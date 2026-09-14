# Phase 51：Release UPDATE 精準改寫實作計畫

> **給實作者：** 依 checkbox 逐步執行；每個 Task 先建立失敗測試，再寫最小實作。執行時使用 `superpowers:executing-plans` 或同等逐項流程。

**目標：** 對 Phase 50 命中的每一篇教學，只重寫命中的步驟，其餘步驟與段落逐字複製到下一版，並留下 `release:<id>` 的原因、正確的 diff 與本次真正注入的規則 ID。

**架構：** `prepare_update` 逐篇取 lease 後串行處理：選 active 規則、配版號、呼叫 `StepRewrite`、由程式核對改寫範圍，最後建立未發布版本。發布交給 Phase 25 的 `Publisher`，多篇一次整批提交，全有或全無。

**技術：** Python 3.12、Pydantic v2、pytest、Phase 19 規則注入、Phase 20–23 版本與內容、Phase 15/17 `Writer.generate_json`。

## 全域限制

- 唯一主來源是 [Training KB 設計 §7.4、§7.6、§8.1–§8.3、§14、§18 O2／O3](../../design/training-kb.md)。
- 前置為 [Phase 50：Release 步驟反查與 Safety Net](50-Phase50-Release步驟反查與Safety-Net.md)；另需 [Phase 20 版本分配](20-Phase20-版本分配與重試重用.md)、[Phase 23 未發布版本與關係完整寫入](23-Phase23-未發布版本與關係完整寫入.md)、[Phase 25 多篇整批發布](25-Phase25-多篇教學整批發布.md) 已完成。
- 下一階段是 [Phase 52：Release RETIRE 與流程驗收](52-Phase52-Release-RETIRE與流程驗收.md)。
- 本階段不做：不發布、不切 `current_version`、不更新 aliases、不退役、不處理 `kind=removed`。
- 只有 `renamed` 與 `changed` 走 UPDATE；`hits` 為空時不呼叫本函式，由呼叫端 KEEP。
- 一般 UPDATE 只注入 active 規則；複製的原文不新增 `rules_applied`（F29）。
- O1–O7 是設計文件第 18 節的七個待確認事項，F 與 D 開頭的編號（F29、D26…）是第 19 節的決策編號；本文件引用它們只是指出依據，不代表已驗證。
- O1–O7 狀態：O2 未通過時不得宣稱同 operation 重送必得同版號；O3 未通過時整條公開發布路徑停止，`prepare_update` 只能產生私有未發布版本。本 Phase 不得宣稱任何 gate 已核定。
- 以下程式檔均是實作時預計建立或修改；本計畫本身不代表它們已存在。

---

## 1. 你在整體流程的位置

```text
Phase 50 hits = (StepHit(prepare-meeting, prepare-meeting@v2, 3),)
             |
             v
[你在這裡] prepare_update：逐篇 lease -> 選規則 -> 配版號 -> 改寫 -> 核對 -> create_version
             |
             +--> VersionPlan(prepare-meeting@v3, reason="release:r_42")   [私有、未發布]
             |
             v
Phase 25 Publisher.prepare / inspect / commit（全有或全無）
             |
             v
Phase 52 發布成功後才呼叫 Phase 49 的 update_feature_aliases
```

## 2. 完成後看得到什麼

`prepare_update` 的結果永遠是 `published_at=None` 的版本，沒有任何一條路徑會在這裡讓讀者看到新內容。A 的 `prepare-meeting@v2` 有四步，Phase 50 只命中第 3 步；完成後產生 `prepare-meeting@v3`，`tutorials/prepare-meeting/v3.diff` 只有這一段（步驟行的形狀由 Phase 22 固定為 `<n>. (type=<step_type>, feature=<feature_id>) <text>`）：

```diff
 2. (type=click_ui, feature=Prepare) 在會議詳情頁確認參與者。
-3. (type=click_ui, feature=Prepare) 在右上角選擇 Meeting Summary，查看會前摘要。
+3. (type=click_ui, feature=Prepare) 在會議頁面右上角選擇 Prepare，查看會前摘要。
 4. (type=read, feature=Prepare) 回到會議列表確認摘要已更新。
```

`feature=Prepare` 在改版前後都一樣：改名只動 `Feature.name` 與 `aliases`，不搬移 `FEATURE#Prepare` 這個主鍵（D06）。回傳值是 `VersionPlan(version_id="prepare-meeting@v3", reason="release:r_42", rules_applied=("R-007",))`。B、C 沒有命中，完全不進入本函式，也沒有新版本。同一個 `operation_id` 重送時，取回同一個 `prepare-meeting@v3`，不會出現 v4。

## 3. 名詞小抄

