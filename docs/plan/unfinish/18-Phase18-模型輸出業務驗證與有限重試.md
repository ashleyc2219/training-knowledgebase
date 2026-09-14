# Phase 18 模型輸出業務驗證與有限重試實作計畫

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 schema 驗證之後執行 context-aware 業務驗證，模型結果不合法時最多修正一次，仍不合法便確定失敗。

**Architecture:** 呼叫端採固定演算法：`generate_json → business validator → 最多再 generate_json 一次 → PermanentError`。這個 correction loop 是 module-private；不新增跨 Phase public 介面，也不與 Step Functions 暫時錯誤 Retry 疊加。

**Tech Stack:** Python 3.12、Phase 15–17 的 Writing 邊界、`botocore.config.Config`、pytest；Step Functions 的 Retry／Catch 由 Phase 29 實作。

## Global Constraints

- 一次 Task 執行內，同一個節點的生成 request 總嘗試最多 2 次：原始輸出 1 次、業務修正 1 次。第三次 request 出現即停止。
- schema 合法仍必須經業務 validator；validator 使用呼叫當下的 Feature、原步驟、命中集合或核定類別 context。
- 只有單一層管理同一種 retry：SDK 自動 retry 關閉、`generate_validated_json` 不重試服務故障、Step Functions Task Retry 是唯一的暫時錯誤重試層。
- 儲存或網路寫入 retry 必須重用 O2 已保存的合法模型輸出（`OperationRecord.model_output_refs`），不再次呼叫模型。
- Claude 生成 request 固定帶 `maxTokens`、逾時與 `temperature=0.1`，不同時設 `topP`；Titan embedding 仍不接受生成參數。
- 錯誤訊息與 `CallTrace` 只寫 validator 代碼與欄位名，不回印模型輸出、prompt 原文、回饋留言或 secret。
- 本 Phase 不發布、不建立版本，也不宣稱 O5 已通過或 Step Functions 已配置完成。

---

## 1. 文件定位

- **讀者：** 要把 Claude 結果接到 Ticket、Release 或 Feedback 流程的工程師。
- **唯一主來源：** [Training Knowledge Base 設計 §7.6、§14.1–§14.3、§15](../../design/training-kb.md)。
- **前置 Phase：** [Phase 02](02-Phase02-設定時間與錯誤契約.md) 的錯誤分類、[Phase 10](10-Phase10-O2操作紀錄與永久去重契約.md)／[Phase 11](11-Phase11-O2接受順序與重啟整合驗證.md) 的 operation 紀錄、[Phase 14](14-Phase14-O5模型可用性與參數驗證.md) 的 O5 gate、[Phase 15](15-Phase15-Writing介面與呼叫追蹤.md) 的 `CallTrace`、[Phase 17](17-Phase17-Claude結構化輸出與Prompt.md) 的八個 schema。
  **實作時的實況（controller 2026-09-14 裁決）：** O5 gate 因帳號未開通 Bedrock 而 BLOCKED，Phase 10／11 也尚未實作。裁決是「真實整合測試維持 FAIL／skip，其餘照常」——本 Phase 的程式與單元測試照常完成（假的 converse 回應），`tests/integration/test_claude_validation.py` 照文件寫並標 `@pytest.mark.aws`，不填猜測 model ID、不放寬斷言；Phase 10 的 `OperationCoordinator`／`operation_ref` 在單元測試裡先用同形的本地替身（見 Task 3 Step 1）。
- **下一 Phase：** [Phase 19](19-Phase19-Active規則選取與注入.md) 選規則；[Phase 21](21-Phase21-教學內容與步驟引用驗證.md) 的 `validate_content` 是同一個 callback 契約的最大使用者；[Phase 29](29-Phase29-共用Pipeline執行器與ASL失敗語意.md) 處理暫時故障的 Retry／Catch。
- **這一階段不做：** 不把業務失敗當服務暫時故障、不無限加長 prompt、不引入人工審核佇列、不自己實作 Step Functions Retry。

## 2. 你在整體流程的位置

