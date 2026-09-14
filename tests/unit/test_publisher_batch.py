"""Phase 25 Task 1／2：多篇教學整批發布的邊界、單一交易、待補清單與 promote 順序。

器材沿用 Phase 24 §7 的形狀：`repo` 是接上 moto 表與 bucket 的 `Repository` 子類別
（多記 `transact_calls`、`site_writes`，並提供 `objects` 唯讀檢視與
`move_base_during_transaction`），`publisher` 是 `Publisher(repo, SiteRenderer(), operations)`。
`tests/unit/conftest.py`（owner P15）與 `tests/integration/conftest.py`（owner P06）都不是
本 Phase 可以改的檔案（00A §3.2），所以器材留在本檔。

起始狀態是兩篇各有一個已發布舊版與一個完整未發布新版：

```text
TUTORIAL#prepare-meeting.current_version = prepare-meeting@v2   待發布 prepare-meeting@v3
TUTORIAL#share-summary  .current_version = share-summary@v1     待發布 share-summary@v2
```

**這裡全綠不代表 O3 通過、也不代表「多篇原子發布已驗收」。** moto 只證明程式邏輯與資料
形狀；O3 由 Phase 12 判定為 FAIL（交易成功後逐篇寫 `site/` 仍是 partial），真實 AWS 的切點
重跑延後至 P41／P59（controller 2026-09-14 裁決）。F49 沒有被放寬：只要一篇失敗就整批不發布。
"""

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import boto3
import pytest
from moto import mock_aws

from training_kb.content import (
    DIFF_CONTENT_TYPE,
    MARKDOWN_CONTENT_TYPE,
    PUBLIC_SITE_PREFIX,
    VersionPlan,
    create_version,
    diff_key,
    markdown_key,
    parse_version_id,
    put_private_artifact,
    render_markdown,
)
from training_kb.errors import PublishError, TransientError
from training_kb.keys import tutorial_pk
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
    MAX_BATCH_VERSIONS,
    PreparedPublish,
    Publisher,
    PublishRequest,
    assert_batch_publishable,
    build_commit_transaction,
    promote_site_objects,
)
from training_kb.repository import Repository
from training_kb.site import SiteRenderer

FEATURE = "Prepare"
SLUG_A = "prepare-meeting"
SLUG_B = "share-summary"
A2 = f"{SLUG_A}@v2"
A3 = f"{SLUG_A}@v3"
B1 = f"{SLUG_B}@v1"
B2 = f"{SLUG_B}@v2"
OPERATION = "op-review-0914"
NOW = datetime(2026, 9, 14, 0, 30, tzinfo=UTC)
PENDING_KEY = f"operations/{OPERATION}/pending-promote.json"
BATCH_SITE_KEYS = [
    "site/tutorials/prepare-meeting/v3.html",
    "site/tutorials/prepare-meeting/v3.diff.txt",
    "site/tutorials/share-summary/v2.html",
    "site/tutorials/share-summary/v2.diff.txt",
]
BATCH_INDEX_KEYS = [
    "site/tutorials/prepare-meeting/index.html",
    "site/tutorials/share-summary/index.html",
    "site/index.html",
]

TABLE_NAME = "training_kb"
BUCKET_NAME = "training-kb-content"
MOTO_REGION = "us-west-2"

_TEXTS = ("開啟行事曆。", "選擇今天的會議。", "開啟摘要。", "確認摘要內容。")
_TYPES = ("read", "click_ui", "click_ui", "read")


# --- 共用器材 ---------------------------------------------------------------


