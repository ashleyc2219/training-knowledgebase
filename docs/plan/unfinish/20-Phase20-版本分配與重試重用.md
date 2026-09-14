# Phase 20：版本分配與重試重用實作計畫

> **給實作者：** 依 checkbox 逐步執行；每個 Task 先建立失敗測試，再寫最小實作。執行時使用 `superpowers:executing-plans` 或同等逐項流程。

**目標：** 讓三條 pipeline 共用同一個版號分配器，使同一次邏輯變更不論重試幾次都拿到同一個 `version_id`。

**架構：** `content` 模組提供唯一的 `allocate_version`；它先問 O2 操作紀錄有沒有配過版號，沒有才以 Tutorial 目前已發布版本為基底往上找空號。各 handler 不得自己拼「current + 1」。

**技術：** Python 3.12、`dataclass`、pytest、Phase 06 `Repository`、Phase 10 `OperationCoordinator`。

## 全域限制

- 唯一主來源是 [Training KB 設計 §8.1、§8.3、§14.2、§18 O2](../../design/training-kb.md)。
- 前置為 [Phase 19：Active 規則選取與注入](./19-Phase19-Active規則選取與注入.md) 與 [Phase 11：O2 接受順序與重啟整合驗證](./11-Phase11-O2接受順序與重啟整合驗證.md)。前置未通過時停止。
- 下一階段是 [Phase 21：教學內容與步驟引用驗證](./21-Phase21-教學內容與步驟引用驗證.md)。
- 本階段不驗證教學內容、不產生 Markdown 或 diff、不寫 VERSION／STEP item、不切 `current_version`、不建立 Tutorial 身分；也不決定 `reason` 的三種格式內容（由 Phase 40 `gap:`、Phase 46 `feedback:`、Phase 51 `release:` 各自斷言，這裡只要求非空並原樣帶走）。
- 與本 Phase 有關的 gate：O2（[設計 §18](../../design/training-kb.md) 七個待確認事項中的「操作紀錄與接受順序」）仍待 [Phase 11](./11-Phase11-O2接受順序與重啟整合驗證.md) 的真實整合驗證。O2 未 PASS 前只能宣稱「給定同一份操作紀錄時版號確定」，不得宣稱併發建版或跨程序重啟已驗收；moto 或 fake backend 的綠燈都不算 O2 證據。
- 本階段不在 item 上加模型沒有的欄位：`TutorialVersion` 只有[00A 第 5.1 節](00A-共用契約與名詞.md)列的七個欄位，版號探測結果、基底推導過程這類執行資訊只寫進 operation 紀錄。以下程式檔均是實作時預計建立或修改；本計畫本身不代表它們已存在。

---

## 1. 你在整體流程的位置

```text
Phase 19 選出的 active 規則 + 呼叫端的 reason
                 v
     [你在這裡：allocate_version]
       |                      |
  O2 已配過版號           尚未配過
       v                      v
 重用原 version_id   以已發布版本為基底往上找空號
       +----------+-----------+
                  v
             VersionPlan -> Phase 21 驗證 -> Phase 22 產物 -> Phase 23 寫未發布版本
```

`VersionPlan` 只是「這次要寫第幾版」的決定，不代表版本已存在於 DynamoDB。

## 2. 完成後看得到什麼

`prepare-meeting` 目前已發布版本是 `prepare-meeting@v1`，Release `r_42` 的操作紀錄是 `op-release-r_42`：

```text
第 1 次 -> VersionPlan(version_id="prepare-meeting@v2", slug="prepare-meeting", number=2,
           supersedes="prepare-meeting@v1", reason="release:r_42",
           rules_applied=("R-007",), operation_id="op-release-r_42")
寫 S3 後當機 -> 換新程序重送同一 operation -> version_id 仍是 "prepare-meeting@v2"
```

若 v2 是上一次**永久失敗**留下的未發布版本，新操作會取得 `prepare-meeting@v3`，`supersedes` 仍是已發布的 `prepare-meeting@v1`；v2 成為合法的號碼缺口。

## 3. 名詞小抄

