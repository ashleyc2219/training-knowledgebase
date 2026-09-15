"""Phase 44 的純函式層：弱教學三條件門檻（`REV` Rule 2、3、4）與同類平手順序。

這一支只測不碰 DynamoDB 的兩個函式：`is_weak`（三條件 AND × formal／demo 兩種樣本數門檻）
與 module-private 的 `_top_category`（只數核定類別、平手時固定贏家）。走真實查詢路徑的
選取行為在 `tests/integration/test_weak_targets.py`。

Demo 的 `n >= 8` 是**明示隔離**的展示門檻（設計 §19.2 F20）；O7 未核定前不得把 demo 命中
說成正式門檻已滿足。
"""

from datetime import UTC, datetime

import pytest

from training_kb.config import Thresholds
from training_kb.errors import PermanentError
from training_kb.models import Feedback
from training_kb.pipelines.feedback import _average, _top_category, is_weak

TH = Thresholds()
NOW = datetime(2026, 9, 14, tzinfo=UTC)
APPROVED = frozenset({"找不到按鈕", "缺少資訊"})
PENDING = "待分類"
"""Phase 43 的 `PENDING_CATEGORY`；它不在核定類別表裡，所以不必特別判斷就被擋掉。"""


def fb(feedback_id: str, category: str | None, *, rating: int | None = 2) -> Feedback:
    """一筆回饋；`rating=None` 時仍有 `comment`，才過得了 D-66 的 `carries_signal`。"""
    return Feedback(id=feedback_id, tutorial_version="prepare-meeting@v1", rating=rating,
                    category=category, comment="按鈕在哪", user="u_01", ts=NOW)


@pytest.mark.parametrize(
    ("avg", "n", "top", "mode", "expected"),
    [
        (2.875, 10, 5, "formal", True),
        (2.875, 9, 5, "formal", False),
        (2.875, 8, 5, "demo", True),
        (2.875, 7, 5, "demo", False),
        (3.49, 10, 5, "formal", True),
        (3.5, 10, 5, "formal", False),
        (2.875, 10, 4, "formal", False),
        (2.875, 8, 8, "formal", False),
        (None, 10, 5, "formal", False),
    ],
)
def test_weak_thresholds(avg: float | None, n: int, top: int, mode: str,
                         expected: bool) -> None:
    """Given 一組（平均、樣本數、同類筆數）與 mode，When 判斷弱教學，Then 三條件同時成立才命中。

    邊界逐條對應 `REV` Rule 2（3.49／3.5，未四捨五入）、Rule 3（formal 9／10、demo 7／8）、
    Rule 4（同類 4／5）；`avg is None`（零評分）一律不命中，不得當成 0 分。
    """
    assert is_weak(avg, n, top, mode=mode, thresholds=TH) is expected


def test_unknown_mode_is_rejected_instead_of_defaulting() -> None:
    """Given 不認得的 mode，When 呼叫 `is_weak`，Then 丟 `PermanentError` 而不是預設成 formal。"""
    with pytest.raises(PermanentError, match="mode"):
        is_weak(2.0, 20, 9, mode="loose", thresholds=TH)


def test_thresholds_come_from_config_not_from_literals() -> None:
    """Given 一份把門檻全部調寬的 `Thresholds`，When 判斷，Then 結果跟著設定走。

    這條就是「門檻不得寫死在判斷式裡」的直接證據（00A §5.4）：原本不命中的
    (avg 4.0, n 3, 同類 2) 在寬鬆設定下必須命中。
    """
    loose = Thresholds(weak_average=4.5, production_feedback=3, recurring_category=2)
    assert is_weak(4.0, 3, 2, mode="formal", thresholds=loose) is True
    assert is_weak(4.0, 3, 2, mode="formal", thresholds=TH) is False


def test_tie_break_prefers_the_smaller_category_name() -> None:
    """Given 兩個核定類別各五筆、筆數多的那一類排在清單後面，When 取同類，Then 取名稱升序者。

    「缺少資訊」刻意排在前面：依 dict 插入順序挑贏家的實作一定會回它，紅燈才不是碰運氣。
    """
    rows = [fb(f"f_{index}", "缺少資訊") for index in range(1, 6)]
    rows += [fb(f"f_{index}", "找不到按鈕") for index in range(6, 11)]
    assert _top_category(rows, APPROVED)[0] == "找不到按鈕"


def test_more_feedback_beats_the_smaller_category_name() -> None:
    """Given 名稱較大的類別多一筆，When 取同類，Then 筆數優先於名稱升序。"""
    rows = [fb(f"f_{index}", "找不到按鈕") for index in range(1, 6)]
    rows += [fb(f"f_{index}", "缺少資訊") for index in range(6, 12)]
    category, ids = _top_category(rows, APPROVED)
    assert (category, len(ids)) == ("缺少資訊", 6)


def test_pending_and_unclassified_feedback_never_counts() -> None:
    """Given 八筆 `待分類` 與 `None`，When 取同類，Then 回 `("", ())`：兩者都不是核定類別。"""
    rows = [fb(f"p_{index}", PENDING) for index in range(1, 6)]
    rows += [fb(f"n_{index}", None) for index in range(1, 4)]
    assert PENDING not in APPROVED
    assert _top_category(rows, APPROVED) == ("", ())


def test_same_feedback_read_twice_does_not_inflate_the_count() -> None:
    """Given 同一個 Feedback ID 出現兩次，When 取同類，Then 只算一筆且輸出已排序去重。"""
    rows = [fb("f_15", "找不到按鈕"), fb("f_15", "找不到按鈕"), fb("f_12", "找不到按鈕")]
    assert _top_category(rows, APPROVED) == ("找不到按鈕", ("f_12", "f_15"))


def test_average_denominator_is_the_rated_feedback_only() -> None:
    """Given 兩筆有評分、一筆沒評分，When 算平均，Then 分母是 2（00A D-44，與 P53 同算法）。"""
    rows = [fb("f_12", "找不到按鈕", rating=2), fb("f_15", "找不到按鈕", rating=4),
            fb("f_19", "找不到按鈕", rating=None)]
    assert _average(rows) == 3.0


def test_average_without_any_rating_is_none_not_zero() -> None:
    """Given 全部沒有評分，When 算平均，Then 回 `None`（零評分不是 0 分，設計 §12.1）。"""
    assert _average([fb("f_12", "找不到按鈕", rating=None)]) is None
    assert _average([]) is None
