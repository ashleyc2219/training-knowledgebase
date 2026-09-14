# Phase 28：引用 Backfill 與規則投影重建實作計畫

> **給實作者：** 依 checkbox 逐步執行；每個 Task 先建立失敗測試，再寫最小實作。執行時使用 `superpowers:executing-plans` 或同等逐項流程。

**目標：** 補上漏掉的 `REFERENCES` 引用邊、把有疑慮的情況列成待處理，並以 `VERSION.rules_applied` 為唯一權威重建規則的 `applied_to` 與 `APPLIED_TO` 邊。

**架構：** 兩個修復函式都掛在 `Repository` 上，只寫關係邊與 `RULE` metadata，完全不碰 `VERSION`、既有步驟與 S3 全文。`backfill_references` 只加不改，補回來的內容逐字取自已發布版的 S3 全文；`rebuild_rule_projection` 是真正的重建，因為套用關係本來就由 `rules_applied` 推導。兩者都不呼叫模型。

**技術：** Python 3.12、Pydantic v2、pytest、boto3 DynamoDB 條件寫入與分頁、moto。

## 全域限制

- 唯一主來源是 [Training KB 設計 §8.2、§9.2、§10、§14.3](../../design/training-kb.md)。前置為 [Phase 23](./23-Phase23-未發布版本與關係完整寫入.md) 與 [Phase 27：固定圖譜查詢](./27-Phase27-固定圖譜查詢.md)，未通過時停止；下一階段是 [Phase 29：共用 Pipeline 執行器與 ASL 失敗語意](./29-Phase29-共用Pipeline執行器與ASL失敗語意.md)。
- **與 Phase 23 修正後的核對對接（controller 2026-09-14）：** `verify_version_complete` 現在也會把「多出來的 STEP／`APPLIED_TO`／`SUPERSEDES` 邊」當成問題，所以刪多餘邊與改寫 `applied_to` 必須一起做；本 Phase 的重建結果必須讓 `verify_version_complete` 回 `True`（整合測試直接斷言）。
- **IAM 相依（controller 2026-09-14 裁決）：** Phase 09 的真實資料角色刻意沒有 `dynamodb:DeleteItem`，所以 `delete_edge` 在雲端還不能用。本 Phase 照 00A 實作它並在 moto 上驗收；授權留給下一批（P41／P57 改 CDK 時）以「只對 `SK begins_with APPLIED_TO#`」的條件補上。
- 本階段不做：**不替換錯邊、不移除既有 `REFERENCES` 引用、不修改既有步驟的文字、不產生新版本、不改 `published_at` 或 `current_version`**、不新增第四條教學 pipeline、不建立 Feature。
- `backfill_references` 只處理**已發布版本**（設計 §10）；`published_at` 為 `None` 的版本可能正在 [Phase 23](./23-Phase23-未發布版本與關係完整寫入.md) 的建版途中，補寫會把半成品補成「看起來完整」，一律丟 `PermanentError` 拒絕。
- `backfill_references` 一律不呼叫模型；需要從原文重新判讀 Feature 的案例全部列進 `unresolved`（見第 6 節的本計畫選擇）。
- 每步只能有一個 Feature 引用（D05）。已有另一個引用時記入 `conflicts` 供人處理，**不追加第二條邊**。
- `rules_applied` 是套用關係的唯一權威（D17）；`applied_to` 與 `APPLIED_TO` 邊都由它重建並去重，三份表示不是三個獨立權威。
- 所有 Query／Scan 都要讀完分頁；空的一頁不等於沒有下一頁。
- O1–O7 gate 狀態：本 Phase 不依賴也不宣稱 O2／O3。修復動作只在維護批次執行，不在發布路徑上；它不能用來補救 [Phase 24](./24-Phase24-單篇教學發布提交.md)／[Phase 25](./25-Phase25-多篇教學整批發布.md) 的 partial publish，也不得被說成 O3 的替代方案。
- 以下程式檔均是實作時預計建立或修改；本計畫本身不代表它們已存在。

---

## 1. 你在整體流程的位置

```text
每日維護批次（與 Phase 48 同批執行，但獨立紀錄）
   |
   |   [你在這裡：backfill_references + rebuild_rule_projection]
   |
   +--> backfill_references(version_id)   只吃已發布版
   |        +--> 缺 REFERENCES 邊 -> 依 S3 全文補一筆（added）
   |        +--> 已有別的 Feature 引用 -> 只記 conflicts，不替換
   |        +--> 全文的 Feature 在基表不存在 -> unresolved，不建立 Feature
   |
   +--> rebuild_rule_projection(rule_id)
            +--> 掃 VERSION.rules_applied（唯一權威）
            +--> 補缺的 APPLIED_TO 邊、刪多餘邊、改寫 applied_to
            v
   Phase 27 查詢結果變完整 --> Phase 50 反查不漏 / Phase 54 套用次數不多計
```

## 2. 完成後看得到什麼

`prepare-meeting@v2`（已發布）的 S3 全文有四步，但基表只有第 1、2、4 步有 `REFERENCES` 邊，第 3 步的邊在一次部分寫入中漏掉：

