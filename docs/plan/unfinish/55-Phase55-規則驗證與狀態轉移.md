# Phase 55：規則驗證與狀態轉移實作計畫

> **給實作者：** 依 checkbox 逐步執行；每個 Task 先建立失敗測試，再寫最小實作。執行時使用 `superpowers:executing-plans` 或同等逐項流程。

**目標：** 以同一篇教學套用前後的已發布版本為對照，判定一條規則在一個批次內是否**兩項都嚴格改善**，再由唯一寫入者把 `candidate`／`active`／`retired` 寫回 RULE item。

**架構：** `evaluate_batch` 用 Phase 54 的 `version_metrics` 取得前後指標並輸出 `RuleEvaluation`（同時帶兩個差值）；`next_status` 是純函式狀態機；`apply_rule_status` 是全系統**唯一**能寫 `RULE.status` 與最近驗證時間的入口；`validate_rules_action` 把這三件事接到 Phase 54 的 analytics Lambda。Feedback Review 只提出 candidate，永遠不改 status。

**技術：** Python 3.12、`dataclasses`、`typing.Literal`、Phase 54 的 `VersionMetrics`、Phase 17 的 `ConflictJudgement` schema、pytest。

## 全域限制

- 唯一主來源是 [Training KB 設計 §7.6、§12.1、§12.2、§12.3、§18 O7](../../design/training-kb.md)。`O4`、`O7` 是設計 §18「待確認事項」的編號，兩者目前都沒有規格答案。
- 前置為 [Phase 54：重開票與呼叫規則指標](./54-Phase54-重開票與呼叫規則指標.md)，未通過就停止。O4 的窗口端點尚未核定，本 Phase 的 rate 比較同樣帶著這個未定狀態，不得宣稱重開票率已有規格答案。下一階段是 [Phase 56：O7 核定 Demo 種子資料](./56-Phase56-O7核定Demo種子資料.md)。
- **本 Phase 只用自含、明示為非核定的合成 fixture 驗證程式邏輯。** fixture 全部寫在 `tests/unit/conftest.py` 與測試檔內，不讀 `demo/seed/`、不引用任何真實專案回饋。測試綠燈只證明狀態機正確，**不得**寫成「R-007 已成為 active」「種子已核定」或「O7 已通過」。
- O7 由 Phase 56 的真實種子與**維護者核定紀錄**關閉，與本 Phase 的程式重算是兩個不同條件。設計 §12.3：前後差值只是**觀察結果**，不宣稱已證明因果，也不得充當「省時」或「降低支援成本」的實測數字。
- 本階段不做：不提出新規則、不合併規則 ID、不搬移 evidence、不改規則文字、不建立版本、不發布、不寫 `applied_to` 投影、不自行呼叫模型產生衝突判定。
- 以下程式檔均是實作時預計建立或修改；本計畫本身不代表它們已存在。

---

## 1. 你在整體流程的位置

```text
Phase 47 propose_candidate ---> RULE#R-007 status=candidate
Phase 53/54 version_metrics(before) ----+---- version_metrics(after)
                                        v
     +-----------------------------------------------------------+
     | [你在這裡] evaluate_batch -> next_status                   |
     |            -> apply_rule_status（唯一寫入者）              |
     |            -> operations/rules/validated_at.json           |
     +-----------------------------------------------------------+
          |                   |                    |
          v                   v                    v
       active            candidate（不變）       retired
          |
          v  Phase 19 load_validated_at + select_active_rules -> 正式寫作
```

Feedback Review（Phase 48）與 Analytics（本 Phase）分工固定：前者只寫 `status=candidate` 的新 RULE，後者是唯一能改既有 `status` 的地方。

## 2. 完成後看得到什麼

輸入一個自含批次：`prepare-meeting@v1`（套用前，平均 2.875、rate 0.7）與 `prepare-meeting@v2`（套用後，平均 4.4、rate 0.2），規則 `R-007`：

```text
evaluate_batch(batch, approved=APPROVED, repository=fake_repo)
    -> RuleEvaluation(rule_id="R-007", verdict="improved", approved=True, decidable=True,
                      before_average=2.875, after_average=4.4, average_delta=1.525,
                      before_rate=0.7,      after_rate=0.2,   rate_delta=-0.5)
next_status("candidate", [improved_eval], conflict=None)  -> "active"
apply_rule_status("R-007", "active", repository=repo, now=NOW)
    -> AuthoringRule(rule_id="R-007", status="active", ...)
    -> operations/rules/validated_at.json = {"R-007": "2026-09-01T00:00:00Z"}
```

把後版 rate 改成 0.7（持平）時 `verdict` 變 `not_improved`、`next_status` 回 `candidate`，`apply_rule_status` 不被呼叫、RULE item 不變。把後版瀏覽者清空時 `rate` 為 `None`、`verdict` 變 `undecidable`、`decidable` 為 `False`，狀態一樣不變。

## 3. 名詞小抄

| 名詞 | 白話意思 |
|---|---|
| 批次（SeedBatch） | 一次比較所需的完整資料：哪條規則、哪一篇教學、套用前與套用後各是哪一個**已發布**版本。 |
| 核定 | 維護者對這個批次簽過名。`approved_by` 為 `None` 代表尚未核定，任何狀態都不能改。 |
| 嚴格改善 | 後版平均 **>** 前版平均，**且** 後版 rate **<** 前版 rate；相等不算。 |
| 差值（delta） | 後版減前版：`average_delta` 為正代表評分變好，`rate_delta` 為負代表重開票率下降。 |
| 不可判定 | 資料不足以下結論；保持原狀態，不算成失敗批次，也不能因此退役。 |
| 不重疊 | 兩個批次沒有共用任何 `version_id`；連續兩個不重疊且未改善才退役。 |
| curation | 只把可能相近的規則分成群組給人看，不合併 ID、不改文字、不改 status。 |

## 4. 預計檔案

