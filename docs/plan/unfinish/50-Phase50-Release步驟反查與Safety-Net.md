# Phase 50：Release 步驟反查與 Safety Net 實作計畫

> **給實作者：** 依 checkbox 逐步執行；每個 Task 先建立失敗測試，再寫最小實作。執行時使用 `superpowers:executing-plans` 或同等逐項流程。

> **現況核對（2026-09-14，Phase 41–60 批次 W0）：**
>
> **（a）已存在、直接重用（file:function）**
> - `src/training_kb/pipelines/release.py` — controller 已預建**只有 docstring 的空殼**（commit `5f8a430`，COMMON.md R4）。本 Phase 用 `Edit` 追加 `# ---- Phase 50 ----` 區段。
> - `src/training_kb/repository.py:Repository.find_current_published_steps_referencing(feature_id) -> list[TutorialStep]`（P27；**反查的唯一實作**，A=GSI `query_by_target` 候選、B=基表 `scan_entity("TUTORIAL")` + `_is_current_published` + `get_steps`，GSI 有而基表讀不到時丟 `PermanentError(f"GSI 候選在基表讀不到對應步驟：{pk}")`）。
> - `src/training_kb/repository.py`：`scan_entity(entity, *, consistent=True, meta_only=True)`（**`meta_only` 預設就是 `True`**）、`get_steps(version_id)`（依 `number` 升序）、`get_version`、`get_tutorial`、模組函式 `item_to_model`。
> - `src/training_kb/content.py:parse_version_id(value) -> tuple[str, int]`、`src/training_kb/vectors.py:cosine`、`src/training_kb/writing/schemas.py:StepConfirmation`（`required: ["confirmed_step_numbers", "reason"]`、`additionalProperties: False`、`confirmed_step_numbers` 的 items 是 `{"type": "integer", "minimum": 1}`）。
> - `src/training_kb/writing/prompts.py`：目前**只有** `_TUTORIAL_SYSTEM`、`_as_data`、`prompt_write_tutorial`、`_GAP_SYSTEM`、`prompt_name_gap`。`_as_data` 就是 `html.escape(text, quote=False)`，直接用模組內那一份（D-67）。
> - `src/training_kb/models.py:TutorialStatus.ACTIVE`／`TutorialStep`（欄位 `tutorial_version`、`number`、`type`、`text`、`feature_id`）、`src/training_kb/keys.py:META`、`src/training_kb/errors.py:ContentError`（是 `PermanentError` 的子類）。
>
> **（b）因上一批裁決／實作而修正的點**
> 1. §4「修改 `pipelines/release.py`」成立，但要補一句：**同一波次 P49 也在改這支檔**（W1：P49 ∥ P50）。只用 `Edit`、各自 `# ---- Phase NN ----` 區段、不重排也不 `ruff format` 整支檔；`git add` 只加自己的檔案路徑（COMMON.md R3）。
> 2. `writing/prompts.py` 是 **P17 owner 的高度共用檔**（00A §3.2：P39、P40、P43、P45–P47、P50、P51 都會追加）。本 Phase 只 `Edit` 追加 `prompt_safety_net_confirm` 與它自己的 `_SAFETY_NET_SYSTEM` 常數，**不動** `_as_data` 與別人的 renderer。W1 期間 P43／P45–P47 也可能在同一支檔追加。
> 3. §7 Task 3 的 `fake_writer`（帶 `scores`、`replies`、`default_reply`、`json_calls`）**不是**共用 fixture：`tests/unit/conftest.py` 的 `RecordingWriter` 只有 `calls`／`replies`（list，依序 pop）／`request_attempts` 與固定 `FIXED_EMBEDDING`，而該檔依 COMMON.md R3.6 **只有 P55 可以修改**。請在 `tests/unit/test_release_safety_net.py` 內自備區域 fixture（同名覆寫即可），**不要**改 conftest，也**不要**與 P49 共用同一份（兩個 Phase 並行，共用會互相卡住）。
> 4. §7 Task 3 的 `fake_writer.json_calls[0].user`／`call.node` 是屬性存取；共用 `RecordingWriter` 記的是 **dict**（`{"kind", "operation_id", "node", "system", "user", "schema"}`）。自備 fixture 時請沿用 dict 形狀或自己定義 dataclass，並在測試裡寫清楚。
> 5. §7 Task 3 Step 4 的 `tests/integration/test_release_hits_consistency.py` 跑在 **moto**（`tests/integration/conftest.py`，region `us-west-2`，`by_target` 是 KEYS_ONLY GSI）。moto 的 GSI 沒有真實的最終一致落後，所以「GSI 延遲」只能用 fixture 主動 `gsi_hide` 模擬；`aws dynamodb query --index-name by_target` 的**真實**輸出取不到，移交 **P52 §6 證據表**（COMMON.md R1）。
> 6. §6 的「`meta_only` 預設 `True`」與現況一致（`repository.py:539`）；`_current_published` 仍自己再濾一次 `SK == META` 是對的（與 `Repository._meta_models` 同一套防禦）。
> 7. §5 Consumes 的其他簽名逐一核對通過，未發現需要改寫的簽名。
>
> **（c）gate 現況對本 Phase 的影響**（COMMON.md §2）
> - **O5 BLOCKED**（`docs/plan/report/o5-20260915T030245Z.md`：Titan／Claude 皆 `ValidationException: Operation not allowed`）→ `safety_net` 的 `embed` 與 `generate_json` 一律走假 writer；真實 AWS 執行時 `SafetyNet` 節點會走 `PermanentError → Catch → PipelineFailed`，那是 **BLOCKED 證據**不是 bug（證據由 P52 取得）。`find_release_hits`／`needs_safety_net` 不碰模型，不受影響。
> - **O2 PASS**（P11）：反查結果的完整性可以依賴永久去重與同版號；但 moto 綠燈仍不等於真實併發，報告照實寫。
> - **O3 FAIL**、**O6 未核定 `github.com/pull_request`**：本 Phase 不發布也不吃 webhook payload，兩者不影響交付物，但不得宣稱已核定。
> - 前置 P01–P40 全部完成；**P49 與本 Phase 同波次並行**，`normalize_feature_name` 由 P49 在同一支檔提供——先寫自己的 Task 1（`find_release_hits` 不需要它），Task 2 需要時若 P49 尚未落地，**不得自己複製一份**，改為等待或暫時 import 失敗留紅燈（00A §6.9 owner 是 P49）。
>
> **（d）適用的 controller 裁決**：R3（`pipelines/release.py`、`writing/prompts.py` 兩支共用檔同波次併行）、R4、R5、R6、R7（`docs/plan/report/phases/2026-09-14-Phase50-REP.md`）、R8、R10。
>
> **實作波次**：W1（P49 ∥ P50 同時進行）→ W2（P51，需要本 Phase 的 `StepHit` 型別）→ W3（P52）。

