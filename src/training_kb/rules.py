"""Active 寫作規則的選取與注入：CREATE／UPDATE／REFINE 共用的四個純函式。

一般寫作路徑只吃 `status == active` 的規則（candidate 與 retired 永不入選），再用
`applies_when == step_type` 的單一等值條件篩出適用範圍（設計 §19 決策 D16，所以不需要
條件字串 parser）。同一範圍有多條時只留最近驗證通過者（決策 F28）；平手時取較小的
`rule_id`，讓結果可重現。

最近驗證時間**不在**十個業務實體裡：`AuthoringRule` 沒有 `validated_at` 欄位，權威來源是
私有 S3 檔 `operations/rules/validated_at.json`（00A D-28）。呼叫端先讀好再以
`validated_at_by_rule` 傳進來，本模組自己不碰 `Repository`、`Writer` 或任何 AWS API；
缺值代表資料不完整，直接 `PermanentError`，不拿「現在」或「最早」時間補。

`render_rules_block` 與 `applied_rule_ids` 都只吃同一份 selected list，prompt 與版本紀錄
因此不會分叉（決策 F29：複製原文不算本次套用）。規則文字的轉義由 Phase 17
`writing/prompts.py` 的 `_as_data` 在 `<active_rules>` 分區統一做（00A D-67），本模組不重複一份。
"""

from collections.abc import Mapping, Sequence
from datetime import datetime

from training_kb.errors import PermanentError
from training_kb.models import AuthoringRule, RuleStatus, StepType


def select_active_rules(
    rules: Sequence[AuthoringRule],
    step_type: StepType,
    validated_at_by_rule: Mapping[str, datetime],
) -> list[AuthoringRule]:
    """回本次要注入的 active 規則；同一個 `step_type` 最多一條。"""
    matching = [item for item in rules
                if item.status == RuleStatus.ACTIVE and item.applies_when == step_type]
    missing = sorted(item.rule_id for item in matching
                     if item.rule_id not in validated_at_by_rule)
    if missing:
        raise PermanentError(f"缺少最近驗證時間：{'、'.join(missing)}")
    # 兩次穩定排序：先讓 rule_id 升序，再依驗證時間降序重排，時間相同時就保留 rule_id 升序。
    # 寫成 `key=lambda item: (時間, rule_id)` 再 `reverse=True` 會把 rule_id 一起反轉成降序。
    matching.sort(key=lambda item: item.rule_id)
    matching.sort(key=lambda item: validated_at_by_rule[item.rule_id], reverse=True)
    return matching[:1]
