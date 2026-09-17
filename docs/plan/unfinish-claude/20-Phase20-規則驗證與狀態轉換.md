# Phase 20：規則驗證與狀態轉換

| 項目 | 內容 |
|---|---|
| 上一階段 | Phase 19：Analytics 學習指標（`19-Phase19-Analytics-學習指標.md`） |
| 下一階段 | Phase 21：Demo 種子資料與可重算驗證（`21-Phase21-Demo種子資料與可重算驗證.md`） |
| 對應設計文件章節 | §12.2、§11.4、§7.6、§15「規則驗證」列（`docs/design/training-kb.md`） |
| 對應交付切片 | S7（設計文件第 16 節） |
| 預估時間 | 約 6 小時 |
| 做完會得到 | 一支能讀「核定種子批次」、重算同篇前後成效，並自動把 Authoring Rule 從 candidate 改成 active 或 retired 的程式。 |

---

## 1. 這階段做完會得到什麼

做完這一階段，你會有：

1. `SeedBatch`：一個「核定種子批次」的資料模型。一個批次裝著**同一篇教學**套用規則前後兩版的原始回饋、瀏覽紀錄與工單。
2. `evaluate_batch()`：用 Phase 19 的指標邏輯，對批次內的資料算出 before／after 兩組指標，並回答「平均評分有沒有嚴格提高」「重開票率有沒有嚴格下降」「這批到底可不可以判定」。
3. `next_status()`：純函式狀態機。輸入目前狀態與一串批次評估結果，輸出下一個狀態（`candidate` / `active` / `retired`）。
4. `apply_rule_status()`：**整個專案裡唯一**會寫入 `AuthoringRule.status` 與 `validated_at` 的函式，同時重建 `applied_to`。
5. 衝突判定：請 Claude 輸出結構化的 `ConflictJudgement`，再由程式檢查「被指名的規則存在嗎」「適用範圍一樣嗎」「引用的證據存在嗎」，通過才退役 candidate。
6. `curation_groups()`：把文字相近的規則分成群組**給人看**，不合併、不搬證據、不改狀態。
7. `handlers/analytics.py` 新增一個 `validate_rules` 動作，讓維護者用 `boto3 invoke`（或 Phase 23 的 `demo/cli.py`）觸發整段流程。

做完之後，你就可以（在 Phase 21 準備好種子資料後）看到 R-007 從 `candidate` 變成 `active`、R-012 從 `active` 變成 `retired`，而且每一步都有可重算的數字支撐。

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
                                                                                        |
學習層          17 Review:REFINE -> 18 Review:候選規則+排程 -> 19 Analytics 指標 -> 20 規則驗證
                                                                                        ^^^^^^^^^^
                                                                                        你在這裡
展示與驗收層    21 Demo 種子資料 -> 22 靜態教學站 -> 23 Demo 控制台 -> 24 失敗復原驗收 -> 25 安全與當日準備
```

你在「學習層」的最後一格。Phase 18 讓系統會「提出」規則（candidate），Phase 19 讓系統會「算」指標，Phase 20 把兩者接起來：用指標決定規則的命運。

---

## 3. 開始前檢查

### 3.1 前置條件

| 條件 | 為什麼需要 |
|---|---|
| Phase 01–03 完成 | 需要 `config.py`、`clock.py`、`errors.py`、`Repository`。 |
| Phase 05 完成 | 需要 `Writer` 介面、`FakeWriter`、`cosine`、`CallTrace`。 |
| Phase 09 完成 | 需要 `repo.list_versions_applying_rule()`、`repo.get_rule()`、`repo.put_rule()`、`repo.list_rules()`。 |
| Phase 19 完成 | 需要 `average_rating`、`negative_feedback_ids`、`reopen_stats`、`ReopenStats`、`VersionMetrics`、`version_metrics`。 |

### 3.2 驗證指令與預期輸出

```bash
cd ~/AWS-Hackathon
uv run python -c "
from training_kb.analytics import average_rating, negative_feedback_ids, reopen_stats, VersionMetrics, ReopenStats, version_metrics
print('analytics ok')
from training_kb.writing.client import FakeWriter, cosine
print('writing ok')
from training_kb.repository import Repository
print('repository ok')
"
```

預期看到三行：

```text
analytics ok
writing ok
repository ok
```

如果出現 `ImportError: cannot import name 'reopen_stats'`，代表 Phase 19 還沒做完，先回去把它做完再回來。

```bash
uv run pytest tests/unit -q
```

預期：全部 PASS（Phase 01–19 的測試）。**先確認舊測試是綠的**，之後新測試失敗時才知道是自己寫的問題。

---

## 4. 名詞小抄

| 名詞 | 白話解釋 | 在本階段哪裡用到 |
|---|---|---|
| Authoring Rule（教學規則） | 一句「寫教學時要遵守的要求」，例如「點 UI 的步驟要寫出按鈕在哪一頁、哪個位置」。它有編號（R-007）、證據（哪幾筆回饋歸納出來的）與適用範圍。 | 全部 Task |
| candidate / active / retired | 規則的三種狀態。candidate＝提出但還沒被證明有用；active＝已驗證，可供寫作使用；retired＝已停用。 | Task 3、4 |
| 核定種子批次（approved seed batch） | 一包「人工確認過的合成驗收資料」。裡面是同一篇教學套用規則前、後兩個版本的回饋／瀏覽／工單。設計文件 §12.2 規定：**只有載入完整核定批次才能改規則狀態**。 | Task 1、2、7 |
| 同篇前後對照 | 比較對象一定是**同一篇教學**套用規則前的已發布版本，不能拿別篇教學來湊（設計文件 F31）。 | Task 2 |
| 嚴格提高／嚴格下降 | 「嚴格」＝必須真的變好，持平（相等）不算。4.4 > 2.875 是嚴格提高；3.0 → 3.0 不是。 | Task 2、3 |
| 可判定（decidable） | 這批資料算得出有意義的結論嗎？分母是 0、算不出平均、批次還沒人工核定 → 不可判定，狀態維持原狀。 | Task 2、3 |
| 重開票率 | 「看過教學後又開同樣問題工單的人數」÷「這一版窗口內看過教學的人數」。Phase 19 已經實作，本階段只是拿來比較。 | Task 2 |
| 不重疊批次 | 兩個批次比較的版本完全沒有重複。例如「v1 vs v2」和「v3 vs v4」不重疊；「v1 vs v2」和「v2 vs v3」重疊（都含 v2）。 | Task 3 |
| ConflictJudgement | Claude 回傳的結構化衝突判定：`conflicts`（是否衝突）、`with_rule_id`（跟哪一條衝突）、`reason`、`evidence`。 | Task 5 |
| curation | 「整理／策展」。這裡指把文字相近的規則分群供人檢視。MVP 只分群，**不合併**。 | Task 6 |
| `validated_at` | 本計劃為設計文件 F28「同範圍衝突取最近驗證通過者」新增的欄位，記錄這條規則最近一次**驗證通過**（變成 active）的時間。它是 metadata 欄位，不是新實體。 | Task 4 |
| O7 | 設計文件第 18 節的待確認事項編號，指「核定種子與外部設定」。本計劃選擇：Phase 21 把配方展開成 JSON、以程式驗證重算值後，才由人工把批次標成核定。 | Task 7 |
| F30 / F31 / F32 / F33 / F34 / F55 | 設計文件第 19.2 節的功能決策編號。F30＝兩項都改善才啟用；F31＝對照取同篇套用前版本；F32＝只在完整核定批次才改狀態；F33＝連續兩批未改善才退役；F34＝curation 只分群；F55＝模型判衝突、Analytics 驗證後寫狀態。 | 第 10 節對照表 |

---

## 5. 設計說明

### 5.1 規則狀態機（設計文件 §12.2）

```text
            Feedback Review（Phase 18）提出
                       |
                       v
                  +-----------+
                  | candidate |
                  +-----------+
                    |   |   |
   一個完整核定批次  |   |   | 衝突判定通過程式驗證
   兩項嚴格改善      |   |   +---------------------+
                    |   |                          |
                    |   | 連續兩個不重疊核定批次    |
                    |   | 都未改善                  |
                    v   v                          v
              +--------+                     +---------+
              | active | ------------------> | retired |
              +--------+  連續兩個不重疊      +---------+
                          核定批次都未改善
                                ^
                                |  衝突判定「不」退役既有 active
                                +--- (X) 不覆蓋既有 active 規則

  資料不足 / 分母為 0 / 缺平均 / 批次未核定 --> 維持原狀態（不算無效）
```

三件事要特別記住：

1. **啟用要兩項都嚴格改善**（F30）。只有評分變好、重開票率持平，不啟用。
2. **退役要連續兩個「不重疊」的核定批次都未改善**（F33）。單一批次未改善不退役；持平視為未改善。
3. **衝突判定只會退役 candidate**（F55）。既有 active 規則不會因為別人跟它衝突就被退役。

### 5.2 一個核定種子批次長什麼樣

```text
SeedBatch
├── batch_id          "b_r007_01"                 批次編號
├── rule_id           "R-007"                     這批要驗證哪一條規則
├── slug              "prepare-meeting"           同一篇教學（F31 要求同篇）
├── before_version    "prepare-meeting@v1"        套用前的已發布版本
├── after_version     "prepare-meeting@v2"        套用後的版本
├── feedback[]        Feedback 物件清單            兩版的回饋都放在同一個清單
├── views[]           TutorialView 物件清單        兩版的瀏覽都放在同一個清單
├── tickets[]         Ticket 物件清單              重開票用的工單
├── approved          true / false                人工核定過才是 true（O7）
├── cluster_id        "c12"           （本階段新增，可空）比較用的同題 cluster
├── published_before  "2026-08-01T00:00:00Z"（本階段新增，可空）before 版的模擬發布時間
└── published_after   "2026-08-20T00:00:00Z"（本階段新增，可空）after 版的模擬發布時間

evaluate_batch() 會依 tutorial_version 把 feedback / views 拆成 before 與 after 兩組，
tickets 則整包交給 Phase 19 的 reopen_stats()，由它用「窗口 + cluster + 瀏覽先後」自己篩。
```

### 5.3 資料流：從批次到狀態

```text
S3: operations/rule-batches/<batch_id>.json
            |
            | load_seed_batch(repo, batch_id)
            v
        SeedBatch  --------------------------+
            |                                |
            | evaluate_batch(...)            | 若批次沒帶 cluster_id / published_*
            |   內部呼叫 Phase 19 的          | 就回頭查 repo.get_tutorial / get_version
            |   average_rating               |
            |   negative_feedback_ids  <-----+
            |   reopen_stats
            v
      RuleEvaluation(before, after, avg_improved, reopen_improved, decidable)
            |
            |  （candidate 才做）judge_conflict -> ConflictJudgement
            |                       |
            |                       v
            |            verify_conflict_judgement（程式驗證）
            |                       |
            v                       v
        next_status(current, evaluations, verified_conflict)
            |
            | 狀態有變才寫
            v
        apply_rule_status(repo, rule_id, status, now=...)
            |
            +--> 寫 RULE item 的 status
            +--> 寫 validated_at（只有 status=active 時才更新）
            +--> 以 repo.list_versions_applying_rule() 重建 applied_to（去重、保持順序）
```

### 5.4 Demo 的規則轉移順序（設計文件 §11.4）

這是 Phase 21 要準備的資料要支撐的故事，你在本階段寫的程式必須能跑出這個結果：

```text
 A v1（prepare-meeting@v1，2026-08-01 模擬發布）
   八筆同類回饋：f_12 f_15 f_19 f_23 f_27 f_31 f_34 f_40
   全部 category = 「找不到按鈕」，平均 23/8 = 2.875
            |
            | Phase 18 的 Feedback Review 提出
            v
   R-007  status = candidate
          applies_when = {"step.type": "click_ui"}
          derived_from = "prepare-meeting@v1"
          evidence = 上面八筆 Feedback ID
            |
            | 匯入「明示的 A v2 試用版本」與完整核定種子批次（F27、F32）
            | A v2 = prepare-meeting@v2，rules_applied = ["R-007"]，2026-08-20 模擬發布
            v
   Analytics（本階段）：
        平均評分   2.875  ->  4.4     嚴格提高  OK
        重開票率   70%    ->  20%     嚴格下降  OK
        重開票數   7 筆   ->  2 筆    （筆數，不是率）
            |
            v
   R-007  status = active，validated_at = 本次執行時間
            |
      +-----+----------------------------+
      v                                  v
 後續正式 B v1 可採用規則            PR #42（r_42）更新 A 的第 3 步
 （share-summary，Phase 13 正常流程）        |
                                            v
                                      A v3 仍採用規則
                                      （prepare-meeting@v3）
