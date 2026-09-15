"""`TKB_FAULT` 故障注入切點（設計 §14.2 的失敗復原驗收）。

**owner 是 Phase 59**；Phase 41 只建立這支檔的第一片，好讓雲端驗收有一個定案的切點清單
與開關語意可以引用。Phase 41 **不在** `content.py`／`publishing.py`／`ingress.py` 插入
任何 `maybe_fail` 呼叫——那五處插入、`check_asl_document` 與 `resume_publish` 都是
Phase 59 的 Task（00A 第 1230 列）。

```text
TKB_FAULT=<切點名稱>   一次只注入一個切點
TKB_ENV=prod           一律不注入（正式環境的保險，比對任何切點之前就先擋）
```

`InjectedFault` 繼承 `TransientError`，所以本機與 moto 的復原測試會走完「重試 -> Catch」
這條路。**但在雲端不會**：Step Functions 的 `ErrorEquals` 比對的是 Lambda runtime 回報的
類別名字串（`InjectedFault`），不認繼承，所以第一條 retrier（`["TransientError"]`）不會
命中。要在真實 AWS 上實證重試，注入點必須丟 `TransientError` **本身**——Phase 41 的
`pipelines.common.maybe_fail_task`（`TKB_FAULT_TASK`）就是為此存在的另一個開關。
"""

import os
from collections.abc import Mapping

from training_kb.errors import PermanentError, TransientError

FAULT_POINTS: tuple[str, ...] = (
    "s3_after_md", "ddb_after_version", "publish_before_transact",
    "publish_after_transact_before_site", "start_execution")
"""五個切點，一個不多一個不少（00A 第 1230 列）。

`s3_after_md`／`ddb_after_version` 在 `content.py`、`publish_before_transact`／
`publish_after_transact_before_site` 在 `publishing.py`、`start_execution` 在
`ingress.py`；每個名稱在對應檔案裡恰好出現一次（Phase 59 的契約測試）。
"""

FAULT_ENV = "TKB_FAULT"
"""切點開關；**不是** `Settings` 欄位，`load_settings` 不讀它（00A §3.5）。"""

ENV_NAME_ENV = "TKB_ENV"
PRODUCTION = "prod"


class InjectedFault(TransientError):
    """人為注入的暫時性失敗；只有 `maybe_fail` 會丟它。"""


def active_fault(env: Mapping[str, str] | None = None) -> str | None:
    """目前開著的切點名稱；沒開、或 `TKB_ENV=prod` 時回 `None`。

    打錯的切點名稱一律 `PermanentError`：靜靜當成「沒有注入」會讓一次復原演練白跑，
    而且事後看不出是開關沒生效還是流程真的沒失敗。
    """
    values: Mapping[str, str] = os.environ if env is None else env
    if values.get(ENV_NAME_ENV) == PRODUCTION:
        return None
    point = values.get(FAULT_ENV, "")
    if not point:
        return None
    if point not in FAULT_POINTS:
        raise PermanentError(f"未知的故障切點：{point}")
    return point


def maybe_fail(point: str, env: Mapping[str, str] | None = None) -> None:
    """切點命中就丟 `InjectedFault`，否則什麼都不做。

    `point` 不在 `FAULT_POINTS` 裡代表呼叫端打錯名字（程式錯誤），當場 `PermanentError`。
    """
    if point not in FAULT_POINTS:
        raise PermanentError(f"未知的故障切點：{point}")
    if active_fault(env) == point:
        raise InjectedFault(f"注入故障切點：{point}")
