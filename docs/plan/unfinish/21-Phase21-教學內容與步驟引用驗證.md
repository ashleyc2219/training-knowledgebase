# Phase 21：教學內容與步驟引用驗證實作計畫

> **給實作者：** 依 checkbox 逐步執行；每個 Task 先建立失敗測試，再寫最小實作。執行時使用 `superpowers:executing-plans` 或同等逐項流程。

**目標：** 在任何內容被寫進 S3 或 DynamoDB 之前，確認五段齊全、步驟編號連續、型態合法，而且每一步恰好引用一個既有 Feature。

**架構：** `validate_content` 是不碰 AWS 也不呼叫模型的純函式。模型只負責產出 `TutorialContent`；能不能保存由這個函式決定。它一次列出所有問題，讓 Phase 18 的「最多修正一次」能把完整訊息交給模型。

**技術：** Python 3.12、Pydantic v2 的 `TutorialContent`／`StepDraft`／`StepType`、pytest、Phase 02 `ContentError`。

## 全域限制

- 唯一主來源是 [Training KB 設計 §7.3、§7.6、§8.2、§14.1](../../design/training-kb.md)。
- 前置為 [Phase 20：版本分配與重試重用](./20-Phase20-版本分配與重試重用.md)。前置未通過時停止。
- 下一階段是 [Phase 22：Markdown 與 Diff 私有產物](./22-Phase22-Markdown與Diff私有產物.md)。
- 本階段不讀 DynamoDB、不寫任何檔案、不呼叫 Bedrock、不建立 Feature、不拆步驟；`known_feature_ids` 由呼叫端事先查好傳進來。
- 本階段不判斷文字好不好，只判斷結構是否可保存；零個或多個 Feature 的步驟一律拒絕，不可「自動挑第一個」或「留空待補」（D05）。
- 與本 Phase 有關的 gate：本階段全是純函式，不涉及 O1–O7；綠燈只代表結構驗證正確，不代表教學已建立或已發布。以下程式檔均是實作時預計建立或修改。

---

## 1. 你在整體流程的位置

```text
Phase 17 JSON schema 通過（欄位形狀正確）
                 v
Phase 18 業務驗證框架（最多修正一次）
                 v
     [你在這裡：validate_content]
       |                       |
     合格                    不合格
       v                       v
  Phase 22 產出 Markdown   ContentError -> 交回 Phase 18 修正一次
       v                       v
  Phase 23 寫未發布版本    仍不合格 -> 操作失敗，不發布
```

`ContentError` 是 `PermanentError` 的子類別：這是資料不合法，不是服務暫時故障，不進 Task Retry。

## 2. 完成後看得到什麼

已知 Feature 是 `frozenset({"Prepare", "Share Summary", "Notification Settings"})`，模型交出 `prepare-meeting` 的四步草稿：

```text
合格：title/problem/prerequisites/steps/expected_outcome 皆非空
      steps 編號 1,2,3,4；type 分別是 read/click_ui/click_ui/read
      每步 feature_id 都是單一且存在，例如 "Prepare"
   -> validate_content(...) 回傳 None，不丟例外

不合格：第 2 步 feature_id = ""  -> 「第 2 步沒有引用 Feature」
        第 3 步 = "Prepare, Share Summary" -> 「第 3 步引用了多個 Feature」
        第 4 步 = "Calendar"       -> 「第 4 步引用的 Feature 不存在」
   -> 一次丟出的 ContentError 同時含這三句話
```

## 3. 名詞小抄

| 名詞 | 白話意思 |
|---|---|
| 五段 | Title、Problem、Prerequisites、Steps、Expected Outcome；少一段就不能保存。 |
| `StepType` | 步驟型態，只有 `click_ui`、`input`、`read` 三種。 |
| 恰好一個 Feature | 一個步驟的 `feature_id` 必須是單一既有 Feature 的裸 ID，不能是空的，也不能塞兩個。 |
| 裸 ID | 不帶 `FEATURE#` 前綴的識別碼，例如 `Prepare`；前綴只在 DynamoDB 的鍵上出現（D03）。 |
| 業務驗證 | schema 說「形狀對」之後，程式再檢查「內容是否可保存」（F48）。 |
| D05／F48 這類編號 | 設計文件第 19 節已解決決策的編號：`D` 是資料決策，`F` 是功能決策，查[設計 §19](../../design/training-kb.md) 就能看到原文。 |

## 4. 預計檔案

