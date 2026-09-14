# Phase 44：弱教學門檻與目標選取實作計畫

> **給實作者：** 依 checkbox 逐步執行；每個 Task 先建立失敗測試，再寫最小實作。執行時使用 `superpowers:executing-plans` 或同等逐項流程。

**目標：** 用三個同時成立的條件挑出弱教學，並把每個命中的版本包成 `WeakTarget` 交給診斷；只看 active Tutorial 的已發布 `current_version`。

**架構：** `select_weak_targets` 先列出所有 Tutorial，逐篇取 `current_version` 與該版截至本次執行的全部有效回饋，交給純函式 `is_weak` 判斷；門檻值全部來自 `Thresholds`，`ReviewMode` 只改樣本數門檻。這裡不呼叫模型、不建立版本，也不判斷證據是否處理過。

**技術：** Python 3.12、pytest、既有 `Repository` 查詢族群、Phase 02 `Thresholds`、Phase 43 的核定類別表。

## 全域限制

- 唯一主來源是 [Training KB 設計 §7.5、§11.2、§12.1、§19.2](../../design/training-kb.md)。
- 前置為 [Phase 43：Feedback 類別判定](./43-Phase43-Feedback類別判定.md)；資料面另需 [Phase 08：分頁查詢與一致讀取基礎](./08-Phase08-分頁查詢與一致讀取基礎.md) 的 `scan_entity` 與 `list_feedback_of_version`。前置未通過時停止。
- 下一階段是 [Phase 45：回饋診斷與命中步驟](./45-Phase45-回饋診斷與命中步驟.md)。
- 本階段不做：不呼叫模型、不建立或發布版本、不提出 candidate 規則、不判斷證據指紋是否已處理（那是 [Phase 46](./46-Phase46-REFINE精準改寫與證據去重.md)）、不計算展示用指標（那是 Phase 53／54）。
- `mode="demo"` 只是**明示隔離**的展示門檻，把樣本數從 10 放寬到 8；平均與同類門檻完全不變。任何情況下都不得把 demo 結果說成正式門檻已滿足。
- 與本 Phase 有關的 O1–O7 gate 狀態：O4 的時間邊界只影響 Phase 54 的重開票窗口，本階段的 `now` 只當「截至本次執行」的截止點；O7 未核定前，Demo 的八筆回饋仍是待核定合成資料。
- 以下程式檔均是實作時預計建立或修改；本計畫本身不代表它們已存在。

---

## 1. 你在整體流程的位置

```text
Phase 42/43 已保存並收斂類別的回饋
        |
        v
Phase 48 feedback-review 的 ListTargets task
        |
        v
[你在這裡] select_weak_targets(repository=..., mode=..., now=...)
        |
   active Tutorial？ -> 有 current_version？ -> published_at 非空？
        | 三者皆是                              | 任一否 --> 跳過該篇
        v
   該版截至 now 的全部有效回饋 -> avg / n / 同一核定類別筆數
        |
        v
   is_weak？ -- 否 --> 不產生 target（這是正常結果，不是錯誤）
        | 是
        v
   WeakTarget -> Phase 45 診斷 -> Phase 46 REFINE（證據去重在那裡）
```

## 2. 完成後看得到什麼

以設計 §11.2 的 A v1 八筆回饋（`f_12`、`f_15`、`f_19`、`f_23`、`f_27`、`f_31`、`f_34`、`f_40`，評分 2、2、3、3、3、3、3、4，全部類別「找不到按鈕」）執行：

```text
mode="demo"  -> avg = 23/8 = 2.875 < 3.5，n = 8 >= 8，同類 = 8 >= 5 -> 命中
   WeakTarget(tutorial_id="prepare-meeting", version_id="prepare-meeting@v1", category="找不到按鈕",
              feedback_ids=("f_12","f_15","f_19","f_23","f_27","f_31","f_34","f_40"))
mode="formal" -> n = 8 < 10 -> 不命中，回 ()
```

同一次執行中，A v2（平均 4.4）與尚未發布的版本都不會出現在結果裡；舊版 A v1 在 A v2 成為 `current_version` 之後也不再被檢視。

## 3. 名詞小抄

