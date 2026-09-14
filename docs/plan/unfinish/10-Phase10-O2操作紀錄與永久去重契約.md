# Phase 10：O2 操作紀錄與永久去重契約實作計畫

> **給實作者：** 依 checkbox 逐步執行；每個 Task 先建立失敗測試，再寫最小實作。執行時使用 `superpowers:executing-plans` 或同等逐項流程。

**目標：** 建立最小的操作紀錄（operation ledger）：同一個 `operation_id` 只能被建立一次，之後的重送都拿到同一筆既有紀錄。

**架構：** `OperationCoordinator` 是唯一寫 `OPS#<operation_id>` item 的入口。`accept` 用 DynamoDB 的 `attribute_not_exists` 條件寫入；已存在就回 `duplicate` 與既有紀錄。大型內容（原始輸入、模型輸出）放私有 S3 `operations/<operation_id>/`，紀錄只存 ref。

**技術：** Python 3.12、dataclass、boto3 條件寫入、moto `mock_aws`、pytest、Phase 06 `update_meta`、Phase 07 `put_object` 與 `RESERVED_ATTRS`。

## 全域限制

- 唯一主來源是 [Training KB 設計 §7.1、§8.3、§9.3、§14.1、§14.2、§18 O2](../../design/training-kb.md)；前置為 [Phase 09：AWS 資料資源與最小 IAM](./09-Phase09-AWS資料資源與最小IAM.md)，Phase 09 未通過時停止。
- 下一階段是 [Phase 11：O2 接受順序與重啟整合驗證](./11-Phase11-O2接受順序與重啟整合驗證.md)。
- 本階段不做：不提供 lease 與接受順序（`acquire_lease`、`release_lease`、`next_sequence` 都在 Phase 11）、不啟動 Step Functions（Phase 32）、不配置版號（Phase 20）、不改 PROC 計數（Phase 35）、不建立第十一個業務實體。**本階段也不能宣稱 FIFO 或 O2 PASS。** 條件寫入只證明「同一個 `operation_id` 不會被建立第二次」；接受順序、程序重啟、交錯事件與 lease 過期都要 Phase 11 的整合證據才算數。
- 不得用 DynamoDB TTL 當永久去重；TTL 是容量管理，不保證準時也不保證保留。操作紀錄是執行資訊而非業務實體：不進 `by_target` GSI，也沒有 `target` 欄位。
- 以下程式檔均是實作時預計建立或修改；本計畫本身不代表它們已存在。

---

## 1. 你在整體流程的位置

```text
Ticket / Release / Feedback / 排程事件
                |
      +---------+------------------------+
      | [你在這裡] OperationCoordinator   |
      |  accept -> accepted | duplicate   |
      |  record_* -> 進度與 ref           |
      +---+--------------------------+---+
          v                          v
  Phase 11 接受順序與 lease   Phase 32 啟動流程
          +------------+-------------+
                       v
  Phase 20 同版號 / Phase 46 去重 / Phase 59 復原
```

## 2. 完成後看得到什麼

```text
accept(AcceptOperation("op-ticket-t_881", "ticket", "t_881", "demo", now))
  第一次 -> Acceptance(status="accepted")；第二次 -> Acceptance(status="duplicate")
  兩次的 record 逐欄相同；表內只有一筆 PK=OPS#op-ticket-t_881, SK=META
record_normalized("op-ticket-t_881", "operations/op-ticket-t_881/input.json")
  -> load(...).input_ref 有值；S3 物件由呼叫端用 if_none_match=True 另外寫入
```

同一 operation 第二次 `record_proc_sample` 一律回 `False`，這是 Phase 35 不重複累加 `success_count` 的依據。

## 3. 名詞小抄

| 名詞 | 白話意思 |
|---|---|
| operation（邏輯操作） | 一次要做完的事，例如「處理 t_881 這張工單」；重送不算新的一次。 |
| `operation_id` | 這次操作的固定名字，形狀是 `op-<kind>-<canonical_id>`（例如 `op-ticket-t_881`），由 [Phase 32](32-Phase32-事件接受去重與流程啟動.md) 的 `operation_id_for(kind, canonical_id)` 算出，不隨機產生（[00A 第 3.3 節](00A-共用契約與名詞.md)）。 |
| 永久去重 | 不靠過期時間，而是靠「這筆紀錄存在就不再建立」達成的去重。 |
| ref | 指向私有 S3 物件的 key 字串，紀錄只存路徑不存全文；compare-and-swap 則是只有目前 revision 與剛讀到的相同才更新，用來擋並行修改。 |
| 續跑 | 操作紀錄已經接受、但它要寫的物件還沒寫成功；重送時要把物件補寫完，不是回報「重複」。 |
| lease | 「同一時間只有一個人能做」的暫時鎖；本 Phase 沒有，Phase 11 才處理。 |

