# Phase 36：JSONPath 與白名單 Adapter 實作計畫

> **給 agentic worker：** 逐項執行 checkbox；實作時使用 `superpowers:subagent-driven-development` 或 `superpowers:executing-plans`，每個 Task 都先紅燈再綠燈。

**目標：** 讓 PROC 只能用安全 JSONPath 讀取事件欄位或前一步輸出，並且只能呼叫 Training KB 明列的八個接入工具。

**架構：** `resolve_jsonpath` 只接受欄位名稱與非負陣列 index；`ToolRegistry` 只暴露五個來源 parser、兩個 normalizer 與 `validate`。兩者都放在本 Phase 擁有的 `adapters.py`（00A §3.2）；`rote.py` 只多兩個函式：`validate_recorded_steps` 檢查已記錄步驟、`execute_recorded_steps` 在記憶體內依序解析參數並執行工具。PROC 保存的是 path 字串，不保存 Ticket 文字、使用者、ID 或任何事件真值。

**技術：** Python 3.12、標準函式庫 `re`、`dataclass`、pytest、Phase 13 的 O6 fixture 與核定紀錄。

## 全域限制

- 唯一主來源是 [Training KB 設計 §7.2、§14.1、§18 O6、§20.7](../../design/training-kb.md)；名稱、模組位置與型別以 [00A 共用契約與名詞](00A-共用契約與名詞.md) §3.2、§6.8、§6.9 為準。
- 前置為 [Phase 29 共用 Pipeline 執行器](./29-Phase29-共用Pipeline執行器與ASL失敗語意.md)（`JSONValue` 的唯一定義）、[Phase 31 正規化](./31-Phase31-Ticket與Release正規化.md)、[Phase 33 結構簽名](./33-Phase33-Rote結構簽名與STABLE_KEYS.md) 與 [Phase 35 PROC 生命週期](./35-Phase35-PROC成功失敗與退役生命週期.md)；fixture 與核定紀錄來自 [Phase 13 O6 來源 ID 契約](./13-Phase13-O6來源ID與穩定使用者契約.md)。前置未通過時停止。
- 下一階段是 [Phase 37 Rote Agent 回退](./37-Phase37-Rote-Agent回退與成功提交.md)。
- 本階段不寫 Ticket／Release、不啟動 Step Functions、不增加 PROC 計數，也不提供 shell、browser、發布或任意 AWS 工具。以下程式檔都是執行本計畫時預計建立或修改；本文件本身沒有實作應用程式。
- **gate 狀態：** O6 尚未核對完成，只有 `("github.com", "issues")` 的 `action, issue, repository, sender` 已核定；其餘 `(domain, event_type)` 的 `approved_by` 為空即 blocked，測試必須以明確 gate failure 結束，**不得**用臨時 mapping 讓它變綠，也不得宣稱 PR／Discord／email／changelog 的 adapter 已驗收。

---

## 1. 你在整體流程的位置

```text
RawEvent（Phase 33） + 已記錄 ProcStep（PROC.steps）
   |
   +-> [你在這裡] adapters.resolve_jsonpath("$event.payload.issue.number")
   +-> [你在這裡] adapters.ToolRegistry.run("parse_github_issue", 已解析的 args)
   +-> [你在這裡] rote.execute_recorded_steps：前一步輸出只留記憶體，下一步用 $steps[0] 指過去
   v
Phase 37：validate 通過 -> 保存 canonical -> 啟動 pipeline -> 才提交 PROC 成功

事件文字／ID／user 真值 --------X--------> PROC.steps（只存 path 字串）
任意運算式／wildcard／filter ---X--------> resolve_jsonpath
模型或 payload 自己給的工具名 --X--------> ToolRegistry
```

## 2. 完成後看得到什麼

輸入 `$event.payload.issue.labels[0].name` 能取得第一個 label 名稱；`$steps[0].ticket.id` 能取得前一步輸出。`$..password`、`$event[*]`、`$event.payload.issue.labels[-1]`、slice、filter、引號 key、函式呼叫，以及光是 `$event` 這種沒有指到欄位的 path，全部回 `PermanentError`。保存後的 `ProcStep.args` 只會看到 JSONPath，例如 `{"body": "$event.payload.issue.body"}`；把 fixture 裡每一個長度 8 以上的字串值拿去搜尋序列化後的 PROC，必須是零筆。

## 3. 名詞小抄

| 名詞 | 白話意思 |
|---|---|
| JSONPath／真值 | JSONPath 是用字串描述「資料在哪裡」，此處只採很小的安全子集合：只有欄位 token（點號後的名稱，如 `.payload`）與陣列 index（中括號內的非負整數，如 `[0]`）。真值是某次事件的實際 ID、文字、時間、user 或 secret，PROC 一律不保存。 |
| Adapter／Registry | Adapter 是把某來源格式轉成 Ticket／Release 欄位的純函式；Registry 是可呼叫工具的白名單，清單外名稱一律拒絕，也不接受執行期動態註冊。 |
| `ProcStep`／`RawEvent` | PROC 裡的一步（`tool` 是工具名、`args` 每個值都是 JSONPath 字串）；`RawEvent` 是 Phase 33 的原始事件容器（`domain`、`adapter`、`event_type`、`headers`、`payload`）。 |
| `SourceApproval` | Phase 13 的核定紀錄；`approved_by` 為空就代表該來源 blocked。 |
| F14／子 Release | 設計 §19 的決策 F14：一個 PR 同時改到多個功能時，拆成多筆 Release（稱為子 Release），每筆各自有 `id`，但共用同一個 `source_event_id`。 |

