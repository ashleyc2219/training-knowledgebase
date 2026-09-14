# Phase 32：事件接受去重與流程啟動實作計畫

> **給 agentic worker：** 必須使用 `superpowers:subagent-driven-development`（建議）或 `superpowers:executing-plans` 逐項執行。

**目標：** 讓同一 canonical Ticket／Release 永久只被接受一次，並以固定 execution name 啟動正確 pipeline；重送取得原結果或續用原 execution。

**架構：** `accept_ticket`／`accept_release` 先交 O2 `OperationCoordinator.accept`，保存 canonical input reference，再呼叫 `PipelineStarter.start`。Step Functions 回 closed `ExecutionAlreadyExists` 時，必須讀 operation ledger 的原結果，不可換名字重跑或直接回成功。

**技術：** Python 3.12、pytest、boto3 Step Functions client、O2 operation ledger、私有 S3 input object。

## 1. 文件定位

- **主來源：** [設計 §7.1、§8.3、§14.1、§18 O2、§20.7](../../design/training-kb.md)。名稱與簽名以 [00A 共用契約與名詞](./00A-共用契約與名詞.md) 為準。
- **硬前置：** [Phase 10](./10-Phase10-O2操作紀錄與永久去重契約.md)／[Phase 11](./11-Phase11-O2接受順序與重啟整合驗證.md) 的 O2 重啟／重送／接受順序 gate 必須通過；[Phase 29](./29-Phase29-共用Pipeline執行器與ASL失敗語意.md) 的 `PipelineName`、[Phase 31](./31-Phase31-Ticket與Release正規化.md) 的 canonical validation 完成。
- **後續：** [Phase 37](./37-Phase37-Rote-Agent回退與成功提交.md) 成功提交、[Phase 41](./41-Phase41-Ticket-Analysis雲端流程驗收.md) Ticket 雲端驗收、[Phase 52](./52-Phase52-Release-RETIRE與流程驗收.md) Release 雲端驗收、[Phase 59](./59-Phase59-失敗復原與重送驗收.md) 故障重送。
- **不做：** 不以 DynamoDB TTL 當永久去重；不在 ASL input 塞完整事件；不把 `ExecutionAlreadyExists` 一律當成功；不啟動 Feedback／View pipeline（那是 [Phase 42](./42-Phase42-Feedback與View固定匯入.md) 的固定匯入，沒有 Step Functions）。
- **gate 狀態：** O2 尚未 PASS 前，本 Phase **不得宣稱永久去重或 FIFO 已成立**；mock 綠燈只證明程式邏輯，不是 gate 證據。「lease 不等於接受順序、TTL 不是準時解鎖」兩句必須保留。

## 2. 你在整體流程的位置

```text
normalize_then_accept(domain, adapter, event_type, headers, payload, deadline)
          |  ← Phase 30 留下的接線點；normalize 半邊由 Phase 37 補上
          v
canonical Ticket / Release（Phase 31）
          |
          v
[你在這裡] accept 半邊：operations.accept(AcceptOperation(...))
          |
          +-- duplicate 且已有 execution_arn --> 直接回既有 Acceptance
          |
          +-- accepted 或 duplicate 但尚未啟動
                   v
          put_object(operations/<op>/input.json, if_none_match=True)
                   |  record_normalized
                   v
          starter.start(pipeline, execution_name(op), 三鍵 input)
                   |  record_execution
                   v
          Phase 41 / Phase 52 的 state machine
```

## 3. 可觀察成果

同一 `t_881` 送兩次，兩次回同一 `operation_id`（`op-ticket-t_881`）與同一 execution ARN，starter 只實際呼叫一次，私有 S3 只有一個 input 物件。若 AWS 回 closed `ExecutionAlreadyExists` 而 ledger 沒有 `status == "done"` 的原結果，回 `CoordinationError`，不能偽裝成成功。

```text
第一次：accept -> status="accepted" -> 寫 input.json -> StartExecution -> arn:...:execution:training-kb-ticket-analysis:op-ticket-t_881
第二次：accept -> status="duplicate" -> 既有 record（input_ref 與 execution_arn 都在）-> 不呼叫 StartExecution
```

### 3.1 名詞小抄

