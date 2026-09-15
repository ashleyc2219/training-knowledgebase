# P43 brief — Feedback 類別判定

波次 **W3**。前置：**P42（W2）** 必須先落地。文件：`docs/plan/unfinish/43-Phase43-Feedback類別判定.md`
（已於 2026-09-14 W0 更新，commit `bc28a42`）。開工前先**讀 P42 實際寫出來的程式**，不要照 P42 的文件片段。

## 1. 單一交付物與停止點

- **交付物**：一筆回饋的 `category` 怎麼定——勾選優先、未勾且留言非空才呼叫**一次**模型、
  任何未核定值收斂成 `待分類`；核定類別表 `CONFIG#feedback_categories` 只讀。
- **停止點**：不寫入／不擴充核定表、不覆蓋使用者勾選、不重新分類既有回饋、不因類別觸發改版、
  不算指標、不判弱教學（P44）。

## 2. 已存在、直接重用

| file:name | 用途 |
|---|---|
| `src/training_kb/writing/schemas.py::CommentClassification` | dict schema，`$id == "CommentClassification"`、`required: ["category"]`、`additionalProperties: false`。**不是** Pydantic 類別 |
| `src/training_kb/writing/client.py::Writer.generate_json(system, user, schema, *, operation_id, node) -> dict[str, Any]` | 吃 schema dict、回 dict（D-02） |
| `src/training_kb/writing/client.py::inference_config(schema)` / `JUDGEMENT_INFERENCE_CONFIG` | 依 `$id` 查 `WRITING_MAX_TOKENS`；`CommentClassification` 不在表裡 → 自動 `{"maxTokens": 512, "temperature": 0.1}`，**永不設 `topP`**（00A §3.7）。本階段不必傳任何判斷參數 |
| `src/training_kb/writing/prompts.py::_as_data(text)` | `html.escape(text, quote=False)`；`<source_data>` 分區（D-67）。`json`／`html` 已在檔頭 import |
| `src/training_kb/repository.py::get_meta_item(pk) -> DynamoItem \| None` | 讀 `CONFIG#feedback_categories`（P10 原語，`CONFIG#` 不走模型） |
| `src/training_kb/repository.py::put_meta_item(pk, attrs, *, create_only=True) -> bool` | **只在測試 fixture 裡**用來塞設定 item；產品程式不寫這個 PK |
| `src/training_kb/ingress.py::operation_id_for("feedback", "f_50")` | 實際回 `op-feedback-f_50` |
| `src/training_kb/models.py::Feedback` | frozen；`model_copy(update=...)` **不重跑 validator**（`carries_signal` 不會被觸發） |
| `tests/unit/conftest.py::RecordingWriter` / `fake_writer` fixture | `replies` 佇列、`request_attempts`、`calls`（**dict**，鍵 `kind`／`operation_id`／`node`／`system`／`user`／`schema`） |
| `tests/integration/conftest.py::repository` | moto 表＋bucket |
| P42 的 `tests/integration/test_fixed_import.py`、`tests/unit/infra/test_import_lambda.py` | 本階段沿用、追加，不新建檔 |

## 3. 要新增／修改

- **`src/training_kb/ingress.py`**（W3 只有你動；W4 是 P59）——`# ---- Phase 43 ----` 區段：
  - `PENDING_CATEGORY = "待分類"`、`DEFAULT_FEEDBACK_CATEGORIES = frozenset({"找不到按鈕","缺少資訊"})`、
    `FEEDBACK_CATEGORIES_PK = "CONFIG#feedback_categories"`、`CLASSIFY_NODE = "classify_comment"`
  - `def approved_categories(repository: Repository) -> frozenset[str]`
  - `def classify_feedback_category(feedback: Feedback, *, approved: frozenset[str], writer: Writer, operation_id: str) -> str | None`
  - private `_settle(value, approved)`、`_resolve_category(...)`
  - **改 P42 的 `import_feedback`**：加尾巴 keyword `writer: Writer | None = None`（有預設，P42 呼叫端不受影響）
- **`src/training_kb/writing/prompts.py`**（Edit-only、只加自己區段、不整支 `ruff format`）：
  `def prompt_classify_comment(comment: str, approved: frozenset[str]) -> tuple[str, str]`
- **`src/training_kb/handlers/import_.py`**：`_import_one` 傳 `writer=_DEPS.writer`（**直接讀屬性，不用 `need_writer()`**
  ——沒接線時的語意是「只收斂勾選值」，不是丟 `PermanentError`）。
- **`infra/training_kb_stack.py`**（**W3 同時有 P48／P52 在改** → Edit-only、自己的區段、`git add` 只加自己路徑）：
  `import_fn.add_to_role_policy(iam.PolicyStatement(actions=["bedrock:InvokeModel"], resources=approved_model_arns))`。
  **只加這一條，不新增環境變數**（`TKB_GENERATION_MODEL_ID` 已在 P41 的 `base_env`；O5 BLOCKED 不得填猜測值）。
- **測試**：`tests/unit/test_feedback_category.py`（新）；追加到 `tests/integration/test_fixed_import.py`
  與 `tests/unit/infra/test_import_lambda.py`（都是 P42 的檔，P42 在 W2 已完成，W3 動不會撞車）。

## 4. Task 順序與紅燈訊號

