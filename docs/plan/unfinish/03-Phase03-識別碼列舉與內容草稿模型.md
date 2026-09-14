# Phase 03 識別碼、列舉與內容草稿模型 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** 在建立十實體前，先鎖定合法列舉、裸識別碼與教學草稿結構，讓錯誤輸入在寫入 AWS 前被拒絕。

**Architecture:** 使用 Pydantic v2 定義共用 value objects。關聯欄位保存裸 ID，DynamoDB 前綴交給 Phase 05；草稿模型只描述內容，不分配版本、不發布。

**Tech Stack:** Python 3.12、Pydantic v2、StrEnum、pytest。

## 文件定位

- **讀者：** 準備實作領域模型與 Writer schema 的工程師。
- **唯一主來源：** [設計 §1、§7.6、§9.1](../../design/training-kb.md)；名稱、成員與欄位一律以 [00A 共用契約與名詞](00A-共用契約與名詞.md) 第 5.2、5.3 節為準，兩邊不一致時改本文件。
- **前置 Phase：** [Phase 02](02-Phase02-設定時間與錯誤契約.md) 的錯誤類別與 `parse_iso`。前置未通過時停止。
- **下一份：** [Phase 04 十個邏輯實體模型](04-Phase04-十個邏輯實體模型.md)。
- **本階段不做：** 不建立資料庫鍵（Phase 05）、不定義 Writer 的八個輸出 schema（Phase 17）、不呼叫 LLM、不檢查 `feature_id` 指到的 Feature 是否真的存在（Phase 21、Phase 23）。
- **錯誤語意：** 本 Phase 的所有失敗都是 pydantic 的 `ValidationError`（它是 `ValueError` 的子類）。`ContentError` 是 Phase 21 `validate_content`、Phase 22 `parse_markdown` 才丟的錯誤，本 Phase 不丟、也不 import。
- **gate 狀態：** 本 Phase 不擁有、也不關閉任何 O1–O7（設計 §18 的七個待確認事項）。這裡全綠只代表「資料形狀合法」，不代表 O1 的 metadata sort key 已核定，更不代表任何 AWS 行為可用。

## 你在整體流程的位置

```text
Phase 02 errors / clock / config
            |
            v
+-----------------------------------------+
| [你在這裡] Phase 03 models.py           |
|   七個 StrEnum、StrictModel、bare_id    |
|   ProcStep、StepDraft、TutorialContent  |
+-----------------------------------------+
     |                     |
     v                     v
Phase 04 十個邏輯實體    Phase 17／18 模型輸出 schema 與業務驗證
     |
     v
Phase 05 keys.py：唯一可以加 TUTORIAL#、FEATURE# 等前綴的地方
```

「裸 ID」是 `prepare-meeting@v2` 或 `R-007`，不帶 `VERSION#`、`RULE#`。型別前綴只屬於物理 PK／SK，避免同一欄位有時存裸值、有時存 DynamoDB key。

## 完成後看得到什麼

輸入 `StepDraft(number=1, type="click_ui", text="開啟設定", feature_id="Prepare")` 會成功，而且 `draft.type is StepType.CLICK_UI`、`draft.type == "click_ui"` 兩種寫法都成立；`feature_id="FEATURE#Prepare"`、空白文字或多給一個 `priority=1` 都會失敗。

```text
輸入 dict / kwargs
   |
   v
[1] 有模型沒宣告的欄位？ --有--> ValidationError: Extra inputs are not permitted
   | 沒有
   v
[2] 型別與 enum 值合法？ --否--> ValidationError: Input should be 'click_ui', 'input' or 'read'
   | 是
   v
[3] 單欄位 validator：裸 ID、非空文字、number >= 1 --失敗--> ValidationError
   | 通過
   v
[4] 跨欄位 model_validator：步驟編號必須是 1..n 連續
   | 通過
   v
可以交給 Phase 04 的實體與 Phase 21 的內容驗證做更嚴格的檢查
```

