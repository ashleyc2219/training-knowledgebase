"""Phase 28：維護批次跑在 moto 的本機表與 bucket 上——分頁、空頁、重跑冪等與核對回 True。

`repository`／`paged_repository`／`table`／`bucket` fixture 來自 `tests/integration/conftest.py`
（owner 是 Phase 06，本 Phase 不是它的修改者）；四步內容、`VersionPlan` 與三個 seed 函式
直接沿用 `test_create_version.py`，兩件事因此只有一種形狀：**這裡修的資料是 Phase 23
`create_version` 真的寫出來的**，不是測試自己拼的 item。

單元測試（`tests/unit/test_backfill_references.py`／`test_rule_projection.py`）驗判定規則，
本檔補上單元測試做不到的三件事：真的 DynamoDB 分頁（`paged_repository` 每頁一筆，所以
`scan_entity` 會走出一堆被 filter 濾成空的頁）、真的 `DeleteItem`，以及與 Phase 23 修正後的
`verify_version_complete` 對接——**重建結果必須讓核對回 `True`**。

**moto 全綠只證明資料形狀。** 本檔不依賴也不宣稱 O2／O3；backfill 是維護批次，不在發布路徑
上，**不能**用來補救 Phase 24／25 的 partial publish，也不是 O3 的替代方案。
"""

from collections.abc import Sequence
from typing import Any

import pytest
from test_create_version import (
    FEATURE,
    NOW,
    SLUG,
    V1,
    V2,
    build_ready_v2,
    four_step_content,
)

from training_kb.clock import to_iso
from training_kb.content import verify_version_complete
from training_kb.errors import PermanentError
from training_kb.keys import feature_pk, rule_pk, step_pk, version_pk
from training_kb.models import AuthoringRule, RuleStatus, StepType
from training_kb.repository import BackfillReport, Repository

RULE = "R-007"
STRAY_RULE = "R-999"
STEP3_PK = step_pk(V2, 3)
STEP3_SK = f"REFERENCES#{feature_pk(FEATURE)}"


def seed_rule(repository: Repository, rule_id: str, applied_to: Sequence[str]) -> None:
    """一條 `active` 規則；`evidence` 至少五筆不同 ID 是 Phase 04 的模型限制。"""
    repository.put_meta(AuthoringRule(
        rule_id=rule_id, rule="每一步都要寫出畫面上看得到的按鈕名稱。",
        applies_when=StepType.CLICK_UI, evidence=[f"f_{index}" for index in range(1, 6)],
        status=RuleStatus.ACTIVE, applied_to=list(applied_to), derived_from="f_1"))


def publish(repository: Repository, version_id: str) -> None:
    """把版本切成已發布：backfill 只吃已發布版，而 `create_version` 永遠寫 `published_at=None`。

    只寫 `published_at` 一個欄位（不碰 `current_version`）：本檔要的是「這一版已發布」這個
    前提，不是重現 Phase 24 的發布交易。
    """
    pk = version_pk(version_id)
    repository.update_meta(pk, {"published_at": to_iso(NOW)},
                           expected_revision=repository.revision_of(pk))


@pytest.fixture
def maintained(repository: Repository, table: Any, bucket: Any) -> Repository:
    """Phase 23 寫出來的完整 v2（四步、`SUPERSEDES`、`APPLIED_TO#R-007`），切成已發布。

    `verify_version_complete(V2)` 在這個起點必須是 `True`——後面每個測試都先弄壞它。
    """
    build_ready_v2(repository, table, bucket)
    publish(repository, V2)
    seed_rule(repository, RULE, [V2])
    assert verify_version_complete(V2, repository) is True
    return repository


def test_backfill_restores_the_missing_edge_and_verify_turns_true(
        maintained: Repository, table: Any) -> None:
    """GPH Rule 7：漏掉的引用邊補回來之後，Phase 23 的核對從 `False` 變回 `True`。"""
    table.delete_item(Key={"PK": STEP3_PK, "SK": STEP3_SK})
    assert verify_version_complete(V2, maintained) is False
    report = maintained.backfill_references(V2)
    assert report == BackfillReport(added=(STEP3_PK,), conflicts=(), unresolved=())
    rows = maintained.query_pk(STEP3_PK, consistent=True)
    assert len(rows) == 1
    # 建立教學版本 Rule 8／10：補出來的 item 與 Phase 23 `_write_edges` 寫的完全一樣。
    assert set(rows[0]) == {"PK", "SK", "target", "entity", "type", "text"}
    assert rows[0]["SK"] == STEP3_SK and rows[0]["target"] == feature_pk(FEATURE)
    assert rows[0]["text"] == four_step_content().steps[2].text
    assert verify_version_complete(V2, maintained) is True
    assert maintained.backfill_references(V2).added == ()


