"""Phase 41 Task 1／2：ticket-analysis 七個 Task 的本機序列、跳過分支與兩層 handler 分派。

共用替身（`FakeRepository`／`FakeOperations`／`FakeWriter`／`dt`）定義在
`test_ticket_decide.py`（Phase 40），本檔只 import 類別再往上加這條流程需要的幾個方法：
`list_tickets`（P38／P39 的掃描來源）、`transact_write`／`list_versions_of_tutorial`／
`table_name`（P24 發布路徑）。**不改 `tests/unit/pipelines/conftest.py`**——同一波次的
P48／P52 也用那支檔（COMMON.md R3）。

`local_deps` 因此是本檔自己的 fixture（Phase 41 文件 §7 Task 1 Step 1 的現況核對已說明：
原文件示意的 `writer.generate_calls`／`repository.created_versions` 兩個屬性不存在）。

替身的 `transact_write` **只套用 SET、不驗條件**：本檔測的是「七個 Task 有沒有依序把小型
結果併回 state」，發布交易的條件語意由 P24／P25 的 `test_publisher_single.py` 與
`test_batch_publish_cutpoints.py`（moto）負責，這裡不重複一份。
"""

import json
from datetime import UTC, datetime
from typing import Any

import pytest
from test_ticket_decide import FakeOperations, FakeRepository, FakeWriter, dt

from training_kb.config import Settings
from training_kb.errors import PermanentError, TransientError
from training_kb.keys import META, operation_ref, ticket_pk, tutorial_pk
from training_kb.models import Ticket, Tutorial, TutorialStatus, TutorialVersion
from training_kb.pipelines import ticket as ticket_pipeline
from training_kb.pipelines.common import (
    Deps,
    build_deps,
    pipeline_task_handler,
    task_name,
)
from training_kb.pipelines.ticket import (
    TICKET_ANALYSIS_TASKS,
    TICKET_STATE_FIELDS,
    run_ticket_analysis,
)
from training_kb.repository import item_to_model, version_sort_key

TICKET_TS = datetime(2026, 9, 13, 2, 0, 0, tzinfo=UTC)
"""同一個 UTC 十四天窗口內的工單時間；整秒（`models.py` 拒絕帶微秒的 datetime）。"""

NOW = dt("2026-09-13T02:05:00Z")
OPERATION_ID = "op-ticket-t_881"
INPUT_REF = operation_ref(OPERATION_ID, "input")
VECTOR = [0.1] * 1024
"""1024 維是 Titan 的維度契約（P16）；同一個向量讓 cosine 固定 1.0。"""

TASK_NAMES = ["ensure_embedding", "assign_cluster", "evaluate_recurring", "name_gap",
              "decide_action", "create_first_version", "publish_version"]


def ticket(ticket_id: str, *, cluster_id: str | None = None,
           embedding: list[float] | None = None) -> Ticket:
    return Ticket(id=ticket_id, source="github_issue", text=f"{ticket_id} 的原始提問",
                  author="reporter", ts=TICKET_TS, project_id="demo",
                  cluster_id=cluster_id, embedding=embedding)


class FlowRepository(FakeRepository):
    """P40 的假表再加上本條流程走到的四個原語。"""

    def list_tickets(self, project_id: str) -> list[Ticket]:
        rows = [item_to_model(row, Ticket) for row in self.scan_entity("TICKET")]
        return sorted((row for row in rows if row.project_id == project_id),
                      key=lambda row: row.id)

    def list_versions_of_tutorial(self, slug: str) -> list[TutorialVersion]:
        rows = [item_to_model(row, TutorialVersion) for row in self.scan_entity("VERSION")]
        return sorted((row for row in rows if row.slug == slug),
                      key=lambda row: version_sort_key(row.version_id))

    @property
    def table_name(self) -> str:
        return "training_kb"

    def transact_write(self, items: list[dict[str, Any]]) -> int | None:
        """只套用 `SET <欄位> = :值`，條件一律視為成立（見模組 docstring）。"""
        for item in items:
            update = item["Update"]
            key = (str(update["Key"]["PK"]), META)
            values = update["ExpressionAttributeValues"]
            if "published_at" in str(update["UpdateExpression"]):
                self.table[key]["published_at"] = values[":now"]
            else:
                self.table[key]["current_version"] = values[":version"]
        return None

    # --- 種子鉤子：不記進 `writes` ---

    def seed_ticket(self, entity: Ticket) -> None:
        self._seed(entity)

    def seed_input(self, entity: Ticket) -> None:
        """接入層（P32 `_put_canonical_input_once`）存下的 canonical 輸入。"""
        self.objects[INPUT_REF] = json.dumps(entity.model_dump(mode="json"),
                                             ensure_ascii=False, sort_keys=True).encode("utf-8")


