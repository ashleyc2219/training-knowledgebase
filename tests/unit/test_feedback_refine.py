"""Phase 46：REFINE 精準改寫與證據去重的單元測試。

每個測試的 docstring 寫 Given／When／Then。**O5 BLOCKED**，全部用假 Writer，不連 Bedrock；
本檔的綠燈只代表程式邏輯，**不代表** Bedrock／AWS 已通過。本 Phase 也不發布（O3 FAIL 不受
影響）：這裡建出來的 `prepare-meeting@v2` 是 `published_at=None` 的私有版本，不是已公開。

器材（**本計畫選擇 2026-09-14**）：Phase 文件 §7 把 `world.repo` 畫成手寫記憶體 fake，但
`create_version`／`verify_version_complete` 需要 `put_meta`／`put_edge`／`scan_entity`／
`query_by_target`／S3 條件寫入與 `_missing_parts` 一整片 `Repository` 行為，手寫替身只會
複製一份會漂移的副本。改為比照 `tests/unit/test_publisher_single.py` 已在用的做法：moto
表＋bucket 上的**真** `Repository` 子類，只加兩個觀察鉤子（`recategorize`／`versions`），
搭配**真** `OperationCoordinator`（lease 與 `record_model_output` 都是真的）。表要含
`by_target` GSI，否則 `list_feedback_of_version` 查不到回饋。

moto 的綠燈只證明資料形狀與程式邏輯，**不是**永久去重（O2）的證據；真實表的重送證據在
`tests/integration/test_feedback_refine_retry.py`。
"""

import json
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import boto3
import pytest
from moto import mock_aws

from training_kb.analytics.status_writer import VALIDATED_AT_KEY
from training_kb.clock import to_iso
from training_kb.content import (
    MARKDOWN_CONTENT_TYPE,
    markdown_key,
    put_private_artifact,
    render_markdown,
    verify_version_complete,
)
from training_kb.errors import ContentError, CoordinationError, TransientError
from training_kb.keys import edge_sk, feature_pk, feedback_pk, step_pk, version_pk
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
    TutorialVersion,
)
from training_kb.operations import AcceptOperation, OperationCoordinator
from training_kb.pipelines.feedback import (
    LEASE_TTL_SECONDS,
    DiagnosisResult,
    RefinePlan,
    evidence_fingerprint,
    evidence_of,
    prepare_refine,
    refine_operation_id,
    refine_reason,
)
from training_kb.repository import Repository, item_to_model
from training_kb.writing.client import inference_config

SLUG = "prepare-meeting"
V1 = f"{SLUG}@v1"
V2 = f"{SLUG}@v2"
FEATURE = "Prepare"
CATEGORY = "找不到按鈕"
OTHER_CATEGORY = "缺少資訊"
NOW = datetime(2026, 9, 14, tzinfo=UTC)
PROJECT = "demo-project"

EIGHT_IDS = ("f_12", "f_15", "f_19", "f_23", "f_27", "f_31", "f_34", "f_40")
"""設計 §11.2 的 A v1 八筆；O7 未核定前它們仍是**待核定的合成資料**。"""

HIT_REASON = "沒有指出按鈕所在頁面與位置"

_STEP_TEXTS = ("開啟會議。", "選擇目標會議。", "開啟摘要。", "確認會前重點。")
_STEP_TYPES = (StepType.READ, StepType.CLICK_UI, StepType.CLICK_UI, StepType.READ)

TABLE_NAME = "training_kb"
TARGET_INDEX = "by_target"
BUCKET_NAME = "training-kb-content"
MOTO_REGION = "us-west-2"


# --- 共用器材 ---------------------------------------------------------------


class RefineRepository(Repository):
    """真 `Repository` 行為 ＋ 三個測試觀察鉤子；沒有覆寫任何既有行為。"""

    def __init__(self, table: Any, bucket: Any) -> None:
        super().__init__(table, bucket)
        self.table = table

    def break_one_step_edge(self, version_id: str) -> None:
        """刪掉最後一步的 STEP 邊，重現設計 §14.1 的「上次寫到一半」。

        關係邊是逐筆寫的，中間當機時前幾筆已經落地；這個鉤子造出的正是那個狀態，
        `verify_version_complete` 會因此回 `False`。
        """
        last = self.get_steps(version_id)[-1]
        self.table.delete_item(Key={"PK": step_pk(version_id, last.number),
                                    "SK": edge_sk("REFERENCES", feature_pk(last.feature_id))})

    @property
    def versions(self) -> dict[str, TutorialVersion]:
        """目前表裡的全部 VERSION item；用來斷言「沒有版本被建立」。"""
        rows = [item_to_model(item, TutorialVersion) for item in self.scan_entity("VERSION")]
        return {row.version_id: row for row in rows}

    def recategorize(self, feedback_id: str, category: str) -> None:
        """把一筆回饋改成別的類別；用來製造「同一批證據跨類別」這個停止點。"""
        pk = feedback_pk(feedback_id)
        self.update_meta(pk, {"category": category}, expected_revision=self.revision_of(pk))


