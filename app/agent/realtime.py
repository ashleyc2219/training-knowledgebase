"""即時路徑：open 票 → 匹配 UserProblem → deflected 或 escalated。

對齊 `docs/spec/features/自動回覆顧客.feature`（五條 Rule）與 `輪詢新票單.feature`。
門檻判斷在 `app/agent/rules.classify_ticket`（純函式，本檔只負責 I/O 與寫回）。

失敗語意（showme §7.1／§14）：任何讀寫例外 → `OperationFailed`，票維持 open，本輪不進分析。
本機為主（唯一寫 Ticket.status 的地方）；RocketRide 只做決策展示，fire-and-forget，絕不影響票流。
"""

from __future__ import annotations

from typing import Any, Optional

from app.agent import rules
from app.errors import OperationFailed
from app.muscle import rote_client

SELECT_TICKET = "SELECT * FROM Ticket WHERE id = :id"

# retired / draft 自然被排除（自動回覆顧客 Rule 4）
SELECT_PUBLISHED_TUTORIAL = """
SELECT tutorial_id, current_version
FROM Tutorial
WHERE user_problem_id = :user_problem_id AND status = 'published'
LIMIT 1
"""

# ERM 不變條件：reopened_from_ticket_id 指向的票 status 必須為 deflected
SELECT_PRIOR_DEFLECTED = """
SELECT id
FROM Ticket
WHERE customer_ref = :customer_ref
  AND user_problem_id = :user_problem_id
  AND status = 'deflected'
  AND id <> :id
ORDER BY created_at DESC, id DESC
LIMIT 1
"""

UPDATE_TICKET_DEFLECTED = """
UPDATE Ticket
SET status = 'deflected',
    deflected_tutorial_id = :tutorial_id,
    deflected_tutorial_version = :tutorial_version,
    reopened_from_ticket_id = NULL
WHERE id = :id
"""

UPDATE_TICKET_ESCALATED = """
UPDATE Ticket
SET status = 'escalated',
    deflected_tutorial_id = NULL,
    deflected_tutorial_version = NULL,
    reopened_from_ticket_id = :reopened_from_ticket_id
WHERE id = :id
"""

UPDATE_TICKET_RESOLVED = """
UPDATE Ticket
SET status = 'resolved',
    resolution_steps = :resolution_steps
WHERE id = :id
"""


def _one(rows: list[dict]) -> Optional[dict]:
    return rows[0] if rows else None


def handle_open_ticket(db, ticket_id: int, rote: Any = None) -> dict:
    """對一張 open 票跑即時路徑，回傳決策結果 dict。

    自動回覆顧客.feature：
      Rule 1 有 published Tutorial → deflected（寫 deflected_tutorial_id / _version）
      Rule 2 沒有 published Tutorial → escalated
      Rule 3 user_problem_id 為空 → escalated
      Rule 4 Tutorial 為 retired 視同沒有 → escalated
      Rule 5 同顧客同 UserProblem 再開票 → escalated ＋ reopened_from_ticket_id
    """
    try:
        ticket = _one(db.run_sql(SELECT_TICKET, {"id": ticket_id}))
        if ticket is None:
            raise OperationFailed(f"找不到 Ticket {ticket_id}")
        if ticket["status"] != "open":
            raise OperationFailed(
                f"Ticket {ticket_id} 目前為 {ticket['status']}，即時路徑只處理 open 票"
            )

        up_id = ticket["user_problem_id"]
        has_up = up_id not in (None, "", 0)

        reopen_id = None
        published = None
        if has_up:
            reopen = _one(
                db.run_sql(
                    SELECT_PRIOR_DEFLECTED,
                    {
                        "customer_ref": ticket["customer_ref"],
                        "user_problem_id": up_id,
                        "id": ticket_id,
                    },
                )
            )
            reopen_id = reopen["id"] if reopen else None
            published = _one(
                db.run_sql(SELECT_PUBLISHED_TUTORIAL, {"user_problem_id": up_id})
            )

        decision = rules.classify_ticket(
            has_user_problem=has_up,
            has_published_tutorial=published is not None,
            is_reopen=reopen_id is not None,
        )

        if decision == "deflected":
            db.execute(
                UPDATE_TICKET_DEFLECTED,
                {
                    "id": ticket_id,
                    "tutorial_id": published["tutorial_id"],
                    "tutorial_version": published["current_version"],
                },
            )
        else:
            db.execute(
                UPDATE_TICKET_ESCALATED,
                {"id": ticket_id, "reopened_from_ticket_id": reopen_id},
            )
    except OperationFailed:
        raise
    except Exception as exc:  # noqa: BLE001 — 規格的「操作失敗」：票維持 open
        raise OperationFailed(f"即時路徑失敗，Ticket {ticket_id} 維持 open：{exc}") from exc

    result: dict[str, Any] = {
        "ticket_id": ticket_id,
        "status": decision,
        "reason": _reason(has_up, reopen_id, published),
        "user_problem_id": up_id if has_up else None,
        "tutorial_id": published["tutorial_id"] if published else None,
        "tutorial_version": published["current_version"] if published else None,
        "reopened_from_ticket_id": reopen_id,
    }

    # Muscle memory：第一次成功攔截捕捉 Workflow，之後 replay_count + 1（Phase 3 換真 Rote）
    if decision == "deflected":
        muscle = rote or rote_client
        try:
            result.update(muscle.on_deflected(db, ticket_id, up_id))
        except Exception as exc:  # noqa: BLE001 — Rote 不在成功邊界上
            result["rote_error"] = str(exc)

    result["agent_echo"] = _mirror_to_rocketride(ticket, result)
    return result


def resolve_ticket(db, ticket_id: int, resolution_steps: str) -> dict:
    """轉真人結案：escalated → resolved，並寫入真人確認過的 resolution_steps。"""
    if not (resolution_steps or "").strip():
        raise OperationFailed("resolution_steps 不得為空")
    try:
        ticket = _one(db.run_sql(SELECT_TICKET, {"id": ticket_id}))
        if ticket is None:
            raise OperationFailed(f"找不到 Ticket {ticket_id}")
        if ticket["status"] != "escalated":
            raise OperationFailed(
                f"Ticket {ticket_id} 目前為 {ticket['status']}，只有 escalated 的票能結案"
            )
        db.execute(
            UPDATE_TICKET_RESOLVED,
            {"id": ticket_id, "resolution_steps": resolution_steps},
        )
    except OperationFailed:
        raise
    except Exception as exc:  # noqa: BLE001
        raise OperationFailed(f"結案失敗，Ticket {ticket_id} 維持原狀態：{exc}") from exc
    return {"ticket_id": ticket_id, "status": "resolved"}


def _reason(has_up: bool, reopen_id: Optional[int], published: Optional[dict]) -> str:
    if not has_up:
        return "no_user_problem"
    if reopen_id is not None:
        return "reopened"
    if published is None:
        return "no_published_tutorial"
    return "published_tutorial"


def _mirror_to_rocketride(ticket: dict, result: dict) -> Optional[dict]:
    """把決策鏡射給 RocketRide Agent 展示用；永不影響票流（showme §3.4）。"""
    try:
        from app.agent import rocketride_client

        return rocketride_client.run_agent(
            {
                "event": "ticket_open",
                "ticket_id": result["ticket_id"],
                "customer_ref": ticket.get("customer_ref"),
                "content": ticket.get("content"),
                "user_problem_id": result["user_problem_id"],
                "local_decision": result["status"],
                "local_reason": result["reason"],
            }
        )
    except Exception:  # noqa: BLE001 — 展示層失敗只是少一行
        return None