class FlowOperations(FakeOperations):
    """P40 的假 operation 紀錄再加上 `run_sequence` 失敗時會呼叫的 `fail`。"""

    def __init__(self, operation_id: str = OPERATION_ID) -> None:
        super().__init__(operation_id)
        self.failures: list[tuple[str, str, bool]] = []

    def fail(self, operation_id: str, error: str, retryable: bool, *,
             now: datetime) -> None:
        self.failures.append((operation_id, error, retryable))


class FlowWriter(FakeWriter):
    """P40 的假 writer 再加上 `embed`，並依 `node` 回不同的 JSON。"""

    def __init__(self) -> None:
        super().__init__()
        self.embedding: list[float] = list(VECTOR)
        self.embed_calls = 0
        self.replies: dict[str, Any] = {}

    def embed(self, text: str, *, operation_id: str, node: str) -> list[float]:
        self.embed_calls += 1
        self.calls.append({"node": node, "operation_id": operation_id, "user": text})
        return list(self.embedding)

    def generate_json(self, system: str, user: str, schema: dict[str, Any], *,
                      operation_id: str, node: str) -> dict[str, Any]:
        self.calls.append({"system": system, "user": user, "schema": schema, "node": node,
                           "operation_id": operation_id})
        reply = self.replies.get(node, self.reply)
        return json.loads(json.dumps(reply))

    @property
    def generate_calls(self) -> list[dict[str, Any]]:
        return [call for call in self.calls if "schema" in call]


def four_step_draft(feature_id: str = "Prepare") -> dict[str, Any]:
    """符合 `TutorialDraft` schema 的 dict（**不是** pydantic 模型，00A D-02）。"""
    types = ["read", "click_ui", "click_ui", "read"]
    return {
        "title": "Prepare Meeting",
        "problem": "找不到會前摘要入口",
        "prerequisites": ["已登入工作區"],
        "expected_outcome": "看得到會前摘要",
        "steps": [{"number": index + 1, "type": types[index], "text": f"第 {index + 1} 步",
                   "feature_id": feature_id} for index in range(4)],
    }


@pytest.fixture
def local_deps() -> Deps:
    """本機跑完整條序列用的 `Deps`；預設種三筆同群工單（同群共四筆，不到 recurring 門檻）。"""
    repository = FlowRepository()
    anchor = ticket("t_881", embedding=VECTOR)
    repository.seed_ticket(anchor)
    repository.seed_input(anchor)
    for index in range(3):
        repository.seed_ticket(ticket(f"t_90{index}", cluster_id="c1", embedding=VECTOR))
    return Deps(operations=FlowOperations(), now=lambda: NOW, repository=repository,
                writer=FlowWriter(), settings=Settings(table_name="training_kb",
                                                       content_bucket="tkb",
                                                       project_id="demo"))


def start_state() -> dict[str, Any]:
    return {"operation_id": OPERATION_ID, "project_id": "demo", "input_ref": INPUT_REF}


def make_recurring(deps: Deps) -> None:
    """再種一筆同群工單，湊滿 `RECURRING_MIN_TICKETS`（含 anchor 共五筆）。"""
    deps.repository.seed_ticket(ticket("t_904", cluster_id="c1", embedding=VECTOR))


def naming(feature_id: str | None) -> dict[str, Any]:
    return {"gap": "找不到會前摘要入口", "feature_id": feature_id}


# --- Task 1 Step 1：順序與跳過分支 -------------------------------------------


