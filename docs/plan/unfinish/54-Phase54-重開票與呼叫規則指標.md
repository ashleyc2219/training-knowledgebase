# Phase 54：重開票與呼叫規則指標實作計畫

> **給實作者：** 依 checkbox 逐步執行；每個 Task 先建立失敗測試，再寫最小實作。執行時使用 `superpowers:executing-plans` 或同等逐項流程。

> **現況核對（2026-09-14，Phase 41–60 批次 W0）：**
>
> **（a）已存在、可直接用**
> - `src/training_kb/writing/client.py`：`CallTrace`（`add` / `count(*, operation_id=None)` / `next_attempt` / `to_json`）、`TRACE_FIELDS`（七個鍵，多一個少一個都 `PermanentError`）、`TRACE_KINDS = {"embedding","generation","tool_use"}`、`TRACE_OUTCOMES = {"success","transient_error","permanent_error"}`。`CallTrace` 已由 `writing/__init__.py` re-export，`from training_kb.writing import CallTrace` **可用**。
> - `src/training_kb/repository.py`：`list_views_of_version(version_id) -> list[TutorialView]`（掃 `VIEW` entity、以 `tutorial_version` 等值過濾、依 `(ts, user)` 排序）、`list_tickets(project_id) -> list[Ticket]`（依 `id` 升序）、`list_rules(status=None) -> list[AuthoringRule]`、`list_feedback_of_version`、`get_tutorial`、`get_version` 全部已實作，`_paged` 已讀完所有分頁（含空頁）。**另有 `list_versions_applying_rule(rule_id) -> list[str]`**（從 `APPLIED_TO` 邊取候選、再以 `VERSION.rules_applied` 為唯一權威過濾去重，依版號升序）——它是「從 DB 查」的版本，本 Phase 的 `applied_count(versions, rule_id)` 是「對已取得的 version 清單算」的純函式，兩者同一條 D17 規則，**不要互相取代**。
> - `src/training_kb/models.py`：`TutorialView(tutorial_version, user, ts)`、`Ticket(id, source: TicketSource, text, author, ts, project_id, cluster_id, feature_ids, embedding)`、`TutorialVersion(version_id, slug, supersedes, reason, rules_applied, s3_key, published_at)`、`AuthoringRule(rule_id, rule, applies_when: StepType, evidence, status: RuleStatus, applied_to, derived_from)` 全部已存在。`TicketSource` 的三個值是 `github_issue`／`discord`／`email`（§7 helper 用的 `"email"` 合法）；`AuthoringRule.evidence` **至少五個不重複 ID**（§7 的 `EVIDENCE` 五筆剛好夠）。
> - `src/training_kb/ingress.py::_wiring()` / `_reset_wiring()` / `_build_wiring(settings)` 是本專案**既有的 Lambda 接線範式**：模組層 `_WIRING` 快取、`boto3.resource(..., region_name=settings.aws_region)`、另備一支 `_reset_wiring()` 給測試清快取。本 Phase 的 `handlers/analytics.py::_wiring()` 照這一套寫（§7 Task 4 的片段已補上這兩點）。
> - `src/training_kb/analytics/__init__.py` 已由 Phase 40 建成 docstring-only 空殼；`src/training_kb/handlers/__init__.py` 已由 Phase 30 建立，docstring 已列出 `training-kb-analytics → analytics.handler（P54／P55）`。
>
> **（b）因上一批裁決／現況而修正的點**
> 1. **`infra/training_kb_stack.py` 目前不存在**（現況：`infra/` 只有 `__init__.py`、`app.py`、`training_kb_data_stack.py`、`scripts/`）。它由 **Phase 41 建立**（00A §3.2、D-21），`tests/unit/infra/` 這個目錄也由 Phase 41 首建。**本 Phase 的 CDK Task 必須排在 Phase 41 之後**。
> 2. **§7 Task 4 的 `Template` 斷言（四支具名 Lambda 的字典等號）另外要求 Phase 42 已落地**——第三支 `training-kb-import` 是 Phase 42 加的（D-58）。**本計畫選擇：**本 Phase 的實作排在 Phase 41 與 Phase 42 之後；萬一輪到本 Phase 時 Phase 42 尚未落地，改用**包含式**斷言（`handlers["training-kb-analytics"] == "training_kb.handlers.analytics.handler"` ＋ `template.resource_count_is("AWS::Lambda::Url", 1)`），在報告寫明是因為 Phase 42 未落地而降級，**不得**為了讓等號成立去刪別的 Phase 的資源或測試。Phase 41 的 `test_stack_has_one_standard_machine_and_two_named_lambdas` 已經改成包含式斷言，不會因為多出第四支而轉紅。
> 3. **`lambda_.Code.from_asset("src")` 只會帶原始碼，不含 `pydantic`／`jsonschema`（COMMON R2）。** §7 Task 4 的 CDK 片段照抄 Phase 41 的寫法，實作時**一律沿用 Phase 41 建立的相依 layer／bundling**，不在本 Phase 另做一套（現況核對 2026-09-14：原片段只寫 `code=lambda_.Code.from_asset("src")`）。
> 4. **`cdk` 指令要用 `command npx aws-cdk@2`**：本機互動 shell 把 `node` 定義成會拒絕的 function（`Security: node blocked`），所以 §7 Task 4 的 `cdk synth --quiet` 實際要寫成 `AWS_REGION=us-east-1 AWS_DEFAULT_REGION=us-east-1 command npx aws-cdk@2 synth --quiet`（COMMON.md §1；全案固定 `us-east-1`，`--outputs-file` 一律指到 scratchpad，**不提交 `cdk.out/`**）。「不加 `uv run`」那句仍然正確。
> 5. **§4 的「修改 `src/training_kb/analytics/__init__.py`」這一列取消。** Phase 53（該檔 owner）依 00A §3.2 的授權裁決「維持 docstring-only、不 re-export」，理由是與既有 `pipelines/__init__.py` 同一套 house style，而且本文件與 Phase 55／56／58 的測試片段**全部**用子模組路徑 import。本 Phase 與 Phase 53 同一實作波（W1），這條裁決同時消掉 COMMON R3 的同檔併行風險。
> 6. **更新 Phase 48 的 Lambda 名稱集合斷言是「有文件依據的例外」。** COMMON R3.6 原則上禁止改別的 Phase 的測試檔，但 Phase 48 §7 已逐字寫「Phase 54 之後會再加第四支 `training-kb-analytics`，屆時要把上面那個名稱集合補齊」。要改的是 `tests/unit/test_feedback_review_flow.py::test_stack_has_review_machine_and_exactly_one_daily_schedule` 裡那個 `names == {...}` 的集合，**只加一個名字、不動該檔其他任何一行**，並在報告寫明。
> 7. Phase 43 的 `approved_categories(repository)`（`_wiring()` 會呼叫）**目前尚未實作**，Phase 43 與本 Phase 同屬 41–60 這一批。`metrics_action` 與 `version_metrics` 都把 `approved` 當參數收，所以**單元測試不受影響**；只有 `handlers/analytics.py::_wiring()` 這條真實接線路徑需要 Phase 43 先落地，實作時若還沒有就把 Task 4 的 handler 分支測試維持在「未知 action 在接線前丟 `PermanentError`」，不去 monkeypatch 出一個假的 `approved_categories`。
> 8. §7 各 Task Step 5 的 `git commit -m "..."` 片段**沒有帶 trailer**；實作時補上 COMMON R8 的兩行 trailer，`git add` 只加自己的檔案路徑。
>
> **（c）gate 現況對本 Phase 的影響**（COMMON.md §2）
> - **O4 未到，本 Phase 是首驗**：§全域限制與 §6 的「O4 待核定、本計畫選擇 `[p, p+14 days)` UTC」敘述**維持不變**，端點測試不得刪。
> - **O5 BLOCKED**（Titan／Claude 都回 `ValidationException: Operation not allowed`；`docs/plan/report/o5-20260915T030245Z.md`）：本 Phase 不呼叫模型，`bedrock_call_count` 只讀 `CallTrace`，**單元測試不受影響**。真實 AWS 上 `training-kb-analytics` 的 `metrics` action 也不碰 Bedrock，可以照常驗收。
> - **O3 FAIL**（`docs/plan/report/o3-20260914t181109z.md`）：本 Phase 不發布，無影響。
> - **O2 PASS**、**O6 待核定**、**O7 未到**：與本 Phase 無關；§11 「不得宣稱 O4 已核定」那條維持。
> - **COMMON R1（真實 AWS 這一批要接）**：本 Phase 不在 R1 的名單（P41／P48／P52／P57／P59／P60）裡，但它改 `infra/training_kb_stack.py`，所以 `cdk synth` 必須真的跑過；要不要 `cdk deploy` 由 controller 依 Phase 41 的部署狀態決定，做不到就在報告寫 BLOCKED 與實際錯誤原文。
>
> **（d）適用的 controller 裁決（COMMON.md §3）**
> - **R2（Lambda 打包）**：見 (b)3。
> - **R3（同波同檔）**：`infra/training_kb_stack.py` 的修改者依 00A §3.2 有 P42、P48、P52、P54 四個 Phase——既有檔**只用 Edit 不用 Write**、新增資源放進自己的 `# ---- Phase 54 ----` 區段、不重排別人的程式、`git add` 只加自己的路徑。同波的 Phase 53 不碰本 Phase 的任何檔。
> - **R5**：文件片段是示意，00A §6.10 的名稱與簽名是契約。
> - **R6／R7／R9**：逐 Task 紅燈→綠燈並留證據；報告寫 `docs/plan/report/phases/2026-09-14-Phase54-REP.md`；不派 subagent。
> - 全套 gate：`uv run pytest tests -q -W error`、`uv run ruff check src tests infra`、`uv run ruff format --check src tests infra`、`uv run mypy`（strict，`files = ["src", "infra"]`——`analytics/*.py`、`handlers/analytics.py` 與 `infra/training_kb_stack.py` 都在範圍內，每個函式都要完整型別註記；測試檔不在範圍內）。測試檔 basename 全專案唯一（tests 沒有 `__init__.py`）：`test_reopen_metrics.py`、`test_rule_and_call_metrics.py`、`infra/test_analytics_stack.py` 三個名字目前都沒被占用。