```

注意：`A v2` 是**明示的種子試用版本**（F27）。一般寫作路徑永遠只取 active 規則，不會自己拿 candidate 去試用。

### 5.5 為什麼「只有 Analytics 能寫 status」

設計文件 §7.6 與 §12.2 都明說：Feedback Review 只負責「提出」candidate，Analytics 才能寫驗證後的 status。這是為了讓「誰改了規則狀態」只有一個答案。因此本階段的 `apply_rule_status()` 是全專案唯一寫 `status` 與 `validated_at` 的地方；Phase 18 建立 candidate 時是 `put_rule()` 寫一個全新的規則，不是改狀態。

---

## 6. 工作項目

### Task 1：批次模型與批次指標計算

**目的**：定義 `SeedBatch`、`RuleEvaluation`，並寫出「從一堆記錄直接算 VersionMetrics」的共用函式。

**檔案**：
- 修改：`src/training_kb/analytics.py`
- 測試：`tests/unit/test_analytics_batch.py`

**介面**：
- 消費（Phase 19）：`analytics.average_rating(list[Feedback]) -> float | None`、`analytics.negative_feedback_ids(list[Feedback], list[str]) -> set[str]`、`analytics.reopen_stats(views, tickets, *, cluster_id, published_at, days=14) -> ReopenStats`、`analytics.VersionMetrics`
- 消費（Phase 02）：`models.Feedback`、`models.TutorialView`、`models.Ticket`
- 產出：
  - `analytics.SeedBatch`（pydantic BaseModel）
  - `analytics.RuleEvaluation`（dataclass）
  - `analytics.metrics_from_records(version_id, *, feedback, views, tickets, cluster_id, published_at, approved_categories, days=14) -> VersionMetrics`（**簡報第 6 節未列，本階段新增**：把 Phase 19 的三個計算函式組成一組指標，差別只在資料來自記憶體而不是 DynamoDB）
  - `SeedBatch` 的 `cluster_id`、`published_before`、`published_after` 三個可空欄位（**簡報 §6.9 未列，本階段新增**：讓批次自己帶比較脈絡，R-012 的展示批次才不需要在圖譜裡建版本）

- [ ] **步驟 1：寫測試**

```python
# tests/unit/test_analytics_batch.py
"""Phase 20 Task 1：核定種子批次模型與批次指標計算。"""

from training_kb.analytics import (
    RuleEvaluation,
    SeedBatch,
    VersionMetrics,
    metrics_from_records,
)
from training_kb.models import Feedback, Ticket, TutorialView

APPROVED = ["找不到按鈕", "缺少資訊"]


def _feedback(fid: str, version: str, rating: int, user: str, category: str | None) -> Feedback:
    return Feedback(
        id=fid,
        tutorial_version=version,
        rating=rating,
        user=user,
        category=category,
        comment=None,
        ts="2026-08-02T12:00:00Z",
    )


def _view(version: str, user: str, ts: str) -> TutorialView:
    return TutorialView(tutorial_version=version, user=user, ts=ts)


def _ticket(tid: str, user: str, ts: str) -> Ticket:
    return Ticket(
        id=tid,
        source="email",
        text="看過準備會議教學後，仍找不到第三步的按鈕",
        author=user,
        ts=ts,
        project_id="demo-project",
        cluster_id="c12",
    )


def test_seed_batch_可以從_dict_建立且預設未核定():
    batch = SeedBatch.model_validate(
        {
            "batch_id": "b_demo_01",
            "rule_id": "R-007",
            "slug": "prepare-meeting",
            "before_version": "prepare-meeting@v1",
            "after_version": "prepare-meeting@v2",
            "feedback": [],
            "views": [],
            "tickets": [],
        }
    )
    assert batch.approved is False
    assert batch.cluster_id is None
    assert batch.published_before is None
    assert batch.published_after is None


def test_seed_batch_可以帶比較脈絡():
    batch = SeedBatch.model_validate(
        {
            "batch_id": "b_demo_02",
            "rule_id": "R-007",
            "slug": "prepare-meeting",
            "before_version": "prepare-meeting@v1",
            "after_version": "prepare-meeting@v2",
            "approved": True,
            "cluster_id": "c12",
            "published_before": "2026-08-01T00:00:00Z",
            "published_after": "2026-08-20T00:00:00Z",
        }
    )
    assert batch.approved is True
    assert batch.cluster_id == "c12"
    assert batch.published_after == "2026-08-20T00:00:00Z"


def test_metrics_from_records_只算指定版本的回饋與瀏覽():
    feedback = [
        _feedback("f_12", "prepare-meeting@v1", 2, "u_01", "找不到按鈕"),
        _feedback("f_15", "prepare-meeting@v1", 4, "u_02", None),
        _feedback("f_101", "prepare-meeting@v2", 5, "u_03", None),
    ]
    views = [
        _view("prepare-meeting@v1", "u_01", "2026-08-02T09:00:00Z"),
        _view("prepare-meeting@v1", "u_02", "2026-08-02T09:00:00Z"),
        _view("prepare-meeting@v2", "u_03", "2026-08-21T09:00:00Z"),
    ]
    tickets = [_ticket("t_2001", "u_01", "2026-08-03T10:00:00Z")]

    metrics = metrics_from_records(
        "prepare-meeting@v1",
        feedback=feedback,
        views=views,
        tickets=tickets,
        cluster_id="c12",
        published_at="2026-08-01T00:00:00Z",
        approved_categories=APPROVED,
    )

    assert isinstance(metrics, VersionMetrics)
    assert metrics.version_id == "prepare-meeting@v1"
    assert metrics.n == 2
    assert metrics.avg == 3.0
    assert metrics.negative == 1
    assert metrics.reopen.viewers == 2
    assert metrics.reopen.count == 1
    assert metrics.reopen.reopen_users == 1
    assert metrics.reopen.rate == 0.5


def test_metrics_from_records_沒有回饋時平均為_None():
    metrics = metrics_from_records(
        "prepare-meeting@v9",
        feedback=[],
        views=[],
        tickets=[],
        cluster_id="c12",
        published_at="2026-08-01T00:00:00Z",
        approved_categories=APPROVED,
    )
    assert metrics.avg is None
    assert metrics.n == 0
    assert metrics.negative == 0
    assert metrics.reopen.rate is None


def test_rule_evaluation_是可直接建立的資料容器():
    before = metrics_from_records(
        "prepare-meeting@v1",
        feedback=[],
        views=[],
        tickets=[],
        cluster_id="c12",
        published_at="2026-08-01T00:00:00Z",
        approved_categories=APPROVED,
    )
    evaluation = RuleEvaluation(
        batch_id="b_demo_01",
        before=before,
        after=before,
        avg_improved=False,
        reopen_improved=False,
        decidable=False,
    )
    assert evaluation.batch_id == "b_demo_01"
    assert evaluation.decidable is False
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：`uv run pytest tests/unit/test_analytics_batch.py -v`

預期：FAIL，錯誤訊息類似 `ImportError: cannot import name 'SeedBatch' from 'training_kb.analytics'`。因為 `analytics.py` 目前只有 Phase 19 的指標函式，還沒有批次相關的東西。

- [ ] **步驟 3：寫最少的程式讓測試通過**

在 `src/training_kb/analytics.py` **檔案最上方的 import 區**加入下面這些（若已存在就不重複加）：

```python
from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel

from .models import Feedback, Ticket, TutorialView
```

在 `src/training_kb/analytics.py` **檔案結尾**加入：

```python
# ---------------------------------------------------------------------------
# Phase 20：核定種子批次與規則驗證
# ---------------------------------------------------------------------------


class SeedBatch(BaseModel):
    """一個核定種子批次：同一篇教學套用規則前後兩版的完整原始資料。

    approved 為 True 才代表維護者已人工核定（本計劃選擇，對應設計文件 O7）。
    cluster_id / published_before / published_after 是本階段新增的可空欄位，
    讓批次自己帶比較脈絡；留空時由呼叫端回頭查圖譜補上。
    """

    batch_id: str
    rule_id: str
    slug: str
    before_version: str
    after_version: str
    feedback: list[Feedback] = []
    views: list[TutorialView] = []
    tickets: list[Ticket] = []
    approved: bool = False
    cluster_id: str | None = None
    published_before: str | None = None
    published_after: str | None = None


@dataclass
class RuleEvaluation:
    """一個批次的評估結果。decidable 為 False 時兩個 improved 一律是 False。"""

    batch_id: str
    before: VersionMetrics
    after: VersionMetrics
    avg_improved: bool
    reopen_improved: bool
    decidable: bool


def metrics_from_records(
    version_id: str,
    *,
    feedback: list[Feedback],
    views: list[TutorialView],
    tickets: list[Ticket],
    cluster_id: str,
    published_at: str,
    approved_categories: list[str],
    days: int = 14,
) -> VersionMetrics:
    """用 Phase 19 的計算規則，對記憶體裡的記錄算出某一版的指標。

    與 version_metrics() 的差別只有資料來源：這裡不查 DynamoDB，
    直接吃批次檔裡的記錄，所以規則驗證不依賴圖譜狀態。
    """
    mine = [f for f in feedback if f.tutorial_version == version_id]
    my_views = [v for v in views if v.tutorial_version == version_id]
    return VersionMetrics(
        version_id=version_id,
        avg=average_rating(mine),
        n=len(mine),
        negative=len(negative_feedback_ids(mine, approved_categories)),
        reopen=reopen_stats(
            my_views,
            tickets,
            cluster_id=cluster_id,
            published_at=published_at,
            days=days,
        ),
    )
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：`uv run pytest tests/unit/test_analytics_batch.py -v`

預期：PASS，5 passed。

- [ ] **步驟 5：commit**

```bash
git add src/training_kb/analytics.py tests/unit/test_analytics_batch.py
git commit -m "feat(analytics): 新增核定種子批次模型與批次指標計算"
```

---

### Task 2：evaluate_batch — 同篇前後對照

**目的**：把一個批次算成 `RuleEvaluation`，並正確判斷「這批可不可以判定」。

**檔案**：
- 修改：`src/training_kb/analytics.py`
- 測試：`tests/unit/test_analytics_evaluate_batch.py`

**介面**：
- 消費（Task 1）：`analytics.SeedBatch`、`analytics.RuleEvaluation`、`analytics.metrics_from_records`
- 產出：`analytics.evaluate_batch(batch, *, cluster_id, published_before, published_after, approved_categories) -> RuleEvaluation`

**決定規則**（設計文件 §12.2、F30、F32）：

| 情況 | decidable | avg_improved | reopen_improved |
|---|---|---|---|
| 批次 `approved=False` | False | False | False |
| before 或 after 沒有任何有效評分（avg 為 None） | False | False | False |
| before 或 after 的重開票率是 N/A（分母 0） | False | False | False |
| 其他 | True | `after.avg > before.avg` | `after.rate < before.rate` |

- [ ] **步驟 1：寫測試**

```python
# tests/unit/test_analytics_evaluate_batch.py
"""Phase 20 Task 2：evaluate_batch 的同篇前後對照與可判定條件。"""

from training_kb.analytics import SeedBatch, evaluate_batch

APPROVED = ["找不到按鈕", "缺少資訊"]
CLUSTER = "c12"
P_BEFORE = "2026-08-01T00:00:00Z"
P_AFTER = "2026-08-20T00:00:00Z"


def _batch(
    *,
    before_ratings: list[int],
    after_ratings: list[int],
    before_reopen_users: int,
    after_reopen_users: int,
    before_viewers: int = 10,
    after_viewers: int = 10,
    approved: bool = True,
) -> SeedBatch:
    feedback = []
    for i, rating in enumerate(before_ratings, start=1):
        feedback.append(
            {
                "id": f"f_b{i}",
                "tutorial_version": "prepare-meeting@v1",
                "rating": rating,
                "user": f"u_{i:02d}",
                "category": None,
                "comment": None,
                "ts": "2026-08-02T12:00:00Z",
            }
        )
    for i, rating in enumerate(after_ratings, start=1):
        feedback.append(
            {
                "id": f"f_a{i}",
                "tutorial_version": "prepare-meeting@v2",
                "rating": rating,
                "user": f"u_{i:02d}",
                "category": None,
                "comment": None,
                "ts": "2026-08-21T12:00:00Z",
            }
        )

    views = []
    for i in range(1, before_viewers + 1):
        views.append(
            {
                "tutorial_version": "prepare-meeting@v1",
                "user": f"u_{i:02d}",
                "ts": "2026-08-02T09:00:00Z",
            }
        )
    for i in range(1, after_viewers + 1):
        views.append(
            {
                "tutorial_version": "prepare-meeting@v2",
                "user": f"u_{i:02d}",
                "ts": "2026-08-21T09:00:00Z",
            }
        )

    tickets = []
    for i in range(1, before_reopen_users + 1):
        tickets.append(
            {
                "id": f"t_20{i:02d}",
                "source": "email",
                "text": "看過準備會議教學後，仍找不到第三步的按鈕",
                "author": f"u_{i:02d}",
                "ts": "2026-08-03T10:00:00Z",
                "project_id": "demo-project",
                "cluster_id": CLUSTER,
            }
        )
    for i in range(1, after_reopen_users + 1):
        tickets.append(
            {
                "id": f"t_21{i:02d}",
                "source": "email",
                "text": "看過準備會議教學後，仍找不到第三步的按鈕",
                "author": f"u_{i:02d}",
                "ts": "2026-08-22T10:00:00Z",
                "project_id": "demo-project",
                "cluster_id": CLUSTER,
            }
        )

    return SeedBatch.model_validate(
        {
            "batch_id": "b_r007_01",
            "rule_id": "R-007",
            "slug": "prepare-meeting",
            "before_version": "prepare-meeting@v1",
            "after_version": "prepare-meeting@v2",
            "feedback": feedback,
            "views": views,
            "tickets": tickets,
            "approved": approved,
        }
    )


