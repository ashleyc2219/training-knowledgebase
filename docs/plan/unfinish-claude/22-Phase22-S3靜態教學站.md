# Phase 22：S3 靜態教學站

| 項目 | 內容 |
|---|---|
| 上一階段 | Phase 21：Demo 種子資料與可重算驗證（`21-Phase21-Demo種子資料與可重算驗證.md`） |
| 下一階段 | Phase 23：Demo 控制台與 Dashboard（`23-Phase23-Demo控制台與Dashboard.md`） |
| 對應設計文件章節 | §13、§8.4、§9.3、§17.2、F38（`docs/design/training-kb.md`） |
| 對應交付切片 | S3、S4（設計文件第 16 節） |
| 預估時間 | 約 7 小時 |
| 做完會得到 | 一個放在 S3 上、可以用瀏覽器打開的教學站：有版本選擇、差異檢視、回饋 widget 與退役頁，而且只有 `site/` 前綴是公開的。 |

---

## 1. 這階段做完會得到什麼

Phase 08 已經做了最小版的 `SiteRenderer`（標題、五段、步驟、版本號、退役提示、跳脫）。這一階段把它擴充成設計文件 §13 畫的那個畫面：

1. **版本選擇**：頁面列出這篇教學所有已發布版本的連結，目前這一版標記出來。
2. **查看與前版差異**：連到 `v<n>.diff.txt`。v1 顯示「第一版，沒有前一版可比較」，不給連結（設計文件 F50）。
3. **查看版本紀錄**：連到該篇教學的索引頁。
4. **回饋 widget**：1–5 分、類別按鈕（找不到按鈕／缺少資訊／未選擇）、留言欄、穩定 user ID 輸入欄，按下「下載回饋檔案，交由維護者匯入」會產生一個符合 Phase 15 匯入格式的 JSON 檔，畫面顯示「檔案已產生，尚未送出」。
5. **記錄瀏覽**：另一個按鈕，產生瀏覽紀錄 JSON 檔。
6. **退役頁**：顯示「此教學已過期」與原因、保留原文、有後繼教學才顯示可點連結、**不自動跳轉**、widget 停用並說明「已退役，不接受新回饋」。
7. **固定標示**：每一頁都寫「合成資料示範」與資料批次。
8. **`demo/site_assets/widget.js` 與 `style.css`**：純 JavaScript，不引任何外部 CDN，不含任何金鑰。
9. **CDK 設定**：bucket 開啟 website hosting，bucket policy 只允許 `s3:GetObject` 於 `site/*`。

**函式名稱與參數完全不變**——Phase 08 寫好的 `render_version_page(...)` 簽名一個字都不動，只是回傳的 HTML 變豐富了。

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
                                   ^^^^^^^^^^^^^
                                   你在這裡
```

你在「展示與驗收層」的第二格。Phase 21 已經把教學寫進 S3，這一階段讓它變成人看得懂的網頁。

---

## 3. 開始前檢查

### 3.1 前置條件

| 條件 | 為什麼需要 |
|---|---|
| Phase 02 完成 | 需要 `Tutorial`、`TutorialVersion`、`TutorialStep`、`TutorialContent`、`parse_version_id`。 |
| Phase 03 完成 | 需要 `repo.put_object()`、`repo.get_object()`、`repo.object_exists()`。 |
| Phase 07 完成 | 需要 `content.render_markdown()`（頁面內容的段落順序沿用它的定義）。 |
| Phase 08 完成 | 需要最小版的 `SiteRenderer`、`site_keys()`、`publish_to_site()`、`content.publish()`。 |
| Phase 15 完成 | 需要 `ingress.validate_feedback()`、`ingress.validate_view()`（Task 8 用來驗證 widget 產生的檔案）。 |
| Phase 04 完成 | 需要 `infra/stacks/data_stack.py`（Task 7 要改它）。 |
| Node.js 與 CDK CLI 可用 | Task 7 要跑 `uv run pytest` 的 CDK assertions，不一定要 deploy，但 `aws-cdk-lib` 必須裝好。 |

### 3.2 驗證指令與預期輸出

```bash
cd ~/AWS-Hackathon
uv run python -c "
from training_kb.site import SiteRenderer, site_keys, publish_to_site
from training_kb.ingress import validate_feedback, validate_view
from training_kb.content import render_markdown
import aws_cdk
print('前置介面齊全，aws-cdk-lib 版本：', aws_cdk.__version__ if hasattr(aws_cdk, '__version__') else '已安裝')
"
```

預期：印出一行「前置介面齊全，...」。

```bash
uv run python -c "
from training_kb.site import site_keys
print(site_keys('prepare-meeting', 2))
"
```

預期：

```text
{'page': 'site/prepare-meeting/v2.html', 'diff': 'site/prepare-meeting/v2.diff.txt', 'index': 'site/prepare-meeting/index.html', 'root': 'site/index.html'}
```

建立資產目錄：

```bash
mkdir -p demo/site_assets
```

---

## 4. 名詞小抄

| 名詞 | 白話解釋 | 在本階段哪裡用到 |
|---|---|---|
| S3 website endpoint | 把 S3 bucket 當成靜態網站伺服器的網址，格式像 `http://<bucket>.s3-website-<region>.amazonaws.com`。**只有 HTTP，沒有 HTTPS**（設計文件 §13 明說不把它描述為 HTTPS）。 | Task 7 |
| Block Public Access | S3 的四道保險，預設全開，會擋掉任何讓 bucket 公開的設定。要做公開靜態站，必須關掉其中的 `BlockPublicPolicy` 與 `RestrictPublicBuckets`。 | Task 7 |
| Bucket Policy | 一份 JSON 規則，寫「誰可以對這個 bucket 的哪些物件做什麼」。我們只允許任何人對 `site/*` 做 `s3:GetObject`（讀取）。 | Task 7 |
| `html.escape` | Python 標準函式，把 `<`、`>`、`&`、`"`、`'` 換成安全的實體字，例如 `<script>` 變成 `&lt;script&gt;`。這樣使用者或模型寫的文字就不會變成可執行的網頁程式碼。 | Task 1 |
| `textContent` vs `innerHTML` | JavaScript 裡放文字的兩種方式。`textContent` 把字串當純文字放進去（安全）；`innerHTML` 會把字串當 HTML 解析（不安全）。本階段的 widget **只用 `textContent`**。 | Task 3 |
| widget | 嵌在教學頁面上的小工具。這裡指評分與留言的表單。 | Task 2、Task 3 |
| Blob / `URL.createObjectURL` | 瀏覽器把一段資料變成可下載檔案的標準做法。我們用它產生回饋 JSON 檔讓使用者存到電腦。 | Task 3 |
| successor（後繼教學） | 教學退役時，維護者可以指定另一篇教學當接班人。沒有指定也能完成退役（設計文件 F19、F54）。 | Task 4 |
| 資料批次 | 這一批展示資料的名稱，固定顯示在頁面上，讓人知道看到的是哪一版種子（設計文件 §11.5）。 | Task 1 |
| F38 | 設計文件第 19.2 節的功能決策編號：MVP 只提供 S3 靜態 docs 站，頁面包含版本化內容與 feedback widget，不另做 in-app 教學頁。 | 第 10 節對照表 |
| F39 | 設計文件功能決策：已退役教學的既有版本拒絕新回饋，既有回饋保留供歷史查詢。 | Task 4 |
| O3 | 設計文件第 18 節待確認事項：S3 公開與發布提交。**本計劃選擇**：私有產物全部驗證完成 → DynamoDB 交易切換 → 才寫 `site/`。 | Task 6、第 9 節 |

---

## 5. 設計說明

### 5.1 頁面長什麼樣（設計文件 §13）

```text
┌──────────────────────────────────────────────────────────────────┐
│ [合成資料示範]  資料批次：demo-seed-01                             │
├──────────────────────────────────────────────────────────────────┤
│ 準備會議：在會議開始前拿到重點摘要                  版本：v2       │
│ 改動原因：feedback:8 則 找不到按鈕                                │
├──────────────────────────────────────────────────────────────────┤
│ 問題                                                             │
│   使用者在會議開始前找不到系統整理好的重點摘要…                    │
│                                                                  │
│ 前置條件                                                         │
│   • 已登入工作區，且今天的行事曆中至少有一場會議                   │
│   • 該會議底下已有至少一則討論訊息或一份附件                       │
│                                                                  │
│ 步驟                                                             │
│   1. [read]      在左側選單開啟「通知設定」…                       │
│   2. [input]     在「會議開始前提醒」的分鐘數欄位輸入 15…           │
│   3. [click_ui]  在會議頁面右上角的工具列，點選標示為…              │
│   4. [read]      在摘要下方的「分享摘要」區塊確認…                  │
│                                                                  │
│ 預期結果                                                         │
│   會議開始前 15 分鐘會收到提醒…                                   │
├──────────────────────────────────────────────────────────────────┤
│ 版本選擇：  [v1]  [v2（目前）]                                    │
│ [查看與 v1 的差異]   [查看版本紀錄]                                │
├──────────────────────────────────────────────────────────────────┤
│ 這篇有幫助嗎？   [1] [2] [3] [4] [5]                              │
│ 問題類別：       [找不到按鈕] [缺少資訊] [未選擇]                  │
│ 留言：           ______________________________________           │
│ 你的使用者 ID：  ______________  （必填，請使用維護者提供的 ID）   │
│ [下載回饋檔案，交由維護者匯入]   [記錄瀏覽]                        │
│ 狀態：（按下按鈕後顯示「檔案已產生，尚未送出」）                    │
└──────────────────────────────────────────────────────────────────┘
```

退役版本的頁面：

```text
┌──────────────────────────────────────────────────────────────────┐
│ [合成資料示範]  資料批次：demo-seed-01                             │
├──────────────────────────────────────────────────────────────────┤
│ ⚠ 此教學已過期                                                    │
│   原因：產品改版（r_42）後此教學已過期。                           │
│   以下原文保留供查閱，內容不再更新。                               │
│   後繼教學：分享摘要（share-summary）   ← 只有維護者指定時才出現   │
├──────────────────────────────────────────────────────────────────┤
│ （原本的五段內容，一字不改）                                       │
├──────────────────────────────────────────────────────────────────┤
│ 版本選擇 / 差異 / 版本紀錄（照常顯示）                             │
├──────────────────────────────────────────────────────────────────┤
│ 此教學已退役，不接受新回饋。既有回饋仍保留供歷史查詢。              │
│ （沒有任何評分按鈕、留言欄或送出按鈕）                             │
└──────────────────────────────────────────────────────────────────┘
```

### 5.2 回饋怎麼從瀏覽器回到系統

設計文件 §13 與 F08 都要求：Feedback 走**手動上傳**，不開放未驗證的公開接入。所以 widget 不會送任何網路請求，它只在瀏覽器裡產生一個檔案。

```text
  使用者在教學頁填評分、類別、留言、user ID
              |
              | 按下「下載回饋檔案，交由維護者匯入」
              v
  widget.js 用 Blob 產生一個 JSON 檔並觸發下載
  畫面顯示「檔案已產生，尚未送出」  ← 絕不顯示「已送出」或「已保存」
              |
              | 使用者把檔案交給維護者
              v
  維護者用已登入的 AWS 身分呼叫 import Lambda
  （Phase 14 的 handlers/import_.py，event = {"kind": "feedback", "items": [...]}）
              |
              v
  Phase 15 的 ingress.import_feedback() 驗證欄位、檢查版本存在、檢查教學未退役
              |
     +--------+--------+
     v                 v
   saved            rejected（指出不合法欄位，允許修正）
```

產生的檔案格式必須讓 `import Lambda` 直接吃：

```json
{
  "kind": "feedback",
  "source": "site_widget",
  "generated_at": "2026-09-13T12:34:56Z",
  "note": "合成資料示範｜此檔尚未送出，需由維護者匯入",
  "items": [
    {
      "id": "f_site-prepare-meeting-v2-u_01-1789012345",
      "tutorial_version": "prepare-meeting@v2",
      "rating": 4,
      "user": "u_01",
      "category": "缺少資訊",
      "comment": "第三步的截圖可以再清楚一點",
      "ts": "2026-09-13T12:34:56Z"
    }
  ]
}
```

瀏覽紀錄的檔案：

```json
{
  "kind": "view",
  "source": "site_widget",
  "generated_at": "2026-09-13T12:34:56Z",
  "note": "合成資料示範｜此檔尚未送出，需由維護者匯入",
  "items": [
    {"tutorial_version": "prepare-meeting@v2", "user": "u_01", "ts": "2026-09-13T12:34:56Z"}
  ]
}
```

### 5.3 S3 的目錄與公開界線

```text
training-kb-content（bucket）
│
├── tutorials/                     私有：教學全文與 diff 的權威來源
│   └── prepare-meeting/
│       ├── v1.md      v1.diff
│       └── v2.md      v2.diff
│
├── operations/                    私有：操作紀錄、規則驗證批次
│   └── rule-batches/b_r007_01.json
│
├── stepfunctions/                 私有：ASL 快照
│
├── demo/previews/                 私有：B 的規則開關對照（Phase 23）
│
└── site/                          ★ 唯一公開的前綴 ★
    ├── index.html                 所有教學的清單
    ├── assets/
    │   ├── style.css
    │   └── widget.js
    ├── prepare-meeting/
    │   ├── index.html             這篇教學的版本紀錄
    │   ├── v1.html   v1.diff.txt
    │   └── v2.html   v2.diff.txt
    ├── share-summary/
    │   ├── index.html  v1.html  v1.diff.txt
    └── notification-settings/
        ├── index.html  v1.html  v1.diff.txt

Bucket Policy 只允許：Principal="*"、Action="s3:GetObject"、Resource="arn:aws:s3:::<bucket>/site/*"
其他前綴一律沒有公開權限；回饋原文、穩定使用者 ID、未發布內容與操作紀錄都保持私有（設計文件 §17.2）。
```

