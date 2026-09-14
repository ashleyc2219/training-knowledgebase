# Phase 33：Rote 結構簽名與 STABLE_KEYS 實作計畫

> **給 agentic worker：** 使用 `superpowers:subagent-driven-development`（建議）或 `superpowers:executing-plans` 逐項執行；每個 Task 先建立失敗測試，再寫最小實作。

**目標：** 以可信來源網域、允許的 header 名稱及事件型別專屬 `STABLE_KEYS` 產生可重現的 16 字元結構簽名，且完全排除事件值。

**架構：** `RawEvent` 保留來源脈絡與 payload；`structure_signature` 只取白名單後的結構形成 canonical JSON，再用 SHA-1 截前 16 碼作 PROC 索引。SHA-1 在此不是安全驗簽，GitHub 的安全邊界仍由 Phase 30 的 HMAC 負責。

**技術：** Python 3.12、`dataclasses`、`hashlib.sha1`、`json`、pytest。

## 1. 文件定位與全域限制

- **主來源：** [設計 §7.2、§15、§18 O6、§20.7](../../design/training-kb.md)；名稱以 [00A 共用契約與名詞](00A-共用契約與名詞.md) 第 6.8 節為準。
- **前置：** [Phase 13：O6 來源 ID 與穩定使用者契約](13-Phase13-O6來源ID與穩定使用者契約.md) 的核定紀錄；GitHub 路徑先經 [Phase 30：GitHub Webhook 原始 Body 驗簽](30-Phase30-GitHub-Webhook原始Body驗簽.md)。前置未通過時停止。
- **後續：** [Phase 34：Rote 兩層命中與候選排序](34-Phase34-Rote兩層命中與候選排序.md) 用 signature 查 exact PROC；[Phase 36：JSONPath 與白名單 Adapter](36-Phase36-JSONPath與白名單Adapter.md) 記錄欄位參照；[Phase 37：Rote Agent 回退與成功提交](37-Phase37-Rote-Agent回退與成功提交.md) 串起三層。
- **本階段不做：** 不驗證 request 身分；不保存任何 header 值；不從 payload 推導 domain／adapter；不替 PR、Discord、email 發明未核定的 keys；不讀寫 `PROC#` item（計數在 Phase 35、寫回在 Phase 37）。
- **O6 gate 狀態：** 只有 `("github.com", "issues")` 的 `action, issue, repository, sender` 已由設計 §19 的決策 F02 核定。其餘 `(domain, event_type)` 在 Phase 13 的核定紀錄補齊前一律 blocked，停止語句是：「O6 尚未核對，該 `(domain, event_type)` 為 blocked，不得 fallback 成可重放簽名。」本 Phase 測試全綠**不代表** O6 已通過。
- 以下程式檔均是實作時預計建立或修改；本計畫本身不代表它們已存在。

## 2. 你在整體流程的位置

```text
GitHub webhook --> Phase 30 HMAC 驗簽 --+
                                        +--> RawEvent(domain, adapter, event_type,
維護者受控匯入 ------------------------+                 headers, payload)
                                                     |
                                                     v
        [你在這裡] 過濾 header 名稱 + 查 STABLE_KEYS + 組 canonical shape
                                                     |
                                                     v
                  sha1(...)[0:16] --> Phase 34 Layer 1 / Layer 2 查詢
                                   --> Phase 36 欄位參照 --> Phase 37 三層 Rote

事件 ID、標題、時間、header 值、巢狀欄位 --X--> signature
```

## 3. 完成後看得到什麼

同一個 repo 的兩個 GitHub Issue webhook：一個是 `issue.number=128`、`title="會前摘要在哪裡開啟？"`、`sender.login="kai-w"`，另一個是 `issue.number=999`、`title="different"`、`sender.login="another-user"`，連 `X-GitHub-Delivery` 都不同。兩者的最上層 key 都是 `action, issue, repository, sender`，所以 `structure_signature` 回同一個 16 個小寫 hex 字元的字串（照第 7 節的公式算出來是 `d1ad3cfd19a24c4d`，可自己驗），[Phase 34](34-Phase34-Rote兩層命中與候選排序.md) 用它組成 `PROC#d1ad3cfd19a24c4d` 這把主鍵。拿掉 `repository` 這個最上層 key，signature 會變；加上 `X-Request-Id` header 或未核定的 `installation` key，signature 不變。對 `("github.com", "pull_request")` 呼叫則直接拋 `PermanentError`，不會回一個猜出來的簽名。