class BatchRepository(Repository):
    """真實 `Repository` 行為 + 三個觀察點，沒有覆寫任何既有語意。

    - `transact_calls`：整批只能送出**一次** `TransactWriteItems`。
    - `site_writes`：實際寫進 `site/` 的 key，**依寫入順序**；寫入失敗（例如條件寫入撞鍵）
      不入列，所以「重送略過」看得出來。
    - `move_base_during_transaction`：在 `transact_write` **被呼叫的那一刻**才改掉某篇的
      `current_version`，用來製造「`inspect` 通過之後、交易之前被別人插隊」的時間窗。
    """

    def __init__(self, table: Any, bucket: Any) -> None:
        super().__init__(table, bucket)
        self.table = table
        self.bucket = bucket
        self.transact_calls = 0
        self.site_writes: list[str] = []
        self._pending_move: tuple[str, str] | None = None

    @property
    def objects(self) -> dict[str, bytes]:
        keys = sorted(item.key for item in self.bucket.objects.all())
        return {key: body for key in keys if (body := self.get_object(key)) is not None}

    def put_object(self, key: str, body: bytes, content_type: str, *,
                   if_none_match: bool) -> None:
        super().put_object(key, body, content_type, if_none_match=if_none_match)
        if key.startswith(PUBLIC_SITE_PREFIX):
            self.site_writes.append(key)

    def transact_write(self, items: Any) -> int | None:
        self.transact_calls += 1
        if self._pending_move is not None:
            slug, version_id = self._pending_move
            self._pending_move = None
            self.set_current_version(slug, version_id)
        return super().transact_write(items)

    def move_base_during_transaction(self, slug: str, version_id: str) -> None:
        self._pending_move = (slug, version_id)

    def set_current_version(self, slug: str, version_id: str | None) -> None:
        pk = tutorial_pk(slug)
        self.update_meta(pk, {"current_version": version_id},
                         expected_revision=self.revision_of(pk))


def four_step_content(title: str) -> TutorialContent:
    """與 `tests/unit/test_publisher_single.py` 同形狀的四步草稿。"""
    steps = [
        StepDraft(number=index + 1, type=StepType(_TYPES[index]), text=_TEXTS[index],
                  feature_id=FEATURE)
        for index in range(4)
    ]
    return TutorialContent(title=title,
                           problem="會議前的準備步驟散在多個頁面，新人找不到。",
                           prerequisites=["已登入工作區"], steps=steps,
                           expected_outcome="會議開始前已備妥議程與摘要。")


def version_plan(version_id: str, *, supersedes: str | None) -> VersionPlan:
    slug, number = parse_version_id(version_id)
    return VersionPlan(version_id=version_id, slug=slug, number=number, supersedes=supersedes,
                       reason="release:r_42" if supersedes else "gap:c12",
                       rules_applied=(), operation_id=f"op-test-{version_id}")


def seed_tutorial(repository: Repository, slug: str, title: str, published: str,
                  draft: str) -> None:
    """一篇教學：已發布的舊版（VERSION item 有 `published_at`、S3 產物齊全、教學指向它）
    加上一個由 Phase 23 `create_version` 寫出的完整未發布新版。"""
    _, number = parse_version_id(published)
    content = four_step_content(title)
    repository.put_meta(Tutorial(slug=slug, current_version=None, topic=title,
                                 feature_ids=[FEATURE], status=TutorialStatus.ACTIVE,
                                 successor=None, cluster_id="c12"))
    repository.put_meta(TutorialVersion(version_id=published, slug=slug, supersedes=None,
                                        reason="gap:c12", rules_applied=[],
                                        s3_key=markdown_key(slug, number), published_at=NOW))
    put_private_artifact(repository, markdown_key(slug, number), render_markdown(content),
                         MARKDOWN_CONTENT_TYPE)
    put_private_artifact(repository, diff_key(slug, number), "", DIFF_CONTENT_TYPE)
    pk = tutorial_pk(slug)
    repository.update_meta(pk, {"current_version": published},
                           expected_revision=repository.revision_of(pk))
    create_version(version_plan(draft, supersedes=published), content, repository)


@pytest.fixture
def repo() -> Iterator[BatchRepository]:
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
        yield BatchRepository(table, bucket)


@pytest.fixture
def operations(repo: BatchRepository) -> OperationCoordinator:
    """整批的**父** operation；D-59：它不持有版號，版號在每篇自己的子 operation 上。"""
    coordinator = OperationCoordinator(repo)
    coordinator.accept(AcceptOperation(operation_id=OPERATION, kind="feedback-review",
                                       canonical_id="r_1", project_id="p_1", now=NOW))
    return coordinator


