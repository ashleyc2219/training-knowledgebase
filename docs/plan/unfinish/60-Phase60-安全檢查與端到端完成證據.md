# Phase 60：安全檢查與端到端完成證據實作計畫

> **給實作者：** 依 checkbox 逐步執行；每個 Task 先建立失敗測試，再寫最小實作。執行時使用 `superpowers:executing-plans` 或同等逐項流程。

> **現況核對（2026-09-14，Phase 41–60 批次 W0）：**
>
> **（a）已存在、可直接重用（file:function）**
> - `infra/training_kb_data_stack.py`：`TABLE_NAME`、`TARGET_INDEX`、`PRIVATE_PREFIXES = ("tutorials/", "operations/", "stepfunctions/", "demo/previews/")`、`TrainingKbDataStack`。**`s3:ListBucket` 的 `s3:prefix` 條件已經存在**（`StringLike` + 四個私有前綴），`check_iam` 是回歸守門而不是首次導入。
> - `tests/unit/test_data_stack.py`：`synth()`（`Template.from_stack(TrainingKbDataStack(cdk.App(), "TrainingKbData"))`）、`test_data_role_has_no_wildcard_action_or_resource`、`test_s3_statement_covers_every_private_prefix_and_never_site`、`test_list_bucket_is_limited_to_the_private_prefixes`——**這三個測試就是 `check_iam` 三條硬性規則的既有形狀**，照它們的判準寫 `check_iam`，但**不得修改這支別人的測試檔**（R3.6）。它第 64 行的註解也已經記下本 Phase 最容易踩的坑（下面 b3）。
> - `infra/scripts/check_models.py`：`infra/scripts/` 底下**唯一一支完整型別註記、mypy strict 過關**的 CLI，`main(argv: Sequence[str] | None = None) -> int`、`REPORT_DIR = Path(__file__).resolve().parents[2] / "docs" / "plan" / "report"`——`checks.py` 照它的骨架寫。
> - `src/training_kb/adapters.py`：`TOOL_NAMES`（`frozenset[str]`，**八個**：`parse_github_issue`／`parse_discord_message`／`parse_support_email`／`parse_pr_diff`／`parse_changelog`／`normalize_ticket`／`normalize_release`／`validate`）、`FINAL_TOOL`、`ToolRegistry`。
> - `src/training_kb/writing/prompts.py`：`_as_data(text)`（實作是 `html.escape(text, quote=False)`，**module-private**）與 `<source_data>` 分區；截至 W0 只有 `prompt_write_tutorial`、`prompt_name_gap` 兩支，本批次的 P43／P45／P46／P47／P50／P51 會再加——所以 `check_output_safety` **要動態列舉**（`[name for name in dir(prompts) if name.startswith("prompt_")]`），不得寫死清單。
> - `src/training_kb/handlers/github_webhook.py:load_secret()`：讀 `TKB_GITHUB_WEBHOOK_SECRET` 的唯一位置。
> - `src/training_kb/site.py`：`SiteRenderer.render_version_page(tutorial, version, steps, content) -> str`（四個位置參數）；`escape_text`／`SITE_PREFIX`／`ASSET_KEYS`／`site_diff_key` 由 **P57** 補上。
> - 已存在的 gate 報告（證據索引可以直接指）：`docs/plan/report/o2-20260914t182824z.md`、`o3-20260914t181109z.md`、`o5-20260914T170050Z.md`、`o5-20260915T030245Z.md`、`o6-mapping.md`；O4／O7 的報告由 P54／P56 在本批次產生。各 Phase 報告在 `docs/plan/report/phases/`。
> - `docs/spec/features/` 共 **13** 份 `.feature`，`grep -c '^\s*Rule:'` 合計 **147**（2026-09-14 實測，與 00B §1 統計表一致）。縮寫依 00B §1：`REL`／`TIC`／`RUN`／`APL`／`REV`／`VER`／`ING`／`PRP`／`COL`／`GPH`／`MET`／`PUB`／`VAL`（`收集教學回饋` 統一 `COL`，不用 `FDB`）。
>
> **（b）因上一批裁決／實作而修正的點**
> 1. **`check_iam` 要讀兩份 template。** `PRIVATE_PREFIXES` 與資料角色在 `infra/training_kb_data_stack.py`（P09），但**四支 Lambda 的 IAM 在 `infra/training_kb_stack.py`**——P41 建檔並加 `training-kb-pipeline-task`／`training-kb-webhook`，**P42 加 `training-kb-import`、P54 加 `training-kb-analytics`**（00A §3.2、D-58）。四支核對表要等這三個 Phase 都完成才驗得完；缺的那幾支在報告標 `not_run`，不是 `pass`。
> 2. `TOOL_NAMES` 的模組是 `training_kb.adapters`（§5 原文只寫「Phase 36」，沒寫模組）。
> 3. **`check_iam` 只能掃 `AWS::IAM::Policy`／`AWS::IAM::Role` 的 `Effect: Allow` 陳述。** P09 目前 `enforce_ssl=True`，CDK 會產生一條 bucket policy 的 **`Deny` `s3:*`**（條件 `aws:SecureTransport=false`）；整份 template 字串比對 `"s3:*"` 會誤判成違規。P57 會把 `enforce_ssl` 改成 `False`（00A §3.2 的 P09 列），但檢查在兩種情況下都必須正確。`tests/unit/test_data_stack.py` 第 64 行的註解就是這件事。
> 4. **`check_secrets` 的掃描範圍要收斂。** 現況：`git check-ignore .env` 回 0（命中 `.gitignore:10`）；**`.env.example` 目前完全沒有 `TKB_GITHUB_WEBHOOK_SECRET` 這一行**（只有 `TKB_BEDROCK_REGION`／`TKB_EMBEDDING_MODEL_ID`／`TKB_GENERATION_MODEL_ID`）；而 `docs/plan/unfinish-claude/`（**維護者自己進行中的舊稿，R8 禁止提交**）裡有 `TKB_GITHUB_WEBHOOK_SECRET=s3cr3t-value`、`"TKB_GITHUB_WEBHOOK_SECRET": "local-test-secret"` 這類**文件範例**。**本計畫選擇：** 掃描範圍用 `git ls-files` 的追蹤檔，排除 `docs/` 與 `.superpowers/`；`.env.example` 只認鍵名或佔位字；「這個鍵在 repo 內完全沒出現」**不是** finding。範圍與排除清單要逐字寫進 `CheckResult.scope`，讓人看得出來掃了什麼、沒掃什麼。
> 5. **Snyk 的實際可用性（2026-09-14 實測）：** CLI **有裝**（`/opt/homebrew/bin/snyk`，版本 `1.1307.2`），但**沒有認證**（`snyk config get api` 取不到 token），所以 `snyk test` 會以認證錯誤結束，既不是 0 也不是 1。照 §6 的規則記成 `not_run` ＋ 實際退出碼與錯誤原文，**不得改寫成通過**。金鑰掃描（Snyk Secrets）與依賴掃描（Snyk Open Source）是**兩種能力**，分開記；沒有 Snyk 認證時的替代依賴掃描見 Task 2 Step 4 的補充（`pip-audit`／GitHub advisory，**必須明確標「非 Snyk」**，且 `pip-audit` 目前**未安裝**）。
> 6. **型別與可匯入性。** `infra/scripts/` 沒有 `__init__.py`（namespace package），但 `infra/__init__.py` 存在，所以 `from infra.scripts.checks import ...` 與 `uv run python -m infra.scripts.checks ...` 都成立（`check_models.py` 就是這樣被 `tests/unit/test_check_models.py` 使用）。**`pyproject.toml` 的 mypy 是 `strict = true` 且 `files = ["src", "infra"]`**，所以 `checks.py` 每個函式都要完整註記；§7 的片段為了易讀省略了註記。
> 7. `SUBCOMMANDS` 這個名字在 P58 的 demo CLI 也有一份（值不同）。兩者**在不同檔**（`demo/` vs `infra/scripts/checks.py`，00A §6 已註明），不得互相 import。
> 8. 168 = 4（V1–V4）+ 9（S0–S8）+ 147（Rule）+ 6（AWS）+ 2（瀏覽器），與實測的 147 相符，數字不用改。
>
> **（c）gate 現況對本 Phase 的影響（`.superpowers/sdd/phase0914-2/COMMON.md` §2）**
> - **O5 = BLOCKED**（重 probe：Titan／Claude 都仍 `ValidationException: Operation not allowed`；報告 `docs/plan/report/o5-20260915T030245Z.md`）。`AWS-MODELS` 那一列與 Task 3 預演第三項（小量模型呼叫）**只能是 `not_run`**，證據指向那份報告與錯誤原文；`TKB_GENERATION_MODEL_ID` 維持空白，不填猜測值。
> - **O3 = FAIL**（P12，報告 `docs/plan/report/o3-20260914t181109z.md`；P24／P25 已在 moto 重現切點，P59 在真實 AWS 重跑）。與發布切換有關的列（`PUB` 4、5、S3 切片、Phase 59 的 recovery 報告列）要**如實標 `fail`**，不得因為 `check_public` 通過就推論 O3 通過——那是兩件事（前者是公開範圍，後者是切換原子性）。
> - **O6 有 4 列待維護者核定**（11 個 `xfail(strict=True)` 站崗；`tests/fixtures/o6/approved-sources.json` **不得動**）。Release 與三個手動來源走不進 Rote，相關 `ING` 列與 Release 端到端列標 `not_run`，證據指向 `o6-mapping.md`。
> - **O7 未到**（P56 首次核定）：`程式重算成功 ≠ 維護者核定`；缺 `demo/seed/approvals/<batch_id>.json` 的核定紀錄就是 `not_run`。**O4 未到**（P54 首驗）。**O1 provisionally accepted（D-71）**：記成 provisional，不記 pass。
> - 一句話：**未執行的檢查不得標 green**；`not_run` 不是警告，是不通過。
>
> **（d）適用的 controller 裁決（`.superpowers/sdd/phase0914-2/COMMON.md`）**
> - **R1 這一批真的接 AWS**：AWS 六列與瀏覽器兩列要有真實 `us-east-1` 的 ARN／HTTP 回應／截圖，做不到的標 `not_run`（O5／O6 造成的就註明 gate）。CLI 一律帶 `--region us-east-1`。
> - **R3 同檔併行**：本 Phase 在 W5（最後），`infra/scripts/checks.py` 只有本 Phase 動；`git add` 只加自己的檔案路徑，不 `git add -A`。
> - **R8 絕不提交**：`docs/spec/**`、`docs/plan/dev-prompts/phase0914-1.md`、`ticket-to-knowledge-design-doc.md`、`docs/plan/unfinish-claude/`、`cdk.out/`、任何 outputs／憑證檔。
> - **R10 需要維護者決定的事自己裁決並標「本計畫選擇」**；**R11 安全**：不把任何金鑰、帳號憑證、bucket 內容寫進 repo，`check_secrets` 命中時只印檔案與行號。
> - **不改 00／00A／00B**（W0 指令 D）：發現它們有錯寫進報告，由 controller 統一處理。
>
> **（e）本計畫選擇（2026-09-15，Phase 60 實作）**
> 1. **`evidence.json` 多一個 `not_run:<原因>` 前綴。** 原文只定義「有值＝pass、`fail:<原因>`＝fail、缺值＝not_run」，但 §7 Task 4 Step 4 又要求「`AWS-MODELS` → `not_run`，證據指 `o5-20260915T030245Z.md`」——缺值就印不出 gate 報告位置。`not_run:` 前綴讓那一列**仍然是 `not_run`**（不進 pass、整體布林仍是 `False`），同時看得到該查哪一份報告。`_row_status` 是唯一判讀處，`tests/unit/test_acceptance.py::test_not_run_prefix_keeps_the_gate_pointer` 站崗。
> 2. **`check_iam` 與四支 Lambda 核對表拆成兩支函式。** `check_iam(template)` 只做三條硬性規則（簽名照 00A），四支 Lambda 的核對表放 `check_lambda_inventory(template)`；後者**只對 `TrainingKbApp` 跑**——四支 Lambda 全在流程 stack（00A §3.2、D-58），對資料 stack 跑只會產生一筆恆定的 `not_run` 雜訊，看報告的人會以為少了什麼。
> 3. **新增 `deploy_checklist()`（五項部署前守門）。** `TKB_ENV=prod`、`TKB_FAULT`／`TKB_FAULT_TASK` 未設、layer `is_built()`、`check_asl` 不帶參數退出碼 0、bucket policy 只 `site/*`。前三項是 P59 報告 §7「請 P60 的 `check_secrets`／部署清單列這三項」交下來的，但它們是**部署前**的事、不是金鑰掃描的事，硬塞進 `check_secrets` 會讓那支檢查的 `scope` 說不清楚。`checks teardown` 會把它跟停用清單一起印。
> 4. **`check_output_safety` 只把惡意文字塞進「不可信」參數。** `VALIDATED_PARAMETERS`（`allowed_features`／`approved`／`rules_block`／`targets`／`version_id`／`feedback_ids`）是 prompts.py 各支 docstring 明寫的「程式產生的已驗證值」，餵乾淨值；其餘（工單原文、回饋留言、步驟文字、改版說明）一律餵 `HOSTILE_TEXT`。理由：核定類別表走 `json.dumps` 不經 `_as_data`，把惡意文字塞進去測到的是「程式自己攻擊自己」，不是注入風險。
> 5. **`sts:GetCallerIdentity` 的 `Resource: "*"` 記成 `fail`，不放寬核對表。** 見報告第 9 節，交 controller 裁決。
> 6. **瀏覽器兩列用 Playwright 實際截圖**，存 `docs/plan/report/screenshots/p60-web-{version,retired}.png`，證據欄同時寫截圖路徑與 **HTTP** website endpoint 網址。
> 7. **P12 spike 殘留 `site/tutorials/spike-a/v2.html`（5 bytes、公開可讀）先記錄再刪除**（controller 2026-09-15 裁決：那是 O3 spike 的一次性物件，不屬於任何教學）。刪除前後狀態見報告第 2 節。其餘 demo 物件（`demo-site-check`、`demo-p52-*`）保留並列進索引。

