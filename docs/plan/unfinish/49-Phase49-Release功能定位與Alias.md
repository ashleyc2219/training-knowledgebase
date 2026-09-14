# Phase 49：Release 功能定位與 Alias 實作計畫

> **給實作者：** 依 checkbox 逐步執行；每個 Task 先建立失敗測試，再寫最小實作。執行時使用 `superpowers:executing-plans` 或同等逐項流程。

**目標：** 讓一則已正規化的 Release 先用名稱與 alias、再用語意相似度定位到唯一一個既有 Feature，並在改版完成後安全更新該 Feature 的顯示名稱與 aliases。

**架構：** 這是 `release-update` pipeline 的第一段。程式先做完全相同字串查詢，再做忽略大小寫與前後空白的正規化比對，全部落空才呼叫 Titan 算向量；是否採用由程式的 `0.85` 門檻決定，不由模型決定。Feature 的 PK 在第一次建立時就固定，本 Phase 只改 `name` 與 `aliases` 兩個欄位。

**技術：** Python 3.12、Pydantic v2、pytest、Phase 16 的 `Writer.embed` 與 `cosine`、Phase 27 的固定查詢、Phase 06 的條件更新。

## 全域限制

- 唯一主來源是 [Training KB 設計 §7.4、§9.1、§10、§16 S5、§19.1 D06／D07](../../design/training-kb.md)。
- 前置為 [Phase 48：Feedback Review 排程流程](./48-Phase48-Feedback-Review排程流程.md)；另需 [Phase 16 向量計算](./16-Phase16-Titan-Embedding與向量計算.md)、[Phase 27 固定圖譜查詢](./27-Phase27-固定圖譜查詢.md) 與 [Phase 31 Release 正規化](./31-Phase31-Ticket與Release正規化.md) 已完成。任一前置未通過時停止。
- 下一階段是 [Phase 50：Release 步驟反查與 Safety Net](./50-Phase50-Release步驟反查與Safety-Net.md)。
- 本階段不做：不反查步驟、不建立新 Feature、不建立版本、不發布、不退役、不呼叫 Claude。
- 定位失敗是合法業務結果（回 `None`），代表「不改版、不建立 Feature」，不是技術故障。
- O1–O7 狀態：O5 未通過時語意分支保持 blocked，只能跑前兩層與純函式測試；O6 未通過時 `old_name`／`new_name` 不可信，整條 release-update 停止。本 Phase 不得宣稱 O5 或 O6 已核定。
- 以下程式檔均是實作時預計建立或修改；本計畫本身不代表它們已存在。

---

## 1. 你在整體流程的位置

```text
Phase 31 validate_release -> Phase 32 接受並啟動 -> release-update pipeline
                                                            |
                                                            v
                        [你在這裡：locate_feature / update_feature_aliases]
                             |                                    |
        找到唯一 Feature -----+                                    +----- 回傳 None
                             |                                                |
                             v                                                v
        Phase 50 步驟反查與 safety_net                            不改版、不建立 Feature
                             |                                       記 KEEP 原因
                             v
     Phase 51 建版 -> Phase 52 發布成功後，才回來呼叫 update_feature_aliases
```

`locate_feature` 只回答「是哪一個既有 Feature」；`update_feature_aliases` 是發布完成後的收尾動作，兩者不在同一個節點。

## 2. 完成後看得到什麼

圖譜裡的 Feature 是 `FEATURE#Prepare`，改版前的欄位是 `name="Meeting Summary"`、`aliases=[]`（PK 後綴 `Prepare` 是建立當時就固定的值，與當時的顯示名稱不一定相同）。輸入 Release `r_42`（`kind="renamed"`、`old_name="Meeting Summary"`、`new_name="Prepare"`）時，`locate_feature` 在第一層就用 `old_name` 字串命中 `name` 並回傳該 Feature，**零次 Bedrock 呼叫**。

Phase 51 建出 `prepare-meeting@v3`、Phase 52 發布成功之後呼叫 `update_feature_aliases(feature, old_name="Meeting Summary", new_name="Prepare", repository=repo)`，結果為：

```text
PK      = FEATURE#Prepare      （與改名前完全相同）
name    = "Prepare"
aliases = ["Meeting Summary"]
```

