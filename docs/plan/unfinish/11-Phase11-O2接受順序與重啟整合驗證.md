# Phase 11：O2 接受順序與重啟整合驗證實作計畫

> **給實作者：** 依 checkbox 逐步執行；每個 Task 先建立失敗測試，再寫最小實作。執行時使用 `superpowers:executing-plans` 或同等逐項流程。

**目標：** 以真實後端的整合證據，證明同一篇教學的操作有可重現的接受順序，且程序重啟、重送、lease 過期、交錯事件與 closed execution 都不會產生第二條版本鏈。

**架構：** Phase 10 的 `OperationCoordinator` 已提供永久去重；本 Phase 在同一個 class 上補三個協調方法，只透過 Phase 06／10 已有的 `Repository` 原語（`put_meta_item`／`get_meta_item`／`update_meta`）讀寫，不碰 boto3 的表物件、也不改 `repository.py`。再用整合測試把五種情境各跑一次，輸出可追溯的 O2 報告。程式負責保存順序與租約；DynamoDB 只提供條件寫入，不提供公平排隊。

**技術：** Python 3.12、pytest、經 `Repository` 的 boto3 DynamoDB、隔離的測試單表、可注入的 clock。

## 全域限制

- 唯一主來源是 [Training KB 設計 §8.3、§14.1、§14.2、§18 O2](../../design/training-kb.md)。
- 前置為 [Phase 10：O2 操作紀錄與永久去重契約](./10-Phase10-O2操作紀錄與永久去重契約.md)。Phase 10 未通過時停止。
- 下一階段是 [Phase 12：O3 發布切換整合驗證](./12-Phase12-O3發布切換整合驗證.md)。
- 本階段不建立教學版本、不呼叫 Bedrock、不發布任何內容、不新增第十一個業務實體。
- 不新增 controller、佇列服務或第二張表；協調資訊仍住在同一張 `training_kb` 與私有 `operations/` 前綴。
- **O2 是前期阻擋 gate**（gate 是「必須有真實證據才能通過的關卡」；O2 是設計 §18 待確認事項的第二項：操作紀錄與接受順序）。本 Phase 只能產生 PASS 或 FAIL 報告，不得因為單元測試綠燈就宣稱 O2 已核定。任一案例 FAIL 就阻擋建版路徑，[Phase 20](./20-Phase20-版本分配與重試重用.md)、[Phase 32](./32-Phase32-事件接受去重與流程啟動.md)、[Phase 46](./46-Phase46-REFINE精準改寫與證據去重.md)、[Phase 59](./59-Phase59-失敗復原與重送驗收.md) 都不得開始；[00A 共用契約與名詞](./00A-共用契約與名詞.md)第 4.2 節另把 [Phase 35](./35-Phase35-PROC成功失敗與退役生命週期.md)、[Phase 42](./42-Phase42-Feedback與View固定匯入.md) 列為 O2 追驗 Phase，FAIL 時它們同樣不得宣稱重送不會重複累積樣本或重複匯入。
- 以下程式檔均是實作時預計建立或修改；本計畫本身不代表它們已存在。

---

## 1. 你在整體流程的位置

```text
Phase 10 永久去重 ledger
          |
          v
  [你在這裡：接受順序 + lease + 五個整合案例]
          |
   +------+-------------------------------+
   |                                      |
PASS 報告                              FAIL 報告
   |                                      |
   v                                      v
Phase 12 O3 -> Phase 20 建版        停止建版路徑
Phase 32 / 46 / 59 可開始           保留重現指令，不改寫限制
```

`accept()` 決定「這個事件是不是第一次」；`next_sequence()` 決定「誰排前面」。兩件事不同，不可互相代替。注意取號的範圍：`accept` 當下還不知道這個事件最後會動到哪一篇教學（`AcceptOperation` 只有 `kind`、`canonical_id`、`project_id`，沒有 slug），所以接受順序用**專案層級**的計數器 `SEQ#PROJECT#<project_id>`；等到流程知道 slug 之後，才用 `LEASE#TUTORIAL#<slug>` 把同一篇的處理串起來，並在該篇待處理的操作裡挑 `accept_seq` 最小的先做。

## 2. 完成後看得到什麼

具體輸入：同一篇 `prepare-meeting` 在同一秒收到 Release 事件 `r_42` 與 Feedback Review 觸發，兩個 worker 同時搶同一個 scope。可觀察結果：

