# Phase 40：Ticket CREATE 與 KEEP 實作計畫

> **給實作者：** 依 checkbox 逐步執行；每個 Task 先建立失敗測試，再寫最小實作。執行時使用 `superpowers:executing-plans` 或同等逐項流程。

**目標：** 由已命名的 Knowledge Gap 決定 CREATE、KEEP 或 NO_FEATURE，並在 CREATE 時建立教學身分與一個**未發布**的 v1。

**架構：** `decide_ticket_action` 是純判斷，只讀 Feature 與 Tutorial 狀態；`create_first_version` 把 Phase 19 規則注入、Phase 17 草稿 schema、Phase 21 內容驗證、Phase 20 版號分配與 Phase 23 寫入串成固定順序。slug 由程式產生與驗證，模型不產任何穩定 ID。

**技術：** Python 3.12、Pydantic v2、pytest、Phase 19 規則選取、Phase 20–23 版本模組、Phase 27 `find_active_tutorial_for_feature`。

## 全域限制

- 唯一主來源是 [Training KB 設計 §7.3、§7.6、§8.1、§8.2](../../design/training-kb.md)。
- 前置為 [Phase 39：Recurring 與 Knowledge Gap 命名](./39-Phase39-Recurring與Knowledge-Gap命名.md)，以及 [Phase 20](./20-Phase20-版本分配與重試重用.md)、[Phase 21](./21-Phase21-教學內容與步驟引用驗證.md)、[Phase 23](./23-Phase23-未發布版本與關係完整寫入.md)。任一未通過時停止。
- 下一階段是 [Phase 41：Ticket Analysis 雲端流程驗收](./41-Phase41-Ticket-Analysis雲端流程驗收.md)。
- 本階段不做：不發布、不切 `current_version`、不建立 Feature、不改既有教學文字、不處理 Release 或 Feedback 的改版。
- 只有 Ticket Analysis 能建立新的 Tutorial 身分；Release Update 與 Feedback Review 只能在既有教學上長版本。KEEP 只留原因紀錄，一個字都不寫進教學內容；NO_FEATURE 保留 gap，不補建 Feature。
- 本 Phase 是 `Ticket.feature_ids` 與 `ASKS_ABOUT` 邊的**唯一寫入者**（00A D-52）：只有 CREATE 與 KEEP 兩種結果才寫，每張工單最多一個 Feature（D04）；`NO_FEATURE` 兩者都不寫。
- 與本 Phase 有關的 gate：O3 未通過時只驗收到「未發布 v1」，不得宣稱公開發布可用；O5 未通過時 Claude 呼叫維持 BLOCKED。以下程式檔均是實作時預計建立或修改，本計畫不代表它們已存在。

---

## 1. 你在整體流程的位置

```text
Phase 39 name_gap 回的 dict：{"gap": ..., "feature_id": ... 或 None}
                |
   [你在這裡] decide_ticket_action
                |
   +------------+-------------+--------------+
   | NO_FEATURE | KEEP        | CREATE       |
   v            v             v
 保留 gap    記原因 log   [你在這裡] create_first_version
 不建 Feature 連工單到       |
 不連工單     Feature        |
                    Phase 19 規則 -> TutorialDraft -> Phase 21 驗證
                              |
                    Phase 20 版號 -> Phase 23 寫入未發布 v1
                              |
                    Phase 41 再交 Publisher（受 O3 gate 控管）
```

## 2. 完成後看得到什麼

輸入 `TicketGap(cluster_id="c12", gap="找不到會前摘要入口", feature_id="Prepare", ticket_ids=(...))`。

```text
Feature Prepare 沒有 active 教學 -> decide_ticket_action = "CREATE"
tutorial_slug              -> "prepare-meeting"
TUTORIAL#prepare-meeting   -> status=active, current_version=None, cluster_id="c12",
                              feature_ids=["Prepare"], successor=None
VERSION#prepare-meeting@v1 -> reason="gap:c12", published_at=None
TICKET#t_881               -> feature_ids=["Prepare"]
TICKET#t_881 的邊           -> SK="ASKS_ABOUT#FEATURE#Prepare"
```

把 `Prepare` 改成「已有一篇 `status=active` 但 `current_version=None` 的教學」：結果是 `KEEP`，沒有任何 TUTORIAL／VERSION 被寫入，但工單仍會連到 `Prepare`。把那篇改成 `retired`：回到 `CREATE`。把 `feature_id` 改成 `None`：`NO_FEATURE`，連工單都不動，只留下 `ticket-decision.json`。

## 3. 名詞小抄

