# Phase 14：O5 模型可用性與參數驗證實作計畫

> **給實作者：** 依 checkbox 逐步執行；每個 Task 先建立失敗測試，再寫最小實作。執行時使用 `superpowers:executing-plans` 或同等逐項流程。

**目標：** 用真實帳號做兩個小量 probe，確認 Region、模型可呼叫性、Titan 1024 維輸出與 Claude `converse` 的參數支援，並輸出後續 Phase 需要的 model ID；沒有權限就產生 BLOCKED 報告，不填猜測值。

> **O5 gate 結果（2026-09-14）：BLOCKED。** 程式與測試已全部完成，但真實帳號 123456789012 尚未送出 Bedrock model access 使用情境表單，`us-east-1`／`ap-northeast-1` 的所有 runtime 呼叫一律回 `ValidationException: Operation not allowed`。證據見 [`docs/plan/report/o5-20260914T170050Z.md`](../report/o5-20260914T170050Z.md)；`check_models.py` exit code 為 2，Phase 15–18 維持 blocked。

**架構：** `infra/scripts/check_models.py` 是一次性的部署前檢查腳本，不進 Lambda runtime。它用 `bedrock` control plane 列模型、用 `bedrock-runtime` 送兩個最小 request，再把結果寫成 O5 報告與 `.env` 片段。Phase 15 的 `Writer` 只讀設定，不自己探測。

**技術：** Python 3.12、boto3（`bedrock` 與 `bedrock-runtime` 兩個 client）、pytest、隔離的 Demo AWS 帳號。

## 全域限制

- 唯一主來源是 [Training KB 設計 §14.3、§17.1、§17.3、§18 O5](../../design/training-kb.md)。
- 前置為 [Phase 13：O6 來源 ID 與穩定使用者契約](./13-Phase13-O6來源ID與穩定使用者契約.md)。下一階段是 [Phase 15：Writing 介面與呼叫追蹤](./15-Phase15-Writing介面與呼叫追蹤.md)。
- 本階段不寫 prompt、不驗 JSON schema、不做業務重試、不接 pipeline。**生成與 embedding 的參數必須分開建構。** Titan 的 request body 不得出現 `maxTokens`、`temperature`、`topP` 或 Messages 欄位；Claude 只設 `temperature`，不同時調 `topP`。
- **不填猜測的 Claude model ID 或 inference profile。** 沒有實際回應就是 `blocked`／`unavailable`，停止語句固定是「O5 未通過，本階段標 BLOCKED；`TKB_GENERATION_MODEL_ID` 保持 `<實測通過的 ID>` 佔位，不填猜測值」，[Phase 15](./15-Phase15-Writing介面與呼叫追蹤.md)、[Phase 16](./16-Phase16-Titan-Embedding與向量計算.md)、[Phase 17](./17-Phase17-Claude結構化輸出與Prompt.md)、[Phase 18](./18-Phase18-模型輸出業務驗證與有限重試.md) 保持 blocked。
- **不承諾免費或固定成本。** 每次 probe 都是計費請求；Free Tier 與 credits 取決於帳號方案與服務條款。
- 需要真實帳號的測試只有**一種**開關（00A 第 3.1 節、裁決 D-41）：測試標 `@pytest.mark.aws`，執行時設 `TKB_RUN_AWS_INTEGRATION=1`；沒設時 [Phase 01](./01-Phase01-專案骨架與離線品質門檻.md) 的 `tests/conftest.py` 會自動跳過。Bedrock 也算「需要真實帳號」，**不得**另外發明 Bedrock 專用的環境變數開關。
- 腳本只把 `.env` 片段印到 stdout；確認 `.env` 已被 git 忽略之前不建立該檔（設計 §2、§17.2）。以下程式檔均是實作時預計建立或修改，本計畫不代表它們已存在。

---

## 1. 你在整體流程的位置

```text
AWS 帳號 + 選定 Region
        |
        v
[你在這裡：check_models.py 兩個 probe]
        |
   +----+---------------------------+
   |                                |
全部 ok                        任一非 ok
   |                                |
   v                                v
.env 片段 -> Phase 15 Writer    BLOCKED 報告
Phase 16 Titan / 17 Claude      Phase 15–18 保持 blocked
```

## 2. 完成後看得到什麼