| 動作 | 路徑 | 責任 |
|---|---|---|
| 新增 | `src/training_kb/analytics/validation.py` | `SeedBatch`、`RuleEvaluation`、`evaluate_batch`、`next_status`、`validated_conflict`、`curation_groups`。 |
| 修改 | `src/training_kb/analytics/status_writer.py` | 補上寫入端 `LEGAL_TRANSITIONS`、`record_evaluation`、`apply_rule_status`；**檔案與讀取端 `VALIDATED_AT_KEY`、`load_validated_at` 由 [Phase 40](40-Phase40-Ticket-CREATE與KEEP.md) 首建**（00A §3.2、D-28），本 Phase 沿用同檔同名，不重新宣告也不另開一份。全系統唯一寫 `RULE.status` 與最近驗證時間的位置。 |
| 修改 | `src/training_kb/handlers/analytics.py` | 加上 `action: "validate_rules"` 分支（D-56；`handler` 與 `action: "metrics"` 由 Phase 54 產出）。 |
| 修改 | `tests/unit/conftest.py` | 自含合成 fixture：`fake_repo`、`batch`、`rules`。 |
| 測試 | `tests/unit/test_rule_validation.py` | 對照選取、兩個差值、兩項改善、不可判定、連續兩批退役、衝突與 curation。 |
| 測試 | `tests/unit/test_rule_status_writer.py` | 合法／非法轉移、未核定不寫、唯一寫入者、`validated_at.json`、handler 分支。 |

## 5. 固定介面

### Consumes

```text
VersionMetrics(version_id, published_at, average, sample_size, negative_ids, reopen)   # P54
ReopenStats(count, reopen_users, viewers, rate)                                        # P54
version_metrics(version_id, *, repository, approved, project_id) -> VersionMetrics     # P54
handler(event, context)：analytics Lambda 入口，已處理 action "metrics"                # P54，D-56
AuthoringRule(rule_id, rule, applies_when: StepType, evidence, status: RuleStatus,
              applied_to, derived_from) / Feedback / TutorialVersion                   # P04
RuleStatus、StepType：P03 的 StrEnum（成員大寫、值小寫），不得改寫成 Literal          # P03
ConflictJudgement：P17 的 JSON schema，required 欄位 conflicts / rule_ids / evidence；
    由 Writer.generate_json(system, user, schema, *, operation_id, node) -> dict 產生（D-02）
rule_pk(rule_id) / feedback_pk(feedback_id)                                            # P05
Repository.get_meta(pk, model, *, consistent=True) / get_version(version_id)           # P06
Repository.update_meta(pk, changes, *, expected_revision: int) -> int                  # P06
Repository.revision_of(pk) -> int                                                      # P06，D-27
Repository.get_object(key) / put_object(key, body, content_type, *, if_none_match)     # P07
VALIDATED_AT_KEY / load_validated_at(repository)：analytics/status_writer.py 的讀取端，
    由 P40 首建；本 Phase 在同一支檔補寫入端，兩邊同檔同名                              # P40，D-28
parse_version_id(value) -> tuple[str, int] / to_iso(dt) / parse_iso(value)
PermanentError                                                                # P20／P02
```

### Produces

```python
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

Verdict = Literal["improved", "not_improved", "undecidable"]
VALIDATED_AT_KEY = "operations/rules/validated_at.json"

@dataclass(frozen=True)
class SeedBatch:
    batch_id: str
    rule_id: str
    slug: str
    before_version_id: str
    after_version_id: str
    cluster_id: str             # 只寫進證據檔供人工核對，不參與判斷
    project_id: str
    synthetic: bool             # MVP 一律 True：只用明示合成證據
    approved_by: str | None     # None 代表尚未核定
    approved_at: datetime | None

@dataclass(frozen=True)
class RuleEvaluation:
    batch_id: str
    rule_id: str
    verdict: Verdict
    reasons: tuple[str, ...]
    before_average: float | None
    after_average: float | None
    before_rate: float | None
    after_rate: float | None
    version_ids: frozenset[str]   # 判斷批次是否重疊用
    approved: bool                # 批次是否已核定
    average_delta: float | None   # after_average - before_average（MET Rule 6）
    rate_delta: float | None      # after_rate - before_rate（MET Rule 6）
    decidable: bool               # verdict != "undecidable"

def evaluate_batch(batch: SeedBatch, *, approved: frozenset[str],
                   repository: "Repository") -> RuleEvaluation: ...
def validated_conflict(judgement: Mapping[str, object], candidate: "AuthoringRule", *,
                       repository: "Repository") -> Mapping[str, object] | None: ...
def next_status(current: "RuleStatus", evaluations: Sequence[RuleEvaluation],
                conflict: Mapping[str, object] | None) -> "RuleStatus": ...
def curation_groups(rules: Sequence["AuthoringRule"]) -> tuple[tuple[str, ...], ...]: ...
def record_evaluation(evaluation: RuleEvaluation, *, repository: "Repository") -> str: ...
def apply_rule_status(rule_id: str, status: "RuleStatus", *, repository: "Repository",
                      now: datetime) -> "AuthoringRule": ...
def load_validated_at(repository: "Repository") -> dict[str, datetime]: ...
def validate_rules_action(event: dict, *, repository: "Repository",
                          approved: frozenset[str]) -> dict: ...
```

`VALIDATED_AT_KEY` 與 `load_validated_at` 在上面同時出現在 Consumes 與 Produces，是因為它們**已經存在**（Phase 40 首建讀取端），本 Phase 只是在同一支 `analytics/status_writer.py` 補上寫入端；實作時不要再寫一次常數或函式定義，第 7 節重貼它們只是為了讓片段可讀。

第 7 節的實作片段一律省略 import：模型與 helper 照上面 Consumes 的來源（`from training_kb.models import AuthoringRule, Feedback, RuleStatus` 等），另外用到標準庫的 `json` 與 `dataclasses.asdict`。

