"""RocketRide（Motion / 協調層）客戶端。

角色（showme §3.4 design decision）：**本機為主、RocketRide 為決策展示**。
本檔任何失敗都不得影響票流 —— `run_agent` 永不 raise，失敗回 None。

協定（`{ROCKETRIDE_URI}/openapi.json` 與 https://docs.rocketride.org/protocols/websocket 實查 2026-09-11）：
    POST   /task?trace=…      body = pipeline JSON      → {"data": {"token": "tk_…"}}   啟動一個 task
    POST   /webhook?token=tk_… body = 事件 JSON          → {"data": {"objectsCompleted": 1}}  餵資料進 task
    GET    /task?token=tk_…                             → task 狀態（含 project_id、errors）
    DELETE /task?token=tk_…                             → 結束 task
    header `authorization: Bearer <APIKEY>` 為必填。
    Agent 的 answers lane 只能從 WebSocket（`/task/service`）讀，REST 沒有對應端點；
    demo 只需要 fire-and-forget 的鏡射，所以本檔只用 REST。

憑證分組（`.env` 註解硬規定）：run / 驗證 / 迭代用 `ROCKETRIDE_URI` / `ROCKETRIDE_APIKEY`；
deploy / schedules / publishApp 只能用 `ROCKETRIDE_DEPLOY_*`，本檔不自動 deploy。
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv

from app.agent.llm import LLMUnavailable

PIPELINE_PATH = Path(__file__).with_name("pipeline.json")
TASK_STATE_PATH = Path(".state/rocketride_task.json")
DEFAULT_TIMEOUT = 3.0

load_dotenv()


def _conn() -> tuple[Optional[str], Optional[str]]:
    """dev 連線（run / 驗證 / 迭代專用）。"""
    uri = (os.getenv("ROCKETRIDE_URI") or "").rstrip("/") or None
    return uri, (os.getenv("ROCKETRIDE_APIKEY") or None)


def _headers(apikey: str) -> dict[str, str]:
    return {"Content-Type": "application/json", "authorization": f"Bearer {apikey}"}


def _request(method: str, path: str, body: Any = None, timeout: float = DEFAULT_TIMEOUT):
    uri, apikey = _conn()
    if not (uri and apikey):
        return None
    import httpx  # 延遲匯入：單元測試不需要網路

    resp = httpx.request(
        method,
        f"{uri}{path}",
        json=body,
        headers=_headers(apikey),
        timeout=timeout,
    )
    if resp.status_code >= 400:
        return None
    try:
        return resp.json()
    except ValueError:
        return {"raw": resp.text[:500]}


def _load_token() -> Optional[str]:
    if os.getenv("ROCKETRIDE_TASK_TOKEN"):
        return os.getenv("ROCKETRIDE_TASK_TOKEN")
    if not TASK_STATE_PATH.exists():
        return None
    try:
        return json.loads(TASK_STATE_PATH.read_text(encoding="utf-8")).get("token")
    except (json.JSONDecodeError, OSError):
        return None


def _save_token(token: str) -> None:
    TASK_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    TASK_STATE_PATH.write_text(json.dumps({"token": token}), encoding="utf-8")


def start_task(timeout: float = 15.0) -> Optional[str]:
    """把 `app/agent/pipeline.json` 送上 dev 連線跑起來，回傳 task token（失敗回 None）。"""
    try:
        pipeline = json.loads(PIPELINE_PATH.read_text(encoding="utf-8"))
        body = _request("POST", "/task", pipeline, timeout=timeout)
        token = ((body or {}).get("data") or {}).get("token")
        if token:
            _save_token(token)
        return token
    except Exception:  # noqa: BLE001 — 展示層失敗不影響票流
        return None


def task_status(token: Optional[str] = None, timeout: float = DEFAULT_TIMEOUT) -> Optional[dict]:
    """讀 task 狀態（中欄用來顯示 Agent 是否在跑）。"""
    token = token or _load_token()
    if not token:
        return None
    try:
        body = _request("GET", f"/task?token={token}", timeout=timeout)
        return (body or {}).get("data")
    except Exception:  # noqa: BLE001
        return None


def stop_task(token: Optional[str] = None) -> None:
    """收工時結束 task；失敗忽略。"""
    token = token or _load_token()
    if not token:
        return
    try:
        _request("DELETE", f"/task?token={token}")
    except Exception:  # noqa: BLE001
        pass
    TASK_STATE_PATH.unlink(missing_ok=True)


def run_agent(event: dict, timeout: float = DEFAULT_TIMEOUT) -> Optional[dict]:
    """把事件送給 RocketRide Agent（fire-and-forget）。永不 raise；失敗回 None。

    沒有 task token 時自動 `start_task()` 一次；webhook 收下資料即算成功。
    Agent 的文字回覆走 WebSocket lane，本函式不等它 —— 中欄只顯示「已送達 Agent」。
    """
    if not all(_conn()):
        return None
    try:
        token = _load_token() or start_task()
        if not token:
            return None
        body = _request("POST", f"/webhook?token={token}", event, timeout=timeout)
        if body is None:  # token 過期／task 已結束 → 重開一次
            TASK_STATE_PATH.unlink(missing_ok=True)
            token = start_task()
            if not token:
                return None
            body = _request("POST", f"/webhook?token={token}", event, timeout=timeout)
        if body is None:
            return None
        data = body.get("data") if isinstance(body, dict) else None
        return {
            "delivered": bool((data or {}).get("objectsCompleted")),
            "token": token,
            "data": data,
        }
    except Exception:  # noqa: BLE001
        return None


def call_llm(prompt: str, schema_hint: str) -> str:
    """provider 鏈第一棒。

    現況：RocketRide REST 只能餵資料進 task，Agent 的 answers lane 要走 WebSocket
    （`/task/service`），Phase 2 不實作。所以這裡一律 `LLMUnavailable`，
    讓 `app/agent/llm.py` 往下掉到 Anthropic API，再不行由呼叫端走模板降級。
    """
    raise LLMUnavailable(
        "RocketRide REST 只能送事件；Agent answers lane 需 WebSocket 協定（Phase 2 未實作）"
    )


def deploy_pipeline(*_args: Any, **_kwargs: Any):
    """本專案不自動 deploy。"""
    raise NotImplementedError(
        "🖐️ 手動：只用 ROCKETRIDE_DEPLOY_* 在 console deploy（.env 註解：never deploy to the dev connection）"
    )
