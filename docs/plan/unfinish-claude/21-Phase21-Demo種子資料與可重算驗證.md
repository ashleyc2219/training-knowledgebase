# Phase 21：Demo 種子資料與可重算驗證

| 項目 | 內容 |
|---|---|
| 上一階段 | Phase 20：規則驗證與狀態轉換（`20-Phase20-規則驗證與狀態轉換.md`） |
| 下一階段 | Phase 22：S3 靜態教學站（`22-Phase22-S3靜態教學站.md`） |
| 對應設計文件章節 | §11（全節）、§12.3、§15、O7、F01、F46（`docs/design/training-kb.md`） |
| 對應交付切片 | S6–S8（設計文件第 16 節） |
| 預估時間 | 約 7 小時 |
| 做完會得到 | 一整套可載入的合成種子資料，以及一支能用真實程式重算出 2.875／4.4／8／2／7／2／0.7／0.2 的驗證工具。 |

---

## 1. 這階段做完會得到什麼

設計文件第 11 節只給了「配方」——它描述應該有哪些資料、算出來應該是多少，但**沒有實際的 JSON 檔**。這一階段就是把配方展開成真的檔案，並且證明那些數字真的算得出來。

做完之後你會有：

1. `demo/seed/` 底下九個種子檔：`features.json`、`tickets.json`、`tutorials/`（四個版本檔）、`releases.json`、`feedback.json`、`views.json`、`reopen_tickets.json`、`rules.json`、`batches.json`。**每一筆資料都是完整寫出來的**，沒有「以此類推」。
2. `demo/seed_loader.py`：把種子載進 DynamoDB 與 S3 的工具，以及 `verify_recipe()`——用 Phase 19 的真實函式重算指標並與目標值比對。
3. `demo/verify_clusters.py`：對 20 筆工單**真的呼叫 Titan** 算 embedding、做 cosine 分群，印出分群結果與每群筆數。這是為了回應設計文件 §11.1 的要求：「不能只把所有 cluster_id 寫成 c12 就聲稱已測過分群」。
4. 一套「核定流程」：配方展開後**先跑驗證、再由人工核定**，批次才能標成 `approved: true`（對應設計文件待確認事項 O7）。

做完之後，Phase 20 的 `validate_rule()` 就有真的批次可以讀，Phase 22 的教學站就有真的教學可以顯示，Phase 23 的 Dashboard 就有真的數字可以畫。

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
                                                                                        |
展示與驗收層    21 Demo 種子資料 -> 22 靜態教學站 -> 23 Demo 控制台 -> 24 失敗復原驗收 -> 25 安全與當日準備
                ^^^^^^^^^^^^^^^
                你在這裡
```

你在「展示與驗收層」的第一格。前面 20 個階段做出來的程式，到這裡第一次有真的資料可以跑完整條路。

---

## 3. 開始前檢查

### 3.1 前置條件

| 條件 | 為什麼需要 |
|---|---|
| Phase 02 完成 | 需要 `Feature`、`Ticket`、`Release`、`Feedback`、`TutorialView`、`AuthoringRule`、`TutorialContent` 等模型與 `parse_version_id`。 |
| Phase 03 完成 | 需要 `Repository` 的 `put_meta` / `put_object` / `update_meta`。 |
| Phase 07 完成 | 需要 `create_tutorial`、`create_version`、`VersionPlan`、`verify_version_complete`。 |
| Phase 08 完成 | 需要 `SiteRenderer`、`publish_to_site`。 |
| Phase 15 完成 | 需要 `validate_feedback`、`validate_view`（載入前先驗欄位）。 |
| Phase 19 完成 | 需要 `version_metrics`（`verify_recipe` 用它重算）。 |
| Phase 20 完成 | 需要 `SeedBatch`、`batch_key`（批次要寫到 S3 的 `operations/rule-batches/`）。 |
| Phase 04 完成且 `.env` 已填好 | `demo/verify_clusters.py` 要真的呼叫 Bedrock Titan。 |

### 3.2 驗證指令與預期輸出

```bash
cd ~/AWS-Hackathon
uv run python -c "
from training_kb.models import Feature, Ticket, Release, Feedback, TutorialView, AuthoringRule, TutorialContent, parse_version_id
from training_kb.content import create_tutorial, create_version, VersionPlan, verify_version_complete
from training_kb.site import SiteRenderer, publish_to_site
from training_kb.ingress import validate_feedback, validate_view
from training_kb.analytics import version_metrics, SeedBatch, batch_key
print('前置介面齊全')
"
```

預期輸出：

```text
前置介面齊全
```

任何一行 `ImportError` 都代表對應階段還沒做完，先回去補。

```bash
uv run pytest -q
```

預期：全部 PASS。

確認 `demo/` 目錄存在（Phase 01 建立的骨架）：

```bash
ls demo/
```

預期：至少看到 `seed/` 或空目錄。若沒有 `demo/seed/tutorials/`，先建立：

```bash
mkdir -p demo/seed/tutorials
```

---

## 4. 名詞小抄

| 名詞 | 白話解釋 | 在本階段哪裡用到 |
|---|---|---|
| 種子資料（seed data） | 事先準備好、用來展示與驗收的假資料。它是**合成的**，不是真實使用者留下的。 | 全部 Task |
| 合成資料示範 | 畫面與檔案上必須固定標示的字樣，避免把假資料當成實測結果（設計文件 F01、§11.5）。 | 全部 Task |
| 配方（recipe） | 設計文件第 11 節寫的「應該有哪些資料、算出來應該是多少」。本階段把它展開成檔案。 | §5、Task 8 |
| 可重算（recomputable） | 展示的數字不是寫死的，而是由完整原始資料用真的程式算出來（設計文件 F46）。 | Task 8 |
| 核定批次（approved batch） | 人工確認過的驗收資料包。Phase 20 只接受 `approved: true` 的批次改規則狀態。 | Task 7 |
| O7 | 設計文件第 18 節待確認事項編號，指「核定種子與外部設定」。**本計劃選擇**：配方展開 → 程式驗證重算值 → 人工核定 → 才標成 `approved: true`。 | Task 7 |
| cluster_id | 同題分群編號。教學 A 固定對應 `c12`（設計文件 D29：以首版的 `gap:<cluster_id>` 為準）。 | Task 2、Task 4 |
| 模擬 published_at | 為了讓 14 天窗口算得出來而指定的假發布時間（A v1＝2026-08-01、A v2＝2026-08-20）。它**不是**本次真實發布時間（設計文件 §11.3、§11.5）。 | Task 3 |
| 試用版本（trial version） | A v2 是 R-007 這條 candidate 規則的「明示種子試用版本」。正式寫作永遠只用 active 規則，不會自己試用 candidate（設計文件 F27）。 | Task 3、Task 6 |
| 相對日期欄位 | 工單時間必須落在「執行當日及前 13 個 UTC 日期」才算 recurring，所以種子檔存 `ts_offset_days`（距今幾天），載入時用 `now` 重算成真的時間。 | Task 2 |
| 隔離預覽（demo/previews） | B 教學「規則關閉／開啟」的兩份對照產物。它們只是 Demo 產物，不寫入正式教學、回饋或統計（設計文件 F47）。 | §9 |
| Titan embedding | Amazon 的文字轉向量模型 `amazon.titan-embed-text-v2:0`，輸出 1024 維向量。用來判斷兩則工單問的是不是同一件事。 | Task 9 |
| cosine（餘弦相似度） | 兩個向量的夾角相似度，範圍 -1 到 1。越接近 1 代表兩段文字越像。本案門檻是 0.85。 | Task 9 |

---

## 5. 設計說明

### 5.1 種子資料之間的關係

```text
                       features.json
                 ┌───────────┴────────────┬──────────────────────┐
                 v                        v                      v
        FEATURE#Prepare          FEATURE#Share Summary   FEATURE#Notification Settings
        name=Meeting Summary
        aliases=[]
                 ^                        ^                      ^
                 │ REFERENCES             │ REFERENCES           │ REFERENCES
                 │ （每步恰好一條）         │                      │
                 │                        │                      │
    ┌────────────┴────────────┐           │                      │
    │  STEP#prepare-meeting   │           │                      │
    │       @v1#3 / @v2#3     │           │                      │
    └────────────┬────────────┘           │                      │
                 │                        │                      │
        tutorials/prepare-meeting.v1.json │                      │
        tutorials/prepare-meeting.v2.json │                      │
        tutorials/share-summary.v1.json ──┘                      │
        tutorials/notification-settings.v1.json ─────────────────┘
                 │
                 │  建立 TUTORIAL / VERSION / STEP
                 v
        TUTORIAL#prepare-meeting  (cluster_id = c12, current_version = @v2)
             │              │
             │ v1           │ v2   <── SUPERSEDES ── v1
             v              v
   VERSION#prepare-meeting@v1   VERSION#prepare-meeting@v2
   published_at=2026-08-01      published_at=2026-08-20
   rules_applied=[]             rules_applied=["R-007"]
             ^      ^                   ^      ^
             │      │                   │      │
   REFERS_TO │      │ (view)  REFERS_TO │      │ (view)
             │      │                   │      │
     feedback.json  views.json   feedback.json  views.json
     f_12..f_40     u_01..u_10   f_101..f_110   u_01..u_10
     （8 筆）        （10 筆）      （10 筆）       （10 筆）

        reopen_tickets.json                    rules.json
        t_2001..t_2007 (A v1 窗口)             R-007 candidate
        t_2101..t_2102 (A v2 窗口)               evidence = f_12..f_40（8 筆）
        全部 cluster_id = c12                    derived_from = prepare-meeting@v1
        author = u_01..u_07 / u_01..u_02         applies_when = {"step.type":"click_ui"}
                                               R-012 active（退役展示用）
        releases.json
        r_42  renamed  Meeting Summary -> Prepare        batches.json
        source_event_id = "42"（人看的 PR #42）           b_r007_01   (R-007)
                                                         b_r012_01   (R-012 第一批)
        tickets.json                                     b_r012_02   (R-012 第二批)
        t_0801..t_0820（20 筆，相對日期）                  批次自帶完整回饋／瀏覽／工單
```

### 5.2 種子檔的目錄結構

```text
demo/
  seed/
    features.json                        3 個 Feature
    tickets.json                        20 筆建立教學用工單（相對日期）
    reopen_tickets.json                  9 筆同題重開票工單（固定 2026-08 時間）
    releases.json                        1 筆 r_42
    feedback.json                       18 筆（A v1 八筆 + A v2 十筆）
    views.json                          20 筆（每版 u_01..u_10 各一筆）
    rules.json                           2 條（R-007、R-012）
    batches.json                         3 個核定種子批次
    tutorials/
      prepare-meeting.v1.json            A v1（四步五段）
      prepare-meeting.v2.json            A v2（R-007 明示試用版本）
      share-summary.v1.json              B v1（不引用 Prepare）
      notification-settings.v1.json      C v1（不引用 Prepare）
  seed_loader.py                         load_* / verify_recipe / approve_batch
  verify_clusters.py                     真的呼叫 Titan 驗證分群
```

### 5.3 載入與驗證的順序

```text
  1. load_features(repo, "demo/seed/features.json")
         └── 先有 Feature，之後每個步驟才驗得過「恰好一個既有 Feature」

  2. load_tutorials(repo, "demo/seed/tutorials", renderer, now)
         ├── create_tutorial + create_version（重用 Phase 07 的程式）
         ├── verify_version_complete() 核對全文、步驟、引用是否齊全
         ├── 直接寫模擬 published_at 與 current_version（不呼叫 content.publish）
         └── publish_to_site() 產生 site/ 頁面

  3. load_tickets(repo, "demo/seed/tickets.json", now=now)          20 筆，相對日期
     load_tickets(repo, "demo/seed/reopen_tickets.json", now=now)    9 筆，固定日期
     load_releases(repo, "demo/seed/releases.json")                  1 筆
     load_feedback(repo, "demo/seed/feedback.json")                 18 筆 + REFERS_TO 邊
     load_views(repo, "demo/seed/views.json")                       20 筆
     load_rules(repo, "demo/seed/rules.json")                        2 條

  4. load_batches("demo/seed/batches.json") -> list[SeedBatch]
     verify_batch_matches_seed(...)    批次內的記錄要和單獨的種子檔一模一樣
     寫到 S3 operations/rule-batches/<batch_id>.json

  5. verify_recipe(repo, approved_categories=[...])
         └── 用 Phase 19 的 version_metrics 重算，比對 EXPECTED_RECIPE

  6. uv run python demo/verify_clusters.py
         └── 真的呼叫 Titan，印出分群結果與每群筆數

  7. 人工看過 5、6 的輸出 → approve_batch() 把 approved 改成 true（O7）

  8. Phase 20 的 validate_rule() 才會採用這些批次
```

### 5.4 為什麼要「先展開、再核定」

設計文件第 18 節的 O7 寫得很清楚：repo 目前只有故事與目標數字，沒有核定批次。「核定」的意思是**有人看過、確認這批資料真的能重算出目標值**，而不是「檔案存在就算數」。

因此 `batches.json` 一開始所有批次都是 `"approved": false`。Phase 20 的 `validate_rule()` 讀到 `approved=false` 會判成「不可判定」，狀態一律維持原狀。只有在 `verify_recipe()` 與 `verify_clusters.py` 都跑過、輸出被人看過之後，才用 `approve_batch()` 把它改成 `true`。

這不是多此一舉：它讓「規則被啟用」這件事永遠有一個人工確認點，而且那個確認點的依據是可重算的數字，不是一句「看起來沒問題」。

### 5.5 三個數字為什麼會是那樣

| 指標 | A v1 | A v2 | 怎麼來的 |
|---|---|---|---|
| 平均評分 | 2.875 | 4.4 | v1：(2+2+3+3+3+3+3+4) ÷ 8 = 23 ÷ 8。v2：(2+2+5×8) ÷ 10 = 44 ÷ 10。顯示一位小數是 2.9 與 4.4，但門檻判斷用未四捨五入的值（設計文件 §11.2）。 |
| 負面回饋數 | 8 | 2 | 「rating ≤ 2」**或**「category 屬核定問題類別」的 Feedback ID 集合大小。v1 八筆全部 category＝找不到按鈕，所以是 8（不是 2+8=10）。v2 只有 f_101、f_102 命中。 |
| 同題重開票筆數 | 7 | 2 | 符合「先瀏覽後開票、在 14 天窗口內、cluster_id 相同」的不同 Ticket ID 數。 |
| 同題重開票率 | 0.7 | 0.2 | 分子＝符合條件的**不同開票使用者數**（7／2），分母＝該版窗口內的**不同瀏覽者數**（10／10）。 |

窗口定義：`[published_at, published_at + 14 天)`，左含右不含（設計文件 O4，**本計劃選擇**）。
- A v1：`[2026-08-01T00:00:00Z, 2026-08-15T00:00:00Z)`，瀏覽在 08-02T09:00、開票在 08-03T10:00，都在窗口內，且開票時間晚於瀏覽時間。
- A v2：`[2026-08-20T00:00:00Z, 2026-09-03T00:00:00Z)`，瀏覽在 08-21T09:00、開票在 08-22T10:00。

---

## 6. 工作項目

### Task 1：Feature 清單與載入

**目的**：建立三個 Feature 的種子檔並寫進 DynamoDB。

**檔案**：
- 新增：`demo/seed/features.json`
- 新增：`demo/seed_loader.py`
- 測試：`tests/integration/test_seed_features.py`

**介面**：
- 消費（Phase 02）：`models.Feature`
- 消費（Phase 03、09）：`repo.put_meta(pk, attrs)`、`repo.get_feature(feature_id)`、`repo.list_features()`
- 消費（Phase 02）：`keys.feature_pk(feature_id)`
- 產出：
  - `demo.seed_loader.SEED_DIR`（`Path`，指向 `demo/seed`）
  - `demo.seed_loader.SYNTHETIC_NOTE = "合成資料示範"`
  - `demo.seed_loader.read_items(path) -> list[dict]`（**簡報第 6 節未列，本階段新增**：讀種子檔的 `items` 陣列）
  - `demo.seed_loader.load_features(repo, path) -> list[str]`（回傳寫入的 `feature_id` 清單）

**設計文件依據**：§11.1「產品功能清單：每個 Feature 的固定 PK、目前 name、aliases；包含 FEATURE#Prepare，名稱不可與其他功能撞名」。`Prepare` 是 PK 後綴，改版前的 `name` 是 `Meeting Summary`、`aliases` 是空的——PR #42 之後才會變成 `name=Prepare`、`aliases=["Meeting Summary"]`（設計文件 D06：改名不遷移 PK）。

- [ ] **步驟 1：寫測試**

```python
# tests/integration/test_seed_features.py
"""Phase 21 Task 1：Feature 種子檔與載入。"""

import json
from pathlib import Path

from moto import mock_aws

from demo.seed_loader import SEED_DIR, load_features, read_items

FEATURES_PATH = SEED_DIR / "features.json"


def test_種子檔存在且標示合成資料():
    raw = json.loads(FEATURES_PATH.read_text(encoding="utf-8"))
    assert "合成資料示範" in raw["note"]


def test_三個_feature_的固定值正確():
    items = read_items(FEATURES_PATH)
    by_id = {item["feature_id"]: item for item in items}

    assert set(by_id) == {"Prepare", "Share Summary", "Notification Settings"}
    assert by_id["Prepare"]["name"] == "Meeting Summary"
    assert by_id["Prepare"]["aliases"] == []
    assert by_id["Share Summary"]["name"] == "Share Summary"
    assert by_id["Notification Settings"]["name"] == "Notification Settings"
    for item in items:
        assert item["first_seen"].endswith("Z")


def test_名稱與_alias_互不撞名():
    items = read_items(FEATURES_PATH)
    names = [item["name"] for item in items]
    aliases = [alias for item in items for alias in item["aliases"]]

    assert len(names) == len(set(names))
    assert not (set(names) & set(aliases))


@mock_aws
def test_載入後可以從_repository_讀回(repository):
    written = load_features(repository, FEATURES_PATH)

    assert written == ["Notification Settings", "Prepare", "Share Summary"]
    prepare = repository.get_feature("Prepare")
    assert prepare is not None
    assert prepare.name == "Meeting Summary"
    assert prepare.aliases == []
    assert len(repository.list_features()) == 3


@mock_aws
def test_重複載入不會變成六筆(repository):
    load_features(repository, FEATURES_PATH)
    load_features(repository, FEATURES_PATH)

    assert len(repository.list_features()) == 3


def test_read_items_能吃_Path_也能吃字串():
    from_path = read_items(FEATURES_PATH)
    from_str = read_items(str(FEATURES_PATH))
    assert from_path == from_str
    assert isinstance(Path(FEATURES_PATH), Path)
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：`uv run pytest tests/integration/test_seed_features.py -v`

預期：FAIL，錯誤訊息是 `ModuleNotFoundError: No module named 'demo.seed_loader'`（`demo/seed_loader.py` 還不存在）。

- [ ] **步驟 3：寫最少的程式讓測試通過**

先建立 `demo/seed/features.json`：

```json
{
  "note": "合成資料示範。這是設計文件 §11.1 配方展開的產品功能清單，不是真實觀測資料。feature_id 是 DynamoDB PK 的後綴，第一次建立後不再變更（設計文件 D06）；PR #42 之後只改 name 與 aliases。",
  "items": [
    {
      "feature_id": "Prepare",
      "name": "Meeting Summary",
      "aliases": [],
      "first_seen": "2026-07-01T00:00:00Z"
    },
    {
      "feature_id": "Share Summary",
      "name": "Share Summary",
      "aliases": [],
      "first_seen": "2026-07-01T00:00:00Z"
    },
    {
      "feature_id": "Notification Settings",
      "name": "Notification Settings",
      "aliases": [],
      "first_seen": "2026-07-01T00:00:00Z"
    }
  ]
}
```

再建立 `demo/seed_loader.py`：

```python
"""Demo 種子資料載入工具。

所有資料都是設計文件第 11 節配方展開的**合成資料**，不是真實觀測結果
（設計文件 F01：不得把合成資料描述為原始觀測或實測結果）。
"""

from __future__ import annotations

import json
from pathlib import Path

from training_kb.keys import feature_pk
from training_kb.models import Feature
from training_kb.repository import Repository

SEED_DIR = Path(__file__).resolve().parent / "seed"
SYNTHETIC_NOTE = "合成資料示範"


def read_items(path: str | Path) -> list[dict]:
    """讀種子檔並回傳 items 陣列。種子檔一律是 {"note": ..., "items": [...]}。"""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return list(raw["items"])


def load_features(repo: Repository, path: str | Path) -> list[str]:
    """載入 Feature 清單，回傳寫入的 feature_id（依 feature_id 排序）。"""
    written: list[str] = []
    for item in read_items(path):
        feature = Feature.model_validate(item)
        repo.put_meta(
            feature_pk(feature.feature_id),
            {
                "entity": "FEATURE",
                "feature_id": feature.feature_id,
                "name": feature.name,
                "aliases": list(feature.aliases),
                "first_seen": feature.first_seen,
            },
        )
        written.append(feature.feature_id)
    return sorted(written)
```

