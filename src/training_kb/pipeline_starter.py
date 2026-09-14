"""啟動 Step Functions 執行的窄介面（Phase 32）。

`PipelineStarter` 是接受路徑唯一認識的啟動方式；正式實作是 `BotoPipelineStarter`，
測試用假的 starter。冪等只由**執行名稱**達成：同名、同 input、仍在執行時 StartExecution
是冪等的，所以名稱一律由 `execution_name(operation_id)` 決定，**不得追加時間戳或隨機字尾**。

同名執行**已經結束**時 Step Functions 一樣丟 `ExecutionAlreadyExists`，那不等於成功
（設計 §14.2）：要嘛 operation ledger 有 `status == "done"` 的原結果可以沿用，要嘛
就是 `CoordinationError`，交人工確認。

`feedback-review` 不經這個模組：它由 EventBridge Scheduler 觸發，input 形狀也不同（00A D-61）。
"""

import json
from typing import Any, Protocol

from botocore.exceptions import (
    ClientError,
    ConnectTimeoutError,
    EndpointConnectionError,
    ReadTimeoutError,
)

from training_kb.errors import CoordinationError, TransientError
from training_kb.operations import OperationCoordinator
from training_kb.pipelines.common import JSONValue, PipelineName

# --- 1. 名稱與 ARN -----------------------------------------------------------

STATE_MACHINE_NAMES: dict[PipelineName, str] = {
    "ticket-analysis": "training-kb-ticket-analysis",
    "release-update": "training-kb-release-update",
    "feedback-review": "training-kb-feedback-review",
}
"""00A §3.5 固定的三個 state machine 名稱；部署時由它加上帳號與 Region 組出 ARN。"""

STATE_MACHINE_SEGMENT = ":stateMachine:"
EXECUTION_SEGMENT = ":execution:"

TRANSIENT_START_CODES = frozenset({
    "ThrottlingException", "ThrottledException", "TooManyRequestsException",
    "ServiceUnavailable", "ServiceUnavailableException",
    "InternalServerError", "InternalError", "InternalFailure",
    "RequestTimeout", "RequestTimeoutException",
})
"""Step Functions 這一側「重送有機會成功」的錯誤碼白名單。

只翻**已知**的碼，其餘 `ClientError` 原樣往外冒（與 `repository.py` 同一條慣例）：
把不認得的錯誤一律當暫時性，會讓 `ValidationException`、`StateMachineDoesNotExist`
這種確定不會成功的失敗被無限重送。
"""

TIMEOUT_ERRORS = (ConnectTimeoutError, ReadTimeoutError, EndpointConnectionError)
"""botocore 的連線／讀取逾時：沒有 HTTP 回應，所以沒有錯誤碼可以判斷，一律暫時性。"""

SERVER_ERROR_STATUS = 500


def _transient(error: ClientError) -> TransientError | None:
    """已知的暫時性錯誤碼或 5xx → `TransientError`；其餘回 `None`（呼叫端原樣往外丟）。

    訊息只留錯誤碼與 HTTP 狀態，**不回填 input**：ASL input 雖然只有三個鍵，
    錯誤訊息還是會進 log，保持「log 不出現事件內容」這條界線（00A §3.8）。
    """
    response = error.response
    code = str(response.get("Error", {}).get("Code", ""))
    status = response.get("ResponseMetadata", {}).get("HTTPStatusCode")
    server_error = isinstance(status, int) and status >= SERVER_ERROR_STATUS
    if code in TRANSIENT_START_CODES or server_error:
        return TransientError(f"Step Functions 暫時失敗：{code or status}")
    return None


def state_machine_arns(*, region: str, account_id: str) -> dict[PipelineName, str]:
    """把 `STATE_MACHINE_NAMES` 組成可以直接呼叫 StartExecution 的 ARN 表。

    名稱是契約（00A §3.5），帳號與 Region 是部署事實，所以兩者在這裡才會合併：
    程式裡不寫死帳號，測試直接注入假 ARN。
    """
    return {
        pipeline: f"arn:aws:states:{region}:{account_id}{STATE_MACHINE_SEGMENT}{name}"
        for pipeline, name in STATE_MACHINE_NAMES.items()
    }


# --- 2. 介面 -----------------------------------------------------------------


