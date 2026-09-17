# Phase 02：領域模型與資料鍵

| 項目 | 內容 |
|---|---|
| 上一階段 | Phase 01：專案骨架與開發環境（`01-Phase01-專案骨架與開發環境.md`） |
| 下一階段 | Phase 03：Repository 本機儲存層（`03-Phase03-Repository-本機儲存層.md`） |
| 對應設計文件章節 | §1 名詞表、§7.1、§9.1、§9.2、§18（O1）（`docs/design/training-kb.md`） |
| 對應交付切片 | S0（設計文件第 16 節） |
| 預估時間 | 約 4 小時 |
| 做完會得到 | 十個實體的 pydantic 模型與全部 PK／SK／target 轉換函式；打錯的枚舉值、超出範圍的評分、格式錯的 version_id，都會在碰到資料庫之前就被擋下來 |

---

## 1. 這階段做完會得到什麼

兩個檔案：

1. **`src/training_kb/models.py`**——設計文件 §9.1 的十個邏輯實體（Tutorial、TutorialVersion、TutorialStep、Feature、Ticket、Release、Feedback、TutorialView、AuthoringRule、ProvenWorkflow）、七個枚舉、模型寫作用的「五段內容」（`TutorialContent`／`StepDraft`），以及裸 ID 工具 `make_version_id`／`parse_version_id`。
2. **`src/training_kb/keys.py`**——把裸 ID 轉成 DynamoDB 的 PK、SK、target，以及反向解析回來。

做完之後，下面這些事在**寫進資料庫之前**就會被擋下來：`source="slack"`（不是合法來源）、`rating=6`（超出 1..5）、`index=0`（步驟從 1 起算）、`version_id="prepare-meeting-v2"`（格式不對）、`Ticket.feature_ids` 放兩個（D04 規定 0 或 1 個）。

這一階段**完全是純邏輯**：不連網、不碰 AWS、不需要憑證。全部測試都能離線跑完。

---

## 2. 它在整張地圖的位置

```text
基礎層          01 骨架 -> 02 模型與鍵 -> 03 Repository(本機) -> 04 AWS 基礎建設
                            ^^^^^^^^                                  |
                          ★ 你在這裡                                   |
AI 與內容層     05 Writing(Bedrock) -> 06 規則注入 -> 07 建立版本 -> 08 發布與退役 -> 09 圖譜查詢
                                                                                        |
接入層          10 Ingress 驗簽 -> 11 Rote 判定 -> 12 Rote Agent -------------------------+
                                                                                        |
流程層          13 Ticket Analysis -> 14 StepFunctions 上線 -> 15 Feedback/View 匯入 -> 16 Release Update
                                                                                        |
學習層          17 Review:REFINE -> 18 Review:候選規則+排程 -> 19 Analytics 指標 -> 20 規則驗證
                                                                                        |
展示與驗收層    21 Demo 種子資料 -> 22 靜態教學站 -> 23 Demo 控制台 -> 24 失敗復原驗收 -> 25 安全與當日準備
```

`models.py` 與 `keys.py` 是**所有後面階段的共同語言**。Phase 03 的 Repository 把它們轉成 DynamoDB item，Phase 05 的模型輸出驗證用它們當 schema，Phase 19 的指標計算直接吃它們。名稱與欄位照文件寫，不要自己改。

---

## 3. 開始前檢查

Phase 01 必須已經完成。逐項確認：

```bash
cd ~/AWS-Hackathon
uv run pytest -q
uv run python -c "import training_kb; print(training_kb.__version__)"
uv run python -c "import pydantic; print(pydantic.VERSION)"
uv run python -c "import sys; print(sys.version_info[:2])"
```

預期：

| 指令 | 你應該看到 |
|---|---|
| `uv run pytest -q` | 結尾是 `38 passed, 1 skipped`，**0 failed、0 error** |
| `print(training_kb.__version__)` | `0.1.0` |
| `print(pydantic.VERSION)` | `2.x.y`（開頭一定要是 `2`；本階段全部用 pydantic v2 的 API） |
| `print(sys.version_info[:2])` | `(3, 12)` |

如果 `pydantic.VERSION` 是 `1.x`，代表 Phase 01 的 `pyproject.toml` 寫錯了，回去確認 `dependencies` 裡是 `"pydantic>=2.7"`，然後 `uv sync`。

另外，手邊打開這兩份檔案當對照，本階段會一直引用它們：

- `docs/spec/erm.dbml`（十個實體的欄位與說明）
- `docs/design/training-kb.md` 的 §9.1、§9.2（鍵與關係邊的表格）

---

## 4. 名詞小抄

| 名詞 | 白話解釋 | 在本階段哪裡用到 |
|---|---|---|
| 實體（entity） | 一種資料的型態，例如「教學」「回饋」。本案有十個 | 全部 Task |
| pydantic `BaseModel` | 繼承它的類別會自動驗證欄位型別，錯了就丟 `ValidationError` | Task 3–7 |
| `ValidationError` | pydantic 驗證失敗時丟的例外 | Task 3–7 |
| `model_validate(dict)` | 從一個 dict 建出模型並驗證；讀 DynamoDB item 時會用 | Task 3 |
| `model_dump()` | 把模型變回 dict；寫進 DynamoDB 前會用（Phase 03） | §9 |
| `ConfigDict(extra="ignore")` | 遇到模型沒定義的欄位就忽略，不報錯 | Task 3–7 |
| `Field(ge=1, le=5)` | 欄位限制：大於等於 1、小於等於 5 | Task 3、6、7 |
| `Field(default_factory=list)` | 每個實例各自建一個新的空清單；可變預設值一定要這樣寫 | Task 3、5、7 |
| `StrEnum` | Python 3.11+ 內建的列舉，成員同時也是字串 | Task 1 |
| 裸 ID | 不帶類型前綴的識別碼，例 `prepare-meeting@v2`、`R-007`、`Prepare` | 全部 |
| PK（分割鍵） | DynamoDB 主鍵的第一段，帶類型前綴，例 `TUTORIAL#prepare-meeting` | Task 8 |
| SK（排序鍵） | DynamoDB 主鍵的第二段。metadata 用 `META`，關係邊用 `關係#終點` | Task 8、9 |
| target | 關係邊的終點 PK，複製一份成獨立屬性，當 `by_target` GSI 的分割鍵 | Task 9 |
| GSI `by_target` | 「誰指向我」的反查索引。設計 §9.1 規定只有一個 | §5.4 |
| item | DynamoDB 裡的一「筆」資料，由 PK + SK 唯一決定 | §5.1 |
| `entity` 屬性 | 每個 item 額外存的類型字串（例 `"TUTORIAL"`），讓 Scan 好篩選 | Task 8 |
| SHA-256 | 雜湊函式：相同輸入永遠得到相同的固定長度指紋 | Task 9 |
| `slug` | 教學的英文短代號，例 `prepare-meeting` | Task 2、3 |
| `version_id` | 版本的裸 ID，格式固定 `<slug>@v<n>`，例 `prepare-meeting@v2` | Task 2、3 |
| `partition(sep)` | Python 字串方法：從**第一個**分隔符切成三段（前、分隔符、後） | Task 2、8、9 |
| `rpartition(sep)` | 同上，但從**最後一個**分隔符切 | Task 9 |

---

## 5. 設計說明

### 5.1 十個實體放在同一張表，長什麼樣子

設計文件 §9.1 規定：DynamoDB 表名 `training_kb`，複合主鍵 `(PK, SK)`，唯一的 GSI `by_target` 以 `target` 為分割鍵。十個邏輯實體**不是十張表**，而是同一張表裡 PK 前綴不同的 item。

```text
DynamoDB 表 training_kb（一張表裝十種實體 + 執行用 item）

+------------------------------+-------------------------------+---------------------------------+
| PK（分割鍵）                  | SK（排序鍵）                   | 其他屬性                          |
+------------------------------+-------------------------------+---------------------------------+
| TUTORIAL#prepare-meeting     | META                          | entity=TUTORIAL                  |
|                              |                               | topic, feature_ids, status,      |
|                              |                               | current_version=prepare-...@v2   |
+------------------------------+-------------------------------+---------------------------------+
| VERSION#prepare-meeting@v2   | META                          | entity=VERSION                   |
|                              |                               | reason, s3_key, rules_applied,   |
|                              |                               | published_at                     |
+------------------------------+-------------------------------+---------------------------------+
| VERSION#prepare-meeting@v2   | SUPERSEDES#VERSION#prepa..@v1 | target=VERSION#prepare-...@v1    |  <- 邊
+------------------------------+-------------------------------+---------------------------------+
| STEP#prepare-meeting@v2#3    | REFERENCES#FEATURE#Prepare    | entity=STEP                      |  <- 步驟與邊
|                              |                               | target=FEATURE#Prepare           |     是同一筆
|                              |                               | type=click_ui, text="開啟會議..."  |
+------------------------------+-------------------------------+---------------------------------+
| FEATURE#Prepare              | META                          | entity=FEATURE                   |
|                              |                               | name=Prepare                     |
|                              |                               | aliases=[Meeting Summary]        |
+------------------------------+-------------------------------+---------------------------------+
| FEEDBACK#f_12                | META                          | entity=FEEDBACK, rating=2 ...    |
| FEEDBACK#f_12                | REFERS_TO#VERSION#prepa..@v1  | target=VERSION#prepare-...@v1    |  <- 邊
+------------------------------+-------------------------------+---------------------------------+
| VIEW#9f2c…（SHA-256 前 32）   | META                          | entity=VIEW                      |
|                              |                               | tutorial_version, user, ts       |
+------------------------------+-------------------------------+---------------------------------+
```

注意 `STEP#...` 那一列：**步驟本體與它的 REFERENCES 邊是同一個 item**。ERM 的 `TUTORIAL_STEP` note 明寫「sk = REFERENCES# + target；target 是關係終點的複本」，而且每個步驟恰好引用一個 Feature（D05），所以不需要拆成兩筆。

### 5.2 裸 ID vs 帶前綴的 PK

這是本階段最容易搞混的地方。D03 的決定是：**邏輯關聯欄位一律使用裸 ID，只有 DynamoDB 的 PK／SK／target 才加型別前綴。**

```text
  models.py 的欄位（裸 ID）                keys.py 轉出來的鍵（帶前綴）
  ----------------------------            ------------------------------------
  Tutorial.slug            = "prepare-meeting"      tutorial_pk(slug)
                                            ---->  "TUTORIAL#prepare-meeting"

  TutorialVersion.version_id = "prepare-meeting@v2" version_pk(version_id)
                                            ---->  "VERSION#prepare-meeting@v2"

  TutorialVersion.supersedes = "prepare-meeting@v1" 邊的 target
                                            ---->  "VERSION#prepare-meeting@v1"

  TutorialStep.feature_id  = "Prepare"              feature_pk(feature_id)
                                            ---->  "FEATURE#Prepare"

  AuthoringRule.rule_id    = "R-007"                rule_pk(rule_id)
                                            ---->  "RULE#R-007"

  反過來：parse_pk("TUTORIAL#prepare-meeting") -> ("TUTORIAL", "prepare-meeting")
```

為什麼要這樣分？因為 `Tutorial.current_version` 存的是 `prepare-meeting@v2`，而不是 `VERSION#prepare-meeting@v2`。如果模型欄位也帶前綴，同一個值就會有兩種寫法，比對時遲早出錯。前綴是「物理儲存的事」，交給 `keys.py` 一個地方處理。

### 5.3 邊 = PK 起點 + SK「關係#終點」+ target

設計文件 §9.2 規定邊的通用格式。五種關係名稱是固定的：

```text
        起點 item                      SK（關係#終點）                 target（GSI 分割鍵）
  STEP#prepare-meeting@v2#3   REFERENCES#FEATURE#Prepare      FEATURE#Prepare
  VERSION#prepare-meeting@v3  SUPERSEDES#VERSION#prepa..@v2   VERSION#prepare-meeting@v2
  RULE#R-007                  APPLIED_TO#VERSION#prepa..@v2   VERSION#prepare-meeting@v2
  TICKET#t_881                ASKS_ABOUT#FEATURE#Prepare      FEATURE#Prepare
  FEEDBACK#f_12               REFERS_TO#VERSION#prepa..@v1    VERSION#prepare-meeting@v1

  查「誰引用 FEATURE#Prepare」：                查「A v3 取代了誰」：
      GSI by_target, target=FEATURE#Prepare        Query PK=VERSION#prepare-meeting@v3
      -> 拿到 STEP 與 TICKET 起點的邊              -> 依 SK 前綴 "SUPERSEDES#" 篩
      -> 再篩 SK 前綴 "REFERENCES#"                -> 得到 VERSION#prepare-meeting@v2
```

