"""Rote Play 打的本機 endpoint（Phase 3）。

一支 `POST /deflect`：讀 Ticket → 找它 UserProblem 的 published Tutorial →
把 Ticket 寫成 deflected → 回教學連結。對應 features/自動回覆顧客.feature 的 deflected Rule。

FastAPI 自動產生的 `/openapi.json` 就是 `rote adapter new deflect-api <url>` 的輸入，
所以 `operation_id` 一定要自己指定（rote 拿它當 tool 名稱）。

啟動：scripts/run_deflect_api.sh（uvicorn，port 8765）
"""

from __future__ import annotations

import os

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from app.analytics.local_db import DEFAULT_PATH, LocalDB

app = FastAPI(title="deflect-api", version="1.0.0")
app.state.db = None


def get_db():
    """測試與 demo 用 `app.state.db` 注入；沒注入就開 `DEFLECT_DB_PATH`（預設 .state/local.db）。"""
    if app.state.db is None:
        db = LocalDB(os.environ.get("DEFLECT_DB_PATH", DEFAULT_PATH))
        db.init_schema()
        app.state.db = db
    return app.state.db


class DeflectIn(BaseModel):
    ticket_id: int


class DeflectOut(BaseModel):
    ticket_id: int
    tutorial_path: str
    version: str


@app.get("/health", operation_id="health")
def health() -> dict:
    """存活檢查（rote adapter 與 demo 暖機用）。"""
    return {"status": "ok"}


@app.post("/deflect", operation_id="deflect_ticket", response_model=DeflectOut)
def deflect(body: DeflectIn) -> DeflectOut:
    """把一張 open 票以它 UserProblem 的 published Tutorial 攔截掉；已 deflected 再打是冪等的。"""
    db = get_db()

    tickets = db.run_sql(
        "SELECT id, user_problem_id FROM Ticket WHERE id = :tid", {"tid": body.ticket_id}
    )
    if not tickets or tickets[0]["user_problem_id"] is None:
        raise HTTPException(status_code=404, detail="ticket 不存在或沒有 user_problem_id")

    tutorials = db.run_sql(
        "SELECT tutorial_id, current_version, path FROM Tutorial "
        "WHERE user_problem_id = :upid AND status = 'published'",
        {"upid": tickets[0]["user_problem_id"]},
    )
    if not tutorials:
        raise HTTPException(status_code=404, detail="這個 UserProblem 沒有 published Tutorial")

    tutorial = tutorials[0]
    db.execute(
        "UPDATE Ticket SET status = 'deflected', deflected_tutorial_id = :tut, "
        "deflected_tutorial_version = :ver WHERE id = :tid",
        {"tut": tutorial["tutorial_id"], "ver": tutorial["current_version"], "tid": body.ticket_id},
    )
    return DeflectOut(
        ticket_id=body.ticket_id,
        tutorial_path=tutorial["path"],
        version=tutorial["current_version"],
    )
