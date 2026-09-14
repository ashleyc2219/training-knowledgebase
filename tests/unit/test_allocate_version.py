"""版號分配：ID 編碼、以已發布版本為基底、跳過永久失敗的號碼、同 operation 重送重用。

整個檔案不碰 AWS：`FakeRepository` 與 `FakeOperations` 是本檔自用的記憶體替身，只實作
`allocate_version` 真的會呼叫的那幾個讀寫（00A §6.6 Consumes）。替身的綠燈**不是** O2 證據，
跨程序重送的驗證在 `tests/integration/test_allocate_version_retry.py`，而真實 DynamoDB 上的
接受順序仍待 Phase 11。
"""

from types import SimpleNamespace

import pytest

from training_kb.content import allocate_version, make_version_id, parse_version_id
from training_kb.errors import ContentError, CoordinationError
from training_kb.models import Tutorial, TutorialStatus, TutorialVersion


class FakeRepository:
    """記憶體版 Repository，只實作本 Phase 用到的兩個讀取。"""

    def __init__(self) -> None:
        self.tutorials: dict[str, Tutorial] = {}
        self.versions: dict[str, TutorialVersion] = {}

    def put_tutorial(self, slug: str, *, current_version: str | None) -> None:
        self.tutorials[slug] = Tutorial(
            slug=slug, current_version=current_version, topic="準備會議",
            feature_ids=["Prepare"], status=TutorialStatus.ACTIVE, successor=None,
            cluster_id="c12")

    def put_unpublished_version(self, version_id: str, *, supersedes: str | None = None,
                                reason: str = "gap:c12",
                                rules_applied: tuple[str, ...] = ()) -> None:
        """模擬 Phase 23 已經把某個 `VersionPlan` 寫成 VERSION item（`published_at=None`）。"""
        slug, number = parse_version_id(version_id)
        self.versions[version_id] = TutorialVersion(
            version_id=version_id, slug=slug, supersedes=supersedes, reason=reason,
            rules_applied=list(rules_applied), s3_key=f"tutorials/{slug}/v{number}.md",
            published_at=None)

    def get_tutorial(self, slug: str) -> Tutorial | None:
        return self.tutorials.get(slug)

    def get_version(self, version_id: str) -> TutorialVersion | None:
        return self.versions.get(version_id)


class FakeOperations:
    """記憶體版 OperationCoordinator，只保存 `version_id` 與寫入次數。"""

    def __init__(self) -> None:
        self.records: dict[str, str | None] = {}
        self.writes: list[tuple[str, str]] = []

    def accepted(self, operation_id: str) -> None:
        self.records[operation_id] = None

    def load(self, operation_id: str) -> SimpleNamespace | None:
        if operation_id not in self.records:
            return None
        return SimpleNamespace(operation_id=operation_id, version_id=self.records[operation_id])

    def record_version(self, operation_id: str, version_id: str) -> None:
        self.records[operation_id] = version_id
        self.writes.append((operation_id, version_id))


@pytest.fixture
def fake_repo() -> FakeRepository:
    return FakeRepository()


@pytest.fixture
def fake_ops() -> FakeOperations:
    return FakeOperations()


def test_version_id_round_trip() -> None:
    assert make_version_id("prepare-meeting", 2) == "prepare-meeting@v2"
    assert parse_version_id("prepare-meeting@v2") == ("prepare-meeting", 2)


@pytest.mark.parametrize("value", ["a@v0", "a@v01", "@v2", "a@vx", "prepare-meeting"])
def test_parse_version_id_rejects_bad_values(value: str) -> None:
    with pytest.raises(ValueError):
        parse_version_id(value)


def test_first_version_starts_at_v1(fake_repo: FakeRepository, fake_ops: FakeOperations) -> None:
    fake_repo.put_tutorial("prepare-meeting", current_version=None)
    fake_ops.accepted("op-gap-c12")
    plan = allocate_version("prepare-meeting", "op-gap-c12", fake_ops,
                            repository=fake_repo, reason="gap:c12", rules_applied=[])
    assert (plan.version_id, plan.number, plan.supersedes) == ("prepare-meeting@v1", 1, None)


def test_next_version_follows_current_published(fake_repo: FakeRepository,
                                                fake_ops: FakeOperations) -> None:
    fake_repo.put_tutorial("prepare-meeting", current_version="prepare-meeting@v2")
    fake_ops.accepted("op-release-r_42")
    plan = allocate_version("prepare-meeting", "op-release-r_42", fake_ops,
                            repository=fake_repo, reason="release:r_42", rules_applied=["R-007"])
    assert (plan.version_id, plan.number) == ("prepare-meeting@v3", 3)
    assert (plan.supersedes, plan.rules_applied) == ("prepare-meeting@v2", ("R-007",))


def test_permanently_failed_number_is_skipped(fake_repo: FakeRepository,
                                              fake_ops: FakeOperations) -> None:
    """v2 是上一次永久失敗留下的未發布版本：新操作拿 v3，基底仍是已發布的 v1（D26）。"""
    fake_repo.put_tutorial("prepare-meeting", current_version="prepare-meeting@v1")
    fake_repo.put_unpublished_version("prepare-meeting@v2")
    fake_ops.accepted("op-release-r_42")
    plan = allocate_version("prepare-meeting", "op-release-r_42", fake_ops,
                            repository=fake_repo, reason="release:r_42", rules_applied=["R-007"])
    assert (plan.version_id, plan.supersedes) == ("prepare-meeting@v3", "prepare-meeting@v1")


@pytest.mark.parametrize("current, recorded, operation_id, reason, error", [
    (None, None, "op-gap-c99", "gap:c99", CoordinationError),               # 沒有被 O2 接受
    (None, None, "op-gap-c12", "   ", ContentError),                        # reason 空白
    ("share-summary@v1", None, "op-gap-c12", "gap:c12", ContentError),      # current_version 是別篇
    (None, "share-summary@v9", "op-gap-c12", "gap:c12", CoordinationError), # 紀錄版號是別篇
])
def test_allocate_version_rejects_bad_input(fake_repo: FakeRepository, fake_ops: FakeOperations,
                                            current: str | None, recorded: str | None,
                                            operation_id: str, reason: str,
                                            error: type[Exception]) -> None:
    """四種失敗都在 `record_version` 之前就丟出來，不留半筆版號紀錄。"""
    fake_repo.put_tutorial("prepare-meeting", current_version=current)
    fake_ops.accepted("op-gap-c12")
    if recorded:
        fake_ops.record_version("op-gap-c12", recorded)
        fake_ops.writes.clear()
    with pytest.raises(error):
        allocate_version("prepare-meeting", operation_id, fake_ops,
                         repository=fake_repo, reason=reason, rules_applied=[])
    assert fake_ops.writes == []
