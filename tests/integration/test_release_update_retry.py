"""Phase 51 Task 3：同 `operation_id` 重送取回同一版號、模型輸出只算一次（O2）。

兩層各自標示，**不可互相冒充**（COMMON.md §2）：

- `test_moto_*`：跑在 moto（`tests/integration/conftest.py` 的 `repository`，region `us-west-2`）。
  綠燈只證明**資料形狀**：同一個子 operation 重送拿回同一個 `version_id`、模型輸出 ref 不會
  變成第二筆、未命中步驟逐 byte 相同。它**不是**真實併發或真實 S3 條件寫入的證據。
- `test_real_table_*`：標 `@pytest.mark.aws`，對真實 `training_kb` 表與 content bucket 跑，
  沒設 `TKB_RUN_AWS_INTEGRATION=1` 時由 `tests/conftest.py` 自動 skip。識別碼一律
  `demo-p51-<uuid>` 前綴，`finally` 會把自己建立的 item 與物件列出來再刪掉。

O5 BLOCKED（`docs/plan/report/o5-20260915T030245Z.md`）：`StepRewrite` 一律用假 writer，
本檔一次真實 Bedrock 呼叫都不會發生。O3 FAIL 不影響本檔：`prepare_update` 只產生
`published_at=None` 的私有版本，完全沒有發布路徑。
"""

import json
import os
import subprocess
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import boto3
import pytest

from training_kb.content import (
    StepDraft,
    TutorialContent,
    diff_key,
    markdown_key,
    render_markdown,
)
from training_kb.keys import operation_ref
from training_kb.models import Feature, Release, StepType, Tutorial, TutorialVersion
from training_kb.operations import AcceptOperation, OperationCoordinator
from training_kb.pipelines.release import StepHit, prepare_update
from training_kb.repository import Repository

NOW = datetime(2026, 9, 14, 9, 0, tzinfo=UTC)
PROJECT = "demo"
FEATURE = "Prepare"
OLD_STEP3 = "在右上角選擇 Meeting Summary，查看會前摘要。"
NEW_STEP3 = "在會議頁面右上角選擇 Prepare，查看會前摘要。"

TABLE_ENV = "TKB_TABLE_NAME"
BUCKET_ENV = "TKB_CONTENT_BUCKET"
REGION_ENV = "TKB_AWS_REGION"


class ScriptedWriter:
    """只會把第 3 步改成 `NEW_STEP3` 的假 writer；`attempts` 就是真的送出去幾次。"""

    def __init__(self) -> None:
        self.attempts = 0

    def embed(self, text: str, *, operation_id: str, node: str) -> list[float]:
        raise AssertionError("prepare_update 不呼叫 embedding")

    def generate_json(self, system: str, user: str, schema: Mapping[str, Any], *,
                      operation_id: str, node: str) -> dict[str, Any]:
        self.attempts += 1
        return {"steps": [{"number": 3, "text": NEW_STEP3, "feature_id": FEATURE,
                           "type": "click_ui"}]}

    def converse_with_tools(self, system: str, messages: Sequence[Mapping[str, Any]],
                            tools: Sequence[Mapping[str, Any]], *,
                            operation_id: str, node: str) -> dict[str, Any]:
        raise AssertionError("prepare_update 不呼叫 tool use")


def base_content(slug: str) -> TutorialContent:
    """四步的基底；只有第 3 步會被命中，第 1／2／4 步用來驗逐 byte 複製。"""
    return TutorialContent(
        title=f"{slug} 會前準備",
        problem="不知道怎麼在會議前拿到摘要。",
        prerequisites=["已登入"],
        steps=[
            StepDraft(number=1, type=StepType.CLICK_UI, text="在側欄點選會議。",
                      feature_id=FEATURE),
            StepDraft(number=2, type=StepType.CLICK_UI, text="在會議詳情頁確認參與者。",
                      feature_id=FEATURE),
            StepDraft(number=3, type=StepType.CLICK_UI, text=OLD_STEP3, feature_id=FEATURE),
            StepDraft(number=4, type=StepType.READ, text="回到會議列表確認摘要已更新。",
                      feature_id=FEATURE),
        ],
        expected_outcome="會前摘要已經可以在會議頁面看到。",
    )