| Task | 指令 | 預期紅燈訊號 |
|---|---|---|
| 1 核定表只讀＋未知值收斂 | `uv run pytest tests/unit/test_feedback_category.py -q` | `cannot import name 'approved_categories' from 'training_kb.ingress'` |
| 2 四條分支＋呼叫次數＋prompt | `uv run pytest tests/unit/test_feedback_category.py -q` | `cannot import name 'classify_feedback_category'` |
| 3 接上固定匯入＋CDK 權限 | `uv run pytest tests/integration/test_fixed_import.py::test_import_saves_settled_category_and_resend_calls_no_model -q` | `import_feedback() got an unexpected keyword argument 'writer'` |

收尾：`uv run pytest tests -q -W error`、`uv run ruff check src tests infra`、
`uv run ruff format --check src tests infra`、`uv run mypy`。
紅燈若來自 P48／P52／P55／P58 進行中的檔，`--ignore=` 排除並寫進報告（R3.5）。

## 5. 00B primary Rule → 測試

| Rule | 測試 |
|---|---|
| `COL` 4 勾選優先於模型分類 | `test_feedback_category.py` 決策表第 1 列，`request_attempts == 0` |
| `COL` 5 類別必須屬核定表或待分類 | `test_feedback_category.py` 的 `_settle` 測試＋決策表第 2 列（`介面太醜` → `待分類`） |
| `COL` 6 需要分類的留言在接入時算一次 | `test_feedback_category.py` 第 3–5 列＋`test_fixed_import.py` 的重送案例（`request_attempts == 1`） |

相關（不重新認領）：`ING` 25（primary P31）、`COL` 3／10（primary P42）。
另外兩條由 P18 的既有測試覆蓋、本階段只是消費：`max_tokens` 512 與 `temperature` 0.1（00B `GEN` 4／9）。

## 6. 風險與陷阱

1. **`CommentClassification` 是 dict 不是模型**：`reply.get("category")`，不要 `reply.category`／`model_validate`。
2. **不走 correction**（00A validator 那一列逐字寫明）：直接 `Writer.generate_json`，**不要** `generate_validated_json`；
   未知值由 `_settle` 降級，全程**只有一次** request。
3. **分類的位置**：必須在 `operations.accept` 回 accepted **之後**、`put_meta` **之前**；
   續跑補寫分支（accept 回 duplicate 但物件不存在）也要走一次；物件已存在的真 duplicate 完全不進這條路徑。
   放在 `accept` 之前 → 每次重送都多一次 Bedrock 呼叫。
4. **`_settle` 的空值語意**：空字串／`None` 回 `None`（= 決策表第 3 列「只有評分」），**不要**回 `PENDING_CATEGORY`。
5. **`model_copy(update=...)` 不重跑 validator**（Pydantic v2）——所以 `category=None` 不會踩到 `carries_signal`。
   不要改成 `Feedback(**{...})` 重建。
6. **FakeWriter 形狀**：`RecordingWriter.calls` 是 **dict**，文件原本的 `Call` NamedTuple 不相容（00A 要求相容）。
   單元測試直接用 `fake_writer` fixture；整合測試（看不到 `tests/unit/conftest.py`）自己宣告一份 dict 版。
   **`tests/unit/conftest.py` 這一批只有 P55 可以動**（R3.6）。
7. **`approved_categories` 的降級**：`categories` 非 list／空 list／缺欄位／item 不存在 → 一律回
   `DEFAULT_FEEDBACK_CATEGORIES`，**不得回空集合**（會讓 P44 的同類計數全部歸零）。
8. **prompt 分區**：只能用 P17 既有的 `<source_data>` 與 `_as_data`，不得自創標記名（P60 的
   `check_output_safety` 只認這一個）。prompt 不得含評分或 `user` ID。
9. **O5 BLOCKED**：FakeWriter 綠燈 ≠ Bedrock 可用。真實 AWS 上這個節點會 `PermanentError → Catch → PipelineFailed`，
   那是 BLOCKED 證據。報告不得寫成通過。`writer=None` 只是 P42 單獨執行的行為，不是 O5 的替代方案。
10. **CDK 權限沒加或 handler 沒傳 writer**，雲端第一次分類會 `AccessDeniedException`／永遠不分類。兩件都要做。

## 7. 需要裁決的點 → 建議裁決（可直接採用）

| 點 | 建議 |
|---|---|
| P43 到底要改 stack 什麼？ | **要改程式**：對 P42 的 `import_fn` 加一條 `bedrock:InvokeModel`（只限核定生成模型 ARN，與 P41 給 `task_fn` 同寫法）。**不新增環境變數。** |
| 這條權限的 `Template` 斷言放哪？ | 追加到 P42 的 `tests/unit/infra/test_import_lambda.py`（00A §3.3 沒給 P43 infra 測試檔；不新建檔名）。 |
| FakeWriter vs `fake_writer` fixture | 單元測試用既有 `fake_writer`；整合測試自宣告 dict 版本地 FakeWriter。 |
| `Deps.writer` 用 `need_writer()` 嗎？ | 不用。直接讀 `_DEPS.writer`，`None` 代表「只收斂勾選值」。 |
| `_settle` 是 private 但單元測試要 import | 保持 private，測試 `from training_kb.ingress import _settle`（同模組單元測試，ruff 不擋）。 |

## 8. 對 AWS 的實際操作

本 Phase **不跑真實 AWS**。`Template.from_stack` 的斷言在 `uv run pytest` 下即可；
若要順手 synth：`AWS_REGION=us-east-1 AWS_DEFAULT_REGION=us-east-1 command npx aws-cdk@2 synth
--outputs-file <scratchpad>/out.json`（`node` 被本機 shell 擋住，必須 `command npx`；不要提交 `cdk.out/`）。
真實 Bedrock 呼叫在 O5 解除前一律 BLOCKED，不要為了「試一下」去改 `TKB_GENERATION_MODEL_ID`。