| 名詞 | 白話意思 |
|---|---|
| operation（操作） | 一次可追溯、可重送而不重複的處理單位；`operation_id` 固定為 `op-<kind>-<canonical_id>`。 |
| ledger（操作紀錄） | Phase 10 寫在 DynamoDB `OPS#<operation_id>` 的那筆紀錄，是永久去重與續跑的唯一證據。 |
| `Acceptance` | `accept` 的回傳值，只有 `status`（`accepted`／`duplicate`）、`operation_id` 與 `record` 三欄。 |
| `OperationStatus` | 五個合法狀態：`accepted`、`normalized`、`started`、`done`、`failed`；**沒有** `running`。 |
| `input_ref` | 私有 S3 的 canonical 輸入 key `operations/<operation_id>/input.json`；ASL 只傳這個字串。 |
| execution name | Step Functions 執行的名字；同名同 input 才有冪等行為，所以必須由 `operation_id` 決定。 |
| `ExecutionAlreadyExists` | Step Functions 對「同名執行已存在」丟的例外；執行**已結束**時也會丟，不等於成功。 |
| `normalize_then_accept` | Phase 30 在 handler 裡留下的單一接線點：一個函式把「正規化」與「接受」串起來；本 Phase 補的是後半段（接受），前半段（Rote 正規化）由 [Phase 37](./37-Phase37-Rote-Agent回退與成功提交.md) 補。 |
| `assert_time_left` | Phase 30 的期限檢查 helper；剩餘時間用完就丟內建 `TimeoutError`，讓呼叫端知道不是程式錯誤而是來不及。 |
| O2／F09 | 設計 §18 第二個待確認事項（操作紀錄與接受順序的真實整合驗證，由 Phase 10／11 負責）；設計 §19 的功能決策 F09：同一事件只接受一次邏輯處理，重送回傳既有結果或沿用未完成執行。 |

## 4. 預計檔案

以下是實作時預計建立或修改；本計畫本身不代表它們已存在：

| 動作 | 路徑 | 責任 |
|---|---|---|
| 修改 | `src/training_kb/ingress.py` | `operation_id_for`、`execution_name` 與兩個 accept 函式；模組由 Phase 30 建立。 |
| 建立 | `src/training_kb/pipeline_starter.py` | `PipelineStarter` Protocol 與 boto3 adapter；[Phase 37](./37-Phase37-Rote-Agent回退與成功提交.md) 直接 `from training_kb.pipeline_starter import PipelineStarter`。 |
| 測試 | `tests/unit/test_ingress_acceptance.py` | 名稱決定性、去重、有限 input、錯誤流程。 |
| 測試 | `tests/integration/test_start_execution_idempotency.py` | running／closed execution 與程序重啟。 |

## 5. 固定介面

**Consumes**

```text
OperationKind / OperationStatus                                   # Phase 10 的 Literal 別名
validate_ticket(payload) / validate_release(payload)              # Phase 31，canonical 正規化
assert_time_left(deadline, *, step) -> None                       # Phase 30，逾時丟內建 TimeoutError
AcceptOperation(operation_id, kind, canonical_id, project_id, now) # Phase 10，五個欄位
Acceptance(status, operation_id, record)                          # Phase 10，status 是 accepted / duplicate
OperationRecord(...)                                              # Phase 10，有 input_ref / execution_arn，沒有 result_ref
OperationCoordinator.accept(request) / .load(operation_id)         # Phase 10
OperationCoordinator.record_normalized / .record_execution        # Phase 10
operation_ref(operation_id, name) -> str                          # Phase 10，operations/<id>/<name>.json
Repository.put_object(key, body, content_type, *, if_none_match)  # Phase 07，keyword-only
ObjectAlreadyExists / CoordinationError / TransientError          # Phase 07 / Phase 02
PermanentError                                                    # Phase 02，normalize 接縫尚未接上時丟它
PipelineName                                                      # Phase 29，三條 pipeline 的字面值
Ticket / Release                                                  # Phase 04；Release 沒有 project_id 欄位
Settings.project_id                                               # Phase 02，Release 的 project 由設定取得
```

**Produces**

