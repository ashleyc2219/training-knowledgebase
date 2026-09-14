# Phase 38：Ticket Embedding 與群中心分群實作計畫

> **給實作者：** 依 checkbox 逐步執行；每個 Task 先建立失敗測試，再寫最小實作。執行時使用 `superpowers:executing-plans` 或同等逐項流程。

**目標：** 讓每則 Ticket 只在缺向量時產生一次 1024 維 embedding 並存回 TICKET，再以各群的群中心決定它屬於哪一個 `cluster_id`。

**架構：** 這是第一個需要資料與模型的 pipeline 節點，所以本 Phase 先把 Phase 29 的 `Deps` 加上 `repository`、`writer`、`settings` 三個 keyword 欄位（00A 裁決 D-36），再在 `pipelines/ticket.py` 放業務函式。模型只負責把文字變成向量；要不要呼叫模型、屬於哪一群、新群叫什麼名字，都由程式決定。

**技術：** Python 3.12、Pydantic v2、pytest、Phase 15 `Writer.embed`、Phase 16 `cosine`／`centroid`、Phase 08 `Repository.list_tickets`。

## 全域限制

- 唯一主來源是 [Training KB 設計 §7.3、§9.1、§14.2、§14.3](../../design/training-kb.md)。
- 前置為 [Phase 37：Rote Agent 回退與成功提交](./37-Phase37-Rote-Agent回退與成功提交.md)。Phase 37 未通過時停止。
- 下一階段是 [Phase 39：Recurring 與 Knowledge Gap 命名](./39-Phase39-Recurring與Knowledge-Gap命名.md)。
- 本階段不做：不判斷 recurring、不命名 Knowledge Gap、不決定 CREATE／KEEP、不建立 Feature 或 Tutorial、不合群也不重編號既有 cluster、不建立向量資料庫、不持久化 Feature／Step 向量、不把 `cluster_id` 寫回 TICKET（那是 Phase 41 的 `assign_cluster` Task）。
- 與本 Phase 有關的 gate：**O5 未通過**時真實 Titan 呼叫維持 BLOCKED，只能用 FakeWriter 證明分支邏輯，不得把假向量綠燈說成 Titan 已驗證；**O2 未通過**時不得宣稱「併發下新群 ID 不會撞號」已驗收。離線開發（程式與單元測試）照常完成，真實 AWS 接線延後到下一批（controller 2026-09-14 裁決，見 `.superpowers/sdd/phase0914-1/COMMON.md`）。
- 以下程式檔均是實作時預計建立或修改；本計畫本身不代表它們已存在。

---

## 1. 你在整體流程的位置

```text
Phase 37 已驗證的 Ticket -> Phase 32 啟動 ticket-analysis
                                   |
                                   v
                   [你在這裡：ensure_embedding + assign_cluster]
                                   |
                +------------------+-------------------+
        有合格群（cosine >= 0.85）              沒有合格群
                |                                      |
        沿用既有 cluster_id                    new_cluster_id 開新群
                |                                      |
                +------------------+-------------------+
                                   v
                     Phase 39 判斷 recurring 與命名 gap
```

模型只出現在「文字 -> 向量」這一步；群中心、門檻比較與新群編號都是程式行為，重跑會得到一樣的結果。

## 2. 完成後看得到什麼

輸入 `t_881`（`project_id="demo"`、`embedding=None`、`cluster_id=None`），資料庫已有 `c12` 群的三筆 Ticket 與 `c13` 群的兩筆 Ticket。可觀察結果：`writer.embed` 呼叫次數 `1`；讀回的 `t_881.embedding` 長度 `1024`；`assign_cluster("t_881") == "c12"`（對 c12 群中心 0.91、對 c13 群中心 0.62）。

同一筆 `t_881` 再送一次：`writer.embed` 仍然是 **1** 次，結果仍是 `c12`。若對所有群的 cosine 都低於 `0.85`，結果會是新的 `c14`，而且 `c14` 一旦配出就不會被別群重複使用。

## 3. 名詞小抄

