# Phase 09：圖譜查詢與 backfill

| 項目 | 內容 |
|---|---|
| 上一階段 | Phase 08：Content-發布與退役（`08-Phase08-Content-發布與退役.md`） |
| 下一階段 | Phase 10：Ingress-驗簽驗證與去重（`10-Phase10-Ingress-驗簽驗證與去重.md`） |
| 對應設計文件章節 | §9.1、§9.2、§10、§14.3、F40（`docs/design/training-kb.md`） |
| 對應交付切片 | S3（設計文件第 16 節） |
| 預估時間 | 約 5 小時 |
| 做完會得到 | `repository.py` 一組「固定讀取」函式，讓後面每條流程都能用同樣的方式問出「誰引用這個功能」「這篇有哪些版本」「這一版有哪些回饋」，而且不會因為分頁或索引延遲而少讀資料。 |

---

## 1. 這階段做完會得到什麼

做完這一階段，你會得到 `src/training_kb/repository.py` 裡面一組**固定寫死的查詢函式**。它們的共同特色是：

1. **不讓模型（LLM）自己拼查詢。** 每一種問題只有一個函式、一種查法。設計文件 §10 明確要求「`repository` 提供下列固定讀取，不讓 LLM 拼查詢」。
2. **一定讀完所有分頁。** DynamoDB 一次最多回傳 1 MB，剩下的要自己再問一次。少讀一頁就等於資料憑空消失。
3. **需要正確答案的地方一定讀基表（base table）**，不依賴會慢一拍的全域次要索引（GSI）。

具體會多出這些能力（都是後面 Phase 13、16、17、19 會直接呼叫的）：

| 你以後想問的問題 | 這階段做出來的函式 |
|---|---|
| 這個功能叫「Meeting Summary」，是哪一個 Feature？ | `find_feature_by_name_or_alias` |
| `prepare-meeting` 這篇教學有哪些版本？ | `list_versions_of_tutorial` |
| `Prepare` 這個功能已經有 active 的教學了嗎？ | `find_active_tutorial_for_feature` |
| 現在線上（已發布）有哪些步驟提到 `Prepare`？ | `find_steps_referencing`、`find_current_published_steps_referencing` |
| `prepare-meeting@v1` 這一版收到哪些回饋／瀏覽？ | `list_feedback_of_version`、`list_views_of_version` |
| 規則 `R-007` 被哪些版本套用過？ | `list_versions_applying_rule` |
| 有哪些步驟當初漏寫了「引用哪個功能」的邊？ | `backfill_references` |

另外還有一整排 `get_*` / `put_*`（Ticket、Release、Feedback、View、Rule），讓後面的流程不必自己組 DynamoDB 的鍵。

> Phase 07（`07-Phase07-Content-建立教學版本.md`）已經先做好 `get_tutorial`、`put_tutorial`、`get_version`、`get_steps`、`get_feature`、`list_features` 六個方法（它的 Task 4）。**這一階段不重寫它們**，只使用；重寫會出現兩個同名方法，後定義的會蓋掉先定義的。

> 注意：這一階段只做「讀取與補邊」，**不做任何判斷**。例如「要不要改版」是 Phase 16 的事，「平均幾分」是 Phase 19 的事。

---

## 2. 它在整張地圖的位置

```text
基礎層          01 骨架 -> 02 模型與鍵 -> 03 Repository(本機) -> 04 AWS 基礎建設
                                                                      |
AI 與內容層     05 Writing(Bedrock) -> 06 規則注入 -> 07 建立版本 -> 08 發布與退役 -> 09 圖譜查詢
                                                                                        ^
                                                                                        |
                                                                                 ★ 你在這裡 ★
                                                                                        |
接入層          10 Ingress 驗簽 -> 11 Rote 判定 -> 12 Rote Agent -------------------------+
                                                                                        |
流程層          13 Ticket Analysis -> 14 Step Functions 上線 -> 15 Feedback/View 匯入 -> 16 Release Update
                                                                                        |
學習層          17 Review:REFINE -> 18 Review:候選規則+排程 -> 19 Analytics 指標 -> 20 規則驗證
                                                                                        |
展示與驗收層    21 Demo 種子資料 -> 22 靜態教學站 -> 23 Demo 控制台 -> 24 失敗復原驗收 -> 25 安全與當日準備
```

你現在站在「AI 與內容層」的最後一格。前面 Phase 03 已經做好「怎麼把一筆資料寫進 DynamoDB 與 S3」；Phase 07、08 已經會「建立版本」「發布版本」。這一階段補的是**怎麼把寫進去的東西正確地找回來**。

---

## 3. 開始前檢查

依序執行，每一條都要看到預期輸出才往下做。

- [ ] **1）確認專案可以跑測試**

執行：

```bash
cd ~/AWS-Hackathon
uv run pytest -q
```

預期：看到 **0 failed**。如果出現 `error: No 'pyproject.toml' found`，代表 Phase 01 還沒做完，請先回去做。

- [ ] **2）確認 Phase 02 的鍵函式可以 import**

執行：

```bash
uv run python -c "
from training_kb import keys
print(keys.tutorial_pk('prepare-meeting'))
print(keys.step_pk('prepare-meeting@v2', 3))
print(keys.parse_step_pk('STEP#prepare-meeting@v2#3'))
print(keys.parse_pk('FEATURE#Prepare'))
print(keys.parse_edge_sk('REFERENCES#FEATURE#Prepare'))
"
```

預期輸出五行：

```text
TUTORIAL#prepare-meeting
STEP#prepare-meeting@v2#3
('prepare-meeting@v2', 3)
('FEATURE', 'Prepare')
('REFERENCES', 'FEATURE#Prepare')
```

- [ ] **3）確認 Phase 03 與 Phase 07 已經做好的方法都在**

執行：

```bash
uv run python -c "
from training_kb.repository import Repository, encode_numbers, decode_numbers
need = ['put_meta','get_meta','update_meta','put_edge','query_pk','query_by_target',
        'scan_entity','put_object','get_object','object_exists','transact_write',
        'get_tutorial','put_tutorial','get_version','get_steps','get_feature','list_features']
print([n for n in need if not hasattr(Repository, n)] or 'OK')
"
```

預期輸出：`OK`。少任何一個都代表 Phase 03 或 Phase 07 沒做完，請先補完再繼續。

- [ ] **4）確認 moto 與共用 fixture 可用**

執行：

```bash
uv run python -c "import moto; print(moto.__version__)"
grep -n "def repo\|def paged_repo" tests/conftest.py
```

預期：印出 moto 版本號，以及 `tests/conftest.py` 裡的兩個 fixture 定義行。`repo` 與 `paged_repo` 是 Phase 03 建立的共用 fixture，本階段直接用，**不要再建立第二份**。

若 moto 出現 `ModuleNotFoundError`，執行：

```bash
uv add --dev moto
```

- [ ] **5）確認 Phase 07 的全文格式**

執行：

```bash
uv run python -c "
from training_kb.content import render_markdown
from training_kb.models import StepDraft, StepType, TutorialContent
content = TutorialContent(title='準備會議', problem='找不到會前摘要。',
                          prerequisites=['已登入'],
                          steps=[StepDraft(type=StepType.click_ui, text='開啟會議頁面', feature_id='Prepare')],
                          expected_outcome='看得到會前摘要。')
print(render_markdown(content))
"
```

預期輸出裡有這兩行（`## Steps` 區塊的格式是 backfill 解析全文的依據）：

```text
## Steps

1. (type=click_ui, feature=Prepare) 開啟會議頁面
```

---

## 4. 名詞小抄

| 名詞 | 白話解釋 | 在本階段哪裡用到 |
|---|---|---|
| DynamoDB | AWS 提供的資料庫，像一本超大的字典：給它「鍵」，它給你「值」。本專案只有一張表 `training_kb`。 | 全部查詢函式 |
| 單表設計（single table） | 十種資料（教學、版本、步驟、功能、工單…）全部塞在同一張表，靠鍵的前綴分辨是哪一種。 | `scan_entity`、`entity` 屬性 |
| PK / SK | PK 是分割鍵（Partition Key），SK 是排序鍵（Sort Key）。兩個合起來唯一決定一筆資料。 | `keys.py` 的所有函式 |
| item | DynamoDB 裡的一「筆」資料，對應 Python 的一個 `dict`。 | 所有回傳 `list[dict]` 的地方 |
| 關係邊（edge） | 用一筆 item 表達「A 指向 B」。格式固定為 `PK=起點`、`SK=關係#終點`、`target=終點`（設計文件 §9.2）。 | `put_edge`、`query_by_target` |
| GSI（Global Secondary Index，全域次要索引） | 幫資料表另外建一份「反向索引」，讓你可以用別的欄位查。本專案只有一個，名字叫 `by_target`。 | `query_by_target` |
| 最終一致（eventually consistent） | 剛寫進去的資料，索引可能要過一下子才看得到。GSI **只能**這樣讀。 | 第 5.3 節 |
| 強一致讀（consistent read） | 讀基表時指定 `ConsistentRead=True`，保證讀到最新寫入的值。GSI 不支援。 | `get_meta`、`scan_entity(consistent=True)` |
| Query | 指定一個完整的 PK，把該 PK 底下的所有 item 撈出來。快。 | `query_pk`、`list_versions_applying_rule` |
| Scan | 整張表從頭掃到尾，再用條件篩。慢，但 MVP 資料量小可以接受（設計文件 §10、§18）。 | `scan_entity` 系列 |
| 分頁（pagination） | DynamoDB 一次最多回 1 MB。回應裡有 `LastEvaluatedKey` 就代表「還有下一頁」。 | 所有讀取函式 |
| `LastEvaluatedKey` / `ExclusiveStartKey` | 前者是「上一頁停在哪」，把它當成後者傳回去就會接著讀下一頁。 | `Repository._paged`（Phase 03 已寫好） |
| `step_count` | VERSION item 上的輔助欄位，記這一版有幾步。因為每一步是獨立 PK，沒有它就不知道要讀到第幾號。（Phase 07 的本計劃選擇） | Task 7、Task 10 |
| backfill | 「回填」。把當初漏寫的資料事後補上。本階段只補「步驟引用哪個功能」這種邊。 | Task 10 |
| moto | 在本機模擬 AWS 的測試套件，用 `with mock_aws():` 包起來就好。 | 所有整合測試 |
| Decimal | Python 的十進位數字型別。DynamoDB 不收 `float`。Phase 03 的 `encode_numbers`／`decode_numbers` 已經處理好。 | 第 8 節 |
| slug | 教學的英文短名，例如 `prepare-meeting`。版本 ID 長成 `prepare-meeting@v2`。 | `list_versions_of_tutorial` |
| F40 | 設計文件第 19.2 節的功能決策編號：「backfill 只增加缺少的邊，不移除或替換既有引用；錯誤邊另列待處理。」 | Task 10 |
| D17 | 設計文件第 19.1 節的資料決策編號：「以版本的 `rules_applied` 為權威。」 | Task 9 |
| F17 | 設計文件第 19.2 節的功能決策編號：「只處理每篇目前已發布版本的步驟。」 | Task 7 |
| F12 | 設計文件第 19.2 節的功能決策編號：「active 但還沒發布的教學也算已有教學。」 | Task 6 |
| D14 | 設計文件第 19.1 節的資料決策編號：「同一使用者對同一版本的每次新提交都算一筆。」 | Task 8 |

---

## 5. 設計說明

### 5.1 一張表裡的資料長什麼樣

先把腦中的圖建立起來。每一筆 item 都有 `PK`、`SK`，另外有兩個自訂欄位：`entity`（是哪一種資料，等於 PK 的前綴）與 `target`（如果這筆是關係邊，指向誰）。

```text
表 training_kb                                             GSI by_target
+----------------------------+----------------------------+--------------------+
| PK                         | SK                         | target             |
+----------------------------+----------------------------+--------------------+
| TUTORIAL#prepare-meeting   | META                       | (無)               | <- 教學本體
| VERSION#prepare-meeting@v2 | META                       | (無)               | <- 版本本體(含 slug、step_count)
| VERSION#prepare-meeting@v2 | SUPERSEDES#VERSION#...@v1  | VERSION#...@v1     | <- 版本往前指
| STEP#prepare-meeting@v2#3  | REFERENCES#FEATURE#Prepare | FEATURE#Prepare    | <- 步驟＝引用邊
| FEATURE#Prepare            | META                       | (無)               | <- 功能本體
| FEEDBACK#f_12              | META                       | (無)               | <- 回饋本體
| FEEDBACK#f_12              | REFERS_TO#VERSION#...@v1   | VERSION#...@v1     | <- 回饋指向版本
| RULE#R-007                 | APPLIED_TO#VERSION#...@v2  | VERSION#...@v2     | <- 規則套用版本
| TICKET#t_881               | ASKS_ABOUT#FEATURE#Prepare | FEATURE#Prepare    | <- 工單問哪個功能
| VIEW#<sha256 前 32 碼>     | META                       | (無)               | <- 瀏覽紀錄
+----------------------------+----------------------------+--------------------+
```

四個重點：

1. **步驟本身就是引用邊。** 設計文件 §9.1：`TUTORIAL_STEP` 的 SK 就是 `REFERENCES#<Feature PK>`，「同一 item 同時表達步驟與引用」。所以「漏抽引用」在資料上長成「這個步驟沒有 `REFERENCES#` 開頭的 item」。
2. **步驟的 `feature_id` 不是獨立欄位**，而是從 `target` 解出來的：`keys.parse_pk("FEATURE#Prepare")[1] == "Prepare"`。Phase 07 就是這樣寫、這樣讀的。
3. **`entity` 屬性等於 PK 的前綴**（`keys.entity_of(pk)`）。`scan_entity("VERSION")` 靠的就是它。
4. **GSI `by_target` 只有 `target` 一個鍵**，而且只投影 `PK`、`SK`、`target`（KEYS_ONLY）。想拿完整資料要回基表再讀一次。

