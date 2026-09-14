"""Phase 28 Task 3：以 `VERSION.rules_applied` 為唯一權威重建 `applied_to` 與 `APPLIED_TO` 邊。

器材（`repo` fixture、`MaintenanceRepository`、固定種子）來自 `test_backfill_references.py`：
`tests/unit/conftest.py` 的 owner 是 P15、修改者只有 P55（00A §3.2），本 Phase 不是它的
修改者，所以兩支測試檔共用同一份自備器材，而不是去改別人的 conftest（Phase 23 的
`test_version_complete.py` 也是這樣 import `test_create_version.py`）。

種子裡的 `R-007`：`applied_to` 記了三個版本（`prepare-meeting@v2`／`@v3`／`share-summary@v1`），
`APPLIED_TO` 邊卻只有前兩個——三份表示互相矛盾，正是本 Phase 要修的東西。
"""

import pytest
from test_backfill_references import (
    DRAFT,
    FEATURE,
    OTHER_V1,
    RULE,
    STEP3_PK,
    V1,
    V2,
    V3,
    MaintenanceRepository,
    repo,
)

from training_kb.errors import CoordinationError, PermanentError
from training_kb.keys import feature_pk, rule_pk, version_pk
from training_kb.repository import version_sort_key

__all__ = ["repo"]  # 讓 pytest 認得 import 進來的 fixture，而不是把它當成未使用的名稱


def test_rebuild_rule_projection_uses_rules_applied_as_the_only_authority(
        repo: MaintenanceRepository) -> None:
    """`套用教學規則` Rule 6、D17：補缺邊、刪多餘邊、改寫 `applied_to`，VERSION 一個都不寫。"""
    repo.set_rules_applied(V2, [RULE])
    repo.set_rules_applied(V3, [RULE])
    repo.set_rules_applied(OTHER_V1, [])
    repo.add_edge(rule_pk(RULE), "APPLIED_TO", version_pk(OTHER_V1))
    repo.drop_edge(rule_pk(RULE), "APPLIED_TO", version_pk(V3))
    before_versions = repo.full_snapshot().versions
    result = repo.rebuild_rule_projection(RULE)
    assert result == [V2, V3]
    assert repo.get_rule(RULE).applied_to == result
    assert repo.edge_targets(rule_pk(RULE), "APPLIED_TO") == [version_pk(V2), version_pk(V3)]
    assert repo.full_snapshot().versions == before_versions
    # §8 Boundary：連跑兩次回同一個清單（冪等）。
    assert repo.rebuild_rule_projection(RULE) == result


def test_delete_edge_only_accepts_applied_to(repo: MaintenanceRepository) -> None:
    """F40：`REFERENCES` 是已發布版的歷史事實，程式刪不掉；白名單只有 `APPLIED_TO`。"""
    with pytest.raises(PermanentError, match="REFERENCES"):
        repo.delete_edge(STEP3_PK, "REFERENCES", feature_pk(FEATURE))
    with pytest.raises(PermanentError, match="SUPERSEDES"):
        repo.delete_edge(version_pk(V3), "SUPERSEDES", version_pk(V2))
    assert repo.edge_targets(STEP3_PK, "REFERENCES") == [feature_pk(FEATURE)]
    assert repo.edge_targets(version_pk(V3), "SUPERSEDES") == [version_pk(V2)]


def test_delete_edge_removes_only_the_named_applied_to_edge(
        repo: MaintenanceRepository) -> None:
    """刪一條不影響另一條；刪不存在的邊是 no-op（`DeleteItem` 本來就冪等）。"""
    repo.delete_edge(rule_pk(RULE), "APPLIED_TO", version_pk(V2))
    repo.delete_edge(rule_pk(RULE), "APPLIED_TO", version_pk(OTHER_V1))
    assert repo.edge_targets(rule_pk(RULE), "APPLIED_TO") == [version_pk(V3)]