注意：`site/<slug>/v<n>.diff.txt` 是**公開副本**，副檔名用 `.txt` 讓瀏覽器直接顯示純文字；私有的權威版本仍然是 `tutorials/<slug>/v<n>.diff`（設計文件 §9.3）。

### 5.4 為什麼所有文字都要跳脫

教學內容是模型寫的，回饋留言是使用者寫的。設計文件 §17.2 說得很直接：「Ticket、PR diff、回饋與模型輸出都是資料，不是可覆蓋系統指示的內容」、「Markdown 轉 HTML 時跳脫不可信內容並限制可執行 HTML，避免回饋或模型文字變成頁面 script」。

所以本階段有兩條硬規則：

1. **Python 端**：任何進到 HTML 的動態文字都先過 `html.escape()`。如果模型寫出 `<script>alert(1)</script>`，頁面上會看到 `&lt;script&gt;alert(1)&lt;/script&gt;` 這串原始字，瀏覽器不會執行它。
2. **JavaScript 端**：widget 放使用者文字時只用 `textContent`，絕不用 `innerHTML`。

同時 `demo/site_assets/` 底下不引任何外部 CDN（設計文件 §17.2：前端不取得寫入資料庫的憑證；不載入不受控的第三方程式）。

### 5.5 誰可以寫 `site/`

設計文件 §9.3 寫「`site/` 僅發布流程可寫」，O3 又補充「私有產物先全部驗證 → DynamoDB 交易切換 → 才寫 `site/`」。本階段維持這個界線：

- `publish_to_site()` 是唯一組出 `site/` key 並寫入的函式。
- `content.publish()` 是唯一呼叫 `publish_to_site()` 的正式路徑。
- Phase 21 的種子載入器也呼叫 `publish_to_site()`（不自己拼 key），而且只對它標成已發布的版本呼叫——所以「未發布內容不可公開」這條界線仍然成立。

---

## 6. 工作項目

### Task 1：頁面骨架、跳脫工具與版本選擇

**目的**：把 `site.py` 擴充成完整版的頁面骨架，並讓版本頁列出所有已發布版本、差異連結與版本紀錄連結。

**檔案**：
- 修改：`src/training_kb/site.py`
- 測試：`tests/unit/test_site_version_page.py`

**介面**：
- 消費（Phase 02）：`models.Tutorial`、`models.TutorialVersion`、`models.TutorialStep`、`models.TutorialContent`、`models.parse_version_id`
- 產出（簽名與 Phase 08 完全相同）：
  - `site.SiteRenderer.__init__(self, *, data_batch="demo-seed-01", synthetic_notice="合成資料示範")`（**本階段補上具名參數，皆有預設值，`SiteRenderer()` 仍可用**）
  - `site.SiteRenderer.render_version_page(self, tutorial, version, steps, content, *, versions, diff_text, retired, successor) -> str`
  - `site.site_keys(slug, n) -> dict[str, str]`
- 產出（**簡報第 6 節未列，本階段新增的模組層工具**）：
  - `site.esc(value) -> str`
  - `site.ASSET_KEYS: dict[str, str]`
  - `site.page_shell(*, title, body, notice, data_batch, depth) -> str`

**`depth` 是什麼**：頁面在 `site/` 底下的深度，用來組出相對路徑。`site/index.html` 的 depth 是 0（資產在 `assets/style.css`）；`site/<slug>/v2.html` 的 depth 是 1（資產在 `../assets/style.css`）。靜態站沒有伺服器端路由，只能用相對路徑。

- [ ] **步驟 1：寫測試**

```python
# tests/unit/test_site_version_page.py
"""Phase 22 Task 1：版本頁的骨架、跳脫與版本選擇。"""

from training_kb.models import (
    StepDraft,
    Tutorial,
    TutorialContent,
    TutorialStep,
    TutorialVersion,
)
from training_kb.site import ASSET_KEYS, SiteRenderer, esc, page_shell, site_keys


def _tutorial(status: str = "active", successor: str | None = None) -> Tutorial:
    return Tutorial(
        slug="prepare-meeting",
        current_version="prepare-meeting@v2",
        topic="準備會議",
        feature_ids=["Prepare"],
        status=status,
        successor=successor,
        cluster_id="c12",
    )


def _version(number: int, published: str | None, reason: str) -> TutorialVersion:
    return TutorialVersion(
        version_id=f"prepare-meeting@v{number}",
        supersedes=None if number == 1 else f"prepare-meeting@v{number - 1}",
        reason=reason,
        rules_applied=[] if number == 1 else ["R-007"],
        s3_key=f"tutorials/prepare-meeting/v{number}.md",
        published_at=published,
    )


def _steps(version_id: str) -> list[TutorialStep]:
    return [
        TutorialStep(
            tutorial_version=version_id,
            index=1,
            type="read",
            text="在左側選單開啟「通知設定」。",
            feature_id="Notification Settings",
        ),
        TutorialStep(
            tutorial_version=version_id,
            index=2,
            type="click_ui",
            text="點選 <script>alert(1)</script> 按鈕。",
            feature_id="Prepare",
        ),
    ]


def _content() -> TutorialContent:
    return TutorialContent(
        title="準備會議：在會議開始前拿到重點摘要",
        problem="使用者找不到會前摘要 & 只能自己翻訊息。",
        prerequisites=["已登入工作區", "會議底下有討論訊息"],
        steps=[
            StepDraft(
                type="read",
                text="在左側選單開啟「通知設定」。",
                feature_id="Notification Settings",
            ),
            StepDraft(
                type="click_ui",
                text="點選 <script>alert(1)</script> 按鈕。",
                feature_id="Prepare",
            ),
        ],
        expected_outcome="能在會議頁看到會前摘要。",
    )


VERSIONS = [
    _version(1, "2026-08-01T00:00:00Z", "gap:c12"),
    _version(2, "2026-08-20T00:00:00Z", "feedback:8 則 找不到按鈕"),
    _version(3, None, "release:r_42"),
]


def _render(number: int = 2, **overrides) -> str:
    renderer = SiteRenderer()
    kwargs = {
        "versions": VERSIONS,
        "diff_text": "--- a\n+++ b\n",
        "retired": False,
        "successor": None,
    }
    kwargs.update(overrides)
    return renderer.render_version_page(
        _tutorial(),
        _version(number, "2026-08-20T00:00:00Z", "feedback:8 則 找不到按鈕"),
        _steps(f"prepare-meeting@v{number}"),
        _content(),
        **kwargs,
    )


def test_esc_跳脫五個危險字元():
    assert esc("<script>") == "&lt;script&gt;"
    assert esc("a & b") == "a &amp; b"
    assert esc('say "hi"') == "say &quot;hi&quot;"
    assert esc("it's") == "it&#x27;s"
    assert esc(3) == "3"
    assert esc(None) == ""


def test_page_shell_有語言與字元集且不引外部_cdn():
    html = page_shell(
        title="測試頁",
        body="<p>內容</p>",
        notice="合成資料示範",
        data_batch="demo-seed-01",
        depth=1,
    )

    assert html.startswith("<!DOCTYPE html>")
    assert 'lang="zh-Hant"' in html
    assert 'charset="utf-8"' in html
    assert "../assets/style.css" in html
    assert "合成資料示範" in html
    assert "demo-seed-01" in html
    assert "cdn" not in html.lower()
    assert "http://" not in html and "https://" not in html


def test_page_shell_depth_0_用相對路徑():
    html = page_shell(
        title="索引", body="", notice="合成資料示範", data_batch="demo-seed-01", depth=0
    )
    assert 'href="assets/style.css"' in html
    assert "../assets" not in html


def test_asset_keys_都在_site_前綴底下():
    assert ASSET_KEYS == {
        "style": "site/assets/style.css",
        "widget": "site/assets/widget.js",
    }
    assert all(key.startswith("site/") for key in ASSET_KEYS.values())


def test_版本頁含五段內容():
    html = _render()

    assert "準備會議：在會議開始前拿到重點摘要" in html
    assert "問題" in html and "只能自己翻訊息" in html
    assert "前置條件" in html and "已登入工作區" in html
    assert "步驟" in html
    assert "預期結果" in html and "能在會議頁看到會前摘要" in html


def test_模型與使用者文字都被跳脫():
    html = _render()

    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "<script>alert(1)</script>" not in html
    assert "使用者找不到會前摘要 &amp; 只能自己翻訊息。" in html


def test_版本選擇只列出已發布版本且標記目前版():
    html = _render(number=2)

    assert 'href="v1.html"' in html
    assert "v2（目前）" in html
    assert 'href="v3.html"' not in html  # v3 尚未發布，不可公開


def test_v2_有差異連結():
    html = _render(number=2)

    assert 'href="v2.diff.txt"' in html
    assert "查看與 v1 的差異" in html


def test_v1_沒有差異連結而是說明文字():
    html = _render(number=1, diff_text="")

    assert "第一版，沒有前一版可比較" in html
    assert 'href="v1.diff.txt"' not in html


def test_有版本紀錄連結():
    html = _render()

    assert 'href="index.html"' in html
    assert "查看版本紀錄" in html


def test_頁面固定標示合成資料與資料批次():
    html = SiteRenderer(data_batch="demo-seed-09").render_version_page(
        _tutorial(),
        _version(2, "2026-08-20T00:00:00Z", "feedback:8 則 找不到按鈕"),
        _steps("prepare-meeting@v2"),
        _content(),
        versions=VERSIONS,
        diff_text="x",
        retired=False,
        successor=None,
    )

    assert "合成資料示範" in html
    assert "demo-seed-09" in html


def test_site_keys_路徑固定():
    assert site_keys("prepare-meeting", 2) == {
        "page": "site/prepare-meeting/v2.html",
        "diff": "site/prepare-meeting/v2.diff.txt",
        "index": "site/prepare-meeting/index.html",
        "root": "site/index.html",
    }
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：`uv run pytest tests/unit/test_site_version_page.py -v`

預期：FAIL，`ImportError: cannot import name 'esc' from 'training_kb.site'`（Phase 08 的最小版沒有這些模組層工具）。

- [ ] **步驟 3：寫最少的程式讓測試通過**

把 `src/training_kb/site.py` 的內容換成下面這份。**類別與函式名稱、參數都和 Phase 08 相同**，只是內容變完整；Task 2、4、5、6 會在這個基礎上繼續加。

```python
"""S3 靜態教學站的 HTML 產生器。

設計文件 F38：MVP 只提供 S3 靜態 docs 站，頁面包含版本化內容與 feedback widget。
設計文件 §17.2：所有不可信文字（模型輸出、使用者留言）都必須跳脫，
頁面不得載入外部 CDN，也不得包含任何金鑰。
"""

from __future__ import annotations

import html

from .models import (
    Tutorial,
    TutorialContent,
    TutorialStep,
    TutorialVersion,
    parse_version_id,
)

SITE_PREFIX = "site/"
ASSET_KEYS: dict[str, str] = {
    "style": "site/assets/style.css",
    "widget": "site/assets/widget.js",
}

STEP_TYPE_LABEL = {
    "click_ui": "點選介面",
    "input": "輸入資料",
    "read": "閱讀確認",
}


def esc(value: object) -> str:
    """把任何值轉成可安全放進 HTML 的字串。None 視為空字串。"""
    if value is None:
        return ""
    return html.escape(str(value), quote=True)


def _asset_href(name: str, depth: int) -> str:
    """組出資產的相對路徑。depth 是頁面在 site/ 底下的層數。"""
    prefix = "../" * depth
    return f"{prefix}assets/{name}"


def page_shell(
    *, title: str, body: str, notice: str, data_batch: str, depth: int
) -> str:
    """所有頁面共用的外框：固定標示、樣式、widget 腳本。

    不引用任何外部 CDN；style.css 與 widget.js 都來自同一個 site/assets/。
    """
    return (
        "<!DOCTYPE html>\n"
        '<html lang="zh-Hant">\n'
        "<head>\n"
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{esc(title)}</title>\n"
        f'<link rel="stylesheet" href="{_asset_href("style.css", depth)}">\n'
        "</head>\n"
        "<body>\n"
        '<div class="notice-bar">'
        f'<span class="tag">{esc(notice)}</span>'
        f'<span class="batch">資料批次：{esc(data_batch)}</span>'
        "</div>\n"
        f'<main class="page">\n{body}\n</main>\n'
        f'<script src="{_asset_href("widget.js", depth)}"></script>\n'
        "</body>\n"
        "</html>\n"
    )


def site_keys(slug: str, n: int) -> dict[str, str]:
    """一個版本在 site/ 底下會用到的四個 key。"""
    return {
        "page": f"{SITE_PREFIX}{slug}/v{n}.html",
        "diff": f"{SITE_PREFIX}{slug}/v{n}.diff.txt",
        "index": f"{SITE_PREFIX}{slug}/index.html",
        "root": f"{SITE_PREFIX}index.html",
    }