```text
generate_json attempt 1（Phase 15 送出，Phase 17 驗 schema）
          |
          v
[你在這裡：business validator] --非法--> correction attempt 2 --非法--> PermanentError
          | 合法                                   | 合法
          v                                        v
 record_model_output（O2 保存 output ref）  <-------+
          |
          v
 儲存 retry 只讀 model_output_refs[-1]，不再叫模型
```

## 3. 完成後看得到什麼

具體輸入：`StepRewrite` JSON 結構完整，但回傳 `number=2`，而 Release 命中集合只有 `{3}`（`prepare-meeting@v2` 的第 3 步）。

可觀察結果：第一次業務驗證拒絕並丟 `ContentError("step_number_not_in_hit_set")`；修正 prompt 只附上這個代碼與 `allowed_step_numbers=[3]`，不附回饋原文；第二次仍回 `number=2` 時丟 `PermanentError`，`CallTrace.count(operation_id="op-release-r_42") == 2`（單元測試用 Phase 15 的共用替身時看 `fake_writer.request_attempts == 2`），repository 沒有新版本。

### 名詞小抄

| 名詞 | 白話意思 |
|---|---|
| 業務驗證 | schema 之外、要有當下資料才能判斷的檢查，例如這個 `feature_id` 在資料庫裡到底存不存在。 |
| correction（一次修正） | 模型輸出業務不合法時，把違規代碼回饋給模型再要一次；本專案固定只給一次機會。 |
| `TransientError`／`PermanentError` | 暫時性故障（重送有機會成功）／確定不合法（重送沒意義），由 Phase 02 定義；同一種重試只由一層管理，三層都重試會讓次數相乘。 |
| output ref | 模型輸出存進私有 S3 後的 key，記在 operation 紀錄的 `model_output_refs`；儲存重試只讀它，不重新叫模型。 |
| `inferenceConfig` | Bedrock `Converse` 請求裡放 `maxTokens`、`temperature` 的欄位；Titan embedding 不吃這些生成參數。 |

## 4. 預計新增／修改的檔案

以下是實作時預計建立或修改，本計畫本身不代表它們已存在：

| 動作 | 路徑 | 責任 |
|---|---|---|
| 建立 | `src/training_kb/writing/validators.py` | `BusinessValidator` 型別，以及可在本階段固定 context 契約的業務檢查 factory。 |
| 修改 | `src/training_kb/writing/client.py` | module-private correction loop、生成參數與 SDK 逾時設定（Phase 15 已建立此檔）。 |
| 建立 | `tests/unit/test_writing_validation.py` | schema-pass／business-fail、一次修正、生成參數與輸出重用。 |
| 沿用 | `tests/unit/conftest.py` | [Phase 15](15-Phase15-Writing介面與呼叫追蹤.md) 的共用替身：回應排進 `fake_writer.replies`，實際送出的次數看 `fake_writer.request_attempts`；本 Phase 不另建一個 `FakeWriter`。 |
| 建立 | `tests/integration/test_claude_validation.py` | O5 通過後記錄真實的兩次上限；預設 skip。 |

## 5. 固定介面

### Consumes

```text
Writer.generate_json(system: str, user: str, schema: Mapping[str, Any], *,
                     operation_id: str, node: str) -> dict[str, Any]          # Phase 15
CallTrace.count(*, operation_id: str | None = None) -> int                     # Phase 15
bedrock_config() -> Config                                                     # Phase 15（writing/client.py 唯一定義）
八個 schema（dict）與 validate_schema(schema, payload)                          # Phase 17
OperationCoordinator.record_model_output(operation_id: str, output_ref: str) -> None   # Phase 10
OperationCoordinator.load(operation_id: str) -> OperationRecord | None         # Phase 10
OperationRecord.model_output_refs: tuple[str, ...] / operation_ref(op, name)   # Phase 10
Repository.put_object / get_object                                             # Phase 07
ContentError / PermanentError / TransientError                                 # Phase 02
```

