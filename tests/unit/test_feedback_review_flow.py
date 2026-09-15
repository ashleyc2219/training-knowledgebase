"""Phase 48：`feedback-review` 排程流程的單元測試（兩條獨立分支、整批語意、ASL 與排程）。

每個測試的 docstring 寫 Given／When／Then。**O5 BLOCKED**，全部用假 `Writer`，不連 Bedrock；
本檔的綠燈只代表程式邏輯，**不代表** Bedrock／AWS 通過。**O3 FAIL**：這裡的 `commit` 是
moto 上的整批交易，綠燈只證明「要嘛一起發布、要嘛一篇都不發布」這個形狀，**不得**當成公開
發布已驗收（真實 AWS 的觀察原樣記在報告 §4）。

器材（**本計畫選擇 2026-09-14**）：比照 `tests/unit/test_feedback_refine.py`（P46）與
`tests/unit/test_publisher_single.py`（P24）已在用的做法，用 moto 表＋bucket 上的**真**
`Repository` 與**真** `OperationCoordinator`，只加測試觀察鉤子。整條流程會走到
`create_version`／`verify_version_complete`／`Publisher.prepare|inspect|commit`／
`transact_write`，手寫記憶體替身只會複製一份會漂移的 `Repository` 副本。

五篇種子資料（都在 `demo` 專案）：

| slug | 狀態 | current | 回饋 | 預期 |
|---|---|---|---|---|
| `a` | retired | `a@v1`（已發布） | 無 | 不是目標 |
| `b` | active | `b@v1`（已發布） | 5 筆同類、`rating=5` | 只有 candidate |
| `c` | active | `c@v1`（已發布） | 10 筆同類、`rating=2` | candidate ＋ RefinePlan |
| `d` | active | `d@v1`（已發布） | 無 | 兩者皆無 |
| `e` | active | `e@v1`（**未發布**） | 無 | 不是目標 |
"""

import json
import pathlib
import sys
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import boto3
import pytest
from moto import mock_aws

from training_kb.clock import to_iso
from training_kb.config import Settings, load_settings
from training_kb.content import VersionPlan, create_version
from training_kb.errors import PermanentError, TransientError
from training_kb.keys import feedback_pk, rule_pk, tutorial_pk, version_pk
from training_kb.models import (
    AuthoringRule,
    Feature,
    Feedback,
    RuleStatus,
    StepDraft,
    StepType,
    Tutorial,
    TutorialContent,
    TutorialStatus,
)
from training_kb.operations import Acceptance, AcceptOperation, OperationCoordinator
from training_kb.pipelines.asl import (
    ASL_LOCAL_PATH,
    ASL_SNAPSHOT_KEY,
    CATCH,
    RETRY,
    assert_safe_asl,
    canonical_json,
    task_state,
)
from training_kb.pipelines.common import Deps, task_name
from training_kb.pipelines.feedback import (
    FEEDBACK_REVIEW_PIPELINE,
    FEEDBACK_REVIEW_TASKS,
    CandidateGroup,
    candidate_rule_id,
    feedback_review_handler,
    refine_operation_id,
    review_operation_id,
    run_feedback_review,
    select_weak_targets,
    task_evaluate_targets,
    task_list_targets,
    task_prepare_batch,
)
from training_kb.publishing import MAX_BATCH_VERSIONS
from training_kb.repository import Repository

PROJECT = "demo"
NOW = datetime(2026, 9, 13, 0, 30, tzinfo=UTC)
OP = "op-feedback-review-demo-2026-09-13"
"""當日 review operation：canonical id 是 `demo-2026-09-13`（連字號，不用 `#`；D-61）。"""

CATEGORY = "找不到按鈕"
FEATURE = "Prepare"
TABLE_NAME = "training_kb"
TARGET_INDEX = "by_target"
BUCKET_NAME = "training-kb-content"
MOTO_REGION = "us-west-2"

HIT_STEP = 3
HIT_REASON = "沒有指出按鈕所在頁面與位置"
_STEP_TEXTS = ("開啟會議。", "選擇目標會議。", "開啟摘要。", "確認會前重點。")
_STEP_TYPES = (StepType.READ, StepType.CLICK_UI, StepType.CLICK_UI, StepType.READ)

B_IDS = tuple(f"f_b{index}" for index in range(1, 6))
"""b 的五筆同類回饋：剛好命中 `MIN_CANDIDATE_FEEDBACK`，但 `rating=5` 不是弱教學。"""

C_IDS = tuple(f"f_c{index:02d}" for index in range(1, 11))
"""c 的十筆同類回饋：n=10、平均 2.0、同類 10 筆 → 正式門檻的弱教學。"""


