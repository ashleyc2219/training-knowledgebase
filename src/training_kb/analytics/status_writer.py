"""規則「最近驗證時間」的單一檔讀寫（00A D-28）。

`AuthoringRule` **沒有** `validated_at` 欄位，也不得為了方便在 `RULE#` item 上加一個
（00A D-40：item 屬性＝模型欄位＋`RESERVED_ATTRS`，沒有第三類）。權威來源是單一私有檔
`operations/rules/validated_at.json`，形狀是 `{"<rule_id>": "<ISO 8601 UTC>"}`。

```text
P55 apply_rule_status --寫--> operations/rules/validated_at.json --讀--> P40／P46／P51
                                        ^                                    |
                              這支檔案唯一的寫入者                    load_validated_at
                                                                             |
                                            P19 rules_for_content(..., 這個 mapping)
```

本檔由 **Phase 40 首建，只放讀取端**（`VALIDATED_AT_KEY` 與 `load_validated_at`）：它比
Phase 55 早用到規則的驗證時間。**寫入端 `apply_rule_status`（以及 `LEGAL_TRANSITIONS`、
`next_status`、`record_evaluation` 等）由 Phase 55 補在同一支檔案上**，不要另開新檔。

Phase 55 之前這個檔不存在，`load_validated_at` 回 `{}`，而且也不會有任何 active 規則
（轉 active 的唯一入口就是 Phase 55），所以 `rules_applied` 是 `[]`——這是正常狀態，
不可為了湊資料把 candidate 規則放進來。缺驗證時間的 active 規則由 Phase 19 丟
`PermanentError`，本檔**不補預設時間**（不拿「最早」或「現在」充數）。
"""

import json
from collections.abc import Mapping
from dataclasses import asdict
from datetime import datetime

from training_kb.analytics.validation import RuleEvaluation
from training_kb.clock import parse_iso, to_iso
from training_kb.errors import PermanentError
from training_kb.keys import rule_pk
from training_kb.models import AuthoringRule, RuleStatus
from training_kb.repository import Repository

VALIDATED_AT_KEY = "operations/rules/validated_at.json"
"""規則最近驗證時間的唯一私有檔；全系統只有這一份字面值（00A D-28）。"""


def load_validated_at(repository: Repository) -> dict[str, datetime]:
    """讀回 `rule_id -> 最近驗證時間`；檔案不存在回 `{}`。

    直接把結果傳給 Phase 19 的 `rules_for_content(rules, step_types, validated_at_by_rule)`，
    呼叫端不得自己再攢一份（00A D-28 明令不留 `_validated_at`／`_load_validated_at` 私有副本）。

    檔案壞掉（不是 JSON 物件、值不是 ISO 時間）一律 `PermanentError`：規則要不要注入是
    可重現的判斷，猜一個時間會讓同一批輸入在不同時刻得到不同的 `rules_applied`。

    **解碼與 `json.loads` 也在 `try` 之內**：壞 UTF-8 會丟 `UnicodeDecodeError`、壞 JSON
    會丟 `json.JSONDecodeError`，兩者都不是 `PermanentError`，漏出去的話 ASL 的 Catch
    分不到失敗終點、呼叫端也接不到（00A §4.1）。`PermanentError` 不是 `ValueError` 的子類，
    所以 `try` 裡那個「不是物件」的 raise 不會被自己的 `except` 再包一層。
    """
    body = repository.get_object(VALIDATED_AT_KEY)
    if body is None:
        return {}
    try:
        payload: object = json.loads(body.decode("utf-8"))
        if not isinstance(payload, dict):
            raise PermanentError(f"{VALIDATED_AT_KEY} 必須是 rule_id 對應時間的物件")
        return {str(rule_id): parse_iso(str(value)) for rule_id, value in payload.items()}
    except (ValueError, UnicodeDecodeError) as error:
        raise PermanentError(f"{VALIDATED_AT_KEY} 內容損壞或有不合法的時間字串") from error


