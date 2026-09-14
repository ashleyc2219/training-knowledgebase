"""Ticket Analysis 的業務函式（設計 §7.3、§9.1、§14.2、§14.3）。

模型只出現在「文字 -> 向量」這一步：要不要呼叫模型、屬於哪一群、新群叫什麼名字，
全部由程式決定，所以同一筆 Ticket 重送會得到一樣的結果。

門檻只有一份：`0.85` 的唯一來源是 `Thresholds.cosine_match`，本檔的
`CLUSTER_COSINE_THRESHOLD` 只是它的別名（00A §5.4、D-35），模組裡不得再出現第二份字面值。

本檔由 Phase 38 建立，Phase 39（recurring 與 gap 命名）、Phase 40（CREATE／KEEP）、
Phase 41（Task 包裝與 handler）會繼續在同一支檔案上追加。
"""

from collections.abc import Iterable
from datetime import date, timedelta

from training_kb.clock import utc_date
from training_kb.config import Thresholds
from training_kb.errors import PermanentError
from training_kb.keys import ticket_pk
from training_kb.models import Ticket
from training_kb.repository import Repository
from training_kb.vectors import centroid, cosine
from training_kb.writing.client import Writer

CLUSTER_COSINE_THRESHOLD = Thresholds().cosine_match
"""同群判定線，`Thresholds.cosine_match` 的別名；要調門檻只改 P02 那個欄位的預設值。"""


# --- 1. Embedding（Task：ensure_embedding） ---------------------------------


def ensure_embedding(ticket: Ticket, *, writer: Writer, repository: Repository,
                     operation_id: str) -> Ticket:
    """缺向量才呼叫 Titan，叫完就寫回；已經有向量就原樣回傳（設計 §14.2）。

    順序不能換：**先一致讀取既有 TICKET**，再決定要不要呼叫模型。只看傳入物件會讓
    重送每次都多花一次 Bedrock 呼叫，而重送是 Step Functions 的常態。

    維度、NaN、`bool` 這些回應有效性由 Phase 16 的 `Writer.embed` 檢查並丟
    `PermanentError`；`TransientError` 則交給 ASL 的 Retry。兩者都**原樣往上拋**，
    函式內不自行重試、失敗時一個字都不寫回。

    寫回走 `put_meta(create_only=False)`：TICKET 已由接入層建立，這是 Phase 06 受控覆寫
    路徑（`_revision` 的 compare-and-swap）。版本過期時它丟 `CoordinationError`，本函式
    **不吞不重試**，由上層依 O2 語意重讀重算。
    """
    stored = repository.get_meta(ticket_pk(ticket.id), Ticket, consistent=True)
    current = stored if stored is not None else ticket
    if current.embedding:
        return current
    # node 名固定 "ticket-embedding"：人工驗收靠它數 `CallTrace` 裡 kind=embedding 的
    # attempt。00A §6.9 沒有把它列成 P38 的公開名稱，所以不另外宣告常數讓 P39／P41 有機會
    # 寫出第二份不同的字串。
    vector = writer.embed(current.text, operation_id=operation_id, node="ticket-embedding")
    updated = current.model_copy(update={"embedding": vector})
    repository.put_meta(updated, create_only=False)
    return updated


# --- 2. 分群（Task：assign_cluster） ----------------------------------------


def assign_cluster(ticket: Ticket, *, repository: Repository) -> str:
    """回傳這則 Ticket 該屬於哪一個 `cluster_id`；**只做判斷，不寫資料庫**。

    把 `cluster_id` 寫回 TICKET 是 Phase 41 `assign_cluster` Task 的責任（該 Task 必須
    先一致讀取 TICKET 再呼叫這裡）。

    已經有 `cluster_id` 就原樣回傳：重送沿用同一群（設計 §14.2）。否則讀同專案的全部
    Ticket（`list_tickets` 走 Phase 08 的 `scan_entity("TICKET")`，`meta_only=True` 讓
    Phase 40 之後掛在 `TICKET#<id>` 上的 `ASKS_ABOUT#` 邊不會被誤算成工單），依
    `cluster_id` 分組、每組算**群中心**再比 cosine。

    三條規則讓重跑結果固定：
    1. 一律拿 `centroid` 比，即使群裡只有一筆，也不拿「第一筆」當代表（F10）。
    2. 排序鍵是 `(-分數, cluster_id)`：同分取最小 `cluster_id`，不依賴掃描或 dict 順序。
    3. 自己不當自己的群中心，但自己的群編號仍算既有編號。

    沒有任何群達到 `CLUSTER_COSINE_THRESHOLD` 就開新群。編號唯一性只在同一個
    `project_id` 內成立；跨專案併發的保證屬於 O2，未通過前不得宣稱無競態。
    """
    if ticket.cluster_id:
        return ticket.cluster_id
    if not ticket.embedding:
        raise PermanentError("assign_cluster 需要已保存的 embedding")
    known: set[str] = set()
    groups: dict[str, list[list[float]]] = {}
    for other in repository.list_tickets(ticket.project_id):
        if not other.cluster_id:
            continue
        known.add(other.cluster_id)
        if other.id != ticket.id and other.embedding:
            groups.setdefault(other.cluster_id, []).append(other.embedding)
    scored = [(cosine(ticket.embedding, centroid(rows)), cid) for cid, rows in groups.items()]
    good = sorted((row for row in scored if row[0] >= CLUSTER_COSINE_THRESHOLD),
                  key=lambda row: (-row[0], row[1]))
    return good[0][1] if good else new_cluster_id(known)