## 4. 預計檔案

| 動作 | 路徑 | 責任 |
|---|---|---|
| 建立 | `src/training_kb/adapters.py` | `TOOL_NAMES`、`FINAL_TOOL`、`PATH_ROOTS`、`PARSER_KIND`、`AdapterTool`、`ToolRegistry`、`default_registry`、`resolve_jsonpath` 與八個工具實作。 |
| 修改／消費 | `src/training_kb/rote.py`、`src/training_kb/pipelines/common.py` | `rote.py` 加 `validate_recorded_steps`、`execute_recorded_steps`；`pipelines/common.py` 只 import `JSONValue`，本 Phase **不重新定義**它。 |
| 測試 | `tests/unit/rote/test_jsonpath.py`、`tests/unit/rote/test_tool_registry.py` | 安全語法與 index 邊界；白名單、記錄格式、最後一步 validate、執行時才解析值。 |
| 測試 | `tests/integration/test_adapter_fixtures.py` | 用 Phase 13 的核定紀錄與 fixture 驗證每個來源。 |

## 5. 固定介面

### Consumes

```text
Phase 29  JSONValue = None | bool | int | float | str | list[JSONValue] | dict[str, JSONValue]
          唯一定義在 training_kb.pipelines.common；本 Phase 只 import，不重新宣告
Phase 33  RawEvent(domain, adapter, event_type, headers, payload)
Phase 03  ProcStep(tool: str, args: dict[str, str])
Phase 31  validate_ticket(payload) -> Ticket、validate_release(payload) -> Release
          必填：Ticket id, source, text, author, ts, project_id；Release id, source, feature, kind, evidence, ts
Phase 13  SourceApproval(domain, event_type, adapter, stable_keys, fixture, id_encoder,
                         stable_user_source, approved_by, approved_at)
          load_source_approvals(path) -> tuple[SourceApproval, ...]
          github_ticket_id／github_release_id／github_user_id／stable_user_from_import
Phase 02  PermanentError（白名單與 path 違規）、IngressError（由 validate 轉手）
          DEFAULT_PROJECT_ID = "demo"    # normalize_ticket 補 project_id 的唯一來源
```

### Produces

```python
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

from training_kb.models import ProcStep
from training_kb.pipelines.common import JSONValue
from training_kb.rote import RawEvent

TOOL_NAMES: frozenset[str] = frozenset({
    "parse_github_issue", "parse_discord_message", "parse_support_email", "parse_pr_diff",
    "parse_changelog", "normalize_ticket", "normalize_release", "validate"})
FINAL_TOOL = "validate"
PATH_ROOTS = ("$event", "$steps")
SUB_RELEASE_INDEX = "index"    # normalize_release 的子 Release 序號參數名（F14）
PARSER_KIND: Mapping[str, str] = {
    "parse_github_issue": "ticket", "parse_discord_message": "ticket", "parse_pr_diff": "release",
    "parse_support_email": "ticket", "parse_changelog": "release"}
AdapterTool = Callable[[Mapping[str, JSONValue]], JSONValue]

@dataclass(frozen=True)
class ToolRegistry:
    tools: Mapping[str, AdapterTool]
    def run(self, name: str, arguments: Mapping[str, JSONValue]) -> JSONValue: ...

def default_registry() -> ToolRegistry: ...
def resolve_jsonpath(root: JSONValue, path: str) -> JSONValue: ...
def is_index_literal(tool: str, name: str, value: str) -> bool: ...
def validate_recorded_steps(steps: Sequence[ProcStep]) -> None: ...
def execute_recorded_steps(event: RawEvent, steps: Sequence[ProcStep],
                           registry: ToolRegistry) -> JSONValue: ...
```

