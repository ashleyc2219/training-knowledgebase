"""單表讀寫：把 DynamoDB 的 `PK`／`SK`／`entity`／`_revision` 藏在這裡，領域模型不感知物理欄位。

九個實體有 metadata item（SK 固定是 `META`），`TutorialStep` 沒有——它本身就是
`REFERENCES#<FEATURE PK>` 邊（設計 §9.1），所以 `put_meta(TutorialStep(...))` 明確拒絕。
建立走 `attribute_not_exists(PK)`，更新走 `_revision` 的 compare-and-swap；兩種條件都在
AWS 端判斷，不是「先查再寫」。衝突一律 `CoordinationError`（**不是** `TransientError`，
呼叫端不得自動重試）。

檔案分成六段，後來的 Phase 直接接在後面，不必改動前面幾段：
1. 型別別名與保留屬性
2. 實體 → PK 的分派
3. Decimal codec 與 `item_to_model`（DynamoDB 只收 `Decimal`，不收 `float`）
4. `Repository`：metadata CRUD、`revision_of`、四個具名 getter，不走模型的
   `put_meta_item`／`get_meta_item`（服務 `OPS#`／`CONFIG#`／`SEQ#`／`LEASE#`），
   再往下是 Phase 07 的 S3 物件（`put_object`／`get_object`／`object_exists`）與
   關係邊（`put_edge`／`list_edges`，共用私有的 `_paged`），最後是 Phase 08 的三個公開查詢
   （`query_pk`／`query_by_target`／`scan_entity`）與六個固定讀取（`get_steps` 與五個 `list_*`）
5. Phase 24 追加的交易寫入（`table_name`／`transact_write`）：唯一走 boto3 **client** 的一段，
   值仍然是原生 Python 值（resource 的 client 會自己序列化，見 `transact_write` 說明）
6. Phase 27 追加的固定圖譜查詢（五個具名方法，與 Phase 08 的 `list_feedback_of_version`
   合為設計 §10 的六種固定查詢）與排序用的模組函式 `version_sort_key`；全部只讀、不接
   `Writer`，所以正常關係遍歷不可能呼叫模型
"""

from collections.abc import Callable, Mapping, Sequence
from decimal import Decimal
from typing import Any, TypeVar

from boto3.dynamodb.conditions import Attr, ConditionBase, Key
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
    parse_step_pk,
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
    RuleStatus,
    StrictModel,
    Ticket,
    Tutorial,
    TutorialStatus,
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
    """`float` -> `Decimal(str(value))`；用 `str` 才不會把二進位浮點誤差一起寫進表。

    序列一併認 `tuple`：Phase 10 的 `OperationRecord.model_output_refs` 是 `tuple[str, ...]`，
    只認 `list` 的話 tuple 內的 `float` 會直接撞 boto3 的 `Float types are not supported`。
    """
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, list | tuple):
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


def version_sort_key(version_id: str) -> tuple[str, int]:
    """`<slug>@v<n>` -> `(slug, n)`：版本排序的唯一依據（00A §6.3）。

    模組函式而不是方法，因為 Phase 27 的三個查詢與 Phase 28 都要拿它當 `sorted` 的 key。
    字典序會把 `@v10` 排在 `@v2` 前面，所以只要牽涉版本排序就一律經過它。
    它與 `content.parse_version_id` 回傳同一種東西，但**不能**直接 import：相依方向是
    `content` 呼叫 `repository`（設計 §5），反向 import 會造成循環，所以這裡自帶一份最小解析。
    驗證寫法與那一支對齊——`isdecimal()`（不是 `isdigit()`）擋掉 `²` 這種 `int()` 會丟自己的
    `ValueError` 的字元，再用 round-trip 比較擋掉 `a@v01` 的前導零與 `a@v１` 的全形數字，
    否則兩個字串會對應同一版、排序也就不再是全序。格式不合丟 `PermanentError`
    （**不是** `ValueError`）：呼叫端拿到的是「這筆資料確定不合法」，不是鍵格式筆誤。
    """
    slug, marker, suffix = version_id.partition("@v")
    number = int(suffix) if suffix.isdecimal() else 0
    if not slug or not marker or number < 1 or f"{slug}@v{number}" != version_id:
        raise PermanentError(f"不是合法的 version_id：{version_id}")
    return slug, number