```text
OPS#op-release-r_42                accept_seq = 41  status = done  version_id = prepare-meeting@v3
OPS#op-feedback-<64 位指紋>         accept_seq = 42  status = done  version_id = prepare-meeting@v4   (每日 Review 替這篇建立的 REFINE 子 operation)
SEQ#PROJECT#demo                   counter = 42
LEASE#TUTORIAL#prepare-meeting     owner = (空)     expires_at = (空)
```

`operation_id` 的形狀固定是 `op-<kind>-<canonical_id>`（00A 第 3.3 節）。每日 Review 本身的 id 是 `op-feedback-review-demo-2026-09-13`（專案加當日 UTC 日期，00A D-61），但它是**父 operation，不持有版號**；真正和 `r_42` 搶同一篇教學的，是 Review 替每個弱教學另外接受的 REFINE 子 operation `op-feedback-<64 位指紋>`（[Phase 46](./46-Phase46-REFINE精準改寫與證據去重.md) 的 `refine_operation_id`，00A D-59），所以上表第二列寫的是子 operation 的紀錄。`accept_seq` 41 的操作一定先讀到基底並先建版；42 以 v3 為基底。把任一 worker 的程序在寫入中途 `kill -9`，重啟後仍得到同樣兩個 `version_id`，沒有第三個版號。版號在本 Phase 由替身產生（見第 6 節），真正的 `allocate_version` 屬於 [Phase 20](./20-Phase20-版本分配與重試重用.md)。

## 3. 名詞小抄

| 名詞 | 白話意思 |
|---|---|
| O2 | 設計 §18「待確認事項」的第二項：操作紀錄與接受順序。沒有真實後端證據就不算通過。 |
| gate | 必須有真實證據才能通過的關卡；文件寫得再完整、mock 測試再綠都不能關掉它。 |
| operation | 一次邏輯處理的永久紀錄，例如「處理 `r_42` 這件事」。 |
| 接受順序 | 多個操作被承認的先後；由持久遞增號碼決定，不是誰先搶到鎖。 |
| `accept_seq` | 本 Phase 寫進 operation 紀錄的接受順序號碼，不是版本號。 |
| lease（租約） | 一段時間內只讓一個 worker 動同一個 scope 的最佳努力提示，不是正確性保證。 |
| scope | 需要序列化的範圍字串：取號用 `PROJECT#<project_id>`，租約用 `TUTORIAL#<slug>`。 |
| compare-and-swap | 先讀到版本號（`_revision`），寫回去時要求它沒被別人改過；改過就整筆失敗。 |
| closed execution | Step Functions 上同名但已結束的執行；重送時會回 `ExecutionAlreadyExists`。 |
| 故障注入 | 在指定位置刻意中斷程式，觀察系統對外看起來變成什麼樣子。 |

## 4. 預計檔案

| 動作 | 路徑 | 責任 |
|---|---|---|
| 修改 | `src/training_kb/operations.py` | 在 `OperationCoordinator` 補 `acquire_lease`／`release_lease`／`next_sequence`。 |
| 新增 | `infra/scripts/o2_report.py` | 執行五個案例並輸出固定格式 O2 報告。 |
| 測試 | `tests/unit/test_operation_ordering.py` | 序號單調、lease 條件、非持有者不可釋放；用記憶體假 `Repository`。 |
| 測試 | `tests/integration/test_o2_cases.py` | 重啟、重送、lease 過期、交錯事件、closed execution；全部標 `@pytest.mark.aws`。 |
| 新增 | `docs/plan/report/o2-<run-id>.md` | O2 報告；原始觀察值另存私有 `operations/o2/<run_id>.json`。 |

## 5. 固定介面

### Consumes

```text
AcceptOperation(operation_id, kind, canonical_id, project_id, now)                  # Phase 10
OperationRecord(operation_id, kind, canonical_id, project_id, status, input_ref,
                execution_arn, version_id, ..., accepted_at, updated_at)            # Phase 10
Acceptance(status, operation_id, record)                                            # Phase 10
OperationCoordinator.accept(request) -> Acceptance                                  # Phase 10
OperationCoordinator.load(operation_id) -> OperationRecord | None                   # Phase 10
OperationCoordinator.record_version(operation_id, version_id) -> None               # Phase 10
ops_pk(operation_id) -> str                                                         # Phase 10
Repository.put_meta_item(pk, attributes, *, create_only=True) -> bool               # Phase 10
Repository.get_meta_item(pk) -> DynamoItem | None                                   # Phase 10
Repository.update_meta(pk, changes, *, expected_revision) -> int                    # Phase 06
Repository.put_meta(entity, *, create_only=True) / get_tutorial(slug)               # Phase 06
META                                                                                # Phase 05
to_iso(dt) -> str / CoordinationError / PermanentError                              # Phase 02
```

