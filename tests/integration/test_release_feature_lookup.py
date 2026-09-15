"""Phase 49 Task 3：用真實 `Repository` 類別 + **moto** 表驗證一致讀取與樂觀鎖。

**Given** 表裡有三筆 Feature、**When** 改完名立刻用**舊名**定位、**Then** 回到同一個節點，
而且全程走基表一致讀取——`NoWriter` 保證它不是靠語意層矇對的。第二條證明這條寫入路徑真的
走 Phase 06 的 revision compare-and-swap，不是後到的覆蓋先到的。

`repository` 是 `tests/integration/conftest.py` 的 fixture，跑在 **moto**（region us-west-2）
上，**不連真實帳號**：這裡的 PASS 只證明資料形狀與條件寫入邏輯。真實帳號的
`FEATURE#Prepare` 逐欄比對（`aws dynamodb get-item --consistent-read`）已移交 **P52 §6
可實證路徑表**（COMMON.md R1）。語意定位的真實 Bedrock 證據因 **O5 BLOCKED** 取不到
（`docs/plan/report/o5-20260915T030245Z.md`），所以本檔不新增語意層案例、也不加
`xfail(strict=True)`。
"""

from datetime import UTC, datetime

import pytest

from training_kb.errors import CoordinationError, PermanentError
from training_kb.keys import feature_pk
from training_kb.models import Feature, Release
from training_kb.pipelines.release import locate_feature, update_feature_aliases

FIXED_TS = datetime(2026, 9, 14, 3, 0, 0, tzinfo=UTC)


class NoWriter:
    """字串層就該命中，所以這個替身只負責在被呼叫時讓測試爆掉。"""

    def embed(self, text: str, *, operation_id: str, node: str) -> list[float]:
        raise AssertionError(f"字串層就該命中，不應該呼叫 Bedrock：{text!r} @ {node}")


@pytest.fixture
def features(repository):
    """§2 的起始狀態：`Prepare` 還掛著舊顯示名稱，另外兩筆是名稱與 `feature_id` 相同的對照組。"""
    rows = [
        Feature(feature_id="Prepare", name="Meeting Summary", aliases=[], first_seen=FIXED_TS),
        Feature(feature_id="Share", name="Share", aliases=[], first_seen=FIXED_TS),
        Feature(feature_id="Notify", name="Notify", aliases=[], first_seen=FIXED_TS),
    ]
    for row in rows:
        repository.put_meta(row)
    return rows


@pytest.fixture
def renamed_release():
    """與 Task 1 相同的 `r_42`：`Meeting Summary` 改名成 `Prepare`。"""
    return Release(id="r_42", source="github_pr", feature="Prepare", kind="renamed",
                   old_name="Meeting Summary", new_name="Prepare",
                   evidence="PR #42：Meeting Summary 改名為 Prepare", ts=FIXED_TS)


def test_locate_feature_reads_back_the_alias_it_just_wrote(repository, features, renamed_release):
    """`REL` Rule 2：Given 剛改完名 When 用舊名定位 Then 回同一個 `FEATURE#Prepare`。"""
    before = repository.get_feature("Prepare")
    assert (before.name, before.aliases) == ("Meeting Summary", [])

    update_feature_aliases(before, old_name="Meeting Summary", new_name="Prepare",
                           repository=repository)

    found = locate_feature(renamed_release, repository=repository,
                           writer=NoWriter(), operation_id="op-release-r_42")
    assert (found.feature_id, found.name, found.aliases) == (
        "Prepare", "Prepare", ["Meeting Summary"])


def test_whole_item_changes_only_name_aliases_and_revision(repository, features):
    """人工驗收（可實證路徑）：Given 改名前後的**整筆 item** When 逐欄比對 Then 只差三個欄位。"""
    pk = feature_pk("Prepare")
    before = repository.get_meta_item(pk)

    update_feature_aliases(repository.get_feature("Prepare"), old_name="Meeting Summary",
                           new_name="Prepare", repository=repository)
    after = repository.get_meta_item(pk)

    assert before["PK"] == after["PK"] == "FEATURE#Prepare"
    assert before["SK"] == after["SK"] == "META"
    assert (before["name"], before["aliases"]) == ("Meeting Summary", [])
    assert (after["name"], after["aliases"]) == ("Prepare", ["Meeting Summary"])
    assert after["_revision"] == before["_revision"] + 1
    assert {key for key in before if before[key] != after.get(key)} == {"name", "aliases",
                                                                       "_revision"}
    assert set(before) == set(after)


def test_stale_expected_revision_cannot_overwrite(repository, features):
    """Given 拿舊 revision 再寫一次 When `update_meta` Then `CoordinationError`，資料不被覆蓋。"""
    pk = feature_pk("Prepare")
    stale = repository.revision_of(pk)

    repository.update_meta(pk, {"name": "Prepare"}, expected_revision=stale)

    with pytest.raises(CoordinationError, match="stale revision"):
        repository.update_meta(pk, {"name": "Wrong"}, expected_revision=stale)
    assert repository.get_feature("Prepare").name == "Prepare"


def test_alias_clash_leaves_the_real_table_untouched(repository, features):
    """D07：Given 新名稱撞到別的 Feature When 更新 Then 整筆 item 與 `_revision` 都沒動。"""
    pk = feature_pk("Prepare")
    share_pk = feature_pk("Share")
    repository.update_meta(share_pk, {"aliases": ["prepare"]},
                           expected_revision=repository.revision_of(share_pk))
    before = repository.get_meta_item(pk)

    with pytest.raises(PermanentError, match="衝突"):
        update_feature_aliases(repository.get_feature("Prepare"), old_name="Meeting Summary",
                               new_name="Prepare", repository=repository)

    assert repository.get_meta_item(pk) == before


def test_exact_layer_hits_the_feature_whose_name_equals_its_id(repository, features):
    """Given `changed` 只有 `feature` 一個鍵 When 它等於某筆的 `name` Then 第 1 層就命中。"""
    changed = Release(id="r_43", source="changelog", feature="Share", kind="changed",
                      evidence="changelog：Share 的行為調整", ts=FIXED_TS)

    found = locate_feature(changed, repository=repository, writer=NoWriter(),
                           operation_id="op-release-r_43")

    assert found is not None and found.feature_id == "Share"


def test_string_layers_miss_falls_through_to_the_semantic_layer(repository, features):
    """Given 前兩層都對不上 When 定位 Then 才輪到語意層——這裡用 `NoWriter` 讓它現形。

    語意層本身的門檻與平手規則由 `tests/unit/test_release_locate_feature.py` 的假向量驗；
    **O5 BLOCKED**，真實 Bedrock 不可用，這裡只證明「順序是對的」。
    """
    orphan = Release(id="r_44", source="changelog", feature="Nowhere", kind="changed",
                     evidence="changelog：圖譜裡沒有的功能", ts=FIXED_TS)

    with pytest.raises(AssertionError, match="不應該呼叫 Bedrock"):
        locate_feature(orphan, repository=repository, writer=NoWriter(),
                       operation_id="op-release-r_44")