# --- 共用器材 ---------------------------------------------------------------


class ReviewOperations(OperationCoordinator):
    """真 `OperationCoordinator` ＋ 一個觀察鉤子：依接受順序記下每一個 `operation_id`。

    子 operation（D-59）是否真的被 `accept` 過，只能從這裡看得出來；`prepare_refine` 的
    `_guard` 會再讀一次同一筆紀錄，所以不能改用不寫表的假物件。
    """

    def __init__(self, repository: Repository) -> None:
        super().__init__(repository)
        self.accepted_ids: list[str] = []

    def accept(self, request: AcceptOperation) -> Acceptance:
        self.accepted_ids.append(request.operation_id)
        return super().accept(request)


def content_of(title: str) -> TutorialContent:
    """四步的教學內容；只有第 3 步（`click_ui`）會被診斷命中。"""
    steps = [StepDraft(number=index + 1, type=_STEP_TYPES[index], text=_STEP_TEXTS[index],
                       feature_id=FEATURE) for index in range(4)]
    return TutorialContent(title=title, problem=f"{title}的步驟散在多個頁面，新人找不到。",
                           prerequisites=["已登入工作區"], steps=steps,
                           expected_outcome=f"{title}已完成。")


def seed_tutorial(repository: Repository, slug: str, *, published: bool = True,
                  status: TutorialStatus = TutorialStatus.ACTIVE) -> str:
    """種一篇教學的 v1：走真的 `create_version`（含 `.md`／`.diff`／STEP 邊），再切發布欄位。

    `create_version` 一律寫 `published_at=None`（D25），所以「已發布」要另外用
    `update_meta` 補上——這正是 `Publisher.commit` 在真實流程裡做的事。種子資料不繞過
    `create_version`，`Publisher.inspect` 的「已保存步驟 vs 公開內容」才比對得出來。
    TUTORIAL item 必須先存在：`create_version` 最後的 `verify_version_complete` 會查它。
    """
    version_id = f"{slug}@v1"
    repository.put_meta(Tutorial(slug=slug, current_version=None, topic=f"教學 {slug}",
                                 feature_ids=[FEATURE], status=status, successor=None,
                                 cluster_id=f"cluster-{slug}"))
    create_version(VersionPlan(version_id=version_id, slug=slug, number=1, supersedes=None,
                               reason=f"gap:{slug}", rules_applied=(),
                               operation_id=f"op-ticket-seed-{slug}"),
                   content_of(f"教學 {slug}"), repository)
    if published:
        repository.update_meta(version_pk(version_id), {"published_at": to_iso(NOW)},
                               expected_revision=repository.revision_of(version_pk(version_id)))
        repository.update_meta(tutorial_pk(slug), {"current_version": version_id},
                               expected_revision=repository.revision_of(tutorial_pk(slug)))
    return version_id


def seed_feedback(repository: Repository, version_id: str, ids: Sequence[str], *,
                  rating: int) -> None:
    """一筆回饋 ＝ `FEEDBACK#` 本體 ＋ 指向該版的 `REFERS_TO` 邊（反查靠這條邊）。"""
    for feedback_id in ids:
        repository.put_meta(Feedback(id=feedback_id, tutorial_version=version_id, rating=rating,
                                     category=CATEGORY, comment="找不到那顆按鈕",
                                     user="u_01", ts=NOW))
        repository.put_edge(feedback_pk(feedback_id), "REFERS_TO", version_pk(version_id))


def rule_proposal() -> dict[str, Any]:
    """`propose_rule` 節點的假回覆（`RuleProposal`）。"""
    return {"rule": "步驟要寫出按鈕所在的頁面與位置。", "applies_when": str(StepType.CLICK_UI),
            "evidence": [], "derived_from": ""}


def weak_diagnosis() -> dict[str, Any]:
    """`diagnose_weak` 節點的假回覆（`WeakDiagnosis`）：只命中第 3 步。"""
    return {"items": [{"number": HIT_STEP, "reason": HIT_REASON}]}


def step_rewrite(slug: str) -> dict[str, Any]:
    """`refine_steps` 節點的假回覆（`StepRewrite`）：只改第 3 步的文字。"""
    return {"steps": [{"number": HIT_STEP, "type": str(_STEP_TYPES[HIT_STEP - 1]),
                       "feature_id": FEATURE,
                       "text": f"在左側導覽列點「摘要」開啟 {slug} 的摘要頁。"}]}


