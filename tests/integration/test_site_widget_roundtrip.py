"""Phase 57 Task 3／Task 4 Step 4：widget 下載封套的形狀，以及整站公開物件的掃描（moto）。

本檔分成兩半：

```text
前半（不碰 AWS）  widget 下載封套 {kind, source, generated_at, note, items} 的形狀，
                  以及 items[0] 能不能過 models.Feedback 的嚴格驗證
後半（moto）      用真的 Publisher 發布一篇，再掃描 site/ 底下每一個物件：
                  沒有未發布標記、沒有私有欄位、每個站內 href 都指得到實際存在的 key
```

**已補（Phase 42，W2）：** 檔尾第三段是真正的 roundtrip——把 `items[0]` 餵進
`training_kb.ingress.import_feedback(...)`／`import_view(...)`，斷言 `status == "saved"`、
同一個 `id` 第二次回 `duplicate`、`rating="4"` 被拒並指出 `rating` 欄位。前半仍然保留用
`models.Feedback` 驗 strict int 的那一條：它守的是下載檔本身，與匯入端各守一層。

**本檔全綠不代表 O3 通過**：moto 只證明資料形狀，不是實 bucket 的行為，也不證明任何發布
切點的原子性（O3 由 Phase 12 判定 FAIL）。
"""

import json
import posixpath
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from training_kb.content import (
    DIFF_CONTENT_TYPE,
    MARKDOWN_CONTENT_TYPE,
    PUBLIC_SITE_PREFIX,
    VersionPlan,
    create_version,
    diff_key,
    markdown_key,
    parse_version_id,
    put_private_artifact,
    render_markdown,
)
from training_kb.ingress import import_feedback, import_view
from training_kb.keys import tutorial_pk
from training_kb.models import (
    Feature,
    Feedback,
    StepDraft,
    StepType,
    Tutorial,
    TutorialContent,
    TutorialStatus,
    TutorialStep,
    TutorialVersion,
)
from training_kb.operations import OperationCoordinator
from training_kb.publishing import (
    SITE_PAGE_CONTENT_TYPE,
    UNPUBLISHED_MARKER,
    Publisher,
    PublishRequest,
)
from training_kb.repository import Repository
from training_kb.site import ASSET_KEYS, SiteRenderer

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ASSET_DIR = PROJECT_ROOT / "demo" / "site_assets"

SLUG = "prepare-meeting"
FEATURE = "Prepare"
V1 = f"{SLUG}@v1"
V2 = f"{SLUG}@v2"
OPERATION = "op-site-57"
NOW = datetime(2026, 9, 14, 0, 30, tzinfo=UTC)
USER = "u_01"
"""Demo 種子的穩定使用者 ID 形狀（00A §6.8）；不是瀏覽器隨機產生的 ID。"""

NOTICE = "合成資料示範"
BATCH = "demo-seed-01"
CATEGORIES = ("找不到按鈕", "缺少資訊")

_TEXTS = ("開啟行事曆。", "選擇今天的會議。", "開啟摘要。", "確認摘要內容。")
_TYPES = ("read", "click_ui", "click_ui", "read")
_HREF = re.compile(r'(?:href|src)="([^"]+)"')
_ASSET_TYPES = {".css": "text/css; charset=utf-8",
                ".js": "text/javascript; charset=utf-8"}

PRIVATE_STRINGS = ("release:", "gap:c12", "r_42", "operations/", "u_gh-", "cluster")
"""公開頁一個字都不准出現的私有欄位（設計 §13、00A §3.8）。"""


# --- 前半：widget 下載封套（不碰 AWS）----------------------------------------


