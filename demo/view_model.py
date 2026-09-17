"""Demo Dashboard 的四區 view model（Phase 58 Task 3／4）——**純計算，不畫任何東西**。

分工（00A §3.2 的 `demo/` 表）：本檔算好一個 dict 給任何呈現層用。原本的 Streamlit 畫面
`demo/dashboard.py` 已於 2026-09-17 移除（Demo 只需要公開站與命令列），本檔仍是四區指標的
唯一計算入口，`tests/unit/test_demo_view_model.py` 守住公式只有一份。

**指標公式一份都不在這裡。** 平均、負面回饋、重開票窗口與呼叫數全部轉呼
`training_kb.analytics`（Phase 53／54）；本檔只做「挑哪些版本、怎麼排、缺值寫什麼字」。
守門：`tests/unit/test_demo_view_model.py`
會掃過整個 `demo/`，找到十四天窗口或自己算平均的樣式就紅燈。

四個區塊與來源固定如下，其他欄位不加（設計 §13）：

```text
  區塊                       來源                                顯示規則
  -------------------------  ----------------------------------  ------------------------
  1 最新教學與版本差異        current_published_versions + 私有    顯示 reason 與完整 diff；
                             tutorials/<slug>/v<n>.diff           即時與模擬分成兩個 key
  2 每版評分與回饋數          version_metrics（P54）               無評分寫「尚無評分」
  3 重開票筆數與分子／分母    version_metrics(...).reopen（P54）   分母 0 寫 N/A 與樣本不足
  4 規則狀態與來源證據        list_rules + rule_counts/applied_    candidate 不寫成已有效
                             count（P54）
```

**時間分兩張表（設計 §11.5）**：`time_mode="simulated"` 的模擬歷史（種子回放的
`published_at`）與 `time_mode="live"` 的現場執行結果分別放在 `TIME_KEYS` 兩個 key 裡，
view model **不提供把兩者相加的欄位**——合成的歷史成效與現場這一次不是同一組使用者。

**gate 措辭固定**：`o7_ready` 為假時只能寫「待維護者核定」，**不得**出現「O7 已通過」或
「雲端驗收已通過」；O5 BLOCKED 時橫幅用 `Banner.fallback_reason` 明寫「目前顯示預先執行
結果」與本次現場失敗原因，**不得**把預先產好的檔案說成本次成功。
"""

import json
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from demo.seed_loader import O7_COMPLETE, O7_INCOMPLETE, SeedBundle, load_seed, verify_recipe
from training_kb.analytics.ratings import format_average
from training_kb.analytics.rules_metrics import applied_count, bedrock_call_count, rule_counts
from training_kb.analytics.version import version_metrics
from training_kb.content import diff_key, make_diff, markdown_key, parse_version_id, render_markdown
from training_kb.keys import tutorial_pk
from training_kb.models import (
    AuthoringRule,
    Feedback,
    RuleStatus,
    Ticket,
    Tutorial,
    TutorialVersion,
    TutorialView,
)
from training_kb.pipelines.feedback import current_published_versions
from training_kb.repository import Repository
from training_kb.writing.client import CallTrace

DASHBOARD_BLOCKS: tuple[str, ...] = (
    "最新教學與版本差異", "每版評分與回饋數", "重開票筆數與分子分母", "規則狀態與來源證據")
"""`dashboard_view` 的四個 key，順序固定（Phase 58 §5）。呈現層照這個順序畫。"""

SYNTHETIC_NOTICE = "合成資料示範"
"""橫幅與每一列數字的合成資料標示；與 `demo/seed_loader.py:BANNER` **逐字相同**（R11）。
兩支檔各自宣告自己的名字（00A §3.2 不得互搬），相等由
`tests/unit/test_demo_view_model.py::test_synthetic_notice_matches_the_seed_loader_banner` 守。"""

