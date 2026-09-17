# Phase 08：Content-發布與退役

| 項目 | 內容 |
|---|---|
| 上一階段 | Phase 07：Content-建立教學版本（`07-Phase07-Content-建立教學版本.md`） |
| 下一階段 | Phase 09：圖譜查詢與 backfill（`09-Phase09-圖譜查詢與backfill.md`） |
| 對應設計文件章節 | §8.3、§8.4、§9.3、§13、O2、O3（`docs/design/training-kb.md`） |
| 對應交付切片 | S3（設計文件第 16 節） |
| 預估時間 | 約 6 小時 |
| 做完會得到 | `publish` 能把一批版本一次上架（全有或全無）、`retire` 能退役教學並檢查後繼、最小版的靜態教學頁會出現在 S3 的 `site/` 前綴底下。 |

---

## 1. 這階段做完會得到什麼

Phase 07 做完之後，版本躺在 S3 的 `tutorials/` 私有區，`published_at` 是空的，讀者看不到。這一階段把它上架：

```text
publish(repo, ["prepare-meeting@v1"], renderer, now=...)
   -> 每一篇先驗證完整性
   -> 全部通過才用「一筆 DynamoDB 交易」同時寫 published_at 與 current_version
   -> 成功之後才把 HTML 寫進 site/
   -> 回傳 PublishResult(published=[...], failed=None, reasons=[])
```

同時會有：

| 函式 | 一句話 |
|---|---|
| `content.publish` | 一批版本一次上架；任何一篇不完整，整批都不切換。 |
| `content.retire` | 把教學標記成 `retired`，並檢查維護者選的後繼教學合不合法。 |
| `content.with_tutorial_lock` | 同一篇教學的寫入串行化，取不到鎖就拋 `TransientError`。 |
| `content.parse_markdown` | 把 S3 全文讀回結構化的五段內容，給頁面使用。 |
| `site.SiteRenderer` | 最小版的 HTML 產生器：標題、五段、步驟、版本號、「第一版，沒有前一版可比較」、退役提示。 |
| `site.publish_to_site` | 把某一版寫進公開的 `site/` 前綴，回傳寫了哪些 key。 |

做完之後，設計文件第 16 節切片 S3 的手動檢查（「發布後讀到正確全文；中途失敗仍讀舊版；版本與引用齊全」）就有自動化證據了。

---

## 2. 它在整張地圖的位置

```text
基礎層        01 骨架 -> 02 模型與鍵 -> 03 Repository(本機) -> 04 AWS 基礎建設
                                                                    |
AI 與內容層   05 Writing(Bedrock) -> 06 規則注入 -> 07 建立版本 -> 08 發布與退役 -> 09 圖譜查詢
                                                                  ^^^^^^^^^^^^^         |
                                                                  你在這裡              |
接入層        10 Ingress 驗簽 -> 11 Rote 判定 -> 12 Rote Agent -------------------------+
                                                                                       |
流程層        13 Ticket Analysis -> 14 Step Functions 上線 -> 15 Feedback/View 匯入 -> 16 Release Update
                                                                                       |
學習層        17 Review:REFINE -> 18 Review:候選規則+排程 -> 19 Analytics 指標 -> 20 規則驗證
                                                                                       |
展示與驗收層  21 Demo 種子資料 -> 22 靜態教學站 -> 23 Demo 控制台 -> 24 失敗復原驗收 -> 25 安全與當日準備
```

---

## 3. 開始前檢查

- [ ] **1. Phase 07 的東西都在**

執行：

```bash
cd ~/AWS-Hackathon
uv run python -c "
from training_kb.content import (VersionPlan, allocate_version, create_tutorial,
                                 create_version, make_diff, render_markdown,
                                 validate_content, verify_version_complete, version_keys)
print('content ok')
from training_kb.repository import Repository
print('repo ok', all(hasattr(Repository, n) for n in
      ['get_tutorial','put_tutorial','get_version','get_steps','get_feature','list_features']))
"
```

預期輸出：

```text
content ok
repo ok True
```

- [ ] **2. Phase 03 的交易、鎖與操作紀錄都在**

執行：

```bash
uv run python -c "
from training_kb.repository import Repository
need = ['transact_write','acquire_lock','release_lock','update_meta','scan_entity']
print('缺少：', [n for n in need if not hasattr(Repository, n)])
"
```

預期輸出：

```text
缺少： []
```

- [ ] **3. 測試用的 fixture 都在**

執行：

```bash
grep -c "def repo" tests/conftest.py
grep -c "def seed_feature" tests/integration/conftest.py
```

預期輸出：兩個指令各印出 `1`。`repo` 是 Phase 03 在 `tests/conftest.py` 建立的假 AWS
Repository；`seed_feature` 是 Phase 07 Task 4 加在 `tests/integration/conftest.py` 的
資料準備工具。任何一個是 `0`，就回該階段補上。

- [ ] **4. `Repository.transact_write` 接受的動作格式**

本階段會傳一串 boto3 `transact_write_items` 的 `TransactItems` 元素給它。先確認 Phase 03 的實作：

```bash
uv run python -c "
import inspect
from training_kb.repository import Repository
print(inspect.getsource(Repository.transact_write))
print('table_name 屬性：', 'table_name' in inspect.getsource(Repository.__init__))
"
```

預期：印出的程式碼直接呼叫 `self.client.transact_write_items(TransactItems=actions)`，
動作用 DynamoDB **低階格式**（值長成 `{"S": "..."}`），每個動作要**自己帶 `TableName`**，
超過 100 個動作或條件不成立時拋 `PermanentError`；最後一行印出 `True`，表示
`Repository` 有 `self.table_name` 可以填進 `TableName`。若 Phase 03 選了別的格式
（例如自動把 Python 值轉成低階型別），以 Phase 03 的寫法為準，本階段
`_publish_actions` 產生的值就要跟著改（見第 8 節「症狀 3」）。

- [ ] **5. 整包測試會過**

執行：

```bash
uv run pytest -q
```

預期：全部 `passed`。

---

## 4. 名詞小抄

| 名詞 | 白話解釋 | 在本階段哪裡用到 |
|---|---|---|
| publish（發布／上架） | 把某一版變成讀者看得到的版本。做兩件事：填 `published_at`、把教學的 `current_version` 指過去。 | `content.publish` |
| DynamoDB 交易（transaction） | 一次送出多個寫入動作，**全部成功或全部不做**。上限 100 個動作，同一筆資料不能在同一個交易裡出現兩次。 | `publish` 的核心 |
| 條件表示式（ConditionExpression） | 寫入前要成立的條件，不成立就整筆拒絕。例如「`current_version` 現在必須等於 v1」。 | 防止兩個流程同時改同一篇 |
| `attribute_not_exists(x)` | DynamoDB 條件函式：這筆資料沒有 `x` 這個欄位時成立。 | v1 上架時的條件 |
| `attribute_type(x, :t)` | DynamoDB 條件函式：`x` 欄位的型別是 `:t`。型別要用「表示式屬性值」傳進去，例如 `{"S": "NULL"}`。 | 相容舊資料把 `current_version` 存成 NULL 的情況 |
| retire（退役） | 教學不再適用時的狀態。資料只有 `retired` 一個值，`obsolete` 只是畫面上的用詞（D21）。 | `content.retire` |
| successor（後繼教學） | 退役教學可以指向的另一篇教學，值是裸 slug。由維護者選，不是來源事件指定（F54）。 | `retire` |
| 鎖（lock） | 一個「我正在寫這篇」的標記，別人拿不到就得等。存在 DynamoDB 的 `LOCK#<slug>`，有存活時間（TTL）。 | `with_tutorial_lock` |
| TTL（存活時間） | 鎖多久之後自動失效，避免程式當掉後鎖住不放。 | `acquire_lock(..., ttl_seconds=120, ...)` |
| `TransientError` | 可以重試的錯誤（網路、限流、逾時、搶不到鎖）。Step Functions 的 Retry 會抓它。 | 取不到鎖時 |
| `PermanentError` | 不可重試的錯誤（資料非法、條件不符）。Step Functions 的 Catch 會抓它。 | 交易條件不符時 |
| `site/` 前綴 | S3 上唯一公開的資料夾。其他前綴（`tutorials/`、`operations/`、`stepfunctions/`、`demo/previews/`）全部私有。 | 公開界線 |
| `html.escape` | Python 標準函式庫的跳脫函式，把 `<`、`>`、`&`、`"` 換成 HTML 實體，讓文字不會變成可執行的標籤。 | 所有使用者與模型文字 |
| 靜態站（static site） | 只有現成 HTML 檔、沒有後端程式的網站。本專案直接用 S3 website endpoint（只有 HTTP，沒有 HTTPS）。 | Phase 22 會完整做 |
| O2、O3 | 設計文件第 18 節「待確認事項」的編號。O2 是操作紀錄與接受順序，O3 是 S3 公開與發布提交。 | 第 5 節 |
| F36、F37、F49 | 設計文件第 19.2 節的功能決策編號。 | 第 5 節、第 10 節 |

---

## 5. 設計說明

### 5.1 公開與私有的界線

這是本階段最重要的一條線。設計文件 §9.3 與 §13 規定：

```text
S3 bucket（training-kb-content）
  |
  +-- tutorials/<slug>/v<n>.md      私有：完整教學全文
  +-- tutorials/<slug>/v<n>.diff    私有：與前版的差異
  +-- operations/<id>.json          私有：執行紀錄、重試用的輸出
  +-- stepfunctions/<p>/v<n>.json   私有：ASL 快照
  +-- demo/previews/                私有：規則開關對照產物
  |
  +-- site/                         公開：只有這裡對外
        index.html                  教學總覽
        <slug>/index.html           某篇教學的版本清單
        <slug>/v<n>.html            某一版的教學頁
        <slug>/v<n>.diff.txt        某一版的差異（公開版）
```

只有「已經發布的版本」可以進 `site/`。設計文件 §18 的 O3 特別警告：不可以用「只是沒有連結」代替「未發布內容不可公開」。所以 `publish_to_site` 第一件事就是檢查 `version.published_at`，是空的就拒絕。

### 5.2 publish 的順序與 O3 的限制

```text
 (1) 逐篇 verify_version_complete           <- 全部通過才往下；任何一篇缺東西就整批停止
      |                                        （F36、F49）
      v
 (2) 逐篇檢查基底
      |   教學存在？status 是 active？
      |   tutorial.current_version == version.supersedes ？
      v
 (3) 一筆 DynamoDB 交易（全有或全無）
      |
      |   Update VERSION#<slug>@v<n>  SET published_at = <now>
      |          條件：attribute_exists(PK)
      |
      |   Update TUTORIAL#<slug>      SET current_version = <version_id>
      |          條件（v1）：attribute_not_exists(current_version)
      |                     OR attribute_type(current_version, "NULL")
      |          條件（v2+）：current_version = <supersedes>
      v
 (4) 成功之後才寫 site/
      |
      v
 (5) 回傳 PublishResult(published=[...], failed=None, reasons=[])
```

三個為什麼：

**為什麼先全部驗證再一起提交？** F49 的答案是 A：「整次執行以失敗結束，不發布新版本」。設計文件 §8.3 明說不能在逐篇處理時「先發布 A，再因 B 失敗而聲稱整次沒有發布」。所以先把整批驗完，再一次提交。