**目標：** 從 Phase 49 定位到的 Feature，找出所有「目前已發布版本」中真的引用它的步驟；反查為零或重大改名時，再用步驟文字相似度提出候選並交 Claude 逐一確認。

**架構：** 反查本身由 Phase 27 的 `find_current_published_steps_referencing` 完成（`by_target` GSI 取候選、基表一致讀取雙向核對）；本 Phase 只**包裝**它，把 `TutorialStep` 轉成下游要的 `StepHit` 座標並固定排序，不重寫一份 GSI 邏輯。Safety Net 是獨立的補漏路徑，只新增確認過的命中，永遠不會刪掉已經明確反查到的命中。

**技術：** Python 3.12、Pydantic v2、pytest、Phase 16 的 `Writer.embed`／`cosine`、Phase 17 的 `StepConfirmation` schema、Phase 27 的固定查詢。

## 全域限制

- 唯一主來源是 [Training KB 設計 §7.4、§9.2、§10、§14.1、§16 S5](../../design/training-kb.md)。
- 前置為 [Phase 49：Release 功能定位與 Alias](./49-Phase49-Release功能定位與Alias.md)。`locate_feature` 回 `None` 時本 Phase 不執行。
- 下一階段是 [Phase 51：Release UPDATE 精準改寫](./51-Phase51-Release-UPDATE精準改寫.md)。
- 本階段不做：不改寫步驟、不配置版號、不建立版本、不發布、不退役、不更新 aliases。
- 只處理每篇教學目前已發布的 `current_version`；歷史版與未發布版的命中只供追溯（F17）。Safety Net 全數未確認、無候選或無法確認時回傳空 tuple，由呼叫端記未命中並 KEEP（F18）。
- O1–O7 狀態（現況核對 2026-09-14）：**O5 BLOCKED**（`docs/plan/report/o5-20260915T030245Z.md`）→ Safety Net 的模型路徑保持 blocked，只能用假 writer 驅動；**O2 PASS**（P11）→ 可以依賴永久去重與同版號，但 moto 綠燈仍不等於真實併發，報告照實寫。本 Phase 不得宣稱任何 gate 已核定。
- 以下程式檔均是實作時預計建立或修改；本計畫本身不代表它們已存在。

---

## 1. 你在整體流程的位置

```text
Phase 49 locate_feature -> Feature(feature_id="Prepare")
             |
             v
[你在這裡] find_release_hits（包裝 Phase 27 的反查）---> StepHit(A, A@v2, 3)
             |
             v
   needs_safety_net？ 是（零命中，或 renamed 且 alias 未命中）-> safety_net
             |          步驟文字向量取候選 -> Claude 逐版確認
             v
   +-- 有確認 --> 與原命中取聯集 --> Phase 51 UPDATE / Phase 52 RETIRE
   +-- 零確認 --> 記未命中，KEEP，不建立版本
```

`find_release_hits` 的結果是**明確證據**；`safety_net` 的結果是**補漏證據**。兩者取聯集，補漏永遠不覆寫明確證據。

## 2. 完成後看得到什麼

圖譜有三篇已發布教學：A `prepare-meeting@v2`（四步，第 3 步引用 `FEATURE#Prepare`）、B `share-summary@v1`、C `notification-settings@v1`；A 另有歷史版 `prepare-meeting@v1`（第 3 步也引用同一 Feature）與未發布的 `share-summary@v2`。

```text
find_release_hits("Prepare", repository=repo)
  -> (StepHit(slug="prepare-meeting", version_id="prepare-meeting@v2", number=3),)
```

歷史版與未發布版都**不**出現；B、C 沒有命中，後續動作是 KEEP。邊只寫進基表、GSI 還沒反映時，結果仍必須包含第 3 步（靠 Phase 27 的基表方向補齊）。反過來 GSI 還留著一筆基表已經查不到的 current 已發布步驟時，Phase 27 會丟 `PermanentError`：那是「基表資料不完整」，不是「沒有命中」，本 Phase 讓它原樣往上拋，**不**改判成空 tuple，也不順手補寫（補寫是 [Phase 28](./28-Phase28-引用Backfill與規則投影重建.md) 的事）。

