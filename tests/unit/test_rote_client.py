"""Phase 3 — Rote 肌肉記憶：capture / replay / 降級。

對應規格 docs/spec/features/重放已驗證流程.feature（3 Rule）。
測試一律 monkeypatch `subprocess.run`，不真的 fork rote CLI、不打網路。
"""

from __future__ import annotations

import subprocess

import pytest

from app.analytics.local_db import LocalDB
from app.muscle import rote_client
from app.muscle.rote_client import STEPS_TEXT

PLAY = "support-deflect"
CAPTURED_AT = "2026-09-11T10:05:00Z"


class FakeRun:
    """假的 subprocess.run：記錄 argv/cwd，回預先安排的 CompletedProcess。"""

    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = "", raises=None):
        self.calls: list[tuple[list[str], str | None]] = []
        self.returncode, self.stdout, self.stderr, self.raises = returncode, stdout, stderr, raises

    def __call__(self, args, cwd=None, capture_output=True, text=True, timeout=None):
        self.calls.append((list(args), cwd))
        if self.raises is not None:
            raise self.raises
        return subprocess.CompletedProcess(args, self.returncode, self.stdout, self.stderr)

    def argv_for(self, *head: str) -> tuple[list[str], str | None]:
        for argv, cwd in self.calls:
            if argv[1 : 1 + len(head)] == list(head):
                return argv, cwd
        raise AssertionError(f"rote {' '.join(head)} 沒有被呼叫：{self.calls}")


@pytest.fixture(autouse=True)
def _reset_cache(monkeypatch):
    """每個測試都從乾淨的 has_play 快取與已設定的 Play 名稱開始。"""
    rote_client.reset_cache()
    monkeypatch.setenv("ROTE_PLAY_NAME", PLAY)
    yield
    rote_client.reset_cache()


@pytest.fixture()
def db(tmp_path):
    d = LocalDB(str(tmp_path / "t.db"))
    d.init_schema()
    d.execute(
        "INSERT INTO Ticket (id, content, customer_ref, user_problem_id, status) "
        "VALUES (5, 'I want to cancel order', 'bob@example.com', 1, 'deflected')"
    )
    return d


def _workflow(db) -> dict:
    rows = db.run_sql("SELECT * FROM Workflow WHERE user_problem_id = 1")
    assert len(rows) == 1
    return rows[0]


def _given_workflow(db, replay_count: int = 0) -> None:
    db.execute(
        "INSERT INTO Workflow (id, user_problem_id, steps, captured_at, replay_count) "
        "VALUES (1, 1, :steps, :cap, :n)",
        {"steps": STEPS_TEXT, "cap": CAPTURED_AT, "n": replay_count},
    )


# --- Rule 1：某 UserProblem 第一次 deflected 成功時新增 Workflow --------------------


def test_第一次攔截新增_workflow_replay_count_為_0(db, monkeypatch):
    fake = FakeRun(stdout=PLAY)
    monkeypatch.setattr(rote_client.subprocess, "run", fake)

    result = rote_client.on_deflected(db, ticket_id=5, user_problem_id=1)

    row = _workflow(db)
    assert (row["steps"], row["replay_count"]) == (STEPS_TEXT, 0)
    assert row["captured_at"]
    assert result["mode"] == "captured"
    assert result["replay_count"] == 0
    assert result["play_captured"] is True


def test_第一次攔截時_play_不存在仍寫入_workflow(db, monkeypatch):
    monkeypatch.setenv("ROTE_PLAY_NAME", "")  # 空值＝還沒 crystallize（蓋掉 .env）
    fake = FakeRun(stdout="")
    monkeypatch.setattr(rote_client.subprocess, "run", fake)

    result = rote_client.on_deflected(db, ticket_id=5, user_problem_id=1)

    assert _workflow(db)["replay_count"] == 0
    assert result["mode"] == "captured"
    assert result["play_captured"] is False


# --- Rule 2：同 UserProblem 已有 Workflow 時再次 deflected 則 replay_count 加 1 ------


