# Phase 25：多篇教學整批發布實作計畫

> **給實作者：** 依 checkbox 逐步執行；每個 Task 先建立失敗測試，再寫最小實作。執行時使用 `superpowers:executing-plans` 或同等逐項流程。

**目標：** 讓一次 `PublishRequest` 同時上架多篇教學，並證明任一中途失敗都不會出現「A 已是新版、B 還是舊版」的對外狀態。

**架構：** 沿用 Phase 24 的 `Publisher.prepare / inspect / commit`，把三段式從一篇擴到 N 篇：全部私有 staging 做完才檢查，全部檢查通過才用**一次** `transact_write_items` 切 N 篇的 `published_at` 與 `current_version`，交易成功後才逐一 promote 到 `site/`。程式負責批次邊界與順序，DynamoDB 只保證交易內的原子性。

**技術：** Python 3.12、pytest、boto3 DynamoDB `transact_write_items`、S3、moto。

## 全域限制

- 唯一主來源是 [Training KB 設計 §7.5、§8.3、§14.1、§18 O3](../../design/training-kb.md)。
- 前置為 [Phase 24：單篇教學發布提交](./24-Phase24-單篇教學發布提交.md)，未通過時停止；下一階段是 [Phase 26：教學退役與後繼導向](./26-Phase26-教學退役與後繼導向.md)。
- 本階段不做：不改 Phase 24 的四個 dataclass 與三個方法簽名、不做退役、不做完整教學站、不決定哪些版本該進同一批（由 [Phase 48](./48-Phase48-Feedback-Review排程流程.md) 與 [Phase 52](./52-Phase52-Release-RETIRE與流程驗收.md) 決定）、不新增第二個 publisher。
- **不可放寬 F49**（F01–F55 是設計 §19 的功能決策編號；F49＝「整次執行以失敗結束，不發布新版本」）。它不得改寫成「允許部分成功再補」，也不得用「先發布 A、B 失敗就刪掉 A」代替；事後刪除不會消除先前曝光。
- O1–O7 gate 狀態：O3 由 [Phase 12](./12-Phase12-O3發布切換整合驗證.md) 判定。O3 未 PASS 前，多篇 `commit` 只能在隔離環境執行，且**不得宣稱多篇原子發布已通過**。O2 未 PASS 前不得宣稱同 operation 重送必得同一批版號。
- 只要任一測試或實測觀察到 partial 可見（A 新 B 舊），即保留可追溯 FAIL 並停止公開路徑，不改需求、不加 CloudFront、不加公開讀取 API。
- 以下程式檔均是實作時預計建立或修改；本計畫本身不代表它們已存在。

---

## 1. 你在整體流程的位置

```text
Phase 48 每日 Review / Phase 52 Release RETIRE
   |  多篇待發布 version_ids
   v
+--+----------------------------------------+
| [你在這裡] Publisher 整批三段式            |
|  prepare(N) -> inspect(N) -> commit(N)     |
+--+----------------------------------------+
   +--> 任一篇未通過 --> 零篇發布；全部維持舊 current_version
   +--> 全部通過 ------> 一次交易切 2N 個欄位 --> promote site/ --> Phase 57 教學站顯示新版
```

## 2. 完成後看得到什麼

一次送出兩篇：`PublishRequest(version_ids=("prepare-meeting@v3", "share-summary@v2"), operation_id="op-review-0914")`。

```text
成功：TUTORIAL#prepare-meeting.current_version : @v2 -> @v3
      TUTORIAL#share-summary  .current_version : @v1 -> @v2
      site/tutorials/prepare-meeting/v3.html、site/tutorials/share-summary/v2.html 同時出現

share-summary 的關係不完整：prepare 直接丟 PublishError，不產生 PublishResult
      兩篇 current_version 都不變，site/ 一個新檔都沒有，prepare-meeting 讀者仍讀 v2
```

## 3. 名詞小抄

