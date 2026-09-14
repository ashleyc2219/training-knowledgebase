# Phase 47：Candidate 規則提出與溯源實作計畫

> **給實作者：** 依 checkbox 做 TDD；每個 Task 先建立失敗測試，再寫最小實作，每個 Task 都要留下可單獨審查的提交。

**目標：** 從同一個已發布版本、同一個核定類別的至少五筆不同 Feedback，提出一條可逐筆回查的 candidate 規則。

**架構：** Feedback Review 的 candidate 分支與弱教學分支完全獨立。固定程式先形成 `CandidateGroup` 並驗證證據範圍，再呼叫模型產生 `RuleProposal`；模型只決定 `rule` 與 `applies_when` 兩個欄位，`rule_id`、`evidence`、`derived_from`、`status`、`applied_to` 一律由程式依已驗證的 group 填入。

**技術：** Python 3.12、Pydantic v2、pytest、Phase 15 的 `Writer.generate_json`、Phase 17 的 `RuleProposal` JSON schema、DynamoDB `Repository`。

## 全域限制

- 唯一主來源是 [Training KB 設計 §7.5、§7.6、§9.1、§12.2](../../design/training-kb.md)；名稱與簽名以 [00A 共用契約與名詞](00A-共用契約與名詞.md) 為準，Rule 歸屬以 [00B 需求覆蓋對照](00B-需求覆蓋對照.md) 為準。
- [00 總覽](00-總覽.md) 順序的前一份是 [Phase 46：REFINE 精準改寫與證據去重](46-Phase46-REFINE精準改寫與證據去重.md)；本階段真正依賴的是 [Phase 43：Feedback 類別判定](43-Phase43-Feedback類別判定.md) 的核定類別表、[Phase 17：Claude 結構化輸出與 Prompt](17-Phase17-Claude結構化輸出與Prompt.md) 的 `RuleProposal` schema，以及 Phase 04–08 的實體模型與 `Repository`。**Candidate 分支不依賴 Phase 46 是否成功改版**，前置未通過時停止。
- 下一階段是 [Phase 48：Feedback Review 排程流程](48-Phase48-Feedback-Review排程流程.md)，由它決定何時呼叫 `candidate_groups`、`candidate_rule_id` 與 `propose_candidate`。
- 本階段不做：不排程、不組 pipeline（Phase 48）；不做診斷與 REFINE（Phase 45／46）；不寫任何 `RULE.status` 轉移（只有 Phase 55 的 `apply_rule_status` 能寫）；不把 candidate 放進 CREATE／UPDATE／REFINE 的 prompt（Phase 19 只選 active）；不計算指標、不比較前後成效（Phase 53–55）。
- 提案門檻**不要求**平均 `< 3.5`，也不要求總樣本達到弱教學門檻（設計 F26；`F` 開頭是設計文件 §19.2 的功能決策編號，`D` 開頭是 §19.1 的資料決策編號）。證據必須來自同一個 `TutorialVersion`、同一個核定類別、至少五個**不同** Feedback ID；`evidence` 只存 ID（設計 D15）；`derived_from` 恰好一個版本（設計 D18）。
- `AuthoringRule.applies_when` 的型別是 `StepType`；模型輸出的 `RuleProposal.applies_when` 是 `"click_ui"`／`"input"`／`"read"` 其中一個**字串**，驗證通過後才轉成 `StepType` 存入（00A 第 8 節 D-10、設計 D16）。不得寫成 `"step.type == click_ui"` 字串或 `{"step.type": "click_ui"}` dict。
- 與本 Phase 有關的 O1–O7 gate（`O` 開頭的編號是設計文件 §18 的七個待確認事項）：**O5** 模型與參數未通過前，本階段只能用假 `Writer` 做單元測試，不得宣稱真實 Bedrock 路徑已驗證；**O7** 核定種子未完成前，candidate 只能說「已提出」，不得寫成「已驗證有效」，也不得自動變成 active；**O2** 操作紀錄未 PASS 前，「重送不重複提案」只由「決定性 `rule_id` 加上寫入前條件檢查」達成，不得宣稱永久去重已驗證。
- 以下程式檔均是實作時預計建立或修改；本計畫本身不代表它們已存在。

---

## 1. 你在整體流程的位置

```text
Phase 48 feedback-review 的 EvaluateTargets Task
                 |
   某個 current 已發布版本的全部有效 Feedback（Phase 08 讀出）
                 |
       +---------+-----------+
       |                     |
  弱教學分支 44/45/46   candidate 分支 [你在這裡] 47
       |                     |
       v                     v
   RefinePlan          candidate_groups() -> 同版同類不同 ID >= 5？
                             | 是
                             v
                 propose_candidate() -> RuleProposal
                             v
                RULE#<rule_id>，status=candidate
                             v
          Phase 55 Analytics 才能把 status 改成 active/retired
```

