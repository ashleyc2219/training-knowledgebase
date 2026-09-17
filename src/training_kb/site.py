"""公開頁 renderer（Phase 24 建立、Phase 57 加畫面、2026-09-17 重新設計版面）：把**已保存**的內容
轉成 HTML，不做任何寫入。

三個 render 方法的簽名固定不變（00A §6.7），這裡只固定**內容契約**，版面可以換：

```text
render_version_page   版本頁     五段內容 + 版號 + 退役提示 + data-published
render_tutorial_index 教學版本紀錄 只列 published_at 非空的版本，標出 current_version + 退役提示
render_site_index     站台索引    只列 current_version 非空的 Tutorial
```

**退役提示同時出現在版本頁與教學索引**（controller 裁決 2026-09-14）：已發布的版本頁是
不可覆寫的一次性產物，退役之後改不動它；索引是可重建投影，P52 退役後重寫索引就能讓讀者
看到提示。兩處共用 `_retired_block`，輸出逐字相同。

**這支檔案不知道 key、不知道 bucket、不知道交易。** 公開 key 由 `training_kb.publishing`
的三個 helper 決定（D-54），寫入順序由 `Publisher.commit` 決定；renderer 只吃領域物件、
吐字串，所以它可以在私有 staging 階段被呼叫，也可以在交易成功後被重新呼叫一次。
反向 import（`site` → `publishing`）一律禁止，否則兩支檔會互相 import。

**渲染時機早於公開時機**，所以 renderer 不能拿 `published_at` 當守門條件（`prepare` 那次
它必然是 `None`）。改用可機器檢查的標記：`published_at is None` 的頁面帶
`data-published="false"`，只能存在於 `operations/` 私有 staging；`Publisher.commit` 在交易
成功後用已切換的 `published_at` 重新渲染，所以進 `site/` 的一律是 `"true"`（00A §3.8、§6.7）。

**版面（2026-09-17）**：每一頁都是完整的 HTML 文件（`<!doctype html>` … `</html>`），
`<article>` 仍是內容根節點、機器可讀標記都掛在它身上。版本頁左欄是「版本欄」（版號、
上一版、版本紀錄、差異），右欄是內文；教學索引是版本時間軸；站台索引是教學清單。
所有連結一律是**瀏覽器相對路徑**（D-78），不含 `http://`、`https://` 或 CDN。

**所有使用者可見文字一律先 `html.escape` 再拼字串**（同時轉 `&`、`<`、`>`、`"`、`'`）。
它與 Phase 22 的 `escape_markdown` 不是同一層，不得互換：那個是給 Markdown 全文用的。
"""

from html import escape

from training_kb.content import PUBLIC_SITE_PREFIX, RETIRED_NOTICE, parse_version_id
from training_kb.errors import PermanentError, PublishError
from training_kb.models import (
    Tutorial,
    TutorialContent,
    TutorialStatus,
    TutorialStep,
    TutorialVersion,
)

SITE_PREFIX = PUBLIC_SITE_PREFIX
"""公開前綴；**是 Phase 22 `PUBLIC_SITE_PREFIX` 的別名**，值必須相同（00A §6.7），
所以這裡直接指過去而不是再抄一次 `"site/"`。它只用來組**資產路徑**與給呼叫端看，
四個公開 key 一律由 `training_kb.publishing` 的 helper 產生（D-54、00A §3.4）。"""

ASSET_KEYS = (f"{SITE_PREFIX}assets/style.css", f"{SITE_PREFIX}assets/widget.js")
"""兩個站台資產的公開 key（含 `site/` 前綴，與頁面 key 不同層）。頁面引用它們時用的是
瀏覽器路徑 `<asset_prefix>/style.css`，預設 `/site/assets/style.css`——同一份檔案的兩種
寫法：key 給 `put_object`，路徑給瀏覽器。"""

SITE_TITLE = "教學站"
"""站台名稱：站台索引的 `<h1>`、其他頁面頂欄的返回連結，以及每一頁 `<title>` 的尾巴。"""

SITE_LEDE = "依使用者回饋與產品改版自動維護的操作教學；每一版都保留，可以逐版對照。"
"""站台索引標題下的一句說明。"""

NO_PREVIOUS_TEXT = "第一版，沒有前一版可比較"
"""v1 的差異區塊固定文案（設計 §8.2）。v1 沒有 `.diff` 可比，顯示空連結比不顯示更糟。"""