| 名詞 | 白話意思 |
|---|---|
| 精準改寫 | 只有命中的步驟文字允許不同，其他欄位與段落必須完全一樣。 |
| byte-for-byte | 連空白與標點都相同；用物件比較，不是「看起來差不多」。 |
| lease（租約） | 同一篇教學同時只讓一個操作改寫的短期標記；它不等於接受順序。 |
| `StepRewrite` | Phase 17 定的 JSON schema，模型只回「哪幾號步驟改成什麼文字」。 |
| `rules_applied` | 本次 prompt 真正注入的 active 規則 ID；沿用原文不算（F29）。 |
| 未發布版本 | `published_at=None`，產物只放私有 S3，公開站讀不到。 |

## 4. 預計檔案

| 動作 | 路徑 | 責任 |
|---|---|---|
| 修改 | `src/training_kb/pipelines/release.py` | `assert_unchanged`、`prepare_update` 與其 private helper。 |
| 修改 | `src/training_kb/writing/prompts.py` | `prompt_release_rewrite`：規則區與不可信證據分區。 |
| 測試 | `tests/unit/test_release_update.py` | 改寫範圍、逐字相同、reason、diff、lease 與重送。 |
| 測試 | `tests/unit/test_release_update_rules.py` | 只記本次注入、candidate 與別型態規則不入選。 |
| 測試 | `tests/integration/test_release_update_retry.py` | O2 重送同版號、重用模型輸出。 |

## 5. 固定介面

### Consumes

```text
StepHit(slug, version_id, number)                                                     # Phase 50
Release / Feature / TutorialContent / StepDraft / StepType / RuleStatus / AuthoringRule  # Phase 03/04
OperationCoordinator.acquire_lease(scope, owner, *, ttl_seconds, now) -> bool /
    release_lease(scope, owner) -> None                                                # Phase 11
AcceptOperation ; OperationCoordinator.accept / load / record_model_output ;
    operation_ref(op, name)                                                            # Phase 10
operation_id_for(kind: OperationKind, canonical_id: str) -> str                        # Phase 32
LEASE_TTL_SECONDS = 120  # pipelines/feedback.py，只 import 不重新宣告              # Phase 46
Repository.get_tutorial / get_version                                                  # Phase 06
Repository.get_object / put_object(key, body, content_type, *, if_none_match)          # Phase 07
Repository.list_rules(status=None) / scan_entity(entity) / item_to_model(item, model)   # Phase 08
select_active_rules / render_rules_block / applied_rule_ids / rules_for_content         # Phase 19
allocate_version(tutorial_id, operation_id, operations, *, repository, reason, rules_applied) -> VersionPlan  # Phase 20
validate_content(content, known_feature_ids) -> None                                   # Phase 21
parse_markdown(markdown) -> TutorialContent                                            # Phase 22
create_version(plan, content, repository) -> TutorialVersion                           # Phase 23
verify_version_complete(version_id, repository) -> bool                                # Phase 23
Writer.generate_json(system, user, schema, *, operation_id, node) -> dict              # Phase 15/17
StepRewrite  # schema dict；required: steps[{number, text, feature_id, type}]           # Phase 17
step_rewrite_validator(*, allowed_steps, allowed_features) -> BusinessValidator         # Phase 18
load_validated_at(repository) -> dict[str, datetime]  # analytics/status_writer.py：
    讀取端由 Phase 40 首建、寫入端 Phase 55 補在同檔                                    # Phase 40
now_utc() -> datetime / ContentError / CoordinationError / TransientError /
    PermanentError                                                                     # Phase 02
```

`generate_json` 吃 schema dict、回普通 dict，呼叫端自己驗（00A D-02）；`step_rewrite_validator` 回的是 `Callable[[dict], None]`，通過才可以進 `_apply_rewrite`。

### Produces

```python
REWRITE_NODE: str = "release_rewrite"

def prompt_release_rewrite(release: Release, base: TutorialContent,
                           targets: Sequence[int], rules_block: str) -> tuple[str, str]: ...
def assert_unchanged(base: TutorialContent, draft: TutorialContent,
                     changed: frozenset[int]) -> None: ...
def prepare_update(
    release: Release,
    hits: Sequence[StepHit],
    *,
    repository: Repository,
    writer: Writer,
    operations: OperationCoordinator,
    operation_id: str,
) -> tuple[VersionPlan, ...]: ...
```

`LEASE_TTL_SECONDS` 不列在 Produces：它的 owner 是 [Phase 46](46-Phase46-REFINE精準改寫與證據去重.md) 的 `pipelines/feedback.py`（值 120，00A §5.4），本 Phase 同名同值直接 `import`，**不重新宣告第二份**。

