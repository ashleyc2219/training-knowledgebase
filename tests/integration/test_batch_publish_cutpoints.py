"""Phase 25 Task 3：多篇整批發布路徑上五個失敗切點的**可觀察結果**（moto）。

| # | 切點 | DynamoDB | 公開 `site/` | 判定 |
|---:|---|---|---|---|
| 1 | `assert_batch_publishable` 拒絕 | 全部舊 | 全部舊 | 合格：零篇發布。 |
| 2 | `prepare` 第 2 篇失敗 | 全部舊 | 全部舊 | 合格：前 1 篇 staging 留在私有 `operations/`。 |
| 3 | `inspect` 回 `ok=False` | 全部舊 | 全部舊 | 合格：`commit` 不執行交易。 |
| 4 | 交易被取消／中斷 | 全部舊 | 全部舊 | 合格：DynamoDB 保證 all-or-nothing。 |
| 5 | 交易成功、promote 第 2 篇失敗 | **全部新** | 第 1 篇新、其餘舊 | **不合格：partial 可見。** |

切點 5 對應 Phase 12 的 O3 切點 `a3_after_first_site_before_second`，**判定屬於
[Phase 12](../../docs/plan/unfinish/12-Phase12-O3發布切換整合驗證.md) 的 O3 報告**；本檔只負責
製造與記錄這個觀察。它**沒有**被標成 `xfail`、斷言也沒有被改寫成「partial 可以接受」：測試
斷言的就是「A 新 B 舊」這個事實本身，F49 沒有被放寬，公開路徑仍然停在 FAIL。

觀察方法與 Phase 12 的 spike、Phase 24 的單篇切點檔一致：DynamoDB 一律基表一致讀取
（`get_tutorial`／`get_version` 內部都是 `ConsistentRead=True`），公開世代取
`site/tutorials/<slug>/index.html` 的 `data-site-version` 標記，公開頁直接讀物件、不存在回
`None`。**真實 website endpoint 的 HTTP 回應延後至 P41／P59**（controller 2026-09-14 裁決）：
本檔在 moto 上跑、**不標 `aws`**（00A §3.2），moto 全綠不是 O3 的驗收證據。

`injected_fault` 是**本檔內**的 `contextmanager`，用 `monkeypatch` 把對應呼叫換成丟
`TransientError` 的替身。Phase 59 之後才有正式的 `TKB_FAULT` 切點，本 Phase 不預先使用它，
也不假裝它已存在。
"""

import json
import re
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import pytest

from training_kb.content import (
    DIFF_CONTENT_TYPE,
    MARKDOWN_CONTENT_TYPE,
    VersionPlan,
    create_version,
    diff_key,
    markdown_key,
    parse_version_id,
    put_private_artifact,
    render_markdown,
)
from training_kb.errors import PublishError, TransientError
from training_kb.keys import tutorial_pk
from training_kb.models import (
    Feature,
    StepDraft,
    StepType,
    Tutorial,
    TutorialContent,
    TutorialStatus,
    TutorialStep,
    TutorialVersion,
)
from training_kb.operations import AcceptOperation, OperationCoordinator
from training_kb.publishing import (
    Publisher,
    PublishInspection,
    PublishRequest,
    PublishResult,
    promote_site_objects,
)
from training_kb.repository import Repository
from training_kb.site import SiteRenderer

FEATURE = "Prepare"
SLUG_A = "prepare-meeting"
SLUG_B = "share-summary"
A2 = f"{SLUG_A}@v2"
A3 = f"{SLUG_A}@v3"
B1 = f"{SLUG_B}@v1"
B2 = f"{SLUG_B}@v2"
OPERATION = "op-review-0914"
NOW = datetime(2026, 9, 14, 0, 30, tzinfo=UTC)
PENDING_KEY = f"operations/{OPERATION}/pending-promote.json"

NEW_PAGES = (f"site/tutorials/{SLUG_A}/v3.html", f"site/tutorials/{SLUG_B}/v2.html")
NEW_PUBLIC = [f"site/tutorials/{SLUG_A}/v3.html", f"site/tutorials/{SLUG_A}/v3.diff.txt",
              f"site/tutorials/{SLUG_B}/v2.html", f"site/tutorials/{SLUG_B}/v2.diff.txt"]
