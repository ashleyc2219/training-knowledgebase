"""Ticket Analysis 的業務函式（設計 §7.3、§9.1、§14.2、§14.3）。

模型只出現在「文字 -> 向量」這一步：要不要呼叫模型、屬於哪一群、新群叫什麼名字，
全部由程式決定，所以同一筆 Ticket 重送會得到一樣的結果。

門檻只有一份：`0.85` 的唯一來源是 `Thresholds.cosine_match`，本檔的
`CLUSTER_COSINE_THRESHOLD` 只是它的別名（00A §5.4、D-35），模組裡不得再出現第二份字面值。

本檔由 Phase 38 建立，Phase 39（recurring 與 gap 命名）、Phase 40（CREATE／KEEP）、
Phase 41（Task 包裝與 handler）會繼續在同一支檔案上追加。
"""

import json
import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import ValidationError

from training_kb.analytics.status_writer import load_validated_at
from training_kb.clock import to_iso, utc_date
from training_kb.config import Thresholds
from training_kb.content import VersionPlan, allocate_version, create_version, validate_content
from training_kb.errors import ContentError, PermanentError
from training_kb.keys import META, feature_pk, operation_ref, ticket_pk
from training_kb.models import (
    Feature,
    RuleStatus,
    StepType,
    Ticket,
    Tutorial,
    TutorialContent,
    TutorialStatus,
)
from training_kb.operations import OperationCoordinator
from training_kb.repository import DynamoItem, Repository, item_to_model
from training_kb.rules import applied_rule_ids, render_rules_block, rules_for_content
from training_kb.vectors import centroid, cosine
from training_kb.writing.client import Writer, generate_validated_json
from training_kb.writing.prompts import prompt_name_gap, prompt_write_tutorial
from training_kb.writing.schemas import GapNaming, TutorialDraft
from training_kb.writing.validators import BusinessValidator, gap_naming_validator

CLUSTER_COSINE_THRESHOLD = Thresholds().cosine_match
"""同群判定線，`Thresholds.cosine_match` 的別名；要調門檻只改 P02 那個欄位的預設值。"""


# --- 1. Embedding（Task：ensure_embedding） ---------------------------------


def ensure_embedding(ticket: Ticket, *, writer: Writer, repository: Repository,
                     operation_id: str) -> Ticket:
    """缺向量才呼叫 Titan，叫完就寫回；已經有向量就原樣回傳（設計 §14.2）。

    順序不能換：**先一致讀取既有 TICKET**，再決定要不要呼叫模型。只看傳入物件會讓
    重送每次都多花一次 Bedrock 呼叫，而重送是 Step Functions 的常態。

    維度、NaN、`bool` 這些回應有效性由 Phase 16 的 `Writer.embed` 檢查並丟
    `PermanentError`；`TransientError` 則交給 ASL 的 Retry。兩者都**原樣往上拋**，
    函式內不自行重試、失敗時一個字都不寫回。

    寫回走 `put_meta(create_only=False)`：TICKET 已由接入層建立，這是 Phase 06 受控覆寫
    路徑（`_revision` 的 compare-and-swap）。版本過期時它丟 `CoordinationError`，本函式
    **不吞不重試**，由上層依 O2 語意重讀重算。
    """
    stored = repository.get_meta(ticket_pk(ticket.id), Ticket, consistent=True)
    current = stored if stored is not None else ticket
    if current.embedding:
        return current
    # node 名固定 "ticket-embedding"：人工驗收靠它數 `CallTrace` 裡 kind=embedding 的
    # attempt。00A §6.9 沒有把它列成 P38 的公開名稱，所以不另外宣告常數讓 P39／P41 有機會
    # 寫出第二份不同的字串。
    vector = writer.embed(current.text, operation_id=operation_id, node="ticket-embedding")
    updated = current.model_copy(update={"embedding": vector})
    repository.put_meta(updated, create_only=False)
    return updated


# --- 2. 分群（Task：assign_cluster） ----------------------------------------


