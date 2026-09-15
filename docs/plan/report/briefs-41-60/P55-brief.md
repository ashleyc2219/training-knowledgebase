# P55 brief — 規則驗證與狀態轉移

## 1. 單一交付物與停止點
- **交付物**：`evaluate_batch` → `next_status` → `apply_rule_status` 這條鏈，讓「兩項嚴格改善」與 candidate→active→retired 狀態機可由**自含、明示非核定**的合成 fixture 重現；`RULE.status` 與最近驗證時間只從 `analytics/status_writer.py` 寫出去。
- **停止點**：兩個測試檔綠、唯一寫入者 `rg` 檢查過、全套 `-W error` 綠；**不提新規則、不合併規則 ID、不搬 evidence、不改規則文字、不建版本、不發布、不寫 `applied_to`、不自行呼叫模型、不動 CDK**。**程式重算成功 ≠ 維護者核定 O7**（那是 P56）。

## 2. 已存在、直接重用
| file:name | 用途 |
|---|---|
| `src/training_kb/analytics/status_writer.py` | **已存在**（P40）：`VALIDATED_AT_KEY = "operations/rules/validated_at.json"`、`load_validated_at(repository) -> dict[str, datetime]`。現行版把 decode + `json.loads` 一起包 `try`，壞檔一律 `PermanentError`（commit `a4f3173`）。**只能 Edit 追加，不得 Write 覆寫** |
| `src/training_kb/repository.py` | `get_meta(pk, model, *, consistent=True)`、`update_meta(pk, changes, *, expected_revision) -> int`、`revision_of(pk) -> int`（不存在丟 **`CoordinationError`**）、`get_object(key) -> bytes\|None`、`put_object(key, body, content_type, *, if_none_match)` |
| `src/training_kb/keys.py` | `rule_pk(rule_id)`、`feedback_pk(feedback_id)`（只吃裸 ID） |
| `src/training_kb/content.py::parse_version_id(value) -> tuple[str,int]` | 版號解析；格式不合丟 **`ValueError`**（不是 `PermanentError`） |
| `src/training_kb/clock.py::to_iso/parse_iso` | `to_iso` 遇 `microsecond != 0` 丟 **`PermanentError`**（不截斷）→ 寫入前必須 `now.replace(microsecond=0)` |
| `src/training_kb/rules.py::select_active_rules/rules_for_content`（P19） | 本 Phase 寫的 `active` ＋ `validated_at.json` 是它的唯一輸入；缺驗證時間的 active 規則它會丟 `PermanentError` |
| `src/training_kb/repository.py::rebuild_rule_projection`（P28） | 寫 RULE 的 **`applied_to`**（不是 `status`）→ 不違反唯一寫入者 |
| `tests/unit/conftest.py::RecordingWriter/fake_writer`（P15） | O5 BLOCKED 時要造模型輸出就用它；**本 Phase 是這支 conftest 唯一記名的修改者**（00A §3.3） |

## 3. 要新增／修改的東西
| 動作 | 路徑 | 名稱（00A §6.10 為契約） |
|---|---|---|
| 新增 | `src/training_kb/analytics/validation.py` | `Verdict = Literal["improved","not_improved","undecidable"]`；`@dataclass(frozen=True) SeedBatch`（10 欄）；`@dataclass(frozen=True) RuleEvaluation`（13 欄，含 `average_delta`／`rate_delta`／`decidable`）；`evaluate_batch(batch, *, approved, repository)`；`validated_conflict(judgement, candidate, *, repository)`；`next_status(current, evaluations, conflict)`；`curation_groups(rules)` |
| **修改** | `src/training_kb/analytics/status_writer.py` | 追加 `LEGAL_TRANSITIONS`、`record_evaluation(evaluation, *, repository) -> str`、`apply_rule_status(rule_id, status, *, repository, now) -> AuthoringRule`。**⚠ 只 Edit**，放 `# ---- Phase 55 ----` 區段 |
| **修改** | `src/training_kb/handlers/analytics.py` | 加 `action: "validate_rules"` 分支 ＋ `validate_rules_action(event, *, repository, approved) -> dict`。**⚠ 只 Edit**，P54 的 `metrics` 分支不得被覆寫；**不動 CDK**（D-58，P54 已給足 `grant_read_write_data`／`grant_read_write`） |
| **修改** | `tests/unit/conftest.py` | 追加 `fake_repo`／`batch`／`rules` 三個 fixture，不改既有 `RecordingWriter`／`fake_writer` |
| 測試 | `tests/unit/test_rule_validation.py`、`tests/unit/test_rule_status_writer.py` | 00A §3.3 指定；basename 未被占用 |
- **W3 單獨一波**，理論上沒有同波併行者；但 `status_writer.py`／`handlers/analytics.py` 都是 W1 才剛落地的檔 → 動手前先重讀那一段。