OLD_PUBLIC = sorted(["site/index.html",
                     f"site/tutorials/{SLUG_A}/index.html", f"site/tutorials/{SLUG_A}/v2.html",
                     f"site/tutorials/{SLUG_B}/index.html", f"site/tutorials/{SLUG_B}/v1.html"])
"""上一次發布留下的公開物件；切點 1–4 之後 `site/` 必須還是這五個。"""

_TEXTS = ("開啟行事曆。", "選擇今天的會議。", "開啟摘要。", "確認摘要內容。")
_TYPES = ("read", "click_ui", "click_ui", "read")
_SITE_VERSION = re.compile(r'data-site-version="(v[0-9]+)"')


# --- 共用器材 ---------------------------------------------------------------


def four_step_content(title: str) -> TutorialContent:
    steps = [
        StepDraft(number=index + 1, type=StepType(_TYPES[index]), text=_TEXTS[index],
                  feature_id=FEATURE)
        for index in range(4)
    ]
    return TutorialContent(title=title,
                           problem="會議前的準備步驟散在多個頁面，新人找不到。",
                           prerequisites=["已登入工作區"], steps=steps,
                           expected_outcome="會議開始前已備妥議程與摘要。")


def version_plan(version_id: str, *, supersedes: str | None) -> VersionPlan:
    slug, number = parse_version_id(version_id)
    return VersionPlan(version_id=version_id, slug=slug, number=number, supersedes=supersedes,
                       reason="release:r_42" if supersedes else "gap:c12",
                       rules_applied=(), operation_id=f"op-test-{version_id}")


def seed_tutorial(repository: Repository, slug: str, title: str, published: str,
                  draft: str) -> None:
    """一篇教學的起始狀態：一個**已發布**舊版（公開站讀得到）＋一個完整未發布新版。"""
    _, number = parse_version_id(published)
    content = four_step_content(title)
    repository.put_meta(Tutorial(slug=slug, current_version=None, topic=title,
                                 feature_ids=[FEATURE], status=TutorialStatus.ACTIVE,
                                 successor=None, cluster_id="c12"))
    repository.put_meta(TutorialVersion(version_id=published, slug=slug, supersedes=None,
                                        reason="gap:c12", rules_applied=[],
                                        s3_key=markdown_key(slug, number), published_at=NOW))
    put_private_artifact(repository, markdown_key(slug, number), render_markdown(content),
                         MARKDOWN_CONTENT_TYPE)
    put_private_artifact(repository, diff_key(slug, number), "", DIFF_CONTENT_TYPE)
    pk = tutorial_pk(slug)
    repository.update_meta(pk, {"current_version": published},
                           expected_revision=repository.revision_of(pk))
    _seed_public_generation(repository, slug, published, content)
    create_version(version_plan(draft, supersedes=published), content, repository)


def _seed_public_generation(repository: Repository, slug: str, published: str,
                            content: TutorialContent) -> None:
    """上一次成功發布已經把公開頁寫出去：`site/` 的**舊世代**真的存在。

    切點表寫的是「公開 `site/`：全部舊」，所以舊世代必須存在，否則切點 5 只能證明
    「公開站是空的」，不是「公開站一新一舊」（Phase 24 報告 §5.5 的同一個教訓）。
    """
    renderer = SiteRenderer()
    tutorial = repository.get_tutorial(slug)
    version = repository.get_version(published)
    assert tutorial is not None and version is not None
    _, number = parse_version_id(published)
    steps = [TutorialStep(tutorial_version=published, number=draft.number, type=draft.type,
                          text=draft.text, feature_id=draft.feature_id)
             for draft in content.steps]
    pages = {
        f"site/tutorials/{slug}/v{number}.html": renderer.render_version_page(
            tutorial, version, steps, content),
        f"site/tutorials/{slug}/index.html": renderer.render_tutorial_index(
            tutorial, [version]),
    }
    for key, page in pages.items():
        repository.put_object(key, page.encode("utf-8"), "text/html; charset=utf-8",
                              if_none_match=False)


def _seed_public_site_index(repository: Repository) -> None:
    tutorials = [repository.get_tutorial(SLUG_A), repository.get_tutorial(SLUG_B)]
    assert all(tutorial is not None for tutorial in tutorials)
    page = SiteRenderer().render_site_index([t for t in tutorials if t is not None])
    repository.put_object("site/index.html", page.encode("utf-8"),
                          "text/html; charset=utf-8", if_none_match=False)


