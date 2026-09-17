# Phase 10：Ingress-驗簽驗證與去重

| 項目 | 內容 |
|---|---|
| 上一階段 | Phase 09：圖譜查詢與 backfill（`09-Phase09-圖譜查詢與backfill.md`） |
| 下一階段 | Phase 11：Rote-結構簽名與流程重放判定（`11-Phase11-Rote-結構簽名與流程重放判定.md`） |
| 對應設計文件章節 | §7.1、§14.1、§14.2、§14.3、O6（`docs/design/training-kb.md`） |
| 對應交付切片 | S1（設計文件第 16 節） |
| 預估時間 | 約 5 小時 |
| 做完會得到 | `ingress.py` 的入口守門邏輯：驗 GitHub 簽名、檢查必填欄位與枚舉、把上游識別碼編成 `t_`／`r_` ID，並且保證同一個事件重送只會被處理一次。 |

---

## 1. 這階段做完會得到什麼

「Ingress」就是**大門**。所有從外面進來的事件都要先通過這道門，門後面才是 Rote、Step Functions 與教學內容。

做完這一階段，`src/training_kb/ingress.py` 會有這些能力：

| 能力 | 函式 | 為什麼需要 |
|---|---|---|
| 確認這個 webhook 真的是 GitHub 送的 | `verify_github_signature` | 我們的 Lambda Function URL 對外是 `NONE`（不驗 IAM），唯一的身分證明就是簽名 |
| 把 GitHub 的 owner/repo/編號變成穩定 ID | `github_ticket_id`、`github_release_id` | 規格要求 ID 要有 `t_`／`r_` 前綴且全域唯一（O6 本計劃選擇） |
| 檢查欄位齊不齊、值合不合法 | `validate_ticket`、`validate_release` | 不合法就回「操作失敗」並指出欄位，不寫進資料庫 |
| 幫每個事件取一個固定的「操作 ID」 | `operation_id_for`、`execution_name` | 同一個事件不管送幾次，算出來的 ID 都一樣，才能去重 |
| 保存物件並啟動流程，而且只做一次 | `accept_ticket`、`accept_release` | 重送不會重複建教學版本、不會重複計一筆回饋 |

**這一階段完全不呼叫 AI。** 它只做「確認身分 → 檢查資料 → 保存 → 啟動 → 記帳」。

### 一個具體的例子

有人在 GitHub 上開了 Issue #17（repo 是 `acme/notes`）。GitHub 送一個 webhook 過來：

```text
POST /  ...
x-hub-signature-256: sha256=757107ea0eb2509fc211221cce984b8a37570b6d7586c22c46f4379c8b043e17
x-github-event: issues
x-github-delivery: 72d3162e-cc78-11e3-81ab-4c9367dc0958
{"action":"opened","issue":{"number":17,...},"repository":{...},"sender":{...}}
```

這一階段的程式會：

1. 用 `x-hub-signature-256` 驗簽 → 不對就直接回失敗，**連 JSON 都不解析**。
2. 算出 Ticket ID = `t_gh-acme-notes-17`。
3. 檢查 `id`、`source`、`text`、`author`、`ts`、`project_id` 都有值且合法。
4. 算出操作 ID = `ingest:ticket:t_gh-acme-notes-17`。
5. 查一下這個操作 ID 有沒有處理過；沒有 → 保存 Ticket → 啟動 `ticket-analysis` → 記錄「已啟動」。
6. 回傳 `AcceptResult(status="accepted", ...)`。

如果 GitHub 因為逾時而重送同一個 delivery，第 5 步會查到紀錄，直接回 `duplicate`，**不會再建立一個教學版本**。

---

## 2. 它在整張地圖的位置

```text
基礎層          01 骨架 -> 02 模型與鍵 -> 03 Repository(本機) -> 04 AWS 基礎建設
                                                                      |
AI 與內容層     05 Writing(Bedrock) -> 06 規則注入 -> 07 建立版本 -> 08 發布與退役 -> 09 圖譜查詢
                                                                                        |
接入層          10 Ingress 驗簽 -> 11 Rote 判定 -> 12 Rote Agent -------------------------+
                  ^
                  |
           ★ 你在這裡 ★
                  |
流程層          13 Ticket Analysis -> 14 Step Functions 上線 -> 15 Feedback/View 匯入 -> 16 Release Update
                                                                                        |
學習層          17 Review:REFINE -> 18 Review:候選規則+排程 -> 19 Analytics 指標 -> 20 規則驗證
                                                                                        |
展示與驗收層    21 Demo 種子資料 -> 22 靜態教學站 -> 23 Demo 控制台 -> 24 失敗復原驗收 -> 25 安全與當日準備
```

你現在開始做「接入層」的第一格。前面的基礎層與內容層已經能「存資料」「建教學」「查圖譜」；從這一格開始，系統終於有辦法接收外面的事件。

---

## 3. 開始前檢查

- [ ] **1）確認前一階段完成**

執行：

```bash
cd ~/AWS-Hackathon
uv run pytest -q
```

預期：全部 passed，且 `tests/integration/` 裡已經有 Phase 09 的測試。

- [ ] **2）確認錯誤型別存在（Phase 01 建立）**

執行：

```bash
uv run python -c "
from training_kb.errors import IngressError, PermanentError, TransientError
err = IngressError('缺少欄位', fields=['id', 'ts'])
print(isinstance(err, PermanentError), err.fields, str(err))
"
```

預期輸出：

```text
True ['id', 'ts'] 缺少欄位
```

如果出現 `AttributeError: 'IngressError' object has no attribute 'fields'`，代表 Phase 01 的 `IngressError.__init__` 沒有把 `fields` 存成屬性，請先補上 `self.fields = fields`。

- [ ] **3）確認時間工具存在（Phase 01 建立）**

執行：

```bash
uv run python -c "
from training_kb.clock import now_utc, to_iso, parse_iso
print(to_iso(parse_iso('2026-08-01T00:00:00+00:00')))
print(to_iso(parse_iso('2026-08-01T00:00:00Z')))
"
```

預期輸出兩行都是 `2026-08-01T00:00:00Z`。

- [ ] **4）確認模型與枚舉存在（Phase 02 建立）**

執行：

```bash
uv run python -c "
from training_kb.models import Ticket, Release, Feedback, TutorialView
from training_kb.models import TicketSource, ReleaseSource, ReleaseKind
print([s.value for s in TicketSource])
print([s.value for s in ReleaseSource], [k.value for k in ReleaseKind])
"
```

預期輸出：

```text
['github_issue', 'discord', 'email']
['github_pr', 'changelog'] ['renamed', 'changed', 'removed']
```

- [ ] **5）確認 Repository 有操作紀錄的三個方法（Phase 03 建立）**

執行：

```bash
uv run python -c "
from training_kb.repository import Repository
need = ['begin_operation', 'load_operation', 'update_operation', 'put_ticket', 'put_release']
have = dir(Repository)
print([n for n in need if n not in have] or 'OK')
"
```

預期輸出：`OK`。若印出缺少的名稱，請先補完 Phase 03 與 Phase 09。

---

## 4. 名詞小抄

| 名詞 | 白話解釋 | 在本階段哪裡用到 |
|---|---|---|
| webhook | 外部系統（這裡是 GitHub）在事情發生時，主動把資料 POST 到你指定的網址。 | 全部 |
| HMAC-SHA256 | 一種「用密鑰算出的指紋」。同樣的密鑰＋同樣的內容，算出來一定一樣；密鑰不對就完全不同。 | Task 1 |
| `X-Hub-Signature-256` | GitHub 放指紋的 HTTP header，格式固定是 `sha256=<64 個十六進位字元>`。 | Task 1 |
| 原始 body（raw body） | 還沒被 JSON 解析、一個位元組都沒改動的請求內容。驗簽一定要用它。 | Task 1 |
| `hmac.compare_digest` | 固定時間比較字串的函式。用 `==` 比會因為「比到第幾個字元才不同」洩漏資訊，攻擊者可以據此猜出正確簽名。 | Task 1 |
| Lambda Function URL | 給 Lambda 一個公開網址。本專案設成 `AuthType=NONE`，代表 AWS 不幫你驗身分，**所以驗簽是唯一防線**。 | 第 5.1 節 |
| 冪等（idempotent） | 同一件事做一次和做十次，結果一樣。 | Task 7、8 |
| 去重（deduplication） | 同一個事件送很多次，只真正處理一次。 | Task 7、8 |
| 操作紀錄（operation record） | 我們自己記的一本帳：這個事件處理到哪一步了、物件存了沒、流程啟動了沒。存在 DynamoDB `OPS#<id>` 與 S3 `operations/<id>.json`。 | Task 5、7、8 |
| `operation_id` | 操作紀錄的 key，格式 `ingest:ticket:t_881`。同一個事件永遠算出同一個。 | Task 5 |
| Step Functions | AWS 的流程編排服務，把多個步驟串成一條有重試、有分支的流程。 | Task 6 |
| `StartExecution` | 啟動一條 Step Functions 流程的 API。 | Task 6 |
| `ExecutionAlreadyExists` | Step Functions 的錯誤：同名執行已經存在，而且 input 不同或已經結束。 | 第 5.4 節 |
| Protocol | Python 的「結構型別」。只要物件有相同名稱與簽名的方法就算符合，不必繼承。方便測試時換成假的。 | Task 6 |
| `AcceptResult` | 這一階段對外的回傳值：`accepted`／`duplicate`／`failed` 三種狀態。 | Task 6 |
| 「操作失敗」 | Gherkin 規格裡的 `Then 操作失敗`。設計文件 §14.1 說它不對應新的 HTTP 錯誤碼表，只要指出不合法欄位。 | Task 3、4 |
| O6 | 設計文件第 18 節的待確認事項編號：「來源完整契約」。本計劃選擇的編碼方式見 Task 2。 | Task 2 |
| F09 | 設計文件第 19.2 節的功能決策編號：「同一事件只接受一次邏輯處理；重送回傳既有結果或沿用未完成執行。」 | Task 7、8 |
| D02 | 設計文件第 19.1 節的資料決策編號：「正規化 id 直接使用上游 ID，接入層產出 `t_`、`r_`、`f_` 前綴且不撞號。」 | Task 2、3、4 |
| D10 | 設計文件第 19.1 節的資料決策編號：Release 必填欄位，`renamed` 另要求 `old_name`、`new_name`。 | Task 4 |

---

## 5. 設計說明

### 5.1 為什麼驗簽是唯一防線

設計文件 §7.1 的「本文件設計選擇」寫得很明白：

> Function URL 對 GitHub 使用 `NONE`，由程式以原始 request body 計算 HMAC-SHA256，先比對 `X-Hub-Signature-256` 才解析 JSON；採固定時間比較。**此設定不是免驗證接入。**

三個不能妥協的細節：

1. **用原始 body。** 如果先 `json.loads` 再 `json.dumps` 回去算簽名，空白與鍵的順序都會變，簽名一定對不上。
2. **用 `hmac.compare_digest`。** 普通的 `==` 會在第一個不同的字元就回傳，攻擊者可以量測時間逐字猜出正確簽名。
3. **先驗簽再解析。** 設計文件 §14.1：「webhook 無簽名、簽名不符 → Ingress 拒絕，**不能先進 Rote 或寫合法 Ticket／Release**。」

GitHub 官方文件給的 Python 範例就是我們要抄的版本：

