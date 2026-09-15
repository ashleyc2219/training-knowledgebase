"""Demo Dashboard（Phase 58 Task 4）：**只**把 `demo/view_model.py` 算好的東西畫出來。

```bash
uv run streamlit run demo/dashboard.py
```

這支檔案刻意保持「沒有邏輯」：沒有函式、沒有類別、沒有任何四則運算，只 import
`streamlit` 與 `demo.view_model`。所有數字都是 `load_dashboard()` 回來的現成值，
而那些值又全部由 Phase 53／54 的函式從原始資料重算——指標公式因此只有一份。
守門測試 `tests/unit/test_demo_dashboard_guard.py` 用 AST 檢查這幾件事，而且它**不會**
import 本檔（import 等於在 pytest 裡執行整支 Streamlit 腳本）。

**唯讀。** 本檔只讀本機種子目錄；沒有任何寫入呼叫，也沒有任何金鑰字面值（R11）。
要寫資料一律回到 `demo/cli.py`，走 `lambda:invoke` 或 `states:StartExecution`。

**橫幅永遠在最上方**，固定含合成資料標示、批次名稱、時間標示與 gate 現況；
現場失敗改用備援時，在側欄填入失敗原因，橫幅會改成「目前顯示預先執行結果」並附上原因
（設計 §11.5：備援不得說成本次成功）。O7 未核定時只會看到「待維護者核定」。
"""

import streamlit as st

from demo.view_model import (
    DASHBOARD_BLOCKS,
    TIME_KEYS,
    load_dashboard,
    render_banner,
)

st.set_page_config(page_title="Training KB Demo 控制台", layout="wide")

st.session_state.setdefault("seed_dir", "demo/seed")
st.session_state.setdefault("fallback_reason", "")

st.sidebar.text_input("種子目錄（本機唯讀）", key="seed_dir")
st.sidebar.text_input("本次現場失敗原因（留白＝即時執行）", key="fallback_reason")
st.sidebar.caption("這個畫面不寫任何資料；要觸發流程請用 python -m demo.cli。")

data = load_dashboard(st.session_state["seed_dir"],
                      fallback_reason=st.session_state["fallback_reason"] or None)

# 橫幅固定在最上方：合成資料標示、批次、時間標示、gate 現況、備援說明。
st.markdown(f"### {render_banner(data.banner)}")
st.caption(data.o7_line)
if data.missing_approvals:
    st.warning(f"缺少維護者核定紀錄：{'、'.join(data.missing_approvals)}")

st.caption(f"本次現場模型呼叫：total={data.calls.total}、retries={data.calls.retries}、"
           f"by_node={dict(data.calls.by_node)}")

st.subheader(DASHBOARD_BLOCKS[0])
st.caption("模擬歷史回放與本次現場執行分成兩張表，不合併成同一組使用者成效。")
for time_key in TIME_KEYS:
    st.markdown(f"**{time_key}**")
    st.json(data.blocks[DASHBOARD_BLOCKS[0]][time_key])

for block_name in DASHBOARD_BLOCKS[1:]:
    st.subheader(block_name)
    st.json(data.blocks[block_name])
