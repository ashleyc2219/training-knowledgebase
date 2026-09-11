"""門檻與決策的純函式集合。

本檔**不做任何 I/O**：所有判斷都由呼叫端把查到的數字餵進來。
每個函式的 docstring 直接引用 `docs/spec/features/*.feature` 的 Rule 原文，
門檻數字只在這裡出現一次（`docs/design/showme.md` §15：單元測試對齊臨界 Example）。
"""

from __future__ import annotations

from typing import Optional

from app.errors import OperationFailed

# --- 門檻常數（來源：CLAUDE.md 訊號→動作表、各 .feature Rule） ---

RECURRING_MIN = 3
"""分析SupportTickets.feature：同一 user_problem_id 且至少 3 張 Ticket 才是 recurring topic。"""

REFINE_AVG_LT = 3.5
"""定期優化Tutorial.feature：平均 rating 小於 3.5 才進入 REFINE。"""

REFINE_MIN_COUNT = 3
"""定期優化Tutorial.feature：current_version 的 Feedback 數量必須 >= 3 才進入 REFINE。"""

REFINE_SAME_CATEGORY_MIN = 2
"""定期優化Tutorial.feature：同一 feedback_category 至少 2 筆才存在 recurring complaints。"""

FEEDBACK_CATEGORIES = [
    "指示不清楚",
    "缺少資訊",
    "UI 與 Tutorial 不一致",
    "Tutorial 太長",
    "Tutorial 沒有解決問題",
    "缺少自己的使用情境",
    "其他",
]
"""收集Feedback.feature：feedback_category 允許六類與「其他」，未填存空字串。"""


# --- 分析 Ticket ---


def is_recurring(count: int) -> bool:
    """分析SupportTickets.feature — Rule: 同一 user_problem_id 且至少 3 張 Ticket 才識別為 recurring topic。"""
    return count >= RECURRING_MIN


def has_knowledge_gap(count: int, has_published: bool) -> bool:
    """分析SupportTickets.feature — Rule: 沒有 published Tutorial 的 recurring topic 才識別為 Knowledge Gap。"""
    return is_recurring(count) and not has_published


def decide_analysis_action(count: int, has_published: bool) -> Optional[str]:
    """分析SupportTickets.feature — Rule: Knowledge Gap 的動作為 CREATE／已有 published Tutorial 的動作為 KEEP。

    未達 recurring 門檻時分析結果為空（回 None）。
    """
    if not is_recurring(count):
        return None
    return "KEEP" if has_published else "CREATE"


# --- 自動回覆顧客（即時路徑） ---


def classify_ticket(
    has_user_problem: bool, has_published_tutorial: bool, is_reopen: bool
) -> str:
    """自動回覆顧客.feature — Rule: UserProblem 已有 published Tutorial 時票單為 deflected；
    user_problem_id 為空／沒有 published Tutorial（retired 視同沒有）／同顧客同 UserProblem 再開票 → escalated。
    """
    if not has_user_problem:
        return "escalated"
    if not has_published_tutorial:
        return "escalated"
    if is_reopen:
        return "escalated"
    return "deflected"


# --- 定期 Feedback Review ---


def should_refine(avg: float, count: int, max_same_category: int) -> bool:
    """定期優化Tutorial.feature — Rule: 平均 rating < 3.5 且 Feedback 數量 >= 3 且同一 feedback_category >= 2 筆。"""
    return (
        avg < REFINE_AVG_LT
        and count >= REFINE_MIN_COUNT
        and max_same_category >= REFINE_SAME_CATEGORY_MIN
    )


def decide_review_action(
    avg: float, count: int, max_same_category: int, is_possibly_outdated: bool = False
) -> str:
    """定期優化Tutorial.feature — Rule: 條件成立則 REFINE 並發布新版本，否則 KEEP；
    Rule: is_possibly_outdated 為 true 的 Tutorial 本輪 Review 動作為 KEEP（讓 Release Note 路徑先處理）。
    """
    if is_possibly_outdated:
        return "KEEP"
    return "REFINE" if should_refine(avg, count, max_same_category) else "KEEP"


# --- Release Note ---


def decide_release_action(change_type: str) -> Optional[str]:
    """依ReleaseNote更新Tutorial.feature — Rule: renamed 或 changed → UPDATE；deprecated 或 removed → RETIRE；
    Rule: 出現 new feature 且無對應 Tutorial 時不決定動作（回 None）。

    change_type 不在 erm.dbml 的五個合法值內則操作失敗。
    """
    if change_type in ("renamed", "changed"):
        return "UPDATE"
    if change_type in ("deprecated", "removed"):
        return "RETIRE"
    if change_type == "new":
        return None
    raise OperationFailed(f"未知的 change_type：{change_type}")


def is_duplicate_release(content: str, created_at: str, existing: list[tuple]) -> bool:
    """輪詢ReleaseNote.feature — Rule: 相同 content 與 created_at 已存在時不新增列。"""
    return (content, created_at) in {(c, t) for c, t in existing}


# --- Feedback 驗證 ---


def validate_feedback(payload: dict) -> dict:
    """收集Feedback.feature — Rule: rating 必須為 1 到 5 的整數；
    Rule: Feedback 必須包含 tutorial_id、tutorial_version、rating、timestamp；
    Rule: feedback_category 允許六類與「其他」，未填存空字串；Rule: comment 可空，未填存空字串；
    Rule: submitter_id 可空。

    回傳補好預設值的 dict；任一條件不符則 `OperationFailed`（規格的 `Then 操作失敗`）。
    """
    for field in ("tutorial_id", "tutorial_version", "timestamp"):
        if payload.get(field) in (None, ""):
            raise OperationFailed(f"Feedback 缺少必填欄位：{field}")

    rating = payload.get("rating")
    if isinstance(rating, bool) or not isinstance(rating, int):
        raise OperationFailed("rating 必須為整數")
    if rating < 1 or rating > 5:
        raise OperationFailed("rating 必須介於 1 到 5")

    category = payload.get("feedback_category") or ""
    if category and category not in FEEDBACK_CATEGORIES:
        raise OperationFailed(f"未知的 feedback_category：{category}")

    return {
        "tutorial_id": payload["tutorial_id"],
        "tutorial_version": payload["tutorial_version"],
        "rating": rating,
        "feedback_category": category,
        "comment": payload.get("comment") or "",
        "submitter_id": payload.get("submitter_id") or "",
        "timestamp": payload["timestamp"],
    }


# --- 命名 ---


def tutorial_slug(topic: str) -> str:
    """UserProblem.topic → Tutorial 檔名 slug，例如 cancel_order → cancel-order。"""
    return topic.strip().lower().replace("_", "-").replace(" ", "-")


def next_version(current: Optional[str]) -> str:
    """建立Tutorial.feature：v1 起算；UPDATE / REFINE 產生下一版 v{n+1}。"""
    if not current:
        return "v1"
    return f"v{int(str(current).lstrip('v')) + 1}"