class RefineOperations(OperationCoordinator):
    """真 `OperationCoordinator` ＋ 一個 lease 鉤子（讓別人先持有這一篇的租約）。"""

    def hold(self, scope: str, owner: str) -> None:
        taken = self.acquire_lease(scope, owner, ttl_seconds=LEASE_TTL_SECONDS, now=NOW)
        assert taken, f"測試前置失敗：{owner} 沒能先拿到 {scope} 的租約"


@dataclass
class World:
    """一次 REFINE 需要的全部器材；欄位名與 Phase 文件 §7 的 `world` 一致。"""

    repo: RefineRepository
    writer: Any
    operations: RefineOperations
    base: TutorialContent
    diagnosis: DiagnosisResult
    operation_id: str


def base_content() -> TutorialContent:
    """v1 的四步：第 1／4 步是 `read`，第 2／3 步是 `click_ui`（只有第 3 步會被命中）。"""
    steps = [
        StepDraft(number=index + 1, type=_STEP_TYPES[index], text=_STEP_TEXTS[index],
                  feature_id=FEATURE)
        for index in range(4)
    ]
    return TutorialContent(title="準備會議",
                           problem="會議前的準備步驟散在多個頁面，新人找不到。",
                           prerequisites=["已登入工作區"], steps=steps,
                           expected_outcome="會議開始前已備妥議程與摘要。")


def feedback_row(feedback_id: str, *, category: str = CATEGORY) -> Feedback:
    return Feedback(id=feedback_id, tutorial_version=V1, rating=2, category=category,
                    comment="找不到那顆按鈕", user="u_01", ts=NOW)


def rule(rule_id: str, applies_when: StepType, *,
         status: str = "active") -> AuthoringRule:
    """一條撰寫規則；`status` 用字串是為了讓測試逐字寫 `"candidate"`。"""
    return AuthoringRule(rule_id=rule_id, rule=f"{rule_id} 的規則文字",
                         applies_when=applies_when, evidence=list(EIGHT_IDS[:5]),
                         status=RuleStatus(status), applied_to=[], derived_from=V1)


def seed_published_v1(repository: Repository) -> None:
    """已發布的 v1：Feature、Tutorial（current 指向 v1）、VERSION item 與 S3 全文。"""
    repository.put_meta(Feature(feature_id=FEATURE, name=FEATURE, aliases=[], first_seen=NOW))
    repository.put_meta(Tutorial(slug=SLUG, current_version=V1, topic="準備會議",
                                 feature_ids=[FEATURE], status=TutorialStatus.ACTIVE,
                                 successor=None, cluster_id="c12"))
    repository.put_meta(TutorialVersion(version_id=V1, slug=SLUG, supersedes=None,
                                        reason="gap:c12", rules_applied=[],
                                        s3_key=markdown_key(SLUG, 1), published_at=NOW))
    put_private_artifact(repository, markdown_key(SLUG, 1),
                         render_markdown(base_content()), MARKDOWN_CONTENT_TYPE)


def seed_feedback(repository: Repository, rows: Sequence[Feedback]) -> None:
    """一筆回饋 ＝ `FEEDBACK#` 本體 ＋ 指向該版的 `REFERS_TO` 邊（反查靠這條邊）。"""
    for row in rows:
        repository.put_meta(row)
        repository.put_edge(feedback_pk(row.id), "REFERS_TO", version_pk(row.tutorial_version))


@pytest.fixture
def repo() -> Iterator[RefineRepository]:
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
        yield RefineRepository(table, bucket)