改完之後，同一則 Release 再跑一次仍然只會找到同一個節點：這次是 `old_name` 命中 `aliases`、`new_name` 命中 `name`。「改名前後的名稱指向同一個 Feature」這件事，就是靠這一組資料成立的。

若另一個 Feature 已把 `Prepare` 當成自己的 alias，這次更新必須整個拒絕並丟 `PermanentError`，不可只改一半，也不可降級成 KEEP。

## 3. 名詞小抄

| 名詞 | 白話意思 |
|---|---|
| Feature PK | DynamoDB 主鍵 `FEATURE#<建立時名稱>`；改名永遠不搬移它。 |
| alias | 這個功能的舊名或別名清單；在整個查詢範圍內必須唯一。 |
| 正規化名稱 | 去掉前後空白再轉小寫後的字串，只用來比對，不用來顯示或存檔。 |
| 語意定位 | 前兩層都沒命中時，用 Titan 向量比相似度找最接近的 Feature。 |
| cosine 門檻 | 固定 `0.85`；`0.8499` 不算命中。這是程式的判斷，不是模型的判斷。 |
| alias 撞名 | 名稱與別的 Feature 的 name／alias 重複；依 D07 拒絕該次更新。 |
| `revision_of` | Phase 06 提供的「讀出這筆 metadata 目前樂觀鎖版本號」方法；`update_meta` 的 `expected_revision` 只能從它取值。 |
| D06／D07／F15、S5 | 設計文件裡的編號：`D` 開頭是 [§19.1 資料決策](../../design/training-kb.md)、`F` 開頭是 §19.2 功能決策、`S5` 是 §16 第五個交付切片（Release 改版）。 |

## 4. 預計檔案

| 動作 | 路徑 | 責任 |
|---|---|---|
| 建立 | `src/training_kb/pipelines/release.py` | `FEATURE_MATCH_THRESHOLD`、`normalize_feature_name`、`locate_feature`、`update_feature_aliases`。 |
| 測試 | `tests/unit/test_release_locate_feature.py` | 三層定位順序、門檻與平手排序。 |
| 測試 | `tests/unit/test_release_alias_update.py` | PK 不變、old_name 入 aliases、撞名拒絕。 |
| 測試 | `tests/integration/test_release_feature_lookup.py` | 真實 Repository 的一致讀取與條件更新。 |

## 5. 固定介面

### Consumes

```text
Release(id, source_event_id, source, feature, kind, old_name, new_name, evidence, ts)   # Phase 04
Feature(feature_id, name, aliases, first_seen)                                          # Phase 04
META: str / feature_pk(feature_id: str) -> str                                          # Phase 05
Repository.put_meta(entity, *, create_only=True) -> None                                # Phase 06，只給測試 setup 用
Repository.get_feature(feature_id: str) -> Feature | None                               # Phase 06
Repository.update_meta(pk, changes, *, expected_revision: int) -> int                   # Phase 06
Repository.revision_of(pk: str) -> int                                                  # Phase 06
Repository.scan_entity(entity, *, consistent=True, meta_only=True) -> list[DynamoItem]  # Phase 08
item_to_model(item: DynamoItem, model: type[T]) -> T                                    # Phase 08，模組函式
Repository.find_feature_by_name_or_alias(name: str) -> Feature | None                   # Phase 27
Writer.embed(text: str, *, operation_id: str, node: str) -> list[float]              # Phase 15/16
cosine(left: list[float], right: list[float]) -> float                                  # Phase 16
Thresholds.cosine_match: float = 0.85                                                   # Phase 02
PermanentError / CoordinationError                                                      # Phase 02
```

### Produces

```python
FEATURE_MATCH_THRESHOLD: float = Thresholds().cosine_match

def normalize_feature_name(value: str) -> str: ...

def locate_feature(
    release: Release, *, repository: Repository, writer: Writer, operation_id: str
) -> Feature | None: ...

def update_feature_aliases(
    feature: Feature, *, old_name: str, new_name: str, repository: Repository
) -> Feature: ...
```

`FEATURE_MATCH_THRESHOLD` 只是 Phase 02 `Thresholds.cosine_match` 的**別名**，本檔不得再寫一次 `0.85`；全套只有 `Thresholds` 一份數字（Phase 38 的 `CLUSTER_COSINE_THRESHOLD` 也指向同一欄位）。

