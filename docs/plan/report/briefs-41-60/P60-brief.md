# P60 brief — 安全檢查與端到端完成證據

文件：`docs/plan/unfinish/60-Phase60-安全檢查與端到端完成證據.md`（已於 W0 更新，commit `bd6be7d`）。波次 **W5**（最後）。

## 1. 單一交付物與停止點
- **交付物**：單一腳本 `infra/scripts/checks.py`（`security`／`scan`／`rehearse`／`teardown`／`acceptance` 五個子命令），產出 168 列證據索引與三份報告（`evidence.json`、`acceptance-<時間>.md`、`snyk-<時間>.md`）。
- **停止點**：**未執行的檢查不得標 green**。`not_run` 不是警告是不通過；任何 `fail`／`not_run` → `run_all` 回非 0、`acceptance_report` 布林 `False`、結論「未完成」。不得代 P12／13／14／56 宣布 gate PASS。

## 2. 已存在、直接重用
- `infra/training_kb_data_stack.py`：`TABLE_NAME`、`TARGET_INDEX`、`PRIVATE_PREFIXES`（4 個）、`TrainingKbDataStack`。**`s3:ListBucket` 的 `s3:prefix` StringLike 條件已存在** → `check_iam` 是回歸守門。
- `tests/unit/test_data_stack.py`：`synth()` = `Template.from_stack(TrainingKbDataStack(cdk.App(),"TrainingKbData"))`；`test_data_role_has_no_wildcard_action_or_resource`、`test_s3_statement_covers_every_private_prefix_and_never_site`、`test_list_bucket_is_limited_to_the_private_prefixes` — **`check_iam` 三條規則的既有形狀，照抄判準**（只讀不改，R3.6）。第 64 行註解已記下 enforce_ssl 的坑。
- `infra/scripts/check_models.py`：mypy-strict CLI 骨架（argparse、`main(argv: Sequence[str]|None)->int`、`REPORT_DIR = Path(__file__).resolve().parents[2]/"docs"/"plan"/"report"`）。
- `src/training_kb/adapters.py`：`TOOL_NAMES`（frozenset，8 個）、`FINAL_TOOL`、`ToolRegistry`。（**不是** `rote.py`。）
- `src/training_kb/writing/prompts.py`：`_as_data`（module-private，`html.escape(text, quote=False)`）、`<source_data>` 分區。W0 時只有 `prompt_write_tutorial`／`prompt_name_gap`，P43/45/46/47/50/51 會再加 → **動態列舉** `[n for n in dir(prompts) if n.startswith("prompt_")]`。
- `src/training_kb/handlers/github_webhook.py:load_secret()`：`TKB_GITHUB_WEBHOOK_SECRET` 唯一讀取點。
- `src/training_kb/site.py`：`SiteRenderer.render_version_page(tutorial, version, steps, content) -> str`；`escape_text`／`SITE_PREFIX`／`ASSET_KEYS`／`site_diff_key` 由 P57 補。
- 已存在的 gate 報告：`o2-20260914t182824z.md`、`o3-20260914t181109z.md`、`o5-20260914T170050Z.md`、`o5-20260915T030245Z.md`、`o6-mapping.md`（O4／O7 由 P54／P56 產生）。Phase 報告在 `docs/plan/report/phases/`。
- 00B：§1 統計＋13 個縮寫、§2 逐條（primary／**其他相關 Phase**／可觀察 assertion）、§4 S0–S8、§6 V1–V4。

## 3. 要新增／修改
- **建** `infra/scripts/checks.py`（唯一腳本，00A §3.2）：`CheckStatus`／`CheckResult`／`check_secrets(root)`／`check_iam(template)`／`check_public(bucket_policy)`／`check_output_safety()`／`run_all(results)->int`；`ScanRecord`／`render_scan_report(records,*,claim="")`；`EvidenceRow`／`ACCEPTANCE_ROWS`／`load_evidence(path)`／`acceptance_report(rows, evidence)->tuple[str,bool]`；`rehearse_steps()`／`teardown_checklist()`；`SUBCOMMANDS`／`main(argv)->int`。簽名逐字照 00A 第 1231 行那一列。
- **建** `tests/unit/test_security_checks.py`、`tests/unit/test_acceptance.py`（00A §3.3 指定）。
- **產出** `docs/plan/report/evidence.json`、`snyk-<時間>.md`、`acceptance-<時間>.md`。
- 併行風險：**無**（W5，只有本 Phase 動 `checks.py`）。`SUBCOMMANDS` 這個名字 P58 的 demo CLI 也有一份，不同檔、不互相 import。

