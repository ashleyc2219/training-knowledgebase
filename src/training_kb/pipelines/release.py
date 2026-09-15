"""Release Update pipeline（`release-update`）。

Owner：Phase 49（Feature 定位與 alias）；Phase 50（步驟反查與 Safety Net）、51（UPDATE 精準改寫）、
52（RETIRE 與 handler）在同一支檔各自追加。00A §3.2。

controller 2026-09-14 預建空殼：讓同一波次的 Phase 只用 Edit 追加各自區段。
"""

import json
import logging
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import Any

from training_kb.analytics.status_writer import load_validated_at
from training_kb.clock import now_utc
from training_kb.config import Thresholds
from training_kb.content import (
    VersionPlan,
    allocate_version,
    create_version,
    parse_markdown,
    parse_version_id,
    validate_content,
    verify_version_complete,
)
from training_kb.errors import (
    ContentError,
    CoordinationError,
    PermanentError,
    TransientError,
)
from training_kb.ingress import operation_id_for
from training_kb.keys import META, feature_pk, operation_ref
from training_kb.models import (
    AuthoringRule,
    Feature,
    Release,
    ReleaseKind,
    RuleStatus,
    StepDraft,
    StepType,
    Tutorial,
    TutorialContent,
    TutorialStatus,
    TutorialStep,
)
from training_kb.operations import AcceptOperation, OperationCoordinator
from training_kb.pipelines.feedback import LEASE_TTL_SECONDS
from training_kb.repository import DynamoValue, Repository, item_to_model
from training_kb.rules import applied_rule_ids, render_rules_block, rules_for_content
from training_kb.vectors import cosine
from training_kb.writing.client import Writer
from training_kb.writing.prompts import prompt_release_rewrite, prompt_safety_net_confirm
from training_kb.writing.schemas import StepConfirmation, StepRewrite
from training_kb.writing.validators import step_rewrite_validator

# ---- Phase 49：Feature 定位與 alias（設計 §7.4、§9.1、D06／D07／F15） ----

FEATURE_MATCH_THRESHOLD: float = Thresholds().cosine_match
"""語意定位的採用線，`Thresholds.cosine_match` 的**別名**（00A §5.4、D-35）。

本檔不得再出現第二份 `0.85`：要調門檻只改 Phase 02 那個欄位的預設值，Phase 38 的
`CLUSTER_COSINE_THRESHOLD` 也指向同一欄位。
"""

LOCATE_QUERY_NODE = "locate_feature_query"
LOCATE_CANDIDATE_NODE = "locate_feature_candidate"
"""語意層兩次 `Writer.embed` 的 `node`：一次查詢、每個候選一次，call trace 才分得出誰是誰。"""


def normalize_feature_name(value: str) -> str:
    """只用來**比對**的正規化名稱：去頭尾空白再 `casefold`，不改顯示值也不寫回圖譜。

    `casefold` 而不是 `lower`：它會把 `ß` 正規成 `ss` 這類大小寫以外的等價字，比對才對得齊。
    字串**中間**的空白刻意保留（`"Meeting Summary"` 與 `"Meeting  Summary"` 是不同名稱），
    因為 `Feature` 的 `bare_id` 本來就允許中間空白，這裡多做壓縮會讓比對比模型還寬鬆。
    Phase 50 會 import 這支函式，名稱不得更動。
    """
    return value.strip().casefold()


def _lookup_keys(release: Release) -> tuple[str, ...]:
    """定位用的查詢鍵，固定 `old_name` → `feature` → `new_name` 並去重。

    `old_name` 排最前面，因為圖譜保存的是改版**之前**的名稱；`new_name` 排最後，只在
    Feature 已先以新名稱建立時才派上用場。`changed`／`removed` 沒有這兩個欄位
    （Phase 31 只對 `renamed` 強制非空），鍵就只剩 `feature` 一個。
    去重比對用**原字串**：第 1 層本來就是完全相同比對，正規化只在第 2 層做。
    """
    keys: list[str] = []
    for value in (release.old_name, release.feature, release.new_name):
        if value and value.strip() and value not in keys:
            keys.append(value)
    return tuple(keys)


def _all_features(repository: Repository) -> list[Feature]:
    """全表 Feature，依 `feature_id` 升序；排序固定，平手時的勝者才可重現。

    先濾掉 `SK != META` 再 `item_to_model`：`entity` 屬性等於 PK 前綴（00A §3.6），所以同一個
    `FEATURE#…` 起點的關係邊也帶 `entity == "FEATURE"`，而邊沒有模型欄位，直接餵給
    `item_to_model` 會整筆 `ValidationError`。`meta_only` 預設就是 `True`，這層過濾是為了
    「哪天預設值變了也還是對的」——與 `repository._meta_models` 同一套寫法。
    掃描固定 `consistent=True`：基表可以一致讀取，GSI 不行（設計 §10）。
    """
    rows = [item for item in repository.scan_entity("FEATURE", consistent=True)
            if str(item["SK"]) == META]
    return sorted((item_to_model(row, Feature) for row in rows),
                  key=lambda item: item.feature_id)


