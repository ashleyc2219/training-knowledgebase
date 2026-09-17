# Phase 07：Content-建立教學版本

| 項目 | 內容 |
|---|---|
| 上一階段 | Phase 06：規則選取與注入（`06-Phase06-規則選取與注入.md`） |
| 下一階段 | Phase 08：Content-發布與退役（`08-Phase08-Content-發布與退役.md`） |
| 對應設計文件章節 | §8.1、§8.2、§9.1、§9.2、§9.3、§10（`docs/design/training-kb.md`） |
| 對應交付切片 | S2（設計文件第 16 節） |
| 預估時間 | 約 5 小時 |
| 做完會得到 | 一個 `content` 模組，能配出版本號、驗證五段內容、把全文與差異寫進 S3、把版本與步驟寫進 DynamoDB，並在最後自己核對一次有沒有寫齊。 |

---

## 1. 這階段做完會得到什麼

做完之後，你可以在本機用一行 Python 建立一個**未發布**的教學版本：

```text
create_tutorial()  ->  建立教學身分（status=active、current_version=None）
allocate_version() ->  決定這次要寫第幾版（重試會拿到同一個版號）
validate_content() ->  五段齊全？每步恰好一個存在的 Feature？
render_markdown()  ->  把結構化內容變成固定格式的 Markdown 全文
make_diff()        ->  跟前一版比較，產生 unified diff（v1 是空字串）
create_version()   ->  把全文、差異、VERSION、STEP 與三種關係邊全部寫下去
verify_version_complete() -> 回報有沒有缺東西
```

這一版寫完之後 `published_at` 是空的，讀者看不到它。把它上架是 Phase 08 的工作。

這樣分兩段是規格要求：D25（設計文件第 19.1 節的資料決策編號）說「版本可以先建立，`published_at` 為 null 代表未發布」，F36（第 19.2 節的功能決策編號）說「內容已寫入但版本關聯不完整時，保留不可公開的待完成版本」。

---

## 2. 它在整張地圖的位置

```text
基礎層        01 骨架 -> 02 模型與鍵 -> 03 Repository(本機) -> 04 AWS 基礎建設
                                                                    |
AI 與內容層   05 Writing(Bedrock) -> 06 規則注入 -> 07 建立版本 -> 08 發布與退役 -> 09 圖譜查詢
                                                   ^^^^^^^^^^^                          |
                                                   你在這裡                              |
接入層        10 Ingress 驗簽 -> 11 Rote 判定 -> 12 Rote Agent -------------------------+
                                                                                       |
流程層        13 Ticket Analysis -> 14 Step Functions 上線 -> 15 Feedback/View 匯入 -> 16 Release Update
                                                                                       |
學習層        17 Review:REFINE -> 18 Review:候選規則+排程 -> 19 Analytics 指標 -> 20 規則驗證
                                                                                       |
展示與驗收層  21 Demo 種子資料 -> 22 靜態教學站 -> 23 Demo 控制台 -> 24 失敗復原驗收 -> 25 安全與當日準備
```

---

## 3. 開始前檢查

- [ ] **1. 整包測試會過**

執行：

```bash
cd ~/AWS-Hackathon
uv run pytest -q
```

預期：全部 `passed`，沒有 `error`。

- [ ] **2. Phase 02 的模型與鍵函式都在**

執行：

```bash
uv run python -c "
from training_kb.models import (Tutorial, TutorialContent, TutorialStep, TutorialVersion,
                                StepDraft, StepType, TutorialStatus,
                                make_version_id, parse_version_id)
from training_kb.keys import feature_pk, rule_pk, step_pk, tutorial_pk, version_pk, parse_pk
print(make_version_id('prepare-meeting', 2), parse_version_id('prepare-meeting@v2'))
print(step_pk('prepare-meeting@v2', 3), feature_pk('Prepare'), parse_pk('FEATURE#Prepare'))
"
```

預期輸出：

```text
prepare-meeting@v2 ('prepare-meeting', 2)
STEP#prepare-meeting@v2#3 FEATURE#Prepare ('FEATURE', 'Prepare')
```

- [ ] **3. Phase 03 的 Repository 有本階段要用的方法**

執行：

```bash
uv run python -c "
from training_kb.repository import Repository
need = ['put_meta','get_meta','update_meta','put_edge','query_pk','scan_entity',
        'put_object','get_object','object_exists','begin_operation','load_operation',
        'update_operation']
missing = [n for n in need if not hasattr(Repository, n)]
print('缺少：', missing)
"
```

預期輸出：

```text
缺少： []
```

如果有缺，回 Phase 03（`03-Phase03-Repository-本機儲存層.md`）補齊再回來。

- [ ] **4. moto 已安裝**

執行：

```bash
uv run python -c "import moto; print(moto.__version__)"
```

預期：印出版本號，且**主版本至少是 5**（例如 `5.0.28`）。moto 是在自己電腦上假裝成 AWS 的套件，不會連上網路。5 以前的版本沒有 `mock_aws` 這個名稱，也不支援 S3 條件寫入。若版本太舊，執行 `uv add --dev "moto[s3,dynamodb]>=5"`。

- [ ] **5. Phase 06 的規則模組可以匯入**

執行：

```bash
uv run python -c "from training_kb.writing.rules import rules_for_content; print('ok')"
```

預期輸出：`ok`。

---

## 4. 名詞小抄

| 名詞 | 白話解釋 | 在本階段哪裡用到 |
|---|---|---|
| Tutorial（教學） | 一篇教學的「身分」，用 `slug`（網址用的短名稱，例如 `prepare-meeting`）辨識。它本身不含教學文字。 | `create_tutorial` |
| TutorialVersion（教學版本） | 這篇教學某一次修改後的完整版本，識別碼是 `<slug>@v<n>`，例如 `prepare-meeting@v2`。教學文字屬於版本，不屬於教學。 | `create_version` |
| `slug` | 教學的短名稱，只用英數與連字號。 | 到處 |
| `supersedes`（取代） | 這一版取代了哪一版。v1 沒有，所以是 `None`。 | 版本鏈、diff |
| `reason`（改動原因） | 為什麼產生這一版，只有三種格式：`gap:<cluster_id>`、`release:<id>`、`feedback:<n> 則 <category>`。 | `allocate_version` |
| `published_at` | 這一版上架的時間。空的代表還沒上架（D25）。 | 本階段一律留空 |
| `current_version` | 教學目前對外的版本。只有 publish 成功才會切換（F37）。 | 本階段用它決定下一個版號 |
| S3 | AWS 的檔案儲存服務，像一個超大的雲端資料夾。用「key」（一個字串路徑）存取檔案。 | 全文與差異檔 |
| DynamoDB | AWS 的資料庫，像一本超大的字典：用 `PK`（分割鍵）加 `SK`（排序鍵）找到一筆資料。 | 版本、步驟、關係邊 |
| item | DynamoDB 裡的一筆資料，等於一列。 | 到處 |
| 關係邊（edge） | 用一筆 item 表示「A 跟 B 有關係」。格式固定：`PK=起點`、`SK=關係#終點`、`target=終點`。 | REFERENCES／SUPERSEDES／APPLIED_TO |
| `target` | 關係邊的終點，同時也是 GSI `by_target` 的分割鍵，讓我們可以反過來問「誰指向我」。 | STEP item |
| GSI（全域次要索引） | DynamoDB 的第二套索引，讓你可以用別的欄位查資料。本專案只有一個叫 `by_target`。 | 本階段只建立資料，查詢在 Phase 09 |
| unified diff | 一種標準的差異格式，開頭是 `--- 舊檔`、`+++ 新檔`，減號開頭是刪掉的行，加號開頭是新增的行。Git 顯示差異用的就是它。 | `make_diff` |
| 條件寫入（conditional write） | 「只有在某個條件成立時才寫」。S3 用 `IfNoneMatch='*'` 表示「只有這個 key 還不存在時才寫」。 | 保護已存在的產物 |
| 操作紀錄（operation record） | 一次邏輯操作的執行筆記，存在 DynamoDB 的 `OPS#<id>` 與 S3 的 `operations/<id>.json`。重試時靠它找回原本的版號。 | `allocate_version` |
| moto | 在測試裡假裝成 AWS 的 Python 套件。程式碼照常呼叫 boto3，但資料其實在記憶體裡。 | 所有 integration 測試 |
| fixture | pytest 的「測試前置準備」機制。寫成一個函式，測試把它的名字放進參數就會自動拿到。 | `repo` |
| D25、D26、F36、F50 | 設計文件第 19 節的決策編號。 | 第 5 節、第 10 節 |

---

## 5. 設計說明

### 5.1 版本鏈長什麼樣子

```text
Tutorial: prepare-meeting  (status=active, cluster_id=c12)
  |
  +-- v1   reason = gap:c12                      published_at = 2026-08-01T00:00:00Z
  |     ^
  |     | SUPERSEDES 邊
  +-- v2   reason = feedback:8 則 找不到按鈕      published_at = 2026-08-20T00:00:00Z
  |     ^
  |     | SUPERSEDES 邊
  +-- v3   reason = release:r_42                 published_at = null（還沒上架）
        ^
        |
  current_version 仍然指向 v2，因為 v3 還沒 publish
```

三件必須記住的事（設計文件 §8.1）：

1. **版本號屬於教學，不屬於流程。** Ticket Analysis、Release Note Update、Feedback Review 三條流程不可以各自計數。所以版號一律由 `content.allocate_version` 配發。
2. **同一個邏輯變更重試時要拿到同一個版號**（D26）。做法是把版號記進操作紀錄（DynamoDB 的 `OPS#<operation_id>` 加 S3 的 `operations/<id>.json`），重試時先去讀它。設計文件第 18 節把「操作紀錄放在哪裡、寫入順序怎麼保證」列為**待確認事項 O2**；用共用操作紀錄保存版號，是**本計劃選擇（對應 O2）**，它的失敗與重送驗收要等 Phase 24 才完成，在那之前不可以宣稱重送去重已經驗過。
3. **下一版以「最近的已發布版本」為基底加一**。`Tutorial.current_version` 只有 publish 成功才會更新（F37），所以它就是「最近的已發布版本」。一個寫到一半永久失敗的 v2，不會把基底往前推；下一次仍然從 v1 算起。D26 允許版號出現缺口，本模組不會為了補洞而回頭改號碼。

### 5.2 create_version 的寫入順序

設計文件 §8.2 規定了順序，順序不能顛倒：

```text
 (1) 讀操作紀錄，決定版號         allocate_version
      |
 (2) 驗證五段內容與每步的 Feature   validate_content       <- 不合法就停在這裡，什麼都不寫
      |
 (3) 產生全文 Markdown 與 diff     render_markdown / make_diff
      |
 (4) 寫 S3（私有區，條件寫入）
      |   tutorials/<slug>/v<n>.md
      |   tutorials/<slug>/v<n>.diff
      |
 (5) 寫 DynamoDB
      |   VERSION#<slug>@v<n>          SK=META      （published_at 不寫）
      |   STEP#<slug>@v<n>#1..#k       SK=REFERENCES#FEATURE#<id>
      |   VERSION#<slug>@v<n>          SK=SUPERSEDES#VERSION#<前一版>
      |   RULE#<rule_id>               SK=APPLIED_TO#VERSION#<slug>@v<n>
      |
 (6) 自己核對一次                  verify_version_complete
      |
 (7) 回傳 TutorialVersion（published_at = None）
```

