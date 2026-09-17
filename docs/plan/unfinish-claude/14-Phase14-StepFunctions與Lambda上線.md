# Phase 14：Step Functions 與 Lambda 上線

| 項目 | 內容 |
|---|---|
| 上一階段 | Phase 13：Ticket Analysis 流程（`13-Phase13-Ticket-Analysis流程.md`） |
| 下一階段 | Phase 15：Feedback 與 View 匯入（`15-Phase15-Feedback與View匯入.md`） |
| 對應設計文件章節 | §5、§7.1、§9.3、§14.1、§14.2、§14.3、§17.1、§17.2（`docs/design/training-kb.md`） |
| 對應交付切片 | S1–S3（設計文件第 16 節） |
| 預估時間 | 約 7 小時 |
| 做完會得到 | 一個真的可以被 GitHub 打進來的 webhook 網址，以及一條在雲端跑得起來的 Ticket Analysis 流程 |

---

## 1. 這階段做完會得到什麼

前面十三個階段寫的都是「在你自己電腦上跑得起來」的函式。這一階段把它們搬上 AWS，變成三個可以被外面呼叫的入口：

1. **`training-kb-webhook`**：一個有公開網址的 Lambda。GitHub 的 Issue 與 PR 事件會直接打進來，程式先驗簽，再交給 Rote 正規化，最後啟動流程。
2. **`training-kb-import`**：沒有公開網址。維護者用自己的 AWS 登入，透過 `boto3` 呼叫它，手動上傳 Ticket 或 Release。
3. **`training-kb-pipeline-task`**：Step Functions 的每一個節點都呼叫這一個 Lambda，用 `task` 名稱決定要跑 Phase 13 的哪一個函式。

還會得到一份 `infra/asl/ticket-analysis.asl.json`（Ticket Analysis 的流程定義檔）、一份把流程定義存進 S3 的快照腳本，以及一次從「在 GitHub 開 Issue」到「讀到新教學網頁」的端到端驗證。

> 名詞先講白話：
> - **Lambda**：AWS 的「跑一段程式就結束」的服務。你不用租主機，把程式丟上去，有人呼叫才跑，跑完就關掉。
> - **Step Functions**：AWS 的流程圖服務。你用一份 JSON 描述「先做 A、再做 B、B 的結果是 X 就去做 C」，AWS 幫你照著跑，還幫你重試與記錄。
> - **webhook**：別人的系統（這裡是 GitHub）在發生事情時，主動打一個 HTTP 請求到你給的網址，通知你。
> - **CDK**：AWS 的「用程式碼描述雲端資源」工具。你寫 Python，它產生 CloudFormation 樣板，再幫你建立資源。

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
                                        ^^^^^^^^^^^^^^^^^^^^
                                        你在這裡
                                                                                        |
學習層          17 Review:REFINE -> 18 Review:候選規則+排程 -> 19 Analytics 指標 -> 20 規則驗證
                                                                                        |
展示與驗收層    21 Demo 種子資料 -> 22 靜態教學站 -> 23 Demo 控制台 -> 24 失敗復原驗收 -> 25 安全與當日準備
```

---

## 3. 開始前檢查

下面每一項都要先通過，否則這一階段做到一半會卡住。

| 前置條件 | 驗證指令 | 預期輸出 |
|---|---|---|
| Phase 01–13 的測試全部通過 | `uv run pytest tests/unit -q` | 最後一行類似 `123 passed`，沒有 `failed` |
| `.env` 已經有 Phase 04 確認過的值 | `grep -c '^TKB_' .env` | 一個大於等於 8 的數字 |
| `.env` 沒有被 Git 追蹤 | `git check-ignore -v .env` | 印出 `.gitignore:<行號>:.env	.env`（有輸出就代表被忽略） |
| Phase 13 的 task 函式都在 | `uv run python -c "from training_kb.pipelines.ticket import TASKS; print(sorted(TASKS))"` | `['cluster', 'create_v1', 'decide', 'embed', 'name_gap', 'publish', 'recurring']` |
| Phase 12 的 Rote 可用 | `uv run python -c "from training_kb.rote import Rote, default_tools; print(len(default_tools().spec_for_bedrock()))"` | 一個大於 0 的數字 |
| Node.js 與 CDK CLI 已安裝（CDK 需要 Node.js） | `node --version && npx cdk --version` | 兩個版本號，例如 `v22.x.x` 與 `2.x.x (build ...)` |
| AWS 登入可用 | `aws sts get-caller-identity` | 一個含 `Account`、`Arn` 的 JSON |
| Phase 04 的 DataStack 已部署 | `aws dynamodb describe-table --table-name training_kb --query 'Table.TableStatus' --output text` | `ACTIVE` |

再安裝這一階段要用的測試相依（CDK 的樣板斷言工具已經包含在 `aws-cdk-lib` 內）：

```bash
uv add --dev pytest
uv add aws-cdk-lib constructs
```

預期輸出：`uv` 印出 `Resolved ... packages` 與 `Installed ... packages`，`pyproject.toml` 多出 `aws-cdk-lib` 與 `constructs`。

---

## 4. 名詞小抄

| 名詞 | 白話解釋 | 在本階段哪裡用到 |
|---|---|---|
| Lambda handler | Lambda 被呼叫時執行的那個函式，固定收 `(event, context)` 兩個參數 | `handlers/webhook.py`、`handlers/import_.py`、`handlers/pipeline_task.py` |
| Function URL | 幫某個 Lambda 開一個固定的 HTTPS 網址，不用另外架 API Gateway | `training-kb-webhook` 的公開入口 |
| auth type `NONE` | Function URL 不做 AWS 身分驗證。**不等於不用驗證**，我們自己用 HMAC 驗簽 | 設計 §7.1；Task 2、Task 7 |
| resource policy（資源政策） | 掛在 Lambda 上的一段 JSON，說明「誰可以呼叫我」 | `NONE` 時必須明確允許公開呼叫，否則會收到 403 |
| HMAC-SHA256 | 用一把只有雙方知道的密鑰，對訊息算出一段固定長度的指紋 | GitHub 用 `X-Hub-Signature-256` 帶這段指紋 |
| base64 | 把任意位元組編成純文字的編碼方式 | Function URL 在判斷 body 是二進位時會用它包起來，`isBase64Encoded` 為 `true` |
| ASL（Amazon States Language） | Step Functions 用來描述流程的 JSON 語言 | `infra/asl/ticket-analysis.asl.json` |
| Task state | ASL 裡「呼叫一個服務做事」的節點 | 每一個 Task 都呼叫 `training-kb-pipeline-task` |
| Choice state | ASL 裡「依條件分岔」的節點 | `recurring?` 與 `action` 兩個分岔 |
| Fail state | ASL 裡「整條流程以失敗結束」的節點 | `PipelineFailed` |
| Retry / Catch | Task 的兩個欄位：Retry 是「同一個節點再試幾次」，Catch 是「試完還失敗就跳到哪裡」 | 設計 §14.2；每個 Task 都要有 |
| `ErrorEquals` | Retry／Catch 用來比對錯誤名稱的清單 | Python 例外的類別名稱會變成錯誤名稱，例如 `TransientError` |
| `States.ALL` | ASL 的萬用錯誤名稱，比對所有可被捕捉的錯誤 | Catch 用它導向 `PipelineFailed` |
| `Parameters` / `ResultSelector` / `OutputPath` | ASL 的三個資料整形欄位：進入節點前組輸入、拿到結果後挑欄位、離開節點時決定輸出 | 把 `state` 一路傳下去 |
| StartExecution | Step Functions 的「開始執行一條流程」API | `StepFunctionsStarter.start` |
| `ExecutionAlreadyExists` | 同名執行已存在且輸入不同、或已經結束時回的錯誤 | 設計 §14.2 的冪等處理 |
| Lambda Layer | 把相依套件打包成一層，多個 Lambda 共用，程式碼本體就能很小 | `build/layer/python/` |
| CloudFormation 樣板 | CDK 產生的那份「要建立哪些資源」的 JSON | `assertions.Template` 就是對它做斷言 |
| ASL 快照 | 部署前把當下的流程定義存一份到 S3，方便事後追溯 | 設計 §9.3；`stepfunctions/ticket-analysis/v<n>.json` |
| S0–S8 | 設計文件第 16 節的九個交付切片編號 | 本階段對應 S1–S3 |
| O2、O3、O6 | 設計文件第 18 節「待確認事項」的編號 | 本階段遇到時會標「本計劃選擇（對應 O?）」 |

---

## 5. 設計說明

### 5.1 三個 Lambda 與一條流程長什麼樣

```text
        GitHub                          維護者的筆電
          |                                   |
   POST（含簽名）                     boto3 invoke（IAM 驗證）
          |                                   |
          v                                   v
  +-----------------+               +-------------------+
  | training-kb-    |               | training-kb-      |
  | webhook (8 秒)  |               | import            |
  +-----------------+               +-------------------+
          |  驗簽 -> 篩事件 -> Rote.normalize -> accept_*
          |                                   |
          +------------------+----------------+
                             | StartExecution（名稱 = 操作 ID）
                             v
             +-----------------------------------------+
             | Step Functions：training-kb-ticket-analysis |
             |                                         |
             |  Embed -> Cluster -> Recurring -> ?      |
             |     -> NameGap -> Decide -> ?            |
             |     -> CreateV1 -> Publish -> Done       |
             +-----------------------------------------+
                 每個 Task 都呼叫同一個 Lambda：
                 +-------------------------------+
                 | training-kb-pipeline-task     |
                 |  event = {pipeline, task, state}
                 |  -> TASKS[task](state, deps)  |
                 +-------------------------------+
```

三個 Lambda 共用同一份 `src/training_kb/`，只是 handler 路徑不同（設計 §5：「Lambda 可有不同 handler 與權限，但共用同一套模組」）。

### 5.2 Function URL 的事件長什麼樣（要小心的三件事）

Lambda Function URL 送進來的事件用的是 **payload format 2.0**，長這樣（只列我們會用到的欄位）：

```text
{
  "version": "2.0",
  "rawPath": "/",
  "headers": {                      <-- key 一律是小寫
    "x-hub-signature-256": "sha256=...",
    "x-github-event": "issues",
    "x-github-delivery": "0c1f...",
    "content-type": "application/json"
  },
  "requestContext": { "http": { "method": "POST" } },
  "body": "{\"action\":\"opened\", ...}",   <-- 字串，不是物件
  "isBase64Encoded": false                   <-- 可能是 true
}
```

要小心的三件事：

1. **header 的 key 一律是小寫。** 你如果寫 `event["headers"]["X-Hub-Signature-256"]` 會拿到 `KeyError`。程式要自己把整份 header 轉小寫再查。
2. **`body` 是字串，而且可能被 base64 編過。** `isBase64Encoded` 為 `true` 時要先 `base64.b64decode`。
3. **驗簽必須用「還原後的原始位元組」。** 先 `json.loads` 再 `json.dumps` 回去算 HMAC 一定會失敗，因為空白與鍵的順序都可能不同。設計 §7.1 明寫「由程式以原始 request body 計算 HMAC-SHA256，先比對 `X-Hub-Signature-256` 才解析 JSON」。

回應也用同一組格式：`{"statusCode": 200, "headers": {...}, "body": "<字串>", "isBase64Encoded": false}`。

### 5.3 為什麼只處理兩種事件、為什麼限 8 秒

設計 §7.1 規定 MVP 只開一個 GitHub webhook，接 Issue 與 PR。本階段再收斂成兩個具體條件：

- `x-github-event: issues` 且 payload 的 `action == "opened"` → 當成 **Ticket**。
- `x-github-event: pull_request` 且 `action == "closed"` 且 `pull_request.merged == true` → 當成 **Release**。

其他事件一律回 200 加 `"status": "ignored"`。回 200 是因為那不是錯誤，只是我們不處理；回 400 會讓 GitHub 的送達紀錄一片紅，看起來像壞掉。

設計 §14.3 寫「GitHub 要求及時回應，超過十秒可能記為失敗，而且不自動重送」，所以「公開入口在八秒內完成或明確回傳失敗」。因此 `training-kb-webhook` 的 Lambda timeout 設 **8 秒**：與其讓 GitHub 等到超時，不如讓 Lambda 自己先結束並在 CloudWatch 留下紀錄。

> 提醒：第一次遇到全新結構的事件時，Rote 會走第三層（Agent 選工具），那一段可能超過 8 秒。設計 §14.3 已經說明這件事，作法是「展示前先以受控事件累積成功流程」，需要重送時由維護者用 GitHub 的 Redeliver 按鈕。這裡不承諾首次探索一定能在 8 秒內完成。

### 5.4 Python 例外怎麼變成 ASL 的錯誤名稱

這是本階段最容易搞錯的地方，先講結論：

```text
pipelines/ticket.py 的 task 函式
        |
        | raise TransientError("Bedrock 逾時")
        v
handlers/pipeline_task.py 不攔截，直接往外拋
        |
        v
Lambda runtime 把未攔截的例外包成
  { "errorType": "TransientError", "errorMessage": "Bedrock 逾時" }
        |
        v
Step Functions 的 Task state 收到，錯誤名稱 = "TransientError"
        |
        +-- 命中 Retry.ErrorEquals ["TransientError"] -> 等 1 秒重試，最多 2 次
        |
        +-- 重試用完 -> 命中 Catch.ErrorEquals ["States.ALL"] -> PipelineFailed
```

三個要記住的事實：

- Python 的 `errorType` 就是**例外類別的名字**，不含模組路徑。`training_kb.errors.TransientError` 在 ASL 裡就是 `"TransientError"`。
- `PermanentError` 不會被我們的 Retry 命中（`ErrorEquals` 只寫 `TransientError`），會直接落到 Catch，符合設計 §14.2「區分暫時服務故障與確定非法資料，不無限重試」。
- 記憶體不足、Lambda 本身逾時這類「runtime 沒機會回報」的狀況，錯誤名稱是 `Lambda.Unknown`（較新的 runtime 會回 `Sandbox.Timedout`），這些也由 `States.ALL` 的 Catch 接住。設計 §14.2 已經提醒「`States.ALL` 並非涵蓋所有終止錯誤」，所以我們另外在 Phase 24 用注入失敗驗證。

### 5.5 state 怎麼在節點之間傳遞

Phase 13 的每個 task 函式都是 `TaskFn = Callable[[dict, Deps], dict]`：吃一個 state 字典，回一個新的 state 字典。ASL 要把這個約定接起來：

```text
進入 Task 前（Parameters）        Lambda 收到的 event
  $  = {"ticket_id": "t_1", ...}  {"pipeline": "ticket",
                                   "task": "embed",
                                   "state": {"ticket_id": "t_1", ...}}

Lambda 回傳                        離開 Task 後（OutputPath）
  {"ticket_id": "t_1",             $ = {"ticket_id": "t_1",
   "embedding_done": true}              "embedding_done": true}
```

寫成 ASL 就是：

```text
"Parameters": {
  "FunctionName": "${PipelineTaskFunctionArn}",
  "Payload": { "pipeline": "ticket", "task": "embed", "state.$": "$" }
},
"OutputPath": "$.Payload"
```

- `Parameters` 組出要送給 Lambda 的輸入；欄位名結尾加 `.$` 表示「值是一個路徑，不是字面字串」，`"state.$": "$"` 就是「把目前整包 state 放到 `state` 欄位」。
- 用 `arn:aws:states:::lambda:invoke` 這個整合方式時，Task 的原始結果是 `{"ExecutedVersion": ..., "Payload": ..., "StatusCode": 200}`，所以要用 `"OutputPath": "$.Payload"` 把外層剝掉，下一個節點的 `$` 才會是乾淨的 state。
- 設計 §14.3 規定「state 間傳 ID、必要的小型判斷結果或 S3 key，不攜帶全文與向量陣列」，所以 `task_embed` 只回 `embedding_done: true`，向量本身寫進 DynamoDB。

### 5.6 為什麼 StartExecution 要處理 `ExecutionAlreadyExists`

我們把執行名稱固定成「操作 ID 去掉冒號」（`ingress.execution_name(operation_id)`），這樣同一次邏輯操作重送時會撞到同一個名稱。AWS 官方對 Standard 工作流的行為是：

- 同名 + **同輸入** + 仍在執行中 → 直接成功，回傳跟第一次一樣的結果（這就是我們要的冪等）。
- 同名但**已經結束**，或輸入不同 → 回 `400 ExecutionAlreadyExists`。名稱要 90 天後才能重複使用。

設計 §14.2 明寫「不能把此例外直接當成功，也不能改名就無條件重跑」。所以 `StepFunctionsStarter` 收到這個例外時要：

```text
ExecutionAlreadyExists
        |
   describe_execution(executionArn)
        |
  +-----+--------------------------+
  |                                |