**目標：** 把四支靜態安全檢查、Snyk 紀錄、Demo 前預演與結束後停用清單，以及 S0–S8 與 147 條 Rule 的證據索引，接成一份可以被人逐項查證的最終驗收；沒有實際執行的項目一律不得標成 green。

**架構：** 所有檢查都住在同一支 `infra/scripts/checks.py`，以子命令分開跑；每支檢查回傳同一個 `CheckResult`，`status` 只有 `pass`、`fail`、`not_run` 三種，沒有第四種樂觀值。證據索引從外部 JSON 讀入，缺證據就是 `not_run`，整份報告因此不通過。腳本只讀 repo、CDK template 與 bucket policy，不修改任何產品程式。

**技術：** Python 3.12、pytest、boto3、AWS CDK assertions、`git check-ignore`、Snyk CLI。

## 全域限制

- 唯一主來源是 [Training KB 設計 §3、§15、§16、§17、§18](../../design/training-kb.md)。
- 前置為 [Phase 59：失敗復原與重送驗收](./59-Phase59-失敗復原與重送驗收.md)；證據索引另外指向 [Phase 12](./12-Phase12-O3發布切換整合驗證.md)、[Phase 13](./13-Phase13-O6來源ID與穩定使用者契約.md)、[Phase 14](./14-Phase14-O5模型可用性與參數驗證.md)、[Phase 56](./56-Phase56-O7核定Demo種子資料.md) 的 gate 報告，並讀 [Phase 09](./09-Phase09-AWS資料資源與最小IAM.md) 的 `PRIVATE_PREFIXES`、[Phase 57](./57-Phase57-S3靜態教學站與回饋下載.md) 的 bucket policy 與 renderer。前置未通過時停止。
- **本批次（Phase 41–60）把本 Phase 排在最後一波 W5**（現況核對 2026-09-14）：`check_iam` 的四支 Lambda 核對表另外依賴 [Phase 41](./41-Phase41-Ticket-Analysis雲端流程驗收.md)（建 `infra/training_kb_stack.py` 與前兩支 Lambda）、[Phase 42](./42-Phase42-Feedback與View固定匯入.md)（`training-kb-import`）、[Phase 54](./54-Phase54-重開票與呼叫規則指標.md)（`training-kb-analytics`）；`check_output_safety` 依賴 P57 的 renderer 與本批次各 Phase 加進 `writing/prompts.py` 的 `prompt_<node>`。缺哪一項就在報告標 `not_run`，不補洞、也不放寬檢查。
- 這是最後一個 Phase；完成後回到 [00 總覽](./00-總覽.md) 的完成判定，並以 [00B 需求覆蓋對照](./00B-需求覆蓋對照.md) 作為每條 Rule 的 primary 與追驗 Phase 依據。
- 本階段不做：不改產品程式碼讓檢查通過；不新增任何 AWS 服務；不代替維護者做帳號設定、費用決策或資源刪除；不重新裁決哪個 Phase 擁有哪條 Rule。
- 與本 Phase 有關的 O1–O7 gate 狀態（**2026-09-14 現況，不是「待驗證」**）：**O1** provisionally accepted（D-71，記 provisional 不記 pass）；**O2 = PASS**（P11）；**O3 = FAIL**（P12，`docs/plan/report/o3-20260914t181109z.md`）；**O4** 未到（P54 首驗）；**O5 = BLOCKED**（`docs/plan/report/o5-20260915T030245Z.md`，Titan／Claude 都仍 `ValidationException: Operation not allowed`）；**O6** 4 列待核定（11 個 `xfail(strict=True)` 站崗）；**O7** 未到（P56 首驗，程式重算成功 ≠ 維護者核定）。O1–O7 只要有一項沒有真實證據，最終驗收就是「未完成」。本 Phase 只彙整別人的證據，**不得代替 Phase 12／13／14／56 宣布任何 gate PASS**，也不得把 CDK synth、Markdown 連結檢查或 DBML／Gherkin parser 成功寫成 runtime 通過。
- **真實 AWS 這一批要接（controller R1）**：AWS 六列與瀏覽器兩列必須是真實 `us-east-1` 的 execution ARN、`describe-execution` 輸出、webhook 的 HTTP 回應與公開站截圖；`check_public` 的人工核對要用實際帳號 `aws s3api get-bucket-policy --region us-east-1` 讀回來比對 CDK template。做不到的部分（Bedrock、Release 端到端）**標 BLOCKED 並附實際錯誤原文，不填猜測值、不假裝通過**。公開網址是 **HTTP** website endpoint，報告不得寫成 HTTPS。
- 本 Phase 沒有 primary Rule：00B 把 P25、P41、P59、P60 列為驗收型，第 10 節的 Rule 一律是「相關」，直接斷言在各自的 primary Phase。
- 以下程式檔均是實作時預計建立或修改；本計畫本身不代表它們已存在。

