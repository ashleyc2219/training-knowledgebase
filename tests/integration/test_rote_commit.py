"""Phase 37 Task 3：只有 validate、canonical 保存與 StartExecution 全部成功才提交 PROC。

`repository` 是 Phase 06 的 moto 建表 fixture，`rote_deps` 的 `accept` 走 Phase 32 真正的
`accept_ticket`／`accept_release`（starter 是假的，記下啟動了哪一條 state machine）。
對應 00B 的 ING Rule 8（端到端那一段）、Rule 10、Rule 14 與 RUN Rule 3。

moto 的綠燈只證明資料形狀與呼叫次序，**不是** O2 或真實 Step Functions 的證據；
不需要真實帳號，所以不標 `aws` marker（00A §3.2）。
"""

import json
from pathlib import Path
from typing import Any

import pytest

from training_kb import ingress
from training_kb.errors import PermanentError
from training_kb.models import ProcStatus
from training_kb.repository import Repository
from training_kb.rote import Rote, structure_signature
from training_kb.source_ids import load_source_approvals

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = REPO_ROOT / "tests" / "fixtures"
PR_APPROVED = any(row.approved and (row.domain, row.event_type) == ("github.com", "pull_request")
                  for row in load_source_approvals(FIXTURES / "o6" / "approved-sources.json"))


def run_ingress(rote: Rote, event: Any, deps: Any) -> tuple[Any, Any, Any]:
    """§6 的固定次序：normalize -> accept_* -> 拿到非空 ARN 才 commit。"""
    result = rote.normalize(event, operation_id=deps.trace_id, deadline=deps.deadline)
    acceptance = deps.accept(result.entity)
    arn = acceptance.record.execution_arn
    if acceptance.status == "duplicate" and arn:
        return acceptance, result, None
    return acceptance, result, rote.commit_success(
        result, operation_id=acceptance.operation_id, execution_arn=arn, now=deps.now())


@pytest.mark.parametrize("broken", ["validate", "save", "start_execution"])
def test_no_success_sample_before_every_step_passes(
        repository: Repository, rote_deps: Any, active_proc: Any, raw_issue: Any,
        broken: str) -> None:
    """ING Rule 14：三個切點任一個失敗，PROC 的 `success_count` 都不得往前。"""
    repository.put_meta(active_proc())                      # success_count=3、active
    deps = rote_deps(repository=repository, fail_at=broken)
    with pytest.raises(PermanentError):
        run_ingress(Rote(deps), raw_issue(), deps)
    assert deps.commit_calls == 0
    stored = repository.get_proc(active_proc().signature)
    assert stored is not None and stored.success_count == 3


def test_brand_new_sequence_records_one_sample_after_start(
        repository: Repository, rote_deps: Any, raw_issue: Any) -> None:
    """全新簽名：validate -> 保存 -> 啟動 三者依序成功後才多一個成功樣本。"""
    deps = rote_deps(repository=repository, execution_arn="arn:aws:states:::execution/x")
    rote = Rote(deps)
    acceptance, result, proc = run_ingress(rote, raw_issue(), deps)
    assert deps.started == [("ticket-analysis", acceptance.operation_id)]
    assert deps.tool_calls_after_start == 0          # RUN Rule 3：工具自由度只在接入層
    assert (proc.success_count, proc.fail_count, proc.status) == (1, 0, ProcStatus.ACTIVE)
    stored = repository.get_proc(result.signature)
    assert stored is not None and stored.success_count == 1
    assert run_ingress(rote, raw_issue(), deps)[2] is None         # 重送根本不進 commit
    same = rote.commit_success(result, operation_id=acceptance.operation_id,
                               execution_arn=deps.execution_arn, now=deps.now())
    assert same is not None and same.success_count == 1            # 第二次 sample 回 False


def test_retired_signature_is_not_overwritten(
        repository: Repository, rote_deps: Any, active_proc: Any, raw_issue: Any) -> None:
    """F53：退役流程視同未命中，`commit_success` 回 `None`，序列與狀態都不變。"""
    repository.put_meta(active_proc(status=ProcStatus.RETIRED, fail_count=3))
    deps = rote_deps(repository=repository, execution_arn="arn:aws:states:::execution/y")
    _, result, proc = run_ingress(Rote(deps), raw_issue(), deps)
    assert result.route == "agent"           # retired 視同未命中
    assert proc is None
    stored = repository.get_proc(result.signature)
    assert stored is not None
    assert (stored.status, stored.steps) == (ProcStatus.RETIRED, active_proc().steps)
    assert stored.success_count == active_proc().success_count


