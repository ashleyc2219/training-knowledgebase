"""Demo 種子的載入、重算與寫入（Phase 56）。

三件事，分得很開：

1. `load_seed(directory)` 只做 **schema 與引用完整性**：十份 JSON 逐檔用 Phase 03／04 的
   `StrictModel` 解析（`extra="forbid"`，多一個欄位就爆），再核對彼此的引用。
2. `verify_recipe(bundle)` 只做 **重算**：八個目標數字一律由原始 Feedback／View／Ticket
   現算，**種子裡沒有預存這八個數字**。公式全部來自 `training_kb.analytics`
   （Phase 53 的 `average_rating`／`negative_feedback_ids`、Phase 54 的 `reopen_stats`），
   本檔**不得**出現第二份平均或十四天窗口。
3. `apply_seed(bundle, ...)` 只做 **寫入**：走 Phase 23 的 `create_version`，寫完逐版呼叫
   `verify_version_complete`。

**O7 的第三個條件是維護者核定，本檔沒有、也不得有任何賦值路徑。**
`approved_by`／`approved_at`／`seed_commit`／`recipe_report_sha256` 四個欄位只從
`demo/seed/approvals/<batch_id>.json` **讀出來**；程式唯一能做的是判斷它們是不是空的，
空的就列進 `RecipeReport.missing_approvals`，`o7_ready` 因此為 `False`。
自動填值等同造假（設計 §18 O7）。

整份種子都是**明示的合成資料**：每個檔案帶 `"synthetic": true` 與 `_notice`，
不含任何真人資料、帳號或金鑰。
"""

import json
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from math import isclose
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from training_kb.analytics.ratings import average_rating, negative_feedback_ids
from training_kb.analytics.reopen import reopen_stats
from training_kb.analytics.validation import SeedBatch
from training_kb.clock import parse_iso, to_iso
from training_kb.content import (
    VersionPlan,
    create_version,
    parse_version_id,
    validate_content,
    verify_version_complete,
)
from training_kb.errors import ContentError
from training_kb.ingress import DEFAULT_FEEDBACK_CATEGORIES
from training_kb.keys import (
    feature_pk,
    feedback_pk,
    release_pk,
    rule_pk,
    step_pk,
    ticket_pk,
    tutorial_pk,
    version_pk,
    view_pk,
)
from training_kb.models import (
    AuthoringRule,
    Feature,
    Feedback,
    Release,
    StepDraft,
    StrictModel,
    Ticket,
    Tutorial,
    TutorialContent,
    TutorialStep,
    TutorialVersion,
    TutorialView,
)
from training_kb.pipelines.ticket import assign_cluster, ensure_embedding
from training_kb.repository import Repository
from training_kb.writing.client import Writer

SYNTHETIC_NOTICE = (
    "合成資料示範（SYNTHETIC）：本檔由 docs/design/training-kb.md §11 的 Demo 配方展開，"
    "不是真實觀測、不是實測成效，也不含任何真人資料、帳號或金鑰。")
"""十份種子檔與兩份產物共用的檔頭聲明；改字只改這一處（設計 §11.5、§12.3）。"""

SEED_FILES: tuple[str, ...] = (
    "features.json", "tutorials.json", "versions.json", "steps.json", "releases.json",
    "feedback.json", "views.json", "tickets.json", "rules.json", "batches.json",
)
"""十份種子檔的固定順序；`seed_digest` 也照這個順序算雜湊，換順序會換出不同的值。"""

APPROVAL_DIR = "approvals"
HUMAN_FIELDS: tuple[str, ...] = (
    "approved_by", "approved_at", "seed_commit", "recipe_report_sha256")
"""四個**只能由維護者填寫**的欄位；本模組只讀不寫（Task 4 的 `rg` 守門就是查這件事）。"""

CREATION_TICKET_PREFIX = "t_10"
"""二十筆「建立教學用」工單的 ID 前綴；它們的 `cluster_id`／`embedding` 在種子中一律 `null`。"""