### 5.2 多跳定位：從一個功能找到「現在線上該改哪一步」

這是設計文件 §10 的核心圖，也是 Phase 16（Release Note Update）能「只改第 3 步」的原因。

```text
Feature: FEATURE#Prepare
   |
   | (1) query_by_target(target = "FEATURE#Prepare")      <- 走 GSI，快，但最終一致
   v
所有指向它的邊（可能混著 TICKET 的 ASKS_ABOUT）
   |
   | (2) 只留 PK 以 STEP# 開頭、SK 以 REFERENCES# 開頭的
   v
候選步驟：STEP#prepare-meeting@v1#3、STEP#prepare-meeting@v2#3
   |
   | (3) 回基表強一致讀：Tutorial.current_version 是誰？
   |     VERSION.published_at 有沒有值？
   v
目前已發布步驟：prepare-meeting@v2 的第 3 步
   |
   | (4) 交給 Phase 16：讀 S3 v2 全文，只重寫第 3 步
   v
A v3；A 的其他步驟、B、C 的原文一個字都不動
```

第 (3) 步是整段的關鍵：**GSI 說有的不一定現在還算數（可能是歷史版本），GSI 沒說的也不一定真的沒有（可能只是索引還沒更新）**。所以答案一律用基表重算。

### 5.3 為什麼 GSI 不能當作唯一答案

AWS 官方文件寫明：DynamoDB 的基表可以做強一致讀，GSI 不行（只有最終一致）。設計文件 §10 因此規定：

> 在本案的小量資料與序列化教學寫入範圍內，**改版前以基表一致讀取核對目前版的完整引用集合**，避免 GSI 暫時少資料就錯判 KEEP。不能只多等固定秒數便宣稱結果完整。

翻成白話：如果 Phase 16 只信 GSI，剛剛新增的 v2 第 3 步可能還沒進索引，程式就會說「沒有任何教學引用這個功能」，於是錯誤地 KEEP，改版就漏了。

所以 `find_current_published_steps_referencing` 的實作是：

```text
  GSI 反查  ---> 候選 slug（快速路徑，落實 Rule 2「用 by_target 的 target」）
                      |
  基表 Scan TUTORIAL --+--> 所有 slug（完整路徑，保證不漏）
                      |
                      v
            對每個 slug 都用基表強一致讀確認：
              get_tutorial(slug)         -> current_version 是誰
              get_version(current)       -> published_at 有沒有值
              get_steps(current)         -> 哪些步驟的 feature_id 命中
                      |
                      v
                回傳命中的 TutorialStep
```

代價是每次都要掃一次 TUTORIAL。設計文件 §18 已經說明這是 MVP 的規模取捨：「單表 Scan、Lambda 內 cosine 與手動匯入是本文件設計選擇的規模取捨，適合少量 Demo 資料，不宣稱適用大型站點。」

### 5.4 分頁：空的一頁不等於沒有資料

AWS 官方文件的原文重點是：

- 一次 Query／Scan 最多回 1 MB；要判斷還有沒有資料，看回應裡有沒有 `LastEvaluatedKey`。
- 「A non-empty `LastEvaluatedKey` only means that the previous `Query` stopped at a page boundary… when you use a `FilterExpression`, `Query` applies the 1 MB/`Limit` page cap to the items it reads **before** applying the filter, so **a page can return zero matching items and still include a `LastEvaluatedKey`**.」

我們的 `scan_entity` 一定會用 `FilterExpression`（`entity = :e`），所以「回傳 0 筆但還有下一頁」是**正常且一定會發生**的情況。

```text
     +---------------------------+
     | 送出 Scan / Query          |<---------------------+
     +---------------------------+                      |
                 |                                      |
                 v                                      |
     +---------------------------+                      |
     | 把這一頁的 Items 加進結果   |  (可能是 0 筆！)      |
     +---------------------------+                      |
                 |                                      |
                 v                                      |
        有 LastEvaluatedKey ?  --是--> 設成               |
                 |                    ExclusiveStartKey--+
                 否
                 |
                 v
           回傳全部結果
```

**唯一正確的停止條件是「回應裡沒有 `LastEvaluatedKey`」**，不是「這一頁是空的」，也不是「已經拿到我要的筆數」。

Phase 03 已經把這個迴圈寫成 `Repository._paged()`，而且提供了 `paged_repo` fixture（每頁只讀 2 筆）讓測試能真的走到多頁。本階段所有新函式都建立在 `_paged` 之上，不要自己另外寫一個迴圈。

### 5.5 backfill 的三種結果

F40 的答案是 A：「只增加缺少的邊，不移除或替換既有引用；錯誤邊另列待處理。」設計文件 §10 補充：「每步若已有另一個引用，不再追加第二個，而是記錄錯誤供處理。不替換舊邊、不改歷史文字、不因此產生新版本。」

```text
              對已發布版本的每一個步驟 index
                            |
          +-----------------+------------------+
          |                                    |
   基表已有 REFERENCES 邊？                 沒有邊
          |                                    |
   +------+------+                     呼叫 feature_of_step(step)
   |             |                     （step 由 S3 全文重建，
callback 回 None  callback 回值           已帶 type / text / feature_id）
或回相同 feature   且與既有不同                   |
   |             |                      +--------+---------+
   v             v                      |                  |
 什麼都不做    conflicts             回傳 None           回傳 feature_id
 (不列入報告)  （只記錄，            或該 Feature         且該 Feature
               不替換）              不存在                存在
                                        |                  |
                                        v                  v
                                    unresolved        寫入邊 -> added
```

回傳的 `BackfillReport` 只裝**步驟編號**（`list[int]`），不裝文字，因為 backfill 不碰文字。

### 5.6 這階段會新增／修改的檔案

```text
src/training_kb/
  repository.py        <- 本階段的主角，在 Phase 03／07 的 Repository 類別內新增方法
  keys.py              <- 不改，只使用
  models.py            <- 不改，只使用
  content.py           <- 不改，只使用 render_markdown 的輸出格式
tests/
  conftest.py          <- 不改（Phase 03 建立，提供 repo 與 paged_repo fixture）
  integration/
    helpers.py                  <- 新增：測試用小工具（直接塞 item，不經過業務流程）
    test_repository_graph.py    <- 新增：固定讀取的測試
    test_repository_backfill.py <- 新增：backfill 三種結果的測試
```

---

## 6. 工作項目

### Task 1：測試用小工具

**目的**：後面每個 Task 都要先「製造出某種資料狀態」（例如：這一版有三步、其中第 3 步沒有引用邊）。把製造資料的程式碼集中在一個檔案，測試本身才看得懂。

**檔案**：
- 新增：`tests/integration/helpers.py`
- 測試：`tests/integration/test_repository_graph.py`

**介面**：
- 消費：`Repository.put_meta`、`Repository.put_edge`、`Repository.put_object`（Phase 03）、`training_kb.keys`（Phase 02）、pytest fixture `repo`／`paged_repo`（Phase 03 的 `tests/conftest.py`）
- 產出：
  - `helpers.put_version_item(repo, version_id, *, step_count, published_at=None, supersedes=None, reason="gap:c12", rules_applied=None) -> str`（回傳 s3_key）
  - `helpers.put_step_item(repo, version_id, index, *, step_type="click_ui", text="開啟會議頁面", feature_id="Prepare", with_reference=True) -> None`
  - `helpers.put_version_markdown(repo, version_id, steps) -> str`（`steps` 是 `(type, feature_id, text)` 的清單；回傳 s3_key）

> `helpers.py` 放在 `tests/integration/` 底下而且**沒有** `__init__.py`。pytest 預設的匯入模式會把測試檔所在的目錄放進 `sys.path`，所以測試裡直接寫 `from helpers import put_step_item` 就能用。

- [ ] **步驟 1：寫測試**

`tests/integration/test_repository_graph.py`：

```python
"""Phase 09：repository 固定讀取的整合測試（全部在 moto 的假 AWS 上跑）。"""

from helpers import put_step_item, put_version_item, put_version_markdown
from training_kb import keys


def test_helpers_build_the_expected_items(repo):
    s3_key = put_version_item(repo, "prepare-meeting@v2", step_count=2,
                              published_at="2026-08-20T00:00:00Z")
    assert s3_key == "tutorials/prepare-meeting/v2.md"

    meta = repo.get_meta(keys.version_pk("prepare-meeting@v2"))
    assert meta["slug"] == "prepare-meeting"
    assert int(meta["step_count"]) == 2
    assert meta["published_at"] == "2026-08-20T00:00:00Z"

    put_step_item(repo, "prepare-meeting@v2", 1, feature_id="Prepare", text="第一步")
    rows = repo.query_pk(keys.step_pk("prepare-meeting@v2", 1))
    assert len(rows) == 1
    assert rows[0]["SK"] == "REFERENCES#FEATURE#Prepare"
    assert rows[0]["target"] == "FEATURE#Prepare"

    put_step_item(repo, "prepare-meeting@v2", 2, with_reference=False, text="第二步")
    rows = repo.query_pk(keys.step_pk("prepare-meeting@v2", 2))
    assert rows[0]["SK"] == keys.META          # 漏抽引用的步驟

    put_version_markdown(repo, "prepare-meeting@v2",
                         [("click_ui", "Prepare", "第一步"), ("read", "Prepare", "第二步")])
    body = repo.get_object("tutorials/prepare-meeting/v2.md").decode("utf-8")
    assert "1. (type=click_ui, feature=Prepare) 第一步" in body
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：`uv run pytest tests/integration/test_repository_graph.py -v`

預期：FAIL，錯誤訊息是 `ModuleNotFoundError: No module named 'helpers'`。因為 `tests/integration/helpers.py` 還不存在。

- [ ] **步驟 3：寫最少的程式讓測試通過**

`tests/integration/helpers.py`：

```python
"""Phase 09 整合測試共用的小工具。

直接寫入 DynamoDB item 與 S3 物件，繞過 content.create_version 的業務流程，
方便製造「漏抽引用」「歷史版本」「尚未發布」這些平常做不出來的狀態。
item 的形狀與 Phase 07 的 content.create_version 完全一致。
"""

from training_kb import keys


def version_s3_key(version_id: str) -> str:
    slug, number = version_id.split("@v")
    return f"tutorials/{slug}/v{number}.md"


def put_version_item(
    repo,
    version_id: str,
    *,
    step_count: int,
    published_at: str | None = None,
    supersedes: str | None = None,
    reason: str = "gap:c12",
    rules_applied: list[str] | None = None,
) -> str:
    """寫一筆 VERSION metadata，形狀照 Phase 07 的 create_version。"""
    s3_key = version_s3_key(version_id)
    slug, _number = version_id.split("@v")
    attrs: dict = {
        "entity": "VERSION",
        "version_id": version_id,
        "slug": slug,
        "reason": reason,
        "rules_applied": list(rules_applied or []),
        "s3_key": s3_key,
        "step_count": step_count,
        "created_at": "2026-08-01T00:00:00Z",
    }
    if supersedes is not None:
        attrs["supersedes"] = supersedes
    if published_at is not None:
        attrs["published_at"] = published_at
    repo.put_meta(keys.version_pk(version_id), attrs)
    return s3_key


def put_step_item(
    repo,
    version_id: str,
    index: int,
    *,
    step_type: str = "click_ui",
    text: str = "開啟會議頁面",
    feature_id: str = "Prepare",
    with_reference: bool = True,
) -> None:
    """寫一個 STEP item。

    with_reference=True  -> SK 是 REFERENCES#FEATURE#<id>，代表「有引用邊」（正常）。
    with_reference=False -> SK 是 META，代表「當初漏抽引用」，給 backfill 測試用。
    """
    pk = keys.step_pk(version_id, index)
    attrs = {
        "entity": "STEP",
        "tutorial_version": version_id,
        "index": index,
        "type": step_type,
        "text": text,
    }
    if with_reference:
        repo.put_edge(pk, "REFERENCES", keys.feature_pk(feature_id), attrs)
    else:
        repo.put_meta(pk, attrs)


def put_version_markdown(repo, version_id: str, steps: list[tuple[str, str, str]]) -> str:
    """在 S3 放一份符合 Phase 07 render_markdown 格式的全文，回傳 s3_key。

    steps 的每一項是 (type, feature_id, text)。
    """
    lines = ["# 準備會議", "", "## Problem", "", "找不到會前摘要。", ""]
    lines += ["## Prerequisites", "", "- 已登入", ""]
    lines += ["## Steps", ""]
    for index, (step_type, feature_id, text) in enumerate(steps, start=1):
        lines.append(f"{index}. (type={step_type}, feature={feature_id}) {text}")
    lines += ["", "## Expected Outcome", "", "看得到會前摘要。", ""]
    s3_key = version_s3_key(version_id)
    repo.put_object(s3_key, "\n".join(lines), content_type="text/markdown; charset=utf-8")
    return s3_key
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：`uv run pytest tests/integration/test_repository_graph.py -v`

預期：PASS（`1 passed`）。

- [ ] **步驟 5：commit**

```bash
git add tests/integration/helpers.py tests/integration/test_repository_graph.py
git commit -m "test(repository): 建立圖譜查詢測試用的資料小工具"
```

---

### Task 2：強一致 Scan、entity 屬性與版本排序

**目的**：補三個所有後續函式都要用的基礎工具。

**檔案**：
- 修改：`src/training_kb/repository.py`
- 測試：`tests/integration/test_repository_graph.py`