| 名詞 | 白話意思 |
|---|---|
| embedding | 把一段文字換成 1024 個數字的清單，讓程式可以比「意思像不像」。 |
| cosine | 兩個向量的夾角相似度，1 代表方向完全一樣，0 代表無關。 |
| centroid（群中心） | 一群 Ticket 的向量逐維平均後的代表向量；不是挑其中某一筆當代表。 |
| cluster_id | 同一個重複問題的群組編號，例如 `c12`；它會被寫進第一版教學的 `reason`。 |
| 門檻 0.85 | 設計固定的同群判定線；`0.8499` 不算同群，`0.85` 算。它存在 `Thresholds.cosine_match`。 |
| `Deps` | Phase 29 定義的「這條 pipeline 用得到的相依」容器，Task 函式只透過它拿 repository、writer 與 settings。 |
| `O2`／`O5` | [設計 §18](../../design/training-kb.md) 七個待確認事項的編號：O2 是操作紀錄與接受順序，O5 是模型與參數驗證。 |
| `D08`／`D29`／`F10` | [設計 §19](../../design/training-kb.md) 已解決決策的編號：`D` 是資料決策（D08＝向量存 `Ticket.embedding`、D29＝`cluster_id` 要可追溯），`F` 是功能決策（F10＝比較群中心取最高）。 |

## 4. 預計檔案

| 動作 | 路徑 | 責任 |
|---|---|---|
| 修改 | `src/training_kb/pipelines/common.py` | Phase 29 的 `Deps` 增加三個 keyword 欄位與三個 `need_*` helper。 |
| 建立 | `src/training_kb/pipelines/ticket.py` | `CLUSTER_COSINE_THRESHOLD`、`ensure_embedding`、`assign_cluster`、`new_cluster_id`。 |
| 建立 | `tests/unit/pipelines/conftest.py` | 五個 fixture 與三個 `Ticket` 工廠（工廠也是 fixture，見 §7），本 Phase 三支測試共用。 |
| 測試 | `tests/unit/pipelines/test_deps.py` | 舊建構方式仍可用；缺相依時明確失敗。 |
| 測試 | `tests/unit/pipelines/test_ticket_embedding.py` | 缺向量才呼叫、重送不重算、非法回應被拒。 |
| 測試 | `tests/unit/pipelines/test_ticket_cluster.py` | 群中心、`0.8499`／`0.85` 邊界、同分排序、新群編號。 |

## 5. 固定介面

### Consumes

```text
P02 config      Thresholds.cosine_match: float = 0.85              # 0.85 的唯一來源
                Settings.project_id: str = DEFAULT_PROJECT_ID      # "demo"
P02 errors      PermanentError、TransientError、CoordinationError
P04 models      Ticket(id, source, text, author, ts, project_id, cluster_id, feature_ids, embedding)
P05 keys        ticket_pk(ticket_id: str) -> str                   # "TICKET#<id>"
P06 repository  get_meta(pk: str, model: type[T], *, consistent: bool = True) -> T | None
                put_meta(entity: Entity, *, create_only: bool = True) -> None
P08 repository  list_tickets(project_id: str) -> list[Ticket]      # 內部走 scan_entity("TICKET")
P10 operations  OperationCoordinator                               # 只用於建構 Deps，本 Phase 不呼叫它
P15 writing     Writer.embed(text: str, *, operation_id: str, node: str) -> list[float]
                CallTrace                                          # 每次真實 attempt 一筆，供人工驗收核對
P16 vectors     cosine(left: list[float], right: list[float]) -> float
                centroid(vectors: list[list[float]]) -> list[float]
P29 pipelines   Deps(operations, now)、TaskFn、run_sequence(pipeline, payload, tasks, deps)
```

`list_tickets` 走 Phase 08 的 `scan_entity("TICKET")`，它預設 `meta_only=True` 只回 `SK == META` 的 item，所以 Phase 40 之後掛在 `TICKET#<id>` 上的 `ASKS_ABOUT#` 邊不會被誤算成工單。

### Produces

```python
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime

from training_kb.config import Thresholds

CLUSTER_COSINE_THRESHOLD = Thresholds().cosine_match     # 別名，不另外寫一份 0.85

@dataclass(frozen=True)
class Deps:
    operations: "OperationCoordinator"
    now: Callable[[], datetime]
    repository: "Repository | None" = None
    writer: "Writer | None" = None
    settings: "Settings | None" = None

    def need_repository(self) -> "Repository": ...
    def need_writer(self) -> "Writer": ...
    def need_settings(self) -> "Settings": ...

def ensure_embedding(ticket: "Ticket", *, writer: "Writer", repository: "Repository",
                     operation_id: str) -> "Ticket": ...

def assign_cluster(ticket: "Ticket", *, repository: "Repository") -> str: ...

def new_cluster_id(existing: Iterable[str]) -> str: ...
```

