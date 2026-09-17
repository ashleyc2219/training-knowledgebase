# Phase 23：Demo 控制台與 Dashboard

| 項目 | 內容 |
|---|---|
| 上一階段 | Phase 22：S3 靜態教學站（`22-Phase22-S3靜態教學站.md`） |
| 下一階段 | Phase 24：失敗復原與重送驗收（`24-Phase24-失敗復原與重送驗收.md`） |
| 對應設計文件章節 | §13、§11.4、§11.5、§12.1、§12.3、§6、§16（`docs/design/training-kb.md`） |
| 對應交付切片 | S8（設計文件第 16 節） |
| 預估時間 | 約 7 小時 |
| 做完會得到 | 一個本機命令列控制台可以觸發三條流程與匯入檔案，一個 Streamlit Dashboard 用四個區塊展示成果，外加 B 教學的規則開關隔離對照與當次真實模型呼叫數。 |

---

## 1. 這階段做完會得到什麼

做完這一階段，你會有兩個「人可以操作」的東西：

1. **`demo/cli.py`**：一個命令列工具。你在自己的電腦上打指令，它用你本機已經登入的 AWS 身分去呼叫雲端的 Lambda 與 Step Functions。它有六個子命令：
   - `seed`：把 Phase 21 準備好的種子資料載進去，並驗證 2.875／4.4／8／2／7／2／70%／20% 這幾個數字能被重算出來。
   - `trigger-ticket <ticket_json>`：送一筆工單進 import handler，啟動 Ticket Analysis。
   - `trigger-release <release_json>`：送一筆改版事件，啟動 Release Note Update。
   - `trigger-review --policy demo|formal`：直接啟動 feedback-review 這條 Step Functions。
   - `import <feedback|view> <file>`：把回饋檔或瀏覽紀錄檔匯入。
   - `metrics`：呼叫 Analytics Lambda 並在終端機印出指標表格。
2. **`demo/dashboard.py`**：一個 Streamlit 網頁（在你自己電腦上跑，網址是 `http://localhost:8501`）。它有設計文件 §13 要求的四個區塊，加上三個展示用的分頁。

另外還會產出三個支援模組：`demo/calls.py`（算當次真實模型呼叫數）、`demo/preview.py`（B 教學的規則關閉／開啟隔離對照）、`demo/view_model.py`（Dashboard 用的純計算函式，可以單獨測試）。

**這階段不會嵌入任何金鑰。** 控制台與 Dashboard 都用維護者本機已經登入的 AWS 身分（`aws configure` 或 SSO 留下的憑證），程式裡不出現 access key、secret key 或 webhook secret。

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
                                                                                        |
展示與驗收層    21 Demo 種子資料 -> 22 靜態教學站 -> 23 Demo 控制台 -> 24 失敗復原驗收 -> 25 安全與當日準備
                                                    ^^^^^^^^^^^^^^^
                                                    ★ 你在這裡 ★
```

Phase 23 是「把前面 22 個階段做好的東西擺到台面上」的階段。它自己**不新增任何業務規則**，也不改 DynamoDB 裡的教學資料；它只做三件事：觸發既有流程、讀取既有資料、把結果畫出來。

---

## 3. 開始前檢查

| # | 前置條件 | 驗證指令 | 預期輸出 |
|---|---|---|---|
| 1 | Phase 21 的種子載入工具存在 | `uv run python -c "from demo.seed_loader import load_all, verify_recipe, check_recipe, EXPECTED_RECIPE, SEED_DIR; print('ok')"` | 印出 `ok` |
| 2 | Phase 22 的 SiteRenderer 存在 | `uv run python -c "from training_kb.site import SiteRenderer; print('ok')"` | 印出 `ok` |
| 3 | Phase 19 的 Analytics 函式存在 | `uv run python -c "from training_kb.analytics import dashboard_payload, format_rating, format_rate; print('ok')"` | 印出 `ok` |
| 4 | Phase 06 的規則注入存在 | `uv run python -c "from training_kb.writing.rules import render_rules_block; print('ok')"` | 印出 `ok` |
| 5 | 本機 AWS 身分可用 | `aws sts get-caller-identity` | 印出含 `Account`、`Arn` 的 JSON，沒有 `Unable to locate credentials` |
| 6 | import Lambda 已部署（Phase 14） | `aws lambda get-function --function-name training-kb-import --query 'Configuration.FunctionName' --output text` | 印出 `training-kb-import` |
| 7 | analytics Lambda 已部署（Phase 19） | `aws lambda get-function --function-name training-kb-analytics --query 'Configuration.FunctionName' --output text` | 印出 `training-kb-analytics` |
| 8 | feedback-review 流程已部署（Phase 18） | `aws stepfunctions list-state-machines --query "stateMachines[?name=='training-kb-feedback-review'].stateMachineArn" --output text` | 印出一個 `arn:aws:states:...` 字串 |

接著安裝這階段唯一的新依賴，並確認 pytest 找得到 `demo/` 套件：

```bash
uv add streamlit
uv run streamlit version
```

預期輸出的格式是 `Streamlit, version <版本號>`，例如 `Streamlit, version 1.40.0`（版本號依安裝當下而不同，只要印得出版本就算通過）。

打開 `pyproject.toml`，確認有下面這段；沒有就加上去（Phase 01 可能已經加過，重複設定會讓 pytest 報錯，所以先確認再加）：

```toml
[tool.pytest.ini_options]
pythonpath = ["."]
markers = [
    "aws: 需要真實 AWS 環境的測試，只有 TKB_RUN_AWS_TESTS=1 才執行",
]
```

`pythonpath = ["."]` 的意思是「把 repo 根目錄放進 Python 的搜尋路徑」，這樣 `from demo.cli import build_parser` 才找得到 `demo/cli.py`。

最後把環境變數載進 shell（`.env` 是 Phase 01 建立、已被 `.gitignore` 忽略的檔案）：

```bash
set -a && source .env && set +a
echo "$TKB_TABLE_NAME"
```

預期輸出是你的表名，例如 `training_kb`。

---

## 4. 名詞小抄

| 名詞 | 白話解釋 | 在本階段哪裡用到 |
|---|---|---|
| Streamlit | 一個 Python 套件，讓你用純 Python 寫出網頁介面，不用寫 HTML 或 JavaScript。跑 `streamlit run 檔案.py` 就會在本機開一個網站。 | `demo/dashboard.py` |
| CLI（Command Line Interface） | 命令列工具，就是你在終端機輸入的指令。 | `demo/cli.py` |
| `argparse` | Python 內建套件，負責把終端機輸入的字串（例如 `trigger-review --policy demo`）拆解成程式看得懂的參數。 | Task 1 |
| 子命令（subcommand） | 一個工具底下的多個動作，例如 `git commit`、`git push` 裡的 `commit`、`push`。 | Task 1 |
| `boto3` | AWS 官方的 Python SDK，用來呼叫 AWS 服務。 | Task 3、4、5 |
| `invoke`（Lambda） | 直接叫一個 Lambda 函式跑起來並拿回它的回傳值，不需要經過網址。 | Task 3、5 |
| `start_execution`（Step Functions） | 啟動一條 state machine（流程）。回傳一個 execution ARN，是這次執行的唯一編號。 | Task 4 |
| ARN | Amazon Resource Name，AWS 資源的完整識別字串，長得像 `arn:aws:states:us-west-2:1234:stateMachine:xxx`。 | Task 4 |
| CallTrace／CallRecord | Phase 05 做的「模型呼叫紀錄本」。每送出一次 Bedrock 請求就記一筆，包含操作 ID、節點名稱、模型 ID、第幾次嘗試、成功與否。 | Task 6 |
| 重試（retry） | 同一個呼叫失敗後再送一次。設計文件 §12.1 規定：重試也要算進呼叫數。 | Task 6 |
| Map | Step Functions 裡「對清單中的每一項各做一次」的節點。每一項的模型呼叫都要分別計數。 | Task 6 |
| 隔離對照（isolated preview） | 用同一批輸入跑兩次，一次關閉規則、一次開啟規則，兩份結果都只存在展示用區域，不進正式資料。 | Task 7 |
| `demo/previews/` | 設計文件 §9.3 指定的 S3 私有路徑，專門放規則開關對照的產物。 | Task 7 |
| proxy（代理指標） | 不是直接量到的東西，而是用別的資料推估出來的近似值。重開票率就是「教學有沒有用」的 proxy。 | Task 8、9 |
| 分子／分母 | 比例的上下兩個數字。重開票率的分子是「看過教學後又開票的不同使用者數」，分母是「窗口內不同瀏覽者數」。 | Task 8、9 |
| evidence／derived_from | 規則的證據欄位。`evidence` 是一串 Feedback ID，`derived_from` 是恰好一個來源版本 ID。 | Task 9 |
| 合成資料（seeded data） | 人為編出來、明確標示不是真實觀測的示範資料。設計文件 §11.5 要求畫面必須固定標示。 | Task 8、9 |
| 預先執行結果 | 展示前先跑好、當天現場當備援用的結果。必須標示清楚，不可以說成本次現場成功。 | Task 8、9 |
| `st.session_state` | Streamlit 的「記憶體」。網頁每次互動都會從頭重跑整份 Python 檔，放在 `st.session_state` 裡的東西才不會被重置。 | Task 9 |
| `@st.cache_data` | Streamlit 的快取裝飾器。同樣的參數第二次呼叫時直接回傳上次結果，不再去打 AWS。 | Task 9 |

---

## 5. 設計說明

### 5.1 為什麼控制台不直接寫資料庫

設計文件 §5 最後一句與 §13 都寫明：「展示頁不直接寫 DynamoDB」。原因有三個：

1. **門檻只能由後端判定**（設計 §13）。如果 Dashboard 可以直接改資料，展示時就無法證明「是流程算出 CREATE，不是人手動塞的」。
2. **權限最小化**（設計 §17.2）。前端不取得寫入資料庫的憑證。
3. **可重現**。所有寫入都經過 handler 或流程，就一定留下操作紀錄與執行紀錄，Phase 24 才能驗證失敗復原。

因此控制台的寫入動作一律走這兩條路：`boto3 lambda invoke`（打 import handler）或 `boto3 stepfunctions start_execution`（啟動流程）。唯一的例外是 `seed` 子命令與 B 對照預覽：

- `seed` 是「準備展示資料」，由維護者在本機一次性執行 Phase 21 的 loader，屬於受控匯入路徑（設計 §7.1 的「手動上傳由已登入 AWS 的維護者透過 SDK 呼叫」）。
- B 對照預覽只寫 S3 的 `demo/previews/` 前綴，**不寫 DynamoDB**，符合 F47。

### 5.2 控制台 → AWS 的呼叫路徑

```text
   你的終端機                         你的瀏覽器（localhost:8501）
        |                                       |
  demo/cli.py                            demo/dashboard.py
        |                                       |
        +--- seed -------> Repository ----------+------> DynamoDB (寫：只有 seed)
        |                  (boto3)              |         S3        tutorials/、site/
        |                                       |
        +--- trigger-ticket   ---+              +------> Repository（只讀）
        +--- trigger-release  ---+                        |
        +--- import feedback  ---+--> lambda:invoke ------+--> training-kb-import
        +--- import view      ---+                        |      |
        |                                                 |      +--> ingress.accept_* / import_*
        +--- metrics ------------> lambda:invoke ---------+--> training-kb-analytics
        |                                                 |
        +--- trigger-review -----> states:StartExecution -+--> training-kb-feedback-review
                                                          |
                                    demo/preview.py ------+--> Bedrock（兩次寫作呼叫）
                                                          +--> S3 demo/previews/<run_id>/off.md
                                                          +--> S3 demo/previews/<run_id>/on.md
                                                              （不寫 DynamoDB）
```

圖中每一條箭頭都用「維護者本機 AWS 登入」的身分。程式碼裡沒有任何金鑰字串；`boto3.client("lambda")` 會自動沿用 `aws configure` 或 SSO 留下的憑證。

### 5.3 Dashboard 版面（設計 §13 的示意）

設計文件 §13 只要求四個區塊：最新教學與版本差異、每版評分與回饋數、重開票筆數及分子／分母、規則狀態與來源證據；另外要有 B 的隔離開關對照與當次執行的實際模型呼叫數。本階段照這個規模做，不建立報表平台。

```text
+==============================================================================+
| [合成資料示範]  批次：demo-seed-2026-09   時間標示：即時執行   備援：關閉      |
+==============================================================================+
| 側邊欄                |  分頁列                                              |
| ------------------    |  [教學與差異][評分][重開票][規則][B 對照][呼叫數]    |
| 資料批次  [______]    | +--------------------------------------------------+ |
| 時間標示  (o)即時     | | ① 最新教學與版本差異                             | |
|           ( )模擬     | |   準備會議（prepare-meeting@v3）                  | |
| 備援      [ ]預先執行 | |   改版原因：release:r_42                         | |
| 教學      [v] A       | |   --- 這一版全文（讀 S3 私有 tutorials/…/v3.md）--| |
| ------------------    | |   # 準備會議 / ## Problem / ## Steps …           | |
| 展示順序              | |   --- 與 v2 的完整 diff（讀 …/v3.diff）-----------| |
| 1. seed               | |   @@ -3,1 +3,1 @@                                | |
| 2. trigger-ticket     | |   -3. 開啟…選擇 Meeting Summary…                 | |
| 3. trigger-release    | |   +3. 開啟…選擇 Prepare…                         | |
| 4. trigger-review     | +--------------------------------------------------+ |
| 5. B 對照             |                                                      |
| 6. metrics            |  ② 每版評分與回饋數        ③ 重開票                  |
| 7. 失敗復原(Ph24)     |  version  avg   n  neg     筆數 7  分子 7  分母 10   |
| ------------------    |  A@v1     2.9   8   8      率 70%                    |
| 說明                  |  A@v2     4.4  10   2      （proxy 與精確定義見下）   |
|  2.9 是顯示值；        |                                                      |
|  門檻用未四捨五入值    |  ④ 規則狀態與來源證據                                |
+-----------------------+  R-007 active  evidence: f_12…f_40                    |
                        |          derived_from: prepare-meeting@v1             |
                        +--------------------------------------------------+---+
```

### 5.4 B 規則關閉／開啟隔離對照的邊界（F47）

設計文件 §11.4 與釐清 F47（`檢視學習指標_Tutorial_B_的規則開關對照是否會影響正式上架版本.md`，答案 C）規定：兩份都只是隔離的 Demo 產物。所以這個功能的寫入邊界必須非常明確：

```text
                 同一批 B（分享摘要）的工單文字
                              |
              +---------------+---------------+
              v                               v
   prompt_write_tutorial(               prompt_write_tutorial(
     gap, feature, texts,                 gap, feature, texts,
     rules_block="")                      rules_block=R-007 文字)
              |                               |
       writer.generate_json              writer.generate_json
              |                               |
       render_markdown                   render_markdown
              |                               |
              v                               v
   S3: demo/previews/<run_id>/off.md   S3: demo/previews/<run_id>/on.md
              |                               |
              +---------------+---------------+
                              |
                    可以寫的只有上面兩個 key
                              |
              +---------------+---------------+---------------+
              X               X               X               X
        TUTORIAL item    VERSION item    rules_applied     FEEDBACK
        （不寫）          （不寫）        （不寫）           （不寫）
                                                          效果統計（不算）
```

Task 7 的測試會用 moto（在本機模擬 AWS 的套件）跑一次預覽，比對執行前後整張 DynamoDB 表的內容完全相同，特別檢查沒有任何 `TUTORIAL#`、`VERSION#`、`RULE#` 開頭的項目被新增或修改。

如果現場另外要展示「正常 Ticket Analysis 建立 B v1」，那是獨立的正常流程（`trigger-ticket`），畫面上要與這兩份預覽明確分開（設計 §11.4 原話：「若另展示正常 Ticket Analysis 建立 B v1，使用獨立正常流程，並在畫面與預覽明確區分」）。

