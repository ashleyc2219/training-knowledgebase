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
from collections.abc import Callable, Mapping
from dataclasses import dataclass

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


# --- 2. 工具白名單（Phase 36）-------------------------------------------------

TOOL_NAMES: frozenset[str] = frozenset({
    "parse_github_issue", "parse_discord_message", "parse_support_email", "parse_pr_diff",
    "parse_changelog", "normalize_ticket", "normalize_release", "validate"})
"""Training KB 明列的八個接入工具（00A §6.8）。

**固定八個**，不得由事件 payload 或模型輸出動態擴充：這裡沒有 shell、browser、發布
或任意 AWS 工具，Agent 的自由度只到「挑哪一個 parser」為止（設計 §7.2、ING Rule 10）。
"""

FINAL_TOOL = "validate"
"""已記錄序列的最後一步一定要是它（ING Rule 13）。"""

SUB_RELEASE_INDEX = "index"
"""`normalize_release` 的子 Release 序號參數名（決策 F14）；也是唯一允許字面值的參數名。"""

PARSER_KIND: Mapping[str, str] = {
    "parse_github_issue": "ticket", "parse_discord_message": "ticket", "parse_pr_diff": "release",
    "parse_support_email": "ticket", "parse_changelog": "release"}
"""每個 parser 產出哪一種類型；`normalize_*` 用它擋掉「PR diff 拿去做 Ticket」的配對。"""

AdapterTool = Callable[[Mapping[str, JSONValue]], JSONValue]
"""一個接入工具：吃已解析好的參數、回一個可直接進 JSON 的值。工具拿不到 `Settings`。"""

_INDEX_LITERAL = re.compile(r"[1-9][0-9]*")


def is_index_literal(tool: str, name: str, value: str) -> bool:
    """這個參數是不是「唯一允許的字面值」——F14 的子 Release 序號。

    三個條件要**同時**成立：工具是 `normalize_release`、參數名是 `SUB_RELEASE_INDEX`、
    值符合 `[1-9][0-9]*`（`k` 從 1 起算，所以 `"0"` 不算）。這是這條例外的唯一判斷處
    （00A §6.8），`rote.py` 的兩個函式都 import 它，不各自再寫一次條件。

    序號是「這條序列的第幾筆」這個位置資訊，不含 ID、文字、使用者或時間，所以它不是
    事件真值；其餘任何不以 `$event`／`$steps` 開頭的參數值一律視為真值而拒絕。
    """
    return (tool == "normalize_release" and name == SUB_RELEASE_INDEX
            and _INDEX_LITERAL.fullmatch(value) is not None)


@dataclass(frozen=True)
class ToolRegistry:
    """可呼叫工具的白名單；建構時與 `run()` 都比對 `TOOL_NAMES`。

    兩處都擋是刻意的：建構時擋住「把 shell 註冊進來」，`run()` 擋住「模型輸出一個沒註冊
    的名字」。不提供執行期註冊 API——registry 的內容在啟動時就固定（設計 §7.2）。
    測試可以只放子集合，但**名稱**永遠只能來自那八個。
    """

    tools: Mapping[str, AdapterTool]

    def __post_init__(self) -> None:
        unknown = sorted(set(self.tools) - TOOL_NAMES)
        if unknown:
            raise PermanentError(f"工具不在白名單: {', '.join(unknown)}")

    def run(self, name: str, arguments: Mapping[str, JSONValue]) -> JSONValue:
        """執行一個已註冊工具；未註冊名稱丟 `PermanentError`，不 fallback 也不動態載入。"""
        tool = self.tools.get(name)
        if tool is None:
            raise PermanentError(f"工具不在白名單或未註冊: {name}")
        return tool(arguments)