三個新欄位有預設值 `None`，所以 Phase 29 既有的 `Deps(operations=..., now=...)` 測試不會壞；需要相依卻沒接線時由 `need_*` 丟 `PermanentError`，不會拿到 `None` 才在深處爆炸（00A D-36）。

數字只有一份：`0.85` 來自 [Phase 02](02-Phase02-設定時間與錯誤契約.md) 的 `Thresholds.cosine_match`，`CLUSTER_COSINE_THRESHOLD` 只是它的別名（00A §5.4 與裁決 D-35，寫法與 Phase 39 的 `RECURRING_MIN_TICKETS` 一致）。本 Phase **不得**自創 `Thresholds.cosine_cluster` 這種新欄位名，也不得在模組裡再寫一次字面值 `0.85`。`assign_cluster` 的簽名（00A §6.9）沒有 settings 參數，所以比較時就用這個別名；要調門檻只改 `Thresholds.cosine_match` 的預設值一處。`Settings.project_id` 與 `need_settings()` 在本 Phase 只供 [Phase 41](41-Phase41-Ticket-Analysis雲端流程驗收.md) 的 Task 包裝決定要掃哪個專案，業務函式本身吃的是 `ticket.project_id`。

## 6. 設計細節

`ensure_embedding` 的固定順序如下。重點是**先一致讀取既有 TICKET**，再決定要不要呼叫模型。

```text
  以 ticket_pk 一致讀取既有 TICKET
            |
   已保存 embedding？ -- 是 --> 回傳既有 Ticket（呼叫模型 0 次）
            | 否
   writer.embed(text, node="ticket-embedding")
            |
   PermanentError（非 1024 維／NaN／bool）-- 是 --> 原樣往上拋，不寫回
            | 否
   put_meta(create_only=False) 寫回，回傳帶向量的 Ticket
```

維度與數值有效性由 [Phase 16](16-Phase16-Titan-Embedding與向量計算.md) 的 `Writer.embed` 負責檢查並丟 `PermanentError`；本 Phase 只負責「缺了才叫」「叫完要存」與「例外時一個字都不寫」。`TransientError` 同樣原樣往上拋，交給 ASL 的 Retry，函式內不自行重試。

寫回用 `put_meta(create_only=False)`，因為 TICKET 已由接入層建立；[Phase 06](06-Phase06-Repository-Metadata與實體讀寫.md) 的覆寫路徑是 `_revision` 的 compare-and-swap，版本過期時丟 `CoordinationError`，本函式**不吞不重試**，由上層依 O2 語意重讀重算。想省一次寫入前的讀取時，也可以改用同一次讀到的 `_revision` 呼叫 `update_meta(pk, changes, expected_revision=...)`，語意相同。併發保護依賴設計 §8.3 的單專案串行接受順序，屬於 O2，未通過前不得宣稱已無競態。

`assign_cluster` 的固定順序：

```text
  傳入 Ticket 已有 cluster_id？ -- 是 --> 原樣回傳（重試沿用，設計 §14.2）
            | 否
  讀同 project 全部 Ticket（分頁讀完）-> 依 cluster_id 分組
            |
  每組算 centroid -> cosine(本筆向量, centroid) -> 篩掉 < 0.85
            |
   還有候選？ -- 否 --> new_cluster_id(所有既有 cluster_id)
            | 是
  依 (分數由大到小, cluster_id 由小到大) 排序，取第一個
```

同分取 `cluster_id` 升序，是為了讓重送得到同一個答案；沒有這條規則，掃描順序一變就會讓同一筆 Ticket 落到不同群。`assign_cluster` 只做判斷，不寫資料庫；把 `cluster_id` 寫回 TICKET 是 [Phase 41](41-Phase41-Ticket-Analysis雲端流程驗收.md) `assign_cluster` Task 的責任，該 Task 必須先一致讀取 TICKET 再呼叫。`new_cluster_id` 只認得 `c<數字>`：取現有最大數字加一，完全沒有既有群時回 `c1`，產生值若仍撞號就丟 `PermanentError`（不靜默換號）。編號的唯一性只在同一個 `project_id` 內成立，跨專案併發的保證屬於 O2。MVP 不做合群或重編號，既有 `cluster_id` 永遠保留，才能追溯到 `Tutorial.cluster_id`（設計 §7.3、D29）。

## 7. TDD Tasks

