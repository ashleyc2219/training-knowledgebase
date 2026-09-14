# Phase 23：未發布版本與關係完整寫入實作計畫

> **給實作者：** 依 checkbox 逐步執行；每個 Task 先建立失敗測試，再寫最小實作。執行時使用 `superpowers:executing-plans` 或同等逐項流程。

**目標：** 依固定順序寫出一個 `published_at=None` 的完整版本：S3 全文與 diff、VERSION item、每一步的 STEP item 與引用邊，以及 `SUPERSEDES`、`APPLIED_TO` 邊，最後自己核對一次。

**架構：** `create_version` 是 `content` 模組的寫入入口，只呼叫 Phase 22 的產物函式與 `Repository`。`verify_version_complete` 只用基表一致讀取核對，不走最終一致的 `by_target` GSI。發布是另一件事，由 Phase 24 負責。

**技術：** Python 3.12、pytest、Phase 06–08 的 `Repository`、Phase 05 的鍵函式。

## 全域限制

- 唯一主來源是 [Training KB 設計 §8.2、§9.1、§9.2、§10、§14.1](../../design/training-kb.md)。
- 前置為 [Phase 22：Markdown 與 Diff 私有產物](./22-Phase22-Markdown與Diff私有產物.md) 與 [Phase 08：分頁查詢與一致讀取基礎](./08-Phase08-分頁查詢與一致讀取基礎.md)。前置未通過時停止。
- 下一階段是 [Phase 24：單篇教學發布提交](./24-Phase24-單篇教學發布提交.md)。
- 本階段不切 `current_version`、不寫 `published_at`、不寫 `site/`、不產生 HTML、不建立 Tutorial 或 Feature、不重算版號。
- 關係不完整的版本一律不可發布。`create_version` 失敗時不刪除已寫入的私有 S3 產物；它們讀不到，留著讓重送沿用（F36）。
- 與本 Phase 有關的 gate（現況依 controller 2026-09-14 裁決，見 `.superpowers/sdd/phase0914-1/COMMON.md`）：**O3 為 FAIL**（`docs/plan/report/o3-20260914t181109z.md`），本批策略是「離線開發照常，真實切點驗證延後到 P41 起」——本階段綠燈只代表「未發布版本寫得完整」，不得宣稱發布或公開切換已驗收；O1 尚未核定，metadata 的 `META` 仍是建議值；**O2 已 PASS**，但「同 operation 重送必得同版號」仍是 [Phase 20](./20-Phase20-版本分配與重試重用.md) 的責任，本 Phase 不重複宣稱。以下程式檔均是實作時預計建立或修改。

---

## 1. 你在整體流程的位置

```text
Phase 20 VersionPlan + Phase 21 已驗證內容 + Phase 22 產物函式
                        |
                        v
            [你在這裡：create_version]
   1 寫 S3 tutorials/<slug>/v<n>.md 與 .diff（私有、條件寫入）
   2 寫 VERSION META（published_at = None）
   3 寫每一步的 STEP item 與 REFERENCES 邊
   4 寫 SUPERSEDES 邊與每條 rules_applied 的 APPLIED_TO 邊，再自我核對
       |                                  |
     齊全                              不齊全
       v                                  v
  Phase 24 才有資格 publish     ContentError；保留不可公開的產物
```

## 2. 完成後看得到什麼

`prepare-meeting@v2` 建立完成後，DynamoDB 基表可讀到下列 item（`target` 與 SK 的終點完全相同）：

```text
PK                          SK                                     target
VERSION#prepare-meeting@v2  META  -> supersedes=prepare-meeting@v1、published_at=null
                                     s3_key=tutorials/prepare-meeting/v2.md
VERSION#prepare-meeting@v2  SUPERSEDES#VERSION#prepare-meeting@v1  VERSION#prepare-meeting@v1
STEP#prepare-meeting@v2#3   REFERENCES#FEATURE#Prepare             FEATURE#Prepare
RULE#R-007                  APPLIED_TO#VERSION#prepare-meeting@v2  VERSION#prepare-meeting@v2
```

此時 `verify_version_complete("prepare-meeting@v2", repository)` 回 `True`，但公開站上仍看不到 v2。

## 3. 名詞小抄

| 名詞 | 白話意思 |
|---|---|
| 未發布版本 | 版本資料齊全但 `published_at` 是 `None`；只有維護者的私有路徑讀得到。 |
| 關係邊 | 一筆 `PK=起點、SK=關係#終點、target=終點` 的 item，用來反查誰引用誰。 |
| `REFERENCES` 邊 | 步驟指向它引用的 Feature；STEP 本身就是這筆 item，不另存 META。 |
| `APPLIED_TO` 邊 | 規則指向本次實際注入它的版本；權威來源是 `VERSION.rules_applied`。 |
| 一致讀取 | 直接讀基表並要求 `ConsistentRead`，看得到剛寫入的資料；GSI 做不到。 |
| 自我核對 | 寫完後再讀一次確認每一項都在，不靠「寫入沒丟例外」就算成功。 |