def _evaluate(batch: SeedBatch):
    return evaluate_batch(
        batch,
        cluster_id=CLUSTER,
        published_before=P_BEFORE,
        published_after=P_AFTER,
        approved_categories=APPROVED,
    )


def test_兩項都改善時兩個旗標都是_True():
    batch = _batch(
        before_ratings=[2, 2, 3, 3, 3, 3, 3, 4],
        after_ratings=[2, 2, 5, 5, 5, 5, 5, 5, 5, 5],
        before_reopen_users=7,
        after_reopen_users=2,
    )
    result = _evaluate(batch)

    assert result.decidable is True
    assert result.before.avg == 2.875
    assert result.after.avg == 4.4
    assert result.before.reopen.count == 7
    assert result.after.reopen.count == 2
    assert result.before.reopen.rate == 0.7
    assert result.after.reopen.rate == 0.2
    assert result.avg_improved is True
    assert result.reopen_improved is True


def test_評分持平不算改善():
    batch = _batch(
        before_ratings=[3, 3, 3, 3, 3],
        after_ratings=[3, 3, 3, 3, 3],
        before_reopen_users=4,
        after_reopen_users=2,
    )
    result = _evaluate(batch)

    assert result.decidable is True
    assert result.avg_improved is False
    assert result.reopen_improved is True


def test_重開票率持平不算改善():
    batch = _batch(
        before_ratings=[2, 2, 2, 2, 2],
        after_ratings=[5, 5, 5, 5, 5],
        before_reopen_users=3,
        after_reopen_users=3,
    )
    result = _evaluate(batch)

    assert result.decidable is True
    assert result.avg_improved is True
    assert result.reopen_improved is False


def test_批次未核定時不可判定():
    batch = _batch(
        before_ratings=[2, 2, 2],
        after_ratings=[5, 5, 5],
        before_reopen_users=3,
        after_reopen_users=1,
        approved=False,
    )
    result = _evaluate(batch)

    assert result.decidable is False
    assert result.avg_improved is False
    assert result.reopen_improved is False


def test_缺平均時不可判定():
    batch = _batch(
        before_ratings=[],
        after_ratings=[5, 5, 5],
        before_reopen_users=3,
        after_reopen_users=1,
    )
    result = _evaluate(batch)

    assert result.before.avg is None
    assert result.decidable is False


def test_零分母時不可判定():
    batch = _batch(
        before_ratings=[2, 2, 2],
        after_ratings=[5, 5, 5],
        before_reopen_users=0,
        after_reopen_users=0,
        after_viewers=0,
    )
    result = _evaluate(batch)

    assert result.after.reopen.rate is None
    assert result.decidable is False
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：`uv run pytest tests/unit/test_analytics_evaluate_batch.py -v`

預期：FAIL，錯誤訊息類似 `ImportError: cannot import name 'evaluate_batch' from 'training_kb.analytics'`。

- [ ] **步驟 3：寫最少的程式讓測試通過**

在 `src/training_kb/analytics.py` 的 Task 1 區塊後面加入：

```python
def evaluate_batch(
    batch: SeedBatch,
    *,
    cluster_id: str,
    published_before: str,
    published_after: str,
    approved_categories: list[str],
) -> RuleEvaluation:
    """對一個核定種子批次做同篇前後對照（設計文件 §12.2、F30、F31、F32）。

    對照組一律是同一篇教學套用規則前的已發布版本（F31），
    由批次檔的 before_version 指定，本函式不自行挑選對照。
    """
    before = metrics_from_records(
        batch.before_version,
        feedback=batch.feedback,
        views=batch.views,
        tickets=batch.tickets,
        cluster_id=cluster_id,
        published_at=published_before,
        approved_categories=approved_categories,
    )
    after = metrics_from_records(
        batch.after_version,
        feedback=batch.feedback,
        views=batch.views,
        tickets=batch.tickets,
        cluster_id=cluster_id,
        published_at=published_after,
        approved_categories=approved_categories,
    )

    decidable = (
        batch.approved
        and before.avg is not None
        and after.avg is not None
        and before.reopen.rate is not None
        and after.reopen.rate is not None
    )

    avg_improved = False
    reopen_improved = False
    if decidable:
        avg_improved = after.avg > before.avg
        reopen_improved = after.reopen.rate < before.reopen.rate

    return RuleEvaluation(
        batch_id=batch.batch_id,
        before=before,
        after=after,
        avg_improved=avg_improved,
        reopen_improved=reopen_improved,
        decidable=decidable,
    )
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：`uv run pytest tests/unit/test_analytics_evaluate_batch.py -v`

預期：PASS，6 passed。

- [ ] **步驟 5：commit**

```bash
git add src/training_kb/analytics.py tests/unit/test_analytics_evaluate_batch.py
git commit -m "feat(analytics): 以核定批次做同篇前後成效對照"
```

---

### Task 3：next_status — 狀態轉換純函式

**目的**：把「什麼情況該變成什麼狀態」寫成一個不碰資料庫、不碰模型的純函式。

**檔案**：
- 修改：`src/training_kb/analytics.py`
- 測試：`tests/unit/test_analytics_next_status.py`

**介面**：
- 消費（Task 2）：`analytics.RuleEvaluation`
- 消費（Phase 05 schemas，本階段 Task 5 才補完定義）：`writing.schemas.ConflictJudgement`
- 產出：`analytics.next_status(current, evaluations, conflict) -> RuleStatus`

**判定順序（本計劃選擇，對應設計文件 O4「規則驗證先固定一組同篇前後配對」）**：

設計文件只寫了各條件，沒有寫條件互相衝突時誰先判。本計劃固定下面的順序，並在程式註解裡標明：

1. `conflict` 不是 None 且 `conflicts=True` → `candidate` 變 `retired`；`active` 維持原狀（**不覆蓋既有 active**，設計文件 §12.2）。
2. 取出 `decidable=True` 的評估，維持呼叫端給的**時間順序**。一個都沒有 → 維持原狀（F32：資料不足不算無效）。
3. 看**最後兩個** decidable 評估：兩個都「未改善」且兩批的版本集合不重疊 → `retired`（F33）。退役先判，是為了避免一條已經連兩批失效的規則，因為更早的一批成功而被重新啟用。
4. `current` 是 `candidate`，且任一 decidable 評估「平均嚴格提高**且**重開票率嚴格下降」→ `active`（F30）。
5. 其他情況一律維持原狀。

「不重疊」的定義（**本計劃選擇**）：兩個評估的 `{before.version_id, after.version_id}` 兩個集合沒有交集。

- [ ] **步驟 1：寫測試**

```python
# tests/unit/test_analytics_next_status.py
"""Phase 20 Task 3：規則狀態轉換純函式。"""

from training_kb.analytics import ReopenStats, RuleEvaluation, VersionMetrics, next_status
from training_kb.models import RuleStatus
from training_kb.writing.schemas import ConflictJudgement


def _metrics(version_id: str, avg: float, rate: float) -> VersionMetrics:
    return VersionMetrics(
        version_id=version_id,
        avg=avg,
        n=10,
        negative=0,
        reopen=ReopenStats(count=0, reopen_users=0, viewers=10, rate=rate),
    )


def _evaluation(
    batch_id: str,
    before_version: str,
    after_version: str,
    *,
    avg_improved: bool,
    reopen_improved: bool,
    decidable: bool = True,
) -> RuleEvaluation:
    return RuleEvaluation(
        batch_id=batch_id,
        before=_metrics(before_version, 3.0, 0.5),
        after=_metrics(after_version, 3.0, 0.5),
        avg_improved=avg_improved,
        reopen_improved=reopen_improved,
        decidable=decidable,
    )


def test_兩項都改善時_candidate_升為_active():
    evaluations = [
        _evaluation("b1", "a@v1", "a@v2", avg_improved=True, reopen_improved=True)
    ]
    assert next_status(RuleStatus.candidate, evaluations, None) == RuleStatus.active


def test_只有評分改善不啟用():
    evaluations = [
        _evaluation("b1", "a@v1", "a@v2", avg_improved=True, reopen_improved=False)
    ]
    assert next_status(RuleStatus.candidate, evaluations, None) == RuleStatus.candidate


def test_只有重開票率改善不啟用():
    evaluations = [
        _evaluation("b1", "a@v1", "a@v2", avg_improved=False, reopen_improved=True)
    ]
    assert next_status(RuleStatus.candidate, evaluations, None) == RuleStatus.candidate


def test_兩項持平不啟用():
    evaluations = [
        _evaluation("b1", "a@v1", "a@v2", avg_improved=False, reopen_improved=False)
    ]
    assert next_status(RuleStatus.candidate, evaluations, None) == RuleStatus.candidate


def test_不完整批次保持原狀():
    evaluations = [
        _evaluation(
            "b1", "a@v1", "a@v2", avg_improved=False, reopen_improved=False, decidable=False
        )
    ]
    assert next_status(RuleStatus.candidate, evaluations, None) == RuleStatus.candidate
    assert next_status(RuleStatus.active, evaluations, None) == RuleStatus.active


def test_沒有任何批次時保持原狀():
    assert next_status(RuleStatus.candidate, [], None) == RuleStatus.candidate
    assert next_status(RuleStatus.active, [], None) == RuleStatus.active


def test_單一批次未改善不退役():
    evaluations = [
        _evaluation("b1", "a@v1", "a@v2", avg_improved=False, reopen_improved=False)
    ]
    assert next_status(RuleStatus.active, evaluations, None) == RuleStatus.active


def test_連續兩個不重疊批次未改善才退役():
    evaluations = [
        _evaluation("b1", "a@v1", "a@v2", avg_improved=False, reopen_improved=False),
        _evaluation("b2", "a@v3", "a@v4", avg_improved=False, reopen_improved=False),
    ]
    assert next_status(RuleStatus.active, evaluations, None) == RuleStatus.retired
    assert next_status(RuleStatus.candidate, evaluations, None) == RuleStatus.retired


def test_兩個重疊批次未改善不退役():
    evaluations = [
        _evaluation("b1", "a@v1", "a@v2", avg_improved=False, reopen_improved=False),
        _evaluation("b2", "a@v2", "a@v3", avg_improved=False, reopen_improved=False),
    ]
    assert next_status(RuleStatus.active, evaluations, None) == RuleStatus.active


def test_中間夾一個改善批次就不算連續():
    evaluations = [
        _evaluation("b1", "a@v1", "a@v2", avg_improved=False, reopen_improved=False),
        _evaluation("b2", "a@v3", "a@v4", avg_improved=True, reopen_improved=True),
    ]
    assert next_status(RuleStatus.active, evaluations, None) == RuleStatus.active


def test_衝突判定讓_candidate_退役():
    judgement = ConflictJudgement(
        conflicts=True,
        with_rule_id="R-003",
        reason="同一個 click_ui 範圍內，一條要求寫出完整位置，一條要求不超過兩句，無法同時滿足",
        evidence=["f_12"],
    )
    assert next_status(RuleStatus.candidate, [], judgement) == RuleStatus.retired


def test_衝突判定不覆蓋既有_active():
    judgement = ConflictJudgement(
        conflicts=True,
        with_rule_id="R-003",
        reason="範圍相同且要求互斥",
        evidence=["f_12"],
    )
    assert next_status(RuleStatus.active, [], judgement) == RuleStatus.active


def test_判定不衝突時不影響原本的升級():
    judgement = ConflictJudgement(
        conflicts=False, with_rule_id=None, reason="適用範圍不同", evidence=[]
    )
    evaluations = [
        _evaluation("b1", "a@v1", "a@v2", avg_improved=True, reopen_improved=True)
    ]
    assert next_status(RuleStatus.candidate, evaluations, judgement) == RuleStatus.active
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：`uv run pytest tests/unit/test_analytics_next_status.py -v`

