# Phase 04 十個邏輯實體模型 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 依主設計建立十個邏輯實體的嚴格 Python 模型，完整包含 `TutorialView`，並在寫入 Repository 前守住跨欄位不變條件。

**Architecture:** 領域模型不帶 DynamoDB `PK/SK`，只保存來源規定的裸識別碼與原生 List/Map/數值型別。單表序列化留到 Phase 06，避免把十個實體誤做十張表。

**Tech Stack:** Python 3.12、Pydantic v2、pytest。

## 文件定位

- **讀者：** Repository、Ingress、Writing 與 Analytics 的實作者。
- **唯一主來源：** [設計 §2、§7.1、§9](../../design/training-kb.md) 與 [ERM](../../spec/erm.dbml)；欄位名稱與型別一律以 [00A 共用契約與名詞](00A-共用契約與名詞.md) 第 5.1 節為準，兩邊不一致時改本文件。
- **前置 Phase：** [Phase 03](03-Phase03-識別碼列舉與內容草稿模型.md) 的七個 StrEnum、`StrictModel`、`bare_id` 與 `ProcStep`。前置未通過時停止。
- **下一份：** [Phase 05 單表鍵與關係邊契約](05-Phase05-單表鍵與關係邊契約.md)。
- **本階段不做：** 不選 metadata SK（Phase 05）、不建立資料庫（Phase 06、09）、不把 model validation 當 referential integrity、不加 `PK`／`SK`／`entity`／`_revision` 這些物理屬性。
- **gate 狀態：** 十實體全綠只代表「欄位形狀合法」。O1（metadata sort key）仍未核定，不得宣稱物理鍵契約已定案；O2（永久去重與接受順序）也未 PASS，模型層的唯一性檢查不能當成儲存層唯一性。

## 你在整體流程的位置

```text
接入輸入 / 模型輸出（裸 ID）
             |
             v
+------------------------------------------+
| [你在這裡] Phase 04 十個邏輯實體          |
|   Tutorial / TutorialVersion / Step       |
|   Feature / Ticket / Release              |
|   Feedback / TutorialView                 |
|   AuthoringRule / ProvenWorkflow + Entity |
+------------------------------------------+
             |
             v
Phase 05 keys.py -> Phase 06 Repository -> 一張 training_kb 表
```

十個實體是領域概念數量，不是資料庫表數量。`TutorialView` 是重開票率的必要分母來源；漏掉它就無法分辨「有看過再開票」和一般 Ticket。

## 完成後看得到什麼

輸入一張 `Ticket`，`author` 必填、`feature_ids` 長度只能 0 或 1、`embedding` 若存在必須是 1024 個有限 float、`ts` 必須帶時區。輸入 `Feedback(rating=True)` 必須被拒絕，因為 bool 不能冒充 1 分。

執行模型盤點測試時，`Entity` union 的成員恰好是這十個，多一個或少一個都會紅燈：

```text
Tutorial ----+                         Feature <---- TutorialStep
             |                            ^              ^
TutorialVersion <---- TutorialStep        |              |
     ^      ^                          Release        Ticket（最多一個 Feature）
     |      |
Feedback  TutorialView                 AuthoringRule --(applied_to/derived_from)--> TutorialVersion

ProvenWorkflow：只有 Rote 讀寫，沒有任何圖譜邊
```

上圖只畫「欄位指向誰」。真正的邊（`REFERENCES#`、`SUPERSEDES#`、`APPLIED_TO#`、`ASKS_ABOUT#`、`REFERS_TO#`）由 Phase 05 與 Phase 07 寫入；本 Phase 只保證關聯欄位存的是裸 ID。

## 名詞小抄

| 名詞 | 白話意思 |
|---|---|
| 邏輯實體 | 領域裡的一種東西（例如一篇教學、一則工單）。十個邏輯實體最後都存進同一張 DynamoDB 表，不是十張表。 |
| 裸 ID | 不帶 `VERSION#`、`FEATURE#` 前綴的識別字串，例如 `prepare-meeting@v2`、`Prepare`。 |
| 不變條件（invariant） | 一個物件無論怎麼建立都必須成立的規則，例如「`kind=renamed` 就一定要有新舊名稱」。 |
| aware datetime | 帶時區的時間。本專案一律 UTC；沒有時區的 naive 時間一律拒絕（Phase 02 的規則）。 |
| referential integrity | 「被指到的東西真的存在」。模型檢查不了它，要等 Repository（Phase 06）與內容驗證（Phase 21）。 |
| `Entity` union | 十個實體的聯集型別，`Repository.put_meta(entity: Entity)` 用它限制只能寫這十種。 |