為什麼 S3 先、DynamoDB 後？因為 S3 的東西在 `tutorials/` 這個**私有**前綴底下，沒有任何人看得到（公開的只有 `site/`，見 Phase 08）。先寫私有產物，就算第 5 步失敗，外面也讀不到半成品。F36 的答案是 A：「保留不可公開的待完成版本，待 S3、版本與關聯全部就緒後才允許發布」——所以失敗時**不要**回頭刪 S3，留著讓重試沿用。

S3 同一個 key 已經存在時怎麼辦？設計文件 §8.3 說「應核對它是否為本次相同產物，而非盲目重寫」。所以程式先讀出來比對：

```text
key 已存在 + 內容一模一樣  -> 視為這次重試，當成成功，繼續往下做
key 已存在 + 內容不一樣    -> 拋 ContentError，不覆寫
key 不存在                -> 用 IfNoneMatch='*' 條件寫入
```

### 5.3 一筆 DynamoDB 資料長什麼樣子

```text
表 training_kb（PK + SK 複合主鍵，GSI by_target 以 target 為分割鍵）

PK                           SK                            其他欄位
---------------------------- ----------------------------- --------------------------------
TUTORIAL#prepare-meeting     META                          entity, slug, topic, feature_ids,
                                                           status, cluster_id,
                                                           （current_version 未發布時不寫）
VERSION#prepare-meeting@v2   META                          entity, version_id, slug, reason,
                                                           rules_applied, s3_key, step_count,
                                                           supersedes, created_at
                                                           （published_at 未發布時不寫）
VERSION#prepare-meeting@v2   SUPERSEDES#VERSION#...@v1     target=VERSION#prepare-meeting@v1
STEP#prepare-meeting@v2#1    REFERENCES#FEATURE#Prepare    target=FEATURE#Prepare,
                                                           entity, tutorial_version, index,
                                                           type, text
STEP#prepare-meeting@v2#2    REFERENCES#FEATURE#Prepare    同上
RULE#R-007                   APPLIED_TO#VERSION#...@v2     target=VERSION#prepare-meeting@v2
FEATURE#Prepare              META                          entity, name, aliases, first_seen
```

有幾個要注意的地方：

- **步驟的 item 同時是「步驟」也是「引用邊」。** 設計文件 §9.1 的表格寫得很清楚：`TUTORIAL_STEP` 的 SK 就是 `REFERENCES#<Feature PK>`。所以一個步驟只能引用一個 Feature（D05），這是資料結構強制的，不是靠檢查。
- **每一步是一個獨立的 PK。** `STEP#prepare-meeting@v2#1` 與 `#2` 是兩個不同的分割鍵，沒辦法用一次 Query 全部撈出來。所以 VERSION item 多存一個 `step_count`，讀步驟時就知道要讀到第幾號。這是**本計劃選擇**：`step_count` 是可以由 S3 全文重建的執行輔助欄位，不是新的業務實體或關係，目的是讓設計文件 §8.2 要求的「核對全部內容與關係」有辦法做。
- **值是 `None` 的欄位乾脆不寫。** `current_version`、`supersedes`、`published_at` 沒有值時，我們不寫 `NULL`，而是整個屬性不放進 item。這樣 Phase 08 判斷「還沒發布」時可以直接用 `attribute_not_exists`，不必去分辨「屬性不存在」跟「屬性是 NULL」。這是**本計劃選擇**。
- **`created_at` 不是 ERM 欄位**，只是執行資訊，方便追溯什麼時候寫的。

### 5.4 五段內容的驗證規則

設計文件 §7.3 與 §7.6 規定：新教學必須有 Title、Problem、Prerequisites、Steps、Expected Outcome 五段；每一步要輸出 `type`、`text` 與**恰好一個既有 Feature**；零個或多個引用必須先拆步或驗證失敗（D05）。

`TutorialContent.steps` 裡每個 `StepDraft` 只有一個 `feature_id` 字串欄位，所以「多個 Feature」在資料結構上塞不進去。模型真的想塞多個時，唯一的做法是用逗號串起來（例如 `"Prepare,Share Summary"`）。**本計劃選擇：** `validate_content` 明確擋掉含有逗號或括號的 `feature_id`，並給出不同的錯誤訊息，讓「零個」「多個」「不存在」三種狀況分得開。括號會被擋掉，是因為全文格式用括號包住步驟的 `type` 與 `feature`（見下一節），括號出現在 Feature 識別碼裡會讓全文無法被正確解讀。

`prerequisites` 必須至少有一項，而且每一項不可以是空白。**本計劃選擇：** 真的沒有前置條件時，寫作 prompt 要求模型輸出一項「無」，而不是給空清單，這樣「五段齊全」才有一致的判準。

### 5.5 全文格式與 diff

`render_markdown` 產生固定格式，欄位順序、標題文字、空行數量都不能變動——因為 diff 是逐行比較的，格式一變，整份 diff 就會變成「整篇都改了」。

```text
# <title>
<空行>
## Problem
<空行>
<problem>
<空行>
## Prerequisites
<空行>
- <第一項>
- <第二項>
<空行>
## Steps
<空行>
1. (type=click_ui, feature=Prepare) <第一步文字>
2. (type=read, feature=Prepare) <第二步文字>
<空行>
## Expected Outcome
<空行>
<expected_outcome>
<檔案結尾換行>
```

diff 用 Python 標準函式庫的 `difflib.unified_diff`（設計文件第 4 節共用技術決定）。F50 的答案是 C：「建立空的 `v1.diff`，介面另外以版本號識別它沒有前版」。所以：

```text
v1（supersedes 是 None） -> make_diff 回傳 ""，S3 上仍然寫一個 0 位元組的 v1.diff
v2 以後                  -> 正常的 unified diff；如果內容完全沒變也是 ""
```

畫面上顯示「第一版，沒有前一版可比較」是 Phase 08 的 `SiteRenderer` 做的事，判準是 `supersedes is None`，不是「diff 檔是空的」。

---

## 6. 工作項目

### Task 1：S3 key 與固定格式全文

**目的**：寫出 `version_keys` 與 `render_markdown`，把結構化內容變成一份格式固定的 Markdown。

**檔案**：
- 新增：`src/training_kb/content.py`
- 測試：`tests/unit/test_content_render.py`

**介面**：
- 消費：`training_kb.models.TutorialContent`、`training_kb.models.StepDraft`、`training_kb.models.StepType`（Phase 02）
- 產出：`training_kb.content.version_keys(slug: str, n: int) -> dict[str, str]`
- 產出：`training_kb.content.render_markdown(content: TutorialContent) -> str`

- [ ] **步驟 1：寫測試**

建立 `tests/unit/test_content_render.py`：

```python
"""Phase 07：全文格式與 S3 key 的純邏輯測試。"""

from training_kb.content import render_markdown, version_keys
from training_kb.models import StepDraft, StepType, TutorialContent


def make_content() -> TutorialContent:
    return TutorialContent(
        title="準備會議",
        problem="使用者找不到會前摘要",
        prerequisites=["已登入", "已建立會議"],
        steps=[
            StepDraft(type=StepType.click_ui, text="開啟會議頁面", feature_id="Prepare"),
            StepDraft(type=StepType.read, text="閱讀右側摘要", feature_id="Prepare"),
        ],
        expected_outcome="看到會前摘要",
    )


def test_版本產物的_s3_key():
    assert version_keys("prepare-meeting", 2) == {
        "md": "tutorials/prepare-meeting/v2.md",
        "diff": "tutorials/prepare-meeting/v2.diff",
    }


def test_全文格式逐字固定():
    assert render_markdown(make_content()) == (
        "# 準備會議\n"
        "\n"
        "## Problem\n"
        "\n"
        "使用者找不到會前摘要\n"
        "\n"
        "## Prerequisites\n"
        "\n"
        "- 已登入\n"
        "- 已建立會議\n"
        "\n"
        "## Steps\n"
        "\n"
        "1. (type=click_ui, feature=Prepare) 開啟會議頁面\n"
        "2. (type=read, feature=Prepare) 閱讀右側摘要\n"
        "\n"
        "## Expected Outcome\n"
        "\n"
        "看到會前摘要\n"
    )


def test_步驟編號從一開始():
    markdown = render_markdown(make_content())
    step_lines = [line for line in markdown.splitlines() if line[:1].isdigit()]

    assert step_lines[0].startswith("1. ")
    assert step_lines[1].startswith("2. ")


def test_全文以單一換行結尾():
    markdown = render_markdown(make_content())

    assert markdown.endswith("看到會前摘要\n")
    assert not markdown.endswith("\n\n")
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：

```bash
uv run pytest tests/unit/test_content_render.py -v
```

預期：FAIL，`ModuleNotFoundError: No module named 'training_kb.content'`。

- [ ] **步驟 3：寫最少的程式讓測試通過**

建立 `src/training_kb/content.py`：

```python
"""教學版本的建立、驗證、全文與差異（Phase 07）。

版本編號、五段內容驗證、S3 全文與 diff、VERSION／STEP item 與關係邊都集中在這裡。
各 pipeline 不可以自己拼出「current + 1」（設計文件 §8.1）。
"""

from __future__ import annotations

from training_kb.models import TutorialContent


def version_keys(slug: str, n: int) -> dict[str, str]:
    """這一版在 S3 私有區的兩個物件 key（設計文件 §9.3）。

    這兩個 key 都在 tutorials/ 前綴底下，屬於私有區，任何人都讀不到。
    公開的靜態站在 site/ 前綴，由 Phase 08 的發布流程寫入。
    """
    return {
        "md": f"tutorials/{slug}/v{n}.md",
        "diff": f"tutorials/{slug}/v{n}.diff",
    }


def render_markdown(content: TutorialContent) -> str:
    """把五段內容變成固定格式的 Markdown 全文。

    格式固定是硬性要求：diff 逐行比較，格式一變整份 diff 就會變成「整篇都改了」。
    """
    lines: list[str] = [f"# {content.title}", "", "## Problem", "", content.problem, ""]
    lines += ["## Prerequisites", ""]
    for item in content.prerequisites:
        lines.append(f"- {item}")
    lines += ["", "## Steps", ""]
    for index, step in enumerate(content.steps, start=1):
        lines.append(f"{index}. (type={step.type}, feature={step.feature_id}) {step.text}")
    lines += ["", "## Expected Outcome", "", content.expected_outcome, ""]
    return "\n".join(lines)
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：

```bash
uv run pytest tests/unit/test_content_render.py -v
```

預期：PASS，4 個 `PASSED`。

- [ ] **步驟 5：commit**

```bash
git add src/training_kb/content.py tests/unit/test_content_render.py
git commit -m "feat(content): 產生固定格式的教學全文與 S3 key"
```

---

### Task 2：五段內容與每步一個 Feature 的驗證

**目的**：寫出 `validate_content`。內容不合格時拋 `ContentError`，而且一次列出所有問題，讓後續的「有限重試一次」能把完整訊息交給模型。

**檔案**：
- 修改：`src/training_kb/content.py`
- 測試：`tests/unit/test_content_validate.py`

**介面**：
- 消費：`training_kb.errors.ContentError`（Phase 01）
- 產出：`training_kb.content.validate_content(content: TutorialContent, known_feature_ids: set[str]) -> None`

