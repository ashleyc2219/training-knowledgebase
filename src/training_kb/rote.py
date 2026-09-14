"""Rote：接入層的結構簽名、兩層命中、PROC 生命週期與三層 normalize。

owner 是 Phase 33；P34（兩層命中與候選排序）、P35（PROC 生命週期）、P36（記錄步驟的
驗證與執行）、P37（三層 normalize 與成功提交）之後會在同一支檔案往下追加。區塊順序固定為：

1. 來源脈絡與白名單（P33）—— `RawEvent`、`HEADER_PREFIXES`、`STABLE_KEYS`、`event_stable_keys`。
2. 結構簽名（P33）—— `signature_shape`、`structure_signature`。
3. 兩層命中與候選排序（P34 追加）。
4. PROC 生命週期（P35 追加）。
5. 記錄步驟的驗證與執行（P36 追加）。
6. 三層 normalize 與成功提交（P37 追加）。

`domain`／`adapter` 一律來自可信入口設定，**不得從 payload 反推**（00A §6.8、D-60）；
GitHub 路徑必須先通過 Phase 30 的 HMAC 驗簽。簽名只是結構索引，不是身分驗證。
"""

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

from training_kb.errors import PermanentError
from training_kb.models import ProcStatus, ProvenWorkflow
from training_kb.operations import OperationCoordinator
from training_kb.pipelines.common import JSONValue
from training_kb.repository import Repository

# --- 1. 來源脈絡與白名單（Phase 33）-------------------------------------------

HEADER_PREFIXES: tuple[str, ...] = ("x-github-", "x-discord-", "x-zendesk-")
"""哪些 header **名稱**有資格進簽名的前綴白名單（設計 §7.2）；只取名稱，永遠不取值。"""

STABLE_KEYS: Mapping[tuple[str, str], frozenset[str]] = {
    # 逐條抄自 Phase 13 的核定紀錄（approved_by 非空的列）。正式程式不讀 tests/ 路徑，
    # 抄錯由 tests/integration/test_o6_stable_keys.py 的逐列比對擋下來。
    ("github.com", "issues"): frozenset({"action", "issue", "repository", "sender"}),
    # ("github.com", "pull_request")：等 O6 核定後才加入，核定前保持 blocked。
}
"""每個已核定 `(domain, event_type)` 的固定必備最上層 key 清單（決策 F02）。"""


@dataclass(frozen=True)
class RawEvent:
    """驗簽後組出來的原始事件：可信來源脈絡 + 原樣 headers 與 payload。"""

    domain: str
    adapter: str
    event_type: str
    headers: Mapping[str, str]
    payload: Mapping[str, JSONValue]


def event_stable_keys(event: RawEvent) -> frozenset[str]:
    """回「核定清單與實際出現的最上層 key 的交集」。

    取交集而不是整份核定清單：缺一個核定 key 屬於**結構不同**，必須得到不同簽名，
    Phase 34 的 Jaccard 也才有比較對象。未核定的來源一律 `PermanentError`，
    不回 fallback 簽名（O6 gate）。
    """
    if not event.domain or not event.adapter:
        raise PermanentError("RawEvent 缺少可信入口設定的 domain 或 adapter")
    allowed = STABLE_KEYS.get((event.domain, event.event_type))
    if allowed is None:
        raise PermanentError(
            f"({event.domain}, {event.event_type}) 尚無核定 STABLE_KEYS；O6 未核對前為 blocked"
        )
    return frozenset(allowed & event.payload.keys())


# --- 2. 結構簽名（Phase 33）---------------------------------------------------


def signature_shape(event: RawEvent) -> dict[str, object]:
    """簽名素材：只有 domain、白名單 header **名稱**與已核定的最上層 key **名稱**。

    序列化結果裡搜不到任何事件值（ID、標題、時間、header 值都不在）。header 名稱一律
    小寫、去重、排序；`adapter` 刻意不進 shape，它存在 `ProvenWorkflow.adapter`（D-09）。
    """
    headers = sorted(
        {name.lower() for name in event.headers if name.lower().startswith(HEADER_PREFIXES)}
    )
    return {"domain": event.domain, "headers": headers, "keys": sorted(event_stable_keys(event))}