def test_ticket_analysis_task_order_and_names() -> None:
    """Given 七個 Task，When 取 `task_name`，Then 逐字等於 ASL 的 `Parameters.task`。"""
    assert [task_name(task) for task in TICKET_ANALYSIS_TASKS] == TASK_NAMES


def test_non_recurring_run_skips_model_and_version(local_deps: Deps) -> None:
    """Given 同群只有四筆且工單已有向量，When 跑完整條序列，Then 0 次模型、0 個版本。"""
    result = run_ticket_analysis(start_state(), local_deps)

    assert (result["is_recurring"], "version_id" in result) == (False, False)
    assert local_deps.writer.calls == []                    # 連 embed 都沒叫
    assert local_deps.repository.written("VERSION#") == []
    assert local_deps.repository.written("TUTORIAL#") == []
    assert result["cluster_id"] == "c1"
    assert result["ticket_id"] == "t_881"


def test_state_only_carries_the_ten_fields(local_deps: Deps) -> None:
    """Given 跑完一次，Then state 不含工單全文、向量或 `feature_id`（設計 §14.3）。"""
    result = run_ticket_analysis(start_state(), local_deps)

    assert set(result) <= set(TICKET_STATE_FIELDS)
    dumped = json.dumps(result, ensure_ascii=False)
    assert "原始提問" not in dumped and "0.1" not in dumped and "Prepare" not in dumped


def test_missing_embedding_is_filled_once_and_written_back(local_deps: Deps) -> None:
    """Given 工單還沒有向量，When 跑 `EnsureEmbedding`，Then 叫一次 Titan 並寫回表。"""
    bare = ticket("t_881")
    local_deps.repository.seed_ticket(bare)
    local_deps.repository.seed_input(bare)

    run_ticket_analysis(start_state(), local_deps)

    assert local_deps.writer.embed_calls == 1
    stored = local_deps.repository.get_meta(ticket_pk("t_881"), Ticket)
    assert stored is not None and stored.embedding == VECTOR


def test_assign_cluster_writes_the_cluster_id_back(local_deps: Deps) -> None:
    """Given `assign_cluster` 只判斷不寫入，Then Task 自己把 `cluster_id` 寫回 TICKET。"""
    run_ticket_analysis(start_state(), local_deps)

    stored = local_deps.repository.get_meta(ticket_pk("t_881"), Ticket)
    assert stored is not None and stored.cluster_id == "c1"


# --- Task 1 Step 4：三條 recurring 分支 --------------------------------------


def test_recurring_without_feature_keeps_the_gap(local_deps: Deps) -> None:
    """Given 模型回 `feature_id=null`，Then `NO_FEATURE`、有決策紀錄、0 個版本。"""
    make_recurring(local_deps)
    local_deps.writer.replies["name_gap"] = naming(None)

    result = run_ticket_analysis(start_state(), local_deps)

    assert (result["is_recurring"], result["action"]) == (True, "NO_FEATURE")
    assert "version_id" not in result
    assert operation_ref(OPERATION_ID, "ticket-decision") in local_deps.repository.objects
    assert local_deps.repository.written("VERSION#") == []
    assert result["gap_ref"] == operation_ref(OPERATION_ID, "gap-naming")


def test_recurring_with_active_tutorial_keeps(local_deps: Deps) -> None:
    """Given Feature 已有 active 教學，Then `KEEP`、0 個版本、0 篇新教學（F12）。"""
    make_recurring(local_deps)
    local_deps.repository.save_feature("Prepare")
    local_deps.repository.save_tutorial("prepare-meeting", feature_id="Prepare")
    local_deps.writer.replies["name_gap"] = naming("Prepare")

    result = run_ticket_analysis(start_state(), local_deps)

    assert result["action"] == "KEEP"
    assert "version_id" not in result
    assert local_deps.repository.written("VERSION#") == []
    assert local_deps.repository.written("TUTORIAL#") == []
    record = json.loads(local_deps.repository.objects[
        operation_ref(OPERATION_ID, "ticket-decision")])
    assert record["action"] == "KEEP"


