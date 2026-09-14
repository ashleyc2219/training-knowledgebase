"""O2 gate 的五個整合案例：重啟、重送、lease 過期、交錯事件、closed execution。

`live_table`／`live_region` 讀的是**隔離的測試單表**（`infra/scripts/o2_report.py --provision`
建的 `training_kb_o2_<run_id>`），不是正式 `training_kb` 表；沒設環境變數就 skip。

整支標 `@pytest.mark.aws`：**只有這裡對真實 DynamoDB 跑出來的觀察值才算 O2 證據**，
`tests/unit/test_operation_ordering.py` 的記憶體 fake 全綠不算（Phase 11 §9）。

離線回歸版本在檔案最後一段（不標 `aws`）：同一組案例走 moto 表，證明案例腳本本身
沒有壞掉；它同樣**不是** O2 證據。
"""

import os
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

from training_kb.content import make_version_id, parse_version_id

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "infra" / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import o2_report  # noqa: E402
from o2_report import (  # noqa: E402
    O2_CASES,
    O2Case,
    o2_verdict,
    render_o2_report,
    run_o2_case,
)

TABLE_ENV = "TKB_TABLE_NAME"
REGION_ENV = "TKB_AWS_REGION"

BY_NAME = {case.name: case for case in O2_CASES}


@pytest.fixture
def live_table() -> str:
    name = os.environ.get(TABLE_ENV)
    if not name:
        pytest.skip(f"需要隔離的測試單表；設 {TABLE_ENV}=training_kb_o2_<run_id>")
    return name


@pytest.fixture
def live_region() -> str:
    region = os.environ.get(REGION_ENV)
    if not region:
        pytest.skip(f"Region 不寫死在測試裡；設 {REGION_ENV}=us-east-1")
    return region


@pytest.mark.aws
def test_all_o2_cases_pass(live_table: str, live_region: str) -> None:
    """五個案例各跑一次；任一 FAIL 就阻擋建版路徑，報告直接貼在斷言訊息裡。"""
    results = [run_o2_case(case, table=live_table, region=live_region) for case in O2_CASES]
    report = render_o2_report(results, run_id="local", table=live_table, region=live_region)
    assert [row.case.name for row in results] == [case.name for case in O2_CASES]
    assert o2_verdict(results) == "PASS", report


@pytest.mark.aws
def test_restart_keeps_one_operation_and_one_version(live_table: str, live_region: str) -> None:
    """真的 `kill -9` 一個子程序，重啟後仍是同 `operation_id`、同 `version_id`，沒有第三個版號。"""
    result = run_o2_case(BY_NAME["restart"], table=live_table, region=live_region)
    assert result.verdict == "PASS", result.observed
    assert "killed=-9" in result.observed
    assert "ops=1" in result.observed


@pytest.mark.aws
def test_resend_never_creates_a_second_operation(live_table: str, live_region: str) -> None:
    """同事件重送四次：`OPS#` 仍只有一筆、`accept_seq` 不變；D-45 的補寫不算重複處理。"""
    result = run_o2_case(BY_NAME["resend"], table=live_table, region=live_region)
    assert result.verdict == "PASS", result.observed
    assert "ops=1" in result.observed
    assert "duplicate=3" in result.observed


@pytest.mark.aws
def test_expired_lease_is_taken_over_and_order_still_follows_accept_seq(
    live_table: str, live_region: str
) -> None:
    """持有者不釋放就消失：到期後他人接手，順序仍照 `accept_seq`；到期 item 仍讀得到。"""
    result = run_o2_case(BY_NAME["lease_expiry"], table=live_table, region=live_region)
    assert result.verdict == "PASS", result.observed
    assert "readable_after_expiry=True" in result.observed


@pytest.mark.aws
def test_interleaved_events_serialize_without_a_fork(
    live_table: str, live_region: str
) -> None:
    """Release 與 Feedback 同時搶同一篇：兩個版號依 `accept_seq` 串行，沒有分叉。"""
    result = run_o2_case(BY_NAME["interleaved"], table=live_table, region=live_region)
    assert result.verdict == "PASS", result.observed
    assert "lock_order_reversed=True" in result.observed


@pytest.mark.aws
def test_closed_execution_reads_the_ledger_or_fails_loudly(
    live_table: str, live_region: str
) -> None:
    """同名執行已結束後重送：讀 ledger 原結果；ledger 沒有結果就 `CoordinationError`。"""
    result = run_o2_case(BY_NAME["closed_execution"], table=live_table, region=live_region)
    assert result.verdict == "PASS", result.observed
    assert "no_result=CoordinationError" in result.observed


# --- 離線回歸（moto；不是 O2 證據）-------------------------------------------


@pytest.fixture
def moto_table(table: object) -> Iterator[str]:
    """把 `tests/integration/conftest.py` 的 moto 表借給案例腳本用。

    案例腳本自己開 boto3 client，所以 `mock_aws` 區塊必須在整個案例期間都活著——
    `table` fixture 的 `yield` 正好提供這段期間。腳本的 resource 快取要清掉，
    上一個 `mock_aws` 區塊留下的物件不能跨到這一個。
    """
    o2_report._RESOURCES.clear()
    yield "training_kb"
    o2_report._RESOURCES.clear()


@pytest.mark.parametrize("case", O2_CASES, ids=lambda case: case.name)
def test_every_case_also_passes_offline(case: O2Case, moto_table: str) -> None:
    """moto 上的同一組案例；證明腳本邏輯沒壞，**不**證明 O2（Phase 11 §9 的停止條件）。"""
    if case.name == "restart":
        pytest.skip("restart 要 spawn 真的子程序，子程序看不到本行程的 moto 攔截器")
    result = run_o2_case(case, table=moto_table, region="us-west-2")
    assert result.verdict == "PASS", result.observed


def test_the_script_reuses_contents_version_functions() -> None:
    """版號字串的定義只有 `training_kb.content` 這一份，腳本不得自己寫一份比較寬鬆的。

    寬鬆的那份把 `a@v01` 讀成第 1 版、也組得出 `a@v0`，等於讓兩個字串對應同一版；
    案例腳本用它算出來的「第幾版」就可能跟正式路徑不一樣。
    """
    assert o2_report.make_version_id is make_version_id
    assert o2_report.parse_version_id is parse_version_id
    assert not hasattr(o2_report, "make_version")
    assert not hasattr(o2_report, "version_number")
