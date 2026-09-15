"""`TKB_FAULT` 故障注入切點的基本行為（`src/training_kb/faults.py`）。

**本檔的第一片由 Phase 41 建立，owner 仍是 Phase 59**（00A §3.2、§3.3）：P41 只需要
`faults.py` 這支檔存在、五個切點名稱定案、開關語意固定，好讓 P41 在雲端證明
「注入的失敗要丟 `TransientError` 本身才命中 ASL 的第一條 retrier」。**P41 不在
`content.py`／`publishing.py`／`ingress.py` 插入任何 `maybe_fail`**，那是 P59 Task 1，
P59 的「每個切點名稱在三個檔各恰好出現一次」那條測試因此完全不受影響。
"""

import ast
from pathlib import Path

import pytest

from training_kb.errors import PermanentError, TransientError
from training_kb.faults import FAULT_POINTS, InjectedFault, active_fault, maybe_fail

WIRED_FILES = ("content.py", "publishing.py", "ingress.py")
"""五個切點只能落在這三支檔（Phase 59 §7 Task 1 Step 4 的插入表）。"""


def test_the_five_fault_points_are_fixed() -> None:
    """Given 00A 第 1230 列，Then 五個切點名稱一個不多一個不少、順序固定。"""
    assert FAULT_POINTS == ("s3_after_md", "ddb_after_version", "publish_before_transact",
                            "publish_after_transact_before_site", "start_execution")


def test_injected_fault_is_transient_error_itself() -> None:
    """Given 注入切點，Then 丟的類別名逐字是 `TransientError`，不是子類。

    Phase 41 在雲端實證過：Step Functions 的 `ErrorEquals` 比對 Lambda 回報的**類別名
    字串**、不認繼承，所以子類 `InjectedFault` 不會命中 `["TransientError"]` 這條 retrier。
    controller 2026-09-14 裁決因此把 `InjectedFault` 降級成相容別名，注入一律丟
    `TransientError` 本身（00A 第 1230 列的名稱不變）。
    """
    assert InjectedFault is TransientError
    assert InjectedFault.__name__ == "TransientError"
    with pytest.raises(TransientError) as caught:
        maybe_fail("s3_after_md", {"TKB_FAULT": "s3_after_md"})
    assert type(caught.value).__name__ == "TransientError"


def test_active_fault_reads_the_switch() -> None:
    assert active_fault({"TKB_FAULT": "s3_after_md"}) == "s3_after_md"
    assert active_fault({}) is None
    assert active_fault({"TKB_FAULT": ""}) is None


def test_prod_never_injects() -> None:
    """Given `TKB_ENV=prod`，Then 任何切點都不生效（正式環境的保險）。"""
    assert active_fault({"TKB_FAULT": "s3_after_md", "TKB_ENV": "prod"}) is None


def test_unknown_switch_value_fails_loudly() -> None:
    """Given 打錯的切點名稱，Then 明確失敗，不靜靜當成「沒有注入」。"""
    with pytest.raises(PermanentError, match="typo"):
        active_fault({"TKB_FAULT": "typo"})


def test_maybe_fail_only_raises_on_the_named_point() -> None:
    env = {"TKB_FAULT": "ddb_after_version"}
    with pytest.raises(TransientError, match="ddb_after_version"):
        maybe_fail("ddb_after_version", env)
    assert maybe_fail("s3_after_md", env) is None


def test_maybe_fail_refuses_an_unknown_point() -> None:
    with pytest.raises(PermanentError, match="not_a_point"):
        maybe_fail("not_a_point", {})


# --- Phase 59 Task 1 Step 4：五個切點真的接進三支檔 ----------------------------


def _maybe_fail_points(source: str) -> list[str]:
    """這份原始碼裡 `maybe_fail("<字面值>")` 的切點名稱（走 AST，不會誤數文件字串）。"""
    found: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "maybe_fail" and node.args
                and isinstance(node.args[0], ast.Constant)):
            found.append(str(node.args[0].value))
    return found


def _wired_points() -> list[str]:
    root = Path(__file__).resolve().parents[2] / "src" / "training_kb"
    return [point for name in WIRED_FILES
            for point in _maybe_fail_points((root / name).read_text(encoding="utf-8"))]


def test_every_fault_point_is_wired_exactly_once() -> None:
    """Given 三支真實路徑的檔案，Then 每個切點名稱恰好出現一次 `maybe_fail(...)`。

    「恰好一次」是 00A 的契約：同一個切點插兩處會讓「注入一次、失敗兩次」，
    復原演練就分不出是哪一次中斷。
    """
    wired = _wired_points()
    assert sorted(wired) == sorted(FAULT_POINTS)
    for point in FAULT_POINTS:
        assert wired.count(point) == 1, f"{point} 出現 {wired.count(point)} 次"


def test_fault_points_live_in_the_expected_files() -> None:
    """Given 插入表，Then 建版切點在 `content.py`、發布在 `publishing.py`、接入在 `ingress.py`。"""
    root = Path(__file__).resolve().parents[2] / "src" / "training_kb"
    by_file = {name: _maybe_fail_points((root / name).read_text(encoding="utf-8"))
               for name in WIRED_FILES}
    assert sorted(by_file["content.py"]) == ["ddb_after_version", "s3_after_md"]
    assert sorted(by_file["publishing.py"]) == ["publish_after_transact_before_site",
                                                "publish_before_transact"]
    assert by_file["ingress.py"] == ["start_execution"]