| 名詞 | 白話意思 |
|---|---|
| 弱教學 | 平均 `< 3.5`、樣本數達門檻、同一核定類別至少五筆，三者同時成立的版本。 |
| `ReviewMode` | `formal` 或 `demo`；只有樣本數門檻不同，其他條件一樣。 |
| 同一核定類別筆數 | 同一版本內，`category` 落在核定類別表的回饋中數量最多的那一類的筆數；`待分類` 不算。 |
| `WeakTarget` | 交給 Phase 45 的固定資料：教學、版本、命中的類別與該類全部證據 ID。 |
| `meta_only` | `Repository.scan_entity` 的開關，預設 `True` 代表只回每個實體的 `META` item，不回掛在同一個 PK 底下的關係邊。 |

## 4. 預計檔案

| 動作 | 路徑 | 責任 |
|---|---|---|
| 建立 | `src/training_kb/pipelines/feedback.py` | 本 Phase 是這支檔案的 owner（00A 第 3.2 節）：`ReviewMode`、`WeakTarget`、`is_weak`、`select_weak_targets`；Phase 45–48 之後只在同一支檔案上追加。 |
| 修改 | `src/training_kb/config.py` | 在 `Thresholds` 加上有預設值的 `weak_average: float = 3.5`（owner 仍是 Phase 02）。 |
| 測試 | `tests/unit/test_weak_threshold.py`、`tests/integration/test_weak_targets.py` | 三條件、兩種 mode 與四組邊界；只選 active 已發布 current_version、排序、跨版不混用。 |

## 5. 固定介面

### Consumes

```text
Phase 02：Thresholds（production_feedback=10、demo_feedback=8、recurring_category=5；weak_average 由本階段追加）、PermanentError
Phase 03／04：TutorialStatus.ACTIVE（StrEnum 成員大寫、值小寫）、Tutorial（slug、status、current_version）、TutorialVersion（version_id、published_at）、Feedback（id、rating、category、ts）
Phase 06：Repository.get_version(version_id) -> TutorialVersion | None
Phase 08：Repository.scan_entity(entity, *, consistent=True, meta_only=True) -> list[DynamoItem]、list_feedback_of_version(version_id) -> list[Feedback]、item_to_model(item, model) -> T（模組函式）
Phase 43：approved_categories(repository) -> frozenset[str]、PENDING_CATEGORY（值為 "待分類"）
```

`scan_entity` 回的是含 `PK`／`SK`／`entity`／`_revision` 的 raw item，**一律用 `item_to_model` 轉成模型**，不可直接 `Tutorial.model_validate(item)`（`StrictModel` 是 `extra="forbid"`，多一個 `PK` 就 `ValidationError`）；00A D-29 把 Phase 44 列為這個函式的消費者。`meta_only` 預設 `True`，只回 `SK == META` 的 item，所以 `scan_entity("TUTORIAL")` 不會混進 `TUTORIAL#` 底下的關係邊，本階段不必自己過濾，也**不要**把它改成 `False`。`PENDING_CATEGORY` 在程式裡不必特別判斷：`待分類` 不在 `approved` 裡，`_top_category` 的 `row.category in approved` 自然把它擋掉；列在 Consumes 是為了讓測試能直接引用同一個常數。

### Produces

```python
ReviewMode = Literal["formal", "demo"]

@dataclass(frozen=True)
class WeakTarget:
    tutorial_id: str
    version_id: str
    category: str
    feedback_ids: tuple[str, ...]

def is_weak(avg: float | None, n: int, top_category_count: int, *, mode: ReviewMode, thresholds: Thresholds) -> bool: ...
def select_weak_targets(*, repository: Repository, mode: ReviewMode, now: datetime, thresholds: Thresholds | None = None) -> tuple[WeakTarget, ...]: ...
```

`WeakTarget` 的四個欄位逐字對應 [Phase 45](./45-Phase45-回饋診斷與命中步驟.md) 的 Consumes，不可改名；`tutorial_id` 是 Tutorial 的裸 slug（例如 `prepare-meeting`），`version_id` 是裸版本 ID（例如 `prepare-meeting@v1`）。**`feedback_ids` 裡的每一個 ID 都必須屬於同一筆 `WeakTarget` 的 `category`**：它裝的是「這個版本、這個類別」的全部證據，不混入別類，也不混入 `待分類` 或 `category is None` 的回饋——Phase 45 的診斷就是針對這一類在問「哪幾步出問題」，混類會讓診斷指錯步驟。`thresholds` 是本階段新增的可選 keyword，缺值用 `Thresholds()`；`_average` 與 `_top_category` 是 module-private helper，不是跨模組 API。