| 名詞 | 白話意思 |
|---|---|
| CREATE／KEEP／NO_FEATURE | 這輪的三種結果：建新教學、什麼都不改、缺有效 Feature 先擱著。 |
| Tutorial 身分 | `TUTORIAL#<slug>` 這筆 metadata，代表「有這一篇教學」；和版本是兩件事。 |
| slug | 教學的英文短代號，例如 `prepare-meeting`；只能是小寫字母數字與單一連字號。 |
| 未發布版本 | `published_at` 是 `null`；資料齊全但外面讀不到。`reason` 則說明這一版為什麼產生，第一版固定是 `gap:<cluster_id>`。 |
| `ASKS_ABOUT` 邊 | 「這張工單在問這個功能」的關聯 item，起點是 `TICKET#<id>`、終點是 `FEATURE#<id>`，每張工單最多一條。 |
| `Fnn`／`Dnn`／`D-nn` | 前兩種是[設計文件](../../design/training-kb.md) §19 的功能／資料決策編號（如 F12、D04）；`D-nn` 是 [00A](00A-共用契約與名詞.md) §8 的跨 Phase 裁決編號（如 D-52）。 |

## 4. 預計檔案

| 動作 | 路徑 | 責任 |
|---|---|---|
| 修改 | `src/training_kb/pipelines/ticket.py` | 判斷、slug、身分、建版與工單連結函式。 |
| 修改 | `src/training_kb/writing/prompts.py` | `prompt_write_tutorial` 由 Phase 17 建立，本 Phase 只在證據組法變動時調整。 |
| 新增 | `src/training_kb/analytics/status_writer.py` | 只放讀取端 `VALIDATED_AT_KEY` 與 `load_validated_at`；寫入端 `apply_rule_status` 由 Phase 55 補（00A D-28）。 |
| 測試 | `tests/unit/pipelines/test_ticket_decide.py` | 三種結果、active 未發布、retired 不阻擋、`ASKS_ABOUT` 連結。 |
| 測試 | `tests/unit/pipelines/test_ticket_create_v1.py` | slug、五段內容、`gap:<cluster_id>`、未發布。 |
| 測試 | `tests/unit/pipelines/test_tutorial_identity_owner.py` | 只有 ticket pipeline 能建立 Tutorial 身分。 |

## 5. 固定介面

### Consumes

```text
to_iso(dt: datetime) -> str；ContentError / PermanentError                   # Phase 02
TutorialContent / StepDraft / StepType / TutorialStatus / RuleStatus         # Phase 03
Tutorial(slug, current_version, topic, feature_ids, status, successor, cluster_id)；Ticket   # Phase 04
ticket_pk(ticket_id) -> str；feature_pk(feature_id) -> str                   # Phase 05
Repository.get_tutorial(slug) / get_feature(feature_id) / get_meta(pk, model, *, consistent=True)  # Phase 06
Repository.put_meta(entity, *, create_only=True) -> None                     # Phase 06
Repository.put_object(key, body, content_type, *, if_none_match) -> None     # Phase 07
Repository.put_edge(pk, relation, target_pk, attrs=None) -> None             # Phase 07
Repository.list_rules(status: RuleStatus | None = None) -> list[AuthoringRule]   # Phase 08
operation_ref(operation_id, name) -> str                                     # Phase 10
Writer.generate_json(system: str, user: str, schema: Mapping[str, Any], *,
                     operation_id: str, node: str) -> dict[str, Any]         # Phase 15
prompt_write_tutorial(source_text: str, allowed_features: Sequence[str],
                      rules_block: str) -> tuple[str, str]                   # Phase 17
TutorialDraft: dict[str, object]                                             # Phase 17 的 JSON schema 常數
rules_for_content(rules, step_types, validated_at_by_rule) -> dict[StepType, list[AuthoringRule]]
render_rules_block(rules) -> str；applied_rule_ids(rules) -> list[str]       # Phase 19
allocate_version(tutorial_id, operation_id, operations, *, repository,
                 reason, rules_applied) -> VersionPlan                       # Phase 20
validate_content(content, known_feature_ids: frozenset[str]) -> None         # Phase 21
create_version(plan, content, repository) -> TutorialVersion                 # Phase 23
Repository.find_active_tutorial_for_feature(feature_id) -> Tutorial | None   # Phase 27
known_features(repository) -> tuple[Feature, ...]                            # Phase 39
load_validated_at(repository) -> dict[str, datetime]                         # 讀取端由本 Phase 首建（見下方說明）
```

### Produces

```python
from datetime import datetime
from typing import Literal

TicketAction = Literal["CREATE", "KEEP", "NO_FEATURE"]
ALL_STEP_TYPES: tuple["StepType", ...] = tuple(StepType)   # 宣告順序：click_ui、input、read

@dataclass(frozen=True)
class TicketGap:
    cluster_id: str
    gap: str
    feature_id: str | None
    ticket_ids: tuple[str, ...]

def decide_ticket_action(gap: TicketGap, *, repository: "Repository") -> TicketAction: ...

def record_decision(action: TicketAction, gap: TicketGap, *, repository: "Repository",
                    operation_id: str, now: datetime) -> str: ...

def tutorial_slug(gap: TicketGap, title: str, *, repository: "Repository") -> str: ...

def create_tutorial_identity(gap: TicketGap, *, slug: str, topic: str,
                             repository: "Repository") -> "Tutorial": ...

def create_first_version(gap: TicketGap, *, repository: "Repository", writer: "Writer",
                         operations: "OperationCoordinator", operation_id: str,
                         now: datetime) -> "VersionPlan": ...
```

