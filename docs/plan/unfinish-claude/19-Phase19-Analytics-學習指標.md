# Phase 19：Analytics 學習指標

| 項目 | 內容 |
|---|---|
| 上一階段 | Phase 18：Feedback Review 候選規則與每日排程（`18-Phase18-Feedback-Review-候選規則與每日排程.md`） |
| 下一階段 | Phase 20：規則驗證與狀態轉換（`20-Phase20-規則驗證與狀態轉換.md`） |
| 對應設計文件章節 | §11.2、§11.3、§12.1、§12.3、§13（`docs/design/training-kb.md`） |
| 對應交付切片 | S7（設計文件第 16 節） |
| 預估時間 | 約 5 小時 |
| 做完會得到 | 一組能從原始回饋、瀏覽與工單重算出 2.9／4.4／8／2／7／2／70%／20% 的指標函式，以及回傳 Dashboard JSON 的 Analytics Lambda |

---

## 1. 這階段做完會得到什麼

前面幾個階段一直在「產生」資料：教學版本、回饋、瀏覽紀錄、工單、規則。這一階段做的是**把它們算成看得懂的數字**，而且每個數字都要能從原始資料重算出來，不是寫死在畫面上的展示值（F46）。

做完會多出：

- `src/training_kb/analytics.py` 的指標部分：
  - 每版平均評分 `average_rating`、跨版等權平均 `cross_version_average`
  - 負面回饋 `negative_feedback_ids`
  - 同題重開票 `reopen_window`、`ReopenStats`、`reopen_stats`
  - 規則計數 `rule_counts`、套用次數 `applied_count`、模型呼叫數 `bedrock_call_count`
  - 單版彙總 `VersionMetrics`、`version_metrics`
  - Dashboard 的完整 JSON `dashboard_payload`
- `src/training_kb/handlers/analytics.py`：把上面那份 JSON 包成 Lambda handler。
- 兩個測試檔，用設計文件 §11.2／§11.3 的資料當 fixture，驗證每一個目標數字。

**特別注意**：這一階段**只算**，不寫任何規則狀態。把 candidate 變成 active、把規則退役，是 Phase 20 的事（設計文件 §12.2：「只有 Analytics 能寫驗證後狀態」，但寫入的程式碼在下一階段）。

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
                                                              ^^^^^^^^^^^^^^^^^^
                                                                   你在這裡
                                                                                        |
展示與驗收層    21 Demo 種子資料 -> 22 靜態教學站 -> 23 Demo 控制台 -> 24 失敗復原驗收 -> 25 安全與當日準備
```

資料從哪裡來、算完之後給誰看：

```text
     Phase 13      Phase 15         Phase 15        Phase 07/08      Phase 18
    TICKET        FEEDBACK       TUTORIAL_VIEW   TUTORIAL_VERSION      RULE
       |              |                |                 |              |
       +------+-------+--------+-------+--------+--------+------+-------+
              |                |                |               |
              v                v                v               v
      +--------------------------------------------------------------------+
      |  analytics.py（本階段）                                             |
      |  average_rating / negative_feedback_ids / reopen_stats /            |
      |  rule_counts / applied_count / version_metrics / dashboard_payload  |
      +----------------------------+---------------------------------------+
                                   |
              +--------------------+--------------------+
              v                                         v
     handlers/analytics.py                        Phase 20 規則驗證
     （Lambda，回傳 Dashboard JSON）              （evaluate_batch 會用
              |                                    VersionMetrics 做前後對照）
              v
     Phase 23 Streamlit Dashboard
```

---

## 3. 開始前檢查

- [ ] **檢查 1：專案測試是綠的**

執行：

```bash
cd ~/AWS-Hackathon
uv run pytest tests/unit -q
```

預期：全部通過（`test_infra_feedback_review.py` 若沒有 `cdk.out` 會顯示 skipped，正常）。

- [ ] **檢查 2：Phase 02 的模型欄位齊全**

執行：

```bash
uv run python - <<'PY'
from training_kb.models import (
    APPROVED_CATEGORIES_DEFAULT, PENDING_CATEGORY,
    AuthoringRule, Feedback, Ticket, Tutorial, TutorialVersion, TutorialView,
    parse_version_id,
)
print("核定類別：", APPROVED_CATEGORIES_DEFAULT, "／待分類：", PENDING_CATEGORY)
print("Feedback 欄位：", sorted(Feedback.model_fields))
print("TutorialView 欄位：", sorted(TutorialView.model_fields))
print("Ticket 欄位：", sorted(Ticket.model_fields))
print("parse_version_id：", parse_version_id("prepare-meeting@v2"))
PY
```

預期：核定類別是 `['找不到按鈕', '缺少資訊']`、待分類是 `待分類`；`Feedback` 有 `category`、`rating`、`user`、`ts`；`TutorialView` 有 `tutorial_version`、`user`、`ts`；`Ticket` 有 `author`、`cluster_id`、`ts`、`project_id`；最後一行是 `('prepare-meeting', 2)`。

- [ ] **檢查 3：Phase 01 的時間工具在**

執行：

```bash
uv run python -c "from training_kb.clock import now_utc, parse_iso, to_iso; print(parse_iso('2026-08-01T00:00:00Z'))"
```

預期：印出 `2026-08-01 00:00:00+00:00`（帶時區，不是 naive）。

- [ ] **檢查 4：Repository 有本階段要用的讀取方法**

執行：

```bash
uv run python - <<'PY'
from training_kb.repository import Repository
need = [
    "get_version", "get_tutorial", "list_versions_of_tutorial",
    "list_feedback_of_version", "list_views_of_version", "list_tickets",
    "list_rules", "get_config_list", "scan_entity",
]
print("缺少：", [n for n in need if not hasattr(Repository, n)])
PY
```

預期：印出 `缺少： []`。若不是空的，回去補 Phase 09（`09-Phase09-圖譜查詢與backfill.md`）。

- [ ] **檢查 5：Phase 05 的 CallTrace 在**

執行：

```bash
uv run python -c "from training_kb.writing.client import CallRecord, CallTrace; t=CallTrace(); print(t.count())"
```

預期：印出 `0`。

- [ ] **檢查 6：handlers 目錄在**

執行：

```bash
ls -l src/training_kb/handlers/
```

預期：看到 `__init__.py`、`webhook.py`、`import_.py`、`pipeline_task.py`。本階段會新增 `analytics.py`。

- [ ] **檢查 7：`analytics.py` 目前的內容**

執行：

```bash
ls -l src/training_kb/analytics.py 2>/dev/null || echo "尚未建立"
```

預期：印出 `尚未建立`。如果檔案已經存在，先打開看它有什麼；本階段從指標函式開始往裡面加。

---

## 4. 名詞小抄

| 名詞 | 白話解釋 | 在本階段哪裡用到 |
|---|---|---|
| 指標（metric） | 從原始資料算出來的數字，例如「這一版平均 2.875 分」。 | 整個階段 |
| 有效回饋 | `rating` 是 1 到 5 的整數的那些回饋。只有評分、沒有類別沒有留言也算有效（D12）。 | `average_rating` 的分母 |
| 未四捨五入的值 | 內部判斷一律用原始小數（2.875），只有畫面上才顯示一位小數（2.9）。設計文件 §11.2 明講顯示位數不影響門檻。 | `avg` 與 `avg_display` 分開 |
| `None`（空值） | Python 表示「沒有值」的寫法。這裡代表「沒有資料可以算」，不是 0。 | 零評分的平均、零瀏覽的比例 |
| 跨版等權平均 | 先算每一版的平均，再把各版平均當成同樣重要求平均。**不是**把所有回饋混在一起算（F44）。 | `cross_version_average` |
| 核定問題類別 | 系統認可的問題分類，初始是「找不到按鈕」「缺少資訊」（D13）。 | 負面回饋判定 |
| 待分類 | 分類不出來時填的值。它**不因類別**計入負面（F43），但如果 `rating <= 2` 仍然照樣計入。 | `negative_feedback_ids` |
| 負面回饋數 | `rating <= 2` **或** 類別屬核定問題類別的回饋，**ID 去重後**的數量。同一筆兩個條件都中只算一次。 | `negative_feedback_ids` |
| TUTORIAL_VIEW（瀏覽紀錄） | 一筆「某人在某時間看過某一版」的紀錄。它是重開票率的分母來源（D24）。 | `reopen_stats` |
| cluster_id | 工單分群的識別碼，例如 `c12`。一篇教學的 cluster 來自它第一版的 `gap:<cluster_id>`，之後不變（D29）。 | 判斷是不是「同題」 |
| 穩定使用者 ID | `TutorialView.user`、`Feedback.user`、`Ticket.author` 用同一組值（例如 `u_01`），所以可以比對「同一個人」（D23）。 | `reopen_stats` |
| 重開票窗口 | 版本發布後的 14 天區間。**本計劃選擇（對應設計文件待確認事項 O4）**：`[p, p+14 天)`，左邊含、右邊不含。 | `reopen_window` |
| 同題重開票筆數 | 符合條件的**不同 Ticket ID** 數。可以比使用者數多。 | `ReopenStats.count` |
| 同題重開票率 | 符合條件的**不同開票使用者**數 ÷ 窗口內**不同瀏覽者**數。每版每人分子分母各最多一次。 | `ReopenStats.rate` |
| N/A | 分母是 0 時的顯示方式，代表樣本不足，不是改善也不是惡化（F42）。 | `format_rate(None)` |
| 規則套用次數 | 由各版本 `rules_applied` 重建、去重後的版本數（D17）。 | `applied_count` |
| Bedrock 呼叫數 | 每次實際送出的請求嘗試總數，包含重試、每個 Map 項目與 Rote 層呼叫（F45）。 | `bedrock_call_count` |
| CallTrace | Phase 05 建立的呼叫紀錄物件，每送一次請求就多一筆 `CallRecord`。 | `bedrock_call_count` |
| Lambda handler | AWS Lambda 的進入點函式，簽名固定是 `handler(event, context)`。 | `handlers/analytics.py` |
| S7 | 設計文件第 16 節的交付切片編號：「原始資料重算成效，R-007 由 Analytics 啟用」。本階段負責前半段。 | 第 7 節完成檢查 |
| O4 | 設計文件第 18 節的待確認事項：時間與比較邊界尚未由規格定義。 | 窗口端點 |

---

## 5. 設計說明

### 5.1 重開票率的時間軸

這是本階段最容易算錯的指標。先把定義攤開（設計文件 §12.1）：

> 對版本 v，發布時間為 p，窗口為發布後十四天。分母為該窗口內 TUTORIAL_VIEW 的不同 user；分子使用同一 user，要求存在 `view.ts < ticket.ts`，且 Ticket 位於相同窗口並符合 Tutorial.cluster_id。

用設計文件 §11.3 的 A v1 資料畫成時間軸：

```text
版本 prepare-meeting@v1   published_at p = 2026-08-01T00:00:00Z
窗口 [p, p + 14 天) = [2026-08-01T00:00:00Z, 2026-08-15T00:00:00Z)

  p                                                                p+14天
  |                                                                   |
  v                                                                   v
2026-08-01T00:00Z                                          2026-08-15T00:00Z
  |<================================ 窗口內 ========================)|
  |                                                                  |
  |          08-02T09:00Z                08-03T10:00Z                |
  |          u_01 ~ u_10 各一筆瀏覽       u_01 ~ u_07 各一張工單       |
  |          ● ● ● ● ● ● ● ● ● ●          ▲ ▲ ▲ ▲ ▲ ▲ ▲              |
  |          分母 = 10 個不同 user        cluster_id = c12            |
  |                                       每人 view.ts < ticket.ts    |
  |                                       分子 = 7 個不同 user        |
  |                                       筆數 = 7 張不同工單         |
  |                                                                  |
  端點「含」：08-01T00:00:00Z 的事件算在窗口內    端點「不含」：08-15T00:00:00Z 的事件不算

  ReopenStats(count=7, reopen_users=7, viewers=10, rate=0.7)
  顯示：重開票 7 筆、7／10、70%
