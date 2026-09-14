# Phase 16：Titan Embedding 與向量計算實作計畫

> **給實作者：** 依 checkbox 逐步執行；每個 Task 先建立失敗測試，再寫最小實作。執行時使用 `superpowers:subagent-driven-development`（建議）或 `superpowers:executing-plans`。

**目標：** 實作 Titan Text Embeddings V2 的 1024 維輸入輸出邊界，以及可重現、無 AWS 相依的 `cosine` 與 `centroid` 純函式。

**架構：** `Writer.embed` 接在 Phase 15 的 `BedrockWriter` 上，只送 Titan 支援的 embedding payload，回應先驗證長度與有限數值再交出去。相似度與群中心留在 `vectors.py`，供後續 Ticket 分群與 Release safety net 共用。

**技術：** Python 3.12、boto3（`bedrock-runtime` 的 `invoke_model`）、標準函式庫 `math`、pytest。

## 全域限制

- 唯一主來源是 [Training KB 設計 §7.3、§9.1、§10、§14.3、§17.1](../../design/training-kb.md)。讀者是要實作 Ticket embedding、群中心或語意比對的新手工程師。
- 前置為 [Phase 15：Writing 介面與呼叫追蹤](15-Phase15-Writing介面與呼叫追蹤.md)（`Writer`、`CallTrace`、`_request_once`），再往前是 [Phase 02](02-Phase02-設定時間與錯誤契約.md) 的錯誤契約與 [Phase 14](14-Phase14-O5模型可用性與參數驗證.md) 的 O5 模型驗證。
- 下一階段是 [Phase 17：Claude 結構化輸出與 Prompt](17-Phase17-Claude結構化輸出與Prompt.md)。消費本 Phase 產出的是 [Phase 38](38-Phase38-Ticket-Embedding與群中心分群.md)（Ticket 分群）、[Phase 49](49-Phase49-Release功能定位與Alias.md) 與 [Phase 50](50-Phase50-Release步驟反查與Safety-Net.md)（Feature 與步驟 safety net）。
- **O5 未通過時只有真實整合測試維持 FAIL／skip，其餘照常完成**（controller 2026-09-14 裁決；原文是「本階段標 BLOCKED」）：程式與單元測試照常交付，`tests/integration/test_titan_embedding.py` 維持 FAIL／skip。embedding model ID 取自 `Settings.embedding_model_id`（預設 `amazon.titan-embed-text-v2:0`），但沒有帳號實測證據就不得勾選整合驗收，也不可改用預填向量假稱 Titan 通過。真實 AWS／Bedrock 測試只有一種開關：測試標 `@pytest.mark.aws`，執行時設 `TKB_RUN_AWS_INTEGRATION=1`（Phase 01 的 conftest 在未設時自動 skip）。
- **Titan 用 `invoke_model`（Claude 才用 `converse`）**，request body 只有三個鍵，不得傳 `maxTokens`、`temperature`、`topP` 或 Claude Messages 欄位（設計 §14.3）。
- embedding 固定 1024 維，元素必須是有限的 `int` 或 `float`；`bool` 是 `int` 的子型別，但**不算數值**，要一起拒絕。
- `cosine` 的 0.85 門檻屬於 Phase 38／49／50 的業務判斷；本階段只提供正確計算與錯誤契約，不定義門檻常數（門檻的唯一來源是 Phase 02 的 `Thresholds.cosine_match`）。
- 本階段不做：不持久化 Feature／Step 向量、不新增 ERM 欄位、不建立向量資料庫或搜尋服務、不命名 gap、不決定分群結果。每次真實 Titan request 仍經 Phase 15 的 `CallTrace` 記一筆 `kind="embedding"` 的 attempt。
- 以下程式檔均是實作時預計建立或修改；本計畫本身不代表它們已存在。

---

## 1. 你在整體流程的位置

```text
Ticket.text / Feature 名稱 / 步驟文字
        |
        v
[你在這裡：Writer.embed] --> Titan V2（invoke_model）--> 1024 維有限數值
        |  CallTrace +1（kind=embedding）                  |
        v                                                  v
Ticket.embedding（只有 Ticket 持久化）   vectors.py：centroid / cosine
                                                   |
                                                   v
                              Phase 38 分群 / Phase 49、50 語意定位
```

