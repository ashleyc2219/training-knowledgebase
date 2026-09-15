# P45 brief — 回饋診斷與命中步驟

## 1. 單一交付物與停止點
- **交付物**：`pipelines/feedback.py` 的 `DiagnosisResult`／`DIAGNOSE_NODE`／`diagnose_weak`，加上 `writing/prompts.py` 的 `prompt_diagnose_weak`——把 `WeakTarget` 交給模型診斷，只留下真實存在且理由非空的步驟 `number`。
- **停止點**：回一個 `DiagnosisResult`（`step_indexes` 可為 `()` 代表 `NO_STEP`）。**不寫任何 DynamoDB item 或 S3 物件、不建版、不發布、不碰 `OperationCoordinator`。**

## 2. 已存在、直接重用
- `src/training_kb/writing/schemas.py:92` `WeakDiagnosis` — schema **dict**，`required:["items"]`、`items[{number:int>=1, reason:非空}]`、`additionalProperties:False`、`items` 可為空陣列。**沒有同名 pydantic 類別，別寫 `model_validate`。**
- `src/training_kb/writing/client.py:51` `Writer.generate_json(system, user, schema: Mapping, *, operation_id, node) -> dict[str, Any]`（吃 dict、回 dict，D-02）。
- `src/training_kb/writing/prompts.py:29` `_as_data(text)`（`html.escape(text, quote=False)`）＋ `<source_data>` 分區契約（D-67）。同檔現有：`prompt_write_tutorial`（:34）、`prompt_name_gap`（:65）。
- `src/training_kb/repository.py:558` `get_steps(version_id) -> list[TutorialStep]`（依 `number` 升序，唯一 `meta_only=False` 的呼叫點）；`:579` `list_feedback_of_version`。
- `src/training_kb/models.py:208` `TutorialStep(tutorial_version, number, type, text, feature_id)`；`:347` `Feedback`；`StepType`（同檔）。
- `src/training_kb/errors.py:12` `ContentError(PermanentError)`。
- `tests/unit/conftest.py:13` `RecordingWriter(replies=[...])` — `calls` 是 **dict 清單**（`calls[0]["user"]`、`["node"]`、`["schema"]`），有 `request_attempts`。
- `src/training_kb/pipelines/feedback.py` — controller 預建空殼，只 Edit。

## 3. 要新增／修改的東西
**兩支共用檔（W1 併行：P44 ∥ P45 ∥ P47）**

`src/training_kb/pipelines/feedback.py`（區段 `# ---- Phase 45 ----`）
- **擁有**：`DIAGNOSE_NODE = "diagnose_weak"`、`DiagnosisResult`、`diagnose_weak`、`_validated_items`。
- **不得碰**：P44 的 `ReviewMode`／`WeakTarget`／`is_weak`／`select_weak_targets`／`_average`／`_top_category`；P47 的 `CandidateGroup`／`MIN_CANDIDATE_FEEDBACK`／`PROPOSE_NODE`／`candidate_groups`／`candidate_rule_id`／`propose_candidate`；P46／P48 的所有名稱。

`src/training_kb/writing/prompts.py`（區段 `# ---- Phase 45 ----`）
- **擁有**：`prompt_diagnose_weak`。**不得碰**：`_as_data`、`prompt_write_tutorial`、`prompt_name_gap`（P17），以及同波次 P47 的 `prompt_propose_rule`。

00A §6.9 canonical 簽名：
```python
DIAGNOSE_NODE = "diagnose_weak"
@dataclass(frozen=True)
class DiagnosisResult:
    version_id: str
    step_indexes: tuple[int, ...]   # 裝的是步驟 number（從 1 起），不是 0-based index（D-55）
    reasons: dict[int, str]         # 鍵同樣是步驟 number
    feedback_ids: tuple[str, ...]
def diagnose_weak(target: WeakTarget, *, repo: "Repository", writer: "Writer",
                  operation_id: str) -> DiagnosisResult: ...
def prompt_diagnose_weak(version_id: str, steps: Sequence["TutorialStep"], category: str,
                         feedback: Sequence["Feedback"]) -> tuple[str, str]: ...
```
**`repo=` 不是 `repository=`**（P46／P47／P48 一致）。新檔：`tests/unit/test_feedback_diagnosis.py`。