在選定 Region 執行 `uv run python infra/scripts/check_models.py --region <region>`，成功時 stdout 出現：

```text
purpose    | model_id                      | status | detail
-----------+-------------------------------+--------+---------------------------
embedding  | amazon.titan-embed-text-v2:0  | ok     | 1024 維、8 tokens
generation | <實測通過的 ID>                | ok     | stopReason=end_turn、12 tokens

TKB_BEDROCK_REGION=<region>
TKB_EMBEDDING_MODEL_ID=amazon.titan-embed-text-v2:0
TKB_GENERATION_MODEL_ID=<實測通過的 ID>
```

帳號未開通 model access 時，同一條指令改印 `status=blocked`、`detail=AccessDeniedException`，而且**不印任何 `TKB_GENERATION_MODEL_ID`**。

## 3. 名詞小抄

| 名詞 | 白話意思 |
|---|---|
| O5／gate | `O1`–`O7` 是[設計 §18](../../design/training-kb.md) 七個待確認事項的編號，O5 就是「模型與參數驗證」這一條；gate 是必須有真實證據才能通過的關卡，文件寫得再完整都不能關閉它。 |
| control plane／runtime | `bedrock` client 只查「這個 Region 有哪些模型」；`bedrock-runtime` client 才真的送出推論請求並計費。 |
| inference profile | 跨區推論用的識別（例如 `us.` 開頭）；`ListFoundationModels` 不會列出它。 |
| probe／`converse` | probe 是一次最小的實際呼叫，用來證明「這個帳號現在真的叫得動」；`converse` 是 Bedrock 的統一對話 API，生成參數放在 `inferenceConfig`。 |
| BLOCKED | 因為權限、Region 或配額而無法驗證的狀態；不是「暫時先當成可用」。 |
| `TKB_RUN_AWS_INTEGRATION` | 真實帳號測試的唯一開關（執行期環境變數）。設成 `1` 才會真的送出計費請求；沒設就自動跳過標了 `aws` 的測試。 |

## 4. 預計檔案

| 動作 | 路徑 | 責任 |
|---|---|---|
| 新增 | `infra/scripts/check_models.py` | 列模型、兩個 probe、`.env` 片段與報告輸出；報告寫到 `docs/plan/report/o5-<run-id>.md`。 |
| 新增 | `.env.example` | 只列 `TKB_BEDROCK_REGION`／`TKB_EMBEDDING_MODEL_ID`／`TKB_GENERATION_MODEL_ID` 三個鍵名與說明，不含任何值。 |
| 測試 | `tests/unit/test_check_models.py` | 候選挑選、request body 純度、錯誤分類、報告格式；整合檔 `tests/integration/test_o5_probe.py` 做真實帳號小量呼叫（整支標 `@pytest.mark.aws`），無權限時明確 BLOCKED。 |

## 5. 固定介面

### Consumes

```text
boto3.client("bedrock", ...)          # list_foundation_models / list_inference_profiles
boto3.client("bedrock-runtime", ...)  # invoke_model / converse
botocore.config.Config                # connect_timeout / read_timeout / retries
botocore.exceptions.ClientError       # response["Error"]["Code"]
設計 §14.3：判斷 max_tokens 512／temperature 0.1；連線 2 秒、讀取 30 秒；只讓一層管理重試
設計 §17.1：Titan V2 為 amazon.titan-embed-text-v2:0，輸出 1024 維
00A §3.5：環境變數 TKB_BEDROCK_REGION / TKB_EMBEDDING_MODEL_ID / TKB_GENERATION_MODEL_ID
```

### Produces

```python
ProbeStatus = Literal[
    "ok", "blocked", "unavailable", "param_unsupported", "quota", "retry_later", "unknown",
]

@dataclass(frozen=True)
class ModelProbe:
    purpose: Literal["embedding", "generation"]
    model_id: str
    region: str
    status: ProbeStatus
    detail: str
    tokens: int | None

def list_candidates(bedrock: object, *, output_modality: str) -> tuple[str, ...]: ...
def classify_error(error: Exception) -> ProbeStatus: ...
def probe_embedding(runtime: object, model_id: str, *, region: str) -> ModelProbe: ...
def probe_generation(runtime: object, model_id: str, *, region: str) -> ModelProbe: ...
def render_env(probes: Sequence[ModelProbe]) -> str: ...
def render_o5_report(probes: Sequence[ModelProbe], *, run_id: str) -> str: ...
def main(argv: Sequence[str] | None = None) -> int: ...
```

