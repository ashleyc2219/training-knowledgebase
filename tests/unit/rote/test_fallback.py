"""Phase 37 Task 1：三層順序與「重放失敗當次回退 Agent」。

對應 00B 的 ING Rule 10（前兩層皆未命中才由 Agent 選 adapter tool）、Rule 17（重放或
正規化驗證失敗時當次回退）與 Rule 18（Agent 最終仍非法就回失敗）。三個 fixture
（`raw_issue`／`active_proc`／`rote_deps`）在 `tests/conftest.py`，不連 AWS、不呼叫 Bedrock。
"""

from typing import Any

import pytest

from training_kb.adapters import SUB_RELEASE_INDEX, ToolRegistry
from training_kb.errors import PermanentError
from training_kb.models import ProcStatus, ProcStep, ProvenWorkflow
from training_kb.rote import (
    AGENT_MAX_TOOL_CALLS,
    RELEASE_NORMALIZER,
    Rote,
    _Run,
    _sub_release_index,
    structure_signature,
)
from training_kb.source_ids import github_ticket_id, github_user_id

NEIGHBOUR = "beef000000000001"
"""Layer 2 的候選簽名：同 domain＋adapter、keys 多一個 `installation`（Jaccard 4/5 = 0.8）。"""


def agent_ticket_for(event: Any) -> dict[str, Any]:
    """`validate_ticket` 的六個必填欄位；ID 與 user 一律由 Phase 13 的函式算出。"""
    repo, issue = event.payload["repository"], event.payload["issue"]
    return {
        "id": github_ticket_id(repo["owner"]["login"], repo["name"], issue["number"]),
        "source": "github_issue", "text": "找不到會議摘要按鈕",
        "author": github_user_id(event.payload["sender"]["id"]),
        "ts": issue["created_at"], "project_id": "demo",
    }


def test_replay_failure_falls_back_to_agent_once(rote_deps: Any, active_proc: Any,
                                                 raw_issue: Any) -> None:
    event = raw_issue()
    agent_ticket = agent_ticket_for(event)
    deps = rote_deps(replay_error="缺少 author 欄位", agent_result=agent_ticket)
    deps.repository.put_meta(active_proc())
    result = Rote(deps).normalize(event, operation_id="op-ingress-d-1", deadline=deps.deadline)
    assert result.route == "agent_after_replay_failure"
    assert result.validated is True
    assert result.entity.id == agent_ticket["id"]
    assert result.replayed_proc_signature == active_proc().signature
    assert deps.replay_failures == [active_proc().signature]
    assert deps.replay_successes == []
    assert deps.agent_calls == 1
    assert deps.tool_calls <= AGENT_MAX_TOOL_CALLS


def test_replay_failure_is_persisted_before_the_agent_runs(rote_deps: Any, active_proc: Any,
                                                           raw_issue: Any) -> None:
    """`on_replay_failure` 的結果要條件寫回；Agent 救回本次事件不會把它清掉。"""
    event = raw_issue()
    deps = rote_deps(replay_error="缺少 author 欄位", agent_result=agent_ticket_for(event))
    deps.repository.put_meta(active_proc())
    Rote(deps).normalize(event, operation_id=deps.trace_id, deadline=deps.deadline)
    stored = deps.repository.get_proc(active_proc().signature)
    assert (stored.fail_count, stored.success_count) == (1, 3)
    assert stored.status == ProcStatus.ACTIVE


@pytest.mark.parametrize("signature", ["exact", NEIGHBOUR])
def test_a_hit_replays_without_touching_the_model(rote_deps: Any, active_proc: Any,
                                                  raw_issue: Any, signature: str) -> None:
    """layer1／layer2 都不呼叫 LLM（00B ING Rule 11 的相關斷言）。"""
    event = raw_issue()
    exact = active_proc().signature
    proc = (active_proc() if signature == "exact"
            else active_proc(signature=NEIGHBOUR,
                             keys=sorted({*active_proc().keys, "installation"})))
    deps = rote_deps()
    deps.repository.put_meta(proc)
    result = Rote(deps).normalize(event, operation_id=deps.trace_id, deadline=deps.deadline)
    assert result.route == ("layer1" if signature == "exact" else "layer2")
    assert result.signature == exact                      # 本次事件的簽名，不是候選的
    assert result.replayed_proc_signature == proc.signature
    assert result.validated is True
    assert deps.agent_calls == 0 and deps.writer.calls == []
    assert deps.replay_failures == [] and deps.commit_calls == 0


def test_retired_signature_is_treated_as_a_miss(rote_deps: Any, active_proc: Any,
                                                raw_issue: Any) -> None:
    """已退役流程在下次接入時視同未命中；不呼叫 `on_replay_failure`（F53）。"""
    deps = rote_deps()
    deps.repository.put_meta(active_proc(status=ProcStatus.RETIRED, fail_count=3))
    result = Rote(deps).normalize(raw_issue(), operation_id=deps.trace_id,
                                  deadline=deps.deadline)
    assert result.route == "agent"
    assert result.replayed_proc_signature is None
    assert deps.agent_calls == 1 and deps.replay_failures == []