```text
backfill_references("prepare-meeting@v2")
  -> BackfillReport(
       added=("STEP#prepare-meeting@v2#3",),
       conflicts=(),
       unresolved=(),
     )
新增一筆 item（設計 §9.1：步驟與引用是同一筆）：
  PK=STEP#prepare-meeting@v2#3  SK=REFERENCES#FEATURE#Prepare  target=FEATURE#Prepare
  entity=STEP 由 put_edge 導出；tutorial_version/number/type/text 逐字取自 v2.md 第 3 步
其他三步、VERSION、S3 .md/.diff、published_at 與 current_version 全部不變，也沒有 v3。
```

`R-007` 的 `applied_to` 記了三個版本，但 `share-summary@v1.rules_applied` 其實是空的：

```text
rebuild_rule_projection("R-007")
  -> ["prepare-meeting@v2", "prepare-meeting@v3"]
RULE#R-007.applied_to 改寫成這兩個；APPLIED_TO#VERSION#share-summary@v1 邊被刪除。
所有 VERSION item 與 rules_applied 內容完全不變。
```

## 3. 名詞小抄

| 名詞 | 白話意思 |
|---|---|
| backfill | 事後把漏掉的資料補回來；只補漏，不「順便改一改」。 |
| STEP item／缺邊 | 步驟與它的 Feature 引用是**同一筆** item（設計 §9.1）：`PK=STEP#<版本>#<編號>`、`SK=REFERENCES#FEATURE#<id>`，沒有另一筆 `SK=META`。所以「缺邊」就等於「缺整個 STEP item」，不是兩種情況。 |
| 錯邊 | 基表的邊指向的 Feature 和全文說的不一樣；本 Phase 只記錄，不動它。 |
| 投影（projection） | 可以由權威資料重新算出來的副本，例如 `applied_to`。 |
| 唯一權威 | 有衝突時以誰為準；套用關係一律以 `VERSION.rules_applied` 為準。 |
| 待處理（unresolved） | 程式不敢自己決定的情況，留給維護者看。 |
| `D05`／`F40` 這類編號 | 設計文件 §19 已解決的決策編號；`D` 開頭是資料決策，`F` 開頭是功能決策。 |

## 4. 預計檔案

| 動作 | 路徑 | 責任 |
|---|---|---|
| 修改 | `src/training_kb/repository.py` | `DELETABLE_RELATIONS`、`BackfillReport`、`delete_edge`、`backfill_references`、`rebuild_rule_projection`。 |
| 測試 | `tests/unit/test_backfill_references.py` | 補缺、不替換、conflicts、unresolved、不改歷史。 |
| 測試 | `tests/unit/test_rule_projection.py` | 以 `rules_applied` 重建、去重、刪多餘邊、不動 VERSION。 |
| 測試 | `tests/integration/test_maintenance_batch.py` | 分頁、空頁與重跑冪等（moto）。 |

## 5. 固定介面

### Consumes

```text
Repository.get_version / get_feature / get_meta(pk, model, *, consistent=True)    # Phase 06
Repository.update_meta(pk, changes, *, expected_revision) -> int                 # Phase 06，revision 不符丟 CoordinationError
Repository.revision_of(pk) -> int                                                # Phase 06（D27）
Repository.get_object(key) -> bytes | None                                       # Phase 07
Repository.put_edge(pk, relation, target_pk, attrs=None) -> None                 # Phase 07，target 與 entity 由它導出
Repository.list_edges(pk, relation=None) -> list[DynamoItem]                     # Phase 07，一致讀取且讀完分頁
Repository.scan_entity(entity, *, consistent=True, meta_only=True)               # Phase 08
item_to_model(item: DynamoItem, model: type[T]) -> T                             # Phase 08 模組函式（D29）
parse_markdown(markdown: str) -> TutorialContent                                 # Phase 22
version_sort_key(version_id) -> tuple[str, int]                                  # Phase 27
META / step_pk / feature_pk / rule_pk / version_pk / edge_sk                     # Phase 05
TutorialVersion / AuthoringRule（Phase 04）、PermanentError / CoordinationError（Phase 02）
```

### Produces

```python
DELETABLE_RELATIONS: frozenset[str] = frozenset({"APPLIED_TO"})   # 模組級

@dataclass(frozen=True)
class BackfillReport:                                             # 模組級
    added: tuple[str, ...]
    conflicts: tuple[str, ...]
    unresolved: tuple[str, ...]

def backfill_references(self, version_id: str) -> BackfillReport: ...
def rebuild_rule_projection(self, rule_id: str) -> list[str]: ...
def delete_edge(self, pk: str, relation: str, target_pk: str) -> None: ...
```

`DELETABLE_RELATIONS` 與 `BackfillReport` 是模組級名稱，必須放在 `Repository` **之前**
（方法的型別註解在 class body 求值時就要看得到它們）；三個方法接在 class 尾端。
`parse_markdown` 一律在 `backfill_references` **函式內** import：相依方向是 `content` 呼叫
`repository`（設計 §5），module 層反向 import 會循環（`adapters.py` 對 `ingress.py` 同樣處理）。