| 名詞 | 白話意思 |
|---|---|
| 整批（batch） | 這一次操作要一起上架的所有版本；不是「一篇一篇送、失敗再補」。 |
| 全有或全無 | 要嘛所有版本都對外變新，要嘛全部維持舊；中間狀態不可被讀者看到。 |
| partial 可見 | 讀者在某一刻讀到 A 是新版、B 還是舊版；本 Phase 的最大失敗。 |
| action | 交易裡的一個寫入項；每篇教學需要兩個（VERSION 一個、TUTORIAL 一個）。 |
| staging | 發布前先寫在私有 `operations/<operation_id>/site/...` 的頁面；讀者看不到。 |
| promote | 把私有 staging 的同一份 bytes 複製到公開 `site/` 前綴。 |
| O3 | 設計 §18 七個「待確認事項」（編號 O1–O7）之一：S3 公開切換與 DynamoDB 發布提交還沒有可行解，只能由真實證據關閉。 |
| F49 | 設計 §19 的功能決策編號之一：Task 重試耗盡進 Catch 後整次執行以失敗結束，不發布新版本。 |

## 4. 預計檔案

| 動作 | 路徑 | 責任 |
|---|---|---|
| 修改 | `src/training_kb/publishing.py` | `MAX_BATCH_VERSIONS`、`assert_batch_publishable`、`build_commit_transaction`、`promote_site_objects`，並把 `Publisher` 三個方法改成走批次路徑。 |
| 沿用 | `src/training_kb/site.py` | [Phase 24](./24-Phase24-單篇教學發布提交.md) 的 `SiteRenderer`；本 Phase 只呼叫既有三個 render 方法重建索引，不改它。 |
| 測試 | `tests/unit/test_publisher_batch.py` | 批次邊界、一次交易、promote 順序與待補清單。 |
| 測試 | `tests/integration/test_batch_publish_cutpoints.py` | 五個切點的可觀察結果（moto + 公開讀取）。 |

## 5. 固定介面

### Consumes

```text
PublishRequest(version_ids: tuple[str, ...], operation_id: str)                          # Phase 24
PreparedPublish(request, version_ids, staged_keys, prepared_at)                          # Phase 24
PublishInspection(ok, problems) / PublishResult(published, failed, reasons)              # Phase 24
Publisher.prepare / inspect / commit（簽名不變）; SiteRenderer 三個 render 方法           # Phase 24
site_key(version_id) -> str ; Repository.transact_write(items) -> int | None ; table_name # Phase 24
verify_version_complete(version_id, repository) -> bool                                  # Phase 23
PUBLIC_SITE_PREFIX（值 "site/"）                                                          # Phase 22
parse_version_id(value: str) -> tuple[str, int]                                          # Phase 20
operation_ref(operation_id, name) -> str ; OperationCoordinator.record_version / load    # Phase 10
Repository.put_object(key, body, content_type, *, if_none_match) / get_object(key)       # Phase 07
Repository.get_version(version_id) / get_tutorial(slug)                                  # Phase 06
version_pk(version_id) / tutorial_pk(slug) / META                                        # Phase 05
PublishError / TransientError / to_iso(dt) -> str                                        # Phase 02
```

### Produces

```python
MAX_BATCH_VERSIONS: int = 50

def assert_batch_publishable(prepared: PreparedPublish) -> None: ...

def build_commit_transaction(
    prepared: PreparedPublish, *, repository: Repository, now: datetime
) -> list[dict[str, object]]: ...

def promote_site_objects(
    prepared: PreparedPublish, *, repository: Repository
) -> tuple[str, ...]: ...
```

`Publisher` 的四個 dataclass 與三個方法簽名由 Phase 24 擁有，本 Phase **只換實作**；[Phase 48](./48-Phase48-Feedback-Review排程流程.md) 與 [Phase 52](./52-Phase52-Release-RETIRE與流程驗收.md) 已在消費它們，不得改名或改參數。`promote_site_objects` 回傳這一批**實際寫出**的公開 key（含 `site/` 前綴），順序與 `prepared.version_ids` 相同，**每篇兩個**：版本頁 `v<n>.html` 與它的公開 diff 副本 `v<n>.diff.txt`（兩份 staging 都由 [Phase 24](./24-Phase24-單篇教學發布提交.md) 的 `prepare` 產生，D-54）。已存在且 bytes 相同的 key 仍然回傳，因為它同樣代表「這個公開物件已就緒」。