`update_meta` 在 `expected_revision` 對不上時丟 `CoordinationError`（Phase 06 的契約），本 Phase 全部的搶佔判定都靠它。

### Produces

```python
# src/training_kb/operations.py（在 Phase 10 的 class 上追加）
SEQUENCE_ATTEMPTS: int = 8

class OperationCoordinator:
    def acquire_lease(
        self, scope: str, owner: str, *, ttl_seconds: int, now: datetime
    ) -> bool: ...
    def release_lease(self, scope: str, owner: str) -> None: ...
    def next_sequence(self, scope: str) -> int: ...

# infra/scripts/o2_report.py
@dataclass(frozen=True)
class O2Case:
    name: str
    fault_point: str
    expectation: str

@dataclass(frozen=True)
class O2CaseResult:
    case: O2Case
    observed: str
    verdict: Literal["PASS", "FAIL"]
    evidence_ref: str

def run_o2_case(case: O2Case, *, table: str, region: str) -> O2CaseResult: ...
def o2_verdict(results: Sequence[O2CaseResult]) -> Literal["PASS", "FAIL"]: ...
def render_o2_report(
    results: Sequence[O2CaseResult], *, run_id: str, table: str, region: str
) -> str: ...
```

本 Phase 在 Phase 10 的 `OperationRecord` 追加一個 `accept_seq: int | None` 欄位，位置固定在 `retryable` 與 `accepted_at` 之間（00A 第 6.4 節的欄位順序），其餘欄位一律不改名；`accept()` 在條件寫入之前取號，號碼只會寫進**本次真的建立**的那筆 `OPS#` item，duplicate 回傳既有紀錄與它原本的 `accept_seq`。`render_o2_report` 多收 `table` 與 `region`，是因為報告必須寫出它對哪張表、哪個 Region 跑；[00A 第 6.4 節](00A-共用契約與名詞.md) 的 gate 工具清單已逐字收錄這個簽名，兩邊必須一致。

## 6. 設計細節

三個名稱依 [00A 第 6.4 節](./00A-共用契約與名詞.md)加在 Phase 10 的 `OperationCoordinator` 上，`self` 之外的參數與回傳型別逐字相同；不另建模組級全域 repository，也不在 `repository.py` 加方法（00A 第 3.2 節沒有把 Phase 11 列為它的修改者）。儲存形狀與寫入方式：

```text
PK = SEQ#PROJECT#<project_id>   SK = META   屬性 counter
PK = LEASE#TUTORIAL#<slug>      SK = META   屬性 owner / expires_at / ttl
        |
        v
第一次建立 -> Repository.put_meta_item(pk, ..., create_only=True)  已存在回 False
之後改值   -> Repository.update_meta(pk, changes, expected_revision=剛讀到的 _revision)
                     |
              _revision 已被別人改過 -> CoordinationError -> 本次搶輸
```

`expected_revision` 就是條件寫入：先讀到 `_revision`，寫回去時要求它沒變。誰先寫成功誰贏，輸的一方拿到 `CoordinationError`，不會靜默覆蓋。`next_sequence` 因此是「讀 counter → 寫 counter+1」的有限次重試，最多 `SEQUENCE_ATTEMPTS`（8）次；超過就丟 `CoordinationError`，不無限重試。

兩句必須寫進程式註解與報告，否則後面 Phase 很容易誤用：

- **鎖不等於接受順序。** 誰先搶到 lease 只代表誰先送達 DynamoDB，不代表事件較早。順序一律讀 `accept_seq`：worker 拿到某篇教學的 lease 之後，在該篇待處理的操作裡挑 `accept_seq` 最小的做，做完才換下一個。
- **TTL 不是準時解鎖。** DynamoDB 的 TTL 官方說明是「typically within a few days after their expiration」，過期項目在刪除前仍讀得到。到期判斷一律自己比 `expires_at`，再用 `expected_revision` 把租約搶下來；`ttl` 屬性只做長期清理，不能當解鎖時刻。

