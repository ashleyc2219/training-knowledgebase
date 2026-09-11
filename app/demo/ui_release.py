"""Demo：貼 changelog 入庫 ＋ 處理 Release ＋ Step diff（Phase 5）。

UI 只觸發、只展示（showme §13）：擷取、多跳、UPDATE／RETIRE 全在
`app/agent/release_update.py`，這裡不判斷 change_type、不決定動作。
"""

from __future__ import annotations

import difflib

import streamlit as st

from app.agent.release_update import process_unprocessed_releases
from app.errors import OperationFailed
from app.ingest.changelog import ingest_release_text, now_iso

DEFAULT_NOTE = "Cancel Order has been renamed to Cancel Purchase."

CURRENT_VERSIONS = """
SELECT t.tutorial_id AS tutorial_id, t.path AS path, t.status AS status,
       t.current_version AS current_version, v.steps AS steps
FROM Tutorial t
LEFT JOIN TutorialVersion v
  ON v.tutorial_id = t.tutorial_id AND v.tutorial_version = t.current_version
ORDER BY t.tutorial_id
"""


def _snapshot(db) -> dict[int, dict]:
    return {row["tutorial_id"]: row for row in db.run_sql(CURRENT_VERSIONS)}


def _diff(before: dict, after: dict) -> str:
    return "\n".join(
        difflib.unified_diff(
            str(before.get("steps") or "").splitlines(),
            str(after.get("steps") or "").splitlines(),
            fromfile=f"{before.get('current_version')}（舊）",
            tofile=f"{after.get('current_version')}（新）",
            lineterm="",
        )
    )


def render(db) -> None:
    """左欄貼 changelog、中欄處理 Release 並顯示 Step diff。"""
    left, mid = st.columns([1, 1.4])

    # --- 左欄：貼 changelog → 入庫（入庫 ≠ 處理） ---
    with left:
        st.markdown("**貼 changelog**")
        text = st.text_area("Release Note 一則", value=DEFAULT_NOTE, height=80, key="release_note_text")
        created_at = st.text_input("created_at（ISO 8601）", value=now_iso(), key="release_note_ts")
        if st.button("入庫", key="release_ingest"):
            release_id = ingest_release_text(db, text, created_at.strip() or None)
            if release_id:
                st.success(f"Release #{release_id} 已入庫，processed_at 為空。")
            else:
                st.info("相同 content + created_at 已存在，不新增列。")

        pending = db.run_sql(
            "SELECT id, content FROM Release WHERE processed_at IS NULL OR processed_at = '' ORDER BY id"
        )
        st.caption(f"待處理 Release：{len(pending)} 列")
        for row in pending:
            st.caption(f"#{row['id']} {row['content']}")

    # --- 中欄：處理 Release → 決定的動作 ＋ Step diff ---
    with mid:
        st.markdown("**處理 Release**")
        if st.button("處理 Release", key="release_process"):
            before = _snapshot(db)
            try:
                decisions = process_unprocessed_releases(db)
                st.session_state["release_result"] = {"before": before, "decisions": decisions}
                st.session_state.pop("release_error", None)
            except OperationFailed as exc:
                st.session_state["release_error"] = str(exc)

        if st.session_state.get("release_error"):
            st.error(f"操作失敗：{st.session_state['release_error']}")

        result = st.session_state.get("release_result")
        if not result:
            st.caption("按上面的按鈕處理所有 processed_at 為空的 Release。")
            return

        decisions = result["decisions"]
        if decisions:
            st.write("受影響 Tutorial 與動作：")
            st.table(decisions)
        else:
            st.info("沒有受影響的 Tutorial，只記錄 processed_at（規格 Rule 8／9）。")

        after = _snapshot(db)
        for decision in decisions:
            tutorial_id = decision["tutorial_id"]
            old = result["before"].get(tutorial_id, {})
            new = after.get(tutorial_id, {})
            st.markdown(f"**Tutorial #{tutorial_id}｜{new.get('path', '')}｜{decision['action']}**")
            col1, col2 = st.columns(2)
            col1.caption(f"{old.get('current_version')}（舊）")
            col1.code(str(old.get("steps") or ""), language="text")
            col2.caption(f"{new.get('current_version')}（新）")
            col2.code(str(new.get("steps") or ""), language="text")
            diff = _diff(old, new)
            if diff:
                st.code(diff, language="diff")

        features = db.run_sql("SELECT id, name, status FROM Feature ORDER BY id")
        st.caption("Feature 目前狀態：" + "、".join(f"{f['name']}（{f['status']}）" for f in features))
