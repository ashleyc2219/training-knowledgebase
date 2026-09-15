"""Phase 18：schema 通過不等於業務通過、最多一次修正、生成參數與輸出重用。"""

import json
from typing import Any

import pytest

import training_kb.writing as writing
from training_kb.errors import ContentError, PermanentError, TransientError
from training_kb.writing.client import (
    BedrockWriter,
    CallTrace,
    bedrock_config,
    generate_validated_json,
    inference_config,
)
from training_kb.writing.schemas import SCHEMAS, GapNaming, StepRewrite, TutorialDraft
from training_kb.writing.validators import gap_naming_validator, step_rewrite_validator


class ConfigRecordingClient:
    """只記下送出的 kwargs；回應形狀與 Bedrock Converse 一致，答案由測試先排好。"""

    def __init__(self, *answers: dict[str, Any]) -> None:
        self.requests: list[dict[str, Any]] = []
        self.answers = list(answers)

    def converse(self, **kwargs: Any) -> dict[str, Any]:
        self.requests.append(kwargs)
        text = json.dumps(self.answers.pop(0), ensure_ascii=False)
        return {"output": {"message": {"content": [{"text": text}]}}, "stopReason": "end_turn"}


class FakeObjectStore:
    """Phase 07 `Repository.put_object`／`get_object` 的最小替身，另加一次性故障注入。

    Phase 07／08 的 `repository.py` 與 `tests/integration/` 目前由別的 agent 在改，
    Phase 10 的 `OperationCoordinator` 也還沒有；這裡用本地替身鎖住「儲存重試重用既有
    bytes」這個行為，真正接上 Repository 與 coordinator 由 Phase 40／41 的測試負責。
    """

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self._pending_error: Exception | None = None

    def fail_next_put(self, error: Exception) -> None:
        self._pending_error = error

    def put_object(self, key: str, body: bytes, content_type: str, *,
                   if_none_match: bool) -> None:
        if self._pending_error is not None:
            error, self._pending_error = self._pending_error, None
            raise error
        self.objects[key] = body

    def get_object(self, key: str) -> bytes | None:
        return self.objects.get(key)


class FakeRecord:
    """只有本測試用得到的那一個欄位；型別與 `OperationRecord.model_output_refs` 相同。"""

    def __init__(self, refs: tuple[str, ...]) -> None:
        self.model_output_refs = refs


class FakeCoordinator:
    """Phase 10 `record_model_output`／`load` 的最小替身。"""

    def __init__(self) -> None:
        self._refs: dict[str, tuple[str, ...]] = {}

    def record_model_output(self, operation_id: str, output_ref: str) -> None:
        self._refs[operation_id] = self._refs.get(operation_id, ()) + (output_ref,)

    def load(self, operation_id: str) -> FakeRecord | None:
        refs = self._refs.get(operation_id)
        return None if refs is None else FakeRecord(refs)


def operation_ref(operation_id: str, name: str) -> str:
    """Phase 10 `keys.operation_ref` 的同形替身：`operations/<id>/<name>.json`（00A §6.2）。"""
    return f"operations/{operation_id}/{name}.json"


SAVED_OUTPUT = {"gap": "找不到會前摘要入口", "feature_id": "Prepare"}
TUTORIAL_OUTPUT = {"title": "準備會議", "problem": "找不到會前摘要入口", "prerequisites": ["無"],
                   "steps": [{"number": 1, "type": "click_ui", "text": "點開 Prepare 分頁",
                              "feature_id": "Prepare"}],
                   "expected_outcome": "看得到會前摘要"}


def test_step_rewrite_rejects_number_outside_hit_set() -> None:
    validate = step_rewrite_validator(allowed_steps=frozenset({3}),
                                      allowed_features=frozenset({"Prepare"}))
    with pytest.raises(ContentError, match="step_number_not_in_hit_set"):
        validate({"steps": [{"number": 2, "type": "click_ui", "text": "x",
                             "feature_id": "Prepare"}]})