- 工具名稱**固定八個**，不得由事件 payload 或模型輸出動態擴充：`ToolRegistry` 建構時就比對 `TOOL_NAMES`，清單外的名稱直接丟 `PermanentError`；`default_registry()` 回傳恰好八個，測試可以用子集合。模組位置（00A §3.2）：`resolve_jsonpath`、`ToolRegistry` 與八個工具在 `src/training_kb/adapters.py`；`validate_recorded_steps`、`execute_recorded_steps` 在 `src/training_kb/rote.py`。相依方向只有一邊：`rote.py` import `adapters.py`，`adapters.py` **不得** import `rote.py`（上面的 Produces 是兩個模組合起來看，`RawEvent` 只出現在 `rote.py` 那半邊），否則會循環 import。
- 每個 parser 在輸出帶一個 `kind`（見 `PARSER_KIND`）。`normalize_ticket` 只接受 `kind == "ticket"`、`normalize_release` 只接受 `"release"`，配錯時在 `validate` **之前**就丟 `PermanentError`。Agent 仍可自由挑 parser（ING Rule 10），被擋掉的只有「PR diff 拿去做 Ticket」這種配對。
- `validate` 內部呼叫 Phase 31 的 `validate_ticket`／`validate_release`（不合法丟 `IngressError`），回傳 `model_dump(mode="json")` 後的 dict，讓整條工具鏈維持同一個 `JSONValue` 型別；Phase 37 再用同一組 validator 取得 `Ticket`／`Release` 物件。
- **F14 多個子 Release：** 兩個 release parser（`parse_pr_diff`、`parse_changelog`）一律回 `{"kind": "release", "changes": [...]}`，`changes` 是**清單**，一個功能變更一筆（各自有 `feature`／`kind`／`old_name`／`new_name`），只改到一個功能時長度就是 1。`normalize_release` 收 `{"parsed": ..., "index": k}`，`k` 從 **1** 起算，取 `parsed["changes"][k-1]` 產出第 k 筆子 Release：`id` 用 `github_release_id(owner, repo, pr_number, k)`、`source_event_id` 用 `github_source_event_id(owner, repo, pr_number)`（同一個 PR 的每一筆都一樣）。`index` 省略時當成 1，`k` 超出 `changes` 長度丟 `PermanentError`。對每一筆 change 重跑一次 `normalize_release → validate` 是 [Phase 37](./37-Phase37-Rote-Agent回退與成功提交.md) 的事，本 Phase 只提供單筆的工具。
- **`index` 是唯一允許的非 JSONPath 參數。** `ProcStep.args` 的值原則上都是 JSONPath 字串；例外只有一個：`normalize_release` 的 `index` 可以是十進位字面值（例如 `"1"`），因為它是「這條序列的第幾筆」這個位置，不是事件真值（不含 ID、文字、使用者或時間）。`is_index_literal(tool, name, value)` 是這條例外的唯一判斷處：`tool == "normalize_release"`、`name == SUB_RELEASE_INDEX` 且 `value` 符合 `[1-9][0-9]*` 三個條件同時成立才算數，其餘任何不以 `$event`／`$steps` 開頭的參數值一律 `PermanentError`。

### 實作時補齊的四個細節（原稿未指定，已落地）

1. **parser 多帶一個 `encoding`**（`"github"`／`"file"`）：對應 O6 核定紀錄的 `id_encoder` 欄
   （`github_ticket_id`／`github_release_id` vs 「檔案提供」）。normalizer 靠它決定「ID 與穩定 user
   由 Phase 13 的編碼函式算」還是「檔案自己帶」，parser 本身仍**不產生 ID 或 user**。
2. **`validate` 用 `source` 分派，不是用 `kind`**：canonical `Release` 的 `kind` 已經是
   `renamed`／`changed`／`removed`（Phase 31 的必填欄位），不能同時兼任「ticket 還是 release」的
   判別欄位。`TicketSource`（`github_issue`／`discord`／`email`）與 `ReleaseSource`
   （`github_pr`／`changelog`）的值互斥，所以 `validate` 讀 `candidate["source"]` 即可分派；
   兩者都不是就丟 `PermanentError`。**`kind` 仍然是 parser 輸出的判別欄位**（§5 的
   `PARSER_KIND` 契約不變），normalizer 的 `_require_kind` 照原稿在 `validate` 之前擋下錯配。
3. **`changes` 依 `feature` 升序**：Phase 13 的 `sub_release_ids` 是「依 Feature 名稱升序配 `k`」，
   若 `parse_pr_diff` 照 body 條列順序回傳，同一個 PR 換個條列順序就會得到不同的 `r_` ID。
   parser 排序後 `changes[k-1]` 與 `github_release_id(..., k)` 就與 Phase 13 完全對齊
   （PR fixture：`k=1` 是 `Legacy Export`、`k=2` 是 `Prepare`）。
4. **`validate` 內對 `ingress` 用函式內 import**：`adapters.py` 需要 Phase 31 的
   `validate_ticket`／`validate_release`，但 Phase 37 很可能讓 `ingress._normalize` 反向 import
   `rote`，那會形成 `ingress → rote → adapters → ingress` 的循環。延後到呼叫時才載入，
   讓 `rote.py → adapters.py` 的單向相依（00A §6.8）在兩個方向都成立。

## 6. 安全 JSONPath 文法

```text
$event .<field> [.<field>] [[<非負整數>]] ...      本次原始事件
$steps [<非負整數>] [.<field>] ...                 前面每一步的輸出清單
```

- 根節點只有 `$event` 與 `$steps`，後面**至少要有一個 token**：`$steps[0]` 合法，光是 `$event` 或 `$steps` 不合法（等於把整包事件當參數）。欄位名稱符合 `[A-Za-z_][A-Za-z0-9_]*`，index 只能是非負十進位整數；禁止 wildcard、recursive descent（`..`）、filter、slice、union、負 index、引號 key、運算子與函式呼叫。
- path 指到不存在的欄位、型別不對的容器或超出範圍的 index 一律丟 `PermanentError`，**不得**回 `None` 假裝欄位存在。

## 7. TDD Tasks

### Task 1：建立安全 JSONPath resolver

- [x] **Step 1：建立失敗測試**

