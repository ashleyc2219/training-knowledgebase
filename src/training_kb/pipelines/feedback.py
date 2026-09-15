"""Feedback Review pipeline（`feedback-review`）。

Owner：Phase 44（弱教學門檻與目標選取）；Phase 45（診斷）、46（REFINE）、47（candidate 規則）、
48（排程流程與 handler）在同一支檔各自追加。00A §3.2。

controller 2026-09-14 預建空殼：讓同一波次的 Phase 只用 Edit 追加各自區段。
"""

from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from training_kb.config import Thresholds
from training_kb.errors import PermanentError
from training_kb.models import Feedback
from training_kb.repository import Repository
from training_kb.writing.client import Writer
from training_kb.writing.prompts import prompt_diagnose_weak
from training_kb.writing.schemas import WeakDiagnosis

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


# ---- Phase 47 ----
# Candidate 規則提出與溯源：`MIN_CANDIDATE_FEEDBACK`、`PROPOSE_NODE`、`CandidateGroup`、
# `candidate_groups`、`candidate_rule_id`、`propose_candidate` 與三個 module-private helper。
# 只做「提出」：不排程、不組 pipeline（Phase 48）、不改 `RULE.status`（只有 Phase 55）、
# 不把 candidate 放進寫作 prompt（Phase 19 只選 active）、不算指標（Phase 53–55）。
# 與弱教學分支（Phase 44／45／46）完全獨立：不讀 `rating`、不呼叫 `is_weak`（設計 F26）。

MIN_CANDIDATE_FEEDBACK = 5
"""同版同類要湊足幾個**不同** Feedback ID 才可提出 candidate（設計 §7.5、00A §5.4）。

刻意不寫成 `Thresholds.recurring_category` 的別名：那是「弱教學要有 recurring 類別」的
門檻，這一個是「可以提規則」的門檻，兩條分支各自判斷，數字相同只是巧合（設計 F26）。
"""


@dataclass(frozen=True)
class CandidateGroup:
    """已驗證的證據組：同一版本、同一核定類別，加上去重且升序的 Feedback ID。

    這是呼叫模型的**前提**而不是結果：`propose_candidate` 只能拿已經成組的證據去問模型，
    `evidence`／`derived_from` 一律取自這裡，不採信模型回傳的版本（設計 D15、D18）。
    """

    version_id: str
    category: str
    feedback_ids: tuple[str, ...]


def candidate_groups(feedback: Iterable[Feedback],
                     approved: frozenset[str]) -> tuple[CandidateGroup, ...]:
    """把回饋分成可提案的證據組（`PRP` Rule 1）；純函式，完全不呼叫模型、不碰 Repository。

    分桶 key 是 `(tutorial_version, category)` 兩欄：跨版湊數是設計 F25 明確禁止的，
    所以 v1 三筆加 v2 兩筆雖然總數是五也不成組。同桶內先用 `set` 去重再數，同一筆回饋
    被讀兩次不會把門檻撐起來（`PRP` Rule 1 的「不同 Feedback」）。

    `category` 是 `None`（沒分類）或 `待分類` 時都不在核定類別表裡，直接跳過——`COL`
    Rule 5 的核定類別表由 Phase 43 維護，本函式只消費，不自己判斷哪些類別合法。
    `approved` 是**參數**不是查詢：要不要連 Repository 讀核定類別表，是 Phase 48 呼叫端的事。

    輸出依 `(version_id, category)` 升序、每組 ID 升序，所以同一批回饋永遠得到同一個順序，
    `candidate_rule_id` 才能是決定性的。`rating` 從頭到尾沒有被讀過：能提規則不代表這一版
    是弱教學（設計 F26）。
    """
    buckets: dict[tuple[str, str], set[str]] = defaultdict(set)
    for item in feedback:
        category = item.category
        # `category is None` 先擋掉是為了讓型別檢查看得出 key 的第二欄一定是 str；
        # 語意上 None 本來就不可能出現在核定類別表裡，兩種寫法結果相同。
        if category is None or category not in approved:
            continue
        buckets[(item.tutorial_version, category)].add(item.id)
    return tuple(
        CandidateGroup(version_id, category, tuple(sorted(ids)))
        for (version_id, category), ids in sorted(buckets.items())
        if len(ids) >= MIN_CANDIDATE_FEEDBACK
    )