def _names_of(item: Feature) -> set[str]:
    """一個 Feature 佔用的全部正規化名稱：現名加上所有別名。"""
    return {normalize_feature_name(name) for name in [item.name, *item.aliases]}


def _normalized_match(features: Sequence[Feature], keys: Sequence[str]) -> Feature | None:
    """第 2 層：strip ＋ casefold 之後比對 name 與 aliases。

    同一個正規化名稱對到兩個 Feature 代表 D07 的唯一性已經被破壞，一律 `PermanentError`，
    不挑一個回去——挑錯會把改版寫到別篇教學上。
    """
    wanted = {normalize_feature_name(key) for key in keys}
    hits = [item for item in features if wanted & _names_of(item)]
    if len(hits) > 1:
        raise PermanentError(f"名稱對到多個 Feature：{[item.feature_id for item in hits]}")
    return hits[0] if hits else None


def _semantic_match(features: Sequence[Feature], keys: Sequence[str], *,
                    writer: Writer, operation_id: str) -> Feature | None:
    """第 3 層：查詢鍵與每個候選各算一條向量，最高分 `>= FEATURE_MATCH_THRESHOLD` 才採用。

    一個候選都沒有就直接回 `None`（**本計畫選擇（2026-09-14）**）：省掉查詢那一次 `embed`，
    「表裡零個 Feature」也就不會算成一次 Bedrock attempt。
    `features` 進來時已依 `feature_id` 升序，加上嚴格 `>` 比較，同分固定選 `feature_id`
    最小者，重跑結果相同。是否採用是程式的判斷，不是模型的判斷（F15）。
    """
    if not features:
        return None
    query = writer.embed(" / ".join(keys), operation_id=operation_id, node=LOCATE_QUERY_NODE)
    best_score, best = 0.0, None
    for item in features:
        text = " / ".join([item.name, *sorted(item.aliases)])
        vector = writer.embed(text, operation_id=operation_id, node=LOCATE_CANDIDATE_NODE)
        score = cosine(query, vector)
        if score > best_score:
            best_score, best = score, item
    return best if best is not None and best_score >= FEATURE_MATCH_THRESHOLD else None


def locate_feature(release: Release, *, repository: Repository, writer: Writer,
                   operation_id: str) -> Feature | None:
    """把一則已正規化的 Release 定位到唯一一個既有 Feature；找不到回 `None`。

    三層固定順序，前一層命中就不進下一層，目的是「能不呼叫模型就不呼叫」（設計 §10）：
    完全相同字串（Phase 27 的 `find_feature_by_name_or_alias`）→ 正規化比對 → 語意 `>= 0.85`。
    第 1 層的 `PermanentError`（同一 alias 屬於兩個 Feature，D07）直接往上拋，不吞、也不改判
    成 `None`。回 `None` 是**合法業務結果**：呼叫端以 KEEP 結束，不改版也不建立 Feature，
    這裡永遠不會產生新的 Feature 主鍵（D06）。
    """
    keys = _lookup_keys(release)
    for key in keys:
        found = repository.find_feature_by_name_or_alias(key)
        if found is not None:
            return found
    features = _all_features(repository)
    return _normalized_match(features, keys) or _semantic_match(
        features, keys, writer=writer, operation_id=operation_id
    )