**目標：** 在 O4 建議的 `[p, p+14 天)` UTC 窗口下重算同題重開票筆數與比率、規則狀態計數、規則套用次數與真實 Bedrock 呼叫數，組成 `VersionMetrics`，並建立 `training-kb-analytics` 的 Lambda 入口。

**架構：** `reopen_stats`、`rule_counts`、`applied_count`、`bedrock_call_count` 都是純函式；`version_metrics` 是唯一讀 Repository 的組裝函式，把 Phase 53 的評分指標與本 Phase 的重開票指標合成同一份結果；`handler` 只做 action 分派與外部資源接線，交 Phase 55 判定、Phase 58 顯示。

**技術：** Python 3.12、`datetime`（全部 timezone-aware UTC）、`dataclasses`、Phase 15 的 `CallTrace`、boto3、pytest。

## 全域限制

- 唯一主來源是 [Training KB 設計 §11.3、§12.1、§12.3、§18 O4](../../design/training-kb.md)；跨 Phase 名稱以 [00A 共用契約與名詞](00A-共用契約與名詞.md) 第 6.10 節為準，Rule 歸屬以 [00B 需求覆蓋對照](00B-需求覆蓋對照.md) 第 2.11、2.3 節為準。
- 前置為 [Phase 53：評分與負面回饋指標](./53-Phase53-評分與負面回饋指標.md)。前置未通過時停止。下一階段是 [Phase 55：規則驗證與狀態轉移](./55-Phase55-規則驗證與狀態轉移.md)。
- **O4 尚未核定。** 窗口端點 `[p, p+14 天)` 與 UTC 編碼是設計 §12.1 的建議；本計畫據此實作並在程式與測試中標成**本計畫選擇**。核定前不得宣稱窗口定義已由規格定案，也不得把多組 rate 自行彙總成單一數字。不得拿工單 recurring 的「UTC 當日加前十三日」替代這個窗口。
- 分母只能來自 `TUTORIAL_VIEW`。Feedback 共用同一個穩定使用者 ID，但**不是**「看過教學」的替代證據。
- 呼叫數以**每次真實 request attempt** 為單位；重試、Map 每個 item、Rote 層與 embedding 都算，記憶體重用不算。
- 本 Phase 的 `handler` 是 `training-kb-analytics` 這支**非 pipeline** Lambda 的入口（00A 第 8 節 D-56），只處理 `action: "metrics"`；它不是第四條教學 pipeline，也不進 Step Functions。
- `training-kb-analytics` 的 **CDK 接線也由本 Phase 完成**（00A D-58）：在 Phase 41 建立的 `infra/training_kb_stack.py` 上加這一支 Lambda 與最小 IAM。[Phase 55](./55-Phase55-規則驗證與狀態轉移.md) 只在同一支 handler 加 `action: "validate_rules"` 分支、**不再動 CDK**，所以本 Phase 給的權限必須連 Phase 55 的寫入一起涵蓋。
- 本階段不做：不判定規則狀態、不寫入任何 item、不呼叫模型、不做多版本 rate 彙總、不建立 Dashboard 畫面；不建立 state machine、不開 Function URL、不加排程。以下程式檔均是實作時預計建立或修改。

---

## 1. 你在整體流程的位置

```text
TUTORIAL_VIEW（分母）  TICKET（分子）  VERSION.rules_applied  CallTrace
        |                   |                  |                 |
        +--------+----------+                  |                 |
                 v                             v                 v
   +-----------------------------------------------------------------+
   | [你在這裡] reopen_window / reopen_stats / rule_counts            |
   |            applied_count / bedrock_call_count / version_metrics  |
   |            handlers/analytics.py::handler（action: "metrics"）    |
   +-----------------------------------------------------------------+
                 |                                    |
                 v                                    v
  Phase 55 evaluate_batch（rate 嚴格下降才可能啟用） Phase 58 Dashboard 四區塊
```

Phase 53 提供 `average`、`negative_ids`；本 Phase 補上 `reopen`，兩者一起才構成一版的完整指標。

## 2. 完成後看得到什麼

用設計 §11.3 的配方（`prepare-meeting@v1` 模擬發布於 `2026-08-01T00:00:00Z`，`u_01`～`u_10` 各在 `08-02T09:00:00Z` 瀏覽一次，`u_01`～`u_07` 各在 `08-03T10:00:00Z` 以 `t_2001`～`t_2007` 開票，`Ticket.cluster_id = c12`）：

