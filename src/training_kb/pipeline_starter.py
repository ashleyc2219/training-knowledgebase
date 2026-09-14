"""啟動 Step Functions 執行的窄介面（Phase 32）。

`PipelineStarter` 是接受路徑唯一認識的啟動方式；正式實作是 `BotoPipelineStarter`，
測試用假的 starter。冪等只由**執行名稱**達成：同名、同 input、仍在執行時 StartExecution
是冪等的，所以名稱一律由 `execution_name(operation_id)` 決定，**不得追加時間戳或隨機字尾**。

同名執行**已經結束**時 Step Functions 一樣丟 `ExecutionAlreadyExists`，那不等於成功
（設計 §14.2）：要嘛 operation ledger 有 `status == "done"` 的原結果可以沿用，要嘛
就是 `CoordinationError`，交人工確認。

`feedback-review` 不經這個模組：它由 EventBridge Scheduler 觸發，input 形狀也不同（00A D-61）。
"""

from typing import Protocol

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