`locate_feature` 回 `None` 代表「沒有合格 Feature」，呼叫端必須以 KEEP 結束。`update_feature_aliases` 只在 Phase 52 的 `UpdateAliases` Task 呼叫，它排在 `PublishBatch` 之後（設計 §7.4：寫下一版、diff、reason，**完成後**更新 aliases）。

## 6. 設計細節

定位固定三層，前一層命中就不進下一層。目的是「能不呼叫模型就不呼叫」（設計 §10）：

```text
_lookup_keys(release) = 去重後的 (old_name, feature, new_name)
        |
        v
第 1 層｜完全相同字串：find_feature_by_name_or_alias(key)
        | 未命中
        v
第 2 層｜正規化比對：strip + casefold 後比對全表 name/aliases
        |   同一個正規化名稱對到兩個 Feature -> PermanentError（D07 已被破壞）
        | 未命中
        v
第 3 層｜語意定位：embed(keys) 與 embed(name + aliases) 取 cosine
        |   最高分 >= 0.85 -> 採用；同分取 feature_id 升序最小
        | < 0.85
        v
      None：不改版、不建立 Feature
```

`old_name` 排最前面，因為圖譜保存的是改版**之前**的名稱；`new_name` 排最後，只在 Feature 已先以新名稱建立時才派上用場。`removed` 與 `changed` 沒有這兩個欄位（Phase 31 只對 `renamed` 強制它們非空），鍵只剩 `feature` 一個。第 1 層直接把 `PermanentError` 往上拋：`find_feature_by_name_or_alias` 在同一個字串命中兩個 Feature 的 alias 時就是這樣結束的（D07），本 Phase 不吞掉、也不改判成 `None`。

alias 更新是一次全有或全無的檢查：先組出目標 `aliases = (舊 aliases + old_name) - new_name`，逐一比對其他 Feature 的 name 與 aliases，**全部通過才**呼叫 `update_meta`。把 `new_name` 從 aliases 移除是**本計畫選擇**，它讓唯一性檢查不必對自己開例外；移除時用 `normalize_feature_name` 比對，所以 `prepare` 這種只差大小寫的舊別名也會一併移掉，不會留下「自己的別名等於自己的名字」。`update_feature_aliases` 只在 `kind == "renamed"` 的流程末端呼叫（`changed`／`removed` 沒有兩個名稱可搬），所以 `old_name` 與 `new_name` 任一為空就是呼叫端接錯線，直接丟 `PermanentError`。

`expected_revision` 的取值**只能**是 `Repository.revision_of(pk)`（Phase 06 §5 已明文要求 Phase 49–52 這樣做）。item 上的欄位名是 `_revision`、而且 `get_meta` 會把它濾掉，所以不得改寫成 `query_pk(pk, sk_prefix=META)[0]["revision"]` 這種自己挖 item 的寫法。本 Phase 不新增參數也不新增欄位：Feature 的 item 屬性只有模型的四個欄位加上保留屬性。

掃描全表 Feature 時，`scan_entity("FEATURE")` 回的是 raw item，而 `entity` 屬性等於 PK 前綴，所以同一個 `FEATURE#…` 起點的邊與它同前綴。[Phase 08](08-Phase08-分頁查詢與一致讀取基礎.md) 的 `meta_only` **預設就是 `True`**（00A §6.3），邊不會進來；固定寫法仍是先濾掉 `SK != META` 的列再交給 Phase 08 的 `item_to_model`（與 Phase 27 的 `_meta_models` 同一套，呼叫端改傳 `meta_only=False` 時這層過濾仍然正確）。直接 `Feature.model_validate(item)` 會因為 `PK`／`SK`／`entity`／`_revision` 被 strict 模型拒絕。

## 7. TDD Tasks

### Task 1：鎖定三層定位順序與 0.85 門檻

- [ ] **Step 1：建立失敗測試**