```

A v2 同樣算法，換成 p = 2026-08-20T00:00:00Z、窗口 `[08-20, 09-03)`、10 個瀏覽者、u_01 與 u_02 兩張工單：

```text
  ReopenStats(count=2, reopen_users=2, viewers=10, rate=0.2)
  顯示：重開票 2 筆、2／10、20%
```

注意兩版的工單不會互相污染：A v1 的工單在 08-03，落在 A v2 的窗口 `[08-20, 09-03)` 之外；A v2 的工單在 08-22，落在 A v1 的窗口 `[08-01, 08-15)` 之外。

### 5.2 不計入分子的五種情況

設計文件 §11.3 要求這五種情況必須分開測，不能混進主表：

```text
情況                         資料                                    結果
------------------------------------------------------------------------------------
(1) 先開票、後瀏覽           08-02T08:00 開票                        分子不算
                             08-02T09:00 瀏覽                        （view.ts < ticket.ts 不成立，F41）

(2) 同一人重複瀏覽           u_01 在 08-02T09:00 與 08-02T15:00      分母只算 1 個人
                             各瀏覽一次                              （每版每人分母最多一次）

(3) 同一人開多張票           u_01 在窗口內開 t_2001 與 t_2002        分子使用者算 1 人
                                                                     筆數 count 算 2 張
                                                                     （筆數可以多於人數）

(4) 不同 cluster             ticket.cluster_id = "c99"               分子不算
                             教學的 cluster_id = "c12"               （不是同一個問題）

(5) 窗外時間                 08-15T00:00:00Z 開票（正好是右端點）    分子不算
                             08-14T23:59:59Z 開票                    分子算
                                                                     （右端點不含，O4 本計劃選擇）
```

判斷「同一人有沒有在開票前看過教學」時，我們取這個人在窗口內**最早的一筆瀏覽**來比。理由：定義寫的是「存在 `view.ts < ticket.ts`」，最早的那一筆最有機會成立，所以用它判斷不會漏掉真的符合條件的人。

### 5.3 空資料要顯示什麼

設計文件 §12.1 與 F42、F52 對空資料有明確規定，**不可以用 0 代替**：

```text
狀況                          內部值              畫面顯示              可不可以拿來驗證規則
--------------------------------------------------------------------------------------
該版沒有任何有效評分          avg = None          「尚無評分」          不可以（F52）
該版窗口內沒有任何瀏覽者      rate = None         「N/A（樣本不足）」   不可以（F42）
該版有瀏覽者但沒人重開票      rate = 0.0          「0%」                可以
該版平均剛好 0 筆負面回饋     negative = 0        「0」                 可以
沒有提供本次執行的呼叫紀錄    None                「未提供」            不適用
```

把 `None` 寫成 0 會讓 Phase 20 的規則驗證誤判成「改善了」，所以這一層一定要分清楚。

### 5.4 Dashboard 的四個區塊對應哪些函式

設計文件 §13 說 Dashboard 只需要四個區塊。本階段的 `dashboard_payload` 就是照這四塊組出來的：

```text
+---------------------------------------------------------------+
| 區塊 1：最新教學與版本差異                                     |
|   versions[].version_id / slug / published_at                 |
|   （diff 的連結由 Phase 22 的靜態站提供，本階段只給版本清單）  |
+---------------------------------------------------------------+
| 區塊 2：每版評分與回饋數                                       |
|   versions[].avg（未四捨五入）                                 |
|   versions[].avg_display（一位小數或「尚無評分」）             |
|   versions[].n、versions[].negative                           |
|   cross_version_average（等權平均）                            |
+---------------------------------------------------------------+
| 區塊 3：重開票筆數及分子／分母                                 |
|   versions[].reopen.count      重開票筆數（不同工單數）        |
|   versions[].reopen.reopen_users  分子（不同開票使用者）        |
|   versions[].reopen.viewers       分母（不同瀏覽者）            |
|   versions[].reopen.rate / rate_display                        |
+---------------------------------------------------------------+
| 區塊 4：規則狀態與來源證據                                     |
|   rule_counts = {"candidate": n, "active": n, "retired": n}   |
|   rules[].rule_id / status / applies_when / evidence /         |
|            derived_from / validated_at / applied_count         |
+---------------------------------------------------------------+
| 另外提供：bedrock_call_count（當次執行的實際呼叫數）            |
|           data_notice = "合成資料示範"（設計文件 §11.5）        |
+---------------------------------------------------------------+
```

### 5.5 本階段會新增的檔案與資料結構

```text
src/training_kb/
  analytics.py        << 新增（指標部分；Phase 20 會在同一檔案加規則驗證）
  handlers/
    analytics.py      << 新增
tests/unit/
  test_analytics_metrics.py    << 新增
  test_handlers_analytics.py   << 新增
```

`dashboard_payload` 回傳的 JSON 形狀：

```text
{
  "generated_at": "2026-09-14T00:30:00Z",
  "project_id": "demo-project",
  "approved_categories": ["找不到按鈕", "缺少資訊"],
  "data_notice": "合成資料示範",
  "versions": [
    {
      "version_id": "prepare-meeting@v1",
      "slug": "prepare-meeting",
      "published_at": "2026-08-01T00:00:00Z",
      "avg": 2.875,                 未四捨五入
      "avg_display": "2.9",         畫面用
      "n": 8,
      "negative": 8,
      "rules_applied": [],
      "reopen": {
        "count": 7,                 重開票筆數
        "reopen_users": 7,          分子
        "viewers": 10,              分母
        "rate": 0.7,
        "rate_display": "70%"
      }
    },
    { ... prepare-meeting@v2：avg 4.4、negative 2、reopen 2／10、20% ... }
  ],
  "cross_version_average": 3.6375,
  "cross_version_average_display": "3.6",
  "rule_counts": {"candidate": 1, "active": 0, "retired": 0},
  "rules": [
    {
      "rule_id": "R-007",
      "status": "candidate",
      "applies_when": {"step.type": "click_ui"},
      "evidence": ["f_12", "f_15", "f_19", "f_23", "f_27", "f_31", "f_34", "f_40"],
      "derived_from": "prepare-meeting@v1",
      "validated_at": null,
      "applied_count": 1
    }
  ],
  "bedrock_call_count": 3,
  "bedrock_call_source": "本次執行提供的 trace"
}
```

---

## 6. 工作項目

### Task 1：平均評分與跨版等權平均

**目的**：算每一版的平均分（沒有有效評分時回傳 `None`），以及多版之間的等權平均。

**檔案**：
- 新增：`src/training_kb/analytics.py`
- 測試：`tests/unit/test_analytics_metrics.py`

**介面**：
- 消費：`models.Feedback`（Phase 02）
- 產出：
  - `analytics.average_rating(feedback: list[Feedback]) -> float | None`
  - `analytics.cross_version_average(per_version: list[float | None]) -> float | None`
  - `analytics.format_rating(avg: float | None) -> str`（本階段新增，簡報第 6 節未列；供 Dashboard 顯示用）

- [ ] **步驟 1：寫測試**

建立 `tests/unit/test_analytics_metrics.py`：

```python
"""Phase 19：學習指標。fixture 來自設計文件 §11.2、§11.3。"""

from __future__ import annotations

import pytest

from training_kb.analytics import average_rating, cross_version_average, format_rating
from training_kb.models import Feedback

# 設計文件 §11.2：A v1 的八筆回饋（總分 23，平均 23/8 = 2.875）
A_V1_FEEDBACK_ROWS = [
    ("f_12", "u_01", 2, "找不到按鈕"),
    ("f_15", "u_02", 2, "找不到按鈕"),
    ("f_19", "u_03", 3, "找不到按鈕"),
    ("f_23", "u_04", 3, "找不到按鈕"),
    ("f_27", "u_05", 3, "找不到按鈕"),
    ("f_31", "u_06", 3, "找不到按鈕"),
    ("f_34", "u_07", 3, "找不到按鈕"),
    ("f_40", "u_08", 4, "找不到按鈕"),
]

# 設計文件 §11.2：A v2 的十筆回饋（總分 44，平均 44/10 = 4.4）
A_V2_FEEDBACK_ROWS = [
    ("f_101", "u_01", 2, "缺少資訊"),
    ("f_102", "u_02", 2, "缺少資訊"),
    ("f_103", "u_03", 5, None),
    ("f_104", "u_04", 5, None),
    ("f_105", "u_05", 5, None),
    ("f_106", "u_06", 5, None),
    ("f_107", "u_07", 5, None),
    ("f_108", "u_08", 5, None),
    ("f_109", "u_09", 5, None),
    ("f_110", "u_10", 5, None),
]


def build_feedback(version_id: str, rows) -> list[Feedback]:
    comment = "第三步沒有指出按鈕在哪一頁與位置"
    return [
        Feedback(
            id=feedback_id,
            tutorial_version=version_id,
            rating=rating,
            user=user,
            category=category,
            comment=comment if category else None,
            ts="2026-08-02T09:00:00Z",
        )
        for feedback_id, user, rating, category in rows
    ]


def test_a_v1_average_is_two_point_eight_seven_five():
    feedback = build_feedback("prepare-meeting@v1", A_V1_FEEDBACK_ROWS)
    assert average_rating(feedback) == 23 / 8


def test_a_v1_average_displays_as_2_9():
    # 設計文件 §11.2：2.875 顯示一位小數為 2.9；門檻判斷仍用未四捨五入的值。
    assert format_rating(23 / 8) == "2.9"


def test_a_v2_average_is_four_point_four():
    feedback = build_feedback("prepare-meeting@v2", A_V2_FEEDBACK_ROWS)
    assert average_rating(feedback) == 44 / 10
    assert format_rating(average_rating(feedback)) == "4.4"


def test_average_of_empty_list_is_none():
    # F52：沒有任何有效評分時內部值是 None，不是 0。
    assert average_rating([]) is None


def test_zero_rating_displays_no_rating_text():
    assert format_rating(None) == "尚無評分"


def test_cross_version_average_weights_versions_equally():
    # F44：先算每版平均再等權平均，不是把所有回饋混在一起。
    assert cross_version_average([23 / 8, 44 / 10]) == (23 / 8 + 44 / 10) / 2


def test_cross_version_average_skips_none():
    assert cross_version_average([4.0, None, 2.0]) == 3.0


def test_cross_version_average_of_all_none_is_none():
    assert cross_version_average([None, None]) is None


def test_mixed_average_is_not_the_same_as_pooled_average():
    # 把 8 筆與 10 筆混在一起算會得到 (23+44)/18 = 3.722...，不是等權的 3.6375。
    equal_weight = cross_version_average([23 / 8, 44 / 10])
    pooled = (23 + 44) / 18
    assert equal_weight == pytest.approx(3.6375)
    assert equal_weight != pytest.approx(pooled)
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：

```bash
uv run pytest tests/unit/test_analytics_metrics.py -v
```

預期：FAIL，錯誤訊息是 `ModuleNotFoundError: No module named 'training_kb.analytics'`。

- [ ] **步驟 3：寫最少的程式讓測試通過**

建立 `src/training_kb/analytics.py`：

