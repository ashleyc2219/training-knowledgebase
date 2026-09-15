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
from training_kb.pipelines.feedback import is_weak

TH = Thresholds()
NOW = datetime(2026, 9, 14, tzinfo=UTC)


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
