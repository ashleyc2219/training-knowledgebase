"""操作紀錄的兩個純函式：`OPS#` 主鍵與 `operations/` 私有 ref。

`op-1` 只是測試字串；正式路徑的 `operation_id` 一律由 Phase 32 的 `operation_id_for`
產生（00A §3.3），它不在 `keys.py`。
"""

import pytest

from training_kb.errors import PermanentError
from training_kb.keys import operation_ref, ops_pk, parse_pk


def test_ops_pk_is_a_non_business_prefix_that_scan_entity_can_find() -> None:
    assert ops_pk("op-ticket-t_881") == "OPS#op-ticket-t_881"
    assert parse_pk(ops_pk("op-ticket-t_881")) == ("OPS", "op-ticket-t_881")


def test_ops_pk_rejects_an_already_prefixed_operation_id() -> None:
    with pytest.raises(ValueError):
        ops_pk("OPS#op-ticket-t_881")


def test_operation_ref_is_private_and_stable() -> None:
    assert operation_ref("op-1", "input") == "operations/op-1/input.json"
    assert operation_ref("op-1", "input") == operation_ref("op-1", "input")
    assert not operation_ref("op-1", "input").startswith("site/")


@pytest.mark.parametrize(
    ("operation_id", "name"),
    [("op-1", "../site/index"), ("op/1", "input"), ("", "input"), ("op-1", "")],
)
def test_operation_ref_rejects_paths_that_escape_the_prefix(
    operation_id: str, name: str
) -> None:
    with pytest.raises(PermanentError):
        operation_ref(operation_id, name)