```python
from collections.abc import Mapping
from typing import Protocol

from training_kb.models import Release, Ticket
from training_kb.operations import Acceptance, OperationKind
from training_kb.pipelines.common import JSONValue, PipelineName

STATE_MACHINE_NAMES: dict[PipelineName, str]   # 三條 pipeline 的 state machine 名稱

def operation_id_for(kind: OperationKind, canonical_id: str) -> str: ...
def execution_name(operation_id: str) -> str: ...

class PipelineStarter(Protocol):
    def start(self, pipeline: PipelineName, execution_name: str,
              input: dict[str, JSONValue]) -> str: ...   # 回 execution ARN

def accept_ticket(ticket: Ticket, *, deadline: float) -> Acceptance: ...
def accept_release(release: Release, *, deadline: float) -> Acceptance: ...
def accept_normalized(obj: Ticket | Release, *, deadline: float) -> Acceptance: ...
def normalize_then_accept(*, domain: str, adapter: str, event_type: str,
                          headers: Mapping[str, str],
                          payload: Mapping[str, JSONValue],
                          deadline: float) -> Acceptance: ...
```

- `operation_id_for` 固定回 `op-<kind>-<canonical_id>`（`op-ticket-t_881`、`op-release-r_42`）。本 Phase 只用到 `ticket`／`release` 兩種 kind，但型別就用 Phase 10 的 `OperationKind`；[Phase 42](./42-Phase42-Feedback與View固定匯入.md) 之後直接沿用同一個函式處理 `feedback`／`view`，行為不變。
- `execution_name(operation_id)` 必須符合 `[A-Za-z0-9_-]{1,80}`；不合規時以固定 UTF-8 SHA-256 截取，並保留 `op-<kind>-` 前綴。
- ASL input 固定只含 `operation_id`、`project_id`、`input_ref`（00A §7、設計 §14.3）。Release 沒有 `project_id` 欄位，單一專案的 Release 由 `Settings.project_id` 取得後寫進 operation 紀錄與 ASL input，**不把完整 evidence 放進 execution history**。
- **本計畫選擇：** `operations`／`starter`／`repository`／`settings` 由模組層一個可覆寫的工廠 `_wiring()` 取得（回傳 frozen dataclass，測試直接注入 fake），所以 `accept_ticket` 的簽名維持 00A 的兩個參數。`deadline` 是 Phase 30 傳進來的整體八秒期限（一個 `time.monotonic()` 浮點數），每一步開始前用 `assert_time_left(deadline, step=...)` 檢查剩餘時間，**不自己呼叫 `monotonic()`、也不重新計八秒**。
- `normalize_then_accept` 的六個參數全部是 keyword-only（00A D-60）：`domain`、`adapter`、`event_type`、小寫化的 `headers`、已解析的 `payload`、`deadline`。本 Phase 補**接受**那半邊（`accept_normalized` 依型別分派到 `accept_ticket`／`accept_release`）；正規化那半邊留一個 `_normalize(...)` 接縫，內容由 [Phase 37](./37-Phase37-Rote-Agent回退與成功提交.md) 用 Rote 填上，在那之前照 Phase 30 的做法丟 `PermanentError`，**不得先回成功**。

## 6. Task 1：固定 operation 與 execution 名稱

- [ ] **Step 1：建立失敗測試**

```python
import re

import pytest

from training_kb.ingress import execution_name, operation_id_for

def test_names_are_deterministic_and_safe():
    op = operation_id_for("ticket", "t_881")
    assert op == "op-ticket-t_881" == operation_id_for("ticket", "t_881")
    assert op != operation_id_for("release", "t_881")
    assert re.fullmatch(r"[A-Za-z0-9_-]{1,80}", execution_name(op))

@pytest.mark.parametrize("canonical_id", ["t_881", "t_" + "9" * 200, "t_會前摘要"])
def test_execution_name_always_obeys_the_step_functions_rule(canonical_id):
    name = execution_name(operation_id_for("ticket", canonical_id))
    assert re.fullmatch(r"[A-Za-z0-9_-]{1,80}", name)
    assert name.startswith("op-ticket-")
    assert name == execution_name(operation_id_for("ticket", canonical_id))
```

- [ ] **Step 2：執行並確認紅燈**

```bash
uv run pytest tests/unit/test_ingress_acceptance.py -q -k names
```

預期：FAIL，訊號包含 `cannot import name 'operation_id_for'`。

- [ ] **Step 3：建立最小實作**

