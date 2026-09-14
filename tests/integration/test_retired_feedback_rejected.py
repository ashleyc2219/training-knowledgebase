"""Phase 26 Task 3：退役之後拒絕新回饋、既有回饋仍可讀、瀏覽紀錄照收（moto 本機表）。

`repo` 是本檔的 fixture：`tests/integration/conftest.py` 的 `repository`（moto 表＋bucket，
owner 是 Phase 08）加上本 Phase 的固定種子，**不改那支 conftest**（00A §3.2）。

```text
meeting-summary   active、current=@v2
  VERSION @v1 / @v2         published_at 已有值
  STEP   @v2 #1             REFERENCES -> FEATURE#Summary
  FEEDBACK f_12             REFERS_TO -> VERSION#meeting-summary@v2
  S3     tutorials/meeting-summary/v2.md
```

moto 的 PASS 只證明資料形狀，不是實表／實 bucket 行為的證據；本檔也**不**宣稱 O3 通過
（退役不發布新版本，根本不走發布切點）。
"""

from datetime import UTC, datetime

import pytest

from training_kb.content import assert_accepts_feedback, retire_tutorial
from training_kb.errors import IngressError
from training_kb.keys import META, feedback_pk, step_pk, tutorial_pk, version_pk
from training_kb.models import (
    Feedback,
    StepType,
    Tutorial,
    TutorialStatus,
    TutorialStep,
    TutorialVersion,
    TutorialView,
)
from training_kb.repository import Repository

NOW = datetime(2026, 9, 14, 9, 0, tzinfo=UTC)
PUBLISHED_AT = datetime(2026, 9, 1, tzinfo=UTC)
SLUG = "meeting-summary"
SUCCESSOR = "prepare-meeting"
V1 = f"{SLUG}@v1"
V2 = f"{SLUG}@v2"
FEATURE = "Summary"
REASON = "release:r_88"
MARKDOWN_KEY = f"tutorials/{SLUG}/v2.md"
MARKDOWN = "# 會議摘要\n\n## Steps\n\n1. (type=read, feature=Summary) 打開摘要頁。\n"


def _version(version_id: str, *, supersedes: str | None, number: int) -> TutorialVersion:
    return TutorialVersion(version_id=version_id, slug=SLUG, supersedes=supersedes,
                           reason=REASON, rules_applied=[],
                           s3_key=f"tutorials/{SLUG}/v{number}.md", published_at=PUBLISHED_AT)


@pytest.fixture
def repo(repository: Repository) -> Repository:
    """固定種子；`repository` 本身是 moto 的表與 bucket（Phase 08 的 fixture）。"""
    repository.put_meta(Tutorial(slug=SLUG, current_version=V2, topic="會議摘要",
                                 feature_ids=[FEATURE], status=TutorialStatus.ACTIVE,
                                 successor=None, cluster_id="c12"))
    repository.put_meta(Tutorial(slug=SUCCESSOR, current_version=f"{SUCCESSOR}@v2",
                                 topic="準備會議", feature_ids=["Prepare"],
                                 status=TutorialStatus.ACTIVE, successor=None,
                                 cluster_id="c12"))
    repository.put_meta(_version(V1, supersedes=None, number=1))
    repository.put_meta(_version(V2, supersedes=V1, number=2))
    step = TutorialStep(tutorial_version=V2, number=1, type=StepType.READ,
                        text="打開摘要頁。", feature_id=FEATURE)
    repository.put_edge(step_pk(V2, step.number), "REFERENCES", f"FEATURE#{FEATURE}",
                        {"type": step.type.value, "text": step.text})
    repository.put_meta(Feedback(id="f_12", tutorial_version=V2, rating=2,
                                 category="找不到按鈕", comment="找不到那個按鈕。",
                                 user="u_01", ts=datetime(2026, 9, 2, tzinfo=UTC)))
    repository.put_edge(feedback_pk("f_12"), "REFERS_TO", version_pk(V2))
    repository.put_object(MARKDOWN_KEY, MARKDOWN.encode("utf-8"),
                          "text/markdown; charset=utf-8", if_none_match=False)
    return repository