@dataclass(frozen=True)
class SiteReader:
    """一個切點當下**對外看得到**的事實：公開物件 ＋ 當時的 `TUTORIAL` item。

    兩者一起讀、一起印，時間戳才對得上（Phase 25 §8 的人工驗收要求）。真實 website
    endpoint 的 HTTP 回應延後至 P41／P59；moto 上讀的是同一個公開 key。
    """

    repository: Repository
    bucket: Any

    def read(self, key: str) -> bytes | None:
        return self.repository.get_object(key)

    def current_version(self, slug: str) -> str | None:
        tutorial = self.repository.get_tutorial(slug)
        return None if tutorial is None else tutorial.current_version

    def published_at(self, version_id: str) -> str | None:
        version = self.repository.get_version(version_id)
        if version is None or version.published_at is None:
            return None
        return version.published_at.isoformat()

    def generation(self, slug: str) -> str | None:
        body = self.read(f"site/tutorials/{slug}/index.html")
        found = None if body is None else _SITE_VERSION.search(body.decode("utf-8"))
        return None if found is None else found.group(1)

    def public_keys(self) -> list[str]:
        return sorted(item.key for item in self.bucket.objects.all()
                      if item.key.startswith("site/"))

    def report(self, cut_point: str) -> str:
        rows = [f"[{cut_point}]"]
        for slug, new_version, page in ((SLUG_A, A3, NEW_PAGES[0]),
                                        (SLUG_B, B2, NEW_PAGES[1])):
            rows.append(
                f"  {slug}: current_version={self.current_version(slug)} "
                f"published_at({new_version})={self.published_at(new_version)} "
                f"site_generation={self.generation(slug)} "
                f"GET {page} -> {'200' if self.read(page) is not None else '404'}")
        return "\n".join(rows)


def publish_batch(publisher: Publisher) -> PublishResult:
    """整批三段式的呼叫端：`prepare` -> `commit`（`commit` 內部自己再 `inspect` 一次）。"""
    prepared = publisher.prepare(PublishRequest((A3, B2), OPERATION), now=NOW)
    return publisher.commit(prepared, now=NOW)


