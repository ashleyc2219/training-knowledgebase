"""Phase 24 Task 3 Step 5：單篇發布路徑上三個失敗切點的**可觀察結果**（moto）。

切點代號與 [Phase 12](../../docs/plan/unfinish/12-Phase12-O3發布切換整合驗證.md) 的
`O3CutPoint` 相同，本檔只是在單篇路徑上重現它們：

| 切點 | DynamoDB | 公開 `site/` |
|---|---|---|
| `a1_before_transact`（交易前中斷） | `published_at=null`、`current_version` 舊值 | 舊版 |
| `a1_before_transact`（交易被取消） | 兩欄皆未變 | 舊版 |
| `a2_after_transact_before_site`（交易成功、寫 `site/` 前） | 已是新版 | **仍是舊版** |

觀察方法與 Phase 12 的 spike 一致：DynamoDB 一律基表一致讀取（`get_version`／`get_tutorial`
內部都是 `ConsistentRead=True`），公開世代取 `site/tutorials/<slug>/index.html` 的
`data-site-version` 標記，物件不存在回 `None`。

**這支檔案不標 `aws`，跑在 moto 上（00A §3.2）。** 它只證明程式在這三個切點的行為，
**不是 O3 的驗收證據**：O3 由 Phase 12 判定為 FAIL（`a2_after_transact_before_site` 是已知
partial），真實 AWS 的切點重跑延後到 P41／P59（controller 2026-09-14 裁決）。
不得因為本檔全綠就宣稱「發布故障驗收已通過」或「站台已上線」。
"""

import re
from collections.abc import Iterator
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
from training_kb.publishing import (
    PreparedPublish,
    Publisher,
    PublishInspection,
    PublishRequest,
)
from training_kb.repository import Repository
from training_kb.site import SiteRenderer, folder_slug

SLUG = "prepare-meeting"
FEATURE = "Prepare"
V1 = f"{SLUG}@v1"
V2 = f"{SLUG}@v2"
OPERATION = "op-pub-2"
NOW = datetime(2026, 9, 14, 0, 30, tzinfo=UTC)
TUTORIAL_INDEX = f"site/tutorials/{SLUG}/index.html"
VERSION_PAGE = f"site/tutorials/{SLUG}/v2.html"

_TEXTS = ("開啟行事曆。", "選擇今天的會議。", "開啟摘要。", "確認摘要內容。")
_TYPES = ("read", "click_ui", "click_ui", "read")
_SITE_VERSION = re.compile(r'data-site-version="(v[0-9]+)"')
OLD_PUBLIC = ["site/index.html", TUTORIAL_INDEX, f"site/tutorials/{SLUG}/v1.html"]
"""上一次發布（v1）留下的公開物件；三個失敗切點之後 `site/` 必須還是這三個。"""
FOLDER_PAGE = f"site/features/{folder_slug(FEATURE)}/index.html"
"""成功發布後多出來的功能資料夾頁（站台依功能分類）。"""


# --- 共用器材 ---------------------------------------------------------------


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


def seed_published_v1(repository: Repository) -> None:
    """已發布的 v1，加上它的公開世代標記：`site/` 的舊版就是 `data-site-version="v1"`。"""
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
    _seed_public_v1(repository)


def _seed_public_v1(repository: Repository) -> None:
    """v1 的上一次發布已經把公開頁寫出去了：`site/` 的**舊世代**是 `v1`。

    切點表寫的是「公開 `site/`：舊版」，所以舊世代必須真的存在，否則 `a2` 只能證明
    「公開站是空的」，不是「公開站落後一個世代」。這裡直接用同一個 renderer 產生，
    避免手寫 HTML 與 `SiteRenderer` 的輸出分岔。
    """
    renderer = SiteRenderer()
    tutorial = repository.get_tutorial(SLUG)
    version = repository.get_version(V1)
    assert tutorial is not None and version is not None
    content = four_step_content()
    steps = [TutorialStep(tutorial_version=V1, number=draft.number, type=draft.type,
                          text=draft.text, feature_id=draft.feature_id)
             for draft in content.steps]
    pages = {
        f"site/tutorials/{SLUG}/v1.html": renderer.render_version_page(
            tutorial, version, steps, content),
        TUTORIAL_INDEX: renderer.render_tutorial_index(tutorial, [version]),
        "site/index.html": renderer.render_site_index([tutorial]),
    }
    for key, page in pages.items():
        repository.put_object(key, page.encode("utf-8"), "text/html; charset=utf-8",
                              if_none_match=False)


@dataclass(frozen=True)
class Observation:
    """一個切點當下**對外看得到**的事實；一律在任何回復動作之前讀。"""

    cut_point: str
    published_at: str | None
    current_version: str | None
    site_generation: str | None
    staged_keys: tuple[str, ...]

    def report(self) -> str:
        return (f"[{self.cut_point}] published_at={self.published_at} "
                f"current_version={self.current_version} "
                f"site_generation={self.site_generation} "
                f"staging={len(self.staged_keys)} 個私有物件")


def observe(cut_point: str, repository: Repository, bucket: Any) -> Observation:
    version = repository.get_version(V2)
    tutorial = repository.get_tutorial(SLUG)
    body = repository.get_object(TUTORIAL_INDEX)
    found = None if body is None else _SITE_VERSION.search(body.decode("utf-8"))
    keys = tuple(sorted(item.key for item in bucket.objects.all()
                        if item.key.startswith(f"operations/{OPERATION}/")))
    return Observation(
        cut_point=cut_point,
        published_at=None if version is None or version.published_at is None
        else version.published_at.isoformat(),
        current_version=None if tutorial is None else tutorial.current_version,
        site_generation=None if found is None else found.group(1),
        staged_keys=keys,
    )