預期：FAIL。第一個錯誤會是 `ImportError: cannot import name 'ConflictJudgement' from 'training_kb.writing.schemas'`（Task 5 才會補完 schema），或 `cannot import name 'next_status'`。**先做步驟 3 的第一段（補 schema），再做第二段。**

- [ ] **步驟 3：寫最少的程式讓測試通過**

先在 `src/training_kb/writing/schemas.py` 檔案結尾加入 schema（Task 5 會再補 prompt）：

```python
class ConflictJudgement(BaseModel):
    """模型對「candidate 是否與某條既有規則衝突」的結構化判定（設計文件 F55）。

    conflicts 為 True 時 with_rule_id 必須指名一條既有規則；
    程式端還會再驗證範圍與證據，通過才退役 candidate。
    """

    conflicts: bool
    with_rule_id: str | None = None
    reason: str = ""
    evidence: list[str] = []
```

再在 `src/training_kb/analytics.py` 的 Task 2 區塊後面加入：

```python
def _batch_versions(evaluation: RuleEvaluation) -> set[str]:
    """一個批次比較到的版本集合，用來判斷兩批是否重疊（本計劃選擇）。"""
    return {evaluation.before.version_id, evaluation.after.version_id}


def _is_improved(evaluation: RuleEvaluation) -> bool:
    """兩項都嚴格改善才算改善（設計文件 F30）。持平視為未改善。"""
    return evaluation.avg_improved and evaluation.reopen_improved


def next_status(
    current: RuleStatus,
    evaluations: list[RuleEvaluation],
    conflict: ConflictJudgement | None,
) -> RuleStatus:
    """依核定批次結果與衝突判定，決定規則的下一個狀態。

    conflict 只接受「已經通過 verify_conflict_judgement 的判定」；
    沒通過驗證的判定請傳 None，本函式不再自行驗證。

    判定順序是本計劃選擇（設計文件只列條件，未定義條件互撞時的先後）：
    1. 通過驗證的衝突 -> candidate 退役；active 維持（不覆蓋既有 active）。
    2. 沒有可判定的批次 -> 維持原狀（F32）。
    3. 最後兩個可判定批次都未改善且版本不重疊 -> retired（F33）。
    4. candidate 且任一可判定批次兩項嚴格改善 -> active（F30）。
    5. 其他維持原狀。
    """
    if conflict is not None and conflict.conflicts:
        if current == RuleStatus.candidate:
            return RuleStatus.retired
        return current

    decidable = [e for e in evaluations if e.decidable]
    if not decidable:
        return current

    if current in (RuleStatus.candidate, RuleStatus.active) and len(decidable) >= 2:
        previous, latest = decidable[-2], decidable[-1]
        both_unimproved = not _is_improved(previous) and not _is_improved(latest)
        disjoint = _batch_versions(previous).isdisjoint(_batch_versions(latest))
        if both_unimproved and disjoint:
            return RuleStatus.retired

    if current == RuleStatus.candidate and any(_is_improved(e) for e in decidable):
        return RuleStatus.active

    return current
```

最後在 `analytics.py` 的 import 區補上：

```python
from .models import RuleStatus
from .writing.schemas import ConflictJudgement
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：`uv run pytest tests/unit/test_analytics_next_status.py -v`

預期：PASS，13 passed。

- [ ] **步驟 5：commit**

```bash
git add src/training_kb/analytics.py src/training_kb/writing/schemas.py tests/unit/test_analytics_next_status.py
git commit -m "feat(analytics): 實作教學規則狀態轉換判定"
```

---

### Task 4：apply_rule_status — 唯一寫 status 的地方

**目的**：把新狀態寫回 DynamoDB，同時更新 `validated_at` 並重建 `applied_to`。

**檔案**：
- 修改：`src/training_kb/analytics.py`
- 測試：`tests/integration/test_analytics_apply_status.py`

**介面**：
- 消費（Phase 03、09）：`repo.get_rule(rule_id) -> AuthoringRule | None`、`repo.put_rule(rule)`、`repo.list_versions_applying_rule(rule_id) -> list[str]`
- 消費（Phase 01）：`clock.to_iso(dt) -> str`、`errors.PermanentError`
- 產出：`analytics.apply_rule_status(repo, rule_id, status, *, now) -> AuthoringRule`

**兩個重要決定**：

1. `validated_at` **只在狀態變成 `active` 時**寫入本次時間，其他狀態沿用原值。理由：設計文件 F28 說「同範圍衝突取最近**驗證通過**者」，所以這個欄位記的是「最近一次通過驗證」的時間，不是「最近一次被檢查」的時間。這是**本計劃選擇**（`validated_at` 本身就是本計劃為 F28 新增的 metadata 欄位）。
2. `applied_to` 一律用 `repo.list_versions_applying_rule()` 重建並去重、保持原順序。設計文件 D17 說：套用關係以各版本的 `rules_applied` 為權威，`applied_to` 是可重建的投影。

- [ ] **步驟 1：寫測試**

```python
# tests/integration/test_analytics_apply_status.py
"""Phase 20 Task 4：apply_rule_status 是唯一寫 status 與 validated_at 的地方。"""

from datetime import datetime, timezone

import pytest
from moto import mock_aws

from training_kb.analytics import apply_rule_status
from training_kb.errors import PermanentError
from training_kb.models import AuthoringRule, RuleStatus

NOW = datetime(2026, 9, 13, 8, 30, 0, tzinfo=timezone.utc)


class _FakeRepo:
    """只實作 apply_rule_status 需要的三個方法，方便單獨驗證行為。"""

    def __init__(self, rule: AuthoringRule | None, applied: list[str]) -> None:
        self._rule = rule
        self._applied = applied
        self.saved: AuthoringRule | None = None

    def get_rule(self, rule_id: str) -> AuthoringRule | None:
        if self._rule is not None and self._rule.rule_id == rule_id:
            return self._rule
        return None

    def put_rule(self, rule: AuthoringRule) -> None:
        self.saved = rule

    def list_versions_applying_rule(self, rule_id: str) -> list[str]:
        return list(self._applied)


def _rule(status: RuleStatus, validated_at: str | None = None) -> AuthoringRule:
    return AuthoringRule(
        rule_id="R-007",
        rule="點選 UI 的步驟必須寫出所在頁面、按鈕位置與點擊後會看到的結果。",
        applies_when={"step.type": "click_ui"},
        evidence=["f_12", "f_15"],
        status=status,
        applied_to=[],
        derived_from="prepare-meeting@v1",
        validated_at=validated_at,
    )


def test_升為_active_時寫入_validated_at():
    repo = _FakeRepo(_rule(RuleStatus.candidate), ["prepare-meeting@v2"])

    updated = apply_rule_status(repo, "R-007", RuleStatus.active, now=NOW)

    assert updated.status == RuleStatus.active
    assert updated.validated_at == "2026-09-13T08:30:00Z"
    assert repo.saved is not None
    assert repo.saved.status == RuleStatus.active


def test_退役時不改寫原本的_validated_at():
    repo = _FakeRepo(_rule(RuleStatus.active, "2026-09-01T00:00:00Z"), [])

    updated = apply_rule_status(repo, "R-007", RuleStatus.retired, now=NOW)

    assert updated.status == RuleStatus.retired
    assert updated.validated_at == "2026-09-01T00:00:00Z"


def test_applied_to_由_rules_applied_重建且去重保序():
    repo = _FakeRepo(
        _rule(RuleStatus.candidate),
        ["prepare-meeting@v2", "share-summary@v1", "prepare-meeting@v2", "prepare-meeting@v3"],
    )

    updated = apply_rule_status(repo, "R-007", RuleStatus.active, now=NOW)

    assert updated.applied_to == [
        "prepare-meeting@v2",
        "share-summary@v1",
        "prepare-meeting@v3",
    ]


def test_找不到規則時拋出_PermanentError():
    repo = _FakeRepo(None, [])

    with pytest.raises(PermanentError) as info:
        apply_rule_status(repo, "R-999", RuleStatus.active, now=NOW)

    assert "R-999" in str(info.value)


@mock_aws
def test_用真實_repository_寫入後讀得回來(repository):
    """repository fixture 由 Phase 03 的 conftest 提供（moto 建好 table 與 bucket）。"""
    repository.put_rule(_rule(RuleStatus.candidate))

    apply_rule_status(repository, "R-007", RuleStatus.active, now=NOW)

    stored = repository.get_rule("R-007")
    assert stored is not None
    assert stored.status == RuleStatus.active
    assert stored.validated_at == "2026-09-13T08:30:00Z"
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：`uv run pytest tests/integration/test_analytics_apply_status.py -v`

預期：FAIL，`ImportError: cannot import name 'apply_rule_status' from 'training_kb.analytics'`。

- [ ] **步驟 3：寫最少的程式讓測試通過**

在 `src/training_kb/analytics.py` 的 Task 3 區塊後面加入：

```python
def apply_rule_status(
    repo: "Repository",
    rule_id: str,
    status: RuleStatus,
    *,
    now: datetime,
) -> AuthoringRule:
    """把驗證後的 status 寫回 RULE item。

    設計文件 §7.6、§12.2：只有 Analytics 能寫驗證後的 status，
    因此整個專案只有這個函式會改 AuthoringRule.status 與 validated_at。

    validated_at 只在 status 變成 active 時更新（本計劃選擇，對應 F28
    「同範圍衝突取最近驗證通過者」）；其他狀態沿用原值。
    applied_to 一律由各版本的 rules_applied 重建（D17），去重且保持順序。
    """
    rule = repo.get_rule(rule_id)
    if rule is None:
        raise PermanentError(f"找不到規則 {rule_id}，無法寫入驗證後狀態")

    seen: set[str] = set()
    applied_to: list[str] = []
    for version_id in repo.list_versions_applying_rule(rule_id):
        if version_id not in seen:
            seen.add(version_id)
            applied_to.append(version_id)

    validated_at = to_iso(now) if status == RuleStatus.active else rule.validated_at
    updated = rule.model_copy(
        update={
            "status": status,
            "applied_to": applied_to,
            "validated_at": validated_at,
        }
    )
    repo.put_rule(updated)
    return updated
```

在 `analytics.py` 的 import 區補上：

```python
from datetime import datetime

from .clock import to_iso
from .errors import PermanentError
from .models import AuthoringRule
from .repository import Repository
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：`uv run pytest tests/integration/test_analytics_apply_status.py -v`

預期：PASS，5 passed。

- [ ] **步驟 5：commit**

```bash
git add src/training_kb/analytics.py tests/integration/test_analytics_apply_status.py
git commit -m "feat(analytics): 寫入規則驗證後狀態並重建 applied_to"
```

---

### Task 5：衝突判定（模型輸出 + 程式驗證）

**目的**：讓 Claude 產生結構化衝突判定，再由程式檢查三件事後才採用。

**檔案**：
- 修改：`src/training_kb/writing/prompts.py`
- 修改：`src/training_kb/analytics.py`
- 測試：`tests/unit/test_analytics_conflict.py`

**介面**：
- 消費（Phase 05）：`Writer.generate_json(*, system, user, schema, operation_id, node, max_tokens, temperature) -> T`、`FakeWriter`
- 消費（Phase 09）：`repo.list_rules(status) -> list[AuthoringRule]`
- 產出：
  - `writing.prompts.prompt_judge_conflict(candidate, existing) -> tuple[str, str]`
  - `analytics.verify_conflict_judgement(judgement, candidate, existing) -> list[str]`（**簡報第 6 節未列，本階段新增**：回傳「不能採用這份判定的原因」，空清單代表通過）
  - `analytics.judge_conflict(repo, writer, candidate, *, operation_id, max_tokens=512) -> tuple[ConflictJudgement | None, list[str]]`（**簡報第 6 節未列，本階段新增**）

**程式驗證的四件事**（設計文件 §7.6：「參照存在、範圍一致、不是只因文字相似就退役」）：

1. `conflicts=True` 時 `with_rule_id` 必填，且必須真的存在於傳入的既有規則清單，也不能指向 candidate 自己。
2. 兩條規則的 `applies_when` 必須**完全相同**。範圍不同就不算衝突（例如一條管 `click_ui`、一條管 `read`）。
3. `reason` 不可為空。
4. `evidence` 不可為空，每個 ID 必須存在於 candidate 或被指名規則的 evidence 裡，而且**至少要引用一筆 candidate 自己的證據**。這一條就是「不只因文字相似就退役」的程式化表達：程式完全不比對規則文字的相似度，也不接受「文字很像」當唯一理由。

- [ ] **步驟 1：寫測試**

```python
# tests/unit/test_analytics_conflict.py
"""Phase 20 Task 5：衝突判定的模型輸出與程式驗證。"""

