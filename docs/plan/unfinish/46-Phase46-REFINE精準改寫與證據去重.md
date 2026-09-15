# Phase 46：REFINE 精準改寫與證據去重實作計畫

> **給實作者：** 依 checkbox 逐步執行；每個 Task 先建立失敗測試，再寫最小實作。執行時使用 `superpowers:executing-plans` 或同等逐項流程。

> **現況核對（2026-09-14，Phase 41–60 批次 W0）：**
>
> **(a) 已存在、可直接重用（不要重寫）**
> - `src/training_kb/content.py`：`allocate_version(tutorial_id, operation_id, operations, *, repository, reason, rules_applied) -> VersionPlan`（:194，**前三個是位置參數**，重送同 `operation_id` 走 `_replay_plan` 回同一版號）、`validate_content(content, known_feature_ids: frozenset[str]) -> None`（:290）、`parse_markdown(markdown) -> TutorialContent`（:431）、`create_version(plan, content, repository) -> TutorialVersion`（:617）、`verify_version_complete(version_id, repository) -> bool`（:691）。
> - `src/training_kb/rules.py`：`rules_for_content(rules, step_types, validated_at_by_rule) -> dict[StepType, list[AuthoringRule]]`（:55，**回 dict**）、`render_rules_block(rules) -> str`（:44）、`applied_rule_ids(rules) -> list[str]`（:50）。`select_active_rules`（:25）同一個 `step_type` **最多回一條**（`matching[:1]`），缺 `validated_at` 直接 `PermanentError`。
> - `src/training_kb/analytics/status_writer.py:36` `load_validated_at(repository) -> dict[str, datetime]`（P40 已建讀取端，檔案不存在回 `{}`；D-28）。
> - `src/training_kb/operations.py`：`OperationCoordinator.load(operation_id) -> OperationRecord | None`（:290）、`record_model_output(operation_id, output_ref)`（:319，同 ref 不重複附加）、`acquire_lease(scope, owner, *, ttl_seconds, now) -> bool`（:376）、`release_lease(scope, owner)`（:416，非持有者呼叫無效果）。`OperationRecord` 有 `version_id`、`model_output_refs`（tuple）、`updated_at`。
> - `src/training_kb/keys.py:182` `operation_ref(operation_id, name) -> "operations/<op>/<name>.json"`；`src/training_kb/ingress.py:243` `operation_id_for(kind, canonical_id) -> "op-<kind>-<canonical_id>"`，`OperationKind` 含 `"feedback"`（`operations.py:47`）。
> - `src/training_kb/writing/schemas.py:53` `StepRewrite`（schema dict）；`writing/prompts.py:29` `_as_data`。
> - `src/training_kb/models.py:173` `TutorialVersion(version_id, slug, supersedes, reason, rules_applied, s3_key, published_at)` —— `slug` 與 `s3_key` 都在，`get_tutorial(base_version.slug)` 成立。
> - `src/training_kb/repository.py:399` `put_object(key, body, content_type, *, if_none_match)` —— `if_none_match` **是必填 keyword、沒有預設值**。
> - `src/training_kb/pipelines/feedback.py`：controller 已預建空殼（commit `5f8a430`），P44／P45／P47 在 W1 先落地。
>
> **(b) 文件因上一批裁決／實作而修正的點**
> 1. 「全域限制」寫 **O2 尚未 PASS** → **錯了，O2 已 PASS**（P11，`docs/plan/report/o2-20260914t182824z.md`）。因此 Task 3 Step 4 那句「**O2 未 PASS 前，本 Task 只能標 blocked**」**作廢**：`tests/integration/test_feedback_refine_retry.py` 要**實際執行**（`TKB_RUN_AWS_INTEGRATION=1 uv run pytest -m aws`）並把輸出寫進報告。記憶體 fake 的綠燈仍然不算永久去重證據，這一句保留。
> 2. §4「檔案由 Phase 44 建立」→ controller 已預建空殼（COMMON.md R4）。本 Phase 是 **W2**（等 P45 的 `DiagnosisResult` 落地後才開始），仍只用 Edit、`# ---- Phase 46 ----` 區段。
> 3. `prompt_refine_steps` 要加進 `writing/prompts.py`，該檔 W1 已被 P45（`prompt_diagnose_weak`）與 P47（`prompt_propose_rule`）各加一段；本 Phase 只 Edit 自己那段。
> 4. `select_active_rules` 每個 `step_type` 只回一條（最近驗證時間優先、同時間取 `rule_id` 升序），所以 `_rules_for_hits` 的 `selected` dict 最多會有「命中步驟型態數」條規則，不是所有 active 規則。
> 5. `prepare_refine` 片段裡 `repo.get_version(diagnosis.version_id)` 可能回 `None`（`get_version` 的回傳型別是 `TutorialVersion | None`）；落檔時要先擋 `None` 再取 `.slug`，否則 mypy strict 會擋下來。
> 6. `record.updated_at` 是 `OperationRecord` 既有欄位，`acquire_lease(..., now=record.updated_at)` 成立（本計畫選擇不變）。
>
> **(c) gate 現況對本 Phase 的影響**（COMMON.md §2）
> - O1 provisionally accepted（D-71）；**O2 PASS**（P11）；**O3 FAIL**（P12，`docs/plan/report/o3-20260914t181109z.md`；P24／P25 已依協定 A 在 moto 重現切點，F49 未放寬）；**O5 BLOCKED**（`docs/plan/report/o5-20260915T030245Z.md`）；O6 待核定；O4／O7 未到。
> - **O5 BLOCKED**：`TKB_GENERATION_MODEL_ID` 不得填猜測值；單元測試用假 Writer；真實 AWS 上 `refine_steps` 節點會走 `PermanentError → Catch → PipelineFailed`，那是 BLOCKED 證據。
> - **O3 FAIL**：本 Phase 本來就不發布（只建未發布版本、只寫私有前綴），不受影響；但報告不得把「建出 v2」寫成「已公開」。
>
> **(d) controller 裁決 R1–R11 的適用項**
> - **R3（同檔併行）**：`pipelines/feedback.py` 與 `writing/prompts.py` 兩支共用檔在本批都有多人動過。只用 Edit 不用 Write；動手前先重讀要改的那一段；不重排、不重格式化、不改名別人的程式；共用檔只跑 `ruff format --check`；`git add` 只加自己的檔案路徑；整套測試紅燈若來自別的 Phase 進行中的測試檔，用 `--ignore=` 排除並在報告寫明。
> - **R4**：空殼已建，直接 Edit。**R5**：文件片段是示意，簽名以 00A ＋ 既有程式為準。
> - **R6／R7／R8**：逐 Task 先紅燈再綠燈；報告寫 `docs/plan/report/phases/2026-09-14-Phase46-REP.md`；commit trailer 照 COMMON.md R8。
> - 測試檔照 00A §3.3 平放：`tests/unit/test_feedback_refine.py`、`tests/integration/test_feedback_refine_retry.py`（兩個 basename 全專案唯一）。