## 4. 預計檔案

| 動作 | 路徑 | 責任 |
|---|---|---|
| 建立 | `src/training_kb/operations.py` | 兩個 Literal 型別、三個 dataclass 與 `OperationCoordinator`。 |
| 消費 | `src/training_kb/repository.py` | `put_meta_item`、`get_meta_item` 兩個非實體 item 原語；[00A 第 6.3 節](00A-共用契約與名詞.md) 記 owner 為 P10，但實作已由 [Phase 06](06-Phase06-Repository-Metadata與實體讀寫.md) 與 `put_meta` 共用同一條條件寫入路徑一併建好，本 Phase **不改**它的簽名或行為。 |
| 修改 | `src/training_kb/keys.py` | `ops_pk` 與 `operation_ref`（[00A 第 6.2 節](00A-共用契約與名詞.md) 把兩個都放 `keys.py`，不放 `operations.py`）。 |
| 測試 | `tests/integration/test_operations_ledger.py` | 去重、進度欄位、重新載入。 |
| 測試 | `tests/unit/test_operation_refs.py` | ref 路徑與私有前綴的純函式測試。 |

## 5. 固定介面

### Consumes

```text
Repository.update_meta(pk, changes, *, expected_revision) -> int    # Phase 06
Repository.put_object(key, body, content_type, *, if_none_match)    # Phase 07
Repository.scan_entity(entity, *, consistent=True, meta_only=True) -> list[DynamoItem]  # Phase 08（測試用）
RESERVED_ATTRS / META / parse_pk / to_iso / parse_iso / CoordinationError / PermanentError
```

整合測試的 `repository` fixture 來自 [Phase 06](06-Phase06-Repository-Metadata與實體讀寫.md) 建立的 `tests/integration/conftest.py`（moto `mock_aws` 先建好 `training_kb` 表與 `by_target` 索引）。

### Produces

```python
OperationKind = Literal["ticket", "release", "feedback", "view",
                        "ticket-analysis", "release-update", "feedback-review", "analytics"]
OperationStatus = Literal["accepted", "normalized", "started", "done", "failed"]

@dataclass(frozen=True)
class AcceptOperation:
    operation_id: str
    kind: OperationKind
    canonical_id: str
    project_id: str
    now: datetime

@dataclass(frozen=True)
class OperationRecord:
    operation_id: str
    kind: OperationKind
    canonical_id: str
    project_id: str
    status: OperationStatus
    input_ref: str | None
    execution_arn: str | None
    version_id: str | None
    model_output_refs: tuple[str, ...]
    proc_sample_signature: str | None
    error: str | None
    retryable: bool | None
    accepted_at: datetime
    updated_at: datetime

@dataclass(frozen=True)
class Acceptance:
    status: Literal["accepted", "duplicate"]
    operation_id: str
    record: OperationRecord

class OperationCoordinator:
    def __init__(self, repository: Repository) -> None: ...
    def accept(self, request: AcceptOperation) -> Acceptance: ...
    def load(self, operation_id: str) -> OperationRecord | None: ...
    def record_normalized(self, operation_id: str, input_ref: str) -> None: ...
    def record_execution(self, operation_id: str, execution_arn: str) -> None: ...
    def record_model_output(self, operation_id: str, output_ref: str) -> None: ...
    def record_version(self, operation_id: str, version_id: str) -> None: ...
    def record_proc_sample(self, operation_id: str, signature: str) -> bool: ...
    def complete(self, operation_id: str, *, now: datetime) -> None: ...
    def fail(self, operation_id: str, error: str, retryable: bool, *, now: datetime) -> None: ...

# training_kb/keys.py（Phase 05 的模組，本 Phase 追加這兩個）
def ops_pk(operation_id: str) -> str: ...                     # "OPS#<operation_id>"
def operation_ref(operation_id: str, name: str) -> str: ...   # "operations/<id>/<name>.json"

class Repository:  # training_kb/repository.py；兩個非實體 item 原語（Phase 06 已建立，本 Phase 只消費）
    def put_meta_item(self, pk: str, attributes: Mapping[str, DynamoValue], *, create_only: bool = True) -> bool: ...
    def get_meta_item(self, pk: str) -> DynamoItem | None: ...
```