如果 `demo/` 還沒有 `__init__.py`，建立一個空檔讓 `from demo.seed_loader import ...` 能運作：

```bash
touch demo/__init__.py
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：`uv run pytest tests/integration/test_seed_features.py -v`

預期：PASS，6 passed。

- [ ] **步驟 5：commit**

```bash
git add demo/__init__.py demo/seed/features.json demo/seed_loader.py tests/integration/test_seed_features.py
git commit -m "feat(demo): 新增 Feature 種子清單與載入工具"
```

---

### Task 2：20 筆建立教學用工單（相對日期）

**目的**：把設計文件 §11.1 的「20 筆不同 t_ ID、相同功能不同問法、時間落在執行當日及前十三個 UTC 日期」展開成檔案。

**檔案**：
- 新增：`demo/seed/tickets.json`
- 修改：`demo/seed_loader.py`
- 測試：`tests/integration/test_seed_tickets.py`

**介面**：
- 消費（Phase 01）：`clock.now_utc()`、`clock.to_iso(dt)`、`clock.utc_date(dt)`
- 消費（Phase 02）：`models.Ticket`、`keys.ticket_pk`
- 產出：
  - `demo.seed_loader.resolve_ticket_ts(item, *, now) -> str`（**本階段新增**：把 `ts_offset_days` + `ts_time` 或固定 `ts` 換算成 ISO 字串）
  - `demo.seed_loader.load_tickets(repo, path, *, now=None) -> list[str]`

**時間怎麼算（本計劃選擇）**：

種子檔不能寫死絕對日期，否則過幾天就跑出「14 天窗口外」的結果。所以：

- 種子檔的每筆工單存 `ts_offset_days`（0＝執行當日，1..13＝前 N 個 UTC 日期）與 `ts_time`（`HH:MM:SS`）。
- 載入時計算：`ts = (utc_date(now) - timedelta(days=ts_offset_days))` 這一天的 `ts_time`，時區固定 UTC。
- 若某筆工單直接給了 `ts`（例如重開票工單需要固定在 2026-08），就用它，不做換算。

這樣 20 筆工單永遠落在「當日及前 13 個 UTC 日期」內，符合設計文件 F11 的 recurring 窗口。

分群設計（**本計劃選擇**）：20 筆分成三組不同功能的問法——12 筆問「會前摘要」（對應 A）、5 筆問「分享摘要」（對應 B）、3 筆問「通知設定」（對應 C）。這樣 Task 9 的分群驗證才有東西可驗：至少有兩群達到 recurring 門檻 5 筆，一群不足 5 筆。如果 20 筆全寫成同一個問題，「驗證過分群」就沒有意義。

種子檔裡 `cluster_id` 與 `feature_ids` 都留空（接入態）——這兩個欄位是 Ticket Analysis 分析後才補入的（設計文件 §7.1）。

- [ ] **步驟 1：寫測試**

```python
# tests/integration/test_seed_tickets.py
"""Phase 21 Task 2：20 筆建立教學用工單與相對日期換算。"""

from datetime import date, datetime, timezone

from moto import mock_aws

from demo.seed_loader import SEED_DIR, load_tickets, read_items, resolve_ticket_ts
from training_kb.clock import parse_iso, utc_date

TICKETS_PATH = SEED_DIR / "tickets.json"
NOW = datetime(2026, 9, 13, 12, 0, 0, tzinfo=timezone.utc)


def test_剛好二十筆且_id_不重複():
    items = read_items(TICKETS_PATH)
    ids = [item["id"] for item in items]

    assert len(items) == 20
    assert len(set(ids)) == 20
    assert all(tid.startswith("t_") for tid in ids)


def test_每筆都有必填欄位且枚舉合法():
    for item in read_items(TICKETS_PATH):
        assert item["source"] in {"github_issue", "discord", "email"}
        assert item["text"].strip() != ""
        assert item["author"].startswith("u_")
        assert item["project_id"] == "demo-project"
        assert 0 <= item["ts_offset_days"] <= 13
        assert item["cluster_id"] is None
        assert item["feature_ids"] == []


def test_文字是中文且互不重複():
    texts = [item["text"] for item in read_items(TICKETS_PATH)]
    assert len(set(texts)) == 20
    assert all(any("一" <= ch <= "鿿" for ch in text) for text in texts)


def test_三組問法的筆數符合分群設計():
    items = read_items(TICKETS_PATH)
    groups: dict[str, int] = {}
    for item in items:
        groups[item["expected_group"]] = groups.get(item["expected_group"], 0) + 1

    assert groups == {"A-prepare": 12, "B-share": 5, "C-notify": 3}


def test_resolve_ticket_ts_以_now_往前推算():
    item = {"ts_offset_days": 3, "ts_time": "09:10:00"}
    assert resolve_ticket_ts(item, now=NOW) == "2026-09-10T09:10:00Z"

    item_zero = {"ts_offset_days": 0, "ts_time": "23:59:59"}
    assert resolve_ticket_ts(item_zero, now=NOW) == "2026-09-13T23:59:59Z"


def test_resolve_ticket_ts_有固定_ts_時直接使用():
    item = {"ts": "2026-08-03T10:00:00Z"}
    assert resolve_ticket_ts(item, now=NOW) == "2026-08-03T10:00:00Z"


@mock_aws
def test_載入後所有工單都在十四天窗口內(repository):
    written = load_tickets(repository, TICKETS_PATH, now=NOW)

    assert len(written) == 20
    tickets = repository.list_tickets("demo-project")
    assert len(tickets) == 20

    earliest = date(2026, 8, 31)  # 2026-09-13 減 13 天
    latest = date(2026, 9, 13)
    for ticket in tickets:
        day = utc_date(parse_iso(ticket.ts))
        assert earliest <= day <= latest


@mock_aws
def test_載入的工單尚未分群(repository):
    load_tickets(repository, TICKETS_PATH, now=NOW)

    for ticket in repository.list_tickets("demo-project"):
        assert ticket.cluster_id is None
        assert ticket.feature_ids == []
        assert ticket.embedding is None
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：`uv run pytest tests/integration/test_seed_tickets.py -v`

預期：FAIL，`ImportError: cannot import name 'load_tickets' from 'demo.seed_loader'`。

- [ ] **步驟 3：寫最少的程式讓測試通過**

建立 `demo/seed/tickets.json`：

```json
{
  "note": "合成資料示範。設計文件 §11.1 配方展開的 20 筆建立教學用工單，不是真實使用者提問。ts 由 ts_offset_days 與 ts_time 在載入時以 now 重算：先取 now 的 UTC 日期，往前推 ts_offset_days 天，再套上 ts_time（UTC）。offset 只允許 0..13，對應設計文件 F11 的『當日及前十三個 UTC 日期』。expected_group 只是給人看的分組提示，不寫入 DynamoDB；實際 cluster_id 由 Ticket Analysis 計算。",
  "items": [
    {"id": "t_0801", "source": "github_issue", "text": "會前摘要在哪裡開啟？", "author": "u_01", "ts_offset_days": 0, "ts_time": "09:10:00", "project_id": "demo-project", "cluster_id": null, "feature_ids": [], "expected_group": "A-prepare"},
    {"id": "t_0802", "source": "github_issue", "text": "如何看到開會前整理的重點？", "author": "u_02", "ts_offset_days": 1, "ts_time": "10:20:00", "project_id": "demo-project", "cluster_id": null, "feature_ids": [], "expected_group": "A-prepare"},
    {"id": "t_0803", "source": "discord", "text": "請問準備會議的摘要功能要去哪一頁找？", "author": "u_03", "ts_offset_days": 2, "ts_time": "11:05:00", "project_id": "demo-project", "cluster_id": null, "feature_ids": [], "expected_group": "A-prepare"},
    {"id": "t_0804", "source": "discord", "text": "我想在開會前先看整理好的重點，要怎麼做？", "author": "u_04", "ts_offset_days": 3, "ts_time": "13:40:00", "project_id": "demo-project", "cluster_id": null, "feature_ids": [], "expected_group": "A-prepare"},
    {"id": "t_0805", "source": "email", "text": "會議開始前的摘要要按哪個按鈕才會出現？", "author": "u_05", "ts_offset_days": 4, "ts_time": "08:55:00", "project_id": "demo-project", "cluster_id": null, "feature_ids": [], "expected_group": "A-prepare"},
    {"id": "t_0806", "source": "github_issue", "text": "找不到產生會前摘要的入口", "author": "u_06", "ts_offset_days": 5, "ts_time": "15:30:00", "project_id": "demo-project", "cluster_id": null, "feature_ids": [], "expected_group": "A-prepare"},
    {"id": "t_0807", "source": "discord", "text": "開會前的重點整理在哪裡看得到？", "author": "u_07", "ts_offset_days": 6, "ts_time": "09:45:00", "project_id": "demo-project", "cluster_id": null, "feature_ids": [], "expected_group": "A-prepare"},
    {"id": "t_0808", "source": "email", "text": "怎麼讓系統幫我先整理會議重點？", "author": "u_08", "ts_offset_days": 7, "ts_time": "14:15:00", "project_id": "demo-project", "cluster_id": null, "feature_ids": [], "expected_group": "A-prepare"},
    {"id": "t_0809", "source": "github_issue", "text": "準備會議的摘要一直沒出現，是要先設定什麼嗎？", "author": "u_09", "ts_offset_days": 8, "ts_time": "16:05:00", "project_id": "demo-project", "cluster_id": null, "feature_ids": [], "expected_group": "A-prepare"},
    {"id": "t_0810", "source": "discord", "text": "請問哪裡可以查看開會前自動整理的內容？", "author": "u_10", "ts_offset_days": 9, "ts_time": "10:50:00", "project_id": "demo-project", "cluster_id": null, "feature_ids": [], "expected_group": "A-prepare"},
    {"id": "t_0811", "source": "email", "text": "會前摘要的按鈕位置在哪？我在會議頁找不到", "author": "u_01", "ts_offset_days": 10, "ts_time": "11:35:00", "project_id": "demo-project", "cluster_id": null, "feature_ids": [], "expected_group": "A-prepare"},
    {"id": "t_0812", "source": "github_issue", "text": "開會之前想先讀摘要，應該從哪裡進入？", "author": "u_02", "ts_offset_days": 11, "ts_time": "09:20:00", "project_id": "demo-project", "cluster_id": null, "feature_ids": [], "expected_group": "A-prepare"},
    {"id": "t_0813", "source": "github_issue", "text": "開完會之後要怎麼把摘要分享給同事？", "author": "u_03", "ts_offset_days": 1, "ts_time": "14:00:00", "project_id": "demo-project", "cluster_id": null, "feature_ids": [], "expected_group": "B-share"},
    {"id": "t_0814", "source": "discord", "text": "請問會議摘要可以寄給沒有參加的人嗎？", "author": "u_04", "ts_offset_days": 3, "ts_time": "15:25:00", "project_id": "demo-project", "cluster_id": null, "feature_ids": [], "expected_group": "B-share"},
    {"id": "t_0815", "source": "email", "text": "分享會議摘要的連結要在哪裡複製？", "author": "u_05", "ts_offset_days": 5, "ts_time": "10:10:00", "project_id": "demo-project", "cluster_id": null, "feature_ids": [], "expected_group": "B-share"},
    {"id": "t_0816", "source": "discord", "text": "我想把整理好的摘要傳給團隊，要怎麼操作？", "author": "u_06", "ts_offset_days": 7, "ts_time": "16:40:00", "project_id": "demo-project", "cluster_id": null, "feature_ids": [], "expected_group": "B-share"},
    {"id": "t_0817", "source": "github_issue", "text": "會議摘要如何分享出去給其他成員看？", "author": "u_07", "ts_offset_days": 9, "ts_time": "13:05:00", "project_id": "demo-project", "cluster_id": null, "feature_ids": [], "expected_group": "B-share"},
    {"id": "t_0818", "source": "email", "text": "要怎麼調整通知的提醒時間？", "author": "u_08", "ts_offset_days": 2, "ts_time": "09:00:00", "project_id": "demo-project", "cluster_id": null, "feature_ids": [], "expected_group": "C-notify"},
    {"id": "t_0819", "source": "discord", "text": "請問通知設定在哪裡可以改？", "author": "u_09", "ts_offset_days": 6, "ts_time": "11:50:00", "project_id": "demo-project", "cluster_id": null, "feature_ids": [], "expected_group": "C-notify"},
    {"id": "t_0820", "source": "github_issue", "text": "我想關掉部分提醒通知，該去哪裡設定？", "author": "u_10", "ts_offset_days": 12, "ts_time": "17:20:00", "project_id": "demo-project", "cluster_id": null, "feature_ids": [], "expected_group": "C-notify"}
  ]
}
```

在 `demo/seed_loader.py` 的結尾加入：

```python
def resolve_ticket_ts(item: dict, *, now: datetime) -> str:
    """把種子檔的相對日期換算成 ISO 8601 UTC 字串。

    有固定 ts 就直接用（重開票工單需要固定在 2026-08）；
    否則以 now 的 UTC 日期往前推 ts_offset_days 天，再套上 ts_time。
    """
    fixed = item.get("ts")
    if fixed:
        return fixed

    offset = int(item["ts_offset_days"])
    hour, minute, second = (int(part) for part in item["ts_time"].split(":"))
    day = utc_date(now) - timedelta(days=offset)
    moment = datetime(
        day.year, day.month, day.day, hour, minute, second, tzinfo=timezone.utc
    )
    return to_iso(moment)


def load_tickets(
    repo: Repository, path: str | Path, *, now: datetime | None = None
) -> list[str]:
    """載入工單種子檔，回傳寫入的 Ticket ID 清單。

    cluster_id、feature_ids、embedding 保持接入態（空值），
    由 Ticket Analysis 在分析時補入（設計文件 §7.1）。
    """
    moment = now if now is not None else now_utc()
    written: list[str] = []
    for item in read_items(path):
        payload = {
            "id": item["id"],
            "source": item["source"],
            "text": item["text"],
            "author": item["author"],
            "ts": resolve_ticket_ts(item, now=moment),
            "project_id": item["project_id"],
            "cluster_id": item.get("cluster_id"),
            "feature_ids": list(item.get("feature_ids", [])),
        }
        ticket = Ticket.model_validate(payload)
        repo.put_meta(
            ticket_pk(ticket.id),
            {
                "entity": "TICKET",
                "id": ticket.id,
                "source": str(ticket.source),
                "text": ticket.text,
                "author": ticket.author,
                "ts": ticket.ts,
                "project_id": ticket.project_id,
                "cluster_id": ticket.cluster_id,
                "feature_ids": list(ticket.feature_ids),
            },
        )
        written.append(ticket.id)
    return written
```

在 `demo/seed_loader.py` 的 import 區補上：

```python
from datetime import datetime, timedelta, timezone

from training_kb.clock import now_utc, to_iso, utc_date
from training_kb.keys import ticket_pk
from training_kb.models import Ticket
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：`uv run pytest tests/integration/test_seed_tickets.py -v`

預期：PASS，8 passed。

- [ ] **步驟 5：commit**

```bash
git add demo/seed/tickets.json demo/seed_loader.py tests/integration/test_seed_tickets.py
git commit -m "feat(demo): 新增二十筆建立教學用工單種子"
```

---

### Task 3：A／B／C 的教學版本全文與載入

**目的**：把設計文件 §11.1 的「A v1／v2 的完整四步與五個區塊；B、C 不引用 Prepare」展開成四個版本檔，並寫進圖譜與 S3。

**檔案**：
- 新增：`demo/seed/tutorials/prepare-meeting.v1.json`
- 新增：`demo/seed/tutorials/prepare-meeting.v2.json`
- 新增：`demo/seed/tutorials/share-summary.v1.json`
- 新增：`demo/seed/tutorials/notification-settings.v1.json`
- 修改：`demo/seed_loader.py`
- 測試：`tests/integration/test_seed_tutorials.py`

**介面**：
- 消費（Phase 07）：`content.create_tutorial(repo, *, slug, topic, feature_ids, cluster_id, now) -> Tutorial`、`content.create_version(repo, plan, content, *, now) -> TutorialVersion`、`content.VersionPlan`、`content.verify_version_complete(repo, version_id) -> list[str]`
- 消費（Phase 08）：`site.publish_to_site(repo, renderer, slug, version_id) -> list[str]`、`site.SiteRenderer`
- 消費（Phase 02）：`models.TutorialContent`、`models.parse_version_id`、`keys.version_pk`、`keys.tutorial_pk`
- 產出：`demo.seed_loader.load_tutorials(repo, path, renderer, now) -> list[str]`（`path` 是 `demo/seed/tutorials` 目錄）

**兩個重要決定**：

1. **不走 `content.publish()`**。`publish()` 會用真實時間寫 `published_at`，但我們需要的是**模擬**發布時間（2026-08-01／2026-08-20），14 天窗口才算得出 0.7 與 0.2。所以載入器重用 Phase 07 的 `create_version()` 建版本，再直接寫模擬 `published_at` 與 `current_version`。這是**本計劃選擇**。
2. **仍然要用 `verify_version_complete()` 核對**。跳過 `publish()` 不代表可以跳過完整性檢查——全文、diff、步驟、引用邊一個都不能少。檢查沒過就 `raise`，不會留下半套資料。
3. **site/ 只寫已發布版本**。載入器對有 `published_at` 的版本呼叫 `publish_to_site()`。設計文件 §9.3 說「site/ 僅發布流程可寫」，這裡的意思是「未發布內容不可公開」；載入器只公開它自己標成已發布的版本，且走同一個 `publish_to_site()`（不自己拼 key），所以這條界線仍然守住。

**A 的四個步驟只有第 3 步引用 `Prepare`**。這是刻意的：設計文件 §10 的反查圖明確寫出「候選步驟：A v1 #3、A v2 #3」，每版只有一步引用該 Feature。這樣 PR #42 才會只改第 3 步，第 1、2、4 步逐字相同（設計文件 §15「Release 精準更新」列）。

- [ ] **步驟 1：寫測試**

```python
# tests/integration/test_seed_tutorials.py
"""Phase 21 Task 3：A／B／C 的教學版本全文與載入。"""

import json

from moto import mock_aws

from demo.seed_loader import SEED_DIR, load_features, load_tutorials
from training_kb.clock import parse_iso
from training_kb.site import SiteRenderer, site_keys

TUTORIAL_DIR = SEED_DIR / "tutorials"
NOW = parse_iso("2026-09-13T12:00:00Z")


def _read(name: str) -> dict:
    return json.loads((TUTORIAL_DIR / name).read_text(encoding="utf-8"))


def test_四個版本檔都存在且標示合成資料():
    names = sorted(path.name for path in TUTORIAL_DIR.glob("*.json"))
    assert names == [
        "notification-settings.v1.json",
        "prepare-meeting.v1.json",
        "prepare-meeting.v2.json",
        "share-summary.v1.json",
    ]
    for name in names:
        assert "合成資料示範" in _read(name)["note"]


def test_每個版本都有五段內容():
    for path in TUTORIAL_DIR.glob("*.json"):
        content = json.loads(path.read_text(encoding="utf-8"))["content"]
        assert content["title"].strip() != ""
        assert content["problem"].strip() != ""
        assert len(content["prerequisites"]) >= 1
        assert len(content["steps"]) >= 3
        assert content["expected_outcome"].strip() != ""


def test_每個步驟恰好引用一個既有_feature():
    known = {"Prepare", "Share Summary", "Notification Settings"}
    for path in TUTORIAL_DIR.glob("*.json"):
        for step in json.loads(path.read_text(encoding="utf-8"))["content"]["steps"]:
            assert step["feature_id"] in known
            assert step["type"] in {"click_ui", "input", "read"}


def test_A_有四步且只有第三步引用_Prepare():
    for name in ("prepare-meeting.v1.json", "prepare-meeting.v2.json"):
        steps = _read(name)["content"]["steps"]
        assert len(steps) == 4
        referencing = [
            index for index, step in enumerate(steps, start=1)
            if step["feature_id"] == "Prepare"
        ]
        assert referencing == [3]
        assert steps[2]["type"] == "click_ui"


def test_B_與_C_不引用_Prepare():
    for name in ("share-summary.v1.json", "notification-settings.v1.json"):
        features = {step["feature_id"] for step in _read(name)["content"]["steps"]}
        assert "Prepare" not in features


