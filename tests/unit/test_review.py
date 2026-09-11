"""定期 Feedback Review：對齊 docs/spec/features/定期優化Tutorial.feature 的 10 條 Rule。

LLM 一律 monkeypatch，不打外部服務；模板降級路徑另外測。
"""

import json
from pathlib import Path

import pytest

from app.agent import feedback_review
from app.agent.llm import LLMUnavailable
from app.analytics.local_db import LocalDB
from app.analytics.metrics import avg_rating
from app.errors import OperationFailed
from app.ingest.feedback import seed_feedback

STEPS_V1 = (
    '1. Open your orders. 2. Select the order. 3. Click "Cancel Order". '
    "4. Confirm cancellation."
)
STEPS_V2 = (
    "1. Open your orders. 2. Select the order. 3. On the order details page, locate the "
    'Cancel Order button beside the order status and click "Cancel Order". This starts '
    "cancellation for that order. 4. Confirm cancellation."
)
REASON_V2 = "Repeated feedback indicates Step 3 lacks context."

LLM_V2 = {
    "title": "Cancel Order",
    "problem": "The customer wants to cancel an existing order.",
    "prerequisites": "The customer has an account and an open order.",
    "steps": STEPS_V2,
    "expected_outcome": "The order is cancelled.",
    "reason": REASON_V2,
}


@pytest.fixture
def db(tmp_path):
    d = LocalDB(path=str(tmp_path / "t.db"))
    d.init_schema()
    return d


@pytest.fixture
def md_path(tmp_path):
    return str(tmp_path / "cancel-order.md")


def _tutorial(db, path, current_version="v1", last_action="CREATE", outdated=0,
              status="published"):
    db.execute(
        "INSERT INTO Tutorial (tutorial_id, feature_id, user_problem_id, path, status,"
        " current_version, is_possibly_outdated, is_obsolete, last_action)"
        " VALUES (1, 1, 1, :path, :status, :cv, :outdated, 0, :la)",
        {"path": path, "status": status, "cv": current_version, "outdated": outdated,
         "la": last_action},
    )


def _version(db, version, steps=STEPS_V1, supersedes="", reason=""):
    db.execute(
        "INSERT INTO TutorialVersion (tutorial_id, tutorial_version, title, problem,"
        " prerequisites, steps, expected_outcome, reason, supersedes_version, created_at)"
        " VALUES (1, :v, 'Cancel Order', 'The customer wants to cancel an existing order.',"
        " 'The customer has an account and an open order.', :steps, 'The order is cancelled.',"
        " :reason, :sup, '2026-09-01T10:00:00Z')",
        {"v": version, "steps": steps, "sup": supersedes, "reason": reason},
    )


def _feedback(db, ratings, version="v1", category="指示不清楚"):
    for i, rating in enumerate(ratings, start=1):
        cat = category[i - 1] if isinstance(category, list) else category
        db.execute(
            "INSERT INTO Feedback (tutorial_id, tutorial_version, rating, feedback_category,"
            " comment, submitter_id, timestamp)"
            " VALUES (1, :v, :r, :c, 'Step 3 很難懂。', 'alice@example.com', :ts)",
            {"v": version, "r": rating, "c": cat, "ts": f"2026-09-0{i}T10:00:00Z"},
        )


def _tutorial_row(db):
    return db.run_sql("SELECT * FROM Tutorial WHERE tutorial_id = 1")[0]


def _versions(db):
    return db.run_sql("SELECT * FROM TutorialVersion WHERE tutorial_id = 1 ORDER BY tutorial_version")


def _fake_llm(monkeypatch, payload=None, exc=None):
    def fake(prompt, schema_hint):
        if exc is not None:
            raise exc
        return dict(payload)

    monkeypatch.setattr("app.agent.llm.complete_json", fake)


# --- Rule: 三條件成立時 REFINE 並發布新版本 ---