```text
reopen_window(2026-08-01T00:00:00Z)
    -> (2026-08-01T00:00:00Z, 2026-08-15T00:00:00Z)   左含、右不含
reopen_stats(views_v1, tickets_v1, cluster_id="c12", published_at=p1)
    -> ReopenStats(count=7, reopen_users=7, viewers=10, rate=0.7)
reopen_stats(views_v2, tickets_v2, cluster_id="c12", published_at=p2)
    -> ReopenStats(count=2, reopen_users=2, viewers=10, rate=0.2)
handler({"action": "metrics", "version_ids": ["prepare-meeting@v1"]}, None)
    -> {"action": "metrics", "results": [{..., "display_average": "2.9", ...}]}
```

零瀏覽者的版本得到 `ReopenStats(0, 0, 0, None)`，畫面顯示「N/A／樣本不足」，不是 0%。

## 3. 名詞小抄

| 名詞 | 白話意思 |
|---|---|
| 窗口 | 從版本發布那一刻起算的十四天區間；左端包含發布時刻，右端不包含第十四天整點。 |
| 分母 `viewers` | 窗口內看過這一版的**不同使用者**數；同一人重複瀏覽只算一次。 |
| 分子 `reopen_users` | 先看過這一版、之後又在窗口內開同群工單的**不同使用者**數；同一人多次開票也只算一次。 |
| 筆數 `count` | 符合條件的**不同 Ticket ID** 數；可以大於 `reopen_users`，不能當比例。 |
| 同題 | `Ticket.cluster_id` 等於該篇首版 `gap:<cluster_id>` 固定下來的 `Tutorial.cluster_id`；不比標題文字。 |
| attempt | 一次真的送到 Bedrock 的請求；第二次重試是第二個 attempt，不是同一個。 |
| action | analytics Lambda 事件裡決定跑哪一種計算的欄位；本 Phase 只認得 `"metrics"`。 |

## 4. 預計檔案

| 動作 | 路徑 | 責任 |
|---|---|---|
| 新增 | `src/training_kb/analytics/reopen.py` | `reopen_window`、`ReopenStats`、`reopen_stats`。 |
| 新增 | `src/training_kb/analytics/rules_metrics.py` | `rule_counts`、`applied_count`、`bedrock_call_count`。 |
| 新增 | `src/training_kb/analytics/version.py` | `VersionMetrics`、`version_metrics`、`metrics_action`。 |
| 新增 | `src/training_kb/handlers/analytics.py` | `training-kb-analytics` 的 Lambda 入口 `handler`；只分派 action 與接線（00A D-56；`handlers/` 套件由 Phase 30 建立）。 |
| 修改 | `infra/training_kb_stack.py` | 把 `training-kb-analytics` 這支 Lambda 接進 stack（檔案 owner 是 Phase 41；00A D-58）。**現況核對 2026-09-14：這支檔還不存在，Phase 41 才會建**；沿用 Phase 41 的相依 layer／bundling（COMMON R2），不自己再做一套。 |
| 測試 | `tests/unit/test_reopen_metrics.py` | 窗口端點、去重、先後、cluster、零分母、`VersionMetrics` 與 handler 分派。 |
| 測試 | `tests/unit/infra/test_analytics_stack.py` | `Template` 斷言 Lambda 名稱、handler 路徑與沒有 Function URL（`tests/unit/infra/` 由 Phase 41 首建）。 |
| 測試 | `tests/unit/test_rule_and_call_metrics.py` | 規則狀態計數、套用次數與 attempt 計數。 |

## 5. 固定介面

### Consumes

```text
TutorialView(tutorial_version, user, ts) / Ticket(id, source, text, author, ts,
    project_id, cluster_id, feature_ids, embedding) / Tutorial(slug, current_version,
    topic, feature_ids, status, successor, cluster_id) / TutorialVersion(version_id,
    slug, supersedes, reason, rules_applied, s3_key, published_at) / AuthoringRule(
    rule_id, rule, applies_when, evidence, status, applied_to, derived_from) /
    Feedback(id, tutorial_version, rating, category, comment, user, ts)          # P04
RuleStatus：Phase 03 的 StrEnum（CANDIDATE／ACTIVE／RETIRED，值為小寫字串）        # P03
Repository.get_tutorial(slug) -> Tutorial | None                                 # P06
Repository.get_version(version_id) -> TutorialVersion | None                     # P06
Repository.list_views_of_version(version_id: str) -> list[TutorialView]          # P08
Repository.list_tickets(project_id: str) -> list[Ticket]                         # P08
Repository.list_rules(status: RuleStatus | None = None) -> list[AuthoringRule]   # P08
Repository.list_feedback_of_version(version_id: str) -> list[Feedback]           # P08
CallTrace.count(*, operation_id: str | None = None) -> int                       # P15
average_rating / negative_feedback_ids / format_average                          # P53
approved_categories(repository) -> frozenset[str]                                # P43
load_settings(env=None) -> Settings（只用 table_name／content_bucket／project_id） # P02
PermanentError                                                                   # P02
```

模組路徑（現況核對 2026-09-14，實際 import 位置）：`from training_kb.writing import CallTrace`（`writing/__init__.py` 有 re-export）、`from training_kb.models import AuthoringRule, Feedback, RuleStatus, Ticket, Tutorial, TutorialVersion, TutorialView`、`from training_kb.config import load_settings`、`from training_kb.errors import PermanentError`、`from training_kb.repository import Repository`、`from training_kb.analytics.ratings import average_rating, format_average, negative_feedback_ids`（Phase 53 的四個名稱走**子模組路徑**，`analytics/__init__.py` 不 re-export）。

### Produces

```python
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime

def reopen_window(published_at: datetime, days: int = 14) -> tuple[datetime, datetime]: ...

@dataclass(frozen=True)
class ReopenStats:
    count: int; reopen_users: int; viewers: int; rate: float | None

def reopen_stats(views: Sequence["TutorialView"], tickets: Sequence["Ticket"], *,
                 cluster_id: str, published_at: datetime) -> ReopenStats: ...
def rule_counts(rules: Iterable["AuthoringRule"]) -> dict[str, int]: ...
def applied_count(versions: Iterable["TutorialVersion"], rule_id: str) -> int: ...
def bedrock_call_count(trace: "CallTrace", *, operation_id: str | None = None) -> int: ...

@dataclass(frozen=True)
class VersionMetrics:
    version_id: str; published_at: datetime | None; average: float | None
    sample_size: int; negative_ids: frozenset[str]; reopen: ReopenStats

def version_metrics(version_id: str, *, repository: "Repository",
                    approved: frozenset[str], project_id: str) -> VersionMetrics: ...
def metrics_action(event: dict, *, repository: "Repository",
                   approved: frozenset[str], project_id: str) -> dict: ...
def handler(event: dict, context: object) -> dict: ...   # training-kb-analytics 入口（D-56）
```

`ReopenStats` 四欄：`count` 是不同 Ticket ID 數、`reopen_users` 是分子（不同使用者）、`viewers` 是分母（不同瀏覽者）、`rate` 在 `viewers == 0` 時是 `None`。`VersionMetrics.sample_size` 是**有評分**的筆數，與 Phase 44 的 `n` 同一套分母（00A D-44）。`rule_counts` 固定回 `candidate`、`active`、`retired` 三個鍵，沒有資料的補 0，避免畫面把缺鍵讀成「沒有這種狀態」。`metrics_action` 與 Phase 55 的 `validate_rules_action` 形狀一致：回 `{"action": ..., "results": [...]}`。

