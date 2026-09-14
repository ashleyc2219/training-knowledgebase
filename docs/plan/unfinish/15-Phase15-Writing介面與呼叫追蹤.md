# Phase 15：Writing 介面與呼叫追蹤實作計畫

> **給實作者：** 依 checkbox 逐步執行；每個 Task 先建立失敗測試，再寫最小實作。執行時使用 `superpowers:subagent-driven-development`（建議）或 `superpowers:executing-plans`。

**目標：** 建立所有 Bedrock 呼叫共用的 `Writer` 邊界與逐次 request attempt 追蹤，讓 embedding、生成、重試、Map 與 Rote 都能用同一套計數規則核對。

**架構：** `Writer` 只封裝 Bedrock 請求與解析，不碰 DynamoDB、S3 或發布。每次真正送出 request 之前先配 attempt 序號，收到回應或例外後各寫一筆 `CallTrace`；呼叫端重用已保存的模型輸出時不增加 attempt。

**技術：** Python 3.12、`typing.Protocol`、boto3（`bedrock-runtime` client）、botocore `Config`、pytest。

## 全域限制

- 唯一主來源是 [Training KB 設計 §5、§7.6、§12.1、§14.3、§17.1](../../design/training-kb.md)。讀者是第一次接手 Training KB、即將實作 Bedrock 邊界的工程師。
- 前置為 [Phase 14：O5 模型可用性與參數驗證](14-Phase14-O5模型可用性與參數驗證.md)，再往前是 [Phase 01](01-Phase01-專案骨架與離線品質門檻.md) 的環境與 [Phase 02](02-Phase02-設定時間與錯誤契約.md) 的錯誤與時間契約。**O5 未通過時本階段的「真實 Bedrock 整合測試」標 BLOCKED，程式與單元測試照常完成**（controller 2026-09-14 裁決，見 §12）：`TKB_GENERATION_MODEL_ID` 保持 `<實測通過的 ID>` 佔位，不填猜測值，也不得勾選真實整合驗收。
- 下一階段是 [Phase 16：Titan Embedding 與向量計算](16-Phase16-Titan-Embedding與向量計算.md)（實作 `embed`），之後是 [Phase 17](17-Phase17-Claude結構化輸出與Prompt.md)（schema 與 prompt）與 [Phase 18](18-Phase18-模型輸出業務驗證與有限重試.md)（業務 validator 與最多一次修正）。Phase 37 消費 `converse_with_tools`，Phase 54、58 消費 `CallTrace`。
- 本階段不做：不寫 prompt、不定義 JSON schema、不實作 Titan 的 1024 維驗證、不實作業務 validator、不做業務層重試迴圈、**不做工具呼叫迴圈**（`converse_with_tools` 只送一次 request，多輪迴圈屬於 Phase 37）、不接 pipeline、不部署。
- 生成與 embedding 是兩種 request：**Claude 一律走 `converse`**（參數放 `inferenceConfig`，回應帶 `stopReason`，截斷判讀由 Phase 17 做），**只有 Titan 走 `invoke_model`**；Titan body 不得出現 `maxTokens`、`temperature`、`topP` 或 Messages 欄位（設計 §14.3）。
- `CallTrace` 以每次真實送出的 request attempt 為單位；失敗、Phase 18 的修正、ASL Retry、Map 每一項、Rote 與 embedding 都要計入，記憶體重用不算。trace、log 與例外訊息都不得出現 secret、原始 webhook body、使用者全文或完整 prompt（設計 §14.3、§17.2）。
- 與本 Phase 有關的 gate 是 **O5**；本階段不得宣稱 O5 已通過，也不得用 mock 綠燈代替帳號證據。真實 AWS／Bedrock 測試只有一種開關：測試標 `@pytest.mark.aws`，執行時設 `TKB_RUN_AWS_INTEGRATION=1`（Phase 01 的 conftest 在未設時自動 skip）。以下程式檔均是實作時預計建立或修改；本計畫本身不代表它們已存在。

---

## 1. 你在整體流程的位置

```text
Ticket / Release / Feedback pipeline  +  Rote Agent 回退（Phase 37）
                |
                v
      [你在這裡：Writer] --> CallTrace.add(一次 attempt) --> Phase 54 呼叫數／Phase 58 分組
                |
                v
  Bedrock Runtime：Claude -> converse ／ Titan -> invoke_model --> embedding / JSON / tool result
```

`Writer` 是可替換的窄介面：純領域測試用 fake client，只有整合測試才建立真的 Bedrock client。

## 2. 完成後看得到什麼

具體輸入：`operation_id="op-17"`、`node="name_gap"`，第一次 request 遇到 `ThrottlingException`，第二次成功。可觀察結果是 `trace.count(operation_id="op-17") == 2`，而 `trace.to_json()` 是兩筆只含固定欄位的紀錄（鍵已排序）。同一個 operation 換一個 `node`（例如接著做 `draft`）時 `attempt` 重新從 1 開始，`count(operation_id="op-17")` 則變成 3：

```text
[{"attempt": 1, "kind": "generation", "model": "<實測通過的 ID>", "node": "name_gap",
  "operation_id": "op-17", "outcome": "transient_error", "started_at": "2026-09-13T00:00:00Z"},
 {"attempt": 2, ... "outcome": "success", "started_at": "2026-09-13T00:00:01Z"}]
```

## 3. 名詞小抄

