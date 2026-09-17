# Phase 11：Rote-結構簽名與流程重放判定

| 項目 | 內容 |
|---|---|
| 上一階段 | Phase 10：Ingress-驗簽驗證與去重（`10-Phase10-Ingress-驗簽驗證與去重.md`） |
| 下一階段 | Phase 12：Rote-Agent 選工具與重放執行（`12-Phase12-Rote-Agent選工具與重放執行.md`） |
| 對應設計文件章節 | §7.2、§9.1、§14.1、D19、D20、F02–F05、F53（`docs/design/training-kb.md`） |
| 對應交付切片 | S1（設計文件第 16 節） |
| 預估時間 | 約 4 小時 |
| 做完會得到 | `rote.py` 的純判斷邏輯：把事件的「形狀」算成一個簽名、比對兩組欄位的重疊度、決定某個已學會的流程能不能重放，以及成功／失敗之後計數該怎麼變。 |

---

## 1. 這階段做完會得到什麼

「Rote」是**死記硬背**的意思。它要解決的問題是：

> 同一個來源（例如 GitHub 的 Issue webhook）送來的事件，長相幾乎都一樣。第一次要用模型去猜「這個 JSON 要怎麼變成 Ticket」，但第二次、第三次就不應該再花一次模型呼叫——直接把上次成功的做法重放一遍就好。

這一階段做的是**判斷的部分**（純函式，不碰網路、不呼叫 AI）：

| 問題 | 這階段做出來的函式 |
|---|---|
| 這個事件的「形狀」是什麼？ | `structure_signature`、`meaningful_header_names`、`payload_keys` |
| 這種來源有哪些欄位算是固定必備的？ | `STABLE_KEYS` |
| 兩組欄位有多像？ | `jaccard` |
| 這個已學會的流程可以直接重放嗎？ | `replayable` |
| 有好幾個差不多的流程，要用哪一個？ | `pick_layer2` |
| 重放成功／失敗之後，計數要怎麼改？ | `on_replay_success`、`on_replay_failure`、`on_new_success` |
| 這些流程存在哪、怎麼讀寫？ | `Repository.get_proc`／`put_proc`／`list_procs` |

**這一階段不會真的執行任何 adapter，也不會呼叫 Bedrock。** 把判斷與執行分開的好處是：判斷全部可以用純 Python 單元測試把邊界值（0.7999 對 0.8、成功 2 次對 3 次）釘死，不需要 AWS 也不需要模型。

執行的部分（工具註冊、JSONPath、Agent 工具迴圈、真的把 JSON 轉成 Ticket）是 Phase 12。

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

Phase 10 已經做好「確認事件是真的、欄位是對的、同一個事件只處理一次」。這一格要做的是「這個事件我以前見過嗎？以前怎麼處理的？」。

---

## 3. 開始前檢查

- [ ] **1）確認前一階段完成**

執行：

```bash
cd ~/AWS-Hackathon
uv run pytest -q
```

預期：全部 passed（含 Phase 09、Phase 10 的測試）。

- [ ] **2）確認 PROC 相關的模型與枚舉存在（Phase 02 建立）**

執行：

```bash
uv run python -c "
from training_kb.models import ProvenWorkflow, ProcStep, ProcStatus
print([s.value for s in ProcStatus])
proc = ProvenWorkflow(signature='abc123', domain='github.com', adapter_type='ticket',
                      keys=['action', 'issue'], steps=[ProcStep(tool='parse_github_issue', args={'raw': '\$.issue'})],
                      success_count=3, fail_count=0, status=ProcStatus.active, last_used=None)
print(proc.signature, proc.success_count, proc.status)
"
```

預期輸出：

```text
['active', 'retired']
abc123 3 active
```

- [ ] **3）確認門檻設定存在（Phase 01 建立）**

執行：

```bash
uv run python -c "
from training_kb.config import Thresholds
t = Thresholds()
print(t.jaccard_replay, t.proc_min_success, t.proc_max_consecutive_fail)
"
```

預期輸出：`0.8 3 3`

若數字不同，請先回 Phase 01 對照簡報 §6.1 的預設值改正。**這三個數字是本階段所有判斷的依據，不可以在這裡另外寫死。**

- [ ] **4）確認 PROC 的鍵函式存在（Phase 02 建立）**

執行：

```bash
uv run python -c "from training_kb import keys; print(keys.proc_pk('9f2c1a3b4d5e6f70'))"
```

預期輸出：`PROC#9f2c1a3b4d5e6f70`

- [ ] **5）確認 Phase 09 的轉換工具存在**

執行：

```bash
uv run python -c "
from training_kb.repository import entity_attrs, Repository
print('OK' if hasattr(Repository, 'scan_entity') else 'MISSING')
"
```

預期輸出：`OK`。若出現 `ImportError`，代表 Phase 09 的 Task 2 還沒做。

---

## 4. 名詞小抄

| 名詞 | 白話解釋 | 在本階段哪裡用到 |
|---|---|---|
| Rote | 「死記硬背」。本專案指接入層的三層處理：先比對記住的做法，都不中才動用模型。 | 全部 |
| PROC（PROVEN_WORKFLOW） | 「已驗證的流程」。一筆資料記著：這種形狀的事件，用哪幾個工具、按什麼順序處理，成功過幾次、連續失敗幾次。 | Task 7、8 |
| adapter | 把某一種來源格式轉成我們的資料格式的小工具，例如 `parse_github_issue`。 | 第 5.1 節（實作在 Phase 12） |
| 結構簽名（structure signature） | 事件「長相」的指紋。只看網域、header 名稱、必備欄位名稱，**完全不看值**。 | Task 3 |
| SHA-1 | 一種雜湊演算法。這裡只拿來當索引用，**不是安全用途**，不能代替 webhook 驗簽。 | Task 3 |
| `shape` | 算簽名之前組出來的那個字典：`{"domain": ..., "headers": [...], "keys": [...]}`。 | Task 3 |
| STABLE_KEYS | 每一種「來源＋事件類型」固定必備的最上層欄位清單（F02）。GitHub Issue 是 `action, issue, repository, sender`。 | Task 1 |
| 白名單 header | 只有 `x-github-`、`x-discord-`、`x-zendesk-` 開頭的 header 名稱會進入簽名。 | Task 2 |
| Jaccard 係數 | 兩個集合的相似度：交集大小除以聯集大小。全部一樣是 1.0，完全不重疊是 0.0。 | Task 4 |
| 第一層／第二層／第三層 | 第一層＝簽名完全相同；第二層＝同來源且欄位 Jaccard ≥ 0.8；第三層＝都不中，交給 Agent。 | 第 5.1 節 |
| `success_count` | 這個流程完整成功過幾次。要 ≥ 3 才能被重放（F03、F05）。 | Task 5、7 |
| `fail_count` | **連續**重放失敗幾次。成功一次就歸零；連續 3 次就退役（D20）。 | Task 7 |
| `last_used` | 最近一次成功重放或成功寫回的時間。第二層平手時用來挑最近成功的那個（F04）。 | Task 6、7 |
| retired（退役） | 這個流程停用了，下次接入視同沒命中（Rule 20）。**不會自動復活**（F53）。 | Task 5、7 |
| D19 | 設計文件第 19.1 節的資料決策編號：「來源網域與 adapter 類型共同構成範圍。」 | Task 6、8 |
| D20 | 設計文件第 19.1 節的資料決策編號：「`fail_count` 代表連續失敗；成功重放後歸零，達到 3 才退役。」 | Task 7 |
| F53 | 設計文件第 19.2 節的功能決策編號：「退役簽名保持停用，由人工核定新的序列後再明確重置流程。」 | Task 7 |

---

## 5. 設計說明

### 5.1 三層流程：能不用模型就不用

這是設計文件 §7.2 的核心圖：

```text
              Ticket / Release 原始事件
                        |
                        v
      +-----------------------------------+
      | 算出結構簽名 signature             |   <- 本階段 Task 3
      +-----------------------------------+
                        |
                        v
  (1) PROC#<signature> 存在，而且 active 且 success_count >= 3 ?
                        |                                  <- 本階段 Task 5
         是 |                          | 否
            v                          v
      重放 adapter 程序      (2) 同 domain + adapter_type 的其他流程中，
      （0 次模型呼叫）           欄位 Jaccard >= 0.8 且同樣可重放？
            |                                              <- 本階段 Task 4、6
            |                  是 |                | 否
            |                     v                v
            |               重放 adapter 程序   (3) Agent 選 adapter
            |                     |                （會呼叫 Bedrock）
            |                     |                       |
            +---------+-----------+                       |
                      v                                   v
              正規化 + validate                      validate 通過
                      |                                   |
                 失敗 | 成功                              |
                      |                                   |
        當次回退到 Agent（第 3 層）                        |
                      |                                   |
                      +-------------+---------------------+
                                    v
                      保存物件 + 成功啟動 Step Functions   <- Phase 10 做的
                                    |
                                    v
                        才記成功、更新 PROC 計數           <- 本階段 Task 7
```

四個不能搞錯的地方：

1. **前兩層的門檻一樣**（F03）：`status == active` **且** `success_count >= 3`。第二層不會因為「很像」就放寬。
2. **重放成功不代表可以記帳**。設計文件 §7.2：「保存新程序前，最後一個工具必須是已通過的 `validate`，**且 Step Functions 已成功啟動**；只完成欄位轉換不算一次成功。」所以 `on_replay_success` 這些函式是由 Phase 10 的接入結果決定要不要呼叫，不是 Rote 自己決定。
3. **重放失敗就當次退回第三層**（Rule 17），不是整個事件失敗。
4. **第三層才會呼叫模型**（Rule 11）。前兩層的接入層模型呼叫數是 0。

### 5.2 結構簽名：只看形狀，不看內容

規格檔 `接入來源事件.feature` 把公式寫死了：

```text
shape = {
    "domain":  "github.com",                                 <- 來源網域（缺省為空字串）
    "headers": ["x-github-delivery", "x-github-event", ...], <- 白名單前綴、轉小寫、排序
    "keys":    ["action", "issue", "repository", "sender"],  <- STABLE_KEYS，排序
}

signature = sha1(json.dumps(shape, sort_keys=True).encode()).hexdigest()[:16]
```