## 預計新增／修改的檔案

以下是實作時預計建立，目前不代表檔案存在：

- Modify: `src/training_kb/models.py`
- Create: `tests/unit/test_entities.py`
- Create: `tests/unit/test_entity_invariants.py`

## 固定介面

### Consumes

Phase 03 已定義（[00A 第 5.2、5.3、6.2 節](00A-共用契約與名詞.md)）：

```text
StrictModel                 -> extra="forbid" + frozen=True 的共同基底
七個 StrEnum                -> TicketSource / ReleaseSource / ReleaseKind / StepType /
                               TutorialStatus / RuleStatus / ProcStatus
ProcStep(tool, args)        -> ProvenWorkflow.steps 的元素
bare_id(value) -> str       -> 關聯欄位的裸 ID 檢查（本計畫選擇）
Phase 02: parse_iso(value)  -> 說明時間格式用；模型直接宣告 datetime 欄位即可
```

### Produces

十個邏輯實體與 `Entity` union（[00A 第 5.1、6.2 節](00A-共用契約與名詞.md)）。欄位名稱、順序與型別逐字照 00A，不得增刪，也不得為了方便加上 `PK`、`SK`、`entity`、`_revision`、`step_count`、`retired_at` 這類屬性：

| 模型 | 固定欄位 |
|---|---|
| `Tutorial` | `slug: str`、`current_version: str \| None`、`topic: str`、`feature_ids: list[str]`、`status: TutorialStatus`、`successor: str \| None`、`cluster_id: str \| None` |
| `TutorialVersion` | `version_id: str`、`slug: str`、`supersedes: str \| None`、`reason: str`、`rules_applied: list[str]`、`s3_key: str`、`published_at: datetime \| None` |
| `TutorialStep` | `tutorial_version: str`、`number: int`、`type: StepType`、`text: str`、`feature_id: str` |
| `Feature` | `feature_id: str`、`name: str`、`aliases: list[str]`、`first_seen: datetime` |
| `Ticket` | `id: str`、`source: TicketSource`、`text: str`、`author: str`、`ts: datetime`、`project_id: str`、`cluster_id: str \| None`、`feature_ids: list[str]`、`embedding: list[float] \| None` |
| `Release` | `id: str`、`source_event_id: str \| None`、`source: ReleaseSource`、`feature: str`、`kind: ReleaseKind`、`old_name: str \| None`、`new_name: str \| None`、`evidence: str`、`ts: datetime` |
| `Feedback` | `id: str`、`tutorial_version: str`、`rating: int \| None`、`category: str \| None`、`comment: str \| None`、`user: str`、`ts: datetime \| None` |
| `TutorialView` | `tutorial_version: str`、`user: str`、`ts: datetime` |
| `AuthoringRule` | `rule_id: str`、`rule: str`、`applies_when: StepType`、`evidence: list[str]`、`status: RuleStatus`、`applied_to: list[str]`、`derived_from: str` |
| `ProvenWorkflow` | `signature: str`、`domain: str`、`adapter: str`、`steps: list[ProcStep]`、`keys: list[str]`、`success_count: int`、`fail_count: int`、`status: ProcStatus`、`last_used: datetime` |

```python
Entity = (Tutorial | TutorialVersion | TutorialStep | Feature | Ticket
          | Release | Feedback | TutorialView | AuthoringRule | ProvenWorkflow)
```

`Entity` 是 Phase 06 `Repository.put_meta(entity: Entity, ...)` 的參數型別，也是「恰好十個」這件事的唯一可驗證來源。

三個要特別記住的裁決（[00A 第 8 節](00A-共用契約與名詞.md) D-09、D-10、D-12）：