**為什麼 `published_at` 與 `current_version` 要在同一筆交易？** F37 的答案是 A：「publish 成功回傳時切換」。如果分兩次寫，中間失敗就會出現「版本說自己已發布，但教學還指著舊版」或反過來的狀態。DynamoDB 的 transaction 讓這兩個寫入同生共死。

**為什麼條件要檢查 `current_version == supersedes`？** 這是併發保護。F35 要求同一篇教學的變更依接受順序串行；如果在我們驗證完、提交前，另一個流程先把 `current_version` 改掉了，條件就不成立，整筆交易被拒絕，我們不會蓋掉別人的結果。

**O3 沒有解決的部分要誠實講出來。** DynamoDB 的交易**不能**把 S3 的寫入一起包進去（設計文件 §8.3 與 §18 的 O3）。所以第 (3) 步成功、第 (4) 步失敗時，資料庫已經切換，但公開頁面還是舊的。下面三點是**本計劃選擇（對應 O3）**，不是已經定案的規格：

1. `publish` 把「已經發布過的版本」視為可以重跑——如果 `version.published_at` 有值而且 `tutorial.current_version` 已經是這一版，就跳過交易，只重寫 `site/`。這樣重試就能把公開頁面補上。
2. `publish_to_site` 對 `site/` 用**覆寫**（不是條件寫入），因為頁面是可以重新產生的衍生資料。
3. 這個殘留風險由 Phase 24（`24-Phase24-失敗復原與重送驗收.md`）注入失敗做整合驗收。**在那之前，不可以宣稱 publish 的故障驗收已通過**（設計文件 §18，O3）。

### 5.3 退役與後繼檢查

```text
retire(slug, reason=..., successor=?, now=...)
        |
        v
   successor 有值嗎？ --否--> successor = None
        | 是
        v
   successor == slug ？ --是--> successor = None        （不能指向自己）
        | 否
        v
   這篇教學存在嗎？ --否--> successor = None
        | 是
        v
   status 是 active 嗎？ --否--> successor = None        （退役的不能當後繼）
        | 是
        v
   current_version 有值嗎？ --否--> successor = None      （沒發布過的不能當後繼）
        | 是
        v
   沿著後繼鏈往下走，會走回自己嗎？ --是--> successor = None   （不能形成循環）
        | 否
        v
   保留 successor
        |
        v
   一律完成退役：status = retired，寫 retired_at 與 retired_reason
```

關鍵是最後一步：**不管後繼合不合法，退役一定完成**。F19 的答案是 A：「仍完成退役，顯示過期說明與原文，但不產生導向」。設計文件 §8.4 也說「找不到合法後繼時保持空值，不能阻擋退役」。

`retired_at` 與 `retired_reason` 不是 ERM 欄位，是**本計劃選擇**新增的執行資訊，因為設計文件 §8.4 要求畫面「顯示過期原因與原文」，沒有存下來就顯示不了。

退役之後公開頁面要重新產生（加上退役提示）。`retire` 的簽名沒有 renderer 參數，所以這件事由呼叫端做：Phase 16 的 RETIRE task 會在 `retire` 之後呼叫 `publish_to_site`。本階段提供函式並測試這條路徑。

### 5.4 模組結構與匯入方向

```text
src/training_kb/
  content.py    版本分配、驗證、全文、diff、create_version   (Phase 07)
                publish、retire、with_tutorial_lock、parse_markdown  (Phase 08)
  site.py       SiteRenderer、site_keys、publish_to_site     (Phase 08 最小版)
  repository.py DynamoDB 與 S3 的存取                        (Phase 03、07)

匯入方向：
  site.py  --import-->  content.py      （site 需要 parse_markdown、version_keys）
  content.py  - - - ->  site.py          （publish 內部延後匯入 publish_to_site）

  兩個模組互相需要，所以 content.publish 用「函式內匯入」打斷循環，
  型別註記則用 TYPE_CHECKING。這也是介面契約把 renderer 的型別寫成
  字串 "SiteRenderer" 的原因。
```

Phase 22（`22-Phase22-S3靜態教學站.md`）會把 `SiteRenderer` 擴充成版本選擇、diff 檢視、回饋 widget、瀏覽紀錄匯出與後繼連結，但**三個 render 方法的名稱與參數不會變**。所以這裡要把參數收齊（`versions`、`diff_text`、`retired`、`successor`），即使最小版只用得到一部分。

---

## 6. 工作項目

### Task 1：最小版的 HTML 產生器

**目的**：寫出 `site_keys` 與 `SiteRenderer` 三個 render 方法。所有文字都要跳脫，v1 要顯示「第一版，沒有前一版可比較」，退役的要顯示提示。

**檔案**：
- 新增：`src/training_kb/site.py`
- 測試：`tests/unit/test_site_render.py`

**介面**：
- 消費：`training_kb.models.Tutorial`、`TutorialVersion`、`TutorialStep`、`TutorialContent`、`TutorialStatus`、`parse_version_id`（Phase 02）
- 產出：`training_kb.site.SITE_PREFIX: str`
- 產出：`training_kb.site.site_keys(slug: str, n: int) -> dict[str, str]`
- 產出：`training_kb.site.SiteRenderer.render_version_page(tutorial, version, steps, content, *, versions, diff_text, retired, successor) -> str`
- 產出：`training_kb.site.SiteRenderer.render_tutorial_index(tutorial, versions) -> str`
- 產出：`training_kb.site.SiteRenderer.render_site_index(tutorials) -> str`

- [ ] **步驟 1：寫測試**

建立 `tests/unit/test_site_render.py`：

```python
"""Phase 08：最小版靜態頁的純邏輯測試。"""

from training_kb.models import (
    StepDraft,
    StepType,
    Tutorial,
    TutorialContent,
    TutorialStatus,
    TutorialStep,
    TutorialVersion,
)
from training_kb.site import SiteRenderer, site_keys


def make_tutorial(**overrides) -> Tutorial:
    data = {
        "slug": "prepare-meeting",
        "current_version": "prepare-meeting@v1",
        "topic": "準備會議",
        "feature_ids": ["Prepare"],
        "status": TutorialStatus.active,
        "successor": None,
        "cluster_id": "c12",
    }
    data.update(overrides)
    return Tutorial(**data)


def make_version(n: int = 1, supersedes: str | None = None) -> TutorialVersion:
    return TutorialVersion(
        version_id=f"prepare-meeting@v{n}",
        supersedes=supersedes,
        reason="gap:c12",
        rules_applied=[],
        s3_key=f"tutorials/prepare-meeting/v{n}.md",
        published_at="2026-08-01T00:00:00Z",
    )


def make_steps(text: str = "開啟會議頁面") -> list[TutorialStep]:
    return [
        TutorialStep(
            tutorial_version="prepare-meeting@v1",
            index=1,
            type=StepType.click_ui,
            text=text,
            feature_id="Prepare",
        )
    ]


def make_content(title: str = "準備會議") -> TutorialContent:
    return TutorialContent(
        title=title,
        problem="使用者找不到會前摘要",
        prerequisites=["已登入"],
        steps=[
            StepDraft(type=StepType.click_ui, text="開啟會議頁面", feature_id="Prepare")
        ],
        expected_outcome="看到會前摘要",
    )


def render_page(**overrides) -> str:
    options = {
        "tutorial": make_tutorial(),
        "version": make_version(),
        "steps": make_steps(),
        "content": make_content(),
        "versions": [make_version()],
        "diff_text": "",
        "retired": False,
        "successor": None,
    }
    options.update(overrides)
    return SiteRenderer().render_version_page(
        options["tutorial"],
        options["version"],
        options["steps"],
        options["content"],
        versions=options["versions"],
        diff_text=options["diff_text"],
        retired=options["retired"],
        successor=options["successor"],
    )


def test_公開站的四個_key():
    assert site_keys("prepare-meeting", 2) == {
        "page": "site/prepare-meeting/v2.html",
        "diff": "site/prepare-meeting/v2.diff.txt",
        "index": "site/prepare-meeting/index.html",
        "root": "site/index.html",
    }


def test_版本頁包含標題_五段與版本號():
    page = render_page()

    assert "<h1>準備會議</h1>" in page
    assert "<h2>Problem</h2>" in page
    assert "<h2>Prerequisites</h2>" in page
    assert "<h2>Steps</h2>" in page
    assert "<h2>Expected Outcome</h2>" in page
    assert "版本：v1（prepare-meeting@v1）" in page
    assert "使用者找不到會前摘要" in page
    assert "<li>已登入</li>" in page
    assert "看到會前摘要" in page


def test_版本頁列出步驟文字與型態():
    page = render_page()

    assert "開啟會議頁面" in page
    assert "click_ui" in page
    assert "Prepare" in page


def test_第一版顯示沒有前一版可比較():
    page = render_page(version=make_version(1, supersedes=None))

    assert "第一版，沒有前一版可比較。" in page
    assert "v1.diff.txt" not in page


def test_第二版顯示差異():
    page = render_page(
        version=make_version(2, supersedes="prepare-meeting@v1"),
        diff_text="--- a\n+++ b\n-舊的\n+新的\n",
    )

    assert "第一版，沒有前一版可比較。" not in page
    assert 'href="v2.diff.txt"' in page
    assert "+新的" in page


def test_退役的教學顯示提示與後繼連結():
    page = render_page(
        tutorial=make_tutorial(status=TutorialStatus.retired, successor="share-summary"),
        retired=True,
        successor="share-summary",
    )

    assert "這篇教學已退役" in page
    assert 'href="../share-summary/index.html"' in page


def test_退役但沒有後繼時不產生導向():
    page = render_page(
        tutorial=make_tutorial(status=TutorialStatus.retired),
        retired=True,
        successor=None,
    )

    assert "這篇教學已退役" in page
    assert "目前沒有指定後繼教學。" in page
    assert "index.html" not in page


def test_所有文字都經過_html_跳脫():
    page = render_page(
        content=make_content(title="<script>alert(1)</script>"),
        steps=make_steps(text='點 <img src=x onerror="alert(2)"> 按鈕'),
    )

    assert "<script>" not in page
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page
    assert "<img" not in page
    assert "&lt;img src=x onerror=&quot;alert(2)&quot;&gt;" in page


def test_教學索引頁列出版本並標出目前版本():
    index = SiteRenderer().render_tutorial_index(
        make_tutorial(current_version="prepare-meeting@v2"),
        [make_version(1), make_version(2, supersedes="prepare-meeting@v1")],
    )

    assert "<h1>準備會議</h1>" in index
    assert '<li><a href="v1.html">v1</a></li>' in index
    assert '<li><a href="v2.html">v2</a>（目前版本）</li>' in index


def test_總覽頁列出每篇教學並標示退役():
    root = SiteRenderer().render_site_index(
        [
            make_tutorial(),
            make_tutorial(
                slug="share-summary", topic="分享摘要", status=TutorialStatus.retired
            ),
        ]
    )

    assert '<a href="prepare-meeting/index.html">準備會議</a>' in root
    assert '<a href="share-summary/index.html">分享摘要</a>（已退役）' in root
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：

```bash
uv run pytest tests/unit/test_site_render.py -v
```

預期：FAIL，`ModuleNotFoundError: No module named 'training_kb.site'`。

- [ ] **步驟 3：寫最少的程式讓測試通過**

建立 `src/training_kb/site.py`：

```python
"""S3 靜態教學站的 HTML 產生器（Phase 08 最小版）。

只有 site/ 前綴是公開的；tutorials/、operations/、stepfunctions/、demo/previews/
都是私有（設計文件 §9.3、§13）。所有使用者與模型產生的文字一律用 html.escape
跳脫，避免回饋或模型文字變成頁面上的 script（設計文件 §17.2）。

Phase 22 會把這裡擴充成版本選擇、diff 檢視、回饋 widget 與瀏覽紀錄匯出，
但三個 render 方法的名稱與參數不會變。
"""