class SiteRenderer:
    """把教學版本轉成 HTML。

    data_batch 與 synthetic_notice 會固定顯示在每一頁上（設計文件 §11.5）。
    """

    def __init__(
        self,
        *,
        data_batch: str = "demo-seed-01",
        synthetic_notice: str = "合成資料示範",
    ) -> None:
        self.data_batch = data_batch
        self.synthetic_notice = synthetic_notice

    # ---------- 版本頁的各個區塊 ----------

    def _content_block(self, content: TutorialContent, steps: list[TutorialStep]) -> str:
        prerequisites = "".join(
            f"<li>{esc(item)}</li>" for item in content.prerequisites
        )
        ordered = sorted(steps, key=lambda step: step.index)
        rows = "".join(
            "<li>"
            f'<span class="step-type">{esc(STEP_TYPE_LABEL.get(str(step.type), str(step.type)))}</span>'
            f'<span class="step-text">{esc(step.text)}</span>'
            f'<span class="step-feature">功能：{esc(step.feature_id)}</span>'
            "</li>"
            for step in ordered
        )
        return (
            '<section class="content">\n'
            f"<h2>問題</h2>\n<p>{esc(content.problem)}</p>\n"
            f"<h2>前置條件</h2>\n<ul>{prerequisites}</ul>\n"
            f"<h2>步驟</h2>\n<ol class=\"steps\">{rows}</ol>\n"
            f"<h2>預期結果</h2>\n<p>{esc(content.expected_outcome)}</p>\n"
            "</section>"
        )

    def _version_picker(
        self, versions: list[TutorialVersion], current_version_id: str
    ) -> str:
        published = [v for v in versions if v.published_at]
        published.sort(key=lambda v: parse_version_id(v.version_id)[1])
        if not published:
            return '<p class="hint">尚無已發布版本。</p>'

        cells = []
        for version in published:
            _, number = parse_version_id(version.version_id)
            if version.version_id == current_version_id:
                cells.append(f'<span class="version current">v{number}（目前）</span>')
            else:
                cells.append(f'<a class="version" href="v{number}.html">v{number}</a>')
        return '<p class="version-picker">版本選擇：' + "".join(cells) + "</p>"

    def _links_block(self, number: int) -> str:
        if number <= 1:
            diff_part = '<span class="hint">第一版，沒有前一版可比較</span>'
        else:
            diff_part = (
                f'<a class="button" href="v{number}.diff.txt">'
                f"查看與 v{number - 1} 的差異</a>"
            )
        return (
            '<p class="links">'
            f"{diff_part}"
            '<a class="button" href="index.html">查看版本紀錄</a>'
            "</p>"
        )

    # ---------- 對外介面（簽名與 Phase 08 相同） ----------

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
        """產生一個版本的完整 HTML 頁面。"""
        _, number = parse_version_id(version.version_id)
        header = (
            '<header class="head">\n'
            f"<h1>{esc(content.title)}</h1>\n"
            f'<p class="meta"><span class="slug">{esc(tutorial.slug)}</span>'
            f'<span class="ver">版本：v{number}</span></p>\n'
            f'<p class="reason">改動原因：{esc(version.reason)}</p>\n'
            "</header>"
        )
        body = "\n".join(
            [
                header,
                self._content_block(content, steps),
                '<section class="nav">',
                self._version_picker(versions, version.version_id),
                self._links_block(number),
                "</section>",
            ]
        )
        return page_shell(
            title=f"{content.title}（v{number}）",
            body=body,
            notice=self.synthetic_notice,
            data_batch=self.data_batch,
            depth=1,
        )
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：`uv run pytest tests/unit/test_site_version_page.py -v`

預期：PASS，11 passed。

Phase 08 原本的測試也要重跑：

```bash
uv run pytest tests/unit -k site -v
```

預期：全部 PASS。若 Phase 08 的測試斷言了舊的 HTML 片段（例如只檢查 `"<h1>"` 存在），它應該仍然通過；若它斷言了現在不再出現的字串，把那個斷言改成新的區塊名稱。

- [ ] **步驟 5：commit**

```bash
git add src/training_kb/site.py tests/unit/test_site_version_page.py
git commit -m "feat(site): 版本頁加入版本選擇與差異連結"
```

---

### Task 2：回饋 widget 與記錄瀏覽按鈕的 HTML

**目的**：在版本頁加上評分、類別、留言、user ID 與兩個產生檔案的按鈕。

**檔案**：
- 修改：`src/training_kb/site.py`
- 測試：`tests/unit/test_site_widget_html.py`

**介面**：
- 產出（**本階段新增的私有方法，供 `render_version_page` 使用**）：
  - `SiteRenderer._feedback_widget(self, tutorial, version, *, retired) -> str`

**HTML 的三個約束**：

1. 所有動態值（slug、version_id、類別名稱）放在 `data-*` 屬性裡，而且一律過 `esc()`。
2. 沒有 `<form action=...>`，沒有 `method="post"`——widget 不會送出任何網路請求。
3. 退役時**完全不輸出表單元素**，只輸出一段說明文字（設計文件 F39）。

類別按鈕固定三個：`找不到按鈕`、`缺少資訊`、`未選擇`。前兩個是設計文件 D13 的初始核定類別；「未選擇」代表使用者不指定類別，產生的 JSON 裡 `category` 會是 `null`。

- [ ] **步驟 1：寫測試**

```python
# tests/unit/test_site_widget_html.py
"""Phase 22 Task 2：回饋 widget 與記錄瀏覽按鈕的 HTML。"""

from tests.unit.test_site_version_page import (  # 重用同一組測試資料
    VERSIONS,
    _content,
    _steps,
    _tutorial,
    _version,
)
from training_kb.site import SiteRenderer


def _render(*, retired: bool = False, successor: str | None = None) -> str:
    return SiteRenderer().render_version_page(
        _tutorial(status="retired" if retired else "active", successor=successor),
        _version(2, "2026-08-20T00:00:00Z", "feedback:8 則 找不到按鈕"),
        _steps("prepare-meeting@v2"),
        _content(),
        versions=VERSIONS,
        diff_text="--- a\n+++ b\n",
        retired=retired,
        successor=successor,
    )


def test_widget_有五個評分按鈕():
    html = _render()

    for score in range(1, 6):
        assert f'data-rating="{score}"' in html


def test_widget_有三個類別按鈕():
    html = _render()

    assert 'data-category="找不到按鈕"' in html
    assert 'data-category="缺少資訊"' in html
    assert 'data-category=""' in html  # 未選擇
    assert "未選擇" in html


def test_widget_有留言欄與使用者_id_欄():
    html = _render()

    assert 'id="tkb-comment"' in html
    assert 'id="tkb-user"' in html
    assert "請使用維護者提供的 ID" in html


def test_widget_有下載回饋與記錄瀏覽兩個按鈕():
    html = _render()

    assert "下載回饋檔案，交由維護者匯入" in html
    assert "記錄瀏覽" in html
    assert 'id="tkb-status"' in html


def test_widget_不送出任何網路請求():
    html = _render()

    assert "<form" not in html
    assert 'method="post"' not in html
    assert "fetch(" not in html
    assert "XMLHttpRequest" not in html


def test_widget_帶著版本與教學資訊():
    html = _render()

    assert 'data-version-id="prepare-meeting@v2"' in html
    assert 'data-slug="prepare-meeting"' in html
    assert 'data-retired="false"' in html


def test_退役版本完全沒有表單元素():
    html = _render(retired=True)

    assert "已退役，不接受新回饋" in html
    assert 'data-rating="1"' not in html
    assert 'id="tkb-comment"' not in html
    assert 'id="tkb-user"' not in html
    assert "下載回饋檔案，交由維護者匯入" not in html
    assert "<textarea" not in html
    assert "<input" not in html


def test_退役版本仍保留原文與版本選擇():
    html = _render(retired=True)

    assert "準備會議：在會議開始前拿到重點摘要" in html
    assert "版本選擇：" in html
    assert "查看版本紀錄" in html
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：`uv run pytest tests/unit/test_site_widget_html.py -v`

預期：FAIL，`AssertionError: assert 'data-rating="1"' in html`——目前的版本頁還沒有 widget。

- [ ] **步驟 3：寫最少的程式讓測試通過**

在 `src/training_kb/site.py` 的 `SiteRenderer` 類別內，`_links_block` 之後加入：

```python
    FEEDBACK_CATEGORIES = ("找不到按鈕", "缺少資訊")

    def _feedback_widget(
        self, tutorial: Tutorial, version: TutorialVersion, *, retired: bool
    ) -> str:
        """回饋 widget。退役版本只輸出說明文字，不輸出任何表單元素（F39）。"""
        if retired:
            return (
                '<section class="widget retired-widget">\n'
                "<p>此教學已退役，不接受新回饋。既有回饋仍保留供歷史查詢。</p>\n"
                "</section>"
            )

        ratings = "".join(
            f'<button type="button" class="rating" data-rating="{score}">{score}</button>'
            for score in range(1, 6)
        )
        categories = "".join(
            f'<button type="button" class="category" data-category="{esc(name)}">'
            f"{esc(name)}</button>"
            for name in self.FEEDBACK_CATEGORIES
        )
        categories += (
            '<button type="button" class="category" data-category="">未選擇</button>'
        )

        return (
            '<section class="widget" id="tkb-widget"'
            f' data-slug="{esc(tutorial.slug)}"'
            f' data-version-id="{esc(version.version_id)}"'
            ' data-retired="false"'
            f' data-notice="{esc(self.synthetic_notice)}">\n'
            "<h2>這篇有幫助嗎？</h2>\n"
            f'<p class="ratings">{ratings}</p>\n'
            f'<p class="categories">問題類別：{categories}</p>\n'
            '<p class="field"><label for="tkb-comment">留言（可留空）</label>'
            '<textarea id="tkb-comment" rows="3"></textarea></p>\n'
            '<p class="field"><label for="tkb-user">你的使用者 ID（必填，'
            '請使用維護者提供的 ID）</label>'
            '<input id="tkb-user" type="text" autocomplete="off"></p>\n'
            '<p class="actions">'
            '<button type="button" id="tkb-download">下載回饋檔案，交由維護者匯入</button>'
            '<button type="button" id="tkb-view">記錄瀏覽</button>'
            "</p>\n"
            '<p class="status" id="tkb-status"></p>\n'
            "</section>"
        )
```

接著修改 `render_version_page` 的 `body`，把 widget 加進去。把原本的：

```python
        body = "\n".join(
            [
                header,
                self._content_block(content, steps),
                '<section class="nav">',
                self._version_picker(versions, version.version_id),
                self._links_block(number),
                "</section>",
            ]
        )
```

換成：

```python
        body = "\n".join(
            [
                header,
                self._content_block(content, steps),
                '<section class="nav">',
                self._version_picker(versions, version.version_id),
                self._links_block(number),
                "</section>",
                self._feedback_widget(tutorial, version, retired=retired),
            ]
        )
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：`uv run pytest tests/unit/test_site_widget_html.py tests/unit/test_site_version_page.py -v`

預期：PASS，兩個檔案共 19 passed。

- [ ] **步驟 5：commit**

```bash
git add src/training_kb/site.py tests/unit/test_site_widget_html.py
git commit -m "feat(site): 加入回饋 widget 與記錄瀏覽按鈕"
```

---

### Task 3：widget.js 與 style.css

**目的**：寫出 widget 的行為與樣式。純 JavaScript，不引外部 CDN，不含任何金鑰。

**檔案**：
- 新增：`demo/site_assets/widget.js`
- 新增：`demo/site_assets/style.css`
- 測試：`tests/unit/test_site_assets.py`

**介面**：
- 產出（檔案本身，由 Task 6 的 `publish_site_assets()` 上傳到 `site/assets/`）

**widget.js 必須遵守的五件事**：

1. 只用 `textContent` 放文字，**完全不出現 `innerHTML`**。
2. 不發任何網路請求：沒有 `fetch`、沒有 `XMLHttpRequest`、沒有 `WebSocket`。
3. 沒有任何金鑰、帳號、AWS 資源名稱。
4. user ID 是必填。空白時顯示提示，不產生檔案（設計文件 §13：「缺少 ID 時要求補入，不能用瀏覽器隨機 ID」）。
5. 下載後只顯示「檔案已產生，尚未送出」，**絕不顯示「已送出」或「已保存」**（設計文件 §13）。

**Feedback ID 的組法**：`f_site-<slug>-v<n>-<user>-<epoch 秒>`。必須以 `f_` 開頭（設計文件 O6：手動匯入檔必須自帶 `f_` ID）。`slug` 與 `user` 先過一層白名單過濾，只留 `A-Za-z0-9_-`，避免 ID 裡混入奇怪字元。

- [ ] **步驟 1：寫測試**

```python
# tests/unit/test_site_assets.py
"""Phase 22 Task 3：widget.js 與 style.css 的安全性與內容檢查。"""

import re
from pathlib import Path

ASSETS = Path(__file__).resolve().parents[2] / "demo" / "site_assets"
WIDGET = ASSETS / "widget.js"
STYLE = ASSETS / "style.css"


def test_兩個資產檔都存在():
    assert WIDGET.is_file()
    assert STYLE.is_file()


def test_widget_不使用_innerHTML():
    source = WIDGET.read_text(encoding="utf-8")

    assert "innerHTML" not in source
    assert "outerHTML" not in source
    assert "insertAdjacentHTML" not in source
    assert "document.write" not in source


def test_widget_不發任何網路請求():
    source = WIDGET.read_text(encoding="utf-8")

    assert "fetch(" not in source
    assert "XMLHttpRequest" not in source
    assert "WebSocket" not in source
    assert "navigator.sendBeacon" not in source


def test_widget_不引用外部資源也不含金鑰():
    source = WIDGET.read_text(encoding="utf-8")

    assert "http://" not in source
    assert "https://" not in source
    assert "cdn" not in source.lower()
    assert not re.search(r"AKIA[0-9A-Z]{16}", source)
    assert "aws_secret" not in source.lower()
    assert "amazonaws" not in source.lower()


def test_widget_產生的_id_以_f_開頭():
    source = WIDGET.read_text(encoding="utf-8")

    assert '"f_site-"' in source or "'f_site-'" in source


def test_widget_要求使用者_id_必填():
    source = WIDGET.read_text(encoding="utf-8")

    assert "請先填入穩定使用者 ID" in source


def test_widget_只說檔案已產生不說已送出():
    source = WIDGET.read_text(encoding="utf-8")

    assert "檔案已產生，尚未送出" in source
    assert "已送出" not in source.replace("尚未送出", "")
    assert "已保存" not in source


def test_widget_同時支援回饋與瀏覽兩種檔案():
    source = WIDGET.read_text(encoding="utf-8")

    assert '"feedback"' in source
    assert '"view"' in source
    assert "tkb-download" in source
    assert "tkb-view" in source


def test_style_不引用外部字型或圖片():
    source = STYLE.read_text(encoding="utf-8")

    assert "@import" not in source
    assert "http://" not in source
    assert "https://" not in source
    assert "url(" not in source


def test_style_有本階段用到的_class():
    source = STYLE.read_text(encoding="utf-8")

    for name in (
        ".notice-bar",
        ".page",
        ".steps",
        ".version-picker",
        ".widget",
        ".retired-banner",
        ".status",
    ):
        assert name in source
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：`uv run pytest tests/unit/test_site_assets.py -v`

預期：FAIL，`AssertionError: assert False`（`WIDGET.is_file()` 是 False，檔案還不存在）。

- [ ] **步驟 3：寫最少的程式讓測試通過**

建立 `demo/site_assets/widget.js`：

```javascript
/* Training KB 教學站的回饋 widget。
 *
 * 設計文件 §13：Feedback 走手動上傳。widget 只在瀏覽器裡產生檔案，
 * 不送出任何網路請求，下載後顯示「檔案已產生，尚未送出」。
 * 設計文件 §17.2：不引用外部資源、不包含任何金鑰、
 * 放使用者文字時只用 textContent，不用 innerHTML。
 */
