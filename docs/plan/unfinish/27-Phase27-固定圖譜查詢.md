# Phase 27：固定圖譜查詢實作計畫

> **給實作者：** 依 checkbox 逐步執行；每個 Task 先建立失敗測試，再寫最小實作。執行時使用 `superpowers:executing-plans` 或同等逐項流程。

**目標：** 把設計 §10 的固定關係查詢寫成 `Repository` 上的五個具名方法（與 Phase 08 的 `list_feedback_of_version` 合為六種固定查詢），並保證「誰引用這個 Feature」只會回傳目前已發布版本的步驟。

**架構：** 六個方法全部建在 [Phase 08](./08-Phase08-分頁查詢與一致讀取基礎.md) 的分頁原語（`query_pk`、`query_by_target`、`scan_entity`、`get_steps`、`item_to_model`）之上，只加業務篩選與排序。GSI 只用來取候選，最終答案一律由基表一致讀取核對；整個模組不接受 `Writer`，因此不可能呼叫模型。

**技術：** Python 3.12、Pydantic v2、pytest、boto3 DynamoDB Query／Scan 分頁、moto。

## 全域限制

- 唯一主來源是 [Training KB 設計 §7.3、§7.4、§9.2、§10](../../design/training-kb.md)。前置為 [Phase 26：教學退役與後繼導向](./26-Phase26-教學退役與後繼導向.md)，未通過時停止；下一階段是 [Phase 28：引用 Backfill 與規則投影重建](./28-Phase28-引用Backfill與規則投影重建.md)。
- 本階段不做：不寫入任何 item 或邊（補邊與投影重建是 [Phase 28](./28-Phase28-引用Backfill與規則投影重建.md)）、不做語意搜尋與 safety net（[Phase 49](./49-Phase49-Release功能定位與Alias.md)、[Phase 50](./50-Phase50-Release步驟反查與Safety-Net.md)）、不決定 CREATE／KEEP（[Phase 40](./40-Phase40-Ticket-CREATE與KEEP.md)）、不新增第二個索引或圖資料庫。
- **正常關係遍歷不呼叫 AI。** 本模組的函式一律不接受 `Writer` 參數；測試要直接斷言 FakeWriter 的呼叫次數為 0。
- 歷史版本與 `published_at=null` 的未發布版本，命中只供追溯，**不得**被當成目前版；`current_version` 與 `published_at` 兩個條件必須同時成立。
- 所有 Query／Scan 都要讀完分頁；**空的一頁不等於沒有下一頁**，有 `LastEvaluatedKey` 就要繼續。
- 對 `scan_entity`／`query_pk` 回來的 raw item，一律先濾掉 `SK != META` 的邊 item，再用 [Phase 08](./08-Phase08-分頁查詢與一致讀取基礎.md) 的 `item_to_model` 轉模型；**不可直接 `Model.model_validate(item)`**。
- O1–O7 gate 狀態：本 Phase 不依賴也不宣稱 O2／O3。GSI 只有最終一致讀取，基表核對只在本案「少量資料＋序列化教學寫入」的範圍內成立，**不宣稱**它是跨併發寫入的快照，也不宣稱適用大型站點。
- 以下程式檔均是實作時預計建立或修改；本計畫本身不代表它們已存在。

---

## 1. 你在整體流程的位置

```text
 Phase 08 分頁原語（只回 raw item）：query_pk / query_by_target /
                    scan_entity / get_steps / item_to_model
                              |
                              v
   +--------------------------------------------------------+
   |  [你在這裡] Phase 27：六種固定查詢（只讀、零 AI）       |
   +--------------------------------------------------------+
     |            |               |             |            |
     v            v               v             v            v
  Feature      版本清單       active 教學   current 已發布   規則套用
  name/alias  （含未發布）    （KEEP 判定）   引用步驟        版本清單
     |            |               |             |            |
     v            v               v             v            v
  Phase 49     Phase 24        Phase 40    Phase 50 -> 51   Phase 28
  Feature 定位 索引頁篩已發布  KEEP 判定   反查改版         投影重建核對
```