```text
  Issue #17 的事件                     Issue #999 的事件
  ------------------                   ------------------
  headers:                             headers:
    X-GitHub-Event: issues               x-github-event: issues
    X-GitHub-Delivery: 72d3162e          x-github-delivery: 9ab77cd1   <- 值不同
    X-Hub-Signature-256: sha256=...      X-Hub-Signature-256: sha256=...
  body:                                body:
    {"action": "opened",                 {"action": "closed",          <- 值不同
     "issue": {"number": 17},             "issue": {"number": 999},    <- 值不同
     "repository": {...},                 "repository": {...},
     "sender": {...}}                     "sender": {...}}
            |                                       |
            v                                       v
  shape = {"domain": "github.com",       shape = {"domain": "github.com",
           "headers": ["x-github-delivery",        "headers": ["x-github-delivery",
                       "x-github-event"],                      "x-github-event"],
           "keys": ["action","issue",              "keys": ["action","issue",
                    "repository","sender"]}                 "repository","sender"]}
            |                                       |
            +------------------+--------------------+
                               v
                    完全一樣 -> 同一個 signature
```

三個重點：

- **`X-Hub-Signature-256` 不會進簽名**：它的前綴是 `x-hub-`，不在白名單裡。這很重要，因為它的值每次都不同，而且它是安全資訊。
- **`x-github-delivery` 的「名稱」會進簽名，「值」不會**。Rule 4：「ID、時間戳與標題等事件值不參與來源簽名。」
- **`keys` 來自 STABLE_KEYS，不是來自這次事件的實際欄位**。如果用實際欄位，GitHub 多送一個 `organization` 就會變成另一個簽名，記憶就失效了。

設計文件 §7.2 也提醒：「此 SHA-1 只是結構索引，**不能代替 webhook 驗簽**。」驗簽在 Phase 10 已經做完了。

### 5.3 PROC 的計數狀態機

D20：「`fail_count` 代表連續失敗；成功重放後歸零，達到 3 才退役。」F05：「首次成功記為 1；同簽名事件再由 Agent 完成相同可泛化序列，每次完整成功才累加。」

```text
                       第三層 Agent 完整成功一次
                                |
                                v
                  +-------------------------------+
                  | 新 PROC                        |
                  | success=1  fail=0  active      |  <- 還不能重放
                  +-------------------------------+
                                |
                     同簽名事件再由 Agent 成功
                                |
                                v
                  +-------------------------------+
                  | success=2  fail=0  active      |  <- 還不能重放
                  +-------------------------------+
                                |
                     同簽名事件再由 Agent 成功
                                |
                                v
                  +===============================+
                  | success=3  fail=0  active      |  <== 從這裡開始可以重放
                  +===============================+
                       |                      ^
          重放失敗      |                      | 重放成功
          fail += 1     |                      | fail = 0、last_used = now
                        v                      |
              +-------------------+            |
              | fail=1  active    |------------+
              +-------------------+
                        | 再失敗
                        v
              +-------------------+
              | fail=2  active    |------------+  成功就回到 fail=0
              +-------------------+
                        | 再失敗（連續第 3 次）
                        v
              +===============================+
              | status = retired              |  <== 下次接入視同未命中（Rule 20）
              +===============================+
                        |
                        | F53：不會自動復活。
                        v
              人工核定新序列後才明確重置
```

「成功穿插失敗不誤退役」就是在測這個：失敗、失敗、**成功**、失敗、失敗 → `fail_count` 只有 2，仍然是 active。如果把 `fail_count` 寫成累積失敗，這個情境就會被錯誤地退役。

### 5.4 第二層要挑哪一個？

F04：「選 Jaccard 最高者，同分時選最近成功使用者；須固定最後的識別碼排序以消除平手。」

```text
  這次事件的 keys = {action, issue, repository, sender}

  候選流程（同 domain=github.com、adapter_type=ticket，且 active 且 success>=3）：

  signature  keys                                          Jaccard  last_used
  ---------  --------------------------------------------  -------  --------------------
  aaa111     {action, issue, repository, sender}            1.00     2026-09-01T00:00:00Z
  bbb222     {action, issue, repository, sender}            1.00     2026-09-10T00:00:00Z  <-- 贏
  ccc333     {action, issue, repository, sender, org}       0.80     2026-09-12T00:00:00Z
  ddd444     {action, issue, repository}                    0.75     2026-09-13T00:00:00Z  (未達門檻)
  eee555     {action, issue, repository, sender}（retired） --       --                     (不可重放)

  排序規則：分數高 -> last_used 新 -> signature 升序
  1) 先看分數：aaa111 與 bbb222 都是 1.00，勝過 ccc333 的 0.80
  2) 分數平手看 last_used：bbb222 的 09-10 比 aaa111 的 09-01 新 -> 選 bbb222
  3) 若 last_used 也一樣，才比 signature 字串，取小的（aaa111）
```

另外兩條硬規定：

- **空集合不當成命中**（設計文件 §7.2）。如果這次事件的 body 不是物件、或沒有任何最上層欄位，`payload_keys` 會回空集合，`pick_layer2` 直接回 `None`。否則 `jaccard(set(), set())` 會變成「除以 0」或被誤判成相似。
- **退役的流程直接跳過**（Rule 20），連算 Jaccard 都不用算。

### 5.5 PROC 存在哪裡

設計文件 §9.1：`PROVEN_WORKFLOW` 的 PK 是 `PROC#<signature>`，SK 是 `META`，**沒有圖譜邊**。

```text
DynamoDB item
+--------------------------------------------------+
| PK  = PROC#9f2c1a3b4d5e6f70                      |
| SK  = META                                       |
| entity = "PROC"                                  |
| signature = "9f2c1a3b4d5e6f70"                   |
| domain = "github.com"          <-+ D19：這兩個欄位 |
| adapter_type = "ticket"        <-+ 合起來是「同寄件者」的範圍 |
| keys = ["action","issue","repository","sender"]  |
| steps = [                                        |
|   {"tool": "parse_github_issue",                 |
|    "args": {"raw": "$.issue"}},                  |
|   {"tool": "to_ticket",                          |
|    "args": {"parsed": "$.steps[0]"}},            |
|   {"tool": "validate",                           |
|    "args": {"obj": "$.steps[1]"}}                |
| ]                                                |
| success_count = 3                                |
| fail_count = 0                                   |
| status = "active"                                |
| last_used = "2026-09-10T00:00:00Z"               |
+--------------------------------------------------+
```

`steps[*].args` 的值是 **JSONPath 字串**，不是真實事件值（設計文件 §7.2：「PROC 的 steps 只包含已註冊工具與 JSONPath 參數，**不含真實事件值**」）。JSONPath 的解析與執行在 Phase 12。

### 5.6 這階段會新增的檔案

```text
src/training_kb/
  rote.py                            <- 本階段的主角（新檔案，只有純邏輯）
  repository.py                      <- 加三個方法：get_proc / put_proc / list_procs
tests/
  unit/
    test_rote_signature.py           <- RawEvent、STABLE_KEYS、header、簽名
    test_rote_similarity.py          <- payload_keys、jaccard、replayable、pick_layer2
    test_rote_counters.py            <- 三個計數轉換函式
    test_rote_acceptance.py          <- 設計文件 §15 的邊界值一次跑齊
  integration/
    test_repository_proc.py          <- PROC 的讀寫（moto）
```

---

## 6. 工作項目

### Task 1：RawEvent 與 STABLE_KEYS 白名單

**目的**：定義「一筆原始事件」長什麼樣，以及每一種來源有哪些固定必備欄位（F02）。

**檔案**：
- 新增：`src/training_kb/rote.py`
- 測試：`tests/unit/test_rote_signature.py`

**介面**：
- 消費：無（純資料結構）
- 產出：
  - `rote.RawEvent`（dataclass：`domain`、`adapter_type`、`event_type`、`headers`、`body`、`received_at`、`delivery_id`）
  - `rote.STABLE_KEYS: dict[tuple[str, str], list[str]]`

> **本階段選擇（對應 O6）**：目前 `STABLE_KEYS` 只填入規格明文給的一組：`("github.com", "issues") -> ["action", "issue", "repository", "sender"]`。
> 規格檔寫得很清楚：「其他來源等手動上傳後再定，**不預先發明 Discord 或 email 清單**。」
> 所以 PR（`pull_request`）與手動來源（Discord、email、changelog）的清單，連同查表用的 `stable_keys_for()`，
> 都由 Phase 12（`12-Phase12-Rote-Agent選工具與重放執行.md`）用真實 fixture 補齊。
> 本階段只提供白名單本體與計算簽名的函式；要算簽名的人自己把清單傳進 `structure_signature`。

- [ ] **步驟 1：寫測試**

`tests/unit/test_rote_signature.py`：

