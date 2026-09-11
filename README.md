# 客服自助教學生成器（Self-Improving Support Tutorial Generator）

顧客票單聚成 UserProblem → 產生 Tutorial → 同類新票自動回覆教學連結（deflection）→
Feedback 與 Release Note 驅動 REFINE / UPDATE / RETIRE。

作用中規格：`docs/spec/erm.dbml`、`docs/spec/features/*.feature`；設計：`docs/design/showme.md`。
目前進度：**Phase 0 骨架**（門檻函式、SQL 層、demo 資料、Streamlit 外殼）。Pipeline 尚未接外部服務。

## 怎麼跑

```bash
uv sync --extra dev                                   # 建 .venv（Python 3.12）
uv run pytest -q                                      # 單元測試（門檻函式 + 指標）
uv run python -m app.ingest.bitext                    # 下載 Bitext → data/seed/、data/script/
uv run streamlit run app/demo/streamlit_app.py        # demo 畫面
uv run python scripts/reset_demo.py                   # 重置 .state/ 與 tutorials/*.md
```

金鑰放 `.env`（git-ignored），由 `app/config.Settings.from_env()` 讀取。
`DB_BACKEND=sqlite`（預設，`.state/local.db`）或 `DB_BACKEND=hotdata`。

## 五層對應（詳見 `docs/design/showme.md` §5、§9）

| 層 | 工具 | 模組 |
|---|---|---|
| Memory 建構 | Cognee | `app/memory/cognee_client.py` |
| Memory 儲存 | HydraDB | `app/memory/hydradb_client.py` |
| Live 分析 | hotdata.dev | `app/analytics/`（`sql.py` / `hotdata_client.py` / `metrics.py`） |
| Motion / 協調 | RocketRide | `app/agent/`（realtime / analysis / feedback_review / release_update） |
| Muscle memory | Modiqo Rote | `app/muscle/rote_client.py` |
| 安全 | Snyk | 掃描依賴與原始碼；`.env` 不進 repo |
