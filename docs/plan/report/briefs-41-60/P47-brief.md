# P47 brief — Candidate 規則提出與溯源

## 1. 單一交付物與停止點
- **交付物**：`pipelines/feedback.py` 的 `CandidateGroup`／`MIN_CANDIDATE_FEEDBACK`／`PROPOSE_NODE`／`candidate_groups`／`candidate_rule_id`／`propose_candidate`，加上 `writing/prompts.py` 的 `prompt_propose_rule`——同版同類 ≥5 筆不同 Feedback ID 時提出一條可逐筆回查的 candidate 規則。
- **停止點**：`put_meta(candidate)` 寫出一筆 `RULE#<rule_id>`（`status=candidate`、`applied_to=[]`）並回傳它。**不排程、不組 pipeline、不改 `RULE.status`（只有 P55）、不把 candidate 放進寫作 prompt、不算指標。**

## 2. 已存在、直接重用
- `writing/schemas.py:66` `RuleProposal` — **已完整**：`required=["rule","applies_when","evidence","derived_from"]`、`applies_when` enum `["click_ui","input","read"]`、`evidence` `minItems:5`、`additionalProperties:False`。**預期不需要改 `schemas.py`。**
- `models.py:397` `AuthoringRule(rule_id, rule, applies_when: StepType, evidence: list[str], status: RuleStatus, applied_to: list[str], derived_from)` — 含 D-66 的 `evidence_has_five_distinct_ids`（<5 個不同 ID 直接 `ValidationError`）與 `rule_is_filled`。
- `models.py:43` `RuleStatus`、`StepType`（同檔）、`:347` `Feedback`（D-66 `carries_signal`、`rating_is_strict_int`）。
- `keys.py:79` `rule_pk(rule_id) -> "RULE#<rule_id>"`。
- `repository.py:357` `get_meta(pk, model, *, consistent=True) -> T | None`；`:240` `put_meta(entity, *, create_only=True)`（撞鍵丟 `CoordinationError`）；`:579` `list_feedback_of_version`。
- `writing/client.py:51` `Writer.generate_json(...) -> dict[str, Any]`（D-02）；`tests/unit/conftest.py:13` `RecordingWriter`。
- `writing/prompts.py:29` `_as_data` ＋ `<source_data>` 分區（D-67）。
- `errors.py:12` `ContentError`。
- `src/training_kb/pipelines/feedback.py` — controller 預建空殼，只 Edit。

## 3. 要新增／修改的東西
**波次 W1（P44 ∥ P45 ∥ P47）；兩支共用檔。**

`src/training_kb/pipelines/feedback.py`（區段 `# ---- Phase 47 ----`）
- **擁有**：`MIN_CANDIDATE_FEEDBACK = 5`、`PROPOSE_NODE = "propose_rule"`、`CandidateGroup`、`candidate_groups`、`candidate_rule_id`、`propose_candidate`、`_require_rule_text`、`_require_step_type`、`_evidence_comments`。
- **不得碰**：P44 的 `ReviewMode`／`WeakTarget`／`is_weak`／`select_weak_targets`／`_average`／`_top_category`；P45 的 `DiagnosisResult`／`DIAGNOSE_NODE`／`diagnose_weak`／`_validated_items`；P46／P48 的所有名稱。

`src/training_kb/writing/prompts.py`（區段 `# ---- Phase 47 ----`）
- **擁有**：`prompt_propose_rule`。**不得碰**：`_as_data`、`prompt_write_tutorial`、`prompt_name_gap`、同波次 P45 的 `prompt_diagnose_weak`。
- `prompt_propose_rule` **只吃字串與字串序列，不 import `pipelines`**（避免反向相依）。

`src/training_kb/writing/schemas.py` — **預期不改**；實地確認 `RuleProposal` 無缺欄位就不要 `git add` 它。

00A §6.9 canonical 簽名（`repo=`，不是 `repository=`）：
```python
MIN_CANDIDATE_FEEDBACK = 5
PROPOSE_NODE = "propose_rule"
@dataclass(frozen=True)
class CandidateGroup:
    version_id: str; category: str; feedback_ids: tuple[str, ...]
def candidate_groups(feedback: Iterable["Feedback"], approved: frozenset[str]) -> tuple[CandidateGroup, ...]: ...
def candidate_rule_id(group: CandidateGroup) -> str: ...
def prompt_propose_rule(version_id: str, category: str, feedback_ids: Sequence[str],
                        comments: Sequence[str]) -> tuple[str, str]: ...
def propose_candidate(group: CandidateGroup, *, writer: "Writer", repo: "Repository",
                      operation_id: str, rule_id: str) -> "AuthoringRule": ...
```
新檔：`tests/unit/test_rule_proposal.py`（平放）。