| 動作 | 路徑 | 責任 |
|---|---|---|
| 修改 | `src/training_kb/content.py` | `LEGAL_STEP_TYPES`、`validate_content` 與私有的 Feature 檢查。 |
| 測試 | `tests/unit/test_validate_content.py` | 五段、編號、型態、零／多／不存在 Feature 與多重問題彙總；同檔另含 `four_step_content(...)` 與 `known_feature_ids` fixture。 |

## 5. 固定介面

### Consumes

```text
TutorialContent(title: str, problem: str, prerequisites: list[str],
                steps: list[StepDraft], expected_outcome: str)   # Phase 03
StepDraft(number: int, type: StepType, text: str, feature_id: str)
StepType（Phase 03 的 StrEnum）：CLICK_UI="click_ui"、INPUT="input"、READ="read"
ContentError(PermanentError)                                     # Phase 02
```

`known_feature_ids` 由呼叫端以 `Repository.scan_entity("FEATURE")` 或既有快取準備；本函式不自己查。裡面一律是裸 ID（`Prepare`），不是 `FEATURE#Prepare`。

### Produces

```python
LEGAL_STEP_TYPES: frozenset[StepType]

def validate_content(
    content: TutorialContent,
    known_feature_ids: frozenset[str],
) -> None: ...
```

回傳 `None` 代表可保存。不合格一律丟 `ContentError`，訊息以「；」串接**所有**問題，不是遇到第一個就中止。

## 6. 設計細節

最終實作的驗證順序固定，而且每一關都只收集問題、不在第一個問題就中止（唯一例外是 `steps` 為空：沒有步驟就沒有步驟可檢查）：

```text
五段是否都有非空內容？ ---- 否 ----> 收集「缺少 Title / Problem / ...」
        v
steps 是否至少一步？ ------ 否 ----> 收集「缺少 Steps」
        v
編號是否為 1..n 連續？ ---- 否 ----> 收集「步驟編號必須是 1 到 n 的連續整數」
        v
每步 text 非空、type 合法？ 否 ----> 收集「第 i 步沒有文字 / type 不合法」
        v
feature_id 去空白後非空？  否 ----> 收集「第 i 步沒有引用 Feature」
        v
feature_id 在 known_feature_ids？ 是 -> 這一步合格
        | 否
        v
含固定分隔符號？ -------- 是 ----> 收集「第 i 步引用了多個 Feature」
        | 否
        v
收集「第 i 步引用的 Feature 不存在」
        v
problems 為空 -> return None；否則一次丟 ContentError
```

1. **一次列完所有問題。** Phase 18 只允許一次修正（設計 §14.3）。如果每次只回報一個錯，那一次機會會被浪費在最前面的小問題上。
2. **編號連續是保存前提。** STEP 的 PK 是 `STEP#<version_id>#<i>`（Phase 05）。編號跳號或重複會讓兩步共用同一個鍵，或讓 [Phase 23](./23-Phase23-未發布版本與關係完整寫入.md) 的核對找不到某一步。Phase 03 的模型已擋掉大部分，這裡仍重驗，因為 `parse_markdown`（Phase 22）與 UPDATE／REFINE 重組的步驟清單也會走進來。
3. **「多個 Feature」要能被看見。** `StepDraft.feature_id` 是單一字串，模型常把兩個功能塞成 `"Prepare, Share Summary"`。本計畫選擇用固定的分隔符號清單辨識這種寫法並拒絕，而不是靜靜取第一個。分隔符號固定為 `,`、`、`、`;`、`/`、`+` 與 ` and `。**先比對 `known_feature_ids`，比不到才看分隔符號**：這個順序讓一個名稱真的含有 `/` 或 `+` 的既有 Feature（例如 `Import/Export`）仍然通過，只有「查無此 Feature 而且長得像兩個」才報「引用了多個」。
4. **分隔符號清單是本計畫選擇，不是規格。** 設計文件沒有規定怎麼辨識「一步塞兩個功能」。若日後出現名稱含分隔符號、又尚未建立成 Feature 的情況，正確做法是先建立／更名該 Feature，或改成明確的清單欄位再改這裡；不得為了讓測試變綠而放行零個或多個引用（D05）。

## 7. TDD Tasks

三個 Task 共用同一支檔案內的兩個小工具（照 Phase 23 的慣例，寫在測試檔裡，不另建 conftest）：