@pytest.fixture
def world(repo: RefineRepository, fake_writer: Any) -> World:
    """已發布的 v1 ＋ 八筆同類回饋 ＋ 已被 O2 接受的 REFINE operation。"""
    seed_published_v1(repo)
    seed_feedback(repo, [feedback_row(row_id) for row_id in EIGHT_IDS])
    operation_id = refine_operation_id(V1, CATEGORY, EIGHT_IDS)
    operations = RefineOperations(repo)
    operations.accept(AcceptOperation(operation_id=operation_id, kind="feedback",
                                      canonical_id=evidence_fingerprint(V1, CATEGORY, EIGHT_IDS),
                                      project_id=PROJECT, now=NOW))
    diagnosis = DiagnosisResult(V1, (3,), {3: HIT_REASON}, EIGHT_IDS)
    return World(repo=repo, writer=fake_writer, operations=operations, base=base_content(),
                 diagnosis=diagnosis, operation_id=operation_id)


# --- Task 1：證據指紋、REFINE operation id 與固定 reason ---------------------


def test_fingerprint_ignores_order_and_duplicates() -> None:
    """Given 同一批 ID 換順序或帶重複，When 算指紋，Then 相同；換版本或換類別一定不同。"""
    left = evidence_fingerprint(V1, CATEGORY, ["f_2", "f_1", "f_1"])
    assert left == evidence_fingerprint(V1, CATEGORY, ["f_1", "f_2"])
    assert left != evidence_fingerprint(V2, CATEGORY, ["f_1", "f_2"])
    assert left != evidence_fingerprint(V1, OTHER_CATEGORY, ["f_1", "f_2"])
    assert refine_operation_id(V1, CATEGORY, ["f_1", "f_2"]) == f"op-feedback-{left}"


def test_fingerprint_is_a_sha256_hex_digest() -> None:
    """Given 任一批證據，When 算指紋，Then 是 64 個十六進位字元（operation id 的形狀依據）。"""
    digest = evidence_fingerprint(V1, CATEGORY, EIGHT_IDS)
    assert len(digest) == 64
    assert set(digest) <= set("0123456789abcdef")


def test_reason_counts_unique_evidence() -> None:
    """Given 八筆證據（含一筆重複），When 組 reason，Then 逐字是去重後的筆數與類別。"""
    assert refine_reason(CATEGORY, EIGHT_IDS) == "feedback:8 則 找不到按鈕"
    assert refine_reason(CATEGORY, [*EIGHT_IDS, "f_12"]) == "feedback:8 則 找不到按鈕"


def test_evidence_must_be_one_category(world: World) -> None:
    """Given 八筆同類證據，When 取證據，Then 回（類別, 排序 ID）；跨類別時 `ContentError`。"""
    assert evidence_of(world.diagnosis, repo=world.repo) == (CATEGORY, EIGHT_IDS)
    world.repo.recategorize("f_40", OTHER_CATEGORY)
    with pytest.raises(ContentError, match="同一個類別"):
        evidence_of(world.diagnosis, repo=world.repo)


def test_evidence_must_not_be_missing(world: World) -> None:
    """Given 診斷帶一個查無此筆的 ID，When 取證據，Then `ContentError`（不可少算證據）。"""
    diagnosis = DiagnosisResult(V1, (3,), {3: HIT_REASON}, (*EIGHT_IDS, "f_999"))
    with pytest.raises(ContentError, match="同一個類別"):
        evidence_of(diagnosis, repo=world.repo)


# --- Task 2：只改命中步驟，只記本次注入的規則 -------------------------------

REWRITE: dict[str, Any] = {"number": 3, "text": "在會議頁面右上角選擇 Meeting Summary。",
                           "feature_id": FEATURE, "type": "click_ui"}


def queue(world: World, *steps: dict[str, Any]) -> None:
    """把一次 `StepRewrite` 回應排進 conftest 的 `RecordingWriter`。"""
    world.writer.replies.append({"steps": [dict(step) for step in steps]})


def run(world: World) -> RefinePlan | None:
    return prepare_refine(world.diagnosis, repo=world.repo, writer=world.writer,
                          operations=world.operations, operation_id=world.operation_id)


def seed_rules(repository: Repository, rules: Sequence[AuthoringRule]) -> None:
    """規則本體 ＋ 最近驗證時間（唯一權威是 `operations/rules/validated_at.json`，D-28）。"""
    for item in rules:
        repository.put_meta(item)
    payload = {item.rule_id: "2026-09-10T00:00:00Z" for item in rules}
    repository.put_object(VALIDATED_AT_KEY, json.dumps(payload).encode("utf-8"),
                          "application/json", if_none_match=False)