@dataclass
class ReviewWorld:
    """一次 review 需要的全部器材；`deps` 就是 Task 函式吃的那一個。"""

    repository: Repository
    writer: Any
    operations: ReviewOperations
    deps: Deps

    def site_keys(self) -> list[str]:
        """目前公開前綴底下的全部物件 key；`site/` 是全案唯一的公開前綴。"""
        bucket = boto3.resource("s3", region_name=MOTO_REGION).Bucket(BUCKET_NAME)
        return sorted(row.key for row in bucket.objects.filter(Prefix="site/"))

    def object_of(self, key: str) -> dict[str, Any]:
        body = self.repository.get_object(key)
        assert body is not None, key
        loaded: dict[str, Any] = json.loads(body.decode("utf-8"))
        return loaded


@pytest.fixture
def repository() -> Iterator[Repository]:
    """moto 的本機表＋bucket；`by_target` GSI 與 `tests/integration/conftest.py` 同形狀。"""
    with mock_aws():
        dynamodb = boto3.resource("dynamodb", region_name=MOTO_REGION)
        table = dynamodb.create_table(
            TableName=TABLE_NAME,
            KeySchema=[{"AttributeName": "PK", "KeyType": "HASH"},
                       {"AttributeName": "SK", "KeyType": "RANGE"}],
            AttributeDefinitions=[{"AttributeName": "PK", "AttributeType": "S"},
                                  {"AttributeName": "SK", "AttributeType": "S"},
                                  {"AttributeName": "target", "AttributeType": "S"}],
            GlobalSecondaryIndexes=[{
                "IndexName": TARGET_INDEX,
                "KeySchema": [{"AttributeName": "target", "KeyType": "HASH"}],
                "Projection": {"ProjectionType": "KEYS_ONLY"},
            }],
            BillingMode="PAY_PER_REQUEST",
        )
        table.wait_until_exists()
        bucket = boto3.resource("s3", region_name=MOTO_REGION).Bucket(BUCKET_NAME)
        bucket.create(CreateBucketConfiguration={"LocationConstraint": MOTO_REGION})
        yield Repository(table, bucket)


def settings_for() -> Settings:
    """`load_settings({})` 的預設值就是 `demo` 專案與 `Thresholds()` 的正式門檻。"""
    return load_settings({})


def build_world(repository: Repository, writer: Any,
                replies: Sequence[dict[str, Any]]) -> ReviewWorld:
    """把 moto 的 `Repository`、排好回覆的假 `Writer` 與真 `OperationCoordinator` 組成 `Deps`。"""
    writer.replies = [dict(reply) for reply in replies]
    operations = ReviewOperations(repository)
    return ReviewWorld(repository=repository, writer=writer, operations=operations,
                       deps=Deps(operations=operations, now=lambda: NOW,
                                 repository=repository, writer=writer,
                                 settings=settings_for()))


@pytest.fixture
def review_deps(repository: Repository, fake_writer: Any) -> ReviewWorld:
    """五篇種子（見模組 docstring）＋ 依呼叫順序排好的四個假模型回覆。

    順序就是 `task_evaluate_targets` 的走法：b 的 candidate、c 的 candidate、c 的診斷、
    c 的改寫。多排或少排都會讓 `RecordingWriter` 當場失敗，順序因此是被斷言住的。
    """
    repository.put_meta(Feature(feature_id=FEATURE, name=FEATURE, aliases=[], first_seen=NOW))
    seed_tutorial(repository, "a", status=TutorialStatus.RETIRED)
    seed_tutorial(repository, "b")
    seed_tutorial(repository, "c")
    seed_tutorial(repository, "d")
    seed_tutorial(repository, "e", published=False)
    seed_feedback(repository, "b@v1", B_IDS, rating=5)
    seed_feedback(repository, "c@v1", C_IDS, rating=2)
    return build_world(repository, fake_writer,
                       [rule_proposal(), rule_proposal(), weak_diagnosis(), step_rewrite("c")])


def expected_rule_id(version_id: str, ids: Sequence[str]) -> str:
    return candidate_rule_id(CandidateGroup(version_id, CATEGORY, tuple(sorted(ids))))


# --- Task 1：兩條獨立分支與 state 契約 ---------------------------------------


def test_review_operation_id_is_project_and_utc_date(review_deps: ReviewWorld) -> None:
    """Given 沒有外部事件，When 產生當日 id，Then 是 `op-feedback-review-<專案>-<UTC 日期>`。

    canonical id 用**連字號**（D-61），`execution_name` 才不必走 SHA-256 截取，同一天的
    執行名稱看得出是哪一天。
    """
    assert FEEDBACK_REVIEW_PIPELINE == "feedback-review"
    assert review_operation_id({"mode": "formal"}, review_deps.deps) == OP
    assert review_operation_id({"operation_id": "op-feedback-review-x"},
                               review_deps.deps) == "op-feedback-review-x"