def public_keys(bucket: Any) -> list[str]:
    return sorted(item.key for item in bucket.objects.all() if item.key.startswith("site/"))


@pytest.fixture
def prepared_v2(repository: Repository) -> Iterator[tuple[Publisher, PreparedPublish]]:
    """完整未發布的 v2 已經 `prepare` 好，交易還沒送出（切點 `a1_before_transact` 的起點）。"""
    seed_published_v1(repository)
    create_version(version_plan(V2, supersedes=V1), four_step_content(), repository)
    publisher = Publisher(repository, SiteRenderer(), _NullOperations())
    yield publisher, publisher.prepare(PublishRequest((V2,), OPERATION), now=NOW)


class _NullOperations:
    """只吃 `record_version` 的假 coordinator：本檔要觀察的是 S3 與 DynamoDB 兩個欄位，
    operation 紀錄不在切點表裡，真的接 `OperationCoordinator` 反而要多 seed 一筆 `OPS#`。"""

    def __init__(self) -> None:
        self.recorded: list[tuple[str, str]] = []

    def record_version(self, operation_id: str, version_id: str) -> None:
        self.recorded.append((operation_id, version_id))


# --- 三個切點 ---------------------------------------------------------------


def test_cut_point_a1_before_transact(
        prepared_v2: tuple[Publisher, PreparedPublish], repository: Repository,
        bucket: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """交易送出前中斷：兩欄皆未變、公開站沒有任何物件，私有 staging 留著可重送（F36）。"""
    publisher, prepared = prepared_v2

    def broken(items: Any) -> int | None:
        raise TransientError("a1_before_transact 注入")

    monkeypatch.setattr(repository, "transact_write", broken)
    with pytest.raises(TransientError, match="a1_before_transact"):
        publisher.commit(prepared, now=NOW)
    found = observe("a1_before_transact", repository, bucket)
    print(found.report())
    assert found.published_at is None
    assert found.current_version == V1
    assert found.site_generation == "v1"
    assert found.staged_keys == prepared.staged_keys
    assert public_keys(bucket) == OLD_PUBLIC


def test_cut_point_a1_transaction_cancelled(
        prepared_v2: tuple[Publisher, PreparedPublish], repository: Repository,
        bucket: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """交易**被取消**（基底在交易當下才位移）：觀察結果與交易前中斷相同，但不丟例外。

    `inspect` 被換成一律通過，模擬「讀過之後才被別人改掉」——只有 DynamoDB 的條件擋得住它。
    """
    publisher, prepared = prepared_v2
    monkeypatch.setattr(publisher, "inspect",
                        lambda _: PublishInspection(ok=True, problems=()))
    pk = tutorial_pk(SLUG)
    repository.update_meta(pk, {"current_version": f"{SLUG}@v9"},
                           expected_revision=repository.revision_of(pk))
    result = publisher.commit(prepared, now=NOW)
    found = observe("a1_before_transact(cancelled)", repository, bucket)
    print(found.report())
    assert result.published == ()
    assert result.failed == V2
    assert result.reasons == ("current_version 不等於 supersedes",)
    assert found.published_at is None
    assert found.current_version == f"{SLUG}@v9"
    assert found.site_generation == "v1"
    assert public_keys(bucket) == OLD_PUBLIC


def test_cut_point_a2_after_transact_before_site(
        prepared_v2: tuple[Publisher, PreparedPublish], repository: Repository,
        bucket: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """交易成功、寫 `site/` 前中斷：**DynamoDB 已是新版、公開站仍是舊版**。

    這就是 Phase 12 判定的 partial。本 Phase 只把它**重現並記錄**，不宣稱已解決：
    補償重送 `resume_publish` 歸 Phase 59，真實 AWS 的重跑歸 P41／P59。
    """
    publisher, prepared = prepared_v2

    def broken(version_id: str, operation_id: str) -> None:
        raise TransientError("a2_after_transact_before_site 注入")

    monkeypatch.setattr(publisher, "_promote", broken)
    with pytest.raises(PublishError, match="a2_after_transact_before_site"):
        publisher.commit(prepared, now=NOW)
    found = observe("a2_after_transact_before_site", repository, bucket)
    print(found.report())
    assert found.published_at == NOW.isoformat()
    assert found.current_version == V2
    assert found.site_generation == "v1", "DynamoDB 已是 v2，公開站仍是 v1：這就是 partial"
    assert public_keys(bucket) == OLD_PUBLIC
    assert found.staged_keys == prepared.staged_keys, "私有 staging 保留，Phase 59 才有東西可補"


def test_happy_path_switches_generation_after_the_transaction(
        prepared_v2: tuple[Publisher, PreparedPublish], repository: Repository,
        bucket: Any) -> None:
    """沒有注入失敗時：兩欄切到 v2，公開世代才跟著變成 v2，而且 `site/` 只有已發布內容。"""
    publisher, prepared = prepared_v2
    assert publisher.commit(prepared, now=NOW).published == (V2,)
    found = observe("happy", repository, bucket)
    print(found.report())
    assert found.published_at == NOW.isoformat()
    assert found.current_version == V2
    assert found.site_generation == "v2"
    assert public_keys(bucket) == sorted([
        *OLD_PUBLIC, FOLDER_PAGE, f"site/tutorials/{SLUG}/v2.diff.txt", VERSION_PAGE,
    ])
    for key in public_keys(bucket):
        body = repository.get_object(key)
        assert body is not None
        assert b'data-published="false"' not in body, f"未發布標記不得進 site/：{key}"