## 4. 名詞小抄

| 名詞 | 白話意思 |
|---|---|
| 結構簽名（structure signature） | 只用「事件長什麼樣子」算出來的 16 字元指紋；換掉裡面的值不會改變它。 |
| `STABLE_KEYS` | 某個來源＋事件型別「一定會有」的最上層欄位名清單，由維護者核定，不能猜。 |
| `RawEvent` | 接入層在驗簽後組出來的原始事件，帶可信 domain、adapter、事件型別、headers 與 payload。 |
| domain／adapter | 來源網域（`github.com`）與處理器類型（`github_issue`）；都來自可信入口設定，不從 payload 讀。 |
| PROC | `ProvenWorkflow` 的物理鍵前綴 `PROC#<signature>`，存已驗證的接入工具順序。 |
| O6 | 設計 §18 的第六個待確認事項「來源完整契約」；核定者欄位空白就是 blocked。 |
| F02／D19 | 設計 §19 的決策編號：F02 說每種來源＋事件型別各有自己的 key 清單，D19 說流程範圍是 domain 加 adapter。 |

## 5. 預計檔案

| 動作 | 路徑 | 責任 |
|---|---|---|
| 新增 | `src/training_kb/rote.py` | `RawEvent`、`HEADER_PREFIXES`、`STABLE_KEYS`、`event_stable_keys`、`signature_shape`、`structure_signature`。 |
| 新增 | `tests/unit/rote/test_signature.py` | 值獨立性、大小寫與排序、header 白名單、未核定來源拒絕。 |
| 新增 | `tests/integration/test_o6_stable_keys.py` | 逐列比對 Phase 13 的核定紀錄與 fixture。 |
| 消費 | `tests/fixtures/o6/approved-sources.json` | Phase 13 產出的核定紀錄，本 Phase 只讀不寫。 |

## 6. 固定介面

### Consumes

```text
Phase 02  PermanentError                                     # 未核定來源、缺可信脈絡時丟出
Phase 13  SourceApproval(domain, event_type, adapter, stable_keys, fixture, id_encoder,
                         stable_user_source, approved_by, approved_at)   # 固定九欄，順序照 Phase 13
Phase 13  load_source_approvals(path: str | Path) -> tuple[SourceApproval, ...]
Phase 13  approved_stable_keys(rows: Sequence[SourceApproval]) -> dict[tuple[str, str], frozenset[str]]
Phase 29  JSONValue                                          # 唯一定義在 training_kb.pipelines.common
```

### Produces

```python
HEADER_PREFIXES: tuple[str, ...]                      # ("x-github-", "x-discord-", "x-zendesk-")
STABLE_KEYS: Mapping[tuple[str, str], frozenset[str]]

@dataclass(frozen=True)
class RawEvent:
    domain: str; adapter: str; event_type: str
    headers: Mapping[str, str]; payload: Mapping[str, JSONValue]

def event_stable_keys(event: RawEvent) -> frozenset[str]: ...
def signature_shape(event: RawEvent) -> dict[str, object]: ...
def structure_signature(event: RawEvent) -> str: ...
```