from __future__ import annotations

import html

from training_kb.models import (
    Tutorial,
    TutorialContent,
    TutorialStatus,
    TutorialStep,
    TutorialVersion,
    parse_version_id,
)

# S3 上唯一公開的前綴。
SITE_PREFIX = "site/"


def site_keys(slug: str, n: int) -> dict[str, str]:
    """這一版在公開站上的四個 key。"""
    return {
        "page": f"{SITE_PREFIX}{slug}/v{n}.html",
        "diff": f"{SITE_PREFIX}{slug}/v{n}.diff.txt",
        "index": f"{SITE_PREFIX}{slug}/index.html",
        "root": f"{SITE_PREFIX}index.html",
    }


def _esc(text: str) -> str:
    """跳脫所有不可信文字。quote=True 連雙引號也換掉，才不會逃出屬性值。"""
    return html.escape(str(text), quote=True)


def _page(title: str, body: str) -> str:
    return (
        "<!DOCTYPE html>\n"
        '<html lang="zh-Hant">\n'
        "<head>\n"
        '<meta charset="utf-8">\n'
        f"<title>{_esc(title)}</title>\n"
        "</head>\n"
        "<body>\n"
        f"{body}"
        "</body>\n"
        "</html>\n"
    )


class SiteRenderer:
    """把已發布的版本變成靜態 HTML。這個類別不碰 AWS，只做字串。"""

    def render_version_page(
        self,
        tutorial: Tutorial,
        version: TutorialVersion,
        steps: list[TutorialStep],
        content: TutorialContent,
        *,
        versions: list[TutorialVersion],
        diff_text: str,
        retired: bool,
        successor: str | None,
    ) -> str:
        slug, n = parse_version_id(version.version_id)
        parts: list[str] = [
            f"<h1>{_esc(content.title)}</h1>\n",
            f"<p>版本：v{n}（{_esc(version.version_id)}）</p>\n",
            f"<p>原因：{_esc(version.reason)}</p>\n",
        ]

        if retired:
            parts.append(
                "<p>這篇教學已退役，內容保留供查閱，不再接受新的回饋。</p>\n"
            )
            if successor:
                parts.append(
                    f'<p>後繼教學：<a href="../{_esc(successor)}/index.html">'
                    f"{_esc(successor)}</a></p>\n"
                )
            else:
                parts.append("<p>目前沒有指定後繼教學。</p>\n")

        parts.append("<h2>Problem</h2>\n")
        parts.append(f"<p>{_esc(content.problem)}</p>\n")

        parts.append("<h2>Prerequisites</h2>\n<ul>\n")
        for item in content.prerequisites:
            parts.append(f"<li>{_esc(item)}</li>\n")
        parts.append("</ul>\n")

        parts.append("<h2>Steps</h2>\n<ol>\n")
        for step in steps:
            parts.append(
                f"<li>{_esc(step.text)}"
                f"<span>（{_esc(str(step.type))}／{_esc(step.feature_id)}）</span></li>\n"
            )
        parts.append("</ol>\n")

        parts.append("<h2>Expected Outcome</h2>\n")
        parts.append(f"<p>{_esc(content.expected_outcome)}</p>\n")

        parts.append("<h2>版本紀錄</h2>\n<ul>\n")
        for item in versions:
            item_n = parse_version_id(item.version_id)[1]
            mark = "（目前版本）" if item.version_id == version.version_id else ""
            parts.append(f'<li><a href="v{item_n}.html">v{item_n}</a>{mark}</li>\n')
        parts.append("</ul>\n")

        parts.append("<h2>與前一版的差異</h2>\n")
        if version.supersedes is None:
            # F50：v1 仍然有一個空的 diff 檔，但畫面用版本號判斷沒有前一版。
            parts.append("<p>第一版，沒有前一版可比較。</p>\n")
        else:
            parts.append(f'<p><a href="v{n}.diff.txt">下載差異檔</a></p>\n')
            parts.append(f"<pre>{_esc(diff_text)}</pre>\n")

        return _page(f"{content.title}｜{slug} v{n}", "".join(parts))

    def render_tutorial_index(
        self, tutorial: Tutorial, versions: list[TutorialVersion]
    ) -> str:
        parts: list[str] = [
            f"<h1>{_esc(tutorial.topic)}</h1>\n",
            f"<p>教學代號：{_esc(tutorial.slug)}</p>\n",
        ]
        if tutorial.status == TutorialStatus.retired:
            parts.append("<p>這篇教學已退役，內容保留供查閱。</p>\n")
            if tutorial.successor:
                parts.append(
                    f'<p>後繼教學：<a href="../{_esc(tutorial.successor)}/index.html">'
                    f"{_esc(tutorial.successor)}</a></p>\n"
                )
        parts.append("<h2>版本</h2>\n<ul>\n")
        for item in versions:
            item_n = parse_version_id(item.version_id)[1]
            mark = "（目前版本）" if item.version_id == tutorial.current_version else ""
            parts.append(f'<li><a href="v{item_n}.html">v{item_n}</a>{mark}</li>\n')
        parts.append("</ul>\n")
        return _page(f"{tutorial.topic}｜{tutorial.slug}", "".join(parts))

    def render_site_index(self, tutorials: list[Tutorial]) -> str:
        parts: list[str] = ["<h1>教學總覽</h1>\n<ul>\n"]
        for tutorial in tutorials:
            mark = "（已退役）" if tutorial.status == TutorialStatus.retired else ""
            parts.append(
                f'<li><a href="{_esc(tutorial.slug)}/index.html">'
                f"{_esc(tutorial.topic)}</a>{mark}</li>\n"
            )
        parts.append("</ul>\n")
        return _page("教學總覽", "".join(parts))
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：

```bash
uv run pytest tests/unit/test_site_render.py -v
```

預期：PASS，10 個 `PASSED`。

- [ ] **步驟 5：commit**

```bash
git add src/training_kb/site.py tests/unit/test_site_render.py
git commit -m "feat(site): 最小版靜態教學頁與索引頁"
```

---

### Task 2：把 S3 全文讀回結構化內容

**目的**：寫出 `parse_markdown`，它是 Phase 07 `render_markdown` 的反函式。頁面需要標題、問題、前置條件與預期結果，而這四段只存在 S3 全文裡，DynamoDB 只保留每一步的文字。

**檔案**：
- 修改：`src/training_kb/content.py`
- 測試：`tests/unit/test_content_parse.py`

**介面**：
- 消費：`training_kb.content.render_markdown`（Phase 07）
- 產出：`training_kb.content.parse_markdown(markdown: str) -> TutorialContent`

- [ ] **步驟 1：寫測試**

建立 `tests/unit/test_content_parse.py`：

```python
"""Phase 08：把 S3 全文讀回結構化內容的純邏輯測試。"""

from training_kb.content import parse_markdown, render_markdown
from training_kb.models import StepDraft, StepType, TutorialContent


def make_content(**overrides) -> TutorialContent:
    data = {
        "title": "準備會議",
        "problem": "使用者找不到會前摘要",
        "prerequisites": ["已登入", "已建立會議"],
        "steps": [
            StepDraft(type=StepType.click_ui, text="開啟會議頁面", feature_id="Prepare"),
            StepDraft(type=StepType.read, text="閱讀右側摘要", feature_id="Share Summary"),
        ],
        "expected_outcome": "看到會前摘要",
    }
    data.update(overrides)
    return TutorialContent(**data)


def test_render_之後再_parse_會拿回一模一樣的內容():
    content = make_content()

    assert parse_markdown(render_markdown(content)) == content


def test_只有一個步驟也能來回():
    content = make_content(
        steps=[StepDraft(type=StepType.input, text="輸入標題", feature_id="Prepare")]
    )

    assert parse_markdown(render_markdown(content)) == content


def test_步驟文字含括號仍能正確拆開():
    content = make_content(
        steps=[
            StepDraft(
                type=StepType.click_ui,
                text="按下右上角的「準備」（第二顆按鈕）",
                feature_id="Prepare",
            )
        ]
    )

    parsed = parse_markdown(render_markdown(content))

    assert parsed.steps[0].text == "按下右上角的「準備」（第二顆按鈕）"
    assert parsed.steps[0].feature_id == "Prepare"
    assert parsed.steps[0].type == StepType.click_ui


def test_解析出的四段文字不含前後空行():
    parsed = parse_markdown(render_markdown(make_content()))

    assert parsed.title == "準備會議"
    assert parsed.problem == "使用者找不到會前摘要"
    assert parsed.expected_outcome == "看到會前摘要"
    assert parsed.prerequisites == ["已登入", "已建立會議"]


def test_不是步驟格式的行會被略過():
    markdown = (
        "# 準備會議\n\n## Problem\n\n問題\n\n## Prerequisites\n\n- 已登入\n\n"
        "## Steps\n\n這一行不是步驟\n"
        "1. (type=read, feature=Prepare) 看一下\n\n"
        "## Expected Outcome\n\n結果\n"
    )

    parsed = parse_markdown(markdown)

    assert len(parsed.steps) == 1
    assert parsed.steps[0].text == "看一下"
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：

```bash
uv run pytest tests/unit/test_content_parse.py -v
```

預期：FAIL，`ImportError: cannot import name 'parse_markdown' from 'training_kb.content'`。

- [ ] **步驟 3：寫最少的程式讓測試通過**

在 `src/training_kb/content.py` 的 import 區塊補上：

```python
import re

from training_kb.models import StepDraft
```

在 `render_markdown` 後面加上：

```python
# render_markdown 產生的步驟行格式：「3. (type=click_ui, feature=Prepare) 文字」
_STEP_LINE = re.compile(
    r"^(?P<index>\d+)\. \(type=(?P<type>[a-z_]+), feature=(?P<feature>[^)]*)\) "
    r"(?P<text>.*)$"
)


