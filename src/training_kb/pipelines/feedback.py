"""Feedback Review pipeline（`feedback-review`）。

Owner：Phase 44（弱教學門檻與目標選取）；Phase 45（診斷）、46（REFINE）、47（candidate 規則）、
48（排程流程與 handler）在同一支檔各自追加。00A §3.2。

controller 2026-09-14 預建空殼：讓同一波次的 Phase 只用 Edit 追加各自區段。
"""

import hashlib
import json
import os
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from training_kb.analytics.ratings import average_rating
from training_kb.analytics.status_writer import load_validated_at
from training_kb.config import Thresholds, load_settings
from training_kb.content import (
    allocate_version,
    create_version,
    parse_markdown,
    validate_content,
    verify_version_complete,
)
from training_kb.errors import (
    ContentError,
    CoordinationError,
    PermanentError,
    TransientError,
)
from training_kb.ingress import (
    DEFAULT_FEEDBACK_CATEGORIES,
    approved_categories,
    operation_id_for,
)
from training_kb.keys import operation_ref, rule_pk
from training_kb.models import (
    AuthoringRule,
    Feature,
    Feedback,
    RuleStatus,
    StepDraft,
    StepType,
    Tutorial,
    TutorialContent,
    TutorialStatus,
)
from training_kb.operations import AcceptOperation, OperationCoordinator, OperationRecord
from training_kb.pipelines.common import (
    Deps,
    JSONValue,
    PipelineName,
    TaskFn,
    build_deps,
    run_sequence,
    task_name,
)
from training_kb.publishing import (
    MAX_BATCH_VERSIONS,
    PreparedPublish,
    Publisher,
    PublishRequest,
    assert_batch_publishable,
)
from training_kb.repository import Repository, item_to_model
from training_kb.rules import applied_rule_ids, render_rules_block, rules_for_content
from training_kb.site import SiteRenderer
from training_kb.writing.client import Writer
from training_kb.writing.prompts import (
    prompt_diagnose_weak,
    prompt_propose_rule,
    prompt_refine_steps,
)
from training_kb.writing.schemas import RuleProposal, StepRewrite, WeakDiagnosis

# ---- Phase 46（owner）：P51 import 同一個，不重新宣告（00A §5.4／§6.9）。 ----
# controller 2026-09-14 預先宣告（值來自 00A §5.4），讓 W2 併行的 P51 不必等 P46。
LEASE_TTL_SECONDS = 120


# ---- Phase 44（owner）：弱教學門檻與目標選取 ----
# 交付 `ReviewMode`、`WeakTarget`、`is_weak`、`select_weak_targets` 與 module-private 的
# `_top_category`；平均一律用 Phase 53 的 `average_rating`（00A D-44，單一算法，不自帶副本）。
# 只讀不寫：不呼叫模型、不建立版本、不判斷證據是否已處理（那是 Phase 46 的
# `evidence_fingerprint`）、不算展示指標（Phase 53／54）。

ReviewMode = Literal["formal", "demo"]
"""檢視模式：`formal` 是正式門檻，`demo` 是**明示隔離**的展示門檻（設計 §19.2 F20）。

兩者只差在樣本數（10 vs 8），平均 `< 3.5` 與同類 `>= 5` 完全一樣。任何情況下都不得把
`demo` 的命中結果說成正式門檻已滿足；O7 未核定前 Demo 的回饋仍是待核定合成資料。
"""


def is_weak(avg: float | None, n: int, top_category_count: int, *,
            mode: ReviewMode, thresholds: Thresholds) -> bool:
    """三條件 AND 的弱教學判斷（`REV` Rule 2、3、4；設計 §7.5）。

    - 平均 `< thresholds.weak_average`（3.5），**未四捨五入**：`3.49` 算弱、`3.5` 不算。
    - 樣本數 `n >= production_feedback`（10）；`mode="demo"` 改用 `demo_feedback`（8）。
    - 同一核定類別筆數 `>= recurring_category`（5）。

    `avg is None`（該版一筆評分都沒有）一律回 `False`，**不得**當成 0 分——零評分是「沒有
    訊號」不是「評價最差」（設計 §12.1）。三個門檻數字一律從 `Thresholds` 取，模組裡不留
    第二份字面值（00A §5.4）。未知的 mode 丟 `PermanentError` 而不是默默退回 formal：
    ASL 的 Catch 會把它導向失敗終點，總比用錯門檻挑出一批不該改的教學好。
    """
    if mode not in ("formal", "demo"):
        raise PermanentError(f"未知的 review mode：{mode}（只接受 formal 或 demo）")
    if avg is None:
        return False
    minimum = thresholds.production_feedback if mode == "formal" else thresholds.demo_feedback
    return (avg < thresholds.weak_average and n >= minimum
            and top_category_count >= thresholds.recurring_category)


@dataclass(frozen=True)
class WeakTarget:
    """一個命中的弱教學版本；四個欄位逐字對應 Phase 45 的 Consumes，不可改名（00A §6.9）。

    `tutorial_id` 是裸 slug（`prepare-meeting`）、`version_id` 是裸版本 ID
    （`prepare-meeting@v1`）。`feedback_ids` 裡的每一筆都屬於 `category` 這一類——它裝的是
    「這個版本、這個類別」的全部證據，不混入別類、`待分類` 或 `category is None` 的回饋；
    Phase 45 的診斷就是針對這一類在問「哪幾步出問題」，混類會讓它指錯步驟。
    """

    tutorial_id: str
    version_id: str
    category: str
    feedback_ids: tuple[str, ...]


def _top_category(feedback: Sequence[Feedback],
                  approved: frozenset[str]) -> tuple[str, tuple[str, ...]]:
    """筆數最多的核定類別與它的全部 Feedback ID；沒有任何核定類別回 `("", ())`。

    只數 `category in approved` 的回饋，所以 `待分類`（`PENDING_CATEGORY`）與 `None` 既不
    進同類計數也不進 `feedback_ids`（設計 §7.5、§12.1）。同類 ID 先用 `set` 去重再排序，
    同一批資料重跑得到逐字相同的輸出，Phase 46 的證據指紋才會穩定。

    平手（兩類筆數相同）用 `min` 配 `(-筆數, 類別名)`：筆數多者優先、其次類別名稱升序。
    **不可以**用 `max`——它在平手時回的是 dict 的插入順序，也就是 DynamoDB 這次剛好先回
    哪一筆，重送會挑到不同類別，Phase 46 的證據指紋就不穩定。
    """
    groups: dict[str, set[str]] = {}
    for row in feedback:
        category = row.category
        # 先擋掉 `None` 讓型別檢查看得出 key 一定是 str；語意上 None 本來就不在核定表裡。
        if category is None or category not in approved:
            continue
        groups.setdefault(category, set()).add(row.id)
    if not groups:
        return "", ()
    best = min(groups, key=lambda name: (-len(groups[name]), name))
    return best, tuple(sorted(groups[best]))