```python
hash_object = hmac.new(secret_token.encode('utf-8'), msg=payload_body, digestmod=hashlib.sha256)
expected_signature = "sha256=" + hash_object.hexdigest()
if not hmac.compare_digest(expected_signature, signature_header):
    ...
```

### 5.2 八秒的時間預算

設計文件 §14.3：

> GitHub 要求及時回應，超過十秒可能記為失敗，而且不自動重送。**本文件設計選擇：** 公開入口在八秒內完成或明確回傳失敗；**不能先回成功、再讓不合法正規化留待背景處理。**

所以整個 webhook handler 的預算長這樣：

```text
0s                                                                    8s
|---------------------------------------------------------------------|
|驗簽|  Rote 判定  |    正規化（可能呼叫模型）    | 保存 | 啟動 | 回應 |
|<1ms|   <50ms     |  第 1/2 層 0ms；第 3 層數秒  | ~50ms| ~100ms|      |
     ^             ^                              ^      ^
     |             |                              |      |
  Phase 10      Phase 11                       Phase 10 Phase 10
  (Task 1)                                     (Task 7) (Task 7)

第 3 層（Agent 選工具）可能吃掉大部分預算。設計文件 §14.3 的處理方式是：
「首次 Rote 探索可能超時，展示前先以受控事件累積成功流程；
  需重新送達時由維護者使用 GitHub 原有重送功能。」
-> 不是「先回 200 再背景處理」。
```

這也解釋了為什麼 `accept_ticket` 在「流程啟動失敗」時**回傳 `failed` 而不是拋例外**：handler 必須在時限內給 GitHub 一個明確答案，讓對方能用既有的重送機制再試一次。

### 5.3 去重：一個事件、兩本帳、三種結果

同一個事件可能因為兩種原因重複出現：

- **同一次投遞重送**：GitHub 逾時後重送同一個 `x-github-delivery`。
- **不同投遞但同一個業務事件**：維護者手動重送、或同一個 Issue 被再次觸發，算出同樣的 `t_gh-acme-notes-17`。

所以我們記兩本帳（都存在同一套操作紀錄裡）：

```text
  import:delivery:<x-github-delivery>   -> 指向它對應的 operation_id
  ingest:ticket:<t_...>                 -> 這個業務事件的真正處理紀錄
```

處理紀錄有三個階段（stage）：

```text
       （沒有紀錄）
            |
            | begin_operation 條件寫入成功
            v
      +------------+   save 物件成功   +---------+   start 成功   +-----------+
      | received   |-----------------> | saved   |--------------> | started   |
      +------------+                   +---------+                +-----------+
            |                               |                           |
            | 重送                          | 重送                      | 重送
            v                               v                           v
      重新走一次（物件還沒存）        沿用：再存一次（冪等）      直接回 duplicate
      status=accepted                 再啟動一次（同名同 input    不再保存、不再啟動
                                      會拿到同一個 ARN）
                                      status=accepted
                                      message 註明「沿用既有操作紀錄」
```

對應設計文件 §15 的驗收項目：「接入去重：同事件重送只對應一次邏輯處理；**保存後但啟動前失敗可辨識，不遺失也不重複建版。**」

`stage="saved"` 就是「保存後但啟動前失敗」這個狀態的名字。它讓重送時能明確辨識並續作，而不是重新產生一個新的版本鏈。

### 5.4 為什麼不能只靠 Step Functions 的冪等

AWS 官方文件對 `StartExecution` 的說明是：

> `StartExecution` is idempotent for `STANDARD` workflows. For a `STANDARD` workflow, if you call `StartExecution` with the same **name and input** as a **running** execution, the call succeeds and return the same response as the original request. If the execution is **closed** or if the **input is different**, it returns a `400 ExecutionAlreadyExists` error. You can reuse the name **90 days** after it closes.

翻成白話，它的冪等有三個洞：

| 洞 | 後果 |
|---|---|
| 執行已經結束 | 再送同名會拿到 `ExecutionAlreadyExists` 錯誤，不是「成功」 |
| input 有一點點不同 | 直接報錯 |
| 90 天後名稱可以重用 | 90 天後同一個事件會被重跑一次 |

設計文件 §14.2 因此規定：「已結束的同名執行會回傳 `ExecutionAlreadyExists`，**不能把此例外直接當成功**，也不能改名就無條件重跑。需檢查原結果與操作紀錄。」§17.1 也寫「同名 input 的啟動冪等有執行狀態與保留期限限制，**不能取代永久事件去重**」。

所以我們的去重靠**自己的操作紀錄**（O2 本計劃選擇：DynamoDB `OPS#<operation_id>` 條件寫入 ＋ S3 `operations/<id>.json`），Step Functions 的冪等只是第二層保險。

執行名稱要固定可重現，才能讓第二層保險生效，這就是 `execution_name(operation_id)` 的用途。注意 `StartExecution` 的 `name` **不能包含 `:`**（官方文件列的禁用字元包含 `" # % \ ^ | ~ \` $ & , ; : /`），長度上限 80 字元，所以我們把 `:` 換成 `_`。

### 5.5 操作紀錄長什麼樣

```text
DynamoDB item                                S3 物件
+-------------------------------------+      operations/ingest_ticket_t_881.json
| PK  = OPS#ingest:ticket:t_881       |      {
| SK  = META                          |        "kind": "ticket",
| entity = "OPS"                      |        "bare_id": "t_881",
| kind = "ticket"                     |        "operation_id": "ingest:ticket:t_881",
| bare_id = "t_881"                   |        "stage": "started",
| operation_id = "ingest:ticket:t_881"|        "object_id": "t_881",
| stage = "started"                   |        "execution_arn": "arn:aws:states:...",
| object_id = "t_881"                 |        "pipeline": "ticket-analysis",
| execution_arn = "arn:aws:states:..."|        "created_at": "2026-08-02T09:00:00Z",
| pipeline = "ticket-analysis"        |        "updated_at": "2026-08-02T09:00:01Z"
| created_at / updated_at             |      }
+-------------------------------------+

另一本（只有 webhook 才有）：
| PK = OPS#import:delivery:72d3162e-... |  -> { "operation_id": "ingest:ticket:t_881", ... }
```

`begin_operation` 用 DynamoDB 的條件寫入（「不存在才寫」）確保**只有一個呼叫者會拿到 True**，所以就算同一瞬間收到兩份重送，也只有一份會真的去保存物件與啟動流程。

### 5.6 這階段會新增的檔案

```text
src/training_kb/
  ingress.py                        <- 本階段的主角（新檔案）
tests/
  unit/
    test_ingress_signature.py       <- 驗簽
    test_ingress_ids.py             <- ID 編碼
    test_ingress_validate.py        <- Ticket 與 Release 的欄位與枚舉驗證
    test_ingress_operation.py       <- 操作 ID 與執行名稱
    test_ingress_starter.py         <- PipelineStarter 與 AcceptResult
  integration/
    test_ingress_accept.py          <- 保存＋啟動＋去重（用 Phase 03 的 repo fixture）
```

---

## 6. 工作項目

### Task 1：GitHub webhook 驗簽

**目的**：確認這個請求真的是我們設定的那個 GitHub webhook 送來的。

**檔案**：
- 新增：`src/training_kb/ingress.py`
- 測試：`tests/unit/test_ingress_signature.py`

**介面**：
- 消費：無（只用 Python 標準庫 `hmac`、`hashlib`）
- 產出：
  - `ingress.GITHUB_SIGNATURE_HEADER: str`（新增；常數 `"x-hub-signature-256"`）
  - `ingress.GITHUB_EVENT_HEADER: str`（新增；常數 `"x-github-event"`）
  - `ingress.GITHUB_DELIVERY_HEADER: str`（新增；常數 `"x-github-delivery"`）
  - `ingress.verify_github_signature(secret: str, body: bytes, signature_header: str | None) -> bool`

- [ ] **步驟 1：寫測試**

`tests/unit/test_ingress_signature.py`：

```python
"""Phase 10：GitHub webhook 驗簽（接入來源事件 Rule 1、Rule 2）。"""

import hashlib
import hmac

from training_kb.ingress import GITHUB_SIGNATURE_HEADER, verify_github_signature

SECRET = "It's a Secret to Everybody"
BODY = b'{"action":"opened","issue":{"number":17}}'


def sign(secret: str, body: bytes) -> str:
    """照 GitHub 官方文件的方式算出簽名 header 的值。"""
    digest = hmac.new(secret.encode("utf-8"), msg=body, digestmod=hashlib.sha256).hexdigest()
    return "sha256=" + digest


def test_header_name_is_lowercase():
    # Lambda Function URL 會把 header 名稱轉成小寫，所以常數也用小寫。
    assert GITHUB_SIGNATURE_HEADER == "x-hub-signature-256"


def test_valid_signature_passes():
    assert verify_github_signature(SECRET, BODY, sign(SECRET, BODY)) is True


def test_missing_signature_is_rejected():
    assert verify_github_signature(SECRET, BODY, None) is False
    assert verify_github_signature(SECRET, BODY, "") is False


def test_wrong_secret_is_rejected():
    assert verify_github_signature(SECRET, BODY, sign("wrong-secret", BODY)) is False


def test_one_changed_byte_in_body_is_rejected():
    tampered = BODY.replace(b'"number":17', b'"number":18')
    assert verify_github_signature(SECRET, BODY, sign(SECRET, tampered)) is False


def test_signature_without_prefix_is_rejected():
    bare_hex = hmac.new(SECRET.encode("utf-8"), msg=BODY, digestmod=hashlib.sha256).hexdigest()
    assert verify_github_signature(SECRET, BODY, bare_hex) is False


def test_sha1_signature_is_rejected():
    # GitHub 舊的 X-Hub-Signature 用 SHA-1，本專案只接受 SHA-256。
    digest = hmac.new(SECRET.encode("utf-8"), msg=BODY, digestmod=hashlib.sha1).hexdigest()
    assert verify_github_signature(SECRET, BODY, "sha1=" + digest) is False


def test_uppercase_hex_is_rejected():
    # GitHub 送的一定是小寫十六進位；大小寫不同就當作不符，不做寬鬆處理。
    assert verify_github_signature(SECRET, BODY, sign(SECRET, BODY).upper()) is False


def test_empty_secret_is_rejected():
    # 沒有設定 secret 時一律拒絕，避免把「忘了設定」變成「任何人都能送」。
    assert verify_github_signature("", BODY, sign("", BODY)) is False


def test_empty_body_with_correct_signature_passes():
    assert verify_github_signature(SECRET, b"", sign(SECRET, b"")) is True
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：`uv run pytest tests/unit/test_ingress_signature.py -v`

預期：FAIL，錯誤訊息是 `ModuleNotFoundError: No module named 'training_kb.ingress'`。因為檔案還不存在。

- [ ] **步驟 3：寫最少的程式讓測試通過**

`src/training_kb/ingress.py`（新檔案）：

```python
"""接入層：驗簽、欄位驗證、識別碼編碼、事件去重與啟動流程。

這個模組是系統的大門。它不呼叫 AI、不產生教學內容，
只負責「確認身分 -> 檢查資料 -> 保存 -> 啟動 -> 記帳」。
對應設計文件 §7.1、§14.1、§14.2、§14.3。
"""

from __future__ import annotations

import hashlib
import hmac

#: Lambda Function URL 會把 header 名稱轉成小寫，所以這裡一律用小寫。
GITHUB_SIGNATURE_HEADER = "x-hub-signature-256"
GITHUB_EVENT_HEADER = "x-github-event"
GITHUB_DELIVERY_HEADER = "x-github-delivery"

