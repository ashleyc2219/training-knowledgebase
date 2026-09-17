# Phase 18：Feedback Review 候選規則與每日排程

| 項目 | 內容 |
|---|---|
| 上一階段 | Phase 17：Feedback Review 弱教學判定與 REFINE（`17-Phase17-Feedback-Review-弱教學與REFINE.md`） |
| 下一階段 | Phase 19：Analytics 學習指標（`19-Phase19-Analytics-學習指標.md`） |
| 對應設計文件章節 | §7.5、§7.6、§9.3、§14.2、§14.3、§17.1（`docs/design/training-kb.md`） |
| 對應交付切片 | S6（設計文件第 16 節） |
| 預估時間 | 約 6 小時 |
| 做完會得到 | 同版同類 5 筆回饋能提出候選寫作規則，而且整條 Feedback Review 每天 00:30 UTC 自己在 AWS 上跑 |

---

## 1. 這階段做完會得到什麼

Phase 17 做完了「挑弱教學、只改命中步驟」。這一階段補上另一半，並讓它真的跑起來：

1. **候選規則**：掃描同一個版本、同一個核定問題類別的回饋。只要滿五筆，就請模型歸納出一條寫作要求，存成 `status = candidate` 的 `AUTHORING_RULE`。這條路**不需要**先達到弱教學門檻（F26），也不會讓規則馬上被一般寫作採用（F27）。
2. **Step Functions 流程定義**：`infra/asl/feedback-review.asl.json`，用 Map 節點對每一篇教學跑一次，全部跑完才集中發布。
3. **每日排程**：EventBridge Scheduler 每天 00:30 UTC 啟動這條流程，輸入是 `{"policy": "formal"}`。
4. **Demo 手動觸發**：同一條流程、同一段程式，只是輸入換成 `{"policy": "demo"}`，正式門檻完全不動。
5. **本機執行器 `run_review`**：跟 ASL 同樣順序的 Python 函式，給測試與 Phase 23 的 Demo 控制台用。

做完之後，設計文件第 16 節切片 S6 的檢查項目「Demo 八筆走隔離門檻；REFINE 只改有效步驟；candidate 不自動進一般寫作」就可以完整驗收。

---

## 2. 它在整張地圖的位置

```text
基礎層          01 骨架 -> 02 模型與鍵 -> 03 Repository(本機) -> 04 AWS 基礎建設
                                                                      |
AI 與內容層     05 Writing(Bedrock) -> 06 規則注入 -> 07 建立版本 -> 08 發布與退役 -> 09 圖譜查詢
                                                                                        |
接入層          10 Ingress 驗簽 -> 11 Rote 判定 -> 12 Rote Agent -------------------------+
                                                                                        |
流程層          13 Ticket Analysis -> 14 Step Functions 上線 -> 15 Feedback/View 匯入 -> 16 Release Update
                                                                                        |
學習層          17 Review:REFINE -> 18 Review:候選規則+排程 -> 19 Analytics 指標 -> 20 規則驗證
                                    ^^^^^^^^^^^^^^^^^^^^^^^
                                          你在這裡
                                                                                        |
展示與驗收層    21 Demo 種子資料 -> 22 靜態教學站 -> 23 Demo 控制台 -> 24 失敗復原驗收 -> 25 安全與當日準備
```

這一階段是三條 Step Functions 流程中的最後一條。前兩條的位置：

```text
Phase 14  infra/asl/ticket-analysis.asl.json   +  TrainingKbAppStack 第一條 state machine
Phase 16  infra/asl/release-update.asl.json    +  TrainingKbAppStack 第二條 state machine
Phase 18  infra/asl/feedback-review.asl.json   +  TrainingKbAppStack 第三條 state machine + 每日排程  << 你在這裡
```

---

## 3. 開始前檢查

- [ ] **檢查 1：Phase 17 的 task 都在，而且測試是綠的**

執行：

```bash
cd ~/AWS-Hackathon
uv run pytest tests/unit/test_pipelines_feedback.py -q
uv run python -c "from training_kb.pipelines.feedback import TASKS, TASK_ORDER; print(sorted(TASKS), TASK_ORDER)"
```

預期：測試全部通過；第二行印出
`['collect', 'diagnose', 'list_targets', 'publish', 'refine'] ('list_targets', 'collect', 'propose_rules', 'diagnose', 'refine', 'publish')`。
注意 `TASKS` 目前**沒有** `propose_rules`，這一階段要補上。

- [ ] **檢查 2：Phase 06 的 active 規則篩選在**

執行：

```bash
uv run python -c "from training_kb.writing.rules import select_active_rules, rules_for_content; print('rules ok')"
```

預期：印出 `rules ok`。本階段的隔離測試要用 `select_active_rules` 證明 candidate 不會進一般寫作。

- [ ] **檢查 3：Phase 02 的 AuthoringRule 模型有 validated_at 欄位**

執行：

```bash
uv run python - <<'PY'
from training_kb.models import AuthoringRule, RuleStatus
print(sorted(AuthoringRule.model_fields))
print([s.value for s in RuleStatus])
PY
```

預期：第一行包含 `applied_to`、`applies_when`、`derived_from`、`evidence`、`rule`、`rule_id`、`status`、`validated_at`；第二行是 `['candidate', 'active', 'retired']`。

- [ ] **檢查 4：Repository 有 put_rule 與 next_counter**

執行：

```bash
uv run python - <<'PY'
from training_kb.repository import Repository
need = ["put_rule", "list_rules", "next_counter", "get_steps", "list_feedback_of_version"]
print("缺少：", [n for n in need if not hasattr(Repository, n)])
PY
```

預期：印出 `缺少： []`。

- [ ] **檢查 5：Phase 14 的 Lambda 與 stack 檔案在，而且 ASL 目錄已建立**

執行：

```bash
ls -l infra/asl/ infra/stacks/
grep -n "TICKET_ASL\|RELEASE_ASL\|training-kb-pipeline-task\|PipelineTaskFunctionArn" infra/stacks/app_stack.py | head -20
```

預期：`infra/asl/` 底下已有 `ticket-analysis.asl.json` 與 `release-update.asl.json`；`infra/stacks/app_stack.py` 裡有路徑常數 `TICKET_ASL = "infra/asl/ticket-analysis.asl.json"`、有 `function_name="training-kb-pipeline-task"` 的 Lambda，而且 `definition_substitutions` 用的代換名稱是 `PipelineTaskFunctionArn`。請記下那支 Lambda 存在哪一個變數（Phase 14 用的是 `__init__` 裡的區域變數 `pipeline_task_fn`）。如果名稱不同，Task 6 的程式碼裡有兩處要換。

- [ ] **檢查 6：CDK CLI 可以用**

執行：

```bash
node --version
npx aws-cdk@2 --version
cat cdk.json
```

預期：`node` 顯示版本號；`npx aws-cdk@2 --version` 顯示 `2.x.y`；`cdk.json` 裡的 `app` 欄位指向 Phase 04 建立的 CDK 進入點（例如 `"app": "uv run python infra/app.py"`）。

- [ ] **檢查 7：先做一次 synth，確認目前的 stack 可以組出範本**

執行：

```bash
npx aws-cdk@2 synth TrainingKbAppStack > /dev/null && ls -l cdk.out/TrainingKbAppStack.template.json
```

預期：指令成功，而且 `cdk.out/TrainingKbAppStack.template.json` 存在。這個檔案是 Task 6、Task 7 測試的輸入。

---

## 4. 名詞小抄

| 名詞 | 白話解釋 | 在本階段哪裡用到 |
|---|---|---|
| Authoring Rule（寫作規則） | 一條「寫這種步驟時必須寫出什麼」的要求，例如「點 UI 時要寫出在哪個頁面、按鈕位置、點完會看到什麼」。 | `task_propose_rules` 產生它 |
| candidate | 規則的第一個狀態，意思是「還沒驗證過」。一般寫作**不會**採用 candidate（F27）。 | 新規則一律存成 candidate |
| active | 規則驗證通過後的狀態，只有這種規則會被注入寫作 prompt。 | Phase 20 才會寫入 |
| retired | 規則被判定無效或衝突後的狀態。 | Phase 20 |
| evidence | 規則的證據，只存 Feedback ID 清單（D15）。類別不另存快照，要用時去讀那幾筆回饋。 | `RuleProposal.evidence` |
| applies_when | 規則的適用範圍。MVP 只支援一個條件：`{"step.type": "click_ui"}`、`{"step.type": "input"}` 或 `{"step.type": "read"}`（D16）。 | `validate_rule_proposal` |
| derived_from | 規則是從哪一個教學版本歸納出來的，**恰好一個**版本 ID（D18）。 | `task_propose_rules` 直接填入 version_id |
| ASL（Amazon States Language） | Step Functions 的流程定義語言，是一份 JSON。 | `infra/asl/feedback-review.asl.json` |
| state machine（狀態機） | 一條 Step Functions 流程。本專案有三條，名稱固定。 | `training-kb-feedback-review` |
| Task state | ASL 裡呼叫外部服務（本專案是呼叫 Lambda）的節點。 | 六個節點都是 Task |
| Map state | ASL 裡「對清單裡的每一項各跑一次同一段流程」的節點。 | 對每一篇教學跑一次 |
| Inline mode | Map 的預設模式：每次迭代都跑在同一個執行紀錄裡，最多 40 個同時進行。任何一次迭代失敗，整個 Map 就失敗。 | 本專案用這個模式 |
| Choice state | ASL 裡的分支節點，依 state 內某個欄位決定下一步。 | 依 `$.action` 決定要不要 refine |
| Fail state | ASL 裡的失敗終點。 | `PipelineFailed`、`ItemFailed` |
| Retry／Catch | Task 節點的重試設定與失敗跳轉設定。設計文件要求每個 Task 都要有。 | 每個 Task 都寫 |
| context object（`$$`） | Step Functions 在執行期提供的額外資料，例如 `$$.Execution.Name`（這次執行的名稱）、`$$.Map.Item.Value`（Map 的當前項目）。 | ASL 的 `ItemSelector` |
| definition_substitutions | CDK 把 ASL 檔裡的 `${名稱}` 換成實際值（例如 Lambda ARN）的機制。 | `${PipelineTaskFunctionArn}` |
| EventBridge Scheduler | AWS 的排程服務，可以用 cron 或 rate 表達式定時啟動別的服務。 | 每日 00:30 UTC |
| 執行角色（execution role） | Scheduler 代替你去啟動別的服務時用的 IAM 角色。信任 `scheduler.amazonaws.com`，並被授權 `states:StartExecution`。 | Task 7 |
| cron 表達式 | EventBridge Scheduler 的六欄格式：`cron(分 時 日 月 星期 年)`。 | `cron(30 0 * * ? *)` |
| `?` 萬用字元 | 在「日」或「星期」欄位代表「任何值」。兩個欄位不能同時用 `*`，其中一個必須用 `?`。 | `cron(30 0 * * ? *)` 的第五欄 |
| F25／F26／F27／F49 | 設計文件第 19 節的功能決策編號。 | 第 10 節對照表 |
| D15／D16／D18 | 設計文件第 19 節的資料決策編號。 | 第 10 節對照表 |

---

## 5. 設計說明

### 5.1 提出候選規則走的是另一條路

設計文件 §7.5 明講：提出 candidate「不必先達弱教學門檻」。這兩條路的差別：

```text
                    collect 算出：n、平均、各核定類別筆數
                                    |
          +-------------------------+-------------------------+
          |                                                   |
          v                                                   v
  propose_rules（本階段）                              diagnose（Phase 17）
  條件：同一版本、同一核定類別 >= 5 筆                條件：平均 < 3.5
  不看平均、不看總筆數（F26）                              且 n >= 10（Demo 8）
          |                                                且 同類 >= 5
          v                                                   |
  請模型歸納一條寫作要求                                       v
          |                                            請模型診斷步驟
          v                                                   |
  程式驗證四件事                                              v
   1 evidence 只含該版本的回饋 ID                         REFINE 或不建版本
   2 至少 5 筆
   3 applies_when 只有一個 step.type 等值
   4 derived_from 恰好是這一版
          |
          v
  同一組證據提出過了嗎？（排序後比對）
          | 否
          v
  rule_id = R-<三位數>，status = candidate，validated_at = None
          |
          v
  put_rule（寫進 DynamoDB）
          |
          v
  一般寫作路徑只讀 active -> candidate 不會被採用（F27）
```

舉例說明 F25「不跨版本」為什麼重要：

```text
情況 A（可以提案）
  prepare-meeting@v1 的「找不到按鈕」回饋：f_12 f_15 f_19 f_23 f_27  -> 5 筆 -> 提出
  derived_from = "prepare-meeting@v1"（恰好一版）

情況 B（不可以提案）
  prepare-meeting@v1 的「找不到按鈕」回饋：f_12 f_15 f_19           -> 3 筆
  prepare-meeting@v2 的「找不到按鈕」回饋：f_60 f_61                -> 2 筆
  3 + 2 = 5，但分散在兩版。每一版各自都沒到 5，兩版都不提案。
  理由：derived_from 恰好一個版本（D18），跨版拼湊會讓證據無法追溯到單一來源。
```

### 5.2 Feedback Review 的 Step Functions 流程長什麼樣