| 名詞 | 白話意思 |
|---|---|
| attempt（嘗試） | 一次真的送到 Bedrock 的 request。同一個節點被重問第二次，就是第二個 attempt。 |
| node（節點） / `CallTrace` | `node` 是「這次呼叫為了哪件事」，例如 `name_gap`、`draft`、`rewrite`、`embed`；`CallTrace` 是只記 metadata 的呼叫清單（哪個操作、哪個節點、哪個模型、第幾次、結果），不記 prompt 內容，Phase 58 依 `node` 分組看呼叫數。 |
| `Writer`（Protocol） / `invoke_model` / `converse` | `Writer` 是三個方法組成的窄介面（測試用 fake client，正式用 `BedrockWriter`）；`invoke_model` 與 `converse` 是 Bedrock Runtime 的兩種 API，Titan embedding 用前者、Claude 對話用後者，參數完全不同。 |
| 單層重試 | 只有一個地方負責重試：SDK 關掉自動重試，`Writer` 不迴圈，業務層最多修正一次，ASL 才做 Retry。 |
| O5 | 設計 §18 的第五個待確認：帳號實際可用的 model ID 與參數支援，由 Phase 14 實測。測試裡的 `op-17` 只是字串，正式 `operation_id` 由 Phase 32 的 `operation_id_for` 產生。 |
| `conftest.py` / fixture | `conftest.py` 是 pytest 自動載入的共用設定檔，放在哪個測試目錄就對那個目錄（含子目錄）生效；fixture 是「測試要用的現成東西」，測試函式把 fixture 名字寫進參數就拿得到。本 Phase 在 `tests/unit/conftest.py` 放一個假的 `Writer`，後面每個 Phase 的單元測試都能直接用，不必各寫一份。 |

## 4. 預計檔案

| 動作 | 路徑 | 責任 |
|---|---|---|
| 建立 | `src/training_kb/writing/__init__.py` | `writing` 套件入口；只 re-export `Writer`、`CallTrace`、`BedrockWriter`。 |
| 建立 | `src/training_kb/writing/client.py` | `Writer` Protocol、`CallTrace`、`BedrockWriter`、`bedrock_config`、`build_bedrock_client` 與錯誤分類。 |
| 建立 | `tests/unit/test_writing_trace.py` | 逐次 attempt、欄位 allowlist、錯誤分類與輸出重用測試。 |
| 建立 | `tests/integration/test_bedrock_trace.py` | O5 通過後以小量實際呼叫核對 request 與 trace 一對一。 |
| 建立 | `tests/unit/conftest.py` | 全套單元測試共用的 `RecordingWriter`（假的 `Writer`）與 `fake_writer` fixture。 |
| 建立 | `tests/unit/test_fake_writer.py` | 證明 `RecordingWriter` 真的能當 `Writer` 用，而且每次呼叫都記得下來。 |

模組路徑是 `writing/client.py`（不是單檔 `writing.py`）：Phase 17 在同一個套件加 `writing/prompts.py`、`writing/schemas.py`，Phase 18 加 `writing/validators.py`，Phase 37 直接 `from training_kb.writing.client import Writer`。

## 5. 固定介面

### Consumes

```text
TransientError / PermanentError              Phase 02，training_kb.errors
now_utc() / to_iso(dt)                       Phase 02，training_kb.clock（aware UTC、整秒）
Settings.generation_model_id: str | None     Phase 02；O5 未通過時是 None
Settings.embedding_model_id: str             Phase 02；預設 amazon.titan-embed-text-v2:0
Settings.bedrock_region: str | None          Phase 02；缺值沿用 aws_region
```

### Produces

```python
TRACE_FIELDS = ("operation_id", "node", "model", "attempt", "kind", "started_at", "outcome")
TRACE_KINDS = frozenset({"embedding", "generation", "tool_use"})
TRACE_OUTCOMES = frozenset({"success", "transient_error", "permanent_error"})
TRANSIENT_ERROR_CODES: frozenset[str]                       # Throttling 等可重送的錯誤碼
JUDGEMENT_INFERENCE_CONFIG = {"maxTokens": 512, "temperature": 0.1}

class Writer(Protocol):
    def embed(self, text: str, *, operation_id: str, node: str) -> list[float]: ...
    def generate_json(self, system: str, user: str, schema: Mapping[str, Any], *,
                      operation_id: str, node: str) -> dict[str, Any]: ...
    def converse_with_tools(self, system: str, messages: Sequence[Mapping[str, Any]],
                            tools: Sequence[Mapping[str, Any]], *,
                            operation_id: str, node: str) -> dict[str, Any]: ...

class CallTrace:
    def add(self, record: Mapping[str, Any]) -> None: ...
    def count(self, *, operation_id: str | None = None) -> int: ...
    def next_attempt(self, *, operation_id: str, node: str) -> int: ...
    def to_json(self) -> str: ...

class BedrockWriter:
    trace: CallTrace
    def __init__(self, client: Any, trace: CallTrace, *,
                 generation_model_id: str | None, embedding_model_id: str) -> None: ...

def bedrock_config() -> "Config": ...       # botocore Config；Phase 18 直接沿用同一個函式
def build_bedrock_client(region: str) -> Any: ...

# tests/unit/conftest.py（只給測試用，不進 src）
FIXED_EMBEDDING: list[float]                # 1024 個固定值，讓向量測試可重現

class RecordingWriter:                      # 實作 Writer 的三個方法
    replies: list[Mapping[str, Any]]        # generate_json 依序回這個佇列
    tool_plans: list[Mapping[str, Any]]     # converse_with_tools 依序回這個佇列
    calls: list[dict[str, Any]]             # 每次呼叫的 kind／operation_id／node／輸入
    request_attempts: int                   # 呼叫次數；對應真實 Writer 的 trace 筆數

@pytest.fixture
def fake_writer() -> RecordingWriter: ...
```