def assign_cluster(ticket: Ticket, *, repository: Repository) -> str:
    """回傳這則 Ticket 該屬於哪一個 `cluster_id`；**只做判斷，不寫資料庫**。

    把 `cluster_id` 寫回 TICKET 是 Phase 41 `assign_cluster` Task 的責任（該 Task 必須
    先一致讀取 TICKET 再呼叫這裡）。

    已經有 `cluster_id` 就原樣回傳：重送沿用同一群（設計 §14.2）。否則讀同專案的全部
    Ticket（`list_tickets` 走 Phase 08 的 `scan_entity("TICKET")`，`meta_only=True` 讓
    Phase 40 之後掛在 `TICKET#<id>` 上的 `ASKS_ABOUT#` 邊不會被誤算成工單），依
    `cluster_id` 分組、每組算**群中心**再比 cosine。

    三條規則讓重跑結果固定：
    1. 一律拿 `centroid` 比，即使群裡只有一筆，也不拿「第一筆」當代表（F10）。
    2. 排序鍵是 `(-分數, cluster_id)`：同分取最小 `cluster_id`，不依賴掃描或 dict 順序。
    3. 自己不當自己的群中心，但自己的群編號仍算既有編號。

    沒有任何群達到 `CLUSTER_COSINE_THRESHOLD` 就開新群。編號唯一性只在同一個
    `project_id` 內成立；跨專案併發的保證屬於 O2，未通過前不得宣稱無競態。
    """
    if ticket.cluster_id:
        return ticket.cluster_id
    if not ticket.embedding:
        raise PermanentError("assign_cluster 需要已保存的 embedding")
    known: set[str] = set()
    groups: dict[str, list[list[float]]] = {}
    for other in repository.list_tickets(ticket.project_id):
        if not other.cluster_id:
            continue
        known.add(other.cluster_id)
        if other.id != ticket.id and other.embedding:
            groups.setdefault(other.cluster_id, []).append(other.embedding)
    scored = [(cosine(ticket.embedding, centroid(rows)), cid) for cid, rows in groups.items()]
    good = sorted((row for row in scored if row[0] >= CLUSTER_COSINE_THRESHOLD),
                  key=lambda row: (-row[0], row[1]))
    return good[0][1] if good else new_cluster_id(known)


def new_cluster_id(existing: Iterable[str]) -> str:
    """既有 `c<數字>` 的最大值加一；完全沒有既有群時回 `c1`。

    只認得 `c<數字>` 這個形狀，其他字串不影響編號。MVP 不合群也不重編號，既有
    `cluster_id` 永遠保留，`Tutorial.cluster_id` 才追溯得回來（設計 §7.3、D29）。
    最後那道撞號檢查是防守用的：`max + 1` 在結構上不會撞到既有編號，真的撞到代表
    上游資料或這段邏輯壞了，**明確失敗**而不是靜默換一個號碼。
    """
    known = set(existing)
    numbers = [int(value[1:]) for value in known if value[:1] == "c" and value[1:].isdigit()]
    candidate = f"c{max(numbers) + 1 if numbers else 1}"
    if candidate in known:
        raise PermanentError(f"新群編號 {candidate} 已存在")
    return candidate


# --- 3. Recurring 判定（Task：evaluate_recurring） ---------------------------

RECURRING_DAYS = 14
"""窗口長度：當日加前 13 個 UTC **日期**，共十四個。

`Thresholds` 刻意**沒有**對應欄位（00A §5.4），所以這份 `14` 就是全套唯一一份；
不得自創 `Thresholds.recurring_days` 這種新欄位名（D-35）。
"""

RECURRING_MIN_TICKETS = Thresholds().recurring_tickets
"""recurring 門檻，`Thresholds.recurring_tickets` 的別名；模組裡不得再出現第二份 `5`。"""