向量只在 Ticket 需要時保存；Feature 與 Step 的向量可在單次執行的記憶體內重用，不寫回 DynamoDB（設計 §10）。

## 2. 完成後看得到什麼

具體輸入：兩個正交向量 `[1.0, 0.0]` 與 `[0.0, 1.0]`。可觀察結果是 `cosine(...) == 0.0`，`centroid([[1.0, 0.0], [0.0, 1.0]]) == [0.5, 0.5]`；單一向量的 `centroid` 回它自己。另一個具體輸入：`writer.embed("prepare meeting", operation_id="op-e", node="embed")`。可觀察結果是送出的 JSON body 恰好是 `{"inputText": "prepare meeting", "dimensions": 1024, "normalize": true}`，回傳 1024 個有限 `float`，`trace.count(operation_id="op-e") == 1`。真實 Titan 回應若不是 1024 維，立刻以 `PermanentError` 結束，不保存 `Ticket.embedding`。

## 3. 名詞小抄

| 名詞 | 白話意思 |
|---|---|
| embedding（向量） | 把一段文字換成一串數字，方向相近代表語意相近。本專案固定 1024 個數字。 |
| cosine（餘弦相似度） / centroid（群中心） | 前者是兩個向量方向有多接近：1 是完全同向，0 是垂直，可能是負數；後者是一群向量逐維平均後的代表向量，不是挑其中一筆當代表。 |
| normalize / 有限數值 | `normalize` 是 Titan 的參數（要不要把輸出向量縮成長度 1，本專案固定 `true`，比較才穩定）；「有限數值」指不是 `NaN`、也不是無限大的數字，`NaN` 參與比較時永遠回 `False`，會讓門檻判斷靜靜失準。 |
| `StreamingBody` | boto3 `invoke_model` 回應裡 `body` 的型別：**不是 dict，要先 `.read()` 拿 bytes 再 `json.loads`**，而且只能讀一次。 |
| `PermanentError` / `_request_once` | 前者是 Phase 02 的永久錯誤（資料確定不合法，重送沒有意義，由 ASL 的 Catch 收掉）；後者是 Phase 15 的私有方法，送出一次 Bedrock request 並寫一筆 `CallTrace`，自己不重試。 |

## 4. 預計檔案

| 動作 | 路徑 | 責任 |
|---|---|---|
| 建立 | `src/training_kb/vectors.py` | `cosine`、`centroid` 與共用的向量輸入檢查。 |
| 修改 | `src/training_kb/writing/client.py` | 在 Phase 15 的 `BedrockWriter` 上補 `embed` 與 Titan 回應驗證。 |
| 建立 | `tests/unit/test_vectors.py` | 向量純函式與邊界測試。 |
| 建立 | `tests/unit/test_titan_writer.py` | Titan request body 與 response 驗證。 |
| 建立 | `tests/integration/test_titan_embedding.py` | O5 通過後的小量實際呼叫。 |

## 5. 固定介面

### Consumes

```text
BedrockWriter._request_once(call, *, model, operation_id, node, kind)   Phase 15
BedrockWriter._embed_id（來自 Settings.embedding_model_id）              Phase 15 / Phase 02
CallTrace.add / CallTrace.count / build_bedrock_client(region)          Phase 15
TransientError / PermanentError                                        Phase 02
```

Titan request 的完整業務 payload 固定為 `{"inputText": text, "dimensions": 1024, "normalize": True}` 三個鍵，多一個就是錯。

### Produces

```python
TITAN_DIMENSIONS = 1024                   # writing/client.py

def cosine(left: list[float], right: list[float]) -> float: ...        # vectors.py
def centroid(vectors: list[list[float]]) -> list[float]: ...           # vectors.py

class BedrockWriter:                      # Phase 15 的類別，本 Phase 只補這一個方法
    def embed(self, text: str, *, operation_id: str, node: str) -> list[float]: ...
```

