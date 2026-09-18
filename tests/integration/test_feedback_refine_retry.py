"""Phase 46：REFINE 在儲存中斷後以同 operation 重送的行為（版號與模型輸出都重用）。

兩段，情境完全相同、只差在跑在哪裡：

1. **moto 段**（不標 `aws`，一律執行）：證明腳本本身沒壞、資料形狀正確。
   moto 的綠燈**不是**永久去重的證據。
2. **真實 AWS 段**（`@pytest.mark.aws`，`TKB_RUN_AWS_INTEGRATION=1` 才跑）：對真實
   DynamoDB 單表與 S3 bucket 跑同一組斷言。**O2 已於 Phase 11 PASS**（見
   `docs/plan/report/o2-20260914t182824z.md`），所以這一段不再標 blocked，要實際執行並
   把輸出寫進 Phase 46 報告。

切點：`create_version` 寫完 `.md`／`.diff` 與 VERSION item、正要寫 STEP 關係邊時中斷
（設計 §14.1 的「部分寫入保留未完成版本」）。重送必須：

- 版號仍是同一個（`allocate_version` 走 `_replay_plan`，D26）；
- `record.model_output_refs` 沒有變長，而且 `writer.request_attempts` 仍是 1
  （`_reuse_or_call` 沿用既有輸出，**不再呼叫模型**，設計 §14.2）；
- 補齊之後 `verify_version_complete` 才為真。

模型一律是假的（**O5 BLOCKED**）：這裡沒有任何 Bedrock 呼叫，綠燈不代表 Bedrock 通過。
本檔也**不發布**：建出來的第二版 `published_at` 是 `None`，只在私有前綴（O3 FAIL 不受影響）。

真實 AWS 段用**明確的 demo 識別碼**（`p46-refine-<run tag>`），每次執行都是一組新的
slug／Feature／Feedback／operation，不碰既有資料；建立的 item 清單列在 Phase 46 報告 §4。
"""

import json
import os
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import boto3
import pytest

from training_kb.content import (
    MARKDOWN_CONTENT_TYPE,
    markdown_key,
    put_private_artifact,
    render_markdown,
    verify_version_complete,
)
from training_kb.errors import PermanentError
from training_kb.keys import feedback_pk, version_pk
from training_kb.models import (
    Feature,
    Feedback,
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
    prepare_refine,
    refine_operation_id,
)
from training_kb.repository import Repository

NOW = datetime(2026, 9, 14, tzinfo=UTC)
CATEGORY = "Button not found"
EIGHT_IDS = ("f_12", "f_15", "f_19", "f_23", "f_27", "f_31", "f_34", "f_40")
HIT_REASON = "沒有指出按鈕所在頁面與位置"
REWRITE: dict[str, Any] = {"number": 3, "text": "在會議頁面右上角選擇 Meeting Summary。",
                           "feature_id": "", "type": "click_ui"}

_STEP_TEXTS = ("開啟會議。", "選擇目標會議。", "開啟摘要。", "確認會前重點。")
_STEP_TYPES = (StepType.READ, StepType.CLICK_UI, StepType.CLICK_UI, StepType.READ)

TABLE_ENV = "TKB_TABLE_NAME"
BUCKET_ENV = "TKB_CONTENT_BUCKET"
REGION_ENV = "TKB_AWS_REGION"


class ScriptedWriter:
    """只回一次 `StepRewrite` 的假 Writer；被呼叫第二次就是測試失敗（O5 BLOCKED）。"""

    def __init__(self, reply: dict[str, Any]) -> None:
        self._reply = reply
        self.request_attempts = 0

    def generate_json(self, system: str, user: str, schema: Any, *,
                      operation_id: str, node: str) -> dict[str, Any]:
        self.request_attempts += 1
        if self.request_attempts > 1:
            raise PermanentError("重送不得再呼叫模型（設計 §14.2）")
        return dict(self._reply)

    def embed(self, text: str, *, operation_id: str, node: str) -> list[float]:
        raise AssertionError("REFINE 不呼叫 embedding")

    def converse_with_tools(self, system: str, messages: Any, tools: Any, *,
                            operation_id: str, node: str) -> dict[str, Any]:
        raise AssertionError("REFINE 只用 generate_json")