def recurring_window(anchor: date, days: int = RECURRING_DAYS) -> frozenset[date]:
    """回傳 anchor 當日與前 `days - 1` 個 UTC 日期組成的**日期集合**（設計 §7.3、F11）。

    是「日期集合」而不是「時間區間」：同一個 UTC 日不管幾點都落在同一個桶裡，所以
    `2026-08-31T00:00:00Z` 在窗口內、`2026-08-30T23:59:59Z` 在窗口外。用
    `now - 14 days` 這種區間算法會讓同一批輸入在不同時刻重跑得到不同答案。

    `days < 1` 是呼叫端的錯，不是資料問題：窗口至少要含 anchor 當日本身，
    空窗口會讓任何一群都算不出 recurring 而**安靜地**跳過命名。
    """
    if days < 1:
        raise PermanentError(f"recurring 窗口天數至少為 1，收到 {days}")
    return frozenset(anchor - timedelta(days=offset) for offset in range(days))


def is_recurring(ticket: Ticket, *, repository: Repository) -> bool:
    """同群工單在 anchor 的十四天窗口內是否累積到 `RECURRING_MIN_TICKETS` 筆（設計 §7.3）。

    anchor 固定是**觸發本輪的那筆工單的 `ts`**，不是執行當下的時間：同一批輸入
    什麼時候重跑都得到一樣的答案（設計 §14.2）。`Ticket.ts` 在 Phase 04 已經是
    `datetime`，所以直接 `utc_date(...)`，不再套一層 `parse_iso`（那是給字串用的）。

    固定順序：沒有 `cluster_id` -> `PermanentError`（Phase 38 還沒跑完，這是流程順序
    錯，不是「不算 recurring」）；否則同專案的 Ticket 只留同群、且日期落在窗口內的，
    依 `Ticket.id` 去重。同一天內的多筆各算一筆——日期只拿來過濾，不拿來去重。

    anchor 自己一定算一筆：它的日期必然在窗口內，而 Phase 41 的 Task 順序容許
    `cluster_id` 還沒寫回表（`assign_cluster` 只判斷不寫入），掃描不一定看得到它。
    """
    if not ticket.cluster_id:
        raise PermanentError(f"工單 {ticket.id} 尚未分群，不能判斷 recurring")
    window = recurring_window(utc_date(ticket.ts))
    seen = {
        other.id
        for other in repository.list_tickets(ticket.project_id)
        if other.cluster_id == ticket.cluster_id and utc_date(other.ts) in window
    }
    seen.add(ticket.id)
    return len(seen) >= RECURRING_MIN_TICKETS


# --- 4. Knowledge Gap 命名（Task：name_gap） ---------------------------------


def _meta_rows(repository: Repository, entity: str) -> list[DynamoItem]:
    """`scan_entity` 的結果再濾一次 `SK == META` 才轉模型（沿用 Phase 27 的做法）。

    Phase 08 的 `scan_entity` **預設 `meta_only=True`**，已經先濾過一次；這裡是第二道
    保險：`entity` 等於**起點** PK 的前綴（Phase 07 `put_edge`），所以 Phase 40 之後掛在
    `TICKET#<id>` 上的 `ASKS_ABOUT#FEATURE#<id>` 邊與 TICKET 本體同前綴。呼叫端哪天改傳
    `meta_only=False`，邊也不會被丟進 `item_to_model` 而整筆 `ValidationError`。
    不改 Phase 08 的簽名。
    """
    return [row for row in repository.scan_entity(entity) if str(row["SK"]) == META]


def known_features(repository: Repository) -> tuple["Feature", ...]:
    """目前存在的全部 Feature，依 `feature_id` 升序（Phase 08 **沒有** `list_features`）。

    順序固定才讓 prompt 的 `allowed_features` 與重跑結果可重現；Phase 40 重用同一份清單。
    """
    features = (item_to_model(row, Feature) for row in _meta_rows(repository, "FEATURE"))
    return tuple(sorted(features, key=lambda feature: feature.feature_id))


def _validated_naming(payload: dict[str, Any], validate: BusinessValidator) -> dict[str, object]:
    """只做兩件事：`gap` 去頭尾後非空，然後交給 Phase 18 的 `gap_naming_validator`。

    「Feature 存不存在」這條規則全系統只有 Phase 18 那一份（Phase 18 §5、00A §6.5），
    本函式**只是包裝**，不得改用 `get_feature` 再判一次。`gap` 非空是 schema 的
    `minLength: 1` 蓋不到的部分——全空白字串在形狀上合法，在業務上是空診斷。
    """
    if not str(payload["gap"]).strip():
        raise ContentError("gap_empty: gap")
    validate(payload)
    return payload