## 6. 設計細節

```text
published_at = p                     p + 14 天
      |                                  |
      v                                  v
      [==================================)      <- O4 本計畫選擇
      ^ 包含 p 本身                       ^ 不包含這一刻

呼叫端先用 list_views_of_version(version_id) 篩出本版的 View 才交進來
      |
每一筆 View                            每一筆 Ticket
  | view.ts 落在窗口內？ 否 -> 丟          | cluster_id 相同？          否 -> 丟
  v                                      | ticket.ts 落在窗口內？     否 -> 丟
viewers = {user} 的大小                   | author 在 viewers 內？     否 -> 丟
（同人取最早一筆 ts 供比較）               | 最早 view.ts < ticket.ts？ 否 -> 丟
                                         v
                                        count = {ticket.id} 大小
                                        reopen_users = {author} 大小
                                        rate = reopen_users / viewers；0 分母 -> None
```

**O4 待核定。** 設計 §18 明寫「ERM 明留窗口端點與時間編碼未定義；本文件建議 UTC、窗口 `[p, p + 14 天)`」。本計畫照建議實作，並把 `timedelta(days=14)` 收斂到 `reopen_window` 一處；端點案例（`ticket.ts == p`、`ticket.ts == p + 14 天`）各有一個測試，核定若改成右含只需改這一處與那兩個測試。核定前只能說「依 §12.1 建議實作且可被測試重現」。

`view.ts < ticket.ts` 是**嚴格**小於：同一刻無法證明先後，不計分子。同一人多筆瀏覽取**最早**一筆比較，因為只要曾經先看過就算；這仍然只給該 user 一次分子與一次分母。`count` 與 `reopen_users` 分開存在，是因為設計 §12.1 明寫「筆數可多於重開票使用者數，不能直接當比例」——§11.3 的 7 與 2 是**筆數**，70% 與 20% 是本配方補上分母後才成立的比率。

`applied_count` 以 `VERSION.rules_applied` 為唯一權威（D17），對含該 `rule_id` 的版本取 `version_id` 去重計數；`RULE.applied_to` 與 `APPLIED_TO` 邊是可重建投影，不一致代表投影過期，應交 [Phase 28](./28-Phase28-引用Backfill與規則投影重建.md) 的 `rebuild_rule_projection` 重建，**不是**改指標遷就投影（Phase 58 的隔離預覽不產生 `VERSION` item，不會被算進來）。`bedrock_call_count` 直接轉呼 `CallTrace.count`，不自建第二份計數器；Phase 15 已保證每次真實 request（含例外）恰有一筆 trace。`handler` 的分派寫在接線之前：未知 `action` 必須在建立 boto3 資源前就丟 `PermanentError`，單元測試才能不碰 AWS 驗證這條路徑；Phase 55 只在 `raise` 前插入 `validate_rules` 分支。

## 7. TDD Tasks

實作區塊只列新增的程式碼；檔頭 import 依區塊內用到的名稱補齊，本 Phase 會用到的是 `from collections.abc import Iterable, Sequence`、`from dataclasses import asdict, dataclass`、`from datetime import UTC, datetime, timedelta`，以及 `training_kb` 內第 5 節列出的那些名稱。

### Task 1：O4 窗口與端點

- [ ] **Step 1：建立失敗測試**

```python
from datetime import UTC, datetime, timedelta

import pytest

from training_kb.analytics.reopen import reopen_window

P1 = datetime(2026, 8, 1, tzinfo=UTC)


def test_reopen_window_is_left_closed_right_open_o4_pending():
    start, end = reopen_window(P1)
    assert (start, end) == (P1, datetime(2026, 8, 15, tzinfo=UTC))
    assert start <= P1 < end                    # 左端包含 p 本身
    assert end - start == timedelta(days=14)
    assert reopen_window(P1, days=7)[1] == datetime(2026, 8, 8, tzinfo=UTC)


def test_reopen_window_rejects_naive_datetime():
    with pytest.raises(ValueError):
        reopen_window(datetime(2026, 8, 1))
```

窗口只回一組端點，不自己判斷成員資格；右端不含由 Task 2 的 `ticket.ts == p + 14 天` 案例斷言。

- [ ] **Step 2：執行並確認紅燈**

```bash
uv run pytest tests/unit/test_reopen_metrics.py -q
```

預期：FAIL，訊號包含 `cannot import name 'reopen_window'`。

- [ ] **Step 3：建立最小實作**

```python
def reopen_window(published_at: datetime, days: int = 14) -> tuple[datetime, datetime]:
    """O4 待核定：本計畫依設計 §12.1 建議採 UTC 的 [p, p + days)。"""
    if published_at.tzinfo is None or published_at.utcoffset() is None:
        raise ValueError("published_at 必須是 timezone-aware 的 UTC 時間")
    start = published_at.astimezone(UTC)
    return start, start + timedelta(days=days)
```

- [ ] **Step 4：跑完整檔案確認綠燈**

```bash
uv run pytest tests/unit/test_reopen_metrics.py -q
```

預期：兩個測試 PASS；另確認全 repo 只有此函式出現 `timedelta(days=14)`。

- [ ] **Step 5：提交**

```bash
git add src/training_kb/analytics/reopen.py tests/unit/test_reopen_metrics.py
git commit -m "feat(analytics): 依 O4 建議定義重開票窗口"
```

### Task 2：分子分母去重與六種邊界

- [ ] **Step 1：建立設計 §11.3 的重算測試**

```python
from training_kb.analytics.reopen import ReopenStats, reopen_stats
from training_kb.models import Ticket, TutorialView

V1 = "prepare-meeting@v1"
VIEW_TS = datetime(2026, 8, 2, 9, tzinfo=UTC)
TICKET_TS = datetime(2026, 8, 3, 10, tzinfo=UTC)


def view(user, ts=VIEW_TS, version=V1):
    return TutorialView(tutorial_version=version, user=user, ts=ts)


def ticket(tid, author, ts=TICKET_TS, cluster="c12"):
    return Ticket(id=tid, source="email", author=author, ts=ts, project_id="demo",
                  text="看過準備會議教學後，仍找不到第三步的按鈕",
                  cluster_id=cluster, feature_ids=[], embedding=None)


def test_reopen_stats_reproduces_design_v1_seven_over_ten():
    views = [view(f"u_{n:02d}") for n in range(1, 11)]
    tickets = [ticket(f"t_200{n}", f"u_{n:02d}") for n in range(1, 8)]
    stats = reopen_stats(views, tickets, cluster_id="c12", published_at=P1)
    assert stats == ReopenStats(count=7, reopen_users=7, viewers=10, rate=0.7)
```

- [ ] **Step 2：確認紅燈後補六個邊界測試**

```bash
uv run pytest tests/unit/test_reopen_metrics.py -q
```

預期：FAIL，訊號包含 `cannot import name 'reopen_stats'`。接著在同一個檔案為下表六個案例各寫一個獨立測試函式，全部沿用上面的 `view`／`ticket` helper：

| 案例 | 資料 | 預期 |
|---|---|---|
| 先開票後瀏覽 | `ticket.ts` 早於同人的 `view.ts` | 不計分子，`count` 不增加。 |
| 同人重複瀏覽 | `u_01` 兩筆 View | `viewers` 仍為 10。 |
| 同人多次開票 | `u_01` 兩張同群工單 | `count` 加 1，`reopen_users` 不變。 |
| 不同 cluster | `ticket.cluster_id = "c99"` | 完全不計。 |
| 窗外時間 | `ticket.ts == p + 14 天`；另一筆 `ticket.ts == p` | 前者不計（右不含）；後者需先有更早 view 才計。 |
| 零瀏覽者 | `views = []`、`tickets` 非空 | `viewers == 0`、`rate is None`。 |