兩個容易接錯的地方：`approved` 這個關鍵字參數是 Phase 43 的**回饋類別**核定表，與 `SeedBatch.approved_by` 的**批次核定**是兩回事（命名沿用 Phase 44、47、53，不改名）；`next_status` 只接受**已通過 `validated_conflict` 的判定**，它是純函式，沒有 repository 可以查 `rule_ids` 是否存在，把模型原始輸出直接餵進去是錯誤用法。

## 6. 設計細節

### 6.1 evaluate_batch 的判斷順序

依序檢查，任何一關沒過就以括號內的 reason 回 `undecidable`，七關全過才做第八步比較：前後 `TutorialVersion` 都讀得到（`missing_version`）→ 兩者 `slug` 都等於 `batch.slug`（`cross_tutorial`）→ 兩者 `published_at` 都非 `None`（`unpublished_comparison`）→ before 版號 < after 版號（`wrong_order`；版號用 `parse_version_id(...)[1]` 取得，不從字串排序猜）→ `approved_by` 與 `approved_at` 都有值（`batch_not_approved`）→ 兩版 `average` 都非 `None`（`missing_average`）→ 兩版 `reopen.rate` 都非 `None`（`zero_denominator`）→ **`after.average > before.average` 且 `after.rate < before.rate`** 成立回 `improved`，否則回 `not_improved`。

無論落在哪一關，`RuleEvaluation` 都會填上能算得出來的 `average_delta` 與 `rate_delta`（缺值為 `None`），這兩個差值就是 MET Rule 6 要求的「評分差與同題重開票率差」。`undecidable` 與 `not_improved` 必須分開：設計 §12.2 明寫「零分母、缺平均、未完整載入批次時，不作有效／無效判定」，而「線上樣本不足不算失敗批次」——把不可判定併進未改善，會讓兩個資料不足的批次直接把規則退役。

### 6.2 next_status 狀態機

```text
                +-- 已驗證衝突（只對 candidate） ------> retired
  candidate ----+-- 最新已核定且可判定的批次 improved -> active
                +-- 連續兩個不重疊已核定 not_improved -> retired
                +-- 其餘（含 undecidable、單項改善、持平） -> candidate

  active -------+-- 連續兩個不重疊已核定 not_improved -> retired
                +-- 其餘 -----------------------------> active

  retired ------------------------------------------> retired（不自動復活）
```

**本計畫選擇：** 設計 §12.2 沒有規定三個判定誰先誰後，本 Phase 固定為「`retired` 終態 → 已驗證衝突 → 連續兩批未改善 → 最新 improved」，讓同一組輸入永遠得到同一個結果。`evaluations` 由呼叫端依批次核定時間**升序**傳入，函式只看其中 `approved and decidable` 的項目，「最新」就是這串的最後一個。

四個不可放寬的條件：**（1）兩項都要**——只有平均提高、或只有 rate 下降、或任一項持平，一律 `not_improved`；**（2）對照只能是同一篇套用前的已發布版本**，不用未發布版本也不跨教學湊對照；**（3）退役要兩個不重疊的已核定批次**——共用任何 `version_id` 就算重疊、只能當一批，`undecidable` 不進這個計數；**（4）不覆蓋既有 active**——衝突判定只能退役提出衝突的那條 candidate。

`validated_conflict` 是採用衝突判定的唯一入口：`conflicts` 為真、`rule_ids` 非空且每一個都存在、目前為 `active`、`applies_when` 與本 candidate 相同（型別是 `StepType`，寫成 `other.applies_when == candidate.applies_when`，不是字串運算式，見 D-10）、`evidence` 非空且每個 Feedback ID 都能回查。任一項不成立就回 `None`，等於沒有衝突判定。模型只負責提出判斷與證據（決策 F55），Analytics 驗證後才寫狀態。

`curation_groups` 對應 VAL Rule 7：只把**非 retired** 的規則依 `applies_when` 分群（**本計畫選擇**：D16 的 MVP 只允許單一 `step.type` 等值條件，所以「相近」在 MVP 就只能以適用範圍表示），群內依 `rule_id` 升序、群之間依 `applies_when` 值升序，單獨一條不成群。它不寫任何資料、不回傳 status，只產生供人工檢視的清單。

### 6.3 唯一寫入者與最近驗證時間

`apply_rule_status` 是全系統唯一寫 `RULE.status` 的地方（VAL Rule 8），做四件事：（1）讀出 RULE item，不存在丟 `PermanentError`；（2）`status` 與目標相同時**跳過** `update_meta`（不製造無意義的 revision 位移），其餘步驟照做，所以同一批次重跑兩次結果相同；（3）只允許 `candidate -> active`、`candidate -> retired`、`active -> retired`，其餘（含 `retired -> active`）丟 `PermanentError`，寫入用 `update_meta(..., expected_revision=repository.revision_of(pk))`（D-27）避免靜默覆蓋；（4）把最近驗證時間併進單一私有檔 `operations/rules/validated_at.json`（`VALIDATED_AT_KEY`，內容 `{rule_id: ISO 時間}`）整檔覆寫，`to_iso` 不會自己截微秒（Phase 02 明訂），所以寫入前先 `now.replace(microsecond=0)`。

**最近驗證時間只有這一個權威位置**（D-28）。`AuthoringRule` 沒有 `validated_at` 欄位（D-40：item 屬性 = 模型欄位 + `RESERVED_ATTRS`，沒有第三類），Phase 19 的呼叫端與 Phase 40／49–52 一律用 `load_validated_at(repository)` 讀它。每批證據另由 `record_evaluation` 寫成 `operations/analytics/rule-validation/<rule_id>/<batch_id>.json`，那是給人看的佐證，不是 `validated_at_by_rule` 的來源。`applied_to` 仍由 Phase 28 從 `rules_applied` 重建，本 Phase 不碰。

## 7. TDD Tasks

### Task 1：批次評估、兩個差值與不可判定

- [ ] **Step 1：先補自含 fixture，再寫失敗測試**

在 `tests/unit/conftest.py` 追加三個 fixture，全部是明示合成資料（`approved_by` 只是欄位值，不是維護者核定）：

