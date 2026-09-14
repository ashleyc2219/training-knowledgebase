# Phase 37：Rote Agent 回退與成功提交實作計畫

> **給 agentic worker：** 逐項執行 checkbox；實作時使用 `superpowers:subagent-driven-development` 或 `superpowers:executing-plans`，每個 Task 都保留紅燈與綠燈證據。

**目標：** 串起 Rote 三層接入；重放失敗時同一次事件改走 Agent，並且只有正規化驗證與 Step Functions 啟動都成功後才提交 PROC 成功。

**架構：** `Rote.normalize` 先用 Phase 34 的 exact／similar PROC，無命中或重放失敗才讓 Writer 在 Phase 36 白名單中選工具。它只回傳已驗證的 `NormalizationResult`；呼叫端交給 Phase 32 的 `accept_ticket`／`accept_release` 保存 canonical 物件並啟動固定 pipeline，拿到 execution ARN 後才呼叫 `Rote.commit_success`。

**技術：** Python 3.12、pytest、既有 Writer tool loop、O2 operation ledger、Phase 36 ToolRegistry。

## 全域限制

- 唯一主來源是 [Training KB 設計 §7.1–§7.4、§14.1、§14.3、§18 O2／O6](../../design/training-kb.md)。
- 前置為 [Phase 32 事件接受](./32-Phase32-事件接受去重與流程啟動.md)、[Phase 34 兩層命中](./34-Phase34-Rote兩層命中與候選排序.md)、[Phase 35 PROC 生命週期](./35-Phase35-PROC成功失敗與退役生命週期.md) 與 [Phase 36 Adapter](./36-Phase36-JSONPath與白名單Adapter.md)；任一未通過時停止。
- 下一階段是 [Phase 38 Ticket embedding](./38-Phase38-Ticket-Embedding與群中心分群.md)；Release 的功能定位由 Phase 49 接續。
- 本階段不做：不改簽名公式（Phase 33）、不改兩層命中規則（Phase 34）、不改 PROC 狀態轉移純函式（Phase 35）、不新增工具或 JSONPath 文法（Phase 36）、不做 embedding 或分群（Phase 38）。
- Agent 自由度只存在於接入 adapter 選擇。Ticket Analysis、Release Update 與 Feedback Review 的核心節點仍走 Standard Step Functions。Feedback／View 不進 Rote，由 Phase 42 固定匯入。
- retired PROC 保持停用；Agent 找到新序列也不能自動覆寫，必須依 F53 由人明確 reset。
- 與本 Phase 有關的 O1–O7 gate 狀態：**O6 未核對**時，該 `(domain, event_type)` 的 fixture 與 `STABLE_KEYS` 是 blocked，Task 2 只能以明確 gate failure 結束，不得用臨時 mapping 讓測試變綠；**O2 未 PASS** 時不得宣稱「同事件重送永久只計一次成功樣本」已驗收，只能說單機情境通過。FakeWriter／moto 綠燈不等於 Bedrock 或真實 Step Functions 已通過。
- 以下程式檔都是實作時預計建立或修改；本計畫沒有啟動真實 pipeline。

---

## 1. 你在整體流程的位置

```text
P33 結構簽名 -> P34 兩層命中 -> P36 工具白名單
                                   |
                                   v
     [你在這裡] P37：normalize（三層＋validate）-> commit_success
                                   |
                                   v
   P32 accept_* 保存 canonical 並啟動 ticket-analysis / release-update
                                   |
                                   v
             P38 Ticket embedding 與群中心分群
```

Replay 失敗後 Agent 若救回本次事件，核心 pipeline 仍會執行。原 replay attempt 仍是一筆失敗，不能用 Agent 成功把 `fail_count` 清零。

## 2. 完成後看得到什麼

一筆 active PROC 的 replay 在 validate 失敗後，`on_replay_failure` 只呼叫一次，同一事件接著由 Agent 產生合法 Ticket，並啟動 `ticket-analysis`。若 StartExecution 失敗，PROC success 不增加；若 Agent 最終仍非法，沒有合法物件、execution 或成功 PROC。PR／changelog fixture 經 `parse_pr_diff`／`parse_changelog` 後，直接 assertion 正規化 Release 具有 `feature`、`kind`、`old_name`、`new_name`；這裡是 REL Rule 1 的 primary 驗證，不把 Phase 31 的 validator 說成抽取實作。

## 3. 名詞小抄

| 名詞 | 白話意思 |
|---|---|
| replay | 不問模型，照已驗證 PROC 重跑 adapter；Agent fallback 則是前兩層不能用時，讓模型從固定工具清單選步驟。 |
| normalization | 把來源資料轉成 canonical Ticket 或 Release。 |
| validate | 對 canonical schema 與業務欄位做最後檢查；它同時是工具清單裡最後一個工具的名稱。 |
| commit success | 已保存物件且 pipeline 真正啟動後，才更新 PROC 計數；`route` 記的是本次走 layer1、layer2、agent 或 replay 失敗後 agent。 |
| tool loop | 模型看工具清單 → 選一個工具 → 程式執行 → 把結果餵回模型，如此反覆；本 Phase 給它固定的次數上限。 |
| `O2`／`O6`／`F53` | 設計文件的編號：[§18](../../design/training-kb.md) 七個待確認事項裡 O2 是操作紀錄與接受順序、O6 是來源完整契約；[§19](../../design/training-kb.md) 已解決決策裡 F53 是「退役簽名要人工重置」。 |
| `ING`／`REL`／`RUN` | [00B](00B-需求覆蓋對照.md) 給三份 `.feature` 的縮寫：接入來源事件、依改版更新教學、執行教學流程。 |

## 4. 預計檔案

| 動作 | 路徑 | 責任 |
|---|---|---|
| 修改 | `src/training_kb/rote.py` | `RoteRoute`、`RoteDeps`、`NormalizationResult`、`AGENT_MAX_TOOL_CALLS`、`Rote` 三層 normalize 與成功提交。 |
| 修改 | `src/training_kb/ingress.py` | 補完 `normalize_then_accept`：把 `normalize → accept_normalized → commit_success` 串成固定次序（保存與啟動由 Phase 32 的 `accept_*` 完成）。 |
| 消費 | `src/training_kb/pipeline_starter.py`、`src/training_kb/adapters.py` | Phase 32 的 `PipelineStarter`（本 Phase 只透過 `accept_*` 間接使用）與 Phase 36 的白名單工具 registry；兩支都不改。 |
| 建立 | `tests/conftest.py` | `rote_deps`、`active_proc`、`raw_issue` 三個 fixture，單元與整合測試共用。 |
| 測試 | `tests/unit/rote/test_fallback.py`、`tests/integration/test_rote_commit.py` | 命中、回退、Agent 最終失敗；operation、啟動與 PROC 計數。 |
| 測試 | `tests/integration/test_release_extraction.py` | 以 O6 PR／changelog fixture 驗證 REL Rule 1。 |