`OperationRecord` **沒有** `output_ref` 欄位，取最後一次保存的輸出一律用 `model_output_refs[-1]`。

### Produces

```python
BusinessValidator = Callable[[dict[str, Any]], None]

def generate_validated_json(writer: "Writer", system: str, user: str,
                            schema: Mapping[str, Any], validate: BusinessValidator,
                            *, operation_id: str, node: str) -> dict[str, Any]: ...

def gap_naming_validator(*, known_feature_ids: frozenset[str]) -> BusinessValidator: ...
def step_rewrite_validator(*, allowed_steps: frozenset[int],
                           allowed_features: frozenset[str]) -> BusinessValidator: ...
def inference_config(schema: Mapping[str, Any]) -> dict[str, object]: ...
```

`bedrock_config()` **不是本 Phase 產出**：它在 [Phase 15](15-Phase15-Writing介面與呼叫追蹤.md) 的 `writing/client.py` 已經定義（`connect_timeout=2`、`read_timeout=30`、`retries={"total_max_attempts": 1}`），本 Phase 只消費它、用測試把那三個值鎖住，不再寫第二份。

`generate_validated_json` 是**公開**的修正迴圈入口（由 `writing/__init__.py` re-export）：P39–P51 需要業務驗證的節點一律 import 它、**呼叫一次**，不自己重試、也不自己再組一次修正 prompt——「最多一次修正」這個上限只在這支函式裡成立，複製一份等於把上限複製壞。回傳值是**同時**通過 schema 與指定 business validator 的 dict，可交 O2 保存；兩次後仍不合法丟 `PermanentError`，訊息只列 validator 代碼與不合法欄位；`TransientError` 不被攔截，直接往上交給 Phase 29 的單層 Task Retry。

八個 schema 的業務檢查接入點如下。`writing/validators.py` 收錄可在本 Phase 就固定契約的 factory，其餘由對應 Phase 依同一個 `BusinessValidator` 形狀提供；同一項檢查不得兩份並存，消費 Phase 的 private helper（例如 Phase 39 的 `_validated_naming`）應包裝本 Phase 的 factory，而不是另寫一份：

| Schema | schema 之外必須驗的 | 提供者 | 走 correction？ |
|---|---|---|---|
| `GapNaming` | `feature_id` 是既有 Feature 或 `null`；一張 Ticket 最多一個 Feature | 本 Phase `gap_naming_validator` | 是 |
| `TutorialDraft` | 五段非空、每步恰一個既有 Feature、型態合法、編號連續 | Phase 21 `validate_content`（Phase 40 呼叫） | 是 |
| `StepRewrite` | 編號在命中集合內、`feature_id` 存在；未命中步驟逐字相同 | 本 Phase `step_rewrite_validator` + Phase 51 `assert_unchanged` | 是 |
| `CommentClassification` | `category` 在「核定類別加 `待分類`」之內 | Phase 43 的 `_settle` | 否：只呼叫一次，未知值降級成 `待分類`，不得為此多叫一次模型 |
| `RuleProposal` | evidence 是本組 Feedback ID、`derived_from` 恰一版、`applies_when` 轉成 `StepType` | Phase 47 | 是 |
| `ConflictJudgement` | `rule_ids` 存在且適用範圍相同 | Phase 55 | 是 |
| `StepConfirmation` | 編號屬於候選版的已發布步驟 | Phase 50 | 否：不在候選內就丟棄 |
| `WeakDiagnosis` | `items[].number` 是目前版本的步驟、`reason` 非空、重複編號原因一致 | Phase 45 | 否：無效項目直接丟棄 |

重試只有一層，三個位置的責任如下：

```text
設計 §14.3「只讓一層管理重試，避免 SDK 與 Task 次數相乘」

botocore Config(retries={"total_max_attempts": 1})  -> SDK 完全不重試
        |
        v
generate_validated_json: attempt 1 --業務不合法--> attempt 2 --仍不合法--> PermanentError
        |  TransientError（服務故障；不算一次修正，也不在這裡重試）
        v
ASL Retry ["TransientError"] IntervalSeconds 1 / MaxAttempts 2 / BackoffRate 2
        |
        v
Catch States.ALL -> PipelineFailed（Phase 29；Catch 之後不得產生新版本）
```

