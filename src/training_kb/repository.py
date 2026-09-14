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

from collections.abc import Mapping
from decimal import Decimal
from typing import Any, TypeVar

from botocore.exceptions import ClientError

from training_kb.errors import CoordinationError, PermanentError
from training_kb.keys import (
    META,
    feature_pk,
    feedback_pk,
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

T = TypeVar("T", bound=StrictModel)

RESERVED_ATTRS = frozenset({"PK", "SK", "target", "entity", "_revision"})
"""item 上唯一允許的非模型屬性（00A §3.6）；只能由 `Repository` 自己算，呼叫端不得傳、不得更新。
`target` 只有 Phase 07 的關係邊會用到，一起列進來讓整套只有一份定義。"""


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

    def __init__(self, table: object) -> None:
        self._table: Any = table

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