---

## 1. 你在整體流程的位置

```text
Phase 01-59 的測試、報告與雲端執行紀錄
        |
        v
  [你在這裡] Phase 60 彙整：infra/scripts/checks.py 的五個子命令
        |
   +----+-----------------+-------------------+
   |                      |                   |
security（四支靜態檢查）  scan（Snyk 紀錄）    rehearse／teardown
check_secrets             dependency          預演四項
check_iam                 vs secrets          停用清單
check_public              分開記錄               |
check_output_safety        |                     |
   |                       |                     |
   +----------+------------+---------------------+
              v
      acceptance 子命令
      V1-V4 + S0-S8 + 147 Rule + AWS／瀏覽器 evidence
              |
     全部有證據？ -- 否 --> 報告標 not_run，最終驗收未完成
              |
             是
              v
   可以說「本次交付的範圍已留下證據」
```

## 2. 完成後看得到什麼

```text
$ uv run python -m infra.scripts.checks acceptance docs/plan/report/evidence.json
[pass]     V1         缺口產生教學       追驗 P38、P41、P24
           evidence: site/tutorials/prepare-meeting/v1.html
[pass]     S8         兩條循環與失敗復原  追驗 P57-P60
           evidence: docs/plan/report/recovery-20260913-1120.md
[not_run]  AWS-MODELS O5 模型與參數      追驗 P14
           evidence: （缺）
[not_run]  RUN#10     ASL 版本快照       追驗 P41、P52
           evidence: （缺）
總計 rows=168 pass=154 fail=0 not_run=14  -> 最終驗收未完成
文件 parser 成功不等於 runtime 通過。
```

`not_run` 不是警告，是不通過。168 列 = 設計 §3 的四個可見結果（V1–V4）＋ §16 的九個切片（S0–S8）＋ 十三份 `.feature` 的 147 條 Rule ＋ AWS 六列與瀏覽器兩列。每一列的「追驗 Phase」抄自 00B 第 2 節的「其他相關 Phase」欄，不在這裡重新裁決。

## 3. 名詞小抄

| 名詞 | 白話意思 |
|---|---|
| `CheckResult` | 每支檢查的統一結果：名稱、狀態、掃描範圍、發現清單。 |
| `not_run` | 這項根本沒跑；不能當成通過，也不能當成失敗。 |
| `git check-ignore` | Git 內建指令，回答「這個檔案有沒有被 ignore 規則命中」。 |
| Snyk Open Source | 掃第三方依賴的已知漏洞；不等於掃金鑰。 |
| Snyk Secrets | 另一項獨立能力，需要組織啟用；沒跑就不能說金鑰掃描通過。 |
| 最小權限 | 執行角色只拿到需要的模型、表、S3 前綴與流程，不用萬用字元。 |
| 追驗 Phase | 這條 Rule 的直接斷言不在本 Phase，而是由 00B 的「其他相關 Phase」在整合情境再驗一次。 |
| runbook | Demo 當日的逐項操作腳本，含時間、指令與預期畫面。 |

## 4. 預計檔案

| 動作 | 路徑 | 責任 |
|---|---|---|
| 建立 | `infra/scripts/checks.py` | 本 Phase 的唯一腳本（00A 第 3.2 節）：`CheckResult`、四支靜態檢查、`run_all`、Snyk 紀錄、預演與停用清單、證據索引，以及 `security`／`scan`／`rehearse`／`teardown`／`acceptance` 五個子命令。 |
| 測試 | `tests/unit/test_security_checks.py` | 四支靜態檢查與 Snyk 紀錄。 |
| 測試 | `tests/unit/test_acceptance.py` | 預演、停用清單與 168 列證據索引。 |
| 產出 | `docs/plan/report/evidence.json` | 證據輸入：`row_id` 對應檔案路徑、ARN 或截圖檔名。 |
| 產出 | `docs/plan/report/snyk-<時間>.md`、`acceptance-<時間>.md` | 掃描紀錄與最終驗收報告。 |

## 5. 固定介面

### Consumes