def feedback_envelope() -> dict[str, Any]:
    """`widget.js` 按下「下載回饋檔案」時產生的檔案內容（00A §6.7 的封套列）。

    這份字面值與 `demo/site_assets/widget.js` 是**同一個契約的兩面**，所以
    `test_the_envelope_matches_the_widget_source` 會回頭比對原始碼裡確實有這些欄位名，
    避免資產改了、測試還綠。
    """
    return {
        "kind": "feedback",
        "source": "site_widget",
        "generated_at": "2026-09-14T00:30:45Z",
        "note": f"{NOTICE}｜此檔尚未送出，需由維護者匯入",
        "items": [{
            "id": f"f_site-{SLUG}-{USER}-1789012345",
            "tutorial_version": V2,
            "rating": 4,
            "category": "缺少資訊",
            "comment": "第三步的截圖可以再清楚一點",
            "user": USER,
            "ts": "2026-09-13T12:34:56Z",
        }],
    }


def test_download_envelope_has_the_five_fixed_fields() -> None:
    """Given 下載的回饋檔／When 讀 JSON／Then 五個固定欄位與 `items` 的必填欄位都在。"""
    envelope = feedback_envelope()
    assert set(envelope) == {"kind", "source", "generated_at", "note", "items"}
    assert envelope["kind"] in ("feedback", "view")
    assert envelope["source"] == "site_widget"
    assert "尚未送出" in envelope["note"]
    item = envelope["items"][0]
    for required in ("id", "tutorial_version", "rating", "user"):
        assert required in item


def test_downloaded_rating_is_a_json_number_not_a_string() -> None:
    """Given 下載的回饋檔／When 檢查 `rating` 型別／Then 是 `int`，不是 `"4"`。

    收集教學回饋.feature Rule 3 的 primary 在 Phase 42 的匯入端，但**下載檔本身寫錯型別**
    的話，維護者要到匯入那一步才會發現，所以這一層也守一次（`models.Feedback` 的
    `rating` 是 `mode="before"` 的 strict int validator，已經存在，不必等 P42）。
    """
    item = feedback_envelope()["items"][0]
    assert type(item["rating"]) is int
    assert Feedback(**item).rating == 4
    with pytest.raises(ValidationError, match="rating"):
        Feedback(**{**item, "rating": "4"})


def test_feedback_id_follows_the_site_widget_shape() -> None:
    """Given 下載的回饋檔／When 檢查 `id`／Then 形狀是 `f_site-<slug>-<user>-<epoch>`。"""
    item = feedback_envelope()["items"][0]
    assert re.fullmatch(r"f_site-[A-Za-z0-9_-]+-[A-Za-z0-9_-]+-\d+", item["id"])
    assert item["id"].startswith(f"f_site-{SLUG}-{USER}-")


def test_view_envelope_carries_no_rating_or_comment() -> None:
    """Given 下載的瀏覽紀錄／When 讀 JSON／Then 只有版本、使用者與時間三個欄位。"""
    view = {"kind": "view", "source": "site_widget", "generated_at": "2026-09-14T00:30:45Z",
            "note": f"{NOTICE}｜此檔尚未送出，需由維護者匯入",
            "items": [{"tutorial_version": V2, "user": USER, "ts": "2026-09-13T12:34:56Z"}]}
    assert set(view["items"][0]) == {"tutorial_version", "user", "ts"}
    assert json.dumps(view, ensure_ascii=False)


def test_the_envelope_matches_the_widget_source() -> None:
    """Given 封套字面值／When 比對 `widget.js`／Then 每個欄位名都真的在資產裡。"""
    source = (ASSET_DIR / "widget.js").read_text(encoding="utf-8")
    for field in feedback_envelope():
        assert f"{field}:" in source
    assert '"site_widget"' in source
    assert '"f_site-"' in source


# --- 後半：整站掃描（moto）---------------------------------------------------


def four_step_content() -> TutorialContent:
    steps = [
        StepDraft(number=index + 1, type=StepType(_TYPES[index]), text=_TEXTS[index],
                  feature_id=FEATURE)
        for index in range(4)
    ]
    return TutorialContent(title="準備會議",
                           problem="會議前的準備步驟散在多個頁面，新人找不到。",
                           prerequisites=["已登入工作區"], steps=steps,
                           expected_outcome="會議開始前已備妥議程與摘要。")