### 5.5 當次執行的實際模型呼叫數

設計文件 §12.1 與釐清 F45 規定：Bedrock 呼叫數是「每次實際送出的請求嘗試總數」，**包含 embedding、Rote、Map 的每一項、失敗與重試**；記憶體重用不算新呼叫。§12.3 另外強調：「若實際是三次呼叫就顯示三次，不為配合表格而刪掉 embedding 或 retry」。

Phase 05 的 `CallTrace` 已經以「嘗試」為單位記錄，所以這階段只要做兩件事：

1. 讓執行中的流程把 trace 存進操作紀錄（`operations/<operation_id>.json` 的 `calls` 欄位）。
2. Dashboard 讀回來分類統計。

```text
一次 Ticket Analysis 執行（operation_id = ingest:ticket:t_881）

  node            model              attempt  ok     算幾次
  --------------  -----------------  -------  -----  ------
  embed           titan-embed-v2     1        True     1     <- embedding 也算
  name_gap        claude             1        False    1     <- 失敗也算
  name_gap        claude             2        True     1     <- 重試也算
  write_tutorial  claude             1        True     1
  rote_agent      claude             1        True     1     <- Rote 層也算
  --------------------------------------------------------
  總計 total = 5    retries = 2（attempt >= 2 的筆數是 1，這裡指非首次嘗試）
```

注意：上表 `retries` 的定義是「`attempt >= 2` 的紀錄筆數」，也就是「重試了幾次」，而不是「總共送了幾次」。總共送了幾次是 `total`。

### 5.6 合成資料、真實時間與備援的標示（設計 §11.5、§12.3）

三條硬性規定，Dashboard 必須同時做到：

1. **頁面固定標示「合成資料示範」與資料批次**。不是可關掉的提示，是永遠在最上方的橫幅。
2. **即時執行用真實時間、模擬歷史資料用模擬時間，兩者不合併**。所以 Dashboard 的時間欄位一定要帶前綴（「即時 2026-09-13T…」或「模擬時間 2026-08-01T…」），而且兩種資料不放在同一張表。
3. **備援要標「預先執行結果」**。現場若改用事先跑好的結果，橫幅要同時顯示失敗原因，不能說成本次 AWS 呼叫成功。

### 5.7 展示順序腳本（設計 §6、§11.4、§16 的 S8）

S8 的檢查是：「展示兩條循環、B 隔離對照、真實呼叫數及一次儲存失敗復原」。兩條循環出自設計 §3：

```text
循環一（工單 → 教學 → 回饋 → 改善 → 規則）
  ①seed ─→ ②trigger-ticket ─→ A v1 發布 ─→（種子回饋 8 筆）
                                   │
                                   └→ ④trigger-review --policy demo
                                          └→ A v2（REFINE）+ R-007 candidate
                                                 └→ ⑥metrics：2.9→4.4、70%→20%
                                                        └→ R-007 active

循環二（改版 → 只改命中步驟）
  ③trigger-release（r_42, renamed）─→ A v3 只改第 3 步，第 1、2、4 步逐字相同
                                          └→ B、C 沒有新版

隔離對照        ⑤B 對照：同一批 B 工單，off.md / on.md 並排，兩份都不進正式資料
真實呼叫數      ⑥metrics 與 Dashboard 呼叫數分頁：顯示 trace 實際筆數
儲存失敗復原    ⑦Phase 24 提供 TKB_FAULT 開關，現場注入一次並展示舊版不變、重送後補齊
```

這份腳本的文字會寫進 `demo/view_model.py` 的 `DEMO_STEPS`，Dashboard 側邊欄直接顯示，避免現場靠記憶。

### 5.8 這階段的目錄結構

```text
AWS-Hackathon/
  demo/
    __init__.py          （空檔，讓 demo 變成可 import 的套件）
    seed/                （Phase 21 的種子 JSON）
    seed_loader.py       （Phase 21）
    site_assets/         （Phase 22）
    cli.py               ★ Task 1–5：六個子命令
    calls.py             ★ Task 6：呼叫數統計與保存
    preview.py           ★ Task 7：B 規則開關隔離對照
    view_model.py        ★ Task 8：Dashboard 用的純計算函式
    dashboard.py         ★ Task 9：Streamlit 畫面
  tests/unit/
    test_demo_cli.py     ★ Task 1–5
    test_demo_calls.py   ★ Task 6
    test_demo_view_model.py  ★ Task 8
    test_demo_dashboard_guard.py  ★ Task 9
  tests/integration/
    test_demo_preview.py ★ Task 7（moto）
```

---

## 6. 工作項目

### Task 1：`demo/cli.py` 的六個子命令與參數解析

**目的**：先把命令列的形狀定下來，讓後面每個 Task 只要填一個子命令的實作。

**檔案**：
- 新增：`demo/__init__.py`（空檔；若 Phase 21 已建立就沿用）
- 新增：`demo/cli.py`
- 測試：`tests/unit/test_demo_cli.py`

**介面**：
- 消費：無（這一步是純參數解析）
- 產出：
  - `demo.cli.build_parser() -> argparse.ArgumentParser`
  - `demo.cli.SUBCOMMANDS: tuple[str, ...]`
  - `demo.cli.main(argv: list[str] | None = None) -> int`

- [ ] **步驟 1：寫測試**

```python
# tests/unit/test_demo_cli.py
from __future__ import annotations

import pytest

from demo.cli import SUBCOMMANDS, build_parser


def test_六個子命令都存在():
    assert SUBCOMMANDS == (
        "seed",
        "trigger-ticket",
        "trigger-release",
        "trigger-review",
        "import",
        "metrics",
    )


def test_seed_預設種子目錄為_demo_seed():
    args = build_parser().parse_args(["seed"])
    assert args.command == "seed"
    assert args.dir == "demo/seed"


def test_trigger_ticket_需要一個檔案路徑():
    args = build_parser().parse_args(["trigger-ticket", "demo/seed/one_ticket.json"])
    assert args.command == "trigger-ticket"
    assert args.ticket_json == "demo/seed/one_ticket.json"


def test_trigger_release_需要一個檔案路徑():
    args = build_parser().parse_args(["trigger-release", "demo/seed/r42.json"])
    assert args.command == "trigger-release"
    assert args.release_json == "demo/seed/r42.json"


def test_trigger_review_的_policy_只接受_demo_或_formal():
    args = build_parser().parse_args(["trigger-review", "--policy", "formal"])
    assert args.policy == "formal"
    assert build_parser().parse_args(["trigger-review"]).policy == "demo"
    with pytest.raises(SystemExit):
        build_parser().parse_args(["trigger-review", "--policy", "loose"])


def test_import_只接受_feedback_或_view():
    args = build_parser().parse_args(["import", "feedback", "demo/seed/feedback.json"])
    assert (args.command, args.kind, args.file) == (
        "import",
        "feedback",
        "demo/seed/feedback.json",
    )
    with pytest.raises(SystemExit):
        build_parser().parse_args(["import", "ticket", "x.json"])


def test_metrics_可以指定教學也可以留空():
    assert build_parser().parse_args(["metrics"]).slug is None
    assert build_parser().parse_args(["metrics", "--slug", "prepare-meeting"]).slug == (
        "prepare-meeting"
    )


def test_沒有子命令時退出():
    with pytest.raises(SystemExit):
        build_parser().parse_args([])
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：`uv run pytest tests/unit/test_demo_cli.py -v`

預期：FAIL，錯誤訊息是 `ModuleNotFoundError: No module named 'demo.cli'`。因為 `demo/cli.py` 還不存在，Python 找不到這個模組。

- [ ] **步驟 3：寫最少的程式讓測試通過**

```python
# demo/__init__.py
```

（這個檔案留空。它的作用只是讓 `demo` 成為一個可以 import 的套件。）

```python
# demo/cli.py
"""Training KB Demo 控制台。

在維護者自己的電腦上執行，使用本機已登入的 AWS 身分。
程式碼不包含任何 access key、secret key 或 webhook secret。

用法：
    uv run python -m demo.cli seed
    uv run python -m demo.cli trigger-ticket demo/seed/one_ticket.json
    uv run python -m demo.cli trigger-release demo/seed/r42.json
    uv run python -m demo.cli trigger-review --policy demo
    uv run python -m demo.cli import feedback demo/seed/feedback.json
    uv run python -m demo.cli metrics --slug prepare-meeting
"""

from __future__ import annotations

import argparse
import sys

SUBCOMMANDS: tuple[str, ...] = (
    "seed",
    "trigger-ticket",
    "trigger-release",
    "trigger-review",
    "import",
    "metrics",
)