class PipelineStarter(Protocol):
    """啟動一條 pipeline，回 execution ARN。

    `input` 只放 `operation_id`／`project_id`／`input_ref` 三個鍵（00A §7）：完整事件、
    教學全文與向量一律不進 execution history，需要時由 Task 自己用 `input_ref` 讀。
    """

    def start(self, pipeline: PipelineName, execution_name: str,
              input: dict[str, JSONValue]) -> str: ...


# --- 3. boto3 adapter --------------------------------------------------------


class BotoPipelineStarter:
    """`PipelineStarter` 的正式實作。

    公開簽名寫 `client: object`（與 `Repository` 同一條慣例，00A §6.3），內部存成 `Any`：
    boto3 的 client 沒有穩定的靜態型別。`arns` 由 `state_machine_arns(...)` 產生，
    測試直接注入假 ARN。`operations` 是 ledger——`ExecutionAlreadyExists` 之後**唯一**
    可以拿來判斷「這次到底成功了沒」的證據來源。
    """

    def __init__(self, client: object, arns: dict[PipelineName, str],
                 operations: OperationCoordinator) -> None:
        self._client: Any = client
        self._arns = arns
        self._operations = operations

    def start(self, pipeline: PipelineName, execution_name: str,
              input: dict[str, JSONValue]) -> str:
        """啟動一次執行並回 ARN；同名執行已存在時交給 `_reuse` 判斷。

        `sort_keys=True` 讓同一份 input 每次序列化成同一串字元——StartExecution 的冪等
        條件是「同名**且同 input**」，鍵順序飄動會讓本來該冪等的重送變成錯誤。
        這裡**不自己重試**：重試由 ASL 的 `Retry` 與來源重送管，只有一層（00A §3.7）。
        """
        try:
            response = self._client.start_execution(
                stateMachineArn=self._arns[pipeline], name=execution_name,
                input=json.dumps(input, sort_keys=True),
            )
        except self._client.exceptions.ExecutionAlreadyExists:
            # 一定要排在 `ClientError` 之前：boto3 的這個例外就是 `ClientError` 的子類。
            return self._reuse(pipeline, execution_name, str(input["operation_id"]))
        except TIMEOUT_ERRORS as error:
            raise TransientError(f"Step Functions 連線逾時：{type(error).__name__}") from error
        except ClientError as error:
            transient = _transient(error)
            if transient is not None:
                raise transient from error
            raise                      # 不認得的碼原樣往外冒，不猜它可不可以重送
        return str(response["executionArn"])

    def _reuse(self, pipeline: PipelineName, execution_name: str, operation_id: str) -> str:
        """同名執行已存在：**仍在執行**才沿用，已結束就要有 ledger 的原結果。

        `ExecutionAlreadyExists` 一律當成功會讓「已經失敗的那次」被報成成功；換個名字重跑
        則會讓同一個事件跑出第二條版本鏈。兩個都不行，所以沒有證據時丟 `CoordinationError`
        交人工確認（設計 §14.2）。

        ledger 沒有 `execution_arn` 時由 state machine ARN 推導執行 ARN，這是**本計畫選擇**，
        必須由 Phase 41 的雲端驗收實證後才可信賴。
        """
        record = self._operations.load(operation_id)
        arn = record.execution_arn if record else None
        if arn is None:
            arn = f"{self._arns[pipeline].replace(STATE_MACHINE_SEGMENT, EXECUTION_SEGMENT)}" \
                  f":{execution_name}"
        status = self._describe(arn)["status"]
        if status == "RUNNING":
            if record is not None and record.execution_arn is None:
                self._operations.record_execution(operation_id, arn)
            return arn
        if record is not None and record.status == "done":
            return arn
        raise CoordinationError(f"{operation_id} 的同名執行已結束但 ledger 沒有原結果，需人工確認")

    def _describe(self, execution_arn: str) -> dict[str, Any]:
        """`describe_execution` 與 `start_execution` 共用同一套錯誤分類。

        這一步被節流時如果原樣冒出 `ClientError`，`ingress._start_once` 會把一次純粹的
        暫時性失敗記成 `retryable=False`——判斷「這次到底成功了沒」的那次查詢，
        分類標準要跟啟動那一次一樣。
        """
        try:
            described: dict[str, Any] = self._client.describe_execution(executionArn=execution_arn)
        except TIMEOUT_ERRORS as error:
            raise TransientError(f"Step Functions 連線逾時：{type(error).__name__}") from error
        except ClientError as error:
            transient = _transient(error)
            if transient is not None:
                raise transient from error
            raise                      # 不認得的碼原樣往外冒，不猜它可不可以重送
        return described
