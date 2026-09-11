"""Demo 中欄下半：顧客回饋表單 ＋ 種子匯入 ＋ Review 按鈕（Phase 4）。

UI 只觸發、只展示（showme §13）：門檻判斷全部在 `app/agent/rules.py`，
這裡不算平均分、不決定 REFINE。
"""

from __future__ import annotations

import difflib
from datetime import datetime, timezone
from pathlib import Path

import streamlit as st

from app.agent.feedback_review import review_all
from app.agent.rules import FEEDBACK_CATEGORIES
from app.analytics import metrics
from app.errors import OperationFailed
from app.ingest.feedback import collect_feedback, seed_feedback

V1_SEED = Path("data/seed/feedback_seed.json")
V2_SEED = Path("data/seed/feedback_v2_seed.json")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _tutorials(db) -> list[dict]:
    return db.run_sql(
        "SELECT tutorial_id, path, status, current_version FROM Tutorial ORDER BY tutorial_id"
    )


def _diff(old_steps: str, new_steps: str) -> str:
    return "\n".join(
        difflib.unified_diff(
            str(old_steps).splitlines() or [str(old_steps)],
            str(new_steps).splitlines() or [str(new_steps)],
            fromfile="steps (舊版)",
            tofile="steps (新版)",
            lineterm="",
        )
    )


def render(db) -> None:
    """畫出回饋表單與 Review 區塊。"""
    st.subheader("顧客回饋")
    tutorials = _tutorials(db)
    if not tutorials:
        st.info("還沒有任何 Tutorial，先在左欄餵票產生 v1。")
        return

    labels = {
        f"#{t['tutorial_id']} {t['path']}（{t['current_version']}）": t["tutorial_id"]
        for t in tutorials
    }

    with st.form("feedback_form", clear_on_submit=True):
        label = st.selectbox("Tutorial", list(labels))
        rating = st.radio("rating", [1, 2, 3, 4, 5], index=2, horizontal=True)
        category = st.selectbox("category", [""] + FEEDBACK_CATEGORIES)
        comment = st.text_input("comment")
        submitter = st.text_input("submitter", value="alice@example.com")
        if st.form_submit_button("送出"):
            try:
                fid = collect_feedback(
                    db,
                    {
                        "tutorial_id": labels[label],
                        "rating": rating,  # 不填版本 → 綁 current_version
                        "feedback_category": category,
                        "comment": comment,
                        "submitter_id": submitter,
                        "timestamp": _now(),
                    },
                )
                st.success(f"已收到 Feedback #{fid}")
                metrics.append_history(metrics.snapshot(db))
            except OperationFailed as exc:
                st.error(f"操作失敗：{exc}")

    col1, col2 = st.columns(2)
    if col1.button("匯入 v1 種子回饋", use_container_width=True):
        n = seed_feedback(db, V1_SEED)
        st.success(f"匯入 v1 回饋 {n} 筆")
        metrics.append_history(metrics.snapshot(db))
    if col2.button("匯入 v2 高分回饋（demo 安排）", use_container_width=True):
        n = seed_feedback(db, V2_SEED)
        st.success(f"匯入 v2 回饋 {n} 筆（劇本資料，不是系統自己產生的）")
        metrics.append_history(metrics.snapshot(db))

    if st.button("Review", type="primary"):
        try:
            results = review_all(db)
        except OperationFailed as exc:
            st.error(f"操作失敗：{exc}（Tutorial 未變更）")
            return
        if not results:
            st.info("沒有 published Tutorial 可以 Review。")
        for r in results:
            if r["action"] == "REFINE":
                st.success(
                    f"REFINE：tutorial {r['tutorial_id']} {r['from_version']} → "
                    f"{r['to_version']}｜{r['reason']}"
                    + ("（模板降級）" if r.get("source") == "template" else "")
                )
                if r.get("warning"):
                    st.warning(r["warning"])
                st.code(_diff(r["old_steps"], r["new_steps"]), language="diff")
            else:
                st.info(f"KEEP：tutorial {r['tutorial_id']}（{r['reason']}）")
        metrics.append_history(metrics.snapshot(db))
