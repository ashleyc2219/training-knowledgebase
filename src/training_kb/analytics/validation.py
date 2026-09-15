"""規則驗證的純判斷層（Phase 55）：批次評估、兩項嚴格改善與狀態機。

本檔只做「判斷」，一個字也不寫回 DynamoDB／S3：寫入端全部收在
`analytics/status_writer.py`（`apply_rule_status` 是全系統唯一寫 `RULE.status`
與最近驗證時間的地方，VAL Rule 8）。

三個不可放寬的界線（設計 §12.2、決策 F30／F31／F32／F33）：

1. **嚴格改善是兩項一起**：後版平均 **>** 前版平均，**且** 後版 rate **<** 前版 rate。
   任一項持平或反向都是 `not_improved`。
2. **`undecidable` 與 `not_improved` 是兩件事**：對照不完整、缺平均、零分母、批次未核定
   一律 `undecidable`，**不算失敗批次**——把它併進 `not_improved`，兩個資料不足的批次
   就會直接把規則退役。
3. **對照只能是同一篇教學套用前的已發布版本**：不跨教學湊對照、不拿未發布版本充數。

`version_metrics` 刻意用**模組層名稱綁定**（`from ... import version_metrics`）：
測試要換掉它時 `monkeypatch.setattr(validation, "version_metrics", ...)` 才換得掉。
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from training_kb.analytics.version import VersionMetrics, version_metrics
from training_kb.content import parse_version_id
from training_kb.models import TutorialVersion
from training_kb.repository import Repository

Verdict = Literal["improved", "not_improved", "undecidable"]
"""一個批次的判定；`undecidable` 是「資料不足」，不是「沒有改善」。"""


@dataclass(frozen=True)
class SeedBatch:
    """一次比較所需的完整資料（明示合成的種子驗證批次，決策 D27）。

    `approved_by`／`approved_at` 是**批次**核定（維護者對這一批簽名）；`evaluate_batch`
    的 `approved` 關鍵字則是 Phase 43 的**回饋類別**核定表，兩者同名不同義，不要互換。
    `cluster_id` 只寫進證據檔供人工核對，不參與任何判斷。
    """

    batch_id: str
    rule_id: str
    slug: str
    before_version_id: str
    after_version_id: str
    cluster_id: str
    project_id: str
    synthetic: bool
    approved_by: str | None
    approved_at: datetime | None


@dataclass(frozen=True)
class RuleEvaluation:
    """一個批次的評估結果；差值即使判定不出來也盡量填（MET Rule 6）。

    `version_ids` 用來判斷兩批是否重疊（共用任何一個版本就算同一批）；`approved` 是
    批次核定與否；`decidable` 是 `verdict != "undecidable"` 的快捷欄位。
    """

    batch_id: str
    rule_id: str
    verdict: Verdict
    reasons: tuple[str, ...]
    before_average: float | None
    after_average: float | None
    before_rate: float | None
    after_rate: float | None
    version_ids: frozenset[str]
    approved: bool
    average_delta: float | None
    rate_delta: float | None
    decidable: bool


def _batch_problems(batch: SeedBatch, before: TutorialVersion | None,
                    after: TutorialVersion | None) -> tuple[str, ...]:
    """比較之前的四道對照檢查加一道核定檢查；回空 tuple 才可以往下比。

    `elif` 是刻意的：版本讀不到就不能再問 `slug`，`parse_version_id` 對不合格式的字串丟
    `ValueError`（不是 `PermanentError`），所以它一定排在「兩版都讀得到」之後。
    """
    reasons: list[str] = []
    if before is None or after is None:
        reasons.append("missing_version")
    elif {before.slug, after.slug} != {batch.slug}:
        reasons.append("cross_tutorial")
    elif before.published_at is None or after.published_at is None:
        reasons.append("unpublished_comparison")
    elif parse_version_id(before.version_id)[1] >= parse_version_id(after.version_id)[1]:
        reasons.append("wrong_order")
    if batch.approved_by is None or batch.approved_at is None:
        reasons.append("batch_not_approved")
    return tuple(reasons)


def _delta(before: float | None, after: float | None) -> float | None:
    """後版減前版；任一邊缺值就回 `None`。**不四捨五入**——門檻比較吃未四捨五入的值。"""
    return None if before is None or after is None else after - before


def _result(batch: SeedBatch, verdict: Verdict, reasons: tuple[str, ...],
            before: VersionMetrics | None = None,
            after: VersionMetrics | None = None) -> RuleEvaluation:
    """把指標攤平成 `RuleEvaluation`；指標還沒取到時四個數字都是 `None`。"""
    before_average = None if before is None else before.average
    after_average = None if after is None else after.average
    before_rate = None if before is None else before.reopen.rate
    after_rate = None if after is None else after.reopen.rate
    return RuleEvaluation(
        batch_id=batch.batch_id, rule_id=batch.rule_id, verdict=verdict, reasons=reasons,
        before_average=before_average, after_average=after_average,
        before_rate=before_rate, after_rate=after_rate,
        version_ids=frozenset({batch.before_version_id, batch.after_version_id}),
        approved=batch.approved_by is not None and batch.approved_at is not None,
        average_delta=_delta(before_average, after_average),
        rate_delta=_delta(before_rate, after_rate),
        decidable=verdict != "undecidable")


def evaluate_batch(batch: SeedBatch, *, approved: frozenset[str],
                   repository: Repository) -> RuleEvaluation:
    """以同一篇教學套用前的已發布版本為對照，判定這個批次有沒有兩項嚴格改善。

    `approved` 是 Phase 43 的**回饋類別**核定表，原封不動轉給 `version_metrics`
    （它只影響 `negative_ids`），與 `batch.approved_by` 的批次核定無關。
    """
    before_version = repository.get_version(batch.before_version_id)
    after_version = repository.get_version(batch.after_version_id)
    reasons = _batch_problems(batch, before_version, after_version)
    if reasons:
        return _result(batch, "undecidable", reasons)
    before = version_metrics(batch.before_version_id, repository=repository,
                             approved=approved, project_id=batch.project_id)
    after = version_metrics(batch.after_version_id, repository=repository,
                            approved=approved, project_id=batch.project_id)
    if before.average is None or after.average is None:
        return _result(batch, "undecidable", ("missing_average",), before, after)
    if before.reopen.rate is None or after.reopen.rate is None:
        return _result(batch, "undecidable", ("zero_denominator",), before, after)
    improved = after.average > before.average and after.reopen.rate < before.reopen.rate
    return _result(batch, "improved" if improved else "not_improved", (), before, after)