**為什麼 `target` 要把終點再存一份？** 因為 DynamoDB 的 GSI 需要一個獨立的屬性當分割鍵，不能拿 SK 的一部分。所以規格規定「`sk = REFERENCES# + target`」是一條**不變條件**：兩者必須一致。`edge_sk(relation, target_pk)` 就是為了保證這件事——SK 一定是從 target 組出來的，不會手打錯。

### 5.4 O1：metadata 的 SK 要放什麼

設計文件第 18 節的 **O1** 明說：ERM 沒有定義各實體 metadata item 的 SK，不可以假設是 `META`。

> **本計劃選擇（對應 O1）**：所有 metadata item 的 SK 一律用字串 `"META"`；`TUTORIAL_STEP` 保持既定的 `REFERENCES#<Feature PK>`。
>
> 理由：`(PK, SK)` 必須唯一，而每個實體只有一筆 metadata。用固定字串可以讓「讀一筆 metadata」變成 `get_item(PK=..., SK="META")`，也讓「讀某個起點的全部關係」變成 `Query(PK=...)` 之後排除 `SK == "META"`。
>
> 這**不代表** O1 已經被規格確認。Phase 03 之後如果規格給了別的答案，只需要改 `keys.META` 一個常數。

### 5.5 View 的 SHA-256 鍵

ERM 的 `TUTORIAL_VIEW` note 明說「PK 格式未指定，不假設 VIEW# 前綴」。設計文件 §9.1 做了選擇：

> **設計文件的選擇（§9.1「本文件設計選擇」）**：View 的 PK 是正規化後 `[tutorial_version, user, ts]` 的固定 JSON 編碼取 SHA-256。
>
> 具體做法（本階段實作）：`"VIEW#" + sha256(json.dumps([tutorial_version, user, ts], ensure_ascii=False, separators=(",", ":")))[:32]`

三個細節，缺一不可：

| 細節 | 為什麼 |
|---|---|
| `ensure_ascii=False` | 中文不要被轉成 `\uXXXX`，否則同一份資料在不同設定下會算出不同雜湊 |
| `separators=(",", ":")` | 去掉 JSON 預設的空白，讓編碼唯一 |
| 用 list 不用 dict | list 的順序固定；dict 的鍵順序在不同情況下可能不同 |

效果：**同樣的三元組永遠得到同一個 PK**（重送會被條件寫入擋掉，達成去重），**不同的 `ts` 得到不同的 PK**（同一個人看兩次會是兩筆紀錄）。設計文件也說明了副作用：完全同一秒的重複紀錄會被合併，但這不影響「每版每人最多一次」的指標分母。

### 5.6 本階段建立的檔案

```text
src/training_kb/
  __init__.py        （Phase 01）
  errors.py          （Phase 01）
  clock.py           （Phase 01）
  config.py          （Phase 01）
  models.py          ★ Task 1–7：七個枚舉、十個實體、TutorialContent、裸 ID 工具
  keys.py            ★ Task 8–9：META、實體 PK、view_pk、邊的 SK、反向解析
tests/unit/
  test_models_enums.py       Task 1
  test_models_version_id.py  Task 2
  test_models_tutorial.py    Task 3
  test_models_content.py     Task 4
  test_models_sources.py     Task 5
  test_models_feedback.py    Task 6
  test_models_rules.py       Task 7
  test_keys_pk.py            Task 8
  test_keys_edges.py         Task 9
```

---

## 6. 工作項目

### Task 1：枚舉與核定類別常數

**目的**：把七組「只能是這幾個值」的欄位寫死成 `StrEnum`，讓打錯字在建立物件時就被擋下來。

**檔案**：
- 新增：`src/training_kb/models.py`
- 測試：`tests/unit/test_models_enums.py`

**介面**：
- 消費：無
- 產出：`TicketSource`、`ReleaseSource`、`ReleaseKind`、`StepType`、`TutorialStatus`、`RuleStatus`、`ProcStatus`、`APPROVED_CATEGORIES_DEFAULT`、`PENDING_CATEGORY`

- [ ] **步驟 1：寫測試**

```python
# tests/unit/test_models_enums.py
"""七個枚舉與核定類別常數；值照 docs/spec/erm.dbml 與設計文件 §7.1。"""

import pytest

from training_kb.models import (
    APPROVED_CATEGORIES_DEFAULT,
    PENDING_CATEGORY,
    ProcStatus,
    ReleaseKind,
    ReleaseSource,
    RuleStatus,
    StepType,
    TicketSource,
    TutorialStatus,
)


def test_every_enum_lists_exactly_the_specified_values() -> None:
    assert [e.value for e in TicketSource] == ["github_issue", "discord", "email"]
    assert [e.value for e in ReleaseSource] == ["github_pr", "changelog"]
    assert [e.value for e in ReleaseKind] == ["renamed", "changed", "removed"]
    assert [e.value for e in StepType] == ["click_ui", "input", "read"]
    assert [e.value for e in TutorialStatus] == ["active", "retired"]
    assert [e.value for e in RuleStatus] == ["candidate", "active", "retired"]
    assert [e.value for e in ProcStatus] == ["active", "retired"]


@pytest.mark.parametrize(
    ("enum_cls", "bad_value"),
    [
        (TicketSource, "slack"),
        (ReleaseSource, "jira"),
        (ReleaseKind, "deprecated"),
        (StepType, "scroll"),
        (TutorialStatus, "obsolete"),  # D21：obsolete 只是顯示文字，不是第二個資料狀態
        (RuleStatus, "draft"),
        (ProcStatus, "paused"),
    ],
)
def test_illegal_value_is_rejected(enum_cls: type, bad_value: str) -> None:
    with pytest.raises(ValueError):
        enum_cls(bad_value)


def test_members_behave_like_plain_strings() -> None:
    assert StepType.CLICK_UI == "click_ui"
    assert f"{StepType.CLICK_UI}" == "click_ui"
    assert TicketSource("email") is TicketSource.EMAIL


def test_approved_categories_match_d13() -> None:
    assert APPROVED_CATEGORIES_DEFAULT == ["找不到按鈕", "缺少資訊"]
    assert PENDING_CATEGORY == "待分類"
    assert PENDING_CATEGORY not in APPROVED_CATEGORIES_DEFAULT
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：`uv run pytest tests/unit/test_models_enums.py -v`

預期：`1 error`，訊息是 `ModuleNotFoundError: No module named 'training_kb.models'`。

為什麼會失敗：`models.py` 還不存在，import 那一行就掛了。

- [ ] **步驟 3：寫最少的程式讓測試通過**

```python
# src/training_kb/models.py
"""十個邏輯實體、枚舉與裸 ID 工具。

來源：設計文件 §9.1（十個實體）、docs/spec/erm.dbml（欄位與說明）。

D03：邏輯關聯欄位一律使用「裸 ID」（例 prepare-meeting@v2、R-007、Prepare），
只有 DynamoDB 的 PK／SK／target 才加型別前綴——那是 keys.py 的責任。
"""

from enum import StrEnum


class TicketSource(StrEnum):
    """Ticket 的來源；ERM TICKET.source。"""

    GITHUB_ISSUE = "github_issue"
    DISCORD = "discord"
    EMAIL = "email"


class ReleaseSource(StrEnum):
    """Release 的來源；ERM RELEASE.source。"""

    GITHUB_PR = "github_pr"
    CHANGELOG = "changelog"


class ReleaseKind(StrEnum):
    """改版種類；renamed／changed 對應 UPDATE，removed 對應 RETIRE（設計 §7.4）。"""

    RENAMED = "renamed"
    CHANGED = "changed"
    REMOVED = "removed"


class StepType(StrEnum):
    """步驟型態；也是 AuthoringRule.applies_when 唯一支援的條件值（D16）。"""

    CLICK_UI = "click_ui"
    INPUT = "input"
    READ = "read"


class TutorialStatus(StrEnum):
    """教學狀態；D21：retired 是唯一資料狀態，obsolete 只是顯示文字。"""

    ACTIVE = "active"
    RETIRED = "retired"


class RuleStatus(StrEnum):
    """寫作規則的生命週期；只有 Analytics 可以寫這個欄位（設計 §12.2）。"""

    CANDIDATE = "candidate"
    ACTIVE = "active"
    RETIRED = "retired"


class ProcStatus(StrEnum):
    """接入流程記憶的狀態；連續三次重放失敗後轉 retired（D20）。"""

    ACTIVE = "active"
    RETIRED = "retired"


# D13：核定類別表可擴充，初始清單就是這兩個；未知值一律寫成「待分類」。
# 實際執行時由 repository.get_config_list("feedback_categories", APPROVED_CATEGORIES_DEFAULT)
# 讀取，可以在不改程式的情況下擴充（Phase 03 實作）。
APPROVED_CATEGORIES_DEFAULT: list[str] = ["找不到按鈕", "缺少資訊"]
PENDING_CATEGORY = "待分類"
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：`uv run pytest tests/unit/test_models_enums.py -v`

預期：`10 passed`（一個列舉檢查 + 七個 parametrize 案例 + 兩個常數檢查）。

- [ ] **步驟 5：commit**

```bash
git add src/training_kb/models.py tests/unit/test_models_enums.py
git commit -m "feat(models): 加入七個枚舉與核定類別常數"
```

---

### Task 2：裸 ID 工具 `make_version_id` 與 `parse_version_id`

**目的**：把 `<slug>@v<n>` 這個格式集中在兩個函式裡，不要讓各階段自己用 f-string 拼。

**檔案**：
- 修改：`src/training_kb/models.py`
- 測試：`tests/unit/test_models_version_id.py`

**介面**：
- 消費：無
- 產出：`make_version_id(slug: str, n: int) -> str`、`parse_version_id(version_id: str) -> tuple[str, int]`、`VERSION_SEPARATOR`（新增常數，`00-總覽.md` §9.2 未列）

- [ ] **步驟 1：寫測試**

```python
# tests/unit/test_models_version_id.py
"""裸 version_id 的格式：<slug>@v<n>，例 prepare-meeting@v2（設計文件 §8.1）。"""

import pytest

from training_kb.models import make_version_id, parse_version_id


def test_make_version_id_formats_slug_and_number() -> None:
    assert make_version_id("prepare-meeting", 1) == "prepare-meeting@v1"
    assert make_version_id("share-summary", 12) == "share-summary@v12"


def test_make_version_id_rejects_numbers_below_one() -> None:
    # 建立教學版本.feature Rule 1：新 Tutorial 的版本從 v1 起算
    for bad_number in (0, -1):
        with pytest.raises(ValueError):
            make_version_id("prepare-meeting", bad_number)


@pytest.mark.parametrize("bad_slug", ["", "already@v1", "has#hash"])
def test_make_version_id_rejects_slugs_that_break_the_format(bad_slug: str) -> None:
    with pytest.raises(ValueError):
        make_version_id(bad_slug, 1)


@pytest.mark.parametrize(
    ("slug", "n"), [("prepare-meeting", 1), ("share-summary", 12), ("a-b-c", 7)]
)
def test_parse_version_id_round_trips(slug: str, n: int) -> None:
    assert parse_version_id(make_version_id(slug, n)) == (slug, n)


def test_parse_version_id_returns_an_int_not_a_string() -> None:
    slug, n = parse_version_id("prepare-meeting@v10")
    assert slug == "prepare-meeting"
    assert n == 10
    assert isinstance(n, int)


@pytest.mark.parametrize(
    "bad",
    [
        "prepare-meeting",  # 沒有 @v
        "prepare-meeting@v",  # 沒有數字
        "@v2",  # 沒有 slug
        "prepare-meeting@vx",  # 不是數字
        "prepare-meeting@v2@v3",  # 多一段
        "prepare-meeting@v0",  # 版本號從 1 起算
        "prepare-meeting-v2",  # 用了錯的分隔符
    ],
)
def test_parse_version_id_rejects_bad_formats(bad: str) -> None:
    with pytest.raises(ValueError):
        parse_version_id(bad)
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：`uv run pytest tests/unit/test_models_version_id.py -v`

預期：`1 error`，訊息是
`ImportError: cannot import name 'make_version_id' from 'training_kb.models'`。

- [ ] **步驟 3：寫最少的程式讓測試通過**

在 `src/training_kb/models.py` 的**最後面**、空兩行之後接上：

```python
# --- 裸 ID 工具（設計文件 §8.1：version_id 格式為 <slug>@v<n>）---

