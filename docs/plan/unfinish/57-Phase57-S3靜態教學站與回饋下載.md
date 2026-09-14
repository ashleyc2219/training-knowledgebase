# Phase 57：S3 靜態教學站與回饋下載實作計畫

> **給實作者：** 依 checkbox 逐步執行；每個 Task 先建立失敗測試，再寫最小實作。執行時使用 `superpowers:executing-plans` 或同等逐項流程。

**目標：** 把 Phase 24 的最小 renderer 擴充成完整教學站：版本選擇、與前版差異、版本紀錄、退役頁與回饋／瀏覽紀錄下載，並把公開範圍鎖死在 `site/` 前綴。

**架構：** `SiteRenderer` 是純函式渲染器，輸入既有實體與內容、輸出 HTML 字串，不讀寫 AWS；公開 key 一律由 Phase 24 的三個 helper 組出，哪些版本真的進 `site/` 由 Phase 24／25 的 `Publisher` 決定。widget 是純瀏覽器端 JavaScript，只在本機產生檔案交給維護者走 Phase 42 的固定匯入路徑，不發網路請求、不持有憑證。

**技術：** Python 3.12、`html.escape`、pytest、AWS CDK（S3 website hosting 與 bucket policy）、不依賴框架與 CDN 的純 JavaScript。

## 全域限制

- 唯一主來源是 [Training KB 設計 §8.2、§8.4、§9.3、§13、§17.1、§17.2](../../design/training-kb.md)。前置為 [Phase 56：O7 核定 Demo 種子資料](./56-Phase56-O7核定Demo種子資料.md)；另需 [Phase 24](./24-Phase24-單篇教學發布提交.md) 的 `SiteRenderer` 最小版與三個公開 key helper、[Phase 25](./25-Phase25-多篇教學整批發布.md) 的整批 `Publisher`、[Phase 26](./26-Phase26-教學退役與後繼導向.md) 的 `retire_tutorial` 與退役文案常數、[Phase 42](./42-Phase42-Feedback與View固定匯入.md) 的匯入契約。前置未通過時停止。下一階段是 [Phase 58：Demo 控制台與規則開關預覽](./58-Phase58-Demo控制台與規則開關預覽.md)。
- 本階段不做：不改 `SiteRenderer` 三個方法的簽名；不重新定義 `site_key`／`tutorial_index_key`／`site_index_key`（[Phase 24](./24-Phase24-單篇教學發布提交.md) 產出，本 Phase 只消費）；不建立第二個公開入口、公開讀取 API 或任何寫入端點；不加 CloudFront 或 HTTPS 託管；不建立版本、不發布、不判定門檻；不在瀏覽器端呼叫 AWS 或 Bedrock。
- 與本 Phase 有關的 O1–O7 gate 狀態（O1–O7 是設計 §18 的七個待確認事項編號）：O3（S3 與 DynamoDB 發布提交）仍待 [Phase 12](./12-Phase12-O3發布切換整合驗證.md) 的整合驗證。本 Phase 只決定「渲染什麼」與「公開哪些 key」，**不得宣稱發布故障驗收已通過**，也不能因為頁面打得開就說 O3 PASS。O7（核定種子與外部設定）的核定屬 [Phase 56](./56-Phase56-O7核定Demo種子資料.md)，頁面批次標示只能照抄已核定批次名稱。
- 以下程式檔均是實作時預計建立或修改；本計畫本身不代表它們已存在。

---

## 1. 你在整體流程的位置

```text
Publisher.prepare --> 私有 staging 產物（尚未公開）
      |
      v
[你在這裡：SiteRenderer 完整版 + widget 資產 + bucket policy]
      |
  +---+--------------------------+
  | render_* 三個方法            | widget.js（只在瀏覽器產生檔案）
  | 只有 commit 成功才寫 site/    | 下載 feedback / view JSON
  v                              v
讀者用 website endpoint（HTTP） 維護者走 Phase 42 固定匯入路徑
```

渲染在發布前，公開在發布後；中間那一段屬於 `Publisher`，不是 renderer 的責任。

## 2. 完成後看得到什麼

輸入 `prepare-meeting`、已發布的 `prepare-meeting@v3`（`supersedes="prepare-meeting@v2"`）與五段內容，`render_version_page` 的輸出必須含有：

```text
[合成資料示範] 批次：demo-seed-01 | 準備會議 | 版本：v3
版本選擇：上一版 v2 | 本頁 v3（目前版本） | [查看版本紀錄]
[查看與 v2 的差異] -> /site/tutorials/prepare-meeting/v3.diff.txt
這篇有幫助嗎？[1][2][3][4][5]  類別：[找不到按鈕][缺少資訊][未選擇]
留言：____  你的穩定使用者 ID：____（必填）
[下載回饋檔案，交由維護者匯入] [下載瀏覽紀錄]  狀態：檔案已產生，尚未送出
```