`main` 的 exit code：全部 `ok` 回 0，任一非 `ok` 回 2。CI 或人工都用 exit code 判斷 gate，不看文字。

## 6. 設計細節

### 6.1 兩種請求形狀完全不同

```text
embedding 路徑                      | generation 路徑
------------------------------------+--------------------------------------------
invoke_model(modelId=EMBED_ID,      | converse(modelId=GEN_ID,
  body={"inputText","dimensions",   |   messages=[{"role","content":[{"text"}]}],
         "normalize"})              |   system=[{"text"}],
                                    |   inferenceConfig={"maxTokens","temperature"})
回應 embedding（1024 float）        | 回應 output.message.content[0].text
     inputTextTokenCount            |      stopReason / usage.inputTokens
------------------------------------+--------------------------------------------
X 不可把 maxTokens、temperature、topP 放進 Titan body；X 不可同時調 temperature 與 topP
```

官方說明 Titan Text Embeddings V1／V2「do not support inference parameters such as `maxTokenCount` or `topP`」，所以兩條路徑各自組 body，不共用參數 dict。`converse` 的生成參數固定放 `inferenceConfig`；模型專屬參數（例如 `top_k`）才走 `additionalModelRequestFields`，本案不使用。

### 6.2 候選挑選與 Region／配額／權限

`list_foundation_models(byOutputModality="EMBEDDING")` 與 `byOutputModality="TEXT"` 各取一次，回傳的 `modelSummaries` 逐筆看 `modelId`、`providerName`、`inferenceTypesSupported`（需含 `ON_DEMAND`）與 `modelLifecycle.status`。只列在清單裡不代表帳號有 access，所以還要真的送 request。部分 Claude 模型在某些 Region 只能透過跨區推論 profile 呼叫，`ListFoundationModels` 不會列出 profile；候選不足時改用 `list_inference_profiles()` 取 profile ID，再做同樣的 probe。**沒有實測成功的 ID 一律不寫進報告的 `.env` 區塊。**

錯誤代碼與狀態的固定對照，讓「沒權限」不會被誤讀成「模型不存在」：

| `Error.Code` | HTTP | `ProbeStatus` | 意思 |
|---|---|---|---|
| `AccessDeniedException` | 403 | `blocked` | 帳號未開通 model access 或 IAM 不足。 |
| `ResourceNotFoundException` | 404 | `unavailable` | 這個 Region 沒有這個 model 或 profile。 |
| `ValidationException` | 400 | `param_unsupported` | 參數組合不被該模型接受。 |
| `ThrottlingException` | 429 | `quota` | 帳號配額被節流。 |
| `ServiceQuotaExceededException` | 400 | `quota` | 超出服務配額（官方文件標 400，不是 429）。 |
| `ModelNotReadyException`／`ModelTimeoutException`／`ServiceUnavailableException` | 429／408／503 | `retry_later` | 暫時性，可重跑一次。其他代碼一律 `unknown`，原始代碼寫進 `detail`，gate 不通過。 |

### 6.3 費用與證據

每次 probe 都是計費請求：Titan 用 `inputTextTokenCount`、`converse` 用 `usage.inputTokens`／`outputTokens` 記錄實際 token。報告固定記 Region、帳號別名、model ID、參數、token 數與時間，供 [Phase 54](./54-Phase54-重開票與呼叫規則指標.md) 核對呼叫數基準。Free Tier 與 credits 取決於帳號方案與建立時間，報告不得寫「免費」或固定金額；`.env` 片段只印到 stdout。`detail` 只放錯誤代碼與 SDK 的錯誤訊息，不貼完整 request／response、憑證或 ARN。

## 7. TDD Tasks

### Task 1：候選清單與錯誤分類

- [x] **Step 1：建立失敗測試**