TIME_KEYS: tuple[str, str] = ("simulated_history", "live_run")
"""區塊 1 的兩張表：模擬歷史回放／本次現場執行。**不得**再加一個把兩者相加的 key。"""

TIME_LABELS: dict[str, str] = {"live": "即時執行", "simulated": "模擬時間"}

GATE_NOTE = "O5 模型未開通（BLOCKED）｜O7 待維護者核定"
"""橫幅固定帶的 gate 現況；畫面不假裝一切正常（COMMON.md §2）。"""

PENDING_APPROVAL = "待維護者核定"
FALLBACK_NOTE = "目前顯示預先執行結果；本次現場失敗原因"

NO_RATING = "尚無評分"
NO_SAMPLE = "N/A：樣本不足"
REOPEN_NOTE = ("rate 是 proxy：窗口內先瀏覽後同群開票的不同使用者數／窗口內不同瀏覽者數，"
               "不是直接量測的教學成效；窗口端點待維護者核定（O4）。7 與 2 是筆數，不是百分比")
CANDIDATE_NOTE = "candidate：尚未生效，還沒有被注入正式教學"
ACTIVE_NOTE = "active：已通過驗證，寫作時會被注入"
RETIRED_NOTE = "retired：已退役，不再注入"
STATUS_NOTES: dict[str, str] = {"candidate": CANDIDATE_NOTE, "active": ACTIVE_NOTE,
                                "retired": RETIRED_NOTE}

NO_DIFF_NOTE = "（本機種子沒有前一版可比較）"


# --- 1. 橫幅與呼叫數 ---------------------------------------------------------


@dataclass(frozen=True)
class Banner:
    """畫面最上方那一條；`fallback_reason` 非空代表現在看到的不是本次現場跑出來的結果。"""

    batch: str
    time_mode: Literal["live", "simulated"]
    fallback_reason: str | None


def render_banner(banner: Banner) -> str:
    """固定輸出「【合成資料示範】｜批次：…｜時間標示：…｜gate：…」。

    `fallback_reason` 非空時追加「｜目前顯示預先執行結果；本次現場失敗原因：<reason>」——
    設計 §11.5 要求備援結果必須標示，**不能說成本次成功**。
    """
    text = (f"【{SYNTHETIC_NOTICE}】｜批次：{banner.batch}"
            f"｜時間標示：{TIME_LABELS[banner.time_mode]}｜gate：{GATE_NOTE}")
    if banner.fallback_reason:
        text += f"｜{FALLBACK_NOTE}：{banner.fallback_reason}"
    return text


@dataclass(frozen=True)
class CallBreakdown:
    """一次執行的真實 request attempt 統計；`by_node` 依節點名升序，方便逐格對照。"""

    total: int
    retries: int
    by_node: tuple[tuple[str, int], ...]


def call_breakdown(trace: CallTrace) -> CallBreakdown:
    """`total` 轉呼 Phase 54 的 `bedrock_call_count`；逐筆用 `trace.to_json()` 讀（Phase 15）。

    `retries` 是 `attempt >= 2` 的紀錄筆數。含 embedding、Rote 的 `tool_use` 與 Map 的每個
    item——**實際幾次就顯示幾次**，不為了對齊展示表格刪掉任何一種（設計 §12.3）。
    記憶體重用沒有送出 request，所以本來就不在 trace 裡。
    """
    records: list[dict[str, Any]] = json.loads(trace.to_json())
    counts = Counter(str(row["node"]) for row in records)
    return CallBreakdown(
        total=bedrock_call_count(trace),
        retries=sum(1 for row in records if int(row["attempt"]) >= 2),
        by_node=tuple(sorted(counts.items())))


# --- 2. 把種子包成唯讀 Repository 形狀 ----------------------------------------


