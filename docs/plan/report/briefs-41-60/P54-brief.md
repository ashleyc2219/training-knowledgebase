# P54 brief — 重開票與呼叫規則指標

## 1. 單一交付物與停止點
- **交付物**：`ReopenStats`／`VersionMetrics` 兩組指標（O4 窗口 `[p, p+14 days)` UTC）＋ `training-kb-analytics` 的 Lambda 入口（只認 `action: "metrics"`）＋ 它在 `infra/training_kb_stack.py` 的 CDK 接線。
- **停止點**：三個測試檔綠、`cdk synth` 跑得過、全套 `-W error` 綠；**不判規則狀態、不寫任何 item、不呼叫模型、不做多版本 rate 彙總、不建 state machine／Function URL／排程**。

## 2. 已存在、直接重用
| file:name | 用途 |
|---|---|
| `src/training_kb/writing/client.py::CallTrace` | `count(*, operation_id=None)` 就是 `bedrock_call_count` 的全部實作；`TRACE_FIELDS` 七鍵、`TRACE_KINDS={embedding,generation,tool_use}`、`TRACE_OUTCOMES={success,transient_error,permanent_error}`。**`from training_kb.writing import CallTrace` 可用**（`__init__` 有 re-export） |
| `src/training_kb/repository.py` | `list_views_of_version(v) -> list[TutorialView]`（掃 VIEW、`tutorial_version` 等值、依 `(ts,user)` 排序）、`list_tickets(project_id) -> list[Ticket]`、`list_rules(status=None)`、`list_feedback_of_version`、`get_tutorial`、`get_version`。`_paged` 已讀完所有分頁（含空頁） |
| `src/training_kb/repository.py::list_versions_applying_rule(rule_id) -> list[str]` | 「從 DB 查」版的套用次數（`APPLIED_TO` 邊取候選 → `rules_applied` 為唯一權威過濾去重）。本 Phase 的 `applied_count` 是「對已取得 version 清單算」的純函式，**兩者並存、不互相取代** |
| `src/training_kb/ingress.py::_wiring/_reset_wiring/_build_wiring` | Lambda 接線的既有範式：模組層快取 + `boto3.resource(..., region_name=settings.aws_region)` + 一支 `_reset_wiring()` 給測試。`handlers/analytics.py::_wiring()` 照抄這一套 |
| `src/training_kb/analytics/ratings.py`（P53，同波 W1） | `average_rating`／`negative_feedback_ids`／`format_average`，走**子模組路徑** import |
| `src/training_kb/operations.py::OperationCoordinator` | P10 ledger；本 Phase 只讀不寫，`metrics` action 不 accept operation |
- 測試 fixture：沒有可沿用的；`FakeRepo` 寫在 `test_reopen_metrics.py` 內（P54 不是 `tests/unit/conftest.py` 的修改者，那是 P55）。

## 3. 要新增／修改的東西
| 動作 | 路徑 | 名稱（00A §6.10 為契約） |
|---|---|---|
| 新增 | `src/training_kb/analytics/reopen.py` | `reopen_window(published_at: datetime, days: int = 14) -> tuple[datetime, datetime]`；`@dataclass(frozen=True) ReopenStats(count, reopen_users, viewers, rate: float\|None)`；`reopen_stats(views, tickets, *, cluster_id, published_at) -> ReopenStats` |
| 新增 | `src/training_kb/analytics/rules_metrics.py` | `rule_counts(rules) -> dict[str,int]`（固定三鍵補 0）；`applied_count(versions, rule_id) -> int`；`bedrock_call_count(trace, *, operation_id=None) -> int` |
| 新增 | `src/training_kb/analytics/version.py` | `@dataclass(frozen=True) VersionMetrics(version_id, published_at, average, sample_size, negative_ids, reopen)`；`version_metrics(version_id, *, repository, approved, project_id)`；`metrics_action(event, *, repository, approved, project_id) -> dict` |
| 新增 | `src/training_kb/handlers/analytics.py` | `handler(event: dict, context: object) -> dict`（D-56）＋ 私有 `_wiring()`／`_reset_wiring()` |
| **修改** | `infra/training_kb_stack.py` | 加 `training-kb-analytics`（D-58）。**⚠ 共用檔**：00A §3.2 的修改者有 P42、P48、P52、P54 → 只用 **Edit**、放自己的 `# ---- Phase 54 ----` 區段、`ruff format` 只跑自己新建的檔 |
| **修改** | `tests/unit/test_feedback_review_flow.py`（P48 的檔） | 只把 `names == {...}` 補上 `"training-kb-analytics"`。這是 R3.6 的**有文件依據的例外**（P48 §7 逐字預告），只改那一行 |
| 測試 | `tests/unit/test_reopen_metrics.py`、`tests/unit/test_rule_and_call_metrics.py`、`tests/unit/infra/test_analytics_stack.py` | 00A §3.3 指定；三個 basename 目前未被占用 |
| **不動** | `src/training_kb/analytics/__init__.py` | P53（owner）裁決維持 docstring-only、不 re-export → 消掉 W1 同檔併行 |