_SIGNATURE_PREFIX = "sha256="


def verify_github_signature(secret: str, body: bytes, signature_header: str | None) -> bool:
    """用 HMAC-SHA256 驗證 GitHub webhook 的簽名。

    參數：
      secret            -- webhook 設定的密鑰，只從環境變數讀（設計文件 §17.2）。
      body              -- 原始 request body，一個位元組都不能改動。
      signature_header  -- x-hub-signature-256 的值，格式是 "sha256=<64 個十六進位字元>"。

    做法完全照 GitHub 官方文件：用密鑰對原始 body 算 HMAC-SHA256，
    前面接上 "sha256="，再用 hmac.compare_digest 做固定時間比較。
    用 == 比較會因為「比到第幾個字元才不同」而洩漏資訊。
    """
    if not secret or not signature_header:
        return False
    if not signature_header.startswith(_SIGNATURE_PREFIX):
        return False
    digest = hmac.new(secret.encode("utf-8"), msg=body, digestmod=hashlib.sha256).hexdigest()
    expected = _SIGNATURE_PREFIX + digest
    return hmac.compare_digest(expected, signature_header)
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：`uv run pytest tests/unit/test_ingress_signature.py -v`

預期：PASS（10 passed）。

- [ ] **步驟 5：commit**

```bash
git add src/training_kb/ingress.py tests/unit/test_ingress_signature.py
git commit -m "feat(ingress): GitHub webhook HMAC-SHA256 驗簽"
```

---

### Task 2：把 GitHub 的來源資訊編成穩定 ID

**目的**：D02 要求正規化物件的 `id` 是全域唯一且有 `t_`／`r_` 前綴；GitHub 的 Issue 編號本身只在單一 repo 內唯一，所以要加上 owner 與 repo。

**檔案**：
- 修改：`src/training_kb/ingress.py`
- 測試：`tests/unit/test_ingress_ids.py`

**介面**：
- 消費：`training_kb.errors.IngressError`（Phase 01）
- 產出：
  - `ingress.github_ticket_id(owner: str, repo: str, issue_number: int) -> str`
  - `ingress.github_release_id(owner: str, repo: str, pr_number: int, k: int) -> str`

> **本計劃選擇（對應 O6「來源完整契約」）**：
> - GitHub Issue → `t_gh-<owner>-<repo>-<issue_number>`
> - GitHub PR → `r_gh-<owner>-<repo>-pr<pr_number>-<k>`，`k` 從 1 開始，是同一個 PR 拆出的第幾個子 Release（F14：一則改版含多個 Feature 變更時拆成多個子 Release，共用同一個父來源事件 ID）。
> - `owner`、`repo` 一律轉小寫，並把 `0-9a-z._-` 以外的字元換成 `-`，讓同一個來源永遠算出同一個 ID。
>
> 設計文件 §18 的 O6 尚未定案，這裡列出的是本計劃的選擇；**不能宣稱「公開 PR 接入已能端到端運作」**，那要等 Phase 12 用真實 fixture 驗證過。

- [ ] **步驟 1：寫測試**

`tests/unit/test_ingress_ids.py`：

```python
"""Phase 10：來源識別碼的確定性編碼（O6 本計劃選擇）。"""

import pytest

from training_kb.errors import IngressError
from training_kb.ingress import github_release_id, github_ticket_id


def test_github_ticket_id_format():
    assert github_ticket_id("acme", "notes", 17) == "t_gh-acme-notes-17"


def test_github_release_id_format():
    assert github_release_id("acme", "notes", 42, 1) == "r_gh-acme-notes-pr42-1"
    assert github_release_id("acme", "notes", 42, 2) == "r_gh-acme-notes-pr42-2"


def test_ids_are_deterministic():
    assert github_ticket_id("ACME", "Notes", 17) == github_ticket_id("acme", "notes", 17)


def test_unsafe_characters_become_hyphen():
    assert github_ticket_id("ac me", "no/tes", 17) == "t_gh-ac-me-no-tes-17"


def test_empty_owner_or_repo_is_rejected():
    with pytest.raises(IngressError) as err:
        github_ticket_id("", "notes", 17)
    assert err.value.fields == ["owner"]

    with pytest.raises(IngressError) as err:
        github_ticket_id("acme", "   ", 17)
    assert err.value.fields == ["repo"]


def test_non_positive_number_is_rejected():
    with pytest.raises(IngressError) as err:
        github_ticket_id("acme", "notes", 0)
    assert err.value.fields == ["issue_number"]

    with pytest.raises(IngressError) as err:
        github_release_id("acme", "notes", 42, 0)
    assert err.value.fields == ["k"]


def test_boolean_is_not_a_valid_number():
    # Python 的 True 也是 int，要特別擋掉，否則 True 會被當成 1。
    with pytest.raises(IngressError):
        github_ticket_id("acme", "notes", True)
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：`uv run pytest tests/unit/test_ingress_ids.py -v`

預期：FAIL，`ImportError: cannot import name 'github_ticket_id' from 'training_kb.ingress'`。

- [ ] **步驟 3：寫最少的程式讓測試通過**

在 `ingress.py` 的 import 區補上：

```python
import re
from typing import Any

from .errors import IngressError
```

在 `verify_github_signature` 之後加入：

```python
#: 識別碼裡允許出現的字元；其餘一律換成 "-"，確保同一來源永遠算出同一個 ID。
_ID_UNSAFE = re.compile(r"[^0-9a-z._-]+")


def _github_part(value: str, field: str) -> str:
    part = _ID_UNSAFE.sub("-", str(value).strip().lower()).strip("-")
    if not part:
        raise IngressError("GitHub 識別碼欄位不可為空", fields=[field])
    return part


def _positive_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise IngressError("GitHub 編號必須是大於 0 的整數", fields=[field])
    return value


def github_ticket_id(owner: str, repo: str, issue_number: int) -> str:
    """GitHub Issue -> Ticket 的裸 ID（O6 本計劃選擇）。

    例：owner="acme"、repo="notes"、issue_number=17 -> "t_gh-acme-notes-17"
    Issue 編號只在單一 repo 內唯一，所以一定要帶上 owner 與 repo 才能全域唯一（D02）。
    """
    return (
        f"t_gh-{_github_part(owner, 'owner')}"
        f"-{_github_part(repo, 'repo')}"
        f"-{_positive_int(issue_number, 'issue_number')}"
    )


def github_release_id(owner: str, repo: str, pr_number: int, k: int) -> str:
    """GitHub PR -> Release 的裸 ID（O6 本計劃選擇）。

    例：owner="acme"、repo="notes"、pr_number=42、k=1 -> "r_gh-acme-notes-pr42-1"
    k 是同一個 PR 拆出的第幾個子 Release，從 1 開始（F14）。
    """
    return (
        f"r_gh-{_github_part(owner, 'owner')}"
        f"-{_github_part(repo, 'repo')}"
        f"-pr{_positive_int(pr_number, 'pr_number')}"
        f"-{_positive_int(k, 'k')}"
    )
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：`uv run pytest tests/unit/test_ingress_ids.py -v`

預期：PASS（7 passed）。

- [ ] **步驟 5：commit**

```bash
git add src/training_kb/ingress.py tests/unit/test_ingress_ids.py
git commit -m "feat(ingress): GitHub 來源識別碼的確定性編碼"
```

---

### Task 3：驗證 Ticket 欄位

**目的**：落實「接入來源事件」Rule 21、22、24、25：必填、ID 前綴、枚舉合法。

**檔案**：
- 修改：`src/training_kb/ingress.py`
- 測試：`tests/unit/test_ingress_validate.py`

**介面**：
- 消費：`models.Ticket`、`models.TicketSource`（Phase 02）、`clock.parse_iso`、`clock.to_iso`（Phase 01）、`errors.IngressError`
- 產出：
  - `ingress.TICKET_REQUIRED_FIELDS: tuple[str, ...]`（新增）
  - `ingress.validate_ticket(data: dict) -> Ticket`

> 失敗時拋 `IngressError`，`fields` 列出所有不合法的欄位名稱。這就是規格裡的 `Then 操作失敗`；設計文件 §7.1 明說「這裡**不新增 HTTP 錯誤碼契約**」，所以不要自創 `error_code`。
>
> `embedding` 與 `cluster_id` 在接入時**不接受輸入**，由 Ticket Analysis 流程補入（D09 補充說明）。

- [ ] **步驟 1：寫測試**

`tests/unit/test_ingress_validate.py`：

```python
"""Phase 10：接入欄位驗證（必填、枚舉、ID 前綴）。"""

import pytest

from training_kb.errors import IngressError
from training_kb.ingress import validate_ticket
from training_kb.models import TicketSource


def valid_ticket_data() -> dict:
    return {
        "id": "t_gh-acme-notes-17",
        "source": "github_issue",
        "text": "會前摘要在哪裡開啟？",
        "author": "u_01",
        "ts": "2026-08-02T09:00:00Z",
        "project_id": "demo-project",
    }


def test_valid_ticket_passes():
    ticket = validate_ticket(valid_ticket_data())
    assert ticket.id == "t_gh-acme-notes-17"
    assert ticket.source is TicketSource.github_issue
    assert ticket.author == "u_01"
    assert ticket.ts == "2026-08-02T09:00:00Z"
    # 接入時不帶分析結果
    assert ticket.embedding is None
    assert ticket.cluster_id is None
    assert ticket.feature_ids == []


def test_missing_required_fields_lists_every_missing_name():
    data = valid_ticket_data()
    del data["author"]
    data["project_id"] = "   "
    with pytest.raises(IngressError) as err:
        validate_ticket(data)
    assert err.value.fields == ["author", "project_id"]


def test_illegal_source_enum_is_rejected():
    data = valid_ticket_data()
    data["source"] = "slack"
    with pytest.raises(IngressError) as err:
        validate_ticket(data)
    assert err.value.fields == ["source"]


def test_id_without_t_prefix_is_rejected():
    data = valid_ticket_data()
    data["id"] = "gh-acme-notes-17"
    with pytest.raises(IngressError) as err:
        validate_ticket(data)
    assert err.value.fields == ["id"]


def test_unparseable_ts_is_rejected():
    data = valid_ticket_data()
    data["ts"] = "2026/08/02 09:00"
    with pytest.raises(IngressError) as err:
        validate_ticket(data)
    assert err.value.fields == ["ts"]


def test_ts_is_normalised_to_z_form():
    data = valid_ticket_data()
    data["ts"] = "2026-08-02T09:00:00+00:00"
    assert validate_ticket(data).ts == "2026-08-02T09:00:00Z"


def test_multiple_invalid_fields_are_all_reported():
    data = valid_ticket_data()
    data["id"] = "x_1"
    data["source"] = "slack"
    data["ts"] = "not-a-time"
    with pytest.raises(IngressError) as err:
        validate_ticket(data)
    assert err.value.fields == ["id", "source", "ts"]


def test_analysis_fields_in_input_are_ignored():
    data = valid_ticket_data()
    data["cluster_id"] = "c99"
    data["embedding"] = [0.1] * 1024
    ticket = validate_ticket(data)
    assert ticket.cluster_id is None
    assert ticket.embedding is None
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：`uv run pytest tests/unit/test_ingress_validate.py -v`

預期：FAIL，`ImportError: cannot import name 'validate_ticket' from 'training_kb.ingress'`。

- [ ] **步驟 3：寫最少的程式讓測試通過**

在 `ingress.py` 的 import 區補上：

```python
from datetime import datetime

