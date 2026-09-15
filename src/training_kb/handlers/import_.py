"""`training-kb-import` 的 Lambda 入口：維護者用 boto3 `invoke` 餵匯入檔（00A D-56）。

事件形狀固定：

```json
{"kind": "feedback|view|ticket|release", "source": "widget-download", "items": [ ... ]}
```

**逐筆處理、逐筆回結果**：一筆 `rejected` 不影響其他筆，這正是設計 §7.1「指出欄位、
允許修正」（F51）的形狀。`kind` 不在 `IMPORT_KINDS` 內、或 `items` 不是陣列，屬於呼叫
方式錯誤而不是資料錯誤，整個事件丟 `PermanentError`，一筆都不寫。

四個 `kind` 分成兩條路：

```text
feedback / view   ingress.import_feedback / import_view —— 只有程式判斷，零模型、零 Rote、
                  零 Step Functions、零 PROC（設計 §5、§7.1）
ticket / release  純委派 ingress.normalize_then_accept —— 那條路徑才有 Rote 與 StartExecution，
                  本 Phase 不重寫也不改它的語意
```

兩條路的期限不同是刻意的：八秒是公開 webhook 的限制（GitHub 十秒會記失敗），受控匯入
用自己的 `IMPORT_DEADLINE_SECONDS`，與 CDK 的函式逾時同一個數字。

**`ticket`／`release` 會走 Rote，所以受 O6「未核定來源一律 blocked」影響**；
`feedback`／`view` 不建 `RawEvent`、不查 `approved_stable_keys()`，不受它阻擋。
"""

import logging
import os
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from time import monotonic
from typing import Any, cast

from training_kb.config import load_settings
from training_kb.errors import IngressError, PermanentError
from training_kb.ingress import (
    ImportResult,
    import_feedback,
    import_view,
    missing_nonempty_strings,
    normalize_then_accept,
)
from training_kb.pipelines.common import Deps, JSONValue, build_deps

IMPORT_KINDS: tuple[str, ...] = ("feedback", "view", "ticket", "release")
"""handler 接受的四種 `kind`（00A §6.8）；順序只影響錯誤訊息。"""

IMPORT_DEADLINE_SECONDS = 300.0
"""匯入 Lambda 自己的期限，與 webhook 的八秒無關；CDK 的 `IMPORT_TIMEOUT` 由它導出。"""

SOURCE_FIELDS = ("domain", "adapter", "event_type")
"""`ticket`／`release` 每一筆自己要帶的可信入口設定（00A D-60），**不從 payload 反推**。"""

_DEPS: Deps | None = None
"""暖啟動快取：同一個執行環境不重建 boto3 client。測試直接 monkeypatch 它。"""

_log = logging.getLogger(__name__)


def handler(event: dict[str, Any], context: object) -> dict[str, object]:
    """匯入事件 → 逐筆 `ImportResult`（`asdict` 之後就是回應的一列）。

    順序固定成三段，**每一段都做完才進下一段**：

    ```text
    1 事件形狀   kind 在四種內、items 是陣列、每一筆都是物件 -> 否則整批 PermanentError
    2 組相依     確認事件合法之後才連 DynamoDB 與 S3
    3 逐筆寫入   一筆的資料不合法只讓那一筆 rejected，其他筆照做（F51）
    ```

    第 1 段的「每一筆都是物件」刻意**先全部檢查完**（review 修正回合 1）：邊檢查邊寫入的話，
    壞在第 n 筆時前 n-1 筆已經進表了，與「整批 PermanentError，一筆都不寫」矛盾。
    整批的 `deadline` 也在這裡算一次就往下傳（比照 `handlers/github_webhook.py`），
    下游不重新計時。
    """
    global _DEPS
    kind = str(event.get("kind") or "")
    items = event.get("items")
    if kind not in IMPORT_KINDS or not isinstance(items, list):
        raise PermanentError(
            f"匯入事件不合法：kind={event.get('kind')!r}、items 必須是陣列；"
            f"可用的 kind 是 {IMPORT_KINDS}")
    rows = [_item(index, row) for index, row in enumerate(items)]
    deadline = _deadline(context)
    if _DEPS is None:
        _DEPS = build_deps(load_settings(os.environ))
    results = [_import_one(kind, row, _DEPS, deadline) for row in rows]
    _record(kind, event.get("source"), results)
    return {"kind": kind, "source": event.get("source"),
            "results": [asdict(result) for result in results]}


def _record(kind: str, source: object, results: Sequence[ImportResult]) -> None:
    """只記 `kind`、來源標籤、筆數與各狀態的計數；**payload 與訊息一律不進 log**（00A §3.8）。"""
    counts = Counter(result.status for result in results)
    _log.info("import kind=%s source=%s items=%d saved=%d duplicate=%d rejected=%d",
              kind, source, len(results), counts["saved"], counts["duplicate"],
              counts["rejected"])


