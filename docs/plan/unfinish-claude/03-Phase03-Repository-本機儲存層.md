# Phase 03：Repository — 本機儲存層

| 項目 | 內容 |
|---|---|
| 上一階段 | Phase 02：領域模型與資料鍵（`02-Phase02-領域模型與資料鍵.md`） |
| 下一階段 | Phase 04：AWS 基礎建設與模型可用性確認（`04-Phase04-AWS基礎建設與模型可用性確認.md`） |
| 對應設計文件章節 | §9（十個邏輯實體如何存入一張表）、§10（分頁與一致性）、§14.2（重試不是重新抽一次文字）、待確認事項 O2（`docs/design/training-kb.md`） |
| 對應交付切片 | S0（設計文件第 16 節） |
| 預估時間 | 約 5 小時 |
| 做完會得到 | 一個可以在自己電腦上跑、完全不連 AWS 的 `Repository`，能讀寫 DynamoDB 單表與 S3，並且條件寫入、原子計數、操作紀錄與鎖都有測試證明它會照預期失敗。 |

---

## 1. 這階段做完會得到什麼

做完這一階段，你會有一個檔案 `src/training_kb/repository.py`，它是**整個專案唯一直接碰資料庫與檔案儲存的地方**。後面所有階段（建立教學版本、發布、查詢圖譜、指標計算）都透過它存取資料，不會自己寫 `boto3` 呼叫。

具體會得到：

1. **一組共用測試設施**：`tests/conftest.py` 裡的 pytest fixture，用 `moto` 在記憶體中假裝有一個 DynamoDB 表和一個 S3 bucket。後面每一個階段的測試都直接用這些 fixture，不用重寫。
2. **基礎讀寫**：`put_meta`、`get_meta`、`update_meta`、`put_edge`、`query_pk`、`query_by_target`、`scan_entity`、`transact_write`、`next_counter`、`get_config_list`。
3. **S3 存取**：`put_object`、`get_object`、`object_exists`，其中 `put_object` 支援「同一個 key 已經存在就不要蓋掉」。
4. **操作紀錄**：`begin_operation`、`load_operation`、`update_operation`。這是「同一個事件重送時只處理一次」的地基。
5. **鎖**：`acquire_lock`、`release_lock`。這是「同一篇教學的修改要排隊」的地基。
6. **建立入口**：`build_repository(settings)`。

而且每一個「應該要失敗」的情況都有測試證明它真的失敗了：重複寫入回傳 `False`、條件不符會拋錯、分頁沒讀完會被抓到。

> 注意：這一階段**不需要 AWS 帳號、不會花任何錢、不會連上網路**。真正的 AWS 資源要等 Phase 04。

---

## 2. 它在整張地圖的位置

```text
基礎層          01 骨架 -> 02 模型與鍵 -> [03 Repository(本機)] -> 04 AWS 基礎建設
                                          ^^^^^^^^^^^^^^^^^^^^
                                             你在這裡
                                                                      |
AI 與內容層     05 Writing(Bedrock) -> 06 規則注入 -> 07 建立版本 -> 08 發布與退役 -> 09 圖譜查詢
                                                                                        |
接入層          10 Ingress 驗簽 -> 11 Rote 判定 -> 12 Rote Agent -------------------------+
                                                                                        |
流程層          13 Ticket Analysis -> 14 Step Functions 上線 -> 15 Feedback/View 匯入 -> 16 Release Update
                                                                                        |
學習層          17 Review:REFINE -> 18 Review:候選規則+排程 -> 19 Analytics 指標 -> 20 規則驗證
                                                                                        |
展示與驗收層    21 Demo 種子資料 -> 22 靜態教學站 -> 23 Demo 控制台 -> 24 失敗復原驗收 -> 25 安全與當日準備
```

Phase 03 是「地基的地基」。Phase 09 會回到同一個檔案補上「固定讀取」函式（`get_tutorial`、`list_feedback_of_version` 等）；Phase 07、08 會用本階段的條件寫入與鎖來保證「發布成功才切換版本」。

---

## 3. 開始前檢查

### 3.1 前置條件

| 條件 | 來自哪裡 |
|---|---|
| `pyproject.toml` 存在，`uv run pytest` 可以跑起來 | Phase 01 |
| `src/training_kb/config.py`（`Settings`、`Thresholds`、`load_settings`）存在 | Phase 01 |
| `src/training_kb/clock.py`（`now_utc`、`to_iso`、`parse_iso`、`utc_date`）存在 | Phase 01 |
| `src/training_kb/errors.py`（`TransientError`、`PermanentError`、`IngressError`、`ContentError`）存在 | Phase 01 |
| `src/training_kb/keys.py`（`META`、`tutorial_pk`、`version_pk`、`step_pk`、`feature_pk`、`rule_pk`、`ops_pk`、`lock_pk`、`counter_pk`、`config_pk`、`edge_sk` 等）存在 | Phase 02 |
| `src/training_kb/models.py`（十個實體的 pydantic 模型）存在 | Phase 02 |

### 3.2 驗證指令與預期輸出

```bash
cd ~/AWS-Hackathon
uv run python -c "import training_kb.keys as k; print(k.META, k.ops_pk('x'), k.lock_pk('a'), k.counter_pk('c'), k.config_pk('n'), k.edge_sk('REFERENCES', 'FEATURE#Prepare'))"
```

預期輸出（一行）：

```text
META OPS#x LOCK#a COUNTER#c CONFIG#n REFERENCES#FEATURE#Prepare
```

```bash
uv run pytest -q
```

預期：Phase 01、02 留下的測試全部 PASS（例如 `12 passed`）。如果這裡就紅了，先回去修 Phase 02，不要往下做。

```bash
uv run python -c "import boto3" 2>&1 | tail -1
```

預期：如果 Phase 01 還沒裝 `boto3`，這裡會出現 `ModuleNotFoundError: No module named 'boto3'`。沒關係，Task 1 就會裝。

---

## 4. 名詞小抄

| 名詞 | 白話解釋 | 在本階段哪裡用到 |
|---|---|---|
| DynamoDB | AWS 提供的資料庫。你可以把它想成一本超大的字典：給它一把鑰匙，它把值還給你。它不是 MySQL，沒有 JOIN、沒有 `SELECT * WHERE`。 | 所有 metadata 與關係邊 |
| S3 | AWS 提供的檔案櫃。你給它一個路徑字串（叫 key）和一坨資料，它幫你存起來。 | 教學全文、diff、操作紀錄 |
| 單表設計（single-table design） | 十種不同的資料全部塞進同一張 DynamoDB 表，用鍵的前綴（`TUTORIAL#`、`VERSION#`…）區分。設計文件 §9 決定這樣做。 | 整個 `repository.py` |
| PK / SK | DynamoDB 的主鍵由兩段組成：PK（分割鍵 partition key，決定資料放在哪一台機器）與 SK（排序鍵 sort key，同一個 PK 底下依 SK 排序）。 | 每一個 item |
| item | DynamoDB 裡的一筆資料，就是一個「欄位名 → 值」的字典。 | 所有讀寫 |
| GSI（Global Secondary Index） | 全域次要索引。DynamoDB 只能用主鍵找資料；想用別的欄位找，就要先建一個索引。本專案的索引叫 `by_target`，分割鍵是 `target`。 | `query_by_target` |
| 最終一致（eventually consistent） | 剛寫進去的資料，GSI 可能要等一下下才看得到。基表（沒有走索引）可以要求「一致讀取」馬上看到。設計文件 §10。 | `query_by_target` 不能要求一致讀 |
| Query / Scan | Query 是「給我這個 PK 底下的資料」，很快；Scan 是「整張表翻一遍」，很慢。設計文件 §10 說 MVP 少量資料允許 Scan。 | `query_pk`、`scan_entity` |
| 分頁（pagination） | DynamoDB 一次最多回傳 1 MB。沒回完時會給你一把 `LastEvaluatedKey`，你要拿它再問一次。 | 所有 Query/Scan 都要迴圈讀完 |
| 條件寫入（conditional write） | 寫入時附帶一個條件，例如「只有當這筆資料不存在時才寫」。條件不成立，AWS 直接拒絕，不會蓋掉舊資料。 | `put_meta(if_not_exists=True)`、鎖、操作紀錄 |
| 原子遞增（atomic increment） | 在資料庫裡直接做「加一」，不是「先讀出來、加一、再寫回去」。後者在兩個程式同時做的時候會算錯。 | `next_counter` |
| 交易（transaction） | 一次送出多個寫入，全部成功或全部失敗。DynamoDB 的 `transact_write_items`。 | `transact_write` |
| 關係邊（edge） | 本專案用一筆 item 表示「A 指向 B」。格式固定為 `PK=起點`、`SK=關係#終點`、`target=終點`。設計文件 §9.2。 | `put_edge` |
| 操作紀錄（operation record） | 一次「邏輯操作」的執行筆記，記錄它的 ID、狀態、產生的版號。用來讓同一個事件重送時不會做兩次。設計文件 O2。 | `begin_operation` 等 |
| 鎖（lock） | 一個「現在輪到我」的標記。同一篇教學同時只有一個操作能改。設計文件 O2。 | `acquire_lock` |
| TTL（time to live） | 存活時間。鎖如果拿走了但程式當掉沒還，過了 TTL 就自動失效，別人可以重新拿。 | `acquire_lock` |
| moto | 一個 Python 套件，在你的電腦記憶體裡「假裝」自己是 AWS。測試時用它，不用真的連線。 | `tests/conftest.py` |
| fixture | pytest 的「測試前置準備」。寫一次，很多測試都能用。 | `tests/conftest.py` |
| `Decimal` | Python 的精確十進位數字型別。DynamoDB 不接受 Python 的 `float`，一定要轉成 `Decimal`。 | `encode_numbers` |
| O2 | 設計文件第 18 節「待確認事項」的第二項：操作紀錄與接受順序的儲存方式還沒定案。本計劃選了一個做法並標示出來。 | 本階段第 5 節 |

---

## 5. 設計說明

### 5.1 為什麼所有資料都放在同一張表

設計文件 §9 的決定：DynamoDB 表名 `training_kb`，主鍵是 `(PK, SK)`，只有一個 GSI `by_target`。十種邏輯實體全部塞進去，用 PK 前綴區分。

理由是：DynamoDB 沒有 JOIN。如果分十張表，要查「誰引用了 Prepare 這個功能」就得自己在程式裡串一堆查詢。單表加上一個 `by_target` 索引，就能用一次查詢把「所有指向某個終點的邊」撈出來。

資料長這樣：

```text
                          DynamoDB 表 training_kb
+-----------------------------+----------------------------+-------------------+
| PK                          | SK                         | 其他欄位          |
+-----------------------------+----------------------------+-------------------+
| TUTORIAL#prepare-meeting    | META                       | entity=TUTORIAL   |
|                             |                            | current_version=… |
+-----------------------------+----------------------------+-------------------+
| VERSION#prepare-meeting@v2  | META                       | entity=VERSION    |
|                             |                            | s3_key=…          |
+-----------------------------+----------------------------+-------------------+
| VERSION#prepare-meeting@v2  | SUPERSEDES#VERSION#…@v1    | target=VERSION#…  |  <- 邊
+-----------------------------+----------------------------+-------------------+
| STEP#prepare-meeting@v2#3   | REFERENCES#FEATURE#Prepare | target=FEATURE#…  |  <- 步驟本身就是邊
|                             |                            | type=click_ui     |
+-----------------------------+----------------------------+-------------------+
| FEATURE#Prepare             | META                       | entity=FEATURE    |
+-----------------------------+----------------------------+-------------------+
| OPS#ingest_ticket_t_881     | META                       | entity=OPS        |  <- 操作紀錄
+-----------------------------+----------------------------+-------------------+
| LOCK#prepare-meeting        | META                       | owner=…           |  <- 鎖
|                             |                            | expires_epoch=…   |
+-----------------------------+----------------------------+-------------------+
| COUNTER#cluster             | META                       | value=12          |  <- 計數器
+-----------------------------+----------------------------+-------------------+

GSI by_target：分割鍵 = target 欄位，投影 = KEYS_ONLY（只帶 PK、SK、target）
  target = FEATURE#Prepare 時，可以一次撈到：
    STEP#prepare-meeting@v2#3 / REFERENCES#FEATURE#Prepare
    TICKET#t_881              / ASKS_ABOUT#FEATURE#Prepare
  想知道步驟的文字，再拿 PK 回基表用一致讀取撈完整內容。
```

**本計劃選擇：** GSI 的投影型別選 `KEYS_ONLY`，也就是索引裡只存 `PK`、`SK`、`target` 三個欄位。這直接對應設計文件 §9.1 的「GSI 不另加排序鍵，先投影查詢需要的鍵；完整資料回基表取得」。好處是索引小、寫入便宜；代價是 `query_by_target()` 回來的字典只有那三個鍵，要內容必須回基表再讀一次。Phase 09、16 都會這樣用。