from .clock import parse_iso, to_iso
from .models import Ticket, TicketSource
```

加入下列內容：

```python
#: 接入 Ticket 時必填的欄位（接入來源事件 Rule 22、D09）。
TICKET_REQUIRED_FIELDS = ("id", "source", "text", "author", "ts", "project_id")


def _blank(value: Any) -> bool:
    """None、空字串、只有空白都算「沒有值」；數字 0 不算。"""
    return value is None or (isinstance(value, str) and not value.strip())


def _unique(names: list[str]) -> list[str]:
    """去掉重複但保持原本順序，讓錯誤訊息穩定可測。"""
    seen: set[str] = set()
    result: list[str] = []
    for name in names:
        if name not in seen:
            seen.add(name)
            result.append(name)
    return result


def _normalised_ts(value: Any) -> str | None:
    """把時間字串正規化成 "2026-08-02T09:00:00Z"；不能解析就回 None。"""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return to_iso(parse_iso(value.strip()))
    except (ValueError, TypeError):
        return None


def _missing_fields(data: dict, required: tuple[str, ...]) -> list[str]:
    return [name for name in required if _blank(data.get(name))]


def validate_ticket(data: dict) -> Ticket:
    """檢查並正規化一筆 Ticket；不合法就拋 IngressError 並列出欄位。

    對應「接入來源事件」Rule 21、22、24、25。
    embedding 與 cluster_id 由 Ticket Analysis 補入，接入時不接受輸入。
    """
    missing = _missing_fields(data, TICKET_REQUIRED_FIELDS)
    if missing:
        raise IngressError("Ticket 缺少必填欄位", fields=missing)

    invalid: list[str] = []
    ticket_id = str(data["id"]).strip()
    if not ticket_id.startswith("t_"):
        invalid.append("id")

    source = str(data["source"]).strip()
    if source not in {item.value for item in TicketSource}:
        invalid.append("source")

    ts = _normalised_ts(data["ts"])
    if ts is None:
        invalid.append("ts")

    if invalid:
        raise IngressError("Ticket 欄位不合法", fields=_unique(invalid))

    return Ticket(
        id=ticket_id,
        source=TicketSource(source),
        text=str(data["text"]),
        author=str(data["author"]).strip(),
        ts=ts,
        project_id=str(data["project_id"]).strip(),
    )
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：`uv run pytest tests/unit/test_ingress_validate.py -v`

預期：PASS（8 passed）。

- [ ] **步驟 5：commit**

```bash
git add src/training_kb/ingress.py tests/unit/test_ingress_validate.py
git commit -m "feat(ingress): Ticket 欄位與枚舉驗證"
```

---

### Task 4：驗證 Release 欄位

**目的**：落實 D10 與「接入來源事件」Rule 23：接入時就完成功能與種類解析；`renamed` 另外必填 `old_name`、`new_name`。

**檔案**：
- 修改：`src/training_kb/ingress.py`
- 測試：`tests/unit/test_ingress_validate.py`

**介面**：
- 消費：`models.Release`、`models.ReleaseSource`、`models.ReleaseKind`（Phase 02）
- 產出：
  - `ingress.RELEASE_REQUIRED_FIELDS: tuple[str, ...]`（新增）
  - `ingress.validate_release(data: dict) -> Release`

> **本階段選擇**：`Release.source_event_id`（父來源事件 ID）在 D10 的必填清單裡沒有，但模型需要它。輸入沒有提供時，**填入這筆 Release 自己的 `id`**，代表「這個改版沒有被拆成多個子 Release」。拆成多筆時由呼叫端（Phase 12 的 adapter）填入共同的父事件 ID（F14）。這個補值只是內部表示，**不宣稱它來自上游**。

- [ ] **步驟 1：寫測試**

把下面這段加到 `tests/unit/test_ingress_validate.py`：

```python
from training_kb.ingress import validate_release
from training_kb.models import ReleaseKind, ReleaseSource


def valid_release_data() -> dict:
    return {
        "id": "r_gh-acme-notes-pr42-1",
        "source": "github_pr",
        "source_event_id": "gh-acme-notes-pr42",
        "feature": "Prepare",
        "kind": "renamed",
        "old_name": "Meeting Summary",
        "new_name": "Prepare",
        "evidence": "PR #42 renamed the Meeting Summary tab to Prepare",
        "ts": "2026-08-19T00:00:00Z",
    }


def test_valid_release_passes():
    release = validate_release(valid_release_data())
    assert release.id == "r_gh-acme-notes-pr42-1"
    assert release.source is ReleaseSource.github_pr
    assert release.kind is ReleaseKind.renamed
    assert release.old_name == "Meeting Summary"
    assert release.new_name == "Prepare"
    assert release.source_event_id == "gh-acme-notes-pr42"


def test_renamed_requires_old_and_new_name():
    data = valid_release_data()
    del data["old_name"]
    data["new_name"] = ""
    with pytest.raises(IngressError) as err:
        validate_release(data)
    assert err.value.fields == ["old_name", "new_name"]


def test_changed_allows_empty_names():
    data = valid_release_data()
    data["kind"] = "changed"
    data.pop("old_name")
    data.pop("new_name")
    release = validate_release(data)
    assert release.kind is ReleaseKind.changed
    assert release.old_name is None
    assert release.new_name is None


def test_removed_allows_empty_names():
    data = valid_release_data()
    data["kind"] = "removed"
    data["old_name"] = ""
    data["new_name"] = ""
    assert validate_release(data).kind is ReleaseKind.removed


def test_illegal_kind_is_rejected():
    data = valid_release_data()
    data["kind"] = "deprecated"
    with pytest.raises(IngressError) as err:
        validate_release(data)
    assert err.value.fields == ["kind"]


def test_id_without_r_prefix_is_rejected():
    data = valid_release_data()
    data["id"] = "t_gh-acme-notes-pr42-1"
    with pytest.raises(IngressError) as err:
        validate_release(data)
    assert err.value.fields == ["id"]


def test_missing_release_required_fields():
    data = valid_release_data()
    del data["feature"]
    del data["evidence"]
    with pytest.raises(IngressError) as err:
        validate_release(data)
    assert err.value.fields == ["feature", "evidence"]


def test_source_event_id_defaults_to_own_id():
    data = valid_release_data()
    del data["source_event_id"]
    assert validate_release(data).source_event_id == "r_gh-acme-notes-pr42-1"
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：`uv run pytest tests/unit/test_ingress_validate.py -k release -v`

預期：FAIL，`ImportError: cannot import name 'validate_release' from 'training_kb.ingress'`。

- [ ] **步驟 3：寫最少的程式讓測試通過**

在 `ingress.py` 的 import 區補上 `Release, ReleaseKind, ReleaseSource`：

```python
from .models import Release, ReleaseKind, ReleaseSource, Ticket, TicketSource
```

加入：

```python
#: 接入 Release 時必填的欄位（D10、接入來源事件 Rule 23）。
RELEASE_REQUIRED_FIELDS = ("id", "source", "feature", "kind", "evidence", "ts")


def _optional_text(value: Any) -> str | None:
    return None if _blank(value) else str(value).strip()


def validate_release(data: dict) -> Release:
    """檢查並正規化一筆 Release；不合法就拋 IngressError 並列出欄位。

    D10：id、source、feature、kind、evidence、ts 必填；
    kind 是 renamed 時另外必填 old_name 與 new_name，其他 kind 允許名稱為空。
    """
    missing = _missing_fields(data, RELEASE_REQUIRED_FIELDS)
    if missing:
        raise IngressError("Release 缺少必填欄位", fields=missing)

    invalid: list[str] = []
    release_id = str(data["id"]).strip()
    if not release_id.startswith("r_"):
        invalid.append("id")

    source = str(data["source"]).strip()
    if source not in {item.value for item in ReleaseSource}:
        invalid.append("source")

    kind = str(data["kind"]).strip()
    if kind not in {item.value for item in ReleaseKind}:
        invalid.append("kind")

    ts = _normalised_ts(data["ts"])
    if ts is None:
        invalid.append("ts")

    old_name = _optional_text(data.get("old_name"))
    new_name = _optional_text(data.get("new_name"))
    if kind == ReleaseKind.renamed.value:
        if old_name is None:
            invalid.append("old_name")
        if new_name is None:
            invalid.append("new_name")

    if invalid:
        raise IngressError("Release 欄位不合法", fields=_unique(invalid))

    # 沒有提供父事件 ID 時，視為「這個改版沒有被拆成多個子 Release」，填自己的 ID。
    source_event_id = _optional_text(data.get("source_event_id")) or release_id

    return Release(
        id=release_id,
        source=ReleaseSource(source),
        source_event_id=source_event_id,
        feature=str(data["feature"]).strip(),
        kind=ReleaseKind(kind),
        old_name=old_name,
        new_name=new_name,
        evidence=str(data["evidence"]),
        ts=ts,
    )
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：`uv run pytest tests/unit/test_ingress_validate.py -v`

預期：PASS（16 passed；Ticket 8 個、Release 8 個）。

- [ ] **步驟 5：commit**

```bash
git add src/training_kb/ingress.py tests/unit/test_ingress_validate.py
git commit -m "feat(ingress): Release 欄位驗證與 renamed 名稱檢查"
```

---

### Task 5：操作 ID 與 Step Functions 執行名稱

**目的**：讓同一個事件永遠算出同一個操作 ID 與執行名稱，這是所有去重的基礎。

**檔案**：
- 修改：`src/training_kb/ingress.py`
- 測試：`tests/unit/test_ingress_operation.py`

**介面**：
- 消費：`errors.IngressError`
- 產出：
  - `ingress.OPERATION_PREFIX: dict[str, str]`（新增）
  - `ingress.operation_id_for(kind: str, bare_id: str) -> str`
  - `ingress.execution_name(operation_id: str) -> str`

> `StartExecution` 的 `name` 限制（AWS 官方文件）：長度 1..80、不得包含空白、`< > { } [ ]`、`? *`，以及 `" # % \ ^ | ~ \` $ & , ; : /` 與控制字元。因為 `:` 被禁止，所以把 `:` 換成 `_`。超過 80 字元時保留前 63 字元再接上原始 ID 的 SHA-256 前 16 碼，這樣既不超長、又保持**同一個操作 ID 永遠得到同一個名稱**。

- [ ] **步驟 1：寫測試**

`tests/unit/test_ingress_operation.py`：