def test_A_v2_是_R007_的明示試用版本():
    v2 = _read("prepare-meeting.v2.json")
    assert v2["rules_applied"] == ["R-007"]
    assert v2["trial"] is True
    assert v2["supersedes"] == "prepare-meeting@v1"
    assert v2["reason"] == "feedback:8 則 找不到按鈕"


def test_A_v2_只改第三步其餘逐字相同():
    v1 = _read("prepare-meeting.v1.json")["content"]["steps"]
    v2 = _read("prepare-meeting.v2.json")["content"]["steps"]

    for index in (0, 1, 3):
        assert v1[index] == v2[index]
    assert v1[2]["text"] != v2[2]["text"]


def test_模擬發布時間符合配方():
    assert _read("prepare-meeting.v1.json")["published_at"] == "2026-08-01T00:00:00Z"
    assert _read("prepare-meeting.v2.json")["published_at"] == "2026-08-20T00:00:00Z"


@mock_aws
def test_載入後圖譜與_S3_齊全(repository):
    load_features(repository, SEED_DIR / "features.json")
    renderer = SiteRenderer()

    written = load_tutorials(repository, TUTORIAL_DIR, renderer, NOW)

    assert written == [
        "notification-settings@v1",
        "prepare-meeting@v1",
        "prepare-meeting@v2",
        "share-summary@v1",
    ]

    tutorial = repository.get_tutorial("prepare-meeting")
    assert tutorial is not None
    assert tutorial.cluster_id == "c12"
    assert tutorial.current_version == "prepare-meeting@v2"
    assert tutorial.status == "active"

    version = repository.get_version("prepare-meeting@v2")
    assert version is not None
    assert version.published_at == "2026-08-20T00:00:00Z"
    assert version.rules_applied == ["R-007"]
    assert version.supersedes == "prepare-meeting@v1"

    steps = repository.get_steps("prepare-meeting@v2")
    assert len(steps) == 4
    assert steps[2].feature_id == "Prepare"

    assert repository.object_exists("tutorials/prepare-meeting/v2.md")
    assert repository.object_exists("tutorials/prepare-meeting/v2.diff")
    assert repository.object_exists(site_keys("prepare-meeting", 2)["page"])


@mock_aws
def test_載入時會核對版本完整性(repository):
    load_features(repository, SEED_DIR / "features.json")
    load_tutorials(repository, TUTORIAL_DIR, SiteRenderer(), NOW)

    from training_kb.content import verify_version_complete

    for version_id in (
        "prepare-meeting@v1",
        "prepare-meeting@v2",
        "share-summary@v1",
        "notification-settings@v1",
    ):
        assert verify_version_complete(repository, version_id) == []


@mock_aws
def test_v1_的_diff_是空的(repository):
    load_features(repository, SEED_DIR / "features.json")
    load_tutorials(repository, TUTORIAL_DIR, SiteRenderer(), NOW)

    diff = repository.get_object("tutorials/prepare-meeting/v1.diff")
    assert diff is not None
    assert diff.decode("utf-8") == ""
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：`uv run pytest tests/integration/test_seed_tutorials.py -v`

預期：FAIL，第一個錯誤是 `FileNotFoundError` 或 `AssertionError`（`demo/seed/tutorials/` 還是空的）。

- [ ] **步驟 3：寫最少的程式讓測試通過**

建立 `demo/seed/tutorials/prepare-meeting.v1.json`：

```json
{
  "note": "合成資料示範。設計文件 §11.1 配方展開的教學 A 第一版，不是真實教學內容。只有第 3 步引用 Prepare，對應設計文件 §10 的反查範例（候選步驟：A v1 #3、A v2 #3）。",
  "slug": "prepare-meeting",
  "version_id": "prepare-meeting@v1",
  "supersedes": null,
  "reason": "gap:c12",
  "rules_applied": [],
  "published_at": "2026-08-01T00:00:00Z",
  "trial": false,
  "tutorial": {
    "topic": "準備會議",
    "feature_ids": ["Prepare", "Share Summary", "Notification Settings"],
    "cluster_id": "c12"
  },
  "content": {
    "title": "準備會議：在會議開始前拿到重點摘要",
    "problem": "使用者在會議開始前找不到系統整理好的重點摘要，只能自己往回翻歷史訊息，常常來不及看完。",
    "prerequisites": [
      "已登入工作區，且今天的行事曆中至少有一場會議",
      "該會議底下已有至少一則討論訊息或一份附件"
    ],
    "steps": [
      {
        "type": "read",
        "feature_id": "Notification Settings",
        "text": "在左側選單開啟「通知設定」，確認「會議開始前提醒」是開啟狀態。"
      },
      {
        "type": "input",
        "feature_id": "Notification Settings",
        "text": "在「會議開始前提醒」的分鐘數欄位輸入 15，然後按下儲存。"
      },
      {
        "type": "click_ui",
        "feature_id": "Prepare",
        "text": "點選 Meeting Summary，就會看到這場會議的會前摘要。"
      },
      {
        "type": "read",
        "feature_id": "Share Summary",
        "text": "在摘要下方的「分享摘要」區塊確認摘要內容是否完整，確認後再決定要不要分享。"
      }
    ],
    "expected_outcome": "會議開始前 15 分鐘會收到提醒，而且能在會議頁看到系統整理好的會前摘要。"
  }
}
```

建立 `demo/seed/tutorials/prepare-meeting.v2.json`：

```json
{
  "note": "合成資料示範。設計文件 §11.1 與 F27 的『明示種子試用版本』：這一版是為了驗證 candidate 規則 R-007 而準備的，正式寫作路徑不會自動試用 candidate。只改第 3 步，第 1、2、4 步逐字複製自 v1。",
  "slug": "prepare-meeting",
  "version_id": "prepare-meeting@v2",
  "supersedes": "prepare-meeting@v1",
  "reason": "feedback:8 則 找不到按鈕",
  "rules_applied": ["R-007"],
  "published_at": "2026-08-20T00:00:00Z",
  "trial": true,
  "tutorial": {
    "topic": "準備會議",
    "feature_ids": ["Prepare", "Share Summary", "Notification Settings"],
    "cluster_id": "c12"
  },
  "content": {
    "title": "準備會議：在會議開始前拿到重點摘要",
    "problem": "使用者在會議開始前找不到系統整理好的重點摘要，只能自己往回翻歷史訊息，常常來不及看完。",
    "prerequisites": [
      "已登入工作區，且今天的行事曆中至少有一場會議",
      "該會議底下已有至少一則討論訊息或一份附件"
    ],
    "steps": [
      {
        "type": "read",
        "feature_id": "Notification Settings",
        "text": "在左側選單開啟「通知設定」，確認「會議開始前提醒」是開啟狀態。"
      },
      {
        "type": "input",
        "feature_id": "Notification Settings",
        "text": "在「會議開始前提醒」的分鐘數欄位輸入 15，然後按下儲存。"
      },
      {
        "type": "click_ui",
        "feature_id": "Prepare",
        "text": "在會議頁面右上角的工具列，點選標示為 Meeting Summary 的按鈕；點擊後畫面右側會展開「會前摘要」面板。"
      },
      {
        "type": "read",
        "feature_id": "Share Summary",
        "text": "在摘要下方的「分享摘要」區塊確認摘要內容是否完整，確認後再決定要不要分享。"
      }
    ],
    "expected_outcome": "會議開始前 15 分鐘會收到提醒，而且能在會議頁看到系統整理好的會前摘要。"
  }
}
```

建立 `demo/seed/tutorials/share-summary.v1.json`：

```json
{
  "note": "合成資料示範。教學 B 的第一版。B 不引用 Prepare，用來驗證 PR #42 改版時 B 完全不變（設計文件 §15『Release 精準更新』列）。",
  "slug": "share-summary",
  "version_id": "share-summary@v1",
  "supersedes": null,
  "reason": "gap:c13",
  "rules_applied": [],
  "published_at": "2026-08-05T00:00:00Z",
  "trial": false,
  "tutorial": {
    "topic": "分享摘要",
    "feature_ids": ["Share Summary", "Notification Settings"],
    "cluster_id": "c13"
  },
  "content": {
    "title": "分享摘要：把會議重點寄給沒有參加的同事",
    "problem": "會議結束後，沒有參加的同事不知道討論了什麼，需要有人手動整理再轉貼。",
    "prerequisites": [
      "該場會議已經產生摘要",
      "要收到摘要的同事已經在同一個工作區"
    ],
    "steps": [
      {
        "type": "click_ui",
        "feature_id": "Share Summary",
        "text": "在會議摘要頁面的右下角，點選標示為「分享摘要」的按鈕；點擊後會跳出分享設定視窗。"
      },
      {
        "type": "input",
        "feature_id": "Share Summary",
        "text": "在分享設定視窗的收件者欄位輸入同事的電子郵件，一行填一個，最後按下送出。"
      },
      {
        "type": "read",
        "feature_id": "Notification Settings",
        "text": "回到「通知設定」，確認「分享完成通知」已勾選，這樣對方開啟摘要時你才會收到通知。"
      }
    ],
    "expected_outcome": "沒有參加會議的同事會收到含摘要連結的信，你也會在對方開啟時收到通知。"
  }
}
```

建立 `demo/seed/tutorials/notification-settings.v1.json`：

```json
{
  "note": "合成資料示範。教學 C 的第一版。C 不引用 Prepare，用來驗證 PR #42 改版時 C 完全不變。",
  "slug": "notification-settings",
  "version_id": "notification-settings@v1",
  "supersedes": null,
  "reason": "gap:c14",
  "rules_applied": [],
  "published_at": "2026-08-10T00:00:00Z",
  "trial": false,
  "tutorial": {
    "topic": "設定通知",
    "feature_ids": ["Notification Settings"],
    "cluster_id": "c14"
  },
  "content": {
    "title": "設定通知：調整提醒時間與安靜時段",
    "problem": "使用者收到太多提醒，想改時間或關掉部分通知，但不知道設定在哪裡。",
    "prerequisites": [
      "已登入工作區",
      "帳號至少加入一個團隊"
    ],
    "steps": [
      {
        "type": "click_ui",
        "feature_id": "Notification Settings",
        "text": "在左側選單最下方，點選標示為「通知設定」的齒輪圖示；點擊後主畫面會切換到通知設定頁。"
      },
      {
        "type": "input",
        "feature_id": "Notification Settings",
        "text": "在「安靜時段」的起訖時間欄位分別輸入 22:00 與 08:00。"
      },
      {
        "type": "read",
        "feature_id": "Notification Settings",
        "text": "確認頁面上方出現「已儲存」的提示，代表新的通知設定已經生效。"
      }
    ],
    "expected_outcome": "安靜時段內不會再收到提醒，其他時間的提醒維持原本設定。"
  }
}
```

在 `demo/seed_loader.py` 的結尾加入：

```python
def _load_one_tutorial(
    repo: Repository, data: dict, renderer: SiteRenderer, now: datetime
) -> str:
    """載入一個版本檔：建教學（若不存在）、建版本、核對完整性、寫模擬發布時間。"""
    slug = data["slug"]
    meta = data["tutorial"]
    if repo.get_tutorial(slug) is None:
        create_tutorial(
            repo,
            slug=slug,
            topic=meta["topic"],
            feature_ids=list(meta["feature_ids"]),
            cluster_id=meta["cluster_id"],
            now=now,
        )

    version_id = data["version_id"]
    _, number = parse_version_id(version_id)
    plan = VersionPlan(
        slug=slug,
        version_id=version_id,
        n=number,
        supersedes=data.get("supersedes"),
        reason=data["reason"],
        rules_applied=list(data.get("rules_applied", [])),
        operation_id=f"seed:{version_id}",
    )
    content = TutorialContent.model_validate(data["content"])
    create_version(repo, plan, content, now=now)

    missing = verify_version_complete(repo, version_id)
    if missing:
        raise PermanentError(f"種子版本 {version_id} 不完整，缺少：{missing}")

    published_at = data.get("published_at")
    if published_at:
        # 種子用的是模擬發布時間，不是本次真實發布時間（設計文件 §11.3、§11.5）。
        # 因此不呼叫 content.publish()，改為直接寫入 published_at 與 current_version。
        repo.update_meta(version_pk(version_id), {"published_at": published_at})
        repo.update_meta(tutorial_pk(slug), {"current_version": version_id})
        publish_to_site(repo, renderer, slug, version_id)

    return version_id


def load_tutorials(
    repo: Repository, path: str | Path, renderer: SiteRenderer, now: datetime
) -> list[str]:
    """載入 demo/seed/tutorials 目錄下的所有版本檔，回傳寫入的 version_id 清單。

    檔名排序保證同一篇教學的 v1 先於 v2 載入，supersedes 才有對象可指。
    """
    written: list[str] = []
    for file_path in sorted(Path(path).glob("*.json")):
        data = json.loads(file_path.read_text(encoding="utf-8"))
        written.append(_load_one_tutorial(repo, data, renderer, now))
    return written
```

在 `demo/seed_loader.py` 的 import 區補上：

```python
from training_kb.content import (
    VersionPlan,
    create_tutorial,
    create_version,
    verify_version_complete,
)
from training_kb.errors import PermanentError
from training_kb.keys import tutorial_pk, version_pk
from training_kb.models import TutorialContent, parse_version_id
from training_kb.site import SiteRenderer, publish_to_site
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：`uv run pytest tests/integration/test_seed_tutorials.py -v`

預期：PASS，11 passed。

- [ ] **步驟 5：commit**

```bash
git add demo/seed/tutorials demo/seed_loader.py tests/integration/test_seed_tutorials.py
git commit -m "feat(demo): 新增 A/B/C 教學版本全文種子與載入"
```

---

### Task 4：Release r_42 與九筆同題重開票工單

**目的**：展開設計文件 §11.1 的 Release 配方與 §11.3 的重開票工單表格。

**檔案**：
- 新增：`demo/seed/releases.json`
- 新增：`demo/seed/reopen_tickets.json`
- 修改：`demo/seed_loader.py`
- 測試：`tests/integration/test_seed_release_reopen.py`

**介面**：
- 消費（Phase 02）：`models.Release`、`keys.release_pk`
- 消費（Task 2）：`demo.seed_loader.load_tickets`
- 產出：`demo.seed_loader.load_releases(repo, path) -> list[str]`

**兩個資料的重點**：

1. `r_42` 是**本配方的合成上游 Release ID**，跟人看的「PR #42」分開。PR 編號存在 `source_event_id`（值是 `"42"`），因為設計文件 §7.1 明說「PR 編號不能直接當 Release.id」。`kind` 是 `renamed`，所以 `old_name`／`new_name` 必填（設計文件 D10）。
2. 九筆重開票工單的 `ts` 是**固定日期**（2026-08），不用相對日期。理由：它們必須落在 A v1／A v2 的模擬發布窗口內，而模擬發布時間本身就是固定的。`cluster_id` 直接填 `c12`（歷史態），因為它們是同題重開票的既有證據，指標計算會直接讀這個欄位（設計文件 D29）。

**時間必須滿足的三件事**（否則 0.7／0.2 算不出來）：

```text
A v1 窗口 [2026-08-01T00:00:00Z, 2026-08-15T00:00:00Z)
   瀏覽 u_01..u_10 於 2026-08-02T09:00:00Z   ← 分母 10 人
   開票 u_01..u_07 於 2026-08-03T10:00:00Z   ← 分子 7 人；開票時間晚於瀏覽時間 ✔

A v2 窗口 [2026-08-20T00:00:00Z, 2026-09-03T00:00:00Z)
   瀏覽 u_01..u_10 於 2026-08-21T09:00:00Z   ← 分母 10 人
   開票 u_01..u_02 於 2026-08-22T10:00:00Z   ← 分子 2 人
```

- [ ] **步驟 1：寫測試**

```python
# tests/integration/test_seed_release_reopen.py
"""Phase 21 Task 4：Release r_42 與九筆同題重開票工單。"""

import json

from moto import mock_aws

from demo.seed_loader import SEED_DIR, load_releases, load_tickets, read_items
from training_kb.clock import parse_iso

RELEASES_PATH = SEED_DIR / "releases.json"
REOPEN_PATH = SEED_DIR / "reopen_tickets.json"


def test_release_是合成上游_id_與人看的_PR_分開():
    raw = json.loads(RELEASES_PATH.read_text(encoding="utf-8"))
    assert "合成資料示範" in raw["note"]

    items = raw["items"]
    assert len(items) == 1
    release = items[0]
    assert release["id"] == "r_42"
    assert release["source_event_id"] == "42"
    assert release["source"] == "github_pr"
    assert release["kind"] == "renamed"
    assert release["old_name"] == "Meeting Summary"
    assert release["new_name"] == "Prepare"
    assert release["evidence"].strip() != ""
    assert release["ts"] == "2026-08-25T00:00:00Z"


def test_九筆重開票工單的_id_與使用者符合配方():
    items = read_items(REOPEN_PATH)
    assert len(items) == 9

    v1_ids = [item["id"] for item in items if item["ts"].startswith("2026-08-03")]
    v2_ids = [item["id"] for item in items if item["ts"].startswith("2026-08-22")]
    assert v1_ids == ["t_2001", "t_2002", "t_2003", "t_2004", "t_2005", "t_2006", "t_2007"]
    assert v2_ids == ["t_2101", "t_2102"]

    v1_users = [item["author"] for item in items if item["id"] in v1_ids]
    v2_users = [item["author"] for item in items if item["id"] in v2_ids]
    assert v1_users == ["u_01", "u_02", "u_03", "u_04", "u_05", "u_06", "u_07"]
    assert v2_users == ["u_01", "u_02"]


def test_九筆重開票工單的固定欄位():
    for item in read_items(REOPEN_PATH):
        assert item["source"] == "email"
        assert item["cluster_id"] == "c12"
        assert item["project_id"] == "demo-project"
        assert item["text"] == "看過準備會議教學後，仍找不到第三步的按鈕"
        assert item["feature_ids"] == []
        assert "ts_offset_days" not in item


def test_重開票時間落在各版窗口內且晚於瀏覽時間():
    v1_start = parse_iso("2026-08-01T00:00:00Z")
    v1_end = parse_iso("2026-08-15T00:00:00Z")
    v2_start = parse_iso("2026-08-20T00:00:00Z")
    v2_end = parse_iso("2026-09-03T00:00:00Z")
    v1_view = parse_iso("2026-08-02T09:00:00Z")
    v2_view = parse_iso("2026-08-21T09:00:00Z")

    for item in read_items(REOPEN_PATH):
        moment = parse_iso(item["ts"])
        if item["id"].startswith("t_20"):
            assert v1_start <= moment < v1_end
            assert moment > v1_view
        else:
            assert v2_start <= moment < v2_end
            assert moment > v2_view


@mock_aws
def test_載入後可以讀回_release_與工單(repository):
    written = load_releases(repository, RELEASES_PATH)
    assert written == ["r_42"]

    release = repository.get_release("r_42")
    assert release is not None
    assert release.feature == "Prepare"
    assert release.kind == "renamed"

    ticket_ids = load_tickets(repository, REOPEN_PATH)
    assert len(ticket_ids) == 9

    ticket = repository.get_ticket("t_2001")
    assert ticket is not None
    assert ticket.cluster_id == "c12"
    assert ticket.ts == "2026-08-03T10:00:00Z"
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：`uv run pytest tests/integration/test_seed_release_reopen.py -v`

預期：FAIL，`ImportError: cannot import name 'load_releases' from 'demo.seed_loader'`。

- [ ] **步驟 3：寫最少的程式讓測試通過**

建立 `demo/seed/releases.json`：

```json
{
  "note": "合成資料示範。r_42 是本配方的合成上游 Release ID，與人看的 PR #42 分開：PR 編號存在 source_event_id（設計文件 §7.1：PR 編號不能直接當 Release.id）。kind 為 renamed，所以 old_name 與 new_name 必填（設計文件 D10）。",
  "items": [
    {
      "id": "r_42",
      "source": "github_pr",
      "source_event_id": "42",
      "feature": "Prepare",
      "kind": "renamed",
      "old_name": "Meeting Summary",
      "new_name": "Prepare",
      "evidence": "PR #42 diff excerpt: - label=\"Meeting Summary\" + label=\"Prepare\"（packages/web/src/meeting/toolbar.tsx 第 48 行）",
      "ts": "2026-08-25T00:00:00Z"
    }
  ]
}
```

建立 `demo/seed/reopen_tickets.json`：