def update_feature_aliases(feature: Feature, *, old_name: str, new_name: str,
                           repository: Repository) -> Feature:
    """改名收尾：把顯示名稱換成 `new_name`、把 `old_name` 收進 aliases，**主鍵不動**（D06）。

    這是一次**全有或全無**的檢查：先組出目標 `aliases = (舊 aliases + old_name) - new_name`，
    再把「新名稱與全部目標別名」逐一比對其他 Feature 的 name 與 aliases，**全部通過才**呼叫
    `update_meta`。順序不能換——先寫再檢查會留下「name 已改、alias 撞名」的半套資料，而
    撞名依 D07 必須整次拒絕（`PermanentError`），不可降級成 KEEP。

    把 `new_name` 從 aliases 移除是**本計畫選擇（2026-09-14）**：唯一性檢查就不必對自己開
    例外。移除用 `normalize_feature_name` 比對，所以 `prepare` 這種只差大小寫的舊別名也會
    一併移掉，不會留下「自己的別名等於自己的名字」（那是 `Feature` 的模型不變量）。
    aliases 固定 `sorted`，重跑寫出去的 byte 相同。

    `model_copy(update=...)` **不重新驗證**，所以 `name` 與 aliases 在這裡就先 `strip` 過；
    `Feature` 的 `bare_id` 只擋空字串、前後空白與 `#`／控制字元，中間空白本來就合法。
    `expected_revision` 的唯一取值來源是 `Repository.revision_of(pk)`（Phase 06 §5）：
    item 上的欄位叫 `_revision` 而且 `get_meta` 會濾掉它，不得自己挖 item 湊一個。
    本函式只在 `kind == "renamed"` 的流程末端（Phase 52 的 `UpdateAliases`，排在
    `PublishBatch` 之後）呼叫，所以兩個名稱任一為空就是呼叫端接錯線，直接 `PermanentError`。
    """
    display, previous = new_name.strip(), old_name.strip()
    if not display or not previous:
        raise PermanentError("old_name 與 new_name 都不可為空")
    wanted = normalize_feature_name(display)
    candidates = {previous, *(item.strip() for item in feature.aliases)}
    aliases = sorted({item for item in candidates
                      if item and normalize_feature_name(item) != wanted})
    mine = {wanted, *(normalize_feature_name(item) for item in aliases)}
    for other in _all_features(repository):
        if other.feature_id == feature.feature_id:
            continue
        clash = sorted(mine & _names_of(other))
        if clash:
            raise PermanentError(f"alias 與 {other.feature_id} 衝突：{clash}")
    pk = feature_pk(feature.feature_id)
    written: list[DynamoValue] = list(aliases)
    repository.update_meta(
        pk,
        {"name": display, "aliases": written},
        expected_revision=repository.revision_of(pk),
    )
    return feature.model_copy(update={"name": display, "aliases": aliases})


# ---- Phase 50：步驟反查與 Safety Net（設計 §7.4、§10、F16／F17／F18） ----


@dataclass(frozen=True)
class StepHit:
    """一個「要被改版的步驟」座標：哪一篇、哪一版、第幾步（00A §6.9 固定欄位順序）。

    frozen 才進得了 `set`：呼叫端（Phase 52 的 `task_safety_net`）用
    `set(direct) | set(net)` 把明確命中與補漏命中取聯集，補漏永遠不覆寫明確命中。
    步驟編號一律叫 `number`（00A §3.3），不是 `index`，也不是候選清單的名次。
    """

    slug: str
    version_id: str
    number: int


def find_release_hits(feature_id: str, *, repository: Repository) -> tuple[StepHit, ...]:
    """目前已發布版本裡真的引用這個 Feature 的步驟座標，依 `(slug, number)` 升序。

    反查本身是 Phase 27 的 `Repository.find_current_published_steps_referencing`：A 方向用
    `by_target` GSI 取候選、B 方向用基表一致讀取核對，歷史版與未發布版都由它排除（F17）。
    本函式只做**型別轉換與排序**，不得另寫一份 `query_by_target` 篩選（00A D-38）——多一份
    就會有兩套一致性規則，GSI 慢半拍時兩邊給的答案還會不一樣。

    `slug` 由 Phase 20 的 `parse_version_id` 從 `TutorialStep.tutorial_version` 還原，不再查一
    次表。GSI 有候選、基表卻讀不到目前已發布步驟時，Phase 27 丟的 `PermanentError` **原樣往
    上拋**：那是「基表資料不完整」，不是「沒有命中」，不得改判成空 tuple 讓呼叫端誤 KEEP；
    補邊是 Phase 28 的責任，不在查詢裡順手寫。
    """
    hits = {
        StepHit(parse_version_id(step.tutorial_version)[0], step.tutorial_version, step.number)
        for step in repository.find_current_published_steps_referencing(feature_id)
    }
    return tuple(sorted(hits, key=lambda hit: (hit.slug, hit.number)))


