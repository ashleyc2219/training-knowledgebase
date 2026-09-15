"""`training-kb-analytics` 的 Lambda 入口（00A D-56）。

這支 Lambda **不是**第四條教學 pipeline，也不進 Step Functions：維護者用 boto3 `invoke`
直接呼叫它，所以它沒有 Function URL。本 Phase 只認得 `action: "metrics"`；Phase 55 會在
`raise` 之前插入 `validate_rules` 分支，**不再動 CDK**（D-58）。

分派寫在接線之前：未知 `action` 必須在建立任何 boto3 資源前就丟 `PermanentError`，
單元測試才不需要 AWS 憑證就能跑這條路徑。`handler` 不 try／except——`PermanentError`
要原樣往外丟，呼叫端才看得到失敗原因。
"""

import importlib
from collections.abc import Mapping
from datetime import datetime
from typing import Any

import boto3

from training_kb.analytics.status_writer import apply_rule_status, record_evaluation
from training_kb.analytics.validation import (
    RuleEvaluation,
    SeedBatch,
    evaluate_batch,
    next_status,
)
from training_kb.analytics.version import metrics_action
from training_kb.clock import parse_iso
from training_kb.config import load_settings
from training_kb.errors import PermanentError
from training_kb.keys import rule_pk
from training_kb.models import AuthoringRule
from training_kb.repository import Repository

Wiring = tuple[Repository, frozenset[str], str]

_WIRING: Wiring | None = None

CATEGORY_RESOLVER = ("training_kb.ingress", "approved_categories")
"""Phase 43 的核定類別表在哪裡；見 `_approved_categories` 的延後解析。"""


def _approved_categories(repository: Repository) -> frozenset[str]:
    """取 Phase 43 的核定類別表；**Phase 43 尚未落地時退回空集合**。

    **本計畫選擇（2026-09-14）：** `approved_categories` 由 Phase 43 加進
    `training_kb.ingress`，與本 Phase 同屬 41–60 這一批但尚未落地。寫成模組層 import 會
    讓整支 `handlers/analytics.py` 連 import 都失敗（單元測試與雲端部署一起掛），所以這裡
    延後到 `_wiring()` 才用 `importlib` 解析：Phase 43 一落地就自動取到真的那一份，不需要
    任何人回來改這裡。退回值是**空集合**而不是抄一份 `DEFAULT_FEEDBACK_CATEGORIES`——
    複製 Phase 43 的契約常數會製造第二個權威，而空集合只讓 `negative_feedback_ids`
    暫時少認「類別命中」那一半（`rating <= 2` 那一半照常），是看得出來的降級。
    """
    module = importlib.import_module(CATEGORY_RESOLVER[0])
    resolver = getattr(module, CATEGORY_RESOLVER[1], None)
    if resolver is None:
        return frozenset()
    return frozenset(resolver(repository))


def _wiring() -> Wiring:
    """取得 repository、核定類別表與 `project_id`（模組層工廠，快取一次）。

    照 `training_kb.ingress._wiring`／`_build_wiring` 的既有範式：client 一律在這裡才建立，
    模組 import 時不碰網路；`boto3.resource` 帶 `region_name=settings.aws_region`，不靠
    shell 預設（全案固定 `us-east-1`）。`load_settings()` 不帶參數就會讀 `os.environ`。
    """
    global _WIRING
    if _WIRING is None:
        settings = load_settings()
        dynamodb = boto3.resource("dynamodb", region_name=settings.aws_region)
        s3 = boto3.resource("s3", region_name=settings.aws_region)
        repository = Repository(dynamodb.Table(settings.table_name),
                                s3.Bucket(settings.content_bucket))
        _WIRING = (repository, _approved_categories(repository), settings.project_id)
    return _WIRING


def _reset_wiring() -> None:
    """丟掉模組層快取，給測試用（與 `ingress._reset_wiring` 同一個理由）。正式程式不呼叫。"""
    global _WIRING
    _WIRING = None


# ---- Phase 55 ----


def _seed_batch(raw: object) -> SeedBatch:
    """把 event 裡的一筆批次還原成 `SeedBatch`；`approved_at` 走 ISO 字串。

    形狀不對一律 `PermanentError`（修正波：final review B 的 minor）：`SeedBatch(**raw)`
    對缺欄位／多欄位丟的是 `TypeError`、`parse_iso` 對壞字串丟 `ValueError`，兩者都不是
    `PermanentError`，呼叫端（維護者的 `lambda invoke`）看到的會是看不出原因的 runtime
    例外，也不符合本模組 docstring 承諾的「未知形狀原樣丟 `PermanentError`」。
    """
    if not isinstance(raw, Mapping):
        raise PermanentError(f"validate_rules 的每一筆 batch 都必須是物件：{type(raw).__name__}")
    row = dict(raw)
    try:
        approved_at: datetime | None = (parse_iso(str(row["approved_at"]))
                                        if row.get("approved_at") else None)
        return SeedBatch(**{**row, "approved_at": approved_at})
    except (TypeError, ValueError) as error:
        raise PermanentError(f"validate_rules 的 batch 欄位不合法：{error}") from error