## 6. 設計細節

`TransactWriteItems` 一次最多 100 個 action、總計 4 MB，而且**同一筆 item 不能在同一個交易被兩個 action 指到**。每篇教學固定用兩個 action，因此：

- `MAX_BATCH_VERSIONS = 50`；超過就丟 `PublishError`。不可拆成兩次交易換取「跑得完」，拆了就不再是全有或全無。
- 同一個 `slug` 不能在同一批出現兩個版本，否則兩個 action 會指到同一個 `TUTORIAL#<slug>` item，整個交易被 AWS 判為 validation error。這種情況代表上游把同篇的兩次變更放進同一批，屬於接受順序（O2）問題，必須回頭串行處理。
- `version_ids` 內重複值一律拒絕，不做「自動去重」，避免遮蔽上游錯誤。

```text
 版本清單 -> assert_batch_publishable --(空／>50 篇／重複 id／同 slug 兩版)--> PublishError
                |                                                （零 staging、零發布）
                v
   prepare 全部 -> inspect 全部 -> build_commit_transaction(2N actions) -> transact_write
                |                                                              |
        任一不通過 --> 零篇發布                            +-------------------+-------+
                                                          | 條件不符                   | 成功
                                                          v                            v
                                             PublishResult(published=())   pending-promote.json
                                                                           -> promote_site_objects
                                                                           -> 教學索引 -> 站台索引
```

五個中途失敗切點與可觀察結果：

| # | 切點 | DynamoDB | 公開 `site/` | 判定 |
|---:|---|---|---|---|
| 1 | `assert_batch_publishable` 拒絕 | 全部舊 | 全部舊 | 合格：零篇發布。 |
| 2 | `prepare` 第 k 篇失敗 | 全部舊 | 全部舊 | 合格：前 k-1 篇 staging 留在私有 `operations/`，讀者看不到。 |
| 3 | `inspect` 回 `ok=False` | 全部舊 | 全部舊 | 合格：`commit` 不執行。 |
| 4 | 交易被取消（任一條件不符） | 全部舊 | 全部舊 | 合格：DynamoDB 保證 all-or-nothing，不會只切一半。 |
| 5 | 交易成功、promote 第 j 篇失敗 | **全部新** | 前 j-1 篇新、其餘舊 | **不合格：partial 可見。** |

切點 5 就是設計 §8.3 明列、O3 尚未解的那一段。本計畫的做法是把它縮到最小並留下可補齊的痕跡，**不是宣稱已解決**：

- `commit` 在交易成功後、promote 之前，先把待 promote 的公開 key 清單寫進私有操作紀錄 `operations/<operation_id>/pending-promote.json`（key 用 [Phase 10](./10-Phase10-O2操作紀錄與永久去重契約.md) 的 `operation_ref(operation_id, "pending-promote")` 組出來，內容是 `{"version_ids": [...], "site_keys": [...]}`）。[Phase 59](./59-Phase59-失敗復原與重送驗收.md) 以同一個 `operation_id` 重送時讀這份清單精確補齊，不會重新建版或重新呼叫模型。這份清單**只寫私有前綴**，不得塞進 `TUTORIAL`／`VERSION` item：十實體模型是嚴格模型，多一個欄位下次讀取就驗證失敗。
- promote 順序固定為「版本頁 → 教學索引 → 站台索引」，讓中斷時公開站最多是「新頁已存在但索引還沒指過去」，而不是索引指向不存在的頁。`promote_site_objects` 只負責第一段：依 `prepared.version_ids` 的順序把私有 staging 的同一份 bytes 複製到 `site/`，每篇先版本頁、再公開 diff 副本 `v<n>.diff.txt`。教學索引與站台索引是可重建投影（Phase 24 已如此處理），由 `commit` 在 `promote_site_objects` 回傳之後才用 `SiteRenderer` 重寫，因此整體順序仍然成立。**本計畫選擇：** 這樣切分是為了讓 `promote_site_objects` 的參數只有 `prepared` 與 `repository`，不必再傳一個 renderer 進來。
- 切點 5 對應 [Phase 12](./12-Phase12-O3發布切換整合驗證.md) 的 O3 切點 `a3_after_first_site_before_second`（多篇中途），判定屬於 Phase 12 的報告，本 Phase 只負責製造與記錄這個觀察。只要真實環境觀察到它，Phase 25 就停在 FAIL：保留報告與重現指令，**不得**改成逐篇 publish、不得刪除已 promote 的頁面充當回滾、不得把 F49 改寫成「允許部分成功」，也不得用「反正沒有連結指過去」當成沒有公開（設計 §18 O3 明文禁止）。