- [ ] **Step 3：建立最小實作**

`ReopenStats` 的 dataclass 定義逐字照第 5 節 Produces（`frozen=True`、四個欄位），這裡只列新增的函式。

```python
def reopen_stats(views: Sequence[TutorialView], tickets: Sequence[Ticket], *,
                 cluster_id: str, published_at: datetime) -> ReopenStats:
    start, end = reopen_window(published_at)
    first_view: dict[str, datetime] = {}
    for item in views:
        if start <= item.ts < end:
            seen = first_view.get(item.user)
            if seen is None or item.ts < seen:
                first_view[item.user] = item.ts
    hits = [row for row in tickets
            if row.cluster_id == cluster_id and start <= row.ts < end
            and row.author in first_view and first_view[row.author] < row.ts]
    viewers = len(first_view)
    users = {row.author for row in hits}
    rate = len(users) / viewers if viewers else None
    return ReopenStats(len({row.id for row in hits}), len(users), viewers, rate)
```

- [ ] **Step 4：加上 v2 案例並跑完整檔案**

```python
P2 = datetime(2026, 8, 20, tzinfo=UTC)


def test_reopen_stats_reproduces_design_v2_two_over_ten():
    views = [view(f"u_{n:02d}", datetime(2026, 8, 21, 9, tzinfo=UTC), "prepare-meeting@v2")
             for n in range(1, 11)]
    tickets = [ticket("t_2101", "u_01", datetime(2026, 8, 22, 10, tzinfo=UTC)),
               ticket("t_2102", "u_02", datetime(2026, 8, 22, 10, tzinfo=UTC))]
    stats = reopen_stats(views, tickets, cluster_id="c12", published_at=P2)
    assert (stats.count, stats.reopen_users, stats.viewers) == (2, 2, 10)
    assert stats.rate == 0.2
```

```bash
uv run pytest tests/unit/test_reopen_metrics.py -q
```

預期：全部 PASS；`rate` 沒有任何路徑回 `0.0` 代替 `None`。

- [ ] **Step 5：提交**

```bash
git add src/training_kb/analytics/reopen.py tests/unit/test_reopen_metrics.py
git commit -m "feat(analytics): 重算同題重開票筆數與比率"
```

### Task 3：規則狀態計數、套用次數與呼叫數

- [ ] **Step 1：建立失敗測試**

`record` 的七個鍵就是 Phase 15 的 `TRACE_FIELDS`，一個不多一個不少；四筆分別是 embedding、同一個 node 的兩次 generation attempt（先暫時性失敗再成功）與 Rote 的 `tool_use`。

```python
from training_kb.analytics.rules_metrics import applied_count, bedrock_call_count, rule_counts
from training_kb.models import AuthoringRule, TutorialVersion
from training_kb.writing import CallTrace

EVIDENCE = ["f_12", "f_15", "f_19", "f_23", "f_27"]


def rule(rule_id, status):
    return AuthoringRule(rule_id=rule_id, rule="點 UI 時寫出頁面與按鈕位置",
                         applies_when="click_ui", status=status, evidence=EVIDENCE,
                         applied_to=[], derived_from="prepare-meeting@v1")


def version(version_id, rules_applied, published_at=None):
    slug = version_id.partition("@")[0]
    return TutorialVersion(version_id=version_id, slug=slug, supersedes=None,
                           reason="gap:c12", rules_applied=rules_applied,
                           s3_key=f"tutorials/{slug}/v1.md", published_at=published_at)


def record(node, kind, attempt, outcome):
    return {"operation_id": "op-1", "node": node, "model": "m", "attempt": attempt,
            "kind": kind, "started_at": "2026-09-01T00:00:00Z", "outcome": outcome}


def test_rule_counts_reports_all_three_statuses_with_zero_fill():
    rules = [rule("R-007", "active"), rule("R-011", "candidate"),
             rule("R-012", "retired"), rule("R-013", "candidate")]
    assert rule_counts(rules) == {"candidate": 2, "active": 1, "retired": 1}
    assert rule_counts([]) == {"candidate": 0, "active": 0, "retired": 0}


def test_applied_count_rebuilds_from_rules_applied_and_deduplicates():
    versions = [version("prepare-meeting@v2", ["R-007"]),
                version("share-summary@v1", ["R-007", "R-011"]),
                version("prepare-meeting@v3", ["R-007"]),
                version("notification-settings@v1", [])]
    assert applied_count(versions, "R-007") == 3
    assert applied_count(versions + versions, "R-007") == 3
    assert applied_count(versions, "R-099") == 0


def test_bedrock_call_count_counts_every_real_attempt():
    trace = CallTrace()
    trace.add(record("embed_ticket", "embedding", 1, "success"))
    trace.add(record("name_gap", "generation", 1, "transient_error"))
    trace.add(record("name_gap", "generation", 2, "success"))
    trace.add(record("rote_agent", "tool_use", 1, "success"))
    assert bedrock_call_count(trace) == 4
    assert bedrock_call_count(trace) == 4   # 重用已保存輸出不送 request，也不多一筆 trace
    assert bedrock_call_count(trace, operation_id="op-2") == 0
```

- [ ] **Step 2：執行並確認紅燈**

```bash
uv run pytest tests/unit/test_rule_and_call_metrics.py -q
```

預期：FAIL，訊號包含 `cannot import name 'rule_counts'`。

- [ ] **Step 3：建立最小實作**

```python
def rule_counts(rules: Iterable[AuthoringRule]) -> dict[str, int]:
    counts = {"candidate": 0, "active": 0, "retired": 0}
    for item in rules:
        counts[str(item.status)] += 1
    return counts


def applied_count(versions: Iterable[TutorialVersion], rule_id: str) -> int:
    return len({item.version_id for item in versions if rule_id in item.rules_applied})


def bedrock_call_count(trace: CallTrace, *, operation_id: str | None = None) -> int:
    return trace.count(operation_id=operation_id)
```

- [ ] **Step 4：跑完整檔案確認綠燈**

```bash
uv run pytest tests/unit/test_rule_and_call_metrics.py -q
```

預期：三個測試皆 PASS；`rule_counts` 的三個鍵在空輸入時仍然存在。

- [ ] **Step 5：提交**

```bash
git add src/training_kb/analytics/rules_metrics.py tests/unit/test_rule_and_call_metrics.py
git commit -m "feat(analytics): 計算規則狀態、套用次數與真實呼叫數"
```

### Task 4：組成 `VersionMetrics`、建立 analytics Lambda 入口並接進 CDK

- [ ] **Step 1：建立失敗測試**

寫在 `tests/unit/test_reopen_metrics.py`，沿用 Task 2 的 `view`／`ticket`／`P1`／`V1`。`FakeRepo` 只回設計 §11.2／§11.3 的 A v1 配方，沒有任何 AWS 相依；兩個建構參數讓「未發布」與「缺 `cluster_id`」各自成為一個案例。