## 4. 預計檔案

| 動作 | 路徑 | 責任 |
|---|---|---|
| 修改 | `src/training_kb/content.py` | `create_version`、`verify_version_complete` 與私有核對函式。 |
| 測試 | `tests/integration/test_create_version.py` | 寫入順序、`published_at=None`、三種邊與 target 一致。 |
| 測試 | `tests/integration/test_version_complete.py` | 缺 S3、缺邊、缺 Feature 與中斷後重送。 |

## 5. 固定介面

### Consumes

```text
ContentError(PermanentError)                                                           # Phase 02
TutorialContent(title, problem, prerequisites, steps, expected_outcome) / StepDraft     # Phase 03
TutorialVersion(version_id, slug, supersedes, reason, rules_applied, s3_key,
    published_at) / TutorialStep(tutorial_version, number, type, text, feature_id) /
    Feature(feature_id, name, aliases)                                                  # Phase 04
version_pk / step_pk / feature_pk / rule_pk / edge_sk / parse_pk                        # Phase 05
Repository.put_meta(entity, *, create_only=True) / get_version / get_tutorial /
    get_feature                                                                        # Phase 06
Repository.put_edge(pk, relation, target_pk, attrs=None) / list_edges(pk, relation=None) /
    get_object / object_exists                                                         # Phase 07
Repository.query_pk(pk, *, sk_prefix=None, consistent=True) /
    scan_entity(entity, *, consistent=True, meta_only=True) /
    item_to_model(item, model)                                                         # Phase 08
VersionPlan(version_id, slug, number, supersedes, reason, rules_applied, operation_id)  # Phase 20
parse_version_id(value) -> tuple[str, int]                                             # Phase 20
validate_content(content, known_feature_ids: frozenset[str]) -> None                   # Phase 21
render_markdown / parse_markdown / make_diff / markdown_key / diff_key /
    put_private_artifact                                                               # Phase 22
```

### Produces

```python
def create_version(
    plan: VersionPlan, content: TutorialContent, repository: Repository
) -> TutorialVersion: ...

def verify_version_complete(version_id: str, repository: Repository) -> bool: ...
```

`verify_version_complete` 只回 `True`／`False`。缺漏明細由 module-private 的 `_missing_parts(version_id, repository) -> list[str]` 提供，`create_version` 用它組出可讀的 `ContentError`；這不是跨模組 public API。

## 6. 設計細節

寫入順序固定，而且每個中斷點都有明確的對外可見狀態（設計 §8.2、F36）：

```text
validate_content
   |--> 寫 S3 .md / .diff ----- 中斷 -> 私有產物留著，重送沿用同版號與同產物
   |--> 寫 VERSION META ------- 中斷 -> 有 VERSION、沒有 STEP：verify 回 False
   |--> 寫 STEP + REFERENCES -- 中斷 -> 部分步驟缺邊：verify 回 False
   |--> 寫 SUPERSEDES / APPLIED_TO 邊
   v
verify_version_complete == True -> 交給 Phase 24；False -> ContentError，不刪產物
```

**`published_at` 一律不寫。** D25 規定未發布就是 `published_at=None`；只有 publish 成功才有值（F37）。因此 `create_version` 永遠不碰這個欄位，也不碰 `Tutorial.current_version`。

**重試要冪等，但只對同一份 plan 冪等。** `create_version` 先讀 `repository.get_version(plan.version_id)`：已存在且 `published_at` 非 `None` 就丟 `ContentError`（已發布不可覆寫）；已存在且未發布則跳過 `put_meta`（Phase 06 的 `create_only=True` 會拒絕重複建立），只補寫產物與邊。S3 那一段由 Phase 22 的條件寫入保證同內容冪等、不同內容失敗。

**重送也要守門內容（修正回合 1）。** 沿用既有 item 之前，必須先把 plan 組出來的 `TutorialVersion` 與既有那筆**逐欄比對**（`version_id`／`slug`／`supersedes`／`reason`／`rules_applied`／`s3_key`，不比 `published_at`），不同就丟 `ContentError`——這與 `put_private_artifact` 比對 bytes 是同一個作法：同一個版號只能有一種內容。少了這一關，同版號換 `reason`／`rules_applied` 重送會靜默成功、回傳舊的 `rules_applied=[]`，卻照新 plan 寫出 `RULE#R-007 APPLIED_TO` 邊，核對還會通過。順帶在 `_planned_version` 檢查 plan 自洽（`make_version_id(slug, number) == version_id`），否則會寫出「item 說自己是 v1、全文卻放在 `v2.md`」的版本。兩道關卡都在任何寫入之前，被拒的重送不留下半筆產物或邊。