`TutorialContent` 必須有 Title、Problem、Prerequisites、至少一個 Step 與 Expected Outcome；`prerequisites` 可以是空清單，但 `steps` 不可以。

## 名詞小抄

| 名詞 | 白話意思 |
|---|---|
| StrEnum | 值就是字串的列舉。成員名大寫、值小寫：`StepType.CLICK_UI` 的值就是 `"click_ui"`，可以直接和字串比較。 |
| 裸 ID | 不帶 `TUTORIAL#`、`FEATURE#` 這類型別前綴的識別字串，例如 `Prepare`、`prepare-meeting@v2`、`R-007`。 |
| strict 模型／`extra="forbid"` | 多給一個沒宣告的欄位就直接失敗，不靜默丟掉。模型輸出多塞欄位時才不會被默默吃掉。 |
| frozen 模型 | 建立後不能再改欄位，要改就建立新物件；避免同一份資料在不同地方被偷偷改掉。 |
| value object（值物件） | 只描述「資料長什麼樣」的小物件，沒有身分也沒有資料庫鍵，例如 `StepDraft`。 |
| 草稿（draft） | 還沒分配版號、還沒發布的教學文字。分配版號在 Phase 20，發布在 Phase 24。 |

## 預計新增／修改的檔案

以下是實作時預計建立，目前不代表檔案存在：

- Create: `src/training_kb/models.py`
- Create: `tests/unit/test_model_primitives.py`

Phase 04 會在同一個 `models.py` 增加十實體；本 Phase 先放共用 primitive，避免循環 import。

## 固定介面

### Consumes

```text
Phase 02（00A 第 6.1 節）
   +-> parse_iso(value: str) -> datetime   Phase 04 的時間欄位會用
   +-> ContentError(PermanentError)        Phase 21／22 才丟，本 Phase 不 import
外部套件
   +-> pydantic v2：BaseModel、ConfigDict、field_validator、model_validator
   +-> 標準函式庫：enum.StrEnum
```

### Produces

七個 StrEnum 的**成員名與值**逐字照 [00A 第 5.3 節](00A-共用契約與名詞.md)（成員名大寫、值小寫），三個草稿模型的欄位逐字照 00A 第 5.2 節；兩者都不可改名，消費端也不得改用 `Literal[...]` 重新宣告：

```python
class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

# 七個 StrEnum：TicketSource、ReleaseSource、ReleaseKind、StepType、TutorialStatus、
# RuleStatus、ProcStatus（成員名與值見 Task 1 Step 3 的完整定義）
def bare_id(value: str) -> str: ...

class ProcStep(StrictModel):        # tool: str, args: dict[str, str]
    ...

class StepDraft(StrictModel):       # number: int, type: StepType, text: str, feature_id: str
    ...

class TutorialContent(StrictModel): # title, problem, prerequisites, steps, expected_outcome
    ...
```

- 七個列舉與三個草稿模型的完整定義分別在 Task 1 Step 3 與 Task 2 Step 3；上面的註解只是速查。
- `StrictModel` 是 Phase 04 起所有模型的共同基底：`extra="forbid"` 讓多餘欄位直接失敗，`frozen=True` 讓物件建立後不可改（Phase 42 的匯入驗證明講它只設這兩項，rating 的嚴格整數檢查由入口另外做）。
- **00A 第 6.2 節的備註欄寫成「`extra="forbid"` ＋ `strict=True`」，是 00A 內部的筆誤，不採用**：`strict=True` 會讓 `StepDraft(type="click_ui")` 直接被拒（實測 pydantic 2.13.5 丟 `Input should be an instance of StepType`），與本 Phase 的驗收案例、Phase 04／06／08 的敘述、以及 00A 自己的裁決 D-12／D-66（`rating=True` 要靠 P04 的 `rating_is_strict_int` 擋，代表模型層沒開 strict）全部衝突。以 `extra="forbid"` ＋ `frozen=True` 實作；00A 第 6.2 節該列備註待 00A 的 owner 修正。
- `bare_id` 是**本計畫選擇**：共用的裸 ID 檢查（拒絕空字串、前後空白、`#` 與控制字元；保留 `@` 供 `<slug>@v<n>` 使用），讓 Phase 04 的十個實體不必各自抄一份相同判斷。Phase 05 的 PK builder 另有等價檢查，不必改寫。
- 步驟編號的欄位名一律是 `number`（[00A 第 3.3 節](00A-共用契約與名詞.md)），不叫 `index` 或 `step_number`。
- `PipelineName` 由 Phase 29 以 `Literal` 定義、`ALL_STEP_TYPES` 由 Phase 40 定義（00A 第 5.3、6.9 節），本 Phase 都不要先加。

