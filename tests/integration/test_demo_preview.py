"""Phase 58 Task 2：同一批 B 工單的「規則關／開」隔離預覽（moto）。

Given 同一批 B（分享摘要）的工單文字與一條 candidate 規則 `R-007`
When 跑一次 `run_rule_toggle_preview`
Then 只多出 `demo/previews/<run_id>/off.md` 與 `on.md` 兩個**私有** key，
     DynamoDB 整張表逐 byte 不變、`site/` 前綴一個物件都沒動、指標數字一個都沒變。

**O5 BLOCKED**：真實 Bedrock 上這兩次 `generate_json` 會 `ValidationException: Operation
not allowed` → `PermanentError`。本檔的綠燈全部在 moto ＋ 假 Writer 上取得，只證明
「隔離寫入界線」這條路接對了，**不是** O5 通過的證據；現場演練的失敗照實記 BLOCKED，
並用 `Banner.fallback_reason` 標「目前顯示預先執行結果」。

種子是**明示的合成資料**，這裡的數字不代表任何真實使用者成效。
"""

import dataclasses
import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from demo.preview import PREVIEW_NODES, PREVIEW_PREFIX, PreviewResult, run_rule_toggle_preview
from demo.seed_loader import SeedBundle, apply_seed, load_seed
from training_kb.analytics.rules_metrics import applied_count
from training_kb.analytics.status_writer import apply_rule_status, load_validated_at
from training_kb.analytics.version import version_metrics
from training_kb.content import VersionPlan, create_version
from training_kb.errors import ObjectAlreadyExists, PermanentError
from training_kb.ingress import DEFAULT_FEEDBACK_CATEGORIES
from training_kb.models import AuthoringRule, RuleStatus, Ticket
from training_kb.pipelines.ticket import ALL_STEP_TYPES
from training_kb.repository import Repository
from training_kb.rules import applied_rule_ids, rules_for_content

SEED_DIR = Path(__file__).resolve().parents[2] / "demo" / "seed"
NOW = datetime(2026, 9, 14, tzinfo=UTC)
KEPT_SLUGS = ("prepare-meeting", "share-summary")
B_SLUG = "share-summary"
B_CLUSTER = "c31"
RUN_ID = "run-01"


class PreviewWriter:
    """只照腳本回 `TutorialDraft` 形狀 dict 的假 Writer（**不連 Bedrock**）。

    `tests/unit/conftest.py` 的 `RecordingWriter` 只在 `tests/unit/` 看得到，所以整合測試
    自備一個等價的最小版本（`tests/integration/test_demo_clustering.py::LocalWriter` 同樣做法）。
    """

    def __init__(self, replies: Sequence[Mapping[str, Any]]) -> None:
        self.replies = [dict(reply) for reply in replies]
        self.calls: list[dict[str, Any]] = []

    def embed(self, text: str, *, operation_id: str, node: str) -> list[float]:
        raise AssertionError("隔離預覽不呼叫 embedding")

    def generate_json(self, system: str, user: str, schema: Mapping[str, Any], *,
                      operation_id: str, node: str) -> dict[str, Any]:
        self.calls.append({"operation_id": operation_id, "node": node,
                           "system": system, "user": user})
        if not self.replies:
            raise AssertionError("PreviewWriter 沒有排好下一個 generate_json 回應")
        return self.replies.pop(0)

    def converse_with_tools(self, system: str, messages: Sequence[Any], tools: Sequence[Any], *,
                            operation_id: str, node: str) -> dict[str, Any]:
        raise AssertionError("隔離預覽不用工具迴圈")


def _draft(title: str) -> dict[str, Any]:
    """一份合成的 `TutorialDraft`；`feature_id` 全部取自種子既有的 Feature。"""
    return {"title": title, "problem": "想把整理好的會議重點分享出去，卻不知道從哪一頁產生連結。",
            "prerequisites": ["已經有一場產生過重點摘要的會議"],
            "expected_outcome": "同事會收到一個可以直接打開的重點連結。",
            "steps": [{"number": 1, "type": "click_ui", "text": "在會議頁點「分享」。",
                       "feature_id": "Share Link"},
                      {"number": 2, "type": "read", "text": "確認連結已經產生。",
                       "feature_id": "Share Summary"}]}


