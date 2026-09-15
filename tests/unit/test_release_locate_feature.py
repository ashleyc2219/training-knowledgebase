"""Phase 49 Task 1：Release 的三層 Feature 定位（完全相同字串 → 正規化 → 語意 `>= 0.85`）。

**Given** 圖譜裡已經有若干 Feature、**When** 一則已正規化的 Release 進來、**Then** 程式要先用
名稱與 alias 命中，全部落空才呼叫 Titan，而且採用與否由程式的 `0.85` 決定、不由模型決定。

這支檔的 `fake_writer` 是**區域** fixture，刻意同名覆寫 `tests/unit/conftest.py` 的 P15
`RecordingWriter`（那支只有固定向量、沒有 `cosine_for`／`embed_calls`，而且依 COMMON.md R3.6
只有 P55 能改）。pytest 以最近的定義為準，所以覆寫只影響本檔。

**O5 BLOCKED**（`docs/plan/report/o5-20260915T030245Z.md`：Titan／Claude 皆
`ValidationException: Operation not allowed`）：本檔的語意層全部跑在假向量上，綠燈**不代表**
語意定位已在真實 Bedrock 驗證。
"""

import math
from collections.abc import Callable
from datetime import UTC, datetime

import pytest

from training_kb.config import Thresholds
from training_kb.errors import PermanentError
from training_kb.keys import META, feature_pk
from training_kb.models import Feature, Release
from training_kb.pipelines.release import (
    FEATURE_MATCH_THRESHOLD,
    locate_feature,
    normalize_feature_name,
)
from training_kb.repository import DynamoItem
from training_kb.writing.client import TITAN_DIMENSIONS

FIXED_TS = datetime(2026, 9, 14, 3, 0, 0, tzinfo=UTC)
"""工廠造出的 `Feature.first_seen`／`Release.ts`：UTC 整秒（`models.py` 拒收帶微秒的 datetime）。"""

QUERY_NODE = "locate_feature_query"
CANDIDATE_NODE = "locate_feature_candidate"
"""語意層兩個 `node` 名稱；`fake_writer` 靠它分辨「查詢那一次」與「候選那一次」。"""


def feature(feature_id: str, *, name: str, aliases: list[str]) -> Feature:
    return Feature(feature_id=feature_id, name=name, aliases=aliases, first_seen=FIXED_TS)


def _release(kind: str, *, old_name: str | None, new_name: str | None) -> Release:
    return Release(id="r_42", source="github_pr", feature="Prepare", kind=kind,
                   old_name=old_name, new_name=new_name,
                   evidence="PR #42：Meeting Summary 改名為 Prepare", ts=FIXED_TS)


class ScoredWriter:
    """只實作 `Writer.embed` 的替身：把文字換成**單位向量**，讓真 `cosine` 算出指定分數。

    查詢文字固定回 `[1.0] + [0.0] * 1023`，候選回 `[s, sqrt(1 - s * s)] + [0.0] * 1022`，
    所以 `cosine(query, candidate)` 剛好等於 `s`（0.85／0.8499 兩個邊界都是精確值，不會被
    浮點誤差推過門檻）。`cosine_for` 的鍵只要是候選文字的子字串就算命中，所以測試可以用
    `feature_id` 當鍵；同一段文字對到兩個鍵是測試寫錯，直接讓它爆掉而不是隨便挑一個。
    """

    def __init__(self) -> None:
        self.cosine_for: dict[str, float] = {}
        self.embed_calls: list[tuple[str, str]] = []

    def embed(self, text: str, *, operation_id: str, node: str) -> list[float]:
        self.embed_calls.append((text, node))
        if node == QUERY_NODE:
            return [1.0] + [0.0] * (TITAN_DIMENSIONS - 1)
        score = self._score(text)
        return [score, math.sqrt(1.0 - score * score)] + [0.0] * (TITAN_DIMENSIONS - 2)

    def _score(self, text: str) -> float:
        hits = [key for key in self.cosine_for if key in text]
        if len(hits) > 1:
            raise AssertionError(f"cosine_for 的鍵 {hits} 同時對到候選文字 {text!r}")
        return self.cosine_for[hits[0]] if hits else 0.0


