"""Ticket Analysis pipeline：聚 recurring topic → 找 Knowledge Gap → CREATE / KEEP。

對齊 `docs/spec/features/分析SupportTickets.feature`（九條 Rule）。
門檻在 `app/agent/rules`（`is_recurring` / `decide_analysis_action`），本檔只做 I/O。
"""

from __future__ import annotations

from app.agent import rules
from app.errors import OperationFailed

# Rule：分析只納入 status 為 escalated 或 resolved 的 Ticket
COUNT_TICKETS_BY_USER_PROBLEM = """
SELECT t.user_problem_id AS user_problem_id,
       up.topic          AS topic,
       COUNT(*)          AS ticket_count
FROM Ticket t
JOIN UserProblem up ON up.id = t.user_problem_id
WHERE t.status IN ('escalated', 'resolved')
  AND t.user_problem_id IS NOT NULL
GROUP BY t.user_problem_id, up.topic
ORDER BY t.user_problem_id
"""

SELECT_PUBLISHED_USER_PROBLEMS = """
SELECT user_problem_id FROM Tutorial WHERE status = 'published'
"""


def analyze_tickets(db) -> list[dict]:
    """回傳 `[{'user_problem_id', 'topic', 'action': 'CREATE'|'KEEP'}]`。

    未達 recurring 門檻（< 3 張）不進結果；沒票或聚不起來時回 `[]`。
    """
    try:
        counts = db.run_sql(COUNT_TICKETS_BY_USER_PROBLEM)
        published = {
            row["user_problem_id"] for row in db.run_sql(SELECT_PUBLISHED_USER_PROBLEMS)
        }
    except Exception as exc:  # noqa: BLE001
        raise OperationFailed(f"分析 Ticket 讀取失敗：{exc}") from exc

    actions = []
    for row in counts:
        action = rules.decide_analysis_action(
            int(row["ticket_count"]), row["user_problem_id"] in published
        )
        if action is None:
            continue
        actions.append(
            {
                "user_problem_id": row["user_problem_id"],
                "topic": row["topic"],
                "action": action,
            }
        )
    return actions


def knowledge_gaps(db) -> list[dict]:
    """Knowledge Gap = recurring 且沒有 published Tutorial（動作為 CREATE）。"""
    return [a for a in analyze_tickets(db) if a["action"] == "CREATE"]