三個名稱都加在既有 `Repository` 類別上。`BackfillReport` 的三個欄位都是**步驟 PK 字串**的 tuple（例如 `"STEP#prepare-meeting@v2#3"`），已排序且去重，讓兩次執行結果可以直接比對。`delete_edge` 是 `put_edge` 的反向操作，**只允許刪 `APPLIED_TO`**（00A 第 6.3 節）：`REFERENCES` 是已發布版的歷史事實，程式不得刪（F40），所以這道白名單就是「不替換錯邊」的程式保險絲。本 Phase 只在 `rebuild_rule_projection` 內用它。

## 6. 設計細節

### 6.1 backfill 的三種結果

```text
version = get_version(version_id)；published_at 為 None 或版本不存在 -> PermanentError
   v
讀 S3 version.s3_key -> parse_markdown -> 每步的 (number, type, text, feature_id)
   v
讀基表 STEP#<version_id>#<number> 的 REFERENCES 邊（list_edges，一致讀取、讀完分頁）
   +-- 已有邊且 target 相同 --------> 什麼都不做（冪等）
   +-- 已有邊但 target 不同 --------> 記 conflicts，邊維持原樣，不追加第二條
   +-- 沒有邊，且 feature_id 有既有 Feature -> put_edge 依全文補一筆 ----> added
   +-- 沒有邊，且 feature_id 查不到 Feature -> unresolved（不建立 Feature）
```

**先看清楚資料形狀：** 設計 §9.1 把步驟與它的 Feature 引用放在同一筆 item（`SK=REFERENCES#FEATURE#…`），所以「缺邊」和「缺 STEP item」是同一件事，不是兩個分支。補邊就是照 S3 全文把那筆 item 寫回去：`target` 與 `entity` 由 `put_edge` 自己導出（**不可以把 `entity` 放進 `attrs`**，Phase 07 會因保留屬性丟 `PermanentError`），`attrs` **只帶 `type` 與 `text`**，值逐字取自 `parse_markdown`——這正是設計 §10 說的「優先沿用已保存的版本建立輸出」。

**（2026-09-14 更正，00A §3.6 優先）** 本節原本寫 `attrs` 還要帶 `tutorial_version` 與 `number`，與 00A §3.6「模型欄位可以由鍵導出時不落成 item 屬性——STEP 邊只存 `type` 與 `text`」以及 Phase 23 `_write_edges` 的實際寫法都不一致，會讓同一份資訊在 item 上多出一份會不一致的副本。補回來的 item 必須與 Phase 23 寫的**完全一樣**：屬性集合恰好是 `{PK, SK, target, entity, type, text}`，`tutorial_version`／`number` 由 `parse_step_pk` 還原、`feature_id` 由 `target` 還原。

**本計畫選擇（需要審閱者確認）：** 設計 §10 允許「若需從原文重新抽取 Feature，可呼叫文字分析」，但本 Phase 不呼叫模型，理由有三：`Repository` 依設計 §5 不得反向依賴 `writing`；`backfill_references(self, version_id)` 的簽名沒有 `Writer` 參數；設計同時要求「必須確認恰好一個既有 Feature 才補邊，不能確定就列為待處理」。已發布版的 S3 全文本來就把 `feature=<id>` 寫在步驟行上（Phase 22 的固定格式），所以正常情況根本不需要重新判讀；判讀不出來的（全文指向不存在的 Feature）一律進 `unresolved`，由維護者處理。這是收斂而非放寬，不影響任何 Rule 的可驗收性；若之後要加回模型輔助，必須另開明示入口並與「一般關係查詢不呼叫 AI」分開計數（D46）。

不做的事情要寫死在測試裡：**不替換錯邊**（`conflicts` 案例執行前後的邊 item 必須 byte 相同）、**不改歷史**（`VERSION`、既有步驟的 `text`、S3 `.md`／`.diff` 前後相同）、**不產生新版本**（該篇的版本數量前後相同）、**不觸發發布**（`published_at`、`current_version` 不變）。

### 6.2 規則投影重建

```text
scan_entity("VERSION")（讀完分頁，只留 SK == META） -> rules_applied 含 rule_id 的 version_id
        v
 expected = 去重 + 依 version_sort_key 排序
   +----+--------------------------------+
現有 APPLIED_TO 邊                  RULE.applied_to
   +-- expected 有、邊沒有 -> put_edge    +-- 一律改寫成 expected
   +-- 邊有、expected 沒有 -> delete_edge
   +-- 兩邊都有 -------------> 不動
        v
 回傳 expected
```

`scan_entity("VERSION")` 的掃描範圍同時涵蓋 `VERSION#…` 的 metadata item 與它的 `SUPERSEDES` 邊（`entity` 等於 PK 前綴）；[Phase 08](./08-Phase08-分頁查詢與一致讀取基礎.md) 的預設 `meta_only=True` 已經濾掉邊，本 Phase 仍明確再濾一次 `SK != META` 才用 `item_to_model` 轉模型；直接 `TutorialVersion.model_validate(item)` 會被 strict 模型拒絕（D29）。