NOT_SENT_TEXT = "檔案已產生，尚未送出"
"""widget 的唯一狀態文案。**任何「已送出」「感謝回饋」的措辭都禁止**：widget 只在瀏覽器
本機產生檔案，要進系統得由維護者走 Phase 42 的固定匯入路徑（設計 §13）。"""

RETIRED_PLACEHOLDER = RETIRED_NOTICE
"""Phase 24 用過的舊名，現在只是 Phase 26 `RETIRED_NOTICE` 的別名（00A §6.6 的 owner 是
`content`）。**字面值只存在 `content.py` 一處**，兩支檔各抄一份的話改字就會漏掉一邊。
退役提示刻意不顯示退役原因：`reason` 是 `release:<id>` 這種上游識別碼，設計 §13 列為私有。"""

SUCCESSOR_PREFIX = "改看："
"""後繼連結的固定前綴。連結文字用**後繼的 slug** 而不是它的 topic：renderer 的簽名到
Phase 57 都不變（00A §6.7），手上只有被退役的那一篇 `Tutorial`，要拿到後繼的 topic 就得
多讀一次 DynamoDB——renderer 不碰儲存層，所以這裡誠實地印 slug，連結本身仍然可點。"""

CURRENT_LABEL = "目前版本"
"""「目前版本」四個字只在這裡宣告；版本欄的括號標記與索引的印章都用它。"""

_SECTIONS = ("Problem", "Prerequisites", "Steps", "Expected Outcome")
"""版本頁固定的四個 `<h2>`；標題自己是 `<h1>`，所以五段裡只有四段有 `<h2>`。"""

_SECTION_ZH = {"Problem": "問題", "Prerequisites": "前置條件",
               "Steps": "步驟", "Expected Outcome": "預期結果"}
"""四個 `<h2>` 旁的中文標籤；`<h2>` 本身維持英文（那是內容契約），中文只是給讀者看。"""

_TUTORIALS_DIR = "tutorials"
"""站台索引往教學索引的那一層目錄名。字面值與 `publishing.SITE_TUTORIALS_DIR` 相同，但那是
**S3 key** 的一段、這是**瀏覽器相對路徑**的一段；`site` 不得 import `publishing`（會循環），
所以兩邊各自宣告、由 `tests/integration/test_site_widget_roundtrip.py` 的整站掃描守住一致。"""

_HOME_FROM_TUTORIAL = "../../index.html"
"""版本頁與教學索引都公開在 `site/tutorials/<slug>/`，回站台索引要往上兩層（D-78 的相對路徑）。"""

_WIDGET_HEADING = "這篇有幫助嗎？"
_UNSELECTED_CATEGORY = "未選擇"
_RATINGS = (1, 2, 3, 4, 5)
"""評分只有 1–5 的整數（收集教學回饋.feature Rule 3）；頁面不提供其他值，匯入端再驗一次。"""


def escape_text(value: str) -> str:
    """HTML 輸出的唯一轉義（同時轉 `&`、`<`、`>`、`"`、`'`）。

    與 Phase 22 的 `escape_markdown` **不是同一層、不得互換**：那個是給 Markdown 全文用的。
    屬性值也走這一個函式（`quote=True` 是 `html.escape` 的預設），所以
    `data-category="缺少資訊"` 這種屬性不會被使用者文字撐開。
    """
    return escape(value, quote=True)


def _items(values: list[str]) -> str:
    return "".join(f"<li>{escape(value)}</li>" for value in values)


def _successor_line(successor: str | None) -> str:
    """退役教學的後繼連結；`successor` 為空時回空字串（F19：無後繼仍完成退役，但不導向）。

    連結是**明確可點的提示**，不做自動跳轉：連續跳轉會把循環藏起來，讀者也看不出自己
    被推到了哪一篇。`successor` 進到這裡時已經通過 Phase 26 `resolve_successor` 的四項
    檢查（存在、非自身、已發布的 active、不成環），所以這裡只負責輸出，不再判一次。

    href 是**瀏覽器層的相對路徑**，不是 S3 key：版本頁公開在
    `site/tutorials/<slug>/v<n>.html`，後繼的版本紀錄頁在
    `site/tutorials/<successor>/index.html`，兩者只差一層目錄。組 key 的三個 helper 在
    `training_kb.publishing`（D-54），而 `site` 一律不 import `publishing`（否則兩支檔
    互相 import），所以這裡不呼叫它們，也沒有用 `PUBLIC_SITE_PREFIX` 拼出任何 key。
    """
    if successor is None:
        return ""
    slug = escape(successor)
    return (f'<p class="successor"><a href="../{slug}/index.html">'
            f"{escape(SUCCESSOR_PREFIX)}{slug}</a></p>")