- `fake_repo`：假 Repository，內含 `R-006`（active、`click_ui`）、`R-007`（candidate、`click_ui`）、`R-013`（active、`read`）三條 `AuthoringRule`，每條 `evidence` 都是 `["fx_1"…"fx_5"]` 五個不同 ID（Phase 04 的下限），以及 `prepare-meeting@v1`／`@v2` 兩個已發布 `TutorialVersion`。`get_meta` 依 `pk` 前綴分派：`RULE#` 回上面三條，`FEEDBACK#` 只回答「這個 ID 在不在 `fx_1`…`fx_5` 裡」（`validated_conflict` 只需要存在性）。它另外提供 `set_version(version_id, *, slug, published)`、`seed_metrics(前平均, 後平均, 前rate, 後rate)`、`seed_rule(rule_id, status)` 三個測試捷徑，並用 `monkeypatch` 把 `validation.version_metrics` 換成查 `seed_metrics` 表的函式；`updated`／`objects` 兩個 dict 記錄所有寫入。指標預設值就是 2.875／4.4／0.7／0.2。
- `batch`：`SeedBatch(batch_id="fixture-b1", rule_id="R-007", slug="prepare-meeting", before_version_id="prepare-meeting@v1", after_version_id="prepare-meeting@v2", cluster_id="c12", project_id="fixture", synthetic=True, approved_by="fixture-only-not-o7", approved_at=NOW)`。
- `rules`：`fake_repo` 的三條再加一條 retired 規則，用來驗 curation 不收 retired。

`version_metrics` 換成查表，是因為「由原始回饋重算出 2.875／4.4」是 Phase 53／54 的測試責任，Phase 56 還會用真實種子再驗一次；本 Phase 要驗的是**比較與狀態轉移**。

```python
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from training_kb.analytics.validation import evaluate_batch

NOW = datetime(2026, 9, 1, tzinfo=UTC)
APPROVED = frozenset({"找不到按鈕", "缺少資訊"})

def test_evaluate_batch_marks_improved_from_self_contained_fixture(fake_repo, batch):
    result = evaluate_batch(batch, approved=APPROVED, repository=fake_repo)
    assert result.verdict == "improved"
    assert (result.before_average, result.after_average) == (2.875, 4.4)
    assert (result.before_rate, result.after_rate) == (0.7, 0.2)

def test_evaluation_reports_both_deltas(fake_repo, batch):
    result = evaluate_batch(batch, approved=APPROVED, repository=fake_repo)
    assert round(result.average_delta, 3) == 1.525
    assert round(result.rate_delta, 3) == -0.5
    assert result.decidable is True

def test_evaluate_batch_is_undecidable_when_batch_is_not_approved(fake_repo, batch):
    result = evaluate_batch(replace(batch, approved_by=None, approved_at=None),
                            approved=APPROVED, repository=fake_repo)
    assert result.verdict == "undecidable"
    assert "batch_not_approved" in result.reasons
    assert result.decidable is False
```

- [ ] **Step 2：執行並確認紅燈**

執行 `uv run pytest tests/unit/test_rule_validation.py -q`，預期 FAIL 且訊號包含 `cannot import name 'evaluate_batch'`。

- [ ] **Step 3：建立最小實作**

```python
def _batch_problems(batch, before, after):
    reasons: list[str] = []
    if before is None or after is None:
        reasons.append("missing_version")
    elif {before.slug, after.slug} != {batch.slug}:
        reasons.append("cross_tutorial")
    elif before.published_at is None or after.published_at is None:
        reasons.append("unpublished_comparison")
    elif parse_version_id(before.version_id)[1] >= parse_version_id(after.version_id)[1]:
        reasons.append("wrong_order")
    if batch.approved_by is None or batch.approved_at is None:
        reasons.append("batch_not_approved")
    return tuple(reasons)

def _delta(before, after):
    return None if before is None or after is None else after - before

def _result(batch, verdict, reasons, before=None, after=None):
    avg = [None if item is None else item.average for item in (before, after)]
    rate = [None if item is None else item.reopen.rate for item in (before, after)]
    return RuleEvaluation(
        batch_id=batch.batch_id, rule_id=batch.rule_id, verdict=verdict, reasons=reasons,
        before_average=avg[0], after_average=avg[1], before_rate=rate[0], after_rate=rate[1],
        version_ids=frozenset({batch.before_version_id, batch.after_version_id}),
        approved=batch.approved_by is not None and batch.approved_at is not None,
        average_delta=_delta(*avg), rate_delta=_delta(*rate),
        decidable=verdict != "undecidable")

def evaluate_batch(batch, *, approved, repository):
    before_version = repository.get_version(batch.before_version_id)
    after_version = repository.get_version(batch.after_version_id)
    reasons = _batch_problems(batch, before_version, after_version)
    if reasons:
        return _result(batch, "undecidable", reasons)
    shared = {"repository": repository, "approved": approved, "project_id": batch.project_id}
    before = version_metrics(batch.before_version_id, **shared)
    after = version_metrics(batch.after_version_id, **shared)
    if before.average is None or after.average is None:
        return _result(batch, "undecidable", ("missing_average",), before, after)
    if before.reopen.rate is None or after.reopen.rate is None:
        return _result(batch, "undecidable", ("zero_denominator",), before, after)
    improved = after.average > before.average and after.reopen.rate < before.reopen.rate
    return _result(batch, "improved" if improved else "not_improved", (), before, after)
```

- [ ] **Step 4：補四個不可判定案例並跑綠燈**

```python
@pytest.mark.parametrize("prepare, reason", [
    (lambda repo: repo.set_version("prepare-meeting@v2", published=False),
     "unpublished_comparison"),
    (lambda repo: repo.set_version("prepare-meeting@v1", slug="share-summary"), "cross_tutorial"),
    (lambda repo: repo.seed_metrics(2.875, None, 0.7, 0.2), "missing_average"),
    (lambda repo: repo.seed_metrics(2.875, 4.4, 0.7, None), "zero_denominator"),
])
def test_incomplete_batches_are_undecidable(fake_repo, batch, prepare, reason):
    prepare(fake_repo)
    result = evaluate_batch(batch, approved=APPROVED, repository=fake_repo)
    assert result.verdict == "undecidable"
    assert result.decidable is False and reason in result.reasons
```