`domain` 與 `adapter` 來自可信入口設定。依主來源的公式，`adapter` **不進** signature shape；它保存在 `ProvenWorkflow.domain`／`ProvenWorkflow.adapter`（00A 第 8 節裁決 D-09，標記為本計畫選擇，對應 O2 的「PROC 同來源脈絡缺持久化位置」與決策 D19）。ERM 的 `PROVEN_WORKFLOW` note 寫「不新增 sender、domain 或專案欄位」，設計 §18 把持久化位置留給 O2；O2 PASS 之前不得宣稱這個欄位形狀已定案。`event_stable_keys` 與 `signature_shape` 由本 Phase 新增，[00A 第 6.8 節](00A-共用契約與名詞.md) 已與 `RawEvent`／`STABLE_KEYS`／`structure_signature` 列在同一格（owner 都是 Phase 33）：前者讓 [Phase 34](34-Phase34-Rote兩層命中與候選排序.md) 的 Jaccard 與本 Phase 的簽名使用**同一份** key 取法，後者讓「shape 只有名稱、沒有值」可以被單獨斷言。

## 7. 設計細節：簽名素材的邊界

設計 §7.2 的原文是：將 `domain`、小寫排序的有意義 header 名稱、排序後的 STABLE_KEYS 組成 `shape`，再取 `sha1(json.dumps(shape, sort_keys=True).encode()).hexdigest()[:16]`。逐項展開如下。

| 素材 | 例子 | 進 signature shape？ |
|---|---|---|
| 可信入口設定的 domain | `github.com` | 是，原樣放進 shape |
| 可信入口設定的 adapter | `github_issue` | 否，存 PROC 的範圍欄位（D-09） |
| 白名單前綴的 header 名稱 | `X-GitHub-Event` | 是，小寫、去重、排序 |
| header 值、未列前綴的 header | `issues`、`X-Request-Id` | 否 |
| 已核定的 payload 最上層 key | `action`／`issue`／`repository` | 是，與 `STABLE_KEYS` 取交集 |
| 未核定 key、payload 值、巢狀欄位 | `installation`、`issue.number`、`title` | 否 |

「排序後的 STABLE_KEYS」在本計畫實作成「核定清單與**實際出現**的最上層 key 取交集後排序」。若直接放整份核定清單，同一個 `(domain, event_type)` 的每個事件都會拿到同一個簽名，設計 §15 要求的「事件值改變不改結構簽名」就分不出「結構真的變了」與「值變了」，Phase 34 的 Jaccard 也失去比較對象。缺一個核定 key 屬於**結構不同**，必須得到不同簽名；這也是 Task 3 要檢查 fixture 必備 key 齊全的原因。

```text
shape = {"domain": "github.com",
         "headers": ["x-github-delivery", "x-github-event"],
         "keys": ["action", "issue", "repository", "sender"]}
          |
          v
json.dumps(shape, sort_keys=True).encode()   <- 不加 separators，逐字照主來源公式
          |
          v
hashlib.sha1(...).hexdigest()[:16]  ->  "d1ad3cfd19a24c4d"  ->  PROC#d1ad3cfd19a24c4d
```

上面那串 `d1ad3cfd19a24c4d` 是這個 shape 的真實結果：把該 shape 字典與 `hashlib.sha1(json.dumps(shape, sort_keys=True).encode()).hexdigest()[:16]` 貼進 `python3` 互動模式就會拿到同一串，對不上代表 shape 的欄位名或序列化方式被改過了。

`json.dumps` 的預設分隔符是 `", "` 與 `": "`，一旦加上 `separators=(",", ":")`，bytes 不同、雜湊就不同，兩個實作會對不起來。SHA-1 在此只是結構索引，不是驗簽，也不得用來判斷請求是否可信。

## 8. TDD Tasks

### Task 1：建立 `RawEvent` 與未核定來源的拒絕

- [x] **Step 1：建立失敗測試**

```python
import pytest

from training_kb.errors import PermanentError
from training_kb.rote import RawEvent, structure_signature

def test_unknown_event_type_is_blocked() -> None:
    event = RawEvent("github.com", "github_pr", "pull_request", {}, {})
    with pytest.raises(PermanentError, match="STABLE_KEYS"):
        structure_signature(event)

def test_untrusted_context_is_rejected() -> None:
    event = RawEvent("", "", "issues", {}, {"action": "opened"})
    with pytest.raises(PermanentError, match="可信"):
        structure_signature(event)
```