版本紀錄連結固定是 `/site/tutorials/prepare-meeting/index.html`，站台索引是 `/site/index.html`。頁面**不顯示 `TutorialVersion.reason`**：`release:r_42`、`gap:c12` 這種字串帶有內部識別碼，屬私有欄位（設計 §13、00A §3.3）。對 `prepare-meeting@v1`，差異區塊固定是「第一版，沒有前一版可比較」；對 `status="retired"` 的 Tutorial，整個評分與留言區消失，改成 Phase 26 的固定文案「此教學已退役，內容僅供歷史查閱。」。

## 3. 名詞小抄

| 名詞 | 白話意思 |
|---|---|
| S3 website endpoint | 把 bucket 當靜態網站用的網址，像 `http://<bucket>.s3-website-<region>.amazonaws.com`；只有 HTTP。 |
| bucket policy | 一段 JSON，寫明誰可以對哪些物件做什麼；本案只允許任何人對 `site/*` 做 `s3:GetObject`。 |
| Block Public Access | S3 的四道保險，預設全開；要用 policy 公開讀取必須關掉 `BlockPublicPolicy` 與 `RestrictPublicBuckets`。 |
| `enforce_ssl` | CDK 的 bucket 參數，打開會自動加一段「非 HTTPS 一律 Deny」的 bucket policy；website endpoint 只有 HTTP，所以本 Phase 要關掉它。 |
| `html.escape`／`textContent` | 前者是 Python 把角括號換成實體字的標準函式，後者是 JavaScript 放純文字的安全方式；`innerHTML` 一律不用。 |
| successor | 教學退役時維護者可指定的接班教學；沒有指定也能完成退役。 |

## 4. 預計檔案

| 動作 | 路徑 | 責任 |
|---|---|---|
| 修改 | `src/training_kb/site.py` | `SiteRenderer` 完整版、`escape_text`、`site_diff_key`、四個公開常數。 |
| 建立 | `demo/site_assets/widget.js`、`demo/site_assets/style.css` | 產生回饋與瀏覽紀錄檔案、版面樣式；不連網、不含金鑰、不 `@import` 外部資源。 |
| 修改 | `infra/training_kb_data_stack.py` | website hosting、放寬 Block Public Access、`enforce_ssl=False` 與只公開 `site/*` 的 bucket policy。 |
| 修改 | `tests/unit/test_data_stack.py` | [Phase 09](./09-Phase09-AWS資料資源與最小IAM.md) 原本斷言四道 Block Public Access 全開，改成新值。 |
| 測試 | `tests/unit/test_site_pages.py` | 版本頁、索引頁、退役頁與跳脫。 |
| 測試 | `tests/unit/test_site_assets.py`、`tests/unit/test_infra_site_hosting.py` | 資產守門與 CDK 公開範圍。 |
| 測試 | `tests/integration/test_site_widget_roundtrip.py` | 下載檔走完 Phase 42 匯入與整站掃描。 |

`SiteRenderer` 的模組路徑是 `src/training_kb/site.py`（00A 的 D-17，owner 是 Phase 24）；類別與三個方法名稱不可改。

## 5. 固定介面

### Consumes

```text
PermanentError                                                            # Phase 02
TutorialContent(title, problem, prerequisites, steps, expected_outcome)   # Phase 03
Tutorial(slug, current_version, topic, feature_ids, status, successor, cluster_id)
TutorialVersion(version_id, slug, supersedes, reason, rules_applied, s3_key, published_at)
TutorialStep(tutorial_version, number, type, text, feature_id)            # Phase 04
Repository.put_object(key, body, content_type, *, if_none_match)          # Phase 07
TrainingKbDataStack（bucket、block_public_access、enforce_ssl）            # Phase 09
parse_version_id(value) -> tuple[str, int]                                # Phase 20
PUBLIC_SITE_PREFIX（值 "site/"）                                          # Phase 22
site_key(version_id) -> "tutorials/<slug>/v<n>.html"                      # Phase 24（D-54）
tutorial_index_key(slug) -> "tutorials/<slug>/index.html"                 # Phase 24（D-54）
site_index_key() -> "index.html"                                          # Phase 24（D-54）
SiteRenderer.render_version_page / render_tutorial_index / render_site_index
Publisher.prepare / inspect / commit      # Phase 24、25：唯一能寫 site/ 的路徑，簽名不得更動
RETIRED_NOTICE（值「此教學已退役，內容僅供歷史查閱。」；在 content.py）      # Phase 26
import_feedback(payload, ...) / import_view(payload, ...) -> ImportResult # Phase 42
approved_categories(repository) -> frozenset[str]                         # Phase 43
```

### Produces