```bash
uv run pytest tests/unit/test_rule_validation.py -q
```

預期：全部 PASS，且沒有任何案例回 `not_improved`。

- [ ] **Step 5：提交**

```bash
git add src/training_kb/analytics/validation.py tests/unit/conftest.py \
        tests/unit/test_rule_validation.py
git commit -m "feat(analytics): 以同篇前後版本評估規則批次"
```

### Task 2：兩項嚴格改善、連續兩批退役、衝突與 curation

- [ ] **Step 1：建立參數化失敗測試**

```python
from training_kb.analytics.validation import (RuleEvaluation, curation_groups, next_status,
                                              validated_conflict)

def ev(batch_id, verdict, versions=("a@v1", "a@v2"), approved=True):
    """測試檔內的本地小工具：組出只保留判定所需欄位的 RuleEvaluation。"""
    return RuleEvaluation(
        batch_id=batch_id, rule_id="R-007", verdict=verdict, reasons=(),
        before_average=None, after_average=None, before_rate=None, after_rate=None,
        version_ids=frozenset(versions), approved=approved,
        average_delta=None, rate_delta=None, decidable=verdict != "undecidable")

@pytest.mark.parametrize("before_avg, after_avg, before_rate, after_rate, expected", [
    (2.875, 4.4, 0.7, 0.2, "improved"),        # 兩項都嚴格改善
    (2.875, 4.4, 0.7, 0.7, "not_improved"),    # rate 持平
    (2.875, 2.875, 0.7, 0.2, "not_improved"),  # 平均持平
    (2.875, 4.4, 0.2, 0.7, "not_improved"),    # rate 反而上升
    (4.4, 2.875, 0.7, 0.2, "not_improved"),    # 平均反而下降
])
def test_only_two_strict_improvements_count(fake_repo, batch, before_avg, after_avg,
                                            before_rate, after_rate, expected):
    fake_repo.seed_metrics(before_avg, after_avg, before_rate, after_rate)
    assert evaluate_batch(batch, approved=APPROVED, repository=fake_repo).verdict == expected

def test_candidate_needs_improved_to_become_active():
    assert next_status("candidate", [ev("b1", "improved")], None) == "active"
    assert next_status("candidate", [ev("b1", "not_improved")], None) == "candidate"
    assert next_status("candidate", [ev("b1", "undecidable")], None) == "candidate"
    assert next_status("retired", [ev("b1", "improved")], None) == "retired"
```

- [ ] **Step 2：執行並確認紅燈**

執行 `uv run pytest tests/unit/test_rule_validation.py -q`，預期 FAIL 且訊號包含 `cannot import name 'next_status'`。

- [ ] **Step 3：建立最小實作**

```python
def _decisive(evaluations):
    return [item for item in evaluations if item.approved and item.decidable]

def _two_unimproved(evaluations):
    decisive = _decisive(evaluations)
    if len(decisive) < 2:
        return False
    last, previous = decisive[-1], decisive[-2]
    return (last.verdict == "not_improved" and previous.verdict == "not_improved"
            and not (last.version_ids & previous.version_ids))

def next_status(current, evaluations, conflict):
    current = RuleStatus(current)
    if current is RuleStatus.RETIRED:
        return current
    if conflict is not None and current is RuleStatus.CANDIDATE:
        return RuleStatus.RETIRED
    if _two_unimproved(evaluations):
        return RuleStatus.RETIRED
    decisive = _decisive(evaluations)
    if current is RuleStatus.CANDIDATE and decisive and decisive[-1].verdict == "improved":
        return RuleStatus.ACTIVE
    return current

def validated_conflict(judgement, candidate, *, repository):
    rule_ids = judgement.get("rule_ids") or []
    evidence = judgement.get("evidence") or []
    if not judgement.get("conflicts") or not rule_ids or not evidence:
        return None
    for rule_id in rule_ids:
        other = repository.get_meta(rule_pk(rule_id), AuthoringRule)
        if other is None or other.status is not RuleStatus.ACTIVE:
            return None
        if other.applies_when != candidate.applies_when:
            return None
    if any(repository.get_meta(feedback_pk(item), Feedback) is None for item in evidence):
        return None
    return judgement

def curation_groups(rules):
    buckets: dict[str, list[str]] = {}
    for rule in rules:
        if rule.status is RuleStatus.RETIRED:
            continue
        buckets.setdefault(rule.applies_when.value, []).append(rule.rule_id)
    return tuple(tuple(sorted(ids)) for _, ids in sorted(buckets.items()) if len(ids) > 1)
```

`next_status` 回的是 `RuleStatus`；它是 StrEnum，所以測試裡的 `== "active"` 仍然成立，回傳值也可以直接丟給 `apply_rule_status`。

- [ ] **Step 4：補退役、重疊、衝突與 curation 測試並跑綠燈**

