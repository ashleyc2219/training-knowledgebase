"""Phase 56：Demo 種子的 schema、重算與核定紀錄。

**這一整支檔案處理的都是明示的合成資料**（`demo/seed/*.json` 每一份都帶
`"synthetic": true`）。測試綠燈只代表「載得起來、算得出來」，**不代表 O7 通過**——
O7 的第三個條件是維護者在 `demo/seed/approvals/<batch_id>.json` 上簽名，
程式沒有、也不得有任何賦值路徑。

fixture 放在本檔而不是 `tests/unit/conftest.py`：那支檔這一批只有 Phase 55 能動
（COMMON.md R3.6），而 Phase 23／24／26 本來就把共用器材留在使用它的測試檔。
`seed_dir` 一律把 `demo/seed/` 整份 `copytree` 到 `tmp_path`，所以**正本永遠不被測試改動**。
"""

import json
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from demo.seed_loader import load_seed
from training_kb.errors import ContentError

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