## 6. TDD Tasks

### Task 1：先證明 schema-pass 仍可 business-fail

**Files:**

- Create: `src/training_kb/writing/validators.py`
- Create: `tests/unit/test_writing_validation.py`

- [x] **Step 1：建立失敗測試**

```python
import pytest

from training_kb.errors import ContentError
from training_kb.writing.validators import gap_naming_validator, step_rewrite_validator


def test_step_rewrite_rejects_number_outside_hit_set():
    validate = step_rewrite_validator(allowed_steps=frozenset({3}),
                                      allowed_features=frozenset({"Prepare"}))
    with pytest.raises(ContentError, match="step_number_not_in_hit_set"):
        validate({"steps": [{"number": 2, "type": "click_ui", "text": "x", "feature_id": "Prepare"}]})


def test_gap_naming_accepts_null_feature_but_rejects_unknown_id():
    validate = gap_naming_validator(known_feature_ids=frozenset({"Prepare"}))
    validate({"gap": "找不到會前摘要入口", "feature_id": None})
    with pytest.raises(ContentError, match="feature_id_not_found"):
        validate({"gap": "找不到會前摘要入口", "feature_id": "Admin"})
```

- [x] **Step 2：執行並確認紅燈**

```bash
uv run pytest tests/unit/test_writing_validation.py -q
```

預期：FAIL，訊號包含 `cannot import name 'step_rewrite_validator'`。

- [x] **Step 3：建立最小實作**

```python
from collections.abc import Callable
from typing import Any

from training_kb.errors import ContentError

BusinessValidator = Callable[[dict[str, Any]], None]


def step_rewrite_validator(*, allowed_steps: frozenset[int],
                           allowed_features: frozenset[str]) -> BusinessValidator:
    def validate(payload: dict[str, Any]) -> None:
        for step in payload["steps"]:
            if step["number"] not in allowed_steps:
                raise ContentError("step_number_not_in_hit_set: steps[].number")
            if step["feature_id"] not in allowed_features:
                raise ContentError("feature_id_not_found: steps[].feature_id")
    return validate


def gap_naming_validator(*, known_feature_ids: frozenset[str]) -> BusinessValidator:
    def validate(payload: dict[str, Any]) -> None:
        value = payload["feature_id"]
        if value is not None and value not in known_feature_ids:
            raise ContentError("feature_id_not_found: feature_id")
    return validate
```

訊息格式固定是 `<代碼>: <欄位路徑>`，不含模型輸出或使用者文字，修正 prompt 與 log 都直接用它。

- [x] **Step 4：跑完整檔案確認綠燈**

```bash
uv run pytest tests/unit/test_writing_validation.py -q
```

預期：兩個測試都 `passed`；未知 Feature 與命中集合外的 step number 都被拒絕，`feature_id=None` 仍可作為 KEEP／gap 結果。

- [x] **Step 5：提交**

```bash
git add src/training_kb/writing/validators.py tests/unit/test_writing_validation.py
git commit -m "feat(writing): 增加模型業務驗證"
```

### Task 2：鎖定最多一次修正

**Files:**

- Modify: `src/training_kb/writing/client.py`
- Modify: `tests/unit/test_writing_validation.py`

- [x] **Step 1：建立失敗測試**