def test_三條件成立時產生v2(db, md_path, monkeypatch):
    _tutorial(db, md_path)
    _version(db, "v1")
    _feedback(db, [2, 3, 3])  # avg 2.67、3 筆、同 category 3 筆
    _fake_llm(monkeypatch, LLM_V2)

    results = feedback_review.review_all(db)

    assert [(r["tutorial_id"], r["action"]) for r in results] == [(1, "REFINE")]
    assert results[0]["from_version"] == "v1"
    assert results[0]["to_version"] == "v2"
    assert results[0]["reason"] == REASON_V2

    tut = _tutorial_row(db)
    assert (tut["current_version"], tut["last_action"], tut["status"]) == ("v2", "REFINE", "published")
    assert (tut["is_possibly_outdated"], tut["is_obsolete"]) == (0, 0)

    versions = _versions(db)
    assert [v["tutorial_version"] for v in versions] == ["v1", "v2"]
    v1, v2 = versions
    assert v1["steps"] == STEPS_V1 and v1["supersedes_version"] == "" and v1["reason"] == ""
    assert v2["steps"] == STEPS_V2
    assert v2["supersedes_version"] == "v1"
    assert v2["reason"] == REASON_V2
    assert v2["created_at"]

    md = Path(md_path).read_text(encoding="utf-8")
    assert "<!-- version: v2 -->" in md
    assert "## Expected Outcome" in md
    assert "Cancel Order button beside the order status" in md


def test_過去結果改變未來行為_current_version改變(db, md_path, monkeypatch):
    _tutorial(db, md_path)
    _version(db, "v1")
    _feedback(db, [2, 3, 3])
    _fake_llm(monkeypatch, LLM_V2)

    assert _tutorial_row(db)["current_version"] == "v1"
    feedback_review.review_all(db)
    assert _tutorial_row(db)["current_version"] == "v2"


# --- Rule: 平均 rating 小於 3.5 才進入 REFINE ---


def test_平均剛好三點五時KEEP(db, md_path, monkeypatch):
    _tutorial(db, md_path)
    _version(db, "v1")
    _feedback(db, [3, 3, 4, 4])  # avg 3.5
    _fake_llm(monkeypatch, LLM_V2)

    results = feedback_review.review_all(db)

    assert results[0]["action"] == "KEEP"
    tut = _tutorial_row(db)
    assert (tut["current_version"], tut["last_action"]) == ("v1", "KEEP")
    assert len(_versions(db)) == 1


def test_平均四點零時KEEP(db, md_path, monkeypatch):
    _tutorial(db, md_path)
    _version(db, "v1")
    _feedback(db, [4, 4, 4], category="其他")
    _fake_llm(monkeypatch, LLM_V2)

    assert feedback_review.review_all(db)[0]["action"] == "KEEP"
    assert _tutorial_row(db)["current_version"] == "v1"


# --- Rule: 平均 rating 只計算 current_version 的 Feedback ---


def test_只算current_version的Feedback(db, md_path, monkeypatch):
    _tutorial(db, md_path, current_version="v2", last_action="REFINE")
    _version(db, "v1")
    _version(db, "v2", steps=STEPS_V2, supersedes="v1", reason=REASON_V2)
    _feedback(db, [1, 1, 1], version="v1")
    _feedback(db, [5, 5, 5], version="v2", category="其他")
    _fake_llm(monkeypatch, LLM_V2)

    results = feedback_review.review_all(db)

    assert results[0]["action"] == "KEEP"
    tut = _tutorial_row(db)
    assert (tut["current_version"], tut["last_action"]) == ("v2", "KEEP")


# --- Rule: Feedback 數量 >= 3 才 REFINE ---


def test_只有兩筆時KEEP(db, md_path, monkeypatch):
    _tutorial(db, md_path)
    _version(db, "v1")
    _feedback(db, [2, 3])
    _fake_llm(monkeypatch, LLM_V2)

    assert feedback_review.review_all(db)[0]["action"] == "KEEP"
    assert len(_versions(db)) == 1


# --- Rule: 不得因單一低分立刻修改 ---


def test_只有一筆低分時KEEP(db, md_path, monkeypatch):
    _tutorial(db, md_path)
    _version(db, "v1")
    _feedback(db, [1])
    _fake_llm(monkeypatch, LLM_V2)

    assert feedback_review.review_all(db)[0]["action"] == "KEEP"


def test_沒有任何Feedback時KEEP(db, md_path, monkeypatch):
    _tutorial(db, md_path)
    _version(db, "v1")
    _fake_llm(monkeypatch, LLM_V2)

    assert feedback_review.review_all(db)[0]["action"] == "KEEP"
    assert _tutorial_row(db)["last_action"] == "KEEP"