## 2. 完成後看得到什麼

以下是單元測試 fixture（不是 [Phase 56](./56-Phase56-O7核定Demo種子資料.md) 的 Demo 種子配方）：`FEATURE#Prepare` 被三個步驟引用，分別是 `prepare-meeting@v1 #3`（歷史版）、`prepare-meeting@v2 #3`（current 已發布版）、`share-summary@v2 #1`（尚未發布的草稿版）。

```text
find_current_published_steps_referencing("Prepare")
  -> [TutorialStep(tutorial_version="prepare-meeting@v2", number=3, ...)]

list_versions_of_tutorial("prepare-meeting")
  -> [v1, v2, v10]   # 依版號升序，含未發布版；v10 排在 v2 之後，不是字典序

find_feature_by_name_or_alias("Meeting Summary")
  -> Feature(feature_id="Prepare", name="Prepare", aliases=["Meeting Summary"], ...)

list_versions_applying_rule("R-007")
  -> ["prepare-meeting@v2", "prepare-meeting@v3"]   # 邊存在但 rules_applied 沒有的一律不算
```

即使 `by_target` GSI 還沒把 `prepare-meeting@v2 #3` 的邊傳播出來，第一個查詢仍要回傳它；這就是基表核對存在的理由。

## 3. 名詞小抄

| 名詞 | 白話意思 |
|---|---|
| 關係邊 | 一個獨立的 item：`PK=起點`、`SK=關係#終點`、`target=終點`。 |
| `by_target` GSI | 唯一的反向索引，用來問「有誰指向我」。 |
| 最終一致 | GSI 可能還沒看到剛寫進基表的資料，讀起來會少一筆。 |
| 一致讀取 | 對基表指定 `ConsistentRead=True`，保證讀到最新已提交的值。 |
| 目前已發布版 | 同時滿足「等於該篇 `current_version`」與「`published_at` 非空」。 |
| 分頁 | 一次查不完就給你 `LastEvaluatedKey`，要一直帶著它問到沒有為止。 |
| STEP item | 步驟本身就是那筆 `REFERENCES` 邊（設計 §9.1），沒有另一筆 `SK=META` 的步驟 item。 |
| `item_to_model` | Phase 08 的轉換函式：先去掉 `PK`／`SK`／`target`／`entity`／`_revision` 再交模型驗證。 |
| `D07`／`F12` 這類編號 | 設計文件 §19 已解決的決策編號；`D` 開頭是資料決策，`F` 開頭是功能決策。 |

## 4. 預計檔案

| 動作 | 路徑 | 責任 |
|---|---|---|
| 修改 | `src/training_kb/repository.py` | 六個固定查詢方法與 `version_sort_key`。 |
| 測試 | `tests/unit/test_graph_queries.py` | 篩選、排序、alias 撞名、零 AI 呼叫。 |
| 測試 | `tests/integration/test_current_published_steps.py` | GSI 落後、歷史版、未發布版與空分頁（moto）。 |

## 5. 固定介面

### Consumes

```text
Repository.query_pk(pk, *, sk_prefix=None, consistent=True) -> list[DynamoItem]   # Phase 08
Repository.query_by_target(target_pk) -> list[DynamoItem]                         # Phase 08，GSI、KEYS_ONLY、最終一致
Repository.scan_entity(entity, *, consistent=True, meta_only=True) -> list[DynamoItem]  # Phase 08
Repository.get_steps(version_id) -> list[TutorialStep]                            # Phase 08
Repository.list_feedback_of_version / list_views_of_version                       # Phase 08
item_to_model(item: DynamoItem, model: type[T]) -> T                              # Phase 08，模組函式
Repository.get_version / get_tutorial / get_feature                               # Phase 06
Tutorial / TutorialVersion / TutorialStep / Feature                               # Phase 04
META / feature_pk / rule_pk / step_pk / parse_pk / parse_edge_sk                   # Phase 05
PermanentError                                                                    # Phase 02
```

### Produces