```text
TABLE_NAME / TARGET_INDEX / PRIVATE_PREFIXES（四個私有前綴）
    TrainingKbDataStack（在 infra/training_kb_data_stack.py）        # Phase 09
CDK Template.from_stack(stack).to_json() -> dict                     # Phase 09
TrainingKbStack（在 infra/training_kb_stack.py；四支 Lambda 的 IAM）  # Phase 41、42、54
TKB_GITHUB_WEBHOOK_SECRET（執行期開關，不是 Settings 欄位）
    handlers/github_webhook.py:load_secret() 是唯一讀取點             # Phase 30
writing/prompts.py 的 _as_data（module-private，html.escape(text, quote=False)）
    與 <source_data> 分區標記；prompt_<node> 要動態列舉               # Phase 17 起
TOOL_NAMES（training_kb.adapters，frozenset，八個）/ FINAL_TOOL /
    ToolRegistry                                                     # Phase 36
SiteRenderer.render_version_page(tutorial, version, steps, content) -> str
                                                                     # Phase 24 簽名、Phase 57 實作
SITE_PREFIX / ASSET_KEYS / escape_text / site_diff_key（在 site.py）  # Phase 57
bucket policy（實際部署後以 get_bucket_policy 讀回）                  # Phase 57
docs/plan/report/recovery-<時間>.md                                  # Phase 59
O1–O7 的 gate 報告（O2／O3／O5 已存在；O4／O7 由 P54／P56 產生）       # Phase 11-14、54、56
147 條 Rule 的 primary 與「其他相關 Phase」欄、13 個縮寫              # 00B §1、§2
S0–S8 對照（00B §4）、V1–V4 四個可見結果（00B §6）                    # 00B
```

（現況核對 2026-09-14：原文沒寫 `TOOL_NAMES` 的模組（是 `training_kb.adapters`，不是 `rote.py`）、沒寫四支 Lambda 的 IAM 在另一份 stack、`render_version_page` 的四個參數與 `_as_data` 是 module-private；`site_diff_key` 一併補上。）

### Produces

```python
CheckStatus = Literal["pass", "fail", "not_run"]
SUBCOMMANDS = ("security", "scan", "rehearse", "teardown", "acceptance")

@dataclass(frozen=True)
class CheckResult:
    name: str
    status: CheckStatus
    scope: str
    findings: tuple[str, ...]

def check_secrets(root: Path) -> CheckResult: ...
def check_iam(template: Mapping[str, object]) -> CheckResult: ...
def check_public(bucket_policy: Mapping[str, object]) -> CheckResult: ...
def check_output_safety() -> CheckResult: ...
def run_all(results: Sequence[CheckResult]) -> int: ...

@dataclass(frozen=True)
class ScanRecord:
    tool: str
    version: str
    command: str
    scope: str
    exit_code: int
    covered: tuple[str, ...]
    not_covered: tuple[str, ...]

def render_scan_report(records: Sequence[ScanRecord], *, claim: str = "") -> str: ...

@dataclass(frozen=True)
class EvidenceRow:
    row_id: str
    group: Literal["visible", "slice", "rule", "aws", "browser"]
    description: str
    owner_phase: str
    verify_phases: tuple[str, ...]

ACCEPTANCE_ROWS: tuple[EvidenceRow, ...]

def load_evidence(path: Path) -> dict[str, str]: ...
def acceptance_report(rows: Sequence[EvidenceRow],
                      evidence: Mapping[str, str]) -> tuple[str, bool]: ...
def rehearse_steps() -> tuple[str, ...]: ...
def teardown_checklist() -> tuple[str, ...]: ...
def main(argv: Sequence[str] | None = None) -> int: ...
```

`acceptance_report` 回傳報告文字與一個布林；布林只有在沒有任何 `fail` 也沒有任何 `not_run` 時才是 `True`。`EvidenceRow.owner_phase` 是 00B 的 primary Phase，`verify_phases` 是同一列的「其他相關 Phase」，兩者都只抄不裁決。

## 6. 設計細節

公開與私有的界線在 [Phase 57](./57-Phase57-S3靜態教學站與回饋下載.md) 決定，本 Phase 只負責查核：

```text
  公開（bucket policy 只對 site/* 授權 s3:GetObject，Principal "*"）
    site/index.html、site/assets/style.css、site/assets/widget.js
    site/tutorials/<slug>/index.html、v<n>.html、v<n>.diff.txt
  私有（沒有任何公開授權）
    tutorials/（含未發布）、operations/（模型輸出、回饋原文、穩定使用者 ID）
    stepfunctions/、demo/previews/        <- PRIVATE_PREFIXES 這四個前綴
  DynamoDB：完全私有，沒有公開讀取路徑
  平台限制：website endpoint 只有 HTTP；報告不得寫成 HTTPS 網站
```

`check_public` 解析 bucket policy 的每個 Allow 陳述，取出被公開授權的前綴集合，只要出現 `site/` 以外的前綴、或 `Resource` 是整桶 `/*`、或 Action 不是只有 `s3:GetObject`，就回 `fail` 並列出違規陳述的 `Sid`。

`check_iam` **只掃 `AWS::IAM::Policy` 與 `AWS::IAM::Role` 兩種資源、而且只看 `Effect: "Allow"` 的陳述**（現況核對 2026-09-14）：Phase 09 目前 `enforce_ssl=True`，CDK 會多產生一條 bucket policy 的 `Deny s3:*`（條件 `aws:SecureTransport=false`），整份 template 做字串比對會把它誤判成萬用字元違規；`tests/unit/test_data_stack.py` 第 64 行已經記下同一個坑。P57 會把 `enforce_ssl` 改成 `False`（S3 website endpoint 只有 HTTP），檢查在兩種情況下都要正確。另外 **template 有兩份**：`TrainingKbDataStack`（P09，資料角色）與 `TrainingKbStack`（P41 建、P42／P54 擴充，四支 Lambda 的執行角色），兩份都要掃；任何一份還不存在就把對應的核對列記成 `not_run`，不是 `pass`。

`check_iam` 用下面這張核對表比對 CDK template，三條硬性規則違反即 `fail`：不得出現 `"Action": "*"` 或 `dynamodb:*`／`s3:*`／`bedrock:*`／`states:*`；不得出現 `"Resource": "*"`（唯一例外是本身不支援限定 ARN 的 CloudWatch Logs 建立群組）；Demo 的 CLI 與 Streamlit 用維護者本人的身分，不另外建立帶寫入權限的長期金鑰。Lambda 就是下面四支（00A 第 3.5 節），出現第五支即 `fail`。

| Lambda | DynamoDB | S3 物件 | `s3:ListBucket` | Bedrock | Step Functions |
|---|---|---|---|---|---|
| `training-kb-webhook` | 表與 `by_target` 讀寫 | `operations/` 讀寫 | 限 `operations/` | embedding 與生成各一 | 啟動 `training-kb-ticket-analysis`、`training-kb-release-update` |
| `training-kb-import` | 同上 | `operations/` 讀寫 | 限 `operations/` | 生成一個 | 同上 |
| `training-kb-pipeline-task` | 同上 | `tutorials/`、`site/`、`operations/`、`stepfunctions/` 讀寫 | 限四個私有前綴 | embedding 與生成各一 | 不啟動 |
| `training-kb-analytics` | 同上 | `operations/` 讀 | 限 `operations/` | 生成一個 | 不啟動 |

`s3:ListBucket` 只授權在 bucket ARN 上，並用 `s3:prefix` 條件限定 `PRIVATE_PREFIXES` 的四個前綴；[Phase 07](./07-Phase07-S3物件與關係邊讀寫.md) 的 `get_object` 在真實 S3 要靠它才會把「物件不存在」回成 `None` 而不是 403。`site/` 不在這個條件裡：公開讀取由 bucket policy 負責，執行角色不需要列出公開前綴。

`check_output_safety` 做兩件事（00A 裁決 D-50）：把含 `<script>`、`onerror=`、`javascript:` 的惡意文字餵進 Phase 57 的 renderer，斷言輸出裡這些片段只以跳脫後的純文字出現；再逐一呼叫 `writing/prompts.py` 的每個 `prompt_<node>`，斷言不可信文字被 `html.escape(text, quote=False)` 轉義後包在成對且唯一的 `<source_data>`／`</source_data>` 內，且工具名稱不超出 Phase 36 的 `TOOL_NAMES`。本 Phase **不**消費任何叫 `SYSTEM_GUARD` 的常數，全套文件沒有這個名稱。