```python
import pytest

from training_kb.adapters import resolve_jsonpath
from training_kb.errors import PermanentError

ROOT = {"event": {"payload": {"issue": {"labels": [{"name": "bug"}], "body": "找不到按鈕"}}},
        "steps": [{"ticket": {"id": "t_gh-acme-app-12"}}]}


def test_resolve_fields_and_array_index() -> None:
    assert resolve_jsonpath(ROOT, "$event.payload.issue.labels[0].name") == "bug"
    assert resolve_jsonpath(ROOT, "$steps[0].ticket.id") == "t_gh-acme-app-12"
    assert resolve_jsonpath(ROOT, "$steps[0]") == {"ticket": {"id": "t_gh-acme-app-12"}}


@pytest.mark.parametrize("path", [
    "$..password", "$event[*]", "$event[?(@.x)]", "$event['payload']",
    "$event.payload.issue.labels[-1]", "$event.payload.issue.labels[0:1]",
    "$event", "$steps", "", "$event.payload.missing", "$steps[9].ticket", "$event.payload[0]",
])
def test_rejects_unsafe_or_missing_paths(path: str) -> None:
    with pytest.raises(PermanentError):
        resolve_jsonpath(ROOT, path)
```

- [x] **Step 2：執行並確認紅燈** — 跑 `uv run pytest tests/unit/rote/test_jsonpath.py -q`，預期 FAIL。實際訊號是 `ModuleNotFoundError: No module named 'training_kb.adapters'`：`adapters.py` 在 Task 1 才建立，整支模組都還不存在，所以 Python 報的是「找不到模組」而不是「找不到名字」。模組建立之後才會出現原稿寫的 `cannot import name 'resolve_jsonpath'`（Task 2 的紅燈就是這種形狀）。

- [x] **Step 3：建立最小實作**

```python
import re
from collections.abc import Mapping

from training_kb.errors import PermanentError
from training_kb.pipelines.common import JSONValue

PATH_ROOTS = ("$event", "$steps")
_TOKEN = re.compile(r"\.([A-Za-z_][A-Za-z0-9_]*)|\[(0|[1-9][0-9]*)\]")


def resolve_jsonpath(root: JSONValue, path: str) -> JSONValue:
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
```

- [x] **Step 4：跑完整檔案確認綠燈** — 跑 `uv run pytest tests/unit/rote/test_jsonpath.py -q`，預期 PASS；十二個非法 path 全部是 `PermanentError`，沒有任何一個靜默回 `None`。

- [x] **Step 5：提交** — `git add src/training_kb/adapters.py tests/unit/rote/test_jsonpath.py && git commit -m "feat(rote): 限制可重放 JSONPath"`

### Task 2：鎖定工具白名單與記錄格式

- [x] **Step 1：建立失敗測試**

```python
import pytest

from training_kb.adapters import TOOL_NAMES, ToolRegistry
from training_kb.errors import PermanentError
from training_kb.models import ProcStep
from training_kb.rote import RawEvent, execute_recorded_steps, validate_recorded_steps

BODY = "找不到按鈕在哪一頁"
EVENT = RawEvent(domain="github.com", adapter="github_issue", event_type="issues",
                 headers={"x-github-event": "issues"},
                 payload={"action": "opened", "issue": {"number": 12, "body": BODY}})
LEGAL = [ProcStep(tool="parse_github_issue", args={"body": "$event.payload.issue.body"}),
         ProcStep(tool="normalize_ticket", args={"parsed": "$steps[0]"}),
         ProcStep(tool="validate", args={"candidate": "$steps[1]"})]


def registry_of(*names: str) -> ToolRegistry:
    return ToolRegistry(tools={name: dict for name in names})


def test_registry_only_accepts_the_eight_approved_tools() -> None:
    assert len(TOOL_NAMES) == 8
    for forbidden in ("shell", "browser", "publish", "boto3"):
        with pytest.raises(PermanentError, match="白名單"):
            registry_of(forbidden)
    with pytest.raises(PermanentError, match="白名單"):
        registry_of("validate").run("parse_pr_diff", {})


def test_recorded_steps_hold_paths_only_and_end_with_validate() -> None:
    validate_recorded_steps(LEGAL)
    dumped = [step.model_dump() for step in LEGAL]
    assert BODY not in repr(dumped)
    assert all(v.startswith(("$event", "$steps")) for s in dumped for v in s["args"].values())


@pytest.mark.parametrize("steps", [
    [],
    [ProcStep(tool="validate", args={"x": BODY})],
    [ProcStep(tool="normalize_ticket", args={"parsed": "$steps[0]"})],
    [ProcStep(tool="validate", args={"a": "$steps[0]"}),
     ProcStep(tool="parse_changelog", args={"b": "$steps[0]"})],
    [ProcStep(tool="validate", args={"a": "$steps[0]"}),
     ProcStep(tool="parse_changelog", args={"b": "$steps[0]"}),
     ProcStep(tool="validate", args={"c": "$steps[1]"})],
])
def test_rejects_illegal_recorded_steps(steps) -> None:
    with pytest.raises(PermanentError):
        validate_recorded_steps(steps)


def test_execute_resolves_values_only_at_run_time() -> None:
    steps = [LEGAL[0], ProcStep(tool="validate", args={"parsed": "$steps[0]"})]
    result = execute_recorded_steps(EVENT, steps, registry_of("parse_github_issue", "validate"))
    assert result == {"parsed": {"body": BODY}}
    assert steps[0].args == {"body": "$event.payload.issue.body"}


def test_only_the_sub_release_index_may_be_a_literal() -> None:
    validate_recorded_steps([
        ProcStep(tool="parse_pr_diff", args={"payload": "$event.payload"}),
        ProcStep(tool="normalize_release", args={"parsed": "$steps[0]", "index": "2"}),
        ProcStep(tool="validate", args={"candidate": "$steps[1]"}),
    ])
    for illegal in ({"parsed": "$steps[0]", "index": "0"},        # k 從 1 起算
                    {"parsed": "$steps[0]", "index": BODY},        # 字面值不是序號
                    {"parsed": "$steps[0]", "other": "2"}):        # 只有 index 有例外
        with pytest.raises(PermanentError):
            validate_recorded_steps([ProcStep(tool="normalize_release", args=illegal),
                                     ProcStep(tool="validate", args={"c": "$steps[0]"})])
    with pytest.raises(PermanentError):                             # 別的工具沒有這條例外
        validate_recorded_steps([ProcStep(tool="normalize_ticket", args={"index": "2"}),
                                 ProcStep(tool="validate", args={"c": "$steps[0]"})])
```