**目標：** 用 Phase 45 的有效診斷只改命中步驟，其餘文字逐字相同，並讓同一批證據不會再產生第二個版本。

**架構：** `pipelines/feedback.py` 先把同版同類的 Feedback ID 正規化成證據指紋，再依「lease → 選規則 → 配版號 → 呼叫模型 → 程式核對 → 建版」的固定順序產出一個**未發布**版本。模型只回命中步驟的新文字；版號、reason、`rules_applied` 與去重全部由程式決定。發布由 Phase 25 的 `Publisher` 在 Phase 48 執行，本階段不碰公開前綴。

**技術：** Python 3.12、Pydantic v2、pytest、Phase 10／11 的 `OperationCoordinator`、Phase 15／17 的 `Writer.generate_json` 與 `StepRewrite` schema、Phase 19 的規則選取、Phase 20–23 的 content 模組。

## 全域限制

- 唯一主來源是 [Training KB 設計 §7.5、§7.6、§8.1、§8.2、§14.1、§18](../../design/training-kb.md)。
- 前置為 [Phase 45：回饋診斷與命中步驟](./45-Phase45-回饋診斷與命中步驟.md)；它未通過時停止。另外依賴已完成的 [Phase 11：O2 接受順序與重啟整合驗證](./11-Phase11-O2接受順序與重啟整合驗證.md)（lease）與 [Phase 20](./20-Phase20-版本分配與重試重用.md)–[Phase 23](./23-Phase23-未發布版本與關係完整寫入.md)（版號、內容、Markdown、建版）。
- 下一階段是 [Phase 47：Candidate 規則提出與溯源](./47-Phase47-Candidate規則提出與溯源.md)。
- 本階段**不發布**、不切 `current_version`、不寫 `site/` 前綴、不提出規則、不修改回饋，也不建立新的 Tutorial 身分（只有 Ticket Analysis 能建）。
- REFINE 只能以該篇**最近已發布版本**為基底（基底不是 `Tutorial.current_version` 時停止）；只注入 active 規則，且只取命中步驟型態的規則，複製原文不算本次套用（F29）。
- gate 狀態（現況核對 2026-09-14，見 COMMON.md §2；原寫「O2 尚未 PASS」已不成立）：**O2 PASS**（P11，`docs/plan/report/o2-20260914t182824z.md`），永久去重與同版號可以依賴，但**記憶體 fake 的綠燈仍不算證據**，要靠 `tests/integration/test_feedback_refine_retry.py` 在真實表上跑；**O3 FAIL**（P12），公開發布路徑保留 FAIL，本 Phase 本來就不發布；**O5 BLOCKED**（不是「尚未通過」），`TKB_GENERATION_MODEL_ID` 保持 `<實測通過的 ID>` 佔位、不得填猜測值，假 Writer 綠燈不等於 Bedrock 或 AWS 已通過。
- 以下程式檔均是實作時預計建立或修改；本計畫本身不代表它們已存在。

---

## 1. 你在整體流程的位置

```text
Phase 45 DiagnosisResult --> [你在這裡：REFINE 準備]
                                   |
     +-----------------------------+-----------------------------+
     v step_indexes == ()          v 同一批證據已產版             v 有新證據且有命中步驟
     -> None（NO_STEP）            -> None（no_new_evidence）     -> 未發布的 v<n+1>
                                                                    |
                                                                    v
                                          Phase 48 交給 Publisher.prepare / commit
```

## 2. 完成後看得到什麼

以 `prepare-meeting@v1` 的四步為基底、只命中第 3 步、八筆「找不到按鈕」的回饋：

```text
base = prepare-meeting@v1        |  新版 prepare-meeting@v2（未發布）
  1. 開啟會議。                   |    1. 開啟會議。                  <- 逐字相同
  2. 選擇目標會議。               |    2. 選擇目標會議。               <- 逐字相同
  3. 開啟摘要。                   |    3. 在會議頁面右上角選擇 Meeting Summary。  <- 唯一改動
  4. 確認會前重點。               |    4. 確認會前重點。               <- 逐字相同

RefinePlan(version_id="prepare-meeting@v2", base_version_id="prepare-meeting@v1",
           reason="feedback:8 則 找不到按鈕", changed_indexes=(3,),
           rules_applied=("R-007",), evidence_fingerprint="9f2c…（64 個十六進位字元）")
```

同樣八個 Feedback ID 再送一次：回傳 `None`，沒有 v3，也沒有第二次模型呼叫。

## 3. 名詞小抄

