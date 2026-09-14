"""Phase 24 Task 2／3：`Publisher` 的 `prepare` / `inspect` / `commit` 三段式單篇提交。

器材照 Phase 24 §7：`repo` 是接上 moto 表與 bucket 的 `Repository` 子類別（多記一個
`transact_calls`，並提供 `objects` 唯讀檢視與 `set_current_version`），`publisher` 是
`Publisher(repo, SiteRenderer(), operations)`，其中的 `prepare-meeting@v2` 已由 Phase 23 的
`create_version` 寫成完整未發布版本。`tests/unit/conftest.py`（owner P15）與
`tests/integration/conftest.py`（owner P06）都不是本 Phase 可以改的檔案（00A §3.2），
所以器材留在本檔。

**這裡全綠不代表 O3 通過。** moto 只證明程式邏輯與資料形狀；真實發布切點仍由 Phase 12
判定為 FAIL（`a2_after_transact_before_site` 是已知 partial），真實驗證延後到 P41／P59。
"""

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import boto3
import pytest
from moto import mock_aws

from training_kb.content import (
    DIFF_CONTENT_TYPE,
    MARKDOWN_CONTENT_TYPE,
    VersionPlan,
    create_version,
    diff_key,
    markdown_key,
    parse_version_id,
    put_private_artifact,
    render_markdown,
)
from training_kb.errors import CoordinationError, PublishError, TransientError
from training_kb.keys import tutorial_pk, version_pk
from training_kb.models import (
    Feature,
    StepDraft,
    StepType,
    Tutorial,
    TutorialContent,
    TutorialStatus,
    TutorialVersion,
)
from training_kb.operations import AcceptOperation, OperationCoordinator
from training_kb.publishing import (
    PreparedPublish,
    Publisher,
    PublishRequest,
    PublishResult,
    site_index_key,
    site_key,
    tutorial_index_key,
)
from training_kb.repository import Repository
from training_kb.site import SiteRenderer

SLUG = "prepare-meeting"
FEATURE = "Prepare"
V1 = f"{SLUG}@v1"
V2 = f"{SLUG}@v2"
OPERATION = "op-pub-2"
NOW = datetime(2026, 9, 14, 0, 30, tzinfo=UTC)
STAGED_V2 = (
    "operations/op-pub-2/site/tutorials/prepare-meeting/v2.diff.txt",
    "operations/op-pub-2/site/tutorials/prepare-meeting/v2.html",
)

TABLE_NAME = "training_kb"
BUCKET_NAME = "training-kb-content"
MOTO_REGION = "us-west-2"

_TEXTS = ("開啟行事曆。", "選擇今天的會議。", "開啟摘要。", "確認摘要內容。")
_TYPES = ("read", "click_ui", "click_ui", "read")


# --- 共用器材 ---------------------------------------------------------------


class RecordingRepository(Repository):
    """真實 `Repository` 行為 + 交易呼叫次數 + bucket 內容的唯讀檢視。

    只在 `Repository` 之上加測試需要的觀察點，沒有覆寫任何既有行為：`transact_write`
    先記一筆再原樣呼叫父類別，所以「`inspect` 沒過就 0 次交易」是真的被觀察到，
    不是被模擬出來的。
    """

    def __init__(self, table: Any, bucket: Any) -> None:
        super().__init__(table, bucket)
        self.table = table
        self.bucket = bucket
        self.transact_calls = 0

    @property
    def objects(self) -> tuple[str, ...]:
        return tuple(sorted(item.key for item in self.bucket.objects.all()))

    def transact_write(self, items: Any) -> int | None:
        self.transact_calls += 1
        return super().transact_write(items)

    def set_current_version(self, slug: str, version_id: str | None) -> None:
        pk = tutorial_pk(slug)
        self.update_meta(pk, {"current_version": version_id},
                         expected_revision=self.revision_of(pk))


