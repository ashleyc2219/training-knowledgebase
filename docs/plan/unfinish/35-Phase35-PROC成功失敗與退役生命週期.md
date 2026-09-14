# Phase 35：PROC 成功、失敗與退役生命週期實作計畫

> **給 agentic worker：** 使用 `superpowers:subagent-driven-development`（建議）或 `superpowers:executing-plans` 執行本計畫；每個 Task 先建立失敗測試，再寫最小實作。

**目標：** 讓 PROC 只在**不同事件**的完整成功後累積 `success_count`，累積到 3 才允許被重放；重放成功把連敗歸零，連續三次重放失敗就永久 retired，直到人工核定重置。

**架構：** 三個純函式吃一個 `ProvenWorkflow`、回傳一個新的 `ProvenWorkflow`，本身不碰 AWS；呼叫端（Phase 37）用 Phase 06 的 `revision_of` 取樂觀鎖版本號，再用 `update_meta(..., expected_revision=...)` 條件更新持久化，避免併發把計數蓋掉。「這次算不算新的成功樣本」由 Phase 10 的 `record_proc_sample` 判定，同一個 operation 重送不新增樣本。只有 Rote 模組可讀寫 PROC。

**技術：** Python 3.12、Pydantic v2（`ProvenWorkflow` 是 `StrictModel`，換欄位用 `model_copy(update=...)`，不是 `dataclasses.replace`）、pytest、moto DynamoDB fixture。

## 1. 文件定位

- **主來源：** [設計 §7.2、§9.1、§14.1、§20.7](../../design/training-kb.md)；名稱與型別以 [00A 共用契約與名詞](00A-共用契約與名詞.md) 第 5、6.8 節為準。
- **前置與後續：** 前置是 [Phase 10 O2 操作紀錄](10-Phase10-O2操作紀錄與永久去重契約.md) 的 `record_proc_sample`、[Phase 11 接受順序](11-Phase11-O2接受順序與重啟整合驗證.md)、[Phase 33 結構簽名](33-Phase33-Rote結構簽名與STABLE_KEYS.md)、[Phase 34 兩層命中](34-Phase34-Rote兩層命中與候選排序.md)，未通過時停止；後續是 [Phase 37 Rote Agent 回退與成功提交](37-Phase37-Rote-Agent回退與成功提交.md)，它在 validate 與 StartExecution 都成功之後才呼叫本 Phase 的三個函式。
- **不做：** 不執行 adapter、不呼叫模型、不啟動 Step Functions、不保存 canonical 物件；不因 fallback Agent 成功就宣稱原重放成功；不自動復活 retired；不讓 ingress／pipelines 直接改 PROC。以下程式檔都是實作時預計建立或修改，本計畫本身不代表它們已存在。
- **gate 狀態：** O2 尚未 PASS，本 Phase 的併發計數只能寫成「條件更新的預期行為」，**不得宣稱永久去重或計數一定不會分岔**；只有 Phase 10／11 的真實 DynamoDB 證據才能改變這句話。O6 未核定的 `(domain, event_type)` 一律 blocked，不得為了湊滿三次成功而替未核定來源建立 PROC。

## 2. 你在整體流程的位置

```text
Phase 34 兩層命中 --未命中或重放失敗--> Phase 37 Agent 選白名單工具
        | 命中並重放                             | validate + StartExecution 都成功
        v                                       v
   replay 成功／失敗 -----> [你在這裡] Phase 35：on_new_success、on_replay_success、
                                     on_replay_failure 三個純函式 + proc_changes
                                          |
        Phase 06 revision_of(pk) + update_meta(pk, changes, expected_revision)
                                          v
                              DynamoDB item PROC#<signature>
```

PROC 的狀態只有兩個，「可不可以重放」的門檻是計數不是狀態：