def name_gap(cluster_id: str, *, repository: Repository, writer: Writer,
             operation_id: str, operations: OperationCoordinator) -> dict[str, object]:
    """替一個 recurring 群命名 Knowledge Gap；模型**最多呼叫一次**（設計 §7.3、§14.2）。

    回傳的是 `generate_json` 吐出的 `dict`（`gap` 與 `feature_id`），不是 pydantic 模型：
    `GapNaming` 是 Phase 17 的 **JSON schema 字典**，呼叫端用 `naming["feature_id"]`
    取值（00A D-02）。

    固定順序與兩道守衛：

    1. 先 `get_object(ref)`。去重的判準是**物件本身**而不是 operation 紀錄的 ref 清單：
       先寫物件、再記 ref，中間失敗時紀錄裡沒有 ref 但物件已存在；只看 `operations.load`
       會再呼叫一次模型，而且 `put_object(if_none_match=True)` 還會撞
       `ObjectAlreadyExists`。先讀物件同時蓋掉這兩個洞，`record_model_output` 仍照補，
       讓 Phase 41 與指標看得到這次輸出。
    2. 再數群成員。任何十四天窗口都不可能從不到五筆的群裡湊出五筆，所以群總數不足
       `RECURRING_MIN_TICKETS` 一定是呼叫端漏做 `is_recurring`，直接 `PermanentError`
       擋在模型呼叫**之前**；精確的窗口判斷仍只由 `is_recurring` 負責。

    `name_gap` 只拿得到 `cluster_id`（Phase 41 的 Task 不傳 Ticket 也不傳 `project_id`），
    所以群成員走 `scan_entity("TICKET")` 再依 `cluster_id` 過濾；MVP 是單一專案（D01），
    與 `is_recurring` 的 `list_tickets` 路徑結果一致。成員依 `Ticket.id` 升序才讓 prompt
    不隨掃描順序漂移。

    模型回不存在的 `feature_id` 是設計 §7.6 要程式攔下的違規輸出，丟 `ContentError`，
    **不自動改成 `null`、不補建 Feature**；回 `null` 則是設計 §14.1 明列的合法業務結果，
    保留 gap 交 Phase 40 決定。本函式自己不重試、不做第二次呼叫。
    """
    ref = operation_ref(operation_id, "gap-naming")
    features = known_features(repository)
    validate = gap_naming_validator(
        known_feature_ids=frozenset(one.feature_id for one in features))
    saved = repository.get_object(ref)
    if saved is not None:
        reused: dict[str, Any] = json.loads(saved)
        naming = _validated_naming(reused, validate)
        operations.record_model_output(operation_id, ref)
        return naming
    tickets = sorted((item_to_model(row, Ticket) for row in _meta_rows(repository, "TICKET")),
                     key=lambda ticket: ticket.id)
    texts = [one.text for one in tickets if one.cluster_id == cluster_id]
    if len(texts) < RECURRING_MIN_TICKETS:
        raise PermanentError(f"群 {cluster_id} 未達 recurring 門檻，不呼叫模型")
    system, user = prompt_name_gap(texts, [one.feature_id for one in features])
    # node 名固定 "name_gap"：人工驗收靠它在 `CallTrace` 裡數同一個 operation 的 attempt，
    # 只能有一筆。Phase 38 的 "ticket-embedding" 同樣直接寫在呼叫點，不另立常數。
    reply = writer.generate_json(system, user, GapNaming,
                                 operation_id=operation_id, node="name_gap")
    naming = _validated_naming(reply, validate)
    body = json.dumps(naming, ensure_ascii=False, sort_keys=True).encode("utf-8")
    repository.put_object(ref, body, "application/json", if_none_match=True)
    operations.record_model_output(operation_id, ref)
    return naming