**核對只用基表。** GSI `by_target` 是最終一致，剛寫入的邊可能還讀不到；用它核對會誤判「關係不完整」或更糟地誤判「完整」。所以 `_missing_parts` 一律用完整 PK 的 `query_pk(..., consistent=True)`（或基表一致的 `scan_entity`），並以 S3 全文 `parse_markdown` 得到的步驟清單當作應有步驟的權威（設計 §10）。

**「不缺」與「不多」都要驗（修正回合 1）。** 只驗缺漏會放行三種矛盾：全文只有四步、基表卻多一個 `STEP#…#5`（上一版留下的殘骸會跟著發布）；`rules_applied` 是空的、卻有 `RULE#R-999 APPLIED_TO#VERSION#…` 指向本版（權威欄位與邊互相矛盾，D17）；同一版兩條 `SUPERSEDES`（版本鏈分岔）。所以 `_extra_step_problems` 比對 `get_steps` 的編號集合與全文步數、`_exact_edge_problems` 要求 `SUPERSEDES` 邊集合恰等於 `[supersedes]`（沒有前版就是空集合）、`_applied_to_problems` 用基表一致 `scan_entity("RULE", meta_only=False)` 找出所有指向本版的 `APPLIED_TO` 邊，集合必須恰等於 `rules_applied`——只查 `rules_applied` 那幾個 `RULE#` 起點驗得出「不缺」、驗不出「不多」。

**核對是關卡，不是程式錯誤回報點（修正回合 1）。** 手改出來的損壞邊（例如 `target="FEATURE#"`）會讓 `edge_sk`／`parse_pk` 丟 `ValueError`；一律經 `_expected_sk` 與 `_missing_parts` 的 `except ValueError` 收斂成一條「問題」，讓 `verify_version_complete` 回 `False`，不得把例外炸給 Phase 24（那會讓「不可發布」變成「發布流程當掉」）。`PermanentError` 類的程式錯誤不吞。

**item 上不可以有模型以外的屬性。** DynamoDB item 的屬性只有兩類：模型欄位與保留屬性 `PK`／`SK`／`target`／`entity`／`_revision`。VERSION item 不得為了省一次 S3 讀取而加 `step_count`，STEP 邊也不得加 `retired_at`；要保存的執行資訊一律寫進 operation 紀錄。這正是「應有步驟數只能由 S3 全文推得」的原因。

**DynamoDB item 轉模型一律走 `item_to_model`。** 它是 [Phase 08](./08-Phase08-分頁查詢與一致讀取基礎.md) 的模組函式：先去掉保留屬性（`PK`／`SK`／`target`／`entity`／`_revision`）再 `model_validate`。直接對 raw item 呼叫 `Feature.model_validate(item)` 會因為嚴格模型不接受多餘欄位而失敗，所以 `create_version` 取既有 Feature ID 時寫成 `item_to_model(item, Feature).feature_id`，不自己挑單一屬性。`scan_entity` 預設 `meta_only=True`，只回 `SK == META` 的 item，同前綴的關係邊（例如 `FEATURE#...` 上的邊）不會混進來。

**STEP 邊只帶 `type` 與 `text`。** `entity` 由 [Phase 07](./07-Phase07-S3物件與關係邊讀寫.md) 的 `put_edge` 自己從 PK 前綴算出，`attrs` 帶任何保留屬性都會被它丟 `PermanentError`；`tutorial_version` 與 `number` 由 `STEP#<version_id>#<n>` 還原，`feature_id` 由 `target` 還原。這與 [Phase 08](./08-Phase08-分頁查詢與一致讀取基礎.md) 的 `get_steps(version_id)`（`scan_entity("STEP")` + 前綴過濾）是同一組約定：寫入端少寫的欄位，讀取端必須算得出來。

## 7. TDD Tasks

