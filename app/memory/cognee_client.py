"""Cognee（Memory 建構層）：Tickets / Release Notes / Tutorial / Feedback → 實體與關係。

走 REST（httpx），不裝 `cognee` 套件——少一個相依，也跟 RocketRide `tool_cognee` 節點
同一條 HTTP 介面。端點與 payload 形狀對齊本機 Cognee 伺服器：

- `POST /api/v1/remember`  multipart/form-data：
  欄位 `datasetName`、`node_set`、`run_in_background`，檔案欄位 `data`（`<kind>.txt`）
- `POST /api/v1/recall`    JSON：`{query, top_k, only_context, scope, datasets}`
- header：`X-Api-Key`

dataset 固定為 `COGNEE_DATASET`（本專案 `support_tutorials`），**不開 per-call override**
（對齊 `tool_cognee` 的 `allow_dataset_override=false`）。
"""

from __future__ import annotations

import json
from typing import Any, Optional

import httpx

from app.config import Settings
from app.errors import OperationFailed

DEFAULT_DATASET = "support_tutorials"
TIMEOUT = 120.0


class CogneeClient:
    """Cognee REST client。"""

    def __init__(
        self,
        settings: Optional[Settings] = None,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        dataset: Optional[str] = None,
        client: Optional[httpx.Client] = None,
    ) -> None:
        if settings is None and base_url is None:
            settings = Settings.from_env()
        self.base_url = (base_url or (settings.COGNEE_URL if settings else None) or "").rstrip("/")
        self.api_key = api_key or (settings.COGNEE_APIKEY if settings else None)
        self.dataset = (
            dataset or (settings.COGNEE_DATASET if settings else None) or DEFAULT_DATASET
        )
        self._client = client

    def _headers(self) -> dict[str, str]:
        return {"X-Api-Key": self.api_key} if self.api_key else {}

    def _post(self, path: str, **kwargs: Any) -> Any:
        if not self.base_url:
            raise OperationFailed("沒有設定 COGNEE_URL，Cognee 不可用")
        url = f"{self.base_url}{path}"
        client = self._client or httpx.Client(timeout=TIMEOUT)
        try:
            resp = client.post(url, headers=self._headers(), **kwargs)
        except httpx.HTTPError as exc:
            raise OperationFailed(f"Cognee 連線失敗（{path}）：{exc}") from exc
        finally:
            if self._client is None:
                client.close()
        if resp.status_code >= 300:
            raise OperationFailed(f"Cognee {path} 回 HTTP {resp.status_code}")
        try:
            return resp.json()
        except ValueError:
            return {}

    def remember(self, text: str, kind: str, meta: Optional[dict] = None) -> Any:
        """寫入一筆記憶（＝ Cognee 的 add + cognify，背景執行）。

        `kind` 當 node_set；`meta` 序列化後併進文字尾端，讓它也能被檢索到。
        """
        meta = meta or {}
        body = text
        if meta:
            body = f"{text}\n\nmeta: {json.dumps(meta, ensure_ascii=False, sort_keys=True)}"
        return self._post(
            "/api/v1/remember",
            data={
                "datasetName": self.dataset,
                "node_set": kind,
                "run_in_background": "true",
            },
            files={"data": (f"{kind}.txt", body.encode("utf-8"), "text/plain")},
        )

    def recall(self, query: str, top_k: int = 10) -> list[dict]:
        """從知識圖譜取回內容。"""
        out = self._post(
            "/api/v1/recall",
            json={
                "query": query,
                "top_k": top_k,
                "only_context": True,
                "scope": "auto",
                "datasets": [self.dataset],
            },
        )
        if isinstance(out, list):
            return out
        return [out] if out else []


_default: Optional[CogneeClient] = None


def get_client() -> CogneeClient:
    """模組層預設 client（給煙測與 demo 用）。"""
    global _default
    if _default is None:
        _default = CogneeClient()
    return _default


def remember(text: str, kind: str, meta: Optional[dict] = None) -> Any:
    return get_client().remember(text, kind, meta)


def recall(query: str, top_k: int = 10) -> list[dict]:
    return get_client().recall(query, top_k)