```text
                         EventBridge Scheduler
                      cron(30 0 * * ? *) UTC
                      input = {"policy": "formal"}
                                 |
                                 v
              +--------------------------------------+
              |  state machine                        |
              |  training-kb-feedback-review          |
              +--------------------------------------+
                                 |
                                 v
                        +------------------+
                        |  ListTargets     |  Task -> Lambda(task=list_targets)
                        |  Retry / Catch   |
                        +--------+---------+
                                 | 產出 $.targets = [{slug, version_id}, ...]
                                 v
     +===========================================================+
     |  ReviewEachTutorial   Type=Map  Mode=INLINE               |
     |  ItemsPath=$.targets  MaxConcurrency=1                    |
     |  ItemSelector: run_id=$$.Execution.Name, policy=$.policy, |
     |                slug/version_id=$$.Map.Item.Value.*        |
     |                                                           |
     |   +----------+   +---------------+   +-----------+        |
     |   | Collect  |-->| ProposeRules  |-->| Diagnose  |        |
     |   +----------+   +---------------+   +-----+-----+        |
     |                                            |              |
     |                                     +------v------+       |
     |                                     | NeedRefine  | Choice|
     |                                     +--+-------+--+       |
     |                        action=REFINE   |       | 其他      |
     |                                        v       v          |
     |                                  +--------+ +-------------+|
     |                                  | Refine | | NoNewVersion||
     |                                  +--------+ +-------------+|
     |                                                           |
     |   每個 Task 都有 Retry / Catch；Catch 指向 ItemFailed（Fail）|
     |   任一篇失敗 -> 整個 Map 失敗 -> 所有迭代停止               |
     +===========================================================+
                                 | ResultPath=$.items
                                 v
                        +------------------+
                        |  PublishAll      |  Task -> Lambda(task=publish)
                        |  Retry / Catch   |  整批 content.publish
                        +--------+---------+
                                 |
                                 v
                               成功結束

  任一 Catch 觸發 -> PipelineFailed（Type=Fail）-> 執行失敗，沒有任何版本上架
```

為什麼「所有教學都跑完才 publish」？設計文件 §8.3 與 F49：

> 同一 Release 或每日 Review 若命中多篇教學，也受 F49「整次失敗不發布新版」限制。不能在逐篇 Map 中先發布 A，再因 B 失敗而聲稱整次沒有發布。

所以 Map 裡面**只建立未發布的版本**（`published_at` 是空的，讀者看不到），發布動作留到 Map 完成之後的 `PublishAll` 一次做完。這樣三種失敗情境都符合 F49：

```text
情境 1：A 的 refine 失敗
  -> ItemFailed -> Map 失敗 -> PipelineFailed
  -> PublishAll 沒有執行 -> A、B 都維持舊版

情境 2：A 成功、B 的 refine 失敗
  -> Map 是 INLINE 模式，任一迭代失敗整個 Map 失敗
  -> PublishAll 沒有執行 -> A 的新版留在未發布狀態，讀者看到的還是舊版

情境 3：兩篇都建好版本，但 PublishAll 中途失敗
  -> content.publish 本身就是「全部驗證完成才提交」（Phase 08、O3 本計劃選擇）
  -> PublishResult.failed 有值 -> task_publish 拋例外 -> PipelineFailed
  -> 沒有任何 current_version 被切換
```

三種情境的重送都靠操作紀錄：`allocate_version` 用同一個 `review:<slug>:<evidence_key>` 找回原版號（D26），所以重跑不會產生第二條版本鏈。

### 5.3 每日排程與 Demo 手動觸發

```text
時間軸（UTC）

00:00 ─────────── 00:30 ─────────── 00:31 ────────────────────────► 隔天 00:30
                    |                  |
                    |                  +-- 執行結束，操作紀錄寫入
                    |
                    +-- EventBridge Scheduler 觸發
                        StartExecution(training-kb-feedback-review,
                                       input = {"policy": "formal"})

任何時間（Demo 現場）
                    +-- 維護者用 AWS CLI 手動觸發
                        StartExecution(training-kb-feedback-review,
                                       input = {"policy": "demo"})
                        同一條 state machine、同一支 Lambda、同一段程式。
                        唯一差別是 ReviewPolicy.for_name("demo").min_feedback = 8。
```

`cron(30 0 * * ? *)` 六個欄位的意思：

```text
cron( 30    0     *       *      ?         *   )
       |    |     |       |      |         |
       |    |     |       |      |         +-- 年：每年
       |    |     |       |      +------------ 星期：任何（因為「日」已經用 *）
       |    |     |       +------------------- 月：每月
       |    |     +--------------------------- 日：每天
       |    +--------------------------------- 時：0 時
       +-------------------------------------- 分：30 分

規則：「日」與「星期」兩欄不能同時用 *，其中一個必須寫 ?。
時區由 ScheduleExpressionTimezone 指定；本專案固定寫 "UTC"。
```

### 5.4 本階段會新增或修改的檔案

```text
src/training_kb/
  writing/
    schemas.py        << 新增 RuleProposal
    prompts.py        << 新增 prompt_propose_rule
  pipelines/
    feedback.py       << 新增 validate_rule_proposal / proposal_evidence_key /
                         proposed_evidence_keys / task_propose_rules / run_review
                         並把 propose_rules 登記進 TASKS
infra/
  asl/
    ticket-analysis.asl.json      （Phase 14）
    release-update.asl.json       （Phase 16）
    feedback-review.asl.json      << 新增
  stacks/
    app_stack.py                  << 修改：第三條 state machine + 每日排程
tests/unit/
  test_pipelines_feedback.py      << 修改：候選規則與 run_review 的測試
  test_asl_feedback_review.py     << 新增：純 JSON 結構檢查
  test_infra_feedback_review.py   << 新增：檢查 cdk synth 出來的 CloudFormation 範本
```

一條 candidate 規則存進 DynamoDB 後長這樣：

```text
PK  = "RULE#R-003"
SK  = "META"
entity      = "RULE"
rule_id     = "R-003"
rule        = "步驟要求點擊 UI 元件時，必須寫出：在哪個頁面、按鈕位置、點完會看到什麼"
applies_when= {"step.type": "click_ui"}          只有一個條件（D16）
evidence    = ["f_12","f_15","f_19","f_23","f_27"]  只有 Feedback ID（D15）
status      = "candidate"                          一般寫作不會取用（F27）
applied_to  = []                                   由各版本 rules_applied 重建（D17）
derived_from= "prepare-meeting@v1"                 恰好一版（D18）
validated_at= null                                 只有 Analytics 能寫（Phase 20）
```

---

## 6. 工作項目

### Task 1：prompt_propose_rule

**目的**：寫出問模型「這一批同類回饋可以歸納出哪一條寫作要求」的題目。回傳格式 `RuleProposal` 由 Phase 05 定義好了，這裡只補 prompt，並用測試釘住 schema 對本階段重要的行為。

**檔案**：
- 修改：`src/training_kb/writing/prompts.py`
- 測試：`tests/unit/test_writing_propose_rule.py`

**介面**：
- 消費：
  - `writing.schemas.RuleProposal`（pydantic model，欄位 `rule: str`、`applies_when: dict[str, str]`、`evidence: list[str]`）（Phase 05）
  - `models.Feedback`、`models.TutorialStep`（Phase 02）
- 產出：`writing.prompts.prompt_propose_rule(feedback: list[Feedback], steps: list[TutorialStep]) -> tuple[str, str]`

> 注意 `applies_when` 的型別是 `dict[str, str]`（Phase 05 依 D16 選的），值只能是字串。所以模型若回 `{"step.type": 3}` 這種東西，pydantic 在 `generate_json` 階段就會擋掉，根本進不到 Task 2 的業務驗證。

- [ ] **步驟 1：寫測試**

建立 `tests/unit/test_writing_propose_rule.py`：

```python
"""Phase 18：候選規則的 prompt，以及 Phase 05 schema 的行為確認。"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from training_kb.models import Feedback, StepType, TutorialStep
from training_kb.writing.prompts import prompt_propose_rule
from training_kb.writing.schemas import RuleProposal


def sample_feedback() -> list[Feedback]:
    return [
        Feedback(id=f"f_{n}", tutorial_version="prepare-meeting@v1", rating=2,
                 user=f"u_{n}", category="找不到按鈕",
                 comment="第三步沒有指出按鈕在哪一頁與位置", ts="2026-08-02T09:00:00Z")
        for n in (12, 15, 19, 23, 27)
    ]


def sample_steps() -> list[TutorialStep]:
    return [
        TutorialStep(tutorial_version="prepare-meeting@v1", index=3,
                     type=StepType.click_ui, text="點選摘要。", feature_id="Prepare"),
    ]


def test_rule_proposal_parses_three_fields():
    parsed = RuleProposal.model_validate({
        "rule": "點擊 UI 時要寫出頁面、按鈕位置與結果",
        "applies_when": {"step.type": "click_ui"},
        "evidence": ["f_12", "f_15", "f_19", "f_23", "f_27"],
    })
    assert parsed.applies_when == {"step.type": "click_ui"}
    assert len(parsed.evidence) == 5


def test_rule_proposal_requires_evidence_list():
    with pytest.raises(ValidationError):
        RuleProposal.model_validate({
            "rule": "x", "applies_when": {"step.type": "click_ui"}, "evidence": "f_12",
        })


def test_rule_proposal_requires_rule_text():
    with pytest.raises(ValidationError):
        RuleProposal.model_validate({
            "applies_when": {"step.type": "click_ui"}, "evidence": ["f_12"],
        })


def test_rule_proposal_rejects_non_string_condition_value():
    # Phase 05 依 D16 把型別定成 dict[str, str]，值不是字串就被擋下來。
    with pytest.raises(ValidationError):
        RuleProposal.model_validate({
            "rule": "x", "applies_when": {"step.type": 3}, "evidence": ["f_12"],
        })


def test_rule_proposal_rejects_extra_field():
    # Phase 05 的 StrictModel 設了 extra="forbid"，模型偷加欄位會失敗。
    with pytest.raises(ValidationError):
        RuleProposal.model_validate({
            "rule": "x", "applies_when": {"step.type": "click_ui"},
            "evidence": ["f_12"], "confidence": "high",
        })


def test_prompt_propose_rule_states_single_condition_limit():
    system, user = prompt_propose_rule(sample_feedback(), sample_steps())

    assert "step.type" in system
    assert "不可以有第二個條件" in system
    assert "不可以發明新的 ID" in system
    assert "f_12" in user
    assert "第三步沒有指出按鈕在哪一頁與位置" in user
    assert "3. [click_ui] 點選摘要。" in user


def test_prompt_propose_rule_lists_every_evidence_id():
    _, user = prompt_propose_rule(sample_feedback(), sample_steps())
    for feedback_id in ("f_12", "f_15", "f_19", "f_23", "f_27"):
        assert feedback_id in user
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：

```bash
uv run pytest tests/unit/test_writing_propose_rule.py -v
```

預期：FAIL，錯誤訊息是 `ImportError: cannot import name 'prompt_propose_rule' from 'training_kb.writing.prompts'`。schema 測試會因為同一個 import 錯誤一起失敗；等 prompt 寫好之後它們會直接通過，因為 `RuleProposal` 在 Phase 05 就做好了。

- [ ] **步驟 3：寫最少的程式讓測試通過**

在 `src/training_kb/writing/prompts.py` 最後加入：

```python
def prompt_propose_rule(
    feedback: list[Feedback], steps: list[TutorialStep]
) -> tuple[str, str]:
    """問模型：這一批同類回饋可以歸納出哪一條寫作要求。

    回傳 (system, user)。模型輸出之後仍要通過 pipelines.feedback.validate_rule_proposal，
    prompt 的限制不能代替程式驗證。
    """
    system = (
        "你是技術文件的寫作規範編輯。下面是同一個教學版本、同一種問題類別的使用者回饋，"
        "請歸納出一條可以套用到未來教學的寫作要求。\n"
        "規則：\n"
        "1. rule 只寫一條，用一句話說清楚「寫這種步驟時必須寫出什麼」。\n"
        '2. applies_when 只能是 {"step.type": "click_ui"}、{"step.type": "input"} '
        '或 {"step.type": "read"} 其中一個，不可以有第二個條件，也不可以寫運算式。\n'
        "3. evidence 只能列出下面出現過的回饋 ID，不可以發明新的 ID。\n"
        "4. 不要提到特定產品名稱或特定教學，規則要能用在別篇教學。\n"
        '5. 只輸出 JSON，格式為 '
        '{"rule": "...", "applies_when": {"step.type": "click_ui"}, "evidence": ["f_12"]}。'
    )
    step_lines = "\n".join(
        f"{step.index}. [{step.type}] {step.text}"
        for step in sorted(steps, key=lambda s: s.index)
    )
    feedback_lines = "\n".join(
        f"- {item.id}／評分 {item.rating}／類別 {item.category or '無'}"
        f"／留言：{item.comment or '（無留言）'}"
        for item in feedback
    )
    user = (
        f"這一版的步驟：\n{step_lines or '（沒有步驟）'}\n\n"
        f"同一類別的回饋（共 {len(feedback)} 筆）：\n{feedback_lines}\n\n"
        "請輸出 JSON。"
    )
    return system, user
```

（`prompts.py` 開頭若還沒有 `from training_kb.models import Feedback, TutorialStep`，補上缺的名稱。）

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：

```bash
uv run pytest tests/unit/test_writing_propose_rule.py -v
```

預期：PASS，7 個測試全綠。

- [ ] **步驟 5：commit**

```bash
git add src/training_kb/writing/prompts.py tests/unit/test_writing_propose_rule.py
git commit -m "feat(writing): 加入候選規則的 prompt"
```

---

### Task 2：程式驗證候選規則

**目的**：模型輸出通過 JSON schema 不代表合法。這個函式檢查四件事：證據只含該版本的回饋、至少五筆、`applies_when` 只有一個 `step.type` 等值條件、`derived_from` 是合法的單一版本 ID。

**檔案**：
- 修改：`src/training_kb/pipelines/feedback.py`
- 修改：`tests/unit/test_pipelines_feedback.py`

**介面**：
- 消費：`writing.schemas.RuleProposal`（Task 1）、`models.StepType`（Phase 02）、`errors.ContentError`（Phase 01）
- 產出：`pipelines.feedback.validate_rule_proposal(proposal: RuleProposal, *, version_id: str, evidence_ids: list[str], min_count: int) -> tuple[list[str], dict]`（本階段新增；回傳「去重排序後的 evidence」與「正規化後的 applies_when」）

- [ ] **步驟 1：寫測試**

在 `tests/unit/test_pipelines_feedback.py` 最後加入：

```python
from training_kb.writing.schemas import RuleProposal

