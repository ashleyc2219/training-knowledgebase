"""Phase 07：關係邊的 `target` 一致性與 `META` 隔離。

邊的形狀固定是 `PK=起點`、`SK=<關係>#<終點 PK>`、`target=<終點 PK>`（設計 §9.2、00A §3.3）。
`target` 只能由 `target_pk` 導出，呼叫端不得自帶；讀取時也逐筆核對，因為 backfill
（Phase 28）與維護腳本一樣會寫邊，只在寫入端檢查發現不了已經寫壞的資料。
"""

import pytest

from training_kb.errors import PermanentError
from training_kb.keys import feature_pk, rule_pk, step_pk, version_pk
from training_kb.models import AuthoringRule, RuleStatus, StepType


def test_put_edge_writes_target_equal_to_sk_endpoint(repository) -> None:
    pk = step_pk("prepare-meeting@v2", 3)
    attrs = {"type": "click_ui", "text": "在右上角選擇 Prepare"}
    repository.put_edge(pk, "REFERENCES", feature_pk("Prepare"), attrs)
    edges = repository.list_edges(pk)
    assert len(edges) == 1
    assert edges[0]["SK"] == "REFERENCES#FEATURE#Prepare"
    assert edges[0]["target"] == "FEATURE#Prepare"
    assert edges[0]["entity"] == "STEP"
    assert edges[0]["text"] == "在右上角選擇 Prepare"


def test_reserved_attributes_are_rejected_and_nothing_is_written(repository, table) -> None:
    pk = step_pk("prepare-meeting@v2", 3)
    for reserved in ("target", "SK", "entity"):
        with pytest.raises(PermanentError, match="reserved"):
            repository.put_edge(pk, "REFERENCES", feature_pk("Prepare"), {reserved: "偷渡"})
    assert table.scan(ConsistentRead=True)["Items"] == []


def test_list_edges_skips_the_meta_item_of_the_same_pk(repository) -> None:
    rule = AuthoringRule(
        rule_id="R-007",
        rule="每一步只提一個功能",
        applies_when=StepType.CLICK_UI,
        evidence=["f_1", "f_2", "f_3", "f_4", "f_5"],
        status=RuleStatus.ACTIVE,
        applied_to=["prepare-meeting@v2"],
        derived_from="f_1",
    )
    pk = rule_pk("R-007")
    repository.put_meta(rule)
    repository.put_edge(pk, "APPLIED_TO", version_pk("prepare-meeting@v2"))
    edges = repository.list_edges(pk)
    assert [edge["SK"] for edge in edges] == ["APPLIED_TO#VERSION#prepare-meeting@v2"]


def test_relation_filter_only_returns_that_relation(repository) -> None:
    pk = step_pk("prepare-meeting@v2", 3)
    repository.put_edge(pk, "REFERENCES", feature_pk("Prepare"))
    assert [edge["SK"] for edge in repository.list_edges(pk, "REFERENCES")] == [
        "REFERENCES#FEATURE#Prepare"
    ]
    assert repository.list_edges(pk, "SUPERSEDES") == []


def test_list_edges_refuses_stored_target_that_does_not_match_sk(repository, table) -> None:
    """backfill 與維護腳本也會寫邊，所以讀取端必須自己檢查，而且不自動修正。"""
    pk = step_pk("prepare-meeting@v2", 3)
    table.put_item(Item={"PK": pk, "SK": "REFERENCES#FEATURE#Prepare",
                         "target": "FEATURE#Schedule", "entity": "STEP"})
    with pytest.raises(PermanentError, match="does not match sort key"):
        repository.list_edges(pk)