**介面**：
- 消費：`Repository._paged`、`repository.encode_numbers`（Phase 03）、`keys.entity_of`、`models.parse_version_id`（Phase 02）
- 產出：
  - `Repository.scan_entity(entity: str, *, consistent: bool = True) -> list[dict]`（**修改** Phase 03 的版本，加一個 keyword-only 參數；既有呼叫方式完全不受影響）
  - `repository.entity_attrs(pk: str, model) -> dict`（新增）
  - `repository.version_sort_key(version_id: str) -> tuple[str, int]`（新增）

> **為什麼要改 `scan_entity`**：設計文件 §10 要求「改版前以基表一致讀取核對」。Phase 03 的版本沒有指定 `ConsistentRead`，預設是最終一致讀。改成 keyword-only 參數、預設 `True`，與 `get_meta`、`query_pk` 的預設一致。
>
> **為什麼不需要自己轉 Decimal**：Phase 03 的 `put_meta`／`put_edge` 已經對傳進去的 attrs 跑 `encode_numbers`（`float` → `Decimal`），`_paged`／`get_meta` 也已經跑 `decode_numbers` 還原。所以 `entity_attrs` 只要把模型 dump 成 JSON 型別就好。
>
> **為什麼模型可以直接 `model_validate(item)`**：Phase 02 的 `_ITEM_CONFIG = ConfigDict(extra="ignore")`，多出來的 `PK`、`SK`、`target`、`entity` 會被忽略，不用自己清掉。

- [ ] **步驟 1：寫測試**

把下面這段加到 `tests/integration/test_repository_graph.py`：

```python
from training_kb.models import Feature
from training_kb.repository import entity_attrs, version_sort_key


def test_entity_attrs_fills_entity_from_pk():
    feature = Feature(feature_id="Prepare", name="Prepare", aliases=["Meeting Summary"],
                      first_seen="2026-08-01T00:00:00Z")
    attrs = entity_attrs(keys.feature_pk("Prepare"), feature)
    assert attrs["entity"] == "FEATURE"
    assert attrs["name"] == "Prepare"
    assert attrs["aliases"] == ["Meeting Summary"]


def test_version_sort_key_orders_by_number_not_string():
    ids = ["prepare-meeting@v10", "prepare-meeting@v2", "share-summary@v1"]
    assert sorted(ids, key=version_sort_key) == [
        "prepare-meeting@v2", "prepare-meeting@v10", "share-summary@v1"
    ]


def test_scan_entity_supports_consistent_read(repo):
    put_version_item(repo, "prepare-meeting@v1", step_count=1)
    rows = repo.scan_entity("VERSION", consistent=True)
    assert [row["version_id"] for row in rows] == ["prepare-meeting@v1"]
    # 預設值就是強一致讀，舊的呼叫方式不受影響
    assert repo.scan_entity("VERSION") == rows
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：`uv run pytest tests/integration/test_repository_graph.py -v`

預期：FAIL，`ImportError: cannot import name 'entity_attrs' from 'training_kb.repository'`。

- [ ] **步驟 3：寫最少的程式讓測試通過**

在 `src/training_kb/repository.py` 的 import 區補上（已存在的不要重複寫）：

```python
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from .keys import (
    entity_of,
    feedback_pk,
    parse_edge_sk,
    parse_pk,
    parse_step_pk,
    release_pk,
    rule_pk,
    step_pk,
    ticket_pk,
    view_pk,
)
from .models import (
    AuthoringRule,
    Feature,
    Feedback,
    Release,
    RuleStatus,
    Ticket,
    Tutorial,
    TutorialStatus,
    TutorialStep,
    TutorialVersion,
    TutorialView,
    parse_version_id,
)
```

在 `class Repository` **之前**（模組層級）加入兩個工具函式：

```python
def entity_attrs(pk: str, model: Any) -> dict:
    """把 pydantic 模型轉成 item 屬性，並依 PK 前綴自動填上 entity。

    用 model_dump(mode="json") 是為了把 StrEnum 變成字串；
    float -> Decimal 的轉換由 put_meta / put_edge 內部的 encode_numbers 負責。
    值是 None 的欄位照樣寫入（會變成 DynamoDB 的 NULL），
    因為 Feedback.category、Release.old_name 這些欄位在模型裡沒有預設值，
    讀回來時必須看得到這個鍵才驗證得過。
    """
    attrs = dict(model.model_dump(mode="json"))
    attrs["entity"] = entity_of(pk)
    return attrs


def version_sort_key(version_id: str) -> tuple[str, int]:
    """版本排序用的鍵：先比 slug，再比版號數字。

    直接用字串排序會把 v10 排在 v2 前面，所以一律用這個函式。
    """
    slug, number = parse_version_id(version_id)
    return (slug, number)
```

找到 Phase 03 寫的 `scan_entity`，用下面這一版取代：

```python
    def scan_entity(self, entity: str, *, consistent: bool = True) -> list[dict]:
        """整張表掃過一遍，只留下 entity 等於指定值的 item（讀完所有分頁）。

        consistent=True 用基表的強一致讀（ConsistentRead），保證讀得到剛寫入的資料；
        設計文件 §10 要求「改版前以基表一致讀取核對」。GSI 不支援強一致讀。
        Scan 很慢，設計文件 §10、§18 只允許 MVP 的少量資料這樣用。
        """
        return self._paged(
            self.table.scan,
            {
                "FilterExpression": Attr("entity").eq(entity),
                "ConsistentRead": consistent,
            },
        )
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：

```bash
uv run pytest tests/integration/test_repository_graph.py -v
uv run pytest tests/integration -q
```

預期：本檔案 PASS（4 passed），而且 Phase 03、07、08 既有的整合測試全部仍然通過。

- [ ] **步驟 5：commit**

```bash
git add src/training_kb/repository.py tests/integration/test_repository_graph.py
git commit -m "feat(repository): 強一致 Scan 與 item 屬性、版本排序工具"
```

---

### Task 3：工單、改版、回饋、瀏覽、規則的 get/put

**目的**：補齊五種實體的固定讀寫，讓 Phase 10、13、15、17 不必自己組 DynamoDB 的鍵。

**檔案**：
- 修改：`src/training_kb/repository.py`
- 測試：`tests/integration/test_repository_graph.py`

**介面**：
- 消費：`Repository.put_meta`、`get_meta`、`put_edge`、`scan_entity`（Phase 03、Task 2）、`repository.entity_attrs`（Task 2）
- 產出：
  - `Repository.get_ticket(ticket_id) -> Ticket | None`、`put_ticket(t, *, if_not_exists=False) -> bool`、`list_tickets(project_id) -> list[Ticket]`
  - `Repository.get_release(release_id) -> Release | None`、`put_release(r, *, if_not_exists=False) -> bool`
  - `Repository.get_feedback(feedback_id) -> Feedback | None`、`put_feedback(f, *, if_not_exists=False) -> bool`
  - `Repository.put_view(v) -> bool`
  - `Repository.get_rule(rule_id) -> AuthoringRule | None`、`put_rule(r, *, if_not_exists=False) -> bool`、`list_rules(status=None) -> list[AuthoringRule]`

> **本階段選擇**：`put_feedback` 會同時寫入 `FEEDBACK` 本體與 `REFERS_TO` 邊（因為 `Feedback.tutorial_version` 必填且恰好一個）；`put_ticket` 只有在 `feature_ids` 非空時才寫 `ASKS_ABOUT` 邊（D04：一張 Ticket 對應零或一個 Feature）。這樣 Phase 15 的 `import_feedback` 呼叫一次就完成「FEEDBACK META + REFERS_TO 邊」。

- [ ] **步驟 1：寫測試**

加到 `tests/integration/test_repository_graph.py`：

```python
from training_kb.models import (
    AuthoringRule,
    Release,
    ReleaseKind,
    ReleaseSource,
    RuleStatus,
    Ticket,
    TicketSource,
    TutorialView,
)
from training_kb.models import Feedback as FeedbackModel


def test_ticket_put_get_and_list_by_project(repo):
    repo.put_ticket(Ticket(id="t_881", source=TicketSource.github_issue,
                           text="會前摘要在哪裡開啟？", author="u_01",
                           ts="2026-08-02T09:00:00Z", project_id="demo-project",
                           feature_ids=["Prepare"]))
    repo.put_ticket(Ticket(id="t_882", source=TicketSource.email,
                           text="另一個專案的問題", author="u_02",
                           ts="2026-08-02T10:00:00Z", project_id="other-project"))

    got = repo.get_ticket("t_881")
    assert got is not None
    assert got.source is TicketSource.github_issue
    assert got.feature_ids == ["Prepare"]
    assert repo.get_ticket("t_999") is None

    assert [t.id for t in repo.list_tickets("demo-project")] == ["t_881"]

    # feature_ids 非空時會一併寫 ASKS_ABOUT 邊
    assert "TICKET#t_881" in [r["PK"] for r in repo.query_by_target(keys.feature_pk("Prepare"))]


def test_ticket_embedding_round_trips_as_float(repo):
    repo.put_ticket(Ticket(id="t_883", source=TicketSource.email, text="有向量的工單",
                           author="u_03", ts="2026-08-02T11:00:00Z",
                           project_id="demo-project", embedding=[0.1, -0.25, 0.5]))
    got = repo.get_ticket("t_883")
    assert got.embedding == [0.1, -0.25, 0.5]
    assert all(isinstance(value, float) for value in got.embedding)


def test_release_put_and_get(repo):
    repo.put_release(Release(id="r_42", source=ReleaseSource.github_pr,
                             source_event_id="gh-acme-notes-pr42", feature="Prepare",
                             kind=ReleaseKind.renamed, old_name="Meeting Summary",
                             new_name="Prepare", evidence="PR #42 renamed the tab",
                             ts="2026-08-19T00:00:00Z"))
    got = repo.get_release("r_42")
    assert got is not None
    assert got.kind is ReleaseKind.renamed
    assert got.old_name == "Meeting Summary"


def test_release_with_empty_names_round_trips(repo):
    repo.put_release(Release(id="r_43", source=ReleaseSource.changelog,
                             source_event_id="changelog-2026-08", feature="Share Summary",
                             kind=ReleaseKind.removed, old_name=None, new_name=None,
                             evidence="changelog 移除分享摘要", ts="2026-08-19T00:00:00Z"))
    got = repo.get_release("r_43")
    assert got.old_name is None
    assert got.new_name is None


def test_feedback_put_writes_refers_to_edge(repo):
    repo.put_feedback(FeedbackModel(id="f_12", tutorial_version="prepare-meeting@v1",
                                    rating=2, user="u_01", category="找不到按鈕",
                                    comment="第三步沒有指出按鈕在哪一頁與位置",
                                    ts="2026-08-02T09:00:00Z"))
    got = repo.get_feedback("f_12")
    assert got is not None
    assert got.rating == 2
    assert isinstance(got.rating, int)

    edges = repo.query_by_target(keys.version_pk("prepare-meeting@v1"))
    assert [(e["PK"], e["SK"]) for e in edges] == [
        ("FEEDBACK#f_12", "REFERS_TO#VERSION#prepare-meeting@v1")
    ]


def test_rating_only_feedback_round_trips(repo):
    repo.put_feedback(FeedbackModel(id="f_103", tutorial_version="prepare-meeting@v2",
                                    rating=5, user="u_03", category=None, comment=None,
                                    ts="2026-08-21T09:00:00Z"))
    got = repo.get_feedback("f_103")
    assert got.category is None
    assert got.comment is None


def test_put_view_is_idempotent_on_same_triple(repo):
    view = TutorialView(tutorial_version="prepare-meeting@v1", user="u_01",
                        ts="2026-08-02T09:00:00Z")
    assert repo.put_view(view) is True
    assert repo.put_view(view) is False        # 同一個三元組只算一次瀏覽
    other_time = TutorialView(tutorial_version="prepare-meeting@v1", user="u_01",
                              ts="2026-08-03T09:00:00Z")
    assert repo.put_view(other_time) is True   # 不同時間是另一筆


def test_rule_put_get_and_filter_by_status(repo):
    repo.put_rule(AuthoringRule(rule_id="R-007", rule="點擊步驟要寫出按鈕位置",
                                applies_when={"step.type": "click_ui"},
                                evidence=["f_12", "f_15"], status=RuleStatus.candidate,
                                derived_from="prepare-meeting@v1"))
    repo.put_rule(AuthoringRule(rule_id="R-012", rule="舊規則",
                                applies_when={"step.type": "read"},
                                evidence=["f_90"], status=RuleStatus.retired,
                                derived_from="share-summary@v1"))

    assert repo.get_rule("R-007").status is RuleStatus.candidate
    assert [r.rule_id for r in repo.list_rules()] == ["R-007", "R-012"]
    assert [r.rule_id for r in repo.list_rules(RuleStatus.retired)] == ["R-012"]
    assert repo.list_rules(RuleStatus.active) == []
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：`uv run pytest tests/integration/test_repository_graph.py -v`

預期：FAIL，`AttributeError: 'Repository' object has no attribute 'put_ticket'`。

- [ ] **步驟 3：寫最少的程式讓測試通過**

在 `class Repository` 內新增：

```python
    # ---- 工單 ----------------------------------------------------------
    def get_ticket(self, ticket_id: str) -> Ticket | None:
        item = self.get_meta(ticket_pk(ticket_id))
        return None if item is None else Ticket.model_validate(item)

    def put_ticket(self, t: Ticket, *, if_not_exists: bool = False) -> bool:
        pk = ticket_pk(t.id)
        created = self.put_meta(pk, entity_attrs(pk, t), if_not_exists=if_not_exists)
        # D04：一張 Ticket 對應零或一個 Feature；有對應才寫 ASKS_ABOUT 邊。
        for feature_id in t.feature_ids[:1]:
            self.put_edge(pk, "ASKS_ABOUT", feature_pk(feature_id),
                          {"entity": "TICKET", "ticket_id": t.id})
        return created

    def list_tickets(self, project_id: str) -> list[Ticket]:
        tickets = [
            Ticket.model_validate(row)
            for row in self.scan_entity("TICKET")
            if row.get("project_id") == project_id
        ]
        tickets.sort(key=lambda t: (t.ts, t.id))
        return tickets

    # ---- 改版 ----------------------------------------------------------
    def get_release(self, release_id: str) -> Release | None:
        item = self.get_meta(release_pk(release_id))
        return None if item is None else Release.model_validate(item)

    def put_release(self, r: Release, *, if_not_exists: bool = False) -> bool:
        pk = release_pk(r.id)
        return self.put_meta(pk, entity_attrs(pk, r), if_not_exists=if_not_exists)

    # ---- 回饋 ----------------------------------------------------------
    def get_feedback(self, feedback_id: str) -> Feedback | None:
        item = self.get_meta(feedback_pk(feedback_id))
        return None if item is None else Feedback.model_validate(item)

    def put_feedback(self, f: Feedback, *, if_not_exists: bool = False) -> bool:
        pk = feedback_pk(f.id)
        created = self.put_meta(pk, entity_attrs(pk, f), if_not_exists=if_not_exists)
        # 一筆回饋一定指向恰好一個版本，所以本體與 REFERS_TO 邊一起寫。
        self.put_edge(pk, "REFERS_TO", version_pk(f.tutorial_version),
                      {"entity": "FEEDBACK", "feedback_id": f.id})
        return created

    # ---- 瀏覽 ----------------------------------------------------------
    def put_view(self, v: TutorialView) -> bool:
        """回傳 True 代表這是新的瀏覽紀錄；False 代表同一個三元組已經存在。

        PK 由 [tutorial_version, user, ts] 的 SHA-256 算出（設計文件 §9.1），
        所以完全相同的三元組重送只會有一筆，不同瀏覽時間是不同紀錄。
        """
        pk = view_pk(v.tutorial_version, v.user, v.ts)
        return self.put_meta(pk, entity_attrs(pk, v), if_not_exists=True)

    # ---- 規則 ----------------------------------------------------------
    def get_rule(self, rule_id: str) -> AuthoringRule | None:
        item = self.get_meta(rule_pk(rule_id))
        return None if item is None else AuthoringRule.model_validate(item)

    def put_rule(self, r: AuthoringRule, *, if_not_exists: bool = False) -> bool:
        pk = rule_pk(r.rule_id)
        return self.put_meta(pk, entity_attrs(pk, r), if_not_exists=if_not_exists)

    def list_rules(self, status: RuleStatus | None = None) -> list[AuthoringRule]:
        rules = [AuthoringRule.model_validate(row) for row in self.scan_entity("RULE")]
        if status is not None:
            rules = [rule for rule in rules if rule.status is status]
        rules.sort(key=lambda rule: rule.rule_id)
        return rules
