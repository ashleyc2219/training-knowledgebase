"""同一個 operation 換程序重送仍拿到同一個版號，`OPS#` 的 `version_id` 只被寫入一次。

`repository` fixture 是 `tests/integration/conftest.py` 的 moto 表＋bucket。第一次呼叫之後
**整組 Python 物件都丟掉**（連 boto3 的 Table handle 一起換新），只留同一張表，再送同一個
`operation_id`，模擬「寫完 S3 就當機、換一個 Lambda 執行環境重試」。

**moto 的 PASS 不是 O2 證據。** 這裡只證明「給定同一份操作紀錄時版號確定」；接受順序、
併發建版與真正的跨程序重啟要等 Phase 11 在真實 DynamoDB 留下證據，O2 gate 目前仍是未通過。
"""

from datetime import UTC, datetime
from typing import Any

import boto3

from training_kb.content import allocate_version
from training_kb.keys import ops_pk, version_pk
from training_kb.models import Tutorial, TutorialStatus, TutorialVersion
from training_kb.operations import AcceptOperation, OperationCoordinator
from training_kb.repository import Repository

NOW = datetime(2026, 9, 14, 9, 0, tzinfo=UTC)
SLUG = "prepare-meeting"
OPERATION = AcceptOperation("op-release-r_42", "release", "r_42", "demo", NOW)
REASON = "release:r_42"
RULES = ["R-007"]


def _restarted(table: Any) -> tuple[Repository, OperationCoordinator]:
    """同一張表、全新的 boto3 handle 與全新的 `Repository`／`OperationCoordinator`。

    重用 `table` fixture 的物件只換 `Repository` 的話，連線與快取都還是原本那一份；
    這裡連 handle 一起重建，第一次呼叫留下的 Python 狀態一個都不剩，只有表裡的資料還在。
    """
    region = table.meta.client.meta.region_name
    handle = boto3.resource("dynamodb", region_name=region).Table(table.name)
    repository = Repository(handle)
    return repository, OperationCoordinator(repository)


def _seed_tutorial(repository: Repository, current_version: str | None) -> None:
    repository.put_meta(Tutorial(slug=SLUG, current_version=current_version, topic="準備會議",
                                 feature_ids=["Prepare"], status=TutorialStatus.ACTIVE,
                                 successor=None, cluster_id="c12"))


def _allocate(repository: Repository, operations: OperationCoordinator) -> Any:
    return allocate_version(SLUG, OPERATION.operation_id, operations,
                            repository=repository, reason=REASON, rules_applied=RULES)


def test_the_same_operation_keeps_its_version_after_a_restart(repository: Repository,
                                                              table: Any) -> None:
    """兩次拿到同一個 `version_id`，而且 `OPS#` 只被多寫了一次（`_revision` 只 +1）。"""
    _seed_tutorial(repository, f"{SLUG}@v1")
    operations = OperationCoordinator(repository)
    operations.accept(OPERATION)
    accepted_revision = repository.revision_of(ops_pk(OPERATION.operation_id))

    first = _allocate(repository, operations)
    after_first = repository.revision_of(ops_pk(OPERATION.operation_id))

    restarted_repository, restarted_operations = _restarted(table)
    second = _allocate(restarted_repository, restarted_operations)

    assert second.version_id == first.version_id == f"{SLUG}@v2"
    assert (second.supersedes, second.number) == (f"{SLUG}@v1", 2)
    # 第一次落地讓 `_revision` 從 accept 的值 +1；第二次沒有再寫，所以兩個值相等。
    assert after_first == accepted_revision + 1
    assert restarted_repository.revision_of(ops_pk(OPERATION.operation_id)) == after_first
    record = restarted_operations.load(OPERATION.operation_id)
    assert record is not None
    assert record.version_id == first.version_id


def test_the_ops_and_version_items_agree_field_by_field(repository: Repository,
                                                        table: Any) -> None:
    """§8 的人工驗收自動化：`OPS#` 與 `VERSION#` 兩個 item 逐欄比對，不只看測試 PASS。

    中間那次 `put_meta` 模擬 Phase 23 已經把第一次的 `VersionPlan` 寫成 VERSION item；
    重送時傳入不同的 `reason` 與規則，已保存的內容仍不得被改寫（設計 §14.2）。
    """
    _seed_tutorial(repository, f"{SLUG}@v1")
    operations = OperationCoordinator(repository)
    operations.accept(OPERATION)
    first = _allocate(repository, operations)
    repository.put_meta(TutorialVersion(version_id=first.version_id, slug=first.slug,
                                        supersedes=first.supersedes, reason=first.reason,
                                        rules_applied=list(first.rules_applied),
                                        s3_key=f"tutorials/{SLUG}/v{first.number}.md",
                                        published_at=None))

    restarted_repository, restarted_operations = _restarted(table)
    second = allocate_version(SLUG, OPERATION.operation_id, restarted_operations,
                              repository=restarted_repository,
                              reason="release:r_99", rules_applied=["R-012"])

    ops_item = restarted_repository.get_meta_item(ops_pk(OPERATION.operation_id))
    version_item = restarted_repository.get_meta_item(version_pk(first.version_id))
    assert ops_item is not None
    assert version_item is not None
    assert ops_item["version_id"] == version_item["version_id"] == second.version_id
    assert version_item["supersedes"] == second.supersedes == f"{SLUG}@v1"
    assert version_item["reason"] == second.reason == REASON
    assert version_item["rules_applied"] == list(second.rules_applied) == RULES
