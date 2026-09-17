# Phase 13：Ticket Analysis 流程

| 項目 | 內容 |
|---|---|
| 上一階段 | Phase 12：Rote Agent 選工具與重放執行（`12-Phase12-Rote-Agent選工具與重放執行.md`） |
| 下一階段 | Phase 14：Step Functions 與 Lambda 上線（`14-Phase14-StepFunctions與Lambda上線.md`） |
| 對應設計文件章節 | §7.3、§6、§7.6、§12.1（`docs/design/training-kb.md`） |
| 對應交付切片 | S2（設計文件第 16 節） |
| 預估時間 | 約 6 小時 |
| 做完會得到 | 在自己電腦上把「一堆重複工單」跑成「一篇已發布的新教學 v1」，中間七個步驟都可以單獨測。 |

---

## 1. 這階段做完會得到什麼

Phase 12 結束時，一則 GitHub Issue 已經可以變成合法的 `Ticket` 並存進 DynamoDB。但那之後就沒有下文了——沒有人去看「這個問題是不是已經被問過五次」，也沒有人寫教學。

這一階段補上第一條教學流程 **Ticket Analysis**（設計文件 §7.3），做完你會有：

1. **`pipelines/common.py`**：三條流程共用的骨架。`Deps`（把 repository、writer、settings、trace、時鐘包成一包）、`TaskFn`（每個工作節點的型別）、`run_sequence`（在本機依序跑完，不需要 AWS Step Functions）、`build_deps`。
2. **`pipelines/ticket.py`**：七個 task 函式
   - `embed`：缺 embedding 才呼叫 Titan，算完存回 TICKET。
   - `cluster`：跟每個群的中心向量比 cosine，≥ 0.85 取最高；都不合格就開新群。
   - `recurring`：依 `Ticket.ts` 的 UTC 日期，看「當日 + 前 13 個日期」裡同群有沒有 ≥ 5 筆。
   - `name_gap`：只有 recurring 才呼叫 Claude 命名教學缺口，結果存操作紀錄，重試不重呼叫。
   - `decide`：CREATE／KEEP／NO_FEATURE。
   - `create_v1`：取 active 規則 → 產生五段內容 → 驗證 → 建 Tutorial、分配版號、建版本。
   - `publish`：呼叫 Phase 08 的 `content.publish` 上架。
3. **一個本機端到端測試**：用 `FakeWriter` 假裝模型，從五筆工單跑到「未發布的 v1」再 `publish`，全程用 `moto` 模擬 AWS。

做完之後，`uv run pytest tests/integration/test_ticket_pipeline.py -v` 會綠燈，而且你可以在 S3（moto 模擬的）裡看到 `tutorials/prepare-meeting/v1.md` 與 `site/prepare-meeting/v1.html`。

---

## 2. 它在整張地圖的位置

```text
基礎層          01 骨架 -> 02 模型與鍵 -> 03 Repository(本機) -> 04 AWS 基礎建設
                                                                      |
AI 與內容層     05 Writing(Bedrock) -> 06 規則注入 -> 07 建立版本 -> 08 發布與退役 -> 09 圖譜查詢
                                                                                        |
接入層          10 Ingress 驗簽 -> 11 Rote 判定 -> 12 Rote Agent -------------------------+
                                                                                        |
流程層          13 Ticket Analysis -> 14 Step Functions 上線 -> 15 Feedback/View 匯入 -> 16 Release Update
                ^^^^^^^^^^^^^^^^^^^                                                     |
                你在這裡                                                                 |
學習層          17 Review:REFINE -> 18 Review:候選規則+排程 -> 19 Analytics 指標 -> 20 規則驗證
                                                                                        |
展示與驗收層    21 Demo 種子資料 -> 22 靜態教學站 -> 23 Demo 控制台 -> 24 失敗復原驗收 -> 25 安全與當日準備
```

這一階段是「AI 與內容層」與「接入層」的第一個交會點：它消費 Phase 02–09 幾乎全部的產出，而它自己的 `TASKS` 字典會在 Phase 14 被 ASL 一對一對應成 Step Functions 的節點。

---

## 3. 開始前檢查

| 前置 | 驗證指令 | 預期輸出 |
|---|---|---|
| Phase 12 完成 | `uv run pytest tests/unit/test_rote_agent.py -v` | 全部 PASS |
| Phase 05 的 writer 與 cosine | `uv run python -c "from training_kb.writing.client import FakeWriter, CallTrace, cosine, centroid, build_writer; print('ok')"` | 印出 `ok` |
| Phase 06 的規則注入 | `uv run python -c "from training_kb.writing.rules import rules_for_content; print('ok')"` | 印出 `ok` |
| Phase 07／08 的內容與發布 | `uv run python -c "from training_kb.content import allocate_version, create_tutorial, create_version, validate_content, publish; from training_kb.site import SiteRenderer; print('ok')"` | 印出 `ok` |
| Phase 05 的 schema 與 prompt | `uv run python -c "from training_kb.writing.schemas import GapNaming, TutorialDraft; from training_kb.writing.prompts import prompt_name_gap, prompt_write_tutorial; print('ok')"` | 印出 `ok` |
| Repository 的讀取函式 | 見下方指令 | 印出 `ok` |

```bash
uv run python - <<'PY'
from training_kb.repository import Repository, build_repository
for name in [
    "get_ticket", "put_ticket", "list_tickets",
    "get_feature", "list_features",
    "get_tutorial", "put_tutorial", "find_active_tutorial_for_feature",
    "list_rules", "next_counter",
    "begin_operation", "load_operation", "update_operation",
]:
    assert hasattr(Repository, name), name
print("ok")
PY
```

預期輸出：`ok`。任何一個 `AssertionError` 都代表對應的 Phase 03／09 還沒做完，先回去補，不要在這裡自己另外寫一個讀取函式。

另外確認 `pipelines` 套件目錄存在（Phase 01 建立骨架時就該有）：

```bash
ls src/training_kb/pipelines/__init__.py
```

預期輸出：`src/training_kb/pipelines/__init__.py`。如果檔案不在，先 `mkdir -p src/training_kb/pipelines && touch src/training_kb/pipelines/__init__.py`。

---

## 4. 名詞小抄

| 名詞 | 白話解釋 | 在本階段哪裡用到 |
|---|---|---|
| pipeline（流程） | 一串固定順序的工作節點。本案有三條，這階段做第一條。 | `pipelines/ticket.py` |
| task（工作節點） | 流程裡的一步。輸入是 `state`，輸出是新的 `state`。 | `TASKS` 裡的七個函式 |
| `state` | 一個小 dict，只放 ID 與小型判斷結果，**不放向量、不放全文**（設計 §14.3）。 | 每個 task 的第一個參數 |
| `Deps` | 把「這個 task 需要的外部東西」包成一包：資料庫、模型、設定、呼叫紀錄、時鐘。 | `pipelines/common.py` |
| embedding（向量） | 把一段文字變成 1024 個數字，讓電腦能比較「意思像不像」。 | `task_embed` |
| Titan | AWS 的 embedding 模型，本案用 `amazon.titan-embed-text-v2:0`。 | `task_embed` |
| cosine（餘弦相似度） | 兩個向量的夾角餘弦，範圍 −1 到 1。越接近 1 越像。 | `task_cluster` |
| 群中心（centroid） | 一群向量的平均向量，代表這一群的「中心點」。 | `task_cluster` |
| cluster_id | 語意分群的編號，例如 `c12`。教學建立後會固定寫進 `Tutorial.cluster_id`（D29）。 | `task_cluster`、`task_create_v1` |
| recurring | 「重複出現的問題」。同一群在窗口內至少 5 筆才算。 | `task_recurring` |
| UTC 日期窗口 | 當日與前 13 個 UTC 日期組成的 14 個日期集合，不是「往前推 14×24 小時」。 | `recurring_window` |
| Knowledge Gap（教學缺口） | 「使用者一直問、但沒有教學」的那件事，用一句話描述。 | `task_name_gap` |
| slug | 教學的網址用短名稱，例如 `prepare-meeting`。ASCII 小寫、用連字號分隔。 | `task_name_gap` |
| kebab-case | 全小寫、單字之間用 `-` 連接的寫法。 | `normalize_slug` |
| CREATE／KEEP | 這次分析的動作：建立新教學，或什麼都不改只記原因。 | `task_decide` |
| NO_FEATURE | 本案新增的第三種結果：gap 對不到既有 Feature，保留診斷紀錄但不建教學（F13）。 | `task_decide` |
| active Tutorial | `status=active` 的教學，**即使 `current_version` 還是 `None`（尚未發布）也算**（F12）。 | `task_decide` |
| 操作紀錄（operation） | Phase 03 提供的私有紀錄，用來去重與「重試重用上次結果」（設計 §18 的 O2）。 | `task_name_gap`、`task_decide` |
| `rules_applied` | 這一版寫作時實際注入 prompt 的規則 ID 清單，是規則套用的唯一權威（D17、F29）。 | `task_create_v1` |
| `reason` | 版本產生的原因。Ticket Analysis 的第一版固定是 `gap:<cluster_id>`。 | `task_create_v1` |
| `run_sequence` | 本機依序跑完所有 task 的小函式，讓你不必開 AWS 就能測整條流程。 | `pipelines/common.py` |

---

## 5. 設計說明

### 5.1 設計文件 §7.3 的流程長什麼樣子

```text
        新的、合法且未重複處理的 Ticket（由 Phase 10 的 accept_ticket 啟動）
                                  |
                                  v
  state = {"ticket_id": "t_...", "operation_id": "ingest:ticket:t_...", "policy": "formal"}
                                  |
        +-------------------------+-------------------------+
        |                                                   |
   [1] embed                                                |
     ticket.embedding 有值？ --是--> 跳過，不呼叫 Titan       |
        | 否                                                 |
        v                                                    |
     writer.embed(ticket.text) -> 1024 維 -> 存回 TICKET      |
        |                                                    |
        v                                                    |
   [2] cluster                                               |
     跟每個既有群的「中心向量」比 cosine                       |
     >= 0.85 的群裡取分數最高者（同分取 cluster_id 小的）       |
     都不合格 -> new_cluster_id(repo) = "c" + next_counter     |
        |                                                    |
        v                                                    |
   [3] recurring                                             |
     anchor = Ticket.ts 的 UTC 日期                           |
     window = {anchor, anchor-1, ..., anchor-13}（14 個日期）  |
     同群工單的 UTC 日期落在 window 內 >= 5 筆？               |
        |                                                    |
        +--- 否 ---> recurring=False -----------------------+ |
        | 是                                                | |
        v                                                  | |
   [4] name_gap（唯一會呼叫 Claude 判斷的節點）               | |
     操作紀錄已有結果？ --是--> 直接用，不重呼叫模型           | |
        | 否                                                | |
        v                                                  | |
     prompt_name_gap -> GapNaming{gap, feature_id, slug}    | |
     程式驗證：feature_id 必須存在；slug 轉成合法 kebab-case  | |
                並且跟既有 Tutorial 不撞名（撞了加 -2）        | |
        |                                                  | |
        v                                                  v |
   [5] decide                                                |
     recurring=False ------------------> KEEP（未達門檻）      |
     feature_id 無效 ------------------> NO_FEATURE（留紀錄）  |
     該 Feature 已有 active Tutorial ---> KEEP（記原因）       |
     其他 ------------------------------> CREATE               |
        |                                                     |
        v                                                     |
   [6] create_v1（只有 CREATE 才做）                            |
     rules_for_content(active 規則) -> rules_block, rule_ids    |
     prompt_write_tutorial -> TutorialDraft（五段）             |
     validate_content（每步恰好一個既有 Feature）               |
     create_tutorial -> allocate_version(reason="gap:c12")     |
                     -> create_version（published_at = None）   |
        |                                                      |
        v                                                      |
   [7] publish                                                 |
     content.publish([version_id]) -> current_version 切到 v1   |
        |                                                      |
        v                                                      v
   state 最終帶著 action / slug / version_id / published / keep_reason
```

### 5.2 分群是怎麼比的

設計文件 §7.3 與 F10 都說得很清楚：**跟群中心比，不是跟最近的那一筆比，也不是跟群裡每一筆都比。**

```text
已有的工單（同一個 project）
   c1: [t_101]------o          c2: [t_201]--o
        [t_102]-----o               [t_202]-o
        [t_103]-----o
                    |                        |
              算平均 = 群中心 C1        算平均 = 群中心 C2
                    |                        |
                    v                        v
              cosine(新工單, C1)        cosine(新工單, C2)
                  = 0.91                   = 0.83
                    |                        |
                    +-----------+------------+
                                |
                  兩者取 >= 0.85 且分數最高者 -> c1
                  （若兩個都是 0.91，取 cluster_id 字串較小的那個）
                  （若都 < 0.85，開新群 c3 = "c" + next_counter("cluster")）
```

門檻 `0.85` 來自 `Thresholds.cosine_cluster`（Phase 01 定義），不要在這裡寫死數字。

**為什麼同分要取 cluster_id 升序？** 設計文件 §7.3 明說「同分依 cluster_id 升序」。沒有這一條，同樣的資料在不同機器上可能分到不同群，測試就會時好時壞。

### 5.3 recurring 的 14 天不是 14×24 小時

F11 選的是 C：「以每日 UTC 日界線計算當日及前 13 個日期，該日內的所有事件歸同一窗口。」

```text
 anchor = 2026-09-13（這張工單 ts 的 UTC 日期）

 窗口（共 14 個日期，含頭含尾）：
   2026-08-31  2026-09-01  ...  2026-09-12  2026-09-13
   ^^^^^^^^^^                                ^^^^^^^^^^
   最早一天                                   anchor

 判斷方式：把同群每一張工單的 ts 換成 UTC 日期，看它在不在這 14 個日期裡。

   t_101  ts = 2026-08-30T23:59:59Z -> 2026-08-30  ✗ 窗口外（差一天）
   t_102  ts = 2026-08-31T00:00:00Z -> 2026-08-31  ✓
   t_103  ts = 2026-09-13T23:59:59Z -> 2026-09-13  ✓（同一天，不看時分秒）
```