```python
def version_sort_key(version_id: str) -> tuple[str, int]: ...
def find_feature_by_name_or_alias(self, name: str) -> Feature | None: ...
def list_versions_of_tutorial(self, slug: str) -> list[TutorialVersion]: ...
def find_active_tutorial_for_feature(self, feature_id: str) -> Tutorial | None: ...
def find_current_published_steps_referencing(self, feature_id: str) -> list[TutorialStep]: ...
def list_versions_applying_rule(self, rule_id: str) -> list[str]: ...
```

五個方法加在既有 `Repository` 類別上，`version_sort_key` 是同一模組的函式（不是方法）。這五個方法與 Phase 08 的 `list_feedback_of_version` 合起來，就是 00A 第 6.3 節說的「六種固定圖譜查詢」；設計 §10 另外兩問「起點有哪些關係」與「某版有哪些瀏覽者」由 Phase 08 的 `query_pk` 與 `list_views_of_version` 直接提供，本 Phase 不重新定義。

| 對應的設計問題 | 固定查法 | 方法 |
|---|---|---|
| §10 誰引用 Feature？ | `by_target` 候選 ∪ 基表核對，只留 current 已發布 | `find_current_published_steps_referencing` |
| §10 某篇教學有哪些版本？ | 基表分頁 Scan，依 VERSION PK 解析的 slug 篩選 | `list_versions_of_tutorial` |
| §10 規則套用哪些版本？ | RULE 起點的 `APPLIED_TO` 邊，再以 `rules_applied` 核對 | `list_versions_applying_rule` |
| §10 某版有哪些回饋？ | `by_target`，保留 `FEEDBACK`／`REFERS_TO` | `list_feedback_of_version`（Phase 08） |
| §7.4 功能叫什麼名字？ | 基表 Scan FEATURE，name 優先於 alias | `find_feature_by_name_or_alias` |
| §7.3 這個功能有 active 教學嗎？ | 基表 Scan TUTORIAL，`status=active` | `find_active_tutorial_for_feature` |

## 6. 設計細節

`find_current_published_steps_referencing` 是本 Phase 唯一有兩條資料來源的查詢：

```text
B. 基表核對（強一致，決定結果集合） scan_entity("TUTORIAL", consistent=True)
        +-- 只取 SK == META 的 item；current_version 為 None 就跳過
        +-- get_version(current).published_at 為 None 就跳過
        +-- get_steps(current) 一致讀，篩 step.feature_id == feature_id

A. GSI 候選（可能少，不會多） query_by_target(FEATURE#Prepare)
        +-- 只留 relation == REFERENCES 且起點是 STEP#（排除 TICKET 的 ASKS_ABOUT）
        +-- 由 STEP PK 解析出 version_id 與 number
        +-- 不是 current 已發布就跳過；是 current 已發布卻在基表讀不到 -> PermanentError

結果 = (A ∪ B) -> 依 (version_sort_key(version_id), number) 升序
```

為什麼要聯集：GSI 只有最終一致讀取，剛寫入的邊可能還沒出現，只用 A 會錯判「沒有教學引用這個功能」而誤 KEEP（設計 §10）；B 用強一致讀取保證目前已發布版的引用集合完整。設計 §9.1 把步驟與引用放在同一筆 item（`PK=STEP#…`、`SK=REFERENCES#FEATURE#…`），所以資料正常時 A 必然是 B 的子集合，聯集不會多出東西。**A 多出 B 沒有的一筆，代表基表資料不完整**（例如邊少了 `entity` 屬性而被 `scan_entity` 漏掉）：依 Phase 08 的規則丟 `PermanentError`，不靜默跳過，也不在查詢裡順手補寫——補寫是 [Phase 28](./28-Phase28-引用Backfill與規則投影重建.md) 的事。B 從 TUTORIAL 出發是因為設計 §10 要求「改版前以基表一致讀取核對目前版的完整引用集合」，而目前版由 `TUTORIAL.current_version` 決定；代價是每個目前已發布版各呼叫一次 `get_steps`。**這是本案少量資料的取捨，不是大型站點的查詢設計。**