```python
def test_two_non_overlapping_unimproved_batches_retire_the_rule():
    b1 = ev("b1", "not_improved", versions=("a@v1", "a@v2"))
    b2 = ev("b2", "not_improved", versions=("a@v3", "a@v4"))
    assert next_status("active", [b1, b2], None) == "retired"
    assert next_status("candidate", [b1, b2], None) == "retired"

def test_overlapping_undecidable_or_unapproved_batches_never_retire():
    over = [ev("b1", "not_improved", versions=("a@v1", "a@v2")),
            ev("b2", "not_improved", versions=("a@v2", "a@v3"))]
    weak = [ev("b3", "undecidable", versions=("a@v1", "a@v2")),
            ev("b4", "undecidable", versions=("a@v3", "a@v4"))]
    unapproved = [ev("b5", "not_improved", versions=("a@v1", "a@v2"), approved=False),
                  ev("b6", "not_improved", versions=("a@v3", "a@v4"), approved=False)]
    for batches in (over, weak, unapproved):
        assert next_status("active", batches, None) == "active"

def test_conflict_retires_only_the_candidate(fake_repo):
    judgement = {"conflicts": True, "rule_ids": ["R-006"], "evidence": ["fx_1"]}
    conflict = validated_conflict(judgement, fake_repo.rules["R-007"], repository=fake_repo)
    assert next_status("candidate", [], conflict) == "retired"
    assert next_status("active", [], conflict) == "active"

@pytest.mark.parametrize("broken", [{"rule_ids": ["R-999"]},   # 指向不存在的規則
                                    {"rule_ids": ["R-013"]},   # applies_when 不同
                                    {"evidence": ["fx_999"]},  # 證據回查不到
                                    {"evidence": []}])
def test_unverifiable_conflict_is_ignored(fake_repo, broken):
    judgement = {"conflicts": True, "rule_ids": ["R-006"], "evidence": ["fx_1"]} | broken
    assert validated_conflict(judgement, fake_repo.rules["R-007"],
                              repository=fake_repo) is None

def test_curation_only_groups_and_never_changes_status(fake_repo, rules):
    assert curation_groups(rules) == (("R-006", "R-007"),)   # read 只有一條，不成群
    assert fake_repo.updated == {}
```

```bash
uv run pytest tests/unit/test_rule_validation.py -q
```

預期：全部 PASS；`retired` 輸入永遠回 `retired`，`curation_groups` 沒有任何寫入。

- [ ] **Step 5：提交**

```bash
git add src/training_kb/analytics/validation.py tests/unit/test_rule_validation.py
git commit -m "feat(analytics): 實作規則狀態轉移條件與 curation 分群"
```

### Task 3：唯一寫入者、最近驗證時間與 handler 的 validate_rules action

Phase 54 依 D-56 產出 `src/training_kb/handlers/analytics.py::handler(event, context)` 並處理 `action: "metrics"`；本 Task 只加第二個分支。**該檔不存在時停止**，先回 Phase 54 補入口。

- [ ] **Step 1：建立失敗測試**（`tests/unit/test_rule_status_writer.py`，`NOW`／`APPROVED` 與 Task 1 同值）

```python
import json
from dataclasses import asdict

import pytest

from training_kb.analytics.status_writer import (VALIDATED_AT_KEY, apply_rule_status,
                                                 load_validated_at, record_evaluation)
from training_kb.analytics.validation import evaluate_batch
from training_kb.errors import PermanentError
from training_kb.handlers.analytics import validate_rules_action

def test_apply_rule_status_writes_status_and_validation_time(fake_repo):
    rule = apply_rule_status("R-007", "active", repository=fake_repo, now=NOW)
    assert rule.status == "active"
    assert fake_repo.updated["RULE#R-007"]["status"] == "active"
    table = json.loads(fake_repo.objects[VALIDATED_AT_KEY].decode("utf-8"))
    assert table["R-007"] == "2026-09-01T00:00:00Z"
    assert load_validated_at(fake_repo)["R-007"] == NOW

def test_record_evaluation_writes_one_evidence_file_per_batch(fake_repo, batch):
    key = record_evaluation(evaluate_batch(batch, approved=APPROVED, repository=fake_repo),
                            repository=fake_repo)
    assert key == "operations/analytics/rule-validation/R-007/fixture-b1.json"
    assert json.loads(fake_repo.objects[key].decode("utf-8"))["rate_delta"] == -0.5

@pytest.mark.parametrize("current, target", [("retired", "active"), ("retired", "candidate"),
                                             ("active", "candidate")])
def test_apply_rule_status_rejects_illegal_transition(fake_repo, current, target):
    fake_repo.seed_rule("R-012", current)
    with pytest.raises(PermanentError):
        apply_rule_status("R-012", target, repository=fake_repo, now=NOW)
    assert fake_repo.updated == {}

def test_validate_rules_action_evaluates_and_writes_status(fake_repo, batch):
    event = {"action": "validate_rules", "now": "2026-09-01T00:00:00Z",
             "batches": [asdict(batch) | {"approved_at": "2026-09-01T00:00:00Z"}]}
    result = validate_rules_action(event, repository=fake_repo, approved=APPROVED)
    assert result["results"] == [{"rule_id": "R-007", "status": "active",
                                  "verdicts": ["improved"]}]
    assert fake_repo.updated["RULE#R-007"]["status"] == "active"
    assert "operations/analytics/rule-validation/R-007/fixture-b1.json" in fake_repo.objects
```

- [ ] **Step 2：執行並確認紅燈**

執行 `uv run pytest tests/unit/test_rule_status_writer.py -q`，預期 FAIL 且訊號包含 `cannot import name 'apply_rule_status'`。

- [ ] **Step 3：建立最小實作**（`status_writer.py`，再加 handler 分支）