```text
建立（Phase 37 第一次寫入）：status=active, success_count=1, fail_count=0
   | 同一 operation 重送 -> record_proc_sample 回 False -> 不加
   v
 success_count 1 --> 2 --> 3 ...  replayable = active 且 success_count >= PROC_MIN_SUCCESS
 replay 成功 --> fail_count = 0、last_used = now
 replay 失敗 --> fail_count 1 --> 2 --> 3 --> status = retired（last_used 不動）
   -> retired：下次接入視同未命中、不重放、不自動復活；只有人工核定重置（F53）
```

## 3. 名詞小抄

| 名詞 | 白話意思 |
|---|---|
| PROC／`ProvenWorkflow`／signature | PROC 是針對某個「結構簽名」記下來的接入處理步驟順序，存成 DynamoDB 的 `PROC#<signature>` item；signature 是 Phase 33 算出的 16 字元指紋，只描述事件長相、完全不含事件值。 |
| `success_count`／`fail_count` | 由**不同事件**的完整成功累積的驗證次數（達 3 才允許重放）；`fail_count` 是**連續**重放失敗次數（決策 D20），重放成功歸零，不是歷史總失敗數。 |
| 完整成功 | validate 通過**而且** Step Functions 成功啟動；只完成欄位轉換不算。 |
| `record_proc_sample` | Phase 10 的操作紀錄方法；同一個 operation 第二次回 `False`，是「重送不加分」的永久證據。 |
| retired／`_revision` | PROC 的停用狀態（下次接入視同未命中，只有人工核定才重置）；`_revision` 是 metadata item 的樂觀鎖版本號，用 `revision_of(pk)` 取值。 |
| D20／F04／F05／F53 | 設計文件第 19 節的決策編號：連續失敗、平手取最近成功、逐次累加成功、退役後人工重置。 |

## 4. 完成後看得到什麼

- 以 signature `a1b2c3d4e5f60718`（GitHub Issue 來源）為例：`op-ticket-t_881`、`op-ticket-t_882`、`op-ticket-t_883` 三個**不同** operation 各完整成功一次後，`PROC#a1b2c3d4e5f60718` 是 `status="active"`、`success_count=3`、`fail_count=0`；Phase 34 的 `replayable(proc)` 從這一刻才回 `True`。
- 只拿 `op-ticket-t_881` 重送十次：`record_proc_sample` 只有第一次回 `True`，`success_count` 停在 1，`last_used` 也停在第一次的時間。
- 接著兩次重放失敗（`fail_count=2`）、一次重放成功（歸零並更新 `last_used`）、再三次重放失敗；第三次寫入後 `status="retired"`，第四次呼叫 `on_replay_failure` 直接丟 `PermanentError`。重放失敗後由 Agent 救回同一次事件時，`fail_count` 仍保留那一次失敗。

## 5. 預計檔案

| 動作 | 路徑 | 責任 |
|---|---|---|
| 修改 | `src/training_kb/rote.py` | `PROC_MAX_CONSECUTIVE_FAIL`、`proc_changes` 與三個狀態轉移純函式；`PROC_MIN_SUCCESS` 沿用 Phase 34，不重新宣告。 |
| 消費 | `src/training_kb/repository.py`、`src/training_kb/operations.py`、`tests/integration/conftest.py` | 只用 Phase 06 的 `revision_of`／`update_meta`／`get_proc`／`put_meta`、Phase 10 的 `record_proc_sample` 與 Phase 06 的 moto `repository` fixture；本 Phase **不修改**這三支檔案。 |
| 測試 | `tests/unit/rote/test_proc_lifecycle.py` | 狀態轉移表、同 operation 重送、retired 邊界。 |
| 測試 | `tests/integration/test_proc_concurrency.py` | 交錯條件更新、落地後的連敗歸零與退役、PROC 寫入 owner 掃描。 |

## 6. 固定介面

### Consumes