- **`ProvenWorkflow.domain` 與 `adapter` 是「本計畫選擇（對應 O2／D19：來源脈絡需要持久化）」。** ERM 的 PROVEN_WORKFLOW 沒有這兩欄，但簽名本身刻意不含事件值、也不能反推來源，而 Phase 33 要把 adapter 範圍存在 PROC、Phase 34 只在「同 domain + 同 adapter」內比 Jaccard、Phase 08 的 `list_procs(domain, adapter)` 也要用它們。兩者都存可信入口設定給的值，不從 payload 或模型推得。
- **`AuthoringRule.applies_when` 的型別是 `StepType`，不是字串運算式也不是 dict。** 模型輸出 schema `RuleProposal.applies_when` 是字串（`"click_ui"`／`"input"`／`"read"`），由 Phase 47 驗證後轉成 `StepType` 才存入；Phase 19 的篩選寫成 `rule.applies_when == step_type`。不得出現 `"step.type == click_ui"` 或 `{"step.type": "click_ui"}`。
- **`Feedback.rating` 是 `int | None`，`ts` 也可為 `None`。** 模型允許缺評分，是因為歷史匯入可能沒有；但**固定匯入入口比模型嚴格**：Phase 42 的 `validate_feedback` 要求 1..5 的嚴格整數並排除 `bool`，缺 rating 直接 `rejected`。本 Phase 的模型另外把「有給值時必須是 1..5 的真整數」也擋掉，兩層都擋不算重複，入口的驗證不因此放寬。`ts` 缺值時由匯入工具記匯入時間，並且不得假稱那是使用者實際提交時間。

## Task 1：建立十實體與基本欄位驗證

**Files:** `src/training_kb/models.py`、`tests/unit/test_entities.py`。

**Interfaces:** Consumes primitives；Produces all ten entities。

- [x] **Step 1：建立失敗測試**

```python
from typing import get_args

import pytest
from pydantic import ValidationError

from training_kb import models

NAMES = ["Tutorial", "TutorialVersion", "TutorialStep", "Feature", "Ticket",
         "Release", "Feedback", "TutorialView", "AuthoringRule", "ProvenWorkflow"]


def test_exactly_ten_entity_models_are_public() -> None:
    assert [model.__name__ for model in get_args(models.Entity)] == NAMES
    assert all(issubclass(model, models.StrictModel) for model in get_args(models.Entity))
    for absent in ("User", "Project", "KnowledgeGap"):
        assert not hasattr(models, absent)


def test_ticket_accepts_zero_or_one_feature() -> None:
    ticket = models.Ticket(
        id="t_881", source="email", text="找不到按鈕", author="u_01",
        ts="2026-08-03T10:00:00Z", project_id="demo", feature_ids=[],
    )
    assert ticket.feature_ids == [] and ticket.ts.tzinfo is not None


def test_ticket_requires_author_and_aware_ts() -> None:
    base = dict(id="t_882", source="email", text="找不到按鈕", project_id="demo")
    with pytest.raises(ValidationError, match="author"):
        models.Ticket(**base, ts="2026-08-03T10:00:00Z")
    with pytest.raises(ValidationError, match="aware"):
        models.Ticket(**base, author="u_01", ts="2026-08-03T10:00:00")
```

- [x] **Step 2：執行並確認紅燈**

```bash
uv run pytest tests/unit/test_entities.py -q
```

預期：FAIL，訊號包含 `cannot import name 'Entity'` 或 `module 'training_kb.models' has no attribute 'Ticket'`。

- [x] **Step 3：按欄位表建立 strict models**

Ticket 是欄位最多的一個，完整形狀如下；其餘九個照 Produces 的欄位表逐欄實作，`Entity` 放在十個類別之後：

```python
from datetime import datetime
from math import isfinite

from pydantic import field_validator


def aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise ValueError("datetime must be timezone aware")
    return value


class Ticket(StrictModel):
    id: str
    source: TicketSource
    text: str
    author: str
    ts: datetime
    project_id: str
    cluster_id: str | None = None
    feature_ids: list[str] = []
    embedding: list[float] | None = None

    @field_validator("ts")
    @classmethod
    def ts_is_aware(cls, value: datetime) -> datetime:
        return aware(value)

    @field_validator("feature_ids")
    @classmethod
    def one_feature_at_most(cls, value: list[str]) -> list[str]:
        if len(value) > 1:
            raise ValueError("Ticket feature_ids length must be 0..1")
        return [bare_id(item) for item in value]

    @field_validator("embedding")
    @classmethod
    def valid_embedding(cls, value: list[float] | None) -> list[float] | None:
        if value is not None and (len(value) != 1024 or not all(isfinite(x) for x in value)):
            raise ValueError("embedding must contain 1024 finite numbers")
        return value


Entity = (Tutorial | TutorialVersion | TutorialStep | Feature | Ticket
          | Release | Feedback | TutorialView | AuthoringRule | ProvenWorkflow)
```