以上名稱與 [00A 第 6.4 節](00A-共用契約與名詞.md) 逐字一致，消費端（Phase 20、23、32、35、37、40、41、42、46、48、51、52、55、59）一律照這份簽名；`Acceptance` 沒有 `is_duplicate` 屬性、`OperationStatus` 沒有 `running`（用 `started`）、`OperationRecord` 沒有 `result_ref`（用 `input_ref`／`execution_arn`）。

`put_meta_item` 回傳「本次是否由我建立」，`False` 代表同鍵已存在；它同時服務 `OPS#` 與之後的核定設定 item（如 Phase 43 的 `CONFIG#feedback_categories`），兩者都不是十個業務實體之一。它負責補上保留屬性：`SK` 固定 `META`、`entity` 取 `parse_pk(pk)[0]`（所以 `scan_entity("OPS")` 找得到）、`_revision` 從 1 起算（與 Phase 06 的 `put_meta` 同一套），而 `target` **不寫**（操作紀錄不進 `by_target` GSI）；`attributes` 出現任何 `RESERVED_ATTRS` 內的名稱一律丟 `PermanentError`。

**Phase 11 擴充（本 Phase 不實作，但介面要留得住）：** [Phase 11](11-Phase11-O2接受順序與重啟整合驗證.md) 會在同一個 dataclass 與同一個 class 上追加下列四項，其餘欄位與方法不改名：

```text
OperationRecord.accept_seq: int | None          追加在 accepted_at 之前；accept 取號，duplicate 不重新取號
OperationCoordinator.acquire_lease(scope: str, owner: str, *, ttl_seconds: int, now: datetime) -> bool
OperationCoordinator.release_lease(scope: str, owner: str) -> None
OperationCoordinator.next_sequence(scope: str) -> int      儲存鍵 SEQ#<scope> / LEASE#<scope>，SK 同為 META
```

因此本 Phase 的 `_from_item` 對**缺少** `accept_seq` 屬性的 item 要還原成 `None`，Phase 11 追加欄位時才不必做資料遷移；`put_meta_item`／`get_meta_item` 也要能直接服務 `SEQ#`、`LEASE#` 兩種鍵。

## 6. 設計細節

`accept` 的分支只有三個，沒有「查一下再寫」的中間狀態：

```text
accept(request) -> put_meta_item("OPS#<id>", item, create_only=True)
      |
      +-- True（本次建立）---> Acceptance(status="accepted")
      +-- False（條件失敗）--> load("<id>")
               讀得到 -> Acceptance(status="duplicate", record=既有)
               讀不到 -> CoordinationError，不得當成新事件重做一次
```

「條件失敗但讀不到」是資料不一致，不是重送；安靜地重建一筆會讓同一事件產生兩條版本鏈，所以必須明確失敗。

`duplicate` 只代表「這個 `operation_id` 被接受過」，**不代表它要寫的東西已經寫完**。設計 §14.1 要求重送時「取得既有結果或沿用未完成邏輯操作」，所以契約多一條**續跑**分支（00A D-45）：

```text
Acceptance.status == "duplicate"
        |
        +-- 呼叫端去看目標物件（FEEDBACK#／VIEW# item、tutorials/<slug>/v<n>.md …）
                存在 -> 真重送：回既有結果，不新增樣本、不新增版本
                不存在 -> 續跑：沿用同一個 operation_id 補寫，仍算同一次邏輯操作
```

續跑是**合法補寫**，不算重複處理；它堵住「OPS 已寫、業務 item 未寫」之間的丟資料視窗（[Phase 42](42-Phase42-Feedback與View固定匯入.md) 的匯入入口就靠這條）。判斷「物件存不存在」一律由呼叫端做，`OperationCoordinator` 不猜；ledger 只回既有紀錄，避免它反過來依賴業務模組。

大小分工固定如下（DynamoDB 單一 item 上限 400 KB，教學全文與模型輸出都可能超過）：