為什麼這裡可以刪邊，而 backfill 不能：`REFERENCES` 邊描述的是**已發布版本的歷史事實**，錯了也不能由程式片面改寫（F40）；`applied_to` 與 `APPLIED_TO` 邊則是 `rules_applied` 的投影（D17），留著多餘邊會讓設計 §12.1 的「規則套用次數＝去重且核對過的 `applied_to` 長度」多計，直接影響 [Phase 54](./54-Phase54-重開票與呼叫規則指標.md) 的指標。重建過程**完全不寫 `VERSION` item**，測試要直接斷言這一點。

`applied_to` 的改寫使用 [Phase 06](./06-Phase06-Repository-Metadata與實體讀寫.md) 的 `update_meta` compare-and-swap，`expected_revision` 由同樣屬於 Phase 06 的 `revision_of(pk)` 取得（D27；領域模型不帶 `_revision`）。revision 不符代表在這兩個呼叫之間有人改了這條規則：`update_meta` 會丟 `CoordinationError`，本 Phase **不攔截、不重試、不靜默覆蓋**，由維護批次記錄後下一輪重跑。本 Phase 也**不寫 `RULE.status`**——只有 Analytics 能寫驗證後狀態（設計 §7.6、§12.2）。

執行時機依設計 §14.3：backfill 與每日維護同批執行，保持獨立紀錄，**不新增第四條教學 pipeline**。兩個函式重跑都必須冪等：同一個 `version_id` 連跑兩次，第二次的 `added` 為空、`conflicts`／`unresolved` 內容不變；同一個 `rule_id` 連跑兩次回同一個清單。

## 7. TDD Tasks

### Task 1：只補缺邊，不替換錯邊

- [x] **Step 1：建立失敗測試**

`repo` 是兩個測試檔共用的 fixture，定義在 `tests/unit/test_backfill_references.py`（**不放 `conftest.py`**：`tests/unit/conftest.py` 的 owner 是 P15、修改者只有 P55，00A §3.2；`test_rule_projection.py` 直接 import 本檔，與 Phase 23 的 `test_version_complete.py` 同一個作法）。它是一個**真的** `Repository`，只有底下的儲存層換成記憶體裡的 `FakeTable`／`FakeBucket`（**不是假的 `Repository`**：假掉被測物件的話「只補缺的邊」「不替換錯邊」「讀完分頁」全部會變成在測假物件；沿用 Phase 27 `test_graph_queries.py` 的作法）。`FakeTable` 只實作 `Repository` 真的會呼叫的六個 boto3 操作（`put_item`／`get_item`／`update_item`／`delete_item`／`query`／`scan`），`scan` 可以排出**空的中間頁**（空頁仍帶 `LastEvaluatedKey`）。器材方法：`drop_edge(pk, relation, target=None)`／`set_edge`／`add_edge` 直接動邊，`set_rules_applied(version_id, ids)` 改版本欄位，`edge_item(pk, relation)` 回整筆 item 供 byte 比對、`edge_targets(pk, relation)` 回排序後的 target 清單，`get_rule(rule_id)` 讀 `RULE` metadata，`markdown_step(version_id, number)` 回 S3 全文解析出的那一步，`snapshot(slug)`／`full_snapshot()` 記下版本清單、各步文字、S3 物件、`published_at`、`current_version`，以及本次寫過的 PK 與 S3 key。

```python
import pytest

from training_kb.errors import PermanentError


def test_backfill_adds_missing_edge_only(repo):
    repo.drop_edge("STEP#prepare-meeting@v2#3", "REFERENCES")
    before = repo.snapshot("prepare-meeting")
    report = repo.backfill_references("prepare-meeting@v2")
    assert report.added == ("STEP#prepare-meeting@v2#3",)
    assert report.conflicts == () and report.unresolved == ()
    restored = repo.edge_item("STEP#prepare-meeting@v2#3", "REFERENCES")
    assert restored["SK"] == "REFERENCES#FEATURE#Prepare" and restored["entity"] == "STEP"
    assert restored["target"] == "FEATURE#Prepare"
    assert restored["text"] == repo.markdown_step("prepare-meeting@v2", 3).text
    assert repo.snapshot("prepare-meeting").versions == before.versions


def test_backfill_records_conflict_without_replacing(repo):
    repo.set_edge("STEP#prepare-meeting@v2#3", "REFERENCES", "FEATURE#Notify")
    before = repo.edge_item("STEP#prepare-meeting@v2#3", "REFERENCES")
    report = repo.backfill_references("prepare-meeting@v2")
    assert report.added == ()
    assert report.conflicts == ("STEP#prepare-meeting@v2#3",)
    assert repo.edge_item("STEP#prepare-meeting@v2#3", "REFERENCES") == before


def test_backfill_refuses_unpublished_version(repo):
    assert repo.get_version("share-summary@v2").published_at is None
    with pytest.raises(PermanentError, match="share-summary@v2"):
        repo.backfill_references("share-summary@v2")
```

- [x] **Step 2：執行並確認紅燈**

```bash
uv run pytest tests/unit/test_backfill_references.py -q
```