class FakeRepository:
    """假 `Repository`：只有定位會用到的兩個方法，行為與 Phase 06／08／27 的真實版本對齊。

    `scan_entity` 回的是 **raw item**（含 `PK`／`SK`／`entity` 保留屬性）而且會多塞一筆
    `REFERENCES#` 邊，這樣「先濾 `SK == META` 再 `item_to_model`」漏掉時測試會直接
    `ValidationError`，不是靜靜通過。
    """

    def __init__(self) -> None:
        self.features: list[Feature] = []
        self.lookup_calls: list[str] = []
        self.scan_calls: list[tuple[str, bool]] = []

    def find_feature_by_name_or_alias(self, name: str) -> Feature | None:
        """照 `repository.py:find_feature_by_name_or_alias`：先比 `name` 再比 `aliases`。"""
        self.lookup_calls.append(name)
        rows = sorted(self.features, key=lambda item: item.feature_id)
        exact = [item for item in rows if item.name == name]
        hits = exact or [item for item in rows if name in item.aliases]
        if not exact and len(hits) > 1:
            raise PermanentError(f"alias {name} 同時屬於 {len(hits)} 個 Feature")
        return hits[0] if hits else None

    def scan_entity(self, entity: str, *, consistent: bool = True,
                    meta_only: bool = True) -> list[DynamoItem]:
        self.scan_calls.append((entity, consistent))
        rows: list[DynamoItem] = []
        for item in self.features:
            pk = feature_pk(item.feature_id)
            payload: DynamoItem = dict(item.model_dump(mode="json"))
            rows.append({"PK": pk, "SK": META, "entity": entity, "_revision": 1, **payload})
            if not meta_only:
                rows.append({"PK": pk, "SK": f"REFERENCES#{pk}", "entity": entity,
                             "target": pk, "_revision": 1})
        return rows


@pytest.fixture
def fake_writer() -> ScoredWriter:
    """區域覆寫：本檔要的是會記 `embed_calls` 並算得出指定 cosine 的替身，不是 P15 的固定向量。"""
    return ScoredWriter()


@pytest.fixture
def fake_repo() -> FakeRepository:
    return FakeRepository()


@pytest.fixture
def renamed_release() -> Release:
    """§2 的 `r_42`：`Meeting Summary` 改名成 `Prepare`。"""
    return _release("renamed", old_name="Meeting Summary", new_name="Prepare")


@pytest.fixture
def changed_release() -> Release:
    """同一則 Release 但 `kind="changed"`，兩個名稱欄位都是 `None`（P31 只對 renamed 強制）。"""
    return _release("changed", old_name=None, new_name=None)


@pytest.fixture
def locate() -> Callable[..., Feature | None]:
    """把四個關鍵字參數收在一處，測試只寫「誰查誰」。"""

    def run(release: Release, *, repository: FakeRepository, writer: ScoredWriter,
            operation_id: str = "op-r42") -> Feature | None:
        return locate_feature(release, repository=repository, writer=writer,
                              operation_id=operation_id)

    return run


def test_threshold_is_an_alias_of_the_config_field():
    """Given 門檻只能有一份 When 讀模組常數 Then 它就是 `Thresholds.cosine_match`（D-35）。"""
    assert FEATURE_MATCH_THRESHOLD == Thresholds().cosine_match


@pytest.mark.parametrize(("raw", "expected"), [
    ("  Meeting Summary  ", "meeting summary"),
    ("PREPARE", "prepare"),
    ("Prepare", "prepare"),
])
def test_normalize_feature_name_strips_and_casefolds(raw, expected):
    """Given 前後空白與大小寫 When 正規化 Then 只去頭尾空白＋casefold，中間空白保留。"""
    assert normalize_feature_name(raw) == expected


def test_alias_hit_does_not_call_the_model(fake_repo, fake_writer, renamed_release, locate):
    """`REL` Rule 2：Given 舊名在 aliases When 定位 Then 回 `FEATURE#Prepare` 且零次 embed。"""
    fake_repo.features = [feature("Prepare", name="Prepare", aliases=["Meeting Summary"])]

    found = locate(renamed_release, repository=fake_repo, writer=fake_writer)

    assert found is not None and found.feature_id == "Prepare"
    assert fake_repo.find_feature_by_name_or_alias("Meeting Summary").feature_id == "Prepare"
    assert fake_repo.find_feature_by_name_or_alias("Prepare").feature_id == "Prepare"
    assert fake_writer.embed_calls == []


def test_lookup_keys_try_old_name_first_and_drop_duplicates(fake_repo, fake_writer,
                                                            renamed_release, locate):
    """Given `feature` 與 `new_name` 是同一個字串 When 定位 Then 查詢順序是舊名、新名各一次。"""
    fake_repo.features = [feature("Prepare", name="Prepare", aliases=[])]

    found = locate(renamed_release, repository=fake_repo, writer=fake_writer)

    assert found is not None and found.feature_id == "Prepare"
    assert fake_repo.lookup_calls == ["Meeting Summary", "Prepare"]
    assert fake_writer.embed_calls == []