# --- 5. CREATE／KEEP 決策（Task：decide_action） -----------------------------

TicketAction = Literal["CREATE", "KEEP", "NO_FEATURE"]
"""這一輪的三種結果：建新教學、什麼都不改、缺有效 Feature 先擱著（設計 §7.3）。"""


@dataclass(frozen=True)
class TicketGap:
    """一個 recurring 群的命名結果加上它的成員。

    由 Phase 41 的 `DecideAction` Task 用 `cluster_id` 與 Phase 39 `name_gap` 回的 dict
    （`naming["gap"]`、`naming["feature_id"]`）以及同群 `Ticket.id` 組出來。`feature_id`
    只可能是**既有 Feature 的裸 ID** 或 `None`——不存在的 ID 在 Phase 39 就已經被
    `gap_naming_validator` 擋掉了。
    """

    cluster_id: str
    gap: str
    feature_id: str | None
    ticket_ids: tuple[str, ...]


@runtime_checkable
class _ActiveTutorialFinder(Protocol):
    """Phase 27 `find_active_tutorial_for_feature` 的最小形狀。

    P27 尚未落地，`Repository` 上還沒有這個方法；有就用它、沒有就走 `_active_tutorial`
    裡同一份判準的基表查法。P27 落地後這個 Protocol 與 fallback 都可以一起刪掉，
    判準不會因此改變（兩邊都是「`status == active` 且 `feature_id in feature_ids`，
    多篇時取 slug 升序第一筆」）。
    """

    def find_active_tutorial_for_feature(self, feature_id: str) -> Tutorial | None: ...


def _active_tutorial(repository: Repository, feature_id: str) -> Tutorial | None:
    """這個 Feature 目前有沒有 `status=active` 的教學（設計 §7.3、F12）。"""
    if isinstance(repository, _ActiveTutorialFinder):
        return repository.find_active_tutorial_for_feature(feature_id)
    found = sorted((item_to_model(row, Tutorial) for row in _meta_rows(repository, "TUTORIAL")),
                   key=lambda one: one.slug)
    return next((one for one in found if one.status == TutorialStatus.ACTIVE
                 and feature_id in one.feature_ids), None)


def decide_ticket_action(gap: TicketGap, *, repository: Repository) -> TicketAction:
    """純判斷：只讀 Feature 與 Tutorial 狀態，**不寫任何資料**（設計 §7.3）。

    判斷順序固定，而且「有沒有教學」看的是 `status`，不是 `current_version`：

    ```text
    feature_id 是 None？ -- 是 --> NO_FEATURE（保留 gap，Ticket Analysis 永不建 Feature）
    get_feature 找得到？ -- 否 --> ContentError（資料不一致，不猜也不補建）
    有 status=active 的教學？ -- 是 --> KEEP（即使 current_version 還是 None，F12）
                              -- 否 --> CREATE（只有 retired 不算已有教學）
    ```

    F12 明說 active 但尚待首次發布也算「已有教學」，避免同一個功能被建兩篇；retired 不算，
    所以退役後遇到同樣的重複工單可以重新建立。
    """
    if gap.feature_id is None:
        return "NO_FEATURE"
    if repository.get_feature(gap.feature_id) is None:
        raise ContentError(f"Feature {gap.feature_id} 不存在")
    return "KEEP" if _active_tutorial(repository, gap.feature_id) is not None else "CREATE"


def record_decision(action: TicketAction, gap: TicketGap, *, repository: Repository,
                    operation_id: str, now: datetime) -> str:
    """寫 `operations/<operation_id>/ticket-decision.json` 並回傳它的私有 ref。

    **三種結果都要寫**，這就是 `分析工單` Rule 8 的「只記錄 log」：KEEP 一個字都不寫進教學
    內容，但為什麼不改要留得下來。物件用 `if_none_match=False` 覆寫，所以同一個
    `operation_id` 重跑安全。

    `action` 不是 `NO_FEATURE` 時，順便把 `gap.ticket_ids` 的每張工單連到 Feature
    （00A D-52／D-57）：那是**工單側的標註**，不是教學內容。本 Phase 是 `Ticket.feature_ids`
    與 `ASKS_ABOUT` 邊的唯一寫入者。
    """
    ref = operation_ref(operation_id, "ticket-decision")
    record = {"action": action, "cluster_id": gap.cluster_id, "gap": gap.gap,
              "feature_id": gap.feature_id, "ticket_ids": list(gap.ticket_ids),
              "decided_at": to_iso(now)}
    body = json.dumps(record, ensure_ascii=False, sort_keys=True).encode("utf-8")
    repository.put_object(ref, body, "application/json", if_none_match=False)
    if action != "NO_FEATURE":
        _link_tickets(gap, repository=repository)      # D-52：只有有效 Feature 才連
    return ref