def parse_markdown(markdown: str) -> TutorialContent:
    """把 render_markdown 產生的全文讀回結構化的五段內容。

    公開頁需要標題、Problem、Prerequisites 與 Expected Outcome，而這四段只存在
    S3 全文裡；DynamoDB 只保留每一步的文字（設計文件 §9.1）。所以要有這個反函式。
    它與 render_markdown 必須永遠互為反函式，測試用來回轉換驗證。
    """
    title = ""
    sections: dict[str, list[str]] = {}
    current: list[str] | None = None
    for line in markdown.splitlines():
        if line.startswith("# "):
            title = line[2:].strip()
            current = None
            continue
        if line.startswith("## "):
            current = []
            sections[line[3:].strip()] = current
            continue
        if current is not None:
            current.append(line)

    def text_of(name: str) -> str:
        return "\n".join(sections.get(name, [])).strip()

    prerequisites = [
        line[2:].strip()
        for line in sections.get("Prerequisites", [])
        if line.startswith("- ")
    ]

    steps: list[StepDraft] = []
    for line in sections.get("Steps", []):
        matched = _STEP_LINE.match(line)
        if matched is None:
            continue
        steps.append(
            StepDraft(
                type=matched.group("type"),
                text=matched.group("text"),
                feature_id=matched.group("feature"),
            )
        )

    return TutorialContent(
        title=title,
        problem=text_of("Problem"),
        prerequisites=prerequisites,
        steps=steps,
        expected_outcome=text_of("Expected Outcome"),
    )
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：

```bash
uv run pytest tests/unit/test_content_parse.py -v
```

預期：PASS，5 個 `PASSED`。

- [ ] **步驟 5：commit**

```bash
git add src/training_kb/content.py tests/unit/test_content_parse.py
git commit -m "feat(content): 把 S3 全文讀回結構化的五段內容"
```

---

### Task 3：把一個已發布的版本寫進公開站

**目的**：寫出 `publish_to_site`。它只接受**已發布**的版本，並寫出四個 `site/` key。

**檔案**：
- 修改：`src/training_kb/site.py`
- 修改：`tests/integration/conftest.py`
- 測試：`tests/integration/test_site_publish.py`

**介面**：
- 消費：`Repository.get_tutorial`、`get_version`、`get_steps`、`get_object`、`put_object`、`scan_entity`
- 消費：`training_kb.content.parse_markdown`（Task 2）、`version_keys`（Phase 07）
- 消費：`training_kb.keys.parse_pk`（Phase 02）
- 產出：`training_kb.site.publish_to_site(repo, renderer, slug: str, version_id: str) -> list[str]`
- 產出（測試用）：pytest fixture `ready_version`

- [ ] **步驟 1：寫測試**

先在 `tests/integration/conftest.py` 的 import 區塊補上：

```python
from datetime import datetime, timezone

from training_kb.content import allocate_version, create_tutorial, create_version
from training_kb.models import StepDraft, StepType, TutorialContent
```

再把下面的 fixture 附加到 `tests/integration/conftest.py` 末端：

```python
SEED_NOW = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


@pytest.fixture()
def ready_version(repo, seed_feature):
    """建立一篇教學與一個「寫齊但尚未發布」的版本，回傳 version_id。"""
    seed_feature("Prepare")

    def _ready(
        slug: str = "prepare-meeting",
        *,
        operation_id: str,
        topic: str = "準備會議",
        cluster_id: str = "c12",
        reason: str = "gap:c12",
        rules_applied: tuple[str, ...] = (),
        step_text: str = "開啟會議頁面",
    ) -> str:
        create_tutorial(
            repo,
            slug=slug,
            topic=topic,
            feature_ids=["Prepare"],
            cluster_id=cluster_id,
            now=SEED_NOW,
        )
        plan = allocate_version(repo, slug, operation_id, reason, list(rules_applied))
        content = TutorialContent(
            title=topic,
            problem="使用者找不到會前摘要",
            prerequisites=["已登入"],
            steps=[
                StepDraft(type=StepType.click_ui, text=step_text, feature_id="Prepare"),
                StepDraft(type=StepType.read, text="閱讀右側摘要", feature_id="Prepare"),
            ],
            expected_outcome="看到會前摘要",
        )
        return create_version(repo, plan, content, now=SEED_NOW).version_id

    return _ready
```

再建立 `tests/integration/test_site_publish.py`：

```python
"""Phase 08：把版本寫進公開站（用 moto 模擬 AWS）。"""

from datetime import datetime, timezone

import pytest

from training_kb.content import retire
from training_kb.errors import ContentError
from training_kb.keys import tutorial_pk, version_pk
from training_kb.site import SiteRenderer, publish_to_site, site_keys

NOW = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


def mark_published(repo, slug: str, version_id: str) -> None:
    """直接把資料改成已發布的樣子（真正的切換是 Task 4 的 publish）。"""
    repo.update_meta(version_pk(version_id), {"published_at": "2026-08-01T00:00:00Z"})
    repo.update_meta(tutorial_pk(slug), {"current_version": version_id})


def test_未發布的版本不可以寫進公開站(repo, ready_version):
    version_id = ready_version(operation_id="op-1")

    with pytest.raises(ContentError) as exc:
        publish_to_site(repo, SiteRenderer(), "prepare-meeting", version_id)

    assert "尚未發布" in str(exc.value)
    assert repo.object_exists(site_keys("prepare-meeting", 1)["page"]) is False


def test_寫出四個公開_key(repo, ready_version):
    version_id = ready_version(operation_id="op-1")
    mark_published(repo, "prepare-meeting", version_id)

    written = publish_to_site(repo, SiteRenderer(), "prepare-meeting", version_id)

    keys = site_keys("prepare-meeting", 1)
    assert written == [keys["page"], keys["diff"], keys["index"], keys["root"]]
    for key in written:
        assert repo.object_exists(key) is True


def test_頁面內容來自_s3_全文與_dynamodb_步驟(repo, ready_version):
    version_id = ready_version(operation_id="op-1")
    mark_published(repo, "prepare-meeting", version_id)

    publish_to_site(repo, SiteRenderer(), "prepare-meeting", version_id)

    page = repo.get_object(site_keys("prepare-meeting", 1)["page"]).decode("utf-8")
    assert "<h1>準備會議</h1>" in page
    assert "使用者找不到會前摘要" in page
    assert "開啟會議頁面" in page
    assert "閱讀右側摘要" in page
    assert "第一版，沒有前一版可比較。" in page


def test_總覽頁只列出已發布的教學(repo, ready_version):
    version_id = ready_version(operation_id="op-1")
    ready_version("share-summary", operation_id="op-2", topic="分享摘要", cluster_id="c13")
    mark_published(repo, "prepare-meeting", version_id)

    publish_to_site(repo, SiteRenderer(), "prepare-meeting", version_id)

    root = repo.get_object("site/index.html").decode("utf-8")
    assert "準備會議" in root
    assert "分享摘要" not in root


def test_退役之後重新產生頁面會出現退役提示(repo, ready_version):
    version_id = ready_version(operation_id="op-1")
    mark_published(repo, "prepare-meeting", version_id)
    publish_to_site(repo, SiteRenderer(), "prepare-meeting", version_id)
    retire(repo, "prepare-meeting", reason="release:r_99", successor=None, now=NOW)

    publish_to_site(repo, SiteRenderer(), "prepare-meeting", version_id)

    page = repo.get_object(site_keys("prepare-meeting", 1)["page"]).decode("utf-8")
    assert "這篇教學已退役" in page
```

最後一個測試會用到 Task 6 的 `retire`；先讓它紅著沒關係，Task 6 做完就會變綠。

- [ ] **步驟 2：跑測試，確認它失敗**

執行：

```bash
uv run pytest tests/integration/test_site_publish.py -v
```

預期：FAIL，`ImportError: cannot import name 'publish_to_site' from 'training_kb.site'`。

- [ ] **步驟 3：寫最少的程式讓測試通過**

在 `src/training_kb/site.py` 的 import 區塊補上：

```python
from training_kb.content import parse_markdown, version_keys
from training_kb.errors import ContentError
from training_kb.keys import parse_pk
from training_kb.repository import Repository
```

在檔案最後面加上：

```python
def _version_chain(repo: Repository, version_id: str) -> list[TutorialVersion]:
    """沿 supersedes 往回走，取得從第一版到這一版的版本鏈。

    Phase 09 會提供 repository.list_versions_of_tutorial；在那之前用版本鏈取得
    索引頁要列的版本，不必 Scan 整張表。
    """
    chain: list[TutorialVersion] = []
    seen: set[str] = set()
    current: str | None = version_id
    while current is not None and current not in seen and len(chain) < 200:
        seen.add(current)
        version = repo.get_version(current)
        if version is None:
            break
        chain.append(version)
        current = version.supersedes
    chain.reverse()
    return chain


def _public_tutorials(repo: Repository) -> list[Tutorial]:
    """總覽頁只列已經有發布版本的教學；沒發布過的不可以出現在公開頁面。"""
    tutorials: list[Tutorial] = []
    for item in repo.scan_entity("TUTORIAL"):
        slug = parse_pk(item["PK"])[1]
        tutorial = repo.get_tutorial(slug)
        if tutorial is not None and tutorial.current_version is not None:
            tutorials.append(tutorial)
    return sorted(tutorials, key=lambda tutorial: tutorial.slug)


def publish_to_site(
    repo: Repository, renderer: SiteRenderer, slug: str, version_id: str
) -> list[str]:
    """把一個已發布的版本寫進公開的 site/ 前綴，回傳寫入的 key 清單。

    只有 content.publish 與 RETIRE 之後的重新產生會呼叫它。未發布的版本一律拒絕
    （設計文件 §8.3 與 O3：不可以用「只是沒有連結」代替「不可公開」）。

    site/ 底下的檔案是可以重新產生的衍生資料，所以用覆寫，不用條件寫入。
    """
    tutorial = repo.get_tutorial(slug)
    if tutorial is None:
        raise ContentError(f"找不到教學：{slug}")
    version = repo.get_version(version_id)
    if version is None:
        raise ContentError(f"找不到版本：{version_id}")
    if version.published_at is None:
        raise ContentError(f"版本 {version_id} 尚未發布，不可寫進公開的 site/")

    n = parse_version_id(version_id)[1]
    raw = repo.get_object(version.s3_key)
    if raw is None:
        raise ContentError(f"找不到全文：{version.s3_key}")
    content = parse_markdown(raw.decode("utf-8"))
    steps = repo.get_steps(version_id)

    diff_raw = repo.get_object(version_keys(slug, n)["diff"])
    diff_text = diff_raw.decode("utf-8") if diff_raw is not None else ""

    published_chain = [
        item for item in _version_chain(repo, version_id) if item.published_at
    ]
    retired = tutorial.status == TutorialStatus.retired

    keys = site_keys(slug, n)
    page = renderer.render_version_page(
        tutorial,
        version,
        steps,
        content,
        versions=published_chain,
        diff_text=diff_text,
        retired=retired,
        successor=tutorial.successor,
    )
    repo.put_object(keys["page"], page, content_type="text/html; charset=utf-8")
    repo.put_object(keys["diff"], diff_text, content_type="text/plain; charset=utf-8")
    repo.put_object(
        keys["index"],
        renderer.render_tutorial_index(tutorial, published_chain),
        content_type="text/html; charset=utf-8",
    )
    repo.put_object(
        keys["root"],
        renderer.render_site_index(_public_tutorials(repo)),
        content_type="text/html; charset=utf-8",
    )
    return [keys["page"], keys["diff"], keys["index"], keys["root"]]
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：

```bash
uv run pytest tests/integration/test_site_publish.py -v
```

預期：前四個 `PASSED`；最後一個 `test_退役之後重新產生頁面會出現退役提示` 仍然
FAIL（`ImportError: cannot import name 'retire'`），因為 `retire` 是 Task 6 才寫。

- [ ] **步驟 5：commit**

```bash
git add src/training_kb/site.py tests/integration/conftest.py tests/integration/test_site_publish.py
git commit -m "feat(site): 把已發布的版本寫進公開的 site 前綴"
```

---

### Task 4：單篇 publish 與 DynamoDB 交易

**目的**：寫出 `publish` 與 `PublishResult`。先驗證、再用一筆交易切換、最後才寫 `site/`。

**檔案**：
- 修改：`src/training_kb/content.py`
- 測試：`tests/integration/test_content_publish.py`

**介面**：
- 消費：`Repository.transact_write(actions: list[dict]) -> None` 與 `Repository.table_name: str`（Phase 03；動作是 boto3 `transact_write_items` 的 `TransactItems` 低階格式，每個動作自己帶 `TableName`，條件不符時拋 `PermanentError`）
- 消費：`training_kb.site.publish_to_site`（Task 3，函式內延後匯入）
- 消費：`training_kb.errors.PermanentError`（Phase 01）
- 產出：`training_kb.content.PublishResult`（dataclass：`published: list[str]`、`failed: str | None = None`、`reasons: list[str] = []`）
- 產出：`training_kb.content.publish(repo, version_ids, renderer, *, now) -> PublishResult`

> `PublishResult` 的 `reasons` 欄位是本階段新增的第三個欄位（介面契約只列了
> `published` 與 `failed`）。加它是為了讓失敗時能把 `verify_version_complete`
> 回報的缺漏原樣交給呼叫端記錄，不必再查一次。

- [ ] **步驟 1：寫測試**

建立 `tests/integration/test_content_publish.py`：

```python
"""Phase 08：publish 的整合測試（用 moto 模擬 AWS）。"""