## 5. 固定介面

### Consumes

全部是更早 Phase 已定義的名稱，逐字照用；模組路徑依 [00A §3.2](00A-共用契約與名詞.md)。

```text
P02 errors      TransientError、PermanentError、IngressError(message, fields: tuple[str, ...])
                IngressError 是 PermanentError 的子類，except PermanentError 會一起接住
P03/P04 models  ProcStep、ProcStatus、ProvenWorkflow、Ticket、Release
P05 keys        proc_pk(signature: str) -> str                     # "PROC#<signature>"
P06 repository  get_proc(signature) -> ProvenWorkflow | None；put_meta(entity, *, create_only=True) -> None
                update_meta(pk, changes, *, expected_revision: int) -> int；revision_of(pk) -> int
P08 repository  list_procs(domain: str, adapter: str) -> list[ProvenWorkflow]
P10 operations  OperationCoordinator.record_proc_sample(operation_id, signature) -> bool
P13 source_ids  github_ticket_id / github_user_id / github_release_id / github_source_event_id
                SourceApproval（九欄，含 fixture 與 approved_by）；load_source_approvals(path)
P15 writing     Writer.converse_with_tools(system, messages, tools, *, operation_id, node) -> dict[str, Any]
P30 ingress     assert_time_left(deadline, *, step: str) -> None   # time.monotonic() 為基準，逾時丟 TimeoutError
P31 ingress     validate_ticket(payload) -> Ticket；validate_release(payload) -> Release
P32 ingress     accept_ticket(ticket, *, deadline: float) -> Acceptance；accept_release(release, *, deadline)
                內部一次做完「永久接受 -> 寫 canonical input -> StartExecution -> 記 execution_arn」
P32 ingress     accept_normalized(obj, *, deadline) -> Acceptance   # 依型別分派到上面兩個
                normalize_then_accept(*, domain, adapter, event_type, headers, payload, deadline)
                本 Phase 補上它的 normalize 半邊（Phase 32 已補 accept 半邊）
P33 rote        RawEvent(domain, adapter, event_type, headers, payload)；structure_signature(event) -> str
                event_stable_keys(event) -> frozenset[str]
P34 rote        replayable(proc) -> bool；pick_layer2(event, candidates) -> ProvenWorkflow | None
                find_replayable(event, signature, *, repository) -> ProvenWorkflow | None  # 兩層順序的唯一實作
P35 rote        on_new_success(proc, operation_id, operations, now)／on_replay_success(proc, now)
                on_replay_failure(proc, now)，三個都回新的 ProvenWorkflow，不寫 DynamoDB
                proc_changes(proc) -> dict[str, DynamoValue]        # _persist 的 changes 唯一來源
P36 adapters    ToolRegistry.run(name, arguments) -> JSONValue；default_registry() -> ToolRegistry
P36 rote        validate_recorded_steps(steps) -> None；execute_recorded_steps(event, steps, registry)
```

### Produces

```python
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

from training_kb.models import ProcStep, ProvenWorkflow, Release, Ticket
from training_kb.rote import RawEvent

RoteRoute = Literal["layer1", "layer2", "agent", "agent_after_replay_failure"]
AGENT_MAX_TOOL_CALLS = 6

class RoteDeps(Protocol):
    repository: "Repository"; operations: "OperationCoordinator"
    registry: "ToolRegistry"; writer: "Writer"
    now: Callable[[], datetime]

@dataclass(frozen=True)
class NormalizationResult:
    entity: Ticket | Release
    signature: str; domain: str; adapter: str
    keys: tuple[str, ...]; steps: tuple[ProcStep, ...]
    route: RoteRoute
    replayed_proc_signature: str | None
    validated: bool

class Rote:
    def __init__(self, deps: RoteDeps) -> None: ...
    def normalize(self, event: RawEvent, *, operation_id: str,
                  deadline: float) -> NormalizationResult: ...
    def normalize_all(self, event: RawEvent, *, operation_id: str,
                      deadline: float) -> tuple[NormalizationResult, ...]: ...
    def commit_success(self, result: NormalizationResult, *, operation_id: str,
                       execution_arn: str, now: datetime) -> ProvenWorkflow | None: ...
```

七個名稱都由 Phase 37 擁有，放在 `src/training_kb/rote.py`；[00A §6.8](00A-共用契約與名詞.md) 已把 `RoteRoute`／`RoteDeps`／`NormalizationResult`／`AGENT_MAX_TOOL_CALLS`／`Rote.normalize`／`Rote.normalize_all`／`Rote.commit_success` 列在同一格。`RoteDeps` 是結構型 Protocol，fake 物件直接滿足即可，也可以多帶測試專用屬性。五個補充約定：

- **`deadline` 是 `time.monotonic()` 的絕對時刻**（00A §6.8），不是「還剩幾秒」：Phase 30 的 handler 一進來就算好 `monotonic() + WEBHOOK_DEADLINE_SECONDS` 並原樣往下傳，本 Phase **不重新計八秒、也不自己呼叫 `monotonic()`**。tool loop 每一回合開始前呼叫 Phase 30 的 `assert_time_left(deadline, step=...)`，逾時就停止並回來源失敗，不把半成品當成功。
- **兩個 `operation_id` 不是同一個值。** 正規化完成前還不知道 canonical ID，所以 `normalize` 收的是本次投遞的 trace 用 ID（本計畫選擇：`op-ingress-<來源投遞識別碼>`，GitHub 取 `X-GitHub-Delivery`，手動匯入取 `<batch_id>-<序號>`），只寫進 `CallTrace` 與模型輸出 ref；`commit_success` 收的是 `accept_*` 回傳的 `Acceptance.operation_id`（`op-<kind>-<canonical_id>`），那才是 `record_proc_sample` 的永久去重鍵。
- **`AGENT_MAX_TOOL_CALLS = 6` 是 tool loop 的硬上限**（本計畫選擇）：固定序列 `parse_* → normalize_* → validate` 三步，依[設計 §14.3](../../design/training-kb.md)「業務不合法最多修正一次」給兩輪額度，超過即停止並回失敗，不得無限迴圈。
- **`domain`／`adapter`／`keys` 是給 `commit_success` 用的**：新簽名沒有既有 PROC 時，靠它們組出 `ProvenWorkflow(signature, domain, adapter, steps, keys, success_count=0, fail_count=0, status=active, last_used=now)` 才能交給 Phase 35 的 `on_new_success`。`keys` 來自 `event_stable_keys(event)` 排序後的 tuple。
- **`normalize_then_accept` 回 `list[Acceptance]`（裁決 D-73，2026-09-14）**：F14 一則事件展開成
  n 筆子 Release 時每筆各自一個 operation，list 依序列出；單一 Ticket／單一 Release 就是長度 1。
  Phase 30 的 handler 回應保留 `operation_id`（第一筆）並新增 `operation_ids` 列出全部，
  00A §6.8 的該列與 §8 的 D-73 已同步更新。