class SeedRepository:
    """`SeedBundle` -> `dashboard_view` 需要的唯讀 Repository 形狀（**沒有任何寫入方法**）。

    P56 §7.2 第 4 條：「dashboard 不需要真實表，`load_seed` ＋ `verify_recipe` 就拿得到全部
    數字」。這個類別把那句話落成程式：不連 AWS、不需要 moto，所以 Demo 控制台在**離線**的
    維護者筆電上也畫得出來，而且指標仍然是由 Phase 53／54 從原始 Feedback／View／Ticket
    **現算**的（`version_metrics` 讀的就是下面這幾個方法）。

    要看**真實表**時改成傳一個真的 `Repository` 進 `dashboard_view` 即可——它只吃介面，
    不吃這個類別。Dashboard 這一側永遠是唯讀：本類別根本沒有 `put_*`／`update_*`。
    """

    def __init__(self, bundle: SeedBundle) -> None:
        self._bundle = bundle
        self._contents = {version.version_id: content
                          for version, content in zip(bundle.versions, bundle.contents,
                                                      strict=False)}

    # --- 掃描與單筆讀取 ---

    def scan_entity(self, entity: str, *, consistent: bool = True,
                    meta_only: bool = True) -> list[dict[str, Any]]:
        """只支援 `TUTORIAL`（`current_published_versions` 用的那一個）。

        回的是 raw item 形狀（帶 `PK`／`SK`／`entity`），呼叫端才能照既有慣例走
        `item_to_model`；其餘 entity 回空清單而不是丟例外——本類別是**取數用的窄視圖**，
        不是 `Repository` 的替代品。
        """
        if entity != "TUTORIAL":
            return []
        return [{**row.model_dump(mode="json"), "PK": tutorial_pk(row.slug), "SK": "META",
                 "entity": "TUTORIAL"} for row in self._bundle.tutorials]

    def get_tutorial(self, slug: str) -> Tutorial | None:
        return next((row for row in self._bundle.tutorials if row.slug == slug), None)

    def get_version(self, version_id: str) -> TutorialVersion | None:
        return next((row for row in self._bundle.versions if row.version_id == version_id), None)

    def list_versions_of_tutorial(self, slug: str) -> list[TutorialVersion]:
        chosen = [row for row in self._bundle.versions if row.slug == slug]
        return sorted(chosen, key=lambda row: parse_version_id(row.version_id))

    def list_feedback_of_version(self, version_id: str) -> list[Feedback]:
        return sorted((row for row in self._bundle.feedback
                       if row.tutorial_version == version_id), key=lambda row: row.id)

    def list_views_of_version(self, version_id: str) -> list[TutorialView]:
        return sorted((row for row in self._bundle.views if row.tutorial_version == version_id),
                      key=lambda row: (row.ts, row.user))

    def list_tickets(self, project_id: str) -> list[Ticket]:
        return sorted((row for row in self._bundle.tickets if row.project_id == project_id),
                      key=lambda row: row.id)

    def list_rules(self, status: RuleStatus | None = None) -> list[AuthoringRule]:
        rules = sorted(self._bundle.rules, key=lambda row: row.rule_id)
        return rules if status is None else [row for row in rules if row.status == status]

    def get_object(self, key: str) -> bytes | None:
        """私有產物的離線版：全文與 diff 由 Phase 22／23 的**同一組函式**現算，不另寫一份。

        真實表上這兩個 key 是 `create_version` 寫進 S3 的；本地種子沒有 S3，所以這裡用
        `render_markdown` 與 `make_diff` 重算出**逐字相同**的內容。
        """
        for version in self._bundle.versions:
            slug, number = parse_version_id(version.version_id)
            content = self._contents.get(version.version_id)
            if content is None:
                continue
            if key == markdown_key(slug, number):
                return render_markdown(content).encode("utf-8")
            if key == diff_key(slug, number):
                return self._diff(version, content).encode("utf-8")
        return None

    def _diff(self, version: TutorialVersion, content: Any) -> str:
        previous = None if version.supersedes is None else self._contents.get(version.supersedes)
        if version.supersedes is None or previous is None:
            return make_diff(None, render_markdown(content), previous_name="",
                             current_name=version.s3_key)
        earlier = self.get_version(version.supersedes)
        return make_diff(render_markdown(previous), render_markdown(content),
                         previous_name="" if earlier is None else earlier.s3_key,
                         current_name=version.s3_key)


