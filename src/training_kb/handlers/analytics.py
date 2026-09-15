"""`training-kb-analytics` 的 Lambda 入口（00A D-56）。

這支 Lambda **不是**第四條教學 pipeline，也不進 Step Functions：維護者用 boto3 `invoke`
直接呼叫它，所以它沒有 Function URL。本 Phase 只認得 `action: "metrics"`；Phase 55 會在
`raise` 之前插入 `validate_rules` 分支，**不再動 CDK**（D-58）。

分派寫在接線之前：未知 `action` 必須在建立任何 boto3 資源前就丟 `PermanentError`，
單元測試才不需要 AWS 憑證就能跑這條路徑。`handler` 不 try／except——`PermanentError`
要原樣往外丟，呼叫端才看得到失敗原因。
"""

import importlib
from typing import Any

import boto3

from training_kb.analytics.version import metrics_action
from training_kb.config import load_settings
from training_kb.errors import PermanentError
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


def handler(event: dict[str, Any], context: object) -> dict[str, Any]:
    """`training-kb-analytics` 的入口；本 Phase 只認得 `action: "metrics"`。"""
    action = str(event.get("action"))
    if action == "metrics":
        repository, approved, project_id = _wiring()
        return metrics_action(event, repository=repository,
                              approved=approved, project_id=project_id)
    raise PermanentError(f"未知的 analytics action：{action!r}")