```text
Phase 05  proc_pk(signature: str) -> str                                  # "PROC#<signature>"
Phase 06  Repository.get_proc(signature: str) -> ProvenWorkflow | None
Phase 06  Repository.revision_of(pk: str) -> int                          # expected_revision 的唯一取值來源
Phase 06  Repository.update_meta(pk: str, changes: Mapping[str, DynamoValue], *,
                                 expected_revision: int) -> int           # 回新 _revision；不符丟 CoordinationError
Phase 10  OperationCoordinator.record_proc_sample(operation_id: str, signature: str) -> bool
Phase 02  to_iso(dt)；PermanentError；CoordinationError
Phase 03  ProcStatus.ACTIVE = "active"、ProcStatus.RETIRED = "retired"    # 只有兩態，沒有 candidate
Phase 04  ProvenWorkflow(signature, domain, adapter, steps, keys, success_count,
                         fail_count, status, last_used)
Phase 34  PROC_MIN_SUCCESS = 3；replayable(proc) -> bool   # 門檻常數 import 同一份，不另建
```

上面這段是 [00A 第 8 節](00A-共用契約與名詞.md) **D-05 裁決後的版本**：`update_meta` 的關鍵字
參數以 Phase 06 實作的 `*, expected_revision: int` 為準，不是舊稿的 `expected: Mapping[...]`；
Phase 35 實作時已逐字核對 `src/training_kb/repository.py`，兩者一致。區塊語言標記維持
` ```text `（D-01：Consumes 是偽簽名，不能 `ast.parse`）。00A 的 D-01／D-05 兩列把位置記成
「P35 §5 Consumes」，實際在本文件的 §6「固定介面」；只是列號漂移，裁決內容不變。

### Produces

```python
from datetime import datetime

from training_kb.models import ProvenWorkflow
from training_kb.operations import OperationCoordinator
from training_kb.repository import DynamoValue

PROC_MAX_CONSECUTIVE_FAIL = 3

def on_new_success(proc: ProvenWorkflow, operation_id: str,
                   operations: OperationCoordinator, now: datetime) -> ProvenWorkflow: ...

def on_replay_success(proc: ProvenWorkflow, now: datetime) -> ProvenWorkflow: ...
def on_replay_failure(proc: ProvenWorkflow, now: datetime) -> ProvenWorkflow: ...
def proc_changes(proc: ProvenWorkflow) -> dict[str, DynamoValue]: ...
```

三個轉移函式都是純函式：回傳新的 `ProvenWorkflow`，不寫 DynamoDB，持久化由呼叫端做（Task 3）。`on_new_success` 一定要先拿到 `record_proc_sample(...)` 回 `True` 這份**永久證據**才可以加 `success_count`；沒有證據就原樣回傳。`proc_changes` 由本 Phase 新增，[00A 第 6.8 節](00A-共用契約與名詞.md) 已與三個轉移函式、`PROC_MAX_CONSECUTIVE_FAIL` 列在同一格（owner 都是 Phase 35）：它把「哪四個欄位會變」收斂成一份，[Phase 37](37-Phase37-Rote-Agent回退與成功提交.md) 的 `_persist` 直接呼叫它，不各自拼 `changes`。**PROC 只有 `active` 與 `retired` 兩種 status**（00A §5.3）；「還不能重放」不是第三種狀態，而是 `success_count < PROC_MIN_SUCCESS`，Phase 34 的 `replayable` 是 `status == "active"` 與這個計數兩個條件同時成立。程式裡只能有一份「3」：門檻常數在 Phase 34，連敗上限 `PROC_MAX_CONSECUTIVE_FAIL` 在本 Phase。

## 7. 狀態轉移總表

| 呼叫 | `success_count` | `fail_count` | `status` | `last_used` |
|---|---|---|---|---|
| `on_new_success`，`record_proc_sample` 回 `True` | +1 | 不變 | 不變（`active`） | 設為 `now` |
| `on_new_success`，`record_proc_sample` 回 `False` | 不變 | 不變 | 不變 | 不變 |
| `on_replay_success` | 不變 | 設為 `0` | 不變（`active`） | 設為 `now` |
| `on_replay_failure`，加完 < 3 | 不變 | +1 | 不變（`active`） | 不變 |
| `on_replay_failure`，加完 == 3 | 不變 | +1 | 設為 `retired` | 不變 |
| 三者任一，`proc.status` 已是 `retired` | — | — | — | 丟 `PermanentError` |

兩個刻意的選擇：**`on_replay_failure` 不更新 `last_used`**（F04 的平手排序要的是「最近一次**成功**使用」，失敗也更新會讓連敗中的 PROC 排到最前面）；**`on_new_success` 不清 `fail_count`**（設計 §7.2 只說「重放成功將 fail_count 歸零」，被 Agent 救回的那次重放仍然是一次失敗，對應 Phase 37 的 `agent_after_replay_failure` route）。retired 則分兩層擋：Phase 37 的 `commit_success` 對 retired signature 直接回 `None`、新序列只留在 operation 紀錄，**不呼叫**這三個函式；萬一被繞過去呼叫，這三個函式就是最後一道防線，丟 `PermanentError` 而不是默默覆寫（F53）。

## 8. TDD Tasks

### Task 1：只有不同事件才累積驗證成功

- [x] **Step 1：建立失敗測試**

```python
from datetime import UTC, datetime