SEED_OPERATION_ID = "demo-seed-01"
BANNER = "合成資料示範"
O7_INCOMPLETE = "O7 = 未完成（缺維護者核定）"
O7_COMPLETE = "O7 = 三條件齊備"


@dataclass(frozen=True)
class SeedBundle:
    """一整份種子；`contents` 是每個版本的五段全文，與 `versions` 一一對應、同序。

    **`contents` 不在 Phase 文件 §5 的 Produces 草圖裡**（那份只列了九個實體與 `batches`），
    但五段內容是種子資料的一部分：Title／Problem／Prerequisites／Expected Outcome 存在
    `versions.json` 的 `content` 區塊、Steps 存在 `steps.json`，`load_seed` 把兩邊合成
    `TutorialContent` 供 `apply_seed` 寫 Markdown 全文。由程式生成這四段等於把資料藏進
    程式碼，配方就不再是「可由維護者逐檔核對」的了。
    """

    batch_label: str
    synthetic: bool
    features: tuple[Feature, ...]
    tutorials: tuple[Tutorial, ...]
    versions: tuple[TutorialVersion, ...]
    contents: tuple[TutorialContent, ...]
    steps: tuple[TutorialStep, ...]
    releases: tuple[Release, ...]
    feedback: tuple[Feedback, ...]
    views: tuple[TutorialView, ...]
    tickets: tuple[Ticket, ...]
    rules: tuple[AuthoringRule, ...]
    batches: tuple[SeedBatch, ...]


@dataclass(frozen=True)
class RecipeCheck:
    """一個目標數字的重算結果；`actual is None` 代表算不出來（缺前置資料），不是 0。"""

    name: str
    expected: float
    actual: float | None
    ok: bool


@dataclass(frozen=True)
class RecipeReport:
    """O7 的三個條件分開記錄；`o7_ready` 是三個布林的 `and`，不是任何一個的別名。"""

    checks: tuple[RecipeCheck, ...]
    schema_ok: bool
    recompute_ok: bool
    approved_batch_ids: tuple[str, ...]
    missing_approvals: tuple[str, ...]
    o7_ready: bool


# --- 1. 讀檔與 schema --------------------------------------------------------