三支測試共用 `tests/unit/pipelines/conftest.py`：`fake_operations` 是只記錄呼叫的 `OperationCoordinator` 替身（本 Phase 不呼叫它，只為建構 `Deps`）；`fake_clock` 回固定的 aware UTC 時間；`embedding_writer` 的 `embed(text, *, operation_id, node)` 回 `embedding_writer.embedding`（預設 `[0.1] * 1024`）並累加 `embed_calls`，設了 `embedding_writer.error` 就改丟該例外——**名字刻意不叫 `fake_writer`**：[Phase 15](./15-Phase15-Writing介面與呼叫追蹤.md) 已經在 `tests/unit/conftest.py` 提供全套共用的 `fake_writer`（`RecordingWriter`，形狀是 `replies`／`tool_plans`／`calls`／`request_attempts`），近端 conftest 用同一個名字會**無聲地**把它蓋掉，讓同目錄其他 Phase 的測試拿到形狀不同的替身；本 Phase 只需要一個會數 `embed` 次數的替身，所以另取一個名字並存；`fake_repo` 用一個 dict 當表，提供 `get_meta`／`put_meta`／`list_tickets`，另加三個測試鉤子 `save_ticket(ticket)`（寫入並回傳同一筆）、`loaded(pk)`（讀回已存模型）、`tickets`（可直接指派的 `Ticket` 清單，`list_tickets` 就回它）；`settings` 是 `Settings(table_name="training_kb", content_bucket="tkb", project_id="demo")`。三個工廠 `ticket_without_embedding(ticket_id)`、`clustered(ticket_id, cluster_id, vector)`、`unclustered(ticket_id, vector)` 造出 `project_id="demo"`、`source="github_issue"`、`ts` 固定的 `Ticket`；它們**也以 fixture 形式提供**（pytest 官方的 factory-as-fixture 寫法），因為 conftest.py 的模組層級函式不會自動出現在測試模組的命名空間裡，測試要用就得把工廠名字寫進函式參數。`fake_repo.put_meta(create_only=True)` 撞鍵時照真實 `Repository` 丟 `CoordinationError`，`list_tickets` 也照真實版本濾 `project_id` 並依 `id` 升序——所以「回填必須用 `create_only=False`」與「同分排序不能靠掃描順序」兩條規則不必另開測試鉤子就擋得住。

### Task 1：讓 Deps 帶得動 repository、writer 與 settings

- [x] **Step 1：建立失敗測試**

```python
import pytest

from training_kb.errors import PermanentError
from training_kb.pipelines.common import Deps

def test_deps_keeps_old_construction(fake_operations, fake_clock):
    legacy = Deps(operations=fake_operations, now=fake_clock)
    assert legacy.repository is None
    with pytest.raises(PermanentError, match="repository"):
        legacy.need_repository()

def test_deps_returns_wired_dependencies(
        fake_operations, fake_clock, fake_repo, embedding_writer, settings):
    deps = Deps(fake_operations, fake_clock,
                repository=fake_repo, writer=embedding_writer, settings=settings)
    assert deps.need_repository() is fake_repo
    assert deps.need_writer() is embedding_writer
    assert deps.need_settings() is settings
```

- [x] **Step 2：執行並確認紅燈** — 跑 `uv run pytest tests/unit/pipelines/test_deps.py -q`，預期 FAIL，訊號含 `unexpected keyword argument 'repository'`。

- [x] **Step 3：建立最小實作**

三個新欄位放在既有欄位之後並預設 `None`；三個 helper 共用同一個檢查形狀：

```python
def need_repository(self) -> "Repository":
    if self.repository is None:
        raise PermanentError("pipeline deps 缺少 repository")
    return self.repository
```

`need_writer`、`need_settings` 照同一形狀各寫一個（訊息各自換成 `writer`／`settings`），不要改成回傳 `None` 的寬鬆版本，也不要合併成一個吃字串參數的動態版本。

- [x] **Step 4：跑新舊測試確認綠燈** — 跑 `uv run pytest tests/unit/pipelines/test_deps.py tests/unit/pipelines/test_common.py -q`，預期新舊測試全部 PASS，且 Phase 29 的 `test_common.py` 一行都沒有改。

- [x] **Step 5：提交**

```bash
git add src/training_kb/pipelines/common.py tests/unit/pipelines/test_deps.py tests/unit/pipelines/conftest.py
git commit -m "feat(pipeline): 擴充 Deps 相依"
```

### Task 2：缺向量才呼叫 Titan，重送不重算