> **本計劃選擇**：F11 沒有指定「當日」是誰的當日。本階段選 **觸發這條流程的那張 Ticket 的 `ts` UTC 日期** 當 anchor，理由是同一批輸入不管什麼時候重跑都會得到同一個答案（測試與種子資料才可重算）。另一種做法是用「執行當日」，兩者在設計文件 §11.1 的 Demo 種子（工單落在執行當日及前 13 個 UTC 日期）會得到相同結果。這一點在文件裡標成本計劃選擇，不是設計文件的既有答案。

門檻 `14` 與 `5` 分別來自 `Thresholds.recurring_days` 與 `Thresholds.recurring_min_tickets`。

### 5.4 state 裡放什麼、不放什麼

設計文件 §14.3：「state 間傳 ID、必要的小型判斷結果或 S3 key，不攜帶全文與向量陣列。」

```text
state（會在 Step Functions 的節點之間傳來傳去，所以要小）
├── ticket_id      : "t_gh-indie-builder-training-kb-demo-881"   <- 進來就有
├── operation_id   : "ingest:ticket:t_gh-..."                    <- 進來就有
├── policy         : "formal"                                    <- 進來就有
├── embedding_done : True                 (task_embed 產生)
├── cluster_id     : "c12"                (task_cluster 產生)
├── recurring      : True                 (task_recurring 產生)
├── gap            : "找不到會前摘要入口"  (task_name_gap 產生，可為 None)
├── feature_id     : "Prepare"            (task_name_gap 產生，可為 None)
├── slug           : "prepare-meeting"    (task_name_gap 或 task_decide 產生)
├── action         : "CREATE"|"KEEP"|"NO_FEATURE"   (task_decide 產生)
├── keep_reason    : "Feature Prepare 已有 active 教學 prepare-meeting"
├── version_id     : "prepare-meeting@v1" (task_create_v1 產生)
└── published      : True                 (task_publish 產生)

不放：ticket.embedding（1024 個 float）、教學全文、diff、回饋原文。
需要的時候再用 ID 去 repository 讀。
```

### 5.5 本機 run_sequence 與雲端 ASL 的分工

本機測試要能一口氣跑完七個 task，但 Step Functions 的分支是 Choice state 做的。為了讓同一份 task 程式兩邊都能用：

- **每個 task 自己檢查前置條件**。例如 `task_name_gap` 看到 `state["recurring"]` 是 `False` 就原樣回傳；`task_create_v1` 看到 `state["action"] != "CREATE"` 就原樣回傳。
- **`run_sequence` 不做任何分支**，就是依序呼叫。
- Phase 14 的 ASL 會在 `recurring` 與 `decide` 之後各放一個 Choice state，省掉不必要的 Lambda 呼叫。兩邊的最終結果一樣。

### 5.6 本階段會動到的檔案

```text
src/training_kb/
  pipelines/
    __init__.py       （Phase 01 已建立，不動）
    common.py         <-- 新增：Deps、TaskFn、run_sequence、build_deps、require、merged
    ticket.py         <-- 新增：七個 task + TASKS + new_cluster_id + 純函式小工具

tests/
  unit/
    test_pipelines_common.py    （Task 1）
    test_ticket_cluster.py      （Task 3：cosine 0.85 兩側、同分排序）
    test_ticket_recurring.py    （Task 4：UTC 日期窗口、四筆／五筆）
    test_ticket_name_gap.py     （Task 5：slug 驗證、重試不重呼叫）
    test_ticket_decide.py       （Task 6：active 未發布仍 KEEP、retired 不阻擋、NO_FEATURE）
  integration/
    test_ticket_pipeline.py     （Task 2、7、8、9：embed、create_v1、publish、端到端）
```

---

## 6. 工作項目

### Task 1：pipelines/common.py 流程骨架

**目的**：做出三條流程共用的 `Deps`、`TaskFn`、`run_sequence`、`build_deps`。

**檔案**：
- 新增：`src/training_kb/pipelines/common.py`
- 測試：`tests/unit/test_pipelines_common.py`

**介面**：
- 消費：`repository.build_repository(settings) -> Repository`（Phase 03）、`writing.client.build_writer(settings, trace) -> BedrockWriter`、`writing.client.CallTrace`（Phase 05）、`clock.now_utc`（Phase 01）
- 產出：
  - `pipelines.common.Deps`（dataclass：`repo`、`writer`、`settings`、`trace`、`now`）
  - `pipelines.common.TaskFn = Callable[[dict, Deps], dict]`
  - `pipelines.common.run_sequence(tasks: list[tuple[str, TaskFn]], state: dict, deps: Deps) -> dict`
  - `pipelines.common.build_deps(settings: Settings) -> Deps`
  - `pipelines.common.require(state: dict, *keys: str) -> tuple`（簡報未列，本階段新增）
  - `pipelines.common.merged(state: dict, **updates: Any) -> dict`（簡報未列，本階段新增）

- [ ] **步驟 1：寫測試**

```python
# tests/unit/test_pipelines_common.py
from datetime import UTC, datetime

import pytest

from training_kb.errors import PermanentError
from training_kb.pipelines.common import Deps, merged, require, run_sequence

NOW = datetime(2026, 9, 13, 0, 0, 0, tzinfo=UTC)


def fake_deps() -> Deps:
    return Deps(repo=None, writer=None, settings=None, trace=None, now=lambda: NOW)


def test_merged_does_not_mutate_input():
    state = {"a": 1}

    out = merged(state, b=2)

    assert out == {"a": 1, "b": 2}
    assert state == {"a": 1}


def test_require_returns_values_in_order():
    assert require({"a": 1, "b": "x"}, "a", "b") == (1, "x")


def test_require_raises_and_names_all_missing_keys():
    with pytest.raises(PermanentError) as info:
        require({"a": 1}, "a", "b", "c")

    assert "b" in str(info.value)
    assert "c" in str(info.value)


def test_run_sequence_threads_state_through_tasks():
    def step_one(state: dict, deps: Deps) -> dict:
        return merged(state, one=True)

    def step_two(state: dict, deps: Deps) -> dict:
        return merged(state, two=state["one"])

    out = run_sequence([("one", step_one), ("two", step_two)], {"seed": 1}, fake_deps())

    assert out == {"seed": 1, "one": True, "two": True}


def test_run_sequence_rejects_task_returning_non_dict():
    def broken(state: dict, deps: Deps) -> dict:
        return None  # type: ignore[return-value]

    with pytest.raises(PermanentError):
        run_sequence([("broken", broken)], {}, fake_deps())


def test_run_sequence_lets_errors_propagate_with_task_name():
    def boom(state: dict, deps: Deps) -> dict:
        raise PermanentError("裡面壞掉了")

    with pytest.raises(PermanentError) as info:
        run_sequence([("boom", boom)], {}, fake_deps())

    assert "boom" in str(info.value)
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：`uv run pytest tests/unit/test_pipelines_common.py -v`
預期：FAIL，`ModuleNotFoundError: No module named 'training_kb.pipelines.common'`，因為檔案還不存在。

- [ ] **步驟 3：寫最少的程式讓測試通過**

```python
# src/training_kb/pipelines/common.py
"""三條教學流程共用的執行骨架。

流程本身不決定分支，分支由 Step Functions 的 Choice state 或每個 task
自己的前置條件檢查負責；這裡只負責把 state 依序穿過一串 task。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from training_kb.clock import now_utc
from training_kb.config import Settings
from training_kb.errors import PermanentError
from training_kb.repository import Repository, build_repository
from training_kb.writing.client import CallTrace, Writer, build_writer


@dataclass
class Deps:
    """一個 task 執行時需要的所有外部資源。

    now 是一個「拿現在時間」的函式而不是 datetime，方便測試時換成固定時間。
    """

    repo: Repository
    writer: Writer
    settings: Settings
    trace: CallTrace
    now: Callable[[], datetime]


# 每個工作節點的形狀：吃 state 與 Deps，回傳新的 state。
TaskFn = Callable[[dict, Deps], dict]


def merged(state: dict, **updates: Any) -> dict:
    """回傳一份新的 state；原本的 state 不被改動。"""
    out = dict(state)
    out.update(updates)
    return out


def require(state: dict, *keys: str) -> tuple:
    """取出 state 裡的必要欄位；缺任何一個就一次列出來再拋錯。"""
    missing = [key for key in keys if state.get(key) is None]
    if missing:
        raise PermanentError(f"state 缺少必要欄位：{', '.join(missing)}")
    return tuple(state[key] for key in keys)


def run_sequence(tasks: list[tuple[str, TaskFn]], state: dict, deps: Deps) -> dict:
    """在本機依序執行一串 task，供測試與 demo CLI 使用。

    正式環境由 Step Functions 逐一呼叫 handlers/pipeline_task.py，
    這裡只是同一組 task 函式的另一種驅動方式。
    """
    current = dict(state)
    for name, fn in tasks:
        try:
            result = fn(current, deps)
        except PermanentError as exc:
            raise PermanentError(f"task {name} 失敗：{exc}") from exc
        if not isinstance(result, dict):
            raise PermanentError(f"task {name} 必須回傳 dict，實際回傳 {type(result).__name__}")
        current = result
    return current


def build_deps(settings: Settings) -> Deps:
    """用設定組出真的 Deps（會連到 AWS）。測試請自己組 Deps，不要呼叫這個。"""
    trace = CallTrace()
    return Deps(
        repo=build_repository(settings),
        writer=build_writer(settings, trace),
        settings=settings,
        trace=trace,
        now=now_utc,
    )
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：`uv run pytest tests/unit/test_pipelines_common.py -v`
預期：6 個測試全部 PASS。

- [ ] **步驟 5：commit**

```bash
git add tests/unit/test_pipelines_common.py src/training_kb/pipelines/common.py
git commit -m "feat(pipelines): 加入流程共用的執行骨架"
```

---

### Task 2：task_embed 計算並保存向量

**目的**：缺 embedding 才呼叫 Titan，算完存回 TICKET，state 不帶向量。

**檔案**：
- 新增：`src/training_kb/pipelines/ticket.py`
- 測試：`tests/integration/test_ticket_pipeline.py`

**介面**：
- 消費：`repo.get_ticket(ticket_id) -> Ticket | None`、`repo.put_ticket(t)`（Phase 03／09）、`writer.embed(text, *, operation_id, node) -> list[float]`（Phase 05）
- 產出：`pipelines.ticket.task_embed(state: dict, deps: Deps) -> dict`（state 新增 `embedding_done: bool`）

- [ ] **步驟 1：寫測試**

```python
# tests/integration/test_ticket_pipeline.py
from datetime import UTC, datetime

import boto3
import pytest
from moto import mock_aws

from training_kb.config import Settings, Thresholds
from training_kb.models import Ticket
from training_kb.pipelines.common import Deps
from training_kb.pipelines.ticket import task_embed
from training_kb.repository import Repository
from training_kb.writing.client import CallTrace, FakeWriter

NOW = datetime(2026, 9, 13, 6, 0, 0, tzinfo=UTC)
TABLE = "training_kb_ticket_test"
BUCKET = "training-kb-ticket-test"


@pytest.fixture
def repo():
    with mock_aws():
        ddb = boto3.resource("dynamodb", region_name="us-east-1")
        ddb.create_table(
            TableName=TABLE,
            KeySchema=[
                {"AttributeName": "PK", "KeyType": "HASH"},
                {"AttributeName": "SK", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "PK", "AttributeType": "S"},
                {"AttributeName": "SK", "AttributeType": "S"},
                {"AttributeName": "target", "AttributeType": "S"},
            ],
            GlobalSecondaryIndexes=[
                {
                    "IndexName": "by_target",
                    "KeySchema": [{"AttributeName": "target", "KeyType": "HASH"}],
                    "Projection": {"ProjectionType": "ALL"},
                }
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket=BUCKET)
        yield Repository(ddb.Table(TABLE), s3, BUCKET)


def settings(dimensions: int = 4) -> Settings:
    return Settings(
        aws_region="us-east-1",
        table_name=TABLE,
        bucket_name=BUCKET,
        project_id="demo-project",
        embed_model_id="amazon.titan-embed-text-v2:0",
        embed_dimensions=dimensions,
        gen_model_id="fake-claude",
        github_webhook_secret="s3cret",
        thresholds=Thresholds(),
    )


def make_deps(repo, writer, dimensions: int = 4) -> Deps:
    return Deps(
        repo=repo,
        writer=writer,
        settings=settings(dimensions),
        trace=writer.trace,
        now=lambda: NOW,
    )


def ticket(ticket_id: str, text: str, ts: str, **kwargs) -> Ticket:
    return Ticket(
        id=ticket_id,
        source="email",
        text=text,
        author=kwargs.pop("author", "u_01"),
        ts=ts,
        project_id="demo-project",
        **kwargs,
    )


def test_embed_calls_titan_once_and_saves_vector(repo):
    repo.put_ticket(ticket("t_1", "會前摘要在哪裡開啟？", "2026-09-13T02:00:00Z"))
    writer = FakeWriter(embeddings={"會前摘要在哪裡開啟？": [1.0, 0.0, 0.0, 0.0]}, trace=CallTrace())
    deps = make_deps(repo, writer)

    out = task_embed({"ticket_id": "t_1", "operation_id": "op-1"}, deps)

    assert out["embedding_done"] is True
    assert "embedding" not in out  # state 不帶向量
    assert repo.get_ticket("t_1").embedding == [1.0, 0.0, 0.0, 0.0]
    assert writer.trace.count() == 1


def test_embed_skips_when_vector_already_saved(repo):
    repo.put_ticket(
        ticket("t_1", "會前摘要在哪裡開啟？", "2026-09-13T02:00:00Z", embedding=[1.0, 0.0, 0.0, 0.0])
    )
    writer = FakeWriter(embeddings={}, trace=CallTrace())
    deps = make_deps(repo, writer)

    out = task_embed({"ticket_id": "t_1", "operation_id": "op-1"}, deps)

    assert out["embedding_done"] is True
    assert writer.trace.count() == 0


def test_embed_rejects_wrong_dimension(repo):
    from training_kb.errors import PermanentError

    repo.put_ticket(ticket("t_1", "文字", "2026-09-13T02:00:00Z"))
    writer = FakeWriter(embeddings={"文字": [1.0, 0.0]}, trace=CallTrace())
    deps = make_deps(repo, writer, dimensions=4)

    with pytest.raises(PermanentError):
        task_embed({"ticket_id": "t_1", "operation_id": "op-1"}, deps)


def test_embed_fails_when_ticket_missing(repo):
    from training_kb.errors import PermanentError

    writer = FakeWriter(embeddings={}, trace=CallTrace())
    deps = make_deps(repo, writer)

    with pytest.raises(PermanentError):
        task_embed({"ticket_id": "t_missing", "operation_id": "op-1"}, deps)
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：`uv run pytest tests/integration/test_ticket_pipeline.py -v`
預期：FAIL，`ModuleNotFoundError: No module named 'training_kb.pipelines.ticket'`。

- [ ] **步驟 3：寫最少的程式讓測試通過**

```python
# src/training_kb/pipelines/ticket.py
"""Ticket Analysis：從重複工單決定 CREATE 或 KEEP（設計文件 §7.3）。