```python
"""學習指標與規則驗證（Phase 19 指標、Phase 20 規則狀態）。

設計文件 §12.1 的公式。所有內部值使用未四捨五入的數字；
只有 format_* 系列是給畫面看的字串，不參與任何門檻判斷。
"""

from __future__ import annotations

from training_kb.models import Feedback


def _rated(feedback: list[Feedback]) -> list[Feedback]:
    """有效回饋：rating 是 1..5 的整數（D12）。"""
    return [
        item
        for item in feedback
        if isinstance(item.rating, int) and 1 <= item.rating <= 5
    ]


def average_rating(feedback: list[Feedback]) -> float | None:
    """該版平均評分；沒有任何有效評分時回傳 None（F52）。"""
    ratings = [item.rating for item in _rated(feedback)]
    if not ratings:
        return None
    return sum(ratings) / len(ratings)


def cross_version_average(per_version: list[float | None]) -> float | None:
    """跨版平均：先算每版平均，再對版本等權平均（F44）。

    per_version 裡的 None 代表那一版沒有評分，直接跳過，不當成 0。
    """
    values = [value for value in per_version if value is not None]
    if not values:
        return None
    return sum(values) / len(values)


def format_rating(avg: float | None) -> str:
    """畫面用的評分文字：一位小數，或「尚無評分」（F52）。"""
    if avg is None:
        return "尚無評分"
    return f"{avg:.1f}"
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：

```bash
uv run pytest tests/unit/test_analytics_metrics.py -v
```

預期：PASS，9 個測試全綠。

- [ ] **步驟 5：commit**

```bash
git add src/training_kb/analytics.py tests/unit/test_analytics_metrics.py
git commit -m "feat(analytics): 加入每版平均與跨版等權平均"
```

---

### Task 2：負面回饋數

**目的**：算出「`rating <= 2` 或類別屬核定問題類別」的回饋 ID 集合，同一筆只算一次。

**檔案**：
- 修改：`src/training_kb/analytics.py`
- 修改：`tests/unit/test_analytics_metrics.py`

**介面**：
- 消費：`models.PENDING_CATEGORY`（Phase 02）
- 產出：`analytics.negative_feedback_ids(feedback: list[Feedback], approved_categories: list[str]) -> set[str]`

- [ ] **步驟 1：寫測試**

在 `tests/unit/test_analytics_metrics.py` 最後加入：

```python
from training_kb.analytics import negative_feedback_ids
from training_kb.models import APPROVED_CATEGORIES_DEFAULT

APPROVED = list(APPROVED_CATEGORIES_DEFAULT)


def test_a_v1_has_eight_negative_feedback():
    # 設計文件 §11.2：八筆皆有核定問題類別，所以負面回饋是 8。
    feedback = build_feedback("prepare-meeting@v1", A_V1_FEEDBACK_ROWS)
    assert len(negative_feedback_ids(feedback, APPROVED)) == 8


def test_a_v2_has_two_negative_feedback():
    # 設計文件 §11.2：只有兩筆低分或問題類別，所以負面回饋是 2。
    feedback = build_feedback("prepare-meeting@v2", A_V2_FEEDBACK_ROWS)
    assert negative_feedback_ids(feedback, APPROVED) == {"f_101", "f_102"}


def test_both_conditions_on_one_row_counts_once():
    # F43：兩個條件不各算一次後相加。
    feedback = build_feedback("x@v1", [("f_01", "u_01", 1, "找不到按鈕")])
    assert negative_feedback_ids(feedback, APPROVED) == {"f_01"}


def test_low_rating_alone_counts():
    feedback = build_feedback("x@v1", [("f_02", "u_02", 2, None)])
    assert negative_feedback_ids(feedback, APPROVED) == {"f_02"}


def test_rating_three_with_approved_category_counts():
    feedback = build_feedback("x@v1", [("f_03", "u_03", 3, "缺少資訊")])
    assert negative_feedback_ids(feedback, APPROVED) == {"f_03"}


def test_pending_category_does_not_count_by_category():
    # F43：待分類不因 category 計入負面；但 rating <= 2 仍獨立計入。
    feedback = build_feedback("x@v1", [("f_04", "u_04", 4, "待分類")])
    assert negative_feedback_ids(feedback, APPROVED) == set()

    low = build_feedback("x@v1", [("f_05", "u_05", 1, "待分類")])
    assert negative_feedback_ids(low, APPROVED) == {"f_05"}


def test_unknown_category_does_not_count():
    feedback = build_feedback("x@v1", [("f_06", "u_06", 5, "介面太醜")])
    assert negative_feedback_ids(feedback, APPROVED) == set()


def test_high_rating_without_category_does_not_count():
    feedback = build_feedback("x@v1", [("f_07", "u_07", 5, None)])
    assert negative_feedback_ids(feedback, APPROVED) == set()
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：

```bash
uv run pytest tests/unit/test_analytics_metrics.py -v
```

預期：FAIL，錯誤訊息是 `ImportError: cannot import name 'negative_feedback_ids'`。

- [ ] **步驟 3：寫最少的程式讓測試通過**

在 `src/training_kb/analytics.py` 的 import 區改成：

```python
from training_kb.models import PENDING_CATEGORY, Feedback
```

在檔案最後加入：

```python
def negative_feedback_ids(
    feedback: list[Feedback], approved_categories: list[str]
) -> set[str]:
    """負面回饋的 ID 集合：rating <= 2 或 category 屬核定問題類別（F43）。

    回傳集合，所以同一筆同時命中兩個條件只算一次；
    「待分類」不因 category 計入，但它的 rating <= 2 仍獨立計入。
    """
    approved = set(approved_categories)
    negative: set[str] = set()
    for item in _rated(feedback):
        if item.rating <= 2:
            negative.add(item.id)
            continue
        category = item.category
        if category is None or category == PENDING_CATEGORY:
            continue
        if category in approved:
            negative.add(item.id)
    return negative
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：

```bash
uv run pytest tests/unit/test_analytics_metrics.py -v
```

預期：PASS，17 個測試全綠。

- [ ] **步驟 5：commit**

```bash
git add src/training_kb/analytics.py tests/unit/test_analytics_metrics.py
git commit -m "feat(analytics): 加入負面回饋數"
```

---

### Task 3：重開票窗口與 ReopenStats

**目的**：把「發布後 14 天」變成一組明確的起訖時間，並定義重開票統計的回傳形狀。

**檔案**：
- 修改：`src/training_kb/analytics.py`
- 修改：`tests/unit/test_analytics_metrics.py`

**介面**：
- 消費：`clock.parse_iso`（Phase 01）、`config.Thresholds.reopen_window_days`（Phase 01）
- 產出：
  - `analytics.ReopenStats`（dataclass，欄位 `count: int`、`reopen_users: int`、`viewers: int`、`rate: float | None`）
  - `analytics.reopen_window(published_at: str, days: int = 14) -> tuple[datetime, datetime]`
  - `analytics.format_rate(rate: float | None) -> str`（本階段新增，簡報第 6 節未列）

> 窗口端點採 `[p, p + days)`：左邊含、右邊不含。這是**本計劃選擇，對應設計文件待確認事項 O4**（ERM 明留窗口端點未定義）。在規格補上答案之前，不可以宣稱這是已定案的規格。

- [ ] **步驟 1：寫測試**

在 `tests/unit/test_analytics_metrics.py` 最後加入：

```python
from datetime import datetime, timezone

from training_kb.analytics import ReopenStats, format_rate, reopen_window

A_V1_PUBLISHED = "2026-08-01T00:00:00Z"
A_V2_PUBLISHED = "2026-08-20T00:00:00Z"


def test_reopen_window_is_left_closed_right_open():
    start, end = reopen_window(A_V1_PUBLISHED)
    assert start == datetime(2026, 8, 1, tzinfo=timezone.utc)
    assert end == datetime(2026, 8, 15, tzinfo=timezone.utc)


def test_reopen_window_for_v2():
    start, end = reopen_window(A_V2_PUBLISHED)
    assert start == datetime(2026, 8, 20, tzinfo=timezone.utc)
    assert end == datetime(2026, 9, 3, tzinfo=timezone.utc)


def test_reopen_window_accepts_custom_days():
    start, end = reopen_window(A_V1_PUBLISHED, days=7)
    assert (end - start).days == 7


def test_reopen_stats_holds_numerator_and_denominator_separately():
    stats = ReopenStats(count=7, reopen_users=7, viewers=10, rate=0.7)
    assert stats.count == 7
    assert stats.reopen_users == 7
    assert stats.viewers == 10
    assert stats.rate == 0.7


def test_format_rate_shows_percent():
    assert format_rate(0.7) == "70%"
    assert format_rate(0.2) == "20%"
    assert format_rate(0.0) == "0%"


def test_format_rate_keeps_one_decimal_when_needed():
    assert format_rate(2 / 3) == "66.7%"


def test_zero_viewers_displays_na():
    # F42：零分母顯示 N/A 與樣本不足，不當成改善或惡化。
    assert format_rate(None) == "N/A（樣本不足）"
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：

```bash
uv run pytest tests/unit/test_analytics_metrics.py -v
```

預期：FAIL，錯誤訊息是 `ImportError: cannot import name 'ReopenStats'`。

- [ ] **步驟 3：寫最少的程式讓測試通過**

在 `src/training_kb/analytics.py` 的 import 區改成：

```python
from dataclasses import dataclass
from datetime import datetime, timedelta

from training_kb.clock import parse_iso
from training_kb.models import PENDING_CATEGORY, Feedback
```

在檔案最後加入：

```python
@dataclass(frozen=True)
class ReopenStats:
    """同題重開票的統計結果。

    count        符合條件的不同 Ticket ID 數（筆數，可以多於人數）
    reopen_users 符合條件的不同開票使用者數（比例的分子）
    viewers      窗口內不同瀏覽者數（比例的分母）
    rate         reopen_users / viewers；分母為 0 時是 None，代表 N/A（F42）
    """

    count: int
    reopen_users: int
    viewers: int
    rate: float | None


def reopen_window(published_at: str, days: int = 14) -> tuple[datetime, datetime]:
    """版本發布後的比較窗口 [p, p + days)。

    左邊含、右邊不含；全部使用 UTC。
    這是本計劃選擇，對應設計文件第 18 節待確認事項 O4，不是規格已定案的答案。
    """
    start = parse_iso(published_at)
    return (start, start + timedelta(days=days))


def format_rate(rate: float | None) -> str:
    """畫面用的比例文字；分母為 0 時顯示 N/A 與樣本不足（F42）。"""
    if rate is None:
        return "N/A（樣本不足）"
    percent = round(rate * 100, 1)
    if percent == int(percent):
        return f"{int(percent)}%"
    return f"{percent}%"
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：

```bash
uv run pytest tests/unit/test_analytics_metrics.py -v
```

預期：PASS，24 個測試全綠。

- [ ] **步驟 5：commit**

```bash
git add src/training_kb/analytics.py tests/unit/test_analytics_metrics.py
git commit -m "feat(analytics): 加入重開票窗口與統計結構"
```

---

### Task 4：重開票統計 reopen_stats

**目的**：把瀏覽紀錄與工單湊起來，算出重開票筆數、分子、分母與比例，並擋掉五種不該計入的情況。

**檔案**：
- 修改：`src/training_kb/analytics.py`
- 修改：`tests/unit/test_analytics_metrics.py`

**介面**：
- 消費：`models.TutorialView`、`models.Ticket`（Phase 02）、`clock.parse_iso`（Phase 01）
- 產出：`analytics.reopen_stats(views: list[TutorialView], tickets: list[Ticket], *, cluster_id: str, published_at: str, days: int = 14) -> ReopenStats`

- [ ] **步驟 1：寫測試**

在 `tests/unit/test_analytics_metrics.py` 最後加入：

```python
from training_kb.analytics import reopen_stats
from training_kb.models import Ticket, TicketSource, TutorialView

CLUSTER = "c12"
PROJECT = "demo-project"
TICKET_TEXT = "看過準備會議教學後，仍找不到第三步的按鈕"


def make_views(version_id: str, users: list[str], ts: str) -> list[TutorialView]:
    return [TutorialView(tutorial_version=version_id, user=user, ts=ts) for user in users]


def make_tickets(
    rows: list[tuple[str, str, str]], cluster_id: str = CLUSTER
) -> list[Ticket]:
    """rows 的每一筆是 (ticket_id, author, ts)。"""
    return [
        Ticket(
            id=ticket_id,
            source=TicketSource.email,
            text=TICKET_TEXT,
            author=author,
            ts=ts,
            project_id=PROJECT,
            cluster_id=cluster_id,
        )
        for ticket_id, author, ts in rows
    ]