## 3. 名詞小抄

| 名詞 | 白話意思 |
|---|---|
| `StepHit` | 一個「要被改版的步驟」座標：哪一篇、哪一版、第幾步。 |
| by_target GSI | 用「邊的終點」反查起點的索引；只有最終一致讀取，可能慢半拍。 |
| 基表核對 | 用可一致讀取的主表再確認一次，避免漏判或誤判。 |
| current 已發布版 | `Tutorial.current_version` 指到的那一版，且該版 `published_at` 非空。 |
| 重大改名 | 只有「alias 比對失敗的 renamed」才算（F16）；alias 已命中的不算。 |
| 候選 | Safety Net 依步驟文字相似度挑出來、要交給 Claude 確認的步驟；候選不等於命中。 |
| `F16`／`F17`／`F18`／`F45` | 設計文件 [§19.2 功能決策](../../design/training-kb.md) 的編號：依序是「什麼算重大改名」「只處理目前已發布版本」「補漏零確認就 KEEP」「呼叫數計入每次真實 attempt」。 |
| `REL` | [00B 需求覆蓋對照](00B-需求覆蓋對照.md) 給 `依改版更新教學.feature` 的縮寫；`REL` Rule 5 就是那份規格的第 5 條 Rule。 |

## 4. 預計檔案

| 動作 | 路徑 | 責任 |
|---|---|---|
| 修改 | `src/training_kb/pipelines/release.py` | `StepHit`、`find_release_hits`、`needs_safety_net`、`safety_net`。（同一波次 P49 也在改這支檔：只 `Edit`、各自 `# ---- Phase NN ----` 區段。） |
| 修改 | `src/training_kb/writing/prompts.py` | `prompt_safety_net_confirm`：只放候選版的步驟文字。（現況核對 2026-09-14：這支檔 owner 是 P17，00A §3.2 列出 P39／P40／P43／P45–P47／P50／P51 都會追加；只 `Edit` 加自己的區段，不動 `_as_data` 與別人的 renderer。） |
| 測試 | `tests/unit/test_release_hits.py` | current／已發布篩選、GSI 漏邊補齊、缺邊拋錯、排序。 |
| 測試 | `tests/unit/test_release_safety_net.py` | 觸發條件、候選排序、確認驗證與空結果。 |
| 測試 | `tests/integration/test_release_hits_consistency.py` | **moto** GSI 下的一致讀取核對（GSI 落後用 fixture 主動隱藏來模擬）。（現況核對 2026-09-14：原寫「真實 GSI 延遲」，`tests/integration/conftest.py` 是 moto、`by_target` 是 KEYS_ONLY，沒有真實落後；真實 GSI 證據移交 P52 §6。） |

## 5. 固定介面

### Consumes

```text
Release / Feature / Tutorial / TutorialVersion / TutorialStep                         # Phase 04
META: str                                                                             # Phase 05
parse_version_id(value: str) -> tuple[str, int]                                       # Phase 20，在 content.py
Repository.get_version(version_id) -> TutorialVersion | None                          # Phase 06
Repository.get_steps(version_id) -> list[TutorialStep]                                # Phase 08
Repository.scan_entity(entity, *, consistent=True, meta_only=True) -> list[DynamoItem]  # Phase 08
item_to_model(item: DynamoItem, model: type[T]) -> T                                  # Phase 08，模組函式
Repository.find_current_published_steps_referencing(feature_id) -> list[TutorialStep] # Phase 27，反查的唯一實作
Writer.embed(text, *, operation_id, node) -> list[float]                           # Phase 15/16
Writer.generate_json(system, user, schema, *, operation_id, node) -> dict[str, Any]   # Phase 15/17
StepConfirmation  # schema dict；required: confirmed_step_numbers, reason              # Phase 17
cosine(left, right) -> float                                                          # Phase 16
normalize_feature_name(value: str) -> str                                             # Phase 49
ContentError / PermanentError                                                         # Phase 02
```

### Produces

```python
SAFETY_NET_CANDIDATES: int = 5

@dataclass(frozen=True)
class StepHit:
    slug: str
    version_id: str
    number: int

def find_release_hits(feature_id: str, *, repository: Repository) -> tuple[StepHit, ...]: ...
def needs_safety_net(release: Release, feature: Feature, hits: Sequence[StepHit]) -> bool: ...
def safety_net(release: Release, *, repository: Repository, writer: Writer, operation_id: str) -> tuple[StepHit, ...]: ...

def prompt_safety_net_confirm(
    version_id: str, steps: Sequence[TutorialStep], names: Sequence[str]
) -> tuple[str, str]: ...
```

`StepHit` 是 frozen dataclass，可放進 `set` 做聯集與去重；所有回傳值依 `(slug, number)` 升序，重跑結果 byte 相同。`prompt_safety_net_confirm` 加在 `writing/prompts.py`（檔案 owner 是 Phase 17），沿用該 Phase 的 `prompt_<node>` 命名並回 `(system, user)`；它只吃字串與模型物件，**不** import `pipelines`，也不拿 `Repository`，避免反向相依。

`find_release_hits` 是模組函式名；`release-update` ASL 那一層的 Task 名是 `find_steps`（Phase 52 的 `FindSteps` state）。兩者是不同層，不得互相取代。

