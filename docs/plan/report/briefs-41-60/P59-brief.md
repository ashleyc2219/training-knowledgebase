# P59 brief — 失敗復原與重送驗收

文件：`docs/plan/unfinish/59-Phase59-失敗復原與重送驗收.md`（已於 W0 更新，commit `d2a2bd8`）。波次 **W4**（P41／P48／P52／P57 之後）。

## 1. 單一交付物與停止點
- **交付物**：用 `TKB_FAULT` 在五個切點注入失敗，證明「讀者永遠看到整批舊狀態」，並以同 `operation_id` 補償重送把東西補齊；外加 `check_asl.py` 靜態檢查三份 ASL。
- **停止點**：出現對外可見的 partial publish／新版號／新模型輸出／重複樣本 → 保留 FAIL 並停；O3 未 PASS 前**不得**宣稱 publish 故障驗收通過。

## 2. 已存在、直接重用
- `src/training_kb/publishing.py`：`Publisher.prepare/inspect/commit`、`promote_site_objects(prepared,*,repository)`、**`public_site_keys(version_ids)`**（含 `site/` 前綴，就是 `pending-promote.json` 的 `site_keys` 算法）、`site_key`、`PENDING_PROMOTE_NAME`、`UNPUBLISHED_MARKER`、`_put_public_object` 守門、`_cut_point`。
- `src/training_kb/content.py`：`allocate_version(tutorial_id, operation_id, operations, *, repository, reason, rules_applied)`、`create_version(plan, content, repository)`、`verify_version_complete`、**`PUBLIC_SITE_PREFIX`（在這裡，不在 publishing）**。
- `src/training_kb/ingress.py`：`_accept`／`_accept_detailed`／`_start_once`；續跑判斷靠 `input_ref`／`execution_arn` 事實欄位（D-45）。
- `src/training_kb/operations.py`：`load/record_version（write-once）/record_model_output（去重）/record_proc_sample（首次 True）/fail/complete/acquire_lease/next_sequence`。
- `src/training_kb/pipelines/asl.py`：`RETRY`（**已兩條**）、`CATCH`、`FAIL_STATE_NAME`、`assert_safe_asl(definition) -> None`（丟 `PermanentError`，已遞迴 Map/Parallel）、`ASL_LOCAL_PATH`。
- 測試資產（**只讀不改**，R3.6）：`tests/integration/test_publish_cutpoints.py`（P24 單篇）、`tests/integration/test_batch_publish_cutpoints.py`（P25：`SiteReader.report()`、`aws_publisher`／`site_reader` fixture、`injected_fault`／`failing_second_promote` contextmanager、「同 operation 重送只補公開物件」案例）、`test_start_execution_idempotency.py`、`test_operations_ledger.py`。
- `infra/scripts/check_models.py`：mypy-strict 的 CLI 骨架（`main(argv)->int`、report dir 解析）。

## 3. 要新增／修改
| 檔 | 內容 | 併行風險 |
|---|---|---|
| 建 `src/training_kb/faults.py` | `FAULT_POINTS`（五個）、`InjectedFault(TransientError)`、`active_fault(env=None)->str\|None`、`maybe_fail(point, env=None)->None`；`TKB_ENV=prod` 一律不注入、未知切點 `ValueError` | 無（除非 P41 先建了→擴充不重建） |
| 改 `content.py` | 切點 1、2 | W4 無人同改 |
| 改 `publishing.py` | 切點 3、4 ＋ `resume_publish(operation_id, *, operations, repository, publisher, now) -> PublishResult` | P57 在 W1/W2 已加 `site_diff_key`；用 Edit、放 `# ---- Phase 59 ----` |
| 改 `ingress.py` | 切點 5 | P42(W2)／P43(W3) 已先改 |
| 建 `infra/scripts/check_asl.py` | `LAMBDA_SERVICE_ERRORS`、`iter_task_states`、`check_asl_document(doc,*,fail_state)`、`main(argv)->int` | 無 |
| 測試 | `tests/unit/test_faults.py`、`tests/unit/test_check_asl.py`、`tests/integration/test_recovery.py`（00A §3.3 指定檔名） | basename 全專案唯一，已確認不撞 |

**切點的確切插入位置**（已寫進文件 §7 Task 1 Step 4 的表）：
1. `content.create_version`：`put_private_artifact(md_key)` 後、寫 diff 前。
2. `content.create_version`：`if existing is None: put_meta(planned)` **整個 if 之後**、`_write_edges` 前。
3. `Publisher.commit`：`inspect` 通過後、`build_commit_transaction` 前（**在 `_after_transaction` 的 try 之外**）。
4. `Publisher._publish_site`：`self._record_pending_promote(prepared)` **之後**、第一次 `_restage` 之前（兩種復原輸入都已就位）。
5. `ingress._accept`：`assert_time_left(step="start-execution")` 後、`_start_once(...)` 前（**不要插在 `_start_once` 裡**，否則 `except Exception` 會先 `operations.fail()` 把 ledger 標 failed）。