```python
def test_candidates_keep_on_demand_active_models_only(fake_bedrock):
    live = {"inferenceTypesSupported": ["ON_DEMAND"], "modelLifecycle": {"status": "ACTIVE"}}
    other = {"inferenceTypesSupported": ["PROVISIONED"], "modelLifecycle": {"status": "ACTIVE"}}
    fake_bedrock.summaries = [
        {"modelId": "amazon.titan-embed-text-v2:0", **live},
        {"modelId": "vendor.legacy", **other},
    ]
    assert list_candidates(fake_bedrock, output_modality="EMBEDDING") == (
        "amazon.titan-embed-text-v2:0",)
    assert classify_error(client_error("AccessDeniedException")) == "blocked"
    assert classify_error(client_error("SomethingNew")) == "unknown"
```

- [x] **Step 2：執行並確認紅燈**

```bash
uv run pytest tests/unit/test_check_models.py -q -k candidates
```

預期：FAIL，訊號包含 `cannot import name 'list_candidates'`。

- [x] **Step 3：建立最小實作**

```python
# 設計 §14.3：連線 2 秒、讀取 30 秒；total_max_attempts=1 代表 SDK 完全不重試
SDK_CONFIG = Config(connect_timeout=2, read_timeout=30, retries={"total_max_attempts": 1})

ERROR_STATUS = {
    "AccessDeniedException": "blocked", "ResourceNotFoundException": "unavailable",
    "ValidationException": "param_unsupported", "ThrottlingException": "quota",
    "ServiceQuotaExceededException": "quota", "ModelNotReadyException": "retry_later",
    "ModelTimeoutException": "retry_later", "ServiceUnavailableException": "retry_later",
}

def classify_error(error: Exception) -> ProbeStatus:
    response = getattr(error, "response", None)
    code = response.get("Error", {}).get("Code", "") if isinstance(response, dict) else ""
    return ERROR_STATUS.get(code, "unknown")

def list_candidates(bedrock: object, *, output_modality: str) -> tuple[str, ...]:
    rows = bedrock.list_foundation_models(byOutputModality=output_modality)["modelSummaries"]
    return tuple(
        row["modelId"] for row in rows
        if "ON_DEMAND" in row.get("inferenceTypesSupported", ())
        and row.get("modelLifecycle", {}).get("status") == "ACTIVE"
    )
```

- [x] **Step 4：補 inference profile 後援並跑完整檔案確認綠燈**

候選為空時改呼叫 `bedrock.list_inference_profiles()`，從 `inferenceProfileSummaries` 逐筆取 `inferenceProfileId` 當候選；兩邊都空就直接回 `unavailable`，不填任何猜測 ID。兩個 client 都用 `SDK_CONFIG` 建立。

**實測補充（2026-09-14，us-east-1）：** `ListFoundationModels(byOutputModality="TEXT")` 的 ON_DEMAND 清單**不為空**（Nova、Llama 等），但**所有 Claude 的 `inferenceTypesSupported` 只有 `INFERENCE_PROFILE`**，所以「候選為空才查 profile」這條規則永遠不會觸發，Claude 也就永遠選不到。因此 `list_candidates` 維持原樣（只在清單為空時 fallback），另外由 `rank_candidates(candidates, *, preferred)` 與 `resolve_candidates(bedrock, *, output_modality, preferred)` 負責挑選：先用 `PREFERRED_*` 前綴過濾 ON_DEMAND 清單，濾不到才查 `list_profile_candidates()`。`PREFERRED_GENERATION` 依成本由低到高排 `anthropic.claude-haiku-4-5`、`us.anthropic.claude-haiku-4-5`、`anthropic.claude-sonnet-4-5`、`us.anthropic.claude-sonnet-4-5`，刻意不收 `global.` 前綴，也刻意不對目錄裡其他廠牌的模型送 request（每個 probe 都計費）。

```bash
uv run pytest tests/unit/test_check_models.py -q
```

- [x] **Step 5：提交**

```bash
git add infra/scripts/check_models.py tests/unit/test_check_models.py
git commit -m "feat(infra): 列出可用模型候選"
```

### Task 2：Titan probe 只帶 embedding 參數

- [x] **Step 1：建立失敗測試**