`TicketGap` 由 Phase 41 的 `DecideAction` Task 用 `cluster_id` 加 Phase 39 `name_gap` 回的 dict（`naming["gap"]`、`naming["feature_id"]`）與同群 `Ticket.id` 組出來。`record_decision` 回傳私有 ref `operations/<operation_id>/ticket-decision.json`，三種結果都要寫，這就是 Rule 8 的「只記錄 log」；`action` 不是 `NO_FEATURE` 時，它同時把 `gap.ticket_ids` 的每張工單連到 Feature（00A D-52），那是工單側的標註，不是教學內容。

`TutorialDraft` 和 Phase 39 的 `GapNaming` 一樣是 **JSON schema 字典**，不是 pydantic 類別：`generate_json` 吃它、回一個普通 `dict`，呼叫端自己 `TutorialContent.model_validate(...)`（00A D-02）。`load_validated_at` 讀的是單一私有檔 `operations/rules/validated_at.json`（常數 `VALIDATED_AT_KEY`，00A D-28）。**讀取端（`VALIDATED_AT_KEY` 與 `load_validated_at`）由本 Phase 首建**在 `src/training_kb/analytics/status_writer.py`（§4 的預計檔案表已列為「新增」）；**寫入端 `apply_rule_status` 才是 [Phase 55](./55-Phase55-規則驗證與狀態轉移.md) 的**，補在同一支檔案上。Phase 19 已規定「缺驗證時間就丟 `PermanentError`，不可當最早或現在時間」，本 Phase 只負責讀出來傳進去。Phase 55 之前這個檔不存在（`load_validated_at` 回 `{}`），也不會有任何 active 規則（轉 active 的唯一入口就是 Phase 55），`rules_applied` 因此是 `[]`，屬於正常狀態。兩邊共用同一個常數與同一份讀取邏輯，不得在 `pipelines/ticket.py` 另複製一份。

## 6. 設計細節

判斷順序固定如下；注意「有沒有教學」看的是 `status`，不是 `current_version`。

```text
  gap.feature_id 是 None？ -- 是 --> NO_FEATURE（保留 gap，不建 Feature）
            | 否
  get_feature 找得到？ -- 否 --> ContentError（資料不一致，不猜）
            | 是
  find_active_tutorial_for_feature 有 status=active 的教學？
            |                              |
            | 是（即使 current_version=None）| 否（含只有 retired）
            v                              v
          KEEP                           CREATE
```

決策 F12（設計 §19.2 功能決策編號）明說 active 但尚待首次發布也算「已有教學」，避免同一功能被建兩篇；retired 不算，所以退役後遇到同樣的重複工單可以重新建立。`find_active_tutorial_for_feature`（Phase 27）是用 `feature_id in Tutorial.feature_ids` 找的，所以 `create_tutorial_identity` **必須**把 `feature_ids=[gap.feature_id]` 寫進去，否則下一輪同群工單會再建一篇。

`create_first_version` 的順序則不可調換：

```text
1. 再判一次 decide_ticket_action -> 不是 CREATE 就 PermanentError
2. list_rules(ACTIVE) + load_validated_at -> rules_for_content -> 去重後的 injected 清單
3. render_rules_block(injected) 進 prompt -> generate_json(TutorialDraft) -> dict
4. TutorialContent.model_validate(dict) + validate_content（五段齊全、每步恰一個既有 Feature）
5. tutorial_slug 產生並驗證 kebab-case 與唯一
6. create_tutorial_identity（create_only=True、feature_ids=[feature_id]；重試沿用同一篇）
7. allocate_version(reason="gap:<cluster_id>", rules_applied=applied_rule_ids)
8. create_version -> published_at 仍是 null
9. record_decision("CREATE", ...) -> 寫決策紀錄並連工單到 Feature
```

先驗內容再建身分，是為了避免模型輸出不合法時仍留下一個空的 `TUTORIAL#` item。步驟 7 的 `rules_applied` 只放**本次實際注入 prompt** 的 ID；沿用原文不算套用（F29）。步驟 2 的規則選取是純函式，`list_rules` 與 `load_validated_at` 都由本 Phase 先讀好再傳進 Phase 19（Phase 19 §5 已如此約定）。`record_decision` 的兩件事都必須可重跑：`ticket-decision.json` 用 `if_none_match=False` 覆寫；連結則先一致讀回 `TICKET#<id>`，`feature_ids` 已等於 `[feature_id]` 就跳過，否則 `put_meta(create_only=False)` 覆寫成單一元素，再 `put_edge(ticket_pk(id), "ASKS_ABOUT", feature_pk(feature_id))`。邊的 `SK` 固定是 `ASKS_ABOUT#FEATURE#<id>`，重寫同一條不會多出 item，所以 Phase 41 的 `DecideAction` Task 與 `create_first_version` 各呼叫一次也安全。