## 4. Task 順序與紅燈訊號
1. **Task 1** `uv run pytest tests/unit/test_faults.py -q` → `ModuleNotFoundError: No module named 'training_kb.faults'`。綠燈後加「原始碼掃描：五個名稱各恰好一次 `maybe_fail(`」。
2. **Task 2** `uv run pytest tests/integration/test_recovery.py -q` → `fixture 'world' not found` → 補 `World` 後 `ImportError: cannot import name 'resume_publish'`。
3. **Task 3** `uv run pytest tests/unit/test_check_asl.py -q` → `ModuleNotFoundError: No module named 'infra.scripts.check_asl'`；然後 `uv run python -m infra.scripts.check_asl` 三份全 `[通過]`。
4. **Task 3 Step 4A**（W0 新增）：真實 AWS 承接 P24／P25 的延後驗收，見文件。
- 收尾：`uv run ruff check src tests infra` / `ruff format --check` / `uv run mypy` / `uv run pytest tests -q -W error`（基線 924 passed / 23 skipped / 11 xfailed）。

## 5. 00B primary Rule
**沒有**（00B §1：P25／P41／P59／P60 是驗收型）。相關（直接斷言在 primary）：`ING` 30（P10）、`VER` 2（P20）、`RUN` 2/6/7/10（P29）、`PUB` 4/5（P24）。文件 §10 已寫成「相關」，不要改成 primary。

## 6. 風險與陷阱
1. **切點 4 的例外會被轉型。** `Publisher._after_transaction` 把交易後的任何例外轉成 `PublishError`（`errors.PublishError(Exception)`，**不是** `TransientError`），訊息帶 `_cut_point` 代號。測試用 `pytest.raises((TransientError, PublishError))` 並對切點 4 斷言訊息含 `a2_after_transact_before_site`。**不得**改掉這個轉型。
2. **`resume_publish` 的 `a2` 必須先 `prepare` 再 `promote_site_objects`**（00A §6.7、REP §8 #9）。切點前的 staging 是交易前渲染、帶 `UNPUBLISHED_MARKER`，promote-only 會被 `_put_public_object` 擋下 → 那是復原失敗。復原路徑不得再走 `commit`（`inspect` 會擋已發布版）。
3. **`pending-promote.json` 只有多篇才寫**（`len(version_ids) < 2: return`）。單篇靠 `OPS#<op>.version_id`。
4. **O3 FAIL**：切點 5（`a3`）的 partial 已在 moto 重現（`test_batch_cutpoint_5_partial_is_observed_not_accepted`）。真實 AWS 只記錄觀察，不宣稱通過、不刪頁回滾、不放寬 F49。
5. **O5 BLOCKED**：需要模型的雲端節點必然 `PermanentError → Catch → PipelineFailed`。抓 `get-execution-history` 的 `error`／`cause` 原文標 `BLOCKED（O5）`。
6. **O6 4 列未核定**：Release 走不進 Rote → 真實端到端改走 Ticket 路徑。
7. **mypy `strict` 涵蓋 `infra/`**（`files = ["src","infra"]`）→ `check_asl.py` 與 `resume_publish` 要完整註記；文件片段刻意省略了。
8. `infra/stepfunctions/` 目錄本 Phase 開工前不存在（P41／P48／P52 建）；`main` 掃不到檔要印訊息並回非 0，不要靜靜回 0。
9. `infra/scripts/` 沒有 `__init__.py` 但可 import（namespace package，`check_models` 已驗證）。
10. `assert_safe_asl` 要求**恰好一條** Catch（`len(catch_items)==1`）；`check_asl_document` 的獨立檢查不要與它矛盾。
11. `record_version` write-once：換版號會 `CoordinationError`；`record_proc_sample` 首次後回 `False`（D-75：`CoordinationError` = 已計數）。

## 7. 需要裁決的點 → 建議
- **P41 已建 `faults.py`？** → **擴充不重建**：Task 1 Step 3 改成補齊缺的切點與 `active_fault`／`maybe_fail`，紅燈改成 `ImportError: cannot import name ...`。（W0 查過：P41 文件 §4 目前**沒有**列 `faults.py`。）
- **切點 5 插哪** → 插 `_accept`（不進 `_start_once`），理由見 §3。
- **`resume_publish` 的 key 清單怎麼算** → 用 `public_site_keys((version_id,))`，不要自己拼 `site_key + site_diff_key`（前者是 `promote_site_objects` 的回傳值，不可能分岔，也不用等 P57）。
- **切點 4 的測試型別** → 收 `(TransientError, PublishError)` ＋ 斷言切點代號，不改產品程式。
- **真實 AWS 做不到的部分** → 一律 `BLOCKED（O5/O6）` ＋ 錯誤原文；`FAIL（O3）` 用於 partial 觀察。不標 green。

## 8. 對 AWS 的實際操作
- Region **固定 `us-east-1`**（CLI 一律 `--region us-east-1`；`aws configure` 預設是 ap-northeast-1）。帳號 `123456789012`。
- 既有資源：table `training_kb`、bucket `training-kb-content-example`。
- 指令：`aws dynamodb get-item --consistent-read`、`aws s3api list-objects-v2 --prefix site/tutorials/<slug>/`、`aws stepfunctions describe-execution`／`get-execution-history`、`curl -i http://<bucket>.s3-website-us-east-1.amazonaws.com/tutorials/<slug>/v<n>.html`（**HTTP，沒有 HTTPS**）。
- 真 AWS 測試：`TKB_RUN_AWS_INTEGRATION=1 uv run pytest tests/integration/test_recovery.py -m aws -q`（marker 由 P01 註冊，`tests/conftest.py` 自動 skip）。
- 證據存 `docs/plan/report/recovery-<YYYYMMDD-HHMM>.md`，固定欄位見文件 §7 Task 3 Step 4；報告 `docs/plan/report/phases/2026-09-14-Phase59-REP.md`。
- 不提交 `cdk.out/`、任何 outputs／憑證檔；`git add` 只加自己的路徑。