- [ ] **步驟 1：寫測試**

建立 `tests/unit/test_content_validate.py`：

```python
"""Phase 07：五段內容驗證的純邏輯測試。"""

import pytest

from training_kb.content import validate_content
from training_kb.errors import ContentError
from training_kb.models import StepDraft, StepType, TutorialContent

KNOWN = {"Prepare", "Share Summary"}


def make_content(**overrides) -> TutorialContent:
    data = {
        "title": "準備會議",
        "problem": "使用者找不到會前摘要",
        "prerequisites": ["已登入"],
        "steps": [
            StepDraft(type=StepType.click_ui, text="開啟會議頁面", feature_id="Prepare")
        ],
        "expected_outcome": "看到會前摘要",
    }
    data.update(overrides)
    return TutorialContent(**data)


def test_一個步驟一個_feature_時通過():
    assert validate_content(make_content(), KNOWN) is None


def test_多個步驟各自一個_feature_時通過():
    content = make_content(
        steps=[
            StepDraft(type=StepType.click_ui, text="開啟會議頁面", feature_id="Prepare"),
            StepDraft(type=StepType.read, text="閱讀摘要", feature_id="Prepare"),
            StepDraft(type=StepType.input, text="輸入標題", feature_id="Share Summary"),
        ]
    )

    assert validate_content(content, KNOWN) is None


def test_沒有步驟時拒絕():
    with pytest.raises(ContentError) as exc:
        validate_content(make_content(steps=[]), KNOWN)

    assert "缺少 Steps" in str(exc.value)


def test_步驟沒有引用_feature_時拒絕():
    content = make_content(
        steps=[StepDraft(type=StepType.click_ui, text="按一下", feature_id="  ")]
    )

    with pytest.raises(ContentError) as exc:
        validate_content(content, KNOWN)

    assert "第 1 步沒有引用 Feature" in str(exc.value)


def test_步驟引用多個_feature_時拒絕():
    content = make_content(
        steps=[
            StepDraft(
                type=StepType.click_ui, text="按一下", feature_id="Prepare,Share Summary"
            )
        ]
    )

    with pytest.raises(ContentError) as exc:
        validate_content(content, KNOWN)

    assert "第 1 步引用了多個 Feature" in str(exc.value)


def test_步驟引用不存在的_feature_時拒絕():
    content = make_content(
        steps=[StepDraft(type=StepType.read, text="看一下", feature_id="Unknown")]
    )

    with pytest.raises(ContentError) as exc:
        validate_content(content, KNOWN)

    assert "第 1 步引用的 Feature 不存在：Unknown" in str(exc.value)


def test_缺少段落時拒絕並一次列出全部問題():
    content = make_content(title="   ", problem="", prerequisites=[], expected_outcome=" ")

    with pytest.raises(ContentError) as exc:
        validate_content(content, KNOWN)

    message = str(exc.value)
    assert "缺少 Title" in message
    assert "缺少 Problem" in message
    assert "缺少 Prerequisites" in message
    assert "缺少 Expected Outcome" in message


def test_前置條件有空白項目時拒絕():
    with pytest.raises(ContentError) as exc:
        validate_content(make_content(prerequisites=["已登入", "  "]), KNOWN)

    assert "Prerequisites 第 2 項是空的" in str(exc.value)


def test_步驟型態不合法時拒絕():
    # model_construct 會跳過 pydantic 驗證，用來模擬「schema 過了但業務不合法」。
    bad_step = StepDraft.model_construct(type="hover", text="按一下", feature_id="Prepare")

    with pytest.raises(ContentError) as exc:
        validate_content(make_content(steps=[bad_step]), KNOWN)

    assert "第 1 步的 type 不合法" in str(exc.value)


def test_步驟文字是空白時拒絕():
    content = make_content(
        steps=[StepDraft(type=StepType.click_ui, text="   ", feature_id="Prepare")]
    )

    with pytest.raises(ContentError) as exc:
        validate_content(content, KNOWN)

    assert "第 1 步沒有文字" in str(exc.value)
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：

```bash
uv run pytest tests/unit/test_content_validate.py -v
```

預期：FAIL，`ImportError: cannot import name 'validate_content' from 'training_kb.content'`。

- [ ] **步驟 3：寫最少的程式讓測試通過**

在 `src/training_kb/content.py` 的 import 區塊改成：

```python
from training_kb.errors import ContentError
from training_kb.models import StepType, TutorialContent
```

在 `version_keys` 前面加上常數：

```python
# 步驟型態只有三種（D16、設計文件 §9.1）。
LEGAL_STEP_TYPES = frozenset(str(step_type) for step_type in StepType)
```

在 `render_markdown` 後面加上：

```python
def validate_content(content: TutorialContent, known_feature_ids: set[str]) -> None:
    """檢查五段內容與每一步的 Feature 引用；不合格就拋 ContentError。

    一次列出全部問題，讓呼叫端的「有限重試一次」可以把完整訊息交給模型
    （設計文件 §14.1、F48）。
    """
    problems: list[str] = []

    if not content.title.strip():
        problems.append("缺少 Title")
    if not content.problem.strip():
        problems.append("缺少 Problem")
    if not content.expected_outcome.strip():
        problems.append("缺少 Expected Outcome")

    if not content.prerequisites:
        problems.append("缺少 Prerequisites（沒有前置條件時請寫「無」）")
    else:
        for position, item in enumerate(content.prerequisites, start=1):
            if not item.strip():
                problems.append(f"Prerequisites 第 {position} 項是空的")

    if not content.steps:
        problems.append("缺少 Steps")

    for index, step in enumerate(content.steps, start=1):
        if not step.text.strip():
            problems.append(f"第 {index} 步沒有文字")
        if str(step.type) not in LEGAL_STEP_TYPES:
            problems.append(f"第 {index} 步的 type 不合法：{step.type}")

        feature_id = step.feature_id.strip()
        if not feature_id:
            problems.append(f"第 {index} 步沒有引用 Feature")
            continue
        if "," in feature_id:
            problems.append(f"第 {index} 步引用了多個 Feature：{feature_id}")
            continue
        if "(" in feature_id or ")" in feature_id:
            problems.append(f"第 {index} 步的 Feature 識別碼含有括號：{feature_id}")
            continue
        if feature_id not in known_feature_ids:
            problems.append(f"第 {index} 步引用的 Feature 不存在：{feature_id}")

    if problems:
        raise ContentError("教學內容驗證失敗：" + "；".join(problems))
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：

```bash
uv run pytest tests/unit/test_content_validate.py -v
```

預期：PASS，10 個 `PASSED`。

- [ ] **步驟 5：commit**

```bash
git add src/training_kb/content.py tests/unit/test_content_validate.py
git commit -m "feat(content): 驗證五段內容與每步恰好一個 Feature"
```

---

### Task 3：與前一版的 unified diff

**目的**：寫出 `make_diff`。v1 沒有前版，一律回傳空字串（F50）。

**檔案**：
- 修改：`src/training_kb/content.py`
- 測試：`tests/unit/test_content_diff.py`

**介面**：
- 產出：`training_kb.content.make_diff(prev_md: str | None, new_md: str, prev_name: str, new_name: str) -> str`

- [ ] **步驟 1：寫測試**

建立 `tests/unit/test_content_diff.py`：

```python
"""Phase 07：unified diff 的純邏輯測試。"""

from training_kb.content import make_diff

V1 = "# 準備會議\n\n## Steps\n\n1. (type=click_ui, feature=Prepare) 開啟舊頁面\n"
V2 = "# 準備會議\n\n## Steps\n\n1. (type=click_ui, feature=Prepare) 開啟新頁面\n"


def test_第一版沒有前版時_diff_是空字串():
    assert make_diff(None, V1, "", "tutorials/prepare-meeting/v1.md") == ""


def test_內容完全相同時_diff_是空字串():
    assert make_diff(V1, V1, "a.md", "b.md") == ""


def test_diff_使用_unified_格式且標示檔名():
    diff = make_diff(
        V1, V2, "tutorials/prepare-meeting/v1.md", "tutorials/prepare-meeting/v2.md"
    )
    lines = diff.splitlines()

    assert lines[0] == "--- tutorials/prepare-meeting/v1.md"
    assert lines[1] == "+++ tutorials/prepare-meeting/v2.md"
    assert lines[2].startswith("@@")


def test_diff_只標出有改的那一行():
    diff = make_diff(V1, V2, "v1.md", "v2.md")
    changed = [line for line in diff.splitlines() if line[:1] in {"-", "+"}]

    # 前兩行是 --- 與 +++ 的檔名標頭，之後才是真正的差異行。
    assert changed[2] == "-1. (type=click_ui, feature=Prepare) 開啟舊頁面"
    assert changed[3] == "+1. (type=click_ui, feature=Prepare) 開啟新頁面"
    assert len(changed) == 4


def test_diff_以換行結尾():
    diff = make_diff(V1, V2, "v1.md", "v2.md")

    assert diff.endswith("\n")
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：

```bash
uv run pytest tests/unit/test_content_diff.py -v
```

預期：FAIL，`ImportError: cannot import name 'make_diff' from 'training_kb.content'`。

- [ ] **步驟 3：寫最少的程式讓測試通過**

在 `src/training_kb/content.py` 最上面的 import 區塊加入標準函式庫：

```python
import difflib
```

在 `validate_content` 後面加上：

```python
def make_diff(prev_md: str | None, new_md: str, prev_name: str, new_name: str) -> str:
    """產生與前一版的 unified diff。

    v1 沒有前一版，prev_md 傳 None，回傳空字串（F50：仍然建立空的 v1.diff，
    畫面另外用版本號判斷「沒有前一版」）。內容完全相同時也回傳空字串。
    """
    if prev_md is None:
        return ""
    lines = difflib.unified_diff(
        prev_md.splitlines(),
        new_md.splitlines(),
        fromfile=prev_name,
        tofile=new_name,
        lineterm="",
    )
    text = "\n".join(lines)
    return text + "\n" if text else ""
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：

```bash
uv run pytest tests/unit/test_content_diff.py -v
```

預期：PASS，5 個 `PASSED`。

- [ ] **步驟 5：commit**

```bash
git add src/training_kb/content.py tests/unit/test_content_diff.py
git commit -m "feat(content): 產生與前一版的 unified diff"
```

---

### Task 4：Repository 的教學讀寫

**目的**：補上本階段需要的六個固定讀取，並加一個寫測試用 Feature 的小 fixture，後面三個 Task 都用它。

Phase 09（`09-Phase09-圖譜查詢與backfill.md`）會補齊其餘的固定讀取（`find_feature_by_name_or_alias`、`list_versions_of_tutorial`、`list_feedback_of_version` 等）並加上它們的測試；這裡只做 Phase 07、08 用得到的六個。

**檔案**：
- 新增或附加：`tests/integration/conftest.py`
- 修改：`src/training_kb/repository.py`
- 測試：`tests/integration/test_repository_tutorial.py`