## 6. 設計細節

三個條件是 AND，任一不成立就不是弱教學：

```text
+--------------------------+------------------+------------------+
| 條件                     | formal           | demo（明示隔離） |
+--------------------------+------------------+------------------+
| 該版平均評分             | < 3.5            | < 3.5            |
| 有效回饋筆數 n           | >= 10            | >= 8             |
| 同一核定類別筆數         | >= 5             | >= 5             |
+--------------------------+------------------+------------------+
   avg is None（零評分）-> 一律不是弱教學，不當成 0 分
```

- **只看 active Tutorial 的已發布 current_version。** `status != TutorialStatus.ACTIVE`（成員名大寫、值是小寫的 `active`）、`current_version is None`、或該版 `published_at is None` 都直接跳過。設計 §7.5 明講不掃舊版、也不做「上次檢視之後」的浮水印切分，所以每次都重算該版截至 `now` 的**全部**有效回饋。
- **未四捨五入。** 設計 §11.2：門檻用原始數值比較，顯示才取一位小數。`2.875` 顯示成 `2.9` 但比較用 `2.875`；`3.5` 不算弱，`3.49` 才算。
- **平均算法與 `n` 的分母必須跟 Phase 53 一模一樣。** 00A D-44：`rating is None` 的回饋不進分子也不進分母。本階段比 [Phase 53](53-Phase53-評分與負面回饋指標.md) 早，不能 import `analytics.ratings`，所以 `_average` 自己實作**同一套算法**（`sum(ratings) / len(ratings)`，沒有任何評分回 `None`），而 `n` 就是 `len(ratings)`——不是 `len(feedback)`。Phase 42 的入口強制 `rating` 必填，正常匯入的資料兩者相等；但種子與歷史匯入可能直接寫 item 而繞過入口，只要分母不同一套，Phase 53 顯示的平均與這裡判斷用的平均就會分岔。Phase 53 §1 已註明「`avg < 3.5` 的門檻判斷屬 Phase 44」，兩份文件必須同時維持這句。00A 第 6 節把 Phase 44 列為 `average_rating` 的消費者，指的是**做完 Phase 53 之後**：把 `_average` 換成 `from training_kb.analytics.ratings import average_rating` 的直接呼叫並刪掉本地副本，本階段的重複實作只是暫時的過渡，在那之前任何一邊改算法都必須同步另一邊。
- **同類只數核定類別。** `待分類` 與 `None` 不參與同類計數，也不進 `feedback_ids`；設計 §12.1 同樣把 `待分類` 排除在負面回饋之外。同一類別內的 ID 先去重再排序，讓重跑得到相同結果。
- **平手要有固定順序。** 兩個核定類別筆數相同時，取「筆數多者優先，其次類別名稱升序」；輸出的 target 依 `version_id` 升序。沒有固定順序時重送會得到不同 target，Phase 46 的證據指紋就不穩定。
- **`now` 是截止點，不重做的判斷也不在這裡。** 只排除 `ts` 晚於 `now` 的回饋（這與 Phase 54 的 O4 重開票窗口 `[p, p+14 天)` 是兩件事，不得互相借用）；`ts` 為 `None` 的回饋無法判斷是否落在截止點之前，一律排除（**本計畫選擇**；Phase 42 的匯入入口一定補上 `ts`，只有種子或歷史資料直接寫 item 才會出現）；「沒有新有效證據就不用同一批證據再產生新版」由 Phase 46 的 `evidence_fingerprint` 與 O2 操作紀錄負責，本階段每次都照實回報命中，否則無法分辨「這次沒有弱教學」與「這次跳過了」。

## 7. TDD Tasks

### Task 1：三條件與兩種 mode 的邊界

- [ ] **Step 1：建立失敗測試**

