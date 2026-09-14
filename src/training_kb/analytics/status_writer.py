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
from datetime import datetime

from training_kb.clock import parse_iso
from training_kb.errors import PermanentError
from training_kb.repository import Repository

VALIDATED_AT_KEY = "operations/rules/validated_at.json"
"""規則最近驗證時間的唯一私有檔；全系統只有這一份字面值（00A D-28）。"""


def load_validated_at(repository: Repository) -> dict[str, datetime]:
    """讀回 `rule_id -> 最近驗證時間`；檔案不存在回 `{}`。

    直接把結果傳給 Phase 19 的 `rules_for_content(rules, step_types, validated_at_by_rule)`，
    呼叫端不得自己再攢一份（00A D-28 明令不留 `_validated_at`／`_load_validated_at` 私有副本）。

    檔案壞掉（不是 JSON 物件、值不是 ISO 時間）一律 `PermanentError`：規則要不要注入是
    可重現的判斷，猜一個時間會讓同一批輸入在不同時刻得到不同的 `rules_applied`。
    """
    body = repository.get_object(VALIDATED_AT_KEY)
    if body is None:
        return {}
    payload: object = json.loads(body.decode("utf-8"))
    if not isinstance(payload, dict):
        raise PermanentError(f"{VALIDATED_AT_KEY} 必須是 rule_id 對應時間的物件")
    try:
        return {str(rule_id): parse_iso(str(value)) for rule_id, value in payload.items()}
    except ValueError as error:
        raise PermanentError(f"{VALIDATED_AT_KEY} 有不合法的時間字串") from error
