"""單表讀寫：把 DynamoDB 的 `PK`／`SK`／`entity`／`_revision` 藏在這裡，領域模型不感知物理欄位。

九個實體有 metadata item（SK 固定是 `META`），`TutorialStep` 沒有——它本身就是
`REFERENCES#<FEATURE PK>` 邊（設計 §9.1），所以 `put_meta(TutorialStep(...))` 明確拒絕。
建立走 `attribute_not_exists(PK)`，更新走 `_revision` 的 compare-and-swap；兩種條件都在
AWS 端判斷，不是「先查再寫」。衝突一律 `CoordinationError`（**不是** `TransientError`，
呼叫端不得自動重試）。

檔案分成四段，Phase 07／08／10 直接接在後面，不必改動前面幾段：
1. 型別別名與保留屬性
2. 實體 → PK 的分派
3. Decimal codec（DynamoDB 只收 `Decimal`，不收 `float`）
4. `Repository`：metadata CRUD、`revision_of` 與四個具名 getter
"""

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


# --- 3. Decimal codec --------------------------------------------------------


def _encode(value: object) -> object:
    """`float` -> `Decimal(str(value))`；用 `str` 才不會把二進位浮點誤差一起寫進表。"""
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
        revision = 1
        arguments: dict[str, object] = {"ConditionExpression": "attribute_not_exists(PK)"}
        if not create_only:
            current = self._revision_or_none(pk)
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
            if error.response["Error"]["Code"] == "ConditionalCheckFailedException":
                raise CoordinationError(
                    f"metadata already exists or changed since read: {pk}") from error
            raise

    def _revision_or_none(self, pk: str) -> int | None:
        """讀目前的 `_revision`；item 不存在回 `None`。`revision_of` 與受控覆寫共用它。"""
        response = self._table.get_item(Key={"PK": pk, "SK": META}, ConsistentRead=True)
        item = response.get("Item")
        return None if item is None else int(item["_revision"])

    # --- metadata 讀取 ---

    def get_meta(self, pk: str, model: type[T], *, consistent: bool = True) -> T | None:
        response = self._table.get_item(Key={"PK": pk, "SK": META}, ConsistentRead=consistent)
        item = response.get("Item")
        if item is None:
            return None
        payload = {k: _decode(v) for k, v in item.items() if k not in RESERVED_ATTRS}
        return model.model_validate(payload)

    def get_tutorial(self, slug: str) -> Tutorial | None:
        return self.get_meta(tutorial_pk(slug), Tutorial)

    def get_version(self, version_id: str) -> TutorialVersion | None:
        return self.get_meta(version_pk(version_id), TutorialVersion)

    def get_feature(self, feature_id: str) -> Feature | None:
        return self.get_meta(feature_pk(feature_id), Feature)

    def get_proc(self, signature: str) -> ProvenWorkflow | None:
        return self.get_meta(proc_pk(signature), ProvenWorkflow)