- **`normalize` 不保存 entity、不啟動 pipeline、不動 `success_count`**；`commit_success` 不接受空 ARN 或 `validated=False`，而且它是 [Phase 35](35-Phase35-PROC成功失敗與退役生命週期.md) Task 3 指定的 PROC **寫入點**：「`get_proc` 讀 → 純函式算 → `update_meta(..., expected_revision=revision_of(pk))` 條件寫」，全新簽名改用 `put_meta(..., create_only=True)`；接到 `CoordinationError` 由呼叫端重讀重算，函式內不自行重試。

## 6. 固定執行順序

```text
 RawEvent（P30 已驗簽）-> structure_signature(event)
        |
        +-- get_proc(sig) 且 replayable --+--> execute_recorded_steps
        +-- list_procs + pick_layer2 -----+      |                  |
        |                            成功 -> route=layer1/layer2   失敗
        | 兩層皆未命中                                              |
        |                       on_replay_failure -> 條件寫回 PROC -+
        v                                                          |
 +------------------------------+ <----- 同一次事件回退 ------------+
 | Agent tool loop              |  route=agent / agent_after_replay_failure
 | 上限 AGENT_MAX_TOOL_CALLS    |  工具只能來自 P36 default_registry()
 +------------------------------+
        |
 validate 通過？-- 否 --> 來源失敗：沒有合法 entity／execution／PROC
        | 是
 NormalizationResult(validated=True) -> accept_ticket / accept_release
        |
        +-- duplicate 且已有 execution_arn --> 回原 operation 與原結果；不 commit
        |
 execution_arn 非空？-- 否／例外 --> 整次失敗；不 commit
        | 是
 commit_success(result, operation_id=acceptance.operation_id, execution_arn=..., now=...)
```

四個順序重點（與上圖逐格對應）：

1. Phase 30 先驗簽、Phase 33 建 signature；Layer 1 用 `get_proc(signature)` 精確比對後**必須**再經 `replayable`（`status == "active"` 且 `success_count >= 3`），Layer 2 用 `list_procs(domain, adapter)` 取候選後交 `pick_layer2`。
2. 重放失敗：先 `on_replay_failure` 並依 §5 條件寫回，再走 Agent，`route = "agent_after_replay_failure"`；完全未命中則直接走 Agent，`route = "agent"`。工具只能來自 `default_registry()`，迴圈上限 `AGENT_MAX_TOOL_CALLS`，剩餘時間由 `assert_time_left(deadline, step=...)` 控制。
3. `validate_recorded_steps` 檢查步驟清單本身（工具在白名單、參數是 JSONPath、最後一步是 `validate`），`execute_recorded_steps` 跑出來的 `validate` 也要通過；任一不成立就是來源失敗。
4. 通過後交給 Phase 32 的 `accept_*`，它內部一次做完「永久接受 → 寫 canonical input → StartExecution → 記 `execution_arn`」，本 Phase 不重寫這三步；`status == "duplicate"` 且 `record.execution_arn` 已存在就回原 operation 與原結果，不新增樣本，拿到非空 `execution_arn` 才用 `Acceptance.operation_id` 呼叫 `commit_success`。

Agent prompt 只提供來源型別、允許工具 schema 與私有事件 reference；事件內容（payload 原文、標題、留言）一律先經 [Phase 17](17-Phase17-Claude結構化輸出與Prompt.md) 的 `_as_data` 包進 `<source_data>` 分區當**資料**，不當指令（00A §6.5、D-67）。模型不得產生 canonical ID、stable user、domain、STABLE_KEYS 或工具名稱白名單；trace 與 log 不得印出 payload 原文。

上面那條固定次序在程式裡只出現在一個地方：`normalize_then_accept`。它是 Phase 30 的 handler 唯一呼叫的接線點，六個參數全部 keyword-only（00A D-60），本 Phase 補上它的前半段（正規化）：

```python
def normalize_then_accept(*, domain: str, adapter: str, event_type: str,
                          headers: Mapping[str, str],
                          payload: Mapping[str, JSONValue],
                          deadline: float) -> list[Acceptance]:   # D-73
    assert_time_left(deadline, step="normalize")
    event = RawEvent(domain=domain, adapter=adapter, event_type=event_type,
                     headers=dict(headers), payload=dict(payload))
    deps = _rote_deps()
    rote = Rote(deps)
    accepted: list[Acceptance] = []
    for result in rote.normalize_all(event, operation_id=trace_operation_id(headers),
                                     deadline=deadline):
        acceptance = accept_normalized(result.entity, deadline=deadline)
        arn = acceptance.record.execution_arn
        if not (acceptance.status == "duplicate" and arn):   # 重送不重複提交 PROC 成功
            rote.commit_success(result, operation_id=acceptance.operation_id,
                                execution_arn=arn, now=deps.now())
        accepted.append(acceptance)
    return accepted                  # D-73：每筆子 Release 各自一個 Acceptance
```

