"""`TKB_FAULT` 故障注入切點的基本行為（`src/training_kb/faults.py`）。

**本檔的第一片由 Phase 41 建立，owner 仍是 Phase 59**（00A §3.2、§3.3）：P41 只需要
`faults.py` 這支檔存在、五個切點名稱定案、開關語意固定，好讓 P41 在雲端證明
「注入的失敗要丟 `TransientError` 本身才命中 ASL 的第一條 retrier」。**P41 不在
`content.py`／`publishing.py`／`ingress.py` 插入任何 `maybe_fail`**，那是 P59 Task 1，
P59 的「每個切點名稱在三個檔各恰好出現一次」那條測試因此完全不受影響。
"""

import pytest

from training_kb.errors import PermanentError, TransientError
from training_kb.faults import FAULT_POINTS, InjectedFault, active_fault, maybe_fail


def test_the_five_fault_points_are_fixed() -> None:
    """Given 00A 第 1230 列，Then 五個切點名稱一個不多一個不少、順序固定。"""
    assert FAULT_POINTS == ("s3_after_md", "ddb_after_version", "publish_before_transact",
                            "publish_after_transact_before_site", "start_execution")


def test_injected_fault_is_a_transient_error() -> None:
    """Given `InjectedFault`，Then 它是 `TransientError` 的子類（00A §4.1）。

    **但雲端的 `errorType` 是 `InjectedFault` 這個字串**，ASL 的
    `ErrorEquals: ["TransientError"]` 比對類別名、不認繼承，所以用它注入證不出 Retry
    （Phase 41 §7 的風險，已回報 controller）。
    """
    assert issubclass(InjectedFault, TransientError)
    assert InjectedFault.__name__ == "InjectedFault"


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
    with pytest.raises(InjectedFault, match="ddb_after_version"):
        maybe_fail("ddb_after_version", env)
    assert maybe_fail("s3_after_md", env) is None


def test_maybe_fail_refuses_an_unknown_point() -> None:
    with pytest.raises(PermanentError, match="not_a_point"):
        maybe_fail("not_a_point", {})
