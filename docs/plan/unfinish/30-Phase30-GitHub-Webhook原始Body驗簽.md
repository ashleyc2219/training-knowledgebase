# Phase 30：GitHub Webhook 原始 Body 驗簽實作計畫

> **給 agentic worker：** 必須使用 `superpowers:subagent-driven-development`（建議）或 `superpowers:executing-plans` 逐項實作。

**目標：** 在解析 JSON 之前，以原始 request bytes 驗證 `X-Hub-Signature-256`，並讓公開 webhook 的整體處理在八秒內明確成功或失敗。

**架構：** Function URL handler 先還原原始 bytes，再呼叫純函式 `verify_github_signature`。驗簽成功後才交 Phase 31 正規化與 Phase 32 接受；任一步失敗都回操作失敗，不能先回成功再背景正規化。

**技術：** Python `hmac`／`hashlib`／`base64`、pytest、Lambda Function URL；secret 只由執行環境提供。

## 1. 文件定位

- **讀者：** 會 Python 與 pytest、但沒寫過 webhook 驗簽的工程師。
- **主來源：** [設計 §7.1、§14.1、§14.3、§17.1、§17.2、§20.7](../../design/training-kb.md)。名稱與簽名以 [00A 共用契約與名詞](00A-共用契約與名詞.md) 第 6.8 節為準；兩邊不一致時改本文件，不改 00A。
- **前置：** [Phase 02 設定時間與錯誤契約](02-Phase02-設定時間與錯誤契約.md) 的 `IngressError`、[Phase 13 O6 來源 ID 與穩定使用者契約](13-Phase13-O6來源ID與穩定使用者契約.md) 已核對的 GitHub fixture 與 ID mapping。前置未通過時停止。
- **前一份：** [Phase 29 共用 Pipeline 執行器與 ASL 失敗語意](29-Phase29-共用Pipeline執行器與ASL失敗語意.md)。**下一份：** [Phase 31 Ticket 與 Release 正規化](31-Phase31-Ticket與Release正規化.md)，接著 [Phase 32 事件接受去重與流程啟動](32-Phase32-事件接受去重與流程啟動.md)、[Phase 33 Rote 結構簽名與 STABLE_KEYS](33-Phase33-Rote結構簽名與STABLE_KEYS.md)。
- **本階段不做：** 不讓 Function URL 使用者取得 secret；不解析或保存 Ticket／Release（那是 Phase 31、32）；不開放非 GitHub 的公開入口（手動來源走已登入 AWS 的受控匯入）；不承諾 GitHub 會替超時 delivery 自動重送；不建立 Lambda 或 Function URL 資源（CDK 由 [Phase 41](41-Phase41-Ticket-Analysis雲端流程驗收.md) 建立 `training-kb-webhook`）。
- **與本 Phase 有關的 gate：** O6（來源完整契約）只核定了 `("github.com", "issues")` 的 `action, issue, repository, sender` 四個 key，其餘來源仍是 blocked。本 Phase 不得自己發明 payload 欄位對應或 ID 規則；沒有實際 Function URL 與 GitHub delivery 之前，只能宣稱「本機測試通過」。
- 以下程式檔均是實作時預計建立或修改；本計畫本身不代表它們已存在。

`body` 必須指 Lambda 收到的原始 bytes。重新 `json.dumps()` 會改變空白與鍵順序，算出來的 HMAC 一定對不上，不能拿來驗簽。

## 2. 你在整體流程的位置

```text
GitHub HTTP request
  | raw bytes + X-Hub-Signature-256
  v
[你在這裡] HMAC-SHA256 + hmac.compare_digest
  | 合法                              | 不合法／逾時
  v                                   v
Phase 31 正規化 -> Phase 32 接受      IngressError；零業務寫入、零 StartExecution
```

## 3. 可觀察成果

用固定 secret 與 `tests/fixtures/github/issue-opened.json` 的 bytes 算出的合法簽名，`verify_github_signature(...)` 回 `None`。把 body 多加一個空白但沿用舊簽名，立刻得到 `IngressError`，`error.fields == ("X-Hub-Signature-256",)`，而且 JSON parser spy 的呼叫次數是 0、接受路徑 spy 的呼叫次數也是 0。

## 4. 名詞小抄