TEN_USERS = [f"u_{n:02d}" for n in range(1, 11)]

# 設計文件 §11.3：A v1 十人瀏覽、u_01~u_07 開票
A_V1_VIEWS = make_views("prepare-meeting@v1", TEN_USERS, "2026-08-02T09:00:00Z")
A_V1_TICKETS = make_tickets(
    [(f"t_200{n}", f"u_{n:02d}", "2026-08-03T10:00:00Z") for n in range(1, 8)]
)

# 設計文件 §11.3：A v2 十人瀏覽、u_01~u_02 開票
A_V2_VIEWS = make_views("prepare-meeting@v2", TEN_USERS, "2026-08-21T09:00:00Z")
A_V2_TICKETS = make_tickets(
    [("t_2101", "u_01", "2026-08-22T10:00:00Z"), ("t_2102", "u_02", "2026-08-22T10:00:00Z")]
)

ALL_TICKETS = A_V1_TICKETS + A_V2_TICKETS


def test_a_v1_reopen_is_seven_over_ten():
    stats = reopen_stats(
        A_V1_VIEWS, ALL_TICKETS, cluster_id=CLUSTER, published_at=A_V1_PUBLISHED
    )
    assert stats.count == 7
    assert stats.reopen_users == 7
    assert stats.viewers == 10
    assert stats.rate == 0.7
    assert format_rate(stats.rate) == "70%"


def test_a_v2_reopen_is_two_over_ten():
    stats = reopen_stats(
        A_V2_VIEWS, ALL_TICKETS, cluster_id=CLUSTER, published_at=A_V2_PUBLISHED
    )
    assert stats.count == 2
    assert stats.reopen_users == 2
    assert stats.viewers == 10
    assert stats.rate == 0.2
    assert format_rate(stats.rate) == "20%"


def test_ticket_before_view_is_not_counted():
    # F41：分子只計在瀏覽之後開的票。
    views = make_views("x@v1", ["u_01"], "2026-08-02T09:00:00Z")
    tickets = make_tickets([("t_01", "u_01", "2026-08-02T08:00:00Z")])

    stats = reopen_stats(views, tickets, cluster_id=CLUSTER, published_at=A_V1_PUBLISHED)

    assert stats.viewers == 1
    assert stats.count == 0
    assert stats.reopen_users == 0
    assert stats.rate == 0.0


def test_repeated_views_by_same_user_count_once_in_denominator():
    views = (
        make_views("x@v1", ["u_01"], "2026-08-02T09:00:00Z")
        + make_views("x@v1", ["u_01"], "2026-08-02T15:00:00Z")
    )
    stats = reopen_stats(views, [], cluster_id=CLUSTER, published_at=A_V1_PUBLISHED)
    assert stats.viewers == 1


def test_earliest_view_is_used_for_the_before_check():
    views = (
        make_views("x@v1", ["u_01"], "2026-08-02T09:00:00Z")
        + make_views("x@v1", ["u_01"], "2026-08-04T09:00:00Z")
    )
    tickets = make_tickets([("t_01", "u_01", "2026-08-03T10:00:00Z")])

    stats = reopen_stats(views, tickets, cluster_id=CLUSTER, published_at=A_V1_PUBLISHED)

    assert stats.reopen_users == 1
    assert stats.count == 1


def test_same_user_multiple_tickets_counts_once_in_numerator():
    views = make_views("x@v1", ["u_01", "u_02"], "2026-08-02T09:00:00Z")
    tickets = make_tickets(
        [
            ("t_01", "u_01", "2026-08-03T10:00:00Z"),
            ("t_02", "u_01", "2026-08-04T10:00:00Z"),
        ]
    )

    stats = reopen_stats(views, tickets, cluster_id=CLUSTER, published_at=A_V1_PUBLISHED)

    assert stats.count == 2          # 筆數是兩張不同工單
    assert stats.reopen_users == 1   # 分子只算一個人
    assert stats.viewers == 2
    assert stats.rate == 0.5


def test_other_cluster_is_not_counted():
    views = make_views("x@v1", ["u_01"], "2026-08-02T09:00:00Z")
    tickets = make_tickets(
        [("t_01", "u_01", "2026-08-03T10:00:00Z")], cluster_id="c99"
    )

    stats = reopen_stats(views, tickets, cluster_id=CLUSTER, published_at=A_V1_PUBLISHED)

    assert stats.count == 0
    assert stats.reopen_users == 0


def test_ticket_without_cluster_is_not_counted():
    views = make_views("x@v1", ["u_01"], "2026-08-02T09:00:00Z")
    tickets = [
        Ticket(
            id="t_01", source=TicketSource.email, text=TICKET_TEXT, author="u_01",
            ts="2026-08-03T10:00:00Z", project_id=PROJECT, cluster_id=None,
        )
    ]

    stats = reopen_stats(views, tickets, cluster_id=CLUSTER, published_at=A_V1_PUBLISHED)

    assert stats.count == 0


def test_window_right_endpoint_is_excluded():
    # 窗口是 [2026-08-01T00:00Z, 2026-08-15T00:00Z)
    views = make_views("x@v1", ["u_01"], "2026-08-01T00:00:00Z")  # 左端點：算
    inside = make_tickets([("t_01", "u_01", "2026-08-14T23:59:59Z")])
    outside = make_tickets([("t_02", "u_01", "2026-08-15T00:00:00Z")])

    assert reopen_stats(
        views, inside, cluster_id=CLUSTER, published_at=A_V1_PUBLISHED
    ).count == 1
    assert reopen_stats(
        views, outside, cluster_id=CLUSTER, published_at=A_V1_PUBLISHED
    ).count == 0


def test_view_outside_window_is_not_in_denominator():
    views = make_views("x@v1", ["u_01"], "2026-08-15T00:00:00Z")
    stats = reopen_stats(views, [], cluster_id=CLUSTER, published_at=A_V1_PUBLISHED)
    assert stats.viewers == 0
    assert stats.rate is None


def test_no_viewer_gives_none_rate():
    # F42：零分母顯示 N/A，不是 0%。
    stats = reopen_stats(
        [], A_V1_TICKETS, cluster_id=CLUSTER, published_at=A_V1_PUBLISHED
    )
    assert stats.viewers == 0
    assert stats.rate is None
    assert format_rate(stats.rate) == "N/A（樣本不足）"


def test_ticket_from_user_who_never_viewed_is_not_counted():
    views = make_views("x@v1", ["u_01"], "2026-08-02T09:00:00Z")
    tickets = make_tickets([("t_01", "u_09", "2026-08-03T10:00:00Z")])

    stats = reopen_stats(views, tickets, cluster_id=CLUSTER, published_at=A_V1_PUBLISHED)

    assert stats.count == 0
    assert stats.reopen_users == 0
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：

```bash
uv run pytest tests/unit/test_analytics_metrics.py -v
```

預期：FAIL，錯誤訊息是 `ImportError: cannot import name 'reopen_stats'`。

- [ ] **步驟 3：寫最少的程式讓測試通過**

在 `src/training_kb/analytics.py` 的 import 區改成：

```python
from training_kb.models import PENDING_CATEGORY, Feedback, Ticket, TutorialView
```

在檔案最後加入：

```python
def reopen_stats(
    views: list[TutorialView],
    tickets: list[Ticket],
    *,
    cluster_id: str,
    published_at: str,
    days: int = 14,
) -> ReopenStats:
    """同題重開票統計（設計文件 §12.1）。

    分母：窗口內出現過的不同瀏覽 user。
    分子：同一個 user 在窗口內開了同 cluster 的票，而且他在這張票之前看過教學。
    每版每人分子、分母各最多一次；筆數 count 則以不同 Ticket ID 計算。
    """
    start, end = reopen_window(published_at, days)

    # 分母：每人只留窗口內最早的一次瀏覽時間。
    first_view: dict[str, datetime] = {}
    for view in views:
        moment = parse_iso(view.ts)
        if not (start <= moment < end):
            continue
        seen = first_view.get(view.user)
        if seen is None or moment < seen:
            first_view[view.user] = moment

    # 分子：窗口內、同 cluster、而且瀏覽發生在開票之前。
    matched_tickets: set[str] = set()
    matched_users: set[str] = set()
    for ticket in tickets:
        if ticket.cluster_id != cluster_id:
            continue
        moment = parse_iso(ticket.ts)
        if not (start <= moment < end):
            continue
        viewed_at = first_view.get(ticket.author)
        if viewed_at is None or not viewed_at < moment:
            continue
        matched_tickets.add(ticket.id)
        matched_users.add(ticket.author)

    viewers = len(first_view)
    rate = None if viewers == 0 else len(matched_users) / viewers
    return ReopenStats(
        count=len(matched_tickets),
        reopen_users=len(matched_users),
        viewers=viewers,
        rate=rate,
    )
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：

```bash
uv run pytest tests/unit/test_analytics_metrics.py -v
```

預期：PASS，36 個測試全綠。

- [ ] **步驟 5：commit**

```bash
git add src/training_kb/analytics.py tests/unit/test_analytics_metrics.py
git commit -m "feat(analytics): 加入同題重開票筆數、分子分母與比例"
```

---

### Task 5：規則計數、套用次數與模型呼叫數

**目的**：算出三種規則狀態各有幾條、某條規則被幾個版本套用過、以及這一次執行送出了幾個 Bedrock 請求。

**檔案**：
- 修改：`src/training_kb/analytics.py`
- 修改：`tests/unit/test_analytics_metrics.py`

**介面**：
- 消費：`models.AuthoringRule`、`models.RuleStatus`、`models.TutorialVersion`（Phase 02）、`writing.client.CallTrace`（Phase 05）
- 產出：
  - `analytics.rule_counts(rules: list[AuthoringRule]) -> dict[str, int]`
  - `analytics.applied_count(versions: list[TutorialVersion], rule_id: str) -> int`
  - `analytics.bedrock_call_count(trace: CallTrace) -> int`

- [ ] **步驟 1：寫測試**

在 `tests/unit/test_analytics_metrics.py` 最後加入：

```python
from training_kb.analytics import applied_count, bedrock_call_count, rule_counts
from training_kb.models import AuthoringRule, RuleStatus, TutorialVersion
from training_kb.writing.client import CallRecord, CallTrace


def make_rule(rule_id: str, status: RuleStatus) -> AuthoringRule:
    return AuthoringRule(
        rule_id=rule_id,
        rule="步驟要求點擊 UI 元件時，必須寫出：在哪個頁面、按鈕位置、點完會看到什麼",
        applies_when={"step.type": "click_ui"},
        evidence=["f_12", "f_15", "f_19", "f_23", "f_27"],
        status=status,
        applied_to=[],
        derived_from="prepare-meeting@v1",
        validated_at=None,
    )


def make_version(version_id: str, rules_applied: list[str]) -> TutorialVersion:
    slug, number = version_id.split("@v")
    return TutorialVersion(
        version_id=version_id,
        supersedes=None,
        reason="gap:c12",
        rules_applied=list(rules_applied),
        s3_key=f"tutorials/{slug}/v{number}.md",
        published_at="2026-08-01T00:00:00Z",
    )


def test_rule_counts_splits_three_statuses():
    rules = [
        make_rule("R-007", RuleStatus.active),
        make_rule("R-008", RuleStatus.candidate),
        make_rule("R-009", RuleStatus.candidate),
        make_rule("R-012", RuleStatus.retired),
    ]
    assert rule_counts(rules) == {"candidate": 2, "active": 1, "retired": 1}


def test_rule_counts_of_empty_list_has_three_zeros():
    assert rule_counts([]) == {"candidate": 0, "active": 0, "retired": 0}