(function () {
  "use strict";

  var widget = document.getElementById("tkb-widget");
  if (!widget) {
    return;
  }

  var slug = widget.getAttribute("data-slug") || "";
  var versionId = widget.getAttribute("data-version-id") || "";
  var notice = widget.getAttribute("data-notice") || "合成資料示範";
  var isRetired = widget.getAttribute("data-retired") === "true";

  var statusNode = document.getElementById("tkb-status");
  var commentNode = document.getElementById("tkb-comment");
  var userNode = document.getElementById("tkb-user");
  var downloadButton = document.getElementById("tkb-download");
  var viewButton = document.getElementById("tkb-view");

  var selectedRating = 0;
  var selectedCategory = "";

  function setStatus(message) {
    if (statusNode) {
      statusNode.textContent = message;
    }
  }

  function safeToken(value) {
    return String(value).replace(/[^A-Za-z0-9_-]/g, "");
  }

  function nowIso() {
    return new Date().toISOString().replace(/\.\d{3}Z$/, "Z");
  }

  function readUser() {
    return userNode ? userNode.value.trim() : "";
  }

  function download(fileName, payload) {
    var text = JSON.stringify(payload, null, 2);
    var blob = new Blob([text], { type: "application/json;charset=utf-8" });
    var url = URL.createObjectURL(blob);
    var link = document.createElement("a");
    link.href = url;
    link.download = fileName;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  }

  function envelope(kind, items) {
    return {
      kind: kind,
      source: "site_widget",
      generated_at: nowIso(),
      note: notice + "｜此檔尚未送出，需由維護者匯入",
      items: items
    };
  }

  function bindRatingButtons() {
    var buttons = document.querySelectorAll("button.rating");
    for (var i = 0; i < buttons.length; i += 1) {
      (function (button) {
        button.addEventListener("click", function () {
          selectedRating = parseInt(button.getAttribute("data-rating"), 10);
          for (var j = 0; j < buttons.length; j += 1) {
            buttons[j].classList.remove("selected");
          }
          button.classList.add("selected");
          setStatus("已選擇評分 " + selectedRating + " 分。");
        });
      })(buttons[i]);
    }
  }

  function bindCategoryButtons() {
    var buttons = document.querySelectorAll("button.category");
    for (var i = 0; i < buttons.length; i += 1) {
      (function (button) {
        button.addEventListener("click", function () {
          selectedCategory = button.getAttribute("data-category") || "";
          for (var j = 0; j < buttons.length; j += 1) {
            buttons[j].classList.remove("selected");
          }
          button.classList.add("selected");
          if (selectedCategory === "") {
            setStatus("問題類別：未選擇。");
          } else {
            setStatus("已選擇問題類別。");
          }
        });
      })(buttons[i]);
    }
  }

  function buildFeedbackItem(user) {
    var comment = commentNode ? commentNode.value.trim() : "";
    var stamp = Math.floor(Date.now() / 1000);
    return {
      id: "f_site-" + safeToken(slug) + "-" + safeToken(user) + "-" + stamp,
      tutorial_version: versionId,
      rating: selectedRating,
      user: user,
      category: selectedCategory === "" ? null : selectedCategory,
      comment: comment === "" ? null : comment,
      ts: nowIso()
    };
  }

  function onDownloadFeedback() {
    var user = readUser();
    if (user === "") {
      setStatus("請先填入穩定使用者 ID，才能產生回饋檔案。");
      return;
    }
    if (selectedRating < 1 || selectedRating > 5) {
      setStatus("請先選擇 1 到 5 的評分。");
      return;
    }
    var payload = envelope("feedback", [buildFeedbackItem(user)]);
    download("feedback-" + safeToken(slug) + "-" + Date.now() + ".json", payload);
    setStatus("檔案已產生，尚未送出。請把檔案交給維護者匯入。");
  }

  function onDownloadView() {
    var user = readUser();
    if (user === "") {
      setStatus("請先填入穩定使用者 ID，才能產生瀏覽紀錄檔案。");
      return;
    }
    var payload = envelope("view", [
      { tutorial_version: versionId, user: user, ts: nowIso() }
    ]);
    download("view-" + safeToken(slug) + "-" + Date.now() + ".json", payload);
    setStatus("檔案已產生，尚未送出。請把檔案交給維護者匯入。");
  }

  if (isRetired) {
    return;
  }

  bindRatingButtons();
  bindCategoryButtons();
  if (downloadButton) {
    downloadButton.addEventListener("click", onDownloadFeedback);
  }
  if (viewButton) {
    viewButton.addEventListener("click", onDownloadView);
  }
})();
```

建立 `demo/site_assets/style.css`：

```css
/* Training KB 教學站樣式。不引用外部字型、圖片或 @import。 */

:root {
  --ink: #1d2330;
  --muted: #5b6376;
  --line: #d9dee8;
  --bg: #ffffff;
  --soft: #f4f6fa;
  --warn-bg: #fdf3e3;
  --warn-line: #d9a441;
}

body {
  margin: 0;
  color: var(--ink);
  background: var(--bg);
  font-family: system-ui, "Noto Sans TC", "PingFang TC", "Microsoft JhengHei", sans-serif;
  line-height: 1.7;
}

.notice-bar {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  padding: 8px 16px;
  background: var(--warn-bg);
  border-bottom: 1px solid var(--warn-line);
  font-size: 14px;
}

.notice-bar .tag {
  font-weight: 700;
}

.notice-bar .batch {
  color: var(--muted);
}

.page {
  max-width: 760px;
  margin: 0 auto;
  padding: 24px 16px 64px;
}

.head h1 {
  margin: 0 0 8px;
  font-size: 26px;
}

.head .meta {
  margin: 0;
  color: var(--muted);
  font-size: 14px;
}

.head .meta span + span {
  margin-left: 16px;
}

.head .reason {
  margin: 4px 0 0;
  color: var(--muted);
  font-size: 14px;
}

.content h2 {
  margin: 28px 0 8px;
  font-size: 18px;
  border-left: 4px solid var(--line);
  padding-left: 8px;
}

.steps {
  padding-left: 20px;
}

.steps li {
  margin-bottom: 12px;
}

.steps .step-type {
  display: inline-block;
  min-width: 72px;
  margin-right: 8px;
  padding: 1px 6px;
  background: var(--soft);
  border: 1px solid var(--line);
  border-radius: 4px;
  font-size: 12px;
  color: var(--muted);
}

.steps .step-feature {
  display: block;
  margin-top: 2px;
  font-size: 12px;
  color: var(--muted);
}

.nav {
  margin-top: 32px;
  padding-top: 16px;
  border-top: 1px solid var(--line);
}

.version-picker .version {
  display: inline-block;
  margin-right: 8px;
  padding: 2px 10px;
  border: 1px solid var(--line);
  border-radius: 4px;
  text-decoration: none;
  color: var(--ink);
}

.version-picker .version.current {
  background: var(--soft);
  font-weight: 700;
}

.links .button {
  display: inline-block;
  margin-right: 8px;
  padding: 6px 12px;
  border: 1px solid var(--line);
  border-radius: 4px;
  text-decoration: none;
  color: var(--ink);
}

.links .hint,
.hint {
  color: var(--muted);
  font-size: 14px;
}

.retired-banner {
  margin: 16px 0;
  padding: 12px 16px;
  background: var(--warn-bg);
  border: 1px solid var(--warn-line);
  border-radius: 6px;
}

.retired-banner h2 {
  margin: 0 0 4px;
  font-size: 18px;
}

.retired-banner p {
  margin: 4px 0;
}

.widget {
  margin-top: 32px;
  padding: 16px;
  background: var(--soft);
  border: 1px solid var(--line);
  border-radius: 6px;
}

.widget h2 {
  margin: 0 0 8px;
  font-size: 18px;
}

.widget button {
  margin-right: 6px;
  padding: 6px 12px;
  border: 1px solid var(--line);
  border-radius: 4px;
  background: var(--bg);
  color: var(--ink);
  cursor: pointer;
  font: inherit;
}

.widget button.selected {
  background: var(--ink);
  color: var(--bg);
}

.widget .field label {
  display: block;
  margin-bottom: 4px;
  font-size: 14px;
  color: var(--muted);
}

.widget textarea,
.widget input[type="text"] {
  width: 100%;
  box-sizing: border-box;
  padding: 6px 8px;
  border: 1px solid var(--line);
  border-radius: 4px;
  font: inherit;
}

.status {
  min-height: 1.7em;
  margin: 8px 0 0;
  font-size: 14px;
  color: var(--muted);
}

.tutorial-list {
  padding-left: 20px;
}

.tutorial-list li {
  margin-bottom: 8px;
}

.tutorial-list .retired-mark {
  margin-left: 8px;
  font-size: 12px;
  color: var(--warn-line);
}
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：`uv run pytest tests/unit/test_site_assets.py -v`

預期：PASS，10 passed。

- [ ] **步驟 5：commit**

```bash
git add demo/site_assets/widget.js demo/site_assets/style.css tests/unit/test_site_assets.py
git commit -m "feat(site): 新增教學站 widget 與樣式資產"
```

---

### Task 4：退役頁與後繼教學連結

**目的**：退役的教學要顯示過期說明、保留原文、有後繼才顯示可點連結，而且不自動跳轉。

**檔案**：
- 修改：`src/training_kb/site.py`
- 測試：`tests/unit/test_site_retired.py`

**介面**：
- 產出（**本階段新增的私有方法**）：
  - `SiteRenderer._retired_banner(self, tutorial, version, *, successor) -> str`
  - `SiteRenderer._retire_reason_text(self, version) -> str`

**過期原因從哪裡來（本計劃選擇）**：

`render_version_page` 的簽名固定，沒有「退役原因」這個參數，`Tutorial` 模型也沒有這個欄位。本階段從 `version.reason` 推出一句白話說明：

| `version.reason` 開頭 | 顯示的原因 |
|---|---|
| `release:` | 「產品改版（`<id>`）後此教學已過期。」 |
| `feedback:` | 「此教學已過期，內容不再更新。」 |
| `gap:` 或其他 | 「此教學已過期，內容不再更新。」 |

這是**本計劃選擇**：在 `Tutorial` 加一個 `retire_reason` 欄位會更精準，但那要動 Phase 02 的模型與 Phase 08 的 `retire()`，超出本階段範圍。文件在這裡記下這個取捨，留給後續評估。

**三條硬規則**：

1. **不自動跳轉**：頁面不得出現 `<meta http-equiv="refresh">`，也不得有任何 `location.href = ...`（設計文件 §8.4：「後繼連結優先採明確可點的提示，不做連續自動跳轉」）。
2. **successor 指向自己就不顯示連結**：避免產生循環導向（設計文件 §8.4：設定時檢查存在、可公開、非自身且不形成循環）。
3. **原文一字不改**：退役只是加一段橫幅，五段內容照樣輸出（設計文件 F19）。

- [ ] **步驟 1：寫測試**

```python
# tests/unit/test_site_retired.py
"""Phase 22 Task 4：退役頁與後繼教學連結。"""

from tests.unit.test_site_version_page import (
    VERSIONS,
    _content,
    _steps,
    _tutorial,
    _version,
)
from training_kb.site import SiteRenderer


def _render(
    *,
    retired: bool = True,
    successor: str | None = None,
    reason: str = "release:r_42",
) -> str:
    return SiteRenderer().render_version_page(
        _tutorial(status="retired" if retired else "active", successor=successor),
        _version(2, "2026-08-20T00:00:00Z", reason),
        _steps("prepare-meeting@v2"),
        _content(),
        versions=VERSIONS,
        diff_text="--- a\n+++ b\n",
        retired=retired,
        successor=successor,
    )


def test_退役頁顯示已過期與原因():
    html = _render(reason="release:r_42")

    assert "此教學已過期" in html
    assert "產品改版（r_42）後此教學已過期。" in html
    assert "以下原文保留供查閱，內容不再更新。" in html


def test_非_release_原因用通用說明():
    html = _render(reason="feedback:8 則 找不到按鈕")

    assert "此教學已過期" in html
    assert "產品改版" not in html


def test_退役頁保留原文():
    html = _render()

    assert "準備會議：在會議開始前拿到重點摘要" in html
    assert "使用者找不到會前摘要 &amp; 只能自己翻訊息。" in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html


def test_有後繼時顯示可點連結():
    html = _render(successor="share-summary")

    assert "後繼教學" in html
    assert 'href="../share-summary/index.html"' in html
    assert "share-summary" in html


def test_沒有後繼時不顯示連結():
    html = _render(successor=None)

    assert "後繼教學" not in html
    assert "../share-summary/index.html" not in html


def test_successor_指向自己時不顯示連結():
    html = _render(successor="prepare-meeting")

    assert "後繼教學" not in html
    assert 'href="../prepare-meeting/index.html"' not in html


def test_退役頁不自動跳轉():
    html = _render(successor="share-summary")

    assert "http-equiv" not in html
    assert "refresh" not in html.lower()
    assert "location.href" not in html
    assert "location.replace" not in html


def test_未退役時沒有過期橫幅():
    html = _render(retired=False)

    assert "此教學已過期" not in html
    assert "retired-banner" not in html


def test_退役頁的_widget_顯示停用說明():
    html = _render()

    assert "此教學已退役，不接受新回饋。" in html
    assert "既有回饋仍保留供歷史查詢。" in html
    assert 'data-rating="3"' not in html
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：`uv run pytest tests/unit/test_site_retired.py -v`

預期：FAIL，`AssertionError: assert '此教學已過期' in html`——目前還沒有退役橫幅。

- [ ] **步驟 3：寫最少的程式讓測試通過**

在 `src/training_kb/site.py` 的 `SiteRenderer` 類別內，`_feedback_widget` 之後加入：

```python
    def _retire_reason_text(self, version: TutorialVersion) -> str:
        """把版本的 reason 轉成給讀者看的過期說明（本計劃選擇）。"""
        reason = version.reason or ""
        if reason.startswith("release:"):
            release_id = reason.split(":", 1)[1].strip()
            return f"產品改版（{release_id}）後此教學已過期。"
        return "此教學已過期，內容不再更新。"

    def _retired_banner(
        self, tutorial: Tutorial, version: TutorialVersion, *, successor: str | None
    ) -> str:
        """退役橫幅。不自動跳轉，只提供明確可點的後繼連結（設計文件 §8.4）。"""
        parts = [
            '<section class="retired-banner">',
            "<h2>此教學已過期</h2>",
            f"<p>原因：{esc(self._retire_reason_text(version))}</p>",
            "<p>以下原文保留供查閱，內容不再更新。</p>",
        ]
        # successor 指向自己會形成循環導向，直接不顯示連結。
        if successor and successor != tutorial.slug:
            parts.append(
                '<p>後繼教學：'
                f'<a href="../{esc(successor)}/index.html">{esc(successor)}</a></p>'
            )
        parts.append("</section>")
        return "\n".join(parts)
