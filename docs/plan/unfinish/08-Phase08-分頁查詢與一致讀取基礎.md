# Phase 08：分頁查詢與一致讀取基礎實作計畫

> **給實作者：** 依 checkbox 逐步執行；每個 Task 先建立失敗測試，再寫最小實作。執行時使用 `superpowers:executing-plans` 或同等逐項流程。

**目標：** 讓 PK Query、`by_target` GSI Query 與 entity Scan 一律讀完所有分頁（包含空的一頁），並在此之上提供六個固定的 list 讀取。

**架構：** 三個公開查詢共用同一個 `_paged` 迴圈，只差在傳給 boto3 的參數。基表查詢可以一致讀取；`by_target` GSI 只有最終一致而且只投影鍵，所以它只產生候選，任何業務判斷都要回基表核對。

**技術：** Python 3.12、boto3 `Key`／`Attr` 條件、moto `mock_aws`、pytest、Phase 07 的 `_paged` 與邊寫入。

## 全域限制

- 唯一主來源是 [Training KB 設計 §9.1、§10](../../design/training-kb.md)；前置為 [Phase 07：S3 物件與關係邊讀寫](./07-Phase07-S3物件與關係邊讀寫.md)，Phase 07 未通過時停止。
- 下一階段是 [Phase 09：AWS 資料資源與最小 IAM](./09-Phase09-AWS資料資源與最小IAM.md)。
- 本階段不做：不實作 Phase 27 的六種固定圖譜查詢、不做 Phase 28 的 backfill、不呼叫任何模型、不新增第二個索引或第二張表、不決定哪一版是 current；「哪一版是目前已發布版」由呼叫端用 `Tutorial.current_version` 與 `VERSION.published_at` 判斷。
- 與本 Phase 有關的 gate：O1 必須已關閉才可讀寫 item。GSI 最終一致造成的漏邊只能靠基表一致讀取核對，設計明說「不能只多等固定秒數便宣稱結果完整」；跨併發寫入的完整性與 O2、O3 一起驗收，本 Phase 不得宣稱已解決。
- moto 通過只代表本機模擬行為，不代表真實 DynamoDB 的分頁與一致性已驗證。以下程式檔均是實作時預計建立或修改；本計畫本身不代表它們已存在。

---

## 1. 你在整體流程的位置

```text
Phase 07 邊與物件寫入 -> [你在這裡] Phase 08
      |  query_pk（基表，一致讀取）｜ query_by_target（GSI，最終一致，只有鍵）
      |  scan_entity（基表，一致讀取 + entity 過濾，預設只回 META）｜ item_to_model ｜ 六個 list
      +-------------------+-------------------+
      v                   v                   v
 Phase 27 圖譜      Phase 44-47 回饋   Phase 50 Release 反查
```

## 2. 完成後看得到什麼

輸入：`prepare-meeting@v1` 有八筆 `REFERS_TO` 回饋邊、兩筆指向同一版的其他關係邊，表中另有三十筆無關 item。

```text
list_feedback_of_version("prepare-meeting@v1")
  -> by_target 候選（只有 PK / SK / target）-> 過濾 REFERS_TO + FEEDBACK# 起點
  -> 逐筆回基表一致讀取 -> [f_12, f_15, f_19, f_23, f_27, f_31, f_34, f_40]

get_steps("prepare-meeting@v2") -> 依編號升序的三筆 TutorialStep，各帶一個 feature_id

scan_entity("TICKET") 遇到「空的一頁但仍有 LastEvaluatedKey」
  -> 不停止，帶 ExclusiveStartKey 續查到沒有游標為止
```

## 3. 名詞小抄

| 名詞 | 白話意思 |
|---|---|
| 分頁 | DynamoDB 一次最多回 1 MB；沒回完會給一把游標 `LastEvaluatedKey`，要拿它再查一次。沒有游標才代表真的讀完。 |
| 空的一頁 | 這一頁掃到的 item 全被 filter 濾掉，`Items` 是空的但游標還在；提前停止就會漏資料。 |
| 一致讀取 | 基表可以要求讀到最新寫入；GSI 沒有這個選項，回來的鍵只能當「可能有關」的候選，要回基表確認。 |
| `entity` 屬性 | item 上的類型標記，值等於 PK 前綴（`TICKET`、`STEP`、`VIEW`…）。因為值是**前綴**，同一個起點的關係邊也會帶同一個 `entity`，Scan 時會一起被掃到。 |
| `meta_only` | `scan_entity` 的開關，預設 `True`：只回 `SK == META` 的那一筆（實體本體），把同前綴的關係邊濾掉。只有 `get_steps` 要用 `meta_only=False`，因為步驟本來就沒有 `META`。 |
| `KEYS_ONLY` | GSI 的投影方式：索引裡只存鍵（`PK`、`SK`、`target`），其他欄位都要回基表拿。 |
| `item_to_model` | 把 DynamoDB 的 raw item 去掉保留屬性後交給 Pydantic 驗證的共用小函式；模型是 `extra="forbid"`，直接餵 raw item 一定會 `ValidationError`。 |

