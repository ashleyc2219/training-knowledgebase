"""輪詢 Release Note 單元測試，對齊 docs/spec/features/輪詢ReleaseNote.feature 的三條 Rule。"""

import pytest

from app.analytics.local_db import LocalDB
from app.ingest import poll
from app.ingest.changelog import ingest_release_text, poll_changelog


@pytest.fixture
def db(tmp_path):
    d = LocalDB(path=str(tmp_path / "t.db"))
    d.init_schema()
    return d


@pytest.fixture(autouse=True)
def cursor_in_tmp(tmp_path, monkeypatch):
    """cursor 檔改寫到 tmp_path，測試不碰 repo 的 .state/。"""
    monkeypatch.setattr(poll, "CURSOR_PATH", tmp_path / "last_checked.json")


# --- Rule: 只把 created_at 大於上次檢查時間的 changelog 列寫入 Release ---


def test_只取created_at大於cursor的列(db):
    rows = [
        {"content": "Cancel Order has been renamed to Cancel Purchase.", "created_at": "2026-09-11T09:00:00Z"},
        {"content": "Track Refund is a new feature.", "created_at": "2026-09-11T10:00:00Z"},
        {"content": "Cancel Order has been deprecated.", "created_at": "2026-09-11T10:30:00Z"},
    ]
    inserted = poll_changelog(db, rows=rows, last_checked="2026-09-11T10:00:00Z")

    assert inserted == 1
    releases = db.run_sql("SELECT content, created_at FROM Release ORDER BY id")
    assert [r["content"] for r in releases] == ["Cancel Order has been deprecated."]
    assert releases[0]["created_at"] == "2026-09-11T10:30:00Z"


def test_cursor在輪詢後前進到最新一列(db):
    rows = [{"content": "Cancel Order has been deprecated.", "created_at": "2026-09-11T10:30:00Z"}]
    poll_changelog(db, rows=rows, last_checked="2026-09-11T10:00:00Z")

    assert poll.load_cursor() == "2026-09-11T10:30:00Z"


# --- Rule: 寫入的 Release processed_at 為空 ---


def test_入庫的release_processed_at為空(db):
    rows = [{"content": "Cancel Order has been renamed to Cancel Purchase.", "created_at": "2026-09-11T09:30:00Z"}]
    inserted = poll_changelog(db, rows=rows, last_checked="2026-09-11T09:00:00Z")

    assert inserted == 1
    releases = db.run_sql("SELECT * FROM Release")
    assert len(releases) == 1
    assert releases[0]["processed_at"] is None


# --- Rule: 相同 content 與 created_at 已存在時不新增列 ---


def test_相同content與created_at不重複入庫(db):
    rows = [{"content": "Cancel Order has been renamed to Cancel Purchase.", "created_at": "2026-09-11T09:30:00Z"}]
    poll_changelog(db, rows=rows, last_checked="2026-09-11T09:00:00Z")
    second = poll_changelog(db, rows=rows, last_checked="2026-09-11T09:00:00Z")

    assert second == 0
    assert len(db.run_sql("SELECT * FROM Release")) == 1


def test_同content不同created_at要入庫(db):
    poll_changelog(
        db,
        rows=[{"content": "Cancel Order has been renamed to Cancel Purchase.", "created_at": "2026-09-11T09:30:00Z"}],
        last_checked="2026-09-11T09:00:00Z",
    )
    poll_changelog(
        db,
        rows=[{"content": "Cancel Order has been renamed to Cancel Purchase.", "created_at": "2026-09-11T09:40:00Z"}],
        last_checked="2026-09-11T09:00:00Z",
    )

    assert len(db.run_sql("SELECT * FROM Release")) == 2


# --- rows=None 讀 data/script/changelog.json ---


def test_rows為None時讀腳本檔(db):
    inserted = poll_changelog(db, last_checked="1970-01-01T00:00:00Z")

    assert inserted >= 1
    contents = [r["content"] for r in db.run_sql("SELECT content FROM Release")]
    assert any("renamed to Cancel Purchase" in c for c in contents)


# --- ingest_release_text（Streamlit 左欄貼一則） ---


def test_貼一則入庫回傳release_id(db):
    release_id = ingest_release_text(db, "Cancel Order has been renamed to Cancel Purchase.", "2026-09-11T15:00:00Z")

    assert release_id == 1
    row = db.run_sql("SELECT * FROM Release WHERE id = :id", {"id": release_id})[0]
    assert row["processed_at"] is None
    assert row["created_at"] == "2026-09-11T15:00:00Z"


def test_貼重複的一則不新增(db):
    ingest_release_text(db, "Cancel Order has been renamed to Cancel Purchase.", "2026-09-11T15:00:00Z")
    again = ingest_release_text(db, "Cancel Order has been renamed to Cancel Purchase.", "2026-09-11T15:00:00Z")

    assert again == 0
    assert len(db.run_sql("SELECT * FROM Release")) == 1