`check_secrets` 的**掃描範圍**要收斂並逐字寫進 `CheckResult.scope`（現況核對 2026-09-14，**本計畫選擇**）：範圍是 `git ls-files` 的追蹤檔，排除 `docs/` 與 `.superpowers/`。理由是 `docs/plan/unfinish-claude/`（維護者自己進行中的舊版計畫稿，controller R8 禁止本批次提交）裡有 `TKB_GITHUB_WEBHOOK_SECRET=s3cr3t-value` 這類**文件範例**，掃進去只會製造假陽性、還會把疑似值印進報告。同時記下三個現況事實：`git check-ignore .env` 回 0（命中 `.gitignore` 第 10 行）；`.env.example` 目前**沒有** `TKB_GITHUB_WEBHOOK_SECRET` 這一行——「這個鍵在範圍內完全沒出現」**不是** finding，「出現且帶非佔位值」才是；命中時只印檔案與行號，不回印命中的字串本身（R11）。

Snyk 的界線照設計 §17.1：`snyk test` 掃依賴、`snyk code test` 掃自己的程式碼、Snyk Secrets 是另一項需要組織啟用的能力。**本機現況（2026-09-14 實測）：CLI 有裝（`/opt/homebrew/bin/snyk`，`snyk --version` = `1.1307.2`），但沒有認證（`snyk config get api` 取不到 token）**，所以 `snyk test` 會以認證錯誤結束，退出碼既不是 0 也不是 1；照下面的規則記 `not_run` ＋ 實際退出碼與錯誤原文，不得改寫成通過。`render_scan_report` 內建拒絕條件：`covered` 不含 `secrets` 時，`claim` 若宣稱「secrets scan 通過」就直接拋錯不輸出。退出碼 0 是完成且無發現、1 是完成且有發現、2 是掃描失敗可重跑、3 是沒有偵測到支援的專案；1 不等於掃描失敗，2 與 3 不等於通過。

## 7. TDD Tasks

### Task 1：四支靜態檢查與共用結果格式

- [x] **Step 1：建立失敗測試**

```python
# tests/unit/test_security_checks.py
from infra.scripts.checks import CheckResult, check_iam, check_public, run_all

def test_check_public_rejects_whole_bucket(policy_factory):
    result = check_public(policy_factory(resource="arn:aws:s3:::b/*"))
    assert result.status == "fail"
    assert any("/*" in item for item in result.findings)

def test_check_public_accepts_site_prefix_only(policy_factory):
    policy = policy_factory(resource="arn:aws:s3:::b/site/*")
    assert check_public(policy).status == "pass"

def test_check_iam_rejects_wildcards(template_with_policy):
    result = check_iam(template_with_policy(actions=["dynamodb:*"], resource="*"))
    assert result.status == "fail" and len(result.findings) >= 2

def test_check_iam_requires_list_bucket_to_be_prefix_scoped(template_with_policy):
    result = check_iam(template_with_policy(actions=["s3:ListBucket"], resource="arn:aws:s3:::b"))
    assert result.status == "fail"
    assert any("s3:prefix" in item for item in result.findings)

def test_run_all_treats_not_run_as_failure():
    results = [CheckResult("a", "pass", "src", ()),
               CheckResult("b", "not_run", "snyk", ("未取得權限",))]
    assert run_all(results) != 0
```

- [x] **Step 2：執行並確認紅燈**

```bash
uv run pytest tests/unit/test_security_checks.py -q
```

預期：FAIL，訊號包含 `No module named 'infra.scripts.checks'`。

- [x] **Step 3：建立最小實作**

`CheckResult` 是 frozen dataclass；`run_all` 印出每筆結果並在出現任何 `fail` 或 `not_run` 時回非 0。`policy_factory`／`template_with_policy` 是同檔的 fixture，各自產生一份只含單一 Allow 陳述的最小 policy 與 CDK template。`check_secrets` 先跑 `git check-ignore .env`（回傳碼 0 才算被忽略，否則列為 finding），再以固定正規表達式掃 `AKIA[0-9A-Z]{16}`、`gh[pousr]_[A-Za-z0-9]{36,}`、`-----BEGIN [A-Z ]*PRIVATE KEY-----`，並確認 `TKB_GITHUB_WEBHOOK_SECRET` 在 repo 內只出現在 `.env.example` 這種只有鍵名的位置、值是佔位字；命中即 `fail` 並只印檔案與行號，不回印命中的字串本身。`check_iam` 的 `s3:ListBucket` 陳述必須帶 `Condition` 的 `s3:prefix`，且值是 `PRIVATE_PREFIXES` 的子集，否則列為 finding。

- [x] **Step 4：補 `check_output_safety` 並跑綠燈**

加入惡意文字案例與 prompt 分區案例：斷言渲染輸出不含未跳脫的 `<script`、`onerror=`、`javascript:`；斷言每個 `prompt_<node>` 的 user 段落內 `<source_data>` 與 `</source_data>` 各恰好出現一次，偽造的結束標記已被轉義成 `&lt;/source_data&gt;`。執行 `uv run pytest tests/unit/test_security_checks.py -q`，預期整個檔案全綠。

- [x] **Step 5：提交** — `git add infra/scripts/checks.py tests/unit/test_security_checks.py` 後 `git commit -m "feat(infra): 四支靜態安全檢查"`。

### Task 2：Snyk 依賴與 secrets 分開紀錄

- [x] **Step 1：建立失敗測試**

```python
import pytest

from infra.scripts.checks import ScanRecord, render_scan_report

def test_report_records_version_scope_and_exit_code():
    record = ScanRecord(tool="snyk", version="1.1298.0", command="snyk test",
                        scope="pyproject.toml 的直接與間接依賴", exit_code=1,
                        covered=("dependencies",), not_covered=("secrets", "code"))
    text = render_scan_report([record])
    assert "1.1298.0" in text and "snyk test" in text
    assert "掃描完成，有發現問題" in text
    assert "未涵蓋範圍：code、secrets" in text

def test_report_refuses_unsupported_claim():
    record = ScanRecord(tool="snyk", version="1.1298.0", command="snyk test",
                        scope="依賴", exit_code=0, covered=("dependencies",),
                        not_covered=("secrets",))
    with pytest.raises(ValueError, match="secrets"):
        render_scan_report([record], claim="secrets scan 通過")
```

- [x] **Step 2：執行並確認紅燈**

```bash
uv run pytest tests/unit/test_security_checks.py -q
```

預期：FAIL，訊號包含 `cannot import name 'render_scan_report'`。

- [x] **Step 3：建立最小實作**

`render_scan_report` 輸出一張表（工具、CLI 版本、指令、掃描範圍、退出碼、退出碼意義、結果摘要），再列已涵蓋與未涵蓋範圍（未涵蓋依字母排序）；`claim` 若宣稱某個範圍而該範圍不在 `covered` 裡就丟 `ValueError`。沒安裝 Snyk 時記 `exit_code=127`、`covered=()`，並回 `CheckResult(name="snyk", status="not_run", ...)`，不改寫成通過。

- [x] **Step 4：實際執行一次並保存報告**

執行 `uv run python -m infra.scripts.checks scan --out docs/plan/report/snyk-<時間>.md`。預期：報告含 CLI 版本與掃描範圍。若組織沒有 Snyk Code 或 Secrets 權限，報告的「未涵蓋範圍」必須同時列出它們，並把金鑰檢查改指向 Task 1 的 `check_secrets`。