```json
{
  "note": "合成資料示範。設計文件 §11.3 表格展開的九筆同題重開票工單。ts 是固定日期（不是相對日期），因為它們必須落在 A v1／A v2 的模擬發布窗口內。cluster_id 直接填 c12（歷史態），對應 Tutorial.cluster_id（設計文件 D29）。",
  "items": [
    {"id": "t_2001", "source": "email", "text": "看過準備會議教學後，仍找不到第三步的按鈕", "author": "u_01", "ts": "2026-08-03T10:00:00Z", "project_id": "demo-project", "cluster_id": "c12", "feature_ids": []},
    {"id": "t_2002", "source": "email", "text": "看過準備會議教學後，仍找不到第三步的按鈕", "author": "u_02", "ts": "2026-08-03T10:00:00Z", "project_id": "demo-project", "cluster_id": "c12", "feature_ids": []},
    {"id": "t_2003", "source": "email", "text": "看過準備會議教學後，仍找不到第三步的按鈕", "author": "u_03", "ts": "2026-08-03T10:00:00Z", "project_id": "demo-project", "cluster_id": "c12", "feature_ids": []},
    {"id": "t_2004", "source": "email", "text": "看過準備會議教學後，仍找不到第三步的按鈕", "author": "u_04", "ts": "2026-08-03T10:00:00Z", "project_id": "demo-project", "cluster_id": "c12", "feature_ids": []},
    {"id": "t_2005", "source": "email", "text": "看過準備會議教學後，仍找不到第三步的按鈕", "author": "u_05", "ts": "2026-08-03T10:00:00Z", "project_id": "demo-project", "cluster_id": "c12", "feature_ids": []},
    {"id": "t_2006", "source": "email", "text": "看過準備會議教學後，仍找不到第三步的按鈕", "author": "u_06", "ts": "2026-08-03T10:00:00Z", "project_id": "demo-project", "cluster_id": "c12", "feature_ids": []},
    {"id": "t_2007", "source": "email", "text": "看過準備會議教學後，仍找不到第三步的按鈕", "author": "u_07", "ts": "2026-08-03T10:00:00Z", "project_id": "demo-project", "cluster_id": "c12", "feature_ids": []},
    {"id": "t_2101", "source": "email", "text": "看過準備會議教學後，仍找不到第三步的按鈕", "author": "u_01", "ts": "2026-08-22T10:00:00Z", "project_id": "demo-project", "cluster_id": "c12", "feature_ids": []},
    {"id": "t_2102", "source": "email", "text": "看過準備會議教學後，仍找不到第三步的按鈕", "author": "u_02", "ts": "2026-08-22T10:00:00Z", "project_id": "demo-project", "cluster_id": "c12", "feature_ids": []}
  ]
}
```

在 `demo/seed_loader.py` 的結尾加入：

```python
def load_releases(repo: Repository, path: str | Path) -> list[str]:
    """載入 Release 種子檔，回傳寫入的 Release ID 清單。"""
    written: list[str] = []
    for item in read_items(path):
        release = Release.model_validate(item)
        repo.put_meta(
            release_pk(release.id),
            {
                "entity": "RELEASE",
                "id": release.id,
                "source": str(release.source),
                "source_event_id": release.source_event_id,
                "feature": release.feature,
                "kind": str(release.kind),
                "old_name": release.old_name,
                "new_name": release.new_name,
                "evidence": release.evidence,
                "ts": release.ts,
            },
        )
        written.append(release.id)
    return written
```

在 `demo/seed_loader.py` 的 import 區補上：

```python
from training_kb.keys import release_pk
from training_kb.models import Release
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：`uv run pytest tests/integration/test_seed_release_reopen.py -v`

預期：PASS，5 passed。

- [ ] **步驟 5：commit**

```bash
git add demo/seed/releases.json demo/seed/reopen_tickets.json demo/seed_loader.py tests/integration/test_seed_release_reopen.py
git commit -m "feat(demo): 新增 r_42 與九筆同題重開票工單種子"
```

---

### Task 5：十八筆回饋與二十筆瀏覽

**目的**：逐字展開設計文件 §11.2 的回饋表格與 §11.3 的瀏覽配方。

**檔案**：
- 新增：`demo/seed/feedback.json`
- 新增：`demo/seed/views.json`
- 修改：`demo/seed_loader.py`
- 測試：`tests/integration/test_seed_feedback_views.py`

**介面**：
- 消費（Phase 15）：`ingress.validate_feedback(data, *, now) -> Feedback`、`ingress.validate_view(data) -> TutorialView`
- 消費（Phase 02）：`keys.feedback_pk`、`keys.view_pk`、`keys.version_pk`、`keys.edge_sk`
- 產出：
  - `demo.seed_loader.load_feedback(repo, path, *, now=None) -> list[str]`
  - `demo.seed_loader.load_views(repo, path) -> int`（回傳寫入筆數，View 沒有業務 ID）

**逐字對照設計文件 §11.2 的表格**：

| 版本 | Feedback ID | user | rating | category |
|---|---|---|---:|---|
| A v1 | f_12 | u_01 | 2 | 找不到按鈕 |
| A v1 | f_15 | u_02 | 2 | 找不到按鈕 |
| A v1 | f_19 | u_03 | 3 | 找不到按鈕 |
| A v1 | f_23 | u_04 | 3 | 找不到按鈕 |
| A v1 | f_27 | u_05 | 3 | 找不到按鈕 |
| A v1 | f_31 | u_06 | 3 | 找不到按鈕 |
| A v1 | f_34 | u_07 | 3 | 找不到按鈕 |
| A v1 | f_40 | u_08 | 4 | 找不到按鈕 |
| A v2 | f_101 | u_01 | 2 | 缺少資訊 |
| A v2 | f_102 | u_02 | 2 | 缺少資訊 |
| A v2 | f_103 | u_03 | 5 | （空） |
| A v2 | f_104 | u_04 | 5 | （空） |
| A v2 | f_105 | u_05 | 5 | （空） |
| A v2 | f_106 | u_06 | 5 | （空） |
| A v2 | f_107 | u_07 | 5 | （空） |
| A v2 | f_108 | u_08 | 5 | （空） |
| A v2 | f_109 | u_09 | 5 | （空） |
| A v2 | f_110 | u_10 | 5 | （空） |

留言（comment）：A v1 每筆都是「第三步沒有指出按鈕在哪一頁與位置」；A v2 只有 f_101、f_102 是「資訊仍不夠完整」，其餘留空。
時間：各版模擬發布後第二日。A v1＝`2026-08-02T12:00:00Z`，A v2＝`2026-08-21T12:00:00Z`。

**載入時為什麼要先過 `validate_feedback`**：種子資料也是資料，一樣要通過 Phase 15 的欄位驗證（rating 1..5 整數、user 必填、版本必須存在）。如果種子有錯，要在載入時就炸掉，不要留到 Dashboard 才發現數字不對。

- [ ] **步驟 1：寫測試**

```python
# tests/integration/test_seed_feedback_views.py
"""Phase 21 Task 5：十八筆回饋與二十筆瀏覽。"""

from moto import mock_aws

from demo.seed_loader import (
    SEED_DIR,
    load_feedback,
    load_features,
    load_tutorials,
    load_views,
    read_items,
)
from training_kb.clock import parse_iso
from training_kb.site import SiteRenderer

FEEDBACK_PATH = SEED_DIR / "feedback.json"
VIEWS_PATH = SEED_DIR / "views.json"
NOW = parse_iso("2026-09-13T12:00:00Z")


def test_十八筆回饋且_id_不重複():
    items = read_items(FEEDBACK_PATH)
    ids = [item["id"] for item in items]

    assert len(items) == 18
    assert len(set(ids)) == 18
    assert all(fid.startswith("f_") for fid in ids)


def test_A_v1_八筆逐字對照設計文件表格():
    items = [
        item
        for item in read_items(FEEDBACK_PATH)
        if item["tutorial_version"] == "prepare-meeting@v1"
    ]
    expected = [
        ("f_12", "u_01", 2),
        ("f_15", "u_02", 2),
        ("f_19", "u_03", 3),
        ("f_23", "u_04", 3),
        ("f_27", "u_05", 3),
        ("f_31", "u_06", 3),
        ("f_34", "u_07", 3),
        ("f_40", "u_08", 4),
    ]

    assert [(i["id"], i["user"], i["rating"]) for i in items] == expected
    for item in items:
        assert item["category"] == "找不到按鈕"
        assert item["comment"] == "第三步沒有指出按鈕在哪一頁與位置"
        assert item["ts"] == "2026-08-02T12:00:00Z"


def test_A_v2_十筆逐字對照設計文件表格():
    items = [
        item
        for item in read_items(FEEDBACK_PATH)
        if item["tutorial_version"] == "prepare-meeting@v2"
    ]

    assert len(items) == 10
    assert items[0]["id"] == "f_101" and items[0]["rating"] == 2
    assert items[0]["category"] == "缺少資訊"
    assert items[0]["comment"] == "資訊仍不夠完整"
    assert items[1]["id"] == "f_102" and items[1]["rating"] == 2

    rest = items[2:]
    assert [item["id"] for item in rest] == [f"f_1{n:02d}" for n in range(3, 11)]
    assert [item["user"] for item in rest] == [f"u_{n:02d}" for n in range(3, 11)]
    for item in rest:
        assert item["rating"] == 5
        assert item["category"] is None
        assert item["comment"] is None
    for item in items:
        assert item["ts"] == "2026-08-21T12:00:00Z"


def test_回饋總分符合配方():
    items = read_items(FEEDBACK_PATH)
    v1 = [i["rating"] for i in items if i["tutorial_version"] == "prepare-meeting@v1"]
    v2 = [i["rating"] for i in items if i["tutorial_version"] == "prepare-meeting@v2"]

    assert sum(v1) == 23 and len(v1) == 8 and sum(v1) / len(v1) == 2.875
    assert sum(v2) == 44 and len(v2) == 10 and sum(v2) / len(v2) == 4.4


def test_二十筆瀏覽每版每人一筆():
    items = read_items(VIEWS_PATH)
    assert len(items) == 20

    v1 = [i for i in items if i["tutorial_version"] == "prepare-meeting@v1"]
    v2 = [i for i in items if i["tutorial_version"] == "prepare-meeting@v2"]

    assert [i["user"] for i in v1] == [f"u_{n:02d}" for n in range(1, 11)]
    assert [i["user"] for i in v2] == [f"u_{n:02d}" for n in range(1, 11)]
    assert all(i["ts"] == "2026-08-02T09:00:00Z" for i in v1)
    assert all(i["ts"] == "2026-08-21T09:00:00Z" for i in v2)


@mock_aws
def test_載入後可以用_REFERS_TO_反查回饋(repository):
    load_features(repository, SEED_DIR / "features.json")
    load_tutorials(repository, SEED_DIR / "tutorials", SiteRenderer(), NOW)

    written = load_feedback(repository, FEEDBACK_PATH, now=NOW)
    assert len(written) == 18

    v1_feedback = repository.list_feedback_of_version("prepare-meeting@v1")
    assert len(v1_feedback) == 8
    assert {f.id for f in v1_feedback} == {
        "f_12", "f_15", "f_19", "f_23", "f_27", "f_31", "f_34", "f_40",
    }


@mock_aws
def test_載入瀏覽後可以依版本查回(repository):
    load_features(repository, SEED_DIR / "features.json")
    load_tutorials(repository, SEED_DIR / "tutorials", SiteRenderer(), NOW)

    count = load_views(repository, VIEWS_PATH)
    assert count == 20

    v1_views = repository.list_views_of_version("prepare-meeting@v1")
    assert len(v1_views) == 10
    assert {v.user for v in v1_views} == {f"u_{n:02d}" for n in range(1, 11)}


@mock_aws
def test_重複載入瀏覽不會變成四十筆(repository):
    load_features(repository, SEED_DIR / "features.json")
    load_tutorials(repository, SEED_DIR / "tutorials", SiteRenderer(), NOW)

    load_views(repository, VIEWS_PATH)
    load_views(repository, VIEWS_PATH)

    assert len(repository.list_views_of_version("prepare-meeting@v1")) == 10
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：`uv run pytest tests/integration/test_seed_feedback_views.py -v`

預期：FAIL，`ImportError: cannot import name 'load_feedback' from 'demo.seed_loader'`。

- [ ] **步驟 3：寫最少的程式讓測試通過**

建立 `demo/seed/feedback.json`：

```json
{
  "note": "合成資料示範。逐字展開設計文件 §11.2 的回饋表格。A v1 八筆（總分 23，平均 2.875，八筆皆為核定問題類別所以負面回饋 8）；A v2 十筆（總分 44，平均 4.4，只有 f_101、f_102 命中所以負面回饋 2）。ts 為各版模擬發布後第二日。",
  "items": [
    {"id": "f_12", "tutorial_version": "prepare-meeting@v1", "rating": 2, "user": "u_01", "category": "找不到按鈕", "comment": "第三步沒有指出按鈕在哪一頁與位置", "ts": "2026-08-02T12:00:00Z"},
    {"id": "f_15", "tutorial_version": "prepare-meeting@v1", "rating": 2, "user": "u_02", "category": "找不到按鈕", "comment": "第三步沒有指出按鈕在哪一頁與位置", "ts": "2026-08-02T12:00:00Z"},
    {"id": "f_19", "tutorial_version": "prepare-meeting@v1", "rating": 3, "user": "u_03", "category": "找不到按鈕", "comment": "第三步沒有指出按鈕在哪一頁與位置", "ts": "2026-08-02T12:00:00Z"},
    {"id": "f_23", "tutorial_version": "prepare-meeting@v1", "rating": 3, "user": "u_04", "category": "找不到按鈕", "comment": "第三步沒有指出按鈕在哪一頁與位置", "ts": "2026-08-02T12:00:00Z"},
    {"id": "f_27", "tutorial_version": "prepare-meeting@v1", "rating": 3, "user": "u_05", "category": "找不到按鈕", "comment": "第三步沒有指出按鈕在哪一頁與位置", "ts": "2026-08-02T12:00:00Z"},
    {"id": "f_31", "tutorial_version": "prepare-meeting@v1", "rating": 3, "user": "u_06", "category": "找不到按鈕", "comment": "第三步沒有指出按鈕在哪一頁與位置", "ts": "2026-08-02T12:00:00Z"},
    {"id": "f_34", "tutorial_version": "prepare-meeting@v1", "rating": 3, "user": "u_07", "category": "找不到按鈕", "comment": "第三步沒有指出按鈕在哪一頁與位置", "ts": "2026-08-02T12:00:00Z"},
    {"id": "f_40", "tutorial_version": "prepare-meeting@v1", "rating": 4, "user": "u_08", "category": "找不到按鈕", "comment": "第三步沒有指出按鈕在哪一頁與位置", "ts": "2026-08-02T12:00:00Z"},
    {"id": "f_101", "tutorial_version": "prepare-meeting@v2", "rating": 2, "user": "u_01", "category": "缺少資訊", "comment": "資訊仍不夠完整", "ts": "2026-08-21T12:00:00Z"},
    {"id": "f_102", "tutorial_version": "prepare-meeting@v2", "rating": 2, "user": "u_02", "category": "缺少資訊", "comment": "資訊仍不夠完整", "ts": "2026-08-21T12:00:00Z"},
    {"id": "f_103", "tutorial_version": "prepare-meeting@v2", "rating": 5, "user": "u_03", "category": null, "comment": null, "ts": "2026-08-21T12:00:00Z"},
    {"id": "f_104", "tutorial_version": "prepare-meeting@v2", "rating": 5, "user": "u_04", "category": null, "comment": null, "ts": "2026-08-21T12:00:00Z"},
    {"id": "f_105", "tutorial_version": "prepare-meeting@v2", "rating": 5, "user": "u_05", "category": null, "comment": null, "ts": "2026-08-21T12:00:00Z"},
    {"id": "f_106", "tutorial_version": "prepare-meeting@v2", "rating": 5, "user": "u_06", "category": null, "comment": null, "ts": "2026-08-21T12:00:00Z"},
    {"id": "f_107", "tutorial_version": "prepare-meeting@v2", "rating": 5, "user": "u_07", "category": null, "comment": null, "ts": "2026-08-21T12:00:00Z"},
    {"id": "f_108", "tutorial_version": "prepare-meeting@v2", "rating": 5, "user": "u_08", "category": null, "comment": null, "ts": "2026-08-21T12:00:00Z"},
    {"id": "f_109", "tutorial_version": "prepare-meeting@v2", "rating": 5, "user": "u_09", "category": null, "comment": null, "ts": "2026-08-21T12:00:00Z"},
    {"id": "f_110", "tutorial_version": "prepare-meeting@v2", "rating": 5, "user": "u_10", "category": null, "comment": null, "ts": "2026-08-21T12:00:00Z"}
  ]
}
```

建立 `demo/seed/views.json`：

```json
{
  "note": "合成資料示範。展開設計文件 §11.3 的瀏覽配方：u_01～u_10 在每一版各留一筆瀏覽紀錄。A v1 的瀏覽在 2026-08-02T09:00:00Z，A v2 的在 2026-08-21T09:00:00Z，都落在各版的十四天窗口內，且早於同版的重開票時間。",
  "items": [
    {"tutorial_version": "prepare-meeting@v1", "user": "u_01", "ts": "2026-08-02T09:00:00Z"},
    {"tutorial_version": "prepare-meeting@v1", "user": "u_02", "ts": "2026-08-02T09:00:00Z"},
    {"tutorial_version": "prepare-meeting@v1", "user": "u_03", "ts": "2026-08-02T09:00:00Z"},
    {"tutorial_version": "prepare-meeting@v1", "user": "u_04", "ts": "2026-08-02T09:00:00Z"},
    {"tutorial_version": "prepare-meeting@v1", "user": "u_05", "ts": "2026-08-02T09:00:00Z"},
    {"tutorial_version": "prepare-meeting@v1", "user": "u_06", "ts": "2026-08-02T09:00:00Z"},
    {"tutorial_version": "prepare-meeting@v1", "user": "u_07", "ts": "2026-08-02T09:00:00Z"},
    {"tutorial_version": "prepare-meeting@v1", "user": "u_08", "ts": "2026-08-02T09:00:00Z"},
    {"tutorial_version": "prepare-meeting@v1", "user": "u_09", "ts": "2026-08-02T09:00:00Z"},
    {"tutorial_version": "prepare-meeting@v1", "user": "u_10", "ts": "2026-08-02T09:00:00Z"},
    {"tutorial_version": "prepare-meeting@v2", "user": "u_01", "ts": "2026-08-21T09:00:00Z"},
    {"tutorial_version": "prepare-meeting@v2", "user": "u_02", "ts": "2026-08-21T09:00:00Z"},
    {"tutorial_version": "prepare-meeting@v2", "user": "u_03", "ts": "2026-08-21T09:00:00Z"},
    {"tutorial_version": "prepare-meeting@v2", "user": "u_04", "ts": "2026-08-21T09:00:00Z"},
    {"tutorial_version": "prepare-meeting@v2", "user": "u_05", "ts": "2026-08-21T09:00:00Z"},
    {"tutorial_version": "prepare-meeting@v2", "user": "u_06", "ts": "2026-08-21T09:00:00Z"},
    {"tutorial_version": "prepare-meeting@v2", "user": "u_07", "ts": "2026-08-21T09:00:00Z"},
    {"tutorial_version": "prepare-meeting@v2", "user": "u_08", "ts": "2026-08-21T09:00:00Z"},
    {"tutorial_version": "prepare-meeting@v2", "user": "u_09", "ts": "2026-08-21T09:00:00Z"},
    {"tutorial_version": "prepare-meeting@v2", "user": "u_10", "ts": "2026-08-21T09:00:00Z"}
  ]
}
```

在 `demo/seed_loader.py` 的結尾加入：

```python
def load_feedback(
    repo: Repository, path: str | Path, *, now: datetime | None = None
) -> list[str]:
    """載入回饋種子檔，寫 FEEDBACK item 與 REFERS_TO 邊，回傳寫入的 Feedback ID。

    種子資料一樣要通過 Phase 15 的欄位驗證，錯誤在載入時就會拋出。
    """
    moment = now if now is not None else now_utc()
    written: list[str] = []
    for item in read_items(path):
        feedback = validate_feedback(item, now=moment)
        repo.put_meta(
            feedback_pk(feedback.id),
            {
                "entity": "FEEDBACK",
                "id": feedback.id,
                "tutorial_version": feedback.tutorial_version,
                "rating": feedback.rating,
                "category": feedback.category,
                "comment": feedback.comment,
                "user": feedback.user,
                "ts": feedback.ts,
            },
        )
        repo.put_edge(
            feedback_pk(feedback.id),
            "REFERS_TO",
            version_pk(feedback.tutorial_version),
        )
        written.append(feedback.id)
    return written


def load_views(repo: Repository, path: str | Path) -> int:
    """載入瀏覽種子檔，回傳寫入筆數。

    View 的 PK 是 [tutorial_version, user, ts] 的 SHA-256 摘要（設計文件 §9.1），
    所以重複載入同一份檔案不會多出紀錄。
    """
    count = 0
    for item in read_items(path):
        view = validate_view(item)
        repo.put_meta(
            view_pk(view.tutorial_version, view.user, view.ts),
            {
                "entity": "VIEW",
                "tutorial_version": view.tutorial_version,
                "user": view.user,
                "ts": view.ts,
            },
        )
        count += 1
    return count
```