```text
DynamoDB OPS#<operation_id>（小）    S3 operations/<operation_id>/（大、私有）
  status / input_ref                  input.json         正規化後的原始輸入
  execution_arn / version_id          model-<node>.json  模型輸出
  model_output_refs / error / ...     ...                重試需要的其他產物
```

S3 物件一律由呼叫端用 `if_none_match=True` 寫入；已存在就比對內容，相同即視為本次已完成，這樣儲存重試不會重新呼叫模型，也不會覆蓋原輸出（設計 §14.2）。時間欄位則有一條刻意的限制：`accept`、`complete`、`fail` 收得到 `now`，所以它們可以更新 `updated_at`；其餘 `record_*` 沒有 `now` 參數就只改自己那個欄位，不讀系統時鐘——寧可讓 `updated_at` 代表「最後一次由呼叫端提供時間的更新」，也不要塞入沒人核對過的時間。同理，`record_model_output` 對相同 ref 不重複附加，`record_proc_sample` 在 `proc_sample_signature` 已有值時回 `False`，兩者都讓重送維持「不新增樣本、不新增輸出」的契約。

「只改自己那個欄位」也包含 `status`：`record_normalized`／`record_execution`／`record_version` **不動 `status`**（§8 驗收矩陣的「其餘欄位不動」），本 Phase 只有 `accept` 寫 `accepted`、`complete` 寫 `done`、`fail` 寫 `failed`。`OperationStatus` 的 `normalized` 與 `started` 是**保留值**，留給接受路徑的 owner（[Phase 32](32-Phase32-事件接受去重與流程啟動.md)）決定要不要推進；ledger 不替呼叫端猜狀態機。`_from_item` 一律先核對 `kind`／`status` 在白名單裡才收斂成 Literal，寫錯的值在載入時就明確失敗。

## 7. TDD Tasks

### Task 1：`accept` 的永久去重

- [x] **Step 1：建立失敗測試並確認紅燈**

```python
from datetime import UTC, datetime

from training_kb.keys import operation_ref
from training_kb.operations import AcceptOperation, OperationCoordinator

NOW = datetime(2026, 9, 13, 12, 0, tzinfo=UTC)
REQUEST = AcceptOperation("op-ticket-t_881", "ticket", "t_881", "demo", NOW)


def test_second_accept_returns_the_same_record(repository) -> None:
    operations = OperationCoordinator(repository)
    first = operations.accept(REQUEST)
    second = operations.accept(REQUEST)
    assert first.status == "accepted"
    assert second.status == "duplicate"
    assert second.record == first.record
    assert len(repository.scan_entity("OPS")) == 1
```

```bash
uv run pytest tests/integration/test_operations_ledger.py -q
```

預期：FAIL，訊號包含 `No module named 'training_kb.operations'`。

- [x] **Step 2：建立最小實作**

```python
from training_kb.errors import CoordinationError
from training_kb.keys import ops_pk

class OperationCoordinator:
    def __init__(self, repository: Repository) -> None:
        self._repository = repository

    def accept(self, request: AcceptOperation) -> Acceptance:
        record = _initial_record(request)
        pk = ops_pk(request.operation_id)
        if self._repository.put_meta_item(pk, _to_item(record), create_only=True):
            return Acceptance("accepted", request.operation_id, record)
        existing = self.load(request.operation_id)
        if existing is None:
            raise CoordinationError(f"operation item is missing after conflict: {pk}")
        return Acceptance("duplicate", request.operation_id, existing)
```

`_initial_record(request)` 取 request 的四個欄位，加上 `status="accepted"`、`accepted_at=updated_at=request.now`，其餘欄位一律 `None` 或 `()`。`_to_item` 把 `datetime` 轉 `to_iso`、`tuple` 轉 `list`，`_from_item` 是它的反函式並用 `parse_iso` 還原時間。`put_meta_item` 沿用 Phase 06 的 `RESERVED_ATTRS` 檢查，`create_only=True` 時帶 `ConditionExpression="attribute_not_exists(PK)"`——複合主鍵的條件運算式是對 `Key` 指定的**那一筆 item** 判斷，再 `AND attribute_not_exists(SK)` 不會多擋到任何情形；條件失敗（`ConditionalCheckFailedException`）回 `False` 而不是丟例外。這兩個原語 Phase 06 已經建好，本 Phase 只消費。