`scan_entity(entity)` 靠 item 的 `entity` 屬性篩選，而 `entity` 等於 PK 前綴，所以 `scan_entity("VERSION")` 的掃描範圍同時涵蓋 `VERSION#…` 的 metadata item 與它的 `SUPERSEDES` 邊；[Phase 08](./08-Phase08-分頁查詢與一致讀取基礎.md) 的預設 `meta_only=True` 已經先幫我們濾掉邊，本 Phase 仍自己再濾一次，這樣呼叫端改傳 `meta_only=False` 時也不會把邊當成版本。**要把 raw item 轉成模型時，一律先濾掉 `SK != META` 的邊，再用 `item_to_model`**（D29）；直接 `Model.model_validate(item)` 會因為 `PK`／`SK`／`entity`／`_revision` 被 strict 模型拒絕。

`list_versions_applying_rule` 以 `VERSION.rules_applied` 為唯一權威（D17）：邊存在但該版的 `rules_applied` 不含這條規則時**不回傳**，因為多餘邊會讓「規則套用次數」指標多計。查詢只讀不寫，重建交給 Phase 28。`list_versions_of_tutorial` 則回傳**全部**版本（含歷史與未發布），由呼叫端自行篩 `published_at`，索引頁只列已發布是 [Phase 24](./24-Phase24-單篇教學發布提交.md) 的責任。兩者都用 `version_sort_key(version_id) -> (slug, number)` 排序，避免字典序把 `@v10` 排在 `@v2` 前面。它和 [Phase 20](./20-Phase20-版本分配與重試重用.md) 的 `parse_version_id` 回傳同一種東西，但**不能**直接 import：相依方向是 `content` 呼叫 `repository`（設計 §5），反向 import 會造成循環，所以 `repository.py` 自帶這份最小解析，格式不合丟 `PermanentError`。

`find_feature_by_name_or_alias` 先比 `name` 再比 `aliases`（設計 §7.4）；alias 必須唯一（D07），同一字串命中兩個 Feature 的 alias 時丟 `PermanentError`，不自行挑一個，找不到就回 `None`，**不做語意搜尋、不建立 Feature**。掃描結果先依 `feature_id` 升序排好再比對，讓同名時的回傳是可重現的。`find_active_tutorial_for_feature` 只看 `status == "active"`：即使 `current_version` 還是 `None`（尚待首次發布）也算已有教學（F12），`retired` 則不算，因此不會阻擋 CREATE；真的出現多篇時回 slug 升序第一筆，讓結果可重現。

## 7. TDD Tasks

### Task 1：Feature 定位與版本清單

- [ ] **Step 1：建立失敗測試**

`repo` 是本測試檔自備的假 `Repository` fixture：底層用一個 dict 當表，`add_feature`／`add_edge`／`set_rules_applied`／`set_current_version`／`set_status` 寫資料，`paginate(*pages)` 指定 Scan 切成哪幾頁（允許空頁），`gsi_hide(pk)` 讓某筆邊暫時不出現在 `query_by_target`（模擬 GSI 落後）。它只覆寫 Phase 08 的四個原語，被測的六個查詢都是真的程式。

```python
import pytest

from training_kb.errors import PermanentError
from training_kb.repository import version_sort_key


def test_find_feature_prefers_name_over_alias_and_rejects_duplicate_alias(repo):
    assert repo.find_feature_by_name_or_alias("Prepare").feature_id == "Prepare"
    assert repo.find_feature_by_name_or_alias("Meeting Summary").feature_id == "Prepare"
    assert repo.find_feature_by_name_or_alias("Nope") is None
    repo.add_feature(feature_id="Notify", name="Notify", aliases=["Meeting Summary"])
    with pytest.raises(PermanentError, match="Meeting Summary"):
        repo.find_feature_by_name_or_alias("Meeting Summary")


def test_list_versions_of_tutorial_sorts_by_number_and_reads_every_page(repo):
    repo.paginate(["prepare-meeting@v1", "prepare-meeting@v2"], [], ["prepare-meeting@v10"])
    ids = [version.version_id for version in repo.list_versions_of_tutorial("prepare-meeting")]
    assert ids == ["prepare-meeting@v1", "prepare-meeting@v2", "prepare-meeting@v10"]
    assert version_sort_key("prepare-meeting@v10") == ("prepare-meeting", 10)
    with pytest.raises(PermanentError, match="prepare-meeting"):
        version_sort_key("prepare-meeting")
```

