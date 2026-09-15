"""規則與呼叫數指標（Phase 54）：`MET` 7／8／9 的三個純函式。

都不讀 DynamoDB：清單由呼叫端用 `Repository.list_rules`／版本查詢取好再交進來，
`CallTrace` 由流程自己帶。三個函式都只做計數，不判定規則狀態（那是 Phase 55）、
也不寫任何 item。
"""

from collections.abc import Iterable

from training_kb.models import AuthoringRule, RuleStatus, TutorialVersion
from training_kb.writing import CallTrace

RULE_STATUS_KEYS: tuple[str, ...] = tuple(str(status) for status in RuleStatus)
"""`candidate`／`active`／`retired`；鍵取自 Phase 03 的 `RuleStatus`，不抄字面值。"""


def rule_counts(rules: Iterable[AuthoringRule]) -> dict[str, int]:
    """已學規則數依 `status` 分別計數；三個鍵固定存在，沒有資料的補 0（`MET` 7）。

    補 0 不是美觀問題：缺鍵會讓畫面把「這個狀態沒有規則」讀成「沒有這種狀態」。
    """
    counts = dict.fromkeys(RULE_STATUS_KEYS, 0)
    for item in rules:
        counts[str(item.status)] += 1
    return counts


def applied_count(versions: Iterable[TutorialVersion], rule_id: str) -> int:
    """規則套用次數：含這條規則的版本數，以 `version_id` 去重（`MET` 8）。

    唯一權威是 `VERSION.rules_applied`（D17）。`RULE.applied_to` 與 `APPLIED_TO` 邊是
    可重建投影，兩者對不上代表投影過期，應交 Phase 28 的 `rebuild_rule_projection`
    重建，**不是**改指標去遷就投影。

    這是「對已取得的版本清單算」的純函式，與 `Repository.list_versions_applying_rule`
    （「從 DB 查」的同一條 D17 規則）並存，不互相取代。
    """
    return len({item.version_id for item in versions if rule_id in item.rules_applied})


def bedrock_call_count(trace: CallTrace, *, operation_id: str | None = None) -> int:
    """每次真實 request attempt 的數量；直接轉呼 Phase 15 的 `CallTrace.count`（`MET` 9）。

    不自建第二份計數器：Phase 15 已保證每次真實 request（含丟例外的那些）恰有一筆
    trace，所以重試的第二次、Map 的每個 item、Rote 層的 `tool_use` 與 embedding 都
    已經在裡面（F45）；自己數就一定會漏掉其中幾種。記憶體重用已保存的輸出沒有送出
    request，也就沒有 trace，因此不會被算進來。
    """
    return trace.count(operation_id=operation_id)
