# Phase 07：S3 物件與關係邊讀寫實作計畫

> **給實作者：** 依 checkbox 逐步執行；每個 Task 先建立失敗測試，再寫最小實作。執行時使用 `superpowers:executing-plans` 或同等逐項流程。

**目標：** 讓 `Repository` 能讀寫私有 S3 物件且同一個 key 不會被盲目覆寫，並保存 `PK=起點`、`SK=關係#終點`、`target=終點` 三者完全一致的關係邊。

**架構：** `Repository` 同時持有 DynamoDB table 與 S3 bucket 兩個 boto3 resource。「同 key 不可覆寫」交給 AWS 的條件寫入判斷，程式不先查再寫；邊的 `target` 一律由程式從 `target_pk` 導出，呼叫端不能另外傳一個不同的 target。

**技術：** Python 3.12、boto3 S3／DynamoDB resource API、moto `mock_aws`、pytest、Phase 05 的 `edge_sk`／`parse_edge_sk`／`parse_pk`。

## 全域限制

- 唯一主來源是 [Training KB 設計 §8.2、§8.3、§9.2、§9.3](../../design/training-kb.md)；前置為 [Phase 06：Repository Metadata 與實體讀寫](./06-Phase06-Repository-Metadata與實體讀寫.md)，Phase 06 未通過或 O1 未關閉時停止。
- 下一階段是 [Phase 08：分頁查詢與一致讀取基礎](./08-Phase08-分頁查詢與一致讀取基礎.md)。
- 本階段不做：不實作三種公開查詢與完整分頁（Phase 08）、不產生 Markdown 或 diff 內容（Phase 22）、不發布也不寫 `site/` 前綴（Phase 24、Phase 57）、不建立任何真實 AWS 資源（Phase 09）。
- 與本 Phase 有關的 gate：O1 必須已由 Phase 05 記錄接受或替代值才可寫 item；O2、O3 都仍未通過。單一物件的條件寫入不是跨 S3 與 DynamoDB 的發布提交，也不是永久去重，不得用本 Phase 的綠燈宣稱 publish 或重送已驗收。
- moto 通過只代表本機模擬行為；真實 S3 與 DynamoDB 的證據要等 Phase 09 資源就緒後另外保留。**本次補充（Phase 09 已完成）**：另以 ad-hoc 腳本對實際 bucket 跑過同一條路徑（412 → `ObjectAlreadyExists`、不存在的 key → `None`／`False`，key 落在 `operations/smoke-<uuid>/`，跑完刪除），輸出留在 Phase 07 報告；這只是本 Phase 兩個方法的行為核對，**不代表 O2／O3 通過**，也不是發布提交。以下程式檔均是實作時預計建立或修改；本計畫本身不代表它們已存在。

---

## 1. 你在整體流程的位置

```text
Phase 06 metadata CRUD
          |
          v
+---------+-----------------------------------------+
| [你在這裡] Phase 07                                |
|  S3 物件：put_object / get_object / object_exists  |
|  關係邊：put_edge / list_edges（共用 _paged）       |
+---------+-------------------+---------------------+
          |                   |
          v                   v
  Phase 08 分頁查詢    Phase 22/23 全文與版本寫入 -> Phase 24 發布（O3 仍未通過）
```

## 2. 完成後看得到什麼

```text
put_object("tutorials/prepare-meeting/v1.md", b"# Prepare Meeting", "text/markdown", if_none_match=True)
  第一次 -> 寫入成功
  第二次 -> ObjectAlreadyExists；bucket 內容仍是第一次那份 bytes

put_edge("STEP#prepare-meeting@v2#3", "REFERENCES", "FEATURE#Prepare", {"type": "click_ui", ...})
  -> PK = STEP#prepare-meeting@v2#3 | SK = REFERENCES#FEATURE#Prepare
     target = FEATURE#Prepare       | entity = STEP

list_edges("STEP#prepare-meeting@v2#3")
  -> 只回上面那一筆邊，不回同 PK 的 META item
```

## 3. 名詞小抄