# ---- Phase 55 ----
#
# 寫入端。`apply_rule_status` 是**全系統唯一**寫 `RULE.status` 與最近驗證時間的位置
# （VAL Rule 8）：Feedback Review 只提出 `status=candidate` 的新規則，Phase 28 的
# `rebuild_rule_projection` 動的是 `applied_to`，兩者都不碰 `status`。

LEGAL_TRANSITIONS = frozenset({
    (RuleStatus.CANDIDATE, RuleStatus.ACTIVE),
    (RuleStatus.CANDIDATE, RuleStatus.RETIRED),
    (RuleStatus.ACTIVE, RuleStatus.RETIRED)})
"""唯三合法的轉移；`retired` 是終態，規則不自動復活（設計 §12.2）。"""


def _write_json(key: str, payload: Mapping[str, object], *, repository: Repository) -> None:
    """整檔覆寫一個私有 JSON 物件。

    `if_none_match=False`：這兩個檔都是**可重寫**的彙總檔（同一批次重跑要得到同樣結果），
    不是「只能建立一次」的 operation 紀錄。`sort_keys=True` 讓同一份內容永遠是同一串
    位元組，冪等才看得出來。
    """
    body = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    repository.put_object(key, body, "application/json", if_none_match=False)


def record_evaluation(evaluation: RuleEvaluation, *, repository: Repository) -> str:
    """把一個批次的評估寫成人工核對用的證據檔，回傳它的 key。

    `asdict` 保證證據檔一定含全部欄位（含兩個差值）；`version_ids` 是 `frozenset`，
    `json.dumps` 會 `TypeError`，所以覆寫成排序後的清單。這個檔**不是**
    `validated_at_by_rule` 的來源——最近驗證時間只有 `VALIDATED_AT_KEY` 一個權威位置。
    """
    key = (f"operations/analytics/rule-validation/{evaluation.rule_id}"
           f"/{evaluation.batch_id}.json")
    payload = asdict(evaluation) | {"version_ids": sorted(evaluation.version_ids)}
    _write_json(key, payload, repository=repository)
    return key


def apply_rule_status(rule_id: str, status: RuleStatus, *, repository: Repository,
                      now: datetime) -> AuthoringRule:
    """唯一寫入者：改 `RULE.status`，並把最近驗證時間併進單一檔（D-28）。

    四件事，順序不可調換：

    1. 先 `get_meta` 判 `None`——`revision_of` 對不存在的 item 丟 **`CoordinationError`**
       而不是 `PermanentError`，先問它會讓「規則不存在」變成看不懂的協調錯誤。
    2. 目前狀態就是目標狀態時**跳過** `update_meta`（不製造無意義的 revision 位移），
       其餘步驟照做——同一批次帶同一個 `now` 重跑兩次結果才會完全相同。
    3. 非法轉移（含 `retired -> active`）丟 `PermanentError`；寫入用
       `expected_revision=revision_of(pk)` 的 compare-and-swap，避免靜默覆蓋（D-27）。
    4. 併寫 `operations/rules/validated_at.json`。`clock.to_iso` 遇到帶微秒的時間**直接
       丟 `PermanentError`**（不靜默截斷），所以這裡先 `now.replace(microsecond=0)`。
    """
    target = RuleStatus(status)
    pk = rule_pk(rule_id)
    rule = repository.get_meta(pk, AuthoringRule)
    if rule is None:
        raise PermanentError(f"找不到規則：{rule_id}")
    if rule.status is not target:
        if (rule.status, target) not in LEGAL_TRANSITIONS:
            raise PermanentError(f"不合法的狀態轉移：{rule.status} -> {target}")
        repository.update_meta(pk, {"status": target.value},
                               expected_revision=repository.revision_of(pk))
        written = repository.get_meta(pk, AuthoringRule)
        if written is None:
            raise PermanentError(f"寫入後讀不回規則：{rule_id}")
        rule = written
    table = {key: to_iso(value) for key, value in load_validated_at(repository).items()}
    table[rule_id] = to_iso(now.replace(microsecond=0))
    _write_json(VALIDATED_AT_KEY, table, repository=repository)
    return rule