```python
VALIDATED_AT_KEY = "operations/rules/validated_at.json"
LEGAL_TRANSITIONS = frozenset({
    (RuleStatus.CANDIDATE, RuleStatus.ACTIVE), (RuleStatus.CANDIDATE, RuleStatus.RETIRED),
    (RuleStatus.ACTIVE, RuleStatus.RETIRED)})

def _write_json(key, payload, *, repository):
    body = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    repository.put_object(key, body, "application/json", if_none_match=False)

def record_evaluation(evaluation, *, repository):
    key = (f"operations/analytics/rule-validation/{evaluation.rule_id}"
           f"/{evaluation.batch_id}.json")
    # asdict 保證證據檔一定含全部欄位（含兩個差值）；frozenset 不能直接序列化，改成排序清單。
    payload = asdict(evaluation) | {"version_ids": sorted(evaluation.version_ids)}
    _write_json(key, payload, repository=repository)
    return key

def load_validated_at(repository):
    raw = repository.get_object(VALIDATED_AT_KEY)
    if raw is None:
        return {}
    return {key: parse_iso(value) for key, value in json.loads(raw.decode("utf-8")).items()}

def apply_rule_status(rule_id, status, *, repository, now):
    status = RuleStatus(status)
    pk = rule_pk(rule_id)
    rule = repository.get_meta(pk, AuthoringRule)
    if rule is None:
        raise PermanentError(f"找不到規則：{rule_id}")
    if rule.status is not status:
        if (rule.status, status) not in LEGAL_TRANSITIONS:
            raise PermanentError(f"不合法的狀態轉移：{rule.status} -> {status}")
        repository.update_meta(pk, {"status": status.value},
                               expected_revision=repository.revision_of(pk))
        rule = repository.get_meta(pk, AuthoringRule)
    table = {key: to_iso(value) for key, value in load_validated_at(repository).items()}
    table[rule_id] = to_iso(now.replace(microsecond=0))
    _write_json(VALIDATED_AT_KEY, table, repository=repository)
    return rule

def validate_rules_action(event, *, repository, approved):      # handlers/analytics.py
    now = parse_iso(event["now"])
    by_rule: dict[str, list] = {}
    for raw in sorted(event["batches"], key=lambda item: item.get("approved_at") or ""):
        batch = SeedBatch(**{**raw, "approved_at": parse_iso(raw["approved_at"])
                             if raw.get("approved_at") else None})
        evaluation = evaluate_batch(batch, approved=approved, repository=repository)
        record_evaluation(evaluation, repository=repository)
        by_rule.setdefault(batch.rule_id, []).append(evaluation)
    results = []
    for rule_id, evaluations in sorted(by_rule.items()):
        rule = repository.get_meta(rule_pk(rule_id), AuthoringRule)
        if rule is None:
            raise PermanentError(f"找不到規則：{rule_id}")
        target = next_status(rule.status, evaluations, None)
        if target is not rule.status:
            apply_rule_status(rule_id, target, repository=repository, now=now)
        results.append({"rule_id": rule_id, "status": target.value,
                        "verdicts": [item.verdict for item in evaluations]})
    return {"action": "validate_rules", "results": results}
```

批次先依 `approved_at` 升序排序，`next_status` 的「最新一批」才有確定意義。`conflict` 固定傳 `None`：衝突判定要先由呼叫端取得 `ConflictJudgement` 並通過 `validated_conflict`，這個 action 不自行呼叫模型。`handler` 只需在 `event["action"] == "validate_rules"` 時轉呼叫它。

- [ ] **Step 4：跑綠燈並用 rg 確認唯一寫入者**

```bash
uv run pytest tests/unit/test_rule_status_writer.py tests/unit/test_rule_validation.py -q
rg -n '"status"' src/training_kb --glob '!**/analytics/status_writer.py'
```

預期：測試 PASS；`rg` 在 pipelines 與 writing 模組**不應**出現修改既有 RULE `status` 的路徑（Phase 47 只在建立新 RULE 時把 `status` 設為 `candidate`，不是修改既有值）。同一批次帶同一個 `now` 重跑兩次，RULE item、證據檔與 `validated_at.json` 完全相同；未知 `action` 仍由 Phase 54 的既有分支丟 `PermanentError`，不因本次修改變成靜默成功。

- [ ] **Step 5：提交**

```bash
git add src/training_kb/analytics/status_writer.py src/training_kb/handlers/analytics.py \
        tests/unit/test_rule_status_writer.py
git commit -m "feat(analytics): 規則狀態唯一寫入者與 validate_rules action"
```

## 8. 驗收矩陣

| 路徑 | 輸入 | 預期資料結果 |
|---|---|---|
| Happy | 自含 fixture：2.875→4.4、0.7→0.2 | `improved`；`average_delta` 1.525、`rate_delta` -0.5；`candidate` 轉 `active`。 |
| Boundary | 平均提高但 rate 持平；rate 下降但平均持平 | 兩者都 `not_improved`；狀態不變。 |
| Boundary | 後版零瀏覽者（`rate is None`）；對照版未發布或來自另一篇 | 都是 `undecidable`、`decidable is False`；狀態不變且不算失敗批次。 |
| Happy | 兩個不重疊已核定 `not_improved` | `active` 與 `candidate` 都轉 `retired`。 |
| Failure | 兩批共用一個 `version_id`；或兩批 `approved is False` | 只算一批／不算任何一批，狀態不變。 |
| Failure | 批次 `approved_by is None`；`retired -> active` | 前者 `undecidable` 且不呼叫 `apply_rule_status`；後者 `PermanentError`、item 不變。 |
| Security | `ConflictJudgement` 指向不存在規則、`applies_when` 不同或 `evidence` 為空 | `validated_conflict` 回 `None`；不退役 candidate、不動既有 active。 |

人工驗收：對每一次狀態變更，打開 `operations/analytics/rule-validation/<rule_id>/<batch_id>.json`，確認裡面同時有批次 ID、前後 `version_id`、前後平均、前後 rate 與兩個差值，且六個數字能用 Phase 53／54 的函式重算出來；再打開 `operations/rules/validated_at.json` 確認該 `rule_id` 的時間已更新。只看 `status == "active"` 不算完成。

## 9. 常見錯誤與停止條件

| 症狀 | 原因 | 修正／停止 |
|---|---|---|
| 資料不足的規則被退役 | 把 `undecidable` 併進 `not_improved` | 兩者分開；設計 §12.2 明寫線上不足不等於無效。 |
| 單項改善就啟用 | 用 `or` 串兩個條件 | 改成 `and`，且兩邊都用嚴格比較。 |
| 零分母算成 rate 0 而判定改善 | Phase 54 回了 `0.0` 而不是 `None` | 回 Phase 54 修正，本 Phase 停止判定。 |
| 用未發布版本當對照 | 只比版號沒看 `published_at` | 兩版都必須 `published_at` 非 None。 |
| 既有 active 被 candidate 的衝突判定退役 | 直接照模型輸出寫狀態 | 先過 `validated_conflict`；只退役提出衝突的 candidate。 |
| Phase 19 讀不到最近驗證時間 | 只寫了每批證據檔、沒寫單一檔 | `apply_rule_status` 必須併寫 `operations/rules/validated_at.json`（D-28）。 |
| `handlers/analytics.py` 不存在 | Phase 54 還沒補 D-56 的 Lambda 入口 | 停止 Task 3 的 handler 部分，回 Phase 54 建 `handler` 與 `action: "metrics"`。 |
| Feedback Review 也改了 status | 寫入入口不只一個 | 停止並收斂到 `apply_rule_status`；用 `rg` 檢查。 |
| 文件宣稱 R-007 已 active | 把 fixture 綠燈當種子核定 | 只能說狀態機測試通過；O7 由 Phase 56 關閉。 |