```python
"""Phase 10：操作 ID 與 Step Functions 執行名稱。"""

import pytest

from training_kb.errors import IngressError
from training_kb.ingress import execution_name, operation_id_for


def test_operation_id_for_each_kind():
    assert operation_id_for("ticket", "t_881") == "ingest:ticket:t_881"
    assert operation_id_for("release", "r_42") == "ingest:release:r_42"
    assert operation_id_for("feedback", "f_12") == "import:feedback:f_12"
    assert operation_id_for("view", "9f2c1a") == "import:view:9f2c1a"
    assert operation_id_for("delivery", "72d3162e-cc78") == "import:delivery:72d3162e-cc78"


def test_unknown_kind_is_rejected():
    with pytest.raises(IngressError) as err:
        operation_id_for("tutorial", "prepare-meeting")
    assert err.value.fields == ["kind"]


def test_blank_bare_id_is_rejected():
    with pytest.raises(IngressError) as err:
        operation_id_for("ticket", "   ")
    assert err.value.fields == ["id"]


def test_execution_name_replaces_colon():
    assert execution_name("ingest:ticket:t_881") == "ingest_ticket_t_881"
    assert ":" not in execution_name("import:delivery:72d3162e-cc78")


def test_execution_name_is_deterministic_and_within_80_chars():
    long_id = operation_id_for("ticket", "t_" + "a" * 200)
    name = execution_name(long_id)
    assert len(name) == 80
    assert name == execution_name(long_id)
    assert ":" not in name


def test_different_long_ids_get_different_names():
    first = execution_name(operation_id_for("ticket", "t_" + "a" * 200 + "1"))
    second = execution_name(operation_id_for("ticket", "t_" + "a" * 200 + "2"))
    assert first != second


def test_execution_name_drops_characters_step_functions_forbids():
    name = execution_name("ingest:ticket:t_a b/c#d")
    assert all(ch not in name for ch in ' /#"%\\^|~$&,;')
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：`uv run pytest tests/unit/test_ingress_operation.py -v`

預期：FAIL，`ImportError: cannot import name 'operation_id_for' from 'training_kb.ingress'`。

- [ ] **步驟 3：寫最少的程式讓測試通過**

在 `ingress.py` 加入：

```python
#: 每一種接入資料對應的操作紀錄前綴。
#: ingest 代表會啟動 Step Functions；import 代表固定保存路徑或輔助紀錄。
OPERATION_PREFIX = {
    "ticket": "ingest",
    "release": "ingest",
    "feedback": "import",
    "view": "import",
    "delivery": "import",
}

#: Step Functions 執行名稱允許的字元；其餘一律換成 "_"。
_EXECUTION_NAME_UNSAFE = re.compile(r"[^0-9A-Za-z._-]")
_EXECUTION_NAME_MAX = 80


def operation_id_for(kind: str, bare_id: str) -> str:
    """算出一個事件的操作 ID，例如 "ingest:ticket:t_881"。

    同一個事件不管送幾次，算出來一定一樣，這是去重的基礎（F09）。
    """
    prefix = OPERATION_PREFIX.get(kind)
    if prefix is None:
        raise IngressError(f"不支援的接入種類：{kind}", fields=["kind"])
    if _blank(bare_id):
        raise IngressError("識別碼不可為空", fields=["id"])
    return f"{prefix}:{kind}:{str(bare_id).strip()}"


def execution_name(operation_id: str) -> str:
    """把操作 ID 轉成 Step Functions 的執行名稱。

    ':' 是 StartExecution 明令禁止的字元，換成 '_'；
    其餘不合法字元也換成 '_'；長度上限 80。
    太長時保留前 63 字元再接原始 ID 的 sha256 前 16 碼，
    確保「同一個操作 ID -> 同一個名稱」，Step Functions 的冪等才有意義。
    """
    safe = _EXECUTION_NAME_UNSAFE.sub("_", operation_id.replace(":", "_"))
    if len(safe) <= _EXECUTION_NAME_MAX:
        return safe
    digest = hashlib.sha256(operation_id.encode("utf-8")).hexdigest()[:16]
    return f"{safe[:63]}_{digest}"
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：`uv run pytest tests/unit/test_ingress_operation.py -v`

預期：PASS（7 passed）。

- [ ] **步驟 5：commit**

```bash
git add src/training_kb/ingress.py tests/unit/test_ingress_operation.py
git commit -m "feat(ingress): 操作 ID 與 Step Functions 執行名稱"
```

---

### Task 6：PipelineStarter 介面、假實作與 AcceptResult

**目的**：把「啟動 Step Functions」這件事抽象成一個介面，測試時換成假的，就不用連 AWS。

**檔案**：
- 修改：`src/training_kb/ingress.py`
- 測試：`tests/unit/test_ingress_starter.py`

**介面**：
- 消費：`errors.TransientError`、`errors.IngressError`
- 產出：
  - `ingress.PipelineStarter`（Protocol）
  - `ingress.FakePipelineStarter`（新增；測試與本機 Demo 用）
  - `ingress.AcceptResult`（dataclass）
  - `ingress.failed_result(error: IngressError) -> AcceptResult`（新增；把驗證錯誤轉成回傳值，給 Phase 14 的 handler 用）

- [ ] **步驟 1：寫測試**

`tests/unit/test_ingress_starter.py`：

```python
"""Phase 10：流程啟動介面與回傳值。"""

import pytest

from training_kb.errors import IngressError, TransientError
from training_kb.ingress import AcceptResult, FakePipelineStarter, failed_result


def test_fake_starter_returns_arn_and_records_the_call():
    starter = FakePipelineStarter()
    arn = starter.start("ticket-analysis", "ingest_ticket_t_881", {"ticket_id": "t_881"})

    assert arn.endswith(":ticket-analysis:ingest_ticket_t_881")
    assert starter.attempts == [
        ("ticket-analysis", "ingest_ticket_t_881", {"ticket_id": "t_881"})
    ]


def test_fake_starter_is_idempotent_on_same_name():
    """模擬 STANDARD 工作流程：同名同 input 且仍在執行 -> 回同一個 ARN。"""
    starter = FakePipelineStarter()
    first = starter.start("ticket-analysis", "same-name", {"ticket_id": "t_881"})
    second = starter.start("ticket-analysis", "same-name", {"ticket_id": "t_881"})
    assert first == second
    assert len(starter.attempts) == 2


def test_fake_starter_can_be_told_to_fail():
    starter = FakePipelineStarter(fail_times=1)
    with pytest.raises(TransientError):
        starter.start("ticket-analysis", "n1", {})
    # 第二次就會成功，用來測「啟動失敗後重送」
    assert starter.start("ticket-analysis", "n1", {}).endswith(":n1")


def test_accept_result_fields():
    result = AcceptResult(status="accepted", object_id="t_881",
                          execution_arn="arn:aws:states:...", message="已接受並啟動流程",
                          invalid_fields=[])
    assert result.status == "accepted"
    assert result.invalid_fields == []


def test_failed_result_carries_invalid_fields():
    result = failed_result(IngressError("Ticket 欄位不合法", fields=["id", "source"]))
    assert result.status == "failed"
    assert result.object_id is None
    assert result.execution_arn is None
    assert result.invalid_fields == ["id", "source"]
    assert "不合法" in result.message
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：`uv run pytest tests/unit/test_ingress_starter.py -v`

預期：FAIL，`ImportError: cannot import name 'AcceptResult' from 'training_kb.ingress'`。

- [ ] **步驟 3：寫最少的程式讓測試通過**

在 `ingress.py` 的 import 區補上：

```python
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from .errors import IngressError, TransientError
```

加入：

```python
class PipelineStarter(Protocol):
    """啟動一條 Step Functions 流程。

    正式實作在 Phase 14（handlers 與 infra）用 boto3 的 stepfunctions client；
    測試與本機 Demo 用下面的 FakePipelineStarter。
    """

    def start(self, pipeline: str, execution_name: str, input: dict) -> str:
        """回傳 executionArn。

        STANDARD 工作流程對「同名、同 input、仍在執行」是冪等的，會回同一個結果；
        已結束或 input 不同會得到 ExecutionAlreadyExists（400），
        實作要依操作紀錄判斷該怎麼處理，不能把例外當成功。
        """
        ...


class FakePipelineStarter:
    """測試用的假 Step Functions，行為刻意模仿 STANDARD 的冪等特性。"""

    def __init__(self, *, fail_times: int = 0) -> None:
        self.fail_times = fail_times
        self.attempts: list[tuple[str, str, dict]] = []
        self.started: dict[str, str] = {}

    def start(self, pipeline: str, execution_name: str, input: dict) -> str:
        self.attempts.append((pipeline, execution_name, dict(input)))
        if self.fail_times > 0:
            self.fail_times -= 1
            raise TransientError("模擬 Step Functions 啟動失敗")
        arn = self.started.get(execution_name)
        if arn is None:
            arn = (
                "arn:aws:states:us-east-1:000000000000:execution:"
                f"{pipeline}:{execution_name}"
            )
            self.started[execution_name] = arn
        return arn


@dataclass
class AcceptResult:
    """接入結果。

    accepted  -- 這次真的保存了物件並啟動流程（含「沿用未完成紀錄後補上啟動」）。
    duplicate -- 這個事件已經處理完成，沒有再保存、也沒有再啟動（F09）。
    failed    -- 沒有完成；invalid_fields 列出不合法欄位（規格的「操作失敗」）。
    """

    status: Literal["accepted", "duplicate", "failed"]
    object_id: str | None
    execution_arn: str | None
    message: str
    invalid_fields: list[str]


def failed_result(error: IngressError) -> AcceptResult:
    """把欄位驗證錯誤轉成回傳值，讓入口能在時限內給來源明確答案。"""
    return AcceptResult(
        status="failed",
        object_id=None,
        execution_arn=None,
        message=str(error),
        invalid_fields=list(error.fields),
    )
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：`uv run pytest tests/unit/test_ingress_starter.py -v`

預期：PASS（5 passed）。

- [ ] **步驟 5：commit**

```bash
git add src/training_kb/ingress.py tests/unit/test_ingress_starter.py
git commit -m "feat(ingress): 流程啟動介面與接入回傳值"
```

---

### Task 7：accept_ticket 的正常路徑

**目的**：把「保存 Ticket → 啟動 ticket-analysis → 記錄已啟動」串起來（「接入來源事件」Rule 26）。

**檔案**：
- 修改：`src/training_kb/ingress.py`
- 測試：`tests/integration/test_ingress_accept.py`

**介面**：
- 消費：`Repository.begin_operation`／`load_operation`／`update_operation`（Phase 03）、`Repository.put_ticket`／`get_ticket`／`list_tickets`（Phase 09 Task 3）、`PipelineStarter`（Task 6）、`operation_id_for`、`execution_name`（Task 5）
- 產出：
  - `ingress.PIPELINE_OF_KIND: dict[str, str]`（新增）
  - `ingress.STAGE_RECEIVED`、`ingress.STAGE_SAVED`、`ingress.STAGE_STARTED`（新增；操作紀錄的三個階段）
  - `ingress.accept_ticket(repo, starter, ticket, *, delivery_id, now) -> AcceptResult`

- [ ] **步驟 1：寫測試**

`tests/integration/test_ingress_accept.py`：

