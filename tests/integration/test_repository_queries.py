"""Phase 08：三個公開查詢、GSI 候選回基表核對與六個固定讀取（moto 本機表）。

moto 的 PASS 只證明資料形狀與分頁邏輯，**不**證明真實 DynamoDB 的分頁與 GSI 最終一致行為；
跨併發寫入的完整性與 O2、O3 一起驗收（設計 §10）。
`paged_repository` 的 `page_size=1` 是測試鉤子：Limit 在過濾之前套用，所以帶
`FilterExpression` 的 Scan 會出現「這一頁零筆但游標還在」，提前停止就會漏資料。
"""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from training_kb.errors import PermanentError
from training_kb.keys import feature_pk, feedback_pk, rule_pk, step_pk, ticket_pk, version_pk
from training_kb.models import (
    AuthoringRule,
    Feedback,
    ProcStep,
    ProvenWorkflow,
    RuleStatus,
    Ticket,
    TutorialView,
)
from training_kb.repository import item_to_model

VERSION = "prepare-meeting@v1"


def feedback(feedback_id: str, version_id: str = VERSION) -> Feedback:
    return Feedback(id=feedback_id, tutorial_version=version_id, rating=2,
                    category="Button not found", comment=None, user="u_01",
                    ts=datetime(2026, 8, 2, tzinfo=UTC))


def ticket(ticket_id: str, project_id: str = "demo") -> Ticket:
    return Ticket(id=ticket_id, source="email", text="Button not found", author="u_01",
                  ts=datetime(2026, 8, 3, 10, tzinfo=UTC), project_id=project_id)


def test_scan_entity_reads_every_page_even_when_pages_come_back_empty(
        repository, paged_repository) -> None:
    """五筆 TICKET 與五筆 FEEDBACK 交錯，`page_size=1` 讓一半的頁被 filter 濾成空。"""
    for number in range(1, 6):
        repository.put_meta(ticket(f"t_{number}"))
        repository.put_meta(feedback(f"f_{number}"))
    tickets = paged_repository.scan_entity("TICKET")
    assert [str(item["PK"]) for item in tickets] == [f"TICKET#t_{n}" for n in range(1, 6)]
    assert tickets == repository.scan_entity("TICKET")


def test_query_pk_returns_every_edge_of_the_same_start_point(repository, paged_repository) -> None:
    """GPH Rule 1：查某起點的關係就用該起點的 PK，而且要讀齊所有分頁。"""
    pk = feedback_pk("f_12")
    repository.put_meta(feedback("f_12"))
    for number in range(1, 4):
        repository.put_edge(pk, "REFERS_TO", version_pk(f"prepare-meeting@v{number}"))
    rows = paged_repository.query_pk(pk)
    assert [str(item["SK"]) for item in rows] == [
        "META",
        "REFERS_TO#VERSION#prepare-meeting@v1",
        "REFERS_TO#VERSION#prepare-meeting@v2",
        "REFERS_TO#VERSION#prepare-meeting@v3",
    ]
    assert [str(item["SK"]) for item in paged_repository.query_pk(pk, sk_prefix="REFERS_TO#")] == [
        f"REFERS_TO#VERSION#prepare-meeting@v{number}" for number in range(1, 4)
    ]
    assert paged_repository.query_pk(ticket_pk("t_missing")) == []


def test_step_edges_are_scanned_with_meta_only_off(repository, paged_repository) -> None:
    """STEP 沒有 `META` item，所以預設的 `meta_only=True` 會把它整個濾掉。"""
    pk = step_pk("prepare-meeting@v2", 1)
    repository.put_edge(pk, "REFERENCES", "FEATURE#Prepare", {"type": "read", "text": "step 1"})
    assert paged_repository.scan_entity("STEP") == []
    assert [str(item["PK"]) for item in paged_repository.scan_entity("STEP", meta_only=False)] == [
        pk
    ]


def test_list_feedback_of_version_ignores_other_relations(repository) -> None:
    """GPH Rule 6：以 `REFERS_TO` 反查某版的回饋；同一個終點上的別種邊不入選。"""
    target = version_pk(VERSION)
    for feedback_id in ("f_15", "f_12"):
        repository.put_meta(feedback(feedback_id))
        repository.put_edge(feedback_pk(feedback_id), "REFERS_TO", target)
    repository.put_edge(version_pk("prepare-meeting@v2"), "SUPERSEDES", target)
    repository.put_edge(ticket_pk("t_881"), "ASKS_ABOUT", target)
    found = repository.list_feedback_of_version(VERSION)
    assert [item.id for item in found] == ["f_12", "f_15"]
    assert found[0] == feedback("f_12")


def test_by_target_candidates_only_carry_keys(repository, paged_repository) -> None:
    """GPH Rule 2：候選來自 `by_target`，而且 `KEYS_ONLY` 只投影三個鍵，內容要回基表拿。"""
    target = version_pk(VERSION)
    repository.put_meta(feedback("f_12"))
    repository.put_edge(feedback_pk("f_12"), "REFERS_TO", target)
    repository.put_edge(version_pk("prepare-meeting@v2"), "SUPERSEDES", target)
    candidates = paged_repository.query_by_target(target)
    assert sorted(str(item["PK"]) for item in candidates) == [
        "FEEDBACK#f_12", "VERSION#prepare-meeting@v2"
    ]
    assert all(set(item) == {"PK", "SK", "target"} for item in candidates)
    assert all(str(item["target"]) == target for item in candidates)


