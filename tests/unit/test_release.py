"""依 Release Note 更新 Tutorial 的單元測試。

對齊 docs/spec/features/依ReleaseNote更新Tutorial.feature 的七條 Rule。
LLM 一律 monkeypatch（預設不可用 → 走規則式擷取），不打任何外部服務。
"""

from pathlib import Path

import pytest

from app.agent import llm, release_update
from app.agent.release_update import extract_changes, process_unprocessed_releases
from app.analytics.local_db import LocalDB
from app.errors import OperationFailed

NOW = "2026-09-11T12:00:00Z"
RENAMED = "Cancel Order has been renamed to Cancel Purchase."


@pytest.fixture
def db(tmp_path):
    d = LocalDB(path=str(tmp_path / "t.db"))
    d.init_schema()
    return d


@pytest.fixture(autouse=True)
def llm_unavailable(monkeypatch):
    """預設沒有 LLM（黑客松當天沒金鑰），擷取與改寫都走規則式降級。"""

    def _raise(prompt, schema_hint):
        raise llm.LLMUnavailable("測試預設無 LLM")

    monkeypatch.setattr(llm, "complete_json", _raise)


# --- 測試資料 ---


def add_feature(db, feature_id=1, name="Cancel Order", status="active"):
    db.execute(
        "INSERT INTO Feature (id, name, status) VALUES (:id, :name, :status)",
        {"id": feature_id, "name": name, "status": status},
    )


def add_tutorial(db, tmp_path, tutorial_id=1, feature_id=1, slug="cancel-order", current_version="v1"):
    path = str(tmp_path / f"{slug}.md")
    db.execute(
        """
        INSERT INTO Tutorial (tutorial_id, feature_id, user_problem_id, path, status,
                              current_version, is_possibly_outdated, is_obsolete, last_action)
        VALUES (:tid, :fid, 1, :path, 'published', :ver, 0, 0, 'CREATE')
        """,
        {"tid": tutorial_id, "fid": feature_id, "path": path, "ver": current_version},
    )
    return path


def add_version(db, tutorial_id=1, version="v1", steps=None):
    db.execute(
        """
        INSERT INTO TutorialVersion (tutorial_id, tutorial_version, title, problem, prerequisites,
                                     steps, expected_outcome, reason, supersedes_version, created_at)
        VALUES (:tid, :ver, 'How to Cancel Order', 'You want to cancel an order.',
                'You are signed in.', :steps, 'The order is cancelled.', '', '', '2026-09-11T11:00:00Z')
        """,
        {
            "tid": tutorial_id,
            "ver": version,
            "steps": steps or '1. Open Orders\n2. Select the order\n3. Click "Cancel Order"',
        },
    )


def add_release(db, release_id=1, content=RENAMED, created_at="2026-09-11T09:00:00Z", processed_at=None):
    db.execute(
        "INSERT INTO Release (id, content, created_at, processed_at) VALUES (:id, :c, :ca, :pa)",
        {"id": release_id, "c": content, "ca": created_at, "pa": processed_at},
    )


def tutorial_row(db, tutorial_id=1):
    return db.run_sql("SELECT * FROM Tutorial WHERE tutorial_id = :id", {"id": tutorial_id})[0]


def feature_row(db, feature_id=1):
    return db.run_sql("SELECT * FROM Feature WHERE id = :id", {"id": feature_id})[0]


# --- 擷取 ---


def test_規則式擷取更名(db):
    changes = extract_changes(RENAMED)

    assert len(changes) == 1
    assert changes[0]["change_type"] == "renamed"
    assert changes[0]["from_name"] == "Cancel Order"
    assert changes[0]["to_name"] == "Cancel Purchase"
    assert changes[0]["source"] == "rule"


@pytest.mark.parametrize(
    "content,change_type",
    [
        ("Cancel Order has been deprecated.", "deprecated"),
        ("Cancel Order has been removed.", "removed"),
        ("Track Refund is a new feature.", "new"),
        ("Cancel Order has changed.", "changed"),
    ],
)
def test_規則式擷取四種句型(content, change_type):
    changes = extract_changes(content)

    assert changes[0]["change_type"] == change_type


def test_LLM可用時走LLM並標source(monkeypatch):
    def _fake(prompt, schema_hint):
        return {
            "changes": [
                {
                    "feature_name": "Cancel Order",
                    "change_type": "renamed",
                    "from_name": "Cancel Order",
                    "to_name": "Cancel Purchase",
                }
            ]
        }

    monkeypatch.setattr(llm, "complete_json", _fake)
    changes = extract_changes(RENAMED)

    assert changes[0]["source"] == "llm"
    assert changes[0]["to_name"] == "Cancel Purchase"


def test_擷取不到change_type則操作失敗():
    with pytest.raises(OperationFailed):
        extract_changes("今天天氣很好。")


# --- Rule: 從 Release Note 擷取產品變更並寫入 ReleaseFeatureChange ---


