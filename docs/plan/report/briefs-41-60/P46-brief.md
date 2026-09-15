# P46 brief — REFINE 精準改寫與證據去重

## 1. 單一交付物與停止點
- **交付物**：`pipelines/feedback.py` 的 `RefinePlan`／`REFINE_NODE`／`LEASE_TTL_SECONDS`／`evidence_fingerprint`／`refine_operation_id`／`refine_reason`／`evidence_of`／`prepare_refine`，加上 `writing/prompts.py` 的 `prompt_refine_steps`——用 P45 的診斷只改命中步驟，產出一個**未發布**的下一版。
- **停止點**：`create_version` ＋ `verify_version_complete` 通過後回 `RefinePlan`。**不發布、不切 `current_version`、不寫 `site/`、不提規則、不建 Tutorial 身分。**

## 2. 已存在、直接重用
- `content.py:194` `allocate_version(tutorial_id, operation_id, operations, *, repository, reason, rules_applied) -> VersionPlan` — **前三個是位置參數**；同 `operation_id` 重送走 `_replay_plan` 回同一版號（D26）。
- `content.py:290` `validate_content(content, known_feature_ids: frozenset[str]) -> None`；`:431` `parse_markdown(markdown) -> TutorialContent`；`:617` `create_version(plan, content, repository) -> TutorialVersion`（寫 `.md`／`.diff`／VERSION／STEP／三種邊，`published_at=None`）；`:691` `verify_version_complete(version_id, repository) -> bool`。
- `rules.py:55` `rules_for_content(rules, step_types, validated_at_by_rule) -> dict[StepType, list[AuthoringRule]]`（**回 dict**，D-03）；`:44` `render_rules_block`；`:50` `applied_rule_ids`；`:25` `select_active_rules` **每個 step_type 最多回一條**（`matching[:1]`，最近驗證優先、同時間取 `rule_id` 升序），缺 validated_at 直接 `PermanentError`。
- `analytics/status_writer.py:36` `load_validated_at(repository) -> dict[str, datetime]`（P40 已建，缺檔回 `{}`，D-28）。
- `operations.py`：`:290` `load(operation_id) -> OperationRecord | None`、`:319` `record_model_output(op, ref)`（同 ref 不重複附加）、`:376` `acquire_lease(scope, owner, *, ttl_seconds, now) -> bool`、`:416` `release_lease(scope, owner)`。`OperationRecord` 有 `version_id`、`model_output_refs`（tuple）、`updated_at`。
- `keys.py:182` `operation_ref(op, name) -> "operations/<op>/<name>.json"`；`ingress.py:243` `operation_id_for(kind, canonical)`，`OperationKind` 含 `"feedback"`。
- `writing/schemas.py:53` `StepRewrite`（schema dict）；`writing/prompts.py:29` `_as_data`。
- `repository.py:399` `put_object(key, body, content_type, *, if_none_match)` — **`if_none_match` 必填無預設**；`:422` `get_object`；`:375/:378` `get_tutorial`／`get_version`；`:622` `list_rules(status=None)`；`:539` `scan_entity`；`:152` `item_to_model`。
- `models.py:173` `TutorialVersion(version_id, slug, supersedes, reason, rules_applied, s3_key, published_at)`。
- P45 的 `DiagnosisResult`（同檔，不用 import）。

## 3. 要新增／修改的東西
**波次 W2（P45 落地後才開始）；兩支共用檔。**

`src/training_kb/pipelines/feedback.py`（區段 `# ---- Phase 46 ----`）
- **擁有**：`REFINE_NODE = "refine_steps"`、`LEASE_TTL_SECONDS = 120`（P51 import 同一個，不重宣告）、`RefinePlan`、`evidence_fingerprint`、`refine_operation_id`、`refine_reason`、`evidence_of`、`prepare_refine`、`_rules_for_hits`、`_assert_unchanged`、`_apply_rewrite`、`_known_feature_ids`、`_reuse_or_call`、`_guard`。
- **不得碰**：P44（`ReviewMode`／`WeakTarget`／`is_weak`／`select_weak_targets`／`_average`／`_top_category`）、P45（`DiagnosisResult`／`DIAGNOSE_NODE`／`diagnose_weak`／`_validated_items`）、P47（`CandidateGroup`／`candidate_*`／`propose_candidate`／`MIN_CANDIDATE_FEEDBACK`／`PROPOSE_NODE`）、P48（`FEEDBACK_REVIEW_*`／`task_*`／`run_feedback_review`／`review_operation_id`）。

`src/training_kb/writing/prompts.py`（區段 `# ---- Phase 46 ----`）
- **擁有**：`prompt_refine_steps`。**不得碰**：`_as_data`、`prompt_write_tutorial`、`prompt_name_gap`、`prompt_diagnose_weak`（P45）、`prompt_propose_rule`（P47）。

00A §6.9 canonical 簽名（`repo=`，不是 `repository=`）：
```python
@dataclass(frozen=True)
class RefinePlan:
    version_id: str; base_version_id: str; reason: str; content: "TutorialContent"
    changed_indexes: tuple[int, ...]   # 裝的是步驟 number（從 1 起），不是 0-based（D-55）
    rules_applied: tuple[str, ...]; evidence_fingerprint: str
def evidence_fingerprint(version_id: str, category: str, ids: Iterable[str]) -> str: ...
def refine_operation_id(version_id: str, category: str, ids: Iterable[str]) -> str: ...
def refine_reason(category: str, feedback_ids: Iterable[str]) -> str: ...
def evidence_of(diagnosis, *, repo) -> tuple[str, tuple[str, ...]]: ...
def prompt_refine_steps(base, diagnosis, category: str, rules_block: str) -> tuple[str, str]: ...
def prepare_refine(diagnosis, *, repo, writer, operations, operation_id) -> RefinePlan | None: ...
```
新檔：`tests/unit/test_feedback_refine.py`、`tests/integration/test_feedback_refine_retry.py`（後者標 `@pytest.mark.aws`）。

