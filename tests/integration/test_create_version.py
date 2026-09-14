"""Phase 23：`create_version` 依固定順序寫出一個 `published_at=None` 的完整版本。

跑在 moto 的本機表與 bucket 上（`repository`／`table`／`bucket` fixture 來自
`tests/integration/conftest.py`，owner 是 Phase 06，本 Phase 不是它的修改者，所以共用器材
一律留在這兩支測試檔裡）。`test_version_complete.py` 直接 import 本檔的 `four_step_content`、
`version_plan` 與三個 seed 函式，兩支檔案因此只有一種內容形狀與一種種子資料。

**moto 全綠只證明資料形狀。** 發布切點（O3）仍未通過，本檔任何一條 PASS 都不代表
「發布」或「公開切換」已驗收；這裡寫出來的 v1／v2 在公開站上都看不到。
"""

from collections.abc import Sequence
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
    verify_version_complete,
)
from training_kb.errors import ContentError, TransientError
from training_kb.keys import feature_pk, rule_pk, step_pk, tutorial_pk, version_pk
from training_kb.models import (
    Feature,
    StepDraft,
    StepType,
    Tutorial,
    TutorialContent,
    TutorialStatus,
    TutorialVersion,
)
from training_kb.repository import Repository

SLUG = "prepare-meeting"
FEATURE = "Prepare"
NOW = datetime(2026, 9, 14, 9, 0, tzinfo=UTC)
V1 = f"{SLUG}@v1"
V2 = f"{SLUG}@v2"
V2_PLAN: dict[str, Any] = dict(number=2, supersedes=V1, reason="release:r_42",
                               rules_applied=("R-007",))

_TEXTS = ("開啟行事曆。", "選擇今天的會議。", "開啟摘要。", "確認摘要內容。")
_TYPES = ("read", "click_ui", "click_ui", "read")


# --- 共用器材 ---------------------------------------------------------------


def four_step_content(
    *,
    title: str = "準備會議",
    problem: str = "會議前的準備步驟散在多個頁面，新人找不到。",
    prerequisites: Sequence[str] | None = None,
    expected_outcome: str = "會議開始前已備妥議程與摘要。",
    step3_feature: str = FEATURE,
    step3_text: str = _TEXTS[2],
) -> TutorialContent:
    """與 `tests/unit/test_validate_content.py`、`test_markdown.py` 同名同語意的四步草稿。

    四步都引用 `Prepare`，編號 1–4，型態依序 `read`／`click_ui`／`click_ui`／`read`，
    第 3 步文字固定是「開啟摘要。」；三份文件不可各寫一種形狀。
    """
    features = (FEATURE, FEATURE, step3_feature, FEATURE)
    texts = (_TEXTS[0], _TEXTS[1], step3_text, _TEXTS[3])
    steps = [
        StepDraft(number=index + 1, type=StepType(_TYPES[index]), text=texts[index],
                  feature_id=features[index])
        for index in range(4)
    ]
    needs = list(prerequisites) if prerequisites is not None else ["已登入工作區"]
    return TutorialContent(title=title, problem=problem, prerequisites=needs,
                           steps=steps, expected_outcome=expected_outcome)


def version_plan(version_id: str, *, number: int, supersedes: str | None, reason: str,
                 rules_applied: Sequence[str] = ()) -> VersionPlan:
    """組一個 `VersionPlan`；`slug` 與 `number` 一律由 `parse_version_id` 對過才算數。

    正式路徑的 plan 由 Phase 20 的 `allocate_version` 產生，這裡只是把同一組欄位手動填好，
    所以本檔不需要 `OperationCoordinator`，也不測版號怎麼來（那是 Phase 20 與 O2 的責任）。
    """
    slug, parsed = parse_version_id(version_id)
    assert parsed == number, f"{version_id} 的號碼是 {parsed}，不是 {number}"
    return VersionPlan(version_id=version_id, slug=slug, number=number, supersedes=supersedes,
                       reason=reason, rules_applied=tuple(rules_applied),
                       operation_id=f"op-test-{version_id}")