## Task 1：鎖定七個列舉、`StrictModel` 與裸 ID 規則

**Files:** `src/training_kb/models.py`、`tests/unit/test_model_primitives.py`。

**Interfaces:** Consumes raw strings；Produces 七個 StrEnum、`StrictModel`、`bare_id`。

- [x] **Step 1：寫列舉成員、strict 基底與裸 ID 測試**

```python
import pytest
from pydantic import ValidationError

from training_kb.models import (
    ProcStatus,
    ReleaseKind,
    ReleaseSource,
    RuleStatus,
    StepType,
    StrictModel,
    TicketSource,
    TutorialStatus,
    bare_id,
)

EXPECTED = {
    TicketSource: ["github_issue", "discord", "email"],
    ReleaseSource: ["github_pr", "changelog"],
    ReleaseKind: ["renamed", "changed", "removed"],
    StepType: ["click_ui", "input", "read"],
    TutorialStatus: ["active", "retired"],
    RuleStatus: ["candidate", "active", "retired"],
    ProcStatus: ["active", "retired"],
}


def test_enum_members_are_upper_case_with_lower_values() -> None:
    assert len(EXPECTED) == 7
    for enum_type, values in EXPECTED.items():
        assert [member.value for member in enum_type] == values
        assert [member.name for member in enum_type] == [v.upper() for v in values]
    assert StepType.CLICK_UI == "click_ui"
    with pytest.raises(ValueError):
        StepType("click")


def test_strict_model_forbids_extra_and_is_frozen() -> None:
    class Probe(StrictModel):
        name: str

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        Probe(name="x", priority=1)
    probe = Probe(name="x")
    with pytest.raises(ValidationError, match="Instance is frozen"):
        probe.name = "y"


def test_bare_id_rejects_prefix_and_keeps_version_shape() -> None:
    assert bare_id("prepare-meeting@v2") == "prepare-meeting@v2"
    for bad in ("FEATURE#Prepare", "", " Prepare", "Prepare\n"):
        with pytest.raises(ValueError, match="bare identifier"):
            bare_id(bad)
```

- [x] **Step 2：執行並確認紅燈**（先建立測試檔再執行）

```bash
uv run pytest tests/unit/test_model_primitives.py -q
```

預期：FAIL，訊號包含 `ModuleNotFoundError: No module named 'training_kb.models'`（或建立空檔後的 `cannot import name 'StrictModel'`）。

- [x] **Step 3：建立列舉、strict 基底與共用裸 ID 檢查**

```python
from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class TicketSource(StrEnum):
    GITHUB_ISSUE = "github_issue"
    DISCORD = "discord"
    EMAIL = "email"

class ReleaseSource(StrEnum):
    GITHUB_PR = "github_pr"
    CHANGELOG = "changelog"

class ReleaseKind(StrEnum):
    RENAMED = "renamed"
    CHANGED = "changed"
    REMOVED = "removed"

class StepType(StrEnum):
    CLICK_UI = "click_ui"
    INPUT = "input"
    READ = "read"

class TutorialStatus(StrEnum):
    ACTIVE = "active"
    RETIRED = "retired"

class RuleStatus(StrEnum):
    CANDIDATE = "candidate"
    ACTIVE = "active"
    RETIRED = "retired"

class ProcStatus(StrEnum):
    ACTIVE = "active"
    RETIRED = "retired"

class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def bare_id(value: str) -> str:
    if not value or value != value.strip():
        raise ValueError("bare identifier must not be empty or padded")
    if "#" in value or any(char < " " for char in value):
        raise ValueError("bare identifier must not contain '#' or control characters")
    return value
```

