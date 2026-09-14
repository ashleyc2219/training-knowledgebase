"""Phase 29 Task 2／3：ASL 的失敗語意（每個 Task 都有 Retry／Catch）與版本化快照。"""

from typing import Any

import pytest

from training_kb.errors import ObjectAlreadyExists, PermanentError
from training_kb.pipelines.asl import (
    ASL_LOCAL_PATH,
    ASL_SNAPSHOT_KEY,
    assert_safe_asl,
    canonical_json,
    save_asl_snapshot,
    task_state,
)

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


class FakeRepository:
    """只記錄物件的假 Repository，`if_none_match` 的語意與 S3 412 相同。"""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def put_object(self, key: str, body: bytes, content_type: str, *,
                   if_none_match: bool) -> None:
        if if_none_match and key in self.objects:
            raise ObjectAlreadyExists(key)
        self.objects[key] = body

    def get_object(self, key: str) -> bytes | None:
        return self.objects.get(key)


def test_snapshot_versioned_and_never_overwritten() -> None:
    repository = FakeRepository()
    body = canonical_json(sample_definition())
    key = save_asl_snapshot(repository, "ticket-analysis", 1, body)
    assert key == "stepfunctions/ticket-analysis/v1.json"
    assert save_asl_snapshot(repository, "ticket-analysis", 1, body) == key   # 同內容重送＝冪等
    with pytest.raises(PermanentError):
        save_asl_snapshot(repository, "ticket-analysis", 1, body + b"\n")
    assert repository.objects[key] == body


def test_canonical_json_is_stable_and_local_path_matches_the_snapshot_key() -> None:
    assert canonical_json(sample_definition()) == canonical_json(sample_definition())
    assert ASL_LOCAL_PATH.format(pipeline="release-update", number=1) == \
        "infra/stepfunctions/release-update/v1.json"
    assert ASL_SNAPSHOT_KEY.format(pipeline="release-update", number=1) == \
        "stepfunctions/release-update/v1.json"


def test_snapshot_rejects_an_unknown_pipeline_name() -> None:
    repository = FakeRepository()
    with pytest.raises(PermanentError):
        save_asl_snapshot(repository, "analytics", 1, b"{}")
    assert repository.objects == {}