def seed_feature_and_tutorial(repository: Repository) -> None:
    """`FEATURE#Prepare` 與 `TUTORIAL#prepare-meeting`（`current_version=None`）。"""
    repository.put_meta(Feature(feature_id=FEATURE, name=FEATURE, aliases=[], first_seen=NOW))
    repository.put_meta(Tutorial(slug=SLUG, current_version=None, topic="準備會議",
                                 feature_ids=[FEATURE], status=TutorialStatus.ACTIVE,
                                 successor=None, cluster_id="c12"))


def seed_published_v1(repository: Repository) -> None:
    """已發布的 v1：VERSION item 有 `published_at`、S3 有 `v1.md`、教學指向它。

    `current_version` 一起切到 v1 才是真實狀態（只有 publish 成功才會切換，F37）；
    v2 的 diff 也要讀得到 v1 全文，所以 `tutorials/prepare-meeting/v1.md` 必須存在。
    """
    seed_feature_and_tutorial(repository)
    repository.put_meta(TutorialVersion(version_id=V1, slug=SLUG, supersedes=None,
                                        reason="gap:c12", rules_applied=[],
                                        s3_key=markdown_key(SLUG, 1), published_at=NOW))
    put_private_artifact(repository, markdown_key(SLUG, 1),
                         render_markdown(four_step_content()), MARKDOWN_CONTENT_TYPE)
    put_private_artifact(repository, diff_key(SLUG, 1), "", DIFF_CONTENT_TYPE)
    pk = tutorial_pk(SLUG)
    repository.update_meta(pk, {"current_version": V1},
                           expected_revision=repository.revision_of(pk))


def fail_next(repository: Repository, name: str) -> None:
    """讓 `repository.<name>` 的**下一次**呼叫丟 `TransientError`，模擬寫到一半當機。

    直接覆寫 instance 屬性（`repository` fixture 每個測試都是新的），比 `monkeypatch`
    少一層還原邏輯：失敗那一次自己把原本的 bound method 放回去，所以重送走的是真實路徑。
    """
    original = getattr(repository, name)

    def failing(*args: object, **kwargs: object) -> None:
        setattr(repository, name, original)
        raise TransientError(f"{name} 中斷")

    setattr(repository, name, failing)


@dataclass(frozen=True)
class ReadyVersion:
    """已經跑完 `create_version` 的 v2，加上把它弄壞的方法（`verify_version_complete` 用）。

    破壞一律直接對 moto 的表與 bucket 動手，不經 `Repository`：`Repository` 沒有、也不該有
    刪除 API（設計 §8.2 規定失敗時保留產物）。
    """

    repository: Repository
    table: Any
    bucket: Any
    version: TutorialVersion

    def _delete_item(self, pk: str, sk: str) -> None:
        self.table.delete_item(Key={"PK": pk, "SK": sk})

    def delete_md(self) -> None:
        self.bucket.Object(markdown_key(SLUG, 2)).delete()

    def delete_diff(self) -> None:
        self.bucket.Object(diff_key(SLUG, 2)).delete()

    def delete_step_edge(self) -> None:
        self._delete_item(step_pk(V2, 3), f"REFERENCES#{feature_pk(FEATURE)}")

    def delete_feature(self) -> None:
        self._delete_item(feature_pk(FEATURE), "META")

    def delete_supersedes_edge(self) -> None:
        self._delete_item(version_pk(V2), f"SUPERSEDES#{version_pk(V1)}")

    def delete_applied_to_edge(self) -> None:
        self._delete_item("RULE#R-007", f"APPLIED_TO#{version_pk(V2)}")

    def delete_tutorial(self) -> None:
        self._delete_item(tutorial_pk(SLUG), "META")

    def add_extra_step_item(self) -> None:
        """全文只有四步，基表卻多一個 `STEP#…#5`（上一版留下的殘骸或手動補寫）。"""
        self.repository.put_edge(step_pk(V2, 5), "REFERENCES", feature_pk(FEATURE),
                                 {"type": "read", "text": "多出來的第五步。"})

    def add_extra_applied_to_edge(self) -> None:
        """`rules_applied` 沒有 R-999，卻有一條 `RULE#R-999 -> APPLIED_TO` 指向這一版。"""
        self.repository.put_edge(rule_pk("R-999"), "APPLIED_TO", version_pk(V2))

    def add_extra_supersedes_edge(self) -> None:
        """同一版指向兩個前一版：版本鏈分岔，追溯會得到兩個答案。"""
        self.repository.put_edge(version_pk(V2), "SUPERSEDES", version_pk("other-topic@v1"))

    def add_second_step_edge(self) -> None:
        """同一步再指向另一個 Feature：`get_steps` 會讀出兩步，關係就不完整了。"""
        self.repository.put_meta(Feature(feature_id="Summary", name="Summary", aliases=[],
                                         first_seen=NOW))
        self.repository.put_edge(step_pk(V2, 3), "REFERENCES", feature_pk("Summary"),
                                 {"type": "read", "text": _TEXTS[2]})