預期：FAIL，訊號包含 `cannot import name 'BackfillReport'`（實測相符）。

- [x] **Step 3：建立最小實作**

三個 Task 都寫在 `src/training_kb/repository.py`，需要的 import（`dataclasses.dataclass`、`PermanentError`、`META`／`step_pk`／`feature_pk`／`rule_pk`／`edge_sk`、`TutorialVersion`／`AuthoringRule`、`parse_markdown`、`item_to_model`）加一次就好。

```python
@dataclass(frozen=True)
class BackfillReport:
    added: tuple[str, ...]
    conflicts: tuple[str, ...]
    unresolved: tuple[str, ...]


def backfill_references(self, version_id):
    version = self.get_version(version_id)
    if version is None or version.published_at is None:
        raise PermanentError(f"{version_id} 不是已發布版本，不在 backfill 範圍")
    body = self.get_object(version.s3_key)
    if body is None:
        raise PermanentError(f"{version_id} 缺少可比對的全文")
    added, conflicts, unresolved = [], [], []
    for draft in parse_markdown(body.decode("utf-8")).steps:
        pk = step_pk(version_id, draft.number)
        target = feature_pk(draft.feature_id)
        existing = [str(edge["target"]) for edge in self.list_edges(pk, "REFERENCES")]
        if target in existing:
            continue                                   # 已一致，冪等
        if existing:
            conflicts.append(pk)                       # 指向別的 Feature：只記錄
            continue
        if self.get_feature(draft.feature_id) is None:
            unresolved.append(pk)                      # 無法確認恰好一個既有 Feature
            continue
        self.put_edge(pk, "REFERENCES", target,
                      {"type": str(draft.type), "text": draft.text})   # 只有兩個屬性
        added.append(pk)
    return BackfillReport(_sorted_step_pks(added), _sorted_step_pks(conflicts),
                          _sorted_step_pks(unresolved))
```

`_sorted_step_pks(values)` 是同檔的模組級私有函式：`tuple(sorted(set(values), key=parse_step_pk))`。
排序鍵用 `parse_step_pk`（回 `(version_id, number)`）**不是字串本身**——字典序會把
`STEP#a@v2#10` 排到 `#3` 前面，與 `version_sort_key` 擋掉的是同一個坑。

- [x] **Step 4：補上 unresolved 與冪等案例並跑綠燈**（`unresolved`：全文第 4 步的 `feature=` 指向基表不存在的 Feature，斷言 `added == ()` 且沒有新增任何 `FEATURE#` item；冪等：連跑兩次，第二次 `added == ()` 且其餘欄位相同）

```bash
uv run pytest tests/unit/test_backfill_references.py -q
```

- [x] **Step 5：提交**

```bash
git add src/training_kb/repository.py tests/unit/test_backfill_references.py
git commit -m "feat(repository): 只補缺的 Feature 引用邊"
```

### Task 2：backfill 不改歷史、不產新版

- [x] **Step 1：建立失敗測試**（補邊必然寫出一筆 `PK=STEP#…`，要鎖的是**只寫 `added` 那幾個 PK、內容逐字等於 S3 全文，其餘一律不動**）

```python
def test_backfill_never_touches_history_or_creates_versions(repo):
    repo.drop_edge("STEP#prepare-meeting@v2#3", "REFERENCES")
    before = repo.full_snapshot()
    repo.backfill_references("prepare-meeting@v2")
    after = repo.full_snapshot()
    assert after.versions == before.versions
    assert after.objects == before.objects                 # S3 .md/.diff byte 相同
    assert after.published_at == before.published_at
    assert after.current_version == before.current_version
    assert after.written_pks == {"STEP#prepare-meeting@v2#3"}
    assert after.written_s3_keys == set()
    others = {n: t for n, t in after.steps_text.items() if n != 3}
    assert others == before.steps_text
    assert after.steps_text[3] == repo.markdown_step("prepare-meeting@v2", 3).text
```

- [x] **Step 2：讓 fake repository 記錄每次寫入的鍵並確認紅燈**

`written_pks` 記每次 `put_item` 的 PK、`written_s3_keys` 記每次 `put_object` 的 key。一旦出現 `VERSION#`、`TUTORIAL#`、`RULE#` 或任何 S3 key，測試就失敗。

```bash
uv run pytest tests/unit/test_backfill_references.py -q -k never_touches
```

預期：FAIL，訊號包含 `AttributeError` 或 `written_pks`（fixture 尚未記錄寫入）。實測：Task 1／2 的
斷言寫在同一支檔、同一輪 RED 一起看到，訊號是 `'MaintenanceRepository' object has no attribute
'backfill_references'`；`written_pks`／`written_s3_keys` 的記錄從一開始就做在 `FakeTable`／
`FakeBucket` 上（快照會把寫入紀錄清空，所以 `after.written_pks` 恰好是那個動作寫過的 PK）。

- [x] **Step 3：跑綠燈並提交**

```bash
uv run pytest tests/unit/test_backfill_references.py -q
git add tests/unit/test_backfill_references.py
git commit -m "test(repository): 鎖定 backfill 不改歷史"
```

