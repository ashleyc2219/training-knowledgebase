"""評分與負面回饋指標（Phase 53）。

四個純函式，輸入原始 `Feedback`，輸出可重算的數值與 ID 集合：不讀 DynamoDB、
不呼叫模型、不判規則狀態。讀取由 `Repository.list_feedback_of_version` 負責，
規則狀態的寫入由 Phase 55 負責。

`average_rating` 與 `cross_version_average` 回**未四捨五入**的浮點數，門檻比較
（例如 Phase 44 的 `is_weak`）一律吃這個值；只有 `format_average` 產生顯示字串。
"""

from collections.abc import Iterable, Sequence
from decimal import ROUND_HALF_UP, Decimal

from training_kb.models import Feedback

NO_RATING_DISPLAY = "尚無評分"


def average_rating(feedback: Iterable[Feedback]) -> float | None:
    """單一版本的平均評分；分母是**有評分**的筆數（00A D-44）。

    `rating is None` 不進分子也不進分母；一筆有效評分都沒有時回 `None`，
    不是 `0.0`（設計 §12.1「無評分為 null，顯示尚無評分；不當成 0 分」）。
    """
    ratings = [item.rating for item in feedback if item.rating is not None]
    if not ratings:
        return None
    return sum(ratings) / len(ratings)


def format_average(value: float | None) -> str:
    """顯示用字串：一位小數、`ROUND_HALF_UP`；`None` 顯示「尚無評分」。

    2.875 剛好落在 2.8 與 2.9 中間，設計 §11.2 要求顯示 2.9，所以策略必須釘死。
    先轉 `str` 再進 `Decimal`，否則會拿到二進位誤差版本而得到 2.8。
    """
    if value is None:
        return NO_RATING_DISPLAY
    quantized = Decimal(str(value)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    return str(quantized)


def cross_version_average(values: Sequence[float | None]) -> float | None:
    """跨版平均：每一版**權重相同**，不是把所有回饋混成一池加權（設計 §12.1）。

    輸入是每版已算好的平均；`None` 代表那一版沒有可比較的評分，直接略過，
    全部都是 `None`（或空序列）時回 `None`。
    """
    present = [value for value in values if value is not None]
    if not present:
        return None
    return sum(present) / len(present)