def test_applied_count_matches_the_spec_example():
    # 檢視學習指標.feature：R-007 的三個套用版本計為 3。
    versions = [
        make_version("prepare-meeting@v2", ["R-007"]),
        make_version("share-summary@v1", ["R-007"]),
        make_version("prepare-meeting@v3", ["R-007"]),
        make_version("notification-settings@v1", []),
    ]
    assert applied_count(versions, "R-007") == 3


def test_applied_count_deduplicates_repeated_version_ids():
    versions = [
        make_version("prepare-meeting@v2", ["R-007", "R-007"]),
        make_version("prepare-meeting@v2", ["R-007"]),
    ]
    assert applied_count(versions, "R-007") == 1


def test_applied_count_of_unused_rule_is_zero():
    versions = [make_version("prepare-meeting@v2", ["R-007"])]
    assert applied_count(versions, "R-999") == 0


def test_bedrock_call_count_counts_every_attempt():
    # F45：包含重試、每個 Map item 與 Rote 呼叫；以嘗試為單位。
    trace = CallTrace()
    trace.add(CallRecord(operation_id="op", node="embed", model_id="titan",
                         attempt=1, ok=True, error=None, elapsed_ms=120))
    trace.add(CallRecord(operation_id="op", node="diagnose", model_id="claude",
                         attempt=1, ok=False, error="timeout", elapsed_ms=30000))
    trace.add(CallRecord(operation_id="op", node="diagnose", model_id="claude",
                         attempt=2, ok=True, error=None, elapsed_ms=900))

    assert bedrock_call_count(trace) == 3


def test_bedrock_call_count_of_empty_trace_is_zero():
    assert bedrock_call_count(CallTrace()) == 0
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：

```bash
uv run pytest tests/unit/test_analytics_metrics.py -v
```

預期：FAIL，錯誤訊息是 `ImportError: cannot import name 'rule_counts'`。

- [ ] **步驟 3：寫最少的程式讓測試通過**

在 `src/training_kb/analytics.py` 的 import 區改成：

```python
from training_kb.models import (
    PENDING_CATEGORY,
    AuthoringRule,
    Feedback,
    RuleStatus,
    Ticket,
    TutorialVersion,
    TutorialView,
)
from training_kb.writing.client import CallTrace
```

在檔案最後加入：

```python
def rule_counts(rules: list[AuthoringRule]) -> dict[str, int]:
    """依 status 分別計數（設計文件 §12.1）。

    三個鍵一定都在，沒有的就是 0；不把 candidate 寫成已有效。
    """
    counts = {status.value: 0 for status in RuleStatus}
    for rule in rules:
        key = str(rule.status)
        counts[key] = counts.get(key, 0) + 1
    return counts


def applied_count(versions: list[TutorialVersion], rule_id: str) -> int:
    """規則被幾個版本實際注入過。

    以各版本的 rules_applied 為權威並去重（D17）；
    原文複製沿用不算本次套用（F29），因為那些版本不會把規則寫進 rules_applied。
    """
    return len(
        {version.version_id for version in versions if rule_id in version.rules_applied}
    )


def bedrock_call_count(trace: CallTrace) -> int:
    """這一次執行實際送出的 Bedrock 請求嘗試總數（F45）。"""
    return trace.count()
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：

```bash
uv run pytest tests/unit/test_analytics_metrics.py -v
```

預期：PASS，43 個測試全綠。

- [ ] **步驟 5：commit**

```bash
git add src/training_kb/analytics.py tests/unit/test_analytics_metrics.py
git commit -m "feat(analytics): 加入規則計數、套用次數與呼叫數"
```

---

### Task 6：單版彙總 VersionMetrics

**目的**：給一個版本 ID，從 Repository 讀齊資料，一次算出平均、筆數、負面數與重開票統計。

**檔案**：
- 修改：`src/training_kb/analytics.py`
- 修改：`tests/unit/test_analytics_metrics.py`

**介面**：
- 消費：`repository.Repository.get_version` / `get_tutorial` / `list_feedback_of_version` / `list_views_of_version` / `list_tickets`（Phase 03、09）、`models.parse_version_id`（Phase 02）、`errors.PermanentError`（Phase 01）
- 產出：
  - `analytics.VersionMetrics`（dataclass，欄位 `version_id: str`、`avg: float | None`、`n: int`、`negative: int`、`reopen: ReopenStats`）
  - `analytics.version_metrics(repo: Repository, version_id: str, *, approved_categories: list[str], project_id: str) -> VersionMetrics`

> **與簡報第 6.9 節的差異**：簡報寫的是 `version_metrics(repo, version_id, *, approved_categories)`。本階段多加一個 keyword-only 參數 `project_id`，因為 `repository.list_tickets(project_id)` 需要它才能取得工單；不傳就沒辦法算重開票，而回傳 0 會被 Phase 20 誤判成「改善了」。其餘名稱與回傳形狀不變。
>
> **對後面階段的影響**：Phase 23（`23-Phase23-Demo控制台與Dashboard.md`）在兩個地方呼叫 `version_metrics(...)`，要補上 `project_id=settings.project_id`。Phase 23 的文件本身也寫了「Phase 19 若已定義不同格式，以 Phase 19 為準」，所以照本階段的簽名改即可。Phase 20（`20-Phase20-規則驗證與狀態轉換.md`）不受影響：它另外做了一個 `metrics_from_records(...)`，直接吃批次檔裡的記錄，不查 DynamoDB。

- [ ] **步驟 1：寫測試**

在 `tests/unit/test_analytics_metrics.py` 最後加入：

```python
from training_kb.analytics import VersionMetrics, version_metrics
from training_kb.errors import PermanentError
from training_kb.models import Tutorial, TutorialStatus


class FakeRepo:
    """只實作 Analytics 用得到的讀取方法，全部放在記憶體裡。"""

    def __init__(self) -> None:
        self.tutorials: dict[str, Tutorial] = {}
        self.versions: dict[str, TutorialVersion] = {}
        self.feedback: dict[str, list[Feedback]] = {}
        self.views: dict[str, list[TutorialView]] = {}
        self.tickets: list[Ticket] = []
        self.rules: list[AuthoringRule] = []
        self.config: dict[str, list[str]] = {}

    def get_tutorial(self, slug: str) -> Tutorial | None:
        return self.tutorials.get(slug)

    def get_version(self, version_id: str) -> TutorialVersion | None:
        return self.versions.get(version_id)

    def list_versions_of_tutorial(self, slug: str) -> list[TutorialVersion]:
        return [v for v in self.versions.values() if v.version_id.split("@v")[0] == slug]

    def list_feedback_of_version(self, version_id: str) -> list[Feedback]:
        return list(self.feedback.get(version_id, []))

    def list_views_of_version(self, version_id: str) -> list[TutorialView]:
        return list(self.views.get(version_id, []))

    def list_tickets(self, project_id: str) -> list[Ticket]:
        return [t for t in self.tickets if t.project_id == project_id]

    def list_rules(self, status: RuleStatus | None = None) -> list[AuthoringRule]:
        if status is None:
            return list(self.rules)
        return [r for r in self.rules if r.status == status]

    def get_config_list(self, name: str, default: list[str]) -> list[str]:
        return list(self.config.get(name, default))

    def scan_entity(self, entity: str) -> list[dict]:
        if entity != "TUTORIAL":
            return []
        return [{"PK": f"TUTORIAL#{slug}", "entity": "TUTORIAL"} for slug in self.tutorials]


def seeded_repo() -> FakeRepo:
    """設計文件 §11.2、§11.3 的完整配方。"""
    repo = FakeRepo()
    repo.tutorials["prepare-meeting"] = Tutorial(
        slug="prepare-meeting",
        current_version="prepare-meeting@v2",
        topic="準備會議",
        feature_ids=["Prepare"],
        status=TutorialStatus.active,
        cluster_id=CLUSTER,
    )
    repo.versions["prepare-meeting@v1"] = TutorialVersion(
        version_id="prepare-meeting@v1", supersedes=None, reason="gap:c12",
        rules_applied=[], s3_key="tutorials/prepare-meeting/v1.md",
        published_at=A_V1_PUBLISHED,
    )
    repo.versions["prepare-meeting@v2"] = TutorialVersion(
        version_id="prepare-meeting@v2", supersedes="prepare-meeting@v1",
        reason="feedback:8 則 找不到按鈕", rules_applied=["R-007"],
        s3_key="tutorials/prepare-meeting/v2.md", published_at=A_V2_PUBLISHED,
    )
    repo.feedback["prepare-meeting@v1"] = build_feedback(
        "prepare-meeting@v1", A_V1_FEEDBACK_ROWS
    )
    repo.feedback["prepare-meeting@v2"] = build_feedback(
        "prepare-meeting@v2", A_V2_FEEDBACK_ROWS
    )
    repo.views["prepare-meeting@v1"] = A_V1_VIEWS
    repo.views["prepare-meeting@v2"] = A_V2_VIEWS
    repo.tickets = list(ALL_TICKETS)
    repo.rules = [make_rule("R-007", RuleStatus.candidate)]
    return repo


def test_version_metrics_reproduces_a_v1_targets():
    metrics = version_metrics(
        seeded_repo(), "prepare-meeting@v1",
        approved_categories=APPROVED, project_id=PROJECT,
    )
    assert isinstance(metrics, VersionMetrics)
    assert metrics.avg == 23 / 8
    assert format_rating(metrics.avg) == "2.9"
    assert metrics.n == 8
    assert metrics.negative == 8
    assert metrics.reopen.count == 7
    assert metrics.reopen.viewers == 10
    assert metrics.reopen.rate == 0.7


def test_version_metrics_reproduces_a_v2_targets():
    metrics = version_metrics(
        seeded_repo(), "prepare-meeting@v2",
        approved_categories=APPROVED, project_id=PROJECT,
    )
    assert metrics.avg == 44 / 10
    assert format_rating(metrics.avg) == "4.4"
    assert metrics.n == 10
    assert metrics.negative == 2
    assert metrics.reopen.count == 2
    assert metrics.reopen.viewers == 10
    assert metrics.reopen.rate == 0.2


def test_version_metrics_of_unpublished_version_has_na_rate():
    repo = seeded_repo()
    repo.versions["prepare-meeting@v3"] = TutorialVersion(
        version_id="prepare-meeting@v3", supersedes="prepare-meeting@v2",
        reason="release:r_42", rules_applied=[],
        s3_key="tutorials/prepare-meeting/v3.md", published_at=None,
    )

    metrics = version_metrics(
        repo, "prepare-meeting@v3", approved_categories=APPROVED, project_id=PROJECT
    )

    assert metrics.avg is None
    assert metrics.n == 0
    assert metrics.reopen.rate is None
    assert metrics.reopen.viewers == 0


def test_version_metrics_rejects_missing_version():
    with pytest.raises(PermanentError):
        version_metrics(
            seeded_repo(), "nope@v1", approved_categories=APPROVED, project_id=PROJECT
        )
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：

```bash
uv run pytest tests/unit/test_analytics_metrics.py -v
```

預期：FAIL，錯誤訊息是 `ImportError: cannot import name 'VersionMetrics'`。

- [ ] **步驟 3：寫最少的程式讓測試通過**

在 `src/training_kb/analytics.py` 的 import 區補上：

```python
from training_kb.errors import PermanentError
from training_kb.models import (
    PENDING_CATEGORY,
    AuthoringRule,
    Feedback,
    RuleStatus,
    Ticket,
    TutorialVersion,
    TutorialView,
    parse_version_id,
)
from training_kb.repository import Repository
```

（把原本的 models import 整段換掉。）

在檔案最後加入：