```

接著把 `render_version_page` 的 `body` 再改一次，加入退役橫幅。把：

```python
        body = "\n".join(
            [
                header,
                self._content_block(content, steps),
                '<section class="nav">',
                self._version_picker(versions, version.version_id),
                self._links_block(number),
                "</section>",
                self._feedback_widget(tutorial, version, retired=retired),
            ]
        )
```

換成：

```python
        blocks = [header]
        if retired:
            blocks.append(
                self._retired_banner(tutorial, version, successor=successor)
            )
        blocks.extend(
            [
                self._content_block(content, steps),
                '<section class="nav">',
                self._version_picker(versions, version.version_id),
                self._links_block(number),
                "</section>",
                self._feedback_widget(tutorial, version, retired=retired),
            ]
        )
        body = "\n".join(blocks)
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：`uv run pytest tests/unit/test_site_retired.py -v`

預期：PASS，9 passed。

- [ ] **步驟 5：commit**

```bash
git add src/training_kb/site.py tests/unit/test_site_retired.py
git commit -m "feat(site): 加入退役頁與後繼教學連結"
```

---

### Task 5：教學索引頁與站台首頁

**目的**：`render_tutorial_index()` 列出某篇教學的版本紀錄；`render_site_index()` 列出所有教學。

**檔案**：
- 修改：`src/training_kb/site.py`
- 測試：`tests/unit/test_site_index.py`

**介面**：
- 產出（簽名與 Phase 08 相同）：
  - `SiteRenderer.render_tutorial_index(self, tutorial, versions) -> str`
  - `SiteRenderer.render_site_index(self, tutorials) -> str`

**兩個頁面的規則**：

1. **只列出已發布版本**。`published_at` 是 `None` 的版本不可公開（設計文件 F36、O3）。
2. 教學索引依版本號**由新到舊**排列，標出目前版本。
3. 站台首頁依 slug 排序，退役的教學標記「已過期」但仍列出（設計文件 §8.4：保留歷史原文）。
4. 沒有任何已發布版本的教學，在首頁顯示但不給連結。

- [ ] **步驟 1：寫測試**

```python
# tests/unit/test_site_index.py
"""Phase 22 Task 5：教學索引頁與站台首頁。"""

from tests.unit.test_site_version_page import _version
from training_kb.models import Tutorial
from training_kb.site import SiteRenderer

VERSIONS = [
    _version(1, "2026-08-01T00:00:00Z", "gap:c12"),
    _version(2, "2026-08-20T00:00:00Z", "feedback:8 則 找不到按鈕"),
    _version(3, None, "release:r_42"),
]


def _tutorial(
    slug: str,
    *,
    status: str = "active",
    current: str | None = "prepare-meeting@v2",
    topic: str = "準備會議",
) -> Tutorial:
    return Tutorial(
        slug=slug,
        current_version=current,
        topic=topic,
        feature_ids=["Prepare"],
        status=status,
        successor=None,
        cluster_id="c12",
    )


def test_教學索引列出已發布版本且由新到舊():
    html = SiteRenderer().render_tutorial_index(_tutorial("prepare-meeting"), VERSIONS)

    assert html.index("v2.html") < html.index("v1.html")
    assert "v3" not in html.replace("v3.html", "")  # v3 未發布，完全不出現
    assert "2026-08-20T00:00:00Z" in html
    assert "feedback:8 則 找不到按鈕" in html


def test_教學索引標出目前版本():
    html = SiteRenderer().render_tutorial_index(_tutorial("prepare-meeting"), VERSIONS)

    assert "目前版本" in html


def test_教學索引沒有已發布版本時顯示說明():
    html = SiteRenderer().render_tutorial_index(
        _tutorial("draft-only", current=None), [_version(1, None, "gap:c99")]
    )

    assert "尚無已發布版本" in html
    assert "v1.html" not in html


def test_站台首頁列出所有教學並依_slug_排序():
    tutorials = [
        _tutorial("share-summary", topic="分享摘要"),
        _tutorial("notification-settings", topic="設定通知"),
        _tutorial("prepare-meeting", topic="準備會議"),
    ]

    html = SiteRenderer().render_site_index(tutorials)

    assert html.index("notification-settings") < html.index("prepare-meeting")
    assert html.index("prepare-meeting") < html.index("share-summary")
    assert "分享摘要" in html and "設定通知" in html and "準備會議" in html


def test_站台首頁標記退役教學但仍列出():
    tutorials = [
        _tutorial("prepare-meeting"),
        _tutorial("old-flow", status="retired", topic="舊流程"),
    ]

    html = SiteRenderer().render_site_index(tutorials)

    assert "舊流程" in html
    assert "已過期" in html


def test_站台首頁對沒有目前版本的教學不給連結():
    tutorials = [_tutorial("draft-only", current=None, topic="草稿")]

    html = SiteRenderer().render_site_index(tutorials)

    assert "草稿" in html
    assert "尚未發布" in html
    assert 'href="draft-only/' not in html


def test_兩個索引頁都標示合成資料與資料批次():
    renderer = SiteRenderer(data_batch="demo-seed-07")

    tutorial_index = renderer.render_tutorial_index(_tutorial("prepare-meeting"), VERSIONS)
    site_index = renderer.render_site_index([_tutorial("prepare-meeting")])

    for html in (tutorial_index, site_index):
        assert "合成資料示範" in html
        assert "demo-seed-07" in html


def test_首頁的資產路徑不帶上層目錄():
    html = SiteRenderer().render_site_index([_tutorial("prepare-meeting")])

    assert 'href="assets/style.css"' in html
    assert "../assets" not in html


def test_索引頁的文字都被跳脫():
    tutorials = [_tutorial("prepare-meeting", topic="準備 <b>會議</b>")]

    html = SiteRenderer().render_site_index(tutorials)

    assert "準備 &lt;b&gt;會議&lt;/b&gt;" in html
    assert "<b>會議</b>" not in html
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：`uv run pytest tests/unit/test_site_index.py -v`

預期：FAIL。Phase 08 的最小版可能已有這兩個方法，但不會通過「由新到舊」「未發布不出現」等斷言，錯誤是 `AssertionError`。

- [ ] **步驟 3：寫最少的程式讓測試通過**

在 `src/training_kb/site.py` 的 `SiteRenderer` 類別內，`render_version_page` 之後加入：

```python
    def render_tutorial_index(
        self, tutorial: Tutorial, versions: list[TutorialVersion]
    ) -> str:
        """某篇教學的版本紀錄頁：只列已發布版本，由新到舊。"""
        published = [v for v in versions if v.published_at]
        published.sort(key=lambda v: parse_version_id(v.version_id)[1], reverse=True)

        if published:
            rows = []
            for version in published:
                _, number = parse_version_id(version.version_id)
                mark = (
                    '<span class="retired-mark">目前版本</span>'
                    if version.version_id == tutorial.current_version
                    else ""
                )
                rows.append(
                    "<li>"
                    f'<a href="v{number}.html">v{number}</a>{mark}'
                    f'<span class="hint">　發布時間：{esc(version.published_at)}</span>'
                    f'<span class="hint">　原因：{esc(version.reason)}</span>'
                    "</li>"
                )
            listing = f'<ol class="tutorial-list">{"".join(rows)}</ol>'
        else:
            listing = '<p class="hint">尚無已發布版本。</p>'

        status_note = (
            '<p class="hint">此教學已過期，內容保留供查閱。</p>'
            if str(tutorial.status) == "retired"
            else ""
        )
        body = (
            '<header class="head">\n'
            f"<h1>{esc(tutorial.topic)}　版本紀錄</h1>\n"
            f'<p class="meta"><span class="slug">{esc(tutorial.slug)}</span></p>\n'
            f"{status_note}\n"
            "</header>\n"
            f'<section class="content">{listing}</section>\n'
            '<p class="links"><a class="button" href="../index.html">回到教學清單</a></p>'
        )
        return page_shell(
            title=f"{tutorial.topic}　版本紀錄",
            body=body,
            notice=self.synthetic_notice,
            data_batch=self.data_batch,
            depth=1,
        )

    def render_site_index(self, tutorials: list[Tutorial]) -> str:
        """站台首頁：列出所有教學，依 slug 排序。"""
        rows = []
        for tutorial in sorted(tutorials, key=lambda item: item.slug):
            retired = str(tutorial.status) == "retired"
            mark = '<span class="retired-mark">已過期</span>' if retired else ""
            if tutorial.current_version:
                _, number = parse_version_id(tutorial.current_version)
                link = (
                    f'<a href="{esc(tutorial.slug)}/v{number}.html">'
                    f"{esc(tutorial.topic)}</a>"
                    f'<span class="hint">　'
                    f'<a href="{esc(tutorial.slug)}/index.html">版本紀錄</a></span>'
                )
            else:
                link = (
                    f"{esc(tutorial.topic)}"
                    '<span class="hint">　尚未發布，暫無可閱讀的版本</span>'
                )
            rows.append(
                f'<li>{link}{mark}'
                f'<span class="hint">　{esc(tutorial.slug)}</span></li>'
            )

        body = (
            '<header class="head">\n'
            "<h1>教學清單</h1>\n"
            '<p class="meta">本站只提供已發布的教學版本。</p>\n'
            "</header>\n"
            f'<section class="content"><ul class="tutorial-list">{"".join(rows)}</ul></section>'
        )
        return page_shell(
            title="教學清單",
            body=body,
            notice=self.synthetic_notice,
            data_batch=self.data_batch,
            depth=0,
        )
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：`uv run pytest tests/unit/test_site_index.py -v`

預期：PASS，9 passed。

- [ ] **步驟 5：commit**

```bash
git add src/training_kb/site.py tests/unit/test_site_index.py
git commit -m "feat(site): 完成教學索引頁與站台首頁"
```

---

### Task 6：publish_to_site 同時複製資產

**目的**：發布時一次寫齊「版本頁、公開 diff、教學索引、站台首頁、資產」五種檔案。

**檔案**：
- 修改：`src/training_kb/site.py`
- 測試：`tests/integration/test_site_publish.py`

**介面**：
- 消費（Phase 03）：`repo.put_object(key, body, *, content_type)`、`repo.get_object(key)`
- 消費（Phase 09）：`repo.get_tutorial`、`repo.get_version`、`repo.get_steps`、`repo.list_versions_of_tutorial`、`repo.list_tutorials`
- 產出（簽名與 Phase 08 相同）：`site.publish_to_site(repo, renderer, slug, version_id) -> list[str]`
- 產出（**簡報第 6 節未列，本階段新增**）：
  - `site.ASSETS_DIR`（`Path`，指向 `demo/site_assets`）
  - `site.publish_site_assets(repo, assets_dir=None) -> list[str]`
  - `site.parse_version_markdown(md, steps) -> TutorialContent`

**`repo.list_tutorials()` 從哪裡來**：Phase 09 的固定讀取清單裡有 `scan_entity("TUTORIAL")`。若 `Repository` 還沒有 `list_tutorials()`，用下面這行實作在 `repository.py`（一行就夠，不需要新測試檔）：

```python
    def list_tutorials(self) -> list[Tutorial]:
        return [Tutorial.model_validate(item) for item in self.scan_entity("TUTORIAL")]
```

**`parse_version_markdown` 為什麼需要**：`publish_to_site` 要重建 `TutorialContent` 才能渲染頁面。步驟的 `type` 與 `feature_id` 在 DynamoDB 的 STEP item 裡是權威資料，但 Title／Problem／Prerequisites／Expected Outcome 只存在 S3 的 `.md`。所以本函式用 `render_markdown()` 的固定格式反向解析那四段，步驟則直接取 DynamoDB 的 `steps`。

**Content-Type 要對**：`.html` 用 `text/html; charset=utf-8`、`.css` 用 `text/css; charset=utf-8`、`.js` 用 `text/javascript; charset=utf-8`、`.diff.txt` 用 `text/plain; charset=utf-8`。S3 website endpoint 會照這個標頭回傳，錯了瀏覽器會把 HTML 當成檔案下載。

