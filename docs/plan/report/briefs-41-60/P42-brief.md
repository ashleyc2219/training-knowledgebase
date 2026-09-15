# P42 brief — Feedback 與 View 固定匯入

波次 **W2**。前置：P41（W1）必須先產出 `infra/training_kb_stack.py`、`tests/unit/infra/`、
`pipelines/common.py::build_deps`、相依 layer／bundling。文件：`docs/plan/unfinish/42-Phase42-*.md`
（已於 2026-09-14 W0 更新，commit `fd9a5f9`）。

## 1. 單一交付物與停止點

- **交付物**：Feedback／View 的固定匯入路徑——欄位驗證、版本與退役檢查、永久去重、寫 DynamoDB，
  加上 Lambda 入口 `training-kb-import` 與它的 CDK 接線。
- **停止點**：`category` 的模型判定（P43）、弱教學（P44）、指標（P53/54）、真實 AWS 部署驗收（P41/P60）
  都不做；`ticket`／`release` 分支只是委派既有的 `normalize_then_accept`，不重寫那條路徑。

## 2. 已存在、直接重用

| file:name | 用途 |
|---|---|
| `src/training_kb/ingress.py::_parsed_ts(payload)` | `ts` 驗證：aware ISO-8601 **整秒**，naive／格式錯／微秒都丟 `IngressError(("ts",))`。**必用**，不要只 `parse_iso` |
| `src/training_kb/ingress.py::missing_nonempty_strings(payload, keys)` | 一次回報所有缺欄位，直接當 `IngressError.fields` |
| `src/training_kb/ingress.py::operation_id_for(kind, canonical_id)` | 回 `op-{kind}-{canonical_id}`；`OperationKind` 已含 `"feedback"`／`"view"` |
| `src/training_kb/ingress.py::normalize_then_accept(...)` | **回 `list[Acceptance]`**（D-73） |
| `src/training_kb/content.py::assert_accepts_feedback(tutorial)` | 唯一的 retired 判斷，丟 `IngressError(fields=("tutorial_version",))`。`content.py` 不 import `ingress`，無循環 |
| `src/training_kb/source_ids.py::stable_user_from_import(value)` | `user` 格式檢查 `^[a-z0-9_-]{2,64}$`，丟 `IngressError(fields=("user",))`。`u_01`／`u_gh-90210` 都過 |
| `src/training_kb/keys.py`：`feedback_pk`／`version_pk`／`view_pk(tv, user, ts)`／`parse_pk` | `view_pk` 內部 `to_iso(ts)`，ts 帶微秒會丟 `PermanentError` |
| `src/training_kb/repository.py` | `get_meta`／`put_meta`／`put_edge`／`get_tutorial`／`get_version`／`list_feedback_of_version`／`list_views_of_version`／`scan_entity`。`_entity_pk` 已認得 `Feedback`（`FEEDBACK#id`）與 `TutorialView`（`view_pk`） |
| `src/training_kb/operations.py` | `AcceptOperation(operation_id, kind, canonical_id, project_id, now)`、`Acceptance(status, operation_id, record)`、`accept`、`complete(op, *, now)` |
| `src/training_kb/models.py::Feedback` | **已有** `rating_is_strict_int`（`mode="before"`，擋 `bool` 與非 1..5）與 `carries_signal` |
| `src/training_kb/config.py::DEFAULT_PROJECT_ID = "demo"`、`load_settings(env=None)` | 操作紀錄分組用 |
| `tests/integration/conftest.py`：`table`／`bucket`／`repository` | moto 表＋bucket＋`by_target` GSI |
| `tests/integration/test_retired_feedback_rejected.py`（P26） | 現成的退役教學種子範例，照抄形狀；**不要改那支檔** |

## 3. 要新增／修改

- **`src/training_kb/ingress.py`**（W2 只有你動；W3 是 P43、W4 是 P59）——追加 `# ---- Phase 42 ----` 區段：
  - `FEEDBACK_FIELDS: frozenset[str]` = `{id, tutorial_version, rating, category, comment, user, ts, project_id}`
  - `VIEW_FIELDS: frozenset[str]` = `{tutorial_version, user, ts, project_id}`
  - `@dataclass(frozen=True) class ImportResult{status: Literal["saved","duplicate","rejected"]; object_id: str|None; message: str; invalid_fields: tuple[str,...]}`
  - `def validate_feedback(payload: Mapping[str, object], *, now: datetime) -> Feedback`
  - `def validate_view(payload: Mapping[str, object]) -> TutorialView`
  - `def import_feedback(payload, *, repository: Repository, operations: OperationCoordinator, now: datetime) -> ImportResult`
  - `def import_view(payload, *, repository, operations, now: datetime | None = None) -> ImportResult`
  - private：`_text`／`_optional_text`／`_stable_user`／`_rejected`／`_project_id`／`_saved_message`／`_assert_open`／`_dedupe`
