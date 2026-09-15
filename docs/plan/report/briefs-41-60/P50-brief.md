# P50 brief — Release 步驟反查與 Safety Net

文件：`docs/plan/unfinish/50-Phase50-Release步驟反查與Safety-Net.md`（W0 已更新，commit `a177a38`）
波次：**W1（P49 ∥ P50 同時進行，同檔不同區段）**

## 1. 單一交付物與停止點
- **交付物**：把 P27 的反查包成 `StepHit` 座標（`find_release_hits`）＋ 觸發判斷（`needs_safety_net`）＋ 補漏候選與逐版模型確認（`safety_net`）。
- **停止點**：兩個函式都回 `tuple[StepHit, ...]`（依 `(slug, number)` 升序）。**不改寫步驟、不配版號、不建版、不發布、不退役、不更新 aliases**。

## 2. 已存在、直接重用
- `src/training_kb/pipelines/release.py` — controller 預建的 docstring 空殼（`5f8a430`）；`Edit` 追加 `# ---- Phase 50 ----`。
- `src/training_kb/repository.py:Repository.find_current_published_steps_referencing(feature_id) -> list[TutorialStep]`（**P27，反查的唯一實作**）：
  - B 方向＝基表 `scan_entity("TUTORIAL")` 一致讀取 → `_is_current_published` → `get_steps` 比 `feature_id`；
  - A 方向＝`query_by_target` 候選，只留 `REFERENCES` 且起點 `STEP#`；不是 current 已發布就跳過；**是 current 已發布卻在基表讀不到 → `PermanentError(f"GSI 候選在基表讀不到對應步驟：{pk}")`**；
  - 回傳已依 `(version_sort_key(version_id), number)` 排序。
- `scan_entity(entity, *, consistent=True, meta_only=True)`（`meta_only` 預設 True）、`get_steps(version_id)`（依 `number` 升序）、`get_version`、`get_tutorial`、模組函式 `item_to_model`。
- `src/training_kb/content.py:parse_version_id(value) -> (slug, number)`；`vectors.py:cosine`。
- `src/training_kb/writing/schemas.py:StepConfirmation`（`required: ["confirmed_step_numbers", "reason"]`、`additionalProperties: False`、numbers 是 `integer >= 1`；空陣列合法）。
- `src/training_kb/writing/prompts.py:_as_data`（`html.escape(text, quote=False)`）與 `<source_data>` 分區契約（D-67）。檔內目前只有 `prompt_write_tutorial`、`prompt_name_gap`。
- `models.py:TutorialStatus.ACTIVE`／`TutorialStep(tutorial_version, number, type, text, feature_id)`；`keys.py:META`；`errors.py:ContentError`（`PermanentError` 子類）。
- P27 的測試做法可抄：`tests/unit/test_graph_queries.py` 的 `GraphRepository(Repository)` fixture——**被測的是真的 `Repository`**，只有 Phase 06／08 原語換成記憶體字典。`three_tutorials` 照這個做，另加 `gsi_hide(pk)` 與 `clear_steps(version_id)`。

## 3. 要新增／修改的東西
`src/training_kb/pipelines/release.py`（**同波次 P49 也在改**）：
```python
SAFETY_NET_CANDIDATES = 5

@dataclass(frozen=True)
class StepHit:
    slug: str; version_id: str; number: int      # 欄位順序固定（00A §6.9）

def find_release_hits(feature_id: str, *, repository: Repository) -> tuple[StepHit, ...]: ...
def needs_safety_net(release: Release, feature: Feature, hits: Sequence[StepHit]) -> bool: ...
def safety_net(release: Release, *, repository: Repository, writer: Writer,
               operation_id: str) -> tuple[StepHit, ...]: ...
```
`src/training_kb/writing/prompts.py`（**owner P17，00A §3.2 列 P39／P40／P43／P45–P47／P50／P51 都會追加** → 只 Edit 自己的區段）：
```python
def prompt_safety_net_confirm(version_id: str, steps: Sequence[TutorialStep],
                              names: Sequence[str]) -> tuple[str, str]: ...
```
測試檔（00A §3.3）：`tests/unit/test_release_hits.py`、`tests/unit/test_release_safety_net.py`、`tests/integration/test_release_hits_consistency.py`。

**相依 P49**：`needs_safety_net` 要 `normalize_feature_name`（owner P49，同檔）。**不得自己複製一份**——先做 Task 1（不需要它），Task 2 開工前確認 P49 的區段已在檔內。

## 4. Task 順序與紅燈訊號
1. **Task 1｜`find_release_hits` 只是型別轉換＋排序**
   - RED：`uv run pytest tests/unit/test_release_hits.py -q` → `cannot import name 'find_release_hits'`
   - GREEN：只回 A `@v2` 第 3 步（歷史 `@v1`、未發布 `share-summary@v2` 都不在）；`gsi_hide` 後仍回同一筆；`clear_steps` 後 `pytest.raises(PermanentError, match="STEP#prepare-meeting@v2#3")`。