def four_step_content() -> TutorialContent:
    """與 `tests/integration/test_create_version.py` 同形狀的四步草稿。"""
    steps = [
        StepDraft(number=index + 1, type=StepType(_TYPES[index]), text=_TEXTS[index],
                  feature_id=FEATURE)
        for index in range(4)
    ]
    return TutorialContent(title="準備會議",
                           problem="會議前的準備步驟散在多個頁面，新人找不到。",
                           prerequisites=["已登入工作區"], steps=steps,
                           expected_outcome="會議開始前已備妥議程與摘要。")


def version_plan(version_id: str, *, supersedes: str | None) -> VersionPlan:
    slug, number = parse_version_id(version_id)
    return VersionPlan(version_id=version_id, slug=slug, number=number, supersedes=supersedes,
                       reason="release:r_42" if supersedes else "gap:c12",
                       rules_applied=(), operation_id=f"op-test-{version_id}")


def seed_published_v1(repository: Repository) -> None:
    """已發布的 v1：VERSION item 有 `published_at`、S3 有 `v1.md`／`v1.diff`，教學指向它。"""
    repository.put_meta(Feature(feature_id=FEATURE, name=FEATURE, aliases=[], first_seen=NOW))
    repository.put_meta(Tutorial(slug=SLUG, current_version=None, topic="準備會議",
                                 feature_ids=[FEATURE], status=TutorialStatus.ACTIVE,
                                 successor=None, cluster_id="c12"))
    repository.put_meta(TutorialVersion(version_id=V1, slug=SLUG, supersedes=None,
                                        reason="gap:c12", rules_applied=[],
                                        s3_key=markdown_key(SLUG, 1), published_at=NOW))
    put_private_artifact(repository, markdown_key(SLUG, 1),
                         render_markdown(four_step_content()), MARKDOWN_CONTENT_TYPE)
    put_private_artifact(repository, diff_key(SLUG, 1), "", DIFF_CONTENT_TYPE)
    pk = tutorial_pk(SLUG)
    repository.update_meta(pk, {"current_version": V1},
                           expected_revision=repository.revision_of(pk))