def test_a_brand_new_signature_goes_straight_to_the_agent(rote_deps: Any,
                                                          raw_issue: Any) -> None:
    event = raw_issue()
    deps = rote_deps()
    result = Rote(deps).normalize(event, operation_id=deps.trace_id, deadline=deps.deadline)
    assert result.route == "agent"
    assert result.signature == structure_signature(event)
    assert result.domain == "github.com" and result.adapter == "github_issue"
    assert result.keys == ("action", "issue", "repository", "sender")
    assert tuple(step.tool for step in result.steps) == (
        "parse_github_issue", "normalize_ticket", "validate")
    assert all(value.startswith(("$event", "$steps"))
               for step in result.steps for value in step.args.values())


def test_an_illegal_agent_result_fails_the_whole_ingress(rote_deps: Any, raw_issue: Any) -> None:
    """Rule 18：Agent 耗盡額度仍非法時整次接入失敗，不寫任何合法物件或成功 PROC。"""
    deps = rote_deps(fail_at="validate")
    with pytest.raises(PermanentError):
        Rote(deps).normalize(raw_issue(), operation_id=deps.trace_id, deadline=deps.deadline)
    assert deps.tool_calls == AGENT_MAX_TOOL_CALLS
    assert deps.started == [] and deps.commit_calls == 0
    assert deps.repository.items == {} and deps.repository.objects == {}


def test_an_expired_deadline_stops_the_agent_before_any_tool(rote_deps: Any,
                                                             raw_issue: Any) -> None:
    deps = rote_deps()
    with pytest.raises(TimeoutError):
        Rote(deps).normalize(raw_issue(), operation_id=deps.trace_id, deadline=deps.deadline - 9)
    assert deps.tool_calls == 0 and deps.writer.calls == []


def test_a_transient_replay_failure_is_not_a_proc_failure(rote_deps: Any, active_proc: Any,
                                                          raw_issue: Any,
                                                          monkeypatch: Any) -> None:
    """`TransientError` 是服務故障，原樣往上拋，不累加 `fail_count`、也不回退 Agent。"""
    from training_kb.errors import TransientError

    deps = rote_deps()
    deps.repository.put_meta(active_proc())

    def boom(name: str, arguments: Any) -> Any:
        raise TransientError("Bedrock 暫時不可用")

    monkeypatch.setattr(deps.registry, "run", boom)
    with pytest.raises(TransientError):
        Rote(deps).normalize(raw_issue(), operation_id=deps.trace_id, deadline=deps.deadline)
    assert deps.replay_failures == [] and deps.agent_calls == 0
    stored: ProvenWorkflow | None = deps.repository.get_proc(active_proc().signature)
    assert stored is not None and stored.fail_count == 0


# --- F14 子 Release 序號的取值（Phase 37 review 必修 B2）----------------------


def index_step(value: str | None) -> ProcStep:
    """`normalize_release` 那一步；`value` 是 `None` 代表整份序列沒帶 `index` 參數。"""
    args = {"parsed": "$steps[0]"}
    return ProcStep(tool=RELEASE_NORMALIZER,
                    args=args if value is None else {**args, SUB_RELEASE_INDEX: value})


def run_over(output: Any, raw_issue: Any) -> _Run:
    """已經跑完第一步的 `_Run`：`$steps[0]` 指得到 `output`。"""
    return _Run(raw_issue(), ToolRegistry(tools={}), [output])


@pytest.mark.parametrize(("value", "expected"), [("1", 1), ("7", 7), (None, 1)])
def test_sub_release_index_reads_a_literal(value: str | None, expected: int,
                                           raw_issue: Any) -> None:
    """字面序號（含「沒帶參數」時的預設 1）直接轉 int，與 `_Run.run` 同一條判準。"""
    assert _sub_release_index(index_step(value), run_over({}, raw_issue)) == expected


def test_sub_release_index_resolves_a_jsonpath(raw_issue: Any) -> None:
    """`validate_recorded_steps` 允許 index 是 JSONPath，所以這裡不能直接 `int(...)`。

    直接 `int("$steps[0].k")` 會丟**裸的** `ValueError`：`normalize_all` 的
    `except PermanentError` 接不到，PROC 不會累計失敗，handler 直接 5xx。
    """
    run = run_over({"k": 3}, raw_issue)
    assert _sub_release_index(index_step("$steps[0].k"), run) == 3


@pytest.mark.parametrize("output", [{"k": "3"}, {"k": 1.5}, {"k": True}, {"k": None}])
def test_sub_release_index_refuses_non_integers(output: Any, raw_issue: Any) -> None:
    """取到的值不是 int（`bool` 也不算）就收斂成 `PermanentError`，不是裸 `ValueError`。"""
    with pytest.raises(PermanentError, match="子 Release 序號不是整數"):
        _sub_release_index(index_step("$steps[0].k"), run_over(output, raw_issue))