## 4. 預計檔案

| 動作 | 路徑 | 責任 |
|---|---|---|
| 修改 | `src/training_kb/repository.py` | `_paged` 加 `page_size`、模組函式 `item_to_model`、三個公開查詢與六個 list 讀取。 |
| 修改 | `tests/integration/conftest.py` | 測試表加上 `by_target` GSI 與 `page_size` fixture。 |
| 測試 | `tests/unit/test_repository_paging.py` | 用腳本化假 table 鎖定空頁與游標行為。 |
| 測試 | `tests/integration/test_repository_queries.py` | moto 上的三種查詢、GSI 核對與六個 list 讀取。 |

> **本次結果（2026-09-14）**：兩點與計畫時的假設不同，已依「設計 > 00A > Phase 文件」裁決。
> 一、`item_to_model` 在 Phase 06 就已經建立（commit `cd062a9`，簽名與 00A §6.3 完全相同），
> 本 Phase **只消費、不重新宣告**；下面 Task 1 Step 3 的 `item_to_model` 片段因此不必再寫一次。
> 二、`tests/integration/conftest.py` 在 00A §3.2 的 conftest 表上「修改者」欄是 `—`，但 P06 的
> conftest 自述「`by_target` GSI 由 Phase 08 補」，且沒有 GSI 就無法驗 `query_by_target`；
> 依本表補上 GSI（KEYS_ONLY，與 Phase 09 CDK 一致）與 `paged_repository` fixture，
> 建議 00A 把該列的修改者補成 P08。

## 5. 固定介面

### Consumes

```text
Repository._paged(operation, **arguments) -> list[DynamoItem]      # Phase 07 的私有分頁迴圈
Repository.put_edge(pk, relation, target_pk, attrs=None) -> None   # Phase 07
RESERVED_ATTRS = {"PK", "SK", "target", "entity", "_revision"}     # Phase 06
Repository.get_meta(pk, model, *, consistent=True) / put_meta(entity, *, create_only=True)
DynamoItem / T = TypeVar("T", bound=StrictModel)                   # 以上三行 Phase 06
META: str                                                          # Phase 05（meta_only 的比較值）
parse_pk(value) -> (kind, identifier) | parse_edge_sk(value) -> (relation, target_pk)
parse_step_pk(value) -> (version_id, number)                       # Phase 05；get_steps 用
version_pk / feedback_pk / step_pk / feature_pk …                  # Phase 05
TutorialStep / Feedback / TutorialView / Ticket / AuthoringRule / ProvenWorkflow  # Phase 04
RuleStatus（Phase 03 的 StrEnum）｜ PermanentError（Phase 02）
```

### Produces

```python
def item_to_model(item: DynamoItem, model: type[T]) -> T: ...   # 模組函式，不是方法

class Repository:
    def __init__(self, table: object, bucket: object | None = None, *, page_size: int | None = None) -> None: ...
    def query_pk(self, pk: str, *, sk_prefix: str | None = None, consistent: bool = True) -> list[DynamoItem]: ...
    def query_by_target(self, target_pk: str) -> list[DynamoItem]: ...
    def scan_entity(self, entity: str, *, consistent: bool = True, meta_only: bool = True) -> list[DynamoItem]: ...
    def get_steps(self, version_id: str) -> list[TutorialStep]: ...
    def list_feedback_of_version(self, version_id: str) -> list[Feedback]: ...
    def list_views_of_version(self, version_id: str) -> list[TutorialView]: ...
    def list_tickets(self, project_id: str) -> list[Ticket]: ...
    def list_rules(self, status: RuleStatus | None = None) -> list[AuthoringRule]: ...
    def list_procs(self, domain: str, adapter: str) -> list[ProvenWorkflow]: ...
```

`meta_only` 預設 `True`（00A §6.3、裁決 D-39）。`entity` 屬性的值是 **PK 前綴**，所以 `scan_entity("RULE")` 不只掃到 `RULE#R-007` 的 `META`，也會掃到同一個 PK 上的 `APPLIED_TO#…` 邊；`scan_entity("TICKET")` 同理會掃到 `ASKS_ABOUT#…` 邊。這些邊沒有模型欄位，直接拿去 `item_to_model` 會整筆 `ValidationError`。預設只回 `SK == META` 的 item，六個 list 讀取就自動安全；唯一要傳 `meta_only=False` 的是 `get_steps`，因為 STEP 根本沒有 `META` item（它的 item 本身就是 `REFERENCES#` 邊）。

