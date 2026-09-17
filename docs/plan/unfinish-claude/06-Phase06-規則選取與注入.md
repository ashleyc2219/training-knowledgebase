# Phase 06：規則選取與注入

| 項目 | 內容 |
|---|---|
| 上一階段 | Phase 05：Writing-Bedrock 呼叫與輸出驗證（`05-Phase05-Writing-Bedrock呼叫與輸出驗證.md`） |
| 下一階段 | Phase 07：Content-建立教學版本（`07-Phase07-Content-建立教學版本.md`） |
| 對應設計文件章節 | §7.6、§8.2、§12.2（`docs/design/training-kb.md`） |
| 對應交付切片 | S7 前置（設計文件第 16 節） |
| 預估時間 | 約 2 小時 |
| 做完會得到 | 一個純計算模組，能挑出「這次寫作真正該用的 active 規則」，產生要貼進 prompt 的文字，並回報實際注入了哪些規則 ID。 |

---

## 1. 這階段做完會得到什麼

做完之後，你會有 `src/training_kb/writing/rules.py`，裡面有四個函式：

| 函式 | 一句話 |
|---|---|
| `select_active_rules(rules, step_type)` | 給我全部規則和一種步驟型態，回傳這次該用的規則。 |
| `render_rules_block(rules)` | 把規則變成一段可以直接貼進 prompt 的文字。 |
| `applied_rule_ids(rules)` | 回傳這些規則的 ID 清單（去重、保持順序）。 |
| `rules_for_content(rules, step_types)` | 上面三個的組合包，一次回傳「prompt 文字」與「ID 清單」。 |

這四個函式**完全不碰 AWS、不呼叫模型、不讀資料庫**，只是把一份 list 換成另一份 list。所以它們全部用 `tests/unit/` 的純邏輯測試就能測完，執行只要不到一秒。

之後三個地方會用到它：

- Phase 13 的 CREATE（Ticket Analysis 寫第一版教學）
- Phase 16 的 UPDATE（Release Note Update 改寫命中的步驟）
- Phase 17 的 REFINE（Feedback Review 改寫被診斷出問題的步驟）

這階段沒有任何東西會寫進 DynamoDB 或 S3。

---

## 2. 它在整張地圖的位置

```text
基礎層        01 骨架 -> 02 模型與鍵 -> 03 Repository(本機) -> 04 AWS 基礎建設
                                                                    |
AI 與內容層   05 Writing(Bedrock) -> 06 規則注入 -> 07 建立版本 -> 08 發布與退役 -> 09 圖譜查詢
                                    ^^^^^^^^^^^                                        |
                                    你在這裡                                           |
接入層        10 Ingress 驗簽 -> 11 Rote 判定 -> 12 Rote Agent -------------------------+
                                                                                       |
流程層        13 Ticket Analysis -> 14 Step Functions 上線 -> 15 Feedback/View 匯入 -> 16 Release Update
                                                                                       |
學習層        17 Review:REFINE -> 18 Review:候選規則+排程 -> 19 Analytics 指標 -> 20 規則驗證
                                                                                       |
展示與驗收層  21 Demo 種子資料 -> 22 靜態教學站 -> 23 Demo 控制台 -> 24 失敗復原驗收 -> 25 安全與當日準備
```

這一階段夾在「會呼叫 Bedrock 的 Writing 模組」（Phase 05）和「會寫版本的 Content 模組」（Phase 07）中間。它是三條流程共用的小零件，先做好它，後面三條流程就不必各寫一份。

---

## 3. 開始前檢查

依序執行下列指令。每一條都要看到預期輸出才往下做。

- [ ] **1. 專案可以跑測試**

執行：

```bash
cd ~/AWS-Hackathon
uv run pytest -q
```

預期：看到類似 `12 passed in 0.40s` 的結果，沒有 `error`。如果出現 `No such file or directory: pyproject.toml`，代表 Phase 01 還沒做完。

- [ ] **2. Phase 02 的模型有 `AuthoringRule` 與 `validated_at` 欄位**

執行：

```bash
uv run python -c "from training_kb.models import AuthoringRule; print(sorted(AuthoringRule.model_fields))"
```

預期輸出（順序是排序過的）：

```text
['applied_to', 'applies_when', 'derived_from', 'evidence', 'rule', 'rule_id', 'status', 'validated_at']
```

如果少了 `validated_at`，回 Phase 02 補上。`validated_at` 是本計劃為了落實 F28（設計文件第 19.2 節的功能決策編號）加的欄位，不是新實體。

- [ ] **3. Phase 02 的枚舉可以用**

執行：

```bash
uv run python -c "from training_kb.models import RuleStatus, StepType; print(list(RuleStatus), list(StepType))"
```

預期輸出：

```text
[<RuleStatus.candidate: 'candidate'>, <RuleStatus.active: 'active'>, <RuleStatus.retired: 'retired'>] [<StepType.click_ui: 'click_ui'>, <StepType.input: 'input'>, <StepType.read: 'read'>]
```

- [ ] **4. Phase 01 的 `clock.parse_iso` 可以解析 ISO 時間**

執行：

```bash
uv run python -c "from training_kb.clock import parse_iso; print(parse_iso('2026-08-01T00:00:00Z'))"
```

預期輸出：

```text
2026-08-01 00:00:00+00:00
```

- [ ] **5. Phase 05 已經把 `writing/` 這個資料夾建好**

執行：

```bash
ls src/training_kb/writing/
```

預期輸出（至少要有這四個檔）：

```text
__init__.py	client.py	prompts.py	schemas.py
```

---

## 4. 名詞小抄

