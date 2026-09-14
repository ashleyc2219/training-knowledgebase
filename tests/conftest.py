"""全套測試共用設定：`aws` marker 自動 skip，以及 Rote 三層接入（Phase 37）的三個 fixture。

`raw_issue`／`active_proc`／`rote_deps` 放在 `tests/` 根目錄（00A §3.2），
`tests/unit/` 與 `tests/integration/` 都看得到，單元與整合測試共用同一組器材。
這裡的假物件都不連 AWS、不呼叫 Bedrock：`rote_deps` 的 writer 是照腳本回工具選擇的
假 Writer，registry 是包了一層計數的 `default_registry()`，starter 只把啟動記下來。
"""

import json
import os
from collections.abc import Callable, Iterator, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic
from typing import Any

import pytest

from training_kb import ingress, rote
from training_kb.adapters import default_registry
from training_kb.clock import now_utc
from training_kb.config import load_settings
from training_kb.errors import IngressError, PermanentError
from training_kb.models import ProcStatus, ProcStep, ProvenWorkflow
from training_kb.operations import OperationCoordinator
from training_kb.rote import RawEvent, structure_signature

RUN_AWS_ENV = "TKB_RUN_AWS_INTEGRATION"


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """未開啟真實 AWS 整合測試時，替所有標了 aws 的測試補上 skip。"""
    if os.environ.get(RUN_AWS_ENV) == "1":
        return
    skip_aws = pytest.mark.skip(reason=f"需要真實 AWS 帳號；設 {RUN_AWS_ENV}=1 才執行")
    for item in items:
        if "aws" in item.keywords:
            item.add_marker(skip_aws)


# --- Rote 三層接入的共用器材（Phase 37）---------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURES = REPO_ROOT / "tests" / "fixtures"
DELIVERY_ID = "d-001"
TRACE_ID = f"op-ingress-{DELIVERY_ID}"
"""正規化之前的臨時 operation id（00A §3.3）；只給 `CallTrace` 用，不是去重鍵。"""

ISSUE_HEADERS: Mapping[str, str] = {
    "x-github-event": "issues",
    "x-github-delivery": DELIVERY_ID,
    "content-type": "application/json",   # 不在 HEADER_PREFIXES 內，不進簽名
}
ISSUE_STEPS: tuple[tuple[str, dict[str, str]], ...] = (
    ("parse_github_issue", {"payload": "$event.payload"}),
    ("normalize_ticket", {"parsed": "$steps[0]"}),
    ("validate", {"candidate": "$steps[1]"}),
)
"""`active_proc` 的已驗證序列；與 Phase 36 的 `steps_for()` 同一種形狀。"""

AGENT_PLAN: Mapping[str, tuple[str, str]] = {
    "github_issue": ("parse_github_issue", "normalize_ticket"),
    "github_pr": ("parse_pr_diff", "normalize_release"),
}
"""假 Writer 會照著提的固定序列；真模型的自由度由 Phase 36 的白名單擋住。"""

DEFAULT_EXECUTION_ARN = "arn:aws:states:us-east-1:111122223333:execution:tkb/agent"


def _payload_of(name: str) -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    return loaded


@pytest.fixture
def raw_issue() -> Callable[..., RawEvent]:
    """`tests/fixtures/github/issue-opened.json` 組出來的 `RawEvent`（每次都是新的物件）。

    `domain`／`adapter`／`event_type` 依可信入口設定給定（00A D-60），**不從 payload 反推**；
    `**overrides` 讓 Release 的測試換成 `github_pr`／`pull_request` 與 PR fixture。
    """
    def make(**overrides: Any) -> RawEvent:
        fields: dict[str, Any] = {
            "domain": "github.com", "adapter": "github_issue", "event_type": "issues",
            "headers": dict(ISSUE_HEADERS), "payload": _payload_of("github/issue-opened.json"),
        }
        return RawEvent(**{**fields, **overrides})
    return make


