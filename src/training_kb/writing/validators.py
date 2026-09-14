"""schema 之後的業務驗證：形狀合法不代表引用得到現在的資料（設計 §7.6、§14.1）。

schema 只看形狀（Phase 17）；「這個 `feature_id` 現在真的存在嗎」「這個步驟編號屬於命中
集合嗎」要有**呼叫當下的 context** 才判得出來，所以一律做成 factory：把 context 閉包進去，
回一個 `BusinessValidator`（合法就安靜回 `None`，不合法丟 `ContentError`）。

錯誤訊息固定是 `<代碼>: <欄位路徑>`，**不含模型輸出、prompt 原文或使用者文字**：
`client.generate_validated_json` 會把這個字串原樣放進修正 prompt 的
`<validation_error>`，也會出現在 log 與 `PermanentError` 裡（00A §3.8）。

八個 schema 的業務檢查只有一份，接入點固定如下（Phase 18 文件 §5；「否」＝不走 correction）：

| Schema | 業務檢查 | 提供者 | correction |
|---|---|---|---|
| `GapNaming` | `feature_id` 是既有 Feature 或 `null` | 本檔 | 是 |
| `TutorialDraft` | 五段非空、每步恰一個既有 Feature、編號連續 | P21 `validate_content` | 是 |
| `StepRewrite` | 編號在命中集合內、`feature_id` 存在 | 本檔＋P51 `assert_unchanged` | 是 |
| `CommentClassification` | `category` 在核定類別加 `待分類` 內 | P43 `_settle` | 否：降級 |
| `RuleProposal` | evidence 是本組 Feedback ID、`derived_from` 一版 | P47 | 是 |
| `ConflictJudgement` | `rule_ids` 存在且適用範圍相同 | P55 | 是 |
| `StepConfirmation` | 編號屬於候選版的已發布步驟 | P50 | 否：丟棄 |
| `WeakDiagnosis` | `number` 是目前版本的步驟、`reason` 非空 | P45 | 否：丟棄 |

消費 Phase 的 private helper（例如 P39 的 `_validated_naming`）只是**包裝**這裡的 factory，
不得另寫一份判斷（00A §6.5）。
"""

from collections.abc import Callable
from typing import Any

from training_kb.errors import ContentError

# 業務 validator 的固定形狀：吃已通過 schema 的 dict，合法回 None、不合法丟 ContentError。
BusinessValidator = Callable[[dict[str, Any]], None]


def step_rewrite_validator(*, allowed_steps: frozenset[int],
                           allowed_features: frozenset[str]) -> BusinessValidator:
    """Release 改寫：只准改命中集合裡的步驟，而且每步都要指到既有 Feature。

    未命中步驟有沒有被逐字保留，由 Phase 51 的 `assert_unchanged` 另外核對：那要拿舊版
    全文比對，不屬於這個只看單一 payload 的 callback。
    """
    def validate(payload: dict[str, Any]) -> None:
        for step in payload["steps"]:
            if step["number"] not in allowed_steps:
                raise ContentError("step_number_not_in_hit_set: steps[].number")
            if step["feature_id"] not in allowed_features:
                raise ContentError("feature_id_not_found: steps[].feature_id")
    return validate


def gap_naming_validator(*, known_feature_ids: frozenset[str]) -> BusinessValidator:
    """工單命名：`feature_id` 只能是既有 Feature 的裸 ID，或 `null`。

    `null` 不是錯誤，是設計 §14.1 明列的合法結果（找不到對應 Feature），由 Phase 40 決定
    KEEP／CREATE；模型不得自己造一個新的 Feature ID。schema 的 `feature_id` 是單一字串或
    `null`，「一張 Ticket 最多一個 Feature」因此在形狀上就成立，這裡只補「存不存在」。
    """
    def validate(payload: dict[str, Any]) -> None:
        value = payload["feature_id"]
        if value is not None and value not in known_feature_ids:
            raise ContentError("feature_id_not_found: feature_id")
    return validate