def build_parser() -> argparse.ArgumentParser:
    """建立命令列解析器。這是純函式，不碰 AWS，方便測試。"""
    parser = argparse.ArgumentParser(
        prog="demo-cli",
        description="Training KB Demo 控制台（使用本機 AWS 登入，不嵌任何金鑰）",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_seed = sub.add_parser("seed", help="載入 Demo 種子資料並驗證可重算的指標")
    p_seed.add_argument(
        "--dir", default="demo/seed", help="種子資料目錄（預設 demo/seed）"
    )

    p_ticket = sub.add_parser("trigger-ticket", help="送一筆工單並啟動 Ticket Analysis")
    p_ticket.add_argument("ticket_json", help="單筆工單的 JSON 檔路徑")

    p_release = sub.add_parser(
        "trigger-release", help="送一筆改版事件並啟動 Release Note Update"
    )
    p_release.add_argument("release_json", help="單筆 Release 的 JSON 檔路徑")

    p_review = sub.add_parser("trigger-review", help="啟動 feedback-review 流程")
    p_review.add_argument(
        "--policy",
        choices=["demo", "formal"],
        default="demo",
        help="demo 使用 n>=8 的隔離門檻，formal 使用正式的 n>=10",
    )

    p_import = sub.add_parser("import", help="匯入回饋檔或瀏覽紀錄檔")
    p_import.add_argument("kind", choices=["feedback", "view"], help="匯入種類")
    p_import.add_argument("file", help="JSON 檔路徑，內容是一個陣列")

    p_metrics = sub.add_parser("metrics", help="呼叫 Analytics Lambda 並印出指標表格")
    p_metrics.add_argument("--slug", default=None, help="只看某一篇教學，留空看全部")
    p_metrics.add_argument(
        "--local",
        action="store_true",
        help="不經過 Lambda，直接在本機用 Repository 計算（除錯用）",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    """進入點。回傳 0 代表成功，非 0 代表失敗。"""
    args = build_parser().parse_args(argv)
    print(f"尚未實作的子命令：{args.command}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：`uv run pytest tests/unit/test_demo_cli.py -v`

預期：PASS，8 個測試全綠。

- [ ] **步驟 5：commit**

```bash
git add demo/__init__.py demo/cli.py tests/unit/test_demo_cli.py
git commit -m "feat(demo): 建立控制台六個子命令的參數解析"
```

---

### Task 2：`seed` 子命令與可重算值比對

**目的**：一行指令把種子載入並當場證明 2.875／4.4／8／2／7／2／70%／20% 可以重算出來。

**檔案**：
- 修改：`demo/cli.py`
- 測試：`tests/unit/test_demo_cli.py`

**介面**：
- 消費（Phase 21，`21-Phase21-Demo種子資料與可重算驗證.md`）：
  - `demo.seed_loader.load_all(repo, renderer, *, now, seed_dir, with_feedback=True) -> dict`（依正確順序載入整套種子，回傳每種資料的筆數）
  - `demo.seed_loader.verify_recipe(repo, *, approved_categories) -> dict`（回傳八個重算值）
  - `demo.seed_loader.check_recipe(actual) -> list[str]`（比對目標值，空清單代表全中）
  - `demo.seed_loader.EXPECTED_RECIPE: dict[str, float | int]`
  - `demo.seed_loader.SEED_DIR: Path`
- 消費（其他階段）：
  - `training_kb.config.load_settings(env=None) -> Settings`（Phase 01）
  - `training_kb.repository.build_repository(settings) -> Repository`（Phase 03）
  - `training_kb.repository.Repository.get_config_list(name, default) -> list[str]`（Phase 03）
  - `training_kb.site.SiteRenderer`（Phase 08／22）
  - `training_kb.clock.now_utc() -> datetime`（Phase 01）
  - `training_kb.models.APPROVED_CATEGORIES_DEFAULT`（Phase 02）
- 產出：
  - `demo.cli.display_width(text: str) -> int`
  - `demo.cli.format_table(headers: list[str], rows: list[list[str]]) -> str`
  - `demo.cli.recipe_rows(actual: dict, expected: dict) -> list[list[str]]`
  - `demo.cli.cmd_seed(args: argparse.Namespace) -> int`

**不重複造輪子**：目標值與比對邏輯都在 Phase 21 的 `demo/seed_loader.py`。這一階段只負責「把它排成人看得懂的表格並回傳退出碼」，不另外定義一份期望值。

- [ ] **步驟 1：寫測試**

```python
# tests/unit/test_demo_cli.py（在檔尾附加）
from demo.cli import display_width, format_table, recipe_rows
from demo.seed_loader import EXPECTED_RECIPE


def test_Phase21_的期望值與設計文件_11_2_11_3_一致():
    """跨階段交叉檢查：Phase 21 的目標值就是設計文件 §11.2、§11.3 的數字。"""
    assert EXPECTED_RECIPE == {
        "A_v1_avg": 2.875,
        "A_v2_avg": 4.4,
        "A_v1_negative": 8,
        "A_v2_negative": 2,
        "A_v1_reopen": 7,
        "A_v2_reopen": 2,
        "A_v1_rate": 0.7,
        "A_v2_rate": 0.2,
    }


def test_中文字寬度算兩格():
    assert display_width("abc") == 3
    assert display_width("版本") == 4
    assert display_width("A@v1 版本") == 9


def test_表格每一列的欄位用兩個空白分隔且對齊():
    text = format_table(["版本", "平均"], [["A@v1", "2.9"], ["A@v2", "4.4"]])
    lines = text.splitlines()
    assert len(lines) == 4
    assert lines[0].startswith("版本")
    assert set(lines[1]) <= {"-", " "}
    assert lines[2].startswith("A@v1")
    assert all(display_width(line) == display_width(lines[0]) for line in lines)


def test_重算表每個指標一列而且標出相符與否():
    actual = dict(EXPECTED_RECIPE)
    rows = recipe_rows(actual, EXPECTED_RECIPE)
    assert len(rows) == len(EXPECTED_RECIPE)
    assert rows[0] == ["A_v1_avg", "2.875", "2.875", "相符"]
    assert all(row[3] == "相符" for row in rows)


def test_重算值不同時標成不符():
    actual = dict(EXPECTED_RECIPE)
    actual["A_v1_avg"] = 2.9
    rows = recipe_rows(actual, EXPECTED_RECIPE)
    bad = [row for row in rows if row[0] == "A_v1_avg"][0]
    assert bad == ["A_v1_avg", "2.9", "2.875", "不符"]


def test_缺少的重算值顯示缺少():
    actual = dict(EXPECTED_RECIPE)
    del actual["A_v2_rate"]
    bad = [row for row in recipe_rows(actual, EXPECTED_RECIPE) if row[0] == "A_v2_rate"][0]
    assert bad[1] == "（缺少）"
    assert bad[3] == "不符"


def test_None_也算不符不當成零():
    actual = dict(EXPECTED_RECIPE)
    actual["A_v1_rate"] = None
    bad = [row for row in recipe_rows(actual, EXPECTED_RECIPE) if row[0] == "A_v1_rate"][0]
    assert bad[1] == "None"
    assert bad[3] == "不符"
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：`uv run pytest tests/unit/test_demo_cli.py -v`

預期：FAIL，錯誤訊息是 `ImportError: cannot import name 'display_width' from 'demo.cli'`。因為這些名稱還沒寫進 `demo/cli.py`。

- [ ] **步驟 3：寫最少的程式讓測試通過**

先把 `demo/cli.py` 檔首的 import 區塊換成下面這一段：

```python
# demo/cli.py（檔首的 import 區塊）
from __future__ import annotations

import argparse
import json
import sys
import unicodedata
from pathlib import Path

from demo.seed_loader import (
    EXPECTED_RECIPE,
    SEED_DIR,
    check_recipe,
    load_all,
    verify_recipe,
)
from training_kb.clock import now_utc
from training_kb.config import load_settings
from training_kb.models import APPROVED_CATEGORIES_DEFAULT
from training_kb.repository import build_repository
from training_kb.site import SiteRenderer
```

接著把下面這三個函式加在 `build_parser()` 後面：

```python
# demo/cli.py（加在 build_parser() 後面）


def display_width(text: str) -> int:
    """算一段文字在終端機佔幾格。中日韓全形字算兩格。"""
    return sum(
        2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1 for ch in text
    )


def _pad(text: str, width: int) -> str:
    return text + " " * max(0, width - display_width(text))


def format_table(headers: list[str], rows: list[list[str]]) -> str:
    """把表頭與資料列排成對齊的純文字表格。"""
    widths = [display_width(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], display_width(cell))
    head = "  ".join(_pad(h, widths[i]) for i, h in enumerate(headers))
    sep = "  ".join("-" * widths[i] for i in range(len(headers)))
    body = [
        "  ".join(_pad(cell, widths[i]) for i, cell in enumerate(row)) for row in rows
    ]
    return "\n".join([head, sep, *body])


MISSING_MARK = "（缺少）"


def recipe_rows(actual: dict, expected: dict) -> list[list[str]]:
    """把重算結果排成「指標｜重算結果｜期望值｜相符與否」四欄。"""
    rows: list[list[str]] = []
    for name, want in expected.items():
        if name not in actual:
            rows.append([name, MISSING_MARK, str(want), "不符"])
            continue
        got = actual[name]
        same = got == want
        rows.append([name, str(got), str(want), "相符" if same else "不符"])
    return rows
```

最後把 `cmd_seed` 加在它們後面：

```python
# demo/cli.py（加在 recipe_rows 後面）


def cmd_seed(args: argparse.Namespace) -> int:
    """載入 Phase 21 的種子資料，然後當場驗證重算值。"""
    settings = load_settings()
    repo = build_repository(settings)
    renderer = SiteRenderer()
    seed_dir = Path(args.dir) if args.dir else SEED_DIR

    counts = load_all(repo, renderer, now=now_utc(), seed_dir=seed_dir)
    print("已載入的種子資料：")
    print(format_table(["資料", "筆數"], [[k, str(v)] for k, v in counts.items()]))

    approved = repo.get_config_list(
        "approved_categories", list(APPROVED_CATEGORIES_DEFAULT)
    )
    actual = verify_recipe(repo, approved_categories=approved)
    print("\n重算結果（設計文件 §11.2、§11.3 的目標值）：")
    print(format_table(["指標", "重算結果", "期望值", "相符"], recipe_rows(actual, EXPECTED_RECIPE)))

    problems = check_recipe(actual)
    if problems:
        print("\n重算值與設計文件不符：")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print("\n全部相符：這批種子資料可以重算出設計文件的目標數字。")
    print("這是合成資料示範，不是真實觀測或實測結果（釐清 F01、F46）。")
    return 0
```

再把 `main()` 換成有分派的版本：

```python
# demo/cli.py（把 main() 換成這一段）
def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    handlers = {"seed": cmd_seed}
    handler = handlers.get(args.command)
    if handler is None:
        print(f"尚未實作的子命令：{args.command}")
        return 1
    return handler(args)
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：`uv run pytest tests/unit/test_demo_cli.py -v`

預期：PASS。接著在有 AWS 登入的環境手動跑一次：

```bash
uv run python -m demo.cli seed
```

預期看到兩張表格：第一張是各種種子資料的筆數，第二張是四欄的重算結果，每一列的「相符」欄都是「相符」；最後兩行是「全部相符：…」與合成資料標示。如果 Phase 21 的種子還沒完成，會看到不符清單並回傳 1，這是正確行為。

- [ ] **步驟 5：commit**

```bash
git add demo/cli.py tests/unit/test_demo_cli.py
git commit -m "feat(demo): seed 子命令載入種子並比對可重算值"
```

### Task 3：`trigger-ticket` 與 `trigger-release`

**目的**：用 boto3 直接呼叫 import handler，把一筆工單或一筆改版事件送進系統。

**檔案**：
- 修改：`demo/cli.py`
- 測試：`tests/unit/test_demo_cli.py`

**介面**：
- 消費：`training_kb.handlers.import_.handler(event, context)`（Phase 14；事件格式 `{"kind": ..., "source": ..., "items": [...]}`，逐筆回傳結果）
- 產出：
  - `demo.cli.DemoTargets`（dataclass：`region`、`import_function`、`analytics_function`、`review_state_machine_arn`）
  - `demo.cli.load_targets(env: Mapping[str, str] | None = None) -> DemoTargets`
  - `demo.cli.read_json_items(path: str | Path) -> list[dict]`
  - `demo.cli.invoke_import(client, function_name: str, *, kind: str, source: str | None, items: list[dict]) -> dict`
  - `demo.cli.cmd_trigger_ticket(args) -> int`、`demo.cli.cmd_trigger_release(args) -> int`

- [ ] **步驟 1：寫測試**

```python
# tests/unit/test_demo_cli.py（在檔尾附加）
import io
import json

import pytest

from demo.cli import DemoTargets, invoke_import, load_targets, read_json_items


class FakeLambda:
    """假的 boto3 lambda client，只記下被呼叫時的參數。"""

    def __init__(self, payload: dict, function_error: str | None = None) -> None:
        self.payload = payload
        self.function_error = function_error
        self.calls: list[dict] = []

    def invoke(self, **kwargs):
        self.calls.append(kwargs)
        body = json.dumps(self.payload).encode("utf-8")
        result = {"StatusCode": 200, "Payload": io.BytesIO(body)}
        if self.function_error:
            result["FunctionError"] = self.function_error
        return result


def test_load_targets_讀環境變數並有預設函式名():
    targets = load_targets(
        {
            "TKB_AWS_REGION": "us-west-2",
            "TKB_FEEDBACK_REVIEW_ARN": "arn:aws:states:us-west-2:1:stateMachine:x",
        }
    )
    assert targets == DemoTargets(
        region="us-west-2",
        import_function="training-kb-import",
        analytics_function="training-kb-analytics",
        review_state_machine_arn="arn:aws:states:us-west-2:1:stateMachine:x",
    )


def test_load_targets_缺少_region_時拋錯並說明缺哪個():
    with pytest.raises(ValueError) as exc:
        load_targets({})
    assert "TKB_AWS_REGION" in str(exc.value)


def test_read_json_items_接受單一物件也接受陣列(tmp_path):
    one = tmp_path / "one.json"
    one.write_text(json.dumps({"id": "t_1"}), encoding="utf-8")
    many = tmp_path / "many.json"
    many.write_text(json.dumps([{"id": "t_1"}, {"id": "t_2"}]), encoding="utf-8")
    assert read_json_items(one) == [{"id": "t_1"}]
    assert len(read_json_items(many)) == 2


def test_invoke_import_送出正確的事件格式():
    client = FakeLambda({"results": [{"status": "accepted", "object_id": "t_1"}]})
    out = invoke_import(
        client,
        "training-kb-import",
        kind="ticket",
        source="github_issue",
        items=[{"id": "t_1"}],
    )
    assert out["results"][0]["status"] == "accepted"
    sent = client.calls[0]
    assert sent["FunctionName"] == "training-kb-import"
    assert sent["InvocationType"] == "RequestResponse"
    assert json.loads(sent["Payload"].decode("utf-8")) == {
        "kind": "ticket",
        "source": "github_issue",
        "items": [{"id": "t_1"}],
    }


def test_invoke_import_遇到_FunctionError_時拋錯():
    client = FakeLambda({"errorMessage": "boom"}, function_error="Unhandled")
    with pytest.raises(RuntimeError) as exc:
        invoke_import(client, "f", kind="ticket", source=None, items=[{}])
    assert "boom" in str(exc.value)
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：`uv run pytest tests/unit/test_demo_cli.py -v`

預期：FAIL，錯誤訊息是 `ImportError: cannot import name 'DemoTargets' from 'demo.cli'`。

- [ ] **步驟 3：寫最少的程式讓測試通過**

先把 `demo/cli.py` 檔首的 import 區塊換成下面這一段（比 Task 2 多了 `os`、`Mapping`、`dataclass`、`boto3`）：

```python
# demo/cli.py（檔首的 import 區塊）
from __future__ import annotations

import argparse
import json
import os
import sys
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import boto3

from demo.seed_loader import (
    EXPECTED_RECIPE,
    SEED_DIR,
    check_recipe,
    load_all,
    verify_recipe,
)
from training_kb.clock import now_utc
from training_kb.config import load_settings
from training_kb.models import APPROVED_CATEGORIES_DEFAULT
from training_kb.repository import build_repository
from training_kb.site import SiteRenderer
```

接著把下面這一段加在 `cmd_seed()` 後面：

```python
# demo/cli.py（加在 cmd_seed 後面）

DEFAULT_IMPORT_FUNCTION = "training-kb-import"
DEFAULT_ANALYTICS_FUNCTION = "training-kb-analytics"


@dataclass(frozen=True)
class DemoTargets:
    """控制台要呼叫的 AWS 目標。全部從環境變數讀，不放在程式碼裡。"""

    region: str
    import_function: str
    analytics_function: str
    review_state_machine_arn: str


def load_targets(env: Mapping[str, str] | None = None) -> DemoTargets:
    source = os.environ if env is None else env
    region = source.get("TKB_AWS_REGION", "").strip()
    if not region:
        raise ValueError("缺少環境變數 TKB_AWS_REGION；請先執行 set -a && source .env")
    return DemoTargets(
        region=region,
        import_function=source.get("TKB_IMPORT_FUNCTION", DEFAULT_IMPORT_FUNCTION),
        analytics_function=source.get(
            "TKB_ANALYTICS_FUNCTION", DEFAULT_ANALYTICS_FUNCTION
        ),
        review_state_machine_arn=source.get("TKB_FEEDBACK_REVIEW_ARN", ""),
    )


def read_json_items(path: str | Path) -> list[dict]:
    """讀一個 JSON 檔。內容是物件就包成一筆，是陣列就原樣回傳。"""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(data, dict):
        return [data]
    if isinstance(data, list):
        return list(data)
    raise ValueError(f"{path} 的內容必須是 JSON 物件或陣列")


def invoke_import(
    client, function_name: str, *, kind: str, source: str | None, items: list[dict]
) -> dict:
    """同步呼叫 import handler，回傳它的 JSON 結果。"""
    payload = {"kind": kind, "source": source, "items": items}
    response = client.invoke(
        FunctionName=function_name,
        InvocationType="RequestResponse",
        Payload=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
    )
    raw = response["Payload"].read().decode("utf-8")
    if response.get("FunctionError"):
        raise RuntimeError(f"import handler 回報錯誤：{raw}")
    return json.loads(raw)


def _print_import_results(result: dict) -> int:
    rows = [
        [
            str(item.get("object_id") or "-"),
            str(item.get("status") or "-"),
            str(item.get("message") or ""),
            "、".join(item.get("invalid_fields") or []),
        ]
        for item in result.get("results", [])
    ]
    print(format_table(["物件 ID", "結果", "訊息", "不合法欄位"], rows))
    bad = [r for r in result.get("results", []) if r.get("status") in ("failed", "rejected")]
    return 1 if bad else 0


def _run_trigger(args: argparse.Namespace, *, kind: str, path: str) -> int:
    targets = load_targets()
    items = read_json_items(path)
    source = items[0].get("source") if items else None
    client = boto3.client("lambda", region_name=targets.region)
    result = invoke_import(
        client, targets.import_function, kind=kind, source=source, items=items
    )
    code = _print_import_results(result)
    for item in result.get("results", []):
        if item.get("execution_arn"):
            print(f"已啟動流程：{item['execution_arn']}")
    return code


def cmd_trigger_ticket(args: argparse.Namespace) -> int:
    return _run_trigger(args, kind="ticket", path=args.ticket_json)


def cmd_trigger_release(args: argparse.Namespace) -> int:
    return _run_trigger(args, kind="release", path=args.release_json)
```

再把 `main()` 的 `handlers` 字典補上兩個項目：

```python
    handlers = {
        "seed": cmd_seed,
        "trigger-ticket": cmd_trigger_ticket,
        "trigger-release": cmd_trigger_release,
    }
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：`uv run pytest tests/unit/test_demo_cli.py -v`

預期：PASS。手動驗證（需要已部署的 Lambda）：

```bash
uv run python -m demo.cli trigger-ticket demo/seed/one_ticket.json
```

預期看到一張四欄表格，`結果` 欄是 `accepted`（第一次）或 `duplicate`（重送同一筆，對應 F09），以及一行 `已啟動流程：arn:aws:states:...`。

- [ ] **步驟 5：commit**

```bash
git add demo/cli.py tests/unit/test_demo_cli.py
git commit -m "feat(demo): trigger-ticket 與 trigger-release 呼叫 import handler"
```

---

### Task 4：`trigger-review` 啟動 feedback-review 流程

**目的**：手動觸發每日 Review 的同一條流程，可以選 Demo 的 n>=8 隔離門檻或正式的 n>=10。

**檔案**：
- 修改：`demo/cli.py`
- 測試：`tests/unit/test_demo_cli.py`

**介面**：
- 消費：`training_kb.ingress.execution_name(operation_id: str) -> str`（Phase 10）
- 產出：
  - `demo.cli.review_operation_id(policy: str, run_id: str) -> str`
  - `demo.cli.start_review(client, state_machine_arn: str, *, policy: str, run_id: str) -> str`
  - `demo.cli.cmd_trigger_review(args) -> int`

設計文件 §14.3 規定每日 Review 在 UTC 00:30 由 EventBridge Scheduler 啟動，input 是 `{"policy": "formal"}`；Demo 手動觸發使用同一條流程、同一套邏輯，只換 policy（設計 §7.5、釐清 F20）。

- [ ] **步驟 1：寫測試**

```python
# tests/unit/test_demo_cli.py（在檔尾附加）
from demo.cli import review_operation_id, start_review


class FakeStates:
    def __init__(self, arn: str = "arn:aws:states:us-west-2:1:execution:x:y") -> None:
        self.arn = arn
        self.calls: list[dict] = []

    def start_execution(self, **kwargs):
        self.calls.append(kwargs)
        return {"executionArn": self.arn, "startDate": None}


def test_review_的_operation_id_含_policy_與_run_id():
    assert review_operation_id("demo", "2026-09-13T0930") == (
        "review:demo:2026-09-13T0930"
    )


def test_start_review_送出_policy_與_operation_id():
    client = FakeStates()
    arn = start_review(
        client,
        "arn:aws:states:us-west-2:1:stateMachine:training-kb-feedback-review",
        policy="demo",
        run_id="r1",
    )
    assert arn == client.arn
    sent = client.calls[0]
    assert sent["stateMachineArn"].endswith("training-kb-feedback-review")
    assert ":" not in sent["name"]
    assert len(sent["name"]) <= 80
    body = json.loads(sent["input"])
    assert body == {
        "run_id": "r1",
        "operation_id": "review:demo:r1",
        "policy": "demo",
    }


def test_start_review_的_formal_門檻也能送出():
    client = FakeStates()
    start_review(client, "arn:x", policy="formal", run_id="r2")
    assert json.loads(client.calls[0]["input"])["policy"] == "formal"
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：`uv run pytest tests/unit/test_demo_cli.py -v`

預期：FAIL，`ImportError: cannot import name 'review_operation_id' from 'demo.cli'`。

- [ ] **步驟 3：寫最少的程式讓測試通過**

```python
# demo/cli.py（加在 cmd_trigger_release 後面）
# 檔首 import 區塊再加一行：from training_kb.ingress import execution_name


def review_operation_id(policy: str, run_id: str) -> str:
    """Review 這次執行的邏輯操作 ID。同一個 ID 重送只算一次邏輯處理。"""
    return f"review:{policy}:{run_id}"


def start_review(client, state_machine_arn: str, *, policy: str, run_id: str) -> str:
    """啟動 feedback-review 流程，回傳這次執行的 execution ARN。"""
    operation_id = review_operation_id(policy, run_id)
    response = client.start_execution(
        stateMachineArn=state_machine_arn,
        name=execution_name(operation_id),
        input=json.dumps(
            {"run_id": run_id, "operation_id": operation_id, "policy": policy},
            ensure_ascii=False,
        ),
    )
    return response["executionArn"]


def cmd_trigger_review(args: argparse.Namespace) -> int:
    targets = load_targets()
    if not targets.review_state_machine_arn:
        print("缺少環境變數 TKB_FEEDBACK_REVIEW_ARN；請先填入 .env")
        return 1
    run_id = now_utc().strftime("%Y%m%dT%H%M%SZ")
    client = boto3.client("stepfunctions", region_name=targets.region)
    arn = start_review(
        client,
        targets.review_state_machine_arn,
        policy=args.policy,
        run_id=run_id,
    )
    threshold = "n>=8（Demo 隔離門檻）" if args.policy == "demo" else "n>=10（正式門檻）"
    print(f"已啟動 feedback-review：{arn}")
    print(f"門檻：{threshold}；operation_id：{review_operation_id(args.policy, run_id)}")
    print("查看執行狀態：")
    print(f"  aws stepfunctions describe-execution --execution-arn {arn}")
    return 0
```

`main()` 的 `handlers` 補上 `"trigger-review": cmd_trigger_review,`。

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：`uv run pytest tests/unit/test_demo_cli.py -v`

預期：PASS。手動驗證：

```bash
uv run python -m demo.cli trigger-review --policy demo
```

預期看到三行輸出：`已啟動 feedback-review：arn:...`、`門檻：n>=8（Demo 隔離門檻）...`、以及一行可以直接貼上的 `aws stepfunctions describe-execution` 指令。

- [ ] **步驟 5：commit**

```bash
git add demo/cli.py tests/unit/test_demo_cli.py
git commit -m "feat(demo): trigger-review 啟動 feedback-review 並可選隔離門檻"
```

---

### Task 5：`import` 與 `metrics`

**目的**：匯入回饋／瀏覽檔案，以及呼叫 Analytics Lambda 把指標印成表格。

**檔案**：
- 修改：`demo/cli.py`
- 測試：`tests/unit/test_demo_cli.py`

**介面**：
- 消費（Phase 14、15）：`training_kb.handlers.import_.handler(event, context)`
- 消費（Phase 19，`19-Phase19-Analytics-學習指標.md`）：
  - `training_kb.handlers.analytics.handler(event, context) -> dict`。它讀 `event.get("slugs")`、`event.get("version_ids")`、`event.get("call_trace")`，回傳 `dashboard_payload(...)` 的結果。
  - `training_kb.analytics.dashboard_payload(repo, *, project_id, approved_categories, slugs=None, version_ids=None, call_trace=None, now) -> dict`。回傳的字典有 `generated_at`、`project_id`、`approved_categories`、`data_notice`、`versions`、`cross_version_average`、`cross_version_average_display`、`rule_counts`、`rules`、`bedrock_call_count`、`bedrock_call_source`。
  - `versions` 裡每一筆的欄位：`version_id`、`slug`、`published_at`、`avg`、`avg_display`、`n`、`negative`、`rules_applied`、`reopen{count, reopen_users, viewers, rate, rate_display}`。
  - `training_kb.analytics.format_rating(avg: float | None) -> str`、`training_kb.analytics.format_rate(rate: float | None) -> str`
- 消費（其他階段）：`training_kb.config.load_settings()`（Phase 01）、`training_kb.repository.build_repository(settings)`（Phase 03）、`training_kb.repository.Repository.get_config_list(name, default)`（Phase 03）、`training_kb.clock.now_utc()`（Phase 01）
- 產出：
  - `demo.cli.METRICS_HEADERS: list[str]`
  - `demo.cli.build_metrics_event(*, slugs: list[str] | None = None, version_ids: list[str] | None = None, call_trace: list[dict] | None = None) -> dict`
  - `demo.cli.invoke_analytics(client, function_name: str, event: dict) -> dict`
  - `demo.cli.metrics_rows(versions: list[dict]) -> list[list[str]]`
  - `demo.cli.cmd_import(args) -> int`、`demo.cli.cmd_metrics(args) -> int`

**顯示格式沿用 Phase 19**：`format_rating` 與 `format_rate` 都由 `training_kb/analytics.py` 提供，不在這裡另寫一份。所以 `0.7` 顯示成 `70%`（不是 `70.0%`），`None` 顯示成 `N/A（樣本不足）`，沒有評分顯示「尚無評分」。

- [ ] **步驟 1：寫測試**

```python
# tests/unit/test_demo_cli.py（在檔尾附加）
from demo.cli import METRICS_HEADERS, build_metrics_event, metrics_rows


def test_事件只帶_Analytics_handler_看得懂的鍵():
    assert build_metrics_event(version_ids=["a@v1", "a@v2"]) == {
        "version_ids": ["a@v1", "a@v2"]
    }
    assert build_metrics_event(slugs=["prepare-meeting"]) == {
        "slugs": ["prepare-meeting"]
    }
    assert build_metrics_event() == {}


def test_有呼叫紀錄時一起送出():
    event = build_metrics_event(call_trace=[{"node": "embed", "attempt": 1}])
    assert event["call_trace"] == [{"node": "embed", "attempt": 1}]


def test_表頭有七欄含分子分母():
    assert METRICS_HEADERS == [
        "版本",
        "平均評分",
        "回饋數",
        "負面回饋數",
        "重開票筆數",
        "分子／分母",
        "重開票率",
    ]


def test_指標列把分子分母一起放進表格():
    versions = [
        {
            "version_id": "prepare-meeting@v1",
            "avg": 2.875,
            "avg_display": "2.9",
            "n": 8,
            "negative": 8,
            "reopen": {
                "count": 7,
                "reopen_users": 7,
                "viewers": 10,
                "rate": 0.7,
                "rate_display": "70%",
            },
        },
        {
            "version_id": "prepare-meeting@v2",
            "avg": 4.4,
            "avg_display": "4.4",
            "n": 10,
            "negative": 2,
            "reopen": {
                "count": 2,
                "reopen_users": 2,
                "viewers": 10,
                "rate": 0.2,
                "rate_display": "20%",
            },
        },
    ]
    rows = metrics_rows(versions)
    assert rows[0] == ["prepare-meeting@v1", "2.9", "8", "8", "7", "7／10", "70%"]
    assert rows[1] == ["prepare-meeting@v2", "4.4", "10", "2", "2", "2／10", "20%"]


def test_沒有瀏覽者時分子分母仍完整顯示():
    versions = [
        {
            "version_id": "share-summary@v1",
            "avg": None,
            "n": 0,
            "negative": 0,
            "reopen": {"count": 0, "reopen_users": 0, "viewers": 0, "rate": None},
        }
    ]
    assert metrics_rows(versions)[0] == [
        "share-summary@v1",
        "尚無評分",
        "0",
        "0",
        "0",
        "0／0",
        "N/A（樣本不足）",
    ]


def test_沒有顯示欄位時自己用_Phase19_的格式化函式補():
    versions = [
        {
            "version_id": "a@v1",
            "avg": 2.875,
            "n": 8,
            "negative": 8,
            "reopen": {"count": 7, "reopen_users": 7, "viewers": 10, "rate": 0.7},
        }
    ]
    assert metrics_rows(versions)[0][1] == "2.9"
    assert metrics_rows(versions)[0][6] == "70%"
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：`uv run pytest tests/unit/test_demo_cli.py -v`

預期：FAIL，錯誤訊息是 `ImportError: cannot import name 'METRICS_HEADERS' from 'demo.cli'`。

- [ ] **步驟 3：寫最少的程式讓測試通過**

先在 `demo/cli.py` 檔首的 import 區塊再加一行：

```python
from training_kb.analytics import dashboard_payload, format_rate, format_rating
```

接著把下面這一段加在 `cmd_trigger_review` 後面：

```python
# demo/cli.py（加在 cmd_trigger_review 後面）

METRICS_HEADERS = [
    "版本",
    "平均評分",
    "回饋數",
    "負面回饋數",
    "重開票筆數",
    "分子／分母",
    "重開票率",
]


def build_metrics_event(
    *,
    slugs: list[str] | None = None,
    version_ids: list[str] | None = None,
    call_trace: list[dict] | None = None,
) -> dict:
    """組出 Analytics Lambda 的事件。只放 handler 讀得到的三個鍵。"""
    event: dict = {}
    if slugs is not None:
        event["slugs"] = slugs
    if version_ids is not None:
        event["version_ids"] = version_ids
    if call_trace is not None:
        event["call_trace"] = call_trace
    return event


def invoke_analytics(client, function_name: str, event: dict) -> dict:
    response = client.invoke(
        FunctionName=function_name,
        InvocationType="RequestResponse",
        Payload=json.dumps(event, ensure_ascii=False).encode("utf-8"),
    )
    raw = response["Payload"].read().decode("utf-8")
    if response.get("FunctionError"):
        raise RuntimeError(f"analytics handler 回報錯誤：{raw}")
    return json.loads(raw)


def metrics_rows(versions: list[dict]) -> list[list[str]]:
    """把 dashboard_payload 的 versions 排成七欄。"""
    rows: list[list[str]] = []
    for item in versions:
        reopen = item.get("reopen") or {}
        rows.append(
            [
                str(item.get("version_id", "-")),
                item.get("avg_display") or format_rating(item.get("avg")),
                str(item.get("n", 0)),
                str(item.get("negative", 0)),
                str(reopen.get("count", 0)),
                f"{reopen.get('reopen_users', 0)}／{reopen.get('viewers', 0)}",
                reopen.get("rate_display") or format_rate(reopen.get("rate")),
            ]
        )
    return rows


def cmd_import(args: argparse.Namespace) -> int:
    targets = load_targets()
    items = read_json_items(args.file)
    client = boto3.client("lambda", region_name=targets.region)
    result = invoke_import(
        client, targets.import_function, kind=args.kind, source=None, items=items
    )
    return _print_import_results(result)


def cmd_metrics(args: argparse.Namespace) -> int:
    settings = load_settings()
    slugs = [args.slug] if args.slug else None

    if args.local:
        repo = build_repository(settings)
        approved = repo.get_config_list(
            "approved_categories", list(APPROVED_CATEGORIES_DEFAULT)
        )
        payload = dashboard_payload(
            repo,
            project_id=settings.project_id,
            approved_categories=approved,
            slugs=slugs,
            now=now_utc(),
        )
    else:
        targets = load_targets()
        client = boto3.client("lambda", region_name=targets.region)
        payload = invoke_analytics(
            client, targets.analytics_function, build_metrics_event(slugs=slugs)
        )

    versions = payload.get("versions", [])
    if not versions:
        print("沒有任何已發布版本可以計算指標。")
        return 1

    print(format_table(METRICS_HEADERS, metrics_rows(versions)))
    counts = payload.get("rule_counts", {})
    print(
        "\n規則數：candidate {c}｜active {a}｜retired {r}".format(
            c=counts.get("candidate", 0),
            a=counts.get("active", 0),
            r=counts.get("retired", 0),
        )
    )
    print(f"跨版等權平均評分：{payload.get('cross_version_average_display', '尚無評分')}")
    print(f"本次 Bedrock 呼叫數：{payload.get('bedrock_call_count')}"
          f"（來源：{payload.get('bedrock_call_source')}）")
    print("\n重開票率是 proxy（代理指標），不是直接量到的成效。")
    print("  分子：在窗口 [published_at, published_at + 14 天) 內，先有瀏覽紀錄、")
    print("        之後又在同一個 cluster 開票的不同使用者數。")
    print("  分母：同一個窗口內的不同瀏覽者數。每版每人分子分母各最多一次。")
    print(f"資料標示：{payload.get('data_notice', '合成資料示範')}（設計 §11.5）。")
    return 0
```

最後把 `main()` 的 `handlers` 字典補成六個子命令：

```python
    handlers = {
        "seed": cmd_seed,
        "trigger-ticket": cmd_trigger_ticket,
        "trigger-release": cmd_trigger_release,
        "trigger-review": cmd_trigger_review,
        "import": cmd_import,
        "metrics": cmd_metrics,
    }
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：`uv run pytest tests/unit/test_demo_cli.py -v`

預期：PASS。手動驗證：

```bash
uv run python -m demo.cli metrics --slug prepare-meeting
```

預期看到七欄表格（版本、平均評分、回饋數、負面回饋數、重開票筆數、分子／分母、重開票率），A v1 那列是 `2.9  8  8  7  7／10  70%`，A v2 那列是 `4.4  10  2  2  2／10  20%`，下方是規則數、跨版平均、呼叫數、proxy 的精確定義與合成資料標示。

- [ ] **步驟 5：commit**

```bash
git add demo/cli.py tests/unit/test_demo_cli.py
git commit -m "feat(demo): import 與 metrics 子命令並標註 proxy 定義"
```

### Task 6：`demo/calls.py` 統計當次真實模型呼叫數

**目的**：把 CallTrace 的每一筆嘗試（含 embedding、Rote、Map、失敗與重試）統計出來，讓 Dashboard 顯示真實數字。

**檔案**：
- 新增：`demo/calls.py`
- 測試：`tests/unit/test_demo_calls.py`

**介面**：
- 消費：
  - `training_kb.writing.client.CallRecord`（欄位：`operation_id`、`node`、`model_id`、`attempt`、`ok`、`error`、`elapsed_ms`）、`CallTrace`（Phase 05）
  - `training_kb.repository.Repository.load_operation(operation_id) -> dict | None`、`update_operation(operation_id, patch)`（Phase 03）
- 產出：
  - `demo.calls.CallSummary`（dataclass：`total`、`retries`、`failed`、`by_node: dict[str, int]`、`by_kind: dict[str, int]`）
  - `demo.calls.classify_kind(model_id: str, embed_model_id: str) -> str`
  - `demo.calls.summarize_calls(records: list[CallRecord], *, embed_model_id: str) -> CallSummary`
  - `demo.calls.records_from_raw(raw: object) -> list[CallRecord]`
  - `demo.calls.record_calls(repo, operation_id: str, trace: CallTrace) -> None`
  - `demo.calls.load_call_records(repo, operation_id: str) -> list[CallRecord]`

- [ ] **步驟 1：寫測試**

```python
# tests/unit/test_demo_calls.py
from __future__ import annotations

import json

from demo.calls import (
    CallSummary,
    classify_kind,
    load_call_records,
    record_calls,
    records_from_raw,
    summarize_calls,
)
from training_kb.writing.client import CallRecord, CallTrace

EMBED = "amazon.titan-embed-text-v2:0"
GEN = "anthropic.claude-x"


def _records() -> list[CallRecord]:
    return [
        CallRecord("op1", "embed", EMBED, 1, True, None, 120),
        CallRecord("op1", "name_gap", GEN, 1, False, "ThrottlingException", 900),
        CallRecord("op1", "name_gap", GEN, 2, True, None, 850),
        CallRecord("op1", "write_tutorial", GEN, 1, True, None, 3100),
        CallRecord("op1", "rote_agent", GEN, 1, True, None, 700),
        CallRecord("op1", "map_item", GEN, 1, True, None, 400),
        CallRecord("op1", "map_item", GEN, 1, True, None, 410),
    ]


def test_embedding_與生成分開分類():
    assert classify_kind(EMBED, EMBED) == "embedding"
    assert classify_kind(GEN, EMBED) == "generation"


def test_總數是每次實際送出的嘗試數():
    summary = summarize_calls(_records(), embed_model_id=EMBED)
    assert summary.total == 7


def test_重試次數只算非首次嘗試():
    assert summarize_calls(_records(), embed_model_id=EMBED).retries == 1


def test_失敗的嘗試也計入總數():
    summary = summarize_calls(_records(), embed_model_id=EMBED)
    assert summary.failed == 1
    assert summary.total == 7


def test_每個_Map_項目分別計數():
    summary = summarize_calls(_records(), embed_model_id=EMBED)
    assert summary.by_node["map_item"] == 2


def test_embedding_與_Rote_都在統計裡():
    summary = summarize_calls(_records(), embed_model_id=EMBED)
    assert summary.by_kind == {"embedding": 1, "generation": 6}
    assert summary.by_node["rote_agent"] == 1
    assert summary.by_node["embed"] == 1


def test_空清單得到全零():
    assert summarize_calls([], embed_model_id=EMBED) == CallSummary(
        total=0, retries=0, failed=0, by_node={}, by_kind={}
    )


def test_從字典與從_JSON_字串都能還原紀錄():
    raw_list = [r.__dict__ for r in _records()]
    assert len(records_from_raw(raw_list)) == 7
    assert len(records_from_raw(json.dumps(raw_list))) == 7
    assert records_from_raw(None) == []


class FakeRepo:
    def __init__(self) -> None:
        self.store: dict[str, dict] = {}

    def load_operation(self, operation_id: str):
        return self.store.get(operation_id)

    def update_operation(self, operation_id: str, patch: dict) -> None:
        self.store.setdefault(operation_id, {}).update(patch)


def test_record_calls_會累加而不是覆蓋():
    repo = FakeRepo()
    repo.store["op1"] = {"kind": "ticket"}
    first = CallTrace()
    first.add(CallRecord("op1", "embed", EMBED, 1, True, None, 10))
    record_calls(repo, "op1", first)
    second = CallTrace()
    second.add(CallRecord("op1", "name_gap", GEN, 1, True, None, 20))
    record_calls(repo, "op1", second)

    loaded = load_call_records(repo, "op1")
    assert [r.node for r in loaded] == ["embed", "name_gap"]
    assert repo.store["op1"]["kind"] == "ticket"


def test_沒有操作紀錄時回傳空清單():
    assert load_call_records(FakeRepo(), "missing") == []
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：`uv run pytest tests/unit/test_demo_calls.py -v`

預期：FAIL，`ModuleNotFoundError: No module named 'demo.calls'`。

- [ ] **步驟 3：寫最少的程式讓測試通過**

```python
# demo/calls.py
"""統計一次執行實際送出的 Bedrock 呼叫。

設計文件 §12.1 與釐清 F45：呼叫數是「每次實際送出的請求嘗試總數」，
包含 embedding、Rote 層、Step Functions Map 的每一項、失敗與重試；
記憶體重用不算新呼叫。設計 §12.3：實際幾次就顯示幾次。
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from training_kb.writing.client import CallRecord, CallTrace

OPERATION_CALLS_FIELD = "calls"


@dataclass(frozen=True)
class CallSummary:
    """一次執行的呼叫統計。"""

    total: int
    retries: int
    failed: int
    by_node: dict[str, int] = field(default_factory=dict)
    by_kind: dict[str, int] = field(default_factory=dict)


def classify_kind(model_id: str, embed_model_id: str) -> str:
    """把一次呼叫分成 embedding 或 generation。"""
    return "embedding" if model_id == embed_model_id else "generation"


def summarize_calls(
    records: list[CallRecord], *, embed_model_id: str
) -> CallSummary:
    by_node: Counter[str] = Counter()
    by_kind: Counter[str] = Counter()
    retries = 0
    failed = 0
    for record in records:
        by_node[record.node] += 1
        by_kind[classify_kind(record.model_id, embed_model_id)] += 1
        if record.attempt >= 2:
            retries += 1
        if not record.ok:
            failed += 1
    return CallSummary(
        total=len(records),
        retries=retries,
        failed=failed,
        by_node=dict(by_node),
        by_kind=dict(by_kind),
    )


def records_from_raw(raw: Any) -> list[CallRecord]:
    """把操作紀錄裡的 calls 欄位轉回 CallRecord 清單。"""
    if raw is None:
        return []
    if isinstance(raw, str):
        raw = json.loads(raw)
    if not isinstance(raw, list):
        return []
    out: list[CallRecord] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        out.append(
            CallRecord(
                operation_id=str(item.get("operation_id", "")),
                node=str(item.get("node", "")),
                model_id=str(item.get("model_id", "")),
                attempt=int(item.get("attempt", 1)),
                ok=bool(item.get("ok", False)),
                error=item.get("error"),
                elapsed_ms=int(item.get("elapsed_ms", 0)),
            )
        )
    return out


def record_calls(repo, operation_id: str, trace: CallTrace) -> None:
    """把這次 Task 的呼叫紀錄附加到操作紀錄，不覆蓋既有紀錄。"""
    existing = repo.load_operation(operation_id) or {}
    merged = [r.__dict__ for r in records_from_raw(existing.get(OPERATION_CALLS_FIELD))]
    merged.extend(r.__dict__ for r in trace.records)
    repo.update_operation(operation_id, {OPERATION_CALLS_FIELD: merged})


def load_call_records(repo, operation_id: str) -> list[CallRecord]:
    """讀回某次邏輯操作的全部呼叫紀錄。"""
    record = repo.load_operation(operation_id)
    if record is None:
        return []
    return records_from_raw(record.get(OPERATION_CALLS_FIELD))
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：`uv run pytest tests/unit/test_demo_calls.py -v`

預期：PASS，11 個測試全綠。

- [ ] **步驟 5：commit**

```bash
git add demo/calls.py tests/unit/test_demo_calls.py
git commit -m "feat(demo): 統計含重試與 Map 的實際模型呼叫數"
```

---

### Task 7：`demo/preview.py` B 教學的規則關閉／開啟隔離對照

**目的**：用同一批 B 的工單各呼叫一次 `prompt_write_tutorial`，一次 `rules_block=""`、一次注入 R-007，兩份輸出只寫 S3 的 `demo/previews/<run_id>/`。

**檔案**：
- 新增：`demo/preview.py`
- 測試：`tests/integration/test_demo_preview.py`（用 moto）

**介面**：
- 消費：
  - `training_kb.writing.prompts.prompt_write_tutorial(gap, feature, evidence_texts, rules_block) -> tuple[str, str]`（Phase 05／06）
  - `training_kb.writing.rules.render_rules_block(rules) -> str`（Phase 06）
  - `training_kb.writing.client.Writer.generate_json(...)`、`FakeWriter`（Phase 05）
  - `training_kb.writing.schemas.TutorialDraft`（Phase 05）
  - `training_kb.content.render_markdown(content) -> str`、`validate_content(content, known_feature_ids)`（Phase 07）
  - `training_kb.models.TutorialContent`、`Feature`、`AuthoringRule`（Phase 02）
  - `training_kb.repository.Repository.put_object(key, body, *, content_type=...)`（Phase 03）
- 產出：
  - `demo.preview.PREVIEW_PREFIX = "demo/previews/"`
  - `demo.preview.preview_keys(run_id: str) -> dict[str, str]`
  - `demo.preview.PreviewSide`（dataclass：`label`、`key`、`markdown`、`rule_ids`、`valid`、`problem`）
  - `demo.preview.PreviewResult`（dataclass：`run_id`、`off`、`on`）
  - `demo.preview.run_rule_toggle_preview(repo, writer, settings, *, run_id, gap, feature, evidence_texts, rule, known_feature_ids) -> PreviewResult`

- [ ] **步驟 1：寫測試**

```python
# tests/integration/test_demo_preview.py
from __future__ import annotations

import boto3
import pytest
from moto import mock_aws

from demo.preview import PREVIEW_PREFIX, preview_keys, run_rule_toggle_preview
from training_kb.config import load_settings
from training_kb.models import (
    AuthoringRule,
    Feature,
    RuleStatus,
    StepDraft,
    StepType,
    TutorialContent,
)
from training_kb.repository import Repository
from training_kb.writing.client import CallTrace, FakeWriter

REGION = "us-west-2"
TABLE = "training_kb_preview_test"
BUCKET = "training-kb-preview-test"


def _draft(marker: str) -> TutorialContent:
    return TutorialContent(
        title=f"分享摘要（{marker}）",
        problem="使用者不知道怎麼把摘要分享出去。",
        prerequisites=["已經產生一份會議摘要"],
        steps=[
            StepDraft(
                type=StepType.click_ui,
                text=f"在摘要頁右上角點選分享（{marker}）",
                feature_id="Share Summary",
            )
        ],
        expected_outcome="對方收到摘要連結。",
    )


@pytest.fixture()
def repo(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", REGION)
    with mock_aws():
        ddb = boto3.resource("dynamodb", region_name=REGION)
        ddb.create_table(
            TableName=TABLE,
            KeySchema=[
                {"AttributeName": "PK", "KeyType": "HASH"},
                {"AttributeName": "SK", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "PK", "AttributeType": "S"},
                {"AttributeName": "SK", "AttributeType": "S"},
                {"AttributeName": "target", "AttributeType": "S"},
            ],
            GlobalSecondaryIndexes=[
                {
                    "IndexName": "by_target",
                    "KeySchema": [{"AttributeName": "target", "KeyType": "HASH"}],
                    "Projection": {"ProjectionType": "ALL"},
                }
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        s3 = boto3.client("s3", region_name=REGION)
        s3.create_bucket(
            Bucket=BUCKET,
            CreateBucketConfiguration={"LocationConstraint": REGION},
        )
        yield Repository(ddb.Table(TABLE), s3, BUCKET)


def _settings(monkeypatch):
    monkeypatch.setenv("TKB_AWS_REGION", REGION)
    monkeypatch.setenv("TKB_TABLE_NAME", TABLE)
    monkeypatch.setenv("TKB_BUCKET_NAME", BUCKET)
    monkeypatch.setenv("TKB_PROJECT_ID", "demo-project")
    monkeypatch.setenv("TKB_EMBED_MODEL_ID", "amazon.titan-embed-text-v2:0")
    monkeypatch.setenv("TKB_EMBED_DIMENSIONS", "1024")
    monkeypatch.setenv("TKB_GEN_MODEL_ID", "anthropic.claude-x")
    monkeypatch.setenv("TKB_GITHUB_WEBHOOK_SECRET", "not-a-real-secret")
    return load_settings()


def _run(repo, monkeypatch):
    settings = _settings(monkeypatch)
    writer = FakeWriter(outputs=[_draft("off"), _draft("on")], trace=CallTrace())
    rule = AuthoringRule(
        rule_id="R-007",
        rule="click_ui 步驟要寫出按鈕在哪一頁與位置",
        applies_when={"step.type": "click_ui"},
        evidence=["f_12", "f_15", "f_19", "f_23", "f_27"],
        status=RuleStatus.active,
        applied_to=[],
        derived_from="prepare-meeting@v1",
        validated_at="2026-08-25T00:00:00Z",
    )
    feature = Feature(
        feature_id="Share Summary",
        name="Share Summary",
        aliases=[],
        first_seen="2026-08-01T00:00:00Z",
    )
    return run_rule_toggle_preview(
        repo,
        writer,
        settings,
        run_id="b-preview-01",
        gap="使用者不知道怎麼分享摘要",
        feature=feature,
        evidence_texts=["怎麼把摘要寄給同事？", "分享按鈕在哪裡？"],
        rule=rule,
        known_feature_ids={"Share Summary"},
    )


def test_預覽只寫兩個_demo_previews_物件(repo, monkeypatch):
    result = _run(repo, monkeypatch)
    keys = preview_keys("b-preview-01")
    assert result.off.key == keys["off"] == f"{PREVIEW_PREFIX}b-preview-01/off.md"
    assert result.on.key == keys["on"] == f"{PREVIEW_PREFIX}b-preview-01/on.md"

    listed = repo.s3.list_objects_v2(Bucket=BUCKET)
    got = sorted(obj["Key"] for obj in listed.get("Contents", []))
    assert got == sorted([keys["off"], keys["on"]])


def test_預覽不寫任何_DynamoDB_資料(repo, monkeypatch):
    before = repo.table.scan()["Items"]
    _run(repo, monkeypatch)
    after = repo.table.scan()["Items"]
    assert before == after == []


def test_預覽不新增_TUTORIAL_與_RULE_項目(repo, monkeypatch):
    _run(repo, monkeypatch)
    items = repo.table.scan()["Items"]
    prefixes = {str(item["PK"]).split("#", 1)[0] for item in items}
    assert "TUTORIAL" not in prefixes
    assert "VERSION" not in prefixes
    assert "RULE" not in prefixes
    assert "FEEDBACK" not in prefixes


def test_關閉那份沒有注入規則開啟那份有(repo, monkeypatch):
    result = _run(repo, monkeypatch)
    assert result.off.rule_ids == []
    assert result.on.rule_ids == ["R-007"]
    assert result.off.label == "規則關閉"
    assert result.on.label == "規則開啟（R-007）"


def test_兩份內容都可以讀回來而且不同(repo, monkeypatch):
    result = _run(repo, monkeypatch)
    off_body = repo.get_object(result.off.key).decode("utf-8")
    on_body = repo.get_object(result.on.key).decode("utf-8")
    assert "off" in off_body
    assert "on" in on_body
    assert off_body != on_body
    assert result.off.valid is True
    assert result.on.valid is True


def test_沒有寫到_site_或_tutorials_前綴(repo, monkeypatch):
    _run(repo, monkeypatch)
    listed = repo.s3.list_objects_v2(Bucket=BUCKET)
    for obj in listed.get("Contents", []):
        assert not obj["Key"].startswith("site/")
        assert not obj["Key"].startswith("tutorials/")
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：`uv run pytest tests/integration/test_demo_preview.py -v`

預期：FAIL，`ModuleNotFoundError: No module named 'demo.preview'`。

- [ ] **步驟 3：寫最少的程式讓測試通過**

```python
# demo/preview.py
"""Tutorial B 的規則關閉／開啟隔離對照。

設計文件 §11.4 與釐清 F47（答案 C）：兩份都只是隔離的 Demo 產物，
不寫入正式教學、rules_applied、回饋或規則效果統計。
因此這個模組唯一的寫入是 S3 的 demo/previews/<run_id>/ 兩個 key，
完全不碰 DynamoDB。
"""

from __future__ import annotations

from dataclasses import dataclass

from training_kb.config import Settings
from training_kb.content import render_markdown, validate_content
from training_kb.errors import ContentError
from training_kb.models import AuthoringRule, Feature, TutorialContent
from training_kb.writing.prompts import prompt_write_tutorial
from training_kb.writing.rules import render_rules_block
from training_kb.writing.schemas import TutorialDraft

PREVIEW_PREFIX = "demo/previews/"
MARKDOWN_CONTENT_TYPE = "text/markdown; charset=utf-8"


def preview_keys(run_id: str) -> dict[str, str]:
    """這次對照要寫的兩個 S3 key。只有這兩個可以寫。"""
    return {
        "off": f"{PREVIEW_PREFIX}{run_id}/off.md",
        "on": f"{PREVIEW_PREFIX}{run_id}/on.md",
    }


@dataclass(frozen=True)
class PreviewSide:
    """對照的其中一邊。"""

    label: str
    key: str
    markdown: str
    rule_ids: list[str]
    valid: bool
    problem: str | None


@dataclass(frozen=True)
class PreviewResult:
    run_id: str
    off: PreviewSide
    on: PreviewSide


def _one_side(
    repo,
    writer,
    settings: Settings,
    *,
    label: str,
    key: str,
    node: str,
    operation_id: str,
    gap: str,
    feature: Feature,
    evidence_texts: list[str],
    rules_block: str,
    rule_ids: list[str],
    known_feature_ids: set[str],
) -> PreviewSide:
    system, user = prompt_write_tutorial(gap, feature, evidence_texts, rules_block)
    draft: TutorialDraft = writer.generate_json(
        system=system,
        user=user,
        schema=TutorialDraft,
        operation_id=operation_id,
        node=node,
        max_tokens=settings.gen_max_tokens_writing,
        temperature=settings.gen_temperature,
    )
    content = TutorialContent.model_validate(draft.model_dump())
    valid = True
    problem: str | None = None
    try:
        validate_content(content, known_feature_ids)
    except ContentError as exc:
        valid = False
        problem = str(exc)

    markdown = render_markdown(content)
    repo.put_object(key, markdown, content_type=MARKDOWN_CONTENT_TYPE)
    return PreviewSide(
        label=label,
        key=key,
        markdown=markdown,
        rule_ids=rule_ids,
        valid=valid,
        problem=problem,
    )


def run_rule_toggle_preview(
    repo,
    writer,
    settings: Settings,
    *,
    run_id: str,
    gap: str,
    feature: Feature,
    evidence_texts: list[str],
    rule: AuthoringRule,
    known_feature_ids: set[str],
) -> PreviewResult:
    """用同一批輸入跑兩次寫作：一次不注入規則，一次注入指定規則。

    兩份輸出只寫 demo/previews/<run_id>/off.md 與 on.md。
    """
    keys = preview_keys(run_id)
    off = _one_side(
        repo,
        writer,
        settings,
        label="規則關閉",
        key=keys["off"],
        node="preview_off",
        operation_id=f"preview:{run_id}:off",
        gap=gap,
        feature=feature,
        evidence_texts=evidence_texts,
        rules_block="",
        rule_ids=[],
        known_feature_ids=known_feature_ids,
    )
    on = _one_side(
        repo,
        writer,
        settings,
        label=f"規則開啟（{rule.rule_id}）",
        key=keys["on"],
        node="preview_on",
        operation_id=f"preview:{run_id}:on",
        gap=gap,
        feature=feature,
        evidence_texts=evidence_texts,
        rules_block=render_rules_block([rule]),
        rule_ids=[rule.rule_id],
        known_feature_ids=known_feature_ids,
    )
    return PreviewResult(run_id=run_id, off=off, on=on)
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：`uv run pytest tests/integration/test_demo_preview.py -v`

預期：PASS，6 個測試全綠。其中 `test_預覽不寫任何_DynamoDB_資料` 與 `test_預覽不新增_TUTORIAL_與_RULE_項目` 就是 F47 的驗收。

- [ ] **步驟 5：commit**

```bash
git add demo/preview.py tests/integration/test_demo_preview.py
git commit -m "feat(demo): B 規則開關隔離對照只寫 demo/previews"
```

---

### Task 8：`demo/view_model.py` Dashboard 的純計算函式

**目的**：把 Dashboard 上所有「文字怎麼寫、表格怎麼排」的判斷抽成純函式，這樣可以單獨測試，Streamlit 檔案只剩畫面組裝。

**檔案**：
- 新增：`demo/view_model.py`
- 測試：`tests/unit/test_demo_view_model.py`

**介面**：
- 消費：
  - `demo.calls.CallSummary`（Task 6）
  - `training_kb.analytics.format_rating(avg: float | None) -> str`、`training_kb.analytics.format_rate(rate: float | None) -> str`（Phase 19）
- 產出：
  - `demo.view_model.Banner`（dataclass：`batch_id`、`time_mode`、`fallback`、`fallback_reason`）
  - `demo.view_model.banner_text(banner) -> str`
  - `demo.view_model.time_label(time_mode: str, ts: str) -> str`
  - `demo.view_model.REOPEN_DEFINITION: str`
  - `demo.view_model.reopen_caption(reopen: dict) -> str`
  - `demo.view_model.rating_rows(versions: list[dict]) -> list[dict]`
  - `demo.view_model.rule_rows(rules: list[dict]) -> list[dict]`
  - `demo.view_model.call_rows(summary: CallSummary) -> list[dict]`
  - `demo.view_model.diff_block(diff_text: str) -> str`
  - `demo.view_model.DemoStep`（dataclass：`order`、`title`、`command`、`expect`）
  - `demo.view_model.DEMO_STEPS: tuple[DemoStep, ...]`
  - `demo.view_model.script_markdown(steps) -> str`

`rating_rows` 與 `rule_rows` 的輸入都是 Phase 19 `dashboard_payload()` 回傳的 `versions` 與 `rules`，不是領域物件。這樣 Dashboard 走 Lambda 或走本機計算都是同一段程式。

- [ ] **步驟 1：寫測試**

```python
# tests/unit/test_demo_view_model.py
from __future__ import annotations

from demo.calls import CallSummary
from demo.view_model import (
    DEMO_STEPS,
    REOPEN_DEFINITION,
    Banner,
    banner_text,
    call_rows,
    diff_block,
    rating_rows,
    reopen_caption,
    rule_rows,
    script_markdown,
    time_label,
)


def test_橫幅永遠有合成資料示範與批次():
    text = banner_text(Banner(batch_id="demo-seed-2026-09", time_mode="即時執行"))
    assert "合成資料示範" in text
    assert "demo-seed-2026-09" in text
    assert "即時執行" in text


def test_備援時橫幅標示預先執行結果並帶失敗原因():
    text = banner_text(
        Banner(
            batch_id="b1",
            time_mode="即時執行",
            fallback=True,
            fallback_reason="Bedrock 逾時",
        )
    )
    assert "預先執行結果" in text
    assert "Bedrock 逾時" in text
    assert "本次 AWS 呼叫" not in text


def test_即時與模擬時間有不同前綴不混用():
    assert time_label("即時執行", "2026-09-13T10:00:00Z") == "即時 2026-09-13T10:00:00Z"
    assert time_label("模擬歷史資料", "2026-08-01T00:00:00Z") == (
        "模擬時間 2026-08-01T00:00:00Z"
    )
    assert time_label("即時執行", "") == "即時（尚無時間）"


def test_重開票說明同時有_proxy_字樣與精確定義():
    assert "proxy" in REOPEN_DEFINITION
    assert "[published_at, published_at + 14 天)" in REOPEN_DEFINITION
    assert "不同瀏覽者" in REOPEN_DEFINITION


def test_重開票說明列出分子分母與筆數():
    caption = reopen_caption(
        {"count": 7, "reopen_users": 7, "viewers": 10, "rate": 0.7, "rate_display": "70%"}
    )
    assert "筆數 7" in caption
    assert "分子 7" in caption
    assert "分母 10" in caption
    assert "70%" in caption


def test_沒有顯示欄位時用_Phase19_的格式化函式():
    caption = reopen_caption({"count": 2, "reopen_users": 2, "viewers": 10, "rate": 0.2})
    assert "20%" in caption


def test_零分母顯示_N_A_與樣本不足():
    caption = reopen_caption({"count": 0, "reopen_users": 0, "viewers": 0, "rate": None})
    assert "N/A（樣本不足）" in caption


def test_評分表每一列有版本平均回饋數與負面數():
    rows = rating_rows(
        [
            {"version_id": "a@v1", "avg": 2.875, "avg_display": "2.9", "n": 8, "negative": 8},
            {"version_id": "a@v2", "avg": None, "n": 0, "negative": 0},
        ]
    )
    assert rows[0] == {
        "版本": "a@v1",
        "平均評分": "2.9",
        "回饋數": 8,
        "負面回饋數": 8,
    }
    assert rows[1]["平均評分"] == "尚無評分"


def test_規則表帶狀態證據與來源版本():
    rows = rule_rows(
        [
            {
                "rule_id": "R-007",
                "status": "active",
                "rule": "click_ui 步驟要寫出位置",
                "applies_when": {"step.type": "click_ui"},
                "evidence": ["f_12", "f_15"],
                "derived_from": "prepare-meeting@v1",
                "validated_at": "2026-08-25T00:00:00Z",
                "applied_count": 3,
            }
        ]
    )
    assert rows[0]["規則 ID"] == "R-007"
    assert rows[0]["狀態"] == "active"
    assert rows[0]["套用次數"] == 3
    assert rows[0]["derived_from"] == "prepare-meeting@v1"
    assert rows[0]["evidence"] == "f_12、f_15"
    assert rows[0]["applies_when"] == '{"step.type": "click_ui"}'


def test_沒有證據的規則顯示無():
    rows = rule_rows(
        [
            {
                "rule_id": "R-012",
                "status": "retired",
                "rule": "x",
                "applies_when": {},
                "evidence": [],
                "derived_from": "share-summary@v1",
                "validated_at": None,
                "applied_count": 0,
            }
        ]
    )
    assert rows[0]["evidence"] == "（無）"
    assert rows[0]["狀態"] == "retired"


def test_呼叫數表列出節點與種類():
    summary = CallSummary(
        total=5,
        retries=1,
        failed=1,
        by_node={"embed": 1, "name_gap": 2, "write_tutorial": 1, "rote_agent": 1},
        by_kind={"embedding": 1, "generation": 4},
    )
    rows = call_rows(summary)
    assert {"節點": "name_gap", "呼叫次數": 2} in rows
    assert {"節點": "（合計）", "呼叫次數": 5} in rows


def test_v1_的空_diff_顯示沒有前一版():
    assert diff_block("") == "第一版，沒有前一版可比較。"
    assert diff_block("@@ -1 +1 @@") == "@@ -1 +1 @@"


def test_展示順序涵蓋兩條循環與_S8_四項():
    titles = " ".join(step.title for step in DEMO_STEPS)
    assert "種子" in titles
    assert "工單" in titles
    assert "改版" in titles
    assert "Review" in titles
    assert "規則開關" in titles
    assert "呼叫數" in titles
    assert "失敗復原" in titles
    assert [s.order for s in DEMO_STEPS] == list(range(1, len(DEMO_STEPS) + 1))


def test_腳本每一步都有指令與預期畫面():
    text = script_markdown(DEMO_STEPS)
    for step in DEMO_STEPS:
        assert step.title in text
        assert step.command in text
        assert step.expect in text
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：`uv run pytest tests/unit/test_demo_view_model.py -v`

預期：FAIL，`ModuleNotFoundError: No module named 'demo.view_model'`。

- [ ] **步驟 3：寫最少的程式讓測試通過**

```python
# demo/view_model.py
"""Dashboard 用的純計算函式。

這個模組不 import streamlit，也不碰 AWS，所以可以單獨測試。
設計文件 §11.5：頁面固定標示合成資料示範與資料批次；即時執行用真實時間、
模擬歷史資料用模擬時間，兩者不合併；備援必須標示「預先執行結果」。

顯示格式一律沿用 Phase 19 的 format_rating 與 format_rate，不另寫一份。
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from demo.calls import CallSummary
from training_kb.analytics import format_rate, format_rating

REOPEN_DEFINITION = (
    "同題重開票率是 proxy（代理指標），不是直接量到的教學成效。"
    "分子：在窗口 [published_at, published_at + 14 天) 內先留下瀏覽紀錄、"
    "之後又在同一個 cluster 開票的不同使用者數；"
    "分母：同一窗口內的不同瀏覽者。每版每人分子、分母各最多一次；"
    "分母為 0 顯示 N/A 與樣本不足。7 與 2 是筆數，不是比例。"
)


@dataclass(frozen=True)
class Banner:
    batch_id: str
    time_mode: str
    fallback: bool = False
    fallback_reason: str = ""


def banner_text(banner: Banner) -> str:
    parts = [
        "【合成資料示範】",
        f"資料批次：{banner.batch_id}",
        f"時間標示：{banner.time_mode}",
    ]
    if banner.fallback:
        reason = banner.fallback_reason or "（未填寫失敗原因）"
        parts.append(f"目前顯示「預先執行結果」；本次現場失敗原因：{reason}")
    return "｜".join(parts)


def time_label(time_mode: str, ts: str) -> str:
    prefix = "模擬時間" if time_mode == "模擬歷史資料" else "即時"
    return f"{prefix} {ts}" if ts else f"{prefix}（尚無時間）"


def reopen_caption(reopen: dict) -> str:
    rate_text = reopen.get("rate_display") or format_rate(reopen.get("rate"))
    return (
        f"筆數 {reopen.get('count', 0)}｜"
        f"分子 {reopen.get('reopen_users', 0)}｜"
        f"分母 {reopen.get('viewers', 0)}｜"
        f"率 {rate_text}"
    )


def rating_rows(versions: list[dict]) -> list[dict]:
    return [
        {
            "版本": str(item.get("version_id", "-")),
            "平均評分": item.get("avg_display") or format_rating(item.get("avg")),
            "回饋數": int(item.get("n", 0)),
            "負面回饋數": int(item.get("negative", 0)),
        }
        for item in versions
    ]


def rule_rows(rules: list[dict]) -> list[dict]:
    return [
        {
            "規則 ID": str(rule.get("rule_id", "-")),
            "狀態": str(rule.get("status", "-")),
            "套用次數": int(rule.get("applied_count", 0)),
            "applies_when": json.dumps(rule.get("applies_when") or {}, ensure_ascii=False),
            "derived_from": str(rule.get("derived_from", "-")),
            "evidence": "、".join(rule.get("evidence") or []) or "（無）",
        }
        for rule in rules
    ]


def call_rows(summary: CallSummary) -> list[dict]:
    rows = [
        {"節點": node, "呼叫次數": count}
        for node, count in sorted(summary.by_node.items())
    ]
    rows.append({"節點": "（其中重試）", "呼叫次數": summary.retries})
    rows.append({"節點": "（其中失敗）", "呼叫次數": summary.failed})
    rows.append({"節點": "（合計）", "呼叫次數": summary.total})
    return rows


def diff_block(diff_text: str) -> str:
    """v1 的 diff 是空檔（釐清 F50）；介面另外說明它沒有前版。"""
    return diff_text if diff_text.strip() else "第一版，沒有前一版可比較。"


@dataclass(frozen=True)
class DemoStep:
    order: int
    title: str
    command: str
    expect: str


DEMO_STEPS: tuple[DemoStep, ...] = (
    DemoStep(
        1,
        "載入種子並當場重算",
        "uv run python -m demo.cli seed",
        "重算表每一列的「相符」欄都是相符，2.875／4.4／8／2／7／2／0.7／0.2 都對得上",
    ),
    DemoStep(
        2,
        "循環一：工單達門檻建立教學",
        "uv run python -m demo.cli trigger-ticket demo/seed/one_ticket.json",
        "結果是 accepted，並印出 execution ARN；靜態站出現 prepare-meeting v1",
    ),
    DemoStep(
        3,
        "循環一：每日 Review 產生 REFINE 與 candidate",
        "uv run python -m demo.cli trigger-review --policy demo",
        "A 出現 v2，reason 是「feedback:8 則 找不到按鈕」；R-007 狀態是 candidate",
    ),
    DemoStep(
        4,
        "循環二：改版只改命中步驟",
        "uv run python -m demo.cli trigger-release demo/seed/r42.json",
        "A 出現 v3，diff 只有第 3 步；第 1、2、4 步逐字相同；B、C 沒有新版",
    ),
    DemoStep(
        5,
        "B 的規則開關隔離對照",
        "Dashboard 的「B 對照」分頁按下按鈕",
        "左右並排兩份 Markdown，只寫入 demo/previews/<run_id>/off.md 與 on.md",
    ),
    DemoStep(
        6,
        "指標與當次真實呼叫數",
        "uv run python -m demo.cli metrics --slug prepare-meeting",
        "2.9→4.4、7→2、70%→20%；呼叫數分頁顯示 trace 實際筆數含重試",
    ),
    DemoStep(
        7,
        "一次儲存失敗復原",
        "TKB_FAULT=publish_before_transact（Phase 24 的開關）",
        "current_version 不變、site/ 沒有新檔；清掉開關並重送後補齊並發布成功",
    ),
)


def script_markdown(steps: tuple[DemoStep, ...]) -> str:
    lines: list[str] = []
    for step in steps:
        lines.append(f"**{step.order}. {step.title}**")
        lines.append(f"- 指令：`{step.command}`")
        lines.append(f"- 預期畫面：{step.expect}")
        lines.append("")
    return "\n".join(lines)
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：`uv run pytest tests/unit/test_demo_view_model.py -v`

預期：PASS，14 個測試全綠。

- [ ] **步驟 5：commit**

```bash
git add demo/view_model.py tests/unit/test_demo_view_model.py
git commit -m "feat(demo): Dashboard 純函式與展示順序腳本"
```

---

### Task 9：`demo/dashboard.py` Streamlit 畫面

**目的**：把四個區塊、B 對照、呼叫數與展示順序腳本組成一個網頁。

**檔案**：
- 新增：`demo/dashboard.py`
- 測試：`tests/unit/test_demo_dashboard_guard.py`

**介面**：
- 消費：`demo.cli`（`load_targets`、`build_metrics_event`、`invoke_analytics`）、`demo.calls`（`load_call_records`、`summarize_calls`）、`demo.preview.run_rule_toggle_preview`、`demo.view_model`、`training_kb.analytics.dashboard_payload`（Phase 19）、`training_kb.repository.build_repository`（Phase 03）、`training_kb.config.load_settings`（Phase 01）、`training_kb.clock.now_utc`（Phase 01）、`training_kb.writing.client.build_writer` 與 `CallTrace`（Phase 05）、`training_kb.models.parse_version_id` 與 `APPROVED_CATEGORIES_DEFAULT`（Phase 02）
- 產出：`demo/dashboard.py`（由 `uv run streamlit run demo/dashboard.py` 執行）

這個 Task 的測試是**護欄測試**：它不啟動瀏覽器，而是檢查原始碼裡沒有任何 DynamoDB 寫入呼叫，而且四個必要區塊的標題都在。設計文件 §5 與 §13 規定「展示頁不直接寫 DynamoDB」，這條規則用測試釘住比用人眼看可靠。

- [ ] **步驟 1：寫測試**

```python
# tests/unit/test_demo_dashboard_guard.py
from __future__ import annotations

from pathlib import Path

import pytest

SOURCE = Path("demo/dashboard.py")

FORBIDDEN_WRITES = (
    "put_item",
    "update_item",
    "delete_item",
    "transact_write",
    "put_meta",
    "update_meta",
    "put_edge",
    "put_tutorial",
    "put_rule",
    "put_feedback",
    "put_view",
    "put_ticket",
    "put_release",
    "put_proc",
    "next_counter",
    "apply_rule_status",
)

REQUIRED_SECTIONS = (
    "最新教學與版本差異",
    "每版評分與回饋數",
    "重開票筆數及分子／分母",
    "規則狀態與來源證據",
    "B 規則開關對照",
    "當次執行的實際模型呼叫數",
)


@pytest.fixture(scope="module")
def source() -> str:
    return SOURCE.read_text(encoding="utf-8")


def test_檔案存在而且語法正確(source):
    compile(source, str(SOURCE), "exec")


def test_不直接寫_DynamoDB(source):
    for name in FORBIDDEN_WRITES:
        assert name not in source, f"Dashboard 不可以呼叫 {name}"


def test_四個區塊與兩個展示分頁都在(source):
    for label in REQUIRED_SECTIONS:
        assert label in source, f"缺少區塊：{label}"


def test_固定標示合成資料示範與資料批次(source):
    assert "banner_text" in source
    assert "資料批次" in source


def test_有備援的預先執行結果標示(source):
    assert "預先執行結果" in source


def test_有_proxy_定義與_F47_隔離說明(source):
    assert "REOPEN_DEFINITION" in source
    assert "F47" in source


def test_只透過_preview_模組寫_demo_previews(source):
    assert "run_rule_toggle_preview" in source
    assert "site/" not in source


def test_指標一律走_Phase19_的_payload(source):
    assert "dashboard_payload" in source or "invoke_analytics" in source
    assert '["versions"]' in source or '.get("versions"' in source
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：`uv run pytest tests/unit/test_demo_dashboard_guard.py -v`

預期：FAIL，`FileNotFoundError: [Errno 2] No such file or directory: 'demo/dashboard.py'`。

- [ ] **步驟 3：寫最少的程式讓測試通過**

```python
# demo/dashboard.py
"""Training KB Demo Dashboard（Streamlit）。

執行方式：
    set -a && source .env && set +a
    uv run streamlit run demo/dashboard.py

這個檔案只讀資料或呼叫 handler／流程，不直接寫 DynamoDB（設計 §5、§13）。
唯一的寫入是 demo/preview.py 對 S3 demo/previews/ 的兩個物件，
依釐清 F47 屬於隔離的 Demo 產物，不進正式教學與統計。
"""

from __future__ import annotations

import json

import boto3
import streamlit as st

from demo.calls import load_call_records, summarize_calls
from demo.cli import build_metrics_event, invoke_analytics, load_targets
from demo.preview import run_rule_toggle_preview
from demo.view_model import (
    DEMO_STEPS,
    REOPEN_DEFINITION,
    Banner,
    banner_text,
    call_rows,
    diff_block,
    rating_rows,
    reopen_caption,
    rule_rows,
    script_markdown,
    time_label,
)
from training_kb.analytics import dashboard_payload
from training_kb.clock import now_utc
from training_kb.config import load_settings
from training_kb.models import APPROVED_CATEGORIES_DEFAULT, parse_version_id
from training_kb.repository import build_repository
from training_kb.writing.client import CallTrace, build_writer

st.set_page_config(page_title="Training KB Demo", layout="wide")

settings = load_settings()
repo = build_repository(settings)


@st.cache_data(ttl=30)
def load_text(_repo, key: str) -> str:
    body = _repo.get_object(key)
    return "" if body is None else body.decode("utf-8")


def load_payload(slug: str | None, use_lambda: bool) -> dict:
    """指標一律來自 Phase 19 的 dashboard_payload，走 Lambda 或走本機都一樣。"""
    slugs = [slug] if slug else None
    if not use_lambda:
        approved = repo.get_config_list(
            "approved_categories", list(APPROVED_CATEGORIES_DEFAULT)
        )
        return dashboard_payload(
            repo,
            project_id=settings.project_id,
            approved_categories=approved,
            slugs=slugs,
            now=now_utc(),
        )
    targets = load_targets()
    client = boto3.client("lambda", region_name=targets.region)
    return invoke_analytics(
        client, targets.analytics_function, build_metrics_event(slugs=slugs)
    )


with st.sidebar:
    st.header("展示設定")
    batch_id = st.text_input("資料批次", value="demo-seed-2026-09")
    time_mode = st.radio("時間標示", options=["即時執行", "模擬歷史資料"], index=0)
    fallback = st.checkbox("改用預先執行結果（備援）", value=False)
    fallback_reason = st.text_input("本次現場失敗原因", value="") if fallback else ""
    slug = st.text_input("教學 slug", value="prepare-meeting")
    use_lambda = st.checkbox("指標走 Analytics Lambda", value=True)
    st.divider()
    st.subheader("展示順序")
    st.markdown(script_markdown(DEMO_STEPS))

st.warning(
    banner_text(
        Banner(
            batch_id=batch_id,
            time_mode=time_mode,
            fallback=fallback,
            fallback_reason=fallback_reason,
        )
    )
)

payload = load_payload(slug, use_lambda)
versions = payload.get("versions", [])

tab_doc, tab_rating, tab_reopen, tab_rule, tab_preview, tab_calls = st.tabs(
    [
        "最新教學與版本差異",
        "每版評分與回饋數",
        "重開票筆數及分子／分母",
        "規則狀態與來源證據",
        "B 規則開關對照",
        "當次執行的實際模型呼叫數",
    ]
)

with tab_doc:
    st.subheader("最新教學與版本差異")
    tutorial = repo.get_tutorial(slug)
    if tutorial is None:
        st.info(f"找不到教學 {slug}。")
    elif tutorial.current_version is None:
        st.info("這篇教學還沒有已發布版本；讀者現在看不到內容。")
    else:
        version = repo.get_version(tutorial.current_version)
        st.markdown(f"### {tutorial.topic}（{tutorial.current_version}）")
        st.caption(time_label(time_mode, version.published_at or ""))
        st.markdown(f"**改版原因 reason**：`{version.reason}`")
        st.markdown(
            f"**本版注入的規則 rules_applied**：{version.rules_applied or '（無）'}"
        )
        st.markdown("#### 這一版全文（S3 私有產物）")
        st.code(load_text(repo, version.s3_key), language="markdown")
        _, number = parse_version_id(tutorial.current_version)
        st.markdown("#### 與前一版的完整 diff")
        st.code(
            diff_block(load_text(repo, f"tutorials/{slug}/v{number}.diff")),
            language="diff",
        )

with tab_rating:
    st.subheader("每版評分與回饋數")
    st.dataframe(rating_rows(versions))
    st.caption(
        "跨版等權平均評分："
        f"{payload.get('cross_version_average_display', '尚無評分')}"
    )
    st.caption("平均評分顯示一位小數；門檻判斷一律使用未四捨五入的數值（設計 §11.2）。")
    st.caption("沒有有效評分的版本顯示「尚無評分」，不當成 0 分（釐清 F52）。")

with tab_reopen:
    st.subheader("重開票筆數及分子／分母")
    st.caption(REOPEN_DEFINITION)
    for item in versions:
        reopen = item.get("reopen") or {}
        st.markdown(f"**{item.get('version_id')}**")
        left, middle, right = st.columns(3)
        left.metric("重開票筆數", reopen.get("count", 0))
        middle.metric("分子（不同開票者）", reopen.get("reopen_users", 0))
        right.metric("分母（不同瀏覽者）", reopen.get("viewers", 0))
        st.caption(reopen_caption(reopen))

with tab_rule:
    st.subheader("規則狀態與來源證據")
    counts = payload.get("rule_counts", {})
    one, two, three = st.columns(3)
    one.metric("candidate", counts.get("candidate", 0))
    two.metric("active", counts.get("active", 0))
    three.metric("retired", counts.get("retired", 0))
    rules = payload.get("rules", [])
    st.dataframe(rule_rows(rules))
    for rule in rules:
        with st.expander(f"{rule.get('rule_id')}｜{rule.get('status')}"):
            st.markdown(f"**規則內容**：{rule.get('rule')}")
            st.markdown(
                "**適用範圍 applies_when**："
                f"`{json.dumps(rule.get('applies_when') or {}, ensure_ascii=False)}`"
            )
            st.markdown(f"**derived_from（恰好一個來源版本）**：`{rule.get('derived_from')}`")
            st.markdown(
                "**evidence（Feedback ID）**："
                + ("、".join(rule.get("evidence") or []) or "（無）")
            )
            st.markdown(
                f"**最近驗證通過時間 validated_at**：{rule.get('validated_at') or '（尚未驗證）'}"
            )
    st.caption("candidate、active、retired 分別計數；candidate 不進一般寫作路徑。")

with tab_preview:
    st.subheader("B 規則開關對照")
    st.info(
        "釐清 F47：兩份都只是隔離的 Demo 產物，"
        "不寫入正式教學、rules_applied、回饋或規則效果統計。"
        "唯一寫入是 demo/previews/<run_id>/off.md 與 on.md。"
    )
    run_id = st.text_input("預覽批次 run_id", value="b-preview-01")
    rule_id = st.text_input("要注入的規則 ID", value="R-007")
    feature_id = st.text_input("B 的 Feature", value="Share Summary")
    gap = st.text_input("同一批 B 工單的 gap 說明", value="使用者不知道怎麼分享摘要")
    evidence_text = st.text_area(
        "同一批 B 工單文字（一行一筆）",
        value="怎麼把摘要寄給同事？\n分享按鈕在哪裡？",
    )
    if st.button("用同一批工單各跑一次（關閉／開啟）"):
        rule = repo.get_rule(rule_id)
        feature = repo.get_feature(feature_id)
        if rule is None or feature is None:
            st.error("找不到指定的規則或 Feature，請先執行 seed。")
        else:
            writer = build_writer(settings, CallTrace())
            with st.spinner("正在呼叫兩次寫作模型…"):
                st.session_state["preview"] = run_rule_toggle_preview(
                    repo,
                    writer,
                    settings,
                    run_id=run_id,
                    gap=gap,
                    feature=feature,
                    evidence_texts=[
                        line for line in evidence_text.splitlines() if line.strip()
                    ],
                    rule=rule,
                    known_feature_ids={f.feature_id for f in repo.list_features()},
                )
    result = st.session_state.get("preview")
    if result is not None:
        left, right = st.columns(2)
        left.markdown(f"#### {result.off.label}")
        left.code(result.off.markdown, language="markdown")
        left.caption(f"寫入：`{result.off.key}`｜注入規則：{result.off.rule_ids or '（無）'}")
        right.markdown(f"#### {result.on.label}")
        right.code(result.on.markdown, language="markdown")
        right.caption(f"寫入：`{result.on.key}`｜注入規則：{result.on.rule_ids}")
        st.caption(
            "若要另外展示正常流程建立的 B v1，請用 trigger-ticket，並與這兩份預覽分開看。"
        )

with tab_calls:
    st.subheader("當次執行的實際模型呼叫數")
    operation_id = st.text_input("operation_id", value="")
    if operation_id:
        records = load_call_records(repo, operation_id)
        summary = summarize_calls(records, embed_model_id=settings.embed_model_id)
        st.metric("實際送出的呼叫嘗試總數", summary.total)
        st.dataframe(call_rows(summary))
        st.caption(
            "包含 embedding、Rote 層、Map 的每一項與每一次重試；"
            "記憶體重用不算新呼叫（設計 §12.1、釐清 F45）。"
        )
        st.caption("實際幾次就顯示幾次，不為配合投影片刪掉 embedding 或 retry（設計 §12.3）。")
    else:
        st.info("填入一個 operation_id，例如 ingest:ticket:t_881 或 review:demo:<run_id>。")
    st.caption(
        "Analytics 自己不呼叫 Bedrock。這一頁的數字來自 operations/<id>.json 的 calls 欄位；"
        f"本次 payload 回報的是 {payload.get('bedrock_call_count')}"
        f"（來源：{payload.get('bedrock_call_source')}）。"
    )
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：`uv run pytest tests/unit/test_demo_dashboard_guard.py -v`

預期：PASS，8 個測試全綠。接著手動開一次網頁：

```bash
set -a && source .env && set +a
uv run streamlit run demo/dashboard.py
```

預期瀏覽器打開 `http://localhost:8501`，最上方是黃色橫幅「【合成資料示範】｜資料批次：demo-seed-2026-09｜時間標示：即時執行」，下方有六個分頁，左側有展示順序腳本。

- [ ] **步驟 5：commit**

```bash
git add demo/dashboard.py tests/unit/test_demo_dashboard_guard.py
git commit -m "feat(demo): Streamlit Dashboard 四區塊與隔離對照"
```

---

## 7. 完成檢查清單

做完全部 9 個 Task 後，逐條手動確認。這些對應設計文件第 16 節 S8 的檢查：「展示兩條循環、B 隔離對照、真實呼叫數及一次儲存失敗復原」（最後一項由 Phase 24 提供開關，這裡只確認 Dashboard 看得到結果）。

- [ ] `uv run pytest tests/unit/test_demo_cli.py tests/unit/test_demo_calls.py tests/unit/test_demo_view_model.py tests/unit/test_demo_dashboard_guard.py tests/integration/test_demo_preview.py -v` 全部 PASS。
- [ ] `uv run ruff check .` 與 `uv run ruff format --check .` 沒有錯誤。
- [ ] `uv run python -m demo.cli seed` 的重算表每一列的「相符」欄都是「相符」，而且印出「全部相符：…」。
- [ ] `uv run python -m demo.cli trigger-ticket <檔案>` 第一次得到 `accepted`，**同一個檔案再送一次得到 `duplicate`**（F09：同一事件只處理一次）。
- [ ] `uv run python -m demo.cli trigger-release <檔案>` 後，A 出現新版且 diff 只有第 3 步。
- [ ] `uv run python -m demo.cli trigger-review --policy demo` 印出 execution ARN 與「n>=8（Demo 隔離門檻）」。
- [ ] `uv run python -m demo.cli metrics` 的表格有七欄，A v1 是 `2.9  8  8  7  7／10  70%`、A v2 是 `4.4  10  2  2  2／10  20%`，且下方 proxy 定義與合成資料標示都在。
- [ ] Dashboard 橫幅永遠顯示「合成資料示範」與資料批次，關不掉。
- [ ] Dashboard 第一個分頁顯示**完整 diff**（不是摘要、不是前幾行）。
- [ ] Dashboard 第三個分頁同時顯示「筆數」「分子」「分母」「率」四個數字，而且有 proxy 的精確定義。
- [ ] Dashboard 第四個分頁每條規則都看得到 `evidence` 的 Feedback ID 與 `derived_from` 的來源版本。
- [ ] B 對照跑完後，用 `aws s3 ls s3://<bucket>/demo/previews/<run_id>/` 只看到 `off.md` 與 `on.md` 兩個檔案。
- [ ] B 對照跑完後，`aws dynamodb scan --table-name <table> --filter-expression "begins_with(PK, :p)" --expression-attribute-values '{":p":{"S":"TUTORIAL#share-summary"}}'` 的 `Count` 沒有因為預覽而改變。
- [ ] 呼叫數分頁的總數等於 trace 裡的紀錄筆數；如果剛才有一次重試，「（其中重試）」那列不是 0。
- [ ] 切換側邊欄的「時間標示」時，時間前綴會從「即時」變成「模擬時間」，畫面上沒有兩種時間混在同一張表。
- [ ] 勾選「改用預先執行結果（備援）」後，橫幅出現「預先執行結果」與失敗原因欄位。
- [ ] `grep -rn "AKIA\|aws_secret_access_key\|ghp_" demo/` 沒有任何結果（控制台不嵌金鑰）。

---

## 8. 常見錯誤與排除

**症狀 1：`ModuleNotFoundError: No module named 'demo'`**
原因：pytest 沒有把 repo 根目錄放進 Python 搜尋路徑，所以找不到 `demo/` 這個套件。
解法：確認 `pyproject.toml` 有 `[tool.pytest.ini_options]` 底下的 `pythonpath = ["."]`，而且 `demo/__init__.py` 存在（可以是空檔）。改完重跑 `uv run pytest`。

**症狀 2：`botocore.exceptions.NoCredentialsError: Unable to locate credentials`**
原因：本機沒有 AWS 登入，或 shell 換過之後憑證環境變數不見了。
解法：先跑 `aws sts get-caller-identity` 確認身分。沒有身分就執行 `aws configure`（長期金鑰）或 `aws sso login --profile <名稱>`（SSO）。**不要**把金鑰寫進 `demo/cli.py` 或 `.env`。如果用 profile，執行前設 `export AWS_PROFILE=<名稱>`。

**症狀 3：`ResourceNotFoundException: Function not found: training-kb-import`**
原因：Phase 14 的 Lambda 還沒部署，或函式名稱與預設值不同，或 Region 不對。
解法：先跑 `aws lambda list-functions --query 'Functions[].FunctionName' --output text` 看實際名稱。名稱不同就在 `.env` 加上 `TKB_IMPORT_FUNCTION=<實際名稱>`；Region 不同就修正 `TKB_AWS_REGION`。

**症狀 4：`ExecutionAlreadyExists` 從 `trigger-review` 冒出來**
原因：Step Functions 的 execution name 必須唯一。`review_operation_id` 用了秒級時間戳，同一秒內按兩次就會撞名。
解法：等一秒再按。這個例外**不可以**直接當成功（設計 §14.2 原話：「已結束的同名執行會回傳 ExecutionAlreadyExists，不能把此例外直接當成功」）。要判斷前一次結果，用 `aws stepfunctions describe-execution --execution-arn <arn>` 查狀態。完整處理在 Phase 24 驗收。

**症狀 5：Dashboard 顯示 `KeyError: 'versions'` 或整個分頁空白**
原因：Analytics Lambda 回傳的欄位名稱與 `build_metrics_event()` 假設的不同。
解法：先用 `uv run python -m demo.cli metrics --local` 走本機路徑（直接呼叫 `dashboard_payload`）確認資料本身沒問題。如果本機正常、Lambda 不正常，就以 Phase 19（`19-Phase19-Analytics-學習指標.md`）的 `dashboard_payload` 回傳欄位為準，只改 `demo/cli.py` 的 `build_metrics_event()` 與 `metrics_rows()` 兩個函式。

**症狀 6：Streamlit 每次按按鈕，預覽結果就不見了**
原因：Streamlit 每次互動都會從頭重跑整份 Python 檔，普通變數會被重置。
解法：把要保留的東西放進 `st.session_state`（Task 9 的 `st.session_state["preview"]` 就是這樣做的）。

**症狀 7：`st.cache_data` 報 `UnhashableParamError`**
原因：`Repository` 物件沒辦法被 Streamlit 計算雜湊值。
解法：把參數名稱改成底線開頭（例如 `_repo`），Streamlit 就會跳過這個參數不做雜湊。Task 9 的 `load_text(_repo, key)` 已經這樣寫。

**症狀 8：B 對照的測試在 moto 下報 `InvalidLocationConstraint`**
原因：`create_bucket` 在 `us-east-1` 不可以帶 `CreateBucketConfiguration`，在其他 Region 則必須帶。
解法：測試固定用 `us-west-2` 並保留 `CreateBucketConfiguration={"LocationConstraint": "us-west-2"}`。如果你要換 Region，兩處要一起改。

---

## 9. 這階段不做的事

| 項目 | 留給哪裡 |
|---|---|
| 注入儲存失敗、驗證舊版不變與重送補齊 | Phase 24（`24-Phase24-失敗復原與重送驗收.md`）提供 `TKB_FAULT` 開關與整合驗證 |
| Snyk 掃描、IAM 最小權限核對、`.env` 忽略確認、當日 runbook、結束後停用清單 | Phase 25（`25-Phase25-安全檢查與Demo當日準備.md`） |
| 公開教學頁的 HTML、回饋 widget、瀏覽紀錄匯出 | Phase 22（`22-Phase22-S3靜態教學站.md`）；本階段只讀 S3 的私有 md 與 diff |
| 種子資料本身的內容與可重算性 | Phase 21（`21-Phase21-Demo種子資料與可重算驗證.md`）；本階段只呼叫它的 loader 與 `verify_recipe` |
| 指標公式（平均、負面數、重開票窗口） | Phase 19（`19-Phase19-Analytics-學習指標.md`）；本階段只顯示它算出來的結果 |
| 規則狀態的判定與寫入 | Phase 20（`20-Phase20-規則驗證與狀態轉換.md`）；Dashboard 只讀 status，不寫 status |
| Streamlit 的端到端 UI 自動化測試 | 本階段只測純函式與原始碼護欄；UI 由人在完成檢查清單裡手動確認 |
| 使用者帳號、權限控管、把 Dashboard 部署到網路上 | 不在 MVP 範圍（設計 §3）；Dashboard 只在維護者本機執行 |
| 報表平台、複雜圖表 | 設計 §13 原話：「少量離散版本使用表格或折線即可，不建立報表平台」 |

---

## 10. 對照：設計章節與 Rule 編號

下表把設計文件第 20 節中屬於本階段的 Rule 全部列出。Rule 原文照抄一次。

| Rule 來源檔 | Rule 編號與原文 | 本階段哪個 Task 落實 |
|---|---|---|
| `檢視學習指標.feature` | Rule 1「平均評分以每個 TutorialVersion 的 rating 計算」 | Task 5（`metrics_rows`）、Task 8（`rating_rows`）、Task 9（評分分頁） |
| `檢視學習指標.feature` | Rule 2「負面 Feedback 數計入 rating 不超過 2 或 category 屬負面的回饋」 | Task 5、Task 8（`rating_rows` 的「負面回饋數」欄） |
| `檢視學習指標.feature` | Rule 3「同題重開票率計算看過教學的使用者在版本發布後 14 天內同 cluster 再開票的比例」 | Task 5（`format_rate`）、Task 8（`REOPEN_DEFINITION`） |
| `檢視學習指標.feature` | Rule 4「同題重開票率的分母取自教學瀏覽事件」 | Task 5（分子／分母欄）、Task 8（`reopen_caption`）、Task 9（三個 metric） |
| `檢視學習指標.feature` | Rule 5「看過教學又開票的同一人比對穩定使用者 ID」 | Task 8（`REOPEN_DEFINITION` 說明「不同使用者」的判準） |
| `檢視學習指標.feature` | Rule 7「已學規則數依 RULE item 的 status 分別計數」 | Task 8（`rule_rows` 的「狀態」欄）、Task 9（規則分頁） |
| `檢視學習指標.feature` | Rule 8「規則套用次數等於 applied_to 清單長度」 | Task 8（`rule_rows` 的「套用次數」，數值由 Phase 19 的 `applied_count` 提供）、Task 9（規則分頁） |
| `檢視學習指標.feature` | Rule 9「每次執行的 Bedrock 呼叫數包含 Step Functions 內的呼叫節點與 Rote 層呼叫」 | Task 6（`summarize_calls`）、Task 9（呼叫數分頁） |
| `檢視學習指標.feature` | Rule 10「Demo 指標以 seeded data 展示」 | Task 2（`recipe_rows` 與 Phase 21 的 `check_recipe`）、Task 8（`banner_text`） |
| `檢視學習指標.feature` | Rule 11「Demo 對同題重開票率標明 proxy 與精確定義」 | Task 5（終端機輸出）、Task 8（`REOPEN_DEFINITION`）、Task 9（重開票分頁） |
| `檢視學習指標.feature` | Rule 12「Demo 以同一批 Ticket 並排展示規則關閉與開啟產生的 Tutorial B」 | Task 7（`run_rule_toggle_preview`）、Task 9（B 對照分頁） |
| `執行教學流程.feature` | Rule 1「缺少原始 Example 時可用明示合成且經確認的驗收資料」 | Task 8（`banner_text` 固定標示合成資料示範） |
| `套用教學規則.feature` | Rule 5「既有教學衍生的適用規則可用於不同主題新教學的第一版」 | Task 7（把 A 衍生的 R-007 注入 B 的寫作 prompt） |
| `提出教學規則.feature` | Rule 6「MVP 的教學與產品功能識別碼在單一專案範圍內唯一」 | Task 2（單一 `project_id` 的種子）、Task 5（教學清單來自同一專案） |
| `發布教學版本.feature` | Rule 4「Tutorial 的 current_version 指向目前教學版本」 | Task 9（教學分頁只顯示 `current_version`，沒有已發布版本時顯示「讀者現在看不到內容」） |
| `建立教學版本.feature` | Rule 7「與前版的 diff 儲存在 tutorials/&lt;slug&gt;/v&lt;n&gt;.diff」 | Task 9（讀 `tutorials/<slug>/v<n>.diff` 顯示完整 diff） |

補充說明：

- **本計劃選擇（對應 O4）**：重開票窗口是 `[published_at, published_at + 14 天)`，左邊含、右邊不含。Dashboard 的 proxy 說明照這個寫。設計文件第 18 節把它列為待確認事項 O4，尚未有規格答案。
- **本計劃選擇（對應 O2）**：當次呼叫紀錄存在 `operations/<operation_id>.json` 的 `calls` 欄位。設計文件第 18 節 O2 把操作紀錄的儲存形狀列為待確認。
- Analytics Lambda 的事件格式與回傳欄位**以 Phase 19（`19-Phase19-Analytics-學習指標.md`）為準**：事件讀 `slugs`、`version_ids`、`call_trace` 三個鍵，回傳 `dashboard_payload()` 的字典。本階段不另外定義一份契約。
- 種子的目標值與比對邏輯**以 Phase 21（`21-Phase21-Demo種子資料與可重算驗證.md`）為準**：`EXPECTED_RECIPE`、`verify_recipe`、`check_recipe`、`load_all` 都在 `demo/seed_loader.py`，本階段只負責排版與退出碼。

---

## 11. 參考來源

設計文件（`docs/design/training-kb.md`）：

- §5 目標架構與模組責任（展示頁不直接寫 DynamoDB）
- §6 端到端流程（兩條循環的順序）
- §7.1 接入：手動上傳由已登入 AWS 的維護者透過 SDK 呼叫
- §9.3 S3 與執行資訊（`demo/previews/`、`operations/` 的地位）
- §11.2 可重算的評分與負面回饋（2.875／4.4／8／2）
- §11.3 可重算的瀏覽、重開票筆數與比例（7／2、70%／20%）
- §11.4 讓規則轉移的順序正確（B 的兩份隔離預覽）
- §11.5 Demo 的資料與即時執行分開標示
- §12.1 指標公式（呼叫數以嘗試為單位）
- §12.3 指標不能替代的證據（實際幾次就顯示幾次）
- §13 Demo UI 與 S3 教學頁（Dashboard 四個區塊）
- §14.2 StartExecution 的冪等限制
- §16 交付切片 S8
- §18 待確認事項 O2、O4
- §20.11、§20.3、§20.4、§20.8、§20.12、§20.6 的 Rule 對照

規格與釐清紀錄：

- `docs/spec/features/檢視學習指標.feature`
- `docs/spec/features/發布教學版本.feature`
- `docs/spec/features/建立教學版本.feature`
- `docs/spec/.clarify/resolved/features/檢視學習指標_Tutorial_B_的規則開關對照是否會影響正式上架版本.md`（F47，答案 C）
- `docs/spec/.clarify/resolved/features/檢視學習指標_Bedrock_呼叫數是否計入重試與_Map_的每次呼叫.md`（F45，答案 A）
- `docs/spec/.clarify/resolved/features/檢視學習指標_seeded_Demo_指標採現算結果還是固定展示值.md`（F46，答案 A）
- `docs/spec/.clarify/resolved/features/檢視學習指標_沒有可識別瀏覽者時重開票率如何顯示.md`（F42，答案 A）
- `docs/spec/.clarify/resolved/features/接入來源事件_同一正規化事件重送時是否再次觸發_pipeline.md`（F09，答案 A）

外部官方文件（以 Context7 MCP 查詢 `/streamlit/docs`、`/snyk/cli` 與 AWS 官方站取得）：

- Streamlit 版面與分頁 `st.tabs`：https://docs.streamlit.io/develop/api-reference/layout/st.tabs
- Streamlit `st.session_state`：https://docs.streamlit.io/develop/api-reference/caching-and-state/st.session_state
- Streamlit `st.cache_data`（底線參數跳過雜湊）：https://docs.streamlit.io/develop/api-reference/caching-and-state/st.cache_data
- Streamlit `st.dataframe`：https://docs.streamlit.io/develop/api-reference/data/st.dataframe
- boto3 Lambda `invoke`（`FunctionName`、`InvocationType`、`Payload`、`FunctionError`）：https://docs.aws.amazon.com/boto3/latest/reference/services/lambda/client/invoke.html
- boto3 Step Functions `start_execution`（`stateMachineArn`、`name`、`input`）：https://docs.aws.amazon.com/boto3/latest/reference/services/stepfunctions/client/start_execution.html
- Step Functions `StartExecution` API（同名冪等的限制）：https://docs.aws.amazon.com/step-functions/latest/apireference/API_StartExecution.html
- moto 使用方式（`from moto import mock_aws`）：https://docs.getmoto.org/en/latest/docs/getting_started.html