def version_plan(version_id: str, *, supersedes: str | None) -> VersionPlan:
    slug, number = parse_version_id(version_id)
    return VersionPlan(version_id=version_id, slug=slug, number=number, supersedes=supersedes,
                       reason="release:r_42" if supersedes else "gap:c12",
                       rules_applied=(), operation_id=f"op-test-{version_id}")


class _NullOperations:
    """只吃 `record_version` 的假 coordinator（同 `test_publish_cutpoints.py` 的做法）。"""

    def record_version(self, operation_id: str, version_id: str) -> None:
        """本檔觀察的是 `site/` 的物件，operation 紀錄不在掃描範圍。"""


def _seed_published_v1(repository: Repository, renderer: SiteRenderer) -> None:
    """已發布的 v1（不經 `Publisher`，只鋪資料），讓 v2 有前一版可以比較。

    v1 的**公開頁也要真的寫出去**：v2 的版本選擇會連到 `v1.html`，教學索引也會列它。
    上一次發布本來就會留下那個物件，沒鋪的話「每個 href 都指得到 key」會誤判成 bug。
    公開頁一律由同一個 renderer 產生，不手寫 HTML。
    """
    repository.put_meta(Feature(feature_id=FEATURE, name=FEATURE, aliases=[], first_seen=NOW))
    repository.put_meta(Tutorial(slug=SLUG, current_version=None, topic="準備會議",
                                 feature_ids=[FEATURE], status=TutorialStatus.ACTIVE,
                                 successor=None, cluster_id="c12"))
    repository.put_meta(TutorialVersion(version_id=V1, slug=SLUG, supersedes=None,
                                        reason="gap:c12", rules_applied=[],
                                        s3_key=markdown_key(SLUG, 1), published_at=NOW))
    put_private_artifact(repository, markdown_key(SLUG, 1),
                         render_markdown(four_step_content()), MARKDOWN_CONTENT_TYPE)
    put_private_artifact(repository, diff_key(SLUG, 1), "", DIFF_CONTENT_TYPE)
    pk = tutorial_pk(SLUG)
    repository.update_meta(pk, {"current_version": V1},
                           expected_revision=repository.revision_of(pk))
    tutorial = repository.get_tutorial(SLUG)
    version = repository.get_version(V1)
    assert tutorial is not None and version is not None
    content = four_step_content()
    steps = [TutorialStep(tutorial_version=V1, number=draft.number, type=draft.type,
                          text=draft.text, feature_id=draft.feature_id)
             for draft in content.steps]
    repository.put_object(f"{PUBLIC_SITE_PREFIX}tutorials/{SLUG}/v1.html",
                          renderer.render_version_page(tutorial, version, steps,
                                                       content).encode("utf-8"),
                          SITE_PAGE_CONTENT_TYPE, if_none_match=False)


@pytest.fixture
def published_site(repository: Repository) -> Repository:
    """真的走一次 `Publisher.prepare` → `commit`，再把兩支資產寫進 `ASSET_KEYS`。

    刻意用真的 `Publisher` 而不是手寫 HTML：本檔要證明的是「renderer 產生的 href」與
    「`publishing` 算出來的 key」對得起來，手寫任何一邊都會讓這個斷言失去意義。
    """
    renderer = SiteRenderer(notice=NOTICE, batch=BATCH, categories=CATEGORIES)
    _seed_published_v1(repository, renderer)
    create_version(version_plan(V2, supersedes=V1), four_step_content(), repository)
    publisher = Publisher(repository, renderer, _NullOperations())
    prepared = publisher.prepare(PublishRequest((V2,), OPERATION), now=NOW)
    assert publisher.commit(prepared, now=NOW).published == (V2,)
    for key in ASSET_KEYS:
        name = Path(key).name
        repository.put_object(key, (ASSET_DIR / name).read_bytes(),
                              _ASSET_TYPES[Path(name).suffix], if_none_match=False)
    return repository