`page_size` 只是測試鉤子：有值時對每次請求加上 `Limit`，讓小資料也能製造多頁與空頁；正式程式不設定它，讓 DynamoDB 用預設的 1 MB 分頁。三個查詢回的是 raw item（含 `PK`／`SK`／`entity`／`_revision`），**要轉成 Phase 04 的 model 一律走 `item_to_model`**（或整筆重讀的 `get_meta`），不可直接 `Model.model_validate(item)`：Phase 03 的 `StrictModel` 是 `extra="forbid"`，多一個 `PK` 就會 `ValidationError`。Phase 27、28、39、44、50 之後做同樣轉換時都 import 這個函式，不各寫一份過濾。

## 6. 設計細節

分頁迴圈只有一個結束條件：回應裡沒有 `LastEvaluatedKey`。官方文件寫得很明確——非空的 `LastEvaluatedKey` 不代表一定還有符合條件的資料，而「唯一知道已讀完的方式，是 `LastEvaluatedKey` 為空」。有 `FilterExpression` 時，1 MB／`Limit` 上限是在過濾前就套用，所以一頁可以零筆結果卻仍帶游標。

```text
arguments = {...}（page_size 有值就加 Limit）
      v
  呼叫 query / scan <---------------------------+
      |                                         |
  items += response["Items"]（可能是 0 筆）      |
      |                                         |
  有 LastEvaluatedKey？ -- 是 --> 設 ExclusiveStartKey
      | 否
      v  回傳全部 items
```

三種查詢的一致性責任不同：

```text
query_pk / scan_entity -> 基表 -> ConsistentRead=True -> 可當判斷依據
query_by_target        -> GSI  -> 最終一致 + KEYS_ONLY -> 只能當候選
                                    |
                                    v  逐筆回基表 get_meta（一致讀取）
                                       讀得到 -> 納入結果
                                       讀不到 -> PermanentError
```

GSI 只會落後基表，不會多出基表沒有的資料，所以「候選讀不到本體」代表資料不完整，必須明確失敗而不是安靜跳過。反過來，GSI 可能還沒反映剛寫入的邊：需要完整引用集合時（Phase 50 的 Release 反查）要用基表核對，不能只等幾秒就宣稱查完。

`scan_entity` 的過濾條件是 `entity`，而 `entity` 的值是 PK 前綴，所以掃出來的不只有實體本體：

```text
scan_entity("RULE")   命中 PK=RULE#R-007 SK=META            <- 本體（要）
                      命中 PK=RULE#R-007 SK=APPLIED_TO#…    <- 邊（不要）
scan_entity("TICKET") 命中 SK=META 與 SK=ASKS_ABOUT#…
scan_entity("STEP")   只有 SK=REFERENCES#…，沒有 META       <- 所以要 meta_only=False
```

這就是 `meta_only=True` 當預設的理由：六個 `list_*` 什麼都不用做就只看得到本體，唯一例外是 `get_steps`。

`get_steps` 是本 Phase 最容易寫歪的一個，因為步驟沒有自己的 metadata item：

```text
Phase 23 create_version：put_edge("STEP#prepare-meeting@v2#3", "REFERENCES",
  "FEATURE#Prepare", {"tutorial_version":…, "number":3, "type":…, "text":…})
        |  一筆 item 同時是步驟本體與引用邊；沒有 META、沒有 step_count
        v
get_steps("prepare-meeting@v2") = scan_entity("STEP", meta_only=False) 依版本過濾
  number / tutorial_version <- parse_step_pk(PK)（鍵是權威，不靠屬性）  type / text <- item 屬性
  feature_id <- parse_pk(target)[1]（所以每一步只會有一個 Feature）
  -> item_to_model(payload, TutorialStep) -> 依 number 升序
```

STEP 的 PK 每一步都不同（`STEP#<slug>@v<n>#<i>`），沒辦法用單一 PK Query 一次拿到整版；設計 §10 已接受「MVP 對基表分頁 Scan」這個少量資料取捨（同一節也用 Scan 解 VERSION 與 VIEW 兩個問題）。應有步驟數的權威是 S3 全文 `parse_markdown().steps`（Phase 23），不是這裡掃到幾筆，所以 item 上**不可以**為了省事加一個 `step_count`（[00A](00A-共用契約與名詞.md) §3.6）。