def _trim(bundle: SeedBundle) -> SeedBundle:
    """只留兩篇教學的版本與回饋／瀏覽，讓 moto 上的 `apply_seed` 從十秒級降到一秒內。

    工單、規則與 Feature **全留**：本檔要驗的就是「預覽不動規則與指標」。
    """
    keep = [index for index, version in enumerate(bundle.versions) if version.slug in KEPT_SLUGS]
    version_ids = {bundle.versions[index].version_id for index in keep}
    return dataclasses.replace(
        bundle,
        tutorials=tuple(row for row in bundle.tutorials if row.slug in KEPT_SLUGS),
        versions=tuple(bundle.versions[index] for index in keep),
        contents=tuple(bundle.contents[index] for index in keep),
        steps=tuple(row for row in bundle.steps if row.tutorial_version in version_ids),
        releases=(),
        feedback=tuple(row for row in bundle.feedback if row.tutorial_version in version_ids),
        views=tuple(row for row in bundle.views if row.tutorial_version in version_ids))


@pytest.fixture
def bundle() -> SeedBundle:
    return _trim(load_seed(SEED_DIR))


@pytest.fixture
def seeded(repository: Repository, bundle: SeedBundle) -> Repository:
    apply_seed(bundle, repository=repository, now=NOW)
    return repository


@pytest.fixture
def rule(bundle: SeedBundle) -> AuthoringRule:
    return next(row for row in bundle.rules if row.rule_id == "R-007")


@pytest.fixture
def tickets(bundle: SeedBundle) -> tuple[Ticket, ...]:
    """B（分享摘要）那一群的工單；種子的 `cluster_id` 還是 `None`（O5 BLOCKED），改用 ID 段。"""
    chosen = tuple(row for row in bundle.tickets if row.id.startswith("t_30"))
    assert chosen
    return chosen


@pytest.fixture
def writer() -> PreviewWriter:
    return PreviewWriter([_draft("分享摘要（規則關閉）"), _draft("分享摘要（規則開啟）")])


def dump_table(table: Any) -> list[dict[str, Any]]:
    """整張表的 item，依 PK／SK 排序後轉成可比較的 JSON 字串清單。"""
    rows: list[dict[str, Any]] = []
    kwargs: dict[str, Any] = {"ConsistentRead": True}
    while True:
        page = table.scan(**kwargs)
        rows += list(page.get("Items", ()))
        key = page.get("LastEvaluatedKey")
        if not key:
            return sorted((json.loads(json.dumps(row, default=str)) for row in rows),
                          key=lambda row: (str(row["PK"]), str(row["SK"])))
        kwargs["ExclusiveStartKey"] = key


def written_keys(bucket: Any) -> list[str]:
    return sorted(str(item.key) for item in bucket.objects.all())


def run_preview(tickets: Sequence[Ticket], rule: AuthoringRule, repository: Repository,
                writer: PreviewWriter, run_id: str = RUN_ID) -> PreviewResult:
    return run_rule_toggle_preview(tickets, rule=rule, repository=repository,
                                   writer=writer, run_id=run_id)


# --- MET Rule 12：同一批 Ticket 並排展示規則關閉與開啟 --------------------------


def test_rule_toggle_preview_writes_only_two_keys(
        seeded: Repository, bucket: Any, table: Any, tickets: tuple[Ticket, ...],
        rule: AuthoringRule, writer: PreviewWriter) -> None:
    """Given 同一批 B 工單 When 跑關／開預覽 Then 只多兩個私有 key，整張表逐 byte 不變。"""
    before_table = dump_table(table)
    before_keys = written_keys(bucket)
    result = run_preview(tickets, rule, seeded, writer)

    assert result.off_key == f"{PREVIEW_PREFIX}{RUN_ID}/off.md"
    assert result.on_key == f"{PREVIEW_PREFIX}{RUN_ID}/on.md"
    assert set(written_keys(bucket)) - set(before_keys) == {result.off_key, result.on_key}
    assert dump_table(table) == before_table
    assert result.model_calls == 2
    assert result.rule_id == rule.rule_id
    assert result.run_id == RUN_ID