```python
def test_alias_hit_does_not_call_the_model(fake_repo, fake_writer, renamed_release):
    fake_repo.features = [feature("Prepare", name="Prepare", aliases=["Meeting Summary"])]
    found = locate_feature(renamed_release, repository=fake_repo, writer=fake_writer, operation_id="op-r42")
    assert found is not None and found.feature_id == "Prepare"
    assert fake_repo.find_feature_by_name_or_alias("Meeting Summary").feature_id == "Prepare"
    assert fake_repo.find_feature_by_name_or_alias("Prepare").feature_id == "Prepare"
    assert fake_writer.embed_calls == []

@pytest.mark.parametrize("score,expected", [(0.8499, None), (0.85, "Share")])
def test_semantic_match_needs_at_least_the_threshold(fake_repo, fake_writer, changed_release, score, expected):
    fake_repo.features = [feature("Share", name="Share Summary", aliases=[])]
    fake_writer.cosine_for = {"Share": score}
    found = locate_feature(changed_release, repository=fake_repo, writer=fake_writer, operation_id="op-edge")
    assert (found.feature_id if found else None) == expected
```

`renamed_release` 是 `r_42`（`kind="renamed"`、`feature="Prepare"`、`old_name="Meeting Summary"`、`new_name="Prepare"`），`changed_release` 是同一則 Release 但 `kind="changed"`、兩個名稱欄位都是 `None`（Phase 31 只有 `renamed` 強制這兩欄）。第一個測試同時斷言新舊名都回到同一個 `FEATURE#Prepare`，這正是 REL Rule 2 的可觀察結果。

`fake_writer` 不算 cosine，也不假裝自己是 Titan：它把每段文字對應到一個**長度 1024 的單位向量**，查詢文字固定回 `[1.0] + [0.0] * 1023`，候選 `X` 回 `[s, sqrt(1 - s * s)] + [0.0] * 1022`，其中 `s = cosine_for[X]`。這樣 Phase 16 的真 `cosine` 算出來就剛好等於 `s`，邊界值不會被浮點誤差推過門檻；`embed_calls` 記錄每次呼叫的 `(text, node)`。

- [ ] **Step 2：執行 `uv run pytest tests/unit/test_release_locate_feature.py -q` 並確認紅燈**，訊號包含 `cannot import name 'locate_feature'`。

- [ ] **Step 3：建立最小實作**

```python
from training_kb.config import Thresholds
from training_kb.errors import PermanentError
from training_kb.keys import META, feature_pk
from training_kb.models import Feature
from training_kb.repository import item_to_model
from training_kb.vectors import cosine

FEATURE_MATCH_THRESHOLD = Thresholds().cosine_match      # 0.85 的唯一定義在 Phase 02

def normalize_feature_name(value: str) -> str:
    return value.strip().casefold()

def _lookup_keys(release):
    keys = []
    for value in (release.old_name, release.feature, release.new_name):
        if value and value.strip() and value not in keys:
            keys.append(value)
    return tuple(keys)

def _all_features(repository):
    rows = [item for item in repository.scan_entity("FEATURE", consistent=True)
            if str(item["SK"]) == META]
    return sorted((item_to_model(row, Feature) for row in rows), key=lambda item: item.feature_id)

def _names_of(item):
    return {normalize_feature_name(name) for name in [item.name, *item.aliases]}

def _normalized_match(features, keys):
    wanted = {normalize_feature_name(key) for key in keys}
    hits = [item for item in features if wanted & _names_of(item)]
    if len(hits) > 1:
        raise PermanentError(f"名稱對到多個 Feature：{[item.feature_id for item in hits]}")
    return hits[0] if hits else None
```

- [ ] **Step 4：補語意層並跑完整檔案**

```python
def _semantic_match(features, keys, *, writer, operation_id):
    query = writer.embed(" / ".join(keys), operation_id=operation_id, node="locate_feature_query")
    best_score, best = 0.0, None
    for item in features:
        text = " / ".join([item.name, *sorted(item.aliases)])
        vector = writer.embed(text, operation_id=operation_id, node="locate_feature_candidate")
        score = cosine(query, vector)
        if score > best_score:
            best_score, best = score, item
    return best if best is not None and best_score >= FEATURE_MATCH_THRESHOLD else None

def locate_feature(release, *, repository, writer, operation_id):
    keys = _lookup_keys(release)
    for key in keys:
        found = repository.find_feature_by_name_or_alias(key)
        if found is not None:
            return found
    features = _all_features(repository)
    return _normalized_match(features, keys) or _semantic_match(
        features, keys, writer=writer, operation_id=operation_id
    )
```

