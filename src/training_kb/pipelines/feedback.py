"""Feedback Review pipeline（`feedback-review`）。

Owner：Phase 44（弱教學門檻與目標選取）；Phase 45（診斷）、46（REFINE）、47（candidate 規則）、
48（排程流程與 handler）在同一支檔各自追加。00A §3.2。

controller 2026-09-14 預建空殼：讓同一波次的 Phase 只用 Edit 追加各自區段。
"""

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

from training_kb.config import Thresholds
from training_kb.errors import PermanentError
from training_kb.models import Feedback

# ---- Phase 46（owner）：P51 import 同一個，不重新宣告（00A §5.4／§6.9）。 ----
# controller 2026-09-14 預先宣告（值來自 00A §5.4），讓 W2 併行的 P51 不必等 P46。
LEASE_TTL_SECONDS = 120


# ---- Phase 44（owner）：弱教學門檻與目標選取 ----
# 交付 `ReviewMode`、`WeakTarget`、`is_weak`、`select_weak_targets` 與兩個 module-private
# helper（`_average`、`_top_category`）。只讀不寫：不呼叫模型、不建立版本、不判斷證據是否
# 已處理（那是 Phase 46 的 `evidence_fingerprint`）、不算展示指標（Phase 53／54）。

ReviewMode = Literal["formal", "demo"]
"""檢視模式：`formal` 是正式門檻，`demo` 是**明示隔離**的展示門檻（設計 §19.2 F20）。

兩者只差在樣本數（10 vs 8），平均 `< 3.5` 與同類 `>= 5` 完全一樣。任何情況下都不得把
`demo` 的命中結果說成正式門檻已滿足；O7 未核定前 Demo 的回饋仍是待核定合成資料。
"""


def is_weak(avg: float | None, n: int, top_category_count: int, *,
            mode: ReviewMode, thresholds: Thresholds) -> bool:
    """三條件 AND 的弱教學判斷（`REV` Rule 2、3、4；設計 §7.5）。

    - 平均 `< thresholds.weak_average`（3.5），**未四捨五入**：`3.49` 算弱、`3.5` 不算。
    - 樣本數 `n >= production_feedback`（10）；`mode="demo"` 改用 `demo_feedback`（8）。
    - 同一核定類別筆數 `>= recurring_category`（5）。

    `avg is None`（該版一筆評分都沒有）一律回 `False`，**不得**當成 0 分——零評分是「沒有
    訊號」不是「評價最差」（設計 §12.1）。三個門檻數字一律從 `Thresholds` 取，模組裡不留
    第二份字面值（00A §5.4）。未知的 mode 丟 `PermanentError` 而不是默默退回 formal：
    ASL 的 Catch 會把它導向失敗終點，總比用錯門檻挑出一批不該改的教學好。
    """
    if mode not in ("formal", "demo"):
        raise PermanentError(f"未知的 review mode：{mode}（只接受 formal 或 demo）")
    if avg is None:
        return False
    minimum = thresholds.production_feedback if mode == "formal" else thresholds.demo_feedback
    return (avg < thresholds.weak_average and n >= minimum
            and top_category_count >= thresholds.recurring_category)