**本計劃選擇（對應 O1）：** 所有 metadata item 的 SK 一律是字串 `META`；只有步驟用 `REFERENCES#<Feature PK>`。設計文件 §9.1 把 `META` 標成「O1 的建議值」，還沒定案，本計劃直接採用。

### 5.2 三個「一定會被新手踩到」的坑

```text
坑 1：float
  Python:  {"embedding": [0.1, 0.2, ...]}
              |
              v  boto3 的 DynamoDB resource
          TypeError: Float types are not supported. Use Decimal types instead.
  解法：寫入前用 encode_numbers() 把每個 float 換成 Decimal(str(f))
       讀出後用 decode_numbers() 把 Decimal 換回 int/float
  注意：一定要 Decimal(str(0.1))，不能 Decimal(0.1)。
       Decimal(0.1) 會展開成 55 位數，DynamoDB 只收 38 位有效數字，會直接報錯。

坑 2：保留字
  update_item(UpdateExpression="SET status = :v")
              |
              v
          ValidationException: Attribute name is a reserved keyword; reserved keyword: status
  解法：一律用佔位符。
       UpdateExpression="SET #a0 = :v0"
       ExpressionAttributeNames={"#a0": "status"}
  DynamoDB 有五百多個保留字（status、owner、name、source、timestamp、text…），
  與其一個個記，不如全部都用 #a0、#a1。

坑 3：分頁
  resp = table.query(...)          # 只回傳第一頁（最多 1 MB）
  return resp["Items"]             # <- 錯！後面的資料全掉了
  解法：while 迴圈跟著 LastEvaluatedKey 讀，直到它不見為止。
  額外陷阱：Scan 加了 FilterExpression 時，某一頁可能「0 筆」但仍有 LastEvaluatedKey。
           空的一頁不等於沒有資料（設計文件 §10 明講）。
```

### 5.3 分頁要怎麼寫

```text
  kwargs = { KeyConditionExpression: ... }
       |
       v
  +-----------------------------+
  |  resp = table.query(**kwargs)|<--------------------+
  +-----------------------------+                      |
       |                                               |
       v                                               |
  items += resp["Items"]        （可能是 0 筆）          |
       |                                               |
       v                                               |
  resp 有 LastEvaluatedKey ?                            |
       | 有 -> kwargs["ExclusiveStartKey"] = 那把鑰匙 ---+
       | 沒有
       v
  回傳 items（這時候才是完整的）
```

測試要怎麼證明「真的讀了第二頁」？真實 AWS 的分頁界線是 1 MB，測試裡塞 1 MB 資料又慢又難維護。**本計劃選擇：** 在 `Repository.__init__` 加一個測試用的參數 `page_size`，設了它就在每次 Query/Scan 帶 `Limit=page_size`。測試用 `page_size=2` 寫 5 筆資料，再直接用原始 `table.query(..., Limit=2)` 確認「第一頁只有 2 筆、而且有 `LastEvaluatedKey`」，就同時證明了分頁真的發生、而且 `Repository` 有讀完。正式程式（`build_repository`）不設這個參數。

### 5.4 操作紀錄與鎖（本計劃選擇，對應 O2）

設計文件第 18 節的 **O2** 還沒定案：「操作紀錄與接受順序的儲存形狀未指定」。本計劃的選擇是：

| 項目 | 本計劃選擇 |
|---|---|
| 去重 | DynamoDB item `OPS#<operation_id>`，用「不存在才寫」的條件寫入。寫成功代表「這次是第一次看到這個操作」；寫失敗（回傳 `False`）代表是重送。 |
| 保存原輸出 | 同時在 S3 寫 `operations/<operation_id>.json`，內容是完整紀錄（模型輸出、分配到的版號…）。重試時讀回來重用，不重新呼叫模型（設計文件 §14.2）。 |
| 同篇排隊 | DynamoDB item `LOCK#<slug>`，條件寫入 +（過期時間）。取得鎖才能改那一篇教學。 |
| 驗收 | Phase 24 用「注入失敗 + 重送」驗證這套機制真的有效。在那之前**不可以宣稱**去重與順序已經沒問題。 |

鎖的狀態圖：

```text
      (沒有 LOCK#slug 這筆資料)
                |
                |  acquire_lock(slug, owner="op-1", ttl=60, now=T0)
                |  條件：attribute_not_exists(PK)
                v
      +-------------------------------+
      | LOCK#prepare-meeting          |
      | owner = op-1                  |
      | expires_epoch = T0 + 60       |
      +-------------------------------+
         |            |             |
         |            |             | acquire_lock(owner="op-2", now=T0+10)
         |            |             | 條件三個都不成立 -> 回傳 False（要排隊）
         |            |             v
         |            |         op-2 收到 False，呼叫端拋 TransientError
         |            |
         |            | acquire_lock(owner="op-2", now=T0+61)
         |            | 條件 expires_epoch <= now 成立 -> 回傳 True（鎖過期，可以搶）
         |            v
         |        LOCK 換成 owner = op-2
         |
         | release_lock(slug, owner="op-1")
         | 條件：owner = op-1 -> 刪掉這筆
         v
      (回到沒有 LOCK#slug)

補充：同一個 owner 重複呼叫 acquire_lock 會成功（條件多一項 owner = :owner），
      這樣同一次操作重試時不會把自己鎖在門外。
```

### 5.5 S3 的條件寫入

設計文件 §8.3 要求「S3 可使用條件寫入防止已存在物件被覆蓋」。S3 的做法是在 `PutObject` 帶 HTTP 標頭 `If-None-Match: *`：

- bucket 裡沒有同名 key → 寫入成功（200）。
- 已經有同名 key → 失敗，錯誤碼 `PreconditionFailed`（HTTP 412）。
- 併發時如果有人剛好刪掉那個 key → 可能收到 `ConditionalRequestConflict`（HTTP 409）。

在 boto3 裡參數名是 `IfNoneMatch="*"`。本階段把這兩種錯誤都翻譯成「回傳 `False`」，讓呼叫端自己決定要不要核對既有內容（設計文件 §8.3：「同 key 已存在時，應核對它是否為本次相同產物，而非盲目重寫」）。

### 5.6 目錄結構（本階段之後）

```text
AWS-Hackathon/
  pyproject.toml               <- 本階段修改：加 boto3、moto、pytest marker
  src/training_kb/
    config.py                  (Phase 01)
    clock.py                   (Phase 01)
    errors.py                  (Phase 01)
    models.py                  (Phase 02)
    keys.py                    (Phase 02)
    repository.py              <- 本階段新增
  tests/
    conftest.py                <- 本階段新增（後面每個階段共用）
    unit/
      test_models.py           (Phase 02)
      test_keys.py             (Phase 02)
    integration/
      test_fixtures.py         <- 本階段新增
      test_repository_meta.py  <- 本階段新增
      test_repository_query.py <- 本階段新增
      test_repository_s3.py    <- 本階段新增
      test_repository_ops.py   <- 本階段新增
      test_repository_lock.py  <- 本階段新增
```

為什麼 Repository 的測試放 `tests/integration/` 而不是 `tests/unit/`？因為它們雖然不連網路，但確實在操作 AWS API 的語意（條件運算式、分頁、索引）。設計文件 §5 把「接入、儲存、發布與失敗復原」歸在 integration。`tests/unit/` 只留純計算。

---

## 6. 工作項目

### Task 1：安裝依賴並建立共用測試 fixture

**目的**：讓所有後續測試都能用一行 `def test_x(repo):` 拿到一個接上假 DynamoDB 與假 S3 的 `Repository`。

**檔案**：
- 修改：`tests/conftest.py`（Phase 01 已經建立這個檔案，本階段在它後面**接上** moto fixture，不要整份覆蓋）
- 新增：`tests/integration/test_fixtures.py`
- 修改：`pyproject.toml`

**介面**：
- 消費：Phase 01 在 `tests/conftest.py` 放的 `pytest_collection_modifyitems`（讓 `@pytest.mark.aws` 預設跳過）與 `pyproject.toml` 註冊的 `aws` marker
- 產出：pytest fixture `aws_credentials`、`mocked_aws`、`dynamodb_table`、`s3_client`、`repo`、`paged_repo`、`test_settings`；常數 `TEST_REGION`、`TEST_TABLE_NAME`、`TEST_BUCKET_NAME`

先安裝依賴：

```bash
cd ~/AWS-Hackathon
uv add boto3
uv add --dev "moto[s3,dynamodb]>=5.0.14"
```

預期輸出：`uv` 會印出 `+ boto3==1.xx.x`、`+ moto==5.x.x` 之類的安裝清單。

> 如果 `moto[s3,dynamodb]` 回報找不到 extra，改用 `uv add --dev "moto[all]>=5.0.14"`。版本一定要 5.0.14 以上，因為 S3 的條件寫入（`If-None-Match`）是在 moto 5.0.14 才支援的，低版本會讓 Task 7 的測試假通過。

接著確認 `pyproject.toml` 的 pytest 設定長這樣。Phase 01 已經寫好 `[tool.pytest.ini_options]` 與 `markers`，這裡只是核對，缺什麼就補什麼：

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
markers = [
    "aws: 需要真實 AWS 資源的測試；只有設定環境變數 TKB_RUN_AWS_TESTS=1 才會執行",
]
```

確認指令：

```bash
uv run pytest --markers | head -3
```

預期：第一行出現 `@pytest.mark.aws: 需要真實 AWS 資源的測試…`。如果沒有，把上面那段補進 `pyproject.toml`。

- [ ] **步驟 1：寫測試**

`tests/integration/test_fixtures.py`：

```python
"""確認共用 fixture 真的建好了假的 DynamoDB 表與 S3 bucket。"""

from __future__ import annotations


def test_table_has_composite_key(dynamodb_table) -> None:
    description = dynamodb_table.meta.client.describe_table(
        TableName="training_kb"
    )["Table"]
    key_schema = {k["AttributeName"]: k["KeyType"] for k in description["KeySchema"]}
    assert key_schema == {"PK": "HASH", "SK": "RANGE"}


def test_table_has_by_target_index(dynamodb_table) -> None:
    description = dynamodb_table.meta.client.describe_table(
        TableName="training_kb"
    )["Table"]
    indexes = {g["IndexName"]: g for g in description.get("GlobalSecondaryIndexes", [])}
    assert "by_target" in indexes
    index_keys = indexes["by_target"]["KeySchema"]
    assert index_keys[0]["AttributeName"] == "target"
    assert index_keys[0]["KeyType"] == "HASH"


def test_bucket_exists(s3_client) -> None:
    names = [b["Name"] for b in s3_client.list_buckets()["Buckets"]]
    assert "training-kb-content-test" in names


def test_write_and_read_back_one_item(dynamodb_table) -> None:
    dynamodb_table.put_item(Item={"PK": "DEMO#1", "SK": "META", "entity": "DEMO"})
    item = dynamodb_table.get_item(
        Key={"PK": "DEMO#1", "SK": "META"}, ConsistentRead=True
    )["Item"]
    assert item["entity"] == "DEMO"
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：

```bash
uv run pytest tests/integration/test_fixtures.py -v
```

預期：FAIL。錯誤訊息類似 `fixture 'dynamodb_table' not found`。原因是 `tests/conftest.py` 還不存在，pytest 不知道 `dynamodb_table` 是什麼。

- [ ] **步驟 3：寫最少的程式讓測試通過**

`tests/conftest.py`。

Phase 01 已經在這個檔案裡放了 `pytest_collection_modifyitems`（讓 `@pytest.mark.aws` 預設跳過）。下面是本階段之後這個檔案**完整**的樣子，方便你對照；如果你的檔案裡已經有 `pytest_collection_modifyitems`，就保留它，只把 import 區與底下的 fixture 接上去，不要貼兩份同名函式（貼兩份的話後面那份會覆蓋前面那份，雖然內容相同不會出錯，但很容易在之後改動時漏掉一邊）。

