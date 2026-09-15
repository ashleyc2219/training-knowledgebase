# P51 brief — Release UPDATE 精準改寫

文件：`docs/plan/unfinish/51-Phase51-Release-UPDATE精準改寫.md`（W0 已更新，commit `16c59b1`）
波次：**W2（在 P49／P50 之後，P52 之前）**

## 1. 單一交付物與停止點
- **交付物**：`prepare_update` — 對每一篇命中的教學逐篇取 lease、開子 operation、選規則、配版號、呼叫 `StepRewrite`、程式核對改寫範圍、`create_version`。
- **停止點**：回 `tuple[VersionPlan, ...]`（依 `slug` 升序），每個對應一個 `published_at=None` 的私有版本。**不發布、不切 `current_version`、不更新 aliases、不退役、不處理 `removed`**。

## 2. 已存在、直接重用
- `src/training_kb/content.py`
  - `VersionPlan(version_id, slug, number, supersedes, reason, rules_applied: tuple[str,...], operation_id)`（frozen）。
  - `allocate_version(tutorial_id, operation_id, operations, *, repository, reason, rules_applied) -> VersionPlan`（`record.version_id` 非空就走 `_replay_plan`；內部已 `record_version`，**不要再補一次**）。
  - `validate_content(content, known_feature_ids: frozenset[str]) -> None`、`parse_markdown`／`render_markdown`／`make_diff`、`create_version(plan, content, repository) -> TutorialVersion`（寫 `v<n>.md`／`v<n>.diff` 與所有邊）、`verify_version_complete(version_id, repository) -> bool`、`markdown_key`／`diff_key`。
- `src/training_kb/operations.py`：`AcceptOperation(operation_id, kind, canonical_id, project_id, now)`、`accept(request) -> Acceptance`（`status ∈ {"accepted","duplicate"}`）、`load -> OperationRecord | None`（有 `project_id`、`version_id`、`model_output_refs`）、`record_model_output`、`acquire_lease(scope, owner, *, ttl_seconds, now) -> bool`、`release_lease(scope, owner)`。`OperationKind` **已含 `"release-update"`**。
- `src/training_kb/rules.py`：`rules_for_content(rules, step_types, validated_at_by_rule) -> dict[StepType, list[AuthoringRule]]`（每個 type 最多一條）、`render_rules_block`（`[<rule_id>] applies_when=<type>\n<rule>`）、`applied_rule_ids`。
- `src/training_kb/analytics/status_writer.py:load_validated_at(repository) -> dict[str, datetime]`（D-28：**不得**另寫 `_load_validated_at`）。
- `src/training_kb/writing/validators.py:step_rewrite_validator(*, allowed_steps: frozenset[int], allowed_features: frozenset[str])`；`schemas.py:StepRewrite`（step 需要 `number`／`type`／`text`／`feature_id`）。
- `src/training_kb/keys.py:operation_ref(op, name) -> "operations/<op>/<name>.json"`；`repository.py:get_object -> bytes | None`、`put_object(key, body, content_type, *, if_none_match)`（412→`ObjectAlreadyExists`、409→`TransientError`）、模組函式 `item_to_model`。
- `src/training_kb/ingress.py:operation_id_for(kind, canonical_id)`；`clock.py:now_utc`。
- P49／P50 在同一支 `pipelines/release.py` 的 `StepHit`、`normalize_feature_name`。

## 3. 要新增／修改的東西
`src/training_kb/pipelines/release.py` → `# ---- Phase 51 ----`：
```python
REWRITE_NODE = "release_rewrite"
def assert_unchanged(base: TutorialContent, draft: TutorialContent,
                     changed: frozenset[int]) -> None: ...
def prepare_update(release: Release, hits: Sequence[StepHit], *, repository: Repository,
                   writer: Writer, operations: OperationCoordinator,
                   operation_id: str) -> tuple[VersionPlan, ...]: ...
# private: _apply_rewrite / _rules_for_hits / _sub_operation / _prepare_one / _rewrite_once
```
`src/training_kb/writing/prompts.py`（共用檔，只 Edit 自己區段）：
```python
def prompt_release_rewrite(release: Release, base: TutorialContent,
                           targets: Sequence[int], rules_block: str) -> tuple[str, str]: ...
```
`from training_kb.pipelines.feedback import LEASE_TTL_SECONDS`（owner **P46**，值 120，00A §5.4）。
測試檔（00A §3.3）：`tests/unit/test_release_update.py`、`tests/unit/test_release_update_rules.py`、`tests/integration/test_release_update_retry.py`。

## 4. Task 順序與紅燈訊號
1. **Task 1｜只改命中步驟，其餘逐字相同**
   - RED：`uv run pytest tests/unit/test_release_update.py -q` → `cannot import name 'prepare_update'`
   - GREEN：只有第 3 步 text 不同；1／2／4 步 `model_dump()` 相等；四個段落相等。模型多改第 2 步 → `ContentError(match="改寫集合")` 且 `created_versions == []`。