| 名詞 | 白話意思 |
|---|---|
| `version_id` | 一篇教學某一版的裸識別碼，格式固定為 `<slug>@v<n>`，例如 `prepare-meeting@v2`。 |
| 基底 | 這一版從哪一版改出來，也就是 `supersedes` 指的版本；固定取最近**已發布**的那一版。 |
| 號碼缺口 | 某個版號被配出去但永久失敗，之後的版本跳過它，中間空一號。 |
| 操作紀錄／O2 gate | 操作紀錄是 `OPS#<operation_id>` item，保存這次邏輯操作已配到的 `version_id`；同一次邏輯變更就是同一個 `operation_id`。gate 是必須有真實整合證據才能通過的關卡，mock 綠燈不算。 |
| `VersionPlan` | 「這次要寫第幾版、以哪一版為基底、為什麼寫、套用了哪些規則」的凍結決定，還沒有寫進資料庫。 |
| `reason` | 這一版為什麼產生，三種格式 `gap:<cluster_id>`、`release:<id>`、`feedback:<n> 則 <category>`，本 Phase 只檢查非空。 |

## 4. 預計檔案

| 動作 | 路徑 | 責任 |
|---|---|---|
| 新增 | `src/training_kb/content.py` | `VersionPlan`、`make_version_id`、`parse_version_id`、`allocate_version`。 |
| 測試 | `tests/unit/test_allocate_version.py`、`tests/integration/test_allocate_version_retry.py` | 版號編碼、v1 起算、號碼缺口、錯誤情境，以及換程序重送同一 operation 仍得同版號。 |

## 5. 固定介面

### Consumes

```text
OperationCoordinator.load(operation_id: str) -> OperationRecord | None    # Phase 10
OperationCoordinator.record_version(operation_id: str, version_id: str) -> None
OperationRecord.version_id: str | None    # 本 Phase 只用到這一個欄位
Repository.get_tutorial(slug: str) -> Tutorial | None                    # Phase 06
Repository.get_version(version_id: str) -> TutorialVersion | None
Tutorial(slug, current_version: str | None, topic, feature_ids, status, successor, cluster_id)
TutorialVersion(version_id, slug, supersedes, reason, rules_applied, s3_key, published_at)
ContentError（PermanentError 家族）、CoordinationError（直接繼承 Exception）  # Phase 02
```

### Produces

```python
@dataclass(frozen=True)
class VersionPlan:
    version_id: str
    slug: str
    number: int
    supersedes: str | None
    reason: str
    rules_applied: tuple[str, ...]
    operation_id: str

def make_version_id(slug: str, number: int) -> str: ...
def parse_version_id(value: str) -> tuple[str, int]: ...
def allocate_version(
    tutorial_id: str,
    operation_id: str,
    operations: OperationCoordinator,
    *,
    repository: Repository,
    reason: str,
    rules_applied: Sequence[str],
) -> VersionPlan: ...
```

`tutorial_id` 就是 `Tutorial.slug`；本專案不另外發明 Tutorial 主鍵。Phase 23、40、46、51 都只透過這個函式取得版號。

## 6. 設計細節

版號屬於 Tutorial，不屬於流程；三條 pipeline 不能各自計數（設計 §8.1）。決策順序固定如下：

```text
operations.load(operation_id)
   | 沒有紀錄 ----------> CoordinationError（尚未被 O2 接受）
   v
   record.version_id 有值？ -- 是 --> 讀既有 VERSION item
   | 否                        有 -> 沿用它的 supersedes / reason / rules_applied
   |                           無 -> supersedes 由基底重新推導，其餘用參數
   v
   tutorial.current_version -> base（None 代表還沒有任何已發布版本）
   v
   number = base 號碼 + 1；該號碼已有 VERSION item 就繼續 +1
   v
   operations.record_version(...) 先落地，再回傳 VersionPlan
```