## 6. 設計細節

反查的雙向核對已經在 [Phase 27](./27-Phase27-固定圖譜查詢.md) 完成，本 Phase **包裝**它、不重寫（00A 裁決 D-38）：

```text
  find_release_hits(feature_id)      <- 本 Phase：型別轉換 + 依 (slug, number) 排序
              |
              v
  Repository.find_current_published_steps_referencing(feature_id)  <- Phase 27：唯一實作
              |
              +-- B｜基表強一致：掃 active Tutorial 的 current 已發布版，比對 feature_id
              +-- A｜GSI query_by_target：不是 current 已發布 -> 丟棄；
              |      是 current 已發布卻在基表讀不到 -> PermanentError
              v
        list[TutorialStep]  ->  tuple[StepHit, ...]
```

A 方向處理「GSI 有、但不該算」（歷史版、未發布版）；B 方向處理「GSI 還沒有、但基表已經有」。這正是設計 §10 所說的「改版前以基表一致讀取核對目前版的完整引用集合，避免 GSI 暫時少資料就錯判 KEEP」。MVP 資料量小，B 方向的 Scan 是設計 §18 已接受的規模取捨。

`StepHit` 只留三欄，因為下游（Phase 51 改寫、Phase 52 退役）只需要「哪一篇、哪一版、第幾步」這組座標；`slug` 由 Phase 20 的 `parse_version_id` 從 `TutorialStep.tutorial_version` 還原，不再查一次表。Safety Net 的觸發條件與執行順序如下：

```text
hits 為空？ -- 是 -------------------------------+
   | 否                                          |
   v                                             |
renamed 且 old_name 不在 name/aliases？ ---------+   （alias 已命中 -> 不觸發）
   | 否 -> 不觸發                                v
        embed(改版名稱) 對每個 current 已發布步驟算 cosine
                    -> 取前 5 名（分數降序、slug 升序、number 升序）
                    -> 依 version_id 分組，每組一次 StepConfirmation 呼叫
                    -> 程式驗證：編號確實是該版的步驟、reason 去空白後非空
                    -> confirmed（可能為空 tuple）
```

每個候選版本各發一次 `generate_json`，是因為 `StepConfirmation.confirmed_step_numbers` 只有裸編號，跨版會分不清是誰的第 3 步。prompt 必須寫明「`confirmed_step_numbers` 填的是教學裡**從 1 起算的步驟 `number`**，不是候選清單的名次，也不是 0-based index」——否則模型回 `[1]` 時，程式分不出它指的是第 1 步還是第一個候選（00A §3.3：步驟編號一律叫 `number`）。程式收到後只留「確實是該版步驟編號」的值，其餘直接丟棄、**不**為此再問一次模型（Phase 18 的 schema 對照表把 `StepConfirmation` 標為不走 correction）；`reason` 去空白後為空屬於模型輸出違規，依設計 §7.4 丟 `ContentError`，不當成 KEEP。

`SAFETY_NET_CANDIDATES = 5` 是**本計畫選擇**的候選預算（上限五個版本、五次確認呼叫），不是業務門檻，也不是另一個 cosine 值。要留意**候選前的 `embed` 次數與「目前已發布步驟總數」成正比**：§2 的三篇教學共約十步，就是 1 次查詢向量加十次步驟向量；教學變多時線性成長，而且每次 `safety_net` 都重算（設計 §10 允許單次執行內重用向量，但不往 ERM 加 embedding 欄位）。每一次 `embed` 與 `generate_json` 都是一次真實 Bedrock attempt，依 F45 必須計入 `CallTrace`。Demo 規模可接受；要放大資料量前先回頭看設計 §18。

### 本計畫選擇（2026-09-14，實作時裁決）

1. **`kind` 比較寫法**：`needs_safety_net` 用 `release.kind is not ReleaseKind.RENAMED`。`ReleaseKind` 是 `StrEnum`，與 `"renamed"` 字串也相等，但 enum 比較不會被打錯的字面值騙過，mypy 也擋得住。
2. **候選 tie-break**：`scored` 的元素固定是 `(-score, slug, number, version_id)`，`list.sort()` 一次得到「分數降序 → slug 升序 → number 升序 → version_id 升序」，同分的勝者固定、重跑 byte 相同。
3. **`safety_net` 不自己先跑 `find_release_hits`**：它只回補漏證據，聯集由呼叫端（P52 的 `task_safety_net`）做 `set(direct) | set(net)`。補漏因此只會新增，不可能抹掉明確命中。
4. **prompt 分區**：system 常數叫 `_SAFETY_NET_SYSTEM`（與 `_TUTORIAL_SYSTEM`／`_GAP_SYSTEM`／`_DIAGNOSE_SYSTEM` 同風格）；user 固定三個分區 `<change>`（改版名稱）→ `<version>`（候選所屬版本，沿用 P45 `prompt_diagnose_weak` 的名字）→ `<source_data>`（候選步驟的 `number` 與文字，經 `_as_data` 轉義）。
5. **node 名稱**：`safety_net_query`（查詢向量）、`safety_net_step`（每個步驟一次）、`safety_net_confirm`（每個候選版本一次）。三個都是字面值，沒有再宣告 00A §6.9 以外的公開常數。
6. **退役教學的不對稱**：`find_release_hits` 會回退役教學的 current 已發布步驟（P27 不看 `status`，見 §7 Task 1 Step 4 的現況核對），`safety_net` 的 `_current_published` **會**排除退役教學——明確證據照實回報，補漏證據只補到 active 的教學上。
7. **整合測試的 GSI 替身**：moto 的 GSI 是即時的，所以用兩個比真實更嚴格的替身——`blind_gsi`（候選來源整個關掉）與「少了 `entity` 屬性的邊」（`by_target` 看得到、`scan_entity` 掃不到）。做法沿用 P27 的 `tests/integration/test_current_published_steps.py`。