VERSION_SEPARATOR = "@v"


def make_version_id(slug: str, n: int) -> str:
    """組出裸 version_id，例 make_version_id("prepare-meeting", 2) -> "prepare-meeting@v2"。"""
    if not slug or VERSION_SEPARATOR in slug or "#" in slug:
        raise ValueError(f"slug 不合法（不可為空、不可含 '@v' 或 '#'）：{slug!r}")
    if n < 1:
        raise ValueError(f"版本號從 1 起算，收到 {n}")
    return f"{slug}{VERSION_SEPARATOR}{n}"


def parse_version_id(version_id: str) -> tuple[str, int]:
    """把裸 version_id 拆回 (slug, n)；格式不合就丟 ValueError。"""
    slug, separator, number = version_id.partition(VERSION_SEPARATOR)
    if not separator or not slug or not number.isdigit():
        raise ValueError(f"version_id 格式應為 <slug>@v<n>，收到 {version_id!r}")
    n = int(number)
    if n < 1:
        raise ValueError(f"版本號從 1 起算，收到 {version_id!r}")
    return slug, n
```

> `partition("@v")` 會從**第一個** `@v` 切開，所以 `"prepare-meeting@v2@v3"` 會得到後段 `"2@v3"`，而 `"2@v3".isdigit()` 是 `False`，於是被拒絕。

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：`uv run pytest tests/unit/test_models_version_id.py -v`

預期：`16 passed`。

- [ ] **步驟 5：commit**

```bash
git add src/training_kb/models.py tests/unit/test_models_version_id.py
git commit -m "feat(models): 加入 version_id 的組合與解析"
```

---

### Task 3：教學三件組 `Tutorial`、`TutorialVersion`、`TutorialStep`

**目的**：把設計文件 §9.1 表格裡教學相關的三個實體變成 pydantic 模型。

**檔案**：
- 修改：`src/training_kb/models.py`
- 測試：`tests/unit/test_models_tutorial.py`

**介面**：
- 消費：`StepType`、`TutorialStatus`（Task 1）
- 產出：`Tutorial`、`TutorialVersion`、`TutorialStep`

> 欄位順序照 `00-總覽.md` §9.2 抄。pydantic 跟 dataclass 不同，**允許有預設值的欄位排在必填欄位前面**，因為它是用關鍵字建構的。

- [ ] **步驟 1：寫測試**

```python
# tests/unit/test_models_tutorial.py
"""教學三件組。欄位照 docs/spec/erm.dbml 的 TUTORIAL / TUTORIAL_VERSION / TUTORIAL_STEP。"""

import pytest
from pydantic import ValidationError

from training_kb.models import StepType, Tutorial, TutorialStatus, TutorialStep, TutorialVersion


def test_tutorial_starts_without_version_successor_or_cluster() -> None:
    t = Tutorial(
        slug="prepare-meeting",
        topic="準備會議",
        feature_ids=["Prepare"],
        status=TutorialStatus.ACTIVE,
    )
    assert t.current_version is None  # publish 成功才切換（F37）
    assert t.successor is None  # D22：可空
    assert t.cluster_id is None  # D29：首版建立時才寫入


def test_tutorial_status_must_be_a_legal_value() -> None:
    with pytest.raises(ValidationError):
        Tutorial(slug="a", topic="t", feature_ids=[], status="obsolete")


def test_tutorial_accepts_the_enum_value_written_as_a_string() -> None:
    t = Tutorial(slug="a", topic="t", feature_ids=[], status="retired")
    assert t.status is TutorialStatus.RETIRED


def test_version_defaults_to_unpublished() -> None:
    v = TutorialVersion(
        version_id="prepare-meeting@v1",
        reason="gap:c12",
        s3_key="tutorials/prepare-meeting/v1.md",
    )
    assert v.published_at is None  # D25：None 代表未發布
    assert v.supersedes is None  # v1 沒有前一版
    assert v.rules_applied == []  # F29：只記本次實際注入的規則


def test_rules_applied_is_not_shared_between_instances() -> None:
    a = TutorialVersion(version_id="a@v1", reason="gap:c1", s3_key="k1")
    b = TutorialVersion(version_id="b@v1", reason="gap:c1", s3_key="k2")
    a.rules_applied.append("R-007")
    assert b.rules_applied == []


def test_version_reason_is_required() -> None:
    # 建立教學版本.feature Rule 4：每次建立版本都記錄引起變更的 reason
    with pytest.raises(ValidationError):
        TutorialVersion(version_id="a@v1", s3_key="k")


def test_step_index_starts_at_one() -> None:
    with pytest.raises(ValidationError):
        TutorialStep(
            tutorial_version="prepare-meeting@v2",
            index=0,
            type=StepType.READ,
            text="x",
            feature_id="Prepare",
        )


def test_step_type_must_be_one_of_the_three_values() -> None:
    with pytest.raises(ValidationError):
        TutorialStep(
            tutorial_version="prepare-meeting@v2",
            index=1,
            type="scroll",
            text="x",
            feature_id="Prepare",
        )


def test_step_holds_exactly_one_feature_id() -> None:
    # D05 / 建立教學版本.feature Rule 9：恰好一個，所以欄位是單一字串而不是清單
    step = TutorialStep(
        tutorial_version="prepare-meeting@v2",
        index=3,
        type=StepType.CLICK_UI,
        text="開啟會議頁面，在右上角選擇 Prepare。",
        feature_id="Prepare",
    )
    assert step.feature_id == "Prepare"


def test_extra_attributes_from_a_dynamodb_item_are_ignored() -> None:
    item = {
        "PK": "TUTORIAL#prepare-meeting",
        "SK": "META",
        "entity": "TUTORIAL",
        "slug": "prepare-meeting",
        "topic": "準備會議",
        "feature_ids": ["Prepare"],
        "status": "active",
    }
    t = Tutorial.model_validate(item)
    assert t.slug == "prepare-meeting"
    assert t.status is TutorialStatus.ACTIVE
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：`uv run pytest tests/unit/test_models_tutorial.py -v`

預期：`1 error`，訊息是
`ImportError: cannot import name 'Tutorial' from 'training_kb.models'`。

- [ ] **步驟 3：寫最少的程式讓測試通過**

先把 `src/training_kb/models.py` **最上面**的 import 區塊改成：

```python
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field
```

再在檔案**最後面**、空兩行之後接上：

```python
# --- 教學三件組（設計文件 §9.1）---

# extra="ignore"：Phase 03 的 Repository 會把整個 DynamoDB item（含 PK、SK、entity、target）
# 直接丟進 model_validate()，這些多出來的屬性要被忽略而不是報錯。
_ITEM_CONFIG = ConfigDict(extra="ignore")


class Tutorial(BaseModel):
    """一篇教學的身分。ERM TUTORIAL；DynamoDB PK = TUTORIAL#<slug>。"""

    model_config = _ITEM_CONFIG

    slug: str
    current_version: str | None = None  # 裸 version_id；publish 成功回傳時才切換（F37）
    topic: str
    feature_ids: list[str]
    status: TutorialStatus
    successor: str | None = None  # 裸 slug，可空（D22、F54）
    cluster_id: str | None = None  # 首版建立時寫入，之後不變（D29）


class TutorialVersion(BaseModel):
    """一篇教學的某一版。ERM TUTORIAL_VERSION；PK = VERSION#<slug>@v<n>。"""

    model_config = _ITEM_CONFIG

    version_id: str  # 裸 ID "<slug>@v<n>"
    supersedes: str | None = None  # 前一版的裸 version_id；v1 為 None
    reason: str  # gap:<cluster_id> / release:<id> / feedback:<n> 則 <category>
    rules_applied: list[str] = Field(default_factory=list)  # D17：套用關係的權威來源
    s3_key: str  # tutorials/<slug>/v<n>.md
    published_at: str | None = None  # D25：None 代表未發布


class TutorialStep(BaseModel):
    """某一版裡的一個步驟。ERM TUTORIAL_STEP；PK = STEP#<slug>@v<n>#<i>。"""

    model_config = _ITEM_CONFIG

    tutorial_version: str  # 所屬版本的裸 version_id
    index: int = Field(ge=1)  # 該版本內的步驟編號，從 1 起算
    type: StepType
    text: str
    feature_id: str  # D05：恰好一個，所以是單一字串不是清單
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：`uv run pytest tests/unit/test_models_tutorial.py -v`

預期：`10 passed`。

- [ ] **步驟 5：commit**

```bash
git add src/training_kb/models.py tests/unit/test_models_tutorial.py
git commit -m "feat(models): 加入 Tutorial、TutorialVersion 與 TutorialStep"
```

---

### Task 4：`Feature` 與「五段內容」`StepDraft`、`TutorialContent`

**目的**：`Feature` 是圖譜的樞紐；`TutorialContent` 是模型寫出來、還沒寫進資料庫的五段內容。

**檔案**：
- 修改：`src/training_kb/models.py`
- 測試：`tests/unit/test_models_content.py`

**介面**：
- 消費：`StepType`（Task 1）
- 產出：`Feature`、`StepDraft`、`TutorialContent`

- [ ] **步驟 1：寫測試**

```python
# tests/unit/test_models_content.py
"""Feature 與五段內容。設計文件 §7.3、§9.1；分析工單.feature Rule 11、12、13。"""

import pytest
from pydantic import ValidationError

from training_kb.models import Feature, StepDraft, StepType, TutorialContent


def test_feature_id_and_display_name_are_separate_fields() -> None:
    # D06：改名只更新 name 與 aliases，第一次建立的 PK 後綴（feature_id）不變
    f = Feature(
        feature_id="Prepare",
        name="Prepare",
        aliases=["Meeting Summary"],
        first_seen="2026-07-01T00:00:00Z",
    )
    assert f.feature_id == "Prepare"
    assert f.name == "Prepare"
    assert f.aliases == ["Meeting Summary"]


def test_feature_aliases_default_to_empty_and_are_not_shared() -> None:
    a = Feature(feature_id="Prepare", name="Meeting Summary", first_seen="2026-07-01T00:00:00Z")
    b = Feature(feature_id="Share", name="Share Summary", first_seen="2026-07-01T00:00:00Z")
    assert a.aliases == []
    a.aliases.append("x")
    assert b.aliases == []


def _content() -> TutorialContent:
    return TutorialContent(
        title="準備會議",
        problem="不知道會前摘要在哪裡開啟。",
        prerequisites=["已登入", "已建立會議"],
        steps=[
            StepDraft(type=StepType.READ, text="打開會議清單。", feature_id="Prepare"),
            StepDraft(type=StepType.CLICK_UI, text="點右上角的 Prepare。", feature_id="Prepare"),
        ],
        expected_outcome="看到這場會議的會前摘要。",
    )


def test_tutorial_content_has_all_five_sections() -> None:
    c = _content()
    assert c.title and c.problem and c.prerequisites and c.steps and c.expected_outcome


@pytest.mark.parametrize(
    "missing", ["title", "problem", "prerequisites", "steps", "expected_outcome"]
)
def test_missing_any_section_is_rejected(missing: str) -> None:
    data = _content().model_dump()
    del data[missing]
    with pytest.raises(ValidationError):
        TutorialContent.model_validate(data)


def test_steps_are_parsed_from_plain_dicts() -> None:
    c = TutorialContent.model_validate(
        {
            "title": "分享摘要",
            "problem": "不知道怎麼分享。",
            "prerequisites": [],
            "steps": [{"type": "click_ui", "text": "點分享。", "feature_id": "Share Summary"}],
            "expected_outcome": "對方收到摘要。",
        }
    )
    assert isinstance(c.steps[0], StepDraft)
    assert c.steps[0].type is StepType.CLICK_UI


def test_step_draft_rejects_an_unknown_type() -> None:
    with pytest.raises(ValidationError):
        StepDraft(type="scroll", text="x", feature_id="Prepare")
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：`uv run pytest tests/unit/test_models_content.py -v`

預期：`1 error`，訊息是
`ImportError: cannot import name 'Feature' from 'training_kb.models'`。

- [ ] **步驟 3：寫最少的程式讓測試通過**

在 `src/training_kb/models.py` 的**最後面**、空兩行之後接上：