from training_kb.analytics import judge_conflict, verify_conflict_judgement
from training_kb.models import AuthoringRule, RuleStatus
from training_kb.writing.client import FakeWriter
from training_kb.writing.prompts import prompt_judge_conflict
from training_kb.writing.schemas import ConflictJudgement


def _rule(
    rule_id: str,
    text: str,
    step_type: str,
    evidence: list[str],
    status: RuleStatus = RuleStatus.active,
) -> AuthoringRule:
    return AuthoringRule(
        rule_id=rule_id,
        rule=text,
        applies_when={"step.type": step_type},
        evidence=evidence,
        status=status,
        applied_to=[],
        derived_from="prepare-meeting@v1",
    )


CANDIDATE = _rule(
    "R-007",
    "點選 UI 的步驟必須寫出所在頁面、按鈕位置與點擊後會看到的結果。",
    "click_ui",
    ["f_12", "f_15"],
    RuleStatus.candidate,
)
EXISTING_SAME_SCOPE = _rule("R-003", "每步不超過兩句。", "click_ui", ["f_90"])
EXISTING_OTHER_SCOPE = _rule("R-004", "每步不超過兩句。", "read", ["f_91"])


class _RuleRepo:
    def __init__(self, rules: list[AuthoringRule]) -> None:
        self._rules = rules

    def list_rules(self, status=None) -> list[AuthoringRule]:
        if status is None:
            return list(self._rules)
        return [r for r in self._rules if r.status == status]


def test_prompt_judge_conflict_回傳兩段文字且含規則編號():
    system, user = prompt_judge_conflict(CANDIDATE, [EXISTING_SAME_SCOPE])
    assert isinstance(system, str) and isinstance(user, str)
    assert "R-007" in user
    assert "R-003" in user
    assert "click_ui" in user


def test_完整合法的判定通過驗證():
    judgement = ConflictJudgement(
        conflicts=True,
        with_rule_id="R-003",
        reason="同為 click_ui 範圍，一條要求補足位置與結果，一條限制兩句，無法同時滿足。",
        evidence=["f_12", "f_90"],
    )
    assert verify_conflict_judgement(judgement, CANDIDATE, [EXISTING_SAME_SCOPE]) == []


def test_判定不衝突時不能拿來退役():
    judgement = ConflictJudgement(conflicts=False, with_rule_id=None, reason="", evidence=[])
    problems = verify_conflict_judgement(judgement, CANDIDATE, [EXISTING_SAME_SCOPE])
    assert problems != []


def test_指名不存在的規則不通過():
    judgement = ConflictJudgement(
        conflicts=True, with_rule_id="R-999", reason="衝突", evidence=["f_12"]
    )
    problems = verify_conflict_judgement(judgement, CANDIDATE, [EXISTING_SAME_SCOPE])
    assert any("R-999" in p for p in problems)


def test_適用範圍不同時不算衝突_即使文字幾乎一樣():
    judgement = ConflictJudgement(
        conflicts=True,
        with_rule_id="R-004",
        reason="兩條規則文字非常相似",
        evidence=["f_12", "f_91"],
    )
    problems = verify_conflict_judgement(judgement, CANDIDATE, [EXISTING_OTHER_SCOPE])
    assert any("applies_when" in p for p in problems)


def test_沒有證據時不通過():
    judgement = ConflictJudgement(
        conflicts=True, with_rule_id="R-003", reason="文字相似", evidence=[]
    )
    problems = verify_conflict_judgement(judgement, CANDIDATE, [EXISTING_SAME_SCOPE])
    assert any("evidence" in p for p in problems)


def test_證據引用不存在時不通過():
    judgement = ConflictJudgement(
        conflicts=True, with_rule_id="R-003", reason="衝突", evidence=["f_12", "f_777"]
    )
    problems = verify_conflict_judgement(judgement, CANDIDATE, [EXISTING_SAME_SCOPE])
    assert any("f_777" in p for p in problems)


def test_沒有引用_candidate_自己的證據時不通過():
    judgement = ConflictJudgement(
        conflicts=True, with_rule_id="R-003", reason="衝突", evidence=["f_90"]
    )
    problems = verify_conflict_judgement(judgement, CANDIDATE, [EXISTING_SAME_SCOPE])
    assert any("candidate" in p for p in problems)


def test_judge_conflict_會呼叫模型並附上驗證結果():
    judgement = ConflictJudgement(
        conflicts=True,
        with_rule_id="R-003",
        reason="同為 click_ui 範圍且要求互斥。",
        evidence=["f_12", "f_90"],
    )
    writer = FakeWriter(outputs=[judgement])
    repo = _RuleRepo([EXISTING_SAME_SCOPE, EXISTING_OTHER_SCOPE])

    result, problems = judge_conflict(
        repo, writer, CANDIDATE, operation_id="analytics:validate:R-007"
    )

    assert result is not None
    assert result.with_rule_id == "R-003"
    assert problems == []


def test_同範圍沒有_active_規則時不呼叫模型():
    writer = FakeWriter(outputs=[])
    repo = _RuleRepo([EXISTING_OTHER_SCOPE])

    result, problems = judge_conflict(
        repo, writer, CANDIDATE, operation_id="analytics:validate:R-007"
    )

    assert result is None
    assert problems != []
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：`uv run pytest tests/unit/test_analytics_conflict.py -v`

預期：FAIL，`ImportError: cannot import name 'prompt_judge_conflict' from 'training_kb.writing.prompts'`。

- [ ] **步驟 3：寫最少的程式讓測試通過**

先在 `src/training_kb/writing/prompts.py` 檔案結尾加入：

```python
def prompt_judge_conflict(
    candidate: "AuthoringRule", existing: list["AuthoringRule"]
) -> tuple[str, str]:
    """請模型判斷 candidate 是否與同適用範圍的既有規則衝突（設計文件 F55）。

    回傳 (system, user) 兩段文字。模型只負責判斷與舉證；
    是否真的退役由 analytics.verify_conflict_judgement 驗證後決定。
    """
    system = (
        "你是教學寫作規則的審查員。"
        "你要判斷一條候選規則是否與既有規則互相衝突，也就是同一個步驟無法同時滿足兩者。"
        "只根據規則內容與適用範圍判斷，不要因為兩條文字相似就說衝突。"
        "請只輸出 JSON，欄位為 conflicts(boolean)、with_rule_id(string 或 null)、"
        "reason(string)、evidence(string 陣列)。"
        "evidence 只能填入下面提供的 Feedback ID，且必須至少包含一個候選規則的證據 ID。"
        "若判斷為不衝突，conflicts 填 false、with_rule_id 填 null。"
    )

    def _render(rule: "AuthoringRule") -> str:
        scope = ", ".join(f"{k}={v}" for k, v in sorted(rule.applies_when.items()))
        evidence = ", ".join(rule.evidence) if rule.evidence else "（無）"
        return f"- {rule.rule_id}｜適用範圍：{scope}｜內容：{rule.rule}｜證據：{evidence}"

    existing_block = "\n".join(_render(rule) for rule in existing)
    user = (
        "候選規則：\n"
        f"{_render(candidate)}\n\n"
        "同適用範圍的既有 active 規則：\n"
        f"{existing_block}\n\n"
        "請判斷候選規則是否與其中某一條衝突。"
    )
    return system, user
```

`prompts.py` 的 import 區補上（若尚未匯入）：

```python
from ..models import AuthoringRule
```

再在 `src/training_kb/analytics.py` 的 Task 4 區塊後面加入：

```python
def verify_conflict_judgement(
    judgement: ConflictJudgement,
    candidate: AuthoringRule,
    existing: list[AuthoringRule],
) -> list[str]:
    """驗證一份衝突判定能不能用來退役 candidate。

    回傳「不能採用的原因」清單；空清單代表通過驗證。
    設計文件 §7.6 要求：參照存在、範圍一致、不是只因文字相似就退役。
    本函式完全不比對規則文字相似度，也不接受「文字相似」作為理由。
    """
    problems: list[str] = []

    if not judgement.conflicts:
        return ["judgement.conflicts 為 False，不構成退役理由"]

    if not judgement.with_rule_id:
        return ["conflicts 為 True 但沒有指名 with_rule_id"]

    by_id = {rule.rule_id: rule for rule in existing}
    other = by_id.get(judgement.with_rule_id)
    if other is None:
        return [f"with_rule_id {judgement.with_rule_id} 不在傳入的既有規則清單中"]

    if other.rule_id == candidate.rule_id:
        problems.append("with_rule_id 指向 candidate 自己")

    if other.applies_when != candidate.applies_when:
        problems.append(
            "兩條規則的 applies_when 不相等，適用範圍不同就不算衝突"
        )

    if not judgement.reason.strip():
        problems.append("reason 為空")

    if not judgement.evidence:
        problems.append("evidence 為空；只因文字相似不退役")
    else:
        known = set(candidate.evidence) | set(other.evidence)
        unknown = [e for e in judgement.evidence if e not in known]
        if unknown:
            problems.append(f"evidence 引用不存在的回饋：{unknown}")
        if not set(judgement.evidence) & set(candidate.evidence):
            problems.append("evidence 沒有引用 candidate 自己的回饋證據")

    return problems


def judge_conflict(
    repo: "Repository",
    writer: "Writer",
    candidate: AuthoringRule,
    *,
    operation_id: str,
    max_tokens: int = 512,
) -> tuple[ConflictJudgement | None, list[str]]:
    """請模型判斷衝突，再交給程式驗證（設計文件 F55）。

    回傳 (判定, 不能採用的原因清單)。
    同適用範圍沒有 active 規則時不呼叫模型，回傳 (None, [原因])。
    """
    existing = [
        rule
        for rule in repo.list_rules(RuleStatus.active)
        if rule.applies_when == candidate.applies_when and rule.rule_id != candidate.rule_id
    ]
    if not existing:
        return None, ["同適用範圍沒有 active 規則，不做衝突判定"]

    system, user = prompt_judge_conflict(candidate, existing)
    judgement = writer.generate_json(
        system=system,
        user=user,
        schema=ConflictJudgement,
        operation_id=operation_id,
        node="judge_conflict",
        max_tokens=max_tokens,
        temperature=0.1,
    )
    return judgement, verify_conflict_judgement(judgement, candidate, existing)
```

`analytics.py` 的 import 區補上：

```python
from .writing.client import Writer
from .writing.prompts import prompt_judge_conflict
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：`uv run pytest tests/unit/test_analytics_conflict.py -v`

預期：PASS，10 passed。

- [ ] **步驟 5：commit**

```bash
git add src/training_kb/analytics.py src/training_kb/writing/prompts.py tests/unit/test_analytics_conflict.py
git commit -m "feat(analytics): 加入規則衝突判定與程式驗證"
```

---

### Task 6：curation_groups — 只分群給人看

**目的**：把文字相近的規則分成群組供人工檢視，**不改任何資料**。

**檔案**：
- 修改：`src/training_kb/analytics.py`
- 測試：`tests/unit/test_analytics_curation.py`

**介面**：
- 消費（Phase 05）：`Writer.embed(text, *, operation_id, node) -> list[float]`、`writing.client.cosine(a, b) -> float`
- 產出：`analytics.curation_groups(rules, writer, *, similar_at=0.85, operation_id="analytics:curation") -> list[list[str]]`

設計文件 F34 在規格檔中標註「未定義觸發時機、相近判準、合併後 ID」。因此相近判準由本階段決定，**本計劃選擇**：

- 只在**相同 `applies_when`** 的規則之間比較（範圍不同的規則沒有合併問題）。
- 用 `Writer.embed()` 算規則文字的向量，cosine ≥ `similar_at`（預設 0.85，與設計文件其他語意比對門檻一致）視為相近。
- 相近關係具傳遞性（A 近 B、B 近 C 就同一群）。
- 只回傳 2 條以上的群組，群內與群間都依 `rule_id` 排序，結果可重現。
- **不合併 ID、不搬移 evidence、不改 status、不改文字。**

`similar_at` 與 `operation_id` 是本階段新增的具名參數，有預設值，所以 `curation_groups(rules, writer)` 這個簡報寫法仍然可用。

- [ ] **步驟 1：寫測試**

```python
# tests/unit/test_analytics_curation.py
"""Phase 20 Task 6：curation 只分群供人檢視，不改資料。"""

from training_kb.analytics import curation_groups
from training_kb.models import AuthoringRule, RuleStatus
from training_kb.writing.client import FakeWriter


def _rule(rule_id: str, text: str, step_type: str) -> AuthoringRule:
    return AuthoringRule(
        rule_id=rule_id,
        rule=text,
        applies_when={"step.type": step_type},
        evidence=["f_1"],
        status=RuleStatus.active,
        applied_to=["prepare-meeting@v2"],
        derived_from="prepare-meeting@v1",
    )