**介面**：
- 消費：`Repository.put_meta`、`get_meta`、`put_edge`、`query_pk`、`scan_entity`（Phase 03）
- 消費：`Repository.__init__(table, s3, bucket)` 把參數存成 `self.table`、`self.s3`、`self.bucket`（Phase 03）
- 消費：pytest fixture `repo`（Phase 03 的 `tests/conftest.py` 產出，接上 moto 假 AWS 的 `Repository`）
- 產出：`Repository.get_tutorial(slug: str) -> Tutorial | None`
- 產出：`Repository.put_tutorial(t: Tutorial, *, if_not_exists: bool = False) -> bool`
- 產出：`Repository.get_version(version_id: str) -> TutorialVersion | None`
- 產出：`Repository.get_steps(version_id: str) -> list[TutorialStep]`
- 產出：`Repository.get_feature(feature_id: str) -> Feature | None`
- 產出：`Repository.list_features() -> list[Feature]`
- 產出（測試用）：pytest fixture `seed_feature`

- [ ] **步驟 1：寫測試**

假 AWS 環境與 `repo` fixture 已經由 Phase 03（`03-Phase03-Repository-本機儲存層.md`）建立在 `tests/conftest.py`，**不要再定義第二個同名的 `repo` fixture**。這裡只加一個寫測試 Feature 的小工具。

把下面的內容**附加**到 `tests/integration/conftest.py`（檔案不存在就先建立）：

```python
"""tests/integration/conftest.py：整合測試共用的資料準備工具。

假 AWS 與 repo fixture 在 tests/conftest.py（Phase 03 建立），這裡只加資料準備。
"""

import pytest

from training_kb.keys import feature_pk


@pytest.fixture()
def seed_feature(repo):
    """在測試資料庫寫入一個 Feature。

    Phase 07 沒有 put_feature 這個介面（Feature 由 Phase 13、16 用 update_meta 維護），
    所以測試直接寫 item。
    """

    def _seed(feature_id: str, *, name: str | None = None) -> None:
        repo.put_meta(
            feature_pk(feature_id),
            {
                "entity": "FEATURE",
                "name": name or feature_id,
                "aliases": [],
                "first_seen": "2026-08-01T00:00:00Z",
            },
        )

    return _seed
```

再建立 `tests/integration/test_repository_tutorial.py`：

```python
"""Phase 07：Repository 的教學讀寫（用 moto 模擬 AWS）。"""

from training_kb.keys import feature_pk, step_pk, tutorial_pk, version_pk
from training_kb.models import Tutorial, TutorialStatus


def make_tutorial(**overrides) -> Tutorial:
    data = {
        "slug": "prepare-meeting",
        "current_version": None,
        "topic": "準備會議",
        "feature_ids": ["Prepare"],
        "status": TutorialStatus.active,
        "successor": None,
        "cluster_id": "c12",
    }
    data.update(overrides)
    return Tutorial(**data)


def test_教學寫入後讀回來一致(repo):
    tutorial = make_tutorial()

    assert repo.put_tutorial(tutorial, if_not_exists=True) is True
    assert repo.get_tutorial("prepare-meeting") == tutorial


def test_current_version_是_None_時不寫入該屬性(repo):
    repo.put_tutorial(make_tutorial(), if_not_exists=True)

    item = repo.get_meta(tutorial_pk("prepare-meeting"))

    assert "current_version" not in item
    assert "successor" not in item


def test_if_not_exists_已存在時不覆寫(repo):
    repo.put_tutorial(make_tutorial(), if_not_exists=True)

    changed = repo.put_tutorial(make_tutorial(topic="改掉的主題"), if_not_exists=True)

    assert changed is False
    assert repo.get_tutorial("prepare-meeting").topic == "準備會議"


def test_讀不到的教學回傳_None(repo):
    assert repo.get_tutorial("does-not-exist") is None
    assert repo.get_version("does-not-exist@v1") is None
    assert repo.get_feature("Nope") is None


def test_feature_讀寫與清單(repo, seed_feature):
    seed_feature("Prepare")
    seed_feature("Share Summary")

    prepare = repo.get_feature("Prepare")

    assert prepare.feature_id == "Prepare"
    assert prepare.name == "Prepare"
    assert [f.feature_id for f in repo.list_features()] == ["Prepare", "Share Summary"]


def test_版本與步驟讀回來依編號排序(repo, seed_feature):
    seed_feature("Prepare")
    version_id = "prepare-meeting@v1"
    repo.put_meta(
        version_pk(version_id),
        {
            "entity": "VERSION",
            "version_id": version_id,
            "slug": "prepare-meeting",
            "reason": "gap:c12",
            "rules_applied": [],
            "s3_key": "tutorials/prepare-meeting/v1.md",
            "step_count": 2,
        },
    )
    for index, text in ((2, "閱讀摘要"), (1, "開啟會議頁面")):
        repo.put_edge(
            step_pk(version_id, index),
            "REFERENCES",
            feature_pk("Prepare"),
            {
                "entity": "STEP",
                "tutorial_version": version_id,
                "index": index,
                "type": "click_ui",
                "text": text,
            },
        )

    version = repo.get_version(version_id)
    steps = repo.get_steps(version_id)

    assert version.supersedes is None
    assert version.published_at is None
    assert version.s3_key == "tutorials/prepare-meeting/v1.md"
    assert [step.index for step in steps] == [1, 2]
    assert [step.text for step in steps] == ["開啟會議頁面", "閱讀摘要"]
    assert [step.feature_id for step in steps] == ["Prepare", "Prepare"]
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：

```bash
uv run pytest tests/integration/test_repository_tutorial.py -v
```

預期：FAIL，`AttributeError: 'Repository' object has no attribute 'put_tutorial'`。

- [ ] **步驟 3：寫最少的程式讓測試通過**

在 `src/training_kb/repository.py` 的 import 區塊補上：

```python
from training_kb.keys import feature_pk, parse_pk, step_pk, tutorial_pk, version_pk
from training_kb.models import (
    Feature,
    Tutorial,
    TutorialStep,
    TutorialVersion,
)
```

在 `Repository` 類別裡面加上六個方法：

```python
    # ---- 固定讀取（Phase 07 用得到的部分；其餘由 Phase 09 補齊）----

    def get_tutorial(self, slug: str) -> Tutorial | None:
        item = self.get_meta(tutorial_pk(slug))
        if item is None:
            return None
        return Tutorial(
            slug=slug,
            current_version=item.get("current_version"),
            topic=item.get("topic", ""),
            feature_ids=list(item.get("feature_ids", [])),
            status=item.get("status", "active"),
            successor=item.get("successor"),
            cluster_id=item.get("cluster_id"),
        )

    def put_tutorial(self, t: Tutorial, *, if_not_exists: bool = False) -> bool:
        """寫入教學 metadata。

        值是 None 的欄位一律不寫進 item（不寫 DynamoDB 的 NULL 型別），
        這樣 Phase 08 的 publish 才能用 attribute_not_exists 判斷「還沒發布過」。
        """
        attrs: dict = {
            "entity": "TUTORIAL",
            "slug": t.slug,
            "topic": t.topic,
            "feature_ids": list(t.feature_ids),
            "status": str(t.status),
        }
        if t.current_version is not None:
            attrs["current_version"] = t.current_version
        if t.successor is not None:
            attrs["successor"] = t.successor
        if t.cluster_id is not None:
            attrs["cluster_id"] = t.cluster_id
        return self.put_meta(tutorial_pk(t.slug), attrs, if_not_exists=if_not_exists)

    def get_version(self, version_id: str) -> TutorialVersion | None:
        item = self.get_meta(version_pk(version_id))
        if item is None:
            return None
        return TutorialVersion(
            version_id=version_id,
            supersedes=item.get("supersedes"),
            reason=item.get("reason", ""),
            rules_applied=list(item.get("rules_applied", [])),
            s3_key=item.get("s3_key", ""),
            published_at=item.get("published_at"),
        )

    def get_steps(self, version_id: str) -> list[TutorialStep]:
        """依步驟編號讀出這一版的步驟。

        每一步是獨立的 PK（STEP#<slug>@v<n>#<i>），沒辦法一次 Query 全部撈出來，
        所以從 VERSION item 的 step_count 得知要讀到第幾號。
        """
        meta = self.get_meta(version_pk(version_id))
        if meta is None:
            return []
        count = int(meta.get("step_count", 0))
        steps: list[TutorialStep] = []
        for index in range(1, count + 1):
            rows = self.query_pk(step_pk(version_id, index))
            if not rows:
                continue
            row = rows[0]
            steps.append(
                TutorialStep(
                    tutorial_version=version_id,
                    index=index,
                    type=row.get("type"),
                    text=row.get("text", ""),
                    feature_id=parse_pk(row.get("target", ""))[1],
                )
            )
        return steps

    def get_feature(self, feature_id: str) -> Feature | None:
        item = self.get_meta(feature_pk(feature_id))
        if item is None:
            return None
        return Feature(
            feature_id=feature_id,
            name=item.get("name", feature_id),
            aliases=list(item.get("aliases", [])),
            first_seen=item.get("first_seen", ""),
        )

    def list_features(self) -> list[Feature]:
        features: list[Feature] = []
        for item in self.scan_entity("FEATURE"):
            feature_id = parse_pk(item["PK"])[1]
            features.append(
                Feature(
                    feature_id=feature_id,
                    name=item.get("name", feature_id),
                    aliases=list(item.get("aliases", [])),
                    first_seen=item.get("first_seen", ""),
                )
            )
        return sorted(features, key=lambda feature: feature.feature_id)
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：

```bash
uv run pytest tests/integration/test_repository_tutorial.py -v
```

預期：PASS，6 個 `PASSED`。

- [ ] **步驟 5：commit**

```bash
git add src/training_kb/repository.py tests/integration/conftest.py tests/integration/test_repository_tutorial.py
git commit -m "feat(repository): 補上教學、版本、步驟與功能的固定讀取"
```

---

### Task 5：建立教學身分與配發版號

**目的**：寫出 `create_tutorial` 與 `allocate_version`。同一個 `operation_id` 重試時必須拿到同一個版號（D26）。

**檔案**：
- 修改：`src/training_kb/content.py`
- 測試：`tests/integration/test_content_allocate.py`

**介面**：
- 消費：`Repository.begin_operation`、`load_operation`、`update_operation`、`update_meta`（Phase 03）
- 消費：`Repository.get_tutorial`、`put_tutorial`（Task 4）
- 消費：`training_kb.clock.to_iso`（Phase 01）
- 產出：`training_kb.content.VersionPlan`（dataclass：`slug`、`version_id`、`n`、`supersedes`、`reason`、`rules_applied`、`operation_id`）
- 產出：`training_kb.content.create_tutorial(repo, *, slug, topic, feature_ids, cluster_id, now) -> Tutorial`
- 產出：`training_kb.content.allocate_version(repo, slug, operation_id, reason, rules_applied) -> VersionPlan`

- [ ] **步驟 1：寫測試**

建立 `tests/integration/test_content_allocate.py`：