def test_preview_uses_two_distinct_nodes_and_only_injects_the_rule_on_the_on_side(
        seeded: Repository, tickets: tuple[Ticket, ...], rule: AuthoringRule,
        writer: PreviewWriter) -> None:
    """Given 兩次呼叫 When 檢查 prompt Then node 不同、只有 on 那次的規則區塊有 `R-007`。"""
    run_preview(tickets, rule, seeded, writer)
    nodes = [call["node"] for call in writer.calls]
    assert nodes == list(PREVIEW_NODES)
    assert len(set(nodes)) == 2          # `call_breakdown` 的 by_node 才分得開
    off_prompt, on_prompt = (call["user"] for call in writer.calls)
    assert rule.rule_id not in off_prompt
    assert rule.rule_id in on_prompt


def test_preview_files_declare_synthetic_isolation_and_the_writer_class(
        seeded: Repository, tickets: tuple[Ticket, ...], rule: AuthoringRule,
        writer: PreviewWriter) -> None:
    """Given 兩份預覽 When 讀檔頭 Then 第一行固定標示隔離預覽，並寫出 run_id 與 writer 類別名。"""
    result = run_preview(tickets, rule, seeded, writer)
    for key, switch in ((result.off_key, "關閉"), (result.on_key, "開啟")):
        body = seeded.get_object(key)
        assert body is not None
        text = body.decode("utf-8")
        assert text.splitlines()[0] == "合成資料示範｜隔離預覽｜不寫入正式教學與統計"
        assert RUN_ID in text and switch in text
        assert "PreviewWriter" in text          # 一眼看出是假模型輸出，不是本次真的跑成功
        assert text.rstrip().endswith("。") or "## Expected Outcome" in text


# --- 污染防護 -----------------------------------------------------------------


def test_same_run_id_twice_is_blocked_and_writes_nothing_new(
        seeded: Repository, bucket: Any, tickets: tuple[Ticket, ...], rule: AuthoringRule,
        writer: PreviewWriter) -> None:
    """Given 同一個 `run_id` 已經跑過 When 再跑一次 Then `ObjectAlreadyExists` 且沒有新寫入。"""
    run_preview(tickets, rule, seeded, writer)
    after_first = written_keys(bucket)
    writer.replies.append(_draft("不該被寫出去的重跑"))
    with pytest.raises(ObjectAlreadyExists):
        run_preview(tickets, rule, seeded, writer)
    assert written_keys(bucket) == after_first


def test_preview_leaves_rules_and_applied_projection_untouched(
        seeded: Repository, tickets: tuple[Ticket, ...], rule: AuthoringRule,
        writer: PreviewWriter) -> None:
    """Given 預覽 When 跑完 Then 每條規則的 status 與 `applied_to` 長度都沒有變。"""
    before = {row.rule_id: (row.status, len(row.applied_to)) for row in seeded.list_rules()}
    run_preview(tickets, rule, seeded, writer)
    after = {row.rule_id: (row.status, len(row.applied_to)) for row in seeded.list_rules()}
    assert after == before
    assert before["R-007"][0] is RuleStatus.CANDIDATE     # 預覽不會讓 candidate 變成已有效


def test_preview_leaves_version_metrics_identical(
        seeded: Repository, tickets: tuple[Ticket, ...], rule: AuthoringRule,
        writer: PreviewWriter) -> None:
    """Given 預覽 When 跑完 Then 同一版的 `VersionMetrics` 逐欄位相同（指標沒被污染）。"""
    def metrics(version_id: str) -> Any:
        return version_metrics(version_id, repository=seeded,
                               approved=DEFAULT_FEEDBACK_CATEGORIES, project_id="demo")

    before = {vid: metrics(vid) for vid in ("prepare-meeting@v1", "prepare-meeting@v2")}
    run_preview(tickets, rule, seeded, writer)
    assert {vid: metrics(vid) for vid in before} == before
    assert before["prepare-meeting@v1"].reopen.count == 7
    assert before["prepare-meeting@v1"].reopen.viewers == 10


