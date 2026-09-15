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

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import boto3
import pytest
from moto import mock_aws

from training_kb.analytics.status_writer import VALIDATED_AT_KEY
from training_kb.content import (
    MARKDOWN_CONTENT_TYPE,
    markdown_key,
    put_private_artifact,
    render_markdown,
)
from training_kb.errors import ContentError
from training_kb.keys import feedback_pk, version_pk
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
    DiagnosisResult,
    evidence_fingerprint,
    evidence_of,
    refine_operation_id,
    refine_reason,
)
from training_kb.repository import Repository, item_to_model

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
    """真 `Repository` 行為 ＋ 兩個測試觀察鉤子；沒有覆寫任何既有行為。"""

    @property
    def versions(self) -> dict[str, TutorialVersion]:
        """目前表裡的全部 VERSION item；用來斷言「沒有版本被建立」。"""
        rows = [item_to_model(item, TutorialVersion) for item in self.scan_entity("VERSION")]
        return {row.version_id: row for row in rows}

    def recategorize(self, feedback_id: str, category: str) -> None:
        """把一筆回饋改成別的類別；用來製造「同一批證據跨類別」這個停止點。"""
        pk = feedback_pk(feedback_id)
        self.update_meta(pk, {"category": category}, expected_revision=self.revision_of(pk))


@dataclass
class World:
    """一次 REFINE 需要的全部器材；欄位名與 Phase 文件 §7 的 `world` 一致。"""

    repo: RefineRepository
    writer: Any
    operations: OperationCoordinator
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
    operations = OperationCoordinator(repo)
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
