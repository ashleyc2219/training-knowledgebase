"""Phase 2 端到端煙測（sqlite，可重跑）。

劇本：餵 3 張 cancel_order → 各 escalated → 確認解法 resolved → 分析 → CREATE
      → tutorials/cancel-order.md（Step 3 含 Click "Cancel Order"）→ 第 4 張同類票 deflected。

用法：uv run python scripts/phase2_smoke.py
獨立的 `.state/phase2_smoke.db`，不動 demo 用的 `.state/local.db`。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agent import analysis, create_tutorial, realtime  # noqa: E402
from app.analytics.local_db import LocalDB  # noqa: E402
from app.ingest import poll  # noqa: E402

DB_PATH = ".state/phase2_smoke.db"
CURSOR_PATH = Path(".state/phase2_smoke_cursor.json")

TOPICS = [
    ("cancel_order", "Cancel Order"),
    ("track_refund", "Track Refund"),
    ("change_shipping_address", "Change Shipping Address"),
]
FALLBACK_RESOLUTION = (
    "Open the Orders page in your account, select the order you want to stop, "
    'and click "Cancel Order". A confirmation email is sent right away.'
)


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"{'✅' if ok else '❌'} {label}{('：' + detail) if detail else ''}")
    if not ok:
        raise SystemExit(1)


def seed(db: LocalDB) -> None:
    for i, (topic, feature_name) in enumerate(TOPICS, start=1):
        db.execute(
            "INSERT INTO Feature (id, name, status) VALUES (:id, :name, 'active')",
            {"id": i, "name": feature_name},
        )
        db.execute(
            "INSERT INTO UserProblem (id, topic, feature_id) VALUES (:id, :topic, :fid)",
            {"id": i, "topic": topic, "fid": i},
        )


def main() -> None:
    Path(DB_PATH).unlink(missing_ok=True)
    CURSOR_PATH.unlink(missing_ok=True)
    poll.DEMO_CURSOR_PATH = CURSOR_PATH
    db = LocalDB(DB_PATH)
    db.init_schema()
    seed(db)
    print("種子：3 Feature ／ 3 UserProblem")

    # 1. 餵 3 張 cancel_order → 全部 escalated → 確認解法 → resolved
    for _ in range(3):
        fed = poll.feed_next_ticket(db)
        check(f"餵票 #{fed['seq']}（{fed['intent']}）", fed["intent"] == "cancel_order", fed["content"][:48])
        result = realtime.handle_open_ticket(db, fed["ticket_id"])
        check(f"  即時路徑 → {result['status']}", result["status"] == "escalated", result["reason"])
        realtime.resolve_ticket(db, fed["ticket_id"], fed["bitext_response"] or FALLBACK_RESOLUTION)
        row = db.run_sql("SELECT status FROM Ticket WHERE id = :id", {"id": fed["ticket_id"]})[0]
        check("  真人確認解法 → resolved", row["status"] == "resolved")

    # 2. 分析 → CREATE
    actions = analysis.analyze_tickets(db)
    check("分析結果", actions == [{"user_problem_id": 1, "topic": "cancel_order", "action": "CREATE"}], str(actions))

    created = create_tutorial.create_tutorial(db, 1)
    check("CREATE 內容來源", True, created["source"])
    md = Path(created["path"])
    check("tutorials/cancel-order.md 存在", md.exists(), str(md))
    text = md.read_text(encoding="utf-8")
    check('Step 3 含 Click "Cancel Order"', '3. Click "Cancel Order"' in text)

    tut = db.run_sql("SELECT * FROM Tutorial")[0]
    check(
        "Tutorial published v1 CREATE",
        (tut["status"], tut["current_version"], tut["last_action"]) == ("published", "v1", "CREATE"),
        str((tut["status"], tut["current_version"], tut["last_action"])),
    )
    ver = db.run_sql("SELECT * FROM TutorialVersion")[0]
    five = ("title", "problem", "prerequisites", "steps", "expected_outcome")
    check("TutorialVersion v1 五欄皆有值", all((ver[f] or "").strip() for f in five))
    check("v1 的 supersedes_version 為空", not ver["supersedes_version"])

    # 3. 第 4 張同類票 → deflected
    ticket_id = db.execute(
        """
        INSERT INTO Ticket (content, resolution_steps, category, customer_ref, feature_id,
                            user_problem_id, status, created_at)
        VALUES ('I want to cancel purchase 998877', '', 'ORDER', 'carol@example.com', 1, 1, 'open',
                '2026-09-11T23:59:00Z')
        """
    )
    result = realtime.handle_open_ticket(db, ticket_id)
    check("第 4 張同類票 → deflected", result["status"] == "deflected", str(result["tutorial_version"]))
    workflow = db.run_sql("SELECT * FROM Workflow WHERE user_problem_id = 1")
    check("Workflow 已捕捉", len(workflow) == 1, f"replay_count={workflow[0]['replay_count']}")

    print("\nPhase 2 煙測全部通過。")


if __name__ == "__main__":
    main()