`features` 已依 `feature_id` 升序排序，加上嚴格 `>` 比較，同分時固定選 `feature_id` 最小者。執行 `uv run pytest tests/unit/test_release_locate_feature.py -q`，預期 alias 命中零模型呼叫、`0.8499` 不命中、`0.85` 命中、同分固定勝者全部 PASS。

- [ ] **Step 5：提交**

```bash
git add src/training_kb/pipelines/release.py tests/unit/test_release_locate_feature.py
git commit -m "feat(release): 三層定位改版功能"
```

### Task 2：alias 撞名拒絕且主鍵不變

- [ ] **Step 1：建立失敗測試**

```python
def test_alias_update_keeps_primary_key_and_moves_old_name(fake_repo):
    target = feature("Prepare", name="Meeting Summary", aliases=[])
    fake_repo.features = [target]
    updated = update_feature_aliases(target, old_name="Meeting Summary", new_name="Prepare", repository=fake_repo)
    assert fake_repo.updated_pk == "FEATURE#Prepare"
    assert (updated.feature_id, updated.name, updated.aliases) == ("Prepare", "Prepare", ["Meeting Summary"])

def test_alias_clash_rejects_the_whole_update(fake_repo):
    target = feature("Prepare", name="Meeting Summary", aliases=[])
    fake_repo.features = [target, feature("Share", name="Share Summary", aliases=["prepare"])]
    with pytest.raises(PermanentError, match="衝突"):
        update_feature_aliases(target, old_name="Meeting Summary", new_name="Prepare", repository=fake_repo)
    assert fake_repo.updated_pk is None
```

- [ ] **Step 2：執行 `uv run pytest tests/unit/test_release_alias_update.py -q` 並確認紅燈**，訊號包含 `cannot import name 'update_feature_aliases'`。

- [ ] **Step 3：建立最小實作**

```python
def update_feature_aliases(feature, *, old_name, new_name, repository):
    display, previous = new_name.strip(), old_name.strip()
    if not display or not previous:
        raise PermanentError("old_name 與 new_name 都不可為空")
    wanted = normalize_feature_name(display)
    candidates = {previous, *(item.strip() for item in feature.aliases)}
    aliases = sorted({item for item in candidates if item and normalize_feature_name(item) != wanted})
    mine = {wanted, *(normalize_feature_name(item) for item in aliases)}
    for other in _all_features(repository):
        if other.feature_id == feature.feature_id:
            continue
        clash = sorted(mine & _names_of(other))
        if clash:
            raise PermanentError(f"alias 與 {other.feature_id} 衝突：{clash}")
    pk = feature_pk(feature.feature_id)
    repository.update_meta(
        pk,
        {"name": display, "aliases": aliases},
        expected_revision=repository.revision_of(pk),
    )
    return feature.model_copy(update={"name": display, "aliases": aliases})
```

`revision_of(pk)` 是 Phase 06 指定的唯一取值來源；它讀的是 item 上的 `_revision`，不是 `revision`，呼叫端也讀不到這個屬性，所以不能自己組 `query_pk`。`_all_features` 的掃描一定要在 `update_meta` **之前**全部跑完：先寫再檢查就會留下「name 已改、alias 撞名」的半套資料。

- [ ] **Step 4：跑 `uv run pytest tests/unit/test_release_alias_update.py -q` 確認綠燈。** 另補三個案例：`new_name` 原本就在 aliases 中（必須被移除）、同一輸入呼叫兩次結果完全相同、只有大小寫不同的撞名也要被拒絕（例如既有 alias 是 `prepare`、新名稱是 `Prepare`，同一個 Feature 自己的要被移除，別的 Feature 的要丟 `PermanentError`）。

- [ ] **Step 5：提交**

```bash
git add src/training_kb/pipelines/release.py tests/unit/test_release_alias_update.py
git commit -m "feat(release): 安全更新功能別名"
```

### Task 3：用真實 Repository 驗證一致讀取與條件更新

- [ ] **Step 1：建立失敗測試**