@pytest.fixture
def publisher(repo: BatchRepository, operations: OperationCoordinator) -> Publisher:
    repo.put_meta(Feature(feature_id=FEATURE, name=FEATURE, aliases=[], first_seen=NOW))
    seed_tutorial(repo, SLUG_A, "準備會議", A2, A3)
    seed_tutorial(repo, SLUG_B, "分享摘要", B1, B2)
    return Publisher(repo, SiteRenderer(), operations)


def batch_request() -> PublishRequest:
    return PublishRequest((A3, B2), OPERATION)


def site_keys(repo: BatchRepository) -> list[str]:
    return [key for key in repo.objects if key.startswith(PUBLIC_SITE_PREFIX)]


def action_pk(item: Any) -> str:
    """一個 `Update` action 指向的 item PK；交易組成的斷言只看得懂這一個欄位。"""
    return str(item["Update"]["Key"]["PK"])


def restage_as_published(repo: BatchRepository, prepared: PreparedPublish) -> None:
    """模擬 `Publisher._restage`：交易成功後 staging 會被已切換的欄位重新渲染一次。

    直接呼叫 `promote_site_objects` 的測試必須先做這一步，否則 staging 還帶
    `data-published="false"`，會被 `_put_public_object` 的 runtime 守門擋下（00A §3.8）。
    """
    for key in prepared.staged_keys:
        body = repo.get_object(key)
        assert body is not None
        repo.put_object(key, body.replace(b'data-published="false"',
                                          b'data-published="true"'),
                        "text/html; charset=utf-8", if_none_match=False)


# --- Task 1：整批邊界與單一交易 ---------------------------------------------


def test_commit_batch_switches_all_or_nothing(
        publisher: Publisher, repo: BatchRepository) -> None:
    """逐字取自 Phase 25 §7 Task 1 Step 1（F49：一篇失敗就整批不發布）。"""
    request = PublishRequest(("prepare-meeting@v3", "share-summary@v2"), "op-review-0914")
    prepared = publisher.prepare(request, now=NOW)
    assert publisher.inspect(prepared).ok is True
    repo.move_base_during_transaction("share-summary", "share-summary@v7")
    result = publisher.commit(prepared, now=NOW)
    assert result.published == () and result.failed == "share-summary@v2"
    assert repo.transact_calls == 1
    tutorial = repo.get_tutorial("prepare-meeting")
    version = repo.get_version("prepare-meeting@v3")
    assert tutorial is not None and tutorial.current_version == "prepare-meeting@v2"
    assert version is not None and version.published_at is None
    assert [key for key in repo.objects if key.startswith("site/")] == []


BAD_BATCHES = [((), "至少要有一個版本"),
               (tuple(f"t-{n}@v1" for n in range(51)), "最多 50 篇"),
               (("a@v1", "a@v1"), "重複的 version_id"), (("a@v1", "a@v2"), "同一篇教學")]


@pytest.mark.parametrize(("version_ids", "signal"), BAD_BATCHES)
def test_assert_batch_publishable_rejects_bad_batches(
        version_ids: tuple[str, ...], signal: str) -> None:
    """逐字取自 Phase 25 §7 Task 1 Step 4：四個邊界各一個拒絕理由。"""
    prepared = PreparedPublish(PublishRequest(version_ids, "op-1"), version_ids, (), NOW)
    with pytest.raises(PublishError, match=signal):
        assert_batch_publishable(prepared)


@pytest.mark.parametrize(("version_ids", "signal"), BAD_BATCHES)
def test_prepare_rejects_bad_batches_before_writing_any_staging(
        publisher: Publisher, repo: BatchRepository, version_ids: tuple[str, ...],
        signal: str) -> None:
    """拒絕必須發生在寫第一個 staging 物件之前：bucket 內容一個都沒變。"""
    before = repo.objects
    with pytest.raises(PublishError, match=signal):
        publisher.prepare(PublishRequest(version_ids, OPERATION), now=NOW)
    assert repo.objects == before


def test_max_batch_versions_is_the_transaction_limit() -> None:
    """`TransactWriteItems` 一次 100 個 action、每篇 2 個 → 最多 50 篇（§6）。"""
    assert MAX_BATCH_VERSIONS == 50