def test_第二次攔截_rote重放成功_replay_count_加一且_captured_at_不變(db, monkeypatch):
    _given_workflow(db)
    fake = FakeRun(stdout=PLAY)
    monkeypatch.setattr(rote_client.subprocess, "run", fake)

    result = rote_client.on_deflected(db, ticket_id=5, user_problem_id=1)

    row = _workflow(db)
    assert (row["replay_count"], row["captured_at"]) == (1, CAPTURED_AT)
    assert result["mode"] == "replayed"
    assert result["replay_count"] == 1


def test_重放帶的是新_ticket_id_且從_workspace_外面跑(db, monkeypatch):
    _given_workflow(db)
    fake = FakeRun(stdout=PLAY)
    monkeypatch.setattr(rote_client.subprocess, "run", fake)

    rote_client.on_deflected(db, ticket_id=5, user_problem_id=1)

    argv, cwd = fake.argv_for("play", "run")
    # 本機 Play 不加 `--yes`（rote 0.82.0：--yes 只給 registry 參照）
    assert argv[1:] == ["play", "run", PLAY, "ticket_id=5"]
    assert cwd == rote_client.RUN_CWD


# --- 降級：不灌水 replay_count（showme §14 / §17）----------------------------------


def test_play_run_失敗時_replay_count_不變(db, monkeypatch):
    _given_workflow(db)
    fake = FakeRun(returncode=1, stdout=PLAY, stderr="adapter unreachable")
    monkeypatch.setattr(rote_client.subprocess, "run", fake)

    result = rote_client.on_deflected(db, ticket_id=5, user_problem_id=1)

    assert _workflow(db)["replay_count"] == 0
    assert result["mode"] == "local_fallback"
    assert result["replay_count"] == 0


def test_重放後_ticket_不是_deflected_則不算成功(db, monkeypatch):
    _given_workflow(db)
    db.execute("UPDATE Ticket SET status = 'open' WHERE id = 5")
    fake = FakeRun(stdout=PLAY)
    monkeypatch.setattr(rote_client.subprocess, "run", fake)

    result = rote_client.on_deflected(db, ticket_id=5, user_problem_id=1)

    assert _workflow(db)["replay_count"] == 0
    assert result["mode"] == "local_fallback"


def test_沒有_play_時第二次不呼叫_rote_但本機計數_replay_count_加一(db, monkeypatch):
    """showme §17 降級：Rote 未暖機（Play 從未捕捉）→ replay_count 本機計數，UI 標「Play 未捕捉」。"""
    _given_workflow(db)
    monkeypatch.setenv("ROTE_PLAY_NAME", "")  # 空值＝還沒 crystallize（蓋掉 .env）
    fake = FakeRun()
    monkeypatch.setattr(rote_client.subprocess, "run", fake)

    result = rote_client.on_deflected(db, ticket_id=5, user_problem_id=1)

    assert _workflow(db)["replay_count"] == 1
    assert result["mode"] == "local_fallback"
    assert result["play_captured"] is False
    assert fake.calls == []


def test_subprocess_逾時不外拋並回_local_fallback(db, monkeypatch):
    _given_workflow(db)
    fake = FakeRun(raises=subprocess.TimeoutExpired(cmd="rote", timeout=20))
    monkeypatch.setattr(rote_client.subprocess, "run", fake)

    result = rote_client.on_deflected(db, ticket_id=5, user_problem_id=1)

    assert result["mode"] == "local_fallback"
    assert _workflow(db)["replay_count"] == 0


# --- has_play ---------------------------------------------------------------------


def test_has_play_需要_env_名稱且_rote_列表看得到(monkeypatch):
    fake = FakeRun(stdout=f"  {PLAY}  v1\n")
    monkeypatch.setattr(rote_client.subprocess, "run", fake)
    assert rote_client.has_play() is True

    rote_client.reset_cache()
    fake2 = FakeRun(stdout="other-play\n")
    monkeypatch.setattr(rote_client.subprocess, "run", fake2)
    assert rote_client.has_play() is False


def test_has_play_結果有快取只查一次(monkeypatch):
    fake = FakeRun(stdout=PLAY)
    monkeypatch.setattr(rote_client.subprocess, "run", fake)
    assert rote_client.has_play() is True
    assert rote_client.has_play() is True
    assert len(fake.calls) == 1