## 7. TDD Tasks

### Task 1：整批邊界與單一交易

- [ ] **Step 1：建立失敗測試**

```python
def test_commit_batch_switches_all_or_nothing(publisher, repo):
    request = PublishRequest(("prepare-meeting@v3", "share-summary@v2"), "op-review-0914")
    prepared = publisher.prepare(request, now=NOW)
    assert publisher.inspect(prepared).ok is True
    repo.move_base_during_transaction("share-summary", "share-summary@v7")
    result = publisher.commit(prepared, now=NOW)
    assert result.published == () and result.failed == "share-summary@v2"
    assert repo.transact_calls == 1
    assert repo.get_tutorial("prepare-meeting").current_version == "prepare-meeting@v2"
    assert repo.get_version("prepare-meeting@v3").published_at is None
    assert [key for key in repo.objects if key.startswith("site/")] == []
```

`move_base_during_transaction` 讓假的 `Repository` 在 `transact_write` **被呼叫的那一刻**才改掉 `share-summary` 的 `current_version`：這裡要驗的是「`inspect` 通過之後、交易之前被別人插隊」這個時間窗，只有交易的條件式擋得住。若基底在 `inspect` 之前就位移，走的是 [Phase 24](./24-Phase24-單篇教學發布提交.md) 的另一條路（`inspect` 回 `ok=False`、`commit` 丟 `PublishError`），同樣零公開產物。

- [ ] **Step 2：執行並確認紅燈**

```bash
uv run pytest tests/unit/test_publisher_batch.py -q
```

預期：FAIL，訊號包含 `cannot import name 'assert_batch_publishable'`。

- [ ] **Step 3：建立最小實作**

```python
MAX_BATCH_VERSIONS = 50


def assert_batch_publishable(prepared: PreparedPublish) -> None:
    version_ids = list(prepared.version_ids)
    if not version_ids:
        raise PublishError("整批發布至少要有一個版本")
    if len(version_ids) > MAX_BATCH_VERSIONS:
        raise PublishError(f"一次交易最多 {MAX_BATCH_VERSIONS} 篇，收到 {len(version_ids)} 篇")
    if len(set(version_ids)) != len(version_ids):
        raise PublishError("整批內有重複的 version_id")
    slugs = [parse_version_id(version_id)[0] for version_id in version_ids]
    if len(set(slugs)) != len(slugs):
        raise PublishError("同一篇教學不可在同一批出現兩個版本，請依接受順序串行處理")


def build_commit_transaction(
    prepared: PreparedPublish, *, repository: Repository, now: datetime
) -> list[dict[str, object]]:
    assert_batch_publishable(prepared)
    items: list[dict[str, object]] = []
    for version_id in prepared.version_ids:
        version = repository.get_version(version_id)
        if version is None:
            raise PublishError(f"{version_id} 不存在，不能提交")
        tutorial = repository.get_tutorial(version.slug)
        if tutorial is None:
            raise PublishError(f"{version.slug} 不存在，不能提交")
        items.extend(
            _version_and_tutorial_actions(version, tutorial, repository.table_name, now=now)
        )
    return items
```

`prepare` 的第一件事就是呼叫 `assert_batch_publishable`，任何拒絕都必須發生在寫第一個 staging 物件之前；slug 用 [Phase 20](./20-Phase20-版本分配與重試重用.md) 的 `parse_version_id` 取，不要自己 `split("@")`，那樣擋不掉形狀不對的 `version_id`，等於多一份版本 ID 解析規則。

