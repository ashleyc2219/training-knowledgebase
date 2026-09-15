# P49 brief — Release 功能定位與 Alias

文件：`docs/plan/unfinish/49-Phase49-Release功能定位與Alias.md`（W0 已更新，commit `8ecce63`）
波次：**W1（P49 ∥ P50 同時進行，同檔不同區段）**

## 1. 單一交付物與停止點
- **交付物**：`pipelines/release.py` 裡的三層 Feature 定位（`locate_feature`）＋ 全有或全無的 alias 更新（`update_feature_aliases`）。
- **停止點**：`locate_feature` 回 `Feature | None`、`update_feature_aliases` 回新的 `Feature`。**不反查步驟、不建版、不發布、不退役、不呼叫 Claude**。

## 2. 已存在、直接重用
- `src/training_kb/pipelines/release.py` — controller 預建的 **docstring 空殼**（`5f8a430`）。只用 `Edit` 追加 `# ---- Phase 49 ----`。
- `src/training_kb/repository.py`
  - `Repository.find_feature_by_name_or_alias(name) -> Feature | None`（P27；先比 `name` 再比 `aliases`；alias 撞兩個 Feature 丟 `PermanentError`；內部已依 `feature_id` 升序）→ **第 1 層直接用它**。
  - `revision_of(pk) -> int`（`expected_revision` 的唯一來源）、`update_meta(pk, changes, *, expected_revision) -> int`（回新 revision；revision 不符丟 `CoordinationError(f"stale revision for {pk}: ...")`）。
  - `scan_entity(entity, *, consistent=True, meta_only=True) -> list[DynamoItem]`（`meta_only` 預設 True）、`get_feature`、`put_meta`、`get_meta_item(pk)`（要看 `_revision` 時用它）。
  - 模組函式 `item_to_model[T: StrictModel](item, model) -> T`（**不是方法**）。
- `src/training_kb/vectors.py:cosine(left, right) -> float`（會檢查長度）。
- `src/training_kb/config.py:Thresholds.cosine_match = 0.85`；`keys.py:META`、`feature_pk`。
- `src/training_kb/models.py:Feature(feature_id, name, aliases, first_seen)`、`Release(...)`、`ReleaseKind`。
- 測試 fixture：`tests/unit/conftest.py:RecordingWriter`／`fake_writer`（**功能不足，見 §6**）、`tests/integration/conftest.py:repository`（**moto**，us-west-2）。

## 3. 要新增／修改的東西
`src/training_kb/pipelines/release.py`（**同波次 P50 也在改這支檔** → 只 Edit、各自區段、不重排、`git add` 只加自己的路徑）：

```python
FEATURE_MATCH_THRESHOLD: float = Thresholds().cosine_match   # 別名，不寫第二份 0.85（D-35）
def normalize_feature_name(value: str) -> str: ...
def locate_feature(release: Release, *, repository: Repository, writer: Writer,
                   operation_id: str) -> Feature | None: ...
def update_feature_aliases(feature: Feature, *, old_name: str, new_name: str,
                           repository: Repository) -> Feature: ...
```
（00A §6.9 逐字核對過。`normalize_feature_name` **P50 會 import**，名字不能改。）

測試檔（00A §3.3 指定，basename 全專案唯一）：
- `tests/unit/test_release_locate_feature.py`
- `tests/unit/test_release_alias_update.py`
- `tests/integration/test_release_feature_lookup.py`

**不新增 prompt**（D-67 明列 P49 不在 prompt renderer 名單裡）。

## 4. Task 順序與紅燈訊號
1. **Task 1｜三層定位＋0.85 門檻**
   - RED：`uv run pytest tests/unit/test_release_locate_feature.py -q` → `ImportError: cannot import name 'locate_feature'`
   - GREEN：alias 命中零次 `embed`；`0.8499` → `None`、`0.85` → 命中；同分取 `feature_id` 最小。
2. **Task 2｜alias 撞名整次拒絕、PK 不變**
   - RED：`uv run pytest tests/unit/test_release_alias_update.py -q` → `cannot import name 'update_feature_aliases'`
   - GREEN：`updated_pk == "FEATURE#Prepare"`、`aliases == ["Meeting Summary"]`；撞名時 `update_meta` 呼叫次數 0。
