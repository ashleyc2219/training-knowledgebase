"""Phase 18：schema 通過不等於業務通過、最多一次修正、生成參數與輸出重用。"""

import pytest

from training_kb.errors import ContentError, PermanentError, TransientError
from training_kb.writing.client import _generate_with_correction
from training_kb.writing.schemas import GapNaming, StepRewrite
from training_kb.writing.validators import gap_naming_validator, step_rewrite_validator


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
    result = _generate_with_correction(fake_writer, "s", "u", StepRewrite, HIT_SET_ONLY_3,
                                       operation_id="op-release-r_42", node="prepare_update")
    assert result == GOOD_STEP_3
    assert fake_writer.request_attempts == 1


def test_business_invalid_output_is_fixed_by_exactly_one_correction(fake_writer) -> None:
    fake_writer.replies.extend([BAD_STEP_2, GOOD_STEP_3])
    result = _generate_with_correction(fake_writer, "s", "u", StepRewrite, HIT_SET_ONLY_3,
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
        _generate_with_correction(fake_writer, "s", "u", StepRewrite, validate,
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
        _generate_with_correction(fake_writer, "s", "u", GapNaming, lambda payload: None,
                                  operation_id="op-ticket-t_881", node="name_gap")
    assert fake_writer.request_attempts == 1