（下面的 D 與 F 編號是[設計 §19](../../design/training-kb.md) 的決策索引：D 是資料決策、F 是功能決策。）**基底與號碼是兩件事。** `supersedes` 固定取 `current_version`，因為只有 publish 成功才會切換它（F37：publish 成功回傳時才切換），它就是「最近已發布版本」；號碼則必須跳過已被占用的號碼，否則永久失敗留下的 v2 會被新操作覆寫。D26（同一邏輯變更重試重用原版號、永久失敗可留缺口）允許缺口，不允許覆寫。
**先落地再回傳，前提是 O2 串行。** `record_version` 必須在回傳前完成：落地前當機時重試由 `current_version` 重新推導出同一號碼，落地後當機時重試直接讀回同一號碼。同篇改版依接受順序串行（F35：同篇變更依接受順序串行，每次讀最新可用基底）；O2 未 PASS 時兩個併發操作仍可能探到同一空號，這是 gate 未通過的已知後果，不是條件寫入就能宣稱解決。
**`record_version` 是 write-once（Phase 11 依 Phase 10 review 追加）**：同一個 operation 重送同一個 `version_id` 是 no-op，換成別的值丟 `CoordinationError`。本 Phase 的流程「先 `load`、有 `version_id` 就直接重用、沒有才配號並 `record_version`」天生相容——重送根本不會走到第二次寫入；併發探到不同空號時則由那個 `CoordinationError` 明確浮出來，不會靜默覆寫。

## 7. TDD Tasks

### Task 1：版號編碼與第一版分配

- [x] **Step 1：建立失敗測試（含本檔自用的記憶體替身，整個 Phase 不碰 AWS）**

```python
from types import SimpleNamespace

import pytest

from training_kb.content import allocate_version, make_version_id, parse_version_id
from training_kb.errors import ContentError, CoordinationError
from training_kb.models import Tutorial, TutorialStatus, TutorialVersion

class FakeRepository:          # 記憶體版 Repository，只實作本 Phase 用到的讀取
    def __init__(self):
        self.tutorials, self.versions = {}, {}
    def put_tutorial(self, slug, *, current_version):
        self.tutorials[slug] = Tutorial(slug=slug, current_version=current_version, topic="準備會議",
            feature_ids=["Prepare"], status=TutorialStatus.ACTIVE, successor=None, cluster_id="c12")
    def put_unpublished_version(self, version_id, *, supersedes=None, reason="gap:c12", rules_applied=()):
        slug, number = parse_version_id(version_id)
        self.versions[version_id] = TutorialVersion(version_id=version_id, slug=slug,
            supersedes=supersedes, reason=reason, rules_applied=list(rules_applied),
            s3_key=f"tutorials/{slug}/v{number}.md", published_at=None)
    def get_tutorial(self, slug): return self.tutorials.get(slug)
    def get_version(self, version_id): return self.versions.get(version_id)

class FakeOperations:          # 記憶體版 OperationCoordinator，只保存 version_id 與寫入次數
    def __init__(self):
        self.records, self.writes = {}, []
    def accepted(self, operation_id): self.records[operation_id] = None
    def load(self, operation_id):
        if operation_id not in self.records:
            return None
        return SimpleNamespace(operation_id=operation_id, version_id=self.records[operation_id])
    def record_version(self, operation_id, version_id):
        self.records[operation_id] = version_id
        self.writes.append((operation_id, version_id))

@pytest.fixture
def fake_repo(): return FakeRepository()
@pytest.fixture
def fake_ops(): return FakeOperations()

def test_version_id_round_trip():
    assert make_version_id("prepare-meeting", 2) == "prepare-meeting@v2"
    assert parse_version_id("prepare-meeting@v2") == ("prepare-meeting", 2)

@pytest.mark.parametrize("value", ["a@v0", "a@v01", "@v2", "a@vx", "prepare-meeting"])
def test_parse_version_id_rejects_bad_values(value):
    with pytest.raises(ValueError):
        parse_version_id(value)

def test_first_version_starts_at_v1(fake_repo, fake_ops):
    fake_repo.put_tutorial("prepare-meeting", current_version=None)
    fake_ops.accepted("op-gap-c12")
    plan = allocate_version("prepare-meeting", "op-gap-c12", fake_ops,
                            repository=fake_repo, reason="gap:c12", rules_applied=[])
    assert (plan.version_id, plan.number, plan.supersedes) == ("prepare-meeting@v1", 1, None)

def test_next_version_follows_current_published(fake_repo, fake_ops):
    fake_repo.put_tutorial("prepare-meeting", current_version="prepare-meeting@v2")
    fake_ops.accepted("op-release-r_42")
    plan = allocate_version("prepare-meeting", "op-release-r_42", fake_ops,
                            repository=fake_repo, reason="release:r_42", rules_applied=["R-007"])
    assert (plan.version_id, plan.number) == ("prepare-meeting@v3", 3)
    assert (plan.supersedes, plan.rules_applied) == ("prepare-meeting@v2", ("R-007",))
```

