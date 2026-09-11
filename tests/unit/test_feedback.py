"""收集 Feedback 寫入：對齊 docs/spec/features/收集Feedback.feature 的 7 條 Rule。

全部走 LocalDB（sqlite），不連外部服務。
"""

import json
from pathlib import Path

import pytest

from app.agent.rules import FEEDBACK_CATEGORIES
from app.analytics.local_db import LocalDB
from app.analytics.metrics import avg_rating
from app.errors import OperationFailed
from app.ingest.feedback import collect_feedback, seed_feedback

STEPS_V1 = (
    '1. Open your orders. 2. Select the order. 3. Click "Cancel Order". '
    "4. Confirm cancellation."
)
STEPS_V2 = (
    "1. Open your orders. 2. Select the order. 3. On the order details page, locate the "
    'Cancel Order button beside the order status and click "Cancel Order". This starts '
    "cancellation for that order. 4. Confirm cancellation."
)


def _tutorial(db, current_version="v1", last_action="CREATE"):
    db.execute(
        "INSERT INTO Tutorial (tutorial_id, feature_id, user_problem_id, path, status,"
        " current_version, is_possibly_outdated, is_obsolete, last_action)"
        " VALUES (1, 1, 1, 'tutorials/cancel-order.md', 'published', :cv, 0, 0, :la)",
        {"cv": current_version, "la": last_action},
    )


def _version(db, version, steps=STEPS_V1, supersedes=""):
    db.execute(
        "INSERT INTO TutorialVersion (tutorial_id, tutorial_version, title, problem,"
        " prerequisites, steps, expected_outcome, reason, supersedes_version, created_at)"
        " VALUES (1, :v, 'Cancel Order', 'The customer wants to cancel an existing order.',"
        " 'The customer has an account and an open order.', :steps, 'The order is cancelled.',"
        " '', :sup, '2026-09-01T10:00:00Z')",
        {"v": version, "steps": steps, "sup": supersedes},
    )


@pytest.fixture
def db(tmp_path):
    d = LocalDB(path=str(tmp_path / "t.db"))
    d.init_schema()
    _tutorial(d)
    _version(d, "v1")
    return d


def _payload(**kwargs):
    base = {
        "tutorial_id": 1,
        "tutorial_version": "v1",
        "rating": 3,
        "timestamp": "2026-09-11T10:00:00Z",
    }
    base.update(kwargs)
    return {k: v for k, v in base.items() if v is not ...}


def _rows(db):
    return db.run_sql("SELECT * FROM Feedback ORDER BY id")


# --- Rule: rating 必須為 1 到 5 的整數 ---


@pytest.mark.parametrize("rating", [1, 5])
def test_rating邊界值提交成功(db, rating):
    fid = collect_feedback(db, _payload(rating=rating))
    assert fid == 1
    assert _rows(db)[0]["rating"] == rating


@pytest.mark.parametrize("rating", [0, 6, "3", 3.5, True, None])
def test_rating不合法時操作失敗且不入庫(db, rating):
    with pytest.raises(OperationFailed):
        collect_feedback(db, _payload(rating=rating))
    assert _rows(db) == []


def test_未填rating時操作失敗(db):
    payload = _payload()
    payload.pop("rating")
    with pytest.raises(OperationFailed):
        collect_feedback(db, payload)
    assert _rows(db) == []


# --- Rule: feedback_category 允許六類與「其他」，未填存空字串 ---


@pytest.mark.parametrize("category", FEEDBACK_CATEGORIES)
def test_七類category皆可提交(db, category):
    collect_feedback(db, _payload(feedback_category=category))
    assert _rows(db)[0]["feedback_category"] == category


def test_未填category時存空字串(db):
    collect_feedback(db, _payload())
    assert _rows(db)[0]["feedback_category"] == ""


def test_非法category時操作失敗(db):
    with pytest.raises(OperationFailed):
        collect_feedback(db, _payload(feedback_category="按鈕太小"))
    assert _rows(db) == []


