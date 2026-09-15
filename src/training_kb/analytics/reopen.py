"""同題重開票指標（Phase 54）：O4 的十四天窗口與分子／分母去重。

兩個純函式，輸入已經取好的 `TutorialView` 與 `Ticket`，輸出可重算的 `ReopenStats`：
不讀 DynamoDB、不呼叫模型。讀取由 `Repository.list_views_of_version`／`list_tickets`
負責（它們已讀完所有分頁，否則分母會被低估）。

**O4 尚未核定。** 設計 §18 O4 明寫「ERM 明留窗口端點與時間編碼未定義；本文件建議 UTC、
窗口 `[p, p + 14 天)`」。本計畫（2026-09-14）依這個建議實作，並把 `timedelta(days=days)`
收斂到 `reopen_window` **一處**：核定若改成右端包含，只要改這裡與
`tests/unit/test_reopen_metrics.py` 的兩個端點測試。核定前只能說「依 §12.1 建議實作且
可被測試重現」，不得宣稱窗口定義已定案。

工單 recurring 的「UTC 當日加前十三日」（Phase 39）是**另一個**十四天，兩者不可互換。
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from training_kb.models import Ticket, TutorialView


def reopen_window(published_at: datetime, days: int = 14) -> tuple[datetime, datetime]:
    """O4 待核定：本計畫依設計 §12.1 建議採 UTC 的 `[p, p + days)`。

    只回一組端點，不判斷成員資格——成員資格由 `reopen_stats` 用 `start <= ts < end`
    表達，右端不含由 `ticket.ts == p + 14 天` 的測試釘住。

    naive datetime 直接拒絕：沒有偏移量就無從換算，猜成 UTC 會讓窗口靜靜地平移。
    """
    if published_at.tzinfo is None or published_at.utcoffset() is None:
        raise ValueError("published_at 必須是 timezone-aware 的 UTC 時間")
    start = published_at.astimezone(UTC)
    return start, start + timedelta(days=days)


@dataclass(frozen=True)
class ReopenStats:
    """一版的重開票指標；四個欄位分開存在，不能互相取代（設計 §12.1）。

    `count` 是不同 **Ticket ID** 數（筆數，可以大於人數，**不是**比例：設計 §11.3 的
    7 與 2 是筆數，70% 與 20% 是補上分母後才成立的比率）、`reopen_users` 是分子
    （不同使用者）、`viewers` 是分母（窗口內的不同瀏覽者）、`rate` 在 `viewers == 0`
    時是 `None`（畫面顯示「N/A／樣本不足」，**不是 0%**：回 `0.0` 會讓 Phase 55 誤判
    「rate 嚴格下降」而啟用規則，F42）。
    """

    count: int
    reopen_users: int
    viewers: int
    rate: float | None


def reopen_stats(views: Sequence[TutorialView], tickets: Sequence[Ticket], *,
                 cluster_id: str, published_at: datetime) -> ReopenStats:
    """同題重開票：看過這一版之後又在窗口內開同群工單的使用者比例（F41）。

    分母只能來自 `TUTORIAL_VIEW`——簽名因此**只收 `views`**，不收 `Feedback`：留過回饋
    不是「看過教學」的證據（設計 §12.1 明文禁止代用）。呼叫端要先用
    `list_views_of_version(version_id)` 篩出本版的 View 才交進來。

    四道過濾與兩種去重：

    1. View 落在窗口內才算分母；同一人多筆取**最早**一筆（只要曾經先看過就算），
       所以重複瀏覽不會把分母灌大。
    2. Ticket 要 `cluster_id` 相同（D-29：同題以首版 `gap:<cluster_id>` 固定，不比標題
       文字）、落在窗口內、`author` 在分母集合裡，且**最早**的 view 嚴格早於開票時間。
       `view.ts < ticket.ts` 是**嚴格**小於：同一刻無法證明先後。
    3. `count` 以 Ticket ID 去重、`reopen_users` 以 author 去重（D-23：跨來源共用穩定
       使用者 ID，比的是 ID 不是顯示名稱）。
    """
    start, end = reopen_window(published_at)
    first_view: dict[str, datetime] = {}
    for item in views:
        if start <= item.ts < end:
            seen = first_view.get(item.user)
            if seen is None or item.ts < seen:
                first_view[item.user] = item.ts
    hits = [row for row in tickets
            if row.cluster_id == cluster_id and start <= row.ts < end
            and row.author in first_view and first_view[row.author] < row.ts]
    viewers = len(first_view)
    users = {row.author for row in hits}
    rate = len(users) / viewers if viewers else None
    return ReopenStats(len({row.id for row in hits}), len(users), viewers, rate)