- [Phase 30](30-Phase30-GitHub-Webhook原始Body驗簽.md) 只留 stub、[Phase 32](32-Phase32-事件接受去重與流程啟動.md) 補了 accept 半邊（`accept_normalized`），本 Phase 把 `_normalize` 那個接縫換成真的 Rote 三層，整段才完成。`domain`／`adapter`／`event_type`／`headers` 由 handler 依可信入口給（GitHub 路徑：`domain="github.com"`、`event_type` 取 `X-GitHub-Event`、`adapter` 依它對應 `github_issue`／`github_pr`），**不從 payload 反推**。
- `trace_operation_id(headers)` 產出 §5 說的 `op-ingress-<來源投遞識別碼>`（GitHub 取 `X-GitHub-Delivery`），只給 `CallTrace` 與模型輸出 ref 用；真正的永久去重鍵是 `acceptance.operation_id`。
- **F14 多個子 Release：** [Phase 36](36-Phase36-JSONPath與白名單Adapter.md) 的 release parser 回 `{"changes": [...]}`，一個 PR 改到 n 個功能就有 n 筆。`normalize_all` 對 `k = 1..n` 各跑一次「`normalize_release`（`index=k`）→ `validate`」（parser 的輸出重用，不重跑 parser），回 n 筆 `NormalizationResult`；`normalize_then_accept` 再對每一筆依序 `accept_release` → `commit_success`，**每筆各自一個 operation**（`op-release-r_gh-acme-app-pr42-1`、`...-2`），但共用同一個 `source_event_id`。Ticket 與只改到一個功能的 PR 都只會回一筆，所以 `normalize(...)` 就是 `normalize_all(...)[0]`，既有呼叫端不用改。回傳值是**全部** `Acceptance` 的 list（D-73；Phase 30 的 handler 回應同時給 `operation_id`＝第一筆與
`operation_ids`＝全部）；任何一筆失敗都原樣往上拋，已成功的那幾筆靠自己的 operation 紀錄留存，不回頭刪除。

## 7. TDD Tasks

### Task 1：重放失敗後同次回退 Agent

- [x] **Step 1：建立可獨立執行的失敗測試**

```python
from training_kb.rote import AGENT_MAX_TOOL_CALLS, Rote
from training_kb.source_ids import github_ticket_id, github_user_id

def test_replay_failure_falls_back_to_agent_once(rote_deps, active_proc, raw_issue) -> None:
    event = raw_issue()
    repo, issue = event.payload["repository"], event.payload["issue"]
    ticket_id = github_ticket_id(repo["owner"]["login"], repo["name"], issue["number"])
    agent_ticket = {
        "id": ticket_id, "source": "github_issue", "text": "找不到會議摘要按鈕",
        "author": github_user_id(event.payload["sender"]["id"]),
        "ts": issue["created_at"], "project_id": "demo",
    }
    deps = rote_deps(replay_error="缺少 author 欄位", agent_result=agent_ticket)
    result = Rote(deps).normalize(event, operation_id="op-ingress-d-1", deadline=deps.deadline)
    assert result.route == "agent_after_replay_failure"
    assert result.validated is True
    assert result.entity.id == ticket_id
    assert result.replayed_proc_signature == active_proc().signature
    assert deps.replay_failures == [active_proc().signature]
    assert deps.replay_successes == []
    assert deps.agent_calls == 1
    assert deps.tool_calls <= AGENT_MAX_TOOL_CALLS
```

`agent_ticket` 六個欄位就是 `validate_ticket` 的必填集合（00A §6.8）；少一個欄位 `validated` 就不可能是 `True`，所以測試不能只放 `id` 與 `source`。ID 與 user 一律由 Phase 13 的函式從 fixture 值算出，不手寫第二套字串。

本 Task 同時建立 `tests/conftest.py`（放 `tests/` 根目錄，`tests/unit/` 與 `tests/integration/` 都看得到）的三個 fixture：`raw_issue()` 用 `tests/fixtures/github/issue-opened.json` 組出 `RawEvent(domain="github.com", adapter="github_issue", event_type="issues", headers=..., payload=...)`；`active_proc(**overrides)` 回 `status=active`、`success_count=3`、`fail_count=0` 且 `signature == structure_signature(raw_issue())` 的 `ProvenWorkflow`，接受 `status`／`fail_count` 等覆寫（Task 3 用它造 retired 案例）；`rote_deps(**overrides)` 回一個滿足 `RoteDeps` 的 fake，額外記錄 `replay_failures`／`replay_successes`／`agent_calls`／`tool_calls`／`tool_calls_after_start`／`commit_calls`／`started`，並提供 `trace_id`、`deadline`、`execution_arn` 與 `accept(entity)`（包住 Phase 32 的 `accept_ticket`／`accept_release`）。四個旋鈕：`replay_error` 讓重放丟 `IngressError`、`agent_result` 是 Agent 最後產出的 dict、`fail_at` 在 `validate`／`save`／`start_execution` 三個切點丟 `PermanentError`、`repository` 換成真的 moto `Repository`。

- [x] **Step 2：執行紅燈** — 跑 `uv run pytest tests/unit/rote/test_fallback.py -q`，預期 FAIL，訊號是 `cannot import name 'AGENT_MAX_TOOL_CALLS'`，補上常數後變成 `Rote.normalize` 尚未實作。

- [x] **Step 3：加入最小分支**

以下三個都是 `Rote` 的方法，貼進 `src/training_kb/rote.py` 的 `class Rote` 內：

```python
def _persist(self, proc: ProvenWorkflow, *, is_new: bool = False) -> None:
    if is_new:                                  # PROC 唯一寫入形狀：讀 -> 算 -> 條件寫
        self.deps.repository.put_meta(proc, create_only=True)
        return
    pk = proc_pk(proc.signature)
    self.deps.repository.update_meta(
        pk, proc_changes(proc), expected_revision=self.deps.repository.revision_of(pk))

def _pick_proc(self, event: RawEvent) -> ProvenWorkflow | None:
    return find_replayable(event, structure_signature(event),
                           repository=self.deps.repository)

def normalize(self, event: RawEvent, *, operation_id: str, deadline: float) -> NormalizationResult:
    selected = self._pick_proc(event)
    if selected is None:
        return self._run_agent(event, operation_id, deadline, route="agent")
    try:
        return self._replay(event, selected)
    except PermanentError:                      # IngressError 是子類，一起接住
        self._persist(on_replay_failure(selected, self.deps.now()))
        return self._run_agent(event, operation_id, deadline,
                               route="agent_after_replay_failure", replayed=selected.signature)
```

三件事不可簡化：`_pick_proc` 直接 `import find_replayable`（[Phase 34](34-Phase34-Rote兩層命中與候選排序.md) 已經把「Layer 1 命中還要再經 `replayable`、不成才進 Layer 2」關進那個函式），**不要在本 Phase 重抄一份兩層順序**；`except` 只捕捉 Phase 02 的 `PermanentError` 家族，**`TransientError` 要原樣往上拋**（那是服務故障，不是這條 PROC 壞掉，不能因此累加 `fail_count`）；`_persist` 是條件寫入，`changes` 一律由 [Phase 35](35-Phase35-PROC成功失敗與退役生命週期.md) 的 `proc_changes(proc)` 產生，不各自拼一份。

