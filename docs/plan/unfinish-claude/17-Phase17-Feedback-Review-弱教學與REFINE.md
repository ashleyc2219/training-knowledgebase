# Phase 17：Feedback Review 弱教學判定與 REFINE

| 項目 | 內容 |
|---|---|
| 上一階段 | Phase 16：Release Note Update 流程（`16-Phase16-Release-Note-Update流程.md`） |
| 下一階段 | Phase 18：Feedback Review 候選規則與每日排程（`18-Phase18-Feedback-Review-候選規則與每日排程.md`） |
| 對應設計文件章節 | §7.5、§7.6、§8.1、§8.2、§14.1、§15（`docs/design/training-kb.md`） |
| 對應交付切片 | S6（設計文件第 16 節） |
| 預估時間 | 約 6 小時 |
| 做完會得到 | 一支能挑出「弱教學」、只改診斷命中步驟、並產生未發布新版本的每日檢視流程 |

---

## 1. 這階段做完會得到什麼

做完這一階段，你會有一組可以在自己電腦上跑的函式，它們合起來做這件事：

> 掃過每一篇還在使用中的教學，看它「目前上架的那一版」累積到現在的全部回饋。如果這一版同時滿足「平均分數低」「回饋夠多」「同一種問題一直重複出現」三個條件，就請模型指出是哪幾個步驟出問題，然後**只重寫那幾個步驟**，產生一個還沒上架的新版本。最後把這一輪要上架的版本一次送出。

具體會多出這些東西：

- `src/training_kb/pipelines/feedback.py`：本階段的主角，裡面有 `ReviewPolicy`、`is_weak`、`evidence_key`、`refine_reason` 四個純函式，以及 `list_targets`、`collect`、`diagnose`、`refine`、`publish` 五個 task。
- `src/training_kb/writing/prompts.py` 多一個 `prompt_diagnose_weak`（問模型「哪幾步有問題」的題目）。診斷結果的 schema `WeakDiagnosis`、`DiagnosisItem` 由 Phase 05（`05-Phase05-Writing-Bedrock呼叫與輸出驗證.md`）建立，本階段只使用，不重寫一份。
- `tests/unit/test_pipelines_feedback.py`：把設計文件第 15 節「Review」那一列的驗收條件全部寫成測試。

做**不到**的事（留給下一階段）：這一階段還沒有 `propose_rules`（提出候選寫作規則）、還沒有 Step Functions 的流程定義檔、還沒有每天自動觸發的排程。那些都在 Phase 18。

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
                ^^^^^^^^^^^^^^^^
                 你在這裡
                                                                                        |
展示與驗收層    21 Demo 種子資料 -> 22 靜態教學站 -> 23 Demo 控制台 -> 24 失敗復原驗收 -> 25 安全與當日準備
```

你會用到前面這些階段的成果：

```text
Phase 02  models.py      Feedback / TutorialStep / TutorialContent / StepDraft / RuleStatus
Phase 03  repository.py  get_config_list / begin_operation / load_operation / 鎖
Phase 05  writing/client.py   Writer / FakeWriter（測試用假模型）/ generate_json
          writing/schemas.py  StepRewrite / StepRewriteItem / WeakDiagnosis / DiagnosisItem
Phase 06  writing/rules.py    rules_for_content（挑 active 規則、產生 prompt 文字）
Phase 07  content.py     allocate_version / create_version / validate_content
Phase 08  content.py     publish / with_tutorial_lock；site.py  SiteRenderer
Phase 09  repository.py  list_feedback_of_version / get_steps / list_rules / list_features
Phase 13  pipelines/common.py  Deps / TaskFn / run_sequence
Phase 16  content.py          parse_markdown（把 S3 全文還原成五段內容）
          writing/prompts.py  prompt_rewrite_steps
```

---

## 3. 開始前檢查

這一階段大量消費前面階段的成果。開始前先確認它們都在，否則寫到一半才發現缺東西會很難除錯。

- [ ] **檢查 1：專案能跑測試**

執行：

```bash
cd ~/AWS-Hackathon
uv run pytest tests/unit -q
```

預期：看到一行類似 `NN passed`，沒有 `error`。如果出現 `command not found: uv`，回去做 Phase 01（`01-Phase01-專案骨架與開發環境.md`）。

- [ ] **檢查 2：Phase 07／08 的 content 函式都在**

執行：

```bash
uv run python -c "from training_kb.content import allocate_version, create_version, publish, validate_content, with_tutorial_lock; print('content ok')"
```

預期：印出 `content ok`。若出現 `ImportError: cannot import name 'publish'`，代表 Phase 08 還沒做完。

- [ ] **檢查 3：Phase 05 的模型輸出 schema 都在**

執行：

```bash
uv run python - <<'PY'
from training_kb.writing.schemas import DiagnosisItem, StepRewrite, StepRewriteItem, WeakDiagnosis
print("StepRewrite 欄位：", sorted(StepRewrite.model_fields))
print("StepRewriteItem 欄位：", sorted(StepRewriteItem.model_fields))
print("WeakDiagnosis 欄位：", sorted(WeakDiagnosis.model_fields))
print("DiagnosisItem 欄位：", sorted(DiagnosisItem.model_fields))
PY
```

預期：依序印出 `['rewrites']`、`['feature_id', 'index', 'text', 'type']`、`['items']`、`['index', 'reason']`。這四個 schema 由 Phase 05（`05-Phase05-Writing-Bedrock呼叫與輸出驗證.md`）建立，本階段直接沿用同一組名稱與欄位，不另外做一份。

- [ ] **檢查 3b：Phase 16 的改寫 prompt 與全文還原函式都在**

執行：

```bash
uv run python -c "from training_kb.writing.prompts import prompt_rewrite_steps; from training_kb.content import parse_markdown; print('phase16 ok')"
```

預期：印出 `phase16 ok`。這兩個由 Phase 16（`16-Phase16-Release-Note-Update流程.md`）建立；Phase 16 的文件已經寫明「Phase 17 的 REFINE 也會用同一個函式」，所以本階段直接沿用，不再寫一份解析器。

- [ ] **檢查 4：Phase 06 的規則注入函式在**

執行：

```bash
uv run python -c "from training_kb.writing.rules import rules_for_content; print('rules ok')"
```

預期：印出 `rules ok`。

- [ ] **檢查 5：Repository 有本階段需要的方法**

執行：

```bash
uv run python - <<'PY'
from training_kb.repository import Repository
need = [
    "scan_entity", "get_tutorial", "get_version", "get_steps",
    "list_feedback_of_version", "list_rules", "list_features",
    "get_config_list", "get_object",
    "begin_operation", "load_operation", "update_operation",
]
print("缺少：", [n for n in need if not hasattr(Repository, n)])
PY
```

預期：印出 `缺少： []`。清單不是空的時候，回去補 Phase 03（`03-Phase03-Repository-本機儲存層.md`）或 Phase 09（`09-Phase09-圖譜查詢與backfill.md`）。

- [ ] **檢查 6：pipelines 的共用型別在**

執行：

```bash
uv run python -c "from training_kb.pipelines.common import Deps, run_sequence; print('common ok')"
```

預期：印出 `common ok`。

- [ ] **檢查 7：feedback.py 檔案位置**

執行：

```bash
ls -l src/training_kb/pipelines/
```

預期：看到 `__init__.py`、`common.py`、`ticket.py`、`release.py`。如果已經有 `feedback.py`，先打開看內容，本階段會從空白開始寫。

---

## 4. 名詞小抄

| 名詞 | 白話解釋 | 在本階段哪裡用到 |
|---|---|---|
| Feedback（回饋） | 使用者看完教學後填的一筆資料：1～5 分的評分、可空的問題類別、可空的留言、提交者 ID。 | `collect` 讀它算平均分；`diagnose` 拿它問模型 |
| TutorialVersion（教學版本） | 一篇教學某一次修改後的完整內容，ID 長得像 `prepare-meeting@v2`。 | 每篇只看目前上架的那一版 |
| current_version | 一篇教學「現在讀者看得到」的那一版。只有 publish 成功後才會指過去。 | `list_targets` 只挑 current_version |
| published_at | 版本的上架時間。是 `null`（空）就代表還沒上架。 | `list_targets` 過濾掉未上架版本 |
| 核定問題類別 | 系統認可的回饋問題分類，初始只有「找不到按鈕」「缺少資訊」兩個（設計文件 D13）。使用者填了別的值會變成「待分類」。 | 算「同一類 ≥ 5 筆」時只數核定類別 |
| 待分類 | 留言分類不出來時填的值。它**不算**任何一個核定類別。 | `approved_category_counts` 會跳過它 |
| 弱教學 | 同時滿足「平均 < 3.5」「筆數 ≥ 門檻」「同一核定類別 ≥ 5」三個條件的版本。 | `is_weak` |
| REFINE | 五種教學動作之一（設計文件 §8.1），意思是「因為回饋而產生下一版」。另外四種是 CREATE、UPDATE、KEEP、RETIRE。 | `refine` task |
| reason（版本原因） | 每一版都要記錄「為什麼產生這一版」的一句話。REFINE 的格式固定是 `feedback:<n> 則 <category>`。 | `refine_reason` |
| 證據集合 / evidence_key | 這一次判斷用到的那一批回饋 ID。把它們排序後算一個 16 個字的指紋，用來判斷「這批回饋是不是已經處理過了」。 | `evidence_key` |
| 操作紀錄（operation record） | 一筆記錄「某一次邏輯操作做到哪裡」的資料，存在 DynamoDB 的 `OPS#<id>` 與 S3 的 `operations/<id>.json`。這是本計劃選擇，對應設計文件的待確認事項 O2。 | 判斷「這批證據處理過沒」、重試時重用版號 |
| task | Step Functions 流程裡的一個工作節點。在程式裡就是一個 `(state, deps) -> state` 的函式。 | `TASKS` 字典裡的五個函式 |
| state | task 之間傳遞的小字典，只放 ID、判斷結果與 S3 key，不放教學全文或向量（設計文件 §14.3）。 | 每個 task 的第一個參數 |
| policy（檢視門檻） | `formal`（正式，n ≥ 10）或 `demo`（展示，n ≥ 8）。兩者只差在筆數門檻，其他條件完全一樣（F20）。 | `ReviewPolicy` |
| F20 / F23 / F24 / D28 | 設計文件第 19 節的釐清決策編號。F 開頭是功能決策，D 開頭是資料決策。 | 第 10 節對照表 |
| S6 | 設計文件第 16 節的交付切片編號，代表「Demo 八筆走隔離門檻、REFINE 只改有效步驟」這一段可展示的成果。 | 第 7 節完成檢查 |
| O2 | 設計文件第 18 節的待確認事項編號，指「操作紀錄與接受順序要怎麼存」。 | 證據紀錄的存放位置 |

---

## 5. 設計說明

### 5.1 一次每日檢視的兩條分流

設計文件 §7.5 說每日檢視要**分開做兩件事**：挑弱教學去 REFINE，和從同版同類回饋提出候選規則。這兩件事的門檻不一樣，互相不擋。本階段只做左邊那條；右邊那條在 Phase 18。

```text
        每日排程（Phase 18 接上 EventBridge）
                     |
                     v
        +------------------------------+
        | list_targets                 |
        | 找出所有 active 教學的        |
        | 目前已發布 current_version    |
        +---------------+--------------+
                        |
        對每一篇教學各做一次（Step Functions 的 Map；本階段先用迴圈）
                        |
                        v
        +------------------------------+
        | collect                      |
        | 讀該版截至本次執行的          |
        | 全部有效回饋                  |
        | -> n、平均、各類別筆數        |
        | -> evidence_key               |
        +---------------+--------------+
                        |
         +--------------+---------------------------+
         |                                          |
         v                                          v
  +--------------------+                  +----------------------+
  | propose_rules      |                  | diagnose             |
  | 同版同類 >= 5 筆    |                  | 是不是弱教學？        |
  | -> candidate 規則   |                  +----------+-----------+
  | （Phase 18 才實作） |                             |
  +--------------------+              +--------------+--------------+
                                      | 否                          | 是
                                      v                             v
                               action = SKIP             這批證據處理過了嗎？
                               不建版本                    |           |
                                                         是|           |否
                                                           v           v
                                                    action=SKIP   問模型：哪幾步有問題
                                                    不建版本            |
                                                              +---------+---------+
                                                              | 沒有有效步驟      | 有
                                                              v                   v
                                                    action = NO_STEP        action = REFINE
                                                    記「無可改步驟」               |
                                                    不建版本                       v
                                                                        +----------------------+
                                                                        | refine               |
                                                                        | 取鎖 -> 分版號 ->     |
                                                                        | 取 active 規則 ->     |
                                                                        | 只改命中步驟 ->       |
                                                                        | 核對其餘逐字相同 ->   |
                                                                        | create_version        |
                                                                        | （published_at=null） |
                                                                        +----------+-----------+
                                                                                   |
        所有教學都跑完之後，才做最後一步 ------------------------------------------+
                        |
                        v
        +------------------------------+
        | publish                      |
        | 把這一輪所有新版本一次送出    |
        | 任一篇失敗 -> 整次不發布      |
        +------------------------------+
```

為什麼順序是「候選規則的證據檢查先完成，再準備 REFINE，publish 放最後」？設計文件 §7.5 的理由是：publish 是唯一會讓讀者看到變化的動作，所以要等所有需要驗證的判斷都做完才做，這樣中途失敗時讀者看到的還是舊版（F49）。

### 5.2 弱教學的門檻判定表

三個條件**同時成立**才算弱教學。判斷時一律使用未四捨五入的原始數值；畫面上顯示幾位小數不影響門檻（設計文件 §11.2 最後一句）。

```text
+--------------------+---------------------------+--------------------------------+
| 條件               | 正式 policy = "formal"    | 展示 policy = "demo"           |
+--------------------+---------------------------+--------------------------------+
| 平均評分           | avg < 3.5                 | avg < 3.5   （完全相同）        |
| 有效回饋筆數       | n   >= 10                 | n   >= 8    （只有這一格不同）  |
| 同一核定類別筆數   | cnt >= 5                  | cnt >= 5    （完全相同）        |
+--------------------+---------------------------+--------------------------------+

邊界值（設計文件第 15 節「Review」列指定要測）：
  avg = 3.49  -> 成立        avg = 3.50  -> 不成立
  n   = 9     -> formal 不成立；n = 10 -> formal 成立
  n   = 7     -> demo   不成立；n = 8  -> demo   成立
  cnt = 4     -> 不成立      cnt = 5   -> 成立
  avg = None（一筆有效評分都沒有）-> 不成立（F52：不當成 0 分）
```