- [x] **Step 1：建立失敗測試**

```python
from training_kb.keys import ticket_pk
from training_kb.pipelines.ticket import ensure_embedding

def test_ensure_embedding_calls_model_once_and_persists(
        fake_repo, embedding_writer, ticket_without_embedding):
    embedding_writer.embedding = [0.1] * 1024
    ticket = fake_repo.save_ticket(ticket_without_embedding("t_881"))
    kw = {"writer": embedding_writer, "repository": fake_repo, "operation_id": "op-ticket-t_881"}
    first, second = ensure_embedding(ticket, **kw), ensure_embedding(ticket, **kw)
    assert len(first.embedding) == 1024
    assert second.embedding == first.embedding
    assert embedding_writer.embed_calls == 1
    assert fake_repo.loaded(ticket_pk("t_881")).embedding == first.embedding
```

`ticket_without_embedding` 來自本 Phase 的 `conftest.py`，它是一個工廠 fixture，所以名字要寫進測試函式的參數；PK 一律由 Phase 05 的 `ticket_pk` 產生，不手寫 `"TICKET#t_881"` 這種字串。

- [x] **Step 2：執行並確認紅燈** — 跑 `uv run pytest tests/unit/pipelines/test_ticket_embedding.py -q`，預期 FAIL。`ticket.py` 這時整支都還不存在，所以實際訊號是更前面一步的 `ModuleNotFoundError: No module named 'training_kb.pipelines.ticket'`；等 Task 3 的測試先寫時才會看到 `cannot import name 'assign_cluster'`。

- [x] **Step 3：建立最小實作**

```python
def ensure_embedding(ticket, *, writer, repository, operation_id):
    stored = repository.get_meta(ticket_pk(ticket.id), Ticket, consistent=True)
    current = stored or ticket
    if current.embedding:
        return current
    vector = writer.embed(current.text, operation_id=operation_id, node="ticket-embedding")
    updated = current.model_copy(update={"embedding": vector})
    repository.put_meta(updated, create_only=False)
    return updated
```

- [x] **Step 4：補三個邊界案例後跑綠**

三個案例：資料庫已有向量但傳入物件沒有（以資料庫為準、0 次呼叫）；`embed` 丟 `PermanentError`（不寫回、不留半筆）；`embed` 丟 `TransientError`（原樣往上拋交給 ASL Retry，函式內不自行重試）。跑 `uv run pytest tests/unit/pipelines/test_ticket_embedding.py -q`，預期全部 PASS，四個案例的 `embedding_writer.embed_calls` 分別是 1、0、1、1。

- [x] **Step 5：提交**

```bash
git add src/training_kb/pipelines/ticket.py tests/unit/pipelines/test_ticket_embedding.py
git commit -m "feat(ticket): 只在缺向量時產生 embedding"
```

### Task 3：以群中心歸群並固定 0.85 邊界

- [x] **Step 1：建立失敗測試**

```python
import pytest

from training_kb.pipelines.ticket import assign_cluster
from training_kb.vectors import cosine
from training_kb.writing.client import TITAN_DIMENSIONS

# 四個種子刻意用整數構成，讓 cosine 精確：dot = 17、|AXIS| = 1、|ON| = 20、17 / 20 = 0.85。
# `Ticket.embedding`（Phase 04）只收「1024 個有限數值」，所以種子要補零到 TITAN_DIMENSIONS
# 才放得進模型；補零不動 dot 也不動任何一條 norm，上面那個算式原封不動成立。
SEED_AXIS = [1.0, 0.0, 0.0, 0.0, 0.0]
SEED_ON = [17.0, 7.0, 6.0, 5.0, 1.0]
SEED_BELOW = [16.99, 7.0, 6.0, 5.0, 1.0]        # 約 0.84986，穩定落在門檻下方
SEED_ORTHOGONAL = [0.0, 1.0, 0.0, 0.0, 0.0]

def vector(seed):
    return seed + [0.0] * (TITAN_DIMENSIONS - len(seed))

AXIS, ON, BELOW, ORTHOGONAL = (vector(SEED_AXIS), vector(SEED_ON),
                               vector(SEED_BELOW), vector(SEED_ORTHOGONAL))

def test_reference_vectors_sit_on_both_sides_of_the_threshold():
    assert cosine(SEED_AXIS, SEED_ON) == 0.85       # 五維的精確算式：17 / 20
    assert cosine(AXIS, ON) == 0.85                 # 補零到 1024 維後完全一樣
    assert cosine(AXIS, BELOW) < 0.85
    assert len(AXIS) == TITAN_DIMENSIONS

@pytest.mark.parametrize(("vector", "expected"), [(ON, "c12"), (BELOW, "c14")])
def test_assign_cluster_threshold_is_inclusive(fake_repo, clustered, unclustered,
                                               vector, expected):
    fake_repo.tickets = [clustered("t_100", "c12", vector), clustered("t_101", "c13", ORTHOGONAL)]
    assert assign_cluster(unclustered("t_881", AXIS), repository=fake_repo) == expected

def test_assign_cluster_breaks_ties_by_cluster_id(fake_repo, clustered, unclustered):
    fake_repo.tickets = [clustered("t_100", "c12", AXIS), clustered("t_101", "c07", AXIS)]
    assert assign_cluster(unclustered("t_882", AXIS), repository=fake_repo) == "c07"
```