回傳依 `slug` 升序，每個 `VersionPlan` 對應一個已寫完但尚未發布的版本；呼叫端把整組 `version_id` 包成一個 `PublishRequest` 交給 Phase 25。`prompt_release_rewrite` 放在 `writing/prompts.py`，命名照 Phase 17 的 `prompt_<node>` 慣例，與 Phase 46 的 REFINE prompt 各自獨立。

## 6. 設計細節

每篇教學的處理順序固定如下。`validated_at_by_rule` 一律用 `analytics/status_writer.py` 的 `load_validated_at(repository)`（讀取端由 Phase 40 首建、寫入端 Phase 55 補在同一支檔）讀單一私有檔 `operations/rules/validated_at.json`（00A D-28）；缺值時 Phase 19 會丟 `PermanentError`，本 Phase 不補預設時間，也不自己再寫一份 `_load_validated_at`。

```text
operations.acquire_lease("TUTORIAL#<slug>", operation_id, ttl_seconds=120, now=now_utc())
        |  False -> TransientError（交給 ASL Retry）
        v
sub_id = operation_id_for("release-update", f"{release.id}--{slug}")  -> operations.accept
        |  每篇一筆子 operation（D-59）
        v
base = parse_markdown(get_object(current_version.s3_key))     [最近已發布版本]
        |
        v
選 active 規則（只用命中步驟的 step.type）-> render_rules_block / applied_rule_ids
        |
        v
allocate_version(slug, sub_id, ..., reason="release:<id>", rules_applied=注入 ID)
        |
        v
StepRewrite：prompt 只給命中步驟原文 + Release 證據 + 規則區
        |
        v
程式核對｜改寫集合 == 命中集合？命中步驟的 feature_id 未變？其餘步驟與四個段落逐字相同？
        |  否 -> ContentError（不建立版本）
        v
validate_content -> create_version -> verify_version_complete -> finally release_lease
```

**每篇教學各開一筆子 operation（00A D-59）。** 「子 operation」就是在這次 Release 的 operation 底下，為每一篇被命中的教學另外開一筆自己的 `OPS#` 紀錄。必須這樣做，是因為 `allocate_version` 以 `operation_id` 當唯一鍵、`OperationRecord.version_id` 只有一個值：一個 Release 命中兩篇教學時，兩篇共用 `op-release-r_42` 會互相搶同一個版號。所以先用 `operation_id_for("release-update", f"{release.id}--{slug}")` 算出 `sub_id`（例如 `op-release-update-r_42--prepare-meeting`；用兩個連字號當分隔，避免 slug 裡的單一連字號造成混淆），`accept` 之後再把 `sub_id` 交給 `allocate_version`。同一個 Release 重送時，`sub_id` 逐字相同，`accept` 回 `duplicate`，版號沿用原本那一個。`project_id` 沿用父 operation 紀錄上的值（**本計畫選擇**：`Release` 模型沒有 `project_id` 欄位，不在這裡另外讀 `Settings`）；父 operation 讀不到就是 `CoordinationError`。`allocate_version` 內部已經呼叫過 `record_version`（Phase 20），本 Phase **不**再補一次。

規則選取排在 `allocate_version` 之前，是因為 Phase 19 要求「prompt 與 `rules_applied` 使用同一份 selected list」，而 `allocate_version` 的參數就包含 `rules_applied`；規則選取是純函式，提前執行不改變任何介面，這是**本計畫選擇**，Phase 46 的 REFINE 採同一順序。

lease 的 scope 字串是 `TUTORIAL#<slug>`（Phase 11 自己補 `LEASE#` 前綴），只讓同一篇的併發改寫串行化（設計 §8.3）；**它不是接受順序的保證，TTL 也不是準時解鎖**，所以拿不到時丟 `TransientError` 交給 ASL 有限重試，不自行迴圈等待，真正的順序保證仍屬 O2。`prepare_update` 的 canonical 簽名沒有 `now`，租約到期時間因此由函式內部呼叫 `now_utc()`（**本計畫選擇**：租約是執行資訊，版本的 `published_at` 仍由 Phase 24 的 `now` 決定）。

「命中步驟的 `feature_id` 不可改變」是硬性檢查：改名不搬移 Feature PK（D06），模型若把第 3 步改指別的 Feature 必須以 `ContentError` 結束。prompt 由 `prompt_release_rewrite` 產生，Release 的 `evidence`、`old_name`、`new_name` 與步驟原文都是不可信文字，一律先經 [Phase 17](17-Phase17-Claude結構化輸出與Prompt.md) 的 `_as_data`（`html.escape`）轉義再包進同一個 `<source_data>` 分區，只當資料不當指令（D-67）；不得自創新的分區名稱；`<active_rules>` 放 `render_rules_block(rules)` 的結果。模型輸出以**每篇一個 ref** 存成 `operations/<operation_id>/rewrite-<slug>.json`，重送先讀回來（設計 §14.2）；用 per-slug ref 而不是 `model_output_refs[-1]`，是因為一個 `operation_id` 可能命中多篇教學、`[-1]` 會分不清是誰的輸出（**本計畫選擇**），每個 ref 仍照 Phase 10 記進 `record_model_output`。