`_version_and_tutorial_actions` 是把 Phase 24 的私有 `Publisher._transact_items` 搬成模組函式，兩個 `Update` action 與條件式**逐字不變**（`published_at` 用 `attribute_not_exists(published_at) OR attribute_type(published_at, :null)`；`current_version` 用 `current_version = :base`，v1 用 `attribute_not_exists(current_version) OR ...`）。搬家之後單篇路徑就是 N=1 特例，全套只有一份條件式；私有方法不是跨 Phase 介面，改它不算動 Phase 24 的固定簽名。`commit` 的順序固定是 `inspect` → `build_commit_transaction` → **一次** `Repository.transact_write`；回傳非 `None` 時用 `prepared.version_ids[index // 2]` 當 `failed`（每篇兩個 action，VERSION 在前、TUTORIAL 在後），`published` 保持空 tuple，**不得**改成逐篇重試或只重送失敗那一篇。

- [ ] **Step 4：補上邊界與成功案例並跑綠燈**

```python
BAD_BATCHES = [((), "至少要有一個版本"), (tuple(f"t-{n}@v1" for n in range(51)), "最多 50 篇"),
               (("a@v1", "a@v1"), "重複的 version_id"), (("a@v1", "a@v2"), "同一篇教學")]


@pytest.mark.parametrize(("version_ids", "signal"), BAD_BATCHES)
def test_assert_batch_publishable_rejects_bad_batches(version_ids, signal):
    prepared = PreparedPublish(PublishRequest(version_ids, "op-1"), version_ids, (), NOW)
    with pytest.raises(PublishError, match=signal):
        assert_batch_publishable(prepared)
```

另補三個案例：第二篇關係不完整時 `prepare` 丟 `PublishError`、零 `site/` 物件、兩篇 `current_version` 都不變；`get_version` 回 `None` 時丟 `PublishError` 而不是 `AttributeError`；兩篇都完整時 `repo.transact_calls == 1`、兩個 `published_at` 都等於 `now`、兩個 `current_version` 都切換，且 `PublishResult.published` 的順序與 `prepared.version_ids` 相同。

```bash
uv run pytest tests/unit/test_publisher_batch.py -q
```

- [ ] **Step 5：提交**

```bash
git add src/training_kb/publishing.py tests/unit/test_publisher_batch.py
git commit -m "feat(content): 整批邊界檢查與單一交易提交"
```

### Task 2：待補清單與 promote 順序

- [ ] **Step 1：建立失敗測試**

```python
def test_commit_records_pending_keys_then_promotes_in_fixed_order(publisher, repo):
    request = PublishRequest(("prepare-meeting@v3", "share-summary@v2"), "op-review-0914")
    prepared = publisher.prepare(request, now=NOW)
    publisher.commit(prepared, now=NOW)
    pending = json.loads(repo.objects["operations/op-review-0914/pending-promote.json"])
    assert pending["site_keys"] == ["site/tutorials/prepare-meeting/v3.html",
                                    "site/tutorials/prepare-meeting/v3.diff.txt",
                                    "site/tutorials/share-summary/v2.html",
                                    "site/tutorials/share-summary/v2.diff.txt"]
    assert repo.site_writes == pending["site_keys"] + [
        "site/tutorials/prepare-meeting/index.html",
        "site/tutorials/share-summary/index.html", "site/index.html"]
```

`repo.site_writes` 是假 `Repository` 記下的「寫進 `site/` 前綴的 key，依實際寫入順序」。斷言同時鎖住兩件事：待補清單在第一個公開物件出現**之前**就已存在，以及「版本頁 → 教學索引 → 站台索引」的順序。

- [ ] **Step 2：執行並確認紅燈**

```bash
uv run pytest tests/unit/test_publisher_batch.py -q
```

預期：FAIL，訊號包含 `cannot import name 'promote_site_objects'`。

- [ ] **Step 3：建立最小實作**