| 名詞 | 白話意思 |
|---|---|
| HMAC-SHA256 | 用共享密鑰和內容算出的一段固定長度雜湊，內容或密鑰不同就對不上。 |
| `X-Hub-Signature-256` | GitHub 放簽名的 header，值的形狀是 `sha256=<64 個十六進位字元>`。 |
| raw body（原始 bytes） | HTTP 請求正文一個 byte 都沒改過的樣子；驗簽只能用它。 |
| 固定時間比較 | 用 `hmac.compare_digest` 比對，不會因為前幾個字元就先回答不同，避免被逐字元試出簽名。 |
| Function URL | Lambda 自帶的 HTTPS 入口；auth 設 `NONE` 只代表不做 IAM 驗證，仍需 resource policy，也**不等於**可信來源。 |
| deadline（整體期限） | 從進入 handler 起算的八秒；驗簽、解析、正規化、接受都要在這段時間內結束。 |
| delivery ID | GitHub 每次送出事件的識別碼（`X-GitHub-Delivery`），可安全寫進 log 用來追查。 |
| adapter（接入器名稱） | 一種來源事件對應的固定處理方式的名字，由 `X-GitHub-Event` 決定：`issues` 對 `github_issue`、`pull_request` 對 `github_pr`。翻成 adapter 名稱不等於這個來源已核定，核定與否看 Phase 13 的 `SourceApproval`。 |

## 5. 預計檔案

| 動作 | 路徑 | 責任 |
|---|---|---|
| 新增 | `src/training_kb/ingress.py` | `SIGNATURE_HEADER`、`verify_github_signature`，以及 `normalize_then_accept` 的接線點。 |
| 新增 | `src/training_kb/handlers/__init__.py`、`handlers/github_webhook.py` | 還原 bytes、header 查找、八秒 deadline、回應形狀。 |
| 新增 | `tests/unit/test_github_signature.py` | 格式、原始 bytes、固定時間比較與 secret 設定錯誤。 |
| 新增 | `tests/integration/test_github_webhook_handler.py` | 驗簽先於 JSON parse、base64 body、header 大小寫、八秒邊界。 |
| 消費 | `src/training_kb/pipelines/common.py` | 只 import `JSONValue`（Phase 29 的唯一定義，裁決 D-31）當 `payload` 的型別；不另寫一份 JSON 型別。 |
| 消費 | `tests/fixtures/github/issue-opened.json`、`pull-request-merged.json` | 由 Phase 13 維護者核對過的 fixture；不得臨時猜 mapping 或自己造 payload。 |

## 6. 固定介面

### Consumes

```text
IngressError(message: str, fields: tuple[str, ...])                      # Phase 02；fields 是 tuple，不是 list
PermanentError                                                           # Phase 02
JSONValue                                                                # Phase 29；pipelines/common.py 的唯一定義（D-31）
validate_ticket(payload: Mapping[str, object]) -> Ticket                 # Phase 31
validate_release(payload: Mapping[str, object]) -> Release               # Phase 31
accept_ticket(ticket: Ticket, *, deadline: float) -> Acceptance          # Phase 32
accept_release(release: Release, *, deadline: float) -> Acceptance       # Phase 32
tests/fixtures/github/issue-opened.json、pull-request-merged.json        # Phase 13
```

### Produces

```python
# src/training_kb/ingress.py
SIGNATURE_HEADER = "X-Hub-Signature-256"
def verify_github_signature(raw_body: bytes, signature_header: str | None, secret: bytes) -> None: ...
def normalize_then_accept(*, domain: str, adapter: str, event_type: str,
                          headers: Mapping[str, str], payload: Mapping[str, JSONValue],
                          deadline: float) -> Acceptance: ...
def time_left(deadline: float) -> float: ...
def assert_time_left(deadline: float, *, step: str) -> None: ...

# src/training_kb/handlers/github_webhook.py
WEBHOOK_DEADLINE_SECONDS = 8.0
def load_secret() -> bytes: ...
def decode_body(event: dict) -> bytes: ...
def parse_json(raw: bytes) -> dict: ...
def handler(event: dict, context: object) -> dict[str, object]: ...
```

- **實作補記（P30 完成時）：** `mypy --strict` 的 `disallow_any_generics` 不接受沒有參數的
  `dict`，所以三個吃／回 `dict` 的函式在程式裡逐字寫成 `dict[str, Any]`（`event: dict[str, Any]`、
  `decode_body(event: dict[str, Any]) -> bytes`、`parse_json(raw: bytes) -> dict[str, Any]`）。
  執行期形狀與 00A 第 6.8 節完全相同，只是補上型別參數；`handler` 的回傳仍是 `dict[str, object]`。