import pytest

from training_kb.errors import PermanentError
from training_kb.models import ProcStatus, ProcStep, ProvenWorkflow
from training_kb.rote import on_new_success

NOW = datetime(2026, 9, 13, 0, 0, tzinfo=UTC)
LATER = datetime(2026, 9, 13, 1, 0, tzinfo=UTC)
BASE = ProvenWorkflow(
    signature="a1b2c3d4e5f60718", domain="github.com", adapter="github_issue",
    steps=[ProcStep(tool="parse_github_issue", args={"body": "$event.payload.issue.body"})],
    keys=["action", "issue", "repository", "sender"],
    success_count=1, fail_count=0, status=ProcStatus.ACTIVE, last_used=NOW,
)


def proc(**changes: object) -> ProvenWorkflow:
    return BASE.model_copy(update=changes)


class FakeOperations:                 # Phase 10 record_proc_sample 的替身
    def __init__(self) -> None:
        self.samples: dict[str, str] = {}

    def record_proc_sample(self, operation_id: str, signature: str) -> bool:
        if operation_id in self.samples:
            return False
        self.samples[operation_id] = signature
        return True


def test_three_distinct_operations_reach_replayable_count() -> None:
    operations, current = FakeOperations(), proc(success_count=0)
    for index in (1, 2, 3):
        current = on_new_success(current, f"op-ticket-t_88{index}", operations, LATER)
        assert current.success_count == index
        assert current.status == ProcStatus.ACTIVE
    assert current.last_used == LATER


def test_duplicate_operation_does_not_add_sample() -> None:
    operations = FakeOperations()
    first = on_new_success(proc(success_count=0), "op-ticket-t_881", operations, NOW)
    duplicate = on_new_success(first, "op-ticket-t_881", operations, LATER)
    assert duplicate.success_count == 1
    assert duplicate.last_used == NOW


def test_retired_proc_needs_manual_reset() -> None:
    with pytest.raises(PermanentError, match="人工"):
        on_new_success(proc(status=ProcStatus.RETIRED), "op-ticket-t_999", FakeOperations(), NOW)
```

- [x] **Step 2：執行並確認紅燈**

```bash
uv run pytest tests/unit/rote/test_proc_lifecycle.py -q
```

預期：FAIL，訊號包含 `cannot import name 'on_new_success' from 'training_kb.rote'`。

- [x] **Step 3：建立最小實作**

```python
from datetime import datetime

from training_kb.errors import PermanentError
from training_kb.models import ProcStatus, ProvenWorkflow
from training_kb.operations import OperationCoordinator

PROC_MAX_CONSECUTIVE_FAIL = 3     # 連敗上限；重放門檻是 Phase 34 的 PROC_MIN_SUCCESS


def _reject_retired(proc: ProvenWorkflow) -> None:
    if proc.status == ProcStatus.RETIRED:
        raise PermanentError(f"PROC {proc.signature} 已 retired，需人工核定新序列才能重置（F53）")