def test_unknown_mode_is_permanent(review_deps: ReviewWorld) -> None:
    """Given `mode` 不是 formal／demo，When 跑 `ListTargets`，Then `PermanentError`（不重試）。"""
    with pytest.raises(PermanentError):
        task_list_targets({"mode": "staging"}, review_deps.deps)


def test_list_targets_only_takes_active_published_current_versions(
        review_deps: ReviewWorld) -> None:
    """Given 五篇教學，When 列目標，Then 只有 active 且 current 已發布的三篇進 state。"""
    state = task_list_targets({"mode": "formal"}, review_deps.deps)
    assert state["target_version_ids"] == ["b@v1", "c@v1", "d@v1"]   # a 已退役、e 尚未發布
    assert state["operation_id"] == OP and state["project_id"] == PROJECT
    assert state["mode"] == "formal"
    assert review_deps.operations.accepted_ids == [OP]


def test_candidate_and_refine_branches_do_not_block_each_other(
        review_deps: ReviewWorld) -> None:
    """Given b 只有 candidate、c 兩者皆有、d 兩者皆無，Then 兩條分支各自照跑不互相吞掉。"""
    state = task_evaluate_targets(task_list_targets({"mode": "formal"}, review_deps.deps),
                                  review_deps.deps)
    assert state["candidate_rule_ids"] == sorted(
        [expected_rule_id("b@v1", B_IDS), expected_rule_id("c@v1", C_IDS)])
    assert state["prepared_version_ids"] == ["c@v2"]
    assert set(state) == {"operation_id", "project_id", "mode", "target_version_ids",
                          "candidate_rule_ids", "prepared_version_ids"}


def test_no_change_reasons_go_to_a_private_object_not_the_state(
        review_deps: ReviewWorld) -> None:
    """Given d 兩條分支都沒命中，Then 理由寫進私有 `review-no-change.json`，不進 state。"""
    state = task_evaluate_targets(task_list_targets({"mode": "formal"}, review_deps.deps),
                                  review_deps.deps)
    assert "no_change_reasons" not in state
    assert review_deps.object_of(
        f"operations/{OP}/review-no-change.json") == {"d@v1": "不是弱教學"}


def test_each_weak_target_gets_its_own_refine_operation(review_deps: ReviewWorld) -> None:
    """Given c 是弱教學，Then 它先 `accept` 一筆自己的 `refine_operation_id` 子 operation。

    兩篇共用當日的 review operation 會搶同一個版號（`allocate_version` 以 `operation_id`
    當唯一鍵、`OperationRecord.version_id` 只有一個值），所以 D-59 要求每個 target 一筆。
    """
    listed = task_list_targets({"mode": "formal"}, review_deps.deps)
    target = select_weak_targets(repository=review_deps.deps.need_repository(), mode="formal",
                                 now=review_deps.deps.now(),
                                 thresholds=review_deps.deps.need_settings().thresholds)[0]
    task_evaluate_targets(listed, review_deps.deps)
    sub_id = refine_operation_id(target.version_id, target.category, target.feedback_ids)
    assert sub_id != OP and sub_id.startswith("op-feedback-")
    assert review_deps.operations.accepted_ids == [OP, sub_id]


def test_refine_failure_keeps_the_candidate(review_deps: ReviewWorld,
                                            monkeypatch: pytest.MonkeyPatch) -> None:
    """Given c 的 REFINE 丟 `PermanentError`，Then c 的 candidate 仍已寫入且是 `candidate`。

    兩條分支沒有共用條件，所以 REFINE 炸掉不會把已經寫好的規則回收——`AuthoringRule` 是
    上一步就 `put_meta` 完成的獨立事實（設計 §7.5：失敗時已保存的合法 candidate 不消失）。
    """
    from training_kb.pipelines import feedback as feedback_module

    def boom(*args: Any, **kwargs: Any) -> None:
        raise PermanentError("REFINE 故意失敗")

    monkeypatch.setattr(feedback_module, "prepare_refine", boom)
    listed = task_list_targets({"mode": "formal"}, review_deps.deps)
    with pytest.raises(PermanentError):
        task_evaluate_targets(listed, review_deps.deps)
    rule = review_deps.repository.get_meta(rule_pk(expected_rule_id("c@v1", C_IDS)),
                                           AuthoringRule)
    assert rule is not None and rule.status is RuleStatus.CANDIDATE