@pytest.fixture
def repo() -> Iterator[RecordingRepository]:
    """moto 的本機表＋bucket；與 `tests/integration/conftest.py` 同一組資源形狀。"""
    with mock_aws():
        dynamodb = boto3.resource("dynamodb", region_name=MOTO_REGION)
        table = dynamodb.create_table(
            TableName=TABLE_NAME,
            KeySchema=[{"AttributeName": "PK", "KeyType": "HASH"},
                       {"AttributeName": "SK", "KeyType": "RANGE"}],
            AttributeDefinitions=[{"AttributeName": "PK", "AttributeType": "S"},
                                  {"AttributeName": "SK", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        table.wait_until_exists()
        bucket = boto3.resource("s3", region_name=MOTO_REGION).Bucket(BUCKET_NAME)
        bucket.create(CreateBucketConfiguration={"LocationConstraint": MOTO_REGION})
        yield RecordingRepository(table, bucket)


@pytest.fixture
def operations(repo: RecordingRepository) -> OperationCoordinator:
    """`commit` 最後會 `record_version`，所以 `OPS#op-pub-2` 必須先被 accept。"""
    coordinator = OperationCoordinator(repo)
    coordinator.accept(AcceptOperation(operation_id=OPERATION, kind="ticket",
                                       canonical_id="t_1", project_id="p_1", now=NOW))
    return coordinator


@pytest.fixture
def publisher(repo: RecordingRepository, operations: OperationCoordinator) -> Publisher:
    """`prepare-meeting@v2` 已由 Phase 23 的 `create_version` 寫成完整未發布版本。"""
    seed_published_v1(repo)
    create_version(version_plan(V2, supersedes=V1), four_step_content(), repo)
    return Publisher(repo, SiteRenderer(), operations)


def request_v2() -> PublishRequest:
    return PublishRequest(version_ids=(V2,), operation_id=OPERATION)


def site_keys(repo: RecordingRepository) -> list[str]:
    return [key for key in repo.objects if key.startswith("site/")]


# --- Task 2：prepare 與 inspect 只碰私有前綴 --------------------------------


def test_prepare_stages_privately_and_never_touches_site(
        publisher: Publisher, repo: RecordingRepository) -> None:
    """逐字取自 Phase 24 §7 Task 2 Step 1。"""
    request = PublishRequest(version_ids=(V2,), operation_id=OPERATION)
    prepared = publisher.prepare(request, now=NOW)
    assert prepared.staged_keys == STAGED_V2
    assert prepared.prepared_at == NOW
    assert site_keys(repo) == []
    version = repo.get_version(V2)
    tutorial = repo.get_tutorial(SLUG)
    assert version is not None and version.published_at is None
    assert tutorial is not None and tutorial.current_version == V1


def test_prepare_refuses_incomplete_version(
        publisher: Publisher, repo: RecordingRepository) -> None:
    """`verify_version_complete` 回 `False` 時丟 `PublishError`，零 staging、零公開檔案。"""
    repo.bucket.Object(diff_key(SLUG, 2)).delete()
    before = repo.objects
    with pytest.raises(PublishError, match="不完整"):
        publisher.prepare(request_v2(), now=NOW)
    assert repo.objects == before
    assert site_keys(repo) == []


def test_inspect_reports_moved_base_version(
        publisher: Publisher, repo: RecordingRepository) -> None:
    """`prepare` 之後基底位移：`inspect` 回 `ok=False`，`problems` 指出 `current_version`。"""
    prepared = publisher.prepare(request_v2(), now=NOW)
    assert publisher.inspect(prepared).ok is True
    repo.set_current_version(SLUG, f"{SLUG}@v9")
    inspection = publisher.inspect(prepared)
    assert inspection.ok is False
    assert any("current_version" in problem for problem in inspection.problems)


def test_inspect_reports_missing_staging(
        publisher: Publisher, repo: RecordingRepository) -> None:
    """§8 Boundary：staging 被刪掉時 `inspect` 擋下來。"""
    prepared = publisher.prepare(request_v2(), now=NOW)
    repo.bucket.Object(STAGED_V2[1]).delete()
    inspection = publisher.inspect(prepared)
    assert inspection.ok is False
    assert any(STAGED_V2[1] in problem for problem in inspection.problems)


def test_prepare_twice_reuses_the_same_staging_bytes(
        publisher: Publisher, repo: RecordingRepository) -> None:
    """§8 Boundary：同 operation 重送不產生第二份 HTML，bytes 完全相同。"""
    first = publisher.prepare(request_v2(), now=NOW)
    before = repo.get_object(STAGED_V2[1])
    second = publisher.prepare(request_v2(), now=NOW)
    assert second.staged_keys == first.staged_keys
    assert repo.get_object(STAGED_V2[1]) == before
    assert len([key for key in repo.objects if key.startswith("operations/")]) == 2


def test_key_helpers_return_relative_keys() -> None:
    """D-54：三個 helper 回的都不含 `site/` 前綴。"""
    assert site_key(V2) == "tutorials/prepare-meeting/v2.html"
    assert tutorial_index_key(SLUG) == "tutorials/prepare-meeting/index.html"
    assert site_index_key() == "index.html"


# --- Task 3：一筆交易同時切 published_at 與 current_version -----------------


def test_commit_switches_both_fields_then_writes_site(
        publisher: Publisher, repo: RecordingRepository) -> None:
    """逐字取自 Phase 24 §7 Task 3 Step 1（`發布教學版本` Rule 1、4、5）。"""
    prepared = publisher.prepare(PublishRequest((V2,), OPERATION), now=NOW)
    assert publisher.inspect(prepared).ok is True
    result = publisher.commit(prepared, now=NOW)
    assert result == PublishResult(published=(V2,), failed=None, reasons=())
    version = repo.get_version(V2)
    tutorial = repo.get_tutorial(SLUG)
    assert version is not None and version.published_at == NOW
    assert tutorial is not None and tutorial.current_version == V2
    assert "site/tutorials/prepare-meeting/v2.html" in repo.objects


def test_commit_refuses_when_base_version_moved(
        publisher: Publisher, repo: RecordingRepository) -> None:
    """逐字取自 Phase 24 §7 Task 3 Step 1 的第二個案例。"""
    prepared = publisher.prepare(PublishRequest((V2,), OPERATION), now=NOW)
    repo.set_current_version(SLUG, f"{SLUG}@v9")
    with pytest.raises(PublishError, match="current_version"):
        publisher.commit(prepared, now=NOW)
    assert repo.transact_calls == 0
    version = repo.get_version(V2)
    assert version is not None and version.published_at is None
    assert site_keys(repo) == []


def test_commit_writes_public_page_and_diff_copy_and_indexes(
        publisher: Publisher, repo: RecordingRepository) -> None:
    """每篇兩個公開物件，加上教學索引與站台索引；staging 與公開 bytes 完全相同。"""
    prepared = publisher.prepare(PublishRequest((V2,), OPERATION), now=NOW)
    publisher.commit(prepared, now=NOW)
    assert site_keys(repo) == [
        "site/index.html",
        "site/tutorials/prepare-meeting/index.html",
        "site/tutorials/prepare-meeting/v2.diff.txt",
        "site/tutorials/prepare-meeting/v2.html",
    ]
    for staged, public in zip(STAGED_V2, ("site/tutorials/prepare-meeting/v2.diff.txt",
                                          "site/tutorials/prepare-meeting/v2.html"),
                              strict=True):
        assert repo.get_object(staged) == repo.get_object(public)


def test_commit_never_exposes_unpublished_pages(
        publisher: Publisher, repo: RecordingRepository) -> None:
    """00A §3.8：`data-published="false"` 不得進 `site/`；交易後重新渲染才 promote。"""
    prepared = publisher.prepare(PublishRequest((V2,), OPERATION), now=NOW)
    staged_before = repo.get_object(STAGED_V2[1])
    assert staged_before is not None and b'data-published="false"' in staged_before
    publisher.commit(prepared, now=NOW)
    for key in site_keys(repo):
        body = repo.get_object(key)
        assert body is not None
        assert b'data-published="false"' not in body
    page = repo.get_object("site/tutorials/prepare-meeting/v2.html")
    assert page is not None and b'data-published="true"' in page


def test_commit_records_version_on_the_operation(
        publisher: Publisher, repo: RecordingRepository,
        operations: OperationCoordinator) -> None:
    """`commit` 最後把版號記進 operation 紀錄（write-once，重送同值 no-op）。"""
    prepared = publisher.prepare(PublishRequest((V2,), OPERATION), now=NOW)
    publisher.commit(prepared, now=NOW)
    record = operations.load(OPERATION)
    assert record is not None and record.version_id == V2


def test_commit_returns_result_when_transaction_is_cancelled(
        publisher: Publisher, repo: RecordingRepository) -> None:
    """位移發生在交易當下：條件不符回 `PublishResult`，不丟例外，兩欄皆不變、`site/` 無新檔。

    `inspect` 讀過之後才位移，所以只有 DynamoDB 的條件擋得住它——這正是交易存在的理由。
    """
    prepared = publisher.prepare(PublishRequest((V2,), OPERATION), now=NOW)
    inspect_then_move(publisher, repo, prepared)
    result = publisher.commit(prepared, now=NOW)
    assert result == PublishResult(published=(), failed=V2,
                                   reasons=("current_version 不等於 supersedes",))
    assert repo.transact_calls == 1
    version = repo.get_version(V2)
    tutorial = repo.get_tutorial(SLUG)
    assert version is not None and version.published_at is None
    assert tutorial is not None and tutorial.current_version == f"{SLUG}@v9"
    assert site_keys(repo) == []


def inspect_then_move(publisher: Publisher, repo: RecordingRepository,
                      prepared: PreparedPublish) -> None:
    """讓 `commit` 內部那次 `inspect` 先通過，回傳之後才把 `current_version` 改掉。"""
    original = publisher.inspect

    def moving(target: PreparedPublish) -> Any:
        publisher.inspect = original  # type: ignore[method-assign]
        outcome = original(target)
        repo.set_current_version(SLUG, f"{SLUG}@v9")
        return outcome

    publisher.inspect = moving  # type: ignore[method-assign]


def test_commit_refuses_already_published_version(
        publisher: Publisher, repo: RecordingRepository) -> None:
    """已發布的版本不可再被覆寫（設計 §8.1）：第二次 `commit` 被 `inspect` 擋下。"""
    prepared = publisher.prepare(PublishRequest((V2,), OPERATION), now=NOW)
    publisher.commit(prepared, now=NOW)
    with pytest.raises(PublishError, match="published_at"):
        publisher.commit(prepared, now=NOW)
    assert repo.transact_calls == 1


def test_commit_publishes_first_version_without_supersedes(
        repo: RecordingRepository, operations: OperationCoordinator) -> None:
    """§8 Happy：v1 首次發布（`supersedes=None`），`current_version` 由空切成 v1。"""
    repo.put_meta(Feature(feature_id=FEATURE, name=FEATURE, aliases=[], first_seen=NOW))
    repo.put_meta(Tutorial(slug=SLUG, current_version=None, topic="準備會議",
                           feature_ids=[FEATURE], status=TutorialStatus.ACTIVE,
                           successor=None, cluster_id="c12"))
    create_version(version_plan(V1, supersedes=None), four_step_content(), repo)
    publisher = Publisher(repo, SiteRenderer(), operations)
    prepared = publisher.prepare(PublishRequest((V1,), OPERATION), now=NOW)
    assert publisher.commit(prepared, now=NOW).published == (V1,)
    tutorial = repo.get_tutorial(SLUG)
    assert tutorial is not None and tutorial.current_version == V1
    index = repo.get_object("site/index.html")
    assert index is not None and "準備會議".encode() in index


def test_transaction_bumps_revision_so_stale_writers_lose(
        publisher: Publisher, repo: RecordingRepository) -> None:
    """交易與 `update_meta` 共用同一個 `_revision` CAS：切換過後舊的持有者一定失敗。

    只斷言 `_revision` 有 +1 還不算證明「舊持有者會輸」，所以最後真的拿發布前讀到的
    revision 去 `update_meta` 一次：它必須被條件式擋下（`CoordinationError`），
    而且 `current_version` 保持交易寫進去的值。
    """
    prepared = publisher.prepare(PublishRequest((V2,), OPERATION), now=NOW)
    before = repo.revision_of(tutorial_pk(SLUG))
    publisher.commit(prepared, now=NOW)
    assert repo.revision_of(tutorial_pk(SLUG)) == before + 1
    assert repo.revision_of(version_pk(V2)) >= 2
    with pytest.raises(CoordinationError, match="stale revision"):
        repo.update_meta(tutorial_pk(SLUG), {"current_version": V1},
                         expected_revision=before)
    tutorial = repo.get_tutorial(SLUG)
    assert tutorial is not None and tutorial.current_version == V2


def test_commit_records_the_version_before_it_writes_site(
        publisher: Publisher, repo: RecordingRepository, operations: OperationCoordinator,
        monkeypatch: pytest.MonkeyPatch) -> None:
    """切點 `a2_after_transact_before_site` 發生時，ledger 仍然留著版號。

    P59 的**單篇**復原輸入就是 `OPS#<operation_id>.version_id` + `site_key`（00A §6.7：
    單篇不寫 `pending-promote.json`）。`record_version` 若排在 S3 階段之後，a2 一發生
    ledger 就是 `None`，復原沒有東西可以重算（Phase 24 review Important 1）。
    """
    prepared = publisher.prepare(PublishRequest((V2,), OPERATION), now=NOW)

    def broken(version_id: str, operation_id: str) -> None:
        raise TransientError("a2_after_transact_before_site 注入")

    monkeypatch.setattr(publisher, "_promote", broken)
    with pytest.raises(PublishError, match="a2_after_transact_before_site"):
        publisher.commit(prepared, now=NOW)
    record = operations.load(OPERATION)
    assert record is not None and record.version_id == V2
    assert site_keys(repo) == []