- `verify_github_signature` 合法時回 `None`，不合法時丟 `IngressError`，`fields` 固定是 `("X-Hub-Signature-256",)`。secret 沒設定是**環境設定錯誤**，丟 `PermanentError`，不能報成使用者輸入錯誤；secret 由環境變數 `TKB_GITHUB_WEBHOOK_SECRET` 提供（00A 第 3.5 節的執行期開關：有 `TKB_` 前綴，但不是 `Settings` 欄位，`load_settings` 不讀它；Phase 60 的 `check_secrets` 核對表也列它）。
- **八秒是整個 handler 的 deadline**，驗簽本身不擁有新的八秒。`handler` 進入時算出 `deadline`，之後一路往下傳；Phase 31、32 每一步開始前用 `assert_time_left(deadline, step=...)` 檢查剩餘時間，不各自重新計八秒。
- `normalize_then_accept` 是本 Phase 先固定下來的**接線點**（呼叫位置與參數），實際內容由 Phase 31（`validate_ticket`／`validate_release`）與 Phase 32（`accept_ticket`／`accept_release`）填上。簽名依 00A 第 8 節 D-60 固定為**六個 keyword-only 參數**：`domain`、`adapter`、`event_type`、全部小寫化的 `headers`、已解析的 `payload`、`deadline`；`payload` 的型別逐字是 `Mapping[str, JSONValue]`（`JSONValue` 就是「任何合法的 JSON 值」這個型別別名，由 [Phase 29](29-Phase29-共用Pipeline執行器與ASL失敗語意.md) 的 `pipelines/common.py` 定義，全套只有那一份，裁決 D-31），不要退化成 `Mapping[str, object]`；handler 把 `domain="github.com"`、由 `X-GitHub-Event` 對應出的 `adapter`、原樣的 `event_type` 一起傳下去，讓 [Phase 37](37-Phase37-Rote-Agent回退與成功提交.md) 組得出 `RawEvent`，不必從 payload 反推來源。本 Phase 只放一個明確丟 `PermanentError("Phase 31／32 尚未接線")` 的版本，整合測試用 monkeypatch 換成 spy；**不得**用「先回成功、之後再處理」代替。
- 回應形狀固定為 `{"ok": bool, "operation_id": str | None}`，失敗時另有 `message` 與 `fields`。這裡不新增 HTTP 錯誤碼契約（設計 §7.1）。

## 7. 設計細節

handler 的固定次序與失敗出口如下；任何一步往前挪動都會破壞 Rule 1 與 Rule 2：

```text
Function URL（auth=NONE，仍需 resource policy；NONE 不等於可信來源）
        |
        v
  decode_body(event)   isBase64Encoded=true -> 嚴格 base64；false -> UTF-8 編碼一次，不做 JSON round-trip
        |
        v
  verify_github_signature(raw, header, secret)   <-- 這一步之前不得出現任何 json.loads
        |  合法                                   | 不合法
        v                                         v
  parse_json(raw)                            {"ok": false, "fields": ["X-Hub-Signature-256"]}
        |                                         |
        v                                         +--> parser 0 次、Repository 0 次、StartExecution 0 次
  normalize_then_accept(domain="github.com", adapter=..., event_type=..., headers=...,
                        payload=..., deadline = 進入時間 + 8.0)
        |  八秒內完成            | 超過八秒
        v                        v
  {"ok": true, ...}         {"ok": false, "operation_id": null}
```

為什麼是這個順序：設計 §7.1 要求「先驗證，再承認處理成功」，§14.1 要求「webhook 無簽名、簽名不符時，Ingress 直接拒絕，不能先進 Rote 或寫合法 Ticket／Release」。八秒來自設計 §14.3：GitHub 超過十秒可能把 delivery 記為失敗，而且**不會自動重送**，所以公開入口要在八秒內給出明確結果；需要重送時由維護者用 GitHub 既有的 redeliver 功能，不是靠我們自己排隊。

## 8. Task 1：原始 bytes 驗簽

- [x] **Step 1：建立失敗測試**

```python
# tests/unit/test_github_signature.py
import hashlib
import hmac
import pytest
from training_kb.errors import IngressError, PermanentError
from training_kb.ingress import verify_github_signature

SECRET = b"test-secret"

def sign(body: bytes, secret: bytes = SECRET) -> str:
    return "sha256=" + hmac.new(secret, body, hashlib.sha256).hexdigest()

def test_rejects_changed_raw_bytes() -> None:
    body = b'{"action":"opened"}'
    header = sign(body)
    assert verify_github_signature(body, header, SECRET) is None      # 合法時回 None
    with pytest.raises(IngressError) as error:
        verify_github_signature(body + b" ", header, SECRET)           # 只多一個空白
    assert error.value.fields == ("X-Hub-Signature-256",)

def test_missing_secret_is_a_configuration_error() -> None:
    with pytest.raises(PermanentError):
        verify_github_signature(b"{}", sign(b"{}"), b"")
```