def structure_signature(event: RawEvent) -> str:
    """shape 的 UTF-8 JSON 取 SHA-1 前 16 個十六進位字元（設計 §7.2 逐字公式）。

    **不得加 `separators`**：`json.dumps` 的預設分隔符是 `", "` 與 `": "`，改了 bytes 就不同，
    兩個實作會算出對不起來的簽名。這個 SHA-1 只是結構索引，不是驗簽，也不得用來判斷
    請求是否可信；GitHub 路徑的安全邊界在 Phase 30 的 HMAC。
    """
    shape = signature_shape(event)
    return hashlib.sha1(json.dumps(shape, sort_keys=True).encode()).hexdigest()[:16]


# --- 3. 兩層命中與候選排序（Phase 34 追加）------------------------------------

JACCARD_THRESHOLD = 0.8
"""第二層欄位重疊度的下限（設計 §7.2）；用 `>=` 比較，`4/5` 命中、`3/4` 淘汰。"""

PROC_MIN_SUCCESS = 3
"""可重放所需的最少完整成功次數（設計 §7.2、決策 F03）。

Phase 34 首建（00A §5.4），Phase 35 只 `import` 這個名字、不為同一個數字另取第二個名稱。
"""


def jaccard(left: frozenset[str], right: frozenset[str]) -> float:
    """兩組 key 名稱的交集數除以聯集數（設計 §7.2）。

    空聯集回 `0.0` 而不是數學慣例的 `1.0`：設計 §7.2 明說「空集合不當成命中」，
    回 `1.0` 會讓兩個沒有任何欄位的事件互相命中。
    """
    union = left | right
    if not union:
        return 0.0
    return len(left & right) / len(union)


def replayable(proc: ProvenWorkflow) -> bool:
    """可重放的兩個硬條件：`status=active` 且 `success_count >= PROC_MIN_SUCCESS`。

    兩層共用這一份判斷（決策 F03）。`ProcStatus` 只有 `active`／`retired`，
    「還沒累積到三次」是用 `success_count` 表達，不是另外加一個狀態。
    """
    return proc.status == ProcStatus.ACTIVE and proc.success_count >= PROC_MIN_SUCCESS


def _order_key(scored: tuple[float, ProvenWorkflow]) -> tuple[float, float, str]:
    """決策 F04 的三段排序鍵：分數最高 → `last_used` 最新 → signature 升序。

    第三個鍵不是裝飾：少了它，同分同時間的兩個候選就由 Scan 回來的順序決定勝負，
    同一份資料換個排列可能得到不同結果。`last_used` 由 Phase 04 保證必填且帶時區，
    所以可以直接取 `.timestamp()`；本 Phase 不補值、不把 naive 時間當 UTC。
    """
    score, proc = scored
    return (-score, -proc.last_used.timestamp(), proc.signature)


def pick_layer2(event: RawEvent, candidates: Sequence[ProvenWorkflow]) -> ProvenWorkflow | None:
    """第二層：同 domain＋adapter 的可重放候選裡，Jaccard 最高且過門檻的那一個。

    即使 `list_procs` 已依 domain＋adapter 查詢，這裡仍再過濾一次——這個純函式要能
    單獨測試，也不該倚賴查詢層是否寫對條件（範圍定義見決策 D19）。沒有合格候選回 `None`。
    """
    keys = event_stable_keys(event)
    hits = [
        (jaccard(keys, frozenset(proc.keys)), proc)
        for proc in candidates
        if replayable(proc) and proc.domain == event.domain and proc.adapter == event.adapter
    ]
    hits = [pair for pair in hits if pair[0] >= JACCARD_THRESHOLD]
    return min(hits, key=_order_key)[1] if hits else None