def test_state_never_carries_comments_or_full_text(review_deps: ReviewWorld) -> None:
    """Given 教學全文與回饋留言都在 S3／表裡，Then state 的值只有 ID 與小型判斷結果。"""
    state = task_evaluate_targets(task_list_targets({"mode": "formal"}, review_deps.deps),
                                  review_deps.deps)
    dumped = json.dumps(state, ensure_ascii=False)
    assert "找不到那顆按鈕" not in dumped and _STEP_TEXTS[0] not in dumped


# --- Task 2：整批 prepare／inspect／commit 與 F49 ------------------------------


@pytest.fixture
def review_deps_two_weak(repository: Repository, fake_writer: Any) -> ReviewWorld:
    """b 與 c 都是弱教學且診斷都有命中；d 兩條分支都沒命中。

    回覆順序＝`task_evaluate_targets` 的走法（逐篇先 candidate 再 REFINE）：
    b candidate、b 診斷、b 改寫、c candidate、c 診斷、c 改寫。
    """
    repository.put_meta(Feature(feature_id=FEATURE, name=FEATURE, aliases=[], first_seen=NOW))
    for slug in ("b", "c", "d"):
        seed_tutorial(repository, slug)
    seed_feedback(repository, "b@v1", B_IDS + tuple(f"f_b{index}" for index in range(6, 11)),
                  rating=2)
    seed_feedback(repository, "c@v1", C_IDS, rating=2)
    return build_world(repository, fake_writer,
                       [rule_proposal(), weak_diagnosis(), step_rewrite("b"),
                        rule_proposal(), weak_diagnosis(), step_rewrite("c")])


@pytest.fixture
def review_deps_no_target(repository: Repository, fake_writer: Any) -> ReviewWorld:
    """沒有任何 active 已發布版本：只有一篇已退役的教學。"""
    repository.put_meta(Feature(feature_id=FEATURE, name=FEATURE, aliases=[], first_seen=NOW))
    seed_tutorial(repository, "a", status=TutorialStatus.RETIRED)
    return build_world(repository, fake_writer, [])


def shift_the_base(world: ReviewWorld, slug: str) -> None:
    """讓某一篇的基底位移：把 `TUTORIAL.current_version` 換掉，不再等於新版的 `supersedes`。

    這是 `Publisher.inspect` 三類問題之一（「基底已位移」），也是併發下真的會發生的情況
    ——另一條流程在這段期間把這篇切到別的版本。挑它當切點是因為它**只有 `inspect` 擋得
    住**：`prepare` 照樣把兩篇的 staging 都寫出來，所以測試證的是「檢查失敗時零篇公開」，
    不是「產物根本沒做出來」。

    **不動** staging 物件：`_prepared` 每個 Task 都重跑一次 `prepare`，刪掉的 staging 會被
    重新寫回來，製造不出「檢查不通過」這個狀態。
    """
    pk = tutorial_pk(slug)
    world.repository.update_meta(pk, {"current_version": f"{slug}@v9"},
                                 expected_revision=world.repository.revision_of(pk))


def run_tasks(world: ReviewWorld, state: dict[str, Any], *, after: str = "",
              corrupt: Any = None) -> dict[str, Any]:
    """照 ASL 的走法逐個 Task 跑（雲端就是這樣，不經 `run_sequence`）。

    `after`／`corrupt` 讓測試在**兩個 Task 之間**動手腳，重現「`EvaluateTargets` 已經建好
    未發布版本，`InspectBatch` 之前產物被改壞」這個切點。
    """
    for task in FEEDBACK_REVIEW_TASKS:
        state = task(state, world.deps)
        if corrupt is not None and task_name(task) == after:
            corrupt(world)
    return state


def test_task_order_and_names_are_fixed() -> None:
    """Given 五個 Task，Then 名稱與順序逐字等於 00A §7 的一條直線。"""
    assert [task_name(task) for task in FEEDBACK_REVIEW_TASKS] == [
        "list_targets", "evaluate_targets", "prepare_batch", "inspect_batch", "commit_batch"]


