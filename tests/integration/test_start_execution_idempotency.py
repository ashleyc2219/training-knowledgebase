"""`ExecutionAlreadyExists` 的三個分支與程序重啟（Phase 32 Task 3）。

Step Functions 只對「同名、同 input、仍在執行」冪等；同名執行**已經結束**時一樣丟
`ExecutionAlreadyExists`，那不是成功（設計 §14.2）。所以這裡的斷言是：

- RUNNING → 沿用原 ARN，必要時補寫 `record_execution`。
- 已結束且 ledger `status == "done"` → 沿用原 ARN。
- 已結束但 ledger 沒有原結果 → `CoordinationError`，**不回成功、不換名重跑**。

ledger 用 moto 表上的**真正** `OperationCoordinator`；Step Functions 用 `MagicMock`
（真實接線是 Phase 41／52 的雲端驗收，本批不跑真 AWS）。moto 與 mock 的綠燈只證明程式
邏輯，**不是 O2 gate 證據**：lease 不等於接受順序、TTL 不是準時解鎖。
"""

from collections.abc import Iterator
from datetime import UTC, datetime
from time import monotonic
from typing import Any
from unittest.mock import MagicMock

import pytest
from botocore.exceptions import ClientError, ConnectTimeoutError

from training_kb import ingress
from training_kb.config import Settings, load_settings
from training_kb.errors import CoordinationError, TransientError
from training_kb.ingress import Wiring, accept_ticket, execution_name, operation_id_for
from training_kb.keys import operation_ref
from training_kb.operations import AcceptOperation, OperationCoordinator, OperationStatus
from training_kb.pipeline_starter import (
    STATE_MACHINE_NAMES,
    BotoPipelineStarter,
    state_machine_arns,
)
from training_kb.pipelines.common import JSONValue, PipelineName
from training_kb.repository import Repository

NOW = datetime(2026, 9, 13, 12, 0, tzinfo=UTC)
OP = operation_id_for("ticket", "t_881")
INPUT_REF = operation_ref(OP, "input")
PIPELINE: PipelineName = "ticket-analysis"
REGION = "ap-northeast-1"
ACCOUNT = "111122223333"
ARNS = state_machine_arns(region=REGION, account_id=ACCOUNT)
ARN = f"arn:aws:states:{REGION}:{ACCOUNT}:execution:{STATE_MACHINE_NAMES[PIPELINE]}:{OP}"
LIMITED_INPUT: dict[str, JSONValue] = {
    "operation_id": OP, "project_id": "demo", "input_ref": INPUT_REF,
}
TICKET = ingress.validate_ticket({
    "id": "t_881", "source": "github_issue", "text": "找不到「開始會議」按鈕在哪裡",
    "author": "u_gh-90210", "ts": "2026-09-01T08:12:30Z", "project_id": "demo",
})


def client_error(code: str, *, status: int = 400) -> ClientError:
    """boto3 的錯誤形狀：`Error.Code` 與 `ResponseMetadata.HTTPStatusCode`。"""
    return ClientError(
        {"Error": {"Code": code, "Message": "x"}, "ResponseMetadata": {"HTTPStatusCode": status}},
        "StartExecution",
    )


class ExecutionAlreadyExists(Exception):
    """替身：boto3 的 `client.exceptions.ExecutionAlreadyExists` 是動態產生的類別。"""


class Harness:
    """moto 表上的真 ledger ＋ 一個假的 Step Functions client。"""

    def __init__(self, repository: Repository) -> None:
        self.repository = repository
        self.operations = OperationCoordinator(repository)
        self.sfn = self.new_client()
        self.starter = BotoPipelineStarter(self.sfn, ARNS, self.operations)

    @staticmethod
    def new_client() -> Any:
        client = MagicMock()
        client.exceptions.ExecutionAlreadyExists = ExecutionAlreadyExists
        client.start_execution.return_value = {"executionArn": ARN}
        return client

    @property
    def already_exists(self) -> ExecutionAlreadyExists:
        return ExecutionAlreadyExists("Execution Already Exists")

    def seed(self, *, status: OperationStatus = "accepted",
             execution_arn: str | None = ARN) -> None:
        """把 ledger 擺成某一個狀態；欄位一律走 Phase 10 的公開方法。"""
        self.operations.accept(AcceptOperation(
            operation_id=OP, kind="ticket", canonical_id="t_881",
            project_id="demo", now=NOW))
        self.operations.record_normalized(OP, INPUT_REF)
        if execution_arn is not None:
            self.operations.record_execution(OP, execution_arn)
        if status == "done":
            self.operations.complete(OP, now=NOW)
        elif status == "failed":
            self.operations.fail(OP, "boom", True, now=NOW)

    def restarted(self) -> BotoPipelineStarter:
        """模擬程序重啟：全新的 client、全新的 coordinator，只剩持久 ledger。"""
        self.sfn = self.new_client()
        return BotoPipelineStarter(self.sfn, ARNS, OperationCoordinator(self.repository))