status == RUNNING             status 已結束
  |                                |
回傳既有 executionArn        讀操作紀錄 OPS#<operation_id>
（重送 = 同一次處理）              |
                            +------+---------+
                            |                |
                    紀錄顯示已完成      紀錄不存在或未完成
                            |                |
                    回傳既有 ARN      raise PermanentError
                    （沿用既有結果）  （交給人核對，不假裝成功）
```

這一段是**本計劃選擇，對應 O2**（操作紀錄與接受順序）。設計文件只說「需檢查原結果與操作紀錄」，沒有規定確切判斷順序。

### 5.7 本階段新增的目錄結構

```text
AWS-Hackathon/
  src/training_kb/
    ingress.py                 <- 修改：加 StepFunctionsStarter、build_starter
    handlers/
      __init__.py              <- 已存在（Phase 01 建立空檔）
      webhook.py               <- 新增（Task 2）
      import_.py               <- 新增（Task 3）
      pipeline_task.py         <- 新增（Task 4）
  infra/
    app.py                     <- 修改：掛上 TrainingKbAppStack
    asl/
      ticket-analysis.asl.json <- 新增（Task 5）
    scripts/
      build_layer.py           <- 新增（Task 6）
      snapshot_asl.py          <- 新增（Task 8）
    stacks/
      app_stack.py             <- 新增（Task 7）
  build/                       <- 建置產物，已在 .gitignore
    requirements.txt
    layer/python/...
  tests/
    unit/
      test_starter.py          test_handler_webhook.py
      test_handler_import.py   test_handler_pipeline_task.py
      test_asl_ticket.py       test_build_layer.py
      test_app_stack.py        test_snapshot_asl.py
    integration/
      test_webhook_e2e.py      <- 需要真 AWS，標記 @pytest.mark.aws
```

---

## 6. 工作項目

### Task 1：`StepFunctionsStarter`——真的去啟動 Step Functions

**目的**：把 Phase 10 只定義了介面的 `PipelineStarter`，換成真的呼叫 AWS 的實作，並正確處理同名執行。

**檔案**：
- 修改：`src/training_kb/ingress.py`
- 測試：`tests/unit/test_starter.py`

**介面**：
- 消費（前面階段做好的）：`ingress.PipelineStarter`（Protocol，Phase 10）、`ingress.execution_name(operation_id) -> str`（Phase 10）、`repository.Repository.load_operation(operation_id) -> dict | None`（Phase 03）、`errors.PermanentError`（Phase 01）
- 產出（後面階段會用到）：
  - `ingress.STATE_MACHINE_ENV: dict[str, str]`
  - `ingress.execution_arn_for(state_machine_arn: str, name: str) -> str`
  - `ingress.StepFunctionsStarter(client, arns: Mapping[str, str], repo: Repository | None = None)`，方法 `start(self, pipeline: str, execution_name: str, input: dict) -> str`
  - `ingress.build_starter(env: Mapping[str, str] | None = None, *, repo: Repository | None = None) -> StepFunctionsStarter`
  - 註：這四項簡報第 6.6 節未列，是本階段為了落實設計 §14.2 新增的；命名沿用 `ingress` 既有風格。

- [ ] **步驟 1：寫測試**

```python
# tests/unit/test_starter.py
"""StepFunctionsStarter：啟動流程與同名執行的處理（設計 §14.2）。"""

from __future__ import annotations

import json

import pytest

from training_kb.errors import PermanentError
from training_kb.ingress import (
    StepFunctionsStarter,
    build_starter,
    execution_arn_for,
)

TICKET_ARN = "arn:aws:states:us-east-1:123456789012:stateMachine:training-kb-ticket-analysis"


class AlreadyExists(Exception):
    """模擬 botocore 產生的 ExecutionAlreadyExists 例外類別。"""


class FakeExceptions:
    ExecutionAlreadyExists = AlreadyExists


class FakeSfn:
    """只記錄呼叫並回傳預先排定結果的假 Step Functions client。"""

    exceptions = FakeExceptions()

    def __init__(self, *, raise_exists: bool = False, describe_status: str = "RUNNING"):
        self.raise_exists = raise_exists
        self.describe_status = describe_status
        self.started: list[dict] = []
        self.described: list[str] = []

    def start_execution(self, **kwargs):
        self.started.append(kwargs)
        if self.raise_exists:
            raise AlreadyExists("already exists")
        return {"executionArn": kwargs["stateMachineArn"].replace(":stateMachine:", ":execution:")
                + ":" + kwargs["name"]}

    def describe_execution(self, executionArn: str):  # noqa: N803 - boto3 參數名
        self.described.append(executionArn)
        return {"executionArn": executionArn, "status": self.describe_status}


class FakeRepo:
    def __init__(self, operations: dict[str, dict] | None = None):
        self.operations = operations or {}

    def load_operation(self, operation_id: str):
        return self.operations.get(operation_id)


def test_execution_arn_for_把_statemachine_換成_execution():
    assert execution_arn_for(TICKET_ARN, "ingest_ticket_t_1") == (
        "arn:aws:states:us-east-1:123456789012:execution:"
        "training-kb-ticket-analysis:ingest_ticket_t_1"
    )


def test_start_會用正確參數呼叫_start_execution():
    client = FakeSfn()
    starter = StepFunctionsStarter(client, {"ticket": TICKET_ARN})

    arn = starter.start("ticket", "ingest_ticket_t_1", {"ticket_id": "t_1", "operation_id": "ingest:ticket:t_1"})

    assert client.started[0]["stateMachineArn"] == TICKET_ARN
    assert client.started[0]["name"] == "ingest_ticket_t_1"
    assert json.loads(client.started[0]["input"]) == {
        "ticket_id": "t_1",
        "operation_id": "ingest:ticket:t_1",
    }
    assert arn.endswith(":ingest_ticket_t_1")


def test_未知的_pipeline_名稱是永久錯誤():
    starter = StepFunctionsStarter(FakeSfn(), {"ticket": TICKET_ARN})
    with pytest.raises(PermanentError):
        starter.start("nope", "n", {})


def test_同名執行仍在執行中時回傳既有_arn():
    client = FakeSfn(raise_exists=True, describe_status="RUNNING")
    starter = StepFunctionsStarter(client, {"ticket": TICKET_ARN}, FakeRepo())

    arn = starter.start("ticket", "ingest_ticket_t_1", {"operation_id": "ingest:ticket:t_1"})

    assert arn.endswith(":ingest_ticket_t_1")
    assert client.described == [arn]


def test_同名執行已結束且操作紀錄已完成時沿用既有結果():
    client = FakeSfn(raise_exists=True, describe_status="SUCCEEDED")
    repo = FakeRepo({"ingest:ticket:t_1": {"status": "done", "object_id": "t_1"}})
    starter = StepFunctionsStarter(client, {"ticket": TICKET_ARN}, repo)

    arn = starter.start("ticket", "ingest_ticket_t_1", {"operation_id": "ingest:ticket:t_1"})

    assert arn.endswith(":ingest_ticket_t_1")


def test_同名執行已結束但操作紀錄未完成時不假裝成功():
    client = FakeSfn(raise_exists=True, describe_status="FAILED")
    repo = FakeRepo({"ingest:ticket:t_1": {"status": "started"}})
    starter = StepFunctionsStarter(client, {"ticket": TICKET_ARN}, repo)

    with pytest.raises(PermanentError) as err:
        starter.start("ticket", "ingest_ticket_t_1", {"operation_id": "ingest:ticket:t_1"})
    assert "FAILED" in str(err.value)


def test_build_starter_從環境變數讀三條流程的_arn():
    env = {
        "TKB_TICKET_STATE_MACHINE_ARN": TICKET_ARN,
        "TKB_RELEASE_STATE_MACHINE_ARN": TICKET_ARN.replace("ticket-analysis", "release-update"),
    }
    starter = build_starter(env, repo=FakeRepo())
    assert sorted(starter.arns) == ["release", "ticket"]
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：`uv run pytest tests/unit/test_starter.py -v`

預期：FAIL，錯誤訊息類似 `ImportError: cannot import name 'StepFunctionsStarter' from 'training_kb.ingress'`。原因是 `ingress.py` 目前只有 Phase 10 寫的 `PipelineStarter` Protocol，還沒有任何實作類別。

- [ ] **步驟 3：寫最少的程式讓測試通過**

在 `src/training_kb/ingress.py` 的最後面加上（`import` 請併到檔案最上方既有的 import 區塊）：