state 內鍵：ticket_id、operation_id、policy。
每個 task 都自己檢查前置條件，遇到不該執行的情況就原樣回傳 state，
這樣同一組函式在本機 run_sequence 與雲端 Step Functions 都能用。
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date, timedelta

from training_kb.clock import parse_iso, to_iso, utc_date
from training_kb.errors import PermanentError
from training_kb.models import Ticket
from training_kb.pipelines.common import Deps, TaskFn, merged, require


def task_embed(state: dict, deps: Deps) -> dict:
    """缺 embedding 才呼叫 Titan，算完存回 TICKET（分析工單 Rule 1）。"""
    ticket_id, operation_id = require(state, "ticket_id", "operation_id")
    ticket = deps.repo.get_ticket(ticket_id)
    if ticket is None:
        raise PermanentError(f"找不到工單 {ticket_id}")

    if ticket.embedding:
        # 已經算過就不再呼叫模型；「每則 Ticket 計算一次」
        return merged(state, embedding_done=True)

    vector = deps.writer.embed(ticket.text, operation_id=operation_id, node="ticket.embed")
    expected = deps.settings.embed_dimensions
    if len(vector) != expected:
        raise PermanentError(f"embedding 維度應為 {expected}，實際為 {len(vector)}")

    ticket.embedding = list(vector)
    deps.repo.put_ticket(ticket)
    return merged(state, embedding_done=True)
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：`uv run pytest tests/integration/test_ticket_pipeline.py -v`
預期：4 個測試全部 PASS。

- [ ] **步驟 5：commit**

```bash
git add tests/integration/test_ticket_pipeline.py src/training_kb/pipelines/ticket.py
git commit -m "feat(pipelines): Ticket Analysis 的向量計算節點"
```

---

### Task 3：task_cluster 群中心分群

**目的**：跟每個群的中心向量比 cosine，≥ 0.85 取最高，同分取 cluster_id 升序；都不合格就開新群。

**檔案**：
- 修改：`src/training_kb/pipelines/ticket.py`
- 測試：`tests/unit/test_ticket_cluster.py`

**介面**：
- 消費：`writing.client.cosine(a, b) -> float`、`writing.client.centroid(vectors) -> list[float]`（Phase 05）、`repo.list_tickets(project_id) -> list[Ticket]`、`repo.next_counter(name) -> int`（Phase 03）
- 產出：
  - `pipelines.ticket.new_cluster_id(repo) -> str`
  - `pipelines.ticket.pick_cluster(vector: list[float], centroids: dict[str, list[float]], threshold: float) -> str | None`（簡報未列，本階段新增的純函式，方便單獨測門檻）
  - `pipelines.ticket.task_cluster(state: dict, deps: Deps) -> dict`（state 新增 `cluster_id: str`）

- [ ] **步驟 1：寫測試**

```python
# tests/unit/test_ticket_cluster.py
import math

from training_kb.pipelines.ticket import pick_cluster
from training_kb.writing.client import cosine

# 下面兩組向量刻意用整數構成，讓 cosine 的結果在浮點數下也精確：
#   a·b = 17、|a| = sqrt(1) = 1、|b| = sqrt(17^2 + 7^2 + 6^2 + 5^2 + 1^2) = sqrt(400) = 20
#   cosine = 17 / 20 = 0.85（17.0 / 20.0 的浮點除法剛好等於字面值 0.85）
AXIS = [1.0, 0.0, 0.0, 0.0, 0.0]
ON_THRESHOLD = [17.0, 7.0, 6.0, 5.0, 1.0]
# 第一個分量稍微調小，實數值約 0.84987，穩定落在門檻下方。
BELOW_THRESHOLD = [16.99, 7.0, 6.0, 5.0, 1.0]


def test_reference_vectors_sit_on_both_sides_of_the_threshold():
    assert cosine(AXIS, ON_THRESHOLD) == 0.85
    assert cosine(AXIS, BELOW_THRESHOLD) < 0.85
    assert math.isclose(cosine(AXIS, BELOW_THRESHOLD), 0.8498, abs_tol=0.001)


def test_exactly_on_threshold_joins_the_cluster():
    assert pick_cluster(AXIS, {"c1": ON_THRESHOLD}, 0.85) == "c1"


def test_just_below_threshold_opens_a_new_cluster():
    assert pick_cluster(AXIS, {"c1": BELOW_THRESHOLD}, 0.85) is None


def test_picks_the_highest_score_among_qualified_clusters():
    centroids = {"c1": ON_THRESHOLD, "c2": [1.0, 0.0, 0.0, 0.0, 0.0]}

    assert pick_cluster(AXIS, centroids, 0.85) == "c2"  # c2 的 cosine 是 1.0


def test_ties_are_broken_by_ascending_cluster_id():
    same = [1.0, 0.0, 0.0, 0.0, 0.0]
    centroids = {"c9": list(same), "c2": list(same), "c10": list(same)}

    # 字串升序：c10 < c2 < c9
    assert pick_cluster(AXIS, centroids, 0.85) == "c10"


def test_empty_centroids_return_none():
    assert pick_cluster(AXIS, {}, 0.85) is None
```

再把分群的整合測試追加到 `tests/integration/test_ticket_pipeline.py`：

```python
from training_kb.pipelines.ticket import new_cluster_id, task_cluster

AXIS = [1.0, 0.0, 0.0, 0.0]
NEAR = [0.99, 0.1, 0.0, 0.0]
FAR = [0.0, 0.0, 1.0, 0.0]


def test_cluster_joins_existing_group(repo):
    repo.put_ticket(
        ticket("t_old", "舊工單", "2026-09-10T00:00:00Z", embedding=list(AXIS), cluster_id="c1")
    )
    repo.put_ticket(ticket("t_new", "新工單", "2026-09-13T00:00:00Z", embedding=list(NEAR)))
    writer = FakeWriter(trace=CallTrace())
    deps = make_deps(repo, writer)

    out = task_cluster({"ticket_id": "t_new", "operation_id": "op-1"}, deps)

    assert out["cluster_id"] == "c1"
    assert repo.get_ticket("t_new").cluster_id == "c1"
    assert writer.trace.count() == 0  # 分群不呼叫模型


def test_cluster_opens_new_group_when_nothing_matches(repo):
    repo.put_ticket(
        ticket("t_old", "舊工單", "2026-09-10T00:00:00Z", embedding=list(AXIS), cluster_id="c1")
    )
    repo.put_ticket(ticket("t_new", "新工單", "2026-09-13T00:00:00Z", embedding=list(FAR)))
    deps = make_deps(repo, FakeWriter(trace=CallTrace()))

    out = task_cluster({"ticket_id": "t_new", "operation_id": "op-1"}, deps)

    assert out["cluster_id"] != "c1"
    assert out["cluster_id"].startswith("c")


def test_cluster_keeps_existing_cluster_id_on_retry(repo):
    repo.put_ticket(
        ticket("t_new", "新工單", "2026-09-13T00:00:00Z", embedding=list(AXIS), cluster_id="c12")
    )
    deps = make_deps(repo, FakeWriter(trace=CallTrace()))

    out = task_cluster({"ticket_id": "t_new", "operation_id": "op-1"}, deps)

    assert out["cluster_id"] == "c12"


def test_new_cluster_id_uses_counter(repo):
    first = new_cluster_id(repo)
    second = new_cluster_id(repo)

    assert first == "c1"
    assert second == "c2"
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：`uv run pytest tests/unit/test_ticket_cluster.py -v`
預期：FAIL，`ImportError: cannot import name 'pick_cluster' from 'training_kb.pipelines.ticket'`。

- [ ] **步驟 3：寫最少的程式讓測試通過**

在 `ticket.py` 的 import 區補上：

```python
from training_kb.writing.client import centroid, cosine
```

再加上三個函式：

```python
def new_cluster_id(repo) -> str:
    """配一個新的群編號；由程式配置並保留，不從模型輸出推導（設計 §7.3）。"""
    return f"c{repo.next_counter('cluster')}"


def pick_cluster(
    vector: list[float], centroids: dict[str, list[float]], threshold: float
) -> str | None:
    """跟每個群的中心向量比 cosine，回傳最合適的 cluster_id。

    規則（F10 與設計 §7.3）：
      1. 只看 cosine >= threshold 的群；
      2. 其中取分數最高者；
      3. 同分取 cluster_id 字串升序的第一個。
    都不合格回傳 None，代表要開新群。
    """
    best_id: str | None = None
    best_score = -2.0
    for cluster_id in sorted(centroids):
        score = cosine(vector, centroids[cluster_id])
        if score >= threshold and score > best_score:
            best_id = cluster_id
            best_score = score
    return best_id


def task_cluster(state: dict, deps: Deps) -> dict:
    """把工單歸到既有群或開新群，並把 cluster_id 寫回 TICKET。"""
    (ticket_id,) = require(state, "ticket_id")
    ticket = deps.repo.get_ticket(ticket_id)
    if ticket is None:
        raise PermanentError(f"找不到工單 {ticket_id}")
    if not ticket.embedding:
        raise PermanentError(f"工單 {ticket_id} 還沒有 embedding，不能分群")

    if ticket.cluster_id:
        # 重試時沿用已保存的結果，不重新分群（設計 §14.2）
        return merged(state, cluster_id=ticket.cluster_id)

    groups: dict[str, list[list[float]]] = {}
    for other in deps.repo.list_tickets(ticket.project_id):
        if other.id == ticket.id or not other.cluster_id or not other.embedding:
            continue
        groups.setdefault(other.cluster_id, []).append(list(other.embedding))

    centroids = {cluster_id: centroid(vectors) for cluster_id, vectors in groups.items()}
    picked = pick_cluster(
        list(ticket.embedding), centroids, deps.settings.thresholds.cosine_cluster
    )
    cluster_id = picked if picked is not None else new_cluster_id(deps.repo)

    ticket.cluster_id = cluster_id
    deps.repo.put_ticket(ticket)
    return merged(state, cluster_id=cluster_id)
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：`uv run pytest tests/unit/test_ticket_cluster.py tests/integration/test_ticket_pipeline.py -v`
預期：全部 PASS（單元 6 個 + 整合 8 個）。

> 如果 `test_reference_vectors_sit_on_both_sides_of_the_threshold` 的第一條斷言 FAIL（`cosine(AXIS, ON_THRESHOLD) != 0.85`），代表 Phase 05 的 `cosine` 不是用 `dot / (norm_a * norm_b)` 算的。這時把斷言改成 `cosine(AXIS, ON_THRESHOLD) >= 0.85` 並在該行加註原因，其餘測試不變。

- [ ] **步驟 5：commit**

```bash
git add tests/unit/test_ticket_cluster.py tests/integration/test_ticket_pipeline.py \
        src/training_kb/pipelines/ticket.py
git commit -m "feat(pipelines): 以群中心 cosine 分群並配置新群編號"
```

---

### Task 4：task_recurring 的 UTC 日期窗口

**目的**：依 `Ticket.ts` 的 UTC 日期算出「當日 + 前 13 個日期」，同群落在集合內 ≥ 5 筆才算 recurring。

**檔案**：
- 修改：`src/training_kb/pipelines/ticket.py`
- 測試：`tests/unit/test_ticket_recurring.py`

**介面**：
- 消費：`clock.parse_iso(s) -> datetime`、`clock.utc_date(dt) -> date`（Phase 01）、`repo.list_tickets(project_id)`
- 產出：
  - `pipelines.ticket.recurring_window(anchor: date, days: int) -> set[date]`（簡報未列，本階段新增）
  - `pipelines.ticket.count_in_window(ticket_dates: list[date], window: set[date]) -> int`（簡報未列，本階段新增）
  - `pipelines.ticket.task_recurring(state: dict, deps: Deps) -> dict`（state 新增 `recurring: bool`）

- [ ] **步驟 1：寫測試**

```python
# tests/unit/test_ticket_recurring.py
from datetime import date

from training_kb.clock import parse_iso, utc_date
from training_kb.pipelines.ticket import count_in_window, recurring_window


def test_window_has_exactly_fourteen_dates():
    window = recurring_window(date(2026, 9, 13), 14)

    assert len(window) == 14
    assert date(2026, 9, 13) in window   # 當日
    assert date(2026, 8, 31) in window   # 前第 13 個日期
    assert date(2026, 8, 30) not in window


def test_utc_day_boundary_is_the_cut_line():
    window = recurring_window(date(2026, 9, 13), 14)

    inside_start = utc_date(parse_iso("2026-08-31T00:00:00Z"))
    outside = utc_date(parse_iso("2026-08-30T23:59:59Z"))
    same_day_late = utc_date(parse_iso("2026-09-13T23:59:59Z"))

    assert inside_start in window
    assert outside not in window
    assert same_day_late in window


def test_events_in_the_same_utc_day_share_one_bucket():
    window = recurring_window(date(2026, 9, 13), 14)
    morning = utc_date(parse_iso("2026-09-13T00:00:01Z"))
    evening = utc_date(parse_iso("2026-09-13T23:59:58Z"))

    assert morning == evening
    assert count_in_window([morning, evening], window) == 2


def test_four_tickets_are_not_recurring_and_five_are():
    window = recurring_window(date(2026, 9, 13), 14)
    four = [date(2026, 9, 10), date(2026, 9, 11), date(2026, 9, 12), date(2026, 9, 13)]
    five = [*four, date(2026, 9, 9)]

    assert count_in_window(four, window) == 4
    assert count_in_window(five, window) == 5


def test_dates_outside_the_window_do_not_count():
    window = recurring_window(date(2026, 9, 13), 14)
    dates = [date(2026, 9, 13), date(2026, 8, 30), date(2026, 8, 29), date(2026, 7, 1)]

    assert count_in_window(dates, window) == 1
```

