# Phase 16：Release Note Update 流程

| 項目 | 內容 |
|---|---|
| 上一階段 | Phase 15：Feedback 與 View 匯入（`15-Phase15-Feedback與View匯入.md`） |
| 下一階段 | Phase 17：Feedback Review 弱教學與 REFINE（`17-Phase17-Feedback-Review-弱教學與REFINE.md`） |
| 對應設計文件章節 | §7.4、§8.1、§8.2、§8.3、§8.4、§9.1、§9.2、§10、§14.2（`docs/design/training-kb.md`） |
| 對應交付切片 | S5（設計文件第 16 節） |
| 預估時間 | 約 8 小時 |
| 做完會得到 | PR #42 把「Meeting Summary」改名成「Prepare」時，教學 A 只有第 3 步被改寫，第 1、2、4 步逐字不動，B 與 C 完全沒有新版本 |

---

## 1. 這階段做完會得到什麼

這是整個專案裡最能說服人的一段：**產品改版時，只改真的受影響的那幾句話。**

做完之後你會有第二條 Step Functions 流程 `training-kb-release-update`，它做八件事：

1. `locate_feature`：用 name／alias 找到改版對應的 Feature，找不到才用語意搜尋，相似度至少 0.85。
2. `find_steps`：沿 `REFERENCES` 邊反查「目前已發布版本」裡引用該 Feature 的步驟。
3. `safety_net`：反查為零、或是「alias 比對失敗的 renamed」時，用步驟文字做語意搜尋找候選，再請 Claude 確認。
4. `decide`：`removed` → RETIRE；`renamed`／`changed` 有命中 → UPDATE；沒命中 → KEEP 並記下原因。
5. `rewrite`：每篇教學取鎖、配版號、注入 active 規則、只改命中步驟，程式再逐字核對其餘步驟沒被動過。
6. `publish`：所有新版本一次提交，整批全有或全無。
7. `retire`：`removed` 時把受影響教學標成 `retired`。
8. `update_aliases`：改名完成後把舊名字加進 `aliases`，撞名就拒絕這次更新並以失敗結束。

還會把 `handlers/import_.py` 的 release 路徑真的接到這條流程上。

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
                                                                                         ^^^^^^^^^^^^^^^^
                                                                                         你在這裡
                                                                                        |
學習層          17 Review:REFINE -> 18 Review:候選規則+排程 -> 19 Analytics 指標 -> 20 規則驗證
                                                                                        |