from datetime import datetime, timezone

from training_kb.content import (
    allocate_version,
    create_version,
    publish,
    version_keys,
)
from training_kb.keys import tutorial_pk
from training_kb.models import StepDraft, StepType, TutorialContent
from training_kb.site import SiteRenderer, site_keys

NOW = datetime(2026, 8, 20, 0, 0, 0, tzinfo=timezone.utc)


def make_content(step_text: str) -> TutorialContent:
    return TutorialContent(
        title="準備會議",
        problem="使用者找不到會前摘要",
        prerequisites=["已登入"],
        steps=[
            StepDraft(type=StepType.click_ui, text=step_text, feature_id="Prepare"),
            StepDraft(type=StepType.read, text="閱讀右側摘要", feature_id="Prepare"),
        ],
        expected_outcome="看到會前摘要",
    )


def test_v1_發布後填入時間並切換目前版本(repo, ready_version):
    version_id = ready_version(operation_id="op-1")

    result = publish(repo, [version_id], SiteRenderer(), now=NOW)

    assert result.published == [version_id]
    assert result.failed is None
    assert repo.get_version(version_id).published_at == "2026-08-20T00:00:00Z"
    assert repo.get_tutorial("prepare-meeting").current_version == version_id
    assert repo.object_exists(site_keys("prepare-meeting", 1)["page"]) is True


def test_v2_發布時檢查基底是_v1(repo, ready_version):
    v1 = ready_version(operation_id="op-1")
    publish(repo, [v1], SiteRenderer(), now=NOW)
    plan = allocate_version(repo, "prepare-meeting", "op-2", "release:r_42", [])
    v2 = create_version(repo, plan, make_content("開啟新的會議頁面"), now=NOW).version_id

    result = publish(repo, [v2], SiteRenderer(), now=NOW)

    assert result.published == [v2]
    assert repo.get_tutorial("prepare-meeting").current_version == v2
    assert repo.get_version(v1).published_at == "2026-08-20T00:00:00Z"
    assert repo.object_exists(site_keys("prepare-meeting", 2)["page"]) is True


def test_驗證失敗時不切換目前版本也不寫公開站(repo, ready_version):
    version_id = ready_version(operation_id="op-1")
    repo.s3.delete_object(
        Bucket=repo.bucket, Key=version_keys("prepare-meeting", 1)["md"]
    )

    result = publish(repo, [version_id], SiteRenderer(), now=NOW)

    assert result.published == []
    assert result.failed == version_id
    assert any("缺少 S3 全文" in reason for reason in result.reasons)
    assert repo.get_tutorial("prepare-meeting").current_version is None
    assert repo.get_version(version_id).published_at is None
    assert repo.object_exists(site_keys("prepare-meeting", 1)["page"]) is False


def test_基底不符時拒絕發布(repo, ready_version):
    v1 = ready_version(operation_id="op-1")
    publish(repo, [v1], SiteRenderer(), now=NOW)
    plan = allocate_version(repo, "prepare-meeting", "op-2", "release:r_42", [])
    v2 = create_version(repo, plan, make_content("開啟新的會議頁面"), now=NOW).version_id
    # 模擬別的流程搶先把 current_version 換掉了。
    repo.update_meta(
        tutorial_pk("prepare-meeting"), {"current_version": "prepare-meeting@v9"}
    )

    result = publish(repo, [v2], SiteRenderer(), now=NOW)

    assert result.published == []
    assert result.failed == v2
    assert any("基底不符" in reason for reason in result.reasons)
    assert repo.get_version(v2).published_at is None


def test_重複發布同一版仍然成功且不重複切換(repo, ready_version):
    version_id = ready_version(operation_id="op-1")
    publish(repo, [version_id], SiteRenderer(), now=NOW)
    later = datetime(2026, 8, 21, 0, 0, 0, tzinfo=timezone.utc)

    result = publish(repo, [version_id], SiteRenderer(), now=later)

    assert result.published == [version_id]
    # 已經發布過，不再進交易，所以時間維持第一次的值。
    assert repo.get_version(version_id).published_at == "2026-08-20T00:00:00Z"


def test_空清單直接回傳空結果(repo):
    result = publish(repo, [], SiteRenderer(), now=NOW)

    assert result.published == []
    assert result.failed is None
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：

```bash
uv run pytest tests/integration/test_content_publish.py -v
```

預期：FAIL，`ImportError: cannot import name 'publish' from 'training_kb.content'`。

- [ ] **步驟 3：寫最少的程式讓測試通過**

在 `src/training_kb/content.py` 的 import 區塊改成含下列各項：

```python
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from training_kb.errors import ContentError, PermanentError
from training_kb.keys import (
    META,
    feature_pk,
    parse_pk,
    rule_pk,
    step_pk,
    tutorial_pk,
    version_pk,
)

if TYPE_CHECKING:  # 只在型別檢查時匯入，避免 content 與 site 互相匯入
    from training_kb.site import SiteRenderer
```

在 `VersionPlan` 後面加上：

```python
@dataclass
class PublishResult:
    """publish 的結果。failed 有值代表整批都沒有切換。"""

    published: list[str]
    failed: str | None = None
    reasons: list[str] = field(default_factory=list)
```

在 `create_version` 後面加上：

```python
def _publish_actions(
    table_name: str,
    version_id: str,
    slug: str,
    version: TutorialVersion,
    now: datetime,
) -> list[dict]:
    """publish 要在同一筆 DynamoDB 交易裡做的兩件事。

    格式是 boto3 transact_write_items 的 TransactItems 元素：值用 DynamoDB 的
    屬性型別描述（{"S": "..."}），而且每個動作要自己帶 TableName
    （Phase 03 的 Repository.transact_write 直接把 actions 送給 boto3，不會補）。
    """
    version_action = {
        "Update": {
            "TableName": table_name,
            "Key": {"PK": {"S": version_pk(version_id)}, "SK": {"S": META}},
            "UpdateExpression": "SET #published = :published_at",
            "ConditionExpression": "attribute_exists(#pk)",
            "ExpressionAttributeNames": {"#published": "published_at", "#pk": "PK"},
            "ExpressionAttributeValues": {":published_at": {"S": to_iso(now)}},
        }
    }

    values: dict = {":new": {"S": version_id}}
    if version.supersedes is None:
        # v1：這篇教學還沒有任何已發布版本。屬性不存在，或舊資料存成 NULL，都算沒有。
        condition = (
            "attribute_not_exists(#current) OR attribute_type(#current, :null_type)"
        )
        values[":null_type"] = {"S": "NULL"}
    else:
        # v2 以後：目前版本必須正好是這一版要取代的那一版，否則有人搶先改過了。
        condition = "#current = :expected"
        values[":expected"] = {"S": version.supersedes}

    tutorial_action = {
        "Update": {
            "TableName": table_name,
            "Key": {"PK": {"S": tutorial_pk(slug)}, "SK": {"S": META}},
            "UpdateExpression": "SET #current = :new",
            "ConditionExpression": condition,
            "ExpressionAttributeNames": {"#current": "current_version"},
            "ExpressionAttributeValues": values,
        }
    }
    return [version_action, tutorial_action]


def publish(
    repo: Repository,
    version_ids: list[str],
    renderer: "SiteRenderer",
    *,
    now: datetime,
) -> PublishResult:
    """把一批版本一次上架。任何一篇不合格，整批都不切換（F49、設計文件 §8.3）。

    順序：全部驗證 -> 一筆 DynamoDB 交易切換 -> 才寫 site/。
    DynamoDB 的交易不能把 S3 的寫入包進去（O3），所以交易成功但 site/ 寫失敗時，
    重跑 publish 會跳過交易、只補寫 site/。
    """
    # 延後匯入：site 模組會反過來使用 content，放在檔案最上面會變成循環匯入。
    from training_kb.site import publish_to_site

    ordered = list(dict.fromkeys(version_ids))
    if not ordered:
        return PublishResult(published=[], failed=None, reasons=[])

    seen_slug: dict[str, str] = {}
    targets: list[tuple[str, str, TutorialVersion, bool]] = []
    for version_id in ordered:
        slug = parse_version_id(version_id)[0]
        if slug in seen_slug:
            return PublishResult(
                published=[],
                failed=version_id,
                reasons=[
                    f"同一批出現同一篇教學的兩個版本：{seen_slug[slug]} 與 {version_id}"
                ],
            )
        seen_slug[slug] = version_id

        missing = verify_version_complete(repo, version_id)
        if missing:
            return PublishResult(published=[], failed=version_id, reasons=missing)

        version = repo.get_version(version_id)
        tutorial = repo.get_tutorial(slug)
        if version is None or tutorial is None:
            return PublishResult(
                published=[],
                failed=version_id,
                reasons=[f"找不到版本 {version_id} 或教學 {slug}"],
            )
        if tutorial.status != TutorialStatus.active:
            return PublishResult(
                published=[],
                failed=version_id,
                reasons=[f"教學 {slug} 已退役，不發布新版"],
            )

        already = (
            version.published_at is not None
            and tutorial.current_version == version_id
        )
        if not already and tutorial.current_version != version.supersedes:
            return PublishResult(
                published=[],
                failed=version_id,
                reasons=[
                    f"基底不符：教學目前版本是 {tutorial.current_version}，"
                    f"這一版的 supersedes 是 {version.supersedes}"
                ],
            )
        targets.append((version_id, slug, version, already))

    actions: list[dict] = []
    for version_id, slug, version, already in targets:
        if already:
            continue
        actions.extend(
            _publish_actions(repo.table_name, version_id, slug, version, now)
        )
    if actions:
        try:
            repo.transact_write(actions)
        except PermanentError as error:
            return PublishResult(
                published=[],
                failed=ordered[0],
                reasons=[f"DynamoDB 交易失敗（可能有其他流程同時改同一篇）：{error}"],
            )

    published: list[str] = []
    for version_id, slug, _version, _already in targets:
        publish_to_site(repo, renderer, slug, version_id)
        published.append(version_id)
    return PublishResult(published=published, failed=None, reasons=[])
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：

```bash
uv run pytest tests/integration/test_content_publish.py -v
```

預期：PASS，6 個 `PASSED`。

- [ ] **步驟 5：commit**

```bash
git add src/training_kb/content.py tests/integration/test_content_publish.py
git commit -m "feat(content): 以單筆交易發布版本並切換目前版本"
```

---

### Task 5：多篇一次發布時的全有或全無

**目的**：驗證同一次 Release 或每日 Review 命中多篇教學時，任何一篇不合格就整批不切換（F49、設計文件 §8.3）。

**檔案**：
- 測試：`tests/integration/test_content_publish_batch.py`

**介面**：
- 消費：`training_kb.content.publish`（Task 4）
- 產出：無新函式。這個 Task 只補上批次行為的測試；`publish` 的程式在 Task 3 就寫好了。

- [ ] **步驟 1：寫測試**

建立 `tests/integration/test_content_publish_batch.py`：

```python
"""Phase 08：多篇教學一次發布的全有或全無（用 moto 模擬 AWS）。"""