def test_only_diagnosed_steps_change_and_others_are_byte_for_byte(world: World) -> None:
    """Given 診斷只命中第 3 步，When 改寫，Then 只有第 3 步變動，其餘步驟與四段逐字相同。

    `REV` Rule 7 的 primary 斷言。
    """
    queue(world, REWRITE)
    plan = run(world)
    assert (plan.version_id, plan.base_version_id) == (V2, V1)
    assert plan.changed_indexes == (3,)
    assert plan.reason == "feedback:8 則 找不到按鈕"
    assert plan.content.steps[2].text == REWRITE["text"]
    for number in (1, 2, 4):
        assert plan.content.steps[number - 1] == world.base.steps[number - 1]
    assert plan.content.model_dump(exclude={"steps"}) == world.base.model_dump(exclude={"steps"})


def test_refine_builds_an_unpublished_version_only(world: World) -> None:
    """Given 一次成功的改寫，When 看產物，Then v2 是未發布版本，且 current_version 沒被切換。"""
    queue(world, REWRITE)
    plan = run(world)
    created = world.repo.versions[V2]
    assert created.published_at is None
    assert created.supersedes == V1
    tutorial = world.repo.get_tutorial(SLUG)
    assert tutorial is not None and tutorial.current_version == V1
    assert plan.evidence_fingerprint == evidence_fingerprint(V1, CATEGORY, EIGHT_IDS)


def test_model_touching_an_extra_step_is_rejected(world: World) -> None:
    """Given 模型偷改沒被命中的第 2 步，When 改寫，Then `ContentError` 且沒有版本被建立。"""
    queue(world, REWRITE, {"number": 2, "text": "偷改的第二步。",
                           "feature_id": FEATURE, "type": "read"})
    with pytest.raises(ContentError, match="改寫集合"):
        run(world)
    assert world.repo.versions.get(V2) is None


def test_model_missing_a_diagnosed_step_is_rejected(world: World) -> None:
    """Given 模型一個命中步驟都沒回，When 改寫，Then `ContentError` 且沒有版本被建立。"""
    queue(world)
    with pytest.raises(ContentError, match="改寫集合"):
        run(world)
    assert world.repo.versions.get(V2) is None


def test_model_changing_the_feature_reference_is_rejected(world: World) -> None:
    """Given 模型把第 3 步改引用別的 Feature，When 改寫，Then `ContentError` 且不建版。"""
    queue(world, {**REWRITE, "feature_id": "Share"})
    with pytest.raises(ContentError, match="Feature 或型態"):
        run(world)
    assert world.repo.versions.get(V2) is None


def test_model_changing_the_step_type_is_rejected(world: World) -> None:
    """Given 模型把第 3 步的 type 從 click_ui 改成 read，When 改寫，Then `ContentError`。"""
    queue(world, {**REWRITE, "type": "read"})
    with pytest.raises(ContentError, match="Feature 或型態"):
        run(world)
    assert world.repo.versions.get(V2) is None


def test_blank_rewritten_text_is_rejected(world: World) -> None:
    """Given 模型回的新文字去空白後是空的，When 改寫，Then `ContentError` 且不建版。"""
    queue(world, {**REWRITE, "text": "   \n  "})
    with pytest.raises(ContentError, match="新文字是空的"):
        run(world)
    assert world.repo.versions.get(V2) is None


def test_only_rules_injected_for_hit_steps_are_recorded(world: World) -> None:
    """Given active 規則同時涵蓋命中與未命中步驟的型態，When 改寫，Then 只記注入的那條。

    第 1、4 步是 `read`，即使 `R-012` 也是 active，也不因「原文沿用」進入 `rules_applied`
    （F29）；candidate 的 `R-099` 永不入選（`APL` Rule 2）。
    """
    seed_rules(world.repo, [rule("R-007", StepType.CLICK_UI),
                            rule("R-012", StepType.READ),
                            rule("R-099", StepType.CLICK_UI, status="candidate")])
    queue(world, REWRITE)
    plan = run(world)
    assert plan.rules_applied == ("R-007",)
    injected = world.writer.calls[0]["user"]
    assert "[R-007]" in injected
    assert "R-012" not in injected
    assert "R-099" not in injected