lease 也不是正確性保證：時鐘偏移時可能兩個 owner 同時以為自己持有。因此任何會改變版本鏈的寫入仍要帶條件（`expected_revision` 或 `attribute_not_exists`），不可只靠 lease。另一個容易誤判的相容性問題（[00A](./00A-共用契約與名詞.md) 裁決 D-45）：[Phase 42](./42-Phase42-Feedback與View固定匯入.md) 在 `accept` 回 `duplicate` 但目標物件其實不存在時會**補寫**那個物件；這是合法的續跑，不是重複處理——`OPS#` 仍然只有一筆、`accept_seq` 不變、不重新取號，補的只是上次沒寫完的產物。`resend` 案例要能區分兩者：重複處理會多出第二筆 `OPS#` 或第二個 `version_id`，合法補寫兩者都不會變。五個整合案例與觀察點：

```text
案例                 注入點                       對外必須看到
-------------------+---------------------------+------------------------------
程序重啟            record_version 之後 kill -9  重啟後同 operation_id 同 version_id
重送                accept 已成功後再送一次      status=duplicate，只有一筆 OPS
lease 過期          持有者不釋放就消失           到期後他人可接手，順序仍照 accept_seq
交錯事件            Release 與 Feedback 同時到   兩個版號依 accept_seq 串行，無分叉
closed execution    同名執行已結束後重送         讀 ledger 原結果；無結果則明確失敗
```

兩個案例需要本 Phase 自備的最小替身，避免用到更後面 Phase 才有的東西：

- **版號**：[Phase 20](./20-Phase20-版本分配與重試重用.md) 的 `allocate_version` 此時還不存在。`restart` 與 `interleaved` 兩個案例改用案例腳本裡的替身「讀 `Tutorial.current_version` → 版號加一 → `record_version`」，字串直接組成 `<slug>@v<n>`。本 Phase 只證明「同一 operation 重送拿到同一個 `version_id`、兩個 operation 不分叉」；真正的 `allocate_version` 由 Phase 20 用同一組情境再驗一次。
- **closed execution**：不在此實作 `PipelineStarter`；[Phase 32](./32-Phase32-事件接受去重與流程啟動.md) 才接上真正的 boto3 adapter。本 Phase 用最小 stub 產生 `ExecutionAlreadyExists`，證明協調紀錄足以判斷。

### 實作記錄（2026-09-14，與本文件的差異與補充）

| 項目 | 本文件原文 | 實際做法 | 理由 |
|---|---|---|---|
| `evidence_ref` 的 run id | `run_o2_case(case, *, table, region)` 沒有 `run_id`，但 `evidence_ref` 要填 `operations/o2/<run_id>.json` | 簽名**逐字不動**；`o2_report.current_run_id()` 讀環境變數 `TKB_O2_RUN_ID`（`main` 會先設定），沒設時回 `adhoc` | 00A 第 6.4 節把簽名列為 canonical，不得為了方便加參數 |
| `render_o2_report` 的列渲染 | `"...".format(row)` | 等價 f-string | `ruff` 的 `UP032` 拒絕單一引數的 `.format`；輸出逐字相同 |
| 「重啟」的強度 | 「`record_version` 之後 `kill -9`」 | `restart` 案例真的 `subprocess` 開子程序，在 `record_version` 之後 `os.kill(os.getpid(), SIGKILL)`；父程序確認 `returncode == -9`，再用**全新**的 `Repository` 與 `OperationCoordinator` 接手 | 換物件不等於換程序；真的殺掉才算重啟證據 |
| 隔離測試表 | 「隔離的測試單表」 | `infra/scripts/o2_report.py --provision` 建 `training_kb_o2_<run_id>`（us-east-1、PK／SK 同正式表、PAY_PER_REQUEST、TTL 屬性 `ttl`），跑完自動刪除並把建立／刪除時間與 `table_exists -> False` 寫進報告 | 正式 `training_kb` 表不得被測試污染 |
| gate 證據 | `operations/o2/<run_id>.json` | 寫進**正式** bucket 的私有前綴（bucket policy 只有 enforce-SSL 的 Deny，沒有任何公開授權） | 00A 第 3.4 節指定這個 key |
| 離線回歸 | 未規定 | 同一支測試檔多一段不標 `aws` 的 moto 參數化測試（`restart` 跳過：子程序看不到本行程的 `mock_aws`） | 平常跑測試也能發現案例腳本壞掉；**它不是 O2 證據** |
| Phase 10 的 `record_version` | 「Consumes」欄只寫 `-> None` | 依 Phase 10 review 改成**只允許寫一次**（同值 no-op、不同值 `CoordinationError`，00A D-59） | 靜默覆蓋會讓同一筆操作先後指到兩個版號，`restart` 案例的判準就不成立 |