def _retired_block(tutorial: Tutorial) -> str:
    """退役提示＋後繼連結；還在維護（`status != retired`）時回空字串。

    版本頁與教學索引共用這一份輸出，所以兩個頁面的提示與連結逐字相同，改字也只改一處。
    `tutorial.successor` 進來時已經是 Phase 26 `resolve_successor` 四項檢查的**結果**
    （不合法時 `retire_tutorial` 讓它保持 `None`），renderer 不再判一次：renderer 不碰
    儲存層，重判就得多讀一次 DynamoDB，簽名也會被迫改（00A §6.7 明訂不改）。
    """
    if tutorial.status != TutorialStatus.RETIRED:
        return ""
    return (f'<p class="retired">{escape(RETIRED_NOTICE)}</p>'
            + _successor_line(tutorial.successor))


def _version_number(version_id: str) -> str:
    """`v<n>`；版號一律用 `parse_version_id(version_id)[1]`，不自訂 `version_number`（D-19）。"""
    return f"v{parse_version_id(version_id)[1]}"


# --- Phase 57：版本選擇、差異連結、橫幅與 widget ------------------------------


def _page_href(version_id: str, suffix: str) -> str:
    """同目錄的相對檔名：`v<n>.html`／`v<n>.diff.txt`（D-78）。

    **這不是 S3 key**：公開 key 由 `training_kb.publishing` 的四個 helper 產生（D-54），
    而 `site` 不得 import `publishing`（`publishing` 已經 import 本模組，反向會循環）。
    版本頁、公開 diff 與教學索引都公開在 `site/tutorials/<slug>/` 這同一層，所以瀏覽器層
    只需要檔名；後繼教學差一層目錄，由 `_successor_line` 輸出 `../<slug>/index.html`。
    """
    return f"{_version_number(version_id)}{suffix}"


def _diff_block(tutorial: Tutorial, version: TutorialVersion) -> str:
    """與前一版的差異連結；沒有前一版時顯示 `NO_PREVIOUS_TEXT`（設計 §8.2）。

    **本計畫選擇（2026-09-14）：守門條件不是「版號大於 1」，而是「這篇明明有一個更舊的
    已發布版，這一版卻沒有 `supersedes`」。** 00A §6.7 原本寫「版號大於 1 卻缺 `supersedes`
    丟 `PermanentError`」，但那條與既有程式衝突（R5 以既有程式為準）：`content._base_version`
    在 `current_version is None` 時回 `(None, 0)`，而 `_next_free_number` 會跳過被永久失敗的
    未發布版占用的號碼——所以「v1 建到一半永久失敗、v2 才是第一個成功的版本」會產生
    **合法的** `v2 + supersedes=None`（設計 §8.1 明文允許版號缺口）。把它當成資料不完整，
    等於讓一篇正常的教學永遠渲染不出來。

    改用 `tutorial.current_version` 判斷：它是更舊的版號時，代表這篇**真的**有前一版可以
    比較，缺 `supersedes` 就是資料不完整 → `PermanentError`（永久性，重試同一份輸入不會
    變好）。等於本頁自己就是 `current_version`、或 `current_version` 更新（在看歷史版）、
    或整篇還沒有任何已發布版本時，都不算不完整。
    """
    if version.supersedes is None:
        _, number = parse_version_id(version.version_id)
        base = tutorial.current_version
        if base is not None and base != version.version_id:
            _, base_number = parse_version_id(base)
            if base_number < number:
                raise PermanentError(
                    f"{version.version_id} 缺少 supersedes（這篇的目前版本是 {base}）")
        return f'<p class="diff-note">{escape_text(NO_PREVIOUS_TEXT)}</p>'
    _, previous = parse_version_id(version.supersedes)
    return (f'<p class="diff-note">'
            f'<a href="{_page_href(version.version_id, ".diff.txt")}">'
            f"查看與 v{previous} 的差異</a></p>")