## 4. Task 順序與紅燈訊號
1. **Task 1** `uv run pytest tests/unit/test_security_checks.py -q` → `ModuleNotFoundError: No module named 'infra.scripts.checks'`。
2. **Task 2** 同一支檔 → `ImportError: cannot import name 'render_scan_report'`；Step 4 實跑 `uv run python -m infra.scripts.checks scan --out docs/plan/report/snyk-<時間>.md`。
3. **Task 3** `uv run pytest tests/unit/test_acceptance.py -q` → `ImportError: cannot import name 'rehearse_steps'`；Step 4 實跑 `... checks rehearse`。
4. **Task 4** 同一支檔 → `ImportError: cannot import name 'ACCEPTANCE_ROWS'`；**Step 3A（W0 新增）**：147 列覆蓋檢查可執行；Step 4 實跑 `... checks acceptance docs/plan/report/evidence.json`。
- 收尾：`ruff check/format --check src tests infra`、`uv run mypy`、`uv run pytest tests -q -W error`。

## 5. 00B primary Rule
**沒有**（驗收型）。相關：`ING` 1/2（P30）、`ING` 7（P34）、`ING` 30（P10）、`PUB` 2（P57）、`MET` 9（P54）、`VAL` 3/6（P55）。文件 §10 已寫成「相關」。

## 6. 風險與陷阱
1. **`check_iam` 只掃 `AWS::IAM::Policy`／`AWS::IAM::Role` 的 `Effect: "Allow"`。** P09 的 `enforce_ssl=True` 會產生 bucket policy 的 `Deny s3:*`（`aws:SecureTransport=false`），整份 template 字串比對會誤判。P57 會把它改成 `False`，兩種情況都要正確。
2. **兩份 template。** 資料角色在 `training_kb_data_stack.py`；**四支 Lambda 的 IAM 在 `infra/training_kb_stack.py`**（P41 建 `training-kb-pipeline-task`／`training-kb-webhook`，P42 加 `training-kb-import`，P54 加 `training-kb-analytics`）。缺的標 `not_run`。
3. **`check_secrets` 的範圍**：`git ls-files` 減 `docs/`／`.superpowers/`，範圍逐字寫進 `CheckResult.scope`。現況事實：`git check-ignore .env` 回 0（`.gitignore:10`）；**`.env.example` 沒有 `TKB_GITHUB_WEBHOOK_SECRET` 這一行**（只有三個 model／region 鍵）；`docs/plan/unfinish-claude/` 有 `TKB_GITHUB_WEBHOOK_SECRET=s3cr3t-value` 等**文件範例**（R8 禁止提交那個目錄）。「鍵完全沒出現」不是 finding；命中只印檔案＋行號（R11）。
4. **Snyk**：CLI 有裝（`/opt/homebrew/bin/snyk`，`1.1307.2`）但**沒認證**（`snyk config get api` 取不到 token）→ `snyk test` 以認證錯誤結束，不是 0 也不是 1。記 `not_run` ＋ 實際退出碼與錯誤原文。金鑰掃描與依賴掃描是兩種能力，分兩筆 `ScanRecord`。`pip-audit` **未安裝**。
5. **`check_output_safety` 不消費 `SYSTEM_GUARD`**（D-50，全套沒有這個名稱）；核對的是 `<source_data>` 分區與 `html.escape`。
6. **mypy `strict` 涵蓋 `infra/`**（`files = ["src","infra"]`）→ `checks.py` 全函式註記。`infra/scripts/` 無 `__init__.py` 但可 import（namespace package，`check_models` 已驗證）。
7. **168 = 4 + 9 + 147 + 6 + 2**。147 已用 `grep -c '^\s*Rule:' docs/spec/features/*.feature` 實測：17/14/10/8/9/10/31/6/10/7/12/5/8。縮寫 `REL TIC RUN APL REV VER ING PRP COL GPH MET PUB VAL`（**`COL` 不是 `FDB`**）。
8. **gate 現況決定哪些列不可能是 pass**：O5 BLOCKED（`o5-20260915T030245Z.md`，`ValidationException: Operation not allowed`）→ `AWS-MODELS`、所有 Bedrock 列與 rehearse 第 3 項 `not_run`；O3 FAIL（`o3-20260914t181109z.md`）→ `PUB` 4/5、S3 切片、Phase 59 recovery 列 `fail`；O6 4 列待核定（`o6-mapping.md`，**不要動 `tests/fixtures/o6/approved-sources.json`**）→ Release 與三個手動來源的 `ING` 列 `not_run`；O7／O4 未到；O1 provisional 不記 pass。
9. `check_public` 通過 ≠ O3 通過（前者是公開範圍，後者是切換原子性）。
10. `render_scan_report` 的未涵蓋範圍**字母排序**（測試斷言 `未涵蓋範圍：code、secrets`）。
11. 退出碼語意：Snyk 0 無發現／1 有發現／2 掃描失敗可重跑／3 沒有支援的專案；1 ≠ 失敗，2 與 3 ≠ 通過。