## 7. TDD Tasks

### Task 1：鎖定接受順序的持久遞增號碼

- [x] **Step 1：建立失敗測試**

```python
def test_next_sequence_is_monotonic_per_scope(coordinator) -> None:
    first = coordinator.next_sequence("PROJECT#demo")
    second = coordinator.next_sequence("PROJECT#demo")
    other = coordinator.next_sequence("PROJECT#other")
    assert (first, second, other) == (1, 2, 1)
```

`coordinator` fixture 用一個只實作 `put_meta_item`／`get_meta_item`／`update_meta` 三個方法的記憶體假 `Repository`，所以這是單元測試。它證明程式邏輯，**證明不了 O2**；只有 Task 3 對真實表跑出來的觀察值才算。

- [x] **Step 2：執行並確認紅燈**

```bash
uv run pytest tests/unit/test_operation_ordering.py::test_next_sequence_is_monotonic_per_scope -q
```

預期：FAIL，訊號包含 `'OperationCoordinator' object has no attribute 'next_sequence'`。

- [x] **Step 3：建立最小實作**

```python
SEQUENCE_ATTEMPTS = 8


def next_sequence(self, scope: str) -> int:
    pk = f"SEQ#{scope}"
    self._repository.put_meta_item(pk, {"counter": 0}, create_only=True)
    for _ in range(SEQUENCE_ATTEMPTS):
        item = self._repository.get_meta_item(pk)
        if item is None:
            raise CoordinationError(f"sequence item is missing: {pk}")
        current = int(item["counter"])
        try:
            self._repository.update_meta(
                pk, {"counter": current + 1}, expected_revision=int(item["_revision"])
            )
        except CoordinationError:
            continue
        return current + 1
    raise CoordinationError(f"sequence contention over {SEQUENCE_ATTEMPTS} attempts: {pk}")
```

`int(...)` 不能省：DynamoDB resource API 回來的數字是 `Decimal`。迴圈有上限，不是無限重試。

- [x] **Step 4：把號碼接進 `accept`，跑完整檔案綠燈後提交**

```python
def accept(self, request: AcceptOperation) -> Acceptance:
    seq = self.next_sequence(f"PROJECT#{request.project_id}")
    record = _initial_record(request, accept_seq=seq)
    pk = ops_pk(request.operation_id)
    if self._repository.put_meta_item(pk, _to_item(record), create_only=True):
        return Acceptance("accepted", request.operation_id, record)
    existing = self.load(request.operation_id)
    if existing is None:
        raise CoordinationError(f"operation item is missing after conflict: {pk}")
    return Acceptance("duplicate", request.operation_id, existing)
```

號碼在條件寫入**之前**取，所以同一筆事件重送會燒掉一個號碼：duplicate 回傳的是既有紀錄與它原本的 `accept_seq`，被燒掉的號碼不會出現在任何 `OPS#` item。接受順序只要求單調遞增、可比較，不要求連號；這種缺口和 D26（設計 §19.1 的資料決策編號：同一邏輯變更重試時重用原版本號，永久失敗可保留版號缺口）是同一種取捨。不要為了補洞改成「先查再寫」，那會把 Phase 10 明確設計的三個分支變成有競態的四個分支。

```bash
uv run pytest tests/unit/test_operation_ordering.py -q
git add src/training_kb/operations.py tests/unit/test_operation_ordering.py
git commit -m "feat(operations): 保存同篇操作接受順序"
```

### Task 2：鎖定 lease 的過期與擁有權

- [x] **Step 1：建立失敗測試**

