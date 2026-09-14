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

from training_kb.config import DEFAULT_PROJECT_ID
from training_kb.errors import PermanentError
from training_kb.models import ReleaseKind, ReleaseSource, TicketSource
from training_kb.pipelines.common import JSONValue
from training_kb.source_ids import (
    github_release_id,
    github_source_event_id,
    github_ticket_id,
    github_user_id,
    stable_user_from_import,
)

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


# --- 3. 八個工具（Phase 36）---------------------------------------------------

GITHUB_ENCODING = "github"
FILE_ENCODING = "file"
"""parser 宣告「這筆的 ID 與 user 怎麼算」，對應 O6 核定紀錄的 `id_encoder` 欄。

`github` 對應 `github_ticket_id`／`github_release_id`（由 Phase 13 的編碼函式算出），
`file` 對應「檔案提供」（手動匯入檔自己帶 ID）。parser **不自己產生 ID 或 user**，
只把算 ID 需要的來源事實（owner／repo／number）原樣往下傳。
"""


def _arg(arguments: Mapping[str, JSONValue], name: str) -> JSONValue:
    if name not in arguments:
        raise PermanentError(f"工具參數缺少 {name}")
    return arguments[name]


def _pick(value: JSONValue, *names: str) -> JSONValue:
    """依序取巢狀欄位；任何一層不是物件或缺欄位都丟 `PermanentError`，**不回 `None`**。"""
    current = value
    for name in names:
        if not isinstance(current, Mapping) or name not in current:
            raise PermanentError(f"來源資料缺少欄位: {'.'.join(names)}")
        current = current[name]
    return current


def _mapping(value: JSONValue, field: str) -> dict[str, JSONValue]:
    if not isinstance(value, Mapping):
        raise PermanentError(f"{field} 必須是物件")
    return value


def _sequence(value: JSONValue, field: str) -> list[JSONValue]:
    if not isinstance(value, list):
        raise PermanentError(f"{field} 必須是清單")
    return value