TEXT_A = "點選 UI 的步驟要寫出按鈕位置。"
TEXT_B = "點 UI 的步驟必須說明按鈕在哪裡。"
TEXT_C = "閱讀型步驟要寫出資料更新頻率。"
TEXT_D = "點選 UI 的步驟要附上截圖。"

EMBEDDINGS = {
    TEXT_A: [1.0, 0.0, 0.0],
    TEXT_B: [0.99, 0.141, 0.0],
    TEXT_C: [0.0, 1.0, 0.0],
    TEXT_D: [0.0, 0.0, 1.0],
}


def test_同範圍且文字相近的規則會分在同一群():
    rules = [
        _rule("R-007", TEXT_A, "click_ui"),
        _rule("R-009", TEXT_B, "click_ui"),
        _rule("R-011", TEXT_D, "click_ui"),
    ]
    writer = FakeWriter(embeddings=EMBEDDINGS)

    groups = curation_groups(rules, writer)

    assert groups == [["R-007", "R-009"]]


def test_適用範圍不同不會分在同一群():
    rules = [
        _rule("R-007", TEXT_A, "click_ui"),
        _rule("R-020", TEXT_A, "read"),
    ]
    writer = FakeWriter(embeddings=EMBEDDINGS)

    groups = curation_groups(rules, writer)

    assert groups == []


def test_沒有相近規則時回傳空清單():
    rules = [
        _rule("R-007", TEXT_A, "click_ui"),
        _rule("R-030", TEXT_C, "click_ui"),
    ]
    writer = FakeWriter(embeddings=EMBEDDINGS)

    assert curation_groups(rules, writer) == []


def test_curation_不改任何規則資料():
    rules = [
        _rule("R-007", TEXT_A, "click_ui"),
        _rule("R-009", TEXT_B, "click_ui"),
    ]
    before = [rule.model_dump() for rule in rules]
    writer = FakeWriter(embeddings=EMBEDDINGS)

    curation_groups(rules, writer)

    after = [rule.model_dump() for rule in rules]
    assert after == before
    assert all(rule.status == RuleStatus.active for rule in rules)
    assert all(rule.evidence == ["f_1"] for rule in rules)


def test_門檻可調高讓相近規則分開():
    rules = [
        _rule("R-007", TEXT_A, "click_ui"),
        _rule("R-009", TEXT_B, "click_ui"),
    ]
    writer = FakeWriter(embeddings=EMBEDDINGS)

    assert curation_groups(rules, writer, similar_at=0.999) == []
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：`uv run pytest tests/unit/test_analytics_curation.py -v`

預期：FAIL，`ImportError: cannot import name 'curation_groups' from 'training_kb.analytics'`。

- [ ] **步驟 3：寫最少的程式讓測試通過**

在 `src/training_kb/analytics.py` 的 Task 5 區塊後面加入：

```python
def _scope_key(rule: AuthoringRule) -> str:
    """把 applies_when 轉成可排序、可比較的字串。"""
    return json.dumps(rule.applies_when, sort_keys=True, ensure_ascii=False)


def _group_within_scope(
    members: list[AuthoringRule],
    vectors: dict[str, list[float]],
    similar_at: float,
) -> list[list[str]]:
    """在同一適用範圍內，用 cosine 門檻做具傳遞性的分群。"""
    ordered = sorted(members, key=lambda rule: rule.rule_id)
    parent = {rule.rule_id: rule.rule_id for rule in ordered}

    def find(node: str) -> str:
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    for index, left in enumerate(ordered):
        for right in ordered[index + 1 :]:
            if cosine(vectors[left.rule_id], vectors[right.rule_id]) >= similar_at:
                root_left, root_right = find(left.rule_id), find(right.rule_id)
                if root_left != root_right:
                    parent[root_right] = root_left

    buckets: dict[str, list[str]] = {}
    for rule in ordered:
        buckets.setdefault(find(rule.rule_id), []).append(rule.rule_id)
    return [sorted(ids) for _, ids in sorted(buckets.items()) if len(ids) >= 2]


def curation_groups(
    rules: list[AuthoringRule],
    writer: "Writer",
    *,
    similar_at: float = 0.85,
    operation_id: str = "analytics:curation",
) -> list[list[str]]:
    """把文字相近的規則分成群組供人工檢視（設計文件 §12.2、F34）。

    MVP 只分群：不合併 ID、不搬移 evidence、不改文字、不改 status。
    相近判準是本計劃選擇：同一 applies_when 內，規則文字的 cosine >= similar_at。
    """
    vectors = {
        rule.rule_id: writer.embed(rule.rule, operation_id=operation_id, node="curation")
        for rule in rules
    }

    scopes: dict[str, list[AuthoringRule]] = {}
    for rule in rules:
        scopes.setdefault(_scope_key(rule), []).append(rule)

    groups: list[list[str]] = []
    for _, members in sorted(scopes.items()):
        groups.extend(_group_within_scope(members, vectors, similar_at))
    return sorted(groups)
```

在 `analytics.py` 的 import 區補上：

```python
import json

from .writing.client import cosine
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：`uv run pytest tests/unit/test_analytics_curation.py -v`

預期：PASS，5 passed。

- [ ] **步驟 5：commit**

```bash
git add src/training_kb/analytics.py tests/unit/test_analytics_curation.py
git commit -m "feat(analytics): 加入相近規則分群供人工檢視"
```

---

### Task 7：載入核定批次並驗證規則（含 Lambda 動作）

**目的**：把前面六個 Task 串起來，讓維護者可以用一個指令完成「讀批次 → 算成效 → 判衝突 → 改狀態」。

**檔案**：
- 修改：`src/training_kb/analytics.py`
- 修改：`src/training_kb/handlers/analytics.py`
- 測試：`tests/integration/test_analytics_validate_rule.py`

**介面**：
- 消費（Phase 03）：`repo.get_object(key) -> bytes | None`、`repo.get_config_list(name, default) -> list[str]`
- 消費（Phase 09）：`repo.get_tutorial(slug)`、`repo.get_version(version_id)`
- 產出：
  - `analytics.BATCH_PREFIX = "operations/rule-batches/"`、`analytics.batch_key(batch_id) -> str`（**本階段新增**）
  - `analytics.load_seed_batch(repo, batch_id) -> SeedBatch`（**本階段新增**）
  - `analytics.RuleValidationReport`（**本階段新增**）
  - `analytics.validate_rule(repo, writer, rule_id, batch_ids, *, now, approved_categories=None) -> RuleValidationReport`（**本階段新增**）
  - `handlers.analytics.run_validate_rules(event, *, repo, writer, now) -> dict`（**本階段新增**）

批次檔放在 S3 的 `operations/rule-batches/<batch_id>.json`。設計文件 §9.3 把 `operations/` 定義為私有執行紀錄區，「規則驗證批次」就列在裡面（O2 建議）。**批次檔絕對不能放進 `site/`**。

觸發方式（維護者本機、已登入 AWS）：

```bash
aws lambda invoke \
  --function-name training-kb-analytics \
  --cli-binary-format raw-in-base64-out \
  --payload '{"action":"validate_rules","rule_id":"R-007","batch_ids":["b_r007_01"]}' \
  /tmp/out.json && cat /tmp/out.json
```

Phase 23 的 `demo/cli.py` 會再包一層更好用的子命令。

- [ ] **步驟 1：寫測試**

```python
# tests/integration/test_analytics_validate_rule.py
"""Phase 20 Task 7：從 S3 載入核定批次並完成規則驗證。"""

import json

import pytest
from moto import mock_aws

from training_kb.analytics import (
    batch_key,
    load_seed_batch,
    validate_rule,
)
from training_kb.clock import parse_iso
from training_kb.errors import PermanentError
from training_kb.handlers.analytics import run_validate_rules
from training_kb.models import AuthoringRule, RuleStatus, Tutorial, TutorialVersion
from training_kb.writing.client import FakeWriter

NOW = parse_iso("2026-09-13T08:30:00Z")


def _batch_payload(*, approved: bool = True) -> dict:
    feedback = []
    for index, (fid, user, rating) in enumerate(
        [
            ("f_12", "u_01", 2),
            ("f_15", "u_02", 2),
            ("f_19", "u_03", 3),
            ("f_23", "u_04", 3),
            ("f_27", "u_05", 3),
            ("f_31", "u_06", 3),
            ("f_34", "u_07", 3),
            ("f_40", "u_08", 4),
        ]
    ):
        feedback.append(
            {
                "id": fid,
                "tutorial_version": "prepare-meeting@v1",
                "rating": rating,
                "user": user,
                "category": "找不到按鈕",
                "comment": "第三步沒有指出按鈕在哪一頁與位置",
                "ts": "2026-08-02T12:00:00Z",
            }
        )
        del index
    feedback.append(
        {
            "id": "f_101",
            "tutorial_version": "prepare-meeting@v2",
            "rating": 2,
            "user": "u_01",
            "category": "缺少資訊",
            "comment": "資訊仍不夠完整",
            "ts": "2026-08-21T12:00:00Z",
        }
    )
    feedback.append(
        {
            "id": "f_102",
            "tutorial_version": "prepare-meeting@v2",
            "rating": 2,
            "user": "u_02",
            "category": "缺少資訊",
            "comment": "資訊仍不夠完整",
            "ts": "2026-08-21T12:00:00Z",
        }
    )
    for number in range(3, 11):
        feedback.append(
            {
                "id": f"f_1{number:02d}",
                "tutorial_version": "prepare-meeting@v2",
                "rating": 5,
                "user": f"u_{number:02d}",
                "category": None,
                "comment": None,
                "ts": "2026-08-21T12:00:00Z",
            }
        )

    views = []
    for number in range(1, 11):
        views.append(
            {
                "tutorial_version": "prepare-meeting@v1",
                "user": f"u_{number:02d}",
                "ts": "2026-08-02T09:00:00Z",
            }
        )
        views.append(
            {
                "tutorial_version": "prepare-meeting@v2",
                "user": f"u_{number:02d}",
                "ts": "2026-08-21T09:00:00Z",
            }
        )

    tickets = []
    for number in range(1, 8):
        tickets.append(
            {
                "id": f"t_200{number}",
                "source": "email",
                "text": "看過準備會議教學後，仍找不到第三步的按鈕",
                "author": f"u_{number:02d}",
                "ts": "2026-08-03T10:00:00Z",
                "project_id": "demo-project",
                "cluster_id": "c12",
            }
        )
    for number in range(1, 3):
        tickets.append(
            {
                "id": f"t_210{number}",
                "source": "email",
                "text": "看過準備會議教學後，仍找不到第三步的按鈕",
                "author": f"u_{number:02d}",
                "ts": "2026-08-22T10:00:00Z",
                "project_id": "demo-project",
                "cluster_id": "c12",
            }
        )

    return {
        "batch_id": "b_r007_01",
        "rule_id": "R-007",
        "slug": "prepare-meeting",
        "before_version": "prepare-meeting@v1",
        "after_version": "prepare-meeting@v2",
        "feedback": feedback,
        "views": views,
        "tickets": tickets,
        "approved": approved,
        "cluster_id": "c12",
        "published_before": "2026-08-01T00:00:00Z",
        "published_after": "2026-08-20T00:00:00Z",
    }


def _seed_rule(repository) -> None:
    repository.put_rule(
        AuthoringRule(
            rule_id="R-007",
            rule="點選 UI 的步驟必須寫出所在頁面、按鈕位置與點擊後會看到的結果。",
            applies_when={"step.type": "click_ui"},
            evidence=["f_12", "f_15", "f_19", "f_23", "f_27", "f_31", "f_34", "f_40"],
            status=RuleStatus.candidate,
            applied_to=[],
            derived_from="prepare-meeting@v1",
        )
    )
    repository.put_tutorial(
        Tutorial(
            slug="prepare-meeting",
            current_version="prepare-meeting@v2",
            topic="準備會議",
            feature_ids=["Prepare"],
            status="active",
            successor=None,
            cluster_id="c12",
        )
    )
    for number, published in ((1, "2026-08-01T00:00:00Z"), (2, "2026-08-20T00:00:00Z")):
        repository.put_meta(
            f"VERSION#prepare-meeting@v{number}",
            {
                "entity": "VERSION",
                "version_id": f"prepare-meeting@v{number}",
                "supersedes": None if number == 1 else "prepare-meeting@v1",
                "reason": "gap:c12" if number == 1 else "feedback:8 則 找不到按鈕",
                "rules_applied": [] if number == 1 else ["R-007"],
                "s3_key": f"tutorials/prepare-meeting/v{number}.md",
                "published_at": published,
            },
        )