## 2. 完成後看得到什麼

輸入是 `prepare-meeting@v1` 的八筆回饋（設計 §11.2 的 `f_12`、`f_15`、`f_19`、`f_23`、`f_27`、`f_31`、`f_34`、`f_40`，類別都是「找不到按鈕」），加上核定類別表 `{"找不到按鈕", "缺少資訊"}`。

`candidate_groups(...)` 回傳一組 `CandidateGroup(version_id="prepare-meeting@v1", category="找不到按鈕", feedback_ids=("f_12", ..., "f_40"))`；`candidate_rule_id(...)` 對這組證據固定回 `R-ad0afde8`；`propose_candidate(...)` 呼叫模型一次，寫出一筆 `RULE#R-ad0afde8` item：

```json
{
  "rule_id": "R-ad0afde8",
  "rule": "click_ui 步驟要指出頁面與控制項位置",
  "applies_when": "click_ui",
  "evidence": ["f_12", "f_15", "f_19", "f_23", "f_27", "f_31", "f_34", "f_40"],
  "status": "candidate",
  "applied_to": [],
  "derived_from": "prepare-meeting@v1"
}
```

設計 §11.2、§11.4 的 `R-007` 是同一組證據在 Demo 種子裡的**既有 ID**，由 [Phase 56](56-Phase56-O7核定Demo種子資料.md) 直接指定，不經本階段的 `candidate_rule_id`。若證據是 v1 三筆加 v2 兩筆，總數雖然是五，仍**不得**提案，也不呼叫模型。

## 3. 名詞小抄

| 名詞 | 白話意思 |
|---|---|
| candidate（候選規則） | 已有重複回饋證據、但尚未證明有效的寫作規則；三態之一（candidate／active／retired）。 |
| `CandidateGroup` | 「同一版本、同一類別、這幾個 Feedback ID」這個已驗證的證據組，是呼叫模型的前提。 |
| `RuleProposal` | Phase 17 的 JSON schema 名稱，規定模型輸出長什麼樣；它是一個 schema dict，不是 pydantic 類別。 |
| `derived_from` ／ `evidence` | 前者是規則證據所屬的**唯一** TutorialVersion ID（例如 `prepare-meeting@v1`）；後者是可回查的 Feedback ID 清單，只存 ID，不複製留言、評分或類別。 |
| `applies_when` | 這條規則適用哪一種步驟；MVP 只表達單一 `step.type` 等值（`click_ui`／`input`／`read`）。 |
| 核定類別表 | Phase 43 維護的合法 Feedback 類別清單；`待分類` 不在裡面，所以不會湊成證據。 |
| 獨立門檻 | 能提規則不代表這一版是弱教學，也不代表要 REFINE；兩條分支各自判斷。 |

## 4. 預計檔案

| 動作 | 路徑 | 責任 |
|---|---|---|
| 修改 | `src/training_kb/pipelines/feedback.py` | `CandidateGroup`、`candidate_groups`、`candidate_rule_id`、`propose_candidate`（檔案 owner 是 Phase 44）。 |
| 修改 | `src/training_kb/writing/prompts.py` | 追加 `prompt_propose_rule`（檔案 owner 是 Phase 17，命名沿用 `prompt_<node>`）。 |
| 修改 | `src/training_kb/writing/schemas.py` | 只在 `RuleProposal` 缺欄位時補齊，不改 `$id` 與既有 required（檔案 owner 是 Phase 17）。 |
| 測試 | `tests/unit/test_rule_proposal.py` | 門檻、溯源、適用範圍、狀態與重送。 |

## 5. 固定介面

### Consumes

```text
ContentError / PermanentError                                                     # Phase 02
StepType（StrEnum：CLICK_UI="click_ui"、INPUT="input"、READ="read"）                # Phase 03
RuleStatus（StrEnum：CANDIDATE="candidate"、ACTIVE、RETIRED）                       # Phase 03
Feedback(id, tutorial_version, rating, category, comment, user, ts)               # Phase 04
AuthoringRule(rule_id, rule, applies_when: StepType, evidence: list[str],
              status, applied_to: list[str], derived_from)                         # Phase 04
rule_pk(rule_id: str) -> str                                                      # Phase 05
Repository.get_meta(pk: str, model: type[T], *, consistent: bool = True) -> T | None   # Phase 06
Repository.put_meta(entity: Entity, *, create_only: bool = True) -> None          # Phase 06
Repository.list_feedback_of_version(version_id: str) -> list[Feedback]            # Phase 08
Writer.generate_json(system: str, user: str, schema: Mapping[str, Any], *,
                     operation_id: str, node: str) -> dict[str, Any]              # Phase 15
RuleProposal: dict[str, object]   # Phase 17；required = rule / applies_when /
              evidence / derived_from，applies_when 是字串 enum，無額外欄位
approved_categories(repository: Repository) -> frozenset[str] / PENDING_CATEGORY   # Phase 43
```