追加整合測試到 `tests/integration/test_ticket_pipeline.py`：

```python
from training_kb.pipelines.ticket import task_recurring


def seed_cluster(repo, count: int, first_day: int) -> None:
    for index in range(count):
        repo.put_ticket(
            ticket(
                f"t_seed{index}",
                f"問題 {index}",
                f"2026-09-{first_day + index:02d}T09:00:00Z",
                embedding=list(AXIS),
                cluster_id="c12",
            )
        )


def test_recurring_is_false_with_four_tickets(repo):
    seed_cluster(repo, 4, 10)
    deps = make_deps(repo, FakeWriter(trace=CallTrace()))
    state = {"ticket_id": "t_seed3", "operation_id": "op-1", "cluster_id": "c12"}

    out = task_recurring(state, deps)

    assert out["recurring"] is False


def test_recurring_is_true_with_five_tickets(repo):
    seed_cluster(repo, 5, 9)
    deps = make_deps(repo, FakeWriter(trace=CallTrace()))
    state = {"ticket_id": "t_seed4", "operation_id": "op-1", "cluster_id": "c12"}

    out = task_recurring(state, deps)

    assert out["recurring"] is True


def test_recurring_ignores_tickets_outside_the_window(repo):
    seed_cluster(repo, 4, 10)
    repo.put_ticket(
        ticket("t_old", "很久以前", "2026-07-01T09:00:00Z", embedding=list(AXIS), cluster_id="c12")
    )
    deps = make_deps(repo, FakeWriter(trace=CallTrace()))
    state = {"ticket_id": "t_seed3", "operation_id": "op-1", "cluster_id": "c12"}

    out = task_recurring(state, deps)

    assert out["recurring"] is False


def test_recurring_ignores_other_clusters(repo):
    seed_cluster(repo, 4, 10)
    repo.put_ticket(
        ticket("t_other", "別群", "2026-09-12T09:00:00Z", embedding=list(FAR), cluster_id="c99")
    )
    deps = make_deps(repo, FakeWriter(trace=CallTrace()))
    state = {"ticket_id": "t_seed3", "operation_id": "op-1", "cluster_id": "c12"}

    out = task_recurring(state, deps)

    assert out["recurring"] is False
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：`uv run pytest tests/unit/test_ticket_recurring.py -v`
預期：FAIL，`ImportError: cannot import name 'recurring_window' from 'training_kb.pipelines.ticket'`。

- [ ] **步驟 3：寫最少的程式讓測試通過**

```python
def recurring_window(anchor: date, days: int) -> set[date]:
    """回傳「anchor 當日與前 days-1 個 UTC 日期」的集合（F11 選項 C）。

    days=14 時是 14 個日期，含頭含尾。這不是「往前推 14x24 小時」。
    """
    if days < 1:
        raise PermanentError(f"recurring 窗口天數必須至少 1，收到 {days}")
    return {anchor - timedelta(days=offset) for offset in range(days)}


def count_in_window(ticket_dates: list[date], window: set[date]) -> int:
    """數有幾張工單的 UTC 日期落在窗口裡。同一天的多張各算一張。"""
    return sum(1 for day in ticket_dates if day in window)


def task_recurring(state: dict, deps: Deps) -> dict:
    """判斷這一群是不是重複問題（分析工單 Rule 3）。"""
    ticket_id, cluster_id = require(state, "ticket_id", "cluster_id")
    ticket = deps.repo.get_ticket(ticket_id)
    if ticket is None:
        raise PermanentError(f"找不到工單 {ticket_id}")

    thresholds = deps.settings.thresholds
    # 本計劃選擇：以觸發這條流程的工單 ts 的 UTC 日期為 anchor，
    # 讓同一批輸入不論何時重跑都得到同一個答案。
    anchor = utc_date(parse_iso(ticket.ts))
    window = recurring_window(anchor, thresholds.recurring_days)

    same_cluster_dates = [
        utc_date(parse_iso(other.ts))
        for other in deps.repo.list_tickets(ticket.project_id)
        if other.cluster_id == cluster_id
    ]
    hits = count_in_window(same_cluster_dates, window)
    return merged(state, recurring=hits >= thresholds.recurring_min_tickets)
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：`uv run pytest tests/unit/test_ticket_recurring.py tests/integration/test_ticket_pipeline.py -v`
預期：全部 PASS（單元 5 個 + 整合 12 個）。

- [ ] **步驟 5：commit**

```bash
git add tests/unit/test_ticket_recurring.py tests/integration/test_ticket_pipeline.py \
        src/training_kb/pipelines/ticket.py
git commit -m "feat(pipelines): 以 UTC 日期窗口判定 recurring"
```

---

### Task 5：task_name_gap 命名教學缺口

**目的**：只有 recurring 才呼叫 Claude；結果存操作紀錄，重試不重呼叫；slug 要是合法 kebab-case 且不撞名。

**檔案**：
- 修改：`src/training_kb/pipelines/ticket.py`
- 測試：`tests/unit/test_ticket_name_gap.py`

**介面**：
- 消費：`writing.prompts.prompt_name_gap(ticket_texts, features) -> tuple[str, str]`、`writing.schemas.GapNaming`、`writer.generate_json(...)`（Phase 05）、`repo.list_features()`、`repo.get_feature(feature_id)`、`repo.get_tutorial(slug)`、`repo.begin_operation` / `load_operation` / `update_operation`（Phase 03）
- 產出：
  - `pipelines.ticket.normalize_slug(raw: str | None) -> str`（簡報未列，本階段新增）
  - `pipelines.ticket.unique_slug(repo, base: str) -> str`（簡報未列，本階段新增）
  - `pipelines.ticket.task_name_gap(state: dict, deps: Deps) -> dict`（state 新增 `gap`、`feature_id`、`slug`）

- [ ] **步驟 1：寫測試**

```python
# tests/unit/test_ticket_name_gap.py
from datetime import UTC, datetime

import pytest

from training_kb.errors import PermanentError
from training_kb.models import Feature, Tutorial
from training_kb.pipelines.common import Deps
from training_kb.pipelines.ticket import normalize_slug, task_name_gap, unique_slug
from training_kb.writing.client import CallTrace, FakeWriter
from training_kb.writing.schemas import GapNaming

NOW = datetime(2026, 9, 13, 6, 0, 0, tzinfo=UTC)


class StubRepo:
    """只實作 task_name_gap 會用到的方法。"""

    def __init__(self, tutorials: dict[str, Tutorial] | None = None) -> None:
        self.tutorials = tutorials or {}
        self.features = {"Prepare": Feature(feature_id="Prepare", name="Prepare", first_seen="2026-08-01T00:00:00Z")}
        self.operations: dict[str, dict] = {}
        self.tickets: list = []

    def get_tutorial(self, slug: str) -> Tutorial | None:
        return self.tutorials.get(slug)

    def get_feature(self, feature_id: str) -> Feature | None:
        return self.features.get(feature_id)

    def list_features(self) -> list[Feature]:
        return list(self.features.values())

    def list_tickets(self, project_id: str) -> list:
        return list(self.tickets)

    def begin_operation(self, operation_id: str, record: dict) -> bool:
        if operation_id in self.operations:
            return False
        self.operations[operation_id] = dict(record)
        return True

    def load_operation(self, operation_id: str) -> dict | None:
        found = self.operations.get(operation_id)
        return dict(found) if found is not None else None

    def update_operation(self, operation_id: str, patch: dict) -> None:
        self.operations.setdefault(operation_id, {}).update(patch)


def tutorial(slug: str) -> Tutorial:
    return Tutorial(
        slug=slug,
        current_version=None,
        topic="示範",
        feature_ids=["Prepare"],
        status="active",
        successor=None,
        cluster_id="c1",
    )


def make_deps(repo, writer, settings_obj) -> Deps:
    return Deps(repo=repo, writer=writer, settings=settings_obj, trace=writer.trace, now=lambda: NOW)


@pytest.fixture
def settings_obj():
    from training_kb.config import Settings, Thresholds

    return Settings(
        aws_region="us-east-1",
        table_name="t",
        bucket_name="b",
        project_id="demo-project",
        embed_model_id="amazon.titan-embed-text-v2:0",
        embed_dimensions=4,
        gen_model_id="fake-claude",
        github_webhook_secret="s",
        thresholds=Thresholds(),
    )


def test_normalize_slug_makes_ascii_kebab_case():
    assert normalize_slug("Prepare Meeting") == "prepare-meeting"
    assert normalize_slug("  Prepare--Meeting  ") == "prepare-meeting"
    assert normalize_slug("Café Notes") == "cafe-notes"
    assert normalize_slug("準備會議") == ""
    assert normalize_slug(None) == ""


def test_unique_slug_appends_two_on_collision():
    repo = StubRepo({"prepare-meeting": tutorial("prepare-meeting")})

    assert unique_slug(repo, "prepare-meeting") == "prepare-meeting-2"


def test_unique_slug_keeps_counting_up():
    repo = StubRepo(
        {
            "prepare-meeting": tutorial("prepare-meeting"),
            "prepare-meeting-2": tutorial("prepare-meeting-2"),
        }
    )

    assert unique_slug(repo, "prepare-meeting") == "prepare-meeting-3"


def test_unique_slug_rejects_invalid_base():
    with pytest.raises(PermanentError):
        unique_slug(StubRepo(), "Prepare Meeting")


def test_name_gap_skips_model_when_not_recurring(settings_obj):
    repo = StubRepo()
    writer = FakeWriter(outputs=[], trace=CallTrace())
    state = {"ticket_id": "t_1", "operation_id": "op-1", "cluster_id": "c12", "recurring": False}

    out = task_name_gap(state, make_deps(repo, writer, settings_obj))

    assert out["gap"] is None
    assert out["feature_id"] is None
    assert out["slug"] is None
    assert writer.trace.count() == 0


def test_name_gap_calls_model_and_validates_feature(settings_obj):
    repo = StubRepo()
    writer = FakeWriter(
        outputs=[GapNaming(gap="找不到會前摘要入口", feature_id="Prepare", slug="Prepare Meeting")],
        trace=CallTrace(),
    )
    state = {"ticket_id": "t_1", "operation_id": "op-1", "cluster_id": "c12", "recurring": True}

    out = task_name_gap(state, make_deps(repo, writer, settings_obj))

    assert out["gap"] == "找不到會前摘要入口"
    assert out["feature_id"] == "Prepare"
    assert out["slug"] == "prepare-meeting"
    assert writer.trace.count() == 1


def test_name_gap_drops_feature_id_that_does_not_exist(settings_obj):
    repo = StubRepo()
    writer = FakeWriter(
        outputs=[GapNaming(gap="未知功能的缺口", feature_id="NotThere", slug="unknown-gap")],
        trace=CallTrace(),
    )
    state = {"ticket_id": "t_1", "operation_id": "op-1", "cluster_id": "c12", "recurring": True}

    out = task_name_gap(state, make_deps(repo, writer, settings_obj))

    assert out["gap"] == "未知功能的缺口"
    assert out["feature_id"] is None


def test_name_gap_reuses_saved_result_on_retry(settings_obj):
    repo = StubRepo()
    writer = FakeWriter(
        outputs=[GapNaming(gap="找不到會前摘要入口", feature_id="Prepare", slug="prepare-meeting")],
        trace=CallTrace(),
    )
    deps = make_deps(repo, writer, settings_obj)
    state = {"ticket_id": "t_1", "operation_id": "op-1", "cluster_id": "c12", "recurring": True}

    first = task_name_gap(state, deps)
    second = task_name_gap(state, deps)

    assert first["gap"] == second["gap"]
    assert first["slug"] == second["slug"]
    assert writer.trace.count() == 1  # 第二次沒有再呼叫模型


def test_name_gap_falls_back_when_slug_is_unusable(settings_obj):
    repo = StubRepo()
    writer = FakeWriter(
        outputs=[GapNaming(gap="找不到會前摘要入口", feature_id="Prepare", slug="準備會議")],
        trace=CallTrace(),
    )
    state = {"ticket_id": "t_1", "operation_id": "op-1", "cluster_id": "c12", "recurring": True}

    out = task_name_gap(state, make_deps(repo, writer, settings_obj))

    # 模型給的 slug 轉不出 ASCII，就改用 feature_id 產生
    assert out["slug"] == "prepare"
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：`uv run pytest tests/unit/test_ticket_name_gap.py -v`
預期：FAIL，`ImportError: cannot import name 'normalize_slug' from 'training_kb.pipelines.ticket'`。

- [ ] **步驟 3：寫最少的程式讓測試通過**

在 `ticket.py` 的 import 區補上：

```python
from training_kb.writing.prompts import prompt_name_gap
from training_kb.writing.schemas import GapNaming
```

再加上：

```python
_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_MAX_SLUG_LEN = 60
_MAX_EVIDENCE_TICKETS = 10


def normalize_slug(raw: str | None) -> str:
    """把任意文字轉成 ASCII kebab-case；轉不出東西就回空字串。"""
    if not raw:
        return ""
    folded = unicodedata.normalize("NFKD", str(raw)).encode("ascii", "ignore").decode("ascii")
    lowered = re.sub(r"[^a-z0-9]+", "-", folded.lower())
    return lowered.strip("-")[:_MAX_SLUG_LEN].strip("-")


def unique_slug(repo, base: str) -> str:
    """base 已被既有 Tutorial 佔用時，依序試 base-2、base-3……"""
    if not _SLUG_RE.fullmatch(base):
        raise PermanentError(f"slug 必須是 ASCII kebab-case：{base!r}")
    candidate = base
    suffix = 1
    while repo.get_tutorial(candidate) is not None:
        suffix += 1
        candidate = f"{base}-{suffix}"
    return candidate


def _name_gap_operation_id(operation_id: str) -> str:
    return f"{operation_id}#name_gap"


