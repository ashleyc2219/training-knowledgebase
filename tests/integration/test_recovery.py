"""Phase 59：五個 `TKB_FAULT` 切點的可觀察結果、整批不切換與同 operation 復原。

前半在 moto 上跑（不標 marker），後半 `@pytest.mark.aws` 對**真實** `us-east-1` 的
`training_kb` 表與內容 bucket 演練同一組切點；未設 `TKB_RUN_AWS_INTEGRATION=1` 時由
`tests/conftest.py` 自動 skip，真 AWS 那幾條另外要求 `TKB_CONTENT_BUCKET`。

**本計畫選擇（2026-09-14）：`World.deliver_release` 直接依序驅動
`ingress.accept_release` → `content.allocate_version`／`create_version` →
`publishing.Publisher.prepare`／`commit`，不經 `pipelines.release.run_release_update`。**
五個切點全在這條直線上（§1 的流程圖就是這個順序），而 `run_release_update` 需要 Bedrock
（**O5 BLOCKED**，`docs/plan/report/o5-20260915T030245Z.md`），接上去只會讓每個切點都先
撞模型。模型段以 `World._run_model` 的假輸出替身表示：第一次寫一個 `model-output` ref 並
`record_model_output`，之後只要 ledger 已有 ref 就完全不呼叫——「重送期間模型呼叫數為 0」
因此是真的被觀察到，不是被繞過。

**O3 仍是 FAIL**（P12，`docs/plan/report/o3-20260914t181109z.md`）。本檔的綠燈只代表
「補償有效」，**不代表發布故障驗收通過**；切點 4 的 `current_version` 已切換而公開頁未寫
就是 O3 缺口本身，測試對它單獨斷言，不改寫成寬鬆通過。
"""

import json
import os
from collections.abc import Iterator
from datetime import UTC, datetime
from time import monotonic
from typing import Any

import boto3
import pytest

from training_kb import ingress
from training_kb.config import load_settings
from training_kb.content import (
    DIFF_CONTENT_TYPE,
    MARKDOWN_CONTENT_TYPE,
    allocate_version,
    create_version,
    diff_key,
    markdown_key,
    put_private_artifact,
    render_markdown,
)
from training_kb.errors import PublishError, TransientError
from training_kb.faults import FAULT_POINTS
from training_kb.keys import operation_ref, tutorial_pk
from training_kb.models import (
    Feature,
    Feedback,
    ProcStatus,
    ProcStep,
    ProvenWorkflow,
    Release,
    ReleaseKind,
    ReleaseSource,
    StepDraft,
    StepType,
    Tutorial,
    TutorialContent,
    TutorialStatus,
    TutorialStep,
    TutorialVersion,
)
from training_kb.operations import OperationCoordinator
from training_kb.publishing import (
    PENDING_PROMOTE_NAME,
    Publisher,
    PublishRequest,
    public_site_keys,
    resume_publish,
    site_key,
)
from training_kb.repository import Repository
from training_kb.rote import on_new_success
from training_kb.site import SiteRenderer

PUBLIC = "site/"
SLUG = "prepare-meeting"
SLUG_B = "share-summary"
FEATURE = "Prepare"
FEATURE_B = "Share"
NOW = datetime(2026, 9, 14, 1, 0, tzinfo=UTC)
SIGNATURE = "a1b2c3d4e5f60718"
MODEL_OUTPUT_NAME = "model-output"
PROJECT = "demo"


# --- 1. 測試資料 -------------------------------------------------------------


def content_for(slug: str, feature: str) -> TutorialContent:
    texts = ("開啟行事曆。", "選擇今天的會議。", "開啟摘要。", "確認摘要內容。")
    types = (StepType.READ, StepType.CLICK_UI, StepType.CLICK_UI, StepType.READ)
    steps = [StepDraft(number=index + 1, type=types[index], text=texts[index],
                       feature_id=feature) for index in range(4)]
    return TutorialContent(title=f"{slug} 教學",
                           problem="步驟散在多個頁面，新人找不到。",
                           prerequisites=["已登入工作區"], steps=steps,
                           expected_outcome="會議開始前已備妥議程與摘要。")