def test_backfill_makes_the_phase27_query_complete_again(maintained: Repository,
                                                         table: Any) -> None:
    """人工驗收的程式版：補邊後 `find_current_published_steps_referencing` 又數得到第 3 步。

    `current_version` 還指著 v1，所以先切到 v2 才是「目前已發布版」。**moto 的 GSI 是即時的**
    （Phase 27 報告 §5 已記錄），所以 `delete_item` 之後 `by_target` 候選也跟著消失，
    這裡看到的是「反查安靜地少一步」，不是 Phase 27 那條 `PermanentError`；真實 DynamoDB 上
    GSI 落後時才會走到那條路徑，兩種症狀的修法都是同一個 backfill。
    """
    pk = f"TUTORIAL#{SLUG}"
    maintained.update_meta(pk, {"current_version": V2},
                           expected_revision=maintained.revision_of(pk))
    table.delete_item(Key={"PK": STEP3_PK, "SK": STEP3_SK})
    before = maintained.find_current_published_steps_referencing(FEATURE)
    assert [step.number for step in before] == [1, 2, 4]
    maintained.backfill_references(V2)
    steps = maintained.find_current_published_steps_referencing(FEATURE)
    assert [(step.tutorial_version, step.number) for step in steps] == [
        (V2, 1), (V2, 2), (V2, 3), (V2, 4)]


def test_backfill_refuses_unpublished_and_unknown_versions(repository: Repository,
                                                           table: Any, bucket: Any) -> None:
    """設計 §10：`create_version` 剛寫好的 v2 還沒發布，補寫會把半成品補成看起來完整。"""
    build_ready_v2(repository, table, bucket)
    version = repository.get_version(V2)
    assert version is not None and version.published_at is None
    with pytest.raises(PermanentError, match=V2):
        repository.backfill_references(V2)
    with pytest.raises(PermanentError, match="nope@v9"):
        repository.backfill_references("nope@v9")
    assert verify_version_complete(V2, repository) is True     # 一個欄位都沒被動過


def test_backfill_never_creates_a_version_or_a_feature(maintained: Repository,
                                                       table: Any, bucket: Any) -> None:
    """F40：補邊不建版本、不造 Feature、不碰 S3；`unresolved` 不是「要補齊」的清單。"""
    table.delete_item(Key={"PK": STEP3_PK, "SK": STEP3_SK})
    table.delete_item(Key={"PK": feature_pk(FEATURE), "SK": "META"})
    before_objects = {item.key: item.get()["Body"].read() for item in bucket.objects.all()}
    report = maintained.backfill_references(V2)
    assert report.added == () and report.conflicts == ()
    assert report.unresolved == (STEP3_PK,)
    assert maintained.get_feature(FEATURE) is None
    assert maintained.query_pk(STEP3_PK, consistent=True) == []
    assert sorted(str(item["PK"]) for item in maintained.scan_entity("VERSION")) == [
        version_pk(V1), version_pk(V2)]
    assert {item.key: item.get()["Body"].read() for item in bucket.objects.all()} == (
        before_objects)


def test_rebuild_removes_the_stray_edge_and_verify_turns_true(
        maintained: Repository) -> None:
    """Phase 23 修正後的核對也會拒絕**多出來的** `APPLIED_TO` 邊，所以刪邊必須刪得掉。"""
    seed_rule(maintained, STRAY_RULE, [V2])
    maintained.put_edge(rule_pk(STRAY_RULE), "APPLIED_TO", version_pk(V2))
    assert verify_version_complete(V2, maintained) is False
    assert maintained.rebuild_rule_projection(STRAY_RULE) == []
    assert maintained.list_edges(rule_pk(STRAY_RULE), "APPLIED_TO") == []
    rule = maintained.get_meta(rule_pk(STRAY_RULE), AuthoringRule)
    assert rule is not None and rule.applied_to == [] and rule.status == RuleStatus.ACTIVE
    assert verify_version_complete(V2, maintained) is True