- [x] **Step 3：補不同 kind 與遺失紀錄的測試，跑綠燈後提交**

再加三條：同一 `canonical_id` 但 `kind` 不同時是兩個 operation；把 item 直接從表刪掉後 `load` 回 `None`、`record_*` 丟 `CoordinationError`（不默默重建）；以及條件失敗卻讀不到既有 item 要拿到 `CoordinationError`。**後兩條是不同的測法**：真實的表刪掉 item 之後條件寫入就會成功，製造不出「條件失敗卻讀不到」，所以那一條用一個永遠讓 `get_meta_item` 回 `None` 的 `Repository` 子類把兩個條件湊在同一次呼叫。

```bash
uv run pytest tests/integration/test_operations_ledger.py -q
git add src/training_kb tests && git commit -m "feat(ops): 以條件寫入永久去重操作"
```

### Task 2：進度欄位、S3 ref 與樣本只算一次

- [x] **Step 1：建立失敗測試並確認紅燈**

```python
def test_progress_fields_and_single_proc_sample(repository) -> None:
    operations = OperationCoordinator(repository)
    operations.accept(REQUEST)
    output = operation_ref("op-ticket-t_881", "model-gap")
    operations.record_normalized("op-ticket-t_881", operation_ref("op-ticket-t_881", "input"))
    operations.record_model_output("op-ticket-t_881", output)
    operations.record_model_output("op-ticket-t_881", output)
    assert operations.record_proc_sample("op-ticket-t_881", "abc123") is True
    assert operations.record_proc_sample("op-ticket-t_881", "abc123") is False
    record = operations.load("op-ticket-t_881")
    assert record.input_ref == "operations/op-ticket-t_881/input.json"
    assert (record.model_output_refs, record.updated_at) == ((output,), NOW)
```

```bash
uv run pytest tests/integration/test_operations_ledger.py -q -k progress
```

預期：FAIL，訊號為缺少 `record_normalized`。

- [x] **Step 2：建立最小實作**

```python
def _existing(self, operation_id: str) -> DynamoItem:
    item = self._repository.get_meta_item(ops_pk(operation_id))
    if item is None:
        raise CoordinationError(f"unknown operation: {operation_id}")
    return item

def _change(self, operation_id: str, changes: dict[str, object]) -> None:
    revision = int(self._existing(operation_id)["_revision"])
    self._repository.update_meta(ops_pk(operation_id), changes, expected_revision=revision)

def record_proc_sample(self, operation_id: str, signature: str) -> bool:
    if self._existing(operation_id).get("proc_sample_signature") is not None:
        return False
    self._change(operation_id, {"proc_sample_signature": signature})
    return True
```

`record_normalized`、`record_execution`、`record_version` 都走 `_change`；`record_model_output` 先讀既有清單，ref 已存在就直接返回；`complete` 與 `fail` 另寫 `status` 與 `updated_at=to_iso(now)`，`fail` 再寫 `error` 與 `retryable`。

`_change` 直接用同一次 `get_meta_item` 讀到的 `_revision`（值與 [Phase 06](06-Phase06-Repository-Metadata與實體讀寫.md) 的 `Repository.revision_of(pk)` 相同），少一次讀取就少一個競態視窗；手上沒有 raw item 的其他 Phase 一律用 `revision_of`，不得自行改用別的屬性名（00A 第 3.6 節）。

- [x] **Step 3：補 ref 單元測試，跑綠燈後提交**

```python
import pytest

from training_kb.errors import PermanentError
from training_kb.keys import operation_ref


def test_operation_ref_is_private_and_stable() -> None:
    assert operation_ref("op-1", "input") == "operations/op-1/input.json"


@pytest.mark.parametrize(
    ("operation_id", "name"),
    [("op-1", "../site/index"), ("op/1", "input"), ("", "input"), ("op-1", "")],
)
def test_operation_ref_rejects_paths_that_escape_the_prefix(
    operation_id: str, name: str
) -> None:
    with pytest.raises(PermanentError):
        operation_ref(operation_id, name)
```

`op-1` 只是測試字串；正式路徑的 `operation_id` 一律由 Phase 32 的 `operation_id_for` 產生（00A 第 3.3 節）。