```python
TITAN, REGION = "amazon.titan-embed-text-v2:0", "ap-northeast-1"

def titan_reply(size: int) -> dict:
    """模擬 boto3 的回應形狀：body 是可 read() 的串流，不是已解析的 dict。"""
    payload = {"embedding": [0.1] * size, "inputTextTokenCount": 8}
    return {"body": io.BytesIO(json.dumps(payload).encode("utf-8"))}

def test_titan_body_is_pure_and_dimension_is_checked(fake_runtime):
    fake_runtime.invoke_response = titan_reply(1024)
    good = probe_embedding(fake_runtime, TITAN, region=REGION)
    body = json.loads(fake_runtime.last_kwargs["body"])
    assert set(body) == {"inputText", "dimensions", "normalize"}
    assert (body["dimensions"], good.status, good.tokens) == (1024, "ok", 8)

    fake_runtime.invoke_response = titan_reply(512)
    wrong = probe_embedding(fake_runtime, TITAN, region=REGION)
    assert (wrong.status, "512" in wrong.detail) == ("param_unsupported", True)
```

- [x] **Step 2：執行並確認紅燈**

```bash
uv run pytest tests/unit/test_check_models.py -q -k titan
```

預期：FAIL，訊號包含 `cannot import name 'probe_embedding'`。

- [x] **Step 3：建立最小實作**（`invoke_model` 的回應 `body` 是 `StreamingBody`，一定要先 `read()` 再 `json.loads`；回應可能同時帶 `embeddingsByType`，本 probe 只讀 `embedding`）

```python
def probe_embedding(runtime: object, model_id: str, *, region: str) -> ModelProbe:
    body = json.dumps({"inputText": "ping", "dimensions": 1024, "normalize": True})
    try:
        raw = runtime.invoke_model(modelId=model_id, body=body, contentType="application/json")
        payload = json.loads(raw["body"].read())
    except Exception as error:
        # 依 §6.3：detail 只放錯誤代碼與 SDK 訊息，不貼 repr(error) 可能帶進來的 ARN。
        detail = error_detail(error)
        return ModelProbe("embedding", model_id, region, classify_error(error), detail, None)
    size, tokens = len(payload.get("embedding") or []), payload.get("inputTextTokenCount")
    if size != 1024:
        detail = f"回應維度為 {size}，不是 1024"
        return ModelProbe("embedding", model_id, region, "param_unsupported", detail, tokens)
    if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in payload["embedding"]):
        detail = "回應含非有限數值（NaN／Infinity）"
        return ModelProbe("embedding", model_id, region, "param_unsupported", detail, tokens)
    return ModelProbe("embedding", model_id, region, "ok", f"1024 維、{tokens} tokens", tokens)
```

- [x] **Step 4：對真實帳號跑一次最小呼叫確認綠燈**

回應必須是 1024 個有限數值（沒有 `NaN`／`Infinity`）；`AccessDeniedException` 保持 `blocked`，不改用預填向量頂替。

```bash
TKB_RUN_AWS_INTEGRATION=1 uv run pytest tests/integration/test_o5_probe.py -q -m aws -k embedding
```

- [x] **Step 5：提交**

```bash
git add infra/scripts/check_models.py tests/unit/test_check_models.py tests/integration/test_o5_probe.py
git commit -m "feat(infra): 實測 Titan 維度與參數"
```

### Task 3：Claude probe、`.env` 片段與 BLOCKED 報告

- [x] **Step 1：建立失敗測試**

```python
def test_generation_config_is_fixed_and_blocked_never_emits_env(fake_runtime):
    fake_runtime.converse_response = {
        "output": {"message": {"content": [{"text": "ok"}], "role": "assistant"}},
        "stopReason": "end_turn", "usage": {"inputTokens": 12, "outputTokens": 2},
    }
    good = probe_generation(fake_runtime, "candidate-id", region=REGION)
    assert set(fake_runtime.last_kwargs["inferenceConfig"]) == {"maxTokens", "temperature"}
    assert fake_runtime.last_kwargs["inferenceConfig"]["temperature"] == 0.1
    assert good.status == "ok"

    fake_runtime.error = client_error("AccessDeniedException")
    blocked = probe_generation(fake_runtime, "candidate-id", region=REGION)
    assert blocked.status == "blocked"
    assert "TKB_GENERATION_MODEL_ID" not in render_env([blocked])
    assert "BLOCKED" in render_o5_report([blocked], run_id="r1")
```

- [x] **Step 2：執行並確認紅燈**