- [x] **Step 2：執行並確認紅燈**

```bash
uv run pytest tests/unit/rote/test_signature.py -q
```

預期：FAIL，訊號包含 `ModuleNotFoundError: No module named 'training_kb.rote'`。

- [x] **Step 3：建立最小實作**

```python
from collections.abc import Mapping
from dataclasses import dataclass

from training_kb.errors import PermanentError
from training_kb.pipelines.common import JSONValue

HEADER_PREFIXES: tuple[str, ...] = ("x-github-", "x-discord-", "x-zendesk-")
STABLE_KEYS: Mapping[tuple[str, str], frozenset[str]] = {
    ("github.com", "issues"): frozenset({"action", "issue", "repository", "sender"}),
}

@dataclass(frozen=True)
class RawEvent:
    domain: str
    adapter: str
    event_type: str
    headers: Mapping[str, str]
    payload: Mapping[str, JSONValue]

def event_stable_keys(event: RawEvent) -> frozenset[str]:
    if not event.domain or not event.adapter:
        raise PermanentError("RawEvent 缺少可信入口設定的 domain 或 adapter")
    allowed = STABLE_KEYS.get((event.domain, event.event_type))
    if allowed is None:
        raise PermanentError(
            f"({event.domain}, {event.event_type}) 尚無核定 STABLE_KEYS；O6 未核對前為 blocked"
        )
    return frozenset(allowed & event.payload.keys())

def structure_signature(event: RawEvent) -> str:
    event_stable_keys(event)
    return ""  # Task 2 換成主來源的雜湊公式
```

- [x] **Step 4：跑完整檔案確認綠燈**

```bash
uv run pytest tests/unit/rote/test_signature.py -q
```

預期：`2 passed`；空 domain、空 adapter、未核定事件型別都明確失敗，沒有分支回 fallback signature。

- [x] **Step 5：提交**

```bash
git add src/training_kb/rote.py tests/unit/rote/test_signature.py
git commit -m "feat(rote): 定義來源結構事件"
```

### Task 2：以 canonical shape 計算 signature

- [x] **Step 1：建立失敗測試**

```python
from dataclasses import replace

ISSUE_PAYLOAD = {
    "action": "opened",
    "issue": {"number": 128, "title": "會前摘要在哪裡開啟？"},
    "repository": {"full_name": "acme/copilot"},
    "sender": {"login": "kai-w", "id": 90210},
}
ISSUE_HEADERS = {"X-GitHub-Event": "issues", "X-GitHub-Delivery": "d-1", "X-Request-Id": "r-1"}

@pytest.fixture
def issue_event() -> RawEvent:
    return RawEvent("github.com", "github_issue", "issues", ISSUE_HEADERS, ISSUE_PAYLOAD)

def test_signature_is_sixteen_lowercase_hex(issue_event: RawEvent) -> None:
    signature = structure_signature(issue_event)
    assert len(signature) == 16
    assert set(signature) <= set("0123456789abcdef")

@pytest.mark.parametrize("changes", [
    {"payload": {**ISSUE_PAYLOAD, "action": "closed", "sender": {"login": "another-user", "id": 1},
                 "issue": {"number": 999, "title": "different"}}},
    {"headers": {"x-github-delivery": "d-2", "X-GITHUB-EVENT": "issue_comment",
                 "Content-Type": "application/json"}},
    {"payload": {**ISSUE_PAYLOAD, "installation": {"id": 7}}},
], ids=["event-values", "header-case-value", "unapproved-key"])
def test_signature_ignores_everything_but_structure(issue_event: RawEvent, changes: dict) -> None:
    assert structure_signature(replace(issue_event, **changes)) == structure_signature(issue_event)

def test_missing_approved_key_changes_signature(issue_event: RawEvent) -> None:
    trimmed = {name: value for name, value in ISSUE_PAYLOAD.items() if name != "repository"}
    assert structure_signature(replace(issue_event, payload=trimmed)) != structure_signature(issue_event)
```

- [x] **Step 2：執行並確認紅燈**