def _version_switch(tutorial: Tutorial, version: TutorialVersion) -> str:
    """版本欄的連結清單：上一版、本頁（必要時標「目前版本」）、版本紀錄頁。

    **不列 `v1..vN`**：設計 §8.1 允許永久失敗留下版號缺口，用版號推算清單會產生死連結。
    完整清單只在版本紀錄頁（`index.html`），那一頁的內容來自 DynamoDB 的實際版本列。
    """
    parts = []
    if version.supersedes is not None:
        parts.append(f'<a href="{_page_href(version.supersedes, ".html")}">'
                     f"上一版 {_version_number(version.supersedes)}</a>")
    current = f"（{CURRENT_LABEL}）" if version.version_id == tutorial.current_version else ""
    parts.append(f'<span class="current">本頁 {_version_number(version.version_id)}'
                 f"{current}</span>")
    parts.append('<a href="index.html">查看版本紀錄</a>')
    items = "".join(f"<li>{part}</li>" for part in parts)
    return f'<nav class="version-switch" aria-label="版本"><ul>{items}</ul></nav>'


def _banner(notice: str, batch: str) -> str:
    """合成資料橫幅；兩個欄位都空（`SiteRenderer()` 的預設）時整段不輸出。

    O7 未到（P56 首驗），所以這裡只照抄呼叫端給的批次名稱，**不得**印成「已核定」。
    """
    if not notice and not batch:
        return ""
    labels = [escape_text(notice)] if notice else []
    if batch:
        labels.append(f"批次：{escape_text(batch)}")
    return f'<p class="banner">{"｜".join(labels)}</p>'


def _asset_links(asset_prefix: str, *, script: bool = True) -> str:
    """樣式與腳本；兩支都在同一個 bucket 的 `site/assets/`（`ASSET_KEYS`），不引 CDN。

    `script=False` 是給兩個索引頁用的：那裡沒有 widget，載 `widget.js` 只會多一次請求。
    """
    prefix = escape_text(asset_prefix.rstrip("/"))
    link = f'<link rel="stylesheet" href="{prefix}/style.css">'
    return link + (f'<script src="{prefix}/widget.js" defer></script>' if script else "")


def _document(title: str, head: str, body: str) -> str:
    """把 `<article>` 包成一份完整的 HTML 文件。

    `<meta>` 只有字元集與 viewport 兩個：不放 `http-equiv`（測試明令禁止，避免被拿來做
    自動跳轉），也不放任何外部資源。`<title>` 與內文一樣先轉義。
    """
    return (f'<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width, initial-scale=1">'
            f"<title>{escape_text(title)}</title>{head}</head>"
            f"<body>{body}</body></html>")


def _masthead(home_href: str, crumb: str) -> str:
    """頂欄：回站台索引的連結＋本頁在哪裡（slug／版號，等寬字）。"""
    return (f'<header class="masthead"><a class="home" href="{escape_text(home_href)}">'
            f"{escape_text(SITE_TITLE)}</a>"
            f'<span class="crumb">{escape_text(crumb)}</span></header>')


def _part(section: str, inner: str) -> str:
    """版本頁的一段：固定的英文 `<h2>`（內容契約）＋中文標籤，內文原樣放進去。"""
    return (f'<section class="part"><div class="part-head"><h2>{section}</h2>'
            f'<span class="part-zh">{escape_text(_SECTION_ZH[section])}</span></div>'
            f"{inner}</section>")