`test_next_version_follows_current_published` 就是 `建立教學版本` Rule 2 的 Example：目前版本是 Feedback Review 產生的 v2，Release 建立下一版時必須拿到 v3。

- [x] **Step 2：執行並確認紅燈**

```bash
uv run pytest tests/unit/test_allocate_version.py -q
```

預期：FAIL，訊號是 `ModuleNotFoundError: No module named 'training_kb.content'`（先建空檔的話是 `cannot import name 'allocate_version'`）。

- [x] **Step 3：建立版號編碼**

```python
def make_version_id(slug: str, number: int) -> str:
    if isinstance(number, bool) or not isinstance(number, int) or number < 1:
        raise ValueError(f"invalid version parts: {slug!r}, {number}")
    if not slug or slug != slug.strip() or "@" in slug or "#" in slug:
        raise ValueError(f"invalid version parts: {slug!r}, {number}")
    return f"{slug}@v{number}"

def parse_version_id(value: str) -> tuple[str, int]:
    slug, separator, suffix = value.partition("@v")
    if not separator or not suffix.isdecimal():
        raise ValueError(f"invalid version id: {value}")
    number = int(suffix)
    if number < 1 or make_version_id(slug, number) != value:
        raise ValueError(f"invalid version id: {value}")
    return slug, number
```

最後一個比較同時擋掉 `a@v01` 這種有前導零的寫法，避免兩個字串對應同一版；`a@v0`、`@v2`、`a@vx`、完全沒有 `@v` 的字串都由 Step 1 的 `test_parse_version_id_rejects_bad_values` 擋住。`isdecimal()`（不是 `isdigit()`）、`isinstance(number, bool)` 與 `slug != slug.strip()` 三個守門員與 `keys.parse_step_pk`／`keys.step_pk` 是同一套寫法：`isdigit()` 會放行 `²` 讓 `int()` 丟自己的 `ValueError`、`True` 會組出 `a@vTrue`（`bool` 是 `int` 的子型別，mypy 擋不住）、前後空白則會讓 `parse_version_id` 接受 `make_version_id` 產不出來的字串，破壞 round-trip 不變式。

- [x] **Step 4：補上分配主流程並跑綠燈**

```python
def allocate_version(tutorial_id, operation_id, operations, *, repository, reason, rules_applied):
    if not reason.strip():
        raise ContentError("建立版本必須記錄 reason")
    record = operations.load(operation_id)
    if record is None:
        raise CoordinationError(f"操作尚未被接受：{operation_id}")
    if record.version_id is not None:
        return _replay_plan(record.version_id, tutorial_id, operation_id,
                            repository, reason, rules_applied)
    supersedes, base_number = _base_version(repository, tutorial_id)
    number = _next_free_number(repository, tutorial_id, base_number)
    version_id = make_version_id(tutorial_id, number)
    operations.record_version(operation_id, version_id)
    return _plan(version_id, supersedes, reason, rules_applied, operation_id)
```

兩個小幫手同檔實作（型別註記用的 `Sequence`、`Repository` 與 `VersionPlan` 都在同一支 `content.py`）。`_plan` 把 `rules_applied` 轉成 tuple，`VersionPlan` 才真的凍結；`_base_version` 只認 `current_version`，不認最新版本：