## 7. 需要裁決的點 → 建議
- **`check_secrets` 掃描範圍** → `git ls-files` 減 `docs/`／`.superpowers/`；範圍寫進 `scope`。理由：`unfinish-claude/` 的文件範例會製造假陽性並把疑似值印進報告。
- **`.env.example` 缺 `TKB_GITHUB_WEBHOOK_SECRET`** → **不要為了讓檢查有東西可查就改 `.env.example`**（§全域限制「不改產品程式碼讓檢查通過」）。把它寫成報告第 9 節的「建議」交給維護者；檢查把「鍵不存在」判成非 finding。
- **沒有 Snyk 認證** → (1) 仍記一筆真實執行的 `ScanRecord(tool="snyk", exit_code=<實際值>, covered=())` ＋ `CheckResult(status="not_run")`；(2) 另記一筆替代依賴掃描（`uv run --with pip-audit pip-audit`，或 GitHub advisory 查核紀錄），`tool` 寫實際工具名並在報告**明確標「非 Snyk」**，`covered=("dependencies",)`、`not_covered` 含 `secrets`／`code`。金鑰結論只引用 `check_secrets`。
- **147 列怎麼「可執行」** → Step 3A：逐列取 00B §2「可觀察 assertion」欄的測試檔路徑，斷言檔案存在 ＋ `pytest --collect-only -q` 的 nodeid 集合收得到（有寫函式名就連函式一起）；收不到 = `not_run`。發現 00B 與實際對不上，寫報告交 controller，**不改 00B**。
- **`check_iam` 缺 Lambda 時** → `not_run`（不是 `pass`，也不要放寬核對表；要改核對表得回 P09）。

## 8. 對 AWS 的實際操作
- Region **固定 `us-east-1`**。帳號 `123456789012`，bucket `training-kb-content-example`。
- `aws s3api get-bucket-policy --region us-east-1 --bucket <bucket>` 讀回實際 policy 與 CDK template 比對（人工驗收要求）。
- AWS 六列：三條 state machine 各一次真實 execution ARN（`aws stepfunctions describe-execution`）、webhook 正確／錯誤簽名各一次 `curl`、`AWS-MODELS` 模型可用性報告（**O5 BLOCKED → `not_run`**）。
- 瀏覽器兩列：公開站版本頁與退役頁截圖，網址是 **HTTP** website endpoint `http://<bucket>.s3-website-us-east-1.amazonaws.com/...`（報告不得寫 HTTPS、不得承諾免費或固定金額）。
- 證據檔：`docs/plan/report/evidence.json`（`row_id` → 路徑／ARN／截圖檔名，或 `"fail:<原因>"`）、`acceptance-<時間>.md`、`snyk-<時間>.md`；報告 `docs/plan/report/phases/2026-09-14-Phase60-REP.md`。
- 不提交 `cdk.out/`、outputs／憑證檔、`docs/spec/**`、`docs/plan/unfinish-claude/`；`git add` 只加自己的路徑。