```python
import hashlib
import re
import string

from training_kb.operations import OperationKind

SAFE_EXECUTION_NAME = re.compile(r"[A-Za-z0-9_-]{1,80}\Z")
_ALLOWED = set(string.ascii_letters + string.digits + "_-")

def operation_id_for(kind: OperationKind, canonical_id: str) -> str:
    return f"op-{kind}-{canonical_id}"

def execution_name(operation_id: str) -> str:
    if SAFE_EXECUTION_NAME.match(operation_id):
        return operation_id
    digest = hashlib.sha256(operation_id.encode("utf-8")).hexdigest()
    head = "".join(ch for ch in operation_id if ch in _ALLOWED)[:15]
    return f"{head}-{digest}"
```

`15 + 1 + 64 = 80`，所以截取後仍在長度上限內；SHA-256 取全長 64 個十六進位字元，不截短到有碰撞風險卻沒有測試的長度。名稱只由 kind 與已核定的 canonical ID 組成，**不含 user、comment 或 title**。

- [ ] **Step 4：跑完整檔案確認綠燈**

```bash
uv run pytest tests/unit/test_ingress_acceptance.py -q
```

預期：超長 ID、Unicode、`ticket`／`release` 同 canonical ID 三個邊界都綠燈，且同輸入兩次得到同名稱。

- [ ] **Step 5：提交**

```bash
git add src/training_kb/ingress.py tests/unit/test_ingress_acceptance.py
git commit -m "feat(ingress): 固定事件與執行名稱"
```

## 7. Task 2：先永久接受，再保存 input reference

- [ ] **Step 1：建立重送失敗測試**

`harness` 是本 Phase 的測試夾具：記錄呼叫次數的 fake `PipelineStarter`（`calls`、`pipelines`、`last_input`）、以 dict 當儲存的 fake `Repository`（`objects`）、真正的 `OperationCoordinator` 接 moto DynamoDB，外加兩個期限值 `deadline`（還有剩）與 `expired_deadline`（已過期）；`TICKET`／`RELEASE` 是 Phase 31 `validate_ticket`／`validate_release` 產出的 `t_881`、`r_gh-acme-app-pr42-1` canonical 物件。

```python
import json

def test_duplicate_ticket_starts_once(harness):
    first = harness.accept_ticket(TICKET)
    second = harness.accept_ticket(TICKET)
    assert first.status == "accepted"
    assert second.status == "duplicate"
    assert second.operation_id == first.operation_id == "op-ticket-t_881"
    assert second.record.input_ref == first.record.input_ref
    assert second.record.execution_arn == first.record.execution_arn
    assert harness.starter.calls == 1
    assert set(harness.objects) == {first.record.input_ref}
    assert set(harness.starter.last_input) == {"operation_id", "project_id", "input_ref"}
    assert TICKET.text not in json.dumps(harness.starter.last_input, ensure_ascii=False)
```

- [ ] **Step 2：執行並確認紅燈**

```bash
uv run pytest tests/unit/test_ingress_acceptance.py -q -k duplicate
```

預期：FAIL，訊號包含 `cannot import name 'accept_ticket'`。

- [ ] **Step 3：建立最小實作（固定次序）**