slug 規則：先把 `content.title` 轉成 ASCII kebab-case，轉不出東西時退回 `feature_id`，再退回 `gap-<cluster_id>`；若該 slug 已被**別群**佔用，固定改用 `<base>-<cluster_id>`，仍衝突就丟 `ContentError`。這個退讓是固定的，所以同一個 operation 重試會得到同一個 slug，不會像「遞增 -2、-3」那樣每次換一個。`ALL_STEP_TYPES` 直接由 `tuple(StepType)` 取得，不重打一份字串清單，才不會跟 Phase 03 的列舉成員拼法分岔。模組私有的 `_evidence_text(gap, repository)` 只讀 `gap.ticket_ids` 指定的工單文字，連同 `gap.gap` 串成**一個字串**，交給 Phase 17 的 `prompt_write_tutorial(source_text, allowed_features, rules_block)`；三個參數的順序與型別由 Phase 17 固定，不可改成傳 `Feature` 物件或多一個參數。`allowed_features` 只放裸 `feature_id`，模型只能從這份白名單挑，別群的工單文字不會進 prompt。工單文字是不可信資料，`prompt_write_tutorial` 內部一律用 Phase 17 的 `_as_data`（`html.escape(text, quote=False)`）把 `source_text` 包進 `<source_data>` 分區當資料、不當指令（00A D-67）；本 Phase 只負責挑對證據，不另建轉義或分區標記。

**本計畫選擇：** 規則的「最近驗證時間」放在單一私有檔 `operations/rules/validated_at.json`，由 Phase 55 的 `apply_rule_status` 唯一寫入、本 Phase 首建的 `load_validated_at(repository)` 讀取（00A D-28：同一支 `analytics/status_writer.py`，讀取端 P40、寫入端 P55）；`AuthoringRule` 沒有 `validated_at` 欄位，不得為了方便在 RULE item 上加一個（00A D-40：item 屬性 = 模型欄位 + `RESERVED_ATTRS`，沒有第三類）。沒有任何 active 規則時這份 mapping 是空的，`rules_for_content` 回空集合、`rules_applied` 就是 `[]`，這是正常狀態，不可為了湊資料把 candidate 放進來。

## 7. TDD Tasks

### Task 1：三種結果與 active／retired 邊界

- [ ] **Step 1：建立失敗測試**

`replace` 是 `dataclasses.replace`、`dt(value)` 是包一層 Phase 02 `parse_iso` 的 helper；`fake_repo` 是同檔 fixture，用 dict 當表並提供 `save_feature`／`save_tutorial`／`save_ticket`／`save_rule`／`save_validated_at_file`／`edges`／`writes` 與 Phase 06–08、27 的讀寫原語；`fake_ops` 必須實作 Phase 10 的 `load`／`record_version`／`record_model_output`（`allocate_version` 在 `load` 回 `None` 時會丟 `CoordinationError`，所以 fixture 要先放一筆 accepted 紀錄）；`fake_writer` 與 [Phase 39](./39-Phase39-Recurring與Knowledge-Gap命名.md) 的同名 double 形狀相同（記下每次 `generate_json` 的 `(system, user, schema, node)` 到 `calls`、回 `self.reply`），也是**測試檔自備**，不是 [Phase 15](./15-Phase15-Writing介面與呼叫追蹤.md) `tests/unit/conftest.py` 的那個共用 `fake_writer`。四者都放在測試檔的 fixture 區。

```python
GAP = TicketGap(cluster_id="c12", gap="找不到會前摘要入口", feature_id="Prepare", ticket_ids=("t_881",))


@pytest.mark.parametrize(
    ("status", "current", "expected"),
    [("active", None, "KEEP"), ("active", "prepare-meeting@v1", "KEEP"),
     ("retired", "prepare-meeting@v1", "CREATE")],
)
def test_only_active_status_blocks_create(fake_repo, status, current, expected):
    fake_repo.save_feature("Prepare")
    fake_repo.save_tutorial("prepare-meeting", feature_id="Prepare", status=status, current_version=current)
    assert decide_ticket_action(GAP, repository=fake_repo) == expected


def test_missing_feature_returns_no_feature(fake_repo):
    assert decide_ticket_action(replace(GAP, feature_id=None), repository=fake_repo) == "NO_FEATURE"
    assert fake_repo.writes == []


@pytest.mark.parametrize(("action", "linked"), [("KEEP", ["Prepare"]), ("NO_FEATURE", [])])
def test_record_decision_links_tickets_only_when_feature_is_valid(fake_repo, fake_ops, action, linked):
    fake_repo.save_feature("Prepare")
    fake_repo.save_ticket("t_881", cluster="c12")
    gap = GAP if action == "KEEP" else replace(GAP, feature_id=None)

    ref = record_decision(action, gap, repository=fake_repo,
                          operation_id="op-1", now=dt("2026-09-13T02:05:00Z"))

    assert ref == "operations/op-1/ticket-decision.json"
    assert fake_repo.get_meta("TICKET#t_881", Ticket).feature_ids == linked
    assert fake_repo.edges("TICKET#t_881", "ASKS_ABOUT") == (
        ["FEATURE#Prepare"] if linked else [])
```