`generate_json` **吃 schema dict、回 dict**（00A 第 8 節 D-02）；schema 本身的形狀檢查由 Phase 15／17 在回傳前完成，本階段只做業務驗證並自行組 `AuthoringRule`，不做 `RuleProposal.model_validate(...)` 這種不存在的呼叫。`propose_candidate` 是**判斷節點**，沿用 00A 第 3.7 節的 `max_tokens` 512、`temperature` 0.1（參數本身由 Phase 15／18 設定與驗收，本階段不重設）。

### Produces

```python
MIN_CANDIDATE_FEEDBACK: int = 5
PROPOSE_NODE: str = "propose_rule"

@dataclass(frozen=True)
class CandidateGroup:
    version_id: str
    category: str
    feedback_ids: tuple[str, ...]

def candidate_groups(feedback: Iterable[Feedback], approved: frozenset[str]) -> tuple[CandidateGroup, ...]: ...
def candidate_rule_id(group: CandidateGroup) -> str: ...
def prompt_propose_rule(version_id: str, category: str, feedback_ids: Sequence[str], comments: Sequence[str]) -> tuple[str, str]: ...
def propose_candidate(group: CandidateGroup, *, writer: Writer, repo: Repository, operation_id: str, rule_id: str) -> AuthoringRule: ...
```

- `candidate_groups` 依 `(version_id, category)` 升序輸出；每組 ID 去重後升序，少於五筆不輸出。
- `propose_candidate` 的 keyword 是 `repo=`（不是 `repository=`），與 Phase 45、46 一致，Phase 48 已照這個名稱呼叫，不得順手統一（00A 第 6.9 節）。
- `rule_id` 由呼叫端傳入，正式路徑一律用 `candidate_rule_id(group)` 產生：`R-` 加上「`version_id`、`category`、排序後 ID 清單」三元組的 UTF-8 JSON 編碼 SHA-256 前 8 個十六進位字元（例如 `R-ad0afde8`）。同一組證據永遠得到同一個 `rule_id`，重送會落在同一筆 `RULE#<rule_id>`。
- `AuthoringRule` 在**模型層**也要求 `evidence` 至少五個不同 Feedback ID（Phase 04 的 validator，本計畫選擇），本階段所有 fixture 與種子都必須給滿五個；`propose_candidate` 的前置檢查只是為了先丟出可讀的 `ContentError`，不是唯一防線。
- `prompt_propose_rule` 放 `writing/prompts.py`，只吃字串與字串序列，**不 import `pipelines`**，避免反向相依。

## 6. 業務驗證順序

```text
candidate_groups（純函式，完全不呼叫模型）
  依 (tutorial_version, category) 分桶
        |
  category 在核定類別表內？ ------- 否 --> 丟棄（待分類與未核定都不計）
        |
  同桶不同 Feedback ID >= 5？ ----- 否 --> 不輸出這一組、不呼叫模型
        v
propose_candidate（每組最多呼叫模型一次）
        |
  group 的不同 ID 仍 >= 5？ ------- 否 --> ContentError
        |
  RULE#<rule_id> 已存在？ --------- 是 --> 回既有規則，不呼叫模型、不覆寫
        |
  generate_json -> RuleProposal schema 通過（Phase 15／17 內完成）
        |
  rule 去頭尾非空？ / applies_when 屬 click_ui|input|read？ -- 否 --> ContentError
        v
  AuthoringRule(rule_id=程式給, rule=模型給, applies_when=StepType(字串),
                evidence=group 的 ID, status=candidate,
                applied_to=[], derived_from=group 的版本)
        v
  Repository.put_meta(candidate)   # create_only=True，撞鍵表示同組已提案過
```