`RecordingWriter` 與 `fake_writer` 是**測試替身**（test double），住在 `tests/unit/conftest.py`，由本 Phase 產出、後續每個需要模型回應的單元測試（Phase 18、27、38、39、43、45、47、50 等）共用。各 Phase 若已有自己的本地 `FakeWriter`，形狀要與它相容：同樣三個方法、同樣用佇列給回應。

每筆 `record` 的鍵集合固定就是 `TRACE_FIELDS` 這七個，多一個或少一個都丟 `PermanentError`；`kind` 只允許 `TRACE_KINDS`，`outcome` 只允許 `TRACE_OUTCOMES`。`Writer` 是後續 Phase 依賴的型別；`BedrockWriter` 是本 Phase 的 Bedrock adapter，本階段先完成 `generate_json` 與 `converse_with_tools`，`embed` 由 Phase 16 在同一個 `_request_once` 路徑上補齊。`bedrock_config()` 與 [Phase 18](18-Phase18-模型輸出業務驗證與有限重試.md) 的 `bedrock_config()` 是**同一個函式**（Phase 18 從本模組 import，不得出現第二份 `Config`）。

## 6. 設計細節

```text
一次「邏輯呼叫」與「真實 attempt」的關係（設計 §14.3：只讓一層管理重試）

ASL Retry（Phase 29，等 1 秒／2 秒） -> 修正迴圈（Phase 18，最多再問一次）
  -> Writer.generate_json / embed / converse_with_tools -> _request_once（送一次就回來，沒有迴圈）
          |
   +------+---------------------+----------------------+
   v                            v                      v
成功 -> trace.add(success)  暫時 -> trace.add(transient)  永久 -> trace.add(permanent)
回傳 response               raise TransientError         raise PermanentError

boto3 Config: retries={"total_max_attempts": 1} -> SDK 這一層不再重試
```

`bedrock_config()` 把逾時與「關閉 SDK 重試」集中在一個地方，單元測試直接對這個 `Config` 物件斷言；**不要**改成對 `client.meta.config.retries` 斷言，botocore 建立 client 時會把 `total_max_attempts` 正規化成未公開的內部欄位。三條規則要一起成立，呼叫數才不會相乘：**（1）attempt 依 `(operation_id, node)` 重新起算**，Phase 58 的 `call_breakdown` 用「同 node 且 `attempt >= 2`」判定重試次數，改成整個 operation 連號會把第二個節點的第一次呼叫誤算成重試；**（2）例外分支一定要寫 trace**，先配 attempt、記下 `started_at`，再送出 request，只在成功時記錄會讓 SDK 次數與 trace 對不起來；**（3）例外訊息只留錯誤碼或例外類別名**，`ClientError` 的 message 可能回聲使用者輸入，直接放進 `TransientError(str(exc))` 等於把內容寫進 log。Phase 54 用 `CallTrace.count` 算總數，Phase 58 需要逐筆的 `node` 與 `attempt`，讀法固定是 `json.loads(trace.to_json())`，不另外維護第二份計數器；本階段固定送設計 §14.3 的判斷節點起點 `{"maxTokens": 512, "temperature": 0.1}`（只設 `temperature`，不同時調 `topP`），教學寫作用的 2048 與依節點選 profile 由 Phase 18 的 `inference_config(schema)` 取代這個常數。

## 7. TDD Tasks

### Task 1：鎖定 CallTrace 的計數、欄位與 attempt 起算

**Files:** Create `src/training_kb/writing/__init__.py`、`src/training_kb/writing/client.py`、`tests/unit/test_writing_trace.py`

- [x] **Step 1：建立失敗測試**

```python
import json

import pytest

from training_kb.errors import PermanentError
from training_kb.writing.client import TRACE_FIELDS, CallTrace

ROW = {"operation_id": "op-17", "node": "name_gap", "model": "verified-model", "attempt": 1,
       "kind": "generation", "started_at": "2026-09-13T00:00:00Z", "outcome": "transient_error"}


def test_trace_counts_attempts_and_keeps_only_fixed_fields() -> None:
    trace = CallTrace()
    trace.add(ROW)
    trace.add({**ROW, "attempt": 2, "outcome": "success"})
    assert trace.count(operation_id="op-17") == 2 and trace.count() == 2
    assert trace.count(operation_id="op-other") == 0
    assert [set(row) for row in json.loads(trace.to_json())] == [set(TRACE_FIELDS)] * 2
    assert trace.next_attempt(operation_id="op-17", node="name_gap") == 3
    assert trace.next_attempt(operation_id="op-17", node="draft") == 1


@pytest.mark.parametrize("bad", [
    {**ROW, "prompt": "secret prompt"},
    {key: value for key, value in ROW.items() if key != "outcome"},
    {**ROW, "outcome": "maybe"},
    {**ROW, "kind": "chat"},
])
def test_trace_rejects_extra_missing_or_unknown_values(bad: dict) -> None:
    trace = CallTrace()
    with pytest.raises(PermanentError):
        trace.add(bad)
    assert trace.count() == 0
```

- [x] **Step 2：執行並確認紅燈**

```bash
uv run pytest tests/unit/test_writing_trace.py -q
```

預期：FAIL，訊號包含 `ModuleNotFoundError: No module named 'training_kb.writing'`。若連 `uv run pytest` 都不能執行，先回 Phase 01 把環境建好。

- [x] **Step 3：建立最小實作**

