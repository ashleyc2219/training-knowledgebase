/* 教學站回饋 widget（Phase 57）。
 *
 * 這支腳本**只在讀者自己的瀏覽器裡產生檔案**，不會把任何東西送出去：
 *
 *   按下下載 -> 組 JSON 封套 -> Blob -> <a download> -> 狀態列寫「not sent yet」
 *
 * 要讓回饋真的進系統，維護者得把下載的檔案走 Phase 42 的固定匯入路徑。因此：
 *   - 沒有任何網路請求（不發請求、不開連線、不送背景信標），也沒有外部網址與憑證；
 *   - 狀態列永遠不寫任何讓人以為系統已經收到回饋的字（禁用字表見
 *     tests/unit/test_site_assets.py 的 claims_delivery，本檔連註解都不得出現）；
 *   - 使用者輸入一律用 textContent 放進畫面，不用任何會解析 HTML 的寫法（設計 §17.2）。
 *
 * 退役頁本來就不輸出 widget 區塊（site.py 的 _widget_block），這裡的 data-retired 檢查是
 * 第二道：腳本是整站共用的，任何一頁忘了拿掉區塊都不該開始收集。
 */
(function () {
  "use strict";

  var NOT_SENT = "File generated, not sent yet";
  var IDLE = "No file generated yet";
  var SAVED = NOT_SENT + ". Hand the file to a maintainer to import it.";
  var NEED_USER = "Enter your stable user ID first. This field is required.";
  var NEED_RATING = "Pick a rating from 1 to 5 first.";

  var root = document.getElementById("tkb-widget");
  if (!root || root.getAttribute("data-retired") === "true") { return; }

  var versionId = root.getAttribute("data-version-id") || "";
  var slug = root.getAttribute("data-slug") || "";
  var notice = root.getAttribute("data-notice") || "";
  var statusNode = document.getElementById("tkb-status");
  var rating = 0;
  var category = "";

  function setStatus(text) {
    if (statusNode) { statusNode.textContent = text; }
  }

  function token(value) {
    return String(value).replace(/[^A-Za-z0-9_-]/g, "");
  }

  function nowIso() {
    return new Date().toISOString().replace(/\.\d{3}Z$/, "Z");
  }

  function field(id) {
    var node = document.getElementById(id);
    return node ? node.value.trim() : "";
  }

  function each(selector, handler) {
    var nodes = root.querySelectorAll(selector);
    for (var index = 0; index < nodes.length; index += 1) { handler(nodes[index]); }
  }

  /* 下載封套（00A §6.7）：kind / source / generated_at / note / items 五個固定欄位。
   * items 的每一筆就是 Phase 42 匯入入口吃的事件形狀，維護者用 Phase 58 的 import
   * 子命令把它們逐筆送進 import_feedback / import_view。 */
  function save(name, kind, items) {
    var body = {
      kind: kind,
      source: "site_widget",
      generated_at: nowIso(),
      note: (notice ? notice + " | " : "") + "This file is not sent yet. A maintainer must import it.",
      items: items
    };
    var blob = new Blob([JSON.stringify(body, null, 2)],
                        { type: "application/json;charset=utf-8" });
    var objectUrl = URL.createObjectURL(blob);
    var link = document.createElement("a");
    link.href = objectUrl;
    link.download = name;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(objectUrl);
    setStatus(SAVED);
  }

  each("button.rating", function (button) {
    button.addEventListener("click", function () {
      rating = Number(button.getAttribute("data-rating"));
      each("button.rating", function (other) {
        other.setAttribute("aria-pressed", other === button ? "true" : "false");
      });
      setStatus("Rating " + rating + " selected. " + IDLE + ".");
    });
  });

  each("button.category", function (button) {
    button.addEventListener("click", function () {
      category = button.getAttribute("data-category") || "";
      each("button.category", function (other) {
        other.setAttribute("aria-pressed", other === button ? "true" : "false");
      });
      setStatus(category ? "Category selected. " + IDLE + "." : IDLE);
    });
  });

  var download = document.getElementById("tkb-download");
  if (download) {
    download.addEventListener("click", function () {
      var user = field("tkb-user");
      if (!user) { setStatus(NEED_USER); return; }
      if (!(rating >= 1 && rating <= 5)) { setStatus(NEED_RATING); return; }
      var item = {
        id: "f_site-" + token(slug) + "-" + token(user) + "-" + Math.floor(Date.now() / 1000),
        tutorial_version: versionId,
        rating: rating,
        user: user,
        ts: nowIso()
      };
      var comment = field("tkb-comment");
      if (category) { item.category = category; }
      if (comment) { item.comment = comment; }
      save("feedback-" + token(slug) + ".json", "feedback", [item]);
    });
  }

  var viewButton = document.getElementById("tkb-view");
  if (viewButton) {
    viewButton.addEventListener("click", function () {
      var user = field("tkb-user");
      if (!user) { setStatus(NEED_USER); return; }
      save("view-" + token(slug) + ".json", "view",
           [{ tutorial_version: versionId, user: user, ts: nowIso() }]);
    });
  }

  setStatus(IDLE);
})();
