# Phase 26：教學退役與後繼導向實作計畫

> **給實作者：** 依 checkbox 逐步執行；每個 Task 先建立失敗測試，再寫最小實作。執行時使用 `superpowers:executing-plans` 或同等逐項流程。

**目標：** 把一篇教學標記為 `retired`、保留全部歷史原文與版本、拒絕新回饋，並只在後繼教學通過四項檢查時才顯示導向。

**架構：** `retire_tutorial` 只改 Tutorial metadata 的兩個欄位（`status`、`successor`），完全不碰 `VERSION`、`STEP`、S3 全文與 diff。後繼由 `resolve_successor` 先驗證再寫入；驗證不過就寫 `None`，退役照樣完成。公開頁由 Phase 24 的最小 `SiteRenderer` 補上退役區塊，簽名不變。

**技術：** Python 3.12、Pydantic v2、pytest、既有 `Repository.update_meta` 條件更新。

## 全域限制

- 唯一主來源是 [Training KB 設計 §8.1、§8.4、§13、§14.1](../../design/training-kb.md)。
- 前置為 [Phase 25：多篇教學整批發布](./25-Phase25-多篇教學整批發布.md)，未通過時停止；下一階段是 [Phase 27：固定圖譜查詢](./27-Phase27-固定圖譜查詢.md)。
- 本階段不做：不判斷哪一篇該退役（`kind=removed` 的定位由 [Phase 50](./50-Phase50-Release步驟反查與Safety-Net.md)、觸發由 [Phase 52](./52-Phase52-Release-RETIRE與流程驗收.md) 負責）、不刪除任何版本或 S3 物件、不建立新版本、不做完整 retired 頁樣式與 diff 檢視（[Phase 57](./57-Phase57-S3靜態教學站與回饋下載.md)）、不實作回饋匯入本身（[Phase 42](./42-Phase42-Feedback與View固定匯入.md)）。
- 資料狀態只使用 `retired`；`obsolete` 只是顯示用語，不得寫進資料。
- successor **由維護者選定既有 Tutorial**；來源事件（Release payload、模型輸出）不得直接指定後繼。
- 找不到合法後繼時保持空值，**不能阻擋退役**；也不做連續自動跳轉。
- O1–O7 gate 狀態：本 Phase 不依賴 O3，也**不宣稱** O3 已通過；退役本身不發布新版本。O1 的 `META` 仍是待確認值，`update_meta` 的鍵沿用 [Phase 05](./05-Phase05-單表鍵與關係邊契約.md) 的決定。
- 以下程式檔均是實作時預計建立或修改；本計畫本身不代表它們已存在。

---

## 1. 你在整體流程的位置

```text
Phase 52 Release(kind=removed) 決定要退役哪一篇
   |  slug + reason + 維護者選定的 successor（可為 None）
   v
+--+--------------------------------------+
| [你在這裡] resolve_successor -> retire   |
+--+--------------------------------------+
   |
   +--> Tutorial.status = retired（歷史版本、S3 全文、既有回饋全部保留）
   |
   +--> successor 合法 --> 公開頁顯示「已退役」+ 一個可點的後繼連結
   |
   +--> successor 無效 --> successor = None；只顯示過期說明，不導向
   |
   +--> 新回饋匯入 ------> IngressError（Phase 42 呼叫本 Phase 的檢查）
```

## 2. 完成後看得到什麼

`retire_tutorial("meeting-summary", reason="release:r_88", successor="prepare-meeting", repository=repo, now=NOW)`：

```text
TUTORIAL#meeting-summary . status         : active -> retired
TUTORIAL#meeting-summary . successor      : null -> prepare-meeting
TUTORIAL#meeting-summary . current_version: meeting-summary@v2（不變）
VERSION#meeting-summary@v1 / @v2          : 完全不變，published_at 保留
tutorials/meeting-summary/v2.md           : 完全不變
```

若改成 `successor="meeting-summary"`（自身）、`"not-exists"`（不存在）或一篇 `status=retired` 的教學，結果一律是 `successor=None`，但 `status` 仍然變成 `retired`。之後匯入 `Feedback(tutorial_version="meeting-summary@v2", ...)` 必須失敗並指出欄位，既有的 `f_12` 仍查得到。

## 3. 名詞小抄