- [ ] **步驟 1：寫測試**

```python
# tests/integration/test_site_publish.py
"""Phase 22 Task 6：publish_to_site 寫齊所有公開檔案與資產。"""

from moto import mock_aws

from demo.seed_loader import SEED_DIR, load_features, load_tutorials
from training_kb.clock import parse_iso
from training_kb.site import (
    ASSET_KEYS,
    SiteRenderer,
    publish_site_assets,
    publish_to_site,
    site_keys,
)

NOW = parse_iso("2026-09-13T12:00:00Z")


def _seed(repository) -> None:
    load_features(repository, SEED_DIR / "features.json")
    load_tutorials(repository, SEED_DIR / "tutorials", SiteRenderer(), NOW)


@mock_aws
def test_發布後五種檔案都在(repository):
    _seed(repository)

    keys = publish_to_site(repository, SiteRenderer(), "prepare-meeting", "prepare-meeting@v2")

    expected = site_keys("prepare-meeting", 2)
    assert expected["page"] in keys
    assert expected["diff"] in keys
    assert expected["index"] in keys
    assert expected["root"] in keys
    assert ASSET_KEYS["style"] in keys
    assert ASSET_KEYS["widget"] in keys

    for key in keys:
        assert repository.object_exists(key)


@mock_aws
def test_公開檔案全部在_site_前綴底下(repository):
    _seed(repository)

    keys = publish_to_site(repository, SiteRenderer(), "prepare-meeting", "prepare-meeting@v2")

    assert all(key.startswith("site/") for key in keys)


@mock_aws
def test_版本頁內容正確且已跳脫(repository):
    _seed(repository)
    publish_to_site(repository, SiteRenderer(), "prepare-meeting", "prepare-meeting@v2")

    page = repository.get_object(site_keys("prepare-meeting", 2)["page"]).decode("utf-8")

    assert "準備會議：在會議開始前拿到重點摘要" in page
    assert "在會議頁面右上角的工具列" in page
    assert "合成資料示範" in page
    assert 'href="v1.html"' in page
    assert 'href="v2.diff.txt"' in page


@mock_aws
def test_公開_diff_與私有_diff_內容相同(repository):
    _seed(repository)
    publish_to_site(repository, SiteRenderer(), "prepare-meeting", "prepare-meeting@v2")

    public = repository.get_object(site_keys("prepare-meeting", 2)["diff"])
    private = repository.get_object("tutorials/prepare-meeting/v2.diff")

    assert public == private


@mock_aws
def test_未發布版本不會被寫進_site(repository):
    _seed(repository)
    publish_to_site(repository, SiteRenderer(), "prepare-meeting", "prepare-meeting@v2")

    page = repository.get_object(site_keys("prepare-meeting", 2)["page"]).decode("utf-8")
    index = repository.get_object(site_keys("prepare-meeting", 2)["index"]).decode("utf-8")

    assert "v3.html" not in page
    assert "v3.html" not in index


@mock_aws
def test_站台首頁列出三篇教學(repository):
    _seed(repository)
    publish_to_site(repository, SiteRenderer(), "prepare-meeting", "prepare-meeting@v2")

    root = repository.get_object("site/index.html").decode("utf-8")

    assert "準備會議" in root
    assert "分享摘要" in root
    assert "設定通知" in root


@mock_aws
def test_資產可以單獨上傳且內容與原檔相同(repository):
    keys = publish_site_assets(repository)

    assert keys == [ASSET_KEYS["style"], ASSET_KEYS["widget"]]

    from pathlib import Path

    assets = Path(__file__).resolve().parents[2] / "demo" / "site_assets"
    assert repository.get_object(ASSET_KEYS["widget"]).decode("utf-8") == (
        (assets / "widget.js").read_text(encoding="utf-8")
    )


@mock_aws
def test_html_的_content_type_正確(repository):
    """repository.s3 與 repository.bucket 是 Phase 03 的 Repository.__init__
    收下的兩個參數（`def __init__(self, table, s3, bucket: str)`）。
    若你在 Phase 03 把它們存成別的屬性名，改成對應的名稱即可。"""
    _seed(repository)
    publish_to_site(repository, SiteRenderer(), "prepare-meeting", "prepare-meeting@v2")

    head = repository.s3.head_object(
        Bucket=repository.bucket, Key=site_keys("prepare-meeting", 2)["page"]
    )
    assert head["ContentType"] == "text/html; charset=utf-8"

    css = repository.s3.head_object(Bucket=repository.bucket, Key=ASSET_KEYS["style"])
    assert css["ContentType"] == "text/css; charset=utf-8"
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：`uv run pytest tests/integration/test_site_publish.py -v`

預期：FAIL，`ImportError: cannot import name 'publish_site_assets' from 'training_kb.site'`。

- [ ] **步驟 3：寫最少的程式讓測試通過**

在 `src/training_kb/site.py` 的**檔案結尾**（`SiteRenderer` 類別外）加入：

```python
ASSETS_DIR = Path(__file__).resolve().parents[2] / "demo" / "site_assets"

CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".txt": "text/plain; charset=utf-8",
}


def content_type_for(key: str) -> str:
    """依副檔名決定 Content-Type；S3 website endpoint 會照這個標頭回傳。"""
    for suffix, value in CONTENT_TYPES.items():
        if key.endswith(suffix):
            return value
    return "application/octet-stream"


def parse_version_markdown(md: str, steps: list[TutorialStep]) -> TutorialContent:
    """從 render_markdown() 的固定格式反向解析出五段內容。

    步驟的 type 與 feature_id 以 DynamoDB 的 STEP item 為準（設計文件 D17 的精神：
    可重建的投影不當作獨立權威），這裡只從 markdown 取四段文字。
    """
    title = ""
    problem_lines: list[str] = []
    prerequisites: list[str] = []
    outcome_lines: list[str] = []
    section = ""

    for raw_line in md.splitlines():
        line = raw_line.rstrip()
        if line.startswith("# "):
            title = line[2:].strip()
            section = "title"
            continue
        if line.startswith("## "):
            section = line[3:].strip().lower()
            continue
        if not line:
            continue
        if section == "problem":
            problem_lines.append(line)
        elif section == "prerequisites":
            prerequisites.append(line.lstrip("-* ").strip())
        elif section == "expected outcome":
            outcome_lines.append(line)

    ordered = sorted(steps, key=lambda step: step.index)
    return TutorialContent(
        title=title,
        problem=" ".join(problem_lines),
        prerequisites=prerequisites,
        steps=[
            StepDraft(type=step.type, text=step.text, feature_id=step.feature_id)
            for step in ordered
        ],
        expected_outcome=" ".join(outcome_lines),
    )


def publish_site_assets(repo, assets_dir: Path | None = None) -> list[str]:
    """把 demo/site_assets 的檔案複製到 site/assets/，回傳寫入的 key 清單。"""
    source = assets_dir if assets_dir is not None else ASSETS_DIR
    written: list[str] = []
    for name, key in sorted(ASSET_KEYS.items()):
        file_name = "style.css" if name == "style" else "widget.js"
        body = (Path(source) / file_name).read_text(encoding="utf-8")
        repo.put_object(key, body, content_type=content_type_for(key))
        written.append(key)
    return written


def publish_to_site(repo, renderer: SiteRenderer, slug: str, version_id: str) -> list[str]:
    """把一個已發布版本寫進公開的 site/ 前綴。

    這是唯一組出 site/ key 並寫入的函式（設計文件 §9.3）。
    只有 content.publish() 與 Demo 種子載入器會呼叫它，
    而且兩者都只對已標成發布的版本呼叫（設計文件 O3）。
    """
    tutorial = repo.get_tutorial(slug)
    version = repo.get_version(version_id)
    if tutorial is None or version is None:
        raise ContentError(f"找不到教學或版本：{slug} / {version_id}")

    _, number = parse_version_id(version_id)
    steps = repo.get_steps(version_id)
    md_bytes = repo.get_object(version.s3_key)
    if md_bytes is None:
        raise ContentError(f"找不到版本全文：{version.s3_key}")
    content = parse_version_markdown(md_bytes.decode("utf-8"), steps)

    versions = repo.list_versions_of_tutorial(slug)
    diff_bytes = repo.get_object(f"tutorials/{slug}/v{number}.diff")
    diff_text = "" if diff_bytes is None else diff_bytes.decode("utf-8")
    retired = str(tutorial.status) == "retired"

    keys = site_keys(slug, number)
    written: list[str] = []

    page_html = renderer.render_version_page(
        tutorial,
        version,
        steps,
        content,
        versions=versions,
        diff_text=diff_text,
        retired=retired,
        successor=tutorial.successor,
    )
    repo.put_object(keys["page"], page_html, content_type=content_type_for(keys["page"]))
    written.append(keys["page"])

    repo.put_object(keys["diff"], diff_text, content_type=content_type_for(keys["diff"]))
    written.append(keys["diff"])

    index_html = renderer.render_tutorial_index(tutorial, versions)
    repo.put_object(keys["index"], index_html, content_type=content_type_for(keys["index"]))
    written.append(keys["index"])

    root_html = renderer.render_site_index(repo.list_tutorials())
    repo.put_object(keys["root"], root_html, content_type=content_type_for(keys["root"]))
    written.append(keys["root"])

    written.extend(publish_site_assets(repo))
    return written
```

在 `src/training_kb/site.py` 的 import 區補上：

```python
from pathlib import Path

from .errors import ContentError
from .models import StepDraft
```

若 `Repository` 還沒有 `list_tutorials()`，在 `src/training_kb/repository.py` 的 `Repository` 類別內加入：

```python
    def list_tutorials(self) -> list[Tutorial]:
        """列出所有教學（MVP 用 Scan，設計文件 §10 明說可以）。"""
        return [Tutorial.model_validate(item) for item in self.scan_entity("TUTORIAL")]
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：`uv run pytest tests/integration/test_site_publish.py -v`

預期：PASS，8 passed。

再跑一次 Phase 21 的教學載入測試，確認沒被改壞：

```bash
uv run pytest tests/integration/test_seed_tutorials.py -v
```

預期：全部 PASS。

- [ ] **步驟 5：commit**

```bash
git add src/training_kb/site.py src/training_kb/repository.py tests/integration/test_site_publish.py
git commit -m "feat(site): 發布時一併寫入索引頁與站台資產"
```

---

### Task 7：CDK 設定 website hosting 與只開放 site/ 的 bucket policy

**目的**：讓 bucket 可以當靜態網站用，而且**只有** `site/` 前綴是公開的。

**檔案**：
- 修改：`infra/stacks/data_stack.py`
- 測試：`tests/unit/test_infra_site_hosting.py`

**介面**：
- 產出：`TrainingKbDataStack` 的 bucket 加上 website 設定與 bucket policy；`CfnOutput` 輸出網站網址。

**四個設定與理由**（全部經 AWS 官方文件查證，連結見第 11 節）：

| 設定 | 值 | 理由 |
|---|---|---|
| `website_index_document` | `"index.html"` | 開啟 S3 static website hosting。存取 `site/prepare-meeting/` 這種目錄路徑時回傳該目錄的 `index.html`。 |
| `website_error_document` | `"index.html"` | 找不到頁面時回站台首頁，而不是 S3 的 XML 錯誤畫面。 |
| `block_public_access` | `block_public_acls=True`、`ignore_public_acls=True`、`block_public_policy=False`、`restrict_public_buckets=False` | AWS 官方文件（Setting permissions for website access）說明：要用 bucket policy 開放公開讀取，必須關掉會擋掉公開政策的兩項。ACL 相關的兩項維持開啟——我們不用 ACL，只用 policy。 |
| bucket policy | `Principal: "*"`、`Action: ["s3:GetObject"]`、`Resource: <bucket>/site/*` | 官方範例的 Resource 是 `<bucket>/*`（整個 bucket 公開）。本案**只寫 `site/*`**，`tutorials/`、`operations/`、`stepfunctions/`、`demo/previews/` 一律不公開（設計文件 §9.3、§17.2）。 |

**不要設 `enforce_ssl=True`**。那個設定會加上一條「拒絕非 HTTPS 請求」的政策，而 S3 website endpoint 只有 HTTP——設了就永遠讀不到頁面。設計文件 §13 已經明說：「S3 website endpoint 只有 HTTP；本文件不把它描述為 HTTPS」。要真正的 HTTPS 需要另外評估 CloudFront，本次不做。

**這一步只改 CDK 程式碼與測試，不執行 `cdk deploy`**。什麼時候部署、要不要部署，由維護者在 Phase 25 的部署清單裡決定。

- [ ] **步驟 1：寫測試**