## 7. TDD Tasks

### Task 1：把 Phase 27 的反查包成 `StepHit` 座標

- [x] **Step 1：建立失敗測試**

```python
import pytest

from training_kb.errors import PermanentError
from training_kb.pipelines.release import StepHit, find_release_hits

A_V2_STEP3 = StepHit("prepare-meeting", "prepare-meeting@v2", 3)


def test_only_current_published_steps_are_hit(three_tutorials):
    assert find_release_hits("Prepare", repository=three_tutorials) == (A_V2_STEP3,)


def test_stale_gsi_does_not_hide_a_base_table_edge(three_tutorials):
    three_tutorials.gsi_hide("STEP#prepare-meeting@v2#3")     # GSI 尚未反映這條邊
    assert find_release_hits("Prepare", repository=three_tutorials) == (A_V2_STEP3,)


def test_gsi_row_without_base_row_is_not_silently_dropped(three_tutorials):
    three_tutorials.clear_steps("prepare-meeting@v2")         # 基表已無，GSI 還留著
    with pytest.raises(PermanentError, match="STEP#prepare-meeting@v2#3"):
        find_release_hits("Prepare", repository=three_tutorials)
```

`three_tutorials` 就是 §2 的圖譜：A `prepare-meeting`（current `@v2`，四步，第 3 步引用 `FEATURE#Prepare`；歷史版 `@v1` 第 3 步也引用它）、B `share-summary`（current `@v1`，兩步；另有未發布的 `@v2`，第 1 步也引用該 Feature）、C `notification-settings`（current `@v1`，兩步）。它和 [Phase 27](./27-Phase27-固定圖譜查詢.md) 的 `repo` fixture 同一種做法：**被測的是真的 `Repository`**，只有 Phase 06／08 的原語（`scan_entity`、`query_by_target`、`get_steps`、`get_tutorial`、`get_version`）由記憶體字典頂替，`gsi_hide(pk)` 讓某筆邊暫時不出現在 GSI、`clear_steps(version_id)` 只刪基表的 STEP item。這樣跑到的 `find_current_published_steps_referencing` 是 Phase 27 的真程式，不是另一份複製品。第一個測試同時蓋掉 F17 的兩種排除（歷史版 `@v1`、未發布的 `share-summary@v2`）與 `REL` Rule 12（B、C 零命中）。

- [x] **Step 2：執行並確認紅燈**

```bash
uv run pytest tests/unit/test_release_hits.py -q
```

預期：FAIL，訊號包含 `cannot import name 'find_release_hits'`。

- [x] **Step 3：建立最小實作**

```python
from dataclasses import dataclass

from training_kb.content import parse_version_id


@dataclass(frozen=True)
class StepHit:
    slug: str
    version_id: str
    number: int


def find_release_hits(feature_id, *, repository):
    hits = {
        StepHit(parse_version_id(step.tutorial_version)[0], step.tutorial_version, step.number)
        for step in repository.find_current_published_steps_referencing(feature_id)
    }
    return tuple(sorted(hits, key=lambda hit: (hit.slug, hit.number)))
```

只有這幾行：GSI 候選、基表核對、`PermanentError` 都在 Phase 27 裡，本 Phase **不得**另寫一份 `query_by_target` 篩選（00A D-38）。函式不吞例外，所以第三個測試才會看到 `PermanentError`。

- [x] **Step 4：跑 `uv run pytest tests/unit/test_release_hits.py -q` 確認綠燈。** 另補三個案例：同一篇兩步都命中時依 `number` 升序、`status="retired"` 的教學不納入、`current_version` 為 `None`（尚未首次發布）不納入。三者都由 Phase 27 的篩選達成，本 Phase 只負責證明包裝沒有把它們放行。

  > **現況核對（2026-09-14，實作）：** 三個案例都補了，但第二個的預期相反——`status="retired"` 的教學**仍然會命中**。`retire_tutorial` 只改 `status` 與 `successor`，`current_version` 與該版 `published_at` 都保留（設計 §8.1 要保存歷史），而 Phase 27 的 `_is_current_published` 只看「是不是 current 而且已發布」，沒有看 `status`。本 Phase 依 D-38 只包裝、不得自己加一層篩選，所以測試 `test_retired_tutorial_is_still_hit_because_it_keeps_a_published_current_version` 照實斷言現況；要不要在 Phase 27 排除退役教學留給 controller／P52 裁決（報告 §9）。補漏那一側的 `_current_published` **有**排除退役教學——建議不該把不再維護的教學拉回來改版。

- [x] **Step 5：提交**

```bash
git add src/training_kb/pipelines/release.py tests/unit/test_release_hits.py
git commit -m "feat(release): 反查目前已發布的引用步驟"
```

### Task 2：固定 Safety Net 的觸發條件

- [x] **Step 1：建立失敗測試**