def test_recurring_create_builds_v1_and_publishes_it(local_deps: Deps) -> None:
    """Given Feature 沒有 active 教學，Then CREATE 一個 v1 並走完 `PublishVersion`。"""
    make_recurring(local_deps)
    local_deps.repository.save_feature("Prepare")
    local_deps.writer.replies["name_gap"] = naming("Prepare")
    local_deps.writer.replies["create_v1"] = four_step_draft()

    result = run_ticket_analysis(start_state(), local_deps)

    assert result["action"] == "CREATE"
    assert result["version_id"] == "prepare-meeting@v1"
    assert result["published"] is True
    version = local_deps.repository.get_version("prepare-meeting@v1")
    assert version is not None and version.published_at is not None
    tutorial = local_deps.repository.get_meta(tutorial_pk("prepare-meeting"), Tutorial)
    assert tutorial is not None
    assert tutorial.current_version == "prepare-meeting@v1"
    assert tutorial.status == TutorialStatus.ACTIVE
    assert [key for key in local_deps.repository.objects if key.startswith("site/")]


def test_model_is_called_once_per_node_on_the_create_path(local_deps: Deps) -> None:
    """Given CREATE 路徑，Then `name_gap` 與 `create_v1` 各恰好一次（設計 §14.2）。"""
    make_recurring(local_deps)
    local_deps.repository.save_feature("Prepare")
    local_deps.writer.replies["name_gap"] = naming("Prepare")
    local_deps.writer.replies["create_v1"] = four_step_draft()

    run_ticket_analysis(start_state(), local_deps)

    assert [call["node"] for call in local_deps.writer.generate_calls] \
        == ["name_gap", "create_v1"]
    assert local_deps.writer.embed_calls == 0


def test_rerun_with_the_same_operation_id_adds_nothing(local_deps: Deps) -> None:
    """Given 同一串輸入重跑，Then 第二輪走 KEEP：不重呼叫模型、不多一版也不多一篇。

    第一輪建立的教學已經是 active，`decide_ticket_action` 依 F12 回 KEEP，所以第二輪
    在 `DecideAction` 就收斂。`name_gap` 也沿用既有的 `gap-naming.json`（Phase 39 先讀
    物件再決定要不要呼叫模型），所以整輪 0 次模型呼叫。
    """
    make_recurring(local_deps)
    local_deps.repository.save_feature("Prepare")
    local_deps.writer.replies["name_gap"] = naming("Prepare")
    local_deps.writer.replies["create_v1"] = four_step_draft()

    first = run_ticket_analysis(start_state(), local_deps)
    second = run_ticket_analysis(start_state(), local_deps)

    assert (first["action"], second["action"]) == ("CREATE", "KEEP")
    assert first["version_id"] == "prepare-meeting@v1"
    assert "version_id" not in second
    assert [call["node"] for call in local_deps.writer.generate_calls] \
        == ["name_gap", "create_v1"]
    assert len([key for key in local_deps.repository.table
                if key[0].startswith("VERSION#")]) == 1


def test_failure_inside_a_task_is_recorded_and_reraised(local_deps: Deps) -> None:
    """Given 模型回不存在的 Feature，Then `NameGap` 記一次失敗再把原例外往外丟。"""
    make_recurring(local_deps)
    local_deps.writer.replies["name_gap"] = naming("Nope")

    with pytest.raises(PermanentError):
        run_ticket_analysis(start_state(), local_deps)

    assert [row[0] for row in local_deps.operations.failures] == [OPERATION_ID]
    assert local_deps.operations.failures[0][2] is False      # 不是暫時錯誤


# --- Task 2 Step 3：兩層 handler 分派 ----------------------------------------


@pytest.fixture
def wired(local_deps: Deps, monkeypatch: pytest.MonkeyPatch) -> Deps:
    """把 `ticket_analysis_handler` 的模組層相依換成本機替身，不連 AWS。"""
    monkeypatch.setattr(ticket_pipeline, "_DEPS", local_deps)
    monkeypatch.delenv("TKB_FAULT_TASK", raising=False)
    monkeypatch.delenv("TKB_ENV", raising=False)
    return local_deps


def event(task: str, state: dict[str, Any] | None = None,
          pipeline: str = "ticket-analysis") -> dict[str, Any]:
    return {"pipeline": pipeline, "task": task,
            "state": start_state() if state is None else state}


