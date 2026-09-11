"""門檻函式單元測試，對齊各 .feature 的臨界 Example。"""

import pytest

from app.agent.rules import (
    FEEDBACK_CATEGORIES,
    classify_ticket,
    decide_analysis_action,
    decide_release_action,
    decide_review_action,
    has_knowledge_gap,
    is_duplicate_release,
    is_recurring,
    next_version,
    should_refine,
    tutorial_slug,
    validate_feedback,
)
from app.errors import OperationFailed


# --- 分析SupportTickets.feature ---


def test_is_recurring_臨界():
    assert is_recurring(2) is False
    assert is_recurring(3) is True


def test_has_knowledge_gap():
    assert has_knowledge_gap(3, True) is False
    assert has_knowledge_gap(3, False) is True
    assert has_knowledge_gap(2, False) is False


def test_decide_analysis_action():
    assert decide_analysis_action(3, False) == "CREATE"
    assert decide_analysis_action(3, True) == "KEEP"
    assert decide_analysis_action(2, False) is None
    assert decide_analysis_action(0, False) is None


# --- 自動回覆顧客.feature（五種情況） ---


def test_classify_ticket_有published教學則deflected():
    assert classify_ticket(True, True, False) == "deflected"


def test_classify_ticket_無user_problem則escalated():
    assert classify_ticket(False, False, False) == "escalated"


def test_classify_ticket_無published教學則escalated():
    assert classify_ticket(True, False, False) == "escalated"


def test_classify_ticket_retired視同沒有教學():
    # retired Tutorial → has_published_tutorial = False
    assert classify_ticket(True, False, False) == "escalated"


def test_classify_ticket_再開票則escalated():
    assert classify_ticket(True, True, True) == "escalated"


# --- 定期優化Tutorial.feature ---


def test_should_refine_臨界():
    assert should_refine(3.4, 3, 2) is True
    assert should_refine(3.5, 3, 2) is False
    assert should_refine(3.4, 2, 2) is False
    assert should_refine(3.4, 3, 1) is False


def test_decide_review_action():
    assert decide_review_action(3.4, 3, 2) == "REFINE"
    assert decide_review_action(4.4, 5, 0) == "KEEP"
    assert decide_review_action(2.9, 10, 4) == "REFINE"


def test_decide_review_action_is_possibly_outdated本輪KEEP():
    assert decide_review_action(3.4, 3, 2, is_possibly_outdated=True) == "KEEP"


# --- 依ReleaseNote更新Tutorial.feature（五種 change_type） ---


def test_decide_release_action():
    assert decide_release_action("renamed") == "UPDATE"
    assert decide_release_action("changed") == "UPDATE"
    assert decide_release_action("deprecated") == "RETIRE"
    assert decide_release_action("removed") == "RETIRE"
    assert decide_release_action("new") is None


def test_decide_release_action_未知類型操作失敗():
    with pytest.raises(OperationFailed):
        decide_release_action("rewritten")


# --- 輪詢ReleaseNote.feature ---


def test_is_duplicate_release():
    existing = [("Cancel Order has been renamed to Cancel Purchase.", "2026-09-11T15:00:00Z")]
    assert is_duplicate_release(
        "Cancel Order has been renamed to Cancel Purchase.", "2026-09-11T15:00:00Z", existing
    ) is True
    assert is_duplicate_release(
        "Cancel Order has been renamed to Cancel Purchase.", "2026-09-12T15:00:00Z", existing
    ) is False
    assert is_duplicate_release("Other note.", "2026-09-11T15:00:00Z", existing) is False
    assert is_duplicate_release("Anything", "2026-09-11T15:00:00Z", []) is False


# --- 收集Feedback.feature ---


def test_validate_feedback_補預設值():
    out = validate_feedback(
        {
            "tutorial_id": 1,
            "tutorial_version": "v1",
            "rating": 3,
            "timestamp": "2026-09-05T09:00:00Z",
        }
    )
    assert out["feedback_category"] == ""
    assert out["comment"] == ""
    assert out["submitter_id"] == ""
    assert out["rating"] == 3


def test_validate_feedback_rating邊界1與5可過():
    for rating in (1, 5):
        out = validate_feedback(
            {
                "tutorial_id": 1,
                "tutorial_version": "v1",
                "rating": rating,
                "timestamp": "2026-09-05T09:00:00Z",
            }
        )
        assert out["rating"] == rating


@pytest.mark.parametrize(
    "payload",
    [
        {"tutorial_id": 1, "tutorial_version": "v1", "rating": 0, "timestamp": "t"},
        {"tutorial_id": 1, "tutorial_version": "v1", "rating": 6, "timestamp": "t"},
        {"tutorial_id": 1, "tutorial_version": "v1", "rating": 3.5, "timestamp": "t"},
        {"tutorial_id": 1, "tutorial_version": "v1", "timestamp": "t"},
        {"tutorial_version": "v1", "rating": 3, "timestamp": "t"},
        {"tutorial_id": 1, "rating": 3, "timestamp": "t"},
        {"tutorial_id": 1, "tutorial_version": "v1", "rating": 3},
        {
            "tutorial_id": 1,
            "tutorial_version": "v1",
            "rating": 3,
            "timestamp": "t",
            "feedback_category": "不存在的類別",
        },
    ],
)
def test_validate_feedback_錯誤一律操作失敗(payload):
    with pytest.raises(OperationFailed):
        validate_feedback(payload)


def test_feedback_categories為七類():
    assert len(FEEDBACK_CATEGORIES) == 7
    assert "指示不清楚" in FEEDBACK_CATEGORIES
    assert FEEDBACK_CATEGORIES[-1] == "其他"


# --- 命名 ---


def test_next_version():
    assert next_version(None) == "v1"
    assert next_version("") == "v1"
    assert next_version("v1") == "v2"
    assert next_version("v2") == "v3"


def test_tutorial_slug():
    assert tutorial_slug("cancel_order") == "cancel-order"
    assert tutorial_slug("track_refund") == "track-refund"
    assert tutorial_slug("change_shipping_address") == "change-shipping-address"
