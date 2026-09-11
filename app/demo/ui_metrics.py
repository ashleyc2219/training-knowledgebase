"""Demo 下欄：四個數字＋學習曲線（Phase 4）。

只讀、只展示（showme §12／§13）；分母為 0 時顯示 `—`，不假裝有數字。
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from app.analytics import metrics

CURVE_COLUMNS = ["deflection_rate", "replay_rate", "coverage"]


def _fmt(value: float) -> str:
    return f"{value:.2f}" if value else "—"


def render(db, tutorial_id: int = 1) -> None:
    """畫出四個 metric 與兩張折線圖（尺度不同，分開畫）。"""
    st.subheader("學習指標")
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("deflection rate", _fmt(metrics.deflection_rate(db)))
    avg = metrics.avg_rating(db, tutorial_id)
    col2.metric("平均 rating（current_version）", f"{avg:.1f}" if avg else "—")
    col3.metric("重放解決率", _fmt(metrics.replay_rate(db)))
    col4.metric("圖譜覆蓋", _fmt(metrics.coverage(db)))

    history = metrics.load_history()
    if not history:
        st.caption("還沒有指標快照：餵票／送出回饋／Review 各會存一個點。")
        return

    frame = pd.DataFrame(history)
    st.line_chart(frame[[c for c in CURVE_COLUMNS if c in frame]])
    if "avg_rating" in frame:
        st.line_chart(frame[["avg_rating"]])
    st.caption("x 軸 = snapshot 序號（每次餵票／送出回饋／Review／匯入種子各存一個點）")