def _text(value: JSONValue, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PermanentError(f"{field} 必須是非空字串")
    return value


def _whole(value: JSONValue, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise PermanentError(f"{field} 必須是整數")
    return value


def _require_kind(parsed: dict[str, JSONValue], expected: str) -> None:
    """normalizer 與 parser 的配對檢查，在 `validate` **之前**就擋下（設計 §7.2）。

    Agent 仍可自由挑 parser（ING Rule 10），被擋掉的只有「PR diff 拿去做 Ticket」
    這種配對；訊息一律含 `kind` 兩個字，讓測試抓得到失敗原因而不是只看到型別錯誤。
    """
    actual = _text(_pick(parsed, "kind"), "kind")
    if actual != expected:
        raise PermanentError(f"kind 不相容：這個 normalizer 只接受 {expected}，收到 {actual}")


def parse_github_issue(arguments: Mapping[str, JSONValue]) -> JSONValue:
    """GitHub Issue webhook payload → Ticket 候選欄位；只讀 fixture 已有的欄位。"""
    payload = _arg(arguments, "payload")
    parsed: dict[str, JSONValue] = {
        "kind": "ticket", "encoding": GITHUB_ENCODING, "source": TicketSource.GITHUB_ISSUE.value,
        "text": _text(_pick(payload, "issue", "body"), "issue.body"),
        "author_id": _whole(_pick(payload, "sender", "id"), "sender.id"),
        "number": _whole(_pick(payload, "issue", "number"), "issue.number"),
        "owner": _text(_pick(payload, "repository", "owner", "login"), "repository.owner.login"),
        "repo": _text(_pick(payload, "repository", "name"), "repository.name"),
        "ts": _text(_pick(payload, "issue", "created_at"), "issue.created_at")}
    return parsed


def _batch_item(arguments: Mapping[str, JSONValue]) -> dict[str, JSONValue]:
    """手動匯入檔：整包批次時取第一筆 `items`，也接受 path 直接指到某一筆。

    多筆批次的逐筆展開是 Phase 42 固定匯入的事；本 Phase 的工具只處理「一次一筆」，
    Agent 想指定第幾筆時記 `$event.payload.items[k]` 即可（index 仍在 path 裡，不是真值）。
    """
    payload = _mapping(_arg(arguments, "payload"), "payload")
    if "items" not in payload:
        return payload
    items = _sequence(payload["items"], "items")
    if not items:
        raise PermanentError("手動匯入批次的 items 是空的")
    return _mapping(items[0], "items[0]")


def _manual_ticket(arguments: Mapping[str, JSONValue], source: TicketSource) -> JSONValue:
    item = _batch_item(arguments)
    parsed: dict[str, JSONValue] = {
        "kind": "ticket", "encoding": FILE_ENCODING, "source": source.value,
        "id": _text(_pick(item, "id"), "id"),
        "text": _text(_pick(item, "text"), "text"),
        "author": _text(_pick(item, "author"), "author"),
        "ts": _text(_pick(item, "ts"), "ts")}
    return parsed


def parse_discord_message(arguments: Mapping[str, JSONValue]) -> JSONValue:
    """Discord 手動匯入的一則訊息 → Ticket 候選欄位（ID 與 user 由檔案提供）。"""
    return _manual_ticket(arguments, TicketSource.DISCORD)


def parse_support_email(arguments: Mapping[str, JSONValue]) -> JSONValue:
    """支援信箱手動匯入的一封信 → Ticket 候選欄位（ID 與 user 由檔案提供）。"""
    return _manual_ticket(arguments, TicketSource.EMAIL)


def _feature_of(change: JSONValue) -> str:
    return _text(_pick(change, "feature"), "feature")


def _changes_from_body(body: str) -> list[JSONValue]:
    """把 PR body 的「功能變更」條列讀成 `changes`（決策 F14：一個功能變更一筆）。

    Phase 13 的 fixture 把兩個子變更放在 `pull_request.body`，格式是
    `- <kind>: <舊名> -> <新名>`；`kind` 不在 `ReleaseKind` 三個值裡的條列一律略過，
    那是說明文字不是變更。清單依 `feature` **升序**排列，才會與 Phase 13 的
    `sub_release_ids`（同樣依名稱升序配 `k`）算出同一組 `r_` ID——同一個 PR 重送、
    條列順序不同也得到相同結果。
    """
    kinds = set(ReleaseKind)
    changes: list[JSONValue] = []
    for line in body.splitlines():
        if not line.startswith("- ") or ": " not in line:
            continue
        kind, rest = line.removeprefix("- ").split(": ", 1)
        if kind not in kinds:
            continue
        old_name, _, new_name = rest.partition(" -> ")
        changes.append({"kind": kind, "evidence": line, "feature": new_name or old_name,
                        "old_name": old_name if new_name else None,
                        "new_name": new_name or None})
    changes.sort(key=_feature_of)
    return changes


def parse_pr_diff(arguments: Mapping[str, JSONValue]) -> JSONValue:
    """GitHub PR webhook payload → `{"kind": "release", "changes": [...]}`（F14）。

    一律回**清單**，只改到一個功能時長度就是 1；挑第幾筆是 `normalize_release` 的
    `index` 的事，本函式不挑也不合併。
    """
    payload = _arg(arguments, "payload")
    parsed: dict[str, JSONValue] = {
        "kind": "release", "encoding": GITHUB_ENCODING, "source": ReleaseSource.GITHUB_PR.value,
        "owner": _text(_pick(payload, "repository", "owner", "login"), "repository.owner.login"),
        "repo": _text(_pick(payload, "repository", "name"), "repository.name"),
        "pr_number": _whole(_pick(payload, "pull_request", "number"), "pull_request.number"),
        "ts": _text(_pick(payload, "pull_request", "merged_at"), "pull_request.merged_at"),
        "changes": _changes_from_body(
            _text(_pick(payload, "pull_request", "body"), "pull_request.body"))}
    return parsed


def parse_changelog(arguments: Mapping[str, JSONValue]) -> JSONValue:
    """changelog 手動匯入 → `{"kind": "release", "changes": [...]}`；ID 由檔案提供。"""
    item = _batch_item(arguments)
    change: dict[str, JSONValue] = {
        "id": _text(_pick(item, "id"), "id"),
        "feature": _text(_pick(item, "feature"), "feature"),
        "kind": _text(_pick(item, "kind"), "kind"),
        "old_name": item.get("old_name"), "new_name": item.get("new_name"),
        "evidence": _text(_pick(item, "evidence"), "evidence"),
        "ts": _text(_pick(item, "ts"), "ts")}
    parsed: dict[str, JSONValue] = {
        "kind": "release", "encoding": FILE_ENCODING, "source": ReleaseSource.CHANGELOG.value,
        "changes": [change]}
    return parsed


def normalize_ticket(arguments: Mapping[str, JSONValue]) -> JSONValue:
    """Ticket 候選欄位 → Phase 31 要的 canonical payload；ID 與 user 只由 Phase 13 產生。

    `project_id` 一律填 Phase 02 的 `DEFAULT_PROJECT_ID`：工具只吃 `arguments`，
    拿不到 `Settings`，所以這裡不猜專案（MVP 只有一個專案）。
    """
    parsed = _mapping(_arg(arguments, "parsed"), "parsed")
    _require_kind(parsed, "ticket")
    if _text(_pick(parsed, "encoding"), "encoding") == GITHUB_ENCODING:
        identifier = github_ticket_id(_text(_pick(parsed, "owner"), "owner"),
                                      _text(_pick(parsed, "repo"), "repo"),
                                      _whole(_pick(parsed, "number"), "number"))
        author = github_user_id(_whole(_pick(parsed, "author_id"), "author_id"))
    else:
        identifier = _text(_pick(parsed, "id"), "id")
        author = stable_user_from_import(_text(_pick(parsed, "author"), "author"))
    candidate: dict[str, JSONValue] = {
        "id": identifier, "source": _text(_pick(parsed, "source"), "source"),
        "text": _text(_pick(parsed, "text"), "text"), "author": author,
        "ts": _text(_pick(parsed, "ts"), "ts"), "project_id": DEFAULT_PROJECT_ID}
    return candidate


def _sub_release_index(arguments: Mapping[str, JSONValue]) -> int:
    """`index` 省略時當成 1（決策 F14）；小於 1 直接拒絕，`k` 從 1 起算。"""
    index = _whole(arguments.get(SUB_RELEASE_INDEX, 1), SUB_RELEASE_INDEX)
    if index < 1:
        raise PermanentError(f"子 Release 序號從 1 起算: {index}")
    return index


def normalize_release(arguments: Mapping[str, JSONValue]) -> JSONValue:
    """第 k 筆子 Release 的 canonical payload；同一個 PR 的每一筆共用 `source_event_id`。

    `k` 超出 `changes` 長度一律 `PermanentError`，**不**回一個猜出來的空 Release。
    對每一筆 change 重跑一次 `normalize_release → validate` 是 Phase 37 的事。
    """
    parsed = _mapping(_arg(arguments, "parsed"), "parsed")
    _require_kind(parsed, "release")
    changes = _sequence(_pick(parsed, "changes"), "changes")
    index = _sub_release_index(arguments)
    if index > len(changes):
        raise PermanentError(f"子 Release 序號 {index} 超出 changes 的長度 {len(changes)}")
    change = _mapping(changes[index - 1], f"changes[{index - 1}]")
    source_event_id: JSONValue = None
    if _text(_pick(parsed, "encoding"), "encoding") == GITHUB_ENCODING:
        owner = _text(_pick(parsed, "owner"), "owner")
        repo = _text(_pick(parsed, "repo"), "repo")
        number = _whole(_pick(parsed, "pr_number"), "pr_number")
        identifier = github_release_id(owner, repo, number, index)
        source_event_id = github_source_event_id(owner, repo, number)
        ts = _text(_pick(parsed, "ts"), "ts")
    else:
        identifier = _text(_pick(change, "id"), "id")
        ts = _text(_pick(change, "ts"), "ts")
    candidate: dict[str, JSONValue] = {
        "id": identifier, "source_event_id": source_event_id,
        "source": _text(_pick(parsed, "source"), "source"), "feature": _feature_of(change),
        "kind": _text(_pick(change, "kind"), "kind"), "old_name": change.get("old_name"),
        "new_name": change.get("new_name"),
        "evidence": _text(_pick(change, "evidence"), "evidence"), "ts": ts}
    return candidate


def validate(arguments: Mapping[str, JSONValue]) -> JSONValue:
    """最後一步：交給 Phase 31 的 `validate_ticket`／`validate_release`，缺欄位由它報。

    本 Phase **不自寫欄位檢查**；型別用 `source` 分派（`TicketSource` 與 `ReleaseSource`
    的值互斥），因為 canonical Release 的 `kind` 已經是 `renamed`／`changed`／`removed`，
    不能同時兼任「ticket 還是 release」的判別欄位。回 `model_dump(mode="json")`，
    讓整條工具鏈維持同一個 `JSONValue` 型別；Phase 37 再用同一組 validator 取得物件。

    `ingress` 在函式內 import：`adapters` → `ingress` 是模組層唯一的外部相依，延後到
    呼叫時才載入，Phase 37 若讓 `ingress` 反向 import `rote` 也不會變成循環 import。
    """
    from training_kb.ingress import validate_release, validate_ticket

    candidate = _mapping(_arg(arguments, "candidate"), "candidate")
    source = _text(_pick(candidate, "source"), "source")
    if source in set(TicketSource):
        return validate_ticket(candidate).model_dump(mode="json")
    if source in set(ReleaseSource):
        return validate_release(candidate).model_dump(mode="json")
    raise PermanentError(f"validate 分不出 candidate 的類型: source={source}")


def default_registry() -> ToolRegistry:
    """恰好八個核定工具的 registry；沒有 shell、browser、發布或任意 AWS 工具。"""
    return ToolRegistry(tools={
        "parse_github_issue": parse_github_issue, "parse_discord_message": parse_discord_message,
        "parse_support_email": parse_support_email, "parse_pr_diff": parse_pr_diff,
        "parse_changelog": parse_changelog, "normalize_ticket": normalize_ticket,
        "normalize_release": normalize_release, "validate": validate})
