"""單表讀寫：把 DynamoDB 的 `PK`／`SK`／`entity`／`_revision` 藏在這裡，領域模型不感知物理欄位。

九個實體有 metadata item（SK 固定是 `META`），`TutorialStep` 沒有——它本身就是
`REFERENCES#<FEATURE PK>` 邊（設計 §9.1），所以 `put_meta(TutorialStep(...))` 明確拒絕。
建立走 `attribute_not_exists(PK)`，更新走 `_revision` 的 compare-and-swap；兩種條件都在
AWS 端判斷，不是「先查再寫」。衝突一律 `CoordinationError`（**不是** `TransientError`，
呼叫端不得自動重試）。

檔案分成四段，Phase 07／08／10 直接接在後面，不必改動前面幾段：
1. 型別別名與保留屬性
2. 實體 → PK 的分派
3. Decimal codec 與 `item_to_model`（DynamoDB 只收 `Decimal`，不收 `float`）
4. `Repository`：metadata CRUD、`revision_of`、四個具名 getter，以及不走模型的
   `put_meta_item`／`get_meta_item`（服務 `OPS#`／`CONFIG#`／`SEQ#`／`LEASE#`）
"""

from collections.abc import Callable, Mapping
from decimal import Decimal
from typing import Any, TypeVar

from boto3.dynamodb.conditions import ConditionBase, Key
from botocore.exceptions import ClientError

from training_kb.errors import (
    CoordinationError,
    ObjectAlreadyExists,
    PermanentError,
    TransientError,
)
from training_kb.keys import (
    META,
    edge_sk,
    feature_pk,
    feedback_pk,
    parse_edge_sk,
    parse_pk,
    proc_pk,
    release_pk,
    rule_pk,
    ticket_pk,
    tutorial_pk,
    version_pk,
    view_pk,
)
from training_kb.models import (
    AuthoringRule,
    Entity,
    Feature,
    Feedback,
    ProvenWorkflow,
    Release,
    StrictModel,
    Ticket,
    Tutorial,
    TutorialStep,
    TutorialVersion,
    TutorialView,
)

# --- 1. 型別別名與保留屬性 ---------------------------------------------------

type DynamoScalar = str | int | float | bool | None | bytes
type DynamoValue = DynamoScalar | list[DynamoValue] | dict[str, DynamoValue]
type DynamoItem = dict[str, DynamoValue]
type EdgeAttrs = Mapping[str, DynamoValue] | None

T = TypeVar("T", bound=StrictModel)

RESERVED_ATTRS = frozenset({"PK", "SK", "target", "entity", "_revision"})
"""item 上唯一允許的非模型屬性（00A §3.6）；只能由 `Repository` 自己算，呼叫端不得傳、不得更新。
`target` 只有 Phase 07 的關係邊會用到，一起列進來讓整套只有一份定義。"""

MISSING_CODES = frozenset({"NoSuchKey", "404"})
"""S3 的「這個 key 不存在」：`GetObject` 回 `NoSuchKey`，`HeadObject` 沒有 body 只回 `404`。
只有這兩個碼會被吞成 `None`／`False`，其餘 `ClientError` 一律往外丟。"""


# --- 2. 實體 -> PK 的分派 ----------------------------------------------------


def _entity_pk(entity: Entity) -> str:
    """明確 `isinstance` 分派，沒有 fallback 猜鍵：漏掉哪個實體就撞最後一行，不會寫出錯的鍵。"""
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


# --- 3. Decimal codec 與 item_to_model ---------------------------------------


def _encode(value: object) -> object:
    """`float` -> `Decimal(str(value))`；用 `str` 才不會把二進位浮點誤差一起寫進表。"""
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, list):
        return [_encode(item) for item in value]
    if isinstance(value, dict):
        return {key: _encode(item) for key, item in value.items()}
    return value


def _decode(value: object) -> Any:
    """`Decimal` -> `int`／`float`；回 `Any` 是因為反序列化出來的形狀本來就由 item 決定。"""
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, list):
        return [_decode(item) for item in value]
    if isinstance(value, dict):
        return {key: _decode(item) for key, item in value.items()}
    return value