```python
HIT = StepHit("prepare-meeting", "prepare-meeting@v2", 3)


@pytest.mark.parametrize("kind,old_name,hits,expected", [
    ("renamed", "Meeting Summary", [HIT], False),   # alias 命中，不是重大改名
    ("renamed", "Legacy Name", [HIT], True),        # alias 未命中 -> 重大改名
    ("changed", None, [], True),                    # 反查為零 -> 獨立觸發
    ("changed", None, [HIT], False),
])
def test_safety_net_trigger_follows_f16(kind, old_name, hits, expected):
    release = make_release(kind=kind, old_name=old_name, new_name="Prepare")
    feature = make_feature("Prepare", name="Prepare", aliases=["Meeting Summary"])
    assert needs_safety_net(release, feature, hits) is expected
```

- [x] **Step 2：執行 `uv run pytest tests/unit/test_release_safety_net.py -q` 並確認紅燈**，訊號包含 `cannot import name 'needs_safety_net'`。

- [x] **Step 3：建立最小實作**

```python
def needs_safety_net(release, feature, hits):
    if not hits:
        return True                                  # 反查為零，獨立觸發
    if release.kind != "renamed":
        return False
    known = {normalize_feature_name(name) for name in [feature.name, *feature.aliases]}
    return normalize_feature_name(release.old_name or "") not in known
```

`release.kind` 是 Phase 03 的 `ReleaseKind` StrEnum，成員值就是小寫字串，所以 `!= "renamed"` 成立。純函式、不碰 `Repository` 也不碰 `Writer`：這一步決定要不要花錢，不該有副作用。

- [x] **Step 4：跑 `uv run pytest tests/unit/test_release_safety_net.py -q` 確認綠燈。** F16 四種組合全部 PASS；特別確認「alias 已命中且有 references 命中」是唯一完全不觸發的組合。

- [x] **Step 5：提交**

```bash
git add src/training_kb/pipelines/release.py tests/unit/test_release_safety_net.py
git commit -m "feat(release): 固定 safety net 觸發條件"
```

### Task 3：候選排序、逐版確認與空結果

- [x] **Step 1：建立失敗測試**

```python
def test_safety_net_confirms_per_version_and_validates_numbers(
    three_tutorials, fake_writer, renamed_release
):
    fake_writer.scores = {                      # 沒列到的步驟一律 0.0
        ("prepare-meeting@v2", 3): 0.91, ("prepare-meeting@v2", 1): 0.40,
        ("prepare-meeting@v2", 2): 0.30, ("prepare-meeting@v2", 4): 0.20,
        ("share-summary@v1", 1): 0.10,
    }
    fake_writer.replies = {
        "prepare-meeting@v2": {"confirmed_step_numbers": [3, 99], "reason": "第 3 步提到舊名稱"},
        "share-summary@v1": {"confirmed_step_numbers": [], "reason": "沒有步驟提到這個功能"},
    }
    found = safety_net(renamed_release, repository=three_tutorials,
                       writer=fake_writer, operation_id="op-release-r_42")
    assert found == (StepHit("prepare-meeting", "prepare-meeting@v2", 3),)   # 99 被丟棄
    assert [call.node for call in fake_writer.json_calls] == ["safety_net_confirm"] * 2
    assert "share-summary" not in fake_writer.json_calls[0].user             # 一次只放一個版本


def test_safety_net_returns_empty_when_nothing_confirmed(
    three_tutorials, fake_writer, renamed_release
):
    fake_writer.default_reply = {"confirmed_step_numbers": [], "reason": "沒有步驟提到這個功能"}
    assert safety_net(renamed_release, repository=three_tutorials,
                      writer=fake_writer, operation_id="op-release-r_42") == ()
```

`renamed_release` 是 `r_42`（`kind="renamed"`、`feature="Prepare"`、`old_name="Meeting Summary"`、`new_name="Prepare"`）。`fake_writer` 與 Phase 49 同型（**現況核對 2026-09-14：各自在自己的測試檔內定義，不共用、不改 `tests/unit/conftest.py`**——那支檔依 COMMON.md R3.6 只有 P55 可以動，而且 P49／P50 同波次並行，共用會互相卡住）：`embed` 把查詢文字回成 `[1.0] + [0.0] * 1023`、把分數為 `s` 的步驟回成 `[s, sqrt(1 - s * s)] + [0.0] * 1022`，所以 Phase 16 的真 `cosine` 算出來剛好等於 `s`，排序不會被浮點誤差推翻；`generate_json` 依 `user` 裡出現的 `version_id` 從 `replies` 取回覆（沒設就用 `default_reply`），並把 `(system, user, schema, node)` 記進 `json_calls`（共用 `RecordingWriter` 記的是 **dict**；自備 fixture 要用屬性存取就自己定義 dataclass，別假設共用那支有 `json_calls`）。八個步驟裡分數最高的五個是 A 的四步加 B 的第 1 步，剛好等於 `SAFETY_NET_CANDIDATES`，所以會有兩次確認呼叫、依 `(slug, version_id)` 升序先 A 後 B。

- [x] **Step 2：執行 `uv run pytest tests/unit/test_release_safety_net.py -q` 並確認紅燈**，訊號包含 `cannot import name 'safety_net'`。

- [x] **Step 3：建立最小實作**