def test_gap_naming_accepts_null_feature_but_rejects_unknown_id() -> None:
    validate = gap_naming_validator(known_feature_ids=frozenset({"Prepare"}))
    validate({"gap": "找不到會前摘要入口", "feature_id": None})
    with pytest.raises(ContentError, match="feature_id_not_found"):
        validate({"gap": "找不到會前摘要入口", "feature_id": "Admin"})


# `fake_writer` 是 Phase 15 放在 tests/unit/conftest.py 的共用替身（RecordingWriter）：
# 回應先排進 `replies`，實際送出幾次看 `request_attempts`，本檔不另建一個 FakeWriter。
BAD_STEP_2 = {"steps": [{"number": 2, "type": "click_ui",
                         "text": "在會議頁面選擇 Prepare。", "feature_id": "Prepare"}]}
GOOD_STEP_3 = {"steps": [{"number": 3, "type": "click_ui",
                          "text": "在會議頁面選擇 Prepare。", "feature_id": "Prepare"}]}
HIT_SET_ONLY_3 = step_rewrite_validator(allowed_steps=frozenset({3}),
                                        allowed_features=frozenset({"Prepare"}))


def test_first_valid_output_is_returned_without_a_correction(fake_writer) -> None:
    fake_writer.replies.append(GOOD_STEP_3)
    result = generate_validated_json(fake_writer, "s", "u", StepRewrite, HIT_SET_ONLY_3,
                                   operation_id="op-release-r_42", node="prepare_update")
    assert result == GOOD_STEP_3
    assert fake_writer.request_attempts == 1


def test_business_invalid_output_is_fixed_by_exactly_one_correction(fake_writer) -> None:
    fake_writer.replies.extend([BAD_STEP_2, GOOD_STEP_3])
    result = generate_validated_json(fake_writer, "s", "u", StepRewrite, HIT_SET_ONLY_3,
                                   operation_id="op-release-r_42", node="prepare_update")
    correction = fake_writer.calls[1]["user"]
    assert result == GOOD_STEP_3 and fake_writer.request_attempts == 2
    # 修正 prompt 只帶代碼與欄位路徑，不回印模型輸出。
    assert "step_number_not_in_hit_set: steps[].number" in correction
    assert "在會議頁面選擇 Prepare。" not in correction


def test_business_invalid_output_gets_only_one_correction(fake_writer) -> None:
    fake_writer.replies.extend([BAD_STEP_2, BAD_STEP_2])      # 兩次都回命中集合外的步驟
    validate = step_rewrite_validator(allowed_steps=frozenset({3}),
                                      allowed_features=frozenset({"Prepare"}))
    with pytest.raises(PermanentError) as error:
        generate_validated_json(fake_writer, "s", "u", StepRewrite, validate,
                                operation_id="op-release-r_42", node="prepare_update")
    assert fake_writer.request_attempts == 2
    assert "step_number_not_in_hit_set" in str(error.value)
    assert "prepare-meeting" not in str(error.value)


def test_transient_error_is_not_counted_as_a_correction(fake_writer, monkeypatch) -> None:
    def throttled(*args: object, **kwargs: object) -> dict[str, object]:
        # RecordingWriter 沒有「排例外」的佇列，改用 monkeypatch。
        fake_writer.request_attempts += 1
        raise TransientError("throttled")

    monkeypatch.setattr(fake_writer, "generate_json", throttled)
    with pytest.raises(TransientError):
        generate_validated_json(fake_writer, "s", "u", GapNaming, lambda payload: None,
                                operation_id="op-ticket-t_881", node="name_gap")
    assert fake_writer.request_attempts == 1


def test_generation_request_sets_max_tokens_timeout_and_low_temperature() -> None:
    assert inference_config(TutorialDraft) == {"maxTokens": 2048, "temperature": 0.1}
    assert inference_config(GapNaming) == {"maxTokens": 512, "temperature": 0.1}
    assert "topP" not in inference_config(GapNaming)
    config = bedrock_config()
    assert (config.connect_timeout, config.read_timeout) == (2, 30)
    assert config.retries["total_max_attempts"] == 1


