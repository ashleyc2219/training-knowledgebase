"""重置 demo：清 .state/、tutorials/*.md，重建 LocalDB schema。

不動 docs/ 與 data/（種子與腳本要留著重跑）。
"""

from __future__ import annotations

import shutil
from pathlib import Path

from app.analytics.local_db import LocalDB

STATE_DIR = Path(".state")
TUTORIALS_DIR = Path("tutorials")


def main() -> None:
    if STATE_DIR.exists():
        shutil.rmtree(STATE_DIR)
        print(f"已刪除 {STATE_DIR}/")

    removed = 0
    for md in TUTORIALS_DIR.glob("*.md"):
        md.unlink()
        removed += 1
    print(f"已刪除 tutorials/*.md（{removed} 個）")

    db = LocalDB()
    db.reset()
    print(f"已重建 LocalDB schema：{db.path}")


if __name__ == "__main__":
    main()