def _link_tickets(gap: TicketGap, *, repository: Repository) -> None:
    """同群每張工單指到同一個 Feature；一張工單最多一個（D04），重跑不會變成兩條。

    先一致讀回 `TICKET#<id>`：`feature_ids` 已經等於 `[feature_id]` 就跳過寫入，否則
    `put_meta(create_only=False)` 覆寫成**單一元素**（不是 append）。邊的 SK 固定是
    `ASKS_ABOUT#FEATURE#<id>`，重寫同一條不會多出 item，所以 Phase 41 的 `DecideAction`
    Task 與 `create_first_version` 各呼叫一次也安全。
    """
    feature_id = gap.feature_id
    if feature_id is None:
        raise ContentError(f"群 {gap.cluster_id} 沒有有效 Feature，不能連工單")
    for ticket_id in gap.ticket_ids:
        ticket = repository.get_meta(ticket_pk(ticket_id), Ticket)
        if ticket is None:
            raise ContentError(f"工單 {ticket_id} 不存在，無法連到 Feature")
        if ticket.feature_ids != [feature_id]:         # 最多一個元素（D04）
            repository.put_meta(ticket.model_copy(update={"feature_ids": [feature_id]}),
                                create_only=False)
        repository.put_edge(ticket_pk(ticket_id), "ASKS_ABOUT", feature_pk(feature_id))


# --- 6. slug 與教學身分 -------------------------------------------------------

_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
"""教學 slug 的唯一形狀：ASCII 小寫字母數字，以單一連字號分段（00A §3.3）。"""


def _kebab(raw: str) -> str:
    """把任意文字折成 ASCII kebab-case；折不出東西就回空字串。"""
    folded = unicodedata.normalize("NFKD", raw or "").encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "-", folded.lower()).strip("-")[:60].strip("-")


def tutorial_slug(gap: TicketGap, title: str, *, repository: Repository) -> str:
    """決定這一篇教學的 slug；**模型不產任何穩定 ID**（設計 §7.6）。

    退讓順序固定，所以同一個 operation 重試會得到同一個 slug，不會像「遞增 -2、-3」那樣
    每次換一個：

    ```text
    _kebab(content.title) -> 空的就退回 _kebab(feature_id) -> 再空就退回 gap-<cluster_id>
                          -> 被「別群」佔用就固定改用 <base>-<cluster_id>
                          -> 仍衝突 -> ContentError（不再往下編號）
    ```

    「被佔用」只看 `Tutorial.cluster_id`：同一群的既有教學就是上一次重試留下的那一篇，
    直接沿用（`create_tutorial_identity` 會回傳它）。
    """
    base = _kebab(title) or _kebab(gap.feature_id or "") or _kebab(f"gap-{gap.cluster_id}")
    if not _SLUG_RE.fullmatch(base):
        raise ContentError(f"slug 必須是 ASCII kebab-case：{base!r}")
    for candidate in (base, f"{base}-{gap.cluster_id}"):
        owner = repository.get_tutorial(candidate)
        if owner is None or owner.cluster_id == gap.cluster_id:
            return candidate
    raise ContentError(f"slug {base} 已被其他群佔用")