```python
SITE_PREFIX = "site/"                       # 與 Phase 22 的 PUBLIC_SITE_PREFIX 同值
ASSET_KEYS = ("site/assets/style.css", "site/assets/widget.js")
NO_PREVIOUS_TEXT = "第一版，沒有前一版可比較"
NOT_SENT_TEXT = "檔案已產生，尚未送出"

def escape_text(value: str) -> str: ...
def site_diff_key(version_id: str) -> str: ...   # "tutorials/<slug>/v<n>.diff.txt"，不含 site/

class SiteRenderer:                              # src/training_kb/site.py，只換實作
    def __init__(self, *, notice: str = "", batch: str = "",
                 categories: tuple[str, ...] = (),
                 asset_prefix: str = "/site/assets") -> None: ...
    def render_version_page(self, tutorial, version, steps, content) -> str: ...
    def render_tutorial_index(self, tutorial, versions) -> str: ...
    def render_site_index(self, tutorials) -> str: ...
```

`__init__` 的四個 keyword 參數**全部有預設值**（00A 的 D-20）：Phase 24／25／41／48／52 都用 `SiteRenderer()` 無參數建構，本 Phase 加畫面選項時不得拿掉預設值。`categories` 由 Phase 43 的 `approved_categories(repository)` 注入，renderer 不自己維護類別清單。版號一律用 Phase 20 的 `parse_version_id(version_id)[1]` 取得，本 Phase **不再自訂 `version_number`**（00A 的 D-19）。

## 6. 設計細節

```text
  bucket training-kb-content（設計 §9.3 只有這一個 bucket）
  +--------------------------------------------------------------------+
  | 公開（bucket policy：Principal "*" + s3:GetObject + site/*）         |
  |   site/index.html                     <- site_index_key()           |
  |   site/tutorials/<slug>/index.html    <- tutorial_index_key(slug)   |
  |   site/tutorials/<slug>/v<n>.html     <- site_key(version_id)       |
  |   site/tutorials/<slug>/v<n>.diff.txt <- site_diff_key(version_id)  |
  |   site/assets/style.css、site/assets/widget.js  <- ASSET_KEYS       |
  +--------------------------------------------------------------------+
  | 私有：tutorials/（含未發布全文與 .diff）、operations/、              |
  |       stepfunctions/、demo/previews/；DynamoDB 全私有（回饋留言、    |
  |       TUTORIAL_VIEW.user、TICKET.author）                           |
  +--------------------------------------------------------------------+
```

四個 helper 回的都是**不含 `site/` 前綴**的相對 key；公開物件是 `PUBLIC_SITE_PREFIX + <相對 key>`，頁面裡的 `href` 再補一個開頭的 `/`，所以 v3 的差異連結是 `/site/tutorials/prepare-meeting/v3.diff.txt`。公開差異檔的內容就是 Phase 22 私有 `tutorials/<slug>/v<n>.diff` 的逐字副本，複製動作屬發布路徑（Phase 24 `Publisher.commit`／Phase 25 `promote_site_objects`），本 Phase 只負責定名與產生連結。

渲染時機早於公開時機，所以 renderer 不能拿 `published_at` 當守門條件（`prepare` 階段它必然是 `None`）。改用可機器檢查的標記：`published_at is None` 的頁面帶 `data-published="false"`，只存在於私有 staging；`Publisher.commit` 只把 `true` 的頁面寫進 `site/`；整合測試掃描 `site/` 全部物件，出現 `false` 即失敗。**重新渲染的責任不在本 Phase：** 依 00A §6.7，`Publisher.commit` 在交易成功後、寫 `site/` 前，用已切換的 `published_at` 重新渲染並覆寫同一個 staging key，再由 promote 複製同一份 bytes；本 Phase 只讓 renderer 把標記印出來。版本選擇則只用 `render_version_page` 拿得到的資料組出來。**本計畫選擇：** 顯示「上一版（`version.supersedes`）」「本頁」「目前版本（`tutorial.current_version`）」，再加一個指向 `tutorial_index_key(slug)` 的版本紀錄連結，完整清單只放在版本紀錄頁；理由是設計 §8.1 允許永久失敗留下版號缺口，用 `v1..vN` 推算會產生死連結。`supersedes is None` 顯示 `NO_PREVIOUS_TEXT`，但版號大於 1 卻缺 `supersedes` 代表資料不完整，丟 `PermanentError`，不要靜默顯示成第一版。

退役頁依設計 §8.4：原文逐字保留，加上 Phase 26 的固定過期說明常數 `RETIRED_NOTICE`（兩份文件共用同一個常數，不各寫一份字面值）。設計 §8.4 寫「顯示過期原因」，但 §13 明訂上游 ID 與執行紀錄屬私有，所以公開頁只印固定說明，不印 `reason`、Release ID 或日期。只有 `tutorial.successor` 去頭尾後非空且不等於自身時才顯示後繼連結，而且是可點連結，沒有 `meta refresh`、沒有 JavaScript 轉址。退役頁不輸出評分、類別、留言與任何下載按鈕，widget.js 讀到 `data-retired="true"` 就整段停用（**本計畫選擇：** 退役頁只保留歷史原文，連瀏覽紀錄也不再收集）。所有進入 HTML 的動態文字都先過 `escape_text`；頁面不引入 Markdown 轉 HTML 轉換器，直接用 `TutorialContent` 的結構欄位組標籤。