```python
# 續寫 tests/unit/test_writing_validation.py。`fake_writer` 是 Phase 15 放在
# tests/unit/conftest.py 的共用替身（RecordingWriter）：回應先排進 `replies`，
# 實際送出幾次看 `request_attempts`，不要在本檔另外寫一個 FakeWriter。
BAD_STEP_2 = {"steps": [{"number": 2, "type": "click_ui",
                         "text": "在會議頁面選擇 Prepare。", "feature_id": "Prepare"}]}


def test_business_invalid_output_gets_only_one_correction(fake_writer):
    fake_writer.replies.extend([BAD_STEP_2, BAD_STEP_2])      # 兩次都回命中集合外的步驟
    validate = step_rewrite_validator(allowed_steps=frozenset({3}),
                                      allowed_features=frozenset({"Prepare"}))
    with pytest.raises(PermanentError) as error:
        generate_validated_json(fake_writer, "s", "u", StepRewrite, validate,
                                  operation_id="op-release-r_42", node="prepare_update")
    assert fake_writer.request_attempts == 2
    assert "step_number_not_in_hit_set" in str(error.value)
    assert "prepare-meeting" not in str(error.value)


def test_transient_error_is_not_counted_as_a_correction(fake_writer, monkeypatch):
    def throttled(*args, **kwargs):     # RecordingWriter 沒有「排例外」的佇列，改用 monkeypatch
        fake_writer.request_attempts += 1
        raise TransientError("throttled")

    monkeypatch.setattr(fake_writer, "generate_json", throttled)
    with pytest.raises(TransientError):
        generate_validated_json(fake_writer, "s", "u", GapNaming, lambda payload: None,
                                  operation_id="op-ticket-t_881", node="name_gap")
    assert fake_writer.request_attempts == 1
```

- [x] **Step 2：執行並確認紅燈**

```bash
uv run pytest tests/unit/test_writing_validation.py -q
```

預期：FAIL，訊號包含 `cannot import name 'generate_validated_json'`；未限制迴圈的實作也會在 `request_attempts == 2` 這個斷言失敗（`replies` 用完時 `RecordingWriter` 會直接丟 `PermanentError`，第三次請求無所遁形）。

- [x] **Step 3：建立最小實作**

```python
def generate_validated_json(writer, system, user, schema, validate, *, operation_id, node):
    first = writer.generate_json(system, user, schema, operation_id=operation_id, node=node)
    try:
        validate(first)
    except ContentError as exc:
        correction = f"{user}\n<validation_error>{exc}</validation_error>\n只修正上述違規，其餘逐字保留。"
    else:
        return first
    second = writer.generate_json(system, correction, schema, operation_id=operation_id, node=node)
    try:
        validate(second)
    except ContentError as exc:
        raise PermanentError(f"business-invalid after one correction: {exc}") from exc
    return second
```

`TransientError` 不進 `except`，會直接往外丟給 ASL Retry；`<validation_error>` 只放 Task 1 的代碼字串，不放模型輸出。

- [x] **Step 4：跑完整檔案確認綠燈**

```bash
uv run pytest tests/unit/test_writing_validation.py -q
```

預期：全部 `passed`；一次就合法 `request_attempts == 1`、修正後合法 `request_attempts == 2`、兩次都不合法 `request_attempts == 2` 並丟 `PermanentError`，第三次 request 不存在。

- [x] **Step 5：提交**

```bash
git add src/training_kb/writing/client.py tests/unit/test_writing_validation.py
git commit -m "feat(writing): 限制模型輸出修正一次"
```

### Task 3：固定生成參數、逾時與輸出重用

**Files:**

- Modify: `src/training_kb/writing/client.py`
- Modify: `tests/unit/test_writing_validation.py`
- Create: `tests/integration/test_claude_validation.py`

- [x] **Step 1：建立失敗測試**

> **實作差異（Phase 10／07 尚未就緒）：** 下面第二個測試用的 `coordinator`／`repository` fixture
> 現在不存在——Phase 10 的 `OperationCoordinator`、`keys.operation_ref` 還沒實作，
> Phase 07 的 `repository` fixture 也沒有 `fail_next_put`，而且 `repository.py` 與
> `tests/integration/` 正由別的 agent 修改。實際落地的版本改用同形的本地替身
> （`FakeObjectStore`／`FakeCoordinator`／`operation_ref`，都在 `tests/unit/test_writing_validation.py`
> 內），斷言逐字保留：儲存第一次丟 `TransientError`、第二次讀 `model_output_refs[-1]` 的 bytes、
> `fake_writer.request_attempts == 1`。真正接上 Repository 與 coordinator 由 Phase 40／41 的測試負責。