def needs_safety_net(release: Release, feature: Feature, hits: Sequence[StepHit]) -> bool:
    """要不要花錢補漏：反查為零，或「alias 比對失敗的 renamed」才要（F16）。

    兩個觸發條件各自獨立：反查為零時不論哪一種 `kind` 都補一次，因為「真的沒人引用」與
    「邊還沒補齊」在這一層分不出來；有命中時只有 renamed 需要再看一眼，而且**只有 alias
    比對失敗**才算重大改名——`old_name` 已經收在 Feature 的 name／aliases 裡，代表 Phase 49
    已經靠名稱對上了，再補漏只是多花錢。

    `kind` 用 `ReleaseKind` 成員比較（**本計畫選擇（2026-09-14）**）：`ReleaseKind` 是
    `StrEnum`，與 `"renamed"` 字串也會相等，但 enum 比較不會被打錯的字面值騙過，mypy 也擋得住。
    名稱比對走 Phase 49 的 `normalize_feature_name`（同一支檔，不另外複製一份規則）。

    純函式：不碰 `Repository` 也不碰 `Writer`。這一步決定要不要呼叫模型，本身不該有副作用，
    所以 alias 已命中的組合連一次 `embed` 都不會發生。
    """
    if not hits:
        return True
    if release.kind is not ReleaseKind.RENAMED:
        return False
    known = {normalize_feature_name(name) for name in [feature.name, *feature.aliases]}
    return normalize_feature_name(release.old_name or "") not in known


SAFETY_NET_CANDIDATES = 5
"""補漏的候選預算：相似度前五名的步驟，因此**最多五個版本、五次確認呼叫**。

這是本 Phase 選定的成本上限，不是業務門檻，也不是另一個 cosine 值——`0.85` 那條線只用在
Phase 49 的定位，補漏這一段由模型逐一確認，不再加第二個分數門檻（00A §6.9）。
"""


def _current_published(repository: Repository) -> Iterator[tuple[str, str]]:
    """每篇 active 教學的 `(slug, current 已發布 version_id)`，依 `slug` 升序。

    先濾掉 `SK != META` 再 `item_to_model`：`entity` 等於 PK 前綴（00A §3.6），同一個
    `TUTORIAL#…` 起點的關係邊也帶 `entity == "TUTORIAL"`，而邊沒有模型欄位，直接餵給
    `item_to_model` 會整筆 `ValidationError`。`scan_entity` 的 `meta_only` 預設就是 `True`，
    這層過濾與 `Repository._meta_models` 同一套防禦。

    退役教學在**這裡**被排除：補漏是「要不要多改一篇」的建議，不該把已經不維護的教學拉回來
    改版（設計 §8.1）。反查那一側沒有這層篩選，因為 `retire_tutorial` 只改 `status` 與
    `successor`，`current_version` 與 `published_at` 都保留，而 Phase 27 只看「是不是 current
    而且已發布」——兩邊的差異是刻意的：明確證據照實回報，補漏證據只補到 active 的教學上。
    """
    rows = [item for item in repository.scan_entity("TUTORIAL") if str(item["SK"]) == META]
    for tutorial in sorted((item_to_model(row, Tutorial) for row in rows),
                           key=lambda item: item.slug):
        current = tutorial.current_version
        if tutorial.status is not TutorialStatus.ACTIVE or current is None:
            continue
        version = repository.get_version(current)
        if version is not None and version.published_at is not None:
            yield tutorial.slug, current


def _release_names(release: Release) -> tuple[str, ...]:
    """這次改版涉及的名稱，固定 `feature` → `old_name` → `new_name` 並去重。

    `dict.fromkeys` 保順序去重，所以 `feature == new_name`（改名後才送進來的常見情況）不會讓
    同一個字串出現兩次；順序固定，查詢向量的輸入文字才逐次相同、`CallTrace` 也讀得懂。
    """
    parts = (release.feature, release.old_name or "", release.new_name or "")
    return tuple(dict.fromkeys(part.strip() for part in parts if part.strip()))


def _score_steps(release: Release, *, repository: Repository, writer: Writer,
                 operation_id: str) -> tuple[list[tuple[float, str, int, str]],
                                             dict[tuple[str, str], dict[int, TutorialStep]]]:
    """每個目前已發布步驟與改版名稱的相似度，排成 `(-score, slug, number, version_id)`。

    分數取負再 `sort()`，一行就得到「分數降序 → slug 升序 → number 升序 → version_id 升序」，
    同分時的勝者固定，重跑 byte 相同。**`embed` 次數與目前已發布步驟總數成正比**，而且每次
    `safety_net` 都重算（設計 §10 只允許單次執行內重用，不往 ERM 加 embedding 欄位）：每一次
    `embed` 都是一次真實 Bedrock attempt，依 F45 全部計入 `CallTrace`。
    """
    query = writer.embed(" / ".join(_release_names(release)),
                         operation_id=operation_id, node="safety_net_query")
    scored: list[tuple[float, str, int, str]] = []
    steps_by_version: dict[tuple[str, str], dict[int, TutorialStep]] = {}
    for slug, version_id in _current_published(repository):
        steps = {step.number: step for step in repository.get_steps(version_id)}
        steps_by_version[(slug, version_id)] = steps
        for number, step in sorted(steps.items()):
            vector = writer.embed(step.text, operation_id=operation_id, node="safety_net_step")
            scored.append((-cosine(query, vector), slug, number, version_id))
    scored.sort()
    return scored, steps_by_version