- `known_feature_ids` fixture：回傳 `frozenset({"Prepare", "Share Summary", "Notification Settings"})`。
- `four_step_content(**overrides)`：預設組出合格的四步草稿——`title="準備會議"`，步驟編號 1–4、`type` 依序 `read`／`click_ui`／`click_ui`／`read`、`feature_id` 都是 `Prepare`、第 3 步文字 `開啟摘要。`。

**不合格的變體必須用 `model_construct` 繞過 Phase 03 的模型驗證。** `TutorialContent` 已經擋掉空白段落與不連續編號，`StepDraft` 已經擋掉空白文字、非法 `type` 與非裸 ID 的 `feature_id`。若 helper 用一般建構式組 `problem="  "`、`numbers=[1, 2, 4, 5]`、`step3_feature=""` 或 `step3_type="scroll"`，測試會停在 `ValidationError`，證明不了 `validate_content` 這道防線。所以 helper 在 override 會被模型擋下時，改用 `StepDraft.model_construct(...)` 與 `TutorialContent.model_construct(...)`。這不是繞過檢查，而是讓第二道防線可以被單獨證明（設計 §14.1、F48）。

### Task 1：五段齊全與步驟編號連續

- [ ] **Step 1：建立失敗測試**

```python
def test_valid_content_passes(known_feature_ids):
    validate_content(four_step_content(), known_feature_ids)

def test_missing_section_is_reported(known_feature_ids):
    content = four_step_content(problem="  ")
    with pytest.raises(ContentError, match="缺少 Problem"):
        validate_content(content, known_feature_ids)

def test_non_contiguous_step_numbers_are_rejected(known_feature_ids):
    content = four_step_content(numbers=[1, 2, 4, 5])
    with pytest.raises(ContentError, match="連續整數"):
        validate_content(content, known_feature_ids)
```

- [ ] **Step 2：執行並確認紅燈**

```bash
uv run pytest tests/unit/test_validate_content.py -q
```

預期：FAIL，訊號包含 `cannot import name 'validate_content'`。

- [ ] **Step 3：建立最小實作**

```python
LEGAL_STEP_TYPES = frozenset(StepType)

def _section_problems(content: TutorialContent) -> list[str]:
    problems = [
        f"缺少 {label}"
        for label, value in (("Title", content.title), ("Problem", content.problem),
                             ("Expected Outcome", content.expected_outcome))
        if not value.strip()
    ]
    if not [item for item in content.prerequisites if item.strip()]:
        problems.append("缺少 Prerequisites（沒有前置條件時請寫「無」）")
    if not content.steps:
        problems.append("缺少 Steps")
        return problems
    numbers = [step.number for step in content.steps]
    if numbers != list(range(1, len(numbers) + 1)):
        problems.append(f"步驟編號必須是 1 到 {len(numbers)} 的連續整數，實際是 {numbers}")
    return problems
```

- [ ] **Step 4：補上 `validate_content` 外殼並跑完整檔案**

```python
def validate_content(content: TutorialContent, known_feature_ids: frozenset[str]) -> None:
    problems = _section_problems(content)
    if problems:
        raise ContentError("教學內容驗證失敗：" + "；".join(problems))
```

這一版只看五段與編號，是刻意的最小實作；步驟引用在 Task 2 才接上。執行 `uv run pytest tests/unit/test_validate_content.py -q`，預期三個測試 PASS。

- [ ] **Step 5：提交**

```bash
git add src/training_kb/content.py tests/unit/test_validate_content.py
git commit -m "feat(content): 驗證教學五段與步驟編號"
```

### Task 2：每步恰好一個存在的 Feature

- [ ] **Step 1：建立失敗測試**

```python
@pytest.mark.parametrize(
    ("feature_id", "signal"),
    [("", "沒有引用 Feature"), ("   ", "沒有引用 Feature"),
     ("Prepare, Share Summary", "引用了多個 Feature"),
     ("Prepare、Share Summary", "引用了多個 Feature"),
     ("Calendar", "引用的 Feature 不存在")],
)
def test_step_feature_reference_is_strict(feature_id, signal, known_feature_ids):
    content = four_step_content(step3_feature=feature_id)
    with pytest.raises(ContentError, match=signal):
        validate_content(content, known_feature_ids)

def test_illegal_step_type_is_rejected(known_feature_ids):
    content = four_step_content(step3_type="scroll")
    with pytest.raises(ContentError, match="type 不合法"):
        validate_content(content, known_feature_ids)
```