def select_weak_targets(*, repository: Repository, mode: ReviewMode, now: datetime,
                        thresholds: Thresholds | None = None) -> tuple[WeakTarget, ...]:
    """掃出所有弱教學版本（設計 §7.5；`REV` Rule 2、3、4，Rule 1 的 primary 在 Phase 48）。

    每一篇 active Tutorial 只看它**現在**的 `current_version`，而且該版必須已發布
    （`published_at` 非空）；retired、`current_version is None`、未發布的版本一律跳過，
    舊版的回饋也不會被算進來。設計 §7.5 明講不做「上次檢視之後」的浮水印切分，所以每次
    都用該版截至 `now` 的**全部**有效回饋重算。

    `now` 只是**截止點**：排除 `ts` 晚於它的回饋，`ts == now` 仍然算數。`ts is None` 的回饋
    無法判斷落在截止點哪一邊，一律排除（**本計畫選擇 2026-09-14**；Phase 42 的匯入入口
    一定補上 `ts`，只有種子或歷史資料直接寫 item 才會出現）。這與 Phase 54 的 O4 重開票
    窗口 `[p, p+14 天)` 是兩件事，不得互相借用。

    回空 tuple 是**正常結果**（這次沒有弱教學），不是錯誤；「同一批證據不要再產生新版」
    由 Phase 46 的 `evidence_fingerprint` 與 O2 操作紀錄負責，本函式每次都照實回報命中，
    否則呼叫端分不出「這次沒有弱教學」與「這次跳過了」。

    輸出依 `version_id` 升序：沒有固定順序時重送會得到不同的 target 順序，下游的證據指紋
    與操作 id 就不再是決定性的。
    """
    limits = thresholds or Thresholds()
    # Phase 43 已併入：讀 `CONFIG#feedback_categories`，讀不到或形狀不合法時，
    # `approved_categories` 自己退回 `DEFAULT_FEEDBACK_CATEGORIES`（初始兩類）。
    approved = approved_categories(repository)
    targets: list[WeakTarget] = []
    for item in repository.scan_entity("TUTORIAL", consistent=True):  # meta_only 預設 True
        tutorial = item_to_model(item, Tutorial)
        if tutorial.status != TutorialStatus.ACTIVE or tutorial.current_version is None:
            continue
        version = repository.get_version(tutorial.current_version)
        if version is None or version.published_at is None:
            continue
        feedback = [row for row in repository.list_feedback_of_version(version.version_id)
                    if row.ts is not None and row.ts <= now]
        rated = [row for row in feedback if row.rating is not None]
        category, ids = _top_category(feedback, approved)
        # 分子與分母都吃同一個 `rated`：平均與 n 必須出自同一群回饋（00A D-44）。
        if is_weak(average_rating(rated), len(rated), len(ids),
                   mode=mode, thresholds=limits):
            targets.append(WeakTarget(tutorial.slug, version.version_id, category, ids))
    return tuple(sorted(targets, key=lambda target: target.version_id))


# ---- Phase 45（owner）：回饋診斷與命中步驟 ----
# 交付 `DIAGNOSE_NODE`、`DiagnosisResult`、`diagnose_weak` 與 module-private 的
# `_validated_items`（`REV` Rule 5、6；設計 §7.5、§7.6、§14.1）。把 Phase 44 選出的
# `WeakTarget` 交給模型診斷，程式再驗證編號與原因，只留下真實存在且理由非空的步驟 `number`。
# 只讀不寫：不寫任何 DynamoDB item 或 S3 物件、不建版、不發布、不碰 `OperationCoordinator`。

DIAGNOSE_NODE = "diagnose_weak"
"""本節點寫進 Phase 15 `CallTrace` 的名字；`generate_json` 的 `node=` 一律傳它（00A §6.9）。"""


@dataclass(frozen=True)
class DiagnosisResult:
    """已驗證的診斷結果；Phase 46／48 只讀它，不直接信任模型回的原始 JSON。

    `WeakDiagnosis` 是模型輸出的原始 JSON（schema 只保證形狀），`DiagnosisResult` 才是
    通過業務驗證、可以交給後續程式的結果，兩者不可混用（設計 §7.6）。
    """

    version_id: str
    step_indexes: tuple[int, ...]
    """裝的是步驟 `number`（從 1 起），不是 0-based index（00A D-55）；`()` 代表 `NO_STEP`。"""
    reasons: dict[int, str]
    """鍵同樣是步驟 `number`（從 1 起），不是 0-based index（00A D-55）。"""
    feedback_ids: tuple[str, ...]


def _validated_items(reply: Mapping[str, Any],
                     valid: frozenset[int]) -> tuple[tuple[int, ...], dict[int, str]]:
    """schema 通過之後的業務驗證（設計 §7.6）：只留真實存在、理由非空的步驟，依 `number` 升序。

    四道檢查的順序固定：

    1. `number` 必須是**真正的**整數。`bool` 要先擋——`True` 是 `int` 的子型別，
       `True in frozenset({1})` 會成立，只比對「編號在不在」擋不掉它。
    2. `number` 必須是目前這一版真的有的步驟（`valid`），否則整個 item 丟掉；
       模型指到不存在的步驟時**不可**改成整篇重寫（設計 §14.1）。
    3. `reason` 去頭尾空白後必須非空，否則整個 item 丟掉：沒有理由的命中無從改寫。
    4. 同 `number` 重複時，原因相同就去重；**原因不同就丟 `ContentError`**（本計畫選擇）。
       任選第一筆或最後一筆會讓同一份輸入重送得到不同結果，寧可明確失敗。

    全部被丟掉就回 `((), {})`，也就是 `NO_STEP`——那是合法的業務結果，不是模型故障。
    """
    reasons: dict[int, str] = {}
    for item in reply.get("items") or ():
        number = item.get("number")
        reason = str(item.get("reason") or "").strip()
        if isinstance(number, bool) or not isinstance(number, int):
            continue
        if number not in valid or not reason:
            continue
        if number in reasons and reasons[number] != reason:
            raise ContentError(
                f"步驟 {number} 有互相衝突的診斷：{reasons[number]} / {reason}"
            )
        reasons[number] = reason
    numbers = tuple(sorted(reasons))
    return numbers, {number: reasons[number] for number in numbers}


def diagnose_weak(target: WeakTarget, *, repo: Repository, writer: Writer,
                  operation_id: str) -> DiagnosisResult:
    """診斷一個弱教學目標命中哪幾個既有步驟（`REV` Rule 5、6）。

    只讀 `target` 指定的那一版步驟與那一批 Feedback ID：其他版本、其他類別的回饋不會進
    prompt，模型看不到就無從混用。步驟依 `number` 升序、證據用 `sorted(set(feedback_ids))`，
    所以同一份輸入重送兩次會得到逐欄相同的 `DiagnosisResult`。

    `generate_json` 在整個函式裡**只出現一次**（F45：每次真實 attempt 都會被 `CallTrace`
    計入），`schema` 直接傳 `WeakDiagnosis` 這個 dict、拿回 dict（00A D-02，沒有同名的
    pydantic 類別可以 `model_validate`）；判斷類的 `maxTokens 512`／`temperature 0.1` 由
    Phase 15 的 `inference_config(schema)` 依 `$id` 決定，本節點不自己調參數（設計 §14.3）。
    不走 `generate_validated_json`：本節點的業務驗證沒有修正迴圈（D-11／00A §6.5），
    `ContentError` 直接往外丟。

    找不到有效步驟是**合法**結果（`step_indexes == ()`），Phase 46 據此記 `NO_STEP`、不配
    版號，**不可**改成整篇重寫（設計 §14.1）。
    """
    steps = sorted(repo.get_steps(target.version_id), key=lambda row: row.number)
    valid = frozenset(row.number for row in steps)
    wanted = tuple(sorted(set(target.feedback_ids)))
    chosen = set(wanted)
    evidence = sorted(
        (row for row in repo.list_feedback_of_version(target.version_id) if row.id in chosen),
        key=lambda row: row.id,
    )
    system, user = prompt_diagnose_weak(target.version_id, steps, target.category, evidence)
    reply = writer.generate_json(system, user, WeakDiagnosis,
                                 operation_id=operation_id, node=DIAGNOSE_NODE)
    numbers, reasons = _validated_items(reply, valid)
    return DiagnosisResult(target.version_id, numbers, reasons, wanted)