不加入 `User`、`Project`、`KnowledgeGap` 或 `view_id` 實體：Knowledge Gap 由 `Ticket.cluster_id` 表達，View 的鍵由 Phase 05 用三元組雜湊算出，不需要輸入欄位。

- [x] **Step 4：跑完整檔案確認綠燈**

```bash
uv run pytest tests/unit/test_entities.py -q
```

預期：三個測試通過；十個合法 fixture 都能建立，缺必要欄位各自失敗。

- [x] **Step 5：提交**

```bash
git add src/training_kb/models.py tests/unit/test_entities.py
git commit -m "feat(core): 建立十個邏輯實體模型"
```

## Task 2：鎖定跨欄位不變條件

**Files:** `src/training_kb/models.py`、`tests/unit/test_entity_invariants.py`。

**Interfaces:** Consumes ten models；Produces validated invariants before persistence。

- [x] **Step 1：建立失敗測試**

```python
import pytest
from pydantic import ValidationError

from training_kb.models import (AuthoringRule, Feature, Feedback, Release, StepType,
                                Ticket, Tutorial)


def test_rating_rejects_bool_and_out_of_range() -> None:
    for bad in (True, 0, 6, 3.5, "4"):
        with pytest.raises(ValidationError, match="integer from 1 to 5"):
            Feedback(id="f_1", tutorial_version="prepare-meeting@v1", rating=bad, user="u_01")
    kept = Feedback(id="f_2", tutorial_version="prepare-meeting@v1", rating=None,
                    comment="第三步沒有指出按鈕在哪一頁", user="u_01")
    assert kept.rating is None and kept.ts is None


def test_ticket_has_at_most_one_feature() -> None:
    with pytest.raises(ValidationError, match=r"0\.\.1"):
        Ticket(id="t_883", source="email", text="找不到按鈕", author="u_01",
               ts="2026-08-03T10:00:00Z", project_id="demo",
               feature_ids=["Prepare", "Share Summary"])


def test_renamed_release_requires_both_names() -> None:
    with pytest.raises(ValidationError, match="old_name and new_name"):
        Release(
            id="r_42", source="github_pr", feature="Prepare", kind="renamed",
            evidence="PR diff hunk", ts="2026-08-04T00:00:00Z",
        )


def test_rule_applies_when_is_a_single_step_type() -> None:
    rule = AuthoringRule(rule_id="R-007", rule="點 UI 時寫出頁面與按鈕位置",
                         applies_when="click_ui", status="candidate",
                         evidence=["f_12", "f_15", "f_19", "f_23", "f_27"],
                         applied_to=[], derived_from="prepare-meeting@v1")
    assert rule.applies_when is StepType.CLICK_UI
    with pytest.raises(ValidationError):
        AuthoringRule(rule_id="R-008", rule="x", applies_when="step.type == click_ui",
                      status="candidate",
                      evidence=["f_12", "f_15", "f_19", "f_23", "f_27"],
                      applied_to=[], derived_from="prepare-meeting@v1")


def test_tutorial_and_feature_ids_have_no_tenant_dimension() -> None:
    assert "project_id" not in Tutorial.model_fields
    assert "project_id" not in Feature.model_fields
```

- [x] **Step 2：執行並確認紅燈**

```bash
uv run pytest tests/unit/test_entity_invariants.py -q
```

預期：FAIL。最明顯的訊號是 `Feedback(rating=True)` 沒有被拒絕——pydantic 在寬鬆模式會把 `True` 轉成 `1`，所以一定要用 `mode="before"` 的 validator 才擋得住。

- [x] **Step 3：增加具體不變條件**

```python
from typing import Any

from pydantic import model_validator


class Feedback(StrictModel):
    id: str
    tutorial_version: str
    rating: int | None = None
    category: str | None = None
    comment: str | None = None
    user: str
    ts: datetime | None = None

    @field_validator("rating", mode="before")
    @classmethod
    def rating_is_strict_int(cls, value: Any) -> Any:
        if value is not None and (type(value) is not int or not 1 <= value <= 5):
            raise ValueError("rating must be an integer from 1 to 5")
        return value

    @model_validator(mode="after")
    def carries_signal(self) -> "Feedback":
        if self.rating is None and self.category is None and not (self.comment or "").strip():
            raise ValueError("feedback must carry a rating, a category or a comment")
        return self
```