## 4. Task 順序與紅燈訊號
1. **Task 1 批次評估＋兩個差值＋不可判定**
   - 先在 `tests/unit/conftest.py` 補三個 fixture（`fake_repo` 內含 `R-006` active/`click_ui`、`R-007` candidate/`click_ui`、`R-013` active/`read`，每條 `evidence=["fx_1"…"fx_5"]`；`prepare-meeting@v1/@v2` 兩個已發布版本；捷徑 `set_version`／`seed_metrics`／`seed_rule`；`updated`／`objects` 兩個 dict 記寫入；`monkeypatch` 換掉 `validation.version_metrics`）
   - RED：`uv run pytest tests/unit/test_rule_validation.py -q` → `cannot import name 'evaluate_batch'`
   - GREEN：`improved`、`(2.875, 4.4)`、`(0.7, 0.2)`、`round(average_delta,3)==1.525`、`round(rate_delta,3)==-0.5`、未核定批次 `undecidable` + `"batch_not_approved"`；四個參數化不可判定案例（`unpublished_comparison`／`cross_tutorial`／`missing_average`／`zero_denominator`）**都不得回 `not_improved`**
2. **Task 2 兩項嚴格改善＋連續兩批退役＋衝突＋curation**
   - RED：同上 → `cannot import name 'next_status'`
   - GREEN：五個參數化（只有 `(2.875,4.4,0.7,0.2)` 是 `improved`）、`retired` 恆回 `retired`、兩個不重疊 `not_improved` 才退役、重疊／`undecidable`／未核定都不退役、衝突只退役 candidate、四個 broken judgement 回 `None`、`curation_groups(rules) == (("R-006","R-007"),)` 且 `fake_repo.updated == {}`
3. **Task 3 唯一寫入者＋validated_at＋handler 分支**
   - **前置檢查**：`handlers/analytics.py` 不存在就停，回 P54
   - RED：`uv run pytest tests/unit/test_rule_status_writer.py -q` → `cannot import name 'apply_rule_status'`
   - GREEN：
     ```bash
     uv run pytest tests/unit/test_rule_status_writer.py tests/unit/test_rule_validation.py -q
     rg -n 'update_meta\(.*status|"status":' src/training_kb --glob '!**/analytics/status_writer.py'
     ```
     逐行確認命中的都不是 `RULE#` 的 `status`（現況 10 行：OPS／PROC／`TutorialStatus.RETIRED`／execution status）
   - 冪等：同批次帶同一個 `now` 重跑兩次，RULE item、證據檔與 `validated_at.json` 完全相同
4. **收尾 gate**：`uv run pytest tests -q -W error`、`uv run ruff check src tests infra`、`uv run ruff format --check src tests infra`、`uv run mypy`
5. **提交**：逐檔列路徑，trailer 照 COMMON R8

## 5. 00B primary Rule 與對應測試
| Rule | 測試 |
|---|---|
| `VAL` 1 對照＝同篇套用前的已發布版本 | `test_rule_validation.py` 的 `cross_tutorial`／`unpublished_comparison` 參數化 |
| `VAL` 2 兩項嚴格改善才升 active | 五個參數化 ＋ `test_candidate_needs_improved_to_become_active` |
| `VAL` 3 未載入完整核定批次不改狀態 | `test_evaluate_batch_is_undecidable_when_batch_is_not_approved` ＋ `test_overlapping_undecidable_or_unapproved_batches_never_retire` |
| `VAL` 4 衝突的 candidate 轉 retired | `test_conflict_retires_only_the_candidate` ＋ `test_unverifiable_conflict_is_ignored` |
| `VAL` 5 失效的 active 轉 retired | `test_two_non_overlapping_unimproved_batches_retire_the_rule`（`current="active"`） |
| `VAL` 6 驗證無效的規則退役 | 同上（`current="candidate"`）＋ 重疊批次反例 |
| `VAL` 7 curation 只分組 | `test_curation_only_groups_and_never_changes_status` |
| `VAL` 8 Analytics 寫入驗證後 status | `test_rule_status_writer.py` 的唯一寫入者測試 ＋ `rg` 檢查 ＋ handler 分派測試 |
| `MET` 6 評分差與重開票率差 | `test_evaluation_reports_both_deltas` |
- **相關（不認領）**：`APL` 2（primary P19）。