## 7. TDD Tasks

### Task 1：只改命中步驟，其餘逐字相同

- [ ] **Step 1：建立失敗測試**（`tests/unit/test_release_update.py`）

```python
HITS_STEP3 = (StepHit("prepare-meeting", "prepare-meeting@v2", 3),)   # Phase 50 的輸出

def test_only_hit_steps_change_and_others_are_byte_for_byte(base_v2, fake_writer, repo, ops):
    fake_writer.reply = {"steps": [
        {"number": 3, "text": "在會議頁面右上角選擇 Prepare，查看會前摘要。",
         "feature_id": "Prepare", "type": "click_ui"},
    ]}
    plans = prepare_update(RELEASE_R42, HITS_STEP3, repository=repo, writer=fake_writer,
                           operations=ops, operation_id="op-release-r_42")
    draft = repo.saved_content(plans[0].version_id)
    assert [step.number for step in draft.steps if step.text != base_v2.step(step.number).text] == [3]
    for number in (1, 2, 4):
        assert draft.step(number).model_dump() == base_v2.step(number).model_dump()
    assert (draft.title, draft.problem, draft.prerequisites, draft.expected_outcome) == base_v2.sections()

def test_model_touching_an_extra_step_is_rejected(base_v2, fake_writer, repo, ops):
    fake_writer.reply = {"steps": [
        {"number": 3, "text": "新的第三步。", "feature_id": "Prepare", "type": "click_ui"},
        {"number": 2, "text": "偷改的第二步。", "feature_id": "Prepare", "type": "read"},
    ]}
    with pytest.raises(ContentError, match="改寫集合"):
        prepare_update(RELEASE_R42, HITS_STEP3, repository=repo, writer=fake_writer,
                       operations=ops, operation_id="op-extra")
    assert repo.created_versions == []
```

- [ ] **Step 2：執行 `uv run pytest tests/unit/test_release_update.py -q` 確認紅燈。** 預期 FAIL，訊號包含 `cannot import name 'prepare_update'`。

- [ ] **Step 3：建立最小實作**

```python
# src/training_kb/pipelines/release.py
def _apply_rewrite(base: TutorialContent, reply: dict, targets: frozenset[int]) -> TutorialContent:
    changed = {int(item["number"]): item for item in reply["steps"]}
    if set(changed) != set(targets):
        raise ContentError(f"改寫集合 {sorted(changed)} 不等於命中集合 {sorted(targets)}")
    steps = []
    for step in base.steps:
        item = changed.get(step.number)
        if item is None:
            steps.append(step)                       # 未命中：整個物件原樣帶過
            continue
        if item["feature_id"] != step.feature_id:
            raise ContentError(f"步驟 {step.number} 不可改變引用的 Feature")
        text = str(item["text"]).strip()
        if not text:
            raise ContentError(f"步驟 {step.number} 的新文字是空的")
        steps.append(step.model_copy(update={"text": text, "type": StepType(item["type"])}))
    return base.model_copy(update={"steps": steps})

def assert_unchanged(base: TutorialContent, draft: TutorialContent,
                     changed: frozenset[int]) -> None:
    if (base.title, base.problem, base.prerequisites, base.expected_outcome) != (
        draft.title, draft.problem, draft.prerequisites, draft.expected_outcome
    ):
        raise ContentError("UPDATE 不可改動命中步驟以外的段落")
    if len(base.steps) != len(draft.steps):
        raise ContentError(f"步驟數量由 {len(base.steps)} 變成 {len(draft.steps)}")
    for left, right in zip(base.steps, draft.steps, strict=True):
        if left.number not in changed and left.model_dump() != right.model_dump():
            raise ContentError(f"未命中步驟 {left.number} 的原文必須逐字相同")
```

`model_copy(update=...)` 在 pydantic v2 不做驗證，所以型態一定要先經 `StepType(...)` 轉換，不能把原始字串直接塞進去。

- [ ] **Step 4：跑 `uv run pytest tests/unit/test_release_update.py -q` 確認綠燈。** 另補三個案例：模型漏回命中步驟、`reply["steps"]` 多一筆造成步驟數量改變、改寫文字去空白後為空，三者都必須是 `ContentError` 且 `repo.created_versions == []`。
- [ ] **Step 5：提交** `git add src/training_kb/pipelines/release.py tests/unit/test_release_update.py`，再 `git commit -m "feat(release): 只改寫命中步驟"`。