| 名詞 | 白話意思 |
|---|---|
| `If-None-Match: *` | S3 的條件寫入標頭，意思是「這個 key 還不存在時才寫」；已存在由 AWS 回 412，不用先查再寫。 |
| `ObjectAlreadyExists` | 本 Phase 新增的錯誤類別，專指「條件寫入撞到同 key」；它是 `PermanentError` 的子類別，所以呼叫端可以用**型別**判斷，不必比對訊息字串。 |
| 關係邊（edge） | 一個獨立 item，用 `SK=關係#終點` 表示「起點透過某關係指向終點」。 |
| `target` | 邊的終點完整 PK；唯一的 `by_target` GSI 用它當反查分割鍵。 |
| 私有前綴 | `tutorials/`、`operations/`、`stepfunctions/` 等不可公開的 S3 路徑；只有 `site/` 是公開區。 |
| 保留屬性（`RESERVED_ATTRS`） | `PK`、`SK`、`target`、`entity`、`_revision`；只能由 `Repository` 自己算，呼叫端不能傳。這個常數的 owner 是 [Phase 06](06-Phase06-Repository-Metadata與實體讀寫.md)，本 Phase 直接**沿用**同一份，不另外宣告。 |

## 4. 預計檔案

| 動作 | 路徑 | 責任 |
|---|---|---|
| 修改 | `src/training_kb/errors.py` | 追加 `ObjectAlreadyExists(PermanentError)`；其餘六個錯誤類別仍屬 Phase 02。 |
| 修改 | `src/training_kb/repository.py` | 加上 bucket、三個 S3 方法、`_paged` 與兩個 edge 方法。 |
| 修改 | `tests/integration/conftest.py` | 讓 `repository` fixture 同時提供 moto 表與 moto bucket。 |
| 測試 | `tests/integration/test_repository_objects.py` | 條件寫入、讀取、重試核對與參數白名單。 |
| 測試 | `tests/integration/test_repository_edges.py` | 邊的 `target` 一致性與 `META` 隔離。 |
| ~~修改~~ 已滿足 | `pyproject.toml` | moto 測試 extra 需包含 S3。**Phase 01 已寫成 `moto[dynamodb,s3]>=5,<6`，本 Phase 不改 `pyproject.toml`／`uv.lock`**（實測 moto 5.2.3 已支援 `IfNoneMatch`）。 |

## 5. 固定介面

### Consumes

```text
Repository.__init__(table)                     # Phase 06；本 Phase 增加第二個參數 bucket
DynamoScalar / DynamoValue / DynamoItem        # Phase 06 的三個型別別名
META: str                                      # Phase 05
RESERVED_ATTRS: frozenset[str]                 # Phase 06；沿用同一份，不重新宣告
edge_sk(relation, target_pk) -> str | parse_edge_sk(value) -> (relation, target_pk)
parse_pk(value) -> (kind, identifier)
PermanentError / TransientError                # Phase 02（errors.py 由本 Phase 追加一個子類別）
```

### Produces

```python
class ObjectAlreadyExists(PermanentError): ...   # errors.py；if_none_match 撞到同 key（S3 412）

EdgeAttrs = Mapping[str, DynamoValue] | None


class Repository:
    def __init__(self, table: object, bucket: object | None = None) -> None: ...
    def put_object(self, key: str, body: bytes, content_type: str, *, if_none_match: bool) -> None: ...
    def get_object(self, key: str) -> bytes | None: ...
    def object_exists(self, key: str) -> bool: ...
    def put_edge(self, pk: str, relation: str, target_pk: str, attrs: EdgeAttrs = None) -> None: ...
    def list_edges(self, pk: str, relation: str | None = None) -> list[DynamoItem]: ...
```

`put_object` 在 `if_none_match=True` 且物件已存在時丟 `ObjectAlreadyExists`（S3 412），併發衝突（409）丟 `TransientError`；`get_object` 對不存在的 key 回 `None` 而不是丟例外。`bucket` 預設 `None`，所以 Phase 06 既有的 `Repository(table)` 呼叫不受影響；沒有 bucket 卻呼叫 S3 方法時丟 `PermanentError`。Phase 08 會在同一個 `__init__` 再加 keyword-only 的 `page_size`，兩次加參數後的完整簽名是 `Repository(table, bucket=None, *, page_size=None)`。本 Phase 另外產出私有的 `Repository._paged(operation, **arguments)`：反覆呼叫同一個 boto3 操作直到回應沒有 `LastEvaluatedKey`；本 Phase 只讓 `list_edges` 用它，Phase 08 會擴充它（加 `Limit`）並在三個公開查詢上重用。