```bash
uv run pytest tests/unit/rote/test_signature.py -q
```

預期：FAIL，訊號是 `test_signature_is_sixteen_lowercase_hex` 的 `assert 0 == 16`（Task 1 的 `structure_signature` 還回空字串）。

- [x] **Step 3：建立最小實作**

```python
import hashlib
import json

def signature_shape(event: RawEvent) -> dict[str, object]:
    headers = sorted(
        {name.lower() for name in event.headers if name.lower().startswith(HEADER_PREFIXES)}
    )
    return {"domain": event.domain, "headers": headers, "keys": sorted(event_stable_keys(event))}

def structure_signature(event: RawEvent) -> str:
    shape = signature_shape(event)
    return hashlib.sha1(json.dumps(shape, sort_keys=True).encode()).hexdigest()[:16]
```

- [x] **Step 4：跑完整檔案確認綠燈**

```bash
uv run pytest tests/unit/rote/test_signature.py -q
```

預期：`7 passed`；插入順序、大小寫、header 值、未核定欄位都不改結果，少一個已核定 key 才改結果。
（上面 Step 1 的 `parametrize` 清單在實際檔案裡依 `ruff` 的 `line-length = 100` 換行，斷言內容不變。）

- [x] **Step 5：提交**

```bash
git add src/training_kb/rote.py tests/unit/rote/test_signature.py
git commit -m "feat(rote): 計算無事件值結構簽名"
```

### Task 3：逐來源核對 O6 核定紀錄

- [x] **Step 1：建立失敗測試**

```python
import json
from dataclasses import replace
from pathlib import Path

import pytest

from training_kb.errors import PermanentError
from training_kb.rote import STABLE_KEYS, RawEvent, signature_shape, structure_signature
from training_kb.source_ids import SourceApproval, approved_stable_keys, load_source_approvals

REPO_ROOT = Path(__file__).resolve().parents[2]   # 與 P13 的整合測試同一種路徑推導
FIXTURE_ROOT = REPO_ROOT / "tests" / "fixtures"
APPROVALS = load_source_approvals(FIXTURE_ROOT / "o6/approved-sources.json")
APPROVED = [row for row in APPROVALS if row.approved_by]

def mask_values(value: object) -> object:
    if isinstance(value, dict):
        return {name: mask_values(item) for name, item in value.items()}
    if isinstance(value, list):
        return [mask_values(item) for item in value]
    return "MASKED"

def test_stable_keys_matches_the_approval_record() -> None:
    assert dict(STABLE_KEYS) == approved_stable_keys(APPROVED)

@pytest.mark.parametrize("row", APPROVED, ids=lambda row: f"{row.domain}:{row.event_type}")
def test_approved_fixture_keeps_structure_without_values(row: SourceApproval) -> None:
    payload = json.loads((FIXTURE_ROOT / row.fixture).read_text(encoding="utf-8"))
    assert set(row.stable_keys) <= set(payload)
    event = RawEvent(row.domain, row.adapter, row.event_type, {}, payload)
    masked = replace(event, payload=mask_values(payload))
    assert signature_shape(masked) == signature_shape(event)
    assert structure_signature(masked) == structure_signature(event)

def test_pending_sources_stay_blocked() -> None:
    for row in APPROVALS:
        if row.approved_by:
            continue
        with pytest.raises(PermanentError, match="STABLE_KEYS"):
            structure_signature(RawEvent(row.domain, row.adapter, row.event_type, {}, {}))

@pytest.mark.xfail(strict=True, reason="O6 尚未核對完畢，見 docs/plan/report/o6-mapping.md")
def test_every_source_row_is_approved() -> None:
    assert [f"{row.domain}:{row.event_type}" for row in APPROVALS if not row.approved_by] == []
```

- [x] **Step 2：執行並確認紅燈**

```bash
uv run pytest tests/integration/test_o6_stable_keys.py -q
```