在 `demo/seed_loader.py` 的 import 區補上：

```python
from training_kb.ingress import validate_feedback, validate_view
from training_kb.keys import feedback_pk, view_pk
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：`uv run pytest tests/integration/test_seed_feedback_views.py -v`

預期：PASS，8 passed。

- [ ] **步驟 5：commit**

```bash
git add demo/seed/feedback.json demo/seed/views.json demo/seed_loader.py tests/integration/test_seed_feedback_views.py
git commit -m "feat(demo): 新增十八筆回饋與二十筆瀏覽種子"
```

---

### Task 6：R-007 與 R-012 規則種子

**目的**：建立兩條 Authoring Rule——一條等著被啟用（R-007），一條等著被退役（R-012）。

**檔案**：
- 新增：`demo/seed/rules.json`
- 修改：`demo/seed_loader.py`
- 測試：`tests/integration/test_seed_rules.py`

**介面**：
- 消費（Phase 02）：`models.AuthoringRule`、`models.RuleStatus`
- 消費（Phase 03、09）：`repo.put_rule(rule)`、`repo.get_rule(rule_id)`、`repo.list_rules(status)`
- 產出：`demo.seed_loader.load_rules(repo, path) -> list[str]`

**兩條規則的設計**：

| 欄位 | R-007 | R-012 |
|---|---|---|
| `status` | `candidate` | `active` |
| `rule` | 「點選 UI 的步驟必須寫出所在頁面、按鈕的位置，以及點擊後會看到的結果。」 | 「每步不超過兩句。」（照 `驗證教學規則.feature` 的 Example 原文） |
| `applies_when` | `{"step.type": "click_ui"}` | `{"step.type": "read"}` |
| `evidence` | A v1 的八筆：f_12、f_15、f_19、f_23、f_27、f_31、f_34、f_40 | 批次 b_r012_01 裡的五筆：f_201～f_205 |
| `derived_from` | `prepare-meeting@v1` | `rule-lab-demo@v1` |
| `applied_to` | `[]`（由 `rules_applied` 重建，Phase 20 的 `apply_rule_status` 會填） | `[]` |
| `validated_at` | `null` | `2026-07-25T00:00:00Z` |

**為什麼 R-012 的 `applies_when` 是 `read` 而不是 `click_ui`（本計劃選擇）**：

`驗證教學規則.feature` 的 Example 只給了 R-012 的 `rule_id` 與 `rule` 文字，沒有給 `applies_when`。如果把它設成 `click_ui`，就會跟 R-007 撞到同一個適用範圍——Phase 20 驗證 R-007 時會先跑衝突判定，模型很可能判定「要寫出頁面與位置」和「每步不超過兩句」互斥，於是 R-007 被退役而不是啟用，Demo 的主線就斷了。設計文件沒有要求這兩條規則衝突，所以本計劃把 R-012 放在不同範圍，讓「啟用」與「退役」兩條展示互不干擾。

**為什麼 R-012 的 `derived_from` 是 `rule-lab-demo@v1`（本計劃選擇）**：

R-012 需要「兩個完整、不重疊的核定種子批次」才能退役（設計文件 §11.4）。如果把這四個版本（v1～v4）建在 A、B、C 任何一篇教學上，就會污染 A 的版本鏈與指標。所以本計劃另開一個明示的合成教學 `rule-lab-demo`，它的版本**只存在於批次檔裡**，不寫入 DynamoDB 的 VERSION item——批次評估（Phase 20 的 `evaluate_batch`）本來就只讀批次內的記錄，不查圖譜。這呼應設計文件 F47 的隔離原則：展示用產物不污染正式教學與統計。

- [ ] **步驟 1：寫測試**

```python
# tests/integration/test_seed_rules.py
"""Phase 21 Task 6：R-007 與 R-012 規則種子。"""

import json

from moto import mock_aws

from demo.seed_loader import SEED_DIR, load_rules, read_items
from training_kb.models import RuleStatus

RULES_PATH = SEED_DIR / "rules.json"


def _by_id() -> dict:
    return {item["rule_id"]: item for item in read_items(RULES_PATH)}


def test_兩條規則且標示合成資料():
    raw = json.loads(RULES_PATH.read_text(encoding="utf-8"))
    assert "合成資料示範" in raw["note"]
    assert set(_by_id()) == {"R-007", "R-012"}


def test_R007_是_candidate_且證據是_A_v1_八筆():
    rule = _by_id()["R-007"]

    assert rule["status"] == "candidate"
    assert rule["applies_when"] == {"step.type": "click_ui"}
    assert rule["evidence"] == [
        "f_12", "f_15", "f_19", "f_23", "f_27", "f_31", "f_34", "f_40",
    ]
    assert rule["derived_from"] == "prepare-meeting@v1"
    assert rule["applied_to"] == []
    assert rule["validated_at"] is None


def test_R012_是_active_且與_R007_範圍不同():
    rules = _by_id()

    assert rules["R-012"]["status"] == "active"
    assert rules["R-012"]["rule"] == "每步不超過兩句。"
    assert rules["R-012"]["applies_when"] == {"step.type": "read"}
    assert rules["R-012"]["applies_when"] != rules["R-007"]["applies_when"]
    assert rules["R-012"]["derived_from"] == "rule-lab-demo@v1"


def test_evidence_只存_feedback_id_且恰好一個來源版本():
    for rule in _by_id().values():
        assert all(fid.startswith("f_") for fid in rule["evidence"])
        assert len(rule["evidence"]) >= 5
        assert isinstance(rule["derived_from"], str)
        assert "@v" in rule["derived_from"]


def test_applies_when_只用_step_type_單一條件():
    for rule in _by_id().values():
        assert list(rule["applies_when"]) == ["step.type"]
        assert rule["applies_when"]["step.type"] in {"click_ui", "input", "read"}


@mock_aws
def test_載入後可以依狀態分別查回(repository):
    written = load_rules(repository, RULES_PATH)
    assert written == ["R-007", "R-012"]

    candidates = repository.list_rules(RuleStatus.candidate)
    actives = repository.list_rules(RuleStatus.active)

    assert [rule.rule_id for rule in candidates] == ["R-007"]
    assert [rule.rule_id for rule in actives] == ["R-012"]

    r007 = repository.get_rule("R-007")
    assert r007 is not None
    assert len(r007.evidence) == 8
    assert r007.validated_at is None
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：`uv run pytest tests/integration/test_seed_rules.py -v`

預期：FAIL，`ImportError: cannot import name 'load_rules' from 'demo.seed_loader'`。

- [ ] **步驟 3：寫最少的程式讓測試通過**

建立 `demo/seed/rules.json`：

```json
{
  "note": "合成資料示範。R-007 是設計文件 §11.4 主線用的 candidate 規則，證據是 A v1 的八筆同類回饋。R-012 是退役展示用的 active 規則，適用範圍刻意與 R-007 不同（本計劃選擇），避免衝突判定打斷 R-007 的啟用展示；它的 derived_from 指向只存在於批次檔的合成教學 rule-lab-demo。",
  "items": [
    {
      "rule_id": "R-007",
      "rule": "點選 UI 的步驟必須寫出所在頁面、按鈕的位置，以及點擊後會看到的結果。",
      "applies_when": {"step.type": "click_ui"},
      "evidence": ["f_12", "f_15", "f_19", "f_23", "f_27", "f_31", "f_34", "f_40"],
      "status": "candidate",
      "applied_to": [],
      "derived_from": "prepare-meeting@v1",
      "validated_at": null
    },
    {
      "rule_id": "R-012",
      "rule": "每步不超過兩句。",
      "applies_when": {"step.type": "read"},
      "evidence": ["f_201", "f_202", "f_203", "f_204", "f_205"],
      "status": "active",
      "applied_to": [],
      "derived_from": "rule-lab-demo@v1",
      "validated_at": "2026-07-25T00:00:00Z"
    }
  ]
}
```

在 `demo/seed_loader.py` 的結尾加入：

```python
def load_rules(repo: Repository, path: str | Path) -> list[str]:
    """載入 Authoring Rule 種子檔，回傳寫入的 rule_id 清單。

    種子只提供初始狀態；之後的 status 與 validated_at 一律由
    Phase 20 的 analytics.apply_rule_status 寫入（設計文件 §12.2）。
    """
    written: list[str] = []
    for item in read_items(path):
        rule = AuthoringRule.model_validate(item)
        repo.put_rule(rule)
        written.append(rule.rule_id)
    return written
```

在 `demo/seed_loader.py` 的 import 區補上：

```python
from training_kb.models import AuthoringRule
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：`uv run pytest tests/integration/test_seed_rules.py -v`

預期：PASS，6 passed。

- [ ] **步驟 5：commit**

```bash
git add demo/seed/rules.json demo/seed_loader.py tests/integration/test_seed_rules.py
git commit -m "feat(demo): 新增 R-007 與 R-012 規則種子"
```

---

### Task 7：三個核定種子批次與核定流程

**目的**：展開 R-007 的一個批次與 R-012 的兩個不重疊批次，並建立「先驗證、再核定」的流程（對應設計文件待確認事項 O7）。

**檔案**：
- 新增：`demo/seed/batches.json`
- 修改：`demo/seed_loader.py`
- 測試：`tests/integration/test_seed_batches.py`

**介面**：
- 消費（Phase 20）：`analytics.SeedBatch`、`analytics.batch_key(batch_id) -> str`
- 消費（Phase 03）：`repo.put_object(key, body, *, content_type)`
- 產出：
  - `demo.seed_loader.load_batches(path) -> list[SeedBatch]`
  - `demo.seed_loader.upload_batches(repo, path) -> list[str]`（**本階段新增**：把批次寫到 S3 的 `operations/rule-batches/`，Phase 20 才讀得到）
  - `demo.seed_loader.verify_batch_matches_seed(batch, *, feedback_path, views_path, tickets_path) -> list[str]`（**本階段新增**：回傳不一致之處，空清單代表一致）
  - `demo.seed_loader.approve_batch(path, batch_id, *, approver, now) -> None`（**本階段新增**：把 `approved` 改成 `true` 並記下核定人與時間）

**為什麼批次要把記錄再寫一次**：

`SeedBatch` 的欄位（簡報 §6.9）是 `feedback: list[Feedback]`、`views: list[TutorialView]`、`tickets: list[Ticket]`——它是**自帶資料**的，不是只存 ID。這樣 Phase 20 的 `evaluate_batch()` 不必查圖譜就能算，規則驗證的結果不會被「圖譜後來被改了」影響。

代價是 `b_r007_01` 的內容和 `feedback.json`／`views.json`／`reopen_tickets.json` 重複。`verify_batch_matches_seed()` 就是為了這個：它比對兩邊，只要有一筆對不上就回報。兩份一致才代表「Dashboard 上看到的數字」和「規則驗證用的數字」是同一組資料。

**R-012 的兩個批次怎麼設計**：

```text
b_r012_01   rule-lab-demo@v1  ->  @v2     窗口 [06-01, 06-15) / [06-20, 07-04)
   平均評分   15/5 = 3.0   ->   15/5 = 3.0     持平  = 未改善
   重開票率   2/5  = 0.4   ->   2/5  = 0.4     持平  = 未改善

b_r012_02   rule-lab-demo@v3  ->  @v4     窗口 [07-01, 07-15) / [07-20, 08-03)
   平均評分   17/5 = 3.4   ->   16/5 = 3.2     下降  = 未改善
   重開票率   2/5  = 0.4   ->   3/5  = 0.6     上升  = 未改善

版本集合 {v1, v2} 與 {v3, v4} 沒有交集  ->  兩批不重疊
兩批都未改善（持平也算未改善）           ->  R-012 從 active 變成 retired
```

**核定流程（O7）**：

```text
1. 三個批次一開始都是 "approved": false
2. 跑 Task 8 的 verify_recipe()          -> 看到 2.875 / 4.4 / 8 / 2 / 7 / 2 / 0.7 / 0.2
3. 跑 Task 9 的 verify_clusters.py        -> 看到實際 embedding 的分群結果
4. 跑 verify_batch_matches_seed()         -> 看到批次與種子檔一致
5. 人工看過以上三個輸出
6. 執行 approve_batch()                   -> "approved": true，並記下 approved_by / approved_at
7. 執行 upload_batches()                  -> 寫到 S3，Phase 20 才讀得到
```

在第 6 步之前，Phase 20 的 `validate_rule()` 讀到 `approved=false` 會判成「不可判定」，規則狀態一律維持原狀。

- [ ] **步驟 1：寫測試**

```python
# tests/integration/test_seed_batches.py
"""Phase 21 Task 7：三個核定種子批次與核定流程。"""

import json
import shutil

from moto import mock_aws

from demo.seed_loader import (
    SEED_DIR,
    approve_batch,
    load_batches,
    upload_batches,
    verify_batch_matches_seed,
)
from training_kb.analytics import (
    batch_key,
    evaluate_batch,
    load_seed_batch,
    next_status,
)
from training_kb.clock import parse_iso
from training_kb.models import RuleStatus

BATCHES_PATH = SEED_DIR / "batches.json"
APPROVED = ["找不到按鈕", "缺少資訊"]
NOW = parse_iso("2026-09-13T12:00:00Z")


def test_三個批次且一開始都未核定():
    raw = json.loads(BATCHES_PATH.read_text(encoding="utf-8"))
    assert "合成資料示範" in raw["note"]

    batches = load_batches(BATCHES_PATH)
    assert [batch.batch_id for batch in batches] == [
        "b_r007_01",
        "b_r012_01",
        "b_r012_02",
    ]
    assert all(batch.approved is False for batch in batches)


def test_R007_批次自帶完整記錄():
    batch = load_batches(BATCHES_PATH)[0]

    assert batch.rule_id == "R-007"
    assert batch.slug == "prepare-meeting"
    assert batch.before_version == "prepare-meeting@v1"
    assert batch.after_version == "prepare-meeting@v2"
    assert batch.cluster_id == "c12"
    assert batch.published_before == "2026-08-01T00:00:00Z"
    assert batch.published_after == "2026-08-20T00:00:00Z"
    assert len(batch.feedback) == 18
    assert len(batch.views) == 20
    assert len(batch.tickets) == 9


def test_R007_批次與獨立種子檔完全一致():
    batch = load_batches(BATCHES_PATH)[0]

    problems = verify_batch_matches_seed(
        batch,
        feedback_path=SEED_DIR / "feedback.json",
        views_path=SEED_DIR / "views.json",
        tickets_path=SEED_DIR / "reopen_tickets.json",
    )

    assert problems == []


def test_R007_批次核定後算出目標數字():
    batch = load_batches(BATCHES_PATH)[0]
    batch.approved = True

    result = evaluate_batch(
        batch,
        cluster_id=batch.cluster_id,
        published_before=batch.published_before,
        published_after=batch.published_after,
        approved_categories=APPROVED,
    )

    assert result.decidable is True
    assert result.before.avg == 2.875
    assert result.after.avg == 4.4
    assert result.before.negative == 8
    assert result.after.negative == 2
    assert result.before.reopen.count == 7
    assert result.after.reopen.count == 2
    assert result.before.reopen.rate == 0.7
    assert result.after.reopen.rate == 0.2
    assert result.avg_improved is True
    assert result.reopen_improved is True


def test_R012_兩批不重疊且都未改善():
    batches = [b for b in load_batches(BATCHES_PATH) if b.rule_id == "R-012"]
    assert len(batches) == 2

    evaluations = []
    for batch in batches:
        batch.approved = True
        evaluations.append(
            evaluate_batch(
                batch,
                cluster_id=batch.cluster_id,
                published_before=batch.published_before,
                published_after=batch.published_after,
                approved_categories=APPROVED,
            )
        )

    first, second = evaluations
    assert first.before.avg == 3.0 and first.after.avg == 3.0
    assert first.before.reopen.rate == 0.4 and first.after.reopen.rate == 0.4
    assert second.before.avg == 3.4 and second.after.avg == 3.2
    assert second.before.reopen.rate == 0.4 and second.after.reopen.rate == 0.6
    assert all(e.decidable for e in evaluations)
    assert not any(e.avg_improved or e.reopen_improved for e in evaluations)

    versions_first = {first.before.version_id, first.after.version_id}
    versions_second = {second.before.version_id, second.after.version_id}
    assert versions_first.isdisjoint(versions_second)

    assert next_status(RuleStatus.active, evaluations, None) == RuleStatus.retired


def test_approve_batch_寫入核定紀錄(tmp_path):
    copied = tmp_path / "batches.json"
    shutil.copy(BATCHES_PATH, copied)

    approve_batch(copied, "b_r007_01", approver="維護者 A", now=NOW)

    raw = json.loads(copied.read_text(encoding="utf-8"))
    by_id = {item["batch_id"]: item for item in raw["items"]}
    assert by_id["b_r007_01"]["approved"] is True
    assert by_id["b_r007_01"]["approved_by"] == "維護者 A"
    assert by_id["b_r007_01"]["approved_at"] == "2026-09-13T12:00:00Z"
    assert by_id["b_r012_01"]["approved"] is False


@mock_aws
def test_上傳後_Phase20_讀得到批次(repository):
    keys = upload_batches(repository, BATCHES_PATH)

    assert keys == [
        batch_key("b_r007_01"),
        batch_key("b_r012_01"),
        batch_key("b_r012_02"),
    ]
    assert all(key.startswith("operations/rule-batches/") for key in keys)

    batch = load_seed_batch(repository, "b_r007_01")
    assert batch.rule_id == "R-007"
    assert len(batch.feedback) == 18


@mock_aws
def test_批次不會被寫進公開的_site_前綴(repository):
    for key in upload_batches(repository, BATCHES_PATH):
        assert not key.startswith("site/")
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：`uv run pytest tests/integration/test_seed_batches.py -v`

預期：FAIL，`ImportError: cannot import name 'load_batches' from 'demo.seed_loader'`。

- [ ] **步驟 3：寫最少的程式讓測試通過**

建立 `demo/seed/batches.json`。這個檔案比較長，分成三個批次，每個批次都自帶完整記錄：