錯誤契約（與 [00A 共用契約與名詞](00A-共用契約與名詞.md) §4.1 一致，**不使用 `ValueError`**）：`embed` 對空白文字、非 1024 維、`NaN`、`Infinity`、`bool` 或非數值元素丟 `PermanentError`，SDK 的暫時性故障由 Phase 15 的 `_request_once` 轉成 `TransientError`；`cosine` 對空向量、長度不一致、零向量與非有限元素丟 `PermanentError`，`centroid` 對空集合、長度不一致與非有限元素丟 `PermanentError`。之所以不用 `ValueError`：00A §4.1 把整套錯誤語彙固定成六個類別，ASL 的 `Retry` 也只認得 `TransientError` 這個名字（00A §3.7）。家族外的例外雖然仍會被 [Phase 29](29-Phase29-共用Pipeline執行器與ASL失敗語意.md) 的 `run_sequence` 記進 `OperationCoordinator.fail(...)`（它攔的是 `Exception`），但一律被記成 `retryable=False`，呼叫端也分不出暫時與永久。

## 6. 設計細節

```text
embed 的檢查順序（任何一關不過就 PermanentError，不保存 Ticket.embedding）

text -- 空白？ --是--> PermanentError（不送 request、不計 attempt）
   v 否
body = {"inputText", "dimensions": 1024, "normalize": true}   <-- 沒有生成參數
   v
Phase 15 _request_once(kind="embedding") --> CallTrace +1
   v
json.loads(response["body"].read())["embedding"]   <-- body 是 StreamingBody
   +--> 不是 list ／ 長度 != 1024 ／ 含 bool 或字串 ／ 含 NaN、Infinity --> PermanentError
   +--> 全部通過 --> list[float]（1024 個）
```

四個容易做錯的地方：

1. **`body` 不是 dict。** boto3 `invoke_model` 的回應把模型輸出放在 `StreamingBody`，一律寫成 `json.loads(response["body"].read())`，而且只能讀一次；測試替身要用同形狀的 `{"body": io.BytesIO(...)}`，不要直接回 dict，否則測試綠燈而正式路徑 `AttributeError`（Claude 走 `converse` 時回的是一般 dict，兩邊不可互抄）。
2. **`bool` 要先擋。** Python 的 `True` 是 `int` 的子型別，`isinstance(True, (int, float))` 與 `math.isfinite(True)` 都成立；檢查順序必須是「先排除 `bool`，再判斷型別，最後才 `math.isfinite`」，而且最後這步只在確定是數值後執行，避免對字串丟 `TypeError`。
3. **`NaN` 不能放行。** `float("nan") >= 0.85` 永遠是 `False`，所以一個 `NaN` 向量不會讓程式爆炸，只會讓 Phase 38 安靜地判成「沒有合格群」而多開一個 cluster。這種靜默失準比直接失敗更難查。
4. **`cosine` 不檢查 1024 維，但運算順序固定。** 它是通用純函式，單元測試用二、五維向量驗算，維度是 Titan 回應的契約、檢查點在 `embed`；運算固定是「先算內積，再除以兩個長度的乘積」（`dot / (norm_left * norm_right)`，不先除一次再除一次、也不做四捨五入），Phase 38 才能用整數構成的向量斷言 `cosine(AXIS, ON) == 0.85` 這種精確值。`centroid` 逐維相加後除以向量筆數，只有一筆時回傳那一筆本身，Phase 38 的單樣本群也走同一條路徑。

## 7. TDD Tasks

### Task 1：鎖定 cosine 與 centroid 的數學與錯誤契約

**Files:** Create `src/training_kb/vectors.py`、`tests/unit/test_vectors.py`

- [x] **Step 1：建立失敗測試**