三個 Task 共用同一組器材，**寫在 `tests/integration/test_create_version.py`，由 `test_version_complete.py` import**（原文寫「寫在 `tests/integration/conftest.py`」，但 00A §3.2 的 conftest owner 是 Phase 06、修改者只有 Phase 07 與 Phase 08，本 Phase 不在其中；moto 的 `repository`／`table`／`bucket` 三個 fixture 仍然來自 conftest）。內容：`fail_next(repository, name)` 讓 `repository.<name>` 的下一次呼叫丟 `TransientError` 模擬中斷（取代原文的 `fail_next_put_meta()`／`fail_next_put_edge()` 兩個鉤子；`repository` fixture 每個測試都是新的，直接覆寫 instance 屬性比 `monkeypatch` 少一層還原邏輯）；`seeded_feature` 先寫入 `FEATURE#Prepare` 與 `TUTORIAL#prepare-meeting`（`current_version=None`）；`published_v1` 在它之上再補一個 `published_at` 非空的 `prepare-meeting@v1`、它的 `tutorials/prepare-meeting/v1.md` 與 `v1.diff`，並把 `current_version` 切到 v1（只有 publish 成功才會切換，F37）；`ready_v2` 是已經跑完 `create_version` 的 v2，另外提供 `delete_md()` 等破壞方法。`version_plan(...)` 與 `four_step_content()` 是同檔的小工具：前者組出 `VersionPlan`，後者與 [Phase 21](./21-Phase21-教學內容與步驟引用驗證.md)、[Phase 22](./22-Phase22-Markdown與Diff私有產物.md) 同名同語意——`title="準備會議"`，四步編號 1–4、`type` 依序 `read`／`click_ui`／`click_ui`／`read`、`feature_id` 都是 `Prepare`、第 3 步文字 `開啟摘要。`，三份文件不可各寫一種形狀。

以下測試片段裡的 `repo` 一律寫成 `repository`（00A §3.2：integration fixture 名稱一律是 `repository`）；本文件列出的 fixture 參數若已由 `seeded_feature`／`published_v1` 回傳同一個 `Repository`，實作時不再重複宣告 `repository` 參數。

### Task 1：依固定順序寫出未發布版本

- [x] **Step 1：建立失敗測試**

```python
def test_create_version_writes_unpublished_version(seeded_feature):
    repository = seeded_feature
    plan = version_plan("prepare-meeting@v1", number=1, supersedes=None, reason="gap:c12")
    version = create_version(plan, four_step_content(), repository)
    assert version.published_at is None
    assert version.s3_key == "tutorials/prepare-meeting/v1.md"
    assert version.reason == "gap:c12"
    assert repository.object_exists("tutorials/prepare-meeting/v1.diff")
    assert repository.get_tutorial("prepare-meeting").current_version is None

def test_published_version_is_never_overwritten(published_v1):
    repository = published_v1
    plan = version_plan("prepare-meeting@v1", number=1, supersedes=None, reason="gap:c12")
    with pytest.raises(ContentError, match="已發布"):
        create_version(plan, four_step_content(), repository)
    # 「S3 與 DynamoDB 都不變」：VERSION#…@v1 上仍然只有 metadata item，一條邊都沒有多寫。
    assert [str(item["SK"]) for item in repository.query_pk(version_pk("prepare-meeting@v1"))] == ["META"]
```

- [x] **Step 2：執行並確認紅燈**

```bash
uv run pytest tests/integration/test_create_version.py -q
```

預期：FAIL，訊號包含 `cannot import name 'create_version'`。

- [x] **Step 3：建立最小實作**

```python
def create_version(plan, content, repository) -> TutorialVersion:
    existing = repository.get_version(plan.version_id)
    if existing is not None and existing.published_at is not None:
        raise ContentError(f"版本 {plan.version_id} 已發布，不可覆寫")
    known = frozenset(item_to_model(item, Feature).feature_id          # 不直接 model_validate(item)
                      for item in repository.scan_entity("FEATURE"))
    validate_content(content, known)
    md_key = markdown_key(plan.slug, plan.number)
    current_md = render_markdown(content)
    previous_md, previous_name = _previous_markdown(plan, repository)
    put_private_artifact(repository, md_key, current_md, MARKDOWN_CONTENT_TYPE)
    put_private_artifact(
        repository, diff_key(plan.slug, plan.number),
        make_diff(previous_md, current_md, previous_name=previous_name, current_name=md_key),
        DIFF_CONTENT_TYPE,
    )
    if existing is None:
        repository.put_meta(TutorialVersion(
            version_id=plan.version_id, slug=plan.slug, supersedes=plan.supersedes,
            reason=plan.reason, rules_applied=list(plan.rules_applied),
            s3_key=md_key, published_at=None))
    _write_edges(plan, content, repository)
    return _verified(plan.version_id, repository)
```

Phase 22 沒有把 content type 定成常數，本 Phase 在 `content.py` 定名（Phase 22 報告第 7 節第 5 點允許）：

```python
MARKDOWN_CONTENT_TYPE = "text/markdown; charset=utf-8"
DIFF_CONTENT_TYPE = "text/plain; charset=utf-8"
```

