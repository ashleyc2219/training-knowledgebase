"""Phase 29 Task 2／3：ASL 的失敗語意（每個 Task 都有 Retry／Catch）與版本化快照。"""

from typing import Any

import pytest

from training_kb.errors import PermanentError
from training_kb.pipelines.asl import assert_safe_asl, task_state

TASK_ARN = "arn:aws:lambda:ap-northeast-1:123456789012:function:training-kb-pipeline-task"


def sample_definition() -> dict[str, Any]:
    return {
        "Comment": "ticket-analysis v1",
        "StartAt": "EnsureEmbedding",
        "States": {
            "EnsureEmbedding": task_state(TASK_ARN, "AssignCluster"),
            "AssignCluster": task_state(TASK_ARN, "Done"),
            "Done": {"Type": "Succeed"},
            "PipelineFailed": {"Type": "Fail", "Error": "PipelineFailed",
                               "Cause": "本次不建版也不發布"},
        },
    }


def test_every_task_retries_then_catches_to_fail() -> None:
    definition = sample_definition()
    assert_safe_asl(definition)
    for state in definition["States"].values():
        if state["Type"] != "Task":
            continue
        assert state["Resource"] == TASK_ARN   # 直接函式 ARN，沒有 lambda:invoke 信封
        business, service = state["Retry"][0], state["Retry"][1]   # D-53：固定兩條 retrier
        assert business["ErrorEquals"] == ["TransientError"]
        assert service["ErrorEquals"] == ["Lambda.ServiceException", "Lambda.AWSLambdaException",
                                          "Lambda.SdkClientException",
                                          "Lambda.TooManyRequestsException"]
        for retry in (business, service):
            assert (retry["IntervalSeconds"], retry["MaxAttempts"],
                    retry["BackoffRate"]) == (1, 2, 2)
        assert state["TimeoutSeconds"] == 120
        assert state["Catch"][0]["ErrorEquals"] == ["States.ALL"]
        assert state["Catch"][0]["Next"] == "PipelineFailed"
    assert definition["States"]["PipelineFailed"]["Type"] == "Fail"


def test_missing_catch_inside_map_is_rejected() -> None:
    definition = sample_definition()
    inner = task_state(TASK_ARN, "InnerDone")
    del inner["Catch"]
    definition["States"]["AssignCluster"] = {
        "Type": "Map", "Next": "Done",
        "ItemProcessor": {"StartAt": "InnerTask",
                          "States": {"InnerTask": inner, "InnerDone": {"Type": "Succeed"}}},
    }
    with pytest.raises(PermanentError) as error:
        assert_safe_asl(definition)
    assert "AssignCluster.ItemProcessor.InnerTask" in str(error.value)


def test_task_with_only_the_first_retrier_is_rejected() -> None:
    definition = sample_definition()
    definition["States"]["AssignCluster"]["Retry"] = [
        definition["States"]["AssignCluster"]["Retry"][0]
    ]
    with pytest.raises(PermanentError) as error:
        assert_safe_asl(definition)
    assert "AssignCluster" in str(error.value)