**沒有 Snyk 認證時的替代依賴掃描**（現況核對 2026-09-14，**本計畫選擇**）：本機 `snyk` 是 `1.1307.2` 但沒有 token，`snyk test` 只會回認證錯誤。此時 (1) **仍然**把那一次實際執行記成 `ScanRecord(tool="snyk", ..., exit_code=<實際值>, covered=(), not_covered=("code", "dependencies", "secrets"))` 與 `CheckResult(status="not_run")`；(2) 另外跑一次替代的依賴掃描並記成**第二筆** `ScanRecord`，`tool` 欄位寫實際工具名（例如 `pip-audit`，`uv run --with pip-audit pip-audit` 或 `uv pip audit`；**`pip-audit` 目前未安裝**），沒有網路或工具時改用 GitHub Dependabot／advisory 的查核紀錄。替代工具的紀錄**必須在報告裡明確標「非 Snyk」**，`covered` 只能寫 `dependencies`，`not_covered` 一定含 `secrets` 與 `code`；`render_scan_report` 的 `claim` 拒絕條件照舊生效。**金鑰掃描的結論只能來自 Task 1 的 `check_secrets`，不得由任何依賴掃描代替。**

- [x] **Step 5：提交** — `git add infra/scripts/checks.py tests/unit/test_security_checks.py` 後 `git commit -m "feat(infra): 分開紀錄 Snyk 依賴與金鑰掃描"`。

### Task 3：Demo 前預演與結束後停用清單

- [x] **Step 1：建立失敗測試**

```python
# tests/unit/test_acceptance.py
from infra.scripts.checks import rehearse_steps, teardown_checklist

def test_rehearse_covers_four_required_items():
    steps = rehearse_steps()
    joined = "\n".join(steps)
    assert "三次不同事件" in joined and "success_count" in joined
    assert "正確簽名" in joined and "錯誤簽名" in joined
    assert "小量" in joined and "重送" in joined
    assert all(step.startswith(("檢查", "執行", "確認")) for step in steps)

def test_teardown_lists_every_resource_to_disable():
    items = teardown_checklist()
    for keyword in ("EventBridge", "Function URL", "TKB_FAULT", "site/", "webhook secret"):
        assert any(keyword in item for item in items)
```

- [x] **Step 2：執行並確認紅燈**

```bash
uv run pytest tests/unit/test_acceptance.py -q
```

預期：FAIL，訊號包含 `cannot import name 'rehearse_steps'`。

- [x] **Step 3：建立最小實作**

`rehearse_steps` 回傳固定順序的字串：三次不同事件走同一 PROC 並確認 `success_count >= 3`；對 webhook 各送一次正確簽名與一次錯誤簽名的 `curl`，預期一個接受、一個拒絕且不寫入任何業務物件；對 Titan 與 Claude 各做一次小量試呼叫並記下 model／inference profile 與回應摘要；重送同一事件確認不新增版本或樣本。`teardown_checklist` 回傳結束後要逐項處理的資源：停用 EventBridge 排程、關閉或移除 Function URL 與 webhook secret（`TKB_GITHUB_WEBHOOK_SECRET`）、清掉所有環境的 `TKB_FAULT`、決定 `site/` 是否繼續公開、保留或移除表與 bucket 的決策紀錄。

- [x] **Step 4：實際跑一次預演並保存輸出**

執行 `uv run python -m infra.scripts.checks rehearse`。預期：四項全部印出實際結果。任何一項沒有真的執行就記 `not_run`；費用與 Free Tier 依帳號方案而定，報告不得寫「本次免費」或固定金額。

- [x] **Step 5：提交** — `git add infra/scripts/checks.py tests/unit/test_acceptance.py` 後 `git commit -m "feat(infra): Demo 預演與停用清單"`。

### Task 4：V1–V4、S0–S8 與 147 條 Rule 的證據索引

- [x] **Step 1：建立失敗測試**

```python
from infra.scripts.checks import ACCEPTANCE_ROWS, acceptance_report

def test_acceptance_rows_cover_every_required_id():
    ids = {row.row_id for row in ACCEPTANCE_ROWS}
    assert {"V1", "V2", "V3", "V4"} <= ids
    assert {f"S{n}" for n in range(9)} <= ids
    assert sum(1 for row in ACCEPTANCE_ROWS if row.group == "rule") == 147
    assert len(ACCEPTANCE_ROWS) == 168

def test_every_rule_row_carries_owner_and_verify_phases():
    rules = [row for row in ACCEPTANCE_ROWS if row.group == "rule"]
    assert all(row.owner_phase.startswith("P") for row in rules)
    assert {row.row_id for row in rules if row.row_id.startswith("COL#")}
    assert not [row for row in rules if row.row_id.startswith("FDB#")]

def test_missing_evidence_blocks_completion():
    text, ok = acceptance_report(ACCEPTANCE_ROWS, {"V1": "site/tutorials/prepare-meeting/v1.html"})
    assert ok is False
    assert "[not_run]" in text
    assert "文件 parser 成功不等於 runtime 通過" in text
```

- [x] **Step 2：執行並確認紅燈**

```bash
uv run pytest tests/unit/test_acceptance.py -q
```

預期：FAIL，訊號包含 `cannot import name 'ACCEPTANCE_ROWS'`。

- [x] **Step 3：建立最小實作**

`ACCEPTANCE_ROWS` 由五部分組成，合計 168 列：設計 §3 的四個可見結果（`V1` 缺口產生教學、`V2` 低分教學獲得改善、`V3` 改版不改無關文字、`V4` 已驗證規則用到另一篇教學——`R-007` 轉 active 之後，由 [Phase 58](./58-Phase58-Demo控制台與規則開關預覽.md) 的 `trigger-ticket` 跑一次正常 Ticket Analysis 產生 B 的第一版且 `rules_applied == ["R-007"]`，證據是那一版的 VERSION item 與公開頁，00A D-68）、§16 的九個切片（`S0`–`S8`）、十三份 `.feature` 的 147 條 Rule（`row_id` 用 00B 的縮寫加編號，例如 `RUN#10`、`COL#2`；`收集教學回饋` 一律用 `COL`，不用 `FDB`）、AWS 六列（三條 state machine 各一次真實執行 ARN、webhook 驗簽的兩次 `curl`、`AWS-MODELS` 模型可用性報告）與瀏覽器兩列（公開站的版本頁與退役頁截圖）。每列的 `owner_phase` 抄 00B 第 2 節的 primary Phase、`verify_phases` 抄同一列的「其他相關 Phase」，本 Phase 不重新裁決歸屬。`acceptance_report` 對每列查 `evidence`：有值標 `pass`、值為 `"fail:<原因>"` 標 `fail`、缺值標 `not_run`，逐列印出 `row_id`、描述、追驗 Phase 與證據，最後固定附上一行「文件 parser 成功不等於 runtime 通過」。

- [x] **Step 3A：把 00B 第 2 節變成可執行的覆蓋檢查**（新增，現況核對 2026-09-14）

147 條 Rule 的覆蓋證據**唯一來源是 [00B](./00B-需求覆蓋對照.md) 第 2 節**：每一列有 `Rule #`、Rule 原文、primary Phase、其他相關 Phase、**可觀察 assertion**（指到 `tests/...` 的檔案，多半連測試函式名都寫了）。本 Phase 要把「這份表存在」變成「這份表可執行」：

