# Phase 57：S3 靜態教學站與回饋下載實作計畫

> **給實作者：** 依 checkbox 逐步執行；每個 Task 先建立失敗測試，再寫最小實作。執行時使用 `superpowers:executing-plans` 或同等逐項流程。

> **現況核對（2026-09-14，Phase 41–60 批次 W0）：**
>
> **（a）已存在、可直接用的東西**
>
> - `src/training_kb/site.py`（P24 建、P26＋修正波 `f1ef75a` 擴充）：`SiteRenderer.__init__(*, notice="", batch="", categories=(), asset_prefix="/site/assets")`、三個 render 方法（簽名與 00A §6.7 逐字相同）、`RETIRED_PLACEHOLDER`（＝`RETIRED_NOTICE` 的別名）、`SUCCESSOR_PREFIX = "改看："`、`_SECTIONS`、`_items`、`_successor_line`、`_retired_block`、`_version_number`。
> - `src/training_kb/publishing.py`（P24／P25）：`site_key`／`tutorial_index_key`／`site_index_key`（D-54）、**`_diff_copy_key(version_id)` 已經回 `tutorials/<slug>/v<n>.diff.txt`**（docstring 明寫「Phase 57 的 `site_diff_key` 回同一個字串」）、`_public_key`、`public_site_keys`、`UNPUBLISHED_MARKER = b'data-published="false"'`、`promote_site_objects`、`Publisher.prepare/inspect/commit`、`SITE_PAGE_CONTENT_TYPE`、`SITE_TUTORIALS_DIR`。
> - `src/training_kb/content.py`：`PUBLIC_SITE_PREFIX = "site/"`（P22，**不是** P24）、`RETIRED_NOTICE`、`parse_version_id`、`diff_key`、`markdown_key`。
> - `src/training_kb/errors.py`：`PermanentError`、`ContentError`、`PublishError`（**注意：`PublishError` 直接繼承 `Exception`，不是 `PermanentError` 的子類**）、`ObjectAlreadyExists`。
> - `infra/training_kb_data_stack.py`（P09）：`TrainingKbDataStack`、`PRIVATE_PREFIXES = ("tutorials/", "operations/", "stepfunctions/", "demo/previews/")`、bucket（`BLOCK_ALL` ＋ `enforce_ssl=True`）、資料角色、三個 `CfnOutput`。
> - `tests/unit/test_data_stack.py`（P09）、`tests/unit/test_site_renderer.py`（P24）、`tests/unit/test_retired_page.py`＋`tests/unit/test_retire_tutorial.py`（P26）已經存在並鎖住多條斷言，見（b）。
>
> **（b）文件因上一批裁決／實作而修正的點（逐條）**
>
> 1. **`site.py` 不得 import `publishing`（會循環）。** `publishing.py` 第 74 行是 `from training_kb.site import SiteRenderer`；`site.py` 的模組 docstring 也明寫「反向 import（`site` → `publishing`）一律禁止」。→ **§7 Task 1 Step 4 原本要 `from training_kb.publishing import site_key, tutorial_index_key` 的寫法不成立**，改用瀏覽器相對 href（詳見 §6 新增的說明與 D-78）。
> 2. **站內 href 一律是瀏覽器相對路徑，不是絕對的 `/site/...`（00A D-78）。** 既有測試已經鎖死：`tests/unit/test_retired_page.py::test_retired_page_links_to_the_successor_tutorial_index` 與 `tests/unit/test_retire_tutorial.py:284` 都斷言 `<a href="../{successor}/index.html">`。**這兩支是 P26 的測試檔，本 Phase 依 COMMON.md R3.6 不得修改。** → §2／§7／§8 裡的 `href="/site/tutorials/.../v3.diff.txt"`、`href="/site/tutorials/.../index.html"` 全部改成同目錄相對形式（`v3.diff.txt`、`v2.html`、`index.html`）。
> 3. **`tests/unit/test_retired_page.py::test_tutorial_index_omits_the_link_when_the_successor_was_rejected` 斷言 `"index.html" not in page`**（沒有 successor 的退役教學索引頁）→ **`render_tutorial_index` 不得加「回站台索引」的連結**，本 Phase 的索引改版要繞開這一條。
> 4. **`render_version_page` 的退役區塊留著。** REP §8 第 8 項寫「`render_version_page` 那份要拿掉或改成只在未發布的預覽有意義」，但修正波 `f1ef75a` 的實際選擇是**兩處都輸出**（`site.py` docstring：「退役提示同時出現在版本頁與教學索引（controller 裁決 2026-09-14）」），而且 P26 的四個版本頁測試（`test_retired_page_shows_notice_and_optional_successor` 等）正在守它。拿掉會紅燈且要改別人的測試 → **本 Phase 不拿掉**。00A §6.7 那句「版本頁維持不變」指的是 D-83 的修正沒有動版本頁，不是要求移除。
> 5. **`site_diff_key` 的落點是 `training_kb.publishing`，不是 `site.py`**（00A §6.7 的程式區塊把它列在「三個公開 key helper 都在 `training_kb.publishing`」那一段；controller 的 preflight conflict scan 也記「publishing.py（`site_diff_key` by P57）」）。實作時讓它**成為既有 `_diff_copy_key` 的公開名稱**（把 `_diff_copy_key` 改成呼叫 `site_diff_key`，或直接改名並保留內部呼叫點），**不要在兩支檔各寫一份字串**。→ §4 的「`src/training_kb/site.py` … `site_diff_key`」已更正。
> 6. **`render_version_page` 目前**輸出 `data-published`、`data-slug`、`data-version-id` 三個屬性，**沒有 `data-retired`**；本 Phase 要加 `data-retired`。`render_tutorial_index` 目前輸出 `data-site-version`、`data-slug`，並且印**完整的 `version_id` 字串**（`tests/unit/test_site_renderer.py::test_render_tutorial_index_lists_only_published_versions` 斷言 `V1 in page`、`V2 not in page`）→ 改版時要保留 `data-site-version` 與完整 `version_id` 文字。
> 7. **`_diff_block` 丟的錯是 `PermanentError`**（00A §6.7 P57 列明文），不是 `PublishError`；但 `render_version_page` 既有的「已保存步驟與公開內容不同步」仍然丟 `PublishError`（P24 既有行為，不動）。兩者並存，§5 Consumes 已補註。
> 8. **`tests/unit/test_data_stack.py` 有四條會被本 Phase 改動打到**，§7 Task 4 已逐條列出（原文只提了 Block Public Access 一條）。
> 9. `import_feedback`／`import_view`／`ImportResult`（P42）與 `approved_categories`（P43）**目前都不存在**（P42 在 **W2**、P43 在 **W3**，本 Phase 在 **W1**）→ §7 Task 3 的 roundtrip 測試在 W1 寫不出來，處理方式見 Task 3 的改寫。
> 10. `PUBLIC_SITE_PREFIX` 的 owner 是 **P22**（在 `content.py`），§5 Consumes 原寫 Phase 22 正確；但 §4／§6 把三個 key helper 說成 Phase 24 產出、放在 `publishing.py` 才是對的（`site.py` 裡沒有 key helper，00A §3.2 那一列的「公開頁 key helper」措辭與 D-54 衝突，已回報 controller）。
>
> **（c）gate 現況對本 Phase 的影響**（COMMON.md §2）
>
> - **O3 FAIL**（P12；報告 `docs/plan/report/o3-20260914t181109z.md`、00A D-80）→ 本 Phase 照協定 A 實作與驗證，真實 AWS 上跑到發布切點就把觀察到的結果**原樣記錄**；**不得宣稱 O3 PASS**，頁面打得開也不算。F49 不放寬。
> - **O5 BLOCKED** → 本 Phase 不呼叫模型，直接影響為零；但真實 AWS 端到端演練若要先有一篇已發布教學，走 pipeline 產生的那一段會在模型節點失敗（那是 O5 的 BLOCKED 證據，不是本 Phase 的 bug）。**替代做法**：用 `Publisher` 直接發布一篇由種子／測試資料建出來的版本，或直接 `put_object` 一份渲染好的頁面到 `site/` 來驗 website endpoint（兩種都要在報告寫清楚是哪一種）。
> - **O7 未到**（P56 首驗）→ 頁面的批次標示（`batch=`）只能照抄 `demo/seed` 的批次名稱，**不得**寫成「已核定」。
> - O1 provisionally accepted、O4 未到、O6 待核定：與本 Phase 無直接相依。
>
> **（d）適用的 controller 裁決（COMMON.md §3）**
>
> - **R1 真實 AWS 這一批要接**：本 Phase 要真的 `cdk deploy TrainingKbData`（`us-east-1`）並用 website endpoint **實際 HTTP 讀到頁面**，把回應存證（見 §7 Task 5 新增）。
> - **R3 同檔併行**：`publishing.py` 本波只有本 Phase 動（P59 在 W4）；`site.py`、`infra/training_kb_data_stack.py`、`demo/site_assets/` 只有本 Phase 動（controller preflight scan）。`tests/unit/test_data_stack.py` 是 P09 的既有檔，**只用 Edit**、只改必須改的斷言。
> - **R5**：本文件的程式碼片段是示意，00A ＋ 既有程式是契約。
> - **R6**：逐 Task 先紅燈再綠燈。**R9**：不派 subagent。
> - **R11 安全**：公開前綴只有 `site/`；私有前綴（`tutorials/`、`operations/`、`stepfunctions/`、`demo/previews/`）一旦可公開讀即停止部署。