def test_prepare_stops_when_the_second_version_is_incomplete(
        publisher: Publisher, repo: BatchRepository) -> None:
    """§8 Failure：第二篇關係不完整 → `prepare` 丟 `PublishError`；零公開、零 DB 變更。"""
    repo.bucket.Object(diff_key(SLUG_B, 2)).delete()
    with pytest.raises(PublishError, match="不完整"):
        publisher.prepare(batch_request(), now=NOW)
    assert site_keys(repo) == []
    assert repo.transact_calls == 0
    for slug, current in ((SLUG_A, A2), (SLUG_B, B1)):
        tutorial = repo.get_tutorial(slug)
        assert tutorial is not None and tutorial.current_version == current


def test_build_commit_transaction_makes_two_actions_per_version_in_order(
        publisher: Publisher, repo: BatchRepository) -> None:
    """交易組成：每篇兩個 `Update`，順序固定 VERSION、TUTORIAL（`CANCEL_REASONS` 依它排）。"""
    prepared = publisher.prepare(batch_request(), now=NOW)
    items = build_commit_transaction(prepared, repository=repo, now=NOW)
    assert len(items) == 4
    assert [action_pk(item) for item in items] == [
        f"VERSION#{A3}", f"TUTORIAL#{SLUG_A}", f"VERSION#{B2}", f"TUTORIAL#{SLUG_B}"]


def test_build_commit_transaction_refuses_a_missing_version(
        publisher: Publisher, repo: BatchRepository) -> None:
    """`get_version` 回 `None` 時丟 `PublishError`，不是 `AttributeError`。"""
    prepared = publisher.prepare(batch_request(), now=NOW)
    missing = PreparedPublish(prepared.request, (A3, f"{SLUG_B}@v9"),
                              prepared.staged_keys, NOW)
    with pytest.raises(PublishError, match="不存在，不能提交"):
        build_commit_transaction(missing, repository=repo, now=NOW)


def test_commit_batch_publishes_every_version_in_request_order(
        publisher: Publisher, repo: BatchRepository) -> None:
    """§8 Happy：兩篇都完整 → 一次交易切 4 個欄位，`published` 順序與請求相同。"""
    prepared = publisher.prepare(batch_request(), now=NOW)
    result = publisher.commit(prepared, now=NOW)
    assert result.published == (A3, B2)
    assert result.failed is None and result.reasons == ()
    assert repo.transact_calls == 1
    for version_id, slug in ((A3, SLUG_A), (B2, SLUG_B)):
        version = repo.get_version(version_id)
        tutorial = repo.get_tutorial(slug)
        assert version is not None and version.published_at == NOW
        assert tutorial is not None and tutorial.current_version == version_id


def test_parent_operation_never_holds_a_version_id_for_a_batch(
        publisher: Publisher, repo: BatchRepository,
        operations: OperationCoordinator) -> None:
    """D-59：`OperationRecord.version_id` 是單值，多篇的父 operation 不持有版號。

    每篇的版號由上游（P48／P52）在各自的 per-slug 子 operation 上 `allocate_version` 時記過，
    父 operation 只負責整批追溯；在這裡硬寫第二篇會直接撞 `CoordinationError`。
    """
    publisher.commit(publisher.prepare(batch_request(), now=NOW), now=NOW)
    record = operations.load(OPERATION)
    assert record is not None and record.version_id is None


# --- Task 2：待補清單與 promote 順序 ----------------------------------------


def test_commit_records_pending_keys_then_promotes_in_fixed_order(
        publisher: Publisher, repo: BatchRepository) -> None:
    """逐字取自 Phase 25 §7 Task 2 Step 1。

    同時鎖住兩件事：待補清單在第一個公開物件出現**之前**就已存在，以及
    「版本頁 → 教學索引 → 站台索引」的順序。
    """
    request = PublishRequest(("prepare-meeting@v3", "share-summary@v2"), "op-review-0914")
    prepared = publisher.prepare(request, now=NOW)
    publisher.commit(prepared, now=NOW)
    pending = json.loads(repo.objects["operations/op-review-0914/pending-promote.json"])
    assert pending["site_keys"] == ["site/tutorials/prepare-meeting/v3.html",
                                    "site/tutorials/prepare-meeting/v3.diff.txt",
                                    "site/tutorials/share-summary/v2.html",
                                    "site/tutorials/share-summary/v2.diff.txt"]
    assert repo.site_writes == pending["site_keys"] + [
        "site/tutorials/prepare-meeting/index.html",
        "site/tutorials/share-summary/index.html", "site/index.html"]