FIVE_IDS = ["f_12", "f_15", "f_19", "f_23", "f_27"]


def a_proposal(**overrides) -> RuleProposal:
    data = {
        "rule": "步驟要求點擊 UI 元件時，必須寫出：在哪個頁面、按鈕位置、點完會看到什麼",
        "applies_when": {"step.type": "click_ui"},
        "evidence": list(FIVE_IDS),
    }
    data.update(overrides)
    return RuleProposal.model_validate(data)


def test_validate_rule_proposal_accepts_five_ids_from_same_version():
    evidence, applies_when = validate_rule_proposal(
        a_proposal(),
        version_id="prepare-meeting@v1",
        evidence_ids=FIVE_IDS,
        min_count=5,
    )
    assert evidence == FIVE_IDS
    assert applies_when == {"step.type": "click_ui"}


def test_validate_rule_proposal_rejects_id_from_another_version():
    # D15／F25：evidence 只能是該版本的回饋 ID。
    with pytest.raises(ContentError):
        validate_rule_proposal(
            a_proposal(evidence=FIVE_IDS[:4] + ["f_60"]),
            version_id="prepare-meeting@v1",
            evidence_ids=FIVE_IDS,
            min_count=5,
        )


def test_validate_rule_proposal_rejects_fewer_than_five():
    with pytest.raises(ContentError):
        validate_rule_proposal(
            a_proposal(evidence=FIVE_IDS[:4]),
            version_id="prepare-meeting@v1",
            evidence_ids=FIVE_IDS,
            min_count=5,
        )


def test_validate_rule_proposal_counts_unique_ids_only():
    with pytest.raises(ContentError):
        validate_rule_proposal(
            a_proposal(evidence=["f_12", "f_12", "f_15", "f_15", "f_19"]),
            version_id="prepare-meeting@v1",
            evidence_ids=FIVE_IDS,
            min_count=5,
        )


def test_validate_rule_proposal_rejects_two_conditions():
    # D16：只支援單一 step.type 條件，不支援 AND/OR 組合。
    # 注意值都寫成字串，因為 Phase 05 的 applies_when 型別是 dict[str, str]；
    # 這個測試要測的是「條件有兩個」，不是型別錯誤。
    with pytest.raises(ContentError):
        validate_rule_proposal(
            a_proposal(applies_when={"step.type": "click_ui", "step.index": "3"}),
            version_id="prepare-meeting@v1",
            evidence_ids=FIVE_IDS,
            min_count=5,
        )


def test_validate_rule_proposal_rejects_unknown_step_type():
    with pytest.raises(ContentError):
        validate_rule_proposal(
            a_proposal(applies_when={"step.type": "scroll"}),
            version_id="prepare-meeting@v1",
            evidence_ids=FIVE_IDS,
            min_count=5,
        )


def test_validate_rule_proposal_rejects_expression_style_condition():
    # 模型把整個判斷式塞進 key；鍵不是 "step.type" 就不接受。
    with pytest.raises(ContentError):
        validate_rule_proposal(
            a_proposal(applies_when={"step.type == click_ui": "true"}),
            version_id="prepare-meeting@v1",
            evidence_ids=FIVE_IDS,
            min_count=5,
        )


def test_validate_rule_proposal_rejects_blank_rule_text():
    with pytest.raises(ContentError):
        validate_rule_proposal(
            a_proposal(rule="   "),
            version_id="prepare-meeting@v1",
            evidence_ids=FIVE_IDS,
            min_count=5,
        )


def test_validate_rule_proposal_rejects_bad_derived_from():
    # D18：derived_from 恰好一個裸 version_id，格式是 <slug>@v<n>。
    with pytest.raises(ContentError):
        validate_rule_proposal(
            a_proposal(),
            version_id="prepare-meeting",
            evidence_ids=FIVE_IDS,
            min_count=5,
        )
```

把 import 區的 `from training_kb.pipelines.feedback import (...)` 補上 `validate_rule_proposal`。

- [ ] **步驟 2：跑測試，確認它失敗**

執行：

```bash
uv run pytest tests/unit/test_pipelines_feedback.py -v
```

預期：FAIL，錯誤訊息是 `ImportError: cannot import name 'validate_rule_proposal'`。

- [ ] **步驟 3：寫最少的程式讓測試通過**

在 `src/training_kb/pipelines/feedback.py` 的 import 區補上：

```python
from training_kb.models import StepType
from training_kb.writing.schemas import RuleProposal, StepRewrite, StepRewriteItem, WeakDiagnosis
```

（把原本的 `from training_kb.writing.schemas import StepRewrite, StepRewriteItem, WeakDiagnosis` 整行換掉；`StepType` 併進既有的 models import 也可以。）

在檔案最後加入：

```python
def _is_version_id(value: str) -> bool:
    """裸版本 ID 的格式是 <slug>@v<n>，例如 prepare-meeting@v1。"""
    if value.count("@v") != 1:
        return False
    slug, number = value.split("@v", 1)
    return bool(slug) and number.isdigit() and int(number) >= 1


def validate_rule_proposal(
    proposal: RuleProposal,
    *,
    version_id: str,
    evidence_ids: list[str],
    min_count: int,
) -> tuple[list[str], dict]:
    """用程式驗證模型提出的候選規則（設計文件 §7.6）。

    回傳 (去重排序後的 evidence, 正規化後的 applies_when)。
    任何一項不合格就拋 ContentError，這一次不寫入規則。
    """
    if not proposal.rule.strip():
        raise ContentError("候選規則的 rule 不可為空白")

    allowed = set(evidence_ids)
    unique = sorted(set(proposal.evidence))
    unknown = [feedback_id for feedback_id in unique if feedback_id not in allowed]
    if unknown:
        raise ContentError(
            f"候選規則的 evidence 含有不屬於 {version_id} 的回饋 ID：{unknown}"
        )
    if len(unique) < min_count:
        raise ContentError(
            f"候選規則的 evidence 只有 {len(unique)} 筆，未達 {min_count} 筆門檻"
        )

    applies_when = dict(proposal.applies_when)
    if set(applies_when) != {"step.type"}:
        raise ContentError(
            f"applies_when 只允許單一 step.type 條件，實際收到：{applies_when}"
        )
    value = applies_when["step.type"]
    valid_types = {step_type.value for step_type in StepType}
    if value not in valid_types:
        raise ContentError(
            f"applies_when 的 step.type 不是合法步驟型態：{value}（合法值：{sorted(valid_types)}）"
        )

    if not _is_version_id(version_id):
        raise ContentError(f"derived_from 不是合法的版本識別碼：{version_id}")

    return unique, {"step.type": value}
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：

```bash
uv run pytest tests/unit/test_pipelines_feedback.py -v
```

預期：PASS，比 Phase 17 結束時多 9 個測試全綠。

- [ ] **步驟 5：commit**

```bash
git add src/training_kb/pipelines/feedback.py tests/unit/test_pipelines_feedback.py
git commit -m "feat(feedback): 加入候選規則的程式驗證"
```

---

### Task 3：同一組證據不重複提出

**目的**：設計文件 §7.5 要求「同一次證據集合排序後比對，避免重複提出相同內容的 candidate」。這個 Task 做出可重算的指紋，以及從已存規則反推指紋的查詢。

**檔案**：
- 修改：`src/training_kb/pipelines/feedback.py`
- 修改：`tests/unit/test_pipelines_feedback.py`

**介面**：
- 消費：`repository.Repository.list_rules`（Phase 03）
- 產出：
  - `pipelines.feedback.proposal_evidence_key(version_id: str, evidence: list[str]) -> str`（本階段新增）
  - `pipelines.feedback.proposed_evidence_keys(repo: Repository, version_id: str) -> set[str]`（本階段新增）

> 指紋只用 `(version_id, 排序去重後的 evidence)` 計算，不含類別。理由：D15 規定 evidence 只存 Feedback ID、類別要從被引用的回饋讀，所以指紋必須只用存得下來的資料算，才能在下一次執行重新算出同一個值。

- [ ] **步驟 1：寫測試**

在 `tests/unit/test_pipelines_feedback.py` 最後加入：

```python
def make_rule(rule_id: str, version_id: str, evidence: list[str], status=RuleStatus.candidate):
    return AuthoringRule(
        rule_id=rule_id,
        rule="步驟要求點擊 UI 元件時，必須寫出：在哪個頁面、按鈕位置、點完會看到什麼",
        applies_when={"step.type": "click_ui"},
        evidence=list(evidence),
        status=status,
        applied_to=[],
        derived_from=version_id,
        validated_at=None,
    )


def test_proposal_evidence_key_is_order_independent():
    a = proposal_evidence_key("prepare-meeting@v1", ["f_15", "f_12", "f_19"])
    b = proposal_evidence_key("prepare-meeting@v1", ["f_19", "f_12", "f_15"])
    assert a == b


def test_proposal_evidence_key_depends_on_version():
    a = proposal_evidence_key("prepare-meeting@v1", FIVE_IDS)
    b = proposal_evidence_key("prepare-meeting@v2", FIVE_IDS)
    assert a != b


def test_proposed_evidence_keys_recomputes_from_stored_rules():
    repo = FakeRepo()
    repo.rules = [
        make_rule("R-007", "prepare-meeting@v1", FIVE_IDS),
        make_rule("R-009", "share-summary@v1", ["f_71", "f_72", "f_73", "f_74", "f_75"]),
    ]

    keys = proposed_evidence_keys(repo, "prepare-meeting@v1")

    assert keys == {proposal_evidence_key("prepare-meeting@v1", FIVE_IDS)}


def test_proposed_evidence_keys_is_empty_for_new_version():
    repo = FakeRepo()
    assert proposed_evidence_keys(repo, "prepare-meeting@v9") == set()
```

把 import 區的 `from training_kb.pipelines.feedback import (...)` 補上 `proposal_evidence_key`、`proposed_evidence_keys`。若 `AuthoringRule`、`RuleStatus` 還沒 import，補進 `from training_kb.models import (...)`。

- [ ] **步驟 2：跑測試，確認它失敗**

執行：

```bash
uv run pytest tests/unit/test_pipelines_feedback.py -v
```

預期：FAIL，錯誤訊息是 `ImportError: cannot import name 'proposal_evidence_key'`。

- [ ] **步驟 3：寫最少的程式讓測試通過**

在 `src/training_kb/pipelines/feedback.py` 最後加入：

```python
def proposal_evidence_key(version_id: str, evidence: list[str]) -> str:
    """候選規則的證據指紋。

    同一版本、同一組（排序去重後）回饋 ID 一定得到同一個值；
    這個值可以由已保存的 AUTHORING_RULE 重新算出來（設計文件 §7.5）。
    """
    payload = json.dumps(
        [version_id, sorted(set(evidence))], ensure_ascii=False, separators=(",", ":")
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def proposed_evidence_keys(repo: Repository, version_id: str) -> set[str]:
    """列出這一版已經提出過的候選規則證據指紋。"""
    return {
        proposal_evidence_key(rule.derived_from, list(rule.evidence))
        for rule in repo.list_rules()
        if rule.derived_from == version_id
    }
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：

```bash
uv run pytest tests/unit/test_pipelines_feedback.py -v
```

預期：PASS，比上一個 Task 多 4 個測試全綠。

- [ ] **步驟 5：commit**

```bash
git add src/training_kb/pipelines/feedback.py tests/unit/test_pipelines_feedback.py
git commit -m "feat(feedback): 加入候選規則證據指紋與去重查詢"
```

---

### Task 4：propose_rules task 與 TASKS 註冊

**目的**：把前三個 Task 串起來，變成可以掛進流程的 `propose_rules` 節點，並登記到 `TASKS`。

**檔案**：
- 修改：`src/training_kb/pipelines/feedback.py`
- 修改：`tests/unit/test_pipelines_feedback.py`

**介面**：
- 消費：`writing.prompts.prompt_propose_rule`（Task 1）、`writing.rules.select_active_rules`（Phase 06，僅測試使用）、`repository.Repository.next_counter` / `put_rule`（Phase 03）、`models.AuthoringRule` / `RuleStatus`（Phase 02）
- 產出：
  - `pipelines.feedback.task_propose_rules(state: dict, deps: Deps) -> dict`
  - `pipelines.feedback.TASKS` 增加 `"propose_rules"` 這一項

- [ ] **步驟 1：寫測試**

在 `tests/unit/test_pipelines_feedback.py` 最後加入：

```python
from training_kb.writing.rules import select_active_rules

R007_TEXT = "步驟要求點擊 UI 元件時，必須寫出：在哪個頁面、按鈕位置、點完會看到什麼"


def collected_state(repo: FakeRepo, version_id: str, *, policy: str = "formal") -> dict:
    slug = version_id.split("@v")[0]
    return task_collect(
        {"run_id": "2026-09-14", "policy": policy, "slug": slug, "version_id": version_id},
        make_deps(repo),
    )


def test_propose_rules_creates_candidate_from_five_same_category():
    repo = FakeRepo()
    add_tutorial(repo, "prepare-meeting", current_version="prepare-meeting@v1")
    add_version_with_steps(repo, "prepare-meeting", "prepare-meeting@v1")
    add_feedback(repo, "prepare-meeting@v1", A_V1_ROWS)
    state = collected_state(repo, "prepare-meeting@v1")
    writer = FakeWriter(outputs=[RuleProposal(
        rule=R007_TEXT,
        applies_when={"step.type": "click_ui"},
        evidence=[row[0] for row in A_V1_ROWS],
    )])

    out = task_propose_rules(state, make_deps(repo, writer))

    assert out["proposed_rule_ids"] == ["R-001"]
    saved = repo.saved_rules[0]
    assert saved.rule_id == "R-001"
    assert saved.status == RuleStatus.candidate
    assert saved.validated_at is None
    assert saved.applied_to == []
    assert saved.derived_from == "prepare-meeting@v1"
    assert saved.evidence == sorted(row[0] for row in A_V1_ROWS)
    assert saved.applies_when == {"step.type": "click_ui"}