def create_tutorial_identity(gap: TicketGap, *, slug: str, topic: str,
                             repository: Repository) -> Tutorial:
    """建立 `TUTORIAL#<slug>` 這筆 metadata；**只有 Ticket Analysis 能做這件事**。

    先 `get_tutorial` 再 `put_meta(create_only=True)` 是刻意的：重試時直接回既有那一篇，
    只有真正併發撞鍵才會讓 `put_meta` 丟 `CoordinationError`。

    `feature_ids=[gap.feature_id]` **必須**寫進去：Phase 27 的
    `find_active_tutorial_for_feature` 是用 `feature_id in Tutorial.feature_ids` 找的，
    漏寫的話下一輪同群工單會再建一篇。`Tutorial` 的七個欄位就是全部，不得多塞第八個
    （00A D-40）。`current_version=None`、`successor=None`：建立與發布是兩件事（設計 §8.2）。
    """
    feature_id = gap.feature_id
    if feature_id is None:
        raise ContentError(f"群 {gap.cluster_id} 沒有有效 Feature，不能建立教學身分")
    existing = repository.get_tutorial(slug)
    if existing is not None:                     # 同一群重試：沿用既有那一篇，不重寫
        if existing.cluster_id != gap.cluster_id:
            raise ContentError(f"教學 {slug} 屬於別群 {existing.cluster_id}")
        return existing
    tutorial = Tutorial(slug=slug, topic=topic, status=TutorialStatus.ACTIVE,
                        current_version=None, feature_ids=[feature_id],
                        successor=None, cluster_id=gap.cluster_id)
    repository.put_meta(tutorial, create_only=True)   # 併發撞鍵 -> CoordinationError
    return tutorial


# --- 7. 建立未發布的第一版（Task：create_first_version） ----------------------

ALL_STEP_TYPES: tuple[StepType, ...] = tuple(StepType)
"""`click_ui`、`input`、`read`（Phase 03 的宣告順序）。

直接由 `tuple(StepType)` 取得，不重打一份字串清單，才不會跟 Phase 03 的列舉成員拼法分岔
（00A §5.2）。
"""


def _evidence_text(gap: TicketGap, repository: Repository) -> str:
    """把 gap 診斷與**同群**工單原文串成 Phase 17 要的那**一個**字串。

    只讀 `gap.ticket_ids` 指定的工單：別群的文字不會進 prompt。工單不存在代表上游資料
    不一致，明確失敗而不是安靜少一筆證據（少的那一筆會讓寫出來的教學不可重現）。
    轉義與分區標記由 `prompt_write_tutorial` 內部的 `_as_data` 負責（00A D-67），
    本函式只負責挑對證據。
    """
    texts: list[str] = [gap.gap]
    for ticket_id in gap.ticket_ids:
        ticket = repository.get_meta(ticket_pk(ticket_id), Ticket)
        if ticket is None:
            raise ContentError(f"工單 {ticket_id} 不存在，無法組出寫作證據")
        texts.append(ticket.text)
    return "\n".join(texts)


def _own_retry_tutorial(gap: TicketGap, *, repository: Repository) -> Tutorial | None:
    """本群上一次重試留下的那一篇 active 教學；沒有就回 `None`。

    第一次跑完之後，`TUTORIAL#<slug>` 已經是 active，`decide_ticket_action` 會改回 KEEP，
    中斷後重送因此會撞上 `create_first_version` 的守衛。用 `Tutorial.cluster_id` 分辨兩件事：
    **同一群**的那一篇就是自己上一次留下的，允許沿用同版號補齊（F36、D26）；**別群**
    （含 Demo 直接寫入的種子教學）佔住 Feature 就是真正的 KEEP，一律 `PermanentError`。
    """
    if gap.feature_id is None:
        return None
    existing = _active_tutorial(repository, gap.feature_id)
    return existing if existing is not None and existing.cluster_id == gap.cluster_id else None


def _as_content(payload: dict[str, Any]) -> TutorialContent:
    """`generate_json` 回的是 `dict`，不是模型；這裡才是唯一的 `model_validate`（D-02）。

    pydantic 的 `ValidationError` 轉成 `ContentError`，修正迴圈（`generate_validated_json`）
    才攔得到而給模型一次機會。訊息只放欄位數，**不放模型輸出**（00A §3.8）。
    """
    try:
        return TutorialContent.model_validate(payload)
    except ValidationError as error:
        raise ContentError(f"tutorial_draft_invalid: {error.error_count()} 個欄位") from error


