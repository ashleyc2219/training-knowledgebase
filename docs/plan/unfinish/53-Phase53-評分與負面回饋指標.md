# Phase 53：評分與負面回饋指標實作計畫

> **給實作者：** 依 checkbox 逐步執行；每個 Task 先建立失敗測試，再寫最小實作。執行時使用 `superpowers:executing-plans` 或同等逐項流程。

**目標：** 由原始 Feedback 重算每版平均評分、跨版等權平均與負面回饋 ID 集合，讓設計 §11.2 的 2.875、4.4、8、2 完全可由資料重現。

**架構：** Analytics 是獨立 Lambda 的責任，不是第四條教學 pipeline。本 Phase 只做**純函式**：輸入 `list[Feedback]` 與核定類別集合，輸出數值與 ID 集合；讀取由 Phase 08 的 `list_feedback_of_version` 負責，寫入規則狀態由 Phase 55 負責。

**技術：** Python 3.12、Pydantic v2 的 `Feedback` 模型、標準函式庫 `decimal`、pytest。

## 全域限制

- 唯一主來源是 [Training KB 設計 §11.2、§12.1、§12.3](../../design/training-kb.md)；跨 Phase 名稱以 [00A 共用契約與名詞](00A-共用契約與名詞.md) 第 6.10 節為準，Rule 歸屬以 [00B 需求覆蓋對照](00B-需求覆蓋對照.md) 第 2.11、2.9 節為準。
- 前置為 [Phase 52：Release RETIRE 與流程驗收](./52-Phase52-Release-RETIRE與流程驗收.md)。前置未通過時停止。
- 下一階段是 [Phase 54：重開票與呼叫規則指標](./54-Phase54-重開票與呼叫規則指標.md)。
- 本階段不做：不計算重開票、不計 Bedrock 呼叫、不判定規則狀態、不寫入任何 DynamoDB item、不呼叫模型。
- 本階段不決定弱教學。`avg < 3.5` 的門檻判斷屬 [Phase 44](./44-Phase44-弱教學門檻與目標選取.md) 的 `is_weak`；這裡只提供可重算的平均值。
- 核定問題類別表由 [Phase 43](./43-Phase43-Feedback類別判定.md) 的 `approved_categories(repository)`（讀 `CONFIG#feedback_categories`）提供；本 Phase 只當唯讀參數收下，不擴充、不猜測，也不把 `PENDING_CATEGORY`（待分類）當負面。
- 與本 Phase 有關的 gate：O7 種子尚未經維護者核定，因此「2.875／4.4／8／2 可重算」只能以本 Phase 的自含 fixture 宣稱，不可寫成 Demo 種子已核定；O4 窗口與規則狀態分別待 Phase 54、Phase 55 處理。以下程式檔均是實作時預計建立或修改。

---

## 1. 你在整體流程的位置

```text
FEEDBACK#f_12 .. FEEDBACK#f_110（原始資料，永不改寫）
        |  Repository.list_feedback_of_version(version_id)
        v
+-----------------------------------------------------------+
| [你在這裡] average_rating / cross_version_average          |
|            negative_feedback_ids / format_average          |
+-----------------------------------------------------------+
        |                              |
        v                              v
Phase 54 VersionMetrics        Dashboard「每版評分與回饋數」
        |
        v
Phase 55 evaluate_batch（前後平均嚴格提高才可能啟用規則）
```

指標只從原始回饋重算。任何預先算好的數字都只能當展示備援，不能回寫成資料來源。

## 2. 完成後看得到什麼

輸入 `prepare-meeting@v1` 的八筆回饋（`f_12`、`f_15`、`f_19`、`f_23`、`f_27`、`f_31`、`f_34`、`f_40`，評分依序 2、2、3、3、3、3、3、4，類別全為「找不到按鈕」）與 `prepare-meeting@v2` 的十筆（`f_101`、`f_102` 為 2 分且「缺少資訊」，`f_103`～`f_110` 各 5 分且類別為空），可觀察結果為：