def test_handler_runs_exactly_one_task(wired: Deps) -> None:
    """Given ASL 一次只給一個 task，Then handler 只跑那一個，不會跑成整條序列。"""
    result = pipeline_task_handler(event("ensure_embedding"), None)

    assert result["ticket_id"] == "t_881"
    assert "cluster_id" not in result and "is_recurring" not in result


def test_handler_passes_the_state_through_for_the_next_task(wired: Deps) -> None:
    """Given 上一個 Task 的輸出，Then 下一個 Task 接得起來（雲端就是這樣串的）。"""
    first = pipeline_task_handler(event("ensure_embedding"), None)
    second = pipeline_task_handler(event("assign_cluster", first), None)

    assert second["cluster_id"] == "c1"


def test_unknown_pipeline_is_a_permanent_error(wired: Deps) -> None:
    with pytest.raises(PermanentError, match="nope"):
        pipeline_task_handler(event("ensure_embedding", pipeline="nope"), None)


def test_module_without_its_handler_is_a_permanent_error(wired: Deps) -> None:
    """Given controller 預建的空殼（模組 import 得到、handler 屬性還沒有），Then 明確失敗。

    這條測試會在 P48 落地 `feedback_review_handler` 之後自然失效，那時由 P48 改掉；
    本 Phase 不預先放寬（不然 Lambda 會丟 `AttributeError`，`errorType` 就看不出原因）。
    """
    with pytest.raises(PermanentError, match="feedback_review_handler"):
        pipeline_task_handler(event("list_targets", pipeline="feedback-review"), None)


def test_unknown_task_name_is_a_permanent_error(wired: Deps) -> None:
    with pytest.raises(PermanentError, match="nope"):
        pipeline_task_handler(event("nope"), None)


# --- Task 2 Step 3：TKB_FAULT_TASK 故障注入 ----------------------------------


def test_fault_task_raises_transient_error_itself(wired: Deps,
                                                  monkeypatch: pytest.MonkeyPatch) -> None:
    """Given `TKB_FAULT_TASK` 命中，Then 丟的類別名逐字是 `TransientError`。

    ASL 的 `ErrorEquals: ["TransientError"]` 比對**類別名字串**，不認繼承，所以注入
    一定要丟 `TransientError` 本身；丟子類（例如 P59 的 `InjectedFault`）在雲端不會
    命中第一條 retrier，證出來的是假陰性。
    """
    monkeypatch.setenv("TKB_FAULT_TASK", "ticket-analysis:name_gap")

    with pytest.raises(TransientError) as caught:
        pipeline_task_handler(event("name_gap"), None)

    assert type(caught.value).__name__ == "TransientError"


def test_fault_task_only_hits_the_named_task(wired: Deps,
                                             monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TKB_FAULT_TASK", "ticket-analysis:name_gap")

    assert pipeline_task_handler(event("ensure_embedding"), None)["ticket_id"] == "t_881"


def test_fault_task_never_fires_in_prod(wired: Deps,
                                        monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TKB_FAULT_TASK", "ticket-analysis:ensure_embedding")
    monkeypatch.setenv("TKB_ENV", "prod")

    assert pipeline_task_handler(event("ensure_embedding"), None)["ticket_id"] == "t_881"


def test_fault_task_is_read_on_every_invoke(wired: Deps,
                                            monkeypatch: pytest.MonkeyPatch) -> None:
    """Given 環境變數在兩次 invoke 之間才設上去，Then 第二次就生效（不做模組層快取）。"""
    pipeline_task_handler(event("ensure_embedding"), None)
    monkeypatch.setenv("TKB_FAULT_TASK", "ticket-analysis:ensure_embedding")

    with pytest.raises(TransientError):
        pipeline_task_handler(event("ensure_embedding"), None)


def test_build_deps_wires_the_four_dependencies() -> None:
    """Given 一份 `Settings`，Then `build_deps` 組出四個相依（形狀照 `_build_wiring`）。"""
    deps = build_deps(Settings(table_name="training_kb", content_bucket="tkb",
                               aws_region="us-east-1"))

    assert deps.need_settings().table_name == "training_kb"
    assert deps.need_repository().table_name == "training_kb"
    assert deps.need_writer() is not None
    assert deps.operations is not None