## 7. TDD Tasks

### Task 1：空頁不得提前停止

- [x] **Step 1：建立失敗測試**

```python
from training_kb.repository import Repository


class ScriptedTable:
    def __init__(self, pages: list[dict[str, object]]) -> None:
        self.pages = pages
        self.requests: list[dict[str, object]] = []

    def _record(self, **kwargs: object) -> dict[str, object]:
        self.requests.append(kwargs)
        return self.pages[len(self.requests) - 1]

    scan = query = _record


def test_empty_page_with_cursor_does_not_stop_the_scan() -> None:
    ticket = {"PK": "TICKET#t_2", "SK": "META", "entity": "TICKET"}
    cursor = {"PK": "FEEDBACK#f_12", "SK": "META"}
    table = ScriptedTable([
        {"Items": [], "LastEvaluatedKey": cursor},
        {"Items": [ticket], "LastEvaluatedKey": {"PK": "TICKET#t_2", "SK": "META"}},
        {"Items": []},
    ])
    assert Repository(table).scan_entity("TICKET") == [ticket]
    assert len(table.requests) == 3
    assert table.requests[1]["ExclusiveStartKey"] == cursor
    assert table.requests[0]["ConsistentRead"] is True


def test_gsi_query_never_asks_for_consistent_read() -> None:
    table = ScriptedTable([{"Items": []}])
    assert Repository(table).query_by_target("FEATURE#Prepare") == []
    assert table.requests[0]["IndexName"] == "by_target"
    assert "ConsistentRead" not in table.requests[0]
```

- [x] **Step 2：執行並確認紅燈**

```bash
uv run pytest tests/unit/test_repository_paging.py -q
```

預期：FAIL，訊號包含 `'Repository' object has no attribute 'scan_entity'`。

- [x] **Step 3：建立最小實作**

```python
from boto3.dynamodb.conditions import Attr, Key   # RESERVED_ATTRS 已在同一個 repository.py 裡

def item_to_model(item, model):
    payload = {key: value for key, value in item.items() if key not in RESERVED_ATTRS}
    return model.model_validate(payload)

def _paged(self, operation, **arguments):   # Phase 07 的迴圈，這裡只多加 page_size
    if self._page_size is not None:
        arguments["Limit"] = self._page_size
    items: list[DynamoItem] = []
    while True:
        response = operation(**arguments)
        items.extend(response.get("Items", []))
        cursor = response.get("LastEvaluatedKey")
        if not cursor:
            return items
        arguments["ExclusiveStartKey"] = cursor

def query_pk(self, pk, *, sk_prefix=None, consistent=True):
    condition = Key("PK").eq(pk)
    if sk_prefix is not None:
        condition = condition & Key("SK").begins_with(sk_prefix)
    return self._paged(
        self._table.query, KeyConditionExpression=condition, ConsistentRead=consistent)

def query_by_target(self, target_pk):
    condition = Key("target").eq(target_pk)
    return self._paged(self._table.query, IndexName="by_target", KeyConditionExpression=condition)

def scan_entity(self, entity, *, consistent=True, meta_only=True):
    where = Attr("entity").eq(entity)
    rows = self._paged(self._table.scan, FilterExpression=where, ConsistentRead=consistent)
    if not meta_only:
        return rows
    return [row for row in rows if str(row["SK"]) == META]
```

`item_to_model` 是**模組函式**不是方法，因為 Phase 27、28、39、44、50 會直接 import 它。`query_by_target` 沒有也不能有 `ConsistentRead`；GSI 不支援一致讀取。`__init__` 多存一行 `self._page_size = page_size`。`META` 由 Phase 07 已經 import 進同一支 `repository.py`（`from training_kb.keys import META, …`），不必再寫一次 import。`meta_only` 的過濾放在讀完所有分頁之後，不寫進 `FilterExpression`：一個請求只送一條 filter 比較好讀，而且分頁行為（空頁仍帶游標）在 Task 1 已經鎖住了。

- [x] **Step 4：加 moto 多頁測試、跑綠燈並提交**

在 moto 表寫入 5 筆 `TICKET` 與 5 筆 `FEEDBACK` metadata，用 `Repository(table, page_size=1)` 呼叫 `scan_entity("TICKET")` 斷言回 5 筆；同樣方式驗 `query_pk` 在同一 PK 有多筆邊時回齊全部。

```bash
uv run pytest tests/unit/test_repository_paging.py tests/integration/test_repository_queries.py -q
git add src/training_kb/repository.py tests/unit/test_repository_paging.py tests/integration
git commit -m "feat(data): 讀完所有查詢分頁"
```