@pytest.fixture
def active_proc(raw_issue: Callable[..., RawEvent]) -> Callable[..., ProvenWorkflow]:
    """與 `raw_issue()` 同簽名、可重放（active 且成功三次）的 `ProvenWorkflow`。

    `**overrides` 讓 Task 3 造出 retired 或連敗中的版本；`steps` 是完整的三步序列，
    所以「retired 的 steps 沒有被新序列覆寫」才有東西可以比對。
    """
    def make(**overrides: Any) -> ProvenWorkflow:
        event = raw_issue()
        fields: dict[str, Any] = {
            "signature": structure_signature(event), "domain": event.domain,
            "adapter": event.adapter,
            "steps": [ProcStep(tool=tool, args=dict(args)) for tool, args in ISSUE_STEPS],
            "keys": sorted(rote.event_stable_keys(event)),
            "success_count": 3, "fail_count": 0, "status": ProcStatus.ACTIVE,
            "last_used": datetime(2026, 9, 12, tzinfo=UTC),
        }
        return ProvenWorkflow(**{**fields, **overrides})
    return make


class MemoryRepository:
    """記憶體版 `Repository`：只實作 Rote 與 `OperationCoordinator` 會用到的原語。

    行為逐條照 Phase 06／07：`put_meta(create_only=True)` 撞鍵丟 `CoordinationError`、
    `update_meta` 做 revision compare-and-swap、`put_meta_item` 回「本次是否由我建立」。
    真表行為的證據在整合測試（moto）與 Phase 11 的 O2。
    """

    def __init__(self) -> None:
        self.items: dict[str, dict[str, Any]] = {}
        self.objects: dict[str, bytes] = {}

    # --- metadata ---
    def put_meta(self, entity: ProvenWorkflow, *, create_only: bool = True) -> None:
        from training_kb.errors import CoordinationError
        from training_kb.keys import proc_pk
        pk = proc_pk(entity.signature)
        if create_only and pk in self.items:
            raise CoordinationError(f"metadata already exists: {pk}")
        self.items[pk] = {**entity.model_dump(mode="json"), "_revision": 1}

    def get_proc(self, signature: str) -> ProvenWorkflow | None:
        from training_kb.keys import proc_pk
        item = self.items.get(proc_pk(signature))
        if item is None:
            return None
        return ProvenWorkflow.model_validate({k: v for k, v in item.items() if k != "_revision"})

    def list_procs(self, domain: str, adapter: str) -> list[ProvenWorkflow]:
        found = [self.get_proc(str(item["signature"])) for key, item in self.items.items()
                 if key.startswith("PROC#")]
        return sorted((proc for proc in found
                       if proc is not None and proc.domain == domain and proc.adapter == adapter),
                      key=lambda proc: proc.signature)

    def revision_of(self, pk: str) -> int:
        from training_kb.errors import CoordinationError
        item = self.items.get(pk)
        if item is None:
            raise CoordinationError(f"metadata not found: {pk}")
        return int(item["_revision"])

    def update_meta(self, pk: str, changes: Mapping[str, Any], *, expected_revision: int) -> int:
        from training_kb.errors import CoordinationError
        item = self.items.get(pk)
        if item is None or item["_revision"] != expected_revision:
            raise CoordinationError(f"stale revision for {pk}")
        item.update(changes)
        item["_revision"] = expected_revision + 1
        return expected_revision + 1

    # --- operation ledger 的原語 ---
    def put_meta_item(self, pk: str, attributes: Mapping[str, Any], *,
                      create_only: bool = True) -> bool:
        if create_only and pk in self.items:
            return False
        revision = int(self.items.get(pk, {}).get("_revision", 0)) + 1
        self.items[pk] = {**dict(attributes), "_revision": revision}
        return True

    def get_meta_item(self, pk: str) -> dict[str, Any] | None:
        item = self.items.get(pk)
        return None if item is None else dict(item)

    def put_object(self, key: str, body: bytes, content_type: str, *,
                   if_none_match: bool = False) -> None:
        from training_kb.errors import ObjectAlreadyExists
        if if_none_match and key in self.objects:
            raise ObjectAlreadyExists(key)
        self.objects[key] = body