def _release(release_id: str) -> Release:
    return Release(id=release_id, source_event_id=None, source=ReleaseSource.CHANGELOG,
                   feature=FEATURE, kind=ReleaseKind.CHANGED, old_name=None, new_name=None,
                   evidence="changelog 第 3 行：摘要按鈕改名。", ts=NOW)


class RecordingStarter:
    """假 `PipelineStarter`：只把啟動記下來，回固定 ARN。"""

    def __init__(self) -> None:
        self.started: list[tuple[str, str]] = []

    def start(self, pipeline: str, execution_name: str, input: dict[str, Any]) -> str:
        self.started.append((pipeline, execution_name))
        return f"arn:aws:states:us-east-1:111122223333:execution:{pipeline}:{execution_name}"


# --- 2. World：把真實路徑包成測試門面 -----------------------------------------


class World:
    """一次 Release 從接入到公開的真實路徑；五個切點都在 `deliver_release` 上。"""

    def __init__(self, repository: Repository) -> None:
        self.repository = repository
        self.operations = OperationCoordinator(repository)
        self.publisher = Publisher(repository, SiteRenderer(), self.operations)
        self.starter = RecordingStarter()
        self.signature = SIGNATURE
        self.model_calls = 0
        self.model_calls_during_resend = 0
        self.v1_html = ""
        self.features: dict[str, str] = {}
        self.public_seeded: list[str] = []

    # --- seed ---

    def seed_one(self, slug: str, feature: str) -> None:
        """一篇教學：Feature、Tutorial、已發布的 v1 與它的兩個私有產物。"""
        self.features[slug] = feature
        self.repository.put_meta(Feature(feature_id=feature, name=feature, aliases=[],
                                         first_seen=NOW))
        self.repository.put_meta(Tutorial(
            slug=slug, current_version=None, topic=f"{slug} 教學", feature_ids=[feature],
            status=TutorialStatus.ACTIVE, successor=None, cluster_id="c12"))
        self.repository.put_meta(TutorialVersion(
            version_id=f"{slug}@v1", slug=slug, supersedes=None, reason="gap:c12",
            rules_applied=[], s3_key=markdown_key(slug, 1), published_at=NOW))
        put_private_artifact(self.repository, markdown_key(slug, 1),
                             render_markdown(content_for(slug, feature)),
                             MARKDOWN_CONTENT_TYPE)
        put_private_artifact(self.repository, diff_key(slug, 1), "", DIFF_CONTENT_TYPE)
        pk = tutorial_pk(slug)
        self.repository.update_meta(pk, {"current_version": f"{slug}@v1"},
                                    expected_revision=self.repository.revision_of(pk))
        self._seed_public((slug,))

    def seed(self, *slugs: str) -> None:
        """每篇都有一版**已發布**的 v1，而且公開站真的有它的三個物件。"""
        features = {SLUG: FEATURE, SLUG_B: FEATURE_B}
        for slug in slugs:
            self.seed_one(slug, features[slug])
        self.repository.put_meta(Feedback(id="fb-p59", tutorial_version=f"{SLUG}@v1", rating=5,
                                          category=None, comment=None, user="u1", ts=NOW))
        self.repository.put_meta(ProvenWorkflow(
            signature=self.signature, domain="changelog", adapter="changelog_release",
            steps=[ProcStep(tool="normalize_release", args={"payload": "$event.payload"})],
            keys=["id"], success_count=1, fail_count=0, status=ProcStatus.ACTIVE, last_used=NOW))
        self.v1_html = self.public_html(f"{SLUG}@v1")

    def _seed_public(self, slugs: tuple[str, ...]) -> None:
        """v1 的上一次發布已經把公開頁寫出去了：公開站的**舊世代**必須真的存在。"""
        renderer = SiteRenderer()
        for slug in slugs:
            tutorial = self.repository.get_tutorial(slug)
            version = self.repository.get_version(f"{slug}@v1")
            assert tutorial is not None and version is not None
            content = content_for(slug, tutorial.feature_ids[0])
            steps = [TutorialStep(tutorial_version=f"{slug}@v1", number=draft.number,
                                  type=draft.type, text=draft.text, feature_id=draft.feature_id)
                     for draft in content.steps]
            self._write_public(f"{PUBLIC}{site_key(f'{slug}@v1')}",
                               renderer.render_version_page(tutorial, version, steps, content))
            self._write_public(f"{PUBLIC}tutorials/{slug}/index.html",
                               renderer.render_tutorial_index(tutorial, [version]))
            self.public_seeded.append(slug)
        seeded = [self.tutorial(slug) for slug in self.public_seeded]
        self._write_public(f"{PUBLIC}index.html", renderer.render_site_index(seeded))

    def _write_public(self, key: str, page: str) -> None:
        self.repository.put_object(key, page.encode("utf-8"), "text/html; charset=utf-8",
                                   if_none_match=False)

    # --- 驅動 ---

    def deliver_release(self, release_id: str, *, slug: str = SLUG) -> str:
        """接入 → 模型段 → 建版 → 發布；同一個 `release_id` 重送會走到同一個 operation。

        `status == "done"` 的重送直接取既有結果（§6 的重送流程圖），不新增版本、回饋樣本
        或 PROC 樣本；其餘狀態沿用 `version_id` 與 `model_output_refs` 把缺的補齊。
        """
        acceptance = ingress.accept_release(_release(release_id), deadline=monotonic() + 60)
        operation_id = acceptance.operation_id
        done = acceptance.record.status == "done" and acceptance.record.version_id is not None
        if done:
            return str(acceptance.record.version_id)
        self._run_model(operation_id)
        version_id = self.build_version(operation_id, slug)
        self._count_proc_sample(operation_id)
        self.publish(operation_id, (version_id,))
        self.operations.complete(operation_id, now=NOW)
        return version_id

    def build_version(self, operation_id: str, slug: str) -> str:
        plan = allocate_version(slug, operation_id, self.operations,
                                repository=self.repository, reason=f"release:{operation_id}",
                                rules_applied=())
        tutorial = self.repository.get_tutorial(slug)
        assert tutorial is not None
        create_version(plan, content_for(slug, tutorial.feature_ids[0]), self.repository)
        return plan.version_id

    def public_bodies(self, version_id: str) -> bytes:
        return self.repository.get_object(self.public_key(version_id)) or b""

    def publish(self, operation_id: str, version_ids: tuple[str, ...]) -> None:
        prepared = self.publisher.prepare(PublishRequest(version_ids, operation_id), now=NOW)
        self.publisher.commit(prepared, now=NOW)

    def publish_batch(self, version_ids: tuple[str, ...], *, operation_id: str) -> None:
        """整批發布：版本先各自在子 operation 建好（D-59 父 operation 不持有版號）。"""
        self.publish(operation_id, version_ids)

    def resume(self, operation_id: str) -> None:
        """補償重送：只呼叫 `resume_publish`，模型段完全不進場。"""
        before = self.model_calls
        resume_publish(operation_id, operations=self.operations, repository=self.repository,
                       publisher=self.publisher, now=NOW)
        self.model_calls_during_resend = self.model_calls - before

    def _run_model(self, operation_id: str) -> None:
        """模型段替身：ledger 已有 `model_output_refs` 就完全不呼叫（設計 §14.2）。"""
        record = self.operations.load(operation_id)
        if record is not None and record.model_output_refs:
            return
        self.model_calls += 1
        ref = operation_ref(operation_id, MODEL_OUTPUT_NAME)
        self.repository.put_object(ref, b'{"p59": "fake"}', "application/json",
                                   if_none_match=False)
        self.operations.record_model_output(operation_id, ref)

    def _count_proc_sample(self, operation_id: str) -> None:
        """Phase 35 的 `on_new_success`：只有 `record_proc_sample` 回 `True` 才加一。"""
        proc = self.repository.get_proc(self.signature)
        assert proc is not None
        updated = on_new_success(proc, operation_id, self.operations, NOW)
        if updated is not proc:
            self.repository.put_meta(updated, create_only=False)

    # --- 觀察 ---

    def public_key(self, version_id: str) -> str:
        return PUBLIC + site_key(version_id)

    def public_html(self, version_id: str) -> str:
        return (self.repository.get_object(self.public_key(version_id)) or b"").decode()

    def object_exists(self, key: str) -> bool:
        return self.repository.object_exists(key)

    def tutorial_index(self, slug: str) -> str:
        body = self.repository.get_object(f"{PUBLIC}tutorials/{slug}/index.html")
        return (body or b"").decode()

    def tutorial(self, slug: str = SLUG) -> Tutorial:
        found = self.repository.get_tutorial(slug)
        assert found is not None
        return found

    def operation(self, operation_id: str) -> Any:
        return self.operations.load(operation_id)

    def counters(self) -> tuple[int, int, int]:
        proc = self.repository.get_proc(self.signature)
        assert proc is not None
        return (len(self.repository.scan_entity("VERSION")),
                len(self.repository.scan_entity("FEEDBACK")),
                proc.success_count)