```python
def promote_site_objects(
    prepared: PreparedPublish, *, repository: Repository
) -> tuple[str, ...]:
    staged = {key.rsplit("/site/", 1)[1]: key for key in prepared.staged_keys}
    promoted: list[str] = []
    for version_id in prepared.version_ids:
        pairs = ((site_key(version_id), "text/html; charset=utf-8"),
                 (_diff_copy_key(version_id), "text/plain; charset=utf-8"))
        for relative, content_type in pairs:      # 版本頁先、公開 diff 副本後
            body = repository.get_object(staged[relative])
            if body is None:
                raise PublishError(f"{version_id} 的 staging 物件不見了，停止 promote：{relative}")
            public_key = PUBLIC_SITE_PREFIX + relative
            existing = repository.get_object(public_key)
            if existing is None:
                repository.put_object(public_key, body, content_type, if_none_match=True)
            elif existing != body:
                raise PublishError(f"{public_key} 已存在且內容不同，不覆寫已發布內容")
            promoted.append(public_key)
    return tuple(promoted)
```

`commit` 在交易成功之後固定照這五步收尾，順序不可對調：(1) 用 `operation_ref(operation_id, "pending-promote")` 組 key，以 `put_object(..., if_none_match=False)` 寫待補清單（同 operation 重送要能覆寫成同一份內容）；(2) `promote_site_objects(...)`；(3) 依 `version_ids` 首次出現順序重寫每個 slug 的教學索引；(4) 重寫站台索引；(5) 逐一 `operations.record_version(...)`。版本頁一律 `if_none_match=True`：已發布內容不可被覆寫，相同 bytes 就略過、不同 bytes 就停。

- [ ] **Step 4：補上三個案例並跑綠燈**

staging 物件不見了 → `PublishError`；公開 key 已存在但 bytes 不同 → `PublishError` 且不寫入；同 operation 重送、公開 key 已存在且 bytes 相同 → 不再寫入但仍回同一組 key，`site_writes` 不增加版本頁。

```bash
uv run pytest tests/unit/test_publisher_batch.py -q
```

- [ ] **Step 5：提交**

```bash
git add src/training_kb/publishing.py tests/unit/test_publisher_batch.py
git commit -m "feat(content): 固定整批 promote 順序與待補清單"
```

### Task 3：切點注入與 O3 觀察

- [ ] **Step 1：建立整合測試起始狀態與失敗測試**（兩篇都已有已發布舊版且公開 URL 讀得到；兩個新版都是 `published_at=null`，公開站讀不到）

```python
@pytest.mark.parametrize("fault", ["prepare_second", "inspect_second", "transact"])
def test_batch_cutpoints_2_to_4_keep_everything_old(fault, aws_publisher, site_reader):
    with injected_fault(fault), pytest.raises((PublishError, TransientError)):
        publish_batch(aws_publisher)
    assert site_reader.read("site/tutorials/prepare-meeting/v3.html") is None
    assert site_reader.read("site/tutorials/share-summary/v2.html") is None
    assert site_reader.current_version("prepare-meeting") == "prepare-meeting@v2"
    assert site_reader.current_version("share-summary") == "share-summary@v1"
```

`injected_fault` 是**本測試檔內**的 `contextmanager`，用 `monkeypatch` 把對應呼叫換成丟 `TransientError` 的替身。[Phase 59](./59-Phase59-失敗復原與重送驗收.md) 之後才有正式的 `TKB_FAULT` 切點；本 Phase 不預先使用它，也不假裝它已存在。

- [ ] **Step 2：執行並確認紅燈**

```bash
uv run pytest tests/integration/test_batch_publish_cutpoints.py -q
```

預期：FAIL，訊號包含 `fixture 'aws_publisher' not found`。

- [ ] **Step 3：補上守門實作**

`commit` 未經 `inspect` 或 `inspect` 不通過就丟 `PublishError`，不進交易；`transact_write` 回非 `None` 時直接回 `PublishResult(published=())`，不進收尾五步。切點 2、3、4 的「全部舊」因此由程式順序保證，不靠 AWS 幫忙回滾。

- [ ] **Step 4：跑綠燈並存證**

切點 2、3、4 必須都是「兩篇皆舊」。每個切點各存一筆證據：兩篇的 `TUTORIAL` item（`get_item`）與公開 website endpoint 的 HTTP 回應，時間戳要能對得上。

```bash
uv run pytest tests/integration/test_batch_publish_cutpoints.py -q
```

- [ ] **Step 5：觀察切點 5、重送補齊並提交**