| 名詞 | 白話解釋 | 在本階段哪裡用到 |
|---|---|---|
| Authoring Rule（教學規則） | 一句「寫教學時必須怎麼寫」的要求，例如「點按鈕的步驟要寫出按鈕在哪一頁、哪個位置、點下去會怎樣」。它是系統從使用者回饋歸納出來的，不是人手寫的設定。 | 本階段全部函式的輸入。 |
| `status`（規則狀態） | 規則的生命週期，只有三種值：`candidate`（剛提出，還沒驗證）、`active`（驗證過，可以用）、`retired`（驗證失敗或衝突，停用）。 | `select_active_rules` 只放行 `active`。 |
| `applies_when`（適用範圍） | 說明這條規則適用於哪種步驟，是一個只有一個鍵的字典，例如 `{"step.type": "click_ui"}`。 | `select_active_rules` 的篩選條件。 |
| `step.type`（步驟型態） | 一個教學步驟的動作種類，只有三種：`click_ui`（點畫面上的東西）、`input`（輸入文字）、`read`（閱讀畫面上的資訊）。 | 篩選規則的唯一依據。 |
| `validated_at`（最近驗證時間） | 這條規則最近一次通過驗證、被 Analytics 改成 `active` 的時間（ISO 8601 字串，例 `2026-08-25T00:00:00Z`）。 | 同一適用範圍有多條 active 規則時，用它決定誰勝出。 |
| prompt | 送給大型語言模型的指示文字。這裡指「寫教學」或「改寫步驟」時送出去的那段話。 | `render_rules_block` 產生的文字會被貼進 prompt。 |
| `rules_applied` | 記在教學版本上的清單，寫著「這一版寫作時實際注入了哪些規則 ID」。 | `applied_rule_ids` 的回傳值就是要寫進去的東西（Phase 07 負責寫）。 |
| 注入（inject） | 把規則文字真的放進送給模型的 prompt 裡。只有「真的放進去」才算注入。 | F29 的判準。 |
| D16、D17、F28、F29 | 設計文件第 19 節的決策編號。D 開頭是資料決策，F 開頭是功能決策。本階段只跟這四條有關。 | 第 5 節與第 10 節。 |
| StrEnum | Python 3.11 之後內建的枚舉型別，它的成員同時也是字串，所以 `StepType.click_ui == "click_ui"` 會是 `True`。 | 寫測試與比較 `applies_when` 的值時會遇到。 |

---

## 5. 設計說明

### 5.1 為什麼要有這個模組

如果不做這個模組，Phase 13、16、17 三條流程各自都要寫一次「去規則庫挑規則」的程式。三份程式很容易寫出三種不同行為——例如其中一份不小心把 `candidate` 也放進去了。設計文件 §7.6 明說「CREATE／UPDATE／REFINE 都在寫作前取 active 規則」，所以這裡集中做一次。

### 5.2 資料流

```text
規則庫（Phase 03 的 repo.list_rules() 讀出來的 list[AuthoringRule]）
        |
        |  (1) 只留 status == active            <- 套用教學規則 Rule 2、F27
        v
  candidate 全部丟掉、retired 全部丟掉
        |
        |  (2) 只留 applies_when 命中這次的 step.type   <- D16、套用教學規則 Rule 3
        v
  例如 step_type = click_ui，只留 {"step.type": "click_ui"} 的規則
        |
        |  (3) 同一適用範圍剩下多條時，只留 validated_at 最新的一條   <- F28
        v
    最多一條規則
        |
        +---------------------------+
        |                           |
        v                           v
render_rules_block(rules)     applied_rule_ids(rules)
  "寫作規則（必須…）：..."       ["R-007"]
        |                           |
        v                           v
  貼進寫作 prompt            Phase 07 寫進版本的 rules_applied
  （真的送出去才算注入）        （F29：只記真的注入的）
```

左右兩條線**必須同時發生**。如果 prompt 沒有真的帶上規則文字，就不可以把 ID 寫進 `rules_applied`；反過來也一樣。這就是 F29 的意思：「只記錄本次寫作 prompt 實際注入的規則，原文複製帶來的效果不計本次套用」。

### 5.3 三件一定要記住的事

**（一）candidate 絕對不進 prompt。**

規則剛被提出來的時候是 `candidate`，它的效果還沒被驗證過。設計文件 §12.2 說「一般寫作只讀 active；只有 Analytics 能寫驗證後狀態」；F27 的答案 B 說黑客松只從「明示的種子試用版本」匯入 candidate 的成效，正式寫作不自動試用 candidate。所以 `select_active_rules` 的第一道過濾就是 `status == active`，這不是效能考量，是規格要求。

**（二）`applies_when` 只有一種形狀。**

D16 的答案是 A：「MVP 僅支援 step.type 等於 click_ui、input 或 read 的單一條件」。所以合法的 `applies_when` 只有三種：

```text
{"step.type": "click_ui"}
{"step.type": "input"}
{"step.type": "read"}
```

其他任何寫法都不算命中，包含：

```text
{"step.type": "hover"}                       <- 值不是三種合法步驟型態
{"step.type": "click_ui", "slug": "share"}   <- 兩個條件，MVP 不支援
{"text": "contains(按鈕)"}                    <- 欄位不是 step.type
{}                                            <- 空的，沒有範圍
```

程式遇到這些不是拋錯誤，而是**當成不命中、跳過**。理由是設計文件 §7.6 說衝突處理「不停止寫作」；一條長相怪異的規則不應該讓整篇教學寫不出來。真正要把這種規則擋掉是 Phase 18（提出 candidate 時就驗證格式）與 Phase 20（驗證狀態）的責任。

**（三）同一適用範圍只用一條。**

F28 的答案是 B：「同一適用範圍內只採用最近驗證通過的規則，舊規則保留歷史但本次不套用」。因為 D16 把 `applies_when` 限制成單一 `step.type` 條件，所以「同一適用範圍」就等於「同一個 step.type」。

**本計劃選擇：** 寫作當下不再呼叫模型判斷兩條規則有沒有真的衝突（那是 Phase 20 的 Analytics 工作，見設計 §12.2 與 F55）。寫作時採用一條確定性規則：同一個 `step.type` 裡面，只注入 `validated_at` 最新的那一條。這樣的好處是同一批輸入永遠得到同一個結果，測試好寫；壞處是兩條其實不衝突的規則也只會用到一條。設計文件 §7.6 明說「不新增 priority，也不讓寫作模型自行取捨」，所以不可以用其他方式排序。

平手怎麼辦？依序看：

```text
1. validated_at 比較新的贏
2. 都沒有 validated_at（或兩者相同）時，rule_id 字串較小的贏（例如 "R-007" 勝過 "R-012"）
```