def _history(repository: Repository) -> tuple[object, ...]:
    """退役前後必須逐字相同的東西：兩個 `VERSION` item、`STEP` 邊、回饋與 S3 全文。"""
    return (
        repository.query_pk(version_pk(V1)),
        repository.query_pk(version_pk(V2)),
        repository.query_pk(step_pk(V2, 1)),
        repository.query_pk(feedback_pk("f_12")),
        repository.get_object(MARKDOWN_KEY),
    )


def test_retired_tutorial_rejects_new_feedback_but_keeps_old(repo: Repository) -> None:
    """逐字取自 Phase 26 §7 Task 3 Step 1（F39）。"""
    retire_tutorial(SLUG, reason=REASON, successor=None,
                    repository=repo, now=NOW)
    tutorial = repo.get_tutorial(SLUG)
    assert tutorial is not None
    with pytest.raises(IngressError) as error:
        assert_accepts_feedback(tutorial)
    assert "tutorial_version" in error.value.fields
    assert [item.id for item in repo.list_feedback_of_version(V2)] == ["f_12"]


def test_active_tutorial_accepts_feedback(repo: Repository) -> None:
    """還在維護的教學：`assert_accepts_feedback` 什麼都不做（沒有回傳值可看）。"""
    tutorial = repo.get_tutorial(SLUG)
    assert tutorial is not None and tutorial.status == TutorialStatus.ACTIVE
    assert assert_accepts_feedback(tutorial) is None


def test_retired_tutorial_still_accepts_views(repo: Repository) -> None:
    """設計 §8.4 只擋回饋：瀏覽紀錄是重開票率的分母，擋掉指標會失真。"""
    retire_tutorial(SLUG, reason=REASON, successor=SUCCESSOR, repository=repo, now=NOW)
    view = TutorialView(tutorial_version=V2, user="u_02", ts=NOW)
    repo.put_meta(view)
    assert [item.user for item in repo.list_views_of_version(V2)] == ["u_02"]


def test_retire_keeps_versions_steps_feedback_and_markdown_untouched(repo: Repository) -> None:
    """人工驗收的自動化版：除了 `TUTORIAL` 的三個屬性以外，一個 byte 都沒有變。"""
    before = _history(repo)
    tutorial_before = repo.get_meta_item(tutorial_pk(SLUG))
    result = retire_tutorial(SLUG, reason=REASON, successor=SUCCESSOR,
                             repository=repo, now=NOW)
    assert (result.status, result.successor, result.current_version) == (
        TutorialStatus.RETIRED, SUCCESSOR, V2)
    assert _history(repo) == before
    tutorial_after = repo.get_meta_item(tutorial_pk(SLUG))
    assert tutorial_before is not None and tutorial_after is not None
    changed = {"status", "successor", "_revision"}
    assert set(tutorial_after) == set(tutorial_before)
    assert {k: v for k, v in tutorial_after.items() if k not in changed} == \
           {k: v for k, v in tutorial_before.items() if k not in changed}


def test_retire_writes_no_new_items_at_all(repo: Repository) -> None:
    """退役不建立新版本、不建 `SUCCESSOR` 邊（D22）：全表的鍵集合完全不變。"""
    keys_before = {(str(item["PK"]), str(item["SK"]))
                   for item in repo.query_pk(tutorial_pk(SLUG))}
    every_before = _every_key(repo)
    retire_tutorial(SLUG, reason=REASON, successor=SUCCESSOR, repository=repo, now=NOW)
    assert {(str(item["PK"]), str(item["SK"]))
            for item in repo.query_pk(tutorial_pk(SLUG))} == keys_before == {(tutorial_pk(SLUG),
                                                                              META)}
    assert _every_key(repo) == every_before


def _every_key(repository: Repository) -> set[tuple[str, str]]:
    found: set[tuple[str, str]] = set()
    for entity in ("TUTORIAL", "VERSION", "STEP", "FEEDBACK", "VIEW"):
        for item in repository.scan_entity(entity, meta_only=False):
            found.add((str(item["PK"]), str(item["SK"])))
    return found