```python
"""Phase 07：教學身分與版號配發（用 moto 模擬 AWS）。"""

from datetime import datetime, timezone

import pytest

from training_kb.content import allocate_version, create_tutorial
from training_kb.errors import ContentError
from training_kb.keys import tutorial_pk
from training_kb.models import TutorialStatus

NOW = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


def new_tutorial(repo, slug: str = "prepare-meeting", cluster_id: str = "c12"):
    return create_tutorial(
        repo,
        slug=slug,
        topic="準備會議",
        feature_ids=["Prepare"],
        cluster_id=cluster_id,
        now=NOW,
    )


def test_建立的教學是_active_且尚未發布(repo):
    tutorial = new_tutorial(repo)

    assert tutorial.status == TutorialStatus.active
    assert tutorial.current_version is None
    assert tutorial.cluster_id == "c12"
    assert repo.get_tutorial("prepare-meeting") == tutorial


def test_重複建立同一篇教學回傳既有資料(repo):
    first = new_tutorial(repo)
    repo.update_meta(tutorial_pk("prepare-meeting"), {"topic": "改過的主題"})

    second = new_tutorial(repo)

    assert second.slug == first.slug
    assert second.topic == "改過的主題"


def test_同_slug_但不同_cluster_時拒絕(repo):
    new_tutorial(repo)

    with pytest.raises(ContentError) as exc:
        new_tutorial(repo, cluster_id="c99")

    assert "不同的 cluster" in str(exc.value)


def test_第一版的版號是_v1_而且沒有前版(repo):
    new_tutorial(repo)

    plan = allocate_version(repo, "prepare-meeting", "op-create-1", "gap:c12", [])

    assert plan.version_id == "prepare-meeting@v1"
    assert plan.n == 1
    assert plan.supersedes is None
    assert plan.reason == "gap:c12"
    assert plan.operation_id == "op-create-1"


def test_同一個_operation_id_重試拿到同一個版號(repo):
    new_tutorial(repo)
    first = allocate_version(repo, "prepare-meeting", "op-create-1", "gap:c12", ["R-007"])

    second = allocate_version(repo, "prepare-meeting", "op-create-1", "gap:c99", [])

    assert second.version_id == first.version_id
    assert second.supersedes == first.supersedes
    assert second.reason == "gap:c12"
    assert second.rules_applied == ["R-007"]


def test_已發布_v1_之後下一版是_v2(repo):
    new_tutorial(repo)
    # publish 是 Phase 08 的事，這裡直接把 current_version 設成已發布的 v1。
    repo.update_meta(
        tutorial_pk("prepare-meeting"), {"current_version": "prepare-meeting@v1"}
    )

    plan = allocate_version(repo, "prepare-meeting", "op-release-42", "release:r_42", [])

    assert plan.version_id == "prepare-meeting@v2"
    assert plan.supersedes == "prepare-meeting@v1"


def test_不同的_operation_id_在同一個基底上拿到同一個版號(repo):
    """未發布的失敗版本不會把基底往前推（D26：可以留下號碼缺口）。"""
    new_tutorial(repo)
    first = allocate_version(repo, "prepare-meeting", "op-a", "gap:c12", [])

    second = allocate_version(repo, "prepare-meeting", "op-b", "gap:c12", [])

    assert first.version_id == "prepare-meeting@v1"
    assert second.version_id == "prepare-meeting@v1"


def test_教學不存在時拒絕配發版號(repo):
    with pytest.raises(ContentError) as exc:
        allocate_version(repo, "no-such-tutorial", "op-x", "gap:c12", [])

    assert "找不到教學" in str(exc.value)


def test_同一個_operation_id_不可以用在另一篇教學(repo):
    new_tutorial(repo)
    new_tutorial(repo, slug="share-summary", cluster_id="c13")
    allocate_version(repo, "prepare-meeting", "op-shared", "gap:c12", [])

    with pytest.raises(ContentError) as exc:
        allocate_version(repo, "share-summary", "op-shared", "gap:c13", [])

    assert "不能再用在" in str(exc.value)
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：

```bash
uv run pytest tests/integration/test_content_allocate.py -v
```

預期：FAIL，`ImportError: cannot import name 'allocate_version' from 'training_kb.content'`。

- [ ] **步驟 3：寫最少的程式讓測試通過**

在 `src/training_kb/content.py` 的 import 區塊補上：

```python
from dataclasses import dataclass
from datetime import datetime

from training_kb.clock import to_iso
from training_kb.keys import tutorial_pk
from training_kb.models import (
    StepType,
    Tutorial,
    TutorialContent,
    TutorialStatus,
    TutorialVersion,
    make_version_id,
    parse_version_id,
)
from training_kb.repository import Repository
```

在 `LEGAL_STEP_TYPES` 後面加上 dataclass：

```python
@dataclass
class VersionPlan:
    """這一次要寫的版本。由 allocate_version 產生，create_version 照著做。"""

    slug: str
    version_id: str
    n: int
    supersedes: str | None
    reason: str
    rules_applied: list[str]
    operation_id: str
```

在 `make_diff` 後面加上兩個函式：

```python
def create_tutorial(
    repo: Repository,
    *,
    slug: str,
    topic: str,
    feature_ids: list[str],
    cluster_id: str,
    now: datetime,
) -> Tutorial:
    """建立一篇教學的身分。status=active、current_version=None（還沒有任何版本上架）。

    只有 Ticket Analysis 可以建立新的 Tutorial 身分（分析工單 Rule 10）。
    重複呼叫時回傳既有教學，但如果來源 cluster 不同就拒絕，避免兩個不同的
    Knowledge Gap 共用同一個 slug（D29 要求 cluster 對應可追溯）。
    """
    tutorial = Tutorial(
        slug=slug,
        current_version=None,
        topic=topic,
        feature_ids=list(feature_ids),
        status=TutorialStatus.active,
        successor=None,
        cluster_id=cluster_id,
    )
    created = repo.put_tutorial(tutorial, if_not_exists=True)
    if created:
        # created_at 不是 ERM 欄位，只是方便追溯的執行資訊，所以分開寫。
        repo.update_meta(tutorial_pk(slug), {"created_at": to_iso(now)})
        return tutorial

    existing = repo.get_tutorial(slug)
    if existing is None:
        raise ContentError(f"教學 {slug} 的寫入被拒絕，但也讀不到既有資料")
    if existing.cluster_id != cluster_id:
        raise ContentError(
            f"教學 {slug} 已存在，且來自不同的 cluster：{existing.cluster_id}"
        )
    return existing


def allocate_version(
    repo: Repository,
    slug: str,
    operation_id: str,
    reason: str,
    rules_applied: list[str],
) -> VersionPlan:
    """決定這一次要寫第幾版。

    1. 先讀操作紀錄。同一個 operation_id 重試時回傳原本配到的版號（D26）。
    2. 沒有紀錄才配新號：以「最近的已發布版本」為基底加一。
       Tutorial.current_version 只有 publish 成功才會更新（F37），所以它就是基底。
       寫到一半永久失敗的未發布版本不會把基底往前推，版號因此可能出現缺口，
       這是 D26 允許的。
    """
    record = repo.load_operation(operation_id) or {}
    existing_version_id = record.get("version_id")
    if existing_version_id:
        recorded_slug, n = parse_version_id(existing_version_id)
        if recorded_slug != slug:
            raise ContentError(
                f"操作 {operation_id} 已經分配給教學 {recorded_slug}，不能再用在 {slug}"
            )
        return VersionPlan(
            slug=slug,
            version_id=existing_version_id,
            n=n,
            supersedes=record.get("supersedes"),
            reason=record.get("reason", reason),
            rules_applied=list(record.get("rules_applied", rules_applied)),
            operation_id=operation_id,
        )

    tutorial = repo.get_tutorial(slug)
    if tutorial is None:
        raise ContentError(f"找不到教學：{slug}")

    base = tutorial.current_version
    if base is None:
        n = 1
        supersedes = None
    else:
        base_slug, base_n = parse_version_id(base)
        if base_slug != slug:
            raise ContentError(f"教學 {slug} 的 current_version 不屬於這篇：{base}")
        n = base_n + 1
        supersedes = base

    version_id = make_version_id(slug, n)
    if not record:
        repo.begin_operation(
            operation_id,
            {"operation_id": operation_id, "kind": "create_version", "slug": slug},
        )
    repo.update_operation(
        operation_id,
        {
            "slug": slug,
            "version_id": version_id,
            "supersedes": supersedes,
            "reason": reason,
            "rules_applied": list(rules_applied),
        },
    )
    return VersionPlan(
        slug=slug,
        version_id=version_id,
        n=n,
        supersedes=supersedes,
        reason=reason,
        rules_applied=list(rules_applied),
        operation_id=operation_id,
    )
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：

```bash
uv run pytest tests/integration/test_content_allocate.py -v
```

預期：PASS，9 個 `PASSED`。

- [ ] **步驟 5：commit**

```bash
git add src/training_kb/content.py tests/integration/test_content_allocate.py
git commit -m "feat(content): 建立教學身分並配發可重試的版本號"
```

---

### Task 6：核對一個版本是不是寫齊了

**目的**：寫出 `verify_version_complete`。它回傳「缺了什麼」的清單，空清單代表齊全、可以進 publish（F36）。

**檔案**：
- 修改：`src/training_kb/content.py`
- 測試：`tests/integration/test_content_verify.py`

**介面**：
- 消費：`Repository.get_meta`、`query_pk`、`object_exists`、`get_tutorial`、`get_feature`
- 消費：`training_kb.keys.parse_pk`、`rule_pk`、`step_pk`、`version_pk`
- 產出：`training_kb.content.verify_version_complete(repo, version_id: str) -> list[str]`

- [ ] **步驟 1：寫測試**

建立 `tests/integration/test_content_verify.py`：