- [x] **Step 2：執行並確認紅燈**

```bash
uv run pytest tests/unit/test_github_signature.py -q
```

預期：FAIL，訊號包含 `cannot import name 'verify_github_signature'`。不要先建立空殼函式讓測試假綠。

- [x] **Step 3：建立最小實作**

```python
# src/training_kb/ingress.py
import hashlib
import hmac
import string
from training_kb.errors import IngressError, PermanentError

SIGNATURE_HEADER = "X-Hub-Signature-256"
SIGNATURE_PREFIX = "sha256="
HEX_DIGEST_LENGTH = 64

def verify_github_signature(raw_body: bytes, signature_header: str | None, secret: bytes) -> None:
    if not secret:
        raise PermanentError("webhook secret 未設定")     # 設定錯誤，不是使用者輸入錯誤
    if not signature_header or not signature_header.startswith(SIGNATURE_PREFIX):
        raise IngressError("GitHub 簽名缺少或格式錯誤", (SIGNATURE_HEADER,))
    supplied = signature_header.removeprefix(SIGNATURE_PREFIX).lower()
    if len(supplied) != HEX_DIGEST_LENGTH or any(c not in string.hexdigits for c in supplied):
        raise IngressError("GitHub 簽名格式錯誤", (SIGNATURE_HEADER,))
    expected = hmac.new(secret, raw_body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, supplied):
        raise IngressError("GitHub 簽名不符", (SIGNATURE_HEADER,))
```

先擋掉格式明顯不對的值，可以避免把任意長度字串丟進比較；真正的比對一定用 `hmac.compare_digest`，不可寫成 `expected == supplied`。錯誤訊息只說「不符」，不回報期望值。

- [x] **Step 4：補邊界測試並跑 `uv run pytest tests/unit/test_github_signature.py -q` 確認綠燈**

補六個案例：缺 header（`None`）、prefix 寫成 `sha1=`、非 hex 字元、長度 63 與 65、大寫十六進位的合法簽名（應通過；**大寫的是 digest，prefix 仍是 GitHub 實際送的小寫 `sha256=`**，`SHA256=` 不在契約內）、以及同 body 同 secret 重算兩次結果一致。預期全部 PASS，且每個失敗案例的 `fields` 都是 `("X-Hub-Signature-256",)`。

- [x] **Step 5：提交**

```bash
git add src/training_kb/ingress.py tests/unit/test_github_signature.py
git commit -m "feat(ingress): 驗證GitHub原始Body簽名"
```

## 9. Task 2：確認驗簽發生在 JSON parse 之前

- [x] **Step 1：建立失敗測試**

```python
# tests/integration/test_github_webhook_handler.py
import base64
import hashlib
import hmac
from pathlib import Path
from types import SimpleNamespace
import pytest
from training_kb.handlers import github_webhook

SECRET = b"test-secret"
FIXTURE = Path("tests/fixtures/github/issue-opened.json")

def sign(body: bytes) -> str:
    return "sha256=" + hmac.new(SECRET, body, hashlib.sha256).hexdigest()

def make_event(body: bytes, *, header: str | None, base64_encoded: bool = False,
               event_type: str = "issues") -> dict:
    payload = base64.b64encode(body).decode("ascii") if base64_encoded else body.decode("utf-8")
    headers = {"x-github-event": event_type, "x-github-delivery": "d-001"}
    if header:
        headers["x-hub-signature-256"] = header
    return {"headers": headers, "body": payload, "isBase64Encoded": base64_encoded}

@pytest.fixture
def spies(monkeypatch):
    parsed: list[bytes] = []
    accepted: list[dict] = []
    monkeypatch.setattr(github_webhook, "load_secret", lambda: SECRET)
    monkeypatch.setattr(github_webhook, "parse_json", lambda raw: parsed.append(raw) or {"action": "opened"})
    monkeypatch.setattr(github_webhook, "normalize_then_accept",      # 六個參數都是 keyword
                        lambda **passed: accepted.append(passed)
                        or SimpleNamespace(operation_id="op-ticket-t_881"))
    return parsed, accepted

def test_bad_signature_never_reaches_parser(spies) -> None:
    parsed, accepted = spies
    body = FIXTURE.read_bytes()
    result = github_webhook.handler(make_event(body, header="sha256=" + "0" * 64), None)
    assert result["ok"] is False
    assert result["fields"] == ["X-Hub-Signature-256"]
    assert parsed == [] and accepted == []          # parser 與接受路徑都 0 次

def test_valid_signature_passes_exact_bytes_to_parser(spies) -> None:
    parsed, accepted = spies
    body = FIXTURE.read_bytes()
    result = github_webhook.handler(make_event(body, header=sign(body)), None)
    assert result == {"ok": True, "operation_id": "op-ticket-t_881"}
    assert parsed == [body] and len(accepted) == 1  # 交給 parser 的是原封不動的 bytes
    assert accepted[0]["domain"] == "github.com" and accepted[0]["adapter"] == "github_issue"
    assert accepted[0]["event_type"] == "issues"          # 來自 X-GitHub-Event，不從 payload 猜
    assert accepted[0]["headers"]["x-github-delivery"] == "d-001"   # header 一律小寫鍵
    assert accepted[0]["payload"] == {"action": "opened"}
```