- [x] **Step 4：補上兩個私有輔助函式並跑綠燈**

```python
def _previous_markdown(plan, repository) -> tuple[str | None, str]:
    if plan.supersedes is None:
        return None, ""
    previous = repository.get_version(plan.supersedes)
    if previous is None:
        raise ContentError(f"找不到前一版 {plan.supersedes}，無法產生 diff")
    body = repository.get_object(previous.s3_key)
    if body is None:
        raise ContentError(f"前一版 {plan.supersedes} 缺少 S3 全文 {previous.s3_key}")
    return body.decode("utf-8"), previous.s3_key


def _verified(version_id: str, repository) -> TutorialVersion:
    problems = _missing_parts(version_id, repository)
    if problems:
        raise ContentError("版本核對失敗：" + "；".join(problems))
    version = repository.get_version(version_id)
    assert version is not None  # _missing_parts 已確認它存在
    return version
```

執行 `uv run pytest tests/integration/test_create_version.py -q`，預期兩個測試 PASS。

- [x] **Step 5：提交**

```bash
git add src/training_kb/content.py tests/integration/test_create_version.py
git commit -m "feat(content): 寫出未發布的教學版本"
```

### Task 2：三種關係邊與 target 一致

- [x] **Step 1：建立失敗測試**

```python
V2_PLAN = dict(number=2, supersedes="prepare-meeting@v1",
               reason="release:r_42", rules_applied=("R-007",))

def test_step_reference_edge_target_matches_sk(published_v1):
    repository = published_v1
    create_version(version_plan("prepare-meeting@v2", **V2_PLAN), four_step_content(), repository)
    rows = repository.query_pk("STEP#prepare-meeting@v2#3", consistent=True)
    assert len(rows) == 1
    assert rows[0]["SK"] == "REFERENCES#FEATURE#Prepare"
    assert rows[0]["target"] == "FEATURE#Prepare"
    assert rows[0]["entity"] == "STEP"
    assert set(rows[0]) == {"PK", "SK", "target", "entity", "type", "text"}

def test_supersedes_and_applied_to_edges_exist(published_v1):
    repository = published_v1
    create_version(version_plan("prepare-meeting@v2", **V2_PLAN), four_step_content(), repository)
    supersedes = repository.list_edges("VERSION#prepare-meeting@v2", "SUPERSEDES")
    assert [(row["SK"], row["target"]) for row in supersedes] == [
        ("SUPERSEDES#VERSION#prepare-meeting@v1", "VERSION#prepare-meeting@v1")]
    applied = repository.list_edges("RULE#R-007", "APPLIED_TO")
    assert [(row["SK"], row["target"]) for row in applied] == [
        ("APPLIED_TO#VERSION#prepare-meeting@v2", "VERSION#prepare-meeting@v2")]
    assert repository.get_version("prepare-meeting@v2").rules_applied == ["R-007"]

# 另外三條同檔測試：`get_steps` 能把四步完整還原（00A §3.6 的「寫入端少寫、讀取端算得出來」）、
# v1 沒有 SUPERSEDES 邊且 `v1.diff` 是 0 位元組、同 plan 第二次呼叫不新增版本也不重建 VERSION
# item（§8 Boundary）。
```

- [x] **Step 2：執行並確認紅燈**

```bash
uv run pytest tests/integration/test_create_version.py -q
```

預期：FAIL，因為此時只寫了 VERSION item，沒有任何邊。

- [x] **Step 3：建立最小實作**

```python
def _write_edges(plan, content, repository) -> None:
    version_key = version_pk(plan.version_id)
    for step in content.steps:
        repository.put_edge(
            step_pk(plan.version_id, step.number), "REFERENCES", feature_pk(step.feature_id),
            {"type": str(step.type), "text": step.text},
        )
    if plan.supersedes is not None:
        repository.put_edge(version_key, "SUPERSEDES", version_pk(plan.supersedes))
    for rule_id in plan.rules_applied:
        repository.put_edge(rule_pk(rule_id), "APPLIED_TO", version_key)
```

- [x] **Step 4：確認邊的權威來源與重寫行為**

`attrs` 只放 `type` 與 `text`：`entity` 是 `put_edge` 自己算的保留屬性，多傳會被丟 `PermanentError`；`tutorial_version`、`number`、`feature_id` 分別由 PK 與 `target` 還原，所以 Phase 08 的 `get_steps` 讀得回完整的 `TutorialStep`。`APPLIED_TO` 只依 `plan.rules_applied` 產生，不從前一版繼承（F29、D17）。邊的內容完全由 plan 與 content 決定，所以重送時重寫同一筆邊是安全的，不需要條件寫入。執行 `uv run pytest tests/integration/test_create_version.py -q`，預期整檔 PASS。