模型不能決定 `rule_id`、`evidence`、`derived_from` 或 `status`；這四個一律由程式依已驗證的 group 設定。`RuleProposal` schema 仍把 `evidence` 與 `derived_from` 列為 required，是要讓模型把 prompt 給的值原樣填回、方便在 trace 中比對，**程式讀完後直接丟棄模型的版本**。同一組證據排序後得到同一個 `rule_id`（設計 §7.5「同一次證據集合排序後比對，避免重複提出相同內容的 candidate」）；這不是把新回饋從平均分母排除——多一筆新的同類 Feedback，`feedback_ids` 與 `rule_id` 就都不同，可以提出新的 candidate。

## 7. TDD Tasks

### Task 1：同版同類分組與五筆邊界

- [ ] **Step 1：建立失敗測試**

```python
# tests/unit/test_rule_proposal.py
from training_kb.models import Feedback
from training_kb.pipelines.feedback import CandidateGroup, candidate_groups

APPROVED = frozenset({"找不到按鈕", "缺少資訊"})

def fb(fid: str, version_id: str, category: str | None, rating: int = 2) -> Feedback:
    return Feedback(id=fid, tutorial_version=version_id, rating=rating, category=category,
                    comment="第三步沒有指出按鈕在哪一頁與位置", user=f"u_{fid}", ts=None)

def test_four_is_not_enough_but_five_is():
    feedback = [fb(f"f_{n}", "prepare-meeting@v1", "找不到按鈕") for n in range(1, 5)]
    assert candidate_groups(feedback, APPROVED) == ()
    feedback.append(fb("f_5", "prepare-meeting@v1", "找不到按鈕"))
    assert candidate_groups(feedback, APPROVED) == (
        CandidateGroup("prepare-meeting@v1", "找不到按鈕",
                       ("f_1", "f_2", "f_3", "f_4", "f_5")),
    )

def test_three_plus_two_across_versions_is_not_a_group():
    feedback = [fb(f"f_{n}", "prepare-meeting@v1", "找不到按鈕") for n in range(1, 4)]
    feedback += [fb(f"f_{n}", "prepare-meeting@v2", "找不到按鈕") for n in range(4, 6)]
    assert candidate_groups(feedback, APPROVED) == ()

def test_duplicate_ids_and_unapproved_categories_do_not_count():
    same = [fb("f_1", "prepare-meeting@v1", "找不到按鈕")] * 5
    assert candidate_groups(same, APPROVED) == ()
    mixed = [fb(f"f_{n}", "prepare-meeting@v1", "待分類") for n in range(1, 5)]
    mixed += [fb("f_9", "prepare-meeting@v1", None)]
    assert candidate_groups(mixed, APPROVED) == ()
```

- [ ] **Step 2：執行並確認紅燈**

```bash
uv run pytest tests/unit/test_rule_proposal.py -q
```

預期：FAIL，訊號包含 `cannot import name 'candidate_groups' from 'training_kb.pipelines.feedback'`。

- [ ] **Step 3：建立最小實作**

```python
# src/training_kb/pipelines/feedback.py（檔案由 Phase 44 建立，本階段追加）
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass

from training_kb.models import Feedback

MIN_CANDIDATE_FEEDBACK = 5

@dataclass(frozen=True)
class CandidateGroup:
    version_id: str
    category: str
    feedback_ids: tuple[str, ...]

def candidate_groups(feedback: Iterable[Feedback],
                     approved: frozenset[str]) -> tuple[CandidateGroup, ...]:
    buckets: dict[tuple[str, str], set[str]] = defaultdict(set)
    for item in feedback:
        if item.category in approved:
            buckets[(item.tutorial_version, item.category)].add(item.id)
    return tuple(
        CandidateGroup(version_id, category, tuple(sorted(ids)))
        for (version_id, category), ids in sorted(buckets.items())
        if len(ids) >= MIN_CANDIDATE_FEEDBACK
    )
```

`item.category` 可能是 `None` 或 `待分類`；兩者都不在核定類別表裡，所以 `in approved` 直接排除，不需要額外分支。

- [ ] **Step 4：跑完整檔案確認綠燈**

```bash
uv run pytest tests/unit/test_rule_proposal.py -q
```

預期：三個測試全部 `passed`；4／5 邊界、跨版 3+2、重複 ID 與未核定類別都不會湊足門檻。

- [ ] **Step 5：提交**

```bash
git add src/training_kb/pipelines/feedback.py tests/unit/test_rule_proposal.py
git commit -m "feat(rules): 建立同版同類候選群組"
```

### Task 2：鎖定 `applies_when` 與溯源欄位

- [ ] **Step 1：建立失敗測試**