```python
"""Phase 07：版本完整性核對（用 moto 模擬 AWS）。"""

from datetime import datetime, timezone

from training_kb.content import create_tutorial, verify_version_complete, version_keys
from training_kb.keys import rule_pk, step_pk, version_pk
from training_kb.repository import Repository

NOW = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


def write_full_version(
    repo: Repository,
    *,
    slug: str = "prepare-meeting",
    n: int = 1,
    supersedes: str | None = None,
    rules_applied: tuple[str, ...] = (),
) -> str:
    """不透過 create_version，手動把一個完整版本的產物與 item 寫齊。"""
    version_id = f"{slug}@v{n}"
    keys = version_keys(slug, n)
    repo.put_object(keys["md"], f"# 第 {n} 版\n")
    repo.put_object(keys["diff"], "")
    attrs = {
        "entity": "VERSION",
        "version_id": version_id,
        "slug": slug,
        "reason": "gap:c12",
        "rules_applied": list(rules_applied),
        "s3_key": keys["md"],
        "step_count": 2,
    }
    if supersedes is not None:
        attrs["supersedes"] = supersedes
    repo.put_meta(version_pk(version_id), attrs)
    for index in (1, 2):
        repo.put_edge(
            step_pk(version_id, index),
            "REFERENCES",
            "FEATURE#Prepare",
            {
                "entity": "STEP",
                "tutorial_version": version_id,
                "index": index,
                "type": "click_ui",
                "text": f"第 {index} 步",
            },
        )
    if supersedes is not None:
        repo.put_edge(version_pk(version_id), "SUPERSEDES", version_pk(supersedes))
    for rule_id in rules_applied:
        repo.put_edge(rule_pk(rule_id), "APPLIED_TO", version_pk(version_id))
    return version_id


def prepare(repo, seed_feature):
    seed_feature("Prepare")
    create_tutorial(
        repo,
        slug="prepare-meeting",
        topic="準備會議",
        feature_ids=["Prepare"],
        cluster_id="c12",
        now=NOW,
    )


def test_完整的版本回傳空清單(repo, seed_feature):
    prepare(repo, seed_feature)
    version_id = write_full_version(repo)

    assert verify_version_complete(repo, version_id) == []


def test_沒有_version_item_時直接回報(repo, seed_feature):
    prepare(repo, seed_feature)

    missing = verify_version_complete(repo, "prepare-meeting@v9")

    assert missing == ["缺少 VERSION item：prepare-meeting@v9"]


def test_缺少_s3_全文時回報(repo, seed_feature):
    prepare(repo, seed_feature)
    version_id = write_full_version(repo)
    repo.s3.delete_object(
        Bucket=repo.bucket, Key=version_keys("prepare-meeting", 1)["md"]
    )

    missing = verify_version_complete(repo, version_id)

    assert "缺少 S3 全文：tutorials/prepare-meeting/v1.md" in missing


def test_缺少步驟時回報(repo, seed_feature):
    prepare(repo, seed_feature)
    version_id = write_full_version(repo)
    repo.table.delete_item(
        Key={"PK": step_pk(version_id, 2), "SK": "REFERENCES#FEATURE#Prepare"}
    )

    missing = verify_version_complete(repo, version_id)

    assert "缺少第 2 步" in missing


def test_步驟引用不存在的_feature_時回報(repo, seed_feature):
    prepare(repo, seed_feature)
    version_id = write_full_version(repo)
    repo.put_edge(
        step_pk(version_id, 1),
        "REFERENCES",
        "FEATURE#Ghost",
        {"entity": "STEP", "index": 1, "type": "click_ui", "text": "第 1 步"},
    )
    repo.table.delete_item(
        Key={"PK": step_pk(version_id, 1), "SK": "REFERENCES#FEATURE#Prepare"}
    )

    missing = verify_version_complete(repo, version_id)

    assert "第 1 步引用的 Feature 不存在：Ghost" in missing


def test_缺少_supersedes_邊時回報(repo, seed_feature):
    prepare(repo, seed_feature)
    write_full_version(repo, n=1)
    version_id = write_full_version(repo, n=2, supersedes="prepare-meeting@v1")
    repo.table.delete_item(
        Key={"PK": version_pk(version_id), "SK": "SUPERSEDES#VERSION#prepare-meeting@v1"}
    )

    missing = verify_version_complete(repo, version_id)

    assert "缺少 SUPERSEDES 邊：SUPERSEDES#VERSION#prepare-meeting@v1" in missing


def test_缺少_applied_to_邊時回報(repo, seed_feature):
    prepare(repo, seed_feature)
    version_id = write_full_version(repo, rules_applied=("R-007",))
    repo.table.delete_item(
        Key={"PK": rule_pk("R-007"), "SK": f"APPLIED_TO#{version_pk(version_id)}"}
    )

    missing = verify_version_complete(repo, version_id)

    assert "規則 R-007 缺少 APPLIED_TO 邊：APPLIED_TO#VERSION#prepare-meeting@v1" in missing
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：

```bash
uv run pytest tests/integration/test_content_verify.py -v
```

預期：FAIL，`ImportError: cannot import name 'verify_version_complete' from 'training_kb.content'`。

- [ ] **步驟 3：寫最少的程式讓測試通過**

在 `src/training_kb/content.py` 的 keys import 改成：

```python
from training_kb.keys import parse_pk, rule_pk, step_pk, tutorial_pk, version_pk
```

在 `allocate_version` 後面加上：

```python
def verify_version_complete(repo: Repository, version_id: str) -> list[str]:
    """核對這一版的 S3 產物、VERSION item、STEP item 與三種關係邊是否齊全。

    回傳缺漏說明清單；空清單代表齊全，可以進 publish（F36、設計文件 §8.2）。
    全部使用基表一致讀取，不走 GSI，因為 GSI 只有最終一致讀取，剛寫入的邊可能
    還看不到（設計文件 §10）。
    """
    missing: list[str] = []
    slug, n = parse_version_id(version_id)
    keys = version_keys(slug, n)

    meta = repo.get_meta(version_pk(version_id))
    if meta is None:
        return [f"缺少 VERSION item：{version_id}"]

    if repo.get_tutorial(slug) is None:
        missing.append(f"缺少 TUTORIAL item：{slug}")

    s3_key = meta.get("s3_key")
    if s3_key != keys["md"]:
        missing.append(f"s3_key 應為 {keys['md']}，實際是 {s3_key}")
    elif not repo.object_exists(keys["md"]):
        missing.append(f"缺少 S3 全文：{keys['md']}")
    if not repo.object_exists(keys["diff"]):
        missing.append(f"缺少 S3 差異檔：{keys['diff']}")

    step_count = int(meta.get("step_count", 0))
    if step_count <= 0:
        missing.append("這一版沒有任何步驟")
    for index in range(1, step_count + 1):
        rows = repo.query_pk(step_pk(version_id, index))
        if not rows:
            missing.append(f"缺少第 {index} 步")
            continue
        if len(rows) != 1:
            missing.append(f"第 {index} 步有 {len(rows)} 條引用邊，應該恰好一條")
            continue
        row = rows[0]
        target = row.get("target", "")
        if not target.startswith("FEATURE#"):
            missing.append(f"第 {index} 步的引用終點不是 Feature：{target}")
            continue
        if row.get("SK") != f"REFERENCES#{target}":
            missing.append(
                f"第 {index} 步的 SK 與 target 不一致：{row.get('SK')} / {target}"
            )
            continue
        feature_id = parse_pk(target)[1]
        if repo.get_feature(feature_id) is None:
            missing.append(f"第 {index} 步引用的 Feature 不存在：{feature_id}")

    supersedes = meta.get("supersedes")
    if supersedes:
        expected = f"SUPERSEDES#{version_pk(supersedes)}"
        edges = repo.query_pk(version_pk(version_id), sk_prefix="SUPERSEDES#")
        if not any(edge.get("SK") == expected for edge in edges):
            missing.append(f"缺少 SUPERSEDES 邊：{expected}")

    expected_applied = f"APPLIED_TO#{version_pk(version_id)}"
    for rule_id in list(meta.get("rules_applied", [])):
        edges = repo.query_pk(rule_pk(rule_id), sk_prefix="APPLIED_TO#")
        if not any(edge.get("SK") == expected_applied for edge in edges):
            missing.append(f"規則 {rule_id} 缺少 APPLIED_TO 邊：{expected_applied}")

    return missing
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：

```bash
uv run pytest tests/integration/test_content_verify.py -v
```

預期：PASS，7 個 `PASSED`。

- [ ] **步驟 5：commit**

```bash
git add src/training_kb/content.py tests/integration/test_content_verify.py
git commit -m "feat(content): 核對版本的全文、步驟與關係是否齊全"
```

---

### Task 7：把一整版寫下去

**目的**：寫出 `create_version`。它把前面六個 Task 的零件串起來，照設計文件 §8.2 的順序寫 S3 與 DynamoDB，最後自己核對一次。

**檔案**：
- 修改：`src/training_kb/content.py`
- 測試：`tests/integration/test_content_create_version.py`

**介面**：
- 消費：`Repository.put_object`、`get_object`、`put_meta`、`put_edge`、`list_features`、`get_version`
- 產出：`training_kb.content.create_version(repo, plan: VersionPlan, content: TutorialContent, *, now: datetime) -> TutorialVersion`

- [ ] **步驟 1：寫測試**

建立 `tests/integration/test_content_create_version.py`：