```python
def _plan(version_id: str, supersedes: str | None, reason: str,
          rules_applied: Sequence[str], operation_id: str) -> VersionPlan:
    slug, number = parse_version_id(version_id)
    return VersionPlan(version_id=version_id, slug=slug, number=number, supersedes=supersedes,
                       reason=reason, rules_applied=tuple(rules_applied),
                       operation_id=operation_id)

def _base_version(repository: Repository, slug: str) -> tuple[str | None, int]:
    tutorial = repository.get_tutorial(slug)
    if tutorial is None:
        raise ContentError(f"找不到教學：{slug}")
    if tutorial.current_version is None:
        return None, 0
    base_slug, number = parse_version_id(tutorial.current_version)
    if base_slug != slug:
        raise ContentError(f"{slug} 的 current_version 指向別篇：{tutorial.current_version}")
    return tutorial.current_version, number
```

執行 `uv run pytest tests/unit/test_allocate_version.py -q`，預期 Step 1 的四個測試函式（參數化展開後 8 項）全部 PASS。

- [x] **Step 5：提交**

```bash
git add src/training_kb/content.py tests/unit/test_allocate_version.py
git commit -m "feat(content): 依已發布基底分配教學版號"
```

### Task 2：跳過永久失敗留下的號碼

- [x] **Step 1：建立失敗測試**

```python
def test_permanently_failed_number_is_skipped(fake_repo, fake_ops):
    fake_repo.put_tutorial("prepare-meeting", current_version="prepare-meeting@v1")
    fake_repo.put_unpublished_version("prepare-meeting@v2")
    fake_ops.accepted("op-release-r_42")
    plan = allocate_version("prepare-meeting", "op-release-r_42", fake_ops,
                            repository=fake_repo, reason="release:r_42", rules_applied=["R-007"])
    assert (plan.version_id, plan.supersedes) == ("prepare-meeting@v3", "prepare-meeting@v1")
```

- [x] **Step 2：執行並確認紅燈**

```bash
uv run pytest tests/unit/test_allocate_version.py::test_permanently_failed_number_is_skipped -q
```

預期：FAIL，因為只做 `base_number + 1` 會回 `prepare-meeting@v2`，等於覆寫既有未發布版本。

- [x] **Step 3：建立最小實作**

```python
def _next_free_number(repository: Repository, slug: str, base_number: int) -> int:
    number = base_number + 1
    while repository.get_version(make_version_id(slug, number)) is not None:
        number += 1
    return number
```

- [x] **Step 4：補四個失敗情境後跑完整檔案**

```python
@pytest.mark.parametrize("current, recorded, operation_id, reason, error", [
    (None, None, "op-gap-c99", "gap:c99", CoordinationError),               # 沒有被 O2 接受
    (None, None, "op-gap-c12", "   ", ContentError),                        # reason 空白
    ("share-summary@v1", None, "op-gap-c12", "gap:c12", ContentError),      # current_version 是別篇
    (None, "share-summary@v9", "op-gap-c12", "gap:c12", CoordinationError), # 紀錄版號是別篇
])
def test_allocate_version_rejects_bad_input(fake_repo, fake_ops, current, recorded,
                                            operation_id, reason, error):
    fake_repo.put_tutorial("prepare-meeting", current_version=current)
    fake_ops.accepted("op-gap-c12")
    if recorded:
        fake_ops.record_version("op-gap-c12", recorded)
        fake_ops.writes.clear()
    with pytest.raises(error):
        allocate_version("prepare-meeting", operation_id, fake_ops,
                         repository=fake_repo, reason=reason, rules_applied=[])
    assert fake_ops.writes == []
```

`assert fake_ops.writes == []` 是重點：失敗時不能留下半筆版號紀錄。執行 `uv run pytest tests/unit/test_allocate_version.py -q`，預期**只有最後一個參數化案例（紀錄版號是別篇）FAIL**（`DID NOT RAISE CoordinationError`，因為 Task 3 的 `_replay_plan` 還不存在，流程會往下重新配號）；把 `_replay_plan` 的 slug 守門員先補上（`existing` 分支留到 Task 3）之後全部 PASS。

- [x] **Step 5：提交**

```bash
git add src/training_kb/content.py tests/unit/test_allocate_version.py
git commit -m "feat(content): 允許永久失敗的版號缺口"
```

### Task 3：同 operation 重送重用版號

- [x] **Step 1：建立失敗測試**