| 名詞 | 白話意思 |
|---|---|
| REFINE／精準改寫 | 因低分回饋而產生下一版（和 CREATE、UPDATE 並列，設計 §8.1）；只有診斷命中的步驟文字允許不同，其餘步驟與四個段落逐字相同。 |
| 證據指紋 | 把「版本 ID + 類別 + 排序去重的 Feedback ID」雜湊成的固定字串，用來辨識同一批證據。 |
| `no_new_evidence` | 同一批證據已經產過版；本輪回 `None`，不再配版號也不呼叫模型（F23）。 |
| `StepRewrite` | Phase 17 固定的 **JSON schema 字典**，required 是 `steps[{number, text, feature_id, type}]`；它不是 pydantic 類別。 |
| lease（租約） | 同一篇教學同時只讓一個操作改寫的暫時標記；**它不是接受順序保證，TTL 也不是準時解鎖**。 |
| `rules_applied` | 本次改寫 prompt 真正注入的 active 規則 ID；沿用原文不算（F29）。 |
| 未發布版本 | `published_at` 是 `null` 的版本；產物只在私有前綴，公開站讀不到。 |

## 4. 預計檔案

| 動作 | 路徑 | 責任 |
|---|---|---|
| 修改 | `src/training_kb/pipelines/feedback.py` | `RefinePlan`、`REFINE_NODE`、`LEASE_TTL_SECONDS`、`evidence_fingerprint`、`refine_operation_id`、`refine_reason`、`evidence_of`、`prepare_refine`。（現況核對 2026-09-14：原寫「檔案由 Phase 44 建立」，實際上 controller 已預建空殼；本 Phase 是 **W2**，在 P44／P45／P47 的 W1 之後，只用 Edit 追加 `# ---- Phase 46 ----` 區段。） |
| 修改 | `src/training_kb/writing/prompts.py` | 依 Phase 17 的 `prompt_<node>` 命名加入 `prompt_refine_steps`（檔案由 Phase 17 建立；`_as_data` 已在該檔，直接用）。**W1 的 P45／P47 已各加一段，只 Edit 自己那段。** |
| 測試 | `tests/unit/test_feedback_refine.py` | 指紋、reason、精準改寫、越界改寫、規則紀錄、`NO_STEP` 與 `no_new_evidence`。 |
| 測試 | `tests/integration/test_feedback_refine_retry.py` | lease 衝突、儲存中斷後以同 operation 重送、同版號與模型輸出重用。 |

## 5. 固定介面

### Consumes

```text
# 簽名逐字照 00A §6.1–§6.9，這裡只列本階段真正呼叫到的名稱
ContentError / CoordinationError / TransientError                                # Phase 02
TutorialContent / StepDraft / StepType / RuleStatus                              # Phase 03
Feature / Feedback / Tutorial / TutorialVersion / AuthoringRule                  # Phase 04
Repository.get_tutorial / get_version / get_object / put_object                  # Phase 06／07
Repository.list_feedback_of_version / list_rules / scan_entity；item_to_model    # Phase 08
operation_ref；OperationCoordinator.load / record_model_output                    # Phase 10
OperationCoordinator.acquire_lease(scope, owner, *, ttl_seconds, now) -> bool；
OperationCoordinator.release_lease(scope, owner) -> None                         # Phase 11
Writer.generate_json(system, user, schema: Mapping[str, Any], *,
                     operation_id: str, node: str) -> dict[str, Any]             # Phase 15／17
StepRewrite  # JSON schema 字典，required: steps[{number,text,feature_id,type}]   # Phase 17
render_rules_block；applied_rule_ids；
rules_for_content(rules, step_types, validated_at_by_rule)
    -> dict[StepType, list[AuthoringRule]]                                       # Phase 19
allocate_version(tutorial_id, operation_id, operations, *, repository,
                 reason, rules_applied) -> VersionPlan                           # Phase 20
validate_content；parse_markdown                                                  # Phase 21／22
create_version(plan, content, repository)；verify_version_complete(version_id, repository)  # Phase 23
operation_id_for(kind: OperationKind, canonical_id: str) -> str                  # Phase 32
DiagnosisResult(version_id, step_indexes, reasons, feedback_ids)                 # Phase 45
load_validated_at(repository) -> dict[str, datetime]  # analytics/status_writer.py，
    讀取端 Phase 40 首建、寫入端 Phase 55；呼叫端負責讀好再傳進 Phase 19       # Phase 40
```

三個最容易抄錯的簽名（00A 第 8 節 D-02／D-03／D-04）：`generate_json` **吃 schema dict、回 `dict`**，本階段直接把 `StepRewrite` 這個字典傳進去，拿回 `dict` 後自己讀 `reply["steps"]`，**沒有** `StepRewrite.model_validate(...)` 可用；`rules_for_content` 回的是以 `StepType` 為 key 的 **dict**，不是 `(list, str)` tuple；`allocate_version` 前三個是位置參數，`repository`／`reason`／`rules_applied` 一律 keyword。`validated_at_by_rule` 只能來自 `analytics/status_writer.py` 的 `load_validated_at(repository)`（讀取端由 Phase 40 首建、寫入端 Phase 55 補在同檔；單一私有檔 `operations/rules/validated_at.json`，D-28），缺值時 Phase 19 會丟 `PermanentError`，本階段不補預設時間。

### Produces

```python
REFINE_NODE = "refine_steps"
LEASE_TTL_SECONDS = 120

@dataclass(frozen=True)
class RefinePlan:
    version_id: str
    base_version_id: str
    reason: str
    content: TutorialContent
    changed_indexes: tuple[int, ...]   # 裝的是步驟 number（從 1 起），不是 0-based index
    rules_applied: tuple[str, ...]
    evidence_fingerprint: str

def evidence_fingerprint(version_id: str, category: str, ids: Iterable[str]) -> str: ...
def refine_operation_id(version_id: str, category: str, ids: Iterable[str]) -> str: ...
def refine_reason(category: str, feedback_ids: Iterable[str]) -> str: ...
def evidence_of(diagnosis: DiagnosisResult, *, repo: Repository) -> tuple[str, tuple[str, ...]]: ...
def prompt_refine_steps(base: TutorialContent, diagnosis: DiagnosisResult, category: str,
                        rules_block: str) -> tuple[str, str]: ...
def prepare_refine(diagnosis: DiagnosisResult, *, repo: Repository, writer: Writer,
                   operations: OperationCoordinator,
                   operation_id: str) -> RefinePlan | None: ...
```