```python
import pytest

from training_kb.errors import PermanentError
from training_kb.vectors import centroid, cosine

NAN = float("nan")


def test_cosine_and_centroid_are_deterministic() -> None:
    assert cosine([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)
    assert cosine([1.0, 1.0], [1.0, 1.0]) == pytest.approx(1.0)
    assert cosine([1.0, 0.0], [-1.0, 0.0]) == pytest.approx(-1.0)
    assert cosine([1.0, 0.0, 0.0], [17.0, 0.0, 0.0]) == 1.0
    assert cosine([1.0, 0.0, 0.0, 0.0, 0.0], [17.0, 7.0, 6.0, 5.0, 1.0]) == 0.85
    assert centroid([[1.0, 0.0], [0.0, 1.0]]) == [0.5, 0.5]
    assert centroid([[0.25, 0.5]]) == [0.25, 0.5]


@pytest.mark.parametrize("left,right", [
    ([], [1.0]),
    ([1.0, 0.0], [1.0]),
    ([0.0, 0.0], [1.0, 0.0]),
    ([NAN, 1.0], [1.0, 0.0]),
    ([True, 1.0], [1.0, 0.0]),
])
def test_cosine_rejects_bad_input(left: list, right: list) -> None:
    with pytest.raises(PermanentError):
        cosine(left, right)


@pytest.mark.parametrize("vectors", [[], [[]], [[1.0, 0.0], [1.0]], [[1.0, NAN]]])
def test_centroid_rejects_bad_input(vectors: list) -> None:
    with pytest.raises(PermanentError):
        centroid(vectors)
```

第五個斷言是 Phase 38 邊界向量的原型（`AXIS`／`ON` 逐字相同）：`|left| = 1`、`|right| = sqrt(289+49+36+25+1) = 20`、內積 17，`17.0 / (1.0 * 20.0)` 與字面值 `0.85` 是同一個 float，所以門檻測試可以用 `==` 而不是 `approx`。

- [x] **Step 2：執行並確認紅燈**

```bash
uv run pytest tests/unit/test_vectors.py -q
```

預期：FAIL，訊號包含 `ModuleNotFoundError: No module named 'training_kb.vectors'`。

- [x] **Step 3：建立最小實作**

```python
import math

from training_kb.errors import PermanentError


def _checked(vector: list[float], *, expected: int | None = None) -> list[float]:
    if not vector:
        raise PermanentError("vector must not be empty")
    if expected is not None and len(vector) != expected:
        raise PermanentError(f"vector length {len(vector)} does not match {expected}")
    for value in vector:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise PermanentError(f"vector contains a non-numeric value: {value!r}")
        if not math.isfinite(value):
            raise PermanentError(f"vector contains a non-finite value: {value!r}")
    return [float(value) for value in vector]


def cosine(left: list[float], right: list[float]) -> float:
    first = _checked(left)
    second = _checked(right, expected=len(first))
    first_norm = math.sqrt(sum(value * value for value in first))
    second_norm = math.sqrt(sum(value * value for value in second))
    if first_norm == 0.0 or second_norm == 0.0:
        raise PermanentError("zero vector has no cosine similarity")
    dot = sum(a * b for a, b in zip(first, second, strict=True))
    return dot / (first_norm * second_norm)


def centroid(vectors: list[list[float]]) -> list[float]:
    if not vectors:
        raise PermanentError("centroid needs at least one vector")
    first = _checked(vectors[0])
    rows = [first] + [_checked(row, expected=len(first)) for row in vectors[1:]]
    return [sum(column) / len(rows) for column in zip(*rows, strict=True)]
```

- [x] **Step 4：跑完整檔案確認綠燈**

```bash
uv run pytest tests/unit/test_vectors.py -q
```

預期：`10 passed`（1 個正常案例 + 5 個 cosine 邊界 + 4 個 centroid 邊界）；每個邊界案例丟的都是 `PermanentError`，沒有任何 `ValueError`。

- [x] **Step 5：提交**

```bash
git add src/training_kb/vectors.py tests/unit/test_vectors.py
git commit -m "feat(writing): 增加向量計算函式"
```

### Task 2：Titan request 只帶 embedding 參數，回應必須 1024 維有限數值

**Files:** Modify `src/training_kb/writing/client.py`；Create `tests/unit/test_titan_writer.py`

- [x] **Step 1：建立失敗測試**