def test_pending_promote_list_exists_when_the_first_restage_breaks(
        publisher: Publisher, repo: BatchRepository,
        monkeypatch: pytest.MonkeyPatch) -> None:
    """整批切點：交易已成功、**第一次 `_restage` 就中斷** → 待補清單仍然已經寫出去。

    父 operation 依 D-59 不持有版號，所以 `operations/<op>/pending-promote.json` 是 P59
    復原**整批**的唯一輸入。它排在 N 次 `_restage` 之後的話，這個切點會讓交易已切換、
    待補清單卻不存在，復原沒有任何輸入可用（Phase 25 review 必修 A1）。
    """
    prepared = publisher.prepare(batch_request(), now=NOW)

    def broken(*_args: Any, **_kwargs: Any) -> None:
        raise TransientError("restage 中斷")

    monkeypatch.setattr(publisher, "_restage", broken)
    with pytest.raises(PublishError, match="a3_after_first_site_before_second"):
        publisher.commit(prepared, now=NOW)
    pending = json.loads(repo.objects[PENDING_KEY])
    assert pending == {"version_ids": [A3, B2], "site_keys": BATCH_SITE_KEYS}
    assert site_keys(repo) == []


def test_pending_promote_list_stays_in_the_private_prefix(
        publisher: Publisher, repo: BatchRepository) -> None:
    """待補清單只寫私有 `operations/`，`TUTORIAL`／`VERSION` item 一個欄位都沒多。"""
    publisher.commit(publisher.prepare(batch_request(), now=NOW), now=NOW)
    pending = json.loads(repo.objects[PENDING_KEY])
    assert pending == {"version_ids": [A3, B2], "site_keys": BATCH_SITE_KEYS}
    assert repo.get_version(A3) is not None and repo.get_tutorial(SLUG_A) is not None
    item = repo.get_meta_item(tutorial_pk(SLUG_A))
    assert item is not None and "site_keys" not in item and "pending_promote" not in item


def test_promote_site_objects_returns_public_keys_in_request_order(
        publisher: Publisher, repo: BatchRepository) -> None:
    """每篇兩個公開物件（版本頁先、公開 diff 副本後，D-54），順序同 `version_ids`。"""
    prepared = publisher.prepare(batch_request(), now=NOW)
    restage_as_published(repo, prepared)
    assert promote_site_objects(prepared, repository=repo) == tuple(BATCH_SITE_KEYS)
    assert repo.site_writes == BATCH_SITE_KEYS


def test_promote_site_objects_stops_when_staging_is_gone(
        publisher: Publisher, repo: BatchRepository) -> None:
    """staging 物件不見了 → `PublishError`，停在那裡不繼續往下搬。"""
    prepared = publisher.prepare(batch_request(), now=NOW)
    restage_as_published(repo, prepared)
    repo.site_writes.clear()
    repo.bucket.Object(f"operations/{OPERATION}/site/tutorials/{SLUG_B}/v2.html").delete()
    with pytest.raises(PublishError, match="staging 物件不見了"):
        promote_site_objects(prepared, repository=repo)
    assert repo.site_writes == BATCH_SITE_KEYS[:2]


def test_promote_site_objects_refuses_to_overwrite_different_bytes(
        publisher: Publisher, repo: BatchRepository) -> None:
    """公開 key 已存在但 bytes 不同 → `PublishError` 且不覆寫已發布內容。"""
    prepared = publisher.prepare(batch_request(), now=NOW)
    restage_as_published(repo, prepared)
    someone_else = "<article>別人先發布的內容</article>".encode()
    repo.put_object(BATCH_SITE_KEYS[0], someone_else, "text/html; charset=utf-8",
                    if_none_match=False)
    with pytest.raises(PublishError, match="已存在且內容不同"):
        promote_site_objects(prepared, repository=repo)
    assert repo.get_object(BATCH_SITE_KEYS[0]) == someone_else