```text
average_rating(v1)  -> 2.875      format_average(2.875) -> "2.9"
average_rating(v2)  -> 4.4        cross_version_average([2.875, 4.4]) -> 3.6375
negative_feedback_ids(v1, APPROVED)
    -> {"f_12","f_15","f_19","f_23","f_27","f_31","f_34","f_40"}   長度 8
negative_feedback_ids(v2, APPROVED) -> {"f_101","f_102"}           長度 2
```

一筆評分都沒有的版本回傳 `None`，畫面顯示「尚無評分」，不是 0.0。

## 3. 名詞小抄

| 名詞 | 白話意思 |
|---|---|
| 有效評分 | `rating` 是 1 到 5 的整數；`None` 代表這筆沒有評分，不參與平均。 |
| 每版平均 | 同一個 `tutorial_version` 的有效評分總和除以有效評分筆數。 |
| 跨版等權 | 先算每一版的平均，再讓每版權重相同地平均；不是把所有回饋混在一起算。 |
| 核定問題類別 | 維護者核定過的類別表，初始為「找不到按鈕」與「缺少資訊」；「待分類」不屬於它，不計負面。 |
| 負面回饋數 | 命中「低分」或「核定問題類別」的 **Feedback ID 集合大小**，同一筆只算一次。 |
| primary／相關 | 00B 的用語：primary 代表本 Phase 必須寫出這條 Rule 的直接斷言；相關代表只引用或不破壞它，直接斷言在別的 Phase。 |

## 4. 預計檔案

| 動作 | 路徑 | 責任 |
|---|---|---|
| 新增 | `src/training_kb/analytics/__init__.py` | 建立 `analytics` 套件入口並匯出本 Phase 的四個名稱（00A D-26：這個檔在本 Phase 之前沒有任何 Phase 建立，owner 是本 Phase）。 |
| 新增 | `src/training_kb/analytics/ratings.py` | `average_rating`、`cross_version_average`、`negative_feedback_ids`、`format_average`。 |
| 測試 | `tests/unit/test_rating_metrics.py` | 八筆／十筆重算、空資料、待分類與去重。 |

## 5. 固定介面

### Consumes

```text
Feedback(id: str, tutorial_version: str, rating: int | None, category: str | None,
         comment: str | None, user: str, ts: datetime | None)      # Phase 04
Repository.list_feedback_of_version(version_id: str) -> list[Feedback]   # Phase 08
approved_categories(repository: Repository) -> frozenset[str]   # Phase 43，讀 CONFIG#feedback_categories
DEFAULT_FEEDBACK_CATEGORIES: frozenset[str]                     # Phase 43，{找不到按鈕, 缺少資訊}
PENDING_CATEGORY: str                                           # Phase 43，"待分類"
```

`Feedback` 模型層已擋掉 `bool` 與 1..5 以外的 `rating`（Phase 04 的 `rating_is_strict_int`），也要求每筆至少帶 rating、category、comment 其中一項（`carries_signal`）。本 Phase 不重做這兩層驗證，但測試 fixture 必須守得住，否則連物件都建不起來。

### Produces

```python
from collections.abc import Iterable, Sequence

def average_rating(feedback: Iterable["Feedback"]) -> float | None: ...
def cross_version_average(values: Sequence[float | None]) -> float | None: ...
def negative_feedback_ids(
    feedback: Iterable["Feedback"], approved: frozenset[str]
) -> frozenset[str]: ...
def format_average(value: float | None) -> str: ...
```

`average_rating` 與 `cross_version_average` 回傳未四捨五入的浮點數；只有 `format_average` 會產生顯示字串。後續 Phase 的門檻比較一律使用未四捨五入的值。

## 6. 設計細節

兩個函式的判斷順序固定如下，不可互相合併：

```text
average_rating                     negative_feedback_ids
  每一筆 Feedback                     每一筆 Feedback
        |                                   |
  rating is None ?                   rating <= 2 ? --+
    是 -> 跳過                              |        |
    否 -> 累加、分母 +1              category         +--> 加入 ID 集合
        |                            in approved ? --+
  分母 == 0 ?                               |
    是 -> None（尚無評分）            兩者皆否 -------> 不加入
    否 -> 總和 / 分母
```

三個重點：