## 10. 來源與 Rule 對照

「D 開頭」是[設計 §19.1](../../design/training-kb.md) 的資料決策編號、「F 開頭」是 §19.2 的功能決策編號；`D-nn` 則是 [00A 共用契約與名詞](00A-共用契約與名詞.md)第 8 節的裁決編號。

- [驗證教學規則.feature](../../spec/features/驗證教學規則.feature)（`VAL`；本 Phase 是 Rule 1–8 的 primary）
  - Rule 1「規則成效比較套用組與同一篇教學套用前的已發布版本」→ Task 1 Step 4 的 `cross_tutorial` 與 `unpublished_comparison` 兩個參數化案例直接斷言 `undecidable`。
  - Rule 2「candidate 僅在平均評分嚴格提高且重開票率嚴格下降時升為 active」→ Task 2 的五個參數化案例與 `test_candidate_needs_improved_to_become_active`。
  - Rule 3「未載入完整核定種子驗證批次時不改變規則狀態」→ Task 1 的 `test_evaluate_batch_is_undecidable_when_batch_is_not_approved` 與 Task 2 的 `test_overlapping_undecidable_or_unapproved_batches_never_retire`。
  - Rule 4「與既有規則衝突的 candidate 規則變為 retired」→ Task 2 的 `test_conflict_retires_only_the_candidate`，同時斷言不覆蓋既有 active。
  - Rule 5「後來失效的 active 規則變為 retired」→ Task 2 的 `test_two_non_overlapping_unimproved_batches_retire_the_rule`（`current="active"` 分支）。
  - Rule 6「驗證無效的規則從可使用規則中退役」→ 同一個測試的 `current="candidate"` 分支與重疊批次反例。
  - Rule 7「curation 合併相近教學規則」→ Task 2 的 `test_curation_only_groups_and_never_changes_status`：MVP 只輸出群組，不合併 ID、不搬 evidence、不改 status（決策 F34）。
  - Rule 8「Analytics 寫入教學規則的驗證後 status」→ Task 3 的 `test_apply_rule_status_writes_status_and_validation_time`、`rg` 檢查與 handler 分派測試。
- [檢視學習指標.feature](../../spec/features/檢視學習指標.feature)（`MET`）Rule 6「規則效果比較套用與未套用版本的評分及同題重開票率差」→ **本 Phase 是 primary**；Task 1 的 `test_evaluation_reports_both_deltas` 斷言 `RuleEvaluation` 同時輸出 `average_delta` 與 `rate_delta`。Phase 53 只做評分那一半、Phase 54 只做重開票率那一半。
- [套用教學規則.feature](../../spec/features/套用教學規則.feature) Rule 2「一般寫作路徑只取得 status 為 active 的規則」→ 相關（primary 在 [Phase 19](19-Phase19-Active規則選取與注入.md)）；本 Phase 寫入的 `active` 與 `validated_at.json` 是 Phase 19 的唯一輸入來源，`candidate` 永遠不會因本 Phase 進入一般 prompt。
- 設計 §12.2（狀態機、完整核定批次、兩項嚴格改善、連續兩批退役、衝突判定、curation 界線）、§12.1（指標公式與 O4 窗口假設）、§12.3（差值只是觀察結果，不宣稱因果）、§7.6（模型提判斷、Analytics 驗證後才寫）、§18 O7（核定是確認合成驗收資料來源，不是日常審核佇列）。
- 決策 F27（candidate 由明示種子試用版本取得成效）、F30（兩項嚴格改善）、F31（同篇套用前對照）、F32（只在完整核定種子批次判定）、F33（連續兩個不重疊窗口未改善才退役）、F34（curation 只分組）、F55（模型提衝突判定、Analytics 驗證後退役）、D16（`applies_when` 只有單一 `step.type` 等值）、D27（跨專案共享只接受明示合成種子證據）。
- 00A 裁決：D-02、D-10（`applies_when` 型別是 `StepType`）、D-27（`expected_revision` 取自 `revision_of`）、D-28（最近驗證時間寫單一檔）、D-40（item 屬性只有模型欄位加保留屬性）、D-56（`handlers/analytics.py` 的 `action` 分派）。

## 11. 完成清單

- [ ] §5 Produces 的十個名稱與簽名全部實作完成，且 `RuleEvaluation` 帶 `average_delta`、`rate_delta`、`decidable`。
- [ ] `undecidable` 與 `not_improved` 分開；不可判定與未核定都不會導致退役，四個反例各有測試。
- [ ] 啟用同時要求平均嚴格提高與 rate 嚴格下降；持平、單項改善、反向各有參數化案例，兩個差值有獨立斷言。
- [ ] 退役需要兩個不重疊的已核定批次；重疊批次只算一批。衝突判定先過 `validated_conflict` 才退役 candidate，且不動既有 active；`curation_groups` 只分組。
- [ ] `apply_rule_status` 是唯一寫 `RULE.status` 的位置（`rg` 已檢查），最近驗證時間只寫 `operations/rules/validated_at.json`，非法轉移丟 `PermanentError`。
- [ ] 所有 fixture 自含、`AuthoringRule.evidence` 有五個不同 ID 且明示非核定；文件沒有宣稱 R-007 已 active 或 O7 已通過。