```python
# src/training_kb/writing/client.py（同時建立 writing/__init__.py。本 Task 只有 CallTrace
# 存在，所以先寫 `from training_kb.writing.client import CallTrace` 加 `__all__`（ruff 的
# F401 會擋沒有 __all__ 的 re-export），Task 2 再補 BedrockWriter 與 Writer。）
import json
from collections.abc import Mapping
from typing import Any

from training_kb.errors import PermanentError

TRACE_FIELDS = ("operation_id", "node", "model", "attempt", "kind", "started_at", "outcome")
TRACE_KINDS = frozenset({"embedding", "generation", "tool_use"})
TRACE_OUTCOMES = frozenset({"success", "transient_error", "permanent_error"})


class CallTrace:
    def __init__(self) -> None:
        self._records: list[dict[str, Any]] = []

    def add(self, record: Mapping[str, Any]) -> None:
        if set(record) != set(TRACE_FIELDS):
            raise PermanentError(f"call trace fields must be exactly {TRACE_FIELDS}")
        if record["kind"] not in TRACE_KINDS or record["outcome"] not in TRACE_OUTCOMES:
            raise PermanentError(f"unknown kind/outcome: {record['kind']!r} {record['outcome']!r}")
        self._records.append({name: record[name] for name in TRACE_FIELDS})

    def count(self, *, operation_id: str | None = None) -> int:
        return sum(1 for row in self._records
                   if operation_id is None or row["operation_id"] == operation_id)

    def next_attempt(self, *, operation_id: str, node: str) -> int:
        return 1 + sum(1 for row in self._records
                       if row["operation_id"] == operation_id and row["node"] == node)

    def to_json(self) -> str:
        return json.dumps(self._records, ensure_ascii=False, sort_keys=True)
```

- [x] **Step 4：跑完整檔案確認綠燈**

```bash
uv run pytest tests/unit/test_writing_trace.py -q
```

預期：`5 passed`（第二個測試有四個參數化案例），且 `to_json()` 只有七個固定鍵。

- [x] **Step 5：提交**

```bash
git add src/training_kb/writing tests/unit/test_writing_trace.py
git commit -m "feat(writing): 建立模型呼叫追蹤"
```

### Task 2：窄介面包住 Bedrock 呼叫、分類錯誤並關掉 SDK 重試

**Files:** Modify `src/training_kb/writing/client.py`、`tests/unit/test_writing_trace.py`

- [x] **Step 1：建立失敗測試**

接在 Task 1 同一個測試檔後面；檔頭已匯入的 `json`、`pytest`、`CallTrace`、`PermanentError` 直接沿用，只補下面四行匯入。

```python
from typing import Any

from botocore.exceptions import ClientError

from training_kb.errors import TransientError
from training_kb.writing.client import BedrockWriter, bedrock_config


class FakeConverseClient:
    def __init__(self, *answers: object) -> None:
        self.answers, self.requests = list(answers), []

    def converse(self, **kwargs: Any) -> dict[str, Any]:
        self.requests.append(kwargs)
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return {"output": {"message": {"content": [{"text": json.dumps(answer)}]}}}


def make_writer(client: object) -> BedrockWriter:
    return BedrockWriter(client, CallTrace(), generation_model_id="verified-model",
                         embedding_model_id="amazon.titan-embed-text-v2:0")


def test_one_sdk_request_creates_one_attempt_per_node() -> None:
    client = FakeConverseClient({"answer": "ok"}, {"answer": "next"})
    writer = make_writer(client)
    first = writer.generate_json("system", "user", {"type": "object"},
                                 operation_id="op-1", node="name_gap")
    writer.generate_json("system", "user", {"type": "object"}, operation_id="op-1", node="draft")
    assert first == {"answer": "ok"}
    assert len(client.requests) == writer.trace.count(operation_id="op-1") == 2
    assert client.requests[0]["inferenceConfig"] == {"maxTokens": 512, "temperature": 0.1}
    assert [row["attempt"] for row in json.loads(writer.trace.to_json())] == [1, 1]


@pytest.mark.parametrize(("code", "raised", "outcome"), [
    ("ThrottlingException", TransientError, "transient_error"),
    ("ValidationException", PermanentError, "permanent_error"),
])
def test_sdk_failure_is_traced_and_classified(code, raised, outcome) -> None:
    error = ClientError({"Error": {"Code": code, "Message": "回聲了使用者輸入"}}, "Converse")
    writer = make_writer(FakeConverseClient(error))
    with pytest.raises(raised):
        writer.generate_json("s", "u", {}, operation_id="op-1", node="draft")
    rows = json.loads(writer.trace.to_json())
    assert len(rows) == 1 and rows[0]["outcome"] == outcome and rows[0]["attempt"] == 1
    assert "回聲" not in writer.trace.to_json()


def test_config_has_one_retry_layer_and_saved_output_adds_no_attempt() -> None:
    config = bedrock_config()
    assert config.retries == {"total_max_attempts": 1}
    assert config.connect_timeout == 2 and config.read_timeout == 30
    client = FakeConverseClient({"gap": "找不到 Prepare 按鈕"})
    writer = make_writer(client)
    first = writer.generate_json("s", "u", {}, operation_id="op-retry", node="name_gap")
    saved = json.dumps(first)            # Phase 10 會寫到 operations/op-retry/gap-naming.json
    assert json.loads(saved) == first    # 儲存重送只讀檔，不再進 Writer
    assert writer.trace.count(operation_id="op-retry") == 1 and len(client.requests) == 1
```

- [x] **Step 2：執行並確認紅燈**

```bash
uv run pytest tests/unit/test_writing_trace.py -q
```

預期：FAIL，訊號包含 `cannot import name 'BedrockWriter'`。

- [x] **Step 3：建立最小實作**

`Writer` Protocol 在本 Task 一併定義（00A §6.5 的簽名逐字照抄）：它是模組的對外型別，`BedrockWriter` 是它唯一的正式實作，Task 4 的 `tests/unit/test_fake_writer.py` 會 `from training_kb.writing.client import Writer`。public method 都只經過一個私有的 `_request_once`：它在 SDK 呼叫前配 attempt，成功或例外後各寫一筆 trace，內部沒有迴圈。`converse_with_tools` 同樣只送一次 request，拿到 `toolUse` 後要不要再問一輪由 Phase 37 決定。