def build_ready_v2(repository: Repository, table: Any, bucket: Any) -> ReadyVersion:
    seed_published_v1(repository)
    version = create_version(version_plan(V2, **V2_PLAN), four_step_content(), repository)
    return ReadyVersion(repository=repository, table=table, bucket=bucket, version=version)


@pytest.fixture
def seeded_feature(repository: Repository) -> Repository:
    seed_feature_and_tutorial(repository)
    return repository


@pytest.fixture
def published_v1(repository: Repository) -> Repository:
    seed_published_v1(repository)
    return repository


# --- Task 1：依固定順序寫出未發布版本 ---------------------------------------


def test_create_version_writes_unpublished_version(seeded_feature: Repository) -> None:
    """`建立教學版本` Rule 4、Rule 6：reason 與 `s3_key` 都寫進 VERSION item。"""
    repository = seeded_feature
    plan = version_plan(V1, number=1, supersedes=None, reason="gap:c12")
    version = create_version(plan, four_step_content(), repository)
    assert version.published_at is None
    assert version.s3_key == "tutorials/prepare-meeting/v1.md"
    assert version.reason == "gap:c12"
    assert repository.object_exists("tutorials/prepare-meeting/v1.diff")
    tutorial = repository.get_tutorial(SLUG)
    assert tutorial is not None
    assert tutorial.current_version is None


def test_published_version_is_never_overwritten(published_v1: Repository) -> None:
    """已發布的版本不可覆寫：S3 沒有多出 `v1.diff` 以外的東西，DynamoDB 也不變。"""
    repository = published_v1
    plan = version_plan(V1, number=1, supersedes=None, reason="gap:c12")
    with pytest.raises(ContentError, match="已發布"):
        create_version(plan, four_step_content(), repository)
    version = repository.get_version(V1)
    assert version is not None
    assert version.published_at == NOW
    # 一條邊都沒有多寫出來：`VERSION#…@v1` 上只有 metadata item。
    assert [str(item["SK"]) for item in repository.query_pk(version_pk(V1))] == ["META"]


# --- Task 2：三種關係邊與 target 一致 ---------------------------------------


def test_step_reference_edge_target_matches_sk(published_v1: Repository) -> None:
    """`建立教學版本` Rule 8、Rule 10：STEP 本身就是邊，`target` 等於 SK 的終點。"""
    repository = published_v1
    create_version(version_plan(V2, **V2_PLAN), four_step_content(), repository)
    rows = repository.query_pk(step_pk(V2, 3), consistent=True)
    assert len(rows) == 1
    assert rows[0]["SK"] == "REFERENCES#FEATURE#Prepare"
    assert rows[0]["target"] == "FEATURE#Prepare"
    assert rows[0]["entity"] == "STEP"
    assert set(rows[0]) == {"PK", "SK", "target", "entity", "type", "text"}


def test_steps_round_trip_through_get_steps(published_v1: Repository) -> None:
    """寫入端少寫的欄位，讀取端必須算得出來（00A §3.6）：四步都還原得回 `TutorialStep`。"""
    repository = published_v1
    create_version(version_plan(V2, **V2_PLAN), four_step_content(), repository)
    steps = repository.get_steps(V2)
    assert [step.number for step in steps] == [1, 2, 3, 4]
    assert [str(step.type) for step in steps] == list(_TYPES)
    assert [step.feature_id for step in steps] == [FEATURE] * 4
    assert [step.tutorial_version for step in steps] == [V2] * 4
    assert steps[2].text == _TEXTS[2]