class CountingRegistry:
    """包一層 `default_registry()`：記工具呼叫次數，並提供 validate 的兩個旋鈕。

    `replay_error` 只讓**第一次** validate 失敗——那一次就是重放，接著的 Agent 仍然照常；
    `fail_at="validate"` 則每一次都失敗，用來證明 Agent 最終非法時整次接入回失敗。
    """

    def __init__(self, deps: "FakeRoteDeps", *, replay_error: str | None,
                 agent_result: Mapping[str, Any] | None, fail_validate: bool) -> None:
        self._inner = default_registry()
        self.tools = self._inner.tools
        self._deps = deps
        self._replay_error = replay_error
        self._agent_result = agent_result
        self._fail_validate = fail_validate
        self.validate_calls = 0

    def run(self, name: str, arguments: Mapping[str, Any]) -> Any:
        self._deps.tool_calls += 1
        if self._deps.started:
            self._deps.tool_calls_after_start += 1
        self._deps.tools_used.append(name)
        if name != "validate":
            return self._inner.run(name, arguments)
        self.validate_calls += 1
        if self._replay_error is not None and self.validate_calls == 1:
            raise IngressError(self._replay_error, ("author",))
        if self._fail_validate:
            raise PermanentError("fail_at=validate：正規化驗證失敗")
        if self._agent_result is not None:
            return dict(self._agent_result)
        return self._inner.run(name, arguments)


class ScriptedWriter:
    """假 Writer：照 `AGENT_PLAN` 依序提出 `parse_* -> normalize_* -> validate`。

    只看 `messages` 裡已經有幾則 assistant 訊息決定下一步，所以「重來一輪」時會再從
    parser 開始——真模型在同一個位置有自由度，這裡固定下來才能斷言工具呼叫次數。
    回應形狀與 Bedrock Converse 的 `toolUse` 區塊一致（00A §6.5）。
    """

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def _plan(self, text: str) -> tuple[str, str]:
        """從 prompt 的 `<source_data>` 讀 adapter。

        比對的是 `"adapter": "<名稱>"` 這個鍵值對而不是裸名稱：`<allowed_tools>` 裡有
        `parse_github_issue`，用子字串比對會讓 PR 事件也命中 `github_issue`。
        """
        for adapter, plan in AGENT_PLAN.items():
            if f'"adapter": "{adapter}"' in text:
                return plan
        raise AssertionError(f"ScriptedWriter 認不出這個 prompt 的 adapter: {text[:120]}")

    def converse_with_tools(self, system: str, messages: Sequence[Mapping[str, Any]],
                            tools: Sequence[Mapping[str, Any]], *,
                            operation_id: str, node: str) -> dict[str, Any]:
        self.calls.append({"operation_id": operation_id, "node": node,
                           "messages": len(messages), "tools": len(tools)})
        text = " ".join(str(block.get("text", "")) for message in messages
                        for block in message.get("content", ()) if isinstance(block, Mapping))
        parser, normalizer = self._plan(text)
        position = sum(1 for message in messages if message.get("role") == "assistant") % 3
        name = (parser, normalizer, "validate")[position]
        args = ({"payload": "$event.payload"}, {"parsed": "$steps[0]"},
                {"candidate": "$steps[1]"})[position]
        return {"output": {"message": {"role": "assistant", "content": [
            {"toolUse": {"toolUseId": f"tu-{len(self.calls)}", "name": name, "input": args}}]}},
            "stopReason": "tool_use"}

    def embed(self, text: str, *, operation_id: str, node: str) -> list[float]:
        raise AssertionError("接入層不呼叫 embedding")

    def generate_json(self, system: str, user: str, schema: Mapping[str, Any], *,
                      operation_id: str, node: str) -> dict[str, Any]:
        raise AssertionError("接入層只用 converse_with_tools")


class RecordingStarter:
    """假 `PipelineStarter`：把「哪一條 state machine、哪一個執行名稱」記下來。"""

    def __init__(self, deps: "FakeRoteDeps", *, error: Exception | None) -> None:
        self._deps = deps
        self._error = error

    def start(self, pipeline: str, execution_name: str, input: dict[str, Any]) -> str:
        if self._error is not None:
            raise self._error
        self._deps.started.append((pipeline, execution_name))
        self._deps.inputs.append(dict(input))
        return self._deps.execution_arn


class FailingSaveRepository:
    """只讓 `put_object` 失敗的代理：模擬 canonical 輸入保存失敗這個切點。"""

    def __init__(self, inner: Any) -> None:
        self._inner = inner

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    def put_object(self, *args: Any, **kwargs: Any) -> None:
        raise PermanentError("fail_at=save：canonical 輸入保存失敗")