- [x] **Step 4：補 layer1、layer2、retired、Agent illegal 四條路徑後跑綠** — 跑 `uv run pytest tests/unit/rote/test_fallback.py -q`，預期 PASS：layer1／layer2 兩條斷言 `deps.agent_calls == 0` 且 writer 完全沒被呼叫，retired 與未命中才是 1；Agent illegal 時 `deps.accept` 未被呼叫、`deps.started == []`、`deps.commit_calls == 0`。

- [x] **Step 5：提交**

```bash
git add src/training_kb/rote.py tests/unit/rote/test_fallback.py tests/conftest.py
git commit -m "feat(rote): 回退接入 Agent"
```

### Task 2：鎖定 PR／changelog 抽取與 validate

- [x] **Step 1：建立失敗測試**

```python
import json
from pathlib import Path

import pytest

from training_kb.adapters import default_registry
from training_kb.source_ids import github_release_id, github_source_event_id, load_source_approvals

FIXTURES = Path("tests/fixtures")
APPROVALS = {(r.domain, r.event_type): r
             for r in load_source_approvals(FIXTURES / "o6" / "approved-sources.json")}
CASES = [("github.com", "pull_request", "parse_pr_diff"),
         ("changelog.local", "manual_batch", "parse_changelog")]

@pytest.mark.parametrize(("domain", "event_type", "parser"), CASES)
def test_extraction_produces_the_four_change_fields(domain, event_type, parser) -> None:
    row = APPROVALS[(domain, event_type)]      # 核定紀錄缺這一列就是 KeyError，不吞錯
    assert row.approved_by, f"O6 gate：({domain}, {event_type}) 尚未核定，不得以臨時 mapping 讓測試變綠"
    registry = default_registry()
    payload = json.loads((FIXTURES / row.fixture).read_text(encoding="utf-8"))
    parsed = registry.run(parser, {"payload": payload})
    release = registry.run("normalize_release", {"parsed": parsed})
    validated = registry.run("validate", {"candidate": release})
    assert validated["feature"] and validated["kind"] in {"renamed", "changed", "removed"}
    if validated["kind"] == "renamed":
        assert validated["old_name"] and validated["new_name"]
    if domain == "github.com":
        owner = payload["repository"]["owner"]["login"]
        repo, number = payload["repository"]["name"], payload["number"]
        assert validated["source_event_id"] == github_source_event_id(owner, repo, number)
        assert validated["id"] == github_release_id(owner, repo, number, 1)
```

fixture 路徑由 [Phase 13](13-Phase13-O6來源ID與穩定使用者契約.md) 核定紀錄的 `SourceApproval.fixture` 提供（相對 `tests/fixtures/`），裡面**只有原始 payload、沒有 expected 區塊**；期望 ID 一律由 Phase 13 的函式對 fixture 值計算，不手寫第二套字串，「是否核定」查同一筆紀錄的 `approved_by`（空字串＝blocked）。工具參數的鍵名照 [Phase 36](36-Phase36-JSONPath與白名單Adapter.md) 的固定慣例：parser 收 `payload`、normalizer 收 `parsed`、`validate` 收 `candidate`。

- [x] **Step 2：執行紅燈** — 跑 `uv run pytest tests/integration/test_release_extraction.py -q`，預期 FAIL，訊號是 `cannot import name 'default_registry'`，或 O6 未核定時的 `O6 gate：...` 明確失敗訊息。

- [x] **Step 3：建立最小實作**

本 Task 不新增產品工具（八個工具都屬 Phase 36），只補「validate 失敗時換一個沒試過的 parser」這條 Agent 分支：

```python
def _next_parser(self, tried: set[str]) -> str | None:
    names = self.deps.registry.tools
    remaining = sorted(n for n in names if n.startswith("parse_") and n not in tried)
    return remaining[0] if remaining else None
```

`sorted` 讓同一份事件每次挑到同一個 parser，重跑結果才穩定。換 parser 的次數一樣算進 `AGENT_MAX_TOOL_CALLS`；最終 `validate` 仍失敗就回來源失敗，不建立 Release、不寫 PROC。

- [x] **Step 4：跑完整檔案確認綠燈** — 跑 `uv run pytest tests/integration/test_release_extraction.py -q`，預期兩個參數化案例 PASS，`feature`／`kind`／`old_name`／`new_name` 四欄都被直接斷言；O6 尚未核定時整支以 gate failure 結束，不能把 Phase 31 的欄位 validator 當成抽取通過。

- [x] **Step 5：提交**

```bash
git add src/training_kb/rote.py tests/integration/test_release_extraction.py
git commit -m "test(rote): 驗證改版資訊抽取"
```

### Task 3：只有完整成功才提交 PROC

- [x] **Step 1：建立失敗測試**

```python
import pytest

from training_kb.errors import PermanentError
from training_kb.models import ProcStatus
from training_kb.rote import Rote

def run_ingress(rote, event, deps):
    """§6 的固定次序：normalize -> accept_* -> 拿到非空 ARN 才 commit。"""
    result = rote.normalize(event, operation_id=deps.trace_id, deadline=deps.deadline)
    acceptance = deps.accept(result.entity)
    arn = acceptance.record.execution_arn
    if acceptance.status == "duplicate" and arn:
        return acceptance, result, None
    return acceptance, result, rote.commit_success(
        result, operation_id=acceptance.operation_id, execution_arn=arn, now=deps.now())

@pytest.mark.parametrize("broken", ["validate", "save", "start_execution"])
def test_no_success_sample_before_every_step_passes(
        repository, rote_deps, active_proc, raw_issue, broken) -> None:
    repository.put_meta(active_proc())                      # success_count=3、active
    deps = rote_deps(repository=repository, fail_at=broken)
    with pytest.raises(PermanentError):
        run_ingress(Rote(deps), raw_issue(), deps)
    assert deps.commit_calls == 0
    assert repository.get_proc(active_proc().signature).success_count == 3

def test_brand_new_sequence_records_one_sample_after_start(
        repository, rote_deps, raw_issue) -> None:
    deps = rote_deps(repository=repository, execution_arn="arn:aws:states:::execution/x")
    rote = Rote(deps)
    acceptance, result, proc = run_ingress(rote, raw_issue(), deps)
    assert deps.started == [("ticket-analysis", acceptance.operation_id)]
    assert deps.tool_calls_after_start == 0
    assert (proc.success_count, proc.fail_count, proc.status) == (1, 0, ProcStatus.ACTIVE)
    assert repository.get_proc(result.signature).success_count == 1
    assert run_ingress(rote, raw_issue(), deps)[2] is None         # 重送根本不進 commit
    same = rote.commit_success(result, operation_id=acceptance.operation_id,
                               execution_arn=deps.execution_arn, now=deps.now())
    assert same.success_count == 1                                 # 第二次 sample 回 False

def test_retired_signature_is_not_overwritten(
        repository, rote_deps, active_proc, raw_issue) -> None:
    repository.put_meta(active_proc(status=ProcStatus.RETIRED, fail_count=3))
    deps = rote_deps(repository=repository, execution_arn="arn:aws:states:::execution/y")
    _, result, proc = run_ingress(Rote(deps), raw_issue(), deps)
    assert result.route == "agent"           # retired 視同未命中
    assert proc is None
    stored = repository.get_proc(result.signature)
    assert (stored.status, stored.steps) == (ProcStatus.RETIRED, active_proc().steps)
```