@contextmanager
def injected_fault(fault: str, *, publisher: Publisher, repository: Repository,
                   monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """把切點 2／3／4 對應的呼叫換成丟 `TransientError` 的替身。

    Phase 59 之後才有正式的 `TKB_FAULT`；這裡只用 `monkeypatch`，注入點分別是
    `Publisher._stage_one`（prepare 第 k 篇）、`Publisher.inspect`、`Repository.transact_write`。
    """
    if fault == "prepare_second":
        original = publisher._stage_one

        def failing_stage(version_id: str, operation_id: str) -> tuple[str, str]:
            if version_id == B2:
                raise TransientError("prepare_second 注入：第二篇 staging 失敗")
            return original(version_id, operation_id)

        monkeypatch.setattr(publisher, "_stage_one", failing_stage)
    elif fault == "inspect_second":
        monkeypatch.setattr(publisher, "inspect", lambda _: PublishInspection(
            ok=False, problems=(f"inspect_second 注入：{B2} 未通過",)))
    elif fault == "transact":
        def failing_transact(items: Any) -> int | None:
            raise TransientError("transact 注入：交易未能送出")

        monkeypatch.setattr(repository, "transact_write", failing_transact)
    else:  # pragma: no cover - 參數化清單以外的值是測試自己寫錯
        raise AssertionError(f"unknown fault: {fault}")
    yield


@contextmanager
def failing_second_promote(publisher: Publisher,
                           monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """切點 5：交易成功、第 1 篇已 promote，第 2 篇的公開物件還沒寫出去就中斷。"""
    original = publisher._promote

    def failing(version_id: str, operation_id: str) -> None:
        if version_id == B2:
            raise TransientError("a3_after_first_site_before_second 注入")
        original(version_id, operation_id)

    monkeypatch.setattr(publisher, "_promote", failing)
    yield


@pytest.fixture
def aws_publisher(repository: Repository, bucket: Any) -> Publisher:  # noqa: ARG001
    """兩篇都已有已發布舊版且公開 URL 讀得到；兩個新版都是 `published_at=null`、公開站讀不到。

    fixture 名沿用 Phase 25 §7 Task 3 的字面；**它跑在 moto 上、不標 `aws`**（00A §3.2），
    真實 AWS 的同一組切點重跑延後至 P41／P59。`bucket` 只是為了共用同一個 `mock_aws` 區塊。
    """
    repository.put_meta(Feature(feature_id=FEATURE, name=FEATURE, aliases=[], first_seen=NOW))
    seed_tutorial(repository, SLUG_A, "準備會議", A2, A3)
    seed_tutorial(repository, SLUG_B, "分享摘要", B1, B2)
    _seed_public_site_index(repository)
    operations = OperationCoordinator(repository)
    operations.accept(AcceptOperation(operation_id=OPERATION, kind="feedback-review",
                                      canonical_id="r_1", project_id="p_1", now=NOW))
    return Publisher(repository, SiteRenderer(), operations)


@pytest.fixture
def site_reader(repository: Repository, bucket: Any) -> SiteReader:
    """公開物件與 `TUTORIAL` item 的同時觀察點；每個切點各印一筆存證。"""
    return SiteReader(repository, bucket)


# --- 五個切點 ---------------------------------------------------------------


def test_batch_cutpoint_1_rejects_before_any_staging(
        aws_publisher: Publisher, site_reader: SiteReader) -> None:
    """切點 1：同一篇教學兩個版本同批 → `assert_batch_publishable` 拒絕，零 staging、零發布。"""
    with pytest.raises(PublishError, match="同一篇教學"):
        aws_publisher.prepare(PublishRequest((A3, f"{SLUG_A}@v4"), OPERATION), now=NOW)
    print(site_reader.report("1_assert_batch_publishable"))
    assert site_reader.public_keys() == OLD_PUBLIC
    assert site_reader.read(PENDING_KEY) is None
    assert site_reader.current_version(SLUG_A) == A2
    assert site_reader.current_version(SLUG_B) == B1


@pytest.mark.parametrize("fault", ["prepare_second", "inspect_second", "transact"])
def test_batch_cutpoints_2_to_4_keep_everything_old(
        fault: str, aws_publisher: Publisher, site_reader: SiteReader,
        repository: Repository, monkeypatch: pytest.MonkeyPatch) -> None:
    """切點 2／3／4：往外丟例外，而且兩篇的 DynamoDB 與公開站都停在舊版（F49）。

    斷言逐字取自 Phase 25 §7 Task 3 Step 1；`repository` 與 `monkeypatch` 是注入故障需要的
    額外 fixture，觀察面不變。
    """
    with injected_fault(fault, publisher=aws_publisher, repository=repository,
                        monkeypatch=monkeypatch), \
            pytest.raises((PublishError, TransientError)):
        publish_batch(aws_publisher)
    print(site_reader.report(f"2_to_4:{fault}"))
    assert site_reader.read("site/tutorials/prepare-meeting/v3.html") is None
    assert site_reader.read("site/tutorials/share-summary/v2.html") is None
    assert site_reader.current_version("prepare-meeting") == "prepare-meeting@v2"
    assert site_reader.current_version("share-summary") == "share-summary@v1"
    assert site_reader.public_keys() == OLD_PUBLIC
    assert site_reader.generation(SLUG_A) == "v2" and site_reader.generation(SLUG_B) == "v1"


def test_batch_cutpoint_4_cancelled_transaction_keeps_everything_old(
        aws_publisher: Publisher, site_reader: SiteReader, repository: Repository,
        monkeypatch: pytest.MonkeyPatch) -> None:
    """切點 4 的另一半：交易**被取消**（第 2 篇基底在交易當下才位移）。

    `commit` 回 `PublishResult` 而不是丟例外——條件不符是預期內的併發結果；重點是第 1 篇
    也**沒有**被切走（DynamoDB 的 all-or-nothing），公開站一個新檔都沒有。
    """
    original = repository.transact_write

    def moving(items: Any) -> int | None:
        pk = tutorial_pk(SLUG_B)
        repository.update_meta(pk, {"current_version": f"{SLUG_B}@v7"},
                               expected_revision=repository.revision_of(pk))
        return original(items)

    monkeypatch.setattr(repository, "transact_write", moving)
    result = publish_batch(aws_publisher)
    print(site_reader.report("4_transaction_cancelled"))
    assert result == PublishResult(published=(), failed=B2,
                                   reasons=("current_version 不等於 supersedes",))
    assert site_reader.current_version(SLUG_A) == A2
    assert site_reader.published_at(A3) is None and site_reader.published_at(B2) is None
    assert site_reader.public_keys() == OLD_PUBLIC


def test_batch_cutpoint_5_partial_is_observed_not_accepted(
        aws_publisher: Publisher, site_reader: SiteReader,
        monkeypatch: pytest.MonkeyPatch) -> None:
    """切點 5：交易成功、promote 第 2 篇失敗 → **DynamoDB 全新、公開站一新一舊**。

    這就是 Phase 12 的 O3 切點 `a3_after_first_site_before_second`，也是設計 §8.3 明列、
    O3 尚未解的那一段。本測試**只製造與記錄**這個觀察，判定交給 Phase 12 的 O3 報告：

    - **不**標 `xfail`、**不**把斷言改成「partial 可以接受」；下面斷言的就是 partial 本身。
    - **不**刪掉已 promote 的 A 頁面充當回滾（事後刪除不消除曝光）。
    - **不**把 F49 改寫成「允許部分成功」，也**不**因為索引還沒指過去就當成沒有公開
      （設計 §18 O3 明文禁止）。

    留下的痕跡是 `pending-promote.json` 與私有 staging：Phase 59 以同一個 `operation_id`
    重送時照它精確補齊，不重新建版、不重新呼叫模型。
    """
    with failing_second_promote(aws_publisher, monkeypatch), \
            pytest.raises(PublishError, match="a3_after_first_site_before_second"):
        publish_batch(aws_publisher)
    print(site_reader.report("5_after_first_site_before_second"))
    assert site_reader.published_at(A3) == NOW.isoformat()
    assert site_reader.published_at(B2) == NOW.isoformat()
    assert site_reader.current_version(SLUG_A) == A3
    assert site_reader.current_version(SLUG_B) == B2
    assert site_reader.read(NEW_PAGES[0]) is not None, "第 1 篇的新頁已經對外可見"
    assert site_reader.read(NEW_PAGES[1]) is None, "第 2 篇還是舊版：這就是 partial 可見"
    assert site_reader.generation(SLUG_A) == "v2" and site_reader.generation(SLUG_B) == "v1"
    pending = json.loads(site_reader.read(PENDING_KEY) or b"{}")
    assert pending["site_keys"] == NEW_PUBLIC


def test_resending_the_same_operation_only_fills_the_missing_public_objects(
        aws_publisher: Publisher, site_reader: SiteReader, repository: Repository,
        monkeypatch: pytest.MonkeyPatch) -> None:
    """切點 5 之後以**同一個 `operation_id`** 重送：照 `pending-promote.json` 補齊缺的物件。

    正式的補償重送 `resume_publish` 歸 Phase 59；這裡只證明本 Phase 留下的痕跡**夠用**：
    清單完整、staging 還在、補齊之後沒有第三個版本、沒有新的 `version_id`。
    """
    prepared = aws_publisher.prepare(PublishRequest((A3, B2), OPERATION), now=NOW)
    with failing_second_promote(aws_publisher, monkeypatch), pytest.raises(PublishError):
        aws_publisher.commit(prepared, now=NOW)
    versions_before = sorted(str(row["PK"]) for row in repository.scan_entity("VERSION"))

    pending = json.loads(site_reader.read(PENDING_KEY) or b"{}")
    monkeypatch.undo()
    promoted = promote_site_objects(prepared, repository=repository)

    assert list(promoted) == pending["site_keys"]
    assert all(site_reader.read(key) is not None for key in pending["site_keys"])
    assert sorted(str(row["PK"]) for row in repository.scan_entity("VERSION")) == versions_before
    assert pending["version_ids"] == [A3, B2]
    assert site_reader.generation(SLUG_A) == "v2", "索引還沒指過去，但不會指向不存在的頁"


def test_batch_happy_path_switches_both_generations(
        aws_publisher: Publisher, site_reader: SiteReader) -> None:
    """沒有注入失敗：兩篇一起切到新版，兩個公開世代同時前進，`site/` 只有已發布內容。"""
    assert publish_batch(aws_publisher).published == (A3, B2)
    print(site_reader.report("happy"))
    assert site_reader.public_keys() == sorted(OLD_PUBLIC + NEW_PUBLIC)
    assert site_reader.generation(SLUG_A) == "v3" and site_reader.generation(SLUG_B) == "v2"
    for key in site_reader.public_keys():
        body = site_reader.read(key)
        assert body is not None
        assert b'data-published="false"' not in body, f"未發布標記不得進 site/：{key}"