- [ ] **Step 2：執行 `uv run pytest tests/unit/pipelines/test_ticket_decide.py -q` 確認紅燈**

預期 FAIL，訊號包含 `cannot import name 'decide_ticket_action'`。

- [ ] **Step 3：建立最小實作**

```python
def decide_ticket_action(gap, *, repository):
    if gap.feature_id is None:
        return "NO_FEATURE"
    if repository.get_feature(gap.feature_id) is None:
        raise ContentError(f"Feature {gap.feature_id} 不存在")
    existing = repository.find_active_tutorial_for_feature(gap.feature_id)
    return "KEEP" if existing is not None else "CREATE"


def record_decision(action, gap, *, repository, operation_id, now):
    ref = operation_ref(operation_id, "ticket-decision")
    record = {"action": action, "cluster_id": gap.cluster_id, "gap": gap.gap,
              "feature_id": gap.feature_id, "ticket_ids": list(gap.ticket_ids),
              "decided_at": to_iso(now)}
    body = json.dumps(record, ensure_ascii=False, sort_keys=True).encode("utf-8")
    repository.put_object(ref, body, "application/json", if_none_match=False)
    if action != "NO_FEATURE":
        _link_tickets(gap, repository=repository)      # D-52：只有有效 Feature 才連
    return ref


def _link_tickets(gap, *, repository):
    for ticket_id in gap.ticket_ids:
        ticket = repository.get_meta(ticket_pk(ticket_id), Ticket)
        if ticket is None:
            raise ContentError(f"工單 {ticket_id} 不存在，無法連到 Feature")
        if ticket.feature_ids != [gap.feature_id]:     # 最多一個元素（D04）
            repository.put_meta(ticket.model_copy(update={"feature_ids": [gap.feature_id]}),
                                create_only=False)
        repository.put_edge(ticket_pk(ticket_id), "ASKS_ABOUT", feature_pk(gap.feature_id))
```

- [ ] **Step 4：補 KEEP 不寫內容的測試後跑綠並提交**

KEEP 與 NO_FEATURE 兩條路徑都要斷言：沒有新的 `TUTORIAL#`／`VERSION#`／`STEP#` item，既有教學的 `current_version` 與全文完全沒變，而 `ticket-decision.json` 有可讀的 `action` 與 `gap`。再補一個重跑案例：同一個 `operation_id` 連呼叫兩次 `record_decision`，`ASKS_ABOUT` 邊仍只有一條、`feature_ids` 仍只有一個元素。執行 `uv run pytest tests/unit/pipelines/test_ticket_decide.py -q` 後 `git add src/training_kb/pipelines/ticket.py tests/unit/pipelines/test_ticket_decide.py` 並 `git commit -m "feat(ticket): 判斷 CREATE 與 KEEP"`。

### Task 2：slug 由程式決定，且只有 ticket pipeline 能建身分

- [ ] **Step 1：建立失敗測試**

```python
import inspect


def test_slug_is_kebab_case_and_stable_across_retries(fake_repo):
    assert tutorial_slug(GAP, "Prepare Meeting", repository=fake_repo) == "prepare-meeting"
    assert tutorial_slug(GAP, "  Prepare--Meeting  ", repository=fake_repo) == "prepare-meeting"
    assert tutorial_slug(GAP, "準備會議", repository=fake_repo) == "prepare"      # 退回 feature_id
    fake_repo.save_tutorial("prepare-meeting", feature_id="Other", cluster_id="c99")
    assert tutorial_slug(GAP, "Prepare Meeting", repository=fake_repo) == "prepare-meeting-c12"


def test_only_ticket_pipeline_creates_tutorial_identity():
    from training_kb.pipelines import feedback, release, ticket

    assert hasattr(ticket, "create_tutorial_identity")
    for module in (release, feedback):
        source = inspect.getsource(module)
        assert "create_tutorial_identity" not in source and "Tutorial(" not in source
```

- [ ] **Step 2：執行 `uv run pytest tests/unit/pipelines/test_ticket_create_v1.py tests/unit/pipelines/test_tutorial_identity_owner.py -q` 確認紅燈**

預期 FAIL，訊號包含 `cannot import name 'tutorial_slug'`。