- [x] **Step 5：提交**

```bash
git add src/training_kb/content.py tests/integration/test_create_version.py
git commit -m "feat(content): 寫出版本的三種關係邊"
```

### Task 3：`verify_version_complete` 與部分寫入的保留

- [x] **Step 1：建立失敗測試**

```python
@pytest.mark.parametrize("break_it", ["delete_md", "delete_diff", "delete_step_edge",
                                      "delete_feature", "delete_supersedes_edge"])
def test_incomplete_version_is_not_complete(ready_v2, break_it):
    getattr(ready_v2, break_it)()
    assert verify_version_complete("prepare-meeting@v2", ready_v2.repository) is False

def test_interrupted_write_keeps_private_artifacts(seeded_feature):
    repository = seeded_feature
    fail_next(repository, "put_meta")
    plan = version_plan("prepare-meeting@v1", number=1, supersedes=None, reason="gap:c12")
    with pytest.raises(TransientError):
        create_version(plan, four_step_content(), repository)
    assert repository.object_exists("tutorials/prepare-meeting/v1.md")
    assert repository.get_version("prepare-meeting@v1") is None
    assert verify_version_complete("prepare-meeting@v1", repository) is False

# 另外五條同檔測試：未被破壞的 v2 回 `True`；`delete_applied_to_edge`／`delete_tutorial` 兩種
# 缺漏也回 `False`；一步兩條引用邊回 `False` 且 `create_version` 的訊息含「應恰好一條」
# （§8 Boundary）；連 VERSION item 都沒有時回 `False`；寫邊中斷後同一份 plan 重送會補齊
# （`fail_next(repository, "put_edge")`，設計 §8.2 的第三個中斷點）。
```

- [x] **Step 2：執行並確認紅燈**

```bash
uv run pytest tests/integration/test_version_complete.py -q
```

預期：FAIL，訊號包含 `cannot import name 'verify_version_complete'`。

- [x] **Step 3：建立最小實作**

```python
def verify_version_complete(version_id: str, repository: Repository) -> bool:
    return not _missing_parts(version_id, repository)


def _step_edge_problems(version_id, steps, repository) -> list[str]:
    problems: list[str] = []
    for step in steps:
        rows = repository.query_pk(step_pk(version_id, step.number), consistent=True)
        if len(rows) != 1:
            problems.append(f"第 {step.number} 步應恰好一條引用邊，實際 {len(rows)} 條")
            continue
        # SK 先收成 str：raw item 的值型別含 bytes，直接 f-string 會被 mypy strict 的
        # str-bytes-safe 擋下（而本專案不用 `# type: ignore`）。
        sort_key, target = str(rows[0].get("SK", "")), str(rows[0].get("target", ""))
        if not target.startswith("FEATURE#") or sort_key != edge_sk("REFERENCES", target):
            problems.append(f"第 {step.number} 步的 SK 與 target 不一致：{sort_key}")
        elif repository.get_feature(parse_pk(target)[1]) is None:
            problems.append(f"第 {step.number} 步引用的 Feature 不存在：{target}")
    return problems
```

- [x] **Step 4：組出 `_missing_parts` 並跑綠燈**

```python
def _has_edge(repository, pk: str, relation: str, target_pk: str) -> bool:
    sort_key = edge_sk(relation, target_pk)
    return any(row.get("SK") == sort_key
               for row in repository.query_pk(pk, sk_prefix=f"{relation}#", consistent=True))


def _missing_parts(version_id: str, repository: Repository) -> list[str]:
    version = repository.get_version(version_id)
    if version is None:
        return [f"找不到 VERSION item {version_id}"]
    slug, number = parse_version_id(version_id)
    md_key, df_key = markdown_key(slug, number), diff_key(slug, number)
    version_key = version_pk(version_id)
    problems = [f"找不到 TUTORIAL item {slug}"] if repository.get_tutorial(slug) is None else []
    if version.s3_key != md_key:
        problems.append(f"s3_key 應為 {md_key}，實際 {version.s3_key}")
    body = repository.get_object(md_key)
    if body is None:
        return problems + [f"缺少 S3 全文 {md_key}"]
    if not repository.object_exists(df_key):
        problems.append(f"缺少 S3 差異檔 {df_key}")
    steps = parse_markdown(body.decode("utf-8")).steps
    problems += _step_edge_problems(version_id, steps, repository)
    if version.supersedes is not None and not _has_edge(
            repository, version_key, "SUPERSEDES", version_pk(version.supersedes)):
        problems.append(f"缺少 SUPERSEDES 邊：{version.supersedes}")
    problems += [f"規則 {rule_id} 缺少 APPLIED_TO 邊" for rule_id in version.rules_applied
                 if not _has_edge(repository, rule_pk(rule_id), "APPLIED_TO", version_key)]
    return problems