def _approved_at_key(raw: object) -> str:
    """批次排序鍵：`approved_at` 的字串（缺值排最前）。形狀不對留給 `_seed_batch` 去報錯。"""
    value = raw.get("approved_at") if isinstance(raw, Mapping) else None
    return str(value) if value else ""


def validate_rules_action(event: dict[str, Any], *, repository: Repository,
                          approved: frozenset[str]) -> dict[str, Any]:
    """`action: "validate_rules"`：評估批次、寫證據檔，再由唯一寫入者落狀態。

    批次先依 `approved_at` **升序**排序，`next_status` 的「最新一批」才有確定意義。
    `conflict` 固定傳 `None`：衝突判定要由呼叫端先取得 `ConflictJudgement` 並通過
    `validated_conflict`，這個 action **不自行呼叫模型**（O5 BLOCKED，也非本 Phase 職責）。

    `approved` 是 Phase 43 的**回饋類別**核定表（`_approved_categories`），與批次的
    `approved_by` 無關；未核定的批次會被 `evaluate_batch` 判成 `undecidable`，
    `next_status` 就不會動狀態，`apply_rule_status` 也不會被呼叫。

    **呼叫端義務（本計畫選擇 2026-09-15，修正波：final review B#4）：一次 invoke 要帶上
    這條規則的完整決定性歷史。** `next_status` 的兩條判定都看「清單的最後兩筆」
    （VAL Rule 5／6 的「連續兩批未改善且不重疊」與「最新一批 improved」），而本 action
    只看**這一次 event 帶進來的** `batches`。所以把同一條規則的兩個批次拆成兩次 invoke，
    第二次的清單長度是 1，`_two_unimproved` 永遠回 `False`，規則**永遠不會退役**。

    為什麼不回頭讀 `record_evaluation` 寫下的證據檔（controller 裁決 10 的「較好版本」）：

    ```text
    1 沒有前綴列舉  `Repository` 只有 get_object／put_object／object_exists，沒有
                    list_objects；要讀回同一條規則的全部批次得先知道每個 batch_id。
    2 排不出順序    證據檔的內容是 asdict(RuleEvaluation)，**沒有** approved_at；
                    而「最新一批」的定義正是依 approved_at 升序的最後一筆。
    ```

    兩件事都要動到 `Repository` 與證據檔格式（跨 Phase 的介面變更），超出修正波的範圍，
    所以照裁決 10 的後備做法：把義務寫進 docstring 並用測試釘住這個限制
    （`tests/unit/test_rule_status_writer.py::test_validate_rules_only_sees_the_batches_in_this_event`）。

    `event` 形狀不對一律 `PermanentError`，不讓 `KeyError`／`TypeError` 漏出去。
    """
    batches = event.get("batches")
    if not isinstance(event.get("now"), str) or not isinstance(batches, list):
        raise PermanentError("validate_rules 需要字串 now 與陣列 batches")
    try:
        now = parse_iso(str(event["now"]))
    except ValueError as error:
        raise PermanentError(f"validate_rules 的 now 不是合法的 ISO 時間：{error}") from error
    by_rule: dict[str, list[RuleEvaluation]] = {}
    for raw in sorted(batches, key=_approved_at_key):
        batch = _seed_batch(raw)
        evaluation = evaluate_batch(batch, approved=approved, repository=repository)
        record_evaluation(evaluation, repository=repository)
        by_rule.setdefault(batch.rule_id, []).append(evaluation)
    results: list[dict[str, Any]] = []
    for rule_id, evaluations in sorted(by_rule.items()):
        rule = repository.get_meta(rule_pk(rule_id), AuthoringRule)
        if rule is None:
            raise PermanentError(f"找不到規則：{rule_id}")
        target = next_status(rule.status, evaluations, None)
        if target is not rule.status:
            apply_rule_status(rule_id, target, repository=repository, now=now)
        results.append({"rule_id": rule_id, "status": target.value,
                        "verdicts": [item.verdict for item in evaluations]})
    return {"action": "validate_rules", "results": results}


def handler(event: dict[str, Any], context: object) -> dict[str, Any]:
    """`training-kb-analytics` 的入口；認得 `metrics`（P54）與 `validate_rules`（P55）。"""
    action = str(event.get("action"))
    if action == "metrics":
        repository, approved, project_id = _wiring()
        return metrics_action(event, repository=repository,
                              approved=approved, project_id=project_id)
    if action == "validate_rules":
        repository, approved, _ = _wiring()
        return validate_rules_action(event, repository=repository, approved=approved)
    raise PermanentError(f"未知的 analytics action：{action!r}")