- [ ] **Step 3：建立最小實作**

```python
_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def _kebab(raw):
    folded = unicodedata.normalize("NFKD", raw or "").encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "-", folded.lower()).strip("-")[:60].strip("-")


def tutorial_slug(gap, title, *, repository):   # 模型不產 ID，slug 一律由這裡決定
    base = _kebab(title) or _kebab(gap.feature_id or "") or _kebab(f"gap-{gap.cluster_id}")
    if not _SLUG_RE.fullmatch(base):
        raise ContentError(f"slug 必須是 ASCII kebab-case：{base!r}")
    for candidate in (base, f"{base}-{gap.cluster_id}"):
        owner = repository.get_tutorial(candidate)
        if owner is None or owner.cluster_id == gap.cluster_id:
            return candidate
    raise ContentError(f"slug {base} 已被其他群佔用")


def create_tutorial_identity(gap, *, slug, topic, repository):
    existing = repository.get_tutorial(slug)
    if existing is not None:                     # 同一群重試：沿用既有那一篇，不重寫
        if existing.cluster_id != gap.cluster_id:
            raise ContentError(f"教學 {slug} 屬於別群 {existing.cluster_id}")
        return existing
    tutorial = Tutorial(slug=slug, topic=topic, status=TutorialStatus.ACTIVE,
                        current_version=None, feature_ids=[gap.feature_id],
                        successor=None, cluster_id=gap.cluster_id)
    repository.put_meta(tutorial, create_only=True)   # 併發撞鍵 -> CoordinationError
    return tutorial
```

`Tutorial` 的七個欄位就是模型的全部，不得多塞第八個（00A D-40）。先 `get_tutorial` 再 `put_meta(create_only=True)` 是刻意的：重試時直接回既有那一篇，只有真正併發撞鍵才會讓 `put_meta` 丟 `CoordinationError`。

- [ ] **Step 4：補身分建立測試後跑綠並提交**

斷言同群重試回同一篇且 `repository` 沒有第二次寫入、別群佔用時丟 `ContentError`、item 屬性只有模型七個欄位加 `RESERVED_ATTRS`。再直接斷言 `find_active_tutorial_for_feature("Prepare").slug == "prepare-meeting"`，證明下一輪同群工單會走 KEEP。執行同一組測試後 `git add src/training_kb/pipelines/ticket.py tests/unit/pipelines/test_ticket_create_v1.py tests/unit/pipelines/test_tutorial_identity_owner.py` 並 `git commit -m "feat(ticket): 建立教學身分與 slug"`。

### Task 3：建立未發布的第一版

- [ ] **Step 1：建立失敗測試**

```python
def test_create_first_version_writes_unpublished_v1(fake_repo, fake_writer, fake_ops):
    fake_repo.save_feature("Prepare")
    fake_repo.save_ticket("t_881", cluster="c12")
    fake_repo.save_rule("R-007", status="active", applies_when="click_ui")
    fake_repo.save_validated_at_file({"R-007": "2026-09-01T00:00:00Z"})   # Phase 55 寫的那個檔
    fake_writer.reply = four_step_draft(feature_id="Prepare")

    plan = create_first_version(GAP, repository=fake_repo, writer=fake_writer, operations=fake_ops,
                                operation_id="op-1", now=dt("2026-09-13T02:05:00Z"))

    assert plan.version_id == "prepare-meeting@v1"
    assert plan.reason == "gap:c12"
    assert plan.rules_applied == ("R-007",)
    assert fake_repo.get_version("prepare-meeting@v1").published_at is None
    assert fake_repo.get_tutorial("prepare-meeting").current_version is None
    assert fake_repo.get_tutorial("prepare-meeting").feature_ids == ["Prepare"]
```

`applies_when` 傳的是 `StepType` 的值 `"click_ui"`（Phase 04 的欄位型別就是 `StepType`），**不是** `"step.type == click_ui"` 這種條件字串（00A D-10）。`save_validated_at_file` 是測試替身寫 `operations/rules/validated_at.json` 的捷徑；少了它，Phase 19 會因為「active 規則缺驗證時間」直接丟 `PermanentError`。`four_step_draft(feature_id=...)` 是同檔 helper，回一個**符合 `TutorialDraft` schema 的 dict**，`title` 固定是 ASCII 的 `"Prepare Meeting"`（slug 才會是 `prepare-meeting`；若 `title` 是中文，依 Task 2 的規則會退回 `prepare`），四步型態 `read`／`click_ui`／`click_ui`／`read`、`feature_id` 全是傳入值。

- [ ] **Step 2：執行 `uv run pytest tests/unit/pipelines/test_ticket_create_v1.py -q` 確認紅燈**

預期 FAIL，訊號包含 `cannot import name 'create_first_version'`。

- [ ] **Step 3：建立最小實作**