def test_two_prepared_versions_commit_together(review_deps_two_weak: ReviewWorld) -> None:
    """Given 兩篇都產生 `RefinePlan`，Then 兩篇在同一次 `commit` 一起切 `published_at`。"""
    result = run_feedback_review({"mode": "formal"}, review_deps_two_weak.deps)
    published = review_deps_two_weak.object_of(str(result["result_ref"]))
    assert result["prepared_version_ids"] == ["b@v2", "c@v2"]
    assert published["published_version_ids"] == ["b@v2", "c@v2"]
    assert published["reviewed_version_ids"] == ["b@v1", "c@v1", "d@v1"]
    assert published["no_change_reasons"] == {"d@v1": "不是弱教學"}
    repository = review_deps_two_weak.repository
    assert repository.get_tutorial("b").current_version == "b@v2"
    assert repository.get_tutorial("c").current_version == "c@v2"
    assert "site/tutorials/b/v2.html" in review_deps_two_weak.site_keys()


def test_second_version_failing_inspection_publishes_nothing(
        review_deps_two_weak: ReviewWorld) -> None:
    """Given 第二篇的產物在 `InspectBatch` 之前被改壞，Then 第一篇也**不會**發布（F49）。

    `PrepareBatch` 只寫私有 staging，`CommitBatch` 才一次交易切 2N 個欄位，所以停在
    `InspectBatch` 時兩篇的 `current_version` 都還是舊值、`site/` 一個物件都沒有。
    """
    with pytest.raises(PermanentError):
        run_tasks(review_deps_two_weak, {"mode": "formal"}, after="evaluate_targets",
                  corrupt=lambda world: shift_the_base(world, "c"))
    repository = review_deps_two_weak.repository
    assert repository.get_tutorial("b").current_version == "b@v1"   # 第一篇也沒被發布
    assert repository.get_version("b@v2").published_at is None
    assert review_deps_two_weak.site_keys() == []


def test_empty_batch_succeeds_without_touching_publisher(
        review_deps_no_target: ReviewWorld) -> None:
    """Given 沒有任何 active 已發布版本，Then `SUCCEEDED`、零次模型呼叫、不碰 `Publisher`。"""
    result = run_feedback_review({"mode": "formal"}, review_deps_no_target.deps)
    assert result["publish_request_ref"] is None and result["prepared_version_ids"] == []
    assert result["target_version_ids"] == []
    assert review_deps_no_target.writer.calls == []
    assert review_deps_no_target.site_keys() == []
    assert review_deps_no_target.object_of(
        str(result["result_ref"]))["published_version_ids"] == []


def test_resend_does_not_call_the_model_or_allocate_a_new_version(
        review_deps_two_weak: ReviewWorld) -> None:
    """Given 同一天、同 operation 重送，Then 不重打模型、不提第二條規則、不配新版號。

    **本計畫選擇 2026-09-14：** Phase 文件原本斷言兩次的 `publish_request_ref` 相同。
    第一次已經把 b@v2／c@v2 發布出去，`current_version` 因此前進，第二次的目標變成
    b@v2／c@v2（它們身上沒有回饋），`prepare_refine` 也會在 `_guard` 判定
    `no_new_evidence`（F23）而回 `None`——所以第二次本來就**不該**再有 publish request。
    §11 真正要守的是「不重複提案、不重打模型、不配新版號」，這裡直接斷言那三件事。
    """
    first = run_feedback_review({"mode": "formal"}, review_deps_two_weak.deps)
    calls = list(review_deps_two_weak.writer.calls)
    rules = {row["PK"] for row in review_deps_two_weak.repository.scan_entity("RULE")}
    second = run_feedback_review({"mode": "formal"}, review_deps_two_weak.deps)

    assert second["result_ref"] == first["result_ref"]          # 同一天＝同一筆 operation
    assert review_deps_two_weak.writer.calls == calls           # 不重打模型
    assert {row["PK"] for row in review_deps_two_weak.repository.scan_entity("RULE")} == rules
    versions = {str(row["version_id"])
                for row in review_deps_two_weak.repository.scan_entity("VERSION")}
    assert versions == {"b@v1", "b@v2", "c@v1", "c@v2", "d@v1"}  # 沒有 v3


def test_a_batch_over_the_transaction_limit_is_rejected_before_any_write(
        review_deps_no_target: ReviewWorld) -> None:
    """Given 超過 `MAX_BATCH_VERSIONS` 的一批，Then `PrepareBatch` 直接拒絕，不寫 staging。"""
    state = {"operation_id": OP, "project_id": PROJECT, "mode": "formal",
             "target_version_ids": [], "candidate_rule_ids": [],
             "prepared_version_ids": [f"x{index}@v2" for index in range(MAX_BATCH_VERSIONS + 1)]}
    with pytest.raises(PermanentError):
        task_prepare_batch(state, review_deps_no_target.deps)
    assert review_deps_no_target.repository.get_object(
        f"operations/{OP}/publish-request.json") is None