```python
import io
import json
from typing import Any

import pytest

from training_kb.errors import PermanentError
from training_kb.writing.client import TITAN_DIMENSIONS, BedrockWriter, CallTrace, Writer


class FakeTitanClient:          # 回應形狀與真實 invoke_model 一致：body 只能讀一次
    def __init__(self, embedding: object) -> None:
        self.embedding: object = embedding
        self.json_body: dict[str, Any] | None = None
        self.calls = 0

    def invoke_model(self, *, modelId: str, body: str) -> dict[str, Any]:
        self.calls += 1
        self.json_body = json.loads(body)
        payload = {"embedding": self.embedding, "inputTextTokenCount": 3}
        return {"body": io.BytesIO(json.dumps(payload).encode())}


def make_writer(client: object) -> BedrockWriter:
    return BedrockWriter(client, CallTrace(), generation_model_id=None,
                         embedding_model_id="amazon.titan-embed-text-v2:0")


def test_titan_request_has_only_embedding_fields_and_one_attempt() -> None:
    client = FakeTitanClient([0.0] * 1023 + [1.0])
    writer = make_writer(client)
    vector = writer.embed("prepare meeting", operation_id="op-e", node="embed")
    assert client.json_body == {"inputText": "prepare meeting", "dimensions": 1024,
                                "normalize": True}
    assert {"maxTokens", "temperature", "topP"}.isdisjoint(client.json_body)
    assert len(vector) == 1024 and vector[1023] == 1.0
    assert writer.trace.count(operation_id="op-e") == 1
    assert json.loads(writer.trace.to_json())[0]["kind"] == "embedding"


@pytest.mark.parametrize("embedding", [
    [0.0] * 1023,
    [0.0] * 1025,
    [0.0] * 1023 + [float("nan")],
    [0.0] * 1023 + [float("inf")],
    [0.0] * 1023 + [True],
    [0.0] * 1023 + ["1.0"],
    {"not": "a list"},
])
def test_embed_rejects_wrong_dimension_or_non_finite(embedding: object) -> None:
    writer = make_writer(FakeTitanClient(embedding))
    with pytest.raises(PermanentError):
        writer.embed("meeting summary", operation_id="op-e", node="embed")


def test_embed_refuses_blank_text_without_calling_titan() -> None:
    client = FakeTitanClient([0.0] * 1024)
    writer = make_writer(client)
    with pytest.raises(PermanentError):
        writer.embed("   ", operation_id="op-e", node="embed")
    assert client.calls == 0 and writer.trace.count() == 0


def test_bedrock_writer_satisfies_the_writer_protocol() -> None:
    """補上 embed 之後 BedrockWriter 才完整實作 Writer；這一行由 mypy 檢查形狀。"""
    client = FakeTitanClient([0.0] * TITAN_DIMENSIONS)
    writer: Writer = BedrockWriter(client, CallTrace(), generation_model_id=None,
                                   embedding_model_id="amazon.titan-embed-text-v2:0")
    assert len(writer.embed("protocol", operation_id="op-p", node="embed")) == TITAN_DIMENSIONS
```

`FakeTitanClient` 的欄位逐一標註（而不是一行 tuple 指派）、`invoke_model` 回 `dict[str, Any]`
（而不是裸 `dict`），是為了讓這支測試檔本身也能過 `uv run mypy`；行為與原稿完全相同。
最後一條是 Phase 15 留下的 Protocol 斷言（`mypy` 專案設定只看 `src`，因此另跑
`uv run mypy src tests/unit/test_titan_writer.py` 當證據）：拿掉 `embed` 時 mypy 會回
`"BedrockWriter" is missing following "Writer" protocol member: embed`。

- [x] **Step 2：執行並確認紅燈**

```bash
uv run pytest tests/unit/test_titan_writer.py -q
```

預期：FAIL。實際訊號是 `ImportError: cannot import name 'TITAN_DIMENSIONS' from 'training_kb.writing.client'`（收集階段先撞到常數）；直接呼叫則是 `AttributeError: 'BedrockWriter' object has no attribute 'embed'`。

