"""Phase 56：Demo 種子的 schema、重算與核定紀錄。

**這一整支檔案處理的都是明示的合成資料**（`demo/seed/*.json` 每一份都帶
`"synthetic": true`）。測試綠燈只代表「載得起來、算得出來」，**不代表 O7 通過**——
O7 的第三個條件是維護者在 `demo/seed/approvals/<batch_id>.json` 上簽名，
程式沒有、也不得有任何賦值路徑。

fixture 放在本檔而不是 `tests/unit/conftest.py`：那支檔這一批只有 Phase 55 能動
（COMMON.md R3.6），而 Phase 23／24／26 本來就把共用器材留在使用它的測試檔。
`seed_dir` 一律把 `demo/seed/` 整份 `copytree` 到 `tmp_path`，所以**正本永遠不被測試改動**。
"""

import dataclasses
import json
import re
import shutil
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from demo.seed_loader import (
    cluster_demo_tickets,
    load_seed,
    seed_digest,
    verify_recipe,
)
from training_kb.analytics.ratings import average_rating
from training_kb.analytics.reopen import reopen_stats
from training_kb.errors import ContentError
from training_kb.models import Ticket

if TYPE_CHECKING:                                    # 只給型別註記用；執行期不需要
    from conftest import RecordingWriter

SEED_SOURCE = Path(__file__).resolve().parents[2] / "demo" / "seed"


@pytest.fixture
def seed_dir(tmp_path: Path) -> Path:
    """`demo/seed/` 的可寫副本；每個測試各拿一份。"""
    copy = tmp_path / "seed"
    shutil.copytree(SEED_SOURCE, copy)
    return copy


@pytest.fixture
def edit_seed(seed_dir: Path) -> Callable[[str, Callable[[Any], None]], Path]:
    """在副本上改一份種子檔：`mutate(payload)` 就地改，改完寫回，回傳種子目錄。"""
    def apply(name: str, mutate: Callable[[Any], None]) -> Path:
        path = seed_dir / name
        payload = json.loads(path.read_text(encoding="utf-8"))
        mutate(payload)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")
        return seed_dir
    return apply


@pytest.fixture
def seed_dir_with_two_features(edit_seed: Callable[[str, Callable[[Any], None]], Path]) -> Path:
    """A v1 第 1 步同時引用兩個 Feature。"""
    def mutate(payload: Any) -> None:
        payload["items"][0]["feature_id"] = "Open Meeting, Meeting List"
    return edit_seed("steps.json", mutate)


@pytest.fixture
def seed_dir_with_no_feature(edit_seed: Callable[[str, Callable[[Any], None]], Path]) -> Path:
    """A v1 第 1 步沒有引用任何 Feature。"""
    def mutate(payload: Any) -> None:
        payload["items"][0]["feature_id"] = ""
    return edit_seed("steps.json", mutate)


@pytest.fixture
def seed_dir_with_dangling_feedback(
    edit_seed: Callable[[str, Callable[[Any], None]], Path],
) -> Path:
    """第一筆回饋指向一個不存在的版本。"""
    def mutate(payload: Any) -> None:
        payload["items"][0]["tutorial_version"] = "prepare-meeting@v9"
    return edit_seed("feedback.json", mutate)


@pytest.fixture
def seed_dir_with_overlapping_batches(
    edit_seed: Callable[[str, Callable[[Any], None]], Path],
) -> Path:
    """`R012-B2` 改成從 `weekly-digest@v2` 起算，與 `R012-B1` 共用一個版本。"""
    def mutate(payload: Any) -> None:
        for item in payload["items"]:
            if item["batch_id"] == "R012-B2":
                item["before_version_id"] = "weekly-digest@v2"
                item["after_version_id"] = "weekly-digest@v3"
    return edit_seed("batches.json", mutate)


# --- Task 1：種子 schema 與載入 ----------------------------------------------


def test_load_seed_reads_all_entities_and_marks_synthetic(seed_dir: Path) -> None:
    """Given 完整種子目錄 When load_seed Then 十種實體齊全且整份標示為合成資料。"""
    bundle = load_seed(seed_dir)
    assert bundle.synthetic is True
    assert bundle.batch_label == "demo-seed-01"
    assert len(bundle.feedback) == 18 + 40          # A 的 18 筆 + weekly-digest 的 40 筆
    assert len(bundle.views) == 20 + 50
    assert {t.id for t in bundle.tickets} >= {"t_1001", "t_2001", "t_2101", "t_3001"}
    assert {r.rule_id for r in bundle.rules} == {"R-007", "R-012"}
    assert {b.batch_id for b in bundle.batches} == {"R007-B1", "R012-B1", "R012-B2"}