- [ ] **Step 2：執行並確認紅燈**

```bash
uv run pytest tests/unit/test_graph_queries.py -q
```

預期：FAIL，訊號包含 `cannot import name 'version_sort_key'`。

- [ ] **Step 3：建立最小實作**

三個 Task 都寫在 `src/training_kb/repository.py`，需要的 import（`PermanentError`、`META`、`feature_pk`／`rule_pk`／`parse_pk`／`parse_edge_sk`、Phase 04 的四個模型、`item_to_model`）加一次就好。

```python
def version_sort_key(version_id: str) -> tuple[str, int]:
    slug, marker, suffix = version_id.partition("@v")
    if not slug or not marker or not suffix.isdigit():
        raise PermanentError(f"不是合法的 version_id：{version_id}")
    return slug, int(suffix)


def _meta_models(self, entity, model):
    rows = [item for item in self.scan_entity(entity) if str(item["SK"]) == META]
    return [item_to_model(item, model) for item in rows]


def find_feature_by_name_or_alias(self, name):
    features = sorted(self._meta_models("FEATURE", Feature), key=lambda f: f.feature_id)
    exact = [feature for feature in features if feature.name == name]
    hits = exact or [feature for feature in features if name in feature.aliases]
    if not exact and len(hits) > 1:
        raise PermanentError(f"alias {name} 同時屬於 {len(hits)} 個 Feature")
    return hits[0] if hits else None


def list_versions_of_tutorial(self, slug):
    versions = self._meta_models("VERSION", TutorialVersion)
    chosen = [version for version in versions if version.slug == slug]
    return sorted(chosen, key=lambda version: version_sort_key(version.version_id))
```

- [ ] **Step 4：補上空分頁案例並跑完整檔案確認綠燈**

`repo.paginate(...)` 的第二頁刻意為空但仍帶 `LastEvaluatedKey`；斷言結果包含第三頁的 `v10`，證明沒有提早停止。`_meta_models` 的 `SK == META` 過濾也要有案例：在同一張表放一筆 `VERSION#prepare-meeting@v2` 的 `SUPERSEDES` 邊，斷言它不會被當成版本。

```bash
uv run pytest tests/unit/test_graph_queries.py -q
```

- [ ] **Step 5：提交**

```bash
git add src/training_kb/repository.py tests/unit/test_graph_queries.py
git commit -m "feat(repository): 固定 Feature 與版本查詢"
```

### Task 2：只回傳目前已發布版本的引用步驟

- [ ] **Step 1：建立失敗測試**

```python
def test_referencing_steps_exclude_history_and_unpublished(repo):
    steps = repo.find_current_published_steps_referencing("Prepare")
    assert [(step.tutorial_version, step.number) for step in steps] == [("prepare-meeting@v2", 3)]


def test_referencing_steps_survive_stale_gsi(repo):
    repo.gsi_hide("STEP#prepare-meeting@v2#3")
    steps = repo.find_current_published_steps_referencing("Prepare")
    assert [(step.tutorial_version, step.number) for step in steps] == [("prepare-meeting@v2", 3)]


def test_referencing_steps_ignore_other_relations(repo):
    repo.add_edge("TICKET#t_881", "ASKS_ABOUT", "FEATURE#Prepare")
    assert all(step.tutorial_version.startswith("prepare-meeting") for step in
               repo.find_current_published_steps_referencing("Prepare"))
```

- [ ] **Step 2：執行並確認紅燈**

```bash
uv run pytest tests/unit/test_graph_queries.py -q -k referencing
```

預期：FAIL，訊號包含 `'Repository' object has no attribute 'find_current_published_steps_referencing'`。

- [ ] **Step 3：建立最小實作**