```bash
uv run pytest tests/unit/test_check_models.py -q -k generation
```

預期：FAIL，訊號包含 `cannot import name 'probe_generation'`。

- [x] **Step 3：建立最小實作**（`render_env` 只輸出實測通過的鍵；鍵名依 00A 第 3.5 節，不可自創縮寫）

```python
ENV_KEY = {"embedding": "TKB_EMBEDDING_MODEL_ID", "generation": "TKB_GENERATION_MODEL_ID"}

def probe_generation(runtime: object, model_id: str, *, region: str) -> ModelProbe:
    try:
        reply = runtime.converse(
            modelId=model_id,
            messages=[{"role": "user", "content": [{"text": "ping"}]}],
            system=[{"text": "reply with ok"}],
            inferenceConfig={"maxTokens": 16, "temperature": 0.1},
        )
    except Exception as error:
        detail = error_detail(error)  # 同 §6.3
        return ModelProbe("generation", model_id, region, classify_error(error), detail, None)
    tokens = reply.get("usage", {}).get("inputTokens")
    detail = f"stopReason={reply.get('stopReason')}、{tokens} tokens"
    return ModelProbe("generation", model_id, region, "ok", detail, tokens)

def render_env(probes: Sequence[ModelProbe]) -> str:
    lines = [f"TKB_BEDROCK_REGION={probes[0].region}"] if probes else []
    lines += [f"{ENV_KEY[p.purpose]}={p.model_id}" for p in probes if p.status == "ok"]
    return "\n".join(lines) + "\n"

def render_o5_report(probes: Sequence[ModelProbe], *, run_id: str) -> str:
    verdict = "PASS" if probes and all(p.status == "ok" for p in probes) else "BLOCKED"
    rows = [f"| {p.purpose} | {p.model_id} | {p.region} | {p.status} | {p.detail} |" for p in probes]
    head = [f"# O5 模型可用性報告 {run_id}：{verdict}", "", "| purpose | model | region | status | detail |", "|---|---|---|---|---|"]
    return "\n".join(head + rows) + "\n"
```

- [x] **Step 4：補 `main` 並對真實帳號跑一次最小呼叫確認綠燈**

`main(argv)` 依序做：解析 `--region` → 用 `SDK_CONFIG` 建兩個 client → `resolve_candidates` → 兩個 probe → 把 `render_o5_report(...)` 寫進 `docs/plan/report/o5-<run-id>.md` → 把 `render_env(...)` 印到 stdout → 全部 `ok` 回 `0`，任一非 `ok` 回 `2`。報告固定記 Region、帳號別名、model、參數與 token 數；非 `ok` 時標題是 `BLOCKED` 並列出原始錯誤代碼。

`main` 另收兩個選用旗標（都不影響上面的行為，只是讓報告可重現與可測試）：`--run-id`（預設 UTC 時間戳）與 `--report-dir`（預設 `docs/plan/report/`）。`render_o5_report` 的簽名不動，Region／帳號別名／參數／token 數／候選嘗試明細與 BLOCKED 停止語句由 `render_run_context(...)` 產生後接在報告後面；stdout 表格由 `render_table(...)` 依第 2 節的欄寬輸出。

```bash
TKB_RUN_AWS_INTEGRATION=1 uv run pytest tests/integration/test_o5_probe.py -q -m aws
```

- [x] **Step 5：提交**

```bash
git add infra/scripts/check_models.py .env.example tests/unit/test_check_models.py tests/integration/test_o5_probe.py
git commit -m "feat(infra): 實測 Claude 呼叫並輸出模型設定"
```

## 8. 驗收矩陣

| 路徑 | 輸入 | 預期資料結果 |
|---|---|---|
| Happy | 兩個 probe 都回應 | 兩筆 `status=ok`，`.env` 片段三行（`TKB_BEDROCK_REGION`／`TKB_EMBEDDING_MODEL_ID`／`TKB_GENERATION_MODEL_ID`），exit code 0。 |
| Failure | `AccessDeniedException` | `status=blocked`，報告標題含 `BLOCKED`，不印 `TKB_GENERATION_MODEL_ID`，exit code 2。 |
| Failure | Titan 回 512 維 | `status=param_unsupported`，detail 含實際維度；Phase 16 保持 blocked。 |
| Boundary | 候選清單為空；Titan body 被塞入 `maxTokens` | 前者改查 inference profile，兩邊都空回 `unavailable` 不填猜測 ID；後者單元測試失敗並列出多出的鍵。 |