```python
def test_replay_reuses_recorded_version_and_base(fake_repo, fake_ops):
    fake_repo.put_tutorial("prepare-meeting", current_version="prepare-meeting@v1")
    fake_ops.accepted("op-refine-1")
    def call(reason, rules):
        return allocate_version("prepare-meeting", "op-refine-1", fake_ops,
                                repository=fake_repo, reason=reason, rules_applied=rules)

    first = call("feedback:8 則 找不到按鈕", ["R-007"])
    fake_repo.put_unpublished_version(first.version_id, supersedes=first.supersedes,
                                      reason=first.reason, rules_applied=first.rules_applied)
    second = call("feedback:9 則 找不到按鈕", ["R-012"])
    assert second.version_id == first.version_id == "prepare-meeting@v2"
    assert (second.supersedes, second.rules_applied) == ("prepare-meeting@v1", ("R-007",))
    assert (second.reason, len(fake_ops.writes)) == ("feedback:8 則 找不到按鈕", 1)
```

`put_unpublished_version` 這一行模擬 [Phase 23](./23-Phase23-未發布版本與關係完整寫入.md) 已經把第一次的 `VersionPlan` 寫成 VERSION item。第二次故意傳入不同的 `reason` 與規則：已寫進 DynamoDB 的版本必須原樣沿用，不能讓重試改寫已保存的內容（設計 §14.2）；`record_version` 也只能寫一次。

- [x] **Step 2：執行並確認紅燈**

```bash
uv run pytest tests/unit/test_allocate_version.py::test_replay_reuses_recorded_version_and_base -q
```

預期：FAIL。Task 2 為了那個參數化案例已經補了 `_replay_plan` 的 slug 守門員，所以紅燈落在欄位上——`AssertionError: At index 1 diff: ('R-012',) != ('R-007',)`：既有 VERSION item 的欄位仍被第二次的參數覆寫。

- [x] **Step 3：建立最小實作**

```python
def _replay_plan(version_id, tutorial_id, operation_id, repository, reason, rules_applied):
    slug, _ = parse_version_id(version_id)
    if slug != tutorial_id:
        raise CoordinationError(f"操作 {operation_id} 已配給 {slug}，不能改用 {tutorial_id}")
    existing = repository.get_version(version_id)
    if existing is not None:
        return _plan(version_id, existing.supersedes, existing.reason,
                     existing.rules_applied, operation_id)
    supersedes = _base_version(repository, tutorial_id)[0]
    return _plan(version_id, supersedes, reason, rules_applied, operation_id)
```

已發布版本不在這裡擋；`create_version` 才是「已發布不可覆寫」的關卡（[Phase 23](./23-Phase23-未發布版本與關係完整寫入.md)）。

- [x] **Step 4：跨程序重啟的整合測試**

整合測試改用 [Phase 06](./06-Phase06-Repository-Metadata與實體讀寫.md) 已建立的 `tests/integration/conftest.py`（moto 建出真的 `training_kb` 表）：第一次呼叫後丟棄整個 Python 物件，用同一張表重建新的 `Repository` 與 `OperationCoordinator`，再送同一個 `operation_id`，模擬換程序重送。

```bash
uv run pytest tests/integration/test_allocate_version_retry.py -q
```

預期：PASS，且 `OPS#<operation_id>` 的 `version_id` 只被寫入一次、兩次拿到同一個 `version_id`。「只寫一次」的斷言方式是比對 `OPS#` item 的 `_revision`：`accept` 之後記下的值 +1 就是第一次 `record_version`，重送後必須**維持不變**。同一支檔案第二個測試把 §8 的人工驗收自動化：中間插一次 `put_meta(TutorialVersion(...))` 模擬 Phase 23 寫出 VERSION item，重送時故意換 `reason` 與規則，再把 `OPS#` 與 `VERSION#` 兩個 raw item 逐欄比對。moto 通過只代表程式邏輯正確，**O2 gate 仍維持未通過**，要等 Phase 11 在真實 DynamoDB 留下證據。

- [x] **Step 5：提交**

```bash
git add src/training_kb/content.py tests/integration/test_allocate_version_retry.py
git commit -m "test(content): 驗證同操作重送重用版號"
```