原本預期的紅燈訊號是 `cannot import name 'approved_stable_keys'` 或核定紀錄檔不存在。但 Phase 13
已交付 `approved_stable_keys` 與 `tests/fixtures/o6/approved-sources.json`，而 Task 1 Step 3 抄進
`STABLE_KEYS` 的那一列就是本 Task 要的最終內容，所以這個檔一寫完就是綠燈。改以「證明它會紅」取代：
暫時把 `("github.com", "issues")` 少抄一個 key、並多抄一列未核定的 `pull_request`，重跑應看到
`test_stable_keys_matches_the_approval_record` 與 `test_pending_sources_stay_blocked` 兩個 FAIL
（後者是 `DID NOT RAISE`），再把 `STABLE_KEYS` 還原成逐列相等的版本。

- [x] **Step 3：建立最小實作**

把 `STABLE_KEYS` 改成逐條抄寫核定紀錄中 `approved_by` 非空的列；正式程式不讀 `tests/` 路徑，抄錯由 `test_stable_keys_matches_the_approval_record` 擋下來。

```python
STABLE_KEYS: Mapping[tuple[str, str], frozenset[str]] = {
    # 逐條抄自 Phase 13 的核定紀錄（approved_by 非空的列）
    ("github.com", "issues"): frozenset({"action", "issue", "repository", "sender"}),
    # ("github.com", "pull_request"): 等 O6 核定後才加入，核定前保持 blocked
}
```

- [x] **Step 4：跑完整檔案確認綠燈**

```bash
uv run pytest tests/unit/rote/test_signature.py tests/integration/test_o6_stable_keys.py -q
```

預期：核對、blocked 與已核定列的參數化案例 PASS，`test_every_source_row_is_approved` 顯示 `xfailed`；核定紀錄全部填完後它會變成 `XPASS(strict)` 而讓測試失敗，那是提醒你移除 marker 並更新 O6 狀態的訊號。

- [x] **Step 5：提交**

```bash
git add src/training_kb/rote.py tests/integration/test_o6_stable_keys.py
git commit -m "test(rote): 核對 O6 來源清單"
```

## 9. 驗收矩陣

| 路徑 | 輸入 | 預期資料結果 |
|---|---|---|
| Happy | 兩個最上層 key 相同、事件值全部不同的 GitHub Issue payload | 兩次 `structure_signature` 回同一個 16 個小寫 hex 字元的字串 |
| Failure | `("github.com", "pull_request")`；或 `domain=""`、`adapter=""` | 丟 `PermanentError`，訊息含 `STABLE_KEYS` 或「可信」；沒有 fallback signature |
| Boundary | header 大小寫、順序、值改變；加入 `X-Request-Id` 或未核定的 `installation` key | signature 完全不變 |
| Boundary | 移除已核定的 `repository` key，或補上原本缺席的另一個已核定 key | signature 改變 |
| Gate | 核定紀錄仍有 `approved_by` 空白的列 | `test_every_source_row_is_approved` 維持 `xfailed`，O6 保持未完成 |

人工驗收（不能只看 PASS）：打開 `docs/plan/report/o6-mapping.md`，確認九欄與 `tests/fixtures/o6/approved-sources.json` 逐列一致且核定者不是「待填」；在 `uv run pytest ... -q -s` 的輸出與 `signature_shape` 的序列化結果中搜尋 fixture 的 `title`、`login`、`node_id` 等值，命中筆數必須為零；確認 `src/training_kb/rote.py` 沒有任何 `tests/fixtures/` 字串。

## 10. 常見錯誤與停止條件