單元測試用五維種子就夠決定比較與排序的結果（補零到 1024 維不改變任何 cosine）；1024 維契約由 Phase 16 與 `Ticket.embedding` 的驗證負責，這裡綠燈不代表 Titan 已驗證。`BELOW` 的 `16.99` 讓分數穩定低於門檻，但四捨五入後仍是設計 §15 要求的 `0.8499` 那一側。`TITAN_DIMENSIONS`（`writing/client.py`）是「向量幾維」這個數字的唯一一份，測試也不另外寫一次 `1024`。

- [x] **Step 2：執行並確認紅燈** — 跑 `uv run pytest tests/unit/pipelines/test_ticket_cluster.py -q`，預期 FAIL，訊號包含 `cannot import name 'assign_cluster'`。

- [x] **Step 3：建立最小實作**

```python
def assign_cluster(ticket, *, repository):
    if ticket.cluster_id:
        return ticket.cluster_id
    if not ticket.embedding:
        raise PermanentError("assign_cluster 需要已保存的 embedding")
    known: set[str] = set()
    groups: dict[str, list[list[float]]] = {}
    for other in repository.list_tickets(ticket.project_id):
        if not other.cluster_id:
            continue
        known.add(other.cluster_id)
        if other.id != ticket.id and other.embedding:
            groups.setdefault(other.cluster_id, []).append(other.embedding)
    scored = [(cosine(ticket.embedding, centroid(r)), cid) for cid, r in groups.items()]
    good = sorted((i for i in scored if i[0] >= CLUSTER_COSINE_THRESHOLD), key=lambda i: (-i[0], i[1]))
    return good[0][1] if good else new_cluster_id(known)

def new_cluster_id(existing):
    known = set(existing)
    numbers = [int(v[1:]) for v in known if v[:1] == "c" and v[1:].isdigit()]
    candidate = f"c{max(numbers) + 1 if numbers else 1}"
    if candidate in known:
        raise PermanentError(f"新群編號 {candidate} 已存在")
    return candidate
```

- [x] **Step 4：補四個案例後跑綠**

四個案例：單一樣本的群也要走 `centroid`；成員缺 `embedding` 只略過該成員、不整群作廢；完全沒有既有群時回 `c1`；傳入 Ticket 已有 `cluster_id` 時直接回原值。跑 `uv run pytest tests/unit/pipelines/test_ticket_cluster.py -q`，預期全部 PASS，且沒有任何案例呼叫 `writer.embed`。

- [x] **Step 5：提交**

```bash
git add src/training_kb/pipelines/ticket.py tests/unit/pipelines/test_ticket_cluster.py
git commit -m "feat(ticket): 以群中心分群"
```

## 8. 驗收矩陣

| 路徑 | 輸入 | 預期資料結果 |
|---|---|---|
| Happy | `t_881` 缺向量、`c12` 群中心相似度 0.91 | 呼叫模型一次、寫回 1024 維、回 `c12`。 |
| Happy | `t_881` 重送 | 模型 0 次；向量與群組與第一次相同。 |
| Failure | Titan 回 1023 維 | `Writer.embed` 丟 `PermanentError` 並原樣往上拋；TICKET 沒有被寫入半筆向量。 |
| Failure | `Deps` 沒接 repository | `need_repository()` 丟 `PermanentError`，不是在深處拿到 `None`。 |
| Boundary | 最高相似度 `0.8499` | 不入既有群，開新群 `c14`。 |
| Boundary | 最高相似度 `0.85` | 入既有群 `c12`。 |
| Boundary | `c07` 與 `c12` 同為 0.9 | 取 `c07`（cluster_id 升序）。 |