```python
import pytest

from training_kb.errors import CoordinationError
from training_kb.keys import feature_pk
from training_kb.pipelines.release import locate_feature, update_feature_aliases


class NoWriter:
    def embed(self, text, *, operation_id, node):
        raise AssertionError("字串層就該命中，不應該呼叫 Bedrock")


def test_locate_feature_reads_back_the_alias_it_just_wrote(repository, renamed_release):
    before = repository.get_feature("Prepare")
    update_feature_aliases(before, old_name="Meeting Summary", new_name="Prepare",
                           repository=repository)
    found = locate_feature(renamed_release, repository=repository,
                           writer=NoWriter(), operation_id="op-release-r_42")
    assert (found.feature_id, found.name, found.aliases) == ("Prepare", "Prepare", ["Meeting Summary"])


def test_stale_expected_revision_cannot_overwrite(repository):
    pk = feature_pk("Prepare")
    stale = repository.revision_of(pk)
    repository.update_meta(pk, {"name": "Prepare"}, expected_revision=stale)
    with pytest.raises(CoordinationError, match="stale revision"):
        repository.update_meta(pk, {"name": "Wrong"}, expected_revision=stale)
    assert repository.get_feature("Prepare").name == "Prepare"
```

`repository` 是 Phase 06 的整合 fixture（名稱沿用 Phase 06，不要改叫 `repo`）。setup 用 `put_meta` 寫入三筆 Feature：`Prepare` 是 §2 的改版**前**狀態（`name="Meeting Summary"`、`aliases=[]`），`Share`、`Notify` 的 `name` 與 `feature_id` 相同且沒有 alias；`renamed_release` 與 Task 1 相同。第一個測試證明「改完立刻用舊名找得回同一個節點」全程走基表一致讀取，`NoWriter` 保證它不是靠語意層矇對；第二個測試證明這條寫入路徑真的走樂觀鎖，不是後到的覆蓋先到的。

- [ ] **Step 2：執行並確認紅燈**

```bash
uv run pytest tests/integration/test_release_feature_lookup.py -q
```

預期：FAIL，訊號包含 `cannot import name 'locate_feature'` 或 `fixture 'repository' not found`。

- [ ] **Step 3：把單元測試用的假 Repository 換成真的**

不新增產品程式：`locate_feature`／`update_feature_aliases` 的實作已在 Task 1、Task 2 完成，本 Task 只補整合 fixture 與 setup 資料。`scan_entity` 與 `query_pk` 一律用預設的 `consistent=True`，**不得**改走最終一致的 `query_by_target`；`expected_revision` 一律由 `repository.revision_of(pk)` 取得。

- [ ] **Step 4：跑完整檔案確認綠燈**

```bash
uv run pytest tests/integration/test_release_feature_lookup.py -q
```

預期：PASS，並保存 `aws dynamodb get-item --consistent-read --table-name training_kb --key '{"PK":{"S":"FEATURE#Prepare"},"SK":{"S":"META"}}'` 的原始輸出當證據。若 O5 尚未通過，語意定位的整合案例標為 `xfail(strict=True, reason="O5 尚未驗證")`，不得改用假向量宣稱語意路徑已驗證。

- [ ] **Step 5：提交**

```bash
git add tests/integration/test_release_feature_lookup.py
git commit -m "test(release): 真實表驗證定位與條件更新"
```

## 8. 驗收矩陣

| 路徑 | 輸入 | 預期資料結果 |
|---|---|---|
| Happy | `old_name="Meeting Summary"` 命中既有 alias | 回 `FEATURE#Prepare`；零次 `embed`。 |
| Happy | 只有大小寫／空白不同的名稱 | 第 2 層命中；仍然零次 `embed`。 |
| Failure | 新名稱與別的 Feature 的 alias 相同 | `PermanentError`；`update_meta` 呼叫次數為 0。 |
| Failure | 同一個正規化名稱對到兩個 Feature | `PermanentError`；不隨便挑一個。 |
| Boundary | 最高 cosine 為 `0.8499`／`0.85` | 前者回 `None`，後者採用。 |
| Boundary | 兩個 Feature 同為 `0.90` | 取 `feature_id` 升序最小者，重跑結果相同。 |
| Identity | 連續兩次改名 | PK 始終是第一次建立的值。 |