def public_objects(bucket: Any) -> dict[str, bytes]:
    return {item.key: item.get()["Body"].read()
            for item in bucket.objects.all() if item.key.startswith(PUBLIC_SITE_PREFIX)}


def test_no_public_object_is_marked_unpublished(
        published_site: Repository, bucket: Any) -> None:
    """Given 發布完成的站／When 掃描 `site/`／Then 沒有任何 `data-published="false"`。

    這是第二道：`_put_public_object` 的 `UNPUBLISHED_MARKER` 守門已經在 runtime 擋一次
    （00A §3.8），整站掃描是「萬一有人繞過那個出口」的兜底。
    """
    objects = public_objects(bucket)
    assert objects, "整站掃描至少要掃到一個公開物件，否則這條測試什麼都沒證明"
    for key, body in objects.items():
        assert UNPUBLISHED_MARKER not in body, key
    assert b'data-published="true"' in objects[f"{PUBLIC_SITE_PREFIX}tutorials/{SLUG}/v2.html"]


def test_no_public_object_leaks_a_private_field(
        published_site: Repository, bucket: Any) -> None:
    """Given 發布完成的站／When 掃描 `site/`／Then 沒有 `reason`、上游 ID 或私有前綴。"""
    for key, body in public_objects(bucket).items():
        if not key.endswith(".html"):
            continue
        text = body.decode("utf-8")
        for secret in PRIVATE_STRINGS:
            assert secret not in text, f"{key} 洩漏了 {secret}"


def test_every_in_page_link_resolves_to_a_real_object(
        published_site: Repository, bucket: Any) -> None:
    """Given 發布完成的站／When 解析每一頁的 href／Then 每個目標都是實際存在的 key。

    href 是瀏覽器相對路徑、key 是 S3 物件名，兩者由不同模組算出來（`site` 與 `publishing`，
    而且 `site` 不能 import `publishing`）。這條測試就是那道接縫的唯一自動檢查：少了它，
    `v3.diff.txt` 這種相對連結寫錯一個字也要等到人工開瀏覽器才會發現。
    """
    objects = public_objects(bucket)
    checked = 0
    for key, body in objects.items():
        if not key.endswith(".html"):
            continue
        for href in _HREF.findall(body.decode("utf-8")):
            target = (href.lstrip("/") if href.startswith("/")
                      else posixpath.normpath(posixpath.join(posixpath.dirname(key), href)))
            assert target in objects, f"{key} 的 {href} 指到不存在的 {target}"
            checked += 1
    assert checked >= 6, f"只檢查到 {checked} 個連結，掃描範圍太小"


def test_the_public_site_contains_exactly_the_expected_keys(
        published_site: Repository, bucket: Any) -> None:
    """Given 發布完成的站／When 列出 `site/`／Then 只有四種頁面加兩支資產，沒有多餘物件。"""
    assert sorted(public_objects(bucket)) == sorted([
        f"{PUBLIC_SITE_PREFIX}index.html",
        f"{PUBLIC_SITE_PREFIX}tutorials/{SLUG}/index.html",
        f"{PUBLIC_SITE_PREFIX}tutorials/{SLUG}/v1.html",
        f"{PUBLIC_SITE_PREFIX}tutorials/{SLUG}/v2.diff.txt",
        f"{PUBLIC_SITE_PREFIX}tutorials/{SLUG}/v2.html",
        *ASSET_KEYS,
    ])


def test_the_published_page_carries_the_widget_and_the_not_sent_status(
        published_site: Repository, bucket: Any) -> None:
    """Given 發布完成的版本頁／When 讀它／Then widget 在、狀態文案是「尚未送出」那一種。"""
    body = public_objects(bucket)[f"{PUBLIC_SITE_PREFIX}tutorials/{SLUG}/v2.html"]
    page = body.decode("utf-8")
    assert 'id="tkb-widget"' in page and 'id="tkb-download"' in page
    assert "尚未送出" in page
    assert "已送出" not in page.replace("尚未送出", "")
    assert SITE_PAGE_CONTENT_TYPE  # 公開頁一律 text/html; charset=utf-8（P24 決定）