def safety_net(release: Release, *, repository: Repository, writer: Writer,
               operation_id: str) -> tuple[StepHit, ...]:
    """補漏路徑：步驟文字相似度取前五名候選，再依版本分組交模型逐一確認。

    回的是**補漏證據**，不是明確證據：呼叫端（Phase 52 的 `task_safety_net`）自己做
    `set(direct) | set(net)`，所以本函式**不**先跑一次 `find_release_hits`
    （**本計畫選擇（2026-09-14）**）——補漏永遠只會新增，不可能抹掉既有命中。

    每個候選版本各發一次 `generate_json`：`StepConfirmation.confirmed_step_numbers` 只有裸
    編號，兩個版本混在同一次呼叫裡就分不清誰的第 3 步。模型回不存在的編號時
    `number in steps` 直接丟棄、**不重問**（Phase 18 的對照表把 `StepConfirmation` 標為不走
    correction）；`reason` 去空白後為空是模型輸出違規，依設計 §7.4 丟 `ContentError`，不當成
    「沒有命中」降級。一個候選都沒被確認時回 `()`，由呼叫端記未命中並 KEEP（F18）。

    `inferenceConfig` 不在這裡決定：`generate_json` 用 `StepConfirmation` 這份 schema 查
    Phase 18 的 `inference_config`，判斷類固定 `maxTokens` 512、`temperature` 0.1（00A §3.7）。
    """
    scored, steps_by_version = _score_steps(
        release, repository=repository, writer=writer, operation_id=operation_id
    )
    picked: dict[tuple[str, str], list[int]] = {}
    for _, slug, number, version_id in scored[:SAFETY_NET_CANDIDATES]:
        picked.setdefault((slug, version_id), []).append(number)
    confirmed: set[StepHit] = set()
    for (slug, version_id), numbers in sorted(picked.items()):
        steps = steps_by_version[(slug, version_id)]
        system, user = prompt_safety_net_confirm(
            version_id, [steps[number] for number in sorted(numbers)], _release_names(release)
        )
        reply = writer.generate_json(system, user, StepConfirmation,
                                     operation_id=operation_id, node="safety_net_confirm")
        if not str(reply["reason"]).strip():
            raise ContentError(f"safety_net 確認缺少理由：{version_id}")
        confirmed |= {StepHit(slug, version_id, number)
                      for number in reply["confirmed_step_numbers"] if number in steps}
    return tuple(sorted(confirmed, key=lambda hit: (hit.slug, hit.number)))


# ---- Phase 51：UPDATE 精準改寫（設計 §7.4、§8.1–§8.3；REL Rule 8／10／11／13／14、APL Rule 8）----
# 交付 `REWRITE_NODE`、`assert_unchanged`、`prepare_update` 與五個 module-private helper。
# 停止點是 `tuple[VersionPlan, ...]`（依 slug 升序），每個對應一個 `published_at=None` 的私有
# 版本：**不發布、不切 `current_version`、不更新 aliases、不退役、不處理 `removed`**。

_log = logging.getLogger(__name__)
"""被跳過的教學唯一的去處；只寫 slug 與狀態，不寫教學內容或證據原文（00A §3.8）。"""

REWRITE_NODE = "release_rewrite"
"""改寫節點寫進 Phase 15 `CallTrace` 的名字；`generate_json` 的 `node=` 一律傳它（00A §6.9）。"""


def _apply_rewrite(base: TutorialContent, reply: dict[str, Any],
                   targets: frozenset[int]) -> TutorialContent:
    """把模型回的改寫套到基底上；**未命中步驟整個物件原樣帶過**（REL Rule 10、11）。

    先比對「改寫集合」與「命中集合」是否相等：多回是越界改寫、漏回是沒做完，兩種都不可
    默默放行——只驗「不多」會讓漏改的版本被當成功發布。`step_rewrite_validator`（Phase 18）
    已經擋過「編號不在命中集合」與「feature_id 不存在」，這裡再擋一次數量與 Feature 是否
    **被搬走**：改名不搬移 Feature 主鍵（D06），第 3 步改指別的 Feature 一律 `ContentError`。

    `model_copy(update=...)` 在 pydantic v2 **不做驗證**，所以 `type` 一定要先經
    `StepType(...)` 轉過再塞，否則會寫出一個 `type` 是裸字串的 `StepDraft`；不合法的值
    收斂成 `ContentError`（裸 `ValueError` 不在 00A §4.1 的錯誤契約裡）。
    """
    changed = {int(item["number"]): item for item in reply["steps"]}
    if len(changed) != len(reply["steps"]):
        raise ContentError(f"改寫集合有重複的步驟編號：{sorted(changed)}")
    if set(changed) != set(targets):
        raise ContentError(f"改寫集合 {sorted(changed)} 不等於命中集合 {sorted(targets)}")
    steps: list[StepDraft] = []
    for step in base.steps:
        item = changed.get(step.number)
        if item is None:
            steps.append(step)
            continue
        if item["feature_id"] != step.feature_id:
            raise ContentError(f"步驟 {step.number} 不可改變引用的 Feature")
        text = str(item["text"]).strip()
        if not text:
            raise ContentError(f"步驟 {step.number} 的新文字是空的")
        try:
            step_type = StepType(item["type"])
        except ValueError as error:
            raise ContentError(f"步驟 {step.number} 的 type 不合法：{item['type']!r}") from error
        steps.append(step.model_copy(update={"text": text, "type": step_type}))
    return base.model_copy(update={"steps": steps})