```

> `feature_pk` 與 `version_pk` 已經被 Phase 07 匯入 `repository.py`，這裡直接使用；若你的檔案還沒有，請把它們加進 `from .keys import (...)`。

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：`uv run pytest tests/integration/test_repository_graph.py -v`

預期：PASS（12 passed）。

- [ ] **步驟 5：commit**

```bash
git add src/training_kb/repository.py tests/integration/test_repository_graph.py
git commit -m "feat(repository): 工單改版回饋瀏覽規則的固定讀寫"
```

---

### Task 4：用名稱或別名找 Feature

**目的**：Phase 16 收到「PR #42 把 Meeting Summary 改名為 Prepare」時，要先用舊名字找到同一個 Feature 節點（`依改版更新教學.feature` Rule 2）。

**檔案**：
- 修改：`src/training_kb/repository.py`
- 測試：`tests/integration/test_repository_graph.py`

**介面**：
- 消費：`Repository.list_features()`（Phase 07）
- 產出：`Repository.find_feature_by_name_or_alias(name: str) -> Feature | None`

> **本階段選擇**：比對時忽略前後空白與大小寫（`str.casefold()`）；**先比 `name`，全部不中才比 `aliases`**。D07 已定「alias 必須唯一」，所以正常情況下不會有兩個 Feature 搶同一個 alias；真的撞名時本函式回傳 `feature_id` 排序最小的那一個（`list_features` 已排序），撞名本身由 Phase 16 的 alias 更新流程拒絕。

- [ ] **步驟 1：寫測試**

```python
def _put_feature(repo, feature_id: str, *, name: str, aliases: list[str]) -> None:
    """Phase 07 只做了 get_feature 與 list_features，沒有 put_feature，
    所以測試直接用 put_meta 寫 FEATURE item。"""
    repo.put_meta(keys.feature_pk(feature_id), {
        "entity": "FEATURE", "name": name, "aliases": aliases,
        "first_seen": "2026-08-01T00:00:00Z"})


def test_find_feature_by_name_or_alias(repo):
    _put_feature(repo, "Prepare", name="Prepare", aliases=["Meeting Summary"])
    _put_feature(repo, "Share Summary", name="Share Summary", aliases=[])

    assert repo.find_feature_by_name_or_alias("Prepare").feature_id == "Prepare"
    assert repo.find_feature_by_name_or_alias("Meeting Summary").feature_id == "Prepare"
    assert repo.find_feature_by_name_or_alias("  meeting summary ").feature_id == "Prepare"
    assert repo.find_feature_by_name_or_alias("Notification Settings") is None
    assert repo.find_feature_by_name_or_alias("") is None


def test_find_feature_prefers_name_over_alias(repo):
    """名字比別名優先：Share Summary 的 name 勝過 Prepare 的 alias。"""
    _put_feature(repo, "Prepare", name="Prepare", aliases=["Share Summary"])
    _put_feature(repo, "Share Summary", name="Share Summary", aliases=[])

    assert repo.find_feature_by_name_or_alias("Share Summary").feature_id == "Share Summary"
```

> 測試裡的 `_put_feature` 小工具只是提醒：Phase 07 只做了 `get_feature` 與 `list_features`，**沒有** `put_feature`，所以測試直接用 `put_meta` 寫 FEATURE item。

- [ ] **步驟 2：跑測試，確認它失敗**

執行：`uv run pytest tests/integration/test_repository_graph.py -k find_feature -v`

預期：FAIL，`AttributeError: 'Repository' object has no attribute 'find_feature_by_name_or_alias'`。

- [ ] **步驟 3：寫最少的程式讓測試通過**

```python
    def find_feature_by_name_or_alias(self, name: str) -> Feature | None:
        """先用目前的 name 比對，全部不中才比 aliases；忽略大小寫與前後空白。

        對應「依改版更新教學」Rule 2：改名前後的 alias 對應同一個 Feature 節點。
        找不到就回 None，由呼叫端決定要不要改用語意搜尋（Phase 16）。
        """
        wanted = name.strip().casefold()
        if not wanted:
            return None
        features = self.list_features()          # 已依 feature_id 排序
        for feature in features:
            if feature.name.strip().casefold() == wanted:
                return feature
        for feature in features:
            for alias in feature.aliases:
                if alias.strip().casefold() == wanted:
                    return feature
        return None
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：`uv run pytest tests/integration/test_repository_graph.py -k find_feature -v`

預期：PASS（2 passed）。

- [ ] **步驟 5：commit**

```bash
git add src/training_kb/repository.py tests/integration/test_repository_graph.py
git commit -m "feat(repository): 用名稱或別名定位 Feature"
```

---

### Task 5：列出某篇教學的所有版本（含多頁與空頁測試）

**目的**：落實「查詢知識圖譜」Rule 4，同時把「分頁一定要讀完」這件事用測試釘死。

**檔案**：
- 修改：`src/training_kb/repository.py`
- 測試：`tests/integration/test_repository_graph.py`

**介面**：
- 消費：`Repository.scan_entity`（Task 2）、`Repository.get_version`（Phase 07）、`repository.version_sort_key`（Task 2）
- 產出：`Repository.list_versions_of_tutorial(slug: str) -> list[TutorialVersion]`

> 設計文件 §10 明說：「某篇教學有哪些版本？**MVP 對基表分頁 Scan**，依 VERSION PK 解析的 slug 篩選；**不能用 PK 前綴冒稱是有效的 DynamoDB Query**。」DynamoDB 的 Query 只接受「完整相等」的分割鍵，`begins_with` 只能用在排序鍵。所以不要試圖寫 `Key('PK').begins_with('VERSION#prepare-meeting')`，那是無效的。
>
> Phase 07 的 VERSION item 上已經有 `slug` 屬性，所以篩選直接比它；萬一遇到沒有 `slug` 的舊資料，退回用 `version_id` 解析。

- [ ] **步驟 1：寫測試**

```python
def _put_versions(repo, slug: str, count: int) -> None:
    for number in range(1, count + 1):
        put_version_item(repo, f"{slug}@v{number}", step_count=1,
                         published_at="2026-08-01T00:00:00Z",
                         supersedes=f"{slug}@v{number - 1}" if number > 1 else None)


def test_list_versions_of_tutorial_sorted_and_filtered(repo):
    _put_versions(repo, "prepare-meeting", 3)
    _put_versions(repo, "share-summary", 2)

    versions = repo.list_versions_of_tutorial("prepare-meeting")
    assert [v.version_id for v in versions] == [
        "prepare-meeting@v1", "prepare-meeting@v2", "prepare-meeting@v3"
    ]
    assert versions[1].supersedes == "prepare-meeting@v1"
    assert repo.list_versions_of_tutorial("notification-settings") == []


def test_list_versions_sorts_v10_after_v2(repo):
    """字串排序會把 v10 排在 v2 前面，必須用版號數字排序。"""
    _put_versions(repo, "prepare-meeting", 11)
    numbers = [
        int(v.version_id.split("@v")[1])
        for v in repo.list_versions_of_tutorial("prepare-meeting")
    ]
    assert numbers == list(range(1, 12))


def test_list_versions_reads_every_page(paged_repo):
    """paged_repo 每頁只讀 2 筆；中間被 FilterExpression 濾成空的一頁不能當成結束。"""
    _put_versions(paged_repo, "prepare-meeting", 4)
    for index in range(6):
        paged_repo.put_ticket(Ticket(id=f"t_9{index}", source=TicketSource.email,
                                     text="雜訊", author="u_99",
                                     ts="2026-08-01T00:00:00Z", project_id="demo-project"))

    versions = paged_repo.list_versions_of_tutorial("prepare-meeting")
    assert [v.version_id for v in versions] == [
        "prepare-meeting@v1", "prepare-meeting@v2",
        "prepare-meeting@v3", "prepare-meeting@v4",
    ]


def test_scan_entity_returns_every_item_across_pages(paged_repo):
    for index in range(7):
        paged_repo.put_ticket(Ticket(id=f"t_{index}", source=TicketSource.email,
                                     text="工單", author="u_01",
                                     ts="2026-08-01T00:00:00Z", project_id="demo-project"))
    assert len(paged_repo.scan_entity("TICKET")) == 7
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：`uv run pytest tests/integration/test_repository_graph.py -k versions -v`

預期：FAIL，`AttributeError: 'Repository' object has no attribute 'list_versions_of_tutorial'`。

- [ ] **步驟 3：寫最少的程式讓測試通過**

```python
    def list_versions_of_tutorial(self, slug: str) -> list[TutorialVersion]:
        """回傳某篇教學的全部版本，依版號由小到大。

        設計文件 §10：MVP 對基表分頁 Scan 再依 slug 篩選。
        DynamoDB 的 Query 必須指定完整的分割鍵，不能用 PK 前綴當 Query 條件，
        所以這裡老實用 Scan，不假裝成 Query。
        """
        version_ids: list[str] = []
        for row in self.scan_entity("VERSION"):
            version_id = row.get("version_id")
            if not isinstance(version_id, str) or not version_id:
                continue
            row_slug = row.get("slug")
            if not isinstance(row_slug, str) or not row_slug:
                try:
                    row_slug = parse_version_id(version_id)[0]
                except ValueError:
                    continue                   # 鍵壞掉的資料跳過，不讓它炸掉整批查詢
            if row_slug == slug:
                version_ids.append(version_id)

        versions: list[TutorialVersion] = []
        for version_id in sorted(set(version_ids), key=version_sort_key):
            version = self.get_version(version_id)
            if version is not None:
                versions.append(version)
        return versions
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：`uv run pytest tests/integration/test_repository_graph.py -v`

預期：PASS（16 passed）。

- [ ] **步驟 5：commit**

```bash
git add src/training_kb/repository.py tests/integration/test_repository_graph.py
git commit -m "feat(repository): 以基表 Scan 列出教學的所有版本"
```

---

### Task 6：找某個功能目前的 active 教學

**目的**：Phase 13 判斷 CREATE 還是 KEEP 要用（`分析工單.feature` Rule 7）。

**檔案**：
- 修改：`src/training_kb/repository.py`
- 測試：`tests/integration/test_repository_graph.py`

**介面**：
- 消費：`Repository.scan_entity`（Task 2）、`Repository.get_tutorial`（Phase 07）
- 產出：`Repository.find_active_tutorial_for_feature(feature_id: str) -> Tutorial | None`

> F12 的答案是 B：「active 的 Tutorial **即使仍待首次發布**也算已有教學，避免重複建立。」所以這裡**不看** `current_version` 有沒有值，只看 `status`。設計文件 §7.3 也寫「有 active Tutorial，即使尚待首次發布也 KEEP；retired 不阻擋 CREATE」。

- [ ] **步驟 1：寫測試**