`bare_id` 保留 `@`，因為 `prepare-meeting@v2` 本身就是裸的 version ID；它拒絕 `#`，因為 `#` 只出現在 Phase 05 的物理鍵。

- [x] **Step 4：跑完整檔案確認綠燈**

```bash
uv run pytest tests/unit/test_model_primitives.py -q
```

預期：三個測試通過；七個列舉的成員名與值完全符合 [00A 第 5.3 節](00A-共用契約與名詞.md)，未知值與帶 `#` 的 ID 都被拒絕。

- [x] **Step 5：提交**

```bash
git add src/training_kb/models.py tests/unit/test_model_primitives.py
git commit -m "feat(core): 鎖定領域列舉與裸識別碼"
```

## Task 2：建立程序步驟與教學內容草稿

**Files:** 修改相同兩個檔案。

**Interfaces:** Consumes enums、`StrictModel`、`bare_id`；Produces `ProcStep`、`StepDraft`、`TutorialContent`。

- [x] **Step 1：建立失敗測試**

```python
import pytest
from pydantic import ValidationError

from training_kb.models import ProcStep, StepDraft, StepType, TutorialContent


def test_step_rejects_prefixed_feature_id() -> None:
    with pytest.raises(ValidationError, match="bare identifier"):
        StepDraft(number=1, type="click_ui", text="開啟設定", feature_id="FEATURE#Prepare")


def test_draft_accepts_bare_feature_id_string_step_type_and_jsonpath_args() -> None:
    draft = StepDraft(number=1, type="click_ui", text="開啟設定", feature_id="Prepare")
    assert draft.type is StepType.CLICK_UI and draft.type == "click_ui"
    assert ProcStep(tool="parse_github_issue", args={"title": "$.issue.title"}).args[
        "title"
    ] == "$.issue.title"


def test_step_rejects_blank_text_and_zero_number() -> None:
    with pytest.raises(ValidationError, match="must not be blank"):
        StepDraft(number=1, type="read", text="   ", feature_id="Prepare")
    with pytest.raises(ValidationError, match="1 or greater"):
        StepDraft(number=0, type="read", text="閱讀摘要", feature_id="Prepare")


def test_content_requires_contiguous_step_numbers_and_at_least_one_step() -> None:
    gap = [StepDraft(number=2, type="read", text="閱讀摘要", feature_id="Prepare")]
    for steps in (gap, []):
        with pytest.raises(ValidationError, match="contiguous"):
            TutorialContent(title="準備會議", problem="需要摘要", prerequisites=["已有會議"],
                            steps=steps, expected_outcome="可看到摘要")
    content = TutorialContent(
        title="準備會議", problem="需要摘要", prerequisites=[],
        steps=[StepDraft(number=1, type="read", text="閱讀摘要", feature_id="Prepare")],
        expected_outcome="可看到摘要",
    )
    assert content.prerequisites == []
```

- [x] **Step 2：執行並確認紅燈**

```bash
uv run pytest tests/unit/test_model_primitives.py -q
```

預期：FAIL，訊號包含 `cannot import name '<草稿模型名>' from 'training_kb.models'`（實測是 import 清單裡字母序最前的 `ProcStep`）。

- [x] **Step 3：建立三個草稿模型**