def test_handler_rejects_unknown_task() -> None:
    """Given ASL 傳來不存在的 task 名稱，Then `PermanentError`（部署錯誤，重試不會變好）。"""
    with pytest.raises(PermanentError):
        feedback_review_handler({"task": "publish_everything", "state": {}}, None)


def test_handler_runs_exactly_one_task(review_deps: ReviewWorld,
                                       monkeypatch: pytest.MonkeyPatch) -> None:
    """Given 雲端逐個 Task 呼叫，Then handler 只跑 `event["task"]` 那一個，不跑整條序列。"""
    from training_kb.pipelines import feedback as feedback_module

    monkeypatch.setattr(feedback_module, "_DEPS", review_deps.deps)
    state = feedback_review_handler({"pipeline": "feedback-review", "task": "list_targets",
                                     "state": {"mode": "formal"}}, None)
    assert state["target_version_ids"] == ["b@v1", "c@v1", "d@v1"]
    assert "candidate_rule_ids" not in state        # EvaluateTargets 沒有被一起跑掉
    assert review_deps.writer.calls == []


# --- Task 3：ASL、每日排程與 CDK template ------------------------------------

# infra/ 是部署用的 CDK 程式，不在 src/ 的安裝套件裡（同 tests/unit/infra/test_ticket_asl.py）。
PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import aws_cdk as cdk  # noqa: E402
from aws_cdk.assertions import Match, Template  # noqa: E402

from infra import training_kb_stack as stack_module  # noqa: E402
from infra.scripts.build_lambda_layer import MARKERS  # noqa: E402
from infra.training_kb_stack import CONTENT_BUCKET_CONTEXT, TrainingKbStack  # noqa: E402

ASL_PATH = PROJECT_ROOT / ASL_LOCAL_PATH.format(pipeline="feedback-review", number=1)
ARN = "${PipelineTaskFunctionArn}"
NEXT = {"ListTargets": "EvaluateTargets", "EvaluateTargets": "PrepareBatch",
        "PrepareBatch": "InspectBatch", "InspectBatch": "CommitBatch",
        "CommitBatch": "Succeeded"}
BUCKET = "training-kb-content-example"
ACCOUNT, REGION = "111122223333", "us-east-1"
REVIEW_MACHINE = "training-kb-feedback-review"
DAILY_SCHEDULE = "training-kb-feedback-review-daily"


@pytest.fixture
def asl() -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(ASL_PATH.read_text(encoding="utf-8"))
    return loaded


@pytest.fixture
def fake_layer(monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path) -> pathlib.Path:
    """把 layer 路徑指到 `tmp_path` 下一份**看起來裝好了**的目錄（同 P41 的 `fake_layer`）。

    **不在工作樹裡 `mkdir`**：真的在 `build/lambda-layer/python` 造一個空目錄，會讓
    「清過 build/ 之後跑一次 pytest」就足以讓部署守門通過（P41 review 必修 2）。
    """
    for marker in MARKERS:
        (tmp_path / "python" / marker).mkdir(parents=True)
    monkeypatch.setattr(stack_module, "LAYER_PATH", tmp_path)
    return tmp_path


@pytest.fixture
def template(monkeypatch: pytest.MonkeyPatch, fake_layer: pathlib.Path) -> "Template":
    monkeypatch.setenv(stack_module.SECRET_ENV, "unit-test-secret")
    app = cdk.App(context={CONTENT_BUCKET_CONTEXT: BUCKET})
    stack = TrainingKbStack(app, "TrainingKbApp",
                            env=cdk.Environment(account=ACCOUNT, region=REGION))
    return Template.from_stack(stack)


def test_every_task_state_equals_phase29_template_plus_parameters(asl: dict[str, Any]) -> None:
    """Given 五個 Task state，Then 除了 `Parameters` 逐欄等於 Phase 29 的 `task_state`。"""
    assert len(RETRY) == 2 and RETRY[0]["ErrorEquals"] == ["TransientError"]        # D-53
    assert RETRY[1]["ErrorEquals"][0] == "Lambda.ServiceException"
    for name, next_state in NEXT.items():
        state, expected = asl["States"][name], task_state(ARN, next_state)
        expected["Parameters"] = {"pipeline": "feedback-review",
                                  "task": state["Parameters"]["task"], "state.$": "$"}
        assert state == expected, name     # Retry／Catch／TimeoutSeconds 全部來自 Phase 29