```python
# 續寫 tests/unit/test_rule_proposal.py
from dataclasses import dataclass, field

import pytest

from training_kb.errors import ContentError
from training_kb.models import AuthoringRule, RuleStatus, StepType
from training_kb.pipelines.feedback import propose_candidate

GROUP = CandidateGroup("prepare-meeting@v1", "找不到按鈕",
                       ("f_1", "f_2", "f_3", "f_4", "f_5"))
OP = "op-feedback-review-demo-2026-09-13"          # 形狀見 00A D-61

@dataclass
class FakeWriter:
    payload: dict
    calls: list[str] = field(default_factory=list)

    def generate_json(self, system, user, schema, *, operation_id, node):
        self.calls.append(node)
        return dict(self.payload)

@dataclass
class FakeRepository:
    saved: list[AuthoringRule] = field(default_factory=list)

    def get_meta(self, pk, model, *, consistent=True):
        return next((r for r in self.saved if f"RULE#{r.rule_id}" == pk), None)

    def put_meta(self, entity, *, create_only=True):
        self.saved.append(entity)

    def list_feedback_of_version(self, version_id):
        return []

def test_program_fills_evidence_and_status_and_ignores_model_versions():
    writer = FakeWriter({"rule": "指出控制項位置", "applies_when": "click_ui",
                         "evidence": ["f_99"], "derived_from": "other@v9"})
    repository = FakeRepository()
    rule = propose_candidate(GROUP, writer=writer, repo=repository,
                             operation_id=OP, rule_id="R-007")
    assert rule.evidence == ["f_1", "f_2", "f_3", "f_4", "f_5"]
    assert rule.derived_from == "prepare-meeting@v1"
    assert rule.applies_when is StepType.CLICK_UI
    assert rule.status is RuleStatus.CANDIDATE and rule.applied_to == []
    assert repository.saved == [rule] and writer.calls == ["propose_rule"]

@pytest.mark.parametrize("field, value", [
    ("applies_when", ""), ("applies_when", "video"), ("applies_when", "click_ui, read"),
    ("applies_when", ["click_ui"]), ("applies_when", {"step.type": "click_ui"}),
    ("applies_when", None), ("applies_when", True),
    ("rule", ""), ("rule", "   "), ("rule", None), ("rule", 3),
])
def test_proposal_rejects_illegal_model_fields(field, value):
    repository = FakeRepository()
    payload = {"rule": "指出控制項位置", "applies_when": "click_ui",
               "evidence": list(GROUP.feedback_ids), "derived_from": GROUP.version_id}
    payload[field] = value
    writer = FakeWriter(payload)
    with pytest.raises(ContentError):
        propose_candidate(GROUP, writer=writer, repo=repository,
                          operation_id=OP, rule_id="R-007")
    assert repository.saved == [] and writer.calls == ["propose_rule"]
```

- [ ] **Step 2：執行並確認紅燈**

```bash
uv run pytest tests/unit/test_rule_proposal.py -q
```

預期：FAIL，訊號包含 `cannot import name 'propose_candidate'`。

- [ ] **Step 3：建立最小實作**

```python
# src/training_kb/pipelines/feedback.py（續）
from training_kb.errors import ContentError
from training_kb.keys import rule_pk
from training_kb.models import AuthoringRule, RuleStatus, StepType
from training_kb.repository import Repository
from training_kb.writing.client import Writer
from training_kb.writing.prompts import prompt_propose_rule
from training_kb.writing.schemas import RuleProposal

PROPOSE_NODE = "propose_rule"

def _require_rule_text(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContentError(f"RuleProposal.rule 必須是非空字串：{value!r}")
    return value.strip()

def _require_step_type(value: object) -> StepType:
    if not isinstance(value, str) or isinstance(value, bool):
        raise ContentError(f"applies_when 必須是單一 step.type 字串：{value!r}")
    try:
        return StepType(value)
    except ValueError as error:
        raise ContentError(f"applies_when 不是合法 step.type：{value!r}") from error

def _evidence_comments(group: CandidateGroup, *, repo: Repository) -> tuple[str, ...]:
    wanted = set(group.feedback_ids)
    return tuple(item.comment for item in repo.list_feedback_of_version(group.version_id)
                 if item.id in wanted and item.comment)

def propose_candidate(group: CandidateGroup, *, writer: Writer, repo: Repository,
                      operation_id: str, rule_id: str) -> AuthoringRule:
    if len(set(group.feedback_ids)) < MIN_CANDIDATE_FEEDBACK:
        raise ContentError(f"candidate 需要至少 {MIN_CANDIDATE_FEEDBACK} 個不同 Feedback ID")
    existing = repo.get_meta(rule_pk(rule_id), AuthoringRule)
    if existing is not None:
        return existing
    system, user = prompt_propose_rule(group.version_id, group.category,
                                       group.feedback_ids, _evidence_comments(group, repo=repo))
    payload = writer.generate_json(system, user, RuleProposal,
                                   operation_id=operation_id, node=PROPOSE_NODE)
    candidate = AuthoringRule(
        rule_id=rule_id, rule=_require_rule_text(payload.get("rule")),
        applies_when=_require_step_type(payload.get("applies_when")),
        evidence=list(group.feedback_ids), status=RuleStatus.CANDIDATE,
        applied_to=[], derived_from=group.version_id,
    )
    repo.put_meta(candidate)
    return candidate
```