```python
@dataclass(frozen=True)
class VersionMetrics:
    """單一版本的四個指標。

    avg 是未四捨五入的平均；沒有有效評分時是 None（F52）。
    """

    version_id: str
    avg: float | None
    n: int
    negative: int
    reopen: ReopenStats


def version_metrics(
    repo: Repository,
    version_id: str,
    *,
    approved_categories: list[str],
    project_id: str,
) -> VersionMetrics:
    """從 Repository 讀齊資料，算出這一版的四個指標。

    未發布的版本沒有窗口起點，重開票一律回傳 N/A（rate=None），不當成 0。
    """
    version = repo.get_version(version_id)
    if version is None:
        raise PermanentError(f"版本不存在：{version_id}")

    feedback = _rated(repo.list_feedback_of_version(version_id))
    slug, _number = parse_version_id(version_id)
    tutorial = repo.get_tutorial(slug)
    cluster_id = tutorial.cluster_id if tutorial is not None else None

    if version.published_at is None or not cluster_id:
        reopen = ReopenStats(count=0, reopen_users=0, viewers=0, rate=None)
    else:
        reopen = reopen_stats(
            repo.list_views_of_version(version_id),
            repo.list_tickets(project_id),
            cluster_id=cluster_id,
            published_at=version.published_at,
        )

    return VersionMetrics(
        version_id=version_id,
        avg=average_rating(feedback),
        n=len(feedback),
        negative=len(negative_feedback_ids(feedback, approved_categories)),
        reopen=reopen,
    )
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：

```bash
uv run pytest tests/unit/test_analytics_metrics.py -v
```

預期：PASS，47 個測試全綠。

- [ ] **步驟 5：commit**

```bash
git add src/training_kb/analytics.py tests/unit/test_analytics_metrics.py
git commit -m "feat(analytics): 加入單版彙總 VersionMetrics"
```

---

### Task 7：Dashboard 的完整 JSON

**目的**：把所有指標組成 Dashboard 四個區塊需要的一份 JSON。

**檔案**：
- 修改：`src/training_kb/analytics.py`
- 修改：`tests/unit/test_analytics_metrics.py`

**介面**：
- 消費：`keys.parse_pk`（Phase 02）、`clock.to_iso`（Phase 01）、`repository.Repository.scan_entity` / `list_versions_of_tutorial` / `list_rules`（Phase 03、09）
- 產出：`analytics.dashboard_payload(repo, *, project_id: str, approved_categories: list[str], slugs: list[str] | None = None, version_ids: list[str] | None = None, call_trace: list[dict] | None = None, now: datetime) -> dict`（本階段新增，簡報第 6 節未列）

> **呼叫數的來源**：Analytics 自己不呼叫 Bedrock，所以它不會憑空知道這一次執行送了幾個請求。`call_trace` 由觸發方（Phase 23 的控制台或維護者）用 `CallTrace.to_json()` 的內容傳進來。沒有傳就回 `null` 並附上 `bedrock_call_source: "未提供本次執行的呼叫紀錄"`，**不猜一個數字**（設計文件 §12.3：呼叫數須由逐次 trace 核對）。
>
> **`applied_count` 的取樣範圍（本計劃選擇）**：只統計**已發布**版本的 `rules_applied`。理由是未發布版本讀者看不到、成效無法觀察。設計文件 §12.1 只說「以 VERSION.rules_applied 重建，不計原文沿用或隔離預覽」，沒有規定未發布版本，所以這裡標成本計劃選擇。

- [ ] **步驟 1：寫測試**

在 `tests/unit/test_analytics_metrics.py` 最後加入：

```python
from datetime import datetime as _dt

from training_kb.analytics import dashboard_payload

NOW = _dt(2026, 9, 14, 0, 30, tzinfo=timezone.utc)


def test_dashboard_payload_lists_published_versions_in_order():
    payload = dashboard_payload(
        seeded_repo(), project_id=PROJECT, approved_categories=APPROVED, now=NOW
    )
    assert [row["version_id"] for row in payload["versions"]] == [
        "prepare-meeting@v1",
        "prepare-meeting@v2",
    ]
    assert payload["versions"][0]["slug"] == "prepare-meeting"
    assert payload["versions"][0]["published_at"] == A_V1_PUBLISHED


def test_dashboard_payload_reproduces_every_target_number():
    payload = dashboard_payload(
        seeded_repo(), project_id=PROJECT, approved_categories=APPROVED, now=NOW
    )
    v1, v2 = payload["versions"]

    assert v1["avg_display"] == "2.9"
    assert v1["n"] == 8
    assert v1["negative"] == 8
    assert v1["reopen"]["count"] == 7
    assert v1["reopen"]["reopen_users"] == 7
    assert v1["reopen"]["viewers"] == 10
    assert v1["reopen"]["rate_display"] == "70%"

    assert v2["avg_display"] == "4.4"
    assert v2["n"] == 10
    assert v2["negative"] == 2
    assert v2["reopen"]["count"] == 2
    assert v2["reopen"]["reopen_users"] == 2
    assert v2["reopen"]["viewers"] == 10
    assert v2["reopen"]["rate_display"] == "20%"


def test_dashboard_payload_computes_cross_version_average():
    payload = dashboard_payload(
        seeded_repo(), project_id=PROJECT, approved_categories=APPROVED, now=NOW
    )
    assert payload["cross_version_average"] == pytest.approx(3.6375)
    assert payload["cross_version_average_display"] == "3.6"


def test_dashboard_payload_reports_rule_block():
    payload = dashboard_payload(
        seeded_repo(), project_id=PROJECT, approved_categories=APPROVED, now=NOW
    )
    assert payload["rule_counts"] == {"candidate": 1, "active": 0, "retired": 0}
    rule = payload["rules"][0]
    assert rule["rule_id"] == "R-007"
    assert rule["status"] == "candidate"
    assert rule["applies_when"] == {"step.type": "click_ui"}
    assert rule["validated_at"] is None
    assert rule["applied_count"] == 1  # 只有 prepare-meeting@v2 的 rules_applied 有它


def test_dashboard_payload_without_trace_reports_null_not_zero():
    payload = dashboard_payload(
        seeded_repo(), project_id=PROJECT, approved_categories=APPROVED, now=NOW
    )
    assert payload["bedrock_call_count"] is None
    assert payload["bedrock_call_source"] == "未提供本次執行的呼叫紀錄"


def test_dashboard_payload_counts_supplied_trace():
    trace = [
        {"operation_id": "op", "node": "embed", "model_id": "titan",
         "attempt": 1, "ok": True, "error": None, "elapsed_ms": 100},
        {"operation_id": "op", "node": "diagnose", "model_id": "claude",
         "attempt": 1, "ok": True, "error": None, "elapsed_ms": 900},
    ]
    payload = dashboard_payload(
        seeded_repo(), project_id=PROJECT, approved_categories=APPROVED,
        call_trace=trace, now=NOW,
    )
    assert payload["bedrock_call_count"] == 2
    assert payload["bedrock_call_source"] == "本次執行提供的 trace"


def test_dashboard_payload_marks_synthetic_data():
    payload = dashboard_payload(
        seeded_repo(), project_id=PROJECT, approved_categories=APPROVED, now=NOW
    )
    assert payload["data_notice"] == "合成資料示範"
    assert payload["generated_at"] == "2026-09-14T00:30:00Z"
    assert payload["approved_categories"] == APPROVED


def test_dashboard_payload_accepts_explicit_version_ids():
    payload = dashboard_payload(
        seeded_repo(), project_id=PROJECT, approved_categories=APPROVED,
        version_ids=["prepare-meeting@v2"], now=NOW,
    )
    assert [row["version_id"] for row in payload["versions"]] == ["prepare-meeting@v2"]


def test_dashboard_payload_skips_unpublished_versions_by_default():
    repo = seeded_repo()
    repo.versions["prepare-meeting@v3"] = TutorialVersion(
        version_id="prepare-meeting@v3", supersedes="prepare-meeting@v2",
        reason="release:r_42", rules_applied=["R-007"],
        s3_key="tutorials/prepare-meeting/v3.md", published_at=None,
    )

    payload = dashboard_payload(
        repo, project_id=PROJECT, approved_categories=APPROVED, now=NOW
    )

    assert [row["version_id"] for row in payload["versions"]] == [
        "prepare-meeting@v1", "prepare-meeting@v2",
    ]
    # 未發布版本的 rules_applied 不計入套用次數（本計劃選擇）
    assert payload["rules"][0]["applied_count"] == 1
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：

```bash
uv run pytest tests/unit/test_analytics_metrics.py -v
```

預期：FAIL，錯誤訊息是 `ImportError: cannot import name 'dashboard_payload'`。

- [ ] **步驟 3：寫最少的程式讓測試通過**

在 `src/training_kb/analytics.py` 的 import 區補上：

```python
from training_kb.clock import parse_iso, to_iso
from training_kb.keys import parse_pk
```

（把原本的 `from training_kb.clock import parse_iso` 整行換掉。）

在檔案最後加入：