```python
# ---- Phase 14：真的去啟動 Step Functions ----------------------------------

import json
import os
from collections.abc import Mapping

import boto3

from training_kb.errors import PermanentError
from training_kb.repository import Repository

#: pipeline 名稱 -> 存放 state machine ARN 的環境變數名稱。
STATE_MACHINE_ENV: dict[str, str] = {
    "ticket": "TKB_TICKET_STATE_MACHINE_ARN",
    "release": "TKB_RELEASE_STATE_MACHINE_ARN",
    "feedback": "TKB_FEEDBACK_STATE_MACHINE_ARN",
}


def execution_arn_for(state_machine_arn: str, name: str) -> str:
    """由 state machine ARN 與執行名稱組出執行 ARN。

    MVP 只使用未加版本／別名的 state machine ARN，格式固定為
    ``arn:aws:states:<region>:<account>:stateMachine:<名稱>``。
    """
    prefix, machine = state_machine_arn.rsplit(":stateMachine:", 1)
    return f"{prefix}:execution:{machine}:{name}"


class StepFunctionsStarter:
    """`PipelineStarter` 的 AWS 實作（設計 §14.2）。

    同名執行的處理是本計劃選擇，對應設計第 18 節的 O2：
    仍在執行中就回傳既有執行；已結束則以操作紀錄決定要沿用結果還是交給人處理。
    """

    def __init__(
        self,
        client,
        arns: Mapping[str, str],
        repo: Repository | None = None,
    ) -> None:
        self.client = client
        self.arns = dict(arns)
        self.repo = repo

    def start(self, pipeline: str, execution_name: str, input: dict) -> str:  # noqa: A002
        state_machine_arn = self.arns.get(pipeline)
        if not state_machine_arn:
            raise PermanentError(f"沒有設定 {pipeline} 流程的 state machine ARN")
        payload = json.dumps(input, ensure_ascii=False)
        try:
            response = self.client.start_execution(
                stateMachineArn=state_machine_arn,
                name=execution_name,
                input=payload,
            )
        except self.client.exceptions.ExecutionAlreadyExists:
            return self._resume(state_machine_arn, execution_name, input)
        return response["executionArn"]

    def _resume(self, state_machine_arn: str, execution_name: str, input: dict) -> str:  # noqa: A002
        arn = execution_arn_for(state_machine_arn, execution_name)
        status = self.client.describe_execution(executionArn=arn).get("status")
        if status == "RUNNING":
            return arn
        operation_id = str(input.get("operation_id") or "")
        record = None
        if self.repo is not None and operation_id:
            record = self.repo.load_operation(operation_id)
        if record is not None and record.get("status") == "done":
            return arn
        raise PermanentError(
            f"同名執行已結束（status={status}）但操作紀錄未完成：{arn}；"
            "請以 OPS 紀錄核對後再決定是否人工重跑，不可直接視為成功"
        )


def build_starter(
    env: Mapping[str, str] | None = None,
    *,
    repo: Repository | None = None,
) -> StepFunctionsStarter:
    """依環境變數組出 `StepFunctionsStarter`；沒設定的流程就不放進表裡。"""
    source = os.environ if env is None else env
    arns = {
        pipeline: source[var]
        for pipeline, var in STATE_MACHINE_ENV.items()
        if source.get(var)
    }
    return StepFunctionsStarter(boto3.client("stepfunctions"), arns, repo)
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：`uv run pytest tests/unit/test_starter.py -v`

預期：PASS，7 個測試全部綠色。

- [ ] **步驟 5：commit**

```bash
git add tests/unit/test_starter.py src/training_kb/ingress.py
git commit -m "feat(ingress): 加入 StepFunctionsStarter 與同名執行處理"
```

---

### Task 2：`handlers/webhook.py`——GitHub 事件的公開入口

**目的**：把 Function URL 的事件轉成 `RawEvent`，驗簽後交給 Rote 與 ingress，回 200／400 JSON。

**檔案**：
- 新增：`src/training_kb/handlers/webhook.py`
- 測試：`tests/unit/test_handler_webhook.py`

**介面**：
- 消費：`ingress.verify_github_signature(secret, body, signature_header) -> bool`、`ingress.accept_ticket(repo, starter, ticket, *, delivery_id, now) -> AcceptResult`、`ingress.accept_release(...)`、`ingress.build_starter(env, repo=...)`（Task 1）、`rote.RawEvent`、`rote.Rote.normalize(event, *, operation_id, now) -> IngestOutcome`、`rote.Rote.commit_success(outcome, *, now)`、`rote.default_tools()`、`config.load_settings(env)`、`repository.build_repository(settings)`、`writing.client.build_writer(settings, trace)`、`writing.client.CallTrace`、`clock.now_utc()`、`clock.to_iso(dt)`
- 產出：
  - `handlers.webhook.handler(event, context) -> dict`
  - `handlers.webhook.parse_request(event) -> tuple[dict[str, str], bytes]`
  - `handlers.webhook.select_adapter_type(github_event, body) -> str | None`
  - `handlers.webhook.json_response(status, payload) -> dict`
  - `handlers.webhook.delivery_operation_id(delivery_id) -> str`
  - `handlers.webhook.WebhookContext`、`build_context()`、`get_context()`、`set_context(ctx)`、`resolve_secret(env)`
  - 註：以上簡報第 6.10 節只列了 `handler`，其餘是本階段為了可測試與冷啟動快取新增的。

- [ ] **步驟 1：寫測試**

```python
# tests/unit/test_handler_webhook.py
"""webhook handler：Function URL 事件格式、驗簽與事件篩選。"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json

import pytest

from training_kb.config import Settings
from training_kb.handlers import webhook
from training_kb.ingress import AcceptResult
from training_kb.models import Ticket, TicketSource
from training_kb.rote import IngestOutcome

SECRET = "hunter2"
TICKET = Ticket(
    id="t_gh-acme-app-7",
    source=TicketSource.github_issue,
    text="會前摘要在哪裡開啟？",
    author="u_01",
    ts="2026-08-01T00:00:00Z",
    project_id="demo-project",
)


def sign(body: bytes) -> str:
    return "sha256=" + hmac.new(SECRET.encode("utf-8"), body, hashlib.sha256).hexdigest()


def make_settings() -> Settings:
    return Settings(
        aws_region="us-east-1",
        table_name="training_kb",
        bucket_name="training-kb-content-demo",
        project_id="demo-project",
        embed_model_id="amazon.titan-embed-text-v2:0",
        embed_dimensions=1024,
        gen_model_id="fake-claude",
        github_webhook_secret=SECRET,
    )


class StubRote:
    def __init__(self, obj):
        self.obj = obj
        self.committed: list[IngestOutcome] = []

    def normalize(self, event, *, operation_id, now):
        self.seen = event
        return IngestOutcome(layer=3, obj=self.obj, proc_steps=[], signature="s0", proc_used=None)

    def commit_success(self, outcome, *, now):
        self.committed.append(outcome)


def make_event(
    payload: dict,
    *,
    github_event: str = "issues",
    signature: str | None = None,
    as_base64: bool = False,
    header_case: str = "lower",
) -> dict:
    body = json.dumps(payload).encode("utf-8")
    raw = {
        "X-GitHub-Event": github_event,
        "X-GitHub-Delivery": "d-0001",
        "Content-Type": "application/json",
    }
    if signature is None:
        signature = sign(body)
    if signature != "":
        raw["X-Hub-Signature-256"] = signature
    headers = {k.lower(): v for k, v in raw.items()} if header_case == "lower" else raw
    return {
        "version": "2.0",
        "rawPath": "/",
        "headers": headers,
        "requestContext": {"http": {"method": "POST"}},
        "body": base64.b64encode(body).decode("ascii") if as_base64 else body.decode("utf-8"),
        "isBase64Encoded": as_base64,
    }


ISSUE_OPENED = {
    "action": "opened",
    "issue": {"number": 7, "title": "找不到按鈕", "body": "會前摘要在哪裡開啟？", "user": {"login": "u_01"}},
    "repository": {"name": "app", "owner": {"login": "acme"}},
    "sender": {"login": "u_01"},
}
PR_MERGED = {
    "action": "closed",
    "pull_request": {"number": 42, "merged": True, "title": "Rename Meeting Summary", "body": "renamed"},
    "repository": {"name": "app", "owner": {"login": "acme"}},
    "sender": {"login": "u_01"},
}


@pytest.fixture
def ctx(monkeypatch):
    rote = StubRote(TICKET)
    context = webhook.WebhookContext(
        settings=make_settings(), repo=object(), rote=rote, starter=object()
    )
    webhook.set_context(context)
    calls: list[dict] = []

    def fake_accept_ticket(repo, starter, ticket, *, delivery_id, now):
        calls.append({"ticket": ticket, "delivery_id": delivery_id})
        return AcceptResult(
            status="accepted",
            object_id=ticket.id,
            execution_arn="arn:aws:states:::execution:x:y",
            message="已接受",
            invalid_fields=[],
        )

    monkeypatch.setattr(webhook.ingress, "accept_ticket", fake_accept_ticket)
    context.calls = calls  # type: ignore[attr-defined]
    yield context
    webhook.set_context(None)


def test_有效的_issue_opened_事件回_200_並接受工單(ctx):
    response = webhook.handler(make_event(ISSUE_OPENED), None)

    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body["status"] == "accepted"
    assert body["id"] == "t_gh-acme-app-7"
    assert ctx.calls[0]["delivery_id"] == "d-0001"
    assert len(ctx.rote.committed) == 1


def test_header_大小寫不同也讀得到(ctx):
    response = webhook.handler(make_event(ISSUE_OPENED, header_case="mixed"), None)
    assert response["statusCode"] == 200


def test_body_是_base64_時用還原後的_bytes_驗簽(ctx):
    response = webhook.handler(make_event(ISSUE_OPENED, as_base64=True), None)
    assert response["statusCode"] == 200


def test_缺少簽名回_400(ctx):
    response = webhook.handler(make_event(ISSUE_OPENED, signature=""), None)

    assert response["statusCode"] == 400
    body = json.loads(response["body"])
    assert body["status"] == "failed"
    assert body["fields"] == ["x-hub-signature-256"]
    assert ctx.rote.committed == []


def test_簽名不符回_400(ctx):
    response = webhook.handler(make_event(ISSUE_OPENED, signature="sha256=deadbeef"), None)
    assert response["statusCode"] == 400


def test_body_不是合法_json_回_400(ctx):
    body = b"not json"
    event = {
        "version": "2.0",
        "headers": {"x-hub-signature-256": sign(body), "x-github-event": "issues"},
        "body": body.decode("utf-8"),
        "isBase64Encoded": False,
    }
    response = webhook.handler(event, None)
    assert response["statusCode"] == 400
    assert json.loads(response["body"])["fields"] == ["body"]


def test_非_opened_的_issue_事件被忽略且不呼叫_rote(ctx):
    payload = dict(ISSUE_OPENED, action="edited")
    response = webhook.handler(make_event(payload), None)

    assert response["statusCode"] == 200
    assert json.loads(response["body"])["status"] == "ignored"
    assert ctx.rote.committed == []


def test_未合併的_pull_request_被忽略(ctx):
    payload = {**PR_MERGED, "pull_request": {**PR_MERGED["pull_request"], "merged": False}}
    response = webhook.handler(make_event(payload, github_event="pull_request"), None)
    assert json.loads(response["body"])["status"] == "ignored"


def test_重送同一事件時不再累加_proc_成功樣本(ctx, monkeypatch):
    def duplicate(repo, starter, ticket, *, delivery_id, now):
        return AcceptResult(
            status="duplicate",
            object_id=ticket.id,
            execution_arn="arn:aws:states:::execution:x:y",
            message="同一事件已處理",
            invalid_fields=[],
        )

    monkeypatch.setattr(webhook.ingress, "accept_ticket", duplicate)
    response = webhook.handler(make_event(ISSUE_OPENED), None)

    assert json.loads(response["body"])["status"] == "duplicate"
    assert ctx.rote.committed == []


def test_select_adapter_type_三種情況():
    assert webhook.select_adapter_type("issues", ISSUE_OPENED) == "ticket"
    assert webhook.select_adapter_type("pull_request", PR_MERGED) == "release"
    assert webhook.select_adapter_type("push", {}) is None


def test_resolve_secret_只在缺值時去拿():
    class FakeSecrets:
        def __init__(self):
            self.calls = 0

        def get_secret_value(self, SecretId):  # noqa: N803 - boto3 參數名
            self.calls += 1
            return {"SecretString": "from-secrets-manager"}

    fake = FakeSecrets()
    env = {"TKB_GITHUB_WEBHOOK_SECRET": "already"}
    webhook.resolve_secret(env, client=fake)
    assert env["TKB_GITHUB_WEBHOOK_SECRET"] == "already"
    assert fake.calls == 0

    env2 = {"TKB_GITHUB_WEBHOOK_SECRET_ARN": "arn:aws:secretsmanager:...:secret:tkb"}
    webhook.resolve_secret(env2, client=fake)
    assert env2["TKB_GITHUB_WEBHOOK_SECRET"] == "from-secrets-manager"
    assert fake.calls == 1
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：`uv run pytest tests/unit/test_handler_webhook.py -v`

預期：FAIL，錯誤訊息是 `ModuleNotFoundError: No module named 'training_kb.handlers.webhook'`，因為檔案還不存在。

- [ ] **步驟 3：寫最少的程式讓測試通過**

```python
# src/training_kb/handlers/webhook.py
"""GitHub webhook 的 Lambda handler（Phase 14）。

Function URL 事件 -> 驗簽 -> 篩事件 -> Rote 正規化 -> ingress 接受 -> 200／400 JSON。
整體必須在 8 秒內結束（設計 §14.3）。
"""

from __future__ import annotations

import base64
import json
import os
from collections.abc import MutableMapping
from dataclasses import dataclass
from typing import Any

import boto3

from training_kb import ingress
from training_kb.clock import now_utc, to_iso
from training_kb.config import Settings, load_settings
from training_kb.errors import IngressError, PermanentError, TransientError
from training_kb.repository import Repository, build_repository
from training_kb.rote import RawEvent, Rote, default_tools
from training_kb.writing.client import CallTrace, build_writer

#: 本階段唯一開放的公開來源網域（設計 §7.1）。
GITHUB_DOMAIN = "github.com"
#: 超過這個大小就直接拒絕，避免在 8 秒內做無謂的工作。
MAX_BODY_BYTES = 1024 * 1024


@dataclass
class WebhookContext:
    """冷啟動時建一次、後續呼叫重用的相依物件。"""

    settings: Settings
    repo: Repository
    rote: Rote
    starter: Any


_CONTEXT: WebhookContext | None = None


def resolve_secret(env: MutableMapping[str, str], *, client: Any = None) -> None:
    """只給 Secrets Manager ARN 時，把 secret 取出來放進環境變數。

    設計 §17.2 要求 webhook secret 只由執行環境提供，不進 Git。
    """
    if env.get("TKB_GITHUB_WEBHOOK_SECRET"):
        return
    arn = env.get("TKB_GITHUB_WEBHOOK_SECRET_ARN")
    if not arn:
        return
    secrets = client or boto3.client("secretsmanager")
    env["TKB_GITHUB_WEBHOOK_SECRET"] = secrets.get_secret_value(SecretId=arn)["SecretString"]


def build_context() -> WebhookContext:
    resolve_secret(os.environ)
    settings = load_settings(os.environ)
    repo = build_repository(settings)
    writer = build_writer(settings, CallTrace())
    rote = Rote(repo, writer, default_tools(), settings)
    starter = ingress.build_starter(os.environ, repo=repo)
    return WebhookContext(settings=settings, repo=repo, rote=rote, starter=starter)


def get_context() -> WebhookContext:
    global _CONTEXT
    if _CONTEXT is None:
        _CONTEXT = build_context()
    return _CONTEXT


def set_context(context: WebhookContext | None) -> None:
    """測試用：直接指定，或傳 None 清掉冷啟動快取。"""
    global _CONTEXT
    _CONTEXT = context


def parse_request(event: dict[str, Any]) -> tuple[dict[str, str], bytes]:
    """把 Function URL 事件拆成「小寫 header 字典」與「原始 body 位元組」。

    Function URL 使用 payload format 2.0：header 名稱已經是小寫，
    但我們仍自己轉一次，讓本機測試與其他呼叫端不必在意大小寫。
    """
    headers = {str(k).lower(): v for k, v in (event.get("headers") or {}).items()}
    raw_body = event.get("body") or ""
    if event.get("isBase64Encoded"):
        body = base64.b64decode(raw_body)
    else:
        body = raw_body.encode("utf-8")
    return headers, body


def json_response(status: int, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "statusCode": status,
        "headers": {"content-type": "application/json; charset=utf-8"},
        "body": json.dumps(payload, ensure_ascii=False),
        "isBase64Encoded": False,
    }


def select_adapter_type(github_event: str, body: dict[str, Any]) -> str | None:
    """只認兩種事件；其餘回 None 代表忽略（設計 §7.1）。"""
    action = body.get("action")
    if github_event == "issues" and action == "opened":
        return "ticket"
    if github_event == "pull_request" and action == "closed":
        pull_request = body.get("pull_request") or {}
        if bool(pull_request.get("merged")):
            return "release"
    return None


def delivery_operation_id(delivery_id: str | None) -> str:
    """給 Rote 呼叫紀錄用的操作 ID；真正的去重仍由 ingress 以物件 ID 負責。"""
    return f"ingest:delivery:{delivery_id or 'unknown'}"


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    now = now_utc()
    ctx = get_context()
    headers, body = parse_request(event)
    signature = headers.get("x-hub-signature-256")
    github_event = headers.get("x-github-event", "")
    delivery_id = headers.get("x-github-delivery")

    if not ingress.verify_github_signature(ctx.settings.github_webhook_secret, body, signature):
        return json_response(
            400,
            {"status": "failed", "fields": ["x-hub-signature-256"], "message": "簽名缺少或不符"},
        )
    if len(body) > MAX_BODY_BYTES:
        return json_response(400, {"status": "failed", "fields": ["body"], "message": "body 過大"})
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return json_response(
            400, {"status": "failed", "fields": ["body"], "message": "body 不是合法 JSON"}
        )
    if not isinstance(payload, dict):
        return json_response(
            400, {"status": "failed", "fields": ["body"], "message": "body 必須是 JSON 物件"}
        )

    adapter_type = select_adapter_type(github_event, payload)
    if adapter_type is None:
        return json_response(
            200,
            {
                "status": "ignored",
                "event": github_event,
                "message": "本階段只處理 issues opened 與 pull_request closed+merged",
            },
        )

    raw_event = RawEvent(
        domain=GITHUB_DOMAIN,
        adapter_type=adapter_type,
        event_type=github_event,
        headers=headers,
        body=payload,
        received_at=to_iso(now),
        delivery_id=delivery_id,
    )
    try:
        outcome = ctx.rote.normalize(
            raw_event, operation_id=delivery_operation_id(delivery_id), now=now
        )
        if adapter_type == "ticket":
            result = ingress.accept_ticket(
                ctx.repo, ctx.starter, outcome.obj, delivery_id=delivery_id, now=now
            )
        else:
            result = ingress.accept_release(
                ctx.repo, ctx.starter, outcome.obj, delivery_id=delivery_id, now=now
            )
    except IngressError as exc:
        return json_response(
            400, {"status": "failed", "fields": list(exc.fields), "message": str(exc)}
        )
    except (PermanentError, TransientError) as exc:
        return json_response(400, {"status": "failed", "fields": [], "message": str(exc)})

    if result.status == "failed":
        return json_response(
            400,
            {"status": "failed", "fields": list(result.invalid_fields), "message": result.message},
        )
    if result.status == "accepted":
        # 設計 §7.2：物件保存且流程啟動成功後才記一次成功；重送不提供新樣本。
        ctx.rote.commit_success(outcome, now=now)
    return json_response(
        200,
        {
            "status": result.status,
            "id": result.object_id,
            "execution_arn": result.execution_arn,
            "message": result.message,
        },
    )
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：`uv run pytest tests/unit/test_handler_webhook.py -v`

預期：PASS，12 個測試全部綠色。

- [ ] **步驟 5：commit**

```bash
git add tests/unit/test_handler_webhook.py src/training_kb/handlers/webhook.py
git commit -m "feat(handlers): 加入 GitHub webhook 的 Lambda handler"
```

---

### Task 3：`handlers/import_.py`——維護者的受控匯入入口

**目的**：讓已登入 AWS 的維護者用 `boto3` 直接 invoke，一次送多筆 Ticket 或 Release；Feedback 與 View 先明確回「未支援」。

**檔案**：
- 新增：`src/training_kb/handlers/import_.py`
- 測試：`tests/unit/test_handler_import.py`

**介面**：
- 消費：`ingress.handle_manual_ticket(repo, rote, starter, payload, source, *, now) -> AcceptResult`、`ingress.handle_manual_release(repo, rote, starter, payload, source, *, now) -> AcceptResult`（兩者由 Phase 12（`12-Phase12-Rote-Agent選工具與重放執行.md`）Task 11 完成；`handle_manual_release` 是該階段新增，簡報第 6.6 節只列了 ticket 版本）、`models.TicketSource`、`models.ReleaseSource`、`errors.IngressError`
- 產出：
  - `handlers.import_.handler(event, context) -> dict`
  - `handlers.import_.ImportContext`、`build_context()`、`get_context()`、`set_context(ctx)`
  - `handlers.import_.SUPPORTED_KINDS: tuple[str, ...]`、`UNSUPPORTED_KINDS: dict[str, str]`
  - 註：`handle_manual_release` 與 `handle_manual_ticket` 同一組簽名，兩者都在 Phase 12 完成。

事件格式（維護者送進來的）：

```text
{
  "kind": "ticket" | "release" | "feedback" | "view",
  "source": "github_issue" | "discord" | "email" | "github_pr" | "changelog",
  "items": [ {...}, {...} ]
}
```

回傳格式：

```text
{
  "kind": "ticket",
  "count": 2,
  "results": [
    {"status": "accepted",  "object_id": "t_1", "execution_arn": "...", "message": "...", "invalid_fields": []},
    {"status": "failed",    "object_id": null,  "execution_arn": null,  "message": "...", "invalid_fields": ["author"]}
  ]
}
```

- [ ] **步驟 1：寫測試**

```python
# tests/unit/test_handler_import.py
"""import handler：kind 分派、逐筆回傳與尚未支援的種類。"""

from __future__ import annotations

import pytest

from training_kb.handlers import import_ as import_handler
from training_kb.ingress import AcceptResult
from training_kb.models import ReleaseSource, TicketSource


@pytest.fixture
def ctx():
    context = import_handler.ImportContext(
        settings=object(), repo=object(), rote=object(), starter=object(), writer=object()
    )
    import_handler.set_context(context)
    yield context
    import_handler.set_context(None)


def ok(object_id: str) -> AcceptResult:
    return AcceptResult(
        status="accepted",
        object_id=object_id,
        execution_arn="arn:aws:states:::execution:a:b",
        message="已接受",
        invalid_fields=[],
    )


def test_ticket_逐筆呼叫_handle_manual_ticket(ctx, monkeypatch):
    seen: list[tuple[dict, TicketSource]] = []

    def fake(repo, rote, starter, payload, source, *, now):
        seen.append((payload, source))
        return ok(payload["id"])

    monkeypatch.setattr(import_handler.ingress, "handle_manual_ticket", fake)

    response = import_handler.handler(
        {"kind": "ticket", "source": "email", "items": [{"id": "t_1"}, {"id": "t_2"}]}, None
    )

    assert response["count"] == 2
    assert [r["object_id"] for r in response["results"]] == ["t_1", "t_2"]
    assert seen[0][1] is TicketSource.email


def test_release_逐筆呼叫_handle_manual_release(ctx, monkeypatch):
    monkeypatch.setattr(
        import_handler.ingress,
        "handle_manual_release",
        lambda repo, rote, starter, payload, source, *, now: ok(payload["id"]),
    )

    response = import_handler.handler(
        {"kind": "release", "source": "changelog", "items": [{"id": "r_42"}]}, None
    )

    assert response["results"][0]["status"] == "accepted"
    assert response["kind"] == "release"


def test_feedback_與_view_本階段回未支援(ctx):
    for kind in ("feedback", "view"):
        response = import_handler.handler({"kind": kind, "source": "widget", "items": [{}]}, None)
        assert response["results"][0]["status"] == "unsupported"
        assert "Phase 15" in response["results"][0]["message"]


def test_未知的_kind_回_failed(ctx):
    response = import_handler.handler({"kind": "banana", "items": []}, None)
    assert response["results"][0]["status"] == "failed"
    assert response["results"][0]["invalid_fields"] == ["kind"]


def test_不合法的_source_回_failed_並指出欄位(ctx):
    response = import_handler.handler(
        {"kind": "ticket", "source": "telegram", "items": [{"id": "t_1"}]}, None
    )
    assert response["results"][0]["status"] == "failed"
    assert response["results"][0]["invalid_fields"] == ["source"]


def test_items_不是清單回_failed(ctx):
    response = import_handler.handler({"kind": "ticket", "source": "email", "items": {}}, None)
    assert response["results"][0]["invalid_fields"] == ["items"]


def test_單筆失敗不影響其他筆(ctx, monkeypatch):
    from training_kb.errors import IngressError

    def fake(repo, rote, starter, payload, source, *, now):
        if payload["id"] == "t_bad":
            raise IngressError("缺少 author", ["author"])
        return ok(payload["id"])

    monkeypatch.setattr(import_handler.ingress, "handle_manual_ticket", fake)

    response = import_handler.handler(
        {"kind": "ticket", "source": "email", "items": [{"id": "t_bad"}, {"id": "t_ok"}]}, None
    )

    assert response["results"][0]["status"] == "failed"
    assert response["results"][0]["invalid_fields"] == ["author"]
    assert response["results"][1]["status"] == "accepted"
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：`uv run pytest tests/unit/test_handler_import.py -v`

預期：FAIL，`ModuleNotFoundError: No module named 'training_kb.handlers.import_'`。

- [ ] **步驟 3：寫最少的程式讓測試通過**

```python
# src/training_kb/handlers/import_.py
"""手動匯入的 Lambda handler（Phase 14 做 ticket／release，Phase 15 補 feedback／view）。