```python
from training_kb.models import Tutorial, TutorialStatus


def test_find_active_tutorial_for_feature(repo):
    repo.put_tutorial(Tutorial(slug="prepare-meeting", current_version=None,
                               topic="準備會議", feature_ids=["Prepare"],
                               status=TutorialStatus.active, cluster_id="c12"))
    # 尚未發布（current_version 是 None）仍然算「已有教學」（F12）
    found = repo.find_active_tutorial_for_feature("Prepare")
    assert found is not None
    assert found.slug == "prepare-meeting"


def test_retired_tutorial_does_not_count_as_active(repo):
    repo.put_tutorial(Tutorial(slug="old-prepare", current_version="old-prepare@v1",
                               topic="舊的準備會議", feature_ids=["Prepare"],
                               status=TutorialStatus.retired, cluster_id="c11"))
    assert repo.find_active_tutorial_for_feature("Prepare") is None


def test_find_active_tutorial_ignores_other_features(repo):
    repo.put_tutorial(Tutorial(slug="share-summary", current_version=None,
                               topic="分享摘要", feature_ids=["Share Summary"],
                               status=TutorialStatus.active, cluster_id="c13"))
    assert repo.find_active_tutorial_for_feature("Prepare") is None
    assert repo.find_active_tutorial_for_feature("Share Summary").slug == "share-summary"


def test_find_active_tutorial_picks_smallest_slug_when_several_match(repo):
    for slug in ("zeta-prepare", "alpha-prepare"):
        repo.put_tutorial(Tutorial(slug=slug, current_version=None, topic="準備會議",
                                   feature_ids=["Prepare"],
                                   status=TutorialStatus.active, cluster_id="c12"))
    assert repo.find_active_tutorial_for_feature("Prepare").slug == "alpha-prepare"
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：`uv run pytest tests/integration/test_repository_graph.py -k active_tutorial -v`

預期：FAIL，`AttributeError: 'Repository' object has no attribute 'find_active_tutorial_for_feature'`。

- [ ] **步驟 3：寫最少的程式讓測試通過**

```python
    def find_active_tutorial_for_feature(self, feature_id: str) -> Tutorial | None:
        """回傳引用這個功能、狀態為 active 的教學（多篇時取 slug 最小者）。

        F12：active 但尚未首次發布也算已有教學，所以這裡不檢查 current_version。
        retired 的教學不算，因此不會阻擋 Phase 13 建立新教學。
        """
        slugs: list[str] = []
        for row in self.scan_entity("TUTORIAL"):
            if str(row.get("status", "")) != str(TutorialStatus.active):
                continue
            if feature_id not in list(row.get("feature_ids", [])):
                continue
            slug = row.get("slug")
            if isinstance(slug, str) and slug:
                slugs.append(slug)
        for slug in sorted(slugs):
            tutorial = self.get_tutorial(slug)   # 基表強一致讀，拿到完整資料
            if tutorial is not None and tutorial.status is TutorialStatus.active:
                return tutorial
        return None
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：`uv run pytest tests/integration/test_repository_graph.py -k active_tutorial -v`

預期：PASS（4 passed）。

- [ ] **步驟 5：commit**

```bash
git add src/training_kb/repository.py tests/integration/test_repository_graph.py
git commit -m "feat(repository): 找出某功能目前的 active 教學"
```

---

### Task 7：反查「現在線上」引用某功能的步驟

**目的**：這是整個 Phase 09 最重要的函式，也是 Phase 16「只改第 3 步」的基礎。

**檔案**：
- 修改：`src/training_kb/repository.py`
- 測試：`tests/integration/test_repository_graph.py`

**介面**：
- 消費：`Repository.query_by_target`（Phase 03）、`Repository.get_tutorial`／`get_version`／`get_steps`（Phase 07）、`Repository.scan_entity`（Task 2）、`keys.parse_pk`／`parse_edge_sk`／`parse_step_pk`（Phase 02）
- 產出：
  - `Repository.find_steps_referencing(feature_id: str) -> list[str]`（**新增**；純 GSI 反查，回傳 STEP 的 PK 清單）
  - `Repository.find_current_published_steps_referencing(feature_id: str) -> list[TutorialStep]`

> **本階段選擇（處理 GSI 最終一致）**：`find_steps_referencing` 用 GSI 當快速路徑，落實「查詢知識圖譜」Rule 2；`find_current_published_steps_referencing` 則把 GSI 的候選與**基表 Scan 出來的全部教學**聯集起來，每一筆都用基表強一致讀重新確認 `current_version` 與 `published_at`。這樣即使 GSI 慢一拍少給了邊，答案仍然完整，符合設計文件 §10「改版前以基表一致讀取核對目前版的完整引用集合」。**不使用「多等幾秒」這種做法。**
>
> 退役（retired）教學若仍有已發布的 `current_version`，它的步驟**也會**被回傳；要不要對退役教學改版由 Phase 16 決定（設計文件 §8.4 要求保留歷史原文）。

- [ ] **步驟 1：寫測試**

```python
def _setup_two_versions(repo):
    """A 教學有 v1 與 v2，兩版的第 2 步都引用 Prepare，current_version 指向 v2。"""
    repo.put_tutorial(Tutorial(slug="prepare-meeting", current_version="prepare-meeting@v2",
                               topic="準備會議", feature_ids=["Prepare"],
                               status=TutorialStatus.active, cluster_id="c12"))
    for number in (1, 2):
        version_id = f"prepare-meeting@v{number}"
        put_version_item(repo, version_id, step_count=2,
                         published_at="2026-08-01T00:00:00Z" if number == 1
                         else "2026-08-20T00:00:00Z",
                         supersedes="prepare-meeting@v1" if number == 2 else None)
        put_step_item(repo, version_id, 1, feature_id="Share Summary", text="第一步")
        put_step_item(repo, version_id, 2, feature_id="Prepare", text="第二步")


def test_find_steps_referencing_uses_by_target(repo):
    _setup_two_versions(repo)
    repo.put_ticket(Ticket(id="t_881", source=TicketSource.email, text="問題",
                           author="u_01", ts="2026-08-02T09:00:00Z",
                           project_id="demo-project", feature_ids=["Prepare"]))

    pks = repo.find_steps_referencing("Prepare")
    # 只留 STEP 起點 + REFERENCES 關係，TICKET 的 ASKS_ABOUT 邊要被排除
    assert pks == ["STEP#prepare-meeting@v1#2", "STEP#prepare-meeting@v2#2"]


def test_current_published_steps_excludes_history(repo):
    _setup_two_versions(repo)
    steps = repo.find_current_published_steps_referencing("Prepare")
    assert [(s.tutorial_version, s.index) for s in steps] == [("prepare-meeting@v2", 2)]
    assert steps[0].feature_id == "Prepare"
    assert steps[0].text == "第二步"


def test_current_published_steps_skips_unpublished_version(repo):
    _setup_two_versions(repo)
    put_version_item(repo, "prepare-meeting@v3", step_count=2, published_at=None,
                     supersedes="prepare-meeting@v2")
    put_step_item(repo, "prepare-meeting@v3", 1, feature_id="Share Summary", text="第一步")
    put_step_item(repo, "prepare-meeting@v3", 2, feature_id="Prepare", text="第二步")
    repo.put_tutorial(Tutorial(slug="prepare-meeting", current_version="prepare-meeting@v3",
                               topic="準備會議", feature_ids=["Prepare"],
                               status=TutorialStatus.active, cluster_id="c12"))

    assert repo.find_current_published_steps_referencing("Prepare") == []


def test_current_published_steps_survive_stale_gsi(repo, monkeypatch):
    """就算 GSI 完全沒資料（模擬索引還沒更新），基表核對仍要找到步驟。"""
    _setup_two_versions(repo)
    monkeypatch.setattr(repo, "query_by_target", lambda target_pk: [])

    steps = repo.find_current_published_steps_referencing("Prepare")
    assert [(s.tutorial_version, s.index) for s in steps] == [("prepare-meeting@v2", 2)]


def test_current_published_steps_returns_empty_for_unknown_feature(repo):
    _setup_two_versions(repo)
    assert repo.find_current_published_steps_referencing("Notification Settings") == []


def test_current_published_steps_covers_several_tutorials(repo):
    _setup_two_versions(repo)
    repo.put_tutorial(Tutorial(slug="share-summary", current_version="share-summary@v1",
                               topic="分享摘要", feature_ids=["Prepare"],
                               status=TutorialStatus.active, cluster_id="c13"))
    put_version_item(repo, "share-summary@v1", step_count=1,
                     published_at="2026-08-05T00:00:00Z")
    put_step_item(repo, "share-summary@v1", 1, feature_id="Prepare", text="也提到 Prepare")

    steps = repo.find_current_published_steps_referencing("Prepare")
    assert [(s.tutorial_version, s.index) for s in steps] == [
        ("prepare-meeting@v2", 2), ("share-summary@v1", 1)
    ]
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：`uv run pytest tests/integration/test_repository_graph.py -k referencing -v`

預期：FAIL，`AttributeError: 'Repository' object has no attribute 'find_steps_referencing'`。

- [ ] **步驟 3：寫最少的程式讓測試通過**

```python
    def find_steps_referencing(self, feature_id: str) -> list[str]:
        """用 GSI by_target 反查，回傳引用這個功能的 STEP 主鍵清單（已排序去重）。

        對應「查詢知識圖譜」Rule 2：查詢誰引用 Feature 時使用 by_target 的 target。
        同一個 target 也會有 TICKET 的 ASKS_ABOUT 邊，所以要篩掉。
        提醒：GSI 只有最終一致讀，這份清單可能比實際少，不能單獨當作答案。
        """
        target = feature_pk(feature_id)
        step_pks: set[str] = set()
        for row in self.query_by_target(target):
            pk = str(row.get("PK", ""))
            sk = str(row.get("SK", ""))
            if not pk or not sk:
                continue
            try:
                if parse_pk(pk)[0] != "STEP":
                    continue
                if parse_edge_sk(sk)[0] != "REFERENCES":
                    continue
            except ValueError:
                continue                       # SK 是 META 或格式不合的 item 直接跳過
            step_pks.add(pk)
        return sorted(step_pks)

    def find_current_published_steps_referencing(self, feature_id: str) -> list[TutorialStep]:
        """回傳「目前已發布版本」中引用這個功能的步驟。

        流程（設計文件 §10）：
          1. GSI 反查取得候選 slug（快速路徑，落實 Rule 2）。
          2. 基表 Scan TUTORIAL 取得所有 slug（完整路徑，GSI 慢一拍也不會漏）。
          3. 每個 slug 都用基表強一致讀確認 current_version 與 published_at。
          4. 只回傳「該版正是 current_version 且已發布」的命中步驟（F17）。
        """
        slugs: set[str] = set()
        for pk in self.find_steps_referencing(feature_id):
            try:
                version_id, _index = parse_step_pk(pk)
                slugs.add(parse_version_id(version_id)[0])
            except ValueError:
                continue
        for row in self.scan_entity("TUTORIAL"):
            slug = row.get("slug")
            if isinstance(slug, str) and slug:
                slugs.add(slug)

        hits: list[TutorialStep] = []
        for slug in sorted(slugs):
            tutorial = self.get_tutorial(slug)            # 基表強一致讀
            if tutorial is None or not tutorial.current_version:
                continue
            version = self.get_version(tutorial.current_version)
            if version is None or not version.published_at:
                continue                                   # 尚未發布的版本不觸發改寫
            for step in self.get_steps(tutorial.current_version):
                if step.feature_id == feature_id:
                    hits.append(step)
        hits.sort(key=lambda s: (version_sort_key(s.tutorial_version), s.index))
        return hits
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：`uv run pytest tests/integration/test_repository_graph.py -k referencing -v`

預期：PASS（6 passed）。

- [ ] **步驟 5：commit**

```bash
git add src/training_kb/repository.py tests/integration/test_repository_graph.py
git commit -m "feat(repository): 反查目前已發布版本中引用功能的步驟"
```

---

### Task 8：列出某一版的回饋與瀏覽

**目的**：Phase 17（每日回饋檢視）與 Phase 19（指標）都要用。

**檔案**：
- 修改：`src/training_kb/repository.py`
- 測試：`tests/integration/test_repository_graph.py`

**介面**：
- 消費：`Repository.query_by_target`（Phase 03）、`Repository.get_feedback`（Task 3）、`Repository.scan_entity`（Task 2）
- 產出：
  - `Repository.list_feedback_of_version(version_id: str) -> list[Feedback]`
  - `Repository.list_views_of_version(version_id: str) -> list[TutorialView]`

> 設計文件 §10 指定的查法不同：回饋用 `by_target` 反查 `REFERS_TO` 再讀本體；瀏覽則「Scan TUTORIAL_VIEW，篩選 `tutorial_version` 與時間，再依 `user` 去重」。**去重是 Phase 19 Analytics 的工作，本函式一筆都不去重、一筆都不丟**（D14：同一使用者每次新的提交 ID 都算一筆）。

- [ ] **步驟 1：寫測試**