### Task 2：固定 reason、diff 與本次注入的規則

- [ ] **Step 1：建立失敗測試（兩個檔案各一組）。** 第一組放 `tests/unit/test_release_update.py`，鎖定 reason 與 diff：

```python
def test_reason_and_rules_come_from_this_run(fake_writer, repo, ops, rule_store):
    rule_store.active = [rule("R-007", "click_ui"), rule("R-012", "read")]   # 第 3 步是 click_ui
    plans = prepare_update(RELEASE_R42, HITS_STEP3, repository=repo, writer=fake_writer,
                           operations=ops, operation_id="op-release-r_42")
    assert plans[0].reason == "release:r_42"
    assert plans[0].rules_applied == ("R-007",)          # read 規則不入選

def test_diff_only_covers_the_hit_step(fake_writer, repo, ops):
    prepare_update(RELEASE_R42, HITS_STEP3, repository=repo, writer=fake_writer,
                   operations=ops, operation_id="op-diff")
    diff = repo.get_object("tutorials/prepare-meeting/v3.diff").decode("utf-8")
    assert [line for line in diff.splitlines()
            if line.startswith(("+", "-")) and not line.startswith(("+++", "---"))] == [
        "-3. (type=click_ui, feature=Prepare) 在右上角選擇 Meeting Summary，查看會前摘要。",
        "+3. (type=click_ui, feature=Prepare) 在會議頁面右上角選擇 Prepare，查看會前摘要。",
    ]
```

第二組放 `tests/unit/test_release_update_rules.py`，鎖定「只注入本次選中的 active 規則」（APL Rule 8）：

```python
def test_only_injected_active_rules_enter_prompt_and_record(fake_writer, repo, ops, rule_store):
    rule_store.active = [rule("R-007", "click_ui"), rule("R-012", "read")]
    rule_store.candidates = [rule("R-099", "click_ui", status="candidate")]
    plans = prepare_update(RELEASE_R42, HITS_STEP3, repository=repo, writer=fake_writer,
                           operations=ops, operation_id="op-rules")
    injected = fake_writer.json_calls[0].user
    assert "[R-007]" in injected
    assert "R-012" not in injected and "R-099" not in injected
    assert plans[0].rules_applied == ("R-007",)
```

- [ ] **Step 2：執行 `uv run pytest tests/unit/test_release_update.py tests/unit/test_release_update_rules.py -q` 確認紅燈。** 預期 FAIL，訊號包含 `cannot import name '_rules_for_hits'`（`load_validated_at` 在 Phase 40 就已經存在，不會是紅燈訊號）。

- [ ] **Step 3：建立最小實作**

```python
def _rules_for_hits(base: TutorialContent, targets: frozenset[int], *, repository):
    step_types = [step.type for step in base.steps if step.number in targets]
    by_type = rules_for_content(repository.list_rules(RuleStatus.ACTIVE), step_types,
                                load_validated_at(repository))       # Phase 19 + Phase 55
    selected, seen = [], set()
    for step_type in step_types:
        for item in by_type[step_type]:
            if item.rule_id not in seen:
                seen.add(item.rule_id)
                selected.append(item)
    return selected

def _sub_operation(release, slug, *, operations, operation_id) -> str:
    """每篇教學各一筆子 operation；allocate_version 以 operation_id 為唯一鍵（D-59）。"""
    parent = operations.load(operation_id)
    if parent is None:
        raise CoordinationError(f"{operation_id} 尚未被 O2 接受")
    canonical_id = f"{release.id}--{slug}"
    sub_id = operation_id_for("release-update", canonical_id)
    operations.accept(AcceptOperation(operation_id=sub_id, kind="release-update",
                                      canonical_id=canonical_id,
                                      project_id=parent.project_id, now=now_utc()))
    return sub_id

def _prepare_one(release, slug, targets, *, repository, writer, operations, operation_id):
    tutorial = repository.get_tutorial(slug)
    if tutorial is None or tutorial.current_version is None:
        raise ContentError(f"{slug} 沒有已發布版本可以當基底")
    sub_id = _sub_operation(release, slug, operations=operations, operation_id=operation_id)
    base_version = repository.get_version(tutorial.current_version)
    base = parse_markdown(repository.get_object(base_version.s3_key).decode("utf-8"))
    rules = _rules_for_hits(base, targets, repository=repository)
    plan = allocate_version(slug, sub_id, operations, repository=repository,
                            reason=f"release:{release.id}", rules_applied=applied_rule_ids(rules))
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
```