def find_replayable(event: RawEvent, signature: str, *,
                    repository: Repository) -> ProvenWorkflow | None:
    """兩層的唯一順序：Layer 1 精確比對主鍵，不成才查同範圍候選交 Layer 2。

    exact item 存在但 retired 或成功次數不足時**不能直接放棄**：設計 §7.2 的第二層條件是
    「第一層未命中」，而不可重放就是未命中（決策 D20、Rule 20）。那筆 exact PROC 會在
    Layer 2 被同一個 `replayable` 濾掉，不需要另外排除它。

    全系統只有這一份順序：Phase 37 的 `Rote._pick_proc` 直接 import 本函式（00A §6.8），
    不得自己再抄一次這三行。整條路徑只讀不寫，也沒有任何模型呼叫，所以簽名裡沒有 writer。
    """
    exact = repository.get_proc(signature)
    if exact is not None and replayable(exact):
        return exact
    return pick_layer2(event, repository.list_procs(event.domain, event.adapter))


# --- 4. PROC 生命週期（Phase 35 追加）-----------------------------------------

PROC_MAX_CONSECUTIVE_FAIL = 3
"""連續重放失敗幾次就退役（決策 D20）。

與重放門檻 `PROC_MIN_SUCCESS` 剛好同值但意義不同：一個數「累積幾次不同事件成功」、
一個數「連續幾次重放失敗」，所以是兩個常數名（00A §5.4），不得互相替代。
"""


def _reject_retired(proc: ProvenWorkflow) -> None:
    """retired 的最後一道防線：默默覆寫等於自動復活（決策 F53）。

    正常路徑上 Phase 37 的 `commit_success` 就會先擋掉 retired signature，
    這裡丟 `PermanentError` 是為了讓「繞過去呼叫」變成看得見的錯誤而不是靜默的計數重置。
    """
    if proc.status == ProcStatus.RETIRED:
        raise PermanentError(f"PROC {proc.signature} 已 retired，需人工核定新序列才能重置（F53）")


def on_new_success(proc: ProvenWorkflow, operation_id: str,
                   operations: OperationCoordinator, now: datetime) -> ProvenWorkflow:
    """一次**新事件**的完整成功：`success_count + 1` 並把 `last_used` 推到 `now`。

    「算不算新樣本」完全由 Phase 10 的 `record_proc_sample` 決定，不是由呼叫次數決定：
    同一個 operation 重送會拿到 `False`，這時原樣回傳（決策 F05）。
    **不清 `fail_count`**——被 Agent 救回的那一次重放仍然是一次失敗（設計 §7.2 只讓
    `on_replay_success` 歸零）。
    """
    _reject_retired(proc)
    if not operations.record_proc_sample(operation_id, proc.signature):
        return proc
    return proc.model_copy(update={"success_count": proc.success_count + 1, "last_used": now})


def on_replay_success(proc: ProvenWorkflow, now: datetime) -> ProvenWorkflow:
    """一次重放成功：連敗歸零並更新 `last_used`，**不加 `success_count`**。

    重放走的是同一份已驗證序列，不是新的驗證樣本（決策 F05）；只有 `on_new_success`
    才能讓計數往前。`last_used` 更新是決策 F04 要的「最近一次成功使用」。
    """
    _reject_retired(proc)
    return proc.model_copy(update={"fail_count": 0, "last_used": now})


def on_replay_failure(proc: ProvenWorkflow, now: datetime) -> ProvenWorkflow:
    """一次重放失敗：`fail_count + 1`，累到 `PROC_MAX_CONSECUTIVE_FAIL` 就 retired。

    `fail_count` 是**連續**失敗次數（決策 D20），中間出現一次 `on_replay_success` 就歸零，
    不是歷史總失敗數。`now` 在簽名裡只為了三個轉移函式的形狀一致，**實作刻意不使用它**：
    失敗也更新 `last_used` 會讓連敗中的 PROC 在 Phase 34 的平手排序裡排到最前面（F04）。
    """
    _reject_retired(proc)
    failures = proc.fail_count + 1
    status = ProcStatus.RETIRED if failures >= PROC_MAX_CONSECUTIVE_FAIL else proc.status
    return proc.model_copy(update={"fail_count": failures, "status": status})


# --- 5. 記錄步驟的驗證與執行（Phase 36 追加）----------------------------------
# --- 6. 三層 normalize 與成功提交（Phase 37 追加）-----------------------------