> **本次結果（2026-09-14）**：`page_size=1` 的 moto Scan 確實會出現「零筆但仍帶游標」的頁——
> 把 `_paged` 改成看到空 `Items` 就回傳，`test_scan_entity_reads_every_page_even_when_pages_come_back_empty`
> 與兩條單元測試立刻變紅（3 failed），改回來就綠，證明測試真的鎖得住這個行為。
> `query_by_target` 的 `IndexName` 直接寫字面值 `"by_target"`：它與 Phase 09 CDK 的 `TARGET_INDEX`
> 同值，但 `src/` 不得 import `infra/`（會把 aws-cdk-lib 拉進執行期），所以兩邊各自宣告、以測試對齊。

### Task 2：GSI 候選一定回基表核對

- [x] **Step 1：建立失敗測試並確認紅燈**

```python
from datetime import UTC, datetime

from training_kb.keys import feedback_pk, version_pk
from training_kb.models import Feedback


def feedback(feedback_id: str, version_id: str) -> Feedback:
    return Feedback(id=feedback_id, tutorial_version=version_id, rating=2, category="找不到按鈕",
                    comment=None, user="u_01", ts=datetime(2026, 8, 2, tzinfo=UTC))


def test_list_feedback_of_version_ignores_other_relations(repository) -> None:
    target = version_pk("prepare-meeting@v1")
    for feedback_id in ("f_15", "f_12"):
        repository.put_meta(feedback(feedback_id, "prepare-meeting@v1"))
        repository.put_edge(feedback_pk(feedback_id), "REFERS_TO", target)
    repository.put_edge(version_pk("prepare-meeting@v2"), "SUPERSEDES", target)
    found = repository.list_feedback_of_version("prepare-meeting@v1")
    assert [item.id for item in found] == ["f_12", "f_15"]
```

```bash
uv run pytest tests/integration/test_repository_queries.py -q -k feedback_of_version
```

預期：FAIL，訊號包含 `'Repository' object has no attribute 'list_feedback_of_version'`。

- [x] **Step 2：建立最小實作**

```python
from training_kb.errors import PermanentError
from training_kb.keys import parse_edge_sk, parse_pk, version_pk
from training_kb.models import Feedback

def list_feedback_of_version(self, version_id):
    target = version_pk(version_id)
    found = []
    for candidate in self.query_by_target(target):
        pk = str(candidate["PK"])
        relation, endpoint = parse_edge_sk(str(candidate["SK"]))
        if relation != "REFERS_TO" or parse_pk(pk)[0] != "FEEDBACK" or endpoint != target:
            continue
        item = self.get_meta(pk, Feedback)
        if item is None:
            raise PermanentError(f"feedback edge has no base item: {pk}")
        found.append(item)
    return sorted(found, key=lambda item: item.id)
```

這裡用 `get_meta`（整筆重讀）而不是 `item_to_model`，因為 GSI 候選只有鍵、沒有內容；`item_to_model` 是給 `scan_entity`／`query_pk` 回來的完整 raw item 用的。

- [x] **Step 3：補缺本體與 KEYS_ONLY 測試後跑綠燈**

再加兩條：一是候選存在但基表沒有本體時丟 `PermanentError`；二是斷言 `query_by_target` 回來的 item 只有 `PK`、`SK`、`target` 三個欄位，證明呼叫端不能直接拿 GSI 結果當內容。測試表的 `by_target` 必須用 `KEYS_ONLY` 投影，與 Phase 09 的 CDK 宣告保持一致。

```bash
uv run pytest tests/integration/test_repository_queries.py -q
```

- [x] **Step 4：提交**

```bash
git add src/training_kb/repository.py tests/integration
git commit -m "feat(data): 以基表核對 GSI 候選"
```

### Task 3：六個固定 list 與步驟排序

- [x] **Step 1：建立失敗測試**

```python
from training_kb.keys import feature_pk, step_pk


def test_get_steps_returns_sorted_steps_with_feature_ids(repository) -> None:
    for number in (3, 1, 2):
        attrs = {"type": "read", "text": f"step {number}"}
        pk = step_pk("prepare-meeting@v2", number)
        repository.put_edge(pk, "REFERENCES", feature_pk("Prepare"), attrs)
    repository.put_edge(step_pk("share-summary@v1", 1), "REFERENCES", feature_pk("Prepare"), attrs)
    steps = repository.get_steps("prepare-meeting@v2")
    assert [step.number for step in steps] == [1, 2, 3]
    assert {step.feature_id for step in steps} == {"Prepare"}
    assert steps[0].tutorial_version == "prepare-meeting@v2"
```

