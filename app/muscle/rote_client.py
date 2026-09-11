"""Rote（Muscle memory）：第一次成功攔截即捕捉 Workflow，之後直接重放 Play。

契約見 docs/spec/features/重放已驗證流程.feature 與 docs/plan/unfinish/04-Phase3-Deflect與Rote重放.md。

共用介面（即時路徑在 Ticket 已寫成 deflected 之後呼叫）：
    on_deflected(db, ticket_id, user_problem_id) -> dict
回傳 {"mode": "captured"|"replayed"|"local_fallback", "replay_count": int, "play_captured": bool}

一支 Play（`.env` 的 `ROTE_PLAY_NAME`）服務所有 UserProblem，`ticket_id` 是參數；
Play 重的是「方法」不是答案，所以新票號會產生新結果。
crystallize 是一次性手動流程（見計畫 §5 步驟 5–7），不在票流程裡跑。

RocketRide catalog 沒有 rote 節點，這層一律走本機 CLI（subprocess），不發明 tool_rote。
所有 subprocess 失敗都吞掉走降級，永不外拋——票的狀態由即時路徑負責，Rote 只是附加價值。
"""

from __future__ import annotations

import os
import subprocess
from datetime import datetime, timezone

from dotenv import load_dotenv

STEPS_TEXT = "匹配 UserProblem → 取 published Tutorial → 回覆連結 → 更新 Ticket"

ROTE_BIN = os.path.expanduser(os.environ.get("ROTE_BIN", "~/.local/bin/rote"))
# Play 會自建臨時 workspace，必須從 ~/.rote/workspaces/ 以外的目錄跑
RUN_CWD = "/tmp"
TIMEOUT = 20

_has_play_cache: bool | None = None


def reset_cache() -> None:
    """清掉 has_play 快取（測試與 demo 重置用）。"""
    global _has_play_cache
    _has_play_cache = None


def play_name() -> str:
    """`.env` / 環境變數的 `ROTE_PLAY_NAME`；沒設就代表還沒 crystallize。"""
    load_dotenv()
    return (os.environ.get("ROTE_PLAY_NAME") or "").strip()


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _rote(args: list[str], cwd: str | None = None) -> subprocess.CompletedProcess | None:
    """跑一次 rote CLI；任何失敗（找不到 binary、逾時、OS 錯）都回 None。"""
    try:
        return subprocess.run(
            [ROTE_BIN, *args], cwd=cwd, capture_output=True, text=True, timeout=TIMEOUT
        )
    except (OSError, subprocess.SubprocessError):
        return None


def has_play() -> bool:
    """Play 是否已經捕捉好：`.env` 有名稱，且 `rote play list` 看得到它。

    一個 process 只查一次，避免每張票都 fork 一次 CLI 拖慢 demo。
    """
    global _has_play_cache
    if _has_play_cache is None:
        name = play_name()
        proc = _rote(["play", "list"]) if name else None
        _has_play_cache = bool(proc and proc.returncode == 0 and name in (proc.stdout or ""))
    return _has_play_cache


def replay_play(db, ticket_id: int) -> bool:
    """重放 Play（帶新的 ticket_id）。成功判定用資料狀態，不解析 stdout 文字。"""
    # 本機 Play 用名稱跑就好；`--yes` 只適用 registry 參照（rote 0.82.0 會直接拒絕）
    proc = _rote(["play", "run", play_name(), f"ticket_id={ticket_id}"], cwd=RUN_CWD)
    if proc is None or proc.returncode != 0:
        return False
    rows = db.run_sql("SELECT status FROM Ticket WHERE id = :tid", {"tid": ticket_id})
    return bool(rows) and rows[0]["status"] == "deflected"


def on_deflected(db, ticket_id: int, user_problem_id: int) -> dict:
    """重放已驗證流程.feature — 第一次 deflected 新增 Workflow；已有 Workflow 則重放並 +1。

    Rule 3（escalated 不建立 Workflow）由即時路徑負責：escalated 根本不會呼叫這裡。
    """
    rows = db.run_sql(
        "SELECT id, replay_count FROM Workflow WHERE user_problem_id = :upid",
        {"upid": user_problem_id},
    )

    if not rows:
        # Rule 1：第一次攔截成功 → 捕捉 Workflow（captured_at 只寫這一次）
        db.execute(
            "INSERT INTO Workflow (user_problem_id, steps, captured_at, replay_count) "
            "VALUES (:upid, :steps, :captured_at, 0)",
            {"upid": user_problem_id, "steps": STEPS_TEXT, "captured_at": _now()},
        )
        return {"mode": "captured", "replay_count": 0, "play_captured": has_play()}

    count = int(rows[0]["replay_count"])

    # Rule 2：已有 Workflow → 交給 Rote 重放；重放沒成功就不灌水 replay_count（showme §14）
    if has_play() and replay_play(db, ticket_id):
        count += 1
        db.execute(
            "UPDATE Workflow SET replay_count = :c WHERE user_problem_id = :upid",
            {"c": count, "upid": user_problem_id},
        )
        return {"mode": "replayed", "replay_count": count, "play_captured": True}

    if play_name():
        # Play 已設定（曾 crystallize）但重放失敗／rote 不可用：本張票改走 Agent 即時路徑（已 deflected），
        # 不把失敗寫成 +1（showme §14）
        return {"mode": "local_fallback", "replay_count": count, "play_captured": has_play()}

    # Rote 未暖機（Play 從未捕捉）：replay_count 用本機計數，UI 標「Play 未捕捉」（showme §17 降級）
    count += 1
    db.execute(
        "UPDATE Workflow SET replay_count = :c WHERE user_problem_id = :upid",
        {"c": count, "upid": user_problem_id},
    )
    return {"mode": "local_fallback", "replay_count": count, "play_captured": False}