def on_new_success(proc: ProvenWorkflow, operation_id: str,
                   operations: OperationCoordinator, now: datetime) -> ProvenWorkflow:
    _reject_retired(proc)
    if not operations.record_proc_sample(operation_id, proc.signature):
        return proc
    return proc.model_copy(update={"success_count": proc.success_count + 1, "last_used": now})
```

- [x] **Step 4：跑完整檔案確認綠燈**

```bash
uv run pytest tests/unit/rote/test_proc_lifecycle.py -q
```

預期：三個測試 PASS；`success_count` 只跟著 `record_proc_sample` 的 `True` 前進。

- [x] **Step 5：提交**

```bash
git add src/training_kb/rote.py tests/unit/rote/test_proc_lifecycle.py
git commit -m "feat(rote): 累積不同事件的驗證成功"
```

### Task 2：連續重放失敗退役與成功歸零

- [x] **Step 1：建立失敗測試**（沿用 Task 1 的 `proc()`、`NOW`、`LATER`）

```python
from training_kb.rote import on_replay_failure, on_replay_success


def test_replay_failure_keeps_last_used() -> None:
    failed = on_replay_failure(proc(success_count=3), LATER)
    assert (failed.fail_count, failed.status, failed.last_used) == (1, ProcStatus.ACTIVE, NOW)


def test_replay_success_resets_streak_and_updates_last_used() -> None:
    current = on_replay_failure(on_replay_failure(proc(success_count=3), LATER), LATER)
    recovered = on_replay_success(current, LATER)
    assert (recovered.fail_count, recovered.success_count, recovered.last_used) == (0, 3, LATER)
    again = on_replay_failure(recovered, LATER)
    assert (again.fail_count, again.status) == (1, ProcStatus.ACTIVE)


def test_third_consecutive_failure_retires() -> None:
    current = proc(success_count=3)
    for count in (1, 2, 3):
        current = on_replay_failure(current, LATER)
        assert current.fail_count == count
    assert current.status == ProcStatus.RETIRED
    with pytest.raises(PermanentError, match="人工"):
        on_replay_failure(current, LATER)
```

- [x] **Step 2：執行並確認紅燈**

```bash
uv run pytest tests/unit/rote/test_proc_lifecycle.py -q -k replay
```

預期：FAIL，訊號包含 `cannot import name 'on_replay_failure'`。

- [x] **Step 3：建立最小實作**

```python
def on_replay_success(proc: ProvenWorkflow, now: datetime) -> ProvenWorkflow:
    _reject_retired(proc)
    return proc.model_copy(update={"fail_count": 0, "last_used": now})


def on_replay_failure(proc: ProvenWorkflow, now: datetime) -> ProvenWorkflow:
    _reject_retired(proc)
    failures = proc.fail_count + 1
    status = ProcStatus.RETIRED if failures >= PROC_MAX_CONSECUTIVE_FAIL else proc.status
    # 刻意不使用 now：簽名保留它只為三個函式一致，實作不得偷偷更新 last_used
    return proc.model_copy(update={"fail_count": failures, "status": status})
```

- [x] **Step 4：跑完整檔案確認綠燈**

```bash
uv run pytest tests/unit/rote/test_proc_lifecycle.py -q
```

預期：六個測試全綠；`fail_count` 是連續值（D20），不是歷史總和。

- [x] **Step 5：提交**

```bash
git add src/training_kb/rote.py tests/unit/rote/test_proc_lifecycle.py
git commit -m "feat(rote): 連敗三次退役與成功歸零"
```

### Task 3：條件更新與 PROC 寫入 owner

- [x] **Step 1：建立失敗測試**

```python
from datetime import UTC, datetime
from pathlib import Path

import pytest

from training_kb.errors import CoordinationError
from training_kb.keys import proc_pk
from training_kb.models import ProcStatus, ProcStep, ProvenWorkflow
from training_kb.repository import Repository
from training_kb.rote import (on_replay_failure, on_replay_success,
                              proc_changes, replayable)