`create_version` 依 Phase 22／23 寫 `tutorials/<slug>/v<n>.md` 與 `v<n>.diff`，本 Phase 只斷言 diff 範圍；raw item 轉模型一律經 `item_to_model`（00A D-29）。模型輸出的 ref 仍掛在**父** operation 底下（`operations/<operation_id>/rewrite-<slug>.json`，00A §6.9），因為它本來就已經 per-slug，不會兩篇互相覆蓋；只有版號分配走子 operation。
- [ ] **Step 4：跑 `uv run pytest tests/unit/test_release_update.py tests/unit/test_release_update_rules.py -q` 確認綠燈。** 另補一個案例放 `tests/unit/test_release_update_rules.py`：第 1 步同樣是 `click_ui` 且原文本來就符合 `R-007`，但它沒被改寫，所以 `R-007` **不因它**進入 `rules_applied`（F29）。
- [ ] **Step 5：提交** `git add src/training_kb/pipelines/release.py src/training_kb/writing/prompts.py tests/unit/test_release_update.py tests/unit/test_release_update_rules.py`，再 `git commit -m "feat(release): 固定改版原因與規則紀錄"`。

### Task 3：lease 串行、同 operation 重送與整批交付

- [ ] **Step 1：建立失敗測試**（同樣放 `tests/unit/test_release_update.py`）

```python
def test_lease_conflict_raises_transient_error(fake_writer, repo, ops, lease_store):
    lease_store.hold("TUTORIAL#prepare-meeting", owner="op-other")
    with pytest.raises(TransientError):
        prepare_update(RELEASE_R42, HITS_STEP3, repository=repo, writer=fake_writer,
                       operations=ops, operation_id="op-release-r_42")

def test_same_operation_reuses_version_and_model_output(fake_writer, repo, ops):
    first = prepare_update(RELEASE_R42, HITS_STEP3, repository=repo, writer=fake_writer,
                           operations=ops, operation_id="op-release-r_42")
    repo.fail_next_edge_write()                        # 寫關係時中斷
    second = prepare_update(RELEASE_R42, HITS_STEP3, repository=repo, writer=fake_writer,
                            operations=ops, operation_id="op-release-r_42")
    assert [plan.version_id for plan in second] == [plan.version_id for plan in first]
    assert fake_writer.request_attempts == 1           # 重送不再呼叫模型

def test_two_hit_tutorials_return_one_batch(fake_writer, repo, ops, hits_two_tutorials):
    plans = prepare_update(RELEASE_R42, hits_two_tutorials, repository=repo, writer=fake_writer,
                           operations=ops, operation_id="op-release-r_42")
    assert [plan.slug for plan in plans] == ["prepare-meeting", "weekly-digest"]   # slug 升序
    assert repo.published_version_ids == []            # 本 Phase 不發布任何版本

def test_each_slug_gets_its_own_sub_operation(fake_writer, repo, ops, hits_two_tutorials):
    plans = prepare_update(RELEASE_R42, hits_two_tutorials, repository=repo, writer=fake_writer,
                           operations=ops, operation_id="op-release-r_42")
    assert ops.accepted_ids == ["op-release-update-r_42--prepare-meeting",
                                "op-release-update-r_42--weekly-digest"]        # D-59
    for plan, sub_id in zip(plans, ops.accepted_ids, strict=True):
        assert ops.load(sub_id).version_id == plan.version_id      # 兩篇的版號各自獨立
    assert ops.load("op-release-r_42").version_id is None          # 父 operation 不佔版號
```

`ops` 是同檔 fixture：記憶體 O2 帳本，`accepted_ids` 依接受順序記下每一個 `accept` 進來的 `operation_id`，`op-release-r_42` 這筆父紀錄在 fixture 建立時就已經接受好（`project_id="demo"`）。

- [ ] **Step 2：執行 `uv run pytest tests/unit/test_release_update.py -q` 確認紅燈。** 預期 FAIL：`TransientError` 沒有被拋出，或 `fake_writer.request_attempts == 2`。

- [ ] **Step 3：建立最小實作**

