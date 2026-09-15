# P44 brief — 弱教學門檻與目標選取

## 1. 單一交付物與停止點
- **交付物**：`pipelines/feedback.py` 的 `ReviewMode`／`WeakTarget`／`is_weak`／`select_weak_targets`——三條件 AND 選出 active 教學 current 已發布版的弱教學，包成 `WeakTarget`。
- **停止點**：回傳 `tuple[WeakTarget, ...]` 就結束；不呼叫模型、不寫任何 item／物件、不判斷證據是否處理過（那是 P46）、不算展示指標（P53/54）。

## 2. 已存在、直接重用
- `src/training_kb/config.py:10` `Thresholds` — **六個欄位全在**（`weak_average=3.5`、`production_feedback=10`、`demo_feedback=8`、`recurring_category=5`）。**不要改 config.py。**
- `src/training_kb/repository.py:539` `scan_entity(entity, *, consistent=True, meta_only=True) -> list[DynamoItem]` — 已自動只回 `SK == META`，不必自己濾邊；已讀完所有分頁。
- `src/training_kb/repository.py:378` `get_version(version_id) -> TutorialVersion | None`；`:375` `get_tutorial(slug)`；`:579` `list_feedback_of_version(version_id) -> list[Feedback]`（依 ID 升序，三重過濾後逐筆一致讀取）。
- `src/training_kb/repository.py:152` `item_to_model[T: StrictModel](item, model) -> T` — 模組函式；`StrictModel` 是 `extra="forbid"`，一定要用它轉。
- `src/training_kb/models.py:38` `TutorialStatus`、`:143` `Tutorial(slug, current_version, topic, feature_ids, status, successor, cluster_id)`、`:173` `TutorialVersion(... published_at)`、`:347` `Feedback(id, tutorial_version, rating, category, comment, user, ts)`。
- `src/training_kb/errors.py:8` `PermanentError`。
- `src/training_kb/pipelines/feedback.py` — controller 預建空殼（commit `5f8a430`），只 Edit。
- fixture：`tests/unit/conftest.py` 的 `fake_writer`／`RecordingWriter`（本 Phase 不用 Writer，但別撞名）；`tests/conftest.py` 的 `aws` marker 自動 skip。

## 3. 要新增／修改的東西
**只改一支檔：`src/training_kb/pipelines/feedback.py`（W1 三人併行，區段 `# ---- Phase 44 ----`）**

本 Phase **擁有**（別人不得動）：`ReviewMode`、`WeakTarget`、`is_weak`、`select_weak_targets`、`_average`、`_top_category`。
本 Phase **不得碰**（同波次 P45／P47 的）：`DiagnosisResult`、`DIAGNOSE_NODE`、`diagnose_weak`、`_validated_items`、`CandidateGroup`、`MIN_CANDIDATE_FEEDBACK`、`PROPOSE_NODE`、`candidate_groups`、`candidate_rule_id`、`propose_candidate`、`_require_rule_text`、`_require_step_type`、`_evidence_comments`。W2/W3 的 P46／P48 名稱同樣不碰。

00A §6.9 canonical 簽名：
```python
ReviewMode = Literal["formal", "demo"]
@dataclass(frozen=True)
class WeakTarget:
    tutorial_id: str; version_id: str; category: str; feedback_ids: tuple[str, ...]
def is_weak(avg: float | None, n: int, top_category_count: int, *,
            mode: ReviewMode, thresholds: "Thresholds") -> bool: ...
def select_weak_targets(*, repository: "Repository", mode: ReviewMode, now: datetime,
                        thresholds: "Thresholds | None" = None) -> tuple[WeakTarget, ...]: ...
```
新檔：`tests/unit/test_weak_threshold.py`、`tests/integration/test_weak_targets.py`（平放，00A §3.3）。
**不改**：`config.py`、`writing/*`、`infra/*`。