def test_supersedes_and_applied_to_edges_exist(published_v1: Repository) -> None:
    """`建立教學版本` Rule 3：`SUPERSEDES` 指向前一版；`APPLIED_TO` 只記本次的規則（F29）。"""
    repository = published_v1
    create_version(version_plan(V2, **V2_PLAN), four_step_content(), repository)
    supersedes = repository.list_edges(version_pk(V2), "SUPERSEDES")
    assert [(row["SK"], row["target"]) for row in supersedes] == [
        (f"SUPERSEDES#{version_pk(V1)}", version_pk(V1))]
    applied = repository.list_edges("RULE#R-007", "APPLIED_TO")
    assert [(row["SK"], row["target"]) for row in applied] == [
        (f"APPLIED_TO#{version_pk(V2)}", version_pk(V2))]
    version = repository.get_version(V2)
    assert version is not None
    assert version.rules_applied == ["R-007"]


def test_first_version_has_no_supersedes_edge(seeded_feature: Repository) -> None:
    """v1 沒有前一版：`VERSION#…@v1` 上只有 metadata item，`v1.diff` 是 0 位元組。"""
    repository = seeded_feature
    create_version(version_plan(V1, number=1, supersedes=None, reason="gap:c12"),
                   four_step_content(), repository)
    assert [str(item["SK"]) for item in repository.query_pk(version_pk(V1))] == ["META"]
    assert repository.get_object(diff_key(SLUG, 1)) == b""


def test_resending_a_different_plan_is_rejected(seeded_feature: Repository) -> None:
    """同一個版號只能有一種內容：換了 `reason`／`rules_applied` 重送一律拒絕，而且不寫任何邊。

    沿用既有 item 卻照新 plan 寫邊，會讓權威的 `VERSION.rules_applied` 與 `APPLIED_TO` 邊
    互相矛盾（D17），核對卻仍然通過。這與 `put_private_artifact` 比對 bytes 是同一個作法。
    """
    repository = seeded_feature
    create_version(version_plan(V1, number=1, supersedes=None, reason="gap:c12"),
                   four_step_content(), repository)
    changed = version_plan(V1, number=1, supersedes=None, reason="release:r_42",
                           rules_applied=("R-007",))
    with pytest.raises(ContentError, match="內容不同"):
        create_version(changed, four_step_content(), repository)
    version = repository.get_version(V1)
    assert version is not None
    assert (version.reason, version.rules_applied) == ("gap:c12", [])
    assert repository.list_edges(rule_pk("R-007")) == []
    assert verify_version_complete(V1, repository) is True


def test_a_plan_that_disagrees_with_its_version_id_is_rejected(
        seeded_feature: Repository) -> None:
    """`version_id` 與 `slug`／`number` 不自洽時立刻拒絕：S3 key 會指向別的版本。"""
    plan = VersionPlan(version_id=V1, slug=SLUG, number=2, supersedes=None,
                       reason="gap:c12", rules_applied=(), operation_id="op-test-broken")
    with pytest.raises(ContentError, match="不自洽"):
        create_version(plan, four_step_content(), seeded_feature)
    assert seeded_feature.get_version(V1) is None
    assert not seeded_feature.object_exists(markdown_key(SLUG, 2))


def test_the_same_plan_twice_does_not_add_a_version(published_v1: Repository) -> None:
    """§8 Boundary：同 plan 第二次呼叫不新增版本、不重建 VERSION item，仍然回完整的版本。"""
    repository = published_v1
    plan = version_plan(V2, **V2_PLAN)
    first = create_version(plan, four_step_content(), repository)
    revision = repository.revision_of(version_pk(V2))
    second = create_version(plan, four_step_content(), repository)
    assert second == first
    assert repository.revision_of(version_pk(V2)) == revision
    assert sorted(str(item["PK"]) for item in repository.scan_entity("VERSION")) == [
        version_pk(V1), version_pk(V2)]
