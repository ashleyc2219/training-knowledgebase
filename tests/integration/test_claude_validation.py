"""O5 通過後，用真實帳號記錄「業務不合法最多兩次 request」這個上限（Phase 18 §6 Task 3）。

預設 skip：Phase 01 的 `tests/conftest.py` 在沒有 `TKB_RUN_AWS_INTEGRATION=1` 時自動跳過
標了 `aws` 的測試。**skip 不得當成通過**；O5 尚未通過（帳號未開通 Bedrock）時這個檔案
實跑會 FAIL，而那正是要保留的證據，不得為了綠燈改寬斷言或填猜測的 model ID。
"""

import json
import os

import pytest

from training_kb.errors import ContentError, PermanentError
from training_kb.writing.client import (
    BedrockWriter,
    CallTrace,
    build_bedrock_client,
    generate_validated_json,
    inference_config,
)
from training_kb.writing.schemas import GapNaming, TutorialDraft
from training_kb.writing.validators import gap_naming_validator

pytestmark = pytest.mark.aws      # Phase 01 conftest：TKB_RUN_AWS_INTEGRATION != "1" 時自動 skip

SYSTEM = "你只輸出符合 GapNaming schema 的 JSON，不輸出任何解釋文字。"
USER = '請輸出 {"gap": "找不到會前摘要入口", "feature_id": "Prepare"}'


def make_writer(trace: CallTrace) -> BedrockWriter:
    """model ID 一律由環境變數提供：O5 未通過時不得在程式裡填猜測值（00A §3.5）。"""
    return BedrockWriter(build_bedrock_client(os.environ["TKB_BEDROCK_REGION"]), trace,
                         generation_model_id=os.environ["TKB_GENERATION_MODEL_ID"],
                         embedding_model_id=os.environ["TKB_EMBEDDING_MODEL_ID"])


def test_business_valid_real_output_costs_one_attempt() -> None:
    trace = CallTrace()
    result = generate_validated_json(
        make_writer(trace), SYSTEM, USER, GapNaming,
        gap_naming_validator(known_feature_ids=frozenset({"Prepare"})),
        operation_id="smoke-validation-ok", node="name_gap")
    assert isinstance(result, dict)
    assert trace.count(operation_id="smoke-validation-ok") == 1


def test_business_invalid_real_output_stops_after_two_attempts() -> None:
    """validator 一律拒絕：真實模型也只會被問兩次，第三次 request 不存在。"""
    trace = CallTrace()

    def always_reject(payload: dict) -> None:
        raise ContentError("feature_id_not_found: feature_id")

    with pytest.raises(PermanentError) as error:
        generate_validated_json(make_writer(trace), SYSTEM, USER, GapNaming, always_reject,
                                operation_id="smoke-validation-bad", node="name_gap")
    rows = json.loads(trace.to_json())
    assert trace.count(operation_id="smoke-validation-bad") == 2
    assert [row["attempt"] for row in rows] == [1, 2]
    # 錯誤與 trace 都只有代碼與固定 metadata，沒有模型輸出或 prompt 原文。
    assert "feature_id_not_found" in str(error.value)
    assert "會前摘要" not in str(error.value) and "會前摘要" not in trace.to_json()


def test_generation_parameters_are_fixed_before_the_request() -> None:
    """權限、逾時或參數錯誤保留 Phase 02 的原始分類；參數本身在送出前就已固定。"""
    assert inference_config(TutorialDraft) == {"maxTokens": 2048, "temperature": 0.1}
    assert inference_config(GapNaming) == {"maxTokens": 512, "temperature": 0.1}