- [x] **Step 2：執行並確認紅燈** — 跑 `uv run pytest tests/unit/rote/test_tool_registry.py -q`，預期 FAIL。實際訊號是 `cannot import name 'TOOL_NAMES' from 'training_kb.adapters'`：Python 只報 import 清單裡**第一個**解析失敗的名字，而 `from training_kb.adapters import TOOL_NAMES, ToolRegistry` 在 `from training_kb.rote import ... validate_recorded_steps` 上面一行。兩者都是「名字還沒實作」的同一個紅燈。

- [x] **Step 3：建立最小實作**（加在 `src/training_kb/rote.py`）

```python
from collections.abc import Sequence

from training_kb.adapters import (FINAL_TOOL, PATH_ROOTS, TOOL_NAMES, ToolRegistry,
                                  is_index_literal, resolve_jsonpath)
from training_kb.errors import PermanentError
from training_kb.models import ProcStep
from training_kb.pipelines.common import JSONValue


def validate_recorded_steps(steps: Sequence[ProcStep]) -> None:
    if not steps or steps[-1].tool != FINAL_TOOL:
        raise PermanentError("PROC 至少要有一步，且最後一步必須是 validate")
    for position, step in enumerate(steps):
        if step.tool not in TOOL_NAMES:
            raise PermanentError(f"工具不在白名單: {step.tool}")
        if step.tool == FINAL_TOOL and position != len(steps) - 1:
            raise PermanentError("validate 只能是最後一步，不能只是「曾經出現」")
        for name, value in step.args.items():
            if is_index_literal(step.tool, name, value):
                continue          # F14 子 Release 序號：是位置，不是事件真值
            if not value.startswith(PATH_ROOTS):
                raise PermanentError(f"步驟 {position} 的參數 {name} 不是 JSONPath，可能含事件真值")


def execute_recorded_steps(event: RawEvent, steps: Sequence[ProcStep],
                           registry: ToolRegistry) -> JSONValue:
    validate_recorded_steps(steps)
    outputs: list[JSONValue] = []
    root: JSONValue = {"steps": outputs, "event": {
        "domain": event.domain, "adapter": event.adapter, "event_type": event.event_type,
        "headers": dict(event.headers), "payload": event.payload}}
    for step in steps:
        arguments = {
            name: int(value) if is_index_literal(step.tool, name, value)
            else resolve_jsonpath(root, value)
            for name, value in step.args.items()}
        outputs.append(registry.run(step.tool, arguments))
    return outputs[-1]
```

`ToolRegistry` 在 `adapters.py` 用 `__post_init__` 檢查 `set(self.tools) - TOOL_NAMES` 是否為空，`run()` 對未註冊名稱丟 `PermanentError`；兩處訊息都含「白名單」三個字，測試才抓得到。`is_index_literal` 也放 `adapters.py`（`tool == "normalize_release" and name == SUB_RELEASE_INDEX and re.fullmatch(r"[1-9][0-9]*", value) is not None`），讓「唯一的字面值例外」只有一份判斷，`rote.py` 兩個函式都 import 它。

- [x] **Step 4：跑完整檔案確認綠燈** — 跑 `uv run pytest tests/unit/rote/test_tool_registry.py -q`，預期 PASS；白名單、真值排除、最後一步 validate 與「執行時才解析值」四組斷言全綠。

- [x] **Step 5：提交** — `git add src/training_kb/adapters.py src/training_kb/rote.py tests/unit/rote/test_tool_registry.py && git commit -m "feat(rote): 建立接入工具白名單"`

### Task 3：以 O6 核定紀錄驗證每個 adapter

- [x] **Step 1：建立失敗測試**

