# Phase 06 Repository Metadata 與實體讀寫 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立九個 metadata 實體共用的序列化與基本 CRUD，以條件寫入阻止同鍵靜默覆蓋，並提供 `expected_revision` 的唯一取值來源。

**Architecture:** `Repository` 隱藏 DynamoDB 的 `PK`、`SK`、`entity` 與 `_revision`，領域模型不感知物理欄位。建立使用 `attribute_not_exists`，更新使用 revision compare-and-swap；本 Phase 先用 moto 驗證資料形狀，實體 AWS 表的 smoke 另外留證。

**Tech Stack:** Python 3.12、boto3 DynamoDB resource API、Pydantic v2、moto、pytest。

## 文件定位

- **讀者：** 需要儲存領域實體，但不應手寫 DynamoDB key 的工程師。
- **唯一主來源：** [設計 §2 與 §9.1](../../design/training-kb.md#s9)。名稱、簽名與保留屬性以 [00A 共用契約與名詞](00A-共用契約與名詞.md) 第 3.6、6.3 節為準。
- **前置 Phase：** [Phase 05](05-Phase05-單表鍵與關係邊契約.md) 的 O1 狀態、`META` 與 key builders。
- **上一份：** [Phase 05](05-Phase05-單表鍵與關係邊契約.md)。**下一份：** [Phase 07 S3 物件與關係邊讀寫](07-Phase07-S3物件與關係邊讀寫.md)。
- **本階段不做：** 不走訪關係邊、不寫 `TutorialStep`（它是邊，Phase 07／23 負責）、不存 S3 全文、不做分頁查詢（Phase 08）、不把 moto PASS 當成實體 AWS 行為證據。
- **與本 Phase 有關的 gate：** O1 必須已由 Phase 05 記錄 `Status: accepted` 或經核定的替代值，本 Phase 才能寫 item；否則寫「O1 尚未核定，`META` 仍是建議值，不得宣稱物理鍵契約已定案。」並停止。revision compare-and-swap **不是** O2：它只擋 stale write，不證明接受順序、不證明永久去重，O2 由 Phase 10／11 用真實 DynamoDB 驗證。O3 不在本 Phase 範圍。
- 以下程式檔均是實作時預計建立或修改；本計畫本身不代表它們已存在。

## 你在整體流程的位置

```text
Phase 04 十實體模型 + Phase 05 keys.py
              |
              v
+-------------+----------------------------+
| [你在這裡] Phase 06 Repository metadata  |
|  put_meta / get_meta / update_meta       |
|  revision_of / 四個具名 getter           |
+---+--------------------------+-----------+
    |                          |
    v                          v
Phase 07 邊與 S3 -> Phase 08   Phase 10 OPS# -> Phase 20 建版
```

**compare-and-swap** 意思是「只有目前 revision 符合我剛剛讀到的值才更新」。它能發現並行修改，但不能代替 Phase 10–11 的接受順序。

## 完成後看得到什麼

輸入 `Feature(feature_id="Prepare", name="Prepare", aliases=[], first_seen=...)`，`put_meta` 建立一筆 item；`get_feature("Prepare")` 回傳與原物件相等的 model。用相同鍵再建立不同內容時，第二次必須失敗，不會把第一筆蓋掉。

```text
put_meta(Feature(feature_id="Prepare", ...)) 寫出的 item
+-------------------------------------------+
| PK        = FEATURE#Prepare               |  <- keys.feature_pk
| SK        = META                          |  <- O1 決定值
| entity    = FEATURE                       |  <- parse_pk(PK)[0]
| _revision = 1                             |  <- 樂觀鎖
| feature_id / name / aliases / first_seen  |  <- 模型欄位，沒有第三類屬性
+-------------------------------------------+
   +-> get_meta(pk, Feature) -- 去掉 RESERVED_ATTRS --> Feature.model_validate(payload)
   +-> revision_of(pk) -> 1 -> update_meta(pk, {"name": ...}, expected_revision=1) -> 2
```

## 名詞小抄

| 名詞 | 白話意思 |
|---|---|
| metadata item | 實體本身那一筆 item，sort key 固定是 O1 選定的 `META`；`TutorialStep` 沒有這種 item。 |
| 保留屬性（`RESERVED_ATTRS`） | `PK`、`SK`、`target`、`entity`、`_revision`；只能由 `Repository` 自己算，呼叫端不能傳、也不能更新。 |
| `entity` 屬性 | item 上的類型標記，值等於 PK 前綴（`FEATURE`、`TICKET`…）；Phase 08 的 `scan_entity` 靠它篩選。 |
| `_revision` | 樂觀鎖版本號，每次成功寫入加 1；`get_meta` 會濾掉它，所以領域模型身上沒有它。 |
| 條件寫入 | 讓 AWS 在寫入當下判斷條件，不是「先查再寫」；先查再寫會在兩個請求之間留下空窗。 |
| `Decimal` | Python 的十進位數字型別；DynamoDB 只收它，不收 `float`。moto 是本機模擬 AWS 的測試套件，它的綠燈不等於真實 AWS 的證據。 |

## 預計新增／修改的檔案

以下是實作時預計建立或修改，目前不代表檔案存在：

| 動作 | 路徑 | 責任 |
|---|---|---|
| （不動） | `pyproject.toml` | boto3、`moto[dynamodb,s3]`、`boto3-stubs` 與 `[tool.pytest.ini_options]` 的 `aws` marker、`tests/conftest.py` 的自動跳過**都已由 Phase 01 備妥**；實作時逐項確認後不做任何修改（COMMON.md：不得改 `pyproject.toml`／`uv.lock`）。 |
| 建立 | `src/training_kb/repository.py` | `RESERVED_ATTRS`、`Repository` 與 metadata CRUD、`revision_of`、四個具名 getter；另含 `item_to_model` 與 `put_meta_item`／`get_meta_item`（見「實作後修訂」第 6 點）。 |
| 建立 | `tests/integration/conftest.py` | moto 表與 `Repository` 兩個 fixture。 |
| 建立 | `tests/integration/test_repository_meta.py` | round-trip、item 形狀、Decimal codec、條件建立與 revision 衝突。 |
| 建立 | `tests/integration/test_repository_meta_smoke.py` | 標 `@pytest.mark.aws` 的實表 smoke，預設不執行。 |

## 固定介面

### Consumes

```text
Entity = Tutorial | TutorialVersion | TutorialStep | Feature | Ticket | Release
       | Feedback | TutorialView | AuthoringRule | ProvenWorkflow    # Phase 04
StrictModel                                                          # Phase 03
META / 十個 PK builder / parse_pk                                    # Phase 05
CoordinationError / PermanentError                                   # Phase 02
```

O1 狀態必須已明確接受或有經核定替代值，才可執行本 Phase 的任何寫入。

### Produces

```python
type DynamoScalar = str | int | float | bool | None | bytes
type DynamoValue = DynamoScalar | list[DynamoValue] | dict[str, DynamoValue]
type DynamoItem = dict[str, DynamoValue]
T = TypeVar("T", bound=StrictModel)

RESERVED_ATTRS = frozenset({"PK", "SK", "target", "entity", "_revision"})


class Repository:
    def __init__(self, table: object) -> None: ...
    def put_meta(self, entity: Entity, *, create_only: bool = True) -> None: ...
    def get_meta(self, pk: str, model: type[T], *, consistent: bool = True) -> T | None: ...
    def update_meta(
        self, pk: str, changes: Mapping[str, DynamoValue], *, expected_revision: int
    ) -> int: ...
    def revision_of(self, pk: str) -> int: ...
    def get_tutorial(self, slug: str) -> Tutorial | None: ...
    def get_version(self, version_id: str) -> TutorialVersion | None: ...
    def get_feature(self, feature_id: str) -> Feature | None: ...
    def get_proc(self, signature: str) -> ProvenWorkflow | None: ...
    def put_meta_item(self, pk: str, attributes: Mapping[str, DynamoValue], *,
                      create_only: bool = True) -> bool: ...          # 見實作後修訂第 6 點
    def get_meta_item(self, pk: str) -> DynamoItem | None: ...        # 見實作後修訂第 6 點


def item_to_model[T: StrictModel](item: DynamoItem, model: type[T]) -> T: ...  # 模組函式
```

- **`RESERVED_ATTRS` 在這裡建立。** `repository.py` 的 owner 是本 Phase（[00A 第 3.2 節](00A-共用契約與名詞.md)），而 `get_meta` 一開始就要用它過濾。`target` 只有 Phase 07 的關係邊會用到，但一起列進來，讓整套只有一份定義；[Phase 07](07-Phase07-S3物件與關係邊讀寫.md) 重列的是同名同值的常數，實作時不要再宣告第二次。
- **`__init__` 之後會被加參數。** [Phase 07](07-Phase07-S3物件與關係邊讀寫.md) 追加 `bucket: object | None = None`，[Phase 08](08-Phase08-分頁查詢與一致讀取基礎.md) 追加 keyword-only 的 `page_size: int | None = None`，最終形狀就是 00A 第 6.3 節的 `__init__(self, table, bucket=None, *, page_size=None)`。兩個新參數都有預設值，所以本 Phase 寫下的 `Repository(table)` 在 Phase 07、08 之後仍然成立。
- **`revision_of` 是 `expected_revision` 的唯一取值來源。** `get_meta` 把 `_revision` 濾掉了，領域模型身上沒有它；沒有這個方法，`update_meta` 就沒有合法的取值方式。Phase 26、28、49–52、55 一律呼叫它，不得改用 `query_pk(...)["revision"]` 這類自己挖 item 的寫法。

`get_steps`、list 族群與圖譜查詢在 Phase 08／27 增加，不改動這裡的 metadata 介面。

## 設計細節

九個實體有 metadata item，`TutorialStep` 沒有：設計 §9.1 讓同一筆 edge item 同時表達「第幾步」與「引用哪個 Feature」，所以 `put_meta(TutorialStep(...))` 必須明確拒絕，而不是寫出一筆 `SK=META` 的假步驟。

```text
create_only=True                          create_only=False（Phase 38 回填向量）
  ConditionExpression                       先 revision_of(pk)，新值 = 舊值 + 1
  = attribute_not_exists(PK)                ConditionExpression = #revision = :current
        |                                          |
   已存在 -> ConditionalCheckFailed           期間被改過 -> ConditionalCheckFailed
        +--------> CoordinationError <------------+
            （不是 TransientError，呼叫端不得自動重試）
```

覆寫路徑仍帶條件、而且把 `_revision` 往上加，不會重設成 1 讓舊的持有者誤以為自己是最新——這正是本 Phase 的停止點「衝突寫入會靜默覆蓋即停」。型別轉換只有一個入口：`model_dump(mode="json")` 之後 `float` 一律換成 `Decimal(str(value))`，讀回來再換回 `int`／`float`；真正會用到的是 `Ticket.embedding` 的 1024 個值，但 codec 必須寫成遞迴，因為 list 與 map 都可能帶數字。

## Task 1：測試器材與 metadata round-trip

**Files:** `pyproject.toml`、`tests/integration/conftest.py`、`tests/integration/test_repository_meta.py`、`src/training_kb/repository.py`。

**Interfaces:** Consumes Phase 04 models 與 Phase 05 keys；Produces `RESERVED_ATTRS`、`Repository.__init__`、`put_meta`、`get_meta`、四個具名 getter。

- [x] **Step 1：建立失敗測試（含完整 fixture，不使用未定義 helper）**

`tests/integration/conftest.py`：

```python
from collections.abc import Iterator

import boto3
import pytest
from moto import mock_aws

from training_kb.repository import Repository


@pytest.fixture
def table() -> Iterator[object]:
    with mock_aws():
        dynamodb = boto3.resource("dynamodb", region_name="us-west-2")
        created = dynamodb.create_table(
            TableName="training_kb",
            KeySchema=[{"AttributeName": "PK", "KeyType": "HASH"},
                       {"AttributeName": "SK", "KeyType": "RANGE"}],
            AttributeDefinitions=[{"AttributeName": "PK", "AttributeType": "S"},
                                  {"AttributeName": "SK", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        created.wait_until_exists()
        yield created


@pytest.fixture
def repository(table: object) -> Repository:
    return Repository(table)
```

`by_target` GSI 由 [Phase 08](08-Phase08-分頁查詢與一致讀取基礎.md) 加在同一支 `conftest.py`，bucket 由 [Phase 07](07-Phase07-S3物件與關係邊讀寫.md) 加；本 Phase 的 metadata 讀寫不經 GSI，所以先不建。

`tests/integration/test_repository_meta.py`：

```python
from datetime import UTC, datetime

import pytest

from training_kb.errors import PermanentError
from training_kb.models import Feature, Ticket, TutorialStep
from training_kb.repository import RESERVED_ATTRS


def feature(name: str = "Prepare") -> Feature:
    return Feature(feature_id="Prepare", name=name, aliases=[],
                   first_seen=datetime(2026, 8, 1, tzinfo=UTC))


def test_feature_round_trip_and_item_shape(repository, table) -> None:
    repository.put_meta(feature())
    assert repository.get_feature("Prepare") == feature()
    assert repository.get_feature("Missing") is None
    item = table.get_item(Key={"PK": "FEATURE#Prepare", "SK": "META"},
                          ConsistentRead=True)["Item"]
    assert item["entity"] == "FEATURE"
    assert int(item["_revision"]) == 1
    assert set(item) - RESERVED_ATTRS == {"feature_id", "name", "aliases", "first_seen"}


def test_embedding_survives_the_decimal_codec(repository) -> None:
    ticket = Ticket(id="t_881", source="email", text="找不到按鈕", author="u_01",
                    ts=datetime(2026, 8, 3, 10, tzinfo=UTC), project_id="demo",
                    feature_ids=[], embedding=[0.1, -0.25] + [0.0] * 1022)
    repository.put_meta(ticket)
    assert repository.get_meta("TICKET#t_881", Ticket) == ticket


def test_tutorial_step_has_no_metadata_item(repository) -> None:
    step = TutorialStep(tutorial_version="prepare-meeting@v2", number=3,
                        type="click_ui", text="按下開始", feature_id="Prepare")
    with pytest.raises(PermanentError, match="put_edge"):
        repository.put_meta(step)
```

- [x] **Step 2：執行並確認紅燈**

```bash
uv run pytest tests/integration/test_repository_meta.py -q
```

（本專案把 moto 與 boto3-stubs 放在 `[dependency-groups] dev`，不是 `optional-dependencies`；`uv run` 會自動同步 dev group，原本寫的 `uv sync --all-extras` 沒有對應的 extras，已刪除。）

預期：FAIL，訊號是 `ModuleNotFoundError: No module named 'training_kb.repository'`（收集 `conftest.py` 時就出現）。若訊號變成「找不到 fixture」或「讀不到 AWS credentials」，代表 `conftest.py` 或 `mock_aws` 沒放對，先修好再回到這一步。

- [x] **Step 3：建立最小實作**

```python
from decimal import Decimal
from typing import Any, TypeVar

from botocore.exceptions import ClientError

from training_kb.errors import CoordinationError, PermanentError
from training_kb.keys import (META, feature_pk, feedback_pk, parse_pk, proc_pk,
                              release_pk, rule_pk, ticket_pk, tutorial_pk,
                              version_pk, view_pk)
from training_kb.models import (AuthoringRule, Entity, Feature, Feedback,
                                ProvenWorkflow, Release, StrictModel, Ticket,
                                Tutorial, TutorialStep, TutorialVersion, TutorialView)

type DynamoScalar = str | int | float | bool | None | bytes
type DynamoValue = DynamoScalar | list[DynamoValue] | dict[str, DynamoValue]
type DynamoItem = dict[str, DynamoValue]

T = TypeVar("T", bound=StrictModel)
RESERVED_ATTRS = frozenset({"PK", "SK", "target", "entity", "_revision"})


def _entity_pk(entity: Entity) -> str:
    if isinstance(entity, TutorialStep):
        raise PermanentError("TutorialStep 沒有 metadata item，請用 Phase 07 的 put_edge")
    if isinstance(entity, Tutorial):
        return tutorial_pk(entity.slug)
    if isinstance(entity, TutorialVersion):
        return version_pk(entity.version_id)
    if isinstance(entity, Feature):
        return feature_pk(entity.feature_id)
    if isinstance(entity, Ticket):
        return ticket_pk(entity.id)
    if isinstance(entity, Release):
        return release_pk(entity.id)
    if isinstance(entity, Feedback):
        return feedback_pk(entity.id)
    if isinstance(entity, TutorialView):
        return view_pk(entity.tutorial_version, entity.user, entity.ts)
    if isinstance(entity, AuthoringRule):
        return rule_pk(entity.rule_id)
    if isinstance(entity, ProvenWorkflow):
        return proc_pk(entity.signature)
    raise PermanentError(f"unknown entity type: {type(entity).__name__}")


def _encode(value: object) -> object:
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, list):
        return [_encode(item) for item in value]
    if isinstance(value, dict):
        return {key: _encode(item) for key, item in value.items()}
    return value


def _decode(value: object) -> object:
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, list):
        return [_decode(item) for item in value]
    if isinstance(value, dict):
        return {key: _decode(item) for key, item in value.items()}
    return value


class Repository:
    def __init__(self, table: object) -> None:
        self._table: Any = table

    def put_meta(self, entity: Entity, *, create_only: bool = True) -> None:
        pk = _entity_pk(entity)
        payload = {k: _encode(v) for k, v in entity.model_dump(mode="json").items()}
        revision = 1
        arguments: dict[str, object] = {
            "ConditionExpression": "attribute_not_exists(PK)"}
        if not create_only:
            current = self._revision_or_none(pk)
            if current is not None:
                revision = current + 1
                arguments = {
                    "ConditionExpression": "#revision = :current",
                    "ExpressionAttributeNames": {"#revision": "_revision"},
                    "ExpressionAttributeValues": {":current": current}}
        arguments["Item"] = {**payload, "PK": pk, "SK": META,
                             "entity": parse_pk(pk)[0], "_revision": revision}
        try:
            self._table.put_item(**arguments)
        except ClientError as error:
            if error.response["Error"]["Code"] == "ConditionalCheckFailedException":
                raise CoordinationError(
                    f"metadata already exists or changed since read: {pk}") from error
            raise

    def get_meta(self, pk: str, model: type[T], *, consistent: bool = True) -> T | None:
        response = self._table.get_item(
            Key={"PK": pk, "SK": META}, ConsistentRead=consistent)
        item = response.get("Item")
        if item is None:
            return None
        payload = {k: _decode(v) for k, v in item.items() if k not in RESERVED_ATTRS}
        return model.model_validate(payload)

    def get_feature(self, feature_id: str) -> Feature | None:
        return self.get_meta(feature_pk(feature_id), Feature)
```

公開簽名寫 `table: object`（00A 第 6.3 節），內部存成 `self._table: Any`：boto3 的 resource 物件沒有穩定的靜態型別，用 `Any` 才能在 `uv run mypy --strict` 下呼叫 `put_item`／`get_item`，同時讓呼叫端的型別提示維持 00A 的樣子。`_entity_pk` 以明確 `isinstance` 分派，沒有 fallback 猜鍵：漏掉哪個實體會直接撞上最後那行 `PermanentError`，不會悄悄寫出一把錯的鍵。保留屬性放在 `**payload` 之後，模型即使有同名欄位也蓋不掉物理欄位。另外三個具名 getter 與 `get_feature` 同一形狀，各一行：`get_tutorial` 用 `tutorial_pk(slug)` 與 `Tutorial`、`get_version` 用 `version_pk(version_id)` 與 `TutorialVersion`、`get_proc` 用 `proc_pk(signature)` 與 `ProvenWorkflow`。`_revision_or_none` **必須在本 Task 就補上**（原文寫「Task 2 補」）：`put_meta` 的 `create_only=False` 分支已經呼叫它，少了它 Task 1 自己的 Step 4 `uv run mypy` 就會停在 `"Repository" has no attribute "_revision_or_none"`，過不了 COMMON.md 的提交門檻。本 Task 仍然只**測**`create_only=True` 的路徑。

- [x] **Step 4：跑完整檔案確認綠燈**

```bash
uv run pytest tests/integration/test_repository_meta.py -q
uv run ruff check src/training_kb/repository.py tests/integration
uv run mypy src/training_kb/repository.py
```

預期：三個測試全 PASS。特別確認 `test_embedding_survives_the_decimal_codec`：忘了 codec 時 boto3 會丟 `TypeError: Float types are not supported. Use Decimal types instead.`；用 `Decimal(value)` 而不是 `Decimal(str(value))` 時，讀回來的 `0.1` 會帶二進位誤差而讓相等斷言失敗。

- [x] **Step 5：提交**

```bash
git add src/training_kb/repository.py \
  tests/integration/conftest.py tests/integration/test_repository_meta.py
git commit -m "feat(data): 建立 metadata 實體讀寫" -- \
  src/training_kb/repository.py \
  tests/integration/conftest.py tests/integration/test_repository_meta.py
```

`pyproject.toml` 不在提交範圍（本 Phase 不改它）；`tests/integration/` 底下同時有 Phase 13／14／15 的測試檔，**不得** `git add tests/integration`（整個目錄），只列自己的兩支。

## Task 2：條件建立、樂觀鎖更新與 `revision_of`

**Files:** `src/training_kb/repository.py`、`tests/integration/test_repository_meta.py`。

**Interfaces:** Consumes Task 1 的 `Repository`；Produces `update_meta`、`revision_of` 與 `create_only=False` 的條件覆寫。

- [x] **Step 1：建立失敗測試**

```python
def test_create_conflict_does_not_overwrite(repository) -> None:
    repository.put_meta(feature())
    with pytest.raises(CoordinationError, match="already exists"):
        repository.put_meta(feature("Meeting Summary"))
    assert repository.get_feature("Prepare") == feature()


def test_revision_of_drives_update_and_rejects_stale_writes(repository) -> None:
    repository.put_meta(feature())
    assert repository.revision_of("FEATURE#Prepare") == 1
    assert repository.update_meta(
        "FEATURE#Prepare", {"name": "Meeting Summary"},
        expected_revision=repository.revision_of("FEATURE#Prepare")) == 2
    assert repository.revision_of("FEATURE#Prepare") == 2
    with pytest.raises(CoordinationError, match="stale revision"):
        repository.update_meta("FEATURE#Prepare", {"name": "Prepare Again"},
                               expected_revision=1)
    assert repository.get_feature("Prepare").name == "Meeting Summary"
    with pytest.raises(CoordinationError, match="metadata not found"):
        repository.revision_of("FEATURE#Missing")


def test_reserved_attributes_and_empty_changes_are_rejected(repository) -> None:
    repository.put_meta(feature())
    for attribute in ("PK", "SK", "target", "entity", "_revision"):
        with pytest.raises(PermanentError, match="reserved"):
            repository.update_meta("FEATURE#Prepare", {attribute: "x"},
                                   expected_revision=1)
    with pytest.raises(PermanentError, match="at least one change"):
        repository.update_meta("FEATURE#Prepare", {}, expected_revision=1)


def test_controlled_overwrite_keeps_revision_monotonic(repository) -> None:
    repository.put_meta(feature())
    repository.put_meta(feature("Meeting Summary"), create_only=False)
    assert repository.revision_of("FEATURE#Prepare") == 2
    assert repository.get_feature("Prepare").name == "Meeting Summary"
```

最後一個測試把「受控覆寫」釘住：`create_only=False` 之後 revision 必須是 2 而不是 1，否則拿著舊 revision 的人還能成功寫入。

- [x] **Step 2：執行並確認紅燈**

```bash
uv run pytest tests/integration/test_repository_meta.py -q
```

預期：FAIL，訊號包含 `'Repository' object has no attribute 'revision_of'` 與 `... has no attribute 'update_meta'`。`test_create_conflict_does_not_overwrite` 在 Task 1 的實作下已經會 PASS，因為條件寫入在 `put_meta` 就完成了。

- [x] **Step 3：建立最小實作（三個方法加在 Task 1 的同一個 `Repository` 類別裡）**

```python
def _revision_or_none(self, pk: str) -> int | None:
    response = self._table.get_item(Key={"PK": pk, "SK": META}, ConsistentRead=True)
    item = response.get("Item")
    return None if item is None else int(item["_revision"])


def revision_of(self, pk: str) -> int:
    revision = self._revision_or_none(pk)
    if revision is None:
        raise CoordinationError(f"metadata not found: {pk}")
    return revision


def update_meta(self, pk: str, changes: Mapping[str, DynamoValue], *,
                expected_revision: int) -> int:
    if not changes:
        raise PermanentError(f"update_meta needs at least one change: {pk}")
    reserved = sorted(RESERVED_ATTRS.intersection(changes))
    if reserved:
        raise PermanentError(f"reserved attributes are not updatable: {reserved}")
    names = {"#revision": "_revision"}
    values: dict[str, object] = {":expected": expected_revision,
                                 ":next": expected_revision + 1}
    assignments = ["#revision = :next"]
    for index, field in enumerate(sorted(changes)):
        names[f"#f{index}"] = field
        values[f":v{index}"] = _encode(changes[field])
        assignments.append(f"#f{index} = :v{index}")
    try:
        self._table.update_item(
            Key={"PK": pk, "SK": META},
            UpdateExpression="SET " + ", ".join(assignments),
            ConditionExpression="#revision = :expected",
            ExpressionAttributeNames=names,
            ExpressionAttributeValues=values,
        )
    except ClientError as error:
        if error.response["Error"]["Code"] == "ConditionalCheckFailedException":
            raise CoordinationError(
                f"stale revision for {pk}: expected {expected_revision}") from error
        raise
    return expected_revision + 1
```

實作檔最上面補 `from collections.abc import Mapping`，測試檔的 import 補上 `CoordinationError`（Task 1 還用不到，先放會被 ruff 判為未使用）。每個欄位名都要經過 `ExpressionAttributeNames` 的 `#fN` 佔位，因為 `name`、`status`、`type` 都是 DynamoDB 保留字，直接寫進 `UpdateExpression` 會被拒。`#revision = :next` 與業務欄位在同一個 `SET` 裡，所以 revision 與內容一定一起生效或一起失敗。

- [x] **Step 4：跑完整檔案確認綠燈**

```bash
uv run pytest tests/integration/test_repository_meta.py -q
uv run mypy src/training_kb/repository.py
```

預期：七個測試全 PASS。人工再看一次失敗更新後的 `name`——它必須還是前一次成功寫入的值，不能留下半套結果。

- [x] **Step 5：提交**

```bash
git add src/training_kb/repository.py tests/integration/test_repository_meta.py
git commit -m "feat(data): 增加條件更新與 revision 取值"
```

## Task 3：準備可與 moto 分開的實表 smoke

**Files:** `tests/integration/test_repository_meta_smoke.py`。

**Interfaces:** Consumes `TKB_TABLE_NAME`、`TKB_AWS_REGION`；Produces 實表建立、讀取與清除單一測試 item 的證據。

真實 AWS 測試一律放 `tests/integration/` 並標 `@pytest.mark.aws`（[00A 第 3.1 節](00A-共用契約與名詞.md)），**不另開 AWS 專用測試目錄**。這個 marker 由 [Phase 01](01-Phase01-專案骨架與離線品質門檻.md) 在 `pyproject.toml` 註冊，而且 Phase 01 的 `tests/conftest.py` 會在沒有設 `TKB_RUN_AWS_INTEGRATION=1` 時**自動跳過**它們（裁決 D-41、D-64）。所以沒有帳號的人直接跑 `uv run pytest tests/integration -q` 就好，不必自己加 `-m` 條件；要真的打 AWS 時才把環境變數設成 `1`。

- [x] **Step 1：建立失敗測試**

```python
import os
from datetime import UTC, datetime
from uuid import uuid4

import boto3
import pytest

from training_kb.models import Feature
from training_kb.repository import Repository


@pytest.mark.aws
def test_real_table_metadata_round_trip() -> None:
    table = boto3.resource(
        "dynamodb", region_name=os.environ["TKB_AWS_REGION"]
    ).Table(os.environ["TKB_TABLE_NAME"])
    repository = Repository(table)
    feature_id = f"smoke-{uuid4().hex}"
    item = Feature(feature_id=feature_id, name=feature_id, aliases=[],
                   first_seen=datetime(2026, 8, 1, tzinfo=UTC))
    try:
        repository.put_meta(item)
        assert repository.get_feature(feature_id) == item
        assert repository.revision_of(f"FEATURE#{feature_id}") == 1
    finally:
        table.delete_item(Key={"PK": f"FEATURE#{feature_id}", "SK": "META"})
```

- [x] **Step 2：執行並確認紅燈**

```bash
uv run pytest tests/integration/test_repository_meta_smoke.py -q
TKB_RUN_AWS_INTEGRATION=1 uv run pytest tests/integration/test_repository_meta_smoke.py -m aws -q
```

預期：第一個指令是 `1 skipped`（沒開開關，Phase 01 的 `tests/conftest.py` 自動跳過，所以沒有帳號的人不會紅燈）；第二個指令在尚未有真實表時 FAIL 於 `KeyError: 'TKB_AWS_REGION'`，或 boto3 回 `ResourceNotFoundException`。這代表測試可被選到、marker 已註冊；若訊號是 `PytestUnknownMarkWarning`，回 Phase 01 的 `pyproject.toml` 補 `markers` 設定，不要在本 Phase 另立一份。

- [x] **Step 3：只在 Phase 09 資源就緒後執行綠燈**

```bash
TKB_RUN_AWS_INTEGRATION=1 TKB_TABLE_NAME=training_kb TKB_AWS_REGION=<你的 Region> \
  uv run pytest tests/integration/test_repository_meta_smoke.py -m aws -q
```

**實測結果（2026-09-14）**：Phase 09 已把 `training_kb` 部署到 `us-east-1`（`arn:aws:dynamodb:us-east-1:123456789012:table/training_kb`，`ACTIVE`），`TKB_RUN_AWS_INTEGRATION=1 TKB_TABLE_NAME=training_kb TKB_AWS_REGION=us-east-1` 下 **1 passed**，`FEATURE#smoke-*` 掃描回空清單（無殘留）。詳見 `.superpowers/sdd/phase0914-0/phase06-report.md` 第 7 節。

預期：真實表 round-trip PASS。報告記錄 Region、table ARN 後綴、時間與 request ID，不記錄 credentials。沒有帳號或權限時標記 `BLOCKED`，**不**把 moto 的 PASS 拿來代替。這支測試要用維護者本人的憑證跑，不能用 [Phase 09](09-Phase09-AWS資料資源與最小IAM.md) 的資料角色——那個角色刻意不含 `dynamodb:DeleteItem`，`finally` 的清除會被拒；真的被拒就把殘留的 `FEATURE#smoke-*` item 記進報告由人工刪，**不得**為了讓測試過而放寬 IAM。它寫的又是正式 `training_kb` 表，所以 `feature_id` 一定要帶 `smoke-` 前綴與隨機碼。

- [x] **Step 4：提交（不論是否已有帳號都要提交測試檔）**

```bash
git add tests/integration/test_repository_meta_smoke.py
git commit -m "test(data): 增加實表 metadata smoke" -- tests/integration/test_repository_meta_smoke.py
```

## 驗收矩陣

| 路徑 | 輸入 | 預期資料結果 |
|---|---|---|
| Happy | 九種 metadata 實體各一個合法 fixture | 全部 round-trip 回原 model；datetime、list、map 是原生型別，不是手寫 JSON 字串 |
| Happy | `put_meta(Feature(...))` 後讀 raw item | `entity == "FEATURE"`、`_revision == 1`，除保留屬性外剛好是模型欄位 |
| Happy | `revision_of(pk)` → `update_meta(..., expected_revision=該值)` | 回傳新的 revision，內容與 `_revision` 一起生效 |
| Failure | 同 PK／SK 再 `put_meta(create_only=True)` | `CoordinationError`（含 `already exists`），舊 item 一個 byte 都不變 |
| Failure | `expected_revision` 過期 | `CoordinationError`（含 `stale revision`），內容維持前一次成功值 |
| Failure | `update_meta` 的 changes 含保留屬性或為空 | `PermanentError`，不送出請求 |
| Failure | `put_meta(TutorialStep(...))` | `PermanentError`（含 `put_edge`），表中不出現 `STEP#...` 的 `META` item |
| Boundary | `Ticket.embedding` 1024 個值，含 `0.0` 與負值 | 寫成 `Decimal`，讀回等於原 list；沒有 `TypeError`、沒有浮點誤差 |
| Boundary | `revision_of` 指向不存在的 PK | `CoordinationError`，不回 0、不回 `None` |
| Gate | O1 尚未核定／moto 通過但實表未跑 | 停止所有 metadata write／只報 local integration PASS，AWS 仍標未驗證 |

人工驗收（不能只看 PASS）：在 moto 表對 `FEATURE#Prepare` 抓一次 raw item，逐個屬性名比對 [00A 第 3.6 節](00A-共用契約與名詞.md) 的「模型欄位 + `RESERVED_ATTRS`，沒有第三類」；確認只有一張表、metadata `SK` 等於 O1 決定值、十實體沒有被拆成十張表。

## 常見錯誤與停止條件

| 症狀 | 原因 | 修正／停止 |
|---|---|---|
| `TypeError: Float types are not supported. Use Decimal types instead.` | `model_dump` 出來的 `float` 直接交給 boto3 | 走 `_encode`／`_decode` 這對 codec，且用 `Decimal(str(value))`。 |
| 讀回來的 embedding 與寫進去的不相等 | 用了 `Decimal(value)`，保留二進位浮點誤差 | 固定 `Decimal(str(value))`；比較失敗就停止，不要改成近似比較。 |
| `ValidationError: Extra inputs are not permitted` | `get_meta` 忘了濾掉 `entity`／`_revision` | 過濾集合一律用 `RESERVED_ATTRS`，不要在各 getter 各寫一份。 |
| item 冒出 `step_count`、`retired_at` 這類欄位 | 為了方便把執行資訊塞進 metadata | 嚴格模型會在讀取時整筆拒絕；執行資訊寫進 Phase 10 的 operation 紀錄。 |
| `ValidationException: Attribute name is a reserved keyword` | `UpdateExpression` 直接寫 `name`／`status`／`type` | 每個欄位都經 `ExpressionAttributeNames` 的 `#fN` 佔位。 |
| `create_only=False` 之後 stale 更新居然成功 | 覆寫時把 `_revision` 重設成 1 | 覆寫必須讀 `revision_of` 加一並帶條件；改不掉就停止，這是本 Phase 的停止點。 |
| 用 `create_only=False` 繞過建立衝突 | 把它當成衝突時的快速修法 | 它只給 Phase 38 回填向量這類受控路徑；一般路徑衝突就是停止與回報。 |
| 宣稱「revision 保證了順序」 | 把樂觀鎖當成 O2 | revision 只擋 stale write，不證明 FIFO、不證明跨 S3 交易；O2 由 Phase 10／11 驗證。 |

Feature alias 的跨 item 唯一性不能只靠模型；本 Phase 不宣稱 alias 全域衝突已解決，那是 [Phase 49](49-Phase49-Release功能定位與Alias.md) 的責任。

## 來源與 Rule 對照

- [設計 §2](../../design/training-kb.md#s2)：十實體包含 `TutorialView`。
- [設計 §9.1](../../design/training-kb.md#s9)：單表鍵、`META` 建議值、原生 list／map、1024 維向量；`TUTORIAL_STEP` 的 SK 是 `REFERENCES#<Feature PK>` 而不是 `META`。
- [00A 第 3.6、6.3 節](00A-共用契約與名詞.md)：`RESERVED_ATTRS`、`entity` 值等於 PK 前綴、`revision_of` 是 `expected_revision` 的唯一來源。
- 本 Phase 在 [00B 需求覆蓋對照](00B-需求覆蓋對照.md) 中**沒有** primary Rule，以下一律標「相關」：
  - [提出教學規則.feature](../../spec/features/提出教學規則.feature) Rule 6：「MVP 的教學與產品功能識別碼在單一專案範圍內唯一」→ 相關（primary 在 Phase 04）；本 Phase 只提供「同鍵不得重複建立」的條件寫入證據。
  - [接入來源事件.feature](../../spec/features/接入來源事件.feature) Rule 21：「正規化物件必須具有 schema 的必填欄位」→ 相關（primary 在 Phase 31）。
  - [接入來源事件.feature](../../spec/features/接入來源事件.feature) Rule 28：「正規化成功的 Feedback 寫入 FEEDBACK item」→ 相關（primary 在 Phase 42）。
  - [依改版更新教學.feature](../../spec/features/依改版更新教學.feature) Rule 3：「改名不變更第一次建立的 Feature 主鍵」→ 相關（primary 在 Phase 49）；本 Phase 只保證 `update_meta` 改欄位不改 PK。

## 完成清單

- [x] O1 記錄已 accepted（或有經核定替代值）才寫 metadata item。
- [x] 九個 metadata 實體共用同一組 key builder 與同一份 Decimal codec。
- [x] item 屬性剛好是「模型欄位 + `RESERVED_ATTRS`」，`entity` 等於 PK 前綴。
- [x] `put_meta(TutorialStep(...))` 明確拒絕並指向 Phase 07 的 `put_edge`。
- [x] 建立與更新都有條件，`create_only=False` 也不重設 `_revision`；衝突一律 `CoordinationError`。
- [x] `revision_of` 存在，且 `update_meta` 的 `expected_revision` 只從它取得。
- [x] fixture 與 test helper 都在預計檔案內有完整定義，沒有未定義的 helper。
- [x] 實表 smoke 在 `tests/integration/` 並標 `@pytest.mark.aws`，與 moto 的結果分開記錄；沒有帳號時標 `BLOCKED`。
- [x] Phase 07 可在不改動 metadata 契約的前提下加上 `bucket`、edge 與 `RESERVED_ATTRS` 的第二個用途。

## 實作後修訂（2026-09-14）

實作時與 00A／既有程式對不上的地方，依 COMMON.md「改 Phase 文件不改名」處理，逐條記錄：

1. **`pyproject.toml` 不修改。** Phase 01 已備妥 boto3、`moto[dynamodb,s3]`、`boto3-stubs`、`aws` marker
   與 `tests/conftest.py` 的自動跳過；本 Phase 逐項確認後不動它（COMMON.md 明令不得改
   `pyproject.toml`／`uv.lock`）。「預計新增／修改的檔案」表已改成「（不動）」。
2. **`uv sync --all-extras` 刪除。** 本專案用 `[dependency-groups] dev`，沒有 `optional-dependencies`；
   `uv run` 會自動同步 dev group。
3. **`_revision_or_none` 從 Task 2 移到 Task 1。** `put_meta` 的 `create_only=False` 分支已經呼叫它，
   否則 Task 1 自己的 Step 4 `uv run mypy` 不會過。
4. **兩處 `git add` 縮小範圍。** `tests/integration/` 底下同時有 Phase 13／14／15 的檔案，
   不得 `git add tests/integration`；提交一律列出自己的檔案並加 `-- <同一批檔案>`。
5. **驗收矩陣第一列補測試。** 原本三個 Task 只測 Feature 與 Ticket，矩陣卻要求「九種 metadata 實體各一個
   合法 fixture 全部 round-trip」。已加 `test_all_nine_metadata_entities_round_trip`、
   `test_native_list_and_map_are_not_json_strings`（`ProvenWorkflow.steps` 是原生 list of map、
   `keys` 是原生 list、時間是 ISO 字串）與 `test_named_getters_use_their_own_key_builder`。
6. **本 Phase 另外產出 `item_to_model`、`put_meta_item`、`get_meta_item`（範圍裁決）。**
   [00A 第 3.2 節](00A-共用契約與名詞.md) 把 `repository.py` 的責任寫成「單一 `Repository` 類別與
   `item_to_model`」、owner 是 P06；[第 3.6 節](00A-共用契約與名詞.md) 也把 `item_to_model` 與
   `put_meta_item`／`get_meta_item` 列進保留屬性的同一套規則。但 [第 6.3 節](00A-共用契約與名詞.md)
   的 owner 欄把 `item_to_model` 記給 P08、`put_meta_item`／`get_meta_item` 記給 P10。
   本次依 controller 指派的 Phase 06 範圍**在此一併實作**，簽名逐字採用 6.3 節的 canonical 形狀：
   - `item_to_model` 與 `get_meta` 共用同一份過濾（`RESERVED_ATTRS` + Decimal 解碼），
     所以 `get_meta` 直接呼叫它，全套只有一份實作。
   - `put_meta_item` 與 `put_meta` 共用同一條私有條件寫入 `_put_item`，`PK`／`SK`／`entity`／`_revision`
     的來源只有一個；差別只在 `create_only` 撞鍵時回 `False` 而不是丟 `CoordinationError`
     （00A 第 6.3 節：「回傳『本次是否由我建立』」，Phase 11 的永久去重就是看這個布林）。
   - `get_meta_item` 回整筆 raw item 並已把 `Decimal` 解碼成 `int`／`float`，所以同一次讀到的
     `_revision` 可以直接當 `update_meta` 的 `expected_revision`（00A 第 3.6 節的唯一例外）。
   - [Phase 08](08-Phase08-分頁查詢與一致讀取基礎.md) 與 [Phase 10](10-Phase10-O2操作紀錄與永久去重契約.md)
     接手時應**確認已存在並直接消費／擴充**，不要再宣告第二份（同 `RESERVED_ATTRS` 的處理方式）。
7. **`item_to_model` 用 PEP 695 型別參數。** ruff 的 `UP047`（`target-version = "py312"`）要求泛型函式寫成
   `def item_to_model[T: StrictModel](...)`；公開簽名與 00A 第 6.3 節的
   `(item: DynamoItem, model: type[T]) -> T` 完全相同，只是綁定寫在函式自己身上。
   模組層仍保留 `T = TypeVar("T", bound=StrictModel)` 給 `get_meta` 用。
8. **`_decode` 的回傳型別是 `Any`。** 反序列化出來的形狀由 item 決定；寫 `object` 會讓
   `get_meta_item` 的 `DynamoItem` 回傳值在 mypy strict 下失敗。沒有使用 `# type: ignore`
   或 `ignore_errors`。

**下一份可用成果：** 有條件衝突保護、可將九個 metadata 實體 round-trip，並提供 `revision_of` 的 Repository metadata 核心。