1. **來源比對**：`ACCEPTANCE_ROWS` 的 147 個 `rule` 列逐列對上 00B 第 2 節；`row_id` = 縮寫 + `#` + 該檔內編號（00B §1 的 13 個縮寫：`REL`／`TIC`／`RUN`／`APL`／`REV`／`VER`／`ING`／`PRP`／`COL`／`GPH`／`MET`／`PUB`／`VAL`）。每個縮寫的列數要等於該 `.feature` 的 `Rule:` 條數（實測 17／14／10／8／9／10／31／6／10／7／12／5／8 = **147**），**用 `grep -c '^\s*Rule:'` 重算一次當斷言，不要相信抄來的數字**。
2. **斷言檔存在**：逐列取 00B 那一列「可觀察 assertion」欄裡的測試檔路徑，斷言檔案存在。
3. **pytest 收集得到**：用 `pytest --collect-only -q` 收集一次全套，把 `nodeid` 收進集合，再逐列斷言該檔（有寫函式名時連函式一起）真的被收集到。**收集不到就是 `not_run`**——測試檔被改名、被刪、或 import 失敗都會在這裡現形。
4. **失敗的表達**：檔案缺／收集不到的列在 `acceptance_report` 裡就是 `not_run`，整體布林為 `False`。**不得**因為「00B 寫了就算覆蓋」而標 `pass`——00B §1 自己就寫了「`有對應` 只代表有一份文件負責，不代表已經執行或通過」。

這一步只讀 00B 與測試樹，**不改 00B、不改任何測試檔**（W0 指令 D、R3.6）。發現 00B 與實際測試檔對不上，寫進報告第 9 節交給 controller，不自行修改 00B。

- [x] **Step 4：填入實際證據並產出報告**

執行 `uv run python -m infra.scripts.checks acceptance docs/plan/report/evidence.json`。預期：列出每列狀態與統計。只要還有 `not_run`，最終結論必須是「未完成」，不得改成「大致完成」。**依 2026-09-14 的 gate 現況，下列各列一定不會是 `pass`，要如實填**：`AWS-MODELS` 與任何需要 Bedrock 的列 → `not_run`，證據指 `docs/plan/report/o5-20260915T030245Z.md`（**O5 BLOCKED**，附 `ValidationException: Operation not allowed` 原文）；發布切換相關列（`PUB` 4、5、S3 切片、Phase 59 的 recovery 報告列）→ `fail:O3 仍是 FAIL`，證據指 `docs/plan/report/o3-20260914t181109z.md`；Release 與三個手動來源的 `ING` 列 → `not_run`，證據指 `docs/plan/report/o6-mapping.md`（**O6 4 列待核定**）；`V4` 與 `VAL` 3／6 的 O7 列 → 沒有 `demo/seed/approvals/<batch_id>.json` 的維護者核定就 `not_run`；O1 記 provisional、O4 依 P54 的首驗結果填。

- [x] **Step 5：提交** — `git add infra/scripts/checks.py tests/unit/test_acceptance.py docs/plan/report/evidence.json` 後 `git commit -m "feat(infra): V1-V4、S0-S8 與 147 Rule 證據索引"`。

## 8. 驗收矩陣

| 路徑 | 輸入 | 預期資料結果 |
|---|---|---|
| Happy | 所有檢查已跑、所有列都有證據 | 四支檢查 `pass`；報告布林為 `True`；仍附 runtime 免責句。 |
| Failure | bucket policy 開放整桶或 `operations/` | `check_public` 回 `fail` 並列出違規 `Sid`。 |
| Failure | 角色出現 `dynamodb:*`、`Resource: "*"` 或第五支 Lambda | `check_iam` 回 `fail` 並逐條列出。 |
| Failure | `s3:ListBucket` 沒有 `s3:prefix` 條件 | `check_iam` 回 `fail`；不得為了讓 `get_object` 能用就開整桶列舉。 |
| Failure | `git check-ignore .env` 未命中 | `check_secrets` 回 `fail`；不得以「還沒放真金鑰」當理由放行。 |
| Boundary | 未安裝或無權限跑 Snyk Secrets | 記 `not_run` 與未涵蓋範圍；宣稱通過會被 `ValueError` 擋下。 |
| Boundary | 147 列少一列或多一列、或出現 `FDB#` 縮寫 | 測試 FAIL；索引必須與 `.feature` 的 Rule 總數與 00B 的縮寫一致。 |
| Boundary | 只提供單元測試證據 | 對應 AWS／瀏覽器列仍是 `not_run`，整體未完成。 |

**這張矩陣的每一列都分成兩類判定**（現況核對 2026-09-14，依 controller R1 與 gate 現況）：

| 類別 | 哪些列 | 怎麼判 |
|---|---|---|
| **可實證** | 四支靜態檢查（`check_secrets`／`check_iam`／`check_public`／`check_output_safety`）、`run_all` 的三態語意、`render_scan_report` 的拒絕條件、147 列的覆蓋檢查（Step 3A）、`teardown_checklist` 的逐項執行紀錄；以及真實帳號讀回 bucket policy 與 HTTP website endpoint 的人工核對 | 在本機（＋真實 `us-east-1` 讀回 policy）實際跑出來、輸出貼進 `acceptance-<時間>.md` 才算過。四支檢查本身可以是 `pass`。 |
| **BLOCKED／FAIL 如實記錄** | `AWS-MODELS` 與所有 Bedrock 相關列（**O5 BLOCKED**）、發布切換相關列（**O3 FAIL**）、Release 與三個手動來源的 `ING` 列（**O6 4 列待核定**）、O7 核定列與 O4 首驗列（**未到**）、Snyk 依賴與 secrets（**本機無認證**） | **照實記錄觀察到的結果與錯誤原文**，在該列填 `not_run` 或 `fail:<原因>`，證據指向對應 gate 報告。**一律不得標 green**，也不得因為「檢查腳本自己跑得過」就把 gate 寫成通過。 |

人工驗收：打開 `acceptance-<時間>.md`，任選五列點進它指的檔案或截圖，確認內容確實對得上該列描述與追驗 Phase；再用實際帳號 `aws s3api get-bucket-policy --region us-east-1 --bucket <bucket>` 讀一次 bucket policy，確認與 CDK template 一致，且公開網址是 **HTTP** website endpoint（S3 website 沒有 HTTPS）。不能只看腳本輸出 `pass`。

## 9. 常見錯誤與停止條件

| 症狀 | 原因 | 修正／停止 |
|---|---|---|
| 報告寫「secrets scan 通過」 | 只跑了依賴掃描 | `render_scan_report` 直接拋錯；改記未涵蓋並指向 `check_secrets`。 |
| 未跑的項目被標成 green | 把 `not_run` 併進 `pass` | 停止；`run_all` 對 `not_run` 一律回非 0。 |
| 為了讓 `check_iam` 過而放寬核對表 | 改檢查門檻而不是改權限 | 停止；核對表是契約，要改先回 Phase 09。 |
| 找不到 `SYSTEM_GUARD` 常數 | 沿用舊版 Consumes | 依裁決 D-50 改核對 `<source_data>` 分區標記，不要新增公開常數。 |
| 宣稱 O3 或 O5 已通過 | 拿本 Phase 的彙整當 gate 結論 | 停止；gate 結論只能來自 Phase 12／14 的實測報告。 |
| 把 CDK synth 或連結檢查當 runtime 通過 | 混淆語法驗證與執行驗證 | 報告固定保留免責句；AWS 列沒有 ARN 就是 `not_run`。 |
| 展示後忘了停用排程或 webhook | 沒有跑停用清單 | 依 `teardown_checklist` 逐項處理並記錄誰在何時執行。 |

## 10. 來源與 Rule 對照

本 Phase 是驗收型，沒有 primary Rule；下列都是「相關」，直接斷言由括號內的 primary Phase 負責，本 Phase 只檢查證據存在（[00B](./00B-需求覆蓋對照.md) 第 2、3.2 節）。

- [接入來源事件.feature](../../spec/features/接入來源事件.feature)
  - Rule 1：「GitHub webhook 必須以 X-Hub-Signature-256 驗簽」、Rule 2：「沒有簽名的 GitHub webhook 請求被拒絕」→ 相關（primary Phase 30）；Task 3 的預演以正確與錯誤簽名各送一次 `curl`，確認一個接受、一個拒絕且不寫入業務物件。
  - Rule 7：「第一層流程的 success_count 必須至少為 3」→ 相關（primary Phase 34）；Task 3 的預演在實機累積三次不同事件後確認 `success_count >= 3`。
  - Rule 30：「同一正規化事件重送時只處理一次」→ 相關（primary Phase 10）；Task 3 的重送項目與 Phase 59 的證據互相對照。
