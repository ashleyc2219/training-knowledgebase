"""`training-kb-webhook` 的 Lambda 入口：GitHub Function URL 的公開接入點。

固定次序（設計 §7.1、§14.1，任何一步往前挪都會破壞 Rule 1 與 Rule 2）：

```text
decode_body -> verify_github_signature -> parse_json -> normalize_then_accept
```

`json.loads` 一定排在 `verify_github_signature` 之後：簽名是用**原始 request bytes**
算的，先解析再重新序列化一定對不上，而且沒驗簽就解析等於讓任何人餵資料進來。
整個 handler 的期限是 `WEBHOOK_DEADLINE_SECONDS`（00A §3.7），進入時算好 `deadline`
一路往下傳，下游不各自重新計時。log 只記 `X-GitHub-Delivery`、`operation_id` 與結果
類型，不得記原始 body、簽名或 secret（00A §3.8）。
"""

import base64
import binascii
import json
import logging
import os
from collections.abc import Mapping
from time import monotonic
from typing import Any

from training_kb.errors import IngressError, PermanentError
from training_kb.ingress import SIGNATURE_HEADER, normalize_then_accept, verify_github_signature

WEBHOOK_DEADLINE_SECONDS = 8.0
"""公開入口的整體期限。GitHub 超過十秒可能把 delivery 記為失敗，而且不會自動重送。"""

SECRET_ENV = "TKB_GITHUB_WEBHOOK_SECRET"
"""共享密鑰只由執行環境提供；**不是** `Settings` 欄位，`load_settings` 不讀它（00A §3.5）。"""

DELIVERY_HEADER = "X-GitHub-Delivery"
"""GitHub 每次投遞的識別碼；這個值可以安全寫進 log 用來追查。"""

GITHUB_DOMAIN = "github.com"
GITHUB_ADAPTERS = {"issues": "github_issue", "pull_request": "github_pr"}  # 00A D-60


_log = logging.getLogger(__name__)


def _record(delivery: str | None, outcome: str, operation_id: str | None) -> None:
    """只記 delivery ID、operation ID 與結果類型（00A §3.8）。

    原始 body、簽名與 secret **一律不進 log**：body 是使用者全文，簽名與 secret 一旦
    落到 CloudWatch 就等於外流。
    """
    _log.info("webhook %s delivery=%s operation=%s", outcome, delivery, operation_id)


def load_secret() -> bytes:
    secret = os.environ.get(SECRET_ENV, "")
    if not secret:
        raise PermanentError(f"{SECRET_ENV} 未設定")
    return secret.encode("utf-8")


def _raw_headers(event: dict[str, Any]) -> Mapping[str, Any]:
    """事件裡的 header 對照表；形狀不對就當成沒有 header，不讓入口直接崩掉。"""
    raw = event.get("headers")
    return raw if isinstance(raw, Mapping) else {}


def lower_headers(event: dict[str, Any]) -> dict[str, str]:
    """一律小寫鍵，讓下游（P33 的 `HEADER_PREFIXES`）只要認得一種形狀。"""
    return {str(key).lower(): str(value) for key, value in _raw_headers(event).items()}


def header(event: dict[str, Any], name: str) -> str | None:
    wanted = name.lower()
    values = [str(value) for key, value in _raw_headers(event).items()
              if str(key).lower() == wanted]
    return values[0] if len(values) == 1 else None  # 兩個同名 header 視為沒有有效簽名


def decode_body(event: dict[str, Any]) -> bytes:
    """還原原始 request bytes；不做 JSON round-trip，一個 byte 都不能改。"""
    raw = event.get("body") or ""
    if not isinstance(raw, str):
        raise IngressError("body 不是字串", ("body",))
    if not event.get("isBase64Encoded"):
        return raw.encode("utf-8")
    try:
        return base64.b64decode(raw, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise IngressError("body 不是合法 base64", ("body",)) from exc


def parse_json(raw: bytes) -> dict[str, Any]:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise IngressError("body 不是合法 JSON", ("body",)) from exc
    if not isinstance(payload, dict):
        raise IngressError("body 不是合法 JSON", ("body",))
    return payload


def handler(event: dict[str, Any], context: object) -> dict[str, object]:
    deadline = monotonic() + WEBHOOK_DEADLINE_SECONDS
    delivery = header(event, DELIVERY_HEADER)
    secret = load_secret()  # 設定錯誤（PermanentError）不轉成使用者輸入錯誤，直接往外丟
    try:
        raw = decode_body(event)
        verify_github_signature(raw, header(event, SIGNATURE_HEADER), secret)
        payload = parse_json(raw)
        headers = lower_headers(event)
        event_type = headers.get("x-github-event", "")
        adapter = GITHUB_ADAPTERS.get(event_type)
        if adapter is None:
            raise IngressError("未支援的 GitHub 事件型別", ("X-GitHub-Event",))
        accepted = normalize_then_accept(domain=GITHUB_DOMAIN, adapter=adapter,
                                         event_type=event_type, headers=headers,
                                         payload=payload, deadline=deadline)
    except IngressError as error:
        _record(delivery, "rejected", None)
        return {"ok": False, "message": str(error), "fields": list(error.fields),
                "operation_id": None}
    except TimeoutError as error:
        _record(delivery, "timeout", None)
        return {"ok": False, "message": str(error), "operation_id": None}
    # F14：一個 PR 改到 n 個功能會展開成 n 筆子 Release，各自一個 operation（裁決 D-73）。
    # `operation_id` 保留第一筆，讓只認單筆的既有消費端行為不變；全部的 ID 在 `operation_ids`。
    operation_ids = [acceptance.operation_id for acceptance in accepted]
    _record(delivery, "accepted", operation_ids[0])
    return {"ok": True, "operation_id": operation_ids[0], "operation_ids": operation_ids}
