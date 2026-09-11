"""依設定挑 DB backend。"""

from __future__ import annotations

from typing import Optional

from app.analytics.local_db import LocalDB
from app.config import Settings


def get_db(settings: Optional[Settings] = None):
    """`DB_BACKEND=hotdata` 回 HotdataClient，否則回 LocalDB（預設）。"""
    settings = settings or Settings.from_env()
    if settings.DB_BACKEND == "hotdata":
        from app.analytics.hotdata_client import HotdataClient

        return HotdataClient(settings)
    db = LocalDB()
    db.init_schema()
    return db