| 重點 | 為什麼（設計 §12.1 原文） |
|---|---|
| `None` 不等於 0 | 「無評分為 null，顯示尚無評分；不當成 0 分」。當 0 會讓沒人評分的版本看起來比 1 分還糟，也會讓 Phase 55 誤判「評分嚴格提高」。 |
| 集合不是加總 | 「同筆同時命中只算一次」。`f_101` 同時是 2 分與「缺少資訊」，兩條件各加一次會得到 4 而不是 2；回傳固定 `frozenset[str]`，呼叫端沒有機會重複相加。 |
| 等權不是加權 | 收到的是每版已算好的平均再取算術平均，A v1 八筆與 A v2 十筆權重相同；`None` 代表那版沒有可比較的評分，全部 `None` 就回 `None`。 |

顯示用 `decimal.Decimal` 加 `ROUND_HALF_UP`：2.875 剛好落在 2.8 與 2.9 中間，不同策略會得到不同結果，而設計 §11.2 要求顯示 **2.9**，所以策略必須被測試釘住。`rating` 的 `bool` 已由 [Phase 04](./04-Phase04-十個邏輯實體模型.md) 的模型層拒絕（`True` 是 `int` 子類別，不擋會變成 1 分），本 Phase 只加一筆案例確認模型層真的擋住。

**與 Phase 44 的平均必須是同一套算法（00A 第 8 節 D-44）。** Phase 44 排在本 Phase 之前，當時還不能 import `analytics.ratings`，所以它的 module-private `_average` 自己寫了同一套公式：分母是**有評分**的筆數，`rating is None` 不進分子也不進分母，沒有任何評分回 `None`。**本 Phase 完成後，Phase 44 的 `_average` 應改為直接呼叫 `average_rating`**，避免兩份實作各自演化；在改完之前，任何一邊調整分母都要同時改另一邊，否則 Phase 44 判定用的平均與這裡顯示的平均會分岔。

## 7. TDD Tasks

### Task 1：每版平均與「尚無評分」

- [ ] **Step 1：建立失敗測試**

```python
import pytest

from training_kb.analytics.ratings import average_rating, format_average
from training_kb.models import Feedback

V1 = "prepare-meeting@v1"
V2 = "prepare-meeting@v2"


def fb(fid, rating, category=None, version=V1):
    return Feedback(id=fid, tutorial_version=version, rating=rating,
                    category=category, comment=None, user=f"u_{fid}", ts=None)


def test_average_rating_reproduces_design_v1_and_v2():
    v1 = [fb("f_12", 2), fb("f_15", 2), fb("f_19", 3), fb("f_23", 3),
          fb("f_27", 3), fb("f_31", 3), fb("f_34", 3), fb("f_40", 4)]
    v2 = [fb("f_101", 2, version=V2), fb("f_102", 2, version=V2)]
    v2 += [fb(f"f_{n}", 5, version=V2) for n in range(103, 111)]
    assert average_rating(v1) == pytest.approx(2.875)
    assert average_rating(v2) == pytest.approx(4.4)
    assert format_average(average_rating(v1)) == "2.9"


def test_average_rating_without_any_rating_is_none_not_zero():
    # Phase 04 的 carries_signal 要求每筆至少帶一項訊號，所以沒有評分時給類別。
    assert average_rating([]) is None
    assert average_rating([fb("f_1", None, "待分類"), fb("f_2", None, "待分類")]) is None
    assert format_average(None) == "尚無評分"
```

- [ ] **Step 2：執行並確認紅燈**

```bash
uv run pytest tests/unit/test_rating_metrics.py::test_average_rating_reproduces_design_v1_and_v2 -q
```

預期：FAIL，訊號包含 `cannot import name 'average_rating'`。

- [ ] **Step 3：建立最小實作**

```python
from collections.abc import Iterable
from decimal import ROUND_HALF_UP, Decimal

from training_kb.models import Feedback


def average_rating(feedback: Iterable[Feedback]) -> float | None:
    ratings = [item.rating for item in feedback if item.rating is not None]
    if not ratings:
        return None
    return sum(ratings) / len(ratings)


def format_average(value: float | None) -> str:
    if value is None:
        return "尚無評分"
    quantized = Decimal(str(value)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    return str(quantized)
```

- [ ] **Step 4：跑完整檔案確認綠燈**