```python
from training_kb.errors import ContentError
from training_kb.keys import META
from training_kb.models import Tutorial, TutorialStatus
from training_kb.repository import item_to_model
from training_kb.vectors import cosine
from training_kb.writing.prompts import prompt_safety_net_confirm
from training_kb.writing.schemas import StepConfirmation

SAFETY_NET_CANDIDATES = 5


def _current_published(repository):        # 每篇 active Tutorial 的 (slug, current 已發布 version_id)
    rows = [item for item in repository.scan_entity("TUTORIAL") if str(item["SK"]) == META]
    for tutorial in sorted((item_to_model(row, Tutorial) for row in rows), key=lambda t: t.slug):
        current = tutorial.current_version
        if tutorial.status is not TutorialStatus.ACTIVE or current is None:
            continue
        version = repository.get_version(current)
        if version is not None and version.published_at is not None:
            yield tutorial.slug, current


def _release_names(release):
    parts = (release.feature, release.old_name or "", release.new_name or "")
    return tuple(dict.fromkeys(part.strip() for part in parts if part.strip()))


def _score_steps(release, *, repository, writer, operation_id):
    query = writer.embed(" / ".join(_release_names(release)),
                         operation_id=operation_id, node="safety_net_query")
    scored, steps_by_version = [], {}
    for slug, version_id in _current_published(repository):
        steps = {step.number: step for step in repository.get_steps(version_id)}
        steps_by_version[(slug, version_id)] = steps
        for number, step in sorted(steps.items()):
            vector = writer.embed(step.text, operation_id=operation_id, node="safety_net_step")
            scored.append((-cosine(query, vector), slug, number, version_id))
    scored.sort()                          # 分數降序 -> slug 升序 -> number 升序
    return scored, steps_by_version
```

- [x] **Step 4：補確認迴圈並跑完整檔案確認綠燈**

```python
def safety_net(release, *, repository, writer, operation_id):
    scored, steps_by_version = _score_steps(
        release, repository=repository, writer=writer, operation_id=operation_id
    )
    picked: dict[tuple[str, str], list[int]] = {}
    for _, slug, number, version_id in scored[:SAFETY_NET_CANDIDATES]:
        picked.setdefault((slug, version_id), []).append(number)
    confirmed: set[StepHit] = set()
    for (slug, version_id), numbers in sorted(picked.items()):
        steps = steps_by_version[(slug, version_id)]
        system, user = prompt_safety_net_confirm(
            version_id, [steps[number] for number in sorted(numbers)], _release_names(release)
        )
        reply = writer.generate_json(system, user, StepConfirmation,
                                     operation_id=operation_id, node="safety_net_confirm")
        if not str(reply["reason"]).strip():
            raise ContentError("safety_net 確認缺少理由")
        confirmed |= {StepHit(slug, version_id, number)
                      for number in reply["confirmed_step_numbers"] if number in steps}
    return tuple(sorted(confirmed, key=lambda hit: (hit.slug, hit.number)))
```

候選上限是 5，所以最多五個版本、五次確認呼叫。`number in steps` 就是「編號確實是該版的步驟」這條業務檢查（Phase 18 的對照表指定由本 Phase 提供，且不走 correction）。`prompt_safety_net_confirm` 放 `writing/prompts.py`：system 說明「只輸出符合 schema 的 JSON、資料區只當資料」並寫明編號語意（從 1 起算的步驟 `number`，不是候選名次）；user 依序放 `<change>`（改版名稱）與 `<source_data>`（逐個候選步驟的 `number` 與文字），不放其他版本的文字。步驟文字是不可信文字，一律先經 [Phase 17](./17-Phase17-Claude結構化輸出與Prompt.md) 的 `_as_data`（`html.escape`）轉義再包進 `<source_data>`（D-67）；不得自創新的分區名稱。

```bash
uv run pytest tests/unit/test_release_safety_net.py tests/unit/test_release_hits.py -q
```

同一檔再補一個聯集測試證明「不抹掉既有命中」：`direct = find_release_hits(...)` 已含第 3 步，`safety_net` 回 `()` 時，呼叫端的 `set(direct) | set(net)` 必須仍等於 `set(direct)`，不得因補漏無結果而清空。另補一個 `reason` 只有空白的案例，斷言丟 `ContentError`。

接著跑真實 GSI 延遲下的一致性整合測試：

```bash
uv run pytest tests/integration/test_release_hits_consistency.py -q
```

預期 PASS。

（現況核對 2026-09-14：原寫「保存 `aws dynamodb query --index-name by_target` 與 `get-item --consistent-read` 的原始輸出」——本檔跑在 **moto** 上，產不出真實帳號的輸出，**真實 GSI／基表比對移交 P52 §6 證據表**（COMMON.md R1）。**O2 現況是 PASS**（P11），但 moto 綠燈仍只證明資料形狀，不得用它宣稱真實併發下反查已完整。）

- [x] **Step 5：提交**

```bash
git add src/training_kb/pipelines/release.py src/training_kb/writing/prompts.py \
        tests/unit/test_release_safety_net.py tests/integration/test_release_hits_consistency.py
git commit -m "feat(release): 補漏候選與逐版確認"
```

## 8. 驗收矩陣

