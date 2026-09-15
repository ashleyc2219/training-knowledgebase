"""修正波（final review A#4／B#3／C 的 soundness caveats）：雲端逐 Task 失敗要進 ledger。

雲端不走 `run_sequence`（那條是本機序列），每個 Task 各 invoke 一次 Lambda 由
`pipeline_task_handler` 分派，原本那一層一個 `except` 都沒有，所以
`OperationCoordinator.fail(...)` 從來沒有在雲端被呼叫過：`OPS#` 會永遠停在 `accepted`。

本檔守四件事（三條 pipeline 各一份）：

```text
Task 丟例外 -> ledger 記一筆 failed（retryable == isinstance(error, TransientError)）
            -> **原例外原樣往外丟**（errorType 不可被改寫，ASL 的 Retry 比對類別名字串）
重試後成功  -> 還是可以 complete（`operations._change` 沒有轉移守門）
沒有 operation_id／相依還沒組起來 -> 不記，也不改寫例外
```
"""

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

import pytest

from training_kb.errors import PermanentError, TransientError
from training_kb.operations import AcceptOperation, OperationCoordinator
from training_kb.pipelines import common
from training_kb.pipelines import feedback as feedback_pipeline
from training_kb.pipelines import release as release_pipeline
from training_kb.pipelines import ticket as ticket_pipeline
from training_kb.pipelines.common import Deps, JSONValue, pipeline_task_handler

NOW = datetime(2026, 9, 15, 3, 0, 0, tzinfo=UTC)
OPERATION_ID = "op-ticket-t_fixwave"

PIPELINES: tuple[tuple[str, Any], ...] = (
    ("ticket-analysis", ticket_pipeline),
    ("release-update", release_pipeline),
    ("feedback-review", feedback_pipeline),
)
"""三條 pipeline 與它們的模組；每個測試都對三條各跑一次。"""


class FakeOperations:
    """只記 `fail`／`complete` 的替身；不碰 DynamoDB。"""

    def __init__(self) -> None:
        self.failures: list[tuple[str, str, bool]] = []
        self.completed: list[str] = []

    def fail(self, operation_id: str, error: str, retryable: bool, *,
             now: datetime) -> None:
        self.failures.append((operation_id, error, retryable))

    def complete(self, operation_id: str, *, now: datetime) -> None:
        self.completed.append(operation_id)


class ExplodingOperations(FakeOperations):
    """連 ledger 都寫不進去的極端狀況：`fail` 自己丟例外。"""

    def fail(self, operation_id: str, error: str, retryable: bool, *,
             now: datetime) -> None:
        raise RuntimeError("ledger 寫不進去")


@pytest.fixture(autouse=True)
def clean_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    """每個測試自己決定快取內容；也把兩個執行期開關清掉。"""
    monkeypatch.setattr(common, "_DEPS_BY_PIPELINE", {})
    monkeypatch.delenv("TKB_FAULT_TASK", raising=False)
    monkeypatch.delenv("TKB_ENV", raising=False)


def wire(pipeline: str, operations: FakeOperations) -> Deps:
    deps = Deps(operations=operations, now=lambda: NOW)  # type: ignore[arg-type]
    common._DEPS_BY_PIPELINE[pipeline] = deps
    return deps


def boom(error: Exception) -> Any:
    def task(state: dict[str, JSONValue], deps: Deps) -> dict[str, JSONValue]:
        raise error
    return task


def install(monkeypatch: pytest.MonkeyPatch, module: Any, task: Any,
            name: str = "fixwave_boom") -> None:
    monkeypatch.setitem(module._TASK_BY_NAME, name, task)


def event(pipeline: str, *, task: str = "fixwave_boom",
          state: Mapping[str, Any] | None = None) -> dict[str, Any]:
    return {"pipeline": pipeline, "task": task,
            "state": {"operation_id": OPERATION_ID} if state is None else dict(state)}