`""`、`"   "` 與 `"scroll"` 會先被 Phase 03 的 `bare_id` 與 `StepType` 擋下，所以 helper 走本節開頭說的 `model_construct` 路徑，證明 schema 以外仍有第二道防線；`"Prepare, Share Summary"` 與 `"Calendar"` 則是模型放行、只有 `validate_content` 攔得住的值，用一般建構式即可。

- [ ] **Step 2：執行並確認紅燈**

```bash
uv run pytest tests/unit/test_validate_content.py -q
```

預期：FAIL，因為目前只檢查五段，非法引用會被放行。

- [ ] **Step 3：建立最小實作**

```python
_FEATURE_SPLITTERS = (",", "、", ";", "/", "+", " and ")

def _feature_problem(index: int, raw: str, known: frozenset[str]) -> str | None:
    feature_id = raw.strip()
    if not feature_id:
        return f"第 {index} 步沒有引用 Feature"
    if feature_id in known:
        return None
    if any(mark in feature_id for mark in _FEATURE_SPLITTERS):
        return f"第 {index} 步引用了多個 Feature：{feature_id}"
    return f"第 {index} 步引用的 Feature 不存在：{feature_id}"
```

- [ ] **Step 4：把逐步檢查接進 `validate_content` 並跑綠燈**

```python
def _step_problems(content: TutorialContent, known: frozenset[str]) -> list[str]:
    problems: list[str] = []
    for index, step in enumerate(content.steps, start=1):
        if not step.text.strip():
            problems.append(f"第 {index} 步沒有文字")
        if step.type not in LEGAL_STEP_TYPES:
            problems.append(f"第 {index} 步的 type 不合法：{step.type}")
        problem = _feature_problem(index, step.feature_id, known)
        if problem is not None:
            problems.append(problem)
    return problems

def validate_content(content: TutorialContent, known_feature_ids: frozenset[str]) -> None:
    problems = _section_problems(content)
    if problems:
        raise ContentError("教學內容驗證失敗：" + "；".join(problems))
    problems = _step_problems(content, known_feature_ids)
    if problems:
        raise ContentError("教學內容驗證失敗：" + "；".join(problems))
```

這一版仍是「五段不過就先丟出」，Task 3 才把兩組問題合併。執行 `uv run pytest tests/unit/test_validate_content.py -q`，預期零個、多個、不存在與非法型態全部 PASS。

- [ ] **Step 5：提交**

```bash
git add src/training_kb/content.py tests/unit/test_validate_content.py
git commit -m "feat(content): 要求每步恰好引用一個既有 Feature"
```

### Task 3：一次回報所有問題

- [ ] **Step 1：建立失敗測試**

```python
def test_all_problems_are_reported_in_one_error(known_feature_ids):
    content = four_step_content(
        problem="  ", step2_feature="", step3_feature="Prepare, Share Summary",
        step4_feature="Calendar",
    )
    with pytest.raises(ContentError) as caught:
        validate_content(content, known_feature_ids)
    message = str(caught.value)
    for signal in ("缺少 Problem", "第 2 步沒有引用", "第 3 步引用了多個", "第 4 步引用的 Feature 不存在"):
        assert signal in message
```

- [ ] **Step 2：執行並確認紅燈**

```bash
uv run pytest tests/unit/test_validate_content.py::test_all_problems_are_reported_in_one_error -q
```

預期：FAIL，因為 Task 2 的實作在五段有問題時就先丟出例外，訊息只有「缺少 Problem」一句，第 2、3、4 步的引用問題還沒被看到。

- [ ] **Step 3：建立最小實作**

```python
def validate_content(content: TutorialContent, known_feature_ids: frozenset[str]) -> None:
    problems = _section_problems(content)
    problems.extend(_step_problems(content, known_feature_ids))
    if problems:
        raise ContentError("教學內容驗證失敗：" + "；".join(problems))
```

- [ ] **Step 4：驗證錯誤訊息不外洩敏感內容**

斷言訊息只含段落名稱、步驟編號與 `feature_id`，不含 `step.text` 全文、回饋原文或使用者 ID。執行 `uv run pytest tests/unit/test_validate_content.py -q`，預期整個檔案 PASS。

- [ ] **Step 5：提交**

```bash
git add src/training_kb/content.py tests/unit/test_validate_content.py
git commit -m "feat(content): 一次回報全部內容問題"
```

## 8. 驗收矩陣

