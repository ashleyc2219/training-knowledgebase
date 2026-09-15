"""Phase 52 Task 2／3：`release-update` 的 ASL 失敗語意與本機三分支序列（不連 AWS）。

`Retry`／`Catch`／`TimeoutSeconds`／`Fail` state 名稱**一律從 `training_kb.pipelines.asl`
import** 再比對回去（Phase 29 的 `RETRY`／`CATCH`／`TASK_TIMEOUT_SECONDS`／`FAIL_STATE_NAME`／
`task_state`），本檔不抄任何字面值：抄一份就會在 Phase 29 改動時默默分岔（文件現況核對 4）。

CDK 的 Template 斷言不在本檔，在 `tests/unit/infra/test_release_machine.py`——那裡才吃得到
`tests/unit/infra/conftest.py` 的共用 `fake_layer`（**本計畫選擇（2026-09-14）**：不在
`tests/unit/` 再複製一份會分岔的 layer fixture）。
"""

import copy
import json
import pathlib

import pytest

from training_kb.errors import PermanentError, TransientError
from training_kb.pipelines.asl import (
    ASL_LOCAL_PATH,
    CATCH,
    FAIL_STATE_NAME,
    RETRY,
    TASK_TIMEOUT_SECONDS,
    assert_safe_asl,
    canonical_json,
    task_state,
)

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[2]
ASL_PATH = PROJECT_ROOT / ASL_LOCAL_PATH.format(pipeline="release-update", number=1)
ARN = "${PipelineTaskFunctionArn}"

NEXT = {"LocateFeature": "FindSteps", "FindSteps": "SafetyNet", "SafetyNet": "ChooseAction",
        "PrepareUpdate": "PublishBatch", "PublishBatch": "UpdateAliases",
        "UpdateAliases": "Succeeded", "RetireTutorials": "Succeeded"}
"""七個 Task state 與它們的 `Next`（文件 §6 的表）；`RetireTutorials` 不經 `PublishBatch`。"""

TASK_STATES = tuple(NEXT)

ORDER = ["locate_feature", "find_steps", "safety_net", "prepare_update",
         "publish_batch", "update_aliases", "retire"]
"""`Parameters.task` 的固定值（D-51）；`find_steps` 包的是 Phase 50 的 `find_release_hits`。"""


@pytest.fixture
def asl() -> dict:
    return json.loads(ASL_PATH.read_text(encoding="utf-8"))


# --- Task 2：ASL 結構與失敗語意 ----------------------------------------------


def test_every_task_has_the_shared_retry_and_catch(asl: dict) -> None:
    """Given 七個 Task state，Then `Retry`／`Catch`／`TimeoutSeconds` 全部來自 Phase 29。

    JSON 讀回來的是 list、Phase 29 的常數是 tuple，所以拿 `task_state(...)` 產生的同一份
    形狀整個比對，而不是逐欄手寫字面值。
    """
    assert_safe_asl(asl)                                   # Phase 29 的遞迴檢查
    assert len(RETRY) == 2 and RETRY[0]["ErrorEquals"] == ["TransientError"]   # D-53
    for name, next_state in NEXT.items():
        state, expected = asl["States"][name], task_state(ARN, next_state)
        expected["Parameters"] = {"pipeline": "release-update",
                                  "task": state["Parameters"]["task"], "state.$": "$"}
        assert state == expected, name
        assert (state["Retry"], state["Catch"], state["TimeoutSeconds"]) \
            == (list(RETRY), list(CATCH), TASK_TIMEOUT_SECONDS), name
    assert asl["States"][FAIL_STATE_NAME]["Type"] == "Fail"


def test_task_envelope_is_the_direct_function_arn(asl: dict) -> None:
    """Given 直接函式 ARN（D-49），Then 封套只有三欄、沒有 `Payload` 外層。"""
    parameters = [asl["States"][name]["Parameters"] for name in TASK_STATES]
    assert [row["task"] for row in parameters] == ORDER
    assert all(set(row) == {"pipeline", "task", "state.$"} for row in parameters)
    assert all(row["pipeline"] == "release-update" and row["state.$"] == "$"
               for row in parameters)
    assert {asl["States"][name]["Resource"] for name in TASK_STATES} == {ARN}
    # Lambda runtime 把未攔截例外的類別名放進 errorType，ASL 就用它比對
    assert (TransientError.__name__, PermanentError.__name__) == ("TransientError",
                                                                  "PermanentError")


def test_choice_has_default_and_no_retry(asl: dict) -> None:
    """Given `ChooseAction` 是 Choice，Then 有 `Default`、沒有 Retry／Catch／End。"""
    choice = asl["States"]["ChooseAction"]
    assert choice["Type"] == "Choice"
    assert choice["Default"] == "RecordKeep"
    assert "Retry" not in choice and "Catch" not in choice and "End" not in choice
    assert choice["Choices"] == [
        {"Variable": "$.action", "StringEquals": "UPDATE", "Next": "PrepareUpdate"},
        {"Variable": "$.action", "StringEquals": "RETIRE", "Next": "RetireTutorials"}]
    assert asl["States"]["RetireTutorials"]["Next"] == "Succeeded"   # RETIRE 不經 PublishBatch


def test_keep_is_a_business_result_not_a_failure(asl: dict) -> None:
    """Given 零命中，Then `RecordKeep` 把 `action` 正規化成 KEEP 再走唯一的成功終點。"""
    assert asl["States"]["RecordKeep"] == {"Type": "Pass", "Result": "KEEP",
                                           "ResultPath": "$.action", "Next": "Succeeded"}
    succeed = {name for name, state in asl["States"].items() if state["Type"] == "Succeed"}
    assert succeed == {"Succeeded"}
    assert asl["StartAt"] == "LocateFeature"


def test_assert_safe_asl_rejects_the_same_file_without_a_catch(asl: dict) -> None:
    """Given 手動拿掉任何一個 `Catch`，Then 靜態檢查必須轉紅（文件 Task 2 Step 4）。"""
    broken = copy.deepcopy(asl)
    del broken["States"]["RetireTutorials"]["Catch"]
    with pytest.raises(PermanentError, match="RetireTutorials"):
        assert_safe_asl(broken)


def test_definition_file_is_canonical_bytes(asl: dict) -> None:
    """Given 部署與 S3 快照是同一份 bytes，Then 檔案本身就是 `canonical_json` 的輸出。"""
    assert ASL_PATH.read_bytes() == canonical_json(asl)