SIG, LATER = "a1b2c3d4e5f60718", datetime(2026, 9, 13, 1, 0, tzinfo=UTC)
REPO_ROOT = Path(__file__).resolve().parents[2]
PROC_OWNERS = {"keys.py", "repository.py", "rote.py"}
BASE = ProvenWorkflow(
    signature=SIG, domain="github.com", adapter="github_issue",
    steps=[ProcStep(tool="validate", args={"candidate": "$steps[0]"})],
    keys=["action", "issue", "repository", "sender"],
    success_count=3, fail_count=0, status=ProcStatus.ACTIVE, last_used=LATER,
)


def save(repository: Repository, updated: ProvenWorkflow) -> None:
    # 呼叫端的固定順序：讀 -> 純函式算 -> 條件寫；CoordinationError 由上層重讀重算
    pk = proc_pk(SIG)
    repository.update_meta(pk, proc_changes(updated),
                           expected_revision=repository.revision_of(pk))


def reload(repository: Repository) -> ProvenWorkflow:
    """重讀那筆 PROC；`get_proc` 回 `None` 代表 item 不見了，直接在這裡斷言比較好讀。"""
    stored = repository.get_proc(SIG)
    assert stored is not None
    return stored


def test_interleaved_failures_do_not_lose_a_count(repository: Repository) -> None:
    repository.put_meta(BASE)
    pk, stale = proc_pk(SIG), repository.revision_of(proc_pk(SIG))
    worker_a, worker_b = reload(repository), reload(repository)
    save(repository, on_replay_failure(worker_a, LATER))
    with pytest.raises(CoordinationError, match="revision"):
        repository.update_meta(pk, proc_changes(on_replay_failure(worker_b, LATER)),
                               expected_revision=stale)
    save(repository, on_replay_failure(reload(repository), LATER))
    assert reload(repository).fail_count == 2


def test_persisted_failures_reset_then_retire(repository: Repository) -> None:
    repository.put_meta(BASE)
    save(repository, on_replay_failure(reload(repository), LATER))
    save(repository, on_replay_success(reload(repository), LATER))
    assert reload(repository).fail_count == 0
    for _ in range(3):
        save(repository, on_replay_failure(reload(repository), LATER))
    stored = reload(repository)
    assert (stored.fail_count, stored.status) == (3, ProcStatus.RETIRED)
    assert replayable(stored) is False


def test_only_rote_touches_proc_items() -> None:
    offenders = sorted(
        str(path.relative_to(REPO_ROOT))
        for path in (REPO_ROOT / "src" / "training_kb").rglob("*.py")
        if path.name not in PROC_OWNERS
        and any(t in path.read_text(encoding="utf-8") for t in ("proc_pk(", "PROC#"))
    )
    assert offenders == [], f"只有 Rote 可以讀寫 PROC，違規檔案：{offenders}"
```

`get_proc` 回的是 `ProvenWorkflow | None`，直接接進 `on_replay_failure(...)` 時「item 不見了」
會變成 `AttributeError: 'NoneType' object has no attribute 'status'`，讀不出真正的原因，
所以統一走 `reload()`（與 Phase 34 對 `pick_layer2` 的 `assert picked is not None` 同一個理由）。
掃描範圍用 `REPO_ROOT` 而不是相對路徑 `Path("src/training_kb")`：相對路徑在非 repo 根目錄執行時
會掃到空清單、測試靜默變成永遠通過，反而失去 Rule 31 的證據力（repo 既有測試一律用
`Path(__file__).resolve().parents[2]`）。`repository` 參數補 `Repository` 型別註記同樣是既有慣例。

- [x] **Step 2：執行並確認紅燈**

```bash
uv run pytest tests/integration/test_proc_concurrency.py -q
```

預期：FAIL，訊號包含 `cannot import name 'proc_changes' from 'training_kb.rote'`。

- [x] **Step 3：建立最小實作**

```python
from training_kb.clock import to_iso
from training_kb.repository import DynamoValue