```python
# --- Feature 與五段內容 ---


class Feature(BaseModel):
    """產品功能節點。ERM FEATURE；PK = FEATURE#<第一次建立時的名稱>。

    D06：改名不遷移 PK，只更新 name 與 aliases，所以 feature_id 與 name 可能不同。
    例：PK 後綴永遠是 "Prepare"，改名後 name 也是 "Prepare"，
    但 aliases 會多一個 "Meeting Summary"。
    """

    model_config = _ITEM_CONFIG

    feature_id: str  # PK 後綴，建立後不變
    name: str  # 目前顯示名稱
    aliases: list[str] = Field(default_factory=list)  # D07：同專案內必須唯一
    first_seen: str


class StepDraft(BaseModel):
    """模型寫出來的一個步驟；還沒有 index，也還沒寫進資料庫。"""

    model_config = _ITEM_CONFIG

    type: StepType
    text: str
    feature_id: str  # 分析工單.feature Rule 13：恰好一個既有 Feature


class TutorialContent(BaseModel):
    """五段內容。設計文件 §7.3：Title、Problem、Prerequisites、Steps、Expected Outcome。

    五個欄位都是必填；缺任何一段就不是合法的教學內容。
    「每步的 feature_id 是否真的存在」這種業務檢查在 Phase 07 的 validate_content()，
    這裡只保證結構齊全。
    """

    model_config = _ITEM_CONFIG

    title: str
    problem: str
    prerequisites: list[str]
    steps: list[StepDraft]
    expected_outcome: str
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：`uv run pytest tests/unit/test_models_content.py -v`

預期：`10 passed`。

- [ ] **步驟 5：commit**

```bash
git add src/training_kb/models.py tests/unit/test_models_content.py
git commit -m "feat(models): 加入 Feature 與五段內容模型"
```

---

### Task 5：來源事件 `Ticket` 與 `Release`

**目的**：兩種會啟動 Step Functions 流程的輸入資料。

**檔案**：
- 修改：`src/training_kb/models.py`
- 測試：`tests/unit/test_models_sources.py`

**介面**：
- 消費：`TicketSource`、`ReleaseSource`、`ReleaseKind`（Task 1）
- 產出：`Ticket`、`Release`

- [ ] **步驟 1：寫測試**

```python
# tests/unit/test_models_sources.py
"""Ticket 與 Release。欄位照 ERM 與設計文件 §7.1 的接入契約表。"""

import pytest
from pydantic import ValidationError

from training_kb.models import Release, ReleaseKind, ReleaseSource, Ticket, TicketSource


def _ticket(**overrides: object) -> Ticket:
    data: dict[str, object] = {
        "id": "t_881",
        "source": TicketSource.GITHUB_ISSUE,
        "text": "會前摘要在哪裡開啟？",
        "author": "u_01",
        "ts": "2026-08-03T10:00:00Z",
        "project_id": "demo-project",
    }
    data.update(overrides)
    return Ticket.model_validate(data)


def test_analysis_fields_are_empty_until_the_pipeline_fills_them() -> None:
    t = _ticket()
    assert t.cluster_id is None  # 由 Ticket Analysis 補入
    assert t.feature_ids == []  # 空清單代表尚未對應 Feature
    assert t.embedding is None  # 1024 維向量由 task_embed 補入


@pytest.mark.parametrize("field", ["id", "source", "text", "author", "ts", "project_id"])
def test_every_ingest_required_field_is_required(field: str) -> None:
    # 接入來源事件.feature Rule 22
    data = _ticket().model_dump()
    del data[field]
    with pytest.raises(ValidationError):
        Ticket.model_validate(data)


def test_illegal_source_is_rejected() -> None:
    with pytest.raises(ValidationError):
        _ticket(source="slack")


def test_ticket_maps_to_at_most_one_feature() -> None:
    # D04 / 分析工單.feature Rule 6：feature_ids 長度為 0 或 1
    assert _ticket(feature_ids=["Prepare"]).feature_ids == ["Prepare"]
    with pytest.raises(ValidationError):
        _ticket(feature_ids=["Prepare", "Share Summary"])


def test_embedding_holds_plain_floats() -> None:
    t = _ticket(embedding=[0.1] * 1024)
    assert len(t.embedding or []) == 1024


def _release(**overrides: object) -> Release:
    data: dict[str, object] = {
        "id": "r_42",
        "source": ReleaseSource.GITHUB_PR,
        "source_event_id": "42",
        "feature": "Prepare",
        "kind": ReleaseKind.RENAMED,
        "old_name": "Meeting Summary",
        "new_name": "Prepare",
        "evidence": "PR #42 diff excerpt",
        "ts": "2026-09-01T00:00:00Z",
    }
    data.update(overrides)
    return Release.model_validate(data)


def test_renamed_release_carries_both_names() -> None:
    r = _release()
    assert r.old_name == "Meeting Summary"
    assert r.new_name == "Prepare"


def test_name_fields_must_be_stated_even_when_empty() -> None:
    # 本模型把 old_name / new_name 定義成「必填但可為 null」，
    # 所以 changed / removed 也要明確寫 None，不能整個欄位省略。
    r = _release(kind=ReleaseKind.REMOVED, old_name=None, new_name=None)
    assert r.kind is ReleaseKind.REMOVED
    data = _release().model_dump()
    del data["old_name"]
    with pytest.raises(ValidationError):
        Release.model_validate(data)


def test_illegal_kind_is_rejected() -> None:
    with pytest.raises(ValidationError):
        _release(kind="deprecated")


def test_sub_releases_share_the_source_event_id() -> None:
    # F14：一則來源含多個 Feature 變更時拆成多個子 Release，共用 source_event_id
    a = _release(id="r_42a", feature="Prepare")
    b = _release(
        id="r_42b", feature="Share Summary", kind=ReleaseKind.CHANGED, old_name=None, new_name=None
    )
    assert a.id != b.id
    assert a.source_event_id == b.source_event_id == "42"
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：`uv run pytest tests/unit/test_models_sources.py -v`

預期：`1 error`，訊息是
`ImportError: cannot import name 'Release' from 'training_kb.models'`。

- [ ] **步驟 3：寫最少的程式讓測試通過**

在 `src/training_kb/models.py` 的**最後面**、空兩行之後接上：

```python
# --- 來源事件 ---


class Ticket(BaseModel):
    """使用者問題。ERM TICKET；PK = TICKET#<id>。

    接入必填：id、source、text、author、ts、project_id（接入來源事件.feature Rule 22）。
    cluster_id、feature_ids、embedding 由 Ticket Analysis 補入，不是接入必填。
    author 與 Feedback.user、TutorialView.user 共用同一個穩定使用者 ID（D23）。
    """

    model_config = _ITEM_CONFIG

    id: str  # D02：直接使用已全域唯一的上游 ID，例 "t_881"
    source: TicketSource
    text: str
    author: str
    ts: str
    project_id: str
    cluster_id: str | None = None
    # D04：長度 0 或 1。max_length=1 讓「一張 Ticket 對應多個 Feature」在型別層就被擋下。
    feature_ids: list[str] = Field(default_factory=list, max_length=1)
    embedding: list[float] | None = None  # 1024 維 Titan 向量（D08）


class Release(BaseModel):
    """產品改版事件。ERM RELEASE；PK = RELEASE#<id>。

    F14：一則來源含多個 Feature 變更時拆成多個子 Release，各自有全域唯一 id，
    但共用同一個 source_event_id（例如 PR 號）。

    old_name / new_name 定義成「必填但可為 null」：renamed 一定要有值（由 Phase 10 的
    validate_release() 檢查並回報欄位名），其他 kind 要明確寫 None，避免「忘了帶」
    與「確實沒有」混在一起。
    """

    model_config = _ITEM_CONFIG

    id: str  # 例 "r_42"
    source: ReleaseSource
    source_event_id: str  # 父來源事件識別碼，例 PR 號
    feature: str  # 對應 FEATURE.name 或 aliases
    kind: ReleaseKind
    old_name: str | None
    new_name: str | None
    evidence: str
    ts: str
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：`uv run pytest tests/unit/test_models_sources.py -v`

預期：`14 passed`。

- [ ] **步驟 5：commit**

```bash
git add src/training_kb/models.py tests/unit/test_models_sources.py
git commit -m "feat(models): 加入 Ticket 與 Release"
```

---

### Task 6：`Feedback` 與 `TutorialView`

**目的**：兩種走「固定保存路徑」的輸入（設計 §7.1：不啟動 Step Functions、不更新 PROC）。

**檔案**：
- 修改：`src/training_kb/models.py`
- 測試：`tests/unit/test_models_feedback.py`

**介面**：
- 消費：無（只用內建型別）
- 產出：`Feedback`、`TutorialView`

- [ ] **步驟 1：寫測試**

```python
# tests/unit/test_models_feedback.py
"""Feedback 與 TutorialView。ERM FEEDBACK / TUTORIAL_VIEW；收集教學回饋.feature。"""

import pytest
from pydantic import ValidationError

from training_kb.models import Feedback, TutorialView


def _feedback(**overrides: object) -> Feedback:
    data: dict[str, object] = {
        "id": "f_12",
        "tutorial_version": "prepare-meeting@v1",
        "rating": 2,
        "user": "u_01",
        "category": "找不到按鈕",
        "comment": "第三步沒有指出按鈕在哪一頁與位置",
        "ts": "2026-08-02T09:00:00Z",
    }
    data.update(overrides)
    return Feedback.model_validate(data)


@pytest.mark.parametrize("rating", [1, 2, 3, 4, 5])
def test_rating_accepts_one_to_five(rating: int) -> None:
    assert _feedback(rating=rating).rating == rating


@pytest.mark.parametrize("rating", [0, 6, -1, 100])
def test_rating_outside_one_to_five_is_rejected(rating: int) -> None:
    # 收集教學回饋.feature Rule 3：rating 只能為 1 到 5 的整數
    with pytest.raises(ValidationError):
        _feedback(rating=rating)


def test_rating_with_a_fractional_part_is_rejected() -> None:
    with pytest.raises(ValidationError):
        _feedback(rating=3.5)


def test_rating_only_feedback_is_valid() -> None:
    # D12：只有評分、category 與 comment 都空的回饋仍然有效
    f = _feedback(category=None, comment=None)
    assert f.category is None
    assert f.comment is None
    assert f.rating == 2


def test_user_is_required() -> None:
    # D11 / 收集教學回饋.feature Rule 9：必須提供穩定使用者 ID
    data = _feedback().model_dump()
    del data["user"]
    with pytest.raises(ValidationError):
        Feedback.model_validate(data)


def test_feedback_points_at_a_bare_version_id() -> None:
    assert _feedback().tutorial_version == "prepare-meeting@v1"


def test_view_requires_version_user_and_timestamp() -> None:
    v = TutorialView(tutorial_version="prepare-meeting@v1", user="u_01", ts="2026-08-02T09:00:00Z")
    assert v.user == "u_01"
    for field in ("tutorial_version", "user", "ts"):
        data = v.model_dump()
        del data[field]
        with pytest.raises(ValidationError):
            TutorialView.model_validate(data)
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：`uv run pytest tests/unit/test_models_feedback.py -v`

預期：`1 error`，訊息是
`ImportError: cannot import name 'Feedback' from 'training_kb.models'`。

- [ ] **步驟 3：寫最少的程式讓測試通過**

在 `src/training_kb/models.py` 的**最後面**、空兩行之後接上：