@mock_aws
def test_載入批次後_candidate_升為_active(repository):
    _seed_rule(repository)
    repository.put_object(
        batch_key("b_r007_01"),
        json.dumps(_batch_payload(), ensure_ascii=False),
        content_type="application/json",
    )
    writer = FakeWriter(outputs=[])

    report = validate_rule(repository, writer, "R-007", ["b_r007_01"], now=NOW)

    assert report.before_status == RuleStatus.candidate
    assert report.after_status == RuleStatus.active
    assert report.changed is True
    assert report.evaluations[0].decidable is True
    assert report.evaluations[0].before.avg == 2.875
    assert report.evaluations[0].after.avg == 4.4
    assert report.evaluations[0].before.reopen.rate == 0.7
    assert report.evaluations[0].after.reopen.rate == 0.2

    stored = repository.get_rule("R-007")
    assert stored.status == RuleStatus.active
    assert stored.validated_at == "2026-09-13T08:30:00Z"


@mock_aws
def test_未核定批次時狀態不變(repository):
    _seed_rule(repository)
    repository.put_object(
        batch_key("b_r007_01"),
        json.dumps(_batch_payload(approved=False), ensure_ascii=False),
        content_type="application/json",
    )
    writer = FakeWriter(outputs=[])

    report = validate_rule(repository, writer, "R-007", ["b_r007_01"], now=NOW)

    assert report.after_status == RuleStatus.candidate
    assert report.changed is False
    assert any("尚未人工核定" in note for note in report.notes)
    assert repository.get_rule("R-007").status == RuleStatus.candidate


@mock_aws
def test_批次檔不存在時拋出_PermanentError(repository):
    _seed_rule(repository)
    writer = FakeWriter(outputs=[])

    with pytest.raises(PermanentError) as info:
        validate_rule(repository, writer, "R-007", ["b_missing"], now=NOW)

    assert "b_missing" in str(info.value)


@mock_aws
def test_批次的_rule_id_不符時拋出_PermanentError(repository):
    _seed_rule(repository)
    payload = _batch_payload()
    payload["rule_id"] = "R-999"
    repository.put_object(
        batch_key("b_r007_01"),
        json.dumps(payload, ensure_ascii=False),
        content_type="application/json",
    )
    writer = FakeWriter(outputs=[])

    with pytest.raises(PermanentError) as info:
        validate_rule(repository, writer, "R-007", ["b_r007_01"], now=NOW)

    assert "R-999" in str(info.value)


@mock_aws
def test_load_seed_batch_可以讀回完整批次(repository):
    repository.put_object(
        batch_key("b_r007_01"),
        json.dumps(_batch_payload(), ensure_ascii=False),
        content_type="application/json",
    )

    batch = load_seed_batch(repository, "b_r007_01")

    assert batch.batch_id == "b_r007_01"
    assert len(batch.feedback) == 18
    assert len(batch.views) == 20
    assert len(batch.tickets) == 9
    assert batch.approved is True


@mock_aws
def test_handler_動作回傳可序列化的報告(repository):
    _seed_rule(repository)
    repository.put_object(
        batch_key("b_r007_01"),
        json.dumps(_batch_payload(), ensure_ascii=False),
        content_type="application/json",
    )
    writer = FakeWriter(outputs=[])

    result = run_validate_rules(
        {"action": "validate_rules", "rule_id": "R-007", "batch_ids": ["b_r007_01"]},
        repo=repository,
        writer=writer,
        now=NOW,
    )

    assert result["status"] == "ok"
    assert result["report"]["after_status"] == "active"
    json.dumps(result, ensure_ascii=False)  # 必須可序列化，Lambda 才能回傳
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：`uv run pytest tests/integration/test_analytics_validate_rule.py -v`

預期：FAIL，`ImportError: cannot import name 'batch_key' from 'training_kb.analytics'`。

- [ ] **步驟 3：寫最少的程式讓測試通過**

在 `src/training_kb/analytics.py` 的 Task 6 區塊後面加入：

```python
BATCH_PREFIX = "operations/rule-batches/"


def batch_key(batch_id: str) -> str:
    """核定種子批次的 S3 key（設計文件 §9.3：operations/ 是私有執行紀錄區）。"""
    return f"{BATCH_PREFIX}{batch_id}.json"


def load_seed_batch(repo: "Repository", batch_id: str) -> SeedBatch:
    """從 S3 讀回一個核定種子批次。缺檔或格式不合法都是 PermanentError。"""
    raw = repo.get_object(batch_key(batch_id))
    if raw is None:
        raise PermanentError(
            f"找不到核定批次 {batch_id}（S3 key: {batch_key(batch_id)}）"
        )
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PermanentError(f"核定批次 {batch_id} 不是合法 JSON：{exc}") from exc

    batch = SeedBatch.model_validate(data)
    if batch.batch_id != batch_id:
        raise PermanentError(
            f"核定批次檔內的 batch_id 是 {batch.batch_id}，與要求的 {batch_id} 不符"
        )
    return batch


@dataclass
class RuleValidationReport:
    """一次規則驗證的完整結果，給維護者看，也給 Lambda 回傳。"""

    rule_id: str
    before_status: RuleStatus
    after_status: RuleStatus
    changed: bool
    evaluations: list[RuleEvaluation]
    conflict: ConflictJudgement | None
    conflict_problems: list[str]
    notes: list[str]

    def to_dict(self) -> dict:
        return {
            "rule_id": self.rule_id,
            "before_status": str(self.before_status),
            "after_status": str(self.after_status),
            "changed": self.changed,
            "evaluations": [
                {
                    "batch_id": evaluation.batch_id,
                    "decidable": evaluation.decidable,
                    "avg_improved": evaluation.avg_improved,
                    "reopen_improved": evaluation.reopen_improved,
                    "before": {
                        "version_id": evaluation.before.version_id,
                        "avg": evaluation.before.avg,
                        "n": evaluation.before.n,
                        "negative": evaluation.before.negative,
                        "reopen_count": evaluation.before.reopen.count,
                        "reopen_users": evaluation.before.reopen.reopen_users,
                        "viewers": evaluation.before.reopen.viewers,
                        "rate": evaluation.before.reopen.rate,
                    },
                    "after": {
                        "version_id": evaluation.after.version_id,
                        "avg": evaluation.after.avg,
                        "n": evaluation.after.n,
                        "negative": evaluation.after.negative,
                        "reopen_count": evaluation.after.reopen.count,
                        "reopen_users": evaluation.after.reopen.reopen_users,
                        "viewers": evaluation.after.reopen.viewers,
                        "rate": evaluation.after.reopen.rate,
                    },
                }
                for evaluation in self.evaluations
            ],
            "conflict": None if self.conflict is None else self.conflict.model_dump(),
            "conflict_problems": list(self.conflict_problems),
            "notes": list(self.notes),
        }


def _undecidable_evaluation(batch: SeedBatch) -> RuleEvaluation:
    """缺比較脈絡時用的佔位結果：一律不可判定。"""
    empty = ReopenStats(count=0, reopen_users=0, viewers=0, rate=None)
    return RuleEvaluation(
        batch_id=batch.batch_id,
        before=VersionMetrics(
            version_id=batch.before_version, avg=None, n=0, negative=0, reopen=empty
        ),
        after=VersionMetrics(
            version_id=batch.after_version, avg=None, n=0, negative=0, reopen=empty
        ),
        avg_improved=False,
        reopen_improved=False,
        decidable=False,
    )


def _batch_context(
    repo: "Repository", batch: SeedBatch
) -> tuple[str | None, str | None, str | None]:
    """取得批次的比較脈絡：批次自己帶的優先，缺的才回頭查圖譜。"""
    cluster_id = batch.cluster_id
    if cluster_id is None:
        tutorial = repo.get_tutorial(batch.slug)
        cluster_id = None if tutorial is None else tutorial.cluster_id

    published_before = batch.published_before
    if published_before is None:
        version = repo.get_version(batch.before_version)
        published_before = None if version is None else version.published_at

    published_after = batch.published_after
    if published_after is None:
        version = repo.get_version(batch.after_version)
        published_after = None if version is None else version.published_at

    return cluster_id, published_before, published_after


def validate_rule(
    repo: "Repository",
    writer: "Writer",
    rule_id: str,
    batch_ids: list[str],
    *,
    now: datetime,
    approved_categories: list[str] | None = None,
) -> RuleValidationReport:
    """載入核定批次、重算成效、判衝突，必要時寫入新的規則狀態。

    設計文件 §12.2：狀態變更只在完整核定種子批次中執行。
    batch_ids 的順序就是時間順序，next_status 依這個順序判斷「連續兩批」。
    """
    rule = repo.get_rule(rule_id)
    if rule is None:
        raise PermanentError(f"找不到規則 {rule_id}")

    categories = approved_categories
    if categories is None:
        categories = repo.get_config_list(
            "approved_categories", list(APPROVED_CATEGORIES_DEFAULT)
        )

    notes: list[str] = []
    evaluations: list[RuleEvaluation] = []
    for batch_id in batch_ids:
        batch = load_seed_batch(repo, batch_id)
        if batch.rule_id != rule_id:
            raise PermanentError(
                f"批次 {batch_id} 的 rule_id 是 {batch.rule_id}，不是 {rule_id}"
            )
        if not batch.approved:
            notes.append(f"批次 {batch_id} 尚未人工核定（approved=false），不可判定（O7）")

        cluster_id, published_before, published_after = _batch_context(repo, batch)
        if cluster_id is None or published_before is None or published_after is None:
            notes.append(
                f"批次 {batch_id} 缺少 cluster_id 或前後版的 published_at，視為不可判定"
            )
            evaluations.append(_undecidable_evaluation(batch))
            continue

        evaluations.append(
            evaluate_batch(
                batch,
                cluster_id=cluster_id,
                published_before=published_before,
                published_after=published_after,
                approved_categories=categories,
            )
        )

    conflict: ConflictJudgement | None = None
    conflict_problems: list[str] = []
    if rule.status == RuleStatus.candidate:
        conflict, conflict_problems = judge_conflict(
            repo, writer, rule, operation_id=f"analytics:validate:{rule_id}"
        )
        notes.extend(conflict_problems)

    verified = conflict if (conflict is not None and not conflict_problems) else None
    target = next_status(rule.status, evaluations, verified)
    changed = target != rule.status
    if changed:
        apply_rule_status(repo, rule_id, target, now=now)

    return RuleValidationReport(
        rule_id=rule_id,
        before_status=rule.status,
        after_status=target,
        changed=changed,
        evaluations=evaluations,
        conflict=conflict,
        conflict_problems=conflict_problems,
        notes=notes,
    )
```

在 `analytics.py` 的 import 區補上：

```python
from .models import APPROVED_CATEGORIES_DEFAULT
```

接著修改 `src/training_kb/handlers/analytics.py`。**在檔案結尾**加入這段（Phase 19 建立的 `handler` 與其他函式都不要動）：

```python
# ---------------------------------------------------------------------------
# Phase 20：載入核定批次並驗證規則
# ---------------------------------------------------------------------------

from ..analytics import validate_rule  # noqa: E402
from ..errors import PermanentError  # noqa: E402


def run_validate_rules(event: dict, *, repo, writer, now) -> dict:
    """由維護者用 boto3 invoke 或 demo/cli.py 觸發的規則驗證動作。

    event 範例：
      {"action": "validate_rules", "rule_id": "R-007", "batch_ids": ["b_r007_01"]}
    batch_ids 的順序就是時間順序。
    """
    rule_id = event.get("rule_id")
    if not rule_id:
        raise PermanentError("validate_rules 需要 rule_id")
    batch_ids = list(event.get("batch_ids") or [])

    report = validate_rule(repo, writer, rule_id, batch_ids, now=now)
    return {"status": "ok", "action": "validate_rules", "report": report.to_dict()}
```

最後把 `validate_rules` 接到既有的 `handler`。找到 Phase 19 寫的 `def handler(event, context)`，在它分派動作的地方加入這兩行（其餘保持原樣）：

```python
    if event.get("action") == "validate_rules":
        settings = load_settings()
        trace = CallTrace()
        return run_validate_rules(
            event,
            repo=build_repository(settings),
            writer=build_writer(settings, trace),
            now=now_utc(),
        )
```

`handlers/analytics.py` 的 import 區需要有（Phase 19 多半已經有 `load_settings`、`build_repository`、`now_utc`，缺哪個就補哪個）：