```json
{
  "note": "合成資料示範。三個核定種子批次（設計文件 §12.2、F32）。b_r007_01 的記錄與 feedback.json／views.json／reopen_tickets.json 完全相同，可用 verify_batch_matches_seed() 核對。b_r012_01／b_r012_02 使用只存在於本檔的合成教學 rule-lab-demo，版本不寫入 DynamoDB，避免污染 A／B／C 的正式資料（本計劃選擇，呼應 F47 的隔離原則）。approved 一律先設為 false，要等 verify_recipe 與 verify_clusters 的輸出經人工看過，才用 approve_batch() 改成 true（對應設計文件 O7）。",
  "items": [
    {
      "batch_id": "b_r007_01",
      "rule_id": "R-007",
      "slug": "prepare-meeting",
      "before_version": "prepare-meeting@v1",
      "after_version": "prepare-meeting@v2",
      "cluster_id": "c12",
      "published_before": "2026-08-01T00:00:00Z",
      "published_after": "2026-08-20T00:00:00Z",
      "approved": false,
      "feedback": [
        {"id": "f_12", "tutorial_version": "prepare-meeting@v1", "rating": 2, "user": "u_01", "category": "找不到按鈕", "comment": "第三步沒有指出按鈕在哪一頁與位置", "ts": "2026-08-02T12:00:00Z"},
        {"id": "f_15", "tutorial_version": "prepare-meeting@v1", "rating": 2, "user": "u_02", "category": "找不到按鈕", "comment": "第三步沒有指出按鈕在哪一頁與位置", "ts": "2026-08-02T12:00:00Z"},
        {"id": "f_19", "tutorial_version": "prepare-meeting@v1", "rating": 3, "user": "u_03", "category": "找不到按鈕", "comment": "第三步沒有指出按鈕在哪一頁與位置", "ts": "2026-08-02T12:00:00Z"},
        {"id": "f_23", "tutorial_version": "prepare-meeting@v1", "rating": 3, "user": "u_04", "category": "找不到按鈕", "comment": "第三步沒有指出按鈕在哪一頁與位置", "ts": "2026-08-02T12:00:00Z"},
        {"id": "f_27", "tutorial_version": "prepare-meeting@v1", "rating": 3, "user": "u_05", "category": "找不到按鈕", "comment": "第三步沒有指出按鈕在哪一頁與位置", "ts": "2026-08-02T12:00:00Z"},
        {"id": "f_31", "tutorial_version": "prepare-meeting@v1", "rating": 3, "user": "u_06", "category": "找不到按鈕", "comment": "第三步沒有指出按鈕在哪一頁與位置", "ts": "2026-08-02T12:00:00Z"},
        {"id": "f_34", "tutorial_version": "prepare-meeting@v1", "rating": 3, "user": "u_07", "category": "找不到按鈕", "comment": "第三步沒有指出按鈕在哪一頁與位置", "ts": "2026-08-02T12:00:00Z"},
        {"id": "f_40", "tutorial_version": "prepare-meeting@v1", "rating": 4, "user": "u_08", "category": "找不到按鈕", "comment": "第三步沒有指出按鈕在哪一頁與位置", "ts": "2026-08-02T12:00:00Z"},
        {"id": "f_101", "tutorial_version": "prepare-meeting@v2", "rating": 2, "user": "u_01", "category": "缺少資訊", "comment": "資訊仍不夠完整", "ts": "2026-08-21T12:00:00Z"},
        {"id": "f_102", "tutorial_version": "prepare-meeting@v2", "rating": 2, "user": "u_02", "category": "缺少資訊", "comment": "資訊仍不夠完整", "ts": "2026-08-21T12:00:00Z"},
        {"id": "f_103", "tutorial_version": "prepare-meeting@v2", "rating": 5, "user": "u_03", "category": null, "comment": null, "ts": "2026-08-21T12:00:00Z"},
        {"id": "f_104", "tutorial_version": "prepare-meeting@v2", "rating": 5, "user": "u_04", "category": null, "comment": null, "ts": "2026-08-21T12:00:00Z"},
        {"id": "f_105", "tutorial_version": "prepare-meeting@v2", "rating": 5, "user": "u_05", "category": null, "comment": null, "ts": "2026-08-21T12:00:00Z"},
        {"id": "f_106", "tutorial_version": "prepare-meeting@v2", "rating": 5, "user": "u_06", "category": null, "comment": null, "ts": "2026-08-21T12:00:00Z"},
        {"id": "f_107", "tutorial_version": "prepare-meeting@v2", "rating": 5, "user": "u_07", "category": null, "comment": null, "ts": "2026-08-21T12:00:00Z"},
        {"id": "f_108", "tutorial_version": "prepare-meeting@v2", "rating": 5, "user": "u_08", "category": null, "comment": null, "ts": "2026-08-21T12:00:00Z"},
        {"id": "f_109", "tutorial_version": "prepare-meeting@v2", "rating": 5, "user": "u_09", "category": null, "comment": null, "ts": "2026-08-21T12:00:00Z"},
        {"id": "f_110", "tutorial_version": "prepare-meeting@v2", "rating": 5, "user": "u_10", "category": null, "comment": null, "ts": "2026-08-21T12:00:00Z"}
      ],
      "views": [
        {"tutorial_version": "prepare-meeting@v1", "user": "u_01", "ts": "2026-08-02T09:00:00Z"},
        {"tutorial_version": "prepare-meeting@v1", "user": "u_02", "ts": "2026-08-02T09:00:00Z"},
        {"tutorial_version": "prepare-meeting@v1", "user": "u_03", "ts": "2026-08-02T09:00:00Z"},
        {"tutorial_version": "prepare-meeting@v1", "user": "u_04", "ts": "2026-08-02T09:00:00Z"},
        {"tutorial_version": "prepare-meeting@v1", "user": "u_05", "ts": "2026-08-02T09:00:00Z"},
        {"tutorial_version": "prepare-meeting@v1", "user": "u_06", "ts": "2026-08-02T09:00:00Z"},
        {"tutorial_version": "prepare-meeting@v1", "user": "u_07", "ts": "2026-08-02T09:00:00Z"},
        {"tutorial_version": "prepare-meeting@v1", "user": "u_08", "ts": "2026-08-02T09:00:00Z"},
        {"tutorial_version": "prepare-meeting@v1", "user": "u_09", "ts": "2026-08-02T09:00:00Z"},
        {"tutorial_version": "prepare-meeting@v1", "user": "u_10", "ts": "2026-08-02T09:00:00Z"},
        {"tutorial_version": "prepare-meeting@v2", "user": "u_01", "ts": "2026-08-21T09:00:00Z"},
        {"tutorial_version": "prepare-meeting@v2", "user": "u_02", "ts": "2026-08-21T09:00:00Z"},
        {"tutorial_version": "prepare-meeting@v2", "user": "u_03", "ts": "2026-08-21T09:00:00Z"},
        {"tutorial_version": "prepare-meeting@v2", "user": "u_04", "ts": "2026-08-21T09:00:00Z"},
        {"tutorial_version": "prepare-meeting@v2", "user": "u_05", "ts": "2026-08-21T09:00:00Z"},
        {"tutorial_version": "prepare-meeting@v2", "user": "u_06", "ts": "2026-08-21T09:00:00Z"},
        {"tutorial_version": "prepare-meeting@v2", "user": "u_07", "ts": "2026-08-21T09:00:00Z"},
        {"tutorial_version": "prepare-meeting@v2", "user": "u_08", "ts": "2026-08-21T09:00:00Z"},
        {"tutorial_version": "prepare-meeting@v2", "user": "u_09", "ts": "2026-08-21T09:00:00Z"},
        {"tutorial_version": "prepare-meeting@v2", "user": "u_10", "ts": "2026-08-21T09:00:00Z"}
      ],
      "tickets": [
        {"id": "t_2001", "source": "email", "text": "看過準備會議教學後，仍找不到第三步的按鈕", "author": "u_01", "ts": "2026-08-03T10:00:00Z", "project_id": "demo-project", "cluster_id": "c12", "feature_ids": []},
        {"id": "t_2002", "source": "email", "text": "看過準備會議教學後，仍找不到第三步的按鈕", "author": "u_02", "ts": "2026-08-03T10:00:00Z", "project_id": "demo-project", "cluster_id": "c12", "feature_ids": []},
        {"id": "t_2003", "source": "email", "text": "看過準備會議教學後，仍找不到第三步的按鈕", "author": "u_03", "ts": "2026-08-03T10:00:00Z", "project_id": "demo-project", "cluster_id": "c12", "feature_ids": []},
        {"id": "t_2004", "source": "email", "text": "看過準備會議教學後，仍找不到第三步的按鈕", "author": "u_04", "ts": "2026-08-03T10:00:00Z", "project_id": "demo-project", "cluster_id": "c12", "feature_ids": []},
        {"id": "t_2005", "source": "email", "text": "看過準備會議教學後，仍找不到第三步的按鈕", "author": "u_05", "ts": "2026-08-03T10:00:00Z", "project_id": "demo-project", "cluster_id": "c12", "feature_ids": []},
        {"id": "t_2006", "source": "email", "text": "看過準備會議教學後，仍找不到第三步的按鈕", "author": "u_06", "ts": "2026-08-03T10:00:00Z", "project_id": "demo-project", "cluster_id": "c12", "feature_ids": []},
        {"id": "t_2007", "source": "email", "text": "看過準備會議教學後，仍找不到第三步的按鈕", "author": "u_07", "ts": "2026-08-03T10:00:00Z", "project_id": "demo-project", "cluster_id": "c12", "feature_ids": []},
        {"id": "t_2101", "source": "email", "text": "看過準備會議教學後，仍找不到第三步的按鈕", "author": "u_01", "ts": "2026-08-22T10:00:00Z", "project_id": "demo-project", "cluster_id": "c12", "feature_ids": []},
        {"id": "t_2102", "source": "email", "text": "看過準備會議教學後，仍找不到第三步的按鈕", "author": "u_02", "ts": "2026-08-22T10:00:00Z", "project_id": "demo-project", "cluster_id": "c12", "feature_ids": []}
      ]
    },
    {
      "batch_id": "b_r012_01",
      "rule_id": "R-012",
      "slug": "rule-lab-demo",
      "before_version": "rule-lab-demo@v1",
      "after_version": "rule-lab-demo@v2",
      "cluster_id": "c30",
      "published_before": "2026-06-01T00:00:00Z",
      "published_after": "2026-06-20T00:00:00Z",
      "approved": false,
      "feedback": [
        {"id": "f_201", "tutorial_version": "rule-lab-demo@v1", "rating": 3, "user": "u_01", "category": "缺少資訊", "comment": "步驟太短，看不懂要點哪裡", "ts": "2026-06-02T12:00:00Z"},
        {"id": "f_202", "tutorial_version": "rule-lab-demo@v1", "rating": 3, "user": "u_02", "category": "缺少資訊", "comment": "步驟太短，看不懂要點哪裡", "ts": "2026-06-02T12:00:00Z"},
        {"id": "f_203", "tutorial_version": "rule-lab-demo@v1", "rating": 3, "user": "u_03", "category": "缺少資訊", "comment": "步驟太短，看不懂要點哪裡", "ts": "2026-06-02T12:00:00Z"},
        {"id": "f_204", "tutorial_version": "rule-lab-demo@v1", "rating": 3, "user": "u_04", "category": "缺少資訊", "comment": "步驟太短，看不懂要點哪裡", "ts": "2026-06-02T12:00:00Z"},
        {"id": "f_205", "tutorial_version": "rule-lab-demo@v1", "rating": 3, "user": "u_05", "category": "缺少資訊", "comment": "步驟太短，看不懂要點哪裡", "ts": "2026-06-02T12:00:00Z"},
        {"id": "f_211", "tutorial_version": "rule-lab-demo@v2", "rating": 3, "user": "u_01", "category": "缺少資訊", "comment": "改寫後還是太短", "ts": "2026-06-21T12:00:00Z"},
        {"id": "f_212", "tutorial_version": "rule-lab-demo@v2", "rating": 3, "user": "u_02", "category": "缺少資訊", "comment": "改寫後還是太短", "ts": "2026-06-21T12:00:00Z"},
        {"id": "f_213", "tutorial_version": "rule-lab-demo@v2", "rating": 3, "user": "u_03", "category": "缺少資訊", "comment": "改寫後還是太短", "ts": "2026-06-21T12:00:00Z"},
        {"id": "f_214", "tutorial_version": "rule-lab-demo@v2", "rating": 3, "user": "u_04", "category": "缺少資訊", "comment": "改寫後還是太短", "ts": "2026-06-21T12:00:00Z"},
        {"id": "f_215", "tutorial_version": "rule-lab-demo@v2", "rating": 3, "user": "u_05", "category": "缺少資訊", "comment": "改寫後還是太短", "ts": "2026-06-21T12:00:00Z"}
      ],
      "views": [
        {"tutorial_version": "rule-lab-demo@v1", "user": "u_01", "ts": "2026-06-02T09:00:00Z"},
        {"tutorial_version": "rule-lab-demo@v1", "user": "u_02", "ts": "2026-06-02T09:00:00Z"},
        {"tutorial_version": "rule-lab-demo@v1", "user": "u_03", "ts": "2026-06-02T09:00:00Z"},
        {"tutorial_version": "rule-lab-demo@v1", "user": "u_04", "ts": "2026-06-02T09:00:00Z"},
        {"tutorial_version": "rule-lab-demo@v1", "user": "u_05", "ts": "2026-06-02T09:00:00Z"},
        {"tutorial_version": "rule-lab-demo@v2", "user": "u_01", "ts": "2026-06-21T09:00:00Z"},
        {"tutorial_version": "rule-lab-demo@v2", "user": "u_02", "ts": "2026-06-21T09:00:00Z"},
        {"tutorial_version": "rule-lab-demo@v2", "user": "u_03", "ts": "2026-06-21T09:00:00Z"},
        {"tutorial_version": "rule-lab-demo@v2", "user": "u_04", "ts": "2026-06-21T09:00:00Z"},
        {"tutorial_version": "rule-lab-demo@v2", "user": "u_05", "ts": "2026-06-21T09:00:00Z"}
      ],
      "tickets": [
        {"id": "t_3001", "source": "email", "text": "看過教學還是不知道要在哪一頁操作", "author": "u_01", "ts": "2026-06-03T10:00:00Z", "project_id": "demo-project", "cluster_id": "c30", "feature_ids": []},
        {"id": "t_3002", "source": "email", "text": "看過教學還是不知道要在哪一頁操作", "author": "u_02", "ts": "2026-06-03T10:00:00Z", "project_id": "demo-project", "cluster_id": "c30", "feature_ids": []},
        {"id": "t_3011", "source": "email", "text": "看過教學還是不知道要在哪一頁操作", "author": "u_01", "ts": "2026-06-22T10:00:00Z", "project_id": "demo-project", "cluster_id": "c30", "feature_ids": []},
        {"id": "t_3012", "source": "email", "text": "看過教學還是不知道要在哪一頁操作", "author": "u_02", "ts": "2026-06-22T10:00:00Z", "project_id": "demo-project", "cluster_id": "c30", "feature_ids": []}
      ]
    },
    {
      "batch_id": "b_r012_02",
      "rule_id": "R-012",
      "slug": "rule-lab-demo",
      "before_version": "rule-lab-demo@v3",
      "after_version": "rule-lab-demo@v4",
      "cluster_id": "c30",
      "published_before": "2026-07-01T00:00:00Z",
      "published_after": "2026-07-20T00:00:00Z",
      "approved": false,
      "feedback": [
        {"id": "f_221", "tutorial_version": "rule-lab-demo@v3", "rating": 4, "user": "u_01", "category": null, "comment": null, "ts": "2026-07-02T12:00:00Z"},
        {"id": "f_222", "tutorial_version": "rule-lab-demo@v3", "rating": 4, "user": "u_02", "category": null, "comment": null, "ts": "2026-07-02T12:00:00Z"},
        {"id": "f_223", "tutorial_version": "rule-lab-demo@v3", "rating": 3, "user": "u_03", "category": "缺少資訊", "comment": "還是漏了設定位置", "ts": "2026-07-02T12:00:00Z"},
        {"id": "f_224", "tutorial_version": "rule-lab-demo@v3", "rating": 3, "user": "u_04", "category": "缺少資訊", "comment": "還是漏了設定位置", "ts": "2026-07-02T12:00:00Z"},
        {"id": "f_225", "tutorial_version": "rule-lab-demo@v3", "rating": 3, "user": "u_05", "category": "缺少資訊", "comment": "還是漏了設定位置", "ts": "2026-07-02T12:00:00Z"},
        {"id": "f_231", "tutorial_version": "rule-lab-demo@v4", "rating": 3, "user": "u_01", "category": "缺少資訊", "comment": "兩句寫不完整個流程", "ts": "2026-07-21T12:00:00Z"},
        {"id": "f_232", "tutorial_version": "rule-lab-demo@v4", "rating": 3, "user": "u_02", "category": "缺少資訊", "comment": "兩句寫不完整個流程", "ts": "2026-07-21T12:00:00Z"},
        {"id": "f_233", "tutorial_version": "rule-lab-demo@v4", "rating": 3, "user": "u_03", "category": "缺少資訊", "comment": "兩句寫不完整個流程", "ts": "2026-07-21T12:00:00Z"},
        {"id": "f_234", "tutorial_version": "rule-lab-demo@v4", "rating": 3, "user": "u_04", "category": "缺少資訊", "comment": "兩句寫不完整個流程", "ts": "2026-07-21T12:00:00Z"},
        {"id": "f_235", "tutorial_version": "rule-lab-demo@v4", "rating": 4, "user": "u_05", "category": null, "comment": null, "ts": "2026-07-21T12:00:00Z"}
      ],
      "views": [
        {"tutorial_version": "rule-lab-demo@v3", "user": "u_01", "ts": "2026-07-02T09:00:00Z"},
        {"tutorial_version": "rule-lab-demo@v3", "user": "u_02", "ts": "2026-07-02T09:00:00Z"},
        {"tutorial_version": "rule-lab-demo@v3", "user": "u_03", "ts": "2026-07-02T09:00:00Z"},
        {"tutorial_version": "rule-lab-demo@v3", "user": "u_04", "ts": "2026-07-02T09:00:00Z"},
        {"tutorial_version": "rule-lab-demo@v3", "user": "u_05", "ts": "2026-07-02T09:00:00Z"},
        {"tutorial_version": "rule-lab-demo@v4", "user": "u_01", "ts": "2026-07-21T09:00:00Z"},
        {"tutorial_version": "rule-lab-demo@v4", "user": "u_02", "ts": "2026-07-21T09:00:00Z"},
        {"tutorial_version": "rule-lab-demo@v4", "user": "u_03", "ts": "2026-07-21T09:00:00Z"},
        {"tutorial_version": "rule-lab-demo@v4", "user": "u_04", "ts": "2026-07-21T09:00:00Z"},
        {"tutorial_version": "rule-lab-demo@v4", "user": "u_05", "ts": "2026-07-21T09:00:00Z"}
      ],
      "tickets": [
        {"id": "t_3021", "source": "email", "text": "看過教學還是不知道要在哪一頁操作", "author": "u_01", "ts": "2026-07-03T10:00:00Z", "project_id": "demo-project", "cluster_id": "c30", "feature_ids": []},
        {"id": "t_3022", "source": "email", "text": "看過教學還是不知道要在哪一頁操作", "author": "u_02", "ts": "2026-07-03T10:00:00Z", "project_id": "demo-project", "cluster_id": "c30", "feature_ids": []},
        {"id": "t_3031", "source": "email", "text": "看過教學還是不知道要在哪一頁操作", "author": "u_01", "ts": "2026-07-22T10:00:00Z", "project_id": "demo-project", "cluster_id": "c30", "feature_ids": []},
        {"id": "t_3032", "source": "email", "text": "看過教學還是不知道要在哪一頁操作", "author": "u_02", "ts": "2026-07-22T10:00:00Z", "project_id": "demo-project", "cluster_id": "c30", "feature_ids": []},
        {"id": "t_3033", "source": "email", "text": "看過教學還是不知道要在哪一頁操作", "author": "u_03", "ts": "2026-07-22T10:00:00Z", "project_id": "demo-project", "cluster_id": "c30", "feature_ids": []}
      ]
    }
  ]
}
```

在 `demo/seed_loader.py` 的結尾加入：

```python
def load_batches(path: str | Path) -> list[SeedBatch]:
    """讀批次種子檔，回傳 SeedBatch 清單（順序即檔案順序，也就是時間順序）。"""
    return [SeedBatch.model_validate(item) for item in read_items(path)]


def upload_batches(repo: Repository, path: str | Path) -> list[str]:
    """把批次寫到 S3 的 operations/rule-batches/，回傳寫入的 key 清單。

    這是私有前綴（設計文件 §9.3），不會出現在公開的 site/ 底下。
    """
    keys: list[str] = []
    for item in read_items(path):
        batch = SeedBatch.model_validate(item)
        key = batch_key(batch.batch_id)
        repo.put_object(
            key,
            json.dumps(item, ensure_ascii=False, sort_keys=True),
            content_type="application/json",
        )
        keys.append(key)
    return keys


def _compare_records(
    label: str, batch_rows: list[dict], seed_rows: list[dict]
) -> list[str]:
    """比對兩組記錄；回傳不一致的描述。"""
    problems: list[str] = []
    if len(batch_rows) != len(seed_rows):
        problems.append(
            f"{label} 筆數不同：批次 {len(batch_rows)} 筆，種子檔 {len(seed_rows)} 筆"
        )
    for index, (left, right) in enumerate(zip(batch_rows, seed_rows)):
        if left != right:
            problems.append(f"{label} 第 {index + 1} 筆不一致：{left} vs {right}")
    return problems


def verify_batch_matches_seed(
    batch: SeedBatch,
    *,
    feedback_path: str | Path,
    views_path: str | Path,
    tickets_path: str | Path,
) -> list[str]:
    """核對批次自帶的記錄與獨立種子檔是否完全相同。

    回傳不一致的描述；空清單代表兩邊一致。
    Dashboard 讀的是圖譜、規則驗證讀的是批次，兩者一致才能宣稱同一組資料。
    """
    problems: list[str] = []
    problems.extend(
        _compare_records(
            "feedback",
            [row.model_dump() for row in batch.feedback],
            [
                Feedback.model_validate(item).model_dump()
                for item in read_items(feedback_path)
            ],
        )
    )
    problems.extend(
        _compare_records(
            "views",
            [row.model_dump() for row in batch.views],
            [
                TutorialView.model_validate(item).model_dump()
                for item in read_items(views_path)
            ],
        )
    )
    problems.extend(
        _compare_records(
            "tickets",
            [row.model_dump() for row in batch.tickets],
            [
                Ticket.model_validate(item).model_dump()
                for item in read_items(tickets_path)
            ],
        )
    )
    return problems


def approve_batch(
    path: str | Path, batch_id: str, *, approver: str, now: datetime
) -> None:
    """把指定批次標成已核定，並記下核定人與時間（對應設計文件 O7）。

    只有在 verify_recipe()、verify_clusters.py 與 verify_batch_matches_seed()
    的輸出都被人看過之後才執行這個動作。
    """
    file_path = Path(path)
    raw = json.loads(file_path.read_text(encoding="utf-8"))
    found = False
    for item in raw["items"]:
        if item["batch_id"] == batch_id:
            item["approved"] = True
            item["approved_by"] = approver
            item["approved_at"] = to_iso(now)
            found = True
    if not found:
        raise PermanentError(f"批次檔內找不到 {batch_id}")
    file_path.write_text(
        json.dumps(raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
```