| 名詞 | 白話意思 |
|---|---|
| 退役（retired） | 這篇教學不再維護，但原文與版本全部留著給人查。 |
| 後繼（successor） | 讀者接下來該看哪一篇；由維護者指定，不是系統猜的。 |
| 循環導向 | A 指向 B、B 又指回 A，讀者會被推來推去；必須在寫入前擋掉。 |
| 可公開的後繼 | 對方是 `active`，而且已經有發布過的版本可以讀。 |
| 冪等 | 同一個退役操作做兩次，結果跟做一次一樣，不會把已設定的後繼清掉。 |
| `_revision` | item 上的樂觀鎖版本號；寫入前先讀它，寫入時比對，不同就代表有人插隊。 |
| O1–O7 | 設計 §18 的七個「待確認事項」編號；只能由真實證據關閉，文件寫得再完整都不算。 |
| D21／F19 這類編號 | 設計 §19 已裁決的決策編號，`D` 是資料決策、`F` 是功能決策；本文件第 10 節逐條列出用到的幾個。 |

## 4. 預計檔案

| 動作 | 路徑 | 責任 |
|---|---|---|
| 修改 | `src/training_kb/content.py` | `retire_tutorial`、`resolve_successor`、`assert_accepts_feedback`。 |
| 修改 | `src/training_kb/site.py` | 退役區塊與後繼連結（[Phase 24](./24-Phase24-單篇教學發布提交.md) 建立的 `SiteRenderer`，`render_version_page` 簽名不變）。 |
| 測試 | `tests/unit/test_retire_tutorial.py` | 四項後繼檢查、循環、保留歷史、冪等。 |
| 測試 | `tests/unit/test_retired_page.py` | 過期說明、後繼連結、無後繼時不導向。 |
| 測試 | `tests/integration/test_retired_feedback_rejected.py` | 退役後拒絕新回饋、既有回饋仍可讀。 |

## 5. 固定介面

### Consumes

```text
Repository.get_tutorial(slug: str) -> Tutorial | None                   # Phase 06
Repository.update_meta(pk, changes, *, expected_revision: int) -> int   # Phase 06
Repository.revision_of(pk: str) -> int                                  # Phase 06
Repository.list_feedback_of_version(version_id: str) -> list[Feedback]  # Phase 08
tutorial_pk(slug: str) -> str                                           # Phase 05
Tutorial(slug, current_version, topic, feature_ids, status, successor, cluster_id)  # Phase 04
TutorialStatus.ACTIVE = "active" / TutorialStatus.RETIRED = "retired"   # Phase 03
SiteRenderer.render_version_page(tutorial, version, steps, content) -> str          # Phase 24
IngressError(message: str, fields: tuple[str, ...]) / PermanentError    # Phase 02
to_iso(dt: datetime) -> str                                             # Phase 02，naive datetime 一律拒絕
```

### Produces

```python
RETIRED_NOTICE = "此教學已退役，內容僅供歷史查閱。"   # 公開頁唯一的過期說明，Phase 57 直接 import

def resolve_successor(slug: str, successor: str | None, *, repository: Repository) -> str | None: ...

def retire_tutorial(
    slug: str,
    *,
    reason: str,
    successor: str | None,
    repository: Repository,
    now: datetime,
) -> Tutorial: ...

def assert_accepts_feedback(tutorial: Tutorial) -> None: ...
```

`RETIRED_NOTICE` 與三個函式同放 `src/training_kb/content.py`，是**公開頁唯一**的過期說明文字（00A 第 6.6 節）；[Phase 57](./57-Phase57-S3靜態教學站與回饋下載.md) 的完整退役頁 `from training_kb.content import RETIRED_NOTICE`，兩份文件不各寫一份字面值，改字只改這一處。`retire_tutorial` 的簽名由本 Phase 擁有，[Phase 52](./52-Phase52-Release-RETIRE與流程驗收.md) 會直接呼叫，不得改名或改參數順序；它對**已經是 `retired` 的教學是冪等的**：原樣回傳、不報錯、也不再寫一次（見第 7 節 Task 2）。`assert_accepts_feedback` 由 [Phase 42](./42-Phase42-Feedback與View固定匯入.md) 在建立 `Feedback` 之前呼叫，違反時丟 `IngressError(..., fields=("tutorial_version",))`，讓 Phase 42 直接轉成 `ImportResult(status="rejected", invalid_fields=("tutorial_version",))`，不必比對訊息字串。