第 2 條是**本計劃選擇**，目的只是讓結果可預測；設計文件沒有規定平手怎麼辦。

### 5.4 模組與資料結構

```text
src/training_kb/
  writing/
    __init__.py
    client.py      BedrockWriter / FakeWriter / CallTrace      (Phase 05)
    schemas.py     模型輸出的 pydantic schema                   (Phase 05)
    prompts.py     各 prompt 函式                               (Phase 05)
    rules.py   <-- 這階段要寫的檔案

tests/
  unit/
    test_writing_rules.py   <-- 這階段要寫的測試
```

一條 `AuthoringRule` 長這樣（欄位定義在設計文件 §9.1 與 `docs/spec/erm.dbml`）：

```text
AuthoringRule
  rule_id       "R-007"                        規則編號，唯一
  rule          "點 UI 的步驟要寫出頁面、按鈕位置與點擊結果"   規則內容，會被放進 prompt
  applies_when  {"step.type": "click_ui"}      適用範圍，只有一個鍵
  evidence      ["f_12", "f_15", ...]          證據：提出這條規則時引用的 Feedback ID
  status        "candidate" | "active" | "retired"
  applied_to    ["prepare-meeting@v2"]         投影欄位，由各版本的 rules_applied 重建（D17）
  derived_from  "prepare-meeting@v1"           這條規則是從哪一版的回饋歸納出來的，恰好一個
  validated_at  "2026-08-25T00:00:00Z" 或 None 最近一次驗證通過的時間（本計劃為 F28 新增）
```

`applied_to` 與 `rules_applied` 講的是同一件事，D17 的答案是 A：**以版本的 `rules_applied` 為權威**，規則上的 `applied_to` 清單與 DynamoDB 的 `APPLIED_TO` 邊都是可以由它重建的投影。本階段只負責產生「這次要寫進 `rules_applied` 的 ID 清單」，不負責寫任何一邊。

---

## 6. 工作項目

### Task 1：只挑出 active 且適用範圍命中的規則

**目的**：寫出 `select_active_rules` 的前兩道過濾：狀態必須是 active，`applies_when` 必須命中這次的步驟型態。

**檔案**：
- 新增：`src/training_kb/writing/rules.py`
- 測試：`tests/unit/test_writing_rules.py`

**介面**：
- 消費：`training_kb.models.AuthoringRule`、`training_kb.models.RuleStatus`、`training_kb.models.StepType`（Phase 02）
- 產出：`training_kb.writing.rules.select_active_rules(rules: list[AuthoringRule], step_type: StepType) -> list[AuthoringRule]`
- 產出：`training_kb.writing.rules.applies_to(rule: AuthoringRule, step_type: StepType) -> bool`
- 產出：`training_kb.writing.rules.APPLIES_WHEN_FIELD: str`、`training_kb.writing.rules.LEGAL_STEP_TYPES: frozenset[str]`

- [ ] **步驟 1：寫測試**

建立 `tests/unit/test_writing_rules.py`：

```python
"""Phase 06：規則選取與注入的純邏輯測試。"""

from training_kb.models import AuthoringRule, RuleStatus, StepType
from training_kb.writing.rules import select_active_rules


def make_rule(
    rule_id: str,
    status: RuleStatus,
    *,
    step_type: str = "click_ui",
    validated_at: str | None = None,
    text: str = "點 UI 的步驟要寫出頁面、按鈕位置與點擊結果",
    applies_when: dict | None = None,
) -> AuthoringRule:
    """組一條規則。測試只關心 status、applies_when 與 validated_at，其餘給固定值。"""
    return AuthoringRule(
        rule_id=rule_id,
        rule=text,
        applies_when={"step.type": step_type} if applies_when is None else applies_when,
        evidence=["f_12", "f_15", "f_19", "f_23", "f_27"],
        status=status,
        applied_to=[],
        derived_from="prepare-meeting@v1",
        validated_at=validated_at,
    )


def test_candidate_規則不會被選中():
    rules = [make_rule("R-007", RuleStatus.candidate)]

    assert select_active_rules(rules, StepType.click_ui) == []


def test_retired_規則不會被選中():
    rules = [make_rule("R-012", RuleStatus.retired)]

    assert select_active_rules(rules, StepType.click_ui) == []


def test_只回傳_active_規則():
    rules = [
        make_rule("R-001", RuleStatus.candidate),
        make_rule("R-007", RuleStatus.active, validated_at="2026-08-25T00:00:00Z"),
        make_rule("R-012", RuleStatus.retired),
    ]

    selected = select_active_rules(rules, StepType.click_ui)

    assert [rule.rule_id for rule in selected] == ["R-007"]


def test_步驟型態不符的規則被排除():
    rules = [make_rule("R-020", RuleStatus.active, step_type="input")]

    assert select_active_rules(rules, StepType.click_ui) == []
    assert [r.rule_id for r in select_active_rules(rules, StepType.input)] == ["R-020"]


def test_applies_when_值不是合法步驟型態時視為不命中():
    rules = [make_rule("R-030", RuleStatus.active, step_type="hover")]

    assert select_active_rules(rules, StepType.click_ui) == []
    assert select_active_rules(rules, StepType.input) == []
    assert select_active_rules(rules, StepType.read) == []


def test_applies_when_有兩個條件時視為不命中():
    rules = [
        make_rule(
            "R-031",
            RuleStatus.active,
            applies_when={"step.type": "click_ui", "slug": "share-summary"},
        )
    ]

    assert select_active_rules(rules, StepType.click_ui) == []


def test_applies_when_是空字典或欄位不對時視為不命中():
    rules = [
        make_rule("R-032", RuleStatus.active, applies_when={}),
        make_rule("R-033", RuleStatus.active, applies_when={"text": "contains(按鈕)"}),
    ]

    assert select_active_rules(rules, StepType.click_ui) == []


def test_空規則庫回傳空清單():
    assert select_active_rules([], StepType.read) == []
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：

```bash
uv run pytest tests/unit/test_writing_rules.py -v
```

預期：FAIL。錯誤訊息是 `ModuleNotFoundError: No module named 'training_kb.writing.rules'`，因為 `rules.py` 還不存在。

- [ ] **步驟 3：寫最少的程式讓測試通過**

建立 `src/training_kb/writing/rules.py`：

```python
"""Authoring Rule 的選取與注入（Phase 06）。

一般寫作路徑只使用 status 為 active 的規則；candidate 永遠不會進 prompt
（設計文件 §12.2、F27）。applies_when 只支援單一等值條件
{"step.type": "click_ui" | "input" | "read"}（D16）。
"""