```python
"""Phase 36 Task 3：用 Phase 13 的核定紀錄與 fixture 驗證每一個 adapter。

三件事：每個**已核定**來源都能從原始事件走到 canonical 物件（ING Rule 12／13）、
已記錄的 `ProcStep` 裡搜不到任何事件真值，以及 F14 的子 Release 由 `index` 挑出。
未核定的來源維持 gate failure：那幾列以 `xfail(strict=True)` 收尾，**不得**補臨時 mapping
讓它變綠——真的補了就會 XPASS，strict 會把它變成紅燈（設計 §18 O6、決策 F02）。

本檔不連 AWS、不呼叫模型、不連 GitHub，所以不標 `aws` marker（00A §3.2）。
"""

import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from training_kb.adapters import FINAL_TOOL, PARSER_KIND, default_registry
from training_kb.errors import PermanentError
from training_kb.models import ProcStep
from training_kb.pipelines.common import JSONValue
from training_kb.rote import RawEvent, execute_recorded_steps
from training_kb.source_ids import SourceApproval, load_source_approvals

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = REPO_ROOT / "tests" / "fixtures"
NORMALIZER = {"ticket": "normalize_ticket", "release": "normalize_release"}
PARSER_OF_ADAPTER = {"github_issue": "parse_github_issue", "github_pr": "parse_pr_diff",
                     "discord_manual": "parse_discord_message",
                     "email_manual": "parse_support_email", "changelog_manual": "parse_changelog"}
APPROVALS = load_source_approvals(FIXTURES / "o6" / "approved-sources.json")
APPROVAL_PARAMS = [
    pytest.param(row, id=f"{row.domain}:{row.event_type}",
                 marks=() if row.approved else pytest.mark.xfail(
                     strict=True, reason=f"O6 尚未核定 {row.domain}/{row.event_type}"))
    for row in APPROVALS
]
PR_APPROVED = any(
    row.approved and (row.domain, row.event_type) == ("github.com", "pull_request")
    for row in APPROVALS
)


def leaf_strings(value: JSONValue) -> Iterator[str]:
    """走訪 fixture 所有葉節點字串，證明 PROC 不含事件真值。"""
    if isinstance(value, dict):
        value = list(value.values())
    if isinstance(value, list):
        for item in value:
            yield from leaf_strings(item)
    elif isinstance(value, str) and len(value) >= 8:
        yield value


def steps_for(parser: str) -> list[ProcStep]:
    return [ProcStep(tool=parser, args={"payload": "$event.payload"}),
            ProcStep(tool=NORMALIZER[PARSER_KIND[parser]], args={"parsed": "$steps[0]"}),
            ProcStep(tool="validate", args={"candidate": "$steps[1]"})]


def event_of(domain: str, adapter: str, event_type: str, fixture: str) -> RawEvent:
    return RawEvent(domain=domain, adapter=adapter, event_type=event_type, headers={},
                    payload=json.loads((FIXTURES / fixture).read_text("utf-8")))


@pytest.mark.parametrize("row", APPROVAL_PARAMS)
def test_each_source_reaches_canonical_without_storing_values(row: SourceApproval) -> None:
    assert row.approved_by, (
        f"O6 未核定 {row.domain}/{row.event_type}：保持 blocked，不得補臨時 mapping")
    parser = PARSER_OF_ADAPTER[row.adapter]
    steps = steps_for(parser)
    assert steps[-1].tool == FINAL_TOOL          # ING Rule 13：最後一個工具恰為 validate
    event = event_of(row.domain, row.adapter, row.event_type, row.fixture)
    canonical = execute_recorded_steps(event, steps, default_registry())
    assert canonical["id"].startswith("t_" if PARSER_KIND[parser] == "ticket" else "r_")
    recorded = json.dumps([step.model_dump() for step in steps], ensure_ascii=False)
    assert all(value not in recorded for value in leaf_strings(event.payload))


def test_wrong_parser_normalizer_pair_fails_before_validate() -> None:
    """配對錯誤是**拒絕**斷言，與 O6 是否核定無關，所以不掛 gate 標記。"""
    event = event_of("github.com", "github_pr", "pull_request", "github/pull-request-merged.json")
    steps = steps_for("parse_pr_diff")
    steps[1] = ProcStep(tool="normalize_ticket", args={"parsed": "$steps[0]"})
    with pytest.raises(PermanentError, match="kind"):
        execute_recorded_steps(event, steps, default_registry())


@pytest.mark.xfail(not PR_APPROVED, strict=True, reason="O6 尚未核定 github.com/pull_request")
def test_release_parser_returns_changes_and_index_picks_one() -> None:
    row = {(r.domain, r.event_type): r for r in APPROVALS}[("github.com", "pull_request")]
    assert row.approved_by, "O6 未核定 github.com/pull_request：保持 blocked，不得補臨時 mapping"
    registry = default_registry()
    payload = json.loads((FIXTURES / row.fixture).read_text("utf-8"))
    parsed = registry.run("parse_pr_diff", {"payload": payload})
    assert isinstance(parsed["changes"], list) and parsed["changes"]
    subs = [registry.run("normalize_release", {"parsed": parsed, "index": k})
            for k in range(1, len(parsed["changes"]) + 1)]
    assert len({sub["id"] for sub in subs}) == len(subs)          # 每筆子 Release 各有 id
    assert len({sub["source_event_id"] for sub in subs}) == 1     # 但共用同一個上游事件
    assert registry.run("normalize_release", {"parsed": parsed})["id"] == subs[0]["id"]
    with pytest.raises(PermanentError):
        registry.run("normalize_release", {"parsed": parsed, "index": len(subs) + 1})
```

與原稿的三處差異（實際落地版本如上）：

1. **`FIXTURES` 改用 `REPO_ROOT`**：原稿的 `Path("tests/fixtures")` 是相對路徑，CWD 不是 repo
   根目錄時會讀不到 fixture。改成 `Path(__file__).resolve().parents[2]`，與 repo 既有的
   `test_o6_github_mapping.py`／`test_proc_concurrency.py` 同一個寫法。