| 症狀 | 原因 | 修正／停止 |
|---|---|---|
| 每個 Issue 都得到不同 signature | shape 放進了 `issue.number`、`title` 或 header 值 | shape 只留名稱清單，重跑 `test_signature_ignores_everything_but_structure`。 |
| 同一個來源的每個事件 signature 都一樣 | 用整份核定清單而不是與 payload 的交集 | 改回 `allowed & event.payload.keys()`，否則 Phase 34 的 Jaccard 沒有比較對象。 |
| PR 事件沿用 Issue 的四個 key | 把 O6 的待核定當成已核定 | 停止 PR 的 Rote 路徑並保留 blocked；等 Phase 13 補齊核定紀錄，不得補猜清單。 |
| 兩個實作算出的 signature 對不起來 | 加了 `separators` 或改了 shape 的欄位名 | 逐字照設計 §7.2 的 `json.dumps(shape, sort_keys=True).encode()`。 |
| 拿 signature 當驗簽，或 `domain` 取自 request body | 混淆結構索引與身分認證；攻擊者可自選分組 | 停止合併；GitHub 路徑必須先過 Phase 30 的 HMAC，`domain`／`adapter` 只能來自可信入口設定。 |
| 正式程式讀 `tests/fixtures/o6/...` | 把核定紀錄當成執行期設定 | 改成逐條抄寫的 literal，由整合測試比對，測試資料不進部署產物。 |

## 11. 來源與 Rule 對照

- [接入來源事件.feature](../../spec/features/接入來源事件.feature)
  - Rule 3（primary）：「來源簽名使用來源網域、有意義的 header 名稱與穩定 payload key 計算」→ Task 2 的 `test_signature_ignores_everything_but_structure`、`test_missing_approved_key_changes_signature` 與 Task 3 的 `test_approved_fixture_keeps_structure_without_values` 直接斷言；Phase 13（提供核定紀錄）與 [Phase 36](36-Phase36-JSONPath與白名單Adapter.md)（記錄欄位參照）為相關。
  - Rule 4（primary）：「ID、時間戳與標題等事件值不參與來源簽名」→ Task 2 的 `event-values` 參數化案例與 Task 3 的 `mask_values` 全量替換直接斷言。
  - Rule 5（相關，primary 在 [Phase 34](34-Phase34-Rote兩層命中與候選排序.md)）與 Rule 12（相關，primary 在 [Phase 36](36-Phase36-JSONPath與白名單Adapter.md)）：本 Phase 只負責產出第一層那把主鍵，並保證 signature 與 shape 都不含事件真值。
- [設計 §7.2](../../design/training-kb.md)：`sha1(json.dumps(shape, sort_keys=True).encode()).hexdigest()[:16]` 公式、header 只取 x-github／x-discord／x-zendesk 前綴、SHA-1 只是結構索引。
- 設計 §15「來源與 Rote」驗收列：「有效／無效／缺少簽名；事件值改變不改結構簽名」對應第 9 節的 Happy、Failure 與第一列 Boundary；同列的「Jaccard 0.7999／0.8；成功數 2／3」屬於 [Phase 34](34-Phase34-Rote兩層命中與候選排序.md)。
- 設計 §18 O6：F02 只提供 Issue 的 STABLE_KEYS，其餘來源必須先有實際 fixture 與維護者核定。
- 設計 §19 決策 F02：「每一種來源與事件類型有自己的固定必備 top-level key 清單。」決策 D19：「來源網域與 adapter 類型共同構成範圍」，所以 adapter 存在 PROC 欄位而不進 shape。
- [00A 共用契約與名詞](00A-共用契約與名詞.md) 第 6.8 節與裁決 D-09、D-31。

## 12. 完成清單

- [x] `RawEvent` 的 `domain`／`adapter` 只來自可信入口設定，沒有任何分支從 payload 推導。
- [x] GitHub Issue 的核定 keys 精確是 `action, issue, repository, sender` 四個。
- [x] 其他 `(domain, event_type)` 在核定前呼叫會拋 `PermanentError`，而不是回 fallback signature。
- [x] signature shape 只含 domain、已核定 key 名稱，與經小寫、去重、排序且只保留三個指定前綴的 header 名稱；序列化結果搜不到任何事件值。
- [x] `structure_signature` 回可重現的 16 個小寫 hex 字元，公式與設計 §7.2 逐字相同。
- [x] `STABLE_KEYS` 與核定紀錄逐列相等，且正式程式不讀 `tests/` 路徑。
- [x] 文件與程式註解都沒有把 SHA-1 描述成安全驗簽，O6 仍標為未完成。