def test_asl_matches_python_tasks_and_has_no_map(asl: dict[str, Any]) -> None:
    """Given ASL 與 Python 兩邊，Then Task 名稱、封套、終點與靜態檢查都對得上，且沒有 Map。"""
    assert [asl["States"][name]["Parameters"]["task"] for name in NEXT] == [
        task_name(task) for task in FEEDBACK_REVIEW_TASKS]
    assert all("Payload" not in asl["States"][name]["Parameters"] for name in NEXT)
    assert '"Map"' not in json.dumps(asl, ensure_ascii=False)      # F49：不得逐篇發布
    assert '"Choice"' not in json.dumps(asl, ensure_ascii=False)   # 00A §7：一條直線
    assert_safe_asl(asl)
    assert asl["StartAt"] == "ListTargets"
    assert CATCH[0]["Next"] == "PipelineFailed"
    assert asl["States"]["PipelineFailed"]["Type"] == "Fail"
    assert asl["States"]["Succeeded"]["Type"] == "Succeed"
    assert TransientError.__name__ == "TransientError"   # ASL 用類別名比對，不帶模組路徑


def test_local_asl_file_is_the_canonical_bytes(asl: dict[str, Any]) -> None:
    """Given 部署與 S3 快照要逐 byte 相同，Then 本地檔就是 `canonical_json` 的輸出。"""
    assert ASL_PATH.read_bytes() == canonical_json(asl)
    assert ASL_SNAPSHOT_KEY.format(pipeline="feedback-review", number=1) \
        == "stepfunctions/feedback-review/v1.json"


def test_stack_has_review_machine_and_exactly_one_daily_schedule(template: "Template") -> None:
    """Given 合成結果，Then 有 `feedback-review` Standard workflow 與**唯一**一條每日排程。

    `REV` Rule 1（每日執行）的 primary assertion 就是這一條：`cron(30 0 * * ? *)`、`UTC`、
    固定 input `{"mode": "formal"}`，雲端再用 `aws scheduler get-schedule` 核對同樣三個值。
    """
    template.has_resource_properties("AWS::StepFunctions::StateMachine", {
        "StateMachineName": REVIEW_MACHINE, "StateMachineType": "STANDARD",
        "DefinitionSubstitutions": Match.object_like(
            {"PipelineTaskFunctionArn": Match.any_value()})})
    template.resource_count_is("AWS::Scheduler::Schedule", 1)
    template.has_resource_properties("AWS::Scheduler::Schedule", {
        "Name": DAILY_SCHEDULE,
        "ScheduleExpression": "cron(30 0 * * ? *)", "ScheduleExpressionTimezone": "UTC",
        "FlexibleTimeWindow": {"Mode": "OFF"},
        "Target": Match.object_like({"Input": '{"mode": "formal"}'})})
    names = {function["Properties"]["FunctionName"]
             for function in template.find_resources("AWS::Lambda::Function").values()}
    # 用包含關係：`training-kb-import`（P42）與之後的 Phase 都在同一支 stack 加東西，
    # 等號會讓別人一落地就把這個檔轉紅（00A D-23、D-58）。**本 Phase 不新增任何 Lambda。**
    assert {"training-kb-pipeline-task", "training-kb-webhook",
            "training-kb-analytics"} <= names
    assert REVIEW_MACHINE not in names        # state machine 與 Lambda 不同名（D-23）


def test_scheduler_role_can_only_start_this_one_state_machine(template: "Template") -> None:
    """Given Scheduler 自己的 role，Then 只拿得到這一條 state machine 的 `StartExecution`。"""
    roles = {logical: row for logical, row in
             template.find_resources("AWS::IAM::Role").items()
             if any(statement["Principal"].get("Service") == "scheduler.amazonaws.com"
                    for statement in
                    row["Properties"]["AssumeRolePolicyDocument"]["Statement"])}
    assert len(roles) == 1
    scheduler_role = next(iter(roles))
    granted = [statement
               for policy in template.find_resources("AWS::IAM::Policy").values()
               if any(ref.get("Ref") == scheduler_role
                      for ref in policy["Properties"]["Roles"])
               for statement in policy["Properties"]["PolicyDocument"]["Statement"]]
    assert [statement["Action"] for statement in granted] == ["states:StartExecution"]
    assert all("Ref" in statement["Resource"] for statement in granted)   # 單一 ARN，不是 *


def test_review_machine_logs_to_its_own_group(template: "Template") -> None:
    """Given 每條 state machine 各有自己的 log group，Then `feedback-review` 也有一個。"""
    names = {row["Properties"]["LogGroupName"]
             for row in template.find_resources("AWS::Logs::LogGroup").values()}
    assert f"/aws/vendedlogs/states/{REVIEW_MACHINE}" in names