```python
TH = Thresholds()


@pytest.mark.parametrize(
    ("avg", "n", "top", "mode", "expected"),
    [
        (2.875, 10, 5, "formal", True),
        (2.875, 9, 5, "formal", False),
        (2.875, 8, 5, "demo", True),
        (2.875, 7, 5, "demo", False),
        (3.49, 10, 5, "formal", True),
        (3.5, 10, 5, "formal", False),
        (2.875, 10, 4, "formal", False),
        (2.875, 8, 8, "formal", False),
        (None, 10, 5, "formal", False),
    ],
)
def test_weak_thresholds(avg, n, top, mode, expected) -> None:
    assert is_weak(avg, n, top, mode=mode, thresholds=TH) is expected


def test_unknown_mode_is_rejected_instead_of_defaulting() -> None:
    with pytest.raises(PermanentError, match="mode"):
        is_weak(2.0, 20, 9, mode="loose", thresholds=TH)
```

- [ ] **Step 2：執行並確認紅燈**

```bash
uv run pytest tests/unit/test_weak_threshold.py -q
```

預期：FAIL，訊號包含 `cannot import name 'is_weak'`。

- [ ] **Step 3：建立最小實作**

```python
ReviewMode = Literal["formal", "demo"]


def is_weak(avg: float | None, n: int, top_category_count: int, *,
            mode: ReviewMode, thresholds: Thresholds) -> bool:
    if mode not in ("formal", "demo"):
        raise PermanentError(f"未知的 review mode：{mode}（只接受 formal 或 demo）")
    if avg is None:
        return False
    minimum = thresholds.production_feedback if mode == "formal" else thresholds.demo_feedback
    return (avg < thresholds.weak_average and n >= minimum
            and top_category_count >= thresholds.recurring_category)
```

- [ ] **Step 4：在 `Thresholds` 補門檻並跑完整檔案確認綠燈**

在 `src/training_kb/config.py` 的 `Thresholds` 加上 `weak_average: float = 3.5`。它有預設值，Phase 02 既有測試與 `load_settings` 都不受影響；三個門檻數字（3.5、10／8、5）不可寫死在判斷式裡，一律讀 `Thresholds` 的 `weak_average`、`production_feedback`／`demo_feedback`、`recurring_category`（00A 第 5.4 節；不得自創 `weak_min_feedback_formal` 這類新欄位名）。

```bash
uv run pytest tests/unit/test_weak_threshold.py tests/unit/test_config.py -q
```

- [ ] **Step 5：提交**

```bash
git add src/training_kb/config.py src/training_kb/pipelines/feedback.py tests/unit/test_weak_threshold.py
git commit -m "feat(feedback): 鎖定弱教學三條件與兩種門檻"
```

### Task 2：只選 active 的已發布 current_version

- [ ] **Step 1：建立失敗測試**

```python
def test_only_active_published_current_versions_are_selected(repository) -> None:
    # A：active，current=v1 已發布，八筆同類低分；B：active 但 current 未發布；
    # C：retired；D：active 但 current_version is None。
    targets = select_weak_targets(repository=repository, mode="demo", now=NOW)
    assert [target.version_id for target in targets] == ["prepare-meeting@v1"]
    assert targets[0].tutorial_id == "prepare-meeting"
    assert targets[0].category == "找不到按鈕"
    assert targets[0].feedback_ids == (
        "f_12", "f_15", "f_19", "f_23", "f_27", "f_31", "f_34", "f_40",
    )
    categories = {row.category for row in repository.list_feedback_of_version("prepare-meeting@v1")
                  if row.id in targets[0].feedback_ids}
    assert categories == {targets[0].category}      # 證據全屬同一類，沒有混類


def test_old_version_feedback_is_not_mixed_into_the_current_one(repository_with_v2) -> None:
    # A v1 的八筆低分仍在圖譜，但 current_version 已是 v2（平均 4.4、n=10）。
    assert select_weak_targets(repository=repository_with_v2, mode="demo", now=NOW) == ()
```

- [ ] **Step 2：執行並確認紅燈**

```bash
uv run pytest tests/integration/test_weak_targets.py -q
```

預期：FAIL，訊號包含 `cannot import name 'select_weak_targets'`。

- [ ] **Step 3：建立最小實作**