```python
import json
from collections.abc import Mapping

from training_kb.clock import now_utc
from training_kb.errors import CoordinationError, ObjectAlreadyExists, PermanentError
from training_kb.keys import operation_ref
from training_kb.operations import AcceptOperation, Acceptance

def accept_ticket(ticket: Ticket, *, deadline: float) -> Acceptance:
    return _accept("ticket", "ticket-analysis", ticket.id, ticket.project_id,
                   ticket.model_dump(mode="json"), deadline)

def accept_release(release: Release, *, deadline: float) -> Acceptance:
    return _accept("release", "release-update", release.id, _wiring().settings.project_id,
                   release.model_dump(mode="json"), deadline)

def _accept(kind: OperationKind, pipeline: PipelineName, canonical_id: str,
            project_id: str, payload: dict, deadline: float) -> Acceptance:
    wiring = _wiring()
    operations = wiring.operations
    operation_id = operation_id_for(kind, canonical_id)
    accepted = operations.accept(AcceptOperation(
        operation_id=operation_id, kind=kind, canonical_id=canonical_id,
        project_id=project_id, now=now_utc(),
    ))
    if accepted.status == "duplicate" and accepted.record.execution_arn:
        return accepted                      # 已完整啟動過，回既有紀錄
    assert_time_left(deadline, step="put-input")
    input_ref = _put_canonical_input_once(wiring.repository, operation_id, payload)
    if accepted.record.input_ref != input_ref:
        operations.record_normalized(operation_id, input_ref)
    assert_time_left(deadline, step="start-execution")
    arn = wiring.starter.start(pipeline, execution_name(operation_id), {
        "operation_id": operation_id, "project_id": project_id, "input_ref": input_ref,
    })
    operations.record_execution(operation_id, arn)
    record = operations.load(operation_id)
    if record is None:
        raise CoordinationError(f"{operation_id} 接受後讀不回紀錄")
    return Acceptance(status=accepted.status, operation_id=operation_id, record=record)

def _put_canonical_input_once(repository, operation_id: str, payload: dict) -> str:
    key = operation_ref(operation_id, "input")
    body = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    try:
        repository.put_object(key, body, "application/json", if_none_match=True)
    except ObjectAlreadyExists:
        pass                                 # 同一 operation 重送：沿用既有輸入，不覆寫
    return key

def accept_normalized(obj: Ticket | Release, *, deadline: float) -> Acceptance:
    if isinstance(obj, Ticket):
        return accept_ticket(obj, deadline=deadline)
    return accept_release(obj, deadline=deadline)

def normalize_then_accept(*, domain: str, adapter: str, event_type: str,
                          headers: Mapping[str, str],
                          payload: Mapping[str, JSONValue],
                          deadline: float) -> Acceptance:
    assert_time_left(deadline, step="normalize")
    normalized = _normalize(domain=domain, adapter=adapter, event_type=event_type,
                            headers=headers, payload=payload)
    return accept_normalized(normalized, deadline=deadline)

def _normalize(*, domain: str, adapter: str, event_type: str,
               headers: Mapping[str, str],
               payload: Mapping[str, JSONValue]) -> Ticket | Release:
    raise PermanentError(f"Phase 37 尚未接線：{domain}/{event_type}（adapter={adapter}）")
```

**duplicate 但尚未啟動是合法的續跑**（00A D-45）：`accept` 已寫 `OPS#`、但 input 物件或 execution 還沒建立時，本次補完即可，不建立第二筆 operation、不換名字。`ObjectAlreadyExists` 用**型別**判斷，不比對訊息字串；其他 S3 錯誤照常往上拋，不吞錯。

期限檢查一律用 Phase 30 的 `assert_time_left(deadline, step=...)`（逾時丟內建 `TimeoutError`），**不要**在本模組另寫一個比 `time.monotonic()` 的私有 helper：八秒是整個 handler 共用的一段時間，本 Phase 只是消費它。`normalize_then_accept` 就是 Phase 30 handler 唯一呼叫的那個函式，六個參數全部 keyword-only；`_normalize` 是留給 [Phase 37](./37-Phase37-Rote-Agent回退與成功提交.md) 的接縫，`domain`／`adapter`／`event_type`／`headers` 四個參數本 Phase 不解讀，只原樣轉交。

- [ ] **Step 4：補五個狀態的重送測試並跑完整檔案確認綠燈**

`OperationStatus` 只有 `accepted`、`normalized`、`started`、`done`、`failed` 五個值。逐一把 ledger 預設成這五種狀態後重送，斷言 starter 呼叫次數與 object 寫入次數符合下表；Ticket 與 Release 各跑一次。

| ledger 既有狀態 | `execution_arn` | 重送時預期 |
|---|---|---|
| `accepted` | 無 | 補寫 input、啟動一次，仍是同一個 `operation_id` |
| `normalized` | 無 | 不重寫 input，啟動一次 |
| `started`／`done`／`failed` | 有 | 完全不呼叫 starter，回既有紀錄 |

同一個 Step 再補兩個小斷言：接線點會依型別分派，期限用完時丟的是 `TimeoutError`（不是 `TransientError`，也不是靜靜回成功）。

```python
from training_kb.ingress import accept_normalized, normalize_then_accept

def test_accept_normalized_dispatches_by_model(harness):
    assert accept_normalized(TICKET, deadline=harness.deadline).operation_id == "op-ticket-t_881"
    assert accept_normalized(RELEASE, deadline=harness.deadline).operation_id.startswith("op-release-")
    assert harness.starter.pipelines == ["ticket-analysis", "release-update"]

def test_normalize_then_accept_stops_when_the_deadline_is_gone(harness):
    with pytest.raises(TimeoutError):
        normalize_then_accept(
            domain="github.com", adapter="github_issue", event_type="issues",
            headers={"x-github-event": "issues"}, payload={"action": "opened"},
            deadline=harness.expired_deadline,
        )
    assert harness.starter.calls == 0
```