class BrokenEdgeRepository:
    """把第一次的 STEP 關係邊寫入變成失敗，重現設計 §14.1 的部分寫入。

    只代理 `put_edge`，其餘一律轉給真的 `Repository`：`.md`／`.diff` 與 VERSION item 都
    真的寫出去了，缺的只有關係邊——這正是「上次寫到一半」的樣子。
    """

    def __init__(self, inner: Repository) -> None:
        self._inner = inner
        self.armed = True

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    def put_edge(self, pk: str, relation: str, target_pk: str,
                 attrs: Any = None) -> None:
        if self.armed and pk.startswith("STEP#"):
            self.armed = False
            raise PermanentError("注入的中斷：STEP 關係邊寫到一半")
        self._inner.put_edge(pk, relation, target_pk, attrs)


@dataclass
class Scenario:
    """一次重送情境需要的識別碼與器材；真實表與 moto 共用同一份腳本。"""

    repo: Repository
    operations: OperationCoordinator
    slug: str
    feature: str
    version_id: str
    next_version_id: str
    feedback_ids: tuple[str, ...]
    operation_id: str
    diagnosis: DiagnosisResult


def base_content(feature: str) -> TutorialContent:
    steps = [
        StepDraft(number=index + 1, type=_STEP_TYPES[index], text=_STEP_TEXTS[index],
                  feature_id=feature)
        for index in range(4)
    ]
    return TutorialContent(title="準備會議",
                           problem="會議前的準備步驟散在多個頁面，新人找不到。",
                           prerequisites=["已登入工作區"], steps=steps,
                           expected_outcome="會議開始前已備妥議程與摘要。")


def build_scenario(repository: Repository, *, tag: str) -> Scenario:
    """種好「已發布的 v1 ＋ 八筆同類回饋 ＋ 已接受的 REFINE operation」。"""
    slug = f"p46-refine-{tag}"
    feature = f"P46Demo{tag}"
    version_id = f"{slug}@v1"
    feedback_ids = tuple(f"p46_{tag}_{row_id}" for row_id in EIGHT_IDS)

    repository.put_meta(Feature(feature_id=feature, name=feature, aliases=[], first_seen=NOW))
    repository.put_meta(Tutorial(slug=slug, current_version=version_id, topic="準備會議",
                                 feature_ids=[feature], status=TutorialStatus.ACTIVE,
                                 successor=None, cluster_id=f"c-{tag}"))
    repository.put_meta(TutorialVersion(version_id=version_id, slug=slug, supersedes=None,
                                        reason="gap:demo", rules_applied=[],
                                        s3_key=markdown_key(slug, 1), published_at=NOW))
    put_private_artifact(repository, markdown_key(slug, 1),
                         render_markdown(base_content(feature)), MARKDOWN_CONTENT_TYPE)
    for row_id in feedback_ids:
        repository.put_meta(Feedback(id=row_id, tutorial_version=version_id, rating=2,
                                     category=CATEGORY, comment="找不到那顆按鈕",
                                     user="u_01", ts=NOW))
        repository.put_edge(feedback_pk(row_id), "REFERS_TO", version_pk(version_id))

    operation_id = refine_operation_id(version_id, CATEGORY, feedback_ids)
    operations = OperationCoordinator(repository)
    operations.accept(AcceptOperation(
        operation_id=operation_id, kind="feedback",
        canonical_id=evidence_fingerprint(version_id, CATEGORY, feedback_ids),
        project_id=f"p46-demo-{tag}", now=NOW))
    return Scenario(repo=repository, operations=operations, slug=slug, feature=feature,
                    version_id=version_id, next_version_id=f"{slug}@v2",
                    feedback_ids=feedback_ids, operation_id=operation_id,
                    diagnosis=DiagnosisResult(version_id, (3,), {3: HIT_REASON}, feedback_ids))