```python
@dataclass(frozen=True)
class WeakTarget:
    tutorial_id: str
    version_id: str
    category: str
    feedback_ids: tuple[str, ...]


def select_weak_targets(*, repository, mode, now, thresholds=None):
    limits = thresholds or Thresholds()
    approved = approved_categories(repository)
    targets: list[WeakTarget] = []
    for item in repository.scan_entity("TUTORIAL", consistent=True):  # meta_only 預設 True
        tutorial = item_to_model(item, Tutorial)
        if tutorial.status != TutorialStatus.ACTIVE or not tutorial.current_version:
            continue
        version = repository.get_version(tutorial.current_version)
        if version is None or version.published_at is None:
            continue
        feedback = repository.list_feedback_of_version(version.version_id)
        rated = [row for row in feedback if row.rating is not None]
        category, ids = _top_category(feedback, approved)
        if is_weak(_average(rated), len(rated), len(ids), mode=mode, thresholds=limits):
            targets.append(WeakTarget(tutorial.slug, version.version_id, category, ids))
    return tuple(sorted(targets, key=lambda target: target.version_id))
```

- [ ] **Step 4：補兩個 helper 並跑完整檔案確認綠燈**

```python
def _average(rated: Sequence[Feedback]) -> float | None:
    ratings = [row.rating for row in rated if row.rating is not None]
    if not ratings:
        return None
    return sum(ratings) / len(ratings)


def _top_category(feedback: Sequence[Feedback],
                  approved: frozenset[str]) -> tuple[str, tuple[str, ...]]:
    groups: dict[str, set[str]] = {}
    for row in feedback:
        if row.category in approved:
            groups.setdefault(row.category, set()).add(row.id)
    if not groups:
        return "", ()
    best = max(groups, key=lambda name: len(groups[name]))
    return best, tuple(sorted(groups[best]))
```

`_average` 與 Phase 53 的 `average_rating` 是同一套算法（00A D-44）：分母是有評分的筆數，沒有任何評分回 `None` 而不是 0。`_top_category` 只收 `row.category in approved` 的回饋，所以 `待分類` 與 `None` 既不進同類計數也不進 `feedback_ids`；同類 ID 先用 `set` 去重再排序，同一類的輸出才會逐字相同。這一版刻意留下兩個缺口交給 Task 3：`now` 還沒被用來過濾證據，`max` 在兩類筆數相同時會依 dict 的插入順序決定贏家。

```bash
uv run pytest tests/integration/test_weak_targets.py -q
```

- [ ] **Step 5：提交**

```bash
git add src/training_kb/pipelines/feedback.py tests/integration/test_weak_targets.py
git commit -m "feat(feedback): 選出 active 已發布版本的弱教學目標"
```

### Task 3：時間截止點、平手順序與分頁完整性

- [ ] **Step 1：建立失敗測試**

```python
# tests/unit/test_weak_threshold.py；fb(id, category) 產生 rating=2、ts=NOW 的 Feedback
APPROVED = frozenset({"找不到按鈕", "缺少資訊"})


def test_tie_break_prefers_the_smaller_category_name() -> None:
    rows = [fb(f"f_{i}", "缺少資訊") for i in range(1, 6)]
    rows += [fb(f"f_{i}", "找不到按鈕") for i in range(6, 11)]
    assert _top_category(rows, APPROVED)[0] == "找不到按鈕"


# tests/integration/test_weak_targets.py
def test_feedback_after_now_is_excluded(repository_with_future_feedback) -> None:
    # 與 Task 2 同一批資料，但 f_40 的 ts 落在 NOW 之後：n 掉到 7，demo 門檻不再成立。
    assert select_weak_targets(repository=repository_with_future_feedback, mode="demo", now=NOW) == ()


def test_tie_between_two_approved_categories_is_deterministic(tied_repository) -> None:
    # 「找不到按鈕」與「缺少資訊」各五筆，平均 2.0。
    first = select_weak_targets(repository=tied_repository, mode="demo", now=NOW)
    assert first == select_weak_targets(repository=tied_repository, mode="demo", now=NOW)
    assert (first[0].category, len(first[0].feedback_ids)) == ("找不到按鈕", 5)
```

第一個測試刻意把「缺少資訊」排在清單前面：Task 2 的 `max` 會回它，紅燈才**一定**出現，不必賭 DynamoDB 的回傳順序；整合測試只負責證明同樣的規則在真實查詢路徑上也成立。

- [ ] **Step 2：執行並確認紅燈**

```bash
uv run pytest tests/unit/test_weak_threshold.py tests/integration/test_weak_targets.py -q
```