```python
def _published_versions(repo: Repository) -> list[TutorialVersion]:
    """所有教學的已發布版本，依 version_id 排序。"""
    slugs = sorted({parse_pk(row["PK"])[1] for row in repo.scan_entity("TUTORIAL")})
    versions: list[TutorialVersion] = []
    for slug in slugs:
        for version in repo.list_versions_of_tutorial(slug):
            if version.published_at:
                versions.append(version)
    return sorted(versions, key=lambda version: version.version_id)


def dashboard_payload(
    repo: Repository,
    *,
    project_id: str,
    approved_categories: list[str],
    slugs: list[str] | None = None,
    version_ids: list[str] | None = None,
    call_trace: list[dict] | None = None,
    now: datetime,
) -> dict:
    """組出 Dashboard 四個區塊需要的 JSON（設計文件 §13）。

    version_ids 指定時就只算那幾版；否則依 slugs（或全部教學）取已發布版本。
    call_trace 是呼叫方提供的逐次紀錄；沒有提供時呼叫數回傳 None 而不是 0，
    因為 Analytics 自己不呼叫 Bedrock，猜數字會違反設計文件 §12.3。
    """
    published = _published_versions(repo)

    if version_ids is None:
        selected = published
        if slugs is not None:
            wanted = set(slugs)
            selected = [
                version
                for version in published
                if parse_version_id(version.version_id)[0] in wanted
            ]
        target_ids = [version.version_id for version in selected]
    else:
        target_ids = list(version_ids)

    rows: list[dict] = []
    for version_id in target_ids:
        metrics = version_metrics(
            repo,
            version_id,
            approved_categories=approved_categories,
            project_id=project_id,
        )
        version = repo.get_version(version_id)
        rows.append(
            {
                "version_id": metrics.version_id,
                "slug": parse_version_id(metrics.version_id)[0],
                "published_at": version.published_at if version else None,
                "avg": metrics.avg,
                "avg_display": format_rating(metrics.avg),
                "n": metrics.n,
                "negative": metrics.negative,
                "rules_applied": list(version.rules_applied) if version else [],
                "reopen": {
                    "count": metrics.reopen.count,
                    "reopen_users": metrics.reopen.reopen_users,
                    "viewers": metrics.reopen.viewers,
                    "rate": metrics.reopen.rate,
                    "rate_display": format_rate(metrics.reopen.rate),
                },
            }
        )

    rules = sorted(repo.list_rules(), key=lambda rule: rule.rule_id)
    cross = cross_version_average([row["avg"] for row in rows])
    return {
        "generated_at": to_iso(now),
        "project_id": project_id,
        "approved_categories": list(approved_categories),
        "data_notice": "合成資料示範",
        "versions": rows,
        "cross_version_average": cross,
        "cross_version_average_display": format_rating(cross),
        "rule_counts": rule_counts(rules),
        "rules": [
            {
                "rule_id": rule.rule_id,
                "status": str(rule.status),
                "rule": rule.rule,
                "applies_when": dict(rule.applies_when),
                "evidence": list(rule.evidence),
                "derived_from": rule.derived_from,
                "validated_at": rule.validated_at,
                "applied_count": applied_count(published, rule.rule_id),
            }
            for rule in rules
        ],
        "bedrock_call_count": None if call_trace is None else len(call_trace),
        "bedrock_call_source": (
            "未提供本次執行的呼叫紀錄"
            if call_trace is None
            else "本次執行提供的 trace"
        ),
    }
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：

```bash
uv run pytest tests/unit/test_analytics_metrics.py -v
uv run ruff check src/training_kb/analytics.py tests/unit/test_analytics_metrics.py
```

預期：pytest 顯示 56 個測試全綠；ruff 顯示 `All checks passed!`。

- [ ] **步驟 5：commit**

```bash
git add src/training_kb/analytics.py tests/unit/test_analytics_metrics.py
git commit -m "feat(analytics): 加入 Dashboard 的完整 JSON"
```

---

### Task 8：Analytics Lambda handler

**目的**：把 `dashboard_payload` 包成 AWS Lambda 的進入點，讓 Dashboard 可以直接呼叫。

**檔案**：
- 新增：`src/training_kb/handlers/analytics.py`
- 測試：`tests/unit/test_handlers_analytics.py`

**介面**：
- 消費：`analytics.dashboard_payload`（Task 7）、`config.load_settings`（Phase 01）、`clock.now_utc`（Phase 01）、`repository.build_repository`（Phase 03）、`models.APPROVED_CATEGORIES_DEFAULT`（Phase 02）
- 產出：`handlers.analytics.handler(event: dict, context: object) -> dict`

- [ ] **步驟 1：寫測試**

建立 `tests/unit/test_handlers_analytics.py`：

```python
"""Phase 19：Analytics Lambda handler。"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

import training_kb.handlers.analytics as mod
from training_kb.config import Settings
from tests.unit.test_analytics_metrics import PROJECT, seeded_repo

NOW = datetime(2026, 9, 14, 0, 30, tzinfo=timezone.utc)


def fake_settings() -> Settings:
    return Settings(
        aws_region="us-east-1",
        table_name="training_kb",
        bucket_name="training-kb-content-test",
        project_id=PROJECT,
        embed_model_id="amazon.titan-embed-text-v2:0",
        embed_dimensions=1024,
        gen_model_id="test.claude",
        github_webhook_secret="not-a-real-secret",
    )


@pytest.fixture
def patched(monkeypatch):
    repo = seeded_repo()
    monkeypatch.setattr(mod, "load_settings", lambda: fake_settings())
    monkeypatch.setattr(mod, "build_repository", lambda settings: repo)
    monkeypatch.setattr(mod, "now_utc", lambda: NOW)
    return repo


def test_handler_returns_dashboard_json(patched):
    result = mod.handler({}, None)

    assert result["project_id"] == PROJECT
    assert [row["version_id"] for row in result["versions"]] == [
        "prepare-meeting@v1",
        "prepare-meeting@v2",
    ]
    assert result["versions"][0]["avg_display"] == "2.9"
    assert result["versions"][1]["avg_display"] == "4.4"
    assert result["rule_counts"] == {"candidate": 1, "active": 0, "retired": 0}
    assert result["generated_at"] == "2026-09-14T00:30:00Z"


def test_handler_uses_approved_categories_from_config(patched):
    patched.config["approved_categories"] = ["找不到按鈕"]

    result = mod.handler({}, None)

    assert result["approved_categories"] == ["找不到按鈕"]
    # 「缺少資訊」不再算核定類別，A v2 的 f_101／f_102 仍因 rating<=2 計入負面。
    assert result["versions"][1]["negative"] == 2


def test_handler_accepts_version_ids_filter(patched):
    result = mod.handler({"version_ids": ["prepare-meeting@v2"]}, None)
    assert [row["version_id"] for row in result["versions"]] == ["prepare-meeting@v2"]


def test_handler_accepts_slugs_filter(patched):
    result = mod.handler({"slugs": ["prepare-meeting"]}, None)
    assert len(result["versions"]) == 2


def test_handler_passes_call_trace_through(patched):
    trace = [
        {"operation_id": "op", "node": "embed", "model_id": "titan",
         "attempt": 1, "ok": True, "error": None, "elapsed_ms": 100},
    ]
    result = mod.handler({"call_trace": trace}, None)
    assert result["bedrock_call_count"] == 1
    assert result["bedrock_call_source"] == "本次執行提供的 trace"


def test_handler_without_trace_reports_null(patched):
    result = mod.handler({}, None)
    assert result["bedrock_call_count"] is None
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：

```bash
uv run pytest tests/unit/test_handlers_analytics.py -v
```

預期：FAIL，錯誤訊息是 `ModuleNotFoundError: No module named 'training_kb.handlers.analytics'`。

如果改成看到 `ModuleNotFoundError: No module named 'tests'`，代表 `tests` 目錄還不是可匯入的套件。解法是在 `pyproject.toml` 的 `[tool.pytest.ini_options]` 加上這一行，讓 pytest 把 repo 根目錄放進匯入路徑：

```toml
[tool.pytest.ini_options]
pythonpath = ["."]
```

- [ ] **步驟 3：寫最少的程式讓測試通過**

建立 `src/training_kb/handlers/analytics.py`：

```python
"""Analytics Lambda：回傳 Dashboard 需要的 JSON（Phase 19）。

由維護者或 Demo 控制台用 boto3 invoke 呼叫，不開放公開 URL。
event 可用的鍵（都是選填）：
  slugs        只算這幾篇教學的已發布版本
  version_ids  只算這幾個版本（優先於 slugs）
  call_trace   本次執行的 Bedrock 呼叫紀錄清單（CallTrace.to_json() 解析後的內容）
"""

from __future__ import annotations

from typing import Any

from training_kb.analytics import dashboard_payload
from training_kb.clock import now_utc
from training_kb.config import load_settings
from training_kb.models import APPROVED_CATEGORIES_DEFAULT
from training_kb.repository import build_repository


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Lambda 進入點。只讀資料、只做計算，不寫入任何東西。"""
    settings = load_settings()
    repo = build_repository(settings)
    approved = repo.get_config_list(
        "approved_categories", list(APPROVED_CATEGORIES_DEFAULT)
    )
    return dashboard_payload(
        repo,
        project_id=settings.project_id,
        approved_categories=approved,
        slugs=event.get("slugs"),
        version_ids=event.get("version_ids"),
        call_trace=event.get("call_trace"),
        now=now_utc(),
    )
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：

```bash
uv run pytest tests/unit -q
uv run ruff check .
```

預期：所有單元測試通過；ruff 顯示 `All checks passed!`。

- [ ] **步驟 5：commit**

```bash
git add src/training_kb/handlers/analytics.py tests/unit/test_handlers_analytics.py pyproject.toml
git commit -m "feat(handlers): 加入 Analytics Lambda 回傳 Dashboard JSON"
```

---

## 7. 完成檢查清單

對應設計文件第 16 節切片 S7 的前半段：「原始資料重算成效」。

- [ ] `uv run pytest tests/unit -q` 全部通過。
- [ ] `uv run ruff check .` 沒有錯誤。
- [ ] 用設計文件 §11.2／§11.3 的資料重算，八個目標數字全部對得上：

```bash
uv run pytest tests/unit/test_analytics_metrics.py -k "reproduces or target" -v
```

預期：`test_version_metrics_reproduces_a_v1_targets`、`test_version_metrics_reproduces_a_v2_targets`、`test_dashboard_payload_reproduces_every_target_number` 全綠。

- [ ] 手動確認顯示值：

```bash
uv run python - <<'PY'
from training_kb.analytics import format_rate, format_rating
print("A v1 平均：", format_rating(23 / 8))     # 2.9
print("A v2 平均：", format_rating(44 / 10))    # 4.4
print("A v1 重開票率：", format_rate(7 / 10))   # 70%
print("A v2 重開票率：", format_rate(2 / 10))   # 20%
print("零評分：", format_rating(None))          # 尚無評分
print("零瀏覽：", format_rate(None))            # N/A（樣本不足）
PY
```

預期輸出：`2.9`、`4.4`、`70%`、`20%`、`尚無評分`、`N/A（樣本不足）`。

- [ ] 手動確認窗口端點：

```bash
uv run python - <<'PY'
from training_kb.analytics import reopen_window
start, end = reopen_window("2026-08-01T00:00:00Z")
print(start.isoformat(), "<= t <", end.isoformat())
PY
```

預期：`2026-08-01T00:00:00+00:00 <= t < 2026-08-15T00:00:00+00:00`。

- [ ] 五種不計入的情況都有各自的測試，而且沒有混進主表：

```bash
uv run pytest tests/unit/test_analytics_metrics.py -k "before_view or repeated_views or multiple_tickets or other_cluster or right_endpoint" -v
```

預期：5 個測試全綠。

- [ ] 確認 Analytics 沒有寫入任何資料：

```bash
grep -n "put_\|update_\|transact_\|delete_" src/training_kb/analytics.py src/training_kb/handlers/analytics.py
```

預期：沒有任何輸出。這一階段只讀不寫；寫入規則 status 是 Phase 20 的事。

- [ ] 確認呼叫數不會被猜出來：

```bash
uv run python - <<'PY'
from training_kb.analytics import dashboard_payload
import inspect
src = inspect.getsource(dashboard_payload)
print("沒有提供 trace 時回 None：", "None if call_trace is None else len(call_trace)" in src)
PY
```

預期：印出 `沒有提供 trace 時回 None： True`。

---

## 8. 常見錯誤與排除

**錯誤 1：`format_rating(23/8)` 得到 `2.8` 而不是 `2.9`**

- 症狀：顯示值比預期小一階。
- 原因：先自己做了 `round(avg, 1)` 再交給 `f"{...:.1f}"`，或是在 `average_rating` 裡就四捨五入過一次。連續兩次捨入會把 2.875 先變成 2.87 再變成 2.9 之外的值。
- 解法：`average_rating` 一律回傳原始除法結果；只在 `format_rating` 做一次 `f"{avg:.1f}"`。設計文件 §11.2 明講「指標判斷使用未四捨五入的數值」。

**錯誤 2：重開票率算成 7/7 = 100% 或 7/20 = 35%**

- 症狀：分母錯。
- 原因：分母用成「符合條件的人數」或「所有版本的瀏覽紀錄總數」。設計文件 §12.1 規定分母是「該窗口內 TUTORIAL_VIEW 的**不同 user**」，而且限定**這一版**。
- 解法：確認傳進 `reopen_stats` 的 `views` 來自 `repo.list_views_of_version(version_id)`，而且分母是 `len(first_view)`（去重後的人數）。

**錯誤 3：A v1 的重開票把 A v2 的工單也算進去**

- 症狀：A v1 的 `count` 變成 9。
- 原因：沒有做窗口過濾，或窗口用錯版本的 `published_at`。
- 解法：`reopen_stats` 一定要收到這一版的 `published_at`；`version_metrics` 裡用的是 `version.published_at`，不是 Tutorial 的任何欄位。用 `test_a_v1_reopen_is_seven_over_ten` 驗證（它傳的是兩版的全部工單）。

**錯誤 4：`TypeError: can't compare offset-naive and offset-aware datetimes`**

- 症狀：比較時間時爆掉。
- 原因：某一邊的 `datetime` 沒有時區。
- 解法：所有時間都要經過 `clock.parse_iso`，它會回傳帶 UTC 時區的 `datetime`。不要用 `datetime.fromisoformat` 直接解析結尾是 `Z` 的字串再拿去比較；也不要用 `datetime.now()`（沒有時區）。

**錯誤 5：零瀏覽的版本顯示 `0%`**

- 症狀：明明沒有人看過，Dashboard 卻顯示 0%，看起來像是「表現很好」。
- 原因：`rate` 用了 `len(matched_users) / max(viewers, 1)` 之類的寫法，或在 `format_rate` 把 `None` 當成 0。
- 解法：`viewers == 0` 時 `rate` 必須是 `None`；`format_rate(None)` 回傳「N/A（樣本不足）」。F42 明講零分母不可當成改善或惡化。

**錯誤 6：負面回饋數變成 10（8 + 2）**