```bash
uv run pytest tests/unit/test_rating_metrics.py -q
```

預期：兩個測試皆 PASS；`2.875` 未被提前四捨五入成 `2.9` 再回傳。

- [ ] **Step 5：提交**

```bash
git add src/training_kb/analytics/__init__.py src/training_kb/analytics/ratings.py tests/unit/test_rating_metrics.py
git commit -m "feat(analytics): 重算每版平均評分"
```

### Task 2：跨版等權平均

- [ ] **Step 1：建立失敗測試**

```python
from training_kb.analytics.ratings import cross_version_average


def test_cross_version_average_weights_each_version_equally():
    assert cross_version_average([2.875, 4.4]) == pytest.approx(3.6375)
    assert cross_version_average([2.875, None, 4.4]) == pytest.approx(3.6375)
    assert cross_version_average([None, None]) is None
    assert cross_version_average([]) is None
    # 按筆數加權會得到 (23 + 44) / 18 約 3.7222；等權公式不得等於它
    assert cross_version_average([2.875, 4.4]) != pytest.approx(67 / 18)
```

- [ ] **Step 2：執行並確認紅燈**

```bash
uv run pytest tests/unit/test_rating_metrics.py::test_cross_version_average_weights_each_version_equally -q
```

預期：FAIL，訊號包含 `cannot import name 'cross_version_average'`。

- [ ] **Step 3：建立最小實作**

```python
from collections.abc import Sequence


def cross_version_average(values: Sequence[float | None]) -> float | None:
    present = [value for value in values if value is not None]
    if not present:
        return None
    return sum(present) / len(present)
```

- [ ] **Step 4：跑完整檔案確認綠燈**

```bash
uv run pytest tests/unit/test_rating_metrics.py -q
```

預期：全部 PASS，包含「不等於加權結果」那一行。

- [ ] **Step 5：提交**

```bash
git add src/training_kb/analytics/ratings.py tests/unit/test_rating_metrics.py
git commit -m "feat(analytics): 以版本等權計算跨版平均"
```

### Task 3：負面回饋 ID 聯集去重

`fb` 與 `V1`／`V2` 是 Task 1 在同一個測試檔案定義的 helper，本 Task 直接使用，不重新定義。

- [ ] **Step 1：建立失敗測試**

```python
from training_kb.analytics.ratings import negative_feedback_ids

APPROVED = frozenset({"找不到按鈕", "缺少資訊"})
V1_RATINGS = [("f_12", 2), ("f_15", 2), ("f_19", 3), ("f_23", 3),
              ("f_27", 3), ("f_31", 3), ("f_34", 3), ("f_40", 4)]


def test_negative_ids_union_is_deduplicated_by_feedback_id():
    v1 = [fb(fid, rating, "找不到按鈕") for fid, rating in V1_RATINGS]
    assert len(negative_feedback_ids(v1, APPROVED)) == 8


def test_negative_ids_skip_unclassified_and_high_rating():
    v2 = [fb("f_101", 2, "缺少資訊", V2), fb("f_102", 2, "缺少資訊", V2)]
    v2 += [fb(f"f_{n}", 5, None, V2) for n in range(103, 111)]
    v2.append(fb("f_200", 5, "待分類", V2))
    assert negative_feedback_ids(v2, APPROVED) == frozenset({"f_101", "f_102"})
```

- [ ] **Step 2：執行並確認紅燈**

```bash
uv run pytest tests/unit/test_rating_metrics.py::test_negative_ids_union_is_deduplicated_by_feedback_id -q
```

預期：FAIL，訊號包含 `cannot import name 'negative_feedback_ids'`。

- [ ] **Step 3：建立最小實作**

```python
from collections.abc import Iterable

from training_kb.models import Feedback


def negative_feedback_ids(
    feedback: Iterable[Feedback], approved: frozenset[str]
) -> frozenset[str]:
    hits: set[str] = set()
    for item in feedback:
        low = item.rating is not None and item.rating <= 2
        flagged = item.category is not None and item.category in approved
        if low or flagged:
            hits.add(item.id)
    return frozenset(hits)
```

- [ ] **Step 4：補三個邊界案例並跑完整檔案**