- **`src/training_kb/handlers/import_.py`**（新檔）：`IMPORT_KINDS = ("feedback","view","ticket","release")`、
  `IMPORT_DEADLINE_SECONDS = 300.0`、`_DEPS: Deps | None = None`、
  `def handler(event: dict[str, Any], context: object) -> dict[str, object]`、`_import_one`。
  mypy strict 涵蓋 `src`，型別要標滿（照 `handlers/github_webhook.py`）。
- **`infra/training_kb_stack.py`**（**W2 同時有 P54 在改** → Edit-only、自己的 `# ---- Phase 42 ----` 區段、
  `git add` 只加自己路徑）：`import_fn`（`function_name="training-kb-import"`、
  handler `training_kb.handlers.import_.handler`、timeout 300s、`environment=base_env`、
  **`code=` 沿用 P41 的 layer／bundling**）＋ `table.grant_read_write_data`／`bucket.grant_read_write`／
  `machine.grant_start_execution`（只有 ticket-analysis 存在）。**不開 Function URL**、**不給 bedrock**。
- **測試**（00A §3.3 指定的檔名，照用）：`tests/unit/test_fixed_import_validate.py`、
  `tests/integration/test_fixed_import.py`、`tests/unit/infra/test_import_lambda.py`。

## 4. Task 順序與紅燈訊號

| Task | 指令 | 預期紅燈訊號 |
|---|---|---|
| 1 欄位契約 | `uv run pytest tests/unit/test_fixed_import_validate.py -q` | `cannot import name 'validate_feedback' from 'training_kb.ingress'` |
| 2 寫圖譜／退役／去重 | `uv run pytest tests/integration/test_fixed_import.py -q` | `cannot import name 'import_feedback'` |
| 3 View 去重與續跑 | `uv run pytest tests/integration/test_fixed_import.py::test_same_view_triple_is_deduplicated -q` | `cannot import name 'import_view'` |
| 4 Lambda 入口＋CDK | `uv run pytest tests/integration/test_fixed_import.py tests/unit/infra/test_import_lambda.py -q` | `No module named 'training_kb.handlers.import_'` |

收尾：`uv run pytest tests -q -W error`（基線 924 passed / 23 skipped / 11 xfailed）、
`uv run ruff check src tests infra`、`uv run ruff format --check src tests infra`、`uv run mypy`。
共用檔（`ingress.py`、`training_kb_stack.py`）只 `ruff format --check`，不整支 format。
紅燈若來自 P54／P46／P51 進行中的檔，用 `--ignore=` 排除並寫進報告（R3.5）。

## 5. 00B primary Rule → 測試

| Rule | 測試 |
|---|---|
| `COL` 1 版本必須存在於圖譜 | `test_fixed_import.py` 版本不存在 → `rejected(("tutorial_version",))`、圖譜零變動 |
| `COL` 2 退役拒絕新回饋 | `test_fixed_import.py::test_retired_tutorial_rejects_feedback_but_still_accepts_views` |
| `COL` 3 rating 只能 1–5 整數 | `test_fixed_import_validate.py` 參數化 `True`／`False`／`"4"`／`3.5`／`0`／`6`／`None` |
| `COL` 7 回饋關聯到指定版本 | `test_fixed_import.py` 斷言 `REFERS_TO#VERSION#prepare-meeting@v1` 邊，不改綁 `current_version` |
| `COL` 8 單筆低分不改教學 | `test_fixed_import.py` 零新 `VERSION#` item |
| `COL` 9 必須提供穩定使用者 ID | `test_fixed_import_validate.py` 缺 `user`／`"U_01"` → `("user",)` |
| `COL` 10 每次新提交各計一筆 | `test_fixed_import.py` `f_12`／`f_13` 都 saved；同 ID 重送 duplicate |
| `ING` 28 寫入 FEEDBACK item | `test_fixed_import.py` 寫入成功且零 PROC、零 StartExecution |
| `ING` 29 單筆不觸發改版 | 同上＋Task 4 的副作用斷言 |