def test_propose_rules_does_not_need_weak_threshold():
    # F26：平均分很高、總筆數只有 5 筆，一樣可以提出 candidate。
    repo = FakeRepo()
    add_tutorial(repo, "share-summary", current_version="share-summary@v1")
    add_version_with_steps(repo, "share-summary", "share-summary@v1")
    add_feedback(
        repo, "share-summary@v1",
        [(f"f_7{n}", f"u_{n}", 5, "缺少資訊") for n in range(1, 6)],
    )
    state = collected_state(repo, "share-summary@v1")
    assert state["avg"] == 5.0  # 完全不是弱教學
    writer = FakeWriter(outputs=[RuleProposal(
        rule="步驟要求閱讀畫面內容時，必須寫出畫面上會出現哪些欄位",
        applies_when={"step.type": "read"},
        evidence=[f"f_7{n}" for n in range(1, 6)],
    )])

    out = task_propose_rules(state, make_deps(repo, writer))

    assert out["proposed_rule_ids"] == ["R-001"]


def test_propose_rules_skips_when_category_has_four():
    repo = FakeRepo()
    add_tutorial(repo, "prepare-meeting", current_version="prepare-meeting@v1")
    add_version_with_steps(repo, "prepare-meeting", "prepare-meeting@v1")
    add_feedback(repo, "prepare-meeting@v1", A_V1_ROWS[:4])
    state = collected_state(repo, "prepare-meeting@v1")

    out = task_propose_rules(state, make_deps(repo))

    assert out["proposed_rule_ids"] == []
    assert repo.saved_rules == []


def test_propose_rules_does_not_accumulate_across_versions():
    # F25：3 + 2 分散在兩版，兩版都不到 5 筆，兩版都不提案。
    repo = FakeRepo()
    add_tutorial(repo, "prepare-meeting", current_version="prepare-meeting@v2")
    add_version_with_steps(repo, "prepare-meeting", "prepare-meeting@v1")
    repo.objects["tutorials/prepare-meeting/v2.md"] = A_V1_MARKDOWN.encode("utf-8")
    add_feedback(repo, "prepare-meeting@v1", A_V1_ROWS[:3])
    add_feedback(
        repo, "prepare-meeting@v2",
        [("f_60", "u_01", 2, "找不到按鈕"), ("f_61", "u_02", 2, "找不到按鈕")],
    )

    out_v1 = task_propose_rules(collected_state(repo, "prepare-meeting@v1"), make_deps(repo))
    out_v2 = task_propose_rules(collected_state(repo, "prepare-meeting@v2"), make_deps(repo))

    assert out_v1["proposed_rule_ids"] == []
    assert out_v2["proposed_rule_ids"] == []
    assert repo.saved_rules == []


def test_propose_rules_does_not_repeat_same_evidence_set():
    repo = FakeRepo()
    add_tutorial(repo, "prepare-meeting", current_version="prepare-meeting@v1")
    add_version_with_steps(repo, "prepare-meeting", "prepare-meeting@v1")
    add_feedback(repo, "prepare-meeting@v1", A_V1_ROWS)
    proposal = RuleProposal(
        rule=R007_TEXT,
        applies_when={"step.type": "click_ui"},
        evidence=[row[0] for row in A_V1_ROWS],
    )

    first = task_propose_rules(
        collected_state(repo, "prepare-meeting@v1"),
        make_deps(repo, FakeWriter(outputs=[proposal])),
    )
    second = task_propose_rules(
        collected_state(repo, "prepare-meeting@v1"),
        make_deps(repo, FakeWriter(outputs=[proposal])),
    )

    assert first["proposed_rule_ids"] == ["R-001"]
    assert second["proposed_rule_ids"] == []
    assert second["proposal_skipped_categories"] == ["找不到按鈕"]
    assert len(repo.saved_rules) == 1


def test_candidate_rule_never_enters_normal_writing():
    # F27：一般寫作路徑只取 active；candidate 不會被 select_active_rules 選中。
    repo = FakeRepo()
    add_tutorial(repo, "prepare-meeting", current_version="prepare-meeting@v1")
    add_version_with_steps(repo, "prepare-meeting", "prepare-meeting@v1")
    add_feedback(repo, "prepare-meeting@v1", A_V1_ROWS)
    writer = FakeWriter(outputs=[RuleProposal(
        rule=R007_TEXT,
        applies_when={"step.type": "click_ui"},
        evidence=[row[0] for row in A_V1_ROWS],
    )])

    task_propose_rules(collected_state(repo, "prepare-meeting@v1"), make_deps(repo, writer))

    saved = repo.saved_rules[0]
    assert select_active_rules([saved], StepType.click_ui) == []
    assert repo.list_rules(RuleStatus.active) == []


def test_propose_rules_rejects_invalid_model_output():
    repo = FakeRepo()
    add_tutorial(repo, "prepare-meeting", current_version="prepare-meeting@v1")
    add_version_with_steps(repo, "prepare-meeting", "prepare-meeting@v1")
    add_feedback(repo, "prepare-meeting@v1", A_V1_ROWS)
    writer = FakeWriter(outputs=[RuleProposal(
        rule=R007_TEXT,
        applies_when={"step.type": "click_ui"},
        evidence=["f_12", "f_15", "f_999", "f_998", "f_997"],
    )])

    with pytest.raises(ContentError):
        task_propose_rules(collected_state(repo, "prepare-meeting@v1"), make_deps(repo, writer))
    assert repo.saved_rules == []


def test_tasks_registry_now_has_propose_rules():
    assert set(TASKS) == set(TASK_ORDER)
    assert TASKS["propose_rules"] is task_propose_rules
```

把 import 區的 `from training_kb.pipelines.feedback import (...)` 補上 `task_propose_rules`。

- [ ] **步驟 2：跑測試，確認它失敗**

執行：

```bash
uv run pytest tests/unit/test_pipelines_feedback.py -v
```

預期：FAIL，錯誤訊息是 `ImportError: cannot import name 'task_propose_rules'`。

- [ ] **步驟 3：寫最少的程式讓測試通過**

在 `src/training_kb/pipelines/feedback.py` 的 import 區補上：

```python
from training_kb.models import AuthoringRule
from training_kb.writing.prompts import (
    prompt_diagnose_weak,
    prompt_propose_rule,
    prompt_rewrite_steps,
)
```

（把原本的 `from training_kb.writing.prompts import prompt_diagnose_weak, prompt_rewrite_steps` 整行換掉；`AuthoringRule` 併進既有的 models import 也可以。）

在 `task_diagnose` 前面（順序不影響執行，放這裡是為了對齊設計文件 §7.5 的節點順序）加入：

```python
def _feedback_by_category(state: dict, deps: Deps) -> dict[str, list[Feedback]]:
    """把該版有效回饋依核定類別分組；待分類與未核定的值不分組。"""
    allow = set(state.get("approved_categories") or APPROVED_CATEGORIES_DEFAULT)
    groups: dict[str, list[Feedback]] = {}
    for item in deps.repo.list_feedback_of_version(state["version_id"]):
        if not is_valid_feedback(item):
            continue
        category = item.category
        if category is None or category == PENDING_CATEGORY or category not in allow:
            continue
        groups.setdefault(category, []).append(item)
    return groups


def task_propose_rules(state: dict, deps: Deps) -> dict:
    """同版同類至少五筆就提出 candidate 規則。

    F26：不必先達弱教學門檻。F25：只在同一個 TutorialVersion 內累積。
    F27：一律存成 candidate，一般寫作不會取用。
    """
    version_id = state["version_id"]
    min_count = deps.settings.thresholds.category_min_count
    counts = state.get("category_counts") or {}
    eligible = sorted(
        [(category, n) for category, n in counts.items() if n >= min_count],
        key=lambda pair: (-pair[1], pair[0]),
    )
    if not eligible:
        return {**state, "proposed_rule_ids": [], "proposal_skipped_categories": []}

    groups = _feedback_by_category(state, deps)
    steps = deps.repo.get_steps(version_id)
    already = proposed_evidence_keys(deps.repo, version_id)
    operation_id = state.get("review_operation_id") or f"propose:{version_id}"

    proposed: list[str] = []
    skipped: list[str] = []
    for category, _count in eligible:
        items = groups.get(category, [])
        evidence_ids = sorted(item.id for item in items)
        if proposal_evidence_key(version_id, evidence_ids) in already:
            skipped.append(category)
            continue

        system, user = prompt_propose_rule(items, steps)
        proposal = deps.writer.generate_json(
            system=system,
            user=user,
            schema=RuleProposal,
            operation_id=operation_id,
            node="propose_rules",
            max_tokens=deps.settings.gen_max_tokens_judgement,
            temperature=deps.settings.gen_temperature,
        )
        evidence, applies_when = validate_rule_proposal(
            proposal,
            version_id=version_id,
            evidence_ids=evidence_ids,
            min_count=min_count,
        )
        stored_key = proposal_evidence_key(version_id, evidence)
        if stored_key in already:
            skipped.append(category)
            continue

        rule_id = f"R-{deps.repo.next_counter('rule'):03d}"
        deps.repo.put_rule(
            AuthoringRule(
                rule_id=rule_id,
                rule=proposal.rule.strip(),
                applies_when=applies_when,
                evidence=evidence,
                status=RuleStatus.candidate,
                applied_to=[],
                derived_from=version_id,
                validated_at=None,
            )
        )
        already.add(stored_key)
        already.add(proposal_evidence_key(version_id, evidence_ids))
        proposed.append(rule_id)

    return {
        **state,
        "proposed_rule_ids": proposed,
        "proposal_skipped_categories": skipped,
    }
```

最後把檔案結尾的 `TASKS` 字典換成：

```python
TASKS: dict[str, TaskFn] = {
    "list_targets": task_list_targets,
    "collect": task_collect,
    "propose_rules": task_propose_rules,
    "diagnose": task_diagnose,
    "refine": task_refine,
    "publish": task_publish,
}
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：

```bash
uv run pytest tests/unit/test_pipelines_feedback.py -v
uv run ruff check src/training_kb/pipelines/feedback.py
```

預期：pytest 全綠（注意 Phase 17 的 `test_tasks_registry_has_phase17_tasks` 會失敗，因為 `TASKS` 現在多了一項）。把那一個測試改成：

```python
def test_tasks_registry_has_phase17_tasks():
    assert {"list_targets", "collect", "diagnose", "refine", "publish"}.issubset(set(TASKS))
    assert set(TASKS).issubset(set(TASK_ORDER))
```

改完再跑一次，預期全綠；ruff 顯示 `All checks passed!`。

- [ ] **步驟 5：commit**

```bash
git add src/training_kb/pipelines/feedback.py tests/unit/test_pipelines_feedback.py
git commit -m "feat(feedback): 加入 propose_rules 並登記進 TASKS"
```

---

### Task 5：feedback-review 的 ASL 流程定義

**目的**：把六個 task 寫成 Step Functions 看得懂的 JSON，Map 每篇教學，Map 完成後才集中發布。

**檔案**：
- 新增：`infra/asl/feedback-review.asl.json`
- 測試：`tests/unit/test_asl_feedback_review.py`

**介面**：
- 消費：`handlers.pipeline_task.handler`（Phase 14；事件格式 `{"pipeline", "task", "state"}`）、`pipelines.feedback.TASK_ORDER`（Phase 17）
- 產出：`infra/asl/feedback-review.asl.json`（供 Task 6 的 CDK 讀取；`${PipelineTaskFunctionArn}` 由 `definition_substitutions` 代換）

- [ ] **步驟 1：寫測試**

建立 `tests/unit/test_asl_feedback_review.py`：