預期：FAIL。`test_tie_break_prefers_the_smaller_category_name` 拿到「缺少資訊」；`test_feedback_after_now_is_excluded` 因為 Task 2 還沒用 `now` 過濾證據，仍然回傳一個 target。

- [ ] **Step 3：建立最小實作**

`select_weak_targets` 取回饋的那一行改成 `feedback = [row for row in repository.list_feedback_of_version(version.version_id) if row.ts is not None and row.ts <= now]`；`_top_category` 的選贏家改成下面這個版本：

```python
def _top_category(feedback: Sequence[Feedback],
                  approved: frozenset[str]) -> tuple[str, tuple[str, ...]]:
    groups: dict[str, set[str]] = {}
    for row in feedback:
        if row.category in approved:
            groups.setdefault(row.category, set()).add(row.id)
    if not groups:
        return "", ()
    best = min(groups, key=lambda name: (-len(groups[name]), name))
    return best, tuple(sorted(groups[best]))
```

`min` 配上 `(-筆數, 類別名)` 這個鍵就是「筆數多者優先、其次類別名稱升序」，不再依賴 dict 的插入順序。

- [ ] **Step 4：補分頁與退役案例並跑完整檔案確認綠燈**

`scan_entity` 與 `list_feedback_of_version` 都必須讀完所有分頁，中間空頁不能提前停止：用「第 2 頁為空、第 3 頁才有 A」的 fake table 驗證 A 仍被選到。再加兩個案例：一個 retired 但回饋滿足全部門檻的 Tutorial，預期不出現在結果中；一批 `category="待分類"` 的回饋，確認它既不進同類計數也不進 `feedback_ids`。

```bash
uv run pytest tests/unit/test_weak_threshold.py tests/integration/test_weak_targets.py -q
```

- [ ] **Step 5：提交**

```bash
git add src/training_kb/pipelines/feedback.py tests/unit/test_weak_threshold.py tests/integration/test_weak_targets.py
git commit -m "feat(feedback): 固定弱教學證據截止點與平手順序"
```

## 8. 驗收矩陣

| 路徑 | 輸入 | 預期資料結果 |
|---|---|---|
| Happy | A v1：avg 2.875、n 8、同類 8，`mode="demo"` | 一個 `WeakTarget`，八個 ID 排序後輸出。 |
| Happy | 同一批資料，`mode="formal"` | 回 `()`；n 8 未達 10。 |
| Failure | 沒有任何評分；或 retired、current 未發布、`current_version is None` | 一律回 `()`；不得把零評分當 0 分。 |
| Boundary | n 9／10（formal）、7／8（demo）、avg 3.49／3.5、同類 4／5 | 只有 10、8、3.49、5 命中。 |
| Boundary | 兩類各五筆平手 | 兩次執行結果相同，取類別名稱升序者。 |
| Boundary | 舊版 v1 低分但 current 已是 v2 | 回 `()`；不混入舊版回饋。 |

人工驗收：把選出的 `WeakTarget` 與 DynamoDB 內該版的回饋逐筆對照，手算平均與同類筆數，確認程式沒有四捨五入、也沒有把 `待分類` 算進去；再用 `mode="formal"` 重跑同一批 Demo 資料，確認結果是空的。不能只看測試顯示 PASS。

## 9. 常見錯誤與停止條件

| 症狀 | 原因 | 修正／停止 |
|---|---|---|
| Demo 八筆在正式模式也命中 | 門檻寫死或 mode 沒傳下去 | 一律從 `Thresholds` 取值；停止 Phase 48 的正式排程直到修正。 |
| 平均 2.9 被拿來和 3.5 比 | 先四捨五入再比較 | 比較用未四捨五入的值，顯示才取一位小數。 |
| 舊版低分回饋讓新版變弱 | 用 Tutorial 的全部回饋而非 current 版 | 只讀 `current_version` 的回饋，補跨版測試。 |
| `待分類` 讓同類達到五筆 | 同類計數沒有先過濾核定類別 | 依設計 §7.5 只數核定類別，`待分類` 不算。 |
| 每天對同一批證據重複產生新版，或分頁中途空頁就停 | 把「不重做」誤當本階段責任；沒讀完 `LastEvaluatedKey` | 去重交 Phase 46 的證據指紋與 O2 紀錄；依 Phase 08 讀完所有分頁並補空頁測試。 |

## 10. 來源與 Rule 對照