這個 Lambda 沒有公開網址。維護者用自己的 AWS 登入以 boto3 invoke 呼叫它
（設計 §7.1：手動上傳由已登入 AWS 的維護者透過 SDK 呼叫，不建立第二個公開 URL）。
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from typing import Any

from training_kb import ingress
from training_kb.clock import now_utc
from training_kb.config import load_settings
from training_kb.errors import IngressError, PermanentError, TransientError
from training_kb.models import ReleaseSource, TicketSource
from training_kb.repository import build_repository
from training_kb.rote import Rote, default_tools
from training_kb.writing.client import CallTrace, build_writer

SUPPORTED_KINDS: tuple[str, ...] = ("ticket", "release")
#: 本階段還沒做的種類；Phase 15 會把它們接到 import_feedback／import_view。
UNSUPPORTED_KINDS: dict[str, str] = {
    "feedback": "本階段尚未支援 feedback 匯入，Phase 15 會接上 ingress.import_feedback",
    "view": "本階段尚未支援 view 匯入，Phase 15 會接上 ingress.import_view",
}


@dataclass
class ImportContext:
    settings: Any
    repo: Any
    rote: Any
    starter: Any
    writer: Any


_CONTEXT: ImportContext | None = None


def build_context() -> ImportContext:
    settings = load_settings(os.environ)
    repo = build_repository(settings)
    writer = build_writer(settings, CallTrace())
    rote = Rote(repo, writer, default_tools(), settings)
    starter = ingress.build_starter(os.environ, repo=repo)
    return ImportContext(settings=settings, repo=repo, rote=rote, starter=starter, writer=writer)


def get_context() -> ImportContext:
    global _CONTEXT
    if _CONTEXT is None:
        _CONTEXT = build_context()
    return _CONTEXT


def set_context(context: ImportContext | None) -> None:
    global _CONTEXT
    _CONTEXT = context


def _failed(message: str, fields: list[str]) -> dict[str, Any]:
    return {
        "status": "failed",
        "object_id": None,
        "execution_arn": None,
        "message": message,
        "invalid_fields": fields,
    }


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    kind = str(event.get("kind") or "")
    source = str(event.get("source") or "")
    items = event.get("items")
    now = now_utc()

    if kind in UNSUPPORTED_KINDS:
        message = UNSUPPORTED_KINDS[kind]
        count = len(items) if isinstance(items, list) else 1
        results = [
            {
                "status": "unsupported",
                "object_id": None,
                "execution_arn": None,
                "message": message,
                "invalid_fields": [],
            }
            for _ in range(max(count, 1))
        ]
        return {"kind": kind, "count": len(results), "results": results}

    if kind not in SUPPORTED_KINDS:
        return {"kind": kind, "count": 1, "results": [_failed(f"未知的 kind：{kind}", ["kind"])]}

    try:
        source_enum = TicketSource(source) if kind == "ticket" else ReleaseSource(source)
    except ValueError:
        return {
            "kind": kind,
            "count": 1,
            "results": [_failed(f"不合法的 source：{source}", ["source"])],
        }

    if not isinstance(items, list):
        return {"kind": kind, "count": 1, "results": [_failed("items 必須是清單", ["items"])]}

    ctx = get_context()
    results: list[dict[str, Any]] = []
    for item in items:
        try:
            if kind == "ticket":
                result = ingress.handle_manual_ticket(
                    ctx.repo, ctx.rote, ctx.starter, item, source_enum, now=now
                )
            else:
                result = ingress.handle_manual_release(
                    ctx.repo, ctx.rote, ctx.starter, item, source_enum, now=now
                )
            results.append(asdict(result))
        except IngressError as exc:
            results.append(_failed(str(exc), list(exc.fields)))
        except (PermanentError, TransientError) as exc:
            results.append(_failed(str(exc), []))
    return {"kind": kind, "count": len(results), "results": results}
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：`uv run pytest tests/unit/test_handler_import.py -v`

預期：PASS，7 個測試綠色。

- [ ] **步驟 5：commit**

```bash
git add tests/unit/test_handler_import.py src/training_kb/handlers/import_.py
git commit -m "feat(handlers): 加入手動匯入的 Lambda handler"
```

---

### Task 4：`handlers/pipeline_task.py`——Step Functions 每一個節點的入口

**目的**：依 `pipeline` 與 `task` 找到對應的 task 函式執行，並讓錯誤型別原樣往外拋，好讓 ASL 的 Retry／Catch 能比對到。

**檔案**：
- 新增：`src/training_kb/handlers/pipeline_task.py`
- 測試：`tests/unit/test_handler_pipeline_task.py`

**介面**：
- 消費：`pipelines.common.Deps`、`pipelines.common.build_deps(settings) -> Deps`、`pipelines.ticket.TASKS`、`errors.TransientError`、`errors.PermanentError`、`config.load_settings(env)`
- 產出：
  - `handlers.pipeline_task.handler(event, context) -> dict`
  - `handlers.pipeline_task.PIPELINE_MODULES: dict[str, str]`
  - `handlers.pipeline_task.load_tasks(pipeline: str) -> dict[str, TaskFn]`
  - `handlers.pipeline_task.get_deps()`、`set_deps(deps)`

- [ ] **步驟 1：寫測試**

```python
# tests/unit/test_handler_pipeline_task.py
"""pipeline_task handler：task 分派與錯誤型別的傳遞。"""

from __future__ import annotations

import pytest

from training_kb.errors import PermanentError, TransientError
from training_kb.handlers import pipeline_task


@pytest.fixture
def deps():
    fake = object()
    pipeline_task.set_deps(fake)
    yield fake
    pipeline_task.set_deps(None)


def test_依_task_名稱執行並回傳新的_state(deps, monkeypatch):
    def fake_tasks(pipeline: str):
        assert pipeline == "ticket"
        return {"embed": lambda state, d: {**state, "embedding_done": True}}

    monkeypatch.setattr(pipeline_task, "load_tasks", fake_tasks)

    result = pipeline_task.handler(
        {"pipeline": "ticket", "task": "embed", "state": {"ticket_id": "t_1"}}, None
    )

    assert result == {"ticket_id": "t_1", "embedding_done": True}


def test_transient_error_原樣往外拋(deps, monkeypatch):
    def boom(state, d):
        raise TransientError("Bedrock 逾時")

    monkeypatch.setattr(pipeline_task, "load_tasks", lambda p: {"embed": boom})

    with pytest.raises(TransientError):
        pipeline_task.handler({"pipeline": "ticket", "task": "embed", "state": {}}, None)


def test_permanent_error_原樣往外拋(deps, monkeypatch):
    def boom(state, d):
        raise PermanentError("步驟引用了不存在的 Feature")

    monkeypatch.setattr(pipeline_task, "load_tasks", lambda p: {"embed": boom})

    with pytest.raises(PermanentError):
        pipeline_task.handler({"pipeline": "ticket", "task": "embed", "state": {}}, None)


def test_未知的_task_名稱是永久錯誤(deps, monkeypatch):
    monkeypatch.setattr(pipeline_task, "load_tasks", lambda p: {"embed": lambda s, d: s})

    with pytest.raises(PermanentError):
        pipeline_task.handler({"pipeline": "ticket", "task": "nope", "state": {}}, None)


def test_未知的_pipeline_名稱是永久錯誤():
    with pytest.raises(PermanentError):
        pipeline_task.load_tasks("banana")


def test_尚未實作的_pipeline_模組是永久錯誤(monkeypatch):
    monkeypatch.setitem(pipeline_task.PIPELINE_MODULES, "release", "training_kb.pipelines.not_yet")
    with pytest.raises(PermanentError) as err:
        pipeline_task.load_tasks("release")
    assert "尚未實作" in str(err.value)


def test_真的載得到_ticket_的_tasks():
    tasks = pipeline_task.load_tasks("ticket")
    assert "embed" in tasks and "publish" in tasks


def test_錯誤類別的名稱就是_asl_要比對的字串():
    # Lambda runtime 會把未攔截例外的類別名稱放進 errorType，
    # Step Functions 再用它比對 ErrorEquals。
    assert TransientError.__name__ == "TransientError"
    assert PermanentError.__name__ == "PermanentError"
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：`uv run pytest tests/unit/test_handler_pipeline_task.py -v`

預期：FAIL，`ModuleNotFoundError: No module named 'training_kb.handlers.pipeline_task'`。

- [ ] **步驟 3：寫最少的程式讓測試通過**

```python
# src/training_kb/handlers/pipeline_task.py
"""Step Functions Task 的 Lambda handler（Phase 14）。

三條 state machine 的每一個 Task 都呼叫這一個 Lambda，用 ``task`` 名稱分派。
錯誤不在這裡攔截：TransientError 要讓 ASL 的 Retry 抓到，
PermanentError 要讓 ASL 的 Catch 抓到（設計 §14.2）。
"""

from __future__ import annotations

import importlib
import os
from typing import Any

from training_kb.config import load_settings
from training_kb.errors import PermanentError
from training_kb.pipelines.common import Deps, build_deps

#: pipeline 名稱 -> 提供 TASKS 的模組。Phase 16、17 會補上 release 與 feedback。
PIPELINE_MODULES: dict[str, str] = {
    "ticket": "training_kb.pipelines.ticket",
    "release": "training_kb.pipelines.release",
    "feedback": "training_kb.pipelines.feedback",
}

_DEPS: Deps | None = None


def get_deps() -> Deps:
    global _DEPS
    if _DEPS is None:
        _DEPS = build_deps(load_settings(os.environ))
    return _DEPS


def set_deps(deps: Deps | None) -> None:
    """測試用：直接指定，或傳 None 清掉冷啟動快取。"""
    global _DEPS
    _DEPS = deps


def load_tasks(pipeline: str) -> dict[str, Any]:
    module_path = PIPELINE_MODULES.get(pipeline)
    if module_path is None:
        raise PermanentError(f"未知的 pipeline：{pipeline}")
    try:
        module = importlib.import_module(module_path)
    except ModuleNotFoundError as exc:
        raise PermanentError(f"pipeline 尚未實作：{pipeline}") from exc
    return module.TASKS


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    pipeline = str(event.get("pipeline") or "")
    task = str(event.get("task") or "")
    state = event.get("state") or {}

    tasks = load_tasks(pipeline)
    task_fn = tasks.get(task)
    if task_fn is None:
        raise PermanentError(f"{pipeline} 流程沒有名為 {task} 的 task")
    return task_fn(state, get_deps())
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：`uv run pytest tests/unit/test_handler_pipeline_task.py -v`

預期：PASS，8 個測試綠色。

- [ ] **步驟 5：commit**

```bash
git add tests/unit/test_handler_pipeline_task.py src/training_kb/handlers/pipeline_task.py
git commit -m "feat(handlers): 加入 Step Functions Task 的分派 handler"
```

---

### Task 5：`infra/asl/ticket-analysis.asl.json`——流程定義檔

**目的**：把 Phase 13 的七個 task 串成一條有分支、有 Retry、有 Catch 的 Step Functions 流程。

**檔案**：
- 新增：`infra/asl/ticket-analysis.asl.json`
- 測試：`tests/unit/test_asl_ticket.py`

**介面**：
- 消費：`handlers.pipeline_task.handler`（透過 `${PipelineTaskFunctionArn}` 這個替換變數指到的 Lambda）
- 產出：`infra/asl/ticket-analysis.asl.json`（Task 7 用 `DefinitionBody.from_file` 讀它；Task 8 把它存進 S3）

流程長這樣：

```text
        Embed
          |
        Cluster
          |
       Recurring
          |
    +-----+---------------------------+
    | $.recurring == true             | 否
    v                                 v
  NameGap                       NotRecurring (Succeed)
    |
  Decide
    |
    +-- $.action == "CREATE" --> CreateV1 -> Publish -> Done (Succeed)
    |
    +-- $.action == "KEEP" ------> Kept (Succeed)
    |
    +-- $.action == "NO_FEATURE" -> NoFeature (Succeed)
    |
    +-- 其他 -------------------> PipelineFailed (Fail)

任一 Task 的錯誤：
  TransientError -> Retry（等 1 秒，最多 2 次，倍率 2）
  重試用完或其他錯誤 -> Catch(States.ALL) -> PipelineFailed (Fail)
```