```python
"""Phase 18：feedback-review 的 ASL 結構檢查（純 JSON，不需要 AWS 或 Node）。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from training_kb.pipelines.feedback import TASK_ORDER

ASL_PATH = Path(__file__).resolve().parents[2] / "infra" / "asl" / "feedback-review.asl.json"


@pytest.fixture(scope="module")
def asl() -> dict:
    return json.loads(ASL_PATH.read_text(encoding="utf-8"))


def all_task_states(asl: dict) -> dict[str, dict]:
    """收集最外層與 Map 內部的所有 Task state。"""
    found: dict[str, dict] = {}
    for name, state in asl["States"].items():
        if state["Type"] == "Task":
            found[name] = state
        if state["Type"] == "Map":
            for inner_name, inner in state["ItemProcessor"]["States"].items():
                if inner["Type"] == "Task":
                    found[inner_name] = inner
    return found


def test_state_machine_starts_with_list_targets(asl):
    assert asl["StartAt"] == "ListTargets"
    assert asl["States"]["ListTargets"]["Type"] == "Task"


def test_every_task_invokes_the_shared_pipeline_lambda(asl):
    for name, state in all_task_states(asl).items():
        assert state["Resource"] == "arn:aws:states:::lambda:invoke", name
        assert state["Parameters"]["FunctionName"] == "${PipelineTaskFunctionArn}", name
        assert state["Parameters"]["Payload"]["pipeline"] == "feedback", name
        assert state["Parameters"]["Payload"]["state.$"] == "$", name
        assert state["OutputPath"] == "$.Payload", name


def test_every_task_name_is_declared_in_task_order(asl):
    used = {state["Parameters"]["Payload"]["task"] for state in all_task_states(asl).values()}
    assert used == set(TASK_ORDER)


def test_every_task_has_retry_and_catch(asl):
    for name, state in all_task_states(asl).items():
        retry = state["Retry"]
        assert retry[0]["ErrorEquals"] == ["TransientError"], name
        assert retry[0]["IntervalSeconds"] == 1, name
        assert retry[0]["MaxAttempts"] == 2, name
        assert retry[0]["BackoffRate"] == 2, name
        assert state["Catch"][0]["ErrorEquals"] == ["States.ALL"], name
        assert state["TimeoutSeconds"] == 120, name


def test_map_runs_inline_over_targets(asl):
    node = asl["States"]["ReviewEachTutorial"]
    assert node["Type"] == "Map"
    assert node["ItemProcessor"]["ProcessorConfig"]["Mode"] == "INLINE"
    assert node["ItemsPath"] == "$.targets"
    assert node["MaxConcurrency"] == 1
    assert node["ResultPath"] == "$.items"
    assert node["ItemSelector"]["run_id.$"] == "$$.Execution.Name"
    assert node["ItemSelector"]["policy.$"] == "$.policy"
    assert node["ItemSelector"]["slug.$"] == "$$.Map.Item.Value.slug"
    assert node["ItemSelector"]["version_id.$"] == "$$.Map.Item.Value.version_id"


def test_map_inner_order_follows_design_7_5(asl):
    inner = asl["States"]["ReviewEachTutorial"]["ItemProcessor"]
    assert inner["StartAt"] == "Collect"
    states = inner["States"]
    assert states["Collect"]["Next"] == "ProposeRules"
    assert states["ProposeRules"]["Next"] == "Diagnose"
    assert states["Diagnose"]["Next"] == "NeedRefine"


def test_choice_branches_on_action(asl):
    choice = asl["States"]["ReviewEachTutorial"]["ItemProcessor"]["States"]["NeedRefine"]
    assert choice["Type"] == "Choice"
    assert choice["Choices"] == [
        {"Variable": "$.action", "StringEquals": "REFINE", "Next": "Refine"}
    ]
    assert choice["Default"] == "NoNewVersion"


def test_inner_failures_stay_inside_the_map(asl):
    inner = asl["States"]["ReviewEachTutorial"]["ItemProcessor"]["States"]
    assert inner["ItemFailed"]["Type"] == "Fail"
    for name in ("Collect", "ProposeRules", "Diagnose", "Refine"):
        assert inner[name]["Catch"][0]["Next"] == "ItemFailed", name


def test_publish_runs_after_the_map(asl):
    assert asl["States"]["ReviewEachTutorial"]["Next"] == "PublishAll"
    publish = asl["States"]["PublishAll"]
    assert publish["Parameters"]["Payload"]["task"] == "publish"
    assert publish["End"] is True


def test_pipeline_failed_is_a_fail_state(asl):
    failed = asl["States"]["PipelineFailed"]
    assert failed["Type"] == "Fail"
    assert failed["Error"] == "FeedbackReviewFailed"
    for name in ("ListTargets", "ReviewEachTutorial", "PublishAll"):
        assert asl["States"][name]["Catch"][0]["Next"] == "PipelineFailed", name
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：

```bash
uv run pytest tests/unit/test_asl_feedback_review.py -v
```

預期：FAIL，錯誤訊息是 `FileNotFoundError: ... infra/asl/feedback-review.asl.json`。

- [ ] **步驟 3：寫最少的程式讓測試通過**

建立 `infra/asl/feedback-review.asl.json`：

```json
{
  "Comment": "Periodic Feedback Review：每日挑弱教學做 REFINE，並從同版同類回饋提出 candidate 規則（設計文件 7.5）。",
  "StartAt": "ListTargets",
  "TimeoutSeconds": 1800,
  "States": {
    "ListTargets": {
      "Type": "Task",
      "Resource": "arn:aws:states:::lambda:invoke",
      "TimeoutSeconds": 120,
      "Parameters": {
        "FunctionName": "${PipelineTaskFunctionArn}",
        "Payload": {
          "pipeline": "feedback",
          "task": "list_targets",
          "state.$": "$"
        }
      },
      "OutputPath": "$.Payload",
      "Retry": [
        {
          "ErrorEquals": ["TransientError"],
          "IntervalSeconds": 1,
          "MaxAttempts": 2,
          "BackoffRate": 2
        }
      ],
      "Catch": [
        {
          "ErrorEquals": ["States.ALL"],
          "Next": "PipelineFailed"
        }
      ],
      "Next": "ReviewEachTutorial"
    },
    "ReviewEachTutorial": {
      "Type": "Map",
      "ItemsPath": "$.targets",
      "MaxConcurrency": 1,
      "ResultPath": "$.items",
      "ItemSelector": {
        "run_id.$": "$$.Execution.Name",
        "policy.$": "$.policy",
        "slug.$": "$$.Map.Item.Value.slug",
        "version_id.$": "$$.Map.Item.Value.version_id"
      },
      "ItemProcessor": {
        "ProcessorConfig": {
          "Mode": "INLINE"
        },
        "StartAt": "Collect",
        "States": {
          "Collect": {
            "Type": "Task",
            "Resource": "arn:aws:states:::lambda:invoke",
            "TimeoutSeconds": 120,
            "Parameters": {
              "FunctionName": "${PipelineTaskFunctionArn}",
              "Payload": {
                "pipeline": "feedback",
                "task": "collect",
                "state.$": "$"
              }
            },
            "OutputPath": "$.Payload",
            "Retry": [
              {
                "ErrorEquals": ["TransientError"],
                "IntervalSeconds": 1,
                "MaxAttempts": 2,
                "BackoffRate": 2
              }
            ],
            "Catch": [
              {
                "ErrorEquals": ["States.ALL"],
                "Next": "ItemFailed"
              }
            ],
            "Next": "ProposeRules"
          },
          "ProposeRules": {
            "Type": "Task",
            "Resource": "arn:aws:states:::lambda:invoke",
            "TimeoutSeconds": 120,
            "Parameters": {
              "FunctionName": "${PipelineTaskFunctionArn}",
              "Payload": {
                "pipeline": "feedback",
                "task": "propose_rules",
                "state.$": "$"
              }
            },
            "OutputPath": "$.Payload",
            "Retry": [
              {
                "ErrorEquals": ["TransientError"],
                "IntervalSeconds": 1,
                "MaxAttempts": 2,
                "BackoffRate": 2
              }
            ],
            "Catch": [
              {
                "ErrorEquals": ["States.ALL"],
                "Next": "ItemFailed"
              }
            ],
            "Next": "Diagnose"
          },
          "Diagnose": {
            "Type": "Task",
            "Resource": "arn:aws:states:::lambda:invoke",
            "TimeoutSeconds": 120,
            "Parameters": {
              "FunctionName": "${PipelineTaskFunctionArn}",
              "Payload": {
                "pipeline": "feedback",
                "task": "diagnose",
                "state.$": "$"
              }
            },
            "OutputPath": "$.Payload",
            "Retry": [
              {
                "ErrorEquals": ["TransientError"],
                "IntervalSeconds": 1,
                "MaxAttempts": 2,
                "BackoffRate": 2
              }
            ],
            "Catch": [
              {
                "ErrorEquals": ["States.ALL"],
                "Next": "ItemFailed"
              }
            ],
            "Next": "NeedRefine"
          },
          "NeedRefine": {
            "Type": "Choice",
            "Choices": [
              {
                "Variable": "$.action",
                "StringEquals": "REFINE",
                "Next": "Refine"
              }
            ],
            "Default": "NoNewVersion"
          },
          "Refine": {
            "Type": "Task",
            "Resource": "arn:aws:states:::lambda:invoke",
            "TimeoutSeconds": 120,
            "Parameters": {
              "FunctionName": "${PipelineTaskFunctionArn}",
              "Payload": {
                "pipeline": "feedback",
                "task": "refine",
                "state.$": "$"
              }
            },
            "OutputPath": "$.Payload",
            "Retry": [
              {
                "ErrorEquals": ["TransientError"],
                "IntervalSeconds": 1,
                "MaxAttempts": 2,
                "BackoffRate": 2
              }
            ],
            "Catch": [
              {
                "ErrorEquals": ["States.ALL"],
                "Next": "ItemFailed"
              }
            ],
            "End": true
          },
          "NoNewVersion": {
            "Type": "Pass",
            "Comment": "未達門檻、本批證據已處理過，或診斷沒有有效步驟；本次不建立版本。",
            "End": true
          },
          "ItemFailed": {
            "Type": "Fail",
            "Error": "TutorialReviewFailed",
            "Cause": "單篇教學的檢視失敗；INLINE Map 會因此讓整個 Map 失敗，後面的集中發布不會執行。"
          }
        }
      },
      "Retry": [
        {
          "ErrorEquals": ["TransientError"],
          "IntervalSeconds": 1,
          "MaxAttempts": 2,
          "BackoffRate": 2
        }
      ],
      "Catch": [
        {
          "ErrorEquals": ["States.ALL"],
          "Next": "PipelineFailed"
        }
      ],
      "Next": "PublishAll"
    },
    "PublishAll": {
      "Type": "Task",
      "Resource": "arn:aws:states:::lambda:invoke",
      "TimeoutSeconds": 120,
      "Parameters": {
        "FunctionName": "${PipelineTaskFunctionArn}",
        "Payload": {
          "pipeline": "feedback",
          "task": "publish",
          "state.$": "$"
        }
      },
      "OutputPath": "$.Payload",
      "Retry": [
        {
          "ErrorEquals": ["TransientError"],
          "IntervalSeconds": 1,
          "MaxAttempts": 2,
          "BackoffRate": 2
        }
      ],
      "Catch": [
        {
          "ErrorEquals": ["States.ALL"],
          "Next": "PipelineFailed"
        }
      ],
      "End": true
    },
    "PipelineFailed": {
      "Type": "Fail",
      "Error": "FeedbackReviewFailed",
      "Cause": "整次 Feedback Review 以失敗結束，沒有任何版本上架（F49）。"
    }
  }
}
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：

```bash
uv run pytest tests/unit/test_asl_feedback_review.py -v
uv run python -c "import json,pathlib; json.loads(pathlib.Path('infra/asl/feedback-review.asl.json').read_text(encoding='utf-8')); print('JSON ok')"
```

預期：pytest 顯示 10 個測試全綠；第二行印出 `JSON ok`。

- [ ] **步驟 5：commit**

```bash
git add infra/asl/feedback-review.asl.json tests/unit/test_asl_feedback_review.py
git commit -m "feat(infra): 加入 feedback-review 的 ASL 流程定義"
```

---

### Task 6：在 app_stack 加入第三條 state machine

**目的**：把上一個 Task 的 ASL 檔部署成名稱為 `training-kb-feedback-review` 的 Step Functions state machine，並授權它呼叫 pipeline task Lambda。

**檔案**：
- 修改：`infra/stacks/app_stack.py`
- 測試：`tests/unit/test_infra_feedback_review.py`

**介面**：
- 消費：Phase 14 在 `TrainingKbAppStack.__init__` 建立的區域變數 `pipeline_task_fn`（Lambda `training-kb-pipeline-task`）、Phase 14 訂的代換名稱 `PipelineTaskFunctionArn`、Phase 14 的路徑常數寫法（`TICKET_ASL = "infra/asl/ticket-analysis.asl.json"`）
- 產出：
  - `infra/stacks/app_stack.py` 的模組常數 `FEEDBACK_ASL = "infra/asl/feedback-review.asl.json"`
  - `TrainingKbAppStack.feedback_review_sm`（`aws_stepfunctions.StateMachine`，名稱 `training-kb-feedback-review`）

- [ ] **步驟 1：寫測試**

建立 `tests/unit/test_infra_feedback_review.py`：

```python
"""Phase 18：檢查 cdk synth 產生的 CloudFormation 範本。

先執行：npx aws-cdk@2 synth TrainingKbAppStack
沒有範本時整個檔案會被跳過，不會讓 CI 假綠。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

TEMPLATE_PATH = (
    Path(__file__).resolve().parents[2] / "cdk.out" / "TrainingKbAppStack.template.json"
)

pytestmark = pytest.mark.skipif(
    not TEMPLATE_PATH.exists(),
    reason="請先執行 npx aws-cdk@2 synth TrainingKbAppStack 產生 CloudFormation 範本",
)


@pytest.fixture(scope="module")
def template() -> dict:
    return json.loads(TEMPLATE_PATH.read_text(encoding="utf-8"))


def resources_of_type(template: dict, kind: str) -> list[dict]:
    return [r for r in template["Resources"].values() if r["Type"] == kind]


def test_feedback_review_state_machine_exists(template):
    machines = resources_of_type(template, "AWS::StepFunctions::StateMachine")
    names = [m["Properties"].get("StateMachineName") for m in machines]
    assert "training-kb-feedback-review" in names


def test_three_state_machines_are_deployed(template):
    machines = resources_of_type(template, "AWS::StepFunctions::StateMachine")
    names = sorted(m["Properties"].get("StateMachineName") for m in machines)
    assert names == [
        "training-kb-feedback-review",
        "training-kb-release-update",
        "training-kb-ticket-analysis",
    ]


def test_feedback_review_is_standard_type(template):
    machines = resources_of_type(template, "AWS::StepFunctions::StateMachine")
    target = next(
        m for m in machines
        if m["Properties"].get("StateMachineName") == "training-kb-feedback-review"
    )
    assert target["Properties"].get("StateMachineType", "STANDARD") == "STANDARD"


def test_feedback_review_definition_substitutes_lambda_arn(template):
    machines = resources_of_type(template, "AWS::StepFunctions::StateMachine")
    target = next(
        m for m in machines
        if m["Properties"].get("StateMachineName") == "training-kb-feedback-review"
    )
    assert "DefinitionSubstitutions" in target["Properties"]
    # 代換名稱沿用 Phase 14 訂的 PipelineTaskFunctionArn，三條流程一致。
    assert "PipelineTaskFunctionArn" in target["Properties"]["DefinitionSubstitutions"]
```

- [ ] **步驟 2：跑測試，確認它失敗**

先確保範本是最新的，再跑測試：