from __future__ import annotations

from training_kb.models import AuthoringRule, RuleStatus, StepType

# D16：applies_when 唯一合法的欄位名稱。
APPLIES_WHEN_FIELD = "step.type"

# D16：applies_when 唯一合法的三個值。
LEGAL_STEP_TYPES = frozenset(str(step_type) for step_type in StepType)


def applies_to(rule: AuthoringRule, step_type: StepType) -> bool:
    """這條規則的適用範圍是否命中這種步驟型態。

    不合法的 applies_when 一律回傳 False（當成不命中），不拋例外：
    設計文件 §7.6 要求規則問題不可以讓寫作停止。
    """
    condition = rule.applies_when
    if not isinstance(condition, dict) or len(condition) != 1:
        return False
    value = condition.get(APPLIES_WHEN_FIELD)
    if not isinstance(value, str) or value not in LEGAL_STEP_TYPES:
        return False
    return value == str(step_type)


def select_active_rules(
    rules: list[AuthoringRule], step_type: StepType
) -> list[AuthoringRule]:
    """挑出這次寫作要注入的規則。

    只放行 status 為 active、且 applies_when 命中 step_type 的規則。
    """
    return [
        rule
        for rule in rules
        if rule.status == RuleStatus.active and applies_to(rule, step_type)
    ]
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：

```bash
uv run pytest tests/unit/test_writing_rules.py -v
```

預期：PASS，看到 8 個 `PASSED`。

- [ ] **步驟 5：commit**

```bash
git add src/training_kb/writing/rules.py tests/unit/test_writing_rules.py
git commit -m "feat(rules): 依 status 與 applies_when 篩選教學規則"
```

---

### Task 2：同一適用範圍衝突時只取最近驗證通過的規則

**目的**：落實 F28。同一個 `step.type` 底下有多條 active 規則時，只保留 `validated_at` 最新的那一條。

**檔案**：
- 修改：`src/training_kb/writing/rules.py`
- 測試：`tests/unit/test_writing_rules.py`

**介面**：
- 消費：`training_kb.clock.parse_iso(s: str) -> datetime`（Phase 01）
- 產出：`training_kb.writing.rules.select_active_rules(rules, step_type) -> list[AuthoringRule]`（行為擴充，簽名不變）

- [ ] **步驟 1：寫測試**

在 `tests/unit/test_writing_rules.py` 最後面加上：

```python
def test_同範圍多條_active_只取_validated_at_最新者():
    rules = [
        make_rule("R-007", RuleStatus.active, validated_at="2026-08-25T00:00:00Z"),
        make_rule("R-050", RuleStatus.active, validated_at="2026-09-01T00:00:00Z"),
        make_rule("R-003", RuleStatus.active, validated_at="2026-07-10T00:00:00Z"),
    ]

    selected = select_active_rules(rules, StepType.click_ui)

    assert [rule.rule_id for rule in selected] == ["R-050"]


def test_不同適用範圍的_active_規則互不影響():
    rules = [
        make_rule("R-007", RuleStatus.active, validated_at="2026-08-25T00:00:00Z"),
        make_rule("R-020", RuleStatus.active, step_type="input",
                  validated_at="2026-09-01T00:00:00Z"),
    ]

    assert [r.rule_id for r in select_active_rules(rules, StepType.click_ui)] == ["R-007"]
    assert [r.rule_id for r in select_active_rules(rules, StepType.input)] == ["R-020"]


def test_沒有_validated_at_的規則視為最舊():
    rules = [
        make_rule("R-007", RuleStatus.active, validated_at=None),
        make_rule("R-050", RuleStatus.active, validated_at="2026-01-01T00:00:00Z"),
    ]

    selected = select_active_rules(rules, StepType.click_ui)

    assert [rule.rule_id for rule in selected] == ["R-050"]


def test_validated_at_相同時取_rule_id_較小者():
    rules = [
        make_rule("R-050", RuleStatus.active, validated_at="2026-09-01T00:00:00Z"),
        make_rule("R-007", RuleStatus.active, validated_at="2026-09-01T00:00:00Z"),
    ]

    selected = select_active_rules(rules, StepType.click_ui)

    assert [rule.rule_id for rule in selected] == ["R-007"]


def test_只有一條_active_時原樣回傳():
    rules = [make_rule("R-007", RuleStatus.active, validated_at=None)]

    selected = select_active_rules(rules, StepType.click_ui)

    assert [rule.rule_id for rule in selected] == ["R-007"]
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：

```bash
uv run pytest tests/unit/test_writing_rules.py -v
```

預期：FAIL。`test_同範圍多條_active_只取_validated_at_最新者` 會失敗，訊息類似
`AssertionError: assert ['R-007', 'R-050', 'R-003'] == ['R-050']`，因為現在的程式把三條都回傳了。

- [ ] **步驟 3：寫最少的程式讓測試通過**

這一步要改三個地方，其他內容維持 Task 1 寫好的樣子。

第一，把 `src/training_kb/writing/rules.py` 開頭的 docstring 與 import 區塊改成：

```python
"""Authoring Rule 的選取與注入（Phase 06）。

一般寫作路徑只使用 status 為 active 的規則；candidate 永遠不會進 prompt
（設計文件 §12.2、F27）。applies_when 只支援單一等值條件
{"step.type": "click_ui" | "input" | "read"}（D16）。
同一適用範圍有多條 active 規則時，只注入最近驗證通過的那一條（F28）。
"""

from __future__ import annotations

from datetime import datetime, timezone