## 4. Task 順序與紅燈訊號
1. **Task 1（有效診斷的資料契約）** — `prompt_diagnose_weak` 先放回 `("", "")` 的空殼。
   `uv run pytest tests/unit/test_feedback_diagnosis.py::test_diagnose_weak_keeps_only_existing_steps -q` → `cannot import name 'diagnose_weak'`。
2. **Task 2（`NO_STEP` 與重複編號）**
   `uv run pytest tests/unit/test_feedback_diagnosis.py -q` → 三筆 FAIL：空白原因、`True` 編號兩個 `AssertionError`，衝突原因是 `Failed: DID NOT RAISE`。
3. **Task 3（prompt 不跨版跨類洩漏）** — 把空殼換成真 renderer。
   `uv run pytest tests/unit/test_feedback_diagnosis.py::test_prompt_only_contains_target_version_and_evidence -q` → `AssertionError`（空殼回 `("", "")`）。
收尾：`uv run ruff check src tests infra`、`ruff format --check`（共用檔不通過就只修自己那段）、`uv run mypy`、`uv run pytest tests -q -W error`。

## 5. 00B primary Rule 與測試檔
| Rule | 內容 | 測試 |
|---|---|---|
| `REV` 5（primary） | 診斷結果含步驟編號與原因 | `test_feedback_diagnosis.py::test_diagnose_weak_keeps_only_existing_steps` |
| `REV` 6（primary） | 找不到有效步驟時不建新版 | `test_diagnose_weak_returns_no_step_for_no_valid_item`（`step_indexes == ()`） |
支援：F24、F45、F48。

## 6. 風險與陷阱
- **fixture 撞名**：`tests/unit/conftest.py` 已有 `fake_writer`（回 `RecordingWriter`）。在測試模組再定義同名 fixture 會**無聲覆蓋**（`tests/unit/pipelines/conftest.py` 檔頭已為同一陷阱留警語）。**建議改名 `diagnosis_writer`，或直接用 `RecordingWriter(replies=[...])`。**
- **`RecordingWriter.calls` 存 dict**，不是物件：用 `call["user"]`／`call["node"]`，文件原本寫 `call.user` 已在文件修正。
- `bool` 是 `int` 子類 → `True in frozenset({1})` 成立。`_validated_items` 必須先 `isinstance(number, bool)` 擋掉。
- 同 `number` 同原因去重、同 `number` 不同原因 **丟 `ContentError`**（不可任選一筆），否則重送不穩定。
- `step_indexes`／`reasons` 這兩個名字**不改**（P46/P48 已消費），但裝的是 `number`（D-55）；模型 schema 一律 `items[].number`，程式與測試**不得出現 `index` 這個鍵名**（D-11）。
- `generate_json` 在整個函式**只出現一次**（測試斷言 `len(calls) == 1`）。
- gate：**O5 BLOCKED**（不是「尚未通過」）——只能用假 Writer，`TKB_GENERATION_MODEL_ID` 不得填猜測值；真實 AWS 上 `diagnose_weak` 節點會走 `Catch → PipelineFailed`，那是 BLOCKED 證據。O2 PASS／O3 FAIL 不阻擋本 Phase。
- 不用 `generate_validated_json`（那是需要業務 validator 修正迴圈的節點；本 Phase 自己做 post-validation，`ContentError` 直接往外丟）。

## 7. 需要裁決的點 → 建議裁決
- 替身命名 → **`diagnosis_writer`**（避免覆蓋 conftest 的 `fake_writer`），在報告寫明「本計畫選擇」。
- 「原因不同的重複編號」處理 → **丟 `ContentError`**（文件已定為本計畫選擇），照做。
- 要不要包 `generate_validated_json` 做一次修正 → **不要**；D-11／§6.5 沒把本節點列為修正迴圈節點，維持一次呼叫。

## 8. 對 AWS 的實際操作
無。本 Phase 沒有整合測試、沒有 `@pytest.mark.aws`、不連 Bedrock。
