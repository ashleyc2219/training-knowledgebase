"""統一錯誤型別。

規格（`docs/spec/features/*.feature`）裡所有失敗情境都寫成 `Then 操作失敗`，
程式層一律抛 `OperationFailed`，不另發明錯誤碼表（`docs/design/showme.md` §14）。
"""


class OperationFailed(Exception):
    """操作失敗：規格 `Then 操作失敗` 的唯一對應例外。"""