```python
def _is_current_published(self, version_id):
    slug, _ = version_sort_key(version_id)
    tutorial = self.get_tutorial(slug)
    if tutorial is None or tutorial.current_version != version_id:
        return False
    version = self.get_version(version_id)
    return version is not None and version.published_at is not None


def find_current_published_steps_referencing(self, feature_id):
    target = feature_pk(feature_id)
    found: dict[tuple[str, int], TutorialStep] = {}
    for item in self.scan_entity("TUTORIAL"):          # B：基表一致讀取
        if str(item["SK"]) != META:
            continue
        current = item_to_model(item, Tutorial).current_version
        if current is None or not self._is_current_published(current):
            continue
        for step in self.get_steps(current):
            if step.feature_id == feature_id:
                found[(current, step.number)] = step
    for edge in self.query_by_target(target):          # A：GSI 候選
        relation, endpoint = parse_edge_sk(str(edge["SK"]))
        kind, body = parse_pk(str(edge["PK"]))
        if relation != "REFERENCES" or kind != "STEP" or endpoint != target:
            continue
        version_id, _, number = body.rpartition("#")
        if (version_id, int(number)) in found or not self._is_current_published(version_id):
            continue
        raise PermanentError(f"GSI 候選在基表讀不到對應步驟：{edge['PK']}")
    return [found[key] for key in sorted(found, key=lambda k: (version_sort_key(k[0]), k[1]))]
```

B 已經用一致讀取列出每個目前已發布版的全部步驟，所以走到最後一行 `raise` 就代表這筆候選的 STEP item 在基表缺失或缺 `entity` 屬性。

- [ ] **Step 4：補上 GSI 多回一筆歷史版的案例並跑綠燈**

GSI 回傳 `prepare-meeting@v1 #3` 與 `share-summary@v2 #1`（未發布）時，兩者都必須被 `_is_current_published` 濾掉。再加一個「GSI 有、基表沒有」的案例：塞一筆 current 已發布版的 `REFERENCES` 邊到假 GSI 但不寫基表，斷言丟 `PermanentError`。

```bash
uv run pytest tests/unit/test_graph_queries.py -q
uv run pytest tests/integration/test_current_published_steps.py -q
```

- [ ] **Step 5：提交**

```bash
git add src/training_kb/repository.py tests/unit tests/integration
git commit -m "feat(repository): 反查目前已發布版本的引用步驟"
```

### Task 3：規則套用版本、active 教學與零 AI

- [ ] **Step 1：建立失敗測試**

```python
def test_rule_versions_follow_rules_applied_only(repo):
    repo.add_edge("RULE#R-007", "APPLIED_TO", "VERSION#share-summary@v1")
    repo.set_rules_applied("share-summary@v1", [])
    assert repo.list_versions_applying_rule("R-007") == ["prepare-meeting@v2"]


def test_active_tutorial_found_even_before_first_publish(repo):
    repo.set_current_version("share-summary", None)
    assert repo.find_active_tutorial_for_feature("Share").slug == "share-summary"
    repo.set_status("share-summary", "retired")
    assert repo.find_active_tutorial_for_feature("Share") is None


def test_graph_queries_never_call_the_model(repo, fake_writer):
    repo.find_current_published_steps_referencing("Prepare")
    repo.list_versions_applying_rule("R-007")
    repo.find_feature_by_name_or_alias("Prepare")
    assert fake_writer.calls == []
```

- [ ] **Step 2：執行並確認紅燈**

```bash
uv run pytest tests/unit/test_graph_queries.py -q -k "rule_versions or active_tutorial or never_call"
```

預期：FAIL，訊號包含 `'Repository' object has no attribute 'list_versions_applying_rule'`。

- [ ] **Step 3：建立最小實作**

```python
def list_versions_applying_rule(self, rule_id):
    version_ids: set[str] = set()
    for edge in self.query_pk(rule_pk(rule_id), sk_prefix="APPLIED_TO#"):
        _, endpoint = parse_edge_sk(str(edge["SK"]))
        _, version_id = parse_pk(endpoint)
        version = self.get_version(version_id)
        if version is not None and rule_id in version.rules_applied:
            version_ids.add(version_id)
    return sorted(version_ids, key=version_sort_key)


def find_active_tutorial_for_feature(self, feature_id):
    hits = self._meta_models("TUTORIAL", Tutorial)
    active = [t for t in hits if t.status == "active" and feature_id in t.feature_ids]
    return min(active, key=lambda tutorial: tutorial.slug) if active else None
```

