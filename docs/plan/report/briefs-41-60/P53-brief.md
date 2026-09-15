# P53 brief — 評分與負面回饋指標

## 1. 單一交付物與停止點
- **交付物**：`src/training_kb/analytics/ratings.py` 的四個純函式，讓設計 §11.2 的 2.875／4.4／8／2 完全由原始 `Feedback` 重算。
- **停止點**：四個函式綠燈、`tests/unit/test_rating_metrics.py` 全過、全套 `-W error` 綠；**不碰 DynamoDB、不呼叫模型、不判規則狀態、不決定弱教學**。

## 2. 已存在、直接重用
| file:name | 用途 |
|---|---|
| `src/training_kb/models.py::Feedback` | `rating_is_strict_int`（`mode="before"`，擋 `bool`、限 1–5）、`carries_signal`（rating/category/comment 至少一項）已生效，不重做 |
| `src/training_kb/repository.py::Repository.list_feedback_of_version(version_id)` | `-> list[Feedback]`，依 `id` 升序；邊存在但基表讀不到丟 `PermanentError` |
| `src/training_kb/analytics/__init__.py` | **已由 P40 建**成 docstring-only 空殼（owner 仍是 P53） |
| `src/training_kb/config.py::Thresholds.weak_average = 3.5` | 已存在，P44 的門檻不必再加欄位 |
| `src/training_kb/pipelines/__init__.py` | house style 參照：套件入口「不做 re-export，只留一條 import 路徑」 |
- 測試 fixture：**沒有**現成的可用；`tests/unit/conftest.py` 只有 `RecordingWriter`／`fake_writer`，而且 00A §3.3 記它的修改者只有 **P55**，本 Phase 不得動。helper 全寫在 `test_rating_metrics.py` 內。

## 3. 要新增／修改的東西
| 動作 | 路徑 | 內容 |
|---|---|---|
| 新增 | `src/training_kb/analytics/ratings.py` | 00A §6.10 的四個簽名，逐字照抄：<br>`def average_rating(feedback: Iterable["Feedback"]) -> float \| None`<br>`def cross_version_average(values: Sequence[float \| None]) -> float \| None`<br>`def negative_feedback_ids(feedback: Iterable["Feedback"], approved: frozenset[str]) -> frozenset[str]`<br>`def format_average(value: float \| None) -> str` |
| 新增 | `tests/unit/test_rating_metrics.py` | 00A §3.3 指定的檔名；basename 目前未被占用 |
| **不動** | `src/training_kb/analytics/__init__.py` | 本 Phase 是 owner，裁決「維持 docstring-only、不 re-export」（見 §7） |
- **同波（W1）另一位是 P54**：它只建 `analytics/reopen.py`／`rules_metrics.py`／`version.py`／`handlers/analytics.py` 與改 `infra/training_kb_stack.py`。依 `__init__.py` 的裁決，**兩邊沒有任何共用檔**。

## 4. Task 順序與紅燈訊號
1. **Task 1 每版平均＋「尚無評分」**
   - RED：`uv run pytest tests/unit/test_rating_metrics.py -q` → `ImportError: cannot import name 'average_rating' from 'training_kb.analytics.ratings'`（其實是 `ModuleNotFoundError: training_kb.analytics.ratings`，兩者都算紅燈訊號）
   - GREEN：`uv run pytest tests/unit/test_rating_metrics.py -q`；斷言 `average_rating(v1) == approx(2.875)`、`(v2) == approx(4.4)`、`format_average(2.875) == "2.9"`、`average_rating([]) is None`、`format_average(None) == "尚無評分"`
2. **Task 2 跨版等權**
   - RED：`uv run pytest tests/unit/test_rating_metrics.py::test_cross_version_average_weights_each_version_equally -q` → `cannot import name 'cross_version_average'`
   - GREEN：`3.6375`，且 `!= approx(67/18)`（3.7222 的加權版）
3. **Task 3 負面 ID 聯集去重**
   - RED：`uv run pytest tests/unit/test_rating_metrics.py::test_negative_ids_union_is_deduplicated_by_feedback_id -q` → `cannot import name 'negative_feedback_ids'`
   - GREEN：v1 得 8、v2 得 `{"f_101","f_102"}`；三個邊界（`rating=None` + 核定類別、`rating=2` + 待分類、同 ID 重複）不拋 `TypeError`