```python
"""Phase 11：事件形狀與結構簽名（接入來源事件 Rule 3、Rule 4）。"""

from training_kb.rote import STABLE_KEYS, RawEvent


def make_event(**overrides) -> RawEvent:
    data = {
        "domain": "github.com",
        "adapter_type": "ticket",
        "event_type": "issues",
        "headers": {
            "X-GitHub-Event": "issues",
            "X-GitHub-Delivery": "72d3162e-cc78-11e3-81ab-4c9367dc0958",
            "X-Hub-Signature-256": "sha256=abc",
            "Content-Type": "application/json",
        },
        "body": {
            "action": "opened",
            "issue": {"number": 17, "title": "會前摘要在哪裡開啟？"},
            "repository": {"full_name": "acme/notes"},
            "sender": {"login": "u_01"},
        },
        "received_at": "2026-08-02T09:00:00Z",
        "delivery_id": "72d3162e-cc78-11e3-81ab-4c9367dc0958",
    }
    data.update(overrides)
    return RawEvent(**data)


def test_raw_event_holds_the_original_pieces():
    event = make_event()
    assert event.domain == "github.com"
    assert event.adapter_type == "ticket"
    assert event.event_type == "issues"
    assert event.body["action"] == "opened"
    assert event.delivery_id.startswith("72d3162e")


def test_github_issues_stable_keys_match_the_spec():
    # 規格檔「接入來源事件」Rule 3 的補充：MVP GitHub 清單為 action、issue、repository、sender。
    assert STABLE_KEYS[("github.com", "issues")] == ["action", "issue", "repository", "sender"]


def test_only_the_github_issue_whitelist_exists_for_now():
    # PR 與其他來源的白名單還沒定，不能拿 Issue 的清單硬套；Phase 12 才補齊。
    assert list(STABLE_KEYS) == [("github.com", "issues")]
    assert ("github.com", "pull_request") not in STABLE_KEYS
    assert ("discord.com", "message") not in STABLE_KEYS


def test_stable_keys_are_sorted_and_unique():
    keys = STABLE_KEYS[("github.com", "issues")]
    assert keys == sorted(keys)
    assert len(keys) == len(set(keys))
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：`uv run pytest tests/unit/test_rote_signature.py -v`

預期：FAIL，`ModuleNotFoundError: No module named 'training_kb.rote'`。

- [ ] **步驟 3：寫最少的程式讓測試通過**

`src/training_kb/rote.py`（新檔案）：

```python
"""Rote：接入層的「死記硬背」。

這個模組分兩半：
  Phase 11（本階段）-- 純判斷邏輯：算事件形狀的簽名、比相似度、決定能不能重放、計數怎麼變。
  Phase 12          -- 執行邏輯：adapter 工具、JSONPath、重放、Agent 工具迴圈。

本階段的所有函式都是純函式：不碰網路、不呼叫模型、不寫資料庫。
對應設計文件 §7.2。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class RawEvent:
    """一筆還沒正規化的原始事件。

    domain       -- 來源網域，例如 "github.com"。取自可信入口設定，不從雜湊反推。
    adapter_type -- "ticket" 或 "release"，決定要轉成哪一種業務物件。
    event_type   -- 來源自己的事件類型，例如 "issues"、"pull_request"。
    headers      -- 原始 HTTP header（大小寫不拘，本模組會自己轉小寫）。
    body         -- 已解析的 JSON（通常是 dict）。
    received_at  -- 收到的時間，ISO 8601 UTC 字串。
    delivery_id  -- 來源自己的投遞 ID（GitHub 是 x-github-delivery），沒有就填 None。
    """

    domain: str
    adapter_type: str
    event_type: str
    headers: dict[str, str]
    body: Any
    received_at: str
    delivery_id: str | None


#: 每一種「來源網域 + 事件類型」固定必備的最上層 payload key（F02）。
#:
#: 目前只有規格明文給的 GitHub Issue 一組。
#: PR 與手動來源（Discord、email、changelog）的清單由 Phase 12 以實際 fixture 補上；
#: 在補上之前不預先發明清單，也不拿 Issue 的清單硬套（規格檔「接入來源事件」Rule 3 的補充）。
STABLE_KEYS: dict[tuple[str, str], list[str]] = {
    ("github.com", "issues"): ["action", "issue", "repository", "sender"],
}
```

Phase 12 會把整個 `STABLE_KEYS` 換成補齊五種來源的版本，並在它後面加上查表用的
`stable_keys_for(domain, event_type) -> list[str]`（查不到就拋 `PermanentError`，
因為那代表這是不支援的事件類型）。本階段不先寫那個函式，避免兩份文件各寫一版。

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：`uv run pytest tests/unit/test_rote_signature.py -v`

預期：PASS（4 passed）。

- [ ] **步驟 5：commit**

```bash
git add src/training_kb/rote.py tests/unit/test_rote_signature.py
git commit -m "feat(rote): 定義原始事件與來源欄位白名單"
```

---

### Task 2：挑出有意義的 header 名稱

**目的**：只讓白名單前綴的 header **名稱**進入簽名，而且轉小寫、排序，讓同樣的事件無論大小寫怎麼寫都得到同一個結果。

**檔案**：
- 修改：`src/training_kb/rote.py`
- 測試：`tests/unit/test_rote_signature.py`

**介面**：
- 消費：無
- 產出：
  - `rote.MEANINGFUL_HEADER_PREFIXES: tuple[str, ...]`（新增）
  - `rote.meaningful_header_names(headers: dict[str, str]) -> list[str]`

- [ ] **步驟 1：寫測試**

加到 `tests/unit/test_rote_signature.py`：

```python
from training_kb.rote import meaningful_header_names


def test_only_whitelisted_prefixes_are_kept():
    names = meaningful_header_names(make_event().headers)
    assert names == ["x-github-delivery", "x-github-event"]
    # 簽名 header 的前綴是 x-hub-，不在白名單；它的值每次都不同，而且是安全資訊
    assert "x-hub-signature-256" not in names
    assert "content-type" not in names


def test_names_are_lowercased_and_sorted():
    headers = {
        "X-GitHub-Event": "issues",
        "x-github-delivery": "abc",
        "X-GITHUB-HOOK-ID": "123",
    }
    assert meaningful_header_names(headers) == [
        "x-github-delivery", "x-github-event", "x-github-hook-id"
    ]


def test_discord_and_zendesk_prefixes_are_also_kept():
    headers = {"X-Discord-Signature": "s", "x-zendesk-webhook-id": "z", "Authorization": "Bearer x"}
    assert meaningful_header_names(headers) == ["x-discord-signature", "x-zendesk-webhook-id"]


def test_duplicate_names_after_lowercasing_are_merged():
    headers = {"X-GitHub-Event": "issues", "x-github-event": "issues"}
    assert meaningful_header_names(headers) == ["x-github-event"]


def test_empty_headers_give_empty_list():
    assert meaningful_header_names({}) == []


def test_header_values_do_not_matter():
    first = meaningful_header_names({"X-GitHub-Delivery": "aaa", "X-GitHub-Event": "issues"})
    second = meaningful_header_names({"X-GitHub-Delivery": "zzz", "X-GitHub-Event": "closed"})
    assert first == second
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：`uv run pytest tests/unit/test_rote_signature.py -k header -v`

預期：FAIL，`ImportError: cannot import name 'meaningful_header_names' from 'training_kb.rote'`。

- [ ] **步驟 3：寫最少的程式讓測試通過**

在 `rote.py` 加入：

```python
#: 只有這些前綴開頭的 header「名稱」會進入結構簽名。
#: 注意 x-hub-signature-256 不在其中：它的前綴是 x-hub-，而且是安全資訊。
MEANINGFUL_HEADER_PREFIXES = ("x-github-", "x-discord-", "x-zendesk-")


def meaningful_header_names(headers: dict[str, str]) -> list[str]:
    """回傳白名單前綴的 header 名稱，全部轉小寫、去重、排序。

    只取「名稱」，完全不取「值」：
    x-github-delivery 的值每次都不同，但名稱是這種事件的固定結構（Rule 4）。
    """
    names = {
        name.strip().lower()
        for name in headers
        if name.strip().lower().startswith(MEANINGFUL_HEADER_PREFIXES)
    }
    return sorted(names)
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：`uv run pytest tests/unit/test_rote_signature.py -v`

預期：PASS（11 passed）。

- [ ] **步驟 5：commit**

```bash
git add src/training_kb/rote.py tests/unit/test_rote_signature.py
git commit -m "feat(rote): 挑出白名單前綴的 header 名稱"
```

---

### Task 3：結構簽名

**目的**：把事件的形狀算成一個 16 字元的字串，同樣形狀永遠得到同一個結果，不同的值不影響結果。

**檔案**：
- 修改：`src/training_kb/rote.py`
- 測試：`tests/unit/test_rote_signature.py`

**介面**：
- 消費：`rote.meaningful_header_names`（Task 2）、`rote.STABLE_KEYS`（Task 1）
- 產出：`rote.structure_signature(domain: str, headers: dict[str, str], stable_keys: list[str]) -> str`

> 公式照抄規格檔（`接入來源事件.feature` Rule 3 的補充說明）：
> `sha1(json.dumps(shape, sort_keys=True).encode()).hexdigest()[:16]`，
> `shape` 由 `domain`（缺省為空字串）、小寫排序的白名單 header 名稱、排序後的 STABLE_KEYS 組成。
> **不要自己改成 SHA-256 或改變 `json.dumps` 的參數**，改了就跟規格對不上。

- [ ] **步驟 1：寫測試**

加到 `tests/unit/test_rote_signature.py`：

```python
import hashlib
import json

from training_kb.rote import structure_signature


def signature_of(event) -> str:
    """測試用的小工具：把一筆事件的白名單查出來再算簽名。

    Phase 12 會提供正式的 stable_keys_for()；本階段直接讀 STABLE_KEYS 就夠了。
    """
    return structure_signature(
        event.domain, event.headers, STABLE_KEYS[(event.domain, event.event_type)]
    )


def test_signature_matches_the_formula_in_the_spec():
    headers = {"X-GitHub-Event": "issues", "X-GitHub-Delivery": "abc"}
    keys = ["action", "issue", "repository", "sender"]

    shape = {
        "domain": "github.com",
        "headers": ["x-github-delivery", "x-github-event"],
        "keys": ["action", "issue", "repository", "sender"],
    }
    expected = hashlib.sha1(json.dumps(shape, sort_keys=True).encode()).hexdigest()[:16]

    assert structure_signature("github.com", headers, keys) == expected
    assert len(structure_signature("github.com", headers, keys)) == 16


def test_event_values_do_not_change_the_signature():
    """設計文件 §15：事件值改變不改結構簽名。"""
    first = make_event()
    second = make_event(
        headers={
            "X-GitHub-Event": "issues",
            "X-GitHub-Delivery": "9ab77cd1-0000-0000-0000-000000000000",
            "X-Hub-Signature-256": "sha256=zzz",
            "Content-Type": "application/json",
        },
        body={
            "action": "closed",
            "issue": {"number": 999, "title": "完全不同的標題"},
            "repository": {"full_name": "other/repo"},
            "sender": {"login": "u_99"},
        },
        received_at="2026-09-13T23:59:59Z",
        delivery_id="9ab77cd1-0000-0000-0000-000000000000",
    )
    assert signature_of(first) == signature_of(second)


def test_stable_keys_order_does_not_matter():
    headers = {"X-GitHub-Event": "issues"}
    a = structure_signature("github.com", headers, ["sender", "action", "repository", "issue"])
    b = structure_signature("github.com", headers, ["action", "issue", "repository", "sender"])
    assert a == b


def test_different_domain_gives_different_signature():
    headers = {"X-GitHub-Event": "issues"}
    keys = ["action", "issue", "repository", "sender"]
    assert structure_signature("github.com", headers, keys) != structure_signature(
        "discord.com", headers, keys
    )


def test_different_header_set_gives_different_signature():
    keys = ["action", "issue", "repository", "sender"]
    with_delivery = structure_signature(
        "github.com", {"X-GitHub-Event": "issues", "X-GitHub-Delivery": "a"}, keys
    )
    without_delivery = structure_signature("github.com", {"X-GitHub-Event": "issues"}, keys)
    assert with_delivery != without_delivery


def test_missing_domain_becomes_empty_string():
    keys = ["action"]
    assert structure_signature("", {}, keys) == structure_signature(None, {}, keys)


def test_unknown_event_type_has_no_whitelist_yet():
    # 沒有白名單就算不出簽名。Phase 12 會補上 pull_request 等清單與查表函式。
    event = make_event(event_type="pull_request")
    assert (event.domain, event.event_type) not in STABLE_KEYS
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：`uv run pytest tests/unit/test_rote_signature.py -k signature -v`

預期：FAIL，`ImportError: cannot import name 'structure_signature' from 'training_kb.rote'`。

- [ ] **步驟 3：寫最少的程式讓測試通過**

在 `rote.py` 的 import 區補上：

```python
import hashlib
import json
```

加入：

```python
def structure_signature(domain: str, headers: dict[str, str], stable_keys: list[str]) -> str:
    """把事件的「形狀」算成 16 個十六進位字元。

    公式照規格檔「接入來源事件」Rule 3 的補充說明：
        shape = {"domain": ..., "headers": [...], "keys": [...]}
        sha1(json.dumps(shape, sort_keys=True).encode()).hexdigest()[:16]

    這裡的 SHA-1 只是結構索引，不是安全用途，不能代替 webhook 驗簽（設計文件 §7.2）。
    """
    shape = {
        "domain": domain or "",
        "headers": meaningful_header_names(headers),
        "keys": sorted(stable_keys),
    }
    return hashlib.sha1(json.dumps(shape, sort_keys=True).encode()).hexdigest()[:16]

```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：`uv run pytest tests/unit/test_rote_signature.py -v`

預期：PASS（17 passed）。

- [ ] **步驟 5：commit**

```bash
git add src/training_kb/rote.py tests/unit/test_rote_signature.py
git commit -m "feat(rote): 以來源形狀計算結構簽名"
```

---

### Task 4：payload 欄位與 Jaccard 相似度

**目的**：第二層要比「這次事件的最上層欄位」和「某個已學流程記下的欄位」有多像。

**檔案**：
- 修改：`src/training_kb/rote.py`
- 測試：`tests/unit/test_rote_similarity.py`

**介面**：
- 消費：無
- 產出：
  - `rote.payload_keys(body: Any) -> set[str]`
  - `rote.jaccard(a: set[str], b: set[str]) -> float`

- [ ] **步驟 1：寫測試**

`tests/unit/test_rote_similarity.py`：

```python
"""Phase 11：欄位相似度與重放資格（接入來源事件 Rule 6、7、9）。"""

import pytest

from training_kb.config import Thresholds
from training_kb.rote import jaccard, payload_keys


def test_payload_keys_takes_only_top_level():
    body = {
        "action": "opened",
        "issue": {"number": 17, "title": "巢狀欄位不算"},
        "repository": {"full_name": "acme/notes"},
        "sender": {"login": "u_01"},
    }
    assert payload_keys(body) == {"action", "issue", "repository", "sender"}


@pytest.mark.parametrize("body", [None, [], ["action"], "action", 42, ()])
def test_non_object_body_gives_empty_set(body):
    assert payload_keys(body) == set()


def test_empty_object_gives_empty_set():
    assert payload_keys({}) == set()


def test_jaccard_identical_sets():
    keys = {"action", "issue", "repository", "sender"}
    assert jaccard(keys, set(keys)) == 1.0


def test_jaccard_disjoint_sets():
    assert jaccard({"a", "b"}, {"c", "d"}) == 0.0


def test_jaccard_empty_union_is_zero_not_one():
    # 空集合不能算成「完全相同」，否則任何事件都會命中任何流程。
    assert jaccard(set(), set()) == 0.0


def test_jaccard_at_the_threshold():
    """交集 4、聯集 5 -> 0.8，剛好等於門檻。"""
    a = {"action", "issue", "repository", "sender"}
    b = a | {"organization"}
    assert jaccard(a, b) == pytest.approx(0.8)


def test_jaccard_just_below_the_threshold():
    """交集 3、聯集 4 -> 0.75，比門檻小。"""
    a = {"action", "issue", "repository"}
    b = a | {"sender"}
    assert jaccard(a, b) == pytest.approx(0.75)


@pytest.mark.parametrize("score,expected", [(0.7999, False), (0.8, True), (0.81, True)])
def test_threshold_comparison_is_greater_or_equal(score, expected):
    """設計文件 §15 指定的邊界：0.7999 不命中、0.8 命中。"""
    assert (score >= Thresholds().jaccard_replay) is expected


def test_jaccard_is_symmetric():
    a = {"action", "issue"}
    b = {"issue", "repository", "sender"}
    assert jaccard(a, b) == jaccard(b, a)
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：`uv run pytest tests/unit/test_rote_similarity.py -v`

預期：FAIL，`ImportError: cannot import name 'jaccard' from 'training_kb.rote'`。

- [ ] **步驟 3：寫最少的程式讓測試通過**

在 `rote.py` 加入：

```python
def payload_keys(body: Any) -> set[str]:
    """取事件 body 的最上層欄位名稱。

    body 不是物件（陣列、字串、None…）時回空集合。
    空集合在第二層不會命中任何流程（設計文件 §7.2：空集合不當成命中）。
    """
    if isinstance(body, dict):
        return {str(name) for name in body}
    return set()


def jaccard(a: set[str], b: set[str]) -> float:
    """兩個集合的 Jaccard 係數：交集大小 / 聯集大小。

    聯集是空的就回 0.0，不是 1.0 ——
    否則兩個空集合會被當成「完全相同」，任何事件都能命中任何流程。
    """
    union = a | b
    if not union:
        return 0.0
    return len(a & b) / len(union)
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：`uv run pytest tests/unit/test_rote_similarity.py -v`

預期：PASS（parametrize 展開後 17 passed）。

- [ ] **步驟 5：commit**

```bash
git add src/training_kb/rote.py tests/unit/test_rote_similarity.py
git commit -m "feat(rote): payload 欄位擷取與 Jaccard 相似度"
```

---

### Task 5：判斷一個流程能不能重放

**目的**：落實「接入來源事件」Rule 6（只允許 active）、Rule 7（`success_count >= 3`）與 Rule 20（退役視同未命中）。

**檔案**：
- 修改：`src/training_kb/rote.py`
- 測試：`tests/unit/test_rote_similarity.py`

**介面**：
- 消費：`models.ProvenWorkflow`、`models.ProcStatus`（Phase 02）、`config.Thresholds`（Phase 01）
- 產出：`rote.replayable(proc: ProvenWorkflow, thresholds: Thresholds) -> bool`

> 門檻一律從 `thresholds` 讀（`proc_min_success = 3`），**不要在函式裡寫死 3**。第一層與第二層共用同一個判斷（F03）。

- [ ] **步驟 1：寫測試**

加到 `tests/unit/test_rote_similarity.py`：

```python
from training_kb.models import ProcStatus, ProcStep, ProvenWorkflow
from training_kb.rote import replayable

THRESHOLDS = Thresholds()


def make_proc(
    *,
    signature: str = "aaa111",
    keys: list[str] | None = None,
    success_count: int = 3,
    fail_count: int = 0,
    status: ProcStatus = ProcStatus.active,
    last_used: str | None = "2026-09-01T00:00:00Z",
    domain: str = "github.com",
    adapter_type: str = "ticket",
) -> ProvenWorkflow:
    return ProvenWorkflow(
        signature=signature,
        domain=domain,
        adapter_type=adapter_type,
        keys=keys if keys is not None else ["action", "issue", "repository", "sender"],
        steps=[
            ProcStep(tool="parse_github_issue", args={"raw": "$.event.issue"}),
            ProcStep(tool="to_ticket", args={"parsed": "$.steps[0]"}),
            ProcStep(tool="validate", args={"obj": "$.steps[1]"}),
        ],
        success_count=success_count,
        fail_count=fail_count,
        status=status,
        last_used=last_used,
    )


@pytest.mark.parametrize("success_count,expected", [(0, False), (1, False), (2, False), (3, True), (4, True)])
def test_success_count_threshold_is_three(success_count, expected):
    """設計文件 §15 指定的邊界：成功數 2 不能重放、3 可以。"""
    assert replayable(make_proc(success_count=success_count), THRESHOLDS) is expected


def test_retired_proc_is_never_replayable():
    """Rule 20：已退役流程在下次接入時視同未命中。"""
    proc = make_proc(success_count=99, status=ProcStatus.retired)
    assert replayable(proc, THRESHOLDS) is False


def test_active_with_failures_is_still_replayable():
    # 連續失敗還沒到 3 次，status 仍是 active，可以再試一次。
    assert replayable(make_proc(fail_count=2), THRESHOLDS) is True
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：`uv run pytest tests/unit/test_rote_similarity.py -k replayable -v`

預期：FAIL，`ImportError: cannot import name 'replayable' from 'training_kb.rote'`。

- [ ] **步驟 3：寫最少的程式讓測試通過**

在 `rote.py` 的 import 區補上：

```python
from .config import Thresholds
from .models import ProcStatus, ProvenWorkflow
```

加入：

```python
def replayable(proc: ProvenWorkflow, thresholds: Thresholds) -> bool:
    """這個流程可以被重放嗎？

    Rule 6：只允許 status 為 active 的流程重放。
    Rule 7：success_count 必須至少為 3（門檻從 thresholds 讀，不寫死）。
    Rule 20：已退役的流程視同未命中，不管成功過幾次。
    第一層與第二層共用同一個判斷（F03）。
    """
    if proc.status is not ProcStatus.active:
        return False
    return proc.success_count >= thresholds.proc_min_success
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：`uv run pytest tests/unit/test_rote_similarity.py -v`

預期：PASS（24 passed）。

- [ ] **步驟 5：commit**

```bash
git add src/training_kb/rote.py tests/unit/test_rote_similarity.py
git commit -m "feat(rote): 判斷已驗證流程能否重放"
```

---

### Task 6：第二層候選挑選

**目的**：落實 Rule 9 與 F04：Jaccard ≥ 0.8；多個合格時「分數最高 → `last_used` 最新 → signature 升序」。

**檔案**：
- 修改：`src/training_kb/rote.py`
- 測試：`tests/unit/test_rote_similarity.py`

**介面**：
- 消費：`rote.replayable`（Task 5）、`rote.jaccard`（Task 4）
- 產出：
  - `rote._Candidate`（模組內部 dataclass；不對外使用）
  - `rote.pick_layer2(procs: list[ProvenWorkflow], keys: set[str], thresholds: Thresholds) -> ProvenWorkflow | None`

> **本階段選擇**：`last_used` 是 ISO 8601 UTC 字串（例 `2026-09-10T00:00:00Z`），格式固定，所以直接用字串比大小就等於比時間先後。`last_used` 是 `None`（還沒成功重放過）時當成空字串，排在最舊。

- [ ] **步驟 1：寫測試**

加到 `tests/unit/test_rote_similarity.py`：

```python
from training_kb.rote import pick_layer2

EVENT_KEYS = {"action", "issue", "repository", "sender"}


def test_picks_the_highest_score():
    lower = make_proc(signature="ccc333", keys=["action", "issue", "repository", "sender", "org"])
    exact = make_proc(signature="aaa111")
    assert pick_layer2([lower, exact], EVENT_KEYS, THRESHOLDS).signature == "aaa111"


def test_rejects_everything_below_the_threshold():
    too_different = make_proc(signature="ddd444", keys=["action", "issue", "repository"])
    assert pick_layer2([too_different], EVENT_KEYS, THRESHOLDS) is None


def test_accepts_exactly_zero_point_eight():
    at_threshold = make_proc(signature="ccc333",
                             keys=["action", "issue", "repository", "sender", "organization"])
    assert pick_layer2([at_threshold], EVENT_KEYS, THRESHOLDS).signature == "ccc333"


def test_tie_on_score_uses_the_most_recent_last_used():
    older = make_proc(signature="aaa111", last_used="2026-09-01T00:00:00Z")
    newer = make_proc(signature="bbb222", last_used="2026-09-10T00:00:00Z")
    assert pick_layer2([older, newer], EVENT_KEYS, THRESHOLDS).signature == "bbb222"
    assert pick_layer2([newer, older], EVENT_KEYS, THRESHOLDS).signature == "bbb222"


def test_tie_on_score_and_last_used_uses_signature_ascending():
    first = make_proc(signature="bbb222", last_used="2026-09-10T00:00:00Z")
    second = make_proc(signature="aaa111", last_used="2026-09-10T00:00:00Z")
    assert pick_layer2([first, second], EVENT_KEYS, THRESHOLDS).signature == "aaa111"


def test_never_used_proc_counts_as_the_oldest():
    never = make_proc(signature="aaa111", last_used=None)
    used = make_proc(signature="bbb222", last_used="2026-09-01T00:00:00Z")
    assert pick_layer2([never, used], EVENT_KEYS, THRESHOLDS).signature == "bbb222"


def test_retired_and_immature_procs_are_skipped():
    retired = make_proc(signature="eee555", status=ProcStatus.retired)
    immature = make_proc(signature="fff666", success_count=2)
    assert pick_layer2([retired, immature], EVENT_KEYS, THRESHOLDS) is None


def test_empty_event_keys_never_match():
    """設計文件 §7.2：空集合不當成命中。"""
    assert pick_layer2([make_proc()], set(), THRESHOLDS) is None


def test_empty_candidate_list_returns_none():
    assert pick_layer2([], EVENT_KEYS, THRESHOLDS) is None
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：`uv run pytest tests/unit/test_rote_similarity.py -k layer2 -v`

預期：FAIL，`ImportError: cannot import name 'pick_layer2' from 'training_kb.rote'`。

- [ ] **步驟 3：寫最少的程式讓測試通過**

在 `rote.py` 加入：

```python
@dataclass
class _Candidate:
    """第二層排序用的暫時資料，不對外使用。"""

    score: float
    last_used: str
    signature: str
    proc: ProvenWorkflow


def pick_layer2(
    procs: list[ProvenWorkflow],
    keys: set[str],
    thresholds: Thresholds,
) -> ProvenWorkflow | None:
    """從同來源的流程裡挑出第二層要重放的那一個。

    Rule 9：Jaccard 至少 0.8，而且同樣必須 active 且 success_count >= 3。
    F04：多個合格時「分數最高 -> last_used 最新 -> signature 升序」。
    設計文件 §7.2：空集合不當成命中。

    procs 應該只包含同一個 domain + adapter_type 的流程（D19），
    由呼叫端用 repository.list_procs(domain, adapter_type) 取得。
    """
    if not keys:
        return None

    candidates: list[_Candidate] = []
    for proc in procs:
        if not replayable(proc, thresholds):
            continue
        score = jaccard(keys, set(proc.keys))
        if score < thresholds.jaccard_replay:
            continue
        candidates.append(
            _Candidate(
                score=score,
                last_used=proc.last_used or "",
                signature=proc.signature,
                proc=proc,
            )
        )

    if not candidates:
        return None

    # Python 的排序是穩定的（reverse=True 也是），所以從最次要的條件排到最主要的條件，
    # 最後 candidates[0] 就是「分數最高 -> last_used 最新 -> signature 最小」。
    candidates.sort(key=lambda c: c.signature)
    candidates.sort(key=lambda c: c.last_used, reverse=True)
    candidates.sort(key=lambda c: c.score, reverse=True)
    return candidates[0].proc
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：`uv run pytest tests/unit/test_rote_similarity.py -v`

預期：PASS（33 passed）。

- [ ] **步驟 5：commit**

```bash
git add src/training_kb/rote.py tests/unit/test_rote_similarity.py
git commit -m "feat(rote): 第二層候選流程的挑選規則"
```

---

### Task 7：PROC 計數的三個轉換

**目的**：落實 Rule 8、15、16、19 與 D20、F53：成功怎麼加、失敗怎麼加、什麼時候退役、退役之後不自動復活。

**檔案**：
- 修改：`src/training_kb/rote.py`
- 測試：`tests/unit/test_rote_counters.py`

**介面**：
- 消費：`models.ProvenWorkflow`、`models.ProcStatus`、`config.Thresholds`、`clock.to_iso`（Phase 01）
- 產出：
  - `rote.on_replay_success(proc: ProvenWorkflow, now: datetime) -> ProvenWorkflow`
  - `rote.on_replay_failure(proc: ProvenWorkflow, thresholds: Thresholds) -> ProvenWorkflow`
  - `rote.on_new_success(proc: ProvenWorkflow, now: datetime) -> ProvenWorkflow`

> 三個函式都**回傳新的物件，不修改傳進來的那一個**，也**不寫資料庫**。要不要存是呼叫端（Phase 12 的 `Rote.commit_success`）的決定，而且只有在「物件已保存且 Step Functions 已成功啟動」之後才會呼叫（Rule 13、14）。
>
> **本階段選擇**（對應 F53）：`on_new_success` 遇到 `status == retired` 的流程時**原樣回傳，不加計數、不改狀態**。F53 的答案是 C：「退役簽名保持停用，由人工核定新的序列後再明確重置流程。」所以就算 Agent 用新的做法成功了，也不能讓退役的流程自己活過來。
>
> **本階段選擇**：`on_new_success` 會把 `fail_count` 歸零。理由是 `fail_count` 的定義是「連續失敗次數」（D20），一次完整成功就把連續中斷了。

- [ ] **步驟 1：寫測試**

`tests/unit/test_rote_counters.py`：

```python
"""Phase 11：PROC 計數轉換（接入來源事件 Rule 8、15、16、19；D20、F53）。"""

from datetime import UTC, datetime

from training_kb.config import Thresholds
from training_kb.models import ProcStatus, ProcStep, ProvenWorkflow
from training_kb.rote import on_new_success, on_replay_failure, on_replay_success

THRESHOLDS = Thresholds()
NOW = datetime(2026, 9, 13, 12, 0, 0, tzinfo=UTC)


def make_proc(*, success_count: int = 3, fail_count: int = 0,
              status: ProcStatus = ProcStatus.active,
              last_used: str | None = "2026-09-01T00:00:00Z") -> ProvenWorkflow:
    return ProvenWorkflow(
        signature="aaa111",
        domain="github.com",
        adapter_type="ticket",
        keys=["action", "issue", "repository", "sender"],
        steps=[ProcStep(tool="validate", args={"obj": "$.steps[0]"})],
        success_count=success_count,
        fail_count=fail_count,
        status=status,
        last_used=last_used,
    )


def test_replay_success_resets_fail_count_and_updates_last_used():
    """Rule 16：重放成功時 fail_count 歸零。"""
    updated = on_replay_success(make_proc(fail_count=2), NOW)
    assert updated.fail_count == 0
    assert updated.last_used == "2026-09-13T12:00:00Z"
    assert updated.success_count == 3      # 重放成功不增加成功樣本數


def test_replay_success_does_not_mutate_the_input():
    original = make_proc(fail_count=2)
    on_replay_success(original, NOW)
    assert original.fail_count == 2


def test_replay_failure_increases_fail_count():
    """Rule 15：每次重放失敗時 fail_count 增加 1。"""
    updated = on_replay_failure(make_proc(fail_count=0), THRESHOLDS)
    assert updated.fail_count == 1
    assert updated.status is ProcStatus.active


def test_third_consecutive_failure_retires_the_proc():
    """Rule 19：同一流程連續三次重放失敗後 status 變為 retired。"""
    first = on_replay_failure(make_proc(), THRESHOLDS)
    second = on_replay_failure(first, THRESHOLDS)
    third = on_replay_failure(second, THRESHOLDS)

    assert [p.fail_count for p in (first, second, third)] == [1, 2, 3]
    assert first.status is ProcStatus.active
    assert second.status is ProcStatus.active
    assert third.status is ProcStatus.retired


def test_failure_does_not_change_last_used():
    # last_used 的定義是「最近一次成功」，失敗不能更新它，否則第二層排序會被污染。
    updated = on_replay_failure(make_proc(last_used="2026-09-01T00:00:00Z"), THRESHOLDS)
    assert updated.last_used == "2026-09-01T00:00:00Z"


def test_success_in_between_failures_does_not_retire():
    """設計文件 §15：成功穿插失敗不誤退役。"""
    proc = make_proc()
    proc = on_replay_failure(proc, THRESHOLDS)      # fail=1
    proc = on_replay_failure(proc, THRESHOLDS)      # fail=2
    proc = on_replay_success(proc, NOW)             # fail=0
    proc = on_replay_failure(proc, THRESHOLDS)      # fail=1
    proc = on_replay_failure(proc, THRESHOLDS)      # fail=2

    assert proc.fail_count == 2
    assert proc.status is ProcStatus.active


def test_new_success_counts_up_and_updates_last_used():
    """Rule 8：新流程每次完整成功才將 success_count 加 1。"""
    updated = on_new_success(make_proc(success_count=1, fail_count=1), NOW)
    assert updated.success_count == 2
    assert updated.fail_count == 0
    assert updated.last_used == "2026-09-13T12:00:00Z"


def test_new_success_from_one_to_three():
    """F05：首次成功記 1，第三次之後才可重放。"""
    proc = make_proc(success_count=1, last_used=None)
    proc = on_new_success(proc, NOW)
    assert proc.success_count == 2
    proc = on_new_success(proc, NOW)
    assert proc.success_count == 3


def test_new_success_never_revives_a_retired_proc():
    """F53：退役簽名保持停用，由人工核定新的序列後再明確重置流程。"""
    retired = make_proc(success_count=3, fail_count=3, status=ProcStatus.retired)
    unchanged = on_new_success(retired, NOW)

    assert unchanged.status is ProcStatus.retired
    assert unchanged.success_count == 3
    assert unchanged.fail_count == 3
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：`uv run pytest tests/unit/test_rote_counters.py -v`

預期：FAIL，`ImportError: cannot import name 'on_new_success' from 'training_kb.rote'`。

- [ ] **步驟 3：寫最少的程式讓測試通過**

在 `rote.py` 的 import 區補上：

```python
from datetime import datetime

from .clock import to_iso
```

加入：

```python
def on_replay_success(proc: ProvenWorkflow, now: datetime) -> ProvenWorkflow:
    """重放成功之後的計數。

    Rule 16：fail_count 歸零。
    last_used 更新成這次成功的時間，供第二層平手時挑「最近成功者」（F04）。
    success_count 不變：重放不是新的成功樣本（F05：同一事件的重送不提供新的成功樣本）。
    回傳新物件，不修改傳進來的那一個；要不要存由呼叫端決定。
    """
    return proc.model_copy(update={"fail_count": 0, "last_used": to_iso(now)})


def on_replay_failure(proc: ProvenWorkflow, thresholds: Thresholds) -> ProvenWorkflow:
    """重放失敗之後的計數。

    Rule 15：fail_count 加 1（D20：這是「連續」失敗次數）。
    Rule 19：連續次數達到 thresholds.proc_max_consecutive_fail（3）就退役。
    不更新 last_used：它的定義是「最近一次成功」。
    """
    fail_count = proc.fail_count + 1
    status = (
        ProcStatus.retired
        if fail_count >= thresholds.proc_max_consecutive_fail
        else proc.status
    )
    return proc.model_copy(update={"fail_count": fail_count, "status": status})


def on_new_success(proc: ProvenWorkflow, now: datetime) -> ProvenWorkflow:
    """第三層（Agent）用同一個序列再次完整成功之後的計數。

    Rule 8：success_count 加 1。F05：達到 3 之後才可被第一層或第二層重放。
    fail_count 歸零：一次完整成功就把「連續失敗」中斷了（D20）。

    F53：已退役的流程原樣回傳，不加計數也不改狀態。
    退役簽名保持停用，必須由人工核定新的序列後才明確重置。
    """
    if proc.status is not ProcStatus.active:
        return proc
    return proc.model_copy(
        update={
            "success_count": proc.success_count + 1,
            "fail_count": 0,
            "last_used": to_iso(now),
        }
    )
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：`uv run pytest tests/unit/test_rote_counters.py -v`

預期：PASS（9 passed）。

- [ ] **步驟 5：commit**

```bash
git add src/training_kb/rote.py tests/unit/test_rote_counters.py
git commit -m "feat(rote): PROC 成功與連續失敗的計數轉換"
```

---

### Task 8：PROC 的讀寫

**目的**：把 `ProvenWorkflow` 存進 DynamoDB 並讀回來；`list_procs` 依 D19 的「同寄件者範圍」篩選。

**檔案**：
- 修改：`src/training_kb/repository.py`
- 測試：`tests/integration/test_repository_proc.py`

**介面**：
- 消費：`Repository.get_meta/put_meta/scan_entity`（Phase 03、Phase 09 Task 2）、`repository.entity_attrs`（Phase 09 Task 2）、`keys.proc_pk`（Phase 02）
- 產出：
  - `Repository.get_proc(signature: str) -> ProvenWorkflow | None`
  - `Repository.put_proc(proc: ProvenWorkflow) -> None`
  - `Repository.list_procs(domain: str, adapter_type: str) -> list[ProvenWorkflow]`

> Rule 31：「只有 Rote 接入層讀寫 `PROVEN_WORKFLOW`。」這三個方法雖然寫在 `repository.py`（因為所有 DynamoDB 存取都集中在那裡），但**只能由 `rote.py` 呼叫**。Phase 13 之後的 pipelines、analytics、content 都不可以碰它們。

- [ ] **步驟 1：寫測試**

`tests/integration/test_repository_proc.py`：

```python
"""Phase 11：PROVEN_WORKFLOW 的讀寫（只有 Rote 接入層可以用）。"""

from training_kb.models import ProcStatus, ProcStep, ProvenWorkflow


def make_proc(signature: str, *, domain: str = "github.com",
              adapter_type: str = "ticket", success_count: int = 3) -> ProvenWorkflow:
    return ProvenWorkflow(
        signature=signature,
        domain=domain,
        adapter_type=adapter_type,
        keys=["action", "issue", "repository", "sender"],
        steps=[
            ProcStep(tool="parse_github_issue", args={"raw": "$.event.issue"}),
            ProcStep(tool="to_ticket", args={"parsed": "$.steps[0]"}),
            ProcStep(tool="validate", args={"obj": "$.steps[1]"}),
        ],
        success_count=success_count,
        fail_count=0,
        status=ProcStatus.active,
        last_used="2026-09-10T00:00:00Z",
    )


def test_put_and_get_proc(repo):
    repo.put_proc(make_proc("9f2c1a3b4d5e6f70"))

    got = repo.get_proc("9f2c1a3b4d5e6f70")
    assert got is not None
    assert got.domain == "github.com"
    assert got.adapter_type == "ticket"
    assert got.keys == ["action", "issue", "repository", "sender"]
    assert got.success_count == 3
    assert got.status is ProcStatus.active
    assert [s.tool for s in got.steps] == ["parse_github_issue", "to_ticket", "validate"]
    assert got.steps[0].args == {"raw": "$.event.issue"}


def test_get_proc_returns_none_when_missing(repo):
    assert repo.get_proc("does-not-exist") is None


def test_put_proc_overwrites_the_same_signature(repo):
    repo.put_proc(make_proc("aaa111", success_count=1))
    repo.put_proc(make_proc("aaa111", success_count=2))
    assert repo.get_proc("aaa111").success_count == 2


def test_list_procs_filters_by_domain_and_adapter_type(repo):
    """D19：來源網域與 adapter 類型共同構成「同寄件者」的範圍。"""
    repo.put_proc(make_proc("aaa111", domain="github.com", adapter_type="ticket"))
    repo.put_proc(make_proc("bbb222", domain="github.com", adapter_type="ticket"))
    repo.put_proc(make_proc("ccc333", domain="github.com", adapter_type="release"))
    repo.put_proc(make_proc("ddd444", domain="discord.com", adapter_type="ticket"))

    signatures = [p.signature for p in repo.list_procs("github.com", "ticket")]
    assert signatures == ["aaa111", "bbb222"]
    assert [p.signature for p in repo.list_procs("github.com", "release")] == ["ccc333"]
    assert repo.list_procs("zendesk.com", "ticket") == []


def test_list_procs_includes_retired_ones(repo):
    """退役的流程仍然讀得到；要不要用是 replayable 的判斷，不是這裡。"""
    retired = make_proc("eee555")
    retired = retired.model_copy(update={"status": ProcStatus.retired, "fail_count": 3})
    repo.put_proc(retired)

    procs = repo.list_procs("github.com", "ticket")
    assert [p.status for p in procs] == [ProcStatus.retired]
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：`uv run pytest tests/integration/test_repository_proc.py -v`

預期：FAIL，`AttributeError: 'Repository' object has no attribute 'put_proc'`。

- [ ] **步驟 3：寫最少的程式讓測試通過**

在 `src/training_kb/repository.py` 的 `class Repository` 內新增：

```python
    # ---- PROVEN_WORKFLOW（只有 Rote 接入層可以呼叫，接入來源事件 Rule 31）----
    def get_proc(self, signature: str) -> ProvenWorkflow | None:
        item = self.get_meta(keys.proc_pk(signature))
        if item is None:
            return None
        return ProvenWorkflow.model_validate(item)

    def put_proc(self, proc: ProvenWorkflow) -> None:
        pk = keys.proc_pk(proc.signature)
        self.put_meta(pk, entity_attrs(pk, proc))

    def list_procs(self, domain: str, adapter_type: str) -> list[ProvenWorkflow]:
        """回傳同一個「寄件者範圍」內的全部流程，依 signature 升序。

        D19：來源網域與 adapter 類型共同構成範圍，同類來源可跨專案共用不含事件值的流程。
        這裡不過濾 status 與 success_count：那是 rote.replayable 的判斷。
        """
        procs = [
            ProvenWorkflow.model_validate(row)
            for row in self.scan_entity("PROC")
            if row.get("domain") == domain and row.get("adapter_type") == adapter_type
        ]
        procs.sort(key=lambda p: p.signature)
        return procs
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：`uv run pytest tests/integration/test_repository_proc.py -v`

預期：PASS（5 passed）。

- [ ] **步驟 5：commit**

```bash
git add src/training_kb/repository.py tests/integration/test_repository_proc.py
git commit -m "feat(repository): PROVEN_WORKFLOW 的讀寫與同來源列舉"
```

---

### Task 9：把設計文件 §15 的驗收條件跑成一支測試

**目的**：設計文件 §15 對「來源與 Rote」列了一串必須看見的結果。前面的 Task 已經各自覆蓋，這裡把它們集中成一支可以直接對照驗收表的測試，避免日後改動時漏掉某一條。

**檔案**：
- 新增：`tests/unit/test_rote_acceptance.py`
- 測試：同上

**介面**：
- 消費：Task 1～7 的全部函式
- 產出：無新程式碼（只有測試）

> 設計文件 §15「來源與 Rote」列的原文：「有效／無效／缺少簽名；**事件值改變不改結構簽名；Jaccard 0.7999／0.8；成功數 2／3；成功穿插失敗不誤退役**。」其中「有效／無效／缺少簽名」屬於 Phase 10（`tests/unit/test_ingress_signature.py`），其餘四項在這裡。

- [ ] **步驟 1：寫測試**

`tests/unit/test_rote_acceptance.py`：

```python
"""Phase 11：對照設計文件 §15「來源與 Rote」的驗收清單。