```python
import boto3
from botocore.config import Config
from botocore.exceptions import ConnectTimeoutError, EndpointConnectionError, ReadTimeoutError

from training_kb.clock import now_utc, to_iso
from training_kb.errors import TransientError

JUDGEMENT_INFERENCE_CONFIG = {"maxTokens": 512, "temperature": 0.1}
TIMEOUT_ERRORS = (ConnectTimeoutError, ReadTimeoutError, EndpointConnectionError)
TRANSIENT_ERROR_CODES = frozenset({
    "ThrottlingException", "ServiceQuotaExceededException", "ModelNotReadyException",
    "ModelTimeoutException", "ServiceUnavailableException", "InternalServerException"})


def bedrock_config() -> Config:
    return Config(connect_timeout=2, read_timeout=30, retries={"total_max_attempts": 1})


def build_bedrock_client(region: str):
    return boto3.client("bedrock-runtime", region_name=region, config=bedrock_config())


def _error_code(error: BaseException) -> str:
    response = getattr(error, "response", None)
    body = response.get("Error", {}) if isinstance(response, Mapping) else {}
    return str(body.get("Code", "")) if isinstance(body, Mapping) else ""


class BedrockWriter:
    def __init__(self, client, trace, *, generation_model_id, embedding_model_id) -> None:
        self.client, self.trace = client, trace
        self._gen_id, self._embed_id = generation_model_id, embedding_model_id

    def _gen_model(self) -> str:
        if not self._gen_id:
            raise PermanentError("O5 尚未通過：generation_model_id 還沒有實測值")
        return self._gen_id

    def _request_once(self, call, *, model: str, operation_id: str, node: str, kind: str) -> Any:
        row = {"operation_id": operation_id, "node": node, "model": model, "kind": kind,
               "attempt": self.trace.next_attempt(operation_id=operation_id, node=node),
               "started_at": to_iso(now_utc())}
        try:
            response = call()
        except Exception as exc:
            code = _error_code(exc)
            transient = isinstance(exc, TIMEOUT_ERRORS) or code in TRANSIENT_ERROR_CODES
            outcome = "transient_error" if transient else "permanent_error"
            self.trace.add({**row, "outcome": outcome})
            raise_as = TransientError if transient else PermanentError
            raise raise_as(code or type(exc).__name__) from exc
        self.trace.add({**row, "outcome": "success"})
        return response

    def _converse(self, *, model, system, messages, extra, operation_id, node, kind) -> Any:
        return self._request_once(
            lambda: self.client.converse(
                modelId=model, system=[{"text": system}], messages=list(messages),
                inferenceConfig=dict(JUDGEMENT_INFERENCE_CONFIG), **extra),
            model=model, operation_id=operation_id, node=node, kind=kind)

    def generate_json(self, system, user, schema, *, operation_id, node):
        model = self._gen_model()
        response = self._converse(
            model=model, system=system, extra={}, operation_id=operation_id, node=node,
            messages=[{"role": "user", "content": [{"text": user}]}], kind="generation")
        try:
            value = json.loads(response["output"]["message"]["content"][0]["text"])
        except json.JSONDecodeError as exc:
            raise PermanentError("model response is not valid JSON") from exc
        if not isinstance(value, dict):
            raise PermanentError("model response is not a JSON object")
        return value

    def converse_with_tools(self, system, messages, tools, *, operation_id, node):
        model = self._gen_model()
        return self._converse(model=model, system=system, messages=messages, kind="tool_use",
                              extra={"toolConfig": {"tools": list(tools)}},
                              operation_id=operation_id, node=node)
```

`generate_json` 現在只確認回應是 JSON object；schema 驗證與 `stopReason == "max_tokens"` 的截斷判讀由 Phase 17 在同一支檔案的 `_parse_schema_json` 補上（本 Phase 不先寫一份，避免兩處各判一次），`embed` 由 Phase 16 以同一個 `_request_once` 加上 Titan body 與 1024 維驗證。

- [x] **Step 4：跑完整檔案確認綠燈**

```bash
uv run pytest tests/unit/test_writing_trace.py -q
```

預期：全部 `passed`；fake client 的 request 次數等於 trace 筆數，例外訊息裡看不到 message 原文。

- [x] **Step 5：提交**

```bash
git add src/training_kb/writing/client.py tests/unit/test_writing_trace.py
git commit -m "feat(writing): 固定 Bedrock 呼叫介面"
```

### Task 3：O5 通過後用真實帳號核對 request 與 trace 一對一

**Files:** Create `tests/integration/test_bedrock_trace.py`

- [x] **Step 1：建立失敗測試**

```python
import json
import os

import pytest

from training_kb.writing.client import TRACE_FIELDS, BedrockWriter, CallTrace, build_bedrock_client

pytestmark = pytest.mark.aws      # Phase 01 conftest：TKB_RUN_AWS_INTEGRATION != "1" 時自動 skip


def test_real_request_creates_exactly_one_attempt() -> None:
    trace = CallTrace()
    writer = BedrockWriter(build_bedrock_client(os.environ["TKB_BEDROCK_REGION"]), trace,
                           generation_model_id=os.environ["TKB_GENERATION_MODEL_ID"],
                           embedding_model_id=os.environ["TKB_EMBEDDING_MODEL_ID"])
    result = writer.generate_json("只輸出一個 JSON 物件，不要其他文字。", '請輸出 {"ok": true}',
                                  {"type": "object"}, operation_id="smoke-writer", node="smoke")
    rows = json.loads(trace.to_json())
    assert isinstance(result, dict) and len(rows) == 1
    assert rows[0]["attempt"] == 1 and rows[0]["outcome"] == "success"
    assert set(rows[0]) == set(TRACE_FIELDS)
```