`repository` 是 [Phase 06](06-Phase06-Repository-Metadata與實體讀寫.md) 的 moto 建表 fixture，名稱不另外取；`deps.accept` 與 `deps.started` 讓測試看得到 Phase 32 的 `accept_*` 實際啟動了哪一條 state machine，`tool_calls_after_start` 證明 Agent 的工具自由度只出現在接入層。三個 `fail_at` 切點在 fake 裡都丟 `PermanentError`，所以斷言用單一例外型別。

- [x] **Step 2：執行紅燈** — 跑 `uv run pytest tests/integration/test_rote_commit.py -q`，預期 FAIL，訊號包含 `AttributeError: 'Rote' object has no attribute 'commit_success'`。

- [x] **Step 3：建立最小實作**

```python
def commit_success(self, result, *, operation_id, execution_arn, now):
    if not execution_arn or not result.validated:
        raise PermanentError("啟動未成功或未通過 validate，不得提交 PROC 成功")
    stored = self.deps.repository.get_proc(result.signature)
    if stored is not None and stored.status == ProcStatus.RETIRED:
        return None                                   # F53：等待人工 reset
    if result.route in ("layer1", "layer2"):
        if stored is None:
            raise PermanentError("重放來源 PROC 已消失，不得提交成功")
        updated = on_replay_success(stored, now)
    else:
        base = stored or ProvenWorkflow(
            signature=result.signature, domain=result.domain, adapter=result.adapter,
            steps=list(result.steps), keys=list(result.keys),
            success_count=0, fail_count=0, status=ProcStatus.ACTIVE, last_used=now,
        )
        updated = on_new_success(base, operation_id, self.deps.operations, now)
    self._persist(updated, is_new=stored is None)
    return updated
```

分支條件看的是 `result.route` 而不是 `replayed_proc_signature`：`agent_after_replay_failure` 也會保留原簽名供 audit，但它**不是**一次重放成功，**不得**呼叫 `on_replay_success`。`_persist` 沿用 Task 1 建立的版本；`on_new_success` 內部先向 `record_proc_sample` 要永久證據，回 `False` 就原樣回傳，所以同一個 operation 重送不會加第二次。

- [x] **Step 4：補重送與 replay 成功兩條路徑後跑綠** — replay 成功走 `on_replay_success`（`fail_count` 歸零、`success_count` 不變），replay 失敗後被 Agent 救回時原 `fail_count` 保留。跑 `uv run pytest tests/integration/test_rote_commit.py -q`，預期只有 validate、canonical save、StartExecution 三者依序成功的全新事件增加一個樣本，失敗與重送都不增加。

- [x] **Step 5：提交**

```bash
git add src/training_kb/rote.py src/training_kb/ingress.py tests/integration/test_rote_commit.py
git commit -m "feat(rote): 延後提交完整成功"
```

## 8. 驗收矩陣

| 路徑 | 輸入 | 預期資料結果 |
|---|---|---|
| Happy | Layer 1 replay 完整成功 | `writer` 呼叫數 0；啟動後 `fail_count` 歸零、`success_count` 不變。 |
| Happy | 前兩層未命中 | Agent 只用白名單且工具呼叫數 ≤ `AGENT_MAX_TOOL_CALLS`；完整成功後新 PROC 以 `success_count=1` 建立。 |
| Failure | replay validate 失敗 | `fail_count` 加一（條件寫入成功），同次 Agent fallback，`route="agent_after_replay_failure"`。 |
| Failure | Agent 最終非法／`deadline` 用完 | tool loop 停止並回來源失敗；無 Ticket／Release、無 execution、無成功 PROC，`commit_calls == 0`，不把半成品當 `validated=True`。 |
| Failure | StartExecution 失敗 | canonical operation 保留 `input_ref` 可恢復，PROC 不加成功。 |
| Boundary | 同事件重送 | `accept_*` 回 duplicate 與原 `execution_arn`，不進 `commit_success`；直接再 commit 一次則 `record_proc_sample` 回 `False`，`success_count` 停在 1。 |
| Boundary | retired signature | 視同未命中（`replayable` 為 `False`）；`commit_success` 回 `None`，PROC 的 `steps` 與 `status` 不變。 |
| Release | renamed fixture | `feature`／`kind`／`old_name`／`new_name` 四欄與 Phase 13 函式算出的 ID 一致。 |
| Release／F14 | 一個 PR 改到兩個功能 | `normalize_all` 回兩筆；兩個 `op-release-...-1`／`-2` operation、兩次 StartExecution，`source_event_id` 相同。 |

人工驗收：檢視一筆 replay failure 後 Agent 成功的 operation audit，順序必須是 `replay_failed -> agent_validated -> execution_started`；PROC `fail_count` 保留失敗，且核心 ticket-analysis／release-update 仍有 execution。再打開該筆 `OPS#` 紀錄，確認 `proc_sample_signature` 只寫過一次，且 trace 與 log 裡搜不到 fixture 的 `title`、`login` 等 payload 原文。只看 pytest PASS 不算完成。

## 9. 常見錯誤與停止條件