from training_kb.clock import parse_iso
from training_kb.models import AuthoringRule, RuleStatus, StepType
```

第二，在 `LEGAL_STEP_TYPES` 那一行後面加上一個常數：

```python
# 沒有 validated_at 的規則一律當成「最舊」，排在有時間的規則後面。
_NEVER_VALIDATED = datetime(1970, 1, 1, tzinfo=timezone.utc)
```

第三，在 `applies_to` 後面加上 `_validated_at`，並把整個 `select_active_rules`
換成下面這一段（`applies_to` 本身不用動）：

```python
def _validated_at(rule: AuthoringRule) -> datetime:
    """把 validated_at 轉成可比較的時間；沒有值就回傳固定的最舊時間。"""
    if not rule.validated_at:
        return _NEVER_VALIDATED
    return parse_iso(rule.validated_at)


def select_active_rules(
    rules: list[AuthoringRule], step_type: StepType
) -> list[AuthoringRule]:
    """挑出這次寫作要注入的規則。

    1. 只放行 status 為 active 的規則（candidate 與 retired 一律排除）。
    2. 只放行 applies_when 命中 step_type 的規則。
    3. D16 讓 applies_when 只能是單一 step.type 條件，所以剩下的規則都屬於
       同一個適用範圍；依 F28 只保留 validated_at 最新的一條。
       平手時取 rule_id 字串較小者（本計劃選擇，只為了結果可預測）。
    """
    matched = [
        rule
        for rule in rules
        if rule.status == RuleStatus.active and applies_to(rule, step_type)
    ]
    if len(matched) <= 1:
        return list(matched)

    # Python 的 sorted 是穩定排序：先依 rule_id 升序排一次，再依驗證時間降序排一次，
    # 驗證時間相同的規則就會保持 rule_id 升序，第一個永遠是 rule_id 最小的那條。
    by_rule_id = sorted(matched, key=lambda rule: rule.rule_id)
    newest_first = sorted(by_rule_id, key=_validated_at, reverse=True)
    return [newest_first[0]]
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：

```bash
uv run pytest tests/unit/test_writing_rules.py -v
```

預期：PASS，13 個 `PASSED`。

- [ ] **步驟 5：commit**

```bash
git add src/training_kb/writing/rules.py tests/unit/test_writing_rules.py
git commit -m "feat(rules): 同範圍衝突取最近驗證通過的規則"
```

---

### Task 3：把規則變成可以貼進 prompt 的文字

**目的**：寫出 `render_rules_block`。空清單必須回傳空字串 `""`，這樣呼叫端就能用「文字是不是空的」判斷這次到底有沒有注入規則。

**檔案**：
- 修改：`src/training_kb/writing/rules.py`
- 測試：`tests/unit/test_writing_rules.py`

**介面**：
- 產出：`training_kb.writing.rules.render_rules_block(rules: list[AuthoringRule]) -> str`

- [ ] **步驟 1：寫測試**

在 `tests/unit/test_writing_rules.py` 的 import 區塊改成：

```python
from training_kb.models import AuthoringRule, RuleStatus, StepType
from training_kb.writing.rules import render_rules_block, select_active_rules
```

在檔案最後面加上：

```python
def test_空清單的規則文字是空字串():
    assert render_rules_block([]) == ""


def test_規則文字包含編號_適用範圍與內容():
    rules = [make_rule("R-007", RuleStatus.active, validated_at="2026-08-25T00:00:00Z")]

    block = render_rules_block(rules)

    assert block == (
        "寫作規則（必須全部遵守）：\n"
        "- [R-007] 適用於 step.type = click_ui："
        "點 UI 的步驟要寫出頁面、按鈕位置與點擊結果"
    )


def test_多條規則各佔一行且順序不變():
    rules = [
        make_rule("R-007", RuleStatus.active, text="規則一"),
        make_rule("R-020", RuleStatus.active, step_type="input", text="規則二"),
    ]

    block = render_rules_block(rules)

    assert block.splitlines() == [
        "寫作規則（必須全部遵守）：",
        "- [R-007] 適用於 step.type = click_ui：規則一",
        "- [R-020] 適用於 step.type = input：規則二",
    ]
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：

```bash
uv run pytest tests/unit/test_writing_rules.py -v
```

預期：FAIL，訊息是 `ImportError: cannot import name 'render_rules_block' from 'training_kb.writing.rules'`。

- [ ] **步驟 3：寫最少的程式讓測試通過**

在 `src/training_kb/writing/rules.py` 的 `select_active_rules` 後面加上：

```python
def render_rules_block(rules: list[AuthoringRule]) -> str:
    """把規則清單變成要貼進寫作 prompt 的一段文字。

    空清單回傳空字串。呼叫端用「這段文字是不是空的」判斷這次有沒有注入規則，
    所以這裡不可以在沒有規則時回傳「（無）」之類的佔位文字。
    """
    if not rules:
        return ""
    lines = ["寫作規則（必須全部遵守）："]
    for rule in rules:
        scope = rule.applies_when.get(APPLIES_WHEN_FIELD, "")
        lines.append(f"- [{rule.rule_id}] 適用於 step.type = {scope}：{rule.rule}")
    return "\n".join(lines)
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：

```bash
uv run pytest tests/unit/test_writing_rules.py -v
```

預期：PASS，16 個 `PASSED`。

- [ ] **步驟 5：commit**

```bash
git add src/training_kb/writing/rules.py tests/unit/test_writing_rules.py
git commit -m "feat(rules): 產生寫作 prompt 用的規則文字區塊"
```

---

### Task 4：回報實際注入的規則 ID

**目的**：寫出 `applied_rule_ids`。它的回傳值就是 Phase 07 要寫進版本 `rules_applied` 的內容，也是 D17 認定的套用關係權威來源。

**檔案**：
- 修改：`src/training_kb/writing/rules.py`
- 測試：`tests/unit/test_writing_rules.py`

**介面**：
- 產出：`training_kb.writing.rules.applied_rule_ids(rules: list[AuthoringRule]) -> list[str]`

- [ ] **步驟 1：寫測試**

把 `tests/unit/test_writing_rules.py` 的 import 區塊改成：

```python
from training_kb.models import AuthoringRule, RuleStatus, StepType
from training_kb.writing.rules import (
    applied_rule_ids,
    render_rules_block,
    select_active_rules,
)
```