切點 5（交易成功、promote 第 2 篇失敗）**不寫成綠燈斷言**。用同一組 fixture 實際跑一次，同時記錄兩篇的 `TUTORIAL` item 與公開 HTTP 回應，判定交給 [Phase 12](./12-Phase12-O3發布切換整合驗證.md) 的 O3 報告（切點 `a3_after_first_site_before_second`）。觀察到「一新一舊」就是 partial 可見：保留 FAIL、停止公開路徑，**不得**改斷言、標 `xfail`、刪除已 promote 的頁面充當回滾，或把 F49 改寫成允許部分成功。

移除故障後以**同一個 `operation_id`** 重送：讀 `operations/op-review-0914/pending-promote.json` 補齊缺的公開物件，斷言沒有第三個版本、沒有第二份模型輸出、沒有新的 `version_id`。

```bash
uv run pytest tests/integration/test_batch_publish_cutpoints.py -q
git add tests/integration/test_batch_publish_cutpoints.py
git commit -m "test(content): 驗證整批發布的失敗切點"
```

## 8. 驗收矩陣

| 路徑 | 輸入 | 預期資料結果 |
|---|---|---|
| Happy | 兩篇都完整 | 一次交易切 4 個欄位；兩個公開頁同時出現。 |
| Happy | 只有一篇 | 與 Phase 24 單篇行為完全相同。 |
| Failure | 第二篇關係不完整 | `prepare` 丟 `PublishError`；零公開、零 DB 變更。 |
| Failure | 第二篇基底在 `inspect` 之前就位移 | `inspect` 回 `ok=False`；`commit` 丟 `PublishError`，不進交易。 |
| Failure | 第二篇基底在 `inspect` 之後才位移 | 整批交易取消；`failed` 指出該版本；第一篇也不切。 |
| Failure | promote 第二篇失敗 | DB 全新、公開一新一舊 → 判 FAIL，停止公開路徑。 |
| Boundary | 51 篇 | `PublishError`；不得自動拆成兩次交易。 |
| Boundary | 同 slug 兩版同批 | `PublishError`，訊息指向接受順序；不得由程式挑較新的那一版。 |
| Boundary | 空 `version_ids` | `PublishError`；不視為「成功但沒事做」。 |
| Idempotency | 同 operation 重送 | 讀 `pending-promote.json` 沿用原 staging 與版號，只補齊缺的公開物件，不重複建版。 |

人工驗收：在故障注入的當下用公開 website endpoint 同時讀 A 與 B 兩頁，把兩個 HTTP 回應與當時的 `TUTORIAL` item 一起存證；不能只看測試顯示 PASS，也不能只檢查 DynamoDB。

## 9. 常見錯誤與停止條件

| 症狀 | 原因 | 修正／停止 |
|---|---|---|
| 在 Map 內逐篇 publish | 把「每篇獨立」當成可以獨立上架 | 停止：改成全部 prepare/inspect 後一次 commit。 |
| B 失敗就刪掉已發布的 A | 以為刪檔等於沒發布過 | 停止：事後刪除不消除曝光，且已發布內容不可覆寫。 |
| 60 篇自動拆成兩次交易 | 只想讓流程跑完 | 停止：拆交易即放棄全有或全無；改由上游分批決策並各自遵守 F49。 |
| 交易回 validation error | 同 slug 兩版進同一批 | 回到 O2 接受順序，串行處理同篇變更。 |
| 公開索引指向不存在的頁 | promote 順序反了 | 固定「版本頁 → 教學索引 → 站台索引」。 |
| 把待 promote 清單塞進 `TUTORIAL` item | 想少開一個 S3 物件 | 停止：十實體是嚴格模型，多欄位下次 `get_meta` 就驗證失敗；一律寫私有 `operations/`。 |
| 切點 5 被標成 `xfail` 或改掉斷言 | 想讓整包測試變綠 | 停止：那是 O3 缺口的證據，必須保留可追溯 FAIL。 |
| 宣稱多篇原子發布已驗證 | 把 moto 綠燈當 O3 證據 | 停止：O3 仍待 [Phase 12](./12-Phase12-O3發布切換整合驗證.md) 的真實結果。 |