def test_rebuild_adds_the_missing_edge_and_keeps_versions_untouched(
        maintained: Repository, table: Any) -> None:
    """D17：邊被刪掉時由 `rules_applied` 補回來；VERSION item 前後完全相同。"""
    table.delete_item(Key={"PK": rule_pk(RULE), "SK": f"APPLIED_TO#{version_pk(V2)}"})
    assert verify_version_complete(V2, maintained) is False
    before = {str(item["PK"]): dict(item) for item in maintained.scan_entity("VERSION")}
    assert maintained.rebuild_rule_projection(RULE) == [V2]
    assert maintained.list_edges(rule_pk(RULE), "APPLIED_TO")[0]["target"] == version_pk(V2)
    assert {str(item["PK"]): dict(item) for item in maintained.scan_entity("VERSION")} == before
    assert verify_version_complete(V2, maintained) is True
    assert maintained.rebuild_rule_projection(RULE) == [V2]


def test_rebuild_reads_every_page_of_a_paged_scan(
        paged_repository: Repository, table: Any, bucket: Any) -> None:
    """設計 §10：Scan 一律讀到沒有下一頁；每頁一筆時多數頁會被 `entity` filter 濾成空。

    `paged_repository` 的 `Limit=1` 讓同一批資料切成幾十頁，其中大部分沒有任何 VERSION
    item——`_paged` 只要看到空頁就停，`R-007` 就會少算版本、`applied_to` 也就漏了。
    """
    build_ready_v2(paged_repository, table, bucket)
    publish(paged_repository, V1)
    publish(paged_repository, V2)
    pk = version_pk(V1)
    paged_repository.update_meta(pk, {"rules_applied": [RULE]},
                                 expected_revision=paged_repository.revision_of(pk))
    seed_rule(paged_repository, RULE, [])
    assert paged_repository.rebuild_rule_projection(RULE) == [V1, V2]
    assert sorted(str(edge["target"]) for edge
                  in paged_repository.list_edges(rule_pk(RULE), "APPLIED_TO")) == [
        version_pk(V1), version_pk(V2)]


def test_backfill_reads_every_page_of_a_paged_scan(
        paged_repository: Repository, table: Any, bucket: Any) -> None:
    """同一件事在 backfill 這一側：`get_feature`／`list_edges` 也要讀完分頁才判斷得準。"""
    build_ready_v2(paged_repository, table, bucket)
    publish(paged_repository, V2)
    table.delete_item(Key={"PK": STEP3_PK, "SK": STEP3_SK})
    assert paged_repository.backfill_references(V2).added == (STEP3_PK,)
    assert verify_version_complete(V2, paged_repository) is True


def test_delete_edge_refuses_references_on_a_real_table(maintained: Repository) -> None:
    """白名單在真表上一樣有效：`REFERENCES` 刪不掉，`DeleteItem` 根本沒被送出。"""
    with pytest.raises(PermanentError, match="REFERENCES"):
        maintained.delete_edge(STEP3_PK, "REFERENCES", feature_pk(FEATURE))
    assert len(maintained.query_pk(STEP3_PK, consistent=True)) == 1
    assert verify_version_complete(V2, maintained) is True


def test_backfill_then_rebuild_leaves_the_version_complete(maintained: Repository,
                                                           table: Any) -> None:
    """§8 Invariant：兩個函式各跑一輪後版本仍完整，而且兩者都冪等。"""
    table.delete_item(Key={"PK": STEP3_PK, "SK": STEP3_SK})
    table.delete_item(Key={"PK": rule_pk(RULE), "SK": f"APPLIED_TO#{version_pk(V2)}"})
    seed_rule(maintained, STRAY_RULE, [V2])
    maintained.put_edge(rule_pk(STRAY_RULE), "APPLIED_TO", version_pk(V2))
    assert verify_version_complete(V2, maintained) is False
    first = (maintained.backfill_references(V2),
             maintained.rebuild_rule_projection(RULE),
             maintained.rebuild_rule_projection(STRAY_RULE))
    assert verify_version_complete(V2, maintained) is True
    second = (maintained.backfill_references(V2),
              maintained.rebuild_rule_projection(RULE),
              maintained.rebuild_rule_projection(STRAY_RULE))
    assert first == (BackfillReport(added=(STEP3_PK,), conflicts=(), unresolved=()), [V2], [])
    assert second == (BackfillReport(added=(), conflicts=(), unresolved=()), [V2], [])
    assert verify_version_complete(V2, maintained) is True