```python
from training_kb.pipelines.feedback import LEASE_TTL_SECONDS   # owner 是 Phase 46，不重新宣告

REWRITE_NODE = "release_rewrite"

def _rewrite_once(release, base, slug, targets, rules, *, repository, writer,
                  operations, operation_id):
    ref = operation_ref(operation_id, f"rewrite-{slug}")
    saved = repository.get_object(ref)
    if saved is not None:                              # 重送：重用既有輸出（設計 §14.2）
        return json.loads(saved.decode("utf-8"))
    system, user = prompt_release_rewrite(release, base, sorted(targets),
                                          render_rules_block(rules))
    validate = step_rewrite_validator(
        allowed_steps=frozenset(targets),
        allowed_features=frozenset(step.feature_id for step in base.steps))
    reply = writer.generate_json(system, user, StepRewrite,
                                 operation_id=operation_id, node=REWRITE_NODE)
    validate(reply)                                    # Phase 18 的業務 validator
    body = json.dumps(reply, ensure_ascii=False, sort_keys=True).encode("utf-8")
    repository.put_object(ref, body, "application/json", if_none_match=True)
    operations.record_model_output(operation_id, ref)
    return reply

def prepare_update(release, hits, *, repository, writer, operations, operation_id):
    if release.kind not in (ReleaseKind.RENAMED, ReleaseKind.CHANGED):
        raise PermanentError(f"UPDATE 只處理 renamed 與 changed，收到 {release.kind}")
    by_slug: dict[str, set[int]] = {}
    for hit in hits:
        by_slug.setdefault(hit.slug, set()).add(hit.number)
    plans = []
    for slug in sorted(by_slug):
        scope = f"TUTORIAL#{slug}"
        if not operations.acquire_lease(scope, operation_id,
                                        ttl_seconds=LEASE_TTL_SECONDS, now=now_utc()):
            raise TransientError(f"{slug} 正由另一個操作改寫，稍後重試")
        try:
            plans.append(_prepare_one(release, slug, frozenset(by_slug[slug]),
                                      repository=repository, writer=writer,
                                      operations=operations, operation_id=operation_id))
        finally:
            operations.release_lease(scope, operation_id)
    return tuple(plans)
```

`finally` 讓 `ContentError` 也會歸還租約，否則同一篇要等 TTL 才解得開。多篇時回一整組 `VersionPlan`，呼叫端把 `version_ids` 一次交給 `Publisher.prepare`；第二篇 inspect 失敗時第一篇也不得被發布（F49），本 Phase 只負責「回傳一整組」與「沒有任何 publish 呼叫」。

- [ ] **Step 4：跑綠燈並執行 O2 整合測試**

```bash
uv run pytest tests/unit/test_release_update.py -q
uv run pytest tests/integration/test_release_update_retry.py -q
```

預期兩者 PASS，並保存 operation record 的 `model_output_refs` 與 `version_id`。若 O2 尚未通過真實整合驗證，本 Task 標為 BLOCKED，不得把記憶體 fake 的綠燈當成 O2 已驗證。

- [ ] **Step 5：提交** `git add src/training_kb/pipelines/release.py tests/unit/test_release_update.py tests/integration/test_release_update_retry.py`，再 `git commit -m "test(release): 驗證改版重送與整批交付"`。

## 8. 驗收矩陣

| 路徑 | 輸入 | 預期資料結果 |
|---|---|---|
| Happy | 只命中 A 第 3 步 | 產生 `prepare-meeting@v3`；第 1、2、4 步物件逐字相同；`reason` 為 `release:r_42`；diff 只含第 3 步兩行。 |
| Failure | 模型多改第 2 步 | `ContentError`；沒有新版本、沒有 S3 產物被當成功。 |
| Failure | 模型把第 3 步改指別的 Feature | `ContentError`；Feature PK 不被搬移（D06）。 |
| Failure | `kind="removed"` 誤入本函式 | `PermanentError`；退役是 Phase 52 的事。 |
| Boundary | 第 1 步同型態但未改寫 | `rules_applied` 不因它增加（F29）。 |
| Boundary | 同一篇已被別的操作持有 lease | `TransientError`，交 ASL 有限重試。 |
| Retry | 同 `operation_id` 重送 | 同一個 `version_id`，模型呼叫次數仍為 1；B、C 未命中則完全不進入本函式。 |
| Boundary | 一個 Release 命中兩篇教學 | 兩篇各 `accept` 一筆 `op-release-update-<release_id>--<slug>` 子 operation，版號互不相干（D-59）。 |

人工驗收：打開 `tutorials/prepare-meeting/v2.md` 與 `v3.md`，用 `diff` 指令逐行比較，親眼確認只有第 3 步不同；再讀 operation record 的 `version_id` 與 `model_output_refs`，確認重送沒有新增第二筆。不能只看測試顯示 PASS。

## 9. 常見錯誤與停止條件