- 症狀：同一筆回饋被算了兩次。
- 原因：用兩個迴圈分別數「低分」與「問題類別」再相加。
- 解法：`negative_feedback_ids` 回傳的是**集合**，重複的 ID 自動只算一次。設計文件 §12.1：「同筆同時命中只算一次」。

**錯誤 7：`ModuleNotFoundError: No module named 'tests'`**

- 症狀：`tests/unit/test_handlers_analytics.py` 匯入 `tests.unit.test_analytics_metrics` 時失敗。
- 原因：pytest 沒有把 repo 根目錄放進匯入路徑。
- 解法：在 `pyproject.toml` 加入

```toml
[tool.pytest.ini_options]
pythonpath = ["."]
```

再確認 `tests/` 與 `tests/unit/` 底下都有 `__init__.py`（沒有就用 `touch tests/__init__.py tests/unit/__init__.py` 建立空檔）。

**錯誤 8：`rule_counts` 少了某個狀態的鍵**

- 症狀：Dashboard 在 `payload["rule_counts"]["retired"]` 這一行拋 `KeyError`。
- 原因：只把出現過的 status 放進字典。
- 解法：先用 `{status.value: 0 for status in RuleStatus}` 把三個鍵都建好再累加。設計文件 §12.1：「分別計算 candidate、active、retired 的 RULE item」。

---

## 9. 這階段不做的事

| 不做的事 | 留給哪一階段 |
|---|---|
| 把 candidate 升為 active、判定衝突、規則退役、寫 `validated_at` | Phase 20（`20-Phase20-規則驗證與狀態轉換.md`）。`SeedBatch`、`RuleEvaluation`、`evaluate_batch`、`next_status`、`apply_rule_status`、`curation_groups` 都在下一階段。 |
| 核定種子批次的 JSON 與 `verify_recipe` 重算驗證 | Phase 21（`21-Phase21-Demo種子資料與可重算驗證.md`）。本階段的 fixture 只寫在測試檔裡，不是可載入的種子資料。 |
| 教學頁面上的圖表、版本選擇、diff 檢視 | Phase 22（`22-Phase22-S3靜態教學站.md`） |
| Streamlit Dashboard 的畫面、B 規則開關對照、把 `call_trace` 傳進來 | Phase 23（`23-Phase23-Demo控制台與Dashboard.md`） |
| 把 Analytics Lambda 加進 CDK stack 並部署 | Phase 23 與 Phase 25（`25-Phase25-安全檢查與Demo當日準備.md`）。本階段只寫 handler 程式碼與單元測試。 |
| 多組同篇前後配對的重開票率彙總權重 | 不在本計劃範圍。設計文件 §12.1 說彙總權重尚未定義，先逐組顯示，不自行用總 Ticket／總 View 判斷（本計劃選擇，對應 O4）。 |
| 宣稱評分提高是規則造成的 | 不做。設計文件 §12.3：評分差異與重開票率都是觀察結果，不宣稱因果。 |
| 統一 `pipelines/feedback.py` 內部的平均計算與本階段的 `average_rating` | 不在本階段。Phase 17 的 `task_collect` 為了門檻判定在內部算了一次平均，公式與 `average_rating` 相同；本階段不改動 Phase 17 的檔案，避免同時修改兩個階段的成果。 |

---

## 10. 對照：設計章節與 Rule 編號

### 主要責任：`docs/spec/features/檢視學習指標.feature`（設計文件 §20.11）

| Rule | 原文 | 本階段哪個 Task 落實 |
|---:|---|---|
| 1 | 平均評分以每個 TutorialVersion 的 rating 計算 | Task 1（`average_rating`、`cross_version_average`、`format_rating`） |
| 2 | 負面 Feedback 數計入 rating 不超過 2 或 category 屬負面的回饋 | Task 2（`negative_feedback_ids`，回傳集合所以不重複計算） |
| 3 | 同題重開票率計算看過教學的使用者在版本發布後 14 天內同 cluster 再開票的比例 | Task 3（`reopen_window`）、Task 4（`reopen_stats`） |
| 4 | 同題重開票率的分母取自教學瀏覽事件 | Task 4（分母是 `list_views_of_version` 去重後的 user 數） |
| 5 | 看過教學又開票的同一人比對穩定使用者 ID | Task 4（`first_view.get(ticket.author)`，直接比字串） |
| 6 | 規則效果比較套用與未套用版本的評分及同題重開票率差 | Task 6（`version_metrics` 提供前後對照需要的四個數字；真正的比較在 Phase 20） |
| 7 | 已學規則數依 RULE item 的 status 分別計數 | Task 5（`rule_counts`） |
| 8 | 規則套用次數等於 applied_to 清單長度 | Task 5（`applied_count`，由各版 `rules_applied` 重建並去重，對應 D17） |
| 9 | 每次執行的 Bedrock 呼叫數包含 Step Functions 內的呼叫節點與 Rote 層呼叫 | Task 5（`bedrock_call_count`）、Task 7（`call_trace` 由呼叫方提供） |
| 10 | Demo 指標以 seeded data 展示 | Task 7（`data_notice = "合成資料示範"`）；完整種子在 Phase 21 |
| 11 | Demo 對同題重開票率標明 proxy 與精確定義 | Task 7（同時輸出 `count`、`reopen_users`、`viewers`、`rate`，讓畫面可以標明筆數與比例的差別）；畫面文字在 Phase 23 |
| 12 | Demo 以同一批 Ticket 並排展示規則關閉與開啟產生的 Tutorial B | 不在本階段；Phase 23（兩份隔離預覽不寫入正式統計，F47） |

### 一併遵守：`docs/spec/features/收集教學回饋.feature`（設計文件 §20.9）

| Rule | 原文 | 本階段哪個 Task 落實 |
|---:|---|---|
| 10 | 同一使用者對同一版本的每次新提交都計一筆 | Task 1（`average_rating` 不依 user 去重，每一筆有效回饋都進分母） |

### 一併遵守：`docs/spec/features/驗證教學規則.feature`（設計文件 §20.13）

| Rule | 原文 | 本階段哪個 Task 落實 |
|---:|---|---|
| 1 | 規則成效比較套用組與同一篇教學套用前的已發布版本 | Task 6（`version_metrics` 是比較的輸入；比較本身在 Phase 20） |
| 8 | Analytics 寫入教學規則的驗證後 status | 不在本階段；Phase 20 的 `apply_rule_status` |

### 相關釐清決策

| 編號 | 內容 | 本階段落實位置 |
|---|---|---|
| D12 | 只有評分的回饋有效，只參與評分計算 | Task 1（`_rated` 只看 rating） |
| D13 | 核定類別表初始為「找不到按鈕」「缺少資訊」，未知值進待分類 | Task 2、Task 8（從 `get_config_list` 讀，可擴充） |
| D17 | 以版本的 `rules_applied` 為權威，`applied_to` 由它重建 | Task 5（`applied_count`） |
| D23 | 瀏覽、回饋與 Ticket 共用同一個穩定使用者 ID | Task 4 |
| D24 | 在 MVP 新增瀏覽事件，作為重開票率的分母來源 | Task 4 |
| D29 | 以教學首版的 `gap:<cluster_id>` 作為固定對應 | Task 6（`cluster_id` 取自 `Tutorial.cluster_id`，不比 topic 文字） |
| F41 | 分子只計在瀏覽之後、且窗口結束前同群開票的使用者 | Task 4（`viewed_at < moment`） |
| F42 | 沒有可識別瀏覽者時顯示 N/A 與樣本不足 | Task 3（`format_rate(None)`）、Task 4（`rate = None`） |
| F43 | 已核定的問題類別都屬負面；待分類不因 category 計入；rating ≤ 2 仍獨立計入 | Task 2 |
| F44 | 先算每版平均再等權平均 | Task 1（`cross_version_average`） |
| F45 | 計算每次實際送出的呼叫嘗試，包含重試、每個 Map item 與 Rote 呼叫 | Task 5（`trace.count()` 以嘗試為單位） |
| F46 | 由完整 seeded 資料實時計算；2.9、4.4、7、2 是資料必須能重現的目標 | Task 6、Task 7（測試直接以設計文件 §11.2／§11.3 的資料重算） |
| F52 | 沒有任何有效評分時顯示「尚無評分」，內部值為 null | Task 1 |
| O4（待確認） | 時間與比較邊界。**本計劃選擇**：全部 UTC、窗口 `[p, p+14 天)`、多組 rate 先逐組顯示 | Task 3、第 9 節 |

---

## 11. 參考來源

### 設計文件章節（`docs/design/training-kb.md`）

- §11.2 可重算的評分與負面回饋（A v1 八筆／2.875／2.9／負面 8；A v2 十筆／4.4／負面 2；未四捨五入的判斷值）
- §11.3 可重算的瀏覽、重開票筆數與比例（模擬 published_at、十人瀏覽、七／二張工單、cluster c12、70%／20%、五種必須分開測的情況）
- §11.5 Demo 的資料與即時執行分開標示（「合成資料示範」）
- §12.1 指標公式（每版平均、跨版等權平均、負面回饋、重開票筆數與率、已學規則數、規則套用次數、Bedrock 呼叫數；窗口定義與 O4）
- §12.3 指標不能替代的證據（呼叫數須由逐次 trace 核對，不為配合表格而刪掉 embedding 或 retry）
- §13 Demo UI 與 S3 教學頁（Dashboard 四個區塊）
- §15 測試與驗收設計（「Analytics」列：零評分／零瀏覽、先開票後瀏覽不計分子、重複瀏覽與多次開票分別去重、2.9／4.4 與 7／2 可由配方重算）
- §16 交付切片 S7
- §18 待確認事項 O4
- §19.1／§19.2 釐清決策 D12、D13、D17、D23、D24、D29、F41–F46、F52
- §20.9／§20.11／§20.13 逐條 Rule 與負責模組

### 規格檔

- `docs/spec/features/檢視學習指標.feature`（12 條 Rule，含 R-007 套用次數為 3 的 Example 與 Demo 指標表）
- `docs/spec/features/收集教學回饋.feature`（Rule 10）
- `docs/spec/features/驗證教學規則.feature`（Rule 1、Rule 8）
- `docs/spec/erm.dbml`（FEEDBACK、TUTORIAL_VIEW、AUTHORING_RULE、TICKET 的欄位註解）
- `docs/spec/.clarify/resolved/features/檢視學習指標_重開票率是否要求瀏覽發生在再次開票之前.md`（F41 解決記錄）
- `docs/spec/.clarify/resolved/features/檢視學習指標_沒有可識別瀏覽者時重開票率如何顯示.md`（F42 解決記錄）
- `docs/spec/.clarify/resolved/features/檢視學習指標_版本沒有任何有效評分時平均評分如何呈現.md`（F52 解決記錄）

### 外部官方文件

- Python `datetime` 與 `timedelta`（tz-aware 比較）：<https://docs.python.org/3/library/datetime.html>
- Python 格式化規格（`f"{value:.1f}"` 的捨入行為）：<https://docs.python.org/3/library/string.html#format-specification-mini-language>
- Python `dataclasses`（`frozen=True`）：<https://docs.python.org/3/library/dataclasses.html>
- pydantic v2 `model_fields`：<https://docs.pydantic.dev/latest/api/base_model/#pydantic.BaseModel.model_fields>
- pytest `monkeypatch`：<https://docs.pytest.org/en/stable/how-to/monkeypatch.html>
- pytest `approx`：<https://docs.pytest.org/en/stable/reference/reference.html#pytest-approx>
- pytest `pythonpath` 設定：<https://docs.pytest.org/en/stable/reference/reference.html#confval-pythonpath>
- AWS Lambda Python handler 定義（`handler(event, context)`）：<https://docs.aws.amazon.com/lambda/latest/dg/python-handler.html>
- AWS Lambda Invoke API（維護者以 SDK 呼叫，不開放公開 URL）：<https://docs.aws.amazon.com/lambda/latest/dg/API_Invoke.html>