```python
"""Phase 07：create_version 的整合測試（用 moto 模擬 AWS）。"""

from datetime import datetime, timezone

import pytest

from training_kb.content import (
    allocate_version,
    create_tutorial,
    create_version,
    version_keys,
)
from training_kb.errors import ContentError
from training_kb.keys import tutorial_pk, version_pk
from training_kb.models import StepDraft, StepType, TutorialContent

NOW = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


def make_content(step_text: str = "開啟會議頁面") -> TutorialContent:
    return TutorialContent(
        title="準備會議",
        problem="使用者找不到會前摘要",
        prerequisites=["已登入"],
        steps=[
            StepDraft(type=StepType.click_ui, text=step_text, feature_id="Prepare"),
            StepDraft(type=StepType.read, text="閱讀右側摘要", feature_id="Prepare"),
        ],
        expected_outcome="看到會前摘要",
    )


def prepare(repo, seed_feature):
    seed_feature("Prepare")
    create_tutorial(
        repo,
        slug="prepare-meeting",
        topic="準備會議",
        feature_ids=["Prepare"],
        cluster_id="c12",
        now=NOW,
    )


def test_建立_v1_後未發布且_diff_是空檔(repo, seed_feature):
    prepare(repo, seed_feature)
    plan = allocate_version(repo, "prepare-meeting", "op-1", "gap:c12", ["R-007"])

    version = create_version(repo, plan, make_content(), now=NOW)

    keys = version_keys("prepare-meeting", 1)
    assert version.version_id == "prepare-meeting@v1"
    assert version.published_at is None
    assert version.supersedes is None
    assert version.reason == "gap:c12"
    assert version.rules_applied == ["R-007"]
    assert version.s3_key == keys["md"]
    assert repo.get_object(keys["diff"]) == b""
    assert repo.get_object(keys["md"]).decode("utf-8").startswith("# 準備會議\n")


def test_建立_v1_同時寫下步驟與引用邊(repo, seed_feature):
    prepare(repo, seed_feature)
    plan = allocate_version(repo, "prepare-meeting", "op-1", "gap:c12", [])

    create_version(repo, plan, make_content(), now=NOW)

    steps = repo.get_steps("prepare-meeting@v1")
    assert [step.index for step in steps] == [1, 2]
    assert [step.feature_id for step in steps] == ["Prepare", "Prepare"]
    assert [str(step.type) for step in steps] == ["click_ui", "read"]


def test_建立_v2_時有_supersedes_邊與非空_diff(repo, seed_feature):
    prepare(repo, seed_feature)
    plan1 = allocate_version(repo, "prepare-meeting", "op-1", "gap:c12", [])
    create_version(repo, plan1, make_content(), now=NOW)
    repo.update_meta(
        version_pk("prepare-meeting@v1"), {"published_at": "2026-08-01T00:00:00Z"}
    )
    repo.update_meta(
        tutorial_pk("prepare-meeting"), {"current_version": "prepare-meeting@v1"}
    )
    plan2 = allocate_version(repo, "prepare-meeting", "op-2", "release:r_42", [])

    version = create_version(repo, plan2, make_content("開啟新的會議頁面"), now=NOW)

    diff = repo.get_object(version_keys("prepare-meeting", 2)["diff"]).decode("utf-8")
    assert version.version_id == "prepare-meeting@v2"
    assert version.supersedes == "prepare-meeting@v1"
    assert diff.splitlines()[0] == "--- tutorials/prepare-meeting/v1.md"
    assert "+1. (type=click_ui, feature=Prepare) 開啟新的會議頁面" in diff
    edges = repo.query_pk(version_pk("prepare-meeting@v2"), sk_prefix="SUPERSEDES#")
    assert edges[0]["target"] == version_pk("prepare-meeting@v1")


def test_零個_feature_的步驟不會被寫下去(repo, seed_feature):
    prepare(repo, seed_feature)
    plan = allocate_version(repo, "prepare-meeting", "op-1", "gap:c12", [])
    bad = TutorialContent(
        title="準備會議",
        problem="問題",
        prerequisites=["已登入"],
        steps=[StepDraft(type=StepType.click_ui, text="按一下", feature_id=" ")],
        expected_outcome="結果",
    )

    with pytest.raises(ContentError):
        create_version(repo, plan, bad, now=NOW)

    assert repo.get_version("prepare-meeting@v1") is None
    assert repo.get_object(version_keys("prepare-meeting", 1)["md"]) is None


def test_多個_feature_的步驟不會被寫下去(repo, seed_feature):
    prepare(repo, seed_feature)
    seed_feature("Share Summary")
    plan = allocate_version(repo, "prepare-meeting", "op-1", "gap:c12", [])
    bad = TutorialContent(
        title="準備會議",
        problem="問題",
        prerequisites=["已登入"],
        steps=[
            StepDraft(
                type=StepType.click_ui, text="按一下", feature_id="Prepare,Share Summary"
            )
        ],
        expected_outcome="結果",
    )

    with pytest.raises(ContentError) as exc:
        create_version(repo, plan, bad, now=NOW)

    assert "引用了多個 Feature" in str(exc.value)
    assert repo.get_version("prepare-meeting@v1") is None


def test_S3_已存在同_key_且內容相同時視為成功(repo, seed_feature):
    prepare(repo, seed_feature)
    plan = allocate_version(repo, "prepare-meeting", "op-1", "gap:c12", [])
    create_version(repo, plan, make_content(), now=NOW)

    # 完全一樣的重試：版號一樣、內容一樣，應該再次成功。
    again = create_version(repo, plan, make_content(), now=NOW)

    assert again.version_id == "prepare-meeting@v1"


def test_S3_已存在同_key_但內容不同時拒絕(repo, seed_feature):
    prepare(repo, seed_feature)
    plan = allocate_version(repo, "prepare-meeting", "op-1", "gap:c12", [])
    repo.put_object(version_keys("prepare-meeting", 1)["md"], "# 別人寫的東西\n")

    with pytest.raises(ContentError) as exc:
        create_version(repo, plan, make_content(), now=NOW)

    assert "內容不同，不覆寫" in str(exc.value)


def test_已發布的版本不可覆寫(repo, seed_feature):
    prepare(repo, seed_feature)
    plan = allocate_version(repo, "prepare-meeting", "op-1", "gap:c12", [])
    create_version(repo, plan, make_content(), now=NOW)
    repo.update_meta(
        version_pk("prepare-meeting@v1"), {"published_at": "2026-08-01T00:00:00Z"}
    )

    with pytest.raises(ContentError) as exc:
        create_version(repo, plan, make_content("改過的文字"), now=NOW)

    assert "已發布，不可覆寫" in str(exc.value)
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：

```bash
uv run pytest tests/integration/test_content_create_version.py -v
```

預期：FAIL，`ImportError: cannot import name 'create_version' from 'training_kb.content'`。

- [ ] **步驟 3：寫最少的程式讓測試通過**

在 `src/training_kb/content.py` 的 import 區塊補上 `feature_pk`：

```python
from training_kb.keys import (
    feature_pk,
    parse_pk,
    rule_pk,
    step_pk,
    tutorial_pk,
    version_pk,
)
```

在 `verify_version_complete` 後面加上兩個函式：

```python
def _put_artifact(repo: Repository, key: str, body: str, content_type: str) -> None:
    """把產物寫進 S3 私有區。

    設計文件 §8.3：同一個 key 已存在時，要核對它是不是本次相同的產物，
    而不是盲目重寫。所以先讀出來比對；不同就拒絕，相同就當成這次重試已完成。
    """
    data = body.encode("utf-8")
    existing = repo.get_object(key)
    if existing is not None:
        if existing != data:
            raise ContentError(f"S3 已有同一個 key 但內容不同，不覆寫：{key}")
        return
    created = repo.put_object(key, data, if_none_match=True, content_type=content_type)
    if created:
        return
    # 條件寫入失敗代表在我們讀完之後、寫之前有人先寫了，再核對一次內容。
    again = repo.get_object(key)
    if again != data:
        raise ContentError(f"S3 已有同一個 key 但內容不同，不覆寫：{key}")


def create_version(
    repo: Repository,
    plan: VersionPlan,
    content: TutorialContent,
    *,
    now: datetime,
) -> TutorialVersion:
    """建立一個未發布的教學版本（設計文件 §8.2）。

    順序固定：驗證 -> 寫 S3 私有產物 -> 寫 DynamoDB -> 自己核對。
    中途失敗時不刪除已寫好的 S3 產物：它在私有區，外面讀不到，留著讓重試沿用
    （F36）。published_at 一律不寫，代表未發布（D25）。
    """
    existing = repo.get_version(plan.version_id)
    if existing is not None and existing.published_at is not None:
        raise ContentError(f"版本 {plan.version_id} 已發布，不可覆寫（設計文件 §8.2）")

    known_feature_ids = {feature.feature_id for feature in repo.list_features()}
    validate_content(content, known_feature_ids)

    keys = version_keys(plan.slug, plan.n)
    new_md = render_markdown(content)

    prev_md: str | None = None
    prev_name = ""
    if plan.supersedes is not None:
        previous = repo.get_version(plan.supersedes)
        if previous is None:
            raise ContentError(f"找不到前一版：{plan.supersedes}")
        raw = repo.get_object(previous.s3_key)
        if raw is None:
            raise ContentError(f"找不到前一版的全文：{previous.s3_key}")
        prev_md = raw.decode("utf-8")
        prev_slug, prev_n = parse_version_id(plan.supersedes)
        prev_name = version_keys(prev_slug, prev_n)["md"]
    diff_text = make_diff(prev_md, new_md, prev_name, keys["md"])

    _put_artifact(repo, keys["md"], new_md, "text/markdown; charset=utf-8")
    _put_artifact(repo, keys["diff"], diff_text, "text/plain; charset=utf-8")

    attrs: dict = {
        "entity": "VERSION",
        "version_id": plan.version_id,
        "slug": plan.slug,
        "reason": plan.reason,
        "rules_applied": list(plan.rules_applied),
        "s3_key": keys["md"],
        "step_count": len(content.steps),
        "created_at": to_iso(now),
    }
    if plan.supersedes is not None:
        attrs["supersedes"] = plan.supersedes
    repo.put_meta(version_pk(plan.version_id), attrs)

    for index, step in enumerate(content.steps, start=1):
        repo.put_edge(
            step_pk(plan.version_id, index),
            "REFERENCES",
            feature_pk(step.feature_id),
            {
                "entity": "STEP",
                "tutorial_version": plan.version_id,
                "index": index,
                "type": str(step.type),
                "text": step.text,
            },
        )

    if plan.supersedes is not None:
        repo.put_edge(
            version_pk(plan.version_id), "SUPERSEDES", version_pk(plan.supersedes)
        )

    for rule_id in plan.rules_applied:
        repo.put_edge(rule_pk(rule_id), "APPLIED_TO", version_pk(plan.version_id))

    missing = verify_version_complete(repo, plan.version_id)
    if missing:
        raise ContentError("版本建立後核對失敗：" + "；".join(missing))

    version = repo.get_version(plan.version_id)
    if version is None:
        raise ContentError(f"版本 {plan.version_id} 寫入後讀不回來")
    return version
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：

```bash
uv run pytest tests/integration/test_content_create_version.py -v
uv run pytest -q
uv run ruff check .
uv run ruff format .
```

預期：新測試 8 個 `PASSED`；整包測試全部通過；`ruff check` 顯示 `All checks passed!`。

- [ ] **步驟 5：commit**

```bash
git add src/training_kb/content.py tests/integration/test_content_create_version.py
git commit -m "feat(content): 建立未發布的教學版本並核對完整性"
```

---

## 7. 完成檢查清單

- [ ] `src/training_kb/content.py` 提供 `LEGAL_STEP_TYPES`、`VersionPlan`、`version_keys`、`render_markdown`、`validate_content`、`make_diff`、`create_tutorial`、`allocate_version`、`verify_version_complete`、`create_version`。
- [ ] `src/training_kb/repository.py` 多了 `get_tutorial`、`put_tutorial`、`get_version`、`get_steps`、`get_feature`、`list_features`。
- [ ] `tests/integration/conftest.py` 有 `seed_feature` fixture；`repo` fixture 仍然只有 Phase 03 的 `tests/conftest.py` 那一份（全專案不可以有兩個同名 fixture）。
- [ ] `uv run pytest -q` 整包通過。本階段新增 49 個測試（unit 19 個、integration 30 個）。
- [ ] `uv run ruff check .` 顯示 `All checks passed!`。
- [ ] 手動驗證版號重試會重用（對應設計文件第 15 節「版本與發布」列的「重試同版號」）：

```bash
uv run pytest tests/integration/test_content_allocate.py::test_同一個_operation_id_重試拿到同一個版號 -v
```

預期：`1 passed`。

- [ ] 手動驗證 v1 的 diff 是空檔（F50）：

```bash
uv run pytest "tests/integration/test_content_create_version.py::test_建立_v1_後未發布且_diff_是空檔" -v
```

預期：`1 passed`。

- [ ] 對應設計文件第 16 節切片 S2 的手動檢查「工單達門檻後建立未發布 v1」：本階段完成的是「建立未發布 v1」這一半，`published_at` 讀出來是 `None`，`Tutorial.current_version` 仍是 `None`。工單門檻那一半在 Phase 13。
- [ ] 對應設計文件第 15 節「全文與步驟」列：五段齊全、每步零／一／多 Feature、非法步驟型態、schema 合法但引用不存在時拒絕，四種案例都有測試。

---

## 8. 常見錯誤與排除

**症狀 1：`botocore.exceptions.NoCredentialsError: Unable to locate credentials`**

原因：moto 需要環境變數裡有（假的）AWS 憑證，測試沒有設定。

解法：確認 `tests/integration/conftest.py` 的 `repo` fixture 有 `monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")` 那幾行，而且它們在 `with mock_aws():` **之前**執行。

---

**症狀 2：`ImportError: cannot import name 'mock_aws' from 'moto'`**

原因：moto 是 4.x 版。`mock_aws` 是 moto 5 才有的統一入口，4.x 用的是 `mock_dynamodb`、`mock_s3`。

解法：執行 `uv add --dev "moto[s3,dynamodb]>=5"`，再 `uv sync`。

---

**症狀 3：`test_S3_已存在同_key_但內容不同時拒絕` 失敗，沒有拋出 ContentError**

原因：`Repository.put_object` 的 `if_none_match` 沒有真的送出 `IfNoneMatch='*'`，或 moto 版本太舊不認得這個參數，於是直接覆寫了。

解法：檢查 Phase 03 的 `put_object` 是不是在 `if_none_match=True` 時傳 `IfNoneMatch="*"`，並且把 `PreconditionFailed`／HTTP 412 的錯誤轉成回傳 `False`。`_put_artifact` 在條件寫入之前會先讀一次，所以即使 moto 忽略了 `IfNoneMatch`，這個測試也應該通過；如果連前面那次讀取都沒抓到，代表 `get_object` 對不存在的 key 沒有回傳 `None`。

---

**症狀 3-1：`test_建立_v1_後未發布且_diff_是空檔` 失敗，`get_object` 對 `v1.diff` 回傳 `None`**

