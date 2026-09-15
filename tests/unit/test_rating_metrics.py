"""Phase 53：評分與負面回饋指標（`training_kb.analytics.ratings`）。

自含 fixture 重現設計 §11.2 的 2.875／4.4／8／2；不連 AWS、不呼叫模型。
`APPROVED` 是測試自備的核定類別集合（不 import Phase 43 的名稱），
所以 Phase 43 是否落地都不影響本檔。
"""

import pytest

from training_kb.analytics.ratings import average_rating, format_average
from training_kb.models import Feedback

V1 = "prepare-meeting@v1"
V2 = "prepare-meeting@v2"


def fb(fid, rating, category=None, version=V1):
    """建一筆 Feedback；`carries_signal` 要求 rating／category／comment 至少一項。"""
    return Feedback(
        id=fid,
        tutorial_version=version,
        rating=rating,
        category=category,
        comment=None,
        user=f"u_{fid}",
        ts=None,
    )


def test_average_rating_reproduces_design_v1_and_v2():
    """Given 設計 §11.2 的八筆與十筆回饋，When 逐版取平均，Then 得到 2.875 與 4.4。"""
    v1 = [
        fb("f_12", 2),
        fb("f_15", 2),
        fb("f_19", 3),
        fb("f_23", 3),
        fb("f_27", 3),
        fb("f_31", 3),
        fb("f_34", 3),
        fb("f_40", 4),
    ]
    v2 = [fb("f_101", 2, version=V2), fb("f_102", 2, version=V2)]
    v2 += [fb(f"f_{n}", 5, version=V2) for n in range(103, 111)]
    assert average_rating(v1) == pytest.approx(2.875)
    assert average_rating(v2) == pytest.approx(4.4)
    assert format_average(average_rating(v1)) == "2.9"


def test_average_rating_without_any_rating_is_none_not_zero():
    """Given 沒有任何有效評分，When 取平均，Then 回 None 並顯示「尚無評分」，不是 0.0。"""
    assert average_rating([]) is None
    assert average_rating([fb("f_1", None, "待分類"), fb("f_2", None, "待分類")]) is None
    assert format_average(None) == "尚無評分"