## 6. 設計細節

S3 條件寫入的固定順序是「先送出、再依 AWS 回應分類」，不是「先查存在再寫」。先查再寫會在兩個請求之間留下空窗，兩個 Lambda 可能同時判斷為不存在。

```text
put_object(..., if_none_match=True) -> PutObject + IfNoneMatch="*"
   |
   +-- 200 OK --------------------------> 寫入完成
   +-- 412 PreconditionFailed ----------> ObjectAlreadyExists（PermanentError 子類別）
   |        |
   |        +-> 呼叫端 except ObjectAlreadyExists，再 get_object 比對 bytes
   |              相同 -> 視為本次已完成，不重寫
   |              不同 -> 停止，回報衝突並保留兩份證據
   +-- 409 ConditionalRequestConflict --> TransientError，交 ASL Retry
```

為什麼要為 412 另開一個類別：Phase 22 的 `put_private_artifact` 要區分「同一次操作重送」與「真正的內容衝突」，只有 412 屬於前者。如果全部都丟 `PermanentError`，呼叫端只能比對訊息字串，訊息一改就壞。409 是併發刪除造成的暫時衝突，官方文件說明可以重試，所以不在這裡自行迴圈，避免與 Phase 29 的單層 Task Retry 相乘。關係邊的一致性則有兩個檢查點，缺一不可：

```text
寫入：target 只能由 target_pk 導出
      edge_sk(relation, target_pk) -> "REFERENCES#FEATURE#Prepare"
      attrs 含保留屬性 -> PermanentError
讀取：list_edges 逐筆驗證
      parse_edge_sk(item["SK"])[1] == item["target"] -> 保留
      不相等 -> PermanentError；SK == META -> 跳過
```

讀取時也檢查，是因為 backfill（Phase 28）與未來的維護腳本也會寫邊；只在寫入端檢查無法發現已經寫壞的資料。`entity` 這個屬性名是全套共用的（[00A](00A-共用契約與名詞.md) §3.6），值等於 PK 前綴；開始 Task 2 前先確認 Phase 06 的 `put_meta`／`get_meta` 用的也是 `entity` 這個名字、存的也是前綴而不是類別名（`Feature`），否則 Phase 08 的 `scan_entity` 會查不到 metadata item，請回 Phase 06 對齊，不要兩種名稱並存。

## 7. TDD Tasks

### Task 1：S3 物件的條件寫入與讀取

- [x] **Step 1：建立失敗測試**

```python
import pytest

from training_kb.errors import ObjectAlreadyExists, PermanentError


def test_put_object_refuses_to_overwrite_same_key(repository) -> None:
    key = "tutorials/prepare-meeting/v1.md"
    repository.put_object(key, b"# Prepare Meeting", "text/markdown", if_none_match=True)
    with pytest.raises(ObjectAlreadyExists, match="already exists"):
        repository.put_object(key, b"# changed", "text/markdown", if_none_match=True)
    assert issubclass(ObjectAlreadyExists, PermanentError)
    assert repository.get_object(key) == b"# Prepare Meeting"
    assert repository.object_exists(key) is True
    assert repository.get_object("tutorials/prepare-meeting/v2.md") is None
    assert repository.object_exists("tutorials/prepare-meeting/v2.md") is False
```

- [x] **Step 2：執行並確認紅燈**

```bash
uv run pytest tests/integration/test_repository_objects.py -q
```

預期：FAIL，訊號包含 `cannot import name 'ObjectAlreadyExists' from 'training_kb.errors'`；補上錯誤類別後改成 `'Repository' object has no attribute 'put_object'`。若改成 fixture 找不到 bucket，先補 conftest 再回到這一步。

- [x] **Step 3：建立最小實作**

