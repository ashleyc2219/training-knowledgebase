"""Phase 41 Task 2／3：`ticket-analysis` 的 ASL 結構與 `TrainingKbStack` 的 Template 斷言。

ASL 的 `Retry`／`Catch`／`TimeoutSeconds` **一律從 `training_kb.pipelines.asl` import**
再比對回去（Phase 29 的 `RETRY`／`CATCH`／`task_state`），本檔不抄任何字面值：抄一份就會
在 Phase 29 改動時默默分岔。
"""

import copy
import json
import pathlib
import sys

import pytest

from training_kb.errors import PermanentError, TransientError
from training_kb.pipelines.asl import (
    ASL_LOCAL_PATH,
    CATCH,
    RETRY,
    assert_safe_asl,
    canonical_json,
)
from training_kb.pipelines.common import task_name
from training_kb.pipelines.ticket import TICKET_ANALYSIS_TASKS

# infra/ 是部署用的 CDK 程式，不在 src/ 的安裝套件裡，所以把專案根目錄加進路徑
# （同 tests/unit/test_data_stack.py 的既有作法）。
PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

ASL_PATH = PROJECT_ROOT / ASL_LOCAL_PATH.format(pipeline="ticket-analysis", number=1)
ARN = "${PipelineTaskFunctionArn}"
NEXT = {"EnsureEmbedding": "AssignCluster", "AssignCluster": "EvaluateRecurring",
        "EvaluateRecurring": "IsRecurring", "NameGap": "DecideAction",
        "DecideAction": "ChooseAction", "CreateFirstVersion": "PublishVersion",
        "PublishVersion": "Published"}


@pytest.fixture
def asl() -> dict:
    return json.loads(ASL_PATH.read_text(encoding="utf-8"))


# --- Task 2：ASL 結構 --------------------------------------------------------


def test_every_task_state_equals_phase29_template_plus_parameters(asl: dict) -> None:
    """Given 七個 Task state，Then 除了 `Parameters` 逐欄等於 Phase 29 的 `task_state`。"""
    from training_kb.pipelines.asl import task_state
    assert len(RETRY) == 2 and RETRY[0]["ErrorEquals"] == ["TransientError"]   # D-53
    for name, next_state in NEXT.items():
        state, expected = asl["States"][name], task_state(ARN, next_state)
        expected["Parameters"] = {"pipeline": "ticket-analysis",
                                  "task": state["Parameters"]["task"], "state.$": "$"}
        assert state == expected, name        # Retry／Catch／TimeoutSeconds 全部來自 Phase 29


def test_asl_task_names_and_branches_match_python(asl: dict) -> None:
    """Given ASL 與 Python 兩邊，Then Task 名稱、封套與兩個 Choice 的分支都對得上。"""
    parameters = [asl["States"][name]["Parameters"] for name in NEXT]
    assert [row["task"] for row in parameters] == [task_name(t) for t in TICKET_ANALYSIS_TASKS]
    assert all(row["pipeline"] == "ticket-analysis" and row["state.$"] == "$"
               and "Payload" not in row for row in parameters)
    assert_safe_asl(asl)
    assert asl["StartAt"] == "EnsureEmbedding"
    assert asl["States"]["PipelineFailed"]["Type"] == "Fail"
    assert asl["States"]["ChooseAction"]["Default"] == CATCH[0]["Next"] == "PipelineFailed"
    assert asl["States"]["IsRecurring"]["Default"] == "NotRecurring"
    # Lambda runtime 把未攔截例外的類別名放進 errorType，ASL 就用它比對
    assert (TransientError.__name__, PermanentError.__name__) == ("TransientError",
                                                                  "PermanentError")


def test_four_succeed_states_and_the_two_choices(asl: dict) -> None:
    """Given 四個成功終點與兩個 Choice，Then 分支目標逐一對得上流程圖（§1）。"""
    succeed = {name for name, state in asl["States"].items() if state["Type"] == "Succeed"}
    assert succeed == {"Published", "Kept", "GapRetained", "NotRecurring"}
    assert asl["States"]["IsRecurring"]["Choices"] == [
        {"Variable": "$.is_recurring", "BooleanEquals": True, "Next": "NameGap"}]
    assert asl["States"]["ChooseAction"]["Choices"] == [
        {"Variable": "$.action", "StringEquals": "CREATE", "Next": "CreateFirstVersion"},
        {"Variable": "$.action", "StringEquals": "KEEP", "Next": "Kept"},
        {"Variable": "$.action", "StringEquals": "NO_FEATURE", "Next": "GapRetained"}]


def test_assert_safe_asl_rejects_the_same_file_without_a_catch(asl: dict) -> None:
    """Given 手動拿掉任何一個 `Catch`，Then 靜態檢查必須轉紅（文件 Task 2 Step 4）。"""
    broken = copy.deepcopy(asl)
    del broken["States"]["NameGap"]["Catch"]
    with pytest.raises(PermanentError, match="NameGap"):
        assert_safe_asl(broken)


def test_definition_file_is_canonical_bytes(asl: dict) -> None:
    """Given 部署與 S3 快照是同一份 bytes，Then 檔案本身就是 `canonical_json` 的輸出。"""
    assert ASL_PATH.read_bytes() == canonical_json(asl)