```python
# --- 回饋與瀏覽（走固定保存路徑，不啟動 Step Functions；設計文件 §7.1）---


class Feedback(BaseModel):
    """使用者對某一個版本的回饋。ERM FEEDBACK；PK = FEEDBACK#<id>。

    category 與 comment 都可以是 None（D12：只有評分的回饋仍然有效）。
    category 的合法值是「核定類別表」或「待分類」（D13），這個比對在 Phase 15 做，
    因為核定類別表可以由 CONFIG item 擴充，不寫死在模型裡。
    """

    model_config = _ITEM_CONFIG

    id: str  # 例 "f_12"
    tutorial_version: str  # 裸 version_id；必須存在於圖譜（Phase 15 檢查）
    rating: int = Field(ge=1, le=5)  # 收集教學回饋.feature Rule 3
    user: str  # D11、D23：必填且與 Ticket.author 同一穩定 ID
    category: str | None
    comment: str | None
    ts: str  # 設計 §7.1：缺值時由匯入工具填匯入時間並註明


class TutorialView(BaseModel):
    """教學版本的瀏覽事件，是同題重開票率的分母來源（D24）。

    ERM TUTORIAL_VIEW；PK 由 keys.view_pk(tutorial_version, user, ts) 計算。
    ts 必填，不可以用匯入時間補成「先瀏覽」的證據（設計文件 §7.1）。
    """

    model_config = _ITEM_CONFIG

    tutorial_version: str
    user: str
    ts: str
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：`uv run pytest tests/unit/test_models_feedback.py -v`

預期：`14 passed`。

> 小提醒：pydantic v2 預設是「寬鬆模式」，字串 `"3"` 會被轉成整數 `3`。設計文件要求的「rating 只能是整數」由 Phase 10／15 的 `validate_feedback()` 做嚴格型別檢查；這裡負責的是範圍與必填。

- [ ] **步驟 5：commit**

```bash
git add src/training_kb/models.py tests/unit/test_models_feedback.py
git commit -m "feat(models): 加入 Feedback 與 TutorialView"
```

---

### Task 7：`AuthoringRule`、`ProcStep` 與 `ProvenWorkflow`

**目的**：最後兩個實體——寫作規則，以及接入層的流程記憶。

**檔案**：
- 修改：`src/training_kb/models.py`
- 測試：`tests/unit/test_models_rules.py`

**介面**：
- 消費：`RuleStatus`、`ProcStatus`（Task 1）
- 產出：`AuthoringRule`、`ProcStep`、`ProvenWorkflow`

> 兩個要特別說明的欄位：
>
> 1. **`AuthoringRule.validated_at`** 是**本計劃新增的 metadata 欄位**，ERM 沒有。F28 規定「同一適用範圍內只採用最近驗證通過的規則」，需要一個時間點才能比較。它不是新實體，只是 RULE item 上多一個屬性，由 `analytics.apply_rule_status()` 寫入（Phase 20）。
> 2. **`ProvenWorkflow.domain` 與 `adapter_type`**：ERM 的 PROVEN_WORKFLOW note 寫「不新增 sender、domain 或專案欄位」，但設計文件 §7.2 同時說「保存這份脈絡的做法列於第 18 節」，也就是 **O2 還沒有答案**。**本計劃選擇（對應 O2）**：把 `domain` 與 `adapter_type` 直接存在 PROC item 上，因為第二層 Jaccard 比對需要先把候選限制在「同網域 + 同 adapter 類型」的範圍內（D19），而簽名是雜湊、無法反推。這是與 ERM note 不同的地方，在 §9 也有記錄。

- [ ] **步驟 1：寫測試**

```python
# tests/unit/test_models_rules.py
"""AuthoringRule 與 ProvenWorkflow。ERM AUTHORING_RULE / PROVEN_WORKFLOW。"""

import pytest
from pydantic import ValidationError

from training_kb.models import AuthoringRule, ProcStatus, ProcStep, ProvenWorkflow, RuleStatus


def _rule(**overrides: object) -> AuthoringRule:
    data: dict[str, object] = {
        "rule_id": "R-007",
        "rule": "點 UI 的步驟要寫出頁面、按鈕位置與點擊結果。",
        "applies_when": {"step.type": "click_ui"},
        "evidence": ["f_12", "f_15", "f_19", "f_23", "f_27"],
        "status": RuleStatus.CANDIDATE,
        "derived_from": "prepare-meeting@v1",
    }
    data.update(overrides)
    return AuthoringRule.model_validate(data)


def test_new_rule_starts_as_candidate_without_applications() -> None:
    r = _rule()
    assert r.status is RuleStatus.CANDIDATE
    assert r.applied_to == []  # D17：由各版 rules_applied 重建
    assert r.validated_at is None  # 本計劃新增欄位；Analytics 驗證通過才寫


def test_applies_when_uses_a_single_step_type_condition() -> None:
    # D16：MVP 只支援 step.type 等於 click_ui / input / read 的單一等值條件
    assert _rule().applies_when == {"step.type": "click_ui"}


def test_evidence_holds_only_feedback_ids() -> None:
    # D15：只存 Feedback ID 清單，不存提出時的類別快照
    assert _rule().evidence == ["f_12", "f_15", "f_19", "f_23", "f_27"]


def test_derived_from_is_exactly_one_version() -> None:
    # D18：恰好一個裸 version_id
    assert _rule().derived_from == "prepare-meeting@v1"
    data = _rule().model_dump()
    del data["derived_from"]
    with pytest.raises(ValidationError):
        AuthoringRule.model_validate(data)


def test_illegal_rule_status_is_rejected() -> None:
    with pytest.raises(ValidationError):
        _rule(status="draft")


def _proc(**overrides: object) -> ProvenWorkflow:
    data: dict[str, object] = {
        "signature": "9f2c41b07ad3e5c8",
        "domain": "github.com",
        "adapter_type": "ticket",
        "keys": ["action", "issue", "repository", "sender"],
        "steps": [
            {"tool": "parse_github_issue", "args": {"payload": "$.issue"}},
            {"tool": "to_ticket", "args": {"parsed": "$.steps[0]"}},
            {"tool": "validate", "args": {"obj": "$.steps[1]"}},
        ],
        "success_count": 4,
        "fail_count": 0,
        "status": ProcStatus.ACTIVE,
        "last_used": "2026-09-12T00:00:00Z",
    }
    data.update(overrides)
    return ProvenWorkflow.model_validate(data)


def test_proc_steps_are_parsed_into_objects_with_jsonpath_args() -> None:
    p = _proc()
    assert isinstance(p.steps[0], ProcStep)
    assert p.steps[0].tool == "parse_github_issue"
    assert p.steps[0].args == {"payload": "$.issue"}
    assert p.steps[-1].tool == "validate"  # 接入來源事件.feature Rule 13


def test_proc_keeps_the_github_issue_stable_keys() -> None:
    # F02：每一種來源與事件類型有自己的固定必備 top-level key 清單
    assert _proc().keys == ["action", "issue", "repository", "sender"]


@pytest.mark.parametrize("field", ["success_count", "fail_count"])
def test_counters_cannot_be_negative(field: str) -> None:
    with pytest.raises(ValidationError):
        _proc(**{field: -1})


def test_proc_can_be_retired_with_no_last_used() -> None:
    p = _proc(status=ProcStatus.RETIRED, fail_count=3, last_used=None)
    assert p.status is ProcStatus.RETIRED
    assert p.last_used is None


def test_proc_keeps_the_source_context_for_layer_two() -> None:
    # 本計劃選擇（對應 O2）：domain 與 adapter_type 存在 item 上，
    # 因為簽名是雜湊、無法反推第二層比對需要的範圍（D19）。
    p = _proc()
    assert p.domain == "github.com"
    assert p.adapter_type == "ticket"
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：`uv run pytest tests/unit/test_models_rules.py -v`

預期：`1 error`，訊息是
`ImportError: cannot import name 'AuthoringRule' from 'training_kb.models'`。

- [ ] **步驟 3：寫最少的程式讓測試通過**

在 `src/training_kb/models.py` 的**最後面**、空兩行之後接上：

```python
# --- 寫作規則與接入流程記憶 ---


class AuthoringRule(BaseModel):
    """從回饋歸納出來的寫作規則。ERM AUTHORING_RULE；PK = RULE#<rule_id>。

    只有 Feedback Review 產生 candidate（設計 §7.5）；
    只有 Analytics 寫 status 與 validated_at（設計 §12.2）。
    """

    model_config = _ITEM_CONFIG

    rule_id: str  # 例 "R-007"
    rule: str  # 歸納出來的寫作要求
    applies_when: dict[str, str]  # D16：只支援 {"step.type": "click_ui"|"input"|"read"}
    evidence: list[str]  # D15：只存 Feedback ID
    status: RuleStatus
    applied_to: list[str] = Field(default_factory=list)  # D17：由各版 rules_applied 重建
    derived_from: str  # D18：恰好一個裸 version_id
    # 本計劃新增的 metadata 欄位（不是新實體）：F28「同範圍衝突取最近驗證通過者」
    # 需要一個可比較的時間點。由 analytics.apply_rule_status() 寫入（Phase 20）。
    validated_at: str | None = None


class ProcStep(BaseModel):
    """PROC 的一個步驟：工具名稱 + JSONPath 參數（設計文件 §7.2）。

    args 的值一律是 JSONPath 字串，指向事件欄位或前一步輸出，
    絕對不含真實事件值（否則就不能重放到別的事件上）。
    """

    model_config = _ITEM_CONFIG

    tool: str
    args: dict[str, str]


class ProvenWorkflow(BaseModel):
    """已驗證的接入程序。ERM PROVEN_WORKFLOW；PK = PROC#<signature>。

    signature 是結構 SHA-1 的前 16 個十六進位字元（設計 §7.2）。
    fail_count 是「連續」失敗次數，成功重放後歸零，達到 3 就 retired（D20）。

    domain 與 adapter_type：本計劃選擇（對應設計文件第 18 節的 O2）把來源脈絡
    存在 item 上，因為第二層 Jaccard 比對要先限制在「同網域 + 同 adapter 類型」
    的候選範圍（D19），而簽名是雜湊、無法反推。ERM 的 note 說「不新增 domain
    欄位」，這是本計劃與它不同的地方，理由記在本階段文件 §9。
    """

    model_config = _ITEM_CONFIG

    signature: str
    domain: str  # 例 "github.com"
    adapter_type: str  # "ticket" 或 "release"
    keys: list[str]  # 簽名用的 STABLE_KEYS，第二層 Jaccard 比對也用它
    steps: list[ProcStep]
    success_count: int = Field(ge=0)
    fail_count: int = Field(ge=0)
    status: ProcStatus
    last_used: str | None
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：`uv run pytest tests/unit/test_models_rules.py -v`

預期：`11 passed`。

再跑一次全部測試確認沒弄壞前面：`uv run pytest -q` → 全部通過。

- [ ] **步驟 5：commit**

```bash
git add src/training_kb/models.py tests/unit/test_models_rules.py
git commit -m "feat(models): 加入 AuthoringRule 與 ProvenWorkflow"
```

---

### Task 8：`keys.py` 的實體 PK、`META` 與 `parse_pk`

**目的**：把「裸 ID → 帶前綴的 PK」集中在一個檔案，並提供反向解析。

**檔案**：
- 新增：`src/training_kb/keys.py`
- 測試：`tests/unit/test_keys_pk.py`

**介面**：
- 消費：無
- 產出：
  - `META`、`PK_SEPARATOR`、十個 `ENTITY_*` 常數
  - `tutorial_pk`、`version_pk`、`step_pk`、`feature_pk`、`ticket_pk`、`release_pk`、`feedback_pk`、`rule_pk`、`proc_pk`、`ops_pk`、`lock_pk`、`counter_pk`、`config_pk`
  - `parse_pk(pk) -> tuple[str, str]`
  - `entity_of(pk) -> str`（新增項目，`00-總覽.md` §9.2 未列；Phase 03 寫 item 時要填 `entity` 屬性，用它取值才不會跟 PK 前綴不一致）

- [ ] **步驟 1：寫測試**

```python
# tests/unit/test_keys_pk.py
"""PK 的產生與解析。設計文件 §9.1 的鍵表格；O1 的 META 選擇。"""

import pytest

from training_kb.keys import (
    META,
    config_pk,
    counter_pk,
    entity_of,
    feature_pk,
    feedback_pk,
    lock_pk,
    ops_pk,
    parse_pk,
    proc_pk,
    release_pk,
    rule_pk,
    step_pk,
    ticket_pk,
    tutorial_pk,
    version_pk,
)


def test_meta_sk_is_the_fixed_string() -> None:
    # 本計劃選擇（對應 O1）：所有 metadata item 的 SK 一律 "META"
    assert META == "META"


def test_entity_pk_prefixes_match_the_design_table() -> None:
    assert tutorial_pk("prepare-meeting") == "TUTORIAL#prepare-meeting"
    assert version_pk("prepare-meeting@v2") == "VERSION#prepare-meeting@v2"
    assert step_pk("prepare-meeting@v2", 3) == "STEP#prepare-meeting@v2#3"
    assert feature_pk("Prepare") == "FEATURE#Prepare"
    assert ticket_pk("t_881") == "TICKET#t_881"
    assert release_pk("r_42") == "RELEASE#r_42"
    assert feedback_pk("f_12") == "FEEDBACK#f_12"
    assert rule_pk("R-007") == "RULE#R-007"
    assert proc_pk("9f2c41b07ad3e5c8") == "PROC#9f2c41b07ad3e5c8"