人工驗收：打開一筆真實寫回後的 TICKET item，確認 `embedding` 是 1024 個原生 number（不是 JSON 字串）、`cluster_id` 是 `c<數字>`，而且 item 上沒有模型以外的額外屬性（00A §3.6）；再重送同一筆事件，核對 `CallTrace` 沒有新增 `kind=embedding` 的 attempt。只看 pytest PASS 不算完成。

## 9. 常見錯誤與停止條件

| 症狀 | 原因 | 修正／停止 |
|---|---|---|
| 每次重送 Bedrock 呼叫數都增加 | 先算向量再查資料庫，或只看傳入物件 | 先一致讀取 TICKET；`embedding` 有值就直接回。 |
| 兩次執行群組結果不同 | 同分沒有固定排序，或依賴 dict 插入順序 | 用 `(-分數, cluster_id)` 排序；同分取最小 ID。 |
| 用群裡「第一筆」當代表比對 | 把樣本當群中心 | 一律呼叫 `centroid`，即使群裡只有一筆。 |
| 新群編號撞到既有群 | 用群數或長度猜編號 | `new_cluster_id` 取最大數字加一，撞號就丟 `PermanentError`。 |
| 模組裡又出現一個 `0.85` | 沒有把門檻接回 `Thresholds.cosine_match` | `CLUSTER_COSINE_THRESHOLD` 只能是欄位別名（00A D-35）。`assign_cluster` 的簽名沒有 settings 參數（00A §6.9），所以比較時就用這個別名，不從 `need_settings().thresholds` 另取一份。 |
| 寫回時吞掉 `CoordinationError` 後重試 | 把樂觀鎖失敗當暫時故障 | `put_meta(create_only=False)` 的 revision 過期屬 O2 範圍，原樣往上拋，由上層重讀重算。 |
| 宣稱「分群已驗證」但只有假向量 | 把 FakeWriter 綠燈當模型驗收 | O5 未通過前維持 BLOCKED；真實 20 筆分群留待 Phase 56。 |

## 10. 來源與 Rule 對照

- [分析工單.feature](../../spec/features/分析工單.feature)
  - Rule 1（primary）：「每則 Ticket 在接入分析時計算一次並儲存 1024 維 embedding」→ Task 2 的 `test_ensure_embedding_calls_model_once_and_persists` 直接斷言呼叫一次且寫回 1024 維。
  - Rule 2（primary）：「demo 分群以 cosine 至少 0.85 為同群門檻」→ Task 3 的 `0.8499`／`0.85` 參數化測試直接斷言邊界；同分排序由 `test_assign_cluster_breaks_ties_by_cluster_id` 鎖定。
