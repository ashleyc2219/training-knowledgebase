"""Phase 36 Task 3：用 Phase 13 的核定紀錄與 fixture 驗證每一個 adapter。

三件事：每個**已核定**來源都能從原始事件走到 canonical 物件（ING Rule 12／13）、
已記錄的 `ProcStep` 裡搜不到任何事件真值，以及 F14 的子 Release 由 `index` 挑出。
未核定的來源維持 gate failure：那幾列以 `xfail(strict=True)` 收尾，**不得**補臨時 mapping
讓它變綠——真的補了就會 XPASS，strict 會把它變成紅燈（設計 §18 O6、決策 F02）。

本檔不連 AWS、不呼叫模型、不連 GitHub，所以不標 `aws` marker（00A §3.2）。
"""

import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from training_kb.adapters import FINAL_TOOL, PARSER_KIND, default_registry
from training_kb.errors import PermanentError
from training_kb.models import ProcStep
from training_kb.pipelines.common import JSONValue
from training_kb.rote import RawEvent, execute_recorded_steps
from training_kb.source_ids import SourceApproval, load_source_approvals

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = REPO_ROOT / "tests" / "fixtures"
NORMALIZER = {"ticket": "normalize_ticket", "release": "normalize_release"}
PARSER_OF_ADAPTER = {"github_issue": "parse_github_issue", "github_pr": "parse_pr_diff",
                     "discord_manual": "parse_discord_message",
                     "email_manual": "parse_support_email", "changelog_manual": "parse_changelog"}
APPROVALS = load_source_approvals(FIXTURES / "o6" / "approved-sources.json")
APPROVAL_PARAMS = [
    pytest.param(row, id=f"{row.domain}:{row.event_type}",
                 marks=() if row.approved else pytest.mark.xfail(
                     strict=True, reason=f"O6 尚未核定 {row.domain}/{row.event_type}"))
    for row in APPROVALS
]
PR_APPROVED = any(
    row.approved and (row.domain, row.event_type) == ("github.com", "pull_request")
    for row in APPROVALS
)


def leaf_strings(value: JSONValue) -> Iterator[str]:
    """走訪 fixture 所有葉節點字串，證明 PROC 不含事件真值。"""
    if isinstance(value, dict):
        value = list(value.values())
    if isinstance(value, list):
        for item in value:
            yield from leaf_strings(item)
    elif isinstance(value, str) and len(value) >= 8:
        yield value


def steps_for(parser: str) -> list[ProcStep]:
    return [ProcStep(tool=parser, args={"payload": "$event.payload"}),
            ProcStep(tool=NORMALIZER[PARSER_KIND[parser]], args={"parsed": "$steps[0]"}),
            ProcStep(tool="validate", args={"candidate": "$steps[1]"})]


def event_of(domain: str, adapter: str, event_type: str, fixture: str) -> RawEvent:
    return RawEvent(domain=domain, adapter=adapter, event_type=event_type, headers={},
                    payload=json.loads((FIXTURES / fixture).read_text("utf-8")))


@pytest.mark.parametrize("row", APPROVAL_PARAMS)
def test_each_source_reaches_canonical_without_storing_values(row: SourceApproval) -> None:
    assert row.approved_by, (
        f"O6 未核定 {row.domain}/{row.event_type}：保持 blocked，不得補臨時 mapping")
    parser = PARSER_OF_ADAPTER[row.adapter]
    steps = steps_for(parser)
    assert steps[-1].tool == FINAL_TOOL          # ING Rule 13：最後一個工具恰為 validate
    event = event_of(row.domain, row.adapter, row.event_type, row.fixture)
    canonical = execute_recorded_steps(event, steps, default_registry())
    assert canonical["id"].startswith("t_" if PARSER_KIND[parser] == "ticket" else "r_")
    # 只看 args：工具名稱本來就含來源字眼（parse_changelog 含 "changelog"），不算「存了事件值」。
    recorded = json.dumps([step.model_dump()["args"] for step in steps], ensure_ascii=False)
    assert all(value not in recorded for value in leaf_strings(event.payload))


def test_wrong_parser_normalizer_pair_fails_before_validate() -> None:
    """配對錯誤是**拒絕**斷言，與 O6 是否核定無關，所以不掛 gate 標記。"""
    event = event_of("github.com", "github_pr", "pull_request", "github/pull-request-merged.json")
    steps = steps_for("parse_pr_diff")
    steps[1] = ProcStep(tool="normalize_ticket", args={"parsed": "$steps[0]"})
    with pytest.raises(PermanentError, match="kind"):
        execute_recorded_steps(event, steps, default_registry())


@pytest.mark.xfail(not PR_APPROVED, strict=True, reason="O6 尚未核定 github.com/pull_request")
def test_release_parser_returns_changes_and_index_picks_one() -> None:
    row = {(r.domain, r.event_type): r for r in APPROVALS}[("github.com", "pull_request")]
    assert row.approved_by, "O6 未核定 github.com/pull_request：保持 blocked，不得補臨時 mapping"
    registry = default_registry()
    payload = json.loads((FIXTURES / row.fixture).read_text("utf-8"))
    parsed = registry.run("parse_pr_diff", {"payload": payload})
    assert isinstance(parsed["changes"], list) and parsed["changes"]
    subs = [registry.run("normalize_release", {"parsed": parsed, "index": k})
            for k in range(1, len(parsed["changes"]) + 1)]
    assert len({sub["id"] for sub in subs}) == len(subs)          # 每筆子 Release 各有 id
    assert len({sub["source_event_id"] for sub in subs}) == 1     # 但共用同一個上游事件
    assert registry.run("normalize_release", {"parsed": parsed})["id"] == subs[0]["id"]
    with pytest.raises(PermanentError):
        registry.run("normalize_release", {"parsed": parsed, "index": len(subs) + 1})