`isinstance(value, bool)` 要單獨擋掉：Python 的 `bool` 是 `int` 的子類，這一行直接說明「`True` 不是合法值」，日後放寬型別也不會破功。`prompt_propose_rule` 沿用 [Phase 17](17-Phase17-Claude結構化輸出與Prompt.md) 的分區寫法：`<derived_from>`、`<category>`、`<evidence_ids>` 由程式產生，回饋留言是不可信文字，一律先經 Phase 17 的 `_as_data`（`html.escape`）轉義再包進 `<source_data>`，當資料不當指令（D-67）；不得自創新的分區名稱。

- [ ] **Step 4：跑完整檔案確認綠燈**

```bash
uv run pytest tests/unit/test_rule_proposal.py -q
```

預期：合法案例寫出一筆 `status=candidate` 的 `AuthoringRule`，模型回傳的 `evidence`／`derived_from` 被忽略；十一個非法欄位參數案例（七個 `applies_when`、四個 `rule`）全部 `ContentError` 且 `repository.saved == []`。

- [ ] **Step 5：提交**

```bash
git add src/training_kb/pipelines/feedback.py src/training_kb/writing/prompts.py tests/unit/test_rule_proposal.py
git commit -m "feat(rules): 提出可追溯的 candidate 規則"
```

### Task 3：決定性 `rule_id` 與兩條分支互不依賴

- [ ] **Step 1：建立失敗測試**

```python
# 續寫 tests/unit/test_rule_proposal.py
from training_kb.pipelines.feedback import candidate_rule_id

def test_rule_id_is_deterministic_and_resend_does_not_repropose():
    twin = CandidateGroup("prepare-meeting@v1", "找不到按鈕",
                          ("f_1", "f_2", "f_3", "f_4", "f_5"))
    assert candidate_rule_id(GROUP) == candidate_rule_id(twin) == "R-f6c7a0d2"
    other = CandidateGroup("prepare-meeting@v2", "找不到按鈕", GROUP.feedback_ids)
    assert candidate_rule_id(other) != candidate_rule_id(GROUP)

    writer = FakeWriter({"rule": "指出控制項位置", "applies_when": "click_ui",
                         "evidence": list(GROUP.feedback_ids),
                         "derived_from": GROUP.version_id})
    repository = FakeRepository()
    rule_id = candidate_rule_id(GROUP)
    first = propose_candidate(GROUP, writer=writer, repo=repository,
                              operation_id=OP, rule_id=rule_id)
    second = propose_candidate(GROUP, writer=writer, repo=repository,
                               operation_id=OP, rule_id=rule_id)
    assert first == second
    assert len(repository.saved) == 1 and writer.calls == ["propose_rule"]

def test_rating_does_not_change_the_candidate_threshold():
    happy = [fb(f"f_{n}", "share-summary@v1", "缺少資訊", rating=5) for n in range(1, 6)]
    assert len(candidate_groups(happy, APPROVED)) == 1

    writer = FakeWriter({"rule": "x", "applies_when": "read",
                         "evidence": [], "derived_from": ""})
    too_few = [fb(f"f_{n}", "share-summary@v1", "缺少資訊", rating=1) for n in range(1, 5)]
    for group in candidate_groups(too_few, APPROVED):
        propose_candidate(group, writer=writer, repo=FakeRepository(),
                          operation_id=OP, rule_id=candidate_rule_id(group))
    assert candidate_groups(too_few, APPROVED) == () and writer.calls == []
```

- [ ] **Step 2：執行並確認紅燈**

```bash
uv run pytest tests/unit/test_rule_proposal.py -q
```

預期：FAIL，訊號包含 `cannot import name 'candidate_rule_id'`。

- [ ] **Step 3：建立最小實作**

```python
# src/training_kb/pipelines/feedback.py（續）
import hashlib
import json

def candidate_rule_id(group: CandidateGroup) -> str:
    payload = json.dumps([group.version_id, group.category, list(group.feedback_ids)],
                         ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return f"R-{hashlib.sha256(payload).hexdigest()[:8]}"
```