# --- Rule: comment 可空，未填存空字串 ---


def test_未填comment時存空字串(db):
    collect_feedback(db, _payload())
    assert _rows(db)[0]["comment"] == ""


def test_comment有值時原樣存入(db):
    collect_feedback(db, _payload(comment="Step 3 很難懂。"))
    assert _rows(db)[0]["comment"] == "Step 3 很難懂。"


# --- Rule: Feedback 必須包含 tutorial_id、tutorial_version、rating、timestamp ---


@pytest.mark.parametrize("missing", ["tutorial_id", "timestamp"])
def test_缺必填欄位時操作失敗(db, missing):
    payload = _payload()
    payload.pop(missing)
    with pytest.raises(OperationFailed):
        collect_feedback(db, payload)
    assert _rows(db) == []


# --- Rule: Feedback 存進 Database ---


def test_提交成功後各欄可查(db):
    fid = collect_feedback(
        db,
        _payload(
            rating=2,
            feedback_category="指示不清楚",
            comment="Step 3 很難懂。",
            submitter_id="alice@example.com",
        ),
    )
    row = _rows(db)[0]
    assert fid == 1
    assert row == {
        "id": 1,
        "tutorial_id": 1,
        "tutorial_version": "v1",
        "rating": 2,
        "feedback_category": "指示不清楚",
        "comment": "Step 3 很難懂。",
        "submitter_id": "alice@example.com",
        "timestamp": "2026-09-11T10:00:00Z",
    }


# --- Rule: Feedback 參照 TutorialVersion ---


def test_對應TutorialVersion不存在時操作失敗(db):
    with pytest.raises(OperationFailed):
        collect_feedback(db, _payload(tutorial_version="v9"))
    assert _rows(db) == []


def test_未指定版本時綁定current_version(tmp_path):
    d = LocalDB(path=str(tmp_path / "t2.db"))
    d.init_schema()
    _tutorial(d, current_version="v2", last_action="REFINE")
    _version(d, "v1")
    _version(d, "v2", steps=STEPS_V2, supersedes="v1")
    payload = _payload(rating=4)
    payload.pop("tutorial_version")
    collect_feedback(d, payload)
    assert _rows(d)[0]["tutorial_version"] == "v2"


def test_有指定版本時綁定指定版(tmp_path):
    d = LocalDB(path=str(tmp_path / "t3.db"))
    d.init_schema()
    _tutorial(d, current_version="v2", last_action="REFINE")
    _version(d, "v1")
    _version(d, "v2", steps=STEPS_V2, supersedes="v1")
    collect_feedback(d, _payload(tutorial_version="v1", rating=2))
    assert _rows(d)[0]["tutorial_version"] == "v1"


# --- Rule: submitter_id 可空，同一 submitter 重複評分各自成列 ---


def test_未填submitter時存空字串(db):
    collect_feedback(db, _payload())
    assert _rows(db)[0]["submitter_id"] == ""


def test_同一submitter重複評分各自成列(db):
    collect_feedback(
        db,
        _payload(rating=2, feedback_category="指示不清楚", submitter_id="alice@example.com",
                 timestamp="2026-09-11T09:00:00Z"),
    )
    collect_feedback(
        db,
        _payload(rating=3, feedback_category="缺少資訊", submitter_id="alice@example.com",
                 timestamp="2026-09-11T10:00:00Z"),
    )
    rows = _rows(db)
    assert [(r["id"], r["rating"], r["timestamp"]) for r in rows] == [
        (1, 2, "2026-09-11T09:00:00Z"),
        (2, 3, "2026-09-11T10:00:00Z"),
    ]


# --- 種子匯入（🖐️ M1） ---


def test_匯入v1種子回饋十筆平均二點九(db):
    n = seed_feedback(db, Path("data/seed/feedback_seed.json"))
    assert n == 10
    assert avg_rating(db, 1) == 2.9