## 4. Task 順序與紅燈訊號
1. **Task 1（指紋／operation id／reason）** — `uv run pytest tests/unit/test_feedback_refine.py -q` → `cannot import name 'evidence_fingerprint'`。
2. **Task 2（只改命中步驟、只記注入規則）** — 同指令 → `cannot import name 'prepare_refine'`。綠燈後再補三案例：漏回命中步驟、改 `feature_id`、改寫文字 strip 後為空，都要 `ContentError` 且無版本被建立。
3. **Task 3（lease／同 operation 重送／同證據不再產版）**
   `uv run pytest tests/unit/test_feedback_refine.py -q` → `DID NOT RAISE TransientError` ＋ `AssertionError`（第二次仍產生 v3 並再打模型）。
   `TKB_RUN_AWS_INTEGRATION=1 uv run pytest tests/integration/test_feedback_refine_retry.py -m aws -q`（**O2 已 PASS，這支要真的跑，不再標 blocked**）。
收尾：`uv run ruff check src tests infra`、`ruff format --check`、`uv run mypy`、`uv run pytest tests -q -W error`。

## 5. 00B primary Rule 與測試檔
| Rule | 內容 | 測試 |
|---|---|---|
| `REV` 7（primary） | REFINE 只重寫命中步驟 | `test_feedback_refine.py::test_only_diagnosed_steps_change_and_others_are_byte_for_byte` |
| `REV` 8（primary） | reason 記錄回饋數與類別 | `test_reason_counts_unique_evidence` ＋ Task 2 的 `reason == "feedback:8 則 找不到按鈕"` |
相關（別搶 primary）：`VER` 2（P20）、`VER` 4（P23）、`APL` 1（P19）、`ING` 30（P10）。

## 6. 風險與陷阱
- **文件原寫「O2 尚未 PASS」是錯的**：O2 於 P11 PASS（`docs/plan/report/o2-20260914t182824z.md`），Task 3 Step 4 的「只能標 blocked」已作廢，整合測試要實跑並附輸出。
- `repo.get_version(...)` 回 `TutorialVersion | None`，取 `.slug` 前要先擋 `None`，否則 **mypy strict 紅燈**（pyproject `files = ["src","infra"]`）。
- `select_active_rules` 每型態只回一條 → `rules_applied` 最多等於「命中步驟的不同型態數」，不是所有 active 規則。candidate／retired 永不入選（F29、`APL` Rule 2）。
- lease scope 逐字 `TUTORIAL#<slug>`（`LEASE#` 前綴由 P11 自己補）；拿不到丟 `TransientError` 交 ASL 重試，**不自行迴圈等待**；`release_lease` 放在 `finally`。`now=record.updated_at`（本計畫選擇，不在深層讀系統時鐘）。
- 「已產版」用 `verify_version_complete`，**不是** `status`。有 `version_id` 但不完整 → 沿用同版號與 `record.model_output_refs[-1]`，**不再呼叫 Writer**。
- `reason` 逐字 `feedback:<n> 則 <category>`，`<n>` 是**去重後**筆數（00A §3.3 三種 reason 格式之一，測試逐字比對）。
- `evidence_fingerprint` 只吃 `version_id` ＋ `category` ＋ 排序去重 ID；平均分、留言、時間都不能進去。
- `generate_json` 吃 dict 回 dict（D-02）；`StepRewrite` **不是** pydantic 類別。`rules_for_content` 回 dict（D-03），別解包成兩個值。
- `put_object(..., if_none_match=False)` 的 keyword 不可省。
- gate：**O3 FAIL**（本 Phase 不發布，不受阻；但別把「建出 v2」寫成「已公開」）；**O5 BLOCKED**（假 Writer；真實 AWS 上 `refine_steps` 節點走 Catch，是 BLOCKED 證據）。

## 7. 需要裁決的點 → 建議裁決
- `_guard` 的 `CoordinationError` 對象（指紋不符 vs 未接受）→ **兩者都丟 `CoordinationError`**，訊息分開寫，照文件。
- 租約時鐘來源 → **`record.updated_at`**（本計畫選擇，與 P51 的 `now_utc()` 不同是刻意的，00A §6.9 已記）。
- 整合測試若 AWS 隔離表尚未備妥 → **先跑 moto 版本並在報告寫明「協定 A」**，真實表那條保留 `@pytest.mark.aws` 並記錄實際結果，不假裝通過。

## 8. 對 AWS 的實際操作
- `tests/integration/test_feedback_refine_retry.py`（`@pytest.mark.aws`）：真實 DynamoDB `training_kb` 表與 bucket `training-kb-content-example`，region **us-east-1**（CLI 一律帶 `--region us-east-1`）。
- 跑法：`TKB_RUN_AWS_INTEGRATION=1 uv run pytest tests/integration/test_feedback_refine_retry.py -m aws -q`。
- 證據存 `docs/plan/report/phases/2026-09-14-Phase46-REP.md` §3／§4：兩次執行的 `operation_id`、`record.version_id`、`model_output_refs` 長度、`writer.request_attempts`。**不把 bucket 內容或憑證寫進 repo。**