- [x] **Step 2：執行並確認紅燈**

```bash
uv run pytest tests/integration/test_repository_queries.py -q -k get_steps
```

預期：FAIL，訊號包含 `'Repository' object has no attribute 'get_steps'`。

- [x] **Step 3：建立最小實作（`get_steps` 與其餘五個 list）**

```python
from training_kb.keys import parse_step_pk
from training_kb.models import AuthoringRule, ProvenWorkflow, Ticket, TutorialStep, TutorialView

def get_steps(self, version_id):
    steps = []
    for item in self.scan_entity("STEP", meta_only=False):
        owner, number = parse_step_pk(str(item["PK"]))
        if owner != version_id:
            continue
        payload = {**item, "tutorial_version": owner, "number": number,
                   "feature_id": parse_pk(str(item["target"]))[1]}
        steps.append(item_to_model(payload, TutorialStep))
    return sorted(steps, key=lambda step: step.number)

def _scan_models(self, entity, model, key, **equals):   # 預設 meta_only=True，邊不會進來
    rows = [item for item in self.scan_entity(entity)
            if all(item.get(name) == value for name, value in equals.items())]
    return sorted((item_to_model(item, model) for item in rows), key=key)

def list_views_of_version(self, version_id):
    return self._scan_models("VIEW", TutorialView, lambda v: (v.ts, v.user),
                             tutorial_version=version_id)

def list_tickets(self, project_id):
    return self._scan_models("TICKET", Ticket, lambda t: t.id, project_id=project_id)

def list_rules(self, status=None):
    rules = self._scan_models("RULE", AuthoringRule, lambda r: r.rule_id)
    return rules if status is None else [rule for rule in rules if rule.status == status]

def list_procs(self, domain, adapter):
    return self._scan_models("PROC", ProvenWorkflow, lambda p: p.signature,
                             domain=domain, adapter=adapter)
```

`get_steps` 的 `number` 與 `tutorial_version` 一律由 PK 推回，而且用 [Phase 05](./05-Phase05-單表鍵與關係邊契約.md) 的 `parse_step_pk`（`step_pk` 的反函式）而不是自己切字串：鍵是權威，即使 Phase 23 同時把它們寫成屬性也不會分岔，而形狀不對的 PK 由 `parse_step_pk` 自己丟 `ValueError`。它也是唯一要傳 `meta_only=False` 的呼叫點。`_scan_models` 的 `equals` 直接比對 raw item 的屬性字串，不先轉 model，省掉「為了篩掉九成資料而建一堆物件」。

- [x] **Step 4：補各 list 的排除條件測試後跑綠燈**

六個 list 各補一條「不符合條件不入選」：別版的 `VIEW`、別專案的 `TICKET`、`status=active` 時不回 candidate、`domain` 相同但 `adapter` 不同的 PROC 不入選。再補一條「表裡有關係邊時 list 不會爆」，證明 `meta_only` 預設值真的在擋：

```python
from training_kb.keys import feature_pk, rule_pk, ticket_pk, version_pk
from training_kb.models import AuthoringRule


def test_list_reads_ignore_relation_edges(repository) -> None:
    repository.put_meta(AuthoringRule(
        rule_id="R-007", rule="點 UI 時寫出頁面與按鈕位置", applies_when="click_ui",
        status="active", evidence=["f_12", "f_15", "f_19", "f_23", "f_27"],
        applied_to=[], derived_from="prepare-meeting@v1"))
    repository.put_edge(rule_pk("R-007"), "APPLIED_TO", version_pk("prepare-meeting@v2"))
    repository.put_edge(ticket_pk("t_881"), "ASKS_ABOUT", feature_pk("Prepare"))
    assert [item.rule_id for item in repository.list_rules()] == ["R-007"]
    assert repository.list_tickets("demo") == []
```

把 `meta_only` 的預設改成 `False` 這條就會變紅（邊沒有模型欄位，`item_to_model` 會丟 `ValidationError`），這正是它該有的訊號。另加一條 `test_raw_item_cannot_be_validated_directly`：對 `scan_entity("TICKET")[0]` 直接呼叫 `Ticket.model_validate` 會 `ValidationError`，改用 `item_to_model` 才成功——這就是 `item_to_model` 存在的理由。`list_procs` 依賴 `ProvenWorkflow.domain`／`adapter`（Phase 04 已有這兩個欄位）；若模型缺欄位就停止，回 Phase 04 補，不要在查詢層猜值。

```bash
uv run pytest tests/unit/test_repository_paging.py tests/integration -q
uv run mypy src/training_kb/repository.py
```