```python
def test_expired_lease_can_be_taken_over_but_only_by_condition(coordinator, clock):
    scope = "TUTORIAL#prepare-meeting"
    assert coordinator.acquire_lease(scope, "worker-a", ttl_seconds=30, now=clock.at(0))
    assert not coordinator.acquire_lease(scope, "worker-b", ttl_seconds=30, now=clock.at(29))
    assert coordinator.acquire_lease(scope, "worker-b", ttl_seconds=30, now=clock.at(31))
    coordinator.release_lease(scope, "worker-a")
    assert not coordinator.acquire_lease(scope, "worker-c", ttl_seconds=30, now=clock.at(32))
```

最後一行是重點：`worker-a` 已非持有者，它的 `release_lease` 不能清掉 `worker-b` 的租約。

- [x] **Step 2：執行並確認紅燈**

```bash
uv run pytest tests/unit/test_operation_ordering.py::test_expired_lease_can_be_taken_over_but_only_by_condition -q
```

預期：FAIL，訊號包含 `has no attribute 'acquire_lease'`。

- [x] **Step 3：建立最小實作**

```python
from datetime import datetime, timedelta


def acquire_lease(self, scope: str, owner: str, *, ttl_seconds: int, now: datetime) -> bool:
    if ttl_seconds <= 0:
        raise PermanentError(f"ttl_seconds must be positive: {ttl_seconds}")
    pk = f"LEASE#{scope}"
    fields = {
        "owner": owner,
        "expires_at": to_iso(now + timedelta(seconds=ttl_seconds)),
        "ttl": int((now + timedelta(days=7)).timestamp()),
    }
    if self._repository.put_meta_item(pk, fields, create_only=True):
        return True
    item = self._repository.get_meta_item(pk)
    if item is None:
        raise CoordinationError(f"lease item is missing: {pk}")
    held_by_other = str(item.get("owner") or "") not in ("", owner)
    if held_by_other and to_iso(now) < str(item.get("expires_at") or ""):
        return False
    try:
        self._repository.update_meta(pk, fields, expected_revision=int(item["_revision"]))
    except CoordinationError:
        return False
    return True
```

`expires_at` 用固定長度的 ISO-8601 UTC 字串，字典序等於時間序，所以 `to_iso(now) < expires_at` 就是「還沒到期」。到期之後靠 `expected_revision` 決勝負：兩個 worker 同時判定過期也只有一個寫得進去，另一個拿到 `CoordinationError` 並回 `False`。`ttl` 只給 DynamoDB 長期清理用。

- [x] **Step 4：補 `release_lease` 與邊界，綠燈後提交**

```python
def release_lease(self, scope: str, owner: str) -> None:
    pk = f"LEASE#{scope}"
    item = self._repository.get_meta_item(pk)
    if item is None or str(item.get("owner") or "") != owner:
        return
    try:
        self._repository.update_meta(
            pk, {"owner": "", "expires_at": ""}, expected_revision=int(item["_revision"])
        )
    except CoordinationError:
        return
```

再補三條邊界測試：同一 owner 重入可延長到期時間、`ttl_seconds <= 0` 丟 `PermanentError`、非持有者呼叫 `release_lease` 之後讀回來的 `owner` 沒變。

```bash
uv run pytest tests/unit/test_operation_ordering.py -q
git add src/training_kb/operations.py tests/unit/test_operation_ordering.py
git commit -m "feat(operations): 以條件寫入管理租約"
```

### Task 3：跑完五個整合案例並產出 O2 報告

- [x] **Step 1：建立會失敗的案例表**

```python
import pytest

O2_CASES = (
    O2Case("restart", "after_record_version", "同 operation_id 與同 version_id"),
    O2Case("resend", "after_accept", "status=duplicate，OPS 只有一筆"),
    O2Case("lease_expiry", "owner_vanishes", "到期後可接手，順序仍照 accept_seq"),
    O2Case("interleaved", "release_and_feedback_same_slug", "兩版串行且無分叉"),
    O2Case("closed_execution", "already_exists_closed", "讀 ledger 原結果或明確失敗"),
)


@pytest.mark.aws
def test_all_o2_cases_pass(live_table, live_region) -> None:
    results = [run_o2_case(case, table=live_table, region=live_region) for case in O2_CASES]
    report = render_o2_report(results, run_id="local", table=live_table, region=live_region)
    assert o2_verdict(results) == "PASS", report
```

