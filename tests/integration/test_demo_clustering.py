"""Phase 56：Demo 種子寫入（moto）與二十筆工單的真實 Titan 分群（`aws`）。

兩段刻意放同一支檔案：00A §3.3 只配給 Phase 56 一個整合測試檔名。

- **上半段（moto）**：`apply_seed` 把整份種子寫進本機假表與假 bucket，逐版通過
  Phase 23 的 `verify_version_complete`。moto 綠燈只證明資料形狀，不是真實表的證據。
- **下半段（`@pytest.mark.aws`）**：真實 Bedrock Titan 的分群。未設
  `TKB_RUN_AWS_INTEGRATION=1` 時由 `tests/conftest.py` 自動 skip；
  **skip 不等於 PASS**。2026-09-14 現況是 **O5 BLOCKED**（Titan 回
  `ValidationException: Operation not allowed`），所以這兩個測試另外標
  `xfail(strict=False)`：真的跑起來時它們會 xfail 並留下錯誤原文，O5 一旦開通就會
  xpass，提醒把標記拿掉。**任何情況下都不得回退成預填 `cluster_id`。**

整份種子是**明示的合成資料**，這裡的斷言不代表任何真實使用者成效。
"""

from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from demo.scripts.cluster_demo_tickets import BLOCKED, OPERATION_ID, clustering_report
from demo.seed_loader import apply_seed, cluster_demo_tickets, creation_tickets, load_seed
from training_kb.content import verify_version_complete
from training_kb.models import RuleStatus
from training_kb.repository import Repository
from training_kb.writing.client import BedrockWriter, CallTrace, build_bedrock_client

SEED_DIR = Path(__file__).resolve().parents[2] / "demo" / "seed"
NOW = datetime(2026, 9, 14, tzinfo=UTC)
FIXED = [0.001] * 1024


class LocalWriter:
    """只回固定向量的假 Writer（`tests/unit/conftest.py` 的 `RecordingWriter` 在 unit 才看得到）。

    **不連 Bedrock。** 用它跑出來的分群只證明路徑接對了，不是 O5 的證據。
    """

    def __init__(self) -> None:
        self.calls: list[str] = []

    def embed(self, text: str, *, operation_id: str, node: str) -> list[float]:
        self.calls.append(node)
        return list(FIXED)

    def generate_json(self, system: str, user: str, schema: Any, *,
                      operation_id: str, node: str) -> dict[str, Any]:
        raise AssertionError("種子載入不呼叫生成模型")

    def converse_with_tools(self, system: str, messages: Sequence[Any], tools: Sequence[Any], *,
                            operation_id: str, node: str) -> dict[str, Any]:
        raise AssertionError("種子載入不呼叫工具迴圈")


# --- moto：apply_seed --------------------------------------------------------


def test_apply_seed_writes_every_version_completely(repository: Repository) -> None:
    """Given 完整種子 When apply_seed 兩次 Then 八個版本完整，重跑不重寫版本與步驟。

    兩件事寫在同一個測試裡是為了省一次完整載入：moto 上跑一次 `apply_seed` 要十秒級，
    而「重跑」本來就只能接在「跑過一次」後面。
    """
    bundle = load_seed(SEED_DIR)
    written = apply_seed(bundle, repository=repository, now=NOW)
    assert len(written) == len(set(written))
    for version in bundle.versions:
        assert verify_version_complete(version.version_id, repository), version.version_id
        stored = repository.get_version(version.version_id)
        assert stored == version
        assert repository.get_object(version.s3_key) is not None
    assert len(repository.list_feedback_of_version("prepare-meeting@v1")) == 8
    assert len(repository.list_views_of_version("weekly-digest@v4")) == 20
    assert len(repository.list_tickets("demo")) == 46
    assert {rule.rule_id for rule in repository.list_rules()} == {"R-007", "R-012"}
    assert {rule.rule_id for rule in repository.list_rules(RuleStatus.CANDIDATE)} == {"R-007"}

    again = apply_seed(bundle, repository=repository, now=NOW)
    assert not [pk for pk in again if pk.startswith(("VERSION#", "STEP#"))]
    assert len([pk for pk in again if pk.startswith("TICKET#")]) == 46