**`revision_of` 不是本 Phase 產出。** `update_meta(..., expected_revision=...)` 需要一個取值來源，而 [Phase 06](./06-Phase06-Repository-Metadata與實體讀寫.md) 的 `get_meta` 會把 `PK`／`SK`／`entity`／`_revision` 這些保留屬性濾掉再交給嚴格模型，所以領域模型身上沒有 `revision`。依 00A 的裁決（D-27），`Repository.revision_of(pk) -> int` 由 **Phase 06 產出**，本 Phase 只是第一個消費者；`_revision` 是 item 上固定的屬性名。若實作到這裡發現 Phase 06 還沒有這個方法，回頭補在 Phase 06，不要在本 Phase 另外加一個同義方法。

## 6. 設計細節

後繼檢查固定順序，任何一關不過就回 `None`，**不丟例外**：

```text
successor is None ----------------------> None
        |
        v
successor == slug（自身）---------------> None
        |
        v
repository.get_tutorial(successor) 不存在 -> None
        |
        v
target.status != "active" --------------> None
        |
        v
target.current_version is None（沒有已發布版本，不可公開）-> None
        |
        v
沿 target.successor 往下走，回到 slug 或走到重複節點（循環）-> None
        |
        v
回傳 successor
```

鏈走訪使用 `visited` 集合，走到 `None` 就停；集合同時擋掉「A→B→C→B」這種不含起點的環。**本計畫選擇：** 不限制鏈長上限而用 `visited`，因為 MVP 的 Tutorial 數量很少，`visited` 比固定跳數更能精確描述「不形成循環」。

`retire_tutorial` 的寫入範圍固定只有兩個欄位：

| 欄位 | 動作 |
|---|---|
| `status` | 設為 `retired`；已是 `retired` 時不重寫。 |
| `successor` | **只在目前為空且新解析結果合法時寫入**；目前已有值時一律保持原值，不論新值是 `None` 還是另一個合法 slug（改後繼是維護者另一次明確決定，不是退役的副作用）。 |
| `current_version` | **不動**，讀者仍能讀到最後一個已發布版本。 |
| `VERSION` / `STEP` / S3 `.md` / `.diff` | **完全不動**，不刪除、不重寫、不產生新版本。 |
| 既有 `FEEDBACK` 與 `REFERS_TO` 邊 | **完全不動**，仍可被查詢與統計。 |

寫入用 [Phase 06](./06-Phase06-Repository-Metadata與實體讀寫.md) 的 `update_meta` compare-and-swap，`expected_revision` 取自 `revision_of(pk)`；revision 不符代表有人同時改了這篇，轉成可重試的技術錯誤，不靜默覆蓋。

**`reason` 與 `now` 去哪裡：** 兩者都**不寫進 `TUTORIAL` item**。`Tutorial` 只有 [Phase 04](./04-Phase04-十個邏輯實體模型.md) 的七個欄位，多塞一個 `retired_at` 或 `retired_reason` 會讓嚴格模型在下一次 `get_meta` 驗證失敗（00A 的 D-40）。`retire_tutorial` 只負責**驗證**它們（`reason` 去頭尾後不可為空；`now` 交給 `to_iso` 一起擋掉 naive datetime），實際紀錄由呼叫端寫進私有操作紀錄 `operations/<operation_id>/retire.json`：它是一個 **JSON 陣列**（一則 removed Release 可能命中多篇教學，單篇時就是長度 1 的陣列），每個元素固定是 `{"slug": ..., "reason": "release:r_88", "retired_at": "<to_iso(now)>", "successor": ...}`。[Phase 52](./52-Phase52-Release-RETIRE與流程驗收.md) 的 `retire_for_release` 是目前唯一的呼叫端，退役原因的落地由它負責；它的 `successor` 只來自維護者事先放好的 `operations/<operation_id>/successors.json`（`{slug: successor_slug}`，讀不到就是空 dict，對應決策 F54），不由本 Phase 猜。