def task_name_gap(state: dict, deps: Deps) -> dict:
    """只有 recurring 的群才交給模型命名 Knowledge Gap（分析工單 Rule 4）。"""
    if not state.get("recurring"):
        return merged(state, gap=None, feature_id=None, slug=None)

    operation_id, cluster_id = require(state, "operation_id", "cluster_id")
    node_operation = _name_gap_operation_id(operation_id)

    saved = deps.repo.load_operation(node_operation)
    if saved is not None and saved.get("result") is not None:
        # 重試時重用已保存的模型輸出（設計 §14.2）
        result = saved["result"]
        return merged(
            state,
            gap=result.get("gap"),
            feature_id=result.get("feature_id"),
            slug=result.get("slug"),
        )

    if saved is None:
        deps.repo.begin_operation(
            node_operation,
            {"task": "name_gap", "cluster_id": cluster_id, "started_at": to_iso(deps.now()), "result": None},
        )

    features = deps.repo.list_features()
    ticket_texts = [
        item.text
        for item in deps.repo.list_tickets(deps.settings.project_id)
        if item.cluster_id == cluster_id
    ][:_MAX_EVIDENCE_TICKETS]

    system, user = prompt_name_gap(ticket_texts, features)
    naming = deps.writer.generate_json(
        system=system,
        user=user,
        schema=GapNaming,
        operation_id=node_operation,
        node="ticket.name_gap",
        max_tokens=deps.settings.gen_max_tokens_judgement,
        temperature=deps.settings.gen_temperature,
    )

    gap = (naming.gap or "").strip()
    if not gap:
        raise PermanentError("模型沒有回傳 gap 說明")

    feature_id = naming.feature_id
    if feature_id is not None and deps.repo.get_feature(feature_id) is None:
        # Feature 必須存在；對不到就保留 gap，不建立 Feature（F13）
        feature_id = None

    base = normalize_slug(naming.slug) or normalize_slug(feature_id) or normalize_slug(f"gap-{cluster_id}")
    if not base:
        raise PermanentError("無法為這個 gap 產生合法 slug")
    slug = unique_slug(deps.repo, base)

    result = {"gap": gap, "feature_id": feature_id, "slug": slug}
    deps.repo.update_operation(node_operation, {"result": result, "finished_at": to_iso(deps.now())})
    return merged(state, gap=gap, feature_id=feature_id, slug=slug)
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：`uv run pytest tests/unit/test_ticket_name_gap.py -v`
預期：10 個測試全部 PASS。

- [ ] **步驟 5：commit**

```bash
git add tests/unit/test_ticket_name_gap.py src/training_kb/pipelines/ticket.py
git commit -m "feat(pipelines): 命名教學缺口並驗證 slug 與 Feature"
```

---

### Task 6：task_decide 決定 CREATE／KEEP／NO_FEATURE

**目的**：把「該不該建教學」的三種結果寫清楚，而且每一種都留下可查的原因紀錄。

**檔案**：
- 修改：`src/training_kb/pipelines/ticket.py`
- 測試：`tests/unit/test_ticket_decide.py`

**介面**：
- 消費：`repo.find_active_tutorial_for_feature(feature_id) -> Tutorial | None`、`repo.put_ticket(t, *, if_not_exists=False) -> bool`（Phase 09；它會依 `Ticket.feature_ids` 自動寫 ASKS_ABOUT 邊）、`repo.begin_operation` / `load_operation` / `update_operation`（Phase 03）
- 產出：`pipelines.ticket.task_decide(state: dict, deps: Deps) -> dict`（state 新增 `action`、`keep_reason`，可能補上 `slug`）

**三種結果的定義**（設計文件 §7.3 與 F12、F13）：

| 條件 | `action` | 會做什麼 |
|---|---|---|
| `recurring` 是 `False` | `KEEP` | 只寫原因紀錄，不碰教學 |
| `feature_id` 是 `None` | `NO_FEATURE` | 保留 gap 診斷紀錄，不建 Feature、不建 Tutorial |
| 該 Feature 已有 `status=active` 的 Tutorial（**即使尚未發布**） | `KEEP` | 寫原因紀錄，並把既有 slug 放進 state 方便除錯 |
| 其他 | `CREATE` | 交給下一個 task 建立教學 |

`retired` 的教學不算「已有教學」，所以不會阻擋 CREATE。

- [ ] **步驟 1：寫測試**

```python
# tests/unit/test_ticket_decide.py
from datetime import UTC, datetime

import pytest

from training_kb.config import Settings, Thresholds
from training_kb.models import Feature, Ticket, Tutorial
from training_kb.pipelines.common import Deps
from training_kb.pipelines.ticket import task_decide
from training_kb.writing.client import CallTrace, FakeWriter

NOW = datetime(2026, 9, 13, 6, 0, 0, tzinfo=UTC)


class StubRepo:
    def __init__(self, active_for_feature: dict[str, Tutorial] | None = None) -> None:
        self.active_for_feature = active_for_feature or {}
        self.features = {
            "Prepare": Feature(feature_id="Prepare", name="Prepare", first_seen="2026-08-01T00:00:00Z")
        }
        self.tickets = {
            "t_1": Ticket(
                id="t_1",
                source="email",
                text="會前摘要在哪裡開啟？",
                author="u_01",
                ts="2026-09-13T02:00:00Z",
                project_id="demo-project",
                cluster_id="c12",
            )
        }
        self.edges: list[tuple[str, str, str]] = []
        self.operations: dict[str, dict] = {}

    def get_ticket(self, ticket_id: str) -> Ticket | None:
        return self.tickets.get(ticket_id)

    def put_ticket(self, ticket: Ticket, *, if_not_exists: bool = False) -> bool:
        # 比照 Phase 09 的 Repository.put_ticket：有 feature_ids 就順手寫 ASKS_ABOUT 邊
        self.tickets[ticket.id] = ticket
        for feature_id in ticket.feature_ids[:1]:
            self.edges.append(("TICKET#" + ticket.id, "ASKS_ABOUT", "FEATURE#" + feature_id))
        return True

    def get_feature(self, feature_id: str) -> Feature | None:
        return self.features.get(feature_id)

    def find_active_tutorial_for_feature(self, feature_id: str) -> Tutorial | None:
        return self.active_for_feature.get(feature_id)

    def begin_operation(self, operation_id: str, record: dict) -> bool:
        if operation_id in self.operations:
            return False
        self.operations[operation_id] = dict(record)
        return True

    def load_operation(self, operation_id: str) -> dict | None:
        found = self.operations.get(operation_id)
        return dict(found) if found is not None else None

    def update_operation(self, operation_id: str, patch: dict) -> None:
        self.operations.setdefault(operation_id, {}).update(patch)


def tutorial(slug: str, status: str = "active", current: str | None = None) -> Tutorial:
    return Tutorial(
        slug=slug,
        current_version=current,
        topic="準備會議",
        feature_ids=["Prepare"],
        status=status,
        successor=None,
        cluster_id="c12",
    )


def settings_obj() -> Settings:
    return Settings(
        aws_region="us-east-1",
        table_name="t",
        bucket_name="b",
        project_id="demo-project",
        embed_model_id="amazon.titan-embed-text-v2:0",
        embed_dimensions=4,
        gen_model_id="fake-claude",
        github_webhook_secret="s",
        thresholds=Thresholds(),
    )


def make_deps(repo) -> Deps:
    writer = FakeWriter(trace=CallTrace())
    return Deps(repo=repo, writer=writer, settings=settings_obj(), trace=writer.trace, now=lambda: NOW)


def base_state(**overrides) -> dict:
    state = {
        "ticket_id": "t_1",
        "operation_id": "op-1",
        "cluster_id": "c12",
        "recurring": True,
        "gap": "找不到會前摘要入口",
        "feature_id": "Prepare",
        "slug": "prepare-meeting",
    }
    state.update(overrides)
    return state


def test_not_recurring_is_keep():
    repo = StubRepo()

    out = task_decide(base_state(recurring=False, gap=None, feature_id=None, slug=None), make_deps(repo))

    assert out["action"] == "KEEP"
    assert "recurring" in out["keep_reason"]
    assert repo.edges == []


def test_active_but_unpublished_tutorial_still_keeps():
    repo = StubRepo({"Prepare": tutorial("prepare-meeting", current=None)})

    out = task_decide(base_state(), make_deps(repo))

    assert out["action"] == "KEEP"
    assert "prepare-meeting" in out["keep_reason"]
    assert out["slug"] == "prepare-meeting"


def test_retired_tutorial_does_not_block_create():
    repo = StubRepo()  # find_active_tutorial_for_feature 對 retired 回 None

    out = task_decide(base_state(), make_deps(repo))

    assert out["action"] == "CREATE"


def test_no_feature_keeps_gap_diagnosis():
    repo = StubRepo()

    out = task_decide(base_state(feature_id=None), make_deps(repo))

    assert out["action"] == "NO_FEATURE"
    record = repo.load_operation("op-1#decide")
    assert record["action"] == "NO_FEATURE"
    assert record["gap"] == "找不到會前摘要入口"
    assert repo.edges == []


def test_create_writes_ticket_feature_and_asks_about_edge():
    repo = StubRepo()

    out = task_decide(base_state(), make_deps(repo))

    assert out["action"] == "CREATE"
    assert repo.get_ticket("t_1").feature_ids == ["Prepare"]
    assert repo.edges == [("TICKET#t_1", "ASKS_ABOUT", "FEATURE#Prepare")]


def test_decision_record_is_updated_on_retry():
    repo = StubRepo()
    deps = make_deps(repo)

    task_decide(base_state(), deps)
    task_decide(base_state(), deps)

    assert repo.load_operation("op-1#decide")["action"] == "CREATE"


def test_ticket_missing_raises():
    from training_kb.errors import PermanentError

    repo = StubRepo()
    repo.tickets.clear()

    with pytest.raises(PermanentError):
        task_decide(base_state(), make_deps(repo))
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：`uv run pytest tests/unit/test_ticket_decide.py -v`
預期：FAIL，`ImportError: cannot import name 'task_decide' from 'training_kb.pipelines.ticket'`。

- [ ] **步驟 3：寫最少的程式讓測試通過**

在 `ticket.py` 加上（不需要新的 import）：

```python
def _decide_operation_id(operation_id: str) -> str:
    return f"{operation_id}#decide"


def _record_decision(deps: Deps, state: dict, action: str, reason: str) -> None:
    """把這次的判斷結果寫進操作紀錄；KEEP 與 NO_FEATURE 都要留下可查的原因。"""
    (operation_id,) = require(state, "operation_id")
    node_operation = _decide_operation_id(operation_id)
    record = {
        "task": "decide",
        "ticket_id": state.get("ticket_id"),
        "cluster_id": state.get("cluster_id"),
        "gap": state.get("gap"),
        "feature_id": state.get("feature_id"),
        "action": action,
        "reason": reason,
        "decided_at": to_iso(deps.now()),
    }
    if not deps.repo.begin_operation(node_operation, record):
        deps.repo.update_operation(node_operation, record)


def _link_ticket_to_feature(deps: Deps, ticket: Ticket, feature_id: str) -> None:
    """一張 Ticket 對應零或一個 Feature（D04）。

    ASKS_ABOUT 邊不在這裡自己寫：Phase 09 的 Repository.put_ticket 會依
    feature_ids[:1] 補上 PK=TICKET#<id>、SK=ASKS_ABOUT#FEATURE#<id> 的邊（設計 §9.2）。
    """
    if ticket.feature_ids == [feature_id]:
        return
    ticket.feature_ids = [feature_id]
    deps.repo.put_ticket(ticket)


def task_decide(state: dict, deps: Deps) -> dict:
    """決定 CREATE、KEEP 或 NO_FEATURE（分析工單 Rule 7、Rule 8、Rule 9）。"""
    (ticket_id,) = require(state, "ticket_id")
    ticket = deps.repo.get_ticket(ticket_id)
    if ticket is None:
        raise PermanentError(f"找不到工單 {ticket_id}")

    if not state.get("recurring"):
        reason = "同群工單未達 recurring 門檻，不建立教學"
        _record_decision(deps, state, "KEEP", reason)
        return merged(state, action="KEEP", keep_reason=reason)

    feature_id = state.get("feature_id")
    if not feature_id:
        reason = "gap 沒有對應到既有 Feature，保留待釐清的 gap"
        _record_decision(deps, state, "NO_FEATURE", reason)
        return merged(state, action="NO_FEATURE", keep_reason=reason)

    _link_ticket_to_feature(deps, ticket, feature_id)

    # status=active 就算已有教學，即使 current_version 還是 None（F12）；
    # retired 的教學不會被這個函式回傳，所以不阻擋 CREATE。
    existing = deps.repo.find_active_tutorial_for_feature(feature_id)
    if existing is not None:
        reason = f"Feature {feature_id} 已有 active 教學 {existing.slug}"
        _record_decision(deps, state, "KEEP", reason)
        return merged(state, action="KEEP", keep_reason=reason, slug=existing.slug)

    _record_decision(deps, state, "CREATE", f"Feature {feature_id} 尚無 active 教學")
    return merged(state, action="CREATE")
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：`uv run pytest tests/unit/test_ticket_decide.py -v`
預期：7 個測試全部 PASS。

- [ ] **步驟 5：commit**

```bash
git add tests/unit/test_ticket_decide.py src/training_kb/pipelines/ticket.py
git commit -m "feat(pipelines): 決定 CREATE、KEEP 與 NO_FEATURE 並留下原因紀錄"
```

---

### Task 7：task_create_v1 建立第一版教學

**目的**：取 active 規則注入 prompt，產生五段內容，驗證後建立 Tutorial 與未發布的 v1。

**檔案**：
- 修改：`src/training_kb/pipelines/ticket.py`
- 測試：`tests/integration/test_ticket_pipeline.py`（追加）

**介面**：
- 消費：
  - `writing.rules.rules_for_content(rules, step_types) -> tuple[str, list[str]]`（Phase 06）
  - `writing.prompts.prompt_write_tutorial(gap, feature, evidence_texts, rules_block) -> tuple[str, str]`、`writing.schemas.TutorialDraft`（Phase 05）
  - `content.validate_content(content, known_feature_ids)`、`content.create_tutorial(...)`、`content.allocate_version(...)`、`content.create_version(...)`（Phase 07）
  - `repo.list_rules(status)`、`repo.get_feature`、`repo.list_features`、`repo.get_tutorial`（Phase 03／09）
