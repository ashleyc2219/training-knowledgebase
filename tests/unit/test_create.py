"""建立 Tutorial（建立Tutorial.feature 五條 Rule）。"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.agent import create_tutorial as ct
from app.agent import llm
from app.errors import OperationFailed
from tests.unit._phase2_fixtures import add_ticket, add_tutorial, make_db, seed_domain

FIVE = {
    "title": "Cancel Order",
    "problem": "Customer wants to cancel an existing order.",
    "prerequisites": "Customer is logged in and has an order number.",
    "steps": '1. Open Orders. 2. Select the order. 3. Click "Cancel Order".',
    "expected_outcome": "The order is cancelled.",
}

MATERIAL = (
    "To cancel your order, open the Orders page, select the order you want to cancel, "
    'and click "Cancel Order". You will receive a confirmation email.'
)


def _gap_db(tmp_path, ids=(1,), upid=1, material=MATERIAL):
    db = make_db(tmp_path)
    seed_domain(db, ids=ids)
    for _ in range(3):
        add_ticket(db, user_problem_id=upid, feature_id=upid, status="resolved",
                   resolution_steps=material)
    return db


def _stub_llm(monkeypatch, payload):
    monkeypatch.setattr(llm, "complete_json", lambda prompt, schema_hint: dict(payload))


def test_create_writes_tables_and_markdown(tmp_path, monkeypatch):
    """Rule 1 ＋ Rule 2：Tutorial published v1、TutorialVersion 五欄、tutorials/*.md。"""
    db = _gap_db(tmp_path)
    _stub_llm(monkeypatch, FIVE)
    monkeypatch.chdir(tmp_path)

    result = ct.create_tutorial(db, 1)

    tut = db.run_sql("SELECT * FROM Tutorial")[0]
    assert tut["status"] == "published"
    assert tut["current_version"] == "v1"
    assert tut["last_action"] == "CREATE"
    assert tut["path"] == "tutorials/cancel-order.md"
    assert tut["feature_id"] == 1
    assert tut["is_possibly_outdated"] == 0 and tut["is_obsolete"] == 0

    ver = db.run_sql("SELECT * FROM TutorialVersion")[0]
    assert ver["tutorial_version"] == "v1"
    for field, value in FIVE.items():
        assert ver[field] == value
    assert (ver["reason"] or "") == ""
    assert not ver["supersedes_version"]

    md = Path(tmp_path, "tutorials/cancel-order.md").read_text(encoding="utf-8")
    assert "# Cancel Order" in md
    assert '3. Click "Cancel Order"' in md
    assert "<!-- version: v1 -->" in md
    assert result["source"] == "llm"
    assert result["path"] == "tutorials/cancel-order.md"


@pytest.mark.parametrize("missing", sorted(FIVE))
def test_missing_field_fails_without_writing(tmp_path, monkeypatch, missing):
    """Rule 3：五欄缺任一 → 操作失敗，且不寫表、不寫檔。"""
    db = _gap_db(tmp_path)
    payload = {k: v for k, v in FIVE.items() if k != missing}
    _stub_llm(monkeypatch, payload)
    monkeypatch.chdir(tmp_path)

    with pytest.raises(OperationFailed):
        ct.create_tutorial(db, 1)

    assert db.run_sql("SELECT * FROM Tutorial") == []
    assert db.run_sql("SELECT * FROM TutorialVersion") == []
    assert not Path(tmp_path, "tutorials/cancel-order.md").exists()


def test_no_knowledge_gap_fails(tmp_path, monkeypatch):
    """Rule 4：未識別出 Knowledge Gap（只有 2 張票）→ 操作失敗。"""
    db = make_db(tmp_path)
    seed_domain(db)
    for _ in range(2):
        add_ticket(db, status="resolved", resolution_steps=MATERIAL)
    _stub_llm(monkeypatch, FIVE)
    monkeypatch.chdir(tmp_path)

    with pytest.raises(OperationFailed):
        ct.create_tutorial(db, 1)

    assert db.run_sql("SELECT * FROM Tutorial") == []


def test_existing_published_tutorial_fails(tmp_path, monkeypatch):
    """Rule 4：已有 published Tutorial（動作是 KEEP，不是 gap）→ 操作失敗。"""
    db = _gap_db(tmp_path)
    add_tutorial(db)
    _stub_llm(monkeypatch, FIVE)
    monkeypatch.chdir(tmp_path)

    with pytest.raises(OperationFailed):
        ct.create_tutorial(db, 1)


def test_missing_feature_fails(tmp_path, monkeypatch):
    """Rule 5：對應的 Feature 不存在 → 操作失敗。"""
    db = _gap_db(tmp_path)
    db.execute("DELETE FROM Feature WHERE id = 1")
    _stub_llm(monkeypatch, FIVE)
    monkeypatch.chdir(tmp_path)

    with pytest.raises(OperationFailed):
        ct.create_tutorial(db, 1)

    assert db.run_sql("SELECT * FROM Tutorial") == []


def test_template_fallback_when_llm_unavailable(tmp_path, monkeypatch):
    """LLM 不可用 → 模板降級，仍產出五欄且 Step 3 是 Click "Cancel Order"。"""
    db = _gap_db(tmp_path)

    def boom(prompt, schema_hint):
        raise llm.LLMUnavailable("沒有金鑰")

    monkeypatch.setattr(llm, "complete_json", boom)
    monkeypatch.chdir(tmp_path)

    result = ct.create_tutorial(db, 1)

    assert result["source"] == "template"
    ver = db.run_sql("SELECT * FROM TutorialVersion")[0]
    assert '3. Click "Cancel Order"' in ver["steps"]
    for field in FIVE:
        assert (ver[field] or "").strip()
    md = Path(tmp_path, "tutorials/cancel-order.md").read_text(encoding="utf-8")
    assert 'Click "Cancel Order"' in md


def test_template_fallback_uses_feature_name_for_other_topic(tmp_path, monkeypatch):
    """其他 topic 的模板 Step 3 用 Feature.name。"""
    db = _gap_db(tmp_path, ids=(2,), upid=2, material="Open Refunds and check the status.")

    monkeypatch.setattr(llm, "complete_json", lambda p, s: (_ for _ in ()).throw(llm.LLMUnavailable("x")))
    monkeypatch.chdir(tmp_path)

    ct.create_tutorial(db, 2)

    ver = db.run_sql("SELECT * FROM TutorialVersion")[0]
    assert 'Click "Track Refund"' in ver["steps"]


def test_memory_layer_is_best_effort(tmp_path, monkeypatch):
    """Cognee／HydraDB 掛掉不影響成功邊界（showme §17）。"""
    db = _gap_db(tmp_path)
    _stub_llm(monkeypatch, FIVE)
    monkeypatch.chdir(tmp_path)

    class BoomCognee:
        def remember(self, *a, **kw):
            raise RuntimeError("cognee 掛了")

    class RecordingHydra:
        def __init__(self):
            self.edges = []

        def upsert_node(self, label, key, props):
            raise RuntimeError("hydra 掛了")

        def upsert_edge(self, from_label, from_key, rel, to_label, to_key):
            self.edges.append(rel)

    hydra = RecordingHydra()
    result = ct.create_tutorial(db, 1, cognee=BoomCognee(), hydra=hydra)

    assert result["tutorial_id"]
    assert db.run_sql("SELECT * FROM Tutorial")[0]["status"] == "published"
