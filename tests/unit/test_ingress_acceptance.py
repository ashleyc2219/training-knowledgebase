"""接受端（Phase 32）：名稱決定性、永久去重、有限 input 與期限。

用的是記憶體版 `Repository` 加**真正的** `OperationCoordinator`：去重語意由 Phase 10 的
程式決定，不在測試裡另寫一份。moto 的整合證據在
`tests/integration/test_start_execution_idempotency.py`，真實表的 O2 證據在 Phase 11。
"""

import re

import pytest

from training_kb.ingress import execution_name, operation_id_for


def test_names_are_deterministic_and_safe() -> None:
    op = operation_id_for("ticket", "t_881")
    assert op == "op-ticket-t_881" == operation_id_for("ticket", "t_881")
    assert op != operation_id_for("release", "t_881")
    assert re.fullmatch(r"[A-Za-z0-9_-]{1,80}", execution_name(op))


@pytest.mark.parametrize("canonical_id", ["t_881", "t_" + "9" * 200, "t_會前摘要"])
def test_execution_name_always_obeys_the_step_functions_rule(canonical_id: str) -> None:
    name = execution_name(operation_id_for("ticket", canonical_id))
    assert re.fullmatch(r"[A-Za-z0-9_-]{1,80}", name)
    assert name.startswith("op-ticket-")
    assert name == execution_name(operation_id_for("ticket", canonical_id))