```python
# src/training_kb/errors.py：接在 Phase 02 的六個類別之後
class ObjectAlreadyExists(PermanentError):
    """條件寫入撞到同一個 key（S3 412）。"""


# src/training_kb/repository.py；__init__ 多存一行 self._bucket = bucket
from botocore.exceptions import ClientError

from training_kb.errors import ObjectAlreadyExists, PermanentError, TransientError

MISSING_CODES = frozenset({"NoSuchKey", "404"})

def put_object(self, key: str, body: bytes, content_type: str, *, if_none_match: bool) -> None:
    arguments: dict[str, object] = {"Key": key, "Body": body, "ContentType": content_type}
    if if_none_match:
        arguments["IfNoneMatch"] = "*"
    try:
        self._bucket.put_object(**arguments)
    except ClientError as error:
        code = error.response["Error"]["Code"]
        if code == "PreconditionFailed":
            raise ObjectAlreadyExists(f"object already exists: {key}") from error
        if code == "ConditionalRequestConflict":
            raise TransientError(f"conditional write conflicted: {key}") from error
        raise

def get_object(self, key: str) -> bytes | None:
    try:
        return self._bucket.Object(key).get()["Body"].read()
    except ClientError as error:
        if error.response["Error"]["Code"] in MISSING_CODES:
            return None
        raise

def object_exists(self, key: str) -> bool:
    try:
        self._bucket.Object(key).load()
    except ClientError as error:
        if error.response["Error"]["Code"] in MISSING_CODES:
            return False
        raise
    return True
```

`object_exists` 用 `Object(key).load()` 只取 metadata，不下載 body。三個方法只接住「不存在」與兩個條件寫入碼，其他 `ClientError` 一律往外丟，不吞錯。`PermanentError` 同時給 Task 2 的 `put_edge` 與 Task 3 的 `_require_bucket` 使用，所以 import 一次寫齊。貼進 `Repository` 類別時記得加回類別內縮排與 PEP 8 的空行。

- [x] **Step 4：跑完整檔案確認綠燈，並記錄器材能力**

Step 1 的第二次 `put_object` 就是器材能力探針。它若沒有 FAIL，代表安裝的 moto 還沒實作 `IfNoneMatch`（getmoto/moto#8091）。正確處理是升級 moto 並把版本寫進測試報告；**不可**刪掉斷言，也不可改成「先 `object_exists` 再寫」的假條件。無法升級時把本 Task 標記 `BLOCKED`，不往 Phase 08 前進。

> **本次結果（2026-09-14）**：moto **5.2.3**，第二次 `put_object` 回 `PreconditionFailed`／HTTP 412，物件 bytes 未變 → 探針 PASS，不需升級。

```bash
uv run pytest tests/integration/test_repository_objects.py -q
```

- [x] **Step 5：提交**

```bash
git add src/training_kb/errors.py src/training_kb/repository.py \
        tests/integration/conftest.py tests/integration/test_repository_objects.py
git commit -m "feat(data): 增加 S3 物件條件寫入"
```

### Task 2：關係邊的 target 一致性

- [x] **Step 1：建立失敗測試**

```python
from training_kb.keys import feature_pk, step_pk


def test_put_edge_writes_target_equal_to_sk_endpoint(repository) -> None:
    pk = step_pk("prepare-meeting@v2", 3)
    attrs = {"type": "click_ui", "text": "在右上角選擇 Prepare"}
    repository.put_edge(pk, "REFERENCES", feature_pk("Prepare"), attrs)
    edges = repository.list_edges(pk)
    assert len(edges) == 1
    assert edges[0]["SK"] == "REFERENCES#FEATURE#Prepare"
    assert edges[0]["target"] == "FEATURE#Prepare"
    assert edges[0]["entity"] == "STEP"
    assert edges[0]["text"] == "在右上角選擇 Prepare"
```

- [x] **Step 2：執行並確認紅燈**

```bash
uv run pytest tests/integration/test_repository_edges.py -q
```

預期：FAIL，訊號包含 `'Repository' object has no attribute 'put_edge'`。

- [x] **Step 3：建立最小實作（`_paged` 與兩個方法）**

`RESERVED_ATTRS` 已經在 Phase 06 的 `repository.py` 裡，本 Phase 是在同一支檔案裡繼續加方法，所以直接沿用同一份常數，**不要**再宣告一次（兩份定義早晚會分岔）。