原因：v1 的 diff 是 0 位元組的空檔（F50）。Phase 03 的 `get_object` 如果寫成 `return body or None`，空檔就會被當成「不存在」。

解法：`get_object` 只能在 S3 回 `NoSuchKey` 時回傳 `None`；讀到 0 位元組時要回傳 `b""`。否則重試 `create_version` 時會把空的 diff 檔誤判成「內容不同」而拒絕。

---

**症狀 4：`create_version` 拋「版本建立後核對失敗：第 1 步引用的 Feature 不存在」**

原因：內容裡的 `feature_id` 是 Feature 的**顯示名稱**，不是 PK 後綴。D06 規定 Feature 的 PK 在第一次建立後就不變，改名只會改 `name` 與 `aliases`。例如 `Prepare` 改名成別的名字之後，`feature_id` 仍然是 `Prepare`。

解法：寫作 prompt 要求模型輸出的是 `feature_id`（PK 後綴），不是 `name`。用 `repo.list_features()` 檢查目前有哪些 `feature_id`。

---

**症狀 5：`allocate_version` 一直回傳 `v1`，即使前一版已經寫好了**

原因：前一版建立了，但還沒 publish，所以 `Tutorial.current_version` 還是 `None`。這是**正確行為**：基底是「最近的已發布版本」，未發布的版本不算（D26、F37）。

解法：如果你是在測試裡要模擬「v1 已發布」，就自己把 `current_version` 更新掉（Task 5 的測試就是這樣做的）；真正的切換是 Phase 08 的 `publish` 負責。

---

**症狀 6：`decimal.Decimal` 出現在 `step_count` 或步驟編號上，比較時不相等**

原因：DynamoDB 的數字讀回 Python 時是 `decimal.Decimal`，不是 `int`。`Decimal("2") == 2` 是 `True`，但 `range(1, Decimal("2") + 1)` 會出錯。

解法：讀出來之後一律用 `int(...)` 轉一次，程式碼裡的 `int(meta.get("step_count", 0))` 就是在做這件事。

---

**症狀 7：`ValidationError: Input should be 'click_ui', 'input' or 'read'`**

原因：在建立 `StepDraft` 時就傳了不合法的 `type`，pydantic 在建構的當下就擋下來了，還沒走到 `validate_content`。

解法：這是好事，代表兩道防線都在。如果你是在寫「模型輸出違反業務規則」的測試，要用 `StepDraft.model_construct(...)` 跳過 pydantic 驗證，才測得到 `validate_content` 那一道。

---

## 9. 這階段不做的事

| 不做的事 | 留給哪一階段 |
|---|---|
| publish（寫 `published_at`、切換 `current_version`、寫 `site/`） | Phase 08（`08-Phase08-Content-發布與退役.md`） |
| 退役（`status=retired`、successor 檢查） | Phase 08 |
| 產生公開 HTML 頁面 | Phase 08 最小版、Phase 22 完整版 |
| 取得同篇教學的寫入鎖（`with_tutorial_lock`） | Phase 08 |
| 其餘固定讀取：`find_feature_by_name_or_alias`、`list_versions_of_tutorial`、`find_active_tutorial_for_feature`、`list_feedback_of_version`、`backfill_references` 等 | Phase 09（`09-Phase09-圖譜查詢與backfill.md`） |
| 決定 `reason` 的內容（`gap:<cluster_id>`／`release:<id>`／`feedback:<n> 則 <category>`） | Phase 13、16、17 各自的流程 |
| 呼叫模型產生 `TutorialContent` | Phase 13（CREATE）、Phase 16（UPDATE）、Phase 17（REFINE） |
| 重試時重用「已保存的模型輸出」 | Phase 13 起的 pipeline。本階段只保證：同樣的 `content` 重跑會得到一模一樣的產物，所以重試不會產生第二份不同的全文（設計文件 §14.2）。 |
| 建立與改名 Feature、維護 `aliases` | Phase 13（建立）、Phase 16（改名） |

---

## 10. 對照：設計章節與 Rule 編號

### 10.1 `建立教學版本.feature`（10 條，全部屬於本階段）

| Rule 編號與原文 | 本階段哪個 Task 落實 |
|---|---|
| Rule 1「新 Tutorial 的版本從 v1 起算」 | Task 5（`current_version` 是 `None` 時 `n=1`） |
| Rule 2「任一 pipeline 修改既有教學時使用該篇的下一個版本號」 | Task 5（版號一律由 `allocate_version` 配發，pipeline 不自己算） |
| Rule 3「新版以 supersedes 關聯同一篇教學的前一版」 | Task 5（`plan.supersedes`）、Task 7（寫 `SUPERSEDES` 邊） |
| Rule 4「每次建立版本都記錄引起變更的 reason」 | Task 5（`reason` 進 `VersionPlan`）、Task 7（寫進 VERSION item） |
| Rule 5「每個版本的完整內容儲存在 `tutorials/<slug>/v<n>.md`」 | Task 1（`version_keys`）、Task 7（`_put_artifact`） |
| Rule 6「TutorialVersion 的 s3_key 指向該版本完整內容」 | Task 7（寫 `s3_key`）、Task 6（核對 `s3_key` 與實際物件） |
| Rule 7「與前版的 diff 儲存在 `tutorials/<slug>/v<n>.diff`」 | Task 3（`make_diff`）、Task 7（寫 diff 檔；v1 是空檔，F50） |
| Rule 8「建立 TutorialStep 時保存 references Feature 邊」 | Task 7（`put_edge(step_pk, "REFERENCES", feature_pk)`） |
| Rule 9「沒有 Feature 或引用多個 Feature 的步驟不可保存」 | Task 2（`validate_content` 三種錯誤訊息）、Task 7（驗證失敗就不寫） |
| Rule 10「references 邊的 target 等於 SK 中的關係終點」 | Task 7（由 `put_edge` 保證）、Task 6（核對 `SK == "REFERENCES#" + target`） |

Rule 2、3、8、10 各有一個可執行 Example，Task 5、6、7 的測試就是它們的自動化版本。例如 Rule 3 的 Example：

```gherkin
Example: prepare-meeting v3 取代 v2
  Given 教學 "prepare-meeting" 的目前版本為 "prepare-meeting@v2"
  When Release Note Update 為教學 "prepare-meeting" 建立下一版
  Then 新版本的取代關係資料如下
    | PK                         | SK                                    | target                     |
    | VERSION#prepare-meeting@v3 | SUPERSEDES#VERSION#prepare-meeting@v2 | VERSION#prepare-meeting@v2 |
```

### 10.2 `分析工單.feature` 中屬於 content 的四條

| Rule 編號與原文 | 本階段哪個 Task 落實 |
|---|---|
| Rule 11「新教學的完整內容包含 Title、Problem、Prerequisites、Steps 與 Expected Outcome」 | Task 2（五段齊全的檢查） |
| Rule 12「產生新教學時同時輸出每步提到的 Feature」 | Task 2（每步都要有 `feature_id`） |
| Rule 13「新教學的每個步驟恰好引用一個 Feature」 | Task 2（零個／多個都拒絕）、Task 7（一步一條 REFERENCES 邊） |
| Rule 14「新教學第一版的 reason 使用 gap 加上來源 cluster_id」 | Task 5 接受並保存 `reason`；`gap:<cluster_id>` 這個字串由 Phase 13 組出來 |

### 10.3 `套用教學規則.feature` 中屬於 content 的兩條

| Rule 編號與原文 | 本階段哪個 Task 落實 |
|---|---|
| Rule 6「套用規則的版本記錄於規則的 applied_to」 | Task 7（依 `plan.rules_applied` 寫 `APPLIED_TO` 邊）、Task 6（核對邊是否存在） |
| Rule 7「版本的 rules_applied 記錄本次套用的規則」 | Task 7（寫進 VERSION item）。清單內容由 Phase 06 的 `rules_for_content` 產生，D17 規定它是套用關係的唯一權威。 |

### 10.4 `依改版更新教學.feature` 中由本階段提供機制的兩條

| Rule 編號與原文 | 本階段哪個 Task 落實 |
|---|---|
| Rule 13「UPDATE 為受影響教學產生與前版的 diff」 | Task 3、Task 7 提供機制；Phase 16 使用 |
| Rule 14「UPDATE 下一版的 reason 使用 release 加上改版事件 id」 | Task 5 提供 `reason` 參數；`release:<id>` 由 Phase 16 組出來 |

---

## 11. 參考來源

設計文件（`docs/design/training-kb.md`）：

- §7.3 Ticket Analysis 的 CREATE 契約（五段內容、每步一個 Feature、`gap:<cluster_id>`）
- §7.6 共用寫作介面（程式必須驗證的項目）
- §8.1 五種動作與版本鏈（版號屬於教學、重試重用版號、允許缺口）
- §8.2 create_version 的完成條件（寫入順序、v1 空 diff、套用關係以 `rules_applied` 為準）
- §8.3 發布與併發必須守住的界線（S3 條件寫入與同 key 核對）
- §9.1 鍵與原生型別、§9.2 關係邊、§9.3 S3 路徑
- §10 圖譜查詢（基表一致讀取、GSI 只有最終一致）
- §14.1、§14.2 失敗語意與「重試不是重新抽一次文字」
- §15 測試與驗收設計，「全文與步驟」「版本與發布」兩列
- §16 交付切片 S2
- §19.1 資料決策 D05、D06、D25、D26、D29
- §19.2 功能決策 F36、F48、F50
- §20.2、§20.4、§20.6 逐條 Rule 與負責模組

規格檔：

- `docs/spec/features/建立教學版本.feature`
- `docs/spec/features/分析工單.feature`
- `docs/spec/features/套用教學規則.feature`
- `docs/spec/erm.dbml`（TUTORIAL、TUTORIAL_VERSION、TUTORIAL_STEP、FEATURE）
- `docs/spec/.clarify/resolved/data/TUTORIAL_VERSION_尚未發布的版本如何與已發布版本區分.md`（D25）
- `docs/spec/.clarify/resolved/data/TUTORIAL_VERSION_版本建立失敗後重試是否重用原版本號.md`（D26）
- `docs/spec/.clarify/resolved/features/建立教學版本_內容已寫入但版本關聯不完整時如何處理.md`（F36）
- `docs/spec/.clarify/resolved/features/建立教學版本_第一版沒有前版時_diff_檔案如何表示.md`（F50）

官方文件（本階段用到的語法都以這些為準）：

- boto3 S3 `put_object`（`IfNoneMatch` 條件寫入參數）：<https://docs.aws.amazon.com/boto3/latest/reference/services/s3/client/put_object.html>
- Amazon S3 條件寫入：<https://docs.aws.amazon.com/AmazonS3/latest/userguide/conditional-writes.html>
- boto3 DynamoDB Table resource：<https://docs.aws.amazon.com/boto3/latest/reference/services/dynamodb/service-resource/Table.html>
- DynamoDB 讀取一致性（基表可一致讀、GSI 不行）：<https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/HowItWorks.ReadConsistency.html>
- Python `difflib.unified_diff`：<https://docs.python.org/3/library/difflib.html#difflib.unified_diff>
- pydantic v2 `model_construct`（跳過驗證建立模型，測試用）：<https://docs.pydantic.dev/latest/api/base_model/#pydantic.BaseModel.model_construct>
- moto `mock_aws`：<https://docs.getmoto.org/en/latest/docs/getting_started.html>