- [發布教學版本.feature](../../spec/features/發布教學版本.feature) Rule 2：「發布的教學透過 S3 靜態 docs 站提供」→ 相關（primary Phase 57）；Task 1 的 `check_public` 掃描公開前綴只有 `site/`。
- [檢視學習指標.feature](../../spec/features/檢視學習指標.feature) Rule 9：「每次執行的 Bedrock 呼叫數包含 Step Functions 內的呼叫節點與 Rote 層呼叫」→ 相關（primary Phase 54）；Task 3 的小量試呼叫逐次記錄 model 與 attempt。
- [驗證教學規則.feature](../../spec/features/驗證教學規則.feature) Rule 3：「未載入完整核定種子驗證批次時不改變規則狀態」、Rule 6：「驗證無效的規則從可使用規則中退役」→ 相關（primary Phase 55）；證據索引的 O7 列必須指向 Phase 56 的核定紀錄與 R-012 兩批證據，缺就 `not_run`。
- 其餘 Rule 由 Task 4 逐條建立索引列，primary 與追驗 Phase 都照 00B，本 Phase 只檢查證據存在。
- 設計 §3（四個可見結果）、§15（十五列驗收範圍、parser 不等於業務驗收）、§16（S0–S8）、§17.1（Snyk 兩種能力不同）、§17.2（最小權限、跳脫、公開區界線、`.env` 尚未被忽略的事實）、§17.3（預演四項、備援標示、結束後停用）、§18（O1–O7 未完成前不能宣稱什麼）。
- [Snyk CLI test 退出碼](https://docs.snyk.io/developer-tools/snyk-cli/commands/test)：0 無發現、1 有發現、2 掃描失敗可重跑、3 沒有支援的專案。
- [Snyk Secrets](https://docs.snyk.io/scan-fix-and-prevent/scan-with-snyk/snyk-secrets)：獨立能力，需組織啟用。
- [S3 static website 權限設定](https://docs.aws.amazon.com/AmazonS3/latest/userguide/WebsiteAccessPermissionsReqd.html)：公開讀取需同時調整 Block Public Access 與 bucket policy。
- [AWS Free Tier FAQ](https://aws.amazon.com/free/free-tier-faqs/)：免費額度依帳號方案與建立時間而定，報告不得承諾全免費或固定金額。

## 11. 完成清單

- [x] 四支靜態檢查都有 `pass`／`fail`／`not_run` 三態，且 `not_run` 讓整體回非 0。
- [x] `git check-ignore .env` 的實際結果已記錄；命中疑似金鑰或 `TKB_GITHUB_WEBHOOK_SECRET` 真值時只印位置不印內容。（2026-09-15 實跑：退出碼 0，命中 `.gitignore:10`；追蹤檔零 finding）
- [ ] `check_iam` 的四支 Lambda 核對表與 CDK template 一致，沒有萬用字元 Action／Resource，`s3:ListBucket` 用 `s3:prefix` 限定 `PRIVATE_PREFIXES` 四個前綴。　**未勾（2026-09-15）：** 四支 Lambda 與 `s3:prefix` 都對得上，但 `TrainingKbApp` 有一條 `sts:GetCallerIdentity` 搭 `Resource: "*"`（`_grant_execution_lookup`），`check_iam` 依核對表判 **fail**。核對表只放行 CloudWatch Logs 建立群組這一個例外，本 Phase **不放寬**；處理方式見報告第 9 節，交 controller 裁決。
- [x] `check_public` 確認公開的只有 `site/tutorials/...`、`site/index.html` 與 `site/assets/`，且報告把 website endpoint 寫成 HTTP。（2026-09-15 實跑：`aws s3api get-bucket-policy` 讀回的唯一 Allow 就是 `site/*` ＋ `s3:GetObject`；website endpoint 一律寫成 HTTP）
- [x] `check_output_safety` 依 D-50 核對 `<source_data>` 分區與 `html.escape`，沒有引用不存在的 `SYSTEM_GUARD`。
- [x] Snyk dependency 與 secrets 分開記錄工具版本、指令、範圍與退出碼；未跑的範圍標為未涵蓋。（2026-09-15 實跑：`snyk test` 退出碼 **3**「No supported files found」且未認證 → `not_run`；替代的 `pip-audit` 退出碼 1，標「非 Snyk」）
- [ ] 預演四項（三次同程序成功、兩次驗簽 `curl`、小量模型呼叫、重送）都有實際輸出。　**未勾（2026-09-15）：** 三次同程序成功（真表 `PROC#d1ad3cfd19a24c4d success_count=3`）、兩次驗簽（Function URL 200 `ok:true`／`ok:false`）、重送（同一 `operation_id`、執行數不變）三項都有實際輸出；**小量模型呼叫是 `not_run`**（O5 BLOCKED，刻意不對真實 Bedrock 發請求）。
- [x] 168 列證據索引齊全（V1–V4、S0–S8、147 條 Rule、AWS 六列、瀏覽器兩列），每列都有 primary 與追驗 Phase，缺證據列為 `not_run`；`V4` 那一列指向 `R-007` 轉 active 後正常產出的 B 第一版（`rules_applied == ["R-007"]`，D-68）。**（前半已做到：168 列齊、每列都有 primary 與追驗 Phase；後半未達成——`V4` 只能是 `not_run`，O7 三份核定紀錄仍空，`R-007` 沒有轉 active，也沒有帶 `rules_applied == ["R-007"]` 的 B 第一版。）**
- [ ] 結束後停用清單已逐項執行並記錄；報告保留「文件 parser 成功不等於 runtime 通過」。　**未勾（2026-09-15）：** 清單已產出（`checks teardown`，六項）並附在報告；**刻意沒有執行**——停用排程／關 Function URL／下架 `site/` 會把 controller 後續複驗要用的資源拆掉，且撤換 webhook secret 是維護者的決定（§全域限制「不代替維護者做資源刪除」）。報告已保留「文件 parser 成功不等於 runtime 通過」。
- [x] **147 列的覆蓋檢查可執行（Task 4 Step 3A）**：縮寫與列數用 `grep -c '^\s*Rule:'` 重算過（13 檔合計 147），每列的斷言檔存在且 `pytest --collect-only` 收得到；收不到的列是 `not_run`。（2026-09-15 實跑：13 檔重算 147；1688 個 nodeid 全部收得到，**0 條 gap**）
- [x] **`check_iam` 只掃 IAM 資源的 `Effect: Allow` 陳述**，沒有被 `enforce_ssl` 產生的 bucket policy `Deny s3:*` 誤判；兩份 template（`TrainingKbDataStack`、`TrainingKbStack`）都掃過，缺的 Lambda 標 `not_run`。（四支 Lambda 在 `TrainingKbApp` 都在，`iam-lambda-inventory` 為 `pass`）
- [x] **`check_secrets` 的掃描範圍與排除清單寫進 `CheckResult.scope`**（`git ls-files` 減 `docs/`／`.superpowers/`），`git check-ignore .env` 的實際退出碼已記錄。
- [x] **Snyk 沒有認證的事實已如實記錄**（CLI 版本、指令、實際退出碼與錯誤原文、`covered=()`），替代依賴掃描另記一筆並明確標「非 Snyk」；金鑰掃描的結論只引用 `check_secrets`。
- [x] **O5 BLOCKED、O3 FAIL、O6 4 列待核定、O7／O4 未到都已如實進索引**，各指向對應 gate 報告；沒有任何未執行的檢查被標成 green。