```bash
uv run pytest tests/unit/test_ingress_acceptance.py -q
```

預期：五種狀態都不會建立第二筆 operation，`set(harness.objects)` 永遠只有一個 key；`normalize_then_accept` 在期限已過時連 `_normalize` 都不會走到。

- [ ] **Step 5：提交**

```bash
git add src/training_kb/ingress.py tests/unit/test_ingress_acceptance.py
git commit -m "feat(ingress): 永久去重來源事件"
```

## 8. Task 3：處理 running 與 closed `ExecutionAlreadyExists`

```text
StartExecution -> ExecutionAlreadyExists
        |
        v
ledger 有 execution_arn？ -- 沒有 --> 由 state machine ARN + 名稱推導（本計畫選擇）
        |                                    |
        +-------------------+----------------+
                            v
                  describe_execution(status)
        +-------------------+--------------------------+
        v                                              v
   RUNNING                                  已結束（SUCCEEDED/FAILED/...）
        |                                  ledger.status == "done"？
  沿用原 ARN                                 是 -> 沿用原 ARN
  （必要時補寫 record_execution）             否 -> CoordinationError（需人工確認）
```

- [ ] **Step 1：建立 closed execution 失敗測試**

```python
import pytest

from training_kb.errors import CoordinationError
from training_kb.operations import OperationRecord

OP = "op-ticket-t_881"
INPUT_REF = f"operations/{OP}/input.json"
ARN = f"arn:aws:states:ap-northeast-1:111122223333:execution:training-kb-ticket-analysis:{OP}"
LIMITED_INPUT = {"operation_id": OP, "project_id": "demo", "input_ref": INPUT_REF}

def ledger_record(**overrides) -> OperationRecord:
    base = dict(
        operation_id=OP, kind="ticket", canonical_id="t_881", project_id="demo",
        status="started", input_ref=INPUT_REF, execution_arn=ARN, version_id=None,
        model_output_refs=(), proc_sample_signature=None, error=None, retryable=None,
        accept_seq=1, accepted_at=NOW, updated_at=NOW,
    )
    return OperationRecord(**(base | overrides))

def test_closed_already_exists_requires_ledger_result(harness):
    harness.sfn.start_execution.side_effect = harness.already_exists
    harness.sfn.describe_execution.return_value = {"status": "FAILED"}
    harness.operations.put(ledger_record(status="started"))
    with pytest.raises(CoordinationError, match="原結果"):
        harness.starter.start("ticket-analysis", OP, LIMITED_INPUT)
    assert harness.sfn.start_execution.call_count == 1

def test_running_already_exists_reuses_the_same_arn(harness):
    harness.sfn.start_execution.side_effect = harness.already_exists
    harness.sfn.describe_execution.return_value = {"status": "RUNNING"}
    harness.operations.put(ledger_record(status="started"))
    assert harness.starter.start("ticket-analysis", OP, LIMITED_INPUT) == ARN
```

- [ ] **Step 2：執行並確認紅燈**

```bash
uv run pytest tests/integration/test_start_execution_idempotency.py -q
```

預期：FAIL，訊號包含 `cannot import name 'PipelineStarter'` 或 `BotoPipelineStarter`。

- [ ] **Step 3：建立最小 boto3 adapter**