```python
from dataclasses import dataclass

from training_kb.analytics.version import metrics_action, version_metrics
from training_kb.errors import PermanentError
from training_kb.handlers.analytics import handler
from training_kb.models import Feedback, Tutorial, TutorialVersion

APPROVED = frozenset({"找不到按鈕", "缺少資訊"})
RATINGS = [("f_12", 2), ("f_15", 2), ("f_19", 3), ("f_23", 3),
           ("f_27", 3), ("f_31", 3), ("f_34", 3), ("f_40", 4)]


@dataclass
class FakeRepo:
    published_at: datetime | None = P1
    cluster_id: str | None = "c12"

    def get_version(self, version_id):
        return TutorialVersion(version_id=version_id, slug="prepare-meeting", supersedes=None,
                               reason="gap:c12", rules_applied=[], s3_key="tutorials/x/v1.md",
                               published_at=self.published_at)

    def get_tutorial(self, slug):
        return Tutorial(slug=slug, current_version=V1, topic="準備會議", feature_ids=["Prepare"],
                        status="active", successor=None, cluster_id=self.cluster_id)

    def list_feedback_of_version(self, version_id):
        return [Feedback(id=fid, tutorial_version=V1, rating=r, category="找不到按鈕",
                         comment=None, user=f"u_{fid}", ts=None) for fid, r in RATINGS]

    def list_views_of_version(self, version_id):
        return [view(f"u_{n:02d}") for n in range(1, 11)]

    def list_tickets(self, project_id):
        return [ticket(f"t_200{n}", f"u_{n:02d}") for n in range(1, 8)]


def test_metrics_action_recomputes_design_11_2_and_11_3():
    row = metrics_action({"action": "metrics", "version_ids": [V1]}, repository=FakeRepo(),
                         approved=APPROVED, project_id="demo")["results"][0]
    assert (row["average"], row["sample_size"], row["negative"]) == (2.875, 8, 8)
    assert row["display_average"] == "2.9"
    assert row["reopen"] == {"count": 7, "reopen_users": 7, "viewers": 10, "rate": 0.7}


def test_version_metrics_without_publish_or_cluster_has_no_rate():
    for repo in (FakeRepo(published_at=None), FakeRepo(cluster_id=None)):
        metrics = version_metrics(V1, repository=repo, approved=APPROVED, project_id="demo")
        assert (metrics.reopen.viewers, metrics.reopen.rate) == (0, None)


def test_handler_rejects_unknown_action_before_touching_aws():
    with pytest.raises(PermanentError):
        handler({"action": "validate_rules"}, None)
```

另外新增 `tests/unit/infra/test_analytics_stack.py`，用 CDK 的 `Template` 斷言這支 Lambda 真的被接進 stack（`Template.from_stack` 只做本機合成，不連 AWS）：

```python
# tests/unit/infra/test_analytics_stack.py
import aws_cdk as cdk
from aws_cdk.assertions import Template

from infra.training_kb_stack import TrainingKbStack


def test_stack_wires_the_analytics_lambda():
    template = Template.from_stack(TrainingKbStack(cdk.App(), "TrainingKbApp"))
    functions = template.find_resources("AWS::Lambda::Function").values()
    assert {f["Properties"]["FunctionName"]: f["Properties"]["Handler"] for f in functions} == {
        "training-kb-pipeline-task": "training_kb.pipelines.common.pipeline_task_handler",
        "training-kb-webhook": "training_kb.handlers.github_webhook.handler",
        "training-kb-import": "training_kb.handlers.import_.handler",
        "training-kb-analytics": "training_kb.handlers.analytics.handler"}   # 00A D-23、D-58
    template.resource_count_is("AWS::Lambda::Url", 1)      # 只有 webhook 有 Function URL
```

（現況核對 2026-09-14：這個**字典等號**同時要求 Phase 41 已建 `infra/training_kb_stack.py` 與 Phase 42 已加 `training-kb-import`。輪到本 Phase 時若 Phase 42 尚未落地，改成包含式斷言——`handlers["training-kb-analytics"] == "training_kb.handlers.analytics.handler"` 加上 `resource_count_is("AWS::Lambda::Url", 1)`——並在報告寫明降級原因；**不得**為了讓等號成立去刪別的 Phase 的資源或測試。）

- [ ] **Step 2：執行並確認紅燈**

```bash
uv run pytest tests/unit/test_reopen_metrics.py -q
```

預期：FAIL，訊號包含 `cannot import name 'version_metrics'`。

- [ ] **Step 3：建立 `version_metrics` 與 `metrics_action`**

`published_at is None`（未發布）或 `Tutorial.cluster_id is None` 時直接回零分母結果，不憑空造窗口。`VersionMetrics` 的 dataclass 定義逐字照第 5 節 Produces（`frozen=True`、六個欄位）。

```python
NO_REOPEN = ReopenStats(0, 0, 0, None)


def version_metrics(version_id: str, *, repository, approved: frozenset[str],
                    project_id: str) -> VersionMetrics:
    item = repository.get_version(version_id)
    if item is None:
        raise PermanentError(f"找不到版本 {version_id!r}")
    feedback = repository.list_feedback_of_version(version_id)
    rated = [row for row in feedback if row.rating is not None]
    tutorial = repository.get_tutorial(item.slug)
    cluster_id = tutorial.cluster_id if tutorial is not None else None
    reopen = NO_REOPEN
    if item.published_at is not None and cluster_id is not None:
        reopen = reopen_stats(repository.list_views_of_version(version_id),
                              repository.list_tickets(project_id),
                              cluster_id=cluster_id, published_at=item.published_at)
    return VersionMetrics(version_id, item.published_at, average_rating(feedback),
                          len(rated), negative_feedback_ids(feedback, approved), reopen)


def _row(item: VersionMetrics) -> dict:
    return {"version_id": item.version_id, "average": item.average,
            "display_average": format_average(item.average),
            "sample_size": item.sample_size, "negative": len(item.negative_ids),
            "reopen": asdict(item.reopen)}


def metrics_action(event: dict, *, repository, approved: frozenset[str],
                   project_id: str) -> dict:
    version_ids = [str(value) for value in event.get("version_ids") or ()]
    if not version_ids:
        raise PermanentError("metrics action 需要非空的 version_ids")
    return {"action": "metrics",
            "results": [_row(version_metrics(value, repository=repository, approved=approved,
                                             project_id=project_id)) for value in version_ids]}
```

- [ ] **Step 4：建立 Lambda 入口並跑綠燈**

`handler` 不 try／except：`PermanentError` 要原樣往外丟，呼叫端才看得到失敗原因。

```python
# src/training_kb/handlers/analytics.py
_WIRING: "tuple[Repository, frozenset[str], str] | None" = None


def _wiring() -> "tuple[Repository, frozenset[str], str]":
    # 現況核對 2026-09-14：照 `src/training_kb/ingress.py::_wiring/_build_wiring` 的既有範式——
    # boto3 resource 一律帶 `region_name=settings.aws_region`（不靠 shell 預設；全案固定 us-east-1），
    # 且 `load_settings()` 不帶參數就會讀 `os.environ`（不必自己傳 `os.environ`）。
    global _WIRING
    if _WIRING is None:
        settings = load_settings()
        dynamodb = boto3.resource("dynamodb", region_name=settings.aws_region)
        s3 = boto3.resource("s3", region_name=settings.aws_region)
        repository = Repository(dynamodb.Table(settings.table_name),
                                s3.Bucket(settings.content_bucket))
        _WIRING = (repository, approved_categories(repository), settings.project_id)
    return _WIRING


def _reset_wiring() -> None:
    """丟掉模組層快取，給測試用（與 `ingress._reset_wiring` 同一個理由）。正式程式不呼叫。"""
    global _WIRING
    _WIRING = None


def handler(event: dict, context: object) -> dict:
    action = str(event.get("action"))
    if action == "metrics":
        repository, approved, project_id = _wiring()
        return metrics_action(event, repository=repository,
                              approved=approved, project_id=project_id)
    raise PermanentError(f"未知的 analytics action：{action!r}")
```