def test_rebuild_writes_no_version_item_and_only_touches_the_rule_pk(
        repo: MaintenanceRepository) -> None:
    """§8 Invariant：寫入的 PK 只有 `RULE#R-007`（本體與它的邊），S3 一個 key 都沒寫。"""
    before = repo.full_snapshot()
    result = repo.rebuild_rule_projection(RULE)
    after = repo.full_snapshot()
    assert result == [V2, V3, OTHER_V1]
    assert after.versions == before.versions
    assert after.objects == before.objects
    assert after.published_at == before.published_at
    assert after.steps_text == before.steps_text
    assert after.written_pks == {rule_pk(RULE)}
    assert after.written_s3_keys == set()


def test_rebuild_with_no_applying_version_clears_the_projection(
        repo: MaintenanceRepository) -> None:
    """§8 Boundary：沒有任何版本套用該規則時回 `[]`、邊全刪、`applied_to` 清空、不改 status。"""
    for version_id in (V2, V3, OTHER_V1):
        repo.set_rules_applied(version_id, [])
    status_before = repo.get_rule(RULE).status
    assert repo.rebuild_rule_projection(RULE) == []
    rule = repo.get_rule(RULE)
    assert rule.applied_to == []
    assert rule.status == status_before          # 只有 Analytics 能寫驗證後 status
    assert repo.list_edges(rule_pk(RULE), "APPLIED_TO") == []
    assert repo.rebuild_rule_projection(RULE) == []


def test_rebuild_reads_every_scan_page_and_ignores_relation_edges(
        repo: MaintenanceRepository) -> None:
    """§8 Boundary：中間一頁為空仍要讀到最後一頁；同次掃到的 `SUPERSEDES` 邊不是版本。"""
    repo.set_rules_applied(V1, [RULE])
    repo.paginate([V2], [], [V1])
    assert repo.edge_targets(version_pk(V3), "SUPERSEDES") == [version_pk(V2)]
    assert repo.rebuild_rule_projection(RULE) == [V1, V2, V3, OTHER_V1]
    assert repo.get_rule(RULE).applied_to == [V1, V2, V3, OTHER_V1]


def test_rebuild_sorts_by_version_number_not_lexicographically(
        repo: MaintenanceRepository) -> None:
    """排序一律經 `version_sort_key`：`@v10` 要排在 `@v3` 之後，不是 `@v1` 之後。"""
    repo.add_version("prepare-meeting@v10", published=True, rules_applied=[RULE])
    assert repo.rebuild_rule_projection(RULE) == [V2, V3, "prepare-meeting@v10", OTHER_V1]
    assert version_sort_key("prepare-meeting@v10") == ("prepare-meeting", 10)


def test_rebuild_counts_unpublished_versions_too(repo: MaintenanceRepository) -> None:
    """D17：權威是 `rules_applied`，不是 `published_at`——與 Phase 27 的查詢同一套判準。"""
    repo.set_rules_applied(DRAFT, [RULE])
    result = repo.rebuild_rule_projection(RULE)
    assert result == [V2, V3, OTHER_V1, DRAFT]
    # 重建後 Phase 27 的固定查詢與投影完全一致（GPH Rule 5）。
    assert repo.list_versions_applying_rule(RULE) == result


def test_rebuild_refuses_a_rule_that_does_not_exist(repo: MaintenanceRepository) -> None:
    """只剩孤兒邊時立刻 `PermanentError`，而且**先確認規則存在才動邊**，不留半改狀態。"""
    repo.add_edge(rule_pk("R-999"), "APPLIED_TO", version_pk(V2))
    with pytest.raises(PermanentError, match="R-999"):
        repo.rebuild_rule_projection("R-999")
    assert repo.edge_targets(rule_pk("R-999"), "APPLIED_TO") == [version_pk(V2)]


def test_rebuild_lets_a_stale_revision_fail_loudly(
        repo: MaintenanceRepository, monkeypatch: pytest.MonkeyPatch) -> None:
    """§8 Failure：`update_meta` 的 `CoordinationError` 往外拋，不重試也不靜默覆蓋。"""
    repo.set_rules_applied(V2, [])
    monkeypatch.setattr(repo, "revision_of", lambda pk: 99)
    with pytest.raises(CoordinationError):
        repo.rebuild_rule_projection(RULE)
    assert repo.get_rule(RULE).applied_to == [V2, V3, OTHER_V1]