> **本次結果（2026-09-14）**：`_scan_models` 寫成 PEP 695 泛型（`def _scan_models[M: StrictModel]`）
> 才過得了 mypy strict，公開簽名不受影響。`list_procs` 的排除條件補了兩條（`domain` 相同但
> `adapter` 不同、`adapter` 相同但 `domain` 不同），因為只驗一個方向會漏掉「只比對其中一個欄位」
> 的實作錯誤。把 `scan_entity` 的 `meta_only` 預設改成 `False` 後，
> `test_list_reads_ignore_relation_edges` 如預期丟 `ValidationError: 7 validation errors for
> AuthoringRule`，`test_step_edges_are_scanned_with_meta_only_off` 也一起變紅。

- [x] **Step 5：提交**

```bash
git add src/training_kb/repository.py tests/unit/test_repository_paging.py tests/integration
git commit -m "feat(data): 增加六個固定清單讀取"
```

## 8. 驗收矩陣

| 路徑 | 輸入 | 預期資料結果 |
|---|---|---|
| Happy | 同版八筆回饋邊；另一版三步亂序寫入 | 八筆 `Feedback` 依 ID 升序；`get_steps` 回 1、2、3 且各有一個 `feature_id`。 |
| Failure | GSI 候選在基表沒有本體 | `PermanentError`，不安靜跳過。 |
| Failure | 直接對 raw item 呼叫 `Model.model_validate` | `ValidationError`（`extra="forbid"`）；改走 `item_to_model` 才成功。 |
| Failure | `query_by_target` 送出的參數 | 含 `IndexName="by_target"`、**不含** `ConsistentRead`；GSI 不支援一致讀取。 |
| Boundary | 第一頁空但仍有游標 | 續查到沒有游標，結果不缺。 |
| Boundary | 表內同時有別版的 `STEP` 邊 | `get_steps` 只回指定 `version_id` 的步驟。 |
| Boundary | 表內有 `APPLIED_TO`／`ASKS_ABOUT` 邊 | `list_rules`、`list_tickets` 靠 `meta_only=True` 濾掉它們，不丟 `ValidationError`。 |
| Boundary | 同 target 有 `ASKS_ABOUT` 與 `SUPERSEDES`；`page_size=1` 的十筆資料 | 只留 `REFERS_TO` + `FEEDBACK` 起點；請求多次但結果與不設 `page_size` 時相同。 |

人工驗收：開啟 moto 表，手動比對某一版的回饋筆數與 `by_target` 候選數；再把一筆邊的基表本體刪掉，確認 `list_feedback_of_version` 明確失敗。不能只看測試顯示 PASS。

> **本次結果（2026-09-14）**：在 moto 表寫入 8 筆 `REFERS_TO`、1 筆 `SUPERSEDES`、1 筆 `ASKS_ABOUT`
> 與 30 筆無關的 `STEP` 邊（表內共 48 個 item），`page_size=1`：`by_target` 候選 10 筆、欄位只有
> `['PK', 'SK', 'target']`，`list_feedback_of_version` 回 8 筆
> `['f_12', 'f_15', 'f_19', 'f_23', 'f_27', 'f_31', 'f_34', 'f_40']`；刪掉 `FEEDBACK#f_19` 的 `META`
> 之後改丟 `PermanentError: feedback edge has no base item: FEEDBACK#f_19`。
> 全部是 moto 本機結果，**不代表**真實 DynamoDB 的分頁與 GSI 一致性已驗證（見 §9 最後一列）。

## 9. 常見錯誤與停止條件

| 症狀 | 原因 | 修正／停止 |
|---|---|---|
| 結果偶爾少幾筆 | 看到空頁就 `break` | 只以 `LastEvaluatedKey` 為結束條件。 |
| 只回第一頁 | 沒把游標寫回 `ExclusiveStartKey` | 每次迴圈都更新請求參數。 |
| 直接用 GSI 結果當內容 | 忘了 `KEYS_ONLY` 只有鍵 | 逐筆回基表一致讀取。 |
| 用 `sleep` 等 GSI 追上 | 把最終一致當成延遲 | 停止；改用基表核對，設計明文禁止固定秒數。 |
| `scan_entity` 掃到別類型 | 用 PK 前綴比對代替 `entity` | 以 `entity` 屬性過濾，前綴只用於再細分。 |
| `list_rules`／`list_tickets` 丟 `ValidationError`，內容看起來像關係邊 | `scan_entity` 被傳了 `meta_only=False`，把同前綴的邊也回來了 | 六個 list 一律用預設值；只有 `get_steps` 可以傳 `meta_only=False`。 |
| `scan_entity` 回零筆但表裡明明有資料 | Phase 06 的 `put_meta` 把屬性名加了後綴，或存成類別名（`Feature`）而不是前綴 | 停止；回 Phase 06 把屬性統一成 `entity`（值＝PK 前綴，[00A](00A-共用契約與名詞.md) §3.6）。 |
| `Model.model_validate(item)` 丟 `ValidationError`，或想在 item 加 `step_count` 省掉 Scan | raw item 帶保留屬性；把方便當成可以加欄位 | 改用 `item_to_model`；不要放寬 `model_config`，也不要加模型外的欄位（步驟數權威是 S3 全文）。 |
| 把 moto PASS 說成 AWS 已驗證 | 混淆模擬與真實 | 只報本機 PASS，實表證據待 Phase 09 之後。 |