| 路徑 | 輸入 | 預期資料結果 |
|---|---|---|
| Happy | 五段齊全、四步、每步一個既有 Feature | 回傳 `None`，不丟例外。 |
| Failure | `problem` 為空白字串 | `ContentError` 含「缺少 Problem」。 |
| Failure | 第 3 步 `feature_id="Prepare, Share Summary"` | `ContentError` 含「引用了多個 Feature」。 |
| Failure | 第 4 步 `feature_id="Calendar"`（不在已知清單） | `ContentError` 含「不存在」。 |
| Boundary | 步驟編號 `[1, 2, 4, 5]`／`[1, 1, 2, 3]`，或 `steps` 為空清單 | `ContentError` 含「連續整數」或「缺少 Steps」。 |
| Boundary | `feature_id="Import/Export"`，而且它就在 `known_feature_ids` 裡 | 回傳 `None`；清單命中優先，分隔符號不推翻它。 |
| Boundary | 四個問題同時存在 | 一個 `ContentError`，訊息含全部四句。 |

人工驗收：把一份真的模型輸出貼進測試，列印 `ContentError` 全文，確認新手看得懂哪一步要改；不能只看測試顯示 PASS。

## 9. 常見錯誤與停止條件

| 症狀 | 原因 | 修正／停止 |
|---|---|---|
| 步驟保存後才發現沒有 Feature | 驗證放在寫入之後 | 停止建版，把 `validate_content` 移到寫 S3 之前。 |
| `"Prepare, Share Summary"` 被當成一個 Feature | 只檢查是否在清單中 | 比不到清單時再用分隔符號辨識多引用，兩個條件都要有。 |
| `Import/Export` 這種合法名稱被誤判成多引用 | 先看分隔符號才比清單 | 改成先比 `known_feature_ids`，命中就直接合格。 |
| 五段有問題時就看不到步驟問題 | 中途 `raise` 取代收集 | 改成收集 `problems`，最後一次丟出。 |
| 模型重試兩次以上 | 把 `ContentError` 當暫時故障 | `ContentError` 是 `PermanentError`；重試上限由 Phase 18 管。 |
| 為了通過驗證自動補 Feature | 把驗證器當修正器 | 停止；驗證器不得改寫內容。 |

## 10. 來源與 Rule 對照

以下四條的 primary Phase 都是本 Phase，對照表見 [00B 需求覆蓋對照](./00B-需求覆蓋對照.md)。

- [分析工單.feature](../../spec/features/分析工單.feature)
  - Rule 11：「新教學的完整內容包含 Title、Problem、Prerequisites、Steps 與 Expected Outcome」→ Task 1 的 `test_missing_section_is_reported` 直接斷言。
  - Rule 12：「產生新教學時同時輸出每步提到的 Feature」→ Task 2 的空 `feature_id` 案例直接斷言。
  - Rule 13：「新教學的每個步驟恰好引用一個 Feature」→ Task 2 的零個、多個、不存在三組參數直接斷言。
- [建立教學版本.feature](../../spec/features/建立教學版本.feature)
  - Rule 9：「沒有 Feature 或引用多個 Feature 的步驟不可保存」→ 同 Task 2；Phase 23 另在寫入端再確認一次。
- 設計 §7.6：每步一個 Feature、型態合法、必備區塊齊全；§14.1 與 F48：schema 通過仍須業務驗證，失敗不發布。
- 決策 D05：恰好一個 Feature，零個或多個必須先拆步或驗證失敗；D16：規則的 `applies_when` 只能是 `step.type` 等於 `click_ui`／`input`／`read` 的單一條件，與本 Phase `LEGAL_STEP_TYPES` 是同一組值。

## 11. 完成清單

- [ ] `validate_content` 簽名與回傳型別符合本文件。
- [ ] 五段缺任何一段都有獨立 assertion。
- [ ] 步驟編號跳號、重複與空清單都被拒絕。
- [ ] 零個、多個、不存在的 Feature 各有獨立 assertion，且清單命中優先於分隔符號判定。
- [ ] 非法 `StepType` 在繞過 schema 時仍被拒絕；多個問題一次回報且訊息不含步驟全文或使用者資料。
- [ ] 測試 helper 對「會被 Phase 03 模型擋下的值」使用 `model_construct`，紅燈不是 `ValidationError`。
- [ ] 驗證器沒有修改任何內容，也沒有讀 DynamoDB 或呼叫模型。
- [ ] 單元測試已實際執行並保存輸出。