```python
"""Phase 10：保存物件、啟動流程與事件去重（用 Phase 09 的 moto repo fixture）。"""

from datetime import UTC, datetime

from training_kb.ingress import (
    STAGE_SAVED,
    STAGE_STARTED,
    FakePipelineStarter,
    accept_ticket,
)
from training_kb.models import Ticket, TicketSource

NOW = datetime(2026, 8, 2, 9, 0, 0, tzinfo=UTC)


def make_ticket() -> Ticket:
    return Ticket(
        id="t_gh-acme-notes-17",
        source=TicketSource.github_issue,
        text="會前摘要在哪裡開啟？",
        author="u_01",
        ts="2026-08-02T09:00:00Z",
        project_id="demo-project",
    )


def test_accept_ticket_saves_object_and_starts_pipeline(repo):
    starter = FakePipelineStarter()

    result = accept_ticket(repo, starter, make_ticket(), delivery_id="d-1", now=NOW)

    assert result.status == "accepted"
    assert result.object_id == "t_gh-acme-notes-17"
    assert result.execution_arn.endswith("ingest_ticket_t_gh-acme-notes-17")
    assert result.invalid_fields == []

    # 物件真的存進去了
    saved = repo.get_ticket("t_gh-acme-notes-17")
    assert saved is not None
    assert saved.author == "u_01"

    # 流程真的啟動了，而且帶的是 ID 不是全文
    assert starter.attempts == [(
        "ticket-analysis",
        "ingest_ticket_t_gh-acme-notes-17",
        {"ticket_id": "t_gh-acme-notes-17",
         "operation_id": "ingest:ticket:t_gh-acme-notes-17"},
    )]

    # 操作紀錄停在「已啟動」
    record = repo.load_operation("ingest:ticket:t_gh-acme-notes-17")
    assert record["stage"] == STAGE_STARTED
    assert record["object_id"] == "t_gh-acme-notes-17"
    assert record["execution_arn"] == result.execution_arn
    assert record["pipeline"] == "ticket-analysis"


def test_accept_ticket_records_the_delivery(repo):
    starter = FakePipelineStarter()
    accept_ticket(repo, starter, make_ticket(), delivery_id="72d3162e", now=NOW)

    delivery = repo.load_operation("import:delivery:72d3162e")
    assert delivery["operation_id"] == "ingest:ticket:t_gh-acme-notes-17"


def test_accept_ticket_without_delivery_id_still_works(repo):
    starter = FakePipelineStarter()
    result = accept_ticket(repo, starter, make_ticket(), delivery_id=None, now=NOW)
    assert result.status == "accepted"
    assert repo.load_operation("ingest:ticket:t_gh-acme-notes-17")["stage"] == STAGE_STARTED


def test_start_failure_keeps_object_and_reports_failed(repo):
    starter = FakePipelineStarter(fail_times=1)

    result = accept_ticket(repo, starter, make_ticket(), delivery_id="d-1", now=NOW)

    assert result.status == "failed"
    assert result.object_id == "t_gh-acme-notes-17"
    assert result.execution_arn is None
    # 物件已保存，紀錄停在 saved，代表「保存後但啟動前失敗」
    assert repo.get_ticket("t_gh-acme-notes-17") is not None
    record = repo.load_operation("ingest:ticket:t_gh-acme-notes-17")
    assert record["stage"] == STAGE_SAVED
    assert "last_error" in record
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：`uv run pytest tests/integration/test_ingress_accept.py -v`

預期：FAIL，`ImportError: cannot import name 'STAGE_SAVED' from 'training_kb.ingress'`。

- [ ] **步驟 3：寫最少的程式讓測試通過**

在 `ingress.py` 加入：

```python
#: 每一種事件對應的流程邏輯名稱（設計文件 §9.3）。
#: 真正的 state machine 名稱是 "training-kb-<pipeline>"，由 Phase 14 組出來。
PIPELINE_OF_KIND = {"ticket": "ticket-analysis", "release": "release-update"}

#: 操作紀錄的三個階段。
STAGE_RECEIVED = "received"   # 已建立紀錄，物件還沒存
STAGE_SAVED = "saved"         # 物件已存，流程還沒啟動
STAGE_STARTED = "started"     # 流程已啟動，本次邏輯處理完成


def accept_ticket(
    repo,
    starter: PipelineStarter,
    ticket: Ticket,
    *,
    delivery_id: str | None,
    now: datetime,
) -> AcceptResult:
    """保存 Ticket 並啟動 Ticket Analysis（接入來源事件 Rule 26）。

    傳進來的 ticket 必須已經通過 validate_ticket；這裡不再做欄位檢查。
    """
    return _accept(
        repo,
        starter,
        kind="ticket",
        bare_id=ticket.id,
        save=lambda: repo.put_ticket(ticket),
        pipeline_input={"ticket_id": ticket.id},
        delivery_id=delivery_id,
        now=now,
    )


def _accept(
    repo,
    starter: PipelineStarter,
    *,
    kind: str,
    bare_id: str,
    save,
    pipeline_input: dict,
    delivery_id: str | None,
    now: datetime,
) -> AcceptResult:
    """Ticket 與 Release 共用的接入流程。"""
    pipeline = PIPELINE_OF_KIND[kind]
    operation_id = operation_id_for(kind, bare_id)
    now_iso = to_iso(now)

    if delivery_id:
        repo.begin_operation(
            operation_id_for("delivery", delivery_id),
            {
                "kind": kind,
                "bare_id": bare_id,
                "operation_id": operation_id,
                "received_at": now_iso,
            },
        )

    repo.begin_operation(
        operation_id,
        {
            "kind": kind,
            "bare_id": bare_id,
            "operation_id": operation_id,
            "pipeline": pipeline,
            "stage": STAGE_RECEIVED,
            "object_id": None,
            "execution_arn": None,
            "created_at": now_iso,
            "updated_at": now_iso,
        },
    )

    save()
    repo.update_operation(
        operation_id,
        {"stage": STAGE_SAVED, "object_id": bare_id, "updated_at": now_iso},
    )

    name = execution_name(operation_id)
    payload = {**pipeline_input, "operation_id": operation_id}
    try:
        execution_arn = starter.start(pipeline, name, payload)
    except Exception as exc:  # 啟動失敗不能拋出去：入口必須在時限內給來源答案
        repo.update_operation(
            operation_id,
            {
                "stage": STAGE_SAVED,
                "last_error": f"{type(exc).__name__}: {exc}",
                "updated_at": now_iso,
            },
        )
        return AcceptResult(
            status="failed",
            object_id=bare_id,
            execution_arn=None,
            message=f"物件已保存，但流程啟動失敗；重送同一事件會沿用這筆紀錄續作：{exc}",
            invalid_fields=[],
        )

    repo.update_operation(
        operation_id,
        {"stage": STAGE_STARTED, "execution_arn": execution_arn, "updated_at": now_iso},
    )
    return AcceptResult(
        status="accepted",
        object_id=bare_id,
        execution_arn=execution_arn,
        message="已接受並啟動流程",
        invalid_fields=[],
    )
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：`uv run pytest tests/integration/test_ingress_accept.py -v`

預期：PASS（4 passed）。

- [ ] **步驟 5：commit**

```bash
git add src/training_kb/ingress.py tests/integration/test_ingress_accept.py
git commit -m "feat(ingress): accept_ticket 保存物件並啟動流程"
```

---

### Task 8：重送去重與「保存後但啟動前失敗」的續作

**目的**：落實 F09 與「接入來源事件」Rule 30：同一個事件重送只處理一次；未完成的執行要能沿用。

**檔案**：
- 修改：`src/training_kb/ingress.py`
- 測試：`tests/integration/test_ingress_accept.py`

**介面**：
- 消費：`Repository.load_operation`（Phase 03）
- 產出：`ingress._accept` 補上去重與續作分支（對外介面不變）

> 三條路（見第 5.3 節的狀態圖）：
> - 紀錄不存在 → 正常處理，回 `accepted`。
> - 紀錄的 `stage` 是 `started` → 回 `duplicate`，**不保存、不啟動**。
> - 紀錄的 `stage` 是 `received` 或 `saved` → 沿用同一個版號與同一個執行名稱把它做完，回 `accepted`，訊息註明「沿用既有操作紀錄」。
>
> 設計文件 §14.2：「一次邏輯操作的 ID、正規化結果、模型輸出與分配版號一旦保存，儲存階段重試就重用它們。」

- [ ] **步驟 1：寫測試**

加到 `tests/integration/test_ingress_accept.py`：

```python
def test_resending_a_finished_event_is_duplicate(repo):
    starter = FakePipelineStarter()
    first = accept_ticket(repo, starter, make_ticket(), delivery_id="d-1", now=NOW)

    second = accept_ticket(repo, starter, make_ticket(), delivery_id="d-2", now=NOW)

    assert first.status == "accepted"
    assert second.status == "duplicate"
    assert second.object_id == "t_gh-acme-notes-17"
    assert second.execution_arn == first.execution_arn   # 回傳既有結果
    assert len(starter.attempts) == 1                    # 沒有再啟動一次


def test_resending_the_same_delivery_is_duplicate(repo):
    starter = FakePipelineStarter()
    accept_ticket(repo, starter, make_ticket(), delivery_id="72d3162e", now=NOW)

    again = accept_ticket(repo, starter, make_ticket(), delivery_id="72d3162e", now=NOW)

    assert again.status == "duplicate"
    assert len(starter.attempts) == 1


def test_resend_after_start_failure_resumes_the_same_operation(repo):
    """保存後但啟動前失敗 -> 重送時沿用，不遺失也不重複建版（設計文件 §15）。"""
    failing = FakePipelineStarter(fail_times=1)
    first = accept_ticket(repo, failing, make_ticket(), delivery_id="d-1", now=NOW)
    assert first.status == "failed"

    second = accept_ticket(repo, failing, make_ticket(), delivery_id="d-1", now=NOW)

    assert second.status == "accepted"
    assert "沿用" in second.message
    assert second.execution_arn is not None
    # 執行名稱與第一次相同，Step Functions 的冪等才能發揮作用
    assert failing.attempts[0][1] == failing.attempts[1][1]
    # 只有一筆 Ticket，沒有變成兩筆
    assert [t.id for t in repo.list_tickets("demo-project")] == ["t_gh-acme-notes-17"]
    assert repo.load_operation("ingest:ticket:t_gh-acme-notes-17")["stage"] == STAGE_STARTED


def test_duplicate_does_not_touch_the_object(repo):
    starter = FakePipelineStarter()
    accept_ticket(repo, starter, make_ticket(), delivery_id="d-1", now=NOW)

    changed = make_ticket()
    changed.text = "被竄改的內容"
    result = accept_ticket(repo, starter, changed, delivery_id="d-2", now=NOW)

    assert result.status == "duplicate"
    assert repo.get_ticket("t_gh-acme-notes-17").text == "會前摘要在哪裡開啟？"
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：`uv run pytest tests/integration/test_ingress_accept.py -k "duplicate or resume or resend" -v`

預期：FAIL。`test_resending_a_finished_event_is_duplicate` 會在 `assert second.status == "duplicate"` 這一行失敗，實際拿到 `'accepted'`，因為目前的 `_accept` 每次都會重新保存並啟動。

- [ ] **步驟 3：寫最少的程式讓測試通過**

把 `_accept` 裡「建立事件紀錄」到「保存物件」之間的那一段，換成下面這一版（其餘不變）：

```python
    if delivery_id:
        delivery_operation_id = operation_id_for("delivery", delivery_id)
        created = repo.begin_operation(
            delivery_operation_id,
            {
                "kind": kind,
                "bare_id": bare_id,
                "operation_id": operation_id,
                "received_at": now_iso,
            },
        )
        if not created:
            # 同一次投遞重送：沿用它當初對應的操作 ID，不另開一條處理鏈。
            previous = repo.load_operation(delivery_operation_id) or {}
            operation_id = str(previous.get("operation_id") or operation_id)

    record = repo.load_operation(operation_id)
    if record is None:
        created = repo.begin_operation(
            operation_id,
            {
                "kind": kind,
                "bare_id": bare_id,
                "operation_id": operation_id,
                "pipeline": pipeline,
                "stage": STAGE_RECEIVED,
                "object_id": None,
                "execution_arn": None,
                "created_at": now_iso,
                "updated_at": now_iso,
            },
        )
        if not created:
            # 同一瞬間有另一個重送搶先建立，改用它的紀錄繼續判斷。
            record = repo.load_operation(operation_id)

    if record is not None and record.get("stage") == STAGE_STARTED:
        # F09：同一事件只接受一次邏輯處理，重送回傳既有結果。
        return AcceptResult(
            status="duplicate",
            object_id=record.get("object_id") or bare_id,
            execution_arn=record.get("execution_arn"),
            message="這個事件已經處理過，回傳既有結果；沒有再保存物件也沒有再啟動流程",
            invalid_fields=[],
        )

    resumed = record is not None