`changed_indexes` 這個欄位名是既有契約（Phase 48 已消費），**不改名**；但它裝的值就是步驟 `number`（00A §3.3、D-55）。`repo=` 這個參數名與 Phase 45、47 一致（Phase 48 照這個名稱呼叫），不可改成 `repository=`。`prepare_refine` 回 `None` **只**代表 `NO_STEP` 或 `no_new_evidence`，技術錯誤一律往外丟，不得吞掉。

## 6. 設計細節

處理順序固定如下，與 [Phase 51](./51-Phase51-Release-UPDATE精準改寫.md) 的 UPDATE 相同（00A §6.9）：

```text
step_indexes == () -------------------------------------> return None（NO_STEP，F24）
   |
   v  evidence_of -> (category, feedback_ids)；跨類別或有缺漏 -> ContentError
   v  operation_id != refine_operation_id(...)，或 load 不到紀錄 -> CoordinationError
   v  record.version_id 已完整 ---------------------------> return None（F23）
   v  acquire_lease("TUTORIAL#<slug>") -- 拿不到 --------> TransientError（交給 ASL Retry）
   v  選 active 規則（純函式，只看命中步驟的 step.type）
   v  allocate_version(..., reason="feedback:<n> 則 <category>", rules_applied=注入 ID)
   v  StepRewrite：prompt 只給命中步驟原文 + 該類回饋留言 + 規則區
   v  程式核對：改寫集合 == 命中集合？feature_id／type 未變？其餘逐字相同？
   v  validate_content -> create_version -> verify_version_complete
   +--> release_lease（finally）-> RefinePlan
```

**指紋只吃穩定的東西。** `evidence_fingerprint` 把 ID 去重排序後和 `version_id`、`category` 一起做 UTF-8 JSON 編碼再 SHA-256，所以 `f_2,f_1,f_1` 與 `f_1,f_2` 相同，換版本或換類別一定不同。平均分、留言原文、執行時間都不進指紋，否則顯示文字一變動就破壞永久去重。

**指紋就是 operation 的 canonical id。** 呼叫端（Phase 48）必須用 `refine_operation_id(...)` 產生每個 target 的 REFINE `operation_id`（形狀 `op-feedback-<64 位指紋>`，經 Phase 32 的 `operation_id_for`），再交給 `OperationCoordinator.accept` 接受。這同時解決三件事：同一批證據跨日重跑會撞到同一筆 `OPS#` 永久紀錄（F23）；同一次 Review 的不同 target 有不同 operation，`allocate_version` 不會兩篇共用一個版號；儲存重試沿用原版號與原模型輸出（設計 §14.2）。`prepare_refine` 自己再核對一次，對不上就丟 `CoordinationError`。**這是本計畫選擇**，永久去重本身仍依賴 O2；O2 未 PASS 前不得宣稱同證據絕不會產生第二版。

**「已產版」用 `verify_version_complete` 判斷，不是用 `status`。** `record.version_id` 有值且 `verify_version_complete` 為 `True`，代表 S3 全文、VERSION、STEP 與關係都齊了，本輪是重複證據 → 回 `None`；有值但不完整代表上次寫到一半 → 沿用同一個版號與 `record.model_output_refs[-1]` 的模型輸出補齊，**不再呼叫 `Writer`**。

**只算本次注入的規則。** 先取命中步驟的 `step.type`，再用 `rules_for_content` 挑 active 規則；同一條只列一次，順序依命中步驟出現順序。未被改寫的步驟就算型態相同、原文剛好符合某條規則，也不進 `rules_applied`（F29）。reason 固定 `feedback:<n> 則 <category>`，`<n>` 是**去重後**的證據筆數（D28）。

**lease 的語氣。** lease 的 scope 字串固定是 `TUTORIAL#<slug>`（Phase 11 自己補 `LEASE#` 前綴，與 Phase 51 逐字相同）；它只讓同一篇的併發改寫串行（設計 §8.3），拿不到就丟 `TransientError` 交給 ASL 有限重試，不自行迴圈等待；它不是接受順序保證，TTL 也不是準時解鎖。本階段簽名沒有 `now`，`acquire_lease` 的 `now` 取 `record.updated_at`（**本計畫選擇**：不在深層程式讀系統時鐘，00A §3.5）。

## 7. TDD Tasks

### Task 1：證據指紋、REFINE operation id 與固定 reason

- [ ] **Step 1：建立失敗測試**

```python
import pytest

from training_kb.errors import ContentError
from training_kb.pipelines.feedback import (evidence_fingerprint, evidence_of,
                                            refine_operation_id, refine_reason)

EIGHT_IDS = ("f_12", "f_15", "f_19", "f_23", "f_27", "f_31", "f_34", "f_40")

def test_fingerprint_ignores_order_and_duplicates() -> None:
    left = evidence_fingerprint("prepare-meeting@v1", "找不到按鈕", ["f_2", "f_1", "f_1"])
    assert left == evidence_fingerprint("prepare-meeting@v1", "找不到按鈕", ["f_1", "f_2"])
    assert left != evidence_fingerprint("prepare-meeting@v2", "找不到按鈕", ["f_1", "f_2"])
    assert left != evidence_fingerprint("prepare-meeting@v1", "缺少資訊", ["f_1", "f_2"])
    assert refine_operation_id("prepare-meeting@v1", "找不到按鈕", ["f_1", "f_2"]) == (
        f"op-feedback-{left}")

def test_reason_counts_unique_evidence() -> None:
    assert refine_reason("找不到按鈕", EIGHT_IDS) == "feedback:8 則 找不到按鈕"
    assert refine_reason("找不到按鈕", [*EIGHT_IDS, "f_12"]) == "feedback:8 則 找不到按鈕"

def test_evidence_must_be_one_category(world) -> None:
    assert evidence_of(world.diagnosis, repo=world.repo) == ("找不到按鈕", EIGHT_IDS)
    world.repo.recategorize("f_40", "缺少資訊")
    with pytest.raises(ContentError, match="同一個類別"):
        evidence_of(world.diagnosis, repo=world.repo)
```