真正的回傳型別是 Phase 10 的 `Acceptance(status, operation_id, record)`；Phase 30 還沒有它的實作，所以測試用 `SimpleNamespace` 代替，只約定 handler 讀得到 `operation_id`。

- [x] **Step 2：執行並確認紅燈**

```bash
uv run pytest tests/integration/test_github_webhook_handler.py -q
```

預期：FAIL，訊號包含 `No module named 'training_kb.handlers'`。

- [x] **Step 3：建立最小實作**

```python
# src/training_kb/handlers/github_webhook.py
import base64
import binascii
import json
import os
from time import monotonic
from training_kb.errors import IngressError, PermanentError
from training_kb.ingress import SIGNATURE_HEADER, normalize_then_accept, verify_github_signature

WEBHOOK_DEADLINE_SECONDS = 8.0

def load_secret() -> bytes:
    secret = os.environ.get("TKB_GITHUB_WEBHOOK_SECRET", "")
    if not secret:
        raise PermanentError("TKB_GITHUB_WEBHOOK_SECRET 未設定")
    return secret.encode("utf-8")

GITHUB_DOMAIN = "github.com"
GITHUB_ADAPTERS = {"issues": "github_issue", "pull_request": "github_pr"}   # 00A D-60

def lower_headers(event: dict) -> dict[str, str]:
    return {str(key).lower(): str(value) for key, value in (event.get("headers") or {}).items()}

def header(event: dict, name: str) -> str | None:
    wanted = name.lower()
    values = [value for key, value in (event.get("headers") or {}).items() if key.lower() == wanted]
    return values[0] if len(values) == 1 else None     # 兩個同名 header 視為沒有有效簽名

def decode_body(event: dict) -> bytes:
    raw = event.get("body") or ""
    if not event.get("isBase64Encoded"):
        return raw.encode("utf-8")
    try:
        return base64.b64decode(raw, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise IngressError("body 不是合法 base64", ("body",)) from exc

def parse_json(raw: bytes) -> dict:
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise IngressError("body 不是合法 JSON", ("body",)) from exc

def handler(event: dict, context: object) -> dict[str, object]:
    deadline = monotonic() + WEBHOOK_DEADLINE_SECONDS
    secret = load_secret()
    try:
        raw = decode_body(event)
        verify_github_signature(raw, header(event, SIGNATURE_HEADER), secret)
        payload = parse_json(raw)
        headers = lower_headers(event)
        event_type = headers.get("x-github-event", "")
        adapter = GITHUB_ADAPTERS.get(event_type)
        if adapter is None:
            raise IngressError("未支援的 GitHub 事件型別", ("X-GitHub-Event",))
        acceptance = normalize_then_accept(domain=GITHUB_DOMAIN, adapter=adapter,
                                           event_type=event_type, headers=headers,
                                           payload=payload, deadline=deadline)
    except IngressError as error:
        return {"ok": False, "message": str(error), "fields": list(error.fields), "operation_id": None}
    except TimeoutError as error:
        return {"ok": False, "message": str(error), "operation_id": None}
    return {"ok": True, "operation_id": acceptance.operation_id}
```

`ingress.py` 同時加上本 Phase 的接線點，Phase 31／32 再換掉函式內容：

```python
# 續寫 src/training_kb/ingress.py
from collections.abc import Mapping
from training_kb.pipelines.common import JSONValue

def normalize_then_accept(*, domain: str, adapter: str, event_type: str,
                          headers: Mapping[str, str], payload: Mapping[str, JSONValue],
                          deadline: float) -> "Acceptance":
    """Phase 31 正規化 + Phase 32 接受的接線點；本 Phase 只固定呼叫位置與六個 keyword 參數（D-60）。"""
    raise PermanentError("Phase 31／32 尚未接線；本 Phase 不得先回成功再背景處理")
```

