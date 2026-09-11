"""共用 LLM 介面（Phase 2 擁有實作；Phase 4／5 只呼叫）。

契約：
    complete_json(prompt, schema_hint) -> dict
provider 鏈：RocketRide（llm 節點，若 ROCKETRIDE_* 可用）→ Ollama（OLLAMA_BASE_URL，預設模型 gemma4:31b）
→ Anthropic API（ANTHROPIC_API_KEY）→ raise LLMUnavailable。
呼叫端（create_tutorial / feedback_review / release_update）必須自備「模板」降級，並在結果標記 source="template"。
hackathon 簡化：不做重試、不做串流。
"""

from __future__ import annotations

import json
import os
from typing import Any


class LLMUnavailable(RuntimeError):
    """沒有可用的 LLM provider（無金鑰或連線失敗）。呼叫端應改走模板降級。"""


def _extract_json(text: str) -> dict[str, Any]:
    """從 LLM 回覆中取出第一個 JSON 物件。"""
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise LLMUnavailable("LLM 回覆不含 JSON")
    return json.loads(text[start : end + 1])


OLLAMA_DEFAULT_MODEL = "gemma4:31b"


def _ollama(prompt: str, schema_hint: str) -> dict[str, Any]:
    """Ollama `/api/chat`（本機 `http://localhost:11434` 或 cloud `https://ollama.com`）。

    - `OLLAMA_BASE_URL` 沒設就視為未啟用（走下一個 provider）。
    - `OLLAMA_API_KEY` 有值時帶 `Authorization: Bearer`（ollama.com cloud 必填；本機可空）。
    - `format={"type":"object"}` 是官方 structured outputs（JSON schema），欄位仍靠 schema_hint 描述。
    官方文件：https://docs.ollama.com/api/chat 、https://docs.ollama.com/cloud
    """
    base_url = (os.getenv("OLLAMA_BASE_URL") or "").rstrip("/")
    if not base_url:
        raise LLMUnavailable("OLLAMA_BASE_URL 未設定")
    import httpx  # 延遲匯入，測試不需要網路

    headers = {"content-type": "application/json"}
    api_key = os.getenv("OLLAMA_API_KEY")
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    try:
        resp = httpx.post(
            f"{base_url}/api/chat",
            headers=headers,
            json={
                "model": os.getenv("OLLAMA_MODEL") or OLLAMA_DEFAULT_MODEL,
                "messages": [
                    {"role": "system", "content": "你只輸出一個 JSON 物件，不要任何其他文字。JSON 形狀：" + schema_hint},
                    {"role": "user", "content": prompt},
                ],
                "stream": False,
                "format": {"type": "object"},
            },
            timeout=120,
        )
    except httpx.HTTPError as exc:
        raise LLMUnavailable(f"Ollama 連線失敗：{exc}") from exc
    if resp.status_code != 200:
        raise LLMUnavailable(f"Ollama API {resp.status_code}")
    data = resp.json()
    text = ((data.get("message") or {}).get("content")) or ""
    return _extract_json(text)


def _anthropic(prompt: str, schema_hint: str) -> dict[str, Any]:
    key = os.getenv("ANTHROPIC_API_KEY")
    if not key:
        raise LLMUnavailable("ANTHROPIC_API_KEY 未設定")
    import httpx  # 延遲匯入，測試不需要網路

    resp = httpx.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            # 模型 id 見 Anthropic Messages API；效能／成本以 .env 的 ANTHROPIC_MODEL 覆寫。
            "model": os.getenv("ANTHROPIC_MODEL", "claude-opus-5"),
            # 現行模型預設開 adaptive thinking，thinking token 也吃 max_tokens；
            # 這裡只要五欄 JSON，effort 壓到 low 讓 demo 快一點。
            "max_tokens": 16000,
            "output_config": {"effort": "low"},
            "system": "你只輸出一個 JSON 物件，不要任何其他文字。JSON 形狀：" + schema_hint,
            "messages": [{"role": "user", "content": prompt}],
        },
        timeout=60,
    )
    if resp.status_code != 200:
        raise LLMUnavailable(f"Anthropic API {resp.status_code}")
    data = resp.json()
    text = "".join(block.get("text", "") for block in data.get("content", []))
    return _extract_json(text)


def complete_json(prompt: str, schema_hint: str) -> dict[str, Any]:
    """依 provider 鏈取得一個 JSON 物件；全部不可用時 raise LLMUnavailable。"""
    errors: list[str] = []
    try:
        from app.agent import rocketride_client  # Phase 2 實作；stub 時可能沒有 call_llm

        call_llm = getattr(rocketride_client, "call_llm", None)
        if call_llm is not None:
            return _extract_json(call_llm(prompt, schema_hint))
    except LLMUnavailable as exc:
        errors.append(f"rocketride: {exc}")
    except Exception as exc:  # noqa: BLE001 - 降級鏈刻意吞掉
        errors.append(f"rocketride: {exc}")
    try:
        return _ollama(prompt, schema_hint)
    except LLMUnavailable as exc:
        errors.append(f"ollama: {exc}")
    try:
        return _anthropic(prompt, schema_hint)
    except LLMUnavailable as exc:
        errors.append(f"anthropic: {exc}")
    raise LLMUnavailable("; ".join(errors) or "no provider")