三個案例分別釘住：`rating=None` 但類別已核定（仍算負面，且不可因 `None <= 2` 拋 `TypeError`）、`rating=2` 但類別是「待分類」（低分條件獨立成立）、同一 ID 在輸入清單重複出現（集合仍只有一個）。

```python
def test_negative_ids_cover_three_independent_boundaries():
    rows = [fb("f_301", None, "找不到按鈕"),   # 沒有評分，但類別已核定
            fb("f_302", 2, "待分類"),          # 待分類，但低分條件獨立成立
            fb("f_303", 3, "缺少資訊"),        # 不低分，但類別已核定
            fb("f_304", 1, "缺少資訊")]
    rows.append(rows[-1])                      # 同一筆重複出現
    assert negative_feedback_ids(rows, APPROVED) == frozenset(
        {"f_301", "f_302", "f_303", "f_304"})
```

```bash
uv run pytest tests/unit/test_rating_metrics.py -q
```

預期：全部 PASS，且沒有 `TypeError`。

- [ ] **Step 5：提交**

```bash
git add src/training_kb/analytics/ratings.py tests/unit/test_rating_metrics.py
git commit -m "feat(analytics): 以 Feedback ID 集合計算負面回饋"
```

## 8. 驗收矩陣

| 路徑 | 輸入 | 預期資料結果 |
|---|---|---|
| Happy | 設計 §11.2 的 A v1 八筆／A v2 十筆 | 平均 `2.875`（顯示 `2.9`）與 `4.4`；負面 8 與 2。 |
| Happy | `[2.875, 4.4]` | `cross_version_average == 3.6375`，不等於加權的 3.7222。 |
| Boundary | 版本無任何 `rating` | 回 `None`，`format_average` 顯示「尚無評分」。 |
| Boundary | `rating=2` 且 `category="待分類"`；`rating=None` 且 `category="缺少資訊"` | 兩者都仍計負面，且不因 `None` 比較而拋錯。 |
| Failure | 同一筆同時低分且屬核定類別 | 集合長度加 1，不是加 2。 |
| Failure | `rating=True`（`bool`） | Phase 04 模型層拒絕；本 Phase 不得把它讀成 1 分。 |

人工驗收：拿測試輸出的負面 ID 集合，逐一回查 `FEEDBACK#<id>` 的 `rating` 與 `category`，確認每個 ID 至少命中一個條件，且沒有「待分類」被算進去。只看長度等於 8 或 2 不算完成。

## 9. 常見錯誤與停止條件

| 症狀 | 原因 | 修正／停止 |
|---|---|---|
| 空版本顯示 0.0 分 | 用 `sum(...) / max(len(...), 1)` 或預設 0 | 回傳 `None`；停止 Phase 55，否則會誤判「評分嚴格提高」。 |
| 負面數變成 10 而不是 8 | 兩個條件各計一次後相加 | 改回 ID 集合聯集；確認回傳型別是 `frozenset`。 |
| 平均顯示 2.8 | 四捨五入策略未釘死 | 固定 `Decimal` 加 `ROUND_HALF_UP`，保留釘住 `"2.9"` 的測試。 |
| 跨版平均是 3.72 | 把所有回饋混成一池加權 | 先每版再等權；設計 §12.1 明寫不可加權。 |
| `None <= 2` 拋 `TypeError` | 先比較再判斷 `None` | 先檢查 `rating is not None`。 |
| 建立 fixture 就拋 `ValidationError` | rating、category、comment 全給 `None` | Phase 04 的 `carries_signal` 要求至少一項；沒有評分的案例改給類別或留言。 |
| 門檻用四捨五入後的值比較 | 把顯示值回填給 `is_weak` | 門檻一律吃未四捨五入的 float；顯示只在最外層。 |
| 把「待分類」算成負面 | 用「category 非空」當條件 | 條件是「屬核定類別表」，不是「有值」。 |
| Phase 44 與這裡平均不同 | 兩份實作各自演化 | 依 00A D-44 對齊分母；本 Phase 完成後改由 Phase 44 呼叫 `average_rating`。 |
| 說「2.875 已由核定種子重算」 | 把自含 fixture 當 O7 證據 | 只能說程式邏輯通過；O7 由 Phase 56 關閉。 |