`world` 是同檔 fixture，提供：`repo`（`get_tutorial`／`get_version`／`get_object`／`put_object`／`list_feedback_of_version`／`list_rules`／`scan_entity` 的記憶體假實作，外加 `recategorize` 與 `versions` 兩個測試鉤子）、`writer`（記下每次 `generate_json` 的 `(system, user, schema, node)`、`request_attempts` 與 `reply`）、`operations`（記憶體 O2 帳本與 lease，已接受 `operation_id`，另有 `hold(scope, owner)` 鉤子）、`base`（v1 的四步 `TutorialContent`）、`diagnosis`（`DiagnosisResult("prepare-meeting@v1", (3,), {3: "沒有指出按鈕所在頁面與位置"}, EIGHT_IDS)`）、`operation_id`（`refine_operation_id("prepare-meeting@v1", "找不到按鈕", EIGHT_IDS)`）。

- [ ] **Step 2：執行並確認紅燈**

```bash
uv run pytest tests/unit/test_feedback_refine.py -q
```

預期：FAIL，訊號包含 `cannot import name 'evidence_fingerprint'`。

- [ ] **Step 3：建立最小實作**

```python
import hashlib
import json
from collections.abc import Iterable

from training_kb.errors import ContentError
from training_kb.ingress import operation_id_for

REFINE_NODE = "refine_steps"
LEASE_TTL_SECONDS = 120
# RefinePlan 的 @dataclass 逐字照 §5 Produces，這裡不重複貼。

def evidence_fingerprint(version_id: str, category: str, ids: Iterable[str]) -> str:
    payload = {"version_id": version_id, "category": category, "feedback_ids": sorted(set(ids))}
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()

def refine_operation_id(version_id: str, category: str, ids: Iterable[str]) -> str:
    return operation_id_for("feedback", evidence_fingerprint(version_id, category, ids))

def refine_reason(category: str, feedback_ids: Iterable[str]) -> str:
    return f"feedback:{len(set(feedback_ids))} 則 {category}"

def evidence_of(diagnosis, *, repo) -> tuple[str, tuple[str, ...]]:
    wanted = frozenset(diagnosis.feedback_ids)
    rows = [row for row in repo.list_feedback_of_version(diagnosis.version_id) if row.id in wanted]
    categories = {row.category for row in rows}
    if len(rows) != len(wanted) or len(categories) != 1:
        raise ContentError(f"{diagnosis.version_id} 的證據必須是同一個類別且不可缺漏")
    return categories.pop(), tuple(sorted(wanted))
```

（本文件的程式片段用單空行分隔以節省篇幅，實際落檔時照 ruff 的兩空行規則。）

- [ ] **Step 4：跑完整檔案確認綠燈**

```bash
uv run pytest tests/unit/test_feedback_refine.py -q
```

預期：PASS；重複 ID 沒有把 `n` 變成 9。

- [ ] **Step 5：提交**

```bash
git add src/training_kb/pipelines/feedback.py tests/unit/test_feedback_refine.py
git commit -m "feat(feedback): 固定 REFINE 證據指紋與改版原因"
```

### Task 2：只改命中步驟，只記本次注入的規則

- [ ] **Step 1：建立失敗測試**

```python
from training_kb.models import StepType
from training_kb.pipelines.feedback import prepare_refine

REWRITE = {"number": 3, "text": "在會議頁面右上角選擇 Meeting Summary。",
           "feature_id": "Prepare", "type": "click_ui"}

def _run(world):
    return prepare_refine(world.diagnosis, repo=world.repo, writer=world.writer,
                          operations=world.operations, operation_id=world.operation_id)

def test_only_diagnosed_steps_change_and_others_are_byte_for_byte(world) -> None:
    world.writer.reply = {"steps": [REWRITE]}
    plan = _run(world)
    assert (plan.version_id, plan.base_version_id) == ("prepare-meeting@v2",
                                                       "prepare-meeting@v1")
    assert plan.changed_indexes == (3,)
    assert plan.reason == "feedback:8 則 找不到按鈕"
    assert plan.content.steps[2].text == REWRITE["text"]
    for number in (1, 2, 4):
        assert plan.content.steps[number - 1] == world.base.steps[number - 1]
    assert plan.content.model_dump(exclude={"steps"}) == world.base.model_dump(exclude={"steps"})

def test_model_touching_an_extra_step_is_rejected(world) -> None:
    world.writer.reply = {"steps": [REWRITE, {"number": 2, "text": "偷改的第二步。",
                                              "feature_id": "Prepare", "type": "read"}]}
    with pytest.raises(ContentError, match="改寫集合"):
        _run(world)
    assert world.repo.versions.get("prepare-meeting@v2") is None

def test_only_rules_injected_for_hit_steps_are_recorded(world) -> None:
    world.repo.rules = [rule("R-007", StepType.CLICK_UI), rule("R-012", StepType.READ),
                        rule("R-099", StepType.CLICK_UI, status="candidate")]
    world.writer.reply = {"steps": [REWRITE]}
    plan = _run(world)
    assert plan.rules_applied == ("R-007",)
    injected = world.writer.calls[0].user
    assert "[R-007]" in injected and "R-012" not in injected and "R-099" not in injected
```

第 1、4 步是 `read`，即使 `R-012` 也是 active，也不因「原文沿用」進入 `rules_applied`；candidate 永不入選（F29、`APL` Rule 2）。`rule(...)` 是同檔 helper，回一個 `AuthoringRule`，並在 `world.repo` 的 `operations/rules/validated_at.json` 放好每條的驗證時間。

- [ ] **Step 2：執行並確認紅燈**

```bash
uv run pytest tests/unit/test_feedback_refine.py -q
```

預期：FAIL，訊號包含 `cannot import name 'prepare_refine'`。

- [ ] **Step 3：建立最小實作**