```python
def create_first_version(gap, *, repository, writer, operations, operation_id, now):
    if decide_ticket_action(gap, repository=repository) != "CREATE":
        raise PermanentError(f"群 {gap.cluster_id} 不是 CREATE，不能建立第一版")
    rules = repository.list_rules(RuleStatus.ACTIVE)
    by_type = rules_for_content(rules, ALL_STEP_TYPES, load_validated_at(repository))
    injected = list({r.rule_id: r for st in ALL_STEP_TYPES for r in by_type[st]}.values())
    features = known_features(repository)
    system, user = prompt_write_tutorial(_evidence_text(gap, repository),
                                         [feature.feature_id for feature in features],
                                         render_rules_block(injected))
    draft = writer.generate_json(system, user, TutorialDraft, operation_id=operation_id, node="create_v1")
    content = TutorialContent.model_validate(draft)      # draft 是 dict，不是模型
    validate_content(content, frozenset(feature.feature_id for feature in features))
    slug = tutorial_slug(gap, content.title, repository=repository)
    create_tutorial_identity(gap, slug=slug, topic=content.title, repository=repository)
    plan = allocate_version(slug, operation_id, operations, repository=repository,
                            reason=f"gap:{gap.cluster_id}", rules_applied=applied_rule_ids(injected))
    create_version(plan, content, repository)
    record_decision("CREATE", gap, repository=repository, operation_id=operation_id, now=now)
    return plan
```

- [ ] **Step 4：補失敗與重試測試後跑綠並提交**

模型回三段內容或某一步沒有 Feature 時，`validate_content` 丟錯且**沒有**任何 `TUTORIAL#` 被建立；同一個 `operation_id` 重跑取得同一個 `version_id`（Phase 20 保證）且不重複建立教學；`ALL_STEP_TYPES` 以外的 `step.type` 被拒絕。執行 `uv run pytest tests/unit/pipelines/test_ticket_create_v1.py -q` 後 `git add src/training_kb/pipelines/ticket.py src/training_kb/analytics/status_writer.py tests/unit/pipelines/test_ticket_create_v1.py` 並 `git commit -m "feat(ticket): 建立未發布第一版"`。

## 8. 驗收矩陣

| 路徑 | 輸入 | 預期資料結果 |
|---|---|---|
| Happy | Feature 存在、無 active 教學 | `CREATE`；未發布 v1，`reason="gap:c12"`。 |
| Happy | active 但 `current_version=None` | `KEEP`；0 筆新 `TUTORIAL#`／`VERSION#`／`STEP#`，只有 `ticket-decision.json` 與工單連結。 |
| Happy | CREATE 或 KEEP 的同群工單 | 每張 `Ticket.feature_ids == ["Prepare"]`，各有一條 `ASKS_ABOUT#FEATURE#Prepare` 邊。 |
| Happy | 只有 retired 教學 | `CREATE`；新篇與 retired 那篇並存。 |
| Failure | 草稿缺 Prerequisites 段 | `validate_content` 失敗；沒有 `TUTORIAL#` 殘留。 |
| Failure | `feature_id` 指向不存在的 Feature | `ContentError`；不建 Feature 也不建教學。 |
| Boundary | `feature_id=None` | `NO_FEATURE`；保留 gap 與 Ticket 群，`feature_ids` 仍是 `[]`、沒有 `ASKS_ABOUT` 邊。 |
| Boundary | slug 已被別群佔用 | 改用 `prepare-meeting-c12`，重試仍相同。 |
| Idempotency | 同 `operation_id` 重跑 | 同一個 `version_id` 與 slug，不新增第二篇教學。 |

人工驗收：查 `TUTORIAL#prepare-meeting` 與 `VERSION#prepare-meeting@v1`，確認 `current_version` 與 `published_at` 都還是空值，`tutorials/prepare-meeting/v1.md` 只在私有 prefix；再看 KEEP 案例的 `ticket-decision.json` 是否寫得出「為什麼不改」。只看 pytest PASS 不算完成。

## 9. 常見錯誤與停止條件

| 症狀 | 原因 | 修正／停止 |
|---|---|---|
| active 未發布卻又建了一篇 | 用 `current_version` 判斷有沒有教學 | 改看 `status == active`（F12）。 |
| retired 之後再也建不出新教學 | 把 retired 也當已有教學 | `find_active_tutorial_for_feature` 只回 active。 |
| KEEP 也寫了新版本 | 判斷與寫入沒有分開 | KEEP 只呼叫 `record_decision`（紀錄 + 工單連結），不碰 TUTORIAL／VERSION／STEP。 |
| 模型自己取 slug 或版號 | 讓模型產穩定 ID | slug 由 `tutorial_slug` 決定；版號只由 Phase 20 分配；重試靠固定的 `-<cluster_id>` 退讓與 `create_only=True`。 |
| Release／Feedback 也建教學 | 共用建版函式時順手建身分 | `create_tutorial_identity` 只存在 ticket 模組，並有測試守住。 |
| 找不到 Feature 就補建一個 | 把 `NO_FEATURE` 當待辦 | 保留 gap；Ticket Analysis 永不建 Feature。 |
| 建好教學，下一輪又建一篇 | `create_tutorial_identity` 沒寫 `feature_ids` | Phase 27 是用 `feature_id in feature_ids` 找 active 教學，必須寫進去。 |
| `draft.model_dump()` 沒有這個方法 | 把 `TutorialDraft` 當 pydantic 類別 | 它是 JSON schema 字典；`generate_json` 回 `dict`，直接 `TutorialContent.model_validate(draft)`。 |
| active 規則存在卻丟 `PermanentError` | 沒讀 `operations/rules/validated_at.json` | 用 `load_validated_at(repository)`；缺值不可自己補時間（Phase 19）。 |