人工驗收：用 `aws dynamodb get-item --consistent-read` 讀改名前後的 `FEATURE#Prepare`，逐欄比對 `PK`、`name`、`aliases`；再用 `CallTrace` 確認 alias 命中那次執行真的沒有 Bedrock attempt。不能只看測試顯示 PASS。

## 9. 常見錯誤與停止條件

| 症狀 | 原因 | 修正／停止 |
|---|---|---|
| 改名後多出 `FEATURE#Meeting Summary` | 把改名當成建立新 Feature | 停止，不要進入 Phase 50；依 D06 只改 `name`／`aliases`。 |
| 每則 Release 都呼叫 Titan | 沒有先做前兩層比對 | 先做字串層；語意層只在全部落空時執行。 |
| `0.83` 也被採用 | 把模型的「最相近」當成命中 | 由程式套用 `0.85`，未達標回 `None`。 |
| alias 撞名後只有 name 被改掉 | 先寫入再檢查 | 全部檢查通過才呼叫 `update_meta`，整次拒絕。 |
| alias 撞名被記成 KEEP | 把資料違規當成業務結果 | 依設計 §7.4 以 `PermanentError` 結束流程。 |
| 重跑得到不同 Feature | 候選未排序、平手未固定 | 候選依 `feature_id` 升序，比較用嚴格 `>`。 |

## 10. 來源與 Rule 對照

- [依改版更新教學.feature](../../spec/features/依改版更新教學.feature)（[00B 需求覆蓋對照](00B-需求覆蓋對照.md) 給這份 feature 的縮寫是 `REL`；下列四條的 primary 都在本 Phase）
  - Rule 2「改名前後的 alias 對應同一個 Feature 節點」→ Task 1 的 `test_alias_hit_does_not_call_the_model` 直接斷言回傳 `FEATURE#Prepare`。
  - Rule 3「改名不變更第一次建立的 Feature 主鍵」→ Task 2 的 `test_alias_update_keeps_primary_key_and_moves_old_name` 與 §8 的 Identity 案例直接斷言 PK。
  - Rule 4「alias 比對未命中時以向量搜尋最相近的 Feature」→ Task 1 的 `test_semantic_match_needs_at_least_the_threshold` 直接斷言 `0.8499`／`0.85` 兩側。
  - Rule 15「UPDATE 完成時更新 Feature 的 aliases」→ Task 2 產出 `aliases == ["Meeting Summary"]`；實際呼叫時機（發布成功之後）由 Phase 52 的 `UpdateAliases` Task 驗收。
- 設計 §7.4：先比 name／alias，失敗才語意搜尋，最高 cosine 至少 0.85 才採用；無合格 Feature 不改版、不建立功能。
- 設計 §9.1：Feature PK 始終保留第一次建立時的值。§10：正常關係遍歷不呼叫 AI。決策 D06（PK 不遷移）、D07（alias 撞名拒絕該次更新）、F15（必須達門檻才可採用）。
- [Amazon Titan Text Embeddings](https://docs.aws.amazon.com/bedrock/latest/userguide/titan-embedding-models.html)：`amazon.titan-embed-text-v2:0` 輸出 1024 維，且明載不支援 `maxTokenCount`／`topP`，所以定位用的 embedding request 不得夾帶生成參數。
- [DynamoDB 讀取一致性](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/HowItWorks.ReadConsistency.html)：基表可一致讀取、GSI 不行，所以本 Phase 的 Feature 掃描固定 `consistent=True`。

## 11. 完成清單

- [ ] `normalize_feature_name`、`locate_feature`、`update_feature_aliases` 的名稱與簽名符合本文件。
- [ ] 三層定位順序固定，前兩層命中時零次 Bedrock 呼叫。
- [ ] `0.8499` 與 `0.85` 兩個邊界各有直接 assertion，平手依 `feature_id` 升序。
- [ ] 改名後 Feature PK 與 `feature_id` 完全未變。
- [ ] alias 撞名整次拒絕，且沒有任何部分寫入。
- [ ] `REL` Rule 2、3、4 有直接 assertion，Rule 15 有資料結果。
- [ ] 未把 FakeWriter 的 PASS 說成 Bedrock、O5 或 O6 已通過。