```python
from boto3.dynamodb.conditions import Key

from training_kb.keys import META, edge_sk, parse_edge_sk, parse_pk

def put_edge(self, pk, relation, target_pk, attrs=None):
    extra = dict(attrs or {})
    forbidden = sorted(RESERVED_ATTRS.intersection(extra))
    if forbidden:
        raise PermanentError(f"edge attributes are reserved: {forbidden}")
    sort_key = edge_sk(relation, target_pk)
    if parse_edge_sk(sort_key) != (relation, target_pk):
        raise PermanentError(f"edge sort key does not round-trip: {sort_key}")
    self._table.put_item(
        Item={"PK": pk, "SK": sort_key, "target": target_pk, "entity": parse_pk(pk)[0], **extra}
    )

def _paged(self, operation, **arguments):
    items = []
    while True:
        response = operation(**arguments)
        items.extend(response.get("Items", []))
        cursor = response.get("LastEvaluatedKey")
        if not cursor:
            return items
        arguments["ExclusiveStartKey"] = cursor

def list_edges(self, pk, relation=None):
    condition = Key("PK").eq(pk)
    if relation is not None:
        condition = condition & Key("SK").begins_with(f"{relation}#")
    edges = []
    for item in self._paged(
        self._table.query, KeyConditionExpression=condition, ConsistentRead=True
    ):
        sort_key = str(item["SK"])
        if sort_key == META:
            continue
        if parse_edge_sk(sort_key)[1] != item.get("target"):
            raise PermanentError(f"edge target does not match sort key: {item['PK']} {sort_key}")
        edges.append(item)
    return edges
```

上面的片段是未註記型別的示意碼，實作時有兩處必須補齊才過 mypy strict：`extra` 的值要走與 `put_meta_item` 同一套 Decimal codec（`_encode`），整套才只有一個地方決定 `float` 怎麼寫進表；`list_edges` 的 `condition` 要標成 `ConditionBase`（`&` 之後型別從 `Equals` 變 `And`），錯誤訊息裡的 `item['PK']` 要包 `str(...)`（`DynamoValue` 含 `bytes`）。

`entity` 由 `parse_pk(pk)[0]` 導出，值等於 PK 前綴（`STEP`、`VERSION`、`RULE`…），Phase 08 的 `scan_entity` 就是靠它篩選。`_paged` 是私有的最小分頁迴圈：反覆呼叫直到回應沒有 `LastEvaluatedKey`；本 Phase 只讓 `list_edges` 使用它，三個公開查詢與空頁邊界的完整驗收在 Phase 08。

- [x] **Step 4：補保留屬性、`META` 隔離與 relation 篩選測試後跑綠燈**

`attrs` 分別帶 `target`、`SK`、`entity` 三種保留屬性時都要 `PermanentError` 且表內沒有新 item；同一 PK 先 `put_meta` 再 `put_edge` 時 `list_edges` 只能回邊；`list_edges(pk, "SUPERSEDES")` 不回 `REFERENCES` 的邊。再補一條讀取端的反向檢查（驗收矩陣的 Failure 列、00B `VER` Rule 10 要求的雙向檢查）：直接用 `table.put_item` 寫一筆 `target` 與 `SK` 終點不符的舊資料，`list_edges` 要丟 `PermanentError` 且不自動修正。

```bash
uv run pytest tests/integration/test_repository_edges.py -q
uv run mypy src/training_kb/repository.py
```

- [x] **Step 5：提交**

```bash
git add src/training_kb/repository.py tests/integration/test_repository_edges.py
git commit -m "feat(data): 保存一致的關係邊"
```

### Task 3：鎖定送出的參數，並在缺 bucket 時明確失敗

- [x] **Step 1：建立失敗測試**

```python
from types import SimpleNamespace

import pytest

from training_kb.errors import PermanentError
from training_kb.repository import Repository


def test_put_object_sends_only_documented_parameters() -> None:
    calls: list[dict[str, object]] = []
    bucket = SimpleNamespace(put_object=lambda **kwargs: calls.append(kwargs))
    repository = Repository(table=None, bucket=bucket)
    repository.put_object("operations/op-1/input.json", b"{}", "application/json", if_none_match=True)
    assert calls == [{
        "Key": "operations/op-1/input.json", "Body": b"{}",
        "ContentType": "application/json", "IfNoneMatch": "*",
    }]


def test_s3_methods_without_bucket_fail_clearly() -> None:
    repository = Repository(table=None)
    key = "tutorials/prepare-meeting/v1.md"
    with pytest.raises(PermanentError, match="bucket"):
        repository.put_object(key, b"x", "text/markdown", if_none_match=True)
    with pytest.raises(PermanentError, match="bucket"):
        repository.get_object(key)
    with pytest.raises(PermanentError, match="bucket"):
        repository.object_exists(key)
```

