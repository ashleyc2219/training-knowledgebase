"""Phase 47：candidate 規則提出與溯源。

對應 `PRP` Rule 1–5（同類至少五筆不同 Feedback 才可提案、`evidence` 可逐筆回查、
`applies_when` 記錄適用範圍、`derived_from` 恰一個來源版本、`rule` 記錄歸納出的寫作要求）
與 `REV` Rule 9（Feedback Review 是唯一提出 Authoring Rule 的 pipeline）。

O5 BLOCKED，所以模型一律用本檔自己的假 `Writer`（形狀與 `tests/unit/conftest.py` 的
`RecordingWriter` 相容，但**不取名 `fake_writer`**，避免蓋掉既有 fixture）。
O7 未到，所以本檔只斷言「已提出（`status=candidate`）」，不斷言任何 active／retired
行為——狀態轉移是 Phase 55 的事。
"""

from training_kb.models import Feedback
from training_kb.pipelines.feedback import CandidateGroup, candidate_groups

APPROVED = frozenset({"找不到按鈕", "缺少資訊"})


def fb(fid: str, version_id: str, category: str | None, rating: int = 2) -> Feedback:
    """`category=None` 的案例靠非空 `comment` 滿足 D-66 的 `carries_signal`。"""
    return Feedback(id=fid, tutorial_version=version_id, rating=rating, category=category,
                    comment="第三步沒有指出按鈕在哪一頁與位置", user=f"u_{fid}", ts=None)


def test_four_is_not_enough_but_five_is() -> None:
    """Given 同版同類四筆／五筆，When 分組，Then 只有五筆那次湊得出一組證據。"""
    feedback = [fb(f"f_{n}", "prepare-meeting@v1", "找不到按鈕") for n in range(1, 5)]
    assert candidate_groups(feedback, APPROVED) == ()
    feedback.append(fb("f_5", "prepare-meeting@v1", "找不到按鈕"))
    assert candidate_groups(feedback, APPROVED) == (
        CandidateGroup("prepare-meeting@v1", "找不到按鈕",
                       ("f_1", "f_2", "f_3", "f_4", "f_5")),
    )


def test_three_plus_two_across_versions_is_not_a_group() -> None:
    """Given v1 三筆加 v2 兩筆同類，When 分組，Then 不得跨版湊足門檻（設計 F25）。"""
    feedback = [fb(f"f_{n}", "prepare-meeting@v1", "找不到按鈕") for n in range(1, 4)]
    feedback += [fb(f"f_{n}", "prepare-meeting@v2", "找不到按鈕") for n in range(4, 6)]
    assert candidate_groups(feedback, APPROVED) == ()


def test_duplicate_ids_and_unapproved_categories_do_not_count() -> None:
    """Given 同一個 ID 重複五次／未核定類別，When 分組，Then 都湊不出證據。"""
    same = [fb("f_1", "prepare-meeting@v1", "找不到按鈕")] * 5
    assert candidate_groups(same, APPROVED) == ()
    mixed = [fb(f"f_{n}", "prepare-meeting@v1", "待分類") for n in range(1, 5)]
    mixed += [fb("f_9", "prepare-meeting@v1", None)]
    assert candidate_groups(mixed, APPROVED) == ()