```python
def _rules_for_hits(base, targets, *, repo):
    step_types = [step.type for step in base.steps if step.number in targets]
    by_type = rules_for_content(repo.list_rules(RuleStatus.ACTIVE), step_types,
                                load_validated_at(repo))
    selected: dict[str, AuthoringRule] = {}          # dict 保留插入順序，同一條只列一次
    for step_type in step_types:
        selected.update({item.rule_id: item for item in by_type[step_type]})
    return list(selected.values())

def _assert_unchanged(base, draft, changed: frozenset[int]) -> None:
    if base.model_dump(exclude={"steps"}) != draft.model_dump(exclude={"steps"}):
        raise ContentError("REFINE 不可改動命中步驟以外的段落")
    for left, right in zip(base.steps, draft.steps, strict=True):
        if left.number not in changed and left.model_dump() != right.model_dump():
            raise ContentError(f"未命中步驟 {left.number} 的原文必須逐字相同")

def _apply_rewrite(base, reply, targets: frozenset[int]):
    changed = {item["number"]: item for item in reply["steps"]}
    if set(changed) != set(targets):
        raise ContentError(f"改寫集合 {sorted(changed)} 不等於診斷命中集合 {sorted(targets)}")
    steps = []
    for step in base.steps:
        item = changed.get(step.number)
        if item is None:
            steps.append(step)                      # 未命中：整個物件原樣帶過
            continue
        if item["feature_id"] != step.feature_id or item["type"] != step.type:
            raise ContentError(f"步驟 {step.number} 不可改變引用的 Feature 或型態")
        text = str(item["text"]).strip()
        if not text:
            raise ContentError(f"步驟 {step.number} 的新文字是空的")
        steps.append(step.model_copy(update={"text": text}))
    draft = base.model_copy(update={"steps": steps})
    _assert_unchanged(base, draft, targets)
    return draft

def _known_feature_ids(repo) -> frozenset[str]:
    return frozenset(item_to_model(i, Feature).feature_id for i in repo.scan_entity("FEATURE"))

def prepare_refine(diagnosis, *, repo, writer, operations, operation_id):
    if not diagnosis.step_indexes:
        return None                                  # NO_STEP（F24）
    category, feedback_ids = evidence_of(diagnosis, repo=repo)
    base_version = repo.get_version(diagnosis.version_id)
    if base_version is None:                         # get_version 回 TutorialVersion | None
        raise ContentError(f"{diagnosis.version_id} 不存在")   # mypy strict 需要這道守門
    tutorial = repo.get_tutorial(base_version.slug)
    if tutorial is None or tutorial.current_version != diagnosis.version_id:
        raise ContentError(f"{diagnosis.version_id} 不是 {base_version.slug} 最近已發布的版本")
    base = parse_markdown(repo.get_object(base_version.s3_key).decode("utf-8"))
    targets = frozenset(diagnosis.step_indexes)
    rules = _rules_for_hits(base, targets, repo=repo)
    plan = allocate_version(base_version.slug, operation_id, operations, repository=repo,
                            reason=refine_reason(category, feedback_ids),
                            rules_applied=applied_rule_ids(rules))
    system, user = prompt_refine_steps(base, diagnosis, category, render_rules_block(rules))
    reply = writer.generate_json(system, user, StepRewrite,
                                 operation_id=operation_id, node=REFINE_NODE)
    draft = _apply_rewrite(base, reply, targets)
    validate_content(draft, known_feature_ids=_known_feature_ids(repo))
    create_version(plan, draft, repo)
    if not verify_version_complete(plan.version_id, repo):
        raise ContentError(f"{plan.version_id} 的內容或關係不完整")
    return RefinePlan(plan.version_id, base_version.version_id, plan.reason, draft,
                      tuple(sorted(targets)), plan.rules_applied,
                      evidence_fingerprint(diagnosis.version_id, category, feedback_ids))
```

`prompt_refine_steps` 加在 `writing/prompts.py`，回 `(system, user)`：system 說明「只輸出符合 schema 的 JSON、只能回列出的步驟編號、不可更動 `feature_id` 與 `type`」；user 依序放 `<active_rules>`（`render_rules_block` 的結果）、`<steps>`（只列命中步驟的 `number`／`type`／原文）與 `<source_data>`（該類別的 Feedback ID 與留言）。回饋留言是不可信文字，一律先經 [Phase 17](./17-Phase17-Claude結構化輸出與Prompt.md) 的 `_as_data`（`html.escape`）轉義再包進 `<source_data>`，當資料不當指令（D-67）；不得自創新的分區名稱。`create_version` 依 Phase 22／23 寫 `tutorials/prepare-meeting/v2.md` 與 `v2.diff`，`published_at` 保持 `null`。

- [ ] **Step 4：跑完整檔案確認綠燈**

```bash
uv run pytest tests/unit/test_feedback_refine.py -q
```

預期：PASS。另補三個案例並確認同樣是 `ContentError` 且沒有版本被建立：模型漏回命中步驟、把 `feature_id` 改成別的 Feature、改寫文字去空白後為空。

- [ ] **Step 5：提交**

```bash
git add src/training_kb/pipelines/feedback.py src/training_kb/writing/prompts.py tests/unit/test_feedback_refine.py
git commit -m "feat(feedback): REFINE 只改命中步驟並記錄注入規則"
```

### Task 3：lease、同 operation 重送與同證據不再產版

- [ ] **Step 1：建立失敗測試**

```python
from training_kb.errors import CoordinationError, TransientError
from training_kb.pipelines.feedback import DiagnosisResult

def test_lease_conflict_raises_transient_error(world) -> None:
    world.operations.hold("TUTORIAL#prepare-meeting", owner="op-other")
    with pytest.raises(TransientError):
        _run(world)

def test_operation_id_must_match_the_evidence(world) -> None:
    with pytest.raises(CoordinationError):
        prepare_refine(world.diagnosis, repo=world.repo, writer=world.writer,
                       operations=world.operations,
                       operation_id="op-feedback-review-demo-2026-09-13")

def test_no_step_and_same_evidence_return_none(world) -> None:
    world.writer.reply = {"steps": [REWRITE]}
    empty = DiagnosisResult("prepare-meeting@v1", (), {}, world.diagnosis.feedback_ids)
    assert prepare_refine(empty, repo=world.repo, writer=world.writer,
                          operations=world.operations, operation_id=world.operation_id) is None
    first = _run(world)
    assert first.version_id == "prepare-meeting@v2"
    assert _run(world) is None                       # 同一批證據：no_new_evidence（F23）
    assert world.writer.request_attempts == 1
    assert [key for key in world.repo.versions if key.startswith("prepare-meeting@")] == [
        "prepare-meeting@v1", "prepare-meeting@v2"
    ]
```