@pytest.fixture
def world(repository: Repository, monkeypatch: pytest.MonkeyPatch) -> Iterator[World]:
    """moto 的表與 bucket ＋ 已發布 v1 ＋ 被換掉的 `ingress._wiring`。"""
    built = World(repository)
    built.seed(SLUG, SLUG_B)
    wiring = ingress.Wiring(operations=built.operations, starter=built.starter,
                            repository=repository, settings=load_settings({}))
    ingress._reset_wiring()
    monkeypatch.setattr(ingress, "_wiring", lambda: wiring)
    monkeypatch.delenv("TKB_FAULT", raising=False)
    monkeypatch.setenv("TKB_ENV", "dev")
    yield built
    ingress._reset_wiring()


# --- 3. 切點矩陣 -------------------------------------------------------------


@pytest.mark.parametrize("point", FAULT_POINTS)
def test_no_public_change_after_injected_fault(point: str, world: World,
                                               monkeypatch: pytest.MonkeyPatch) -> None:
    """Given 任一切點注入，When 一次 Release 送達，Then 公開站仍整批是舊狀態。

    切點 4 的 `InjectedFault` 會被 `Publisher._after_transaction` 轉成 `PublishError`
    （設計 §8.3），所以這裡收兩種型別，並單獨斷言切點代號。
    """
    monkeypatch.setenv("TKB_FAULT", point)
    with pytest.raises((TransientError, PublishError)) as caught:
        world.deliver_release("r_42")
    if point == "publish_after_transact_before_site":
        assert "a2_after_transact_before_site" in str(caught.value)
    assert world.public_html(f"{SLUG}@v1") == world.v1_html
    assert not world.object_exists(world.public_key(f"{SLUG}@v2"))
    assert "v2.html" not in world.tutorial_index(SLUG)
    if point != "publish_after_transact_before_site":
        assert world.tutorial().current_version == f"{SLUG}@v1"