- [x] **Step 4：補邊界測試並跑 `uv run pytest tests/integration/test_github_webhook_handler.py -q` 確認綠燈**

補五個案例：`isBase64Encoded=true` 的合法 body（decode 後與原檔 bytes 相同）、不合法 base64（`IngressError(fields=["body"])`，且 parser 0 次）、header 名稱寫成 `X-Hub-Signature-256` 與 `x-hub-signature-256` 都找得到、簽名合法但 body 不是合法 JSON（驗簽通過後 parser 明確回 `IngressError(fields=["body"])`，接受路徑 0 次）、`make_event(..., event_type="star")` 這種沒有對應 adapter 的事件（`IngressError(fields=["X-GitHub-Event"])`，接受路徑 0 次）。

- [x] **Step 5：提交**

```bash
git add src/training_kb/handlers tests/integration/test_github_webhook_handler.py
git commit -m "feat(ingress): 驗簽先於JSON解析"
```

## 10. Task 3：鎖定八秒整體期限

- [x] **Step 1：建立失敗測試**

```python
# 續寫 tests/integration/test_github_webhook_handler.py
from training_kb.ingress import assert_time_left

def fake_clock(*ticks: float):
    values = iter(ticks)
    return lambda: next(values)

def test_deadline_boundary_is_exclusive(monkeypatch) -> None:
    monkeypatch.setattr("training_kb.ingress.monotonic", fake_clock(7.999))
    assert_time_left(8.0, step="accept")                       # 7.999 秒還在期限內
    monkeypatch.setattr("training_kb.ingress.monotonic", fake_clock(8.0))
    with pytest.raises(TimeoutError):
        assert_time_left(8.0, step="accept")                   # 8.000 秒到期

def test_timeout_never_returns_success(spies, monkeypatch) -> None:
    parsed, accepted = spies
    monkeypatch.setattr(github_webhook, "monotonic", fake_clock(0.0))
    monkeypatch.setattr("training_kb.ingress.monotonic", fake_clock(8.5))
    def slow_accept(*, deadline, **passed):
        assert_time_left(deadline, step="accept")
        raise AssertionError("超過期限後不應該繼續")
    monkeypatch.setattr(github_webhook, "normalize_then_accept", slow_accept)
    body = FIXTURE.read_bytes()
    result = github_webhook.handler(make_event(body, header=sign(body)), None)
    assert result["ok"] is False and result["operation_id"] is None
    assert "success" not in str(result)
```

- [x] **Step 2：執行並確認紅燈**

```bash
uv run pytest tests/integration/test_github_webhook_handler.py -q -k deadline
```

預期：FAIL，訊號包含 `cannot import name 'assert_time_left'`。

- [x] **Step 3：建立最小實作**

```python
# 續寫 src/training_kb/ingress.py
from time import monotonic

def time_left(deadline: float) -> float:
    """還剩幾秒；小於等於 0 代表整體期限已到。"""
    return deadline - monotonic()

def assert_time_left(deadline: float, *, step: str) -> None:
    if time_left(deadline) <= 0:
        raise TimeoutError(f"{step} 時已超過 webhook 的八秒整體期限")
```

- [x] **Step 4：串好剩餘要求並跑 `uv run pytest tests/integration/test_github_webhook_handler.py -q` 確認綠燈**

同一個 `deadline` 一路傳給 Phase 31、32，兩邊在每一步開始前呼叫 `assert_time_left`，不得各自重新計時。到期時不寫成功回執；若 operation 已經被 Phase 32 接受，重送同一事件會靠 O2 永久去重回到同一個 `operation_id`，**不會建立第二個 operation**（O2 尚未 PASS 前這句話只是設計意圖，不得當成已驗證）。log 只記 `X-GitHub-Delivery`、`operation_id` 與結果類型，不得記原始 body、簽名或 secret。

- [x] **Step 5：提交**

```bash
git add src/training_kb/ingress.py tests/integration/test_github_webhook_handler.py
git commit -m "test(ingress): 鎖定Webhook整體期限"
```

## 11. 驗收矩陣