再把這支函式接進 Phase 41 建好的 stack（同一個 `table`／`bucket`／`base_env`，不新建第二個 stack、不開 Function URL、不給 `states:StartExecution`——它不啟動任何 pipeline）：

```python
# infra/training_kb_stack.py（class TrainingKbStack；檔案 owner 是 Phase 41，本 Phase 只追加）
# ---- Phase 54 ----（R3：既有檔只用 Edit，新增資源放自己的區段，不重排別人的程式）
analytics_fn = lambda_.Function(
    self, "AnalyticsFunction", function_name="training-kb-analytics",
    runtime=lambda_.Runtime.PYTHON_3_12,
    code=...,        # 現況核對 2026-09-14：**沿用 Phase 41 建立的相依 layer／bundling**
                     # （COMMON R2：`Code.from_asset("src")` 不含 pydantic／jsonschema），
                     # 與 task_fn／webhook_fn／import_fn 同一支，不在本 Phase 另做一套。
    handler="training_kb.handlers.analytics.handler",
    timeout=Duration.seconds(60), environment=base_env)
table.grant_read_write_data(analytics_fn)   # 讀指標來源；Phase 55 的 apply_rule_status 要寫 RULE.status
bucket.grant_read_write(analytics_fn)       # Phase 55 要寫 operations/rules/validated_at.json 與證據檔
```

寫入權限現在就給足，是因為 Phase 55 依裁決**不再動 CDK**（D-58）；本 Phase 自己只讀不寫，這個差距在上面那行註解寫清楚即可，不要為了「最小」而讓 Phase 55 又回來改一次 stack。維護者用 boto3 `invoke` 呼叫它，所以不開 Function URL。**同時要更新 [Phase 48](./48-Phase48-Feedback-Review排程流程.md) 那個列舉 Lambda 名稱集合的 `Template` 斷言**：本 Phase 之後 stack 有四支具名 Lambda，少補一個名字會讓 Phase 48 的測試轉紅。（現況核對 2026-09-14：確切位置是 `tests/unit/test_feedback_review_flow.py::test_stack_has_review_machine_and_exactly_one_daily_schedule` 裡的 `names == {"training-kb-pipeline-task", "training-kb-webhook", "training-kb-import"}`。這是 COMMON R3.6「不修改別的 Phase 的測試檔」的**有文件依據的例外**——Phase 48 §7 已逐字預告本 Phase 要補；**只加一個名字、不動該檔其他任何一行**，並在報告寫明。）

```bash
uv run pytest tests/unit/test_reopen_metrics.py tests/unit/test_rule_and_call_metrics.py \
             tests/unit/infra/test_analytics_stack.py -q
# 現況核對 2026-09-14：本機互動 shell 把 node 定成會拒絕的 function（`Security: node blocked`），
# 所以 cdk 一律走 `command npx aws-cdk@2`，並明寫 region（COMMON.md §1）。
AWS_REGION=us-east-1 AWS_DEFAULT_REGION=us-east-1 command npx aws-cdk@2 synth --quiet
```

預期：全部 PASS，且 `handler({"action": "validate_rules"}, None)` 在 Phase 55 完成前一律 `PermanentError`；`cdk synth` 產出的 template 恰有四支具名 Lambda、沒有新增 state machine。`cdk` 是 Node.js 套件，指令**不加** `uv run`（00A §3.1、D-22）。CDK 環境尚未建立時先完成 Phase 01／09／41，不要把「目前跑不了」寫成已通過。

- [ ] **Step 5：提交**

```bash
# 現況核對 2026-09-14：不要 `git add src/training_kb/analytics/`（那會把 Phase 53 的
# ratings.py 與 Phase 40 的 status_writer.py 一起帶進來）；逐檔列出自己的路徑（COMMON R3.3）。
git add src/training_kb/analytics/reopen.py src/training_kb/analytics/rules_metrics.py \
        src/training_kb/analytics/version.py src/training_kb/handlers/analytics.py \
        infra/training_kb_stack.py tests/unit/test_reopen_metrics.py \
        tests/unit/infra/test_analytics_stack.py tests/unit/test_feedback_review_flow.py
git commit -m "feat(analytics): 組成單版完整指標並建立 analytics 入口"
```

## 8. 驗收矩陣

| 路徑 | 輸入 | 預期資料結果 |
|---|---|---|
| Happy | 設計 §11.3 的 A v1／A v2 配方 | `(7, 7, 10, 0.7)` 與 `(2, 2, 10, 0.2)`。 |
| Boundary | `ticket.ts == p + 14 天`；`ticket.ts == view.ts` | 兩者都不計入（右端不含、需嚴格先後）。 |
| Boundary | 同人兩筆 View、同人兩張同群票 | `viewers` 不變、`reopen_users` 不變、`count` 加 1。 |
| Boundary | 零 View、有票 | `viewers=0`、`rate=None`，畫面顯示 N/A。 |
| Boundary | 未發布版本、缺 `Tutorial.cluster_id` | 兩者都回 `ReopenStats(0, 0, 0, None)`，不猜測窗口也不拋例外。 |
| Failure | 用 Feedback 當分母 | 不允許：`reopen_stats` 的簽名不接受 Feedback。 |
| Failure | `applied_to` 長度與 `applied_count` 不同 | 判定為投影過期，交 Phase 28 重建，不改指標。 |
| Failure | `handler` 收到未知 `action` | 丟 `PermanentError`，且沒有建立任何 boto3 資源。 |
| Infra | `Template.from_stack` | 四支具名 Lambda 齊全、`training-kb-analytics` 的 handler 是 `training_kb.handlers.analytics.handler`、只有一個 `AWS::Lambda::Url`。 |
| Happy | 4 個 attempt 的 trace | `bedrock_call_count == 4`，輸出重用後仍是 4。 |

人工驗收：把 `reopen_stats` 命中的 Ticket ID 逐張列出，回查 `TICKET#<id>` 的 `author`、`ts`、`cluster_id`，並在 `TUTORIAL_VIEW` 找到同一 `user` 更早的瀏覽紀錄。只看 `rate == 0.7` 不算完成。

## 9. 常見錯誤與停止條件