- [x] **Step 3：建立最小實作**

在 Phase 15 的 `BedrockWriter` 類別上補 `embed`，並在同一個模組加上回應驗證：

```python
import math

TITAN_DIMENSIONS = 1024


def _validated_embedding(value: object) -> list[float]:
    if not isinstance(value, list) or len(value) != TITAN_DIMENSIONS:
        raise PermanentError(f"Titan embedding must contain {TITAN_DIMENSIONS} values")
    for item in value:
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            raise PermanentError(f"Titan embedding contains a non-numeric value: {item!r}")
        if not math.isfinite(item):
            raise PermanentError(f"Titan embedding contains a non-finite value: {item!r}")
    return [float(item) for item in value]


class BedrockWriter:                      # 接在 Phase 15 的同一個類別上
    def embed(self, text: str, *, operation_id: str, node: str) -> list[float]:
        if not text.strip():
            raise PermanentError("embedding input must not be blank")
        body = json.dumps({"inputText": text, "dimensions": TITAN_DIMENSIONS,
                           "normalize": True})
        response = self._request_once(
            lambda: self.client.invoke_model(modelId=self._embed_id, body=body),
            model=self._embed_id, operation_id=operation_id, node=node, kind="embedding")
        payload = json.loads(response["body"].read())
        return _validated_embedding(payload.get("embedding"))
```

空白文字在送出 request **之前**就擋掉，所以不會產生 attempt；這是本計畫選擇：Titan 也會回 `ValidationException`，但先擋可以少一次計費請求，也讓錯誤訊息指向真正的欄位。

- [x] **Step 4：跑完整檔案確認綠燈**

```bash
uv run pytest tests/unit/test_vectors.py tests/unit/test_titan_writer.py -q
```

預期：`20 passed`（向量 10 筆 + Titan 10 筆：原稿 9 筆再加一條 Protocol 斷言）。1024 個有限數值成功；1023／1025 維、`NaN`、`Infinity`、字串、`bool` 與非 list 全部被拒絕；空白文字時 `client.calls == 0`。

- [x] **Step 5：提交**

```bash
git add src/training_kb/writing/client.py tests/unit/test_titan_writer.py
git commit -m "feat(writing): 驗證 Titan 向量輸出"
```

### Task 3：O5 通過後用真實 Titan 核對維度與呼叫數

**Files:** Create `tests/integration/test_titan_embedding.py`

- [x] **Step 1：建立失敗測試**

```python
import math
import os

import pytest

from training_kb.vectors import cosine
from training_kb.writing.client import BedrockWriter, CallTrace, build_bedrock_client

pytestmark = pytest.mark.aws      # Phase 01 conftest：TKB_RUN_AWS_INTEGRATION != "1" 時自動 skip


def test_real_titan_returns_1024_finite_values() -> None:
    trace = CallTrace()
    writer = BedrockWriter(build_bedrock_client(os.environ["TKB_BEDROCK_REGION"]), trace,
                           generation_model_id=None,
                           embedding_model_id=os.environ["TKB_EMBEDDING_MODEL_ID"])
    first = writer.embed("會前摘要在哪裡開啟？", operation_id="smoke-titan", node="embed")
    second = writer.embed("如何看到開會前整理的重點？", operation_id="smoke-titan", node="embed")
    assert len(first) == len(second) == 1024
    assert all(math.isfinite(value) for value in first)
    assert -1.0 <= cosine(first, second) <= 1.0
    assert trace.count(operation_id="smoke-titan") == 2
```

- [x] **Step 2：執行並確認紅燈**

```bash
TKB_RUN_AWS_INTEGRATION=1 uv run pytest tests/integration/test_titan_embedding.py -q -m aws
```

預期：FAIL，訊號是 `KeyError: 'TKB_EMBEDDING_MODEL_ID'`（環境變數還沒接上）或 `AccessDeniedException`（帳號未開通 model access）。兩種訊號都代表本 Phase 維持 BLOCKED。

- [ ] **Step 3：建立最小實作**（BLOCKED：帳號未開通 Bedrock model access）