## 4. Task 順序與紅燈訊號
1. **Task 1（三條件 × 兩 mode 邊界）**
   `uv run pytest tests/unit/test_weak_threshold.py -q` → `ImportError: cannot import name 'is_weak'`。
   綠燈後 `uv run pytest tests/unit/test_weak_threshold.py tests/unit/test_config.py -q`。
2. **Task 2（只選 active 已發布 current_version）**
   `uv run pytest tests/integration/test_weak_targets.py -q` → `cannot import name 'select_weak_targets'`。
3. **Task 3（`now` 截止點、平手順序、分頁空頁）**
   `uv run pytest tests/unit/test_weak_threshold.py tests/integration/test_weak_targets.py -q`
   → 平手測試拿到「缺少資訊」（`max` 依插入順序）；`test_feedback_after_now_is_excluded` 仍回一個 target。
收尾：`uv run ruff check src tests infra`、`uv run ruff format --check src tests infra`、`uv run mypy`、`uv run pytest tests -q -W error`（基線 924 passed / 23 skipped / 11 xfailed）。

## 5. 00B primary Rule 與測試檔
| Rule | 內容 | 測試 |
|---|---|---|
| `REV` 2（primary） | 版本平均 < 3.5 | `tests/unit/test_weak_threshold.py` 的 3.49／3.5 |
| `REV` 3（primary） | 樣本數 >= 10（Demo 隔離 8） | 同檔 9／10、7／8 |
| `REV` 4（primary） | 必須有 recurring category | 同檔 4／5 與平手案例 |
| `REV` 1 | 每日執行 → **相關**，primary 在 P48（00B §3.2 已裁決） | 只斷言「每次取 current 已發布版重算」 |

## 6. 風險與陷阱
- **`Thresholds.weak_average` 已存在**（Phase 02 commit `16a3639`）。文件 §4／Task 1 Step 4 與 00A §6.9 都還寫「本 Phase 追加」，已在文件加註；**別再改 config.py**，也別 `git add` 它。
- **P43 尚未實作**：`approved_categories(repository)`／`PENDING_CATEGORY` 會在 `src/training_kb/ingress.py`（00A §3.2）。P43 未合併 → import 直接紅燈。開工前確認。
- `Feedback` 有 D-66 的 `carries_signal`（rating/category/comment 至少一項）與 `rating_is_strict_int`（拒 `bool`、限 1..5）。造「零評分」fixture 時要給 `category` 或 `comment`。
- `bool` 是 `int` 子類；`rating=True` 已被模型層擋掉，但自己算平均時別假設一定是 int。
- `_average` 的分母是**有評分**的筆數（D-44），`n = len(rated)` 不是 `len(feedback)`；P53 完成後要換成 `from training_kb.analytics.ratings import average_rating`（目前 `analytics/` 只有 `status_writer.py`）。
- 平手用 `min(groups, key=lambda name: (-len(groups[name]), name))`，不要用 `max`（依 dict 插入順序）。
- `scan_entity` 預設 `meta_only=True`，**不要**改成 `False`（會混進關係邊，`item_to_model` 直接 `ValidationError`）。
- gate：O2 PASS／O3 FAIL／O5 BLOCKED 都不阻擋本 Phase（不呼叫模型、不寫入、不發布）。O7 未到 → Demo 結果只能說「待核定合成資料」。

## 7. 需要裁決的點 → 建議裁決
- `ts is None` 的回饋是否排除？→ **排除**（文件已寫「本計畫選擇」），照做並在報告寫明。
- 00A §6.9 P44 那一列說 `weak_average` 由本 Phase 加 → **視為過時敘述**，不改 00A（W0 不得改 00A），在 Phase 報告 §6 寫一行請 controller 統一處理。
- `_average` 暫時本地實作（P53 之前）→ **照做**，在函式 docstring 寫明「P53 完成後改 import `average_rating`」。

## 8. 對 AWS 的實際操作
無。`tests/integration/test_weak_targets.py` 用記憶體／fake table，**不標 `@pytest.mark.aws`**（本 Phase 不連真實 AWS）。