| 症狀 | 原因 | 修正／停止 |
|---|---|---|
| 第 1、2、4 步標點被順手改掉 | 讓模型重生成全文 | 未命中步驟由 base 物件帶過，並用 `assert_unchanged` 擋住。 |
| diff 出現整篇差異 | 以新產生的全文為基底 | 基底必須是最近已發布版本（`current_version`）的原文。 |
| `rules_applied` 列出所有 active 規則，或 candidate 進了 prompt | 把沿用原文當本次套用；沒過濾 status | 只記 prompt 實際注入的 ID（F29）；停止改寫，回 Phase 19 只取 active。 |
| active 規則存在卻丟 `PermanentError` | 沒讀 `operations/rules/validated_at.json` | 用 `load_validated_at(repository)`；缺值不可自己補時間（00A D-28）。 |
| 重送產生 v3、v4 | 沒先讀 operation 的 `version_id` | 停止發布路徑，回 Phase 20／11 修正；O2 未 PASS 前不得宣稱去重成立。 |
| 兩篇搶同一個版號，或第二篇拿到第一篇的 `version_id` | 兩篇共用同一個 `operation_id` 呼叫 `allocate_version` | 每篇先 `accept` 自己的 `op-release-update-<release_id>--<slug>` 子 operation（D-59）。 |
| lease 一直拿不到 | 例外路徑沒有 `release_lease` | 用 `try/finally` 歸還；TTL 不是準時解鎖，不可自行迴圈等待。 |
| A 已發布、D 失敗 | 逐篇各自 publish | 停止，改為整組交 Phase 25 一次提交（F49）。 |

## 10. 來源與 Rule 對照

- [依改版更新教學.feature](../../spec/features/依改版更新教學.feature)
  - Rule 8「renamed 或 changed 的改版動作為 UPDATE」（primary）→ `prepare_update` 入口只接受這兩種 kind，Task 1 的 fixture 用 `renamed`，Task 3 的 `removed` 案例斷言 `PermanentError`。
  - Rule 10「UPDATE 只重寫受影響的步驟」（primary）→ `tests/unit/test_release_update.py::test_only_hit_steps_change_and_others_are_byte_for_byte` 與 `test_model_touching_an_extra_step_is_rejected`。
  - Rule 11「UPDATE 將未命中步驟的原文複製到下一版」（primary）→ 同一測試對第 1、2、4 步做 `model_dump()` 逐欄比較。
  - Rule 13「UPDATE 為受影響教學產生與前版的 diff」（primary）→ `tests/unit/test_release_update.py::test_diff_only_covers_the_hit_step`。
  - Rule 14「UPDATE 下一版的 reason 使用 release 加上改版事件 id」（primary）→ `tests/unit/test_release_update.py::test_reason_and_rules_come_from_this_run` 斷言 `release:r_42`。
  - Rule 15「UPDATE 完成時更新 Feature 的 aliases」→ 相關（primary Phase 49）：本 Phase 不呼叫 `update_feature_aliases`，時機由 Phase 52 的 `UpdateAliases` 排在發布之後。
- [套用教學規則.feature](../../spec/features/套用教學規則.feature)
  - Rule 8「後續 Release 重寫仍注入適用的教學規則」（primary）→ `tests/unit/test_release_update_rules.py::test_only_injected_active_rules_enter_prompt_and_record` 斷言 `[R-007]` 同時出現在 prompt 與 `rules_applied`。
  - Rule 1「CREATE、UPDATE 與 REFINE 在寫作前讀取教學規則」、Rule 7「版本的 rules_applied 記錄本次套用的規則」→ 相關（primary Phase 19）；本 Phase 只證明 UPDATE 這條路徑確實照做。
- Supporting：F29（沿用原文不算套用）、F35（同篇依接受順序串行）、D26（重試重用版號）、F36（關係不完整不得發布）、F49（整次失敗不發布新版）、D06（改名保留 Feature PK）；設計 §7.4 與 §8.1–8.3。

## 11. 完成清單

- [ ] `assert_unchanged` 與 `prepare_update` 的名稱與簽名符合本文件與 00A；命中步驟以外的步驟物件與四個段落都有 byte-for-byte assertion。
- [ ] 模型越界改寫、漏改、改動 Feature、步驟數量改變、空文字五種情況都以 `ContentError` 結束且無新版本。
- [ ] `reason` 固定為 `release:<id>`，diff 範圍只含命中步驟，`rules_applied` 只含本次實際注入的 active 規則；驗證時間來自 `analytics/status_writer.py` 的 `load_validated_at(repository)`，本 Phase 沒有第二份 `_load_validated_at`。
- [ ] lease scope 是 `TUTORIAL#<slug>`、衝突丟 `TransientError`、例外路徑也會 `release_lease`；同 operation 重送取回同一版號且不重呼叫模型。
- [ ] 每篇教學都先 `accept` 一筆 `operation_id_for("release-update", f"{release.id}--{slug}")` 子 operation，再用它呼叫 `allocate_version`（D-59）；父 operation 不佔版號，也沒有第二次 `record_version`。
- [ ] REL Rule 8、10、11、13、14 與 APL Rule 8 有直接 assertion，且各自寫明在哪一個測試檔。
- [ ] 未把 Fake 的 PASS 說成 O2／O3 已通過，也沒有在本 Phase 發布任何版本。