| 路徑 | 輸入 | 預期資料結果 |
|---|---|---|
| Happy | `issue-opened.json` 的原始 bytes + 正確簽名 | `verify_github_signature` 回 `None`；parser 收到與檔案完全相同的 bytes；回應 `{"ok": True, "operation_id": ...}`。 |
| Failure | body 多一個空白但沿用舊簽名／缺 header／`sha1=` prefix | `IngressError`，`fields == ("X-Hub-Signature-256",)`；parser、Repository、StartExecution spy 全部 0 次。 |
| Failure | secret 未設定 | `PermanentError`；不得回成使用者輸入錯誤，也不得放行。 |
| Boundary | `isBase64Encoded=true` 的合法／不合法 base64 | 前者 decode 後 bytes 與原檔相同；後者 `IngressError(fields=["body"])` 且 parser 0 次。 |
| Boundary | 簽名合法但 JSON 壞掉 | 驗簽通過後才由 parser 回 `IngressError(fields=["body"])`；接受路徑 0 次。 |
| Boundary | 7.999 秒／8.000 秒 | 前者仍在期限內；後者 `TimeoutError`，回應 `ok` 為 `False` 且 `operation_id` 為 `None`。 |

人工驗收（不能只看 PASS）：用眼睛確認 `handler` 的原始碼裡 `json.loads` 一定排在 `verify_github_signature` 之後；grep 整個 repo 沒有任何真實 secret 或簽名被寫進程式、fixture 或 log 字串；確認 `tests/fixtures/github/*.json` 是 Phase 13 核對過的檔案，不是本 Phase 自己造的。**雲端停點：** 尚未以實際 Function URL 與 GitHub delivery 驗證前，只能寫「本機通過」，不得寫「GitHub 整合通過」。

## 12. 常見錯誤與停止條件

| 症狀 | 原因 | 修正／停止 |
|---|---|---|
| 同一份 JSON 驗簽失敗 | 先 `json.loads` 再 `json.dumps` 才算 HMAC | 保留原始 bytes，先驗 HMAC 再解析。 |
| 簽名錯卻仍觸發 parser | handler 次序錯 | 用 parser spy 測驗簽短路；順序錯就停止，不要只改測試。 |
| 兩秒即回 202、稍後正規化失敗 | 過早承認成功 | 八秒內完成驗簽、正規化與接受；否則回失敗／未完成，不先回成功。 |
| log 印出 signature 或 body | 診斷過度 | 只記 delivery ID、operation ID 與結果類型。 |
| 用 `==` 比對簽名 | 忽略固定時間比較 | 一律 `hmac.compare_digest`；長度與格式先擋掉。 |
| 為了讓 fixture 通過而自己改 payload 欄位 | 繞過 O6 | 停止；未核定的 `(domain, event_type)` 保持 blocked，等 Phase 13 的核對紀錄。 |

## 13. 來源與 Rule 對照

- [接入來源事件.feature](../../spec/features/接入來源事件.feature)
  - Rule 1：「GitHub webhook 必須以 X-Hub-Signature-256 驗簽」（primary）→ `tests/unit/test_github_signature.py::test_rejects_changed_raw_bytes` 斷言合法 fixture 必須先通過 HMAC 驗簽。
  - Rule 2：「沒有簽名的 GitHub webhook 請求被拒絕」（primary）→ `tests/integration/test_github_webhook_handler.py::test_bad_signature_never_reaches_parser` 斷言缺簽名時 parser 與寫入次數皆為 0。
  - Rule 18：「Agent 最終仍無法產出合法物件時回傳失敗」→ 相關（primary 在 [Phase 37](37-Phase37-Rote-Agent回退與成功提交.md)）；本 Phase 只保證入口失敗時不留下合法業務物件。