## 7. TDD Tasks

### Task 1：版本頁的版本選擇、差異與未發布標記

- [ ] **Step 1：建立失敗測試**（`renderer` fixture 是 `SiteRenderer(notice="合成資料示範", batch="demo-seed-01", categories=("找不到按鈕", "缺少資訊"))`；`make_version` 建 `TutorialVersion`，`published_at` 預設是一個 aware datetime）

```python
from training_kb.site import NO_PREVIOUS_TEXT, SiteRenderer

def test_version_page_links_previous_diff(renderer, tutorial, steps, content):
    version = make_version("prepare-meeting@v3", supersedes="prepare-meeting@v2")
    page = renderer.render_version_page(tutorial, version, steps, content)
    assert 'data-published="true"' in page and "查看與 v2 的差異" in page
    assert 'href="/site/tutorials/prepare-meeting/v3.diff.txt"' in page
    assert 'href="/site/tutorials/prepare-meeting/index.html"' in page
    assert "release:r_42" not in page and version.reason not in page

def test_version_page_v1_says_no_previous(renderer, tutorial, steps, content):
    page = renderer.render_version_page(
        tutorial, make_version("prepare-meeting@v1", supersedes=None), steps, content)
    assert NO_PREVIOUS_TEXT in page and "v0.diff.txt" not in page
```

- [ ] **Step 2：執行並確認紅燈**

```bash
uv run pytest tests/unit/test_site_pages.py -q
```

預期：FAIL，訊號包含 `cannot import name 'NO_PREVIOUS_TEXT'`。

- [ ] **Step 3：建立最小實作**

```python
import html

from training_kb.content import parse_version_id     # Phase 20
from training_kb.errors import PermanentError        # Phase 02

SITE_PREFIX = "site/"
ASSET_KEYS = ("site/assets/style.css", "site/assets/widget.js")
NO_PREVIOUS_TEXT = "第一版，沒有前一版可比較"
NOT_SENT_TEXT = "檔案已產生，尚未送出"

def escape_text(value: str) -> str:
    return html.escape(value, quote=True)

def site_diff_key(version_id: str) -> str:
    slug, number = parse_version_id(version_id)
    return f"tutorials/{slug}/v{number}.diff.txt"

def _href(relative_key: str) -> str:
    return "/" + SITE_PREFIX + relative_key

def _diff_block(version) -> str:
    _, number = parse_version_id(version.version_id)
    if version.supersedes is None:
        if number != 1:
            raise PermanentError(f"{version.version_id} 缺少 supersedes")
        return f'<p class="diff-note">{escape_text(NO_PREVIOUS_TEXT)}</p>'
    _, previous = parse_version_id(version.supersedes)
    return (f'<p class="diff-note"><a href="{_href(site_diff_key(version.version_id))}">'
            f"查看與 v{previous} 的差異</a></p>")
```

- [ ] **Step 4：補版本選擇與跳脫後跑綠燈**

`_version_switch(tutorial, version)` 用 `from training_kb.publishing import site_key, tutorial_index_key`（Phase 24，D-54；模組位置以 Phase 24 的實際檔案為準）組出三段：`version.supersedes` 非空時是 `_href(site_key(version.supersedes))` 的「上一版 vN」、本頁版號（等於 `tutorial.current_version` 時加「（目前版本）」）、以及 `_href(tutorial_index_key(version.slug))` 的「查看版本紀錄」。`render_version_page` 的最外層元素固定帶 `data-published`（`version.published_at is not None` 轉成 `"true"`／`"false"`）、`data-retired`、`data-slug`、`data-version-id`，接著依序輸出橫幅（`notice`、`batch`）、標題、版本選擇、`_diff_block`、五段內容與 widget 區塊；`version.reason` 不進頁面。標題、步驟文字與所有動態欄位一律經 `escape_text`；加入惡意文字案例：步驟文字為 `<script>alert(1)</script>` 時輸出只含 `&lt;script&gt;`。執行 `uv run pytest tests/unit/test_site_pages.py -q`，預期整個檔案全綠。

- [ ] **Step 5：提交**

```bash
git add src/training_kb/site.py tests/unit/test_site_pages.py
git commit -m "feat(site): 版本頁加入版本選擇與差異連結"
```

### Task 2：退役頁、後繼連結與索引頁的公開界線

- [ ] **Step 1：建立失敗測試**