在檔案最後面加上：

```python
def test_空清單回傳空的_id_清單():
    assert applied_rule_ids([]) == []


def test_id_清單保持傳入順序():
    rules = [
        make_rule("R-020", RuleStatus.active, step_type="input"),
        make_rule("R-007", RuleStatus.active),
    ]

    assert applied_rule_ids(rules) == ["R-020", "R-007"]


def test_重複的規則只算一次():
    rule = make_rule("R-007", RuleStatus.active)
    rules = [rule, rule, make_rule("R-020", RuleStatus.active, step_type="input"), rule]

    assert applied_rule_ids(rules) == ["R-007", "R-020"]
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：

```bash
uv run pytest tests/unit/test_writing_rules.py -v
```

預期：FAIL，訊息是 `ImportError: cannot import name 'applied_rule_ids' from 'training_kb.writing.rules'`。

- [ ] **步驟 3：寫最少的程式讓測試通過**

在 `src/training_kb/writing/rules.py` 的 `render_rules_block` 後面加上：

```python
def applied_rule_ids(rules: list[AuthoringRule]) -> list[str]:
    """回傳這些規則的 ID，去重並保持原順序。

    這份清單會被寫進 TutorialVersion.rules_applied。D17 規定 rules_applied 是
    規則與版本套用關係的唯一權威；RULE.applied_to 與 APPLIED_TO 邊都由它重建。
    """
    seen: set[str] = set()
    ids: list[str] = []
    for rule in rules:
        if rule.rule_id in seen:
            continue
        seen.add(rule.rule_id)
        ids.append(rule.rule_id)
    return ids
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：

```bash
uv run pytest tests/unit/test_writing_rules.py -v
```

預期：PASS，19 個 `PASSED`。

- [ ] **步驟 5：commit**

```bash
git add src/training_kb/writing/rules.py tests/unit/test_writing_rules.py
git commit -m "feat(rules): 回報實際注入的規則識別碼"
```

---

### Task 5：CREATE／UPDATE／REFINE 共用的組合包

**目的**：寫出 `rules_for_content`。一次傳入這次要寫作的所有步驟型態，一次拿到「prompt 文字」與「要寫進 `rules_applied` 的 ID」，確保兩者永遠對得上。

**檔案**：
- 修改：`src/training_kb/writing/rules.py`
- 測試：`tests/unit/test_writing_rules.py`

**介面**：
- 產出：`training_kb.writing.rules.rules_for_content(rules: list[AuthoringRule], step_types: list[StepType]) -> tuple[str, list[str]]`

- [ ] **步驟 1：寫測試**

把 `tests/unit/test_writing_rules.py` 的 import 區塊改成：

```python
from training_kb.models import AuthoringRule, RuleStatus, StepType
from training_kb.writing.rules import (
    applied_rule_ids,
    render_rules_block,
    rules_for_content,
    select_active_rules,
)
```

在檔案最後面加上：

```python
def test_沒有適用規則時回傳空字串與空清單():
    rules = [
        make_rule("R-007", RuleStatus.candidate),
        make_rule("R-012", RuleStatus.retired),
    ]

    block, ids = rules_for_content(rules, [StepType.click_ui, StepType.read])

    assert block == ""
    assert ids == []


def test_沒有步驟型態時回傳空字串與空清單():
    rules = [make_rule("R-007", RuleStatus.active)]

    block, ids = rules_for_content(rules, [])

    assert block == ""
    assert ids == []


def test_合併多種步驟型態的規則且去重():
    rules = [
        make_rule("R-007", RuleStatus.active, text="規則一"),
        make_rule("R-020", RuleStatus.active, step_type="input", text="規則二"),
        make_rule("R-030", RuleStatus.candidate, step_type="read", text="規則三"),
    ]

    block, ids = rules_for_content(
        rules,
        [StepType.click_ui, StepType.input, StepType.read, StepType.click_ui],
    )

    assert ids == ["R-007", "R-020"]
    assert block.splitlines() == [
        "寫作規則（必須全部遵守）：",
        "- [R-007] 適用於 step.type = click_ui：規則一",
        "- [R-020] 適用於 step.type = input：規則二",
    ]


def test_文字與_id_永遠對得上():
    rules = [make_rule("R-007", RuleStatus.active, text="規則一")]

    block, ids = rules_for_content(rules, [StepType.click_ui])

    # 只要有 ID，文字就一定非空；只要文字是空的，ID 就一定是空清單（F29）。
    assert (block == "") == (ids == [])
    for rule_id in ids:
        assert rule_id in block
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：

```bash
uv run pytest tests/unit/test_writing_rules.py -v
```

預期：FAIL，訊息是 `ImportError: cannot import name 'rules_for_content' from 'training_kb.writing.rules'`。

- [ ] **步驟 3：寫最少的程式讓測試通過**

在 `src/training_kb/writing/rules.py` 最後面加上：

```python
def rules_for_content(
    rules: list[AuthoringRule], step_types: list[StepType]
) -> tuple[str, list[str]]:
    """CREATE／UPDATE／REFINE 共用的入口。

    傳入「這次真的要寫作的步驟型態」，回傳 (要貼進 prompt 的文字, 要記進
    rules_applied 的 ID 清單)。

    重要：step_types 只能放這次真的會重寫的步驟型態。UPDATE 與 REFINE 只重寫
    命中的步驟，沒有重寫的步驟是原文複製，依 F29 不算本次套用，所以它們的型態
    不可以放進來。

    兩個回傳值一定成對：文字為空字串時 ID 必為空清單，反之亦然。呼叫端只有在
    真的把文字送進模型時，才可以把 ID 寫進版本的 rules_applied。
    """
    selected: list[AuthoringRule] = []
    seen: set[str] = set()
    for step_type in step_types:
        for rule in select_active_rules(rules, step_type):
            if rule.rule_id in seen:
                continue
            seen.add(rule.rule_id)
            selected.append(rule)
    return render_rules_block(selected), applied_rule_ids(selected)
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：

```bash
uv run pytest tests/unit/test_writing_rules.py -v
```

