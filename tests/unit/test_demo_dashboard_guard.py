"""Phase 58 Task 4：橫幅標示護欄與 `demo/dashboard.py` 的原始碼守門。

Given 展示頁是維護者本機的**唯讀**工具
When 檢查它的原始碼
Then 它只 import `streamlit` 與 `demo.view_model`、不含任何業務邏輯、沒有寫入呼叫，
     也沒有任何金鑰字面值。

**本檔刻意不 import streamlit，也不 import `demo.dashboard`。**
兩個理由：(1) `uv run pytest -W error` 不得有任何 warning，第三方套件 import 時的
DeprecationWarning 會直接把整套測試打紅；(2) `demo/dashboard.py` 是 Streamlit 腳本，
import 它等於在測試裡執行整支腳本。守門一律用 `ast` 與原始碼字串做。
"""

import ast
from pathlib import Path

import pytest

from demo.view_model import (
    FALLBACK_NOTE,
    GATE_NOTE,
    PENDING_APPROVAL,
    SYNTHETIC_NOTICE,
    TIME_LABELS,
    Banner,
    render_banner,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
DEMO_DIR = REPO_ROOT / "demo"
DASHBOARD = DEMO_DIR / "dashboard.py"
BATCH = "demo-seed-01"

BANNED_CALLS = ("put_item", "update_item", "transact_write_items", "put_meta",
                "put_edge", "delete_item", "aws_secret", "AKIA")
"""展示頁不得出現的寫入呼叫與金鑰字面值（Phase 58 §7 Task 4）。"""

ALLOWED_IMPORTS = {"streamlit", "demo.view_model"}
"""唯二允許的 import；多一個就代表業務邏輯開始往展示頁滲透。"""


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _tree(path: Path) -> ast.Module:
    return ast.parse(_source(path), filename=str(path))


def _imported_modules(tree: ast.Module) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


# --- 1. 橫幅：合成資料、批次、時間標示、gate，備援要標成備援 --------------------


def test_banner_always_marks_synthetic_and_batch() -> None:
    """Given 即時執行 When 畫橫幅 Then 同時有合成標示、批次與「即時執行」。"""
    text = render_banner(Banner(batch=BATCH, time_mode="live", fallback_reason=None))
    assert SYNTHETIC_NOTICE in text and BATCH in text and "即時執行" in text
    assert FALLBACK_NOTE not in text


def test_banner_marks_fallback_as_pre_run_result_with_the_live_failure() -> None:
    """Given 現場失敗改用備援 When 畫橫幅 Then 明寫「預先執行結果」與本次失敗原因。"""
    fallback = render_banner(Banner(batch=BATCH, time_mode="live",
                                    fallback_reason="Bedrock 逾時"))
    assert "預先執行結果" in fallback and "Bedrock 逾時" in fallback


def test_banner_separates_live_from_simulated_time() -> None:
    """Given 兩種 `time_mode` When 畫橫幅 Then 兩個標示不同，不會混成同一組成效。"""
    live = render_banner(Banner(batch=BATCH, time_mode="live", fallback_reason=None))
    simulated = render_banner(Banner(batch=BATCH, time_mode="simulated", fallback_reason=None))
    assert TIME_LABELS["live"] in live and TIME_LABELS["simulated"] in simulated
    assert live != simulated


def test_banner_shows_gate_status_instead_of_pretending_everything_is_fine() -> None:
    """Given O5 BLOCKED 與 O7 未核定 When 畫橫幅 Then 兩個 gate 都寫出來，且沒有「已通過」。"""
    text = render_banner(Banner(batch=BATCH, time_mode="simulated", fallback_reason=None))
    assert GATE_NOTE in text
    assert "BLOCKED" in text and PENDING_APPROVAL in text
    assert "已通過" not in text


# --- 2. dashboard.py 的原始碼守門 ---------------------------------------------


def test_dashboard_never_writes_dynamodb_or_embeds_keys() -> None:
    """Given 展示頁原始碼 When 搜尋寫入呼叫與金鑰 Then 一個都沒有。"""
    source = _source(DASHBOARD)
    for banned in BANNED_CALLS:
        assert banned not in source, banned


def test_dashboard_only_imports_streamlit_and_the_view_model() -> None:
    """Given 展示頁 When 看它 import 什麼 Then 只有 `streamlit` 與 `demo.view_model`。"""
    assert _imported_modules(_tree(DASHBOARD)) == ALLOWED_IMPORTS


def test_dashboard_holds_no_business_logic() -> None:
    """Given 展示頁 When 走訪 AST Then 沒有函式、類別，也沒有任何乘除法（公式只有一份）。"""
    tree = _tree(DASHBOARD)
    defined = [node for node in ast.walk(tree)
               if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)]
    assert defined == []
    operators = [node.op for node in ast.walk(tree) if isinstance(node, ast.BinOp)]
    assert not any(isinstance(op, ast.Div | ast.Mult | ast.FloorDiv) for op in operators)
    calls = {node.func.id for node in ast.walk(tree)
             if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
    assert not calls & {"sum", "round", "len", "sorted"}


def test_dashboard_wording_is_pending_approval_not_passed() -> None:
    """Given O7 未核定 When 讀展示頁文案 Then 寫「待維護者核定」，沒有「O7 已通過」。"""
    source = _source(DASHBOARD)
    assert PENDING_APPROVAL in source or "o7_line" in source
    for banned in ("O7 已通過", "雲端驗收已通過", "O5 已開通"):
        assert banned not in source


# --- 3. demo/ 全域：指標公式不得有第二份實作 ------------------------------------


def test_demo_package_has_no_second_metric_formula() -> None:
    """Given `demo/*.py` When 搜尋十四天窗口與自己算平均的樣式 Then 一個都沒有。

    `rg -n "days=14|sum\\(.*\\)/len\\(" demo/` 的程式版：公式一律轉呼
    `training_kb.analytics`（Phase 53／54），Demo 這一側只做顯示。
    """
    hits: list[str] = []
    for path in sorted(DEMO_DIR.rglob("*.py")):
        for number, line in enumerate(_source(path).splitlines(), start=1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if "days=14" in line or ("/len(" in line.replace(" ", "") and "sum(" in line):
                hits.append(f"{path.relative_to(REPO_ROOT)}:{number}: {stripped}")
    assert hits == []


@pytest.mark.parametrize("folder", ["unit", "integration"])
def test_no_test_module_imports_the_streamlit_dashboard(folder: str) -> None:
    """Given 整套測試 When 檢查 import Then 沒有任何測試 import `demo.dashboard`。

    import 它等於在 pytest 裡執行整支 Streamlit 腳本，而且會把 streamlit 的第三方
    warning 帶進 `-W error` 的 gate。
    """
    offenders = [path.name for path in sorted((REPO_ROOT / "tests" / folder).rglob("*.py"))
                 if "demo.dashboard" in _imported_modules(_tree(path))]
    assert offenders == []
