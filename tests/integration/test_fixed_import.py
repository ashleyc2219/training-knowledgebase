"""Phase 42 Task 2／3／4：固定匯入在 moto 表上的寫入、退役、去重、續跑與 Lambda 入口。

種子（`tests/integration/conftest.py` 的 `repository` 加本檔的固定資料，不改那支 conftest）：

```text
prepare-meeting   status 由 fixture 決定、current_version=@v2
  VERSION @v1      published_at 已有值   <- 回饋與瀏覽都指向這一版
  VERSION @v2      published_at 已有值   <- current_version，回饋刻意不指它
  VERSION @v3      published_at=None     <- 未發布；View 照收（驗收矩陣第一列）
```

全檔有一個 autouse fixture 把 `ingress._build_wiring`／`_build_rote_deps` 換成會爆的函式：
`Repository` 沒有 `started_executions` 可以數，所以「零次 `StartExecution`」改成
「只要碰到 `PipelineStarter`／Rote 的產地就當場失敗」。

**moto 全綠不代表 O2 或 O6 通過**：這裡只證明固定匯入這條路徑套用了同一份去重契約，
真表行為的證據在 Phase 11（O2 PASS）與 `@pytest.mark.aws` 的實機測試。
"""

import json
import logging
from collections.abc import Iterator, Mapping
from datetime import UTC, datetime
from time import monotonic
from typing import Any

import pytest

from training_kb import ingress
from training_kb.clock import to_iso
from training_kb.config import DEFAULT_PROJECT_ID
from training_kb.errors import (
    CoordinationError,
    IngressError,
    PermanentError,
    TransientError,
)
from training_kb.handlers import import_
from training_kb.ingress import (
    import_feedback,
    import_view,
    operation_id_for,
    validate_view,
)
from training_kb.keys import feedback_pk, parse_pk, version_pk, view_pk
from training_kb.models import Feedback, Tutorial, TutorialStatus, TutorialVersion
from training_kb.operations import (
    Acceptance,
    AcceptOperation,
    OperationCoordinator,
    OperationRecord,
)
from training_kb.pipelines.common import Deps
from training_kb.repository import Repository

SLUG = "prepare-meeting"
V1 = f"{SLUG}@v1"
V2 = f"{SLUG}@v2"
V3 = f"{SLUG}@v3"
PUBLISHED_AT = datetime(2026, 9, 1, tzinfo=UTC)
NOW = datetime(2026, 9, 14, 3, 0, tzinfo=UTC)

FEEDBACK: dict[str, Any] = {"id": "f_12", "tutorial_version": V1, "rating": 2, "user": "u_01"}
VIEW: dict[str, Any] = {"tutorial_version": V1, "user": "u_01", "ts": "2026-08-02T09:00:00Z"}

_ENTITIES = ("TUTORIAL", "VERSION", "FEEDBACK", "VIEW", "PROC", "OPS", "SEQ")

TICKET_ITEM: dict[str, Any] = {
    "domain": "github.com", "adapter": "github_issue", "event_type": "issues",
    "headers": {"X-GitHub-Event": "issues"},
    "payload": {"issue": {"number": 881, "body": "找不到摘要按鈕"}},
}
"""`ticket`／`release` 分支的每一筆自己帶六個來源欄位（00A D-60），不從 payload 反推。"""


def _acceptance(operation_id: str) -> Acceptance:
    """`normalize_then_accept` 的假回傳；本檔只看 handler 怎麼收斂它，不重測 P32。"""
    record = OperationRecord(operation_id=operation_id, kind="release",
                             canonical_id=operation_id.removeprefix("op-release-"),
                             project_id=DEFAULT_PROJECT_ID, status="started", input_ref=None,
                             execution_arn=None, version_id=None, model_output_refs=(),
                             proc_sample_signature=None, error=None, retryable=None,
                             accept_seq=1, accepted_at=NOW, updated_at=NOW)
    return Acceptance(status="accepted", operation_id=operation_id, record=record)


def _version(version_id: str, *, number: int, published: bool) -> TutorialVersion:
    return TutorialVersion(version_id=version_id, slug=SLUG, supersedes=None,
                           reason="gap:c12", rules_applied=[],
                           s3_key=f"tutorials/{SLUG}/v{number}.md",
                           published_at=PUBLISHED_AT if published else None)


def _seed(repository: Repository, status: TutorialStatus) -> Repository:
    repository.put_meta(Tutorial(slug=SLUG, current_version=V2, topic="準備會議",
                                 feature_ids=["Prepare"], status=status,
                                 successor=None, cluster_id="c12"))
    repository.put_meta(_version(V1, number=1, published=True))
    repository.put_meta(_version(V2, number=2, published=True))
    repository.put_meta(_version(V3, number=3, published=False))
    return repository


@pytest.fixture
def active_repo(repository: Repository) -> Repository:
    return _seed(repository, TutorialStatus.ACTIVE)


@pytest.fixture
def retired_repo(repository: Repository) -> Repository:
    """退役的同一篇教學；狀態由種子直接給，不重跑 `retire_tutorial`（那是 Phase 26 的事）。"""
    return _seed(repository, TutorialStatus.RETIRED)


@pytest.fixture
def operations(repository: Repository) -> OperationCoordinator:
    """與 `active_repo`／`retired_repo` 共用**同一個** `repository`（同一個 moto 表）。"""
    return OperationCoordinator(repository)