def _read_file(directory: Path, name: str) -> tuple[str, bool, list[Any]]:
    """讀一份種子檔，回 `(batch_label, synthetic, items)`；缺欄位一律 `ContentError`。"""
    path = directory / name
    if not path.is_file():
        raise ContentError(f"缺少種子檔：{path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ContentError(f"種子檔不是合法 JSON：{name}：{error}") from error
    if not isinstance(payload, dict):
        raise ContentError(f"種子檔最外層必須是物件：{name}")
    items = payload.get("items")
    if not isinstance(items, list):
        raise ContentError(f"種子檔缺少 items 陣列：{name}")
    if payload.get("synthetic") is not True:
        raise ContentError(f"種子檔必須明示 synthetic: true：{name}")
    label = payload.get("batch_label")
    if not isinstance(label, str) or not label:
        raise ContentError(f"種子檔缺少 batch_label：{name}")
    return label, True, items


def _models[M: StrictModel](model: type[M], rows: Sequence[Any], name: str) -> tuple[M, ...]:
    """逐筆用 Phase 03／04 的模型解析；pydantic 的 `ValidationError` 一律轉 `ContentError`。

    不另寫寬鬆 parser：`extra="forbid"` 是種子資料的第一道關卡，多一個欄位就要爆。
    """
    parsed: list[M] = []
    for index, row in enumerate(rows):
        try:
            parsed.append(model.model_validate(row))
        except ValidationError as error:
            raise ContentError(
                f"{name} 第 {index + 1} 筆不符 {model.__name__}：{error.error_count()} 個欄位"
            ) from error
    return tuple(parsed)


def _contents(versions: Sequence[TutorialVersion], raw_versions: Sequence[Any],
              steps: Sequence[TutorialStep]) -> tuple[TutorialContent, ...]:
    """把 `versions.json` 的四段文字與 `steps.json` 的步驟合成 `TutorialContent`。"""
    by_version: dict[str, list[TutorialStep]] = {}
    for step in steps:
        by_version.setdefault(step.tutorial_version, []).append(step)
    contents: list[TutorialContent] = []
    for version, raw in zip(versions, raw_versions, strict=True):
        section = raw.get("content")
        if not isinstance(section, dict):
            raise ContentError(f"版本 {version.version_id} 缺少 content 區塊")
        rows = sorted(by_version.get(version.version_id, ()), key=lambda item: item.number)
        try:
            contents.append(TutorialContent(
                title=section.get("title", ""), problem=section.get("problem", ""),
                prerequisites=list(section.get("prerequisites", ())),
                expected_outcome=section.get("expected_outcome", ""),
                steps=[StepDraft(number=row.number, type=row.type, text=row.text,
                                 feature_id=row.feature_id) for row in rows]))
        except ValidationError as error:
            raise ContentError(
                f"版本 {version.version_id} 的五段內容不合法：{error.error_count()} 個欄位"
            ) from error
    return tuple(contents)


def _reference_problems(bundle: SeedBundle) -> list[str]:
    """十份檔案彼此的引用完整性；空 list 代表 schema 通過。

    `load_seed` 與 `verify_recipe` 共用同一份實作：前者把問題變成 `ContentError`，
    後者把「有沒有問題」變成 `RecipeReport.schema_ok`，兩邊不會各自長出一套規則。
    """
    features = {item.feature_id for item in bundle.features}
    slugs = {item.slug for item in bundle.tutorials}
    versions = {item.version_id for item in bundle.versions}
    feedback_ids = {item.id for item in bundle.feedback}
    rule_ids = {item.rule_id for item in bundle.rules}
    problems: list[str] = []

    for tutorial in bundle.tutorials:
        if tutorial.current_version is not None and tutorial.current_version not in versions:
            problems.append(f"教學 {tutorial.slug} 的 current_version 不存在")
        problems += [f"教學 {tutorial.slug} 引用不存在的 Feature：{fid}"
                     for fid in tutorial.feature_ids if fid not in features]
    seen: set[str] = set()
    for version in bundle.versions:
        if version.slug not in slugs:
            problems.append(f"版本 {version.version_id} 的 slug 不存在：{version.slug}")
        if version.supersedes is not None and version.supersedes not in seen:
            problems.append(f"版本 {version.version_id} 的 supersedes 必須排在它前面")
        problems += [f"版本 {version.version_id} 套用不存在的規則：{rid}"
                     for rid in version.rules_applied if rid not in rule_ids]
        seen.add(version.version_id)
    for version, content in zip(bundle.versions, bundle.contents, strict=True):
        try:
            validate_content(content, frozenset(features))
        except ContentError as error:
            problems.append(f"版本 {version.version_id}：{error}")
    problems += [f"步驟 {step.tutorial_version}#{step.number} 指向不存在的版本"
                 for step in bundle.steps if step.tutorial_version not in versions]
    problems += [f"回饋 {item.id} 指向不存在的版本：{item.tutorial_version}"
                 for item in bundle.feedback if item.tutorial_version not in versions]
    problems += [f"瀏覽紀錄指向不存在的版本：{item.tutorial_version}"
                 for item in bundle.views if item.tutorial_version not in versions]
    problems += [f"上游變更 {item.id} 指向不存在的 Feature：{item.feature}"
                 for item in bundle.releases if item.feature not in features]
    for rule in bundle.rules:
        problems += [f"規則 {rule.rule_id} 的證據不存在：{fid}"
                     for fid in rule.evidence if fid not in feedback_ids]
        problems += [f"規則 {rule.rule_id} 的 applied_to 指向不存在的版本：{vid}"
                     for vid in rule.applied_to if vid not in versions]
        if rule.derived_from not in versions:
            problems.append(f"規則 {rule.rule_id} 的 derived_from 不存在：{rule.derived_from}")
    problems += _batch_problems(bundle, versions, rule_ids, slugs)
    return problems


def _batch_problems(bundle: SeedBundle, versions: set[str], rule_ids: set[str],
                    slugs: set[str]) -> list[str]:
    """核定批次的欄位檢查與「兩批不重疊」（設計 §12.2）。

    共用任何一個 `version_id` 就只能算一批；不擋的話 `R-012` 會用同一份證據退役兩次。
    """
    problems: list[str] = []
    used: dict[str, str] = {}
    for batch in bundle.batches:
        if batch.rule_id not in rule_ids:
            problems.append(f"核定批次 {batch.batch_id} 指向不存在的規則：{batch.rule_id}")
        if batch.slug not in slugs:
            problems.append(f"核定批次 {batch.batch_id} 指向不存在的教學：{batch.slug}")
        for version_id in (batch.before_version_id, batch.after_version_id):
            if version_id not in versions:
                problems.append(f"核定批次 {batch.batch_id} 指向不存在的版本：{version_id}")
                continue
            owner = used.get(version_id)
            if owner is not None and owner != batch.batch_id:
                problems.append(
                    f"核定批次 {owner} 與 {batch.batch_id} 重疊：共用版本 {version_id}")
            used[version_id] = batch.batch_id
        if not batch.synthetic:
            problems.append(f"核定批次 {batch.batch_id} 必須明示 synthetic")
    return problems


def seed_digest(directory: Path) -> str:
    """十份種子檔內容的 SHA-256；維護者簽名時填進 `seed_commit`。

    只涵蓋 `SEED_FILES`，**不含** `approvals/`、`clustering_report.json` 與
    `recipe-report.txt`——那三者是簽名與產物，把它們算進去會讓簽名永遠對不上自己。
    """
    digest = sha256()
    for name in SEED_FILES:
        digest.update(name.encode("utf-8"))
        digest.update((directory / name).read_bytes())
    return digest.hexdigest()


def _approval(directory: Path, batch_id: str, digest: str) -> tuple[str | None, datetime | None]:
    """讀一份核定紀錄，回 `(approved_by, approved_at)`；**沒簽名就回 `(None, None)`**。

    四個維護者欄位任一為空、或 `seed_commit` 與目前種子的雜湊不符（種子改過、需重新
    核對），都視同未核定。本函式只讀不寫：`approved_by` 這個名字在整個 `demo/`／`src/`
    下只出現在讀取端。
    """
    path = directory / APPROVAL_DIR / f"{batch_id}.json"
    if not path.is_file():
        raise ContentError(f"核定批次 {batch_id} 缺少核定紀錄檔：{path}")
    record = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(record, dict):
        raise ContentError(f"核定紀錄最外層必須是物件：{path.name}")
    if record.get("batch_id") != batch_id:
        raise ContentError(f"核定紀錄的 batch_id 與檔名不符：{path.name}")
    if record.get("synthetic") is not True:
        raise ContentError(f"核定紀錄必須明示 synthetic: true：{path.name}")
    if not str(record.get("statement", "")).strip():
        raise ContentError(f"核定紀錄缺少 statement：{path.name}")
    values = [str(record.get(field, "")).strip() for field in HUMAN_FIELDS]
    if not all(values) or record.get("seed_commit") != digest:
        return None, None
    try:
        signed_at = parse_iso(str(record["approved_at"]))
    except ValueError as error:
        raise ContentError(f"核定紀錄的 approved_at 不是合法時間：{path.name}") from error
    return str(record["approved_by"]), signed_at


def load_seed(directory: Path) -> SeedBundle:
    """讀整份種子並驗證；任何 schema 或引用問題一律 `ContentError`，不回半套 bundle。

    固定順序：features -> tutorials -> versions -> steps -> releases -> feedback ->
    views -> tickets -> rules -> batches -> approvals。後面的檔案可以引用前面的 ID。
    """
    labels: set[str] = set()
    raw: dict[str, list[Any]] = {}
    for name in SEED_FILES:
        label, _, items = _read_file(directory, name)
        labels.add(label)
        raw[name] = items
    if len(labels) != 1:
        raise ContentError(f"十份種子檔的 batch_label 不一致：{sorted(labels)}")
    raw_versions = raw["versions.json"]
    versions = _models(TutorialVersion, [row.get("version") for row in raw_versions],
                       "versions.json")
    steps = _models(TutorialStep, raw["steps.json"], "steps.json")
    digest = seed_digest(directory)
    batches: list[SeedBatch] = []
    for row in raw["batches.json"]:
        if not isinstance(row, dict):
            raise ContentError("batches.json 的每一筆都必須是物件")
        missing = sorted({"batch_id", "rule_id", "slug", "before_version_id",
                          "after_version_id", "cluster_id", "project_id", "synthetic",
                          *HUMAN_FIELDS[:2]} - set(row))
        if missing:
            raise ContentError(f"batches.json 缺少欄位：{missing}")
        signed_by, signed_at = _approval(directory, str(row["batch_id"]), digest)
        batches.append(SeedBatch(
            batch_id=str(row["batch_id"]), rule_id=str(row["rule_id"]), slug=str(row["slug"]),
            before_version_id=str(row["before_version_id"]),
            after_version_id=str(row["after_version_id"]),
            cluster_id=str(row["cluster_id"]), project_id=str(row["project_id"]),
            synthetic=bool(row["synthetic"]), approved_by=signed_by, approved_at=signed_at))
    bundle = SeedBundle(
        batch_label=labels.pop(), synthetic=True,
        features=_models(Feature, raw["features.json"], "features.json"),
        tutorials=_models(Tutorial, raw["tutorials.json"], "tutorials.json"),
        versions=versions, contents=_contents(versions, raw_versions, steps), steps=steps,
        releases=_models(Release, raw["releases.json"], "releases.json"),
        feedback=_models(Feedback, raw["feedback.json"], "feedback.json"),
        views=_models(TutorialView, raw["views.json"], "views.json"),
        tickets=_models(Ticket, raw["tickets.json"], "tickets.json"),
        rules=_models(AuthoringRule, raw["rules.json"], "rules.json"),
        batches=tuple(batches))
    problems = _reference_problems(bundle)
    if problems:
        raise ContentError("種子資料引用不完整：" + "；".join(problems))
    return bundle


# --- 2. 重算 -----------------------------------------------------------------

TARGET_VERSIONS: tuple[tuple[str, str], ...] = (
    ("A v1", "prepare-meeting@v1"), ("A v2", "prepare-meeting@v2"))
"""八個目標數字只看 A 的兩版（設計 §11.2、§11.3）；weekly-digest 的四版是 R-012 的批次資料。"""

TARGET_METRICS: tuple[str, ...] = ("average", "negative count", "reopen count", "reopen rate")

RECIPE_TARGETS: Mapping[str, float] = {
    "A v1 average": 2.875, "A v2 average": 4.4,
    "A v1 negative count": 8, "A v2 negative count": 2,
    "A v1 reopen count": 7, "A v2 reopen count": 2,
    "A v1 reopen rate": 0.7, "A v2 reopen rate": 0.2,
}
"""設計 §11.2／§11.3 的期望值。**只有期望值寫在這裡，實際值一律從原始資料算出來。**"""


def _actuals(bundle: SeedBundle, version_id: str) -> dict[str, float | None]:
    """一個版本的四個實際值；公式全部來自 `training_kb.analytics`，本檔不自己算。"""
    version = next((row for row in bundle.versions if row.version_id == version_id), None)
    tutorial = None if version is None else next(
        (row for row in bundle.tutorials if row.slug == version.slug), None)
    feedback = [row for row in bundle.feedback if row.tutorial_version == version_id]
    views = [row for row in bundle.views if row.tutorial_version == version_id]
    values: dict[str, float | None] = {
        "average": average_rating(feedback),
        "negative count": len(negative_feedback_ids(feedback, DEFAULT_FEEDBACK_CATEGORIES)),
        "reopen count": None, "reopen rate": None,
    }
    if version is None or version.published_at is None or tutorial is None:
        return values
    if tutorial.cluster_id is None:
        return values
    stats = reopen_stats(views, bundle.tickets, cluster_id=tutorial.cluster_id,
                         published_at=version.published_at)
    values["reopen count"] = stats.count
    values["reopen rate"] = stats.rate
    return values


def _matches(expected: float, actual: float | None) -> bool:
    """實際值等於期望值；`None`（算不出來）一律不算通過。"""
    return actual is not None and isclose(actual, expected, rel_tol=0.0, abs_tol=1e-9)


def verify_recipe(bundle: SeedBundle) -> RecipeReport:
    """重算八個目標數字並彙整 O7 的三個條件。

    **不讀 DynamoDB、不呼叫模型、不碰檔案**：輸入只有 `bundle`，所以同一份種子永遠算出
    同一份報告。`o7_ready` 是 `schema_ok and recompute_ok and not missing_approvals`；
    `missing_approvals` 非空時它必須是 `False`，程式沒有別的路徑把它變成 `True`。
    """
    actuals = {label: _actuals(bundle, version_id) for label, version_id in TARGET_VERSIONS}
    checks = tuple(
        RecipeCheck(name=f"{label} {metric}", expected=RECIPE_TARGETS[f"{label} {metric}"],
                    actual=actuals[label][metric],
                    ok=_matches(RECIPE_TARGETS[f"{label} {metric}"], actuals[label][metric]))
        for metric in TARGET_METRICS for label, _ in TARGET_VERSIONS)
    schema_ok = not _reference_problems(bundle)
    recompute_ok = all(check.ok for check in checks)
    approved = tuple(batch.batch_id for batch in bundle.batches
                     if batch.approved_by and batch.approved_at is not None)
    missing = tuple(batch.batch_id for batch in bundle.batches
                    if not (batch.approved_by and batch.approved_at is not None))
    return RecipeReport(checks=checks, schema_ok=schema_ok, recompute_ok=recompute_ok,
                        approved_batch_ids=approved, missing_approvals=missing,
                        o7_ready=schema_ok and recompute_ok and not missing)


def _number(value: float | None) -> str:
    if value is None:
        return "n/a"
    return str(int(value)) if float(value).is_integer() else f"{value:g}"


def render_report(bundle: SeedBundle, report: RecipeReport) -> str:
    """`uv run python -m demo.seed_loader verify demo/seed` 的輸出（Phase 文件 §2）。

    最後一行只有兩種可能：`O7 = 未完成（缺維護者核定）` 或 `O7 = 三條件齊備`。
    **不得**出現「O7 已通過」這種結論式措辭（Phase 文件 §9）。
    """
    lines = [f"[{BANNER}] batch={bundle.batch_label} synthetic={str(bundle.synthetic).lower()}"]
    pairs = list(zip(report.checks[0::2], report.checks[1::2], strict=True))
    for left, right in pairs:
        lines.append(
            f"  {left.name:<19} expected {_number(left.expected):<6} "
            f"actual {_number(left.actual):<6} {'OK' if left.ok else 'FAIL'}  | "
            f"{right.name:<19} {_number(right.expected):<5} {_number(right.actual):<5} "
            f"{'OK' if right.ok else 'FAIL'}")
    approvals = ("PASS" if not report.missing_approvals
                 else f"MISSING({', '.join(report.missing_approvals)})")
    lines.append(f"schema={'PASS' if report.schema_ok else 'FAIL'}  "
                 f"recompute={'PASS' if report.recompute_ok else 'FAIL'}  "
                 f"approvals={approvals}")
    lines.append(O7_COMPLETE if report.o7_ready else O7_INCOMPLETE)
    return "\n".join(lines) + "\n"


# --- 3. 寫入 -----------------------------------------------------------------


def _write_version(version: TutorialVersion, content: TutorialContent, *,
                   repository: Repository) -> list[str]:
    """寫一個版本的全文、diff、VERSION item 與三種邊，寫完核對一次（Phase 23）。

    已經存在且內容相同、核對也通過時直接跳過：`apply_seed` 因此可以重跑。
    `published_at` 是**模擬**的歷史回放時間，`create_version` 永遠不寫它（D25），
    所以這裡用 Phase 06 的 compare-and-swap 補上，不繞過 `Repository`。
    """
    version_id = version.version_id
    existing = repository.get_version(version_id)
    if existing == version and verify_version_complete(version_id, repository):
        return []
    slug, number = parse_version_id(version_id)
    create_version(VersionPlan(version_id=version_id, slug=slug, number=number,
                               supersedes=version.supersedes, reason=version.reason,
                               rules_applied=tuple(version.rules_applied),
                               operation_id=SEED_OPERATION_ID), content, repository)
    pk = version_pk(version_id)
    if version.published_at is not None:
        repository.update_meta(pk, {"published_at": to_iso(version.published_at)},
                               expected_revision=repository.revision_of(pk))
    if not verify_version_complete(version_id, repository):
        raise ContentError(f"版本 {version_id} 寫入後核對不完整")
    return [pk, *(step_pk(version_id, step.number) for step in content.steps)]


def apply_seed(bundle: SeedBundle, *, repository: Repository, now: datetime) -> tuple[str, ...]:
    """把整份種子寫進 DynamoDB 與私有 S3 前綴；回傳這次實際寫入的 PK 清單。

    **一律 `create_only=False`，也就是覆寫**（修正波：final review C#2 要求寫明）：種子的
    主鍵是 `TUTORIAL#prepare-meeting`、`RULE#R-007`、`RULE#R-012`、`FEATURE#Prepare` 這些
    正式資料會用到的名字，所以同名的既有 item 會被合成資料蓋掉。呼叫端有義務先確認目標表
    ——`demo.cli seed` 因此要 `--apply`、會先印出解析到的 table／bucket，並在
    `TKB_ENV=prod` 時拒絕。

    `now` 是載入時間：模擬 `published_at` 只用於歷史回放（設計 §11.5），晚於載入時間的
    版本一律拒絕，避免把合成的未來時間當成真實發布。

    寫入順序固定，後面的實體可以引用前面的：Feature -> Tutorial -> 版本（全文／diff／
    VERSION／邊，逐版 `verify_version_complete`）-> Release -> Feedback -> View ->
    Ticket -> Rule。**item 上只寫模型欄位**（D-40）：`synthetic`、`batch_label`
    只留在 JSON 檔與報告裡，不進 DynamoDB item。
    """
    future = [row.version_id for row in bundle.versions
              if row.published_at is not None and row.published_at > now]
    if future:
        raise ContentError(f"模擬發布時間晚於載入時間，不可回放：{'、'.join(future)}")
    written: list[str] = []
    for feature in bundle.features:
        repository.put_meta(feature, create_only=False)
        written.append(feature_pk(feature.feature_id))
    for tutorial in bundle.tutorials:
        repository.put_meta(tutorial, create_only=False)
        written.append(tutorial_pk(tutorial.slug))
    for version, content in zip(bundle.versions, bundle.contents, strict=True):
        written += _write_version(version, content, repository=repository)
    for release in bundle.releases:
        repository.put_meta(release, create_only=False)
        written.append(release_pk(release.id))
    for item in bundle.feedback:
        repository.put_meta(item, create_only=False)
        # 與 `ingress._complete_feedback` 同一條邊：`list_feedback_of_version` 只看
        # `FEEDBACK#<id> --REFERS_TO--> VERSION#<version_id>`，少了它指標就掃不到回饋。
        repository.put_edge(feedback_pk(item.id), "REFERS_TO",
                            version_pk(item.tutorial_version))
        written.append(feedback_pk(item.id))
    for view in bundle.views:
        repository.put_meta(view, create_only=False)
        written.append(view_pk(view.tutorial_version, view.user, view.ts))
    for ticket in bundle.tickets:
        repository.put_meta(ticket, create_only=False)
        written.append(ticket_pk(ticket.id))
    for rule in bundle.rules:
        repository.put_meta(rule, create_only=False)
        written.append(rule_pk(rule.rule_id))
    return tuple(written)


# --- 4. 二十筆工單的真實 embedding 分群 --------------------------------------


def creation_tickets(bundle: SeedBundle) -> tuple[Ticket, ...]:
    """二十筆「建立教學用」工單；它們的 `cluster_id` 必須由真實 embedding 決定。"""
    return tuple(row for row in bundle.tickets if row.id.startswith(CREATION_TICKET_PREFIX))


def cluster_demo_tickets(bundle: SeedBundle, *, writer: Writer, repository: Repository,
                         operation_id: str) -> dict[str, str]:
    """逐筆 `ensure_embedding` -> `assign_cluster`，回 `{ticket_id: cluster_id}`。

    **這支函式會寫 DynamoDB**（修正波：final review C#2 要求寫明）：每一筆都做一次
    `repository.put_meta(..., create_only=False)`，把 embedding 與 `cluster_id` 覆寫回
    `TICKET#<id>`。`repository` 指到哪張表由呼叫端決定；唯一的正式呼叫端
    `demo/scripts/cluster_demo_tickets.py` 用 `load_settings()` 解析，所以要 `--write`
    才會跑（`TKB_ENV=prod` 一律拒絕）。

    分群邏輯完全沿用 Phase 38（cosine >= 0.85 取最高、同分 `cluster_id` 升序、無命中開新群），
    本檔**不另寫一套**。每一筆算完就寫回 `cluster_id`，下一筆才比得到前面已成形的群中心。

    **沒有「模型不可用就預填」的分支。** Bedrock 回錯時 `Writer.embed` 丟的
    `PermanentError`／`TransientError` 原樣往上拋，由呼叫端記成 BLOCKED（O5）。
    """
    assigned: dict[str, str] = {}
    for ticket in creation_tickets(bundle):
        embedded = ensure_embedding(ticket, writer=writer, repository=repository,
                                    operation_id=operation_id)
        cluster_id = assign_cluster(embedded, repository=repository)
        repository.put_meta(embedded.model_copy(update={"cluster_id": cluster_id}),
                            create_only=False)
        assigned[ticket.id] = cluster_id
    return assigned


# --- 5. CLI ------------------------------------------------------------------


def main(argv: Sequence[str]) -> int:
    """`python -m demo.seed_loader verify <種子目錄>`：印出重算報告並回傳退出碼。

    **退出碼不是 O7 的判斷依據**：`0` 只代表 schema 與重算都通過，維護者核定仍然缺席時
    最後一行照樣是「O7 = 未完成（缺維護者核定）」。
    """
    if len(argv) != 2 or argv[0] != "verify":
        print("用法：python -m demo.seed_loader verify <種子目錄>", file=sys.stderr)
        return 2
    bundle = load_seed(Path(argv[1]))
    report = verify_recipe(bundle)
    print(render_report(bundle, report), end="")
    return 0 if report.schema_ok and report.recompute_ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