公開頁只顯示**固定過期說明**與可點的後繼連結。**本計畫選擇：** 設計 §8.4 的敘述是「顯示過期原因與原文」，但同一節依據的決策 F19 寫的是「顯示過期說明與原文」，而設計 §13 明訂上游 ID 與執行紀錄屬私有資料；把 `release:<id>` 印在公開 HTML 會讓內部識別碼外流，讀者需要的資訊只是「這篇過期了、可以改看哪一篇」。因此本計畫採 F19 的「固定過期說明」，與 [Phase 57](./57-Phase57-S3靜態教學站與回饋下載.md) 的完整退役頁一致（該頁同樣不吃 `retired_reason` 欄位）。

公開頁的退役區塊（沿用 Phase 24 的最小 renderer，簽名不變）：

```text
<p class="retired">{RETIRED_NOTICE}</p>   <- 固定文字「此教學已退役，內容僅供歷史查閱。」
<p class="successor"><a href="../prepare-meeting/index.html">改看：準備會議</a></p>   <- successor 非空才輸出
```

連結是明確可點的提示，不做自動跳轉；`successor` 為空時完全不輸出第二行。所有文字與 slug 一律先 `html.escape`。完整的 retired 頁樣式、版本選擇與 diff 檢視留給 [Phase 57](./57-Phase57-S3靜態教學站與回饋下載.md)。

## 7. TDD Tasks

### Task 1：後繼合法性檢查

- [ ] **Step 1：建立失敗測試**

```python
@pytest.mark.parametrize(
    "candidate",
    ["meeting-summary", "not-exists", "already-retired", "never-published", "cycles-back"],
)
def test_resolve_successor_rejects_invalid_targets(candidate, repo):
    assert resolve_successor("meeting-summary", candidate, repository=repo) is None


def test_resolve_successor_accepts_active_published_other(repo):
    assert resolve_successor("meeting-summary", "prepare-meeting", repository=repo) == "prepare-meeting"
```

- [ ] **Step 2：執行並確認紅燈**

```bash
uv run pytest tests/unit/test_retire_tutorial.py -q
```

預期：FAIL，訊號包含 `cannot import name 'resolve_successor'`。

- [ ] **Step 3：建立最小實作**

```python
def resolve_successor(slug, successor, *, repository):
    if successor is None or successor == slug:
        return None
    target = repository.get_tutorial(successor)
    if target is None or target.status != "active" or target.current_version is None:
        return None
    visited = {slug, successor}
    cursor = target.successor
    while cursor is not None:
        if cursor in visited:
            return None
        visited.add(cursor)
        nxt = repository.get_tutorial(cursor)
        if nxt is None:
            return None
        cursor = nxt.successor
    return successor
```

`target.status != "active"` 用字串比較成立，因為 `TutorialStatus` 是值為小寫字串的 `StrEnum`（[Phase 03](./03-Phase03-識別碼列舉與內容草稿模型.md)）。

- [ ] **Step 4：補上兩層與三層循環 fixture，跑完整檔案確認綠燈**

`cycles-back` 直接指回 `meeting-summary`；另加 `A -> B -> C -> B` 的不含起點環，兩者都必須回 `None`。再加一個 `successor=None` 的案例，確認回 `None` 而不是丟例外。

```bash
uv run pytest tests/unit/test_retire_tutorial.py -q
```

- [ ] **Step 5：提交**

```bash
git add src/training_kb/content.py tests/unit/test_retire_tutorial.py
git commit -m "feat(content): 驗證退役教學的後繼"
```

### Task 2：退役保留歷史且不被後繼阻擋

- [ ] **Step 1：建立失敗測試**

```python
def test_retire_completes_even_when_successor_is_invalid(repo):
    before = snapshot_versions(repo, "meeting-summary")
    result = retire_tutorial(
        "meeting-summary", reason="release:r_88", successor="not-exists",
        repository=repo, now=NOW,
    )
    assert result.status == "retired"
    assert result.successor is None
    assert result.current_version == "meeting-summary@v2"
    assert snapshot_versions(repo, "meeting-summary") == before
    assert repo.objects["tutorials/meeting-summary/v2.md"] == before.markdown
    assert repo.versions_written == []
```

`snapshot_versions` 回一個同時可比較、又帶得出 `.markdown` 的小 dataclass；`repo.versions_written` 記的是這次呼叫期間新建的 `VERSION` item，必須是空的。

- [ ] **Step 2：執行並確認紅燈**

