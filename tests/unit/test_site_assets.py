"""Phase 57 Task 3：`demo/site_assets/` 兩支純資產的守門測試。

這兩支檔案是**瀏覽器端資產**，不是 Python 套件，所以測試只 `read_text()` 讀原始碼再斷言，
不 import 也不執行它們（`demo/` 不需要可 import，那是 Phase 56 的事）。

守的是三件會直接變成事故的事（設計 §13、§17.2）：

```text
1. widget 不得連網                 fetch/XHR/sendBeacon/http 一律不准出現
2. widget 不得宣稱已經送出         狀態文案只有 NOT_SENT_TEXT 這一種
3. widget 不得用 innerHTML 放文字  使用者輸入一律走 textContent
```
"""

import re
from pathlib import Path

from training_kb.site import ASSET_KEYS, NOT_SENT_TEXT, SITE_PREFIX

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ASSET_DIR = PROJECT_ROOT / "demo" / "site_assets"
WIDGET = ASSET_DIR / "widget.js"
STYLE = ASSET_DIR / "style.css"

NETWORK_CALLS = ("fetch(", "XMLHttpRequest", "sendBeacon", "WebSocket",
                 "http://", "https://", "amazonaws")
HTML_INJECTION = ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write")


def claims_delivery(text: str) -> bool:
    """頁面或腳本是否暗示「系統已收到回饋」：拿掉 `not sent` 這個片語後，sent／submitted／
    received／thank 任一出現就算（英文版的「已送出」「感謝回饋」禁令）。"""
    stripped = re.sub(r"(?i)not[ -]sent", "", text)
    return re.search(r"(?i)\b(sent|submitted|received|thank)", stripped) is not None


def widget_source() -> str:
    return WIDGET.read_text(encoding="utf-8")


def test_widget_is_self_contained_and_never_claims_sent() -> None:
    """Given `widget.js`／When 讀原始碼／Then 不連網、不注入 HTML、不宣稱已經送出。"""
    source = widget_source()
    for banned in NETWORK_CALLS + HTML_INJECTION:
        assert banned not in source
    assert NOT_SENT_TEXT in source
    assert not claims_delivery(source)
    assert "textContent" in source


def test_widget_stops_on_a_retired_page() -> None:
    """Given 退役頁的 `data-retired="true"`／When 讀原始碼／Then widget 早退。

    退役頁本來就不輸出 widget 區塊（`site.py::_widget_block`），這是**第二道**：
    腳本是整站共用的，任何一頁忘了拿掉 `<section id="tkb-widget">` 都不該開始收集。
    """
    source = widget_source()
    assert 'data-retired' in source
    assert '"true"' in source


def test_widget_builds_the_phase42_download_envelope() -> None:
    """Given `widget.js`／When 讀原始碼／Then 封套五個欄位與 Feedback ID 形狀都在。

    封套是 00A §6.7 的「widget 下載封套」列：`{kind, source, generated_at, note, items}`，
    Feedback ID 形狀是 `f_site-<slug>-<user>-<epoch>`。真正的匯入 roundtrip 由 Phase 42
    在 `tests/integration/test_site_widget_roundtrip.py` 補（本波 `import_feedback` 還不存在）。
    """
    source = widget_source()
    for field in ("kind:", "source:", "generated_at:", "note:", "items:"):
        assert field in source
    assert '"f_site-"' in source
    assert '"feedback"' in source and '"view"' in source
    for required in ("tutorial_version:", "rating:", "user:"):
        assert required in source


def test_widget_requires_a_stable_user_id_and_a_numeric_rating() -> None:
    """Given `widget.js`／When 讀原始碼／Then 缺 ID 或缺評分時走的是「不產生檔案」那條路。

    收集教學回饋.feature Rule 3／Rule 9 的 primary 在 Phase 42 的匯入端，widget 這一層只是
    先擋一次；`Number(...)` 讓 `rating` 在 JSON 裡是 `4` 而不是 `"4"`。
    """
    source = widget_source()
    assert "tkb-user" in source
    assert "Number(" in source
    assert "rating >= 1" in source and "rating <= 5" in source


def test_stylesheet_is_self_contained() -> None:
    """Given `style.css`／When 讀原始碼／Then 不 `@import`、不抓外部字型或圖片。"""
    style = STYLE.read_text(encoding="utf-8")
    for banned in ("@import", "http://", "https://", "amazonaws", "url("):
        assert banned not in style
    assert "#tkb-widget" in style


def test_asset_keys_point_at_the_two_files_on_disk() -> None:
    """Given `ASSET_KEYS`／When 對照磁碟／Then 兩個 key 的檔名與實際檔案一致。

    key 是 `site/assets/<name>`（含公開前綴），本機來源是 `demo/site_assets/<name>`：
    發布時是同一份 bytes 的兩個位置，名字對不上就會上線一個 404 的樣式表。
    """
    assert ASSET_KEYS == (f"{SITE_PREFIX}assets/style.css", f"{SITE_PREFIX}assets/widget.js")
    for key in ASSET_KEYS:
        assert (ASSET_DIR / Path(key).name).is_file()