@pytest.mark.parametrize(("pipeline", "module"), PIPELINES)
def test_transient_failure_is_recorded_as_retryable_and_reraised(
        pipeline: str, module: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """Given 一個 Task 丟 `TransientError`，Then ledger 記 retryable，例外原樣往外丟。"""
    operations = FakeOperations()
    wire(pipeline, operations)
    install(monkeypatch, module, boom(TransientError("上游超時")))

    with pytest.raises(TransientError) as caught:
        pipeline_task_handler(event(pipeline), None)

    assert type(caught.value).__name__ == "TransientError"
    assert operations.failures == [(OPERATION_ID, "上游超時", True)]


@pytest.mark.parametrize(("pipeline", "module"), PIPELINES)
def test_permanent_failure_is_recorded_as_not_retryable(
        pipeline: str, module: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    operations = FakeOperations()
    wire(pipeline, operations)
    install(monkeypatch, module, boom(PermanentError("內容不合規")))

    with pytest.raises(PermanentError):
        pipeline_task_handler(event(pipeline), None)

    assert operations.failures == [(OPERATION_ID, "內容不合規", False)]


@pytest.mark.parametrize(("pipeline", "module"), PIPELINES)
def test_injected_task_fault_is_recorded_too(
        pipeline: str, module: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """`TKB_FAULT_TASK` 命中時也要留紀錄：注入的失敗與真實失敗在 ledger 上同形狀。"""
    operations = FakeOperations()
    wire(pipeline, operations)
    install(monkeypatch, module, boom(PermanentError("不該跑到這裡")))
    monkeypatch.setenv("TKB_FAULT_TASK", f"{pipeline}:fixwave_boom")

    with pytest.raises(TransientError):
        pipeline_task_handler(event(pipeline), None)

    assert [row[0] for row in operations.failures] == [OPERATION_ID]
    assert operations.failures[0][2] is True


@pytest.mark.parametrize(("pipeline", "module"), PIPELINES)
def test_missing_operation_id_records_nothing_and_keeps_the_error(
        pipeline: str, module: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """Given state 沒有 `operation_id`，Then 不記 ledger，例外仍然原樣往外丟。"""
    operations = FakeOperations()
    wire(pipeline, operations)
    install(monkeypatch, module, boom(TransientError("上游超時")))

    with pytest.raises(TransientError):
        pipeline_task_handler(event(pipeline, state={}), None)

    assert operations.failures == []


@pytest.mark.parametrize(("pipeline", "module"), PIPELINES)
def test_ledger_write_failure_never_rewrites_the_error_type(
        pipeline: str, module: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """Given 連 `fail` 都失敗，Then 往外丟的仍是原例外（ASL 比對的是類別名字串）。"""
    wire(pipeline, ExplodingOperations())
    install(monkeypatch, module, boom(TransientError("上游超時")))

    with pytest.raises(TransientError) as caught:
        pipeline_task_handler(event(pipeline), None)

    assert type(caught.value).__name__ == "TransientError"


@pytest.mark.parametrize(("pipeline", "module"), PIPELINES)
def test_build_deps_failure_is_never_masked(
        pipeline: str, module: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """Given `build_deps` 自己失敗，Then 往外丟的是**它的**錯誤，不是記帳時的第二個錯誤。

    組不起相依就代表這個執行環境根本沒有 coordinator（final review C 的 soundness
    caveat）。分派層不會為了記帳再組一次，所以 `_DEPS_BY_PIPELINE` 仍然是空的，
    `_record_task_failure` 直接放棄。
    """
    install(monkeypatch, module, boom(PermanentError("不該跑到這裡")))
    monkeypatch.delenv("TKB_AWS_REGION", raising=False)

    with pytest.raises(PermanentError, match="TKB_AWS_REGION"):
        pipeline_task_handler(event(pipeline), None)

    assert common._DEPS_BY_PIPELINE == {}


def test_a_retry_that_succeeds_can_still_complete_after_a_recorded_failure() -> None:
    """Given ledger 已經記過 `failed`，Then 重試成功時仍然 `complete` 得了。

    ASL 的 Retry 會讓同一個 Task 重跑，每一次失敗各記一筆；`operations._change` 沒有
    合法轉移守門，所以最後一次成功照樣把狀態寫成 `done`。
    """
    repository = _MemoryRepository()
    coordinator = OperationCoordinator(repository)
    coordinator.accept(AcceptOperation(operation_id=OPERATION_ID, kind="ticket",
                                       project_id="demo", canonical_id="t_fixwave", now=NOW))

    coordinator.fail(OPERATION_ID, "上游超時", True, now=NOW)
    first = coordinator.load(OPERATION_ID)
    coordinator.complete(OPERATION_ID, now=NOW)
    second = coordinator.load(OPERATION_ID)

    assert first is not None and first.status == "failed"
    assert second is not None and second.status == "done"


class _MemoryRepository:
    """`OperationCoordinator` 需要的四個方法；與 `test_operation_ordering.py` 同一個形狀。"""

    def __init__(self) -> None:
        self.items: dict[str, dict[str, Any]] = {}

    def put_meta_item(self, pk: str, attributes: Mapping[str, Any], *,
                      create_only: bool) -> bool:
        if create_only and pk in self.items:
            return False
        self.items[pk] = {**attributes, "_revision": 1}
        return True

    def get_meta_item(self, pk: str) -> dict[str, Any] | None:
        item = self.items.get(pk)
        return dict(item) if item is not None else None

    def update_meta(self, pk: str, changes: Mapping[str, Any], *,
                    expected_revision: int) -> int:
        item = self.items[pk]
        item.update(changes)
        item["_revision"] = expected_revision + 1
        return expected_revision + 1

    def revision_of(self, pk: str) -> int:
        return int(self.items[pk]["_revision"])