```python
"""所有測試共用的 fixture。

用 moto 在記憶體裡模擬 AWS：測試期間完全不連網路、不需要 AWS 帳號。
重點順序：一定要先啟動 mock_aws()，之後才建立 boto3 client/resource。
順序反了會真的打去 AWS。
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import boto3
import pytest
from moto import mock_aws

TEST_REGION = "us-east-1"
TEST_TABLE_NAME = "training_kb"
TEST_BUCKET_NAME = "training-kb-content-test"


def pytest_collection_modifyitems(config, items) -> None:
    """沒有設定 TKB_RUN_AWS_TESTS=1 時，跳過所有標了 @pytest.mark.aws 的測試。"""
    if os.environ.get("TKB_RUN_AWS_TESTS") == "1":
        return
    skip_aws = pytest.mark.skip(
        reason="需要真實 AWS 資源；設定環境變數 TKB_RUN_AWS_TESTS=1 才會執行"
    )
    for item in items:
        if "aws" in item.keywords:
            item.add_marker(skip_aws)


@pytest.fixture(scope="function")
def aws_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    """塞假的 AWS 認證，避免 botocore 撿到你電腦上真正的金鑰。"""
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SECURITY_TOKEN", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", TEST_REGION)
    monkeypatch.delenv("AWS_PROFILE", raising=False)


@pytest.fixture(scope="function")
def mocked_aws(aws_credentials: None) -> Iterator[None]:
    """在這個區塊裡，所有 boto3 呼叫都被 moto 攔截。"""
    with mock_aws():
        yield


@pytest.fixture(scope="function")
def dynamodb_table(mocked_aws: None):
    """建立 training_kb 表：PK/SK 複合主鍵 + by_target GSI，回傳 Table resource。"""
    client = boto3.client("dynamodb", region_name=TEST_REGION)
    client.create_table(
        TableName=TEST_TABLE_NAME,
        AttributeDefinitions=[
            {"AttributeName": "PK", "AttributeType": "S"},
            {"AttributeName": "SK", "AttributeType": "S"},
            {"AttributeName": "target", "AttributeType": "S"},
        ],
        KeySchema=[
            {"AttributeName": "PK", "KeyType": "HASH"},
            {"AttributeName": "SK", "KeyType": "RANGE"},
        ],
        GlobalSecondaryIndexes=[
            {
                "IndexName": "by_target",
                "KeySchema": [{"AttributeName": "target", "KeyType": "HASH"}],
                "Projection": {"ProjectionType": "KEYS_ONLY"},
            }
        ],
        BillingMode="PAY_PER_REQUEST",
    )
    client.get_waiter("table_exists").wait(TableName=TEST_TABLE_NAME)
    return boto3.resource("dynamodb", region_name=TEST_REGION).Table(TEST_TABLE_NAME)


@pytest.fixture(scope="function")
def s3_client(mocked_aws: None):
    """建立測試用 bucket，回傳 S3 client。"""
    client = boto3.client("s3", region_name=TEST_REGION)
    client.create_bucket(Bucket=TEST_BUCKET_NAME)
    return client


@pytest.fixture(scope="function")
def repo(dynamodb_table, s3_client):
    """接上假 DynamoDB 與假 S3 的 Repository。"""
    from training_kb.repository import Repository

    return Repository(dynamodb_table, s3_client, TEST_BUCKET_NAME)


@pytest.fixture(scope="function")
def paged_repo(dynamodb_table, s3_client):
    """每頁只讀 2 筆的 Repository，用來測試分頁有沒有讀完。"""
    from training_kb.repository import Repository

    return Repository(dynamodb_table, s3_client, TEST_BUCKET_NAME, page_size=2)


@pytest.fixture(scope="function")
def test_settings():
    """測試用的 Settings，後面 Phase 05 以後也會用到。"""
    from training_kb.config import Settings

    return Settings(
        aws_region=TEST_REGION,
        table_name=TEST_TABLE_NAME,
        bucket_name=TEST_BUCKET_NAME,
        project_id="demo-project",
        embed_model_id="amazon.titan-embed-text-v2:0",
        embed_dimensions=1024,
        gen_model_id="test-generation-model",
        github_webhook_secret="test-secret",
    )
```

注意 `repo`、`paged_repo`、`test_settings` 三個 fixture 把 `import` 寫在函式**裡面**。這是刻意的：`training_kb.repository` 現在還不存在，如果寫在檔案最上面，pytest 連收集測試都會失敗，Task 1 就永遠紅的。

- [ ] **步驟 4：再跑一次測試，確認通過**

```bash
uv run pytest tests/integration/test_fixtures.py -v
```

預期：`4 passed`。

- [ ] **步驟 5：commit**

```bash
git add pyproject.toml uv.lock tests/conftest.py tests/integration/test_fixtures.py
git commit -m "test(repository): 建立 moto 共用 fixture 與 aws 標記"
```

---

### Task 2：型別轉換與 `put_meta` / `get_meta`

**目的**：把 Python 的資料安全地寫進 DynamoDB 再讀回來，包含 `float` → `Decimal` 的轉換，以及「已存在就不要覆蓋」。

**檔案**：
- 新增：`src/training_kb/repository.py`
- 新增：`tests/integration/test_repository_meta.py`

**介面**：
- 消費：`training_kb.keys.META`、`training_kb.errors.PermanentError`
- 產出：
  - `repository.encode_numbers(value: Any) -> Any`
  - `repository.decode_numbers(value: Any) -> Any`
  - `repository.serialize_item(item: Mapping[str, Any]) -> dict[str, Any]`
  - `repository.deserialize_item(item: Mapping[str, Any]) -> dict[str, Any]`
  - `Repository.__init__(self, table, s3, bucket: str, *, page_size: int | None = None)`
  - `Repository.put_meta(self, pk: str, attrs: dict, *, if_not_exists: bool = False) -> bool`
  - `Repository.get_meta(self, pk: str, *, consistent: bool = True) -> dict | None`

- [ ] **步驟 1：寫測試**

`tests/integration/test_repository_meta.py`：