```python
# tests/unit/test_infra_site_hosting.py
"""Phase 22 Task 7：CDK 的 website hosting 與 site/ 專用 bucket policy。"""

import json

import aws_cdk as cdk
from aws_cdk.assertions import Template

from infra.stacks.data_stack import TrainingKbDataStack


def _template() -> Template:
    app = cdk.App()
    stack = TrainingKbDataStack(
        app,
        "TestDataStack",
        env=cdk.Environment(account="111122223333", region="us-east-1"),
    )
    return Template.from_stack(stack)


def test_bucket_開啟_website_hosting():
    _template().has_resource_properties(
        "AWS::S3::Bucket",
        {
            "WebsiteConfiguration": {
                "IndexDocument": "index.html",
                "ErrorDocument": "index.html",
            }
        },
    )


def test_block_public_access_只放行_policy():
    _template().has_resource_properties(
        "AWS::S3::Bucket",
        {
            "PublicAccessBlockConfiguration": {
                "BlockPublicAcls": True,
                "IgnorePublicAcls": True,
                "BlockPublicPolicy": False,
                "RestrictPublicBuckets": False,
            }
        },
    )


def test_bucket_policy_只允許讀取_site_前綴():
    rendered = json.dumps(_template().to_json())

    assert "s3:GetObject" in rendered
    assert "/site/*" in rendered
    # 不得出現把整個 bucket 開放的寫法
    assert '"/*"' not in rendered


def test_bucket_policy_沒有寫入權限():
    rendered = json.dumps(_template().to_json())

    for action in ("s3:PutObject", "s3:DeleteObject", "s3:ListBucket", "s3:*"):
        assert f'"{action}"' not in rendered


def test_沒有強制_https_否則_website_endpoint_會失效():
    rendered = json.dumps(_template().to_json())

    assert "aws:SecureTransport" not in rendered


def test_輸出網站網址供維護者取用():
    outputs = _template().find_outputs("*")
    keys = list(outputs)

    assert any("SiteUrl" in key for key in keys)
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：`uv run pytest tests/unit/test_infra_site_hosting.py -v`

預期：FAIL，`Template has 1 resources with type AWS::S3::Bucket, but none match as expected`——Phase 04 建立的 bucket 還沒有 website 設定。

- [ ] **步驟 3：寫最少的程式讓測試通過**

打開 `infra/stacks/data_stack.py`，找到 Phase 04 建立 bucket 的那段（大致是 `s3.Bucket(self, "ContentBucket", ...)`），把它換成下面這段，並在 stack 結尾加上 `CfnOutput`：

```python
        # S3：教學全文、diff、操作紀錄、ASL 快照與公開教學站。
        # 只有 site/ 前綴公開；其餘前綴沒有任何公開權限（設計文件 §9.3、§17.2）。
        #
        # 注意：不設 enforce_ssl。S3 website endpoint 只有 HTTP，
        # 加上「拒絕非 HTTPS」的政策會讓公開頁面永遠讀不到（設計文件 §13）。
        self.bucket = s3.Bucket(
            self,
            "ContentBucket",
            bucket_name=bucket_name,
            website_index_document="index.html",
            website_error_document="index.html",
            block_public_access=s3.BlockPublicAccess(
                block_public_acls=True,
                ignore_public_acls=True,
                block_public_policy=False,
                restrict_public_buckets=False,
            ),
            encryption=s3.BucketEncryption.S3_MANAGED,
            removal_policy=RemovalPolicy.RETAIN,
        )

        # 公開讀取只開放 site/ 前綴的物件，而且只有 GetObject。
        self.bucket.add_to_resource_policy(
            iam.PolicyStatement(
                sid="PublicReadSitePrefixOnly",
                effect=iam.Effect.ALLOW,
                principals=[iam.AnyPrincipal()],
                actions=["s3:GetObject"],
                resources=[self.bucket.arn_for_objects("site/*")],
            )
        )

        CfnOutput(
            self,
            "SiteUrl",
            value=self.bucket.bucket_website_url,
            description="S3 website endpoint（只有 HTTP，不是 HTTPS）",
        )
        CfnOutput(
            self,
            "SiteIndexUrl",
            value=f"{self.bucket.bucket_website_url}/site/index.html",
            description="教學站首頁（只有 HTTP）",
        )
```

`infra/stacks/data_stack.py` 的 import 區需要有：

```python
from aws_cdk import CfnOutput, RemovalPolicy, Stack
from aws_cdk import aws_iam as iam
from aws_cdk import aws_s3 as s3
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：`uv run pytest tests/unit/test_infra_site_hosting.py -v`

預期：PASS，6 passed。

檢查 CDK 能合成（不部署）：

```bash
uv run cdk synth TrainingKbDataStack --app "uv run python infra/app.py" > /dev/null && echo "synth OK"
```

預期：印出 `synth OK`。若 `cdk` 指令不存在，先確認 Node.js 與 `npm install -g aws-cdk` 已完成（Phase 04 的步驟）。

- [ ] **步驟 5：commit**

```bash
git add infra/stacks/data_stack.py tests/unit/test_infra_site_hosting.py
git commit -m "feat(infra): 開啟 S3 website hosting 並只公開 site 前綴"
```

---

### Task 8：widget 產生的檔案要能通過匯入驗證

**目的**：證明 widget 產生的 JSON 真的可以被 Phase 15 的匯入流程吃下去，不是「格式看起來像」而已。

**檔案**：
- 測試：`tests/integration/test_site_widget_roundtrip.py`

**介面**：
- 消費（Phase 15）：`ingress.validate_feedback(data, *, now) -> Feedback`、`ingress.validate_view(data) -> TutorialView`、`ingress.import_feedback(repo, writer, data, *, now) -> ImportResult`、`ingress.import_view(repo, data) -> ImportResult`
- 消費（Phase 05）：`writing.client.FakeWriter`
- 消費（Phase 21）：`demo.seed_loader.load_features`、`load_tutorials`

**這個 Task 沒有新程式碼**，只有測試。它是本階段的收尾驗收：把 widget.js 會產生的那份 JSON 原封不動寫進測試，走完整條匯入路徑。

如果 widget.js 之後改了欄位名稱，這個測試會失敗——這正是我們要的。測試裡也直接檢查 `widget.js` 原始碼含有每個必要欄位名，讓兩邊不會悄悄分岔。

- [ ] **步驟 1：寫測試**

```python
# tests/integration/test_site_widget_roundtrip.py
"""Phase 22 Task 8：widget 產生的檔案能通過 Phase 15 的匯入驗證。"""

from pathlib import Path

import pytest
from moto import mock_aws

from demo.seed_loader import SEED_DIR, load_features, load_tutorials
from training_kb.clock import parse_iso
from training_kb.errors import IngressError
from training_kb.ingress import (
    import_feedback,
    import_view,
    validate_feedback,
    validate_view,
)
from training_kb.site import SiteRenderer
from training_kb.writing.client import FakeWriter

NOW = parse_iso("2026-09-13T12:34:56Z")
WIDGET = Path(__file__).resolve().parents[2] / "demo" / "site_assets" / "widget.js"

# 與 widget.js 產生的格式逐欄位對應。
FEEDBACK_FILE = {
    "kind": "feedback",
    "source": "site_widget",
    "generated_at": "2026-09-13T12:34:56Z",
    "note": "合成資料示範｜此檔尚未送出，需由維護者匯入",
    "items": [
        {
            "id": "f_site-prepare-meeting-u_01-1789012496",
            "tutorial_version": "prepare-meeting@v2",
            "rating": 4,
            "user": "u_01",
            "category": "缺少資訊",
            "comment": "第三步的說明可以再清楚一點",
            "ts": "2026-09-13T12:34:56Z",
        }
    ],
}

VIEW_FILE = {
    "kind": "view",
    "source": "site_widget",
    "generated_at": "2026-09-13T12:34:56Z",
    "note": "合成資料示範｜此檔尚未送出，需由維護者匯入",
    "items": [
        {
            "tutorial_version": "prepare-meeting@v2",
            "user": "u_01",
            "ts": "2026-09-13T12:34:56Z",
        }
    ],
}


def _seed(repository) -> None:
    load_features(repository, SEED_DIR / "features.json")
    load_tutorials(repository, SEED_DIR / "tutorials", SiteRenderer(), NOW)


def test_widget_原始碼含有每個必要欄位名():
    source = WIDGET.read_text(encoding="utf-8")

    for field in (
        "tutorial_version",
        "rating",
        "user",
        "category",
        "comment",
        "ts",
        "items",
        "kind",
    ):
        assert field in source


def test_回饋檔案通過_validate_feedback():
    feedback = validate_feedback(FEEDBACK_FILE["items"][0], now=NOW)

    assert feedback.id.startswith("f_")
    assert feedback.tutorial_version == "prepare-meeting@v2"
    assert feedback.rating == 4
    assert feedback.user == "u_01"
    assert feedback.category == "缺少資訊"


def test_瀏覽檔案通過_validate_view():
    view = validate_view(VIEW_FILE["items"][0])

    assert view.tutorial_version == "prepare-meeting@v2"
    assert view.user == "u_01"
    assert view.ts == "2026-09-13T12:34:56Z"


def test_未選擇類別時_category_為_null_仍然合法():
    payload = dict(FEEDBACK_FILE["items"][0])
    payload["category"] = None
    payload["comment"] = None

    feedback = validate_feedback(payload, now=NOW)

    assert feedback.category is None
    assert feedback.comment is None


def test_缺少使用者_id_會被拒絕():
    payload = dict(FEEDBACK_FILE["items"][0])
    payload.pop("user")

    with pytest.raises(IngressError) as info:
        validate_feedback(payload, now=NOW)

    assert "user" in info.value.fields


@mock_aws
def test_回饋檔案可以完成匯入(repository):
    _seed(repository)

    result = import_feedback(
        repository, FakeWriter(outputs=[]), FEEDBACK_FILE["items"][0], now=NOW
    )

    assert result.status == "saved"
    stored = repository.list_feedback_of_version("prepare-meeting@v2")
    assert any(item.id.startswith("f_site-") for item in stored)


@mock_aws
def test_瀏覽檔案可以完成匯入且重送算重複(repository):
    _seed(repository)

    first = import_view(repository, VIEW_FILE["items"][0])
    second = import_view(repository, VIEW_FILE["items"][0])

    assert first.status == "saved"
    assert second.status == "duplicate"
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：`uv run pytest tests/integration/test_site_widget_roundtrip.py -v`

預期：多數 PASS。若 `test_widget_原始碼含有每個必要欄位名` 失敗，代表 widget.js 少了某個欄位——回到 Task 3 補上。若 `test_回饋檔案可以完成匯入` 失敗且錯誤是 `版本不存在`，代表 Phase 21 的種子沒載入成功。

- [ ] **步驟 3：寫最少的程式讓測試通過**

這個 Task 原則上不需要新程式碼。若有測試失敗，依錯誤修正對應的檔案：

| 失敗的測試 | 要改的檔案 |
|---|---|
| `test_widget_原始碼含有每個必要欄位名` | `demo/site_assets/widget.js`：在 `buildFeedbackItem()` 補上缺少的欄位。 |
| `test_回饋檔案通過_validate_feedback` | `demo/site_assets/widget.js`：欄位名稱要和 `training_kb/models.py` 的 `Feedback` 完全一致（`tutorial_version`、`rating`、`user`、`category`、`comment`、`ts`）。 |
| `test_缺少使用者_id_會被拒絕` | `src/training_kb/ingress.py`：`validate_feedback` 必須把缺少的欄位名放進 `IngressError.fields`（Phase 15 的行為，這裡只是再確認一次）。 |
| `test_瀏覽檔案可以完成匯入且重送算重複` | `src/training_kb/keys.py`：`view_pk()` 必須對相同的三元組產生相同 PK（Phase 02 的行為）。 |

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：`uv run pytest tests/integration/test_site_widget_roundtrip.py -v`

預期：PASS，7 passed。

最後跑全部：

```bash
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
```

預期：全部 PASS、沒有 lint 錯誤。

- [ ] **步驟 5：commit**

```bash
git add tests/integration/test_site_widget_roundtrip.py
git commit -m "test(site): 驗證 widget 產生的檔案可完成匯入"
```

---

## 7. 完成檢查清單

對應設計文件第 16 節切片 S3（「發布後讀到正確全文」）與 S4（「View 與 Feedback 可匯入」）。

- [ ] `uv run pytest -q` 全部通過，`uv run ruff check .` 沒有錯誤。
- [ ] 跳脫有效：產生的 HTML 含 `&lt;script&gt;`，不含可執行的 `<script>alert`。
  ```bash
  uv run pytest tests/unit/test_site_version_page.py::test_模型與使用者文字都被跳脫 -v
  ```
- [ ] 退役頁沒有任何表單元素、沒有自動跳轉、successor 指向自己時不出現連結。
- [ ] v1 沒有 diff 連結，改顯示「第一版，沒有前一版可比較」。
- [ ] widget 產生的回饋 JSON 通過 `validate_feedback()`，瀏覽 JSON 通過 `validate_view()`。
- [ ] `widget.js` 不含 `innerHTML`、`fetch`、`XMLHttpRequest`、任何 `http(s)://` 網址或金鑰：
  ```bash
  grep -n 'innerHTML\|fetch(\|XMLHttpRequest\|https\?://\|AKIA' demo/site_assets/widget.js
  ```
  預期：沒有輸出。
- [ ] 公開檔案全部在 `site/` 底下：
  ```bash
  uv run pytest tests/integration/test_site_publish.py::test_公開檔案全部在_site_前綴底下 -v
  ```
- [ ] CDK 的 bucket policy 只開放 `site/*` 的 `s3:GetObject`，沒有寫入權限、沒有 `aws:SecureTransport`。
- [ ] 每一頁都標示「合成資料示範」與資料批次。
- [ ] 人工看一次實際頁面。先把種子載入並發布，再把 `site/` 下載到本機用瀏覽器開：
  ```bash
  uv run python -c "
  from training_kb.clock import now_utc
  from training_kb.config import load_settings
  from training_kb.repository import build_repository
  from training_kb.site import SiteRenderer
  from demo.seed_loader import SEED_DIR, load_all
  s = load_settings()
  print(load_all(build_repository(s), SiteRenderer(), now=now_utc(), seed_dir=SEED_DIR))
  "
  aws s3 sync "s3://$TKB_BUCKET_NAME/site" ./_site_check
  open ./_site_check/index.html
  ```
  預期：瀏覽器看到教學清單，點進去看到版本頁、版本選擇、差異連結與 widget。
  **看完請刪掉本機副本**：`rm -rf ./_site_check`。
- [ ] 若已部署，用 website endpoint 確認公開界線：
  ```bash
  curl -s -o /dev/null -w "%{http_code}\n" "http://<bucket>.s3-website-<region>.amazonaws.com/site/index.html"
  curl -s -o /dev/null -w "%{http_code}\n" "http://<bucket>.s3-website-<region>.amazonaws.com/tutorials/prepare-meeting/v2.md"
  ```
  預期：第一個 `200`、第二個 `403`。第二個若回 `200`，代表 bucket policy 開太大，立刻回頭檢查 Task 7。

---

## 8. 常見錯誤與排除