2. **Task 2｜`needs_safety_net`（F16 四種組合）**
   - RED：`uv run pytest tests/unit/test_release_safety_net.py -q` → `cannot import name 'needs_safety_net'`
   - GREEN：`(renamed, alias 命中, 有 hits) → False`；其餘三種 → True／False 照表；純函式、零次 `embed`。
3. **Task 3｜候選排序、逐版確認、空結果**
   - RED：同檔 → `cannot import name 'safety_net'`
   - GREEN：`99` 被丟棄、兩次 `generate_json`（node 都是 `safety_net_confirm`）、一次只放一個版本的步驟文字；全未確認回 `()`；`reason` 只有空白 → `ContentError`。
   - 再跑 `uv run pytest tests/integration/test_release_hits_consistency.py -q`（moto）。
4. 收尾：`ruff check`／`ruff format --check`／`mypy`／`uv run pytest tests -q -W error`。

## 5. 00B primary Rule → 測試
| Rule | 說明 | 測試 |
|---|---|---|
| `REL` 5 | by_target 反查只選引用該 Feature 的步驟 | `test_release_hits.py::test_only_current_published_steps_are_hit` |
| `REL` 6 | 反查為零或重大改名時向量補漏 | `test_release_safety_net.py::test_safety_net_trigger_follows_f16` |
| `REL` 7 | 疑似命中交給 Claude 確認 | `test_release_safety_net.py::test_safety_net_confirms_per_version_and_validates_numbers` |
| `REL` 12 | 未引用的教學維持 KEEP | `test_release_hits.py` Happy 案例（B、C 零 `StepHit`）；流程層 P52 再驗 |

## 6. 風險與陷阱
- **不得重寫 GSI 邏輯**（D-38）：`find_release_hits` 就是「轉型＋排序」幾行。另寫一份 `query_by_target` 篩選＝違規。
- **`PermanentError` 原樣上拋**，不接起來改回 `()`；補邊是 P28 的事。
- 共用 `fake_writer` 沒有 `scores`／`default_reply`／`json_calls`（它記的是 **dict**，不是有 `.user`／`.node` 屬性的物件）。**自己在測試檔內定義區域 fixture**，且**不要與 P49 共用**（同波次並行）。
- `tests/unit/conftest.py` 依 R3.6 **只有 P55 能改**。
- 每個候選版本各一次 `generate_json`：`confirmed_step_numbers` 只有裸編號，跨版會分不清誰的第 3 步。prompt 要寫明「是教學裡從 1 起算的步驟 `number`，不是候選名次、不是 0-based index」（00A §3.3）。
- 模型回不存在的編號 → **丟棄、不重問**（P18 對照表把 `StepConfirmation` 標為不走 correction）。
- 步驟文字是不可信文字 → 一律 `_as_data` 包進 `<source_data>`，**用 `prompts.py` 模組內那一份**，不自創分區名稱（D-67）。
- `embed` 次數與「目前已發布步驟總數」成正比，每次 `safety_net` 都重算；F45 要求每次 attempt 都計入 `CallTrace`。
- moto 的 GSI 沒有真實落後 → 「GSI 延遲」只能用 `gsi_hide` 模擬；真實證據移交 P52。
- **O5 BLOCKED** → `safety_net` 只有假 writer 綠燈；真實 AWS 上 `SafetyNet` 節點走 Catch（P52 保存證據）。

## 7. 需要裁決的點 → 建議裁決
1. **`needs_safety_net` 的 `kind` 比較寫法**？→ 用 `release.kind is not ReleaseKind.RENAMED`（`ReleaseKind` 是 `StrEnum`，與 `"renamed"` 也相等，但 enum 比較清楚且 mypy 友善）。
2. **候選排序的 tie-break**？→ 照文件：`(-score, slug, number, version_id)` 排序後取前 5；分數相同時 slug 升序、number 升序，重跑 byte 相同。
3. **`safety_net` 要不要自己先跑 `find_release_hits` 取聯集**？→ **不要**。`safety_net` 只回補漏證據，聯集由呼叫端（P52 的 `task_safety_net`）做 `set(direct) | set(net)`；文件 §7 Task 3 的聯集測試就寫在呼叫端語意上。
4. **`prompt_safety_net_confirm` 的 system 常數命名**？→ `_SAFETY_NET_SYSTEM`，放在自己的區段，與 `_TUTORIAL_SYSTEM`／`_GAP_SYSTEM` 同風格。

## 8. 對 AWS 的實際操作
**無。** 整合測試跑 moto（`tests/integration/conftest.py`，region `us-west-2`，`by_target` 是 KEYS_ONLY GSI）。
真實帳號的 `aws dynamodb query --index-name by_target --region us-east-1` 與 `get-item --consistent-read` 已寫進 **P52 §6 可實證路徑表**；`safety_net` 的真實 Bedrock 證據因 **O5 BLOCKED** 取不到。