```bash
uv run pytest tests/unit/test_retire_tutorial.py -q
```

預期：FAIL，訊號包含 `cannot import name 'retire_tutorial'`。

- [ ] **Step 3：建立最小實作**

```python
def retire_tutorial(slug, *, reason, successor, repository, now):
    if not reason.strip():
        raise PermanentError("退役必須帶原因，交給呼叫端寫進 operation 紀錄")
    to_iso(now)                       # naive datetime 在這裡就被擋掉，不寫進 item
    pk = tutorial_pk(slug)
    tutorial = repository.get_tutorial(slug)
    if tutorial is None:
        raise PermanentError(f"找不到教學 {slug}")
    chosen = resolve_successor(slug, successor, repository=repository)
    changes: dict[str, object] = {}
    if tutorial.status != "retired":
        changes["status"] = "retired"
    if chosen is not None and tutorial.successor is None:
        changes["successor"] = chosen
    if changes:
        repository.update_meta(pk, changes, expected_revision=repository.revision_of(pk))
    retired = repository.get_tutorial(slug)
    if retired is None:
        raise PermanentError(f"{slug} 在退役寫入後讀不到，停止")
    return retired
```

`reason` 與 `now` 只做驗證，不進 `TUTORIAL` item；紀錄由呼叫端寫 `operations/<operation_id>/retire.json`（見第 6 節）。`changes` 為空時完全不呼叫 `update_meta`，這就是冪等：連退兩次不會多花一次條件寫入，也不會把 `_revision` 往上推。

- [ ] **Step 4：補上冪等與不覆蓋案例，跑完整檔案確認綠燈**

同一篇連退兩次結果相同且第二次 `repo.update_calls` 不增加；第二次帶 `successor=None` 不得把已寫入的合法後繼清成 `None`；第二次帶另一個合法 slug 也不得覆蓋既有值；`reason=" "` 丟 `PermanentError`；`now` 是 naive datetime 時拒絕。

```bash
uv run pytest tests/unit/test_retire_tutorial.py -q
```

- [ ] **Step 5：提交**

```bash
git add src/training_kb/content.py tests/unit/test_retire_tutorial.py
git commit -m "feat(content): 退役教學並保留歷史"
```

### Task 3：拒絕新回饋與退役頁顯示

- [ ] **Step 1：建立失敗測試**

```python
def test_retired_tutorial_rejects_new_feedback_but_keeps_old(repo):
    retire_tutorial("meeting-summary", reason="release:r_88", successor=None,
                    repository=repo, now=NOW)
    tutorial = repo.get_tutorial("meeting-summary")
    with pytest.raises(IngressError) as error:
        assert_accepts_feedback(tutorial)
    assert "tutorial_version" in error.value.fields
    assert [item.id for item in repo.list_feedback_of_version("meeting-summary@v2")] == ["f_12"]


def test_retired_page_shows_notice_and_optional_successor(renderer, fixtures):
    page = renderer.render_version_page(*fixtures.retired(successor="prepare-meeting"))
    assert 'class="retired"' in page and RETIRED_NOTICE in page
    assert "prepare-meeting" in page
    assert "release:r_88" not in page and "r_88" not in page
    assert 'class="successor"' not in renderer.render_version_page(*fixtures.retired(successor=None))
```

- [ ] **Step 2：執行並確認紅燈**

```bash
uv run pytest tests/unit/test_retired_page.py tests/integration/test_retired_feedback_rejected.py -q
```

預期：FAIL，訊號包含 `cannot import name 'assert_accepts_feedback'`。

- [ ] **Step 3：建立最小實作**

```python
def assert_accepts_feedback(tutorial: Tutorial) -> None:
    if tutorial.status == "retired":
        raise IngressError("已退役教學不接受新回饋", fields=("tutorial_version",))
```

`render_version_page` 在 `tutorial.status == "retired"` 時輸出 `RETIRED_NOTICE` 那一行（引用常數，不在 `site.py` 重抄字面值）；`tutorial.successor` 非空時再輸出一行連結。兩行的文字與 slug 一律先 `html.escape`，`active` 的教學兩行都不輸出。

- [ ] **Step 4：跑完整檔案確認綠燈**

