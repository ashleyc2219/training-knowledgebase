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
from training_kb.errors import PermanentError
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
from training_kb.pipelines.common import Deps
from training_kb.pipelines.feedback import (
    FEEDBACK_REVIEW_PIPELINE,
    CandidateGroup,
    candidate_rule_id,
    refine_operation_id,
    review_operation_id,
    select_weak_targets,
    task_evaluate_targets,
    task_list_targets,
)
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
