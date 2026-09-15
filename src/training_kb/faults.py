"""`TKB_FAULT` 故障注入切點（設計 §14.2 的失敗復原驗收）。

**owner 是 Phase 59**；Phase 41 只建立這支檔的第一片，好讓雲端驗收有一個定案的切點清單
與開關語意可以引用。Phase 41 **不在** `content.py`／`publishing.py`／`ingress.py` 插入
任何 `maybe_fail` 呼叫——那五處插入、`check_asl_document` 與 `resume_publish` 都是
Phase 59 的 Task（00A 第 1230 列）。

```text
TKB_FAULT=<切點名稱>   一次只注入一個切點
TKB_ENV=prod           一律不注入（正式環境的保險，比對任何切點之前就先擋）
```

**注入一律丟 `TransientError` 本身**（controller 2026-09-14 裁決）。Phase 41／52 在真實
AWS 實證過：Step Functions 的 `ErrorEquals` 比對的是 Lambda runtime 回報的**類別名字串**、
不認繼承，所以子類（原本的 `InjectedFault`）不會命中第一條 retrier `["TransientError"]`。
`InjectedFault` 因此降級成**相容別名**（00A 第 1230 列的名稱不變，仍可 `except InjectedFault`
或 `pytest.raises(InjectedFault)`），但沒有任何地方用它建立例外實例。同一條理由也是 Phase 41
`pipelines.common.maybe_fail_task`（`TKB_FAULT_TASK`）存在的原因：那支是 Lambda **Task 層**
的開關，本模組這五個是 library 路徑上的切點，兩者互補。
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


InjectedFault = TransientError
"""人為注入的暫時性失敗；**就是 `TransientError` 本身**的相容別名（00A 第 1230 列）。

原本它是 `TransientError` 的子類，但雲端的 `errorType` 會變成 `InjectedFault` 這個字串，
ASL 的 `ErrorEquals: ["TransientError"]` 因此比不中（Phase 41 §9 第 3 點的實證）。改成別名
之後，注入的失敗在雲端與本機都是同一個類別名，走完 Retry 才進 Catch；呼叫端既有的
`except InjectedFault` 仍然成立，因為兩個名字指的是同一個類別。
"""


def is_production(env: Mapping[str, str] | None = None) -> bool:
    """`TKB_ENV` 是不是正式環境；**所有故障注入開關共用這一個答案**。

    寬鬆比對：`TKB_ENV=" Prod"`／`"PROD"` 也算正式環境。正式環境的保險寧可誤擋，
    不可因為大小寫或前後空白就漏擋（Phase 59 review Minor）。

    抽成公開函式是修正波的必修項（final review C#3）：`pipelines.common.maybe_fail_task`
    原本自己寫一次 `== PRODUCTION` 的精確比對，與本檔的寬鬆比對分岔——同一份環境變數
    會讓 library 切點不注入、Task 切點卻注入，正式環境的保險等於破了一個洞。
    """
    values: Mapping[str, str] = os.environ if env is None else env
    return values.get(ENV_NAME_ENV, "").strip().lower() == PRODUCTION


def active_fault(env: Mapping[str, str] | None = None) -> str | None:
    """目前開著的切點名稱；沒開、或 `TKB_ENV=prod` 時回 `None`。

    打錯的切點名稱一律 `PermanentError`：靜靜當成「沒有注入」會讓一次復原演練白跑，
    而且事後看不出是開關沒生效還是流程真的沒失敗。
    """
    values: Mapping[str, str] = os.environ if env is None else env
    if is_production(values):
        return None
    point = values.get(FAULT_ENV, "")
    if not point:
        return None
    if point not in FAULT_POINTS:
        raise PermanentError(f"未知的故障切點：{point}")
    return point


def maybe_fail(point: str, env: Mapping[str, str] | None = None) -> None:
    """切點命中就丟 `TransientError`，否則什麼都不做。

    `point` 不在 `FAULT_POINTS` 裡代表呼叫端打錯名字（程式錯誤），當場 `PermanentError`。

    丟的是 `TransientError` **本身**而不是子類：雲端的 `errorType` 就是這個類別名，
    ASL 第一條 retrier `ErrorEquals: ["TransientError"]` 才會命中（見模組說明）。
    訊息帶切點名稱，`describe-execution` 的 `cause` 裡看得出是哪一個切點。
    """
    if point not in FAULT_POINTS:
        raise PermanentError(f"未知的故障切點：{point}")
    if active_fault(env) == point:
        raise TransientError(f"注入故障切點：{point}")