```bash
npx aws-cdk@2 synth TrainingKbAppStack > /dev/null
uv run pytest tests/unit/test_infra_feedback_review.py -v
```

預期：FAIL。`test_feedback_review_state_machine_exists` 會顯示 `assert 'training-kb-feedback-review' in ['training-kb-ticket-analysis', 'training-kb-release-update']`，因為第三條 state machine 還沒建立。

- [ ] **步驟 3：寫最少的程式讓測試通過**

Phase 14 在 `infra/stacks/app_stack.py` 的檔案最上面放了一組路徑常數，長這樣：

```python
SRC_DIR = "src"
LAYER_DIR = "build/layer"
TICKET_ASL = "infra/asl/ticket-analysis.asl.json"
```

在 `TICKET_ASL` 下面補一行（Phase 16 應該已經加了 `RELEASE_ASL`，有的話就接在它後面）：

```python
FEEDBACK_ASL = "infra/asl/feedback-review.asl.json"
```

接著在 `TrainingKbAppStack.__init__` 裡，**建立完前兩條 state machine 之後**加入這一段。它用的 `pipeline_task_fn` 就是 Phase 14 在同一個 `__init__` 裡建立的區域變數：

```python
        # 第三條 state machine：Periodic Feedback Review（設計文件 §7.5）。
        feedback_machine = sfn.StateMachine(
            self,
            "FeedbackReview",
            state_machine_name="training-kb-feedback-review",
            state_machine_type=sfn.StateMachineType.STANDARD,
            definition_body=sfn.DefinitionBody.from_file(FEEDBACK_ASL),
            definition_substitutions={
                "PipelineTaskFunctionArn": pipeline_task_fn.function_arn
            },
            timeout=Duration.minutes(30),
            comment="Periodic Feedback Review（每日弱教學檢視與候選規則）",
        )
        # 用 from_file 定義的流程，CDK 推不出需要的權限，必須明確授權。
        pipeline_task_fn.grant_invoke(feedback_machine)
        self.feedback_review_sm = feedback_machine
```

`sfn`、`Duration` 在 Phase 14 就已經 import 了（`from aws_cdk import Duration`、`from aws_cdk import aws_stepfunctions as sfn`），不用再加。最後一行把 state machine 存成屬性，Task 7 的排程會用到它。

> 若你的 Phase 14 把 pipeline task Lambda 存成別的變數名（例如 `task_fn`），上面這段裡的 `pipeline_task_fn` 有兩處（`definition_substitutions` 與 `grant_invoke`）要一起換成那個名稱。用 `grep -n "training-kb-pipeline-task" infra/stacks/app_stack.py` 就能找到它是哪一個變數。

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：

```bash
npx aws-cdk@2 synth TrainingKbAppStack > /dev/null
uv run pytest tests/unit/test_infra_feedback_review.py -v
```

預期：PASS，4 個測試全綠。

- [ ] **步驟 5：commit**

```bash
git add infra/stacks/app_stack.py tests/unit/test_infra_feedback_review.py
git commit -m "feat(infra): 部署 training-kb-feedback-review state machine"
```

---

### Task 7：每日排程與 Demo 手動觸發

**目的**：用 EventBridge Scheduler 每天 00:30 UTC 啟動上面那條流程，輸入 `{"policy": "formal"}`；同時準備 Demo 用的手動觸發指令，輸入 `{"policy": "demo"}`。

**檔案**：
- 修改：`infra/stacks/app_stack.py`
- 修改：`tests/unit/test_infra_feedback_review.py`

**介面**：
- 消費：Task 6 在 `__init__` 建立的 `feedback_machine`（同時存成 `TrainingKbAppStack.feedback_review_sm`）
- 產出：
  - `TrainingKbAppStack.feedback_review_scheduler_role`（`aws_iam.Role`，信任 `scheduler.amazonaws.com`，被授權 `states:StartExecution`）
  - `AWS::Scheduler::Schedule` 資源 `training-kb-feedback-review-daily`
  - `CfnOutput` `FeedbackReviewStateMachineArn`（給 Demo 手動觸發用）

- [ ] **步驟 1：寫測試**

在 `tests/unit/test_infra_feedback_review.py` 最後加入：

```python
def test_daily_schedule_runs_at_00_30_utc(template):
    schedules = resources_of_type(template, "AWS::Scheduler::Schedule")
    assert len(schedules) == 1
    props = schedules[0]["Properties"]
    assert props["ScheduleExpression"] == "cron(30 0 * * ? *)"
    assert props["ScheduleExpressionTimezone"] == "UTC"
    assert props["State"] == "ENABLED"
    assert props["FlexibleTimeWindow"]["Mode"] == "OFF"


def test_daily_schedule_sends_formal_policy(template):
    props = resources_of_type(template, "AWS::Scheduler::Schedule")[0]["Properties"]
    assert json.loads(props["Target"]["Input"]) == {"policy": "formal"}


def test_scheduler_role_is_trusted_by_scheduler_service(template):
    roles = resources_of_type(template, "AWS::IAM::Role")
    principals = [
        statement["Principal"].get("Service")
        for role in roles
        for statement in role["Properties"]["AssumeRolePolicyDocument"]["Statement"]
    ]
    assert "scheduler.amazonaws.com" in principals


def test_scheduler_role_can_start_execution(template):
    policies = resources_of_type(template, "AWS::IAM::Policy")
    actions = [
        statement["Action"]
        for policy in policies
        for statement in policy["Properties"]["PolicyDocument"]["Statement"]
    ]
    flat: list[str] = []
    for action in actions:
        flat.extend(action if isinstance(action, list) else [action])
    assert "states:StartExecution" in flat


def test_state_machine_arn_is_exported_for_manual_trigger(template):
    outputs = template.get("Outputs", {})
    assert "FeedbackReviewStateMachineArn" in outputs
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：

```bash
npx aws-cdk@2 synth TrainingKbAppStack > /dev/null
uv run pytest tests/unit/test_infra_feedback_review.py -v
```

預期：FAIL。`test_daily_schedule_runs_at_00_30_utc` 會顯示 `assert 0 == 1`，因為範本裡還沒有 `AWS::Scheduler::Schedule`。

- [ ] **步驟 3：寫最少的程式讓測試通過**

在 `infra/stacks/app_stack.py` 的 import 區補上（已有的不用重複；`iam` 在 Phase 14 就 import 過了）：

```python
import json

from aws_cdk import CfnOutput
from aws_cdk import aws_iam as iam
from aws_cdk import aws_scheduler as scheduler
```

接著在 `TrainingKbAppStack.__init__` 裡、Task 6 那一段的正下方加入：

```python
        # EventBridge Scheduler 每日 00:30 UTC 啟動 Feedback Review（設計文件 §14.3）。
        # Demo 走同一條 state machine，只是手動送 {"policy": "demo"}，
        # 正式門檻完全不變（F20）。
        scheduler_role = iam.Role(
            self,
            "FeedbackReviewSchedulerRole",
            assumed_by=iam.ServicePrincipal("scheduler.amazonaws.com"),
            description="讓 EventBridge Scheduler 啟動 training-kb-feedback-review",
        )
        # 只授權啟動這一條 state machine，不給其他流程的權限。
        feedback_machine.grant_start_execution(scheduler_role)
        self.feedback_review_scheduler_role = scheduler_role

        scheduler.CfnSchedule(
            self,
            "FeedbackReviewDailySchedule",
            name="training-kb-feedback-review-daily",
            description="每日 00:30 UTC 執行 Periodic Feedback Review",
            schedule_expression="cron(30 0 * * ? *)",
            schedule_expression_timezone="UTC",
            state="ENABLED",
            flexible_time_window=scheduler.CfnSchedule.FlexibleTimeWindowProperty(
                mode="OFF"
            ),
            target=scheduler.CfnSchedule.TargetProperty(
                arn=feedback_machine.state_machine_arn,
                role_arn=scheduler_role.role_arn,
                input=json.dumps({"policy": "formal"}, ensure_ascii=False),
                retry_policy=scheduler.CfnSchedule.RetryPolicyProperty(
                    maximum_event_age_in_seconds=3600,
                    maximum_retry_attempts=2,
                ),
            ),
        )

        CfnOutput(
            self,
            "FeedbackReviewStateMachineArn",
            value=feedback_machine.state_machine_arn,
            description='Demo 手動觸發用；input 改成 {"policy": "demo"}',
        )
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：

```bash
npx aws-cdk@2 synth TrainingKbAppStack > /dev/null
uv run pytest tests/unit/test_infra_feedback_review.py -v
```

預期：PASS，9 個測試全綠。

接著確認 Demo 手動觸發的指令可以組出來（這一步只看輸出，不真的部署）：

```bash
npx aws-cdk@2 synth TrainingKbAppStack 2>/dev/null \
  | grep -A 3 "FeedbackReviewStateMachineArn"
```

預期：看到這個 Output 的定義。部署之後，Demo 當天用下面兩行取得 ARN 並手動觸發：

```bash
SM_ARN=$(aws cloudformation describe-stacks \
  --stack-name TrainingKbAppStack \
  --query "Stacks[0].Outputs[?OutputKey=='FeedbackReviewStateMachineArn'].OutputValue" \
  --output text)

aws stepfunctions start-execution \
  --state-machine-arn "$SM_ARN" \
  --name "demo-review-$(date -u +%Y%m%dT%H%M%SZ)" \
  --input '{"policy":"demo"}'
```

預期：回傳一段包含 `executionArn` 與 `startDate` 的 JSON。`--name` 每次都不同，所以不會撞到 `ExecutionAlreadyExists`；正式排程用的 `{"policy":"formal"}` 完全不受影響。

- [ ] **步驟 5：commit**

```bash
git add infra/stacks/app_stack.py tests/unit/test_infra_feedback_review.py
git commit -m "feat(infra): 加入每日 00:30 UTC 排程與 Demo 手動觸發輸出"
```

---

### Task 8：本機執行器 run_review 與整批全有或全無驗證

**目的**：做一個跟 ASL 同順序的本機執行函式，給測試與 Phase 23 的 Demo 控制台用；並用它證明「一篇失敗，整次不發布」。

**檔案**：
- 修改：`src/training_kb/pipelines/feedback.py`
- 修改：`tests/unit/test_pipelines_feedback.py`

**介面**：
- 消費：`pipelines.feedback.TASKS`（Task 4）
- 產出：`pipelines.feedback.run_review(state: dict, deps: Deps) -> dict`（本階段新增；本機依序執行整條流程，順序與 `infra/asl/feedback-review.asl.json` 相同）

- [ ] **步驟 1：寫測試**

在 `tests/unit/test_pipelines_feedback.py` 最後加入：

```python
def prepare_two_tutorials(repo: FakeRepo) -> None:
    """A 會進 REFINE；B 沒有回饋，只會走 SKIP。"""
    add_tutorial(repo, "prepare-meeting", current_version="prepare-meeting@v1")
    add_version_with_steps(repo, "prepare-meeting", "prepare-meeting@v1")
    add_feedback(repo, "prepare-meeting@v1", A_V1_ROWS)

    add_tutorial(repo, "share-summary", current_version="share-summary@v1")
    repo.objects["tutorials/share-summary/v1.md"] = A_V1_MARKDOWN.encode("utf-8")
    repo.steps["share-summary@v1"] = [
        TutorialStep(tutorial_version="share-summary@v1", index=1,
                     type=StepType.click_ui, text="開啟摘要頁面。", feature_id="Prepare"),
    ]


def test_run_review_follows_the_same_order_as_the_asl(monkeypatch):
    repo = FakeRepo()
    prepare_two_tutorials(repo)
    patch_content(monkeypatch, RefineSpy())
    calls: list = []
    patch_publish(monkeypatch, PublishResultStub(["prepare-meeting@v2"]), calls)

    writer = FakeWriter(outputs=[
        RuleProposal(rule=R007_TEXT, applies_when={"step.type": "click_ui"},
                     evidence=[row[0] for row in A_V1_ROWS]),
        WeakDiagnosis(items=[DiagnosisItem(index=3, reason="沒寫按鈕位置")]),
        StepRewrite(rewrites=[StepRewriteItem(
            index=3, text=NEW_STEP_TEXT, type=StepType.click_ui, feature_id="Prepare")]),
    ])

    out = run_review({"run_id": "2026-09-14", "policy": "demo"}, make_deps(repo, writer))

    assert repo.saved_rules[0].rule_id == "R-001"
    assert repo.saved_rules[0].status == RuleStatus.candidate
    assert out["published"] == ["prepare-meeting@v2"]
    assert calls == [["prepare-meeting@v2"]]


def test_run_review_publishes_nothing_when_one_tutorial_fails(monkeypatch):
    # F49：Map 內任一篇失敗，整次執行以失敗結束，不發布新版本。
    repo = FakeRepo()
    prepare_two_tutorials(repo)
    patch_content(monkeypatch, RefineSpy())
    calls: list = []
    patch_publish(monkeypatch, PublishResultStub(["prepare-meeting@v2"]), calls)

    writer = FakeWriter(outputs=[
        RuleProposal(rule=R007_TEXT, applies_when={"step.type": "click_ui"},
                     evidence=[row[0] for row in A_V1_ROWS]),
        WeakDiagnosis(items=[DiagnosisItem(index=3, reason="沒寫按鈕位置")]),
        # 模型改了沒有命中的步驟 -> apply_step_rewrites 會拋 ContentError
        StepRewrite(rewrites=[StepRewriteItem(
            index=1, text="整篇重寫", type=StepType.click_ui, feature_id="Prepare")]),
    ])

    with pytest.raises(ContentError):
        run_review({"run_id": "2026-09-14", "policy": "demo"}, make_deps(repo, writer))

    assert calls == []  # publish 從頭到尾沒有被呼叫


def test_run_review_keeps_candidate_when_publish_fails(monkeypatch):
    # 設計文件 §7.5：失敗時「已保存的合法 candidate 不因此變成 active」。
    repo = FakeRepo()
    prepare_two_tutorials(repo)
    patch_content(monkeypatch, RefineSpy())
    calls: list = []
    patch_publish(monkeypatch, PublishResultStub([], failed="prepare-meeting@v2"), calls)

    writer = FakeWriter(outputs=[
        RuleProposal(rule=R007_TEXT, applies_when={"step.type": "click_ui"},
                     evidence=[row[0] for row in A_V1_ROWS]),
        WeakDiagnosis(items=[DiagnosisItem(index=3, reason="沒寫按鈕位置")]),
        StepRewrite(rewrites=[StepRewriteItem(
            index=3, text=NEW_STEP_TEXT, type=StepType.click_ui, feature_id="Prepare")]),
    ])

    with pytest.raises(PermanentError):
        run_review({"run_id": "2026-09-14", "policy": "demo"}, make_deps(repo, writer))

    assert repo.saved_rules[0].status == RuleStatus.candidate
    assert repo.list_rules(RuleStatus.active) == []


def test_run_review_formal_policy_does_not_refine_eight_feedback(monkeypatch):
    repo = FakeRepo()
    prepare_two_tutorials(repo)
    patch_content(monkeypatch, RefineSpy())
    calls: list = []
    patch_publish(monkeypatch, PublishResultStub([]), calls)

    writer = FakeWriter(outputs=[
        RuleProposal(rule=R007_TEXT, applies_when={"step.type": "click_ui"},
                     evidence=[row[0] for row in A_V1_ROWS]),
    ])

    out = run_review({"run_id": "2026-09-14", "policy": "formal"}, make_deps(repo, writer))

    assert out["published"] == []
    assert calls == []
    # 規則提案不受弱教學門檻影響（F26），所以 candidate 還是會產生。
    assert repo.saved_rules[0].rule_id == "R-001"
```