def test_擷取寫入ReleaseFeatureChange(db, tmp_path):
    add_feature(db)
    add_tutorial(db, tmp_path)
    add_version(db)
    add_release(db)

    process_unprocessed_releases(db, now=NOW)

    rows = db.run_sql("SELECT * FROM ReleaseFeatureChange")
    assert len(rows) == 1
    assert rows[0]["release_id"] == 1
    assert rows[0]["feature_id"] == 1
    assert rows[0]["change_type"] == "renamed"
    assert rows[0]["from_name"] == "Cancel Order"
    assert rows[0]["to_name"] == "Cancel Purchase"


# --- Rule: 只依 Tutorial.feature_id 找出受影響 Tutorial ---


def test_只依feature_id找出受影響tutorial(db, tmp_path):
    add_feature(db, 1, "Cancel Order")
    add_feature(db, 2, "Track Refund")
    add_tutorial(db, tmp_path, tutorial_id=1, feature_id=1, slug="cancel-order")
    add_tutorial(db, tmp_path, tutorial_id=2, feature_id=2, slug="track-refund")
    add_version(db, tutorial_id=1)
    add_version(db, tutorial_id=2)
    add_release(db)

    decisions = process_unprocessed_releases(db, now=NOW)

    assert [(d["tutorial_id"], d["action"]) for d in decisions] == [(1, "UPDATE")]
    assert tutorial_row(db, 2)["current_version"] == "v1"
    assert tutorial_row(db, 2)["last_action"] == "CREATE"


# --- Rule: renamed 或 changed 時對受影響 Tutorial 執行 UPDATE ---


def test_renamed產生下一版並改名(db, tmp_path):
    add_feature(db)
    md_path = add_tutorial(db, tmp_path)
    add_version(db)
    add_release(db)

    decisions = process_unprocessed_releases(db, now=NOW)

    assert decisions == [{"release_id": 1, "tutorial_id": 1, "action": "UPDATE"}]

    versions = db.run_sql("SELECT * FROM TutorialVersion ORDER BY tutorial_version")
    assert [v["tutorial_version"] for v in versions] == ["v1", "v2"]
    v2 = versions[1]
    assert 'Click "Cancel Purchase"' in v2["steps"]
    assert 'Click "Cancel Order"' not in v2["steps"]
    assert v2["reason"] == f"Release: {RENAMED}"
    assert v2["supersedes_version"] == "v1"
    assert v2["created_at"] == NOW

    tut = tutorial_row(db)
    assert tut["current_version"] == "v2"
    assert tut["status"] == "published"
    assert tut["is_possibly_outdated"] == 0
    assert tut["is_obsolete"] == 0
    assert tut["last_action"] == "UPDATE"

    assert feature_row(db)["name"] == "Cancel Purchase"
    assert feature_row(db)["status"] == "active"

    assert db.run_sql("SELECT * FROM Release")[0]["processed_at"] == NOW


def test_UPDATE後重寫md檔(db, tmp_path):
    add_feature(db)
    md_path = add_tutorial(db, tmp_path)
    add_version(db)
    add_release(db)

    process_unprocessed_releases(db, now=NOW)

    text = Path(md_path).read_text(encoding="utf-8")
    assert 'Click "Cancel Purchase"' in text
    assert "## Steps" in text
    assert "<!-- version: v2 -->" in text


def test_v1不存在五欄仍可更新(db, tmp_path):
    """規格 Example 的 Given 只填 steps；其餘欄位為空也要能升版。"""
    add_feature(db)
    add_tutorial(db, tmp_path)
    db.execute(
        """
        INSERT INTO TutorialVersion (tutorial_id, tutorial_version, title, problem,
                                     prerequisites, steps, expected_outcome, reason,
                                     supersedes_version, created_at)
        VALUES (1, 'v1', '', '', '', 'Step 3: Click "Cancel Order"', '', '', '', '')
        """
    )
    add_release(db)

    process_unprocessed_releases(db, now=NOW)

    v2 = db.run_sql("SELECT * FROM TutorialVersion WHERE tutorial_version = 'v2'")[0]
    assert v2["steps"] == 'Step 3: Click "Cancel Purchase"'


# --- Rule: deprecated 或 removed 時對受影響 Tutorial 執行 RETIRE ---


@pytest.mark.parametrize(
    "content,feature_status",
    [
        ("Cancel Order has been deprecated.", "deprecated"),
        ("Cancel Order has been removed.", "removed"),
    ],
)
def test_deprecated或removed執行RETIRE(db, tmp_path, content, feature_status):
    add_feature(db)
    add_tutorial(db, tmp_path)
    add_version(db)
    add_release(db, content=content)

    decisions = process_unprocessed_releases(db, now=NOW)

    assert decisions == [{"release_id": 1, "tutorial_id": 1, "action": "RETIRE"}]

    tut = tutorial_row(db)
    assert tut["status"] == "retired"
    assert tut["is_obsolete"] == 1
    assert tut["is_possibly_outdated"] == 0
    assert tut["last_action"] == "RETIRE"
    assert tut["current_version"] == "v1"

    assert feature_row(db)["status"] == feature_status
    assert len(db.run_sql("SELECT * FROM TutorialVersion")) == 1


# --- Rule: 出現 new feature 且無對應 Tutorial 時不決定動作 ---