## 10. 來源與 Rule 對照

本 Phase 是**驗收型 Phase，沒有 primary Rule**；下列三條的 primary 都在別份文件（依 [00B 需求覆蓋對照](./00B-需求覆蓋對照.md) 第 3.2、3.3 節的裁決），本 Phase 只在多篇整批的情境下再驗一次，測試保留但不重複認領。

- [發布教學版本.feature](../../spec/features/發布教學版本.feature)
  - Rule 1：「publish 上架指定的 TutorialVersion」→ **相關（primary 在 [Phase 24](./24-Phase24-單篇教學發布提交.md)）**；Task 2 成功案例補驗 N 篇同時上架，順序與請求一致。
  - Rule 4：「Tutorial 的 current_version 指向目前教學版本」→ **相關（primary 在 Phase 24）**；Task 2 失敗案例補驗任一篇失敗時**所有** `current_version` 都不切。
  - Rule 5：「已上架的版本具有 published_at」→ **相關（primary 在 Phase 24）**；Task 2 補驗 `published_at` 只在同一筆交易內一起寫入。
- [執行教學流程.feature](../../spec/features/執行教學流程.feature) Rule 7：「每個 Step Functions Task 設定 Catch」→ **相關（primary 在 [Phase 29](./29-Phase29-共用Pipeline執行器與ASL失敗語意.md)）**。Rule 7 本身是 ASL 上每個 Task 都有 `Catch` 的斷言；本 Phase 驗的是 Catch 之後的**資料結果**（零新版本公開），依據是決策 F49，不是 Rule 7 的 ASL 斷言。
- [定期檢視回饋.feature](../../spec/features/定期檢視回饋.feature)：supporting；本 Phase 是 [Phase 48](./48-Phase48-Feedback-Review排程流程.md) 整批提交的實作基礎，不決定哪些版本進批。
- 設計 §8.3：多篇命中同受 F49 限制；不能先發布 A 再因 B 失敗宣稱整次沒有發布；多篇提交切點納入 O3。
- 設計 §14.1：Task 重試耗盡由 Catch 導向失敗終點，不發布新版本、不新增待審狀態。
- [DynamoDB TransactWriteItems](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/transaction-apis.html)：一次最多 100 個 action、4 MB，且同一筆 item 不能被同一交易的兩個 action 指到；取消時回 `TransactionCanceledException` 與依序的 `CancellationReasons`。
- [S3 條件寫入](https://docs.aws.amazon.com/AmazonS3/latest/userguide/conditional-writes.html)：S3 沒有跨物件交易，promote 只能逐一寫入，這正是切點 5 存在的原因。

## 11. 完成清單

- [ ] `MAX_BATCH_VERSIONS`、`assert_batch_publishable`、`build_commit_transaction`、`promote_site_objects` 簽名符合本文件。
- [ ] Phase 24 的四個 dataclass 與三個方法簽名完全沒有更動。
- [ ] 整批 prepare／inspect 失敗時，零公開產物且零 `current_version` 變更。
- [ ] N 篇只用一次 `transact_write_items`，測試直接斷言呼叫次數為 1。
- [ ] 51 篇、同 slug 兩版、重複 id、空清單四個邊界各有拒絕測試。
- [ ] `promote_site_objects` 有自己的測試：順序、staging 遺失、bytes 不同、重送略過各一例；每篇都搬版本頁與 `v<n>.diff.txt` 兩個公開物件（D-54）。
- [ ] 待 promote 的公開 key 清單寫在 `operations/<operation_id>/pending-promote.json`，沒有任何欄位進 `TUTORIAL`／`VERSION` item。
- [ ] 切點 2、3、4 各有一筆 DynamoDB 與公開 HTTP 的同時觀察證據；切點 5 的觀察結果交給 [Phase 12](./12-Phase12-O3發布切換整合驗證.md) 的 O3 報告。
- [ ] 出現 partial 可見時保留 FAIL，未放寬 F49、未新增服務、未改寫需求。
- [ ] 未把單元測試或 moto PASS 說成 O3 已通過或多篇原子發布已驗收。