把 import 區的 `from training_kb.pipelines.feedback import (...)` 補上 `run_review`。

- [ ] **步驟 2：跑測試，確認它失敗**

執行：

```bash
uv run pytest tests/unit/test_pipelines_feedback.py -v
```

預期：FAIL，錯誤訊息是 `ImportError: cannot import name 'run_review'`。

- [ ] **步驟 3：寫最少的程式讓測試通過**

在 `src/training_kb/pipelines/feedback.py` 最後（`TASKS` 定義之後）加入：

```python
def run_review(state: dict, deps: Deps) -> dict:
    """在本機依序執行整條 Feedback Review，順序與 ASL 完全相同。

    節點順序：list_targets -> 每篇（collect -> propose_rules -> diagnose -> refine）
    -> 全部跑完才 publish（設計文件 §7.5、F49）。
    正式執行由 Step Functions 驅動；這個函式給測試與 Demo 控制台用。
    任何一篇拋出例外都會直接往外傳，publish 不會被呼叫。
    """
    run = TASKS["list_targets"](state, deps)
    items: list[dict] = []
    for target in run["targets"]:
        item = {
            "run_id": run.get("run_id"),
            "policy": run["policy"],
            "slug": target["slug"],
            "version_id": target["version_id"],
        }
        item = TASKS["collect"](item, deps)
        item = TASKS["propose_rules"](item, deps)
        item = TASKS["diagnose"](item, deps)
        item = TASKS["refine"](item, deps)
        items.append(item)
    return TASKS["publish"]({**run, "items": items}, deps)
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：

```bash
uv run pytest tests/unit -q
uv run ruff check .
```

預期：所有單元測試通過（`test_infra_feedback_review.py` 在沒有 `cdk.out` 時會顯示 skipped，這是預期行為）；ruff 顯示 `All checks passed!`。

- [ ] **步驟 5：commit**

```bash
git add src/training_kb/pipelines/feedback.py tests/unit/test_pipelines_feedback.py
git commit -m "feat(feedback): 加入本機 run_review 與整批全有或全無驗證"
```

---

## 7. 完成檢查清單

對應設計文件第 16 節切片 S6：「Demo 八筆走隔離門檻；REFINE 只改有效步驟；candidate 不自動進一般寫作」。

- [ ] `uv run pytest tests/unit -q` 全部通過。
- [ ] `uv run ruff check .` 沒有錯誤。
- [ ] `TASKS` 的鍵與 `TASK_ORDER` 完全相同：

```bash
uv run python -c "from training_kb.pipelines.feedback import TASKS, TASK_ORDER; print(set(TASKS) == set(TASK_ORDER), TASK_ORDER)"
```

預期：`True ('list_targets', 'collect', 'propose_rules', 'diagnose', 'refine', 'publish')`。

- [ ] ASL 的 task 名稱與 `TASK_ORDER` 完全對得上：

```bash
uv run python - <<'PY'
import json, pathlib
from training_kb.pipelines.feedback import TASK_ORDER
asl = json.loads(pathlib.Path("infra/asl/feedback-review.asl.json").read_text(encoding="utf-8"))
names = set()
for state in asl["States"].values():
    if state["Type"] == "Task":
        names.add(state["Parameters"]["Payload"]["task"])
    if state["Type"] == "Map":
        for inner in state["ItemProcessor"]["States"].values():
            if inner["Type"] == "Task":
                names.add(inner["Parameters"]["Payload"]["task"])
print(names == set(TASK_ORDER), sorted(names))
PY
```

預期：`True ['collect', 'diagnose', 'list_targets', 'propose_rules', 'publish', 'refine']`。

- [ ] `cdk synth` 出來的範本有三條 state machine 與一個排程：

```bash
npx aws-cdk@2 synth TrainingKbAppStack > /dev/null
uv run python - <<'PY'
import json, pathlib
tpl = json.loads(pathlib.Path("cdk.out/TrainingKbAppStack.template.json").read_text(encoding="utf-8"))
sm = [r["Properties"].get("StateMachineName") for r in tpl["Resources"].values()
      if r["Type"] == "AWS::StepFunctions::StateMachine"]
sc = [r["Properties"] for r in tpl["Resources"].values()
      if r["Type"] == "AWS::Scheduler::Schedule"]
print("state machines:", sorted(sm))
print("schedule:", sc[0]["ScheduleExpression"], sc[0]["ScheduleExpressionTimezone"], sc[0]["Target"]["Input"])
PY
```

預期第一行列出三個名稱；第二行是 `schedule: cron(30 0 * * ? *) UTC {"policy": "formal"}`。

- [ ] 手動確認一次候選規則的形狀：

```bash
uv run python - <<'PY'
from training_kb.models import AuthoringRule, RuleStatus
from training_kb.pipelines.feedback import proposal_evidence_key, validate_rule_proposal
from training_kb.writing.rules import select_active_rules
from training_kb.models import StepType
from training_kb.writing.schemas import RuleProposal

ids = ["f_12", "f_15", "f_19", "f_23", "f_27", "f_31", "f_34", "f_40"]
proposal = RuleProposal(rule="點擊 UI 時要寫出頁面、按鈕位置與結果",
                        applies_when={"step.type": "click_ui"}, evidence=ids)
evidence, applies_when = validate_rule_proposal(
    proposal, version_id="prepare-meeting@v1", evidence_ids=ids, min_count=5)
rule = AuthoringRule(rule_id="R-001", rule=proposal.rule, applies_when=applies_when,
                     evidence=evidence, status=RuleStatus.candidate, applied_to=[],
                     derived_from="prepare-meeting@v1", validated_at=None)
print("evidence 筆數：", len(rule.evidence))
print("candidate 是否會進一般寫作：", select_active_rules([rule], StepType.click_ui) != [])
print("指紋：", proposal_evidence_key("prepare-meeting@v1", rule.evidence))
PY
```

預期：`evidence 筆數： 8`、`candidate 是否會進一般寫作： False`、一個 16 位十六進位指紋。

- [ ] 部署後（Demo 前一天）確認排程真的存在：

```bash
aws scheduler get-schedule --name training-kb-feedback-review-daily \
  --query "{expr:ScheduleExpression, tz:ScheduleExpressionTimezone, state:State, input:Target.Input}"
```

預期：`expr` 是 `cron(30 0 * * ? *)`、`tz` 是 `UTC`、`state` 是 `ENABLED`、`input` 是 `{"policy": "formal"}`。

- [ ] Demo 結束後，依設計文件 §17.3 由維護者停用排程：

```bash
aws scheduler update-schedule --name training-kb-feedback-review-daily --state DISABLED \
  --schedule-expression 'cron(30 0 * * ? *)' \
  --schedule-expression-timezone UTC \
  --flexible-time-window '{"Mode":"OFF"}' \
  --target "$(aws scheduler get-schedule --name training-kb-feedback-review-daily --query Target --output json)"
```

預期：回傳含 `ScheduleArn` 的 JSON。這一步屬於 Phase 25（`25-Phase25-安全檢查與Demo當日準備.md`）的結束後停用清單，這裡先把指令記下來。

---

## 8. 常見錯誤與排除

**錯誤 1：`uv run pytest tests/unit/test_infra_feedback_review.py` 全部顯示 skipped**

- 症狀：測試沒有紅也沒有綠，只有 `s`。
- 原因：`cdk.out/TrainingKbAppStack.template.json` 不存在。這個測試檔刻意設計成「沒有範本就跳過」，避免在沒裝 Node 的機器上誤報失敗。
- 解法：先跑 `npx aws-cdk@2 synth TrainingKbAppStack`，再跑測試。每次改完 `app_stack.py` 都要重新 synth，否則測到的是舊範本。

**錯誤 2：`Error: Parameter validation failed: Invalid cron expression`**

- 症狀：部署時 EventBridge Scheduler 拒絕 cron 表達式。
- 原因：EventBridge Scheduler 的 cron 有**六個欄位**（分 時 日 月 星期 年），而且「日」與「星期」不能同時是 `*`。寫成 Unix 五欄的 `cron(30 0 * * *)` 或 `cron(30 0 * * * *)`（星期用 `*`）都會失敗。
- 解法：用 `cron(30 0 * * ? *)`。第五欄的 `?` 代表「星期任何值」。來源：[Schedule types in EventBridge Scheduler](https://docs.aws.amazon.com/scheduler/latest/UserGuide/schedule-types.html)。

**錯誤 3：排程觸發了，但 Step Functions 執行顯示 `States.Permissions`**

- 症狀：CloudWatch 看得到 Scheduler 有動作，Step Functions 卻沒有新的執行紀錄，或執行馬上失敗。
- 原因：執行角色沒有 `states:StartExecution`，或角色的信任政策不是 `scheduler.amazonaws.com`。
- 解法：確認 `_add_feedback_review_schedule` 裡有 `self.feedback_review_sm.grant_start_execution(self.feedback_review_scheduler_role)`，而且角色用的是 `iam.ServicePrincipal("scheduler.amazonaws.com")`。用 `test_scheduler_role_can_start_execution` 與 `test_scheduler_role_is_trusted_by_scheduler_service` 驗證。來源：[Setting up an execution role](https://docs.aws.amazon.com/scheduler/latest/UserGuide/setting-up.html#setting-up-execution-role)。

**錯誤 4：Task 失敗時沒有重試，直接進 PipelineFailed**

- 症狀：程式明明拋的是 `TransientError`，執行紀錄卻只看到一次嘗試。
- 原因：Step Functions 看到的錯誤名稱不一定等於 Python 的例外類別名稱。AWS 文件註記：「Unhandled errors in Lambda runtimes were historically reported only as `Lambda.Unknown`.」
- 解法：用下面這個指令看實際的錯誤名稱，再決定要不要在 ASL 的第一個 retrier 的 `ErrorEquals` 陣列裡補上看到的名稱（例如改成 `["TransientError", "Lambda.Unknown"]`）：

```bash
aws stepfunctions get-execution-history --execution-arn "<執行 ARN>" \
  --query "events[?type=='TaskFailed'].taskFailedEventDetails.[error,cause]" --output table