`live_table`／`live_region` 兩個 fixture 從 `TKB_TABLE_NAME`、`TKB_AWS_REGION` 讀隔離的測試表，沒設就 `pytest.skip`；Region 不寫死在測試裡。`@pytest.mark.aws` 是 00A 第 3.1 節規定的真實 AWS 標籤，marker 在 [Phase 01](01-Phase01-專案骨架與離線品質門檻.md) 的 `pyproject.toml` 註冊，而且 Phase 01 的 `tests/conftest.py` 在沒設 `TKB_RUN_AWS_INTEGRATION=1` 時會自動跳過它們（裁決 D-64），所以平常不必自己加 `-m` 條件。

- [x] **Step 2：執行並確認紅燈**

```bash
TKB_RUN_AWS_INTEGRATION=1 uv run pytest tests/integration/test_o2_cases.py::test_all_o2_cases_pass -q -m aws
```

預期：FAIL，訊號包含 `cannot import name 'run_o2_case'`。（**實作記錄**：`o2_report.py` 是整支新檔，所以實際訊號是更前面一步的 `ModuleNotFoundError: No module named 'o2_report'`；同一個原因，同樣是正確的紅燈。）

- [x] **Step 3：實作觀察器與報告**

每個案例固定回傳四欄，報告不得只寫「通過」：

```python
COLUMNS = "| 案例 | 注入點 | 期望 | 觀察 | 判定 | 證據 |\n|---|---|---|---|---|---|\n"


def render_o2_report(
    results: Sequence[O2CaseResult], *, run_id: str, table: str, region: str
) -> str:
    rows = "".join(
        # ruff UP032 不接受單一引數的 `.format`，改用等價的 f-string（輸出逐字相同）。
        f"| {row.case.name} | {row.case.fault_point} | {row.case.expectation} |"
        f" {row.observed} | {row.verdict} | {row.evidence_ref} |\n"
        for row in results
    )
    head = f"# O2 報告 {run_id}\n\nRegion：{region}｜表：{table}｜run id：{run_id}\n\n"
    return f"{head}{COLUMNS}{rows}\n整體判定：{o2_verdict(results)}\n"
```

`evidence_ref` 填私有 S3 的 `operations/o2/<run_id>.json`，裡面放該案例的原始讀值；報告只放摘要。

- [x] **Step 4：對真實隔離表執行並提交**

```bash
TKB_RUN_AWS_INTEGRATION=1 uv run pytest tests/integration/test_o2_cases.py -q -m aws
git add infra/scripts/o2_report.py tests/integration/test_o2_cases.py docs/plan/report
git commit -m "test(operations): 產出O2整合驗證報告"
```

預期：五個案例都有實際 DynamoDB 讀寫紀錄。記憶體 fake 全綠不算 O2 通過；報告要註明 Region、表名與 run id。

## 8. 驗收矩陣

| 路徑 | 輸入 | 預期資料結果 |
|---|---|---|
| Happy | 同篇兩個事件依序到達 | `accept_seq` 遞增，版號 v3、v4，無分叉。 |
| Failure | `record_version` 後 `kill -9` | 重啟取回同 `operation_id`、同 `version_id`，不出現第三個版號。 |
| Failure | closed `ExecutionAlreadyExists` 且 ledger 無結果 | `CoordinationError`；不回成功、不換名重跑。 |
| Boundary | lease 到期前一秒與到期後一秒 | 29 秒不可接手、31 秒可接手。 |
| Boundary | 非持有者呼叫 `release_lease`；同事件重送四次 | 租約不變；`OPS#` 仍只有一筆且 `accept_seq` 不變。 |

人工驗收：打開 `docs/plan/report/o2-<run-id>.md`，逐列核對 Region、表名、注入點與觀察值；再以 AWS Console 或 `aws dynamodb get-item` 重看一次 `OPS#`、`SEQ#`、`LEASE#` 三種 item。只看 pytest 顯示 PASS 不算完成。

## 9. 常見錯誤與停止條件

