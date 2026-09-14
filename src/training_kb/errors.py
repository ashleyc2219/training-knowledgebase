from collections.abc import Iterable


class TransientError(Exception):
    """暫時性服務故障，重送有機會成功；由 ASL Task 的 Retry 處理。"""


class PermanentError(Exception):
    """確定不合法或不會成功；由 ASL 的 Catch 導向失敗終點。"""


class ContentError(PermanentError):
    """內容不合規：段落缺失、步驟編號不連續、每步不是恰一個 Feature、未命中步驟被改動。"""


class CoordinationError(Exception):
    """操作紀錄不一致：找不到 operation、狀態轉移不合法、同 operation 取到不同版號。"""


class PublishError(Exception):
    """發布前提不成立或中途失敗：版本不完整、current_version 已被改、bytes 不同。"""


class IngressError(PermanentError):
    """接入資料缺欄位或值不合法；fields 是不合法欄位名的 tuple。"""

    def __init__(self, message: str, fields: Iterable[str] = ()) -> None:
        super().__init__(message)
        self.message = message
        self.fields: tuple[str, ...] = tuple(sorted(set(fields)))


class ObjectAlreadyExists(PermanentError):
    """`put_object(..., if_none_match=True)` 撞到同一個 key（S3 412）。

    另開一個類別而不是共用 `PermanentError`，是為了讓呼叫端用**型別**分辨
    「同一次操作重送」（412，核對 bytes 後視為已完成）與真正的內容衝突；
    訊息字串不是契約。409（併發刪除）另外轉 `TransientError` 交 ASL Retry。
    """