- [ ] **Step 2：執行並確認紅燈**

```bash
uv run pytest tests/unit/test_feedback_refine.py -q
```

預期：FAIL，訊號包含 `DID NOT RAISE TransientError` 與 `AssertionError`（第二次仍產生 v3 並再呼叫一次模型）。`test_operation_id_must_match_the_evidence` 這時可能因 `allocate_version` 找不到紀錄而先通過，Step 3 補上指紋守門後才是本 Phase 自己的斷言。

- [ ] **Step 3：把三道守門補進 `prepare_refine`**

```python
def _reuse_or_call(base, diagnosis, category, rules, *, record, repo, writer,
                   operations, operation_id):
    if record.model_output_refs:
        stored = repo.get_object(record.model_output_refs[-1])
        if stored is not None:
            return json.loads(stored.decode("utf-8"))       # 儲存重試不再呼叫模型
    system, user = prompt_refine_steps(base, diagnosis, category, render_rules_block(rules))
    reply = writer.generate_json(system, user, StepRewrite,
                                 operation_id=operation_id, node=REFINE_NODE)
    ref = operation_ref(operation_id, "refine-steps")
    repo.put_object(ref, json.dumps(reply, ensure_ascii=False).encode("utf-8"),
                    "application/json", if_none_match=False)
    operations.record_model_output(operation_id, ref)
    return reply

def _guard(diagnosis, category, feedback_ids, *, repo, operations, operation_id):
    if operation_id != refine_operation_id(diagnosis.version_id, category, feedback_ids):
        raise CoordinationError(f"{operation_id} 與本批證據的指紋不符")
    record = operations.load(operation_id)
    if record is None:
        raise CoordinationError(f"{operation_id} 尚未被 O2 接受")
    if record.version_id and verify_version_complete(record.version_id, repo):
        return None                                          # no_new_evidence（F23）
    return record
```

在 `prepare_refine` 裡照這個順序插進去：`evidence_of` 之後先 `record = _guard(...)`，`record is None` 就直接回 `None`；接著才取 `base_version` 與 `tutorial` 做基底核對；然後 `scope = f"TUTORIAL#{base_version.slug}"`（`LEASE#` 前綴由 Phase 11 自己補，00A §6.4），`operations.acquire_lease(scope, operation_id, ttl_seconds=LEASE_TTL_SECONDS, now=record.updated_at)` 為 `False` 時丟 `TransientError`；從選規則到 `verify_version_complete` 整段包在 `try` 裡，`finally` 呼叫 `operations.release_lease(scope, operation_id)`；原本直接呼叫 `writer.generate_json` 的那兩行改成 `reply = _reuse_or_call(base, diagnosis, category, rules, record=record, repo=repo, writer=writer, operations=operations, operation_id=operation_id)`。

- [ ] **Step 4：跑單元測試與 O2 整合測試**

```bash
uv run pytest tests/unit/test_feedback_refine.py -q
uv run pytest tests/integration/test_feedback_refine_retry.py -q
```

整合測試用真實 DynamoDB 與 S3（`@pytest.mark.aws`，未設 `TKB_RUN_AWS_INTEGRATION=1` 時 skip）：第一次在寫 STEP 關係前注入失敗，第二次用**同一個** `operation_id` 重送，斷言版號仍是 `prepare-meeting@v2`、`record.model_output_refs` 沒有增加、`writer.request_attempts == 1`。（現況核對 2026-09-14：原寫「**O2 未 PASS 前，本 Task 只能標 blocked**」——**O2 已於 P11 PASS**，所以這支整合測試要**實際以 `TKB_RUN_AWS_INTEGRATION=1` 執行**並把輸出寫進報告，不再標 blocked。）記憶體 fake 的綠燈本身仍不算永久去重已驗證，這一點不變。

- [ ] **Step 5：提交**

```bash
git add src/training_kb/pipelines/feedback.py tests/unit/test_feedback_refine.py tests/integration/test_feedback_refine_retry.py
git commit -m "test(feedback): 驗證 REFINE 租約、重送與同證據去重"
```

## 8. 驗收矩陣

| 路徑 | 輸入 | 預期資料結果 |
|---|---|---|
| Happy | 診斷只命中第 3 步、八筆同類證據 | 未發布的 `prepare-meeting@v2`；`changed_indexes=(3,)`、`reason="feedback:8 則 找不到按鈕"`。 |
| Failure | 模型額外回第 2 步，或改了 `feature_id`／`type` | `ContentError`；沒有任何 VERSION item 被建立。 |
| Failure | `operation_id` 不是證據指紋導出的 | `CoordinationError`；不配置版號。 |
| Boundary | `step_indexes == ()`；或相同八個 ID 第二次送（順序打亂、含重複） | 都回 `None`，不配版號也不呼叫模型；只有 v2，`request_attempts` 仍是 1。 |
| Retry | 寫關係時中斷後以同 operation 重送 | 同 `version_id`、重用既有模型輸出，補齊後才完整。 |
| Rules | 未改步驟的型態也有 active 規則 | 該規則不進 `rules_applied`、不進 prompt。 |

人工驗收：開啟 `tutorials/prepare-meeting/v2.diff`，逐行確認只有第 3 步變動；再查 operation 紀錄的 `version_id` 與 `model_output_refs`，確認一次 REFINE 只留一筆模型輸出。不能只看測試顯示 PASS。

## 9. 常見錯誤與停止條件