# --- 4. Repository -----------------------------------------------------------


class Repository:
    """單表讀寫的唯一入口。

    公開簽名寫 `table: object`（00A §6.3），內部存成 `self._table: Any`：boto3 的 resource
    物件沒有穩定的靜態型別，用 `Any` 才能在 mypy strict 下呼叫 `put_item`／`get_item`。
    """

    def __init__(self, table: object, bucket: object | None = None, *,
                 page_size: int | None = None) -> None:
        self._table: Any = table
        self._bucket: Any = bucket
        self._page_size = page_size

    # --- metadata 寫入 ---

    def put_meta(self, entity: Entity, *, create_only: bool = True) -> None:
        """建立（或受控覆寫）一筆 metadata item。

        `create_only=True` 用 `attribute_not_exists(PK)` 擋同鍵覆蓋；`create_only=False`
        只給 Phase 38 回填向量這類受控路徑，它仍然帶條件、而且把 `_revision` 往上加，
        不會重設成 1 讓舊的持有者誤以為自己是最新。
        """
        pk = _entity_pk(entity)
        payload = {k: _encode(v) for k, v in entity.model_dump(mode="json").items()}
        created = self._put_item(pk, payload, create_only=create_only)
        if create_only and not created:
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
        """條件寫入的唯一實作。回傳值是「**本次是否由我建立**」（00A §6.3）。

        新建成功回 `True`；受控覆寫（`create_only=False` 且 item 已存在）成功回 `False`——
        回 `True` 會讓 `OPS#`／`SEQ#`／`LEASE#` 的呼叫端誤以為自己是第一個建立者，
        永久去重的判斷點就失效了。`create_only=True` 撞鍵同樣回 `False`（沒有寫入）。
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
        try:
            kind = parse_pk(pk)[0]
        except ValueError as error:
            raise PermanentError(f"invalid physical primary key: {pk!r}") from error
        arguments["Item"] = {**payload, "PK": pk, "SK": META,
                             "entity": kind, "_revision": revision}
        try:
            self._table.put_item(**arguments)
        except ClientError as error:
            if error.response["Error"]["Code"] != "ConditionalCheckFailedException":
                raise
            if current is not None:
                raise CoordinationError(
                    f"metadata changed since read: {pk}") from error
            if not create_only:
                raise CoordinationError(
                    f"metadata created by someone else since read: {pk}") from error
            return False
        return current is None

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
        上限），看到空頁就 `break` 會靜默漏資料。`list_edges` 與 Phase 08 的三個公開查詢
        共用它，所以留在 `Repository` 內部，外部不得 import。

        `page_size` 有值時每個請求都帶同一個 `Limit`（含續查的那幾次），讓小資料也能製造
        多頁與空頁；正式程式不設定它，讓 DynamoDB 用預設的 1 MB 分頁。
        """
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

    # --- 三個公開查詢 ---

    def query_pk(self, pk: str, *, sk_prefix: str | None = None,
                 consistent: bool = True) -> list[DynamoItem]:
        """基表 Query：一個 PK 上的全部 item（`META` 與各種邊都算），讀完所有分頁。

        `sk_prefix` 走 `begins_with`，所以 `query_pk(pk, sk_prefix="REFERENCES#")` 只回那一種
        關係。基表可以一致讀取，結果能直接當業務判斷依據（設計 §10）。回的是 raw item，
        要模型一律經 `item_to_model`。
        """
        condition: ConditionBase = Key("PK").eq(pk)
        if sk_prefix is not None:
            condition = condition & Key("SK").begins_with(sk_prefix)
        return self._paged(self._table.query, KeyConditionExpression=condition,
                           ConsistentRead=consistent)

    def query_by_target(self, target_pk: str) -> list[DynamoItem]:
        """`by_target` GSI Query：誰指向這個終點。回的是**候選**，不是答案。

        GSI 只有最終一致而且是 `KEYS_ONLY`（索引裡只有 `PK`／`SK`／`target`），所以這裡沒有、
        也不能有 `ConsistentRead`；任何業務判斷都要拿候選的 PK 回基表一致讀取核對，
        `list_feedback_of_version` 就是範例。等固定秒數不算核對（設計 §10 明文禁止）。
        索引名稱與 Phase 09 CDK 的 `TARGET_INDEX` 是同一個值，改名要一起改。
        """
        return self._paged(self._table.query, IndexName="by_target",
                           KeyConditionExpression=Key("target").eq(target_pk))

    def scan_entity(self, entity: str, *, consistent: bool = True,
                    meta_only: bool = True) -> list[DynamoItem]:
        """基表 Scan + `entity` 過濾；預設只回實體本體（`SK == META`）。

        `entity` 的值等於 PK 前綴（00A §3.6），所以同一個起點的關係邊也帶同一個 `entity`，
        `scan_entity("RULE")` 會連 `APPLIED_TO#` 邊一起掃到。邊沒有模型欄位，直接
        `item_to_model` 會整筆 `ValidationError`，所以預設 `meta_only=True`，五個 `list_*`
        什麼都不用做就只看得到本體；唯一要傳 `meta_only=False` 的是 `get_steps`
        （STEP 沒有 `META` item）。過濾放在讀完所有分頁之後，不寫進 `FilterExpression`：
        一個請求只送一條 filter，而且空頁不早停的行為只由 `_paged` 負責。
        """
        rows = self._paged(self._table.scan, FilterExpression=Attr("entity").eq(entity),
                           ConsistentRead=consistent)
        if not meta_only:
            return rows
        return [row for row in rows if str(row["SK"]) == META]

    # --- 六個固定讀取 ---

    def get_steps(self, version_id: str) -> list[TutorialStep]:
        """一個版本的全部步驟，依 `number` 升序。

        STEP 沒有 metadata item——它的 item 本身就是 `REFERENCES#<FEATURE PK>` 邊，所以這是
        唯一要傳 `meta_only=False` 的呼叫點。`tutorial_version` 與 `number` 一律用
        `parse_step_pk`（`step_pk` 的反函式）從 PK 還原、`feature_id` 由邊的 `target` 還原：
        鍵是權威，item 上就算另外存了同名屬性也不會分岔（00A §3.6）。每一步的 PK 都不同，
        沒辦法用單一 PK Query 一次拿整版，設計 §10 已接受 MVP 對基表分頁 Scan 這個取捨；
        應有步驟數的權威是 S3 全文的 `parse_markdown().steps`，**不可以**為了省掉 Scan
        在 item 上加 `step_count`。
        """
        steps: list[TutorialStep] = []
        for item in self.scan_entity("STEP", meta_only=False):
            owner, number = parse_step_pk(str(item["PK"]))
            if owner != version_id:
                continue
            payload: DynamoItem = {**item, "tutorial_version": owner, "number": number,
                                   "feature_id": parse_pk(str(item["target"]))[1]}
            steps.append(item_to_model(payload, TutorialStep))
        return sorted(steps, key=lambda step: step.number)

    def list_feedback_of_version(self, version_id: str) -> list[Feedback]:
        """某版的全部回饋，依 ID 升序（設計 §10 六問之一）。

        `by_target` 候選只有鍵，而且同一個終點上還有 `SUPERSEDES`／`ASKS_ABOUT` 這些別的邊，所以要
        三重過濾（關係是 `REFERS_TO`、起點是 `FEEDBACK`、終點確實是這一版），再逐筆回基表
        一致讀取取得內容。GSI 只會落後基表、不會多出基表沒有的資料，所以候選讀不到本體
        代表資料不完整，必須明確失敗而不是安靜跳過。這裡用 `get_meta`（整筆重讀）而不是
        `item_to_model`，因為候選身上根本沒有內容。
        """
        target = version_pk(version_id)
        found: list[Feedback] = []
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

    def _scan_models[M: StrictModel](self, entity: str, model: type[M],
                                     key: Callable[[M], Any], **equals: str) -> list[M]:
        """`scan_entity` 預設值 + raw item 等值過濾 + `item_to_model` + 穩定排序。

        `equals` 直接比對 raw item 的屬性字串，不先轉 model：為了篩掉九成資料而建一堆物件
        沒有必要。`meta_only` 用預設的 `True`，所以同前綴的關係邊不會進來。
        """
        rows = [row for row in self.scan_entity(entity)
                if all(row.get(name) == value for name, value in equals.items())]
        return sorted((item_to_model(row, model) for row in rows), key=key)

    def list_views_of_version(self, version_id: str) -> list[TutorialView]:
        """某版的全部瀏覽紀錄，依時間再依 user 排序（設計 §10：VIEW 靠欄位掃描，不建邊）。"""
        return self._scan_models("VIEW", TutorialView, lambda view: (view.ts, view.user),
                                 tutorial_version=version_id)

    def list_tickets(self, project_id: str) -> list[Ticket]:
        """某個專案的全部工單，依 ID 升序；別的專案不入選。"""
        return self._scan_models("TICKET", Ticket, lambda ticket: ticket.id,
                                 project_id=project_id)

    def list_rules(self, status: RuleStatus | None = None) -> list[AuthoringRule]:
        """全部撰寫規則，依 `rule_id` 升序；`status` 有值時只留那個狀態。"""
        rules = self._scan_models("RULE", AuthoringRule, lambda rule: rule.rule_id)
        return rules if status is None else [rule for rule in rules if rule.status == status]

    def list_procs(self, domain: str, adapter: str) -> list[ProvenWorkflow]:
        """某個 domain＋adapter 的全部既有流程，依 signature 升序；兩個條件都要相等。"""
        return self._scan_models("PROC", ProvenWorkflow, lambda proc: proc.signature,
                                 domain=domain, adapter=adapter)

    # --- 5. 交易寫入（Phase 24 追加） ---

    @property
    def table_name(self) -> str:
        """交易 action 的 `TableName`；就是 `self._table.name`（00A §6.7）。"""
        name: str = self._table.name
        return name

    def transact_write(self, items: Sequence[Mapping[str, object]]) -> int | None:
        """一次送出 all-or-nothing 的 `TransactWriteItems`；**全部成功回 `None`**。

        `transact_write_items` 只存在於 **client**，所以這裡經 `self._table.meta.client`
        取得。**但值一律用原生 Python 值，不是 `{"S": ...}` 低階 AttributeValue**（00A §6.7
        與 Phase 24 §5 原本寫低階形式，與 boto3 實際行為不符，已在 Phase 24 文件更正）：
        `boto3.resource("dynamodb")` 會在**它自己的 client** 上註冊
        `dynamodb-attr-value-input`（`boto3/dynamodb/transform.py`），把所有 `AttributeValue`
        形狀的參數再序列化一次，所以傳 `{"S": "TUTORIAL#x"}` 會變成
        `{"M": {"S": {"S": "TUTORIAL#x"}}}`，moto 與真實 DynamoDB 都會拒絕。`self._table`
        永遠是 resource Table，它的 `meta.client` 永遠帶著這個轉換，所以整個 `Repository`
        只有一種寫法：原生 Python 值。

        回傳值是「**哪一個 action 的條件不符**」：
        - 全部成功 -> `None`
        - 任一 `ConditionalCheckFailed` -> 它在 `items` 裡的 index（`CancellationReasons`
          依 `TransactItems` 順序回報，取**第一個**不符的）
        - 其他取消原因（容量不足、同鍵衝突、內部錯誤…）-> `TransientError`，交 ASL Retry

        條件不符不是例外而是回傳值：呼叫端（`Publisher.commit`）要用它換算成「哪一篇、
        哪一個欄位」的可讀原因，而不是把整次執行變成失敗。真正的 `TransactionCanceledException`
        以外的 `ClientError` 一律原樣往外丟。
        """
        try:
            self._table.meta.client.transact_write_items(TransactItems=list(items))
        except ClientError as error:
            if error.response["Error"]["Code"] != "TransactionCanceledException":
                raise
            reasons: Any = error.response.get("CancellationReasons", [])
            for index, reason in enumerate(reasons):
                if reason.get("Code") == "ConditionalCheckFailed":
                    return index
            raise TransientError(f"transaction cancelled: {reasons}") from error
        return None

    # --- 6. 固定圖譜查詢（Phase 27 追加） ---

    def _meta_models[M: StrictModel](self, entity: str, model: type[M]) -> list[M]:
        """`scan_entity` 的 raw item -> 模型清單；**不排序**，排序由各查詢自己決定。

        `scan_entity` 的預設 `meta_only=True` 已經濾過一次邊，這裡仍然自己再濾一次
        `SK == META`：`entity` 等於 PK 前綴（00A §3.6），所以 `scan_entity("VERSION")` 的
        掃描範圍同時涵蓋 VERSION 本體與它的 `SUPERSEDES` 邊，哪天預設值變了、或有人改傳
        `meta_only=False`，邊就會被當成版本餵進 `item_to_model` 而整筆 `ValidationError`。
        與 `_scan_models` 的差別只有兩點：不接 `equals` 過濾、不排序，所以三個 Scan 型查詢
        可以各自套自己的順序（`version_sort_key`／`feature_id`／`slug`）。
        """
        rows = [item for item in self.scan_entity(entity) if str(item["SK"]) == META]
        return [item_to_model(item, model) for item in rows]

    def find_feature_by_name_or_alias(self, name: str) -> Feature | None:
        """先比 `name` 再比 `aliases`（設計 §7.4）；找不到回 `None`，**不做語意搜尋**。

        `name` 命中時直接採用，所以「某個 Feature 的舊名是另一個 Feature 的現名」不會誤判。
        alias 必須唯一（D07），同一字串命中兩個 Feature 的 alias 一律 `PermanentError`，
        不自行挑一個——挑錯會把改版寫到別篇教學上。掃描結果先依 `feature_id` 升序排好再比對，
        讓同名（name 撞名）時的回傳可重現。語意搜尋與建立 Feature 都不在這裡（Phase 49）。
        """
        features = sorted(self._meta_models("FEATURE", Feature),
                          key=lambda feature: feature.feature_id)
        exact = [feature for feature in features if feature.name == name]
        hits = exact or [feature for feature in features if name in feature.aliases]
        if not exact and len(hits) > 1:
            raise PermanentError(f"alias {name} 同時屬於 {len(hits)} 個 Feature")
        return hits[0] if hits else None

    def list_versions_of_tutorial(self, slug: str) -> list[TutorialVersion]:
        """某篇教學的**全部**版本，依版號升序（設計 §10 六問之一）。

        含歷史版與 `published_at=None` 的未發布版：索引頁只列已發布是 Phase 24 的責任，
        查詢層先把事實給齊。`VERSION#<slug>@v` 不是合法的 Query 鍵（PK 是完整值，不是前綴），
        所以照設計 §10 走基表分頁 Scan 再依 `slug` 篩選。排序一律經 `version_sort_key`，
        字典序會把 `@v10` 排在 `@v2` 前面。
        """
        versions = self._meta_models("VERSION", TutorialVersion)
        chosen = [version for version in versions if version.slug == slug]
        return sorted(chosen, key=lambda version: version_sort_key(version.version_id))

    def _is_current_published(self, version_id: str) -> bool:
        """這一版是不是「目前已發布版」：`current_version` 與 `published_at` 必須同時成立。

        只比 `current_version` 會把還沒發布的草稿當成目前版（設計 §7.4 的改版會寫到看不見的
        內容上）；只比 `published_at` 則會把歷史版一起算進來，改版就會分岔。兩個條件都用
        基表一致讀取取得，所以不受 GSI 落後影響。
        """
        slug, _ = version_sort_key(version_id)
        tutorial = self.get_tutorial(slug)
        if tutorial is None or tutorial.current_version != version_id:
            return False
        version = self.get_version(version_id)
        return version is not None and version.published_at is not None

    def find_current_published_steps_referencing(self, feature_id: str) -> list[TutorialStep]:
        """誰引用這個 Feature（設計 §10 六問之一）：**只回目前已發布版本的步驟**。

        兩條資料來源聯集，順序是「先基表、後 GSI」：

        - **B（基表，決定結果集合）**：`scan_entity("TUTORIAL")` 一致讀取每篇教學，取
          `current_version` 且 `published_at` 非空的那一版，再 `get_steps` 篩
          `feature_id`。這是設計 §10 要求的「改版前以基表一致讀取核對目前版的完整引用集合」，
          代價是每個目前已發布版各一次 `get_steps`。
        - **A（GSI，只補候選）**：`query_by_target` 的候選只留 `REFERENCES` 且起點是 `STEP#`
          的邊（排除 TICKET 的 `ASKS_ABOUT` 等別種關係），不是目前已發布版就跳過。

        為什麼要聯集：GSI 只有最終一致，剛寫入的邊可能還沒出現，只用 A 會錯判「沒有教學引用
        這個功能」而誤 KEEP。設計 §9.1 把步驟與引用放在同一筆 item，所以資料正常時 A 必然是
        B 的子集合，聯集不會多出東西；**A 多出 B 沒有的一筆就代表基表資料不完整**（例如邊少了
        `entity` 屬性而被 `scan_entity` 漏掉），照 Phase 08 的規則丟 `PermanentError`，
        不靜默跳過，也不在查詢裡順手補寫——補寫是 Phase 28 的事。

        基表核對只在本案「少量資料＋序列化教學寫入」的範圍內成立，**不是**跨併發寫入的快照，
        也不是大型站點的查詢設計（設計 §10 明載此取捨）。
        """
        target = feature_pk(feature_id)
        found: dict[tuple[str, int], TutorialStep] = {}
        for item in self.scan_entity("TUTORIAL"):
            if str(item["SK"]) != META:
                continue
            current = item_to_model(item, Tutorial).current_version
            if current is None or not self._is_current_published(current):
                continue
            for step in self.get_steps(current):
                if step.feature_id == feature_id:
                    found[(current, step.number)] = step
        for edge in self.query_by_target(target):
            pk = str(edge["PK"])
            relation, endpoint = parse_edge_sk(str(edge["SK"]))
            if relation != "REFERENCES" or parse_pk(pk)[0] != "STEP" or endpoint != target:
                continue
            version_id, number = parse_step_pk(pk)
            if (version_id, number) in found or not self._is_current_published(version_id):
                continue
            raise PermanentError(f"GSI 候選在基表讀不到對應步驟：{pk}")
        return [found[key] for key in sorted(found, key=lambda k: (version_sort_key(k[0]), k[1]))]

    def list_versions_applying_rule(self, rule_id: str) -> list[str]:
        """這條規則套用過哪些版本，依版號升序去重（設計 §10 六問之一）。

        從 RULE 起點的 `APPLIED_TO` 邊出發取候選，但**以 `VERSION.rules_applied` 為唯一權威**
        （D17）：邊存在而該版的 `rules_applied` 不含這條規則時不回傳，因為多餘邊會讓
        「規則套用次數」這個指標多計。邊指向已不存在的版本時只跳過——本 Phase 只讀，
        清理與投影重建是 Phase 28 的事。回的是 version_id 字串（不是模型），因為呼叫端
        （Phase 28、Phase 54）要的就是集合比對。
        """
        version_ids: set[str] = set()
        for edge in self.query_pk(rule_pk(rule_id), sk_prefix="APPLIED_TO#"):
            _, endpoint = parse_edge_sk(str(edge["SK"]))
            _, version_id = parse_pk(endpoint)
            version = self.get_version(version_id)
            if version is not None and rule_id in version.rules_applied:
                version_ids.add(version_id)
        return sorted(version_ids, key=version_sort_key)

    def find_active_tutorial_for_feature(self, feature_id: str) -> Tutorial | None:
        """這個 Feature 有沒有 active 教學（設計 §7.3，CREATE／KEEP 的判斷依據）。

        只看 `status == "active"`：即使 `current_version` 還是 `None`（尚待首次發布）也算
        已有教學（F12），`retired` 則不算，所以不會擋住 CREATE。走基表 Scan 而不是
        `ASKS_ABOUT` 邊，所以 Phase 40 還沒開始寫那條邊也能用。真的出現多篇時回 slug 升序
        第一筆，讓結果可重現；這裡不決定 CREATE／KEEP，只回事實（決定在 Phase 40）。
        """
        hits = self._meta_models("TUTORIAL", Tutorial)
        active = [tutorial for tutorial in hits
                  if tutorial.status == TutorialStatus.ACTIVE
                  and feature_id in tutorial.feature_ids]
        return min(active, key=lambda tutorial: tutorial.slug) if active else None