相關（不重新認領）：`ING` 24（primary P13）、`ING` 30（primary P10）、`ING` 31（primary P35）。

## 6. 風險與陷阱

1. **`normalize_then_accept` 回 `list[Acceptance]`**（D-73）。文件舊片段當成單一物件，會 `AttributeError`。
2. **`build_deps` 目前不存在**，owner 是 P41（W1）。開工時若還沒有，回報 controller，**不要自己造一份**。
3. **`infra/training_kb_stack.py` 目前不存在**，`tests/unit/infra/` 也沒有。W1 完成才動得了；用 Edit 不用 Write。
4. **微秒 `ts`**：`parse_iso` 放行微秒 → `view_pk` 的 `to_iso` 丟 `PermanentError`（不是 `IngressError`）。用 `_parsed_ts`。
5. **`Repository` 沒有 `started_executions`**。零啟動改成 monkeypatch `ingress._build_wiring`／`_build_rote_deps`
   為會丟 `AssertionError` 的函式（`tests/conftest.py` 的 `rote_deps` fixture 就是這個手法），
   再加 `repository.scan_entity("PROC") == []`。記得測試結尾 `ingress._reset_wiring()`。
6. **rating 的理由**：`Feedback` 模型已擋 `bool`；入口自己判斷是為了吐 `IngressError` 而不是 `ValidationError`。
7. **退役判斷**：一律 `assert_accepts_feedback(tutorial)`，不寫 `tutorial.status == "retired"`；StrEnum 成員大寫 `TutorialStatus.RETIRED`。
8. **續跑（D-45）**：`accept` 回 duplicate ≠ 物件存在。要 `repository.get_meta(pk, Model) is not None` 才回 duplicate，否則補寫。
9. **`ImportResult.invalid_fields` 是 tuple**；`asdict()` 保留 tuple，JSON 序列化成 array。
10. **release 分支的 IAM 缺口**：`training-kb-release-update` 在 P52（W3）才存在，本 Phase 只能授權 ticket-analysis。
11. moto 綠燈 ≠ O2／O6 通過；報告不得這樣寫。

## 7. 需要裁決的點 → 建議裁決（可直接採用）

| 點 | 建議 |
|---|---|
| O6 未核定擋不擋 `stable_user`？ | **不擋**。11 個 `xfail(strict)` 全在 Rote／來源簽名側（`test_o6_*`、`test_adapter_fixtures.py`、`test_release_extraction.py`、`test_rote_commit.py`、`tests/unit/rote/`）；`feedback`／`view` 不經 Rote、不查 `approved_stable_keys()`。**直接重用 `stable_user_from_import` 做 `user` 格式檢查**（滿足 `COL` Rule 9、不另寫判斷），但報告不得宣稱 O6 已核定。被 O6 擋住的只有 handler 的 `ticket`／`release` 分支。 |
| P36 的 `items[0]` 怎麼展開？ | `adapters.py::_batch_item` **不動**（那是 Rote 工具的「一次一筆」語意）。多筆展開在 `handler`：`event["items"]` 逐筆 `_import_one`，一筆壞不影響其他筆。 |
| `release` 分支的 StartExecution 授權 | 只授權 ticket-analysis；release-update 由 P52 建 state machine 時補 `grant_start_execution(import_fn)`。寫進報告「未做／建議」。 |
| `ts` 驗證函式 | 重用 `_parsed_ts`（擋微秒），不新寫。 |
| 00A 第 915 列說「`validate_feedback` 必須呼叫 `assert_accepts_feedback`」 | 以 00A 第 425 列的實質規則為準：呼叫點在 `import_feedback`（`validate_feedback` 拿不到 `Tutorial`）。已回報 controller。 |

## 8. 對 AWS 的實際操作

本 Phase **不直接跑真實 AWS**（雲端驗收在 P41 與 P60）。只要 `cdk synth` 能過即可：
`AWS_REGION=us-east-1 AWS_DEFAULT_REGION=us-east-1 command npx aws-cdk@2 synth --outputs-file <scratchpad>/out.json`
（`node` 被本機 shell 擋住，必須 `command npx`；**不要提交 `cdk.out/`**）。
`Template.from_stack` 在 `uv run pytest` 下可用，單元測試不需要 AWS 憑證。