## 4. Task 順序與紅燈訊號
1. **Task 1（同版同類分組與 4／5 邊界）** — `uv run pytest tests/unit/test_rule_proposal.py -q` → `cannot import name 'candidate_groups' from 'training_kb.pipelines.feedback'`。
2. **Task 2（`applies_when`／溯源欄位）** — 同指令 → `cannot import name 'propose_candidate'`。綠燈時 11 個非法欄位案例（7 個 `applies_when` ＋ 4 個 `rule`）全 `ContentError` 且 `repository.saved == []`。
3. **Task 3（決定性 `rule_id` 與兩分支互不依賴）** — 同指令 → `cannot import name 'candidate_rule_id'`。
收尾：`uv run ruff check src tests infra`、`ruff format --check`（共用檔不通過只修自己那段）、`uv run mypy`、`uv run pytest tests -q -W error`。

## 5. 00B primary Rule 與測試檔
全部落在 `tests/unit/test_rule_proposal.py`：
| Rule | 內容 |
|---|---|
| `PRP` 1（primary） | 同類 ≥5 筆才可提 candidate（Task 1 的 4／5、跨版 3+2、重複 ID） |
| `PRP` 2（primary） | 保留可追溯的 Feedback 證據（`evidence` 只有 group 的 ID） |
| `PRP` 3（primary） | 記錄 `applies_when` 適用範圍（7 個非法案例 ＋ `StepType.CLICK_UI`） |
| `PRP` 4（primary） | 記錄 `derived_from` 來源版本（恰一版） |
| `PRP` 5（primary） | 記錄歸納出的寫作要求（4 個 `rule` 非法案例 ＋ 非空斷言） |
| `REV` 9（primary） | Feedback Review 是唯一提出 Authoring Rule 的 pipeline（`pipelines/ticket.py`、`pipelines/release.py`、`analytics/` 都不 import `propose_candidate`） |
相關：`REV` 4（P44）、`APL` 2／3（P19）、`COL` 5（P43）、`VAL` 4（P55）。

## 6. 風險與陷阱
- **`candidate_rule_id` 的三個期望值已實測**（2026-09-14）：`(prepare-meeting@v1, 找不到按鈕, f_1..f_5)` → `R-f6c7a0d2`；`(prepare-meeting@v2, 同上)` → `R-7e16d4f3`；八筆證據那組 → `R-ad0afde8`（與 00A §6.9 範例一致）。實作必須是 `json.dumps([version_id, category, list(ids)], ensure_ascii=False, separators=(",",":")).encode("utf-8")` 再 SHA-256 取前 8 碼；改 `separators`／`ensure_ascii`／排序就全部變。
- **本 Phase 對 P43 沒有程式相依**：`approved` 是 `candidate_groups` 的參數，測試給字面 frozenset。`approved_categories(repository)`（P43 在 `ingress.py` 追加，目前不存在）是 **P48 呼叫端**的事——別 import 它。
- `AuthoringRule.evidence` 模型層要求 ≥5 個**不同** ID（D-66）。所有 fixture 給滿五個；`propose_candidate` 的前置檢查只是為了先丟好讀的 `ContentError`，不是唯一防線。
- `Feedback` 的 `carries_signal`：`category=None` 的 fixture 必須有非空 `comment`（文件的 `fb` helper 已滿足）。
- `bool` 是 `int` 子類 → `_require_step_type` 要單獨 `isinstance(value, bool)` 擋掉 `True`。
- 模型只給 `rule` 與 `applies_when`；`rule_id`／`evidence`／`derived_from`／`status`／`applied_to` **一律由程式填**，模型回的 `evidence`／`derived_from` 讀完就丟。
- `put_meta(create_only=True)` 撞鍵丟 `CoordinationError`——但流程上先 `get_meta` 命中就直接回既有規則，不會走到那裡。
- gate：**O5 BLOCKED**（假 Writer；真實 AWS 上 `propose_rule` 節點走 Catch → BLOCKED 證據）；**O7 未到** → candidate 只能寫「已提出、待驗證」，絕不寫「已驗證有效」或自動 active；**O2 PASS** 但本 Phase 的去重不靠它（靠決定性 `rule_id` ＋ 寫入前檢查）。

## 7. 需要裁決的點 → 建議裁決
- `schemas.py` 到底改不改 → **不改**（已確認 `RuleProposal` 齊全）；在報告 §6 寫一行「文件原列為修改，實查無需修改」。
- 本地 `FakeWriter`／`FakeRepository` vs conftest 的 `RecordingWriter` → **用文件裡的本地 dataclass 版本**（形狀與 `RecordingWriter` 相容即可，00A §6.5），但**別取名 `fake_writer`**（會覆蓋 `tests/unit/conftest.py` 的同名 fixture）。
- `REV` Rule 9 的「唯一 pipeline」怎麼斷言 → **靜態斷言**：讀 `pipelines/ticket.py`／`pipelines/release.py`／`analytics/*.py` 的原始碼確認不含 `propose_candidate`，比 monkeypatch 穩。

## 8. 對 AWS 的實際操作
無。本 Phase 沒有整合測試、沒有 `@pytest.mark.aws`、不連 Bedrock、不部署。