@pytest.fixture(autouse=True)
def no_pipeline_start(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """整條路徑一碰到 AWS 接線就當場失敗（`ING` Rule 29、`COL` Rule 8）。

    `ingress._build_wiring` 是 `PipelineStarter` 的唯一產地、`_build_rote_deps` 是 Rote 的
    唯一產地。換成會丟 `AssertionError` 的函式之後，feedback／view 只要試圖啟動 pipeline
    或進 Rote 就會爆，不必事後比對次數。結尾一定要 reset，否則模組級快取會漏到別的檔。
    """
    def boom(*args: object, **kwargs: object) -> object:
        raise AssertionError("feedback／view 不得啟動任何 pipeline，也不得進 Rote")

    ingress._reset_wiring()
    ingress._reset_rote_deps()
    monkeypatch.setattr(ingress, "_build_wiring", boom)
    monkeypatch.setattr(ingress, "_build_rote_deps", boom)
    yield
    ingress._reset_wiring()
    ingress._reset_rote_deps()


def every_key(repository: Repository) -> set[tuple[str, str]]:
    """全表（含關係邊與 `OPS#`／`SEQ#`）的鍵集合；「圖譜零變動」就是它前後相等。"""
    return {(str(item["PK"]), str(item["SK"]))
            for entity in _ENTITIES
            for item in repository.scan_entity(entity, meta_only=False)}


def accept_request_for(payload: Mapping[str, object]) -> AcceptOperation:
    """手動組出 `import_view` 會用的同一筆接受請求，用來模擬「已接受、還沒寫 item」。"""
    view = validate_view(payload)
    canonical_id = parse_pk(view_pk(view.tutorial_version, view.user, view.ts))[1]
    return AcceptOperation(operation_id=operation_id_for("view", canonical_id), kind="view",
                           canonical_id=canonical_id, project_id=DEFAULT_PROJECT_ID, now=NOW)


# --- Task 2：寫入圖譜、退役拒絕與重送去重 --------------------------------------


def test_feedback_is_saved_and_refers_to_the_requested_version(
        active_repo: Repository, operations: OperationCoordinator) -> None:
    """Given 指向 `@v1` 的回饋／When 匯入／Then `saved`，邊指向 `@v1` 而不是 current（Rule 7）。"""
    result = import_feedback(FEEDBACK, repository=active_repo, operations=operations, now=NOW)
    assert (result.status, result.object_id, result.invalid_fields) == ("saved", "f_12", ())
    assert [item.id for item in active_repo.list_feedback_of_version(V1)] == ["f_12"]
    assert active_repo.list_feedback_of_version(V2) == []
    edges = {(str(row["SK"]), str(row["target"]))
             for row in active_repo.query_pk(feedback_pk("f_12")) if str(row["SK"]) != "META"}
    assert edges == {(f"REFERS_TO#{version_pk(V1)}", version_pk(V1))}


def test_saving_feedback_does_not_touch_the_tutorial_or_create_a_version(
        active_repo: Repository, operations: OperationCoordinator) -> None:
    """Given 一筆兩分的回饋／When 匯入／Then 零新 `VERSION#`、零 `PROC#`、教學沒被改。

    `COL` Rule 8（單筆低分不改教學）、`ING` Rule 29（不觸發改版）、`ING` Rule 31
    （只有 Rote 讀寫 PROC）在同一個斷言裡一起守住。
    """
    versions_before = {str(row["PK"]) for row in active_repo.scan_entity("VERSION")}
    import_feedback(FEEDBACK, repository=active_repo, operations=operations, now=NOW)
    assert {str(row["PK"]) for row in active_repo.scan_entity("VERSION")} == versions_before
    assert active_repo.scan_entity("PROC") == []
    tutorial = active_repo.get_tutorial(SLUG)
    assert tutorial is not None and tutorial.current_version == V2


def test_a_missing_ts_is_filled_with_the_import_time_and_the_message_says_so(
        active_repo: Repository, operations: OperationCoordinator) -> None:
    """Given 來源沒給 `ts`／When 匯入／Then 記匯入時間且訊息明示不是使用者提交時間。"""
    result = import_feedback(FEEDBACK, repository=active_repo, operations=operations, now=NOW)
    assert to_iso(NOW) in result.message
    assert "非使用者實際提交時間" in result.message
    saved = active_repo.get_meta(feedback_pk("f_12"), type(
        active_repo.list_feedback_of_version(V1)[0]))
    assert saved is not None and saved.ts == NOW


def test_a_supplied_ts_is_not_described_as_an_import_time(
        active_repo: Repository, operations: OperationCoordinator) -> None:
    """Given 來源有給 `ts`／When 匯入／Then 訊息不得出現補值那段話。"""
    payload = {**FEEDBACK, "ts": "2026-09-13T12:34:56Z"}
    result = import_feedback(payload, repository=active_repo, operations=operations, now=NOW)
    assert result.status == "saved" and "非使用者實際提交時間" not in result.message
    assert active_repo.list_feedback_of_version(V1)[0].ts == datetime(
        2026, 9, 13, 12, 34, 56, tzinfo=UTC)


def test_same_feedback_id_resent_is_duplicate(
        active_repo: Repository, operations: OperationCoordinator) -> None:
    """Given 同一個 `f_12` 送兩次／When 匯入／Then 第二次 `duplicate` 且樣本數不變（Rule 10）。"""
    first = import_feedback(FEEDBACK, repository=active_repo, operations=operations, now=NOW)
    again = import_feedback(FEEDBACK, repository=active_repo, operations=operations, now=NOW)
    assert (first.status, again.status) == ("saved", "duplicate")
    assert again.object_id == "f_12" and again.invalid_fields == ()
    assert len(active_repo.list_feedback_of_version(V1)) == 1


def test_two_feedback_ids_from_the_same_user_each_count(
        active_repo: Repository, operations: OperationCoordinator) -> None:
    """Given 同一人對同一版送 `f_12` 與 `f_13`／When 匯入／Then 兩筆都 `saved`（Rule 10）。"""
    statuses = [import_feedback({**FEEDBACK, "id": feedback_id}, repository=active_repo,
                                operations=operations, now=NOW).status
                for feedback_id in ("f_12", "f_13")]
    assert statuses == ["saved", "saved"]
    assert [item.id for item in active_repo.list_feedback_of_version(V1)] == ["f_12", "f_13"]


def test_an_unknown_version_is_rejected_and_the_graph_is_untouched(
        active_repo: Repository, operations: OperationCoordinator) -> None:
    """Given `tutorial_version` 不在圖譜／When 匯入／Then `rejected` 且全表鍵集合不變（Rule 1）。"""
    before = every_key(active_repo)
    result = import_feedback({**FEEDBACK, "tutorial_version": "no-such@v9"},
                             repository=active_repo, operations=operations, now=NOW)
    assert (result.status, result.object_id) == ("rejected", None)
    assert result.invalid_fields == ("tutorial_version",)
    assert every_key(active_repo) == before


def test_retired_tutorial_rejects_new_feedback(
        retired_repo: Repository, operations: OperationCoordinator) -> None:
    """Given 教學已退役／When 匯入回饋／Then `rejected(("tutorial_version",))` 且零寫入（Rule 2）。

    判斷來自 Phase 26 的 `assert_accepts_feedback`，本檔不比對訊息字串也不自己看 `status`。
    """
    before = every_key(retired_repo)
    result = import_feedback(FEEDBACK, repository=retired_repo, operations=operations, now=NOW)
    assert (result.status, result.invalid_fields) == ("rejected", ("tutorial_version",))
    assert every_key(retired_repo) == before


@pytest.mark.parametrize("bad_rating", [True, "4", 3.5, 0, 6])
def test_an_invalid_rating_is_rejected_and_writes_nothing(
        active_repo: Repository, operations: OperationCoordinator, bad_rating: object) -> None:
    """Given `rating` 不合法／When 匯入／Then `rejected(("rating",))` 且沒有建立 item（F51）。"""
    before = every_key(active_repo)
    result = import_feedback({**FEEDBACK, "rating": bad_rating}, repository=active_repo,
                             operations=operations, now=NOW)
    assert (result.status, result.invalid_fields) == ("rejected", ("rating",))
    assert every_key(active_repo) == before


def test_a_saved_feedback_closes_its_operation(
        active_repo: Repository, operations: OperationCoordinator) -> None:
    """Given 匯入成功／When 讀操作紀錄／Then `op-feedback-f_12` 是 `done`（設計 §14.1）。"""
    import_feedback(FEEDBACK, repository=active_repo, operations=operations, now=NOW)
    record = operations.load(operation_id_for("feedback", "f_12"))
    assert record is not None
    assert (record.status, record.kind, record.canonical_id) == ("done", "feedback", "f_12")
    assert record.project_id == DEFAULT_PROJECT_ID


# --- Task 3：View 去重與未完成操作續跑 ------------------------------------------


def test_same_view_triple_is_deduplicated(
        active_repo: Repository, operations: OperationCoordinator) -> None:
    """Given 同一組（版本、使用者、時間）送兩次／When 匯入／Then 第二次 `duplicate`。"""
    first = import_view(VIEW, repository=active_repo, operations=operations, now=NOW)
    second = import_view(VIEW, repository=active_repo, operations=operations, now=NOW)
    assert (first.status, second.status) == ("saved", "duplicate")
    assert second.object_id == first.object_id
    assert len(active_repo.list_views_of_version(V1)) == 1


def test_the_view_primary_key_is_the_sha256_of_the_triple(
        active_repo: Repository, operations: OperationCoordinator) -> None:
    """Given 一筆瀏覽紀錄／When 匯入／Then `object_id` 就是 `view_pk`（設計 §9.1）。"""
    result = import_view(VIEW, repository=active_repo, operations=operations, now=NOW)
    expected = view_pk(V1, "u_01", datetime(2026, 8, 2, 9, 0, tzinfo=UTC))
    assert result.object_id == expected
    assert parse_pk(expected)[0] == "VIEW" and len(parse_pk(expected)[1]) == 64


def test_a_different_ts_from_the_same_user_counts_again(
        active_repo: Repository, operations: OperationCoordinator) -> None:
    """Given 同一人同一版但時間不同／When 匯入／Then 兩筆都 `saved`（去重的是三元組）。"""
    later = {**VIEW, "ts": "2026-08-02T10:00:00Z"}
    statuses = [import_view(payload, repository=active_repo, operations=operations,
                            now=NOW).status for payload in (VIEW, later)]
    assert statuses == ["saved", "saved"]
    assert len(active_repo.list_views_of_version(V1)) == 2


def test_views_never_create_a_viewed_edge(
        active_repo: Repository, operations: OperationCoordinator) -> None:
    """Given 匯入一筆瀏覽紀錄／When 看那個 PK 底下的列／Then 只有 `META`（設計 §9.2）。"""
    result = import_view(VIEW, repository=active_repo, operations=operations, now=NOW)
    assert result.object_id is not None
    assert [str(row["SK"]) for row in active_repo.query_pk(result.object_id)] == ["META"]


def test_accepted_but_unwritten_view_operation_is_resumed(
        active_repo: Repository, operations: OperationCoordinator) -> None:
    """Given 操作已接受但 item 還沒寫成／When 重送／Then 續跑補寫，最後仍只有一筆（D-45）。"""
    operations.accept(accept_request_for(VIEW))     # 模擬寫 item 之前就中斷
    resumed = import_view(VIEW, repository=active_repo, operations=operations, now=NOW)
    assert resumed.status == "saved"
    assert len(active_repo.list_views_of_version(V1)) == 1


def test_accepted_but_unwritten_feedback_operation_is_resumed(
        active_repo: Repository, operations: OperationCoordinator) -> None:
    """Given 回饋的 operation 已接受、FEEDBACK item 還沒寫／When 重送／Then 補寫成 `saved`。"""
    operations.accept(AcceptOperation(
        operation_id=operation_id_for("feedback", "f_12"), kind="feedback",
        canonical_id="f_12", project_id=DEFAULT_PROJECT_ID, now=NOW))
    resumed = import_feedback(FEEDBACK, repository=active_repo, operations=operations, now=NOW)
    assert resumed.status == "saved"
    assert [item.id for item in active_repo.list_feedback_of_version(V1)] == ["f_12"]


def test_retired_tutorial_rejects_feedback_but_still_accepts_views(
        retired_repo: Repository, operations: OperationCoordinator) -> None:
    """Given 教學已退役／When 各匯入一筆／Then 回饋 `rejected`、瀏覽仍 `saved`（設計 §8.4）。

    瀏覽數是「重開票率」的分母，退役後一起擋掉會讓指標失真，所以 `import_view`
    刻意**不**查教學狀態。
    """
    rejected = import_feedback(FEEDBACK, repository=retired_repo, operations=operations, now=NOW)
    accepted = import_view(VIEW, repository=retired_repo, operations=operations, now=NOW)
    assert (rejected.status, rejected.invalid_fields) == ("rejected", ("tutorial_version",))
    assert accepted.status == "saved"
    assert len(retired_repo.list_views_of_version(V1)) == 1


def test_a_view_of_an_unpublished_version_is_saved(
        active_repo: Repository, operations: OperationCoordinator) -> None:
    """Given 指向 `published_at=None` 的 `@v3`／When 匯入／Then `saved`（驗收矩陣第一列）。"""
    result = import_view({**VIEW, "tutorial_version": V3}, repository=active_repo,
                         operations=operations, now=NOW)
    assert result.status == "saved"
    assert len(active_repo.list_views_of_version(V3)) == 1


@pytest.mark.parametrize(("change", "fields"), [
    ({"ts": None}, ("ts",)),
    ({"tutorial_version": "no-such@v9"}, ("tutorial_version",)),
    ({"user": "U_01"}, ("user",)),
])
def test_a_bad_view_is_rejected_and_writes_nothing(
        active_repo: Repository, operations: OperationCoordinator,
        change: dict[str, Any], fields: tuple[str, ...]) -> None:
    """Given 缺 `ts`／版本不存在／`user` 不合格式／When 匯入／Then `rejected` 且圖譜零變動。"""
    payload = {**VIEW, **change}
    if change.get("ts") is None and "ts" in change:
        payload.pop("ts")
    before = every_key(active_repo)
    result = import_view(payload, repository=active_repo, operations=operations, now=NOW)
    assert (result.status, result.object_id, result.invalid_fields) == ("rejected", None, fields)
    assert every_key(active_repo) == before


def test_import_view_accepts_without_an_explicit_now(
        active_repo: Repository, operations: OperationCoordinator) -> None:
    """Given 呼叫端沒給 `now`／When 匯入／Then 用 `now_utc()` 當接受時間，事件時間不受影響。"""
    result = import_view(VIEW, repository=active_repo, operations=operations)
    assert result.status == "saved"
    stored = active_repo.list_views_of_version(V1)
    assert [view.ts for view in stored] == [datetime(2026, 8, 2, 9, 0, tzinfo=UTC)]
    record = operations.load(operation_id_for("view", parse_pk(str(result.object_id))[1]))
    assert record is not None and record.status == "done"
    assert record.accepted_at is not None and record.accepted_at.microsecond == 0


def test_saving_views_leaves_no_proc_and_no_new_version(
        active_repo: Repository, operations: OperationCoordinator) -> None:
    """Given 匯入兩筆瀏覽紀錄／When 掃描／Then 零 `PROC#`、`VERSION#` 數量不變（Rule 31、8）。"""
    versions_before = {str(row["PK"]) for row in active_repo.scan_entity("VERSION")}
    import_view(VIEW, repository=active_repo, operations=operations, now=NOW)
    import_view({**VIEW, "user": "u_02"}, repository=active_repo, operations=operations, now=NOW)
    assert active_repo.scan_entity("PROC") == []
    assert {str(row["PK"]) for row in active_repo.scan_entity("VERSION")} == versions_before


# --- Task 4：`training-kb-import` 的 Lambda 入口 --------------------------------


@pytest.fixture
def wired_handler(active_repo: Repository, operations: OperationCoordinator,
                  monkeypatch: pytest.MonkeyPatch) -> Repository:
    """把 `import_._DEPS` 換成指向 moto 表的相依；`monkeypatch` 結束時自動還原。"""
    monkeypatch.setattr(import_, "_DEPS", Deps(operations=operations, now=lambda: NOW,
                                               repository=active_repo))
    return active_repo


def test_handler_imports_every_item_and_starts_no_pipeline(wired_handler: Repository) -> None:
    """Given 三筆回饋（兩筆合法、一筆 `rating=True`）／When 呼叫 handler／Then 逐筆回結果。

    一筆壞資料不影響其他筆，這正是設計 §7.1「指出欄位、允許修正」（F51）的形狀；
    整條路徑零 `PROC#` 變動（`ING` Rule 31），零 `StartExecution` 由 autouse fixture 守。
    """
    items = [FEEDBACK, {**FEEDBACK, "id": "f_13"}, {**FEEDBACK, "rating": True}]
    body = import_.handler({"kind": "feedback", "source": "widget-download", "items": items},
                           None)
    results = body["results"]
    assert isinstance(results, list)
    assert [row["status"] for row in results] == ["saved", "saved", "rejected"]
    assert results[2]["invalid_fields"] == ("rating",)
    assert results[2]["object_id"] is None
    assert (body["kind"], body["source"]) == ("feedback", "widget-download")
    assert wired_handler.scan_entity("PROC") == []
    assert [item.id for item in wired_handler.list_feedback_of_version(V1)] == ["f_12", "f_13"]


def test_handler_deduplicates_repeated_view_items(wired_handler: Repository) -> None:
    """Given 同一筆瀏覽紀錄在一個 batch 裡出現兩次／When 呼叫 handler／Then 第二筆 duplicate。"""
    body = import_.handler({"kind": "view", "source": "widget-download",
                            "items": [VIEW, VIEW]}, None)
    results = body["results"]
    assert isinstance(results, list)
    assert [row["status"] for row in results] == ["saved", "duplicate"]
    assert len(wired_handler.list_views_of_version(V1)) == 1


def test_handler_result_rows_are_json_serialisable(wired_handler: Repository) -> None:
    """Given handler 的回應／When `json.dumps`／Then `invalid_fields` 序列化成 array。"""
    body = import_.handler({"kind": "feedback", "items": [{**FEEDBACK, "rating": "4"}]}, None)
    assert json.loads(json.dumps(body))["results"][0]["invalid_fields"] == ["rating"]


@pytest.mark.parametrize("event", [{"kind": "tutorial", "items": []}, {"kind": "feedback"},
                                   {"kind": "feedback", "items": {}}, {"items": []}])
def test_handler_refuses_unknown_kind_or_missing_items(event: dict[str, Any]) -> None:
    """Given `kind` 不在四種內或 `items` 不是陣列／When 呼叫／Then `PermanentError`，零寫入。"""
    with pytest.raises(PermanentError):
        import_.handler(event, None)


def test_import_kinds_is_the_four_fixed_values() -> None:
    """Given `IMPORT_KINDS`／When 讀它／Then 就是 00A §6.8 的四個值。"""
    assert import_.IMPORT_KINDS == ("feedback", "view", "ticket", "release")


def test_the_ticket_branch_delegates_to_normalize_then_accept(
        wired_handler: Repository, monkeypatch: pytest.MonkeyPatch) -> None:
    """Given 一筆 ticket 匯入／When 呼叫 handler／Then 原樣交給 P32／P37 的六個 keyword 參數。

    `normalize_then_accept` 回的是 **`list[Acceptance]`**（D-73）：一個 PR 可展開成 n 筆
    子 Release，所以 `object_id` 取第一筆、訊息列出全部 operation ID，不丟掉其餘幾筆。
    """
    seen: list[dict[str, Any]] = []

    def fake(**kwargs: Any) -> list[Acceptance]:
        seen.append(kwargs)
        return [_acceptance("op-release-r_1"), _acceptance("op-release-r_2")]

    monkeypatch.setattr(import_, "normalize_then_accept", fake)
    body = import_.handler({"kind": "ticket", "items": [TICKET_ITEM]}, None)
    results = body["results"]
    assert isinstance(results, list)
    assert results[0]["status"] == "saved"
    assert "op-release-r_1, op-release-r_2" in results[0]["message"]
    assert set(seen[0]) == {"domain", "adapter", "event_type", "headers", "payload", "deadline"}
    assert seen[0]["headers"] == {"x-github-event": "issues"}   # header 一律小寫


def test_the_ticket_branch_needs_its_own_source_fields(wired_handler: Repository) -> None:
    """Given ticket 匯入缺 `adapter`／When 呼叫 handler／Then 整批 `PermanentError`（D-60）。

    `domain`／`adapter`／`event_type` 由匯出檔自己帶，**不從 payload 反推**。
    """
    broken = {key: value for key, value in TICKET_ITEM.items() if key != "adapter"}
    with pytest.raises(PermanentError, match="adapter"):
        import_.handler({"kind": "ticket", "items": [broken]}, None)


def test_a_batch_of_zero_items_is_accepted(wired_handler: Repository) -> None:
    """Given 空的 `items`／When 呼叫 handler／Then 回空結果，不是錯誤（維護者匯出空檔）。"""
    assert import_.handler({"kind": "feedback", "items": []}, None)["results"] == []


# --- Phase 43：匯入時判定並保存回饋類別 ------------------------------------------
#
# **O5 BLOCKED**：這裡用本檔自己的 `FakeWriter`，綠燈只代表**決策邏輯**與**呼叫次數**
# 正確，**不代表** Bedrock 可用。`calls` 刻意用 **dict** 記錄，形狀與
# `tests/unit/conftest.py::RecordingWriter` 相容（整合測試看不到那支 conftest，00A 要求
# 兩份形狀一致，否則呼叫次數的斷言會分岔）。

CLASSIFIED: dict[str, Any] = {**FEEDBACK, "id": "f_50", "rating": 2,
                              "comment": "第三步的按鈕在哪一頁？"}
"""未勾選類別、留言非空——決策表第 4 列，唯一會呼叫模型的那一列。"""


class FakeWriter:
    """本檔的假 `Writer`：只實作 `generate_json`，`calls` 與 `RecordingWriter` 同形（dict）。"""

    def __init__(self, reply: Mapping[str, object]) -> None:
        self.reply = dict(reply)
        self.calls: list[dict[str, Any]] = []
        self.request_attempts = 0

    def generate_json(self, system: str, user: str, schema: Mapping[str, Any], *,
                      operation_id: str, node: str) -> dict[str, Any]:
        self.request_attempts += 1
        self.calls.append({"kind": "generation", "operation_id": operation_id, "node": node,
                           "system": system, "user": user, "schema": dict(schema)})
        return dict(self.reply)


def saved_feedback(repository: Repository, feedback_id: str) -> Feedback:
    """讀回剛寫進去的那一筆；讀不到就讓測試當場失敗，不要回 `None` 往下傳。"""
    stored = repository.get_meta(feedback_pk(feedback_id), Feedback)
    assert stored is not None, feedback_id
    return stored


def test_import_saves_settled_category_and_resend_calls_no_model(
        active_repo: Repository, operations: OperationCoordinator) -> None:
    """Given 未勾選但有留言／When 匯入兩次／Then 存模型值，第二次 `duplicate` 且仍只呼叫一次。

    分類接在**永久去重之後**：放到 `accept` 之前的話，每次重送都會多一次 Bedrock 呼叫
    （`COL` Rule 6 的停止點）。
    """
    writer = FakeWriter({"category": "Button not found"})
    first = import_feedback(CLASSIFIED, repository=active_repo, operations=operations,
                            now=NOW, writer=writer)
    again = import_feedback(CLASSIFIED, repository=active_repo, operations=operations,
                            now=NOW, writer=writer)
    assert (first.status, again.status) == ("saved", "duplicate")
    assert saved_feedback(active_repo, "f_50").category == "Button not found"
    assert writer.request_attempts == 1
    assert writer.calls[0]["operation_id"] == operation_id_for("feedback", "f_50")
    assert writer.calls[0]["node"] == "classify_comment"


def test_a_checked_category_is_saved_verbatim_without_the_model(
        active_repo: Repository, operations: OperationCoordinator) -> None:
    """Given 勾選了核定類別／When 匯入／Then 原樣保存，模型呼叫數 0（`COL` Rule 4）。"""
    writer = FakeWriter({"category": "Missing information"})
    payload = {**CLASSIFIED, "id": "f_12", "category": "Button not found"}
    result = import_feedback(payload, repository=active_repo, operations=operations,
                             now=NOW, writer=writer)
    assert result.status == "saved"
    assert saved_feedback(active_repo, "f_12").category == "Button not found"
    assert writer.request_attempts == 0


def test_an_unapproved_checked_category_is_stored_as_pending(
        active_repo: Repository, operations: OperationCoordinator) -> None:
    """Given 勾選「介面太醜」／When 匯入／Then 存 `待分類`，不呼叫模型、不擴充核定表。"""
    writer = FakeWriter({"category": "Button not found"})
    payload = {**CLASSIFIED, "id": "f_52", "category": "介面太醜"}
    import_feedback(payload, repository=active_repo, operations=operations, now=NOW,
                    writer=writer)
    assert saved_feedback(active_repo, "f_52").category == "待分類"
    assert writer.request_attempts == 0
    assert active_repo.get_meta_item("CONFIG#feedback_categories") is None


def test_an_unapproved_model_answer_is_stored_as_pending(
        active_repo: Repository, operations: OperationCoordinator) -> None:
    """Given 模型回「操作太慢」／When 匯入／Then 存 `待分類`，而且沒有第二次 request。"""
    writer = FakeWriter({"category": "操作太慢"})
    import_feedback({**CLASSIFIED, "id": "f_53"}, repository=active_repo,
                    operations=operations, now=NOW, writer=writer)
    assert saved_feedback(active_repo, "f_53").category == "待分類"
    assert writer.request_attempts == 1


@pytest.mark.parametrize("comment", [None, "   "])
def test_a_rating_only_feedback_keeps_no_category_and_calls_no_model(
        active_repo: Repository, operations: OperationCoordinator,
        comment: str | None) -> None:
    """Given 只有評分（留言缺或全空白）／When 匯入／Then `category is None`，呼叫數 0。"""
    writer = FakeWriter({"category": "Button not found"})
    payload = {**CLASSIFIED, "id": "f_51", "rating": 5, "comment": comment}
    result = import_feedback(payload, repository=active_repo, operations=operations,
                             now=NOW, writer=writer)
    assert result.status == "saved"
    assert saved_feedback(active_repo, "f_51").category is None
    assert writer.request_attempts == 0


def test_the_configured_category_table_is_used_and_never_written(
        active_repo: Repository, operations: OperationCoordinator) -> None:
    """Given 維護者匯入了三類／When 匯入一筆留言／Then 用設定值，且設定 item 逐字不變。"""
    active_repo.put_meta_item("CONFIG#feedback_categories",
                              {"categories": ["Button not found", "Missing information",
                                              "步驟順序錯誤"]})
    before = active_repo.get_meta_item("CONFIG#feedback_categories")
    writer = FakeWriter({"category": "步驟順序錯誤"})
    import_feedback({**CLASSIFIED, "id": "f_54"}, repository=active_repo,
                    operations=operations, now=NOW, writer=writer)
    assert saved_feedback(active_repo, "f_54").category == "步驟順序錯誤"
    assert "步驟順序錯誤" in writer.calls[0]["user"]
    assert active_repo.get_meta_item("CONFIG#feedback_categories") == before


def test_a_resumed_feedback_is_classified_once_because_nothing_was_saved(
        active_repo: Repository, operations: OperationCoordinator) -> None:
    """Given 操作已接受但 FEEDBACK item 還沒寫／When 重送／Then 補寫時分類**一次**（D-45）。

    模型輸出從未保存過，所以續跑重算一次符合設計 §14.2「已保存的輸出才重用」。
    """
    operations.accept(AcceptOperation(
        operation_id=operation_id_for("feedback", "f_50"), kind="feedback",
        canonical_id="f_50", project_id=DEFAULT_PROJECT_ID, now=NOW))
    writer = FakeWriter({"category": "Missing information"})
    resumed = import_feedback(CLASSIFIED, repository=active_repo, operations=operations,
                              now=NOW, writer=writer)
    assert resumed.status == "saved"
    assert saved_feedback(active_repo, "f_50").category == "Missing information"
    assert writer.request_attempts == 1


def test_without_a_writer_the_import_only_settles_the_checked_value(
        active_repo: Repository, operations: OperationCoordinator) -> None:
    """Given 沒有接 writer（P42 單獨執行）／When 匯入／Then 勾選值照收斂、留言不分類。

    `writer=None` **不是** O5 BLOCKED 的替代方案，只是 P42 的既有行為。
    """
    import_feedback({**CLASSIFIED, "id": "f_55", "category": "介面太醜"},
                    repository=active_repo, operations=operations, now=NOW)
    import_feedback({**CLASSIFIED, "id": "f_56"}, repository=active_repo,
                    operations=operations, now=NOW)
    assert saved_feedback(active_repo, "f_55").category == "待分類"
    assert saved_feedback(active_repo, "f_56").category is None


def test_the_handler_hands_its_writer_to_the_feedback_import(
        active_repo: Repository, operations: OperationCoordinator,
        monkeypatch: pytest.MonkeyPatch) -> None:
    """Given `Deps.writer` 已接線／When 走 Lambda 入口／Then 留言真的被分類（雲端才會分類）。

    這一條守的是 `_import_one` 有沒有把 `writer` 傳下去：沒傳的話 CDK 上的
    `bedrock:InvokeModel` 就白加了，雲端的匯入 Lambda 永遠不分類留言。
    """
    writer = FakeWriter({"category": "Missing information"})
    monkeypatch.setattr(import_, "_DEPS", Deps(operations=operations, now=lambda: NOW,
                                               repository=active_repo, writer=writer))
    body = import_.handler({"kind": "feedback", "items": [CLASSIFIED]}, None)
    results = body["results"]
    assert isinstance(results, list) and results[0]["status"] == "saved"
    assert saved_feedback(active_repo, "f_50").category == "Missing information"
    assert writer.request_attempts == 1


# --- review 修正回合 1：重送的冪等收尾與 handler 的批次語意 ----------------------


def _flaky(target: object, name: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """讓某個方法**第一次**丟 `TransientError`，之後照常——模擬寫到一半斷掉。"""
    real = getattr(target, name)
    seen = {"calls": 0}

    def flaky(*args: Any, **kwargs: Any) -> Any:
        seen["calls"] += 1
        if seen["calls"] == 1:
            raise TransientError(f"{name} 第一次中斷")
        return real(*args, **kwargs)

    monkeypatch.setattr(target, name, flaky)


def test_feedback_whose_edge_write_failed_is_finished_on_resend(
        active_repo: Repository, operations: OperationCoordinator,
        monkeypatch: pytest.MonkeyPatch) -> None:
    """Given `put_meta` 成功、`put_edge` 斷掉／When 重送／Then 補上邊並關掉 operation。

    一筆回饋是**兩筆寫入**（metadata item ＋ `REFERS_TO` 邊）。舊版在這個狀態下重送會走
    duplicate 短路，邊永遠補不回來——而 `list_feedback_of_version` 只走 `by_target` GSI，
    沒有邊就等於這筆回饋永遠查不到，ledger 也永遠停在 `accepted`。
    """
    _flaky(active_repo, "put_edge", monkeypatch)
    with pytest.raises(TransientError):
        import_feedback(FEEDBACK, repository=active_repo, operations=operations, now=NOW)
    operation_id = operation_id_for("feedback", "f_12")
    stranded = operations.load(operation_id)
    assert active_repo.get_meta(feedback_pk("f_12"), Feedback) is not None  # item 寫進去了
    assert active_repo.list_feedback_of_version(V1) == []                   # 但查不到
    assert stranded is not None and stranded.status == "accepted"

    again = import_feedback(FEEDBACK, repository=active_repo, operations=operations, now=NOW)

    assert (again.status, again.object_id) == ("duplicate", "f_12")
    assert [item.id for item in active_repo.list_feedback_of_version(V1)] == ["f_12"]
    finished = operations.load(operation_id)
    assert finished is not None and finished.status == "done"


def test_resending_a_finished_feedback_adds_no_second_edge(
        active_repo: Repository, operations: OperationCoordinator) -> None:
    """Given 已經完整寫好的回饋／When 再送兩次／Then 邊仍然只有一條（收尾是冪等的）。"""
    for _ in range(3):
        import_feedback(FEEDBACK, repository=active_repo, operations=operations, now=NOW)
    rows = [str(row["SK"]) for row in active_repo.query_pk(feedback_pk("f_12"))]
    assert sorted(rows) == ["META", f"REFERS_TO#{version_pk(V1)}"]
    assert len(active_repo.list_feedback_of_version(V1)) == 1


def test_a_resent_feedback_keeps_the_stored_version_not_the_new_payload(
        active_repo: Repository, operations: OperationCoordinator) -> None:
    """Given 同一個 ID 改指 `@v2` 重送／When 匯入／Then 不會長出第二條邊（以表裡的現況為準）。

    `put_meta(create_only=True)` 讓表裡的那一筆說了算，所以重送的收尾也要用它的
    `tutorial_version`，不是這次 payload 解出來的。
    """
    import_feedback(FEEDBACK, repository=active_repo, operations=operations, now=NOW)
    again = import_feedback({**FEEDBACK, "tutorial_version": V2}, repository=active_repo,
                            operations=operations, now=NOW)
    assert again.status == "duplicate"
    assert [str(row["SK"]) for row in active_repo.query_pk(feedback_pk("f_12"))
            if str(row["SK"]) != "META"] == [f"REFERS_TO#{version_pk(V1)}"]
    assert active_repo.list_feedback_of_version(V2) == []


def test_view_whose_operation_never_closed_is_finished_on_resend(
        active_repo: Repository, operations: OperationCoordinator,
        monkeypatch: pytest.MonkeyPatch) -> None:
    """Given View 的 item 寫好了但 `complete` 斷掉／When 重送／Then operation 補成 `done`。"""
    _flaky(operations, "complete", monkeypatch)
    with pytest.raises(TransientError):
        import_view(VIEW, repository=active_repo, operations=operations, now=NOW)
    pk = view_pk(V1, "u_01", datetime(2026, 8, 2, 9, 0, tzinfo=UTC))
    operation_id = operation_id_for("view", parse_pk(pk)[1])
    stranded = operations.load(operation_id)
    assert stranded is not None and stranded.status == "accepted"

    again = import_view(VIEW, repository=active_repo, operations=operations, now=NOW)

    assert (again.status, again.object_id) == ("duplicate", pk)
    finished = operations.load(operation_id)
    assert finished is not None and finished.status == "done"
    assert len(active_repo.list_views_of_version(V1)) == 1


def test_handler_checks_every_item_shape_before_writing_anything(
        wired_handler: Repository) -> None:
    """Given 第二筆不是物件／When 呼叫 handler／Then 整批 `PermanentError`，第一筆也沒寫。

    形狀檢查要**全部做完**才進寫入迴圈：邊檢查邊寫的話前面那幾筆已經進表了，與
    「一筆都不寫」矛盾（review 修正回合 1 的 Important 2）。
    """
    before = every_key(wired_handler)
    with pytest.raises(PermanentError, match=r"items\[1\]"):
        import_.handler({"kind": "feedback", "items": [FEEDBACK, "壞掉的一筆"]}, None)
    assert every_key(wired_handler) == before
    assert wired_handler.list_feedback_of_version(V1) == []


def test_a_ticket_item_that_fails_normalization_only_rejects_itself(
        wired_handler: Repository, monkeypatch: pytest.MonkeyPatch) -> None:
    """Given 三筆 ticket、中間那筆正規化丟 `IngressError`／When 呼叫／Then 只有它 `rejected`。

    與 `feedback`／`view` 同一種語意：資料不合法只拒那一筆，其他筆照做（F51）。
    """
    calls = {"n": 0}

    def fake(**kwargs: Any) -> list[Acceptance]:
        calls["n"] += 1
        if calls["n"] == 2:
            raise IngressError("Ticket 必填欄位不完整", ("author",))
        return [_acceptance(f"op-ticket-t_{calls['n']}")]

    monkeypatch.setattr(import_, "normalize_then_accept", fake)
    body = import_.handler({"kind": "ticket", "items": [TICKET_ITEM] * 3}, None)
    results = body["results"]
    assert isinstance(results, list)
    assert [row["status"] for row in results] == ["saved", "rejected", "saved"]
    assert results[1]["invalid_fields"] == ("author",)
    assert results[1]["object_id"] is None


def test_the_whole_batch_shares_one_deadline(
        wired_handler: Repository, monkeypatch: pytest.MonkeyPatch) -> None:
    """Given 一批三筆 ticket／When 呼叫 handler／Then 三筆拿到**同一個** deadline。

    舊版在 `_import_one` 內每筆重算 `monotonic() + 300`，那個期限永遠不會到；
    期限必須在 handler 進入時算一次就往下傳（比照 `handlers/github_webhook.py`）。
    """
    seen: list[float] = []

    def fake(**kwargs: Any) -> list[Acceptance]:
        seen.append(float(kwargs["deadline"]))
        return [_acceptance(f"op-ticket-t_{len(seen)}")]

    monkeypatch.setattr(import_, "normalize_then_accept", fake)
    import_.handler({"kind": "ticket", "items": [TICKET_ITEM] * 3}, None)
    assert len(seen) == 3 and len(set(seen)) == 1


def test_the_deadline_prefers_the_lambda_remaining_time(
        wired_handler: Repository, monkeypatch: pytest.MonkeyPatch) -> None:
    """Given context 報告只剩 5 秒／When 呼叫 handler／Then 期限用那 5 秒，不是 300 秒。"""
    class _Context:
        def get_remaining_time_in_millis(self) -> int:
            return 5_000

    seen: list[float] = []

    def fake(**kwargs: Any) -> list[Acceptance]:
        seen.append(float(kwargs["deadline"]) - monotonic())
        return [_acceptance("op-ticket-t_1")]

    monkeypatch.setattr(import_, "normalize_then_accept", fake)
    import_.handler({"kind": "ticket", "items": [TICKET_ITEM]}, _Context())
    assert 0 < seen[0] <= 5.0


def test_the_handler_logs_only_counts(
        wired_handler: Repository, caplog: pytest.LogCaptureFixture) -> None:
    """Given 一批回饋／When 呼叫 handler／Then log 只有 kind、來源與計數，沒有 payload。"""
    with caplog.at_level(logging.INFO, logger=import_.__name__):
        import_.handler({"kind": "feedback", "source": "widget-download",
                         "items": [FEEDBACK, {**FEEDBACK, "rating": True}]}, None)
    messages = [record.getMessage() for record in caplog.records]
    assert any("saved=1" in line and "rejected=1" in line for line in messages), messages
    for line in messages:
        assert "u_01" not in line and "prepare-meeting" not in line


# --- review 修正回合 2：ticket／release 的形狀檢查也要在寫入前整批做完 ----------


@pytest.mark.parametrize(("broken", "match"), [
    ({key: value for key, value in TICKET_ITEM.items() if key != "domain"}, r"items\[1\]"),
    ({**TICKET_ITEM, "adapter": "  "}, r"items\[1\]"),
    ({**TICKET_ITEM, "payload": "不是物件"}, r"items\[1\]"),
])
def test_a_ticket_batch_with_a_bad_shape_starts_nothing_at_all(
        wired_handler: Repository, monkeypatch: pytest.MonkeyPatch,
        broken: dict[str, Any], match: str) -> None:
    """Given 第二筆的**形狀**壞掉／When 呼叫 handler／Then 整批 `PermanentError`、零啟動。

    形狀錯代表匯出檔本身壞了（缺可信入口設定、`payload` 不是物件），不是「這一筆資料
    不合法」。舊版把這兩個檢查留在寫入迴圈裡，壞在第 n 筆時前 n-1 筆**已經
    `StartExecution`** 了（review 修正回合 2）。
    """
    started: list[dict[str, Any]] = []

    def fake(**kwargs: Any) -> list[Acceptance]:
        started.append(kwargs)
        return [_acceptance("op-ticket-t_1")]

    monkeypatch.setattr(import_, "normalize_then_accept", fake)
    with pytest.raises(PermanentError, match=match):
        import_.handler({"kind": "ticket", "items": [TICKET_ITEM, broken]}, None)
    assert started == []


def test_a_feedback_batch_is_unaffected_by_the_ticket_shape_rules(
        wired_handler: Repository) -> None:
    """Given feedback batch 沒有 `domain`／`payload`／When 呼叫 handler／Then 照樣寫得進去。

    `ticket`／`release` 才要可信入口設定；預檢不得把那套規則套到固定匯入的兩種 kind 上。
    """
    body = import_.handler({"kind": "feedback", "items": [FEEDBACK]}, None)
    results = body["results"]
    assert isinstance(results, list) and results[0]["status"] == "saved"


# --- 修正波（final review A#6）：逐筆的失敗界線 -------------------------------


def test_a_permanent_error_only_rejects_its_own_item(
        wired_handler: Repository, monkeypatch: pytest.MonkeyPatch) -> None:
    """Given 中間那筆 `normalize_then_accept` 丟 `PermanentError`／Then 只有它 `rejected`。

    `normalize_then_accept` 在「沒有任何 canonical id」時丟的是 `PermanentError`（不是
    `IngressError`），原本會整批中止，前面已經寫進去、甚至已經 `StartExecution` 的那幾筆
    留在表裡——與 docstring 承諾的「整批 `PermanentError` 零寫入」矛盾（final review A#6）。
    """
    calls = {"n": 0}

    def fake(**kwargs: Any) -> list[Acceptance]:
        calls["n"] += 1
        if calls["n"] == 2:
            raise PermanentError("沒有任何 canonical id")
        return [_acceptance(f"op-ticket-t_{calls['n']}")]

    monkeypatch.setattr(import_, "normalize_then_accept", fake)
    body = import_.handler({"kind": "ticket", "items": [TICKET_ITEM] * 3}, None)
    results = body["results"]
    assert isinstance(results, list)
    assert [row["status"] for row in results] == ["saved", "rejected", "saved"]
    assert results[1]["invalid_fields"] == ()
    assert "canonical id" in str(results[1]["message"])


def test_a_coordination_error_only_rejects_its_own_item(
        wired_handler: Repository, monkeypatch: pytest.MonkeyPatch) -> None:
    """Given `put_meta` 的 create_only 競態丟 `CoordinationError`／Then 只有那一筆 `rejected`。"""
    calls = {"n": 0}

    def fake(**kwargs: Any) -> list[Acceptance]:
        calls["n"] += 1
        if calls["n"] == 1:
            raise CoordinationError("同一個 canonical id 被別人先建立了")
        return [_acceptance(f"op-ticket-t_{calls['n']}")]

    monkeypatch.setattr(import_, "normalize_then_accept", fake)
    body = import_.handler({"kind": "ticket", "items": [TICKET_ITEM] * 2}, None)
    results = body["results"]
    assert isinstance(results, list)
    assert [row["status"] for row in results] == ["rejected", "saved"]


def test_a_transient_error_still_aborts_the_whole_invocation(
        wired_handler: Repository, monkeypatch: pytest.MonkeyPatch) -> None:
    """Given 中間那筆丟 `TransientError`／Then 整次 invoke 失敗（呼叫端重送整批）。

    `TransientError` 是「重送有機會成功」，收斂成 `rejected` 會把一次可回復的故障寫成
    永久的資料錯誤；維護者重送整批時 O2 會把已寫入的那幾筆判成 `duplicate`。
    """
    calls = {"n": 0}

    def fake(**kwargs: Any) -> list[Acceptance]:
        calls["n"] += 1
        if calls["n"] == 2:
            raise TransientError("DynamoDB 節流")
        return [_acceptance(f"op-ticket-t_{calls['n']}")]

    monkeypatch.setattr(import_, "normalize_then_accept", fake)
    with pytest.raises(TransientError):
        import_.handler({"kind": "ticket", "items": [TICKET_ITEM] * 3}, None)