- [定期檢視回饋.feature](../../spec/features/定期檢視回饋.feature)（本文件縮寫 `REV`，見 [00B 第 1 節](00B-需求覆蓋對照.md)）
  - 相關（primary 在 [Phase 48](./48-Phase48-Feedback-Review排程流程.md)）Rule 1：「Periodic Feedback Review 每日執行」→ 「每日」這件事由 Phase 48 的排程與 CDK template 直接斷言；本階段只斷言「每次執行都取 active 教學的已發布 `current_version`，並用該版截至 `now` 的全部有效回饋重算」（Task 2、Task 3），屬支援證據。
  - **primary** Rule 2：「弱教學的版本平均評分必須小於 3.5」→ Task 1 的 `3.49`／`3.5` 邊界案例。
  - **primary** Rule 3：「弱教學的版本回饋樣本數必須至少為 10」→ Task 1 的 `9`／`10` 與 demo `7`／`8` 案例，並在文件與測試名稱明示 demo 是隔離門檻。
  - **primary** Rule 4：「弱教學必須具有 recurring Feedback Category」→ Task 1 的同類 `4`／`5` 案例與 Task 3 的平手案例。
  - 相關 Rule 5–9：診斷與無有效步驟的 primary 在 [Phase 45](./45-Phase45-回饋診斷與命中步驟.md)，REFINE 只改命中步驟與 reason 格式的 primary 在 [Phase 46](./46-Phase46-REFINE精準改寫與證據去重.md)，唯一提出 Authoring Rule 的 pipeline 的 primary 在 [Phase 47](./47-Phase47-Candidate規則提出與溯源.md)；本階段只提供 `WeakTarget`，不寫這五條的 assertion。
- 設計 §7.5：弱教學三條件、Demo 只改 n、每日只看已發布 current_version、不做浮水印切分；§11.2：A v1 的 `23/8 = 2.875` 與「指標判斷使用未四捨五入的數值」；§12.1：平均以該版有效回饋計、零評分為 null 不是 0、`待分類` 不算負面。
- 設計 §19.2 的五條功能決策（`F20`～`F24` 是**設計文件自己的**決策編號，與 [00A 第 8 節](00A-共用契約與名詞.md) 的 `D-01`～`D-52` 不是同一套）：`F20`「正式維持 n>=10，Demo 使用明示且隔離的 n>=8」→ Task 1 的兩組樣本數案例；`F21`「同一類別至少 5 筆，與候選規則門檻一致」→ `recurring_category`；`F22`「只檢視 current_version，使用該版截至本次執行的全部有效回饋」→ Task 2、Task 3；`F23`「同一批回饋不可再次觸發 REFINE，必須有新的有效證據」與 `F24`「診斷找不到有效步驟時記錄並保留回饋」→ **不屬本階段**，分別由 Phase 46 的證據指紋與 Phase 45／46 負責，本階段每次都照實回報命中。
- [DynamoDB Query 分頁](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/Query.Pagination.html)：必須以 `LastEvaluatedKey` 讀到沒有下一頁為止，空的一頁不代表沒有資料。

## 11. 完成清單

- [ ] `ReviewMode`、`WeakTarget`、`is_weak`、`select_weak_targets` 簽名與本文件一致，`WeakTarget` 欄位與 Phase 45 的 Consumes 逐字相同。
- [ ] 三個條件同時成立才算弱教學；`avg is None` 不命中。
- [ ] 門檻值全部來自 `Thresholds`，`weak_average` 以有預設值的欄位加入，不破壞 Phase 02。
- [ ] 只選 active Tutorial 的已發布 `current_version`、不混入舊版或未發布版；邊界 9／10、7／8、3.49／3.5、4／5 各有直接 assertion 且比較未四捨五入。
- [ ] `feedback_ids` 全部屬於同一筆 `WeakTarget` 的 `category`（有直接 assertion），`待分類` 與 `None` 不進去。
- [ ] 平手類別與輸出順序固定、重跑結果完全相同；`scan_entity` 與 `list_feedback_of_version` 讀完所有分頁，空頁不早停。
- [ ] `REV` Rule 2、3、4 標為 primary 且各有直接 assertion；Rule 1 標為「相關（primary 在 Phase 48）」、Rule 5–9 標為相關；未把 demo 門檻說成正式門檻已滿足。
