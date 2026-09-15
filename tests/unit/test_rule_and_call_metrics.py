"""Phase 54：規則狀態計數、規則套用次數與真實 Bedrock 呼叫數。

三個純函式都不讀 DynamoDB：`rule_counts`／`applied_count` 對呼叫端已取得的清單計算，
`bedrock_call_count` 直接轉呼 Phase 15 的 `CallTrace.count`（**不自建第二份計數器**，
自建的那一份一定會漏掉 retry 與 Map 的每個 item）。
"""

from training_kb.analytics.rules_metrics import applied_count, bedrock_call_count, rule_counts
from training_kb.models import AuthoringRule, TutorialVersion
from training_kb.writing import CallTrace

EVIDENCE = ["f_12", "f_15", "f_19", "f_23", "f_27"]


def rule(rule_id: str, status: str) -> AuthoringRule:
    return AuthoringRule(rule_id=rule_id, rule="點 UI 時寫出頁面與按鈕位置",
                         applies_when="click_ui", status=status, evidence=EVIDENCE,
                         applied_to=[], derived_from="prepare-meeting@v1")


def version(version_id: str, rules_applied: list[str]) -> TutorialVersion:
    slug = version_id.partition("@")[0]
    return TutorialVersion(version_id=version_id, slug=slug, supersedes=None,
                           reason="gap:c12", rules_applied=rules_applied,
                           s3_key=f"tutorials/{slug}/v1.md", published_at=None)


def record(node: str, kind: str, attempt: int, outcome: str) -> dict[str, object]:
    """七個鍵就是 Phase 15 的 `TRACE_FIELDS`，一個不多一個不少。"""
    return {"operation_id": "op-1", "node": node, "model": "m", "attempt": attempt,
            "kind": kind, "started_at": "2026-09-01T00:00:00Z", "outcome": outcome}


def test_rule_counts_reports_all_three_statuses_with_zero_fill() -> None:
    """Given 混合狀態的規則，Then 三個鍵都在，沒有資料的補 0（`MET` 7）。

    空輸入也要有三個鍵：缺鍵會讓畫面把「沒有這種狀態」讀成資料缺漏。
    """
    rules = [rule("R-007", "active"), rule("R-011", "candidate"),
             rule("R-012", "retired"), rule("R-013", "candidate")]
    assert rule_counts(rules) == {"candidate": 2, "active": 1, "retired": 1}
    assert rule_counts([]) == {"candidate": 0, "active": 0, "retired": 0}


def test_applied_count_rebuilds_from_rules_applied_and_deduplicates() -> None:
    """Given 版本清單，Then 套用次數由 `rules_applied` 重建並以 version_id 去重（D17、`MET` 8）。

    `RULE.applied_to` 與 `APPLIED_TO` 邊是可重建投影：不一致代表投影過期，
    交 Phase 28 的 `rebuild_rule_projection` 重建，**不是**改指標遷就投影。
    """
    versions = [version("prepare-meeting@v2", ["R-007"]),
                version("share-summary@v1", ["R-007", "R-011"]),
                version("prepare-meeting@v3", ["R-007"]),
                version("notification-settings@v1", [])]
    assert applied_count(versions, "R-007") == 3
    assert applied_count(versions + versions, "R-007") == 3
    assert applied_count(versions, "R-099") == 0


def test_bedrock_call_count_counts_every_real_attempt() -> None:
    """Given 四筆 attempt（embedding、retry 前後兩次 generation、Rote 的 tool_use），
    Then 呼叫數是 4（`MET` 9、F45）。

    第二次重試是**第二個** attempt，不是同一個；Rote 層與 embedding 一樣算。
    記憶體重用已保存的輸出不送 request，所以也不會多一筆 trace。
    """
    trace = CallTrace()
    trace.add(record("embed_ticket", "embedding", 1, "success"))
    trace.add(record("name_gap", "generation", 1, "transient_error"))
    trace.add(record("name_gap", "generation", 2, "success"))
    trace.add(record("rote_agent", "tool_use", 1, "success"))
    assert bedrock_call_count(trace) == 4
    assert bedrock_call_count(trace) == 4   # 重用已保存輸出不送 request，也不多一筆 trace
    assert bedrock_call_count(trace, operation_id="op-2") == 0
