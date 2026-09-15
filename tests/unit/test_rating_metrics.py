"""Phase 53：評分與負面回饋指標（`training_kb.analytics.ratings`）。

自含 fixture 重現設計 §11.2 的 2.875／4.4／8／2；不連 AWS、不呼叫模型。
`APPROVED` 是測試自備的核定類別集合（不 import Phase 43 的名稱），
所以 Phase 43 是否落地都不影響本檔。
"""

import pytest
from pydantic import ValidationError

from training_kb.analytics.ratings import (
    average_rating,
    cross_version_average,
    format_average,
    negative_feedback_ids,
)
from training_kb.models import Feedback

V1 = "prepare-meeting@v1"
V2 = "prepare-meeting@v2"
# 核定類別表自備，不 import Phase 43 的 DEFAULT_FEEDBACK_CATEGORIES（值相同，但不建相依）。
APPROVED = frozenset({"找不到按鈕", "缺少資訊"})
V1_RATINGS = [
    ("f_12", 2),
    ("f_15", 2),
    ("f_19", 3),
    ("f_23", 3),
    ("f_27", 3),
    ("f_31", 3),
    ("f_34", 3),
    ("f_40", 4),
]


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


def test_cross_version_average_weights_each_version_equally():
    """Given 每版已算好的平均，When 跨版彙總，Then 每版等權，不是依筆數加權。"""
    assert cross_version_average([2.875, 4.4]) == pytest.approx(3.6375)
    assert cross_version_average([2.875, None, 4.4]) == pytest.approx(3.6375)
    assert cross_version_average([None, None]) is None
    assert cross_version_average([]) is None
    # 按筆數加權會得到 (23 + 44) / 18 約 3.7222；等權公式不得等於它
    assert cross_version_average([2.875, 4.4]) != pytest.approx(67 / 18)


def test_negative_ids_union_is_deduplicated_by_feedback_id():
    """Given 八筆同時低分或屬核定類別，When 取負面集合，Then 長度是 8 不是 10。"""
    v1 = [fb(fid, rating, "找不到按鈕") for fid, rating in V1_RATINGS]
    negatives = negative_feedback_ids(v1, APPROVED)
    assert isinstance(negatives, frozenset)
    assert len(negatives) == 8
    assert negatives == frozenset(fid for fid, _ in V1_RATINGS)


def test_negative_ids_skip_unclassified_and_high_rating():
    """Given 「待分類」與 5 分的回饋，When 取負面集合，Then 只留 f_101 與 f_102。"""
    v2 = [fb("f_101", 2, "缺少資訊", V2), fb("f_102", 2, "缺少資訊", V2)]
    v2 += [fb(f"f_{n}", 5, None, V2) for n in range(103, 111)]
    v2.append(fb("f_200", 5, "待分類", V2))
    assert negative_feedback_ids(v2, APPROVED) == frozenset({"f_101", "f_102"})


def test_negative_ids_cover_three_independent_boundaries():
    """Given 三個獨立邊界，When 取負面集合，Then 四個 ID 都在且同筆重複只算一次。"""
    rows = [
        fb("f_301", None, "找不到按鈕"),  # 沒有評分，但類別已核定
        fb("f_302", 2, "待分類"),  # 待分類，但低分條件獨立成立
        fb("f_303", 3, "缺少資訊"),  # 不低分，但類別已核定
        fb("f_304", 1, "缺少資訊"),  # 兩個條件同時命中
    ]
    rows.append(rows[-1])  # 同一筆重複出現
    assert negative_feedback_ids(rows, APPROVED) == frozenset({"f_301", "f_302", "f_303", "f_304"})


def test_rating_true_is_rejected_by_the_model_layer():
    """Given rating=True，When 建立 Feedback，Then Phase 04 模型層擋下，不會被讀成 1 分。"""
    with pytest.raises(ValidationError):
        fb("f_400", True)
