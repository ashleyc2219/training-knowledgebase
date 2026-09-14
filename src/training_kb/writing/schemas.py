"""八個 Claude 工作的固定 JSON schema（Draft 2020-12）與 schema-first 驗證入口。

schema 只描述**形狀**：欄位在不在、型別對不對、enum 值合不合法。
「Feature 真的存在嗎」「步驟編號是這一版的嗎」「未改動的文字有沒有被動過」屬於業務，
由 Phase 18 的 validator 與 Phase 21 的內容驗證再擋一次（設計 §7.6、§14.1）。

每個 object 都是 `additionalProperties: false`：模型多回一個欄位就是不合法，
模型因此無法夾帶新的識別碼、Feature 或回饋類別。會變動的核定類別清單刻意**不寫進**
`CommentClassification`（它存在 `CONFIG#feedback_categories`），值是否核定由 Phase 43／18 比對。
"""

from collections.abc import Mapping
from typing import Any

from jsonschema import Draft202012Validator

_DRAFT = "https://json-schema.org/draft/2020-12/schema"

# 設計 §7.6：步驟型別只有三種；`RuleProposal.applies_when` 也用同一組字串
# （Phase 47 驗證後才轉成 StepType 存進 AuthoringRule.applies_when，00A D-10）。
_STEP_TYPES = ["click_ui", "input", "read"]

_TEXT: dict[str, object] = {"type": "string", "minLength": 1}
# 步驟編號一律叫 `number`，從 1 起算，沒有 0-based index（00A §3.3）。
_NUMBER: dict[str, object] = {"type": "integer", "minimum": 1}
_ID_LIST: dict[str, object] = {"type": "array", "items": _TEXT}

_STEP: dict[str, object] = {
    "type": "object", "additionalProperties": False,
    "required": ["number", "type", "text", "feature_id"],
    "properties": {"number": _NUMBER, "type": {"enum": _STEP_TYPES},
                   "text": _TEXT, "feature_id": _TEXT},
}

GapNaming: dict[str, object] = {
    "$schema": _DRAFT, "$id": "GapNaming", "type": "object",
    "required": ["gap", "feature_id"], "additionalProperties": False,
    # feature_id 是**裸 ID**（`Prepare`，不是 `FEATURE#Prepare`）或 null；
    # null 代表「沒有對應 Feature」，是設計 §14.1 明列的合法業務結果，不是錯誤。
    "properties": {"gap": _TEXT, "feature_id": {"type": ["string", "null"], "minLength": 1}},
}

TutorialDraft: dict[str, object] = {
    "$schema": _DRAFT, "$id": "TutorialDraft", "type": "object",
    "required": ["title", "problem", "prerequisites", "steps", "expected_outcome"],
    "additionalProperties": False,
    # 五段缺一不可；沒有前置條件時寫「無」而不是空陣列，與 Phase 21 一致。
    "properties": {"title": _TEXT, "problem": _TEXT, "expected_outcome": _TEXT,
                   "prerequisites": {"type": "array", "minItems": 1, "items": _TEXT},
                   "steps": {"type": "array", "minItems": 1, "items": _STEP}},
}

StepRewrite: dict[str, object] = {
    "$schema": _DRAFT, "$id": "StepRewrite", "type": "object",
    "required": ["steps"], "additionalProperties": False,
    # 「哪幾號步驟改成什麼」；漏回或多回命中步驟由 Phase 51 的核對擋（schema 不管數量）。
    "properties": {"steps": {"type": "array", "items": _STEP}},
}

CommentClassification: dict[str, object] = {
    "$schema": _DRAFT, "$id": "CommentClassification", "type": "object",
    "required": ["category"], "additionalProperties": False,
    "properties": {"category": _TEXT},
}

RuleProposal: dict[str, object] = {
    "$schema": _DRAFT, "$id": "RuleProposal", "type": "object",
    "required": ["rule", "applies_when", "evidence", "derived_from"],
    "additionalProperties": False,
    # evidence 至少五筆 Feedback ID（Phase 47 的 candidate 門檻）；derived_from 恰一個 version_id。
    "properties": {"rule": _TEXT, "applies_when": {"enum": _STEP_TYPES},
                   "evidence": {"type": "array", "minItems": 5, "items": _TEXT},
                   "derived_from": _TEXT},
}

ConflictJudgement: dict[str, object] = {
    "$schema": _DRAFT, "$id": "ConflictJudgement", "type": "object",
    "required": ["conflicts", "rule_ids", "evidence"], "additionalProperties": False,
    # rule_ids 是既有規則 ID、evidence 是 Feedback ID；兩者存不存在一律由 Phase 55 回查。
    "properties": {"conflicts": {"type": "boolean"}, "rule_ids": _ID_LIST,
                   "evidence": _ID_LIST},
}

StepConfirmation: dict[str, object] = {
    "$schema": _DRAFT, "$id": "StepConfirmation", "type": "object",
    "required": ["confirmed_step_numbers", "reason"], "additionalProperties": False,
    # 空陣列是合法的「一個候選都沒命中」，Phase 50 據此記未命中，不是模型故障。
    "properties": {"confirmed_step_numbers": {"type": "array", "items": _NUMBER},
                   "reason": _TEXT},
}

WeakDiagnosis: dict[str, object] = {
    "$schema": _DRAFT, "$id": "WeakDiagnosis", "type": "object",
    "required": ["items"], "additionalProperties": False,
    # 每個被診斷的步驟各自一個原因；欄位名固定是 `number`，不是 `index`。
    # items 可為空陣列，Phase 45 據此回 NO_STEP。
    "properties": {"items": {"type": "array", "items": {
        "type": "object", "additionalProperties": False,
        "required": ["number", "reason"],
        "properties": {"number": _NUMBER, "reason": _TEXT}}}},
}

SCHEMAS: dict[str, dict[str, object]] = {
    str(schema["$id"]): schema
    for schema in (GapNaming, TutorialDraft, StepRewrite, CommentClassification,
                   RuleProposal, ConflictJudgement, StepConfirmation, WeakDiagnosis)
}


def validate_schema(schema: Mapping[str, Any], payload: object) -> None:
    """全套唯一一個 JSON schema 驗證入口；不合法丟 `jsonschema` 的 `ValidationError`。"""
    Draft202012Validator(schema).validate(payload)