def seed(repository: Repository, *, slug: str, feature_id: str,
         operation_id: str) -> list[tuple[str, str]]:
    """種一篇已發布的 `<slug>@v2` 與父 operation；回「我建立了哪些 item」給清理與報告用。"""
    repository.put_meta(Feature(feature_id=feature_id, name=feature_id, aliases=[],
                                first_seen=NOW))
    repository.put_meta(Tutorial(slug=slug, current_version=f"{slug}@v2", topic=slug,
                                 feature_ids=[feature_id], status="active",
                                 successor=None, cluster_id=None))
    repository.put_meta(TutorialVersion(version_id=f"{slug}@v2", slug=slug, supersedes=None,
                                        reason="create:seed", rules_applied=[],
                                        s3_key=markdown_key(slug, 2), published_at=NOW))
    repository.put_object(markdown_key(slug, 2),
                          render_markdown(base_content(slug)).encode("utf-8"),
                          "text/markdown; charset=utf-8", if_none_match=False)
    OperationCoordinator(repository).accept(
        AcceptOperation(operation_id=operation_id, kind="release-update",
                        canonical_id=slug, project_id=PROJECT, now=NOW))
    return [(f"FEATURE#{feature_id}", "META"), (f"TUTORIAL#{slug}", "META"),
            (f"VERSION#{slug}@v2", "META"), (f"OPS#{operation_id}", "META")]


def make_release(release_id: str) -> Release:
    return Release(id=release_id, source="github_pr", feature=FEATURE, kind="renamed",
                   old_name="Meeting Summary", new_name=FEATURE,
                   evidence="PR #42 rename Meeting Summary -> Prepare", ts=NOW)


# --- moto：資料形狀 ---------------------------------------------------------


@pytest.fixture
def seeded(repository: Repository) -> tuple[str, str, Release]:
    slug, operation_id = "prepare-meeting", "op-release-r_42"
    seed(repository, slug=slug, feature_id=FEATURE, operation_id=operation_id)
    return slug, operation_id, make_release("r_42")


def test_moto_resend_reuses_the_version_and_the_model_output(
        repository: Repository, seeded: tuple[str, str, Release]) -> None:
    """Given 同一個 `operation_id` 送了兩次，When 第二次跑 `prepare_update`，
    Then 拿回同一個 `version_id`、模型只被呼叫一次、`model_output_refs` 只有一筆（D26）。"""
    slug, operation_id, release = seeded
    writer = ScriptedWriter()
    operations = OperationCoordinator(repository)
    hits = (StepHit(slug, f"{slug}@v2", 3),)
    first = prepare_update(release, hits, repository=repository, writer=writer,
                           operations=operations, operation_id=operation_id)
    second = prepare_update(release, hits, repository=repository, writer=writer,
                            operations=operations, operation_id=operation_id)
    assert [plan.version_id for plan in first] == [f"{slug}@v3"]
    assert [plan.version_id for plan in second] == [plan.version_id for plan in first]
    assert writer.attempts == 1

    sub = operations.load(f"op-release-update-r_42--{slug}")
    assert sub is not None and sub.version_id == f"{slug}@v3"
    parent = operations.load(operation_id)
    assert parent is not None
    assert parent.version_id is None
    assert list(parent.model_output_refs) == [operation_ref(operation_id, f"rewrite-{slug}")]

    saved = repository.get_object(operation_ref(operation_id, f"rewrite-{slug}"))
    assert saved is not None
    assert json.loads(saved.decode("utf-8"))["steps"][0]["number"] == 3

    version = repository.get_version(f"{slug}@v3")
    assert version is not None
    assert version.published_at is None and version.reason == "release:r_42"