def run_retry_scenario(scenario: Scenario) -> dict[str, Any]:
    """中斷一次再以同 operation 重送；回一份可以直接貼進報告的觀察值。"""
    writer = ScriptedWriter({"steps": [{**REWRITE, "feature_id": scenario.feature}]})
    broken = BrokenEdgeRepository(scenario.repo)

    with pytest.raises(PermanentError, match="注入的中斷"):
        prepare_refine(scenario.diagnosis, repo=broken, writer=writer,
                       operations=scenario.operations, operation_id=scenario.operation_id)

    after_break = scenario.operations.load(scenario.operation_id)
    assert after_break is not None
    assert after_break.version_id == scenario.next_version_id  # 版號已記下
    assert len(after_break.model_output_refs) == 1             # 模型輸出已保存
    assert not verify_version_complete(scenario.next_version_id, scenario.repo)

    plan = prepare_refine(scenario.diagnosis, repo=scenario.repo, writer=writer,
                          operations=scenario.operations, operation_id=scenario.operation_id)
    assert plan is not None
    assert plan.version_id == scenario.next_version_id          # 同版號（D26）
    assert plan.changed_indexes == (3,)
    assert plan.reason == "feedback:8 則 Button not found"
    assert writer.request_attempts == 1                         # 重送沒有再打模型

    after_retry = scenario.operations.load(scenario.operation_id)
    assert after_retry is not None
    assert after_retry.version_id == scenario.next_version_id
    assert len(after_retry.model_output_refs) == 1              # 沒有多一筆
    assert verify_version_complete(scenario.next_version_id, scenario.repo)

    created = scenario.repo.get_version(scenario.next_version_id)
    assert created is not None and created.published_at is None  # 未發布（不碰 site/）

    # 修正波（final review A#2）：F23 的短路條件是「完整**且已發布**」。這裡的 v2 還沒發布
    # （本 Phase 不碰 site/），所以第三次拿回的是**既有版本**的 RefinePlan——讓上一次沒發布
    # 完的那一版回到下一批重新發布，而不是短路成「沒有新證據」讓它永遠停在未發布。
    # 重點不變：不再打模型、不配新版號。
    third = prepare_refine(scenario.diagnosis, repo=scenario.repo, writer=writer,
                           operations=scenario.operations,
                           operation_id=scenario.operation_id)
    assert third is not None and third.version_id == scenario.next_version_id
    assert writer.request_attempts == 1

    return {
        "slug": scenario.slug,
        "feature": scenario.feature,
        "operation_id": scenario.operation_id,
        "version_id": plan.version_id,
        "reason": plan.reason,
        "model_output_refs": list(after_retry.model_output_refs),
        "request_attempts": writer.request_attempts,
        "published_at": created.published_at,
        "feedback_ids": list(scenario.feedback_ids),
    }


# --- moto 段：腳本自身的回歸，**不是** O2 證據 ------------------------------


def test_storage_retry_reuses_version_and_model_output_on_moto(repository: Repository) -> None:
    """Given 寫 STEP 邊時中斷，When 同 operation 重送，Then 同版號、重用輸出、只打一次模型。

    這一段跑在 moto 上：只證明腳本與資料形狀正確，**不是**永久去重（O2）的證據。
    """
    observed = run_retry_scenario(build_scenario(repository, tag="moto"))
    assert observed["version_id"] == "p46-refine-moto@v2"
    assert observed["request_attempts"] == 1
    assert observed["published_at"] is None


# --- 真實 AWS 段：O2 已 PASS，這裡要真的跑 ---------------------------------


@pytest.fixture
def live_repository() -> Iterator[Repository]:
    """真實 DynamoDB 單表與 S3 bucket；名稱從環境變數取，不寫死在測試裡。"""
    region = os.environ.get(REGION_ENV, "us-east-1")
    table_name = os.environ.get(TABLE_ENV, "training_kb")
    bucket_name = os.environ.get(BUCKET_ENV)
    if not bucket_name:
        pytest.skip(f"需要真實 bucket 名稱；設 {BUCKET_ENV}=<TrainingKbData 的 content bucket>")
    table = boto3.resource("dynamodb", region_name=region).Table(table_name)
    bucket = boto3.resource("s3", region_name=region).Bucket(bucket_name)
    yield Repository(table, bucket)


@pytest.mark.aws
def test_storage_retry_reuses_version_and_model_output_on_real_aws(
    live_repository: Repository, capsys: pytest.CaptureFixture[str],
) -> None:
    """Given 真實表上寫 STEP 邊時中斷，When 同 operation 重送，Then 同版號且不再打模型。

    **O2 已於 Phase 11 PASS**，所以這一條不再標 blocked。每次執行用一組新的 demo 識別碼
    （`p46-refine-<run tag>`），不碰既有資料；建立的 item 列在 Phase 46 報告 §4。
    模型仍是假的（O5 BLOCKED）：本測試不呼叫 Bedrock。
    """
    tag = os.environ.get("TKB_P46_RUN_TAG") or uuid.uuid4().hex[:8]
    observed = run_retry_scenario(build_scenario(live_repository, tag=tag))
    with capsys.disabled():
        print("\nPhase46 real-AWS evidence:",
              json.dumps(observed, ensure_ascii=False, indent=2, default=str))
    assert observed["version_id"] == f"p46-refine-{tag}@v2"
    assert observed["request_attempts"] == 1
    assert observed["published_at"] is None