再補三個案例：`active` 教學呼叫 `assert_accepts_feedback` 什麼都不做；退役後同版 `TutorialView` 仍可寫入（設計 §8.4 只擋回饋）；退役頁全文搜尋不得出現使用者 ID 或回饋原文。

```bash
uv run pytest tests/unit/test_retired_page.py -q
uv run pytest tests/integration/test_retired_feedback_rejected.py -q
```

- [ ] **Step 5：提交**

```bash
git add src/training_kb/content.py src/training_kb/site.py tests/unit/test_retired_page.py tests/integration/test_retired_feedback_rejected.py
git commit -m "feat(content): 退役頁提示與拒絕新回饋"
```

## 8. 驗收矩陣

| 路徑 | 輸入 | 預期資料結果 |
|---|---|---|
| Happy | successor 是 active 且已發布的別篇 | `status=retired`、`successor` 寫入、頁面出現一個可點連結。 |
| Happy | `successor=None` | `status=retired`、`successor=None`、頁面只有過期說明。 |
| Failure | successor 不存在 | `successor=None`，退役仍完成，不丟例外。 |
| Failure | successor 是自身 | `successor=None`，不建立自我導向。 |
| Failure | successor 已 retired 或尚未發布 | `successor=None`；不導向讀者看不到的內容。 |
| Failure | successor 會形成循環 | `successor=None`；測試涵蓋兩層與三層環。 |
| Failure | `update_meta` revision 不符 | 轉成可重試錯誤，不靜默覆蓋別人的修改。 |
| Failure | `reason` 是空字串或全空白 | `PermanentError`；不得在沒有原因的情況下退役。 |
| Failure | `now` 是 naive datetime | `to_iso` 拒絕；時間一律 aware UTC。 |
| Boundary | 對已 retired 的教學再退一次 | 冪等；零次 `update_meta`、不清掉既有 successor、不改 `current_version`。 |
| Boundary | 退役後匯入新回饋 | `IngressError` 指出 `tutorial_version`；既有回饋筆數不變。 |
| Boundary | 退役後匯入同版 `TutorialView` | 仍然成功；設計 §8.4 只擋回饋，不擋瀏覽紀錄。 |
| Privacy | 公開頁全文搜尋 | 找不到 `release:`、`r_88`、使用者 ID 或回饋原文。 |

人工驗收：退役前後各抓一次 `TUTORIAL`、`VERSION` item 與 `tutorials/<slug>/v<n>.md` 的 bytes 做 diff，除了 `status`、`successor` 與 `_revision` 之外必須完全相同；再用公開 URL 實際點一次後繼連結確認可讀。不能只看測試顯示 PASS。

## 9. 常見錯誤與停止條件

| 症狀 | 原因 | 修正／停止 |
|---|---|---|
| 找不到 successor 就不讓退役 | 把後繼當必填 | 停止：F19 明訂無後繼仍完成退役；改回寫 `None`。 |
| 退役時順手刪掉舊版本或 S3 全文 | 把 retired 當「清理」 | 停止：設計 §8.1／§8.4 要求保留歷史原文與版本。 |
| 資料寫成 `obsolete` | 混淆顯示文字與資料狀態 | 只寫 `retired`；`obsolete` 僅能出現在畫面文案。 |
| 後繼自動跳轉 | 想省讀者一次點擊 | 改成明確可點連結；連續跳轉會讓循環更難發現。 |
| Release payload 直接指定後繼 | 把來源事件當維護者 | 停止：successor 只能來自維護者輸入。 |
| 退役後還能送新回饋 | 匯入端沒呼叫檢查 | 在建立 `Feedback` 之前呼叫 `assert_accepts_feedback`。 |
| 把 `release:<id>` 印在公開頁 | 想顯示過期原因 | 內部識別碼留私有紀錄；公開只顯示固定說明。 |
| 在 `TUTORIAL` item 加 `retired_at`／`retired_reason` | 想把退役時間存起來 | 停止：嚴格模型只接受 Phase 04 的七個欄位（D-40）；寫進 `operations/<operation_id>/retire.json`。 |
| 退役也順手擋掉 `TutorialView` | 把「拒絕回饋」擴大成「停止收資料」 | 只擋 Feedback；瀏覽紀錄是重開票率的分母，擋掉指標會失真。 |

## 10. 來源與 Rule 對照