## 6. 風險與陷阱
- **`test_record_evaluation_writes_one_evidence_file_per_batch` 原文有真 bug**：`0.2 - 0.7 == -0.49999999999999994`，JSON round-trip 後 `== -0.5` 是 **False**。改用 `pytest.approx(-0.5)`。**不要**在 `_delta` 裡四捨五入。
- **不要覆寫 `load_validated_at`**：§7 重貼它只為可讀；現行版有壞檔 `PermanentError` 強化（`a4f3173`），覆寫等於回退。
- **`fake_repo` 這個 fixture 名在測試樹已被用三次**：`tests/unit/pipelines/conftest.py`（P38）、`tests/unit/pipelines/test_ticket_name_gap.py`（刻意遮蔽）、`tests/unit/test_allocate_version.py`（P20 模組層）。pytest 解析順序「模組層 > 最近 conftest > 上層 conftest」→ 新增不會撞，但**必須跑全套**確認。
- **`monkeypatch` 換得掉的前提**：`validation.py` 要用 `from training_kb.analytics.version import version_metrics` 做模組層名稱綁定。
- **`asdict` + `frozenset`**：`RuleEvaluation.version_ids` 是 `frozenset`，`json.dumps` 會 `TypeError` → `record_evaluation` 必須覆寫成 `sorted(...)`。
- **`undecidable` 與 `not_improved` 必須分開**，合併會讓兩個資料不足的批次直接退役規則。
- **狀態機優先序是本計畫選擇**：`retired` 終態 → 已驗證衝突 → 連續兩批未改善 → 最新 improved；`evaluations` 由呼叫端依 `approved_at` **升序**傳入。
- **`revision_of` 丟 `CoordinationError`**（不是 `PermanentError`）→ `apply_rule_status` 先 `get_meta` 判 `None` 的順序不能調換。
- **`next_status` 回 `RuleStatus`**（StrEnum）→ 測試的 `== "active"` 成立，回傳值可直接給 `apply_rule_status`。
- **mypy strict 涵蓋 `src`**：§7 實作片段**全部省略型別註記**，要照 §5 Produces 補齊（`Verdict` 用 `typing.Literal`；`RuleStatus`／`StepType` 是 StrEnum，**不得**改寫成 `Literal`，D-10）。
- **O7 紅線**：報告與文件都不得寫「R-007 已 active」「種子已核定」「O7 通過」。只能說「狀態機測試通過」。
- **O4 紅線**：rate 比較帶著 O4 未核定狀態，不得宣稱重開票率已有規格答案。

## 7. 需要裁決的點 → 建議裁決
1. **`rate_delta == -0.5` 的浮點比較** → 改 `pytest.approx(-0.5)`（已寫進 Phase 55 文件）。
2. **`rg` 唯一寫入者指令太寬** → 縮成 `rg -n 'update_meta\(.*status|"status":' src/training_kb --glob '!**/analytics/status_writer.py'`（已寫進文件）。
3. **00B §2.12 Rule 3 的測試名 `test_undecidable_batches_never_retire` 與文件的 `test_overlapping_undecidable_or_unapproved_batches_never_retire` 不同名** → 以 Phase 文件為準，回報 controller 統一處理 00B（本 Phase 不改 00B）。
4. **`conflict` 在 `validate_rules_action` 固定傳 `None`** → 維持：衝突判定要由呼叫端先取得 `ConflictJudgement` 並過 `validated_conflict`，這個 action 不自行呼叫模型。

## 8. 對 AWS 的實際操作
- **無。** 本 Phase 全部是純函式 + 假 Repository 的單元測試，**不動 CDK、不部署、不連 AWS、不呼叫 Bedrock**。判斷類模型參數（`maxTokens 512`、`temperature 0.1`）由 `writing/client.py::JUDGEMENT_INFERENCE_CONFIG` 統一提供，本 Phase 不重設；O5 BLOCKED 下若有任何模型節點一律用 `RecordingWriter` 假 writer。