def _tutorial_draft_validator(known_feature_ids: frozenset[str]) -> BusinessValidator:
    """`TutorialDraft` 的業務檢查：五段齊全、每步恰一個既有 Feature（Phase 21）。

    只是把 Phase 21 的 `validate_content` 包成 `BusinessValidator` 交給
    `generate_validated_json`；業務判斷本身**一份都不重寫**（00A §6.5）。
    """
    def validate(payload: dict[str, Any]) -> None:
        validate_content(_as_content(payload), known_feature_ids)
    return validate


def create_first_version(gap: TicketGap, *, repository: Repository, writer: Writer,
                         operations: OperationCoordinator, operation_id: str,
                         now: datetime) -> VersionPlan:
    """CREATE：寫出一個**未發布**的 v1，順序不可調換（設計 §7.3、§8.2）。

    ```text
    1 再判一次 decide_ticket_action -> 不是 CREATE 就 PermanentError
    2 list_rules(ACTIVE) + load_validated_at -> rules_for_content -> 去重後的 injected 清單
    3 render_rules_block(injected) 進 prompt -> generate_validated_json(TutorialDraft)
    4 （驗證在 3 裡面：TutorialContent.model_validate + validate_content）
    5 tutorial_slug 產生並驗證 kebab-case 與唯一
    6 create_tutorial_identity（create_only=True、feature_ids=[feature_id]；重試沿用同一篇）
    7 allocate_version(reason="gap:<cluster_id>", rules_applied=applied_rule_ids)
    8 create_version -> published_at 仍是 null
    9 record_decision("CREATE", ...) -> 寫決策紀錄並連工單到 Feature
    ```

    **先驗內容再建身分**：模型輸出不合法時不留下一個空的 `TUTORIAL#` item。步驟 2 的規則
    選取是純函式，`list_rules` 與 `load_validated_at` 都由本函式先讀好再傳進 Phase 19；
    步驟 7 的 `rules_applied` 只放**本次實際注入 prompt** 的 ID，沿用原文不算套用（F29）。

    模型呼叫走 `generate_validated_json`（00A §6.5：schema 後業務驗證＋最多一次修正的
    唯一合法入口），本函式自己**不重試、不另組修正 prompt**。
    """
    if decide_ticket_action(gap, repository=repository) != "CREATE" \
            and _own_retry_tutorial(gap, repository=repository) is None:
        raise PermanentError(f"群 {gap.cluster_id} 不是 CREATE，不能建立第一版")
    rules = repository.list_rules(RuleStatus.ACTIVE)
    by_type = rules_for_content(rules, ALL_STEP_TYPES, load_validated_at(repository))
    injected = list({rule.rule_id: rule
                     for step_type in ALL_STEP_TYPES
                     for rule in by_type[step_type]}.values())
    features = known_features(repository)
    known = frozenset(feature.feature_id for feature in features)
    system, user = prompt_write_tutorial(_evidence_text(gap, repository),
                                         [feature.feature_id for feature in features],
                                         render_rules_block(injected))
    # node 名固定 "create_v1"：人工驗收靠它在 `CallTrace` 裡數同一個 operation 的 attempt。
    draft = generate_validated_json(writer, system, user, TutorialDraft,
                                    _tutorial_draft_validator(known),
                                    operation_id=operation_id, node="create_v1")
    content = _as_content(draft)              # draft 是 dict，不是模型
    slug = tutorial_slug(gap, content.title, repository=repository)
    create_tutorial_identity(gap, slug=slug, topic=content.title, repository=repository)
    plan = allocate_version(slug, operation_id, operations, repository=repository,
                            reason=f"gap:{gap.cluster_id}",
                            rules_applied=applied_rule_ids(injected))
    create_version(plan, content, repository)
    record_decision("CREATE", gap, repository=repository, operation_id=operation_id, now=now)
    return plan
