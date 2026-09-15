"""Phase 43：回饋類別判定（核定表只讀、四條分支、呼叫次數與 prompt 不可信分區）。

每個測試的 docstring 寫 Given／When／Then。**O5 BLOCKED**：本檔全部用 `tests/unit/conftest.py`
的假 `Writer`（`fake_writer` fixture），綠燈只代表**決策邏輯**正確，**不代表** Bedrock 可用；
真實 AWS 上這個節點會走 `PermanentError → Catch → PipelineFailed`（見報告 §7）。

器材：`FakeRepository` 只實作 `get_meta_item`／`put_meta_item` 兩個原語（`CONFIG#` 不走
Pydantic 模型，00A §3.6），並把每次讀寫記下來——「核定表全程沒有被寫入」是本階段的停止點，
要有東西可以斷言。moto 上的真表行為由 `tests/integration/test_fixed_import.py` 負責。
"""

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

import pytest

from training_kb.ingress import (
    DEFAULT_FEEDBACK_CATEGORIES,
    FEEDBACK_CATEGORIES_PK,
    PENDING_CATEGORY,
    _settle,
    approved_categories,
)

NOW = datetime(2026, 9, 14, 3, 0, tzinfo=UTC)
CONFIGURED = ["找不到按鈕", "缺少資訊", "步驟順序錯誤"]


class FakeRepository:
    """記憶體版 `Repository`：只有 `CONFIG#` 這對原語，形狀照 P10。

    `put_meta_item` 存在只是為了讓「本階段沒有任何寫入路徑」可以被斷言——產品程式**不得**
    呼叫它寫 `CONFIG#feedback_categories`（設定只由維護者受控匯入）。
    """

    def __init__(self, items: Mapping[str, Mapping[str, Any]] | None = None) -> None:
        self.items: dict[str, dict[str, Any]] = {
            pk: dict(attrs) for pk, attrs in (items or {}).items()}
        self.reads: list[str] = []
        self.writes: list[str] = []

    def get_meta_item(self, pk: str) -> dict[str, Any] | None:
        self.reads.append(pk)
        item = self.items.get(pk)
        return None if item is None else dict(item)

    def put_meta_item(self, pk: str, attributes: Mapping[str, Any], *,
                      create_only: bool = True) -> bool:
        self.writes.append(pk)
        if create_only and pk in self.items:
            return False
        self.items[pk] = dict(attributes)
        return True


def config_item(categories: Any) -> dict[str, dict[str, Any]]:
    """`put_meta_item("CONFIG#feedback_categories", {"categories": [...]})` 之後的固定形狀。

    `SK`／`entity`／`_revision` 是那支原語自己補的，所以設定 item 一定長這樣。
    """
    return {FEEDBACK_CATEGORIES_PK: {"PK": FEEDBACK_CATEGORIES_PK, "SK": "META",
                                     "entity": "CONFIG", "_revision": 1,
                                     "categories": categories}}


@pytest.fixture
def empty_repo() -> FakeRepository:
    """完全沒有 `CONFIG#feedback_categories` 的表。"""
    return FakeRepository()


@pytest.fixture
def configured_repo() -> FakeRepository:
    """維護者已經匯入三類的表（多一個「步驟順序錯誤」）。"""
    return FakeRepository(config_item(CONFIGURED))


# --- Task 1：核定類別表只讀與未知值收斂 ------------------------------------------


def test_default_categories_are_used_when_config_item_is_absent(
        empty_repo: FakeRepository) -> None:
    """Given 沒有設定 item／When 讀核定表／Then 回初始兩類，而且讀的是那個 PK。"""
    assert approved_categories(empty_repo) == frozenset({"找不到按鈕", "缺少資訊"})
    assert approved_categories(empty_repo) == DEFAULT_FEEDBACK_CATEGORIES
    assert empty_repo.reads == [FEEDBACK_CATEGORIES_PK, FEEDBACK_CATEGORIES_PK]


def test_configured_categories_replace_the_default(configured_repo: FakeRepository) -> None:
    """Given 維護者匯入了三類／When 讀核定表／Then 以設定為準，預設兩類不再是唯一答案。"""
    approved = approved_categories(configured_repo)
    assert "步驟順序錯誤" in approved
    assert approved == frozenset(CONFIGURED)


def test_reading_the_table_never_writes_it(configured_repo: FakeRepository) -> None:
    """Given 任何一次讀取／When 讀完／Then 一次 `put_meta_item` 都沒有（本階段只讀）。"""
    approved_categories(configured_repo)
    approved_categories(FakeRepository())
    assert configured_repo.writes == []


@pytest.mark.parametrize("categories", [None, "找不到按鈕", [], ["", "   "], 3])
def test_broken_config_shapes_fall_back_to_the_defaults(categories: Any) -> None:
    """Given `categories` 缺欄位／非 list／空 list／全空字串／數字／When 讀／Then 退回預設兩類。

    **不得回空集合**：Phase 44 的同類計數會整批歸零，錯誤設定會變成「沒有弱教學」。
    """
    attrs = config_item(categories)
    if categories is None:
        del attrs[FEEDBACK_CATEGORIES_PK]["categories"]
    assert approved_categories(FakeRepository(attrs)) == DEFAULT_FEEDBACK_CATEGORIES


def test_unknown_checkbox_value_settles_to_pending(empty_repo: FakeRepository) -> None:
    """Given 核定表／When `_settle` 收斂三種值／Then 未核定→待分類、空值→None、核定值原樣。"""
    approved = approved_categories(empty_repo)
    assert _settle("介面太醜", approved) == "待分類"
    assert _settle("  ", approved) is None
    assert _settle(None, approved) is None
    assert _settle("缺少資訊", approved) == "缺少資訊"


def test_settle_keeps_pending_itself_and_trims_whitespace(empty_repo: FakeRepository) -> None:
    """Given `待分類` 本身與前後有空白的核定值／When `_settle`／Then 都不再被降級一次。

    `待分類` 不是核定類別（設計 §12.1 不算負面），但它是保留值：再收斂一次仍然是它。
    """
    approved = approved_categories(empty_repo)
    assert _settle(PENDING_CATEGORY, approved) == PENDING_CATEGORY
    assert _settle("  缺少資訊  ", approved) == "缺少資訊"