- 產出：`pipelines.ticket.task_create_v1(state: dict, deps: Deps) -> dict`（state 新增 `version_id`，確認 `slug`）

**步驟順序（不可調換）**：
1. `rules_for_content` 取 active 規則 → `(rules_block, rule_ids)`
2. `prompt_write_tutorial` → `writer.generate_json(schema=TutorialDraft)`
3. `validate_content`（五段齊全、每步恰好一個既有 Feature）
4. `create_tutorial`（`status=active`、`current_version=None`）
5. `allocate_version(reason=f"gap:{cluster_id}", rules_applied=rule_ids)`
6. `create_version`（`published_at=None`）

- [ ] **步驟 1：寫測試**

追加到 `tests/integration/test_ticket_pipeline.py`：

```python
from training_kb.models import Feature, StepDraft
from training_kb.pipelines.ticket import task_create_v1
from training_kb.writing.schemas import TutorialDraft


def put_feature(repo, feature_id: str, name: str) -> None:
    repo.put_feature(
        Feature(feature_id=feature_id, name=name, aliases=[], first_seen="2026-08-01T00:00:00Z")
    )


def sample_draft() -> TutorialDraft:
    return TutorialDraft(
        title="準備會議",
        problem="使用者找不到會前摘要的入口。",
        prerequisites=["已登入產品", "已建立一場會議"],
        steps=[
            StepDraft(type="read", text="開啟會議列表，找到今天的會議。", feature_id="Prepare"),
            StepDraft(type="click_ui", text="在會議頁右上角點選 Prepare。", feature_id="Prepare"),
            StepDraft(type="read", text="確認畫面出現會前摘要內容。", feature_id="Prepare"),
        ],
        expected_outcome="可以在開會前看到整理好的重點。",
    )


def create_state() -> dict:
    return {
        "ticket_id": "t_seed4",
        "operation_id": "op-create",
        "cluster_id": "c12",
        "recurring": True,
        "gap": "找不到會前摘要入口",
        "feature_id": "Prepare",
        "slug": "prepare-meeting",
        "action": "CREATE",
    }


def test_create_v1_builds_unpublished_first_version(repo):
    seed_cluster(repo, 5, 9)
    put_feature(repo, "Prepare", "Prepare")
    writer = FakeWriter(outputs=[sample_draft()], trace=CallTrace())
    deps = make_deps(repo, writer)

    out = task_create_v1(create_state(), deps)

    assert out["version_id"] == "prepare-meeting@v1"
    tutorial_obj = repo.get_tutorial("prepare-meeting")
    assert tutorial_obj is not None
    assert tutorial_obj.status == "active"
    assert tutorial_obj.current_version is None
    assert tutorial_obj.cluster_id == "c12"

    version = repo.get_version("prepare-meeting@v1")
    assert version.published_at is None
    assert version.reason == "gap:c12"
    assert version.supersedes is None
    assert len(repo.get_steps("prepare-meeting@v1")) == 3
    assert repo.get_object("tutorials/prepare-meeting/v1.md") is not None
    assert writer.trace.count() == 1


def test_create_v1_skips_when_action_is_not_create(repo):
    writer = FakeWriter(outputs=[], trace=CallTrace())
    deps = make_deps(repo, writer)
    state = create_state()
    state["action"] = "KEEP"

    out = task_create_v1(state, deps)

    assert out.get("version_id") is None
    assert writer.trace.count() == 0


def test_create_v1_rejects_step_referencing_unknown_feature(repo):
    from training_kb.errors import ContentError

    seed_cluster(repo, 5, 9)
    put_feature(repo, "Prepare", "Prepare")
    bad = sample_draft()
    bad.steps[1].feature_id = "NotThere"
    deps = make_deps(repo, FakeWriter(outputs=[bad], trace=CallTrace()))

    with pytest.raises(ContentError):
        task_create_v1(create_state(), deps)


def test_create_v1_reuses_tutorial_when_retried(repo):
    seed_cluster(repo, 5, 9)
    put_feature(repo, "Prepare", "Prepare")
    writer = FakeWriter(outputs=[sample_draft(), sample_draft()], trace=CallTrace())
    deps = make_deps(repo, writer)

    first = task_create_v1(create_state(), deps)
    second = task_create_v1(create_state(), deps)

    assert first["version_id"] == second["version_id"] == "prepare-meeting@v1"
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：`uv run pytest tests/integration/test_ticket_pipeline.py -k create_v1 -v`
預期：FAIL，`ImportError: cannot import name 'task_create_v1' from 'training_kb.pipelines.ticket'`。

- [ ] **步驟 3：寫最少的程式讓測試通過**

在 `ticket.py` 的 import 區補上：

```python
from training_kb.content import allocate_version, create_tutorial, create_version, validate_content
from training_kb.models import RuleStatus, StepType, TutorialContent
from training_kb.writing.prompts import prompt_write_tutorial
from training_kb.writing.rules import rules_for_content
from training_kb.writing.schemas import TutorialDraft
```

再加上：

```python
_ALL_STEP_TYPES = [StepType.click_ui, StepType.input, StepType.read]


def task_create_v1(state: dict, deps: Deps) -> dict:
    """建立新 Tutorial 與未發布的 v1（分析工單 Rule 9～Rule 14）。"""
    if state.get("action") != "CREATE":
        return dict(state)

    operation_id, cluster_id, feature_id, gap, slug = require(
        state, "operation_id", "cluster_id", "feature_id", "gap", "slug"
    )
    feature = deps.repo.get_feature(feature_id)
    if feature is None:
        raise PermanentError(f"Feature {feature_id} 不存在，不能建立教學")

    # 1) 寫作前取 active 規則並記下實際注入的 ID（套用教學規則 Rule 1、Rule 2、Rule 7）
    active_rules = deps.repo.list_rules(RuleStatus.active)
    rules_block, rule_ids = rules_for_content(active_rules, _ALL_STEP_TYPES)

    # 2) 產生五段內容
    evidence_texts = [
        item.text
        for item in deps.repo.list_tickets(deps.settings.project_id)
        if item.cluster_id == cluster_id
    ][:_MAX_EVIDENCE_TICKETS]
    system, user = prompt_write_tutorial(gap, feature, evidence_texts, rules_block)
    draft: TutorialDraft = deps.writer.generate_json(
        system=system,
        user=user,
        schema=TutorialDraft,
        operation_id=operation_id,
        node="ticket.create_v1",
        max_tokens=deps.settings.gen_max_tokens_writing,
        temperature=deps.settings.gen_temperature,
    )

    # 3) 業務驗證：五段齊全、每步恰好一個既有 Feature、型態合法
    content = TutorialContent.model_validate(draft.model_dump())
    known_feature_ids = {item.feature_id for item in deps.repo.list_features()}
    validate_content(content, known_feature_ids)

    now = deps.now()

    # 4) 建立 Tutorial 身分；重試時沿用既有的那一篇
    tutorial = deps.repo.get_tutorial(slug)
    if tutorial is None:
        tutorial = create_tutorial(
            deps.repo,
            slug=slug,
            topic=content.title,
            feature_ids=sorted({step.feature_id for step in content.steps}),
            cluster_id=cluster_id,
            now=now,
        )

    # 5) 分配版號：同一個 operation_id 重試會拿回原本的 version_id（D26）
    plan = allocate_version(
        deps.repo,
        tutorial.slug,
        operation_id,
        f"gap:{cluster_id}",
        rule_ids,
    )

    # 6) 建立版本；published_at 仍是 None（D25）
    version = create_version(deps.repo, plan, content, now=now)
    return merged(state, slug=tutorial.slug, version_id=version.version_id)
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：`uv run pytest tests/integration/test_ticket_pipeline.py -v`
預期：全部 PASS（含前面 12 個，共 16 個）。

- [ ] **步驟 5：commit**

```bash
git add tests/integration/test_ticket_pipeline.py src/training_kb/pipelines/ticket.py
git commit -m "feat(pipelines): 以 active 規則產生並保存教學第一版"
```

---

### Task 8：task_publish 與 TASKS 對照表

**目的**：把 v1 上架，並把七個 task 收進 `TASKS` 字典，讓 Phase 14 的 ASL 可以用名字呼叫。

**檔案**：
- 修改：`src/training_kb/pipelines/ticket.py`
- 測試：`tests/integration/test_ticket_pipeline.py`（追加）

**介面**：
- 消費：`content.publish(repo, version_ids, renderer, *, now) -> PublishResult`、`site.SiteRenderer`（Phase 08）
- 產出：
  - `pipelines.ticket.task_publish(state: dict, deps: Deps) -> dict`（state 新增 `published: bool`）
  - `pipelines.ticket.TASKS: dict[str, TaskFn]`
  - `pipelines.ticket.TASK_ORDER: list[str]`（簡報未列，本階段新增）
  - `pipelines.ticket.task_sequence() -> list[tuple[str, TaskFn]]`（簡報未列，本階段新增，給 `run_sequence` 用）

- [ ] **步驟 1：寫測試**

```python
from training_kb.pipelines.ticket import TASK_ORDER, TASKS, task_publish, task_sequence


def test_tasks_dict_matches_design_node_names():
    assert sorted(TASKS) == [
        "cluster",
        "create_v1",
        "decide",
        "embed",
        "name_gap",
        "publish",
        "recurring",
    ]
    assert TASK_ORDER == [
        "embed",
        "cluster",
        "recurring",
        "name_gap",
        "decide",
        "create_v1",
        "publish",
    ]
    assert [name for name, _ in task_sequence()] == TASK_ORDER
    assert all(callable(fn) for fn in TASKS.values())


def test_publish_switches_current_version(repo):
    seed_cluster(repo, 5, 9)
    put_feature(repo, "Prepare", "Prepare")
    writer = FakeWriter(outputs=[sample_draft()], trace=CallTrace())
    deps = make_deps(repo, writer)
    state = task_create_v1(create_state(), deps)

    out = task_publish(state, deps)

    assert out["published"] is True
    assert repo.get_tutorial("prepare-meeting").current_version == "prepare-meeting@v1"
    assert repo.get_version("prepare-meeting@v1").published_at is not None
    assert repo.get_object("site/prepare-meeting/v1.html") is not None


def test_publish_skips_when_nothing_was_created(repo):
    deps = make_deps(repo, FakeWriter(trace=CallTrace()))
    state = {"ticket_id": "t_1", "operation_id": "op-1", "action": "KEEP"}

    out = task_publish(state, deps)

    assert out["published"] is False


def test_publish_raises_when_publish_reports_failure(repo, monkeypatch):
    from training_kb.errors import PermanentError

    import training_kb.pipelines.ticket as ticket_module

    class Failed:
        published: list[str] = []
        failed = "prepare-meeting@v1"

    monkeypatch.setattr(ticket_module, "publish", lambda *args, **kwargs: Failed())
    deps = make_deps(repo, FakeWriter(trace=CallTrace()))
    state = {"operation_id": "op-1", "action": "CREATE", "version_id": "prepare-meeting@v1"}

    with pytest.raises(PermanentError):
        task_publish(state, deps)
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：`uv run pytest tests/integration/test_ticket_pipeline.py -k "TASKS or publish or tasks_dict" -v`
預期：FAIL，`ImportError: cannot import name 'TASKS' from 'training_kb.pipelines.ticket'`。

- [ ] **步驟 3：寫最少的程式讓測試通過**

在 `ticket.py` 的 import 區補上：

```python
from training_kb.content import publish
from training_kb.site import SiteRenderer
```

再加上：

```python
def task_publish(state: dict, deps: Deps) -> dict:
    """上架這次建立的版本（發布教學版本 Rule 1、Rule 4、Rule 5）。"""
    version_id = state.get("version_id")
    if state.get("action") != "CREATE" or not version_id:
        return merged(state, published=False)

    result = publish(deps.repo, [version_id], SiteRenderer(), now=deps.now())
    if result.failed is not None:
        # 任一篇失敗整批不切換 current_version（F49）
        raise PermanentError(f"發布失敗：{result.failed}")
    return merged(state, published=True)


# Step Functions 的 Task 節點名稱 -> 函式。Phase 14 的 ASL 用同一組名稱分派。
TASKS: dict[str, TaskFn] = {
    "embed": task_embed,
    "cluster": task_cluster,
    "recurring": task_recurring,
    "name_gap": task_name_gap,
    "decide": task_decide,
    "create_v1": task_create_v1,
    "publish": task_publish,
}

TASK_ORDER: list[str] = [
    "embed",
    "cluster",
    "recurring",
    "name_gap",
    "decide",
    "create_v1",
    "publish",
]


def task_sequence() -> list[tuple[str, TaskFn]]:
    """給本機 run_sequence 用的完整順序；雲端由 ASL 逐一呼叫同一組函式。"""
    return [(name, TASKS[name]) for name in TASK_ORDER]
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：`uv run pytest tests/integration/test_ticket_pipeline.py -v`
預期：全部 PASS（共 20 個）。

- [ ] **步驟 5：commit**

```bash
git add tests/integration/test_ticket_pipeline.py src/training_kb/pipelines/ticket.py
git commit -m "feat(pipelines): 上架第一版並整理 Ticket Analysis 節點表"
```

---

### Task 9：本機端到端跑完整條流程

**目的**：用 `run_sequence` 一口氣跑完七個 task，證明「五筆同題工單 → 未發布 v1 → 發布」這條路真的通。

**檔案**：
- 測試：`tests/integration/test_ticket_pipeline.py`（追加）

**介面**：
- 消費：`pipelines.common.run_sequence`、`pipelines.ticket.task_sequence`、`FakeWriter`
- 產出：無新程式。這個 Task 只加測試；如果它一次就 PASS，代表 Task 1–8 的 state 欄位串接正確。

- [ ] **步驟 1：寫測試**

