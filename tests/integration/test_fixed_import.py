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

from collections.abc import Iterator, Mapping
from datetime import UTC, datetime
from typing import Any

import pytest

from training_kb import ingress
from training_kb.clock import to_iso
from training_kb.config import DEFAULT_PROJECT_ID
from training_kb.ingress import (
    import_feedback,
    import_view,
    operation_id_for,
    validate_view,
)
from training_kb.keys import feedback_pk, parse_pk, version_pk, view_pk
from training_kb.models import Tutorial, TutorialStatus, TutorialVersion
from training_kb.operations import AcceptOperation, OperationCoordinator
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
