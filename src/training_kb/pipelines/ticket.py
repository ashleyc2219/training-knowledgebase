"""Ticket Analysis 的業務函式（設計 §7.3、§9.1、§14.2、§14.3）。

模型只出現在「文字 -> 向量」這一步：要不要呼叫模型、屬於哪一群、新群叫什麼名字，
全部由程式決定，所以同一筆 Ticket 重送會得到一樣的結果。

門檻只有一份：`0.85` 的唯一來源是 `Thresholds.cosine_match`，本檔的
`CLUSTER_COSINE_THRESHOLD` 只是它的別名（00A §5.4、D-35），模組裡不得再出現第二份字面值。

本檔由 Phase 38 建立，Phase 39（recurring 與 gap 命名）、Phase 40（CREATE／KEEP）、
Phase 41（Task 包裝與 handler）會繼續在同一支檔案上追加。
"""

from training_kb.config import Thresholds
from training_kb.keys import ticket_pk
from training_kb.models import Ticket
from training_kb.repository import Repository
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