其餘不變條件逐條實作：

- `Release.kind=renamed` 時 `old_name`、`new_name` 都是非空字串；`changed`、`removed` 允許空（設計 §7.1）。
- `TutorialStep.number >= 1`、`feature_id` 恰好一個非空裸 ID（用 Phase 03 的 `bare_id`）。
- `Feature.aliases` 自身不得重複，也不得包含自己的 `name`；跨 Feature 的 alias 唯一性留給 Repository（Phase 49）。
- `AuthoringRule.evidence` 至少五個不同 Feedback ID（**本計畫選擇**：讓證據不足的規則連物件都建不出來；正式的「同版同類 ≥ 5」判定仍在 Phase 47），`derived_from` 恰一個裸 version ID。
- `ProvenWorkflow.success_count`／`fail_count` `>= 0`；`signature` 是 16 位小寫 hex；`domain`、`adapter` 非空。
- `Feedback` 至少要有 rating、category、非空 comment 其中一項（**本計畫選擇**；只有評分是合法的，符合設計 §11.2 的 `f_103`～`f_110`）。
- 所有 datetime 必須 aware，模型內不補 `now`；時間一律由呼叫端傳入（Phase 02 的規則）。

- [x] **Step 4：跑完整檔案確認綠燈**

```bash
uv run pytest tests/unit/test_entities.py tests/unit/test_entity_invariants.py -q
uv run ruff check src/training_kb/models.py tests/unit
uv run mypy src/training_kb/models.py
```

預期：所有邊界 assertion 通過；沒有用 `Any` 跳過欄位型別（`rating` 的 `mode="before"` validator 是唯一例外，因為它要看到轉型前的原值）。

- [x] **Step 5：提交**

```bash
git add src/training_kb/models.py tests/unit/test_entity_invariants.py
git commit -m "feat(core): 鎖定實體欄位不變條件"
```

## Primary Rule 驗收：PRP Rule 6 與 TIC Rule 6

兩條 primary Rule 的直接 assertion 都放在 `tests/unit/test_entity_invariants.py`（見 Task 2 Step 1）：

- **PRP Rule 6「MVP 的教學與產品功能識別碼在單一專案範圍內唯一」** → `test_tutorial_and_feature_ids_have_no_tenant_dimension`。這只鎖 MVP 單一專案的模型範圍；識別碼唯一性仍需 Phase 06 的條件寫入驗證。不得把「沒有 `project_id`」宣稱成跨專案安全。
- **TIC Rule 6「一張 Ticket 對應零或一個 Feature」** → `test_ticket_has_at_most_one_feature`，加上 Task 1 的 `test_ticket_accepts_zero_or_one_feature` 覆蓋零個的情況。[00B 需求覆蓋對照](00B-需求覆蓋對照.md) 第 3.1 節把這條從「無人認領」升為本 Phase 的 primary。**注意 00B 的建議文字寫成 `Ticket.feature_id`，但 00A 第 5.1 節與 [ERM](../../spec/erm.dbml) 的欄位是 `feature_ids: list[str]`（長度 0 或 1，不另增 scalar 欄位）**；本文件依 00A 實作 `feature_ids`，斷言改成「兩個元素被拒絕」。

## 驗收與停止條件

| 路徑 | 輸入 | 預期資料結果 |
|---|---|---|
| Happy | 十個合法 fixture（含 `TutorialView(tutorial_version, user, ts)`） | 全部建立成功，`get_args(Entity)` 恰好十個。 |
| Happy | `ProvenWorkflow(domain="github.com", adapter="issues", ...)` | 成功；`list_procs(domain, adapter)`（Phase 08）之後才查得到同範圍的 PROC。 |
| Failure | 1023／1025 維、含 NaN 或 Infinity 的 embedding | 拒絕，訊息指出必須是 1024 個有限數值。 |
| Failure | Ticket 兩個 `feature_ids`、缺 `author`、naive `ts` | 三者都拒絕。 |
| Failure | `Feedback(rating=True)`、`rating="4"`、`rating=0`、`rating=6` | 全部拒絕；bool 不能冒充 1 分。 |
| Failure | `AuthoringRule(applies_when="step.type == click_ui")` | 拒絕；`applies_when` 只能是單一 `StepType`。 |
| Boundary | `rating=1`／`rating=5` | 接受；`rating=None` 但有 comment 也接受。 |
| Boundary | active Tutorial 且 `current_version=None` | 模型允許，符合首次發布前狀態（判定已有教學時仍算 active，會擋重複 CREATE）。 |
| Boundary | retired Tutorial 且 `successor=None` | 模型允許；沒有後繼仍可完成退役。 |
| Boundary | 未發布 version | `published_at=None`；模型不阻止，但 Phase 24 不得把它寫進 `site/`。 |

