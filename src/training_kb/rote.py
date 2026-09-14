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

from collections.abc import Mapping
from dataclasses import dataclass

from training_kb.errors import PermanentError
from training_kb.pipelines.common import JSONValue

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


def structure_signature(event: RawEvent) -> str:
    event_stable_keys(event)
    return ""  # Task 2 換成主來源的雜湊公式


# --- 3. 兩層命中與候選排序（Phase 34 追加）------------------------------------
# --- 4. PROC 生命週期（Phase 35 追加）-----------------------------------------
# --- 5. 記錄步驟的驗證與執行（Phase 36 追加）----------------------------------
# --- 6. 三層 normalize 與成功提交（Phase 37 追加）-----------------------------