def test_execution_pk_prefixes() -> None:
    assert ops_pk("ingest:ticket:t_881") == "OPS#ingest:ticket:t_881"
    assert lock_pk("prepare-meeting") == "LOCK#prepare-meeting"
    assert counter_pk("cluster") == "COUNTER#cluster"
    assert config_pk("feedback_categories") == "CONFIG#feedback_categories"


def test_step_pk_requires_an_index_of_at_least_one() -> None:
    with pytest.raises(ValueError):
        step_pk("prepare-meeting@v2", 0)


def test_pk_builders_reject_empty_bare_ids() -> None:
    for builder in (tutorial_pk, version_pk, feature_pk, ticket_pk, rule_pk):
        with pytest.raises(ValueError):
            builder("")


def test_parse_pk_splits_on_the_first_separator_only() -> None:
    assert parse_pk("TUTORIAL#prepare-meeting") == ("TUTORIAL", "prepare-meeting")
    assert parse_pk("VERSION#prepare-meeting@v2") == ("VERSION", "prepare-meeting@v2")
    # STEP 的裸 ID 自己還帶一個 '#'，必須保留
    assert parse_pk("STEP#prepare-meeting@v2#3") == ("STEP", "prepare-meeting@v2#3")
    assert parse_pk("OPS#ingest:ticket:t_881") == ("OPS", "ingest:ticket:t_881")


@pytest.mark.parametrize("bad", ["TUTORIAL", "#prepare-meeting", "TUTORIAL#", ""])
def test_parse_pk_rejects_malformed_keys(bad: str) -> None:
    with pytest.raises(ValueError):
        parse_pk(bad)


def test_entity_of_returns_the_prefix() -> None:
    # Phase 03 會把這個值寫進 item 的 entity 屬性，讓 scan_entity() 好篩選
    assert entity_of(tutorial_pk("prepare-meeting")) == "TUTORIAL"
    assert entity_of(step_pk("prepare-meeting@v2", 3)) == "STEP"
    assert entity_of(proc_pk("9f2c41b07ad3e5c8")) == "PROC"
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：`uv run pytest tests/unit/test_keys_pk.py -v`

預期：`1 error`，訊息是 `ModuleNotFoundError: No module named 'training_kb.keys'`。

- [ ] **步驟 3：寫最少的程式讓測試通過**

```python
# src/training_kb/keys.py
"""DynamoDB 的鍵：裸 ID 與 PK／SK／target 之間的轉換。

來源：設計文件 §9.1（鍵與原生型別）、§9.2（關係邊）、D03（邏輯欄位一律裸 ID）。

本計劃選擇（對應設計文件第 18 節的 O1）：
所有 metadata item 的 SK 一律用 "META"；TUTORIAL_STEP 保持既定的
REFERENCES#<Feature PK>。O1 尚未由規格確認；若之後有別的答案，
只需要改這個檔案裡的 META 常數。
"""

PK_SEPARATOR = "#"
META = "META"

# entity 屬性的值 = PK 的前綴。Phase 03 寫 item 時一起寫入，讓 Scan 可以篩類型。
ENTITY_TUTORIAL = "TUTORIAL"
ENTITY_VERSION = "VERSION"
ENTITY_STEP = "STEP"
ENTITY_FEATURE = "FEATURE"
ENTITY_TICKET = "TICKET"
ENTITY_RELEASE = "RELEASE"
ENTITY_FEEDBACK = "FEEDBACK"
ENTITY_VIEW = "VIEW"
ENTITY_RULE = "RULE"
ENTITY_PROC = "PROC"

# 執行用 item（不是業務實體）：操作紀錄、鎖、計數器、可擴充設定
ENTITY_OPS = "OPS"
ENTITY_LOCK = "LOCK"
ENTITY_COUNTER = "COUNTER"
ENTITY_CONFIG = "CONFIG"


def _join(entity: str, bare_id: str) -> str:
    if not bare_id:
        raise ValueError(f"{entity} 的裸 ID 不可以是空字串")
    return f"{entity}{PK_SEPARATOR}{bare_id}"


def tutorial_pk(slug: str) -> str:
    """TUTORIAL#<slug>"""
    return _join(ENTITY_TUTORIAL, slug)


def version_pk(version_id: str) -> str:
    """VERSION#<slug>@v<n>"""
    return _join(ENTITY_VERSION, version_id)


def step_pk(version_id: str, index: int) -> str:
    """STEP#<slug>@v<n>#<i>；index 從 1 起算。"""
    if index < 1:
        raise ValueError(f"步驟編號從 1 起算，收到 {index}")
    return _join(ENTITY_STEP, f"{version_id}{PK_SEPARATOR}{index}")


def feature_pk(feature_id: str) -> str:
    """FEATURE#<第一次建立時的名稱>；改名不遷移（D06）。"""
    return _join(ENTITY_FEATURE, feature_id)


def ticket_pk(ticket_id: str) -> str:
    """TICKET#<id>"""
    return _join(ENTITY_TICKET, ticket_id)


def release_pk(release_id: str) -> str:
    """RELEASE#<id>"""
    return _join(ENTITY_RELEASE, release_id)


def feedback_pk(feedback_id: str) -> str:
    """FEEDBACK#<id>"""
    return _join(ENTITY_FEEDBACK, feedback_id)


def rule_pk(rule_id: str) -> str:
    """RULE#<rule_id>，例 RULE#R-007"""
    return _join(ENTITY_RULE, rule_id)


def proc_pk(signature: str) -> str:
    """PROC#<signature>；signature 是結構 SHA-1 的前 16 個十六進位字元。"""
    return _join(ENTITY_PROC, signature)


def ops_pk(operation_id: str) -> str:
    """OPS#<operation_id>；操作紀錄（本計劃選擇，對應 O2）。"""
    return _join(ENTITY_OPS, operation_id)


def lock_pk(slug: str) -> str:
    """LOCK#<slug>；同一篇教學的序列化寫入鎖（本計劃選擇，對應 O2）。"""
    return _join(ENTITY_LOCK, slug)


def counter_pk(name: str) -> str:
    """COUNTER#<name>；原子遞增流水號，例 COUNTER#cluster。"""
    return _join(ENTITY_COUNTER, name)


def config_pk(name: str) -> str:
    """CONFIG#<name>；可擴充設定清單，例 CONFIG#feedback_categories。"""
    return _join(ENTITY_CONFIG, name)


def parse_pk(pk: str) -> tuple[str, str]:
    """把 PK 拆成（類型, 裸 ID）。

    只在**第一個** '#' 切開，因為 STEP 的裸 ID 自己就含一個 '#'：
    parse_pk("STEP#prepare-meeting@v2#3") -> ("STEP", "prepare-meeting@v2#3")
    """
    entity, separator, bare_id = pk.partition(PK_SEPARATOR)
    if not separator or not entity or not bare_id:
        raise ValueError(f"PK 格式應為 <ENTITY>#<裸 ID>，收到 {pk!r}")
    return entity, bare_id


def entity_of(pk: str) -> str:
    """取 PK 的類型前綴；這個值要一起寫進 item 的 entity 屬性。"""
    return parse_pk(pk)[0]
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：`uv run pytest tests/unit/test_keys_pk.py -v`

預期：`11 passed`。

- [ ] **步驟 5：commit**

```bash
git add src/training_kb/keys.py tests/unit/test_keys_pk.py
git commit -m "feat(keys): 加入實體 PK 產生與解析"
```

---

### Task 9：`keys.py` 的 `view_pk` 與關係邊

**目的**：瀏覽紀錄的去重鍵，以及五種關係邊的 SK 組合與解析。

**檔案**：
- 修改：`src/training_kb/keys.py`
- 測試：`tests/unit/test_keys_edges.py`

**介面**：
- 消費：Task 8 的常數與 `parse_pk`
- 產出：
  - `view_pk(tutorial_version, user, ts) -> str`
  - `REL_REFERENCES`、`REL_SUPERSEDES`、`REL_APPLIED_TO`、`REL_ASKS_ABOUT`、`REL_REFERS_TO`、`RELATIONS`
  - `edge_sk(relation, target_pk) -> str`、`parse_edge_sk(sk) -> tuple[str, str]`
  - `parse_step_pk(pk) -> tuple[str, int]`（新增項目，`00-總覽.md` §9.2 未列；Phase 09 要從 STEP item 還原 `TutorialStep.tutorial_version` 與 `index`）

- [ ] **步驟 1：寫測試**

```python
# tests/unit/test_keys_edges.py
"""View 的去重鍵與五種關係邊。設計文件 §9.1（View 的 SHA-256 鍵）、§9.2（邊）。"""

import pytest

from training_kb.keys import (
    REL_APPLIED_TO,
    REL_ASKS_ABOUT,
    REL_REFERENCES,
    REL_REFERS_TO,
    REL_SUPERSEDES,
    RELATIONS,
    edge_sk,
    feature_pk,
    parse_edge_sk,
    parse_step_pk,
    step_pk,
    version_pk,
    view_pk,
)


def test_view_pk_has_the_expected_shape() -> None:
    pk = view_pk("prepare-meeting@v1", "u_01", "2026-08-02T09:00:00Z")
    assert pk.startswith("VIEW#")
    assert len(pk) == len("VIEW#") + 32
    assert all(ch in "0123456789abcdef" for ch in pk.removeprefix("VIEW#"))


def test_same_triple_always_produces_the_same_key() -> None:
    # 重送同一筆瀏覽紀錄會得到同一個 PK，條件寫入就能去重
    a = view_pk("prepare-meeting@v1", "u_01", "2026-08-02T09:00:00Z")
    b = view_pk("prepare-meeting@v1", "u_01", "2026-08-02T09:00:00Z")
    assert a == b


def test_a_different_timestamp_produces_a_different_key() -> None:
    # 同一個人看兩次是兩筆紀錄
    a = view_pk("prepare-meeting@v1", "u_01", "2026-08-02T09:00:00Z")
    b = view_pk("prepare-meeting@v1", "u_01", "2026-08-02T10:00:00Z")
    assert a != b


def test_a_different_user_or_version_produces_a_different_key() -> None:
    base = view_pk("prepare-meeting@v1", "u_01", "2026-08-02T09:00:00Z")
    assert base != view_pk("prepare-meeting@v1", "u_02", "2026-08-02T09:00:00Z")
    assert base != view_pk("prepare-meeting@v2", "u_01", "2026-08-02T09:00:00Z")


def test_view_pk_is_stable_for_non_ascii_values() -> None:
    # ensure_ascii=False：中文不會被轉成 \\uXXXX，所以雜湊在任何環境都一樣
    pk = view_pk("prepare-meeting@v1", "使用者一號", "2026-08-02T09:00:00Z")
    assert pk == view_pk("prepare-meeting@v1", "使用者一號", "2026-08-02T09:00:00Z")


def test_the_five_relation_names_are_fixed() -> None:
    assert RELATIONS == {
        REL_REFERENCES,
        REL_SUPERSEDES,
        REL_APPLIED_TO,
        REL_ASKS_ABOUT,
        REL_REFERS_TO,
    }
    assert sorted(RELATIONS) == [
        "APPLIED_TO",
        "ASKS_ABOUT",
        "REFERENCES",
        "REFERS_TO",
        "SUPERSEDES",
    ]


def test_edge_sk_matches_the_design_examples() -> None:
    assert edge_sk(REL_REFERENCES, feature_pk("Prepare")) == "REFERENCES#FEATURE#Prepare"
    assert (
        edge_sk(REL_SUPERSEDES, version_pk("prepare-meeting@v2"))
        == "SUPERSEDES#VERSION#prepare-meeting@v2"
    )
    assert (
        edge_sk(REL_REFERS_TO, version_pk("prepare-meeting@v1"))
        == "REFERS_TO#VERSION#prepare-meeting@v1"
    )


@pytest.mark.parametrize(
    ("relation", "target"),
    [
        (REL_REFERENCES, "FEATURE#Prepare"),
        (REL_SUPERSEDES, "VERSION#prepare-meeting@v2"),
        (REL_APPLIED_TO, "VERSION#prepare-meeting@v2"),
        (REL_ASKS_ABOUT, "FEATURE#Prepare"),
        (REL_REFERS_TO, "VERSION#prepare-meeting@v1"),
    ],
)
def test_edge_sk_and_parse_edge_sk_round_trip(relation: str, target: str) -> None:
    assert parse_edge_sk(edge_sk(relation, target)) == (relation, target)