```python
"""Repository 的 metadata 讀寫與型別轉換。"""

from __future__ import annotations

from decimal import Decimal

from training_kb.keys import feature_pk, ticket_pk, tutorial_pk
from training_kb.repository import decode_numbers, encode_numbers, serialize_item


def test_encode_numbers_turns_float_into_decimal() -> None:
    encoded = encode_numbers({"embedding": [0.1, 0.25], "n": 3})
    assert encoded["embedding"][0] == Decimal("0.1")
    assert encoded["embedding"][1] == Decimal("0.25")
    assert encoded["n"] == 3


def test_decode_numbers_turns_decimal_back() -> None:
    decoded = decode_numbers({"avg": Decimal("2.875"), "n": Decimal("8")})
    assert decoded["avg"] == 2.875
    assert isinstance(decoded["avg"], float)
    assert decoded["n"] == 8
    assert isinstance(decoded["n"], int)


def test_serialize_item_produces_dynamodb_attribute_values() -> None:
    serialized = serialize_item({"PK": "TICKET#t_1", "SK": "META", "rating": 4})
    assert serialized["PK"] == {"S": "TICKET#t_1"}
    assert serialized["rating"] == {"N": "4"}


def test_put_and_get_meta_round_trip(repo) -> None:
    repo.put_meta(
        tutorial_pk("prepare-meeting"),
        {
            "entity": "TUTORIAL",
            "topic": "準備會議",
            "feature_ids": ["Prepare"],
            "status": "active",
            "current_version": None,
        },
    )
    item = repo.get_meta(tutorial_pk("prepare-meeting"))
    assert item is not None
    assert item["PK"] == "TUTORIAL#prepare-meeting"
    assert item["SK"] == "META"
    assert item["topic"] == "準備會議"
    assert item["feature_ids"] == ["Prepare"]
    assert item["current_version"] is None


def test_get_meta_returns_none_when_missing(repo) -> None:
    assert repo.get_meta(feature_pk("NotThere")) is None


def test_put_meta_stores_embedding_floats(repo) -> None:
    vector = [0.1, -0.25, 0.5]
    repo.put_meta(ticket_pk("t_881"), {"entity": "TICKET", "embedding": vector})
    item = repo.get_meta(ticket_pk("t_881"))
    assert item is not None
    assert item["embedding"] == [0.1, -0.25, 0.5]
    assert all(isinstance(v, float) for v in item["embedding"])


def test_put_meta_if_not_exists_returns_false_on_duplicate(repo) -> None:
    first = repo.put_meta(
        ticket_pk("t_881"), {"entity": "TICKET", "text": "第一次"}, if_not_exists=True
    )
    second = repo.put_meta(
        ticket_pk("t_881"), {"entity": "TICKET", "text": "第二次"}, if_not_exists=True
    )
    assert first is True
    assert second is False
    item = repo.get_meta(ticket_pk("t_881"))
    assert item is not None
    assert item["text"] == "第一次"


def test_put_meta_without_condition_overwrites(repo) -> None:
    repo.put_meta(ticket_pk("t_882"), {"entity": "TICKET", "text": "舊的"})
    repo.put_meta(ticket_pk("t_882"), {"entity": "TICKET", "text": "新的"})
    item = repo.get_meta(ticket_pk("t_882"))
    assert item is not None
    assert item["text"] == "新的"


def test_encode_numbers_keeps_precision_for_small_floats() -> None:
    """Decimal(str(f)) 保留 repr 的位數；Decimal(f) 會展開成 50 幾位。

    DynamoDB 只收 38 位有效數字，所以一定要走 str() 這條路。
    """
    encoded = encode_numbers(0.1 + 0.2)
    assert isinstance(encoded, Decimal)
    assert str(encoded) == "0.30000000000000004"
    assert len(str(Decimal(0.1 + 0.2)).split(".")[1]) > 38


def test_encode_numbers_walks_into_nested_structures() -> None:
    encoded = encode_numbers({"a": {"b": [1, 0.5, "x", None, True]}})
    assert encoded["a"]["b"] == [1, Decimal("0.5"), "x", None, True]
    assert isinstance(encoded["a"]["b"][1], Decimal)
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：

```bash
uv run pytest tests/integration/test_repository_meta.py -v
```

預期：FAIL，錯誤訊息是 `ModuleNotFoundError: No module named 'training_kb.repository'`。因為 `repository.py` 還沒建立。

- [ ] **步驟 3：寫最少的程式讓測試通過**

`src/training_kb/repository.py`（整個檔案）：

```python
"""DynamoDB 單表與 S3 的存取層。

本模組是專案裡唯一直接呼叫 boto3 做資料讀寫的地方。
業務規則不放這裡；這裡只負責「把資料正確地放進去、完整地拿出來」。
對應設計文件 §9、§10、§14.2 與待確認事項 O2。
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from typing import Any

from boto3.dynamodb.types import TypeDeserializer, TypeSerializer

from .errors import PermanentError
from .keys import META

_SERIALIZER = TypeSerializer()
_DESERIALIZER = TypeDeserializer()


def encode_numbers(value: Any) -> Any:
    """把 Python 的 float 換成 Decimal，DynamoDB 才收得下。

    一定要用 Decimal(str(f)) 而不是 Decimal(f)：
    Decimal(0.1) 會展開成 55 位十進位數，超過 DynamoDB 的 38 位有效數字上限。
    """
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, Mapping):
        return {key: encode_numbers(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [encode_numbers(item) for item in value]
    return value


def decode_numbers(value: Any) -> Any:
    """把 DynamoDB 回來的 Decimal 換回 int 或 float，方便 pydantic 驗證。"""
    if isinstance(value, Decimal):
        if value == value.to_integral_value():
            return int(value)
        return float(value)
    if isinstance(value, Mapping):
        return {key: decode_numbers(item) for key, item in value.items()}
    if isinstance(value, list):
        return [decode_numbers(item) for item in value]
    return value


def serialize_item(item: Mapping[str, Any]) -> dict[str, Any]:
    """把一般 Python 字典轉成 DynamoDB 低階格式，例如 {"S": "..."}、{"N": "4"}。

    只有 transact_write_items 這種低階 API 需要它；
    一般的 put_item/get_item 由 boto3 的 Table resource 自動處理。
    """
    encoded = encode_numbers(dict(item))
    return {key: _SERIALIZER.serialize(value) for key, value in encoded.items()}


def deserialize_item(item: Mapping[str, Any]) -> dict[str, Any]:
    """serialize_item 的反向操作。"""
    plain = {key: _DESERIALIZER.deserialize(value) for key, value in item.items()}
    return decode_numbers(plain)


class Repository:
    """DynamoDB 單表 + S3 的存取層。

    參數：
        table:     boto3 DynamoDB Table resource。
        s3:        boto3 S3 client。
        bucket:    S3 bucket 名稱。
        page_size: 測試用。設了之後每次 Query/Scan 都帶 Limit，
                   讓小量資料也能走到分頁邏輯。正式程式不要設。
    """

    def __init__(self, table, s3, bucket: str, *, page_size: int | None = None) -> None:
        self.table = table
        self.s3 = s3
        self.bucket = bucket
        self.page_size = page_size
        self.client = table.meta.client
        self.table_name = table.name

    # ------------------------------------------------------------------ 基礎
    def put_meta(self, pk: str, attrs: dict, *, if_not_exists: bool = False) -> bool:
        """寫入一筆 metadata（SK 固定是 META）。

        if_not_exists=True 且該 PK 已經存在時，不覆蓋、回傳 False。
        """
        from botocore.exceptions import ClientError

        item = {**encode_numbers(dict(attrs)), "PK": pk, "SK": META}
        kwargs: dict[str, Any] = {"Item": item}
        if if_not_exists:
            kwargs["ConditionExpression"] = "attribute_not_exists(PK)"
        try:
            self.table.put_item(**kwargs)
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
                return False
            raise
        return True

    def get_meta(self, pk: str, *, consistent: bool = True) -> dict | None:
        """讀一筆 metadata；找不到回傳 None。

        consistent=True 是「一致讀取」：保證讀得到剛剛寫進去的資料。
        只有基表可以這樣讀，GSI 不行（設計文件 §10）。
        """
        response = self.table.get_item(
            Key={"PK": pk, "SK": META}, ConsistentRead=consistent
        )
        item = response.get("Item")
        if item is None:
            return None
        return decode_numbers(dict(item))


__all__ = [
    "PermanentError",
    "Repository",
    "decode_numbers",
    "deserialize_item",
    "encode_numbers",
    "serialize_item",
]
```

> `from botocore.exceptions import ClientError` 寫在函式裡只是為了讓這個 Task 的程式碼片段能獨立貼上。下一個 Task 會把它移到檔案最上面，一併整理 import。

- [ ] **步驟 4：再跑一次測試，確認通過**

```bash
uv run pytest tests/integration/test_repository_meta.py -v
```

預期：`10 passed`。

- [ ] **步驟 5：commit**

```bash
git add src/training_kb/repository.py tests/integration/test_repository_meta.py
git commit -m "feat(repository): 加入型別轉換與 metadata 讀寫"
```

---

### Task 3：`update_meta` 與條件更新

**目的**：只改指定欄位，而且可以要求「只有在某些欄位還是我預期的值時才改」。這是 Phase 08 發布交易的基礎。

**檔案**：
- 修改：`src/training_kb/repository.py`
- 新增：`tests/integration/test_repository_update.py`

**介面**：
- 消費：`Repository.put_meta`、`Repository.get_meta`
- 產出：`Repository.update_meta(self, pk: str, attrs: dict, *, condition_equals: dict | None = None) -> None`（條件不符拋 `PermanentError`）

- [ ] **步驟 1：寫測試**

`tests/integration/test_repository_update.py`：

```python
"""Repository.update_meta 的條件更新行為。"""

from __future__ import annotations

import pytest
from training_kb.errors import PermanentError
from training_kb.keys import tutorial_pk


def _seed(repo) -> str:
    pk = tutorial_pk("prepare-meeting")
    repo.put_meta(
        pk,
        {
            "entity": "TUTORIAL",
            "topic": "準備會議",
            "status": "active",
            "current_version": None,
        },
    )
    return pk


def test_update_meta_changes_only_named_fields(repo) -> None:
    pk = _seed(repo)
    repo.update_meta(pk, {"current_version": "prepare-meeting@v1"})
    item = repo.get_meta(pk)
    assert item is not None
    assert item["current_version"] == "prepare-meeting@v1"
    assert item["topic"] == "準備會議"
    assert item["status"] == "active"


def test_update_meta_handles_reserved_words(repo) -> None:
    """status 與 owner 都是 DynamoDB 保留字，不用佔位符會直接被拒絕。"""
    pk = _seed(repo)
    repo.update_meta(pk, {"status": "retired", "owner": "u_01"})
    item = repo.get_meta(pk)
    assert item is not None
    assert item["status"] == "retired"
    assert item["owner"] == "u_01"


def test_update_meta_with_matching_condition_succeeds(repo) -> None:
    pk = _seed(repo)
    repo.update_meta(pk, {"current_version": "prepare-meeting@v1"},
                     condition_equals={"current_version": None})
    item = repo.get_meta(pk)
    assert item is not None
    assert item["current_version"] == "prepare-meeting@v1"


def test_update_meta_with_wrong_condition_raises(repo) -> None:
    pk = _seed(repo)
    repo.update_meta(pk, {"current_version": "prepare-meeting@v1"})
    with pytest.raises(PermanentError) as excinfo:
        repo.update_meta(
            pk,
            {"current_version": "prepare-meeting@v2"},
            condition_equals={"current_version": None},
        )
    assert "條件不符" in str(excinfo.value)
    item = repo.get_meta(pk)
    assert item is not None
    assert item["current_version"] == "prepare-meeting@v1"


def test_update_meta_condition_on_missing_attribute(repo) -> None:
    """欄位根本不存在時，條件值 None 也要算成立。"""
    pk = tutorial_pk("share-summary")
    repo.put_meta(pk, {"entity": "TUTORIAL", "topic": "分享摘要"})
    repo.update_meta(pk, {"current_version": "share-summary@v1"},
                     condition_equals={"current_version": None})
    item = repo.get_meta(pk)
    assert item is not None
    assert item["current_version"] == "share-summary@v1"


def test_update_meta_rejects_empty_attrs(repo) -> None:
    pk = _seed(repo)
    with pytest.raises(PermanentError):
        repo.update_meta(pk, {})
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：

```bash
uv run pytest tests/integration/test_repository_update.py -v
```

預期：FAIL，`AttributeError: 'Repository' object has no attribute 'update_meta'`。

- [ ] **步驟 3：寫最少的程式讓測試通過**

先把 `repository.py` 最上面的 import 區塊整理成這樣（取代原本的 import 段，同時把 Task 2 裡函式內的 `from botocore.exceptions import ClientError` 那一行刪掉）：

```python
from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from typing import Any

from boto3.dynamodb.types import TypeDeserializer, TypeSerializer
from botocore.exceptions import ClientError

from .errors import PermanentError
from .keys import META
```

再把下面這個方法貼進 `class Repository` 內，接在 `get_meta` 之後（注意縮排四個空格）：

```python
    def update_meta(
        self,
        pk: str,
        attrs: dict,
        *,
        condition_equals: dict | None = None,
    ) -> None:
        """只更新指定欄位；condition_equals 不成立時拋 PermanentError("條件不符…")。

        所有欄位名一律用 #s0、#c0 這種佔位符，避開 DynamoDB 的保留字
        （status、owner、name、source、timestamp… 有五百多個）。

        condition_equals 的值如果是 None，條件寫成
        (attribute_not_exists(#c) OR #c = :c)，
        這樣「欄位不存在」和「欄位是 null」都算成立。
        """
        if not attrs:
            raise PermanentError("update_meta 需要至少一個要更新的欄位")

        names: dict[str, str] = {}
        values: dict[str, Any] = {}
        assignments: list[str] = []
        for index, (field, value) in enumerate(attrs.items()):
            names[f"#s{index}"] = field
            values[f":s{index}"] = encode_numbers(value)
            assignments.append(f"#s{index} = :s{index}")

        conditions: list[str] = []
        for index, (field, value) in enumerate(condition_equals.items() if condition_equals else []):
            names[f"#c{index}"] = field
            values[f":c{index}"] = encode_numbers(value)
            if value is None:
                conditions.append(
                    f"(attribute_not_exists(#c{index}) OR #c{index} = :c{index})"
                )
            else:
                conditions.append(f"#c{index} = :c{index}")

        kwargs: dict[str, Any] = {
            "Key": {"PK": pk, "SK": META},
            "UpdateExpression": "SET " + ", ".join(assignments),
            "ExpressionAttributeNames": names,
            "ExpressionAttributeValues": values,
        }
        if conditions:
            kwargs["ConditionExpression"] = " AND ".join(conditions)

        try:
            self.table.update_item(**kwargs)
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
                raise PermanentError(
                    f"條件不符：{pk} 目前的值與 {condition_equals} 不同，不更新"
                ) from exc
            raise
```

- [ ] **步驟 4：再跑一次測試，確認通過**

```bash
uv run pytest tests/integration/test_repository_update.py -v
```

預期：`6 passed`。

- [ ] **步驟 5：commit**

```bash
git add src/training_kb/repository.py tests/integration/test_repository_update.py
git commit -m "feat(repository): 加入條件更新 update_meta"
```

---

### Task 4：關係邊與 `query_pk`（分頁一定要讀完）

**目的**：把「A 指向 B」存成一筆 item，並且能把某個 PK 底下的所有資料完整撈出來——包含第二頁、第三頁。

**檔案**：
- 修改：`src/training_kb/repository.py`
- 新增：`tests/integration/test_repository_query.py`

**介面**：
- 消費：`training_kb.keys.edge_sk`
- 產出：
  - `Repository.put_edge(self, pk: str, relation: str, target_pk: str, attrs: dict | None = None) -> None`
  - `Repository.query_pk(self, pk: str, *, sk_prefix: str | None = None, consistent: bool = True) -> list[dict]`

- [ ] **步驟 1：寫測試**

`tests/integration/test_repository_query.py`：

```python
"""Repository 的邊寫入、Query 與分頁。"""

from __future__ import annotations

from boto3.dynamodb.conditions import Key
from training_kb.keys import feature_pk, rule_pk, step_pk, version_pk


def test_put_edge_writes_target_matching_sk(repo) -> None:
    """設計文件 §9.2：references 邊的 target 必須等於 SK 裡的關係終點。"""
    repo.put_edge(
        step_pk("prepare-meeting@v2", 3),
        "REFERENCES",
        feature_pk("Prepare"),
        {"entity": "STEP", "type": "click_ui", "text": "在右上角選擇 Prepare"},
    )
    items = repo.query_pk(step_pk("prepare-meeting@v2", 3))
    assert len(items) == 1
    edge = items[0]
    assert edge["SK"] == "REFERENCES#FEATURE#Prepare"
    assert edge["target"] == "FEATURE#Prepare"
    assert edge["text"] == "在右上角選擇 Prepare"


def test_query_pk_filters_by_sk_prefix(repo) -> None:
    pk = version_pk("prepare-meeting@v3")
    repo.put_meta(pk, {"entity": "VERSION", "reason": "release:r_42"})
    repo.put_edge(pk, "SUPERSEDES", version_pk("prepare-meeting@v2"))
    only_edges = repo.query_pk(pk, sk_prefix="SUPERSEDES#")
    assert len(only_edges) == 1
    assert only_edges[0]["target"] == "VERSION#prepare-meeting@v2"
    everything = repo.query_pk(pk)
    assert len(everything) == 2


def test_query_pk_reads_every_page(paged_repo, dynamodb_table) -> None:
    """證明兩件事：真的有第二頁，而且 Repository 有把它讀完。"""
    pk = rule_pk("R-007")
    for n in range(1, 6):
        paged_repo.put_edge(pk, "APPLIED_TO", version_pk(f"demo@v{n}"))

    first_page = dynamodb_table.query(
        KeyConditionExpression=Key("PK").eq(pk), Limit=2
    )
    assert len(first_page["Items"]) == 2
    assert "LastEvaluatedKey" in first_page

    everything = paged_repo.query_pk(pk)
    assert len(everything) == 5
    targets = sorted(item["target"] for item in everything)
    assert targets == [f"VERSION#demo@v{n}" for n in range(1, 6)]


def test_query_pk_returns_empty_list_when_nothing_there(repo) -> None:
    assert repo.query_pk(version_pk("nothing@v1")) == []
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：

```bash
uv run pytest tests/integration/test_repository_query.py -v
```

預期：FAIL，`AttributeError: 'Repository' object has no attribute 'put_edge'`。

- [ ] **步驟 3：寫最少的程式讓測試通過**

先在 `repository.py` 的 import 區把 `keys` 那行改成：

```python
from .keys import META, edge_sk
```

再在 import 區加一行：

```python
from boto3.dynamodb.conditions import Key
```

把下面兩個方法貼進 `class Repository`，接在 `update_meta` 之後：

```python
    def put_edge(
        self,
        pk: str,
        relation: str,
        target_pk: str,
        attrs: dict | None = None,
    ) -> None:
        """寫一條關係邊：PK=起點、SK=關係#終點、target=終點（設計文件 §9.2）。

        target 一定由 target_pk 決定，不從 attrs 覆寫，
        這樣就不可能出現「SK 說指向 A、target 說指向 B」的壞資料。
        """
        item = {
            **encode_numbers(dict(attrs or {})),
            "PK": pk,
            "SK": edge_sk(relation, target_pk),
            "target": target_pk,
        }
        self.table.put_item(Item=item)

    def _paged(self, method, kwargs: dict[str, Any]) -> list[dict]:
        """共用的分頁迴圈：一直讀到沒有 LastEvaluatedKey 為止。

        注意：加了 FilterExpression 時，中間某一頁可能是 0 筆卻仍有下一頁。
        空的一頁不等於全部沒有資料（設計文件 §10）。
        """
        if self.page_size:
            kwargs = {**kwargs, "Limit": self.page_size}
        items: list[dict] = []
        while True:
            response = method(**kwargs)
            items.extend(decode_numbers(dict(raw)) for raw in response.get("Items", []))
            last_key = response.get("LastEvaluatedKey")
            if not last_key:
                return items
            kwargs = {**kwargs, "ExclusiveStartKey": last_key}

    def query_pk(
        self,
        pk: str,
        *,
        sk_prefix: str | None = None,
        consistent: bool = True,
    ) -> list[dict]:
        """撈出某個 PK 底下的所有 item（讀完所有分頁）。"""
        condition = Key("PK").eq(pk)
        if sk_prefix is not None:
            condition = condition & Key("SK").begins_with(sk_prefix)
        return self._paged(
            self.table.query,
            {"KeyConditionExpression": condition, "ConsistentRead": consistent},
        )
```

- [ ] **步驟 4：再跑一次測試，確認通過**

```bash
uv run pytest tests/integration/test_repository_query.py -v
```

預期：`4 passed`。

- [ ] **步驟 5：commit**

```bash
git add src/training_kb/repository.py tests/integration/test_repository_query.py
git commit -m "feat(repository): 加入關係邊與分頁 Query"
```

---

### Task 5：`query_by_target`（GSI）與 `scan_entity`

**目的**：反查「誰指向某個終點」，以及按 `entity` 掃出同一類資料。兩者都要讀完分頁。

**檔案**：
- 修改：`src/training_kb/repository.py`
- 新增：`tests/integration/test_repository_index.py`

**介面**：
- 消費：`Repository.put_edge`、`Repository.put_meta`
- 產出：
  - `Repository.query_by_target(self, target_pk: str) -> list[dict]`
  - `Repository.scan_entity(self, entity: str) -> list[dict]`

- [ ] **步驟 1：寫測試**

`tests/integration/test_repository_index.py`：

```python
"""by_target GSI 反查與 entity Scan。"""

from __future__ import annotations

from training_kb.keys import feature_pk, step_pk, ticket_pk, version_pk


def test_query_by_target_finds_every_incoming_edge(repo) -> None:
    """對應查詢知識圖譜.feature Rule 2：用 by_target 的 target 反查。"""
    target = feature_pk("Prepare")
    repo.put_edge(step_pk("prepare-meeting@v2", 3), "REFERENCES", target,
                  {"entity": "STEP", "type": "click_ui"})
    repo.put_edge(step_pk("prepare-meeting@v1", 3), "REFERENCES", target,
                  {"entity": "STEP", "type": "click_ui"})
    repo.put_edge(ticket_pk("t_881"), "ASKS_ABOUT", target, {"entity": "TICKET"})

    edges = repo.query_by_target(target)
    assert len(edges) == 3

    step_edges = [
        e for e in edges
        if e["PK"].startswith("STEP#") and e["SK"].startswith("REFERENCES#")
    ]
    assert sorted(e["PK"] for e in step_edges) == [
        "STEP#prepare-meeting@v1#3",
        "STEP#prepare-meeting@v2#3",
    ]


def test_query_by_target_reads_every_page(paged_repo) -> None:
    target = feature_pk("Prepare")
    for n in range(1, 6):
        paged_repo.put_edge(step_pk(f"demo@v{n}", 1), "REFERENCES", target,
                            {"entity": "STEP"})
    assert len(paged_repo.query_by_target(target)) == 5


def test_query_by_target_returns_empty_for_unknown_target(repo) -> None:
    assert repo.query_by_target(feature_pk("Nobody")) == []


def test_scan_entity_reads_every_page_even_with_empty_pages(paged_repo) -> None:
    """Scan 加了篩選以後，中間可能有 0 筆的一頁，但還是有下一頁。"""
    for n in range(1, 4):
        paged_repo.put_meta(ticket_pk(f"t_{n}"), {"entity": "TICKET", "text": f"第 {n} 筆"})
        paged_repo.put_meta(version_pk(f"demo@v{n}"), {"entity": "VERSION"})

    tickets = paged_repo.scan_entity("TICKET")
    assert len(tickets) == 3
    assert sorted(t["PK"] for t in tickets) == ["TICKET#t_1", "TICKET#t_2", "TICKET#t_3"]

    versions = paged_repo.scan_entity("VERSION")
    assert len(versions) == 3


def test_scan_entity_ignores_other_entities(repo) -> None:
    repo.put_meta(ticket_pk("t_1"), {"entity": "TICKET"})
    repo.put_meta(feature_pk("Prepare"), {"entity": "FEATURE"})
    assert len(repo.scan_entity("FEATURE")) == 1
    assert repo.scan_entity("RULE") == []
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：

```bash
uv run pytest tests/integration/test_repository_index.py -v
```

預期：FAIL，`AttributeError: 'Repository' object has no attribute 'query_by_target'`。

- [ ] **步驟 3：寫最少的程式讓測試通過**

把 import 區的 conditions 那行改成：

```python
from boto3.dynamodb.conditions import Attr, Key
```

把下面兩個方法貼進 `class Repository`，接在 `query_pk` 之後：

```python
    def query_by_target(self, target_pk: str) -> list[dict]:
        """用 by_target 索引反查「誰指向這個終點」（讀完所有分頁）。

        GSI 只有最終一致讀取，不能要求 ConsistentRead，
        剛寫進去的邊有可能還沒出現在索引裡（設計文件 §10）。
        因為投影是 KEYS_ONLY，回傳的字典只有 PK、SK、target 三個鍵；
        需要內容時拿 PK 回基表用 get_meta 或 query_pk 一致讀取。
        """
        return self._paged(
            self.table.query,
            {
                "IndexName": "by_target",
                "KeyConditionExpression": Key("target").eq(target_pk),
            },
        )

    def scan_entity(self, entity: str) -> list[dict]:
        """整張表掃過一遍，只留下 entity 等於指定值的 item（讀完所有分頁）。

        Scan 很慢，設計文件 §10 只允許 MVP 的少量資料這樣用。
        """
        return self._paged(
            self.table.scan,
            {"FilterExpression": Attr("entity").eq(entity)},
        )
```

- [ ] **步驟 4：再跑一次測試，確認通過**

```bash
uv run pytest tests/integration/test_repository_index.py -v
```

預期：`5 passed`。

- [ ] **步驟 5：commit**

```bash
git add src/training_kb/repository.py tests/integration/test_repository_index.py
git commit -m "feat(repository): 加入 by_target 反查與 entity Scan"
```

---

### Task 6：交易寫入、原子計數器與設定清單

**目的**：提供「多筆一起成功或一起失敗」的寫入、「絕對不會算錯的加一」、以及可擴充的核定類別表讀取。

**檔案**：
- 修改：`src/training_kb/repository.py`
- 新增：`tests/integration/test_repository_transact.py`

**介面**：
- 消費：`repository.serialize_item`、`training_kb.keys.counter_pk`、`training_kb.keys.config_pk`
- 產出：
  - `Repository.transact_write(self, actions: list[dict]) -> None`（條件失敗拋 `PermanentError`）
  - `Repository.next_counter(self, name: str) -> int`
  - `Repository.get_config_list(self, name: str, default: list[str]) -> list[str]`

- [ ] **步驟 1：寫測試**

`tests/integration/test_repository_transact.py`：

```python
"""交易寫入、原子計數器與設定清單。"""

from __future__ import annotations

import pytest
from training_kb.errors import PermanentError
from training_kb.keys import config_pk, tutorial_pk, version_pk
from training_kb.repository import serialize_item


def _put_action(repo, pk: str, attrs: dict, *, if_not_exists: bool = False) -> dict:
    action: dict = {
        "Put": {
            "TableName": repo.table_name,
            "Item": serialize_item({**attrs, "PK": pk, "SK": "META"}),
        }
    }
    if if_not_exists:
        action["Put"]["ConditionExpression"] = "attribute_not_exists(PK)"
    return action


def test_transact_write_commits_all_actions(repo) -> None:
    repo.transact_write(
        [
            _put_action(repo, version_pk("prepare-meeting@v1"),
                        {"entity": "VERSION", "published_at": "2026-08-01T00:00:00Z"}),
            _put_action(repo, tutorial_pk("prepare-meeting"),
                        {"entity": "TUTORIAL", "current_version": "prepare-meeting@v1"}),
        ]
    )
    assert repo.get_meta(version_pk("prepare-meeting@v1")) is not None
    tutorial = repo.get_meta(tutorial_pk("prepare-meeting"))
    assert tutorial is not None
    assert tutorial["current_version"] == "prepare-meeting@v1"


def test_transact_write_rolls_back_when_one_condition_fails(repo) -> None:
    repo.put_meta(tutorial_pk("prepare-meeting"), {"entity": "TUTORIAL"})
    with pytest.raises(PermanentError):
        repo.transact_write(
            [
                _put_action(repo, version_pk("prepare-meeting@v1"), {"entity": "VERSION"}),
                _put_action(repo, tutorial_pk("prepare-meeting"),
                            {"entity": "TUTORIAL"}, if_not_exists=True),
            ]
        )
    # 第一個動作也一起被取消了，所以 VERSION 不存在。
    assert repo.get_meta(version_pk("prepare-meeting@v1")) is None


def test_transact_write_accepts_empty_list(repo) -> None:
    repo.transact_write([])


def test_next_counter_starts_at_one_and_increases(repo) -> None:
    assert repo.next_counter("cluster") == 1
    assert repo.next_counter("cluster") == 2
    assert repo.next_counter("cluster") == 3


def test_next_counter_is_independent_per_name(repo) -> None:
    assert repo.next_counter("cluster") == 1
    assert repo.next_counter("asl:ticket-analysis") == 1
    assert repo.next_counter("cluster") == 2


def test_get_config_list_returns_default_when_absent(repo) -> None:
    assert repo.get_config_list("approved_categories", ["找不到按鈕", "缺少資訊"]) == [
        "找不到按鈕",
        "缺少資訊",
    ]


def test_get_config_list_reads_stored_values(repo) -> None:
    repo.put_meta(
        config_pk("approved_categories"),
        {"entity": "CONFIG", "values": ["找不到按鈕", "缺少資訊", "步驟太長"]},
    )
    assert repo.get_config_list("approved_categories", ["找不到按鈕"]) == [
        "找不到按鈕",
        "缺少資訊",
        "步驟太長",
    ]


def test_get_config_list_falls_back_when_values_empty(repo) -> None:
    repo.put_meta(config_pk("approved_categories"), {"entity": "CONFIG", "values": []})
    assert repo.get_config_list("approved_categories", ["找不到按鈕"]) == ["找不到按鈕"]
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：

```bash
uv run pytest tests/integration/test_repository_transact.py -v
```

預期：FAIL，`AttributeError: 'Repository' object has no attribute 'transact_write'`。

- [ ] **步驟 3：寫最少的程式讓測試通過**

把 import 區的 keys 那行改成：

```python
from .keys import META, config_pk, counter_pk, edge_sk
```

把下面三個方法貼進 `class Repository`，接在 `scan_entity` 之後：

```python
    def transact_write(self, actions: list[dict]) -> None:
        """一次送出多個寫入，全部成功或全部失敗。

        actions 是 DynamoDB 低階格式的 TransactItems，例如：
            {"Put": {"TableName": repo.table_name,
                     "Item": serialize_item({...}),
                     "ConditionExpression": "attribute_not_exists(PK)"}}
        用 serialize_item() 把一般字典轉成低階格式。

        任何一個條件不成立，整批都不會寫入，並拋 PermanentError。
        """
        if not actions:
            return
        if len(actions) > 100:
            raise PermanentError(f"一次交易最多 100 個動作，收到 {len(actions)} 個")
        try:
            self.client.transact_write_items(TransactItems=actions)
        except ClientError as exc:
            code = exc.response["Error"]["Code"]
            if code in ("TransactionCanceledException", "ConditionalCheckFailedException"):
                reasons = [
                    reason.get("Code", "")
                    for reason in exc.response.get("CancellationReasons", [])
                ]
                raise PermanentError(f"交易被取消（{code}）：{reasons}") from exc
            raise

    def next_counter(self, name: str) -> int:
        """在資料庫裡原子遞增一個計數器，從 1 開始。

        ADD 是 DynamoDB 內建的加法：兩個程式同時呼叫也不會拿到同一個號碼。
        千萬不要改成「先 get 再 put」，那樣一定會重號。
        注意 SET 與 ADD 不能操作同一個屬性，所以 entity 與 value 分開寫。
        """
        response = self.table.update_item(
            Key={"PK": counter_pk(name), "SK": META},
            UpdateExpression="SET #e = :entity ADD #v :one",
            ExpressionAttributeNames={"#e": "entity", "#v": "value"},
            ExpressionAttributeValues={":entity": "COUNTER", ":one": Decimal(1)},
            ReturnValues="UPDATED_NEW",
        )
        return int(response["Attributes"]["value"])

    def get_config_list(self, name: str, default: list[str]) -> list[str]:
        """讀 CONFIG#<name> 的 values 清單；沒設定或設定成空的就回傳 default。

        對應 D13：核定的 Feedback Category 表是可擴充的，初始值寫在程式裡。
        """
        item = self.get_meta(config_pk(name))
        if item is None:
            return list(default)
        values = item.get("values")
        if not isinstance(values, list) or not values:
            return list(default)
        return [str(value) for value in values]
```

- [ ] **步驟 4：再跑一次測試，確認通過**

```bash
uv run pytest tests/integration/test_repository_transact.py -v
```

預期：`8 passed`。

- [ ] **步驟 5：commit**

```bash
git add src/training_kb/repository.py tests/integration/test_repository_transact.py
git commit -m "feat(repository): 加入交易寫入、計數器與設定清單"
```

---

### Task 7：S3 讀寫與條件寫入

**目的**：存教學全文、diff 與操作紀錄；並且用 `If-None-Match` 防止同一個 key 被蓋掉。

**檔案**：
- 修改：`src/training_kb/repository.py`
- 新增：`tests/integration/test_repository_s3.py`

**介面**：
- 消費：無
- 產出：
  - `Repository.put_object(self, key: str, body: bytes | str, *, if_none_match: bool = False, content_type: str = "text/plain; charset=utf-8") -> bool`
  - `Repository.get_object(self, key: str) -> bytes | None`
  - `Repository.object_exists(self, key: str) -> bool`

- [ ] **步驟 1：寫測試**

`tests/integration/test_repository_s3.py`：

```python
"""S3 讀寫與條件寫入。"""

from __future__ import annotations


def test_put_and_get_object_round_trip(repo) -> None:
    written = repo.put_object("tutorials/prepare-meeting/v1.md", "# 準備會議\n")
    assert written is True
    assert repo.get_object("tutorials/prepare-meeting/v1.md") == "# 準備會議\n".encode()


def test_put_object_accepts_bytes(repo) -> None:
    repo.put_object("tutorials/prepare-meeting/v1.diff", b"")
    assert repo.get_object("tutorials/prepare-meeting/v1.diff") == b""


def test_get_object_returns_none_when_missing(repo) -> None:
    assert repo.get_object("tutorials/nothing/v9.md") is None


def test_object_exists(repo) -> None:
    assert repo.object_exists("tutorials/prepare-meeting/v1.md") is False
    repo.put_object("tutorials/prepare-meeting/v1.md", "# 準備會議\n")
    assert repo.object_exists("tutorials/prepare-meeting/v1.md") is True


def test_put_object_if_none_match_refuses_to_overwrite(repo) -> None:
    """設計文件 §8.3：同 key 已存在時不盲目重寫。"""
    first = repo.put_object("tutorials/a/v1.md", "原本的內容", if_none_match=True)
    second = repo.put_object("tutorials/a/v1.md", "想要蓋掉的內容", if_none_match=True)
    assert first is True
    assert second is False
    assert repo.get_object("tutorials/a/v1.md") == "原本的內容".encode()


def test_put_object_without_condition_overwrites(repo) -> None:
    repo.put_object("tutorials/a/v1.md", "舊的")
    repo.put_object("tutorials/a/v1.md", "新的")
    assert repo.get_object("tutorials/a/v1.md") == "新的".encode()


def test_put_object_sets_content_type(repo) -> None:
    repo.put_object(
        "site/prepare-meeting/v1.html",
        "<h1>準備會議</h1>",
        content_type="text/html; charset=utf-8",
    )
    head = repo.s3.head_object(
        Bucket=repo.bucket, Key="site/prepare-meeting/v1.html"
    )
    assert head["ContentType"] == "text/html; charset=utf-8"
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：

```bash
uv run pytest tests/integration/test_repository_s3.py -v
```

預期：FAIL，`AttributeError: 'Repository' object has no attribute 'put_object'`。

- [ ] **步驟 3：寫最少的程式讓測試通過**

把下面三個方法貼進 `class Repository`，接在 `get_config_list` 之後：

```python
    # --------------------------------------------------------------------- S3
    def put_object(
        self,
        key: str,
        body: bytes | str,
        *,
        if_none_match: bool = False,
        content_type: str = "text/plain; charset=utf-8",
    ) -> bool:
        """寫一個 S3 物件。

        if_none_match=True 時帶上 HTTP 標頭 If-None-Match: *，
        代表「只有這個 key 還不存在時才寫」。
        已存在 -> S3 回 412 PreconditionFailed -> 這裡回傳 False。
        併發時剛好有人刪掉 -> 409 ConditionalRequestConflict -> 也回傳 False。
        """
        data = body.encode("utf-8") if isinstance(body, str) else body
        kwargs: dict[str, Any] = {
            "Bucket": self.bucket,
            "Key": key,
            "Body": data,
            "ContentType": content_type,
        }
        if if_none_match:
            kwargs["IfNoneMatch"] = "*"
        try:
            self.s3.put_object(**kwargs)
        except ClientError as exc:
            code = exc.response["Error"]["Code"]
            if code in ("PreconditionFailed", "ConditionalRequestConflict"):
                return False
            raise
        return True

    def get_object(self, key: str) -> bytes | None:
        """讀一個 S3 物件的內容；不存在回傳 None。"""
        try:
            response = self.s3.get_object(Bucket=self.bucket, Key=key)
        except ClientError as exc:
            if exc.response["Error"]["Code"] in ("NoSuchKey", "404", "NotFound"):
                return None
            raise
        return response["Body"].read()

    def object_exists(self, key: str) -> bool:
        """只看這個 key 在不在，不下載內容。"""
        try:
            self.s3.head_object(Bucket=self.bucket, Key=key)
        except ClientError as exc:
            if exc.response["Error"]["Code"] in ("404", "NoSuchKey", "NotFound"):
                return False
            raise
        return True
```

- [ ] **步驟 4：再跑一次測試，確認通過**

```bash
uv run pytest tests/integration/test_repository_s3.py -v
```

預期：`7 passed`。如果 `test_put_object_if_none_match_refuses_to_overwrite` 失敗（第二次也回 `True`），代表你的 moto 版本低於 5.0.14，執行 `uv add --dev "moto[s3,dynamodb]>=5.0.14"` 升級。

- [ ] **步驟 5：commit**

```bash
git add src/training_kb/repository.py tests/integration/test_repository_s3.py
git commit -m "feat(repository): 加入 S3 讀寫與條件寫入"
```

---

### Task 8：操作紀錄（去重的地基）

**目的**：讓「同一個事件送兩次」只被處理一次，並且把第一次的輸出（含分配到的版號）保存下來給重試重用。

**檔案**：
- 修改：`src/training_kb/repository.py`
- 新增：`tests/integration/test_repository_ops.py`

**介面**：
- 消費：`Repository.put_meta`、`Repository.put_object`、`Repository.get_object`、`training_kb.keys.ops_pk`
- 產出：
  - `Repository.begin_operation(self, operation_id: str, record: dict) -> bool`
  - `Repository.load_operation(self, operation_id: str) -> dict | None`
  - `Repository.update_operation(self, operation_id: str, patch: dict) -> None`
  - `Repository.operation_key(self, operation_id: str) -> str`（新增：把 operation_id 轉成 S3 key，`:` 換成 `_`）

> 這一組是 **本計劃選擇（對應 O2）**。設計文件第 18 節明說操作紀錄的儲存形狀還沒定案；本計劃選擇「DynamoDB 條件寫入負責去重、S3 JSON 負責保存完整輸出」，並且要到 Phase 24 用注入失敗與重送驗證之後，才可以說這套機制成立。

- [ ] **步驟 1：寫測試**

`tests/integration/test_repository_ops.py`：

```python
"""操作紀錄：去重、保存原輸出、更新狀態。"""

from __future__ import annotations

import pytest
from training_kb.errors import PermanentError
from training_kb.keys import ops_pk


def test_begin_operation_first_time_returns_true(repo) -> None:
    started = repo.begin_operation(
        "ingest:ticket:t_881",
        {"status": "started", "kind": "ticket", "created_at": "2026-08-01T00:00:00Z"},
    )
    assert started is True
    assert repo.get_meta(ops_pk("ingest:ticket:t_881")) is not None


def test_begin_operation_second_time_returns_false(repo) -> None:
    """對應 F09／接入來源事件.feature Rule 30：同一事件重送只處理一次。"""
    repo.begin_operation("ingest:ticket:t_881", {"status": "started", "attempt": 1})
    again = repo.begin_operation("ingest:ticket:t_881", {"status": "started", "attempt": 2})
    assert again is False
    item = repo.get_meta(ops_pk("ingest:ticket:t_881"))
    assert item is not None
    assert item["attempt"] == 1


def test_begin_operation_also_writes_s3_copy(repo) -> None:
    repo.begin_operation("create:version:prepare-meeting", {"status": "started"})
    key = repo.operation_key("create:version:prepare-meeting")
    assert key == "operations/create_version_prepare-meeting.json"
    assert repo.object_exists(key) is True


def test_load_operation_returns_saved_record(repo) -> None:
    repo.begin_operation(
        "create:version:prepare-meeting",
        {"status": "started", "version_id": "prepare-meeting@v2"},
    )
    record = repo.load_operation("create:version:prepare-meeting")
    assert record is not None
    assert record["status"] == "started"
    assert record["version_id"] == "prepare-meeting@v2"
    assert record["operation_id"] == "create:version:prepare-meeting"


def test_load_operation_returns_none_when_never_started(repo) -> None:
    assert repo.load_operation("ingest:ticket:never") is None


def test_update_operation_merges_patch(repo) -> None:
    repo.begin_operation("create:version:a", {"status": "started", "version_id": "a@v2"})
    repo.update_operation("create:version:a", {"status": "done", "published": True})
    record = repo.load_operation("create:version:a")
    assert record is not None
    assert record["status"] == "done"
    assert record["published"] is True
    assert record["version_id"] == "a@v2"
    item = repo.get_meta(ops_pk("create:version:a"))
    assert item is not None
    assert item["status"] == "done"


def test_update_operation_rejects_unknown_operation(repo) -> None:
    with pytest.raises(PermanentError):
        repo.update_operation("create:version:never", {"status": "done"})


def test_retry_can_reuse_the_original_version_id(repo) -> None:
    """設計文件 §14.2／D26：同一邏輯變更重試時重用原版本號。"""
    operation_id = "create:version:prepare-meeting:gap-c12"
    if repo.begin_operation(operation_id, {"status": "started"}):
        repo.update_operation(operation_id, {"version_id": "prepare-meeting@v2"})

    # 第二次（重試）：begin 回傳 False，改用已保存的版號。
    assert repo.begin_operation(operation_id, {"status": "started"}) is False
    record = repo.load_operation(operation_id)
    assert record is not None
    assert record["version_id"] == "prepare-meeting@v2"
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：

```bash
uv run pytest tests/integration/test_repository_ops.py -v
```

預期：FAIL，`AttributeError: 'Repository' object has no attribute 'begin_operation'`。

- [ ] **步驟 3：寫最少的程式讓測試通過**

在 import 區加一行：

```python
import json
```

把 keys 的 import 改成：

```python
from .keys import META, config_pk, counter_pk, edge_sk, ops_pk
```

在 `class Repository` 上方（模組層級）加一個常數：

```python
OPERATION_PREFIX = "operations/"
```

把下面四個方法貼進 `class Repository`，接在 `object_exists` 之後：

```python
    # ---------------------------------------------------- 操作紀錄（O2 本計劃選擇）
    def operation_key(self, operation_id: str) -> str:
        """把 operation_id 轉成 S3 key。

        operation_id 長得像 "ingest:ticket:t_881"，冒號在網址與檔名裡很麻煩，
        統一換成底線，和 Phase 10 的 execution_name() 用同一套規則。
        """
        return f"{OPERATION_PREFIX}{operation_id.replace(':', '_')}.json"

    def _write_operation_file(self, operation_id: str, record: dict) -> None:
        self.put_object(
            self.operation_key(operation_id),
            json.dumps(record, ensure_ascii=False, sort_keys=True, default=str),
            content_type="application/json; charset=utf-8",
        )

    def begin_operation(self, operation_id: str, record: dict) -> bool:
        """宣告「我要開始做這個操作」。

        回傳 True  = 這是第一次，可以往下做。
        回傳 False = 之前已經開始過了（重送），呼叫端要改用 load_operation()
                     取回既有結果，不可以再做一次。

        去重靠的是 DynamoDB 的條件寫入，不是「先查再寫」——
        後者在兩個請求同時進來時會兩邊都通過。
        record 裡的值要先轉成可以 JSON 化的型別（datetime 請先用 to_iso()）。
        """
        payload = {**dict(record), "entity": "OPS", "operation_id": operation_id}
        if not self.put_meta(ops_pk(operation_id), payload, if_not_exists=True):
            return False
        self._write_operation_file(operation_id, payload)
        return True

    def load_operation(self, operation_id: str) -> dict | None:
        """取回操作紀錄；沒有回傳 None。

        優先讀 S3（內容完整），S3 不在時退回讀 DynamoDB item，
        這樣「DynamoDB 寫成功但 S3 寫失敗」的中間狀態也看得見。
        """
        raw = self.get_object(self.operation_key(operation_id))
        if raw is not None:
            return json.loads(raw.decode("utf-8"))
        item = self.get_meta(ops_pk(operation_id))
        if item is None:
            return None
        return {key: value for key, value in item.items() if key not in ("PK", "SK")}

    def update_operation(self, operation_id: str, patch: dict) -> None:
        """把新的欄位合併進操作紀錄，DynamoDB 與 S3 兩邊都更新。"""
        current = self.load_operation(operation_id)
        if current is None:
            raise PermanentError(f"操作紀錄不存在，不能更新：{operation_id}")
        self.update_meta(ops_pk(operation_id), dict(patch))
        self._write_operation_file(operation_id, {**current, **dict(patch)})
```

- [ ] **步驟 4：再跑一次測試，確認通過**

```bash
uv run pytest tests/integration/test_repository_ops.py -v
```

預期：`8 passed`。

- [ ] **步驟 5：commit**

```bash
git add src/training_kb/repository.py tests/integration/test_repository_ops.py
git commit -m "feat(repository): 加入操作紀錄與去重機制"
```

---

### Task 9：每篇教學的鎖

**目的**：讓同一篇教學的修改排隊進行；程式當掉沒還鎖時，過了存活時間別人可以重新取得。

**檔案**：
- 修改：`src/training_kb/repository.py`
- 新增：`tests/integration/test_repository_lock.py`

**介面**：
- 消費：`training_kb.keys.lock_pk`、`training_kb.clock.to_iso`
- 產出：
  - `Repository.acquire_lock(self, slug: str, owner: str, ttl_seconds: int, now: datetime) -> bool`
  - `Repository.release_lock(self, slug: str, owner: str) -> None`

> 同樣是 **本計劃選擇（對應 O2）**：設計文件 §8.3 說「實際儲存位置與取得寫入順序的機制仍是 O2，不能把條件更新本身當成順序保證」。本階段只提供機制；它是否足夠，要到 Phase 24 才有結論。

- [ ] **步驟 1：寫測試**

`tests/integration/test_repository_lock.py`：

```python
"""每篇教學一把鎖：取得、排隊、過期重取、歸還。"""

from __future__ import annotations

from datetime import UTC, datetime

from training_kb.keys import lock_pk

T0 = datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)


def _plus(seconds: int) -> datetime:
    return datetime.fromtimestamp(T0.timestamp() + seconds, tz=UTC)


def test_first_owner_gets_the_lock(repo) -> None:
    assert repo.acquire_lock("prepare-meeting", "op-1", 60, T0) is True
    item = repo.get_meta(lock_pk("prepare-meeting"))
    assert item is not None
    assert item["owner"] == "op-1"
    assert item["expires_at"] == "2026-08-01T00:01:00Z"


def test_second_owner_is_refused_while_lock_is_alive(repo) -> None:
    repo.acquire_lock("prepare-meeting", "op-1", 60, T0)
    assert repo.acquire_lock("prepare-meeting", "op-2", 60, _plus(10)) is False
    item = repo.get_meta(lock_pk("prepare-meeting"))
    assert item is not None
    assert item["owner"] == "op-1"


def test_expired_lock_can_be_taken_over(repo) -> None:
    repo.acquire_lock("prepare-meeting", "op-1", 60, T0)
    assert repo.acquire_lock("prepare-meeting", "op-2", 60, _plus(61)) is True
    item = repo.get_meta(lock_pk("prepare-meeting"))
    assert item is not None
    assert item["owner"] == "op-2"


def test_same_owner_can_reacquire_its_own_lock(repo) -> None:
    """同一次操作重試時，不應該被自己鎖在門外。"""
    repo.acquire_lock("prepare-meeting", "op-1", 60, T0)
    assert repo.acquire_lock("prepare-meeting", "op-1", 60, _plus(5)) is True


def test_release_lock_lets_the_next_owner_in(repo) -> None:
    repo.acquire_lock("prepare-meeting", "op-1", 60, T0)
    repo.release_lock("prepare-meeting", "op-1")
    assert repo.get_meta(lock_pk("prepare-meeting")) is None
    assert repo.acquire_lock("prepare-meeting", "op-2", 60, _plus(1)) is True


def test_release_lock_does_nothing_when_owner_differs(repo) -> None:
    repo.acquire_lock("prepare-meeting", "op-1", 60, T0)
    repo.release_lock("prepare-meeting", "op-2")
    item = repo.get_meta(lock_pk("prepare-meeting"))
    assert item is not None
    assert item["owner"] == "op-1"


def test_locks_are_per_tutorial(repo) -> None:
    assert repo.acquire_lock("prepare-meeting", "op-1", 60, T0) is True
    assert repo.acquire_lock("share-summary", "op-2", 60, T0) is True
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：

```bash
uv run pytest tests/integration/test_repository_lock.py -v
```

預期：FAIL，`AttributeError: 'Repository' object has no attribute 'acquire_lock'`。

- [ ] **步驟 3：寫最少的程式讓測試通過**

在 import 區加入：

```python
from datetime import UTC, datetime
```

並把 keys 的 import 改成：

```python
from .keys import META, config_pk, counter_pk, edge_sk, lock_pk, ops_pk
```

再加一行：

```python
from .clock import to_iso
```

把下面兩個方法貼進 `class Repository`，接在 `update_operation` 之後：

```python
    # -------------------------------------------------------- 鎖（O2 本計劃選擇）
    def acquire_lock(
        self,
        slug: str,
        owner: str,
        ttl_seconds: int,
        now: datetime,
    ) -> bool:
        """嘗試取得某篇教學的鎖。拿到回傳 True，別人正拿著回傳 False。

        條件是三選一成立：
        1. 這把鎖還不存在。
        2. 鎖已經過期（expires_epoch <= 現在）。
        3. 拿鎖的人就是自己（同一次操作重試）。

        存兩份時間：expires_epoch 是數字，給條件運算式比大小用；
        expires_at 是 ISO 字串，給人看的。now 必須是 tz-aware 的 UTC 時間。
        """
        now_epoch = int(now.timestamp())
        expires_epoch = now_epoch + int(ttl_seconds)
        item = {
            "PK": lock_pk(slug),
            "SK": META,
            "entity": "LOCK",
            "owner": owner,
            "acquired_at": to_iso(now),
            "expires_at": to_iso(datetime.fromtimestamp(expires_epoch, tz=UTC)),
            "expires_epoch": expires_epoch,
        }
        try:
            self.table.put_item(
                Item=item,
                ConditionExpression=(
                    "attribute_not_exists(PK) OR #e <= :now OR #o = :owner"
                ),
                ExpressionAttributeNames={"#e": "expires_epoch", "#o": "owner"},
                ExpressionAttributeValues={":now": now_epoch, ":owner": owner},
            )
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
                return False
            raise
        return True

    def release_lock(self, slug: str, owner: str) -> None:
        """歸還鎖。只有自己是持有人時才真的刪掉；別人的鎖不動也不報錯。"""
        try:
            self.table.delete_item(
                Key={"PK": lock_pk(slug), "SK": META},
                ConditionExpression="#o = :owner",
                ExpressionAttributeNames={"#o": "owner"},
                ExpressionAttributeValues={":owner": owner},
            )
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
                return
            raise
```

- [ ] **步驟 4：再跑一次測試，確認通過**

```bash
uv run pytest tests/integration/test_repository_lock.py -v
```

預期：`7 passed`。

- [ ] **步驟 5：commit**

```bash
git add src/training_kb/repository.py tests/integration/test_repository_lock.py
git commit -m "feat(repository): 加入每篇教學的 TTL 鎖"
```

---

### Task 10：`build_repository` 與整體檢查

**目的**：提供一個從 `Settings` 直接組出 `Repository` 的入口，並且確認整份程式碼通過 ruff 與全部測試。

**檔案**：
- 修改：`src/training_kb/repository.py`
- 新增：`tests/integration/test_repository_build.py`

**介面**：
- 消費：`training_kb.config.Settings`
- 產出：`repository.build_repository(settings: Settings) -> Repository`

- [ ] **步驟 1：寫測試**

`tests/integration/test_repository_build.py`：

```python
"""build_repository 從 Settings 組出可用的 Repository。"""

from __future__ import annotations

from training_kb.keys import feature_pk
from training_kb.repository import Repository, build_repository


def test_build_repository_uses_settings(dynamodb_table, s3_client, test_settings) -> None:
    repo = build_repository(test_settings)
    assert isinstance(repo, Repository)
    assert repo.table_name == "training_kb"
    assert repo.bucket == "training-kb-content-test"
    assert repo.page_size is None


def test_built_repository_can_read_and_write(dynamodb_table, s3_client, test_settings) -> None:
    repo = build_repository(test_settings)
    repo.put_meta(feature_pk("Prepare"), {"entity": "FEATURE", "name": "Prepare"})
    item = repo.get_meta(feature_pk("Prepare"))
    assert item is not None
    assert item["name"] == "Prepare"

    repo.put_object("operations/smoke.json", "{}")
    assert repo.get_object("operations/smoke.json") == b"{}"
```

注意測試同時要求 `dynamodb_table` 與 `s3_client` 兩個 fixture：它們負責在 `mock_aws()` 裡把表與 bucket 建好，`build_repository` 才連得上。

- [ ] **步驟 2：跑測試，確認它失敗**

執行：

```bash
uv run pytest tests/integration/test_repository_build.py -v
```

預期：FAIL，`ImportError: cannot import name 'build_repository' from 'training_kb.repository'`。

- [ ] **步驟 3：寫最少的程式讓測試通過**

在 import 區加入：

```python
import boto3

from .config import Settings
```

在檔案最後（`__all__` 之前）加入：

```python
def build_repository(settings: Settings) -> Repository:
    """用 Settings 組出正式用的 Repository（連真正的 AWS）。

    測試不要呼叫這個函式來造假環境；測試用 tests/conftest.py 的 repo fixture。
    """
    table = boto3.resource("dynamodb", region_name=settings.aws_region).Table(
        settings.table_name
    )
    s3 = boto3.client("s3", region_name=settings.aws_region)
    return Repository(table, s3, settings.bucket_name)
```

並把檔案最後的 `__all__` 換成：

```python
__all__ = [
    "OPERATION_PREFIX",
    "Repository",
    "build_repository",
    "decode_numbers",
    "deserialize_item",
    "encode_numbers",
    "serialize_item",
]
```

- [ ] **步驟 4：再跑一次測試，確認通過**

```bash
uv run pytest tests/integration/test_repository_build.py -v
uv run pytest -q
uv run ruff check .
uv run ruff format .
```

預期：第一行 `2 passed`；第二行全部通過（本階段新增約 60 個測試）；`ruff check` 印出 `All checks passed!`；`ruff format` 印出被格式化的檔案數。如果 `ruff format` 改動了檔案，再跑一次 `uv run pytest -q` 確認仍然全綠。

- [ ] **步驟 5：commit**

```bash
git add src/training_kb/repository.py tests/integration/test_repository_build.py
git commit -m "feat(repository): 加入 build_repository 入口"
```

---

## 7. 完成檢查清單

逐條打勾，每一條都要真的跑過指令看到結果，不能用「應該可以」帶過。

- [ ] `uv run pytest -q` 全綠，且 `tests/integration/` 下有 8 個測試檔。
- [ ] `uv run ruff check .` 沒有錯誤。
- [ ] `uv run pytest tests/integration/test_repository_query.py::test_query_pk_reads_every_page -v` 通過 —— 證明分頁真的有第二頁、而且有讀完（對應設計文件 §10「所有 Query／Scan 都必須讀完分頁」）。
- [ ] `uv run pytest tests/integration/test_repository_index.py::test_scan_entity_reads_every_page_even_with_empty_pages -v` 通過 —— 證明空的一頁不會提早結束。
- [ ] `uv run pytest tests/integration/test_repository_meta.py::test_put_meta_if_not_exists_returns_false_on_duplicate -v` 通過 —— 重複寫入回傳 `False` 且不覆蓋。
- [ ] `uv run pytest tests/integration/test_repository_update.py::test_update_meta_with_wrong_condition_raises -v` 通過 —— 條件不符拋 `PermanentError` 且資料沒被改。
- [ ] `uv run pytest tests/integration/test_repository_s3.py::test_put_object_if_none_match_refuses_to_overwrite -v` 通過 —— 同 key 第二次寫入回 `False`，內容仍是第一次的。
- [ ] `uv run pytest tests/integration/test_repository_transact.py::test_next_counter_starts_at_one_and_increases -v` 通過 —— 計數器從 1 開始、每次加一。
- [ ] `uv run pytest tests/integration/test_repository_ops.py::test_begin_operation_second_time_returns_false -v` 通過 —— 重送回傳 `False`，第一次的內容不被覆蓋。
- [ ] `uv run pytest tests/integration/test_repository_lock.py::test_expired_lock_can_be_taken_over -v` 通過 —— 鎖過期後可以被別人取得。
- [ ] `uv run python -c "from training_kb.repository import build_repository; print(build_repository.__doc__.splitlines()[0])"` 印出說明文字 —— 模組可以正常匯入。
- [ ] 手動確認 `git status --short` 沒有漏掉未加入的檔案。

對應設計文件第 16 節切片 S0 的檢查項目「O2／O3 的最小整合驗證有可追溯結果」：本階段只完成 **O2 的機制**（操作紀錄與鎖），還沒有做失敗注入驗證。S0 要整個完成，還需要 Phase 04（AWS 資源與模型可用性）與 Phase 24（失敗復原驗收）。**不要在這裡宣稱 O2 已經驗證完畢。**

---

## 8. 常見錯誤與排除

**症狀 1：`TypeError: Float types are not supported. Use Decimal types instead.`**

- 原因：把 Python 的 `float`（例如 embedding 的 `0.1`）直接丟給 boto3 的 DynamoDB resource。DynamoDB 的數字型別要求精確表示，boto3 不接受 `float`。
- 解法：確認你走的是 `repo.put_meta(...)`（裡面呼叫了 `encode_numbers`），而不是自己呼叫 `table.put_item(...)`。如果是新的方法忘了轉，在寫入前補上 `encode_numbers(...)`。

**症狀 2：`ClientError: ... Inexact / Rounded`（寫 embedding 時）**

- 原因：用了 `Decimal(0.1)` 而不是 `Decimal(str(0.1))`。`Decimal(0.1)` 會把 float 的二進位誤差展開成 55 位十進位數，超過 DynamoDB 的 38 位有效數字上限。
- 解法：`encode_numbers` 裡一定是 `Decimal(str(value))`。不要「優化」成 `Decimal(value)`。

**症狀 3：`ValidationException: Invalid UpdateExpression: Attribute name is a reserved keyword; reserved keyword: status`**

- 原因：把欄位名直接寫進 `UpdateExpression` 或 `ConditionExpression`，而那個名字是 DynamoDB 的保留字（`status`、`owner`、`name`、`source`、`text`、`timestamp`、`value`… 共五百多個）。
- 解法：一律用 `#a0` 這種佔位符搭配 `ExpressionAttributeNames`。本階段的 `update_meta`、`next_counter`、`acquire_lock` 都已經這樣寫了；你自己新增方法時也要照做。

**症狀 4：測試跑出 `NoCredentialsError`，或是你在真正的 AWS 帳單上看到新資源**

- 原因：boto3 client 在 `mock_aws()` 啟動之前就建立了。moto 是靠「攔截之後建立的 client」運作的，順序反了就攔不到。
- 解法：所有 `boto3.client(...)` / `boto3.resource(...)` 都要寫在 `mocked_aws` fixture 之後（也就是該 fixture 要放進參數列）。另外確認 `aws_credentials` fixture 有執行到，它會塞假金鑰並移除 `AWS_PROFILE`。

**症狀 5：`ResourceNotFoundException: Requested resource not found`**

- 原因：測試忘了要求 `dynamodb_table` fixture，或者程式用的表名與 fixture 建的不同。
- 解法：測試函式的參數要包含 `repo`（它會連帶帶進 `dynamodb_table`、`s3_client`）。如果是直接用 `build_repository`，要同時要求 `dynamodb_table` 與 `s3_client` 兩個 fixture。

**症狀 6：`query_by_target` 找不到剛剛 `put_edge` 進去的邊**

- 原因：GSI 是最終一致的，寫入之後索引要一小段時間才更新。moto 通常會馬上反映，但真實 AWS 不會。
- 解法：這不是 bug，是 DynamoDB 的本質（設計文件 §10 明講）。需要立刻看到完整結果的地方（例如改版前核對引用集合），要改用基表一致讀取 `query_pk(..., consistent=True)`。**不要用「多等幾秒」當解法**，設計文件 §10 明確禁止這樣宣稱結果完整。

**症狀 7：`test_put_object_if_none_match_refuses_to_overwrite` 第二次也回傳 `True`**

- 原因：moto 版本低於 5.0.14，還沒實作 S3 的條件寫入，所以 `IfNoneMatch` 被忽略了。
- 解法：`uv add --dev "moto[s3,dynamodb]>=5.0.14"` 後重跑。用 `uv run python -c "import moto; print(moto.__version__)"` 確認版本。

**症狀 8：`query_pk` 只拿回一部分資料**

- 原因：自己寫了新的查詢方法卻沒有走 `_paged`，直接回傳 `response["Items"]`。
- 解法：所有 Query/Scan 一律透過 `self._paged(...)`。想驗證有沒有讀完，把 `Repository` 換成 `paged_repo`（`page_size=2`）再跑一次測試。

**症狀 9：`transact_write` 拋出 `PermanentError` 但看不出是哪一個動作失敗**

- 原因：`TransactionCanceledException` 的細節在 `CancellationReasons` 裡，每個動作一個項目。
- 解法：本階段的實作已經把 `CancellationReasons` 的 `Code` 清單放進錯誤訊息。清單裡 `ConditionalCheckFailed` 的位置就是失敗的那個動作的索引，`None` 代表那個動作本身沒問題。

---

## 9. 這階段不做的事

| 不做的事 | 留給哪一階段 |
|---|---|
| `get_tutorial`、`get_version`、`get_steps`、`list_feedback_of_version` 等「固定讀取」函式（會回傳 pydantic 物件而不是 dict） | Phase 09（`09-Phase09-圖譜查詢與backfill.md`）；Phase 07、08、13 會先實作各自用得到的少數幾個 |
| `backfill_references` 與 `BackfillReport` | Phase 09 |
| 建立真正的 AWS 資源（CDK、`cdk deploy`） | Phase 04（`04-Phase04-AWS基礎建設與模型可用性確認.md`） |
| 版本分配、內容驗證、`create_version`、`publish`、`retire` | Phase 07、08 |
| `with_tutorial_lock`（用本階段的鎖包住一段程式） | Phase 08（`08-Phase08-Content-發布與退役.md`） |
| 決定哪些 `operation_id` 要怎麼命名（`ingest:ticket:<id>` 等） | Phase 10（`10-Phase10-Ingress-驗簽驗證與去重.md`） |
| 用注入失敗驗證 O2、O3 是否真的守得住 | Phase 24（`24-Phase24-失敗復原與重送驗收.md`） |
| 指標計算、規則狀態寫入 | Phase 19、20 |
| DynamoDB 的 TTL 自動刪除設定（本階段的鎖是靠條件運算式判斷過期，不靠 AWS 自動刪） | 不做；如果 Phase 04 想加 TTL 屬性，可以指向 `expires_epoch`，但判斷邏輯不改 |

---

## 10. 對照：設計章節與 Rule 編號

| Rule 來源檔 | Rule 編號與原文 | 本階段哪個 Task 落實 |
|---|---|---|
| `查詢知識圖譜.feature` | Rule 1：查詢某起點的關係使用該起點的 PK | Task 4（`query_pk`） |
| `查詢知識圖譜.feature` | Rule 2：查詢誰引用 Feature 時使用 by_target 的 target | Task 5（`query_by_target`）；完整的「只取 STEP／REFERENCES」篩選在 Phase 09 |
| `查詢知識圖譜.feature` | Rule 3：沿 Feature 關係邊反查不呼叫 AI | Task 5（`query_by_target` 只做 Query，沒有任何模型呼叫） |
| `建立教學版本.feature` | Rule 8：建立 TutorialStep 時保存 references Feature 邊 | Task 4 提供 `put_edge` 機制；實際寫入在 Phase 07 |
| `建立教學版本.feature` | Rule 10：references 邊的 target 等於 SK 中的關係終點 | Task 4（`put_edge` 的 `target` 由 `target_pk` 決定，不接受 `attrs` 覆寫；有測試 `test_put_edge_writes_target_matching_sk`） |
| `接入來源事件.feature` | Rule 30：同一正規化事件重送時只處理一次 | Task 8 提供 `begin_operation` 去重機制；判定與回應在 Phase 10 |
| `執行教學流程.feature` | Rule 10：Step Functions 的 ASL 版本快照存於 `stepfunctions/<pipeline>/v<n>.json` | Task 6（`next_counter`）與 Task 7（`put_object`）提供版本號與寫入機制；實際快照在 Phase 14 |
| `提出教學規則.feature` | Rule 4：Authoring Rule 記錄 derived_from 來源版本 | Task 2（`put_meta` 能保存裸 ID 欄位）；規則內容在 Phase 18 |
| `收集教學回饋.feature` | Rule 5：Feedback Category 必須屬於核定類別表或待分類 | Task 6（`get_config_list` 提供可擴充的核定類別表，對應 D13）；判定在 Phase 15 |
| `檢視學習指標.feature` | Rule 8：規則套用次數等於 applied_to 清單長度 | Task 4（`put_edge` 的 `APPLIED_TO` 邊）與 Task 5（反查）；計算在 Phase 19 |

設計文件章節對照：

| 設計章節 | 本階段落實處 |
|---|---|
| §9.1 鍵與原生型別（表名、PK/SK、`by_target`、List/Map 原生型別、1024 維 embedding） | Task 1 的 fixture、Task 2 的型別轉換 |
| §9.2 關係邊（`PK=起點`、`SK=關係#終點`、`target=終點`） | Task 4 |
| §9.3 S3 路徑（`tutorials/`、`stepfunctions/`、`operations/`） | Task 7、Task 8 |
| §10 分頁與一致性（讀完分頁、空頁不等於沒資料、GSI 最終一致） | Task 4、Task 5 |
| §14.2 重試不是重新抽一次文字（重用已保存的輸出與版號） | Task 8 |
| O1 metadata SK 一律 `META` | Task 2（`put_meta`／`get_meta` 都寫死 `SK=META`） |
| O2 操作紀錄與接受順序 | Task 8、Task 9（兩者都標示為本計劃選擇） |

---

## 11. 參考來源

設計文件（`docs/design/training-kb.md`）：§8.3 發布與併發、§9.1 鍵與原生型別、§9.2 關係邊、§9.3 S3 與執行資訊、§10 圖譜查詢與多跳定位、§14.2 重試、§15 測試與驗收設計、§16 交付切片、§18 待確認事項 O1／O2／O3。

規格檔：`docs/spec/features/查詢知識圖譜.feature`、`docs/spec/features/建立教學版本.feature`、`docs/spec/features/接入來源事件.feature`、`docs/spec/features/執行教學流程.feature`、`docs/spec/features/收集教學回饋.feature`；資料決策 D13、D17、D26。

外部文件（本次以 Context7 MCP 與 AWS 官方文件查證）：

- moto 快速開始與 pytest fixture 寫法（`aws_credentials` → `mock_aws()` → 建立 client 的順序）：<https://github.com/getmoto/moto/blob/master/docs/docs/getting_started.md>
- moto CHANGELOG（S3 `put_object` 條件寫入自 5.0.14 起支援）：<https://github.com/getmoto/moto/blob/master/CHANGELOG.md>
- boto3 DynamoDB 指南（`update_item`、`UpdateExpression`、`ExpressionAttributeValues`）：<https://boto3.amazonaws.com/v1/documentation/api/latest/guide/dynamodb.html>
- boto3 DynamoDB 條件（`Key`、`Attr`、`&`／`|`／`~`）：<https://boto3.amazonaws.com/v1/documentation/api/latest/reference/customizations/dynamodb.html>
- DynamoDB Query 分頁（`LastEvaluatedKey`、`ExclusiveStartKey`）：<https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/Query.Pagination.html>
- DynamoDB 讀取一致性（基表可一致讀、GSI 只有最終一致）：<https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/HowItWorks.ReadConsistency.html>
- DynamoDB 交易 API（`TransactWriteItems`、限制與 `CancellationReasons`）：<https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/transaction-apis.html>
- DynamoDB 保留字清單：<https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/ReservedWords.html>
- S3 條件寫入（`If-None-Match: *`、412 `PreconditionFailed`、409 `ConditionalRequestConflict`、支援的 API）：<https://docs.aws.amazon.com/AmazonS3/latest/userguide/conditional-writes.html>
- S3 `PutObject` API 參考（`IfNoneMatch` 參數）：<https://docs.aws.amazon.com/AmazonS3/latest/API/API_PutObject.html>