第一條就是「沒有 `ACL`、沒有 `public-read`、沒有多餘欄位」的固定證據；第二條讓「忘了給 bucket」變成看得懂的 `PermanentError`，而不是 `AttributeError`。

- [x] **Step 2：執行並確認紅燈**

```bash
uv run pytest tests/integration/test_repository_objects.py -q -k without_bucket
```

預期：FAIL，訊號包含 `AttributeError: 'NoneType' object has no attribute 'put_object'`。

- [x] **Step 3：建立最小實作**

```python
def _require_bucket(self):
    if self._bucket is None:
        raise PermanentError("repository was created without an S3 bucket")
    return self._bucket
```

把 Task 1 的三個方法內所有 `self._bucket` 改成 `self._require_bucket()`；其餘程式不動。

- [x] **Step 4：補重試核對測試後跑綠燈**

再加一條 `test_identical_retry_is_treated_as_done`：同一個 `operations/op-ticket-t_881/input.json` 寫兩次相同 bytes，第二次用 `except ObjectAlreadyExists`（**型別**，不是訊息字串）接住，再用 `get_object` 比對 bytes，確認內容一致後把本次視為已完成。這條就是 Phase 22 `put_private_artifact` 的最小原型。同時把 §8 的人工驗收寫成可執行斷言（`test_every_written_key_stays_in_a_private_prefix`）：列出 moto bucket 的所有 key，確認全部落在私有前綴且沒有任何 `site/`。另補一條用假 bucket 觸發 409／`AccessDenied` 的測試，鎖住 「409 → `TransientError`、其餘 `ClientError` 不吞」這條對應（§11 完成清單第 2 項）。

```bash
uv run pytest tests/integration -q
uv run ruff check src/training_kb/errors.py src/training_kb/repository.py tests/integration
```

- [x] **Step 5：提交**

```bash
git add src/training_kb/repository.py tests/integration/test_repository_objects.py
git commit -m "test(data): 鎖定物件寫入參數"
```

## 8. 驗收矩陣

| 路徑 | 輸入 | 預期資料結果 |
|---|---|---|
| Happy | 新 key + `if_none_match=True` | 寫入成功，`get_object` 回同一份 bytes。 |
| Happy | `put_edge` 後 `list_edges` | 一筆邊，`SK` 終點與 `target` 相同。 |
| Failure | 同 key 再寫一次 | `ObjectAlreadyExists`（且是 `PermanentError` 子類別）；既有物件 byte 不變。 |
| Failure | `attrs` 帶 `target` 或 `SK` | `PermanentError`；表內沒有新 item。 |
| Failure | 讀到 `target` 與 `SK` 不符的舊資料 | `PermanentError`，不自動修正。 |
| Failure | `Repository(table)` 沒有 bucket 就呼叫三個 S3 方法 | `PermanentError`，訊息說明缺少 bucket。 |
| Boundary | 不存在的 key | `get_object` 回 `None`、`object_exists` 回 `False`；同 PK 有 `META` 時 `list_edges` 只回邊。 |

人工驗收：在 moto bucket 列出所有 key，確認全部落在 `tutorials/`、`operations/`、`stepfunctions/` 前綴，沒有任何 key 落在 `site/`；再讀一筆 raw DynamoDB item，確認 `target` 存在且等於 `SK` 的終點。不能只看測試顯示 PASS。

## 9. 常見錯誤與停止條件

| 症狀 | 原因 | 修正／停止 |
|---|---|---|
| 同 key 第二次寫入成功 | 沒送 `IfNoneMatch`，或 moto 版本太舊 | 先跑能力探針；升級 moto，不改成先查再寫。 |
| 先 `object_exists` 再 `put_object` | 想避開例外 | 停止，這是有空窗的假條件寫入。 |
| `target` 與 `SK` 終點不同 | 呼叫端自帶 `target` | 拒絕保留屬性；`target` 只能由 `target_pk` 導出。 |
| `list_edges` 回到 `META` item | 用 PK 查詢卻沒排除 metadata | 過濾 `SK == META`。 |
| 409 被當永久失敗 | 沒有分辨 412 與 409 | 409 轉 `TransientError`，交 ASL Retry。 |
| 呼叫端用 `match="already exists"` 判斷重送 | 沒有用 `ObjectAlreadyExists` 型別 | 改 `except ObjectAlreadyExists`；訊息字串不是契約。 |
| 把 moto 綠燈說成「S3 已驗收」 | 混淆模擬與真實 | 只報本機 integration PASS；AWS 證據待 Phase 09。 |