2. **未核定來源用 `xfail(strict=True)` 收尾**：gate 的要求是「以明確 gate failure 結束、不得用臨時
   mapping 讓它變綠、不是 skip」。`pytest.param(..., marks=pytest.mark.xfail(strict=True, reason=...))`
   同時滿足三件事——測試報告逐列印出 `XFAIL ... O6 尚未核定 <domain>/<event_type>`（不是 skip）、
   斷言真的執行並失敗、而且一旦有人補臨時 mapping 讓它通過就會 `XPASS` 被 strict 判成紅燈。
   這也是 Phase 31 `test_o6_github_mapping.py` 已經在用的同一個前例（`not PR_APPROVED` 那三行）。
3. **多一行 `assert steps[-1].tool == FINAL_TOOL`**：00B ING Rule 13 指定的可執行斷言就落在本檔，
   原稿只靠 `execute_recorded_steps` 內部的 `validate_recorded_steps` 間接涵蓋，補一行直接斷言。
   另外補上型別註記（`leaf_strings(value: JSONValue)`、`row: SourceApproval`）與一處換行，
   讓 `uv run ruff check tests` 的 100 字元上限通過。


- [x] **Step 2：執行並確認紅燈** — 跑 `uv run pytest tests/integration/test_adapter_fixtures.py -q`，預期 FAIL；`default_registry` 尚未建立，且未核定來源以斷言失敗印出 blocked 訊息，不是 skip。

- [x] **Step 3：建立最小實作**

```python
def parse_github_issue(arguments: Mapping[str, JSONValue]) -> JSONValue:
    payload = arguments["payload"]
    issue, repo = payload["issue"], payload["repository"]
    return {"kind": "ticket", "source": "github_issue", "text": issue["body"],
            "author_id": payload["sender"]["id"], "number": issue["number"],
            "owner": repo["owner"]["login"], "repo": repo["name"], "ts": issue["created_at"]}


def default_registry() -> ToolRegistry:
    return ToolRegistry(tools={
        "parse_github_issue": parse_github_issue, "parse_discord_message": parse_discord_message,
        "parse_support_email": parse_support_email, "parse_pr_diff": parse_pr_diff,
        "parse_changelog": parse_changelog, "normalize_ticket": normalize_ticket,
        "normalize_release": normalize_release, "validate": validate})
```

其餘四個 parser 依同一形狀實作：只讀 fixture 已有的欄位、輸出帶 `kind`，**不自己產生 ID 或 user**。`normalize_ticket`／`normalize_release` 先檢查 `kind`（不符丟 `PermanentError("kind 不相容…")`），再用 [Phase 13](./13-Phase13-O6來源ID與穩定使用者契約.md) 的 `github_ticket_id`／`github_release_id`／`github_user_id`／`stable_user_from_import` 算出 `id` 與穩定 user，並把 Phase 31 要求的 `source`、`ts` 照抄、`project_id` 一律填 Phase 02 的 `DEFAULT_PROJECT_ID`（工具只吃 `arguments`，拿不到 `Settings`，所以這裡不猜專案）；`validate` 呼叫 Phase 31 的 `validate_ticket`／`validate_release` 後回 `model_dump(mode="json")`，缺欄位由它丟 `IngressError`。

兩個 release parser 多一步：先把 diff 或 changelog 拆成 `changes` 清單（一個功能變更一筆），`normalize_release` 再用 `index`（省略時為 1）挑出第 k 筆、用 `github_release_id(owner, repo, pr_number, k)` 算 `id`，`source_event_id` 對同一個 PR 永遠相同；`k` 超出清單長度丟 `PermanentError`，**不**回一個猜出來的空 Release。

- [x] **Step 4：跑完整檔案確認綠燈**

```bash
uv run pytest tests/unit/rote tests/integration/test_adapter_fixtures.py -q
uv run ruff check src/training_kb/adapters.py src/training_kb/rote.py tests/unit/rote
```

預期：已核定來源 PASS；未核定來源停在明確 gate failure，不能用臨時值讓它變綠。

實際結果：`2 passed, 5 xfailed`——PASS 的是 `github.com:issues`（唯一核定列）與「配對錯誤要被擋下」那條；5 個 XFAIL 是四列未核定來源加上 `github.com/pull_request` 的 F14 測試，每一列都印出 `O6 尚未核定 <domain>/<event_type>`。五個 adapter 的程式碼本身都已實作完成（手動驗證過 PR fixture 會產出 `r_gh-acme-copilot-pr42-1`／`-2`、共用 `gh-acme-copilot-pr42`），**擋住它們的只有 O6 gate，不是實作缺口**；核定紀錄補上 `approved_by`／`approved_at` 之後，strict xfail 會變成 XPASS 紅燈，提醒把標記拿掉。

- [x] **Step 5：提交** — `git add src/training_kb/adapters.py tests/integration/test_adapter_fixtures.py && git commit -m "test(rote): 驗證核定來源 adapter"`

## 8. 驗收矩陣

| 路徑 | 輸入 | 預期資料結果 |
|---|---|---|
| Happy／Failure／Boundary | 欄位與 `[0]` 的 path；wildcard／filter／slice／不存在欄位；index 等於陣列長度；光是 `$event` | 合法 path 取得相同記憶體值、不改動 root；其餘一律 `PermanentError`，工具呼叫數為 0。 |
| Security | 工具名為 `shell`；或未註冊工具被 `run()` 呼叫 | 建構與 `run()` 都丟 `PermanentError`，沒有 subprocess。 |
| Privacy | `ProcStep` 序列化 | 只有工具名與 path；fixture 的每個長字串值搜尋結果為零筆。 |
| Order／Pairing | `validate -> parse_changelog`；`parse_pr_diff -> normalize_ticket` | 兩者都在 `validate` 之前就 `PermanentError`。 |
| F14 | 一份 PR fixture 的 `changes` 清單 | 逐個 `index` 取得不同 `id`、相同 `source_event_id`；省略 `index` 等於 `index=1`；超出長度 `PermanentError`。 |
| Gate | `approved_by` 為空的來源 | integration 以斷言失敗印出 blocked 訊息，不建立臨時 mapping。 |

