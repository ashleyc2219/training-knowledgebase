"""Phase 36 Task 2：工具白名單、記錄格式與「執行時才解析值」。

四組斷言：registry 只收核定的八個名稱（ING Rule 12 的白名單那半邊）、已記錄步驟只留
JSONPath 與工具名（Rule 12）、最後一步必須是 `validate` 而且不能只是「曾經出現」
（Rule 13），以及 `execute_recorded_steps` 只在執行當下解析值、不回寫進 `ProcStep`。
純函式測試，不連 AWS、不呼叫模型，所以不標 `aws` marker。
"""

from collections.abc import Sequence

import pytest

from training_kb.adapters import TOOL_NAMES, ToolRegistry
from training_kb.errors import PermanentError
from training_kb.models import ProcStep
from training_kb.rote import RawEvent, execute_recorded_steps, validate_recorded_steps

BODY = "Button not found在哪一頁"
EVENT = RawEvent(domain="github.com", adapter="github_issue", event_type="issues",
                 headers={"x-github-event": "issues"},
                 payload={"action": "opened", "issue": {"number": 12, "body": BODY}})
LEGAL = [ProcStep(tool="parse_github_issue", args={"body": "$event.payload.issue.body"}),
         ProcStep(tool="normalize_ticket", args={"parsed": "$steps[0]"}),
         ProcStep(tool="validate", args={"candidate": "$steps[1]"})]


def registry_of(*names: str) -> ToolRegistry:
    return ToolRegistry(tools={name: dict for name in names})


def test_registry_only_accepts_the_eight_approved_tools() -> None:
    assert len(TOOL_NAMES) == 8
    for forbidden in ("shell", "browser", "publish", "boto3"):
        with pytest.raises(PermanentError, match="白名單"):
            registry_of(forbidden)
    with pytest.raises(PermanentError, match="白名單"):
        registry_of("validate").run("parse_pr_diff", {})


def test_recorded_steps_hold_paths_only_and_end_with_validate() -> None:
    validate_recorded_steps(LEGAL)
    dumped = [step.model_dump() for step in LEGAL]
    assert BODY not in repr(dumped)
    assert all(v.startswith(("$event", "$steps")) for s in dumped for v in s["args"].values())


@pytest.mark.parametrize("steps", [
    [],
    [ProcStep(tool="validate", args={"x": BODY})],
    [ProcStep(tool="normalize_ticket", args={"parsed": "$steps[0]"})],
    [ProcStep(tool="validate", args={"a": "$steps[0]"}),
     ProcStep(tool="parse_changelog", args={"b": "$steps[0]"})],
    [ProcStep(tool="validate", args={"a": "$steps[0]"}),
     ProcStep(tool="parse_changelog", args={"b": "$steps[0]"}),
     ProcStep(tool="validate", args={"c": "$steps[1]"})],
])
def test_rejects_illegal_recorded_steps(steps: Sequence[ProcStep]) -> None:
    with pytest.raises(PermanentError):
        validate_recorded_steps(steps)


def test_execute_resolves_values_only_at_run_time() -> None:
    steps = [LEGAL[0], ProcStep(tool="validate", args={"parsed": "$steps[0]"})]
    result = execute_recorded_steps(EVENT, steps, registry_of("parse_github_issue", "validate"))
    assert result == {"parsed": {"body": BODY}}
    assert steps[0].args == {"body": "$event.payload.issue.body"}


def test_only_the_sub_release_index_may_be_a_literal() -> None:
    validate_recorded_steps([
        ProcStep(tool="parse_pr_diff", args={"payload": "$event.payload"}),
        ProcStep(tool="normalize_release", args={"parsed": "$steps[0]", "index": "2"}),
        ProcStep(tool="validate", args={"candidate": "$steps[1]"}),
    ])
    for illegal in ({"parsed": "$steps[0]", "index": "0"},        # k 從 1 起算
                    {"parsed": "$steps[0]", "index": BODY},        # 字面值不是序號
                    {"parsed": "$steps[0]", "other": "2"}):        # 只有 index 有例外
        with pytest.raises(PermanentError):
            validate_recorded_steps([ProcStep(tool="normalize_release", args=illegal),
                                     ProcStep(tool="validate", args={"c": "$steps[0]"})])
    with pytest.raises(PermanentError):                             # 別的工具沒有這條例外
        validate_recorded_steps([ProcStep(tool="normalize_ticket", args={"index": "2"}),
                                 ProcStep(tool="validate", args={"c": "$steps[0]"})])