class FakeRoteDeps:
    """滿足 `RoteDeps` 的結構型 fake，外加測試要觀察的計數器。

    `replay_failures`／`replay_successes` 由 monkeypatch 包住 Phase 35 的兩個純函式取得，
    所以記到的是「真的被呼叫了幾次、對哪一個簽名」，不是測試自己推論出來的。
    """

    def __init__(self, *, repository: Any, replay_error: str | None,
                 agent_result: Mapping[str, Any] | None, fail_at: str | None,
                 execution_arn: str) -> None:
        self.repository = repository
        self.operations = OperationCoordinator(repository)
        self.registry = CountingRegistry(self, replay_error=replay_error,
                                         agent_result=agent_result,
                                         fail_validate=fail_at == "validate")
        self.writer = ScriptedWriter()
        self.now = now_utc
        self.trace_id = TRACE_ID
        self.deadline = monotonic() + 8.0
        self.execution_arn = execution_arn
        self.replay_failures: list[str] = []
        self.replay_successes: list[str] = []
        self.tool_calls = 0
        self.tool_calls_after_start = 0
        self.tools_used: list[str] = []
        self.commit_calls = 0
        self.started: list[tuple[str, str]] = []
        self.inputs: list[dict[str, Any]] = []
        self.starter = RecordingStarter(
            self, error=PermanentError("fail_at=start_execution：啟動失敗")
            if fail_at == "start_execution" else None)
        self.wiring = ingress.Wiring(
            operations=self.operations, starter=self.starter,
            repository=FailingSaveRepository(repository) if fail_at == "save" else repository,
            settings=load_settings({}))

    @property
    def agent_calls(self) -> int:
        """Agent 被叫起來幾次＝從空對話開始的 `converse_with_tools` 次數。"""
        return sum(1 for call in self.writer.calls if call["messages"] == 1)

    def accept(self, entity: Any) -> Any:
        """Phase 32 的 `accept_*`（依型別分派）；wiring 已由 fixture 注入。"""
        return ingress.accept_normalized(entity, deadline=self.deadline)


@pytest.fixture
def rote_deps(monkeypatch: pytest.MonkeyPatch) -> Iterator[Callable[..., FakeRoteDeps]]:
    """造一個滿足 `RoteDeps` 的 fake；四個旋鈕見 `FakeRoteDeps`。

    同時把 Phase 32 的 `_wiring()` 換成本次的假相依，`deps.accept(...)` 才不會連到真 AWS；
    Phase 35 的 `on_replay_success`／`on_replay_failure` 也包一層記錄用的 wrapper。
    """
    created: list[FakeRoteDeps] = []

    def make(*, replay_error: str | None = None,
             agent_result: Mapping[str, Any] | None = None,
             fail_at: str | None = None, repository: Any = None,
             execution_arn: str = DEFAULT_EXECUTION_ARN) -> FakeRoteDeps:
        deps = FakeRoteDeps(repository=repository if repository is not None
                            else MemoryRepository(),
                            replay_error=replay_error, agent_result=agent_result,
                            fail_at=fail_at, execution_arn=execution_arn)
        created.append(deps)
        ingress._reset_wiring()
        ingress._reset_rote_deps()
        monkeypatch.setattr(ingress, "_wiring", lambda: deps.wiring)
        monkeypatch.setattr(ingress, "_rote_deps", lambda: deps)
        return deps

    real_failure, real_success = rote.on_replay_failure, rote.on_replay_success

    def spy_failure(proc: ProvenWorkflow, now: datetime) -> ProvenWorkflow:
        for deps in created:
            deps.replay_failures.append(proc.signature)
        return real_failure(proc, now)

    def spy_success(proc: ProvenWorkflow, now: datetime) -> ProvenWorkflow:
        for deps in created:
            deps.replay_successes.append(proc.signature)
        return real_success(proc, now)

    real_commit = rote.Rote.commit_success

    def spy_commit(self: rote.Rote, *args: Any, **kwargs: Any) -> Any:
        for deps in created:
            deps.commit_calls += 1
        return real_commit(self, *args, **kwargs)

    def no_real_aws(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("測試忘了注入 _rote_deps／_wiring：這條路徑會連到真實 AWS")

    monkeypatch.setattr(rote, "on_replay_failure", spy_failure)
    monkeypatch.setattr(rote, "on_replay_success", spy_success)
    monkeypatch.setattr(rote.Rote, "commit_success", spy_commit)
    monkeypatch.setattr(ingress, "_build_rote_deps", no_real_aws)
    monkeypatch.setattr(ingress, "_build_wiring", no_real_aws)
    yield make
    ingress._reset_wiring()
    ingress._reset_rote_deps()