# --- Phase 42（W2）補上的 roundtrip：下載檔 -> import_feedback／import_view ------
#
# controller 核准的 R3.6 例外：`import_feedback` 的 owner 是 Phase 42，檔頭的 TODO 指名
# 把這幾個案例補進**本檔**而不是另開一支。前半驗的是「下載檔長得對」，這一段驗的是
# 「維護者真的匯得進去」——兩者接不起來的話，widget 產出的檔就只是好看的 JSON。


def view_envelope() -> dict[str, Any]:
    """`widget.js` 的瀏覽紀錄封套；三個欄位與 `VIEW_FIELDS` 對得上。"""
    return {"kind": "view", "source": "site_widget", "generated_at": "2026-09-14T00:30:45Z",
            "note": f"{NOTICE}｜此檔尚未送出，需由維護者匯入",
            "items": [{"tutorial_version": V2, "user": USER, "ts": "2026-09-13T12:34:56Z"}]}


@pytest.fixture
def imported(published_site: Repository) -> tuple[Repository, OperationCoordinator]:
    """已發布的站 ＋ 建在同一個 moto 表上的操作紀錄。"""
    return published_site, OperationCoordinator(published_site)


def test_the_downloaded_feedback_file_imports_into_the_graph(
        imported: tuple[Repository, OperationCoordinator]) -> None:
    """Given widget 下載的回饋檔／When `import_feedback`／Then `saved` 並掛在 `@v2` 上。"""
    repository, operations = imported
    item = feedback_envelope()["items"][0]
    result = import_feedback(item, repository=repository, operations=operations, now=NOW)
    assert (result.status, result.object_id) == ("saved", item["id"])
    assert [row.id for row in repository.list_feedback_of_version(V2)] == [item["id"]]


def test_the_same_downloaded_feedback_imported_twice_is_a_duplicate(
        imported: tuple[Repository, OperationCoordinator]) -> None:
    """Given 維護者不小心匯入同一個檔兩次／When 再匯一次／Then `duplicate`，樣本數不變。"""
    repository, operations = imported
    item = feedback_envelope()["items"][0]
    first = import_feedback(item, repository=repository, operations=operations, now=NOW)
    again = import_feedback(item, repository=repository, operations=operations, now=NOW)
    assert (first.status, again.status) == ("saved", "duplicate")
    assert len(repository.list_feedback_of_version(V2)) == 1


def test_a_string_rating_in_the_download_is_rejected_at_import(
        imported: tuple[Repository, OperationCoordinator]) -> None:
    """Given 下載檔的 `rating` 被改成 `"4"`／When 匯入／Then `rejected` 且指名 `rating`。

    前半的 `test_downloaded_rating_is_a_json_number_not_a_string` 守的是模型層；
    這裡守的是匯入端真的回得出「哪個欄位不合法」（`COL` Rule 3、F51）。
    """
    repository, operations = imported
    item = {**feedback_envelope()["items"][0], "rating": "4"}
    result = import_feedback(item, repository=repository, operations=operations, now=NOW)
    assert (result.status, result.invalid_fields) == ("rejected", ("rating",))
    assert repository.list_feedback_of_version(V2) == []


def test_the_downloaded_view_file_imports_and_deduplicates(
        imported: tuple[Repository, OperationCoordinator]) -> None:
    """Given widget 下載的瀏覽紀錄檔／When 匯入兩次／Then `saved` 之後 `duplicate`。"""
    repository, operations = imported
    item = view_envelope()["items"][0]
    first = import_view(item, repository=repository, operations=operations, now=NOW)
    again = import_view(item, repository=repository, operations=operations, now=NOW)
    assert (first.status, again.status) == ("saved", "duplicate")
    assert [row.user for row in repository.list_views_of_version(V2)] == [USER]