def test_case_and_space_only_difference_hits_the_second_layer(fake_repo, fake_writer, locate):
    """Given 只差大小寫與前後空白 When 定位 Then 第 2 層命中，仍然零次 embed。"""
    fake_repo.features = [feature("Prepare", name="  meeting   summary ".strip(), aliases=[])]
    release = _release("renamed", old_name="Meeting   Summary", new_name="Prepare")

    found = locate(release, repository=fake_repo, writer=fake_writer)

    assert found is not None and found.feature_id == "Prepare"
    assert fake_writer.embed_calls == []
    assert fake_repo.scan_calls == [("FEATURE", True)]


def test_second_layer_rejects_one_name_pointing_at_two_features(fake_repo, fake_writer, locate):
    """Given 同一個正規化名稱對到兩個 Feature When 定位 Then `PermanentError`，不隨便挑一個。"""
    fake_repo.features = [feature("Prepare", name="Meeting Summary", aliases=[]),
                          feature("Share", name="meeting summary", aliases=[])]
    release = _release("renamed", old_name="  Meeting Summary  ", new_name="Prepare")

    with pytest.raises(PermanentError, match="Feature"):
        locate(release, repository=fake_repo, writer=fake_writer)
    assert fake_writer.embed_calls == []


def test_first_layer_alias_clash_is_propagated(fake_repo, fake_writer, renamed_release, locate):
    """Given 同一個 alias 屬於兩個 Feature When 第 1 層查詢 Then `PermanentError` 往上拋（D07）。"""
    fake_repo.features = [feature("Prepare", name="Prepare", aliases=["Meeting Summary"]),
                          feature("Share", name="Share", aliases=["Meeting Summary"])]

    with pytest.raises(PermanentError, match="Meeting Summary"):
        locate(renamed_release, repository=fake_repo, writer=fake_writer)


@pytest.mark.parametrize(("score", "expected"), [(0.8499, None), (0.85, "Share")])
def test_semantic_match_needs_at_least_the_threshold(fake_repo, fake_writer, changed_release,
                                                     locate, score, expected):
    """`REL` Rule 4：Given 前兩層落空 When cosine 是 `0.8499`／`0.85` Then 前 `None` 後採用。"""
    fake_repo.features = [feature("Share", name="Share Summary", aliases=[])]
    fake_writer.cosine_for = {"Share": score}

    found = locate(changed_release, repository=fake_repo, writer=fake_writer,
                   operation_id="op-edge")

    assert (found.feature_id if found else None) == expected
    assert [node for _, node in fake_writer.embed_calls] == [QUERY_NODE, CANDIDATE_NODE]


def test_semantic_tie_picks_the_smallest_feature_id(fake_repo, fake_writer, changed_release,
                                                    locate):
    """Given 兩個 Feature 同為 `0.90` When 定位 Then 取 `feature_id` 升序最小者，重跑相同。"""
    fake_repo.features = [feature("Share", name="Share Summary", aliases=[]),
                          feature("Notify", name="Notify Summary", aliases=[])]
    fake_writer.cosine_for = {"Share Summary": 0.90, "Notify Summary": 0.90}

    first = locate(changed_release, repository=fake_repo, writer=fake_writer)
    second = locate(changed_release, repository=fake_repo, writer=fake_writer)

    assert first is not None and first.feature_id == "Notify"
    assert second is not None and second.feature_id == first.feature_id


def test_no_feature_at_all_skips_even_the_query_embedding(fake_repo, fake_writer,
                                                          changed_release, locate):
    """本計畫選擇：Given 表裡一個 Feature 都沒有 When 定位 Then 直接 `None`，連查詢向量都不算。"""
    assert locate(changed_release, repository=fake_repo, writer=fake_writer) is None
    assert fake_writer.embed_calls == []


def test_candidate_text_covers_name_and_aliases(fake_repo, fake_writer, changed_release, locate):
    """Given 候選有 alias When 進語意層 Then 候選文字含 name 與排序後的 aliases，且只算一次。"""
    fake_repo.features = [feature("Share", name="Share Summary", aliases=["Zeta", "Alpha"])]
    fake_writer.cosine_for = {"Share Summary": 0.90}

    found = locate(changed_release, repository=fake_repo, writer=fake_writer)

    assert found is not None and found.feature_id == "Share"
    candidates = [text for text, node in fake_writer.embed_calls if node == CANDIDATE_NODE]
    assert candidates == ["Share Summary / Alpha / Zeta"]
