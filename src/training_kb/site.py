"""公開頁最小 renderer（Phase 24）：把**已保存**的內容轉成 HTML，不做任何寫入。

三個 render 方法的簽名到 Phase 57 都不改，Phase 57 只換實作（00A §6.7），所以這裡只固定
**內容契約**，不固定版面：

```text
render_version_page   版本頁     五段內容 + 版號 + 退役提示 + data-published
render_tutorial_index 教學版本紀錄 只列 published_at 非空的版本，標出 current_version
render_site_index     站台索引    只列 current_version 非空的 Tutorial
```

**這支檔案不知道 key、不知道 bucket、不知道交易。** 公開 key 由 `training_kb.publishing`
的三個 helper 決定（D-54），寫入順序由 `Publisher.commit` 決定；renderer 只吃領域物件、
吐字串，所以它可以在私有 staging 階段被呼叫，也可以在交易成功後被重新呼叫一次。
反向 import（`site` → `publishing`）一律禁止，否則兩支檔會互相 import。

**渲染時機早於公開時機**，所以 renderer 不能拿 `published_at` 當守門條件（`prepare` 那次
它必然是 `None`）。改用可機器檢查的標記：`published_at is None` 的頁面帶
`data-published="false"`，只能存在於 `operations/` 私有 staging；`Publisher.commit` 在交易
成功後用已切換的 `published_at` 重新渲染，所以進 `site/` 的一律是 `"true"`（00A §3.8、§6.7）。

**所有使用者可見文字一律先 `html.escape` 再拼字串**（同時轉 `&`、`<`、`>`、`"`、`'`）。
它與 Phase 22 的 `escape_markdown` 不是同一層，不得互換：那個是給 Markdown 全文用的。
"""

from html import escape

from training_kb.content import RETIRED_NOTICE, parse_version_id
from training_kb.errors import PublishError
from training_kb.models import (
    Tutorial,
    TutorialContent,
    TutorialStatus,
    TutorialStep,
    TutorialVersion,
)

RETIRED_PLACEHOLDER = RETIRED_NOTICE
"""Phase 24 用過的舊名，現在只是 Phase 26 `RETIRED_NOTICE` 的別名（00A §6.6 的 owner 是
`content`）。**字面值只存在 `content.py` 一處**，兩支檔各抄一份的話改字就會漏掉一邊。
退役提示刻意不顯示退役原因：`reason` 是 `release:<id>` 這種上游識別碼，設計 §13 列為私有。"""

SUCCESSOR_PREFIX = "改看："
"""後繼連結的固定前綴。連結文字用**後繼的 slug** 而不是它的 topic：renderer 的簽名到
Phase 57 都不變（00A §6.7），手上只有被退役的那一篇 `Tutorial`，要拿到後繼的 topic 就得
多讀一次 DynamoDB——renderer 不碰儲存層，所以這裡誠實地印 slug，連結本身仍然可點。"""

_SECTIONS = ("Problem", "Prerequisites", "Steps", "Expected Outcome")
"""版本頁固定的四個 `<h2>`；標題自己是 `<h1>`，所以五段裡只有四段有 `<h2>`。"""


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


def _version_number(version_id: str) -> str:
    """`v<n>`；版號一律用 `parse_version_id(version_id)[1]`，不自訂 `version_number`（D-19）。"""
    return f"v{parse_version_id(version_id)[1]}"


class SiteRenderer:
    """最小公開頁 renderer。

    四個 keyword 參數在本 Phase 只是存起來備用（Phase 57 才會真的用到橫幅與資產路徑），
    但**現在就要有預設值**：`SiteRenderer()` 無參數建構是 Phase 24／25／41／48／52 的既定
    用法，Phase 57 加畫面選項時也不得拿掉預設值（00A §6.7）。
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
        """
        saved = [(step.number, step.text) for step in steps]
        public = [(draft.number, draft.text) for draft in content.steps]
        if saved != public:
            raise PublishError(f"{version.version_id} 的已保存步驟與公開內容不同步")
        published = "true" if version.published_at is not None else "false"
        page = (
            f'<article data-published="{published}" data-slug="{escape(tutorial.slug)}"'
            f' data-version-id="{escape(version.version_id)}">'
            f"<h1>{escape(content.title)}</h1>"
            f'<p class="version">{escape(version.version_id)}</p>'
            f"<h2>{_SECTIONS[0]}</h2><p>{escape(content.problem)}</p>"
            f"<h2>{_SECTIONS[1]}</h2><ul>{_items(content.prerequisites)}</ul>"
            f"<h2>{_SECTIONS[2]}</h2>"
            f"<ol>{_items([step.text for step in steps])}</ol>"
            f"<h2>{_SECTIONS[3]}</h2><p>{escape(content.expected_outcome)}</p>"
        )
        if tutorial.status == TutorialStatus.RETIRED:
            page += f'<p class="retired">{escape(RETIRED_NOTICE)}</p>'
            page += _successor_line(tutorial.successor)
        return page + "</article>"

    def render_tutorial_index(self, tutorial: Tutorial,
                              versions: list[TutorialVersion]) -> str:
        """一篇教學的版本紀錄；**只列 `published_at` 非空的版本**。

        未發布版本出現在公開索引就等於曝光（設計 §9.3、§13），「沒有連結的 URL」不算私有。
        `data-site-version` 是「公開站此刻指向哪一版」的機器可讀標記，Phase 12 的 O3 觀察
        腳本就是讀它；`current_version` 是空的（還沒有任何已發布版本）時它是空字串。
        """
        current = tutorial.current_version
        marker = "" if current is None else _version_number(current)
        rows = "".join(
            f"<li>{escape(version.version_id)}"
            f"{'（目前版本）' if version.version_id == current else ''}</li>"
            for version in versions if version.published_at is not None
        )
        return (f'<article class="tutorial-index" data-site-version="{escape(marker)}"'
                f' data-slug="{escape(tutorial.slug)}">'
                f"<h1>{escape(tutorial.topic)}</h1><ul>{rows}</ul></article>")

    def render_site_index(self, tutorials: list[Tutorial]) -> str:
        """站台索引；**只列 `current_version` 非空的 Tutorial**（還沒發布過的不上架）。"""
        rows = "".join(
            f"<li>{escape(tutorial.topic)}</li>"
            for tutorial in tutorials if tutorial.current_version is not None
        )
        return f'<article class="site-index"><h1>教學站</h1><ul>{rows}</ul></article>'