from datetime import datetime, timezone

from training_kb.content import publish, version_keys
from training_kb.site import SiteRenderer, site_keys

NOW = datetime(2026, 8, 20, 0, 0, 0, tzinfo=timezone.utc)


def two_ready(ready_version) -> tuple[str, str]:
    first = ready_version(operation_id="op-a")
    second = ready_version(
        "share-summary", operation_id="op-b", topic="分享摘要", cluster_id="c13"
    )
    return first, second


def test_兩篇都完整時一起發布(repo, ready_version):
    first, second = two_ready(ready_version)

    result = publish(repo, [first, second], SiteRenderer(), now=NOW)

    assert result.published == [first, second]
    assert repo.get_tutorial("prepare-meeting").current_version == first
    assert repo.get_tutorial("share-summary").current_version == second
    assert repo.object_exists(site_keys("prepare-meeting", 1)["page"]) is True
    assert repo.object_exists(site_keys("share-summary", 1)["page"]) is True


def test_其中一篇不完整時整批都不切換(repo, ready_version):
    first, second = two_ready(ready_version)
    repo.s3.delete_object(
        Bucket=repo.bucket, Key=version_keys("share-summary", 1)["md"]
    )

    result = publish(repo, [first, second], SiteRenderer(), now=NOW)

    assert result.published == []
    assert result.failed == second
    assert repo.get_tutorial("prepare-meeting").current_version is None
    assert repo.get_tutorial("share-summary").current_version is None
    assert repo.get_version(first).published_at is None
    assert repo.object_exists(site_keys("prepare-meeting", 1)["page"]) is False
    assert repo.object_exists(site_keys("share-summary", 1)["page"]) is False


def test_同一批不可以有同一篇教學的兩個版本(repo, ready_version):
    first = ready_version(operation_id="op-a")

    result = publish(repo, [first, first, "prepare-meeting@v2"], SiteRenderer(), now=NOW)

    assert result.published == []
    assert result.failed == "prepare-meeting@v2"
    assert any("同一篇教學的兩個版本" in reason for reason in result.reasons)
    assert repo.get_tutorial("prepare-meeting").current_version is None


def test_重複傳入同一個版本識別碼只處理一次(repo, ready_version):
    first = ready_version(operation_id="op-a")

    result = publish(repo, [first, first], SiteRenderer(), now=NOW)

    assert result.published == [first]
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：

```bash
uv run pytest tests/integration/test_content_publish_batch.py -v
```

預期：這四個測試中，`test_其中一篇不完整時整批都不切換` 與
`test_同一批不可以有同一篇教學的兩個版本` 會 FAIL，如果 Task 4 的 `publish` 漏掉了
「先全部驗證再提交」或「同一篇教學去重」其中一段。若 Task 4 完全照著寫，四個會直接
PASS——這時把 `publish` 裡「先全部驗證」的迴圈暫時改成「驗一篇就提交一篇」，重跑一次
看它變紅，再改回來，確認測試真的抓得到這個錯。

- [ ] **步驟 3：寫最少的程式讓測試通過**

`publish` 已經在 Task 4 寫好，這裡不需要新增函式。打開 `src/training_kb/content.py`，確認 `publish` 裡確實有下面三段程式；如果剛才為了看紅燈改過，現在改回來：

```python
    # 第一段：去重並保持順序，重複傳入同一個版本只處理一次。
    ordered = list(dict.fromkeys(version_ids))
```

第二段在 `for version_id in ordered:` 迴圈的開頭（DynamoDB 交易不允許同一筆資料在一個交易裡出現兩次，所以先擋下來）。從 Task 4 的 `publish` 節錄出來核對：

```text
        if slug in seen_slug:
            return PublishResult(
                published=[],
                failed=version_id,
                reasons=[
                    f"同一批出現同一篇教學的兩個版本：{seen_slug[slug]} 與 {version_id}"
                ],
            )
        seen_slug[slug] = version_id
```

第三段也在同一個迴圈裡：先把整批驗完並收進 `targets`，全部通過之後才呼叫 `repo.transact_write(actions)`。不可以「驗一篇就提交一篇」，否則 A 會先上架、B 失敗時就違反 F49。節錄如下：

```text
        missing = verify_version_complete(repo, version_id)
        if missing:
            return PublishResult(published=[], failed=version_id, reasons=missing)
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：

```bash
uv run pytest tests/integration/test_content_publish_batch.py -v
```

預期：PASS，4 個 `PASSED`。

- [ ] **步驟 5：commit**

```bash
git add tests/integration/test_content_publish_batch.py
git commit -m "test(content): 多篇發布的全有或全無驗收"
```

---

### Task 6：退役與後繼檢查

**目的**：寫出 `retire`。不管後繼合不合法，退役一定完成（F19）。

**檔案**：
- 修改：`src/training_kb/content.py`
- 測試：`tests/integration/test_content_retire.py`

**介面**：
- 消費：`Repository.get_tutorial`、`update_meta`
- 產出：`training_kb.content.retire(repo, slug: str, *, reason: str, successor: str | None, now: datetime) -> Tutorial`

- [ ] **步驟 1：寫測試**

建立 `tests/integration/test_content_retire.py`：

```python
"""Phase 08：退役與後繼檢查（用 moto 模擬 AWS）。"""

from datetime import datetime, timezone

import pytest

from training_kb.content import publish, retire
from training_kb.errors import ContentError
from training_kb.keys import tutorial_pk
from training_kb.models import TutorialStatus
from training_kb.site import SiteRenderer

NOW = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)


def published_tutorial(repo, ready_version, slug: str, operation_id: str, topic: str,
                       cluster_id: str) -> str:
    version_id = ready_version(
        slug, operation_id=operation_id, topic=topic, cluster_id=cluster_id
    )
    publish(repo, [version_id], SiteRenderer(), now=NOW)
    return version_id


def test_沒有後繼也能完成退役(repo, ready_version):
    published_tutorial(repo, ready_version, "prepare-meeting", "op-a", "準備會議", "c12")

    tutorial = retire(
        repo, "prepare-meeting", reason="release:r_99", successor=None, now=NOW
    )

    stored = repo.get_tutorial("prepare-meeting")
    assert tutorial.status == TutorialStatus.retired
    assert tutorial.successor is None
    assert stored.status == TutorialStatus.retired
    assert stored.successor is None
    assert repo.get_meta(tutorial_pk("prepare-meeting"))["retired_reason"] == "release:r_99"


def test_合法的後繼會被保留(repo, ready_version):
    published_tutorial(repo, ready_version, "prepare-meeting", "op-a", "準備會議", "c12")
    published_tutorial(repo, ready_version, "share-summary", "op-b", "分享摘要", "c13")

    tutorial = retire(
        repo,
        "prepare-meeting",
        reason="release:r_99",
        successor="share-summary",
        now=NOW,
    )

    assert tutorial.successor == "share-summary"
    assert repo.get_tutorial("prepare-meeting").successor == "share-summary"


def test_後繼是自己時清空(repo, ready_version):
    published_tutorial(repo, ready_version, "prepare-meeting", "op-a", "準備會議", "c12")

    tutorial = retire(
        repo,
        "prepare-meeting",
        reason="release:r_99",
        successor="prepare-meeting",
        now=NOW,
    )

    assert tutorial.status == TutorialStatus.retired
    assert tutorial.successor is None


def test_後繼不存在時清空(repo, ready_version):
    published_tutorial(repo, ready_version, "prepare-meeting", "op-a", "準備會議", "c12")

    tutorial = retire(
        repo, "prepare-meeting", reason="release:r_99", successor="ghost", now=NOW
    )

    assert tutorial.successor is None


def test_後繼還沒發布過版本時清空(repo, ready_version):
    published_tutorial(repo, ready_version, "prepare-meeting", "op-a", "準備會議", "c12")
    ready_version("share-summary", operation_id="op-b", topic="分享摘要", cluster_id="c13")

    tutorial = retire(
        repo,
        "prepare-meeting",
        reason="release:r_99",
        successor="share-summary",
        now=NOW,
    )

    assert tutorial.successor is None


def test_後繼已退役時清空(repo, ready_version):
    published_tutorial(repo, ready_version, "prepare-meeting", "op-a", "準備會議", "c12")
    published_tutorial(repo, ready_version, "share-summary", "op-b", "分享摘要", "c13")
    retire(repo, "share-summary", reason="release:r_98", successor=None, now=NOW)

    tutorial = retire(
        repo,
        "prepare-meeting",
        reason="release:r_99",
        successor="share-summary",
        now=NOW,
    )

    assert tutorial.successor is None


def test_會形成循環的後繼被清空(repo, ready_version):
    published_tutorial(repo, ready_version, "prepare-meeting", "op-a", "準備會議", "c12")
    published_tutorial(repo, ready_version, "share-summary", "op-b", "分享摘要", "c13")
    # share-summary 已經指回 prepare-meeting，再讓 prepare-meeting 指過去就成環。
    repo.update_meta(tutorial_pk("share-summary"), {"successor": "prepare-meeting"})

    tutorial = retire(
        repo,
        "prepare-meeting",
        reason="release:r_99",
        successor="share-summary",
        now=NOW,
    )

    assert tutorial.successor is None


def test_教學不存在時拋錯(repo):
    with pytest.raises(ContentError) as exc:
        retire(repo, "ghost", reason="release:r_99", successor=None, now=NOW)

    assert "找不到教學" in str(exc.value)
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：

```bash
uv run pytest tests/integration/test_content_retire.py -v
```

預期：FAIL，`ImportError: cannot import name 'retire' from 'training_kb.content'`。

- [ ] **步驟 3：寫最少的程式讓測試通過**

在 `src/training_kb/content.py` 最後面加上：

