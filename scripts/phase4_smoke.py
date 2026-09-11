"""Phase 4 端到端煙霧測試（本機 sqlite，不動 demo 主資料庫）。

流程：published v1 → 匯入 10 筆 v1 低分回饋（avg 2.9）→ Review → REFINE v2
      → 匯入 5 筆 v2 高分回饋（avg 4.4）→ 再 Review（KEEP）→ snapshot。

    uv run python scripts/phase4_smoke.py
"""

from __future__ import annotations

import shutil
from pathlib import Path

from app.agent.feedback_review import review_all
from app.analytics import metrics
from app.analytics.local_db import LocalDB
from app.ingest.feedback import seed_feedback

WORKDIR = Path(".state/phase4_smoke")
MD_PATH = WORKDIR / "cancel-order.md"
HISTORY = WORKDIR / "metrics_history.json"

STEPS_V1 = (
    '1. Open your orders. 2. Select the order. 3. Click "Cancel Order". '
    "4. Confirm cancellation."
)


def _seed_tutorial(db: LocalDB) -> None:
    db.execute("INSERT INTO UserProblem (id, topic) VALUES (1, 'cancel_order')")
    db.execute("INSERT INTO UserProblem (id, topic) VALUES (2, 'track_refund')")
    db.execute(
        "INSERT INTO Tutorial (tutorial_id, feature_id, user_problem_id, path, status,"
        " current_version, is_possibly_outdated, is_obsolete, last_action)"
        " VALUES (1, 1, 1, :path, 'published', 'v1', 0, 0, 'CREATE')",
        {"path": str(MD_PATH)},
    )
    db.execute(
        "INSERT INTO TutorialVersion (tutorial_id, tutorial_version, title, problem,"
        " prerequisites, steps, expected_outcome, reason, supersedes_version, created_at)"
        " VALUES (1, 'v1', 'Cancel Order', 'The customer wants to cancel an existing order.',"
        " 'The customer has an account and an open order.', :steps, 'The order is cancelled.',"
        " '', '', '2026-09-01T10:00:00Z')",
        {"steps": STEPS_V1},
    )
    for status in ("deflected", "deflected", "escalated", "escalated"):
        db.execute(
            "INSERT INTO Ticket (content, status, created_at)"
            " VALUES ('x', :status, '2026-09-05T10:00:00Z')",
            {"status": status},
        )
    db.execute(
        "INSERT INTO Workflow (user_problem_id, steps, captured_at, replay_count)"
        " VALUES (1, 's', '2026-09-05T10:00:00Z', 1)"
    )


def main() -> None:
    if WORKDIR.exists():
        shutil.rmtree(WORKDIR)
    WORKDIR.mkdir(parents=True)

    db = LocalDB(path=str(WORKDIR / "smoke.db"))
    db.init_schema()
    _seed_tutorial(db)
    print("1) 起點：Tutorial 1 published v1")

    n = seed_feedback(db, "data/seed/feedback_seed.json")
    print(f"2) 匯入 v1 回饋 {n} 筆 → avg_rating = {metrics.avg_rating(db, 1)}")
    metrics.append_history(metrics.snapshot(db), HISTORY)

    for r in review_all(db):
        print(f"3) Review：{r['action']} {r['from_version']} -> {r['to_version']}"
              f"｜{r['reason']}（{r['source']}）")
    metrics.append_history(metrics.snapshot(db), HISTORY)
    print(f"   current_version = {db.run_sql('SELECT current_version FROM Tutorial')[0]}")
    print(f"   {MD_PATH} 尾巴：{MD_PATH.read_text(encoding='utf-8').strip().splitlines()[-1]}")

    n = seed_feedback(db, "data/seed/feedback_v2_seed.json")
    print(f"4) 匯入 v2 回饋 {n} 筆 → avg_rating = {metrics.avg_rating(db, 1)}")

    for r in review_all(db):
        print(f"5) 再 Review：{r['action']}（{r['reason']}）")

    point = metrics.append_history(metrics.snapshot(db), HISTORY)[-1]
    print(f"6) snapshot = {point}")
    print(f"   歷史點數 = {len(metrics.load_history(HISTORY))}")


if __name__ == "__main__":
    main()