- [ ] **Step 4：跑完整檔案確認綠燈**

```bash
uv run pytest tests/unit/test_graph_queries.py -q
```

- [ ] **Step 5：提交**

```bash
git add src/training_kb/repository.py tests/unit/test_graph_queries.py
git commit -m "feat(repository): 規則套用版本與 active 教學查詢"
```

## 8. 驗收矩陣

| 路徑 | 輸入 | 預期資料結果 |
|---|---|---|
| Happy | Prepare 被 A v2 #3 引用 | 只回 `("prepare-meeting@v2", 3)`。 |
| Happy | R-007 的兩個 `APPLIED_TO` 邊皆有 `rules_applied` | 回兩個 version_id，依版號排序且去重。 |
| Failure | 同一 alias 屬於兩個 Feature | `PermanentError`；不自行挑一個。 |
| Failure | GSI 候選是 current 已發布版，基表卻讀不到該步驟 | `PermanentError`；不靜默跳過、不在查詢裡補邊。 |
| Failure | `version_sort_key("prepare-meeting")` | `PermanentError`；不回傳猜測的版號。 |
| Boundary | GSI 尚未傳播該邊 | 基表核對仍回傳該步驟。 |
| Boundary | 命中的是歷史版、未發布版或 `ASKS_ABOUT` 邊 | 一律排除，不觸發改版。 |
| Boundary | `scan_entity("VERSION")` 同時掃到 `SUPERSEDES` 邊；第二頁為空但仍有 `LastEvaluatedKey` | 邊被 `SK != META` 濾掉；讀到第三頁，結果完整。 |
| Boundary | active 教學尚未首次發布／已 retired | 前者仍回傳（F12），後者回 `None`，不阻擋 CREATE。 |
| Privacy | 全部查詢執行一輪 | FakeWriter 呼叫次數為 0。 |

人工驗收：在真實表上先寫一筆新的 `REFERENCES` 邊，立刻查一次 `find_current_published_steps_referencing`，確認不必等待固定秒數就能拿到完整結果；同時把 `query_by_target` 當下的回傳存證，證明 GSI 真的落後過。不能只看測試顯示 PASS。

## 9. 常見錯誤與停止條件

| 症狀 | 原因 | 修正／停止 |
|---|---|---|
| 命中歷史版就產生新版 | 只比 `feature_id`，沒比 `current_version` | 停止改版路徑；兩個條件都要檢查。 |
| 未發布版被當成目前版 | 只看 `current_version` 沒看 `published_at` | 兩者同時成立才算；`published_at=null` 一律排除。 |
| GSI 空就判定沒有教學引用 | 把最終一致當成完整 | 停止 KEEP 判定；補上基表一致讀取核對。 |
| 用 PK 前綴 Query 列版本 | 以為 `VERSION#<slug>@v` 可以當 Query 條件 | 改用基表分頁 Scan；PK 前綴不是合法的 Query 鍵。 |
| 空的一頁就結束／`@v10` 排在 `@v2` 前面 | 以為沒資料代表查完；用字典序 | 有 `LastEvaluatedKey` 就繼續；改用 `version_sort_key`。 |
| `ValidationError: extra fields not permitted`／`SUPERSEDES` 邊被當成版本 | 對 raw item 直接 `Model.model_validate`；`scan_entity` 依 `entity` 篩選而 `entity` 等於 PK 前綴 | 先濾掉 `SK != META` 再用 `item_to_model`（D29）。 |
| 查詢裡順手補邊或改 `applied_to` | 把查詢和修復混在一起 | 停止：本 Phase 只讀；補寫是 Phase 28。 |
| 查詢時呼叫模型 | 把 alias 未命中當成要語意搜尋 | 停止：本模組不接受 `Writer`；語意搜尋在 Phase 49／50。 |