```python
STATE_MACHINE_NAMES: dict[PipelineName, str] = {
    "ticket-analysis": "training-kb-ticket-analysis",
    "release-update": "training-kb-release-update",
    "feedback-review": "training-kb-feedback-review",
}

class BotoPipelineStarter:
    def __init__(self, client, arns: dict[PipelineName, str], operations) -> None:
        self._client, self._arns, self._operations = client, arns, operations

    def start(self, pipeline: PipelineName, execution_name: str,
              input: dict[str, JSONValue]) -> str:
        try:
            return self._client.start_execution(
                stateMachineArn=self._arns[pipeline], name=execution_name,
                input=json.dumps(input, sort_keys=True),
            )["executionArn"]
        except self._client.exceptions.ExecutionAlreadyExists:
            return self._reuse(pipeline, execution_name, str(input["operation_id"]))

    def _reuse(self, pipeline: PipelineName, execution_name: str, operation_id: str) -> str:
        record = self._operations.load(operation_id)
        arn = record.execution_arn if record else None
        if arn is None:
            arn = f'{self._arns[pipeline].replace(":stateMachine:", ":execution:")}:{execution_name}'
        status = self._client.describe_execution(executionArn=arn)["status"]
        if status == "RUNNING":
            if record is not None and record.execution_arn is None:
                self._operations.record_execution(operation_id, arn)
            return arn
        if record is not None and record.status == "done":
            return arn
        raise CoordinationError(f"{operation_id} 的同名執行已結束但 ledger 沒有原結果，需人工確認")
```

`STATE_MACHINE_NAMES` 是 00A §3.5 固定的 state machine 名稱；部署時由它與帳號、Region 組出 `arns`，測試直接注入假 ARN。ledger 沒有 `execution_arn` 時才推導執行 ARN，這是**本計畫選擇**，必須由 [Phase 41](./41-Phase41-Ticket-Analysis雲端流程驗收.md) 的雲端驗收實證後才可信賴。

- [ ] **Step 4：補重啟與禁止改名測試並跑完整檔案確認綠燈**

- 建立新的 adapter 物件（模擬程序重啟），只憑持久 ledger 仍取得同一個 `operation_id`、`input_ref` 與 ARN。
- 斷言 `start_execution` 的 `name` 參數在任何分支都等於 `execution_name(operation_id)`：**不得追加 timestamp、random suffix 或新的 operation ID**。
- ledger 沒有 `execution_arn` 且推導出的執行已結束、`status != "done"` 時，仍必須是 `CoordinationError`。

```bash
uv run pytest tests/integration/test_start_execution_idempotency.py -q
```

預期：running／done／ambiguous 三個分支全綠，`start_execution` 每個案例都只呼叫一次。

- [ ] **Step 5：提交**

```bash
git add src/training_kb/pipeline_starter.py tests/integration/test_start_execution_idempotency.py
git commit -m "fix(pipeline): 沿用已存在執行結果"
```

## 9. 驗收

```bash
uv run pytest tests/unit/test_ingress_acceptance.py -q
uv run pytest tests/integration/test_start_execution_idempotency.py -q
```

| 路徑 | 輸入 | 預期資料結果 |
|---|---|---|
| Happy | 新的合法 `Ticket`／`Release` | `Acceptance(status="accepted")`；一個 `OPS#op-ticket-t_881`、一個 input 物件、一次對應 pipeline 的 StartExecution；Release 的 `project_id` 來自 `Settings`。 |
| Failure | StartExecution 暫時失敗 | operation 保留 `input_ref` 並標 `retryable=True`；重試沿用同一 execution name。 |
| Failure | closed `ExecutionAlreadyExists`、ledger `status != "done"` | `CoordinationError`；不回成功、不改名重跑。 |
| Boundary | 同 canonical ID 不同 kind；duplicate 但 `execution_arn` 為 `None` | `op-ticket-t_881` 與 `op-release-t_881` 不碰撞；後者續跑補齊，仍只有一筆 operation、一個 input 物件。 |
| 重啟 | 新 process 重新建立 adapter | 只憑持久 ledger 就回同一 `operation_id`、`input_ref` 與 ARN。 |

人工驗收（不能只看 PASS）：打開 fake starter 記到的 input，確認裡面沒有工單全文、evidence 原文或向量；再確認 `OPS#` item 只有一筆。**停止條件：** Phase 10／11 的 O2 gate 未通過時，本 Phase 的 mock 綠燈**不得**被寫成「永久去重已完成」；雲端證據要等 Phase 41／52。

## 10. 常見錯誤與停止條件