```python
def test_list_feedback_of_version(repo):
    for feedback_id, minute in (("f_12", 1), ("f_15", 2), ("f_19", 3)):
        repo.put_feedback(FeedbackModel(id=feedback_id,
                                        tutorial_version="prepare-meeting@v1",
                                        rating=2, user="u_01", category="找不到按鈕",
                                        comment="第三步沒有指出按鈕在哪一頁與位置",
                                        ts=f"2026-08-02T09:0{minute}:00Z"))
    repo.put_feedback(FeedbackModel(id="f_101", tutorial_version="prepare-meeting@v2",
                                    rating=5, user="u_03", category=None, comment=None,
                                    ts="2026-08-21T09:00:00Z"))

    got = repo.list_feedback_of_version("prepare-meeting@v1")
    assert [f.id for f in got] == ["f_12", "f_15", "f_19"]
    assert all(f.tutorial_version == "prepare-meeting@v1" for f in got)
    assert repo.list_feedback_of_version("share-summary@v1") == []


def test_list_feedback_keeps_every_submission_from_the_same_user(repo):
    """D14：同一使用者對同一版本的每次新提交都計一筆，這裡不去重。"""
    for feedback_id in ("f_20", "f_21"):
        repo.put_feedback(FeedbackModel(id=feedback_id,
                                        tutorial_version="prepare-meeting@v1",
                                        rating=3, user="u_01", category=None,
                                        comment=None, ts="2026-08-02T09:00:00Z"))
    assert len(repo.list_feedback_of_version("prepare-meeting@v1")) == 2


def test_list_views_of_version_keeps_every_record(repo):
    for user in ("u_01", "u_02"):
        repo.put_view(TutorialView(tutorial_version="prepare-meeting@v1",
                                   user=user, ts="2026-08-02T09:00:00Z"))
    # 同一人不同時間的兩筆瀏覽都要保留，去重是 Analytics 的事
    repo.put_view(TutorialView(tutorial_version="prepare-meeting@v1",
                               user="u_01", ts="2026-08-03T09:00:00Z"))
    repo.put_view(TutorialView(tutorial_version="prepare-meeting@v2",
                               user="u_01", ts="2026-08-21T09:00:00Z"))

    views = repo.list_views_of_version("prepare-meeting@v1")
    assert len(views) == 3
    assert sorted({v.user for v in views}) == ["u_01", "u_02"]
    assert repo.list_views_of_version("notification-settings@v1") == []
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：`uv run pytest tests/integration/test_repository_graph.py -k "list_feedback or list_views" -v`

預期：FAIL，`AttributeError: 'Repository' object has no attribute 'list_feedback_of_version'`。

- [ ] **步驟 3：寫最少的程式讓測試通過**

```python
    def list_feedback_of_version(self, version_id: str) -> list[Feedback]:
        """反查指定版本的全部回饋（「查詢知識圖譜」Rule 6）。

        走 GSI by_target 取得 REFERS_TO 邊，再回基表讀回饋本體。
        GSI 是最終一致的：剛寫入的回饋可能要一下子才查得到。
        每日 Review 在寫入後很久才執行，這個延遲不影響它的正確性；
        需要立刻看到剛寫入資料的流程請改用基表讀取。
        """
        target = version_pk(version_id)
        feedback: list[Feedback] = []
        seen: set[str] = set()
        for row in self.query_by_target(target):
            pk = str(row.get("PK", ""))
            sk = str(row.get("SK", ""))
            if not pk or not sk:
                continue
            try:
                kind, bare_id = parse_pk(pk)
                relation, _target = parse_edge_sk(sk)
            except ValueError:
                continue
            if kind != "FEEDBACK" or relation != "REFERS_TO" or bare_id in seen:
                continue
            seen.add(bare_id)
            item = self.get_feedback(bare_id)
            if item is not None:
                feedback.append(item)
        feedback.sort(key=lambda f: (f.ts, f.id))
        return feedback

    def list_views_of_version(self, version_id: str) -> list[TutorialView]:
        """回傳指定版本的全部瀏覽紀錄，不做任何去重。

        設計文件 §10：Scan TUTORIAL_VIEW 篩選 tutorial_version，再依 user 去重；
        「依 user 去重」是指標計算（Phase 19）的步驟，不在這裡做，
        否則 Phase 19 就看不到原始筆數了。
        """
        views = [
            TutorialView.model_validate(row)
            for row in self.scan_entity("VIEW")
            if row.get("tutorial_version") == version_id
        ]
        views.sort(key=lambda v: (v.ts, v.user))
        return views
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：`uv run pytest tests/integration/test_repository_graph.py -k "list_feedback or list_views" -v`

預期：PASS（3 passed）。

- [ ] **步驟 5：commit**

```bash
git add src/training_kb/repository.py tests/integration/test_repository_graph.py
git commit -m "feat(repository): 列出某一版的回饋與瀏覽紀錄"
```

---

### Task 9：查詢某條規則套用過哪些版本

**目的**：落實「查詢知識圖譜」Rule 5，並遵守 D17「以版本的 `rules_applied` 為權威」。

**檔案**：
- 修改：`src/training_kb/repository.py`
- 測試：`tests/integration/test_repository_graph.py`

**介面**：
- 消費：`Repository.query_pk`（Phase 03）、`Repository.get_version`（Phase 07）、`Repository.scan_entity`（Task 2）
- 產出：`Repository.list_versions_applying_rule(rule_id: str) -> list[str]`（回傳裸版本 ID）

> D17 的答案是 A：「以版本的 `rules_applied` 為權威，規則清單與 `APPLIED_TO` 邊可由它重建。」所以本函式做兩件事：
> 1. 讀 `RULE#<id>` 起點的 `APPLIED_TO#` 邊，但每一筆都回去看該版本的 `rules_applied` 有沒有真的寫這條規則；沒有就丟掉（邊是可重建的投影，不是權威）。
> 2. 再掃一次 VERSION，把「`rules_applied` 有這條規則但邊漏寫」的版本補進結果。
>
> `查詢知識圖譜.feature` 的 Example 用「回傳的版本**集合**為」比對，所以回傳值的排序不影響驗收；本函式固定依 `(slug, 版號)` 排序，讓結果可重現。

- [ ] **步驟 1：寫測試**

```python
def test_list_versions_applying_rule(repo):
    for version_id in ("prepare-meeting@v2", "share-summary@v1", "prepare-meeting@v3"):
        put_version_item(repo, version_id, step_count=1,
                         published_at="2026-08-20T00:00:00Z", rules_applied=["R-007"])
        repo.put_edge(keys.rule_pk("R-007"), "APPLIED_TO", keys.version_pk(version_id),
                      {"entity": "RULE", "rule_id": "R-007"})

    assert repo.list_versions_applying_rule("R-007") == [
        "prepare-meeting@v2", "prepare-meeting@v3", "share-summary@v1"
    ]
    assert repo.list_versions_applying_rule("R-999") == []


def test_rules_applied_is_the_authority(repo):
    """邊寫錯時以 rules_applied 為準：多的邊丟掉，漏的邊補回來。"""
    put_version_item(repo, "prepare-meeting@v2", step_count=1,
                     published_at="2026-08-20T00:00:00Z", rules_applied=["R-007"])
    put_version_item(repo, "share-summary@v1", step_count=1,
                     published_at="2026-08-20T00:00:00Z", rules_applied=[])
    repo.put_edge(keys.rule_pk("R-007"), "APPLIED_TO", keys.version_pk("share-summary@v1"),
                  {"entity": "RULE", "rule_id": "R-007"})

    assert repo.list_versions_applying_rule("R-007") == ["prepare-meeting@v2"]
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：`uv run pytest tests/integration/test_repository_graph.py -k applying_rule -v`

預期：FAIL，`AttributeError: 'Repository' object has no attribute 'list_versions_applying_rule'`。

- [ ] **步驟 3：寫最少的程式讓測試通過**

```python
    def list_versions_applying_rule(self, rule_id: str) -> list[str]:
        """回傳套用過這條規則的版本 ID（裸 ID，例如 "prepare-meeting@v2"）。

        D17：VERSION.rules_applied 才是權威，APPLIED_TO 邊只是可重建的投影。
        所以邊有而 rules_applied 沒有 -> 丟掉；rules_applied 有而邊漏寫 -> 補回來。
        """
        from_edges: set[str] = set()
        for row in self.query_pk(rule_pk(rule_id), sk_prefix="APPLIED_TO#"):
            try:
                relation, target = parse_edge_sk(str(row.get("SK", "")))
                kind, bare_id = parse_pk(target)
            except ValueError:
                continue
            if relation == "APPLIED_TO" and kind == "VERSION":
                from_edges.add(bare_id)

        confirmed: set[str] = set()
        for version_id in from_edges:
            version = self.get_version(version_id)
            if version is not None and rule_id in version.rules_applied:
                confirmed.add(version_id)

        for row in self.scan_entity("VERSION"):
            version_id = row.get("version_id")
            if isinstance(version_id, str) and rule_id in list(row.get("rules_applied", [])):
                confirmed.add(version_id)

        return sorted(confirmed, key=version_sort_key)
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：`uv run pytest tests/integration/test_repository_graph.py -k applying_rule -v`

預期：PASS（2 passed）。

- [ ] **步驟 5：commit**

```bash
git add src/training_kb/repository.py tests/integration/test_repository_graph.py
git commit -m "feat(repository): 以 rules_applied 為權威查詢規則套用的版本"
```

---

### Task 10：backfill 補漏掉的功能引用邊

**目的**：落實「查詢知識圖譜」Rule 7 與 F40：只補漏、不替換、不改文字、不建版本。

**檔案**：
- 修改：`src/training_kb/repository.py`
- 測試：`tests/integration/test_repository_backfill.py`

**介面**：
- 消費：`Repository.get_version`／`get_meta`／`get_object`／`put_edge`／`get_feature`（Phase 03、07）、`Repository.scan_entity`（Task 2）
- 產出：
  - `repository.MarkdownStep`（dataclass：`index: int`、`type: str`、`feature_id: str`、`text: str`）（新增）
  - `repository.parse_markdown_steps(markdown: str) -> list[MarkdownStep]`（新增）
  - `repository.BackfillReport`（dataclass：`added: list[int]`、`conflicts: list[int]`、`unresolved: list[int]`）
  - `Repository.list_step_items(version_id: str) -> list[dict]`（新增；含 SK 是 `META` 的漏抽 item）
  - `Repository.backfill_references(version_id, feature_of_step) -> BackfillReport`

> **本階段選擇**：
> - 只處理 `published_at` 有值的版本。未發布的版本仍在 Phase 07／08 的流程中，由 `verify_version_complete` 把關，不由 backfill 介入。
> - 步驟是**從 S3 全文重建**的：Phase 07 的 `render_markdown` 會把每一步寫成 `1. (type=click_ui, feature=Prepare) 文字`，所以全文本身就記著這一步當初引用哪個功能。`feature_of_step` 收到的 `TutorialStep` 已經帶著這個 `feature_id`，最單純的呼叫端寫法就是 `lambda step: step.feature_id or None`。
> - callback 回傳的 `feature_id` 必須是**既有**的 Feature（`get_feature` 查得到）才補邊；查不到就列入 `unresolved`。這對應設計文件 §10「必須確認恰好一個既有 Feature 才補邊，不能確定就列為待處理」。
> - backfill **不刪除任何 item**。補完之後，原本 SK 是 `META` 的 STEP item 仍然留著；Phase 07 的 `get_steps` 是用 `query_pk` 逐號讀，會同時看到兩筆，所以補完之後請一併確認 `verify_version_complete` 的結果（見第 7 節的完成檢查）。

- [ ] **步驟 1：寫測試**

`tests/integration/test_repository_backfill.py`：