def test_promote_site_objects_skips_identical_resend(
        publisher: Publisher, repo: BatchRepository) -> None:
    """同 operation 重送、公開 key 已存在且 bytes 相同 → 不再寫入但仍回同一組 key。"""
    prepared = publisher.prepare(batch_request(), now=NOW)
    restage_as_published(repo, prepared)
    assert promote_site_objects(prepared, repository=repo) == tuple(BATCH_SITE_KEYS)
    repo.site_writes.clear()
    assert promote_site_objects(prepared, repository=repo) == tuple(BATCH_SITE_KEYS)
    assert repo.site_writes == []


def test_promote_site_objects_refuses_unpublished_marker(
        publisher: Publisher, repo: BatchRepository) -> None:
    """00A §3.8 的 runtime 守門：staging 還帶 `data-published="false"` 就不得進 `site/`。

    `prepare` 那次渲染 `published_at` 必然是 `None`，所以直接 promote（沒有先經
    `Publisher._restage` 重新渲染）一定撞到這道守門——公開前綴一個物件都不會出現。
    """
    prepared = publisher.prepare(batch_request(), now=NOW)
    with pytest.raises(PublishError, match="未發布標記不得進公開前綴"):
        promote_site_objects(prepared, repository=repo)
    assert site_keys(repo) == []


# --- 代修 Phase 24 review：交易後的收尾不得留下「半發布＋非 PublishError」-----


def test_batch_commit_does_not_touch_the_parent_operation_ledger(
        publisher: Publisher, repo: BatchRepository,
        operations: OperationCoordinator) -> None:
    """D-59：父 operation 已經持有別的版號時，整批發布也不該去動它。

    Phase 24 的 `commit` 對第二篇呼叫 `record_version` 會丟 `CoordinationError`，而且那個
    例外在 S3 階段之外——會留下「DynamoDB 兩篇都切、`site/` 只寫一篇、例外型別不是
    `PublishError`」的半發布。整批路徑改成不寫父 operation 之後，這條路徑消失。
    """
    operations.record_version(OPERATION, "another-tutorial@v1")
    result = publisher.commit(publisher.prepare(batch_request(), now=NOW), now=NOW)
    assert result.published == (A3, B2)
    record = operations.load(OPERATION)
    assert record is not None and record.version_id == "another-tutorial@v1"
    assert site_keys(repo) == sorted(BATCH_SITE_KEYS + BATCH_INDEX_KEYS)


def test_single_commit_turns_a_ledger_conflict_into_publish_error(
        publisher: Publisher, repo: BatchRepository,
        operations: OperationCoordinator) -> None:
    """單篇：operation 已持有別的版號 → `PublishError`，而且 `site/` 一個物件都沒寫出去。

    `record_version` 排在 S3 階段之前，所以衝突時公開站完全沒動；交易已經切換，因此它是
    切點 `a2_after_transact_before_site`，**一律以 `PublishError` 現身**，不讓
    `CoordinationError` 直接漏出去讓呼叫端誤判成別的故障。
    """
    operations.record_version(OPERATION, "another-tutorial@v1")
    prepared = publisher.prepare(PublishRequest((A3,), OPERATION), now=NOW)
    with pytest.raises(PublishError, match="a2_after_transact_before_site"):
        publisher.commit(prepared, now=NOW)
    version = repo.get_version(A3)
    assert version is not None and version.published_at == NOW
    assert site_keys(repo) == []


def test_single_publish_writes_no_pending_promote_list(
        publisher: Publisher, repo: BatchRepository) -> None:
    """00A §6.7：單篇不寫 `pending-promote.json`（P59 用 ledger 的版號 + `site_key` 重算）。"""
    publisher.commit(publisher.prepare(PublishRequest((A3,), OPERATION), now=NOW), now=NOW)
    assert PENDING_KEY not in repo.objects