```python
from training_kb.pipelines.common import run_sequence
from training_kb.pipelines.ticket import task_sequence
from training_kb.writing.schemas import GapNaming

TRIGGER_TEXT = "會前摘要在哪裡開啟？"


def seed_four_existing_tickets(repo) -> None:
    """四張已有向量與 cluster_id 的同題工單，時間落在窗口內。"""
    for index in range(4):
        repo.put_ticket(
            ticket(
                f"t_20{index}",
                f"會前摘要相關問題 {index}",
                f"2026-09-{9 + index:02d}T09:00:00Z",
                author=f"u_0{index + 1}",
                embedding=list(AXIS),
                cluster_id="c12",
            )
        )


def test_end_to_end_creates_and_publishes_v1(repo):
    seed_four_existing_tickets(repo)
    put_feature(repo, "Prepare", "Prepare")
    repo.put_ticket(ticket("t_881", TRIGGER_TEXT, "2026-09-13T02:00:00Z", author="u_05"))

    writer = FakeWriter(
        embeddings={TRIGGER_TEXT: list(AXIS)},
        outputs=[
            GapNaming(gap="找不到會前摘要入口", feature_id="Prepare", slug="prepare-meeting"),
            sample_draft(),
        ],
        trace=CallTrace(),
    )
    deps = make_deps(repo, writer)
    state = {"ticket_id": "t_881", "operation_id": "ingest:ticket:t_881", "policy": "formal"}

    out = run_sequence(task_sequence(), state, deps)

    assert out["embedding_done"] is True
    assert out["cluster_id"] == "c12"
    assert out["recurring"] is True
    assert out["gap"] == "找不到會前摘要入口"
    assert out["feature_id"] == "Prepare"
    assert out["action"] == "CREATE"
    assert out["version_id"] == "prepare-meeting@v1"
    assert out["published"] is True

    tutorial_obj = repo.get_tutorial("prepare-meeting")
    assert tutorial_obj.current_version == "prepare-meeting@v1"
    assert tutorial_obj.cluster_id == "c12"
    assert repo.get_version("prepare-meeting@v1").reason == "gap:c12"
    assert repo.get_object("tutorials/prepare-meeting/v1.md") is not None
    assert repo.get_object("tutorials/prepare-meeting/v1.diff") == b""  # v1 是空 diff（F50）
    assert repo.get_object("site/prepare-meeting/v1.html") is not None
    # 一次 embedding + 一次 name_gap + 一次 create_v1 = 3 次模型呼叫
    assert writer.trace.count() == 3


def test_end_to_end_keeps_when_only_four_tickets(repo):
    put_feature(repo, "Prepare", "Prepare")
    for index in range(3):
        repo.put_ticket(
            ticket(
                f"t_30{index}",
                f"會前摘要相關問題 {index}",
                f"2026-09-{10 + index:02d}T09:00:00Z",
                embedding=list(AXIS),
                cluster_id="c12",
            )
        )
    repo.put_ticket(ticket("t_881", TRIGGER_TEXT, "2026-09-13T02:00:00Z"))

    writer = FakeWriter(embeddings={TRIGGER_TEXT: list(AXIS)}, outputs=[], trace=CallTrace())
    deps = make_deps(repo, writer)
    state = {"ticket_id": "t_881", "operation_id": "ingest:ticket:t_881", "policy": "formal"}

    out = run_sequence(task_sequence(), state, deps)

    assert out["recurring"] is False
    assert out["action"] == "KEEP"
    assert out.get("version_id") is None
    assert out["published"] is False
    assert repo.get_tutorial("prepare-meeting") is None
    assert writer.trace.count() == 1  # 只有 embedding，沒有呼叫 Claude


def test_end_to_end_keeps_when_feature_already_has_active_tutorial(repo):
    seed_four_existing_tickets(repo)
    put_feature(repo, "Prepare", "Prepare")
    repo.put_ticket(ticket("t_881", TRIGGER_TEXT, "2026-09-13T02:00:00Z"))

    first_writer = FakeWriter(
        embeddings={TRIGGER_TEXT: list(AXIS)},
        outputs=[
            GapNaming(gap="找不到會前摘要入口", feature_id="Prepare", slug="prepare-meeting"),
            sample_draft(),
        ],
        trace=CallTrace(),
    )
    run_sequence(
        task_sequence(),
        {"ticket_id": "t_881", "operation_id": "ingest:ticket:t_881", "policy": "formal"},
        make_deps(repo, first_writer),
    )

    repo.put_ticket(ticket("t_882", TRIGGER_TEXT, "2026-09-13T03:00:00Z", author="u_06"))
    second_writer = FakeWriter(
        embeddings={TRIGGER_TEXT: list(AXIS)},
        outputs=[GapNaming(gap="找不到會前摘要入口", feature_id="Prepare", slug="prepare-meeting")],
        trace=CallTrace(),
    )

    out = run_sequence(
        task_sequence(),
        {"ticket_id": "t_882", "operation_id": "ingest:ticket:t_882", "policy": "formal"},
        make_deps(repo, second_writer),
    )

    assert out["action"] == "KEEP"
    assert "prepare-meeting" in out["keep_reason"]
    assert repo.get_version("prepare-meeting@v2") is None


def test_end_to_end_no_feature_does_not_create_tutorial(repo):
    seed_four_existing_tickets(repo)
    put_feature(repo, "Prepare", "Prepare")
    repo.put_ticket(ticket("t_881", TRIGGER_TEXT, "2026-09-13T02:00:00Z"))

    writer = FakeWriter(
        embeddings={TRIGGER_TEXT: list(AXIS)},
        outputs=[GapNaming(gap="某個還沒定義的功能", feature_id=None, slug="unknown-gap")],
        trace=CallTrace(),
    )
    deps = make_deps(repo, writer)
    state = {"ticket_id": "t_881", "operation_id": "ingest:ticket:t_881", "policy": "formal"}

    out = run_sequence(task_sequence(), state, deps)

    assert out["action"] == "NO_FEATURE"
    assert repo.get_tutorial("unknown-gap") is None
    record = repo.load_operation("ingest:ticket:t_881#decide")
    assert record["gap"] == "某個還沒定義的功能"
```

> 第一個測試的 `writer.trace.count() == 3` 對應設計文件 §12.1 的「Bedrock 呼叫數」定義：embedding、Rote、Map 每一項、重試都算。這條流程沒有重試、沒有 Map，所以剛好是 3。

- [ ] **步驟 2：跑測試，確認它失敗**

執行：`uv run pytest tests/integration/test_ticket_pipeline.py -k end_to_end -v`
預期：通常會 FAIL 在第一個測試的 `assert out["cluster_id"] == "c12"`，錯誤訊息類似 `assert 'c1' == 'c12'`，因為種子工單的 `cluster_id` 是自己寫死的 `c12`，而 `new_cluster_id` 從 1 開始數。若四筆種子工單的向量與觸發工單一致，`task_cluster` 應該歸進 `c12` 而不是開新群；FAIL 代表向量設定不對。

- [ ] **步驟 3：寫最少的程式讓測試通過**

不需要新增產品程式。若上面的斷言 FAIL，依序檢查：

1. `seed_four_existing_tickets` 的四筆工單有沒有同時設定 `embedding` 與 `cluster_id`。`task_cluster` 只把「同時有這兩個欄位」的工單納入群中心計算。
2. 觸發工單的 `embeddings` 對照表 key 是不是 `Ticket.text` 原文。`FakeWriter.embed(text)` 是用文字當 key 查表。
3. `Settings.embed_dimensions` 有沒有跟測試向量的長度一致（這裡是 4）。
4. 第三個測試若 FAIL 在 `repo.get_version("prepare-meeting@v2") is None`，回頭確認 `task_decide` 的 `find_active_tutorial_for_feature` 分支有沒有把 `action` 設成 `KEEP`。

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：`uv run pytest tests/integration/test_ticket_pipeline.py -v`
預期：全部 PASS（共 24 個）。

再跑一次整個 Phase 13：

執行：
```bash
uv run pytest tests/unit/test_pipelines_common.py tests/unit/test_ticket_cluster.py \
              tests/unit/test_ticket_recurring.py tests/unit/test_ticket_name_gap.py \
              tests/unit/test_ticket_decide.py tests/integration/test_ticket_pipeline.py -v
uv run ruff check .
```
預期：測試全綠，`ruff` 沒有輸出錯誤。

- [ ] **步驟 5：commit**

```bash
git add tests/integration/test_ticket_pipeline.py
git commit -m "test(pipelines): 本機端到端驗證 Ticket Analysis"
```

---

## 7. 完成檢查清單

對應設計文件第 16 節切片 **S2**（「工單達門檻後建立未發布 v1；active 已存在時 KEEP」）。

- [ ] `uv run pytest tests/unit/test_pipelines_common.py tests/unit/test_ticket_cluster.py tests/unit/test_ticket_recurring.py tests/unit/test_ticket_name_gap.py tests/unit/test_ticket_decide.py -v` 全部 PASS。
- [ ] `uv run pytest tests/integration/test_ticket_pipeline.py -v` 全部 PASS。
- [ ] `uv run ruff check .` 與 `uv run ruff format --check .` 沒有錯誤。
- [ ] cosine **剛好等於** 0.85 的工單會加入該群；略低於 0.85 的會開新群。
- [ ] 兩個群分數相同時，選中的是 `cluster_id` 字串升序的第一個。
- [ ] `recurring_window(date(2026, 9, 13), 14)` 有 14 個日期，包含 `2026-08-31`，不包含 `2026-08-30`。
- [ ] 同群四筆 → `recurring=False`；五筆 → `recurring=True`。
- [ ] `recurring=False` 時完全不呼叫 Claude（`CallTrace.count()` 只有 embedding 那一次）。
- [ ] 某 Feature 已有 `status=active` 但 `current_version=None` 的教學時，結果是 `KEEP`，而且不會產生 v2。
- [ ] 某 Feature 只有 `status=retired` 的教學時，結果是 `CREATE`。
- [ ] `feature_id` 對不到既有 Feature 時，結果是 `NO_FEATURE`，操作紀錄裡看得到 `gap` 原文，且沒有建立任何 Tutorial 或 Feature。
- [ ] 用同一個 `operation_id` 連呼叫兩次 `task_name_gap`，模型只被呼叫一次。
- [ ] 建好的 v1：`published_at` 是 `None`、`reason` 是 `gap:c12`、`supersedes` 是 `None`、步驟數與 draft 一致、每步都有一個既有 Feature。
- [ ] `publish` 之後 `Tutorial.current_version` 指到 `prepare-meeting@v1`，而且 `site/prepare-meeting/v1.html` 存在。
- [ ] `tutorials/prepare-meeting/v1.diff` 是空檔（F50）。
- [ ] `state` 裡從頭到尾沒有出現 `embedding` 或教學全文。

手動抽查（不需要 AWS，只檢查純函式）：

```bash
uv run python - <<'PY'
from datetime import date
from training_kb.pipelines.ticket import normalize_slug, pick_cluster, recurring_window

axis = [1.0, 0.0, 0.0, 0.0, 0.0]
on = [17.0, 7.0, 6.0, 5.0, 1.0]
below = [16.99, 7.0, 6.0, 5.0, 1.0]
print("剛好 0.85 ->", pick_cluster(axis, {"c1": on}, 0.85))
print("略低於 0.85 ->", pick_cluster(axis, {"c1": below}, 0.85))
print("窗口天數 ->", len(recurring_window(date(2026, 9, 13), 14)))
print("最早一天 ->", min(recurring_window(date(2026, 9, 13), 14)))
print("slug ->", normalize_slug("Prepare Meeting"))
PY
```

預期輸出：

```text
剛好 0.85 -> c1
略低於 0.85 -> None
窗口天數 -> 14
最早一天 -> 2026-08-31
slug -> prepare-meeting
```

---

## 8. 常見錯誤與排除

**1. `PermanentError: state 缺少必要欄位：cluster_id`**

- 症狀：單獨執行 `task_recurring` 或 `task_name_gap` 時直接失敗。
- 原因：這兩個 task 需要前一個 task 放進 state 的欄位。單獨測試時要自己把 `cluster_id`、`recurring` 補進 state。
- 解法：照本文件測試裡 `base_state()` 的寫法準備 state；或直接用 `run_sequence(task_sequence(), ...)` 跑完整條。

**2. 分群結果每次都不一樣**

- 症狀：同樣的資料，有時歸到 `c1`、有時 `c2`。
- 原因：`pick_cluster` 沒有用 `sorted(centroids)` 走訪，或用了 `>=` 而不是 `>` 比較分數，導致同分時後面的群覆蓋前面的。
- 解法：照 Task 3 的實作，先 `sorted(centroids)` 再用嚴格大於 `score > best_score`。這樣同分時留下的一定是 `cluster_id` 最小的那個。

**3. `recurring` 永遠是 `False`，即使工單明明有五筆**

- 症狀：種子資料看起來夠，但判斷不過。
- 原因有三種：(a) 觸發工單自己的 `cluster_id` 還沒寫回 DynamoDB，所以 `list_tickets` 撈不到它，只數到四筆；(b) 工單 `ts` 的日期超出窗口；(c) `Thresholds.recurring_days` 被寫成 13。
- 解法：先印出 `[(t.id, t.cluster_id, t.ts) for t in repo.list_tickets("demo-project")]`，確認觸發工單的 `cluster_id` 已經寫進去了。`task_cluster` 必須在 `task_recurring` 之前執行。

**4. `ContentError: 步驟 2 引用的 Feature 不存在`**

- 症狀：`task_create_v1` 在 `validate_content` 就失敗。
- 原因：模型輸出的 `feature_id` 不在 `repo.list_features()` 裡。這是正確行為（`分析工單` Rule 13、`建立教學版本` Rule 9），不是 bug。
- 解法：測試裡先用 `put_feature(repo, "Prepare", "Prepare")` 建好 Feature；正式環境則由維護者先匯入 Feature 清單（Phase 21 的種子資料）。

**5. 重試時版本號從 v1 變成 v2**

- 症狀：同一次操作重跑，卻多出一個版本。
- 原因：`allocate_version` 的 `operation_id` 每次都不一樣（例如用了 `uuid4()`）。
- 解法：`operation_id` 必須是 Phase 10 的 `operation_id_for("ticket", ticket_id)` 產出的固定值，整條流程從頭到尾用同一個。D26 要求「同一邏輯變更重試時重用原版本號」。

**6. `KeyError` 出現在 `FakeWriter.embed`**

- 症狀：整合測試在 `task_embed` 炸掉。
- 原因：`FakeWriter(embeddings=...)` 是用文字當 key 查表，測試裡的 key 必須跟 `Ticket.text` 完全一樣（含全形問號、換行）。
- 解法：把文字抽成常數（例如 `TRIGGER_TEXT`），建工單與建 `embeddings` 都用同一個常數。