@pytest.mark.parametrize("name", sorted(SCHEMAS))
def test_every_schema_gets_max_tokens_and_low_temperature(name: str) -> None:
    """八個 schema 一個都不能漏；教學寫作 2048，其餘判斷類 512（00A §3.7）。

    教學寫作有兩個 schema：`TutorialDraft`（CREATE 整篇）與 `StepRewrite`（P46 REFINE 與
    P51 UPDATE 的命中步驟改寫）。**controller 核准的 R3.6 例外（2026-09-14）**：本行原本
    只認 `TutorialDraft`，是 P18 當時的假設；00A §3.7 明列 P46／P51 屬教學寫作類，以 00A
    為準。截斷（`stopReason == "max_tokens"`）仍然是驗證失敗，不靠調高上限救。
    """
    config = inference_config(SCHEMAS[name])
    assert config["temperature"] == 0.1 and "topP" not in config
    assert config["maxTokens"] == (2048 if name in ("TutorialDraft", "StepRewrite") else 512)


def test_bedrock_writer_sends_the_schema_specific_inference_config() -> None:
    """Phase 15 送出的 inferenceConfig 就是 inference_config(schema)，不是另一份常數。"""
    client = ConfigRecordingClient(SAVED_OUTPUT, TUTORIAL_OUTPUT)
    writer = BedrockWriter(client, CallTrace(), generation_model_id="verified-model",
                           embedding_model_id="amazon.titan-embed-text-v2:0")
    writer.generate_json("s", "u", GapNaming, operation_id="op-1", node="name_gap")
    writer.generate_json("s", "u", TutorialDraft, operation_id="op-1", node="create_v1")
    assert client.requests[0]["inferenceConfig"] == {"maxTokens": 512, "temperature": 0.1}
    assert client.requests[1]["inferenceConfig"] == {"maxTokens": 2048, "temperature": 0.1}


def test_storage_retry_reuses_recorded_output(fake_writer) -> None:
    """儲存暫時失敗時重用 `model_output_refs[-1]` 的 bytes，不再叫一次模型。"""
    repository, coordinator = FakeObjectStore(), FakeCoordinator()

    def save_gap(payload: dict) -> None:      # 代表 Phase 39／40 的保存步驟
        repository.put_object("operations/gap/last.json", json.dumps(payload).encode(),
                              "application/json", if_none_match=False)

    op = "op-ticket-t_881"
    fake_writer.replies.append({"gap": "找不到會前摘要入口", "feature_id": "Prepare"})
    output = generate_validated_json(
        fake_writer, "s", "u", GapNaming,
        gap_naming_validator(known_feature_ids=frozenset({"Prepare"})),
        operation_id=op, node="name_gap")
    # 名稱逐字是 "gap-naming"（00A §6.9 的 P39 欄）：operations/<op>/gap-naming.json。
    ref = operation_ref(op, "gap-naming")
    repository.put_object(ref, json.dumps(output).encode(), "application/json", if_none_match=True)
    coordinator.record_model_output(op, ref)
    repository.fail_next_put(TransientError("dynamodb throttled"))
    with pytest.raises(TransientError):
        save_gap(output)
    record = coordinator.load(op)
    assert record is not None
    reloaded = json.loads(repository.get_object(record.model_output_refs[-1]))
    save_gap(reloaded)
    assert reloaded == output
    assert fake_writer.request_attempts == 1      # 重用既有輸出，沒有第二次模型呼叫


def test_the_correction_loop_is_the_packages_public_entry_point() -> None:
    """00A §6.5：呼叫端呼叫 `generate_validated_json` 一次，不自己重試。

    P39–P51 有 12 個 Phase 要用它，所以它必須是 `writing` 套件 re-export 的公開名稱，
    不能只留在 `client.py` 裡當 module-private。
    """
    assert "generate_validated_json" in writing.__all__
    assert writing.generate_validated_json is generate_validated_json