3. **Task 3｜moto 整合：一致讀取與樂觀鎖**
   - RED：`uv run pytest tests/integration/test_release_feature_lookup.py -q` → `cannot import name ...` 或 setup 缺資料
   - GREEN：改完立刻用舊名找回同一節點（`NoWriter` 保證沒走語意層）；stale `expected_revision` 丟 `CoordinationError(match="stale revision")`。
4. 收尾：`uv run ruff check src tests infra`、`uv run ruff format --check src tests infra`（共用檔只看不修別人的段）、`uv run mypy`、`uv run pytest tests -q -W error`。

## 5. 00B primary Rule → 測試
| Rule | 說明 | 測試 |
|---|---|---|
| `REL` 2 | 改名前後 alias 指向同一 Feature | `test_release_locate_feature.py::test_alias_hit_does_not_call_the_model` |
| `REL` 3 | 改名不變更 Feature 主鍵 | `test_release_alias_update.py::test_alias_update_keeps_primary_key_and_moves_old_name` |
| `REL` 4 | 未命中時向量搜尋最相近 | `test_release_locate_feature.py::test_semantic_match_needs_at_least_the_threshold`（0.8499／0.85 兩側） |
| `REL` 15 | UPDATE 完成時更新 aliases | `test_release_alias_update.py`（資料結果）；**呼叫時機由 P52 的 `UpdateAliases` 驗收** |

## 6. 風險與陷阱
- **共用 `fake_writer` 不夠用**：`RecordingWriter` 只有 `calls`（dict 清單）、`replies`（list）、`request_attempts`、固定 `FIXED_EMBEDDING`；文件裡的 `cosine_for`／`embed_calls` 要**自己在測試檔內定義區域 fixture**。`tests/unit/conftest.py` 依 R3.6 **只有 P55 能改**。
- 邊界值要用「單位向量」技巧才不會被浮點推過門檻：查詢 `[1.0] + [0.0]*1023`、候選 `[s, sqrt(1-s*s)] + [0.0]*1022`，`cosine` 算出來剛好 `s`。
- `Feature.aliases` 的 `bare_id` 只擋空字串／前後空白／`#`／控制字元，**中間空白合法**（`"Meeting Summary"` OK）。`model_copy(update=...)` **不重新驗證**，寫入前自己 strip。
- 掃描全表 Feature 要先濾 `SK == META` 再 `item_to_model`（邊沒有模型欄位會整筆 `ValidationError`）。
- **先檢查再寫入**：`_all_features` 的撞名掃描必須全部跑完才呼叫 `update_meta`，否則留下「name 改了、alias 撞名」的半套資料。
- `find_feature_by_name_or_alias` 的 `PermanentError` **往上拋**，不吞、不改判成 `None`。
- moto 整合測試產不出真實 AWS 證據；`aws dynamodb get-item` 那條已移交 P52。
- **O5 BLOCKED** → 語意層只有假向量單元測試；不新增 `xfail(strict=True)`（會變成第 12 個站崗 xfail），在報告寫 BLOCKED 即可。

## 7. 需要裁決的點 → 建議裁決
1. **`fake_writer` 怎麼來**？→ 在 `tests/unit/test_release_locate_feature.py` 內定義同名區域 fixture 覆寫 conftest 的；P50 自己定義一份，兩邊不共用。
2. **`_lookup_keys` 去重比對用原字串還是正規化字串**？→ 用**原字串**去重（照文件片段），第 1 層本來就是完全相同比對；正規化只在第 2 層做。
3. **語意層是否要對 0 個候選短路**？→ 是：`features` 為空就直接回 `None`，省掉查詢向量那次 `embed`（省錢、也讓「零 Feature」不算一次 Bedrock attempt）。寫成本計畫選擇。
4. **`update_feature_aliases` 的 `aliases` 排序**？→ 照文件用 `sorted(...)`，讓重跑 byte 相同。

## 8. 對 AWS 的實際操作
**無。** 本 Phase 不上 AWS（COMMON.md R1：真實 AWS 集中在 P41／P48／P52／P57／P59／P60）。整合測試跑 moto。
真實帳號的 `FEATURE#Prepare` 逐欄比對已寫進 **P52 §6 可實證路徑表**；語意層的真實 Bedrock 證據因 **O5 BLOCKED** 取不到（`docs/plan/report/o5-20260915T030245Z.md`）。