```python
from training_kb.content import RETIRED_NOTICE
from training_kb.site import escape_text

def test_retired_page_keeps_text_and_disables_widget(renderer, steps, content):
    tutorial = make_tutorial(status="retired", successor="share-summary")
    version = make_version("prepare-meeting@v3", supersedes="prepare-meeting@v2")
    page = renderer.render_version_page(tutorial, version, steps, content)
    assert RETIRED_NOTICE in page and 'data-retired="true"' in page
    assert escape_text(content.steps[0].text) in page
    assert 'href="/site/tutorials/share-summary/index.html"' in page
    assert "http-equiv" not in page and "tkb-download" not in page

def test_tutorial_index_hides_unpublished_versions(renderer, tutorial):
    v1 = make_version("prepare-meeting@v1", supersedes=None, published_at=NOW)
    draft = make_version("prepare-meeting@v2", supersedes="prepare-meeting@v1",
                         published_at=None)
    page = renderer.render_tutorial_index(tutorial, [v1, draft])
    assert 'href="/site/tutorials/prepare-meeting/v1.html"' in page
    assert "v2.html" not in page
```

- [ ] **Step 2：執行並確認紅燈**

```bash
uv run pytest tests/unit/test_site_pages.py -q
```

預期：FAIL，退役橫幅與索引過濾都還不存在。

- [ ] **Step 3：建立最小實作**

`_retired_banner(tutorial)` 在 `tutorial.status is not TutorialStatus.RETIRED` 時回空字串（StrEnum 成員名一律大寫，00A §5.3）；否則輸出 Phase 26 的 `RETIRED_NOTICE` 那一行（常數在 Phase 26 的 `content.py`，00A §6.6；直接 import 引用，不在 `site.py` 重抄一份字面值），只有 `tutorial.successor` 去頭尾後非空且不等於 `tutorial.slug` 時，才追加一個指向 `_href(tutorial_index_key(successor))` 的 `<a>`。`_published_versions(versions)` 只保留 `published_at is not None`，依 `parse_version_id(v.version_id)[1]` 升序排序，連結用 `_href(site_key(v.version_id))`。兩者的輸出都經 `escape_text`；退役時 widget 區塊整段不輸出。

- [ ] **Step 4：補邊界案例並跑綠燈**

再加 successor 為 `None`、successor 等於自身、successor 為空白字串三個案例，預期都沒有連結卻仍顯示過期說明與原文；再加一個「退役頁全文不含使用者 ID 與回饋留言」的斷言。執行 `uv run pytest tests/unit/test_site_pages.py -q`，預期整個檔案全綠。

- [ ] **Step 5：提交**

```bash
git add src/training_kb/site.py tests/unit/test_site_pages.py
git commit -m "feat(site): 退役頁與索引只列已發布版本"
```

### Task 3：widget.js 產生可直接匯入的檔案

- [ ] **Step 1：建立失敗測試**

```python
from pathlib import Path

from training_kb.site import NOT_SENT_TEXT

def test_widget_is_self_contained_and_never_claims_sent():
    source = Path("demo/site_assets/widget.js").read_text(encoding="utf-8")
    for banned in ("innerHTML", "outerHTML", "insertAdjacentHTML", "fetch(",
                   "XMLHttpRequest", "sendBeacon", "http://", "https://", "amazonaws"):
        assert banned not in source
    assert NOT_SENT_TEXT in source
    assert "已送出" not in source.replace("尚未送出", "")

def test_downloaded_feedback_passes_phase42_import(repository, operations):
    item = {"id": "f_site-prepare-meeting-u_01-1789012345", "rating": 4, "user": "u_01",
            "tutorial_version": "prepare-meeting@v2", "category": "缺少資訊",
            "comment": "第三步的截圖可以再清楚一點", "ts": "2026-09-13T12:34:56Z"}
    assert type(item["rating"]) is int
    assert import_feedback(item, repository=repository,
                           operations=operations, now=NOW).status == "saved"
```

- [ ] **Step 2：執行並確認紅燈**

```bash
uv run pytest tests/unit/test_site_assets.py tests/integration/test_site_widget_roundtrip.py -q
```

預期：FAIL，訊號包含 `FileNotFoundError: demo/site_assets/widget.js`。

- [ ] **Step 3：建立最小實作**