@pytest.fixture(autouse=True)
def never_touch_real_aws(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """清掉模組層的 `Wiring` 快取，並讓真正的建構器當場失敗（同 unit 檔的守門員）。"""
    ingress._reset_wiring()
    monkeypatch.setattr(ingress, "_build_wiring", _forbidden_wiring)
    yield
    ingress._reset_wiring()


def _forbidden_wiring(settings: Settings) -> Wiring:
    raise AssertionError(f"測試忘了注入 _wiring，差點連上真的 AWS：{settings.table_name}")


@pytest.fixture
def harness(repository: Repository) -> Harness:
    return Harness(repository)


def test_a_fresh_start_sends_only_the_three_key_input(harness: Harness) -> None:
    assert harness.starter.start(PIPELINE, execution_name(OP), LIMITED_INPUT) == ARN
    sent = harness.sfn.start_execution.call_args.kwargs
    assert sent["stateMachineArn"] == ARNS[PIPELINE]
    assert sent["name"] == OP
    assert sent["input"] == (
        '{"input_ref": "operations/op-ticket-t_881/input.json", '
        '"operation_id": "op-ticket-t_881", "project_id": "demo"}'
    )


def test_closed_already_exists_requires_ledger_result(harness: Harness) -> None:
    harness.sfn.start_execution.side_effect = harness.already_exists
    harness.sfn.describe_execution.return_value = {"status": "FAILED"}
    harness.seed(status="started")
    with pytest.raises(CoordinationError, match="原結果"):
        harness.starter.start(PIPELINE, execution_name(OP), LIMITED_INPUT)
    assert harness.sfn.start_execution.call_count == 1


def test_running_already_exists_reuses_the_same_arn(harness: Harness) -> None:
    harness.sfn.start_execution.side_effect = harness.already_exists
    harness.sfn.describe_execution.return_value = {"status": "RUNNING"}
    harness.seed(status="started")
    assert harness.starter.start(PIPELINE, execution_name(OP), LIMITED_INPUT) == ARN
    assert harness.sfn.start_execution.call_count == 1


def test_a_closed_execution_with_a_done_ledger_reuses_the_original_arn(
    harness: Harness,
) -> None:
    """已結束但 ledger 有 `status == "done"` 的原結果：沿用原 ARN，不重跑。"""
    harness.sfn.start_execution.side_effect = harness.already_exists
    harness.sfn.describe_execution.return_value = {"status": "SUCCEEDED"}
    harness.seed(status="done")
    assert harness.starter.start(PIPELINE, execution_name(OP), LIMITED_INPUT) == ARN


def test_a_running_execution_backfills_the_missing_arn(harness: Harness) -> None:
    """ledger 沒有 `execution_arn` 時由 state machine ARN 推導，RUNNING 就補寫回去。"""
    harness.sfn.start_execution.side_effect = harness.already_exists
    harness.sfn.describe_execution.return_value = {"status": "RUNNING"}
    harness.seed(status="accepted", execution_arn=None)
    assert harness.starter.start(PIPELINE, execution_name(OP), LIMITED_INPUT) == ARN
    assert harness.sfn.describe_execution.call_args.kwargs == {"executionArn": ARN}
    record = harness.operations.load(OP)
    assert record is not None
    assert record.execution_arn == ARN


def test_a_derived_closed_execution_without_a_result_is_still_ambiguous(
    harness: Harness,
) -> None:
    """ledger 沒有 ARN、推導出的執行已結束且不是 `done`：仍然是需要人工確認的不一致。"""
    harness.sfn.start_execution.side_effect = harness.already_exists
    harness.sfn.describe_execution.return_value = {"status": "TIMED_OUT"}
    harness.seed(status="failed", execution_arn=None)
    with pytest.raises(CoordinationError, match="原結果"):
        harness.starter.start(PIPELINE, execution_name(OP), LIMITED_INPUT)


def test_a_restarted_process_reuses_the_same_name_and_arn(harness: Harness) -> None:
    """換一個 process：只憑持久 ledger 就回同一個 `operation_id`、`input_ref` 與 ARN。"""
    harness.seed(status="started")
    starter = harness.restarted()
    harness.sfn.start_execution.side_effect = harness.already_exists
    harness.sfn.describe_execution.return_value = {"status": "RUNNING"}
    assert starter.start(PIPELINE, execution_name(OP), LIMITED_INPUT) == ARN
    assert harness.sfn.start_execution.call_args.kwargs["name"] == execution_name(OP)
    record = OperationCoordinator(harness.repository).load(OP)
    assert record is not None
    assert (record.operation_id, record.input_ref) == (OP, INPUT_REF)


@pytest.mark.parametrize("execution_status", ["RUNNING", "SUCCEEDED", "FAILED", "ABORTED"])
def test_the_execution_name_never_changes(harness: Harness, execution_status: str) -> None:
    """任何分支都不得追加 timestamp、random suffix 或新的 operation ID。"""
    harness.sfn.start_execution.side_effect = harness.already_exists
    harness.sfn.describe_execution.return_value = {"status": execution_status}
    harness.seed(status="done")
    harness.starter.start(PIPELINE, execution_name(OP), LIMITED_INPUT)
    assert harness.sfn.start_execution.call_count == 1
    assert harness.sfn.start_execution.call_args.kwargs["name"] == OP


def test_state_machine_arns_use_the_three_fixed_names() -> None:
    assert ARNS == {
        "ticket-analysis": f"arn:aws:states:{REGION}:{ACCOUNT}"
                           ":stateMachine:training-kb-ticket-analysis",
        "release-update": f"arn:aws:states:{REGION}:{ACCOUNT}"
                          ":stateMachine:training-kb-release-update",
        "feedback-review": f"arn:aws:states:{REGION}:{ACCOUNT}"
                           ":stateMachine:training-kb-feedback-review",
    }


# --- 錯誤分類：只有已知的暫時性碼才可以重送 -----------------------------------


@pytest.mark.parametrize("failure", [
    client_error("ThrottlingException"),
    client_error("ServiceUnavailableException", status=503),
    client_error("InternalServerError", status=500),
    client_error("RequestTimeout"),
    client_error("SomethingNew", status=500),          # 不認得的碼，但 5xx
    ConnectTimeoutError(endpoint_url="https://states.example"),
])
def test_known_transient_start_failures_become_transient_errors(
    harness: Harness, failure: Exception,
) -> None:
    harness.sfn.start_execution.side_effect = failure
    with pytest.raises(TransientError):
        harness.starter.start(PIPELINE, execution_name(OP), LIMITED_INPUT)


@pytest.mark.parametrize("code", ["ValidationException", "StateMachineDoesNotExist",
                                  "AccessDeniedException"])
def test_unknown_client_errors_are_raised_unchanged(harness: Harness, code: str) -> None:
    """不認得的碼原樣往外冒，不猜它可不可以重送（與 `repository.py` 同一條慣例）。"""
    harness.sfn.start_execution.side_effect = client_error(code)
    with pytest.raises(ClientError) as raised:
        harness.starter.start(PIPELINE, execution_name(OP), LIMITED_INPUT)
    assert raised.value.response["Error"]["Code"] == code


def test_a_throttled_describe_is_also_transient(harness: Harness) -> None:
    """判斷「這次到底成功了沒」的那次查詢，分類標準要跟啟動那一次一樣。"""
    harness.sfn.start_execution.side_effect = harness.already_exists
    harness.sfn.describe_execution.side_effect = client_error("ThrottlingException")
    harness.seed(status="started")
    with pytest.raises(TransientError):
        harness.starter.start(PIPELINE, execution_name(OP), LIMITED_INPUT)


def test_a_throttled_start_lands_in_the_ledger_as_retryable(
    harness: Harness, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """正式 adapter ＋真 ledger：節流的啟動要記成 `retryable=True`（§9 驗收表）。"""
    harness.sfn.start_execution.side_effect = client_error("ThrottlingException")
    monkeypatch.setattr(ingress, "_wiring", lambda: Wiring(
        operations=harness.operations, starter=harness.starter,
        repository=harness.repository, settings=load_settings({})))
    with pytest.raises(TransientError):
        accept_ticket(TICKET, deadline=monotonic() + 8.0)
    record = harness.operations.load(OP)
    assert record is not None
    assert (record.status, record.retryable) == ("failed", True)
    assert record.input_ref == INPUT_REF          # 輸入留著，重送沿用同一個 execution name


def test_a_permanent_start_failure_is_not_marked_retryable(
    harness: Harness, monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness.sfn.start_execution.side_effect = client_error("ValidationException")
    monkeypatch.setattr(ingress, "_wiring", lambda: Wiring(
        operations=harness.operations, starter=harness.starter,
        repository=harness.repository, settings=load_settings({})))
    with pytest.raises(ClientError):
        accept_ticket(TICKET, deadline=monotonic() + 8.0)
    record = harness.operations.load(OP)
    assert record is not None
    assert (record.status, record.retryable) == ("failed", False)