本 Task 不新增產品程式；「實作」是把 Phase 14 `check_models.py` 實測出的兩個值接上環境變數再跑。不得為了讓測試變綠而改小維度斷言、拿掉 `-m aws`，或改用預先準備的向量。

```bash
export TKB_BEDROCK_REGION=<Phase 14 實測 Region>
export TKB_EMBEDDING_MODEL_ID=amazon.titan-embed-text-v2:0
```

- [ ] **Step 4：跑完整檔案確認綠燈**（BLOCKED：實跑得到 `PermanentError: ValidationException`，底層是 `Operation not allowed`）

```bash
TKB_RUN_AWS_INTEGRATION=1 uv run pytest tests/integration/test_titan_embedding.py -q -m aws
```

預期：`1 passed`，trace 增加兩筆 `kind=embedding`，並保留 Region、model ID、維度與 `inputTextTokenCount` 當證據。沒有帳號時輸出是 `1 skipped`，**skipped 不等於通過**。

- [x] **Step 5：提交**

```bash
git add tests/integration/test_titan_embedding.py
git commit -m "test(writing): 鎖定 Titan 請求契約"
```

## 8. 驗收矩陣

| 路徑 | 輸入 | 預期資料結果 |
|---|---|---|
| Happy | fake Titan 以 `StreamingBody` 回 1024 個有限數值 | 回 `list[float]` 長度 1024；trace 多一筆 `kind=embedding`；送出的 body 鍵集合精確等於 `{inputText, dimensions, normalize}` 且 `dimensions` 是 1024。 |
| Failure | 1023／1025 維、`NaN`、`Infinity`、字串、`bool` 回應；或空白 `text` | 都丟 `PermanentError`，不保存 `Ticket.embedding`；空白 `text` 另外要 `client.calls == 0`、trace 不增加。 |
| Boundary | `cosine` 用相同向量／正交向量／反向向量／`17 /(1 * 20)` | `1.0`／`0.0`／`-1.0`／`0.85`；0.85 門檻不在本 Phase 決策。 |
| Boundary | `centroid` 空集合、長度不一致、單一向量 | 前兩者 `PermanentError`；單一向量回它自己。 |

人工驗收：O5 通過後，實際比對兩段「同一個問題的不同問法」的 cosine 明顯高於兩段不相關文字，並把 Region、model ID、維度與 token 數留成證據。停止條件（controller 2026-09-14 裁決後）：Phase 14 未確認 Region 與 model access，或真實 response 結構不符時，**只有真實 Titan 整合測試維持 FAIL／skip**，程式與單元測試照常完成；保留實際錯誤當證據，不改用預填向量假稱 Titan 通過。

## 9. 常見錯誤與停止條件

| 症狀 | 原因 | 修正／停止 |
|---|---|---|
| 單元測試綠燈但真跑 `AttributeError: 'dict' object has no attribute 'read'` | test double 把 `body` 做成 dict，真實回應是 `StreamingBody` | 替身改用 `{"body": io.BytesIO(...)}`；正式路徑一律 `json.loads(response["body"].read())`。 |
| Titan 回 `ValidationException` | 共用生成設定被併進 embedding body，或誤用 `converse` | embedding 只走 `invoke_model` 並單獨建 body；body 還有生成鍵就停止。 |
| 分群結果莫名多出新 cluster；或 `cosine` 除以零 | 向量含 `NaN`（門檻比較永遠 `False`），或群中心與輸入是零向量 | `_checked`／`_validated_embedding` 明確拒絕非有限值，零向量明確丟 `PermanentError`、不得當成 0 相似度；看到靜默新群就停止查向量來源。 |
| 失敗沒有留下 operation 紀錄 | 用 `ValueError` 而不是 `PermanentError` | Phase 29 只攔 `TransientError`／`PermanentError`；改回專案錯誤類別。 |
| 測試全用 2 維卻宣稱 Titan 合格 | 純數學測試與 API 契約混在一起 | 維度檢查放 `embed`，另做 1024 維 response 與真實 smoke test；沒跑整合測試就保持未驗證。 |