- [ ] **步驟 1：寫測試**

```python
# tests/unit/test_asl_ticket.py
"""ticket-analysis 的 ASL：節點順序、Retry／Catch、Choice 分支。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ASL_PATH = Path("infra/asl/ticket-analysis.asl.json")
EXPECTED_TASKS = {"Embed", "Cluster", "Recurring", "NameGap", "Decide", "CreateV1", "Publish"}


@pytest.fixture(scope="module")
def asl() -> dict:
    return json.loads(ASL_PATH.read_text(encoding="utf-8"))


def test_起點是_embed(asl):
    assert asl["StartAt"] == "Embed"


def test_七個_task_節點齊全(asl):
    tasks = {n for n, s in asl["States"].items() if s["Type"] == "Task"}
    assert tasks == EXPECTED_TASKS


def test_task_的執行順序正確(asl):
    states = asl["States"]
    assert states["Embed"]["Next"] == "Cluster"
    assert states["Cluster"]["Next"] == "Recurring"
    assert states["Recurring"]["Next"] == "IsRecurring"
    assert states["NameGap"]["Next"] == "Decide"
    assert states["Decide"]["Next"] == "ChooseAction"
    assert states["CreateV1"]["Next"] == "Publish"
    assert states["Publish"]["Next"] == "Done"


def test_每個_task_都有_retry_與_catch(asl):
    for name in EXPECTED_TASKS:
        state = asl["States"][name]
        retry = state["Retry"][0]
        assert retry["ErrorEquals"] == ["TransientError"], name
        assert retry["IntervalSeconds"] == 1, name
        assert retry["MaxAttempts"] == 2, name
        assert retry["BackoffRate"] == 2, name
        assert state["Catch"] == [{"ErrorEquals": ["States.ALL"], "Next": "PipelineFailed"}], name
        assert state["TimeoutSeconds"] == 120, name


def test_每個_task_都把_pipeline_task_state_傳給_lambda(asl):
    for name in EXPECTED_TASKS:
        state = asl["States"][name]
        assert state["Resource"] == "arn:aws:states:::lambda:invoke"
        payload = state["Parameters"]["Payload"]
        assert payload["pipeline"] == "ticket"
        assert payload["state.$"] == "$"
        assert state["Parameters"]["FunctionName"] == "${PipelineTaskFunctionArn}"
        assert state["OutputPath"] == "$.Payload"


def test_task_名稱與_phase13_的_tasks_對得起來(asl):
    from training_kb.pipelines.ticket import TASKS

    names = {asl["States"][n]["Parameters"]["Payload"]["task"] for n in EXPECTED_TASKS}
    assert names == set(TASKS)


def test_recurring_的_choice_分支(asl):
    choice = asl["States"]["IsRecurring"]
    assert choice["Type"] == "Choice"
    assert choice["Choices"][0] == {
        "Variable": "$.recurring",
        "BooleanEquals": True,
        "Next": "NameGap",
    }
    assert choice["Default"] == "NotRecurring"


def test_action_的_choice_分支(asl):
    choice = asl["States"]["ChooseAction"]
    branches = {c["StringEquals"]: c["Next"] for c in choice["Choices"]}
    assert branches == {"CREATE": "CreateV1", "KEEP": "Kept", "NO_FEATURE": "NoFeature"}
    assert choice["Default"] == "PipelineFailed"


def test_pipelinefailed_是_fail_state(asl):
    assert asl["States"]["PipelineFailed"]["Type"] == "Fail"


def test_四個成功終點都是_succeed(asl):
    for name in ("Done", "Kept", "NoFeature", "NotRecurring"):
        assert asl["States"][name]["Type"] == "Succeed", name
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：`uv run pytest tests/unit/test_asl_ticket.py -v`

預期：FAIL，錯誤訊息是 `FileNotFoundError: [Errno 2] No such file or directory: 'infra/asl/ticket-analysis.asl.json'`。

- [ ] **步驟 3：寫最少的程式讓測試通過**

先建目錄：`mkdir -p infra/asl`，再寫入下面這份檔案。

```json
{
  "Comment": "Training KB - Ticket Analysis（設計 §7.3）。每個 Task 都呼叫 training-kb-pipeline-task。",
  "StartAt": "Embed",
  "States": {
    "Embed": {
      "Type": "Task",
      "Resource": "arn:aws:states:::lambda:invoke",
      "TimeoutSeconds": 120,
      "Parameters": {
        "FunctionName": "${PipelineTaskFunctionArn}",
        "Payload": {
          "pipeline": "ticket",
          "task": "embed",
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
      "Catch": [{ "ErrorEquals": ["States.ALL"], "Next": "PipelineFailed" }],
      "Next": "Cluster"
    },
    "Cluster": {
      "Type": "Task",
      "Resource": "arn:aws:states:::lambda:invoke",
      "TimeoutSeconds": 120,
      "Parameters": {
        "FunctionName": "${PipelineTaskFunctionArn}",
        "Payload": {
          "pipeline": "ticket",
          "task": "cluster",
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
      "Catch": [{ "ErrorEquals": ["States.ALL"], "Next": "PipelineFailed" }],
      "Next": "Recurring"
    },
    "Recurring": {
      "Type": "Task",
      "Resource": "arn:aws:states:::lambda:invoke",
      "TimeoutSeconds": 120,
      "Parameters": {
        "FunctionName": "${PipelineTaskFunctionArn}",
        "Payload": {
          "pipeline": "ticket",
          "task": "recurring",
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
      "Catch": [{ "ErrorEquals": ["States.ALL"], "Next": "PipelineFailed" }],
      "Next": "IsRecurring"
    },
    "IsRecurring": {
      "Type": "Choice",
      "Choices": [{ "Variable": "$.recurring", "BooleanEquals": true, "Next": "NameGap" }],
      "Default": "NotRecurring"
    },
    "NameGap": {
      "Type": "Task",
      "Resource": "arn:aws:states:::lambda:invoke",
      "TimeoutSeconds": 120,
      "Parameters": {
        "FunctionName": "${PipelineTaskFunctionArn}",
        "Payload": {
          "pipeline": "ticket",
          "task": "name_gap",
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
      "Catch": [{ "ErrorEquals": ["States.ALL"], "Next": "PipelineFailed" }],
      "Next": "Decide"
    },
    "Decide": {
      "Type": "Task",
      "Resource": "arn:aws:states:::lambda:invoke",
      "TimeoutSeconds": 120,
      "Parameters": {
        "FunctionName": "${PipelineTaskFunctionArn}",
        "Payload": {
          "pipeline": "ticket",
          "task": "decide",
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
      "Catch": [{ "ErrorEquals": ["States.ALL"], "Next": "PipelineFailed" }],
      "Next": "ChooseAction"
    },
    "ChooseAction": {
      "Type": "Choice",
      "Choices": [
        { "Variable": "$.action", "StringEquals": "CREATE", "Next": "CreateV1" },
        { "Variable": "$.action", "StringEquals": "KEEP", "Next": "Kept" },
        { "Variable": "$.action", "StringEquals": "NO_FEATURE", "Next": "NoFeature" }
      ],
      "Default": "PipelineFailed"
    },
    "CreateV1": {
      "Type": "Task",
      "Resource": "arn:aws:states:::lambda:invoke",
      "TimeoutSeconds": 120,
      "Parameters": {
        "FunctionName": "${PipelineTaskFunctionArn}",
        "Payload": {
          "pipeline": "ticket",
          "task": "create_v1",
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
      "Catch": [{ "ErrorEquals": ["States.ALL"], "Next": "PipelineFailed" }],
      "Next": "Publish"
    },
    "Publish": {
      "Type": "Task",
      "Resource": "arn:aws:states:::lambda:invoke",
      "TimeoutSeconds": 120,
      "Parameters": {
        "FunctionName": "${PipelineTaskFunctionArn}",
        "Payload": {
          "pipeline": "ticket",
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
      "Catch": [{ "ErrorEquals": ["States.ALL"], "Next": "PipelineFailed" }],
      "Next": "Done"
    },
    "Done": { "Type": "Succeed" },
    "Kept": { "Type": "Succeed" },
    "NoFeature": { "Type": "Succeed" },
    "NotRecurring": { "Type": "Succeed" },
    "PipelineFailed": {
      "Type": "Fail",
      "Error": "PipelineFailed",
      "Cause": "Ticket Analysis 以失敗結束；不發布新版本（設計 §14.1、F49）"
    }
  }
}
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：`uv run pytest tests/unit/test_asl_ticket.py -v`

預期：PASS，10 個測試綠色。

- [ ] **步驟 5：commit**

```bash
git add tests/unit/test_asl_ticket.py infra/asl/ticket-analysis.asl.json
git commit -m "feat(infra): 加入 ticket-analysis 的 ASL 定義"
```

---

### Task 6：`infra/scripts/build_layer.py`——不用 Docker 打包相依層

**目的**：用 `uv` 把正式相依匯出成 `requirements.txt`，再安裝到 `build/layer/python/`，做成 Lambda Layer。

**檔案**：
- 新增：`infra/scripts/build_layer.py`
- 測試：`tests/unit/test_build_layer.py`

**介面**：
- 消費：無（只呼叫 `uv` 指令）
- 產出：
  - `infra.scripts.build_layer.LAYER_ROOT: Path`、`REQUIREMENTS_PATH: Path`、`SITE_PACKAGES: Path`
  - `infra.scripts.build_layer.layer_commands(python_version: str = "3.12", platform: str = "x86_64-manylinux2014") -> list[list[str]]`
  - `infra.scripts.build_layer.main(argv: list[str] | None = None) -> int`

為什麼要 `--python-platform`：你的筆電可能是 macOS 或 Apple Silicon，Lambda 跑的是 Linux。沒指定平台時裝下來的套件可能含有不能在 Lambda 上執行的二進位檔。

- [ ] **步驟 1：寫測試**

```python
# tests/unit/test_build_layer.py
"""build_layer：組出來的 uv 指令必須正確。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path("infra/scripts").resolve()))

import build_layer  # noqa: E402


def test_第一個指令是_uv_export():
    export, _install = build_layer.layer_commands()
    assert export[:2] == ["uv", "export"]
    assert "--no-dev" in export
    assert "--frozen" in export
    assert "--no-editable" in export
    assert export[export.index("-o") + 1] == str(build_layer.REQUIREMENTS_PATH)


def test_第二個指令是_uv_pip_install_到_layer_的_python_目錄():
    _export, install = build_layer.layer_commands()
    assert install[:3] == ["uv", "pip", "install"]
    assert install[install.index("--target") + 1] == str(build_layer.SITE_PACKAGES)
    assert install[install.index("-r") + 1] == str(build_layer.REQUIREMENTS_PATH)
    assert install[install.index("--python") + 1] == "3.12"
    assert install[install.index("--python-platform") + 1] == "x86_64-manylinux2014"
    assert "--no-installer-metadata" in install
    assert "--no-compile-bytecode" in install


def test_layer_的目錄結構必須是_python_子目錄():
    # Lambda Layer 的規定：Python 套件要放在壓縮檔根目錄下的 python/。
    assert build_layer.SITE_PACKAGES == build_layer.LAYER_ROOT / "python"


def test_可以改成_arm64():
    _export, install = build_layer.layer_commands(platform="aarch64-manylinux2014")
    assert install[install.index("--python-platform") + 1] == "aarch64-manylinux2014"
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：`uv run pytest tests/unit/test_build_layer.py -v`

預期：FAIL，`ModuleNotFoundError: No module named 'build_layer'`。

- [ ] **步驟 3：寫最少的程式讓測試通過**

```python
# infra/scripts/build_layer.py
"""把正式相依打包成 Lambda Layer（不使用 Docker）。

Layer 的壓縮檔結構必須是 python/<套件>，Lambda 才會把它放進 sys.path。
用法：uv run python infra/scripts/build_layer.py
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

BUILD_DIR = Path("build")
LAYER_ROOT = BUILD_DIR / "layer"
SITE_PACKAGES = LAYER_ROOT / "python"
REQUIREMENTS_PATH = BUILD_DIR / "requirements.txt"


def layer_commands(
    python_version: str = "3.12",
    platform: str = "x86_64-manylinux2014",
) -> list[list[str]]:
    """回傳要依序執行的兩個指令。抽成純函式是為了可以單獨測試。"""
    export = [
        "uv",
        "export",
        "--frozen",
        "--no-dev",
        "--no-editable",
        "--format",
        "requirements.txt",
        "-o",
        str(REQUIREMENTS_PATH),
    ]
    install = [
        "uv",
        "pip",
        "install",
        "--no-installer-metadata",
        "--no-compile-bytecode",
        "--python-platform",
        platform,
        "--python",
        python_version,
        "--target",
        str(SITE_PACKAGES),
        "-r",
        str(REQUIREMENTS_PATH),
    ]
    return [export, install]


def main(argv: list[str] | None = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    platform = args[0] if args else "x86_64-manylinux2014"

    if LAYER_ROOT.exists():
        shutil.rmtree(LAYER_ROOT)
    SITE_PACKAGES.mkdir(parents=True, exist_ok=True)

    for command in layer_commands(platform=platform):
        print("執行：", " ".join(command))
        subprocess.run(command, check=True)
    print(f"完成：{SITE_PACKAGES} 已就緒，可供 CDK 的 LayerVersion 使用")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：

```bash
uv run pytest tests/unit/test_build_layer.py -v
uv run python infra/scripts/build_layer.py
ls build/layer/python | head
```

預期：測試 4 個綠色；建置指令最後印出「完成：build/layer/python 已就緒」；`ls` 看得到 `boto3`、`pydantic` 等目錄。

> 如果你的 `uv` 版本回報 `--format` 不接受 `requirements.txt`，代表版本較舊，請把 `"requirements.txt"` 改成 `"requirements-txt"`，或執行 `uv self update` 後重試。

- [ ] **步驟 5：commit**

```bash
git add tests/unit/test_build_layer.py infra/scripts/build_layer.py
git commit -m "chore(infra): 加入不用 Docker 的 Lambda Layer 建置腳本"
```

---

### Task 7：`infra/stacks/app_stack.py`——把三個 Lambda 與流程建起來

**目的**：用 CDK 描述 Layer、三個 Lambda、Function URL、state machine 與最小權限，並用 `assertions.Template` 驗證產出的樣板。

**檔案**：
- 新增：`infra/stacks/app_stack.py`
- 修改：`infra/app.py`
- 測試：`tests/unit/test_app_stack.py`

**介面**：
- 消費：Phase 04 的 `training_kb` table 與 bucket（用名稱 import）、Task 5 的 ASL 檔、Task 6 的 `build/layer`
- 產出：
  - `infra.stacks.app_stack.TrainingKbAppStack(scope, construct_id, *, table_name, bucket_name, project_id, embed_model_id, gen_model_id, webhook_secret, **kwargs)`
  - `infra.stacks.app_stack.bedrock_model_arns(region: str, account: str, model_id: str) -> list[str]`

最小權限一覽（設計 §17.2「AWS 執行角色只授權需要的模型、表、S3 路徑與流程」）：

| Lambda | DynamoDB | S3 | Bedrock | Step Functions |
|---|---|---|---|---|
| `training-kb-webhook` | 讀寫 `training_kb` | 讀寫 bucket | 指定的兩個模型 | `StartExecution` |
| `training-kb-import` | 讀寫 `training_kb` | 讀寫 bucket | 指定的兩個模型 | `StartExecution` |
| `training-kb-pipeline-task` | 讀寫 `training_kb` | 讀寫 bucket | 指定的兩個模型 | 無 |
| state machine 的角色 | — | — | — | `InvokeFunction` 到 pipeline-task |

- [ ] **步驟 1：寫測試**

```python
# tests/unit/test_app_stack.py
"""TrainingKbAppStack：產生的 CloudFormation 樣板必須符合設計。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from aws_cdk import App, Stack
from aws_cdk.assertions import Match, Template

sys.path.insert(0, str(Path("infra").resolve()))

from stacks.app_stack import TrainingKbAppStack, bedrock_model_arns  # noqa: E402


@pytest.fixture(scope="module")
def template() -> Template:
    app = App()
    stack = TrainingKbAppStack(
        app,
        "TrainingKbAppStack",
        table_name="training_kb",
        bucket_name="training-kb-content-demo",
        project_id="demo-project",
        embed_model_id="amazon.titan-embed-text-v2:0",
        gen_model_id="us.anthropic.claude-sonnet-4-5-20250929-v1:0",
        webhook_secret="dummy-secret-for-synth",
        env={"account": "123456789012", "region": "us-east-1"},
    )
    return Template.from_stack(stack)


def test_有三個_lambda(template: Template):
    template.resource_count_is("AWS::Lambda::Function", 3)


def test_webhook_的_timeout_是_8_秒(template: Template):
    template.has_resource_properties(
        "AWS::Lambda::Function",
        {
            "FunctionName": "training-kb-webhook",
            "Timeout": 8,
            "Handler": "training_kb.handlers.webhook.handler",
            "Runtime": "python3.12",
        },
    )


def test_pipeline_task_的_timeout_是_120_秒(template: Template):
    template.has_resource_properties(
        "AWS::Lambda::Function",
        {
            "FunctionName": "training-kb-pipeline-task",
            "Timeout": 120,
            "Handler": "training_kb.handlers.pipeline_task.handler",
        },
    )


def test_function_url_的_auth_type_是_none(template: Template):
    template.has_resource_properties("AWS::Lambda::Url", {"AuthType": "NONE"})


def test_有兩條公開呼叫的_resource_policy(template: Template):
    template.has_resource_properties(
        "AWS::Lambda::Permission",
        {"Action": "lambda:InvokeFunctionUrl", "Principal": "*", "FunctionUrlAuthType": "NONE"},
    )
    template.has_resource_properties(
        "AWS::Lambda::Permission",
        {"Action": "lambda:InvokeFunction", "Principal": "*", "InvokedViaFunctionUrl": True},
    )


def test_只有_webhook_拿得到_secret(template: Template):
    template.has_resource_properties(
        "AWS::Lambda::Function",
        {
            "FunctionName": "training-kb-webhook",
            "Environment": {"Variables": Match.object_like({"TKB_GITHUB_WEBHOOK_SECRET": Match.any_value()})},
        },
    )
    functions = template.find_resources("AWS::Lambda::Function")
    with_secret = [
        name
        for name, res in functions.items()
        if "TKB_GITHUB_WEBHOOK_SECRET" in res["Properties"]["Environment"]["Variables"]
    ]
    assert len(with_secret) == 1


def test_state_machine_是_standard_且用_asl_檔(template: Template):
    template.has_resource_properties(
        "AWS::StepFunctions::StateMachine",
        {
            "StateMachineName": "training-kb-ticket-analysis",
            "StateMachineType": "STANDARD",
            "DefinitionSubstitutions": Match.object_like(
                {"PipelineTaskFunctionArn": Match.any_value()}
            ),
        },
    )


def test_有一個_layer(template: Template):
    template.resource_count_is("AWS::Lambda::LayerVersion", 1)


def test_bedrock_權限只給指定的模型(template: Template):
    template.has_resource_properties(
        "AWS::IAM::Policy",
        {
            "PolicyDocument": Match.object_like(
                {
                    "Statement": Match.array_with(
                        [
                            Match.object_like(
                                {
                                    "Action": "bedrock:InvokeModel",
                                    "Resource": Match.array_with(
                                        [
                                            "arn:aws:bedrock:us-east-1::foundation-model/"
                                            "amazon.titan-embed-text-v2:0"
                                        ]
                                    ),
                                }
                            )
                        ]
                    )
                }
            )
        },
    )


def test_bedrock_model_arns_三種寫法():
    region, account = "us-east-1", "123456789012"

    assert bedrock_model_arns(region, account, "amazon.titan-embed-text-v2:0") == [
        "arn:aws:bedrock:us-east-1::foundation-model/amazon.titan-embed-text-v2:0"
    ]
    assert bedrock_model_arns(region, account, "us.anthropic.claude-sonnet-4-5-20250929-v1:0") == [
        "arn:aws:bedrock:us-east-1:123456789012:inference-profile/"
        "us.anthropic.claude-sonnet-4-5-20250929-v1:0",
        "arn:aws:bedrock:*::foundation-model/anthropic.claude-sonnet-4-5-20250929-v1:0",
    ]
    assert bedrock_model_arns(region, account, "arn:aws:bedrock:us-east-1::foundation-model/x") == [
        "arn:aws:bedrock:us-east-1::foundation-model/x"
    ]
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：`uv run pytest tests/unit/test_app_stack.py -v`

預期：FAIL，`ModuleNotFoundError: No module named 'stacks.app_stack'`。若先看到 `FileNotFoundError: build/layer`，代表 Task 6 的建置指令還沒跑過，先執行 `uv run python infra/scripts/build_layer.py`。

- [ ] **步驟 3：寫最少的程式讓測試通過**

```python
# infra/stacks/app_stack.py
"""Training KB 的應用層資源（Phase 14 起）。

Phase 04 的 TrainingKbDataStack 已經建好 table 與 bucket，這裡只用名稱引用，
避免兩個 stack 互相卡住部署順序。
"""

from __future__ import annotations

from pathlib import Path

from aws_cdk import CfnOutput, Duration, Stack
from aws_cdk import aws_dynamodb as dynamodb
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_stepfunctions as sfn
from constructs import Construct

SRC_DIR = "src"
LAYER_DIR = "build/layer"
TICKET_ASL = "infra/asl/ticket-analysis.asl.json"


def bedrock_model_arns(region: str, account: str, model_id: str) -> list[str]:
    """把模型 ID 轉成 IAM 要用的 ARN 清單（設計 §17.1 的 O5）。

    - 已經是 ARN：原樣使用。
    - 跨區推論設定檔（inference profile，ID 以 us. / eu. / apac. 開頭）：
      需要同時允許設定檔本身與它背後的基礎模型。
    - 其他：當成基礎模型（foundation model）。
    """
    if model_id.startswith("arn:"):
        return [model_id]
    prefix = model_id.split(".", 1)[0]
    if prefix in {"us", "eu", "apac", "global"}:
        base = model_id.split(".", 1)[1]
        return [
            f"arn:aws:bedrock:{region}:{account}:inference-profile/{model_id}",
            f"arn:aws:bedrock:*::foundation-model/{base}",
        ]
    return [f"arn:aws:bedrock:{region}::foundation-model/{model_id}"]


class TrainingKbAppStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        table_name: str,
        bucket_name: str,
        project_id: str,
        embed_model_id: str,
        gen_model_id: str,
        webhook_secret: str,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        if not Path(LAYER_DIR, "python").is_dir():
            raise FileNotFoundError(
                f"找不到 {LAYER_DIR}/python，請先執行 `uv run python infra/scripts/build_layer.py`"
            )

        table = dynamodb.Table.from_table_name(self, "Table", table_name)
        bucket = s3.Bucket.from_bucket_name(self, "Bucket", bucket_name)

        layer = lambda_.LayerVersion(
            self,
            "DepsLayer",
            code=lambda_.Code.from_asset(LAYER_DIR),
            compatible_runtimes=[lambda_.Runtime.PYTHON_3_12],
            description="training-kb 的正式相依（由 uv pip install --target 產生）",
        )

        base_env = {
            "TKB_AWS_REGION": self.region,
            "TKB_TABLE_NAME": table_name,
            "TKB_BUCKET_NAME": bucket_name,
            "TKB_PROJECT_ID": project_id,
            "TKB_EMBED_MODEL_ID": embed_model_id,
            "TKB_EMBED_DIMENSIONS": "1024",
            "TKB_GEN_MODEL_ID": gen_model_id,
        }
        model_arns = bedrock_model_arns(self.region, self.account, embed_model_id) + \
            bedrock_model_arns(self.region, self.account, gen_model_id)

        def make_function(
            construct: str, name: str, handler: str, timeout_seconds: int, env: dict[str, str]
        ) -> lambda_.Function:
            fn = lambda_.Function(
                self,
                construct,
                function_name=name,
                runtime=lambda_.Runtime.PYTHON_3_12,
                handler=handler,
                code=lambda_.Code.from_asset(SRC_DIR),
                layers=[layer],
                timeout=Duration.seconds(timeout_seconds),
                memory_size=512,
                environment=env,
            )
            table.grant_read_write_data(fn)
            bucket.grant_read_write(fn)
            fn.add_to_role_policy(
                iam.PolicyStatement(actions=["bedrock:InvokeModel"], resources=model_arns)
            )
            return fn

        # 1) Task Lambda：Step Functions 的每個節點都打它。Task 上限 120 秒（設計 §14.3）。
        pipeline_task_fn = make_function(
            "PipelineTaskFunction",
            "training-kb-pipeline-task",
            "training_kb.handlers.pipeline_task.handler",
            120,
            dict(base_env),
        )

        # 2) state machine：定義直接讀 ASL 檔，用 DefinitionSubstitutions 填入 Lambda ARN。
        ticket_machine = sfn.StateMachine(
            self,
            "TicketAnalysis",
            state_machine_name="training-kb-ticket-analysis",
            state_machine_type=sfn.StateMachineType.STANDARD,
            definition_body=sfn.DefinitionBody.from_file(TICKET_ASL),
            definition_substitutions={
                "PipelineTaskFunctionArn": pipeline_task_fn.function_arn
            },
            timeout=Duration.minutes(15),
        )
        pipeline_task_fn.grant_invoke(ticket_machine)

        entry_env = dict(base_env, TKB_TICKET_STATE_MACHINE_ARN=ticket_machine.state_machine_arn)

        # 3) webhook：公開入口，8 秒內必須結束（設計 §14.3）。
        webhook_fn = make_function(
            "WebhookFunction",
            "training-kb-webhook",
            "training_kb.handlers.webhook.handler",
            8,
            dict(entry_env, TKB_GITHUB_WEBHOOK_SECRET=webhook_secret),
        )
        ticket_machine.grant_start_execution(webhook_fn)

        # 4) import：沒有公開網址，靠 IAM 驗證（設計 §7.1）。
        import_fn = make_function(
            "ImportFunction",
            "training-kb-import",
            "training_kb.handlers.import_.handler",
            120,
            dict(entry_env),
        )
        ticket_machine.grant_start_execution(import_fn)

        # Function URL：auth type NONE，驗證由程式的 HMAC 負責。
        function_url = webhook_fn.add_function_url(auth_type=lambda_.FunctionUrlAuthType.NONE)
        # CDK 會自動補 lambda:InvokeFunctionUrl；自 2025-10 起還需要 lambda:InvokeFunction，
        # 並用 InvokedViaFunctionUrl 限制成「只能從 Function URL 進來」。
        lambda_.CfnPermission(
            self,
            "WebhookUrlInvokeFunctionPermission",
            action="lambda:InvokeFunction",
            function_name=webhook_fn.function_name,
            principal="*",
            invoked_via_function_url=True,
        )

        CfnOutput(self, "WebhookUrl", value=function_url.url, description="填進 GitHub webhook 的 Payload URL")
        CfnOutput(self, "TicketStateMachineArn", value=ticket_machine.state_machine_arn)
        CfnOutput(self, "ImportFunctionName", value=import_fn.function_name)
```

接著把它掛到 CDK app（修改 `infra/app.py`，保留 Phase 04 已有的 DataStack）：

```python
# infra/app.py（新增的部分）
import os

import aws_cdk as cdk

from stacks.app_stack import TrainingKbAppStack
from stacks.data_stack import TrainingKbDataStack

app = cdk.App()
env = cdk.Environment(
    account=os.environ["CDK_DEFAULT_ACCOUNT"], region=os.environ["CDK_DEFAULT_REGION"]
)

TrainingKbDataStack(app, "TrainingKbDataStack", env=env)

TrainingKbAppStack(
    app,
    "TrainingKbAppStack",
    table_name=app.node.try_get_context("table_name") or "training_kb",
    bucket_name=app.node.try_get_context("bucket_name") or os.environ["TKB_BUCKET_NAME"],
    project_id=app.node.try_get_context("project_id") or "demo-project",
    embed_model_id=os.environ["TKB_EMBED_MODEL_ID"],
    gen_model_id=os.environ["TKB_GEN_MODEL_ID"],
    webhook_secret=os.environ["TKB_GITHUB_WEBHOOK_SECRET"],
    env=env,
)

app.synth()
```

> **關於 webhook secret 的兩種作法。** 上面把 secret 從你本機的環境變數帶進 Lambda 的環境變數。它會出現在 CloudFormation 樣板與 Lambda 設定裡，**所以絕對不能把含有真值的檔案 commit 進 Git**（設計 §17.2）。
> 如果你想改用 Secrets Manager：先手動建一個 secret，把它的 ARN 用環境變數 `TKB_GITHUB_WEBHOOK_SECRET_ARN` 傳進來，把上面 webhook 的 `environment` 換成 `dict(entry_env, TKB_GITHUB_WEBHOOK_SECRET_ARN=secret_arn)`，再加一行授權：
>
> ```python
> from aws_cdk import aws_secretsmanager as secretsmanager
>
> secret = secretsmanager.Secret.from_secret_complete_arn(self, "WebhookSecret", secret_arn)
> secret.grant_read(webhook_fn)
> ```
>
> Task 2 的 `resolve_secret()` 已經會在冷啟動時把它讀出來放進 `os.environ`，不需要改 handler。

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：

```bash
uv run pytest tests/unit/test_app_stack.py -v
uv run npx cdk synth TrainingKbAppStack > /dev/null && echo SYNTH_OK
```

預期：10 個測試綠色；`cdk synth` 最後印出 `SYNTH_OK`。

> 如果 `CfnPermission` 回報沒有 `invoked_via_function_url` 這個參數，代表 `aws-cdk-lib` 版本較舊。請先 `uv add "aws-cdk-lib>=2.220.0"`；若無法升級，就先刪掉那段 `CfnPermission`，改在部署後手動補：
> `aws lambda add-permission --function-name training-kb-webhook --statement-id UrlPolicyInvokeFunction --action lambda:InvokeFunction --principal '*' --invoked-via-function-url`

- [ ] **步驟 5：commit**

```bash
git add tests/unit/test_app_stack.py infra/stacks/app_stack.py infra/app.py
git commit -m "feat(infra): 加入 Lambda、Function URL 與 ticket-analysis state machine"
```

---

### Task 8：`infra/scripts/snapshot_asl.py`——部署前保存 ASL 快照

**目的**：依設計 §9.3 與「執行教學流程」Rule 10，把每次要部署的流程定義存到 S3 的 `stepfunctions/<pipeline>/v<n>.json`。

**檔案**：
- 新增：`infra/scripts/snapshot_asl.py`
- 測試：`tests/unit/test_snapshot_asl.py`

**介面**：
- 消費：`repository.Repository.next_counter(name) -> int`、`repository.Repository.put_object(key, body, *, if_none_match=False, content_type=...) -> bool`、`repository.build_repository(settings)`、`config.load_settings(env)`
- 產出：
  - `infra.scripts.snapshot_asl.asl_key(pipeline: str, n: int) -> str`
  - `infra.scripts.snapshot_asl.snapshot(repo, pipeline: str, path: Path) -> str`
  - `infra.scripts.snapshot_asl.main(argv: list[str] | None = None) -> int`

- [ ] **步驟 1：寫測試**

```python
# tests/unit/test_snapshot_asl.py
"""snapshot_asl：ASL 快照的 key 與內容。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path("infra/scripts").resolve()))

import snapshot_asl  # noqa: E402


class FakeRepo:
    def __init__(self):
        self.counters: dict[str, int] = {}
        self.objects: dict[str, str] = {}

    def next_counter(self, name: str) -> int:
        self.counters[name] = self.counters.get(name, 0) + 1
        return self.counters[name]

    def put_object(self, key, body, *, if_none_match=False, content_type="text/plain; charset=utf-8"):
        self.objects[key] = body if isinstance(body, str) else body.decode("utf-8")
        return True


def test_key_的格式(tmp_path):
    assert snapshot_asl.asl_key("ticket-analysis", 3) == "stepfunctions/ticket-analysis/v3.json"


def test_快照使用_next_counter_遞增版本(tmp_path):
    path = tmp_path / "x.asl.json"
    path.write_text(json.dumps({"StartAt": "A", "States": {}}), encoding="utf-8")
    repo = FakeRepo()

    first = snapshot_asl.snapshot(repo, "ticket-analysis", path)
    second = snapshot_asl.snapshot(repo, "ticket-analysis", path)

    assert first == "stepfunctions/ticket-analysis/v1.json"
    assert second == "stepfunctions/ticket-analysis/v2.json"
    assert repo.counters == {"asl:ticket-analysis": 2}


def test_快照內容與原檔逐字相同(tmp_path):
    path = tmp_path / "x.asl.json"
    original = json.dumps({"StartAt": "A", "States": {"A": {"Type": "Succeed"}}}, indent=2)
    path.write_text(original, encoding="utf-8")
    repo = FakeRepo()

    key = snapshot_asl.snapshot(repo, "ticket-analysis", path)

    assert repo.objects[key] == original


def test_不是合法_json_就不上傳(tmp_path):
    path = tmp_path / "bad.asl.json"
    path.write_text("{ not json", encoding="utf-8")
    repo = FakeRepo()

    with pytest.raises(ValueError):
        snapshot_asl.snapshot(repo, "ticket-analysis", path)
    assert repo.objects == {}


def test_真的_ticket_analysis_檔可以被快照():
    repo = FakeRepo()
    key = snapshot_asl.snapshot(
        repo, "ticket-analysis", Path("infra/asl/ticket-analysis.asl.json")
    )
    assert json.loads(repo.objects[key])["StartAt"] == "Embed"
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：`uv run pytest tests/unit/test_snapshot_asl.py -v`

預期：FAIL，`ModuleNotFoundError: No module named 'snapshot_asl'`。

- [ ] **步驟 3：寫最少的程式讓測試通過**

```python
# infra/scripts/snapshot_asl.py
"""部署前把 ASL 定義存進 S3（設計 §9.3、「執行教學流程」Rule 10）。

用法：
    uv run python infra/scripts/snapshot_asl.py ticket-analysis
    uv run python infra/scripts/snapshot_asl.py            # 快照 infra/asl 下所有檔案
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from training_kb.config import load_settings
from training_kb.repository import build_repository

ASL_DIR = Path("infra/asl")


def asl_key(pipeline: str, n: int) -> str:
    return f"stepfunctions/{pipeline}/v{n}.json"


def snapshot(repo, pipeline: str, path: Path) -> str:
    """把 `path` 的內容原樣存成下一個版本的快照，回傳 S3 key。"""
    body = path.read_text(encoding="utf-8")
    try:
        json.loads(body)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path} 不是合法 JSON，不上傳：{exc}") from exc
    n = repo.next_counter(f"asl:{pipeline}")
    key = asl_key(pipeline, n)
    repo.put_object(key, body, content_type="application/json; charset=utf-8")
    return key


def main(argv: list[str] | None = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    if args:
        paths = [ASL_DIR / f"{name}.asl.json" for name in args]
    else:
        paths = sorted(ASL_DIR.glob("*.asl.json"))
    if not paths:
        print("infra/asl 下沒有 .asl.json 檔")
        return 1

    repo = build_repository(load_settings(os.environ))
    for path in paths:
        if not path.is_file():
            print(f"找不到 {path}")
            return 1
        pipeline = path.name.removesuffix(".asl.json")
        key = snapshot(repo, pipeline, path)
        print(f"已快照 {path} -> s3://{repo.bucket}/{key}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：`uv run pytest tests/unit/test_snapshot_asl.py -v`

預期：PASS，5 個測試綠色。

- [ ] **步驟 5：commit**

```bash
git add tests/unit/test_snapshot_asl.py infra/scripts/snapshot_asl.py
git commit -m "feat(infra): 加入 ASL 快照上傳腳本"
```

---

### Task 9：部署、設定 GitHub webhook、端到端驗證 S1–S3

**目的**：把資源真的建到 AWS，把 GitHub 的 webhook 接上，再用一個整合測試證明 S1–S3 的檢查點都成立。

**檔案**：
- 新增：`tests/integration/test_webhook_e2e.py`
- 修改：`.env`（加入部署後才知道的值，不進 Git）

**介面**：
- 消費：`handlers.import_.handler`（經由 `boto3` 的 `lambda.invoke`）、`training-kb-webhook` 的 Function URL、`training-kb-ticket-analysis` 的 state machine
- 產出：一個可重跑的驗收腳本（測試檔本身）

- [ ] **步驟 1：寫測試**

```python
# tests/integration/test_webhook_e2e.py
"""端到端驗收：S1（正規化與驗簽）、S2（達門檻建 v1）、S3（發布後讀得到全文）。

需要真的 AWS 資源。只有設定 TKB_RUN_AWS_TESTS=1 時才會跑。
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
import urllib.request

import boto3
import pytest

pytestmark = pytest.mark.aws

RUN = os.environ.get("TKB_RUN_AWS_TESTS") == "1"
skip_unless_aws = pytest.mark.skipif(not RUN, reason="需要 TKB_RUN_AWS_TESTS=1 與真 AWS 資源")

WEBHOOK_URL = os.environ.get("TKB_WEBHOOK_URL", "")
SECRET = os.environ.get("TKB_GITHUB_WEBHOOK_SECRET", "")


def post(payload: dict, *, event: str, signature: str | None, delivery: str) -> tuple[int, dict]:
    body = json.dumps(payload).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "X-GitHub-Event": event,
        "X-GitHub-Delivery": delivery,
    }
    if signature is not None:
        headers["X-Hub-Signature-256"] = signature
    request = urllib.request.Request(WEBHOOK_URL, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as err:
        return err.code, json.loads(err.read())


def sign(payload: dict) -> str:
    body = json.dumps(payload).encode("utf-8")
    return "sha256=" + hmac.new(SECRET.encode("utf-8"), body, hashlib.sha256).hexdigest()


ISSUE = {
    "action": "opened",
    "issue": {
        "number": 9001,
        "title": "會前摘要在哪裡開啟？",
        "body": "我找不到會前摘要的按鈕。",
        "user": {"login": "u_01"},
    },
    "repository": {"name": "app", "owner": {"login": "acme"}},
    "sender": {"login": "u_01"},
}


@skip_unless_aws
def test_s1_一則有效的_github_事件被正規化():
    status, body = post(ISSUE, event="issues", signature=sign(ISSUE), delivery="e2e-0001")
    assert status == 200, body
    assert body["status"] in {"accepted", "duplicate"}
    assert body["id"].startswith("t_gh-")


@skip_unless_aws
def test_s1_缺少簽名的請求失敗且不建立物件():
    status, body = post(ISSUE, event="issues", signature=None, delivery="e2e-0002")
    assert status == 400
    assert body["fields"] == ["x-hub-signature-256"]


@skip_unless_aws
def test_s1_手動上傳走受控入口():
    client = boto3.client("lambda")
    payload = {
        "kind": "ticket",
        "source": "email",
        "items": [
            {
                "id": "t_e2e_manual_1",
                "source": "email",
                "text": "如何看到開會前整理的重點？",
                "author": "u_02",
                "ts": "2026-08-01T02:00:00Z",
                "project_id": os.environ["TKB_PROJECT_ID"],
            }
        ],
    }
    response = client.invoke(
        FunctionName="training-kb-import", Payload=json.dumps(payload).encode("utf-8")
    )
    result = json.loads(response["Payload"].read())
    assert result["results"][0]["status"] in {"accepted", "duplicate"}, result


@skip_unless_aws
def test_s1_重送同一事件不重複處理():
    first = post(ISSUE, event="issues", signature=sign(ISSUE), delivery="e2e-0003")
    second = post(ISSUE, event="issues", signature=sign(ISSUE), delivery="e2e-0003")
    assert first[0] == 200 and second[0] == 200
    assert second[1]["status"] == "duplicate"


@skip_unless_aws
def test_s2_s3_執行會走到終點():
    """確認最近一次 ticket-analysis 執行不是 FAILED，並印出終點供人工核對。"""
    sfn = boto3.client("stepfunctions")
    arn = os.environ["TKB_TICKET_STATE_MACHINE_ARN"]
    deadline = time.time() + 180
    latest = None
    while time.time() < deadline:
        executions = sfn.list_executions(stateMachineArn=arn, maxResults=1)["executions"]
        assert executions, "state machine 還沒有任何執行紀錄"
        latest = executions[0]
        if latest["status"] != "RUNNING":
            break
        time.sleep(5)
    assert latest is not None
    assert latest["status"] == "SUCCEEDED", f"最近一次執行是 {latest['status']}：{latest['executionArn']}"
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：`TKB_RUN_AWS_TESTS=1 uv run pytest tests/integration/test_webhook_e2e.py -v`

預期：FAIL。因為還沒部署，`TKB_WEBHOOK_URL` 是空字串，第一個測試會在 `urllib.request` 拋出 `ValueError: unknown url type`。不設 `TKB_RUN_AWS_TESTS` 時應該全部 `SKIPPED`。

- [ ] **步驟 3：寫最少的程式讓測試通過**（這一步是「部署與設定」，不是寫程式）

**3-1 建置並部署**

```bash
uv run python infra/scripts/build_layer.py
uv run npx cdk deploy TrainingKbAppStack --require-approval never
```

預期輸出：最後出現 `TrainingKbAppStack: deploying...` 後的 `✅  TrainingKbAppStack`，並印出三個 Outputs：

```text
Outputs:
TrainingKbAppStack.WebhookUrl = https://<url-id>.lambda-url.us-east-1.on.aws/
TrainingKbAppStack.TicketStateMachineArn = arn:aws:states:us-east-1:...:stateMachine:training-kb-ticket-analysis
TrainingKbAppStack.ImportFunctionName = training-kb-import
```

把前兩個寫進 `.env`（`.env` 已被 `.gitignore` 忽略）：

```bash
echo "TKB_WEBHOOK_URL=https://<url-id>.lambda-url.us-east-1.on.aws/" >> .env
echo "TKB_TICKET_STATE_MACHINE_ARN=arn:aws:states:...:stateMachine:training-kb-ticket-analysis" >> .env
```

**3-2 保存 ASL 快照**

```bash
uv run python infra/scripts/snapshot_asl.py ticket-analysis
aws s3 ls s3://$TKB_BUCKET_NAME/stepfunctions/ticket-analysis/
```

預期：第一行印出 `已快照 infra/asl/ticket-analysis.asl.json -> s3://.../stepfunctions/ticket-analysis/v1.json`；`aws s3 ls` 看得到 `v1.json`。

**3-3 設定 GitHub webhook**

在你要接的 GitHub repo：

1. 進 **Settings → Webhooks → Add webhook**。
2. **Payload URL**：貼上 `WebhookUrl`（結尾的 `/` 保留）。
3. **Content type**：選 `application/json`。這很重要——選 `application/x-www-form-urlencoded` 的話 body 會被包成表單欄位，驗簽與解析都會失敗。
4. **Secret**：貼上跟 `TKB_GITHUB_WEBHOOK_SECRET` 完全一樣的字串。
5. **Which events would you like to trigger this webhook?** 選 **Let me select individual events**，只勾 **Issues** 與 **Pull requests**，其餘取消勾選。
6. 勾選 **Active**，按 **Add webhook**。

**截圖存放位置**：新增完成後，把三張截圖存到 `docs/evidence/phase14/`（這個目錄不在 Git 追蹤範圍內就自行加進 `.gitignore`，截圖含有 repo 名稱）：

- `docs/evidence/phase14/github-webhook-config.png`：webhook 設定頁，Payload URL、Content type 與勾選的事件都要入鏡；**Secret 欄位一律遮蔽，不可入鏡**。
- `docs/evidence/phase14/github-webhook-delivery.png`：Webhooks → 該 webhook → **Recent Deliveries** 分頁，展開一筆 `issues` 事件，看得到綠色勾與 `Response 200`。
- `docs/evidence/phase14/stepfunctions-graph.png`：Step Functions 主控台 → `training-kb-ticket-analysis` → 最近一次執行的流程圖，看得到走過的節點。

**3-4 用 GitHub 的 Redeliver 做第一次驗證**

在 **Recent Deliveries** 找到 GitHub 自動送的 `ping` 事件，按 **Redeliver**；我們的程式會回 200 加 `"status": "ignored"`（`ping` 不是 `issues` 也不是 `pull_request`）。看到 200 就代表網址、資源政策與 Lambda 都通了。

接著在該 repo 開一個新 Issue，標題寫「會前摘要在哪裡開啟？」。到 Recent Deliveries 應該看到一筆 `issues` 事件，Response 是 200 且 body 含 `"status": "accepted"`。

- [ ] **步驟 4：再跑一次測試，確認通過**

```bash
set -a; source .env; set +a
TKB_RUN_AWS_TESTS=1 uv run pytest tests/integration/test_webhook_e2e.py -v
```

預期：5 個測試 PASS。若 `test_s2_s3_執行會走到終點` 失敗，到 Step Functions 主控台打開那筆執行，看是哪一個節點變紅，紅色節點的 **Exception** 分頁會顯示 `errorType`（例如 `PermanentError`）與訊息。

最後再手動確認 S3 的切片（設計 §16）：

```bash
aws s3 ls s3://$TKB_BUCKET_NAME/site/ --recursive | head
aws s3 cp s3://$TKB_BUCKET_NAME/site/index.html - | head -20
```

預期：看得到剛剛建立的教學頁（例如 `site/<slug>/v1.html`），內容是 Phase 08 的最小版教學頁。

- [ ] **步驟 5：commit**

```bash
git add tests/integration/test_webhook_e2e.py
git commit -m "test(integration): 加入 webhook 與流程的端到端驗收"
```

---

## 7. 完成檢查清單

做完打勾，每一項都要自己跑過看到結果，不能只憑印象。

- [ ] `uv run pytest tests/unit -q` 全綠。
- [ ] `uv run ruff check .` 與 `uv run ruff format --check .` 沒有錯誤。
- [ ] `uv run npx cdk synth TrainingKbAppStack` 成功，`cdk deploy` 後三個 Output 都印出來。
- [ ] `aws lambda get-function-configuration --function-name training-kb-webhook --query Timeout --output text` 回 `8`。
- [ ] `aws lambda get-policy --function-name training-kb-webhook` 看得到 `lambda:InvokeFunctionUrl` 與 `lambda:InvokeFunction` 兩條允許公開呼叫的敘述。
- [ ] `aws s3 ls s3://$TKB_BUCKET_NAME/stepfunctions/ticket-analysis/` 看得到 `v1.json`，內容與 repo 內的 ASL 逐字相同。
- [ ] **S1**：一則有效的 GitHub Issue 事件回 200 且 `status` 為 `accepted`；同一則 delivery 再送一次回 `duplicate`。
- [ ] **S1**：拿掉 `X-Hub-Signature-256` 後回 400，且 DynamoDB 沒有多出對應的 `TICKET#` item（用 `aws dynamodb get-item` 確認）。
- [ ] **S1**：`aws lambda invoke --function-name training-kb-import ...` 手動上傳一筆 Ticket，回傳 `accepted`；`training-kb-import` 沒有 Function URL（`aws lambda get-function-url-config --function-name training-kb-import` 應回 `ResourceNotFoundException`）。
- [ ] **S2**：同群工單達到 5 筆後，Step Functions 走到 `CreateV1` 與 `Publish`，DynamoDB 出現 `VERSION#<slug>@v1`。未達門檻時走到 `NotRecurring` 終點。
- [ ] **S2**：該 Feature 已有 active 教學時，執行走到 `Kept` 終點，沒有新版本。
- [ ] **S3**：發布後 `aws s3 cp s3://$TKB_BUCKET_NAME/site/<slug>/v1.html -` 讀得到完整教學全文。
- [ ] Step Functions 主控台上，任一節點的定義裡都看得到 `Retry` 與 `Catch`（可用 `aws stepfunctions describe-state-machine --state-machine-arn $TKB_TICKET_STATE_MACHINE_ARN --query definition --output text | python -m json.tool` 檢查）。
- [ ] 三張截圖已存到 `docs/evidence/phase14/`，且 Secret 欄位沒有入鏡。
- [ ] `git status --short` 沒有把 `.env`、`build/`、`cdk.out/` 列為待提交。

---

## 8. 常見錯誤與排除

**症狀 1：呼叫 Function URL 得到 `403 Forbidden`，Lambda 的 CloudWatch 完全沒有 log。**
原因：Function URL 的 auth type 雖然是 `NONE`，但 Lambda 的資源政策沒有允許公開呼叫。AWS 官方明說「`NONE` 時你的 function 仍必須有一份允許 `lambda:InvokeFunctionUrl` 與 `lambda:InvokeFunction` 的資源政策」，用 CDK／CloudFormation／CLI 建立時不會自動補齊第二條。
解法：`aws lambda get-policy --function-name training-kb-webhook | python -m json.tool` 看缺哪一條，缺什麼補什麼：

```bash
aws lambda add-permission --function-name training-kb-webhook \
  --statement-id UrlPolicyInvokeFunction --action lambda:InvokeFunction \
  --principal '*' --invoked-via-function-url
```

**症狀 2：GitHub 的 Recent Deliveries 顯示 400，回應 body 是 `{"status":"failed","fields":["x-hub-signature-256"]}`，但你確定 secret 打對了。**
原因：多半是三件事之一——(a) GitHub webhook 的 Content type 選成 `application/x-www-form-urlencoded`；(b) 你在程式裡先 `json.loads` 再 `json.dumps` 才算 HMAC；(c) Lambda 的 `TKB_GITHUB_WEBHOOK_SECRET` 和 GitHub 那邊不是同一個字串（例如多了換行）。
解法：先把 Content type 改成 `application/json`；確認 `parse_request` 回傳的是 `bytes` 且直接餵給 `verify_github_signature`；用 `aws lambda get-function-configuration --function-name training-kb-webhook --query 'Environment.Variables.TKB_GITHUB_WEBHOOK_SECRET'` 比對，注意 `echo` 會在結尾加換行，設定時用 `printf` 或直接在主控台貼上。

**症狀 3：`KeyError: 'X-Hub-Signature-256'`。**
原因：Function URL 的 payload format 2.0 把 header 名稱一律轉成小寫。
解法：一律走 `parse_request()`，它會把整份 header 轉小寫；程式裡永遠用小寫的 key 去查。

**症狀 4：Step Functions 某個節點變紅，Exception 顯示 `Lambda.Unknown`，而不是 `TransientError`。**
原因：`Lambda.Unknown`（較新的 runtime 會是 `Sandbox.Timedout`）代表 Lambda 根本沒機會回報錯誤，通常是記憶體不足或 Lambda 本身逾時。你的 `Retry` 只比對 `TransientError`，所以不會重試，會直接落到 `Catch(States.ALL)`。
解法：先看 CloudWatch log 裡的 `Duration` 與 `Max Memory Used`。逾時就把 `training-kb-pipeline-task` 的 `timeout` 調到 120 秒以內的合理值並確認 ASL 的 `TimeoutSeconds` 一致；記憶體不足就調高 `memory_size`。不要為了掩蓋問題把 `ErrorEquals` 改成 `States.ALL` 重試，那會違反設計 §14.2「區分暫時服務故障與確定非法資料，不無限重試」。

**症狀 5：`StepFunctionsStarter` 拋出「同名執行已結束但操作紀錄未完成」。**
原因：同一個操作 ID 先前已經跑過一次並結束了，但 `OPS#<operation_id>` 沒有被標成完成——通常是上一次執行中途失敗。Standard 工作流的執行名稱 90 天內不能重複使用，所以不可能用同一個名字再跑一次。
解法：`aws stepfunctions describe-execution --execution-arn <ARN>` 看上一次為什麼結束；再用 `aws dynamodb get-item --table-name training_kb --key '{"PK":{"S":"OPS#<id>"},"SK":{"S":"META"}}'` 核對操作紀錄。確認可以重跑後，由維護者以新的操作 ID 重新匯入。不要把 `ExecutionAlreadyExists` 直接當成功，也不要在程式裡自動改名重跑。

**症狀 6：`cdk deploy` 報 `Cannot find asset at .../build/layer`。**
原因：Layer 目錄還沒建，或上一次 `cdk deploy` 之後你執行了 `git clean`。
解法：`uv run python infra/scripts/build_layer.py` 重建，再確認 `ls build/layer/python` 有東西。這個目錄是建置產物，本來就不進 Git。

**症狀 7：Lambda 冷啟動就 `ImportError: No module named 'pydantic'`。**
原因：Layer 的目錄結構錯了。Lambda 只會把壓縮檔裡的 `python/` 加進 `sys.path`，所以套件必須在 `build/layer/python/` 之下，而不是 `build/layer/` 之下。
解法：確認 `build_layer.py` 的 `--target` 指到 `build/layer/python`，重新建置後再部署。

**症狀 8：state machine 執行時，每個節點的輸入都變成 `{"ExecutedVersion": ..., "Payload": ...}`。**
原因：漏掉 `"OutputPath": "$.Payload"`。用 `arn:aws:states:::lambda:invoke` 這個整合方式時，Task 的結果是整包 invoke 回應，不是 Lambda 的回傳值。
解法：每個 Task 都要有 `"OutputPath": "$.Payload"`；`tests/unit/test_asl_ticket.py` 的 `test_每個_task_都把_pipeline_task_state_傳給_lambda` 就是在守這條。

---

## 9. 這階段不做的事

- **不做 Feedback 與 View 的匯入。** `handlers/import_.py` 對 `feedback`、`view` 回 `"status": "unsupported"`，Phase 15 才接到 `ingress.import_feedback` 與 `ingress.import_view`。
- **不做 Release Note Update 的流程定義。** `infra/asl/release-update.asl.json` 與第二條 state machine 是 Phase 16 的事；`PIPELINE_MODULES` 已經預留 `release` 的位置，載入失敗時會回「pipeline 尚未實作」。
- **不做 Feedback Review 與 EventBridge 排程。** 第三條 state machine 與 `cron(30 0 * * ? *)` 是 Phase 18 的事。
- **不做 Analytics Lambda。** `handlers/analytics.py` 留給 Phase 19。
- **不做完整的靜態教學站。** 這裡只驗證 Phase 08 的最小版頁面讀得到；版本選擇、diff 檢視、回饋 widget 是 Phase 22。
- **不做失敗注入驗收。** 設計 §18 的 O2、O3 要求對三個切點注入失敗，那是 Phase 24 的整合驗收。本階段只驗證正常路徑與缺簽名這個明確的失敗路徑。
- **不承諾首次 Rote 探索一定能在 8 秒內完成。** 設計 §14.3 已經把這件事列為限制；展示前要先用受控事件累積成功流程。
- **不做 CloudFront 或 HTTPS 靜態站。** 設計 §13 明寫 S3 website endpoint 只有 HTTP，本次不把它描述成 HTTPS。
- **不做費用保證。** 設計 §17.3 說 Free Tier 取決於帳號方案，本文件不宣稱免費。

---

## 10. 對照：設計章節與 Rule 編號

| Rule 來源檔 | Rule 編號與原文 | 本階段哪個 Task 落實 |
|---|---|---|
| `接入來源事件.feature` | Rule 1：GitHub webhook 必須以 X-Hub-Signature-256 驗簽 | Task 2（`handler` 先驗簽才解析 JSON）、Task 9（步驟 3-3 設定 Secret） |
| `接入來源事件.feature` | Rule 2：沒有簽名的 GitHub webhook 請求被拒絕 | Task 2（`test_缺少簽名回_400`）、Task 9（`test_s1_缺少簽名的請求失敗且不建立物件`） |
| `接入來源事件.feature` | Rule 14：寫回新流程前 Step Functions 必須成功啟動 | Task 2（只有 `result.status == "accepted"` 才呼叫 `rote.commit_success`） |
| `接入來源事件.feature` | Rule 18：Agent 最終仍無法產出合法物件時回傳失敗 | Task 2（`IngressError`／`PermanentError` 一律回 400，不寫合法物件） |
| `接入來源事件.feature` | Rule 26：正規化成功的 Ticket 觸發 Ticket Analysis | Task 1（`StepFunctionsStarter.start`）、Task 2（`accept_ticket`） |
| `接入來源事件.feature` | Rule 27：正規化成功的 Release 觸發 Release Note Update | Task 2、Task 3（`accept_release`／`handle_manual_release`）；實際的 state machine 在 Phase 16 |
| `接入來源事件.feature` | Rule 30：同一正規化事件重送時只處理一次 | Task 1（`ExecutionAlreadyExists` 的處理）、Task 2（`duplicate` 不累加 PROC 成功）、Task 9（`test_s1_重送同一事件不重複處理`） |
| `執行教學流程.feature` | Rule 2：教學 pipeline 依 Step Functions 預定義節點執行 | Task 5（ASL 固定七個節點）、Task 7（`StateMachine`） |
| `執行教學流程.feature` | Rule 6：每個 Step Functions Task 設定 Retry | Task 5（`test_每個_task_都有_retry_與_catch`） |
| `執行教學流程.feature` | Rule 7：每個 Step Functions Task 設定 Catch | Task 5（同上）；Rule 補充「Task 重試耗盡並進入 Catch 後，整次執行以失敗結束，不發布新版本」由 `PipelineFailed` 這個 Fail state 落實 |
| `執行教學流程.feature` | Rule 10：Step Functions 的 ASL 版本快照存於 `stepfunctions/<pipeline>/v<n>.json` | Task 8（`asl_key`、`snapshot`）、Task 9（步驟 3-2） |
| `分析工單.feature` | Rule 10：Ticket Analysis 是唯一建立新 Tutorial 身分的 pipeline | Task 5（只有 `ChooseAction` 的 `CREATE` 分支會走到 `CreateV1`） |

另外對照設計文件的待確認事項：

| 編號 | 本階段怎麼處理 |
|---|---|
| O2（操作紀錄與接受順序） | **本計劃選擇**：`StepFunctionsStarter` 遇到已結束的同名執行時，讀 `OPS#<operation_id>`；紀錄顯示已完成才沿用結果，否則拋 `PermanentError` 交給人核對。完整的失敗注入驗收在 Phase 24。 |
| O3（S3 公開與發布提交） | 本階段不處理。`Publish` 節點沿用 Phase 08 的 `content.publish`，中途失敗的契約在 Phase 24 驗收。 |
| O5（模型與參數驗證） | `bedrock_model_arns()` 支援「基礎模型」與「跨區推論設定檔」兩種 ID 形式，實際可用的 ID 以 Phase 04 `check_models.py` 確認的值為準，不在這裡猜。 |
| O6（來源完整契約） | 本階段只確認 `issues` opened 與 `pull_request` closed+merged 兩種事件會進到 Rote；`STABLE_KEYS` 的補齊在 Phase 12。 |

---

## 11. 參考來源

設計文件章節（`docs/design/training-kb.md`）：

- §5 目標架構與模組責任（三個 Lambda 共用同一套模組）
- §7.1 接入：先驗證，再承認處理成功（Function URL 用 `NONE`、以原始 body 算 HMAC）
- §7.2 Rote 三層（成功條件：物件保存 + Step Functions 成功啟動）
- §7.3 Ticket Analysis 的 CREATE／KEEP 契約
- §9.3 S3 與執行資訊（`stepfunctions/<pipeline>/v<n>.json`）
- §14.1 各層如何結束、§14.2 重試不是重新抽一次文字、§14.3 執行參數的建議起點（8 秒、120 秒、重試 1 秒與 2 秒）
- §16 交付切片 S1–S3 的手動檢查
- §17.1 已查證的平台用法、§17.2 最小必要的安全處理
- §18 待確認事項 O2、O3、O5、O6

規格檔：

- `docs/spec/features/接入來源事件.feature`（Rule 1、2、14、18、26、27、30）
- `docs/spec/features/執行教學流程.feature`（Rule 2、6、7、10）
- `docs/spec/features/分析工單.feature`（Rule 10）

AWS 官方文件（2026-09-13 查證）：

- Lambda Function URL 的請求與回應格式（payload format 2.0、`headers` 小寫、`isBase64Encoded`）：<https://docs.aws.amazon.com/lambda/latest/dg/urls-invocation.html>
- Function URL 的存取控制（`NONE` 需要允許 `lambda:InvokeFunctionUrl` 與 `lambda:InvokeFunction` 的資源政策、`lambda:InvokedViaFunctionUrl` 條件鍵）：<https://docs.aws.amazon.com/lambda/latest/dg/urls-auth.html>
- Step Functions 錯誤處理（`Retry` 的 `ErrorEquals`／`IntervalSeconds`／`MaxAttempts`／`BackoffRate`、`Catch` 的 `States.ALL`、`Lambda.Unknown` 與 `Sandbox.Timedout`）：<https://docs.aws.amazon.com/step-functions/latest/dg/concepts-error-handling.html>
- Step Functions 錯誤處理教學（Task state 搭配自訂錯誤名稱的完整 ASL 範例）：<https://docs.aws.amazon.com/step-functions/latest/dg/tutorial-handling-error-conditions.html>
- Step Functions Task state 與 `arn:aws:states:::lambda:invoke` 整合：<https://docs.aws.amazon.com/step-functions/latest/dg/state-task.html>
- `StartExecution` API（Standard 工作流的冪等行為、`ExecutionAlreadyExists`、執行名稱長度 1–80 與不可用字元）：<https://docs.aws.amazon.com/step-functions/latest/apireference/API_StartExecution.html>
- AWS CDK Python：`aws_stepfunctions.DefinitionBody.from_file`：<https://docs.aws.amazon.com/cdk/api/v2/python/aws_cdk.aws_stepfunctions/FileDefinitionBody.html>
- AWS CDK Python：`aws_lambda.FunctionUrlAuthType`、`Function.add_function_url`：<https://docs.aws.amazon.com/cdk/api/v2/python/aws_cdk.aws_lambda/FunctionUrlAuthType.html>
- AWS CDK Python：`aws_lambda.CfnPermission`（`function_url_auth_type`、`invoked_via_function_url`）：<https://docs.aws.amazon.com/cdk/api/v2/python/aws_cdk.aws_lambda/CfnPermission.html>
- AWS CDK Python：`aws_lambda.LayerVersion`、`Code.from_asset`：<https://docs.aws.amazon.com/cdk/api/v2/python/aws_cdk.aws_lambda/LayerVersion.html>
- AWS CDK Python：`aws_cdk.assertions.Template`（`from_stack`、`resource_count_is`、`has_resource_properties`）：<https://docs.aws.amazon.com/cdk/api/v2/python/aws_cdk.assertions/Template.html>
- uv 的 AWS Lambda 整合指南（`uv export --frozen --no-dev --no-editable`、`uv pip install --target` 與 `--python-platform`）：<https://docs.astral.sh/uv/guides/integration/aws-lambda/>
- uv 的匯出格式（`uv export --format requirements.txt`）：<https://docs.astral.sh/uv/concepts/projects/sync/#exporting-the-lockfile>
- GitHub webhook 驗簽：<https://docs.github.com/en/webhooks/using-webhooks/validating-webhook-deliveries>
- GitHub webhook 失敗與重送處理：<https://docs.github.com/en/webhooks/using-webhooks/handling-failed-webhook-deliveries>