def _widget_block(tutorial: Tutorial, version: TutorialVersion,
                  categories: tuple[str, ...], notice: str) -> str:
    """回饋與瀏覽紀錄的下載區；退役教學整段不輸出（設計 §8.4、§13）。

    **這裡沒有任何送出行為**：按鈕由 `demo/site_assets/widget.js` 在瀏覽器本機產生檔案，
    狀態文字固定是 `NOT_SENT_TEXT`，要進系統得由維護者走 Phase 42 的固定匯入路徑。
    類別清單由呼叫端注入（Phase 43 的 `approved_categories`），本模組不維護任何類別字面值。
    """
    if tutorial.status == TutorialStatus.RETIRED:
        return ""
    ratings = "".join(
        f'<button type="button" class="rating" data-rating="{value}">{value}</button>'
        for value in _RATINGS
    )
    chips = "".join(
        f'<button type="button" class="category" data-category="{escape_text(name)}">'
        f"{escape_text(name)}</button>"
        for name in categories
    )
    chips += ('<button type="button" class="category" data-category="">'
              f"{_UNSELECTED_CATEGORY}</button>")
    return (
        f'<section id="tkb-widget" class="widget"'
        f' data-slug="{escape_text(tutorial.slug)}"'
        f' data-version-id="{escape_text(version.version_id)}"'
        f' data-notice="{escape_text(notice)}" data-retired="false">'
        f"<h2>{_WIDGET_HEADING}</h2>"
        f'<p class="ratings">{ratings}</p>'
        f'<p class="categories">{chips}</p>'
        f'<p><label for="tkb-comment">留言</label>'
        f'<textarea id="tkb-comment" rows="3"></textarea></p>'
        f'<p><label for="tkb-user">你的穩定使用者 ID（必填）</label>'
        f'<input id="tkb-user" type="text" autocomplete="off"></p>'
        f'<p class="actions">'
        f'<button type="button" id="tkb-download">下載回饋檔案，交由維護者匯入</button>'
        f'<button type="button" id="tkb-view">下載瀏覽紀錄</button></p>'
        f'<p class="not-sent">本頁不會送出任何資料：按下下載只會在你的電腦產生檔案，'
        f"狀態一律是「{escape_text(NOT_SENT_TEXT)}」，需要維護者匯入才會進系統。</p>"
        f'<p class="status">狀態：<span id="tkb-status">尚未產生檔案</span></p>'
        f"</section>"
    )