## 10. 來源與 Rule 對照

- [分析工單.feature](../../spec/features/分析工單.feature)
  - Rule 7「對應 Feature 已有教學時動作為 KEEP」→ Task 1 的 `test_only_active_status_blocks_create` 直接斷言（含 active 未發布）。
  - Rule 8「KEEP 只記錄 log 而不寫入教學內容」→ Task 1 Step 4 斷言 0 筆新 `TUTORIAL#`／`VERSION#`／`STEP#` item 且 `ticket-decision.json` 可讀；工單側的 `feature_ids` 與 `ASKS_ABOUT` 不是教學內容，依 D-52 照寫。
  - Rule 9「已識別且尚無現成教學的 Knowledge Gap 建立新的 Tutorial」→ Task 3 的 `test_create_first_version_writes_unpublished_v1`。
  - Rule 14「新教學第一版的 reason 使用 gap 加上來源 cluster_id」→ 同一測試斷言 `plan.reason == "gap:c12"`。
  - Rule 10「Ticket Analysis 是唯一建立新 Tutorial 身分的 pipeline」→ Task 2 的 `test_only_ticket_pipeline_creates_tutorial_identity`。
  - Rule 6「一張 Ticket 對應零或一個 Feature」→ **相關（primary 在 Phase 04）**；本 Phase 是 `Ticket.feature_ids` 與 `ASKS_ABOUT` 邊的唯一寫入者（00A D-52），Task 1 斷言寫進去的永遠是 0 或 1 個元素。
  - 相關（primary 在 Phase 21）：Rule 11–13 的五段與「每步恰一個 Feature」由 Phase 21 `validate_content` 驗收，本 Phase 只證明它被呼叫且失敗時不留殘骸。
- 設計 §7.3：只有這條流程能建立新的 Tutorial 身分；active 即使尚待首次發布也 KEEP；retired 不阻擋 CREATE；無有效 Feature 時保留 Ticket 群與 gap 診斷紀錄。§8.1：版本號屬於 Tutorial。§8.2：建立版本與發布是兩個步驟，未發布時 `published_at=null`。§9.2：`ASKS_ABOUT` 是 TICKET → FEATURE 的關係邊。決策 F12、F13、D04、D05、D25、D26、D29、F29 同時適用。
- [00A 共用契約與名詞](00A-共用契約與名詞.md)：D-02（`generate_json` 吃 schema dict、回 dict）、D-10（`applies_when` 是 `StepType`）、D-28（`validated_at` 存 `operations/rules/validated_at.json`）、D-40（item 不得多欄位）、D-52（本 Phase 寫 `ASKS_ABOUT` 與 `Ticket.feature_ids`）。

## 11. 完成清單

- [ ] 五個產出函式加 `TicketAction`、`TicketGap`、`ALL_STEP_TYPES` 的簽名與本文件一致，三種結果都有直接斷言。
- [ ] active 未發布 KEEP 與 retired 不阻擋 CREATE 兩個邊界都有獨立測試，且兩條路徑的教學內容與版本數完全沒變。
- [ ] `create_tutorial_identity` 寫進 `feature_ids=[feature_id]`，且有測試證明下一輪會走 KEEP；item 沒有模型以外的欄位。
- [ ] CREATE／KEEP 會寫 `Ticket.feature_ids`（0 或 1 個元素）與一條 `ASKS_ABOUT` 邊，`NO_FEATURE` 兩者都不寫；重跑不會變成兩條。
- [ ] slug 由程式產生、驗證 kebab-case 且重試穩定；模型不產任何 ID；`generate_json` 拿回的是 `dict`，全檔沒有把 schema 當模型用的寫法。
- [ ] 第一版 `reason` 精確等於 `gap:<cluster_id>`、`published_at` 為 `null`，`rules_applied` 只含本次實際注入 prompt 的 ID，驗證時間來自 `load_validated_at`。
- [ ] 有測試守住「只有 ticket pipeline 能建立 Tutorial 身分」；未把未發布 v1 描述成已發布，O3 未過不得宣稱公開發布通過。