`propose_candidate` 在 Task 2 已經有「`RULE#<rule_id>` 已存在就回既有規則」的分支，所以這個 Task 只補決定性 ID；兩者合起來就是「同一組證據重送不會多出第二條規則、也不會多打一次模型」。`"R-f6c7a0d2"` 是上面五個 ID 那組的實際輸出；換掉 `separators` 或排序方式都會改變它，測試會立刻紅燈。

- [ ] **Step 4：跑完整檔案確認綠燈**

```bash
uv run pytest tests/unit/test_rule_proposal.py -q
```

預期：全部 `passed`；`writer.calls` 長度為 1 證明第二次沒有呼叫模型，`rating=5` 與 `rating=1` 兩個案例證明提案門檻與評分完全無關。

- [ ] **Step 5：提交**

```bash
git add src/training_kb/pipelines/feedback.py tests/unit/test_rule_proposal.py
git commit -m "feat(rules): 以決定性規則 ID 避免重複提案"
```

## 8. 驗收矩陣

| 路徑 | 輸入 | 預期資料結果 |
|---|---|---|
| Happy | v1 同類 5 個不同 ID | 一條 candidate；`evidence` 五個 ID、`derived_from="prepare-meeting@v1"`、模型呼叫 1 次。 |
| Boundary | v1 同類 4 筆 | 無 group、無 candidate、模型呼叫 0 次。 |
| Boundary | v1 3 筆 + v2 2 筆 | 無 group；不得跨版湊足門檻。 |
| Boundary | 同一個 ID 重複 5 次 | 無 group；去重後只有 1 個 ID。 |
| Boundary | 類別是 `待分類` 或 `None` | 不進任何桶；核定類別表外的值不算證據。 |
| Independent | 五筆 `rating=5` 的同類回饋 | 仍可提 candidate；`propose_candidate` 不呼叫 `is_weak`，也不讀 `rating`。 |
| Failure | `applies_when` 是 `""`／`"video"`／list／dict／`None`／`True` | `ContentError`，`RULE` item 零筆。 |
| Failure | `rule` 是 `""`／空白／`None`／數字 | `ContentError`，`RULE` item 零筆。 |
| Idempotency | 同一組證據呼叫兩次 | 回同一條規則；`RULE` item 仍是一筆，模型呼叫仍是 1 次。 |
| Security | 模型自帶另一組 `evidence`／`derived_from` | 忽略模型欄位，寫入的是 group 的值與 `status="candidate"`。 |

人工驗收（不能只看 PASS）：打開寫出的 `RULE#<rule_id>` item，逐一拿 `evidence` 裡的每個 Feedback ID 回查 `FEEDBACK#<id>`，確認每一筆的 `tutorial_version` 與 `category` 都和 `derived_from`、group 的類別完全相同；確認 item 上**沒有**模型輸出的原文留言。只看總筆數不算完成。

## 9. 常見錯誤與停止條件

| 症狀 | 原因 | 修正／停止 |
|---|---|---|
| 3+2 跨版被提案 | 先按類別全域分組 | 分桶 key 必須含 `tutorial_version`；跨版是設計 F25 明確禁止的。 |
| `applies_when` 存成 `{"step.type": "click_ui"}` | 沿用舊草稿的 dict 表示法 | 依 00A D-10 存 `StepType`；模型輸出是字串，程式轉型後才寫入。 |
| candidate 直接進一般寫作 prompt | 混淆「提出」與「驗證」 | 停止寫作路徑；Phase 19 只選 active，只有 Phase 55 能改 status。 |
| 每次執行都產生新的規則 ID | `rule_id` 用隨機值或時間戳 | 用 `candidate_rule_id(group)`；同一組證據必須得到同一個 ID。 |
| `evidence` 存完整留言，或模型回傳 `status="active"` 就照寫 | 相信模型輸出的控制欄位 | `status`／`evidence`／`derived_from`／`applied_to` 一律由程式填（設計 D15 只存 ID）；模型只給 `rule` 與 `applies_when`。 |
| 宣稱 candidate 已證明有效 | 把提出當成驗證 | O7 未完成、Phase 55 未判定前保持 `candidate`，文件與報告寫「已提出、待驗證」。 |

## 10. 來源與 Rule 對照