# --- 3. 四個區塊 -------------------------------------------------------------


def _notice(batch: str) -> str:
    return f"{SYNTHETIC_NOTICE}｜批次：{batch}"


def _all_versions(repository: Any) -> list[TutorialVersion]:
    """每一篇 active 教學的**全部**版本，依版本 ID 排序；區塊 2／3／4 共用同一份清單。"""
    found: dict[str, TutorialVersion] = {}
    for tutorial, _ in current_published_versions(repository):
        for version in repository.list_versions_of_tutorial(tutorial.slug):
            found[version.version_id] = version
    return sorted(found.values(), key=lambda row: parse_version_id(row.version_id))


def _block_versions(repository: Any, versions: Sequence[TutorialVersion],
                    batch: str) -> dict[str, dict[str, Any]]:
    """區塊 1：最新教學與版本差異；模擬歷史與現場執行分成 `TIME_KEYS` 兩張表。"""
    history: dict[str, Any] = {}
    for tutorial, current in current_published_versions(repository):
        slug, number = parse_version_id(current.version_id)
        body = repository.get_object(diff_key(slug, number))
        diff = None if body is None else body.decode("utf-8")
        history[tutorial.slug] = {
            "version_id": current.version_id, "reason": current.reason,
            "rules_applied": list(current.rules_applied),
            "published_at": current.published_at.isoformat() if current.published_at else None,
            "diff": diff or NO_DIFF_NOTE, "notice": _notice(batch)}
    live = {version.version_id: {
        "version_id": version.version_id, "reason": version.reason,
        "rules_applied": list(version.rules_applied), "published_at": None,
        "notice": _notice(batch)}
        for version in versions if version.published_at is None}
    return {TIME_KEYS[0]: history, TIME_KEYS[1]: live}


def _block_ratings(metrics: dict[str, Any], batch: str) -> dict[str, dict[str, Any]]:
    """區塊 2：每版評分與回饋數。`average` 是**未四捨五入**的值，`display` 才是畫面值。"""
    return {version_id: {
        "average": item.average, "display": format_average(item.average),
        "sample_size": item.sample_size, "negative": len(item.negative_ids),
        "note": NO_RATING if item.average is None else "",
        "notice": _notice(batch)} for version_id, item in metrics.items()}


def _block_reopen(metrics: dict[str, Any], batch: str) -> dict[str, dict[str, Any]]:
    """區塊 3：重開票筆數與分子／分母。

    `count`／`numerator`／`denominator`／`rate` 全部原樣取自 Phase 54 的 `ReopenStats`；
    `rate is None`（零分母）一律寫「N/A：樣本不足」，**不顯示 0%**。
    """
    rows: dict[str, dict[str, Any]] = {}
    for version_id, item in metrics.items():
        stats = item.reopen
        note = REOPEN_NOTE if stats.rate is not None else f"{NO_SAMPLE}｜{REOPEN_NOTE}"
        rows[version_id] = {"count": stats.count, "numerator": stats.reopen_users,
                            "denominator": stats.viewers, "rate": stats.rate,
                            "note": note, "notice": _notice(batch)}
    return rows


def _block_rules(repository: Any, versions: Sequence[TutorialVersion],
                 batch: str) -> dict[str, Any]:
    """區塊 4：規則狀態與來源證據；candidate 與 active 分開計數，candidate 不寫成已有效。"""
    rules = repository.list_rules()
    rows = [{"rule_id": rule.rule_id, "rule": rule.rule,
             "applies_when": str(rule.applies_when), "status": str(rule.status),
             "status_note": STATUS_NOTES[str(rule.status)],
             "evidence": list(rule.evidence), "derived_from": rule.derived_from,
             "applied_count": applied_count(versions, rule.rule_id),
             "notice": _notice(batch)} for rule in rules]
    return {"notice": _notice(batch), "counts": rule_counts(rules), "rules": rows}