```python
from ..clock import now_utc
from ..config import load_settings
from ..repository import build_repository
from ..writing.client import CallTrace, build_writer
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：`uv run pytest tests/integration/test_analytics_validate_rule.py -v`

預期：PASS，6 passed。

再跑全部：

```bash
uv run pytest -q
uv run ruff check .
```

預期：全部 PASS，ruff 沒有錯誤。

- [ ] **步驟 5：commit**

```bash
git add src/training_kb/analytics.py src/training_kb/handlers/analytics.py tests/integration/test_analytics_validate_rule.py
git commit -m "feat(analytics): 載入核定批次並完成規則驗證動作"
```

---

## 7. 完成檢查清單

對應設計文件第 16 節切片 S7 的手動檢查「原始資料重算成效，R-007 由 Analytics 啟用，再供後續寫作使用」。

- [ ] `uv run pytest -q` 全部通過，`uv run ruff check .` 沒有錯誤。
- [ ] `analytics.py` 內能 import 到：`SeedBatch`、`RuleEvaluation`、`metrics_from_records`、`evaluate_batch`、`next_status`、`apply_rule_status`、`verify_conflict_judgement`、`judge_conflict`、`curation_groups`、`batch_key`、`load_seed_batch`、`RuleValidationReport`、`validate_rule`。
- [ ] 全專案搜尋確認只有 `apply_rule_status` 會改規則狀態：
  ```bash
  rg -n 'status.*RuleStatus\.(active|retired)' src/training_kb --glob '!analytics.py'
  ```
  預期：沒有輸出，或輸出的都只是「讀取／篩選」而不是寫入。
- [ ] 兩項都改善才啟用；只改善一項或持平不啟用（`test_analytics_next_status.py` 前四個測試）。
- [ ] 未核定或缺資料的批次保持原狀（`test_未核定批次時狀態不變`、`test_不完整批次保持原狀`）。
- [ ] 連續兩個**不重疊**核定批次都未改善才退役；重疊的兩批不退役。
- [ ] 衝突判定只退役 candidate，不動既有 active。
- [ ] `curation_groups` 跑完後規則資料一字未改。
- [ ] 手動確認報告數字可重算：用 Phase 21 的種子跑一次
  ```bash
  uv run python -c "
  import json
  from training_kb.clock import now_utc
  from training_kb.config import load_settings
  from training_kb.repository import build_repository
  from training_kb.writing.client import CallTrace, build_writer
  from training_kb.analytics import validate_rule
  s = load_settings(); t = CallTrace()
  r = validate_rule(build_repository(s), build_writer(s, t), 'R-007', ['b_r007_01'], now=now_utc())
  print(json.dumps(r.to_dict(), ensure_ascii=False, indent=2))
  "
  ```
  預期在輸出中看到 `"avg": 2.875`、`"avg": 4.4`、`"rate": 0.7`、`"rate": 0.2`、`"after_status": "active"`。
- [ ] 報告內每個數字都能說出來源（哪幾筆 Feedback、哪幾筆 View、哪幾筆 Ticket），沒有寫死的展示值。

---

## 8. 常見錯誤與排除

**症狀 1：`test_兩項都改善時兩個旗標都是_True` 失敗，`before.reopen.rate` 是 `None`。**
原因：`reopen_stats()` 需要 `published_at` 落在瀏覽與工單之前，而且 Ticket 的 `cluster_id` 要等於傳入的 `cluster_id`。多半是 `published_before` 傳錯（例如傳成 after 的時間），導致 v1 的瀏覽落在窗口外、分母變 0。
解法：檢查 `evaluate_batch` 呼叫時 `published_before` 對應的是 `batch.before_version`。在測試裡印出 `result.before.reopen.viewers`，若是 0 就是窗口設錯。

**症狀 2：`ImportError: cannot import name 'ConflictJudgement' from 'training_kb.writing.schemas'`。**
原因：`ConflictJudgement` 在簡報第 6.4 節列出，但註明「各階段補」，本階段才真正建立。
解法：照 Task 3 步驟 3 的第一段，把 schema 加到 `writing/schemas.py`，並確認檔案開頭有 `from pydantic import BaseModel`。

**症狀 3：`validate_rule` 把 candidate 意外退役了。**
原因：`judge_conflict` 呼叫到真的 Bedrock，模型回了 `conflicts=True`，而且剛好通過程式驗證；或是測試裡 `FakeWriter` 的 `outputs` 排了一個衝突判定。
解法：先看報告的 `conflict` 與 `conflict_problems`。如果 `conflict_problems` 是空的，代表判定通過了驗證——檢查同 `applies_when` 的 active 規則是不是真的該衝突（例如 Phase 21 的 R-012 若誤設成 `click_ui`，就會跟 R-007 撞範圍）。把 R-012 的 `applies_when` 改成不同範圍即可。

**症狀 4：`test_applied_to_由_rules_applied_重建且去重保序` 失敗，順序被打亂。**
原因：用了 `sorted(set(...))`。`set` 不保證順序，排序後也會改掉原順序。
解法：照 Task 4 的寫法，用 `seen` 集合搭配 list 逐筆過濾，保留 `repo.list_versions_applying_rule()` 給的順序。

**症狀 5：`AttributeError: 'NoneType' object has no attribute 'cluster_id'`。**
原因：`_batch_context` 回頭查圖譜時，`repo.get_tutorial(batch.slug)` 找不到教學（例如批次用的是只存在於批次檔裡的合成 slug）。
解法：在批次檔裡直接填 `cluster_id`、`published_before`、`published_after` 三個欄位。`_batch_context` 會優先用批次自己帶的值，不再回頭查圖譜。

**症狀 6：`uv run ruff check .` 抱怨 `E402 module level import not at top of file`（`handlers/analytics.py`）。**
原因：Task 7 把 import 放在檔案結尾的區塊裡。
解法：程式碼裡已經加了 `# noqa: E402`；若你把 import 搬到檔案最上方，就把 `# noqa: E402` 拿掉。兩種做法都可以，選一種就好。

**症狀 7：`moto` 測試回報 `ResourceNotFoundException: Requested resource not found`。**
原因：`repository` fixture 沒有被 `@mock_aws` 包住，或 fixture 本身沒有建立 table／bucket。
解法：確認 Phase 03 的 `tests/conftest.py` 提供 `repository` fixture，而且測試函式上有 `@mock_aws`。

---

## 9. 這階段不做的事

| 不做的事 | 留給哪一階段 |
|---|---|
| 準備 R-007、R-012 的實際批次 JSON 內容 | Phase 21（`21-Phase21-Demo種子資料與可重算驗證.md`）。本階段只定義格式與讀取方式。 |
| 提出新的 candidate 規則 | Phase 18。設計文件 §7.6 明說 Analytics 不提出規則。 |
| 把 active 規則注入寫作 prompt | Phase 06 的 `writing/rules.py` 已完成。 |
| 用線上（非種子）資料自動驗證規則 | 不做。F32 決定 MVP 只在完整核定種子批次判定。 |
| 自動合併相近規則、搬移 evidence 或改寫規則文字 | 不做。F34 決定 MVP 只分群供人檢視。 |
| 退役既有 active 規則以讓路給新 candidate | 不做。設計文件 §12.2 明說不覆蓋既有 active。 |
| 多組版本配對的重開票率彙總權重 | 不做。設計文件 §12.1 明說彙總權重尚未定義，先逐組顯示（對應 O4）。 |
| Dashboard 呈現規則狀態與來源證據 | Phase 23（`23-Phase23-Demo控制台與Dashboard.md`）。 |
| 把 Analytics Lambda 部署上去、給它 IAM 權限 | Phase 14／Phase 19 的 CDK 設定；本階段只加一個動作分支。 |

---

## 10. 對照：設計章節與 Rule 編號

| Rule 來源檔 | Rule 編號與原文 | 本階段哪個 Task 落實 |
|---|---|---|
| `驗證教學規則.feature` | Rule 1：規則成效比較套用組與同一篇教學套用前的已發布版本 | Task 2（`evaluate_batch` 以批次的 `before_version` 為對照，不跨教學湊對） |
| `驗證教學規則.feature` | Rule 2：candidate 僅在平均評分嚴格提高且重開票率嚴格下降時升為 active | Task 2（算兩個旗標）、Task 3（`next_status` 要求兩項同時成立） |
| `驗證教學規則.feature` | Rule 3：未載入完整核定種子驗證批次時不改變規則狀態 | Task 2（`approved=False` → `decidable=False`）、Task 3（沒有可判定批次維持原狀）、Task 7（未核定時寫入 notes 且不改狀態） |
| `驗證教學規則.feature` | Rule 4：與既有規則衝突的 candidate 規則變為 retired | Task 5（模型判定 + 程式驗證）、Task 3（只退役 candidate，不動 active） |
| `驗證教學規則.feature` | Rule 5：後來失效的 active 規則變為 retired | Task 3（`current=active` 也適用連續兩批未改善的退役條件） |
| `驗證教學規則.feature` | Rule 6：驗證無效的規則從可使用規則中退役 | Task 3（連續兩個不重疊批次都未改善 → retired；持平視為未改善）、Task 4（寫回 status） |
| `驗證教學規則.feature` | Rule 7：curation 合併相近教學規則 | Task 6（MVP 只建立相近群組供人工檢視，不合併 ID／證據／status） |
| `驗證教學規則.feature` | Rule 8：Analytics 寫入教學規則的驗證後 status | Task 4（`apply_rule_status` 是唯一寫入點） |
| `檢視學習指標.feature` | Rule 6：規則效果比較套用與未套用版本的評分及同題重開票率差 | Task 2（before／after 兩組 `VersionMetrics`；零分母不用於驗證） |
| `檢視學習指標.feature` | Rule 8：規則套用次數等於 applied_to 清單長度 | Task 4（以 `rules_applied` 重建 `applied_to` 並去重） |
| `套用教學規則.feature` | Rule 6：套用規則的版本記錄於規則的 applied_to | Task 4（`apply_rule_status` 以 `repo.list_versions_applying_rule()` 重建 `applied_to`） |
| `套用教學規則.feature` | Rule 2：一般寫作路徑只取得 status 為 active 的規則 | Task 4（本階段只負責把狀態寫對；篩選由 Phase 06 的 `select_active_rules` 執行） |

---

## 11. 參考來源

### 設計文件章節（`docs/design/training-kb.md`）

- §7.6 共用寫作與 Analytics 的內部介面：衝突判定的輸入輸出與程式必須驗證的三件事；Analytics 不提出規則。
- §8.2 create_version 的完成條件：`rules_applied` 是套用關係的權威，`applied_to` 與 `APPLIED_TO` 邊由它重建。
- §9.3 S3 與執行資訊：`operations/` 是私有執行紀錄區，規則驗證批次存放在此。
- §11.2、§11.3 可重算的評分／瀏覽／重開票配方：2.875、4.4、7、2、70%、20% 的來源。
- §11.4 讓規則轉移的順序正確：本階段第 5.4 節的 ASCII 圖來源。
- §12.1 指標公式：平均評分、負面回饋、重開票筆數與率、規則計數、套用次數。
- §12.2 規則驗證：狀態機、兩項嚴格改善、連續兩批未改善、衝突判定、curation 範圍。
- §12.3 指標不能替代的證據：不宣稱因果，不為配合表格刪掉呼叫。
- §15 測試與驗收設計「規則驗證」列：兩項都改善才啟用；持平、單項改善不啟用；不完整批次保持原狀；連續兩個不重疊未改善批次才退役。
- §16 交付切片 S7。
- §18 待確認事項 O4（時間與比較邊界）、O7（核定種子）。
- §19.2 功能決策 F27、F28、F30、F31、F32、F33、F34、F55。
- §19.1 資料決策 D15（evidence 只存 Feedback ID）、D16（applies_when 只支援 step.type 單一條件）、D17（rules_applied 為權威）、D18（derived_from 恰好一個）、D27（跨專案共享只接受明示合成種子證據）。
- §20.13 逐條 Rule 與負責模組（驗證教學規則 8 條）。

### 規格檔

- `docs/spec/features/驗證教學規則.feature`（8 條 Rule，含 R-012 退役的 Example）
- `docs/spec/features/檢視學習指標.feature`（Rule 6、Rule 8）
- `docs/spec/features/套用教學規則.feature`（Rule 2、Rule 6）
- `docs/spec/erm.dbml`（`AUTHORING_RULE` 欄位與 note）

### 外部官方文件

- DynamoDB 讀取一致性（基表可一致讀、GSI 不行）：<https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/HowItWorks.ReadConsistency.html>
- DynamoDB 分頁（Query／Scan 必須讀完 `LastEvaluatedKey`）：<https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/Query.Pagination.html>
- Lambda 以 `invoke` 呼叫（維護者本機觸發用）：<https://docs.aws.amazon.com/lambda/latest/dg/API_Invoke.html>
- Bedrock Claude Messages 請求參數（`temperature`、`max_tokens`）：<https://docs.aws.amazon.com/bedrock/latest/userguide/model-parameters-anthropic-claude-messages-request-response.html>
- Amazon Titan Text Embeddings V2 請求／回應格式（`curation_groups` 用到的 `embed`）：<https://docs.aws.amazon.com/bedrock/latest/userguide/model-parameters-titan-embed-text.html>（經本次查證：V2 request 為 `{"inputText": string, "dimensions": int, "normalize": boolean, "embeddingTypes": list}`，response 為 `{"embedding": [float...], "inputTextTokenCount": int, "embeddingsByType": {...}}`）