## 10. 來源與 Rule 對照

- [查詢知識圖譜.feature](../../spec/features/查詢知識圖譜.feature)
  - GPH Rule 1：「查詢某起點的關係使用該起點的 PK」→ **primary**。Task 1 Step 4 直接斷言 `query_pk` 回齊同一 PK 的全部邊。
  - GPH Rule 2：「查詢誰引用 Feature 時使用 by_target 的 target」→ **primary**。Task 2 Step 1、Step 3 斷言候選來自 `by_target`、只有鍵且排除其他關係。
  - GPH Rule 6：「Feedback Review 以 refers_to 關係反查指定版本的回饋」→ **primary**。`list_feedback_of_version` 的 happy 測試。
  - GPH Rule 3：「沿 Feature 關係邊反查不呼叫 AI」→ **相關（primary 在 [Phase 27](./27-Phase27-固定圖譜查詢.md)）**。本 Phase 只證明查詢層沒有任何 `Writer` 相依，測試以 import 邊界佐證。
  - GPH Rule 4、5、7 → **相關**，primary 驗收在 [Phase 27](./27-Phase27-固定圖譜查詢.md) 與 [Phase 28](./28-Phase28-引用Backfill與規則投影重建.md)，本 Phase 只提供底層查詢。
- 設計 §10、§9.1：六種固定查法、Query／Scan 必須讀完分頁、GSI 最終一致要以基表核對、正常遍歷不呼叫 AI；`by_target` 不加排序鍵、只投影查詢需要的鍵，完整資料回基表取得；「某篇教學有哪些版本」「某版有哪些瀏覽者」明文用基表分頁 Scan，`get_steps` 沿用同一取捨。
- [00A 共用契約與名詞](00A-共用契約與名詞.md)：§3.6 保留屬性與 `item_to_model` 的過濾規則；§6.3 `Repository` 與 `item_to_model` 的 canonical 簽名（含 `scan_entity(..., meta_only=True)`）；§3.4／§3.6「STEP 沒有 META item」與「Scan 會掃到同前綴的邊」；裁決 D-29（`item_to_model` 由本 Phase 產出）與 D-39（`get_steps` 的實作方式）。
- [DynamoDB Query 分頁](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/Query.Pagination.html)：`LastEvaluatedKey` 為空才代表讀完；有 `FilterExpression` 時一頁可能零筆卻仍帶游標。
- [DynamoDB 讀取一致性](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/HowItWorks.ReadConsistency.html)：基表可一致讀取，GSI 只有最終一致。

## 11. 完成清單

- [x] `_paged` 只以 `LastEvaluatedKey` 判斷結束，空頁不提前停。
- [x] `query_pk`、`scan_entity` 預設一致讀取；`query_by_target` 沒有一致讀取選項。
- [x] `scan_entity` 預設 `meta_only=True`，六個 list 因此自動濾掉同前綴的關係邊，且有一條「表裡有 `APPLIED_TO`／`ASKS_ABOUT` 邊時 list 不爆」的測試。
- [x] GSI 候選一律回基表核對，讀不到本體時明確失敗；`query_by_target` 的請求不含 `ConsistentRead`。
- [x] `item_to_model(item, model)` 是模組函式，有一條「直接 `model_validate` 會失敗、用它才成功」的測試。
- [x] `get_steps` 走 `scan_entity("STEP", meta_only=False)` 加版本過濾、依編號升序，`number` 與 `tutorial_version` 由 `parse_step_pk` 從 PK 推回、`feature_id` 來自邊的 `target`，且與 Phase 23 的寫入方式一致。
- [x] 六個 list 都有 happy 與排除條件測試，排序穩定，轉 model 一律經 `item_to_model` 或 `get_meta`。
- [x] `page_size` 只出現在測試，正式程式沒有寫死 `Limit`；文件沒有把 moto PASS 或 GSI 等待說成一致性已解決。