```javascript
(function () {
  "use strict";
  var root = document.getElementById("tkb-widget");
  if (!root || root.getAttribute("data-retired") === "true") { return; }
  var versionId = root.getAttribute("data-version-id") || "";
  var slug = root.getAttribute("data-slug") || "";
  var notice = root.getAttribute("data-notice") || "合成資料示範";
  var status = document.getElementById("tkb-status");
  function setStatus(t) { if (status) { status.textContent = t; } }
  function token(v) { return String(v).replace(/[^A-Za-z0-9_-]/g, ""); }
  function nowIso() { return new Date().toISOString().replace(/\.\d{3}Z$/, "Z"); }
  function field(id) { var n = document.getElementById(id); return n ? n.value.trim() : ""; }
  function save(name, kind, items) {
    var body = { kind: kind, source: "site_widget", generated_at: nowIso(),
                 note: notice + "｜此檔尚未送出，需由維護者匯入", items: items };
    var url = URL.createObjectURL(new Blob([JSON.stringify(body, null, 2)],
                                  { type: "application/json;charset=utf-8" }));
    var link = document.createElement("a");
    link.href = url; link.download = name;
    document.body.appendChild(link); link.click(); document.body.removeChild(link);
    URL.revokeObjectURL(url);
    setStatus("檔案已產生，尚未送出。請把檔案交給維護者匯入。");
  }
})();
```

同一檔案再加三段：`button.rating` 與 `button.category` 的 click handler 只更新兩個區域變數並用 `textContent` 更新狀態列；`#tkb-download` 檢查 `field("tkb-user")` 非空且評分是 1–5 的整數，再用 `Number(...)` 讓 `rating` 是數字型別，組出 `id = "f_site-" + token(slug) + "-" + token(user) + "-" + Math.floor(Date.now() / 1000)` 後呼叫 `save(..., "feedback", [...])`；`#tkb-view` 只檢查使用者 ID，呼叫 `save(..., "view", [{tutorial_version: versionId, user: user, ts: nowIso()}])`。全部用 `addEventListener`，不用 `innerHTML`。封套 `{kind, source, generated_at, note, items}` 的 `kind`／`items` 與 Phase 42 匯入入口的事件形狀相同，維護者用 [Phase 58](./58-Phase58-Demo控制台與規則開關預覽.md) 的 `import` 子命令把 `items` 逐筆送進 `import_feedback`／`import_view`；`user` 一律是 Demo 種子的 `u_01` 形狀，不是瀏覽器隨機 ID。

- [ ] **Step 4：跑完整檔案確認綠燈**

roundtrip 另需補 `validate_view` 案例、「同一個 `id` 第二次匯入回 `duplicate` 且不增加樣本」的案例，以及「`rating` 是 `"4"` 字串時被拒絕並指出 `rating` 欄位」的案例。執行 `uv run pytest tests/unit/test_site_assets.py tests/integration/test_site_widget_roundtrip.py -q`，預期整個檔案全綠。

- [ ] **Step 5：提交**

```bash
git add demo/site_assets tests/unit/test_site_assets.py tests/integration/test_site_widget_roundtrip.py
git commit -m "feat(site): 回饋 widget 產生可匯入檔案"
```

### Task 4：只公開 `site/*` 的 bucket policy

- [ ] **Step 1：建立失敗測試**

```python
import json

import aws_cdk as cdk
from aws_cdk.assertions import Template

from infra.training_kb_data_stack import TrainingKbDataStack

def synth() -> Template:
    return Template.from_stack(TrainingKbDataStack(cdk.App(), "TrainingKbData"))

def test_bucket_policy_only_opens_site_prefix() -> None:
    template = synth()
    policies = list(template.find_resources("AWS::S3::BucketPolicy").values())
    assert len(policies) == 1
    statements = policies[0]["Properties"]["PolicyDocument"]["Statement"]
    assert len(statements) == 1          # enforce_ssl=False 之後沒有多餘的 Deny
    only = statements[0]
    assert only["Effect"] == "Allow" and only["Principal"] == {"AWS": "*"}
    assert only["Action"] in ("s3:GetObject", ["s3:GetObject"])
    assert "/site/*" in json.dumps(only["Resource"])
    assert "aws:SecureTransport" not in json.dumps(template.to_json())

def test_website_hosting_is_enabled_without_public_acls() -> None:
    bucket = list(synth().find_resources("AWS::S3::Bucket").values())[0]["Properties"]
    assert bucket["WebsiteConfiguration"] == {"IndexDocument": "index.html",
                                              "ErrorDocument": "index.html"}
    assert bucket["PublicAccessBlockConfiguration"] == {
        "BlockPublicAcls": True, "IgnorePublicAcls": True,
        "BlockPublicPolicy": False, "RestrictPublicBuckets": False}
```

- [ ] **Step 2：執行並確認紅燈**

```bash
uv run pytest tests/unit/test_infra_site_hosting.py -q
```

預期：FAIL，Phase 09 建立的 bucket 還沒有 website 設定與 bucket policy。

- [ ] **Step 3：修改 Phase 09 的 CDK**

