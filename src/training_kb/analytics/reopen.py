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

from datetime import UTC, datetime, timedelta


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