## 10. 來源與 Rule 對照

- [查詢知識圖譜.feature](../../spec/features/查詢知識圖譜.feature)
  - Rule 3：「沿 Feature 關係邊反查不呼叫 AI」→ **primary**；Task 3 `test_graph_queries_never_call_the_model` 直接斷言呼叫次數為 0。
  - Rule 4：「可查詢某篇 Tutorial 所屬的版本」→ **primary**；Task 1 `test_list_versions_of_tutorial_sorts_by_number_and_reads_every_page`。
  - Rule 5：「可查詢某條 Authoring Rule 套用的版本」→ **primary**；Task 3 `test_rule_versions_follow_rules_applied_only`。
  - Rule 1：「查詢某起點的關係使用該起點的 PK」、Rule 2：「查詢誰引用 Feature 時使用 by_target 的 target」、Rule 6：「Feedback Review 以 refers_to 關係反查指定版本的回饋」→ 三條都是**相關（primary 在 [Phase 08](./08-Phase08-分頁查詢與一致讀取基礎.md)）**：固定查法由 Phase 08 負責，本 Phase 的 Task 2、Task 3 只在它們之上加業務篩選並保留斷言。
  - Rule 7：「定期 backfill 漏抽的 Feature 引用邊」**不在本階段**，由 [Phase 28](./28-Phase28-引用Backfill與規則投影重建.md) 負責。
- [依改版更新教學.feature](../../spec/features/依改版更新教學.feature) Rule 5：「by_target 反查只選出引用改版 Feature 的步驟」→ **相關（primary 在 [Phase 50](./50-Phase50-Release步驟反查與Safety-Net.md)）**，Rule 2、3 同樣相關（primary 在 [Phase 49](./49-Phase49-Release功能定位與Alias.md)）；Task 2 斷言歷史版與未發布版不觸發改寫（F17），Task 1 斷言 alias 與 Feature PK 的對應（D06、D07）。
- [套用教學規則.feature](../../spec/features/套用教學規則.feature) Rule 6：「套用規則的版本記錄於規則的 applied_to」→ **相關（primary 在 [Phase 28](./28-Phase28-引用Backfill與規則投影重建.md)）**；本 Phase 以 `rules_applied` 核對後才回傳（D17、F29）。
- 設計 §10：固定查詢清單、分頁必須讀完、GSI 最終一致需基表核對、正常遍歷不呼叫 AI。§7.3：active 即使未發布仍算已有教學。§7.4：先比 name／alias。§9.1：STEP 與 `REFERENCES` 是同一筆 item。§9.2：邊的格式與 `ASKS_ABOUT` 等其他關係必須被篩掉。
- [DynamoDB 分頁](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/Query.Pagination.html)：以 `LastEvaluatedKey` 接續直到沒有下一頁；[DynamoDB 讀取一致性](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/HowItWorks.ReadConsistency.html)：基表可一致讀取，GSI 只有最終一致。

## 11. 完成清單

- [ ] 六個查詢的名稱與簽名符合本文件與 00A 第 6.3 節。
- [ ] `find_current_published_steps_referencing` 同時使用 GSI 候選與基表一致讀取核對，且「GSI 有、基表沒有」會丟 `PermanentError`。
- [ ] 歷史版、未發布版與 `ASKS_ABOUT` 等其他關係全部被排除。
- [ ] 每個 Query／Scan 都讀完分頁，空頁不早停，且有測試證明。
- [ ] raw item 一律先濾 `SK != META` 再經 `item_to_model`，沒有任何 `Model.model_validate(item)`。
- [ ] `list_versions_applying_rule` 以 `VERSION.rules_applied` 為唯一權威並去重；排序用 `version_sort_key`，`@v10` 在 `@v2` 之後，格式不合丟 `PermanentError`。
- [ ] 查詢知識圖譜 Rule 3、4、5 各有直接 assertion（Rule 3 以呼叫次數 0 證明），Rule 1、2、6 標為相關並指向 Phase 08。
- [ ] 本 Phase 沒有任何寫入；未把基表核對描述成跨併發寫入的快照或大型站點方案。