```python
def test_generation_request_sets_max_tokens_timeout_and_low_temperature():
    assert inference_config(TutorialDraft) == {"maxTokens": 2048, "temperature": 0.1}
    assert inference_config(GapNaming) == {"maxTokens": 512, "temperature": 0.1}
    assert "topP" not in inference_config(GapNaming)
    config = bedrock_config()
    assert (config.connect_timeout, config.read_timeout) == (2, 30)
    assert config.retries["total_max_attempts"] == 1


def test_storage_retry_reuses_recorded_output(coordinator, fake_writer, repository):
    def save_gap(payload):  # 代表 Phase 39／40 的保存步驟
        repository.put_object("operations/gap/last.json", json.dumps(payload).encode(),
                              "application/json", if_none_match=False)

    op = "op-ticket-t_881"
    fake_writer.replies.append({"gap": "找不到會前摘要入口", "feature_id": "Prepare"})
    output = generate_validated_json(
        fake_writer, "s", "u", GapNaming,
        gap_naming_validator(known_feature_ids=frozenset({"Prepare"})),
        operation_id=op, node="name_gap")
    ref = operation_ref(op, "gap-naming")   # 與 Phase 39／41 的 operations/<op>/gap-naming.json 同名
    repository.put_object(ref, json.dumps(output).encode(), "application/json", if_none_match=True)
    coordinator.record_model_output(op, ref)
    repository.fail_next_put(TransientError("dynamodb throttled"))
    with pytest.raises(TransientError):
        save_gap(output)
    reloaded = json.loads(repository.get_object(coordinator.load(op).model_output_refs[-1]))
    save_gap(reloaded)
    assert reloaded == output
    assert fake_writer.request_attempts == 1      # 重用既有輸出，沒有第二次模型呼叫
```

- [x] **Step 2：執行並確認紅燈**

```bash
uv run pytest tests/unit/test_writing_validation.py -q
```

預期：FAIL，訊號包含 `cannot import name 'inference_config'`。把 `save_gap` 的 retry 分支故意改成重新呼叫 `generate_validated_json`，第二個測試會在 `count(...) == 1` 失敗；確認這個訊號後再改回讀 `model_output_refs`。

- [x] **Step 3：建立最小實作**

```python
# 續寫 src/training_kb/writing/client.py；bedrock_config 已由 Phase 15 建在同一支檔案，不重寫。
_MAX_TOKENS = {"TutorialDraft": 2048}
_DEFAULT_MAX_TOKENS = 512
_TEMPERATURE = 0.1


def inference_config(schema: Mapping[str, Any]) -> dict[str, object]:
    return {"maxTokens": _MAX_TOKENS.get(schema["$id"], _DEFAULT_MAX_TOKENS),
            "temperature": _TEMPERATURE}
```

> **實作差異（與 Phase 15 既有測試相容）：** `schema["$id"]` 會對沒有 `$id` 的 schema 丟 `KeyError`，
> 而 Phase 15 的 `test_writing_trace.py` 與 `tests/integration/test_bedrock_trace.py` 都用裸的
> `{"type": "object"}` 送 request。落地版本改成 `schema.get("$id", "")`（與 Phase 17 的
> `_parse_schema_json` 同一種取法），缺 `$id` 時走判斷類預設 512。判斷類的 512／0.1 不另寫一份常數，
> 直接以 Phase 15 的 `JUDGEMENT_INFERENCE_CONFIG` 為底稿，只在 `WRITING_MAX_TOKENS`
> （`{"TutorialDraft": 2048}`）命中時覆寫 `maxTokens`，所以 Phase 15 Task 2 那條
> `inferenceConfig == {"maxTokens": 512, "temperature": 0.1}` 的斷言原樣成立。
> `BedrockWriter._converse` 加一個 `inference` 關鍵字參數（預設判斷類，給沒有 schema 的 tool use），
> `generate_json` 逐次傳 `inference_config(schema)`。