人工驗收：打開 `docs/plan/report/o5-<run-id>.md`，確認 Region、model ID、參數與 token 數都是本次實測值；再用 AWS Console 的 Bedrock model access 頁面對照一次。把報告的 `.env` 片段貼進本機 `.env` 前，先執行 `git check-ignore .env` 確認會被忽略。

## 9. 常見錯誤與停止條件

| 症狀 | 原因 | 修正／停止 |
|---|---|---|
| Titan 回 `ValidationException` | 生成參數混進 embedding body | 兩條路徑各自組 body；仍失敗就停止 Phase 16。 |
| 清單有模型但呼叫 403 | 把 `ListFoundationModels` 當成有 access | 以實際 request 為準，狀態記 `blocked`；沒有實測就不寫進 `.env` 區塊。 |
| 找不到 Claude 就填像樣的 ID；同時調 `temperature` 與 `topP` | 想讓後續 Phase 先動；沿用他處預設 | 停止；沒有實測就是 blocked 不填猜測值，且只設 `temperature`。 |
| 報告寫「免費」或固定金額；`.env` 連同真實值提交 | 引用未驗證的成本保證；未確認 git 忽略 | 只記 token 數與時間；先確認忽略再建立檔案，`.env.example` 只放鍵名。 |
| 把 `invoke_model` 回應當成已解析的 dict，`embedding` 永遠是空的 | 忘了回應的 `body` 是 `StreamingBody` | 一律 `json.loads(raw["body"].read())`；測試 double 也要回同一種形狀，否則單元測試綠燈但實機是 `param_unsupported`。 |
| `.env` 片段把鍵名縮寫（例如把 `GENERATION` 縮成三個字母） | 自創縮寫，`load_settings` 讀不到 | 鍵名固定 `TKB_GENERATION_MODEL_ID`／`TKB_EMBEDDING_MODEL_ID`／`TKB_BEDROCK_REGION`（00A 第 3.5 節）。 |

## 10. 來源與 Rule 對照

本 Phase 交付的是**帳號 probe 證據**，不是產品呼叫路徑；下列三條的 primary 依 [00B 需求覆蓋對照](00B-需求覆蓋對照.md) 第 3.2 節都在 [Phase 18](./18-Phase18-模型輸出業務驗證與有限重試.md)，本文件的斷言保留但只算「相關」。

- [執行教學流程.feature](../../spec/features/執行教學流程.feature)
  - Rule 4：「每個 Bedrock 呼叫設定 max_tokens」與 Rule 5：「每個 Bedrock 呼叫設定逾時」→ 相關（O5 probe 證據）：Task 3 斷言 `inferenceConfig` 鍵集合精確為 `{maxTokens, temperature}`（embedding 路徑依 §14.3 不適用），逾時由 Task 1 的 `SDK_CONFIG` 設定並記入報告。
  - Rule 9：「判斷節點使用低 temperature」→ 相關（O5 probe 證據）：Task 3 斷言 `temperature == 0.1` 且未出現 `topP`。