def test_cut_point_4_is_the_o3_gap(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    """Given 切點 4，Then `current_version` 已切換、`published_at` 有值，但公開頁不存在。

    這是 **O3 = FAIL** 的缺口本身（設計 §18 O3）：補償重送有效不等於原子性通過，
    本測試只記錄事實，不得被讀成「發布故障驗收已通過」。
    """
    monkeypatch.setenv("TKB_FAULT", "publish_after_transact_before_site")
    with pytest.raises(PublishError, match="a2_after_transact_before_site"):
        world.deliver_release("r_42")
    version = world.repository.get_version(f"{SLUG}@v2")
    assert version is not None and version.published_at is not None
    assert world.tutorial().current_version == f"{SLUG}@v2"
    assert not world.object_exists(world.public_key(f"{SLUG}@v2"))
    assert "v2.html" not in world.tutorial_index(SLUG)


def test_batch_publish_is_all_or_nothing(world: World,
                                         monkeypatch: pytest.MonkeyPatch) -> None:
    """Given 兩篇整批在切點 3 失敗，Then 兩篇同時維持舊狀態（F49）。"""
    parent = "op-release-r_batch"
    version_ids = tuple(world.build_version(f"op-release-r_{slug}", slug)
                        for slug in (SLUG, SLUG_B)
                        if _accept_sub(world, f"op-release-r_{slug}", slug))
    monkeypatch.setenv("TKB_FAULT", "publish_before_transact")
    _accept_sub(world, parent, "r_batch")
    with pytest.raises(TransientError, match="publish_before_transact"):
        world.publish_batch(version_ids, operation_id=parent)
    for version_id in version_ids:
        slug = version_id.split("@")[0]
        assert world.tutorial(slug).current_version == f"{slug}@v1"
        assert not world.object_exists(world.public_key(version_id))


def test_batch_resume_uses_pending_promote_list(world: World,
                                                monkeypatch: pytest.MonkeyPatch) -> None:
    """Given 兩篇在切點 4 中斷，When 同 operation 復原，Then 依 `pending-promote.json` 補齊。"""
    parent = "op-release-r_batch"
    version_ids = tuple(world.build_version(f"op-release-r_{slug}", slug)
                        for slug in (SLUG, SLUG_B)
                        if _accept_sub(world, f"op-release-r_{slug}", slug))
    _accept_sub(world, parent, "r_batch")
    monkeypatch.setenv("TKB_FAULT", "publish_after_transact_before_site")
    with pytest.raises(PublishError, match="a3_after_first_site_before_second"):
        world.publish_batch(version_ids, operation_id=parent)
    pending = world.repository.get_object(operation_ref(parent, PENDING_PROMOTE_NAME))
    assert pending is not None
    assert json.loads(pending)["site_keys"] == list(public_site_keys(version_ids))
    for version_id in version_ids:
        assert not world.object_exists(world.public_key(version_id))
    monkeypatch.delenv("TKB_FAULT")
    world.resume(parent)
    for version_id in version_ids:
        assert world.object_exists(world.public_key(version_id))
        assert b'data-published="false"' not in (
            world.repository.get_object(world.public_key(version_id)) or b"")


def _accept_sub(world: World, operation_id: str, canonical_id: str) -> bool:
    """幫子 operation 在 ledger 開一筆（`allocate_version` 要求先被接受）。"""
    from training_kb.operations import AcceptOperation
    world.operations.accept(AcceptOperation(operation_id=operation_id, kind="release",
                                            canonical_id=canonical_id, project_id=PROJECT,
                                            now=NOW))
    return True


# --- 4. 同 operation 重送 -----------------------------------------------------


def test_resend_reuses_version_and_model_output(world: World,
                                                monkeypatch: pytest.MonkeyPatch) -> None:
    """Given 切點 4 中斷，When 同 operation 補償重送，Then 沿用版號與模型輸出、公開頁補齊。"""
    monkeypatch.setenv("TKB_FAULT", "publish_after_transact_before_site")
    with pytest.raises(PublishError):
        world.deliver_release("r_42")
    first = world.operation("op-release-r_42")
    monkeypatch.delenv("TKB_FAULT")
    world.resume("op-release-r_42")
    again = world.operation("op-release-r_42")
    assert again.version_id == first.version_id == f"{SLUG}@v2"
    assert again.model_output_refs == first.model_output_refs
    assert world.model_calls_during_resend == 0
    assert world.object_exists(f"site/tutorials/{SLUG}/v2.html")
    assert b'data-published="false"' not in (
        world.repository.get_object(world.public_key(f"{SLUG}@v2")) or b"")


@pytest.mark.parametrize("point", ["s3_after_md", "ddb_after_version",
                                   "publish_before_transact", "start_execution"])
def test_resend_after_early_cut_points_converges(point: str, world: World,
                                                 monkeypatch: pytest.MonkeyPatch) -> None:
    """Given 切點 1／2／3／5 中斷，When 清掉開關以同一事件重送，Then 收斂到同一個 v2。

    這四個切點都在交易之前，所以重送走**完整**路徑（不是補償路徑）；版號來自 ledger，
    模型輸出沿用既有 ref。切點 5 在模型段**之前**（連 operation 都還沒啟動流程），
    所以那一次重送模型是第一次跑，計數 +1；切點 1／2／3 在模型段之後，重送必須是 0。
    """
    monkeypatch.setenv("TKB_FAULT", point)
    with pytest.raises(TransientError):
        world.deliver_release("r_42")
    calls_before = world.model_calls
    expected_new_calls = 1 if point == "start_execution" else 0
    assert calls_before == (0 if point == "start_execution" else 1)
    monkeypatch.delenv("TKB_FAULT")
    version_id = world.deliver_release("r_42")
    assert version_id == f"{SLUG}@v2"
    assert world.model_calls == calls_before + expected_new_calls
    assert world.tutorial().current_version == f"{SLUG}@v2"
    assert world.object_exists(world.public_key(f"{SLUG}@v2"))
    assert "v2.html" in world.tutorial_index(SLUG)


def test_same_event_resend_adds_no_samples(world: World) -> None:
    """Given 同一事件送兩次，Then 版本數、回饋樣本數與 PROC `success_count` 都不變（Rule 30）。"""
    first = world.deliver_release("r_42")
    before = world.counters()
    assert world.deliver_release("r_42") == first
    assert world.counters() == before
    assert before[2] == 2                    # v1 的 1 次 ＋ 這次事件 1 次，重送不再加


def test_resume_refuses_an_operation_without_a_version(world: World) -> None:
    """Given 沒有版號也沒有待補清單的 operation，Then `resume_publish` 明確拒絕。"""
    from training_kb.errors import CoordinationError
    _accept_sub(world, "op-release-r_empty", "r_empty")
    with pytest.raises(CoordinationError, match="沒有可沿用"):
        world.resume("op-release-r_empty")


def test_resume_before_transaction_runs_the_normal_commit(world: World,
                                                          monkeypatch: pytest.MonkeyPatch
                                                          ) -> None:
    """Given 切點 3 中斷（`published_at` 仍是 None），When 復原，Then 走正常 `commit`。"""
    monkeypatch.setenv("TKB_FAULT", "publish_before_transact")
    with pytest.raises(TransientError):
        world.deliver_release("r_42")
    monkeypatch.delenv("TKB_FAULT")
    world.resume("op-release-r_42")
    assert world.tutorial().current_version == f"{SLUG}@v2"
    assert world.object_exists(world.public_key(f"{SLUG}@v2"))


# --- 5. 切點 5 的續跑與 closed execution --------------------------------------


def test_start_execution_cut_point_leaves_a_resumable_ledger(
        world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    """Given 切點 5，Then ledger 有 `input_ref`、沒有 `execution_arn`，重送走續跑分支（D-45）。

    切點刻意插在 `_start_once` **之外**：插在裡面會先 `operations.fail(...)` 把 ledger 標成
    failed，重送就不是續跑而是另一種狀態。
    """
    monkeypatch.setenv("TKB_FAULT", "start_execution")
    with pytest.raises(TransientError, match="start_execution"):
        ingress.accept_release(_release("r_42"), deadline=monotonic() + 60)
    record = world.operation("op-release-r_42")
    assert record.input_ref is not None
    assert record.execution_arn is None
    assert world.starter.started == []
    monkeypatch.delenv("TKB_FAULT")
    again = ingress.accept_release(_release("r_42"), deadline=monotonic() + 60)
    assert again.status == "duplicate"
    assert again.record.execution_arn is not None
    assert world.starter.started == [("release-update", "op-release-r_42")]


def test_closed_execution_needs_a_ledger_result(world: World,
                                                monkeypatch: pytest.MonkeyPatch) -> None:
    """Given 同名 execution 已結束，Then 先核對 ledger 的 `status == "done"` 才可沿用。

    這條用 `BotoPipelineStarter` 的真實判斷分支（假 boto client），證明
    `ExecutionAlreadyExists` 不等於成功（設計 §14.2）。
    """
    from botocore.exceptions import ClientError

    from training_kb.errors import CoordinationError
    from training_kb.pipeline_starter import BotoPipelineStarter

    class AlreadyExists(ClientError):
        pass

    class FakeExceptions:
        ExecutionAlreadyExists = AlreadyExists

    class FakeClient:
        exceptions = FakeExceptions()

        def __init__(self, status: str) -> None:
            self.status = status

        def start_execution(self, **kwargs: Any) -> dict[str, Any]:
            raise AlreadyExists({"Error": {"Code": "ExecutionAlreadyExists"}},
                                "StartExecution")

        def describe_execution(self, **kwargs: Any) -> dict[str, Any]:
            return {"status": self.status}

    arns = {"release-update":
            "arn:aws:states:us-east-1:111122223333:stateMachine:training-kb-release-update"}
    _accept_sub(world, "op-release-r_closed", "r_closed")
    starter = BotoPipelineStarter(FakeClient("FAILED"), arns,  # type: ignore[arg-type]
                                  world.operations)
    with pytest.raises(CoordinationError, match="需人工確認"):
        starter.start("release-update", "op-release-r_closed", {"operation_id":
                                                                "op-release-r_closed"})
    world.operations.complete("op-release-r_closed", now=NOW)
    reused = starter.start("release-update", "op-release-r_closed",
                           {"operation_id": "op-release-r_closed"})
    assert reused.endswith(":execution:training-kb-release-update:op-release-r_closed")


# --- 6. 串行：lease 不等於接受順序 --------------------------------------------


def test_lease_serialises_two_writers_on_the_same_tutorial(world: World) -> None:
    """Given 同篇的兩個操作，Then lease 一次只給一個寫入者，接受順序另由 `next_sequence` 決定。

    lease **不等於**接受順序，TTL 也不保證準時解鎖（00A §6.4）：兩者是兩個機制，
    這裡把它們各自斷言一次。
    """
    scope = f"TUTORIAL#{SLUG}"
    assert world.operations.acquire_lease(scope, "release", ttl_seconds=30, now=NOW) is True
    assert world.operations.acquire_lease(scope, "feedback", ttl_seconds=30, now=NOW) is False
    first = world.operations.next_sequence(f"PROJECT#{PROJECT}")
    second = world.operations.next_sequence(f"PROJECT#{PROJECT}")
    assert second > first
    world.operations.release_lease(scope, "release")
    assert world.operations.acquire_lease(scope, "feedback", ttl_seconds=30, now=NOW) is True


# --- 7. 真實 AWS：承接 P24 §11／P25 §11 的切點重跑 -----------------------------

AWS_REGION = "us-east-1"
AWS_PREFIX = "p59-"
"""真實資源上所有 demo 資料的 slug／ID 前綴；演練後自己清掉（留下的列進報告）。"""


@pytest.fixture
def aws_world(monkeypatch: pytest.MonkeyPatch) -> Iterator[World]:
    """真實 `training_kb` 表與內容 bucket 上的 `World`；資料一律 `p59-` 前綴，結束時清掉。

    `TKB_CONTENT_BUCKET` 沒設就 skip（自足）：這支檔不依賴任何別的 Phase 的 fixture。
    """
    bucket_name = os.environ.get("TKB_CONTENT_BUCKET")
    if not bucket_name:
        pytest.skip("需要 TKB_CONTENT_BUCKET 指向真實內容 bucket")
    table = boto3.resource("dynamodb", region_name=AWS_REGION).Table(
        os.environ.get("TKB_TABLE_NAME", "training_kb"))
    bucket = boto3.resource("s3", region_name=AWS_REGION).Bucket(bucket_name)
    built = World(Repository(table, bucket))
    monkeypatch.delenv("TKB_FAULT", raising=False)
    monkeypatch.setenv("TKB_ENV", "demo")
    yield built
    _cleanup(built, table, bucket)


def _cleanup(world: World, table: Any, bucket: Any) -> None:
    """清掉本次演練 seed 的 `p59-` item 與物件；刪不掉的由報告列出來交人工處理。"""
    for entity in ("TUTORIAL", "VERSION", "FEATURE", "STEP", "RULE", "OPS"):
        for item in world.repository.scan_entity(entity, meta_only=False):
            if AWS_PREFIX in f"{item.get('PK', '')}{item.get('SK', '')}":
                table.delete_item(Key={"PK": item["PK"], "SK": item["SK"]})
    for summary in bucket.objects.all():
        if AWS_PREFIX in summary.key:
            summary.delete()


@pytest.mark.aws
def test_real_aws_publish_cut_points_and_resume(aws_world: World,
                                                monkeypatch: pytest.MonkeyPatch) -> None:
    """真實 S3／DynamoDB 上跑切點 3、切點 4 與 `resume_publish` 復原（不需要模型）。

    這是 P24 §11／P25 §11「延後至 P41／P59」的程式面承接；website endpoint 的 HTTP 人工
    驗收與批次 partial 觀察在 `docs/plan/report/recovery-*.md`（要在切點當下 curl 才算數）。
    **O3 仍是 FAIL**：切點 4 觀察到的「DynamoDB 已新、公開頁還舊」原樣記錄，不宣稱通過。
    """
    world = aws_world
    slug = f"{AWS_PREFIX}{SLUG}"
    world.seed_one(slug, f"{AWS_PREFIX}{FEATURE}")
    operation_id = f"op-release-{AWS_PREFIX}r1"
    _accept_sub(world, operation_id, f"{AWS_PREFIX}r1")
    version_id = world.build_version(operation_id, slug)

    monkeypatch.setenv("TKB_FAULT", "publish_before_transact")
    with pytest.raises(TransientError, match="publish_before_transact"):
        world.publish(operation_id, (version_id,))
    assert world.tutorial(slug).current_version == f"{slug}@v1"
    assert not world.object_exists(world.public_key(version_id))

    monkeypatch.setenv("TKB_FAULT", "publish_after_transact_before_site")
    with pytest.raises(PublishError, match="a2_after_transact_before_site"):
        world.publish(operation_id, (version_id,))
    assert world.tutorial(slug).current_version == version_id     # O3 缺口：DynamoDB 已切換
    assert not world.object_exists(world.public_key(version_id))  # 公開站仍是舊世代

    monkeypatch.delenv("TKB_FAULT")
    world.resume(operation_id)
    assert world.object_exists(world.public_key(version_id))
    assert b'data-published="false"' not in world.public_bodies(version_id)
    assert world.operation(operation_id).version_id == version_id


@pytest.mark.aws
def test_real_aws_create_version_cut_points(aws_world: World,
                                            monkeypatch: pytest.MonkeyPatch) -> None:
    """真實 S3 條件寫入上跑切點 1、2，並以同一個 operation 重送沿用同版號（O2 PASS）。"""
    world = aws_world
    slug = f"{AWS_PREFIX}{SLUG_B}"
    world.seed_one(slug, f"{AWS_PREFIX}{FEATURE_B}")
    operation_id = f"op-release-{AWS_PREFIX}r2"
    _accept_sub(world, operation_id, f"{AWS_PREFIX}r2")

    monkeypatch.setenv("TKB_FAULT", "s3_after_md")
    with pytest.raises(TransientError, match="s3_after_md"):
        world.build_version(operation_id, slug)
    assert world.repository.get_version(f"{slug}@v2") is None
    assert world.repository.object_exists(markdown_key(slug, 2))
    assert not world.repository.object_exists(diff_key(slug, 2))

    monkeypatch.setenv("TKB_FAULT", "ddb_after_version")
    with pytest.raises(TransientError, match="ddb_after_version"):
        world.build_version(operation_id, slug)
    assert world.repository.get_version(f"{slug}@v2") is not None
    assert world.repository.get_steps(f"{slug}@v2") == []

    monkeypatch.delenv("TKB_FAULT")
    version_id = world.build_version(operation_id, slug)
    assert version_id == f"{slug}@v2"                     # 沒有新版號（O2 PASS）
    assert world.operation(operation_id).version_id == version_id
    assert len(world.repository.get_steps(version_id)) == 4