**目標：** 把 Phase 24 的最小 renderer 擴充成完整教學站：版本選擇、與前版差異、版本紀錄、退役頁與回饋／瀏覽紀錄下載，並把公開範圍鎖死在 `site/` 前綴。

**架構：** `SiteRenderer` 是純函式渲染器，輸入既有實體與內容、輸出 HTML 字串，不讀寫 AWS；公開 key 一律由 Phase 24 的三個 helper 組出，哪些版本真的進 `site/` 由 Phase 24／25 的 `Publisher` 決定。widget 是純瀏覽器端 JavaScript，只在本機產生檔案交給維護者走 Phase 42 的固定匯入路徑，不發網路請求、不持有憑證。

**技術：** Python 3.12、`html.escape`、pytest、AWS CDK（S3 website hosting 與 bucket policy）、不依賴框架與 CDN 的純 JavaScript。

## 全域限制

- 唯一主來源是 [Training KB 設計 §8.2、§8.4、§9.3、§13、§17.1、§17.2](../../design/training-kb.md)。前置為 [Phase 56：O7 核定 Demo 種子資料](./56-Phase56-O7核定Demo種子資料.md)；另需 [Phase 24](./24-Phase24-單篇教學發布提交.md) 的 `SiteRenderer` 最小版與三個公開 key helper、[Phase 25](./25-Phase25-多篇教學整批發布.md) 的整批 `Publisher`、[Phase 26](./26-Phase26-教學退役與後繼導向.md) 的 `retire_tutorial` 與退役文案常數、[Phase 42](./42-Phase42-Feedback與View固定匯入.md) 的匯入契約。前置未通過時停止。下一階段是 [Phase 58：Demo 控制台與規則開關預覽](./58-Phase58-Demo控制台與規則開關預覽.md)。
- 本階段不做：不改 `SiteRenderer` 三個方法的簽名；不重新定義 `site_key`／`tutorial_index_key`／`site_index_key`（[Phase 24](./24-Phase24-單篇教學發布提交.md) 產出，本 Phase 只消費）；不建立第二個公開入口、公開讀取 API 或任何寫入端點；不加 CloudFront 或 HTTPS 託管；不建立版本、不發布、不判定門檻；不在瀏覽器端呼叫 AWS 或 Bedrock。
- 與本 Phase 有關的 O1–O7 gate 狀態（O1–O7 是設計 §18 的七個待確認事項編號）：**O3（S3 與 DynamoDB 發布提交）現況是 FAIL**（現況核對 2026-09-14：原寫「仍待 Phase 12 的整合驗證」，實際 P12 已跑完並判 **FAIL**，P24／P25 已依協定 A 實作於 moto 並重現五個切點；報告 `docs/plan/report/o3-20260914t181109z.md`、00A D-80）。本 Phase 只決定「渲染什麼」與「公開哪些 key」，**不得宣稱發布故障驗收已通過**，也不能因為頁面打得開就說 O3 PASS；**F49 不放寬**。O7（核定種子與外部設定）**未到**，首驗在 [Phase 56](./56-Phase56-O7核定Demo種子資料.md)，頁面批次標示只能照抄 `demo/seed` 的批次名稱，**不得寫成「已核定」**。O5 **BLOCKED**（Titan／Claude 皆 `ValidationException: Operation not allowed`，報告 `docs/plan/report/o5-20260915T030245Z.md`）：本 Phase 不呼叫模型，但真實 AWS 演練若靠 pipeline 產生教學會在模型節點失敗，見前言現況核對 (c) 的替代做法。
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
[查看與 v2 的差異] -> v3.diff.txt          （現況核對 2026-09-14：原寫絕對路徑
                                            /site/tutorials/prepare-meeting/v3.diff.txt）