| 路徑 | 輸入 | 預期資料結果 |
|---|---|---|
| Happy | A `@v2` 第 3 步引用該 Feature | 只有 `StepHit("prepare-meeting", "prepare-meeting@v2", 3)`；B、C 無命中。 |
| Boundary | A `@v1` 歷史版與未發布的 `share-summary@v2` 也引用 | 都不出現在結果中（F17）。 |
| Boundary | GSI 尚未反映新邊 | 結果仍含 A 的第 3 步（Phase 27 的基表方向補齊）。 |
| Failure | GSI 留著一筆基表查不到的 current 已發布步驟 | `PermanentError` 原樣往上拋；**不**回 `()`、不當成 KEEP。 |
| Trigger | renamed，alias 已命中／未命中 | 前者 `needs_safety_net` 為 `False` 且零次 `embed`；後者為 `True`，即使已有反查命中。 |
| Boundary | Claude 全部未確認／回傳不存在的編號 99 | 前者回 `()` 並由呼叫端 KEEP（F18）；後者丟棄該編號、不重問模型。 |
| Failure | Claude 回的 `reason` 只有空白 | `ContentError`；依設計 §7.4 當成模型輸出違規，不降級成 KEEP。 |

人工驗收（現況核對 2026-09-14：拆成兩條路徑，照 COMMON.md §2）：

- **可實證路徑（本 Phase 交付）**：在 moto 整合測試裡分別呼叫 `repository.query_by_target(feature_pk("Prepare"))` 與 `repository.get_steps(...)`／`scan_entity("TUTORIAL")`，比較兩邊差異再對照 `find_release_hits` 的輸出；另讀出自備 fake writer 捕捉的確認 prompt，親眼確認只含候選版的步驟文字、且不可信文字已被 `_as_data` 轉義。不能只看測試顯示 PASS。
- **BLOCKED／移交路徑**：真實帳號的 `aws dynamodb query --index-name by_target --region us-east-1` 與 `get-item --consistent-read` 由 **P52 雲端驗收**取得；`safety_net` 的真實 Bedrock 證據因 **O5 BLOCKED** 取不到（`docs/plan/report/o5-20260915T030245Z.md`），報告記 BLOCKED。

## 9. 常見錯誤與停止條件

| 症狀 | 原因 | 修正／停止 |
|---|---|---|
| 歷史版第 3 步也被改寫 | 只看 GSI，沒核對 `current_version` | 停止，不要進入 Phase 51；反查一律走 Phase 27（F17）。 |
| GSI 慢半拍就判定 KEEP | 在本 Phase 另寫一份只讀 GSI 的反查 | 改為呼叫 Phase 27 的方法（D-38）；不得改用「多等幾秒」。 |
| 基表缺邊卻靜靜回 `()` | 把 Phase 27 的 `PermanentError` 接起來吞掉 | 讓它往上拋；補邊是 Phase 28 的責任，不在查詢裡順手寫。 |
| alias 已命中仍跑 safety_net | 把所有 renamed 當重大改名 | 依 F16 只在 alias 比對失敗時觸發。 |
| 跨版編號對錯步驟 | 一次確認呼叫混多個版本 | 依 `version_id` 分組，每組一次呼叫。 |
| 未確認卻建立新版 | 把「相似」當成「命中」 | 零確認回 `()`；由呼叫端 KEEP（F18）。 |

## 10. 來源與 Rule 對照

- [依改版更新教學.feature](../../spec/features/依改版更新教學.feature)（[00B 需求覆蓋對照](00B-需求覆蓋對照.md) 的縮寫是 `REL`；下列四條的 primary 都在本 Phase，其中 Rule 12 的流程層再驗在 Phase 52）
  - Rule 5「by_target 反查只選出引用改版 Feature 的步驟」→ Task 1 的 `test_only_current_published_steps_are_hit` 直接斷言結果恰為 A 的第 3 步，B、C 不在內。
  - Rule 6「反查為零或重大改名時使用 step 文字向量搜尋補漏」→ Task 2 的 `test_safety_net_trigger_follows_f16` 直接斷言四種組合。
  - Rule 7「safety_net 的疑似命中交給 Claude 確認」→ Task 3 的 `test_safety_net_confirms_per_version_and_validates_numbers` 直接斷言確認節點與編號驗證。
  - Rule 12「未引用改版 Feature 的教學維持 KEEP」→ §8 Happy 案例斷言 B、C 沒有 `StepHit`。
- Supporting：F16（只有 alias 比對失敗的 renamed 算重大改名；反查為零獨立觸發）、F17（只處理目前已發布版本）、F18（未確認即記未命中並 KEEP）；設計 §7.4（補漏無確認命中即 KEEP、已有明確命中不被空補漏抹掉）與 §10（GSI 最終一致，改版前以基表核對）。
- [DynamoDB 讀取一致性](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/HowItWorks.ReadConsistency.html)：GSI 不支援一致讀取，是本 Phase 必須雙向核對的直接原因。
- [DynamoDB Query 分頁](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/Query.Pagination.html)：`find_current_published_steps_referencing` 與 `scan_entity` 都必須讀完分頁，空頁不代表沒有下一頁。

## 11. 完成清單

- [x] `StepHit`、`find_release_hits`、`needs_safety_net`、`safety_net` 的名稱與簽名符合本文件。
- [x] `find_release_hits` 只包裝 Phase 27 的 `find_current_published_steps_referencing`，沒有另一份 GSI 篩選；歷史版、未發布版與「GSI 有、基表沒有」各有直接 assertion。
- [x] Safety Net 四種觸發組合都有測試，alias 已命中時零次 `embed`；候選上限固定為 5。
- [x] 確認呼叫依版本分組，非法編號被丟棄，空結果回 `()`。
- [x] 有聯集測試證明補漏不會抹掉既有明確命中；`REL` Rule 5、6、7、12 有直接 assertion。
- [x] 未把 Fake 的 PASS 說成 Bedrock、GSI 延遲或 O2／O5 已驗證。