```python
def _valid_successor(repo: Repository, slug: str, successor: str | None) -> str | None:
    """檢查維護者選的後繼教學能不能用（設計文件 §8.4、D22、F54）。

    四個條件：存在、status 是 active、已經發布過版本、不是自己也不形成循環。
    任何一個不成立就回傳 None——F19 規定沒有合法後繼時仍然完成退役，只是不做導向。
    """
    if not successor or successor == slug:
        return None
    target = repo.get_tutorial(successor)
    if target is None:
        return None
    if target.status != TutorialStatus.active:
        return None
    if target.current_version is None:
        return None

    # 沿著後繼鏈往下走；走回自己或走進已經看過的節點，就是循環。
    seen = {slug}
    current: str | None = successor
    for _ in range(50):
        if current is None:
            return successor
        if current in seen:
            return None
        seen.add(current)
        node = repo.get_tutorial(current)
        if node is None:
            return successor
        current = node.successor
    return None


def retire(
    repo: Repository,
    slug: str,
    *,
    reason: str,
    successor: str | None,
    now: datetime,
) -> Tutorial:
    """把教學標記成 retired（設計文件 §8.4）。

    資料狀態只有 retired 一個值，obsolete 只是畫面用詞（D21）。
    歷史版本與原文全部保留；退役版本拒絕新回饋是 Phase 15 的 ingress 負責。
    retired_at 與 retired_reason 不是 ERM 欄位，是本計劃為了在畫面顯示過期說明
    而新增的執行資訊。
    """
    tutorial = repo.get_tutorial(slug)
    if tutorial is None:
        raise ContentError(f"找不到教學：{slug}")

    valid_successor = _valid_successor(repo, slug, successor)
    repo.update_meta(
        tutorial_pk(slug),
        {
            "status": str(TutorialStatus.retired),
            "successor": valid_successor,
            "retired_at": to_iso(now),
            "retired_reason": reason,
        },
    )
    return tutorial.model_copy(
        update={"status": TutorialStatus.retired, "successor": valid_successor}
    )
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：

```bash
uv run pytest tests/integration/test_content_retire.py tests/integration/test_site_publish.py -v
```

預期：PASS。`test_content_retire.py` 8 個、`test_site_publish.py` 5 個（包含 Task 3
留下來那個紅色的 `test_退役之後重新產生頁面會出現退役提示`，現在會變綠）。

- [ ] **步驟 5：commit**

```bash
git add src/training_kb/content.py tests/integration/test_content_retire.py
git commit -m "feat(content): 退役教學並檢查後繼是否合法"
```

---

### Task 7：同一篇教學的寫入鎖

**目的**：寫出 `with_tutorial_lock`。同一篇教學同時只能有一個操作在寫；搶不到就拋 `TransientError`，讓 Step Functions 的 Retry 稍後再試。

**檔案**：
- 修改：`src/training_kb/content.py`
- 測試：`tests/integration/test_content_lock.py`

**介面**：
- 消費：`Repository.acquire_lock(slug, owner, ttl_seconds, now) -> bool`、`release_lock(slug, owner)`（Phase 03）
- 消費：`training_kb.errors.TransientError`（Phase 01）
- 產出：`training_kb.content.TUTORIAL_LOCK_TTL_SECONDS: int`
- 產出：`training_kb.content.with_tutorial_lock(repo, slug, owner, now, fn) -> T`

- [ ] **步驟 1：寫測試**

建立 `tests/integration/test_content_lock.py`：

```python
"""Phase 08：同一篇教學的寫入鎖（用 moto 模擬 AWS）。"""

from datetime import datetime, timezone

import pytest

from training_kb.content import TUTORIAL_LOCK_TTL_SECONDS, with_tutorial_lock
from training_kb.errors import TransientError

NOW = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)


def test_取得鎖之後執行並回傳結果(repo):
    calls: list[str] = []

    def work() -> str:
        calls.append("執行了")
        return "完成"

    result = with_tutorial_lock(repo, "prepare-meeting", "op-a", NOW, work)

    assert result == "完成"
    assert calls == ["執行了"]


def test_鎖用完會釋放_下一個操作拿得到(repo):
    with_tutorial_lock(repo, "prepare-meeting", "op-a", NOW, lambda: None)

    result = with_tutorial_lock(repo, "prepare-meeting", "op-b", NOW, lambda: "第二次")

    assert result == "第二次"


def test_別人持有鎖時拋_TransientError(repo):
    assert (
        repo.acquire_lock("prepare-meeting", "op-a", TUTORIAL_LOCK_TTL_SECONDS, NOW)
        is True
    )

    with pytest.raises(TransientError) as exc:
        with_tutorial_lock(repo, "prepare-meeting", "op-b", NOW, lambda: "不該執行")

    assert "prepare-meeting" in str(exc.value)


def test_工作失敗時仍然釋放鎖(repo):
    def boom() -> None:
        raise ValueError("寫壞了")

    with pytest.raises(ValueError):
        with_tutorial_lock(repo, "prepare-meeting", "op-a", NOW, boom)

    assert with_tutorial_lock(repo, "prepare-meeting", "op-b", NOW, lambda: "ok") == "ok"


def test_不同教學的鎖互不影響(repo):
    repo.acquire_lock("prepare-meeting", "op-a", TUTORIAL_LOCK_TTL_SECONDS, NOW)

    result = with_tutorial_lock(repo, "share-summary", "op-b", NOW, lambda: "ok")

    assert result == "ok"
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：

```bash
uv run pytest tests/integration/test_content_lock.py -v
```

預期：FAIL，`ImportError: cannot import name 'TUTORIAL_LOCK_TTL_SECONDS' from 'training_kb.content'`。

- [ ] **步驟 3：寫最少的程式讓測試通過**

在 `src/training_kb/content.py` 的 import 區塊補上：

```python
from collections.abc import Callable
from typing import TypeVar

from training_kb.errors import TransientError
```

在 `LEGAL_STEP_TYPES` 後面加上：

```python
T = TypeVar("T")

# 鎖的存活時間。設計文件 §14.3 把單一 Task 的上限訂在 120 秒，取相同值，
# 讓當掉的執行最多鎖住一個 Task 的時間。
TUTORIAL_LOCK_TTL_SECONDS = 120
```

在檔案最後面加上：

```python
def with_tutorial_lock(
    repo: Repository,
    slug: str,
    owner: str,
    now: datetime,
    fn: Callable[[], T],
) -> T:
    """同一篇教學的寫入串行化。

    F35 要求同篇變更依接受順序串行處理。用「寫入前先取 LOCK#<slug>」來落實它，是
    本計劃選擇（對應設計文件第 18 節的待確認事項 O2）；O2 在 Phase 24 完成注入失敗
    與重送驗收之前，不可以宣稱寫入順序已經驗過。取不到鎖代表另一個操作正在寫，拋
    TransientError 讓 Step Functions 的 Retry 稍後再試（設計文件 §14.2）。

    不論 fn 成功或失敗都會釋放鎖；鎖本身也有 TTL，程式當掉時會自動失效。
    """
    if not repo.acquire_lock(slug, owner, TUTORIAL_LOCK_TTL_SECONDS, now):
        raise TransientError(f"教學 {slug} 正在被其他操作寫入，稍後重試")
    try:
        return fn()
    finally:
        repo.release_lock(slug, owner)
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：

```bash
uv run pytest tests/integration/test_content_lock.py -v
uv run pytest -q
uv run ruff check .
uv run ruff format .
```

預期：新測試 5 個 `PASSED`；整包測試全部通過；`ruff check` 顯示 `All checks passed!`。

- [ ] **步驟 5：commit**

```bash
git add src/training_kb/content.py tests/integration/test_content_lock.py
git commit -m "feat(content): 同一篇教學的寫入鎖與可重試錯誤"
```

---

## 7. 完成檢查清單

- [ ] `src/training_kb/site.py` 提供 `SITE_PREFIX`、`site_keys`、`SiteRenderer`（三個 render 方法）、`publish_to_site`。
- [ ] `src/training_kb/content.py` 多了 `PublishResult`、`TUTORIAL_LOCK_TTL_SECONDS`、`parse_markdown`、`publish`、`retire`、`with_tutorial_lock`。
- [ ] `uv run pytest -q` 整包通過。本階段新增 43 個測試（unit 15 個、integration 28 個）。
- [ ] `uv run ruff check .` 顯示 `All checks passed!`。
- [ ] 手動驗證「發布後讀到正確全文」（切片 S3）：

```bash
uv run pytest tests/integration/test_site_publish.py::test_頁面內容來自_s3_全文與_dynamodb_步驟 -v
```

預期：`1 passed`。

- [ ] 手動驗證「中途失敗仍讀舊版」（切片 S3、F37）：

```bash
uv run pytest "tests/integration/test_content_publish.py::test_驗證失敗時不切換目前版本也不寫公開站" -v
```

預期：`1 passed`。

- [ ] 手動驗證「多篇全有或全無」（F49、設計文件 §8.3）：

```bash
uv run pytest "tests/integration/test_content_publish_batch.py::test_其中一篇不完整時整批都不切換" -v
```

預期：`1 passed`。

- [ ] 手動驗證「退役有／無後繼都能完成，無效後繼不建立循環導向」（設計文件第 15 節「退役」列）：

```bash
uv run pytest tests/integration/test_content_retire.py -v
```

預期：`8 passed`。

- [ ] 手動驗證 HTML 跳脫（設計文件 §17.2）：

```bash
uv run pytest "tests/unit/test_site_render.py::test_所有文字都經過_html_跳脫" -v
```

預期：`1 passed`。

- [ ] 確認公開界線：整個 `src/` 只有 `site.py` 會組出 `site/` 開頭的 key。

```bash
grep -rn "site_keys\|SITE_PREFIX" src/training_kb/ | grep -v "^src/training_kb/site.py:"
```

預期：沒有任何輸出。（`content.py` 只透過 `publish_to_site` 間接寫公開站，不自己拼 key。）

---

## 8. 常見錯誤與排除

**症狀 1：`ImportError: cannot import name 'publish_to_site' from partially initialized module 'training_kb.site' (most likely due to a circular import)`**

原因：`content.py` 在檔案最上面就 `from training_kb.site import publish_to_site`，而 `site.py` 又在最上面 `from training_kb.content import parse_markdown`，兩邊互等。

解法：`content.publish` 裡的匯入必須放在**函式內**；型別註記用 `TYPE_CHECKING` 區塊。`site.py` 則正常在最上面匯入 `content`。方向只能是「site 匯入 content」。

---

**症狀 2：`PermanentError` 在 v1 publish 時就被丟出來，訊息說條件不符**

原因：`TUTORIAL#<slug>` 這筆資料的 `current_version` 屬性被寫成了 DynamoDB 的 `NULL` 型別，而不是「屬性不存在」。`attribute_not_exists` 對 NULL 型別會回傳 false。

解法：Phase 07 的 `put_tutorial` 必須在 `current_version is None` 時**不寫這個屬性**。本階段的條件已經加上 `OR attribute_type(#current, :null_type)` 當作保險，如果連這樣都失敗，先用下面這行看實際存了什麼：

```bash
uv run python -c "
import boto3
table = boto3.resource('dynamodb').Table('training_kb')
print(table.get_item(Key={'PK':'TUTORIAL#prepare-meeting','SK':'META'})['Item'])
"
```

---