人工驗收：打開一筆序列化 PROC，逐個 argument 確認都是 `$event...` 或 `$steps[n]...`；再從 fixture 挑一段辨識度高的 body 片段去搜尋 PROC 輸出與 DynamoDB item，預期零筆。

## 9. 常見錯誤與停止條件

| 症狀 | 原因 | 修正／停止 |
|---|---|---|
| 重放不同事件卻拿到舊 ID；或 path 支援 `..`／filter | PROC 保存了真值；直接用通用 JSONPath 函式庫 | 停止 Phase 37 並改存 path；resolver 改回本 Phase 的小型白名單 parser。 |
| 任意工具可由模型輸入；或最後工具不是 validate 仍保存 | registry 允許執行期註冊；只檢查中途曾驗證 | 啟動時固定白名單（`__post_init__` 與 `run()` 都擋）；固定檢查 `steps[-1].tool == FINAL_TOOL`。 |
| 缺欄位回 `None`；或自己再定義一份 `JSONValue` | 想讓流程繼續；沒查 00A D-31 | 缺欄位一律 `PermanentError`；`JSONValue` 只從 `training_kb.pipelines.common` import。 |
| 在本 Phase 猜 Discord／email 的 ID 或 user 對應 | 想讓 integration 變綠 | 停止；`approved_by` 為空即 blocked，等 Phase 13 的核定紀錄。 |

## 10. 來源與 Rule 對照

- [接入來源事件.feature](../../spec/features/接入來源事件.feature)
  - Rule 12：「記錄的 tool 參數以 JSONPath 指向事件欄位或前一步輸出」→ **primary 在本 Phase**；Task 2 的 `test_recorded_steps_hold_paths_only_and_end_with_validate` 與 Task 3 的 `leaf_strings` 真值掃描直接斷言。
  - Rule 13：「寫回新流程前最後一個 tool 必須是通過的 validate」→ **primary 在本 Phase**；Task 2 的 `test_rejects_illegal_recorded_steps` 含「最後一步不是 validate」與「validate 出現在中途、結尾也有一個」兩個反例。
  - Rule 3（來源簽名的組成）是**相關**，primary 在 [Phase 33](./33-Phase33-Rote結構簽名與STABLE_KEYS.md)；本 Phase 只消費 Phase 13 的核定紀錄。Rule 10、14、17、18 與 [依改版更新教學](../../spec/features/依改版更新教學.feature) 的 REL Rule 1 都**不在本 Phase**：Agent 選工具、啟動流程與 PR／changelog 抽取的直接斷言在 [Phase 37](./37-Phase37-Rote-Agent回退與成功提交.md)。
- 設計 §7.2：PROC 的 steps 只含已註冊工具與 JSONPath 參數、不含真實事件值；只支援明確欄位與陣列索引；工具範圍限五個 parser、轉成 Ticket／Release、最後 `validate`。
- 設計 §14.1 與 §18 O6／決策 F02、F07：每一種來源與事件型別各有自己的固定必備 key 清單，必須由維護者核定，本計畫不猜測（F02）；resolver 或 adapter 產生永久錯誤時整條接入回傳失敗，不得寫入合法業務物件或成功 PROC（F07，實際回傳在 Phase 37）。
- [00A 共用契約與名詞](00A-共用契約與名詞.md) §3.2（`adapters.py` 由本 Phase 建立）、§6.8（八個工具名稱）、§6.9（`JSONValue` 唯一定義在 Phase 29）、D-31。

## 11. 完成清單

- [x] resolver 只接受兩個根節點、欄位與非負 index，根節點後至少一個 token；wildcard、filter、slice、recursive、引號 key、函式與負 index 全被拒絕，缺欄位不回 `None`。
- [x] registry 恰含核定的八個接入工具名稱、不接受執行期動態註冊；PROC 只保存 tool 名稱與 JSONPath，fixture 長字串值在序列化結果中零筆。
- [x] 最後一步必須是 validate，中途出現 validate 會被拒絕。
- [x] release parser 回 `{"changes": [...]}`、`normalize_release` 以 `index`（從 1）取第 k 筆子 Release，子 Release 共用 `source_event_id`。
- [x] `index` 是唯一允許的字面值參數（只在 `normalize_release`、只接受 `[1-9][0-9]*`），其他參數一律 JSONPath。
- [x] parser 與 normalizer 的 `kind` 配對在 validate 之前就擋下。
- [x] `validate` 工具只呼叫 Phase 31 的 `validate_ticket`／`validate_release`，`project_id` 取 Phase 02 的 `DEFAULT_PROJECT_ID`，缺欄位由 `IngressError` 指出，本 Phase 不自寫欄位檢查。
- [x] `JSONValue` 從 Phase 29 import（沒有第二份定義），未核定來源維持 gate failure，且沒有把計畫或 fixture 測試描述成 AWS 已部署。