- [x] **Step 2：執行並確認紅燈**

```bash
TKB_RUN_AWS_INTEGRATION=1 uv run pytest tests/integration/test_bedrock_trace.py -q -m aws
```

預期：FAIL，訊號是 `KeyError: 'TKB_GENERATION_MODEL_ID'`（O5 還沒填 model ID）或 `AccessDeniedException`。這兩種訊號都代表本 Phase 的真實整合驗收維持 BLOCKED。

**實測補充**：三個環境變數在測試裡是由左而右讀的，所以什麼都不設時先撞到的是 `KeyError: 'TKB_BEDROCK_REGION'`；只把 Phase 14 唯一實測出來的 Region 設進去（`TKB_BEDROCK_REGION=us-east-1`）之後，訊號才是計畫寫的 `KeyError: 'TKB_GENERATION_MODEL_ID'`。兩者是同一件事：O5 沒有產出 model ID。

- [ ] **Step 3：建立最小實作**（**BLOCKED**：O5 未開通，見 §12）

本 Task 不新增產品程式；「實作」就是把 Phase 14 `check_models.py` 印出的三個值接上環境變數再跑，不得改寫測試去繞過缺少的 model ID。

```bash
export TKB_BEDROCK_REGION=<Phase 14 實測 Region>
export TKB_GENERATION_MODEL_ID=<實測通過的 ID>
export TKB_EMBEDDING_MODEL_ID=amazon.titan-embed-text-v2:0
```

- [ ] **Step 4：跑完整檔案確認綠燈**（**BLOCKED**：O5 未開通，見 §12）

```bash
TKB_RUN_AWS_INTEGRATION=1 uv run pytest tests/integration/test_bedrock_trace.py -q -m aws
```

預期：`1 passed`，並保留 Region、model ID、request 次數與 response 類型當證據。沒有帳號時輸出是 `1 skipped`，**skipped 不等於通過**，本 Phase 維持 BLOCKED。

- [x] **Step 5：提交**

```bash
git add tests/integration/test_bedrock_trace.py
git commit -m "test(writing): 驗證真實呼叫與 trace 一對一"
```

### Task 4：給後續 Phase 一個共用的假 Writer

**Files:** Create `tests/unit/conftest.py`、`tests/unit/test_fake_writer.py`

- [x] **Step 1：建立失敗測試**

```python
import pytest

from training_kb.errors import PermanentError
from training_kb.writing.client import Writer


def count_dimensions(writer: Writer) -> int:     # 只收 Writer，用來證明形狀相容
    return len(writer.embed("開啟摘要。", operation_id="op-1", node="embed"))


def test_fake_writer_records_every_call(fake_writer) -> None:
    fake_writer.replies.append({"gap": "找不到 Prepare 按鈕"})
    answer = fake_writer.generate_json("s", "u", {}, operation_id="op-1", node="name_gap")
    assert answer == {"gap": "找不到 Prepare 按鈕"}
    assert count_dimensions(fake_writer) == 1024
    assert fake_writer.request_attempts == 2
    assert [call["kind"] for call in fake_writer.calls] == ["generation", "embedding"]
    assert [call["node"] for call in fake_writer.calls] == ["name_gap", "embed"]


def test_fake_writer_fails_loudly_when_no_reply_is_queued(fake_writer) -> None:
    with pytest.raises(PermanentError):
        fake_writer.generate_json("s", "u", {}, operation_id="op-1", node="draft")
```

第二條是刻意的：測試忘了排回應時要**明確失敗**，不能回一個空 dict 讓後面的斷言看起來像通過。`count_dimensions` 的參數型別寫成 `Writer`，所以形狀一旦對不上，讀程式的人與型別檢查都看得出來。

- [x] **Step 2：執行並確認紅燈**

```bash
uv run pytest tests/unit/test_fake_writer.py -q
```

預期：FAIL，訊號包含 `fixture 'fake_writer' not found`（`tests/unit/conftest.py` 還沒建立）。

- [x] **Step 3：建立最小實作**

`tests/unit/conftest.py` 的完整內容：

```python
"""單元測試共用設定：一個不連 Bedrock 的假 Writer。"""

from collections.abc import Mapping, Sequence
from typing import Any

import pytest

from training_kb.errors import PermanentError

FIXED_EMBEDDING = [0.001] * 1024


class RecordingWriter:
    """實作 Phase 15 的 Writer：回應由測試先排好，呼叫全部記下來。"""

    def __init__(self, *, replies: Sequence[Mapping[str, Any]] = (),
                 tool_plans: Sequence[Mapping[str, Any]] = (),
                 embedding: Sequence[float] = FIXED_EMBEDDING) -> None:
        self.replies = [dict(reply) for reply in replies]
        self.tool_plans = [dict(plan) for plan in tool_plans]
        self.embedding = list(embedding)
        self.calls: list[dict[str, Any]] = []
        self.request_attempts = 0

    def _record(self, kind: str, *, operation_id: str, node: str, **extra: Any) -> None:
        self.request_attempts += 1
        self.calls.append({"kind": kind, "operation_id": operation_id, "node": node, **extra})

    def _next(self, queue: list[dict[str, Any]], name: str) -> dict[str, Any]:
        if not queue:
            raise PermanentError(f"RecordingWriter 沒有排好下一個 {name} 回應")
        return queue.pop(0)

    def embed(self, text: str, *, operation_id: str, node: str) -> list[float]:
        self._record("embedding", operation_id=operation_id, node=node, text=text)
        return list(self.embedding)

    def generate_json(self, system: str, user: str, schema: Mapping[str, Any], *,
                      operation_id: str, node: str) -> dict[str, Any]:
        self._record("generation", operation_id=operation_id, node=node,
                     system=system, user=user, schema=dict(schema))
        return self._next(self.replies, "generate_json")

    def converse_with_tools(self, system: str, messages: Sequence[Mapping[str, Any]],
                            tools: Sequence[Mapping[str, Any]], *,
                            operation_id: str, node: str) -> dict[str, Any]:
        self._record("tool_use", operation_id=operation_id, node=node,
                     messages=[dict(message) for message in messages],
                     tools=[dict(tool) for tool in tools])
        return self._next(self.tool_plans, "converse_with_tools")


@pytest.fixture
def fake_writer() -> RecordingWriter:
    return RecordingWriter()
```