```bash
uv run pytest tests/unit/test_operation_refs.py tests/integration/test_operations_ledger.py -q
git add src/training_kb/operations.py src/training_kb/keys.py \
  tests/unit/test_operation_refs.py tests/integration/test_operations_ledger.py
git commit -m "feat(ops): 記錄進度與模型輸出 ref"
```

### Task 3：重新載入同一筆紀錄

- [x] **Step 1：建立失敗測試並確認紅燈**

```python
def test_ledger_survives_a_new_coordinator(repository) -> None:
    first = OperationCoordinator(repository)
    accepted = first.accept(REQUEST)
    first.record_normalized("op-ticket-t_881", operation_ref("op-ticket-t_881", "input"))
    again = OperationCoordinator(repository).accept(REQUEST)
    assert again.status == "duplicate"
    assert again.record.input_ref == "operations/op-ticket-t_881/input.json"
    assert again.record.accepted_at == accepted.record.accepted_at
```

```bash
uv run pytest tests/integration/test_operations_ledger.py -q -k survives
```

- [x] **Step 2：補 `complete`／`fail` 後仍是 duplicate，跑綠燈並記錄本階段限制**

`complete` 之後重送要拿到 `status="duplicate"` 且 `record.status == "done"`；`fail(..., retryable=True)` 之後重送也不得建立第二筆。要不要重試由呼叫端依 `retryable` 決定，不是由 ledger 決定。

```bash
uv run pytest tests/integration/test_operations_ledger.py -q
uv run mypy src/training_kb/operations.py
```

驗收報告必須寫明：這裡只換了新的 `OperationCoordinator` 物件，資料仍在同一個 moto 表，**只證明持久紀錄可以被重新載入**。真正的程序重啟、交錯事件、lease 過期與 closed execution 都留給 Phase 11；在那份報告出來前，O2 一律標記為未通過。確認後提交：`git add tests/integration/test_operations_ledger.py` 再 `git commit -m "test(ops): 驗證紀錄可重新載入"`。

## 8. 驗收矩陣

| 路徑 | 輸入 | 預期資料結果 |
|---|---|---|
| Happy | 同一 `AcceptOperation` 送兩次 | 第二次 `duplicate`，表內仍只有一筆 `OPS#` item。 |
| Happy | `record_normalized` 後 `load` | `input_ref` 有值，其餘欄位不動。 |
| Failure | 對不存在的 operation 呼叫 `record_*`，或條件失敗卻讀不到既有 item | `CoordinationError`，不重建、不當成新事件。 |
| Boundary | 同 ref 連續 `record_model_output` 兩次；同 operation 第二次 `record_proc_sample`；`complete` 後再 `accept` | 依序為長度仍是 1、回 `False`、仍是 `duplicate` 且 `status == "done"`。 |
| Boundary | `accept` 回 `duplicate`，但它要寫的業務 item 其實不存在 | 這是**續跑**：呼叫端沿用同一個 `operation_id` 補寫，表內仍只有一筆 `OPS#` item，不算重複處理。 |

人工驗收：讀出 raw `OPS#` item，確認沒有 `target` 欄位（不會進 GSI）、沒有教學全文或回饋留言，只有 ID、狀態與 ref；再確認 `operations/` 底下的物件都不在 `site/` 前綴。不能只看測試顯示 PASS。

## 9. 常見錯誤與停止條件

| 症狀 | 原因 | 修正／停止 |
|---|---|---|
| 重送建立第二筆紀錄，或用 TTL 當去重 | 沒用條件寫入、先查再寫，或以為過期就不會重覆 | 一律 `attribute_not_exists`，條件失敗才讀既有；TTL 不準時也不保證保留。 |
| 把全文塞進 `OPS#` item | 想少寫一個 S3 物件 | 大內容一律進 `operations/`，紀錄只存 ref；重試時先讀 ref 重用輸出，不重新呼叫模型。 |
| `record_proc_sample` 每次回 `True` | 沒檢查既有簽名 | 已有值回 `False`，否則 PROC 重複加分。 |
| 收到 `duplicate` 就直接回「已處理」，資料卻沒寫進去 | 把續跑當成重送 | 先確認目標物件存在再回重複；不存在就沿用同一個 `operation_id` 補寫（§6 續跑分支）。 |
| `scan_entity("OPS")` 找不到剛寫的紀錄 | `put_meta_item` 沒補 `entity` 屬性 | `entity` 取 `parse_pk(pk)[0]`，`SK` 固定 `META`；但**不要**補 `target`。 |
| 從 `training_kb.operations` import `operation_ref` | 放錯模組 | `ops_pk`／`operation_ref` 都在 `keys.py`（00A 第 6.2 節）。 |
| 用本 Phase 綠燈宣稱 O2 通過 | 混淆單一 ID 去重與接受順序 | 只記「永久去重成立」，FIFO 與重啟留 Phase 11。 |

