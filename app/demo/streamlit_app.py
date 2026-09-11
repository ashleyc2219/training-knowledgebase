"""Demo UI（單一分頁）。

邊界見 docs/design/showme.md §13：UI 只觸發、只展示，**不**計算門檻、**不**決定 CREATE／擋票。
版面（docs/design/architecture.md §1）：
    左：假裝進資料（餵票／貼 changelog）   中：Agent 產出（deflected／轉真人、教學、diff）
    下：學習指標（deflection rate、平均 rating、重放率、圖譜覆蓋）
各區塊由 app/demo/ui_*.py 提供 render(db)，本檔只負責接線與重置。
"""

from __future__ import annotations

import os
from pathlib import Path

import streamlit as st

from app.analytics.db import get_db
from app.config import Settings
from app.demo import ui_feedback, ui_metrics, ui_release, ui_tickets

STATE_FILES = [
    ".state/graph.json",
    ".state/metrics_history.json",
    ".state/demo_cursor.json",
    ".state/last_checked.json",
]
TUTORIALS_DIR = Path("tutorials")

st.set_page_config(page_title="客服自助教學生成器", layout="wide")


@st.cache_resource
def _db():
    return get_db()


def _reset(db) -> None:
    """一鍵重置：清 9 表、清 .state 游標／圖譜／指標歷史、清產出的 .md。"""
    reset = getattr(db, "reset", None)
    if reset is not None:
        try:
            reset()
        except NotImplementedError:
            st.warning("hotdata backend 不支援 reset；請改用 DB_BACKEND=sqlite 彩排。")
    for f in STATE_FILES:
        Path(f).unlink(missing_ok=True)
    if TUTORIALS_DIR.exists():
        for md in TUTORIALS_DIR.glob("*.md"):
            md.unlink()
    for key in list(st.session_state.keys()):
        del st.session_state[key]


def _sidebar(db) -> None:
    settings = Settings.from_env()
    st.sidebar.title("客服自助教學生成器")
    st.sidebar.caption("單一 Agent 的客服 deflection 教學生成器（hackathon demo）")
    st.sidebar.markdown(
        f"- DB backend：`{settings.DB_BACKEND}`\n"
        f"- Rote Play：`{os.getenv('ROTE_PLAY_NAME') or '未設定'}`\n"
        f"- LLM：`{'Anthropic' if settings.ANTHROPIC_API_KEY else ('RocketRide' if os.getenv('ROCKETRIDE_PROJECT_ID') else '模板降級')}`\n"
        f"- Cognee：`{'已設定' if settings.COGNEE_URL else '未設定'}`\n"
        f"- HydraDB：`{'HTTP' if settings.HYDRADB_URI else '本機圖譜檔'}`"
    )
    st.sidebar.divider()
    if st.sidebar.button("重置 demo 資料", type="secondary"):
        _reset(db)
        st.sidebar.success("已重置。請重新執行種子匯入：`uv run python -m app.ingest.seed`")
        st.rerun()
    st.sidebar.caption("Demo 順序：種子 → 餵 3 張 cancel_order 轉真人 → 分析 CREATE v1 → 第 4 張 deflect → 第 5 張重放 → 回饋 Review REFINE → 貼 changelog UPDATE")


def main() -> None:
    db = _db()
    _sidebar(db)

    st.title("客服自助教學生成器")
    st.caption("左：假裝進資料　中：Agent 寫／改教學文件　下：曲線證明它有變聰明")

    # 上半：餵票（左）＋ Agent 產出（中）
    ui_tickets.render(db)

    st.divider()
    # Release Note：左貼 changelog、中 Step diff
    ui_release.render(db)

    st.divider()
    # 顧客回饋與 Review（REFINE）
    ui_feedback.render(db)

    st.divider()
    # 下：評審拍照區
    ui_metrics.render(db)

    st.divider()
    _memory_panel()


def _memory_panel() -> None:
    """記憶層狀態：HydraDB Cloud（鏡射的節點／邊、抽出的關係、recall）與 Cognee dataset。"""
    from app.memory.hydradb_client import HydraDBClient

    with st.expander("記憶層：HydraDB 圖譜 ＋ Cognee", expanded=False):
        g = HydraDBClient()
        st.markdown(f"**本機索引**：{len(g.nodes())} 節點／{len(g.edges())} 邊（`.state/graph.json`，五種邊的多跳在這裡算）")
        status = g.remote_status()
        if status.get("backend") == "hydradb":
            st.markdown(
                f"**HydraDB Cloud**：database `{status.get('database')}`／collection `{status.get('collection')}`，"
                f"ready={status.get('ready_for_ingestion')}，memory rows={status.get('memory_rows')}"
            )
            rels = g.relations(limit=30)
            st.markdown(f"HydraDB 自己抽出的關係：{len(rels)} 條")
            if rels:
                rows = []
                for r in rels[:15]:
                    src, tgt = r.get("source"), r.get("target")
                    rows.append({
                        "source": src.get("name") if isinstance(src, dict) else src,
                        "target": tgt.get("name") if isinstance(tgt, dict) else tgt,
                        "relations": ", ".join(
                            str(x.get("relation") or x.get("predicate") or x) for x in (r.get("relations") or [])[:3]
                        ),
                    })
                st.dataframe(rows, use_container_width=True, hide_index=True)
            q = st.text_input("HydraDB recall", value="which tutorial explains Cancel Order", key="hydra_recall_q")
            if st.button("Recall", key="hydra_recall_btn"):
                out = g.recall(q, top_k=5)
                if out.get("error"):
                    st.warning(out["error"])
                for c in out.get("chunks") or []:
                    st.code((c.get("chunk_content") or "")[:300])
        else:
            st.info("HYDRADB_URI 未設定：只用本機圖譜檔（降級）。")
        settings = Settings.from_env()
        st.markdown(f"**Cognee**：{'已設定，dataset `' + (settings.__dict__.get('COGNEE_DATASET') or 'support_tutorials') + '`' if settings.COGNEE_URL else '未設定'}")


main()