## 10. 來源與 Rule 對照

- [建立教學版本.feature](../../spec/features/建立教學版本.feature)
  - VER Rule 10：「references 邊的 target 等於 SK 中的關係終點」→ **primary**。Task 2 Step 1 的 `target` 斷言，加上 Step 3、Step 4 的寫入與讀取雙向檢查。
  - VER Rule 8：「建立 TutorialStep 時保存 references Feature 邊」→ **相關（primary 在 [Phase 23](./23-Phase23-未發布版本與關係完整寫入.md)）**。本 Phase 只提供通用的邊讀寫；「建立 TutorialStep 時」這個情境由 Phase 23 的 `create_version` 斷言。Task 2 Step 1 的測試保留。
- [查詢知識圖譜.feature](../../spec/features/查詢知識圖譜.feature)
  - GPH Rule 1：「查詢某起點的關係使用該起點的 PK」→ **相關（primary 在 [Phase 08](./08-Phase08-分頁查詢與一致讀取基礎.md)）**。本 Phase 只提供 `list_edges` 的最小證據。
- 設計 §8.2、§8.3：S3 已寫入但版本或關係未完成時保留不可公開的產物；同 key 已存在時核對是否為同一份產物，而非盲目重寫。
- 設計 §9.2、§9.3：`PK=起點`、`SK=關係#終點`、`target=終點` 的通用格式；`tutorials/`、`operations/`、`stepfunctions/` 是私有路徑，只有 `site/` 公開。
- [00A 共用契約與名詞](00A-共用契約與名詞.md)：§3.6 保留屬性（`RESERVED_ATTRS` 的 owner 是 Phase 06，本 Phase 沿用）與 `entity` 的值等於 PK 前綴；§4.1 錯誤類別表（`ObjectAlreadyExists` 由本 Phase 追加到 `errors.py`）；§6.3 `Repository` 的 canonical 簽名；裁決 D-30。
- [S3 條件寫入](https://docs.aws.amazon.com/AmazonS3/latest/userguide/conditional-writes.html)：`If-None-Match` 期望值為 `*`，已存在回 `412 Precondition Failed`，併發刪除回 `409 Conflict` 且可重試；[boto3 put_object](https://docs.aws.amazon.com/boto3/latest/reference/services/s3/client/put_object.html) 的參數名稱為 `IfNoneMatch`、`ContentType`。
- [moto issue #8091](https://github.com/getmoto/moto/issues/8091)：`IfNoneMatch` 支援由 PR #8109 加入，舊版不會擋下第二次寫入；[moto 入門](https://docs.getmoto.org/en/latest/docs/getting_started.html) 是 `mock_aws` 與假憑證 fixture 的用法。

## 11. 完成清單

- [x] `Repository(table)` 舊呼叫仍可用，`bucket` 只是可選第二個參數；沒有 bucket 時三個 S3 方法丟 `PermanentError`。
- [x] `errors.py` 有 `ObjectAlreadyExists(PermanentError)`，且 `put_object` 的 412 對應它、409 對應 `TransientError`。
- [x] 至少一條測試用 `except ObjectAlreadyExists` 的**型別**判斷重送，沒有任何呼叫端比對訊息字串。
- [x] moto 能力探針已執行並記錄 moto 版本。
- [x] `put_edge` 拒絕全部保留屬性，`target` 一律由 `target_pk` 導出，`entity` 等於 PK 前綴。
- [x] `list_edges` 經 `_paged` 讀完分頁、逐筆驗證 `SK` 終點與 `target`，並排除 `META`；測試中所有 S3 key 都在私有前綴，沒有任何 `site/` 寫入。
- [x] 文件與提交訊息沒有把 moto PASS 說成 AWS 或 O3 已通過。