- [設計 §7.1](../../design/training-kb.md)：Function URL 對 GitHub 用 `NONE`，由程式以原始 request body 計算 HMAC-SHA256，先比對 `X-Hub-Signature-256` 才解析 JSON，並採固定時間比較；此設定不是免驗證接入。手動上傳由已登入 AWS 的維護者呼叫匯入 handler，不建立第二個公開 URL。
- 設計 §14.1：webhook 無簽名或簽名不符時由 Ingress 拒絕，不能先進 Rote 或寫合法 Ticket／Release；入口回傳「操作失敗」與不合法欄位，不新增 HTTP 錯誤碼契約。
- 設計 §14.3：公開入口的八秒整體期限優先於其他時限；GitHub 超過十秒可能記為失敗且不自動重送。
- 設計 §17.1、§17.2：[Lambda Function URL 權限](https://docs.aws.amazon.com/lambda/latest/dg/urls-auth.html) 設 `NONE` 仍需 resource policy，驗簽由 handler 執行；webhook secret 只由執行環境提供，頁面、種子檔、Git 與公開 log 不含真實金鑰。
- O6（設計 §18）：只有 `("github.com", "issues")` 的 `action, issue, repository, sender` 已核定；真實 Issue／PR mapping 未核定前，不可自行發明 ID 或欄位。
- [GitHub 驗簽](https://docs.github.com/en/webhooks/using-webhooks/validating-webhook-deliveries)：`sha256=` 前綴、以原始 payload 計算、用固定時間比較函式；[GitHub 失敗處理](https://docs.github.com/en/webhooks/using-webhooks/handling-failed-webhook-deliveries)：超過十秒可能記為失敗且不自動重送。

## 14. 完成清單

- [x] 使用原始 bytes 與 HMAC-SHA256，且比對一律走 `hmac.compare_digest`。
- [x] 驗簽一定早於 JSON parse，錯簽名時 parser、Repository 與 StartExecution spy 都是 0 次。
- [x] `IngressError.fields` 是 `tuple[str, ...]`，簽名錯誤固定回 `("X-Hub-Signature-256",)`。
- [x] secret 未設定時丟 `PermanentError`，不是 `IngressError`，也不會放行。
- [x] 八秒是整體 deadline，往下傳給 Phase 31／32，沒有分段重置。
- [x] `normalize_then_accept` 是 00A D-60 的六個 keyword 參數，handler 傳的是 `domain="github.com"`、由 `X-GitHub-Event` 對應的 `adapter`、`event_type`、小寫化 `headers` 與已解析 `payload`。
- [x] 成功回執只在正規化與接受完成後產生；逾時回應的 `ok` 為 `False`。
- [x] 非 GitHub 來源仍沒有公開 URL；log 不含 body、簽名或 secret；fixture 全部來自 Phase 13 的核對紀錄，未核定來源維持 blocked。
- [x] 尚未把本機測試稱為 GitHub／AWS 整合通過。

## 15. 實作差異紀錄（2026-09-14 完成時補記）

計畫寫的形狀一律保留，以下是實作時為了通過 `uv run mypy src infra`（strict、無 `# type: ignore`）
與「公開入口不得因為畸形輸入直接崩掉」而補的差異，行為與第 6、7 節的契約一致：

| 差異 | 原因 |
|---|---|
| `event: dict[str, Any]`、`parse_json(raw) -> dict[str, Any]` | mypy strict 的 `disallow_any_generics` 不收沒有參數的 `dict`（詳見第 6 節補記）。 |
| `parse_json` 在 `json.JSONDecodeError` 之外，另外擋掉「合法 JSON 但不是物件」（例如 `[1,2]`） | strict 的 `warn_return_any` 不准把 `json.loads` 的 `Any` 直接當 `dict` 回傳；順帶讓 `Mapping[str, JSONValue]` 這個宣告是真的。回的仍是 `IngressError(fields=("body",))`。 |
| 新增私有 `_raw_headers(event)`，`lower_headers` 與 `header` 都走它 | 原本兩處各寫一次 `(event.get("headers") or {})`；`headers` 不是對照表時（公開入口可能收到任何形狀）`.items()` 會直接 `AttributeError`，改成當作沒有 header，於是走「缺簽名」的正常拒絕路徑。 |
| `decode_body` 先擋 `body` 不是字串 | 同上理由，回 `IngressError(fields=("body",))` 而不是 `AttributeError`。 |
| 新增 `SECRET_ENV`、`DELIVERY_HEADER` 兩個常數與 `_log`／`_record` | 第 10 節 Task 3 Step 4 要求「log 只記 `X-GitHub-Delivery`、`operation_id` 與結果類型」，原本的最小實作完全沒有 log。`_record` 只印這三樣，結果類型固定 `accepted`／`rejected`／`timeout`。 |
| 兩個同名（大小寫不同）的簽名 header 視為沒有有效簽名 | 第 9 節 Step 3 的 `header()` 已經這樣寫，這裡只是補了對應測試 `test_duplicate_signature_headers_count_as_no_signature`。 |

另外兩點與計畫一致、但值得記下來：

- `ingress.py` 依「1 驗簽 → 2 整體期限 → 3 接線點」分節並在模組 docstring 寫明追加位置，
  P31 的正規化請加在「3 接線點」之前，P32／P37 直接換掉 `normalize_then_accept` 的內容。
- `tests/integration/test_github_webhook_handler.py` 不需要真實 AWS（純函式＋monkeypatch spy），
  依 00A 第 3.2 節的慣例**不標** `aws` marker，所以它在一般 `uv run pytest tests` 就會跑。