```

再把最後成功回傳的那一段換成：

```python
    repo.update_operation(
        operation_id,
        {"stage": STAGE_STARTED, "execution_arn": execution_arn, "updated_at": now_iso},
    )
    message = "沿用既有操作紀錄，補上流程啟動" if resumed else "已接受並啟動流程"
    return AcceptResult(
        status="accepted",
        object_id=bare_id,
        execution_arn=execution_arn,
        message=message,
        invalid_fields=[],
    )
```

改完之後，`_accept` 的完整順序是：

```text
1. delivery 紀錄（有 delivery_id 才做）-> 決定要用哪一個 operation_id
2. 事件紀錄：沒有就建立；已經是 started 就回 duplicate
3. 保存物件（同 ID 重寫是冪等的）-> stage = saved
4. 啟動流程（同名同 input 會拿到同一個 ARN）-> 失敗就回 failed 並保留 saved
5. stage = started -> 回 accepted
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：`uv run pytest tests/integration/test_ingress_accept.py -v`

預期：PASS（8 passed）。

- [ ] **步驟 5：commit**

```bash
git add src/training_kb/ingress.py tests/integration/test_ingress_accept.py
git commit -m "feat(ingress): 事件重送去重與未完成執行的續作"
```

---

### Task 9：accept_release 與 handle_manual_ticket 的簽名

**目的**：補上 Release 的接入（「接入來源事件」Rule 27），並先把手動匯入的函式簽名定下來，讓 Phase 12 直接填內容。

**檔案**：
- 修改：`src/training_kb/ingress.py`
- 測試：`tests/integration/test_ingress_accept.py`

**介面**：
- 消費：`Repository.put_release`（Phase 09）、`_accept`（Task 7、8）
- 產出：
  - `ingress.accept_release(repo, starter, release, *, delivery_id, now) -> AcceptResult`
  - `ingress.handle_manual_ticket(repo, rote, starter, payload, source, *, now) -> AcceptResult`（本階段只有簽名與明確的未實作錯誤，Phase 12 填內容）

> `handle_manual_ticket` 要走 Rote 三層（設計文件 §7.1、F08：Discord、email、changelog 由受控匯入提供），而 Rote 的 `normalize` 要到 Phase 12 才完成。本階段先把簽名定死並丟出**帶有明確說明的 `NotImplementedError`**，這樣 Phase 14 的 handler 可以先接上，而不會誤以為它已經能用。

- [ ] **步驟 1：寫測試**

加到 `tests/integration/test_ingress_accept.py`：

```python
import pytest

from training_kb.ingress import accept_release, handle_manual_ticket
from training_kb.models import Release, ReleaseKind, ReleaseSource


def make_release() -> Release:
    return Release(
        id="r_gh-acme-notes-pr42-1",
        source=ReleaseSource.github_pr,
        source_event_id="gh-acme-notes-pr42",
        feature="Prepare",
        kind=ReleaseKind.renamed,
        old_name="Meeting Summary",
        new_name="Prepare",
        evidence="PR #42 renamed the Meeting Summary tab to Prepare",
        ts="2026-08-19T00:00:00Z",
    )


def test_accept_release_starts_release_update(repo):
    starter = FakePipelineStarter()

    result = accept_release(repo, starter, make_release(), delivery_id="d-9", now=NOW)

    assert result.status == "accepted"
    assert result.object_id == "r_gh-acme-notes-pr42-1"
    assert repo.get_release("r_gh-acme-notes-pr42-1") is not None
    assert starter.attempts == [(
        "release-update",
        "ingest_release_r_gh-acme-notes-pr42-1",
        {"release_id": "r_gh-acme-notes-pr42-1",
         "operation_id": "ingest:release:r_gh-acme-notes-pr42-1"},
    )]


def test_release_and_ticket_use_separate_operation_records(repo):
    starter = FakePipelineStarter()
    accept_ticket(repo, starter, make_ticket(), delivery_id=None, now=NOW)
    accept_release(repo, starter, make_release(), delivery_id=None, now=NOW)

    assert repo.load_operation("ingest:ticket:t_gh-acme-notes-17")["pipeline"] == "ticket-analysis"
    assert repo.load_operation("ingest:release:r_gh-acme-notes-pr42-1")["pipeline"] == "release-update"


def test_resending_a_release_is_duplicate(repo):
    starter = FakePipelineStarter()
    accept_release(repo, starter, make_release(), delivery_id="d-9", now=NOW)
    again = accept_release(repo, starter, make_release(), delivery_id="d-10", now=NOW)

    assert again.status == "duplicate"
    assert len(starter.attempts) == 1


def test_handle_manual_ticket_is_not_ready_before_phase_12(repo):
    starter = FakePipelineStarter()
    with pytest.raises(NotImplementedError) as err:
        handle_manual_ticket(repo, None, starter, {"text": "問題"},
                             TicketSource.discord, now=NOW)
    assert "Phase 12" in str(err.value)
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：`uv run pytest tests/integration/test_ingress_accept.py -k "release or manual" -v`

預期：FAIL，`ImportError: cannot import name 'accept_release' from 'training_kb.ingress'`。

- [ ] **步驟 3：寫最少的程式讓測試通過**

在 `ingress.py` 的 import 區補上 `Release` 已經有了，再加入：

```python
def accept_release(
    repo,
    starter: PipelineStarter,
    release: Release,
    *,
    delivery_id: str | None,
    now: datetime,
) -> AcceptResult:
    """保存 Release 並啟動 Release Note Update（接入來源事件 Rule 27）。

    傳進來的 release 必須已經通過 validate_release；這裡不再做欄位檢查。
    """
    return _accept(
        repo,
        starter,
        kind="release",
        bare_id=release.id,
        save=lambda: repo.put_release(release),
        pipeline_input={"release_id": release.id},
        delivery_id=delivery_id,
        now=now,
    )


def handle_manual_ticket(
    repo,
    rote,
    starter: PipelineStarter,
    payload: dict,
    source: TicketSource,
    *,
    now: datetime,
) -> AcceptResult:
    """手動匯入的工單（Discord、email）也要走 Rote 三層正規化。

    完整實作在 Phase 12（12-Phase12-Rote-Agent選工具與重放執行.md）：
      1. 用 payload 與 source 組出 RawEvent。
      2. 呼叫 rote.normalize(event, operation_id=..., now=...) 取得 Ticket。
      3. 呼叫 accept_ticket 保存並啟動流程。
      4. 成功後呼叫 rote.commit_success 更新 PROC（接入來源事件 Rule 14）。
    在那之前，受控匯入請走 validate_ticket + accept_ticket 這條固定路徑。
    """
    raise NotImplementedError(
        "handle_manual_ticket 需要 Rote 的三層正規化，於 Phase 12 完成；"
        "目前請改用 validate_ticket 搭配 accept_ticket。"
    )
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：

```bash
uv run pytest tests/unit/test_ingress_signature.py tests/unit/test_ingress_ids.py tests/unit/test_ingress_validate.py tests/unit/test_ingress_operation.py tests/unit/test_ingress_starter.py tests/integration/test_ingress_accept.py -v
uv run pytest -q
uv run ruff check .
```

預期：全部 PASS，ruff 顯示 `All checks passed!`。

- [ ] **步驟 5：commit**

```bash
git add src/training_kb/ingress.py tests/integration/test_ingress_accept.py
git commit -m "feat(ingress): accept_release 與手動匯入入口簽名"
```

---

## 7. 完成檢查清單

- [ ] `uv run pytest -q` 全部通過。
- [ ] `uv run ruff check .` 沒有錯誤。
- [ ] `ingress.py` 具備下列名稱（用下面的指令確認）：

```bash
uv run python -c "
import training_kb.ingress as i
need = ['verify_github_signature','github_ticket_id','github_release_id','validate_ticket',
        'validate_release','operation_id_for','execution_name',
        'PipelineStarter','FakePipelineStarter',
        'AcceptResult','failed_result','accept_ticket','accept_release','handle_manual_ticket']
print([n for n in need if not hasattr(i, n)] or 'OK')
"
```

預期輸出：`OK`。

- [ ] 手動驗證「有效／無效／缺少簽名」三種情況（設計文件 §15 的「來源與 Rote」列）：

```bash
uv run python - <<'PY'
import hashlib, hmac
from training_kb.ingress import verify_github_signature

secret = "It's a Secret to Everybody"
body = b'{"action":"opened"}'
good = "sha256=" + hmac.new(secret.encode("utf-8"), msg=body, digestmod=hashlib.sha256).hexdigest()

print("有效簽名:", verify_github_signature(secret, body, good))
print("無效簽名:", verify_github_signature(secret, body, "sha256=" + "0" * 64))
print("缺少簽名:", verify_github_signature(secret, body, None))
PY
```

預期輸出：

```text
有效簽名: True
無效簽名: False
缺少簽名: False
```

- [ ] 手動驗證「操作失敗會指出欄位」：

```bash
uv run python -c "
from training_kb.errors import IngressError
from training_kb.ingress import validate_ticket
try:
    validate_ticket({'id': 'x_1', 'source': 'slack', 'text': 'hi', 'author': 'u_01',
                     'ts': 'not-a-time', 'project_id': 'demo-project'})
except IngressError as err:
    print(err.fields)
"
```

預期輸出：`['id', 'source', 'ts']`

- [ ] 對應設計文件第 16 節 S1 切片的檢查：
  - 「一則有效 GitHub 事件正規化」→ `test_valid_ticket_passes` ＋ `test_accept_ticket_saves_object_and_starts_pipeline`。
  - 「缺簽名失敗」→ `test_missing_signature_is_rejected`。
  - 「手動上傳走受控入口」→ `handle_manual_ticket` 已定義並明確標示 Phase 12 完成；Phase 14 才會接上 Lambda。
- [ ] 對應設計文件 §15「接入去重」的檢查：`test_resending_a_finished_event_is_duplicate`、`test_resending_the_same_delivery_is_duplicate`、`test_resend_after_start_failure_resumes_the_same_operation` 三個測試都通過。

---

## 8. 常見錯誤與排除

**1）本機測簽名都對，接上真的 GitHub 就一直失敗**

- 症狀：`verify_github_signature` 在單元測試通過，實際 webhook 全部被拒。
- 原因：多半是拿「解析後又重新序列化」的 JSON 去算簽名。`json.loads` 再 `json.dumps` 會改變空白與鍵順序，算出來的指紋完全不同。
- 解法：從 Lambda 事件取 `event["body"]` 的**原始字串**（若 `isEncodingBase64` 為真要先 base64 解碼）再 `.encode("utf-8")`，整個過程不要碰 `json`。這一段在 Phase 14 實作，但概念現在就要記住。

**2）`AttributeError: 'IngressError' object has no attribute 'fields'`**

- 症狀：`failed_result` 或測試讀 `err.value.fields` 時炸掉。
- 原因：Phase 01 的 `IngressError.__init__` 只呼叫了 `super().__init__(message)`，忘了保存 `fields`。
- 解法：在 `errors.py` 補上 `self.fields = list(fields)`。

**3）數字欄位收到 `True` 竟然通過驗證**