這篇有幫助嗎？[1][2][3][4][5]  類別：[找不到按鈕][缺少資訊][未選擇]
留言：____  你的穩定使用者 ID：____（必填）
[下載回饋檔案，交由維護者匯入] [下載瀏覽紀錄]  狀態：檔案已產生，尚未送出
```

**（現況核對 2026-09-14：站內 href 一律相對，不是絕對 `/site/...`。）** 版本頁公開在 `site/tutorials/<slug>/v<n>.html`，所以上一版是同目錄的 `v2.html`、差異檔是 `v3.diff.txt`、版本紀錄頁是 `index.html`；後繼教學是上一層再下去的 `../<successor>/index.html`（00A D-78，P26 的兩支既有測試已經鎖死）。三個理由：(i) `site.py` 不能 import `publishing`（`publishing.py` 已經 import `SiteRenderer`，反向 import 會循環）；(ii) 00A §3.4 明文「任何 Phase 都不得自己用 `PUBLIC_SITE_PREFIX` 接字串拼出這四個 key」，而 href 不是 key，相對路徑不碰這條；(iii) 相對 href 在 website endpoint 與任何前綴掛載下都成立。**站台索引** `site/index.html` 從版本頁看是 `../../index.html`——但 `render_tutorial_index` **不得**輸出它（`tests/unit/test_retired_page.py::test_tutorial_index_omits_the_link_when_the_successor_was_rejected` 斷言 `"index.html" not in page`），版本頁要不要放由實作者決定、放了要補測試。頁面**不顯示 `TutorialVersion.reason`**：`release:r_42`、`gap:c12` 這種字串帶有內部識別碼，屬私有欄位（設計 §13、00A §3.3）。對 `prepare-meeting@v1`，差異區塊固定是「第一版，沒有前一版可比較」；對 `status="retired"` 的 Tutorial，整個評分與留言區消失，改成 Phase 26 的固定文案「此教學已退役，內容僅供歷史查閱。」。

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
| 修改 | `src/training_kb/site.py` | `SiteRenderer` 完整版、`escape_text`、`SITE_PREFIX`／`ASSET_KEYS`／`NO_PREVIOUS_TEXT`／`NOT_SENT_TEXT` 四個公開常數。（現況核對 2026-09-14：原本把 `site_diff_key` 也列在這裡，實際落點是 `publishing.py`，見下一列。） |
| 修改 | `src/training_kb/publishing.py` | `site_diff_key(version_id) -> "tutorials/<slug>/v<n>.diff.txt"`（00A §6.7 把它列在「三個公開 key helper 都在 `training_kb.publishing`」那一段，controller preflight scan 同）。**既有的私有 `_diff_copy_key` 回的就是同一個字串**，實作時把它改成公開名稱並讓 `_public_pairs` 用同一個函式，不要留兩份。 |
| 建立 | `demo/site_assets/widget.js`、`demo/site_assets/style.css` | 產生回饋與瀏覽紀錄檔案、版面樣式；不連網、不含金鑰、不 `@import` 外部資源。（現況核對 2026-09-14：`demo/` 目前整個不存在；這兩支是**純資產**，測試只用 `Path(...).read_text()` 讀，**不需要** `demo` 可 import——P56 才需要那件事。） |
| 修改 | `infra/training_kb_data_stack.py` | website hosting、放寬 Block Public Access、`enforce_ssl=False`、只公開 `site/*` 的 bucket policy，**以及資料角色的 `site/` 寫入權限**（REP §8 第 6 項，見 §7 Task 4 Step 3 的分工說明）。 |
| 修改 | `tests/unit/test_data_stack.py` | [Phase 09](./09-Phase09-AWS資料資源與最小IAM.md) 的既有測試。（現況核對 2026-09-14：原文只提 Block Public Access 一條，實際有 **四條** 會被打到，逐條列在 §7 Task 4 Step 3。） |
| 測試 | `tests/unit/test_site_pages.py` | 版本頁、索引頁、退役頁與跳脫。 |
| 測試 | `tests/unit/test_site_assets.py`、`tests/unit/test_infra_site_hosting.py` | 資產守門與 CDK 公開範圍。 |
| 測試 | `tests/integration/test_site_widget_roundtrip.py` | 下載檔走完 Phase 42 匯入與整站掃描。 |

`SiteRenderer` 的模組路徑是 `src/training_kb/site.py`（00A 的 D-17，owner 是 Phase 24）；類別與三個方法名稱不可改。

## 5. 固定介面

### Consumes

```text
# 已存在（可直接 import）
training_kb.errors      PermanentError（_diff_block 缺 supersedes 時丟這個，00A §6.7）
                        PublishError  ← 直接繼承 Exception，**不是** PermanentError 子類；
                                         render_version_page 既有的「步驟不同步」丟它，不動
training_kb.models      TutorialContent(title, problem, prerequisites, steps,       # P03
                                        expected_outcome)
                        Tutorial(slug, current_version, topic, feature_ids,
                                 status, successor, cluster_id)
                        TutorialVersion(version_id, slug, supersedes, reason,
                                        rules_applied, s3_key, published_at)
                        TutorialStep(tutorial_version, number, type, text,          # P04
                                     feature_id) / TutorialStatus（StrEnum，成員大寫）
training_kb.repository  Repository.put_object(key, body, content_type, *,           # P07
                                              if_none_match)  ← if_none_match 無預設值
infra.training_kb_data_stack
                        TrainingKbDataStack、PRIVATE_PREFIXES、TABLE_NAME            # P09
training_kb.content     parse_version_id(value) -> tuple[str, int]                  # P20
                        PUBLIC_SITE_PREFIX = "site/"                                # P22
                        RETIRED_NOTICE = "此教學已退役，內容僅供歷史查閱。"           # P26
training_kb.publishing  site_key(version_id)        -> "tutorials/<slug>/v<n>.html"  # P24 D-54
                        tutorial_index_key(slug)    -> "tutorials/<slug>/index.html"
                        site_index_key()            -> "index.html"
                        _diff_copy_key(version_id)  -> "tutorials/<slug>/v<n>.diff.txt"
                                                       ← 本 Phase 的 site_diff_key 就是它
                        Publisher.prepare / inspect / commit、promote_site_objects、
                        public_site_keys、UNPUBLISHED_MARKER
                        ！site.py 不得 import 這支檔（publishing 已 import site，會循環）
training_kb.site        SiteRenderer.render_version_page / render_tutorial_index /
                        render_site_index（簽名不得更動）、_retired_block、_successor_line

# 本批才會出現（現況核對 2026-09-14：目前 src/ 裡一個都沒有）
training_kb.ingress     import_feedback(payload, *, repository, operations, now,
                                        writer=None) -> ImportResult                # P42（W2）
                        import_view(...) -> ImportResult
                        ImportResult(status, object_id, message, invalid_fields)
                        approved_categories(repository) -> frozenset[str]           # P43（W3）
```

### Produces

```python
SITE_PREFIX = "site/"                       # 與 Phase 22 的 PUBLIC_SITE_PREFIX 同值
ASSET_KEYS = ("site/assets/style.css", "site/assets/widget.js")
NO_PREVIOUS_TEXT = "第一版，沒有前一版可比較"
NOT_SENT_TEXT = "檔案已產生，尚未送出"

def escape_text(value: str) -> str: ...          # site.py

# 現況核對 2026-09-14：落點是 publishing.py（00A §6.7 的「三個公開 key helper 都在
# training_kb.publishing」那一段；既有私有名稱 _diff_copy_key 回同一個字串，改成公開即可）
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

四個 helper 回的都是**不含 `site/` 前綴**的相對 key；公開物件是 `PUBLIC_SITE_PREFIX + <相對 key>`。**（現況核對 2026-09-14：原文接著寫「頁面裡的 `href` 再補一個開頭的 `/`，所以 v3 的差異連結是 `/site/tutorials/prepare-meeting/v3.diff.txt`」——這條不成立。）** key 與 href 是兩層東西：

```text
  S3 key（publishing.py 的 helper 算）        頁面裡的 href（site.py 直接寫，同目錄）
  site/tutorials/prepare-meeting/v3.html      （本頁）
  site/tutorials/prepare-meeting/v2.html      v2.html
  site/tutorials/prepare-meeting/v3.diff.txt  v3.diff.txt
  site/tutorials/prepare-meeting/index.html   index.html
  site/tutorials/share-summary/index.html     ../share-summary/index.html   ← D-78 既有
  site/index.html                             ../../index.html（只在版本頁；索引頁不得輸出）
```

`site.py` 產生 href 時**只用 `parse_version_id(version_id)[1]` 取版號**，不 import `publishing`（會循環：`publishing.py` 已經 `from training_kb.site import SiteRenderer`），也不用 `PUBLIC_SITE_PREFIX` 拼 key（00A §3.4 明文禁止）。這與 `_successor_line` 既有的 `../<slug>/index.html`（D-78）是同一套規則，兩處一致。公開差異檔的內容就是 Phase 22 私有 `tutorials/<slug>/v<n>.diff` 的逐字副本，複製動作屬發布路徑（Phase 24 `Publisher.commit`／Phase 25 `promote_site_objects`，`_public_pairs` 已經在做），本 Phase 只負責把 `_diff_copy_key` 改成公開的 `site_diff_key` 並在頁面產生相對連結。

渲染時機早於公開時機，所以 renderer 不能拿 `published_at` 當守門條件（`prepare` 階段它必然是 `None`）。改用可機器檢查的標記：`published_at is None` 的頁面帶 `data-published="false"`，只存在於私有 staging；`Publisher.commit` 只把 `true` 的頁面寫進 `site/`；整合測試掃描 `site/` 全部物件，出現 `false` 即失敗。**重新渲染的責任不在本 Phase：** 依 00A §6.7，`Publisher.commit` 在交易成功後、寫 `site/` 前，用已切換的 `published_at` 重新渲染並覆寫同一個 staging key，再由 promote 複製同一份 bytes；本 Phase 只讓 renderer 把標記印出來。版本選擇則只用 `render_version_page` 拿得到的資料組出來。**本計畫選擇：** 顯示「上一版（`version.supersedes`）」「本頁」「目前版本（`tutorial.current_version`）」，再加一個指向 `tutorial_index_key(slug)` 的版本紀錄連結，完整清單只放在版本紀錄頁；理由是設計 §8.1 允許永久失敗留下版號缺口，用 `v1..vN` 推算會產生死連結。`supersedes is None` 顯示 `NO_PREVIOUS_TEXT`，但版號大於 1 卻缺 `supersedes` 代表資料不完整，丟 `PermanentError`，不要靜默顯示成第一版。

退役頁依設計 §8.4：原文逐字保留，加上 Phase 26 的固定過期說明常數 `RETIRED_NOTICE`（兩份文件共用同一個常數，不各寫一份字面值）。設計 §8.4 寫「顯示過期原因」，但 §13 明訂上游 ID 與執行紀錄屬私有，所以公開頁只印固定說明，不印 `reason`、Release ID 或日期。只有 `tutorial.successor` 去頭尾後非空且不等於自身時才顯示後繼連結，而且是可點連結，沒有 `meta refresh`、沒有 JavaScript 轉址。退役頁不輸出評分、類別、留言與任何下載按鈕，widget.js 讀到 `data-retired="true"` 就整段停用（**本計畫選擇：** 退役頁只保留歷史原文，連瀏覽紀錄也不再收集）。所有進入 HTML 的動態文字都先過 `escape_text`；頁面不引入 Markdown 轉 HTML 轉換器，直接用 `TutorialContent` 的結構欄位組標籤。

**（現況核對 2026-09-14）退役區塊已經寫好了，本 Phase 只加 `data-retired` 與停用 widget。** `site.py` 的 `_retired_block(tutorial)`＋`_successor_line(successor)` 已經實作了上面整段判斷（`status != RETIRED` 回空字串、`successor is None` 不輸出連結、輸出經 `escape`、href 是 `../<slug>/index.html`），而且**同時掛在 `render_version_page` 與 `render_tutorial_index`**（修正波 `f1ef75a`，D-83）。P26 的 `tests/unit/test_retired_page.py`（九個測試）與 `tests/unit/test_retire_tutorial.py:284` 正在守這些行為，**本 Phase 依 R3.6 不得修改那兩支測試檔**，所以：

- **不重寫** `_retired_block`／`_successor_line` 的判斷與輸出字串，只在版本頁最外層加 `data-retired="true|false"`。
- **不把版本頁的退役區塊拿掉**（REP §8 第 8 項提過「拿掉或改成只在未發布的預覽有意義」，修正波的實際選擇是兩處都留；拿掉會讓 P26 的四個測試紅燈）。
- `successor` **等於自身**時不顯示連結：**現有 `_successor_line` 沒有這一條**（P26 的 `resolve_successor` 在寫入前已經擋掉，renderer 不再判一次）。本 Phase §7 Task 2 Step 4 的「successor 等於自身」案例若要成立，加判斷時**不能**改動既有輸出字串，而且要確認 P26 的四個 successor 測試仍然全綠。**本計畫選擇：** 照 `site.py` 現有註解的理由（責任在 `resolve_successor`）**不加**這一條判斷，改成在測試裡斷言「renderer 原樣輸出」，並在報告寫明分工；若實作者選擇加，必須先跑 `uv run pytest tests/unit/test_retired_page.py tests/unit/test_retire_tutorial.py -q` 確認沒有紅燈。

## 7. TDD Tasks

### Task 1：版本頁的版本選擇、差異與未發布標記

- [ ] **Step 1：建立失敗測試**（`renderer` fixture 是 `SiteRenderer(notice="合成資料示範", batch="demo-seed-01", categories=("找不到按鈕", "缺少資訊"))`；`make_version` 建 `TutorialVersion`，`published_at` 預設是一個 aware datetime）

```python
from training_kb.site import NO_PREVIOUS_TEXT, SiteRenderer

def test_version_page_links_previous_diff(renderer, tutorial, steps, content):
    version = make_version("prepare-meeting@v3", supersedes="prepare-meeting@v2")
    page = renderer.render_version_page(tutorial, version, steps, content)
    assert 'data-published="true"' in page and "查看與 v2 的差異" in page
    # 現況核對 2026-09-14：原寫絕對 href（/site/tutorials/prepare-meeting/...），
    # 改成同目錄相對 href——site.py 不能 import publishing（會循環），D-78 同規則。
    assert 'href="v3.diff.txt"' in page
    assert 'href="v2.html"' in page and 'href="index.html"' in page
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

# 現況核對 2026-09-14：原本有一個 _href(relative_key) = "/" + SITE_PREFIX + relative_key，
# 並在 _diff_block 裡呼叫 site_diff_key()。兩者都拿掉：site.py 不能 import publishing
# （publishing.py 已經 from training_kb.site import SiteRenderer，反向 import 會循環），
# 頁面裡的 href 也不是 S3 key，只是同目錄檔名（D-78 的 ../<slug>/index.html 同一套規則）。
def _page_href(version_id: str, suffix: str) -> str:
    """同目錄檔名：`v<n>.html`／`v<n>.diff.txt`。"""
    return f"v{parse_version_id(version_id)[1]}{suffix}"

def _diff_block(version) -> str:
    _, number = parse_version_id(version.version_id)
    if version.supersedes is None:
        if number != 1:
            raise PermanentError(f"{version.version_id} 缺少 supersedes")
        return f'<p class="diff-note">{escape_text(NO_PREVIOUS_TEXT)}</p>'
    _, previous = parse_version_id(version.supersedes)
    return (f'<p class="diff-note"><a href="{_page_href(version.version_id, ".diff.txt")}">'
            f"查看與 v{previous} 的差異</a></p>")
```

`site_diff_key(version_id)`（**S3 key**，含 `tutorials/` 不含 `site/`）在 `publishing.py`：把既有的 `_diff_copy_key` 改成這個公開名稱，`_public_pairs` 改呼叫它，一份字串兩個用途。

- [ ] **Step 4：補版本選擇與跳脫後跑綠燈**

`_version_switch(tutorial, version)` 組出三段：`version.supersedes` 非空時是 `_page_href(version.supersedes, ".html")` 的「上一版 vN」、本頁版號（等於 `tutorial.current_version` 時加「（目前版本）」）、以及 `href="index.html"` 的「查看版本紀錄」。（現況核對 2026-09-14：原文要 `from training_kb.publishing import site_key, tutorial_index_key` 再套 `_href(...)`，**那會造成 `site` ↔ `publishing` 循環 import**——`publishing.py` 第 74 行已經 `from training_kb.site import SiteRenderer`，而 `site.py` 的模組 docstring 也明寫反向 import 一律禁止。三個 key helper 仍然是 D-54 的唯一 key 來源，只是它們算的是 **S3 key**，頁面裡的是 **href**，兩層分開。）

`render_version_page` 的最外層元素固定帶 `data-published`（`version.published_at is not None` 轉成 `"true"`／`"false"`）、**新增的 `data-retired`**、`data-slug`、`data-version-id`（現況核對 2026-09-14：前者與後兩者**已經存在**，只有 `data-retired` 是本 Phase 新增），接著依序輸出橫幅（`notice`、`batch`）、標題、版本選擇、`_diff_block`、五段內容與 widget 區塊；`version.reason` 不進頁面。**`_retired_block(tutorial)` 維持在 `</article>` 之前**（P26 的既有位置，不搬動）。標題、步驟文字與所有動態欄位一律經 `escape_text`；加入惡意文字案例：步驟文字為 `<script>alert(1)</script>` 時輸出只含 `&lt;script&gt;`。

**改完一定要跑別人的既有測試**（本 Phase 換的是 `SiteRenderer` 的實作，P24／P26 的測試就掛在上面）：

```bash
uv run pytest tests/unit/test_site_pages.py tests/unit/test_site_renderer.py \
              tests/unit/test_retired_page.py tests/unit/test_retire_tutorial.py \
              tests/unit/test_publisher_single.py tests/unit/test_publisher_batch.py -q
```

其中已經鎖死、**不得改測試只能改實作去滿足**的有：`data-published="true"/"false"` 兩個標記、`data-site-version="v<n>"`、版本頁與教學索引都輸出 `class="retired"`＋`RETIRED_NOTICE`、後繼連結逐字是 `<a href="../<successor>/index.html">`、教學索引在沒有 successor 時**整頁不含 `index.html`**、教學索引印完整 `version_id` 字串且只列已發布版本、`render_version_page` 對步驟不同步仍丟 `PublishError`、頁面不含 `reason`／`c12`／`operations/`。

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
    # 現況核對 2026-09-14：原寫 'href="/site/tutorials/share-summary/index.html"'。
    # D-78 與 P26 的既有測試（test_retired_page.py、test_retire_tutorial.py:284）鎖的是
    # 相對形式；那兩支是別人的測試檔，本 Phase 不得改（R3.6）。
    assert 'href="../share-summary/index.html"' in page
    assert "http-equiv" not in page and "tkb-download" not in page

def test_tutorial_index_hides_unpublished_versions(renderer, tutorial):
    v1 = make_version("prepare-meeting@v1", supersedes=None, published_at=NOW)
    draft = make_version("prepare-meeting@v2", supersedes="prepare-meeting@v1",
                         published_at=None)
    page = renderer.render_tutorial_index(tutorial, [v1, draft])
    assert 'href="v1.html"' in page          # 同上：同目錄相對 href
    assert "v2.html" not in page
    assert "prepare-meeting@v1" in page      # P24 的既有斷言：索引印完整 version_id
```

- [ ] **Step 2：執行並確認紅燈**

```bash
uv run pytest tests/unit/test_site_pages.py -q
```

預期：FAIL，退役橫幅與索引過濾都還不存在。

- [ ] **Step 3：建立最小實作**

**（現況核對 2026-09-14：這一整段大部分已經做完了。）** 原文要新建的 `_retired_banner(tutorial)` 就是既有的 `site.py::_retired_block(tutorial)`＋`_successor_line(successor)`：它已經在 `status != TutorialStatus.RETIRED` 時回空字串、已經 `from training_kb.content import RETIRED_NOTICE`（不重抄字面值）、已經在 `successor is None` 時不輸出 `<a>`、已經 `escape` 過 slug，href 逐字是 `../<successor>/index.html`（D-78）。**不要重寫它，也不要改名。** 「`successor` 等於 `tutorial.slug` 時不顯示」這一條**現況沒有**（責任在 P26 的 `resolve_successor`），要不要加見 §6 的「本計畫選擇」。

本 Step 真正要新寫的只有：`_published_versions(versions)` —— 只保留 `published_at is not None`，依 `parse_version_id(v.version_id)[1]` 升序排序，連結用 **`_page_href(v.version_id, ".html")`** 的同目錄相對 href（**不是** `_href(site_key(...))`，理由見 §6），每列仍然印出完整的 `version_id` 文字（P24 既有斷言）；外層保留既有的 `data-site-version` 與 `data-slug`。**索引頁不得輸出任何指向站台索引的 `index.html`**（P26 的 `test_tutorial_index_omits_the_link_when_the_successor_was_rejected` 斷言 `"index.html" not in page`）。退役時 widget 區塊整段不輸出。

- [ ] **Step 4：補邊界案例並跑綠燈**

再加 successor 為 `None`、successor 等於自身、successor 為空白字串三個案例，預期都沒有連結卻仍顯示過期說明與原文；再加一個「退役頁全文不含使用者 ID 與回饋留言」的斷言。執行 `uv run pytest tests/unit/test_site_pages.py -q`，預期整個檔案全綠。

- [ ] **Step 5：提交**

```bash
git add src/training_kb/site.py tests/unit/test_site_pages.py
git commit -m "feat(site): 退役頁與索引只列已發布版本"
```

### Task 3：widget.js 產生可直接匯入的檔案

> **（現況核對 2026-09-14）`import_feedback`／`import_view`／`ImportResult`（P42）與 `approved_categories`（P43）目前都不存在**，而且波次是 **P57 在 W1、P42 在 W2、P43 在 W3**。所以：
>
> - **`tests/unit/test_site_assets.py` 的守門測試（Step 1 的第一個測試）本波要做完**——它只讀檔案內容，不相依 P42／P43。
> - **`tests/integration/test_site_widget_roundtrip.py` 的 `import_feedback` roundtrip 本波做不完。** 本計畫選擇：本波把 roundtrip 檔建起來，內容改成**只斷言下載封套的形狀**（`{kind, source, generated_at, note, items}`、`kind in ("feedback", "view")`、`items[0]` 具備 P42 的必填欄位 `id`／`tutorial_version`／`rating`／`user`、`type(rating) is int`、ID 形狀 `f_site-<slug>-<user>-<epoch>`，00A §6.7「widget 下載封套」列），不 import `training_kb.ingress.import_feedback`；真正的 roundtrip 由 **P42 在 W2 補上**（它是 `import_feedback` 的 owner，00A 把 P57 列為它的消費 Phase）。差異寫進 Phase 報告 §9 與 §11 完成清單（維持未勾）。
> - `approved_categories(repository)`（P43）同理：`SiteRenderer(categories=...)` 的值本波直接用 `("找不到按鈕", "缺少資訊")` 這個 tuple 字面值傳入測試，**並在 `site.py` 裡一個字都不寫類別清單**（renderer 不自己維護類別表，00A §6.7）。

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
    # 現況核對 2026-09-14：import_feedback 是 P42（W2）的產出，W1 還不存在。
    # 本波先只留封套形狀斷言（見本 Task 開頭的說明），這一行等 P42 補。
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

（現況核對 2026-09-14：這三個案例全部相依 P42 的 `validate_feedback`／`validate_view`／`import_*`，**在 W1 做不到**，留給 P42 在 W2 補進同一支檔。本波 `tests/integration/test_site_widget_roundtrip.py` 只放「整站掃描」（Task 4 Step 4 那一項，不相依 P42）與封套形狀斷言。`rating` 是 `"4"` 會被拒絕這件事，本波可以用**已存在的** `training_kb.models.Feedback`（`rating` 的 `mode="before"` strict int validator）先斷言一次，不必等 P42。）

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

在 `infra/training_kb_data_stack.py` 既有的 `s3.Bucket(...)` 加上 `website_index_document="index.html"`、`website_error_document="index.html"`，把 `block_public_access` 由 `s3.BlockPublicAccess.BLOCK_ALL` 改成 `s3.BlockPublicAccess(block_public_acls=True, ignore_public_acls=True, block_public_policy=False, restrict_public_buckets=False)`，並把 `enforce_ssl=True` 改成 `enforce_ssl=False`。再用 `bucket.add_to_resource_policy(iam.PolicyStatement(effect=iam.Effect.ALLOW, principals=[iam.AnyPrincipal()], actions=["s3:GetObject"], resources=[bucket.arn_for_objects("site/*")]))`，最後以 `CfnOutput` 輸出 `bucket.bucket_website_url` 並在說明寫「只有 HTTP」。**`enforce_ssl=False` 是本 Phase 的明確決定，理由要寫進程式註解：** 設計 §9.3 只有一個 bucket，`enforce_ssl=True` 會加一段「非 HTTPS 一律 Deny」的 bucket policy，而 S3 website endpoint 只提供 HTTP（設計 §13、§17.1），兩者同時存在時公開頁永遠讀不到。關掉它不會讓私有前綴變成公開：`tutorials/`、`operations/`、`stepfunctions/`、`demo/previews/` 沒有任何 Allow 語句，只有 `site/*` 有；程式與 Lambda 透過 SDK 存取本來就走 HTTPS。**不得因此宣稱本站提供 HTTPS。**

**（現況核對 2026-09-14）另外要補的一件事：資料角色的 `site/` 寫入權限（REP §8 第 6 項）。** 現況 `infra/training_kb_data_stack.py` 的資料角色只對 `PRIVATE_PREFIXES`（`tutorials/`、`operations/`、`stepfunctions/`、`demo/previews/`）有 `s3:GetObject`／`s3:PutObject`，**沒有 `site/`**，所以 P24／P25 的 `promote_site_objects` 在真實 AWS 上會 403。分工：

- **P41**（同波 W1）負責 `infra/training_kb_stack.py` 裡 **Lambda 執行角色**的權限；
- **本 Phase** 負責 `infra/training_kb_data_stack.py` 裡的 **bucket policy 公開讀** ＋ **資料角色的 `site/` 寫入**（因為那支檔的修改者只有 P57，00A §3.2）。

實作方式：**不要**把 `site/` 塞進 `PRIVATE_PREFIXES`（名字就叫 private，塞進去會讓 `test_s3_statement_covers_every_private_prefix_and_never_site` 的語意壞掉）。新增一個模組層常數 `PUBLISH_PREFIX = "site/"` 與**獨立的一條** `PolicyStatement`（`actions=["s3:GetObject", "s3:PutObject"]`、`resources=[bucket.arn_for_objects("site/*")]`），並把 `ListBucket` 的 `s3:prefix` 條件擴充成 `PRIVATE_PREFIXES + (PUBLISH_PREFIX,)`（`Repository.get_object` 要靠 `ListBucket` 才會把「key 不存在」回成 404 而不是 403，而 `_put_public_object` 會先比對既有 bytes）。

**同時更新 [Phase 09](./09-Phase09-AWS資料資源與最小IAM.md) 的 `tests/unit/test_data_stack.py`。（現況核對 2026-09-14：原文只提 Block Public Access 一條，實際有四條會被打到。）** 逐條：

| 既有測試 | 現況斷言 | 本 Phase 要改成 |
|---|---|---|
| `test_bucket_blocks_all_public_access` | 四道 BPA 全 `True` | `BlockPublicAcls`／`IgnorePublicAcls` 維持 `True`，`BlockPublicPolicy`／`RestrictPublicBuckets` 改 `False`；並加上 `WebsiteConfiguration` 的斷言。測試名稱也要改（`blocks_all` 已經不成立）。 |
| `test_s3_statement_covers_every_private_prefix_and_never_site` | `len(statements) == 1`、`len(Resource) == len(PRIVATE_PREFIXES) == 4`、**`"site/" not in rendered`** | 拆成兩條：私有那條維持四個前綴且不含 `site/`；新增一條斷言**只有一條** `site/*` 的 Allow 且動作只有 `GetObject`／`PutObject`。 |
| `test_list_bucket_is_limited_to_the_private_prefixes` | `prefixes == [f"{p}*" for p in PRIVATE_PREFIXES]`、**`"site/" not in json.dumps(prefixes)`** | 改成 `PRIVATE_PREFIXES + (PUBLISH_PREFIX,)`；仍然斷言**沒有**裸 `*`（不得整桶 List）。 |
| `test_outputs_expose_the_three_names` | `set(find_outputs("*")) == {TableName, BucketName, DataRoleArn}` | **加第四個 output**（website URL），集合要一起改；否則這條必紅。 |
| `test_data_role_has_no_wildcard_action_or_resource` | 只掃 `AWS::IAM::Policy`，註解說「`enforce_ssl` 產生的 bucket policy 是 Deny `s3:*`」 | 斷言不用改（公開讀那條是 `AWS::S3::BucketPolicy` 不是 `AWS::IAM::Policy`），但**註解已過時**（`enforce_ssl=False` 之後沒有那段 Deny），順手改成新的理由。 |

改別人的測試檔一律**只用 Edit**、只動上表列出的斷言，不重排不重格式化（COMMON.md R3）。

- [ ] **Step 4：跑測試並補整站掃描**

補一個整合測試：用 `Repository.put_object` 把 `demo/site_assets/*` 寫到 `ASSET_KEYS`、把整站渲染結果寫到本機假 S3，然後斷言 `site/` 底下沒有任何物件含 `data-published="false"`、沒有 `reason` 字串，且每個站內 `href` 都對得到已產生的 key。`cdk synth` 通過只代表 template 合法，不代表已部署。執行 `uv run pytest tests/unit/test_infra_site_hosting.py tests/unit/test_data_stack.py tests/integration/test_site_widget_roundtrip.py -q`，預期整個檔案全綠。

- [ ] **Step 5：提交**

```bash
git add infra/training_kb_data_stack.py tests/unit/test_infra_site_hosting.py tests/unit/test_data_stack.py tests/integration/test_site_widget_roundtrip.py
git commit -m "feat(infra): 只公開 site 前綴的靜態教學站"
```

### Task 5：真實 AWS 部署與 website endpoint 實測（現況核對 2026-09-14 新增，COMMON.md R1）

上一批把所有真實 AWS 延後到 P41；這一批 **P41／P48／P52／P57／P59／P60 要真的部署與執行並保存證據**。本 Phase 承接 [Phase 24](./24-Phase24-單篇教學發布提交.md)／[Phase 25](./25-Phase25-多篇教學整批發布.md) 文件裡「真實 AWS 重跑切點與 website endpoint 人工驗收」的 website endpoint 那幾條。

- [ ] **Step 1：部署 data stack**（`TrainingKbData` 已存在於 `us-east-1`，本次是更新）

```bash
AWS_REGION=us-east-1 AWS_DEFAULT_REGION=us-east-1 \
  command npx aws-cdk@2 diff TrainingKbData
AWS_REGION=us-east-1 AWS_DEFAULT_REGION=us-east-1 \
  command npx aws-cdk@2 deploy TrainingKbData --require-approval any-change \
  --outputs-file "$SCRATCH/trainingkbdata-outputs.json"
```

`node` 在互動 shell 被擋（`Security: node blocked`），一律 `command npx aws-cdk@2 …`；`--outputs-file` 指到 scratchpad（專案外），**`cdk.out/` 與 outputs 檔都不提交**（COMMON.md R8）。`diff` 的輸出要貼進報告——它會明確列出 BPA 兩項由 `true` 變 `false` 與新增的 bucket policy，是「改動範圍就是預期範圍」的證據。

- [ ] **Step 2：寫入一份公開頁並用 website endpoint 實際讀**

bucket 是 `training-kb-content-example`，website endpoint 形如 `http://<bucket>.s3-website-us-east-1.amazonaws.com`。**O5 BLOCKED**，所以不要靠 pipeline 產生教學；用 `Publisher` 發布一篇測試資料的版本，或直接 `aws s3 cp` 一份渲染好的頁面與 `site/assets/*` 上去（報告要寫清楚用哪一種）。然後：

```bash
aws s3 cp <本機渲染的 index.html> s3://<bucket>/site/index.html \
  --content-type "text/html; charset=utf-8" --region us-east-1
curl -si "http://<bucket>.s3-website-us-east-1.amazonaws.com/site/index.html" | head -20
curl -si "http://<bucket>.s3-website-us-east-1.amazonaws.com/tutorials/prepare-meeting/v1.md"
aws s3api get-bucket-policy --bucket <bucket> --region us-east-1 --output text
```

存證（貼進報告 §4，**不貼 bucket 內容本身**）：第一條 `curl` 的 **HTTP 200** 與回應標頭；第二條**必須是 403／404**（私有前綴沒有公開 Allow）；`get-bucket-policy` 的 JSON 逐字，確認 `Resource` 結尾是 `/site/*` 而不是 `/*`。

- [ ] **Step 3：把觀察結果原樣記錄，不做 gate 結論**

O3 仍是 FAIL：頁面打得開**只證明 website hosting 與 bucket policy 生效**，不證明發布切點的原子性。報告 §7 只能寫「website endpoint 可讀、公開範圍僅 `site/`」，**不得**寫「O3 PASS」或「發布故障驗收通過」。同時在報告寫明本站**只有 HTTP**（設計 §17.1），要 HTTPS 須另案評估。

- [ ] **Step 4：提交**（只提交程式與文件，證據寫進報告；不提交 `cdk.out/`、outputs 檔、任何 bucket 內容）

## 8. 驗收矩陣

| 路徑 | 輸入 | 預期資料結果 | 本批（2026-09-14）實際可驗到哪 |
|---|---|---|---|
| Happy | 已發布 v3、`supersedes=v2` | 頁面含 `href="v3.diff.txt"`、`href="v2.html"`、版本紀錄連結 `href="index.html"` 與 `data-published="true"`。（現況核對 2026-09-14：原寫絕對 `/site/tutorials/...`，改相對，理由見 §6。） | 可驗。 |
| Happy | v1、`supersedes=None` | 顯示「第一版，沒有前一版可比較」，沒有 `v0` 連結。 | 可驗。 |
| Failure | v3 但 `supersedes=None` | `PermanentError`；不輸出頁面。（**不是** `PublishError`；00A §6.7 P57 列明文。） | 可驗。 |
| Failure | 步驟文字含 `<script>` | 只輸出 `&lt;script&gt;`，沒有可執行標籤。 | 可驗。 |
| Boundary | retired 且 successor 為自身或空；版本清單含未發布版本；widget 未填 ID／未選評分 | 顯示 `RETIRED_NOTICE` 與原文、不顯示後繼連結、widget 完全消失；索引只列已發布版本；widget 不產生檔案也不顯示已送出。 | 可驗。「successor 等於自身」見 §6 的本計畫選擇（現況由 P26 的 `resolve_successor` 擋，renderer 不重判）。 |
| Privacy | 整站渲染後掃描 `site/` | 沒有 `data-published="false"`、沒有 `reason`／`release:`、沒有回饋留言原文與穩定使用者 ID。 | 可驗（moto／本機假 S3；`UNPUBLISHED_MARKER` 的 runtime 守門已存在）。 |
| （新增）Real AWS | Task 5：部署後 `curl` website endpoint | `site/index.html` **HTTP 200**；`tutorials/<slug>/v<n>.md` **403／404**；`get-bucket-policy` 的 `Resource` 結尾是 `/site/*`。 | **本批要做**（COMMON.md R1）。 |
| （新增）Gate | 頁面打得開 | **不得**推論成 O3 PASS 或「發布故障驗收通過」；O3 現況 FAIL。 | 報告措辭檢查。 |
| （新增）Blocked | roundtrip 的 `import_feedback` 斷言 | P42（W2）落地後才成立 | 本批只驗封套形狀與 `Feedback` 模型的 strict `rating`；`§11` 對應列維持未勾。 |

人工驗收：用 website endpoint 在瀏覽器開一次版本頁、版本紀錄頁與退役頁，實際按下下載按鈕，打開下載的 JSON 逐欄位對照 Phase 42 的必填欄位（`id`、`tutorial_version`、`rating`、`user`），確認 `rating` 在檔案裡是 `4` 而不是 `"4"`。不能只看測試顯示 PASS。（現況核對 2026-09-14：這一項在 Task 5 做，用的是本機瀏覽器 ＋ 真實 website endpoint；下載的 JSON 只用肉眼與 `python -c "import json…"` 對欄位型別，`import_feedback` 的實際匯入等 P42。）

## 9. 常見錯誤與停止條件

| 症狀 | 原因 | 修正／停止 |
|---|---|---|
| widget 顯示「已送出」或「感謝回饋」 | 把產生檔案當成提交成功 | 改回固定文案「檔案已產生，尚未送出」；未改正前不得展示。 |
| 未發布版本能從 website URL 讀到 | 渲染後直接寫 `site/` | 停止公開路徑；只有 `commit` 成功才寫，並補 `data-published` 掃描測試。 |
| 頁面印出 `release:r_42` 或 `gap:c12` | 把 `reason` 當版本說明顯示 | 停止：`reason` 是私有欄位（00A §3.3）；公開頁只顯示版號與差異連結。 |
| 版本選擇列出 `v1..vN` | 用版號推算清單 | 改用 `supersedes`、`current_version` 與版本紀錄頁（設計 §8.1 允許永久失敗留下版號缺口，`v1..vN` 會產生死連結）。 |
| `site.py` 冒出 `from training_kb.publishing import …` | 想用 key helper 組 href | 停止：`publishing.py` 已經 import `SiteRenderer`，這是循環 import。href 是同目錄相對檔名（D-78），**S3 key** 才用 `site_key`／`tutorial_index_key`／`site_index_key`／`site_diff_key`（D-54），而且那四個都在 `publishing.py`，由 `Publisher` 呼叫。（現況核對 2026-09-14 改寫。） |
| 為了讓文件裡的絕對 href 斷言過，去改 `tests/unit/test_retired_page.py` 或 `test_retire_tutorial.py` | 把別人的測試當自己的 | 停止：那是 P26 的測試檔（COMMON.md R3.6 不得修改），而且 D-78 鎖的就是相對 href。改本 Phase 的文件與測試。 |
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
- [ ] 公開 key 全部由 Phase 24 的 `site_key`／`tutorial_index_key`／`site_index_key` 與本 Phase 的 `site_diff_key`（在 `publishing.py`）組出，佈局是 `site/tutorials/<slug>/...`；**頁面裡的 href 是同目錄相對路徑，`site.py` 沒有 import `publishing`**（現況核對 2026-09-14 補）。
- [ ] 版本頁有版本選擇、差異連結與版本紀錄連結；v1 顯示固定的無前版文案；頁面不含 `reason`。
- [ ] 退役頁使用 Phase 26 的 `RETIRED_NOTICE`、保留原文、只在合法 successor 時顯示連結且不自動跳轉。
- [ ] widget 只產生檔案、狀態固定為「檔案已產生，尚未送出」，下載檔通過 Phase 42 驗證；不引 CDN、不含金鑰、不用 `innerHTML` 放使用者文字。
- [ ] bucket policy 只公開 `site/*`，`enforce_ssl=False` 的理由已寫進程式註解，Phase 09 的測試同步更新（四條，見 §7 Task 4 Step 3 的表）。
- [ ] **資料角色補上 `site/` 的 `PutObject`／`GetObject` 與 `ListBucket` 前綴**（REP §8 第 6 項；現況核對 2026-09-14 新增）。
- [ ] **P24／P26 的既有測試全綠**：`test_site_renderer.py`、`test_retired_page.py`、`test_retire_tutorial.py`、`test_publisher_single.py`、`test_publisher_batch.py` 一條都沒改、一條都沒紅（現況核對 2026-09-14 新增）。
- [ ] **真實 AWS（COMMON.md R1）**：`cdk deploy TrainingKbData` 完成；website endpoint `curl` 到 `site/index.html` 是 200、私有前綴是 403／404；`get-bucket-policy` 的 `Resource` 是 `/site/*`；證據貼進報告（現況核對 2026-09-14 新增）。
- [ ] 文件與畫面都把 website endpoint 寫成 HTTP，沒有宣稱 HTTPS；也沒有把單元測試 PASS 說成 O3 發布故障驗收已通過（**O3 現況是 FAIL**）。

**（現況核對 2026-09-14）本批注定勾不起來的一列：** 「下載檔通過 Phase 42 驗證」——`import_feedback`／`import_view` 是 P42（W2）的產出，P57 在 W1。本批只驗封套形狀與 `Feedback` 模型的 strict `rating`；真正的 roundtrip 由 P42 在 `tests/integration/test_site_widget_roundtrip.py` 補上（00A 已把 P57 列為 P42 的消費 Phase）。