def assert_unchanged(base: TutorialContent, draft: TutorialContent,
                     changed: frozenset[int]) -> None:
    """命中步驟以外的一切都必須 byte-for-byte 相同，否則 `ContentError`（REL Rule 11）。

    三道檢查：四個段落（title／problem／prerequisites／expected_outcome）、步驟數量、
    以及每個未命中步驟的 `model_dump()`。比的是**物件**不是「看起來差不多」：連空白與
    標點都要一樣，否則這一版的 diff 會變成「整篇都改了」，讀者也會看到沒人審過的改動。

    `_apply_rewrite` 走完之後步驟數量必定相同，這裡仍然再驗一次：`assert_unchanged` 是
    公開介面（00A §6.9），Phase 52 也可能拿別的來源組出來的 draft 進來核對。
    """
    if (base.title, base.problem, base.prerequisites, base.expected_outcome) != (
        draft.title, draft.problem, draft.prerequisites, draft.expected_outcome
    ):
        raise ContentError("UPDATE 不可改動命中步驟以外的段落")
    if len(base.steps) != len(draft.steps):
        raise ContentError(f"步驟數量由 {len(base.steps)} 變成 {len(draft.steps)}")
    for left, right in zip(base.steps, draft.steps, strict=True):
        if left.number not in changed and left.model_dump() != right.model_dump():
            raise ContentError(f"未命中步驟 {left.number} 的原文必須逐字相同")


def _rules_for_hits(base: TutorialContent, targets: frozenset[int], *,
                    repository: Repository) -> list[AuthoringRule]:
    """本次要注入的 active 規則：**只看命中步驟的 `type`**（F29、APL Rule 8）。

    未命中步驟的原文是複製過來的，沿用原文不算本次套用，所以第 1 步就算同樣是
    `click_ui`，也不會讓 `R-007` 進 `rules_applied`。`rules_for_content`（Phase 19）每個
    `step_type` 最多回一條；這裡照 `step_types` 的**出現順序**遍歷並用 `seen` 去重，
    注入順序與 `applied_rule_ids` 的順序因此完全一致（prompt 與版本紀錄不分叉）。

    驗證時間一律走 `analytics/status_writer.load_validated_at(repository)`（00A D-28），
    本模組**沒有**第二份 `_load_validated_at`；缺值時 Phase 19 丟 `PermanentError`，
    這裡不補預設時間。candidate 與 retired 由 `list_rules(RuleStatus.ACTIVE)` 擋在門外。
    """
    step_types = [step.type for step in base.steps if step.number in targets]
    by_type = rules_for_content(repository.list_rules(RuleStatus.ACTIVE), step_types,
                                load_validated_at(repository))
    selected: list[AuthoringRule] = []
    seen: set[str] = set()
    for step_type in step_types:
        for item in by_type[step_type]:
            if item.rule_id not in seen:
                seen.add(item.rule_id)
                selected.append(item)
    return selected


def _sub_operation(release: Release, slug: str, *, operations: OperationCoordinator,
                   operation_id: str) -> str:
    """每篇教學各一筆子 operation；`allocate_version` 以 `operation_id` 為唯一鍵（D-59）。

    `OperationRecord.version_id` 是**單值**，一個 Release 命中兩篇教學時共用父 operation 會
    互相搶同一個版號，所以固定用 `operation_id_for("release-update", f"{release.id}--{slug}")`
    ——兩個連字號當分隔，slug 裡本來就有的單一連字號才不會造成混淆。同一個 Release 重送時
    `sub_id` 逐字相同，`accept` 回 `duplicate`，版號沿用原本那一個。

    `project_id` 沿用**父** operation 紀錄上的值（`Release` 模型沒有 `project_id` 欄位，
    不在這裡另外讀 `Settings`）；父 operation 讀不到代表呼叫端沒有先經 O2 接受，那是協調
    錯誤而不是內容錯誤，一律 `CoordinationError`。
    """
    parent = operations.load(operation_id)
    if parent is None:
        raise CoordinationError(f"{operation_id} 尚未被 O2 接受")
    canonical_id = f"{release.id}--{slug}"
    sub_id = operation_id_for("release-update", canonical_id)
    operations.accept(AcceptOperation(operation_id=sub_id, kind="release-update",
                                      canonical_id=canonical_id,
                                      project_id=parent.project_id, now=now_utc()))
    return sub_id