def test_every_seed_file_declares_itself_synthetic(seed_dir: Path) -> None:
    """Given 十份種子檔 When 逐份讀 Then 每一份都有 `synthetic: true` 與合成資料聲明。"""
    for path in sorted(seed_dir.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["synthetic"] is True, path.name
        assert "合成" in payload["_notice"], path.name


def test_load_seed_rejects_step_without_exactly_one_feature(
    seed_dir_with_two_features: Path,
) -> None:
    """Given 一步引用兩個 Feature When load_seed Then ContentError。"""
    with pytest.raises(ContentError):
        load_seed(seed_dir_with_two_features)


def test_load_seed_rejects_step_with_zero_features(seed_dir_with_no_feature: Path) -> None:
    """Given 一步沒有引用 Feature When load_seed Then ContentError。"""
    with pytest.raises(ContentError):
        load_seed(seed_dir_with_no_feature)


def test_load_seed_rejects_feedback_pointing_at_a_missing_version(
    seed_dir_with_dangling_feedback: Path,
) -> None:
    """Given 回饋指向不存在的版本 When load_seed Then ContentError。"""
    with pytest.raises(ContentError):
        load_seed(seed_dir_with_dangling_feedback)


def test_load_seed_rejects_two_batches_sharing_a_version(
    seed_dir_with_overlapping_batches: Path,
) -> None:
    """Given R-012 兩批共用 `weekly-digest@v2` When load_seed Then ContentError。"""
    with pytest.raises(ContentError) as caught:
        load_seed(seed_dir_with_overlapping_batches)
    assert "重疊" in str(caught.value)


def _sign(seed_dir: Path, *, digest: str | None = None) -> Path:
    """把三份核定紀錄填成「已簽名」——**只改 `tmp_path` 的副本，正本永遠不動**。

    簽名者刻意寫 `fixture-only-not-o7`（沿用 Phase 55 的做法）：它只是為了證明
    `o7_ready` 真的是三個布林的 `and`，**不代表**維護者核定過任何東西。
    """
    value = seed_digest(seed_dir) if digest is None else digest
    for path in sorted((seed_dir / "approvals").glob("*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        record.update({"approved_by": "fixture-only-not-o7",
                       "approved_at": "2026-09-14T00:00:00Z",
                       "seed_commit": value, "recipe_report_sha256": "0" * 64})
        path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")
    return seed_dir


@pytest.fixture
def seed_dir_with_wrong_rating(edit_seed: Callable[[str, Callable[[Any], None]], Path]) -> Path:
    """把 `f_19` 的 rating 從 3 改成 4：只有 A v1 的平均會變。"""
    def mutate(payload: Any) -> None:
        for item in payload["items"]:
            if item["id"] == "f_19":
                item["rating"] = 4
    return edit_seed("feedback.json", mutate)


@pytest.fixture
def seed_dir_missing_approved_by(seed_dir: Path) -> Path:
    """三份核定紀錄都簽好，只有 `R012-B2` 把 `approved_by` 整個欄位拿掉。"""
    _sign(seed_dir)
    path = seed_dir / "approvals" / "R012-B2.json"
    record = json.loads(path.read_text(encoding="utf-8"))
    del record["approved_by"]
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return seed_dir


# --- Task 2：verify_recipe 重算八個數字 --------------------------------------

EXPECTED = {
    "A v1 average": 2.875, "A v2 average": 4.4,
    "A v1 negative count": 8, "A v2 negative count": 2,
    "A v1 reopen count": 7, "A v2 reopen count": 2,
    "A v1 reopen rate": 0.7, "A v2 reopen rate": 0.2,
}


def test_verify_recipe_recomputes_all_eight_targets(seed_dir: Path) -> None:
    """Given 完整種子 When verify_recipe Then 八個目標數字都由原始資料算得出來。"""
    report = verify_recipe(load_seed(seed_dir))
    assert {c.name: c.expected for c in report.checks} == EXPECTED
    assert {c.name: c.actual for c in report.checks} == EXPECTED
    assert all(c.ok for c in report.checks)
    assert report.recompute_ok is True


def test_verify_recipe_fails_when_one_feedback_is_edited(seed_dir_with_wrong_rating: Path) -> None:
    """Given 改掉一筆評分 When verify_recipe Then 只有那一個 check 失敗。"""
    report = verify_recipe(load_seed(seed_dir_with_wrong_rating))
    assert report.recompute_ok is False
    assert [c.name for c in report.checks if not c.ok] == ["A v1 average"]


def test_seed_does_not_store_the_eight_numbers_as_source(seed_dir: Path) -> None:
    """Given 十份種子檔 When 搜尋目標數字 Then 種子裡只有原始資料，沒有預存的答案。

    `2.875`／`4.4`／`0.7`／`0.2` 只能出現在核定紀錄的 `recomputed`（給人核對用），
    不得出現在十份種子檔裡——那會讓「重算」變成「讀回自己寫的答案」。
    """
    for name in sorted(seed_dir.glob("*.json")):
        text = name.read_text(encoding="utf-8")
        assert "2.875" not in text, name.name
        assert "0.35" not in text, name.name


def test_weekly_digest_batches_recompute_their_documented_before_and_after(
    seed_dir: Path,
) -> None:
    """Given R-012 兩批的原始資料 When 用 P53／P54 重算 Then 3.8／3.8／3.5／3.9 與四個 rate。

    這四版是 `approvals/R012-B*.json` 的 `recomputed` 區塊的來源；配方數字必須自洽，
    否則維護者核對到的是兩份不同的答案。
    """
    bundle = load_seed(seed_dir)
    averages, rates = {}, {}
    for version in (row for row in bundle.versions if row.slug == "weekly-digest"):
        feedback = [f for f in bundle.feedback if f.tutorial_version == version.version_id]
        views = [v for v in bundle.views if v.tutorial_version == version.version_id]
        assert version.published_at is not None
        stats = reopen_stats(views, bundle.tickets, cluster_id="c58",
                             published_at=version.published_at)
        averages[version.version_id] = average_rating(feedback)
        rates[version.version_id] = stats.rate
    assert averages == {"weekly-digest@v1": 3.8, "weekly-digest@v2": 3.8,
                        "weekly-digest@v3": 3.5, "weekly-digest@v4": 3.9}
    assert rates == {"weekly-digest@v1": 0.4, "weekly-digest@v2": 0.3,
                     "weekly-digest@v3": 0.3, "weekly-digest@v4": 0.35}


def test_o7_is_ready_only_when_schema_recompute_and_approval_all_hold(seed_dir: Path) -> None:
    """Given 三個條件各缺一個 When verify_recipe Then `o7_ready` 只在三者皆真時為真。

    簽名用的是 `fixture-only-not-o7`，**只存在於 `tmp_path` 的副本**：這個測試證明的是
    `o7_ready` 真的是三個布林的 `and`，不是「維護者已經核定」。
    """
    unsigned = verify_recipe(load_seed(seed_dir))
    assert (unsigned.schema_ok, unsigned.recompute_ok) == (True, True)
    assert unsigned.missing_approvals == ("R007-B1", "R012-B1", "R012-B2")
    assert unsigned.o7_ready is False

    signed = verify_recipe(load_seed(_sign(seed_dir)))
    assert signed.approved_batch_ids == ("R007-B1", "R012-B1", "R012-B2")
    assert signed.missing_approvals == ()
    assert signed.o7_ready is True

    broken_schema = verify_recipe(dataclasses.replace(load_seed(seed_dir), features=()))
    assert (broken_schema.schema_ok, broken_schema.recompute_ok) == (False, True)
    assert broken_schema.o7_ready is False


def test_o7_is_not_ready_when_the_recompute_fails_even_after_signing(
    seed_dir_with_wrong_rating: Path,
) -> None:
    """Given 已簽名但資料被改過 When verify_recipe Then 重算失敗讓 `o7_ready` 為假。"""
    report = verify_recipe(load_seed(_sign(seed_dir_with_wrong_rating)))
    assert (report.schema_ok, report.recompute_ok, report.o7_ready) == (True, False, False)


def test_a_stale_seed_commit_counts_as_missing_approval(seed_dir: Path) -> None:
    """Given 簽名時的 `seed_commit` 對不上目前種子 When load_seed Then 視同未核定。"""
    report = verify_recipe(load_seed(_sign(seed_dir, digest="0" * 64)))
    assert set(report.missing_approvals) == {"R007-B1", "R012-B1", "R012-B2"}
    assert report.o7_ready is False


# --- Task 3：二十筆工單的分群路徑（不證明 O5） -------------------------------


class FakeTicketRepository:
    """`ensure_embedding`／`assign_cluster` 真正會用到的三個方法，全部在記憶體裡。

    **這支假 Repository 不連 AWS、也不呼叫 Bedrock。** 搭 `RecordingWriter` 的
    `FIXED_EMBEDDING` 跑出來的綠燈只證明「分群這條路徑接對了」，
    **不證明** O5 通過，也不是真實 embedding 的觀察值。
    """

    def __init__(self, tickets: Sequence[Ticket]) -> None:
        self.tickets: dict[str, Ticket] = {row.id: row for row in tickets}
        self.writes: list[str] = []

    def get_meta(self, pk: str, model: type[Any], *, consistent: bool = True) -> Any:
        return self.tickets.get(pk.removeprefix("TICKET#"))

    def put_meta(self, entity: Any, *, create_only: bool = True) -> None:
        self.tickets[entity.id] = entity
        self.writes.append(entity.id)

    def list_tickets(self, project_id: str) -> list[Ticket]:
        return [row for row in self.tickets.values() if row.project_id == project_id]


def test_seed_tickets_for_creation_have_no_precomputed_cluster(seed_dir: Path) -> None:
    """Given 種子 When 看二十筆建立教學用工單 Then `cluster_id`／`embedding` 都是 null。"""
    bundle = load_seed(seed_dir)
    creation = [t for t in bundle.tickets if t.id.startswith("t_10")]
    assert len(creation) == 20
    assert len({t.text for t in creation}) == 20
    assert all(t.cluster_id is None and t.embedding is None for t in creation)
    reopen = [t for t in bundle.tickets if t.id.startswith("t_2")]
    assert len(reopen) == 9
    assert all(t.cluster_id == "c12" for t in reopen)
    weekly = [t for t in bundle.tickets if t.id.startswith("t_3")]
    assert len(weekly) == 17
    assert all(t.cluster_id == "c58" for t in weekly)


def test_cluster_demo_tickets_embeds_each_ticket_once_and_only_writes_the_cluster(
    seed_dir: Path, fake_writer: "RecordingWriter",
) -> None:
    """Given 假 Writer When cluster_demo_tickets Then 二十筆各呼叫一次、只多了向量與群號。

    `FIXED_EMBEDDING` 讓二十筆的 cosine 都是 1.0，所以會落在同一個新群；
    既有的 `c12`／`c58` 佔住編號，新群號因此不是 `c1`（Phase 38 的 `new_cluster_id`）。
    """
    bundle = load_seed(seed_dir)
    repository = FakeTicketRepository(bundle.tickets)
    assigned = cluster_demo_tickets(bundle, writer=fake_writer,
                                    repository=repository, operation_id="demo-cluster-fake")
    assert len(assigned) == 20
    assert len(set(assigned.values())) == 1
    assert set(assigned.values()) == {"c59"}
    assert [call["kind"] for call in fake_writer.calls] == ["embedding"] * 20
    assert {call["node"] for call in fake_writer.calls} == {"ticket-embedding"}
    assert sorted(set(repository.writes)) == sorted(t.id for t in bundle.tickets
                                                    if t.id.startswith("t_10"))
    for before in bundle.tickets:
        after = repository.tickets[before.id]
        changed = {name for name in before.model_dump()
                   if getattr(before, name) != getattr(after, name)}
        assert changed <= {"cluster_id", "embedding"}, before.id


def test_the_committed_clustering_report_records_o5_as_blocked() -> None:
    """Given repo 裡的分群報告 When 讀它 Then status 是 BLOCKED、帶 AWS 錯誤原文、observed 為 null。

    這是 2026-09-14 實際執行 `demo/scripts/cluster_demo_tickets.py` 打到真實 Bedrock 的
    結果（O5 BLOCKED）。**skip 不等於 PASS，BLOCKED 也不等於 PASS**；有人把二十筆
    `cluster_id` 預填進種子、或補一份看起來跑過的 `tickets_clustered.json`，這裡就會紅。
    """
    report = json.loads((SEED_SOURCE / "clustering_report.json").read_text(encoding="utf-8"))
    assert report["status"] == "BLOCKED"
    assert report["observed"] is None and report["tickets"] == []
    assert "ValidationException" in report["upstream"]
    assert not (SEED_SOURCE / "tickets_clustered.json").exists()


def test_the_seed_digest_ignores_reports_and_approvals(seed_dir: Path) -> None:
    """Given 改了核定紀錄或分群報告 When seed_digest Then 雜湊不變。

    `seed_commit` 只能綁十份種子檔：把簽名檔或產物算進去，維護者一簽名就會讓自己的
    簽名失效，`recipe_report_sha256` 也永遠對不上。
    """
    before = seed_digest(seed_dir)
    (seed_dir / "clustering_report.json").write_text(
        json.dumps({"_notice": "合成", "synthetic": True, "status": "BLOCKED",
                    "observed": None, "tickets": []}, ensure_ascii=False), encoding="utf-8")
    _sign(seed_dir)
    assert seed_digest(seed_dir) == before
