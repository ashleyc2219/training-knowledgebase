"""單一版本的完整指標（Phase 54）：把 Phase 53 的評分與本 Phase 的重開票合成一份。

`version_metrics` 是本 Phase **唯一**讀 Repository 的函式（其餘都是純函式），
`metrics_action` 是 `training-kb-analytics` 的 `action: "metrics"` 實作。兩者都不寫任何
item、不呼叫模型、不判定規則狀態（Phase 55），也不把多版的 rate 彙總成單一數字
（O4 未核定，設計 §12.1 明文禁止自行彙總）。
"""

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any

from training_kb.analytics.ratings import average_rating, format_average, negative_feedback_ids
from training_kb.analytics.reopen import ReopenStats, reopen_stats
from training_kb.errors import PermanentError
from training_kb.repository import Repository

NO_REOPEN = ReopenStats(0, 0, 0, None)
"""未發布或缺 `cluster_id` 時的結果：零分母、`rate is None`，不是 0%。"""


@dataclass(frozen=True)
class VersionMetrics:
    """一版的完整指標。

    `average` 是**未四捨五入**的浮點數（門檻比較吃這個值，顯示才用 `format_average`）；
    `None` 代表「尚無評分」而不是 0 分。`sample_size` 是**有評分**的筆數，與 Phase 44 的
    `n` 同一套分母（D-44）。`negative_ids` 是 Feedback ID 集合，要數量就 `len(...)`。
    """

    version_id: str
    published_at: datetime | None
    average: float | None
    sample_size: int
    negative_ids: frozenset[str]
    reopen: ReopenStats


def version_metrics(version_id: str, *, repository: Repository,
                    approved: frozenset[str], project_id: str) -> VersionMetrics:
    """讀一版的回饋、瀏覽與工單，算出評分與重開票兩組指標。

    `published_at is None`（還沒發布）或 `Tutorial.cluster_id is None`（沒有固定同題對應）
    時直接回 `NO_REOPEN`：**不憑空造窗口**，也不拋例外——這兩種情況是資料狀態，不是錯誤。
    找不到版本才是錯誤（`PermanentError`），因為呼叫端給的 `version_id` 根本不存在。
    """
    item = repository.get_version(version_id)
    if item is None:
        raise PermanentError(f"找不到版本 {version_id!r}")
    feedback = repository.list_feedback_of_version(version_id)
    rated = [row for row in feedback if row.rating is not None]
    tutorial = repository.get_tutorial(item.slug)
    cluster_id = tutorial.cluster_id if tutorial is not None else None
    reopen = NO_REOPEN
    if item.published_at is not None and cluster_id is not None:
        reopen = reopen_stats(repository.list_views_of_version(version_id),
                              repository.list_tickets(project_id),
                              cluster_id=cluster_id, published_at=item.published_at)
    return VersionMetrics(version_id, item.published_at, average_rating(feedback),
                          len(rated), negative_feedback_ids(feedback, approved), reopen)


def _row(item: VersionMetrics) -> dict[str, Any]:
    """一版的 JSON 形狀；`display_average` 是唯一四捨五入過的欄位，不可回填比較。"""
    return {"version_id": item.version_id, "average": item.average,
            "display_average": format_average(item.average),
            "sample_size": item.sample_size, "negative": len(item.negative_ids),
            "reopen": asdict(item.reopen)}


def metrics_action(event: dict[str, Any], *, repository: Repository,
                   approved: frozenset[str], project_id: str) -> dict[str, Any]:
    """`action: "metrics"`：逐版回傳指標，形狀與 Phase 55 的 `validate_rules_action` 一致。

    `version_ids` 為空是 `PermanentError` 而不是「預設全部版本」：全表掃描的成本與
    「維護者少打一個參數」不該由一次 Lambda 呼叫默默承擔。
    """
    version_ids = [str(value) for value in event.get("version_ids") or ()]
    if not version_ids:
        raise PermanentError("metrics action 需要非空的 version_ids")
    return {"action": "metrics",
            "results": [_row(version_metrics(value, repository=repository, approved=approved,
                                             project_id=project_id)) for value in version_ids]}