`inference_config` 的結果原樣放進 `Converse` 的 `inferenceConfig`；Phase 15 的 `bedrock_config()` 給 `boto3.client("bedrock-runtime", config=...)`，`total_max_attempts=1` 代表含首次請求共一次、SDK 不重試，本 Phase 的測試只是把這三個值鎖住。Titan 的 `embed` 只共用 `bedrock_config()` 的逾時，不套用任何生成參數。

- [x] **Step 4：跑完整檔案確認綠燈**

```bash
uv run pytest tests/unit/test_writing_validation.py -q
```

預期：全部 `passed`；storage retry 前後 `CallTrace` 筆數不變，重新載入的 bytes 與原輸出相同。

O5 通過後再跑一次真實帳號檢查。真實 AWS／Bedrock 測試全套只有一種開關：檔案標 `@pytest.mark.aws`（`pytestmark = pytest.mark.aws`），執行時設 `TKB_RUN_AWS_INTEGRATION=1`，Phase 01 的 `tests/conftest.py` 在沒設它時自動跳過：

```bash
TKB_RUN_AWS_INTEGRATION=1 uv run pytest tests/integration/test_claude_validation.py -q -m aws
```

預期：實際 request attempt 不超過 2；權限、逾時或參數錯誤保留 Phase 02 的原始分類後停止。O5 未通過時這個檔案 skip，**skip 不得當成通過**。

- [x] **Step 5：提交**

```bash
git add src/training_kb/writing/client.py tests/unit/test_writing_validation.py tests/integration/test_claude_validation.py
git commit -m "feat(writing): 固定生成參數與輸出重用"
```

## 7. 驗收矩陣

| 路徑 | 輸入 | 預期資料結果 |
|---|---|---|
| Happy | 首次 schema 與 business 皆合法 | 1 個 request、1 筆 trace、1 個 output ref。 |
| Failure | 兩次都回命中集合外的 step number | `PermanentError`，`calls == 2`，沒有第三次，也沒有新版本。 |
| Boundary | schema 合法但 `feature_id` 不存在；`feature_id = null` | 前者進 correction 而不是保存，修正後合法則 `calls == 2`；後者業務驗證通過，交 Phase 40 決定 KEEP／CREATE。 |
| Storage retry | repository 第一次暫時失敗 | 第二次重用同一份 output bytes，`CallTrace` 不增加。 |
| Transient model error | `Writer` 丟 `TransientError` | 原樣往外丟給 ASL Retry；`calls == 1`，correction 預算未被消耗。 |

人工驗收：打開 `PermanentError` 的訊息與 `CallTrace.to_json()`，確認只看得到 validator 代碼、欄位路徑與固定 metadata，看不到教學全文、回饋留言或 prompt 原文；只看測試 PASS 不算完成。
停止條件：若觀察到同一輸出超過兩個 generation attempt、或 storage retry 產生不同文字，立即停止後續建版 Phase；這會破壞呼叫計數與 idempotency。O5 未通過時本 Phase 只能完成 fake 單元測試，不得勾選整合驗收。
**實跑證據（2026-09-14）：** `TKB_RUN_AWS_INTEGRATION=1` 下實跑 `tests/integration/test_claude_validation.py`，兩個需要真實模型的測試 FAIL：Bedrock 回 `ValidationException: Operation not allowed`（帳號未開通），被 Phase 15 的分類器照 Phase 02 契約轉成 `PermanentError("ValidationException")`、不轉成 `TransientError`。O5 維持 **BLOCKED**，整合驗收未勾選。

## 8. 常見錯誤與停止條件