```

核對全部用完整 PK 的 `query_pk(..., consistent=True)`（`APPLIED_TO` 是基表一致的 `scan_entity("RULE", meta_only=False)`），不查 GSI；應有步驟一律以 S3 全文 `parse_markdown().steps` 為準，沒有 `step_count` 可讀。執行 `uv run pytest tests/integration/test_version_complete.py -q`，預期五組破壞參數與中斷案例全部 PASS。

修正回合 1 依 review 把 `_has_edge` 換成 `_exact_edge_problems`（缺的與多的都是問題），並追加 `_extra_step_problems`、`_applied_to_problems`、`_expected_sk` 與 `_missing_parts` 的 `except ValueError` 護欄；同檔追加四條測試：多塞 STEP／多塞 `APPLIED_TO`／多塞 `SUPERSEDES` 三組 parametrize 都回 `False`，損壞的 `target` 回 `False` 而不是丟例外。`create_version` 端追加 `_planned_version`／`_reject_changed_version` 與兩條測試（同 plan 重送 OK；換 `reason`／`rules_applied` 重送丟 `ContentError` 且不寫任何邊；`version_id` 與 `slug`／`number` 不自洽丟 `ContentError`）。

- [x] **Step 5：提交**

```bash
git add src/training_kb/content.py tests/integration/test_version_complete.py
git commit -m "feat(content): 核對版本與關係是否齊全"
```

## 8. 驗收矩陣

| 路徑 | 輸入 | 預期資料結果 |
|---|---|---|
| Happy | v1 四步無規則；v2 帶 `supersedes=v1`、`rules_applied=("R-007",)` | v1 有 `published_at=None`、`s3_key` 指向 `v1.md`、四條 `REFERENCES` 邊與空 `v1.diff`；v2 另有 `SUPERSEDES` 與 `APPLIED_TO` 邊，`target` 等於 SK 終點。 |
| Failure | 目標版本已 `published_at` 非空 | `ContentError` 含「已發布」；S3 與 DynamoDB 都不變。 |
| Failure | 寫 VERSION item 時中斷 | 私有 `.md` 仍在、`verify_version_complete` 回 `False`、公開站沒有任何變化。 |
| Failure | 缺 `.diff`、缺步驟邊或引用的 Feature 不存在 | `verify_version_complete` 回 `False`，Phase 24 不得發布。 |
| Boundary | 同 plan 第二次呼叫 | 不新增版本、不重複建立 VERSION item，最終仍回 `True`。 |
| Boundary | 某步有兩條引用邊 | 回 `False`，訊息指出「應恰好一條」。 |

人工驗收：在 DynamoDB 主控台以 `VERSION#prepare-meeting@v2`、`STEP#prepare-meeting@v2#3`、`RULE#R-007` 三個 PK 各查一次，逐欄確認 `SK`、`target`、`published_at`；再確認公開站沒有 v2。不能只看測試顯示 PASS。

## 9. 常見錯誤與停止條件

| 症狀 | 原因 | 修正／停止 |
|---|---|---|
| 版本可發布但某步沒有引用邊 | 核對只看 VERSION item | 停止發布，補 `_step_edge_problems`。 |
| 核對用 GSI 讀不到剛寫的邊 | 用 `by_target` 取代基表 | 一律改 `query_pk(..., consistent=True)`。 |
| 失敗後刪掉 S3 產物 | 誤以為要「清乾淨」 | 保留私有產物讓重送沿用；刪除會讓同版號重試重算（F36）。 |
| `published_at` 被填成建立時間 | 把建立當成發布 | 固定寫 `None`；只有 Phase 24 能填值。 |
| `rules_applied` 從前一版複製 | 沿用原文也算套用 | 只寫本次 plan 的 ID；沿用不計（F29）。 |
| `put_edge` 丟 `PermanentError: edge attributes are reserved` | `attrs` 傳了 `entity`／`target`／`SK` | 保留屬性由 Phase 07 自己算；`attrs` 只放 `type` 與 `text`。 |
| 在 VERSION item 加 `step_count` 讓核對變快 | 想省一次 S3 讀取 | 停止：strict 模型會拒絕多餘屬性；應有步驟只能由 S3 全文推得。 |
| 核對回 `True`，但這一版多一個 `STEP#…#5`／多一條 `APPLIED_TO`／兩條 `SUPERSEDES` | 只驗「不缺」沒驗「不多」 | 步驟編號集合、`APPLIED_TO` 規則集合、`SUPERSEDES` 終點集合都要**恰等於**權威來源。 |
| 同版號換 `reason` 重送靜默成功、回傳舊值卻寫出新邊 | `existing is not None` 就直接沿用，沒比對內容 | 逐欄比對 plan 與既有 item，不同就 `ContentError`；比對放在任何寫入之前。 |
| `verify_version_complete` 丟 `ValueError` 把 Phase 24 打斷 | 損壞的 `target` 直接餵給 `edge_sk`／`parse_pk` | 經 `_expected_sk` 與 `except ValueError` 收斂成問題；關卡只回齊全／不齊全。 |