## 10. 來源與 Rule 對照

- [分析工單.feature](../../spec/features/分析工單.feature)：Rule 1「每則 Ticket 在接入分析時計算一次並儲存 1024 維 embedding」與 Rule 2「demo 分群以 cosine 至少 0.85 為同群門檻」→ 兩條都是**相關**（primary 在 [Phase 38](38-Phase38-Ticket-Embedding與群中心分群.md)）。本 Phase 由 Task 2 斷言回應精確 1024 維、每次 request 恰一筆 attempt，並保證 `cosine` 的值正確且不四捨五入。
- [依改版更新教學.feature](../../spec/features/依改版更新教學.feature)：Rule 4「alias 比對未命中時以向量搜尋最相近的 Feature」→ **相關**（primary 在 [Phase 49](49-Phase49-Release功能定位與Alias.md)）；Rule 6「反查為零或重大改名時使用 step 文字向量搜尋補漏」→ **相關**（primary 在 [Phase 50](50-Phase50-Release步驟反查與Safety-Net.md)）。
- 設計 §7.3、§9.1：`Ticket.embedding` 是含 1024 個有限數值的原生清單，缺少時才呼叫 Titan 產生，不另存 `embedding_ref`。§10：少量語意比對在 Lambda 計算，不新增向量服務，也不持久化 Feature／Step 向量。§14.3：Titan V2 是 embedding API，不使用文字生成的 `max_tokens`／`temperature`；設定輸入上限、1024 維輸出與 timeout，生成模型才傳輸出 token 上限。§17.1、§18 O5：Titan V2 的 model ID 為 `amazon.titan-embed-text-v2:0` 且支援 1024 維；帳號權限、Region 與配額仍須部署前確認。
- [Titan Embeddings 模型](https://docs.aws.amazon.com/bedrock/latest/userguide/titan-embedding-models.html)：V2 請求欄位為 `inputText`、`dimensions`、`normalize`，回應含 `embedding` 與 `inputTextTokenCount`，不支援 `maxTokenCount`／`topP`。[Bedrock InvokeModel API](https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_InvokeModel.html)：`body` 是模型專屬 JSON，回應的 `body` 以 streaming body 取得。

## 11. 完成清單

- [x] `Writer.embed` 的名稱與 keyword-only 追蹤參數與 [00A 共用契約與名詞](00A-共用契約與名詞.md) §6.5 逐字一致，實作在 `src/training_kb/writing/client.py`，經 Phase 15 的 `_request_once`，`kind` 是 `embedding`。
- [x] Titan 走 `invoke_model`，body 的鍵集合精確等於 `{inputText, dimensions, normalize}`，沒有任何生成模型參數。
- [x] 回應一律以 `json.loads(response["body"].read())` 解析，測試替身用 `{"body": io.BytesIO(...)}` 維持同形狀。
- [x] 1024 維、非有限值、`bool`、非 list 與空白文字的邊界都有測試且都丟 `PermanentError`；`cosine` 與 `centroid` 是無 AWS 相依的純函式，錯誤一律用 `PermanentError`、不用 `ValueError`，`centroid` 對單一向量回它自己、對空集合拒絕。
- [x] 每次實際 Titan request 在 `CallTrace` 恰記一筆（單元測試斷言 `count == 1`；2026-09-14 的真實呼叫被拒時也只留一筆 `kind=embedding`／`outcome=permanent_error`）。
- [ ] **BLOCKED**：真實整合測試只在 Phase 14 O5 gate 通過後、以 `TKB_RUN_AWS_INTEGRATION=1` 加 `-m aws` 執行才勾選，skipped 不當成通過。2026-09-14 實跑 `us-east-1` + `amazon.titan-embed-text-v2:0` 得到 `PermanentError: ValidationException`（底層 `Operation not allowed`），與 `docs/plan/report/o5-20260914T170050Z.md` 一致。
- [x] 沒有建立向量資料庫、沒有新增 ERM 欄位、沒有部署，也沒有在本 Phase 定義 0.85 門檻常數。