# ---- Phase 47 ----
# Candidate 規則提出與溯源：`MIN_CANDIDATE_FEEDBACK`、`PROPOSE_NODE`、`CandidateGroup`、
# `candidate_groups`、`candidate_rule_id`、`propose_candidate` 與三個 module-private helper。
# 只做「提出」：不排程、不組 pipeline（Phase 48）、不改 `RULE.status`（只有 Phase 55）、
# 不把 candidate 放進寫作 prompt（Phase 19 只選 active）、不算指標（Phase 53–55）。
# 與弱教學分支（Phase 44／45／46）完全獨立：不讀 `rating`、不呼叫 `is_weak`（設計 F26）。

MIN_CANDIDATE_FEEDBACK = 5
"""同版同類要湊足幾個**不同** Feedback ID 才可提出 candidate（設計 §7.5、00A §5.4）。

刻意不寫成 `Thresholds.recurring_category` 的別名：那是「弱教學要有 recurring 類別」的
門檻，這一個是「可以提規則」的門檻，兩條分支各自判斷，數字相同只是巧合（設計 F26）。
"""


@dataclass(frozen=True)
class CandidateGroup:
    """已驗證的證據組：同一版本、同一核定類別，加上去重且升序的 Feedback ID。

    這是呼叫模型的**前提**而不是結果：`propose_candidate` 只能拿已經成組的證據去問模型，
    `evidence`／`derived_from` 一律取自這裡，不採信模型回傳的版本（設計 D15、D18）。
    """

    version_id: str
    category: str
    feedback_ids: tuple[str, ...]


def candidate_groups(feedback: Iterable[Feedback],
                     approved: frozenset[str]) -> tuple[CandidateGroup, ...]:
    """把回饋分成可提案的證據組（`PRP` Rule 1）；純函式，完全不呼叫模型、不碰 Repository。

    分桶 key 是 `(tutorial_version, category)` 兩欄：跨版湊數是設計 F25 明確禁止的，
    所以 v1 三筆加 v2 兩筆雖然總數是五也不成組。同桶內先用 `set` 去重再數，同一筆回饋
    被讀兩次不會把門檻撐起來（`PRP` Rule 1 的「不同 Feedback」）。

    `category` 是 `None`（沒分類）或 `待分類` 時都不在核定類別表裡，直接跳過——`COL`
    Rule 5 的核定類別表由 Phase 43 維護，本函式只消費，不自己判斷哪些類別合法。
    `approved` 是**參數**不是查詢：要不要連 Repository 讀核定類別表，是 Phase 48 呼叫端的事。

    輸出依 `(version_id, category)` 升序、每組 ID 升序，所以同一批回饋永遠得到同一個順序，
    `candidate_rule_id` 才能是決定性的。`rating` 從頭到尾沒有被讀過：能提規則不代表這一版
    是弱教學（設計 F26）。
    """
    buckets: dict[tuple[str, str], set[str]] = defaultdict(set)
    for item in feedback:
        category = item.category
        # `category is None` 先擋掉是為了讓型別檢查看得出 key 的第二欄一定是 str；
        # 語意上 None 本來就不可能出現在核定類別表裡，兩種寫法結果相同。
        if category is None or category not in approved:
            continue
        buckets[(item.tutorial_version, category)].add(item.id)
    return tuple(
        CandidateGroup(version_id, category, tuple(sorted(ids)))
        for (version_id, category), ids in sorted(buckets.items())
        if len(ids) >= MIN_CANDIDATE_FEEDBACK
    )