def _rewrite_once(release: Release, base: TutorialContent, slug: str, targets: frozenset[int],
                  rules: Sequence[AuthoringRule], *, repository: Repository, writer: Writer,
                  operations: OperationCoordinator, operation_id: str) -> dict[str, Any]:
    """整個流程裡**唯一**呼叫模型的地方；重送先讀回既有輸出（設計 §14.2、F45）。

    模型輸出的 ref 是 **per-slug** 的 `operations/<父 operation_id>/rewrite-<slug>.json`，
    不是 `model_output_refs[-1]`：一個 `operation_id` 可能命中多篇教學，用 `[-1]` 會分不清
    是誰的輸出（**本計畫選擇（2026-09-14）**）。ref 掛在**父** operation 底下，因為它本來
    就已經 per-slug、兩篇不會互相覆蓋；只有版號分配走子 operation（D-59）。

    `put_object(..., if_none_match=True)` 在併發重送會丟 `ObjectAlreadyExists`
    （`PermanentError` 子類）；本 Phase **不吞它**，讓 ASL 的 Catch 收——正常重送已經被
    上面那次 `get_object` 涵蓋，會撞到就代表兩個執行同時在改同一篇，那本來就該停。

    `inferenceConfig` 不在這裡決定：`generate_json` 用 `StepRewrite` 這份 schema 查
    Phase 18 的 `inference_config`，`temperature` 固定 0.1、截斷（`stopReason ==
    "max_tokens"`）由 Phase 15 判成 `PermanentError`，不靠調高上限救（00A §3.7）。
    """
    ref = operation_ref(operation_id, f"rewrite-{slug}")
    saved = repository.get_object(ref)
    if saved is not None:
        replayed: dict[str, Any] = json.loads(saved.decode("utf-8"))
        return replayed
    system, user = prompt_release_rewrite(release, base, sorted(targets),
                                          render_rules_block(rules))
    validate = step_rewrite_validator(
        allowed_steps=frozenset(targets),
        allowed_features=frozenset(step.feature_id for step in base.steps))
    reply = writer.generate_json(system, user, StepRewrite,
                                 operation_id=operation_id, node=REWRITE_NODE)
    validate(reply)
    body = json.dumps(reply, ensure_ascii=False, sort_keys=True).encode("utf-8")
    repository.put_object(ref, body, "application/json", if_none_match=True)
    operations.record_model_output(operation_id, ref)
    return reply


def _prepare_one(release: Release, tutorial: Tutorial, targets: frozenset[int], *,
                 repository: Repository, writer: Writer, operations: OperationCoordinator,
                 operation_id: str) -> VersionPlan:
    """一篇教學的完整改版順序；每一步的先後都有理由，不可對調。

    ```text
    子 operation -> 基底全文 -> 選規則 -> 配版號 -> 模型 -> 程式核對 -> create_version -> verify
    ```

    **規則選取排在 `allocate_version` 之前**：Phase 19 要求 prompt 與 `rules_applied` 用
    同一份 selected list，而 `allocate_version` 的參數就包含 `rules_applied`（本計畫選擇，
    Phase 46 的 REFINE 採同一順序）。基底是**最近已發布版本**（`current_version`）的 S3
    原文，不是最新版本，也不是模型重新生成的全文——否則 diff 會變成整篇差異。

    `tutorial` 由 `prepare_update` 讀好傳進來（狀態過濾在那一層做），這裡不再讀一次表。
    `known_feature_ids` 用 `scan_entity("FEATURE")` 配 `item_to_model`（00A D-29、§3.6）；
    `verify_version_complete` 回 `False` 代表關係不完整，依 F36 不得發布，這裡就停住。
    """
    slug = tutorial.slug
    if tutorial.current_version is None:
        raise ContentError(f"{slug} 沒有已發布版本可以當基底")
    sub_id = _sub_operation(release, slug, operations=operations, operation_id=operation_id)
    base_version = repository.get_version(tutorial.current_version)
    if base_version is None:
        raise ContentError(f"找不到 {slug} 的基底版本 {tutorial.current_version}")
    body = repository.get_object(base_version.s3_key)
    if body is None:
        raise ContentError(f"{base_version.version_id} 缺少 S3 全文 {base_version.s3_key}")
    base = parse_markdown(body.decode("utf-8"))
    rules = _rules_for_hits(base, targets, repository=repository)
    plan = allocate_version(slug, sub_id, operations, repository=repository,
                            reason=f"release:{release.id}",
                            rules_applied=applied_rule_ids(rules))
    reply = _rewrite_once(release, base, slug, targets, rules, repository=repository,
                          writer=writer, operations=operations, operation_id=operation_id)
    draft = _apply_rewrite(base, reply, targets)
    assert_unchanged(base, draft, targets)
    known = frozenset(item_to_model(row, Feature).feature_id
                      for row in repository.scan_entity("FEATURE"))
    validate_content(draft, known)
    create_version(plan, draft, repository)
    if not verify_version_complete(plan.version_id, repository):
        raise ContentError(f"{plan.version_id} 的關係不完整")
    return plan