## 10. 來源與 Rule 對照

- [接入來源事件.feature](../../spec/features/接入來源事件.feature)
  - ING Rule 30：「同一正規化事件重送時只處理一次」→ **primary（見 [00B 需求覆蓋對照](00B-需求覆蓋對照.md)）**；Task 1 Step 1、Task 3 Step 1 直接斷言第二次為 `duplicate` 且紀錄逐欄相同。同檔補充「重送回傳既有結果，或接續尚未完成的執行」對應 §6 的續跑分支。
  - ING Rule 8：「新流程每次完整成功才將 success_count 加 1」→ **相關（primary 在 [Phase 35](35-Phase35-PROC成功失敗與退役生命週期.md)）**；`record_proc_sample` 的 `False` 分支是它的前置條件。
- [分析工單.feature](../../spec/features/分析工單.feature)
  - TIC Rule 8：「KEEP 只記錄 log 而不寫入教學內容」→ **相關（primary 在 [Phase 40](40-Phase40-Ticket-CREATE與KEEP.md)）**；KEEP 的原因寫在本 Phase 的 `operations/<operation_id>/` 私有前綴，不進任何業務 item。
- 設計 §7.1、§14.1：重送取得既有結果或沿用未完成邏輯操作，不新增版本、回饋樣本或 PROC 成功樣本；§8.3、§18 O2：接受順序與已處理證據由共用操作紀錄支援，但「不能把共用模組或條件更新本身當成順序保證」。
- 設計 §9.3、§14.2：`operations/` 是私有執行紀錄前綴；儲存重試重用已保存的 ID、正規化結果與模型輸出。
- [DynamoDB 條件運算式](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/Expressions.ConditionExpressions.html)：`attribute_not_exists()` 對複合主鍵是針對同一筆 item 判斷，條件為假時寫入被拒絕；[S3 條件寫入](https://docs.aws.amazon.com/AmazonS3/latest/userguide/conditional-writes.html)：`operations/` 產物用 `If-None-Match: *` 避免覆蓋原輸出。

## 11. 完成清單

- [x] `OperationCoordinator`、三個 dataclass 與兩個 Literal 與本文件 §5、[00A 第 6.4 節](00A-共用契約與名詞.md) 逐字一致，沒有多餘公開方法。
- [x] `ops_pk`、`operation_ref` 在 `keys.py`；`put_meta_item`、`get_meta_item` 在 `repository.py`。
- [x] `accept` 使用條件寫入，重送回 `duplicate` 與逐欄相同的既有紀錄。
- [x] 條件失敗卻讀不到既有 item 時明確失敗，不重建。
- [x] 大型內容都在 `operations/<operation_id>/`，item 只存 ref 且沒有 `target` 欄位。
- [x] `record_model_output` 不重複附加，`record_proc_sample` 第二次回 `False`。
- [x] 沒有 `now` 參數的 `record_*` 不讀系統時鐘。
- [x] §6 寫明續跑分支（`duplicate` 但物件不存在時合法補寫），§5 標明 Phase 11 會追加 `accept_seq` 與三個協調方法。
- [x] 報告寫明本 Phase 只證明永久去重；FIFO、接受順序與 O2 仍未通過。

**O2 gate 狀態：未通過（本 Phase 不負責翻牌）。** 本 Phase 的證據全部來自 moto 本機表，
只證明「同一個 `operation_id` 不會被建立第二次」與「持久紀錄可以被重新載入」。
接受順序（`accept_seq`）、程序重啟、交錯事件、lease 過期與 closed execution 五類案例的真實
DynamoDB 證據在 [Phase 11](./11-Phase11-O2接受順序與重啟整合驗證.md)；在那份報告出來前，
一律保留「O2 尚未 PASS，不得宣稱永久去重或 FIFO」與「lease 不等於接受順序、TTL 不是準時解鎖」
兩句（[00A 第 4.2 節](00A-共用契約與名詞.md)）。