4. **收尾 gate**：`uv run pytest tests -q -W error`（基線 924 passed / 23 skipped / 11 xfailed，本 Phase 只會增加 passed）、`uv run ruff check src tests infra`、`uv run ruff format --check src tests infra`、`uv run mypy`
5. **提交**：`git add src/training_kb/analytics/ratings.py tests/unit/test_rating_metrics.py`（**不要** `git add src/training_kb/analytics/`，那會帶到別人的檔），commit 訊息補 COMMON R8 的兩行 trailer

## 5. 00B primary Rule 與對應測試
| Rule | 對應測試（`tests/unit/test_rating_metrics.py`） |
|---|---|
| `MET` Rule 1「平均評分以每個 TutorialVersion 的 rating 計算」（**primary**） | `test_average_rating_reproduces_design_v1_and_v2`、`test_average_rating_without_any_rating_is_none_not_zero`、`test_cross_version_average_weights_each_version_equally` |
| `MET` Rule 2「負面 Feedback 數計入 rating ≤ 2 或 category 屬負面」（**primary**） | `test_negative_ids_union_is_deduplicated_by_feedback_id`、`test_negative_ids_skip_unclassified_and_high_rating`、`test_negative_ids_cover_three_independent_boundaries` |
- **相關（不是 primary，別在報告裡認領）**：`MET` 6（primary P55）、`MET` 10（primary P56）、`COL` 5（primary P43）、`COL` 10（primary P42）、`REV` 2「弱教學平均 < 3.5」（primary P44）。

## 6. 風險與陷阱
- **P43／P44 都還沒實作**（同批 41–60）。本 Phase 的函式只吃 `frozenset[str]`，測試自備 `APPROVED = frozenset({"找不到按鈕", "缺少資訊"})`，**不 import P43 任何名稱** → 不被擋。
- **D-44 的收斂是同批內協調**：P44 尚未實作，本 Phase **不去改 P44 的檔**，只在報告記「P44 落地後改 `import average_rating`」。
- **`format_average` 的四捨五入**：`Decimal(str(value)).quantize(Decimal("0.1"), ROUND_HALF_UP)`。用 `Decimal(value)`（不經 `str`）會拿到二進位誤差版本，2.875 可能變 2.8。
- **`None <= 2`**：先 `rating is not None` 再比較，否則 `TypeError`。
- **`0.0` 陷阱**：`sum(...) / max(len(...), 1)` 這種寫法會讓沒人評分的版本看起來 0 分，並讓 P55 誤判「評分嚴格提高」。回 `None`。
- **mypy strict 涵蓋 `src`**：四個函式都要完整型別註記；`Iterable`／`Sequence` 從 `collections.abc` import（ruff 的 `UP` 規則會擋 `typing.Iterable`）。
- **`-W error`**：pytest 不得有任何 warning。
- 浮點：`23/8 == 2.875`、`44/10 == 4.4`、`(2.875+4.4)/2 == 3.6375` 都剛好成立，`pytest.approx` 只是保險。

## 7. 需要裁決的點 → 建議裁決
1. **`analytics/__init__.py` 要不要 re-export？** → **不要。維持 docstring-only。** 理由：(a) `pipelines/__init__.py` 已立下同一套 house style；(b) P54／P55／P56／P58 的測試片段**全部**用子模組路徑，沒有一處 `from training_kb.analytics import ...`；(c) P53 與 P54 同波，兩邊都改這支檔會直接撞 R3。已寫進 Phase 53 文件 §4 與現況核對區塊。
2. **P44 的 `_average` 誰去收斂？** → 本 Phase **不改**，只在報告列為後續；由 controller 在 P44 實作時指派（P44 先落地就留本地副本，P53 先落地就直接 import）。

## 8. 對 AWS 的實際操作
- **無。** 本 Phase 是純函式，不連 AWS、不部署、不跑 integration。不需要 `aws` marker 測試，也不產生任何 AWS 證據。