**7. `moto` 測試報 `ValidationException: One or more parameter values were invalid`**

- 症狀：`repo` fixture 建表時就失敗。
- 原因：`AttributeDefinitions` 裡宣告了沒有被任何 key schema 用到的屬性，或 GSI 的分割鍵名稱不是 `target`。
- 解法：照 Task 2 的 fixture 原樣建表：三個屬性定義（`PK`、`SK`、`target`），GSI 名稱 `by_target`。

**8. `task_publish` 通過了，但 `site/` 底下沒有檔案**

- 症狀：`repo.get_object("site/prepare-meeting/v1.html")` 回 `None`。
- 原因：Phase 08 的 `publish` 內部是否有呼叫 `publish_to_site`，或 `SiteRenderer` 的建構子需要參數。
- 解法：回 Phase 08 的文件確認 `publish(repo, version_ids, renderer, *, now)` 的行為；本階段只負責呼叫它，不在這裡另外寫 S3 寫入。

---

## 9. 這階段不做的事

| 不做 | 留給誰 |
|---|---|
| Step Functions 的 ASL、Lambda handler、Retry／Catch、Choice 分支 | Phase 14（`14-Phase14-StepFunctions與Lambda上線.md`）。本階段只把 `TASKS` 字典準備好。 |
| 真的呼叫 Bedrock。本階段所有測試都用 `FakeWriter` | Phase 04 確認模型可用性、Phase 05 實作 `BedrockWriter`。不宣稱已在真帳號跑過。 |
| Release Note Update 的 `pipelines/release.py` | Phase 16（`16-Phase16-Release-Note-Update流程.md`）。 |
| Feedback Review 的 `pipelines/feedback.py`、REFINE、候選規則 | Phase 17、Phase 18。 |
| 建立新的 Feature。gap 對不到既有 Feature 就是 `NO_FEATURE` | 依 F13，Ticket Analysis 永遠不建 Feature。Feature 清單由維護者提供（Phase 21）。 |
| 合群、重新編號、把多個 cluster 併起來 | 設計文件 §7.3 明說 MVP 不做，以保留 `Tutorial.cluster_id` 的追溯。 |
| 把整群工單都標上 `feature_ids` | 本階段只標觸發這條流程的那一張工單。其他工單各自流過 pipeline 時會被標上。 |
| 重開票率、平均評分等指標 | Phase 19（`19-Phase19-Analytics-學習指標.md`）。本階段只把 `Tutorial.cluster_id` 固定下來，讓 D29 的同題對應成立。 |
| 教學頁的版本選擇、diff 檢視、回饋 widget | Phase 22（`22-Phase22-S3靜態教學站.md`）。本階段用 Phase 08 的最小版 `SiteRenderer`。 |

---

## 10. 對照：設計章節與 Rule 編號

| Rule 來源檔 | Rule 編號與原文 | 本階段哪個 Task 落實 |
|---|---|---|
| `分析工單.feature` | Rule 1「每則 Ticket 在接入分析時計算一次並儲存 1024 維 embedding」 | Task 2（`task_embed`；已有向量就不重算，維度以 `Settings.embed_dimensions` 檢查） |
| `分析工單.feature` | Rule 2「demo 分群以 cosine 至少 0.85 為同群門檻」 | Task 3（`pick_cluster` 與 `Thresholds.cosine_cluster`） |
| `分析工單.feature` | Rule 3「同群在 14 天內至少有 5 筆 Ticket 才算 recurring」 | Task 4（`recurring_window` + `count_in_window`） |
| `分析工單.feature` | Rule 4「只有達 recurring 門檻的群才交給模型命名 Knowledge Gap」 | Task 5（`task_name_gap` 開頭的 `if not state.get("recurring")`） |
| `分析工單.feature` | Rule 5「Knowledge Gap 的命名結果包含對應 Feature」 | Task 5（`GapNaming.feature_id`，且程式驗證該 Feature 必須存在） |
| `分析工單.feature` | Rule 6「一張 Ticket 對應零或一個 Feature」 | Task 5（`GapNaming.feature_id` 是單值）、Task 6（`_link_ticket_to_feature` 寫入長度 0 或 1 的 `feature_ids`；ASKS_ABOUT 邊由 Phase 09 的 `Repository.put_ticket` 依 `feature_ids[:1]` 補上） |
| `分析工單.feature` | Rule 7「對應 Feature 已有教學時動作為 KEEP」 | Task 6（`find_active_tutorial_for_feature` 分支） |
| `分析工單.feature` | Rule 8「KEEP 只記錄 log 而不寫入教學內容」 | Task 6（`_record_decision` 只寫操作紀錄，不碰 TUTORIAL） |
| `分析工單.feature` | Rule 9「已識別且尚無現成教學的 Knowledge Gap 建立新的 Tutorial」 | Task 7（`task_create_v1`） |
| `分析工單.feature` | Rule 10「Ticket Analysis 是唯一建立新 Tutorial 身分的 pipeline」 | Task 7（整個專案只有這裡呼叫 `content.create_tutorial`） |
| `分析工單.feature` | Rule 11「新教學的完整內容包含 Title、Problem、Prerequisites、Steps 與 Expected Outcome」 | Task 7（`TutorialDraft` schema + `validate_content`） |
| `分析工單.feature` | Rule 12「產生新教學時同時輸出每步提到的 Feature」 | Task 7（`StepDraft.feature_id`） |
| `分析工單.feature` | Rule 13「新教學的每個步驟恰好引用一個 Feature」 | Task 7（`validate_content(content, known_feature_ids)`） |
| `分析工單.feature` | Rule 14「新教學第一版的 reason 使用 gap 加上來源 cluster_id」 | Task 7（`allocate_version(..., f"gap:{cluster_id}", ...)`） |
| `執行教學流程.feature` | Rule 2「教學 pipeline 依 Step Functions 預定義節點執行」 | Task 1（`run_sequence`）、Task 8（`TASKS` 與 `TASK_ORDER` 是 ASL 節點名稱的來源） |
| `執行教學流程.feature` | Rule 8「LLM 輸出遵循指定 JSON schema」 | Task 5（`GapNaming`）、Task 7（`TutorialDraft` + `validate_content` 的業務驗證） |
| `執行教學流程.feature` | Rule 9「判斷節點使用低 temperature」 | Task 5（`temperature=deps.settings.gen_temperature`，預設 0.1） |
| `套用教學規則.feature` | Rule 1「CREATE、UPDATE 與 REFINE 在寫作前讀取教學規則」 | Task 7（先 `rules_for_content` 再 `prompt_write_tutorial`） |
| `套用教學規則.feature` | Rule 2「一般寫作路徑只取得 status 為 active 的規則」 | Task 7（`repo.list_rules(RuleStatus.active)`） |
| `套用教學規則.feature` | Rule 3「依 step 型態與 applies_when 篩選規則」 | Task 7（`rules_for_content(active_rules, _ALL_STEP_TYPES)`） |
| `套用教學規則.feature` | Rule 4「適用規則的內容注入教學寫作 prompt」 | Task 7（`rules_block` 傳進 `prompt_write_tutorial`） |
| `套用教學規則.feature` | Rule 7「版本的 rules_applied 記錄本次套用的規則」 | Task 7（`allocate_version(..., rules_applied=rule_ids)`） |
| `建立教學版本.feature` | Rule 1「新 Tutorial 的版本從 v1 起算」 | Task 7（`allocate_version` 對新教學回傳 v1） |
| `建立教學版本.feature` | Rule 4「每次建立版本都記錄引起變更的 reason」 | Task 7（`reason = gap:<cluster_id>`） |
| `發布教學版本.feature` | Rule 1「publish 上架指定的 TutorialVersion」 | Task 8（`task_publish`） |
| `發布教學版本.feature` | Rule 4「Tutorial 的 current_version 指向目前教學版本」 | Task 8（測試斷言 `current_version == "prepare-meeting@v1"`） |
| `發布教學版本.feature` | Rule 5「已上架的版本具有 published_at」 | Task 8（測試斷言 `published_at is not None`） |

設計章節對照：

| 設計文件章節 | 本階段對應內容 |
|---|---|
| §7.3「Ticket Analysis：CREATE 或 KEEP」 | Task 2–Task 8 全部 |
| §7.6「共用寫作與 Analytics 的內部介面」的「命名 gap」與「撰寫教學」兩列 | Task 5、Task 7 |
| §6 端到端流程第 1、2 點 | Task 9 的端到端測試 |
| §8.1 五種動作與版本鏈（CREATE 這一列） | Task 7 |
| §8.2 create_version 的完成條件 | Task 7（`published_at=None`）、Task 8（publish 之後才有值） |
| §12.1 Bedrock 呼叫數 | Task 9（`CallTrace.count() == 3`） |
| §14.3 執行參數（`max_tokens` 512／2048、`temperature` 0.1、state 不帶向量與全文） | Task 5、Task 7、§5.4 |
| §15 測試與驗收設計的「Ticket 分析」列 | 第 7 節完成檢查清單 |
| §16 交付切片 S2 | 第 7 節完成檢查清單 |
| §19.1 D04、D25、D26、D29；§19.2 F10、F11、F12、F13、F48、F50 | Task 3–Task 8 |

**待確認事項的標示**：

- recurring 窗口的 anchor 用「觸發工單的 `ts` UTC 日期」而不是「執行當日」，是**本計劃選擇**（F11 只指定了日界線，沒有指定 anchor）。
- `NO_FEATURE` 這個 `action` 值、`keep_reason` 欄位、把決策寫進 `<operation_id>#decide` 操作紀錄，是**本計劃選擇（對應 O2）**；設計文件只說「保留 Ticket 群與 gap 診斷紀錄」，沒有指定儲存形狀。
- `name_gap` 的結果存在 `<operation_id>#name_gap` 操作紀錄以避免重試重呼叫模型，是**本計劃選擇（對應 O2）**。
- slug 撞名時加 `-2`、`-3`，以及 slug 轉不出 ASCII 時退回用 `feature_id` 產生，是**本計劃選擇**；設計文件沒有規定 slug 的產生規則。
- 只替「觸發這條流程的那一張工單」寫 `feature_ids`（ASKS_ABOUT 邊隨 `put_ticket` 產生），是**本計劃選擇**；設計文件只規定基數是 0..1，沒有規定寫入時機。

---

## 11. 參考來源

**設計文件（`docs/design/training-kb.md`）**
- §6 端到端流程（第 1、2 點）
- §7.3 Ticket Analysis：CREATE 或 KEEP
- §7.6 共用寫作與 Analytics 的內部介面
- §8.1 五種動作與版本鏈、§8.2 create_version 的完成條件
- §9.1 鍵與原生型別（TICKET、TUTORIAL、TUTORIAL_VERSION 三列）、§9.2 關係邊（ASKS_ABOUT）
- §11.1 共用一份產品資料清單（20 筆工單落在執行當日及前 13 個 UTC 日期）
- §12.1 指標公式（Bedrock 呼叫數）
- §14.3 執行參數的建議起點（`max_tokens`、`temperature`、工作流資料不帶全文與向量）
- §15 測試與驗收設計（「Ticket 分析」列）
- §16 交付切片 S2
- §18 待確認事項 O2
- §19.1 D04、D25、D26、D29；§19.2 F10、F11、F12、F13、F48、F50
- §20.2 分析工單的 14 條 Rule；§20.3 執行教學流程；§20.4 套用教學規則；§20.6 建立教學版本；§20.12 發布教學版本

**規格檔**
- `docs/spec/features/分析工單.feature`
- `docs/spec/features/執行教學流程.feature`
- `docs/spec/features/套用教學規則.feature`
- `docs/spec/features/建立教學版本.feature`
- `docs/spec/features/發布教學版本.feature`
- `docs/spec/erm.dbml`（`TICKET`、`FEATURE`、`TUTORIAL`、`TUTORIAL_VERSION` 四張表的 note）
- `docs/spec/.clarify/resolved/data/TICKET_一張_Ticket_可以對應幾個_Feature.md`（D04）
- `docs/spec/.clarify/resolved/data/TUTORIAL_同題重開票的教學與_cluster_對應以何者為準.md`（D29）
- `docs/spec/.clarify/resolved/features/分析工單_cosine_門檻以哪種群代表判斷_Ticket_歸群.md`（F10）
- `docs/spec/.clarify/resolved/features/分析工單_recurring_的十四天窗口以哪個時間為基準.md`（F11）
- `docs/spec/.clarify/resolved/features/分析工單_判定已有教學時哪些_Tutorial_狀態算有效.md`（F12）
- `docs/spec/.clarify/resolved/features/分析工單_Knowledge_Gap_無法對應既有_Feature_時如何處理.md`（F13）

**外部官方文件**（2026-09-13 以 Context7 MCP 與官方網頁查證）
- Amazon Bedrock｜Amazon Titan Text Embeddings：模型 ID `amazon.titan-embed-text-v2:0`、支援 1024 維輸出、embedding API 不吃 `max_tokens`／`temperature`
  <https://docs.aws.amazon.com/bedrock/latest/userguide/titan-embedding-models.html>
- Amazon Bedrock｜Anthropic Claude Messages API request/response：生成模型的 `max_tokens` 與 `temperature` 參數
  <https://docs.aws.amazon.com/bedrock/latest/userguide/model-parameters-anthropic-claude-messages-request-response.html>
- Amazon Bedrock｜Carry out a conversation with the Converse API operations（Phase 05 的 `generate_json` 底層）
  <https://docs.aws.amazon.com/bedrock/latest/userguide/conversation-inference.html>
- AWS Step Functions｜Error handling in Step Functions（Phase 14 會用到的 Retry／Catch 契約，這裡只保證 task 會拋出對的錯誤型別）
  <https://docs.aws.amazon.com/step-functions/latest/dg/concepts-error-handling.html>
- Amazon DynamoDB｜Read consistency（`list_tickets` 走基表一致讀取的理由）
  <https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/HowItWorks.ReadConsistency.html>
- Python 標準函式庫｜`unicodedata.normalize`（`normalize_slug` 把非 ASCII 字元折成 ASCII 的做法）
  <https://docs.python.org/3/library/unicodedata.html#unicodedata.normalize>