## 10. 來源與 Rule 對照

Rule 原文逐字取自 `.feature` 原檔；primary／相關的歸屬依 [00B 第 2.11、2.9、3.1、3.2 節](00B-需求覆蓋對照.md)。

- [檢視學習指標.feature](../../spec/features/檢視學習指標.feature)（00B 縮寫 `MET`）
  - **primary** Rule 1「平均評分以每個 TutorialVersion 的 rating 計算」→ Task 1 的兩個測試直接斷言每版計算與「沒有有效評分回 `None`」的語意；Task 2 斷言跨版等權。
  - **primary** Rule 2「負面 Feedback 數計入 rating 不超過 2 或 category 屬負面的回饋」→ Task 3 的三個測試直接斷言聯集去重、「待分類」不計，以及兩個條件各自獨立成立。
  - Rule 6「規則效果比較套用與未套用版本的評分及同題重開票率差」→ **相關**：本 Phase 只提供評分那一半，重開票率在 Phase 54，兩者相減與判定在 [Phase 55](./55-Phase55-規則驗證與狀態轉移.md)（00B 第 3.1 節裁決 primary 為 Phase 55，該 Task 補上前本文件不得自稱擁有者）。
  - Rule 10「Demo 指標以 seeded data 展示」→ **相關（primary 在 [Phase 56](./56-Phase56-O7核定Demo種子資料.md)）**：本 Phase 以自含 fixture 重現 2.9／4.4／8／2，種子檔案與維護者核定紀錄屬 Phase 56，本 Phase 不得宣稱 O7 已完成。
- [收集教學回饋.feature](../../spec/features/收集教學回饋.feature)（00B 縮寫 `COL`，不寫 `FDB`）
  - Rule 5「Feedback Category 必須屬於核定類別表或待分類」→ **相關（primary 在 [Phase 43](./43-Phase43-Feedback類別判定.md)）**：`approved` 參數只接受 Phase 43 載入的核定表，本 Phase 不自行擴充，也不把「待分類」當負面。
  - Rule 10「同一使用者對同一版本的每次新提交都計一筆」→ **相關（primary 在 [Phase 42](./42-Phase42-Feedback與View固定匯入.md)）**：平均的分母以 Feedback ID 為單位，不以 user 去重。
- 設計 §11.2（八筆與十筆完整資料與 2.875／4.4／8／2）、§12.1（平均、等權、負面集合與空資料語意）、§12.3（指標是觀察結果，不得為配合表格改數字）。
- 設計 §19 決策：D12（只有評分也有效）、D13（可擴充核定類別表，初始兩類）、D14（每次新提交 ID 各計一筆）、F43（所有已核定問題類別都屬負面，未分類不因 category 計入，`rating<=2` 仍獨立計入）、F44（先算每版平均再等權）、F46（Demo 指標由完整 seeded 資料實時計算，2.9／4.4 是必須能重現的目標）、F52（版本沒有任何有效評分時顯示尚無評分、內部值為 null）。
- 00A 裁決：D-26（`analytics/__init__.py` 由本 Phase 建立）、D-44（平均算法與 Phase 44 一致）。

## 11. 完成清單

- [ ] `average_rating`、`cross_version_average`、`negative_feedback_ids`、`format_average` 簽名與本文件、00A 第 6.10 節一致。
- [ ] A v1 八筆重算出 2.875，A v2 十筆重算出 4.4，皆由測試斷言。
- [ ] 負面回饋為 ID 集合，A v1 得 8、A v2 得 2，同筆不重複計。
- [ ] 無有效評分回傳 `None`，顯示「尚無評分」，沒有任何路徑產生 0.0。
- [ ] 跨版平均先每版再等權，並有測試證明不等於加權結果。
- [ ] 顯示四捨五入策略被測試釘住，門檻比較仍使用未四捨五入的值。
- [ ] 與 Phase 44 的平均分母一致（D-44），且已記下「Phase 44 改呼叫 `average_rating`」這筆後續工作。
- [ ] 本 Phase 未寫入任何 DynamoDB item、未呼叫模型、未改變規則狀態。
- [ ] 沒有把自含 fixture 的綠燈說成 Demo 種子已核定或 O7 已通過。