預期：PASS，23 個 `PASSED`。接著跑整包測試與格式檢查：

```bash
uv run pytest -q
uv run ruff check .
uv run ruff format .
```

預期：`pytest` 全數通過；`ruff check` 顯示 `All checks passed!`。

- [ ] **步驟 5：commit**

```bash
git add src/training_kb/writing/rules.py tests/unit/test_writing_rules.py
git commit -m "feat(rules): 提供 CREATE/UPDATE/REFINE 共用的規則注入入口"
```

---

## 7. 完成檢查清單

全部打勾才算做完這一階段。

- [ ] `src/training_kb/writing/rules.py` 存在，並提供 `APPLIES_WHEN_FIELD`、`LEGAL_STEP_TYPES`、`applies_to`、`select_active_rules`、`render_rules_block`、`applied_rule_ids`、`rules_for_content` 七個名稱。
- [ ] `uv run pytest tests/unit/test_writing_rules.py -v` 全部通過，共 23 個測試。
- [ ] `uv run pytest -q` 整包通過。
- [ ] `uv run ruff check .` 顯示 `All checks passed!`。
- [ ] 手動驗證「candidate 不會進 prompt」：

```bash
uv run python -c "
from training_kb.models import AuthoringRule, RuleStatus, StepType
from training_kb.writing.rules import rules_for_content
r = AuthoringRule(rule_id='R-007', rule='要寫出按鈕位置',
                  applies_when={'step.type': 'click_ui'}, evidence=['f_12'],
                  status=RuleStatus.candidate, applied_to=[],
                  derived_from='prepare-meeting@v1', validated_at=None)
print(rules_for_content([r], [StepType.click_ui]))
"
```

預期輸出：

```text
('', [])
```

- [ ] 手動驗證「同範圍衝突取最新」：

```bash
uv run python -c "
from training_kb.models import AuthoringRule, RuleStatus, StepType
from training_kb.writing.rules import rules_for_content
def rule(rid, at):
    return AuthoringRule(rule_id=rid, rule='規則 '+rid,
                         applies_when={'step.type': 'click_ui'}, evidence=['f_12'],
                         status=RuleStatus.active, applied_to=[],
                         derived_from='prepare-meeting@v1', validated_at=at)
print(rules_for_content([rule('R-007','2026-08-25T00:00:00Z'),
                         rule('R-050','2026-09-01T00:00:00Z')], [StepType.click_ui])[1])
"
```

預期輸出：

```text
['R-050']
```

- [ ] 對應設計文件第 16 節切片 S7 的前置條件：規則選取的行為已可用純邏輯測試重現（「candidate 不進一般 prompt；實際注入才計套用；同範圍衝突採最近驗證者」，設計文件第 15 節「規則」列）。

---

## 8. 常見錯誤與排除

**症狀 1：`ModuleNotFoundError: No module named 'training_kb'`**

原因：專案用的是 src layout（程式在 `src/training_kb/`），但套件沒有被安裝到虛擬環境裡。

解法：先確認 `pyproject.toml` 有 Phase 01 設定的 build backend 與 `packages = ["src/training_kb"]` 之類的設定，然後執行 `uv sync`。之後所有指令都要用 `uv run` 開頭，不要直接用 `python`。

---

**症狀 2：`test_同範圍多條_active_只取_validated_at_最新者` 一直失敗，回傳的是 `R-003`**

原因：`sorted(..., reverse=True)` 寫成了 `sorted(...)`，或者把兩次排序的順序寫反了（先依驗證時間、再依 rule_id）。Python 的排序是穩定的，所以「後排的那一次決定主要順序」，`rule_id` 那一次一定要排在前面。

解法：照 Task 2 的程式碼順序寫：先 `by_rule_id = sorted(matched, key=lambda rule: rule.rule_id)`，再 `newest_first = sorted(by_rule_id, key=_validated_at, reverse=True)`。

---

**症狀 3：`TypeError: '<' not supported between instances of 'NoneType' and 'datetime.datetime'`**

原因：`_validated_at` 在 `validated_at` 是 `None` 時回傳了 `None`，排序時就無法比較。

解法：`_validated_at` 一定要回傳 `datetime`，沒有值時回傳固定的 `_NEVER_VALIDATED`。不要用 `None` 當排序鍵。

---

**症狀 4：規則有 `status="active"`，但 `select_active_rules` 回傳空清單**

原因有三種，依序檢查：

1. `applies_when` 的鍵打錯了。必須正好是 `"step.type"`（中間是半形句點，不是底線，也不是 `step_type`）。
2. `applies_when` 的值不是 `click_ui`／`input`／`read` 三者之一。D16 規定 MVP 只支援這三個值，其他值一律當成不命中。
3. `applies_when` 放了兩個以上的鍵。D16 不支援 AND／OR 組合。

解法：用下面這行檢查那條規則到底命不命中：

```bash
uv run python -c "
from training_kb.models import StepType
from training_kb.writing.rules import LEGAL_STEP_TYPES, APPLIES_WHEN_FIELD
print(APPLIES_WHEN_FIELD, sorted(LEGAL_STEP_TYPES))
"
```

預期輸出：

```text
step.type ['click_ui', 'input', 'read']
```

---

**症狀 5：`rules_applied` 記了規則 ID，但那一版的教學文字裡看不出規則有生效**

原因：呼叫端把 `rules_for_content` 的 ID 寫進去了，卻沒有把回傳的文字放進 prompt；或者這次是 UPDATE／REFINE，被記錄的步驟其實是原文複製過來的。

解法：F29 規定只有「本次寫作 prompt 實際注入的規則」才算套用。呼叫端要遵守兩件事：

1. `block` 與 `ids` 一定一起用，不可以只用其中一個。
2. UPDATE／REFINE 傳給 `rules_for_content` 的 `step_types`，只能包含**這次真的要重寫的那幾步**的型態。

---

**症狀 6：`ValueError: Invalid isoformat string` 或 `PermanentError`**

原因：`validated_at` 的字串格式不對，例如寫成 `2026/08/25` 或 `2026-08-25`（少了時間與時區）。