**症狀 1：瀏覽器打開頁面，看到的是一堆原始 HTML 標籤或直接下載檔案。**
原因：`Content-Type` 沒設對，S3 用預設的 `binary/octet-stream` 回傳。
解法：確認 `publish_to_site()` 每次 `put_object` 都傳了 `content_type=content_type_for(key)`。用下面這行檢查：
```bash
aws s3api head-object --bucket "$TKB_BUCKET_NAME" --key site/index.html --query ContentType
```
預期：`"text/html; charset=utf-8"`。

**症狀 2：頁面沒有樣式，瀏覽器主控台顯示 `style.css` 404。**
原因：資產沒上傳，或相對路徑的 `depth` 算錯。
解法：確認 `site/assets/style.css` 存在（`aws s3 ls "s3://$TKB_BUCKET_NAME/site/assets/"`）。若存在，檢查頁面原始碼裡的路徑：版本頁應該是 `../assets/style.css`，首頁應該是 `assets/style.css`。`page_shell()` 的 `depth` 參數：首頁傳 0、其他頁傳 1。

**症狀 3：`curl` 讀 `site/index.html` 回 403 Forbidden。**
原因有三種，依序檢查：
1. 帳號層級的 Block Public Access 還開著——bucket 層關掉沒用，AWS 取兩者中較嚴格的。到 S3 主控台的「Block Public Access settings for this account」確認。
2. bucket policy 沒套用成功——`aws s3api get-bucket-policy --bucket "$TKB_BUCKET_NAME"` 看看有沒有 `PublicReadSitePrefixOnly`。
3. 用錯網址——website endpoint 是 `http://<bucket>.s3-website-<region>.amazonaws.com`，不是 `https://<bucket>.s3.amazonaws.com`。後者是 REST endpoint，行為不一樣。

**症狀 4：`curl` 讀 `tutorials/prepare-meeting/v2.md` 竟然回 200。**
原因：bucket policy 的 `Resource` 寫成 `<bucket>/*` 而不是 `<bucket>/site/*`。
解法：回到 Task 7，確認用的是 `self.bucket.arn_for_objects("site/*")`。`test_bucket_policy_只允許讀取_site_前綴` 這個測試就是在擋這件事——它會斷言 `'"/*"'` 不出現在 template 裡。

**症狀 5：`test_版本選擇只列出已發布版本且標記目前版` 失敗，v3 的連結還在。**
原因：`_version_picker()` 沒有過濾 `published_at is None`。
解法：檢查那一行 `published = [v for v in versions if v.published_at]`。**未發布版本絕對不能出現在公開頁面**，這是設計文件 F36 與 O3 的界線。

**症狀 6：widget 按了「下載回饋檔案」沒反應，主控台出現 `Cannot read properties of null`。**
原因：`widget.js` 在 DOM 還沒載入時就跑了，`document.getElementById` 回傳 `null`。
解法：`page_shell()` 把 `<script>` 放在 `</body>` 之前（在 `<main>` 後面），所以 DOM 一定已經存在。若你把 script 搬到 `<head>`，就要改用 `DOMContentLoaded` 事件包起來。照本文件的順序放就不會有這個問題。

**症狀 7：下載的 JSON 檔中文變成 `中文`。**
原因：`JSON.stringify` 預設不會跳脫非 ASCII，所以這其實不會發生在瀏覽器端；若看到這個，多半是維護者這邊用 Python 重新寫檔時忘了 `ensure_ascii=False`。
解法：匯入流程讀檔用 `json.loads`（不受影響）；若要重新寫檔，加上 `ensure_ascii=False`。

**症狀 8：`cdk synth` 抱怨 `Bucket name is not valid`。**
原因：`bucket_name` 用了大寫字母、底線或太長的名稱。S3 bucket 名稱必須全小寫、3–63 字元、只能用字母數字與 `-`、`.`。
解法：改用符合規則的名稱，並記得 bucket 名稱在整個 AWS 是全域唯一的（設計文件 §9.1：「部署時實際 bucket 名稱須符合 AWS 的唯一性要求，不假設此名稱可直接取得」）。

---

## 9. 這階段不做的事

| 不做的事 | 留給哪一階段／為什麼 |
|---|---|
| CloudFront、自訂網域、HTTPS | 不做。設計文件 §13 明說：S3 website endpoint 只有 HTTP，要可靠的 HTTPS 需另外確認 CloudFront 等託管方式，本次不默默加進 MVP。 |
| 讓 widget 直接把回饋送進 API | 不做。設計文件 F08：Feedback 只由本機或受控種子匯入提供，不開放未驗證的公開接入。widget 只產生檔案。 |
| 在頁面上顯示指標、評分統計或規則狀態 | Phase 23（`23-Phase23-Demo控制台與Dashboard.md`）的 Streamlit 控制台。公開頁不放回饋原文與使用者 ID（設計文件 §17.2）。 |
| B 教學的「規則關閉／開啟」對照頁 | Phase 23，產物放 `demo/previews/`（私有），不進 `site/`（設計文件 F47）。 |
| 執行 `cdk deploy` 與設定帳號層級 Block Public Access | Phase 25（`25-Phase25-安全檢查與Demo當日準備.md`）的部署與安全檢查清單。本階段只改 CDK 程式碼並用 assertions 驗證。 |
| 在 `Tutorial` 加 `retire_reason` 欄位 | 不做。會動到 Phase 02 的模型與 Phase 08 的 `retire()`。本階段改以 `version.reason` 推導說明文字（本計劃選擇），並在第 6 節 Task 4 記下這個取捨。 |
| 搜尋、分頁、多語系、深色模式 | 不做。設計文件 §3：不納入完整 LMS 或複雜 dashboard。 |
| 把 `.md` 用第三方 markdown 套件轉 HTML | 不做。共用技術決定：不用第三方 markdown 套件，由結構化內容直接產生 HTML 並全部跳脫。 |

---

## 10. 對照：設計章節與 Rule 編號

| Rule 來源檔 | Rule 編號與原文 | 本階段哪個 Task 落實 |
|---|---|---|
| `發布教學版本.feature` | Rule 2：發布的教學透過 S3 靜態 docs 站提供 | Task 6（`publish_to_site` 寫入 `site/`）、Task 7（website hosting 與公開政策） |
| `發布教學版本.feature` | Rule 3：發布的教學提供 feedback widget | Task 2（widget HTML）、Task 3（`widget.js`）、Task 8（產出的檔案可匯入） |
| `發布教學版本.feature` | Rule 1：publish 上架指定的 TutorialVersion | Task 6（只對已發布版本寫 `site/`；未發布版本不出現在任何公開頁面） |
| `發布教學版本.feature` | Rule 4：Tutorial 的 current_version 指向目前教學版本 | Task 1（版本選擇標記「目前」）、Task 5（教學索引標「目前版本」） |
| `發布教學版本.feature` | Rule 5：已上架的版本具有 published_at | Task 1、Task 5（`published_at` 為空的版本一律不列出） |
| `建立教學版本.feature` | Rule 7：與前版的 diff 儲存在 tutorials/&lt;slug&gt;/v&lt;n&gt;.diff | Task 6（公開副本 `site/<slug>/v<n>.diff.txt` 內容與私有 `.diff` 相同） |
| `收集教學回饋.feature` | Rule 2：已退役教學的既有版本拒絕新回饋 | Task 4（退役頁完全不輸出表單元素並說明「不接受新回饋」） |
| `收集教學回饋.feature` | Rule 3：Feedback 的 rating 只能為 1 到 5 的整數 | Task 3（widget 只產生 1–5，未選評分不產生檔案）、Task 8（`validate_feedback` 驗證） |
| `收集教學回饋.feature` | Rule 4：使用者勾選的 Feedback Category 優先於模型分類 | Task 2、Task 3（勾選的類別直接寫進 `category`；「未選擇」寫 `null`，才交給模型分類） |
| `收集教學回饋.feature` | Rule 5：Feedback Category 必須屬於核定類別表或待分類 | Task 2（按鈕只提供「找不到按鈕」「缺少資訊」「未選擇」，不讓使用者自創類別） |
| `收集教學回饋.feature` | Rule 7：回饋關聯到提交時指定的 TutorialVersion | Task 3（`tutorial_version` 直接取自頁面的 `data-version-id`，不會綁到之後的 current_version） |
| `收集教學回饋.feature` | Rule 9：Feedback 接入時必須提供穩定使用者 ID | Task 3（user ID 必填，空白時不產生檔案）、Task 8（缺 user 被拒絕） |
| `依改版更新教學.feature` | Rule 16：RETIRE 將受影響教學標記為過期 | Task 4（退役橫幅顯示「此教學已過期」） |
| `依改版更新教學.feature` | Rule 17：RETIRE 的教學導向後繼 Tutorial | Task 4（有 successor 才顯示可點連結；指向自己不顯示；不自動跳轉） |
| `查詢知識圖譜.feature` | Rule 4：可查詢某篇 Tutorial 所屬的版本 | Task 5（教學索引頁列出所有已發布版本） |

---

## 11. 參考來源

### 設計文件章節（`docs/design/training-kb.md`）

- §8.2 create_version 的完成條件：v1 仍有空的 `v1.diff`，畫面顯示「第一版，沒有前一版可比較」。
- §8.3 發布與併發必須守住的界線：S3 產物先保存在私有區，公開站僅使用完成發布的版本。
- §8.4 退役後的畫面與資料：顯示過期原因與原文、不做連續自動跳轉、退役版本拒絕新回饋、後繼檢查非自身且不形成循環。
- §9.3 S3 與執行資訊：`tutorials/`、`site/`、`demo/previews/`、`operations/` 的地位；`site/` 僅發布流程可寫。
- §11.5 Demo 的資料與即時執行分開標示：畫面固定標示「合成資料示範」及資料批次。
- §13 Demo UI 與 S3 教學頁：頁面版面、widget 產生檔案的流程、「檔案已產生，尚未送出」、穩定 user ID 的要求、S3 website endpoint 只有 HTTP。
- §17.1 已查證的平台用法：S3 website endpoint 不提供 HTTPS。
- §17.2 最小必要的安全處理：Markdown 轉 HTML 時跳脫不可信內容並限制可執行 HTML；公開區只放可公開教學與合成展示資料；前端不取得寫入資料庫的憑證。
- §16 交付切片 S3、S4。
- §18 待確認事項 O3（S3 公開與發布提交）。
- §19.2 功能決策 F08（非 GitHub 事件由受控入口接收）、F19（無後繼仍完成退役）、F36（內容已寫入但關聯不完整時保留不可公開）、F38（MVP 只提供 S3 靜態 docs 站）、F39（退役版本拒絕新回饋）、F50（v1 建立空 diff）、F54（後繼由維護者選定）。
- §19.1 資料決策 D13（核定類別表：找不到按鈕、缺少資訊）、D21（只用 retired，obsolete 是顯示用語）、D22（successor 存在 Tutorial metadata）、D25（`published_at` 為空代表未發布）。

### 規格檔

- `docs/spec/features/發布教學版本.feature`（5 條 Rule）
- `docs/spec/features/收集教學回饋.feature`（10 條 Rule）
- `docs/spec/features/依改版更新教學.feature`（Rule 16、Rule 17）
- `docs/spec/features/查詢知識圖譜.feature`（Rule 4）
- `docs/spec/erm.dbml`（`TUTORIAL.successor`、`TUTORIAL_VERSION.published_at` 的 note）

### 外部官方文件（本次查證）

- S3 static website endpoints（website endpoint 的網址格式，且只有 HTTP）：<https://docs.aws.amazon.com/AmazonS3/latest/userguide/WebsiteEndpoints.html>
- Setting permissions for website access（要公開就必須關掉會擋政策的 Block Public Access 設定，並加上允許 `s3:GetObject` 的 bucket policy）：<https://docs.aws.amazon.com/AmazonS3/latest/userguide/WebsiteAccessPermissionsReqd.html>
  官方範例的 policy 是：`{"Version":"2012-10-17","Statement":[{"Sid":"PublicReadGetObject","Effect":"Allow","Principal":"*","Action":["s3:GetObject"],"Resource":["arn:aws:s3:::{{Bucket-Name}}/*"]}]}`。本案把 `Resource` 收窄成 `arn:aws:s3:::<bucket>/site/*`，其餘前綴不公開。
- Blocking public access to your Amazon S3 storage（帳號層級與 bucket 層級取較嚴格者）：<https://docs.aws.amazon.com/AmazonS3/latest/userguide/access-control-block-public-access.html>
- AWS CDK Python `aws_cdk.aws_s3.Bucket`（`website_index_document`、`website_error_document`、`block_public_access`、`arn_for_objects`、`bucket_website_url`）：<https://docs.aws.amazon.com/cdk/api/v2/python/aws_cdk.aws_s3/Bucket.html>
- AWS CDK Python `aws_cdk.aws_s3.BlockPublicAccess`（四個參數 `block_public_acls`、`block_public_policy`、`ignore_public_acls`、`restrict_public_buckets`）：<https://docs.aws.amazon.com/cdk/api/v2/python/aws_cdk.aws_s3/BlockPublicAccess.html>
  經本次查證：`BlockPublicPolicy` 啟用時 S3 會拒絕任何授予公開存取的 bucket policy，因此靜態站必須把它設為 `False`。
- AWS CDK Python `aws_cdk.aws_s3.BucketPolicy` 與 `IBucket.add_to_resource_policy`（官方建議用 `add_to_resource_policy()` 而非直接建 `BucketPolicy`，以免覆蓋既有政策）：<https://docs.aws.amazon.com/cdk/api/v2/python/aws_cdk.aws_s3/BucketPolicy.html>
- AWS CDK assertions（`Template.from_stack`、`has_resource_properties`、`find_outputs`）：<https://docs.aws.amazon.com/cdk/api/v2/python/aws_cdk.assertions/README.html>
- S3 條件寫入（避免同 key 被覆蓋，`publish_to_site` 的重送情境）：<https://docs.aws.amazon.com/AmazonS3/latest/userguide/conditional-writes.html>