在 `infra/training_kb_data_stack.py` 既有的 `s3.Bucket(...)` 加上 `website_index_document="index.html"`、`website_error_document="index.html"`，把 `block_public_access` 由 `s3.BlockPublicAccess.BLOCK_ALL` 改成 `s3.BlockPublicAccess(block_public_acls=True, ignore_public_acls=True, block_public_policy=False, restrict_public_buckets=False)`，並把 `enforce_ssl=True` 改成 `enforce_ssl=False`。再用 `bucket.add_to_resource_policy(iam.PolicyStatement(effect=iam.Effect.ALLOW, principals=[iam.AnyPrincipal()], actions=["s3:GetObject"], resources=[bucket.arn_for_objects("site/*")]))`，最後以 `CfnOutput` 輸出 `bucket.bucket_website_url` 並在說明寫「只有 HTTP」。**`enforce_ssl=False` 是本 Phase 的明確決定，理由要寫進程式註解：** 設計 §9.3 只有一個 bucket，`enforce_ssl=True` 會加一段「非 HTTPS 一律 Deny」的 bucket policy，而 S3 website endpoint 只提供 HTTP（設計 §13、§17.1），兩者同時存在時公開頁永遠讀不到。關掉它不會讓私有前綴變成公開：`tutorials/`、`operations/`、`stepfunctions/`、`demo/previews/` 沒有任何 Allow 語句，只有 `site/*` 有；程式與 Lambda 透過 SDK 存取本來就走 HTTPS。**不得因此宣稱本站提供 HTTPS。** 同時更新 [Phase 09](./09-Phase09-AWS資料資源與最小IAM.md) 的 `tests/unit/test_data_stack.py`：原本斷言四道 Block Public Access 全為 `True`，改成與上面相同的新值，並保留「萬用字元只掃 `AWS::IAM::Policy`」那條測試。

- [ ] **Step 4：跑測試並補整站掃描**

補一個整合測試：用 `Repository.put_object` 把 `demo/site_assets/*` 寫到 `ASSET_KEYS`、把整站渲染結果寫到本機假 S3，然後斷言 `site/` 底下沒有任何物件含 `data-published="false"`、沒有 `reason` 字串，且每個站內 `href` 都對得到已產生的 key。`cdk synth` 通過只代表 template 合法，不代表已部署。執行 `uv run pytest tests/unit/test_infra_site_hosting.py tests/unit/test_data_stack.py tests/integration/test_site_widget_roundtrip.py -q`，預期整個檔案全綠。

- [ ] **Step 5：提交**

```bash
git add infra/training_kb_data_stack.py tests/unit/test_infra_site_hosting.py tests/unit/test_data_stack.py tests/integration/test_site_widget_roundtrip.py
git commit -m "feat(infra): 只公開 site 前綴的靜態教學站"
```

## 8. 驗收矩陣

| 路徑 | 輸入 | 預期資料結果 |
|---|---|---|
| Happy | 已發布 v3、`supersedes=v2` | 頁面含 `/site/tutorials/prepare-meeting/v3.diff.txt`、版本紀錄連結與 `data-published="true"`。 |
| Happy | v1、`supersedes=None` | 顯示「第一版，沒有前一版可比較」，沒有 `v0` 連結。 |
| Failure | v3 但 `supersedes=None` | `PermanentError`；不輸出頁面。 |
| Failure | 步驟文字含 `<script>` | 只輸出 `&lt;script&gt;`，沒有可執行標籤。 |
| Boundary | retired 且 successor 為自身或空；版本清單含未發布版本；widget 未填 ID／未選評分 | 顯示 `RETIRED_NOTICE` 與原文、不顯示後繼連結、widget 完全消失；索引只列已發布版本；widget 不產生檔案也不顯示已送出。 |
| Privacy | 整站渲染後掃描 `site/` | 沒有 `data-published="false"`、沒有 `reason`／`release:`、沒有回饋留言原文與穩定使用者 ID。 |

人工驗收：用 website endpoint 在瀏覽器開一次版本頁、版本紀錄頁與退役頁，實際按下下載按鈕，打開下載的 JSON 逐欄位對照 Phase 42 的必填欄位（`id`、`tutorial_version`、`rating`、`user`），確認 `rating` 在檔案裡是 `4` 而不是 `"4"`。不能只看測試顯示 PASS。

## 9. 常見錯誤與停止條件

| 症狀 | 原因 | 修正／停止 |
|---|---|---|
| widget 顯示「已送出」或「感謝回饋」 | 把產生檔案當成提交成功 | 改回固定文案「檔案已產生，尚未送出」；未改正前不得展示。 |
| 未發布版本能從 website URL 讀到 | 渲染後直接寫 `site/` | 停止公開路徑；只有 `commit` 成功才寫，並補 `data-published` 掃描測試。 |
| 頁面印出 `release:r_42` 或 `gap:c12` | 把 `reason` 當版本說明顯示 | 停止：`reason` 是私有欄位（00A §3.3）；公開頁只顯示版號與差異連結。 |
| 版本選擇列出 `v1..vN`，或 href 寫成 `/site/<slug>/v3.html` | 用版號推算連結、自己接字串而不用 Phase 24 的 helper | 改用 `supersedes`、`current_version` 與版本紀錄頁（版號可能有缺口）；key 一律用 `site_key`／`tutorial_index_key`／`site_index_key`（D-54）。 |
| 退役頁自動跳到 successor | 用 `meta refresh` 或 JS 轉址 | 改成可點連結；測試斷言頁面不含 `http-equiv`。 |
| 頁面被寫成 HTTPS 網站，或 bucket policy 用 `<bucket>/*` | 混淆 website endpoint 與 CloudFront、照抄官方整桶公開範例 | 文件與畫面都寫 HTTP（要 HTTPS 須另案評估）；Resource 改成 `site/*`，`tutorials/`、`operations/` 一旦可公開讀即停止部署。 |