class SiteRenderer:
    """公開頁 renderer。

    四個 keyword 參數都有預設值：`SiteRenderer()` 無參數建構是 Phase 24／25／41／48／52 的
    既定用法，加畫面選項時也不得拿掉預設值（00A §6.7）。
    """

    def __init__(self, *, notice: str = "", batch: str = "",
                 categories: tuple[str, ...] = (),
                 asset_prefix: str = "/site/assets") -> None:
        self.notice = notice
        self.batch = batch
        self.categories = categories
        self.asset_prefix = asset_prefix

    def render_version_page(self, tutorial: Tutorial, version: TutorialVersion,
                            steps: list[TutorialStep], content: TutorialContent) -> str:
        """一個版本的公開頁。

        第一件事是核對**已保存步驟**（DynamoDB 的 `STEP` 邊）與**公開內容**（S3 全文解析出
        的 `content.steps`）逐字相同：兩邊分岔代表寫入沒寫完或有人改過其中一邊，這時輸出
        半對的頁面比停下來危險得多（設計 §8.2）。核對只比 `(number, text)`——`type` 與
        `feature_id` 不進公開頁，拿它們比對會把「不影響公開內容的差異」誤判成不同步。

        **機器可讀標記全掛在 `<article>` 上**：`data-published`（00A §3.8）、`data-retired`、
        `data-slug`、`data-version-id`。左欄是版本欄（版號、上一版、版本紀錄、差異連結），
        右欄是內文；`version.reason` 一個字都不進頁面（`release:<id>` 是上游識別碼，
        設計 §13 私有）。
        """
        saved = [(step.number, step.text) for step in steps]
        public = [(draft.number, draft.text) for draft in content.steps]
        if saved != public:
            raise PublishError(f"{version.version_id} 的已保存步驟與公開內容不同步")
        published = "true" if version.published_at is not None else "false"
        retired = "true" if tutorial.status == TutorialStatus.RETIRED else "false"
        is_current = version.version_id == tutorial.current_version
        crumb = f"{tutorial.slug} / {_version_number(version.version_id)}"
        stamp = (f'<p><span class="stamp">{escape_text(CURRENT_LABEL)}</span></p>'
                 if is_current else "")
        rail = (
            f'<aside class="rail" aria-label="版本資訊">'
            f'<p class="version">{escape(version.version_id)}</p>'
            f"{stamp}"
            f"{_version_switch(tutorial, version)}"
            f"{_diff_block(tutorial, version)}"
            f"</aside>"
        )
        body = (
            f'<div class="body">'
            f'<p class="eyebrow">操作教學</p>'
            f"<h1>{escape(content.title)}</h1>"
            + _part(_SECTIONS[0], f"<p>{escape(content.problem)}</p>")
            + _part(_SECTIONS[1], f"<ul>{_items(content.prerequisites)}</ul>")
            + _part(_SECTIONS[2], f'<ol class="steps">{_items([step.text for step in steps])}</ol>')
            + _part(_SECTIONS[3], f"<p>{escape(content.expected_outcome)}</p>")
            + _widget_block(tutorial, version, self.categories, self.notice)
            + "</div>"
        )
        article = (
            f'<article data-published="{published}" data-retired="{retired}"'
            f' data-slug="{escape(tutorial.slug)}"'
            f' data-version-id="{escape(version.version_id)}">'
            f"{_masthead(_HOME_FROM_TUTORIAL, crumb)}"
            f"{_banner(self.notice, self.batch)}"
            f'<div class="page">{rail}{body}</div>'
            f"{_retired_block(tutorial)}</article>"
        )
        return _document(f"{content.title}｜{version.version_id}｜{SITE_TITLE}",
                         _asset_links(self.asset_prefix), article)

    def render_tutorial_index(self, tutorial: Tutorial,
                              versions: list[TutorialVersion]) -> str:
        """一篇教學的版本紀錄；**只列 `published_at` 非空的版本**，退役時加上退役區塊。

        未發布版本出現在公開索引就等於曝光（設計 §9.3、§13），「沒有連結的 URL」不算私有。
        `data-site-version` 是「公開站此刻指向哪一版」的機器可讀標記，Phase 12 的 O3 觀察
        腳本就是讀它；`current_version` 是空的（還沒有任何已發布版本）時它是空字串。

        清單照呼叫端給的順序輸出（`Publisher` 給的是版號大的在前），目前版本那一列
        加上印章。退役區塊放在版本清單**之後**、`</article>` 之前，與版本頁一致。
        """
        current = tutorial.current_version
        marker = "" if current is None else _version_number(current)
        rows = []
        for version in versions:
            if version.published_at is None:
                continue
            is_current = version.version_id == current
            label = escape(version.version_id) + (f"（{CURRENT_LABEL}）" if is_current else "")
            stamp = (f'<span class="stamp">{escape_text(CURRENT_LABEL)}</span>'
                     if is_current else "")
            rows.append(f'<li{" class=\"is-current\"" if is_current else ""}>'
                        f'<a href="{_page_href(version.version_id, ".html")}">{label}</a>'
                        f"{stamp}</li>")
        article = (f'<article class="tutorial-index" data-site-version="{escape(marker)}"'
                   f' data-slug="{escape(tutorial.slug)}">'
                   f"{_masthead(_HOME_FROM_TUTORIAL, tutorial.slug)}"
                   f"{_banner(self.notice, self.batch)}"
                   '<p class="eyebrow">版本紀錄</p>'
                   f"<h1>{escape(tutorial.topic)}</h1>"
                   f'<ol class="versions">{"".join(rows)}</ol>'
                   f"{_retired_block(tutorial)}</article>")
        return _document(f"{tutorial.topic}｜版本紀錄｜{SITE_TITLE}",
                         _asset_links(self.asset_prefix, script=False), article)

    def render_site_index(self, tutorials: list[Tutorial]) -> str:
        """站台索引；**只列 `current_version` 非空的 Tutorial**（還沒發布過的不上架）。

        連結是 `tutorials/<slug>/index.html`：站台索引公開在 `site/index.html`，教學索引在
        `site/tutorials/<slug>/index.html`，所以從這一頁看過去就是往下兩層的相對路徑
        （同 D-78 的規則，不是 S3 key）。沒發布過的教學連 slug 都不輸出。每一列顯示
        主題、目前版號，退役的教學加上標籤（連結仍可點，讀者會在教學索引看到後繼）。
        """
        rows = []
        for tutorial in tutorials:
            if tutorial.current_version is None:
                continue
            retired = ('<span class="tag-retired">已退役</span>'
                       if tutorial.status == TutorialStatus.RETIRED else "")
            rows.append(
                f'<li><a href="{_TUTORIALS_DIR}/{escape_text(tutorial.slug)}/index.html">'
                f'<span class="topic">{escape(tutorial.topic)}</span>'
                f'<span class="chip">'
                f'{escape_text(_version_number(tutorial.current_version))}</span>'
                f"{retired}</a></li>")
        article = (f'<article class="site-index">'
                   f'<header class="masthead"><span class="home">{escape_text(SITE_TITLE)}</span>'
                   f'<span class="crumb">{len(rows)} 篇</span></header>'
                   f"{_banner(self.notice, self.batch)}"
                   f"<h1>{escape_text(SITE_TITLE)}</h1>"
                   f'<p class="lede">{escape_text(SITE_LEDE)}</p>'
                   f'<ul class="tutorials">{"".join(rows)}</ul></article>')
        return _document(SITE_TITLE, _asset_links(self.asset_prefix, script=False), article)
