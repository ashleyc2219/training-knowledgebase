"""Release Update pipeline（`release-update`）。

Owner：Phase 49（Feature 定位與 alias）；Phase 50（步驟反查與 Safety Net）、51（UPDATE 精準改寫）、
52（RETIRE 與 handler）在同一支檔各自追加。00A §3.2。

controller 2026-09-14 預建空殼：讓同一波次的 Phase 只用 Edit 追加各自區段。
"""

from collections.abc import Sequence
from dataclasses import dataclass

from training_kb.config import Thresholds
from training_kb.content import parse_version_id
from training_kb.errors import PermanentError
from training_kb.keys import META, feature_pk
from training_kb.models import Feature, Release, ReleaseKind
from training_kb.repository import DynamoValue, Repository, item_to_model
from training_kb.vectors import cosine
from training_kb.writing.client import Writer

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