def test_moto_only_the_hit_step_differs_under_a_real_diff(
        repository: Repository, seeded: tuple[str, str, Release], tmp_path: Path) -> None:
    """人工驗收（可實證路徑）：把 v2.md 與 v3.md 兩份 bytes 落到本機檔，用 `diff` 逐行比較，
    親眼確認只有第 3 步不同——不是只看測試顯示 PASS。"""
    slug, operation_id, release = seeded
    prepare_update(release, (StepHit(slug, f"{slug}@v2", 3),), repository=repository,
                   writer=ScriptedWriter(), operations=OperationCoordinator(repository),
                   operation_id=operation_id)
    before, after = tmp_path / "v2.md", tmp_path / "v3.md"
    for path, key in ((before, markdown_key(slug, 2)), (after, markdown_key(slug, 3))):
        body = repository.get_object(key)
        assert body is not None
        path.write_bytes(body)
    result = subprocess.run(["diff", "-u", str(before), str(after)],
                            capture_output=True, text=True, check=False)
    assert result.returncode == 1, result.stdout
    changed = [line for line in result.stdout.splitlines()
               if line.startswith(("+", "-")) and not line.startswith(("+++", "---"))]
    assert changed == [f"-3. (type=click_ui, feature={FEATURE}) {OLD_STEP3}",
                       f"+3. (type=click_ui, feature={FEATURE}) {NEW_STEP3}"]
    stored = repository.get_object(diff_key(slug, 3))
    assert stored is not None and stored.decode("utf-8").splitlines()[2:] == \
        result.stdout.splitlines()[2:]


# --- 真實表：同一段資料形狀，但寫在正式 `training_kb` 上 ---------------------


@pytest.mark.aws
def test_real_table_resend_reuses_the_version() -> None:
    """實表重送：同一個 `operation_id` 兩次都拿回同一個 `version_id`（O2 PASS 的複驗）。

    識別碼一律 `demo-p51-<uuid>`；`finally` 會把自己建立的 item 與 S3 物件**列出來**再刪。
    刪除被 IAM 拒絕時不放寬權限，殘留清單原樣記進報告由人工處理。
    """
    region = os.environ.get(REGION_ENV, "us-east-1")
    table_name = os.environ.get(TABLE_ENV, "training_kb")
    bucket_name = os.environ.get(BUCKET_ENV)
    if not bucket_name:
        pytest.skip(f"需要 content bucket 名稱；設 {BUCKET_ENV}=<實際 bucket>")
    table = boto3.resource("dynamodb", region_name=region).Table(table_name)
    bucket = boto3.resource("s3", region_name=region).Bucket(bucket_name)
    repository = Repository(table, bucket)

    run_id = uuid4().hex[:8]
    slug = f"demo-p51-{run_id}"
    feature_id = f"demo-p51-feature-{run_id}"
    release_id = f"demo-p51-{run_id}"
    operation_id = f"op-release-{release_id}"
    created = seed(repository, slug=slug, feature_id=feature_id, operation_id=operation_id)
    objects = [markdown_key(slug, 2), operation_ref(operation_id, f"rewrite-{slug}")]
    try:
        writer = ScriptedWriter()
        operations = OperationCoordinator(repository)
        hits = (StepHit(slug, f"{slug}@v2", 3),)
        release = make_release(release_id)
        first = prepare_update(release, hits, repository=repository, writer=writer,
                               operations=operations, operation_id=operation_id)
        created += [(f"VERSION#{slug}@v3", "META"),
                    (f"OPS#op-release-update-{release_id}--{slug}", "META")]
        created += [(f"STEP#{slug}@v3#{number}", f"REFERENCES#FEATURE#{feature_id}")
                    for number in (1, 2, 3, 4)]
        created += [(f"VERSION#{slug}@v3", f"SUPERSEDES#VERSION#{slug}@v2")]
        objects += [markdown_key(slug, 3), diff_key(slug, 3)]
        second = prepare_update(release, hits, repository=repository, writer=writer,
                                operations=operations, operation_id=operation_id)
        assert [plan.version_id for plan in second] == [plan.version_id for plan in first]
        assert writer.attempts == 1
        version = repository.get_version(f"{slug}@v3")
        assert version is not None and version.published_at is None
        print("created items:", sorted(created))
        print("created objects:", sorted(objects))
    finally:
        for key in objects:
            bucket.Object(key).delete()
        for pk, sk in created:
            table.delete_item(Key={"PK": pk, "SK": sk})