def test_candidate_without_base_item_fails_loudly(repository) -> None:
    """GSI 只會落後基表、不會多出資料，所以候選讀不到本體代表資料不完整，必須明確失敗。"""
    repository.put_edge(feedback_pk("f_12"), "REFERS_TO", version_pk(VERSION))
    with pytest.raises(PermanentError, match="has no base item"):
        repository.list_feedback_of_version(VERSION)


def view(user: str, day: int, version_id: str = VERSION) -> TutorialView:
    return TutorialView(tutorial_version=version_id, user=user,
                        ts=datetime(2026, 8, day, tzinfo=UTC))


def rule(rule_id: str = "R-007", status: RuleStatus = RuleStatus.ACTIVE) -> AuthoringRule:
    return AuthoringRule(rule_id=rule_id, rule="點 UI 時寫出頁面與按鈕位置",
                         applies_when="click_ui", status=status,
                         evidence=["f_12", "f_15", "f_19", "f_23", "f_27"],
                         applied_to=[], derived_from=VERSION)


def proc(signature: str, *, domain: str = "github", adapter: str = "rest") -> ProvenWorkflow:
    return ProvenWorkflow(signature=signature, domain=domain, adapter=adapter,
                          steps=[ProcStep(tool="get_issue", args={"number": "17"})],
                          keys=["number"], success_count=3, fail_count=0, status="active",
                          last_used=datetime(2026, 8, 4, tzinfo=UTC))


def test_get_steps_returns_sorted_steps_with_feature_ids(repository, paged_repository) -> None:
    for number in (3, 1, 2):
        repository.put_edge(step_pk("prepare-meeting@v2", number), "REFERENCES",
                            feature_pk("Prepare"), {"type": "read", "text": f"step {number}"})
    repository.put_edge(step_pk("share-summary@v1", 1), "REFERENCES", feature_pk("Schedule"),
                        {"type": "click_ui", "text": "別版的步驟"})
    steps = paged_repository.get_steps("prepare-meeting@v2")
    assert [step.number for step in steps] == [1, 2, 3]
    assert {step.feature_id for step in steps} == {"Prepare"}
    assert steps[0].tutorial_version == "prepare-meeting@v2"
    assert steps[0].text == "step 1"
    assert repository.get_steps("prepare-meeting@v9") == []


def test_list_views_of_version_excludes_other_versions(repository) -> None:
    repository.put_meta(view("u_02", 5))
    repository.put_meta(view("u_01", 4))
    repository.put_meta(view("u_03", 6, version_id="prepare-meeting@v2"))
    assert [item.user for item in repository.list_views_of_version(VERSION)] == ["u_01", "u_02"]


def test_list_tickets_excludes_other_projects(repository) -> None:
    repository.put_meta(ticket("t_881"))
    repository.put_meta(ticket("t_12"))
    repository.put_meta(ticket("t_999", project_id="other"))
    assert [item.id for item in repository.list_tickets("demo")] == ["t_12", "t_881"]
    assert [item.id for item in repository.list_tickets("other")] == ["t_999"]


def test_list_rules_filters_by_status(repository) -> None:
    repository.put_meta(rule("R-007"))
    repository.put_meta(rule("R-002", status=RuleStatus.CANDIDATE))
    assert [item.rule_id for item in repository.list_rules()] == ["R-002", "R-007"]
    assert [item.rule_id for item in repository.list_rules(RuleStatus.ACTIVE)] == ["R-007"]
    assert repository.list_rules(RuleStatus.RETIRED) == []


def test_list_procs_needs_both_domain_and_adapter(repository) -> None:
    repository.put_meta(proc("b" * 16))
    repository.put_meta(proc("a" * 16))
    repository.put_meta(proc("c" * 16, adapter="graphql"))
    repository.put_meta(proc("d" * 16, domain="discord"))
    assert [item.signature for item in repository.list_procs("github", "rest")] == [
        "a" * 16, "b" * 16
    ]
    assert [item.signature for item in repository.list_procs("github", "graphql")] == ["c" * 16]
    assert [item.signature for item in repository.list_procs("discord", "rest")] == ["d" * 16]
    assert repository.list_procs("discord", "graphql") == []


def test_list_reads_ignore_relation_edges(repository) -> None:
    """`meta_only=True` 是預設值，所以同前綴的關係邊不會被拿去 `item_to_model`。"""
    repository.put_meta(rule())
    repository.put_edge(rule_pk("R-007"), "APPLIED_TO", version_pk("prepare-meeting@v2"))
    repository.put_edge(ticket_pk("t_881"), "ASKS_ABOUT", feature_pk("Prepare"))
    assert [item.rule_id for item in repository.list_rules()] == ["R-007"]
    assert repository.list_tickets("demo") == []


def test_raw_item_cannot_be_validated_directly(repository) -> None:
    """raw item 帶保留屬性，`extra="forbid"` 一定擋下來；這就是 `item_to_model` 的理由。"""
    repository.put_meta(ticket("t_881"))
    item = repository.scan_entity("TICKET")[0]
    with pytest.raises(ValidationError):
        Ticket.model_validate(item)
    assert item_to_model(item, Ticket) == ticket("t_881")
