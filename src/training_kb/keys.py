"""單表物理鍵與關係邊契約：十個邏輯實體 -> 一張 DynamoDB 表的 `PK`／`SK`。

`models.py` 只保留裸 ID；這裡是**唯一**可以加上 `TUTORIAL#`、`VERSION#` 等類型前綴的地方，
已帶前綴的字串再傳進任何 builder 一律拒絕（00A §3.3）。邊的形狀固定是
`PK=起點`、`SK=<關係>#<終點 PK>`、`target=<終點 PK>`（設計 §9.2）。

檔案分成五段，Phase 10 的 `ops_pk`／`operation_ref` 直接接在最後一段，不必改動前四段：
1. 常數（`META`、`RELATIONS`）
2. 私有守門員（`_bare`、`_pk`）
3. 十個 PK builder
4. 三個 parser
5. 關係邊（`edge_sk`／`parse_edge_sk`）
"""

import json
from datetime import datetime
from hashlib import sha256

from training_kb.clock import to_iso

# --- 1. 常數 -----------------------------------------------------------------

META = "META"
"""十實體 metadata item 的固定 sort key；值必須等於 docs/decisions/O1-metadata-sort-key.md
的 `Sort-Key`（O1 gate）。STEP 沒有 metadata item，它的 SK 是 `REFERENCES#<FEATURE PK>`。"""

RELATIONS = frozenset({"REFERENCES", "SUPERSEDES", "APPLIED_TO", "ASKS_ABOUT", "REFERS_TO"})
"""設計 §9.2 的五種關係；`keys.py` 內部白名單，其他模組不 import。"""


# --- 2. 私有守門員 -----------------------------------------------------------


def _bare(value: str) -> str:
    """十個 builder 共用的裸 ID 檢查：非空、無前後空白、不含 `#`，避免重複加前綴。

    前後空白的規則與 `models.bare_id` 對齊：`" Prepare "` 與 `"Prepare"` 若都能建鍵，
    同一個 Feature 會得到兩把不同的 PK。
    """
    if not isinstance(value, str) or not value or value != value.strip() or "#" in value:
        raise ValueError(f"key input must be a non-empty bare identifier: {value!r}")
    return value


def _pk(kind: str, value: str) -> str:
    return f"{kind}#{_bare(value)}"


# --- 3. 十個 PK builder ------------------------------------------------------


def tutorial_pk(slug: str) -> str:
    return _pk("TUTORIAL", slug)


def version_pk(version_id: str) -> str:
    return _pk("VERSION", version_id)


def feature_pk(feature_id: str) -> str:
    return _pk("FEATURE", feature_id)


def ticket_pk(ticket_id: str) -> str:
    return _pk("TICKET", ticket_id)


def release_pk(release_id: str) -> str:
    return _pk("RELEASE", release_id)


def feedback_pk(feedback_id: str) -> str:
    return _pk("FEEDBACK", feedback_id)


def rule_pk(rule_id: str) -> str:
    return _pk("RULE", rule_id)


def proc_pk(signature: str) -> str:
    return _pk("PROC", signature)


def step_pk(version_id: str, number: int) -> str:
    """`STEP#<slug>@v<n>#<i>`；先擋 `bool` 再擋非正整數，避免 `True` 變成假的第 1 步。"""
    if isinstance(number, bool) or not isinstance(number, int) or number < 1:
        raise ValueError(f"step number must be a positive int: {number!r}")
    return f"STEP#{_bare(version_id)}#{number}"


def view_pk(tutorial_version: str, user: str, ts: datetime) -> str:
    """三元組固定 JSON 編碼後的 SHA-256；只用於瀏覽去重，不是使用者身分。"""
    canonical = json.dumps(
        [_bare(tutorial_version), _bare(user), to_iso(ts)],
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"VIEW#{sha256(canonical).hexdigest()}"


# --- 4. 三個 parser ----------------------------------------------------------


def parse_pk(value: str) -> tuple[str, str]:
    """只切第一個 `#`；刻意不維護前綴白名單，Phase 10 追加前綴時不必回頭改它。"""
    kind, separator, identifier = value.partition("#")
    if not separator or not kind or not identifier:
        raise ValueError(f"invalid physical primary key: {value!r}")
    return kind, identifier


def parse_step_pk(value: str) -> tuple[str, int]:
    """`step_pk` 的反函式；用 `rpartition` 從右邊切，版本 ID 自己長得像 `slug@v2`。

    只接受 `step_pk` 產得出來的字串，也就是 `step_pk(*parse_step_pk(pk)) == pk` 必須成立：
    版本 ID 不得為空（`STEP##3`）；步驟號用 `isdecimal()` 擋掉 `³` 這種 `isdigit()` 會放行、
    `int()` 卻要丟自己的 `ValueError` 的字元；再用 `str(int(number)) == number` 擋掉前導零
    （`03`）與全形數字（`３`）——它們 `int()` 得到同一個值，組回去卻不是原本那把鍵。
    """
    kind, identifier = parse_pk(value)
    version_id, separator, number = identifier.rpartition("#")
    if (
        kind != "STEP"
        or not separator
        or not version_id
        or not number.isdecimal()
        or str(int(number)) != number
    ):
        raise ValueError(f"invalid step primary key: {value!r}")
    return version_id, int(number)


# --- 5. 關係邊 ---------------------------------------------------------------


def edge_sk(relation: str, target_pk: str) -> str:
    if relation not in RELATIONS:
        raise ValueError(f"unsupported edge relation: {relation!r}")
    parse_pk(target_pk)
    return f"{relation}#{target_pk}"


def parse_edge_sk(value: str) -> tuple[str, str]:
    """只切第一個 `#`：終點本身就含 `#`，用 `split` 會把 target 切壞。"""
    relation, separator, target = value.partition("#")
    if not separator or relation not in RELATIONS:
        raise ValueError(f"invalid edge sort key: {value!r}")
    parse_pk(target)
    return relation, target