人工驗收：逐項比對 [ERM 十張邏輯表](../../spec/erm.dbml) 與 [00A 第 5.1 節](00A-共用契約與名詞.md)，確認欄位沒漏、原生清單沒有被 JSON 字串化、沒有第十一個業務實體，也沒有偷加 `PK`／`SK`／`step_count`。

## 常見錯誤與邊界案例

| 症狀 | 原因 | 修正／停止 |
|---|---|---|
| 文件或程式寫「九實體」 | 沿用草稿與舊 AGENTS 說明 | 主設計 §2 已裁決十實體（含 `TUTORIAL_VIEW`）；發現九實體的殘留就改掉。 |
| 把 `Tutorial.current_version=None` 當成 retired | 混淆「沒有已發布版本」與「已退役」 | 只有 `status` 決定退役；active 但尚未首次發布仍會擋重複 CREATE（Phase 40）。 |
| 改名時想換 `Feature.feature_id` | 以為 ID 跟著顯示名稱走 | `feature_id` 是第一次建立時固定的，改名只動 `name` 與 `aliases`，PK 不遷移（設計 §9.1）。 |
| `Feedback(rating=True)` 竟然通過 | validator 用預設的 `mode="after"`，看到的已經是被轉型後的 `1` | 改成 `mode="before"` 並用 `type(value) is not int` 判斷。 |
| 為了讓某個 fixture 過關，想在 item 上加 `step_count`、`retired_at` | 把模型當成可隨手擴充的容器 | **停止**：item 屬性 = 模型欄位 + `RESERVED_ATTRS`，沒有第三類（00A 第 3.6 節、裁決 D-40）。需要保存的執行資訊寫進 operation 紀錄或私有 S3。 |
| 以為模型通過就代表資料正確 | 把 validation 當成 referential integrity | 模型不查被引用的 version／Feature 是否存在；那是 Phase 06、21、23 的事。`AuthoringRule.evidence` 的「五筆」也只是計數，Phase 47 才確認它們同屬一個版本、同一類別。 |

## 來源與 Rule 對照