- [提出教學規則.feature](../../spec/features/提出教學規則.feature)（縮寫 `PRP`）
  - Rule 1：「同類 Feedback 至少 5 筆才可提出 candidate 規則」（primary）→ Task 1 的 4／5 邊界測試。設計 F25（僅同一 TutorialVersion）、D18（`derived_from` 恰一版）與「不同 ID」都是**比 Rule 原文更嚴**的加嚴條件，對應 Task 1 的跨版與重複 ID 案例。
  - Rule 2：「Authoring Rule 保留可追溯的 Feedback 證據」（primary）→ Task 2 斷言 `evidence` 只有 group 的 ID，人工驗收逐筆回查。
  - Rule 3：「Authoring Rule 記錄 applies_when 適用範圍」（primary）→ `test_proposal_rejects_illegal_model_fields` 的七個 `applies_when` 案例與 `StepType.CLICK_UI` 斷言。
  - Rule 4：「Authoring Rule 記錄 derived_from 來源版本」（primary）→ Task 2 斷言 `derived_from` 恰好是 group 的版本。
  - Rule 5：「Authoring Rule 記錄歸納出的寫作要求」（primary）→ `test_proposal_rejects_illegal_model_fields` 的四個 `rule` 案例與合法路徑的非空 `rule` 斷言。
- [定期檢視回饋.feature](../../spec/features/定期檢視回饋.feature)（縮寫 `REV`）
  - Rule 9：「Feedback Review 是唯一提出 Authoring Rule 的 pipeline」（primary）→ `propose_candidate` 只存在於 `pipelines/feedback.py`；`pipelines/ticket.py`、`pipelines/release.py` 與 `analytics/` 都不 import 它。
  - Rule 4：「弱教學必須具有 recurring Feedback Category」→ 相關（primary 在 [Phase 44](44-Phase44-弱教學門檻與目標選取.md)）；本階段共用「同類 >= 5」這個數字，但判斷分開跑。
- [套用教學規則.feature](../../spec/features/套用教學規則.feature)（縮寫 `APL`）Rule 2「一般寫作路徑只取得 status 為 active 的規則」、Rule 3「依 step 型態與 applies_when 篩選規則」→ 相關（primary 在 [Phase 19](19-Phase19-Active規則選取與注入.md)）；本階段只保證寫出的 `status` 是 `candidate`、`applies_when` 是單一 `StepType`。
- [收集教學回饋.feature](../../spec/features/收集教學回饋.feature)（縮寫 `COL`）Rule 5「Feedback Category 必須屬於核定類別表或待分類」→ 相關（primary 在 [Phase 43](43-Phase43-Feedback類別判定.md)）；本階段只消費核定類別表，`待分類` 不計入證據。
- [驗證教學規則.feature](../../spec/features/驗證教學規則.feature)（縮寫 `VAL`）Rule 4「與既有規則衝突的 candidate 規則變為 retired」→ 相關（primary 在 [Phase 55](55-Phase55-規則驗證與狀態轉移.md)）；本階段不做衝突判定，也不改 status。
- 設計 §7.5「提出規則」列與 §7.6 內部介面表：同版同類至少五筆、`evidence` 只存 ID、`derived_from` 恰一版、只允許 `step.type` 單一等值條件。
- 設計決策：F25（證據僅同一 TutorialVersion）、F26（不必先達弱教學門檻）、F27（一般寫作不自動試用 candidate）、D15（`evidence` 只存 ID 清單）、D16（`applies_when` 只支援 `step.type` 等於 `click_ui`／`input`／`read`）、D18（`derived_from` 恰好一個）。
- [00A 共用契約與名詞](00A-共用契約與名詞.md) 第 5.1 節（`AuthoringRule` 欄位）、第 6.5 節（`RuleProposal` required 欄位）、第 6.9 節（本 Phase 的 owner 名稱）、第 8 節 D-02 與 D-10。

## 11. 完成清單

- [ ] 同版、同類、不同 ID、至少五筆四個條件各有直接測試。
- [ ] 跨版 3+2、重複 ID、`待分類` 與 `None` 類別都不會湊足門檻。
- [ ] `evidence` 只存 Feedback ID，`derived_from` 恰好一個版本。
- [ ] `AuthoringRule.applies_when` 是 `StepType`，模型輸出的字串驗證後才轉型。
- [ ] `status` 固定 `candidate`、`applied_to` 初始為空，而且不是由模型決定。
- [ ] `rule_id` 由 `candidate_rule_id(group)` 決定性產生，重送不重複提案也不重複呼叫模型。
- [ ] candidate 分支不讀 `rating`、不呼叫 `is_weak`，與弱教學門檻完全分開。
- [ ] `PRP` Rule 1–5 與 `REV` Rule 9 有直接 assertion；其餘相關 Rule 已標明 primary 在哪一份。
- [ ] 文件與報告沒有把 candidate 寫成已驗證、已生效或可供一般寫作使用。