primary 與相關的分工依 [00B 需求覆蓋對照](./00B-需求覆蓋對照.md) 第 2、3.2 節。

- [依改版更新教學.feature](../../spec/features/依改版更新教學.feature)（縮寫 `REL`）
  - Rule 16：「RETIRE 將受影響教學標記為過期」→ **primary 在本 Phase**；Task 2 `test_retire_completes_even_when_successor_is_invalid` 直接斷言 `status == "retired"` 且歷史未變。[Phase 52](./52-Phase52-Release-RETIRE與流程驗收.md) 是在 release-update 流程中呼叫（相關）。
  - Rule 17：「RETIRE 的教學導向後繼 Tutorial」→ **primary 在本 Phase**；Task 1 的 successor 案例（自身、不存在、已退役、尚未發布、兩層環、三層環、`None`，加上一個合法的別篇）與 Task 3 的頁面斷言直接證明它；無後繼仍完成退役、不產生導向。
- [收集教學回饋.feature](../../spec/features/收集教學回饋.feature)（縮寫 `COL`）Rule 2：「已退役教學的既有版本拒絕新回饋」→ **相關（primary 在 [Phase 42](./42-Phase42-Feedback與View固定匯入.md)）**。Rule 原文說的是匯入時拒絕，入口在 Phase 42；本 Phase 提供 `retired` 狀態與 `assert_accepts_feedback` 這個判斷來源，Task 3 的測試保留為相關證據，不重複認領。
- [發布教學版本.feature](../../spec/features/發布教學版本.feature)（縮寫 `PUB`）：supporting Rule 4（primary 在 [Phase 24](./24-Phase24-單篇教學發布提交.md)）；退役不切換也不清空 `current_version`。
- 設計 §8.1：RETIRE 只改 `status`，保留歷史原文與版本。§8.4：資料只用 `retired`；無 successor 仍完成退役；設定時檢查存在、可公開、非自身且不形成循環；退役版本拒絕新回饋，原回饋仍可查閱。§13：回饋原文、身份與執行紀錄保持私有。§14.1：已 retired 的 Tutorial 不接受新回饋，歷史保留。§15 驗收表「退役」列：有／無後繼都能完成、保留原文、拒絕新回饋、無效後繼不建立循環導向。
- 設計 §19 的決策編號（D 是資料決策、F 是功能決策）：D21（`retired` 是唯一資料狀態，`obsolete` 只是顯示文字）、D22（successor 存在 Tutorial metadata，不另造 `SUCCESSOR` 邊）、F19（無後繼仍完成退役，顯示過期說明與原文但不產生導向）、F39（退役版本拒絕新回饋，既有回饋保留供歷史查詢）、F54（後繼由維護者選定既有 Tutorial，未選定時走無後繼分支）。

## 11. 完成清單

- [ ] `retire_tutorial`、`resolve_successor`、`assert_accepts_feedback` 簽名符合本文件；`revision_of` 消費自 [Phase 06](./06-Phase06-Repository-Metadata與實體讀寫.md)，本 Phase 沒有另外宣告一份。
- [ ] 四項後繼檢查（存在、active 且已發布、非自身、不循環）各有獨立測試。
- [ ] 後繼無效時 `successor=None`，退役仍然完成且不丟例外。
- [ ] 退役前後 `VERSION`、`STEP`、S3 `.md`／`.diff` 與既有回饋 byte-for-byte 相同。
- [ ] `TUTORIAL` item 只多了 `status`／`successor`／`_revision` 的變動，沒有 `retired_at`、`retired_reason` 這類新欄位。
- [ ] 退役後新回饋被拒並指出欄位，既有回饋仍查得到，同版 `TutorialView` 仍可匯入。
- [ ] 退役頁顯示常數 `RETIRED_NOTICE` 的固定過期說明（Phase 57 直接 import 同一個常數）；有合法後繼才輸出一個可點連結，且無自動跳轉。
- [ ] 同一篇連退兩次是冪等的：第二次不呼叫 `update_meta`、不覆蓋既有 `successor`，回傳結果與第一次相同。
- [ ] `REL` Rule 16、17 有直接 assertion；`COL` Rule 2 已標為相關（primary 在 Phase 42）。
- [ ] 公開頁沒有 `release:<id>`、上游 ID、使用者 ID 或回饋原文。