**（2026-09-14 實作差異）** Task 1 與 Task 2 的斷言寫在同一支檔、同一輪 RED 一起看到，
所以合併成 Task 1 的那一次提交（`feat(repository): 只補缺的 Feature 引用邊`），沒有另外一次
test-only commit。`repository.py` 的 `delete_edge`／`rebuild_rule_projection` 也在同一次落地
（Task 1 Step 3 已說明「三個 Task 都寫在 `src/training_kb/repository.py`」）；Task 3 的 RED 是
把這兩個方法暫時移除後實測出來的，見報告第 3 節。

### Task 3：以 rules_applied 重建規則投影

- [x] **Step 1：建立失敗測試**（新檔 `tests/unit/test_rule_projection.py` 開頭同樣要 `import pytest` 與 `from training_kb.errors import PermanentError`）

```python
def test_rebuild_rule_projection_uses_rules_applied_as_the_only_authority(repo):
    repo.set_rules_applied("prepare-meeting@v2", ["R-007"])
    repo.set_rules_applied("prepare-meeting@v3", ["R-007"])
    repo.set_rules_applied("share-summary@v1", [])
    repo.add_edge("RULE#R-007", "APPLIED_TO", "VERSION#share-summary@v1")
    repo.drop_edge("RULE#R-007", "APPLIED_TO", "VERSION#prepare-meeting@v3")
    before_versions = repo.full_snapshot().versions
    result = repo.rebuild_rule_projection("R-007")
    assert result == ["prepare-meeting@v2", "prepare-meeting@v3"]
    assert repo.get_rule("R-007").applied_to == result
    assert repo.edge_targets("RULE#R-007", "APPLIED_TO") == [
        "VERSION#prepare-meeting@v2", "VERSION#prepare-meeting@v3",
    ]
    assert repo.full_snapshot().versions == before_versions
    assert repo.rebuild_rule_projection("R-007") == result


def test_delete_edge_only_accepts_applied_to(repo):
    with pytest.raises(PermanentError, match="REFERENCES"):
        repo.delete_edge("STEP#prepare-meeting@v2#3", "REFERENCES", "FEATURE#Prepare")
```

- [x] **Step 2：執行並確認紅燈**

```bash
uv run pytest tests/unit/test_rule_projection.py -q
```

預期：FAIL，訊號包含 `'Repository' object has no attribute 'rebuild_rule_projection'`。
實測：fixture 是 `Repository` 的子類別，所以訊息前綴是 `'MaintenanceRepository'`。

- [x] **Step 3：建立最小實作**

```python
DELETABLE_RELATIONS = frozenset({"APPLIED_TO"})


def delete_edge(self, pk, relation, target_pk):
    if relation not in DELETABLE_RELATIONS:
        raise PermanentError(f"不允許刪除 {relation} 邊；只有 APPLIED_TO 是可重建的投影")
    self._table.delete_item(Key={"PK": pk, "SK": edge_sk(relation, target_pk)})


def rebuild_rule_projection(self, rule_id):
    versions = [
        item_to_model(item, TutorialVersion)
        for item in self.scan_entity("VERSION")
        if str(item["SK"]) == META
    ]
    expected = sorted(
        {v.version_id for v in versions if rule_id in v.rules_applied}, key=version_sort_key
    )
    pk = rule_pk(rule_id)
    rule = self.get_meta(pk, AuthoringRule)      # 先確認規則在，才動任何一筆邊
    if rule is None:
        raise PermanentError(f"找不到規則 {rule_id}")
    wanted = {version_pk(version_id) for version_id in expected}   # 前綴只由 keys.py 加
    current = {str(edge["target"]) for edge in self.list_edges(pk, "APPLIED_TO")}
    for target in sorted(wanted - current):
        self.put_edge(pk, "APPLIED_TO", target)
    for target in sorted(current - wanted):
        self.delete_edge(pk, "APPLIED_TO", target)
    if rule.applied_to != expected:
        self.update_meta(pk, {"applied_to": expected}, expected_revision=self.revision_of(pk))
    return expected
```

**（2026-09-14 更正）** `get_meta` 的存在確認移到**動邊之前**：規則不存在時（基表只剩孤兒邊）
原本的順序會先刪掉幾條邊才丟 `PermanentError`，留下「邊改了一半、欄位沒改」的中間狀態。
`update_meta` 的 `changes` 值要先宣告成 `list[DynamoValue]`（`list` 在 mypy 下是不變的，
直接傳 `list[str]` 過不了 strict）。

- [x] **Step 4：補上三個案例並跑綠燈**（沒有任何版本套用該規則時回 `[]`、刪光所有邊、`applied_to` 改成 `[]`；VERSION 的 Scan 中間夾一個空頁仍讀到最後一頁；`RULE.status` 與所有 `VERSION` item 前後完全不變）。另外補了四條：`@v10` 依版號而不是字典序排、`rules_applied` 含該規則的**未發布版**照樣算（權威是 `rules_applied` 不是 `published_at`，與 Phase 27 的 `list_versions_applying_rule` 同一套判準）、規則不存在時孤兒邊原封不動、`revision` 不符時 `CoordinationError` 往外拋且 `applied_to` 沒被覆寫。