## 10. 來源與 Rule 對照

- [發布教學版本.feature](../../spec/features/發布教學版本.feature)
  - Rule 2：「發布的教學透過 S3 靜態 docs 站提供」→ **primary 在本 Phase**；Task 4 的 bucket policy 測試與整站掃描直接斷言公開 key 只在 `site/`。[Phase 24](./24-Phase24-單篇教學發布提交.md) 的最小 renderer 與 [Phase 60](./60-Phase60-安全檢查與端到端完成證據.md) 的 `check_public` 掃描為相關。
  - Rule 3：「發布的教學提供 feedback widget」→ **primary 在本 Phase**；Task 3 的守門測試與 roundtrip 測試直接斷言 widget 存在且產出可匯入。
- [收集教學回饋.feature](../../spec/features/收集教學回饋.feature)
  - Rule 2：「已退役教學的既有版本拒絕新回饋」、Rule 3：「Feedback 的 rating 只能為 1 到 5 的整數」、Rule 9：「Feedback 接入時必須提供穩定使用者 ID」→ 三條都是 **相關（primary 在 [Phase 42](./42-Phase42-Feedback與View固定匯入.md)）**：本 Phase 只斷言退役頁不出現 widget 與下載元素（Task 2）、widget 產生的 `rating` 是 1–5 的數字型別、未填穩定使用者 ID 就不產生檔案（Task 3）；拒絕與欄位驗證都在匯入入口。
- [建立教學版本.feature](../../spec/features/建立教學版本.feature) Rule 7：「與前版的 diff 儲存在 `tutorials/<slug>/v<n>.diff`」→ **相關（primary 在 [Phase 22](./22-Phase22-Markdown與Diff私有產物.md)）**；本 Phase 只負責 v1 空 diff 的畫面文案與公開副本 key（Task 1）。
- 設計 §8.2（v1 空 diff 文案）、§8.4（退役顯示與 successor）、§9.3（`site/` 僅發布流程可寫）、§13（S3 docs 站唯一入口、下載尚未送出、只有 HTTP、私有資料不公開）、§17.1（website endpoint 不提供 HTTPS）、§17.2（跳脫不可信內容、公開區不含回饋原文與穩定使用者 ID）。
- [S3 static website 權限設定](https://docs.aws.amazon.com/AmazonS3/latest/userguide/WebsiteAccessPermissionsReqd.html)：官方範例的 `Resource` 是整桶 `/*`，本案刻意縮到 `site/*`；[S3 website endpoints](https://docs.aws.amazon.com/AmazonS3/latest/userguide/WebsiteEndpoints.html)：不提供 HTTPS。
- [AWS CDK aws_s3.Bucket](https://docs.aws.amazon.com/cdk/api/v2/python/aws_cdk.aws_s3/Bucket.html)：`website_index_document`、`block_public_access`、`enforce_ssl`、`add_to_resource_policy`、`arn_for_objects`、`bucket_website_url`。

## 11. 完成清單

- [ ] `SiteRenderer` 三個方法簽名與 Phase 24 完全相同，且 `SiteRenderer()` 仍可無參數建構。
- [ ] 公開 key 全部由 Phase 24 的 `site_key`／`tutorial_index_key`／`site_index_key` 與本 Phase 的 `site_diff_key` 組出，佈局是 `site/tutorials/<slug>/...`。
- [ ] 版本頁有版本選擇、差異連結與版本紀錄連結；v1 顯示固定的無前版文案；頁面不含 `reason`。
- [ ] 退役頁使用 Phase 26 的 `RETIRED_NOTICE`、保留原文、只在合法 successor 時顯示連結且不自動跳轉。
- [ ] widget 只產生檔案、狀態固定為「檔案已產生，尚未送出」，下載檔通過 Phase 42 驗證；不引 CDN、不含金鑰、不用 `innerHTML` 放使用者文字。
- [ ] bucket policy 只公開 `site/*`，`enforce_ssl=False` 的理由已寫進程式註解，Phase 09 的測試同步更新。
- [ ] 文件與畫面都把 website endpoint 寫成 HTTP，沒有宣稱 HTTPS；也沒有把單元測試 PASS 說成 O3 發布故障驗收已通過或網站已部署。