**症狀 3：`botocore.exceptions.ParamValidationError: Missing required parameter in TransactItems[0].Update: "TableName"`，或 `Invalid type for parameter ... ExpressionAttributeValues`**

原因：`_publish_actions` 產生的動作格式跟 Phase 03 的 `transact_write` 對不起來。Phase 03 是把 `actions` 原樣送給 boto3（`self.client.transact_write_items(TransactItems=actions)`），所以每個動作**必須自己帶 `TableName`**，而且值要用低階格式 `{"S": "..."}`。

解法：確認 `_publish_actions` 的兩個動作都有 `"TableName": table_name`，而且 `publish` 呼叫時傳的是 `repo.table_name`。如果 Phase 03 後來改成「自動把 Python 值轉成低階型別」，就把 `_publish_actions` 裡所有 `{"S": x}` 改成 `x`、`{"S": "NULL"}` 改成 `"NULL"`，或改用 Phase 03 提供的 `serialize_item()`——兩種寫法擇一，整個專案一致。

---

**症狀 4：`moto` 回報 `ValidationException: Invalid ConditionExpression: Invalid function name; function: attribute_type`**

原因：moto 版本太舊，條件表示式的解析器不認得 `attribute_type`。

解法：升級 moto（`uv add --dev "moto[s3,dynamodb]>=5"`）。`attribute_type` 是 DynamoDB 正式支援的條件函式，`type` 這個運算元必須用表示式屬性值傳入（`{"S": "NULL"}`），不能直接寫在字串裡。

---

**症狀 5：`publish` 回報成功，但公開頁面還是舊的**

原因：DynamoDB 交易成功之後，寫 `site/` 的那幾行拋了例外（例如網路中斷），而例外沒有被處理。這正是設計文件第 18 節 O3 指出還沒關閉的缺口。

解法：重跑同一次 `publish`。因為那一版的 `published_at` 已經有值、`current_version` 也已經指過去，`publish` 會把它判定成「已發布」，跳過交易，只補寫 `site/`。這條路徑由 Phase 24 用注入失敗做整合驗收；在那之前**不可以宣稱 publish 的故障驗收已通過**。

---

**症狀 6：`retire` 之後公開頁面沒有出現退役提示**

原因：`retire` 只改 DynamoDB，不碰 `site/`（它的簽名裡沒有 renderer）。

解法：呼叫端要在 `retire` 之後呼叫 `publish_to_site(repo, renderer, slug, tutorial.current_version)` 重新產生頁面。Phase 16 的 RETIRE task 會做這件事；本階段的 `test_退役之後重新產生頁面會出現退役提示` 就是在驗證這條路徑。

---

**症狀 7：`test_同一批不可以有同一篇教學的兩個版本` 沒有被擋下來，交易報錯 `Transaction request cannot include multiple operations on one item`**

原因：`publish` 少了「同一篇教學只能有一個版本」的檢查，兩個動作同時指向同一筆 `TUTORIAL#<slug>`，DynamoDB 直接拒絕整筆交易。

解法：照 Task 5 的第三步補上 `seen_slug` 檢查。這不是效能優化，是 DynamoDB 交易的硬性限制（同一筆資料在一個交易裡只能出現一次）。

---

## 9. 這階段不做的事

| 不做的事 | 留給哪一階段 |
|---|---|
| 完整的教學頁：版本下拉選單、diff 檢視介面、回饋 widget、瀏覽紀錄匯出、`demo/site_assets/` 的 CSS 與 JS | Phase 22（`22-Phase22-S3靜態教學站.md`）。三個 render 方法的名稱與參數不會變。 |
| 「合成資料示範」標示與資料批次標籤（設計文件 §11.5、§13） | Phase 22、Phase 23 |
| 建立 S3 website endpoint、設定公開讀取政策 | Phase 04（bucket 與 IAM）、Phase 25（安全檢查） |
| 退役版本拒絕新回饋 | Phase 15（`15-Phase15-Feedback與View匯入.md`，ingress 負責） |
| 決定什麼時候該 RETIRE（`kind=removed` 的判斷）與由誰指定 successor | Phase 16（`16-Phase16-Release-Note-Update流程.md`） |
| 把 `publish` 與 `retire` 接到 Step Functions Task | Phase 14（`14-Phase14-StepFunctions與Lambda上線.md`） |
| 注入 S3／DynamoDB／publish 失敗做故障驗收（O2、O3 的整合驗證） | Phase 24（`24-Phase24-失敗復原與重送驗收.md`） |
| `list_versions_of_tutorial` 等其餘固定讀取 | Phase 09（`09-Phase09-圖譜查詢與backfill.md`）。本階段用版本鏈走訪代替。 |

---

## 10. 對照：設計章節與 Rule 編號

### 10.1 `發布教學版本.feature`（5 條，全部屬於本階段）

| Rule 編號與原文 | 本階段哪個 Task 落實 |
|---|---|
| Rule 1「publish 上架指定的 TutorialVersion」 | Task 4（`publish`）。補充文字要求「S3 已寫入但版本或關聯不完整的版本不可 publish」，由 `verify_version_complete` 把關（Phase 07 Task 6）。 |
| Rule 2「發布的教學透過 S3 靜態 docs 站提供」 | Task 1、Task 3（`site/` 四個 key） |
| Rule 3「發布的教學提供 feedback widget」 | 本階段**不做**。最小版頁面沒有 widget，完整版在 Phase 22（設計文件 §13）。 |
| Rule 4「Tutorial 的 current_version 指向目前教學版本」 | Task 4（交易的第二個動作；條件 `current_version == supersedes`） |
| Rule 5「已上架的版本具有 published_at」 | Task 4（交易的第一個動作；未發布時屬性不存在，D25） |

### 10.2 `依改版更新教學.feature` 中的兩條 RETIRE Rule

| Rule 編號與原文 | 本階段哪個 Task 落實 |
|---|---|
| Rule 16「RETIRE 將受影響教學標記為過期」 | Task 6（`status=retired`；`obsolete` 只是顯示文字，D21） |
| Rule 17「RETIRE 的教學導向後繼 Tutorial」 | Task 6（`_valid_successor` 四項檢查）、Task 1（頁面上的後繼連結或「目前沒有指定後繼教學」，F19、F54） |

補充文字「後繼由維護者選定既有 Tutorial，寫入 Tutorial.successor，值為裸 slug」對應 `retire` 的 `successor` 參數與 D22（successor 存在 Tutorial metadata）。

### 10.3 其他相關 Rule

| Rule 來源檔 | Rule 編號與原文 | 本階段哪個 Task 落實 |
|---|---|---|
| `建立教學版本.feature` | Rule 5 的補充「S3 已寫入但版本或關聯不完整時，保留不可公開的未完成未發布版本；待全部就緒後才允許 publish」（F36） | Task 4（`publish` 第一步逐篇 `verify_version_complete`） |
| `執行教學流程.feature` | Rule 7「每個 Step Functions Task 設定 Catch」的下游後果 F49「整次執行以失敗結束，不發布新版本」 | Task 5（多篇全有或全無） |
| `收集教學回饋.feature` | Rule 2「已退役教學的既有版本拒絕新回饋」 | 本階段只負責把 `status` 寫成 `retired`；拒絕新回饋由 Phase 15 的 ingress 落實（F39）。 |
| `查詢知識圖譜.feature` | Rule 4「可查詢某篇 Tutorial 所屬的版本」 | 本階段用 `_version_chain` 沿 `supersedes` 走訪，供索引頁使用；正式的 `list_versions_of_tutorial` 在 Phase 09。 |

---

## 11. 參考來源

設計文件（`docs/design/training-kb.md`）：

- §8.1 五種動作與版本鏈（RETIRE 的定義）
- §8.2 create_version 的完成條件（publish 成功才有 `published_at` 與 `current_version`）
- §8.3 發布與併發必須守住的界線（先驗證、再交易、才公開；多篇全有或全無）
- §8.4 退役後的畫面與資料（successor 檢查、不做連續自動跳轉、拒絕新回饋）
- §9.3 S3 與執行資訊（`site/` 只有發布流程可寫）
- §10 圖譜查詢（基表一致讀取）
- §13 Demo UI 與 S3 教學頁（公開界線、website endpoint 只有 HTTP）
- §14.1、§14.2、§14.3（失敗語意、Retry／Catch、Task 上限 120 秒）
- §15 測試與驗收設計，「版本與發布」「退役」「UI 與公開界線」三列
- §16 交付切片 S3
- §17.2 最小必要的安全處理（HTML 跳脫、公開區只放可公開內容）
- §18 待確認事項 O2（操作紀錄與接受順序）、O3（S3 公開與發布提交）
- §19.1 資料決策 D21、D22、D25
- §19.2 功能決策 F19、F36、F37、F38、F39、F49、F50、F54
- §20.1、§20.12 逐條 Rule 與負責模組

規格檔：

- `docs/spec/features/發布教學版本.feature`
- `docs/spec/features/依改版更新教學.feature`（Rule 16、17）
- `docs/spec/features/建立教學版本.feature`
- `docs/spec/erm.dbml`（TUTORIAL.current_version、TUTORIAL.successor、TUTORIAL_VERSION.published_at）
- `docs/spec/.clarify/resolved/data/TUTORIAL_後繼_Tutorial_的關係要持久化在哪裡.md`（D22）
- `docs/spec/.clarify/resolved/features/發布教學版本_current_version_在哪個時點切換到新版.md`（F37）
- `docs/spec/.clarify/resolved/features/依改版更新教學_退役時沒有後繼_Tutorial_要呈現什麼結果.md`（F19）
- `docs/spec/.clarify/resolved/features/依改版更新教學_退役教學的後繼_Tutorial_由哪個來源指定.md`（F54）
- `docs/spec/.clarify/resolved/features/執行教學流程_Task_重試耗盡並進入_Catch_後如何結束流程.md`（F49）

官方文件（本階段用到的語法都以這些為準）：

- boto3 DynamoDB `transact_write_items`（`TransactItems`、`Update`、`ConditionExpression`、最多 100 個動作、同一筆資料不可重複）：<https://docs.aws.amazon.com/boto3/latest/reference/services/dynamodb/client/transact_write_items.html>
- DynamoDB 交易 API 與限制：<https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/transaction-apis.html>
- DynamoDB 條件表示式的運算子與函式（`attribute_not_exists`、`attribute_type` 與它的型別運算元必須用表示式屬性值傳入）：<https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/Expressions.OperatorsAndFunctions.html>
- boto3 S3 `put_object`：<https://docs.aws.amazon.com/boto3/latest/reference/services/s3/client/put_object.html>
- Amazon S3 條件寫入：<https://docs.aws.amazon.com/AmazonS3/latest/userguide/conditional-writes.html>
- Amazon S3 website endpoints（只有 HTTP）：<https://docs.aws.amazon.com/AmazonS3/latest/userguide/WebsiteEndpoints.html>
- Python `html.escape`：<https://docs.python.org/3/library/html.html#html.escape>
- Python `re` 模組：<https://docs.python.org/3/library/re.html>
- pydantic v2 `model_copy`：<https://docs.pydantic.dev/latest/api/base_model/#pydantic.BaseModel.model_copy>
- moto `mock_aws`：<https://docs.getmoto.org/en/latest/docs/getting_started.html>