| 症狀 | 原因 | 修正／停止 |
|---|---|---|
| 零瀏覽者顯示 0% | 分母為 0 時回 `0.0` | 回 `None` 並顯示 N/A；否則 Phase 55 會誤判「rate 嚴格下降」。 |
| rate 大於 1 | 分子用票數而不是人數 | 分子固定 `reopen_users`；`count` 只當筆數顯示。 |
| 用 Feedback 當分母 | 誤以為留過回饋就等於看過 | 分母只能是 `TUTORIAL_VIEW`；設計 §12.1 明文禁止代用。 |
| 先開票後瀏覽也被算進去 | 只比對 user 與 cluster，沒比時間 | 加上 `view.ts < ticket.ts` 嚴格比較。 |
| recurring 窗口與重開票窗口混用 | 兩個十四天定義長得像 | recurring 是「UTC 當日加前十三日」，不可互換；停止並分開實作。 |
| 呼叫數少算 retry 或 Map | 自建計數器只記成功 | 一律轉呼 `CallTrace.count`，不維護第二份來源。 |
| `CallTrace.add` 丟 `PermanentError` | 測試紀錄少了 `TRACE_FIELDS` 的某個鍵 | 七個鍵一個不多一個不少；`kind` 只能是 `embedding`／`generation`／`tool_use`。 |
| 單元測試需要 AWS 憑證 | `handler` 一進來就接線 | 未知 `action` 先丟 `PermanentError`，`_wiring()` 只在需要時才呼叫。 |
| 部署後找不到 `training-kb-analytics` | 只寫了 handler 沒接 CDK | 依 D-58 在 `infra/training_kb_stack.py` 補這支 Lambda，並用 `Template` 斷言釘住名稱與 handler 路徑。 |
| Phase 55 又回來改 stack | 本 Phase 只給唯讀權限 | 現在就給 `grant_read_write_data`／`grant_read_write`，Phase 55 才不必再動 CDK。 |
| Phase 48 的 Lambda 名稱集合斷言轉紅 | 新增第四支 Lambda 後沒同步那個測試 | 一併把 `training-kb-analytics` 加進 Phase 48 的集合斷言。 |
| 說「窗口已定案」 | 把建議值當規格 | O4 未核定；只能說本計畫選擇，並保留兩個端點測試。 |

## 10. 來源與 Rule 對照

Rule 原文逐字取自 `.feature` 原檔；primary／相關的歸屬依 [00B 第 2.11、2.3、3.2 節](00B-需求覆蓋對照.md)。

- [檢視學習指標.feature](../../spec/features/檢視學習指標.feature)（00B 縮寫 `MET`）
  - **primary** Rule 3「同題重開票率計算看過教學的使用者在版本發布後 14 天內同 cluster 再開票的比例」→ Task 2 的 `test_reopen_stats_reproduces_design_v1_seven_over_ten` 與六個邊界測試直接斷言窗口、cluster 與先後。
  - **primary** Rule 4「同題重開票率的分母取自教學瀏覽事件」→ `reopen_stats` 簽名只接受 `views`；零 View 案例斷言 `rate is None`。
  - **primary** Rule 5「看過教學又開票的同一人比對穩定使用者 ID」→ 測試以 `view.user == ticket.author` 配對，不比對顯示名稱。
  - **primary** Rule 7「已學規則數依 RULE item 的 status 分別計數」→ Task 3 的 `test_rule_counts_reports_all_three_statuses_with_zero_fill`。
  - **primary** Rule 8「規則套用次數等於 applied_to 清單長度」→ Task 3 的 `test_applied_count_rebuilds_from_rules_applied_and_deduplicates`；長度由 `rules_applied` 重建去重（D17），投影不一致交 Phase 28。
  - **primary** Rule 9「每次執行的 Bedrock 呼叫數包含 Step Functions 內的呼叫節點與 Rote 層呼叫」→ Task 3 的 `test_bedrock_call_count_counts_every_real_attempt`，四筆 attempt 含 retry、Rote 與 embedding。
  - Rule 11「Demo 對同題重開票率標明 proxy 與精確定義」→ **相關（primary 在 [Phase 58](./58-Phase58-Demo控制台與規則開關預覽.md)）**：本 Phase 只負責讓 `ReopenStats` 同時輸出四個欄位，畫面上的 proxy 說明由 Phase 58 斷言。
- [執行教學流程.feature](../../spec/features/執行教學流程.feature)（00B 縮寫 `RUN`）
  - Rule 1「缺少原始 Example 時可用明示合成且經確認的驗收資料」→ **相關（primary 在 [Phase 56](./56-Phase56-O7核定Demo種子資料.md)）**：本 Phase 的 View 與 Ticket 都是合成配方，測試與文件均標明合成、不描述成實測；「經確認」需要的維護者核定紀錄屬 Phase 56。
- 設計 §11.3（A v1／A v2 完整瀏覽與開票資料、7／2、7/10、2/10）、§12.1 與 §18 O4（窗口、去重、零分母 N/A、多組 rate 不自行彙總）、§12.3（呼叫數以逐次 trace 核對）。
- 設計 §19 決策：D17（`rules_applied` 為套用關係唯一權威）、D23（跨來源共用穩定 user ID）、D24（新增瀏覽事件作指標來源）、D29（以首版 `gap:<cluster_id>` 作固定同題對應）、F41（分子只計在瀏覽之後且窗口結束前同群開票的使用者）、F42（沒有可識別瀏覽者時顯示 N/A 與樣本不足，不把零分母當成改善或惡化）、F45（計算每次實際送出的呼叫嘗試，含重試、每個 Map item 與 Rote 呼叫）、F46（Demo 指標由完整 seeded 資料實時計算，7、2 是必須能重現的目標）。
- 00A 裁決：D-56（`handlers/analytics.py::handler` 由本 Phase 產出並處理 `action: "metrics"`，Phase 55 再加 `validate_rules`）、D-58（`training-kb-analytics` 的 CDK 接線由本 Phase 完成，Phase 55 不再動 CDK）、D-23（四支具名 Lambda）、D-44（`sample_size` 與 Phase 44 的 `n` 同一套分母）。
- [Amazon Bedrock InvokeModel API 參考](https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_InvokeModel.html)：一次 request 即一個 attempt，是呼叫數定義的依據。
- [DynamoDB 分頁](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/Query.Pagination.html)：`list_views_of_version`、`list_tickets` 必須讀完所有分頁（含空頁）才交給本 Phase，否則分母會被低估。

## 11. 完成清單

- [ ] `reopen_window` 是全 repo 唯一定義十四天窗口的地方，且標明 O4 待核定。
- [ ] 窗口左右端點各有測試；`ticket.ts == p + 14 天` 不計入。
- [ ] 分子、分母各自以 user 去重，`count` 以 Ticket ID 去重，三者分開輸出。
- [ ] 先開票後瀏覽、重複瀏覽、多次開票、不同 cluster、窗外時間各有獨立測試。
- [ ] 零分母回 `rate=None`，沒有任何路徑產生 0%；分母不接受 Feedback。
- [ ] `applied_count` 由 `rules_applied` 重建去重，`bedrock_call_count` 轉呼 `CallTrace.count`。
- [ ] `version_metrics` 對未發布或缺 `cluster_id` 的版本回零分母結果，不猜測時間。
- [ ] `handlers/analytics.py::handler` 已建立、只認得 `action: "metrics"`，未知 action 在接線前就丟 `PermanentError`（D-56）。
- [ ] `infra/training_kb_stack.py` 已加入 `training-kb-analytics`（handler `training_kb.handlers.analytics.handler`、無 Function URL、無 `states:StartExecution`），並有 `Template` 斷言；權限已涵蓋 Phase 55 的寫入（D-58）。
- [ ] Phase 48 的 Lambda 名稱集合斷言（`tests/unit/test_feedback_review_flow.py`）已補上 `training-kb-analytics`，且只動那一行。
- [ ] CDK 沿用 Phase 41 的相依 layer／bundling（COMMON R2），沒有另做一套；`cdk synth` 以 `command npx aws-cdk@2` 實際跑過。
- [ ] 文件與測試都沒有把 7／2 當成百分比，也沒有宣稱 O4 已核定。