| 症狀 | 原因 | 修正／停止 |
|---|---|---|
| 重送建立新 execution | 名稱加時間或 UUID | 改用 deterministic `execution_name(operation_id)`。 |
| AlreadyExists 一律當 200 | 沒區分 RUNNING 與已結束 | 查 ledger 原 ARN／`status == "done"`；無證據就 `CoordinationError`。 |
| TTL 到期後事件可再接受；ASL history 出現完整 Ticket | 把 lease 當永久 ledger；直接把 model dump 傳入 | canonical key 永久保留在 `OPS#`，TTL 只管 worker lease；輸入存私有 S3，只傳 `input_ref`。 |
| `Acceptance` 沒有 `is_duplicate`、`OperationRecord` 沒有 `result_ref` | 用了舊版偽碼 | 改判 `accepted.status == "duplicate"`，欄位用 `input_ref`／`execution_arn`；狀態沒有 `running`，請用 `started`（Phase 10 是 owner）。 |
| `Release` 沒有 `project_id` | 誤把 Ticket 欄位套到 Release | 由 `Settings.project_id` 取得，寫進 operation 紀錄與 ASL input。 |
| 自己寫一個比 `time.monotonic()` 的 `_check_deadline` | 沒發現 Phase 30 已經有 `assert_time_left` | 改呼叫 `assert_time_left(deadline, step=...)`；八秒只算一次，本 Phase 只消費。 |
| `normalize_then_accept(payload, deadline=...)` 位置參數 | 沿用 Phase 30 stub 的舊寫法 | 改成 00A D-60 的六個 keyword 參數（`domain`／`adapter`／`event_type`／`headers`／`payload`／`deadline`）。 |
| 把 mock 綠燈寫成 O2 通過 | 混淆邏輯測試與 gate 證據 | 停止；O2 由 Phase 10／11 的真實 DynamoDB 證據決定。 |

## 11. 來源與 Rule 對照

- [接入來源事件.feature](../../spec/features/接入來源事件.feature)（00B 縮寫 `ING`）
  - Rule 26：「正規化成功的 Ticket 觸發 Ticket Analysis」→ **primary**；`tests/unit/test_ingress_acceptance.py` 斷言合法 Ticket 只啟動 `ticket-analysis` 一次。
  - Rule 27：「正規化成功的 Release 觸發 Release Note Update」→ **primary**；同檔斷言合法 Release 只啟動 `release-update` 一次。
  - Rule 30：「同一正規化事件重送時只處理一次」→ **相關（primary 在 [Phase 10](./10-Phase10-O2操作紀錄與永久去重契約.md)）**；本 Phase 的重送測試是接入端的表現，永久去重契約本身由 Phase 10 的 ledger 測試證明。
- [設計 §14.1、§14.2](../../design/training-kb.md)：同一事件重送取得既有結果或沿用未完成邏輯操作，不新增版本、回饋樣本或 PROC 成功樣本；StartExecution 只對「同名、同 input、仍在執行」冪等，已結束的同名執行回 `ExecutionAlreadyExists`，**不能直接當成功，也不能改名就無條件重跑**。
- [設計 §18 O2](../../design/training-kb.md)：操作紀錄與接受順序的儲存形狀待確認；TTL 與 SDK 重試都不保證永久去重。
- 設計 §19 的 F09：同一事件只接受一次邏輯處理。
- [StartExecution API](https://docs.aws.amazon.com/step-functions/latest/apireference/API_StartExecution.html)：同名執行的冪等窗口與 `ExecutionAlreadyExists` 條件；保留期限不是永久去重。

## 12. 完成清單

- [ ] canonical event key 永久對應一個 operation（`op-<kind>-<canonical_id>`）。
- [ ] operation／execution 名稱可重現、符合 `[A-Za-z0-9_-]{1,80}` 且不含敏感內容。
- [ ] ASL input 只有 `operation_id`、`project_id`、`input_ref`。
- [ ] Ticket／Release 啟動正確且唯一的 pipeline；Release 的 `project_id` 來自 `Settings`。
- [ ] `accepted`／`normalized`／`started`／`done`／`failed` 五種 ledger 狀態的重送都有測試。
- [ ] `normalize_then_accept` 是 D-60 的六個 keyword 參數，accept 半邊依型別分派到 `accept_ticket`／`accept_release`。
- [ ] 期限檢查全部走 `assert_time_left(deadline, step=...)`，模組裡沒有第二份 `monotonic()` 比較。
- [ ] duplicate 但尚未啟動時是續跑，不建立第二筆 operation。
- [ ] closed `ExecutionAlreadyExists` 不直接當成功、不換名重跑；process restart 後仍只憑持久 ledger 取得原狀態。
- [ ] O2 gate 未通過時維持 blocked 標示，沒有把 mock 綠燈寫成永久去重已完成。