```python
"""Phase 09：backfill 只補漏、不替換（F40）。"""

from helpers import put_step_item, put_version_item, put_version_markdown
from training_kb import keys
from training_kb.models import StepType, TutorialStep
from training_kb.repository import BackfillReport, parse_markdown_steps

MARKDOWN_STEPS = [
    ("click_ui", "Share Summary", "第一步"),
    ("click_ui", "Prepare", "第二步"),
    ("read", "Prepare", "第三步"),
]


def register_features(repo) -> None:
    """Phase 07 沒有 put_feature，所以直接用 put_meta 寫 FEATURE item。"""
    for feature_id in ("Prepare", "Share Summary"):
        repo.put_meta(keys.feature_pk(feature_id), {
            "entity": "FEATURE", "name": feature_id, "aliases": [],
            "first_seen": "2026-08-01T00:00:00Z"})


def prepare_version(repo, *, published: bool = True) -> str:
    version_id = "prepare-meeting@v2"
    put_version_item(repo, version_id, step_count=len(MARKDOWN_STEPS),
                     published_at="2026-08-20T00:00:00Z" if published else None)
    put_version_markdown(repo, version_id, MARKDOWN_STEPS)
    return version_id


def test_parse_markdown_steps_reads_only_the_steps_block():
    markdown = "\n".join([
        "# 準備會議", "", "## Problem", "", "1. 這一行不是步驟", "",
        "## Steps", "",
        "1. (type=click_ui, feature=Share Summary) 第一步",
        "2. (type=read, feature=Prepare) 第二步",
        "", "## Expected Outcome", "", "1. 這一行也不是步驟", "",
    ])
    steps = parse_markdown_steps(markdown)
    assert [(s.index, s.type, s.feature_id, s.text) for s in steps] == [
        (1, "click_ui", "Share Summary", "第一步"),
        (2, "read", "Prepare", "第二步"),
    ]


def test_backfill_adds_missing_edge(repo):
    register_features(repo)
    version_id = prepare_version(repo)
    put_step_item(repo, version_id, 1, feature_id="Share Summary", text="第一步")
    put_step_item(repo, version_id, 2, feature_id="Prepare", text="第二步")
    put_step_item(repo, version_id, 3, with_reference=False, text="第三步")  # 漏抽引用

    report = repo.backfill_references(version_id, lambda step: step.feature_id or None)

    assert report == BackfillReport(added=[3], conflicts=[], unresolved=[])
    rows = repo.query_pk(keys.step_pk(version_id, 3))
    assert any(row["SK"] == "REFERENCES#FEATURE#Prepare" for row in rows)


def test_backfill_passes_the_markdown_step_to_the_callback(repo):
    register_features(repo)
    version_id = prepare_version(repo)
    put_step_item(repo, version_id, 1, feature_id="Share Summary", text="第一步")
    put_step_item(repo, version_id, 2, feature_id="Prepare", text="第二步")
    put_step_item(repo, version_id, 3, with_reference=False, text="第三步")
    seen: list[TutorialStep] = []

    def analyse(step: TutorialStep) -> str | None:
        seen.append(step)
        return step.feature_id or None

    repo.backfill_references(version_id, analyse)

    assert [s.index for s in seen] == [3]
    assert seen[0].type is StepType.read
    assert seen[0].text == "第三步"
    assert seen[0].feature_id == "Prepare"
    assert seen[0].tutorial_version == version_id


def test_backfill_records_conflict_and_keeps_the_old_edge(repo):
    register_features(repo)
    version_id = prepare_version(repo)
    put_step_item(repo, version_id, 1, feature_id="Share Summary", text="第一步")
    put_step_item(repo, version_id, 2, feature_id="Prepare", text="第二步")
    put_step_item(repo, version_id, 3, feature_id="Prepare", text="第三步")

    # 分析說每一步都該指向 Prepare，但第 1 步已經有另一個引用 -> 記衝突，不替換
    report = repo.backfill_references(version_id, lambda step: "Prepare")

    assert report.added == []
    assert report.conflicts == [1]
    assert report.unresolved == []
    rows = repo.query_pk(keys.step_pk(version_id, 1))
    assert [row["SK"] for row in rows] == ["REFERENCES#FEATURE#Share Summary"]


def test_backfill_marks_unresolved_when_feature_unknown(repo):
    register_features(repo)
    version_id = prepare_version(repo)
    put_step_item(repo, version_id, 1, feature_id="Share Summary", text="第一步")
    put_step_item(repo, version_id, 2, with_reference=False, text="第二步")
    put_step_item(repo, version_id, 3, with_reference=False, text="第三步")

    def analyse(step: TutorialStep) -> str | None:
        # 第 2 步無法判斷；第 3 步給了一個不存在的 Feature
        return None if step.index == 2 else "Notification Settings"

    report = repo.backfill_references(version_id, analyse)

    assert report.added == []
    assert report.conflicts == []
    assert report.unresolved == [2, 3]


def test_backfill_lists_step_missing_from_the_table(repo):
    """S3 全文有第 3 步，但基表完全沒有這一步的 item -> 仍然可以補上。"""
    register_features(repo)
    version_id = prepare_version(repo)
    put_step_item(repo, version_id, 1, feature_id="Share Summary", text="第一步")
    put_step_item(repo, version_id, 2, feature_id="Prepare", text="第二步")

    report = repo.backfill_references(version_id, lambda step: step.feature_id or None)

    assert report.added == [3]
    rows = repo.query_pk(keys.step_pk(version_id, 3))
    assert [row["SK"] for row in rows] == ["REFERENCES#FEATURE#Prepare"]
    assert rows[0]["text"] == "第三步"


def test_backfill_skips_unpublished_version(repo):
    register_features(repo)
    version_id = prepare_version(repo, published=False)
    put_step_item(repo, version_id, 1, with_reference=False, text="第一步")

    report = repo.backfill_references(version_id, lambda step: "Prepare")

    assert report == BackfillReport(added=[], conflicts=[], unresolved=[])
    assert repo.query_pk(keys.step_pk(version_id, 1))[0]["SK"] == keys.META


def test_backfill_does_not_touch_text_or_create_version(repo):
    register_features(repo)
    version_id = prepare_version(repo)
    put_step_item(repo, version_id, 1, feature_id="Share Summary", text="原始文字")
    put_step_item(repo, version_id, 2, feature_id="Prepare", text="第二步")
    put_step_item(repo, version_id, 3, with_reference=False, text="第三步")
    before = repo.get_object("tutorials/prepare-meeting/v2.md")

    repo.backfill_references(version_id, lambda step: step.feature_id or None)

    assert repo.get_object("tutorials/prepare-meeting/v2.md") == before
    assert repo.query_pk(keys.step_pk(version_id, 1))[0]["text"] == "原始文字"
    assert repo.get_version("prepare-meeting@v3") is None
    assert [v.version_id for v in repo.list_versions_of_tutorial("prepare-meeting")] == [version_id]


def test_backfill_is_idempotent(repo):
    register_features(repo)
    version_id = prepare_version(repo)
    put_step_item(repo, version_id, 1, feature_id="Share Summary", text="第一步")
    put_step_item(repo, version_id, 2, feature_id="Prepare", text="第二步")
    put_step_item(repo, version_id, 3, with_reference=False, text="第三步")

    first = repo.backfill_references(version_id, lambda step: step.feature_id or None)
    second = repo.backfill_references(version_id, lambda step: step.feature_id or None)

    assert first.added == [3]
    assert second == BackfillReport(added=[], conflicts=[], unresolved=[])
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：`uv run pytest tests/integration/test_repository_backfill.py -v`

預期：FAIL，`ImportError: cannot import name 'BackfillReport' from 'training_kb.repository'`。

- [ ] **步驟 3：寫最少的程式讓測試通過**

在 `src/training_kb/repository.py` 的 import 區補上：

```python
import re
```

在模組層級（`class Repository` 之前）加入：

```python
@dataclass
class MarkdownStep:
    """從已發布全文解析出來的一個步驟。"""

    index: int
    type: str
    feature_id: str
    text: str


@dataclass
class BackfillReport:
    """backfill 的結果。三個清單裝的都是步驟編號（index）。

    added      -> 本次補上引用邊的步驟
    conflicts  -> 已經有另一個引用，分析結果卻不同；只記錄，不替換（F40）
    unresolved -> 無法確定恰好一個既有 Feature
    """

    added: list[int] = field(default_factory=list)
    conflicts: list[int] = field(default_factory=list)
    unresolved: list[int] = field(default_factory=list)


#: Phase 07 的 render_markdown 固定把每一步寫成
#: "1. (type=click_ui, feature=Prepare) 開啟會議頁面"
_MARKDOWN_STEP = re.compile(r"^(\d+)\.\s*\(type=([^,]+),\s*feature=(.*?)\)\s*(.*)$")


def parse_markdown_steps(markdown: str) -> list[MarkdownStep]:
    """從已發布全文取出每一步的編號、型態、引用功能與文字。

    只讀「## Steps」區塊，下一個「## 」開始就結束，
    這樣 Problem 或 Expected Outcome 裡剛好以數字開頭的句子不會被誤認成步驟。
    """
    steps: list[MarkdownStep] = []
    in_steps = False
    for line in markdown.splitlines():
        stripped = line.strip()
        if stripped.startswith("## "):
            in_steps = stripped == "## Steps"
            continue
        if not in_steps or not stripped:
            continue
        matched = _MARKDOWN_STEP.match(stripped)
        if matched is None:
            continue
        steps.append(
            MarkdownStep(
                index=int(matched.group(1)),
                type=matched.group(2).strip(),
                feature_id=matched.group(3).strip(),
                text=matched.group(4).strip(),
            )
        )
    return steps
```

在 `class Repository` 內新增：

```python
    def list_step_items(self, version_id: str) -> list[dict]:
        """回傳某一版的全部 STEP 原始 item，包含 SK 是 META 的漏抽 item。

        Phase 07 的 get_steps 只讀得到有引用邊的步驟；
        backfill 需要看到「沒有邊」的那些，所以另開這個入口。
        """
        return [
            row
            for row in self.scan_entity("STEP")
            if row.get("tutorial_version") == version_id
        ]

    def backfill_references(
        self,
        version_id: str,
        feature_of_step: Callable[[TutorialStep], str | None],
    ) -> BackfillReport:
        """補上漏抽的 Feature 引用邊。

        F40：只增加缺少的邊，不移除或替換既有引用；錯誤邊另列待處理。
        設計文件 §10：不改歷史文字、不因此產生新版本。

        feature_of_step 收到的 TutorialStep 由 S3 已發布全文重建，
        已經帶著全文記錄的 feature_id；最單純的呼叫端寫法是
        `lambda step: step.feature_id or None`。
        """
        report = BackfillReport()
        version = self.get_version(version_id)
        if version is None:
            raise PermanentError(f"找不到版本：{version_id}")
        if not version.published_at:
            return report                       # 只回填已發布版本

        body = self.get_object(version.s3_key)
        if body is None:
            raise PermanentError(f"版本 {version_id} 的全文不存在：{version.s3_key}")
        markdown_steps = {step.index: step for step in parse_markdown_steps(body.decode("utf-8"))}

        existing_by_index: dict[int, list[dict]] = {}
        for row in self.list_step_items(version_id):
            raw_index = row.get("index")
            if raw_index is None:
                continue
            existing_by_index.setdefault(int(raw_index), []).append(row)

        for index in sorted(set(markdown_steps) | set(existing_by_index)):
            rows = existing_by_index.get(index, [])
            referenced = [
                row for row in rows if str(row.get("SK", "")).startswith("REFERENCES#")
            ]
            source = markdown_steps.get(index)
            if source is None:
                # 全文沒有這一步，無法重建可信的 type 與文字，列為待處理。
                if not referenced:
                    report.unresolved.append(index)
                continue

            step = TutorialStep(
                tutorial_version=version_id,
                index=index,
                type=source.type,
                text=source.text,
                feature_id=source.feature_id,
            )
            decided = feature_of_step(step)

            if referenced:
                current = parse_pk(str(referenced[0].get("target", "")))[1]
                if decided and decided != current:
                    report.conflicts.append(index)   # 已有另一個引用：只記錄，不替換
                continue

            if not decided or self.get_feature(decided) is None:
                report.unresolved.append(index)      # 不能確定恰好一個既有 Feature
                continue

            self.put_edge(
                step_pk(version_id, index),
                "REFERENCES",
                feature_pk(decided),
                {
                    "entity": "STEP",
                    "tutorial_version": version_id,
                    "index": index,
                    "type": step.type.value,
                    "text": step.text,
                },
            )
            report.added.append(index)

        return report
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：

```bash
uv run pytest tests/integration/test_repository_backfill.py -v
uv run pytest -q
uv run ruff check .
```

預期：backfill 9 passed、全部測試 passed、ruff 顯示 `All checks passed!`。

- [ ] **步驟 5：commit**

```bash
git add src/training_kb/repository.py tests/integration/test_repository_backfill.py
git commit -m "feat(repository): backfill 只補漏的功能引用邊"
```

---

## 7. 完成檢查清單

全部打勾才算做完這一階段。

- [ ] `uv run pytest -q` 全部通過（含 Phase 03、07、08 的既有測試，代表改動 `scan_entity` 沒有弄壞別人）。
- [ ] `uv run ruff check .` 沒有錯誤。
- [ ] `Repository` 具備下列方法：

```bash
uv run python -c "
from training_kb.repository import Repository
need = ['backfill_references','find_active_tutorial_for_feature',
        'find_current_published_steps_referencing','find_feature_by_name_or_alias',
        'find_steps_referencing','get_feedback','get_release','get_rule','get_ticket',
        'list_feedback_of_version','list_rules','list_step_items','list_tickets',
        'list_versions_applying_rule','list_versions_of_tutorial','list_views_of_version',
        'put_feedback','put_release','put_rule','put_ticket','put_view']
print([n for n in need if not hasattr(Repository, n)] or 'OK')
"
```

預期輸出：`OK`。

- [ ] `repository.py` 裡沒有任何地方直接呼叫 `self.table.scan(` 或 `self.table.query(` 之後就 `return`；所有讀取都走 Phase 03 的 `self._paged(...)`。用這個指令確認：

```bash
grep -n "self.table.scan\|self.table.query" src/training_kb/repository.py
```

預期：只出現在 `_paged` 的呼叫參數位置（`self._paged(self.table.scan, ...)`、`self._paged(self.table.query, ...)`）。

- [ ] 手動驗證「歷史版本不被列入」：`test_current_published_steps_excludes_history` 通過。
- [ ] 手動驗證「退役教學不算 active」：`test_retired_tutorial_does_not_count_as_active` 通過。
- [ ] 手動驗證「多頁與空頁後仍有下一頁」：`test_list_versions_reads_every_page`、`test_scan_entity_returns_every_item_across_pages` 通過（兩者都用每頁 2 筆的 `paged_repo`）。
- [ ] 手動驗證 backfill 三種結果：`added`、`conflicts`、`unresolved` 各有一個通過的測試，而且 `test_backfill_is_idempotent` 確認重跑不會重複補。
- [ ] 補完邊之後，該版本仍能通過 Phase 07 的完整性核對。新增 `tests/integration/test_backfill_completeness.py`：

```python
"""補完引用邊之後，Phase 07 的 verify_version_complete 應該回報「沒有缺漏」。"""

from helpers import put_step_item, put_version_item, put_version_markdown
from training_kb import keys
from training_kb.content import verify_version_complete
from training_kb.models import Tutorial, TutorialStatus


def test_backfilled_version_is_complete(repo):
    for feature_id in ("Prepare", "Share Summary"):
        repo.put_meta(keys.feature_pk(feature_id), {
            "entity": "FEATURE", "name": feature_id, "aliases": [],
            "first_seen": "2026-08-01T00:00:00Z"})

    version_id = "prepare-meeting@v2"
    put_version_item(repo, version_id, step_count=2, published_at="2026-08-20T00:00:00Z")
    put_version_markdown(repo, version_id, [("click_ui", "Prepare", "第一步"),
                                            ("read", "Share Summary", "第二步")])
    put_step_item(repo, version_id, 1, feature_id="Prepare", text="第一步")
    repo.put_tutorial(Tutorial(slug="prepare-meeting", current_version=version_id,
                               topic="準備會議", feature_ids=["Prepare"],
                               status=TutorialStatus.active, cluster_id="c12"))

    report = repo.backfill_references(version_id, lambda step: step.feature_id or None)

    assert report.added == [2]
    assert verify_version_complete(repo, version_id) == []
```