`request_attempts` 刻意與真實 `CallTrace` 的筆數同義：一次方法呼叫算一次，重用已保存的輸出不經過它，所以測試可以直接拿它跟「預期呼叫幾次模型」對照。三個方法的簽名逐字照 `Writer`，少一個 keyword 就不是同一個介面。

- [x] **Step 4：跑完整檔案確認綠燈**

```bash
uv run pytest tests/unit -q
uv run ruff check tests/unit
```

預期：`test_fake_writer.py` 兩條全 PASS，且 Task 1／2 的既有測試不受影響（`tests/unit/conftest.py` 只新增 fixture，不改任何既有行為）。

- [x] **Step 5：提交**

```bash
git add tests/unit/conftest.py tests/unit/test_fake_writer.py
git commit -m "test(writing): 增加共用的假 Writer"
```

## 8. 驗收矩陣

| 路徑 | 輸入 | 預期資料結果 |
|---|---|---|
| Happy | fake client 成功回一次 `converse` | trace 恰一筆 `outcome=success`、`attempt=1`；SDK request 次數等於 trace 筆數。 |
| Failure | fake client 丟 `ThrottlingException` ／ `ValidationException` | 各一筆 `transient_error`／`permanent_error`，外部分別收到 `TransientError`／`PermanentError`，訊息只有錯誤碼。 |
| Boundary | 同 operation 先 `name_gap` 再 `draft`；以及重用已保存輸出 | 前者兩筆 `attempt` 都是 1、`count(operation_id=...)` 是 2；後者 trace 筆數與 SDK request 次數都不變。 |
| Boundary | `bedrock_config()` | `retries == {"total_max_attempts": 1}`、逾時 2／30 秒。 |
| Privacy | `trace.add` 收到多一個 `prompt` 鍵 | 丟 `PermanentError`，不寫入任何紀錄。 |
| Happy | `fake_writer` 依序被要一次 JSON 與一次 embedding | `request_attempts == 2`，`calls` 依序是 `generation`、`embedding`，向量長度 1024。 |
| Failure | `fake_writer.generate_json` 但 `replies` 是空的 | 丟 `PermanentError`；不得回空 dict 讓測試假通過。 |

人工驗收：打開 `trace.to_json()` 的輸出逐行確認只有七個固定鍵，沒有 prompt、payload 或帳號資訊；O5 通過後另外保存一次真實呼叫的 Region、model ID 與 request 次數。停止條件（controller 2026-09-14 裁決後）：Phase 14 沒有實際模型可用證據時，**程式與單元測試照常完成**，但真實 Bedrock 整合測試維持 FAIL／skip、不得勾選真實整合驗收，也不得宣稱 O5 完成。

## 9. 常見錯誤與停止條件

| 症狀 | 原因 | 修正／停止 |
|---|---|---|
| trace 只記成功 | 在收到 response 之後才開始記錄 | request 前先配 attempt，例外分支也要 `add`；對不出 SDK 次數就停止。 |
| 一次業務呼叫出現 3、6、9 次 | SDK 自動重試與呼叫端重試相乘 | 一律用 `bedrock_config()` 建 client，業務重試只留 Phase 18 那一層；次數仍相乘就停止。 |
| Phase 58 的重試數虛高 | `attempt` 依整個 operation 連號 | 改用 `next_attempt(operation_id=..., node=...)`；同 operation 換節點必須回到 1。 |
| 儲存重送又產生新文字；或 trace 洩漏 prompt | persist 失敗後重新呼叫 writer；直接序列化 request body 或用 `str(exc)` | 從 `operations/<operation_id>/<name>.json` 讀回已保存輸出（找不到 ref 就停止並保留失敗紀錄）；trace 用欄位 allowlist ＋ 只保留錯誤碼，發現內容或 secret 立即停止並清掉測試產物。 |
| Claude 被寫成 `invoke_model` | 兩種 API 的參數形狀混用 | Claude 一律 `converse`（`inferenceConfig`、`stopReason`），`invoke_model` 只留給 Titan；混用就停止。 |

## 10. 來源與 Rule 對照