def candidate_rule_id(group: CandidateGroup) -> str:
    """同一組證據永遠得到同一個 `rule_id`（設計 §7.5；00A §6.9 的例子是 `R-ad0afde8`）。

    `R-` 加上「`version_id`、`category`、排序後 ID 清單」三元組的 UTF-8 JSON 編碼取
    SHA-256 前 8 個十六進位字元。編碼方式是**契約的一部分**：`ensure_ascii=False`（中文
    類別名不轉 `\\uXXXX`）、`separators=(",", ":")`（不留空白），任何一項改掉，既有 item
    的 ID 就對不上，重送會變成新的一條規則。

    決定性 ID 就是本 Phase 的去重手段：搭配 `propose_candidate` 寫入前的 `get_meta` 與
    `put_meta(create_only=True)`，同一組證據重送落在同一筆 `RULE#<rule_id>`，不靠 O2 的
    操作紀錄。反過來說，多一筆新的同類 Feedback 就是**不同**的證據集合，得到不同的
    `rule_id`，可以另外提一條 candidate——這不是把新回饋排除在外。
    """
    payload = json.dumps([group.version_id, group.category, list(group.feedback_ids)],
                         ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return f"R-{hashlib.sha256(payload).hexdigest()[:8]}"


PROPOSE_NODE = "propose_rule"
"""`propose_candidate` 呼叫模型時的節點名；`CallTrace` 與 Phase 48 的 ASL 狀態都用它。"""


def _require_rule_text(value: object) -> str:
    """模型的 `rule` 必須是去頭尾後非空的字串（`PRP` Rule 5）。

    schema 已經擋過 `minLength: 1`，但 `"   "` 在 schema 眼裡是合法字串；這裡多擋一次，
    免得寫進 `AuthoringRule` 時才被 `rule_is_filled` 用 `ValidationError` 打回——
    後者是 pydantic 的例外，不會被 ASL 的 Catch 當成 `PermanentError` 處理。
    """
    if not isinstance(value, str) or not value.strip():
        raise ContentError(f"RuleProposal.rule 必須是非空字串：{value!r}")
    return value.strip()


def _require_step_type(value: object) -> StepType:
    """模型的 `applies_when` 必須是單一 `step.type` 字串，轉型後才存入（`PRP` Rule 3、D-10）。

    `bool` 單獨先擋掉：Python 的 `bool` 是 `int` 的子類，這一行明說「`True` 不是合法值」，
    日後放寬型別也不會破功。list／dict／`"click_ui, read"` 這種「多條件」寫法一律拒絕——
    MVP 的 `applies_when` 只表達單一 `step.type` 等值（設計 D16），不是運算式也不是 dict。
    """
    if isinstance(value, bool) or not isinstance(value, str):
        raise ContentError(f"applies_when 必須是單一 step.type 字串：{value!r}")
    try:
        return StepType(value)
    except ValueError as error:
        raise ContentError(f"applies_when 不是合法 step.type：{value!r}") from error


def _evidence_comments(group: CandidateGroup, *, repo: Repository) -> tuple[str, ...]:
    """取 group 內這幾個 ID 的留言原文，給 prompt 當素材；同版別組的留言不進 prompt。

    留言只是**素材**，不會被寫進 `AuthoringRule`：`evidence` 只存 ID（設計 D15）。
    沒有留言（只有評分或只有類別）的回饋自然跳過，不會在 prompt 留下空行。
    """
    wanted = set(group.feedback_ids)
    found: list[str] = []
    for item in repo.list_feedback_of_version(group.version_id):
        if item.id in wanted and item.comment:
            found.append(item.comment)
    return tuple(found)


def propose_candidate(group: CandidateGroup, *, writer: Writer, repo: Repository,
                      operation_id: str, rule_id: str) -> AuthoringRule:
    """對一組已驗證的證據提出一條 candidate 規則（`PRP` Rule 1–5、`REV` Rule 9）。

    順序是固定的（Phase 文件 §6）：先重驗門檻 → 已存在就回既有規則 → 才呼叫模型一次 →
    驗證模型只該決定的兩個欄位 → 組 `AuthoringRule` → `put_meta`。所以

    - 不足五個**不同** ID 連模型都不會打（前置檢查丟好讀的 `ContentError`；模型層的
      `evidence_has_five_distinct_ids` 是第二道防線，不是唯一防線）。
    - `RULE#<rule_id>` 已存在就**原樣回傳既有規則**：不覆寫、不再打模型。搭配
      `candidate_rule_id` 的決定性 ID，同一組證據重送不會多出第二條規則。
    - 模型只決定 `rule` 與 `applies_when`；`rule_id`／`evidence`／`derived_from`／`status`／
      `applied_to` 一律由程式依已驗證的 group 填。模型回傳的 `evidence` 與 `derived_from`
      讀完就丟——它們留在 schema 裡只是為了在 trace 中比對（設計 D15、D18）。

    寫出的 `status` 永遠是 `candidate`：這代表「已提出、待驗證」，**不代表已驗證有效**。
    只有 Phase 55 的狀態轉移能把它改成 active／retired，Phase 19 的一般寫作只取 active
    （設計 F27），所以這裡不需要、也不得碰 `status`。

    keyword 是 `repo=` 不是 `repository=`（00A §6.9，Phase 48 已照這個名稱呼叫）。
    判斷類參數（`max_tokens` 512、`temperature` 0.1）由 Phase 15／18 的 `inference_config`
    依 schema 的 `$id` 決定，本函式不重設。
    """
    if len(set(group.feedback_ids)) < MIN_CANDIDATE_FEEDBACK:
        raise ContentError(
            f"candidate 需要至少 {MIN_CANDIDATE_FEEDBACK} 個不同 Feedback ID："
            f"{group.version_id} / {group.category} 只有 {len(set(group.feedback_ids))} 個")
    existing = repo.get_meta(rule_pk(rule_id), AuthoringRule)
    if existing is not None:
        return existing
    system, user = prompt_propose_rule(group.version_id, group.category,
                                       group.feedback_ids,
                                       _evidence_comments(group, repo=repo))
    payload = writer.generate_json(system, user, RuleProposal,
                                   operation_id=operation_id, node=PROPOSE_NODE)
    candidate = AuthoringRule(
        rule_id=rule_id,
        rule=_require_rule_text(payload.get("rule")),
        applies_when=_require_step_type(payload.get("applies_when")),
        evidence=list(group.feedback_ids),
        status=RuleStatus.CANDIDATE,
        applied_to=[],
        derived_from=group.version_id,
    )
    repo.put_meta(candidate)
    return candidate


# ---- Phase 46（owner）：REFINE 精準改寫與證據去重 ----
# 交付 `REFINE_NODE`、`RefinePlan`、`evidence_fingerprint`、`refine_operation_id`、
# `refine_reason`、`evidence_of`、`prepare_refine` 與五個 module-private helper
# （`REV` Rule 7、8；設計 §7.5、§7.6、§8.1、§8.2、§14.1、§14.2）。
# `LEASE_TTL_SECONDS` 是同一個 Phase 的交付物，但由 controller 預先宣告在本檔開頭
# （讓 W2 併行的 P51 不必等本 Phase），所以這裡**不重複宣告**。
#
# 停止點：`create_version` ＋ `verify_version_complete` 通過後回 `RefinePlan`。
# **不發布、不切 `current_version`、不寫 `site/`、不提規則、不建立新的 Tutorial 身分。**

REFINE_NODE = "refine_steps"
"""本節點寫進 Phase 15 `CallTrace` 的名字；`generate_json` 的 `node=` 一律傳它（00A §6.9）。"""


def evidence_fingerprint(version_id: str, category: str, ids: Iterable[str]) -> str:
    """把「版本 ＋ 類別 ＋ 排序去重的 Feedback ID」雜湊成穩定字串（64 個十六進位字元）。

    **只吃穩定的東西。** 平均分、留言原文、執行時間都不進指紋：顯示文字改一個字就換一個
    指紋的話，永久去重（F23）會在第一次改文案時失效。ID 先 `sorted(set(...))`，所以
    `f_2, f_1, f_1` 與 `f_1, f_2` 得到同一個值；換版本或換類別則一定不同。

    `ensure_ascii=False` ＋ `sort_keys=True` ＋ 固定 `separators`：同一批證據在不同機器、
    不同 Python 版本上要算出逐字相同的 JSON，才算得出逐字相同的雜湊。
    """
    payload = {"version_id": version_id, "category": category,
               "feedback_ids": sorted(set(ids))}
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def refine_operation_id(version_id: str, category: str, ids: Iterable[str]) -> str:
    """這批證據的 REFINE `operation_id`：`op-feedback-<64 位指紋>`（00A §3.3）。

    **指紋就是 operation 的 canonical id**（本計畫選擇）。呼叫端（Phase 48）用它產生每個
    target 的 operation 再交給 `OperationCoordinator.accept`，一次解決三件事：同一批證據
    跨日重跑撞到同一筆 `OPS#` 永久紀錄（F23）；同一次 Review 的不同 target 有不同
    operation，`allocate_version` 不會兩篇共用版號；儲存重試沿用原版號與原模型輸出。

    永久去重本身仍然依賴 O2（P11 已 PASS），不是靠這個函式；它只保證「同證據＝同 ID」。
    """
    return operation_id_for("feedback", evidence_fingerprint(version_id, category, ids))


def refine_reason(category: str, feedback_ids: Iterable[str]) -> str:
    """改版原因，逐字 `feedback:<n> 則 <category>`（00A §3.3 三種格式之一、D28）。

    `<n>` 是**去重後**的證據筆數：同一個 ID 送兩次不會把 8 變成 9。
    """
    return f"feedback:{len(set(feedback_ids))} 則 {category}"


def evidence_of(diagnosis: DiagnosisResult, *, repo: Repository) -> tuple[str, tuple[str, ...]]:
    """回（唯一類別, 排序去重的 Feedback ID）；跨類別或有缺漏一律 `ContentError`。

    **一次 REFINE 只處理一個類別的證據。** 混類別的改寫沒有單一改法，reason 也寫不出
    `feedback:<n> 則 <category>`；缺漏則代表診斷引用了這一版沒有的回饋，兩者都是內容
    問題（`PermanentError` 子類），不重試。

    只看 `diagnosis.version_id` 那一版的回饋：別版、別類的回饋連讀都不會讀進來。
    """
    wanted = frozenset(diagnosis.feedback_ids)
    rows = [row for row in repo.list_feedback_of_version(diagnosis.version_id)
            if row.id in wanted]
    categories = {row.category for row in rows}
    if len(rows) != len(wanted) or len(categories) != 1:
        raise ContentError(f"{diagnosis.version_id} 的證據必須是同一個類別且不可缺漏")
    return categories.pop() or "", tuple(sorted(wanted))


@dataclass(frozen=True)
class RefinePlan:
    """一次 REFINE 的結果：一個**未發布**的下一版與它的來歷（00A §6.9，七個欄位不可改名）。

    回傳它代表 `create_version` ＋ `verify_version_complete` 都過了。**不代表已發布**：
    `published_at` 仍是 `None`、`Tutorial.current_version` 還指著基底版，公開站讀不到它。
    發布是 Phase 48 交給 Phase 25 `Publisher` 的事（O3 FAIL，不得宣稱可公開）。
    """

    version_id: str
    base_version_id: str
    reason: str
    content: TutorialContent
    changed_indexes: tuple[int, ...]
    """裝的是步驟 `number`（從 1 起），不是 0-based index（00A D-55）；欄位名是既有契約。"""
    rules_applied: tuple[str, ...]
    evidence_fingerprint: str


def _rules_for_hits(base: TutorialContent, targets: frozenset[int], *,
                    repo: Repository) -> list[AuthoringRule]:
    """只取**命中步驟型態**的 active 規則，依命中步驟出現順序、同一條只列一次（F29）。

    未改動的步驟就算型態相同、原文剛好符合某條規則，也不進 `rules_applied`：沿用原文不算
    本次套用。`select_active_rules` 每個型態最多回一條，所以上限是「命中步驟的不同型態數」，
    不是所有 active 規則；candidate 與 retired 永不入選（`APL` Rule 2）。

    最近驗證時間只能來自 `load_validated_at`（單一私有檔，D-28），缺值時 Phase 19 直接丟
    `PermanentError`，本函式**不補預設時間**。
    """
    step_types = [step.type for step in base.steps if step.number in targets]
    by_type = rules_for_content(repo.list_rules(RuleStatus.ACTIVE), step_types,
                                load_validated_at(repo))
    selected: dict[str, AuthoringRule] = {}  # dict 保留插入順序，同一條只列一次
    for step_type in step_types:
        selected.update({item.rule_id: item for item in by_type[step_type]})
    return list(selected.values())


def _assert_unchanged(base: TutorialContent, draft: TutorialContent,
                      changed: frozenset[int]) -> None:
    """未命中步驟與四個段落必須逐字相同（`REV` Rule 7；設計 §7.6）。

    逐欄 `model_dump()` 比較而不是只比 `text`：`feature_id`／`type`／`number` 任何一欄被動
    到都要擋。`strict=True` 讓「步驟數量變了」也是錯誤，而不是靜靜比對前 n 步。
    """
    if base.model_dump(exclude={"steps"}) != draft.model_dump(exclude={"steps"}):
        raise ContentError("REFINE 不可改動命中步驟以外的段落")
    for left, right in zip(base.steps, draft.steps, strict=True):
        if left.number not in changed and left.model_dump() != right.model_dump():
            raise ContentError(f"未命中步驟 {left.number} 的原文必須逐字相同")


def _apply_rewrite(base: TutorialContent, reply: Mapping[str, Any],
                   targets: frozenset[int]) -> TutorialContent:
    """把模型回的新文字套回基底；改寫集合必須**恰好**等於命中集合（F48 的業務驗證）。

    未命中的步驟整個物件原樣帶過——不是「重新產生一個看起來一樣的」，所以標點、空白都不會
    因為重新序列化而漂移。命中步驟只換 `text`：`feature_id` 與 `type` 一律以基底為準，模型
    想改就是錯誤（改引用等於偷換這一步在講哪個功能）。

    `schema` 只保證形狀（`StepRewrite` 連 `minItems` 都沒設），漏回、多回、改引用、空文字
    四種都要在這裡擋下來，而且全部在 `create_version` 之前——被拒的改寫不留半個產物。
    """
    changed = {int(item["number"]): item for item in reply["steps"]}
    if set(changed) != set(targets):
        raise ContentError(f"改寫集合 {sorted(changed)} 不等於診斷命中集合 {sorted(targets)}")
    steps: list[StepDraft] = []
    for step in base.steps:
        item = changed.get(step.number)
        if item is None:
            steps.append(step)  # 未命中：整個物件原樣帶過
            continue
        if item["feature_id"] != step.feature_id or item["type"] != step.type:
            raise ContentError(f"步驟 {step.number} 不可改變引用的 Feature 或型態")
        text = str(item["text"]).strip()
        if not text:
            raise ContentError(f"步驟 {step.number} 的新文字是空的")
        steps.append(step.model_copy(update={"text": text}))
    draft = base.model_copy(update={"steps": steps})
    _assert_unchanged(base, draft, targets)
    return draft


def _known_feature_ids(repo: Repository) -> frozenset[str]:
    """既有 Feature 的裸 ID；`item_to_model` 是必要的（strict 模型不吃保留屬性，00A §3.6）。"""
    return frozenset(item_to_model(item, Feature).feature_id
                     for item in repo.scan_entity("FEATURE"))


def _reuse_or_call(base: TutorialContent, diagnosis: DiagnosisResult, category: str,
                   rules: Sequence[AuthoringRule], *, record: OperationRecord,
                   repo: Repository, writer: Writer, operations: OperationCoordinator,
                   operation_id: str) -> Mapping[str, Any]:
    """取得這次的模型輸出；**儲存重試一律沿用既有的，不再呼叫模型**（設計 §14.2）。

    上一次已經打過模型、只是寫到一半的話，`record.model_output_refs[-1]` 指著那份輸出。
    重打一次會得到不一樣的文字（同樣的 prompt 也不保證同樣的回答），補齊出來的版本就與
    `.md`／`.diff` 對不上；而且 `CallTrace` 會多算一次真實 attempt。

    ref 讀不回來（物件被清掉）才重打：此時仍寫回**同一個** ref，`record_model_output`
    對同一個 ref 不重複附加，所以 `model_output_refs` 不會愈重試愈長。
    """
    if record.model_output_refs:
        stored = repo.get_object(record.model_output_refs[-1])
        if stored is not None:
            reused: dict[str, Any] = json.loads(stored.decode("utf-8"))
            return reused
    system, user = prompt_refine_steps(base, diagnosis, category, render_rules_block(rules))
    reply = writer.generate_json(system, user, StepRewrite,
                                 operation_id=operation_id, node=REFINE_NODE)
    ref = operation_ref(operation_id, "refine-steps")
    repo.put_object(ref, json.dumps(reply, ensure_ascii=False).encode("utf-8"),
                    "application/json", if_none_match=False)
    operations.record_model_output(operation_id, ref)
    return reply


def _guard(diagnosis: DiagnosisResult, category: str, feedback_ids: Sequence[str], *,
           repo: Repository, operations: OperationCoordinator,
           operation_id: str) -> OperationRecord | None:
    """三道守門：指紋相符、O2 已接受、這批證據還沒產出完整版本。

    回 `None` 代表 `no_new_evidence`（F23）——不是錯誤，呼叫端據此回 `None`。
    兩種 `CoordinationError` 的訊息刻意分開寫（**本計畫選擇**）：指紋不符是呼叫端組錯了
    `operation_id`，未接受是 O2 那一步漏了，兩者的修法不同。

    「已產版」用 `verify_version_complete` 判斷，**不是** `record.status`：狀態只說流程走到
    哪，產物齊不齊要看 S3 全文、VERSION item、STEP 與三種邊。有 `version_id` 但不完整代表
    上次寫到一半，要沿用同版號補齊，不能當成重複證據跳過。
    """
    if operation_id != refine_operation_id(diagnosis.version_id, category, feedback_ids):
        raise CoordinationError(f"{operation_id} 與本批證據的指紋不符")
    record = operations.load(operation_id)
    if record is None:
        raise CoordinationError(f"{operation_id} 尚未被 O2 接受")
    if record.version_id and verify_version_complete(record.version_id, repo):
        return None  # no_new_evidence（F23）
    return record


def prepare_refine(diagnosis: DiagnosisResult, *, repo: Repository, writer: Writer,
                   operations: OperationCoordinator,
                   operation_id: str) -> RefinePlan | None:
    """用 Phase 45 的診斷只改命中步驟，產出一個**未發布**的下一版（`REV` Rule 7、8）。

    處理順序固定（00A §6.9，與 Phase 51 的 UPDATE 相同）：

    ```text
    step_indexes == ()  -> None（NO_STEP，F24）
    evidence_of         -> 跨類別或有缺漏 -> ContentError
    _guard              -> 指紋不符／未接受 -> CoordinationError；已產完整版 -> None（F23）
    基底核對            -> 不是該篇最近已發布的版本 -> ContentError
    acquire_lease       -> 拿不到 -> TransientError（交 ASL Retry，不自行迴圈等待）
    選規則 -> 配版號 -> 模型（或重用）-> 程式核對 -> validate -> create_version -> verify
    release_lease（finally）-> RefinePlan
    ```

    回 `None` **只**代表 `NO_STEP` 或 `no_new_evidence` 兩種合法業務結果；技術錯誤一律往外
    丟，不吞：`ContentError`／`CoordinationError` 走 ASL 的 Catch，`TransientError` 走 Retry。

    停止點：`verify_version_complete` 通過就回 `RefinePlan`。**不發布、不切
    `current_version`、不寫 `site/`、不提規則、不建立新的 Tutorial 身分。**

    lease 的 `now` 取 `record.updated_at`（**本計畫選擇 2026-09-14**）：深層程式不讀系統
    時鐘（00A §3.5）。lease 不是接受順序保證，TTL 也不是準時解鎖，所以會改變版本鏈的寫入
    各自仍帶條件。
    """
    if not diagnosis.step_indexes:
        return None  # NO_STEP（F24）：記錄即可，不配版號、不建版、不整篇重寫
    category, feedback_ids = evidence_of(diagnosis, repo=repo)
    record = _guard(diagnosis, category, feedback_ids, repo=repo, operations=operations,
                    operation_id=operation_id)
    if record is None:
        return None  # no_new_evidence（F23）：不配版號、不呼叫模型
    base_version = repo.get_version(diagnosis.version_id)
    if base_version is None:  # get_version 回 TutorialVersion | None
        raise ContentError(f"{diagnosis.version_id} 不存在")
    tutorial = repo.get_tutorial(base_version.slug)
    if tutorial is None or tutorial.current_version != diagnosis.version_id:
        raise ContentError(f"{diagnosis.version_id} 不是 {base_version.slug} 最近已發布的版本")
    body = repo.get_object(base_version.s3_key)
    if body is None:
        raise ContentError(f"{diagnosis.version_id} 的全文不存在：{base_version.s3_key}")
    base = parse_markdown(body.decode("utf-8"))
    targets = frozenset(diagnosis.step_indexes)
    scope = f"TUTORIAL#{base_version.slug}"  # `LEASE#` 前綴由 Phase 11 自己補（00A §6.4）
    if not operations.acquire_lease(scope, operation_id, ttl_seconds=LEASE_TTL_SECONDS,
                                    now=record.updated_at):
        raise TransientError(f"{scope} 正在被另一個操作改寫，稍後重試")
    try:
        rules = _rules_for_hits(base, targets, repo=repo)
        plan = allocate_version(base_version.slug, operation_id, operations, repository=repo,
                                reason=refine_reason(category, feedback_ids),
                                rules_applied=applied_rule_ids(rules))
        reply = _reuse_or_call(base, diagnosis, category, rules, record=record, repo=repo,
                               writer=writer, operations=operations, operation_id=operation_id)
        draft = _apply_rewrite(base, reply, targets)
        validate_content(draft, _known_feature_ids(repo))
        create_version(plan, draft, repo)
        if not verify_version_complete(plan.version_id, repo):
            raise ContentError(f"{plan.version_id} 的內容或關係不完整")
        return RefinePlan(plan.version_id, base_version.version_id, plan.reason, draft,
                          tuple(sorted(targets)), plan.rules_applied,
                          evidence_fingerprint(diagnosis.version_id, category, feedback_ids))
    finally:
        operations.release_lease(scope, operation_id)


# ---- Phase 48 ----
# Feedback Review 排程流程：五個 Task 的組裝、本機整條序列與共用 Lambda 的直接入口。
# 本段只做 orchestration：業務判斷全部呼叫上面 Phase 44–47 的既有函式，不改它們的邏輯、
# 不改名、不重排。不新增第四條 pipeline（Demo 手動觸發共用同一個 state machine）、
# 不寫 `RULE.status`（只有 Phase 55 能寫）、不做部分發布（F49）。

FEEDBACK_REVIEW_PIPELINE: PipelineName = "feedback-review"
"""本條 pipeline 的名稱；`run_sequence` 與 ASL 的 `Parameters.pipeline` 都用它。"""

REVIEW_MODES: tuple[ReviewMode, ...] = ("formal", "demo")
"""ASL input 只有 `mode` 這一個必要欄位，合法值就是 `ReviewMode` 的兩個（設計 §19.2 F20）。"""


def _review_mode(state: Mapping[str, Any]) -> ReviewMode:
    """讀 `state["mode"]`；未知的值一律 `PermanentError`（不重試、不默默退回 formal）。

    退回 formal 會讓一次 demo 觸發用正式門檻挑出一批不該改的教學，錯得看不出來；
    丟 `PermanentError` 則直接進 ASL 的 Catch，整次執行停在 `PipelineFailed`。
    回傳值逐一比對 `REVIEW_MODES` 而不是 `cast`，型別收斂由比對本身保證。
    """
    mode = str(state.get("mode") or "formal")
    for candidate in REVIEW_MODES:
        if mode == candidate:
            return candidate
    raise PermanentError(f"未知的 review mode：{mode!r}（只接受 {'／'.join(REVIEW_MODES)}）")


def _ids(values: Iterable[str]) -> list[JSONValue]:
    """把 ID 清單轉成 ASL state 放得下的 `list[JSONValue]`。

    `list[str]` **不是** `list[JSONValue]` 的子型別（list 是不變的），直接塞進 state 會被
    型別檢查擋下來；這裡只做一次轉型，不在每個 Task 各寫一份 `cast`。
    """
    return [value for value in values]


def _listed(value: JSONValue) -> list[str]:
    """把 state 裡的 ID 清單讀回 `list[str]`；不是 list 就當成空清單。"""
    return [str(item) for item in value] if isinstance(value, list) else []


def _review_targets(repository: Repository) -> list[str]:
    """本次要檢視的版本 ID：active Tutorial 的 current，而且該版已發布（設計 §7.5）。

    retired、`current_version is None`、`published_at is None` 一律跳過；輸出依 ID 升序，
    同一批資料重跑得到逐字相同的 `target_version_ids`。這裡**只列 ID**：弱教學判斷與
    candidate 判斷都在 `EvaluateTargets`（00A §7 明講不拆成兩個 Task）。
    """
    found: list[str] = []
    for item in repository.scan_entity("TUTORIAL"):
        tutorial = item_to_model(item, Tutorial)
        if tutorial.status is not TutorialStatus.ACTIVE or tutorial.current_version is None:
            continue
        version = repository.get_version(tutorial.current_version)
        if version is not None and version.published_at is not None:
            found.append(version.version_id)
    return sorted(found)


def review_operation_id(state: Mapping[str, Any], deps: Deps) -> str:
    """當日 review 的 `operation_id`；`feedback-review` 沒有外部事件，由專案＋日期決定。

    canonical id 逐字是 `f"{project_id}-{UTC 日期}"`——**用連字號、不用 `#`**（00A D-61），
    所以 `operation_id` 就是 `op-feedback-review-demo-2026-09-13`，`execution_name` 可以
    原樣沿用而不必走 SHA-256 截取（`#` 會觸發截取，同一天的名稱就認不出來）。

    同一天重送會落在同一筆 operation 紀錄，`accept` 回 `duplicate`（O2 已 PASS，P11）。
    state 已經帶 `operation_id`（`EvaluateTargets` 之後的每一個 Task）就原樣沿用。
    """
    project_id = str(state.get("project_id") or deps.need_settings().project_id)
    canonical = f"{project_id}-{deps.now().date().isoformat()}"
    return str(state.get("operation_id")
               or operation_id_for("feedback-review", canonical))


def task_list_targets(state: dict[str, JSONValue], deps: Deps) -> dict[str, JSONValue]:
    """`ListTargets`：接受當日 operation，列出本次要檢視的版本 ID。

    `mode` 先驗證再做任何讀取，未知的 mode 連表都不掃（§8 驗收矩陣的 Boundary 那一列）。
    """
    mode = _review_mode(state)
    now = deps.now()
    project_id = str(state.get("project_id") or deps.need_settings().project_id)
    operation_id = review_operation_id(state, deps)
    deps.operations.accept(AcceptOperation(
        operation_id=operation_id, kind="feedback-review", project_id=project_id,
        canonical_id=f"{project_id}-{now.date().isoformat()}", now=now))
    return {"operation_id": operation_id, "project_id": project_id, "mode": mode,
            "target_version_ids": _ids(_review_targets(deps.need_repository()))}


def task_evaluate_targets(state: dict[str, JSONValue], deps: Deps) -> dict[str, JSONValue]:
    """`EvaluateTargets`：同一個 Task 裡跑 candidate 與 REFINE **兩條獨立分支**。

    兩條分支寫在同一個迴圈但**沒有共用條件**：candidate 只看 `candidate_groups` 的
    「同版同類 >= 5」，REFINE 只看 `select_weak_targets` 的三條件 AND，所以「平均 5.0 但
    同類五筆」仍會提規則（設計 F26），「弱教學但診斷沒命中」仍不會建版（F24）。

    **每個弱教學 target 都有自己的子 operation（00A D-59）**：`allocate_version` 以
    `operation_id` 當唯一鍵、`OperationRecord.version_id` 只有一個值，兩篇共用當日的
    review operation 會互相搶同一個版號。所以先用 `refine_operation_id(...)` `accept`
    一筆子 operation，再把它當成 `diagnose_weak`／`prepare_refine` 的 `operation_id`。

    逐篇的「沒有改動」理由**不進 state**（00A §7 只有八個欄位）：寫進私有
    `operations/<op>/review-no-change.json`，`CommitBatch` 再把它併進 `review-result.json`。
    """
    repository, writer = deps.need_repository(), deps.need_writer()
    operation_id = str(state["operation_id"])
    # P43 併入後改成 `approved_categories(repository)`（00A §6.9）；與 `select_weak_targets`
    # 目前用的是同一個常數，兩條分支的核定類別表不會分岔。
    approved = DEFAULT_FEEDBACK_CATEGORIES
    weak = {target.version_id: target
            for target in select_weak_targets(repository=repository, mode=_review_mode(state),
                                              now=deps.now(),
                                              thresholds=deps.need_settings().thresholds)}
    rule_ids: list[str] = []
    prepared: list[str] = []
    reasons: dict[str, str] = {}
    for version_id in _listed(state.get("target_version_ids")):
        found: list[str] = []
        for group in candidate_groups(repository.list_feedback_of_version(version_id), approved):
            found.append(propose_candidate(group, writer=writer, repo=repository,
                                           operation_id=operation_id,
                                           rule_id=candidate_rule_id(group)).rule_id)
        target, plan = weak.get(version_id), None
        if target is not None:
            refine_id = refine_operation_id(target.version_id, target.category,
                                            target.feedback_ids)
            deps.operations.accept(AcceptOperation(
                operation_id=refine_id, kind="feedback",
                canonical_id=evidence_fingerprint(target.version_id, target.category,
                                                  target.feedback_ids),
                project_id=str(state["project_id"]), now=deps.now()))
            plan = prepare_refine(diagnose_weak(target, repo=repository, writer=writer,
                                                operation_id=refine_id),
                                  repo=repository, writer=writer, operations=deps.operations,
                                  operation_id=refine_id)
            if plan is not None:
                prepared.append(plan.version_id)
        rule_ids.extend(found)
        if not found and plan is None:
            reasons[version_id] = ("不是弱教學" if target is None
                                   else "診斷沒有可改步驟，或沒有新證據")
    repository.put_object(f"operations/{operation_id}/review-no-change.json",
                          json.dumps(reasons, ensure_ascii=False).encode("utf-8"),
                          "application/json", if_none_match=False)
    return {**state, "candidate_rule_ids": _ids(sorted(rule_ids)),
            "prepared_version_ids": _ids(sorted(prepared))}


def _publisher(deps: Deps) -> Publisher:
    """本 pipeline 的 `Publisher`；`SiteRenderer()` 無參數建構是既定用法（P24）。"""
    return Publisher(deps.need_repository(), SiteRenderer(), deps.operations)


def _prepared(state: Mapping[str, Any], deps: Deps) -> PreparedPublish | None:
    """這一批的 staging 產物；沒有要發布的版本時回 `None`。

    同一個 operation 重跑會得到**同一批** staging 產物（設計 §14.2：`prepare` 只寫私有
    前綴、同 bytes 覆寫），所以不必把 `PreparedPublish` 塞進 state——state 只放 ID 與
    S3 key（00A §7）。三個 Task 各自重算一次，代價是重寫同一份 bytes。

    超過 `MAX_BATCH_VERSIONS` 在**寫第一個 staging 物件之前**就擋下來：交易上限是 100 個
    action、每篇兩個，拆成兩次交易就不再是全有或全無（F49）。
    """
    version_ids = tuple(_listed(state.get("prepared_version_ids")))
    if not version_ids:
        return None
    if len(version_ids) > MAX_BATCH_VERSIONS:
        raise PermanentError(f"單批最多 {MAX_BATCH_VERSIONS} 個版本，本次 {len(version_ids)} 個")
    request = PublishRequest(version_ids=version_ids, operation_id=str(state["operation_id"]))
    return _publisher(deps).prepare(request, now=deps.now())


def task_prepare_batch(state: dict[str, JSONValue], deps: Deps) -> dict[str, JSONValue]:
    """`PrepareBatch`：把整批的公開產物寫進**私有** staging，並記下這次的請求。

    這個 Task 結束時**一個公開物件都還沒寫**；`publish_request_ref` 指向的
    `operations/<op>/publish-request.json` 只是可追溯紀錄，不是發布。
    """
    prepared = _prepared(state, deps)
    if prepared is None:
        return {**state, "publish_request_ref": None}
    assert_batch_publishable(prepared)
    key = f"operations/{state['operation_id']}/publish-request.json"
    deps.need_repository().put_object(
        key, json.dumps({"version_ids": list(prepared.version_ids),
                         "staged_keys": list(prepared.staged_keys)},
                        ensure_ascii=False).encode("utf-8"), "application/json",
        if_none_match=False)
    return {**state, "publish_request_ref": key}


def task_inspect_batch(state: dict[str, JSONValue], deps: Deps) -> dict[str, JSONValue]:
    """`InspectBatch`：整批只讀不寫的檢查；任一篇不過就整批停在這裡（F49）。

    停在這裡的時候 `published_at` 與 `current_version` 都還沒動、`site/` 也還是空的，
    所以「第二篇檢查失敗」一定發生在任何公開前綴寫入**之前**。
    """
    prepared = _prepared(state, deps)
    if prepared is None:
        return dict(state)
    inspection = _publisher(deps).inspect(prepared)
    if not inspection.ok:
        raise PermanentError("整批未通過檢查：" + "；".join(inspection.problems))
    return dict(state)


def task_commit_batch(state: dict[str, JSONValue], deps: Deps) -> dict[str, JSONValue]:
    """`CommitBatch`：一次交易切完整批，再把本次結果寫成 `review-result.json`。

    `PublishResult.failed` 有值代表 DynamoDB 擋下了這次切換（兩個欄位都沒變、`site/` 也
    沒有新檔），那是**失敗**不是「發布了一部分」：丟 `PermanentError` 交給 Catch，
    不回一個看起來正常的結果（比照 P41 review 必修 3 的 `task_publish_version`）。

    這是整條流程的停止點：寫出 `review-result.json` 並 `operations.complete(...)`。
    逐篇的「沒有改動」理由在這裡才從 `review-no-change.json` 併進來。
    """
    repository, operation_id = deps.need_repository(), str(state["operation_id"])
    published: tuple[str, ...] = ()
    prepared = _prepared(state, deps)
    if prepared is not None:
        result = _publisher(deps).commit(prepared, now=deps.now())
        if result.failed is not None:
            raise PermanentError(f"整批提交失敗：{result.failed}；{'；'.join(result.reasons)}")
        published = result.published
    body = repository.get_object(f"operations/{operation_id}/review-no-change.json")
    key = f"operations/{operation_id}/review-result.json"
    repository.put_object(key, json.dumps({
        "reviewed_version_ids": _listed(state.get("target_version_ids")),
        "candidate_rule_ids": _listed(state.get("candidate_rule_ids")),
        "prepared_version_ids": _listed(state.get("prepared_version_ids")),
        "published_version_ids": list(published),
        "no_change_reasons": json.loads((body or b"{}").decode("utf-8")),
    }, ensure_ascii=False).encode("utf-8"), "application/json", if_none_match=False)
    deps.operations.complete(operation_id, now=deps.now())
    return {**state, "result_ref": key}


FEEDBACK_REVIEW_TASKS: tuple[TaskFn, ...] = (task_list_targets, task_evaluate_targets,
                                             task_prepare_batch, task_inspect_batch,
                                             task_commit_batch)
"""五個 Task 的固定順序（00A §7 的一條直線）；`task_name(...)` 就是 ASL 的 `Parameters.task`。

**沒有 Choice、沒有 Map**：把逐篇處理拆進 Map 會讓「第一篇已 publish、第二篇失敗」變成
可能，那正是 F49 禁止的形狀。
"""

_TASK_BY_NAME: dict[str, TaskFn] = {task_name(task): task for task in FEEDBACK_REVIEW_TASKS}
"""ASL `Parameters.task` -> Task 函式；名稱由 `task_name` 導出，不另打一份字串表。"""

_DEPS: Deps | None = None
"""Lambda 容器層級的相依快取：同一個容器只組一次 boto3 client 與 `BedrockWriter`。"""


def run_feedback_review(state: dict[str, JSONValue], deps: Deps) -> dict[str, JSONValue]:
    """本機與測試用的整條序列；雲端由 Step Functions 逐個 Task 呼叫 handler。

    `run_sequence` 會先檢查 payload 有非空 `operation_id`（D-07），但 `feedback-review`
    沒有外部事件、ASL input 只有 `mode`，所以這裡先把當日 id 補進 payload 再交給它。
    雲端路徑不經 `run_sequence`，因此不受這個前置檢查影響。
    """
    payload: dict[str, JSONValue] = {**state, "mode": _review_mode(state),
                                     "operation_id": review_operation_id(state, deps)}
    return run_sequence(FEEDBACK_REVIEW_PIPELINE, payload, FEEDBACK_REVIEW_TASKS, deps)


def feedback_review_handler(event: dict[str, Any], context: object) -> dict[str, JSONValue]:
    """`feedback-review` 的直接入口：**只跑 `event["task"]` 指定的那一個 Task**。

    不 try／except：`TransientError` 要讓 ASL 的 Retry 抓到，`PermanentError` 要讓 Catch
    抓到（設計 §14.2）。相依在第一次 invoke 時才組，之後同一個容器沿用。
    """
    global _DEPS
    task = _TASK_BY_NAME.get(str(event.get("task")))
    if task is None:
        raise PermanentError(f"feedback-review 沒有名為 {event.get('task')!r} 的 task")
    if _DEPS is None:
        _DEPS = build_deps(load_settings(os.environ))
    state = event.get("state")
    return task(dict(state) if isinstance(state, dict) else {}, _DEPS)