def prepare_update(release: Release, hits: Sequence[StepHit], *, repository: Repository,
                   writer: Writer, operations: OperationCoordinator,
                   operation_id: str) -> tuple[VersionPlan, ...]:
    """對每一篇命中的教學只重寫命中步驟，回一整組**未發布**版本（依 `slug` 升序）。

    入口只接受 `renamed` 與 `changed`（REL Rule 8）：`removed` 走 Phase 52 的退役路徑，
    誤接進來是呼叫端接錯線，`PermanentError` 讓 ASL 的 Catch 導向失敗終點。`hits` 為空時
    回 `()`，呼叫端 KEEP。

    **退役教學一律跳過。** `find_release_hits`（Phase 50）用的 Phase 27 反查只看「是不是
    current 而且已發布」，不看 `Tutorial.status`（D-38 也禁止包裝層自己再篩一次），所以
    退役教學**會**出現在 `hits` 裡。UPDATE 不得替退役教學建新版（設計 §8.1：退役的教學
    不再維護），因此過濾放在這一層：跳過並寫一行 log 說明原因，不丟例外——那是別篇教學
    的正常結果，不該讓整次改版失敗（**本計畫選擇（2026-09-14）**，controller 2026-09-14
    裁決）。

    每篇先取 `TUTORIAL#<slug>` 的租約（`LEASE#` 前綴由 Phase 11 自己補）再串行處理；拿不到
    就 `TransientError` 交 ASL 有限重試，**不自行迴圈等待**——租約不是接受順序的保證，TTL
    也不是準時解鎖，真正的順序保證仍屬 O2。`try/finally` 讓 `ContentError` 也會歸還租約，
    否則同一篇要等 `LEASE_TTL_SECONDS` 才解得開。`prepare_update` 的簽名沒有 `now`，所以
    到期時間由函式內部的 `now_utc()` 決定（租約是執行資訊，`published_at` 仍由 Phase 24 的
    `now` 決定）。

    多篇時回一整組 `VersionPlan`，呼叫端（Phase 52）把整組 `version_id` 包成**一個**
    `PublishRequest` 交給 Phase 25：第二篇 inspect 失敗時第一篇也不得被發布（F49）。
    本函式沒有任何 publish 呼叫，也不碰 `current_version` 與 aliases。
    """
    if release.kind not in (ReleaseKind.RENAMED, ReleaseKind.CHANGED):
        raise PermanentError(f"UPDATE 只處理 renamed 與 changed，收到 {release.kind}")
    by_slug: dict[str, set[int]] = {}
    for hit in hits:
        by_slug.setdefault(hit.slug, set()).add(hit.number)
    plans: list[VersionPlan] = []
    for slug in sorted(by_slug):
        tutorial = repository.get_tutorial(slug)
        if tutorial is None:
            raise ContentError(f"找不到教學：{slug}")
        if tutorial.status is not TutorialStatus.ACTIVE:
            _log.info("release update skipped retired tutorial slug=%s status=%s release=%s",
                      slug, tutorial.status.value, release.id)
            continue
        scope = f"TUTORIAL#{slug}"
        if not operations.acquire_lease(scope, operation_id,
                                        ttl_seconds=LEASE_TTL_SECONDS, now=now_utc()):
            raise TransientError(f"{slug} 正由另一個操作改寫，稍後重試")
        try:
            plans.append(_prepare_one(release, tutorial, frozenset(by_slug[slug]),
                                      repository=repository, writer=writer,
                                      operations=operations, operation_id=operation_id))
        finally:
            operations.release_lease(scope, operation_id)
    return tuple(plans)