```

本階段的 `Retry` 刻意只寫 `["TransientError"]` 一組，跟 Phase 14 的 `ticket-analysis.asl.json` 完全一致；三條流程的錯誤處理保持同一個形狀，改的時候三個檔案要一起改。AWS 的最佳實務另外建議把 `Lambda.ServiceException`、`Lambda.AWSLambdaException`、`Lambda.SdkClientException`、`Lambda.TooManyRequestsException` 也列成可重試的暫時性錯誤；要不要加、加在哪三個檔案，由 Phase 24（`24-Phase24-失敗復原與重送驗收.md`）以實際部署觀察到的錯誤名稱一併決定。來源：[Handling errors in Step Functions workflows](https://docs.aws.amazon.com/step-functions/latest/dg/concepts-error-handling.html)、[Handle transient Lambda service exceptions](https://docs.aws.amazon.com/step-functions/latest/dg/bp-lambda-serviceexception.html)。

**錯誤 5：`States.Runtime` 且訊息提到 `$.policy`**

- 症狀：Map 節點一開始就失敗，錯誤是 `States.Runtime`，cause 提到找不到路徑。
- 原因：`ItemSelector` 的 `"policy.$": "$.policy"` 要求輸入一定有 `policy` 欄位。手動觸發時如果 `--input` 給的是 `{}`，這個路徑就解析不出來。
- 解法：手動觸發一定要帶 `{"policy":"demo"}` 或 `{"policy":"formal"}`。`run_id` 不用帶，它取自 `$$.Execution.Name`。

**錯誤 6：`test_propose_rules_does_not_repeat_same_evidence_set` 第二次還是產生規則**

- 症狀：連跑兩次，`saved_rules` 有兩條。
- 原因：`proposed_evidence_keys` 沒有讀到剛存的規則（假 Repository 的 `put_rule` 沒有同時放進 `self.rules`），或指紋把類別也算進去，導致存進去之後算不回同一個值。
- 解法：確認 `FakeRepo.put_rule` 同時 append 到 `saved_rules` 與 `rules`；確認 `proposal_evidence_key` 只吃 `(version_id, evidence)`。

**錯誤 7：`NameError: name 'pipeline_task_fn' is not defined`**

- 症狀：`cdk synth` 在新加的 `sfn.StateMachine(...)` 那一行失敗。
- 原因：那一段被貼到 `__init__` 之外（例如貼成類別層級的方法），或 Phase 14 把 pipeline task Lambda 存成別的變數名。
- 解法：確認新程式碼貼在 `TrainingKbAppStack.__init__` 裡、而且在建立 `pipeline_task_fn` 之後；用 `grep -n "training-kb-pipeline-task" -B 6 infra/stacks/app_stack.py` 找出實際的變數名稱，把 Task 6 那一段裡的兩處 `pipeline_task_fn` 換掉。

**錯誤 8：`States.Runtime` 且 cause 提到 `${PipelineTaskFunctionArn}`**

- 症狀：部署成功，但執行時每個 Task 都說找不到函式。
- 原因：ASL 檔裡的代換名稱和 `definition_substitutions` 的鍵不一致（例如一邊寫 `PipelineTaskArn`、另一邊寫 `PipelineTaskFunctionArn`）。
- 解法：兩邊都用 Phase 14 訂的 `PipelineTaskFunctionArn`。`test_feedback_review_definition_substitutes_lambda_arn` 與 `test_every_task_invokes_the_shared_pipeline_lambda` 就是在守這一條。

**錯誤 9：部署時說 state machine 名稱已存在**

- 症狀：`CREATE_FAILED ... training-kb-feedback-review already exists`。
- 原因：之前手動在主控台建過同名的 state machine，或上一次部署失敗留下殘留資源。
- 解法：用 `aws stepfunctions list-state-machines --query "stateMachines[?name=='training-kb-feedback-review']"` 確認，再由維護者刪掉手動建立的那一個，之後只用 CDK 管理。

---

## 9. 這階段不做的事

| 不做的事 | 留給哪一階段 |
|---|---|
| 把 candidate 規則升為 active、判定衝突、退役規則 | Phase 20（`20-Phase20-規則驗證與狀態轉換.md`）。只有 Analytics 能寫 `status` 與 `validated_at`（F27、§12.2）。 |
| 平均評分、負面回饋、重開票率等指標 | Phase 19（`19-Phase19-Analytics-學習指標.md`） |
| `demo/cli.py` 的 `trigger-review` 子命令與 Streamlit 控制台 | Phase 23（`23-Phase23-Demo控制台與Dashboard.md`），它會呼叫本階段的 `run_review` 或直接 StartExecution |
| 真實部署到 AWS、實際跑一次每日排程 | Phase 24（`24-Phase24-失敗復原與重送驗收.md`）與 Phase 25（`25-Phase25-安全檢查與Demo當日準備.md`） |
| 注入 S3／DynamoDB／publish 失敗，驗證舊版不變、重送不重複 | Phase 24 |
| 種子規則 `R-007`、`R-012` 的完整 JSON 與核定批次 | Phase 21（`21-Phase21-Demo種子資料與可重算驗證.md`） |
| backfill 與每日維護同批執行 | 設計文件 §14.3 說 backfill 與每日維護同批執行、保持獨立紀錄；本計劃把它放在 Phase 09 的 `backfill_references`，不加進這條 state machine，也不新增第四條 pipeline。 |
| 把 Map 換成 Distributed 模式 | 不在本計劃範圍。MVP 只有三篇教學，INLINE 模式的 40 個併發與 25,000 筆執行紀錄上限綽綽有餘。 |

---

## 10. 對照：設計章節與 Rule 編號

### 主要責任：`docs/spec/features/提出教學規則.feature`（設計文件 §20.8）

| Rule | 原文 | 本階段哪個 Task 落實 |
|---:|---|---|
| 1 | 同類 Feedback 至少 5 筆才可提出 candidate 規則 | Task 2（`min_count` 檢查）、Task 4（`counts[category] >= category_min_count`） |
| 2 | Authoring Rule 保留可追溯的 Feedback 證據 | Task 2（evidence 必須屬於該版本）、Task 4（`evidence=` 寫入去重排序後的 ID） |
| 3 | Authoring Rule 記錄 applies_when 適用範圍 | Task 2（只允許單一 `step.type` 等值）、Task 1（prompt 明講限制） |
| 4 | Authoring Rule 記錄 derived_from 來源版本 | Task 2（`_is_version_id`）、Task 4（`derived_from=version_id`） |
| 5 | Authoring Rule 記錄歸納出的寫作要求 | Task 1（`RuleProposal.rule`）、Task 2（不可空白） |
| 6 | MVP 的教學與產品功能識別碼在單一專案範圍內唯一 | Task 4（`rule_id = f"R-{next_counter('rule'):03d}"`，由原子計數器產生，不會撞號） |

### 主要責任：`docs/spec/features/定期檢視回饋.feature`（設計文件 §20.5）

| Rule | 原文 | 本階段哪個 Task 落實 |
|---:|---|---|
| 1 | Periodic Feedback Review 每日執行 | Task 7（`cron(30 0 * * ? *)` UTC） |
| 9 | Feedback Review 是唯一提出 Authoring Rule 的 pipeline | Task 4（只有 `pipelines/feedback.py` 呼叫 `put_rule` 寫 candidate）、Task 5（ASL 裡只有這條流程有 `propose_rules` 節點） |
| 2–8 | 弱教學三條件、診斷、REFINE、reason | Phase 17 已落實；Task 5 把它們接進流程 |

### 一併遵守：`docs/spec/features/執行教學流程.feature`（設計文件 §20.3）

| Rule | 原文 | 本階段哪個 Task 落實 |
|---:|---|---|
| 2 | 教學 pipeline 依 Step Functions 預定義節點執行 | Task 5、Task 6 |
| 4 | 每個 Bedrock 呼叫設定 max_tokens | Task 4（`gen_max_tokens_judgement`） |
| 6 | 每個 Step Functions Task 設定 Retry | Task 5（`test_every_task_has_retry_and_catch`） |
| 7 | 每個 Step Functions Task 設定 Catch | Task 5（外層 Catch 到 `PipelineFailed`，Map 內 Catch 到 `ItemFailed`） |
| 8 | LLM 輸出遵循指定 JSON schema | Task 1（`RuleProposal`）、Task 2（schema 通過後再做業務驗證） |
| 9 | 判斷節點使用低 temperature | Task 4（`deps.settings.gen_temperature`） |
| 10 | Step Functions 的 ASL 版本快照存於 `stepfunctions/<pipeline>/v<n>.json` | 不在本階段；Phase 14 建立的部署前快照流程沿用同一段程式，pipeline 名稱是 `feedback-review` |

### 一併遵守：`docs/spec/features/套用教學規則.feature`（設計文件 §20.4）

| Rule | 原文 | 本階段哪個 Task 落實 |
|---:|---|---|
| 2 | 一般寫作路徑只取得 status 為 active 的規則 | Task 4（`test_candidate_rule_never_enters_normal_writing` 用 Phase 06 的 `select_active_rules` 驗證） |

### 相關釐清決策

| 編號 | 內容 | 本階段落實位置 |
|---|---|---|
| D15 | evidence 只存 Feedback ID 清單，category 由被引用的回饋取得 | Task 1、Task 2、Task 3（指紋不含類別） |
| D16 | applies_when 僅支援單一 `step.type` 條件，不支援 AND／OR | Task 2 |
| D17 | 以版本的 `rules_applied` 為權威，`applied_to` 可由它重建 | Task 4（新規則 `applied_to=[]`，不自己維護） |
| D18 | `derived_from` 恰好一個裸 version_id | Task 2、Task 4 |
| F25 | 五筆同類回饋只在同一 TutorialVersion 累積；跨版 3+2 不達標 | Task 4（`test_propose_rules_does_not_accumulate_across_versions`） |
| F26 | 提出 candidate 不必先滿足弱教學門檻 | Task 4（`test_propose_rules_does_not_need_weak_threshold`） |
| F27 | 正式寫作不自動試用 candidate | Task 4（一律寫 `status=candidate`、`validated_at=None`） |
| F32 | 只在完整核定種子批次載入後才判定規則狀態 | 不在本階段；Phase 20 |
| F49 | 整次執行以失敗結束，不發布新版本 | Task 5（INLINE Map 的失敗語意）、Task 8（`test_run_review_publishes_nothing_when_one_tutorial_fails`） |
| O2（待確認） | 操作紀錄與接受順序。**本計劃選擇**：`propose:<version_id>` 作為候選規則呼叫的 trace 操作 ID | Task 4 |
| O5（待確認） | 模型與參數。Claude model ID 由 Phase 04 確認後寫入 `.env`，本階段不猜值 | Task 4 使用 `deps.settings.gen_model_id`（由 `Writer` 內部讀取） |

---

## 11. 參考來源

### 設計文件章節（`docs/design/training-kb.md`）

- §7.5 Periodic Feedback Review（提出規則的獨立條件、證據集合排序比對、publish 放最後、失敗時 candidate 不變 active）
- §7.6 共用寫作與 Analytics 的內部介面（提出規則必須由程式驗證的四件事）
- §8.3 發布與併發必須守住的界線（多篇同批任一失敗整批不切換）
- §9.1 鍵與原生型別（`RULE#<rule_id>`、`SK = META`）
- §9.3 S3 與執行資訊（`stepfunctions/<pipeline>/v<n>.json`、三條流程名稱）
- §12.2 規則驗證（只有 Analytics 能寫驗證後 status）
- §14.1 各層如何結束（Task 重試耗盡即失敗）
- §14.2 重試不是重新抽一次文字（StartExecution 冪等、Retry／Catch）
- §14.3 執行參數的建議起點（每日 Review UTC 00:30、Task 最多 120 秒、重試兩次等 1 秒 2 秒）
- §15 測試與驗收設計（「規則」列：同版五筆可提案、跨版 3+2 不可、candidate 不進一般 prompt）
- §16 交付切片 S6
- §17.1 已查證的平台用法（Step Functions Standard、EventBridge Scheduler 需明確授權目標）
- §18 待確認事項 O2、O5
- §19.1／§19.2 釐清決策 D15、D16、D17、D18、F25、F26、F27、F32、F49
- §20.3／§20.4／§20.5／§20.8 逐條 Rule 與負責模組

### 規格檔

- `docs/spec/features/提出教學規則.feature`（6 條 Rule 與 R-007 的 Example）
- `docs/spec/features/定期檢視回饋.feature`（Rule 1、Rule 9）
- `docs/spec/features/執行教學流程.feature`（Rule 2、4、6、7、8、9、10）
- `docs/spec/features/套用教學規則.feature`（Rule 2）
- `docs/spec/erm.dbml`（AUTHORING_RULE 的 `applies_when`、`evidence`、`derived_from`、`applied_to` 註解）
- `docs/spec/.clarify/resolved/features/提出教學規則_候選規則的五筆同類回饋可以跨哪些範圍累積.md`（F25 解決記錄）
- `docs/spec/.clarify/resolved/features/提出教學規則_提出_candidate_是否必須先滿足弱教學門檻.md`（F26 解決記錄）

### 外部官方文件（本階段以 Context7 MCP 與 AWS 官方文件查證，查證日期 2026-09-13）

- Map workflow state（Inline 與 Distributed 的差別）：<https://docs.aws.amazon.com/step-functions/latest/dg/state-map.html>
- Using Map state in Inline mode（`ItemProcessor`、`ProcessorConfig.Mode`、`ItemsPath`、`ItemSelector`、`MaxConcurrency`、`ResultPath`、Retry／Catch；「States within the ItemProcessor field can only transition to each other」）：<https://docs.aws.amazon.com/step-functions/latest/dg/state-map-inline.html>
- Handling errors in Step Functions workflows（Retrier／Catcher 欄位、`States.ALL`、`Lambda.Unknown` 註記）：<https://docs.aws.amazon.com/step-functions/latest/dg/concepts-error-handling.html>
- Handle transient Lambda service exceptions（`Lambda.ServiceException`、`Lambda.SdkClientException` 等應重試的例外）：<https://docs.aws.amazon.com/step-functions/latest/dg/bp-lambda-serviceexception.html>
- StartExecution API（同名同 input 的冪等行為）：<https://docs.aws.amazon.com/step-functions/latest/apireference/API_StartExecution.html>
- Using Amazon EventBridge Scheduler to start a Step Functions state machine execution：<https://docs.aws.amazon.com/step-functions/latest/dg/using-eventbridge-scheduler.html>
- Schedule types in EventBridge Scheduler（六欄 cron、`?` 萬用字元、`ScheduleExpressionTimezone`）：<https://docs.aws.amazon.com/scheduler/latest/UserGuide/schedule-types.html>
- Setting up Amazon EventBridge Scheduler（執行角色信任 `scheduler.amazonaws.com`）：<https://docs.aws.amazon.com/scheduler/latest/UserGuide/setting-up.html>
- AWS CDK Python：`aws_cdk.aws_scheduler.CfnSchedule`（`FlexibleTimeWindowProperty`、`TargetProperty`、`RetryPolicyProperty`）：<https://docs.aws.amazon.com/cdk/api/v2/python/aws_cdk.aws_scheduler/CfnSchedule.html>
- AWS CDK Python：`aws_cdk.aws_stepfunctions.StateMachine`（`definition_body`、`definition_substitutions`、`grant_start_execution`）：<https://docs.aws.amazon.com/cdk/api/v2/python/aws_cdk.aws_stepfunctions/StateMachine.html>
- AWS CDK Python：`aws_cdk.aws_stepfunctions.DefinitionBody`（`from_file`）：<https://docs.aws.amazon.com/cdk/api/v2/python/aws_cdk.aws_stepfunctions/DefinitionBody.html>
- pytest `skipif` 與 `pytestmark`：<https://docs.pytest.org/en/stable/how-to/skipping.html>