| 症狀 | 原因 | 修正／停止 |
|---|---|---|
| 同一批回饋每天多一版 | 去重只存在 process 記憶體，或 `operation_id` 沒有由指紋導出 | 停止每日排程，先修 `refine_operation_id` 與 O2 永久紀錄。 |
| 重送產生 v2、v3 | 沒有先讀 `record.version_id` 就重新配號 | 停止發布，回到 [Phase 20](./20-Phase20-版本分配與重試重用.md)／[Phase 11](./11-Phase11-O2接受順序與重啟整合驗證.md)。 |
| diff 包含未命中步驟 | 讓模型重新生成全文 | 未命中步驟必須從 base 原樣帶過，並用 `_assert_unchanged` 逐欄比較。 |
| 所有 active 規則都進 `rules_applied` | 把「沿用原文」當成本次套用 | 只記本次 prompt 真正注入的 ID（F29）。 |
| `StepRewrite.model_validate(...)` 找不到方法；`rules_for_content` 解包成兩個值 | 把 JSON schema 字典當成 pydantic 類別；照舊草稿寫成 `(list, str)` | `generate_json` 回 `dict`，用 `reply["steps"]`（D-02）；`rules_for_content` 回 `dict[StepType, list[AuthoringRule]]`（D-03）。 |
| 本階段就把 v2 寫進 `site/` | 把建版與發布混成一步 | 建版只寫私有前綴，`published_at` 保持 `null`；發布是 Phase 48 的事，O3 未 PASS 不得宣稱可公開。 |

## 10. 來源與 Rule 對照

- [定期檢視回饋.feature](../../spec/features/定期檢視回饋.feature)（本文件縮寫 `REV`）
  - Rule 7：「REFINE 只重寫診斷命中的步驟」→ **primary 在本 Phase**；Task 2 的 `test_only_diagnosed_steps_change_and_others_are_byte_for_byte` 直接斷言 `changed_indexes` 恰等於診斷集合，且其餘步驟 `model_dump()` 相同。
  - Rule 8：「REFINE 的下一版 reason 記錄回饋數與類別」→ **primary 在本 Phase**；Task 1 的 `test_reason_counts_unique_evidence` 與 Task 2 直接斷言 `reason == "feedback:8 則 找不到按鈕"`。
- [建立教學版本.feature](../../spec/features/建立教學版本.feature)（`VER`）Rule 2「任一 pipeline 修改既有教學時使用該篇的下一個版本號」→ 相關（primary 在 [Phase 20](./20-Phase20-版本分配與重試重用.md)，本文件只透過 `allocate_version` 取號）；Rule 4「每次建立版本都記錄引起變更的 reason」→ 相關（primary 在 [Phase 23](./23-Phase23-未發布版本與關係完整寫入.md)，本文件只負責 reason 的內容）。
- [套用教學規則.feature](../../spec/features/套用教學規則.feature)（`APL`）Rule 1「CREATE、UPDATE 與 REFINE 在寫作前讀取教學規則」→ 相關（primary 在 [Phase 19](./19-Phase19-Active規則選取與注入.md)）；Task 2 斷言 prompt 組出前已選好規則。
- [接入來源事件.feature](../../spec/features/接入來源事件.feature)（`ING`）Rule 30「同一正規化事件重送時只處理一次」→ 相關（primary 在 [Phase 10](./10-Phase10-O2操作紀錄與永久去重契約.md)）；Task 3 只是 REFINE 重送情境的再驗。
- Supporting：F23（同一批證據不可再次觸發 REFINE，完成後記錄已處理證據集合）、F29（沿用原文不算本次套用）、F24（無有效步驟不建版）、F48（schema 通過仍要業務驗證）、D28（reason 格式 `feedback:<n> 則 <category>`）。
- 設計 §7.5（REFINE 與「沒有新有效證據就不再產版」）、§7.6（改寫步驟只改命中集合、其餘逐字相同）、§8.1–§8.2（版本鏈、基底與 `create_version` 完成條件）、§14.1–§14.2（部分寫入保留未完成版本、重送重用模型輸出與版號）、§18（O2／O3）。
- 契約來源：[00A 共用契約與名詞](./00A-共用契約與名詞.md) §3.3（reason 三種格式、步驟編號一律 `number`）、§6.5（`generate_json`／`StepRewrite`／Phase 19 四個函式）、§6.6（`allocate_version`／`create_version`）、§6.9（`RefinePlan`／`prepare_refine` 與 `repo=`）、§8 D-02／D-03／D-04／D-28／D-55。

## 11. 完成清單

- [ ] `RefinePlan` 七個欄位、`prepare_refine` 簽名與 `repo=` 參數名符合 00A §6.9。
- [ ] 指紋對順序與重複 ID 穩定，換版本或換類別一定不同；平均分與留言原文不進指紋。
- [ ] `reason` 是 `feedback:<去重後筆數> 則 <類別>`，與 00A §3.3 的三種格式之一逐字相同。
- [ ] 新版只改診斷命中步驟；其餘步驟與四個段落逐字相同，違反時是 `ContentError` 且不建版。
- [ ] `rules_applied` 只含本次 prompt 真正注入的 active 規則；candidate 與未改步驟的規則都不入選。
- [ ] `NO_STEP` 與 `no_new_evidence` 都回 `None` 且沒有配版號、沒有模型呼叫；儲存中斷後以同 operation 重送時版號與模型輸出都重用。
- [ ] `REV` Rule 7、8 有直接 assertion，`VER` 2／4、`APL` 1、`ING` 30 標為相關並指出 primary。
- [ ] 未把記憶體 fake 或假 Writer 的綠燈當成證據；gate 語氣照現況：**O2 PASS**（整合測試要真的跑）、**O3 FAIL**、**O5 BLOCKED**；也沒有把未發布版本寫進 `site/`。
- [ ] `pipelines/feedback.py` 與 `writing/prompts.py` 只用 Edit 追加 `# ---- Phase 46 ----` 自己的區段，沒有動 P44／P45／P47 的程式或格式。