- 設計 §7.3：缺 embedding 才呼叫 Titan、群中心取最高、無合格群建新 `cluster_id`、同分依 cluster_id 升序、MVP 不合群不重編號；§9.1：`Ticket.embedding` 是 1024 個原生數值，不另存 `embedding_ref`；§14.2：儲存階段重試重用已保存結果；§15：驗收必須看到 `0.8499`／`0.85` 兩側案例。
- 決策 D08（以 `Ticket.embedding` 為權威）、D29（`cluster_id` 需保留可追溯身分）、F10（比較群中心並取最高）。
- [Titan Embeddings 官方文件](https://docs.aws.amazon.com/bedrock/latest/userguide/titan-embedding-models.html)：1024 維與 embedding 專用參數；請求格式由 Phase 16 鎖定，本 Phase 不重複定義，也不對 Titan 傳 `max_tokens`／`temperature`。

## 11. 完成清單

- [x] `Deps` 新增三個 keyword 欄位與三個 `need_*`，Phase 29 既有測試未修改仍通過。
- [x] `ensure_embedding`、`assign_cluster`、`new_cluster_id` 的簽名與本文件、00A §6.9 一致。
- [x] 已保存向量時模型呼叫次數為 0，並有測試直接斷言。
- [x] `0.8499` 與 `0.85` 兩個邊界案例都有獨立斷言，同分取最小 `cluster_id`。
- [x] `CLUSTER_COSINE_THRESHOLD` 是 `Thresholds.cosine_match` 的別名，模組裡沒有第二份 `0.85`。
- [x] 寫回只動模型欄位，`CoordinationError`／`TransientError` 都原樣往上拋，不在函式內重試。
- [x] 新群編號不會與既有群撞號，撞號時明確失敗。
- [x] 未把 FakeWriter 綠燈描述成 Titan 或 AWS 已通過；O5 未過維持 BLOCKED，O2 未過不宣稱無撞號。

## 12. 實作期間的文件修正與裁決（2026-09-14）

| # | 位置 | 原文要點 | 改後 | 理由 |
|---|---|---|---|---|
| 1 | Task 3 Step 1 的測試碼、Step 1 之後的說明 | 參考向量是五維的 `AXIS`／`ON`／`BELOW`／`ORTHOGONAL`，直接餵給 `clustered(...)`／`unclustered(...)` | 五維改成「種子」，用 `vector(seed)` 補零成 `TITAN_DIMENSIONS`（1024）維再放進 `Ticket` | `Ticket.embedding`（Phase 04 `models.py`）有 `field_validator`：不是 1024 個有限數值就 `ValidationError: embedding must contain 1024 finite numbers`，照原文寫的測試連 fixture 都建不起來。補零不改變 dot 也不改變任何一條 norm，`cosine(AXIS, ON) == 0.85` 與 `cosine(AXIS, BELOW) < 0.85` 原封不動成立（測試裡兩個斷言都留著）。依「設計 > 00A > Phase 文件」，以 00A §5.1 的模型欄位為準。 |
| 2 | §4 表格、§7 conftest 說明、Task 2／Task 3 的測試函式簽名 | 三個 `Ticket` 工廠被當成可以直接呼叫的名字（`clustered("t_100", ...)`），但 conftest 只列為「五個 fixture 與三個工廠」 | 三個工廠也以 pytest 官方的 factory-as-fixture 形式提供，測試把工廠名字寫進函式參數；測試**內容**逐字不變 | conftest.py 的模組層級函式不會自動進入測試模組的命名空間，照原文寫會 `NameError`。改用 sys.path 把 conftest 當模組 import 是脆弱作法（兩個同名 conftest），fixture 是標準解。 |
| 3 | Task 2 Step 2 | 預期紅燈訊號是 `cannot import name 'ensure_embedding'` | 補記實際訊號是更前面一步的 `ModuleNotFoundError: No module named 'training_kb.pipelines.ticket'` | Task 2 是本檔的第一個函式，`ticket.py` 這時整支都還不存在。`cannot import name 'assign_cluster'` 在 Task 3 Step 2 如實出現。 |
| 4 | §9 常見錯誤表最後一列 | 「跑 pipeline 時從 `need_settings().thresholds` 取」 | 改為「`assign_cluster` 的簽名沒有 settings 參數（00A §6.9），所以比較時就用這個別名」 | 與同一份文件 §5 的裁決（以及 00A §6.9 的簽名）互相矛盾；`assign_cluster(ticket, *, repository)` 根本拿不到 settings。 |
| 5 | 全域限制的 gate 段 | 只寫 O5／O2 未通過的禁止事項 | 補一句「離線開發照常完成，真實 AWS 接線延後」與裁決來源 | controller 2026-09-14 裁決（`.superpowers/sdd/phase0914-1/COMMON.md`），與 Phase 15 §12 第 1 列同一條。 |

### 實作時的其他選擇（不算文件錯誤）

- `writer.embed(..., node="ticket-embedding")` 的節點名照 §6 的 sketch **內嵌字面值**，不另外宣告 `EMBEDDING_NODE` 常數：00A §6.9 沒有把這個名字列進 Phase 38 的公開介面，多一個公開名稱會讓 Phase 39／41 有機會各寫一份不同的字串。
- `new_cluster_id` 最後那道撞號檢查在結構上不可能被觸發（`max + 1` 一定大於所有解析得出的既有編號），它是防守用的。測試因此改成斷言「回傳值永遠不在既有集合裡」，沒有為了覆蓋率去偽造無法發生的輸入。

### gate 狀態（未變更）

- **O5 BLOCKED**：帳號未開通 Bedrock，本 Phase 全程使用 `embedding_writer` 假向量。1024 維寫回、只呼叫一次、分群邊界都只在假向量上綠燈，**不代表** Titan 或真實分群已驗證；真實 20 筆分群留待 Phase 56。
- **O2 未通過**：`new_cluster_id` 的編號唯一性只在單一 `project_id` 的單執行緒語意下成立，不得宣稱「併發下新群 ID 不會撞號」已驗收。