每一個測試前面的註解就是驗收表的原文，改動程式時請一併確認這支檔案還是綠的。
"""

from datetime import UTC, datetime

import pytest

from training_kb.config import Thresholds
from training_kb.models import ProcStatus, ProcStep, ProvenWorkflow
from training_kb.rote import (
    STABLE_KEYS,
    RawEvent,
    jaccard,
    meaningful_header_names,
    on_new_success,
    on_replay_failure,
    on_replay_success,
    payload_keys,
    pick_layer2,
    replayable,
    structure_signature,
)

THRESHOLDS = Thresholds()
NOW = datetime(2026, 9, 13, 12, 0, 0, tzinfo=UTC)

BASE_HEADERS = {
    "X-GitHub-Event": "issues",
    "X-GitHub-Delivery": "72d3162e-cc78-11e3-81ab-4c9367dc0958",
    "X-Hub-Signature-256": "sha256=abc",
    "Content-Type": "application/json",
}
BASE_BODY = {
    "action": "opened",
    "issue": {"number": 17, "title": "會前摘要在哪裡開啟？"},
    "repository": {"full_name": "acme/notes"},
    "sender": {"login": "u_01"},
}


def event(**overrides) -> RawEvent:
    data = {
        "domain": "github.com",
        "adapter_type": "ticket",
        "event_type": "issues",
        "headers": dict(BASE_HEADERS),
        "body": dict(BASE_BODY),
        "received_at": "2026-08-02T09:00:00Z",
        "delivery_id": "72d3162e-cc78-11e3-81ab-4c9367dc0958",
    }
    data.update(overrides)
    return RawEvent(**data)


def signature_of(raw_event: RawEvent) -> str:
    """查出這種來源的白名單再算簽名。Phase 12 會提供正式的 stable_keys_for()。"""
    return structure_signature(
        raw_event.domain,
        raw_event.headers,
        STABLE_KEYS[(raw_event.domain, raw_event.event_type)],
    )


def proc(**overrides) -> ProvenWorkflow:
    data = {
        "signature": "aaa111",
        "domain": "github.com",
        "adapter_type": "ticket",
        "keys": ["action", "issue", "repository", "sender"],
        "steps": [ProcStep(tool="validate", args={"obj": "$.steps[0]"})],
        "success_count": 3,
        "fail_count": 0,
        "status": ProcStatus.active,
        "last_used": "2026-09-01T00:00:00Z",
    }
    data.update(overrides)
    return ProvenWorkflow(**data)


# 驗收項：事件值改變不改結構簽名
def test_changing_every_value_keeps_the_same_signature():
    changed = event(
        headers={**BASE_HEADERS, "X-GitHub-Delivery": "ffffffff", "X-Hub-Signature-256": "sha256=zzz"},
        body={"action": "closed", "issue": {"number": 999}, "repository": {}, "sender": {}},
        received_at="2026-12-31T23:59:59Z",
        delivery_id="ffffffff",
    )
    assert signature_of(event()) == signature_of(changed)


# 驗收項：header 只取白名單前綴且小寫排序
def test_only_whitelisted_headers_in_lowercase_sorted_order():
    assert meaningful_header_names(BASE_HEADERS) == ["x-github-delivery", "x-github-event"]


# 驗收項：Jaccard 0.7999／0.8
@pytest.mark.parametrize("score,should_match", [(0.7999, False), (0.8, True)])
def test_jaccard_threshold_boundary(score, should_match):
    assert (score >= THRESHOLDS.jaccard_replay) is should_match


def test_layer2_accepts_exactly_zero_point_eight_and_rejects_zero_point_seven_five():
    keys = payload_keys(BASE_BODY)
    at_threshold = proc(signature="ccc333",
                        keys=["action", "issue", "repository", "sender", "organization"])
    below = proc(signature="ddd444", keys=["action", "issue", "repository"])

    assert jaccard(keys, set(at_threshold.keys)) == pytest.approx(0.8)
    assert jaccard(keys, set(below.keys)) == pytest.approx(0.75)
    assert pick_layer2([at_threshold], keys, THRESHOLDS) is at_threshold
    assert pick_layer2([below], keys, THRESHOLDS) is None


# 驗收項：成功數 2／3
@pytest.mark.parametrize("success_count,can_replay", [(2, False), (3, True)])
def test_success_count_boundary(success_count, can_replay):
    assert replayable(proc(success_count=success_count), THRESHOLDS) is can_replay


# 驗收項：成功穿插失敗不誤退役
def test_success_between_failures_keeps_the_proc_active():
    workflow = proc()
    for _ in range(2):
        workflow = on_replay_failure(workflow, THRESHOLDS)
    workflow = on_replay_success(workflow, NOW)
    for _ in range(2):
        workflow = on_replay_failure(workflow, THRESHOLDS)

    assert workflow.fail_count == 2
    assert workflow.status is ProcStatus.active


def test_three_consecutive_failures_do_retire():
    workflow = proc()
    for _ in range(3):
        workflow = on_replay_failure(workflow, THRESHOLDS)
    assert workflow.status is ProcStatus.retired


# 驗收項：平手依 last_used 再 signature 升序
def test_tie_break_order():
    keys = payload_keys(BASE_BODY)
    older = proc(signature="aaa111", last_used="2026-09-01T00:00:00Z")
    newer = proc(signature="bbb222", last_used="2026-09-10T00:00:00Z")
    same_time_smaller = proc(signature="aaa000", last_used="2026-09-10T00:00:00Z")

    assert pick_layer2([older, newer], keys, THRESHOLDS) is newer
    assert pick_layer2([newer, same_time_smaller], keys, THRESHOLDS) is same_time_smaller


# 驗收項：退役 PROC 視同未命中
def test_retired_proc_is_treated_as_a_miss():
    keys = payload_keys(BASE_BODY)
    retired = proc(signature="eee555", status=ProcStatus.retired, success_count=99)

    assert replayable(retired, THRESHOLDS) is False
    assert pick_layer2([retired], keys, THRESHOLDS) is None
    # 而且不會因為 Agent 又成功一次就自己復活（F53）
    assert on_new_success(retired, NOW).status is ProcStatus.retired


# 驗收項：空集合不命中
def test_empty_key_set_never_matches():
    assert payload_keys(None) == set()
    assert jaccard(set(), set()) == 0.0
    assert pick_layer2([proc()], set(), THRESHOLDS) is None
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：`uv run pytest tests/unit/test_rote_acceptance.py -v`

預期：這一支的所有函式在 Task 1～7 都已經實作，所以理論上會直接通過。**先刻意確認它真的在測東西**：暫時把 `rote.py` 的 `jaccard` 改成 `return 1.0`，再跑一次，應該會看到 `test_layer2_accepts_exactly_zero_point_eight_and_rejects_zero_point_seven_five` 與 `test_empty_key_set_never_matches` FAIL。確認之後把 `jaccard` 改回來。

這一步的意義是：**沒看過測試失敗，就不知道它有沒有真的在檢查**。

- [ ] **步驟 3：寫最少的程式讓測試通過**

不需要新程式碼。把剛才暫時改動的 `jaccard` 還原成：

```python
def jaccard(a: set[str], b: set[str]) -> float:
    """兩個集合的 Jaccard 係數：交集大小 / 聯集大小。

    聯集是空的就回 0.0，不是 1.0 ——
    否則兩個空集合會被當成「完全相同」，任何事件都能命中任何流程。
    """
    union = a | b
    if not union:
        return 0.0
    return len(a & b) / len(union)
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：

```bash
uv run pytest tests/unit/test_rote_acceptance.py -v
uv run pytest -q
uv run ruff check .
```

預期：全部 PASS，ruff 顯示 `All checks passed!`。

- [ ] **步驟 5：commit**

```bash
git add tests/unit/test_rote_acceptance.py
git commit -m "test(rote): 對照設計文件驗收清單的邊界值測試"
```

---

## 7. 完成檢查清單

- [ ] `uv run pytest -q` 全部通過。
- [ ] `uv run ruff check .` 沒有錯誤。
- [ ] `rote.py` 具備下列名稱：

```bash
uv run python -c "
import training_kb.rote as r
need = ['RawEvent','STABLE_KEYS','MEANINGFUL_HEADER_PREFIXES',
        'meaningful_header_names','structure_signature',
        'payload_keys','jaccard','replayable','pick_layer2',
        'on_replay_success','on_replay_failure','on_new_success']
print([n for n in need if not hasattr(r, n)] or 'OK')
"
```

預期輸出：`OK`。

- [ ] `Repository` 具備 `get_proc`、`put_proc`、`list_procs`：

```bash
uv run python -c "
from training_kb.repository import Repository
need = ['get_proc','put_proc','list_procs']
print([n for n in need if not hasattr(Repository, n)] or 'OK')
"
```

預期輸出：`OK`。

- [ ] 手動驗證「事件值改變不改簽名」：

```bash
uv run python - <<'PY'
from training_kb.rote import STABLE_KEYS, RawEvent, structure_signature

def make(delivery, action, number):
    return RawEvent(
        domain="github.com", adapter_type="ticket", event_type="issues",
        headers={"X-GitHub-Event": "issues", "X-GitHub-Delivery": delivery,
                 "X-Hub-Signature-256": "sha256=abc"},
        body={"action": action, "issue": {"number": number},
              "repository": {}, "sender": {}},
        received_at="2026-08-02T09:00:00Z", delivery_id=delivery)

def signature_of(event):
    return structure_signature(event.domain, event.headers,
                               STABLE_KEYS[(event.domain, event.event_type)])

a = signature_of(make("72d3162e", "opened", 17))
b = signature_of(make("ffffffff", "closed", 999))
print(a, b, "相同" if a == b else "不同")
PY
```

預期輸出：兩個一樣的 16 字元簽名，後面接「相同」。

- [ ] 手動驗證「連續三次失敗會退役、中間成功一次不會」：

```bash
uv run python - <<'PY'
from datetime import UTC, datetime
from training_kb.config import Thresholds
from training_kb.models import ProcStatus, ProcStep, ProvenWorkflow
from training_kb.rote import on_replay_failure, on_replay_success

t = Thresholds()
now = datetime(2026, 9, 13, tzinfo=UTC)
p = ProvenWorkflow(signature="aaa111", domain="github.com", adapter_type="ticket",
                   keys=["action"], steps=[ProcStep(tool="validate", args={})],
                   success_count=3, fail_count=0, status=ProcStatus.active, last_used=None)

x = p
for _ in range(3):
    x = on_replay_failure(x, t)
print("連續三次失敗:", x.fail_count, x.status)

y = p
y = on_replay_failure(y, t); y = on_replay_failure(y, t)
y = on_replay_success(y, now)
y = on_replay_failure(y, t); y = on_replay_failure(y, t)
print("中間成功一次:", y.fail_count, y.status)
PY
```

預期輸出：

```text
連續三次失敗: 3 ProcStatus.retired
中間成功一次: 2 ProcStatus.active
```

- [ ] 對應設計文件第 16 節 S1 切片的檢查：本階段提供「同一事件再次進來時能判斷該不該重放」的全部判斷函式；實際重放與 Agent 由 Phase 12 完成，S1 的端到端檢查要等 Phase 12、14 才能整條跑。**現在不能宣稱 S1 已經完成。**

---

## 8. 常見錯誤與排除

**1）同一個事件每次算出來的簽名都不一樣**

- 症狀：第一層永遠不命中。
- 原因通常是把「值」放進了 `shape`：例如用 `payload_keys(event.body)` 當 `keys`，或把 header 的值也放進去。
- 解法：`keys` 一定要來自 `STABLE_KEYS`（固定白名單），`headers` 只取名稱。用 Task 3 的 `test_event_values_do_not_change_the_signature` 驗證。

**2）ruff 報 `S324 Probable use of insecure hash function`**

- 症狀：如果專案的 ruff 設定打開了 `flake8-bandit`（`S` 系列規則），`hashlib.sha1` 會被標記。
- 原因：SHA-1 不適合當安全雜湊。
- 解法：這裡的 SHA-1 **只是結構索引**，而且公式由規格檔指定，不能改成 SHA-256。在那一行加上 `# noqa: S324  # 結構索引用，非安全用途；驗簽在 ingress.py` 並在 `pyproject.toml` 保留說明。設計文件 §7.2 已經寫明「此 SHA-1 只是結構索引，不能代替 webhook 驗簽」。

**3）`pick_layer2` 挑出來的不是預期的那一個**

- 症狀：平手時挑錯。
- 原因：把三個排序條件寫成一次 `sort(key=lambda c: (-c.score, -c.last_used, c.signature))` —— 字串不能取負號，會直接 `TypeError`；或是順序寫反了。
- 解法：照 Task 6 的寫法，**從最次要的條件排到最主要的條件**，連續三次 `sort`。Python 的排序是穩定的（`reverse=True` 也保持穩定），所以這樣做的結果正確而且好讀。

**4）`fail_count` 被當成累積失敗，好用的流程被誤退役**

- 症狀：明明常常成功，卻莫名其妙退役。
- 原因：`on_replay_success` 忘了把 `fail_count` 設成 0。
- 解法：D20 說得很清楚：「代表連續失敗；成功重放後歸零，達到 3 才退役。」用 `test_success_in_between_failures_does_not_retire` 驗證。

**5）退役的流程自己復活了**

- 症狀：`status` 從 `retired` 變回 `active`。
- 原因：`on_new_success` 沒有先檢查 `status`，或是有人在別的地方直接改 `status`。
- 解法：F53 的答案是 C，退役簽名必須保持停用。`on_new_success` 已經在遇到非 active 時原樣回傳；另外請確認除了 Rote 之外沒有其他模組寫 PROC（Rule 31）。

**6）`ValidationError: Input should be a valid integer`（讀 PROC 時）**

- 症狀：`get_proc` 炸掉。
- 原因：DynamoDB 把 `success_count` 存成 `Decimal`。
- 解法：確認讀取一定走 `get_meta()`／`scan_entity()`（Phase 03 的 `_paged` 與 `get_meta` 內部已經用 `decode_numbers` 把 `Decimal` 還原成 `int`／`float`），不要自己呼叫 `self.table.get_item()` 繞過去。

**7）`TypeError: RawEvent.__init__() missing 1 required positional argument: 'delivery_id'`**

- 症狀：建立 `RawEvent` 時漏參數。
- 原因：`delivery_id` 沒有預設值，這是刻意的——手動匯入沒有投遞 ID 時要明確寫 `delivery_id=None`，而不是讓人忘記傳。
- 解法：明確寫出 `delivery_id=None`。

---

## 9. 這階段不做的事

| 不做的事 | 留給哪一階段 |
|---|---|
| adapter 工具本體（`parse_github_issue`、`parse_pr_diff`、`to_ticket`、`validate` 等） | Phase 12（`12-Phase12-Rote-Agent選工具與重放執行.md`） |
| `ToolRegistry`、`default_tools()` | Phase 12 |
| JSONPath 子集的解析（`resolve_jsonpath`） | Phase 12 |
| `replay()`：真的把記下來的步驟跑一遍 | Phase 12 |
| `Rote` 類別、`normalize()`（三層串接）、`commit_success()`、`commit_replay_failure()` | Phase 12 |
| Agent 工具迴圈（`writer.converse_with_tools`，最多 8 回合） | Phase 12 |
| 補齊 PR 與手動來源的 `STABLE_KEYS`，以及查表函式 `stable_keys_for(domain, event_type)` | Phase 12（O6：以一個真實 Issue、一個 PR 的 fixture 補齊；查不到白名單時拋 `PermanentError`） |
| `handle_manual_ticket` 的實作 | Phase 12 |
| 決定要不要把更新後的 PROC 存回資料庫 | Phase 12（本階段的三個 `on_*` 只回傳新物件，不寫入） |
| 人工核定後重置退役流程的工具 | **本 MVP 不做。** F53 只要求「保持停用，由人工核定新的序列後再明確重置」，沒有要求提供自動化入口；Demo 若需要重置，由維護者手動改資料並記錄。 |
| Feedback 的 PROC 學習 | **永遠不做。** F06：Feedback 不納入 `PROVEN_WORKFLOW` 學習，只使用固定接入保存流程。 |

---

## 10. 對照：設計章節與 Rule 編號

`接入來源事件.feature` 共 31 條 Rule，下表列出**本階段負責**的 12 條。

| Rule 來源檔 | Rule 編號與原文 | 本階段哪個 Task 落實 |
|---|---|---|
| `接入來源事件.feature` | Rule 3「來源簽名使用來源網域、有意義的 header 名稱與穩定 payload key 計算」 | Task 1（STABLE_KEYS）、Task 2（header 名稱）、Task 3（公式） |
| `接入來源事件.feature` | Rule 4「ID、時間戳與標題等事件值不參與來源簽名」 | Task 3（`test_event_values_do_not_change_the_signature`） |
| `接入來源事件.feature` | Rule 5「第一層以 PROC 主鍵精確比對來源簽名」 | Task 3（算出 signature）＋ Task 8（`get_proc` 用 `PROC#<signature>` 精確讀取）；串接在 Phase 12 |
| `接入來源事件.feature` | Rule 6「第一層只允許 status 為 active 的流程重放」 | Task 5（`replayable`） |
| `接入來源事件.feature` | Rule 7「第一層流程的 success_count 必須至少為 3」 | Task 5（門檻取自 `Thresholds.proc_min_success`） |
| `接入來源事件.feature` | Rule 8「新流程每次完整成功才將 success_count 加 1」 | Task 7（`on_new_success`） |
| `接入來源事件.feature` | Rule 9「第一層未命中才在同寄件者的流程中以 Jaccard 至少 0.8 比對欄位」 | Task 4（`jaccard`）、Task 6（`pick_layer2`）、Task 8（`list_procs` 依 D19 限定同寄件者範圍） |
| `接入來源事件.feature` | Rule 15「每次重放失敗時 fail_count 增加 1」 | Task 7（`on_replay_failure`） |
| `接入來源事件.feature` | Rule 16「重放成功時 fail_count 歸零」 | Task 7（`on_replay_success`） |
| `接入來源事件.feature` | Rule 19「同一流程連續三次重放失敗後 status 變為 retired」 | Task 7（門檻取自 `Thresholds.proc_max_consecutive_fail`） |
| `接入來源事件.feature` | Rule 20「已退役流程在下次接入時視同未命中」 | Task 5（`replayable` 回 False）、Task 6（`pick_layer2` 直接跳過）、Task 7（`on_new_success` 不復活，對應 F53） |
| `接入來源事件.feature` | Rule 31「只有 Rote 接入層讀寫 PROVEN_WORKFLOW」 | Task 8（三個方法寫在 repository，但只由 `rote.py` 呼叫；其他模組不得使用） |

其餘 Rule 的歸屬（列出以免遺漏）：

- Rule 1、2、14、18、21～30 → Phase 10（`10-Phase10-Ingress-驗簽驗證與去重.md`）。
- Rule 10「前兩層皆未命中時才由 Agent 選擇 adapter tool」、Rule 11「命中已驗證流程的重放路徑不呼叫 LLM」、Rule 12「tool 參數以 JSONPath 指向事件欄位或前一步輸出」、Rule 13「寫回新流程前最後一個 tool 必須是通過的 validate」、Rule 17「重放或正規化驗證失敗時當次回退到 Agent」 → Phase 12。

相關的資料決策：

| 決策 | 原文摘要 | 本階段落實處 |
|---|---|---|
| D19 | 「來源網域與 adapter 類型共同構成範圍，同類來源可跨專案共用不含事件值的流程。」 | Task 8（`list_procs(domain, adapter_type)`）、Task 6（只在同範圍內挑） |
| D20 | 「`fail_count` 代表連續失敗；成功重放後歸零，達到 3 才退役。」 | Task 7 |
| F02 | 「每一種來源與事件類型有自己的固定必備 top-level key 清單。」 | Task 1 |
| F03 | 「第二層也必須 active 且 `success_count >= 3` 才可重放。」 | Task 5、6 |
| F04 | 「選 Jaccard 最高者，同分時選最近成功使用者；須固定最後的識別碼排序以消除平手。」 | Task 6 |
| F05 | 「首次成功記為 1；同簽名事件再由 Agent 完成相同可泛化序列，每次完整成功才累加。」 | Task 7 |
| F53 | 「退役簽名保持停用，由人工核定新的序列後再明確重置流程。」 | Task 7（`on_new_success` 對 retired 原樣回傳） |

---

## 11. 參考來源

設計文件（`docs/design/training-kb.md`）：

- §7.2 Rote：只記住可重複使用的接入程序（三層圖、簽名公式、header 白名單、Jaccard、PROC 計數、空集合不當成命中、「此 SHA-1 只是結構索引，不能代替 webhook 驗簽」）。
- §9.1 鍵與原生型別：`PROVEN_WORKFLOW` 的 PK 是 `PROC#<signature>`、SK 是 `META`、「沒有圖譜邊」。
- §14.1 各層如何結束：「Rote 重放失敗 → Rote 記連敗並當次回退 Agent」「已 retired 的 PROC 不重放」。
- §15 測試與驗收設計，「來源與 Rote」列：「事件值改變不改結構簽名；Jaccard 0.7999／0.8；成功數 2／3；成功穿插失敗不誤退役。」
- §16 交付切片 S1。
- §18 待確認事項 O6（來源完整契約；PR 與手動來源的白名單仍待補齊）。
- §19.1 D19、D20；§19.2 F02、F03、F04、F05、F06、F53。
- §20.7 接入來源事件的 31 條 Rule 對照。

規格檔：

- `docs/spec/features/接入來源事件.feature`，特別是 Rule 3 的補充說明（簽名公式、header 前綴、GitHub Issue 的 STABLE_KEYS 清單、「其他來源等手動上傳後再定，不預先發明 Discord 或 email 清單」）與 Rule 9 的補充說明（同寄件者範圍、平手排序）。
- `docs/spec/erm.dbml` 第 232–252 行：`PROVEN_WORKFLOW` 各欄位的註解（`success_count`、`fail_count`、`last_used` 的定義）。

Python 官方文件（2026-09-13 查證）：

- `hashlib`（`sha1`、`hexdigest`）：<https://docs.python.org/3/library/hashlib.html>
- `json.dumps`（`sort_keys`）：<https://docs.python.org/3/library/json.html>
- 排序的穩定性（`sorted()` 與 `list.sort()` 保證穩定，`reverse=True` 亦然）：<https://docs.python.org/3/howto/sorting.html#sort-stability-and-complex-sorts>
- `dataclasses`：<https://docs.python.org/3/library/dataclasses.html>

pydantic v2 官方文件（2026-09-13 查證）：

- `model_copy(update=...)` 產生更新後的新物件：<https://docs.pydantic.dev/latest/concepts/serialization/#modelmodel_copy>

AWS 官方文件（Phase 12 會用到，本階段僅引用背景）：

- Bedrock `Converse` 的工具呼叫（`toolConfig`）：<https://docs.aws.amazon.com/bedrock/latest/userguide/tool-use.html>