| 症狀 | 原因 | 修正／停止 |
|---|---|---|
| normalize 完成就 success+1 | 把接入半成品當完整成功 | 移到 `accept_*` 回非空 `execution_arn` 後才 commit。 |
| replay 失敗便結束，或 Agent 救回後清 `fail_count` | 少了同次 Agent fallback；或拿 `replayed_proc_signature` 當分支條件 | 記失敗後走 Agent；分支看 `result.route`，只有 layer1／layer2 才 `on_replay_success`。 |
| 同事件重送增加樣本，或 retired PROC 被新 steps 覆寫 | commit 在 duplicate 判斷前；把 fallback 當自動 reset | duplicate 且已有 ARN 就回原結果不 commit；retired 停止 mutation，等待人工核定。 |
| Release 抽取只測欄位存在 | Phase 31 validator 被誤當 parser | 直接從 O6 raw fixture 跑 parser 到 canonical 欄位。 |
| tool loop 停不下來 | 沒設迴圈上限或沒看 `deadline` | 以 `AGENT_MAX_TOOL_CALLS` 與 `assert_time_left` 雙重封頂，超過就回失敗。 |
| replay 遇到 Bedrock 逾時卻加 `fail_count` | 把 `TransientError` 當資料錯誤 | 只在 `PermanentError` 家族才 `on_replay_failure`，暫時錯誤原樣往上拋。 |
| 換 parser 的順序每次不同 | 直接迭代 `registry.tools` 的插入順序 | `_next_parser` 先 `sorted`，讓重跑得到同一條序列。 |
| `_pick_proc` 自己寫兩層順序；或 `_persist` 自己拼 `changes` | 沒發現 Phase 34／35 已經有 `find_replayable`／`proc_changes` | 兩個都改成 import 同一份，行為才不會和 Phase 34 的測試分岔。 |
| `normalize_then_accept(payload, *, deadline)` | 沿用 Phase 30 stub 的舊簽名 | 改成 D-60 的六個 keyword 參數；`domain`／`adapter`／`event_type`／`headers` 由可信入口給，不從 payload 反推。 |

## 10. 來源與 Rule 對照

Rule 原文逐字取自 `.feature` 原檔；primary 歸屬依 [00B 需求覆蓋對照](00B-需求覆蓋對照.md)。

- [依改版更新教學.feature](../../spec/features/依改版更新教學.feature)
  - REL Rule 1（primary）：「從 PR diff 或 changelog 抽出 feature、kind、old_name 與 new_name」→ Task 2 的 `test_extraction_produces_the_four_change_fields` 對兩份 fixture 直接斷言四欄。
- [執行教學流程.feature](../../spec/features/執行教學流程.feature)
  - RUN Rule 3（primary）：「Agent 的工具選擇自由度只用於接入層」→ Task 3 的 `test_brand_new_sequence_records_one_sample_after_start` 斷言 `deps.started` 是固定的 `ticket-analysis` state machine，且 `tool_calls_after_start == 0`。
- [接入來源事件.feature](../../spec/features/接入來源事件.feature)
  - ING Rule 10（primary）：「前兩層皆未命中時才由 Agent 選擇 adapter tool」→ Task 1 Step 4 的 layer1／layer2 路徑斷言 `deps.agent_calls == 0`；Task 3 的 `test_retired_signature_is_not_overwritten` 在整合層斷言未命中才是 `route == "agent"`。
  - ING Rule 14（primary）：「寫回新流程前 Step Functions 必須成功啟動」→ Task 3 的 `test_no_success_sample_before_every_step_passes`（`start_execution` 參數）斷言 `commit_calls == 0`。
  - ING Rule 17（primary）：「重放或正規化驗證失敗時當次回退到 Agent」→ Task 1 的 `test_replay_failure_falls_back_to_agent_once`。
  - ING Rule 18（primary）：「Agent 最終仍無法產出合法物件時回傳失敗」→ Task 1 Step 4 的 Agent illegal 路徑，斷言 `deps.accept` 未被呼叫、`deps.started` 為空、`commit_calls == 0`。
  - ING Rule 11（**相關**，primary 在 [Phase 34](34-Phase34-Rote兩層命中與候選排序.md)，`test_rote_lookup.py`）與 ING Rule 13（**相關**，primary 在 [Phase 36](36-Phase36-JSONPath與白名單Adapter.md)）：「重放路徑不呼叫 LLM」由本 Phase 的 layer1／layer2 案例一併斷言 `writer` 呼叫數為 0；「最後一個 tool 必須是通過的 validate」由本 Phase 在 `commit_success` 前呼叫 `validate_recorded_steps` 支撐，工具白名單的直接斷言在 Phase 36。