def test_edge_sk_rejects_unknown_relation_names() -> None:
    with pytest.raises(ValueError):
        edge_sk("POINTS_AT", "FEATURE#Prepare")


@pytest.mark.parametrize(
    "bad", ["META", "REFERENCES", "REFERENCES#", "#FEATURE#Prepare", "WRONG#x"]
)
def test_parse_edge_sk_rejects_things_that_are_not_edges(bad: str) -> None:
    # repository 讀到 SK == "META" 時要先判斷，不要丟進 parse_edge_sk
    with pytest.raises(ValueError):
        parse_edge_sk(bad)


def test_parse_step_pk_recovers_version_and_index() -> None:
    assert parse_step_pk(step_pk("prepare-meeting@v2", 3)) == ("prepare-meeting@v2", 3)
    assert parse_step_pk("STEP#share-summary@v10#12") == ("share-summary@v10", 12)


@pytest.mark.parametrize(
    "bad", ["VERSION#prepare-meeting@v2", "STEP#prepare-meeting@v2", "STEP#a@v1#x", "STEP#a@v1#0"]
)
def test_parse_step_pk_rejects_bad_keys(bad: str) -> None:
    with pytest.raises(ValueError):
        parse_step_pk(bad)
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：`uv run pytest tests/unit/test_keys_edges.py -v`

預期：`1 error`，訊息是
`ImportError: cannot import name 'REL_APPLIED_TO' from 'training_kb.keys'`
（`from ... import (...)` 會在第一個找不到的名稱就停下來，而排序後第一個是 `REL_APPLIED_TO`）。

- [ ] **步驟 3：寫最少的程式讓測試通過**

先把 `src/training_kb/keys.py` **最上面**的 docstring 之後加上兩行 import：

```python
import hashlib
import json
```

再在檔案**最後面**、空兩行之後接上：

```python
# --- 瀏覽紀錄的去重鍵（設計文件 §9.1「本文件設計選擇」）---

VIEW_HASH_LENGTH = 32


def view_pk(tutorial_version: str, user: str, ts: str) -> str:
    """VIEW# + sha256([tutorial_version, user, ts] 的固定 JSON 編碼) 的前 32 個字元。

    三個細節缺一不可：
    - ensure_ascii=False：中文不要被轉成 \\uXXXX，否則不同設定會算出不同雜湊；
    - separators=(",", ":")：去掉 JSON 預設空白，讓編碼唯一；
    - 用 list 不用 dict：list 順序固定。

    效果：同樣的三元組永遠得到同一個 PK（重送可去重），不同的 ts 得到不同 PK
    （同一人看兩次是兩筆）。副作用是完全同一秒的重複紀錄會被合併，
    但不影響「每版每人最多一次」的指標分母。
    """
    payload = json.dumps([tutorial_version, user, ts], ensure_ascii=False, separators=(",", ":"))
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return _join(ENTITY_VIEW, digest[:VIEW_HASH_LENGTH])


# --- 關係邊（設計文件 §9.2）---
# 五個關係名稱是固定的，不可以新增。邊的格式：PK = 起點、SK = 關係#終點、target = 終點。

REL_REFERENCES = "REFERENCES"  # STEP -> FEATURE
REL_SUPERSEDES = "SUPERSEDES"  # VERSION -> VERSION
REL_APPLIED_TO = "APPLIED_TO"  # RULE -> VERSION
REL_ASKS_ABOUT = "ASKS_ABOUT"  # TICKET -> FEATURE
REL_REFERS_TO = "REFERS_TO"  # FEEDBACK -> VERSION

RELATIONS: frozenset[str] = frozenset(
    {REL_REFERENCES, REL_SUPERSEDES, REL_APPLIED_TO, REL_ASKS_ABOUT, REL_REFERS_TO}
)


def edge_sk(relation: str, target_pk: str) -> str:
    """組出邊的 SK，例 edge_sk("REFERENCES", "FEATURE#Prepare") -> "REFERENCES#FEATURE#Prepare"。

    ERM 的不變條件是 sk = 關係# + target。只從 target_pk 組 SK，
    就不可能出現「SK 和 target 不一致」的資料。
    """
    if relation not in RELATIONS:
        raise ValueError(f"未知的關係名稱 {relation!r}；合法值為 {sorted(RELATIONS)}")
    if not target_pk:
        raise ValueError("邊的終點 PK 不可以是空字串")
    return f"{relation}{PK_SEPARATOR}{target_pk}"


def parse_edge_sk(sk: str) -> tuple[str, str]:
    """把邊的 SK 拆成（關係名, 終點 PK）。

    metadata item 的 SK 是 "META"，不是邊；呼叫前要先判斷 sk == META，
    否則這裡會丟 ValueError。
    """
    relation, separator, target_pk = sk.partition(PK_SEPARATOR)
    if not separator or relation not in RELATIONS or not target_pk:
        raise ValueError(f"不是合法的關係 SK：{sk!r}")
    return relation, target_pk


def parse_step_pk(pk: str) -> tuple[str, int]:
    """把 "STEP#prepare-meeting@v2#3" 拆成 ("prepare-meeting@v2", 3)。

    Phase 09 從 STEP item 還原 TutorialStep 時要用；version_id 自己含 '@v'，
    所以用 rpartition 從最後一個 '#' 切。
    """
    entity, bare_id = parse_pk(pk)
    if entity != ENTITY_STEP:
        raise ValueError(f"不是 STEP 的 PK：{pk!r}")
    version_id, separator, index_text = bare_id.rpartition(PK_SEPARATOR)
    if not separator or not version_id or not index_text.isdigit():
        raise ValueError(f"STEP PK 格式應為 STEP#<slug>@v<n>#<i>，收到 {pk!r}")
    index = int(index_text)
    if index < 1:
        raise ValueError(f"步驟編號從 1 起算，收到 {pk!r}")
    return version_id, index
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：`uv run pytest tests/unit/test_keys_edges.py -v`

預期：`23 passed`。

再跑一次全部測試：`uv run pytest -q` → 全部通過。

- [ ] **步驟 5：commit**

```bash
git add src/training_kb/keys.py tests/unit/test_keys_edges.py
git commit -m "feat(keys): 加入 view_pk 與關係邊的鍵"
```

---

## 7. 完成檢查清單

- [ ] `uv run pytest -q` → 結尾是 `157 passed, 1 skipped`（**0 failed、0 error**）；本階段新增約 119 個測試。
- [ ] `uv run ruff check .` → `All checks passed!`；`uv run ruff format --check .` → 沒有 `Would reformat`。
- [ ] 十個實體、七個枚舉都在：

  ```bash
  uv run python -c "from training_kb import models as m; print([n for n in ('Ticket','Release','Feedback','TutorialView','Feature','Tutorial','TutorialVersion','TutorialStep','AuthoringRule','ProvenWorkflow') if hasattr(m,n)])"
  ```

  預期：印出十個名稱的完整清單。
- [ ] 手動試一次錯誤值被擋下來：

  ```bash
  uv run python -c "from training_kb.models import Feedback; Feedback(id='f_1',tutorial_version='a@v1',rating=6,user='u_01',category=None,comment=None,ts='2026-08-01T00:00:00Z')"
  ```

  預期：丟 `pydantic_core._pydantic_core.ValidationError`，訊息含 `less_than_equal`。
- [ ] 手動確認 View 的去重鍵：

  ```bash
  uv run python -c "from training_kb.keys import view_pk as v; print(v('prepare-meeting@v1','u_01','2026-08-02T09:00:00Z')); print(v('prepare-meeting@v1','u_01','2026-08-02T09:00:00Z')); print(v('prepare-meeting@v1','u_01','2026-08-02T10:00:00Z'))"
  ```

  預期：前兩行**完全相同**，第三行不同。
- [ ] 手動確認邊的往返：

  ```bash
  uv run python -c "from training_kb.keys import edge_sk,parse_edge_sk,feature_pk; sk=edge_sk('REFERENCES',feature_pk('Prepare')); print(sk, parse_edge_sk(sk))"
  ```

  預期：印出 `REFERENCES#FEATURE#Prepare ('REFERENCES', 'FEATURE#Prepare')`。
- [ ] 對照 `docs/spec/erm.dbml`，確認十個實體的欄位名稱一個不漏、拼字一致。
- [ ] `git log --oneline | head -10` → 看得到 Task 1–9 的 9 個 commit。

**這一階段不能宣稱什麼**：S0 的完整檢查是「O2／O3 的最小整合驗證有可追溯結果；來源 ID、白名單與模型可用性已確認」。本階段只完成了資料形狀，O1 的 META 選擇還沒經過真實 DynamoDB 驗證（Phase 03、04），O2 的 PROC 來源脈絡也還沒被實際重放驗證（Phase 11、12）。

---

## 8. 常見錯誤與排除

**1. `ImportError: cannot import name 'X' from 'training_kb.models'`，但你確定已經寫了**

- 原因：程式碼貼到了錯的位置（例如貼進某個 class 的內部，變成方法），或是檔案還沒存檔。
- 解法：`uv run python -c "import training_kb.models as m; print([n for n in dir(m) if not n.startswith('_')])"` 看實際有哪些名稱。注意每個 Task 的 step 3 都說「接在**檔案最後面**」，縮排必須是 0。

**2. `TypeError: non-default argument follows default argument`**

- 症狀：改檔案時把某個模型換成了 `@dataclass`，就出現這個錯。
- 原因：dataclass 不允許必填欄位排在有預設值的欄位後面，pydantic `BaseModel` 允許。
- 解法：本階段的十個實體都必須是 `BaseModel`，不要改成 dataclass。只有 Phase 01 的 `Settings`、`Thresholds` 是 dataclass。

**3. `ValidationError: Input should be 'github_issue', 'discord' or 'email'`**

- 症狀：明明資料看起來沒問題卻被拒絕。
- 原因：值真的不合法（例如從 Demo 種子檔讀到 `"Github_Issue"`，大小寫不同）。枚舉比對是**區分大小寫**的。
- 解法：修資料，不要為了讓它通過就在枚舉裡加值。設計文件 §7.1 明說「非法枚舉由入口回傳操作失敗」。

**4. `view_pk` 在兩台電腦上算出不同結果**

- 原因：`json.dumps` 少了 `ensure_ascii=False` 或 `separators=(",", ":")`，或者參數順序寫反了。
- 解法：照 Task 9 的程式碼逐字比對。這三個參數是設計文件 §9.1 指定的編碼方式，改任何一個都會讓舊資料對不上。

**5. `ValueError: 不是合法的關係 SK：'META'`**

- 症狀：Phase 03 讀某個 PK 的全部 item 時炸掉。
- 原因：`Query(PK=...)` 會同時拿到 metadata item（SK=`META`）與邊，程式把 metadata 也丟進 `parse_edge_sk`。
- 解法：先判斷 `if item["SK"] == keys.META: continue`，再處理邊。這是刻意的設計：`parse_edge_sk` 只接受真正的邊。

**6. `AttributeError: 'str' object has no attribute 'value'`**

- 症狀：對 `t.status` 呼叫 `.value` 出錯。
- 原因：`StrEnum` 的成員**本身就是字串**，你可以直接 `t.status == "active"`，不需要 `.value`。從 `model_validate` 出來的一定是枚舉成員，但如果你自己用 `Tutorial.model_construct()` 繞過驗證，拿到的就是原始字串。
- 解法：不要用 `model_construct()`；比較時直接用 `is TutorialStatus.ACTIVE` 或 `== "active"`。

---

## 9. 這階段不做的事

| 不做的事 | 留給哪一階段 |
|---|---|
| 把模型寫進 DynamoDB／讀回來（`model_dump()`、`model_validate()` 的實際使用） | Phase 03 |
| 檢查 `Feedback.category` 是不是核定類別或「待分類」（要讀 `CONFIG#feedback_categories`） | Phase 15 |
| 檢查 `renamed` 的 `old_name`／`new_name` 有沒有值並回報欄位名 | Phase 10 的 `validate_release()` |
| 檢查 `rating` 是不是「嚴格的整數型別」（pydantic 寬鬆模式會把 `"3"` 轉成 `3`） | Phase 10、15 的 `validate_*()` |
| 檢查 `TutorialContent` 每步的 `feature_id` 是不是真的存在 | Phase 07 的 `validate_content()` |
| 檢查 `applies_when` 的 key 一定是 `step.type`、值一定是三種之一 | Phase 06 的 `select_active_rules()` |
| 產生 `signature`（結構 SHA-1）與 `STABLE_KEYS` | Phase 11 |
| 寫 `AuthoringRule.status` 與 `validated_at` | Phase 20 的 `analytics.apply_rule_status()`——**只有那裡可以寫** |
| 產生 S3 的路徑字串（`tutorials/<slug>/v<n>.md`、`site/...`） | Phase 07（`content.py`）、Phase 08（`site_keys()`） |
| 決定 `Ticket.embedding` 怎麼算 | Phase 05 |