def new_cluster_id(existing: Iterable[str]) -> str:
    """既有 `c<數字>` 的最大值加一；完全沒有既有群時回 `c1`。

    只認得 `c<數字>` 這個形狀，其他字串不影響編號。MVP 不合群也不重編號，既有
    `cluster_id` 永遠保留，`Tutorial.cluster_id` 才追溯得回來（設計 §7.3、D29）。
    最後那道撞號檢查是防守用的：`max + 1` 在結構上不會撞到既有編號，真的撞到代表
    上游資料或這段邏輯壞了，**明確失敗**而不是靜默換一個號碼。
    """
    known = set(existing)
    numbers = [int(value[1:]) for value in known if value[:1] == "c" and value[1:].isdigit()]
    candidate = f"c{max(numbers) + 1 if numbers else 1}"
    if candidate in known:
        raise PermanentError(f"新群編號 {candidate} 已存在")
    return candidate


# --- 3. Recurring 判定（Task：evaluate_recurring） ---------------------------

RECURRING_DAYS = 14
"""窗口長度：當日加前 13 個 UTC **日期**，共十四個。

`Thresholds` 刻意**沒有**對應欄位（00A §5.4），所以這份 `14` 就是全套唯一一份；
不得自創 `Thresholds.recurring_days` 這種新欄位名（D-35）。
"""

RECURRING_MIN_TICKETS = Thresholds().recurring_tickets
"""recurring 門檻，`Thresholds.recurring_tickets` 的別名；模組裡不得再出現第二份 `5`。"""


def recurring_window(anchor: date, days: int = RECURRING_DAYS) -> frozenset[date]:
    """回傳 anchor 當日與前 `days - 1` 個 UTC 日期組成的**日期集合**（設計 §7.3、F11）。

    是「日期集合」而不是「時間區間」：同一個 UTC 日不管幾點都落在同一個桶裡，所以
    `2026-08-31T00:00:00Z` 在窗口內、`2026-08-30T23:59:59Z` 在窗口外。用
    `now - 14 days` 這種區間算法會讓同一批輸入在不同時刻重跑得到不同答案。

    `days < 1` 是呼叫端的錯，不是資料問題：窗口至少要含 anchor 當日本身，
    空窗口會讓任何一群都算不出 recurring 而**安靜地**跳過命名。
    """
    if days < 1:
        raise PermanentError(f"recurring 窗口天數至少為 1，收到 {days}")
    return frozenset(anchor - timedelta(days=offset) for offset in range(days))


def is_recurring(ticket: Ticket, *, repository: Repository) -> bool:
    """同群工單在 anchor 的十四天窗口內是否累積到 `RECURRING_MIN_TICKETS` 筆（設計 §7.3）。

    anchor 固定是**觸發本輪的那筆工單的 `ts`**，不是執行當下的時間：同一批輸入
    什麼時候重跑都得到一樣的答案（設計 §14.2）。`Ticket.ts` 在 Phase 04 已經是
    `datetime`，所以直接 `utc_date(...)`，不再套一層 `parse_iso`（那是給字串用的）。

    固定順序：沒有 `cluster_id` -> `PermanentError`（Phase 38 還沒跑完，這是流程順序
    錯，不是「不算 recurring」）；否則同專案的 Ticket 只留同群、且日期落在窗口內的，
    依 `Ticket.id` 去重。同一天內的多筆各算一筆——日期只拿來過濾，不拿來去重。

    anchor 自己一定算一筆：它的日期必然在窗口內，而 Phase 41 的 Task 順序容許
    `cluster_id` 還沒寫回表（`assign_cluster` 只判斷不寫入），掃描不一定看得到它。
    """
    if not ticket.cluster_id:
        raise PermanentError(f"工單 {ticket.id} 尚未分群，不能判斷 recurring")
    window = recurring_window(utc_date(ticket.ts))
    seen = {
        other.id
        for other in repository.list_tickets(ticket.project_id)
        if other.cluster_id == ticket.cluster_id and utc_date(other.ts) in window
    }
    seen.add(ticket.id)
    return len(seen) >= RECURRING_MIN_TICKETS
