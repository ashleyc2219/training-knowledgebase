"""Adapters：可重放的安全 JSONPath 與 Training KB 明列的八個接入工具白名單。

owner 是 Phase 36。區塊順序固定為：

1. 安全 JSONPath（P36）—— `PATH_ROOTS`、`resolve_jsonpath`。
2. 工具白名單（P36）—— `TOOL_NAMES`、`FINAL_TOOL`、`PARSER_KIND`、`ToolRegistry`。
3. 八個工具（P36）—— 五個 parser、兩個 normalizer 與 `validate`。

相依方向是**單向**的：`rote.py` import 本檔，本檔**不得** import `rote.py`
（00A §6.8），否則會循環 import。`JSONValue` 只從 Phase 29 的 `pipelines/common.py`
import，不另寫第二份定義（00A D-31）。

PROC 保存的是 path 字串，不保存 Ticket 文字、使用者、ID 或任何事件真值（設計 §7.2）。
"""

import re
from collections.abc import Mapping

from training_kb.errors import PermanentError
from training_kb.pipelines.common import JSONValue

# --- 1. 安全 JSONPath（Phase 36）---------------------------------------------

PATH_ROOTS = ("$event", "$steps")
"""JSONPath 只准用的兩個開頭：本次原始事件與前面每一步的輸出清單（00A §6.8）。"""

_TOKEN = re.compile(r"\.([A-Za-z_][A-Za-z0-9_]*)|\[(0|[1-9][0-9]*)\]")
"""唯一合法的兩種 token：點號後的欄位名，或中括號內的非負十進位整數。

刻意不用通用 JSONPath 函式庫：那些函式庫支援 `..`、`[*]`、filter 與函式呼叫，
一個沒擋住的運算式就能把整包事件（含 secret）撈出來當工具參數（設計 §7.2）。
"""


def resolve_jsonpath(root: JSONValue, path: str) -> JSONValue:
    """依安全子集合的 path 取值；語法不合、欄位不存在或 index 超界一律 `PermanentError`。

    根節點只有 `$event` 與 `$steps`，而且後面**至少要有一個 token**：光是 `$event`
    等於把整包事件當參數，合法的最短形式是 `$steps[0]`。缺欄位**不回 `None`**——
    回 `None` 會讓「欄位不存在」與「值就是 null」變成同一件事，重放時悄悄換掉語意。

    只讀不寫：回傳的是 `root` 裡的同一個物件，不做複製也不修改 `root`。
    """
    prefix = next((name for name in PATH_ROOTS if path.startswith(name)), None)
    if prefix is None:
        raise PermanentError(f"JSONPath 根節點不在白名單: {path!r}")
    if not isinstance(root, Mapping) or prefix[1:] not in root:
        raise PermanentError(f"JSONPath 根節點不存在: {prefix}")
    position = len(prefix)
    if position == len(path):
        raise PermanentError(f"JSONPath 必須指到具體欄位或 index: {path}")
    value: JSONValue = root[prefix[1:]]
    while position < len(path):
        match = _TOKEN.match(path, position)
        if match is None:
            raise PermanentError(f"JSONPath 含不支援語法: {path[position:]!r}")
        field, raw_index = match.groups()
        if field is not None:
            if not isinstance(value, Mapping) or field not in value:
                raise PermanentError(f"JSONPath 欄位不存在: {field}")
            value = value[field]
        else:
            index = int(raw_index)
            if not isinstance(value, list) or index >= len(value):
                raise PermanentError(f"JSONPath index 不合法: [{index}]")
            value = value[index]
        position = match.end()
    return value