門檻數字來自 Phase 01 的 `config.Thresholds`：`weak_avg_below = 3.5`、`weak_min_feedback_formal = 10`、`weak_min_feedback_demo = 8`、`category_min_count = 5`。程式不要把數字寫死在判斷式裡，一律從 `Thresholds` 讀。

### 5.3 「不重做」是怎麼判斷的

F23 規定：同一批回饋不可以每天都觸發一次 REFINE，必須有**新的有效證據**才能再做一次。設計文件說證據紀錄的存放位置屬於待確認事項 O2。

**本計劃選擇（對應 O2）：** 用共用的操作紀錄來記，操作 ID 是 `review:<slug>:<evidence_key>`。

```text
第 1 天：該版有效回饋 = {f_12, f_15, f_19, f_23, f_27, f_31, f_34, f_40, f_44, f_47}
        evidence_key = sha256(排序後的 JSON)[:16] = 例如 "4f2c9a1b77e05d63"
        操作 ID       = "review:prepare-meeting:4f2c9a1b77e05d63"
        -> 這筆操作紀錄不存在 -> 可以做 -> 做完寫 status = "refined"

第 2 天：沒有新回饋，有效回饋集合一模一樣
        evidence_key 一模一樣 -> 操作 ID 一模一樣
        -> 操作紀錄已存在且 status 已是終局 -> 跳過，不建版本

第 3 天：多了 f_51
        有效回饋集合變了 -> evidence_key 變了 -> 操作 ID 變了
        -> 可以再做一次
```

兩個細節：

1. **evidence_key 用「該版全部有效回饋」算，不是只用命中類別的那幾筆。** 本計劃選擇。理由是 F23 的字面是「新的有效證據」，任何一筆新的有效回饋都算新證據；而且平均分數也是用全部回饋算的，用同一個集合當指紋比較一致。設計文件沒有規定要用哪一個集合，所以這裡標成本計劃選擇。
2. **操作紀錄的 status 有分階段。** `started` 代表開始了但還沒做完（例如上次執行中途壞掉），這種情況要**繼續做**，而且 `allocate_version` 會用同一個操作 ID 找回原本分到的版號（設計文件 D26：同一邏輯變更重試重用原版本號）。只有 `no_step`、`refined`、`published` 這三個終局狀態才代表「這批證據處理完了」，下次要跳過。

### 5.4 REFINE 只改命中步驟

設計文件 §7.6 要求：改寫步驟時，「編號存在、僅改命中集合；其餘文字逐字相同」必須由**程式**驗證，不能只相信模型。所以 `refine` 會做三層檢查：

```text
模型回傳 StepRewrite(rewrites=[StepRewriteItem(index, text, type, feature_id), ...])
        |
        v
[檢查 1] apply_step_rewrites
   - 回傳的 index 不在命中集合 -> ContentError
   - 同一個 index 回傳兩次     -> ContentError
   - 命中集合有 index 沒回傳   -> ContentError
        |
        v
[檢查 2] assert_unchanged_steps
   - 步驟總數改變                       -> ContentError
   - 未命中步驟的 type/text/feature_id
     跟原本不是逐字相同                 -> ContentError
        |
        v
[檢查 3] content.validate_content（Phase 07）
   - 五段是否齊全、每步恰好一個存在的 Feature、type 是否合法
        |
        v
   create_version（寫 S3 全文與 diff、VERSION／STEP／關係邊，published_at = null）
```

### 5.5 本階段會碰到的目錄與資料形狀

```text
src/training_kb/
  pipelines/
    common.py        Deps / TaskFn / run_sequence            （Phase 13 已有）
    ticket.py                                                （Phase 13 已有）
    release.py                                               （Phase 16 已有）
    feedback.py      << 本階段新增
  writing/
    schemas.py       （Phase 05 已建立 StepRewrite / WeakDiagnosis，本階段不改）
    prompts.py       << 本階段新增 prompt_diagnose_weak
  content.py         （Phase 16 已建立 parse_markdown，本階段只呼叫）
tests/unit/
  test_pipelines_feedback.py   << 本階段新增
  test_writing_diagnose.py     << 本階段新增
```

task 之間傳的 state（只有 ID 與小型判斷結果，沒有全文）：

```text
執行層級（Map 之前）
{
  "run_id":       "2026-09-14",                      這一輪的識別字串
  "operation_id": "review:2026-09-14",               這一輪整體的操作 ID
  "policy":       "formal",                          formal 或 demo
  "targets": [ {"slug": "prepare-meeting",
                "version_id": "prepare-meeting@v2"} , ... ]
}

單篇層級（Map 之內，每篇一份）
{
  "run_id": ..., "policy": ...,
  "slug": "prepare-meeting", "version_id": "prepare-meeting@v2",

  collect 之後新增：
  "feedback_ids":        ["f_12", "f_15", ...],      排序後的有效回饋 ID
  "n":                   10,                          有效回饋筆數
  "avg":                 2.875,                       未四捨五入
  "approved_categories": ["找不到按鈕", "缺少資訊"],
  "category_counts":     {"找不到按鈕": 8},
  "top_category":        "找不到按鈕",
  "top_category_count":  8,
  "evidence_key":        "4f2c9a1b77e05d63",

  diagnose 之後新增：
  "weak":                True,
  "action":              "REFINE" | "NO_STEP" | "SKIP",
  "skip_reason":         "無可改步驟",                 只有跳過時才有
  "target_indexes":      [3],
  "diagnosis":           [{"index": 3, "reason": "沒有寫按鈕在哪一頁"}],
  "review_operation_id": "review:prepare-meeting:4f2c9a1b77e05d63",

  refine 之後新增：
  "new_version_id":      "prepare-meeting@v3",
  "reason":              "feedback:8 則 找不到按鈕",
  "rules_applied":       ["R-007"]
}

publish（Map 之後）讀 state["items"]，也就是所有單篇 state 組成的清單。
```

---

## 6. 工作項目

### Task 1：檢視門檻 ReviewPolicy 與 is_weak

**目的**：把「正式 n ≥ 10、Demo n ≥ 8、其餘條件相同」以及弱教學三條件寫成兩個純函式。

**檔案**：
- 新增：`src/training_kb/pipelines/feedback.py`
- 測試：`tests/unit/test_pipelines_feedback.py`

**介面**：
- 消費：`training_kb.config.Thresholds`（Phase 01）、`training_kb.errors.PermanentError`（Phase 01）
- 產出：
  - `pipelines.feedback.ReviewPolicy`（dataclass，欄位 `min_feedback: int`）
  - `ReviewPolicy.formal(thresholds: Thresholds | None = None) -> ReviewPolicy`
  - `ReviewPolicy.demo(thresholds: Thresholds | None = None) -> ReviewPolicy`
  - `ReviewPolicy.for_name(name: str, thresholds: Thresholds | None = None) -> ReviewPolicy`（本階段新增，簡報第 6 節未列）
  - `pipelines.feedback.is_weak(avg: float | None, n: int, top_category_count: int, policy: ReviewPolicy, thresholds: Thresholds) -> bool`

- [ ] **步驟 1：寫測試**

建立 `tests/unit/test_pipelines_feedback.py`：

```python
"""Phase 17／18：Feedback Review 流程的單元測試。"""

from __future__ import annotations

import pytest

from training_kb.config import Thresholds
from training_kb.errors import PermanentError
from training_kb.pipelines.feedback import ReviewPolicy, is_weak

TH = Thresholds()


def test_formal_policy_needs_ten_feedback():
    assert ReviewPolicy.formal().min_feedback == 10


def test_demo_policy_needs_eight_feedback():
    assert ReviewPolicy.demo().min_feedback == 8


def test_for_name_maps_policy_string():
    assert ReviewPolicy.for_name("formal").min_feedback == 10
    assert ReviewPolicy.for_name("demo").min_feedback == 8


def test_for_name_rejects_unknown_policy():
    with pytest.raises(PermanentError):
        ReviewPolicy.for_name("weekly")


@pytest.mark.parametrize(
    ("n", "expected"),
    [(9, False), (10, True)],
)
def test_formal_sample_size_boundary(n, expected):
    assert is_weak(2.9, n, 5, ReviewPolicy.formal(), TH) is expected


@pytest.mark.parametrize(
    ("n", "expected"),
    [(7, False), (8, True)],
)
def test_demo_sample_size_boundary(n, expected):
    assert is_weak(2.9, n, 5, ReviewPolicy.demo(), TH) is expected


@pytest.mark.parametrize(
    ("avg", "expected"),
    [(3.49, True), (3.5, False)],
)
def test_average_boundary(avg, expected):
    assert is_weak(avg, 10, 5, ReviewPolicy.formal(), TH) is expected


@pytest.mark.parametrize(
    ("count", "expected"),
    [(4, False), (5, True)],
)
def test_recurring_category_boundary(count, expected):
    assert is_weak(2.9, 10, count, ReviewPolicy.formal(), TH) is expected


def test_no_rating_is_not_weak():
    # F52：沒有任何有效評分時平均是 None，不能當成 0 分。
    assert is_weak(None, 10, 5, ReviewPolicy.formal(), TH) is False


def test_demo_eight_feedback_does_not_pass_formal():
    # 設計文件 §11.2：Demo 的八筆在正式門檻下不觸發 REFINE。
    assert is_weak(2.875, 8, 8, ReviewPolicy.demo(), TH) is True
    assert is_weak(2.875, 8, 8, ReviewPolicy.formal(), TH) is False
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：

```bash
uv run pytest tests/unit/test_pipelines_feedback.py -v
```

預期：FAIL，錯誤訊息是 `ModuleNotFoundError: No module named 'training_kb.pipelines.feedback'`。因為 `feedback.py` 還不存在，Python 找不到這個模組。

- [ ] **步驟 3：寫最少的程式讓測試通過**

建立 `src/training_kb/pipelines/feedback.py`：

```python
"""Feedback Review 流程：弱教學判定、REFINE 與候選規則（Phase 17、18）。

設計文件 §7.5、§7.6。task 之間只傳 ID 與小型判斷結果，不傳教學全文。
"""

from __future__ import annotations

from dataclasses import dataclass

from training_kb.config import Thresholds
from training_kb.errors import PermanentError


@dataclass(frozen=True)
class ReviewPolicy:
    """每日檢視的樣本數門檻。

    正式與 Demo 只差在 min_feedback；平均 < 3.5 與同類 >= 5 完全相同（F20）。
    """

    min_feedback: int

    @classmethod
    def formal(cls, thresholds: Thresholds | None = None) -> "ReviewPolicy":
        settings = thresholds or Thresholds()
        return cls(min_feedback=settings.weak_min_feedback_formal)

    @classmethod
    def demo(cls, thresholds: Thresholds | None = None) -> "ReviewPolicy":
        settings = thresholds or Thresholds()
        return cls(min_feedback=settings.weak_min_feedback_demo)

    @classmethod
    def for_name(cls, name: str, thresholds: Thresholds | None = None) -> "ReviewPolicy":
        """把 state 裡的 policy 字串轉成門檻物件。"""
        if name == "formal":
            return cls.formal(thresholds)
        if name == "demo":
            return cls.demo(thresholds)
        raise PermanentError(f"未知的 review policy：{name}（只接受 formal 或 demo）")


def is_weak(
    avg: float | None,
    n: int,
    top_category_count: int,
    policy: ReviewPolicy,
    thresholds: Thresholds,
) -> bool:
    """三個條件同時成立才是弱教學（設計文件 §7.5）。

    使用未四捨五入的 avg；沒有任何有效評分時 avg 是 None，不算弱教學（F52）。
    """
    if avg is None:
        return False
    return (
        avg < thresholds.weak_avg_below
        and n >= policy.min_feedback
        and top_category_count >= thresholds.category_min_count
    )
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：

```bash
uv run pytest tests/unit/test_pipelines_feedback.py -v
```

預期：PASS，看到 14 個測試全綠。

- [ ] **步驟 5：commit**

```bash
git add src/training_kb/pipelines/feedback.py tests/unit/test_pipelines_feedback.py
git commit -m "feat(feedback): 加入弱教學三條件門檻與正式／Demo policy"
```

---

### Task 2：證據指紋、版本原因與操作 ID

**目的**：把「這批回饋處理過沒有」的指紋、REFINE 的 reason 格式、以及操作紀錄的 ID 規則寫成三個純函式。

**檔案**：
- 修改：`src/training_kb/pipelines/feedback.py`
- 修改：`tests/unit/test_pipelines_feedback.py`

**介面**：
- 產出：
  - `pipelines.feedback.evidence_key(feedback_ids: list[str]) -> str`
  - `pipelines.feedback.refine_reason(n: int, category: str) -> str`
  - `pipelines.feedback.review_operation_id(slug: str, key: str) -> str`（本階段新增，簡報第 6 節未列）
  - `pipelines.feedback.REVIEW_DONE_STATUSES: frozenset[str]`（本階段新增）

- [ ] **步驟 1：寫測試**

在 `tests/unit/test_pipelines_feedback.py` 的 import 區加入：

```python
from training_kb.pipelines.feedback import (
    REVIEW_DONE_STATUSES,
    ReviewPolicy,
    evidence_key,
    is_weak,
    refine_reason,
    review_operation_id,
)
```

（把原本那行 `from training_kb.pipelines.feedback import ReviewPolicy, is_weak` 換成上面這一段。）

然後在檔案最後加入：

```python
def test_evidence_key_is_order_independent():
    a = evidence_key(["f_15", "f_12", "f_40"])
    b = evidence_key(["f_40", "f_12", "f_15"])
    assert a == b


def test_evidence_key_changes_when_new_feedback_arrives():
    before = evidence_key(["f_12", "f_15"])
    after = evidence_key(["f_12", "f_15", "f_51"])
    assert before != after


def test_evidence_key_is_sixteen_hex_chars():
    key = evidence_key(["f_12"])
    assert len(key) == 16
    assert all(ch in "0123456789abcdef" for ch in key)


def test_refine_reason_uses_design_format():
    # D28：格式固定為 feedback:<n> 則 <category>
    assert refine_reason(8, "找不到按鈕") == "feedback:8 則 找不到按鈕"


def test_review_operation_id_combines_slug_and_key():
    assert review_operation_id("prepare-meeting", "abc123") == "review:prepare-meeting:abc123"


def test_done_statuses_cover_three_terminal_states():
    assert REVIEW_DONE_STATUSES == frozenset({"no_step", "refined", "published"})
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：

```bash
uv run pytest tests/unit/test_pipelines_feedback.py -v
```

預期：FAIL，錯誤訊息是 `ImportError: cannot import name 'evidence_key' from 'training_kb.pipelines.feedback'`。因為這四個名稱還沒寫。

- [ ] **步驟 3：寫最少的程式讓測試通過**

在 `src/training_kb/pipelines/feedback.py` 的 import 區改成：

```python
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from training_kb.config import Thresholds
from training_kb.errors import PermanentError
```

在 `is_weak` 後面加入：

```python
#: 操作紀錄走到這三個狀態，代表這批證據已經處理完，下次不重做（F23）。
REVIEW_DONE_STATUSES: frozenset[str] = frozenset({"no_step", "refined", "published"})


