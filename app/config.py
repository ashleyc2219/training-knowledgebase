"""應用設定。

所有外部服務金鑰都從 `.env` 讀取（`.env` 已 git-ignore），不落進 repo、不印出內容。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

from dotenv import load_dotenv


@dataclass
class Settings:
    """外部服務連線設定與 DB backend 選擇。"""

    ROCKETRIDE_URI: Optional[str] = None
    ROCKETRIDE_APIKEY: Optional[str] = None
    ROCKETRIDE_DEPLOY_URI: Optional[str] = None
    ROCKETRIDE_DEPLOY_APIKEY: Optional[str] = None
    HOTDATA_API_KEY: Optional[str] = None
    HOTDATA_DATABASE: Optional[str] = None
    # hotdata instant database 的 SQL catalog 與 schema：查詢要寫三段式
    # `<catalog>.<schema>.<table>`（`hotdata databases create --catalog support --schema public`）。
    HOTDATA_CATALOG: str = "support"
    HOTDATA_SCHEMA: str = "public"
    HYDRADB_URI: Optional[str] = None
    HYDRADB_APIKEY: Optional[str] = None
    HYDRADB_DATABASE: Optional[str] = None
    HYDRADB_COLLECTION: Optional[str] = None
    COGNEE_URL: Optional[str] = None
    COGNEE_APIKEY: Optional[str] = None
    # 本專案自己的 dataset，不要碰記憶插件的 agent_sessions。
    COGNEE_DATASET: str = "support_tutorials"
    ANTHROPIC_API_KEY: Optional[str] = None
    # Ollama：`OLLAMA_BASE_URL` 有值才啟用（本機 http://localhost:11434 或 cloud https://ollama.com）；
    # cloud 要 `OLLAMA_API_KEY`；模型預設 gemma4:31b。空字串一律視為未設定。
    OLLAMA_BASE_URL: Optional[str] = None
    OLLAMA_API_KEY: Optional[str] = None
    OLLAMA_MODEL: str = "gemma4:31b"
    # "hotdata" | "sqlite"；黑客松預設走本機 sqlite，接上 hotdata 後改 env 即可切換。
    DB_BACKEND: str = "sqlite"

    @classmethod
    def from_env(cls) -> "Settings":
        """讀 `.env` 與環境變數；缺的欄位留 None，不報錯。"""
        load_dotenv()
        return cls(
            ROCKETRIDE_URI=os.getenv("ROCKETRIDE_URI"),
            ROCKETRIDE_APIKEY=os.getenv("ROCKETRIDE_APIKEY"),
            ROCKETRIDE_DEPLOY_URI=os.getenv("ROCKETRIDE_DEPLOY_URI"),
            ROCKETRIDE_DEPLOY_APIKEY=os.getenv("ROCKETRIDE_DEPLOY_APIKEY"),
            HOTDATA_API_KEY=os.getenv("HOTDATA_API_KEY"),
            HOTDATA_DATABASE=os.getenv("HOTDATA_DATABASE"),
            HOTDATA_CATALOG=os.getenv("HOTDATA_CATALOG", "support"),
            HOTDATA_SCHEMA=os.getenv("HOTDATA_SCHEMA", "public"),
            HYDRADB_URI=os.getenv("HYDRADB_URI"),
            HYDRADB_APIKEY=os.getenv("HYDRADB_APIKEY"),
            HYDRADB_DATABASE=os.getenv("HYDRADB_DATABASE"),
            HYDRADB_COLLECTION=os.getenv("HYDRADB_COLLECTION"),
            COGNEE_URL=os.getenv("COGNEE_URL"),
            COGNEE_APIKEY=os.getenv("COGNEE_APIKEY"),
            COGNEE_DATASET=os.getenv("COGNEE_DATASET", "support_tutorials"),
            ANTHROPIC_API_KEY=os.getenv("ANTHROPIC_API_KEY"),
            OLLAMA_BASE_URL=os.getenv("OLLAMA_BASE_URL") or None,
            OLLAMA_API_KEY=os.getenv("OLLAMA_API_KEY") or None,
            OLLAMA_MODEL=os.getenv("OLLAMA_MODEL") or "gemma4:31b",
            DB_BACKEND=os.getenv("DB_BACKEND", "sqlite"),
        )