- 症狀：布林值被當成數字 1。
- 原因：Python 的 `bool` 是 `int` 的子類別，`isinstance(True, int)` 是 `True`。
- 解法：所有數字檢查都要先寫 `if isinstance(value, bool): 不合法`。本階段的 `_positive_int()`（Task 2）就是這樣做的；Phase 15 的 `validate_feedback` 檢查 `rating` 時也必須這樣做。

**4）重送測試一直回 `accepted` 而不是 `duplicate`**

- 症狀：Task 8 的測試過不了。
- 原因有兩種：（a）`_accept` 沒有先 `load_operation` 就直接 `begin_operation`；（b）`begin_operation` 沒有真的用條件寫入（已存在也回 True）。
- 解法：先確認 Phase 03 的 `begin_operation` 在 item 已存在時回 `False`（用 `ConditionExpression="attribute_not_exists(PK)"`）。可以用 `uv run pytest tests/integration -k operation -v` 單獨驗。

**5）`ClientError: ExecutionAlreadyExists`（上到真 AWS 之後才會遇到）**

- 症狀：重送時 Step Functions 直接報錯。
- 原因：同名執行已經結束，或 input 有一點點不同（例如多帶了時間戳）。
- 解法：兩件事。第一，`pipeline_input` 只放 ID 與必要的小型判斷結果，**不要放時間或全文**，否則每次 input 都不同。第二，重送時先看操作紀錄：`stage == "started"` 就直接回 `duplicate`，根本不會走到 `start`。設計文件 §14.2 明確禁止「把此例外直接當成功」。

**6）webhook 偶爾逾時，GitHub 標記失敗**

- 症狀：事件有時候沒進來。
- 原因：第三層（Agent 選工具）會呼叫模型，可能吃掉好幾秒。
- 解法：設計文件 §14.3 的做法是「展示前先以受控事件累積成功流程」，讓 Rote 能走第一層重放（0 次模型呼叫）。**不可以**改成「先回 200 再背景處理」。

**7）`TypeError: accept_ticket() takes 3 positional arguments but 5 were given`**

- 症狀：呼叫 `accept_ticket(repo, starter, ticket, "d-1", now)` 就炸。
- 原因：`delivery_id` 與 `now` 是 keyword-only 參數（簽名裡的 `*` 之後）。
- 解法：寫成 `accept_ticket(repo, starter, ticket, delivery_id="d-1", now=now)`。這是全專案的約定：所有「現在時間」一律用 `now=` 明寫，方便測試（共用技術決定：「所有需要『現在』的函式都接受 `now: datetime` 參數以便測試」）。

---

## 9. 這階段不做的事

| 不做的事 | 留給哪一階段 |
|---|---|
| 判斷事件該用哪個 adapter、結構簽名、PROC 計數 | Phase 11（`11-Phase11-Rote-結構簽名與流程重放判定.md`） |
| 真正把 GitHub 的 JSON 轉成 Ticket／Release（adapter 工具、JSONPath、Agent 迴圈） | Phase 12（`12-Phase12-Rote-Agent選工具與重放執行.md`） |
| `handle_manual_ticket` 的實作 | Phase 12 |
| Lambda handler、Function URL、真的 `boto3` Step Functions client、HTTP 狀態碼 | Phase 14（`14-Phase14-StepFunctions與Lambda上線.md`） |
| `validate_feedback`／`validate_view`（Feedback 與瀏覽紀錄的欄位驗證） | Phase 15（`15-Phase15-Feedback與View匯入.md`）Task 2、Task 4。本階段只提供它們會用到的 `operation_id_for("feedback", ...)`／`operation_id_for("view", ...)`。 |
| `import_feedback`／`import_view`（版本存在檢查、退役拒絕、留言分類、View 去重） | Phase 15（`15-Phase15-Feedback與View匯入.md`） |
| 檢查 `category` 是否屬於核定類別表 | Phase 15（需要讀 `CONFIG#categories`） |
| 檢查 `tutorial_version` 是否存在、教學是否已退役 | Phase 15（需要查資料庫） |
| 新增 HTTP 錯誤碼契約 | **不做。** 設計文件 §7.1：「這裡不新增 HTTP 錯誤碼契約。」只回傳 `AcceptResult` 與不合法欄位清單。 |
| STABLE_KEYS 白名單補齊（PR 與手動來源） | Phase 12（O6：以一個真實 Issue、一個 PR 的 fixture 補齊） |

---

## 10. 對照：設計章節與 Rule 編號

`接入來源事件.feature` 共 31 條 Rule，下表列出**本階段負責**的 14 條；其餘屬於 Rote（Phase 11、12）或 Feedback 匯入（Phase 15），列在表格下方供對照。

| Rule 來源檔 | Rule 編號與原文 | 本階段哪個 Task 落實 |
|---|---|---|
| `接入來源事件.feature` | Rule 1「GitHub webhook 必須以 X-Hub-Signature-256 驗簽」 | Task 1 |
| `接入來源事件.feature` | Rule 2「沒有簽名的 GitHub webhook 請求被拒絕」 | Task 1（`signature_header` 為 None 或空字串一律 False） |
| `接入來源事件.feature` | Rule 14「寫回新流程前 Step Functions 必須成功啟動」 | Task 7、8（只有 `stage` 走到 `started` 才算完成；PROC 的更新由 Phase 12 依這個結果決定） |
| `接入來源事件.feature` | Rule 18「Agent 最終仍無法產出合法物件時回傳失敗」 | Task 6（`failed_result` 提供回傳形狀；判斷在 Phase 12） |
| `接入來源事件.feature` | Rule 21「正規化物件必須具有 schema 的必填欄位」 | Task 3、4（Feedback 與 View 的欄位驗證在 Phase 15） |
| `接入來源事件.feature` | Rule 22「Ticket 接入時 id、source、text、author、ts 與 project_id 必填」 | Task 3（`TICKET_REQUIRED_FIELDS`） |
| `接入來源事件.feature` | Rule 23「Release 接入時即完成功能與種類解析」 | Task 4（`feature`、`kind` 必填；renamed 另要求 old_name／new_name） |
| `接入來源事件.feature` | Rule 24「正規化物件的 id 直接使用已全域唯一的上游識別碼」 | Task 2（`t_gh-…`／`r_gh-…` 編碼）、Task 3、4（前綴檢查） |
| `接入來源事件.feature` | Rule 25「正規化物件的枚舉欄位必須使用合法值」 | Task 3、4（`TicketSource`、`ReleaseSource`、`ReleaseKind`） |
| `接入來源事件.feature` | Rule 26「正規化成功的 Ticket 觸發 Ticket Analysis」 | Task 7（`PIPELINE_OF_KIND["ticket"] == "ticket-analysis"`） |
| `接入來源事件.feature` | Rule 27「正規化成功的 Release 觸發 Release Note Update」 | Task 9 |
| `接入來源事件.feature` | Rule 28「正規化成功的 Feedback 寫入 FEEDBACK item」 | 不在本階段：欄位驗證與寫入都在 Phase 15（`15-Phase15-Feedback與View匯入.md`） |
| `接入來源事件.feature` | Rule 29「單筆 Feedback 接入不立即觸發教學改版」 | Task 7（`PIPELINE_OF_KIND` 只有 ticket 與 release，沒有 feedback，所以 Feedback 永遠不會啟動流程） |
| `接入來源事件.feature` | Rule 30「同一正規化事件重送時只處理一次」 | Task 8 |
| `收集教學回饋.feature` | Rule 3「Feedback 的 rating 只能為 1 到 5 的整數」 | 不在本階段：Phase 15 的 `validate_feedback` |
| `收集教學回饋.feature` | Rule 9「Feedback 接入時必須提供穩定使用者 ID」 | 不在本階段：Phase 15 的 `validate_feedback` |

其餘 Rule 的歸屬（不在本階段落實，列出以免遺漏）：

- Rule 3、4、5、6、7、8、9、15、16、19、20、31 → Phase 11（結構簽名、Jaccard、PROC 計數）。
- Rule 10、11、12、13、17 → Phase 12（Agent 選工具、JSONPath、重放執行）。
- `收集教學回饋.feature` Rule 1、2、4、5、6、7、8、10 → Phase 15。

---

## 11. 參考來源

設計文件（`docs/design/training-kb.md`）：

- §7.1 接入：先驗證，再承認處理成功（四種輸入的必填欄位表、Function URL `NONE` 與驗簽、Feedback 與 View 的 `ts` 差異、「不新增 HTTP 錯誤碼契約」）。
- §14.1 各層如何結束（「webhook 無簽名、簽名不符 → Ingress 拒絕，不能先進 Rote 或寫合法 Ticket／Release」；「同一事件／Feedback 重送 → 取得既有結果或沿用未完成邏輯操作」）。
- §14.2 重試不是重新抽一次文字（`StartExecution` 的冪等限制、`ExecutionAlreadyExists` 不能當成功）。
- §14.3 執行參數（webhook 8 秒、不先回成功再背景處理、每次請求記錄操作與節點）。
- §15 測試與驗收設計：「來源與 Rote」與「接入去重」兩列。
- §16 交付切片 S1：「一則有效 GitHub 事件正規化；缺簽名失敗；手動上傳走受控入口。」
- §17.1 已查證的平台用法（Step Functions 冪等「不能取代永久事件去重」、Lambda URL `NONE` 仍需 resource policy）。
- §17.2 最小必要的安全處理（webhook secret 只由執行環境提供）。
- §18 待確認事項 O2（操作紀錄與接受順序）、O6（來源完整契約）。
- §19.1 D02、D09、D10、D11、D12、D13、D14、D23；§19.2 F07、F08、F09、F14、F41、F51。
- §20.7 接入來源事件的 31 條 Rule 對照；§20.9 收集教學回饋的 10 條 Rule 對照。

規格檔：

- `docs/spec/features/接入來源事件.feature`（31 條 Rule，含 STABLE_KEYS、必填欄位與重送的補充說明）。
- `docs/spec/features/收集教學回饋.feature`（Rule 3、Rule 9）。
- `docs/spec/.clarify/resolved/features/接入來源事件_同一正規化事件重送時是否再次觸發_pipeline.md`（F09，答案 A）。

外部官方文件（2026-09-13 查證）：

- GitHub 驗證 webhook 投遞：<https://docs.github.com/en/webhooks/using-webhooks/validating-webhook-deliveries> — header 是 `x-hub-signature-256`，格式 `"sha256=" + hash_object.hexdigest()`，用原始 body 計算，並以 `hmac.compare_digest` 做固定時間比較。
- GitHub 處理失敗的 webhook 投遞：<https://docs.github.com/en/webhooks/using-webhooks/handling-failed-webhook-deliveries>
- AWS Step Functions `StartExecution` API：<https://docs.aws.amazon.com/step-functions/latest/apireference/API_StartExecution.html> — 「`StartExecution` is idempotent for `STANDARD` workflows… If the execution is closed or if the input is different, it returns a `400 ExecutionAlreadyExists` error. You can reuse the name 90 days after it closes.」；`name` 長度 1..80、禁用字元含 `:`。
- AWS Step Functions 錯誤處理：<https://docs.aws.amazon.com/step-functions/latest/dg/concepts-error-handling.html>
- AWS Lambda Function URL 權限：<https://docs.aws.amazon.com/lambda/latest/dg/urls-auth.html>
- Python 標準庫 `hmac`（`compare_digest`）：<https://docs.python.org/3/library/hmac.html>