## 10. 來源與 Rule 對照

Rule 原文逐字取自 feature 檔；primary 歸屬依 [00B 需求覆蓋對照](./00B-需求覆蓋對照.md)。

- [建立教學版本.feature](../../spec/features/建立教學版本.feature)
  - Rule 3：「新版以 supersedes 關聯同一篇教學的前一版」→ **primary**，Task 2 的 `test_supersedes_and_applied_to_edges_exist` 直接斷言。
  - Rule 4：「每次建立版本都記錄引起變更的 reason」→ **primary**，Task 1 的 `test_create_version_writes_unpublished_version` 斷言 `version.reason == "gap:c12"`。
  - Rule 6：「TutorialVersion 的 s3_key 指向該版本完整內容」→ **primary**，同一個測試斷言 `s3_key` 等於 `tutorials/prepare-meeting/v1.md`。
  - Rule 8：「建立 TutorialStep 時保存 references Feature 邊」→ **primary**，Task 2 的 `test_step_reference_edge_target_matches_sk` 直接斷言。
  - Rule 9：「沒有 Feature 或引用多個 Feature 的步驟不可保存」→ 相關（primary 在 [Phase 21](./21-Phase21-教學內容與步驟引用驗證.md)）；本 Phase 只在寫入端再呼叫一次 `validate_content`，並由 `_step_edge_problems` 確認每步恰好一條引用邊。
  - Rule 10：「references 邊的 target 等於 SK 中的關係終點」→ 相關（primary 在 [Phase 07](./07-Phase07-S3物件與關係邊讀寫.md)）；本 Phase 在寫入端再確認一次，`test_step_reference_edge_target_matches_sk` 與 `_step_edge_problems` 都比對 `target` 與 SK 終點。
  - Rule 5、Rule 7（`.md`／`.diff` 路徑）→ 相關（primary 在 [Phase 22](./22-Phase22-Markdown與Diff私有產物.md)）；本 Phase 只呼叫它的 key 與寫入函式。
- 設計 §8.2：建立與發布是兩步；S3 成功但關係未完成時保留不可公開產物，不刪掉後偽稱成功。
- 設計 §9.1、§9.2：VERSION／STEP 的鍵與三種邊格式；§10：核對用基表一致讀取，不用最終一致的 GSI。
- 決策 D25（未發布即 `published_at=null`）、D17（`rules_applied` 是套用關係的權威）、F36（保留待完成版本）、F29（沿用原文不算套用）。

## 11. 完成清單

- [x] 兩個公開函式的簽名符合本文件；寫入順序為 S3 產物 → VERSION → STEP／邊 → 自我核對。
- [x] 新版本的 `published_at` 一律是 `None`，`current_version` 不變。
- [x] `REFERENCES`、`SUPERSEDES`、`APPLIED_TO` 三種邊都有 `target` 等於 SK 終點的 assertion。
- [x] VERSION 與 STEP item 的屬性只有模型欄位加上 `PK`／`SK`／`target`／`entity`／`_revision`，沒有 `step_count`。
- [x] 已發布版本不可覆寫；同 plan 重送不新增版本；五種缺漏都讓 `verify_version_complete` 回 `False`。
- [x] 中斷後私有 S3 產物仍在，且公開站無任何變化。
- [x] 建立教學版本 Rule 3、4、6、8 各有直接 assertion；Rule 5、7、9、10 只標為相關。
- [x] 整合測試已實際執行；沒有把綠燈說成 O3 發布 gate 已通過。
- [x] 核對同時驗「不缺」與「不多」：多出來的 STEP item、`APPLIED_TO` 邊、`SUPERSEDES` 邊都讓 `verify_version_complete` 回 `False`（修正回合 1）。
- [x] 同版號換內容重送一律 `ContentError` 且不留下任何產物或邊；plan 的 `version_id` 與 `slug`／`number` 必須自洽（修正回合 1）。
- [x] 損壞的關係資料收斂成問題清單，`verify_version_complete` 不丟 `ValueError`（修正回合 1）。