| 症狀 | 原因 | 修正／停止 |
|---|---|---|
| 兩個 worker 同時建版 | 把 lease 當唯一保護 | 每次版本寫入補 `expected_revision` 條件；FAIL 就停止 Phase 20。 |
| 到期租約遲遲不放 | 依賴 TTL 自動刪除 | 自己比 `expires_at`，再用 `expected_revision` 搶佔；`ttl` 只做長期清理。 |
| 重送產生新版號 | 用時間或 UUID 產生 operation id | 回到 Phase 10 的 canonical id；重送必須是 duplicate。 |
| 順序跟著鎖跑 | 用「誰先拿到鎖」當接受順序 | 改讀 `accept_seq`；FAIL 就阻擋 Phase 32、46。 |
| 取號寫進 `Repository` | 在 `repository.py` 加原子計數方法 | 只用既有三個原語；要動 `repository.py` 得先改 00A 第 3.2 節的修改者欄。 |
| 報告只有 PASS 字樣 | 沒有記錄觀察值與證據 | 補齊六欄並寫上 Region、表名、run id；沒有證據等同未驗證。 |
| 用 fake 後端宣稱 O2 通過 | 混淆單元測試與整合 gate | 標示 BLOCKED，不勾選完成清單最後兩項。 |

## 10. 來源與 Rule 對照

- [接入來源事件.feature](../../spec/features/接入來源事件.feature)
  - Rule 30：「同一正規化事件重送時只處理一次」→ **相關（primary 在 [Phase 10](./10-Phase10-O2操作紀錄與永久去重契約.md)）**。Task 3 的 `resend` 案例在真實後端的重啟與交錯情境下再驗一次，斷言 `OPS#` 僅一筆且 `accept_seq` 不變。
- [建立教學版本.feature](../../spec/features/建立教學版本.feature)
  - Rule 2：「任一 pipeline 修改既有教學時使用該篇的下一個版本號」→ **相關（primary 在 [Phase 20](./20-Phase20-版本分配與重試重用.md)）**。Task 3 的 `interleaved` 案例用第 6 節的版號替身在整合情境再驗，斷言兩個操作依 `accept_seq` 串行得到 v3、v4。
- 設計 §8.3：同篇變更依接受順序串行，輪到才讀最新基底；共用模組本身不是順序保證。
- 設計 §14.1、§14.2、§18 O2：重送取得既有結果；`ExecutionAlreadyExists` 不能直接當成功；接受順序、程序重啟與重送必須先驗證，才決定協調方式。
- [DynamoDB TTL](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/howitworks-ttl.html)：過期項目「typically within a few days after their expiration」才刪除，讀取需自行過濾。
- [DynamoDB 交易與條件](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/transaction-apis.html)：條件不成立時整筆取消並回 `ConditionalCheckFailed`。
- [StartExecution](https://docs.aws.amazon.com/step-functions/latest/apireference/API_StartExecution.html)：同名冪等只在執行未結束時成立。

## 11. 完成清單

- [x] `acquire_lease`、`release_lease`、`next_sequence` 的參數與回傳型別符合本文件，且只用 `Repository` 既有原語，沒有改 `repository.py`。
- [x] `accept_seq` 由 `SEQ#PROJECT#<project_id>` 取號並寫進 `OPS#` item；duplicate 回傳既有號碼，號碼缺口允許存在。
- [x] lease 到期判斷自己比 `expires_at` 並用 `expected_revision` 搶佔，不依賴 TTL 刪除時間。
- [x] 非持有者無法釋放他人租約。
- [x] 五個案例都標 `@pytest.mark.aws`、對真實隔離表執行並留下觀察值。
- [x] `docs/plan/report/o2-<run-id>.md` 六欄齊全，含 Region、表名與 run id。
- [x] 文件與報告都寫明「鎖不等於接受順序」「TTL 不是準時解鎖」。
- [x] 任一案例 FAIL 時，Phase 20、32、46、59 標為阻擋，未宣稱 O2 已核定。

## 12. 本次 gate 結論

**O2：PASS**（2026-09-14）。五個案例都對真實 DynamoDB 的隔離表 `training_kb_o2_20260914t182824z`
（us-east-1）各跑一次，逐案觀察值與重現指令在
[`docs/plan/report/o2-20260914t182824z.md`](../report/o2-20260914t182824z.md)；原始證據在私有
`s3://training-kb-content-example/operations/o2/20260914t182824z.json`。
隔離表在同一次執行結束時刪除（報告的「隔離測試表生命週期」一節記了建立／刪除時間與
`table_exists -> False`）。

因此 Phase 20、32、46、59 **不再被 O2 阻擋**；追驗 Phase 35、42 仍要各自在自己的情境再驗一次
（00A 第 4.2 節）。兩句停止語仍然保留，而且已經寫進 `operations.py` 的模組 docstring、
`o2_report.py` 的模組 docstring 與報告本文：**鎖不等於接受順序**、**TTL 不是準時解鎖**。