```bash
uv run pytest tests/unit/test_rule_projection.py -q
uv run pytest tests/integration/test_maintenance_batch.py -q
```

- [x] **Step 5：提交**

```bash
git add tests/unit/test_rule_projection.py tests/integration/test_maintenance_batch.py
git commit -m "feat(repository): 以 rules_applied 重建規則投影"
```

（`git add tests/integration` 整個目錄會把別的 agent 進行中的檔案一起提交，COMMON.md 的 git 規則
只允許逐檔 add；`repository.py` 的三個方法在 Task 1 那一次提交就一起落地，見下方說明。）

## 8. 驗收矩陣

| 路徑 | 輸入 | 預期資料結果 |
|---|---|---|
| Happy | 已發布的 v2 第 3 步缺邊 | `added` 一筆；`target` 等於 SK 中的關係終點，`type`／`text` 逐字等於 `v2.md`。 |
| Happy | R-007 少一條邊、多一條邊 | 補一條、刪一條、`applied_to` 改寫成兩個版本。 |
| Failure | 該步已有指向別的 Feature 的邊 | 只進 `conflicts`；邊 item byte 不變，不追加第二條。 |
| Failure | 全文的 `feature=` 指向不存在的 Feature | 進 `unresolved`；不建立 Feature、不補邊。 |
| Failure | 傳入 `published_at is None` 或不存在的版本；`delete_edge(..., "REFERENCES", ...)` | 兩者都 `PermanentError`：不補半成品、只有 `APPLIED_TO` 可刪。 |
| Failure | `update_meta` revision 不符 | `CoordinationError` 往外拋；不重試、不靜默覆蓋 `applied_to`。 |
| Boundary | 同一版本連跑兩次 backfill | 第二次 `added == ()`，其餘欄位相同。 |
| Boundary | 沒有任何版本套用該規則 | 回 `[]`；邊全刪、`applied_to` 清空；不改 `status`。 |
| Boundary | VERSION Scan 中間一頁為空；同次掃到 `SUPERSEDES` 邊 | 仍讀到最後一頁；邊被 `SK != META` 濾掉，不當成版本。 |
| Invariant | 兩個函式各跑一輪 | 寫入的 PK 只有 `added` 列出的 `STEP#`、`RULE#R-007` 與它的 `APPLIED_TO` 邊；版本數、既有步驟文字、S3 物件全部不變。 |

人工驗收：對同一篇教學在執行前後各匯出一次 `VERSION`、`STEP`、`tutorials/<slug>/v<n>.md` 與 `v<n>.diff`，除了 `added` 那幾筆 `STEP` 以外必須 byte 相同，而補回來的那筆要逐欄比對 `.md` 的同一步；再用 [Phase 27](./27-Phase27-固定圖譜查詢.md) 的 `find_current_published_steps_referencing` 確認補邊後結果變完整。不能只看測試顯示 PASS。

**moto 的 GSI 是即時的**（Phase 27 報告 §5）：整合測試刪掉 STEP item 之後 `by_target` 候選也跟著消失，所以看到的是「反查安靜地少一步」，不是 Phase 27 那條 `PermanentError`。真實 DynamoDB 的 GSI 落後時才會走到 `PermanentError` 那條路徑；兩種症狀的修法都是同一個 backfill，但**真實行為未驗證**，留給 P41 起的真實接線（controller 2026-09-14「離線開發優先」）。

## 9. 常見錯誤與停止條件

| 症狀 | 原因 | 修正／停止 |
|---|---|---|
| 錯邊被改成「正確」的 Feature | 把 backfill 當資料清理 | 停止：F40 只允許增加缺少的邊；錯邊另列待處理，`delete_edge` 也擋掉 `REFERENCES`。 |
| 同一步出現兩條 `REFERENCES` 邊 | 已有邊時仍追加 | 停止：每步恰好一個 Feature（D05）；改成記 `conflicts`。 |
| `added` 永遠是空的 | 先用 `get_steps` 判斷「有沒有 STEP item」，再判斷「有沒有邊」——兩者是同一筆，第一關就把缺邊案例吃成 `unresolved` | 只用 `list_edges(step_pk(...), "REFERENCES")` 判斷，缺了就依 S3 全文補。 |
| `PermanentError: edge attributes are reserved` | 把 `entity` 或 `target` 塞進 `put_edge` 的 `attrs` | 只傳 `type`／`text`，其餘（`target`、`entity`、`tutorial_version`、`number`、`feature_id`）一律由 `put_edge` 導出或由鍵還原（00A §3.6）。 |
| backfill 順手產生新版本或造出 Feature | 想「修好順便重發」、把 `unresolved` 當成要補齊 | 停止：不建版本、不改既有文字、不切 `current_version`、不造 Feature。 |
| `applied_to` 只增不減；或重建時順手改 `rules_applied`／`RULE.status` | 把投影當歷史紀錄、搞反權威方向、把修復當驗證 | `applied_to` 是投影，多餘邊要刪；`VERSION` 一個欄位都不能寫，只有 Analytics 能寫驗證後 status。 |
| 用 backfill 補救 partial publish | 把修復當 O3 解法 | 停止：發布同步問題留在 [Phase 12](./12-Phase12-O3發布切換整合驗證.md)／25 的 FAIL。 |