展示與驗收層    21 Demo 種子資料 -> 22 靜態教學站 -> 23 Demo 控制台 -> 24 失敗復原驗收 -> 25 安全與當日準備
```

---

## 3. 開始前檢查

| 前置條件 | 驗證指令 | 預期輸出 |
|---|---|---|
| Phase 01–15 單元測試全綠 | `uv run pytest tests/unit -q` | 最後一行類似 `230 passed` |
| Phase 09 的固定讀取都在 | `uv run python -c "from training_kb.repository import Repository as R; print(all(hasattr(R,n) for n in ['find_feature_by_name_or_alias','find_current_published_steps_referencing','list_features','get_steps','scan_entity']))"` | `True` |
| Phase 07／08 的內容函式都在 | `uv run python -c "from training_kb import content; print(all(hasattr(content,n) for n in ['allocate_version','validate_content','render_markdown','create_version','publish','retire','with_tutorial_lock']))"` | `True` |
| Phase 06 的規則注入可用 | `uv run python -c "from training_kb.writing.rules import rules_for_content; print(callable(rules_for_content))"` | `True` |
| Phase 05 的 schema 都在 | `uv run python -c "from training_kb.writing.schemas import StepRewrite, StepConfirmation; print(StepRewrite.model_fields.keys(), StepConfirmation.model_fields.keys())"` | `dict_keys(['rewrites']) dict_keys(['confirmed_indexes'])` |
| Phase 12 的 `parse_pr_diff` 已經會拆子 Release | `uv run pytest tests/unit/test_rote_tools.py -q` | 全綠 |
| Phase 13 的 pipeline 骨架可用 | `uv run python -c "from training_kb.pipelines.common import Deps, run_sequence; print(callable(run_sequence))"` | `True` |
| Phase 14 的 ASL 與 stack 已部署過一次 | `aws stepfunctions list-state-machines --query "stateMachines[?name=='training-kb-ticket-analysis'].name" --output text` | `training-kb-ticket-analysis` |

---

## 4. 名詞小抄

| 名詞 | 白話解釋 | 在本階段哪裡用到 |
|---|---|---|
| Release | 一次產品改版事件。有 `feature`（哪個功能）、`kind`（renamed／changed／removed）、`evidence`（證據文字） | 流程的輸入 |
| `source_event_id` | 同一個上游事件（例如同一個 PR）的識別碼。一個 PR 改了三個功能就拆成三筆 Release，共用同一個 `source_event_id` | F14；拆分在 Phase 12 |
| alias | Feature 的舊名字。改名之後舊名字會被放進 `aliases`，這樣下次還找得到 | D06、D07 |
| alias 撞名 | 要加的 alias 已經是別的 Feature 的 name 或 alias | D07：拒絕該次 alias 更新 |
| `by_target` 反查 | 用 GSI 從「終點」找回「所有指向它的起點」 | 找出誰引用了這個 Feature |
| 基表一致讀 | 直接讀主表（不是 GSI），而且要求「讀到最新寫入」 | 設計 §10：避免 GSI 延遲害我們錯判 KEEP |
| 目前已發布版本 | 某篇教學的 `current_version`，而且那一版的 `published_at` 不是空的 | F17：只有它的步驟會被改寫 |
| safety_net | 反查失敗時的補救路徑：用步驟文字算向量找候選，再請 Claude 確認 | 設計 §7.4；F16、F18 |
| 重大改名 | **只有**「alias 比對失敗的 renamed」才算 | F16 |
| cosine（餘弦相似度） | 兩個向量有多像，值介於 -1 到 1，越接近 1 越像 | Feature 語意搜尋門檻 0.85 |
| UPDATE / RETIRE / KEEP | 三種改版動作：產生下一版／把教學標成退役／什麼都不做只記原因 | 設計 §8.1 |
| `reason` | 記在版本上的「為什麼有這一版」。這裡固定是 `release:<id>` | 依改版更新教學 Rule 14 |
| successor（後繼） | 教學退役後可以指向的另一篇教學，由維護者選 | D22、F54、F19 |
| `rules_applied` | 這一版實際注入了哪些 active 規則 | D17、F29 |
| 整批全有或全無 | 一次 Release 命中多篇時，要嘛全部發布，要嘛一篇都不發布 | F49、設計 §8.3 |
| D06、D07、D10 | 設計文件第 19.1 節的資料決策編號 | Feature 主鍵、alias 唯一、Release 必填欄位 |
| F14–F19、F54 | 設計文件第 19.2 節的功能決策編號 | 子 Release、門檻、重大改名、歷史版不觸發、未命中 KEEP、無後繼、後繼由維護者選 |

---

## 5. 設計說明

### 5.1 多跳定位：從一個功能名字走到「要改的那一句話」

這是設計 §10 的圖，照著走一次就懂了：

```text
  Release：feature="Meeting Summary", kind=renamed,
           old_name="Meeting Summary", new_name="Prepare"
                     |
                     | (1) locate_feature：先比 name / alias
                     v
            FEATURE#Prepare
            （PK 是第一次建立時就固定的，改名不換 PK——D06）
                     |
                     | (2) find_steps：by_target(target = FEATURE#Prepare)
                     v
            所有指向它的邊
              STEP#prepare-meeting@v1#3  REFERENCES#FEATURE#Prepare
              STEP#prepare-meeting@v2#3  REFERENCES#FEATURE#Prepare
              TICKET#t_881               ASKS_ABOUT#FEATURE#Prepare   <- 丟掉
                     |
                     | 只留 STEP# 起點 + REFERENCES 關係
                     v
            候選步驟：A v1 #3、A v2 #3
                     |
                     | 查 Tutorial.current_version 與 VERSION.published_at
                     | 再用基表一致讀核對一次（設計 §10）
                     v
            目前已發布步驟：A v2 #3        <- v1 是歷史版，不觸發改寫（F17）
                     |
                     | (5) rewrite：讀 S3 的 v2 全文，只重寫第 3 步
                     v
            A v3：第 1、2、4 步逐字相同；B、C 完全沒動
```

**為什麼要「基表一致讀核對」？** GSI（`by_target`）是最終一致讀，剛寫進去的邊可能還查不到。如果只信 GSI，一篇本來該改的教學會被誤判成 KEEP。設計 §10 的作法是：改版前用主表把「目前已發布版本的完整引用集合」重算一次，跟 GSI 的結果取聯集。這樣 GSI 慢了也不會漏。

### 5.2 §7.4 的決策樹

```text
                        新的 Release
                             |
                   locate_feature
                   先比 name / aliases
                     /            \
                  命中            未命中
                    |                |
              alias_hit=True   對所有 Feature 的
                    |          name+aliases 算 embedding
                    |          取最高 cosine
                    |                |
                    |          >= 0.85 ?
                    |          /        \
                    |        是          否
                    |         |           |
                    |   alias_hit=False  action=KEEP
                    |                    keep_reason="無有效 Feature"
                    |                    不建立 Feature、不改版
                    v
                find_steps（只取目前已發布版本的步驟）
                             |
                   +---------+----------+
                   |                    |
             反查為零？           renamed 且 alias_hit=False？
             （獨立觸發）          （這才叫「重大改名」——F16）
                   \                    /
                    +--------+---------+
                             |  任一成立
                             v
                        safety_net
              對「目前已發布步驟」的文字算 embedding
              取前幾名 -> prompt_confirm_step_hits
                        -> StepConfirmation
                             |
                    確認到任何步驟嗎？
                     /              \
                   有               沒有
                    |                 |
            併進 hits（不抹掉     記錄未命中
            原本已有的命中）          |
                    |                 |
                    v                 v
                          decide
                             |
       +---------------------+---------------------+
       |                     |                     |
  kind == removed      有 hits 且              沒有 hits
       |               kind in {renamed,            |
       v               changed}                     v
    RETIRE                  |                    KEEP
       |                    v                 keep_reason 記未命中
       |                 UPDATE                    |
       |                    |                      v
       v              rewrite -> publish        （結束）
    retire                  |
       |                    v
       |             update_aliases（只有 renamed 要做）
       |                    |
       |            alias 撞名？ -> 是 -> PermanentError（整次失敗，不是 KEEP）
       v                    v
    （結束）            （結束）
```

兩個容易記錯的地方：

- **「重大改名」的定義很窄。** F16 明寫「只有 alias 比對失敗的 renamed 才算重大改名；反查為零仍獨立觸發」。也就是說 alias 已經命中的 renamed **不會**跑 safety_net（除非反查剛好為零）。
- **「補漏沒命中」是 KEEP，「alias 撞名」是失敗。** F18 說 safety_net 全數未確認就記錄未命中並以 KEEP 結束；但設計 §7.4 的失敗列明寫「alias 撞名、模型輸出違規或寫入失敗……不把技術故障當 KEEP」。前者是業務結果，後者是錯誤。

### 5.3 UPDATE 怎麼保證「其餘步驟逐字相同」

只靠 prompt 叫模型「不要改其他步驟」是不夠的。程式要自己驗：

```text
  讀出 v2 的四個步驟（DynamoDB 的 STEP item 是權威）
        index 1  "開啟行事曆，找到今天的會議。"          type=click_ui  feature=Calendar
        index 2  "點右上角的齒輪開啟設定。"              type=click_ui  feature=Settings
        index 3  "在會議頁面右上角選擇 Meeting Summary。" type=click_ui  feature=Prepare   <- 命中
        index 4  "確認摘要內容後關閉視窗。"              type=read      feature=Prepare
        |
        | target_indexes = [3]
        v
  prompt_rewrite_steps(steps, target_indexes, evidence, rules_block)
        |
        v
  StepRewrite(rewrites=[StepRewriteItem(index=3, text="...Prepare...", type=click_ui, feature_id="Prepare")])
        |
        | 程式核對（做不到就 PermanentError，不重試到天荒地老）
        |   a. 回傳的 index 集合 == target_indexes（不多不少）
        |   b. 每個 rewrite 的 feature_id 存在於圖譜（每步恰好一個 Feature——D05）
        |   c. 沒被命中的 index 我們根本不問模型，直接複製原文
        v
  組成新的 TutorialContent -> validate_content -> create_version
        |
        v
  v3：index 1、2、4 的 text 與 v2 逐字相同；index 3 換成新文字
```

第 4 步也引用 `Prepare`，但它沒有被反查命中嗎？會的——反查是看 `REFERENCES` 邊，第 4 步也有邊，所以 `target_indexes` 會是 `[3, 4]`。這裡的圖只是示意「命中集合怎麼被使用」。Gherkin 的 Example 用的是「A 的 v2 只有第 3 步引用該功能」這個前提，所以測試要照那個前提建資料。

### 5.4 五段內容從哪裡來

`create_version` 需要一份完整的 `TutorialContent`（title／problem／prerequisites／steps／expected_outcome），但 DynamoDB 只保留每一步的文字，四段散文只存在 S3 的 `.md` 裡。

好消息是 Phase 08（`08-Phase08-Content-發布與退役.md`）已經做好 `content.parse_markdown(markdown) -> TutorialContent`，它是 Phase 07 `render_markdown` 的反函式。因為 `render_markdown` 把每一步寫成 `<編號>. (type=<型態>, feature=<Feature>) <文字>` 這種固定格式，連 `type` 與 `feature_id` 都還原得回來：

```text
  S3: tutorials/prepare-meeting/v2.md
  ---------------------------------------------------------------
  # 準備會議前的摘要                                  -> title

  ## Problem
  使用者找不到會前摘要。                              -> problem

  ## Prerequisites
  - 已登入                                            -> prerequisites[0]
  - 已建立會議                                        -> prerequisites[1]

  ## Steps
  1. (type=click_ui, feature=Calendar) 開啟行事曆...   -> StepDraft
  2. (type=click_ui, feature=Notification Settings)…  -> StepDraft
  3. (type=click_ui, feature=Prepare) 在會議頁面...    -> StepDraft
  4. (type=read, feature=Calendar) 確認摘要內容...     -> StepDraft

  ## Expected Outcome
  你可以在會議頁面看到會前摘要。                      -> expected_outcome
```

所以本階段**不新增**這個函式，只消費它。不過命中集合的編號來自 DynamoDB 的 `STEP#` item，所以 `rewrite` 會多做一次核對：`parse_markdown` 還原出來的步驟文字，必須跟 `repo.get_steps(version_id)` 逐字一致。對不上就代表 S3 與基表不同步，直接以 `PermanentError` 結束，不硬改。Phase 17 的 REFINE 也走同一條路。

### 5.5 state 在八個 task 之間怎麼長大

```text
  進入流程時
    {"release_id": "r_42", "operation_id": "ingest:release:r_42"}
         |
  locate_feature  + feature_id, alias_hit
         |          （找不到時：+ action="KEEP", keep_reason）
  find_steps      + hits=[{"slug","version_id","index"}, ...]
         |
  safety_net      + hits（可能變多，不會變少）, safety_net_used
         |
  decide          + action("UPDATE"|"RETIRE"|"KEEP"), keep_reason
         |
  rewrite         + new_version_ids=["prepare-meeting@v3"]
         |
  publish         + published=True
         |
  retire          + retired_slugs=["prepare-meeting"]
         |
  update_aliases  + aliases_updated=True
```

設計 §14.3 規定 state 只能帶 ID、小型判斷結果與 S3 key，不能帶全文或向量。上面每一個新增的鍵都符合。

### 5.6 本階段新增的目錄結構

```text
AWS-Hackathon/
  src/training_kb/
    pipelines/
      release.py                   <- 新增（八個 task + TASKS）
    writing/
      prompts.py                   <- 修改：prompt_rewrite_steps、prompt_confirm_step_hits
  infra/
    asl/release-update.asl.json    <- 新增
    stacks/app_stack.py            <- 修改：第二條 state machine
  tests/
    unit/
      release_fakes.py             <- 新增（八個測試檔共用的假資料層）
      test_prompt_rewrite_steps.py
      test_release_locate.py       test_release_find_steps.py
      test_release_safety_net.py   test_release_decide.py
      test_release_rewrite.py      test_release_publish_retire.py
      test_release_aliases.py      test_asl_release.py
  （content.py 不修改：parse_markdown 由 Phase 08 提供）
```

---

## 6. 工作項目

### Task 1：測試用的假資料層與 `task_locate_feature`

**目的**：先建一組八個 task 共用的假 Repository／假 Writer，再做第一個 task：找到改版對應的 Feature。

**檔案**：
- 新增：`tests/unit/release_fakes.py`
- 新增：`src/training_kb/pipelines/release.py`
- 測試：`tests/unit/test_release_locate.py`

**介面**：
- 消費：`repository.Repository.find_feature_by_name_or_alias(name) -> Feature | None`、`list_features() -> list[Feature]`、`get_release(release_id) -> Release | None`（Phase 09）、`writing.client.Writer.embed(text, *, operation_id, node) -> list[float]`、`writing.client.cosine(a, b) -> float`（Phase 05）、`config.Thresholds.cosine_feature`（Phase 01）、`pipelines.common.Deps`（Phase 13）
- 產出：
  - `pipelines.release.lookup_names(release: Release) -> list[str]`
  - `pipelines.release.semantic_feature(deps, release, operation_id: str) -> tuple[Feature | None, float | None]`
  - `pipelines.release.task_locate_feature(state: dict, deps: Deps) -> dict`
  - `pipelines.release.TASKS: dict[str, TaskFn]`（本 Task 先放一個，之後逐一補齊）
  - state 新增鍵：`feature_id`、`alias_hit`、`feature_match_score`、（找不到時）`action`、`keep_reason`

> **本計劃選擇**：設計 §7.4 只說「先比 name／alias」。`Release.feature`、`old_name`、`new_name` 三個欄位都可能是那個功能的名字，所以 `lookup_names` 依序試這三個（去掉空值與重複）。這樣 `依改版更新教學.feature` Rule 2 的 Example（`FEATURE#Prepare` 的 aliases 有 `Meeting Summary`，PR 的 `old_name` 是 `Meeting Summary`）在「改版前 name 還是舊名」與「改版後 name 已是新名」兩種狀態下都找得到。

- [ ] **步驟 1：寫測試**

先建共用的假資料層（後面七個 Task 都會 `from release_fakes import ...`）：

```python
# tests/unit/release_fakes.py
"""Release Note Update 流程的測試用假資料層。

只實作 pipelines/release.py 會呼叫到的方法；其餘一律不提供，
這樣一旦流程偷偷用了沒約定好的介面，測試會直接 AttributeError。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from training_kb.config import Settings, Thresholds
from training_kb.models import (
    AuthoringRule,
    Feature,
    Release,
    ReleaseKind,
    ReleaseSource,
    StepType,
    Tutorial,
    TutorialStatus,
    TutorialStep,
    TutorialVersion,
)

NOW = datetime(2026, 9, 1, 0, 0, 0, tzinfo=UTC)


def make_settings() -> Settings:
    return Settings(
        aws_region="us-east-1",
        table_name="training_kb",
        bucket_name="training-kb-content-demo",
        project_id="demo-project",
        embed_model_id="amazon.titan-embed-text-v2:0",
        embed_dimensions=1024,
        gen_model_id="fake-claude",
        github_webhook_secret="x",
        thresholds=Thresholds(),
    )


def renamed_release() -> Release:
    return Release(
        id="r_42",
        source=ReleaseSource.github_pr,
        source_event_id="gh-pr-42",
        feature="Meeting Summary",
        kind=ReleaseKind.renamed,
        old_name="Meeting Summary",
        new_name="Prepare",
        evidence="PR #42 將 Meeting Summary 改名為 Prepare",
        ts="2026-08-25T00:00:00Z",
    )


def a_v2_steps() -> list[TutorialStep]:
    """教學 A 的 v2 四個步驟；只有第 3 步引用 FEATURE#Prepare。"""
    return [
        TutorialStep(tutorial_version="prepare-meeting@v2", index=1, type=StepType.click_ui,
                     text="開啟行事曆，找到今天的會議。", feature_id="Calendar"),
        TutorialStep(tutorial_version="prepare-meeting@v2", index=2, type=StepType.click_ui,
                     text="點右上角的齒輪開啟設定。", feature_id="Notification Settings"),
        TutorialStep(tutorial_version="prepare-meeting@v2", index=3, type=StepType.click_ui,
                     text="在會議頁面右上角選擇 Meeting Summary，查看會前摘要。", feature_id="Prepare"),
        TutorialStep(tutorial_version="prepare-meeting@v2", index=4, type=StepType.read,
                     text="確認摘要內容後關閉視窗。", feature_id="Calendar"),
    ]


A_V2_MARKDOWN = """# 準備會議前的摘要

## Problem

使用者找不到會前摘要。

## Prerequisites

- 已登入
- 已建立會議

## Steps

1. (type=click_ui, feature=Calendar) 開啟行事曆，找到今天的會議。
2. (type=click_ui, feature=Notification Settings) 點右上角的齒輪開啟設定。
3. (type=click_ui, feature=Prepare) 在會議頁面右上角選擇 Meeting Summary，查看會前摘要。
4. (type=read, feature=Calendar) 確認摘要內容後關閉視窗。

## Expected Outcome

你可以在會議頁面看到會前摘要。
"""


class StubWriter:
    """回傳預先排定向量與 JSON 物件的假 Writer。"""

    def __init__(self, embeddings: dict[str, list[float]] | None = None, outputs: list[Any] | None = None):
        self.embeddings = embeddings or {}
        self.outputs = list(outputs or [])
        self.embed_calls: list[str] = []
        self.json_calls: list[dict] = []

    def embed(self, text: str, *, operation_id: str, node: str) -> list[float]:
        self.embed_calls.append(text)
        return self.embeddings.get(text, [0.0, 0.0, 1.0])

    def generate_json(self, *, system, user, schema, operation_id, node, max_tokens, temperature=0.1):
        self.json_calls.append({"node": node, "system": system, "user": user, "max_tokens": max_tokens})
        if not self.outputs:
            raise AssertionError(f"測試沒有替 node={node} 準備輸出")
        return self.outputs.pop(0)


@dataclass
class FakeReleaseRepo:
    releases: dict[str, Release] = field(default_factory=dict)
    features: dict[str, Feature] = field(default_factory=dict)
    tutorials: dict[str, Tutorial] = field(default_factory=dict)
    versions: dict[str, TutorialVersion] = field(default_factory=dict)
    steps: dict[str, list[TutorialStep]] = field(default_factory=dict)
    gsi_hits: dict[str, list[TutorialStep]] = field(default_factory=dict)
    rules: list[AuthoringRule] = field(default_factory=list)
    objects: dict[str, str] = field(default_factory=dict)
    updates: list[tuple[str, dict]] = field(default_factory=list)
    locks: list[str] = field(default_factory=list)

    # ---- Release / Feature ----
    def get_release(self, release_id: str) -> Release | None:
        return self.releases.get(release_id)

    def get_feature(self, feature_id: str) -> Feature | None:
        return self.features.get(feature_id)

    def list_features(self) -> list[Feature]:
        return list(self.features.values())

    def find_feature_by_name_or_alias(self, name: str) -> Feature | None:
        for feature in self.features.values():
            if name == feature.name or name in feature.aliases:
                return feature
        return None

    # ---- Tutorial / Version / Step ----
    def get_tutorial(self, slug: str) -> Tutorial | None:
        return self.tutorials.get(slug)

    def get_version(self, version_id: str) -> TutorialVersion | None:
        return self.versions.get(version_id)

    def get_steps(self, version_id: str) -> list[TutorialStep]:
        return sorted(self.steps.get(version_id, []), key=lambda s: s.index)

    def find_current_published_steps_referencing(self, feature_id: str) -> list[TutorialStep]:
        """模擬 GSI 反查；測試可以刻意讓它少回傳，驗證基表核對有補上。"""
        return list(self.gsi_hits.get(feature_id, []))

    def scan_entity(self, entity: str) -> list[dict]:
        if entity == "TUTORIAL":
            return [t.model_dump() for t in self.tutorials.values()]
        return []

    # ---- 規則、S3、metadata、鎖 ----
    def list_rules(self, status=None) -> list[AuthoringRule]:
        if status is None:
            return list(self.rules)
        return [r for r in self.rules if r.status == status]

    def get_object(self, key: str) -> bytes | None:
        value = self.objects.get(key)
        return None if value is None else value.encode("utf-8")

    def update_meta(self, pk: str, attrs: dict, *, condition_equals: dict | None = None) -> None:
        self.updates.append((pk, dict(attrs)))

    def acquire_lock(self, slug: str, owner: str, ttl_seconds: int, now: datetime) -> bool:
        self.locks.append(slug)
        return True

    def release_lock(self, slug: str, owner: str) -> None:
        return None


def make_repo(*, published_version: str = "prepare-meeting@v2", status=TutorialStatus.active) -> FakeReleaseRepo:
    """建一份「A 已發布 v2、B 與 C 不引用 Prepare」的圖譜。"""
    repo = FakeReleaseRepo()
    repo.releases["r_42"] = renamed_release()
    repo.features["Prepare"] = Feature(
        feature_id="Prepare", name="Meeting Summary", aliases=[], first_seen="2026-07-01T00:00:00Z"
    )
    repo.features["Share Summary"] = Feature(
        feature_id="Share Summary", name="Share Summary", aliases=[], first_seen="2026-07-01T00:00:00Z"
    )
    repo.features["Notification Settings"] = Feature(
        feature_id="Notification Settings", name="Notification Settings", aliases=[],
        first_seen="2026-07-01T00:00:00Z",
    )
    repo.features["Calendar"] = Feature(
        feature_id="Calendar", name="Calendar", aliases=[], first_seen="2026-07-01T00:00:00Z"
    )

    repo.tutorials["prepare-meeting"] = Tutorial(
        slug="prepare-meeting", current_version=published_version, topic="準備會議",
        feature_ids=["Prepare"], status=status, successor=None, cluster_id="c12",
    )
    repo.tutorials["share-summary"] = Tutorial(
        slug="share-summary", current_version="share-summary@v1", topic="分享摘要",
        feature_ids=["Share Summary"], status=TutorialStatus.active, successor=None, cluster_id="c20",
    )
    repo.tutorials["notification-settings"] = Tutorial(
        slug="notification-settings", current_version="notification-settings@v1", topic="設定通知",
        feature_ids=["Notification Settings"], status=TutorialStatus.active, successor=None, cluster_id="c30",
    )

    repo.versions["prepare-meeting@v1"] = TutorialVersion(
        version_id="prepare-meeting@v1", supersedes=None, reason="gap:c12", rules_applied=[],
        s3_key="tutorials/prepare-meeting/v1.md", published_at="2026-08-01T00:00:00Z",
    )
    repo.versions["prepare-meeting@v2"] = TutorialVersion(
        version_id="prepare-meeting@v2", supersedes="prepare-meeting@v1",
        reason="feedback:8 則 找不到按鈕", rules_applied=["R-007"],
        s3_key="tutorials/prepare-meeting/v2.md", published_at="2026-08-20T00:00:00Z",
    )
    repo.versions["prepare-meeting@v3"] = TutorialVersion(
        version_id="prepare-meeting@v3", supersedes="prepare-meeting@v2", reason="release:r_42",
        rules_applied=[], s3_key="tutorials/prepare-meeting/v3.md", published_at=None,
    )
    repo.versions["share-summary@v1"] = TutorialVersion(
        version_id="share-summary@v1", supersedes=None, reason="gap:c20", rules_applied=[],
        s3_key="tutorials/share-summary/v1.md", published_at="2026-08-05T00:00:00Z",
    )
    repo.versions["notification-settings@v1"] = TutorialVersion(
        version_id="notification-settings@v1", supersedes=None, reason="gap:c30", rules_applied=[],
        s3_key="tutorials/notification-settings/v1.md", published_at="2026-08-06T00:00:00Z",
    )

    repo.steps["prepare-meeting@v2"] = a_v2_steps()
    repo.steps["prepare-meeting@v1"] = [
        TutorialStep(tutorial_version="prepare-meeting@v1", index=3, type=StepType.click_ui,
                     text="舊版第三步。", feature_id="Prepare")
    ]
    repo.steps["share-summary@v1"] = [
        TutorialStep(tutorial_version="share-summary@v1", index=1, type=StepType.click_ui,
                     text="點分享按鈕。", feature_id="Share Summary")
    ]
    repo.steps["notification-settings@v1"] = [
        TutorialStep(tutorial_version="notification-settings@v1", index=1, type=StepType.click_ui,
                     text="開啟通知設定。", feature_id="Notification Settings")
    ]

    # GSI 反查同時回歷史版與目前版，流程要自己篩掉歷史版（F17）。
    repo.gsi_hits["Prepare"] = [
        repo.steps["prepare-meeting@v1"][0],
        a_v2_steps()[2],
    ]
    repo.objects["tutorials/prepare-meeting/v2.md"] = A_V2_MARKDOWN
    return repo
```

再寫 `task_locate_feature` 的測試：

```python
# tests/unit/test_release_locate.py
"""task_locate_feature：alias 優先、語意搜尋 0.85 門檻、無有效 Feature 時 KEEP。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path("tests/unit").resolve()))

from release_fakes import NOW, FakeReleaseRepo, StubWriter, make_repo, make_settings  # noqa: E402

from training_kb.pipelines.common import Deps  # noqa: E402
from training_kb.pipelines.release import lookup_names, task_locate_feature  # noqa: E402
from training_kb.writing.client import CallTrace  # noqa: E402

STATE = {"release_id": "r_42", "operation_id": "ingest:release:r_42"}


def make_deps(repo, writer) -> Deps:
    return Deps(repo=repo, writer=writer, settings=make_settings(), trace=CallTrace(), now=lambda: NOW)


def test_lookup_names_依序去重():
    repo = make_repo()
    assert lookup_names(repo.get_release("r_42")) == ["Meeting Summary", "Prepare"]


def test_name_命中時_alias_hit_為_true_且不呼叫模型():
    repo, writer = make_repo(), StubWriter()

    state = task_locate_feature(STATE, make_deps(repo, writer))

    assert state["feature_id"] == "Prepare"
    assert state["alias_hit"] is True
    assert writer.embed_calls == []


def test_alias_命中也算_alias_hit():
    repo, writer = make_repo(), StubWriter()
    repo.features["Prepare"] = repo.features["Prepare"].model_copy(
        update={"name": "Prepare", "aliases": ["Meeting Summary"]}
    )

    state = task_locate_feature(STATE, make_deps(repo, writer))

    assert state["feature_id"] == "Prepare"
    assert state["alias_hit"] is True


def test_alias_未命中時用語意搜尋且達_0_85_才採用():
    repo, writer = make_repo(), StubWriter()
    repo.features["Prepare"] = repo.features["Prepare"].model_copy(update={"name": "會前重點"})
    writer.embeddings = {
        "Meeting Summary Prepare": [1.0, 0.0, 0.0],
        "會前重點": [0.9, 0.4359, 0.0],          # cosine ≈ 0.900
        "Share Summary": [0.0, 1.0, 0.0],        # cosine = 0.0
        "Notification Settings": [0.0, 0.0, 1.0],
        "Calendar": [0.0, 0.0, 1.0],
    }

    state = task_locate_feature(STATE, make_deps(repo, writer))

    assert state["feature_id"] == "Prepare"
    assert state["alias_hit"] is False
    assert state["feature_match_score"] > 0.85


def test_語意搜尋未達門檻時不改版也不建立_feature():
    repo, writer = make_repo(), StubWriter()
    repo.features["Prepare"] = repo.features["Prepare"].model_copy(update={"name": "會前重點"})
    writer.embeddings = {
        "Meeting Summary Prepare": [1.0, 0.0, 0.0],
        "會前重點": [0.8, 0.6, 0.0],             # cosine = 0.80 < 0.85
        "Share Summary": [0.0, 1.0, 0.0],
        "Notification Settings": [0.0, 0.0, 1.0],
        "Calendar": [0.0, 0.0, 1.0],
    }
    before = len(repo.features)

    state = task_locate_feature(STATE, make_deps(repo, writer))

    assert state["feature_id"] is None
    assert state["action"] == "KEEP"
    assert "無有效 Feature" in state["keep_reason"]
    assert len(repo.features) == before


def test_剛好_0_85_算命中():
    repo, writer = make_repo(), StubWriter()
    repo.features["Prepare"] = repo.features["Prepare"].model_copy(update={"name": "會前重點"})
    writer.embeddings = {
        "Meeting Summary Prepare": [1.0, 0.0, 0.0],
        "會前重點": [0.85, 0.5267, 0.0],         # cosine = 0.85
        "Share Summary": [0.0, 1.0, 0.0],
        "Notification Settings": [0.0, 0.0, 1.0],
        "Calendar": [0.0, 0.0, 1.0],
    }

    state = task_locate_feature(STATE, make_deps(repo, writer))

    assert state["feature_id"] == "Prepare"


def test_找不到_release_是永久錯誤():
    import pytest

    from training_kb.errors import PermanentError

    repo, writer = FakeReleaseRepo(), StubWriter()
    with pytest.raises(PermanentError):
        task_locate_feature(STATE, make_deps(repo, writer))
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：`uv run pytest tests/unit/test_release_locate.py -v`

預期：FAIL，`ModuleNotFoundError: No module named 'training_kb.pipelines.release'`。

- [ ] **步驟 3：寫最少的程式讓測試通過**

```python
# src/training_kb/pipelines/release.py
"""Release Note Update 流程的八個 task（設計 §7.4）。

state 進來時只有 release_id 與 operation_id；每個 task 回傳一個新的 state。
"""

from __future__ import annotations

from training_kb.errors import PermanentError
from training_kb.models import Feature, Release
from training_kb.pipelines.common import Deps, TaskFn
from training_kb.writing.client import cosine

#: safety_net 與 locate_feature 共用的呼叫節點名稱，方便在 trace 裡分辨。
NODE_LOCATE = "release:locate_feature"


def load_release(state: dict, deps: Deps) -> Release:
    release_id = state.get("release_id")
    release = deps.repo.get_release(release_id) if release_id else None
    if release is None:
        raise PermanentError(f"找不到 Release：{release_id}")
    return release


def lookup_names(release: Release) -> list[str]:
    """要拿去比對 name／aliases 的候選名稱，依序、去重、去空值。"""
    names: list[str] = []
    for value in (release.feature, release.old_name, release.new_name):
        text = (value or "").strip()
        if text and text not in names:
            names.append(text)
    return names


def semantic_feature(deps: Deps, release: Release, operation_id: str) -> tuple[Feature | None, float | None]:
    """name／alias 未命中時的語意搜尋；最高 cosine 至少 0.85 才採用（F15）。"""
    features = deps.repo.list_features()
    if not features:
        return None, None
    query = " ".join(lookup_names(release))
    query_vector = deps.writer.embed(query, operation_id=operation_id, node=NODE_LOCATE)

    scored: list[tuple[float, str, Feature]] = []
    for feature in features:
        text = " ".join([feature.name, *feature.aliases])
        vector = deps.writer.embed(text, operation_id=operation_id, node=NODE_LOCATE)
        scored.append((cosine(query_vector, vector), feature.feature_id, feature))
    # 分數高者優先；同分依 Feature 識別碼升序，消除平手的不確定性。
    scored.sort(key=lambda item: (-item[0], item[1]))

    best_score, _, best = scored[0]
    if best_score >= deps.settings.thresholds.cosine_feature:
        return best, best_score
    return None, best_score


def task_locate_feature(state: dict, deps: Deps) -> dict:
    release = load_release(state, deps)

    for name in lookup_names(release):
        feature = deps.repo.find_feature_by_name_or_alias(name)
        if feature is not None:
            return {**state, "feature_id": feature.feature_id, "alias_hit": True,
                    "feature_match_score": None}

    feature, score = semantic_feature(deps, release, state["operation_id"])
    if feature is None:
        return {
            **state,
            "feature_id": None,
            "alias_hit": False,
            "feature_match_score": score,
            "action": "KEEP",
            "keep_reason": (
                "無有效 Feature：name/alias 未命中，語意搜尋最高相似度 "
                f"{score if score is not None else 'N/A'} 未達 "
                f"{deps.settings.thresholds.cosine_feature}"
            ),
        }
    return {**state, "feature_id": feature.feature_id, "alias_hit": False,
            "feature_match_score": score}


TASKS: dict[str, TaskFn] = {
    "locate_feature": task_locate_feature,
}
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：`uv run pytest tests/unit/test_release_locate.py -v`

預期：PASS，7 個測試綠色。

- [ ] **步驟 5：commit**

```bash
git add tests/unit/release_fakes.py tests/unit/test_release_locate.py \
        src/training_kb/pipelines/release.py
git commit -m "feat(pipelines): Release 流程定位 Feature"
```

---

### Task 2：`task_find_steps`——反查目前已發布版本的步驟

**目的**：從 Feature 反查引用它的步驟，只留「目前已發布版本」的，而且要用基表一致讀補上 GSI 可能漏掉的部分。

**檔案**：
- 修改：`src/training_kb/pipelines/release.py`
- 測試：`tests/unit/test_release_find_steps.py`

**介面**：
- 消費：`repository.Repository.find_current_published_steps_referencing(feature_id) -> list[TutorialStep]`、`scan_entity(entity) -> list[dict]`、`get_version(version_id)`、`get_steps(version_id)`（Phase 03、09）、`models.parse_version_id`
- 產出：
  - `pipelines.release.base_table_hits(repo, feature_id: str) -> list[TutorialStep]`
  - `pipelines.release.to_hit(step: TutorialStep) -> dict`
  - `pipelines.release.merge_hits(existing: list[dict], extra: list[dict]) -> list[dict]`
  - `pipelines.release.task_find_steps(state, deps) -> dict`
  - state 新增鍵：`hits: list[{"slug", "version_id", "index"}]`

- [ ] **步驟 1：寫測試**

```python
# tests/unit/test_release_find_steps.py
"""task_find_steps：只取目前已發布版本，並用基表一致讀補上 GSI 的漏。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path("tests/unit").resolve()))

from release_fakes import NOW, StubWriter, make_repo, make_settings  # noqa: E402

from training_kb.models import TutorialStatus  # noqa: E402
from training_kb.pipelines.common import Deps  # noqa: E402
from training_kb.pipelines.release import merge_hits, task_find_steps  # noqa: E402
from training_kb.writing.client import CallTrace  # noqa: E402

STATE = {"release_id": "r_42", "operation_id": "ingest:release:r_42", "feature_id": "Prepare",
         "alias_hit": True}


def make_deps(repo) -> Deps:
    return Deps(repo=repo, writer=StubWriter(), settings=make_settings(), trace=CallTrace(),
                now=lambda: NOW)


def test_只命中教學_a_的第三步():
    repo = make_repo()

    state = task_find_steps(STATE, make_deps(repo))

    assert state["hits"] == [{"slug": "prepare-meeting", "version_id": "prepare-meeting@v2", "index": 3}]


def test_歷史版本的命中不觸發改寫():
    repo = make_repo()

    hits = task_find_steps(STATE, make_deps(repo))["hits"]

    assert all(h["version_id"] == "prepare-meeting@v2" for h in hits)
    assert "prepare-meeting@v1" not in {h["version_id"] for h in hits}


def test_未發布版本的命中不觸發改寫():
    repo = make_repo()
    # 讓 v3（published_at 為 None）成為 current_version：不該被當成「目前已發布版本」。
    repo.tutorials["prepare-meeting"] = repo.tutorials["prepare-meeting"].model_copy(
        update={"current_version": "prepare-meeting@v3"}
    )
    repo.steps["prepare-meeting@v3"] = repo.steps["prepare-meeting@v2"]

    assert task_find_steps(STATE, make_deps(repo))["hits"] == []


def test_gsi_還沒反映時基表一致讀仍找得到():
    repo = make_repo()
    repo.gsi_hits["Prepare"] = []          # 模擬 GSI 延遲，什麼都查不到

    state = task_find_steps(STATE, make_deps(repo))

    assert state["hits"] == [{"slug": "prepare-meeting", "version_id": "prepare-meeting@v2", "index": 3}]


def test_b_與_c_沒有引用時完全不在命中集合():
    repo = make_repo()

    hits = task_find_steps(STATE, make_deps(repo))["hits"]

    assert {h["slug"] for h in hits} == {"prepare-meeting"}


def test_退役教學不納入命中():
    repo = make_repo(status=TutorialStatus.retired)

    assert task_find_steps(STATE, make_deps(repo))["hits"] == []


def test_沒有_feature_id_時直接保持原狀():
    repo = make_repo()
    state = task_find_steps({**STATE, "feature_id": None, "action": "KEEP"}, make_deps(repo))
    assert state["hits"] == []
    assert state["action"] == "KEEP"


def test_merge_hits_不重複也不抹掉原本命中():
    existing = [{"slug": "a", "version_id": "a@v2", "index": 3}]
    extra = [
        {"slug": "a", "version_id": "a@v2", "index": 3},
        {"slug": "a", "version_id": "a@v2", "index": 1},
    ]
    assert merge_hits(existing, extra) == [
        {"slug": "a", "version_id": "a@v2", "index": 1},
        {"slug": "a", "version_id": "a@v2", "index": 3},
    ]
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：`uv run pytest tests/unit/test_release_find_steps.py -v`

預期：FAIL，`ImportError: cannot import name 'task_find_steps' from 'training_kb.pipelines.release'`。

- [ ] **步驟 3：寫最少的程式讓測試通過**

在 `src/training_kb/pipelines/release.py` 加上（並把 `TASKS` 補上第二個項目）：

```python
from training_kb.models import Tutorial, TutorialStatus, TutorialStep, parse_version_id


def to_hit(step: TutorialStep) -> dict:
    slug, _n = parse_version_id(step.tutorial_version)
    return {"slug": slug, "version_id": step.tutorial_version, "index": step.index}


def merge_hits(existing: list[dict], extra: list[dict]) -> list[dict]:
    """把補漏找到的命中併進既有命中；去重、排序，不抹掉原本已有的（設計 §7.4）。"""
    seen: dict[tuple[str, str, int], dict] = {}
    for hit in [*existing, *extra]:
        seen[(hit["slug"], hit["version_id"], int(hit["index"]))] = hit
    return [seen[key] for key in sorted(seen)]


def current_published_versions(repo) -> list[tuple[str, str]]:
    """回傳 (slug, version_id)：active 教學、有 current_version、且該版已發布。"""
    result: list[tuple[str, str]] = []
    for item in repo.scan_entity("TUTORIAL"):
        tutorial = Tutorial.model_validate(item)
        if tutorial.status != TutorialStatus.active or not tutorial.current_version:
            continue
        version = repo.get_version(tutorial.current_version)
        if version is None or not version.published_at:
            continue
        result.append((tutorial.slug, tutorial.current_version))
    return sorted(result)


def base_table_hits(repo, feature_id: str) -> list[TutorialStep]:
    """以基表一致讀重算「目前已發布版本」中引用 feature_id 的步驟。

    設計 §10：GSI 只有最終一致讀，可能尚未反映剛寫入的邊；改版前用基表核對，
    避免暫時少資料就錯判 KEEP。
    """
    hits: list[TutorialStep] = []
    for _slug, version_id in current_published_versions(repo):
        for step in repo.get_steps(version_id):
            if step.feature_id == feature_id:
                hits.append(step)
    return hits


def task_find_steps(state: dict, deps: Deps) -> dict:
    feature_id = state.get("feature_id")
    if not feature_id:
        return {**state, "hits": []}

    allowed = {version_id for _slug, version_id in current_published_versions(deps.repo)}
    gsi = [
        step
        for step in deps.repo.find_current_published_steps_referencing(feature_id)
        if step.tutorial_version in allowed          # F17：歷史版與未發布版不觸發改寫
    ]
    base = base_table_hits(deps.repo, feature_id)
    hits = merge_hits([to_hit(s) for s in gsi], [to_hit(s) for s in base])
    return {**state, "hits": hits}


TASKS["find_steps"] = task_find_steps
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：`uv run pytest tests/unit/test_release_find_steps.py -v`

預期：PASS，8 個測試綠色。

- [ ] **步驟 5：commit**

```bash
git add tests/unit/test_release_find_steps.py src/training_kb/pipelines/release.py
git commit -m "feat(pipelines): Release 流程反查目前已發布步驟"
```

---

### Task 3：`task_safety_net`——補漏與 Claude 確認

**目的**：反查為零、或是「alias 比對失敗的 renamed」時，用步驟文字做語意搜尋找候選，再請 Claude 確認哪些真的要改。

**檔案**：
- 修改：`src/training_kb/pipelines/release.py`
- 修改：`src/training_kb/writing/prompts.py`
- 測試：`tests/unit/test_release_safety_net.py`

**介面**：
- 消費：`writing.prompts.prompt_confirm_step_hits(release, candidate_steps) -> tuple[str, str]`（本 Task 實作）、`writing.schemas.StepConfirmation`（Phase 05）、`writing.client.Writer.embed`、`generate_json`、`cosine`
- 產出：
  - `writing.prompts.prompt_confirm_step_hits(release: Release, candidate_steps: list[TutorialStep]) -> tuple[str, str]`
  - `pipelines.release.SAFETY_NET_TOP_K: int`（值為 5）
  - `pipelines.release.needs_safety_net(release, state) -> bool`
  - `pipelines.release.candidate_steps(repo, exclude: set[tuple[str, int]]) -> list[TutorialStep]`
  - `pipelines.release.task_safety_net(state, deps) -> dict`
  - state 新增鍵：`safety_net_used: bool`；`hits` 可能變多

> **`StepConfirmation.confirmed_indexes` 指的是什麼？本計劃選擇**：候選步驟會橫跨好幾篇教學，光給「步驟編號」沒辦法唯一指出是哪一步。所以 `prompt_confirm_step_hits` 會把候選**從 1 開始編號**列給模型，`confirmed_indexes` 就是**候選清單的序號**，不是步驟在教學裡的 index。程式再把序號換回真正的步驟。簡報第 6.4 節只寫了 `StepConfirmation(confirmed_indexes: list[int])`，沒有定義語意，這裡補上。

- [ ] **步驟 1：寫測試**

```python
# tests/unit/test_release_safety_net.py
"""task_safety_net：觸發條件、候選排序、Claude 確認與未命中結果。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path("tests/unit").resolve()))

from release_fakes import NOW, StubWriter, make_repo, make_settings  # noqa: E402

from training_kb.models import ReleaseKind  # noqa: E402
from training_kb.pipelines.common import Deps  # noqa: E402
from training_kb.pipelines.release import needs_safety_net, task_safety_net  # noqa: E402
from training_kb.writing.client import CallTrace  # noqa: E402
from training_kb.writing.prompts import prompt_confirm_step_hits  # noqa: E402
from training_kb.writing.schemas import StepConfirmation  # noqa: E402

HIT_3 = {"slug": "prepare-meeting", "version_id": "prepare-meeting@v2", "index": 3}
BASE = {"release_id": "r_42", "operation_id": "ingest:release:r_42", "feature_id": "Prepare"}


def make_deps(repo, writer) -> Deps:
    return Deps(repo=repo, writer=writer, settings=make_settings(), trace=CallTrace(), now=lambda: NOW)


def test_alias_命中且有反查結果時不跑_safety_net():
    repo = make_repo()
    assert needs_safety_net(repo.get_release("r_42"), {**BASE, "alias_hit": True, "hits": [HIT_3]}) is False


def test_反查為零就獨立觸發_即使_alias_命中():
    repo = make_repo()
    assert needs_safety_net(repo.get_release("r_42"), {**BASE, "alias_hit": True, "hits": []}) is True


def test_alias_未命中的_renamed_算重大改名_即使已有命中():
    repo = make_repo()
    assert needs_safety_net(repo.get_release("r_42"), {**BASE, "alias_hit": False, "hits": [HIT_3]}) is True


def test_alias_未命中的_changed_不算重大改名():
    repo = make_repo()
    release = repo.get_release("r_42").model_copy(
        update={"kind": ReleaseKind.changed, "old_name": None, "new_name": None}
    )
    assert needs_safety_net(release, {**BASE, "alias_hit": False, "hits": [HIT_3]}) is False


def test_確認到的候選會被併進_hits():
    repo = make_repo()
    writer = StubWriter(
        embeddings={
            "PR #42 將 Meeting Summary 改名為 Prepare Meeting Summary Prepare": [1.0, 0.0, 0.0],
            "在會議頁面右上角選擇 Meeting Summary，查看會前摘要。": [1.0, 0.0, 0.0],
            "開啟行事曆，找到今天的會議。": [0.0, 1.0, 0.0],
            "點右上角的齒輪開啟設定。": [0.0, 1.0, 0.0],
            "確認摘要內容後關閉視窗。": [0.0, 1.0, 0.0],
            "點分享按鈕。": [0.0, 1.0, 0.0],
            "開啟通知設定。": [0.0, 1.0, 0.0],
        },
        outputs=[StepConfirmation(confirmed_indexes=[1])],
    )

    state = task_safety_net({**BASE, "alias_hit": True, "hits": []}, make_deps(repo, writer))

    assert state["safety_net_used"] is True
    assert state["hits"] == [HIT_3]


def test_全數未確認時記錄未命中且不建立新版():
    repo = make_repo()
    writer = StubWriter(outputs=[StepConfirmation(confirmed_indexes=[])])

    state = task_safety_net({**BASE, "alias_hit": True, "hits": []}, make_deps(repo, writer))

    assert state["hits"] == []
    assert "未命中" in state["keep_reason"]


def test_不抹掉原本已有的明確命中():
    repo = make_repo()
    writer = StubWriter(outputs=[StepConfirmation(confirmed_indexes=[])])

    state = task_safety_net({**BASE, "alias_hit": False, "hits": [HIT_3]}, make_deps(repo, writer))

    assert state["hits"] == [HIT_3]


def test_候選只包含目前已發布版本的步驟():
    repo = make_repo()
    writer = StubWriter(outputs=[StepConfirmation(confirmed_indexes=[])])

    task_safety_net({**BASE, "alias_hit": True, "hits": []}, make_deps(repo, writer))

    assert "舊版第三步。" not in writer.embed_calls


def test_沒有候選時不呼叫模型():
    repo = make_repo()
    repo.steps = {}
    writer = StubWriter()

    state = task_safety_net({**BASE, "alias_hit": True, "hits": []}, make_deps(repo, writer))

    assert writer.json_calls == []
    assert state["hits"] == []


def test_prompt_把候選從_1_開始編號():
    repo = make_repo()
    system, user = prompt_confirm_step_hits(repo.get_release("r_42"), repo.get_steps("prepare-meeting@v2"))

    assert "confirmed_indexes" in system
    assert "1." in user and "4." in user
    assert "在會議頁面右上角選擇 Meeting Summary，查看會前摘要。" in user
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：`uv run pytest tests/unit/test_release_safety_net.py -v`

預期：FAIL，`ImportError: cannot import name 'needs_safety_net'`（以及 `prompt_confirm_step_hits` 尚未實作）。

- [ ] **步驟 3：寫最少的程式讓測試通過**

先在 `src/training_kb/writing/prompts.py` 加上 prompt：

```python
def prompt_confirm_step_hits(release, candidate_steps) -> tuple[str, str]:
    """safety_net 的確認 prompt（設計 §7.4：疑似命中交給 Claude 確認）。

    候選從 1 開始編號；模型回傳的 confirmed_indexes 指的是「候選清單的序號」。
    """
    system = (
        "你是技術文件維護助理。使用者會給你一則產品改版說明，以及一份候選教學步驟清單。\n"
        "請判斷哪些候選步驟的內容真的受這次改版影響，需要改寫。\n"
        "只輸出 JSON，格式為 {\"confirmed_indexes\": [整數, ...]}。\n"
        "confirmed_indexes 是候選清單的序號（從 1 開始），不是步驟在教學裡的編號。\n"
        "無法確定就不要放進去；寧可少選，也不要誤改沒有受影響的步驟。\n"
        "不要輸出 JSON 以外的任何文字。"
    )
    lines = [
        "改版說明：",
        f"- 功能：{release.feature}",
        f"- 種類：{release.kind}",
        f"- 舊名稱：{release.old_name or '（無）'}",
        f"- 新名稱：{release.new_name or '（無）'}",
        f"- 證據：{release.evidence}",
        "",
        "候選步驟：",
    ]
    for number, step in enumerate(candidate_steps, start=1):
        lines.append(
            f"{number}. [{step.tutorial_version} 第 {step.index} 步｜type={step.type}] {step.text}"
        )
    return system, "\n".join(lines)
```

再在 `src/training_kb/pipelines/release.py` 加上：

```python
from training_kb.models import ReleaseKind
from training_kb.writing.prompts import prompt_confirm_step_hits
from training_kb.writing.schemas import StepConfirmation

NODE_SAFETY_NET = "release:safety_net"
#: 交給模型確認的候選上限；設計 §14.3 要求 state 與 prompt 都保持小量。
SAFETY_NET_TOP_K = 5


def needs_safety_net(release: Release, state: dict) -> bool:
    """F16：反查為零就獨立觸發；另外只有『alias 比對失敗的 renamed』算重大改名。"""
    if not state.get("hits"):
        return True
    return release.kind == ReleaseKind.renamed and not state.get("alias_hit", False)


def candidate_steps(repo, exclude: set[tuple[str, int]]) -> list[TutorialStep]:
    """所有『目前已發布版本』的步驟，扣掉已經明確命中的那些。"""
    steps: list[TutorialStep] = []
    for _slug, version_id in current_published_versions(repo):
        for step in repo.get_steps(version_id):
            if (step.tutorial_version, step.index) not in exclude:
                steps.append(step)
    return steps


def task_safety_net(state: dict, deps: Deps) -> dict:
    release = load_release(state, deps)
    hits = list(state.get("hits", []))
    if not needs_safety_net(release, state):
        return {**state, "hits": hits, "safety_net_used": False}

    operation_id = state["operation_id"]
    exclude = {(hit["version_id"], int(hit["index"])) for hit in hits}
    candidates = candidate_steps(deps.repo, exclude)
    if not candidates:
        return {
            **state,
            "hits": hits,
            "safety_net_used": True,
            "keep_reason": "safety_net 沒有任何候選步驟，本次未命中",
        }

    query_text = " ".join([release.evidence, *lookup_names(release)])
    query_vector = deps.writer.embed(query_text, operation_id=operation_id, node=NODE_SAFETY_NET)
    scored: list[tuple[float, str, int, TutorialStep]] = []
    for step in candidates:
        vector = deps.writer.embed(step.text, operation_id=operation_id, node=NODE_SAFETY_NET)
        scored.append((cosine(query_vector, vector), step.tutorial_version, step.index, step))
    scored.sort(key=lambda item: (-item[0], item[1], item[2]))
    shortlist = [item[3] for item in scored[:SAFETY_NET_TOP_K]]

    system, user = prompt_confirm_step_hits(release, shortlist)
    confirmation: StepConfirmation = deps.writer.generate_json(
        system=system,
        user=user,
        schema=StepConfirmation,
        operation_id=operation_id,
        node=NODE_SAFETY_NET,
        max_tokens=deps.settings.gen_max_tokens_judgement,
        temperature=deps.settings.gen_temperature,
    )

    confirmed: list[dict] = []
    for number in confirmation.confirmed_indexes:
        if 1 <= int(number) <= len(shortlist):
            confirmed.append(to_hit(shortlist[int(number) - 1]))
    merged = merge_hits(hits, confirmed)

    result = {**state, "hits": merged, "safety_net_used": True}
    if not merged:
        # F18：全數未確認時記錄未命中並以 KEEP 結束，不建立新版本。
        result["keep_reason"] = "safety_net 未確認任何步驟，本次未命中"
    return result


TASKS["safety_net"] = task_safety_net
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：`uv run pytest tests/unit/test_release_safety_net.py -v`

預期：PASS，10 個測試綠色。

- [ ] **步驟 5：commit**

```bash
git add tests/unit/test_release_safety_net.py src/training_kb/pipelines/release.py \
        src/training_kb/writing/prompts.py
git commit -m "feat(pipelines): Release 流程補漏與步驟確認"
```

---

### Task 4：`task_decide`——決定 UPDATE、RETIRE 還是 KEEP

**目的**：把前三個 task 的結果收斂成一個 `action`。

**檔案**：
- 修改：`src/training_kb/pipelines/release.py`
- 測試：`tests/unit/test_release_decide.py`

**介面**：
- 消費：`models.ReleaseKind`
- 產出：`pipelines.release.task_decide(state, deps) -> dict`；state 新增鍵 `action`（`"UPDATE"` | `"RETIRE"` | `"KEEP"`）、`keep_reason`

- [ ] **步驟 1：寫測試**

```python
# tests/unit/test_release_decide.py
"""task_decide：removed -> RETIRE；有命中 -> UPDATE；無命中 -> KEEP。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path("tests/unit").resolve()))

from release_fakes import NOW, StubWriter, make_repo, make_settings  # noqa: E402

from training_kb.models import ReleaseKind  # noqa: E402
from training_kb.pipelines.common import Deps  # noqa: E402
from training_kb.pipelines.release import task_decide  # noqa: E402
from training_kb.writing.client import CallTrace  # noqa: E402

HIT_3 = {"slug": "prepare-meeting", "version_id": "prepare-meeting@v2", "index": 3}
BASE = {"release_id": "r_42", "operation_id": "ingest:release:r_42", "feature_id": "Prepare",
        "alias_hit": True, "safety_net_used": False}


def deps_for(repo) -> Deps:
    return Deps(repo=repo, writer=StubWriter(), settings=make_settings(), trace=CallTrace(),
                now=lambda: NOW)


def set_kind(repo, kind: ReleaseKind):
    repo.releases["r_42"] = repo.releases["r_42"].model_copy(update={"kind": kind})


def test_renamed_有命中就是_update():
    repo = make_repo()
    assert task_decide({**BASE, "hits": [HIT_3]}, deps_for(repo))["action"] == "UPDATE"


def test_changed_有命中也是_update():
    repo = make_repo()
    set_kind(repo, ReleaseKind.changed)
    assert task_decide({**BASE, "hits": [HIT_3]}, deps_for(repo))["action"] == "UPDATE"


def test_removed_是_retire():
    repo = make_repo()
    set_kind(repo, ReleaseKind.removed)
    assert task_decide({**BASE, "hits": [HIT_3]}, deps_for(repo))["action"] == "RETIRE"


def test_沒有命中就是_keep_並記原因():
    repo = make_repo()
    state = task_decide({**BASE, "hits": []}, deps_for(repo))
    assert state["action"] == "KEEP"
    assert state["keep_reason"]


def test_keep_原因沿用_safety_net_寫的那一句():
    repo = make_repo()
    state = task_decide(
        {**BASE, "hits": [], "keep_reason": "safety_net 未確認任何步驟，本次未命中"}, deps_for(repo)
    )
    assert state["keep_reason"] == "safety_net 未確認任何步驟，本次未命中"


def test_沒有_feature_id_時維持前面寫好的_keep():
    repo = make_repo()
    state = task_decide(
        {**BASE, "feature_id": None, "hits": [], "action": "KEEP", "keep_reason": "無有效 Feature"},
        deps_for(repo),
    )
    assert state["action"] == "KEEP"
    assert state["keep_reason"] == "無有效 Feature"


def test_removed_但沒有命中仍是_retire_由_retire_task_記錄無受影響教學():
    repo = make_repo()
    set_kind(repo, ReleaseKind.removed)
    assert task_decide({**BASE, "hits": []}, deps_for(repo))["action"] == "RETIRE"
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：`uv run pytest tests/unit/test_release_decide.py -v`

預期：FAIL，`ImportError: cannot import name 'task_decide'`。

- [ ] **步驟 3：寫最少的程式讓測試通過**

```python
def task_decide(state: dict, deps: Deps) -> dict:
    """設計 §7.4：removed -> RETIRE；renamed／changed 有命中 -> UPDATE；無命中 -> KEEP。"""
    if not state.get("feature_id"):
        # locate_feature 已經寫好 KEEP 與原因，不覆蓋。
        return {**state, "action": state.get("action", "KEEP"),
                "keep_reason": state.get("keep_reason", "無有效 Feature")}

    release = load_release(state, deps)
    if release.kind == ReleaseKind.removed:
        return {**state, "action": "RETIRE"}
    if state.get("hits"):
        return {**state, "action": "UPDATE"}
    return {
        **state,
        "action": "KEEP",
        "keep_reason": state.get("keep_reason", "未命中任何目前已發布步驟，本次不改版"),
    }


TASKS["decide"] = task_decide
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：`uv run pytest tests/unit/test_release_decide.py -v`

預期：PASS，7 個測試綠色。

- [ ] **步驟 5：commit**

```bash
git add tests/unit/test_release_decide.py src/training_kb/pipelines/release.py
git commit -m "feat(pipelines): Release 流程決定改版動作"
```

---

### Task 5：`prompt_rewrite_steps`——改寫步驟的 prompt

**目的**：寫出 UPDATE 與 REFINE 共用的改寫 prompt，並確認 Phase 08 的 `parse_markdown` 真的能把前一版全文還原成五段內容。

**檔案**：
- 修改：`src/training_kb/writing/prompts.py`
- 測試：`tests/unit/test_prompt_rewrite_steps.py`

**介面**：
- 消費：`content.render_markdown(content) -> str`（Phase 07）、`content.parse_markdown(markdown) -> TutorialContent`（Phase 08，**本階段只使用、不修改**）、`models.TutorialStep`、`models.StepDraft`
- 產出：`writing.prompts.prompt_rewrite_steps(steps, target_indexes, evidence, rules_block) -> tuple[str, str]`

> Phase 08（`08-Phase08-Content-發布與退役.md`）已經把 `parse_markdown(markdown) -> TutorialContent` 做好，而且它是 `render_markdown` 的反函式：步驟行的格式是 `<編號>. (type=<型態>, feature=<Feature>) <文字>`，所以 `type` 與 `feature_id` 都還原得回來。本階段**不重做**它，只在測試裡確認我們的 fixture 走得通。

- [ ] **步驟 1：寫測試**

```python
# tests/unit/test_prompt_rewrite_steps.py
"""改寫 prompt，以及用 Phase 08 的 parse_markdown 還原前一版全文。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path("tests/unit").resolve()))

from release_fakes import A_V2_MARKDOWN, a_v2_steps  # noqa: E402

from training_kb import content  # noqa: E402
from training_kb.models import StepType  # noqa: E402
from training_kb.writing.prompts import prompt_rewrite_steps  # noqa: E402


def test_前一版全文可以還原成五段內容():
    parsed = content.parse_markdown(A_V2_MARKDOWN)

    assert parsed.title == "準備會議前的摘要"
    assert parsed.problem == "使用者找不到會前摘要。"
    assert parsed.prerequisites == ["已登入", "已建立會議"]
    assert parsed.expected_outcome == "你可以在會議頁面看到會前摘要。"


def test_還原出來的步驟與_dynamodb_的_step_item_一致():
    parsed = content.parse_markdown(A_V2_MARKDOWN)
    steps = a_v2_steps()

    assert [draft.text for draft in parsed.steps] == [step.text for step in steps]
    assert [draft.feature_id for draft in parsed.steps] == [step.feature_id for step in steps]
    assert parsed.steps[3].type is StepType.read


def test_render_再_parse_可以還原():
    parsed = content.parse_markdown(A_V2_MARKDOWN)
    assert content.parse_markdown(content.render_markdown(parsed)) == parsed


def test_prompt_只要求改命中步驟():
    system, user = prompt_rewrite_steps(
        a_v2_steps(), [3], "PR #42 將 Meeting Summary 改名為 Prepare", "R-007：按鈕要寫出位置"
    )

    assert "rewrites" in system
    assert "只改寫指定編號的步驟" in system
    assert "第 3 步" in user
    assert "R-007" in user
    assert "在會議頁面右上角選擇 Meeting Summary，查看會前摘要。" in user


def test_prompt_把需要改寫的步驟標出來():
    _system, user = prompt_rewrite_steps(a_v2_steps(), [3], "證據", "")
    marked = [line for line in user.splitlines() if line.endswith("<- 需要改寫")]
    assert len(marked) == 1
    assert marked[0].startswith("3. ")


def test_prompt_沒有規則時不放規則區塊():
    _system, user = prompt_rewrite_steps(a_v2_steps(), [3], "證據", "")
    assert "適用的寫作規則" not in user


def test_prompt_多個命中編號都會列出():
    _system, user = prompt_rewrite_steps(a_v2_steps(), [3, 4], "證據", "")
    assert "第 3 步、第 4 步" in user
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：`uv run pytest tests/unit/test_prompt_rewrite_steps.py -v`

預期：FAIL，`ImportError: cannot import name 'prompt_rewrite_steps' from 'training_kb.writing.prompts'`（Phase 05 只建了檔案與其他 prompt，這一個留給本階段）。

- [ ] **步驟 3：寫最少的程式讓測試通過**

在 `src/training_kb/writing/prompts.py` 加上：

```python
def prompt_rewrite_steps(steps, target_indexes, evidence, rules_block) -> tuple[str, str]:
    """UPDATE 與 REFINE 共用的改寫 prompt（設計 §7.6）。

    steps 是該版全部步驟，target_indexes 是這次要改的編號集合。
    其餘步驟不由模型處理，改由程式逐字複製，所以 prompt 也明說不要動它們。
    """
    targets = sorted(int(i) for i in target_indexes)
    system = (
        "你是技術文件維護者。使用者會給你一篇教學的全部步驟，以及需要改寫的步驟編號。\n"
        "只改寫指定編號的步驟；其他步驟一個字都不要動，也不要出現在輸出裡。\n"
        "每個步驟恰好對應一個既有功能，feature_id 必須沿用原步驟的值。\n"
        "type 只能是 click_ui、input 或 read。\n"
        "只輸出 JSON，格式為 "
        '{"rewrites": [{"index": 整數, "text": "字串", "type": "click_ui|input|read", '
        '"feature_id": "字串"}]}。\n'
        "rewrites 的 index 必須剛好等於指定的編號集合，不多也不少。\n"
        "不要輸出 JSON 以外的任何文字。"
    )
    lines = [
        f"需要改寫的步驟編號：{'、'.join(f'第 {i} 步' for i in targets)}",
        "",
        "改版或回饋證據：",
        evidence,
    ]
    if rules_block.strip():
        lines += ["", "適用的寫作規則（必須遵守）：", rules_block.strip()]
    lines += ["", "目前的步驟："]
    for step in sorted(steps, key=lambda s: s.index):
        mark = " <- 需要改寫" if step.index in targets else ""
        lines.append(f"{step.index}. [type={step.type}｜feature_id={step.feature_id}] {step.text}{mark}")
    return system, "\n".join(lines)
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：`uv run pytest tests/unit/test_prompt_rewrite_steps.py -v`

預期：PASS，7 個測試綠色。

- [ ] **步驟 5：commit**

```bash
git add tests/unit/test_prompt_rewrite_steps.py src/training_kb/writing/prompts.py
git commit -m "feat(writing): 加入改寫步驟的 prompt"
```

---

### Task 6：`task_rewrite`——只改命中步驟，其餘逐字複製

**目的**：每篇命中的教學取鎖、配版號、注入 active 規則、請模型只改命中步驟，再由程式逐字核對其餘步驟沒被動過。

**檔案**：
- 修改：`src/training_kb/pipelines/release.py`
- 測試：`tests/unit/test_release_rewrite.py`

**介面**：
- 消費：`content.with_tutorial_lock(repo, slug, owner, now, fn)`、`content.allocate_version(repo, slug, operation_id, reason, rules_applied) -> VersionPlan`、`content.parse_markdown(markdown) -> TutorialContent`、`content.validate_content(content, known_feature_ids)`、`content.create_version(repo, plan, content, *, now) -> TutorialVersion`（Phase 07、08）、`writing.rules.rules_for_content(rules, step_types) -> tuple[str, list[str]]`（Phase 06）、`writing.prompts.prompt_rewrite_steps`（Task 5）、`writing.schemas.StepRewrite`（Phase 05）、`models.RuleStatus`
- 產出：
  - `pipelines.release.apply_rewrites(base_content, steps, rewrite, target_indexes, known_feature_ids) -> TutorialContent`
  - `pipelines.release.rewrite_one(deps, release, slug, target_indexes, operation_id, active_rules) -> str`
  - `pipelines.release.task_rewrite(state, deps) -> dict`
  - state 新增鍵：`new_version_ids: list[str]`

**執行順序**（注意：`allocate_version` 需要 `rules_applied`，所以規則要先算）：

```text
  取 LOCK#<slug>
      |
  rules_for_content(active 規則, 命中步驟的 type) -> (rules_block, rule_ids)
      |
  allocate_version(reason="release:<id>", rules_applied=rule_ids) -> VersionPlan
      |
  讀 S3 前一版全文 -> parse_markdown -> 與 DynamoDB 的 STEP item 逐字核對
      |
  prompt_rewrite_steps -> StepRewrite
      |
  apply_rewrites：index 集合必須剛好相符；feature_id 必須存在；
                  未命中步驟逐字比對
      |
  validate_content -> create_version
      |
  放開 LOCK#<slug>
```

- [ ] **步驟 1：寫測試**

```python
# tests/unit/test_release_rewrite.py
"""task_rewrite：只改命中步驟、其餘逐字相同、reason 與規則注入。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path("tests/unit").resolve()))

from release_fakes import NOW, StubWriter, a_v2_steps, make_repo, make_settings  # noqa: E402

from training_kb.errors import PermanentError  # noqa: E402
from training_kb.models import AuthoringRule, RuleStatus, StepType  # noqa: E402
from training_kb.pipelines import release as release_pipeline  # noqa: E402
from training_kb.pipelines.common import Deps  # noqa: E402
from training_kb.pipelines.release import apply_rewrites, task_rewrite  # noqa: E402
from training_kb.writing.client import CallTrace  # noqa: E402
from training_kb.writing.schemas import StepRewrite, StepRewriteItem  # noqa: E402

NEW_TEXT = "在會議頁面右上角選擇 Prepare，查看會前摘要。"
HIT_3 = {"slug": "prepare-meeting", "version_id": "prepare-meeting@v2", "index": 3}
STATE = {
    "release_id": "r_42",
    "operation_id": "ingest:release:r_42",
    "feature_id": "Prepare",
    "alias_hit": True,
    "action": "UPDATE",
    "hits": [HIT_3],
}


def make_deps(repo, writer) -> Deps:
    return Deps(repo=repo, writer=writer, settings=make_settings(), trace=CallTrace(), now=lambda: NOW)


@pytest.fixture
def content_spy(monkeypatch):
    """把 content 的四個函式換成記錄器；它們本身由 Phase 07／08 的測試負責。"""
    calls: dict[str, list] = {"allocate": [], "validate": [], "create": [], "lock": []}

    class Plan:
        slug = "prepare-meeting"
        version_id = "prepare-meeting@v3"
        n = 3
        supersedes = "prepare-meeting@v2"
        reason = ""
        rules_applied: list[str] = []
        operation_id = ""

    def fake_lock(repo, slug, owner, now, fn):
        calls["lock"].append((slug, owner))
        return fn()

    def fake_allocate(repo, slug, operation_id, reason, rules_applied):
        calls["allocate"].append(
            {"slug": slug, "operation_id": operation_id, "reason": reason, "rules_applied": list(rules_applied)}
        )
        plan = Plan()
        plan.reason = reason
        plan.rules_applied = list(rules_applied)
        plan.operation_id = operation_id
        return plan

    def fake_validate(content_obj, known_feature_ids):
        calls["validate"].append((content_obj, set(known_feature_ids)))

    class Version:
        version_id = "prepare-meeting@v3"

    def fake_create(repo, plan, content_obj, *, now):
        calls["create"].append({"plan": plan, "content": content_obj})
        return Version()

    monkeypatch.setattr(release_pipeline.content, "with_tutorial_lock", fake_lock)
    monkeypatch.setattr(release_pipeline.content, "allocate_version", fake_allocate)
    monkeypatch.setattr(release_pipeline.content, "validate_content", fake_validate)
    monkeypatch.setattr(release_pipeline.content, "create_version", fake_create)
    return calls


def rewrite_output(index: int = 3, text: str = NEW_TEXT, feature_id: str = "Prepare") -> StepRewrite:
    return StepRewrite(
        rewrites=[StepRewriteItem(index=index, text=text, type=StepType.click_ui, feature_id=feature_id)]
    )


def test_只有第三步被改寫其餘逐字相同(content_spy):
    repo = make_repo()
    writer = StubWriter(outputs=[rewrite_output()])

    state = task_rewrite(STATE, make_deps(repo, writer))

    assert state["new_version_ids"] == ["prepare-meeting@v3"]
    new_content = content_spy["create"][0]["content"]
    texts = [s.text for s in new_content.steps]
    original = [s.text for s in a_v2_steps()]
    assert texts[0] == original[0]
    assert texts[1] == original[1]
    assert texts[2] == NEW_TEXT
    assert texts[3] == original[3]


def test_四段散文沿用前一版(content_spy):
    repo = make_repo()
    writer = StubWriter(outputs=[rewrite_output()])

    task_rewrite(STATE, make_deps(repo, writer))

    new_content = content_spy["create"][0]["content"]
    assert new_content.title == "準備會議前的摘要"
    assert new_content.prerequisites == ["已登入", "已建立會議"]
    assert new_content.expected_outcome == "你可以在會議頁面看到會前摘要。"


def test_reason_是_release_加事件_id(content_spy):
    repo = make_repo()
    writer = StubWriter(outputs=[rewrite_output()])

    task_rewrite(STATE, make_deps(repo, writer))

    assert content_spy["allocate"][0]["reason"] == "release:r_42"


def test_改寫前注入適用的_active_規則(content_spy):
    repo = make_repo()
    repo.rules = [
        AuthoringRule(rule_id="R-007", rule="按鈕要寫出所在頁面與位置",
                      applies_when={"step.type": "click_ui"}, evidence=["f_12"],
                      status=RuleStatus.active, applied_to=[], derived_from="prepare-meeting@v1",
                      validated_at="2026-08-25T00:00:00Z"),
        AuthoringRule(rule_id="R-099", rule="不該被選到的候選規則",
                      applies_when={"step.type": "click_ui"}, evidence=["f_99"],
                      status=RuleStatus.candidate, applied_to=[], derived_from="prepare-meeting@v1",
                      validated_at=None),
    ]
    writer = StubWriter(outputs=[rewrite_output()])

    task_rewrite(STATE, make_deps(repo, writer))

    assert content_spy["allocate"][0]["rules_applied"] == ["R-007"]
    assert "R-007" in writer.json_calls[0]["user"]
    assert "R-099" not in writer.json_calls[0]["user"]


def test_取得該篇教學的鎖(content_spy):
    repo = make_repo()
    writer = StubWriter(outputs=[rewrite_output()])

    task_rewrite(STATE, make_deps(repo, writer))

    assert content_spy["lock"][0][0] == "prepare-meeting"


def test_模型多改了一個步驟就是永久錯誤(content_spy):
    repo = make_repo()
    writer = StubWriter(
        outputs=[
            StepRewrite(rewrites=[
                StepRewriteItem(index=3, text=NEW_TEXT, type=StepType.click_ui, feature_id="Prepare"),
                StepRewriteItem(index=1, text="偷改的第一步", type=StepType.click_ui, feature_id="Calendar"),
            ])
        ]
    )

    with pytest.raises(PermanentError) as err:
        task_rewrite(STATE, make_deps(repo, writer))
    assert "不一致" in str(err.value)


def test_模型少改了就是永久錯誤(content_spy):
    repo = make_repo()
    writer = StubWriter(outputs=[StepRewrite(rewrites=[])])

    with pytest.raises(PermanentError):
        task_rewrite(STATE, make_deps(repo, writer))


def test_命中步驟的_feature_不存在就是永久錯誤(content_spy):
    repo = make_repo()
    writer = StubWriter(outputs=[rewrite_output(feature_id="NotExist")])

    with pytest.raises(PermanentError) as err:
        task_rewrite(STATE, make_deps(repo, writer))
    assert "feature" in str(err.value).lower() or "Feature" in str(err.value)


def test_改寫後的文字不可為空(content_spy):
    repo = make_repo()
    writer = StubWriter(outputs=[rewrite_output(text="   ")])

    with pytest.raises(PermanentError):
        task_rewrite(STATE, make_deps(repo, writer))


def test_action_不是_update_時什麼都不做(content_spy):
    repo = make_repo()
    writer = StubWriter()

    state = task_rewrite({**STATE, "action": "KEEP", "hits": []}, make_deps(repo, writer))

    assert state["new_version_ids"] == []
    assert content_spy["create"] == []


def test_apply_rewrites_直接驗證未命中步驟逐字相同():
    from training_kb import content as content_module

    steps = a_v2_steps()
    base = content_module.parse_markdown(make_repo().objects["tutorials/prepare-meeting/v2.md"])

    result = apply_rewrites(base, steps, rewrite_output(), {3}, {"Prepare", "Calendar", "Notification Settings"})

    assert [s.text for s in result.steps][:2] == [s.text for s in base.steps][:2]
    assert result.steps[2].text == NEW_TEXT
    assert result.steps[3].text == base.steps[3].text
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：`uv run pytest tests/unit/test_release_rewrite.py -v`

預期：FAIL，`ImportError: cannot import name 'apply_rewrites'`。

- [ ] **步驟 3：寫最少的程式讓測試通過**

```python
from training_kb import content
from training_kb.models import RuleStatus, StepDraft, TutorialContent
from training_kb.writing.prompts import prompt_rewrite_steps
from training_kb.writing.rules import rules_for_content
from training_kb.writing.schemas import StepRewrite

NODE_REWRITE = "release:rewrite"


def apply_rewrites(
    base_content: TutorialContent,
    steps: list[TutorialStep],
    rewrite: StepRewrite,
    target_indexes: set[int],
    known_feature_ids: set[str],
) -> TutorialContent:
    """把模型的改寫套進去，並由程式核對三件事。

    1. 回傳的 index 集合剛好等於命中集合（不多也不少）。
    2. 每個改寫步驟的 feature_id 存在，且恰好一個（D05）。
    3. 未命中步驟的文字與前一版逐字相同（依改版更新教學 Rule 11）。
    """
    by_index = {int(item.index): item for item in rewrite.rewrites}
    if set(by_index) != set(target_indexes):
        raise PermanentError(
            f"模型回傳的步驟編號 {sorted(by_index)} 與命中集合 {sorted(target_indexes)} 不一致"
        )

    ordered = sorted(steps, key=lambda s: s.index)
    drafts: list[StepDraft] = []
    for position, step in enumerate(ordered):
        item = by_index.get(step.index)
        if item is None:
            drafts.append(StepDraft(type=step.type, text=step.text, feature_id=step.feature_id))
            if drafts[position].text != base_content.steps[position].text:
                raise PermanentError(f"未命中的第 {step.index} 步文字與前一版不一致")
            continue
        text = (item.text or "").strip()
        if not text:
            raise PermanentError(f"第 {step.index} 步改寫後的文字為空")
        if item.feature_id not in known_feature_ids:
            raise PermanentError(f"第 {step.index} 步引用了不存在的 Feature：{item.feature_id}")
        drafts.append(StepDraft(type=item.type, text=text, feature_id=item.feature_id))
    return base_content.model_copy(update={"steps": drafts})


def rewrite_one(
    deps: Deps,
    release: Release,
    slug: str,
    target_indexes: list[int],
    operation_id: str,
    active_rules: list,
) -> str:
    tutorial = deps.repo.get_tutorial(slug)
    if tutorial is None or not tutorial.current_version:
        raise PermanentError(f"教學 {slug} 沒有目前版本，無法改寫")
    base_version = deps.repo.get_version(tutorial.current_version)
    if base_version is None:
        raise PermanentError(f"找不到版本 {tutorial.current_version}")
    steps = deps.repo.get_steps(tutorial.current_version)
    targets = {int(i) for i in target_indexes}
    if not targets.issubset({step.index for step in steps}):
        raise PermanentError(f"命中集合 {sorted(targets)} 超出 {tutorial.current_version} 的步驟範圍")

    # 規則要先算出來，allocate_version 才能把 rules_applied 寫進版本計畫。
    target_types = [step.type for step in steps if step.index in targets]
    rules_block, rule_ids = rules_for_content(active_rules, target_types)
    plan = content.allocate_version(
        deps.repo, slug, f"{operation_id}:{slug}", f"release:{release.id}", rule_ids
    )

    raw = deps.repo.get_object(base_version.s3_key)
    if raw is None:
        raise PermanentError(f"S3 找不到前一版全文：{base_version.s3_key}")
    base_content = content.parse_markdown(raw.decode("utf-8"))
    if [draft.text for draft in base_content.steps] != [step.text for step in steps]:
        raise PermanentError(
            f"{tutorial.current_version} 的 S3 全文與 STEP item 不一致，無法安全改寫"
        )

    system, user = prompt_rewrite_steps(steps, sorted(targets), release.evidence, rules_block)
    rewrite: StepRewrite = deps.writer.generate_json(
        system=system,
        user=user,
        schema=StepRewrite,
        operation_id=operation_id,
        node=NODE_REWRITE,
        max_tokens=deps.settings.gen_max_tokens_writing,
        temperature=deps.settings.gen_temperature,
    )

    known_feature_ids = {feature.feature_id for feature in deps.repo.list_features()}
    new_content = apply_rewrites(base_content, steps, rewrite, targets, known_feature_ids)
    content.validate_content(new_content, known_feature_ids)
    version = content.create_version(deps.repo, plan, new_content, now=deps.now())
    return version.version_id


def task_rewrite(state: dict, deps: Deps) -> dict:
    hits = state.get("hits", [])
    if state.get("action") != "UPDATE" or not hits:
        return {**state, "new_version_ids": []}

    release = load_release(state, deps)
    operation_id = state["operation_id"]
    by_slug: dict[str, set[int]] = {}
    for hit in hits:
        by_slug.setdefault(hit["slug"], set()).add(int(hit["index"]))

    active_rules = deps.repo.list_rules(RuleStatus.active)
    new_version_ids: list[str] = []
    for slug in sorted(by_slug):
        targets = sorted(by_slug[slug])

        def build(slug: str = slug, targets: list[int] = targets) -> str:
            return rewrite_one(deps, release, slug, targets, operation_id, active_rules)

        # 同篇教學的寫入要串行（設計 §8.3、F35）。
        new_version_ids.append(
            content.with_tutorial_lock(deps.repo, slug, operation_id, deps.now(), build)
        )
    return {**state, "new_version_ids": new_version_ids}


TASKS["rewrite"] = task_rewrite
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：`uv run pytest tests/unit/test_release_rewrite.py -v`

預期：PASS，11 個測試綠色。

- [ ] **步驟 5：commit**

```bash
git add tests/unit/test_release_rewrite.py src/training_kb/pipelines/release.py
git commit -m "feat(pipelines): Release 流程只改寫命中步驟"
```

---

### Task 7：`task_publish` 與 `task_retire`

**目的**：把新版本整批發布（全有或全無），以及 `removed` 時把教學退役。

**檔案**：
- 修改：`src/training_kb/pipelines/release.py`
- 測試：`tests/unit/test_release_publish_retire.py`

**介面**：
- 消費：`content.publish(repo, version_ids, renderer, *, now) -> PublishResult`、`content.retire(repo, slug, *, reason, successor, now) -> Tutorial`（Phase 08）、`site.SiteRenderer`（Phase 08）
- 產出：
  - `pipelines.release.task_publish(state, deps) -> dict`；state 新增鍵 `published: bool`、`published_version_ids: list[str]`
  - `pipelines.release.task_retire(state, deps) -> dict`；state 新增鍵 `retired_slugs: list[str]`
  - 讀取 state 的 `successor_by_slug: dict[str, str]`（維護者輸入；沒給就是 `None`）

- [ ] **步驟 1：寫測試**

```python
# tests/unit/test_release_publish_retire.py
"""task_publish 與 task_retire：整批全有或全無、退役與後繼。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path("tests/unit").resolve()))

from release_fakes import NOW, StubWriter, make_repo, make_settings  # noqa: E402

from training_kb.errors import PermanentError  # noqa: E402
from training_kb.models import ReleaseKind  # noqa: E402
from training_kb.pipelines import release as release_pipeline  # noqa: E402
from training_kb.pipelines.common import Deps  # noqa: E402
from training_kb.pipelines.release import task_publish, task_retire  # noqa: E402
from training_kb.writing.client import CallTrace  # noqa: E402

HIT_3 = {"slug": "prepare-meeting", "version_id": "prepare-meeting@v2", "index": 3}


def make_deps(repo) -> Deps:
    return Deps(repo=repo, writer=StubWriter(), settings=make_settings(), trace=CallTrace(),
                now=lambda: NOW)


class Result:
    def __init__(self, published, failed=None):
        self.published = published
        self.failed = failed


def test_發布成功時記錄版本(monkeypatch):
    repo = make_repo()
    monkeypatch.setattr(
        release_pipeline.content, "publish",
        lambda repo_, ids, renderer, *, now: Result(list(ids)),
    )

    state = task_publish(
        {"release_id": "r_42", "operation_id": "op", "action": "UPDATE",
         "new_version_ids": ["prepare-meeting@v3"]},
        make_deps(repo),
    )

    assert state["published"] is True
    assert state["published_version_ids"] == ["prepare-meeting@v3"]


def test_整批中有一篇失敗就是永久錯誤(monkeypatch):
    repo = make_repo()
    monkeypatch.setattr(
        release_pipeline.content, "publish",
        lambda repo_, ids, renderer, *, now: Result([], failed="share-summary@v2"),
    )

    with pytest.raises(PermanentError) as err:
        task_publish(
            {"release_id": "r_42", "operation_id": "op", "action": "UPDATE",
             "new_version_ids": ["prepare-meeting@v3", "share-summary@v2"]},
            make_deps(repo),
        )
    assert "share-summary@v2" in str(err.value)


def test_多篇一起送給_publish_只呼叫一次(monkeypatch):
    repo = make_repo()
    calls: list[list[str]] = []
    monkeypatch.setattr(
        release_pipeline.content, "publish",
        lambda repo_, ids, renderer, *, now: (calls.append(list(ids)), Result(list(ids)))[1],
    )

    task_publish(
        {"release_id": "r_42", "operation_id": "op", "action": "UPDATE",
         "new_version_ids": ["a@v2", "b@v2"]},
        make_deps(repo),
    )

    assert calls == [["a@v2", "b@v2"]]


def test_沒有新版本時不呼叫_publish(monkeypatch):
    repo = make_repo()
    monkeypatch.setattr(
        release_pipeline.content, "publish",
        lambda *a, **k: pytest.fail("KEEP 不應該呼叫 publish"),
    )

    state = task_publish(
        {"release_id": "r_42", "operation_id": "op", "action": "KEEP", "new_version_ids": []},
        make_deps(repo),
    )
    assert state["published"] is False


def test_removed_把命中的教學退役(monkeypatch):
    repo = make_repo()
    repo.releases["r_42"] = repo.releases["r_42"].model_copy(update={"kind": ReleaseKind.removed})
    calls: list[dict] = []
    monkeypatch.setattr(
        release_pipeline.content, "retire",
        lambda repo_, slug, *, reason, successor, now: calls.append(
            {"slug": slug, "reason": reason, "successor": successor}
        ),
    )

    state = task_retire(
        {"release_id": "r_42", "operation_id": "op", "action": "RETIRE", "hits": [HIT_3]},
        make_deps(repo),
    )

    assert state["retired_slugs"] == ["prepare-meeting"]
    assert calls[0]["reason"] == "release:r_42"
    assert calls[0]["successor"] is None


def test_維護者有指定後繼時傳進去(monkeypatch):
    repo = make_repo()
    repo.releases["r_42"] = repo.releases["r_42"].model_copy(update={"kind": ReleaseKind.removed})
    calls: list[dict] = []
    monkeypatch.setattr(
        release_pipeline.content, "retire",
        lambda repo_, slug, *, reason, successor, now: calls.append({"successor": successor}),
    )

    task_retire(
        {"release_id": "r_42", "operation_id": "op", "action": "RETIRE", "hits": [HIT_3],
         "successor_by_slug": {"prepare-meeting": "share-summary"}},
        make_deps(repo),
    )

    assert calls[0]["successor"] == "share-summary"


def test_removed_沒有命中時仍然完成不當失敗(monkeypatch):
    repo = make_repo()
    repo.releases["r_42"] = repo.releases["r_42"].model_copy(update={"kind": ReleaseKind.removed})
    monkeypatch.setattr(
        release_pipeline.content, "retire",
        lambda *a, **k: pytest.fail("沒有命中時不該退役任何教學"),
    )

    state = task_retire(
        {"release_id": "r_42", "operation_id": "op", "action": "RETIRE", "hits": []},
        make_deps(repo),
    )

    assert state["retired_slugs"] == []
    assert "沒有教學需要退役" in state["keep_reason"]


def test_action_不是_retire_時什麼都不做(monkeypatch):
    repo = make_repo()
    monkeypatch.setattr(
        release_pipeline.content, "retire", lambda *a, **k: pytest.fail("不該退役")
    )

    state = task_retire(
        {"release_id": "r_42", "operation_id": "op", "action": "UPDATE", "hits": [HIT_3]},
        make_deps(repo),
    )
    assert state["retired_slugs"] == []
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：`uv run pytest tests/unit/test_release_publish_retire.py -v`

預期：FAIL，`ImportError: cannot import name 'task_publish'`。

- [ ] **步驟 3：寫最少的程式讓測試通過**

```python
from training_kb.site import SiteRenderer


def task_publish(state: dict, deps: Deps) -> dict:
    """整批發布新版本；任一篇失敗就整次失敗，不部分發布（F49、設計 §8.3）。"""
    new_version_ids = list(state.get("new_version_ids", []))
    if state.get("action") != "UPDATE" or not new_version_ids:
        return {**state, "published": False, "published_version_ids": []}

    result = content.publish(deps.repo, new_version_ids, SiteRenderer(), now=deps.now())
    if getattr(result, "failed", None):
        raise PermanentError(
            f"整批發布失敗於 {result.failed}；本次不發布任何新版本，current_version 維持原值"
        )
    return {**state, "published": True, "published_version_ids": list(result.published)}


def task_retire(state: dict, deps: Deps) -> dict:
    """kind 為 removed 時把受影響教學標成 retired（設計 §8.4）。"""
    if state.get("action") != "RETIRE":
        return {**state, "retired_slugs": []}

    release = load_release(state, deps)
    slugs = sorted({hit["slug"] for hit in state.get("hits", [])})
    if not slugs:
        return {
            **state,
            "retired_slugs": [],
            "keep_reason": "removed 未命中任何目前已發布步驟，沒有教學需要退役",
        }

    successors = state.get("successor_by_slug") or {}
    retired: list[str] = []
    for slug in slugs:
        # F19、F54：後繼由維護者選定；沒給就是 None，仍完成退役。
        content.retire(
            deps.repo,
            slug,
            reason=f"release:{release.id}",
            successor=successors.get(slug),
            now=deps.now(),
        )
        retired.append(slug)
    return {**state, "retired_slugs": retired}


TASKS["publish"] = task_publish
TASKS["retire"] = task_retire
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：`uv run pytest tests/unit/test_release_publish_retire.py -v`

預期：PASS，8 個測試綠色。

- [ ] **步驟 5：commit**

```bash
git add tests/unit/test_release_publish_retire.py src/training_kb/pipelines/release.py
git commit -m "feat(pipelines): Release 流程整批發布與退役"
```

---

### Task 8：`task_update_aliases`——改名後更新 aliases，撞名就失敗

**目的**：`renamed` 發布完成後，把舊名字加進 `aliases`、`name` 改成新名字；如果新舊名字已經被別的 Feature 佔用，拒絕這次更新並以失敗結束。

**檔案**：
- 修改：`src/training_kb/pipelines/release.py`
- 測試：`tests/unit/test_release_aliases.py`

**介面**：
- 消費：`repository.Repository.get_feature(feature_id)`、`list_features()`、`update_meta(pk, attrs, *, condition_equals=None)`、`keys.feature_pk(feature_id)`
- 產出：
  - `pipelines.release.alias_conflicts(features, feature_id: str, names: list[str]) -> list[str]`
  - `pipelines.release.task_update_aliases(state, deps) -> dict`
  - state 新增鍵：`aliases_updated: bool`、`feature_name: str`、`feature_aliases: list[str]`

> **為什麼撞名是失敗而不是 KEEP。** D07 說「alias 必須唯一；新增或改名造成衝突時拒絕該次 alias 更新」，設計 §7.4 的失敗列又寫「alias 撞名、模型輸出違規或寫入失敗，依第 14 節結束；**不把技術故障當 KEEP**」。所以這裡拋 `PermanentError`，讓 ASL 的 Catch 把整條流程導到 `PipelineFailed`。

- [ ] **步驟 1：寫測試**

```python
# tests/unit/test_release_aliases.py
"""task_update_aliases：加舊名進 aliases、改 name、撞名失敗、PK 不變。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path("tests/unit").resolve()))

from release_fakes import NOW, StubWriter, make_repo, make_settings  # noqa: E402

from training_kb.errors import PermanentError  # noqa: E402
from training_kb.keys import feature_pk  # noqa: E402
from training_kb.models import Feature, ReleaseKind  # noqa: E402
from training_kb.pipelines.common import Deps  # noqa: E402
from training_kb.pipelines.release import alias_conflicts, task_update_aliases  # noqa: E402
from training_kb.writing.client import CallTrace  # noqa: E402

STATE = {
    "release_id": "r_42",
    "operation_id": "ingest:release:r_42",
    "feature_id": "Prepare",
    "action": "UPDATE",
    "published": True,
}


def make_deps(repo) -> Deps:
    return Deps(repo=repo, writer=StubWriter(), settings=make_settings(), trace=CallTrace(),
                now=lambda: NOW)


def test_舊名字被加進_aliases_而_name_換成新名字():
    repo = make_repo()

    state = task_update_aliases(STATE, make_deps(repo))

    pk, attrs = repo.updates[0]
    assert pk == feature_pk("Prepare")
    assert attrs["name"] == "Prepare"
    assert attrs["aliases"] == ["Meeting Summary"]
    assert state["aliases_updated"] is True


def test_主鍵不因改名而改變():
    repo = make_repo()

    task_update_aliases(STATE, make_deps(repo))

    assert repo.updates[0][0] == "FEATURE#Prepare"
    assert "Prepare" in repo.features        # 還是原本那一筆，沒有搬移


def test_重複執行不會把舊名字加兩次():
    repo = make_repo()
    repo.features["Prepare"] = repo.features["Prepare"].model_copy(
        update={"name": "Prepare", "aliases": ["Meeting Summary"]}
    )

    task_update_aliases(STATE, make_deps(repo))

    assert repo.updates[0][1]["aliases"] == ["Meeting Summary"]


def test_新名字撞到別的_feature_的_name_就失敗():
    repo = make_repo()
    repo.features["Other"] = Feature(
        feature_id="Other", name="Prepare", aliases=[], first_seen="2026-07-01T00:00:00Z"
    )

    with pytest.raises(PermanentError) as err:
        task_update_aliases(STATE, make_deps(repo))
    assert "撞名" in str(err.value)
    assert repo.updates == []


def test_舊名字撞到別的_feature_的_alias_就失敗():
    repo = make_repo()
    repo.features["Other"] = Feature(
        feature_id="Other", name="Other", aliases=["Meeting Summary"],
        first_seen="2026-07-01T00:00:00Z",
    )

    with pytest.raises(PermanentError):
        task_update_aliases(STATE, make_deps(repo))


def test_撞名不會被當成_keep():
    repo = make_repo()
    repo.features["Other"] = Feature(
        feature_id="Other", name="Prepare", aliases=[], first_seen="2026-07-01T00:00:00Z"
    )

    with pytest.raises(PermanentError):
        task_update_aliases(STATE, make_deps(repo))
    # 沒有任何路徑會把 action 改成 KEEP。


def test_changed_不更新_aliases():
    repo = make_repo()
    repo.releases["r_42"] = repo.releases["r_42"].model_copy(
        update={"kind": ReleaseKind.changed, "old_name": None, "new_name": None}
    )

    state = task_update_aliases(STATE, make_deps(repo))

    assert state["aliases_updated"] is False
    assert repo.updates == []


def test_removed_不更新_aliases():
    repo = make_repo()
    repo.releases["r_42"] = repo.releases["r_42"].model_copy(update={"kind": ReleaseKind.removed})

    state = task_update_aliases({**STATE, "action": "RETIRE"}, make_deps(repo))

    assert state["aliases_updated"] is False


def test_renamed_缺_new_name_是永久錯誤():
    repo = make_repo()
    repo.releases["r_42"] = repo.releases["r_42"].model_copy(update={"new_name": None})

    with pytest.raises(PermanentError):
        task_update_aliases(STATE, make_deps(repo))


def test_alias_conflicts_只看別的_feature():
    features = [
        Feature(feature_id="Prepare", name="Prepare", aliases=["Meeting Summary"],
                first_seen="2026-07-01T00:00:00Z"),
        Feature(feature_id="Other", name="Other", aliases=[], first_seen="2026-07-01T00:00:00Z"),
    ]
    assert alias_conflicts(features, "Prepare", ["Prepare", "Meeting Summary"]) == []
    assert alias_conflicts(features, "Other", ["Prepare"]) != []
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：`uv run pytest tests/unit/test_release_aliases.py -v`

預期：FAIL，`ImportError: cannot import name 'alias_conflicts'`。

- [ ] **步驟 3：寫最少的程式讓測試通過**

```python
from training_kb.keys import feature_pk


def alias_conflicts(features, feature_id: str, names: list[str]) -> list[str]:
    """檢查這些名稱有沒有被「別的」Feature 的 name 或 alias 佔用（D07）。"""
    conflicts: list[str] = []
    for other in features:
        if other.feature_id == feature_id:
            continue
        taken = {other.name, *other.aliases}
        for name in names:
            if name in taken:
                conflicts.append(f"「{name}」已被 FEATURE#{other.feature_id} 使用")
    return conflicts


def task_update_aliases(state: dict, deps: Deps) -> dict:
    """UPDATE 完成時更新 Feature 的 aliases（依改版更新教學 Rule 15、D06、D07）。"""
    release = load_release(state, deps)
    feature_id = state.get("feature_id")
    if release.kind != ReleaseKind.renamed or not feature_id or state.get("action") != "UPDATE":
        return {**state, "aliases_updated": False}

    feature = deps.repo.get_feature(feature_id)
    if feature is None:
        raise PermanentError(f"找不到 Feature：{feature_id}")
    old_name = (release.old_name or "").strip()
    new_name = (release.new_name or "").strip()
    if not old_name or not new_name:
        raise PermanentError("renamed 必須同時提供 old_name 與 new_name")

    conflicts = alias_conflicts(deps.repo.list_features(), feature_id, [old_name, new_name])
    if conflicts:
        # D07：撞名時拒絕該次 alias 更新；設計 §7.4 要求不把它當 KEEP。
        raise PermanentError("alias 撞名，拒絕此次 alias 更新：" + "；".join(conflicts))

    aliases = list(feature.aliases)
    if old_name != new_name and old_name not in aliases:
        aliases.append(old_name)
    # Feature PK 保持第一次建立的值，只改 name 與 aliases（D06）。
    deps.repo.update_meta(feature_pk(feature_id), {"name": new_name, "aliases": aliases})
    return {**state, "aliases_updated": True, "feature_name": new_name, "feature_aliases": aliases}


TASKS["update_aliases"] = task_update_aliases
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：

```bash
uv run pytest tests/unit/test_release_aliases.py -v
uv run python -c "from training_kb.pipelines.release import TASKS; print(sorted(TASKS))"
```

預期：10 個測試綠色；第二行印出 `['decide', 'find_steps', 'locate_feature', 'publish', 'retire', 'rewrite', 'safety_net', 'update_aliases']`。

- [ ] **步驟 5：commit**

```bash
git add tests/unit/test_release_aliases.py src/training_kb/pipelines/release.py
git commit -m "feat(pipelines): Release 流程更新 Feature aliases"
```

---

### Task 9：`infra/asl/release-update.asl.json`

**目的**：把八個 task 串成第二條 Step Functions 流程。

**檔案**：
- 新增：`infra/asl/release-update.asl.json`
- 測試：`tests/unit/test_asl_release.py`

**介面**：
- 消費：`handlers.pipeline_task.handler`（`pipeline` 固定為 `"release"`）
- 產出：`infra/asl/release-update.asl.json`（Task 10 用 `DefinitionBody.from_file` 讀它；`infra/scripts/snapshot_asl.py` 會自動連它一起快照）

```text
       LocateFeature
             |
        HasFeature?  --- $.feature_id 是 null ---> NoFeature (Succeed)
             |
         FindSteps
             |
         SafetyNet
             |
          Decide
             |
      ChooseAction?
        |    |    |
    UPDATE RETIRE KEEP
        |    |      \
     Rewrite Retire  Kept (Succeed)
        |      |
     Publish  Retired (Succeed)
        |
   UpdateAliases
        |
      Done (Succeed)

任一 Task：TransientError -> Retry(1 秒、2 次、倍率 2)
           其他或重試用完 -> Catch(States.ALL) -> PipelineFailed (Fail)
```

- [ ] **步驟 1：寫測試**

```python
# tests/unit/test_asl_release.py
"""release-update 的 ASL：節點、分支、Retry／Catch。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ASL_PATH = Path("infra/asl/release-update.asl.json")
EXPECTED_TASKS = {
    "LocateFeature", "FindSteps", "SafetyNet", "Decide",
    "Rewrite", "Publish", "Retire", "UpdateAliases",
}


@pytest.fixture(scope="module")
def asl() -> dict:
    return json.loads(ASL_PATH.read_text(encoding="utf-8"))


def test_起點是_locate_feature(asl):
    assert asl["StartAt"] == "LocateFeature"


def test_八個_task_節點齊全且對得上_tasks(asl):
    from training_kb.pipelines.release import TASKS

    tasks = {n for n, s in asl["States"].items() if s["Type"] == "Task"}
    assert tasks == EXPECTED_TASKS
    names = {asl["States"][n]["Parameters"]["Payload"]["task"] for n in EXPECTED_TASKS}
    assert names == set(TASKS)


def test_pipeline_名稱是_release(asl):
    for name in EXPECTED_TASKS:
        assert asl["States"][name]["Parameters"]["Payload"]["pipeline"] == "release"
        assert asl["States"][name]["Parameters"]["Payload"]["state.$"] == "$"
        assert asl["States"][name]["OutputPath"] == "$.Payload"


def test_每個_task_都有_retry_與_catch(asl):
    for name in EXPECTED_TASKS:
        state = asl["States"][name]
        assert state["Retry"][0] == {
            "ErrorEquals": ["TransientError"],
            "IntervalSeconds": 1,
            "MaxAttempts": 2,
            "BackoffRate": 2,
        }, name
        assert state["Catch"] == [{"ErrorEquals": ["States.ALL"], "Next": "PipelineFailed"}], name
        assert state["TimeoutSeconds"] == 120, name


def test_找不到_feature_就走到_nofeature(asl):
    choice = asl["States"]["HasFeature"]
    assert choice["Type"] == "Choice"
    assert choice["Choices"][0] == {"Variable": "$.feature_id", "IsNull": True, "Next": "NoFeature"}
    assert choice["Default"] == "FindSteps"


def test_三種動作的分支(asl):
    branches = {c["StringEquals"]: c["Next"] for c in asl["States"]["ChooseAction"]["Choices"]}
    assert branches == {"UPDATE": "Rewrite", "RETIRE": "Retire", "KEEP": "Kept"}
    assert asl["States"]["ChooseAction"]["Default"] == "PipelineFailed"


def test_update_的順序是改寫_發布_再更新_aliases(asl):
    states = asl["States"]
    assert states["LocateFeature"]["Next"] == "HasFeature"
    assert states["FindSteps"]["Next"] == "SafetyNet"
    assert states["SafetyNet"]["Next"] == "Decide"
    assert states["Decide"]["Next"] == "ChooseAction"
    assert states["Rewrite"]["Next"] == "Publish"
    assert states["Publish"]["Next"] == "UpdateAliases"
    assert states["UpdateAliases"]["Next"] == "Done"
    assert states["Retire"]["Next"] == "Retired"


def test_失敗終點是_fail_state(asl):
    assert asl["States"]["PipelineFailed"]["Type"] == "Fail"


def test_四個成功終點(asl):
    for name in ("Done", "Retired", "Kept", "NoFeature"):
        assert asl["States"][name]["Type"] == "Succeed", name
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：`uv run pytest tests/unit/test_asl_release.py -v`

預期：FAIL，`FileNotFoundError: ... 'infra/asl/release-update.asl.json'`。

- [ ] **步驟 3：寫最少的程式讓測試通過**

```json
{
  "Comment": "Training KB - Release Note Update（設計 §7.4）。每個 Task 都呼叫 training-kb-pipeline-task。",
  "StartAt": "LocateFeature",
  "States": {
    "LocateFeature": {
      "Type": "Task",
      "Resource": "arn:aws:states:::lambda:invoke",
      "TimeoutSeconds": 120,
      "Parameters": {
        "FunctionName": "${PipelineTaskFunctionArn}",
        "Payload": { "pipeline": "release", "task": "locate_feature", "state.$": "$" }
      },
      "OutputPath": "$.Payload",
      "Retry": [
        { "ErrorEquals": ["TransientError"], "IntervalSeconds": 1, "MaxAttempts": 2, "BackoffRate": 2 }
      ],
      "Catch": [{ "ErrorEquals": ["States.ALL"], "Next": "PipelineFailed" }],
      "Next": "HasFeature"
    },
    "HasFeature": {
      "Type": "Choice",
      "Choices": [{ "Variable": "$.feature_id", "IsNull": true, "Next": "NoFeature" }],
      "Default": "FindSteps"
    },
    "FindSteps": {
      "Type": "Task",
      "Resource": "arn:aws:states:::lambda:invoke",
      "TimeoutSeconds": 120,
      "Parameters": {
        "FunctionName": "${PipelineTaskFunctionArn}",
        "Payload": { "pipeline": "release", "task": "find_steps", "state.$": "$" }
      },
      "OutputPath": "$.Payload",
      "Retry": [
        { "ErrorEquals": ["TransientError"], "IntervalSeconds": 1, "MaxAttempts": 2, "BackoffRate": 2 }
      ],
      "Catch": [{ "ErrorEquals": ["States.ALL"], "Next": "PipelineFailed" }],
      "Next": "SafetyNet"
    },
    "SafetyNet": {
      "Type": "Task",
      "Resource": "arn:aws:states:::lambda:invoke",
      "TimeoutSeconds": 120,
      "Parameters": {
        "FunctionName": "${PipelineTaskFunctionArn}",
        "Payload": { "pipeline": "release", "task": "safety_net", "state.$": "$" }
      },
      "OutputPath": "$.Payload",
      "Retry": [
        { "ErrorEquals": ["TransientError"], "IntervalSeconds": 1, "MaxAttempts": 2, "BackoffRate": 2 }
      ],
      "Catch": [{ "ErrorEquals": ["States.ALL"], "Next": "PipelineFailed" }],
      "Next": "Decide"
    },
    "Decide": {
      "Type": "Task",
      "Resource": "arn:aws:states:::lambda:invoke",
      "TimeoutSeconds": 120,
      "Parameters": {
        "FunctionName": "${PipelineTaskFunctionArn}",
        "Payload": { "pipeline": "release", "task": "decide", "state.$": "$" }
      },
      "OutputPath": "$.Payload",
      "Retry": [
        { "ErrorEquals": ["TransientError"], "IntervalSeconds": 1, "MaxAttempts": 2, "BackoffRate": 2 }
      ],
      "Catch": [{ "ErrorEquals": ["States.ALL"], "Next": "PipelineFailed" }],
      "Next": "ChooseAction"
    },
    "ChooseAction": {
      "Type": "Choice",
      "Choices": [
        { "Variable": "$.action", "StringEquals": "UPDATE", "Next": "Rewrite" },
        { "Variable": "$.action", "StringEquals": "RETIRE", "Next": "Retire" },
        { "Variable": "$.action", "StringEquals": "KEEP", "Next": "Kept" }
      ],
      "Default": "PipelineFailed"
    },
    "Rewrite": {
      "Type": "Task",
      "Resource": "arn:aws:states:::lambda:invoke",
      "TimeoutSeconds": 120,
      "Parameters": {
        "FunctionName": "${PipelineTaskFunctionArn}",
        "Payload": { "pipeline": "release", "task": "rewrite", "state.$": "$" }
      },
      "OutputPath": "$.Payload",
      "Retry": [
        { "ErrorEquals": ["TransientError"], "IntervalSeconds": 1, "MaxAttempts": 2, "BackoffRate": 2 }
      ],
      "Catch": [{ "ErrorEquals": ["States.ALL"], "Next": "PipelineFailed" }],
      "Next": "Publish"
    },
    "Publish": {
      "Type": "Task",
      "Resource": "arn:aws:states:::lambda:invoke",
      "TimeoutSeconds": 120,
      "Parameters": {
        "FunctionName": "${PipelineTaskFunctionArn}",
        "Payload": { "pipeline": "release", "task": "publish", "state.$": "$" }
      },
      "OutputPath": "$.Payload",
      "Retry": [
        { "ErrorEquals": ["TransientError"], "IntervalSeconds": 1, "MaxAttempts": 2, "BackoffRate": 2 }
      ],
      "Catch": [{ "ErrorEquals": ["States.ALL"], "Next": "PipelineFailed" }],
      "Next": "UpdateAliases"
    },
    "UpdateAliases": {
      "Type": "Task",
      "Resource": "arn:aws:states:::lambda:invoke",
      "TimeoutSeconds": 120,
      "Parameters": {
        "FunctionName": "${PipelineTaskFunctionArn}",
        "Payload": { "pipeline": "release", "task": "update_aliases", "state.$": "$" }
      },
      "OutputPath": "$.Payload",
      "Retry": [
        { "ErrorEquals": ["TransientError"], "IntervalSeconds": 1, "MaxAttempts": 2, "BackoffRate": 2 }
      ],
      "Catch": [{ "ErrorEquals": ["States.ALL"], "Next": "PipelineFailed" }],
      "Next": "Done"
    },
    "Retire": {
      "Type": "Task",
      "Resource": "arn:aws:states:::lambda:invoke",
      "TimeoutSeconds": 120,
      "Parameters": {
        "FunctionName": "${PipelineTaskFunctionArn}",
        "Payload": { "pipeline": "release", "task": "retire", "state.$": "$" }
      },
      "OutputPath": "$.Payload",
      "Retry": [
        { "ErrorEquals": ["TransientError"], "IntervalSeconds": 1, "MaxAttempts": 2, "BackoffRate": 2 }
      ],
      "Catch": [{ "ErrorEquals": ["States.ALL"], "Next": "PipelineFailed" }],
      "Next": "Retired"
    },
    "Done": { "Type": "Succeed" },
    "Retired": { "Type": "Succeed" },
    "Kept": { "Type": "Succeed" },
    "NoFeature": { "Type": "Succeed" },
    "PipelineFailed": {
      "Type": "Fail",
      "Error": "PipelineFailed",
      "Cause": "Release Note Update 以失敗結束；不發布新版本（設計 §14.1、F49）"
    }
  }
}
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：`uv run pytest tests/unit/test_asl_release.py -v`

預期：PASS，9 個測試綠色。

- [ ] **步驟 5：commit**

```bash
git add tests/unit/test_asl_release.py infra/asl/release-update.asl.json
git commit -m "feat(infra): 加入 release-update 的 ASL 定義"
```

---

### Task 10：第二條 state machine 上線與端到端驗證 S5

**目的**：把 `training-kb-release-update` 建到 AWS，讓 `handlers/import_.py` 的 release 路徑真的啟動它，並驗證 S5 切片。

**檔案**：
- 修改：`infra/stacks/app_stack.py`
- 測試：`tests/unit/test_app_stack.py`（追加）、`tests/integration/test_release_e2e.py`

**介面**：
- 消費：Task 9 的 ASL 檔、Phase 14 的 `pipeline_task_fn`、`ingress.STATE_MACHINE_ENV`（`release` → `TKB_RELEASE_STATE_MACHINE_ARN`）
- 產出：`training-kb-release-update` state machine 與 `TKB_RELEASE_STATE_MACHINE_ARN` 環境變數

- [ ] **步驟 1：寫測試**

先追加 CDK 樣板測試（加到 `tests/unit/test_app_stack.py` 檔尾）：

```python
# --- Phase 16：第二條 state machine ---------------------------------------

RELEASE_ASL = "infra/asl/release-update.asl.json"


def test_有兩條_state_machine(template: Template):
    template.resource_count_is("AWS::StepFunctions::StateMachine", 2)


def test_release_update_也是_standard(template: Template):
    template.has_resource_properties(
        "AWS::StepFunctions::StateMachine",
        {
            "StateMachineName": "training-kb-release-update",
            "StateMachineType": "STANDARD",
            "DefinitionSubstitutions": Match.object_like(
                {"PipelineTaskFunctionArn": Match.any_value()}
            ),
        },
    )


def test_webhook_與_import_都拿得到兩條流程的_arn(template: Template):
    functions = template.find_resources("AWS::Lambda::Function")
    for name in ("training-kb-webhook", "training-kb-import"):
        matched = [
            res
            for res in functions.values()
            if res["Properties"].get("FunctionName") == name
        ]
        assert matched, name
        variables = matched[0]["Properties"]["Environment"]["Variables"]
        assert "TKB_TICKET_STATE_MACHINE_ARN" in variables
        assert "TKB_RELEASE_STATE_MACHINE_ARN" in variables


def test_pipeline_task_沒有啟動流程的權限(template: Template):
    # 只有入口 Lambda 需要 StartExecution；Task Lambda 不需要。
    functions = template.find_resources("AWS::Lambda::Function")
    task_fn = [
        logical
        for logical, res in functions.items()
        if res["Properties"].get("FunctionName") == "training-kb-pipeline-task"
    ]
    assert task_fn
    assert "TKB_TICKET_STATE_MACHINE_ARN" not in functions[task_fn[0]]["Properties"]["Environment"]["Variables"]
```

再寫端到端驗收：

```python
# tests/integration/test_release_e2e.py
"""端到端驗收 S5：PR #42 只改 A 第 3 步；B、C 不變；removed 呈現退役。"""

from __future__ import annotations

import json
import os
import time

import boto3
import pytest

pytestmark = pytest.mark.aws

RUN = os.environ.get("TKB_RUN_AWS_TESTS") == "1"
skip_unless_aws = pytest.mark.skipif(not RUN, reason="需要 TKB_RUN_AWS_TESTS=1 與真 AWS 資源")

RELEASE_ITEM = {
    "id": "r_42",
    "source": "github_pr",
    "source_event_id": "gh-pr-42",
    "feature": "Meeting Summary",
    "kind": "renamed",
    "old_name": "Meeting Summary",
    "new_name": "Prepare",
    "evidence": "PR #42 將 Meeting Summary 改名為 Prepare",
    "ts": "2026-08-25T00:00:00Z",
}


def invoke_import(payload: dict) -> dict:
    client = boto3.client("lambda")
    response = client.invoke(
        FunctionName="training-kb-import", Payload=json.dumps(payload).encode("utf-8")
    )
    return json.loads(response["Payload"].read())


def wait_for_latest(arn: str, timeout: int = 240) -> dict:
    sfn = boto3.client("stepfunctions")
    deadline = time.time() + timeout
    latest = None
    while time.time() < deadline:
        executions = sfn.list_executions(stateMachineArn=arn, maxResults=1)["executions"]
        assert executions, "state machine 還沒有任何執行紀錄"
        latest = executions[0]
        if latest["status"] != "RUNNING":
            return latest
        time.sleep(5)
    return latest or {}


@skip_unless_aws
def test_s5_release_匯入會啟動_release_update():
    result = invoke_import({"kind": "release", "source": "github_pr", "items": [RELEASE_ITEM]})
    assert result["results"][0]["status"] in {"accepted", "duplicate"}, result
    assert result["results"][0]["execution_arn"], result


@skip_unless_aws
def test_s5_執行成功且只有_a_產生新版():
    latest = wait_for_latest(os.environ["TKB_RELEASE_STATE_MACHINE_ARN"])
    assert latest.get("status") == "SUCCEEDED", latest

    sfn = boto3.client("stepfunctions")
    detail = sfn.describe_execution(executionArn=latest["executionArn"])
    output = json.loads(detail["output"])
    assert output["action"] == "UPDATE"
    assert [h["slug"] for h in output["hits"]] == ["prepare-meeting"]
    assert output["new_version_ids"] == ["prepare-meeting@v3"]
    assert output["published"] is True


@skip_unless_aws
def test_s5_第一二四步逐字相同():
    s3 = boto3.client("s3")
    bucket = os.environ["TKB_BUCKET_NAME"]
    v2 = s3.get_object(Bucket=bucket, Key="tutorials/prepare-meeting/v2.md")["Body"].read().decode()
    v3 = s3.get_object(Bucket=bucket, Key="tutorials/prepare-meeting/v3.md")["Body"].read().decode()

    def steps(markdown: str) -> list[str]:
        body = markdown.split("## Steps", 1)[1].split("## Expected Outcome", 1)[0]
        return [line.strip() for line in body.strip().splitlines() if line.strip()]

    old, new = steps(v2), steps(v3)
    assert len(old) == len(new) == 4
    assert old[0] == new[0]
    assert old[1] == new[1]
    assert old[2] != new[2]
    assert old[3] == new[3]


@skip_unless_aws
def test_s5_aliases_已更新且主鍵不變():
    ddb = boto3.client("dynamodb")
    item = ddb.get_item(
        TableName=os.environ["TKB_TABLE_NAME"],
        Key={"PK": {"S": "FEATURE#Prepare"}, "SK": {"S": "META"}},
        ConsistentRead=True,
    )["Item"]
    assert item["name"]["S"] == "Prepare"
    assert "Meeting Summary" in [v["S"] for v in item["aliases"]["L"]]
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：

```bash
uv run pytest tests/unit/test_app_stack.py -v
TKB_RUN_AWS_TESTS=1 uv run pytest tests/integration/test_release_e2e.py -v
```

預期：CDK 測試的 `test_有兩條_state_machine` 會 `AssertionError`（目前只有一條）；端到端測試會因為 `TKB_RELEASE_STATE_MACHINE_ARN` 還沒設定而 `KeyError`。

- [ ] **步驟 3：寫最少的程式讓測試通過**

改 `infra/stacks/app_stack.py`：在 `TICKET_ASL` 常數旁邊加上 `RELEASE_ASL`，並把「建 state machine」與「建入口 Lambda」兩段換成下面這樣：

```python
TICKET_ASL = "infra/asl/ticket-analysis.asl.json"
RELEASE_ASL = "infra/asl/release-update.asl.json"
```

```python
        # 2) 兩條 state machine：定義都直接讀 ASL 檔。
        def make_state_machine(construct: str, name: str, asl_path: str) -> sfn.StateMachine:
            machine = sfn.StateMachine(
                self,
                construct,
                state_machine_name=name,
                state_machine_type=sfn.StateMachineType.STANDARD,
                definition_body=sfn.DefinitionBody.from_file(asl_path),
                definition_substitutions={
                    "PipelineTaskFunctionArn": pipeline_task_fn.function_arn
                },
                timeout=Duration.minutes(15),
            )
            pipeline_task_fn.grant_invoke(machine)
            return machine

        ticket_machine = make_state_machine(
            "TicketAnalysis", "training-kb-ticket-analysis", TICKET_ASL
        )
        release_machine = make_state_machine(
            "ReleaseUpdate", "training-kb-release-update", RELEASE_ASL
        )

        entry_env = dict(
            base_env,
            TKB_TICKET_STATE_MACHINE_ARN=ticket_machine.state_machine_arn,
            TKB_RELEASE_STATE_MACHINE_ARN=release_machine.state_machine_arn,
        )

        # 3) webhook：公開入口，8 秒內必須結束（設計 §14.3）。
        webhook_fn = make_function(
            "WebhookFunction",
            "training-kb-webhook",
            "training_kb.handlers.webhook.handler",
            8,
            dict(entry_env, TKB_GITHUB_WEBHOOK_SECRET=webhook_secret),
        )
        ticket_machine.grant_start_execution(webhook_fn)
        release_machine.grant_start_execution(webhook_fn)

        # 4) import：沒有公開網址，靠 IAM 驗證（設計 §7.1）。
        import_fn = make_function(
            "ImportFunction",
            "training-kb-import",
            "training_kb.handlers.import_.handler",
            120,
            dict(entry_env),
        )
        ticket_machine.grant_start_execution(import_fn)
        release_machine.grant_start_execution(import_fn)
```

最後在 `CfnOutput` 區塊加一行：

```python
        CfnOutput(self, "ReleaseStateMachineArn", value=release_machine.state_machine_arn)
```

`handlers/import_.py` 不用改：Phase 14 已經把 `release` 接到 `ingress.handle_manual_release`，而它會透過 `StepFunctionsStarter.start("release", ...)` 找 `TKB_RELEASE_STATE_MACHINE_ARN`。這一行環境變數之前是空的，所以 Phase 14 時啟動會失敗；補上之後就通了。

部署與快照：

```bash
uv run python infra/scripts/build_layer.py
uv run npx cdk deploy TrainingKbAppStack --require-approval never
uv run python infra/scripts/snapshot_asl.py release-update
echo "TKB_RELEASE_STATE_MACHINE_ARN=<部署輸出的 ReleaseStateMachineArn>" >> .env
```

預期輸出：`cdk deploy` 多印一個 `TrainingKbAppStack.ReleaseStateMachineArn = arn:...:stateMachine:training-kb-release-update`；快照指令印出 `已快照 infra/asl/release-update.asl.json -> s3://.../stepfunctions/release-update/v1.json`。

- [ ] **步驟 4：再跑一次測試，確認通過**

```bash
uv run pytest tests/unit -q
set -a; source .env; set +a
TKB_RUN_AWS_TESTS=1 uv run pytest tests/integration/test_release_e2e.py -v
```

預期：單元測試全綠；四個端到端測試 PASS。

> 跑端到端之前，圖譜裡要先有「A 的 v2 已發布、第 3 步引用 `FEATURE#Prepare`、B 與 C 不引用」這份資料。你可以先用 Phase 14 的 webhook 走一次 Ticket Analysis 建出 A v1，再手動匯入一筆 Feedback 走 Phase 17 產生 v2；或是等 Phase 21 的種子載入器一次備妥。在資料還沒備妥之前，這四個測試會因為 `hits` 是空的而失敗——那是資料還沒到位，不是程式錯了。

- [ ] **步驟 5：commit**

```bash
git add tests/unit/test_app_stack.py tests/integration/test_release_e2e.py \
        infra/stacks/app_stack.py
git commit -m "feat(infra): 加入 release-update state machine 與端到端驗收"
```

---

## 7. 完成檢查清單

- [ ] `uv run pytest tests/unit -q` 全綠；`uv run ruff check .`、`uv run ruff format --check .` 沒有錯誤。
- [ ] `uv run python -c "from training_kb.pipelines.release import TASKS; print(sorted(TASKS))"` 印出八個 task 名稱。
- [ ] `uv run npx cdk synth TrainingKbAppStack > /dev/null` 成功；`cdk deploy` 後印出 `ReleaseStateMachineArn`。
- [ ] `aws s3 ls s3://$TKB_BUCKET_NAME/stepfunctions/release-update/` 看得到 `v1.json`。
- [ ] **設計 §15「Release 精準更新」整列**：
  - [ ] A 只改第 3 步，第 1、2、4 步逐字相同（`test_只有第三步被改寫其餘逐字相同`、端到端 `test_s5_第一二四步逐字相同`）。
  - [ ] B、C 無新版（`test_b_與_c_沒有引用時完全不在命中集合`；端到端檢查 `aws s3 ls s3://$TKB_BUCKET_NAME/tutorials/share-summary/` 仍只有 `v1.md`）。
  - [ ] 歷史版步驟不觸發更新（`test_歷史版本的命中不觸發改寫`）。
  - [ ] 未發布版步驟不觸發更新（`test_未發布版本的命中不觸發改寫`）。
- [ ] **設計 §15「退役」整列**：
  - [ ] 有後繼、無後繼都能完成退役（`test_維護者有指定後繼時傳進去`、`test_removed_把命中的教學退役`）。
  - [ ] `removed` 沒有後繼仍完成退役，`successor` 是 `None`。
  - [ ] 退役後保留原文（`content.retire` 不刪版本，由 Phase 08 保證；本階段的檢查是 `aws s3 ls s3://$TKB_BUCKET_NAME/tutorials/<slug>/` 仍看得到所有 `.md`）。
  - [ ] 退役後拒絕新回饋（用 Phase 15 的 `import_feedback` 送一筆，預期 `rejected`）。
- [ ] **alias**：
  - [ ] 改名後 `FEATURE#Prepare` 的 `name` 是 `Prepare`、`aliases` 含 `Meeting Summary`，PK 沒變（端到端 `test_s5_aliases_已更新且主鍵不變`）。
  - [ ] alias 撞名時整條流程以 `PipelineFailed` 結束，不是 KEEP（`test_撞名不會被當成_keep`）。手動驗證：在 DynamoDB 另建一個 `FEATURE#Other` 且 `name` 為 `Prepare`，重跑一次 release，Step Functions 執行狀態應該是 `FAILED`。
- [ ] **Feature 語意搜尋**：`0.8499` 不採用、`0.85` 採用（`test_語意搜尋未達門檻時不改版也不建立_feature`、`test_剛好_0_85_算命中`）。
- [ ] **safety_net**：反查為零獨立觸發；alias 未命中的 `renamed` 也觸發；`changed` 不觸發；全數未確認以 KEEP 結束。
- [ ] **整批全有或全無**：`test_整批中有一篇失敗就是永久錯誤` 通過；Step Functions 上該次執行是 `FAILED`，且 `aws dynamodb get-item` 看到 `TUTORIAL#prepare-meeting` 的 `current_version` 沒有被改。
- [ ] **S5 切片**（設計 §16）：PR #42 只改 A 第 3 步；`removed` 呈現退役；B、C 不變。三項都用端到端測試或主控台確認過。
- [ ] Step Functions 主控台上，`training-kb-release-update` 的八個 Task 都看得到 `Retry` 與 `Catch`：
  ```bash
  aws stepfunctions describe-state-machine \
    --state-machine-arn $TKB_RELEASE_STATE_MACHINE_ARN \
    --query definition --output text | python -m json.tool | grep -c '"Retry"'
  ```
  預期輸出 `8`。

---

## 8. 常見錯誤與排除

**症狀 1：明明 A 的第 3 步引用了那個 Feature，`hits` 卻是空的，流程走到 KEEP。**
原因：多半是 GSI（`by_target`）還沒反映剛寫進去的邊，或是 `current_version` 指到一個 `published_at` 為空的版本。
解法：先跑 `aws dynamodb get-item --table-name training_kb --key '{"PK":{"S":"TUTORIAL#prepare-meeting"},"SK":{"S":"META"}}' --consistent-read` 看 `current_version`，再 `get-item` 那一版看 `published_at`。兩者都正確的話，`base_table_hits` 應該就能補上；如果連基表都查不到，代表 `REFERENCES` 邊根本沒寫進去，要用 Phase 09 的 `backfill_references` 補。**不要**為了讓它通過而放寬「只取目前已發布版本」這個條件，那會違反 F17。

**症狀 2：Step Functions 的 `Rewrite` 節點失敗，錯誤是 `PermanentError: 模型回傳的步驟編號 [1, 3] 與命中集合 [3] 不一致`。**
原因：模型多改了沒被命中的步驟。這正是程式核對要擋下來的事。
解法：這不是 bug，是保護機制在運作。看 CloudWatch log 裡的 prompt，確認 `prompt_rewrite_steps` 有把「需要改寫的步驟編號」寫清楚、而且沒有把其他步驟標成需要改寫。設計 §14.1 規定「schema 通過但步驟、引用或未改文字不符 → 業務驗證拒絕，有限重試後失敗，不發布」，所以正確的處置是失敗，不是放行。

**症狀 3：`PermanentError: S3 找不到前一版全文`。**
原因：`TutorialVersion.s3_key` 指到的物件不存在，通常是 Phase 07 的 `create_version` 中途失敗留下的不完整版本。
解法：`aws s3 ls s3://$TKB_BUCKET_NAME/tutorials/<slug>/` 確認哪些 `.md` 真的在。設計 §8.2 說「S3 成功但版本或關係未完成時，保留不可公開的產物，不刪掉後偽稱成功」，所以那個版本本來就不該是 `current_version`。檢查 `current_version` 有沒有被錯誤地切到未發布版本。

**症狀 4：`PermanentError: ... 的 S3 全文與 STEP item 不一致，無法安全改寫`。**
原因：S3 上的 `.md` 不是 `render_markdown` 產生的格式（最常見的是有人手動編輯過），所以 `parse_markdown` 還原出來的步驟文字跟 DynamoDB 的 `STEP#` item 對不上。`parse_markdown` 遇到不符合 `<編號>. (type=..., feature=...) <文字>` 的行會直接略過那一行，不會報錯，所以這個不一致只有靠 `rewrite` 的核對才抓得到。
解法：`aws s3 cp s3://$TKB_BUCKET_NAME/tutorials/<slug>/v<n>.md -` 印出來對照 Phase 07 的固定格式：`# Title`、`## Problem`、`## Prerequisites`、`## Steps`、`## Expected Outcome`，每一步都要有 `(type=..., feature=...)` 前綴。手動編輯 S3 上的教學全文會破壞這條路徑，不要這樣做；要修就重跑一次產生該版的流程。

**症狀 5：alias 更新完之後，下一次同一個 PR 重送，`locate_feature` 反而找不到 Feature 了。**
原因：`lookup_names` 會依序試 `feature`、`old_name`、`new_name`。改名完成後 `name` 是新名字、`aliases` 含舊名字，所以兩個都找得到——除非 `update_aliases` 沒把舊名字加進 `aliases`（例如中途失敗）。
解法：`aws dynamodb get-item --table-name training_kb --key '{"PK":{"S":"FEATURE#Prepare"},"SK":{"S":"META"}}' --consistent-read` 檢查 `aliases`。缺的話重跑一次 `update_aliases`（它是冪等的，`test_重複執行不會把舊名字加兩次` 有守）。

**症狀 6：`safety_net` 每次都呼叫模型，Bedrock 呼叫數比預期多很多。**
原因：`needs_safety_net` 的條件寫錯，最常見的是把「alias 未命中」單獨當成觸發條件，忘了 F16 要求同時是 `renamed`。
解法：對照 F16 原文：「只有 alias 比對失敗的 renamed 才算重大改名；反查為零仍獨立觸發」。也就是兩個獨立條件：`not hits`，或 `kind == renamed and not alias_hit`。`test_alias_未命中的_changed_不算重大改名` 就是在守這條。

**症狀 7：多篇教學被命中時，第一篇發布了、第二篇失敗，結果只有第一篇上線。**
原因：`task_publish` 沒有把所有 `new_version_ids` 一次交給 `content.publish`，而是逐篇呼叫。
解法：`task_publish` 只能呼叫 `content.publish` **一次**，把整份清單傳進去（`test_多篇一起送給_publish_只呼叫一次` 在守這條）。F49 與設計 §8.3 明寫「不能在逐篇 Map 中先發布 A，再因 B 失敗而聲稱整次沒有發布」。

**症狀 8：`ChooseAction` 走到 `PipelineFailed`，但看起來沒有任何錯誤。**
原因：`$.action` 的值不是 `UPDATE`、`RETIRE`、`KEEP` 三者之一（例如 `task_decide` 回傳了 `None`，或 state 在某個節點被整包覆蓋掉）。
解法：到 Step Functions 主控台打開該次執行，點 `Decide` 節點的 **Output** 分頁看 `action` 是什麼。`Default: PipelineFailed` 是刻意的——與其讓未知狀態悄悄跳過，不如明確失敗。

---

## 9. 這階段不做的事

- **不做 PR diff 的解析與子 Release 拆分。** 設計 §7.4 明寫「接入已完成 change 解析。流程中的 extract_change 使用並檢查這份結果，不再呼叫模型重新決定另一個 Release 身分」。`parse_pr_diff` 與 F14 的「多功能變更拆成多個子 Release、共用同一個 `source_event_id`」都在 Phase 12 完成；本階段只是消費那個結果。一個 PR 改三個功能，就是三次獨立的 Release Note Update 執行，各自有自己的 `r_` ID。
- **不建立新的 Feature。** 語意搜尋沒達 0.85 就 KEEP，不新增 Feature，也不改版（F15）。
- **不改 Feature 的主鍵。** 改名只動 `name` 與 `aliases`（D06）。
- **不做 REFINE。** 回饋導向的改寫在 Phase 17；兩者共用 `prompt_rewrite_steps` 與 `content.parse_markdown`，但診斷步驟的邏輯不同。
- **不做候選規則的提出或驗證。** 本階段只「使用」已經是 active 的規則（F27：一般寫作只用 active）。
- **不做 Feedback Review 的 state machine 與 EventBridge 排程。** 那是 Phase 18。
- **不做失敗注入驗收。** 發布中途失敗、S3 寫壞、多篇部分成功這些情境的完整驗收在 Phase 24（O2、O3）。
- **不做 `demo/previews/` 的規則開關對照。** 那是 Phase 23，而且它不寫正式教學與統計（F47）。
- **不承諾種子資料已核定。** 端到端測試需要的 A v1／v2 資料由 Phase 21 展開並驗證後才算核定（O7）。

---

## 10. 對照：設計章節與 Rule 編號

`依改版更新教學.feature` 共 17 條，全部列出：

| # | Rule 原文 | 本階段哪個 Task 落實 |
|---:|---|---|
| 1 | 從 PR diff 或 changelog 抽出 feature、kind、old_name 與 new_name | **不在本階段**：Phase 12 的 `parse_pr_diff`／`parse_changelog`。本階段在 Task 1 的 `load_release` 直接讀已經解析好的 Release，並在第 9 節說明 F14 的子 Release 由 Phase 12 拆好、共用 `source_event_id` |
| 2 | 改名前後的 alias 對應同一個 Feature 節點 | Task 1（`lookup_names` 同時試 `feature`／`old_name`／`new_name`；`test_alias_命中也算_alias_hit`） |
| 3 | 改名不變更第一次建立的 Feature 主鍵 | Task 8（`test_主鍵不因改名而改變`） |
| 4 | alias 比對未命中時以向量搜尋最相近的 Feature | Task 1（`semantic_feature`） |
| 5 | by_target 反查只選出引用改版 Feature 的步驟 | Task 2（`find_current_published_steps_referencing` + 基表核對） |
| 6 | 反查為零或重大改名時使用 step 文字向量搜尋補漏 | Task 3（`needs_safety_net`） |
| 7 | safety_net 的疑似命中交給 Claude 確認 | Task 3（`prompt_confirm_step_hits` + `StepConfirmation`） |
| 8 | renamed 或 changed 的改版動作為 UPDATE | Task 4（`test_renamed_有命中就是_update`、`test_changed_有命中也是_update`） |
| 9 | kind 為 removed 的改版動作為 RETIRE | Task 4（`test_removed_是_retire`） |
| 10 | UPDATE 只重寫受影響的步驟 | Task 6（`apply_rewrites` 的 index 集合檢查） |
| 11 | UPDATE 將未命中步驟的原文複製到下一版 | Task 6（`apply_rewrites` 的逐字比對；`test_只有第三步被改寫其餘逐字相同`） |
| 12 | 未引用改版 Feature 的教學維持 KEEP | Task 2、Task 4（`test_b_與_c_沒有引用時完全不在命中集合`） |
| 13 | UPDATE 為受影響教學產生與前版的 diff | Task 6（`content.create_version` 內含 `make_diff`，由 Phase 07 負責寫 `tutorials/<slug>/v<n>.diff`） |
| 14 | UPDATE 下一版的 reason 使用 release 加上改版事件 id | Task 6（`test_reason_是_release_加事件_id`） |
| 15 | UPDATE 完成時更新 Feature 的 aliases | Task 8、Task 9（ASL 把 `UpdateAliases` 排在 `Publish` 之後） |
| 16 | RETIRE 將受影響教學標記為過期 | Task 7（`content.retire` 寫入 `retired`；D21 只用 `retired`，`obsolete` 是顯示文字） |
| 17 | RETIRE 的教學導向後繼 Tutorial | Task 7（`successor_by_slug` 由維護者給；沒給就是 `None` 仍完成退役） |

其他 feature 檔：

| Rule 來源檔 | Rule 編號與原文 | 本階段哪個 Task 落實 |
|---|---|---|
| `套用教學規則.feature` | Rule 1：CREATE、UPDATE 與 REFINE 在寫作前讀取教學規則 | Task 6（`rules_for_content` 在 `allocate_version` 之前） |
| `套用教學規則.feature` | Rule 2：一般寫作路徑只取得 status 為 active 的規則 | Task 6（`repo.list_rules(RuleStatus.active)`；`test_改寫前注入適用的_active_規則` 驗證 candidate 不進 prompt） |
| `套用教學規則.feature` | Rule 3：依 step 型態與 applies_when 篩選規則 | Task 6（只把命中步驟的 `type` 傳給 `rules_for_content`） |
| `套用教學規則.feature` | Rule 4：適用規則的內容注入教學寫作 prompt | Task 5（`prompt_rewrite_steps` 的「適用的寫作規則」區塊） |
| `套用教學規則.feature` | Rule 7：版本的 rules_applied 記錄本次套用的規則 | Task 6（`allocate_version(..., rules_applied=rule_ids)`） |
| `套用教學規則.feature` | Rule 8：後續 Release 重寫仍注入適用的教學規則 | Task 6 |
| `建立教學版本.feature` | Rule 2：任一 pipeline 修改既有教學時使用該篇的下一個版本號 | Task 6（`content.allocate_version`） |
| `建立教學版本.feature` | Rule 3：新版以 supersedes 關聯同一篇教學的前一版 | Task 6（`VersionPlan.supersedes` 由 Phase 07 填） |
| `建立教學版本.feature` | Rule 4：每次建立版本都記錄引起變更的 reason | Task 6（`release:<id>`） |
| `建立教學版本.feature` | Rule 7：與前版的 diff 儲存在 `tutorials/<slug>/v<n>.diff` | Task 6（`create_version` 負責） |
| `發布教學版本.feature` | Rule 1：publish 上架指定的 TutorialVersion | Task 7 |
| `發布教學版本.feature` | Rule 4：Tutorial 的 current_version 指向目前教學版本 | Task 7（`content.publish` 的交易） |
| `發布教學版本.feature` | Rule 5：已上架的版本具有 published_at | Task 7 |
| `查詢知識圖譜.feature` | Rule 2：查詢誰引用 Feature 時使用 by_target 的 target | Task 2 |
| `查詢知識圖譜.feature` | Rule 3：沿 Feature 關係邊反查不呼叫 AI | Task 2（`task_find_steps` 完全沒有 `writer` 呼叫；`test_只命中教學_a_的第三步` 用的 `StubWriter` 不會被呼叫） |
| `執行教學流程.feature` | Rule 6：每個 Step Functions Task 設定 Retry | Task 9（`test_每個_task_都有_retry_與_catch`） |
| `執行教學流程.feature` | Rule 7：每個 Step Functions Task 設定 Catch | Task 9 |
| `執行教學流程.feature` | Rule 10：ASL 版本快照存於 `stepfunctions/<pipeline>/v<n>.json` | Task 10（`snapshot_asl.py release-update`） |

決策對照：

| 編號 | 內容 | 本階段怎麼落實 |
|---|---|---|
| D06 | 保留第一次建立的 FEATURE PK，改名只更新顯示名稱與 aliases | Task 8 |
| D07 | alias 必須唯一；衝突時拒絕該次 alias 更新 | Task 8（`alias_conflicts` + `PermanentError`） |
| D10 | Release 接入即完成解析；renamed 另要求 old_name 與 new_name | Task 8（缺任一就是永久錯誤）；接入驗證本身在 Phase 10 |
| D17 | 以版本的 rules_applied 為權威 | Task 6 |
| D21 | retired 是唯一資料狀態 | Task 7 |
| D22、F54 | successor 保存在 Tutorial metadata，由維護者選定既有 Tutorial | Task 7（`successor_by_slug`） |
| F14 | 多功能變更拆成多個子 Release，保留相同的父來源事件識別碼 | Phase 12 完成；本階段第 9 節說明 |
| F15 | 向量搜尋必須達明確門檻才可採用 | Task 1（0.85） |
| F16 | 只有 alias 比對失敗的 renamed 算重大改名；反查為零仍獨立觸發 | Task 3（`needs_safety_net`） |
| F17 | 只處理每篇目前已發布版本的步驟 | Task 2 |
| F18 | safety_net 沒有確認任何步驟時記錄未命中並以 KEEP 結束 | Task 3、Task 4 |
| F19 | 退役時沒有後繼仍完成退役，不產生導向 | Task 7 |
| F29 | 只記錄本次寫作 prompt 實際注入的規則 | Task 6（未命中步驟是程式複製，不進 prompt，也不計套用） |
| F35 | 同篇變更依接受順序串行處理 | Task 6（`with_tutorial_lock`） |
| F49 | Task 重試耗盡並進入 Catch 後整次以失敗結束，不發布新版本 | Task 7、Task 9（`PipelineFailed`） |

待確認事項：

| 編號 | 本階段怎麼處理 |
|---|---|
| O2（操作紀錄與接受順序） | **本計劃選擇**：`rewrite` 用 `with_tutorial_lock` 串行化同篇寫入，`allocate_version` 的 `operation_id` 用 `<operation_id>:<slug>`，讓同一次 Release 對同一篇教學重試時重用原版號（D26）。完整的失敗注入驗收在 Phase 24。 |
| O3（S3 公開與發布提交） | **本計劃選擇**：`task_publish` 只呼叫一次 `content.publish`，把整批 version_id 一起送出，失敗就整次 `PermanentError`。跨 S3 與 DynamoDB 的完整契約驗收在 Phase 24。 |
| O4（時間與比較邊界） | 本階段不做窗口計算；所有時間沿用 `Deps.now()` 提供的 UTC 值。 |
| O5（模型與參數） | 判斷節點（`safety_net`）用 `gen_max_tokens_judgement` 與 `gen_temperature`；寫作節點（`rewrite`）用 `gen_max_tokens_writing`。實際模型 ID 以 Phase 04 確認的為準。 |
| O7（核定種子） | 端到端測試需要的 A v1／v2 資料屬於設計 §11 的配方，Phase 21 展開並重算驗證後才算核定。本階段不宣稱已有實測結果。 |

---

## 11. 參考來源

設計文件章節（`docs/design/training-kb.md`）：

- §7.4 Release Note Update：UPDATE 或 RETIRE（定位、補漏、UPDATE、RETIRE、成功／KEEP、失敗六列契約）
- §7.6 共用寫作與 Analytics 的內部介面（改寫步驟：編號存在、僅改命中集合、其餘文字逐字相同）
- §8.1 五種動作與版本鏈、§8.2 create_version 的完成條件、§8.3 發布與併發必須守住的界線、§8.4 退役後的畫面與資料
- §9.1 鍵與原生型別（Feature PK 不因改名遷移）、§9.2 關係邊（`REFERENCES`、`SUPERSEDES`、`APPLIED_TO`）
- §10 圖譜查詢與多跳定位（by_target 反查、GSI 最終一致與基表核對、分頁要讀完）
- §14.1 各層如何結束、§14.2 重試不是重新抽一次文字、§14.3 執行參數
- §15 測試與驗收設計（「Release 精準更新」與「退役」兩列）
- §16 交付切片 S5
- §18 待確認事項 O2、O3、O4、O5、O7
- §19.1 資料決策 D06、D07、D10、D17、D21、D22、D26
- §19.2 功能決策 F14、F15、F16、F17、F18、F19、F29、F35、F49、F54

規格檔：

- `docs/spec/features/依改版更新教學.feature`（Rule 1–17 全部，含 `@Partial`／`@Specified` 的四個 Example）
- `docs/spec/features/套用教學規則.feature`（Rule 1、2、3、4、7、8）
- `docs/spec/features/建立教學版本.feature`（Rule 2、3、4、7）
- `docs/spec/features/發布教學版本.feature`（Rule 1、4、5）
- `docs/spec/features/查詢知識圖譜.feature`（Rule 2、3）
- `docs/spec/features/執行教學流程.feature`（Rule 6、7、10）

AWS 官方文件（2026-09-13 查證）：

- Step Functions Choice state 的比較運算子（含 `IsNull`）與 Task state：<https://docs.aws.amazon.com/step-functions/latest/dg/state-choice.html>、<https://docs.aws.amazon.com/step-functions/latest/dg/state-task.html>
- Step Functions 錯誤處理（`Retry` 的 `ErrorEquals`／`IntervalSeconds`／`MaxAttempts`／`BackoffRate`、`Catch` 的 `States.ALL`）：<https://docs.aws.amazon.com/step-functions/latest/dg/concepts-error-handling.html>
- AWS CDK Python：`aws_stepfunctions.DefinitionBody.from_file`：<https://docs.aws.amazon.com/cdk/api/v2/python/aws_cdk.aws_stepfunctions/FileDefinitionBody.html>
- AWS CDK Python：`aws_cdk.assertions.Template`（`from_stack`、`find_resources`、`has_resource_properties`、`Match`）：<https://docs.aws.amazon.com/cdk/api/v2/python/aws_cdk.assertions/Template.html>
- DynamoDB 讀取一致性（GSI 只有最終一致讀）：<https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/HowItWorks.ReadConsistency.html>
- DynamoDB 查詢分頁（`LastEvaluatedKey`）：<https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/Query.Pagination.html>
- pydantic v2 的 `model_copy(update=...)` 與 `model_validate`：<https://docs.pydantic.dev/latest/api/base_model/>