def test_preview_does_not_touch_the_public_site_prefix(
        seeded: Repository, bucket: Any, tickets: tuple[Ticket, ...], rule: AuthoringRule,
        writer: PreviewWriter) -> None:
    """Given 預覽 When 跑完 Then `site/` 前綴的物件數量不變（本 Phase 不對 O3 下任何結論）。"""
    before = [key for key in written_keys(bucket) if key.startswith("site/")]
    run_preview(tickets, rule, seeded, writer)
    after = [key for key in written_keys(bucket) if key.startswith("site/")]
    assert after == before
    assert PREVIEW_PREFIX.startswith("demo/previews/")


# --- D-68：正式套用走的是另一條路，預覽不進效果統計 -----------------------------


def test_active_rule_reaches_a_formal_version_while_the_preview_does_not(
        seeded: Repository, bundle: SeedBundle, tickets: tuple[Ticket, ...],
        rule: AuthoringRule, writer: PreviewWriter) -> None:
    """Given `R-007` 轉 active When 走正式建版 Then 新版的 `rules_applied` 含 `R-007`；預覽不計入。

    現況核對：種子的 `R-012` 也是 active（`applies_when=read`），而 `create_first_version`
    走的是 `rules_for_content(..., ALL_STEP_TYPES, ...)`，所以正式版本的 `rules_applied`
    是 `["R-007", "R-012"]`——D-68 字面上的 `== ["R-007"]` 在這份種子下不成立。
    可觀察結果改成「`R-007` 確實被注入並記進 `rules_applied`，而且 `applied_count` 只被
    正式版本加一、不被兩份預覽加」。
    """
    # 現況核對：種子把 `R-012` 直接寫成 active，卻沒有 `operations/rules/validated_at.json`，
    # 所以剛種好的表上，任何走 `rules_for_content` 的正式寫作路徑都會當場 PermanentError。
    # 這是 P56 種子與 P19 選取規則之間的缺口，本檔先把它證出來再補齊（見報告 §9）。
    with pytest.raises(PermanentError, match="R-012"):
        rules_for_content(seeded.list_rules(RuleStatus.ACTIVE), ALL_STEP_TYPES,
                          load_validated_at(seeded))
    for rule_id in ("R-007", "R-012"):
        apply_rule_status(rule_id, RuleStatus.ACTIVE, repository=seeded, now=NOW)

    before_applied = applied_count(seeded.list_versions_of_tutorial(B_SLUG), "R-007")
    run_preview(tickets, rule, seeded, writer)
    assert applied_count(seeded.list_versions_of_tutorial(B_SLUG), "R-007") == before_applied

    by_type = rules_for_content(seeded.list_rules(RuleStatus.ACTIVE), ALL_STEP_TYPES,
                                load_validated_at(seeded))
    injected = list({row.rule_id: row for step_type in ALL_STEP_TYPES
                     for row in by_type[step_type]}.values())
    assert applied_rule_ids(injected) == ["R-007", "R-012"]

    content = next(content for version, content in zip(bundle.versions, bundle.contents,
                                                       strict=True)
                   if version.version_id == f"{B_SLUG}@v1")
    plan = VersionPlan(version_id=f"{B_SLUG}@v2", slug=B_SLUG, number=2,
                       supersedes=f"{B_SLUG}@v1", reason=f"gap:{B_CLUSTER}",
                       rules_applied=tuple(applied_rule_ids(injected)),
                       operation_id="op-ticket-analysis-demo-b")
    created = create_version(plan, content, seeded)
    assert "R-007" in created.rules_applied
    assert applied_count(seeded.list_versions_of_tutorial(B_SLUG), "R-007") == before_applied + 1