解法：`validated_at` 一律用 `clock.to_iso()` 產生，格式是 `2026-08-25T00:00:00Z`。這個欄位只能由 Phase 20 的 `analytics.apply_rule_status` 寫入，不要手動塞值進資料庫。

---

## 9. 這階段不做的事

| 不做的事 | 留給哪一階段 |
|---|---|
| 從 DynamoDB 讀規則（`repo.list_rules(status=...)`） | Phase 03 建立基礎讀寫、Phase 09 補齊固定讀取 |
| 把 `rules_applied` 寫進版本、建立 `APPLIED_TO` 邊 | Phase 07（`07-Phase07-Content-建立教學版本.md`） |
| 真的把規則文字送進 Bedrock、組裝完整 prompt | Phase 13（CREATE）、Phase 16（UPDATE）、Phase 17（REFINE） |
| 提出新的 candidate 規則（同版同類 ≥5 筆） | Phase 18（`18-Phase18-Feedback-Review-候選規則與每日排程.md`） |
| 判斷兩條規則是否真的衝突、把規則改成 active 或 retired、寫 `validated_at` | Phase 20（`20-Phase20-規則驗證與狀態轉換.md`） |
| 計算「規則套用次數」等指標 | Phase 19（`19-Phase19-Analytics-學習指標.md`） |
| 規則開／關的並排對照展示 | Phase 23（`23-Phase23-Demo控制台與Dashboard.md`） |

另外，本階段**不**拒絕格式不合法的規則，只是略過它。把不合法的 `applies_when` 擋在資料庫外面是 Phase 18 提出 candidate 時的責任。

---

## 10. 對照：設計章節與 Rule 編號

Rule 原文抄自 `docs/spec/features/套用教學規則.feature`；設計文件第 20.4 節有同一份對照表。

| Rule 來源檔 | Rule 編號與原文 | 本階段哪個 Task 落實 |
|---|---|---|
| `套用教學規則.feature` | Rule 1「CREATE、UPDATE 與 REFINE 在寫作前讀取教學規則」 | Task 5 提供三者共用的 `rules_for_content`；真正呼叫在 Phase 13／16／17。 |
| `套用教學規則.feature` | Rule 2「一般寫作路徑只取得 status 為 active 的規則」 | Task 1（`select_active_rules` 只放行 active） |
| `套用教學規則.feature` | Rule 3「依 step 型態與 applies_when 篩選規則」 | Task 1（`applies_to`，D16 單一條件）、Task 2（F28 同範圍取最新） |
| `套用教學規則.feature` | Rule 4「適用規則的內容注入教學寫作 prompt」 | Task 3（`render_rules_block`）、Task 5 |
| `套用教學規則.feature` | Rule 5「既有教學衍生的適用規則可用於不同主題新教學的第一版」 | Task 5 的函式不看教學 slug，所以 A 的規則可以用在 B v1；Demo 資料在 Phase 21。 |
| `套用教學規則.feature` | Rule 6「套用規則的版本記錄於規則的 applied_to」 | Task 4 產生 ID 清單；`APPLIED_TO` 邊由 Phase 07 依 `rules_applied` 寫入（D17）。 |
| `套用教學規則.feature` | Rule 7「版本的 rules_applied 記錄本次套用的規則」 | Task 4、Task 5（F29：只記實際注入的） |
| `套用教學規則.feature` | Rule 8「後續 Release 重寫仍注入適用的教學規則」 | Task 5 的 `step_types` 參數讓 Phase 16 只帶入被重寫步驟的型態。 |

`套用教學規則.feature` 的 Rule 3 帶有唯一一個可執行 Example：

```gherkin
Example: click_ui 步驟取得 R-007
  Given 教學規則庫具有下列規則
    | rule_id | status | applies_when          |
    | R-007   | active | step.type == click_ui |
  When 系統取得 "click_ui" 步驟的教學規則
  Then 取得的規則集合為
    | rule_id |
    | R-007   |
```

Task 1 的 `test_只回傳_active_規則` 與 Task 2 的 `test_只有一條_active_時原樣回傳` 合起來就是這個 Example 的自動化版本。

---

## 11. 參考來源

設計文件（`docs/design/training-kb.md`）：

- §7.6 共用寫作與 Analytics 的內部介面（規則注入、applies_when 範圍、rules_applied）
- §8.2 create_version 的完成條件（套用關係以 `rules_applied` 為準）
- §9.1 十個邏輯實體的欄位（AUTHORING_RULE）
- §9.2 關係邊（`RULE#R-007` → `APPLIED_TO#VERSION#...`）
- §12.2 規則驗證（一般寫作只讀 active；只有 Analytics 能寫狀態）
- §15 測試與驗收設計，「規則」列
- §19.1 資料決策 D16、D17
- §19.2 功能決策 F27、F28、F29
- §20.4 逐條 Rule 與負責模組（套用教學規則）

規格檔：

- `docs/spec/features/套用教學規則.feature`
- `docs/spec/erm.dbml`（AUTHORING_RULE、TUTORIAL_VERSION.rules_applied、TUTORIAL_STEP.type）
- `docs/spec/.clarify/resolved/data/AUTHORING_RULE_applies_when_的可表達條件範圍為何.md`（D16）
- `docs/spec/.clarify/resolved/data/AUTHORING_RULE_規則與版本的套用關係以哪份資料為權威.md`（D17）
- `docs/spec/.clarify/resolved/features/套用教學規則_多條相互衝突的_active_規則同時適用時如何選擇.md`（F28）
- `docs/spec/.clarify/resolved/features/套用教學規則_未改寫步驟沿用的規則是否算新版的套用紀錄.md`（F29）

官方文件：

- Python `enum.StrEnum`：<https://docs.python.org/3/library/enum.html#enum.StrEnum>
- Python `sorted` 的穩定排序保證：<https://docs.python.org/3/library/functions.html#sorted>
- Python `sorted` 排序技巧（多重排序鍵）：<https://docs.python.org/3/howto/sorting.html#sort-stability-and-complex-sorts>
- pydantic v2 Models（`model_fields`、欄位預設值）：<https://docs.pydantic.dev/latest/concepts/models/>