def test_a_replay_success_clears_the_failure_streak(
        repository: Repository, rote_deps: Any, active_proc: Any, raw_issue: Any) -> None:
    """重放成功走 `on_replay_success`：`fail_count` 歸零、`success_count` **不變**。"""
    repository.put_meta(active_proc(fail_count=2))
    deps = rote_deps(repository=repository)
    _, result, proc = run_ingress(Rote(deps), raw_issue(), deps)
    assert result.route == "layer1"
    assert deps.replay_successes == [active_proc().signature]
    assert proc is not None and (proc.success_count, proc.fail_count) == (3, 0)
    stored = repository.get_proc(result.signature)
    assert stored is not None and (stored.success_count, stored.fail_count) == (3, 0)


def test_an_agent_rescue_keeps_the_replay_failure(
        repository: Repository, rote_deps: Any, active_proc: Any, raw_issue: Any) -> None:
    """Agent 救回本次事件不代表那次重放成功：`fail_count` 保留，且不走 `on_replay_success`。"""
    repository.put_meta(active_proc())
    event = raw_issue()
    issue, repo = event.payload["issue"], event.payload["repository"]
    deps = rote_deps(repository=repository, replay_error="缺少 author 欄位", agent_result={
        "id": f"t_gh-acme-{repo['name']}-{issue['number']}", "source": "github_issue",
        "text": "找不到會議摘要按鈕", "author": "u_gh-90210",
        "ts": issue["created_at"], "project_id": "demo"})
    _, result, proc = run_ingress(Rote(deps), event, deps)
    assert result.route == "agent_after_replay_failure"
    assert deps.replay_failures == [active_proc().signature] and deps.replay_successes == []
    assert proc is not None and (proc.success_count, proc.fail_count) == (4, 1)


def test_normalize_then_accept_runs_the_whole_fixed_order(
        repository: Repository, rote_deps: Any, raw_issue: Any) -> None:
    """D-60 的接線點：整段「Rote 三層 -> accept_normalized -> commit_success」只在這裡。"""
    deps = rote_deps(repository=repository)
    event = raw_issue()
    accepted = ingress.normalize_then_accept(
        domain=event.domain, adapter=event.adapter, event_type=event.event_type,
        headers=event.headers, payload=event.payload, deadline=deps.deadline)
    assert [acceptance.operation_id for acceptance in accepted] == [
        "op-ticket-t_gh-acme-copilot-128"]
    assert accepted[0].status == "accepted" and accepted[0].record.execution_arn
    assert deps.started == [("ticket-analysis", accepted[0].operation_id)]
    assert deps.writer.calls[0]["operation_id"] == "op-ingress-d-001"   # 臨時 trace ID
    stored = repository.get_proc(structure_signature(event))
    assert stored is not None and stored.success_count == 1
    resent = ingress.normalize_then_accept(
        domain=event.domain, adapter=event.adapter, event_type=event.event_type,
        headers=event.headers, payload=event.payload, deadline=deps.deadline)
    assert resent[0].status == "duplicate" and deps.commit_calls == 1   # 重送不再 commit
    assert repository.get_proc(structure_signature(event)).success_count == 1


@pytest.mark.xfail(not PR_APPROVED, strict=True, reason="O6 尚未核定 github.com/pull_request")
def test_one_pr_with_two_features_becomes_two_operations(
        repository: Repository, rote_deps: Any, raw_issue: Any) -> None:
    """F14：一個 PR 改到兩個功能就回兩筆，各自一個 operation，`source_event_id` 相同。"""
    payload = json.loads((FIXTURES / "github" / "pull-request-merged.json").read_text("utf-8"))
    event = raw_issue(adapter="github_pr", event_type="pull_request", payload=payload,
                      headers={"x-github-event": "pull_request", "x-github-delivery": "d-002"})
    deps = rote_deps(repository=repository)
    results = Rote(deps).normalize_all(event, operation_id=deps.trace_id,
                                       deadline=deps.deadline)
    assert len(results) == 2
    assert [result.entity.id for result in results] == [
        "r_gh-acme-copilot-pr42-1", "r_gh-acme-copilot-pr42-2"]
    assert len({result.entity.source_event_id for result in results}) == 1
    accepted = [deps.accept(result.entity) for result in results]
    assert [acceptance.operation_id for acceptance in accepted] == [
        "op-release-r_gh-acme-copilot-pr42-1", "op-release-r_gh-acme-copilot-pr42-2"]
    assert [pipeline for pipeline, _ in deps.started] == ["release-update", "release-update"]