- 設計 §14.3、§17.1、§17.3、§18 O5：Titan 是 embedding API 不使用生成參數且固定 `amazon.titan-embed-text-v2:0` 與 1024 維；Claude 只設 temperature，model ID／inference profile 須由帳號確認，不填猜測值；Free Tier 不保證。
- [Titan Embeddings 模型](https://docs.aws.amazon.com/bedrock/latest/userguide/titan-embedding-models.html)：V2 輸出 1024／512／256 維，不支援 `maxTokenCount`、`topP`；請求欄位為 `inputText`、`dimensions`、`normalize`，回應含 `embedding` 與 `inputTextTokenCount`。
- [Converse API](https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_Converse.html)：`inferenceConfig` 含 `maxTokens`、`temperature`、`topP`、`stopSequences`；需要 `bedrock:InvokeModel` 權限；錯誤含 `AccessDeniedException`、`ValidationException`、`ThrottlingException`。
- [ListFoundationModels](https://docs.aws.amazon.com/bedrock/latest/APIReference/API_ListFoundationModels.html)：可用 `byOutputModality` 篩選，回傳 `modelSummaries` 的 `inferenceTypesSupported` 與 `modelLifecycle`。
- [InvokeModel](https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_InvokeModel.html)：回應的 `body` 是 HTTP body（boto3 給 `StreamingBody`）；錯誤 HTTP 碼 `AccessDenied` 403、`ResourceNotFound` 404、`Validation` 400、`ServiceQuotaExceeded` **400**、`Throttling` 429、`ModelNotReady` 429、`ModelTimeout` 408、`ServiceUnavailable` 503。
- [botocore Config](https://docs.aws.amazon.com/botocore/latest/reference/config.html)：`retries` 只接受 `total_max_attempts`／`max_attempts`／`mode`；`total_max_attempts` 是**總嘗試次數**，設 1 就是不重試。

## 11. 完成清單

- [x] `check_models.py` 的函式名稱與簽名符合本文件，exit code 規則已實作。
- [x] Titan request body 的鍵集合精確為 `{inputText, dimensions, normalize}`；Claude 只設 `temperature`，沒有同時調 `topP`。
- [x] 各錯誤代碼對應到固定 `ProbeStatus`，未知代碼記 `unknown` 並保留原始代碼。
- [x] `.env` 片段與 `.env.example` 的鍵名逐字等於 `TKB_BEDROCK_REGION`／`TKB_EMBEDDING_MODEL_ID`／`TKB_GENERATION_MODEL_ID`。
- [x] 兩個 probe 都對真實帳號執行，報告記錄 Region、model、參數與 token 數。
- [x] 任一 probe 非 `ok` 時輸出 BLOCKED 報告且不印 model ID，Phase 15–18 標為 blocked。
- [x] 報告與文件沒有承諾免費、固定成本或「一定可用」；`.env` 片段只印到 stdout，確認 git 忽略前未建立含真實值的檔案。

## 12. O5 gate 結果（2026-09-14）

**判定：BLOCKED。** `uv run python infra/scripts/check_models.py --region us-east-1` exit code = 2。

| 項目 | 值 |
|---|---|
| Region | `us-east-1`（`ap-northeast-1` 也試過，同樣被拒） |
| 帳號 | 123456789012（無帳號別名），IAM user `tkb-deploy-admin` |
| 執行時間（UTC） | 2026-09-14T17:00:50Z |
| embedding 候選／結果 | `amazon.titan-embed-text-v2:0` → `param_unsupported`／`ValidationException: Operation not allowed` |
| generation 候選／結果 | `us.anthropic.claude-haiku-4-5-20251001-v1:0`、`us.anthropic.claude-sonnet-4-5-20250929-v1:0` → 兩者皆 `param_unsupported`／同一錯誤 |
| token 數 | 無（請求在服務端被拒，沒有 `inputTextTokenCount`／`usage`） |
| `TKB_BEDROCK_REGION` | `us-east-1`（唯一印出的一行） |
| `TKB_EMBEDDING_MODEL_ID` | **未輸出**（沒有實測通過） |
| `TKB_GENERATION_MODEL_ID` | **未輸出**（沒有實測通過） |

成因：`bedrock:GetUseCaseForModelAccess` 回 `ResourceNotFoundException: You have not filled out the
request form. Fill out the form before getting access.`——帳號從未送出 Bedrock model access 表單，
所以沒有任何模型被授權。control plane（`ListFoundationModels`／`ListInferenceProfiles`）與
STS／S3 都正常，確認不是 IAM、Region 或參數問題。完整佐證見
[`docs/plan/report/o5-20260914T170050Z.md`](../report/o5-20260914T170050Z.md)。

停止語句（逐字，依 00A §4.2）：

> O5 未通過，本階段標 BLOCKED；`TKB_GENERATION_MODEL_ID` 保持 `<實測通過的 ID>` 佔位，不填猜測值。

Phase 15、16、17、18 保持 blocked。解除方式：人在 AWS Console 的 Bedrock → Model access 填寫使用情境
表單並取得 Titan Text Embeddings V2 與 Claude Haiku 4.5（或 Sonnet 4.5）的存取後，重跑
`uv run python infra/scripts/check_models.py --region us-east-1`，exit code 變成 0 才算 PASS。