def proc_changes(proc: ProvenWorkflow) -> dict[str, DynamoValue]:
    """只序列化四個會變的欄位；signature／domain／adapter／steps／keys 建立後不再改寫。"""
    return {"success_count": proc.success_count, "fail_count": proc.fail_count,
            "status": proc.status.value, "last_used": to_iso(proc.last_used)}
```

- [x] **Step 4：跑完整檔案確認綠燈**

```bash
uv run pytest tests/unit/rote/test_proc_lifecycle.py tests/integration/test_proc_concurrency.py -q
uv run ruff check src/training_kb/rote.py tests/unit/rote tests/integration/test_proc_concurrency.py
```

預期：交錯更新最終 `fail_count == 2`（不是 1），stale revision 明確丟 `CoordinationError`，掃描測試回空清單。

- [x] **Step 5：提交**

```bash
git add src/training_kb/rote.py tests/integration/test_proc_concurrency.py
git commit -m "feat(rote): 以條件更新保護 PROC 計數"
```

## 9. 驗收矩陣

| 路徑 | 輸入 | 預期資料結果 |
|---|---|---|
| Happy | 三個不同 operation 各完整成功一次 | `success_count` 1→2→3、`status="active"`、`fail_count=0`；`replayable` 開始回 `True`。 |
| Happy | 連敗兩次後重放成功 | `fail_count=0`、`last_used=now`、`success_count` 不變。 |
| Failure | 連續三次重放失敗 | 第三次寫入後 `status="retired"`；第四次呼叫丟 `PermanentError`，數字不動。 |
| Boundary | 同一個 operation 重送十次；失敗、失敗、成功、失敗 | 前者 `record_proc_sample` 只回一次 `True`、`success_count` 停在 1；後者 `fail_count` 回到 1、`status` 仍是 `active`（成功穿插失敗不誤退役）。 |
| Boundary | 兩個 worker 讀到同一個 `_revision` | 第二次 `update_meta` 丟 `CoordinationError`；重讀重算後最終值是 2。 |
| Ownership | 掃描 `src/training_kb` | 除 `keys.py`／`repository.py` 兩支原語外，只有 `rote.py` 出現 `proc_pk(`／`PROC#`。 |

人工驗收：打開一筆累積三次成功的 PROC item，逐欄確認屬性只有 `ProvenWorkflow` 的九個欄位加上 `PK`／`SK`／`entity`／`_revision`，沒有 `attempt_id`、`retired_at` 這類模型外欄位（00A §3.6）；再打開對應三筆 `OPS#` 紀錄，確認 `proc_sample_signature` 都等於同一個 signature，而且是三個不同的 `operation_id`。

## 10. 常見錯誤與停止條件

| 症狀 | 原因 | 修正／停止 |
|---|---|---|
| 同一事件重送三次就變成可重放；或 fallback Agent 成功後 `fail_count` 歸零 | 用呼叫次數當樣本；混淆 replay 與 Agent | 一律以 `record_proc_sample` 的回傳值為準，`False` 就原樣回傳；只有 `on_replay_success` 歸零，`agent_after_replay_failure` 走 `on_new_success`。 |
| retired 下一次接入又自動變成可用 | 覆寫同 signature 的 PROC | 停止並丟 `PermanentError`；F53 要求人工核定新序列才重置。 |
| 併發兩次失敗只存下 1 | read-modify-write 沒有條件 | `revision_of` + `expected_revision`；接到 `CoordinationError` 後重讀重算，不是盲目重送同一份 changes。 |
| 用 `dataclasses.replace(proc, ...)` 換欄位；或在 `rote.py` 再寫一份 `3` | 把 `StrictModel` 當 dataclass；沒發現門檻常數已在 Phase 34 | 改用 `proc.model_copy(update={...})`；門檻一律 import `PROC_MIN_SUCCESS`。 |
| 把「還沒滿三次」寫成 `status="candidate"`，或失敗時一起更新 `last_used` | 誤以為 PROC 有三態；把 `last_used` 當「最後一次用到」 | `ProcStatus` 只有 `active`／`retired`，門檻是 `success_count >= PROC_MIN_SUCCESS`；`last_used` 依 F04 只記最近一次**成功**使用。 |
| 為了展示先把未核定來源的 PROC 湊到三次 | 想跳過 O6 | 停止；未核定 `(domain, event_type)` 維持 blocked，不得產生可重放簽名。 |

## 11. 來源與 Rule 對照

- [接入來源事件.feature](../../spec/features/接入來源事件.feature)（primary 在本 Phase 的六條；00B 指定的可觀察斷言檔 `tests/integration/test_proc_concurrency.py` 由 Task 3 建立，Rule 8 的整條完整成功路徑另由 Phase 37 的 `tests/integration/test_rote_commit.py` 落地）
  - Rule 8：「新流程每次完整成功才將 success_count 加 1」→ Task 1 的 `test_three_distinct_operations_reach_replayable_count` 與 `test_duplicate_operation_does_not_add_sample`。
  - Rule 15：「每次重放失敗時 fail_count 增加 1」→ Task 2 的 `test_third_consecutive_failure_retires` 逐次斷言，Task 3 的 `test_persisted_failures_reset_then_retire` 再驗落地值。
  - Rule 16：「重放成功時 fail_count 歸零」→ Task 2 的 `test_replay_success_resets_streak_and_updates_last_used` 與 Task 3 同一個整合測試。
  - Rule 19：「同一流程連續三次重放失敗後 status 變為 retired」→ Task 2 與 Task 3 的 `status == ProcStatus.RETIRED` 斷言。
  - Rule 20：「已退役流程在下次接入時視同未命中」→ Task 2 的 retired 邊界與 `_reject_retired`，Task 3 對落地後的 PROC 斷言 `replayable(stored) is False`（選取端由 Phase 34 保證）。
  - Rule 31：「只有 Rote 接入層讀寫 PROVEN_WORKFLOW」→ Task 3 的 `test_only_rote_touches_proc_items`。
  - Rule 6、7（第一層只重放 active 且 `success_count >= 3`）在本 Phase 是**相關**（primary 在 [Phase 34](34-Phase34-Rote兩層命中與候選排序.md)）：本 Phase 只負責把這兩個欄位算成正確的值。
- 設計決策：D20（`fail_count` 是連續失敗，成功歸零，達 3 退役）、F05（首次完整成功記 1，同簽名事件再由 Agent 完成才累加）、F53（退役簽名保持停用，人工核定新序列後才明確重置）、F04（平手取最近成功使用者，所以失敗不更新 `last_used`）。
- [設計 §7.2、§14.1](../../design/training-kb.md)：validate 通過且 Step Functions 成功啟動才算完整成功；同一事件的重送不提供新的成功樣本；已 retired 的 PROC 不重放、歷史保留。實際接線在 Phase 37。
- [00A 共用契約與名詞](00A-共用契約與名詞.md) §5.1、§5.3、§6.3、§6.4、§6.8：`ProvenWorkflow` 九個欄位、`ProcStatus` 只有兩態，以及 `update_meta(expected_revision)`／`revision_of`／`record_proc_sample` 的 canonical 簽名。

## 12. 完成清單

- [x] 新 PROC 的第一次完整成功是 1，第三次才讓 `replayable` 成立；過程中 `status` 一直是 `active`。
- [x] 同一個 operation 重送不新增樣本，且判斷依據是 `record_proc_sample` 的 `False`，不是呼叫次數。
- [x] `on_replay_success` 只清 `fail_count` 並更新 `last_used`、不虛增驗證樣本；連續三次重放失敗才 retired，中間出現一次成功會重新計算連敗。
- [x] `on_replay_failure` 不更新 `last_used`；fallback Agent 成功也不抹除既有連敗。
- [x] retired 不會自動復活，三個函式都丟 `PermanentError`。
- [x] 條件更新測試證明交錯更新不遺失、stale revision 丟 `CoordinationError`，掃描測試證明只有 Rote 會讀寫 PROC item，且文件沒有把 O2 寫成已 PASS。