| 症狀 | 原因 | 修正／停止 |
|---|---|---|
| schema 通過卻改錯 step | validator 沒有 runtime context | 把命中集合閉包進 factory；取不到 context 時不寫入。 |
| 失敗一直叫模型 | 用 `while` 而沒有明確上限 | 固定 first + second 兩次；第三次 request 出現即停止。 |
| 儲存錯誤後文字改變 | retry 路徑重跑生成 | 從 `model_output_refs[-1]` 讀回；ref 遺失時停止並標 O2 失敗。 |
| 逾時後 SDK 與 Lambda 同時重試 | 多層 retry 相乘 | SDK `total_max_attempts=1`，只留 Task 的暫時錯誤 Retry；次數無法預測時停止。 |
| 業務失敗被丟成 `TransientError` | 錯用錯誤分類，讓 ASL 白重試兩次 | 業務不合法一律 `ContentError` → `PermanentError`；分類錯誤時停止。 |
| 修正 prompt 夾帶回饋原文或模型輸出 | 把整個 payload 塞進 `<validation_error>` | 只放 `<代碼>: <欄位路徑>`；看到內容外洩立即停止並清除測試產物。 |

## 9. 來源與 Rule 對照

- [執行教學流程.feature](../../spec/features/執行教學流程.feature)
  - Rule 4：「每個 Bedrock 呼叫設定 max_tokens」→ primary 在本 Phase；Task 3 的 `test_generation_request_sets_max_tokens_timeout_and_low_temperature` 斷言 `inference_config` 對每個 schema 都給 `maxTokens`（`TutorialDraft` 2048、其餘 512）。
  - Rule 5：「每個 Bedrock 呼叫設定逾時」→ primary 在本 Phase；同一個測試斷言 `bedrock_config()` 的 `connect_timeout=2`、`read_timeout=30`。
  - Rule 9：「判斷節點使用低 temperature」→ primary 在本 Phase；同一個測試斷言 `temperature == 0.1` 且沒有 `topP`。
  - Rule 8：「LLM 輸出遵循指定 JSON schema」→ 相關（primary 在 [Phase 17](17-Phase17-Claude結構化輸出與Prompt.md)）；本 Phase 只證明 schema 通過不等於業務通過。
- [建立教學版本.feature](../../spec/features/建立教學版本.feature) Rule 9：「沒有 Feature 或引用多個 Feature 的步驟不可保存」→ 相關（primary 在 [Phase 21](21-Phase21-教學內容與步驟引用驗證.md)）；本 Phase 提供 `feature_id_not_found` 這一半的驗證接點。
- [設計 §7.6、§14.1–§14.3](../../design/training-kb.md)：模型輸出須先過 JSON schema 再過業務驗證才可進入儲存；schema 合法但引用或未改文字不符時由業務驗證拒絕、有限重試後失敗；業務不合法最多修正一次；只讓一層管理重試。
- [botocore Config](https://docs.aws.amazon.com/botocore/latest/reference/config.html)：`connect_timeout`／`read_timeout` 的單位是秒，`retries={"total_max_attempts": 1}` 代表含首次請求共一次、不重試（2026-09-13 查證）。
- [Bedrock Converse API](https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_Converse.html)：`inferenceConfig` 接受 `maxTokens`、`temperature`、`topP`（2026-09-13 查證）。

## 10. 完成清單

- [x] correction loop（`generate_validated_json`）只有這一份實作，呼叫端一律 import 它、呼叫一次，沒有人自己再寫一遍或自己重試。
- [x] 八個 schema 都有 context-aware 業務檢查或第 5 節表格指定的接入點，且沒有兩份並存。
- [x] 第一次就合法 1 次、修正成功 2 次、修正失敗 2 次，第三次 request 不存在。
- [x] `TransientError` 不被 correction 攔截，交 Phase 29 的單層 Task Retry。
- [x] 生成參數（`maxTokens`／`temperature`／逾時）與 Titan 設定完全分開，SDK 自動 retry 已關閉。
- [x] storage retry 從 `OperationRecord.model_output_refs[-1]` 重用輸出，`CallTrace` 不增加。
- [x] 錯誤訊息、修正 prompt 與 trace 都只有代碼與欄位名，沒有模型輸出或使用者文字。
- [x] 沒有建立版本、沒有發布、沒有部署，也沒有以 mock 綠燈宣稱 O5 或 AWS 已通過。