在 `demo/seed_loader.py` 的 import 區補上：

```python
from training_kb.analytics import SeedBatch, batch_key
from training_kb.models import Feedback, TutorialView
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：`uv run pytest tests/integration/test_seed_batches.py -v`

預期：PASS，8 passed。

- [ ] **步驟 5：commit**

```bash
git add demo/seed/batches.json demo/seed_loader.py tests/integration/test_seed_batches.py
git commit -m "feat(demo): 新增三個核定種子批次與核定流程"
```

---

### Task 8：verify_recipe — 用真的程式重算目標數字

**目的**：證明 2.875、4.4、8、2、7、2、0.7、0.2 是**算出來**的，不是寫死的（設計文件 F46）。

**檔案**：
- 修改：`demo/seed_loader.py`
- 測試：`tests/integration/test_seed_verify_recipe.py`

**介面**：
- 消費（Phase 19）：`analytics.version_metrics(repo, version_id, *, approved_categories) -> VersionMetrics`
- 消費（Phase 02）：`models.APPROVED_CATEGORIES_DEFAULT`
- 產出：
  - `demo.seed_loader.EXPECTED_RECIPE`（**本階段新增**：設計文件 §11.2、§11.3 的目標值字典）
  - `demo.seed_loader.verify_recipe(repo, *, approved_categories) -> dict`
  - `demo.seed_loader.check_recipe(actual) -> list[str]`（**本階段新增**：回傳不符之處，空清單代表全中）
  - `demo.seed_loader.load_all(repo, renderer, *, now, seed_dir=SEED_DIR) -> dict`（**本階段新增**：依正確順序跑完所有 `load_*`）

**八個目標值**：

| 鍵 | 目標值 | 來源 |
|---|---|---|
| `A_v1_avg` | 2.875 | 設計文件 §11.2：23 ÷ 8 |
| `A_v2_avg` | 4.4 | 設計文件 §11.2：44 ÷ 10 |
| `A_v1_negative` | 8 | 設計文件 §11.2：八筆皆有核定問題類別 |
| `A_v2_negative` | 2 | 設計文件 §11.2：只有兩筆低分或問題類別 |
| `A_v1_reopen` | 7 | 設計文件 §11.3：重開票筆數 |
| `A_v2_reopen` | 2 | 設計文件 §11.3：重開票筆數 |
| `A_v1_rate` | 0.7 | 設計文件 §11.3：7 ÷ 10 |
| `A_v2_rate` | 0.2 | 設計文件 §11.3：2 ÷ 10 |

**注意**：`A_v1_avg` 是 `2.875` 不是 `2.9`。設計文件 §11.2 明說「指標判斷使用未四捨五入的數值；顯示位數不影響門檻」。`2.9` 只是畫面上的顯示。

- [ ] **步驟 1：寫測試**

```python
# tests/integration/test_seed_verify_recipe.py
"""Phase 21 Task 8：用 Phase 19 的函式重算配方目標值。"""

from moto import mock_aws

from demo.seed_loader import (
    EXPECTED_RECIPE,
    SEED_DIR,
    check_recipe,
    load_all,
    verify_recipe,
)
from training_kb.clock import parse_iso
from training_kb.models import APPROVED_CATEGORIES_DEFAULT
from training_kb.site import SiteRenderer

NOW = parse_iso("2026-09-13T12:00:00Z")


def test_目標值字典與設計文件一致():
    assert EXPECTED_RECIPE == {
        "A_v1_avg": 2.875,
        "A_v2_avg": 4.4,
        "A_v1_negative": 8,
        "A_v2_negative": 2,
        "A_v1_reopen": 7,
        "A_v2_reopen": 2,
        "A_v1_rate": 0.7,
        "A_v2_rate": 0.2,
    }


@mock_aws
def test_載入完整種子後重算出全部目標值(repository):
    load_all(repository, SiteRenderer(), now=NOW, seed_dir=SEED_DIR)

    actual = verify_recipe(
        repository, approved_categories=list(APPROVED_CATEGORIES_DEFAULT)
    )

    assert actual == EXPECTED_RECIPE
    assert check_recipe(actual) == []


@mock_aws
def test_平均使用未四捨五入的值(repository):
    load_all(repository, SiteRenderer(), now=NOW, seed_dir=SEED_DIR)

    actual = verify_recipe(
        repository, approved_categories=list(APPROVED_CATEGORIES_DEFAULT)
    )

    assert actual["A_v1_avg"] == 2.875
    assert actual["A_v1_avg"] != 2.9
    assert round(actual["A_v1_avg"], 1) == 2.9


@mock_aws
def test_少載入回饋時_check_recipe_會指出差異(repository):
    summary = load_all(
        repository, SiteRenderer(), now=NOW, seed_dir=SEED_DIR, with_feedback=False
    )
    assert summary["feedback"] == 0

    actual = verify_recipe(
        repository, approved_categories=list(APPROVED_CATEGORIES_DEFAULT)
    )
    problems = check_recipe(actual)

    assert problems != []
    assert any("A_v1_avg" in problem for problem in problems)


@mock_aws
def test_load_all_回傳每種資料的筆數(repository):
    summary = load_all(repository, SiteRenderer(), now=NOW, seed_dir=SEED_DIR)

    assert summary == {
        "features": 3,
        "tutorials": 4,
        "tickets": 20,
        "reopen_tickets": 9,
        "releases": 1,
        "feedback": 18,
        "views": 20,
        "rules": 2,
        "batches": 3,
    }
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：`uv run pytest tests/integration/test_seed_verify_recipe.py -v`

預期：FAIL，`ImportError: cannot import name 'EXPECTED_RECIPE' from 'demo.seed_loader'`。

- [ ] **步驟 3：寫最少的程式讓測試通過**

在 `demo/seed_loader.py` 的結尾加入：

```python
EXPECTED_RECIPE: dict[str, float | int] = {
    # 設計文件 §11.2：A v1 總分 23／8 筆，A v2 總分 44／10 筆
    "A_v1_avg": 2.875,
    "A_v2_avg": 4.4,
    # 設計文件 §11.2：rating<=2 或核定問題類別的 Feedback ID 集合大小
    "A_v1_negative": 8,
    "A_v2_negative": 2,
    # 設計文件 §11.3：重開票筆數（筆數，不是比例）
    "A_v1_reopen": 7,
    "A_v2_reopen": 2,
    # 設計文件 §11.3：不同開票使用者數 ÷ 窗口內不同瀏覽者數
    "A_v1_rate": 0.7,
    "A_v2_rate": 0.2,
}


def verify_recipe(repo: Repository, *, approved_categories: list[str]) -> dict:
    """用 Phase 19 的 version_metrics 重算配方目標值。

    設計文件 F46：2.9、4.4、7、2 是資料必須能重現的目標，
    不是寫死的展示值。這個函式只負責「算」，比對交給 check_recipe()。
    """
    v1 = version_metrics(
        repo, "prepare-meeting@v1", approved_categories=approved_categories
    )
    v2 = version_metrics(
        repo, "prepare-meeting@v2", approved_categories=approved_categories
    )
    return {
        "A_v1_avg": v1.avg,
        "A_v2_avg": v2.avg,
        "A_v1_negative": v1.negative,
        "A_v2_negative": v2.negative,
        "A_v1_reopen": v1.reopen.count,
        "A_v2_reopen": v2.reopen.count,
        "A_v1_rate": v1.reopen.rate,
        "A_v2_rate": v2.reopen.rate,
    }


def check_recipe(actual: dict) -> list[str]:
    """比對重算結果與目標值；回傳不符的描述，空清單代表全中。"""
    problems: list[str] = []
    for key, expected in EXPECTED_RECIPE.items():
        got = actual.get(key)
        if got != expected:
            problems.append(f"{key}：期望 {expected}，實際 {got}")
    return problems


def load_all(
    repo: Repository,
    renderer: SiteRenderer,
    *,
    now: datetime,
    seed_dir: Path = SEED_DIR,
    with_feedback: bool = True,
) -> dict:
    """依正確順序載入整套種子，回傳每種資料的筆數。

    順序很重要：先有 Feature，步驟的引用才驗得過；
    先有版本，回饋與瀏覽的 REFERS_TO 才有對象。
    with_feedback 只有測試會用到，用來製造「資料不齊」的情境。
    """
    features = load_features(repo, seed_dir / "features.json")
    tutorials = load_tutorials(repo, seed_dir / "tutorials", renderer, now)
    tickets = load_tickets(repo, seed_dir / "tickets.json", now=now)
    reopen = load_tickets(repo, seed_dir / "reopen_tickets.json", now=now)
    releases = load_releases(repo, seed_dir / "releases.json")
    feedback = (
        load_feedback(repo, seed_dir / "feedback.json", now=now) if with_feedback else []
    )
    views = load_views(repo, seed_dir / "views.json")
    rules = load_rules(repo, seed_dir / "rules.json")
    batches = upload_batches(repo, seed_dir / "batches.json")
    return {
        "features": len(features),
        "tutorials": len(tutorials),
        "tickets": len(tickets),
        "reopen_tickets": len(reopen),
        "releases": len(releases),
        "feedback": len(feedback),
        "views": views,
        "rules": len(rules),
        "batches": len(batches),
    }
```

在 `demo/seed_loader.py` 的 import 區補上：

```python
from training_kb.analytics import version_metrics
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：`uv run pytest tests/integration/test_seed_verify_recipe.py -v`

預期：PASS，5 passed。

- [ ] **步驟 5：commit**

```bash
git add demo/seed_loader.py tests/integration/test_seed_verify_recipe.py
git commit -m "feat(demo): 以真實指標函式重算種子配方目標值"
```

---

### Task 9：verify_clusters.py — 真的呼叫 Titan 驗證分群

**目的**：回應設計文件 §11.1 的要求——「實作時展開為二十筆完整資料並驗證實際 embedding 分群；不能只把所有 cluster_id 寫成 c12 就聲稱已測過分群」。

**檔案**：
- 新增：`demo/verify_clusters.py`
- 測試：`tests/unit/test_verify_clusters.py`

**介面**：
- 消費（Phase 01）：`config.load_settings()`、`clock.now_utc()`
- 消費（Phase 05）：`writing.client.build_writer(settings, trace)`、`writing.client.CallTrace`、`writing.client.cosine(a, b)`、`writing.client.centroid(vectors)`、`FakeWriter`
- 消費（Task 2）：`demo.seed_loader.read_items`、`demo.seed_loader.SEED_DIR`
- 產出：
  - `demo.verify_clusters.ClusterReport`（**本階段新增**：dataclass，`groups: list[list[str]]`、`sizes: list[int]`、`largest: int`、`recurring_groups: int`）
  - `demo.verify_clusters.cluster_tickets(texts_by_id, embed, *, threshold=0.85, min_tickets=5) -> ClusterReport`（**本階段新增**：純函式，`embed` 是 `Callable[[str], list[float]]`）
  - `demo.verify_clusters.main() -> int`（**本階段新增**：命令列進入點）

**分群方法**（與 Phase 13 的 `task_cluster` 同一套邏輯，設計文件 F10）：

```text
對每一則工單（依 ID 排序）：
    算出它的 1024 維 Titan 向量
    跟目前每一群的「群中心」比 cosine
    最高的那群若 >= 0.85       -> 加入該群，重算群中心
    沒有任何群達 0.85          -> 自己開一個新群
最後輸出每群的工單 ID 與筆數，並標出哪些群達到 recurring 門檻（>= 5 筆）
```

**這個腳本會真的花錢呼叫 Bedrock**（20 次 Titan embedding）。它不是 pytest 測試的一部分——單元測試用 `FakeWriter` 驗演算法，真實呼叫由維護者手動執行一次並把輸出貼進核定紀錄。

**不保證的事**：本文件不宣稱「實際跑出來一定是 12／5／3 三群」。真實 embedding 的結果要跑過才知道。腳本的職責是**把實際結果印出來**，讓人判斷種子是否需要調整。若 A 群不足 5 筆，或 A、B 合併成一群，就修改工單文字讓語意差異更明顯，再重跑。

- [ ] **步驟 1：寫測試**

```python
# tests/unit/test_verify_clusters.py
"""Phase 21 Task 9：embedding 分群驗證腳本的演算法。"""

import math

from demo.verify_clusters import ClusterReport, cluster_tickets


def _unit(x: float, y: float) -> list[float]:
    length = math.sqrt(x * x + y * y)
    return [x / length, y / length, 0.0]


VECTORS = {
    # 三個非常接近的向量（夾角小，cosine > 0.85）
    "t_a1": _unit(1.0, 0.00),
    "t_a2": _unit(1.0, 0.05),
    "t_a3": _unit(1.0, 0.10),
    # 兩個彼此接近、但與上面正交的向量
    "t_b1": _unit(0.0, 1.0),
    "t_b2": _unit(0.05, 1.0),
}


def _fake_embed(text: str) -> list[float]:
    return VECTORS[text]


def test_相近的工單會分在同一群():
    texts = {tid: tid for tid in VECTORS}

    report = cluster_tickets(texts, _fake_embed, threshold=0.85, min_tickets=5)

    assert isinstance(report, ClusterReport)
    assert report.groups == [["t_a1", "t_a2", "t_a3"], ["t_b1", "t_b2"]]
    assert report.sizes == [3, 2]
    assert report.largest == 3


def test_門檻提高時每個工單自成一群():
    texts = {tid: tid for tid in VECTORS}

    report = cluster_tickets(texts, _fake_embed, threshold=0.999, min_tickets=5)

    assert report.sizes == [1, 1, 1, 1, 1]
    assert report.largest == 1
    assert report.recurring_groups == 0


def test_達到_recurring_門檻的群會被算出來():
    texts = {tid: tid for tid in VECTORS}

    report = cluster_tickets(texts, _fake_embed, threshold=0.85, min_tickets=3)

    assert report.recurring_groups == 1


def test_空輸入回傳空報告():
    report = cluster_tickets({}, _fake_embed)

    assert report.groups == []
    assert report.sizes == []
    assert report.largest == 0
    assert report.recurring_groups == 0


def test_結果與輸入順序無關():
    forward = cluster_tickets({tid: tid for tid in VECTORS}, _fake_embed)
    backward = cluster_tickets(
        {tid: tid for tid in reversed(list(VECTORS))}, _fake_embed
    )

    assert forward.groups == backward.groups
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：`uv run pytest tests/unit/test_verify_clusters.py -v`

預期：FAIL，`ModuleNotFoundError: No module named 'demo.verify_clusters'`。

- [ ] **步驟 3：寫最少的程式讓測試通過**

建立 `demo/verify_clusters.py`：

```python
"""對種子工單真的呼叫 Titan 算 embedding，並驗證 cosine 分群結果。

設計文件 §11.1 要求：「實作時展開為二十筆完整資料並驗證實際 embedding 分群；
不能只把所有 cluster_id 寫成 c12 就聲稱已測過分群。」

這支腳本會實際送出 Bedrock 請求（每則工單一次 Titan embedding），
不屬於 pytest 測試。分群演算法本身由 tests/unit/test_verify_clusters.py 驗證。

用法：
    uv run python demo/verify_clusters.py
    uv run python demo/verify_clusters.py --threshold 0.9
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from dataclasses import dataclass, field

from demo.seed_loader import SEED_DIR, read_items
from training_kb.clock import now_utc, to_iso
from training_kb.config import load_settings
from training_kb.writing.client import CallTrace, build_writer, centroid, cosine


@dataclass
class ClusterReport:
    """分群結果。groups 內各群依加入順序排列，群之間依第一筆 ID 排序。"""

    groups: list[list[str]] = field(default_factory=list)
    sizes: list[int] = field(default_factory=list)
    largest: int = 0
    recurring_groups: int = 0


def cluster_tickets(
    texts_by_id: dict[str, str],
    embed: Callable[[str], list[float]],
    *,
    threshold: float = 0.85,
    min_tickets: int = 5,
) -> ClusterReport:
    """依群中心 cosine 分群（設計文件 F10）。

    逐則工單（依 ID 排序）與每個群的中心向量比 cosine，
    達 threshold 的群中選相似度最高者；都不達標就開新群。
    """
    groups: list[list[str]] = []
    centroids: list[list[float]] = []
    vectors: dict[str, list[float]] = {}

    for ticket_id in sorted(texts_by_id):
        vector = embed(texts_by_id[ticket_id])
        vectors[ticket_id] = vector

        best_index = -1
        best_score = threshold
        for index, center in enumerate(centroids):
            score = cosine(vector, center)
            if score >= best_score:
                best_score = score
                best_index = index

        if best_index < 0:
            groups.append([ticket_id])
            centroids.append(list(vector))
        else:
            groups[best_index].append(ticket_id)
            centroids[best_index] = centroid(
                [vectors[member] for member in groups[best_index]]
            )

    ordered = sorted(groups, key=lambda members: members[0])
    sizes = [len(members) for members in ordered]
    return ClusterReport(
        groups=ordered,
        sizes=sizes,
        largest=max(sizes) if sizes else 0,
        recurring_groups=sum(1 for size in sizes if size >= min_tickets),
    )


def main() -> int:
    """讀 demo/seed/tickets.json，對每則工單呼叫 Titan，印出分群結果。"""
    parser = argparse.ArgumentParser(
        description="對種子工單實際呼叫 Titan 並驗證 cosine 分群"
    )
    parser.add_argument("--threshold", type=float, default=0.85, help="同群 cosine 門檻")
    parser.add_argument(
        "--min-tickets", type=int, default=5, help="recurring 門檻（同群筆數）"
    )
    args = parser.parse_args()

    settings = load_settings()
    trace = CallTrace()
    writer = build_writer(settings, trace)

    items = read_items(SEED_DIR / "tickets.json")
    texts_by_id = {item["id"]: item["text"] for item in items}
    expected_group = {item["id"]: item.get("expected_group", "") for item in items}

    started = to_iso(now_utc())
    print("合成資料示範：以下為種子工單的實際 embedding 分群結果。")
    print(f"執行時間：{started}")
    print(f"模型：{settings.embed_model_id}，維度：{settings.embed_dimensions}")
    print(f"門檻：cosine >= {args.threshold}，recurring >= {args.min_tickets} 筆")
    print(f"工單筆數：{len(texts_by_id)}")
    print("-" * 68)

    def embed(text: str) -> list[float]:
        return writer.embed(text, operation_id="demo:verify-clusters", node="cluster")

    report = cluster_tickets(
        texts_by_id,
        embed,
        threshold=args.threshold,
        min_tickets=args.min_tickets,
    )

    for index, members in enumerate(report.groups, start=1):
        size = len(members)
        mark = "達 recurring 門檻" if size >= args.min_tickets else "未達 recurring 門檻"
        print(f"群 {index}：{size} 筆（{mark}）")
        for ticket_id in members:
            print(f"    {ticket_id}  [{expected_group[ticket_id]}]  {texts_by_id[ticket_id]}")
        print()

    print("-" * 68)
    print(f"群數：{len(report.groups)}")
    print(f"各群筆數：{report.sizes}")
    print(f"最大群筆數：{report.largest}")
    print(f"達 recurring 門檻（>= {args.min_tickets} 筆）的群數：{report.recurring_groups}")
    print(f"實際 Bedrock 呼叫次數：{trace.count()}")
    print()

    if report.recurring_groups == 0:
        print(
            "結果：沒有任何一群達到 recurring 門檻。"
            "請調整 tickets.json 讓同一功能的問法更接近，再重跑一次。"
        )
        return 1

    print(
        "結果：至少有一群達到 recurring 門檻。"
        "請把上面的輸出貼進核定紀錄，再執行 approve_batch()。"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：`uv run pytest tests/unit/test_verify_clusters.py -v`

預期：PASS，5 passed。

接著**手動執行一次真實的分群驗證**（會實際呼叫 Bedrock）：

```bash
uv run python demo/verify_clusters.py
```

預期輸出長這樣（實際的群數與筆數以當次輸出為準）：

```text
合成資料示範：以下為種子工單的實際 embedding 分群結果。
執行時間：2026-09-13T12:34:56Z
模型：amazon.titan-embed-text-v2:0，維度：1024
門檻：cosine >= 0.85，recurring >= 5 筆
工單筆數：20
--------------------------------------------------------------------
群 1：12 筆（達 recurring 門檻）
    t_0801  [A-prepare]  會前摘要在哪裡開啟？
    ...