**與 ERM 不同的地方（要記錄，不要當成 ERM 寫錯）**：

1. `ProvenWorkflow` 多了 `domain` 與 `adapter_type` 兩個欄位。ERM 的 note 說「不新增 sender、domain 或專案欄位；比對時由事件與既有 keys／簽名脈絡取得範圍」，但設計文件 §7.2 同時承認「保存這份脈絡的做法列於第 18 節」（也就是 **O2 尚未定案**）。**本計劃選擇（對應 O2）**把脈絡存在 item 上，因為 D19 要求第二層先限縮在「同網域 + 同 adapter 類型」，而簽名是雜湊、無法反推。
2. `AuthoringRule` 多了 `validated_at`。ERM 沒有這個欄位，但 F28 要求「同範圍衝突取最近驗證通過者」，需要可比較的時間點。它是 RULE item 上的一個 metadata 屬性，**不是第十一個實體**。
3. `Ticket.feature_ids` 加了 `max_length=1`。ERM note 說「長度為 0 或 1」，D04 也是同一個答案；這裡把它變成型別層的限制。

---

## 10. 對照：設計章節與 Rule 編號

本階段只提供**資料形狀**。表格第三欄寫「哪個 Task 讓這條 Rule 在型別層就成立」，第四欄寫「哪個階段做業務驗收」。**本階段通過不代表這些 Rule 已經驗收完成。**

| Rule 來源檔 | Rule 編號與原文 | 本階段哪個 Task | 業務驗收階段 |
|---|---|---|---|
| `建立教學版本.feature` | Rule 1：新 Tutorial 的版本從 v1 起算 | Task 2：`make_version_id` 拒絕 n < 1 | Phase 07 |
| `建立教學版本.feature` | Rule 3：新版以 supersedes 關聯同一篇教學的前一版 | Task 3：`TutorialVersion.supersedes`；Task 9：`REL_SUPERSEDES` | Phase 07 |
| `建立教學版本.feature` | Rule 4：每次建立版本都記錄引起變更的 reason | Task 3：`reason` 為必填欄位 | Phase 07 |
| `建立教學版本.feature` | Rule 6：TutorialVersion 的 s3_key 指向該版本完整內容 | Task 3：`s3_key` 為必填欄位 | Phase 07 |
| `建立教學版本.feature` | Rule 8：建立 TutorialStep 時保存 references Feature 邊 | Task 3：`TutorialStep.feature_id`；Task 9：`edge_sk(REL_REFERENCES, ...)` | Phase 07 |
| `建立教學版本.feature` | Rule 9：沒有 Feature 或引用多個 Feature 的步驟不可保存 | Task 3、Task 4：`feature_id` 是單一必填字串，型別上不可能是零個或多個 | Phase 07 |
| `建立教學版本.feature` | Rule 10：references 邊的 target 等於 SK 中的關係終點 | Task 9：`edge_sk` 只從 `target_pk` 組 SK；`parse_edge_sk` 往返驗證 | Phase 03、07 |
| `分析工單.feature` | Rule 1：每則 Ticket 在接入分析時計算一次並儲存 1024 維 embedding | Task 5：`Ticket.embedding: list[float] \| None` | Phase 13 |
| `分析工單.feature` | Rule 6：一張 Ticket 對應零或一個 Feature | Task 5：`feature_ids` 的 `max_length=1`（D04） | Phase 13 |
| `分析工單.feature` | Rule 11：新教學的完整內容包含 Title、Problem、Prerequisites、Steps 與 Expected Outcome | Task 4：`TutorialContent` 五個必填欄位 | Phase 07、13 |
| `分析工單.feature` | Rule 12：產生新教學時同時輸出每步提到的 Feature | Task 4：`StepDraft.feature_id` | Phase 07、13 |
| `分析工單.feature` | Rule 13：新教學的每個步驟恰好引用一個 Feature | Task 4：`StepDraft.feature_id` 是單一必填字串 | Phase 07 |
| `分析工單.feature` | Rule 14：新教學第一版的 reason 使用 gap 加上來源 cluster_id | Task 3：`reason`；Task 3：`Tutorial.cluster_id` | Phase 13 |
| `收集教學回饋.feature` | Rule 3：Feedback 的 rating 只能為 1 到 5 的整數 | Task 6：`Field(ge=1, le=5)` | Phase 15 |
| `收集教學回饋.feature` | Rule 5：Feedback Category 必須屬於核定類別表或待分類 | Task 1：`APPROVED_CATEGORIES_DEFAULT`、`PENDING_CATEGORY` | Phase 15 |
| `收集教學回饋.feature` | Rule 7：回饋關聯到提交時指定的 TutorialVersion | Task 6：`tutorial_version`；Task 9：`REL_REFERS_TO` | Phase 15 |
| `收集教學回饋.feature` | Rule 9：Feedback 接入時必須提供穩定使用者 ID | Task 6：`user` 為必填欄位（D11、D23） | Phase 15 |
| `接入來源事件.feature` | Rule 21：正規化物件必須具有 schema 的必填欄位 | Task 5、Task 6：pydantic 必填欄位 | Phase 10 |
| `接入來源事件.feature` | Rule 22：Ticket 接入時 id、source、text、author、ts 與 project_id 必填 | Task 5：六個欄位都沒有預設值 | Phase 10 |
| `接入來源事件.feature` | Rule 23：Release 接入時即完成功能與種類解析 | Task 5：`feature`、`kind` 為必填欄位 | Phase 10 |
| `接入來源事件.feature` | Rule 24：正規化物件的 id 直接使用已全域唯一的上游識別碼 | Task 5：`id` 存裸上游 ID；Task 8：前綴只在 `ticket_pk`／`release_pk` 加 | Phase 10 |
| `接入來源事件.feature` | Rule 25：正規化物件的枚舉欄位必須使用合法值 | Task 1 的七個 StrEnum + Task 5、6 的欄位型別 | Phase 10 |
| `依改版更新教學.feature` | Rule 2：改名前後的 alias 對應同一個 Feature 節點 | Task 4：`Feature.aliases` | Phase 16 |
| `依改版更新教學.feature` | Rule 3：改名不變更第一次建立的 Feature 主鍵 | Task 4：`feature_id` 與 `name` 分開；Task 8：`feature_pk(feature_id)` | Phase 16 |
| `套用教學規則.feature` | Rule 6：套用規則的版本記錄於規則的 applied_to | Task 7：`applied_to`；Task 9：`REL_APPLIED_TO` | Phase 19、20 |
| `套用教學規則.feature` | Rule 7：版本的 rules_applied 記錄本次套用的規則 | Task 3：`rules_applied`（D17 的權威來源） | Phase 06、07 |
| `提出教學規則.feature` | Rule 2：Authoring Rule 保留可追溯的 Feedback 證據 | Task 7：`evidence: list[str]`（D15） | Phase 18 |
| `提出教學規則.feature` | Rule 3：Authoring Rule 記錄 applies_when 適用範圍 | Task 7：`applies_when: dict[str, str]`（D16） | Phase 18 |
| `提出教學規則.feature` | Rule 4：Authoring Rule 記錄 derived_from 來源版本 | Task 7：`derived_from` 為必填單一值（D18） | Phase 18 |
| `提出教學規則.feature` | Rule 5：Authoring Rule 記錄歸納出的寫作要求 | Task 7：`rule` 為必填欄位 | Phase 18 |
| `提出教學規則.feature` | Rule 6：MVP 的教學與產品功能識別碼在單一專案範圍內唯一 | Task 8：PK 不含專案維度（D01） | Phase 03 |
| `查詢知識圖譜.feature` | Rule 1：查詢某起點的關係使用該起點的 PK | Task 8：`parse_pk` 與各 `*_pk` | Phase 09 |
| `查詢知識圖譜.feature` | Rule 2：查詢誰引用 Feature 時使用 by_target 的 target | Task 9：`edge_sk` 的終點就是 target | Phase 09 |
| `發布教學版本.feature` | Rule 4：Tutorial 的 current_version 指向目前教學版本 | Task 3：`current_version`（預設 None，F37） | Phase 08 |
| `發布教學版本.feature` | Rule 5：已上架的版本具有 published_at | Task 3：`published_at`（預設 None，D25） | Phase 08 |
| `檢視學習指標.feature` | Rule 5：看過教學又開票的同一人比對穩定使用者 ID | Task 5：`Ticket.author`；Task 6：`Feedback.user`、`TutorialView.user`（D23） | Phase 19 |
| `檢視學習指標.feature` | Rule 7：已學規則數依 RULE item 的 status 分別計數 | Task 1：`RuleStatus`；Task 7：`AuthoringRule.status` | Phase 19 |
| `檢視學習指標.feature` | Rule 8：規則套用次數等於 applied_to 清單長度 | Task 7：`applied_to` | Phase 19 |

---

## 11. 參考來源

**設計文件章節**（`docs/design/training-kb.md`）

- §1：名詞表（Tutorial／TutorialVersion、Feature、Release／publish、Step／Task、Rote／PROC、candidate／active／retired 的區別）。
- §7.1：四種輸入的必要資料與合法值表；Feedback `ts` 與 View `ts` 的差別。
- §7.2：PROC 的簽名、steps 只含 JSONPath、來源脈絡的保存待 O2 決定。
- §8.1：版本鏈與 `reason` 的三種格式；§8.2：`published_at = null` 代表未發布。
- §9.1：十個實體的 PK／SK 表格、View 的 SHA-256 鍵、裸 ID 與前綴的分工。
- §9.2：五種關係邊的格式與範例；`sk = 關係# + target` 的不變條件。
- §12.1、§12.2：規則狀態與指標所需的欄位。
- §18：待確認事項 O1（metadata SK）、O2（PROC 來源脈絡與操作紀錄）。
- §19.1：D01–D29 的最新答案，本階段引用 D01、D02、D03、D04、D05、D06、D07、D08、D11、D12、D13、D15、D16、D17、D18、D19、D20、D21、D22、D23、D24、D25、D29。
- §19.2：F02、F14、F28、F29、F37、F54。
- §20.1、§20.2、§20.4、§20.6、§20.7、§20.8、§20.9、§20.10、§20.11、§20.12：本階段 §10 對照表引用的 Rule 原文。

**資料模型**：`docs/spec/erm.dbml`——十個 Table 的欄位與 note，以及 11 個 Ref。本階段的欄位名稱一律以它為準。

**功能規格**：`docs/spec/features/建立教學版本.feature`、`分析工單.feature`、`收集教學回饋.feature`、`接入來源事件.feature`、`依改版更新教學.feature`、`套用教學規則.feature`、`提出教學規則.feature`、`查詢知識圖譜.feature`、`發布教學版本.feature`、`檢視學習指標.feature`。

**外部文件**（本次以 Context7 MCP 查證）

| 主題 | 連結 |
|---|---|
| pydantic v2：Enum／IntEnum 欄位的驗證與 `ValidationError` | https://github.com/pydantic/pydantic/blob/main/docs/api/standard_library_types.md |
| pydantic v2：`Field(ge=...)`／`Field(le=...)` 的錯誤型別（`greater_than_equal`、`less_than_equal`） | https://github.com/pydantic/pydantic/blob/main/docs/errors/validation_errors.md |
| pydantic v2：`model_validate` 與缺欄位、超出範圍的錯誤輸出 | https://github.com/pydantic/pydantic/blob/main/docs/examples/files.md |
| pytest：`parametrize` 與自訂 marker | https://github.com/pytest-dev/pytest/blob/main/doc/en/example/markers.rst |
| DynamoDB：單表設計的讀取一致性與交易限制（Phase 03 會用到） | https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/HowItWorks.ReadConsistency.html ｜ https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/transaction-apis.html |

---

**下一步**：`03-Phase03-Repository-本機儲存層.md`。