2. **Task 2｜reason／diff／rules_applied**
   - RED：`uv run pytest tests/unit/test_release_update.py tests/unit/test_release_update_rules.py -q` → `cannot import name '_rules_for_hits'`
   - GREEN：`reason == "release:r_42"`；`rules_applied == ("R-007",)`；diff 只有第 3 步兩行；prompt 含 `[R-007]`、不含 `R-012`／`R-099`。
3. **Task 3｜lease、重送、整批**
   - RED：`TransientError` 沒被拋，或 `request_attempts == 2`
   - GREEN：lease 衝突 → `TransientError`；重送同 `version_id` 且 `request_attempts == 1`；兩篇依 slug 升序、`published_version_ids == []`；`ops.accepted_ids == ["op-release-update-r_42--prepare-meeting", "op-release-update-r_42--weekly-digest"]`、父 operation `version_id is None`。
   - 再跑 `uv run pytest tests/integration/test_release_update_retry.py -q`（moto）。
4. 收尾：`ruff check`／`ruff format --check`／`mypy`／`uv run pytest tests -q -W error`。

## 5. 00B primary Rule → 測試
| Rule | 說明 | 測試 |
|---|---|---|
| `REL` 8 | renamed／changed 走 UPDATE | `test_release_update.py`（`removed` 入口 → `PermanentError`） |
| `REL` 10 | 只重寫受影響步驟 | `test_release_update.py::test_only_hit_steps_change_and_others_are_byte_for_byte`、`::test_model_touching_an_extra_step_is_rejected` |
| `REL` 11 | 未命中步驟原文複製到下一版 | 同上（1／2／4 步 `model_dump()` 逐欄比較） |
| `REL` 13 | 產生與前版的 diff | `test_release_update.py::test_diff_only_covers_the_hit_step` |
| `REL` 14 | reason 用 `release:<id>` | `test_release_update.py::test_reason_and_rules_come_from_this_run` |
| `APL` 8 | 後續 Release 重寫仍注入 active 規則 | `test_release_update_rules.py::test_only_injected_active_rules_enter_prompt_and_record` |

## 6. 風險與陷阱
- **跨群組相依**：`pipelines/feedback.py` 目前只有 docstring 空殼，`LEASE_TTL_SECONDS` 的 owner 是 **P46**（另一組）。開工前確認 P46 已提交；**不得**在 `release.py` 自己宣告第二份。
- **`TutorialContent` 沒有 `.step()`／`.sections()`**（文件片段是示意）。測試 helper 自己寫，不要改 `models.py`。
- **`item_to_model` 是模組函式**，不是 `Repository` 方法。
- 共用 `fake_writer` 的 `replies` 是 list（依序 pop）、記的是 dict；文件用的 `.reply`／`.json_calls` 要自己在測試檔定義。`request_attempts` 倒是共用版本就有。
- `model_copy(update=...)` 不驗證 → `type` 一定要先 `StepType(item["type"])` 轉過再塞。
- **D-59**：每篇先 `accept` `op-release-update-<release_id>--<slug>` 子 operation，再 `allocate_version`。父 operation 不佔版號、不重複 `record_version`。`project_id` 取自父 operation record；讀不到 → `CoordinationError`。
- 規則選取**排在 `allocate_version` 之前**（prompt 與 `rules_applied` 必須同一份 selected list）。
- lease `try/finally` 歸還，否則 `ContentError` 之後要等 TTL；scope 是 `TUTORIAL#<slug>`（P11 自己補 `LEASE#` 前綴）。
- 模型輸出 ref 是 **per-slug**：`operations/<父 operation_id>/rewrite-<slug>.json`，不用 `model_output_refs[-1]`。
- `put_object(..., if_none_match=True)` 在併發重送會丟 `ObjectAlreadyExists`（`PermanentError` 子類）——本 Phase 不吞它。
- **O3 FAIL** 不影響本 Phase（本來就不發布）；**O2 PASS** → 重送 Task **不標 BLOCKED**，照做但不得把 moto 綠燈說成真實併發證據；**O5 BLOCKED** → `StepRewrite` 只有假 writer。

## 7. 需要裁決的點 → 建議裁決
1. **P46 還沒落地怎麼辦**？→ 回報 controller 等待；**不要**自己宣告 `LEASE_TTL_SECONDS`，也不要改成傳參數。
2. **`ObjectAlreadyExists` 要不要轉成「讀回既有輸出」**？→ 不要（保持最小實作）；`get_object` 先讀過已經涵蓋正常重送，併發撞到就讓 Catch 收。寫進報告「未做／建議」。
3. **`known_feature_ids` 從哪來**？→ `frozenset(item_to_model(row, Feature).feature_id for row in repository.scan_entity("FEATURE"))`（`meta_only` 預設 True 已濾過邊）。
4. **`_rules_for_hits` 的去重順序**？→ 照文件：依 `step_types` 出現順序遍歷 `rules_for_content` 的結果，用 `seen` 去重，保留注入順序給 `applied_rule_ids`。

## 8. 對 AWS 的實際操作
**無。** 整合測試跑 moto。真實帳號的「`v2.md` 對 `v3.md` 做 `diff`」與重送證據已寫進 **P52 §6**；受 **O5 BLOCKED**（`PrepareUpdate` 會走 Catch）與 **O3 FAIL** 影響，P52 那兩列列在 BLOCKED 表。
