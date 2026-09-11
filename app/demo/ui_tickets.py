"""Demo UI — 餵票／即時路徑／轉真人／分析／CREATE 區塊（Phase 2）。

邊界（showme §13）：UI 只觸發、只展示。門檻計算與 CREATE 決定都在 `app/agent/`，不在這裡。
接法：`streamlit_app.py` 內 `from app.demo import ui_tickets; ui_tickets.render(db)`。
"""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from app.agent import analysis, create_tutorial, realtime, rocketride_client
from app.errors import OperationFailed
from app.ingest import poll

TUTORIALS_DIR = Path("tutorials")


def render(db) -> None:
    """左欄餵票與系統回覆、中欄轉真人解法框 ＋ 分析 ＋ Tutorial 檢視。"""
    left, middle = st.columns([1, 1.4])

    with left:
        _render_feed(db)
    with middle:
        _render_decision(db)
        _render_analysis(db)
        _render_tutorials()


# --- 左欄：模擬顧客 ---


def _render_feed(db) -> None:
    st.subheader("模擬顧客")

    nxt = poll.peek_next_ticket()
    if nxt is None:
        st.info("腳本票單已全部餵完。")
    else:
        st.caption(f"下一張：intent={nxt.get('intent')}｜{nxt.get('customer_ref')}")
        st.code(nxt.get("content", ""), language=None)

    if st.button("餵下一張票", disabled=nxt is None, type="primary"):
        fed = poll.feed_next_ticket(db)
        if fed is None:
            st.warning("沒有票可餵了。")
        else:
            st.session_state["p2_ticket"] = fed
            try:
                st.session_state["p2_result"] = realtime.handle_open_ticket(db, fed["ticket_id"])
                st.session_state["p2_error"] = None
            except OperationFailed as exc:
                st.session_state["p2_result"] = None
                st.session_state["p2_error"] = str(exc)
            st.rerun()

    fed = st.session_state.get("p2_ticket")
    result = st.session_state.get("p2_result")
    if fed:
        st.divider()
        st.markdown(f"**顧客原文（#{fed['seq']}／{fed['total']}）**")
        st.info(fed["content"])
        st.markdown("**系統回覆**")
        if result and result["status"] == "deflected":
            path = db.run_sql(
                "SELECT path FROM Tutorial WHERE tutorial_id = :id",
                {"id": result["tutorial_id"]},
            )
            link = path[0]["path"] if path else f"tutorial #{result['tutorial_id']}"
            st.success(
                f"這題已經有教學了：{link}（{result['tutorial_version']}）\n\n"
                "— 已自動回覆顧客，未進人工佇列。"
            )
        elif result:
            st.warning("目前沒有可用的教學 → 轉真人客服處理。")
        elif st.session_state.get("p2_error"):
            st.error(f"操作失敗：{st.session_state['p2_error']}；票維持 open")


# --- 中欄：決策卡 ＋ 轉真人 ---


def _render_decision(db) -> None:
    st.subheader("這張：deflected ／ 轉真人")

    fed = st.session_state.get("p2_ticket")
    result = st.session_state.get("p2_result")
    if not fed or not result:
        st.caption("按左欄「餵下一張票」開始。")
        return

    cols = st.columns(3)
    cols[0].metric("本機決策", result["status"])
    cols[1].metric("理由", result["reason"])
    cols[2].metric("ticket_id", result["ticket_id"])
    if result.get("reopened_from_ticket_id"):
        st.caption(f"再開票：reopened_from_ticket_id = {result['reopened_from_ticket_id']}")
    if "replay_count" in result:
        st.caption(f"Workflow（Rote）：replay_count = {result['replay_count']}")

    echo = result.get("agent_echo")
    if echo is None:
        st.caption("Agent 未回應（本機決策照跑）")
    elif echo.get("delivered"):
        st.caption(f"RocketRide Agent 已收到事件（task {echo.get('token', '')[:12]}…）")
    else:
        st.caption("RocketRide Agent 未確認送達（本機決策照跑）")

    if result["status"] != "escalated":
        return

    st.markdown("**轉真人：確認解法**")
    default = st.session_state.get("p2_resolution") or fed.get("bitext_response") or ""
    text = st.text_area("解法（真人確認後才進知識庫）", value=default, height=160, key="p2_resolution_box")
    if st.button("確認解法"):
        try:
            realtime.resolve_ticket(db, result["ticket_id"], text)
            st.success(f"已結案：Ticket {result['ticket_id']} status = resolved")
        except OperationFailed as exc:
            st.error(f"操作失敗：{exc}")


# --- 中欄：分析 → CREATE ---


def _render_analysis(db) -> None:
    st.divider()
    if st.button("分析 Support Tickets"):
        try:
            actions = analysis.analyze_tickets(db)
        except OperationFailed as exc:
            st.error(f"操作失敗：{exc}")
            return
        st.session_state["p2_actions"] = actions
        created = []
        for action in actions:
            if action["action"] != "CREATE":
                continue
            try:
                created.append(create_tutorial.create_tutorial(db, action["user_problem_id"]))
            except OperationFailed as exc:
                st.error(f"CREATE 失敗（user_problem_id={action['user_problem_id']}）：{exc}")
        st.session_state["p2_created"] = created

    actions = st.session_state.get("p2_actions")
    if actions is not None:
        st.markdown("**分析結果（動作）**")
        st.write(actions or "（無 recurring topic）")
    for item in st.session_state.get("p2_created", []):
        st.success(
            f"CREATE：{item['path']}（{item['version']}，published，"
            f"內容來源 {'LLM' if item['source'] == 'llm' else '模板降級'}）"
        )


def _render_tutorials() -> None:
    st.divider()
    st.markdown("**tutorials/*.md**")
    files = sorted(TUTORIALS_DIR.glob("*.md")) if TUTORIALS_DIR.exists() else []
    if not files:
        st.caption("`tutorials/` 尚無 .md（按「分析 Support Tickets」後由 CREATE 產出）。")
        return
    picked = st.selectbox("挑一篇", [p.name for p in files], key="p2_md_pick")
    st.markdown((TUTORIALS_DIR / picked).read_text(encoding="utf-8"))