- [設計 §2 衝突裁決](../../design/training-kb.md#s2)：十實體包含 TUTORIAL_VIEW；D23 覆寫 D09（設計 §19.1 的資料決策編號），`Ticket.author` 改為必填。
- [設計 §7.1](../../design/training-kb.md#s7)：Ticket、Release、Feedback、View 的必填欄位與合法值；Feedback 缺 `ts` 時記匯入時間但不假稱是提交時間。
- [設計 §9](../../design/training-kb.md#s9)：單表投影、原生 List／Map 型別、關聯欄位存裸 ID。
- [提出教學規則.feature](../../spec/features/提出教學規則.feature)
  - Rule 6：「MVP 的教學與產品功能識別碼在單一專案範圍內唯一」→ **primary**，由 `test_tutorial_and_feature_ids_have_no_tenant_dimension` 直接斷言；儲存層唯一性在 Phase 06。
- [分析工單.feature](../../spec/features/分析工單.feature)
  - Rule 6：「一張 Ticket 對應零或一個 Feature」→ **primary**（00B 第 3.1 節裁決），由 `test_ticket_has_at_most_one_feature` 與 `test_ticket_accepts_zero_or_one_feature` 直接斷言。
  - Rule 1：「每則 Ticket 在接入分析時計算一次並儲存 1024 維 embedding」→ 相關（primary 在 [Phase 38](38-Phase38-Ticket-Embedding與群中心分群.md)）；本 Phase 只鎖 1024 維與有限數值。
- [建立教學版本.feature](../../spec/features/建立教學版本.feature)
  - Rule 9：「沒有 Feature 或引用多個 Feature 的步驟不可保存」→ 相關（primary 在 [Phase 21](21-Phase21-教學內容與步驟引用驗證.md)）；本 Phase 只保證 `TutorialStep.feature_id` 是單一非空裸 ID。
- [收集教學回饋.feature](../../spec/features/收集教學回饋.feature)（縮寫 `COL`）
  - Rule 3：「Feedback 的 rating 只能為 1 到 5 的整數」→ 相關（primary 在 [Phase 42](42-Phase42-Feedback與View固定匯入.md)）。
  - Rule 9：「Feedback 接入時必須提供穩定使用者 ID」→ 相關（primary 在 Phase 42）；本 Phase 只讓 `user` 必填。
- [接入來源事件.feature](../../spec/features/接入來源事件.feature)
  - Rule 21／22／25（必填欄位、Ticket 六個必填、合法 enum）→ 相關（primary 都在 [Phase 31](31-Phase31-Ticket與Release正規化.md)）。
- 完整對照見 [00B 需求覆蓋對照](00B-需求覆蓋對照.md)。

## 實作備註（2026-09-14 完成時補記）

實作時與本文件原文不一致、已依「設計 > 00A > 本文件」裁決的地方：

| 項目 | 本文件原文 | 實作結果 | 理由 |
|---|---|---|---|
| 可為 `None` 欄位的預設值 | Produces 欄位表與 Task 1 Step 3 片段只寫型別，沒寫 `= None` | `Tutorial.current_version`／`successor`／`cluster_id`、`TutorialVersion.supersedes`／`published_at`、`Ticket.cluster_id`／`embedding`、`Release.source_event_id`／`old_name`／`new_name`、`Feedback.rating`／`category`／`comment`／`ts` 全部給 `= None` | [00A 第 5.1 節](00A-共用契約與名詞.md)「可為 `None` 的欄位在模型層一律給預設值 `None`」；`Ticket.feature_ids = []` 照本文件 Task 1 Step 3 片段，其餘 list 欄位維持必填（00A 沒給預設值） |
| `aware()` 的位置 | Task 1 Step 3 片段把它寫在 `Ticket` 之前 | 放在 `TutorialContent` 之後、十實體之前 | 不插入也不搬動 Phase 03 既有的 `StrictModel`／`bare_id`／`filled`／`ProcStep` 區塊 |
| 測試檔 import 排版 | Task 2 Step 1 用括號單行 import | 改成既有 `tests/unit/test_model_primitives.py` 的一行一個名稱 | `ruff` 的 `I001` 要求；測試函式內容逐字沿用，斷言未改 |
| `AuthoringRule.evidence` 的消費端 | 只寫「至少五個不同 Feedback ID」 | 已實作；[00A D-66](00A-共用契約與名詞.md) 點名 P47／P55／P56 的 fixture 要給滿五筆 | **[Phase 19](19-Phase19-Active規則選取與注入.md) Task 的 fixture 目前是 `evidence=["f_12"]`（一筆），會被本 Phase 的 validator 拒絕，由 P19 實作者補成五筆不同 ID** |

其餘關聯欄位（`slug`、`version_id`、`feature_id`、`rule_id`、`derived_from`、`applied_to`、`rules_applied`、`tutorial_version`、`author`／`user`、`project_id`、`id` 等）一律過 Phase 03 的 `bare_id`；顯示用文字（`topic`、`text`、`reason`、`s3_key`、`evidence`、`rule`、`domain`、`adapter`）過 `filled`。`Feedback.category`／`comment` 不另加空白檢查，只由 `carries_signal` 一起判定。

## 完成清單

- [x] `get_args(Entity)` 恰好十個，順序與 00A 第 5.1 節一致，且每個都繼承 `StrictModel`。
- [x] `TutorialView` 存在且 `tutorial_version`／`user`／`ts` 全部必填。
- [x] `Ticket.author` 必填（D23 覆寫 D09），`ts` 必須 aware。
- [x] bool rating、非法 embedding、兩個 Ticket feature、非 `StepType` 的 `applies_when` 都被拒絕。
- [x] `ProvenWorkflow` 有 `domain` 與 `adapter`，並在文件中標明是本計畫選擇。
- [x] 模型沒有物理 `PK`／`SK`／`_revision`，也沒有第十一個業務實體。
- [x] PRP Rule 6 與 TIC Rule 6 的直接 assertion 都通過。
- [x] 尚未宣稱 referential integrity、AWS CRUD 或跨專案隔離通過。

**下一份可用成果：** 十個經本機驗證的領域模型，可安全交給 key builder 與 Repository serializer。