def test_new_feature無tutorial時只記processed_at(db):
    add_feature(db, feature_id=2, name="Track Refund")
    add_release(db, release_id=2, content="Track Refund is a new feature.")

    decisions = process_unprocessed_releases(db, now=NOW)

    assert decisions == []
    assert db.run_sql("SELECT * FROM Release")[0]["processed_at"] == NOW
    assert db.run_sql("SELECT * FROM Tutorial") == []


# --- Rule: 找不到受影響 Tutorial 時只記錄 processed_at ---


def test_無受影響tutorial只記processed_at(db):
    add_feature(db)
    add_release(db)

    decisions = process_unprocessed_releases(db, now=NOW)

    assert decisions == []
    assert db.run_sql("SELECT * FROM Release")[0]["processed_at"] == NOW
    assert feature_row(db)["name"] == "Cancel Order"


def test_對不到Feature時不新建Feature(db):
    add_feature(db, feature_id=2, name="Track Refund")
    add_release(db)

    process_unprocessed_releases(db, now=NOW)

    assert len(db.run_sql("SELECT * FROM Feature")) == 1
    assert db.run_sql("SELECT * FROM ReleaseFeatureChange") == []
    assert db.run_sql("SELECT * FROM Release")[0]["processed_at"] == NOW


# --- Rule: 已有 processed_at 的 Release 不再處理 ---


def test_已處理的release不再處理(db, tmp_path):
    add_feature(db, name="Cancel Purchase")
    add_tutorial(db, tmp_path, current_version="v2")
    add_version(db, version="v1")
    add_version(db, version="v2", steps='3. Click "Cancel Purchase"')
    add_release(db, processed_at="2026-09-11T09:30:00Z")

    decisions = process_unprocessed_releases(db, now=NOW)

    assert decisions == []
    tut = tutorial_row(db)
    assert tut["current_version"] == "v2"
    assert tut["last_action"] == "CREATE"
    assert len(db.run_sql("SELECT * FROM TutorialVersion")) == 2
    assert db.run_sql("SELECT * FROM Release")[0]["processed_at"] == "2026-09-11T09:30:00Z"


def test_處理兩次是冪等的(db, tmp_path):
    add_feature(db)
    add_tutorial(db, tmp_path)
    add_version(db)
    add_release(db)

    process_unprocessed_releases(db, now=NOW)
    before = (tutorial_row(db), feature_row(db), db.run_sql("SELECT * FROM TutorialVersion"))

    second = process_unprocessed_releases(db, now="2026-09-11T13:00:00Z")

    assert second == []
    assert (tutorial_row(db), feature_row(db), db.run_sql("SELECT * FROM TutorialVersion")) == before


# --- 失敗語意：擷取失敗的列 processed_at 保持空，其他列照處理 ---


def test_擷取失敗的列保持未處理且其他列照跑(db, tmp_path):
    add_feature(db)
    add_tutorial(db, tmp_path)
    add_version(db)
    add_release(db, release_id=1, content="今天天氣很好。", created_at="2026-09-11T08:00:00Z")
    add_release(db, release_id=2, content=RENAMED, created_at="2026-09-11T09:00:00Z")

    with pytest.raises(OperationFailed):
        process_unprocessed_releases(db, now=NOW)

    releases = {r["id"]: r["processed_at"] for r in db.run_sql("SELECT * FROM Release")}
    assert releases[1] is None
    assert releases[2] == NOW
    assert tutorial_row(db)["current_version"] == "v2"


# --- hydra 降級：呼叫失敗時走 SQL ---


def test_hydra呼叫失敗時降級為SQL(db, tmp_path):
    class BrokenHydra:
        def upsert_node(self, *a, **k):
            raise RuntimeError("HydraDB down")

        def upsert_edge(self, *a, **k):
            raise RuntimeError("HydraDB down")

        def affected_tutorials_by_release(self, release_id):
            raise RuntimeError("HydraDB down")

    add_feature(db)
    add_tutorial(db, tmp_path)
    add_version(db)
    add_release(db)

    decisions = process_unprocessed_releases(db, hydra=BrokenHydra(), now=NOW)

    assert decisions == [{"release_id": 1, "tutorial_id": 1, "action": "UPDATE"}]
    assert tutorial_row(db)["current_version"] == "v2"


def test_cognee失敗不影響升版(db, tmp_path):
    class BrokenCognee:
        def remember(self, *a, **k):
            raise RuntimeError("Cognee down")

    add_feature(db)
    add_tutorial(db, tmp_path)
    add_version(db)
    add_release(db)

    decisions = process_unprocessed_releases(db, cognee=BrokenCognee(), now=NOW)

    assert decisions == [{"release_id": 1, "tutorial_id": 1, "action": "UPDATE"}]


def test_decide_release_action對齊規則():
    from app.agent.rules import decide_release_action

    assert decide_release_action("renamed") == "UPDATE"
    assert decide_release_action("changed") == "UPDATE"
    assert decide_release_action("deprecated") == "RETIRE"
    assert decide_release_action("removed") == "RETIRE"
    assert decide_release_action("new") is None