## 4. Task 順序與紅燈訊號
1. **Task 1 O4 窗口**：RED `uv run pytest tests/unit/test_reopen_metrics.py -q` → `cannot import name 'reopen_window'`。GREEN：`(P1, P1+14d)`、`days=7` 可調、naive datetime 丟 `ValueError`。另確認全 repo 只有這裡出現 `timedelta(days=14)`：`rg -n 'timedelta\(days=14\)' src/`
2. **Task 2 分子分母去重＋六邊界**：RED 同上 → `cannot import name 'reopen_stats'`。GREEN：v1 `ReopenStats(7,7,10,0.7)`、v2 `(2,2,10,0.2)`；六個邊界各一個測試（先開票後瀏覽／重複瀏覽／多次開票／不同 cluster／`ts==p+14d` 與 `ts==p`／零瀏覽者 `rate is None`）
3. **Task 3 規則計數＋呼叫數**：RED `uv run pytest tests/unit/test_rule_and_call_metrics.py -q` → `cannot import name 'rule_counts'`。GREEN：三鍵補 0、`applied_count` 去重、`bedrock_call_count(trace) == 4`
4. **Task 4 `VersionMetrics` ＋ handler ＋ CDK**：RED `uv run pytest tests/unit/test_reopen_metrics.py -q` → `cannot import name 'version_metrics'`。GREEN：
   ```bash
   uv run pytest tests/unit/test_reopen_metrics.py tests/unit/test_rule_and_call_metrics.py \
                tests/unit/infra/test_analytics_stack.py tests/unit/test_feedback_review_flow.py -q
   AWS_REGION=us-east-1 AWS_DEFAULT_REGION=us-east-1 command npx aws-cdk@2 synth --quiet
   ```
5. **收尾 gate**：`uv run pytest tests -q -W error`、`uv run ruff check src tests infra`、`uv run ruff format --check src tests infra`、`uv run mypy`
6. **提交**：逐檔列路徑（**不要** `git add src/training_kb/analytics/`），trailer 照 COMMON R8

## 5. 00B primary Rule 與對應測試
| Rule | 測試 |
|---|---|
| `MET` 3 同題重開票率（14 天、同 cluster）| `test_reopen_metrics.py::test_reopen_stats_reproduces_design_v1_seven_over_ten` ＋ 六邊界 |
| `MET` 4 分母取自教學瀏覽事件 | `reopen_stats` 簽名只收 `views`；零 View 案例 `rate is None` |
| `MET` 5 穩定使用者 ID 配對 | `view.user == ticket.author`，不比顯示名稱 |
| `MET` 7 已學規則數依 status 分別計數 | `test_rule_and_call_metrics.py::test_rule_counts_reports_all_three_statuses_with_zero_fill` |
| `MET` 8 規則套用次數 | `test_applied_count_rebuilds_from_rules_applied_and_deduplicates` |
| `MET` 9 Bedrock 呼叫數含 SFN 節點與 Rote 層 | `test_bedrock_call_count_counts_every_real_attempt`（4 筆 attempt 含 retry／Rote／embedding） |
- **相關（不認領）**：`MET` 11（primary P58）、`RUN` 1（primary P56）、`TIC` 3／`APL` 6／`GRF` 5／`COL` 9（primary 在 P39／P28／P27／P42）。