執行：

```bash
uv run pytest tests/integration/test_backfill_completeness.py -v
```

預期：`1 passed`。

- [ ] 對應設計文件第 16 節 S3 切片的檢查「版本與引用齊全」：上面 `test_backfilled_version_is_complete` 就是它的可驗證版本。

---

## 8. 常見錯誤與排除

**1）`ModuleNotFoundError: No module named 'helpers'`**

- 症狀：測試檔 `from helpers import ...` 失敗。
- 原因：pytest 只有在測試檔所在目錄「沒有 `__init__.py`」時，才會把該目錄放進 `sys.path`。如果 `tests/integration/` 底下有 `__init__.py`，匯入方式就要改成套件路徑。
- 解法：確認 `tests/integration/` 沒有 `__init__.py`；若專案刻意採用套件式測試目錄，把匯入改成 `from tests.integration.helpers import ...` 並確保 `tests/` 與 `tests/integration/` 都有 `__init__.py`。兩種做法擇一，不要混用。

**2）`pydantic_core.ValidationError: Field required [type=missing]`（讀 Feedback 或 Release 時）**

- 症狀：`get_feedback` 或 `get_release` 炸掉。
- 原因：寫入時把值是 `None` 的欄位濾掉了。`Feedback.category`、`Feedback.comment`、`Release.old_name`、`Release.new_name` 在 Phase 02 是「必填但可為 null」，沒有預設值，所以 item 上一定要看得到這個鍵。
- 解法：用 Task 2 的 `entity_attrs()`，它**不會**濾掉 None。（相對地，Phase 07 的 `put_tutorial` 刻意濾掉 None，因為 Phase 08 的 publish 要用 `attribute_not_exists(current_version)` 判斷「還沒發布過」——兩者的需求不同，不要互相套用。）

**3）`TypeError: Float types are not supported. Use Decimal types instead.`**

- 症狀：寫 `Ticket.embedding` 時炸掉。
- 原因：DynamoDB 的 resource API 不收 `float`。
- 解法：一定要透過 `put_meta`／`put_edge` 寫入（它們內部會呼叫 Phase 03 的 `encode_numbers`）。**不要**自己呼叫 `self.table.put_item()` 繞過去。

**4）只讀到第一頁資料（資料一多就少幾筆）**

- 症狀：本機 20 筆測試都過，資料一多就開始漏。
- 原因：自己寫了 `self.table.scan(...)` 只呼叫一次，沒有處理 `LastEvaluatedKey`。
- 解法：所有讀取一律走 `self._paged(...)`。判斷條件不能寫成「這一頁沒資料就結束」，因為 `FilterExpression` 會讓某些頁剛好 0 筆（見第 5.4 節的官方說明）。要驗證有沒有真的讀完，用 `paged_repo` fixture（每頁 2 筆）跑一次。

**5）剛寫入的邊用 `query_by_target` 查不到**

- 症狀：寫完 STEP 邊馬上反查，回來是空的。
- 原因：GSI 只有最終一致讀，索引更新有延遲。
- 解法：需要正確答案的地方改用 `find_current_published_steps_referencing`（它會用基表強一致讀核對）。**不要**用 `time.sleep(2)`，設計文件 §10 明確禁止「只多等固定秒數便宣稱結果完整」。

**6）`backfill_references` 回報 `unresolved`，但我覺得步驟明明有對應功能**

- 症狀：`report.unresolved` 一直有東西。
- 原因有三種：（a）callback 回傳的 `feature_id` 在 FEATURE 表裡不存在；（b）S3 全文的該行不符合 `1. (type=..., feature=...) 文字` 格式，解析不到；（c）全文根本沒有這一步。
- 解法：先用 `repo.get_object(version.s3_key).decode()` 印出全文，再用 `parse_markdown_steps()` 看解析結果。情況（a）要先建立 Feature；情況（b）多半是全文被手動改過，不要在 backfill 裡猜，照設計文件 §10 列為待處理。

**7）`ValueError: 不是合法的關係 SK：'META'`**

- 症狀：反查函式在遇到 metadata item 時炸掉。
- 原因：`keys.parse_edge_sk` 只接受關係 SK，遇到 `META` 會丟 `ValueError`。
- 解法：呼叫前先判斷，或像 Task 7、8、9 的程式那樣包在 `try/except ValueError` 裡跳過。

**8）改了 `scan_entity` 之後，Phase 03 或 Phase 07 的測試變紅**

- 症狀：既有測試出現非預期結果。
- 原因：多半是把參數寫成位置參數（`scan_entity("VERSION", True)`）而不是 keyword-only。
- 解法：新參數一定要放在 `*` 之後，寫成 `def scan_entity(self, entity: str, *, consistent: bool = True)`。既有呼叫端只傳一個參數，行為不變（只是從最終一致讀變成強一致讀，結果只會更新、不會更少）。

---

## 9. 這階段不做的事

| 不做的事 | 留給哪一階段 |
|---|---|
| `get_proc`／`put_proc`／`list_procs`（PROVEN_WORKFLOW 的讀寫） | Phase 11（`11-Phase11-Rote-結構簽名與流程重放判定.md`）。接入來源事件 Rule 31 規定只有 Rote 接入層能讀寫 PROC，所以那一組方法跟 Rote 的判定邏輯放在一起做。 |
| 重寫 `get_tutorial`／`put_tutorial`／`get_version`／`get_steps`／`get_feature`／`list_features` | **不做。** Phase 07 已經實作，本階段只使用。 |
| Feature 的語意搜尋（cosine ≥ 0.85） | Phase 16（`16-Phase16-Release-Note-Update流程.md`）。本階段的 `find_feature_by_name_or_alias` 只做字面比對。 |
| 決定要不要改版（UPDATE／KEEP／RETIRE） | Phase 16。本階段只負責把「現在線上哪些步驟引用了這個功能」查出來。 |
| 平均評分、負面回饋數、重開票率的計算與去重 | Phase 19（`19-Phase19-Analytics-學習指標.md`）。本階段只把原始回饋與瀏覽紀錄完整交出去。 |
| 規則的 `status` 與 `validated_at` 變更 | Phase 20（`20-Phase20-規則驗證與狀態轉換.md`）。設計文件 §12.2：只有 Analytics 能寫驗證後 status。 |
| backfill 的排程（每天什麼時候跑） | Phase 14／Phase 18。設計文件 §14.3：backfill「與每日維護同批執行，保持獨立紀錄，不新增第四條教學 pipeline」。 |
| `backfill_references` 的 `feature_of_step` 實作（若要呼叫 Claude 重新抽取） | 由呼叫端提供。本階段只定義 callback 介面並測試三種回傳值的處理。 |

---

## 10. 對照：設計章節與 Rule 編號

| Rule 來源檔 | Rule 編號與原文 | 本階段哪個 Task 落實 |
|---|---|---|
| `查詢知識圖譜.feature` | Rule 1「查詢某起點的關係使用該起點的 PK」 | Task 9（`list_versions_applying_rule` 用 `query_pk(rule_pk, sk_prefix="APPLIED_TO#")`） |
| `查詢知識圖譜.feature` | Rule 2「查詢誰引用 Feature 時使用 by_target 的 target」 | Task 7（`find_steps_referencing`；只留 STEP 起點＋REFERENCES 關係，排除 TICKET 的 ASKS_ABOUT。對應該 Rule 的 Example「反查 Prepare 的引用步驟」） |
| `查詢知識圖譜.feature` | Rule 3「沿 Feature 關係邊反查不呼叫 AI」 | Task 7（整段只有 DynamoDB 呼叫，沒有任何 Bedrock 呼叫） |
| `查詢知識圖譜.feature` | Rule 4「可查詢某篇 Tutorial 所屬的版本」 | Task 5（`list_versions_of_tutorial`，基表 Scan 後篩 slug） |
| `查詢知識圖譜.feature` | Rule 5「可查詢某條 Authoring Rule 套用的版本」 | Task 9（Example「R-007 套用過三個版本」以版本集合比對） |
| `查詢知識圖譜.feature` | Rule 6「Feedback Review 以 refers_to 關係反查指定版本的回饋」 | Task 8（`list_feedback_of_version`） |
| `查詢知識圖譜.feature` | Rule 7「定期 backfill 漏抽的 Feature 引用邊」 | Task 10（`backfill_references`；排程留給 Phase 14／18） |
| `依改版更新教學.feature` | Rule 2「改名前後的 alias 對應同一個 Feature 節點」 | Task 4（`find_feature_by_name_or_alias`） |
| `依改版更新教學.feature` | Rule 5「by_target 反查只選出引用改版 Feature 的步驟」 | Task 7 |
| `依改版更新教學.feature` | Rule 3「改名不變更第一次建立的 Feature 主鍵」 | Task 4（比對只讀 `name`／`aliases`，永遠不改 `feature_id`；D06） |
| `分析工單.feature` | Rule 7「對應 Feature 已有教學時動作為 KEEP」 | Task 6（`find_active_tutorial_for_feature` 提供判斷依據；判斷本身在 Phase 13） |
| `建立教學版本.feature` | Rule 10「references 邊的 target 等於 SK 中的關係終點」 | Task 10（補邊時由 `put_edge` 同時寫 SK 與 `target`，保證一致） |
| `檢視學習指標.feature` | Rule 8「規則套用次數等於 applied_to 清單長度」 | Task 9 提供版本清單；長度與去重的計算在 Phase 19 |
| `收集教學回饋.feature` | Rule 10「同一使用者對同一版本的每次新提交都計一筆」 | Task 8（`list_feedback_of_version` 不去重，原始筆數完整交給 Phase 19） |

補充：設計文件第 20.10 節列出 `查詢知識圖譜.feature` 全部 7 條 Rule，責任模組都是 `repository`、設計段落都是 §10，因此本階段把 7 條全部落實完畢。

---

## 11. 參考來源

設計文件（`docs/design/training-kb.md`）：

- §9.1 鍵與原生型別：單表鍵設計、GSI `by_target`、View 的 SHA-256 鍵、「GSI 不另加排序鍵，先投影查詢需要的鍵」。
- §9.2 關係邊：`PK=起點`、`SK=關係#終點`、`target=終點`；五種關係名稱。
- §9.3 S3 與執行資訊：`tutorials/<slug>/v<n>.md`、`.diff`。
- §10 圖譜查詢與多跳定位：六種固定查法、分頁必讀完、GSI 最終一致的處理、backfill 只補漏。
- §14.3 執行參數：backfill「與每日維護同批執行，保持獨立紀錄」。
- §15 測試與驗收設計，「圖譜與索引」列：「多頁與空頁後仍有下一頁；GSI 延遲不誤判無影響；backfill 只補漏、不替換錯邊。」
- §16 交付切片 S3：「發布後讀到正確全文；中途失敗仍讀舊版；版本與引用齊全。」
- §18 待確認事項 O1（metadata SK 一律 `META`）、O2（操作紀錄與接受順序）；本階段沿用這兩項的「本計劃選擇」。
- §19.1 D04、D05、D06、D07、D14、D17、D21；§19.2 F12、F17、F40。
- §20.10 查詢知識圖譜的 7 條 Rule 對照。

規格檔：

- `docs/spec/features/查詢知識圖譜.feature`（7 條 Rule，含「反查 Prepare 的引用步驟」與「R-007 套用過三個版本」兩個 Example）。
- `docs/spec/features/依改版更新教學.feature`（Rule 2、Rule 3、Rule 5）。
- `docs/spec/.clarify/resolved/features/查詢知識圖譜_backfill_發現既有_Feature_引用錯誤時如何更新.md`（F40，答案 A：只增加缺少的邊，不移除或替換既有引用）。
- `docs/spec/erm.dbml`（`TUTORIAL_STEP.target` 等欄位說明）。

前面階段的文件（介面以它們的「產出」為準）：

- `02-Phase02-領域模型與資料鍵.md`：`keys.parse_pk`／`parse_edge_sk`／`parse_step_pk`／`entity_of`、各模型的欄位與 `ConfigDict(extra="ignore")`。
- `03-Phase03-Repository-本機儲存層.md`：`Repository._paged`、`encode_numbers`／`decode_numbers`、`put_meta`／`get_meta`／`put_edge`／`query_pk`／`query_by_target`／`scan_entity`、`tests/conftest.py` 的 `repo` 與 `paged_repo` fixture。
- `07-Phase07-Content-建立教學版本.md`：`render_markdown` 的固定格式、VERSION item 的 `slug` 與 `step_count`、STEP item 的屬性、`get_tutorial`／`put_tutorial`／`get_version`／`get_steps`／`get_feature`／`list_features`、`verify_version_complete`。

AWS 官方文件（2026-09-13 查證）：

- DynamoDB Query 分頁：<https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/Query.Pagination.html> — 「a page can return zero matching items and still include a `LastEvaluatedKey`」「The only way to know when you have reached the end of the result set is when `LastEvaluatedKey` is empty.」
- DynamoDB 讀取一致性：<https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/HowItWorks.ReadConsistency.html> — 基表可強一致讀，GSI 只有最終一致。
- DynamoDB 交易與限制：<https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/transaction-apis.html>
- boto3 DynamoDB 使用指南（Query／Scan 與 `boto3.dynamodb.conditions`）：<https://boto3.amazonaws.com/v1/documentation/api/latest/guide/dynamodb.html>（經 Context7 `/boto/boto3` 查證，來源檔 `docs/source/guide/dynamodb.rst`）
- moto 使用方式（`from moto import mock_aws`）：<https://docs.getmoto.org/en/latest/docs/getting_started.html>