- 設計 §7.2、§14.1：重放只省接入模型呼叫，核心 pipeline 不被跳過；重放失敗當次回退 Agent，Agent 也失敗才回「操作失敗」。
- 設計 §14.3：公開入口八秒整體期限，由 Phase 30 換算成一個 `time.monotonic()` 絕對時刻往下傳（00A §6.8）；業務不合法最多修正一次，對應 `AGENT_MAX_TOOL_CALLS`。
- [Step Functions StartExecution](https://docs.aws.amazon.com/step-functions/latest/apireference/API_StartExecution.html)：已結束的同名執行回 `ExecutionAlreadyExists`，不得直接當成功。

## 11. 完成清單

- [x] `NormalizationResult` 九個欄位（含 `domain`／`adapter`／`keys`）與 owner 固定。
- [x] `normalize_then_accept` 是 D-60 的六個 keyword 參數，整段「Rote 正規化 → `accept_normalized` → `commit_success`」只寫在這一個函式裡。
- [x] F14 的多筆子 Release 走 `normalize_all`，每筆各自 accept 一次、共用 `source_event_id`。
- [x] layer1、layer2、agent 與 fallback route 全有 assertion；Agent 只用 `default_registry()`，工具呼叫數不超過 `AGENT_MAX_TOOL_CALLS`。
- [x] `validate_recorded_steps` 在 `commit_success` 之前被呼叫，最後一步是通過的 `validate`；PR／changelog 抽取由 O6 核定紀錄的 fixture 加 Phase 13 的 ID 函式證明，沒有第二套手寫期望值。
- [x] 保存與啟動走 Phase 32 的 `accept_*`，拿到非空 `execution_arn` 才提交 PROC，且 PROC 寫入走「讀 → 算 → 條件寫」。
- [x] 重送不增加成功樣本（duplicate 不進 commit；`record_proc_sample` 第二次回 `False`）；replay failure 即使被 Agent 救回仍保留失敗，`TransientError` 不累加 `fail_count`。
- [x] retired PROC 不自動覆寫或 reset，`commit_success` 回 `None`；核心 pipeline 仍實際啟動，`deps.started` 只出現三條固定 state machine 之一。
- [x] 未把 FakeWriter 或本機 integration 結果描述成 Bedrock／AWS 已通過；O6 未核對時 Task 2 維持 gate failure。

## 12. 實作偏差紀錄（2026-09-14）

實作完成後回填；每一條都是「原稿寫 A、實際落地 B」，並附理由。名稱與簽名仍逐字採用
[00A §6.8](00A-共用契約與名詞.md)，唯一改動的 00A 是 `normalize_then_accept` 那一列（D-73）。

| # | 原稿 | 實際落地 | 理由 |
|---|---|---|---|
| 1 | Task 1 Step 2 的紅燈訊號 `cannot import name 'AGENT_MAX_TOOL_CALLS'` | **逐字相同** | — |
| 2 | Task 2 Step 2 的紅燈訊號 `cannot import name 'default_registry'` | 實際是 `AssertionError: O6 gate：(changelog.local, manual_batch) 尚未核定…`（三個案例全紅） | `default_registry` 在 Phase 36 就建立了，所以紅燈只可能來自另一個預期訊號——O6 gate。 |
| 3 | Task 3 Step 2 的紅燈訊號 `AttributeError: 'Rote' object has no attribute 'commit_success'` | 實際是 `ValueError: Invalid endpoint: https://bedrock-runtime..amazonaws.com`（接線點測試在 `_rote_deps` 還沒被注入時打到真實 Bedrock） | `commit_success` 在 Task 1 就必須存在：`rote_deps` fixture 要 monkeypatch 它來數 `commit_calls`，而那個計數是 Task 1 Step 4「Agent illegal 時 `commit_calls == 0`」的斷言對象。 |
| 4 | §5「最後一律做正規化驗證（`validate_ticket`／`validate_release`）」 | 驗證**由序列最後一步的 `validate` 工具執行**（Phase 36 的 `adapters.validate` 內部就是呼叫這兩個函式，且 `validate_recorded_steps` 保證最後一步一定是它）；`rote._validated_entity` 只把已驗證的 `model_dump(mode="json")` 還原成模型物件 | 再驗一次**會失敗**：dump 帶著 `cluster_id`／`feature_ids`／`embedding`，而 `validate_ticket` 刻意拒絕預填分析欄位的 payload（Phase 36 報告第 7 節第 1 點說「冪等」是不準確的）。`ValidationError` 仍收斂成 `IngressError`，不外洩給只認 `IngressError` 的 handler。 |
| 5 | `RoteDeps` 五個可寫屬性 | 宣告成**唯讀** `@property` | 可寫變數的 Protocol 讓 `frozen=True` 的 dataclass（`ingress.RoteWiring`）過不了 mypy strict；唯讀版更寬鬆，普通屬性、`@property` 與 bound method 三種形狀都滿足。 |
| 6 | Task 1 Step 3 的 `normalize` 直接分支 | 分支搬到 `normalize_all`，`normalize` 就是 `normalize_all(...)[0]`（00A §6.8 原文） | F14 要回多筆，兩個入口只能有一份三層順序。 |
| 7 | §6「`normalize_all` 對 `k = 1..n` 各跑一次」只描述 Agent 路徑 | **重放與 Agent 兩條路都展開**（`Rote._sub_releases`），而且展開是確定性後處理、**不算進 `AGENT_MAX_TOOL_CALLS`** | 重放一個改到 n 個功能的 PR 時只回第 1 筆會漏掉其餘子 Release；`index` 是位置資訊不是事件真值（00A §6.8），換 `k` 重跑同一條已驗證序列仍在契約內。已記錄的 `index`（預設 1）那一筆直接重用，不重跑。 |
| 8 | `record_proc_sample` 併發時回 `False` | 併發下也可能丟 `CoordinationError`；**提交端把它視為「別人已經算過」**（回既有 PROC、不重試、不當失敗） | controller 裁決 2026-09-14（Phase 35 報告第 9 節第 4 點把這一點留給 P37）。`_persist` 自己的 `CoordinationError` 仍原樣往上拋，由呼叫端重讀重算。 |
| 9 | Task 2 Step 3 新增 `_next_parser` | Task 1 就一併實作（Task 2 沒有新增任何產品程式） | Agent 的 tool loop 在 Task 1 就需要「validate 失敗換 parser」這條分支才停得下來。 |
| 10 | Task 2 的測試片段只驗 `index=1` | 擴成逐筆 `k = 1..n` 都驗，並斷言「至少一筆 `renamed` 且 `old_name`／`new_name` 非空」；另加 `test_pr_sub_release_order_matches_phase13` 交叉比對 `sub_release_ids` | PR fixture 依 `feature` 升序後 `k=1` 是 `removed`，原片段的 `if kind == "renamed"` 分支永遠不會執行，REL Rule 1 的 `old_name`／`new_name` 就沒有被真的斷言。交叉比對是 Phase 36 報告第 9 節第 4 點指名要補的。 |
| 11 | 未核定來源「以明確 gate failure 結束」 | 用 `pytest.mark.xfail(strict=True)` 收尾（與 Phase 36、Phase 31 同一種表達） | 斷言照跑、逐列印出 `O6 尚未核定 …`、不是 skip，而且補臨時 mapping 讓它通過會 XPASS 被判成紅燈；同時滿足 COMMON.md「自己的檔案全綠」。 |
| 12 | §6 的 `trace_operation_id(headers)` 沒有定義找不到識別碼時的行為 | 依序看 `x-github-delivery`、`x-tkb-delivery`（P42 手動匯入用），都沒有就回固定的 `op-ingress-unknown` | trace 的用途是對回來源那一次投遞，**不得**自己造隨機值（那會讓 trace 對不回去）。 |
| 13 | §6 只說「`deps = _rote_deps()`」 | `ingress` 新增 `RoteWiring`／`_rote_deps`／`_reset_rote_deps`／`_build_rote_deps` 四個內部名稱，與 Phase 32 的 `_wiring` 同一種形狀 | `adapters` 與 `writing` 一律在 `_build_rote_deps` **函式內** import：Phase 36 的 `adapters.validate` 反向 import `ingress`，`ingress` 模組層 import `adapters` 會變成循環 import（controller 2026-09-14）。`rote.py` 則是模組層 import `ingress`，所以 `normalize_then_accept` 內也用函式內 import 取得 `Rote`。 |
| 14 | §7 的 `rote_deps` 四個旋鈕 | `replay_error` 的落地方式是「**第一次** `validate` 丟 `IngressError`」——第一次 validate 就是重放那一次，接著的 Agent 照常 | fake 看不到「現在是哪一條路」，用呼叫次序表達最小且可預測。另外 `replay_failures`／`replay_successes`／`commit_calls` 由 monkeypatch 包住 `on_replay_failure`／`on_replay_success`／`Rote.commit_success` 取得，記到的是真的被呼叫幾次，不是測試自己推論。 |
| 15 | 未提及 Phase 30／32 既有測試 | 一併更新 `tests/integration/test_github_webhook_handler.py`（回應多了 `operation_ids`、接線點不再是 stub）與 `tests/unit/test_ingress_acceptance.py`（`_normalize` 已不存在） | D-73 與「接線點接上」都會改到這兩支的斷言；controller 明確授權更新 handler 的消費端與其測試。 |