def evidence_key(feedback_ids: list[str]) -> str:
    """把一批回饋 ID 轉成固定長度的指紋。

    先去重再排序，所以同一批 ID 不管什麼順序都得到同一個結果；
    只要多一筆或少一筆有效回饋，指紋就會改變（F23）。
    """
    payload = json.dumps(sorted(set(feedback_ids)), ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def refine_reason(n: int, category: str) -> str:
    """REFINE 版本的 reason，格式由 D28 固定。

    n 是本次該類別的有效證據數，不是該版全部回饋數。
    """
    return f"feedback:{n} 則 {category}"


def review_operation_id(slug: str, key: str) -> str:
    """每日檢視在單篇教學上的操作 ID（本計劃選擇，對應待確認事項 O2）。"""
    return f"review:{slug}:{key}"
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：

```bash
uv run pytest tests/unit/test_pipelines_feedback.py -v
```

預期：PASS，20 個測試全綠。

- [ ] **步驟 5：commit**

```bash
git add src/training_kb/pipelines/feedback.py tests/unit/test_pipelines_feedback.py
git commit -m "feat(feedback): 加入證據指紋、REFINE reason 與操作 ID 規則"
```

---

### Task 3：list_targets task 與測試用假 Repository

**目的**：找出所有還在使用中的教學，取出它們目前已上架的那一版；同時建立後面幾個 Task 都會用到的假 Repository。

**檔案**：
- 修改：`src/training_kb/pipelines/feedback.py`
- 修改：`tests/unit/test_pipelines_feedback.py`

**介面**：
- 消費：`repository.Repository.scan_entity`、`get_tutorial`、`get_version`（Phase 03、09）、`keys.parse_pk`（Phase 02）、`models.TutorialStatus`（Phase 02）、`pipelines.common.Deps`（Phase 13）
- 產出：`pipelines.feedback.task_list_targets(state: dict, deps: Deps) -> dict`

- [ ] **步驟 1：寫測試**

在 `tests/unit/test_pipelines_feedback.py` 的 import 區後面（`TH = Thresholds()` 那一行之前）插入這一大段。這是整個測試檔共用的假物件，後面每個 Task 都會用到：

```python
from datetime import datetime, timezone

from training_kb.config import Settings
from training_kb.models import (
    Feature,
    Feedback,
    StepType,
    Tutorial,
    TutorialStatus,
    TutorialStep,
    TutorialVersion,
)
from training_kb.pipelines.common import Deps
from training_kb.writing.client import CallTrace, FakeWriter

NOW = datetime(2026, 9, 14, 0, 30, tzinfo=timezone.utc)


def make_settings() -> Settings:
    """測試用的最小設定；門檻用預設值。"""
    return Settings(
        aws_region="us-east-1",
        table_name="training_kb",
        bucket_name="training-kb-content-test",
        project_id="demo-project",
        embed_model_id="amazon.titan-embed-text-v2:0",
        embed_dimensions=1024,
        gen_model_id="test.claude",
        github_webhook_secret="not-a-real-secret",
    )


class FakeRepo:
    """只實作本階段用得到的 Repository 方法，全部放在記憶體裡。

    這樣單元測試不需要連 AWS，也不需要 moto。
    """

    def __init__(self) -> None:
        self.tutorials: dict[str, Tutorial] = {}
        self.versions: dict[str, TutorialVersion] = {}
        self.steps: dict[str, list[TutorialStep]] = {}
        self.feedback: dict[str, list[Feedback]] = {}
        self.features: list[Feature] = []
        self.rules: list = []
        self.objects: dict[str, bytes] = {}
        self.operations: dict[str, dict] = {}
        self.config: dict[str, list[str]] = {}
        self.counters: dict[str, int] = {}
        self.saved_rules: list = []

    # --- 掃描與讀取 ---
    def scan_entity(self, entity: str) -> list[dict]:
        if entity != "TUTORIAL":
            return []
        return [{"PK": f"TUTORIAL#{slug}", "entity": "TUTORIAL"} for slug in self.tutorials]

    def get_tutorial(self, slug: str) -> Tutorial | None:
        return self.tutorials.get(slug)

    def get_version(self, version_id: str) -> TutorialVersion | None:
        return self.versions.get(version_id)

    def get_steps(self, version_id: str) -> list[TutorialStep]:
        return sorted(self.steps.get(version_id, []), key=lambda s: s.index)

    def list_feedback_of_version(self, version_id: str) -> list[Feedback]:
        return list(self.feedback.get(version_id, []))

    def list_features(self) -> list[Feature]:
        return list(self.features)

    def list_rules(self, status=None) -> list:
        if status is None:
            return list(self.rules)
        return [r for r in self.rules if r.status == status]

    def get_config_list(self, name: str, default: list[str]) -> list[str]:
        return list(self.config.get(name, default))

    def get_object(self, key: str) -> bytes | None:
        return self.objects.get(key)

    # --- 操作紀錄（O2 本計劃選擇）---
    def begin_operation(self, operation_id: str, record: dict) -> bool:
        if operation_id in self.operations:
            return False
        self.operations[operation_id] = dict(record)
        return True

    def load_operation(self, operation_id: str) -> dict | None:
        record = self.operations.get(operation_id)
        return dict(record) if record is not None else None

    def update_operation(self, operation_id: str, patch: dict) -> None:
        self.operations.setdefault(operation_id, {}).update(patch)

    # --- 寫入（Phase 18 會用到）---
    def put_rule(self, r, *, if_not_exists: bool = False) -> bool:
        # 簽名與 Phase 09 的 Repository.put_rule 一致。
        self.saved_rules.append(r)
        self.rules.append(r)
        return True

    def next_counter(self, name: str) -> int:
        self.counters[name] = self.counters.get(name, 0) + 1
        return self.counters[name]


def make_deps(repo: FakeRepo, writer: FakeWriter | None = None) -> Deps:
    trace = CallTrace()
    return Deps(
        repo=repo,
        writer=writer or FakeWriter(trace=trace),
        settings=make_settings(),
        trace=trace,
        now=lambda: NOW,
    )


def add_tutorial(
    repo: FakeRepo,
    slug: str,
    *,
    current_version: str | None,
    status: TutorialStatus = TutorialStatus.active,
    published: bool = True,
    cluster_id: str = "c12",
) -> None:
    """在假 Repository 裡放一篇教學與它的目前版本。"""
    repo.tutorials[slug] = Tutorial(
        slug=slug,
        current_version=current_version,
        topic=f"{slug} 主題",
        feature_ids=["Prepare"],
        status=status,
        cluster_id=cluster_id,
    )
    if current_version is None:
        return
    repo.versions[current_version] = TutorialVersion(
        version_id=current_version,
        supersedes=None,
        reason="gap:c12",
        rules_applied=[],
        s3_key=f"tutorials/{slug}/v1.md",
        published_at="2026-08-01T00:00:00Z" if published else None,
    )
```

然後在檔案最後加入 `list_targets` 的測試：

```python
def test_list_targets_only_returns_active_published_current_version():
    repo = FakeRepo()
    add_tutorial(repo, "prepare-meeting", current_version="prepare-meeting@v2")
    add_tutorial(repo, "share-summary", current_version="share-summary@v1")
    # 已退役：不檢視
    add_tutorial(
        repo, "old-topic", current_version="old-topic@v3", status=TutorialStatus.retired
    )
    # 還沒發布過第一版：current_version 是空的
    add_tutorial(repo, "draft-topic", current_version=None)
    # current_version 指到一個 published_at 還是空的版本
    add_tutorial(repo, "half-done", current_version="half-done@v1", published=False)

    out = task_list_targets({"run_id": "2026-09-14", "policy": "formal"}, make_deps(repo))

    assert out["targets"] == [
        {"slug": "prepare-meeting", "version_id": "prepare-meeting@v2"},
        {"slug": "share-summary", "version_id": "share-summary@v1"},
    ]


def test_list_targets_keeps_original_state_keys():
    repo = FakeRepo()
    add_tutorial(repo, "prepare-meeting", current_version="prepare-meeting@v2")

    out = task_list_targets({"run_id": "2026-09-14", "policy": "demo"}, make_deps(repo))

    assert out["run_id"] == "2026-09-14"
    assert out["policy"] == "demo"
```

並把 import 區的 `from training_kb.pipelines.feedback import (...)` 加上 `task_list_targets`。

- [ ] **步驟 2：跑測試，確認它失敗**

執行：

```bash
uv run pytest tests/unit/test_pipelines_feedback.py -v
```

預期：FAIL，錯誤訊息是 `ImportError: cannot import name 'task_list_targets'`。

- [ ] **步驟 3：寫最少的程式讓測試通過**

在 `src/training_kb/pipelines/feedback.py` 的 import 區補上：

```python
from training_kb.keys import parse_pk
from training_kb.models import TutorialStatus
from training_kb.pipelines.common import Deps
```

在檔案最後加入：

```python
def task_list_targets(state: dict, deps: Deps) -> dict:
    """列出所有要檢視的版本：active 教學的、已發布的 current_version。

    設計文件 §7.5：每日只看 current_version，不看歷史版本。
    """
    slugs = sorted({parse_pk(row["PK"])[1] for row in deps.repo.scan_entity("TUTORIAL")})
    targets: list[dict] = []
    for slug in slugs:
        tutorial = deps.repo.get_tutorial(slug)
        if tutorial is None or tutorial.status != TutorialStatus.active:
            continue
        if not tutorial.current_version:
            continue
        version = deps.repo.get_version(tutorial.current_version)
        if version is None or not version.published_at:
            continue
        targets.append({"slug": slug, "version_id": tutorial.current_version})
    return {**state, "targets": targets}
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：

```bash
uv run pytest tests/unit/test_pipelines_feedback.py -v
```

預期：PASS，22 個測試全綠。

- [ ] **步驟 5：commit**

```bash
git add src/training_kb/pipelines/feedback.py tests/unit/test_pipelines_feedback.py
git commit -m "feat(feedback): 加入 list_targets 與測試用假 Repository"
```

---

### Task 4：collect task 與類別統計

**目的**：讀某一版截至本次執行的全部有效回饋，算出筆數、平均、各核定類別筆數與證據指紋。

**檔案**：
- 修改：`src/training_kb/pipelines/feedback.py`
- 修改：`tests/unit/test_pipelines_feedback.py`

**介面**：
- 消費：`repository.Repository.list_feedback_of_version`（Phase 09）、`get_config_list`（Phase 03）、`models.APPROVED_CATEGORIES_DEFAULT`、`models.PENDING_CATEGORY`（Phase 02）
- 產出：
  - `pipelines.feedback.is_valid_feedback(item: Feedback) -> bool`（本階段新增）
  - `pipelines.feedback.approved_category_counts(feedback: list[Feedback], approved_categories: list[str]) -> dict[str, int]`（本階段新增）
  - `pipelines.feedback.top_approved_category(counts: dict[str, int]) -> tuple[str | None, int]`（本階段新增）
  - `pipelines.feedback.task_collect(state: dict, deps: Deps) -> dict`

- [ ] **步驟 1：寫測試**

在 `tests/unit/test_pipelines_feedback.py` 最後加入：

```python
def add_feedback(repo: FakeRepo, version_id: str, rows: list[tuple[str, str, int, str | None]]) -> None:
    """rows 的每一筆是 (feedback_id, user, rating, category)。"""
    bucket = repo.feedback.setdefault(version_id, [])
    for feedback_id, user, rating, category in rows:
        bucket.append(
            Feedback(
                id=feedback_id,
                tutorial_version=version_id,
                rating=rating,
                user=user,
                category=category,
                comment="第三步沒有指出按鈕在哪一頁與位置",
                ts="2026-08-02T09:00:00Z",
            )
        )


A_V1_ROWS = [
    ("f_12", "u_01", 2, "找不到按鈕"),
    ("f_15", "u_02", 2, "找不到按鈕"),
    ("f_19", "u_03", 3, "找不到按鈕"),
    ("f_23", "u_04", 3, "找不到按鈕"),
    ("f_27", "u_05", 3, "找不到按鈕"),
    ("f_31", "u_06", 3, "找不到按鈕"),
    ("f_34", "u_07", 3, "找不到按鈕"),
    ("f_40", "u_08", 4, "找不到按鈕"),
]


def test_collect_computes_unrounded_average_and_counts():
    repo = FakeRepo()
    add_tutorial(repo, "prepare-meeting", current_version="prepare-meeting@v1")
    add_feedback(repo, "prepare-meeting@v1", A_V1_ROWS)

    out = task_collect(
        {"slug": "prepare-meeting", "version_id": "prepare-meeting@v1", "policy": "demo"},
        make_deps(repo),
    )

    assert out["n"] == 8
    assert out["avg"] == 23 / 8  # 2.875，未四捨五入
    assert out["top_category"] == "找不到按鈕"
    assert out["top_category_count"] == 8
    assert out["feedback_ids"] == [
        "f_12", "f_15", "f_19", "f_23", "f_27", "f_31", "f_34", "f_40",
    ]
    assert out["evidence_key"] == evidence_key(out["feedback_ids"])


def test_collect_does_not_mix_other_versions():
    repo = FakeRepo()
    add_tutorial(repo, "prepare-meeting", current_version="prepare-meeting@v2")
    add_feedback(repo, "prepare-meeting@v1", A_V1_ROWS)
    add_feedback(
        repo,
        "prepare-meeting@v2",
        [("f_101", "u_01", 5, None), ("f_102", "u_02", 5, None)],
    )

    out = task_collect(
        {"slug": "prepare-meeting", "version_id": "prepare-meeting@v2", "policy": "formal"},
        make_deps(repo),
    )

    assert out["n"] == 2
    assert out["avg"] == 5.0
    assert out["feedback_ids"] == ["f_101", "f_102"]


def test_collect_returns_none_average_when_no_feedback():
    repo = FakeRepo()
    add_tutorial(repo, "share-summary", current_version="share-summary@v1")

    out = task_collect(
        {"slug": "share-summary", "version_id": "share-summary@v1", "policy": "formal"},
        make_deps(repo),
    )

    assert out["n"] == 0
    assert out["avg"] is None
    assert out["top_category"] is None
    assert out["top_category_count"] == 0


def test_pending_category_is_not_counted():
    repo = FakeRepo()
    add_tutorial(repo, "prepare-meeting", current_version="prepare-meeting@v1")
    add_feedback(
        repo,
        "prepare-meeting@v1",
        [
            ("f_01", "u_01", 2, "待分類"),
            ("f_02", "u_02", 2, "待分類"),
            ("f_03", "u_03", 2, "找不到按鈕"),
        ],
    )

    out = task_collect(
        {"slug": "prepare-meeting", "version_id": "prepare-meeting@v1", "policy": "demo"},
        make_deps(repo),
    )

    assert out["category_counts"] == {"找不到按鈕": 1}
    assert out["top_category_count"] == 1


def test_top_category_breaks_tie_by_name():
    counts = {"缺少資訊": 5, "找不到按鈕": 5}
    assert top_approved_category(counts) == ("找不到按鈕", 5)
```

把 import 區的 `from training_kb.pipelines.feedback import (...)` 補上 `task_collect`、`top_approved_category`。

- [ ] **步驟 2：跑測試，確認它失敗**

執行：

```bash
uv run pytest tests/unit/test_pipelines_feedback.py -v
```

預期：FAIL，錯誤訊息是 `ImportError: cannot import name 'task_collect'`。

- [ ] **步驟 3：寫最少的程式讓測試通過**

在 `src/training_kb/pipelines/feedback.py` 的 import 區補上：

```python
from training_kb.models import APPROVED_CATEGORIES_DEFAULT, Feedback, PENDING_CATEGORY, TutorialStatus
```

（把原本那行 `from training_kb.models import TutorialStatus` 整行換掉。）

在檔案最後加入：

```python
def is_valid_feedback(item: Feedback) -> bool:
    """有效回饋：rating 是 1..5 的整數。

    接入端（Phase 10、15 的 validate_feedback）已經擋掉非法值，
    這裡再確認一次，避免手動塞入的資料混進門檻計算。
    """
    return isinstance(item.rating, int) and 1 <= item.rating <= 5


def approved_category_counts(
    feedback: list[Feedback], approved_categories: list[str]
) -> dict[str, int]:
    """統計每個核定問題類別各有幾筆。待分類與未核定的值不計（F43）。"""
    approved = set(approved_categories)
    counts: dict[str, int] = {}
    for item in feedback:
        category = item.category
        if category is None or category == PENDING_CATEGORY or category not in approved:
            continue
        counts[category] = counts.get(category, 0) + 1
    return counts


def top_approved_category(counts: dict[str, int]) -> tuple[str | None, int]:
    """取出筆數最多的核定類別。

    同筆數時取類別名稱字典序較小者，讓結果固定（本計劃選擇；設計文件未規定平手規則）。
    """
    if not counts:
        return (None, 0)
    category = sorted(counts.items(), key=lambda pair: (-pair[1], pair[0]))[0][0]
    return (category, counts[category])


def task_collect(state: dict, deps: Deps) -> dict:
    """讀該版截至本次執行的全部有效回饋（F22）。

    只讀 state["version_id"] 這一版，不混入舊版；也不做「上次之後」的切分。
    """
    version_id = state["version_id"]
    feedback = [
        item
        for item in deps.repo.list_feedback_of_version(version_id)
        if is_valid_feedback(item)
    ]
    feedback_ids = sorted(item.id for item in feedback)
    ratings = [item.rating for item in feedback]
    avg = sum(ratings) / len(ratings) if ratings else None
    approved = deps.repo.get_config_list(
        "approved_categories", list(APPROVED_CATEGORIES_DEFAULT)
    )
    counts = approved_category_counts(feedback, approved)
    category, category_count = top_approved_category(counts)
    return {
        **state,
        "feedback_ids": feedback_ids,
        "n": len(feedback),
        "avg": avg,
        "approved_categories": approved,
        "category_counts": counts,
        "top_category": category,
        "top_category_count": category_count,
        "evidence_key": evidence_key(feedback_ids),
    }
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：

```bash
uv run pytest tests/unit/test_pipelines_feedback.py -v
```

預期：PASS，27 個測試全綠。

- [ ] **步驟 5：commit**

```bash
git add src/training_kb/pipelines/feedback.py tests/unit/test_pipelines_feedback.py
git commit -m "feat(feedback): 加入 collect 與核定類別統計"
```

---

### Task 5：把 S3 全文讀回來、還原成五段內容

**目的**：`create_version` 需要完整的 `TutorialContent`（五段）才能建立新版本，但 DynamoDB 只存每一步的文字。Phase 16 已經做好 `content.parse_markdown`，本階段只要補上「從 S3 把全文讀回來」這一段，再交給它。

**檔案**：
- 修改：`src/training_kb/pipelines/feedback.py`
- 修改：`tests/unit/test_pipelines_feedback.py`

**介面**：
- 消費：`content.parse_markdown(markdown: str, steps: list[TutorialStep]) -> TutorialContent`（Phase 16）、`repository.Repository.get_object`（Phase 03）、`errors.ContentError`（Phase 01）
- 產出：`pipelines.feedback.load_version_content(repo: Repository, version: TutorialVersion, steps: list[TutorialStep]) -> TutorialContent`（本階段新增，簡報第 6 節未列）

> 格式約定：全文由 Phase 07 的 `content.render_markdown` 產生，固定為 `# Title`、`## Problem`、`## Prerequisites`、`## Steps`、`## Expected Outcome` 五段。`## Steps` 區塊由 `parse_markdown` 忽略，因為 STEP item 同時帶 `type` 與 `feature_id`，資訊比文字完整。格式不符時 `parse_markdown` 會拋 `ContentError`，不會產生半套內容。

- [ ] **步驟 1：寫測試**

在 `tests/unit/test_pipelines_feedback.py` 最後加入：

```python
A_V1_MARKDOWN = """# 準備會議

## Problem

會前摘要找不到在哪裡開啟。

## Prerequisites

- 已登入產品
- 已建立至少一場會議

## Steps

1. 開啟會議頁面。
2. 在左側選單找到會議清單。
3. 點選摘要。
4. 確認摘要內容。

## Expected Outcome

你會看到這場會議的會前摘要。
"""


def add_version_with_steps(repo: FakeRepo, slug: str, version_id: str) -> None:
    repo.objects[f"tutorials/{slug}/v1.md"] = A_V1_MARKDOWN.encode("utf-8")
    repo.steps[version_id] = [
        TutorialStep(
            tutorial_version=version_id, index=1, type=StepType.click_ui,
            text="開啟會議頁面。", feature_id="Prepare",
        ),
        TutorialStep(
            tutorial_version=version_id, index=2, type=StepType.read,
            text="在左側選單找到會議清單。", feature_id="Prepare",
        ),
        TutorialStep(
            tutorial_version=version_id, index=3, type=StepType.click_ui,
            text="點選摘要。", feature_id="Prepare",
        ),
        TutorialStep(
            tutorial_version=version_id, index=4, type=StepType.read,
            text="確認摘要內容。", feature_id="Prepare",
        ),
    ]
    repo.features = [Feature(feature_id="Prepare", name="Prepare", aliases=[], first_seen="2026-07-01T00:00:00Z")]


def test_load_version_content_reads_four_sections_from_s3():
    repo = FakeRepo()
    add_tutorial(repo, "prepare-meeting", current_version="prepare-meeting@v1")
    add_version_with_steps(repo, "prepare-meeting", "prepare-meeting@v1")

    version = repo.get_version("prepare-meeting@v1")
    content = load_version_content(repo, version, repo.get_steps("prepare-meeting@v1"))

    assert content.title == "準備會議"
    assert content.problem == "會前摘要找不到在哪裡開啟。"
    assert content.prerequisites == ["已登入產品", "已建立至少一場會議"]
    assert content.expected_outcome == "你會看到這場會議的會前摘要。"


def test_load_version_content_takes_steps_from_dynamodb():
    repo = FakeRepo()
    add_tutorial(repo, "prepare-meeting", current_version="prepare-meeting@v1")
    add_version_with_steps(repo, "prepare-meeting", "prepare-meeting@v1")

    version = repo.get_version("prepare-meeting@v1")
    content = load_version_content(repo, version, repo.get_steps("prepare-meeting@v1"))

    assert [s.text for s in content.steps] == [
        "開啟會議頁面。", "在左側選單找到會議清單。", "點選摘要。", "確認摘要內容。",
    ]
    assert content.steps[0].type == StepType.click_ui
    assert content.steps[0].feature_id == "Prepare"


def test_load_version_content_rejects_missing_object():
    repo = FakeRepo()
    add_tutorial(repo, "prepare-meeting", current_version="prepare-meeting@v1")
    version = repo.get_version("prepare-meeting@v1")

    with pytest.raises(ContentError):
        load_version_content(repo, version, [])


def test_load_version_content_rejects_missing_section():
    repo = FakeRepo()
    add_tutorial(repo, "prepare-meeting", current_version="prepare-meeting@v1")
    add_version_with_steps(repo, "prepare-meeting", "prepare-meeting@v1")
    repo.objects["tutorials/prepare-meeting/v1.md"] = b"# \xe6\xba\x96\xe5\x82\x99\xe6\x9c\x83\xe8\xad\xb0\n"

    version = repo.get_version("prepare-meeting@v1")
    with pytest.raises(ContentError):
        load_version_content(repo, version, repo.get_steps("prepare-meeting@v1"))
```

把 import 區的 `from training_kb.pipelines.feedback import (...)` 補上 `load_version_content`，並在 `from training_kb.errors import PermanentError` 那一行改成 `from training_kb.errors import ContentError, PermanentError`。

- [ ] **步驟 2：跑測試，確認它失敗**

執行：

```bash
uv run pytest tests/unit/test_pipelines_feedback.py -v
```

預期：FAIL，錯誤訊息是 `ImportError: cannot import name 'load_version_content'`。

- [ ] **步驟 3：寫最少的程式讓測試通過**

在 `src/training_kb/pipelines/feedback.py` 的 import 區補上：

```python
from training_kb.content import parse_markdown
from training_kb.errors import ContentError, PermanentError
from training_kb.models import (
    APPROVED_CATEGORIES_DEFAULT,
    PENDING_CATEGORY,
    Feedback,
    TutorialStatus,
    TutorialStep,
    TutorialVersion,
)
from training_kb.repository import Repository
```

（把原本的 `from training_kb.errors import PermanentError` 與 `from training_kb.models import ...` 兩段換成上面這四段。後面的 Task 還會再往 models 那一段加名稱。）

在檔案最後加入：

```python
def load_version_content(
    repo: Repository, version: TutorialVersion, steps: list[TutorialStep]
) -> TutorialContent:
    """把某一版還原成五段內容，給 create_version 使用。

    S3 只存 markdown 全文，所以要先讀回來再交給 Phase 16 建立的
    content.parse_markdown；步驟以 DynamoDB 的 STEP item 為準
    （它同時帶 type 與 feature_id，比全文裡的文字完整）。
    """
    raw = repo.get_object(version.s3_key)
    if raw is None:
        raise ContentError(f"找不到版本全文：{version.s3_key}")
    text = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)
    return parse_markdown(text, sorted(steps, key=lambda step: step.index))
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：

```bash
uv run pytest tests/unit/test_pipelines_feedback.py -v
```

預期：PASS，31 個測試全綠。

- [ ] **步驟 5：commit**

```bash
git add src/training_kb/pipelines/feedback.py tests/unit/test_pipelines_feedback.py
git commit -m "feat(feedback): 從 S3 全文與步驟還原五段內容"
```

---

### Task 6：只改命中步驟與逐字核對

**目的**：把模型回傳的改寫結果套到步驟上，並用程式證明「未命中的步驟一個字都沒動」。

**檔案**：
- 修改：`src/training_kb/pipelines/feedback.py`
- 修改：`tests/unit/test_pipelines_feedback.py`

**介面**：
- 消費：`writing.schemas.StepRewrite`、`writing.schemas.StepRewriteItem`（Phase 16）
- 產出：
  - `pipelines.feedback.apply_step_rewrites(steps: list[TutorialStep], rewrites: StepRewrite, target_indexes: list[int]) -> list[StepDraft]`（本階段新增）
  - `pipelines.feedback.assert_unchanged_steps(original: list[TutorialStep], drafts: list[StepDraft], target_indexes: list[int]) -> None`（本階段新增）

- [ ] **步驟 1：寫測試**

在 `tests/unit/test_pipelines_feedback.py` 最後加入：

```python
from training_kb.writing.schemas import StepRewrite, StepRewriteItem


def four_steps(version_id: str = "prepare-meeting@v1") -> list[TutorialStep]:
    return [
        TutorialStep(tutorial_version=version_id, index=1, type=StepType.click_ui,
                     text="開啟會議頁面。", feature_id="Prepare"),
        TutorialStep(tutorial_version=version_id, index=2, type=StepType.read,
                     text="在左側選單找到會議清單。", feature_id="Prepare"),
        TutorialStep(tutorial_version=version_id, index=3, type=StepType.click_ui,
                     text="點選摘要。", feature_id="Prepare"),
        TutorialStep(tutorial_version=version_id, index=4, type=StepType.read,
                     text="確認摘要內容。", feature_id="Prepare"),
    ]


def test_apply_step_rewrites_only_changes_hit_step():
    steps = four_steps()
    rewrites = StepRewrite(rewrites=[
        StepRewriteItem(index=3, text="在會議頁面右上角點選「Prepare」，就會看到會前摘要。",
                        type=StepType.click_ui, feature_id="Prepare"),
    ])

    drafts = apply_step_rewrites(steps, rewrites, [3])

    assert [d.text for d in drafts] == [
        "開啟會議頁面。",
        "在左側選單找到會議清單。",
        "在會議頁面右上角點選「Prepare」，就會看到會前摘要。",
        "確認摘要內容。",
    ]
    assert [d.type for d in drafts] == [
        StepType.click_ui, StepType.read, StepType.click_ui, StepType.read,
    ]
    assert_unchanged_steps(steps, drafts, [3])


def test_apply_step_rewrites_rejects_index_outside_hit_set():
    steps = four_steps()
    rewrites = StepRewrite(rewrites=[
        StepRewriteItem(index=1, text="改了不該改的步驟。",
                        type=StepType.click_ui, feature_id="Prepare"),
    ])

    with pytest.raises(ContentError):
        apply_step_rewrites(steps, rewrites, [3])


def test_apply_step_rewrites_rejects_duplicate_index():
    steps = four_steps()
    rewrites = StepRewrite(rewrites=[
        StepRewriteItem(index=3, text="第一次", type=StepType.click_ui, feature_id="Prepare"),
        StepRewriteItem(index=3, text="第二次", type=StepType.click_ui, feature_id="Prepare"),
    ])

    with pytest.raises(ContentError):
        apply_step_rewrites(steps, rewrites, [3])


def test_apply_step_rewrites_rejects_missing_index():
    steps = four_steps()
    rewrites = StepRewrite(rewrites=[
        StepRewriteItem(index=3, text="只改了一步", type=StepType.click_ui, feature_id="Prepare"),
    ])

    with pytest.raises(ContentError):
        apply_step_rewrites(steps, rewrites, [2, 3])


def test_assert_unchanged_steps_catches_silent_edit():
    steps = four_steps()
    drafts = [
        StepDraft(type=s.type, text=s.text, feature_id=s.feature_id) for s in steps
    ]
    drafts[0] = StepDraft(type=StepType.click_ui, text="偷偷改掉第一步。", feature_id="Prepare")

    with pytest.raises(ContentError):
        assert_unchanged_steps(steps, drafts, [3])


def test_assert_unchanged_steps_catches_step_count_change():
    steps = four_steps()
    drafts = [StepDraft(type=s.type, text=s.text, feature_id=s.feature_id) for s in steps[:3]]

    with pytest.raises(ContentError):
        assert_unchanged_steps(steps, drafts, [3])
```

把 import 區的 `from training_kb.pipelines.feedback import (...)` 補上 `apply_step_rewrites`、`assert_unchanged_steps`；`from training_kb.models import (...)` 補上 `StepDraft`。

- [ ] **步驟 2：跑測試，確認它失敗**

執行：

```bash
uv run pytest tests/unit/test_pipelines_feedback.py -v
```

預期：FAIL，錯誤訊息是 `ImportError: cannot import name 'apply_step_rewrites'`。

- [ ] **步驟 3：寫最少的程式讓測試通過**

在 `src/training_kb/pipelines/feedback.py` 的 import 區補上：

```python
from training_kb.writing.schemas import StepRewrite, StepRewriteItem
```

並在既有的 `from training_kb.models import (...)` 那一段裡加上 `StepDraft`（依字母順序放在 `PENDING_CATEGORY` 之後、`Feedback` 之前也可以，ruff 不管順序，只管有沒有用到）。

在檔案最後加入：

```python
def apply_step_rewrites(
    steps: list[TutorialStep], rewrites: StepRewrite, target_indexes: list[int]
) -> list[StepDraft]:
    """把改寫結果套到步驟上；未命中的步驟原文複製。

    設計文件 §7.6：編號存在、僅改命中集合，由程式驗證，不相信模型自律。
    """
    targets = set(target_indexes)
    by_index: dict[int, StepRewriteItem] = {}
    for item in rewrites.rewrites:
        if item.index not in targets:
            raise ContentError(f"改寫結果包含未命中的步驟編號 {item.index}")
        if item.index in by_index:
            raise ContentError(f"改寫結果重複指定步驟編號 {item.index}")
        by_index[item.index] = item
    missing = sorted(targets - set(by_index))
    if missing:
        raise ContentError(f"改寫結果缺少步驟編號 {missing}")

    drafts: list[StepDraft] = []
    for step in sorted(steps, key=lambda s: s.index):
        item = by_index.get(step.index)
        if item is None:
            drafts.append(
                StepDraft(type=step.type, text=step.text, feature_id=step.feature_id)
            )
        else:
            drafts.append(
                StepDraft(type=item.type, text=item.text, feature_id=item.feature_id)
            )
    return drafts


def assert_unchanged_steps(
    original: list[TutorialStep], drafts: list[StepDraft], target_indexes: list[int]
) -> None:
    """核對未命中步驟是否逐字相同；不同就拒絕這次改寫。"""
    targets = set(target_indexes)
    ordered = sorted(original, key=lambda s: s.index)
    if len(ordered) != len(drafts):
        raise ContentError(
            f"步驟數量改變：原本 {len(ordered)} 步，改寫後 {len(drafts)} 步"
        )
    for step, draft in zip(ordered, drafts, strict=True):
        if step.index in targets:
            continue
        if (draft.type, draft.text, draft.feature_id) != (
            step.type,
            step.text,
            step.feature_id,
        ):
            raise ContentError(f"第 {step.index} 步未命中卻被改動")
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：

```bash
uv run pytest tests/unit/test_pipelines_feedback.py -v
```

預期：PASS，37 個測試全綠。

- [ ] **步驟 5：commit**

```bash
git add src/training_kb/pipelines/feedback.py tests/unit/test_pipelines_feedback.py
git commit -m "feat(feedback): 只改命中步驟並逐字核對其餘步驟"
```

---

### Task 7：診斷用的 prompt

**目的**：寫出問模型「哪幾步有問題」的題目。回傳格式 `WeakDiagnosis` 由 Phase 05 定義好了，這裡只補 prompt，並用測試確認 schema 的行為符合本階段的需要。

**檔案**：
- 修改：`src/training_kb/writing/prompts.py`
- 測試：`tests/unit/test_writing_diagnose.py`

**介面**：
- 消費：
  - `writing.schemas.WeakDiagnosis`（pydantic model，欄位 `items: list[DiagnosisItem]`，預設空清單）（Phase 05）
  - `writing.schemas.DiagnosisItem`（pydantic model，欄位 `index: int`、`reason: str`）（Phase 05）
  - `models.TutorialStep`、`models.Feedback`（Phase 02）
- 產出：`writing.prompts.prompt_diagnose_weak(steps: list[TutorialStep], feedback: list[Feedback]) -> tuple[str, str]`

> Phase 05 的 schema 都繼承 `StrictModel`（`model_config = ConfigDict(extra="forbid")`），意思是「模型多輸出一個沒定義的欄位就算失敗」。所以下面的測試除了 prompt 之外，也順便釘住 schema 對本階段重要的三個行為：空清單合法、index 必須是整數、reason 必填。

- [ ] **步驟 1：寫測試**

建立 `tests/unit/test_writing_diagnose.py`：

```python
"""Phase 17：弱教學診斷的 prompt，以及 Phase 05 schema 的行為確認。"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from training_kb.models import Feedback, StepType, TutorialStep
from training_kb.writing.prompts import prompt_diagnose_weak
from training_kb.writing.schemas import DiagnosisItem, WeakDiagnosis


def sample_steps() -> list[TutorialStep]:
    return [
        TutorialStep(tutorial_version="prepare-meeting@v1", index=1, type=StepType.click_ui,
                     text="開啟會議頁面。", feature_id="Prepare"),
        TutorialStep(tutorial_version="prepare-meeting@v1", index=3, type=StepType.click_ui,
                     text="點選摘要。", feature_id="Prepare"),
    ]


def sample_feedback() -> list[Feedback]:
    return [
        Feedback(id="f_12", tutorial_version="prepare-meeting@v1", rating=2, user="u_01",
                 category="找不到按鈕", comment="第三步沒有指出按鈕在哪一頁與位置",
                 ts="2026-08-02T09:00:00Z"),
    ]


def test_weak_diagnosis_accepts_index_and_reason():
    parsed = WeakDiagnosis.model_validate({"items": [{"index": 3, "reason": "沒寫按鈕位置"}]})
    assert parsed.items[0].index == 3
    assert parsed.items[0].reason == "沒寫按鈕位置"


def test_weak_diagnosis_accepts_empty_items():
    # F24：模型可以回答「找不到有效步驟」，這是合法輸出。
    assert WeakDiagnosis.model_validate({"items": []}).items == []


def test_weak_diagnosis_rejects_non_integer_index():
    with pytest.raises(ValidationError):
        WeakDiagnosis.model_validate({"items": [{"index": "third", "reason": "x"}]})


def test_diagnosis_item_requires_reason():
    with pytest.raises(ValidationError):
        DiagnosisItem.model_validate({"index": 3})


def test_prompt_diagnose_weak_lists_steps_and_feedback():
    system, user = prompt_diagnose_weak(sample_steps(), sample_feedback())

    assert "只能回傳現有步驟的編號" in system
    assert "空清單" in system
    assert "1. [click_ui] 開啟會議頁面。" in user
    assert "3. [click_ui] 點選摘要。" in user
    assert "第三步沒有指出按鈕在哪一頁與位置" in user


def test_prompt_diagnose_weak_handles_empty_comment():
    feedback = [
        Feedback(id="f_40", tutorial_version="prepare-meeting@v1", rating=4, user="u_08",
                 category="找不到按鈕", comment=None, ts="2026-08-02T09:00:00Z"),
    ]
    _, user = prompt_diagnose_weak(sample_steps(), feedback)
    assert "（無留言）" in user
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：

```bash
uv run pytest tests/unit/test_writing_diagnose.py -v
```

預期：FAIL，錯誤訊息是 `ImportError: cannot import name 'prompt_diagnose_weak' from 'training_kb.writing.prompts'`。四個 schema 測試會因為同一個 import 錯誤一起失敗，這是正常的；等 prompt 寫好之後它們會直接通過，因為 schema 在 Phase 05 就做好了。

- [ ] **步驟 3：寫最少的程式讓測試通過**

在 `src/training_kb/writing/prompts.py` 最後加入：

```python
def prompt_diagnose_weak(
    steps: list[TutorialStep], feedback: list[Feedback]
) -> tuple[str, str]:
    """問模型：這一版的負面回饋是哪幾個步驟造成的。

    回傳 (system, user) 兩段文字。程式之後還會驗證編號是否存在，
    所以 prompt 只要求模型不要發明編號，不代表可以省略程式驗證。
    """
    system = (
        "你是技術教學編輯。使用者對某一版教學留下負面回饋，"
        "請判斷是哪幾個步驟造成問題。\n"
        "規則：\n"
        "1. 只能回傳現有步驟的編號，不可以發明新的編號。\n"
        "2. 找不到明確對應的步驟時回傳空清單，不要硬指一個步驟。\n"
        "3. 這一步只做診斷，不要改寫步驟文字。\n"
        '4. 只輸出 JSON，格式為 {"items": [{"index": 3, "reason": "原因"}]}。'
    )
    step_lines = "\n".join(
        f"{step.index}. [{step.type}] {step.text}"
        for step in sorted(steps, key=lambda s: s.index)
    )
    feedback_lines = "\n".join(
        f"- 評分 {item.rating}／類別 {item.category or '無'}／留言：{item.comment or '（無留言）'}"
        for item in feedback
    )
    user = (
        f"目前步驟：\n{step_lines}\n\n"
        f"使用者回饋：\n{feedback_lines}\n\n"
        "請輸出 JSON。"
    )
    return system, user
```

（若 `prompts.py` 檔案開頭還沒有 `from training_kb.models import Feedback, TutorialStep`，補上這一行；已有部分名稱時只補缺的。）

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：

```bash
uv run pytest tests/unit/test_writing_diagnose.py -v
```

預期：PASS，6 個測試全綠。

- [ ] **步驟 5：commit**

```bash
git add src/training_kb/writing/prompts.py tests/unit/test_writing_diagnose.py
git commit -m "feat(writing): 加入弱教學診斷的 prompt"
```

---

### Task 8：diagnose task

**目的**：把「是不是弱教學」「這批證據處理過沒」「模型說哪幾步有問題」串起來，並處理「無可改步驟」與「無新證據」兩條不建版本的路。

**檔案**：
- 修改：`src/training_kb/pipelines/feedback.py`
- 修改：`tests/unit/test_pipelines_feedback.py`

**介面**：
- 消費：`writing.client.Writer.generate_json`（Phase 05）、`repository.Repository.begin_operation` / `load_operation` / `update_operation`（Phase 03）、`clock.to_iso`（Phase 01）
- 產出：`pipelines.feedback.task_diagnose(state: dict, deps: Deps) -> dict`

- [ ] **步驟 1：寫測試**

在 `tests/unit/test_pipelines_feedback.py` 最後加入：

```python
from training_kb.writing.schemas import DiagnosisItem, WeakDiagnosis


def weak_state(repo: FakeRepo, *, policy: str = "demo") -> dict:
    """準備一份已經跑過 collect、而且符合 Demo 弱教學門檻的 state。"""
    add_tutorial(repo, "prepare-meeting", current_version="prepare-meeting@v1")
    add_version_with_steps(repo, "prepare-meeting", "prepare-meeting@v1")
    add_feedback(repo, "prepare-meeting@v1", A_V1_ROWS)
    return task_collect(
        {
            "run_id": "2026-09-14",
            "policy": policy,
            "slug": "prepare-meeting",
            "version_id": "prepare-meeting@v1",
        },
        make_deps(repo),
    )


def test_diagnose_marks_refine_for_weak_version():
    repo = FakeRepo()
    state = weak_state(repo)
    writer = FakeWriter(outputs=[WeakDiagnosis(items=[DiagnosisItem(index=3, reason="沒寫按鈕位置")])])

    out = task_diagnose(state, make_deps(repo, writer))

    assert out["weak"] is True
    assert out["action"] == "REFINE"
    assert out["target_indexes"] == [3]
    assert out["diagnosis"] == [{"index": 3, "reason": "沒寫按鈕位置"}]
    assert out["review_operation_id"] == review_operation_id("prepare-meeting", state["evidence_key"])
    assert repo.operations[out["review_operation_id"]]["status"] == "started"


def test_diagnose_skips_when_formal_threshold_not_reached():
    repo = FakeRepo()
    state = weak_state(repo, policy="formal")  # 只有 8 筆，正式門檻要 10 筆

    out = task_diagnose(state, make_deps(repo))

    assert out["action"] == "SKIP"
    assert out["weak"] is False
    assert out["target_indexes"] == []
    assert repo.operations == {}  # 沒達門檻就不寫操作紀錄


def test_diagnose_skips_when_same_evidence_already_processed():
    # F23：沒有新的有效證據時，同一批回饋不可再次觸發 REFINE。
    repo = FakeRepo()
    state = weak_state(repo)
    op_id = review_operation_id("prepare-meeting", state["evidence_key"])
    repo.operations[op_id] = {"status": "refined", "new_version_id": "prepare-meeting@v2"}

    out = task_diagnose(state, make_deps(repo))

    assert out["action"] == "SKIP"
    assert out["skip_reason"] == "本批證據已處理，沒有新的有效回饋"
    assert out["target_indexes"] == []


def test_diagnose_continues_when_previous_run_stopped_halfway():
    repo = FakeRepo()
    state = weak_state(repo)
    op_id = review_operation_id("prepare-meeting", state["evidence_key"])
    repo.operations[op_id] = {"status": "started"}
    writer = FakeWriter(outputs=[WeakDiagnosis(items=[DiagnosisItem(index=3, reason="沒寫按鈕位置")])])

    out = task_diagnose(state, make_deps(repo, writer))

    assert out["action"] == "REFINE"


def test_diagnose_records_no_step_when_model_returns_empty():
    # F24：診斷找不到有效步驟時記錄「無可改步驟」，本次不建版本。
    repo = FakeRepo()
    state = weak_state(repo)
    writer = FakeWriter(outputs=[WeakDiagnosis(items=[])])

    out = task_diagnose(state, make_deps(repo, writer))

    assert out["action"] == "NO_STEP"
    assert out["skip_reason"] == "無可改步驟"
    assert out["target_indexes"] == []
    op_id = out["review_operation_id"]
    assert repo.operations[op_id]["status"] == "no_step"
    assert repo.operations[op_id]["note"] == "無可改步驟"


def test_diagnose_drops_index_that_does_not_exist():
    repo = FakeRepo()
    state = weak_state(repo)
    writer = FakeWriter(outputs=[WeakDiagnosis(items=[
        DiagnosisItem(index=3, reason="沒寫按鈕位置"),
        DiagnosisItem(index=99, reason="不存在的步驟"),
    ])])

    out = task_diagnose(state, make_deps(repo, writer))

    assert out["target_indexes"] == [3]
    assert [hit["index"] for hit in out["diagnosis"]] == [3]
```

把 import 區的 `from training_kb.pipelines.feedback import (...)` 補上 `task_diagnose`。

- [ ] **步驟 2：跑測試，確認它失敗**

執行：

```bash
uv run pytest tests/unit/test_pipelines_feedback.py -v
```

預期：FAIL，錯誤訊息是 `ImportError: cannot import name 'task_diagnose'`。

- [ ] **步驟 3：寫最少的程式讓測試通過**

在 `src/training_kb/pipelines/feedback.py` 的 import 區補上：

```python
from training_kb.clock import to_iso
from training_kb.writing.prompts import prompt_diagnose_weak
from training_kb.writing.schemas import StepRewrite, StepRewriteItem, WeakDiagnosis
```

（把原本的 `from training_kb.writing.schemas import StepRewrite, StepRewriteItem` 整行換掉。）

在檔案最後加入：

```python
def _category_evidence(state: dict, deps: Deps) -> list[Feedback]:
    """取出命中類別的有效回饋，當作診斷與改寫的證據。"""
    return [
        item
        for item in deps.repo.list_feedback_of_version(state["version_id"])
        if is_valid_feedback(item) and item.category == state["top_category"]
    ]


def task_diagnose(state: dict, deps: Deps) -> dict:
    """判斷是不是弱教學，是的話請模型指出要改哪幾步。

    三條不建版本的路：未達門檻、本批證據已處理過（F23）、模型找不到有效步驟（F24）。
    """
    policy = ReviewPolicy.for_name(state["policy"], deps.settings.thresholds)
    weak = is_weak(
        state.get("avg"),
        state.get("n", 0),
        state.get("top_category_count", 0),
        policy,
        deps.settings.thresholds,
    )
    if not weak:
        return {
            **state,
            "weak": False,
            "action": "SKIP",
            "skip_reason": "未達弱教學門檻",
            "target_indexes": [],
        }

    operation_id = review_operation_id(state["slug"], state["evidence_key"])
    record = deps.repo.load_operation(operation_id)
    if record is not None and record.get("status") in REVIEW_DONE_STATUSES:
        return {
            **state,
            "weak": True,
            "action": "SKIP",
            "skip_reason": "本批證據已處理，沒有新的有效回饋",
            "target_indexes": [],
            "review_operation_id": operation_id,
        }
    if record is None:
        deps.repo.begin_operation(
            operation_id,
            {
                "kind": "review",
                "slug": state["slug"],
                "version_id": state["version_id"],
                "run_id": state.get("run_id"),
                "policy": state["policy"],
                "evidence_key": state["evidence_key"],
                "feedback_ids": state["feedback_ids"],
                "category": state["top_category"],
                "category_count": state["top_category_count"],
                "status": "started",
                "started_at": to_iso(deps.now()),
            },
        )

    steps = deps.repo.get_steps(state["version_id"])
    system, user = prompt_diagnose_weak(steps, _category_evidence(state, deps))
    diagnosis = deps.writer.generate_json(
        system=system,
        user=user,
        schema=WeakDiagnosis,
        operation_id=operation_id,
        node="diagnose",
        max_tokens=deps.settings.gen_max_tokens_judgement,
        temperature=deps.settings.gen_temperature,
    )

    existing = {step.index for step in steps}
    hits = sorted({item.index for item in diagnosis.items if item.index in existing})
    reasons = [
        {"index": item.index, "reason": item.reason}
        for item in diagnosis.items
        if item.index in existing
    ]
    if not hits:
        deps.repo.update_operation(
            operation_id,
            {
                "status": "no_step",
                "note": "無可改步驟",
                "decided_at": to_iso(deps.now()),
            },
        )
        return {
            **state,
            "weak": True,
            "action": "NO_STEP",
            "skip_reason": "無可改步驟",
            "target_indexes": [],
            "review_operation_id": operation_id,
        }
    return {
        **state,
        "weak": True,
        "action": "REFINE",
        "target_indexes": hits,
        "diagnosis": reasons,
        "review_operation_id": operation_id,
    }
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：

```bash
uv run pytest tests/unit/test_pipelines_feedback.py -v
```

預期：PASS，43 個測試全綠。

- [ ] **步驟 5：commit**

```bash
git add src/training_kb/pipelines/feedback.py tests/unit/test_pipelines_feedback.py
git commit -m "feat(feedback): 加入 diagnose 與不重做、無可改步驟兩條分支"
```

---

### Task 9：refine task

**目的**：取鎖、分配版號、注入 active 規則、只改命中步驟、核對、建立未發布版本。

**檔案**：
- 修改：`src/training_kb/pipelines/feedback.py`
- 修改：`tests/unit/test_pipelines_feedback.py`

**介面**：
- 消費：`content.with_tutorial_lock`、`content.allocate_version`、`content.create_version`、`content.validate_content`（Phase 07、08）、`writing.rules.rules_for_content`（Phase 06）、`writing.prompts.prompt_rewrite_steps`（Phase 16）
- 產出：`pipelines.feedback.task_refine(state: dict, deps: Deps) -> dict`

> 測試會把 `content` 的三個函式暫時換成假的（pytest 的 `monkeypatch`），這樣單元測試可以只檢查「呼叫順序對不對、有沒有只改命中步驟」，不必真的寫 DynamoDB 與 S3。真正的寫入路徑由 Phase 24（`24-Phase24-失敗復原與重送驗收.md`）用注入失敗驗證。

- [ ] **步驟 1：寫測試**

在 `tests/unit/test_pipelines_feedback.py` 最後加入：

```python
from training_kb.models import AuthoringRule, RuleStatus
from training_kb.writing.schemas import StepRewrite, StepRewriteItem


class RefineSpy:
    """記下 refine 過程實際呼叫了什麼，讓測試可以檢查。"""

    def __init__(self) -> None:
        self.lock_owner: str | None = None
        self.plan_args: dict | None = None
        self.created_content = None
        self.validated = False


def patch_content(monkeypatch, spy: RefineSpy):
    from types import SimpleNamespace

    import training_kb.pipelines.feedback as mod

    def fake_lock(repo, slug, owner, now, fn):
        spy.lock_owner = owner
        return fn()

    def fake_allocate(repo, slug, operation_id, reason, rules_applied):
        spy.plan_args = {
            "slug": slug,
            "operation_id": operation_id,
            "reason": reason,
            "rules_applied": list(rules_applied),
        }
        return SimpleNamespace(
            slug=slug,
            version_id=f"{slug}@v2",
            n=2,
            supersedes=f"{slug}@v1",
            reason=reason,
            rules_applied=list(rules_applied),
            operation_id=operation_id,
        )

    def fake_validate(content, known_feature_ids):
        spy.validated = True

    def fake_create(repo, plan, content, *, now):
        spy.created_content = content
        return TutorialVersion(
            version_id=plan.version_id,
            supersedes=plan.supersedes,
            reason=plan.reason,
            rules_applied=plan.rules_applied,
            s3_key=f"tutorials/{plan.slug}/v{plan.n}.md",
            published_at=None,
        )

    monkeypatch.setattr(mod, "with_tutorial_lock", fake_lock)
    monkeypatch.setattr(mod, "allocate_version", fake_allocate)
    monkeypatch.setattr(mod, "validate_content", fake_validate)
    monkeypatch.setattr(mod, "create_version", fake_create)


def refine_ready_state(repo: FakeRepo) -> dict:
    state = weak_state(repo)
    writer = FakeWriter(outputs=[WeakDiagnosis(items=[DiagnosisItem(index=3, reason="沒寫按鈕位置")])])
    return task_diagnose(state, make_deps(repo, writer))


NEW_STEP_TEXT = "在會議頁面右上角點選「Prepare」，畫面會顯示會前摘要。"


def test_refine_builds_unpublished_next_version(monkeypatch):
    repo = FakeRepo()
    repo.rules = [
        AuthoringRule(
            rule_id="R-007",
            rule="步驟要求點擊 UI 元件時，必須寫出：在哪個頁面、按鈕位置、點完會看到什麼",
            applies_when={"step.type": "click_ui"},
            evidence=["f_12", "f_15", "f_19", "f_23", "f_27"],
            status=RuleStatus.active,
            derived_from="prepare-meeting@v1",
            validated_at="2026-09-01T00:00:00Z",
        )
    ]
    state = refine_ready_state(repo)
    spy = RefineSpy()
    patch_content(monkeypatch, spy)
    writer = FakeWriter(outputs=[StepRewrite(rewrites=[
        StepRewriteItem(index=3, text=NEW_STEP_TEXT, type=StepType.click_ui, feature_id="Prepare"),
    ])])

    out = task_refine(state, make_deps(repo, writer))

    assert out["new_version_id"] == "prepare-meeting@v2"
    assert out["reason"] == "feedback:8 則 找不到按鈕"
    assert spy.plan_args["reason"] == "feedback:8 則 找不到按鈕"
    assert spy.plan_args["operation_id"] == state["review_operation_id"]
    assert spy.lock_owner == state["review_operation_id"]
    assert spy.validated is True


def test_refine_only_rewrites_hit_step(monkeypatch):
    repo = FakeRepo()
    state = refine_ready_state(repo)
    spy = RefineSpy()
    patch_content(monkeypatch, spy)
    writer = FakeWriter(outputs=[StepRewrite(rewrites=[
        StepRewriteItem(index=3, text=NEW_STEP_TEXT, type=StepType.click_ui, feature_id="Prepare"),
    ])])

    task_refine(state, make_deps(repo, writer))

    texts = [step.text for step in spy.created_content.steps]
    assert texts == [
        "開啟會議頁面。",
        "在左側選單找到會議清單。",
        NEW_STEP_TEXT,
        "確認摘要內容。",
    ]
    assert spy.created_content.title == "準備會議"
    assert spy.created_content.prerequisites == ["已登入產品", "已建立至少一場會議"]


def test_refine_rejects_rewrite_of_unhit_step(monkeypatch):
    repo = FakeRepo()
    state = refine_ready_state(repo)
    spy = RefineSpy()
    patch_content(monkeypatch, spy)
    writer = FakeWriter(outputs=[StepRewrite(rewrites=[
        StepRewriteItem(index=1, text="整篇重寫", type=StepType.click_ui, feature_id="Prepare"),
    ])])

    with pytest.raises(ContentError):
        task_refine(state, make_deps(repo, writer))
    assert spy.created_content is None


def test_refine_does_nothing_when_action_is_not_refine(monkeypatch):
    repo = FakeRepo()
    spy = RefineSpy()
    patch_content(monkeypatch, spy)

    out = task_refine({"action": "NO_STEP", "slug": "prepare-meeting"}, make_deps(repo))

    assert "new_version_id" not in out
    assert spy.plan_args is None


def test_refine_writes_refined_status_to_operation_record(monkeypatch):
    repo = FakeRepo()
    state = refine_ready_state(repo)
    patch_content(monkeypatch, RefineSpy())
    writer = FakeWriter(outputs=[StepRewrite(rewrites=[
        StepRewriteItem(index=3, text=NEW_STEP_TEXT, type=StepType.click_ui, feature_id="Prepare"),
    ])])

    task_refine(state, make_deps(repo, writer))

    record = repo.operations[state["review_operation_id"]]
    assert record["status"] == "refined"
    assert record["new_version_id"] == "prepare-meeting@v2"
```

把 import 區的 `from training_kb.pipelines.feedback import (...)` 補上 `task_refine`。

- [ ] **步驟 2：跑測試，確認它失敗**

執行：

```bash
uv run pytest tests/unit/test_pipelines_feedback.py -v
```

預期：FAIL，錯誤訊息是 `ImportError: cannot import name 'task_refine'`。

- [ ] **步驟 3：寫最少的程式讓測試通過**

在 `src/training_kb/pipelines/feedback.py` 的 import 區補上：

```python
from training_kb.content import (
    allocate_version,
    create_version,
    parse_markdown,
    validate_content,
    with_tutorial_lock,
)
from training_kb.models import RuleStatus
from training_kb.writing.prompts import prompt_diagnose_weak, prompt_rewrite_steps
from training_kb.writing.rules import rules_for_content
```

（把 Task 5 加的 `from training_kb.content import parse_markdown` 與 Task 8 加的 `from training_kb.writing.prompts import prompt_diagnose_weak` 兩行換成上面這三段。另外在既有的 `from training_kb.models import (...)` 那一段裡加上 `TutorialContent`；`RuleStatus` 可以留在上面那一行，也可以併進同一段。）

在檔案最後加入：

```python
def _evidence_text(state: dict, deps: Deps) -> str:
    """把命中類別的回饋與診斷原因整理成一段給改寫 prompt 的證據文字。"""
    lines = [f"共 {state['top_category_count']} 則「{state['top_category']}」回饋："]
    for item in _category_evidence(state, deps):
        lines.append(f"- 評分 {item.rating}：{item.comment or '（無留言）'}")
    for hit in state.get("diagnosis", []):
        lines.append(f"- 第 {hit['index']} 步的診斷原因：{hit['reason']}")
    return "\n".join(lines)


def task_refine(state: dict, deps: Deps) -> dict:
    """只重寫診斷命中的步驟，產生一個 published_at 還是空的新版本。

    順序：取鎖 -> 分配版號 -> 取 active 規則 -> 改寫 -> 核對 -> 建立版本。
    """
    if state.get("action") != "REFINE":
        return state

    slug = state["slug"]
    version_id = state["version_id"]
    operation_id = state["review_operation_id"]
    target_indexes = list(state["target_indexes"])
    reason = refine_reason(state["top_category_count"], state["top_category"])

    def _build() -> TutorialVersion:
        version = deps.repo.get_version(version_id)
        if version is None:
            raise PermanentError(f"目前版本不存在：{version_id}")
        steps = deps.repo.get_steps(version_id)
        previous = load_version_content(deps.repo, version, steps)

        hit = set(target_indexes)
        step_types = [step.type for step in steps if step.index in hit]
        rules_block, rule_ids = rules_for_content(
            deps.repo.list_rules(RuleStatus.active), step_types
        )
        plan = allocate_version(deps.repo, slug, operation_id, reason, rule_ids)

        system, user = prompt_rewrite_steps(
            steps, target_indexes, _evidence_text(state, deps), rules_block
        )
        rewrites = deps.writer.generate_json(
            system=system,
            user=user,
            schema=StepRewrite,
            operation_id=operation_id,
            node="refine",
            max_tokens=deps.settings.gen_max_tokens_writing,
            temperature=deps.settings.gen_temperature,
        )
        drafts = apply_step_rewrites(steps, rewrites, target_indexes)
        assert_unchanged_steps(steps, drafts, target_indexes)

        content = TutorialContent(
            title=previous.title,
            problem=previous.problem,
            prerequisites=previous.prerequisites,
            steps=drafts,
            expected_outcome=previous.expected_outcome,
        )
        known_feature_ids = {feature.feature_id for feature in deps.repo.list_features()}
        validate_content(content, known_feature_ids)
        return create_version(deps.repo, plan, content, now=deps.now())

    version = with_tutorial_lock(deps.repo, slug, operation_id, deps.now(), _build)
    deps.repo.update_operation(
        operation_id,
        {
            "status": "refined",
            "new_version_id": version.version_id,
            "reason": reason,
            "refined_at": to_iso(deps.now()),
        },
    )
    return {
        **state,
        "new_version_id": version.version_id,
        "reason": reason,
        "rules_applied": list(version.rules_applied),
    }
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：

```bash
uv run pytest tests/unit/test_pipelines_feedback.py -v
```

預期：PASS，48 個測試全綠。

- [ ] **步驟 5：commit**

```bash
git add src/training_kb/pipelines/feedback.py tests/unit/test_pipelines_feedback.py
git commit -m "feat(feedback): 加入 REFINE，只改命中步驟並建立未發布版本"
```

---

### Task 10：publish task 與 TASKS 註冊

**目的**：把這一輪所有新版本一次送出，任一篇失敗整次不發布；同時把 task 名稱登記到 `TASKS`，並用 `TASK_ORDER` 記錄設計文件 §7.5 規定的順序。

**檔案**：
- 修改：`src/training_kb/pipelines/feedback.py`
- 修改：`tests/unit/test_pipelines_feedback.py`

**介面**：
- 消費：`content.publish`（Phase 08）、`site.SiteRenderer`（Phase 08）、`pipelines.common.TaskFn`（Phase 13）
- 產出：
  - `pipelines.feedback.task_publish(state: dict, deps: Deps) -> dict`
  - `pipelines.feedback.TASK_ORDER: tuple[str, ...]`（本階段新增）
  - `pipelines.feedback.TASKS: dict[str, TaskFn]`

- [ ] **步驟 1：寫測試**

在 `tests/unit/test_pipelines_feedback.py` 最後加入：

```python
class PublishResultStub:
    def __init__(self, published: list[str], failed: str | None = None) -> None:
        self.published = published
        self.failed = failed


def patch_publish(monkeypatch, result: PublishResultStub, calls: list):
    import training_kb.pipelines.feedback as mod

    def fake_publish(repo, version_ids, renderer, *, now):
        calls.append(list(version_ids))
        return result

    monkeypatch.setattr(mod, "publish", fake_publish)


def test_publish_sends_every_new_version_once(monkeypatch):
    repo = FakeRepo()
    repo.operations["review:a:k1"] = {"status": "refined"}
    repo.operations["review:b:k2"] = {"status": "refined"}
    calls: list = []
    patch_publish(monkeypatch, PublishResultStub(["a@v2", "b@v3"]), calls)

    out = task_publish(
        {
            "run_id": "2026-09-14",
            "items": [
                {"slug": "a", "new_version_id": "a@v2", "review_operation_id": "review:a:k1"},
                {"slug": "b", "new_version_id": "b@v3", "review_operation_id": "review:b:k2"},
                {"slug": "c", "action": "SKIP"},
            ],
        },
        make_deps(repo),
    )

    assert calls == [["a@v2", "b@v3"]]
    assert out["published"] == ["a@v2", "b@v3"]
    assert out["published_count"] == 2
    assert repo.operations["review:a:k1"]["status"] == "published"


def test_publish_raises_when_any_version_fails(monkeypatch):
    # F49：整次執行以失敗結束，不發布新版本。
    repo = FakeRepo()
    repo.operations["review:a:k1"] = {"status": "refined"}
    calls: list = []
    patch_publish(monkeypatch, PublishResultStub([], failed="b@v3"), calls)

    with pytest.raises(PermanentError):
        task_publish(
            {
                "items": [
                    {"slug": "a", "new_version_id": "a@v2", "review_operation_id": "review:a:k1"},
                    {"slug": "b", "new_version_id": "b@v3", "review_operation_id": "review:b:k2"},
                ]
            },
            make_deps(repo),
        )
    assert repo.operations["review:a:k1"]["status"] == "refined"  # 沒有被改成 published


def test_publish_does_nothing_when_no_new_version(monkeypatch):
    repo = FakeRepo()
    calls: list = []
    patch_publish(monkeypatch, PublishResultStub([]), calls)

    out = task_publish({"items": [{"slug": "a", "action": "SKIP"}]}, make_deps(repo))

    assert calls == []
    assert out["published"] == []
    assert out["published_count"] == 0


def test_task_order_follows_design_section_7_5():
    # 設計文件 §7.5：候選規則證據檢查先完成，再準備 REFINE，publish 放最後。
    assert TASK_ORDER == (
        "list_targets", "collect", "propose_rules", "diagnose", "refine", "publish",
    )
    assert TASK_ORDER.index("propose_rules") < TASK_ORDER.index("diagnose")
    assert TASK_ORDER[-1] == "publish"


def test_tasks_registry_has_phase17_tasks():
    assert set(TASKS) == {"list_targets", "collect", "diagnose", "refine", "publish"}
    assert set(TASKS).issubset(set(TASK_ORDER))


def test_end_to_end_demo_policy_produces_one_unpublished_version(monkeypatch):
    repo = FakeRepo()
    spy = RefineSpy()
    patch_content(monkeypatch, spy)
    calls: list = []
    patch_publish(monkeypatch, PublishResultStub(["prepare-meeting@v2"]), calls)

    add_tutorial(repo, "prepare-meeting", current_version="prepare-meeting@v1")
    add_version_with_steps(repo, "prepare-meeting", "prepare-meeting@v1")
    add_feedback(repo, "prepare-meeting@v1", A_V1_ROWS)

    writer = FakeWriter(outputs=[
        WeakDiagnosis(items=[DiagnosisItem(index=3, reason="沒寫按鈕位置")]),
        StepRewrite(rewrites=[
            StepRewriteItem(index=3, text=NEW_STEP_TEXT, type=StepType.click_ui, feature_id="Prepare"),
        ]),
    ])
    deps = make_deps(repo, writer)

    run = TASKS["list_targets"]({"run_id": "2026-09-14", "policy": "demo"}, deps)
    items = []
    for target in run["targets"]:
        item = {"run_id": run["run_id"], "policy": run["policy"], **target}
        item = TASKS["collect"](item, deps)
        item = TASKS["diagnose"](item, deps)
        item = TASKS["refine"](item, deps)
        items.append(item)
    out = TASKS["publish"]({**run, "items": items}, deps)

    assert items[0]["reason"] == "feedback:8 則 找不到按鈕"
    assert out["published"] == ["prepare-meeting@v2"]
    assert calls == [["prepare-meeting@v2"]]
```

把 import 區的 `from training_kb.pipelines.feedback import (...)` 補上 `TASKS`、`TASK_ORDER`、`task_publish`。

- [ ] **步驟 2：跑測試，確認它失敗**

執行：

```bash
uv run pytest tests/unit/test_pipelines_feedback.py -v
```

預期：FAIL，錯誤訊息是 `ImportError: cannot import name 'TASKS'`。

- [ ] **步驟 3：寫最少的程式讓測試通過**

在 `src/training_kb/pipelines/feedback.py` 的 import 區補上：

```python
from training_kb.content import (
    allocate_version,
    create_version,
    parse_markdown,
    publish,
    validate_content,
    with_tutorial_lock,
)
from training_kb.pipelines.common import Deps, TaskFn
from training_kb.site import SiteRenderer
```

（把原本的 content import 與 `from training_kb.pipelines.common import Deps` 兩段換掉。）

在檔案最後加入：

```python
def task_publish(state: dict, deps: Deps) -> dict:
    """把這一輪所有新版本一次送出。

    F49：任一篇失敗，整次執行以失敗結束，不發布新版本。
    已保存的 candidate 規則不受影響，也不會因此變成 active。
    """
    items = state.get("items") or []
    pending = [item for item in items if item.get("new_version_id")]
    if not pending:
        return {**state, "published": [], "published_count": 0}

    version_ids = [item["new_version_id"] for item in pending]
    result = publish(deps.repo, version_ids, SiteRenderer(), now=deps.now())
    if result.failed:
        raise PermanentError(
            f"整批發布失敗，未切換任何 current_version；第一個失敗版本：{result.failed}"
        )
    for item in pending:
        operation_id = item.get("review_operation_id")
        if operation_id:
            deps.repo.update_operation(
                operation_id,
                {"status": "published", "published_at": to_iso(deps.now())},
            )
    return {
        **state,
        "published": list(result.published),
        "published_count": len(result.published),
    }


#: 設計文件 §7.5 規定的節點順序：候選規則證據檢查先完成，再準備 REFINE，publish 放最後。
#: propose_rules 由 Phase 18 實作並登記到 TASKS。
TASK_ORDER: tuple[str, ...] = (
    "list_targets",
    "collect",
    "propose_rules",
    "diagnose",
    "refine",
    "publish",
)

TASKS: dict[str, TaskFn] = {
    "list_targets": task_list_targets,
    "collect": task_collect,
    "diagnose": task_diagnose,
    "refine": task_refine,
    "publish": task_publish,
}
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：

```bash
uv run pytest tests/unit/test_pipelines_feedback.py tests/unit/test_writing_diagnose.py -v
uv run ruff check src/training_kb/pipelines/feedback.py tests/unit/test_pipelines_feedback.py
```

預期：pytest 顯示 54 個測試全綠；ruff 顯示 `All checks passed!`。

- [ ] **步驟 5：commit**

```bash
git add src/training_kb/pipelines/feedback.py tests/unit/test_pipelines_feedback.py
git commit -m "feat(feedback): 加入整批 publish 與 TASKS 註冊"
```

---

## 7. 完成檢查清單

對應設計文件第 16 節切片 S6 的檢查項目「Demo 八筆走隔離門檻；REFINE 只改有效步驟」。逐項自己跑一次：

- [ ] `uv run pytest tests/unit -q` 全部通過，沒有跳過的測試。
- [ ] `uv run ruff check .` 沒有錯誤。
- [ ] 執行下面這段，確認正式與展示門檻的差別只在筆數：

```bash
uv run python - <<'PY'
from training_kb.config import Thresholds
from training_kb.pipelines.feedback import ReviewPolicy, is_weak
th = Thresholds()
print("demo  n=8 ->", is_weak(2.875, 8, 8, ReviewPolicy.demo(), th))     # True
print("formal n=8 ->", is_weak(2.875, 8, 8, ReviewPolicy.formal(), th))  # False
print("formal n=10 ->", is_weak(2.875, 10, 8, ReviewPolicy.formal(), th))# True
print("avg 3.5 ->", is_weak(3.5, 10, 8, ReviewPolicy.formal(), th))      # False
print("cat 4 ->", is_weak(2.875, 10, 4, ReviewPolicy.formal(), th))      # False
PY
```

預期輸出依序是 `True`、`False`、`True`、`False`、`False`。

- [ ] 執行下面這段，確認 REFINE 的 reason 格式與設計文件 §8.1 的版本鏈圖一致：

```bash
uv run python -c "from training_kb.pipelines.feedback import refine_reason; print(refine_reason(8, '找不到按鈕'))"
```

預期輸出：`feedback:8 則 找不到按鈕`。

- [ ] 執行下面這段，確認同一批證據的指紋穩定、多一筆就改變：

```bash
uv run python - <<'PY'
from training_kb.pipelines.feedback import evidence_key, review_operation_id
ids = ["f_12", "f_15", "f_19", "f_23", "f_27", "f_31", "f_34", "f_40"]
k1 = evidence_key(ids)
k2 = evidence_key(list(reversed(ids)))
k3 = evidence_key(ids + ["f_44"])
print(k1 == k2, k1 != k3)
print(review_operation_id("prepare-meeting", k1))
PY
```

預期輸出第一行是 `True True`，第二行是 `review:prepare-meeting:<16 個十六進位字元>`。

- [ ] 打開 `src/training_kb/pipelines/feedback.py`，確認 `TASK_ORDER` 裡 `propose_rules` 排在 `diagnose` 之前、`publish` 在最後。
- [ ] 確認 `task_refine` 產生的版本 `published_at` 是空的（測試 `test_refine_builds_unpublished_next_version` 已檢查 `create_version` 的回傳；真實寫入由 Phase 24 驗收）。
- [ ] 確認 `task_publish` 在 `result.failed` 有值時拋出例外，而且沒有把任何操作紀錄改成 `published`。

---

## 8. 常見錯誤與排除

**錯誤 1：`ImportError: cannot import name 'StepRewrite' from 'training_kb.writing.schemas'` 或 `cannot import name 'parse_markdown' from 'training_kb.content'`**

- 症狀：跑 Task 5 或 Task 6 的測試時，import 就失敗。
- 原因：`StepRewrite`、`StepRewriteItem`、`WeakDiagnosis`、`DiagnosisItem` 由 Phase 05（`05-Phase05-Writing-Bedrock呼叫與輸出驗證.md`）建立；`prompt_rewrite_steps` 與 `content.parse_markdown` 由 Phase 16（`16-Phase16-Release-Note-Update流程.md`）建立。本階段只沿用，不重寫一份。
- 解法：回頭做完對應階段的 Task 再回來。確認方式是本文件第 3 節的檢查 3 與檢查 3b。

**錯誤 2：`test_collect_computes_unrounded_average_and_counts` 失敗，`avg` 變成 2.9**

- 症狀：斷言 `out["avg"] == 23 / 8` 不成立，實際值是 `2.9`。
- 原因：在 `task_collect` 裡就先做了四捨五入。設計文件 §11.2 明講「指標判斷使用未四捨五入的數值；顯示位數不影響門檻」。
- 解法：`task_collect` 只算 `sum(ratings) / len(ratings)`，不要呼叫 `round`。四捨五入是 Phase 19（`19-Phase19-Analytics-學習指標.md`）顯示時才做的事。

**錯誤 3：每天跑都產生一個新版本**

- 症狀：連續兩天跑同一份資料，第二天又多了一版 v3。
- 原因：`task_diagnose` 沒有查操作紀錄，或 `evidence_key` 用了會變動的輸入（例如把執行時間也算進去）。
- 解法：確認 `evidence_key` 只吃 `feedback_ids`，而且 `task_collect` 的 `feedback_ids` 有排序；確認 `task_diagnose` 有查 `load_operation(review_operation_id(...))`，且 `REVIEW_DONE_STATUSES` 包含 `refined`。用 `test_diagnose_skips_when_same_evidence_already_processed` 驗證。

**錯誤 4：模型把整篇教學重寫了**

- 症狀：新版本的第 1、2、4 步文字跟舊版不一樣。
- 原因：只靠 prompt 要求模型「只改第 3 步」，沒有用程式核對。
- 解法：確認 `task_refine` 有依序呼叫 `apply_step_rewrites` 與 `assert_unchanged_steps`，而且兩個函式的例外沒有被 `try/except` 吞掉。設計文件 §7.6 要求這一項由程式驗證。

**錯誤 5：`ContentError: 全文缺少區塊：Prerequisites`**

- 症狀：`load_version_content` 讀得到檔案，`content.parse_markdown` 卻說缺區塊。
- 原因：S3 上的全文不是 Phase 07 的 `content.render_markdown` 產生的（例如手動貼了一份格式不同的 Markdown），或是標題層級寫成 `###`。
- 解法：先用下面這段產生一份標準格式對照，再跟 S3 上的內容比對。區塊標題必須剛好是 `## Problem`、`## Prerequisites`、`## Steps`、`## Expected Outcome`，主標題是單一個 `# `。

```bash
uv run python - <<'PY'
from training_kb.content import render_markdown
from training_kb.models import StepDraft, StepType, TutorialContent
sample = TutorialContent(
    title="標題", problem="問題", prerequisites=["前置一"],
    steps=[StepDraft(type=StepType.click_ui, text="第一步", feature_id="Prepare")],
    expected_outcome="結果",
)
print(render_markdown(sample))
PY
```

**錯誤 6：`TypeError: FakeWriter.generate_json() got an unexpected keyword argument 'temperature'`**

- 症狀：Task 8 的測試在呼叫模型那一行爆掉。
- 原因：Phase 05 的 `FakeWriter` 沒有跟 `Writer` 協定一樣接受 `temperature`。
- 解法：回到 Phase 05（`05-Phase05-Writing-Bedrock呼叫與輸出驗證.md`），讓 `FakeWriter.generate_json` 的參數與 `Writer` 協定完全一致：`system`、`user`、`schema`、`operation_id`、`node`、`max_tokens`、`temperature`。

**錯誤 7：`AttributeError: 'FakeRepo' object has no attribute 'put_meta'`**

- 症狀：Task 9 的測試呼叫到真的 `create_version`。
- 原因：`monkeypatch.setattr` 的目標寫成 `training_kb.content.create_version`，但 `feedback.py` 是用 `from training_kb.content import create_version` 匯入的，改到的不是同一個名稱。
- 解法：一定要改 `training_kb.pipelines.feedback` 模組裡的名稱（本文件的 `patch_content` 就是這樣寫的）。

---

## 9. 這階段不做的事

| 不做的事 | 留給哪一階段 |
|---|---|
| `propose_rules`（從同版同類 ≥ 5 筆回饋提出 candidate 規則） | Phase 18（`18-Phase18-Feedback-Review-候選規則與每日排程.md`） |
| `infra/asl/feedback-review.asl.json`（Step Functions 流程定義、Map、Retry／Catch） | Phase 18 |
| EventBridge Scheduler 每日 00:30 UTC 觸發、Demo 手動觸發 | Phase 18 |
| 把 candidate 規則變成 active、規則衝突判定、規則退役 | Phase 20（`20-Phase20-規則驗證與狀態轉換.md`） |
| 平均評分、負面回饋數、重開票率等 Dashboard 指標 | Phase 19（`19-Phase19-Analytics-學習指標.md`）。本階段的 `task_collect` 只為了門檻判定算一次平均，公式與 Phase 19 的 `analytics.average_rating` 相同，但不是同一個函式。 |
| 真的寫入 DynamoDB／S3 的整合測試、注入寫入失敗驗證 | Phase 24（`24-Phase24-失敗復原與重送驗收.md`） |
| 教學頁面上的回饋 widget、瀏覽紀錄匯出 | Phase 22（`22-Phase22-S3靜態教學站.md`） |
| Demo 種子回饋資料（八筆、十筆的完整 JSON） | Phase 21（`21-Phase21-Demo種子資料與可重算驗證.md`） |
| 自己再寫一份 Markdown 解析器 | 不做。Phase 16 已經在 `content.py` 建立 `parse_markdown(markdown, steps)`，而且它的文件寫明「Phase 17 的 REFINE 也會用同一個函式」。本階段只加一層讀 S3 的 `load_version_content`，不重複解析邏輯。 |
| 自己再定義一份模型輸出 schema | 不做。`StepRewrite`、`StepRewriteItem`、`WeakDiagnosis`、`DiagnosisItem` 都在 Phase 05 的 `writing/schemas.py`，本階段只 import。 |

---

## 10. 對照：設計章節與 Rule 編號

本階段落實的 Rule 來自設計文件第 20 節。`@Missing` 標記代表 Gherkin 還缺原始 Example，不代表可以略過契約。

### 主要責任：`docs/spec/features/定期檢視回饋.feature`（設計文件 §20.5）

| Rule | 原文 | 本階段哪個 Task 落實 |
|---:|---|---|
| 1 | Periodic Feedback Review 每日執行 | Task 3、Task 10（本階段做出可每日執行的 task 序列；真正的排程在 Phase 18） |
| 2 | 弱教學的版本平均評分必須小於 3.5 | Task 1（`is_weak` 的 `avg < thresholds.weak_avg_below`）、Task 4（未四捨五入的 `avg`） |
| 3 | 弱教學的版本回饋樣本數必須至少為 10 | Task 1（`ReviewPolicy.formal()` = 10、`ReviewPolicy.demo()` = 8） |
| 4 | 弱教學必須具有 recurring Feedback Category | Task 1（`top_category_count >= 5`）、Task 4（`approved_category_counts`） |
| 5 | 診斷結果包含需要改寫的步驟編號與原因 | Task 7（`prompt_diagnose_weak` 要求編號與原因；schema `WeakDiagnosis`／`DiagnosisItem` 由 Phase 05 提供）、Task 8（`diagnosis` 寫進 state） |
| 6 | 診斷找不到有效步驟時不建立新版 | Task 8（`action = "NO_STEP"`、操作紀錄寫 `無可改步驟`） |
| 7 | REFINE 只重寫診斷命中的步驟 | Task 6（`apply_step_rewrites`／`assert_unchanged_steps`）、Task 9 |
| 8 | REFINE 的下一版 reason 記錄回饋數與類別 | Task 2（`refine_reason`）、Task 9（傳進 `allocate_version`） |
| 9 | Feedback Review 是唯一提出 Authoring Rule 的 pipeline | 不在本階段；Phase 18 |

### 一併遵守：`docs/spec/features/套用教學規則.feature`（設計文件 §20.4）

| Rule | 原文 | 本階段哪個 Task 落實 |
|---:|---|---|
| 1 | CREATE、UPDATE 與 REFINE 在寫作前讀取教學規則 | Task 9（改寫前先 `rules_for_content`） |
| 2 | 一般寫作路徑只取得 status 為 active 的規則 | Task 9（`deps.repo.list_rules(RuleStatus.active)`） |
| 3 | 依 step 型態與 applies_when 篩選規則 | Task 9（只把命中步驟的 `step.type` 傳給 `rules_for_content`） |
| 4 | 適用規則的內容注入教學寫作 prompt | Task 9（`rules_block` 傳進 `prompt_rewrite_steps`） |
| 7 | 版本的 rules_applied 記錄本次套用的規則 | Task 9（`rule_ids` 傳進 `allocate_version`；未改寫步驟沿用的規則不計，對應 F29） |
| 8 | 後續 Release 重寫仍注入適用的教學規則 | 不在本階段；Phase 16 已落實 |

### 一併遵守：`docs/spec/features/執行教學流程.feature`（設計文件 §20.3）

| Rule | 原文 | 本階段哪個 Task 落實 |
|---:|---|---|
| 4 | 每個 Bedrock 呼叫設定 max_tokens | Task 8（`gen_max_tokens_judgement`）、Task 9（`gen_max_tokens_writing`） |
| 8 | LLM 輸出遵循指定 JSON schema | Task 7（用 Phase 05 的 `WeakDiagnosis`）、Task 8（`generate_json(schema=...)`） |
| 9 | 判斷節點使用低 temperature | Task 8（`deps.settings.gen_temperature`，預設 0.1） |
| 6、7 | 每個 Step Functions Task 設定 Retry／Catch | 不在本階段；Phase 18 的 ASL |

### 一併遵守：`docs/spec/features/建立教學版本.feature`（設計文件 §20.6）

| Rule | 原文 | 本階段哪個 Task 落實 |
|---:|---|---|
| 2 | 任一 pipeline 修改既有教學時使用該篇的下一個版本號 | Task 9（呼叫 `allocate_version`，不自己算 current + 1） |
| 4 | 每次建立版本都記錄引起變更的 reason | Task 2、Task 9 |
| 9 | 沒有 Feature 或引用多個 Feature 的步驟不可保存 | Task 9（`validate_content`） |

### 相關釐清決策

| 編號 | 內容 | 本階段落實位置 |
|---|---|---|
| F20 | 正式 n ≥ 10；Demo 使用明示且隔離的 n ≥ 8 門檻 | Task 1 |
| F21 | 同一類別至少 5 筆，與候選規則提出門檻一致 | Task 1、Task 4 |
| F22 | 只檢視 current_version，使用該版截至本次執行的全部有效回饋 | Task 3、Task 4 |
| F23 | 完成後記錄已處理證據集合，必須有新的有效證據才可再次觸發 | Task 2、Task 8 |
| F24 | 記錄無可修改步驟，本次不建立版本，保留回饋供後續分析 | Task 8 |
| F29 | 只記錄本次寫作 prompt 實際注入的規則 | Task 9 |
| F43 | 待分類不因 category 計入負面 | Task 4（`approved_category_counts` 跳過待分類） |
| F49 | 整次執行以失敗結束，不發布新版本 | Task 10 |
| F52 | 沒有任何有效評分時平均為 null，不當成 0 分 | Task 1、Task 4 |
| D28 | REFINE 的 reason 使用 `feedback:<n> 則 <category>` | Task 2 |
| D13 | 核定類別表初始為「找不到按鈕」「缺少資訊」，未知值進待分類 | Task 4 |
| D26 | 同一邏輯變更重試時重用原版本號 | Task 8（操作紀錄）、Task 9（`allocate_version` 用同一個 operation_id） |
| O2（待確認） | 操作紀錄與接受順序的儲存形狀。**本計劃選擇**：`OPS#review:<slug>:<evidence_key>` + `LOCK#<slug>` | Task 2、Task 8、Task 9 |

---

## 11. 參考來源

### 設計文件章節（`docs/design/training-kb.md`）

- §7.5 Periodic Feedback Review：兩個判斷分開做（分流圖、門檻、REFINE、不改版、失敗語意）
- §7.6 共用寫作與 Analytics 的內部介面（改寫步驟的程式驗證要求、規則注入）
- §8.1 五種動作與版本鏈（REFINE 的位置與 reason 範例）
- §8.2 create_version 的完成條件（published_at = null、S3 與關係齊全才能發布）
- §8.3 發布與併發必須守住的界線（per-tutorial 鎖、多篇全有或全無）
- §11.2 可重算的評分與負面回饋（A v1 八筆、2.875、Demo 與正式門檻的差別）
- §12.1 指標公式（負面回饋、未四捨五入）
- §14.1 各層如何結束（診斷沒有有效步驟時不建立版本）
- §14.3 執行參數的建議起點（max_tokens 512／2048、temperature 0.1、每日 UTC 00:30）
- §15 測試與驗收設計（「Review」列的邊界值）
- §16 交付切片 S6
- §18 待確認事項 O2
- §19.1／§19.2 釐清決策 D13、D26、D28、F20–F24、F29、F43、F49、F52
- §20.3／§20.4／§20.5／§20.6 逐條 Rule 與負責模組

### 規格檔

- `docs/spec/features/定期檢視回饋.feature`（9 條 Rule）
- `docs/spec/features/套用教學規則.feature`（Rule 1–4、7）
- `docs/spec/features/建立教學版本.feature`（Rule 2、4、9）
- `docs/spec/features/執行教學流程.feature`（Rule 4、8、9）
- `docs/spec/erm.dbml`（FEEDBACK、TUTORIAL_VERSION、AUTHORING_RULE 欄位註解）
- `docs/spec/.clarify/resolved/features/定期檢視回饋_同一批回饋是否可以再次觸發_REFINE.md`（F23 解決記錄）
- `docs/spec/.clarify/resolved/data/TUTORIAL_VERSION_REFINE_版本的_reason_採用哪種標準格式.md`（D28 解決記錄）

### 外部官方文件

- Python `hashlib`：<https://docs.python.org/3/library/hashlib.html>
- Python `json.dumps` 的 `separators` 與 `sort_keys`：<https://docs.python.org/3/library/json.html#json.dumps>
- pydantic v2 `model_validate`：<https://docs.pydantic.dev/latest/api/base_model/#pydantic.BaseModel.model_validate>
- pytest `monkeypatch`：<https://docs.pytest.org/en/stable/how-to/monkeypatch.html>
- pytest `parametrize`：<https://docs.pytest.org/en/stable/how-to/parametrize.html>
- Amazon Bedrock Claude 請求參數（max_tokens、temperature）：<https://docs.aws.amazon.com/bedrock/latest/userguide/model-parameters-anthropic-claude-messages-request-response.html>
- AWS Step Functions 錯誤處理（Retry／Catch，本階段先只在程式層區分 TransientError／PermanentError）：<https://docs.aws.amazon.com/step-functions/latest/dg/concepts-error-handling.html>