## 10. 來源與 Rule 對照

- [查詢知識圖譜.feature](../../spec/features/查詢知識圖譜.feature)
  - Rule 7：「定期 backfill 漏抽的 Feature 引用邊」→ **primary**；Task 1 `test_backfill_adds_missing_edge_only` 與 `test_backfill_records_conflict_without_replacing`、Task 2 的不改歷史斷言，共同覆蓋「只增加缺少的邊、不移除或替換既有引用、錯誤邊另列待處理、不因此建立新 TutorialVersion」。
  - Rule 5：「可查詢某條 Authoring Rule 套用的版本」→ **相關（primary 在 [Phase 27](./27-Phase27-固定圖譜查詢.md)）**；Task 3 讓 Phase 27 的查詢結果與投影一致。
- [套用教學規則.feature](../../spec/features/套用教學規則.feature)
  - Rule 6：「套用規則的版本記錄於規則的 applied_to」→ **primary**；Task 3 直接斷言 `applied_to` 與 `APPLIED_TO` 邊都由 `rules_applied` 重建並去重。
  - Rule 7：「版本的 rules_applied 記錄本次套用的規則」→ **相關（primary 在 [Phase 19](./19-Phase19-Active規則選取與注入.md)）**；本 Phase 只斷言重建過程完全不寫 `VERSION` item，`rules_applied` 保持權威。
- [建立教學版本.feature](../../spec/features/建立教學版本.feature) Rule 8「建立 TutorialStep 時保存 references Feature 邊」（primary 在 [Phase 23](./23-Phase23-未發布版本與關係完整寫入.md)）、Rule 9「沒有 Feature 或引用多個 Feature 的步驟不可保存」（primary 在 [Phase 21](./21-Phase21-教學內容與步驟引用驗證.md)）、Rule 10「references 邊的 target 等於 SK 中的關係終點」（primary 在 [Phase 07](./07-Phase07-S3物件與關係邊讀寫.md)）→ 三條都是**相關**；Task 1 斷言補出來的那筆 item 同時滿足這三條。
- 設計 §10：backfill 比對已發布版本的 S3 Steps 與基表 `STEP`／`REFERENCES`；優先沿用已保存的版本建立輸出；只有確認恰好一個既有 Feature 才補邊，不能確定就列為待處理；每步已有另一個引用時記錄錯誤供處理，不替換舊邊、不改歷史文字、不因此產生新版本。§9.1：`TUTORIAL_STEP` 的 SK 是 `REFERENCES#<Feature PK>`，同一 item 同時表達步驟與引用。§8.2：套用關係以 `rules_applied` 為準，`applied_to` 與 `APPLIED_TO` 邊由它重建並去重。§9.2：邊的通用格式與 `target`。§14.3：backfill 與每日維護同批執行、保持獨立紀錄、不新增第四條 pipeline。§7.6、§12.2：只有 Analytics 能寫規則驗證後 status。
- 決策 D05（每步恰好一個 Feature）、D17（`rules_applied` 是權威）、F29（原文複製不計本次套用）、F40（只增加缺少的邊）。
- [DynamoDB 分頁](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/Query.Pagination.html)：Scan 與 Query 都要以 `LastEvaluatedKey` 讀到沒有下一頁；[DynamoDB 讀取一致性](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/HowItWorks.ReadConsistency.html)：比對用的基表讀取指定 `ConsistentRead`，不用 GSI 判斷缺邊。

## 11. 完成清單

- [x] `BackfillReport`、`backfill_references`、`rebuild_rule_projection`、`delete_edge` 簽名符合本文件與 00A 第 6.3 節。
- [x] `added`／`conflicts`／`unresolved` 都是排序去重的步驟 PK，重跑結果可直接比對。
- [x] 有測試證明：`backfill_references` 拒絕未發布或不存在的版本；`conflicts` 案例前後的錯邊 item byte 相同；`delete_edge` 擋掉 `REFERENCES`。
- [x] 有測試證明 backfill 只寫 `added` 列出的那幾個 `STEP#` PK、內容逐字取自 S3 全文；版本數、其他步驟文字與 S3 物件全部不變。
- [x] `rebuild_rule_projection` 以 `VERSION.rules_applied` 為唯一權威，補缺邊、刪多餘邊並去重排序；raw item 先濾 `SK != META` 再經 `item_to_model`。
- [x] 重建過程不寫任何 `VERSION` item，也不寫 `RULE.status`；`update_meta` 衝突時讓 `CoordinationError` 往外拋。
- [x] 分頁與空頁案例通過；兩個函式重跑皆冪等。
- [x] 查詢知識圖譜 Rule 7 與套用教學規則 Rule 6 各有直接 assertion，其餘 Rule 標為相關並指向 primary Phase。
- [x] 未把 backfill 描述成 O3 的替代方案或 partial publish 的補救手段。