## 6. 風險與陷阱
- **`infra/training_kb_stack.py` 目前不存在**（`infra/` 只有 `__init__.py`、`app.py`、`training_kb_data_stack.py`、`scripts/`）。P41 才建，`tests/unit/infra/` 也是 P41 首建 → **CDK Task 必須排在 P41 之後**。
- **§7 Task 4 的四支 Lambda 字典等號同時要求 P42 已落地**（第三支 `training-kb-import`）。P42 未落地時改包含式斷言並在報告寫明降級原因，**不得**刪別人的資源讓等號成立。
- **COMMON R2**：`Code.from_asset("src")` 不含 `pydantic`／`jsonschema` → 沿用 P41 的 layer／bundling，不自己再做一套。
- **`cdk` 指令**：本機 shell 把 `node` 定成會拒絕的 function → 一律 `command npx aws-cdk@2 <子命令>`，帶 `AWS_REGION=us-east-1 AWS_DEFAULT_REGION=us-east-1`；`--outputs-file` 指到 scratchpad；**不提交 `cdk.out/`**。
- **P43 尚未實作**（`approved_categories` 是 `_wiring()` 的相依）。單元測試不受影響（`approved` 是參數）；handler 測試只驗「未知 action 在接線前丟 `PermanentError`」，不要 monkeypatch 假的 `approved_categories`。
- **`_wiring()` 不能在 import 時執行**，未知 action 必須在建 boto3 資源前就 `raise`，否則單元測試會需要 AWS 憑證。
- **rate 的 `None` vs `0.0`**：零分母一律 `None`，否則 P55 會誤判「rate 嚴格下降」。
- **`count` 不是比例**：設計 §11.3 的 7／2 是**筆數**，70%／20% 是補上分母後才成立。
- **`view.ts < ticket.ts` 是嚴格小於**；同人多筆瀏覽取**最早**。
- **recurring 的十四天不可混用**：那是「UTC 當日加前十三日」（P39），與本 Phase 的 `[p, p+14d)` 是兩回事。
- **mypy strict 涵蓋 `src` 與 `infra`**：`infra/training_kb_stack.py` 的新程式也要過。
- 浮點：`7/10 == 0.7`、`2/10 == 0.2` 剛好成立。

## 7. 需要裁決的點 → 建議裁決
1. **P54 排在哪一波？** controller dispatch 同時寫了「W1：P53 ∥ P54」與「P54 在 W2 與 P42 同波」。→ **建議：P54 的純函式 Task 1–3 可在 W1 做；Task 4 的 CDK 與 `Template` 等號斷言排在 P41＋P42 之後。** 需要 controller 確認。
2. **P42 未落地時的 stack 斷言** → 降級為包含式，報告寫明（已寫進 Phase 54 文件）。
3. **改 P48 的測試檔** → 允許，但只加一個名字、不動其他行，報告寫明（P48 §7 已預告）。
4. **`analytics/__init__.py`** → 本 Phase 不碰（P53 owner 裁決）。

## 8. 對 AWS 的實際操作
- **一定要做**：`AWS_REGION=us-east-1 AWS_DEFAULT_REGION=us-east-1 command npx aws-cdk@2 synth --quiet`（本機合成，不連 AWS）；`Template.from_stack` 在 `uv run pytest` 下可用（jsii 正常）。
- **可能要做**（依 P41 部署狀態，由 controller 決定）：`cdk deploy TrainingKbApp`；部署後用 boto3 `invoke` 打 `training-kb-analytics` 的 `{"action":"metrics","version_ids":[...]}`，**不開 Function URL**。
- **資源**：region `us-east-1`、帳號 `123456789012`、table `training_kb`、bucket `training-kb-content-example`。
- **證據存放**：`docs/plan/report/phases/2026-09-14-Phase54-REP.md`（貼 `synth` 輸出摘要、`aws lambda get-function --function-name training-kb-analytics --region us-east-1` 的回應摘要）。**不把任何憑證、ARN 以外的帳號資訊或 bucket 內容寫進 repo**；`--outputs-file` 一律指到 scratchpad。