群 2：5 筆（達 recurring 門檻）
    t_0813  [B-share]  開完會之後要怎麼把摘要分享給同事？
    ...
群 3：3 筆（未達 recurring 門檻）
    t_0818  [C-notify]  要怎麼調整通知的提醒時間？
    ...
--------------------------------------------------------------------
群數：3
各群筆數：[12, 5, 3]
最大群筆數：12
達 recurring 門檻（>= 5 筆）的群數：2
實際 Bedrock 呼叫次數：20
結果：至少有一群達到 recurring 門檻。請把上面的輸出貼進核定紀錄，再執行 approve_batch()。
```

**把這段輸出保存下來**（貼進你的核定紀錄或 PR 說明），它就是「已驗證分群」的證據。若實際結果和 `expected_group` 對不上（例如 A 和 B 合併成一群），就調整 `tickets.json` 的文字讓兩組語意差更開，再重跑。

- [ ] **步驟 5：commit**

```bash
git add demo/verify_clusters.py tests/unit/test_verify_clusters.py
git commit -m "feat(demo): 新增實際 embedding 分群驗證腳本"
```

---

## 7. 完成檢查清單

對應設計文件第 16 節切片 S6–S8 的手動檢查。

- [ ] `uv run pytest -q` 全部通過，`uv run ruff check .` 沒有錯誤。
- [ ] 種子檔數量正確：
  ```bash
  ls demo/seed/*.json demo/seed/tutorials/*.json | wc -l
  ```
  預期：`12`（8 個頂層檔 + 4 個版本檔）。
- [ ] 每個種子檔的 `note` 都含「合成資料示範」：
  ```bash
  grep -L '合成資料示範' demo/seed/*.json demo/seed/tutorials/*.json
  ```
  預期：沒有輸出（沒有任何檔案缺少標示）。
- [ ] 資料筆數正確：20 筆工單、9 筆重開票工單、18 筆回饋、20 筆瀏覽、3 個 Feature、4 個版本、1 筆 Release、2 條規則、3 個批次。
  ```bash
  uv run python -c "
  from demo.seed_loader import SEED_DIR, read_items
  for name, expect in [('tickets',20),('reopen_tickets',9),('feedback',18),('views',20),('features',3),('releases',1),('rules',2),('batches',3)]:
      got = len(read_items(SEED_DIR / f'{name}.json'))
      print(f'{name}: {got} (預期 {expect})', 'OK' if got == expect else 'MISMATCH')
  "
  ```
  預期：八行全部 `OK`。
- [ ] 重算目標值全中：`uv run pytest tests/integration/test_seed_verify_recipe.py -v` 全 PASS，特別是 `test_載入完整種子後重算出全部目標值`。
- [ ] 批次與獨立種子檔一致：`test_R007_批次與獨立種子檔完全一致` PASS。
- [ ] 已**手動**執行 `uv run python demo/verify_clusters.py`，輸出已保存，且「達 recurring 門檻的群數」至少為 1。
- [ ] 所有批次一開始都是 `"approved": false`；只有在上面三項都確認過之後，才用 `approve_batch()` 改成 `true`。
  ```bash
  uv run python -c "
  from demo.seed_loader import SEED_DIR, load_batches
  for b in load_batches(SEED_DIR / 'batches.json'):
      print(b.batch_id, b.approved)
  "
  ```
- [ ] 批次寫進 S3 之後只在 `operations/rule-batches/` 底下，不在 `site/` 底下（`test_批次不會被寫進公開的_site_前綴`）。
- [ ] 用 Phase 20 的 `validate_rule()` 實際跑一次（種子已核定並上傳後）：
  ```bash
  uv run python -c "
  import json
  from training_kb.clock import now_utc
  from training_kb.config import load_settings
  from training_kb.repository import build_repository
  from training_kb.writing.client import CallTrace, build_writer
  from training_kb.analytics import validate_rule
  s = load_settings(); t = CallTrace(); repo = build_repository(s); w = build_writer(s, t)
  print(json.dumps(validate_rule(repo, w, 'R-007', ['b_r007_01'], now=now_utc()).to_dict(), ensure_ascii=False, indent=2))
  print(json.dumps(validate_rule(repo, w, 'R-012', ['b_r012_01','b_r012_02'], now=now_utc()).to_dict(), ensure_ascii=False, indent=2))
  "
  ```
  預期：R-007 的 `after_status` 是 `active`，R-012 的 `after_status` 是 `retired`。
- [ ] A 的第 1、2、4 步在 v1 與 v2 逐字相同（`test_A_v2_只改第三步其餘逐字相同`）。
- [ ] B、C 的步驟完全沒有引用 `Prepare`（`test_B_與_C_不引用_Prepare`）。

---

## 8. 常見錯誤與排除

**症狀 1：`verify_recipe()` 算出 `A_v1_rate` 是 `None`。**
原因：`reopen_stats()` 找不到窗口內的瀏覽者，分母是 0。多半是 `prepare-meeting@v1` 的 `published_at` 沒寫進去——`load_tutorials()` 只在版本檔有 `published_at` 時才寫。
解法：`uv run python -c "..."` 讀回版本確認：
```bash
uv run python -c "
from training_kb.config import load_settings
from training_kb.repository import build_repository
repo = build_repository(load_settings())
print(repo.get_version('prepare-meeting@v1').published_at)
"
```
應該印出 `2026-08-01T00:00:00Z`。若是 `None`，檢查 `prepare-meeting.v1.json` 的 `published_at` 欄位。

**症狀 2：`verify_recipe()` 算出 `A_v1_reopen` 是 `0`。**
原因：重開票工單的 `cluster_id` 與 `Tutorial.cluster_id` 對不上，或工單時間早於瀏覽時間。
解法：確認 `reopen_tickets.json` 每筆 `cluster_id` 都是 `c12`，且 `prepare-meeting.v1.json` 的 `tutorial.cluster_id` 也是 `c12`。再確認工單 `ts`（08-03T10:00）晚於瀏覽 `ts`（08-02T09:00）——設計文件 F41 要求分子只計「瀏覽之後」的開票。

**症狀 3：`load_tutorials()` 拋出 `ContentError: 步驟引用的 Feature 不存在`。**
原因：`load_features()` 沒有先跑，或版本檔的 `feature_id` 打錯字（例如寫成 `Share summary` 小寫 s）。
解法：先跑 `load_features()`，再跑 `load_tutorials()`；`load_all()` 已經照正確順序排好。`feature_id` 必須完全等於 `features.json` 裡的值，大小寫與空格都要一樣。

**症狀 4：`test_A_v2_只改第三步其餘逐字相同` 失敗。**
原因：複製 v1 的內容到 v2 時，某個步驟的標點或空白改掉了（例如「。」變成「.」）。
解法：用文字比對工具找出差異：
```bash
uv run python -c "
import json, pathlib
d = pathlib.Path('demo/seed/tutorials')
v1 = json.loads((d/'prepare-meeting.v1.json').read_text(encoding='utf-8'))['content']['steps']
v2 = json.loads((d/'prepare-meeting.v2.json').read_text(encoding='utf-8'))['content']['steps']
for i, (a, b) in enumerate(zip(v1, v2), start=1):
    if a != b:
        print(f'第 {i} 步不同'); print('  v1:', a); print('  v2:', b)
"
```
只有第 3 步應該出現在輸出裡。

**症狀 5：`verify_clusters.py` 印出「沒有任何一群達到 recurring 門檻」。**
原因：20 筆工單的文字彼此太不像，或門檻設太高。
解法：先用 `--threshold 0.8` 再跑一次看分群長什麼樣。如果放寬門檻就分得出來，代表工單文字的語意差異偏大——把同一組的問法改得更接近（例如都提到「會前摘要」這個詞）。**不要為了湊結果直接把 `threshold` 改小寫進程式**；設計文件 §7.3 固定 0.85。

**症狀 6：`verify_clusters.py` 拋出 `PermanentError: 缺少必填環境變數`。**
原因：`.env` 沒設好，`load_settings()` 找不到 `TKB_AWS_REGION`、`TKB_EMBED_MODEL_ID` 等。
解法：回到 Phase 04（`04-Phase04-AWS基礎建設與模型可用性確認.md`）把 `.env` 補齊，再確認 `.env` 已被 `.gitignore` 忽略：
```bash
git check-ignore -v .env
```
預期：印出 `.gitignore:<行號>:.env	.env`。

**症狀 7：`test_重複載入瀏覽不會變成四十筆` 失敗。**
原因：`view_pk()` 的實作沒有依 `[tutorial_version, user, ts]` 做穩定編碼，或 `put_meta` 用了會產生新 ID 的路徑。
解法：檢查 Phase 02 的 `keys.view_pk()`——它必須是 `"VIEW#" + sha256(json.dumps([tutorial_version, user, ts], ensure_ascii=False, separators=(",", ":")))[:32]`。相同三元組必須得到相同 PK（設計文件 §9.1）。

**症狀 8：`approve_batch()` 之後 `batches.json` 的中文變成 `中文`。**
原因：寫檔時忘了 `ensure_ascii=False`。
解法：照 Task 7 的寫法，`json.dumps(raw, ensure_ascii=False, indent=2)`。

---

## 9. 這階段不做的事

| 不做的事 | 留給哪一階段 |
|---|---|
| 用種子跑完整的 Ticket Analysis／Release Update／Feedback Review | Phase 23（`23-Phase23-Demo控制台與Dashboard.md`）的觸發按鈕。本階段只準備資料。 |
| 建立教學站的 HTML 頁面樣式、回饋 widget | Phase 22（`22-Phase22-S3靜態教學站.md`）。本階段只呼叫 `publish_to_site()`。 |
| B 教學的「規則關閉／開啟」兩份隔離預覽 | Phase 23。設計文件 F47：兩份都只是隔離的 Demo 產物，寫在 `demo/previews/`，不寫入正式教學、回饋或統計。種子的 5 筆 B 工單就是給那個對照用的同一批 Ticket。 |
| 把 `rule-lab-demo` 的四個版本寫進 DynamoDB | 不做。它們只存在於批次檔內，避免污染正式教學與統計（本計劃選擇）。 |
| 修改規則的 `status` 或 `validated_at` | Phase 20 的 `apply_rule_status()`。種子只提供初始狀態。 |
| 執行 PR #42 的改名流程、產生 A v3 | Phase 16（Release Note Update）與 Phase 23 的觸發。種子只提供 `r_42` 這筆事件。 |
| 把模擬 `published_at` 當成真實發布時間展示 | 不做。設計文件 §11.5：模擬歷史資料使用明示的模擬時間，不得與即時運作合併成真實使用者成效。 |
| 保證 `verify_clusters.py` 一定分出三群 | 不做。腳本只負責印出實際結果；本文件不宣稱已跑過或一定成功。 |
| 準備 Bedrock 呼叫次數的歷史 trace | Phase 23。設計文件 §11.1：預先準備的 trace 需明示為歷史展示。 |

---

## 10. 對照：設計章節與 Rule 編號

| Rule 來源檔 | Rule 編號與原文 | 本階段哪個 Task 落實 |
|---|---|---|
| `執行教學流程.feature` | Rule 1：缺少原始 Example 時可用明示合成且經確認的驗收資料 | 全部 Task（每個種子檔的 `note` 都標示「合成資料示範」）、Task 7（人工核定流程） |
| `檢視學習指標.feature` | Rule 10：Demo 指標以 seeded data 展示 | Task 8（`verify_recipe` 由完整 seeded 資料實時計算） |
| `檢視學習指標.feature` | Rule 1：平均評分以每個 TutorialVersion 的 rating 計算 | Task 5（18 筆回饋）、Task 8（重算 2.875／4.4） |
| `檢視學習指標.feature` | Rule 2：負面 Feedback 數計入 rating 不超過 2 或 category 屬負面的回饋 | Task 5（v1 八筆全部核定類別）、Task 8（重算 8／2） |
| `檢視學習指標.feature` | Rule 3：同題重開票率計算看過教學的使用者在版本發布後 14 天內同 cluster 再開票的比例 | Task 4（9 筆重開票工單，時間與 cluster 都對得上）、Task 8（重算 0.7／0.2） |
| `檢視學習指標.feature` | Rule 4：同題重開票率的分母取自教學瀏覽事件 | Task 5（20 筆瀏覽，每版每人一筆） |
| `檢視學習指標.feature` | Rule 5：看過教學又開票的同一人比對穩定使用者 ID | Task 4、Task 5（`u_01`…`u_10` 貫穿工單 `author`、回饋 `user`、瀏覽 `user`） |
| `檢視學習指標.feature` | Rule 11：Demo 對同題重開票率標明 proxy 與精確定義 | Task 4、Task 8（文件與 `note` 都寫明 7／2 是筆數、0.7／0.2 是率） |
| `分析工單.feature` | Rule 1：每則 Ticket 在接入分析時計算一次並儲存 1024 維 embedding | Task 2（種子工單 `embedding` 留空）、Task 9（實際呼叫 Titan 驗證） |
| `分析工單.feature` | Rule 2：demo 分群以 cosine 至少 0.85 為同群門檻 | Task 9（`cluster_tickets` 預設 `threshold=0.85`） |
| `分析工單.feature` | Rule 3：同群在 14 天內至少有 5 筆 Ticket 才算 recurring | Task 2（相對日期落在當日及前 13 日）、Task 9（`min_tickets=5`） |
| `分析工單.feature` | Rule 13：新教學的每個步驟恰好引用一個 Feature | Task 3（`test_每個步驟恰好引用一個既有_feature`） |
| `分析工單.feature` | Rule 14：新教學第一版的 reason 使用 gap 加上來源 cluster_id | Task 3（A v1 的 `reason` 是 `gap:c12`） |
| `建立教學版本.feature` | Rule 5：每個版本的完整內容儲存在 tutorials/&lt;slug&gt;/v&lt;n&gt;.md | Task 3（`load_tutorials` 重用 `create_version`） |
| `建立教學版本.feature` | Rule 7：與前版的 diff 儲存在 tutorials/&lt;slug&gt;/v&lt;n&gt;.diff | Task 3（`test_v1_的_diff_是空的`） |
| `建立教學版本.feature` | Rule 8：建立 TutorialStep 時保存 references Feature 邊 | Task 3（`verify_version_complete` 核對） |
| `發布教學版本.feature` | Rule 4：Tutorial 的 current_version 指向目前教學版本 | Task 3（A 的 `current_version` 是 `prepare-meeting@v2`） |
| `發布教學版本.feature` | Rule 5：已上架的版本具有 published_at | Task 3（寫入模擬 `published_at`） |
| `收集教學回饋.feature` | Rule 3：Feedback 的 rating 只能為 1 到 5 的整數 | Task 5（載入時走 `validate_feedback`） |
| `收集教學回饋.feature` | Rule 9：Feedback 接入時必須提供穩定使用者 ID | Task 5（每筆都有 `user`） |
| `收集教學回饋.feature` | Rule 10：同一使用者對同一版本的每次新提交都計一筆 | Task 5（`u_01` 在 v1 與 v2 各一筆，都算數） |
| `提出教學規則.feature` | Rule 2：Authoring Rule 保留可追溯的 Feedback 證據 | Task 6（R-007 的 evidence 是 A v1 八筆真實存在的 ID） |
| `提出教學規則.feature` | Rule 3：Authoring Rule 記錄 applies_when 適用範圍 | Task 6（只用 `step.type` 單一條件） |
| `提出教學規則.feature` | Rule 4：Authoring Rule 記錄 derived_from 來源版本 | Task 6（恰好一個版本） |
| `提出教學規則.feature` | Rule 6：MVP 的教學與產品功能識別碼在單一專案範圍內唯一 | Task 1、Task 3（`project_id` 固定 `demo-project`；slug 與 feature_id 不重複） |
| `套用教學規則.feature` | Rule 7：版本的 rules_applied 記錄本次套用的規則 | Task 3（A v2 的 `rules_applied` 是 `["R-007"]`） |
| `驗證教學規則.feature` | Rule 3：未載入完整核定種子驗證批次時不改變規則狀態 | Task 7（批次預設 `approved: false`，核定流程） |
| `驗證教學規則.feature` | Rule 6：驗證無效的規則從可使用規則中退役 | Task 7（R-012 的兩個不重疊批次都未改善） |
| `查詢知識圖譜.feature` | Rule 6：Feedback Review 以 refers_to 關係反查指定版本的回饋 | Task 5（載入時寫 `REFERS_TO` 邊） |

---

## 11. 參考來源

### 設計文件章節（`docs/design/training-kb.md`）

- §7.1 接入路徑：Ticket／Release／Feedback／View 的必填欄位與合法值。
- §7.3 Ticket Analysis：cosine 0.85 群中心分群、recurring 窗口、`gap:<cluster_id>` 的 reason 格式。
- §8.2 create_version 的完成條件：v1 仍有空的 `v1.diff`；`rules_applied` 是套用關係的權威。
- §9.1 鍵與原生型別：View 的 PK 是 `[tutorial_version, user, ts]` 的 SHA-256 摘要。
- §9.3 S3 與執行資訊：`tutorials/`、`site/`、`demo/previews/`、`operations/` 各自的地位。
- §11.1 共用一份產品資料清單：Feature 清單、20 筆工單、A v1／v2 全文、`r_42`、規則試用、執行紀錄的配方與檢查；「不能只把所有 cluster_id 寫成 c12 就聲稱已測過分群」。
- §11.2 可重算的評分與負面回饋：18 筆回饋的完整表格與 2.875／4.4／8／2。
- §11.3 可重算的瀏覽、重開票筆數與比例：20 筆瀏覽、9 筆重開票工單與 7／2／70%／20%。
- §11.4 讓規則轉移的順序正確：R-007 從 candidate 到 active 的順序；R-012 需要兩個完整不重疊批次。
- §11.5 Demo 的資料與即時執行分開標示：固定標示「合成資料示範」與資料批次。
- §12.1 指標公式與 §12.3 指標不能替代的證據。
- §12.2 規則驗證：只在完整核定種子批次中改狀態。
- §15 測試與驗收設計「Analytics」列：2.9／4.4 與 7／2 可由配方重算。
- §16 交付切片 S6、S7、S8。
- §18 待確認事項 O4（時間與比較邊界）、O7（核定種子與外部設定）。
- §19.1 資料決策 D01、D02、D06、D10、D11、D13、D14、D16、D17、D18、D23、D24、D25、D28、D29。
- §19.2 功能決策 F01、F11、F27、F30、F32、F33、F41、F43、F44、F46、F47、F50。

### 規格檔

- `docs/spec/features/檢視學習指標.feature`（12 條 Rule，含 Demo seeded 指標的 Example）
- `docs/spec/features/驗證教學規則.feature`（R-012 退役的 Example）
- `docs/spec/features/分析工單.feature`（cosine 0.85、recurring 5 筆 14 天）
- `docs/spec/features/收集教學回饋.feature`（rating 1..5、穩定 user ID、每次新提交計一筆）
- `docs/spec/features/建立教學版本.feature`（S3 路徑、diff、references 邊）
- `docs/spec/features/發布教學版本.feature`（`published_at`、`current_version`）
- `docs/spec/features/提出教學規則.feature`（evidence、applies_when、derived_from）
- `docs/spec/erm.dbml`（十個實體的欄位與 note）

### 外部官方文件

- Amazon Titan Text Embeddings V2 請求／回應格式：<https://docs.aws.amazon.com/bedrock/latest/userguide/model-parameters-titan-embed-text.html>
  經本次查證：V2 request body 為 `{"inputText": string, "dimensions": int, "normalize": boolean, "embeddingTypes": list}`（只有 `inputText` 必填，`dimensions` 可填 1024／512／256，預設 1024）；response 為 `{"embedding": [float, ...], "inputTextTokenCount": int, "embeddingsByType": {...}}`。
- Amazon Titan Text Embeddings 模型說明（`amazon.titan-embed-text-v2:0`、8192 tokens、1024 維、不支援 `maxTokenCount`／`topP`）：<https://docs.aws.amazon.com/bedrock/latest/userguide/titan-embedding-models.html>
- Bedrock `InvokeModel` API：<https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_InvokeModel.html>
- DynamoDB 分頁（載入後的查詢必須讀完所有分頁）：<https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/Query.Pagination.html>
- S3 條件寫入（避免同 key 被覆蓋）：<https://docs.aws.amazon.com/AmazonS3/latest/userguide/conditional-writes.html>