```python
from pydantic import field_validator, model_validator


def filled(value: str) -> str:
    if not value.strip():
        raise ValueError("text must not be blank")
    return value


class ProcStep(StrictModel):
    tool: str
    args: dict[str, str]


class StepDraft(StrictModel):
    number: int
    type: StepType
    text: str
    feature_id: str

    @field_validator("number")
    @classmethod
    def number_starts_at_one(cls, value: int) -> int:
        if value < 1:
            raise ValueError("number must be 1 or greater")
        return value

    @field_validator("text")
    @classmethod
    def text_is_filled(cls, value: str) -> str:
        return filled(value)

    @field_validator("feature_id")
    @classmethod
    def feature_is_bare(cls, value: str) -> str:
        return bare_id(value)


class TutorialContent(StrictModel):
    title: str
    problem: str
    prerequisites: list[str]
    steps: list[StepDraft]
    expected_outcome: str

    @field_validator("title", "problem", "expected_outcome")
    @classmethod
    def section_is_filled(cls, value: str) -> str:
        return filled(value)

    @model_validator(mode="after")
    def contiguous_steps(self) -> "TutorialContent":
        numbers = [step.number for step in self.steps]
        if not numbers or numbers != list(range(1, len(numbers) + 1)):
            raise ValueError("step numbers must be contiguous from 1 and must not be empty")
        return self
```

- `prerequisites` 允許空清單（設計 §7.6 只要求五個區塊齊全，沒有要求前置條件非空），`steps` 至少一項，因為五段 Markdown 的 Steps 區塊不能是空的。
- `ProcStep.args` 的值只放 JSONPath 字串，本 Phase 不檢查語法；白名單工具名與 JSONPath 的合法形式由 Phase 36 驗證。
- 這裡只檢查「形狀」。`feature_id` 指到的 Feature 是否存在、每步是否恰好一個 Feature，由 Phase 21 的 `validate_content` 以 `ContentError` 判定。

- [x] **Step 4：跑完整檔案確認綠燈**

```bash
uv run pytest tests/unit/test_model_primitives.py -q
uv run ruff check src/training_kb/models.py tests/unit/test_model_primitives.py
uv run mypy src/training_kb/models.py
```

預期：全部通過；extra 欄位、空文字、非連續編號、零步驟各有獨立失敗 assertion。

- [x] **Step 5：提交**

```bash
git add src/training_kb/models.py tests/unit/test_model_primitives.py
git commit -m "feat(core): 增加教學內容草稿模型"
```

## 驗收與停止條件

| 路徑 | 輸入 | 預期資料結果 |
|---|---|---|
| Happy | `StepType("click_ui")`、`StepType.CLICK_UI == "click_ui"`、`ProcStep(tool="parse_github_issue", args={"title": "$.issue.title"})` | 成功；成員名大寫、值小寫兩種比較都成立，args 原樣保留字串。 |
| Failure | `StepType("click")`、`ProcStatus("published")` | `ValueError`；不自動 fallback，也不能用 `TutorialStatus` 代替 `ProcStatus`。 |
| Failure | `feature_id="FEATURE#Prepare"` | `ValidationError`，訊息指出必須是裸 ID。 |
| Failure | `StepDraft(..., priority=1)` | `ValidationError: Extra inputs are not permitted`；模型輸出多塞欄位不被靜默丟棄。 |
| Boundary | step 編號 `1, 3` | `ValidationError`；不自動重排成 `1, 2`。 |
| Boundary | `steps=[]` ／ `prerequisites=[]` | 前者 `ValidationError`（Steps 區塊不可空），後者成功。 |
| Boundary | `number=0`、`text="   "` | `ValidationError`；編號從 1 起算、顯示文字不可全空白。 |

人工驗收：在 REPL 列出七個 `list(EnumType)` 的成員名與值，逐字比對 [00A 第 5.3 節](00A-共用契約與名詞.md)；確認沒有 `obsolete`、`published` 或第四個 step type，也沒有把成員寫成小寫名稱。

## 常見錯誤與邊界案例

