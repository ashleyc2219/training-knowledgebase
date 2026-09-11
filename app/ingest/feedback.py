"""顧客 Feedback 寫入（Phase 4）。

對齊 `docs/spec/features/收集Feedback.feature` 的 7 條 Rule：
驗證不過一律 `OperationFailed`（規格的 `Then 操作失敗`），**一列都不寫**。

CLI（🖐️ 手動匯入種子）：
    uv run python -m app.ingest.feedback --file data/seed/feedback_seed.json
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from app.agent.rules import validate_feedback
from app.errors import OperationFailed

INSERT_FEEDBACK = """
INSERT INTO Feedback
    (id, tutorial_id, tutorial_version, rating, feedback_category, comment, submitter_id, timestamp)
VALUES
    (:id, :tutorial_id, :tutorial_version, :rating, :feedback_category, :comment, :submitter_id, :timestamp)
"""

NEXT_ID = "SELECT COALESCE(MAX(id), 0) + 1 AS next_id FROM Feedback"

CURRENT_VERSION = "SELECT current_version FROM Tutorial WHERE tutorial_id = :tutorial_id"

VERSION_EXISTS = """
SELECT 1 AS found FROM TutorialVersion
WHERE tutorial_id = :tutorial_id AND tutorial_version = :tutorial_version
"""


def _current_version(db, tutorial_id) -> str:
    """未指定 tutorial_version 時綁定 Tutorial.current_version（Rule: Feedback 參照 TutorialVersion）。"""
    rows = db.run_sql(CURRENT_VERSION, {"tutorial_id": tutorial_id})
    if not rows or not rows[0].get("current_version"):
        raise OperationFailed(f"找不到 Tutorial {tutorial_id} 的 current_version")
    return str(rows[0]["current_version"])


def collect_feedback(db, payload: dict) -> int:
    """寫入一筆 Feedback，回傳 feedback_id；任一條 Rule 不過即 `OperationFailed`。"""
    tutorial_id = payload.get("tutorial_id")
    if tutorial_id in (None, ""):
        raise OperationFailed("Feedback 缺少必填欄位：tutorial_id")

    data = dict(payload)
    if not data.get("tutorial_version"):
        data["tutorial_version"] = _current_version(db, tutorial_id)

    row = validate_feedback(data)

    if not db.run_sql(VERSION_EXISTS, {
        "tutorial_id": row["tutorial_id"],
        "tutorial_version": row["tutorial_version"],
    }):
        raise OperationFailed(
            f"找不到對應的 TutorialVersion：{row['tutorial_id']} {row['tutorial_version']}"
        )

    row["id"] = int(db.run_sql(NEXT_ID)[0]["next_id"])
    db.execute(INSERT_FEEDBACK, row)
    return row["id"]


def seed_feedback(db, path) -> int:
    """匯入種子回饋 JSON（list[dict]），回傳成功寫入的筆數。失敗的列只略過，不中斷。"""
    rows = json.loads(Path(path).read_text(encoding="utf-8"))
    ok = 0
    for item in rows:
        try:
            collect_feedback(db, item)
            ok += 1
        except OperationFailed as exc:
            print(f"  ! 略過：{exc}")
    return ok


def main(argv: Optional[list[str]] = None) -> None:
    """`python -m app.ingest.feedback --file <seed.json>`。"""
    import argparse

    from app.analytics.db import get_db
    from app.analytics import metrics

    parser = argparse.ArgumentParser(description="匯入 Feedback 種子資料")
    parser.add_argument("--file", required=True, help="種子 JSON 路徑")
    args = parser.parse_args(argv)

    db = get_db()
    total = len(json.loads(Path(args.file).read_text(encoding="utf-8")))
    ok = seed_feedback(db, args.file)
    print(f"匯入完成：{ok}/{total} 筆")
    metrics.append_history(metrics.snapshot(db))


if __name__ == "__main__":  # pragma: no cover - CLI
    main()