def test_refine_prompt_is_the_refine_node_with_untrusted_text_as_data(world: World) -> None:
    """Given 一次改寫，When 看送出的 prompt，Then node 是 refine_steps 且留言只當資料。"""
    queue(world, REWRITE)
    run(world)
    call = world.writer.calls[0]
    assert call["node"] == "refine_steps"
    assert call["schema"]["$id"] == "StepRewrite"
    assert call["user"].count("</source_data>") == 1
    # 只放命中步驟的原文；未命中步驟不進 prompt，模型看不到就無從「順手」改它。
    assert "開啟摘要。" in call["user"]
    assert "選擇目標會議。" not in call["user"]


def test_refine_uses_the_tutorial_writing_inference_config(world: World) -> None:
    """Given 一次改寫，When 看 schema，Then 走教學寫作類參數（2048／0.1，00A §3.7）。

    參數本身由 Phase 15／18 的 `inference_config(schema)` 依 `$id` 決定，本 Phase 不自己調；
    這裡斷言的是「REFINE 傳的是 `StepRewrite`」這條證據鏈的起點。
    """
    queue(world, REWRITE)
    run(world)
    assert inference_config(world.writer.calls[0]["schema"]) == {"maxTokens": 2048,
                                                                 "temperature": 0.1}


# --- Task 3：lease、同 operation 重送與同證據不再產版 -----------------------


def test_lease_conflict_raises_transient_error(world: World) -> None:
    """Given 同一篇的 lease 已被別人持有，When 改寫，Then `TransientError`（交 ASL 重試）。

    lease 只讓同一篇的併發改寫串行（設計 §8.3）；拿不到就往外丟，**不自行迴圈等待**。
    """
    world.operations.hold(f"TUTORIAL#{SLUG}", owner="op-other")
    queue(world, REWRITE)
    with pytest.raises(TransientError):
        run(world)
    assert world.repo.versions.get(V2) is None
    assert world.writer.request_attempts == 0


def test_lease_is_released_even_when_the_rewrite_fails(world: World) -> None:
    """Given 改寫在 lease 之內失敗，When 同 operation 重送，Then 租約已釋放、版本沒建出來。

    重送仍然是同一個 `ContentError`（不是 `TransientError`）這件事本身就證明租約還回去了
    ——沒還的話 `acquire_lease` 會先失敗。

    **現況核對（修正波 2026-09-15，final review A#3）：** 本測試原本還斷言
    `request_attempts == 1`，也就是「重送沿用同一份不合格的輸出，不讓模型再擲一次骰子」。
    修正波把 `_reuse_or_call` 改成「存下來的改寫對不上這次的命中集合就丟掉重打」——
    不這樣做的話，一份改寫集合永遠對不上的輸出會讓這批證據**永遠**走不完（controller
    裁決 4）。所以現在第二次會再打一次模型（`request_attempts == 2`），要守的行為
    ——租約有還、版本沒建出來、錯誤型別不變——完全沒變。
    """
    bad = {"number": 2, "text": "偷改的第二步。", "feature_id": FEATURE, "type": "read"}
    queue(world, REWRITE, bad)
    with pytest.raises(ContentError, match="改寫集合"):
        run(world)
    queue(world, REWRITE, bad)
    with pytest.raises(ContentError, match="改寫集合"):
        run(world)
    assert world.writer.request_attempts == 2
    assert world.repo.versions.get(V2) is None


def test_operation_id_must_match_the_evidence(world: World) -> None:
    """Given operation_id 不是這批證據的指紋導出的，When 改寫，Then `CoordinationError`。"""
    with pytest.raises(CoordinationError, match="指紋不符"):
        prepare_refine(world.diagnosis, repo=world.repo, writer=world.writer,
                       operations=world.operations,
                       operation_id="op-feedback-review-demo-2026-09-13")
    assert world.repo.versions.get(V2) is None
    assert world.writer.request_attempts == 0


def test_operation_must_be_accepted_first(world: World) -> None:
    """Given 指紋對但 O2 還沒接受這筆 operation，When 改寫，Then `CoordinationError`。"""
    other = DiagnosisResult(V1, (3,), {3: HIT_REASON}, EIGHT_IDS[:5])
    with pytest.raises(CoordinationError, match="尚未被 O2 接受"):
        prepare_refine(other, repo=world.repo, writer=world.writer,
                       operations=world.operations,
                       operation_id=refine_operation_id(V1, CATEGORY, EIGHT_IDS[:5]))