def test_cluster_demo_tickets_assigns_all_twenty_on_a_real_repository(
    repository: Repository,
) -> None:
    """Given 種子已載入 When 用固定向量分群 Then 二十筆都拿到群號並寫回 TICKET item。"""
    bundle = load_seed(SEED_DIR)
    apply_seed(bundle, repository=repository, now=NOW)
    assigned = cluster_demo_tickets(bundle, writer=LocalWriter(), repository=repository,
                                    operation_id="demo-cluster-moto")
    assert len(assigned) == 20
    for ticket in creation_tickets(bundle):
        stored = repository.get_meta(f"TICKET#{ticket.id}", type(ticket))
        assert stored is not None
        assert stored.cluster_id == assigned[ticket.id]
        assert stored.embedding is not None and len(stored.embedding) == 1024


# --- 真實 Bedrock Titan：O5 BLOCKED 時 skip，跑起來時 xfail ------------------

pytestmark_aws = pytest.mark.aws


@pytest.mark.aws
@pytest.mark.xfail(strict=False, reason="O5 BLOCKED：Titan 回 ValidationException")
def test_real_titan_clusters_the_twenty_demo_tickets(repository: Repository) -> None:
    """Given 真實 Titan When 對二十筆分群 Then 每筆一個 1024 維向量、attempt 數等於呼叫數。

    這個測試用 moto 的 `repository`（只有 Bedrock 是真的），所以不會寫進真實表。
    """
    import os
    bundle = load_seed(SEED_DIR)
    apply_seed(bundle, repository=repository, now=NOW)
    trace = CallTrace()
    writer = BedrockWriter(build_bedrock_client(os.environ["TKB_BEDROCK_REGION"]), trace,
                           generation_model_id=None,
                           embedding_model_id=os.environ["TKB_EMBEDDING_MODEL_ID"])
    assigned = cluster_demo_tickets(bundle, writer=writer, repository=repository,
                                    operation_id=OPERATION_ID)
    assert len(assigned) == 20
    assert trace.count(operation_id=OPERATION_ID) == 20
    for ticket in creation_tickets(bundle):
        stored = repository.get_meta(f"TICKET#{ticket.id}", type(ticket))
        assert stored is not None and stored.embedding is not None
        assert len(stored.embedding) == 1024


@pytest.mark.aws
@pytest.mark.xfail(strict=False, reason="O5 BLOCKED：同一筆重跑要不重算，前提是第一次算得出來")
def test_real_titan_does_not_recompute_an_existing_embedding(repository: Repository) -> None:
    """Given 同一筆已經有向量 When 再跑一次 Then 不再呼叫 Bedrock（設計 §14.2）。"""
    import os
    bundle = load_seed(SEED_DIR)
    apply_seed(bundle, repository=repository, now=NOW)
    trace = CallTrace()
    writer = BedrockWriter(build_bedrock_client(os.environ["TKB_BEDROCK_REGION"]), trace,
                           generation_model_id=None,
                           embedding_model_id=os.environ["TKB_EMBEDDING_MODEL_ID"])
    cluster_demo_tickets(bundle, writer=writer, repository=repository, operation_id=OPERATION_ID)
    first = trace.count(operation_id=OPERATION_ID)
    cluster_demo_tickets(bundle, writer=writer, repository=repository, operation_id=OPERATION_ID)
    assert trace.count(operation_id=OPERATION_ID) == first


def test_the_blocked_clustering_report_never_carries_observed_clusters(tmp_path: Path) -> None:
    """Given 分群腳本記下 BLOCKED When 讀報告 Then `observed` 是 null、沒有 tickets_clustered。

    這是本批的實際狀態（O5 BLOCKED）：**空的觀察值必須長得像空的**，
    不得回退成預填 `cluster_id`，也不得產生一份看起來跑過的 `tickets_clustered.json`。
    """
    report = clustering_report(status=BLOCKED, reason="ValidationException: Operation not allowed",
                               probed_at=NOW, assigned=None)
    assert report["status"] == BLOCKED
    assert report["observed"] is None
    assert report["tickets"] == []
    assert report["synthetic"] is True
    assert not (tmp_path / "tickets_clustered.json").exists()
