"""操作紀錄（operation ledger）：同一個 `operation_id` 只能被建立一次。

`OperationCoordinator` 是**唯一**寫 `OPS#<operation_id>` item 的入口。`accept` 直接送
`put_meta_item(..., create_only=True)`（DynamoDB 端的 `attribute_not_exists`），
沒有「先查再寫」的中間狀態；條件失敗才回頭讀既有紀錄回 `duplicate`。去重靠「這筆紀錄
存在」達成，**不是**靠 TTL——TTL 是容量管理，既不保證準時也不保證保留（設計 §14.1）。

`duplicate` 只代表「這個 `operation_id` 被接受過」，不代表它要寫的東西已經寫完：
目標物件不存在時呼叫端要沿用同一個 `operation_id` 補寫（**續跑**，00A D-45）。
判斷物件在不在一律由呼叫端做，ledger 不猜、也不反過來依賴業務模組。

大小分工固定：小欄位（狀態與 ref）進 DynamoDB item，大內容（正規化輸入、模型輸出）
進私有 S3 `operations/<operation_id>/<name>.json`，由呼叫端用 `if_none_match=True` 寫，
item 只存 ref（設計 §9.3、§14.2）。

**本模組不宣稱 FIFO。** 條件寫入只證明同一個 `operation_id` 不會被建立第二次；接受順序
（`accept_seq`）、lease 與程序重啟是 Phase 11 的事，在那份證據出來前 O2 一律標未通過。

檔案分成三段：
1. 型別與三個 dataclass
2. item <-> record 的 codec（`_to_item`／`_from_item`）
3. `OperationCoordinator`
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, cast, get_args

from training_kb.clock import parse_iso, to_iso
from training_kb.errors import CoordinationError
from training_kb.keys import ops_pk
from training_kb.repository import DynamoItem, DynamoValue, Repository

# --- 1. 型別與三個 dataclass -------------------------------------------------

OperationKind = Literal["ticket", "release", "feedback", "view",
                        "ticket-analysis", "release-update", "feedback-review", "analytics"]
OperationStatus = Literal["accepted", "normalized", "started", "done", "failed"]

KINDS: frozenset[str] = frozenset(get_args(OperationKind))
STATUSES: frozenset[str] = frozenset(get_args(OperationStatus))
"""`_from_item` 的白名單。表裡讀回來的是純字串，要先核對才能收斂成 Literal；
沒有 `running`（用 `started`），寫錯的值一律在載入時就明確失敗（00A D-08）。"""


@dataclass(frozen=True)
class AcceptOperation:
    """一次接受請求。`now` 由呼叫端傳，深層程式不讀系統時鐘（00A §3.5）。"""

    operation_id: str
    kind: OperationKind
    canonical_id: str
    project_id: str
    now: datetime


@dataclass(frozen=True)
class OperationRecord:
    """`OPS#` item 的領域形狀。

    `model_output_refs` 是 `tuple`（frozen dataclass 要可雜湊），存進表時轉 `list`。
    沒有 `result_ref`：輸入走 `input_ref`、執行走 `execution_arn`（00A D-08）。
    Phase 11 會在 `accepted_at` 之前追加 `accept_seq: int | None`，其餘欄位不改名；
    `_from_item` 只讀認得的屬性，所以那時的舊 item 不必做資料遷移。
    """

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
    """`accept` 的結果。刻意沒有 `is_duplicate`，呼叫端一律比對 `status`（00A D-08）。"""

    status: Literal["accepted", "duplicate"]
    operation_id: str
    record: OperationRecord


# --- 2. item <-> record 的 codec ---------------------------------------------


def _initial_record(request: AcceptOperation) -> OperationRecord:
    """剛接受的紀錄：四個請求欄位＋`status="accepted"`，其餘一律 `None` 或 `()`。"""
    return OperationRecord(
        operation_id=request.operation_id,
        kind=request.kind,
        canonical_id=request.canonical_id,
        project_id=request.project_id,
        status="accepted",
        input_ref=None,
        execution_arn=None,
        version_id=None,
        model_output_refs=(),
        proc_sample_signature=None,
        error=None,
        retryable=None,
        accepted_at=request.now,
        updated_at=request.now,
    )


def _to_item(record: OperationRecord) -> dict[str, DynamoValue]:
    """record -> 可寫入的屬性表。`PK`／`SK`／`entity`／`_revision` 由 `put_meta_item` 補，
    這裡一個保留屬性都不能出現（00A §3.6）。"""
    return {
        "operation_id": record.operation_id,
        "kind": record.kind,
        "canonical_id": record.canonical_id,
        "project_id": record.project_id,
        "status": record.status,
        "input_ref": record.input_ref,
        "execution_arn": record.execution_arn,
        "version_id": record.version_id,
        "model_output_refs": list(record.model_output_refs),
        "proc_sample_signature": record.proc_sample_signature,
        "error": record.error,
        "retryable": record.retryable,
        "accepted_at": to_iso(record.accepted_at),
        "updated_at": to_iso(record.updated_at),
    }


def _text(item: DynamoItem, field: str) -> str | None:
    value = item.get(field)
    if value is None or isinstance(value, str):
        return value
    raise CoordinationError(f"operation attribute {field} is not a string: {value!r}")


def _required_text(item: DynamoItem, field: str) -> str:
    value = _text(item, field)
    if value is None:
        raise CoordinationError(f"operation attribute {field} is missing")
    return value


def _refs(item: DynamoItem) -> tuple[str, ...]:
    value = item.get("model_output_refs")
    if value is None:
        return ()
    if isinstance(value, list) and all(isinstance(ref, str) for ref in value):
        return tuple(cast(list[str], value))
    raise CoordinationError(f"operation attribute model_output_refs is not a ref list: {value!r}")


def _flag(item: DynamoItem, field: str) -> bool | None:
    value = item.get(field)
    if value is None or isinstance(value, bool):
        return value
    raise CoordinationError(f"operation attribute {field} is not a boolean: {value!r}")


def _revision(item: DynamoItem) -> int:
    """同一次 `get_meta_item` 讀到的 `_revision` 直接當 `expected_revision`（00A §3.6 的
    唯一例外）：少一次讀取就少一個競態視窗。`bool` 不算（`True` 不是版本號）。"""
    value = item.get("_revision")
    if isinstance(value, bool) or not isinstance(value, int):
        raise CoordinationError(f"operation item has no usable revision: {value!r}")
    return value


def _from_item(item: DynamoItem) -> OperationRecord:
    """`_to_item` 的反函式；時間用 `parse_iso` 還原，只讀認得的屬性。"""
    kind = _required_text(item, "kind")
    status = _required_text(item, "status")
    if kind not in KINDS:
        raise CoordinationError(f"unknown operation kind: {kind!r}")
    if status not in STATUSES:
        raise CoordinationError(f"unknown operation status: {status!r}")
    return OperationRecord(
        operation_id=_required_text(item, "operation_id"),
        kind=cast(OperationKind, kind),
        canonical_id=_required_text(item, "canonical_id"),
        project_id=_required_text(item, "project_id"),
        status=cast(OperationStatus, status),
        input_ref=_text(item, "input_ref"),
        execution_arn=_text(item, "execution_arn"),
        version_id=_text(item, "version_id"),
        model_output_refs=_refs(item),
        proc_sample_signature=_text(item, "proc_sample_signature"),
        error=_text(item, "error"),
        retryable=_flag(item, "retryable"),
        accepted_at=parse_iso(_required_text(item, "accepted_at")),
        updated_at=parse_iso(_required_text(item, "updated_at")),
    )


# --- 3. OperationCoordinator -------------------------------------------------


class OperationCoordinator:
    """`OPS#` item 的唯一寫入者。Phase 11 會在同一個 class 上追加 `accept_seq` 與
    `acquire_lease`／`release_lease`／`next_sequence`，現有方法不改名。"""

    def __init__(self, repository: Repository) -> None:
        self._repository = repository

    # --- 接受與載入 ---

    def accept(self, request: AcceptOperation) -> Acceptance:
        """條件寫入 `OPS#<operation_id>`；只有三個分支，沒有「查一下再寫」。

        條件失敗卻讀不到既有 item 是資料不一致，不是重送：安靜地重建一筆會讓同一事件
        產生兩條版本鏈，所以一律 `CoordinationError`（設計 §14.1）。
        """
        record = _initial_record(request)
        pk = ops_pk(request.operation_id)
        if self._repository.put_meta_item(pk, _to_item(record), create_only=True):
            return Acceptance("accepted", request.operation_id, record)
        existing = self.load(request.operation_id)
        if existing is None:
            raise CoordinationError(f"operation item is missing after conflict: {pk}")
        return Acceptance("duplicate", request.operation_id, existing)

    def load(self, operation_id: str) -> OperationRecord | None:
        item = self._repository.get_meta_item(ops_pk(operation_id))
        return None if item is None else _from_item(item)

    # --- 進度 ---

    def record_normalized(self, operation_id: str, input_ref: str) -> None:
        """記下正規化輸入的 S3 key。物件本身由呼叫端用 `if_none_match=True` 另外寫入。"""
        self._change(operation_id, {"input_ref": input_ref})

    def record_execution(self, operation_id: str, execution_arn: str) -> None:
        self._change(operation_id, {"execution_arn": execution_arn})

    def record_version(self, operation_id: str, version_id: str) -> None:
        self._change(operation_id, {"version_id": version_id})

    def record_model_output(self, operation_id: str, output_ref: str) -> None:
        """附加一筆模型輸出 ref；同一個 ref 不重複附加，重送才不會多算一次輸出。"""
        item = self._existing(operation_id)
        refs = _refs(item)
        if output_ref in refs:
            return
        self._write(operation_id, {"model_output_refs": [*refs, output_ref]}, item)

    def record_proc_sample(self, operation_id: str, signature: str) -> bool:
        """第一次回 `True`，同一個 operation 之後一律回 `False`。

        Phase 35 靠這個 `False` 分支避免同一次邏輯操作重複累加 `success_count`。
        """
        item = self._existing(operation_id)
        if item.get("proc_sample_signature") is not None:
            return False
        self._write(operation_id, {"proc_sample_signature": signature}, item)
        return True

    # --- 終點 ---

    def complete(self, operation_id: str, *, now: datetime) -> None:
        self._change(operation_id, {"status": "done", "updated_at": to_iso(now)})

    def fail(self, operation_id: str, error: str, retryable: bool, *, now: datetime) -> None:
        """記下失敗與可否重試；**要不要重試由呼叫端依 `retryable` 決定**，不是 ledger 決定。"""
        self._change(operation_id, {"status": "failed", "error": error,
                                    "retryable": retryable, "updated_at": to_iso(now)})

    # --- 私有 ---

    def _existing(self, operation_id: str) -> DynamoItem:
        item = self._repository.get_meta_item(ops_pk(operation_id))
        if item is None:
            raise CoordinationError(f"unknown operation: {operation_id}")
        return item

    def _write(self, operation_id: str, changes: Mapping[str, DynamoValue],
               item: DynamoItem) -> None:
        """用**手上這一筆** item 的 `_revision` 做 compare-and-swap，不再讀一次。"""
        self._repository.update_meta(ops_pk(operation_id), changes,
                                     expected_revision=_revision(item))

    def _change(self, operation_id: str, changes: Mapping[str, DynamoValue]) -> None:
        self._write(operation_id, changes, self._existing(operation_id))