def test_no_step_and_same_evidence_return_none(world: World) -> None:
    """Given NO_STEP 或同一批證據**已經發布**之後再送，When 改寫，Then 都回 None。

    `NO_STEP`（F24）與 `no_new_evidence`（F23）都是**合法業務結果**，不是錯誤；兩者都不配
    版號、不呼叫模型。

    **現況核對（修正波 2026-09-15，final review A#2）：** F23 的短路條件從「完整」收緊成
    「完整**且已發布**」。本 Phase 不發布，所以這裡自己把 v2 的 `published_at` 補上，
    重現「上一批真的發布出去了」——沒補的話第二次會拿回既有版本的 `RefinePlan`
    （見 `test_an_unpublished_complete_version_is_offered_for_republish`）。
    """
    queue(world, REWRITE)
    empty = DiagnosisResult(V1, (), {}, world.diagnosis.feedback_ids)
    assert prepare_refine(empty, repo=world.repo, writer=world.writer,
                          operations=world.operations,
                          operation_id=world.operation_id) is None
    first = run(world)
    assert first is not None and first.version_id == V2
    publish(world, V2)
    assert run(world) is None  # 同一批證據且已發布：no_new_evidence（F23）
    assert world.writer.request_attempts == 1
    assert sorted(key for key in world.repo.versions if key.startswith(f"{SLUG}@")) == [V1, V2]


def publish(world: World, version_id: str) -> None:
    """把一版切成已發布；`Publisher.commit` 在真實流程裡做的就是這件事的一半。"""
    pk = version_pk(version_id)
    world.repo.update_meta(pk, {"published_at": to_iso(NOW)},
                           expected_revision=world.repo.revision_of(pk))


def test_an_unpublished_complete_version_is_offered_for_republish(world: World) -> None:
    """Given 版本已建好但還沒發布，When 同一批證據再送，Then 拿回**既有版本**的 RefinePlan。

    修正波（final review A#2）：原本這裡回 `None`（`no_new_evidence`），所以
    「上一次在 Prepare／Inspect／Commit 掛掉」之後，後續每一次 Review 都會短路成沒有新
    證據——`prepared_version_ids` 是空的、整條流程 `Succeeded`，那一版卻永遠不會發布。

    回傳的是既有產物，不是重做一次：不打模型、不配新版號、版本總數不變。
    """
    queue(world, REWRITE)
    first = run(world)
    assert first is not None and first.version_id == V2

    again = run(world)

    assert again is not None and again.version_id == V2
    assert again.evidence_fingerprint == first.evidence_fingerprint
    assert again.content == first.content
    assert world.writer.request_attempts == 1
    assert sorted(key for key in world.repo.versions if key.startswith(f"{SLUG}@")) == [V1, V2]


def test_shuffled_and_duplicated_evidence_is_the_same_operation(world: World) -> None:
    """Given 同八個 ID 打亂順序又帶重複，When 算 operation id，Then 與原本逐字相同。

    去重的依據是指紋，不是呼叫端傳進來的順序；跨日重跑因此撞到同一筆 `OPS#` 永久紀錄。
    """
    shuffled = ("f_40", "f_12", "f_31", "f_12", "f_19", "f_23", "f_15", "f_27", "f_34")
    assert refine_operation_id(V1, CATEGORY, shuffled) == world.operation_id


def test_storage_retry_reuses_the_version_and_the_model_output(world: World) -> None:
    """Given 上次寫到一半（VERSION 有了、關係邊沒寫完），When 同 operation 重送，
    Then 沿用同版號與既有模型輸出，**不再呼叫模型**（設計 §14.2）。

    這裡用刪掉一筆 STEP 邊來重現「不完整」：`verify_version_complete` 因此回 `False`，
    `_guard` 就不會把它當成 `no_new_evidence`。
    """
    queue(world, REWRITE)
    first = run(world)
    assert first is not None
    world.repo.break_one_step_edge(V2)
    assert not verify_version_complete(V2, world.repo)

    second = run(world)  # 沒有再 queue 回應：再打模型就會 PermanentError
    assert second is not None
    assert second.version_id == V2
    assert world.writer.request_attempts == 1
    record = world.operations.load(world.operation_id)
    assert record is not None and record.version_id == V2
    assert len(record.model_output_refs) == 1
    assert verify_version_complete(V2, world.repo)