def item_to_model[T: StrictModel](item: DynamoItem, model: type[T]) -> T:
    """raw item -> 模型：去掉 `RESERVED_ATTRS` 再 `model_validate`（00A §3.6）。

    模組函式不是方法，因為 Phase 08 的 `query_pk`／`scan_entity` 與 Phase 27、28、39、44、50
    都會直接 import 它。模型是 `extra="forbid"`，直接餵 raw item 一定 `ValidationError`。
    型別參數寫成 PEP 695 的 `[T: StrictModel]`（ruff UP047 要求），公開簽名與 00A §6.3 的
    `(item: DynamoItem, model: type[T]) -> T` 完全相同，只是綁定寫在函式自己身上。
    """
    payload = {key: _decode(value) for key, value in item.items() if key not in RESERVED_ATTRS}
    return model.model_validate(payload)


# --- 4. Repository -----------------------------------------------------------


class Repository:
    """單表讀寫的唯一入口。

    公開簽名寫 `table: object`（00A §6.3），內部存成 `self._table: Any`：boto3 的 resource
    物件沒有穩定的靜態型別，用 `Any` 才能在 mypy strict 下呼叫 `put_item`／`get_item`。
    """

    def __init__(self, table: object, bucket: object | None = None) -> None:
        self._table: Any = table
        self._bucket: Any = bucket

    # --- metadata 寫入 ---

    def put_meta(self, entity: Entity, *, create_only: bool = True) -> None:
        """建立（或受控覆寫）一筆 metadata item。

        `create_only=True` 用 `attribute_not_exists(PK)` 擋同鍵覆蓋；`create_only=False`
        只給 Phase 38 回填向量這類受控路徑，它仍然帶條件、而且把 `_revision` 往上加，
        不會重設成 1 讓舊的持有者誤以為自己是最新。
        """
        pk = _entity_pk(entity)
        payload = {k: _encode(v) for k, v in entity.model_dump(mode="json").items()}
        if not self._put_item(pk, payload, create_only=create_only):
            raise CoordinationError(f"metadata already exists or changed since read: {pk}")

    def put_meta_item(self, pk: str, attributes: Mapping[str, DynamoValue], *,
                      create_only: bool = True) -> bool:
        """不走模型的 `OPS#`／`CONFIG#`／`SEQ#`／`LEASE#` 原語；回「本次是否由我建立」。

        與 `put_meta` 共用同一條條件寫入路徑，所以 `PK`／`SK`／`entity`／`_revision`
        的來源只有一個。差別只在撞鍵時回 `False` 而不是丟 `CoordinationError`——
        呼叫端要的正是「別人先建立了」這個事實（永久去重的判斷點）。
        """
        reserved = sorted(RESERVED_ATTRS.intersection(attributes))
        if reserved:
            raise PermanentError(f"reserved attributes are not writable: {reserved}")
        payload = {key: _encode(value) for key, value in attributes.items()}
        return self._put_item(pk, payload, create_only=create_only)

    def _put_item(self, pk: str, payload: Mapping[str, object], *, create_only: bool) -> bool:
        """條件寫入的唯一實作。回 `True` 表示這次是新建，`False` 表示 `create_only` 撞鍵。

        `create_only=False` 仍然帶條件（`#revision = :current`），而且把 `_revision` 往上加，
        不會重設成 1 讓舊的持有者誤以為自己是最新；期間被改過就丟 `CoordinationError`。
        """
        revision = 1
        arguments: dict[str, object] = {"ConditionExpression": "attribute_not_exists(PK)"}
        current = None if create_only else self._revision_or_none(pk)
        if current is not None:
            revision = current + 1
            arguments = {
                "ConditionExpression": "#revision = :current",
                "ExpressionAttributeNames": {"#revision": "_revision"},
                "ExpressionAttributeValues": {":current": current},
            }
        arguments["Item"] = {**payload, "PK": pk, "SK": META,
                             "entity": parse_pk(pk)[0], "_revision": revision}
        try:
            self._table.put_item(**arguments)
        except ClientError as error:
            if error.response["Error"]["Code"] != "ConditionalCheckFailedException":
                raise
            if current is not None:
                raise CoordinationError(
                    f"metadata changed since read: {pk}") from error
            return False
        return True

    def _revision_or_none(self, pk: str) -> int | None:
        """讀目前的 `_revision`；item 不存在回 `None`。`revision_of` 與受控覆寫共用它。"""
        response = self._table.get_item(Key={"PK": pk, "SK": META}, ConsistentRead=True)
        item = response.get("Item")
        return None if item is None else int(item["_revision"])

    def revision_of(self, pk: str) -> int:
        """`expected_revision` 的唯一取值來源；`get_meta` 濾掉 `_revision`，模型身上沒有它。"""
        revision = self._revision_or_none(pk)
        if revision is None:
            raise CoordinationError(f"metadata not found: {pk}")
        return revision

    def update_meta(self, pk: str, changes: Mapping[str, DynamoValue], *,
                    expected_revision: int) -> int:
        """revision compare-and-swap：只有目前 `_revision` 等於讀到的值才更新，回傳新的 revision。

        每個欄位名都經 `ExpressionAttributeNames` 的 `#fN` 佔位，因為 `name`／`status`／`type`
        都是 DynamoDB 保留字；`#revision = :next` 與業務欄位在同一個 `SET`，所以版本與內容
        一定一起生效或一起失敗。
        """
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

    # --- metadata 讀取 ---

    def get_meta(self, pk: str, model: type[T], *, consistent: bool = True) -> T | None:
        response = self._table.get_item(Key={"PK": pk, "SK": META}, ConsistentRead=consistent)
        item = response.get("Item")
        return None if item is None else item_to_model(item, model)

    def get_meta_item(self, pk: str) -> DynamoItem | None:
        """`put_meta_item` 的反向原語：回整筆 raw item（含保留屬性），不存在回 `None`。

        `Decimal` 已解碼成 `int`／`float`，所以同一次讀到的 `_revision` 可以直接當
        `update_meta` 的 `expected_revision`（00A §3.6 的唯一例外），不必再讀一次。
        """
        response = self._table.get_item(Key={"PK": pk, "SK": META}, ConsistentRead=True)
        item = response.get("Item")
        if item is None:
            return None
        decoded: DynamoItem = {key: _decode(value) for key, value in item.items()}
        return decoded

    def get_tutorial(self, slug: str) -> Tutorial | None:
        return self.get_meta(tutorial_pk(slug), Tutorial)

    def get_version(self, version_id: str) -> TutorialVersion | None:
        return self.get_meta(version_pk(version_id), TutorialVersion)

    def get_feature(self, feature_id: str) -> Feature | None:
        return self.get_meta(feature_pk(feature_id), Feature)

    def get_proc(self, signature: str) -> ProvenWorkflow | None:
        return self.get_meta(proc_pk(signature), ProvenWorkflow)

    # --- S3 物件 ---

    def _require_bucket(self) -> Any:
        """把「建 `Repository` 時沒給 bucket」變成看得懂的 `PermanentError`。

        不加這一層的話呼叫端只會看到 `AttributeError: 'NoneType' object has no attribute
        'put_object'`，要回頭翻才知道是建構參數少了一個。
        """
        if self._bucket is None:
            raise PermanentError("repository was created without an S3 bucket")
        return self._bucket

    def put_object(self, key: str, body: bytes, content_type: str, *, if_none_match: bool) -> None:
        """寫一個私有物件；`if_none_match=True` 時「同 key 是否已存在」交給 AWS 判斷。

        固定順序是「先送出、再依回應分類」，不是「先查存在再寫」——先查再寫會在兩個請求
        之間留下空窗，兩個 Lambda 可能同時判斷為不存在。412（已存在）轉
        `ObjectAlreadyExists`，409（併發刪除造成的暫時衝突）轉 `TransientError` 交 ASL Retry；
        這裡不自己迴圈重試，避免與 Phase 29 的單層 Task Retry 相乘。
        送出的參數只有 `Key`／`Body`／`ContentType`（＋`IfNoneMatch`），沒有 `ACL`：
        公開與否一律由 bucket policy 的 `site/*` 決定（00A §3.8）。
        """
        arguments: dict[str, object] = {"Key": key, "Body": body, "ContentType": content_type}
        if if_none_match:
            arguments["IfNoneMatch"] = "*"
        try:
            self._require_bucket().put_object(**arguments)
        except ClientError as error:
            code = error.response["Error"]["Code"]
            if code == "PreconditionFailed":
                raise ObjectAlreadyExists(f"object already exists: {key}") from error
            if code == "ConditionalRequestConflict":
                raise TransientError(f"conditional write conflicted: {key}") from error
            raise

    def get_object(self, key: str) -> bytes | None:
        """讀回整個 body；key 不存在回 `None` 而不是丟例外。

        真實 S3 要有 `s3:ListBucket` 才會對不存在的 key 回 404 而不是 403（00A §3.8），
        否則這個「不存在回 `None`」的契約在雲端不成立。
        """
        try:
            payload: bytes = self._require_bucket().Object(key).get()["Body"].read()
        except ClientError as error:
            if error.response["Error"]["Code"] in MISSING_CODES:
                return None
            raise
        return payload

    def object_exists(self, key: str) -> bool:
        """只取 metadata（HeadObject），不下載 body。"""
        try:
            self._require_bucket().Object(key).load()
        except ClientError as error:
            if error.response["Error"]["Code"] in MISSING_CODES:
                return False
            raise
        return True

    # --- 關係邊 ---

    def put_edge(self, pk: str, relation: str, target_pk: str, attrs: EdgeAttrs = None) -> None:
        """保存一筆 `PK=起點`、`SK=<關係>#<終點>`、`target=<終點>` 的邊（設計 §9.2）。

        `target` **只能**由 `target_pk` 導出：呼叫端另外傳一個 `target` 會讓同一份資訊有兩份
        會不一致的副本，所以保留屬性一律拒絕。`entity` 等於起點 PK 的前綴（00A §3.6），
        Phase 08 的 `scan_entity` 就是靠它篩選。屬性值走與 `put_meta_item` 同一套
        Decimal codec，整套只有一個地方決定 `float` 怎麼寫進表。
        """
        extra = {key: _encode(value) for key, value in dict(attrs or {}).items()}
        forbidden = sorted(RESERVED_ATTRS.intersection(extra))
        if forbidden:
            raise PermanentError(f"edge attributes are reserved: {forbidden}")
        sort_key = edge_sk(relation, target_pk)
        if parse_edge_sk(sort_key) != (relation, target_pk):
            raise PermanentError(f"edge sort key does not round-trip: {sort_key}")
        self._table.put_item(
            Item={"PK": pk, "SK": sort_key, "target": target_pk,
                  "entity": parse_pk(pk)[0], **extra}
        )

    def _paged(self, operation: Callable[..., Any], **arguments: Any) -> list[DynamoItem]:
        """反覆呼叫同一個 boto3 操作直到回應沒有 `LastEvaluatedKey`，**空頁不早停**。

        DynamoDB 的一頁可能沒有任何 `Items` 卻仍帶 `LastEvaluatedKey`（被過濾掉或撞到 1 MB
        上限），看到空頁就 `break` 會靜默漏資料。本 Phase 只有 `list_edges` 用它；
        Phase 08 會擴充（加 `Limit`）再給三個公開查詢共用，所以留在 `Repository` 內部。
        """
        items: list[DynamoItem] = []
        while True:
            response = operation(**arguments)
            items.extend(response.get("Items", []))
            cursor = response.get("LastEvaluatedKey")
            if not cursor:
                return items
            arguments["ExclusiveStartKey"] = cursor

    def list_edges(self, pk: str, relation: str | None = None) -> list[DynamoItem]:
        """回某個起點的全部邊（可選擇只要某一種關係）；`META` item 不算邊。

        讀取端也逐筆核對 `SK` 終點與 `target`，因為 backfill（Phase 28）與維護腳本一樣會
        寫邊，只在寫入端檢查發現不了已經寫壞的資料；不一致就停下來丟 `PermanentError`，
        **不自動修正**。回的是 raw item，呼叫端要模型一律經 `item_to_model`（00A §3.6）。
        """
        condition: ConditionBase = Key("PK").eq(pk)
        if relation is not None:
            condition = condition & Key("SK").begins_with(f"{relation}#")
        edges: list[DynamoItem] = []
        for item in self._paged(
            self._table.query, KeyConditionExpression=condition, ConsistentRead=True
        ):
            sort_key = str(item["SK"])
            if sort_key == META:
                continue
            if parse_edge_sk(sort_key)[1] != item.get("target"):
                raise PermanentError(
                    f"edge target does not match sort key: {str(item['PK'])} {sort_key}")
            edges.append(item)
        return edges