def _deadline(context: object) -> float:
    """整批共用的絕對期限（`time.monotonic()` 的時刻），進入時算一次。

    真實 Lambda 的 `context.get_remaining_time_in_millis()` 比常數準——它扣掉了冷啟動與
    已經用掉的時間；拿不到（單元測試傳 `None`、或執行環境沒有這個方法）才退回
    `IMPORT_DEADLINE_SECONDS`。取兩者較小的那個，免得 context 回報得比函式逾時還久。
    """
    remaining = getattr(context, "get_remaining_time_in_millis", None)
    if callable(remaining):
        value = remaining()
        if isinstance(value, int | float) and not isinstance(value, bool) and value > 0:
            return monotonic() + min(float(value) / 1000.0, IMPORT_DEADLINE_SECONDS)
    return monotonic() + IMPORT_DEADLINE_SECONDS


def _item(index: int, row: object) -> Mapping[str, object]:
    """batch 的一筆必須是物件；不是的話整批停下來，一筆都不寫（呼叫端先全部檢查完）。"""
    if not isinstance(row, Mapping):
        raise PermanentError(
            f"匯入檔的每一筆都必須是物件：items[{index}] 是 {type(row).__name__}")
    return cast(Mapping[str, object], row)


def _lower_headers(payload: Mapping[str, object]) -> dict[str, str]:
    """header 一律小寫鍵，讓下游（P33 的 `HEADER_PREFIXES`）只要認得一種形狀。"""
    raw = payload.get("headers")
    source: Mapping[Any, Any] = raw if isinstance(raw, Mapping) else {}
    return {str(name).lower(): str(value) for name, value in source.items()}


def _event_payload(payload: Mapping[str, object]) -> Mapping[str, JSONValue]:
    """`ticket`／`release` 的原始事件本體；不是物件就是匯出檔壞了，整筆停下來。"""
    body = payload.get("payload")
    if not isinstance(body, Mapping):
        raise PermanentError("匯入的 payload 必須是物件")
    return cast(Mapping[str, JSONValue], body)


def _import_one(kind: str, payload: Mapping[str, object], deps: Deps,
                deadline: float) -> ImportResult:
    """一筆的分派；四種 `kind` 的**資料**錯誤一律收斂成 `rejected`，不影響同一批的其他筆。

    `feedback`／`view` 由 `ingress` 自己收斂，所以那兩條不用 try；`ticket`／`release`
    的 `IngressError` 是從 `normalize_then_accept` 冒上來的，在這裡轉成同一種
    `rejected` row（review 修正回合 1）。缺 `domain`／`adapter`／`event_type` 不在此列：
    那是匯出檔本身壞了、不是某一筆資料不合法，仍然整批 `PermanentError`（文件 §11）。
    """
    repository, operations = deps.need_repository(), deps.operations
    if kind == "feedback":
        # Phase 43：`writer` 直接讀屬性、**不用** `need_writer()`——沒接線時的語意是
        # 「只收斂勾選值」，不是丟 `PermanentError`。少了這個參數，雲端的匯入 Lambda
        # 永遠不分類留言，CDK 上那條 `bedrock:InvokeModel` 也就白加了。
        return import_feedback(payload, repository=repository, operations=operations,
                               now=deps.now(), writer=deps.writer)
    if kind == "view":
        return import_view(payload, repository=repository, operations=operations,
                           now=deps.now())
    missing = missing_nonempty_strings(payload, SOURCE_FIELDS)
    if missing:
        raise PermanentError(f"{kind} 匯入缺少來源欄位：{missing}")
    try:
        accepted = normalize_then_accept(      # 00A D-60：六個參數全是 keyword
            domain=str(payload["domain"]), adapter=str(payload["adapter"]),
            event_type=str(payload["event_type"]), headers=_lower_headers(payload),
            payload=_event_payload(payload), deadline=deadline)
    except IngressError as error:
        return ImportResult("rejected", None, error.message, error.fields)
    # `normalize_then_accept` 回 **list[Acceptance]**（D-73）：一個 PR 可展開成 n 筆子
    # Release，各自一個 operation。與 P30 的 handler 同口徑：`object_id` 取第一筆，
    # 訊息列出全部 operation ID，不丟掉其餘幾筆。
    message = f"{kind} 已交給 {', '.join(item.operation_id for item in accepted)}"
    canonical_id = accepted[0].record.canonical_id
    if all(item.status == "duplicate" for item in accepted):
        return ImportResult("duplicate", canonical_id, message, ())
    return ImportResult("saved", canonical_id, message, ())