## 8. 驗收矩陣

| 路徑 | 輸入 | 預期資料結果 |
|---|---|---|
| Happy | 新 Tutorial（`current_version=None`）／`current_version=v1` | 分別得到 `@v1`（`supersedes=None`）與 `@v2`（`supersedes="prepare-meeting@v1"`）。 |
| Happy | 同 `operation_id` 第二次呼叫 | 同一個 `version_id`，不再寫入新的 `record_version`。 |
| Failure | `operations.load` 回 `None`／`reason` 空白／`current_version` 是別篇 | `CoordinationError`／`ContentError`／`ContentError`；都不配號、不寫紀錄。 |
| Failure | 紀錄的版號屬於別篇教學 | `CoordinationError`，訊息含兩個 slug。 |
| Boundary | v2 已存在且未發布 | 新操作取得 v3；重送舊操作則回傳既有 reason 與 `rules_applied`。 |

人工驗收：讀出 `OPS#<operation_id>` 與 `VERSION#<version_id>` 兩個 item，逐欄比對 `version_id`、`supersedes`、`reason`；不能只看測試顯示 PASS。

## 9. 常見錯誤與停止條件

| 症狀 | 原因 | 修正／停止 |
|---|---|---|
| 重試產生 v2、v3 兩個版本 | 沒先讀 `record.version_id` 就重新配號 | 停止建版路徑，回到本 Phase Task 3。 |
| 新版覆寫永久失敗的 v2 | 只做 `base_number + 1`，沒探空號 | 補 `_next_free_number`；已被覆寫的資料不可宣稱無影響。 |
| `supersedes` 指向未發布版本 | 把「最新版本」當基底而非 `current_version` | 只取 `current_version`；未發布版本不是基底。 |
| 併發操作拿到同一個空號 | O2 串行尚未驗證 | 停止雲端併發建版，保留 FAIL 給 Phase 11。 |

## 10. 來源與 Rule 對照

- [建立教學版本.feature](../../spec/features/建立教學版本.feature)
  - Rule 1：「新 Tutorial 的版本從 v1 起算」→ Task 1 `test_first_version_starts_at_v1` 直接斷言。
  - Rule 2：「任一 pipeline 修改既有教學時使用該篇的下一個版本號」→ 本文件是 primary：Task 1 `test_next_version_follows_current_published`（就是 Rule 2 的 Example）、Task 2 `test_permanently_failed_number_is_skipped` 與 Task 3 的重送測試直接斷言；Phase 11、Phase 59 在整合情境再驗（相關）。
  - Rule 3：「新版以 supersedes 關聯同一篇教學的前一版」→ 相關：本文件只決定 `VersionPlan.supersedes` 的值，primary 在 [Phase 23](./23-Phase23-未發布版本與關係完整寫入.md)（寫入 `SUPERSEDES` 邊）。
  - Rule 4：「每次建立版本都記錄引起變更的 reason」→ 相關：本文件只擋空白 `reason`（Task 2 的參數化失敗測試），primary 在 Phase 23（把 `reason` 寫進 VERSION item）。
- 設計 §8.1、§8.3、§14.2、§18 O2 與決策 D26、F35、F37：版號屬於 Tutorial、重試重用原版號、永久失敗可留缺口、同篇依接受順序串行、`current_version` 只在 publish 成功時切換；接受順序仍待整合驗證。

## 11. 完成清單

- [x] `VersionPlan` 七個欄位與 `allocate_version` 簽名符合本文件。
- [x] `make_version_id`／`parse_version_id` 有 round-trip 與非法輸入測試。
- [x] v1 起算、下一版、號碼缺口三種情境各有獨立 assertion；同 `operation_id` 重送取得同一 `version_id` 且既有欄位不被參數覆寫。
- [x] `record_version` 在回傳前落地；未被 O2 接受的 operation 與空 `reason` 都明確失敗，且失敗時 `writes` 為空。
- [x] 沒有在 VERSION item 或 `Tutorial` 上偷加模型沒有的欄位；單元與整合測試已實際執行並保存輸出，且沒有把 fake 替身或 moto 的 PASS 說成 O2 gate 已通過。