# --- Rule: 同一 feedback_category 至少 2 筆才是 recurring complaints ---


def test_三筆不同category時KEEP(db, md_path, monkeypatch):
    _tutorial(db, md_path)
    _version(db, "v1")
    _feedback(db, [2, 2, 2], category=["指示不清楚", "缺少資訊", "Tutorial 太長"])
    _fake_llm(monkeypatch, LLM_V2)

    assert feedback_review.review_all(db)[0]["action"] == "KEEP"
    assert len(_versions(db)) == 1


# --- Rule: is_possibly_outdated 為 true 本輪 KEEP ---


def test_可能過期時本輪KEEP且旗標保持(db, md_path, monkeypatch):
    _tutorial(db, md_path, outdated=1)
    _version(db, "v1")
    _feedback(db, [2, 3, 3])
    _fake_llm(monkeypatch, LLM_V2)

    assert feedback_review.review_all(db)[0]["action"] == "KEEP"
    tut = _tutorial_row(db)
    assert (tut["current_version"], tut["is_possibly_outdated"], tut["last_action"]) == (
        "v1", 1, "KEEP",
    )


# --- REFINE 後再 Review ---


def test_REFINE後再Review為KEEP(db, md_path, monkeypatch):
    _tutorial(db, md_path)
    _version(db, "v1")
    _feedback(db, [2, 3, 3])
    _fake_llm(monkeypatch, LLM_V2)

    feedback_review.review_all(db)
    second = feedback_review.review_all(db)

    assert second[0]["action"] == "KEEP"
    tut = _tutorial_row(db)
    assert (tut["current_version"], tut["last_action"]) == ("v2", "KEEP")
    assert len(_versions(db)) == 2


# --- 五欄缺一：本篇完全不動 ---


def test_五欄缺一時操作失敗且不改Tutorial(db, md_path, monkeypatch):
    _tutorial(db, md_path)
    _version(db, "v1")
    _feedback(db, [2, 3, 3])
    broken = dict(LLM_V2)
    broken["title"] = ""
    _fake_llm(monkeypatch, broken)

    with pytest.raises(OperationFailed):
        feedback_review.review_all(db)

    tut = _tutorial_row(db)
    assert (tut["current_version"], tut["last_action"]) == ("v1", "CREATE")
    assert len(_versions(db)) == 1
    assert not Path(md_path).exists()


# --- LLM 不可用時走模板降級 ---


def test_LLM不可用時走模板改寫(db, md_path, monkeypatch):
    _tutorial(db, md_path)
    _version(db, "v1")
    _feedback(db, [2, 3, 3])
    _fake_llm(monkeypatch, exc=LLMUnavailable("no key"))

    results = feedback_review.review_all(db)

    assert results[0]["action"] == "REFINE"
    assert results[0]["source"] == "template"
    assert results[0]["reason"] == REASON_V2
    v2 = _versions(db)[1]
    assert v2["steps"] != STEPS_V1
    assert "Cancel Order" in v2["steps"]
    assert Path(md_path).read_text(encoding="utf-8").count("<!-- version: v2 -->") == 1


# --- retired 不進 Review ---


def test_retired的Tutorial不進Review(db, md_path, monkeypatch):
    _tutorial(db, md_path, status="retired")
    _version(db, "v1")
    _feedback(db, [1, 1, 1])
    _fake_llm(monkeypatch, LLM_V2)

    assert feedback_review.review_all(db) == []


# --- 端到端：v1 種子 → REFINE → v2 種子 → 2.9 到 4.4 ---


def test_端到端_2點9到4點4(db, md_path, monkeypatch):
    _tutorial(db, md_path)
    _version(db, "v1")
    assert seed_feedback(db, Path("data/seed/feedback_seed.json")) == 10
    assert avg_rating(db, 1) == 2.9

    _fake_llm(monkeypatch, exc=LLMUnavailable("no key"))
    results = feedback_review.review_all(db)
    assert results[0]["action"] == "REFINE"
    assert _tutorial_row(db)["current_version"] == "v2"

    assert seed_feedback(db, Path("data/seed/feedback_v2_seed.json")) == 5
    assert avg_rating(db, 1) == 4.4

    assert feedback_review.review_all(db)[0]["action"] == "KEEP"