- [執行教學流程.feature](../../spec/features/執行教學流程.feature)：Rule 4「每個 Bedrock 呼叫設定 max_tokens」、Rule 5「每個 Bedrock 呼叫設定逾時」、Rule 9「判斷節點使用低 temperature」→ 三條都是**相關**（primary 在 [Phase 18](18-Phase18-模型輸出業務驗證與有限重試.md)）。本 Phase 由 Task 2 斷言 `inferenceConfig == {"maxTokens": 512, "temperature": 0.1}`（有 `maxTokens`、低 `temperature`、沒有 `topP`）與 `bedrock_config()` 的 `connect_timeout == 2`、`read_timeout == 30`。
- [檢視學習指標.feature](../../spec/features/檢視學習指標.feature)：Rule 9「每次執行的 Bedrock 呼叫數包含 Step Functions 內的呼叫節點與 Rote 層呼叫」→ **相關**（primary 在 [Phase 54](54-Phase54-重開票與呼叫規則指標.md)）。本 Phase 提供「每次真實 request 恰一筆 trace」這個前提。
- 設計 §5、§7.6：`writing` 只做 Bedrock 呼叫、JSON 驗證與規則注入，不直接操作資料庫、不接受任意工具，也不新增公開 API 或業務實體。§12.1、§14.3：呼叫數以「每次實際送出的請求嘗試」計，記錄所屬操作、節點、模型、嘗試序號與結果；不把 request body、secret 或使用者全文寫進公開 log；只讓一層管理重試；Bedrock 連線最多 2 秒、等待回應最多 30 秒。§17.1、§18 O5：Claude 的 model ID／inference profile 由帳號確認後才固定，不填猜測值。
- [Bedrock Converse API](https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_Converse.html)：`system`、`messages`、`inferenceConfig`、`toolConfig`、`stopReason` 的形狀與 `AccessDeniedException`／`ValidationException`／`ThrottlingException` 等錯誤名稱。
- [Bedrock InvokeModel API](https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_InvokeModel.html)：一次 request 就是一個 attempt，是呼叫數定義的依據。[boto3 retries 設定](https://boto3.amazonaws.com/v1/documentation/api/latest/guide/retries.html)：`total_max_attempts` 含第一次請求，設為 1 等於關閉 SDK 這一層重試。

## 11. 完成清單

- [x] `Writer` 三個 method 的名稱、參數與回傳型別與 [00A 共用契約與名詞](00A-共用契約與名詞.md) §6.5 逐字一致，且模組路徑是 `src/training_kb/writing/client.py`（`writing/__init__.py` 已建立）。
- [x] Claude 走 `converse`、Titan 留給 `invoke_model`；`converse_with_tools` 每次只送一次 request。
- [x] 每次真實 request（包含例外）都恰有一筆 trace；`attempt` 依 `(operation_id, node)` 重新起算。
- [x] `CallTrace.add` 對多欄位、缺欄位、未知 `kind` 或 `outcome` 一律丟 `PermanentError`；trace 與例外訊息不含完整 prompt、payload、secret 或使用者全文。SDK 重試已關閉（`bedrock_config()` 的 `retries == {"total_max_attempts": 1}`），業務重試只留 Phase 18 一層，重用已保存輸出不增加 call count。
- [x] `tests/unit/conftest.py` 提供 `RecordingWriter` 與 `fake_writer`，三個方法簽名與 `Writer` 逐字一致，`replies`／`tool_plans` 用完即明確失敗。
- [x] 單元測試已真正執行並保存輸出，不以計畫文字當證據。
- [ ] Phase 14 O5 通過後才用 `TKB_RUN_AWS_INTEGRATION=1` 加 `-m aws` 執行並勾選 Bedrock 整合測試；skipped 不當成通過。（**維持未勾：O5 BLOCKED**，見 §12）

## 12. 實作期間的文件修正與裁決（2026-09-14）

| # | 位置 | 原文要點 | 改後 | 理由 |
|---|---|---|---|---|
| 1 | 全域限制、§8 停止條件、§11 最後一項 | 「O5 未通過時本階段標 BLOCKED」 | 「O5 未通過時**只有真實 Bedrock 整合測試** BLOCKED；程式與單元測試照常完成」 | controller 2026-09-14 裁決。Phase 16–18、37 都要 import 這支檔，整包卡住會擋住後面七個 Phase；O5 是帳號層級問題，不是程式問題。 |
| 2 | Task 1 Step 3 註解 | `writing/__init__.py` 內容只有一行 `from ... import BedrockWriter, CallTrace, Writer` | Task 1 只 re-export `CallTrace` 並加 `__all__`，Task 2 補齊 | Task 1 結束時 `BedrockWriter`／`Writer` 還不存在，照抄會 `ImportError`；另外 ruff 的 F401 會擋沒有 `__all__` 的 re-export。 |
| 3 | Task 2 Step 3 | 最小實作 sketch 沒有列 `Writer` Protocol | 明寫 `Writer` 在 Task 2 一併定義 | Task 4 的測試 `from training_kb.writing.client import Writer`，且 00A §6.5 把 `Writer` 列為本 Phase owner。 |
| 4 | Task 2／Task 4 的程式 sketch | 多處缺型別註記（`_request_once`、`_converse`、`BedrockWriter.__init__` 等） | 補上完整註記 | `pyproject.toml` 的 mypy 是 strict，缺註記無法過門檻。行為與 sketch 完全相同。 |
| 5 | Task 3 Step 2 | 預期紅燈訊號只寫 `KeyError: 'TKB_GENERATION_MODEL_ID'` | 補記實際會先撞 `KeyError: 'TKB_BEDROCK_REGION'` | 測試由左而右讀三個環境變數；兩個訊號是同一件事。 |

### O5 狀態

`docs/plan/report/o5-20260914T170050Z.md`：帳號 123456789012 尚未在 AWS Console 送出 Bedrock
model access 使用情境表單（`bedrock:GetUseCaseForModelAccess` 回
`ResourceNotFoundException: You have not filled out the request form.`），所以 Titan 與 Claude
的 `InvokeModel`／`Converse` 一律 `ValidationException: Operation not allowed`。
`TKB_GENERATION_MODEL_ID`／`TKB_EMBEDDING_MODEL_ID` **維持未設定**，不填猜測值。

停止語句照 00A §4.2 逐字保留：

> O5 未通過，本階段標 BLOCKED；`TKB_GENERATION_MODEL_ID` 保持 `<實測通過的 ID>` 佔位，不填猜測值。