def dashboard_view(*, repository: Repository | Any, approved: frozenset[str],
                   project_id: str, batch: str) -> dict[str, Any]:
    """四個區塊的完整 view model；key 逐字是 `DASHBOARD_BLOCKS`。

    `approved` 是 Phase 43 的**回饋類別核定表**，一律由呼叫端傳進來——本檔一個字都不寫
    類別清單。所有數字都由 `version_metrics`（Phase 54，內含 Phase 53 的平均與負面回饋、
    Phase 54 的十四天窗口）現算，本函式沒有第二份公式。
    """
    versions = _all_versions(repository)
    metrics = {version.version_id: version_metrics(version.version_id, repository=repository,
                                                   approved=approved, project_id=project_id)
               for version in versions}
    return {DASHBOARD_BLOCKS[0]: _block_versions(repository, versions, batch),
            DASHBOARD_BLOCKS[1]: _block_ratings(metrics, batch),
            DASHBOARD_BLOCKS[2]: _block_reopen(metrics, batch),
            DASHBOARD_BLOCKS[3]: _block_rules(repository, versions, batch)}


# --- 4. Dashboard 的唯一入口（呈現層只呼叫這個）--------------------------------


@dataclass(frozen=True)
class Dashboard:
    """呈現層要畫的全部東西；呈現層不再做任何計算。"""

    banner: Banner
    blocks: dict[str, Any]
    o7_line: str
    missing_approvals: tuple[str, ...]
    calls: CallBreakdown


DEFAULT_SEED_DIR = Path("demo/seed")
DEFAULT_APPROVED: frozenset[str] = frozenset()
"""預設不傳核定類別表：`negative_ids` 因此是空集合，畫面上就是「沒有已核定的負面類別」。
真值由呼叫端（Phase 43 的 `approved_categories`）傳進來，本檔**不寫死類別清單**。"""


def load_dashboard(directory: Path | str = DEFAULT_SEED_DIR, *,
                   approved: Iterable[str] | None = None,
                   fallback_reason: str | None = None,
                   trace: CallTrace | None = None) -> Dashboard:
    """讀本機種子 -> 組唯讀視圖 -> 算四個區塊。**本檔唯一會碰檔案系統的函式。**

    預設資料來源是**本機的 `demo/seed`**（離線、不連 AWS，P56 §7.2 第 4 條）；要看真實表的
    人改呼叫 `dashboard_view(repository=Repository(...), ...)`，Dashboard 那一側仍是唯讀。

    `o7_line` 只有兩種可能（`demo/seed_loader.py` 的兩個常數），而且未核定時一定帶
    「待維護者核定」——**程式重算成功不等於維護者核定**（設計 §18 O7）。
    """
    bundle = load_seed(Path(directory))
    report = verify_recipe(bundle)
    repository = SeedRepository(bundle)
    blocks = dashboard_view(
        repository=repository,
        approved=frozenset(DEFAULT_APPROVED if approved is None else approved),
        project_id=bundle.batches[0].project_id if bundle.batches else "demo",
        batch=bundle.batch_label)
    o7_line = (f"{O7_COMPLETE}" if report.o7_ready
               else f"{O7_INCOMPLETE}｜{PENDING_APPROVAL}："
                    f"{', '.join(report.missing_approvals)}")
    return Dashboard(
        banner=Banner(batch=bundle.batch_label, time_mode="simulated",
                      fallback_reason=fallback_reason),
        blocks=blocks, o7_line=o7_line, missing_approvals=report.missing_approvals,
        calls=call_breakdown(trace if trace is not None else CallTrace()))