| 症狀 | 原因 | 修正／停止 |
|---|---|---|
| 測試寫 `StepType.click_ui` 找不到成員 | 成員名是大寫常數 `CLICK_UI`，只有**值**是小寫 | 改用 `StepType.CLICK_UI` 或 `StepType("click_ui")`；不得為了方便新增小寫別名。 |
| 某個 Phase 想改用 `Literal["click_ui", ...]` | 以為 enum 與 Literal 等價 | 七個型別的 owner 是本 Phase；消費端一律 import StrEnum（00A 裁決 D-32）。 |
| `retired` 在 Tutorial、Rule、PROC 之間互傳沒報錯；或 validator 自己補了 ID 與時間 | 三者的值相同但型別不同；validator 誤當成生成器 | 欄位型別寫成各自的 enum 而不是 `str`；identifier 由可信程式路徑提供、時間由 Phase 02 的 `now_utc` 當參數傳入，validator 只驗證不生成。 |
| 為了讓某個 Phase 的測試變綠而想拿掉 `extra="forbid"` 或 `frozen=True` | 誤把模型當成可隨手擴充的容器 | **停止**：Phase 42 的 rating 驗證、Phase 06 的 `get_meta` 過濾都建立在這兩個設定上；要放寬必須先改 00A，不能只改本 Phase。 |
| 以為草稿通過就能發布 | 把形狀合法當成內容合法 | 草稿成功只代表結構可接受，不代表 Feature 存在、關係已寫入或可發布。 |

## 來源與 Rule 對照

- [設計 §1 名詞](../../design/training-kb.md#s1)：TutorialVersion、Step／Task、candidate／active／retired 的意思。
- [設計 §7.6](../../design/training-kb.md#s7)：`applies_when` 只支援 `click_ui`、`input`、`read`；模型輸出要先過 JSON schema 再過業務驗證。
- [設計 §9.1](../../design/training-kb.md#s9)：邏輯關聯欄位保存裸 ID，PK／SK／target 才加類型前綴。
- [建立教學版本.feature](../../spec/features/建立教學版本.feature)
  - Rule 9：「沒有 Feature 或引用多個 Feature 的步驟不可保存」→ 相關（primary 在 [Phase 21](21-Phase21-教學內容與步驟引用驗證.md)）。本 Phase 只保證 `StepDraft.feature_id` 是單一非空裸 ID，不查 Feature 是否存在。
- [套用教學規則.feature](../../spec/features/套用教學規則.feature)
  - Rule 3：「依 step 型態與 applies_when 篩選規則」→ 相關（primary 在 [Phase 19](19-Phase19-Active規則選取與注入.md)）。本 Phase 提供 `StepType` 這個唯一合法的篩選型別。
- [接入來源事件.feature](../../spec/features/接入來源事件.feature)
  - Rule 25：「正規化物件的枚舉欄位必須使用合法值」→ 相關（primary 在 [Phase 31](31-Phase31-Ticket與Release正規化.md)）。Task 1 的 `test_enum_members_are_upper_case_with_lower_values` 裡 `StepType("click")` 被拒絕，是型別層的證據。
- 本 Phase 沒有 primary Rule；直接 assertion 由上述 owning Phase 完成（對照表見 [00B 需求覆蓋對照](00B-需求覆蓋對照.md)）。

## 完成清單

- [x] 七個 StrEnum 的成員名與值逐字符合 00A 第 5.3 節（大寫成員名、小寫值）。
- [x] `StrictModel` 只設 `extra="forbid"` 與 `frozen=True`，並可被 Phase 04 直接繼承。
- [x] `bare_id` 拒絕空字串、前後空白、`#` 與控制字元，且保留 `@`。
- [x] 三個草稿模型拒絕 extra 欄位、空白必要文字、非連續步驟編號與零步驟。
- [x] `PipelineName`、`ALL_STEP_TYPES` 沒有被提早加入。
- [x] 兩個 Task 都先紅後綠，且全程沒有模型呼叫或 AWS 呼叫。
- [x] 下一份可在同一檔案加入十個邏輯實體，不需要改本 Phase 的任何名稱。

**下一份可用成果：** 可重用的 enum、PROC step 與完整教學草稿 value objects。
