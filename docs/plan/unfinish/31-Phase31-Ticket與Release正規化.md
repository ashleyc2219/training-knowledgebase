# Phase 31：Ticket 與 Release 正規化實作計畫

> **給 agentic worker：** 使用 `superpowers:subagent-driven-development`（建議）或 `superpowers:executing-plans` 執行所有 checkbox。

**目標：** 將已驗證來源交出的候選欄位，轉成欄位完整、列舉合法且 ID 可追溯的 `Ticket` 或 `Release`。

**架構：** adapter 只做來源欄位抽取；本 Phase 的 `validate_ticket`／`validate_release` 是唯一 canonical model 邊界。O6 的 ID、作者與事件 mapping 必須使用 Phase 13 維護者已確認 fixture，模型不可產生穩定 ID。

**技術：** Python 3.12、Pydantic v2、StrEnum、pytest、ISO-8601 UTC parser。

## 1. 文件定位

- **主來源：** [設計 §7.1、§7.4、§9.1、§18 O6、§20.1／20.7](../../design/training-kb.md)。名稱與簽名以 [00A 共用契約與名詞](./00A-共用契約與名詞.md) 為準。
- **前置：** [Phase 03](./03-Phase03-識別碼列舉與內容草稿模型.md) 的七個 StrEnum、[Phase 04](./04-Phase04-十個邏輯實體模型.md) 的 `Ticket`／`Release`、[Phase 13](./13-Phase13-O6來源ID與穩定使用者契約.md) 的 fixture 與 ID 編碼；GitHub 路徑另需 [Phase 30](./30-Phase30-GitHub-Webhook原始Body驗簽.md) 驗簽。任一前置未完成時停止，不自造 fixture。
- **後續：** [Phase 32](./32-Phase32-事件接受去重與流程啟動.md) 接受去重、[Phase 36](./36-Phase36-JSONPath與白名單Adapter.md) adapters、[Phase 37](./37-Phase37-Rote-Agent回退與成功提交.md) Rote Agent。
- **不做：** 不算 embedding、不分群、不做 Feature 語意命中或教學動作；不把 PR number 當 `Release.id`；不猜跨來源 user 對應；不寫任何 DynamoDB item 或 S3 物件。
- **gate 狀態：** O6（來源完整契約）由 Phase 13 負責核對，本 Phase **不得宣稱 O6 已核定**。未核對前該 `(domain, event_type)` 維持 blocked，整合測試只能是明確 XFAIL。

## 2. 你在整體流程的位置

```text
可信入口 / 已驗簽 GitHub
        |
        v
adapter 候選欄位
        |
        v
[你在這裡] validate_ticket / validate_release
        | 合法                         | 不合法
        v                              v
canonical model -> Phase 32          IngressError(fields=("author",))
```

## 3. 完成後看得到什麼

輸入是 adapter 交出的候選欄位（全部字串），輸出是 canonical model；過程中沒有任何 Repository 寫入：

```text
{"id": "t_gh-acme-app-881", "source": "github_issue", "text": "會前摘要在哪裡開啟？",
 "author": "u_gh-4821", "ts": "2026-08-03T10:00:00Z", "project_id": "demo"}
        |  validate_ticket(payload)
        v
Ticket(id="t_gh-acme-app-881", source=TicketSource.GITHUB_ISSUE, author="u_gh-4821",
       ts=datetime(2026, 8, 3, 10, 0, tzinfo=UTC), project_id="demo",
       cluster_id=None, feature_ids=[], embedding=None)
```

同一份 PR #42 fixture 提到兩個功能變更時，會得到 `r_gh-acme-app-pr42-1` 與 `r_gh-acme-app-pr42-2` 兩筆 `Release`，兩筆的 `source_event_id` 都是 `gh-acme-app-pr42`；缺 `author` 的匯入檔得到 `IngressError(fields=("author",))`，沒有任何物件被建立。重新驗證同一候選得到完全相同的 ID。

### 3.1 名詞小抄

| 名詞 | 白話意思 |
|---|---|
| 正規化（normalize） | 把來源給的零散欄位，轉成本專案固定形狀的 `Ticket` 或 `Release`。 |
| canonical model | 正規化後唯一合法的物件形狀；之後所有流程只認它，不再回頭讀原始 payload。 |
| 候選欄位 | adapter 從原始事件抽出、尚未驗證的欄位字典；它還不是合法物件。 |
| `IngressError` | Phase 02 定義的接入錯誤；`fields` 是**不合法欄位名的 tuple**，由 constructor 排序去重。 |
| StrEnum | Phase 03 的列舉型別，成員名大寫、值小寫（`TicketSource.GITHUB_ISSUE == "github_issue"`）。 |
| `source_event_id` | 同一個上游事件（例如一個 PR）的共同識別碼；同一事件拆出的多筆子 Release 共用它。 |
| `deadline` | Phase 30 在 handler 進入時算好的「整體期限」（一個 `time.monotonic()` 浮點數）；驗簽、正規化、接受全部要在它之前做完。 |
| O6 | 設計 §18 第六個待確認事項：來源 ID、STABLE_KEYS 與跨來源使用者對應尚待維護者核對。 |
| D10／D23／F14 | 設計 §19 的決策編號：D10 是 Release 必填欄位、D23 是 author 必填與共用穩定 user、F14 是多 Feature 拆子 Release。 |

## 4. 預計檔案

以下是實作時預計建立或修改；本計畫本身不代表它們已存在：

| 動作 | 路徑 | 責任 |
|---|---|---|
| 修改 | `src/training_kb/ingress.py` | 兩個 validation 函式與共用的必填欄位檢查；模組由 Phase 30 建立。 |
| 未改 | `src/training_kb/models.py` | 原本預留「補前期已規劃但尚未完成的 model validation」；實際檢查後 Phase 04 已經做齊（`Ticket` 的 `bare_id`／`filled`／`aware`／`feature_ids` 最多一個、`Release.renamed_carries_both_names`、`aware()` 拒絕微秒），本 Phase **沒有修改 `models.py`**。 |
| 測試 | `tests/unit/test_ingress_validation.py` | 必填、列舉、時間與「分析欄位不得預填」的測試。 |
| 測試 | `tests/integration/test_o6_github_mapping.py` | 用 Phase 13 核定 fixture 做可追溯整合。 |
| 消費 | `tests/fixtures/github/issue-opened.json`、`pull-request-merged.json`、`tests/fixtures/o6/approved-sources.json` | Phase 13 建立的 O6 fixture 與核定紀錄，本 Phase 只讀不改。 |

## 5. 固定介面

**Consumes**

```text
parse_iso(value) -> datetime                    # Phase 02，naive 時間一律拒絕
IngressError(message, fields)                   # Phase 02，fields 是 tuple[str, ...]
TicketSource / ReleaseSource / ReleaseKind      # Phase 03 的 StrEnum，不得改寫成 Literal
Ticket / Release                                # Phase 04 的 StrictModel
github_ticket_id(owner, repo, number)           # Phase 13，"t_gh-<owner>-<repo>-<n>"
github_release_id(owner, repo, pr_number, k)    # Phase 13，"r_gh-<owner>-<repo>-pr<n>-<k>"
github_source_event_id(owner, repo, pr_number)  # Phase 13，"gh-<owner>-<repo>-pr<n>"
github_user_id(numeric_id)                      # Phase 13，"u_gh-<id>"
load_source_approvals / approved_stable_keys    # Phase 13，讀 O6 核定紀錄
```

**Produces**

```python
def validate_ticket(payload: Mapping[str, object]) -> Ticket: ...
def validate_release(payload: Mapping[str, object]) -> Release: ...
def missing_nonempty_strings(payload: Mapping[str, object],
                             keys: Sequence[str]) -> tuple[str, ...]: ...
```

模組層另外公開四個常數：`TICKET_REQUIRED`、`RELEASE_REQUIRED`（00A §6.8 逐字）、
`RENAMED_REQUIRED = ("old_name", "new_name")` 與 `ANALYSIS_FIELDS`。

Ticket 必填六欄 `id, source, text, author, ts, project_id`；`cluster_id`／`feature_ids`／`embedding` 是分析欄位，接入時不得預填。Release 必填六欄 `id, source, feature, kind, evidence, ts`；`kind` 為 `renamed` 時另要求 `old_name, new_name`，其他 kind 允許兩個名稱欄位為空。`source_event_id`、`old_name`、`new_name` 在模型裡可為 `None`，所以建構時一律用 `payload.get(...)`，不用 `payload[...]`；實作把這個取值收斂成 `_optional_string(payload, key)`（沒出現或給 `null` 都是 `None`，給了非字串就是 `IngressError`），因為 mypy strict 不接受把 `object` 直接餵給 `str | None` 欄位。這三個欄位**不檢查 key 有沒有出現**：00A §6.8 的 `RELEASE_REQUIRED` 不含它們，而 `changed`／`removed` 事件本來就沒有名稱欄位、`changelog` 來源也沒有上游事件識別碼。關聯欄位保存裸 ID，只有 DynamoDB key 才加前綴（設計 §9.1）。

驗證順序固定如下，先看欄位在不在，再看值合不合法；每一關都把不合法欄位名收進 `IngressError.fields`：

```text
payload（adapter 候選欄位）
   |
   +--> (1) 六個必填欄位是否為非空字串？ -- 否 --> IngressError(fields=缺的欄位名)
   |
   +--> (2) 分析欄位被預填？(embedding/cluster_id/feature_ids) -- 有 --> IngressError(預填欄位名)
   |
   +--> (3) kind == renamed 時 old_name / new_name 也必須非空 -- 否 --> IngressError(缺的名稱欄位)
   |
   +--> (4) source / kind 是合法 StrEnum 值？ -- 否 --> IngressError(("source",) 或 ("kind",))
   |
   +--> (5) parse_iso(ts) 是 aware UTC 整秒？ -- 否 --> IngressError(("ts",))
   |
   +--> (6) 模型層仍然拒絕？(例如 id 帶 TICKET# 前綴) -- 是 --> IngressError(loc 上的欄位名)
   |
   v
canonical Ticket / Release（沒有任何 Repository 寫入）
```

第 (5) 關連**微秒**一起擋掉：00A §3.5 要求 datetime 欄位一律 UTC 整秒，靜默截斷會讓以時間入鍵的計算悄悄改變答案。第 (6) 關是本 Phase 的補強——這兩個函式是唯一的 canonical model 邊界，pydantic 的 `ValidationError` 若原樣往外丟，只認得 `IngressError`／`TimeoutError` 的 webhook handler 會回 500 而不是明確拒絕（00A §4.1 把 `IngressError` 的拋出者寫成 `validate_ticket`／`validate_release`）。

本 Phase 的兩個函式是純函式，**不收 `deadline`**：正規化只做欄位檢查，沒有網路或 IO，不必自己看時間。期限由呼叫端管——Phase 32 的 `normalize_then_accept(*, domain, adapter, event_type, headers, payload, deadline)` 在呼叫 `validate_ticket`／`validate_release` 之前先 `assert_time_left(deadline, step="normalize")`（Phase 30 的 helper），拿的是 Phase 30 handler 進入時算好的同一個 `deadline`，**不重新計八秒**、也不在本 Phase 內再呼叫 `monotonic()`。

## 6. Task 1：鎖定 Ticket canonical 契約

- [x] **Step 1：建立失敗測試**

```python
import pytest

from training_kb.errors import IngressError
from training_kb.ingress import validate_ticket
from training_kb.models import TicketSource

@pytest.fixture
def valid_ticket() -> dict[str, object]:
    return {
        "id": "t_gh-acme-app-881", "source": "github_issue",
        "text": "會前摘要在哪裡開啟？", "author": "u_gh-4821",
        "ts": "2026-08-03T10:00:00Z", "project_id": "demo",
    }

@pytest.mark.parametrize("missing", ["id", "source", "text", "author", "ts", "project_id"])
def test_ticket_requires_all_ingress_fields(valid_ticket, missing):
    valid_ticket.pop(missing)
    with pytest.raises(IngressError) as error:
        validate_ticket(valid_ticket)
    assert missing in error.value.fields

def test_ticket_has_no_analysis_output_at_ingress(valid_ticket):
    ticket = validate_ticket(valid_ticket)
    assert ticket.source is TicketSource.GITHUB_ISSUE
    assert ticket.embedding is None
    assert ticket.cluster_id is None
    assert ticket.feature_ids == []
```

- [x] **Step 2：執行並確認紅燈**

```bash
uv run pytest tests/unit/test_ingress_validation.py -q -k ticket
```

預期：FAIL，訊號包含 `cannot import name 'validate_ticket'`。不要先建空殼讓測試假綠。

- [x] **Step 3：建立最小實作**

```python
from collections.abc import Mapping, Sequence
from datetime import datetime

from training_kb.clock import parse_iso
from training_kb.errors import IngressError
from training_kb.models import Ticket, TicketSource

TICKET_REQUIRED = ("id", "source", "text", "author", "ts", "project_id")
ANALYSIS_FIELDS = ("cluster_id", "feature_ids", "embedding")

def missing_nonempty_strings(
    payload: Mapping[str, object], keys: Sequence[str]
) -> tuple[str, ...]:
    return tuple(
        key for key in keys
        if not isinstance(payload.get(key), str) or not str(payload[key]).strip()
    )

def _parsed_ts(payload: Mapping[str, object]) -> datetime:
    try:
        return parse_iso(str(payload["ts"]))
    except ValueError as error:
        raise IngressError("ts 必須是 aware 的 UTC ISO-8601 時間", ("ts",)) from error

def validate_ticket(payload: Mapping[str, object]) -> Ticket:
    missing = missing_nonempty_strings(payload, TICKET_REQUIRED)
    if missing:
        raise IngressError("Ticket 必填欄位不完整", missing)
    prefilled = tuple(key for key in ANALYSIS_FIELDS if key in payload)
    if prefilled:
        raise IngressError("接入不得預填分析欄位", prefilled)
    if payload["source"] not in set(TicketSource):
        raise IngressError("Ticket source 不合法", ("source",))
    return Ticket(
        id=str(payload["id"]), source=TicketSource(str(payload["source"])),
        text=str(payload["text"]), author=str(payload["author"]),
        ts=_parsed_ts(payload), project_id=str(payload["project_id"]),
        cluster_id=None, feature_ids=[], embedding=None,
    )
```

`set(TicketSource)` 是 Phase 03 StrEnum 的成員集合；`"github_issue" in set(TicketSource)` 成立，因為 StrEnum 成員本身就是字串，不必另外維護一份字面值清單。列舉轉型要寫成 `TicketSource(str(payload["source"]))`：`payload` 的值型別是 `object`，mypy strict 不接受直接餵進 `TicketSource(...)`；此處已經通過必填檢查，`str(...)` 只是讓型別收斂，不會改值。

- [x] **Step 4：補邊界測試並跑完整檔案確認綠燈**

```python
@pytest.mark.parametrize(("patch", "expected"), [
    ({"cluster_id": "c12"}, ("cluster_id",)),
    ({"feature_ids": []}, ("feature_ids",)),
    ({"embedding": [0.1]}, ("embedding",)),
    ({"author": "   "}, ("author",)),
    ({"ts": "2026-08-03T10:00:00"}, ("ts",)),
    ({"source": "slack"}, ("source",)),
])
def test_ticket_boundaries_report_exact_fields(valid_ticket, patch, expected):
    with pytest.raises(IngressError) as error:
        validate_ticket(valid_ticket | patch)
    assert error.value.fields == expected
```

```bash
uv run pytest tests/unit/test_ingress_validation.py -q
```

預期：`-k ticket` 的案例全綠；`author` 為全空白時歸到「缺必填」而不是通過（D23 覆寫 D09 的舊答案）。

- [x] **Step 5：提交**

```bash
git add src/training_kb/ingress.py tests/unit/test_ingress_validation.py
git commit -m "feat(ingress): 正規化Ticket契約"
```

## 7. Task 2：鎖定 Release 與 renamed 條件

- [x] **Step 1：建立失敗測試**

```python
from training_kb.ingress import validate_release
from training_kb.models import ReleaseKind, ReleaseSource

@pytest.fixture
def valid_release() -> dict[str, object]:
    return {
        "id": "r_gh-acme-app-pr42-1", "source_event_id": "gh-acme-app-pr42",
        "source": "github_pr", "feature": "Prepare", "kind": "removed",
        "evidence": "PR diff hunk: remove Meeting Summary entry point",
        "ts": "2026-08-04T00:00:00Z",
    }

def test_renamed_requires_old_and_new_name(valid_release):
    payload = valid_release | {"kind": "renamed", "old_name": "Meeting Summary"}
    with pytest.raises(IngressError) as error:
        validate_release(payload)
    assert error.value.fields == ("new_name",)

def test_changed_does_not_invent_names(valid_release):
    release = validate_release(valid_release | {"kind": "changed"})
    assert release.kind is ReleaseKind.CHANGED
    assert release.source is ReleaseSource.GITHUB_PR
    assert release.old_name is None
    assert release.new_name is None
```

- [x] **Step 2：執行並確認紅燈**

```bash
uv run pytest tests/unit/test_ingress_validation.py -q -k release
```

預期：FAIL，訊號包含 `cannot import name 'validate_release'`。

- [x] **Step 3：建立最小實作**

```python
from training_kb.models import Release, ReleaseKind, ReleaseSource

RELEASE_REQUIRED = ("id", "source", "feature", "kind", "evidence", "ts")

def validate_release(payload: Mapping[str, object]) -> Release:
    fields = missing_nonempty_strings(payload, RELEASE_REQUIRED)
    if payload.get("kind") == ReleaseKind.RENAMED:
        fields += missing_nonempty_strings(payload, ("old_name", "new_name"))
    if fields:
        raise IngressError("Release 欄位不完整", fields)
    if payload["source"] not in set(ReleaseSource):
        raise IngressError("Release source 不合法", ("source",))
    if payload["kind"] not in set(ReleaseKind):
        raise IngressError("Release kind 不合法", ("kind",))
    return Release(
        id=str(payload["id"]),
        source_event_id=_optional_string(payload, "source_event_id"),
        source=ReleaseSource(str(payload["source"])), feature=str(payload["feature"]),
        kind=ReleaseKind(str(payload["kind"])), old_name=_optional_string(payload, "old_name"),
        new_name=_optional_string(payload, "new_name"), evidence=str(payload["evidence"]),
        ts=_parsed_ts(payload),
    )
```

`source_event_id`、`old_name`、`new_name` 是「必填但可為 null」的欄位，所以用 `payload.get(...)`（實作包成 `_optional_string`，見 §5）：`payload["old_name"]` 在 `changed`／`removed` 事件會直接 `KeyError`，那是程式錯誤，不該變成接入錯誤。`payload.get("kind") == ReleaseKind.RENAMED` 成立是因為 StrEnum 成員等於自己的字串值。`IngressError` 的 constructor 已排序去重，這裡不必再 `sorted(set(...))`。

- [x] **Step 4：補多 Feature 子 Release 測試並跑完整檔案確認綠燈**

一個 PR 同時改到兩個功能時（設計 F14），adapter 先拆成兩個候選，本函式**逐筆**驗證；`id` 由 `github_release_id(owner, repo, pr_number, k)` 產生、`source_event_id` 由 `github_source_event_id(owner, repo, pr_number)` 產生，兩筆相同。

```python
def test_sub_releases_share_source_event_id(valid_release):
    first = validate_release(valid_release)
    second = validate_release(
        valid_release | {"id": "r_gh-acme-app-pr42-2", "feature": "Share Summary"}
    )
    assert first.id != second.id
    assert first.source_event_id == second.source_event_id == "gh-acme-app-pr42"
    assert "42" not in {first.id, second.id}
    with pytest.raises(IngressError) as error:
        validate_release(valid_release | {"id": ""})
    assert error.value.fields == ("id",)
```

```bash
uv run pytest tests/unit/test_ingress_validation.py -q
```

預期：required、renamed、enum、時間、子 Release 案例全綠；移除或重排 payload 文字都不改變 `id`，也不得讓模型補 ID。

- [x] **Step 5：提交**

```bash
git add src/training_kb/ingress.py tests/unit/test_ingress_validation.py
git commit -m "feat(ingress): 正規化Release契約"
```

## 8. Task 3：用 O6 fixture 做可追溯整合

- [x] **Step 1：建立失敗測試**

```python
import json
from pathlib import Path

import pytest

from training_kb.ingress import validate_ticket
from training_kb.source_ids import (approved_stable_keys, github_ticket_id,
                                    github_user_id, load_source_approvals)

REPO_ROOT = Path(__file__).resolve().parents[2]   # 相對路徑會隨 pytest 的 cwd 飄掉
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "github"
APPROVED = approved_stable_keys(
    load_source_approvals(REPO_ROOT / "tests" / "fixtures" / "o6" / "approved-sources.json")
)
ISSUE_APPROVED = bool(APPROVED.get(("github.com", "issues")))
PR_APPROVED = bool(APPROVED.get(("github.com", "pull_request")))

@pytest.mark.xfail(not ISSUE_APPROVED, strict=True, reason="O6 尚未核定")
def test_issue_fixture_maps_to_traceable_ticket():
    event = json.loads((FIXTURES / "issue-opened.json").read_text(encoding="utf-8"))
    owner, repo = event["repository"]["full_name"].split("/")
    payload = {
        "id": github_ticket_id(owner, repo, event["issue"]["number"]),
        "source": "github_issue", "text": event["issue"]["body"],
        "author": github_user_id(event["issue"]["user"]["id"]),
        "ts": event["issue"]["created_at"], "project_id": "demo",
    }
    ticket = validate_ticket(payload)
    assert ticket.id == github_ticket_id(owner, repo, event["issue"]["number"])
    assert ticket.author == github_user_id(event["issue"]["user"]["id"])
    assert ticket.model_dump_json() == validate_ticket(payload).model_dump_json()
```

- [x] **Step 2：執行並確認紅燈**

```bash
uv run pytest tests/integration/test_o6_github_mapping.py -q
```

預期：O6 已核定時 FAIL（缺 `validate_ticket` 或 Phase 13 的 ID 函式）；O6 尚未核定時是明確 XFAIL。兩種情況都不可宣稱整合完成。**本次實作的實際情況**：Task 1／Task 2 已經先把 `validate_ticket`／`validate_release` 做出來，這個紅燈在 Task 1 Step 2 就消化掉了，所以 Task 3 Step 2 改用 mutation 證明不是假綠——暫時把 `author` 從 `TICKET_REQUIRED` 拿掉，整合測試立刻紅燈，還原後綠燈。

**xfail 的成立條件**：`xfail(strict=True)` 要求「未核定時測試真的會失敗」，所以每個測試的第一行是 `assert (domain, event_type) in APPROVED`。這個 gate 斷言不通過就是 XFAIL；維護者核定之後它自動通過，剩下的斷言才會真的跑。

- [x] **Step 3：補 PR fixture 的子 Release 斷言**

同樣從 `tests/fixtures/github/pull-request-merged.json` 讀入，斷言至少包含：上游事件識別 `gh-<owner>-<repo>-pr<n>`、canonical `Release.id`、stable user、兩筆 `source_event_id` 相同、子 Release 依 `k` 升序（用 Phase 13 的 `sub_release_ids`）、`feature` 與 `kind` 在接入當下就已解析（ING Rule 23）。期望值一律由 Phase 13 的函式產生，**不在測試裡手寫另一套期望 ID**。`Release` 模型沒有 author 欄位，所以「stable author」這一項斷言的是 `github_user_id(sender.id)` 的編碼可追溯，而不是存進 `Release`。fixture 的兩個子變更放在 `pull_request.body`，本 Phase 在測試裡用一個十行的 `pr_changes` 扮演 adapter 角色；真正的抽取工具是 Phase 36 的 `parse_pr_diff`。

- [x] **Step 4：跑完整檔案確認綠燈或明確 XFAIL**

```bash
uv run pytest tests/integration/test_o6_github_mapping.py -q
```

預期：同 fixture 執行兩次，`model_dump_json()` 完全相同。gate 是**逐 `(domain, event_type)`** 判斷，不是整個檔案一起（00A §4.2 O6：「該 `(domain, event_type)` 為 blocked」）：`("github.com", "issues")` 已核定，兩個 Issue 測試是真綠燈；`("github.com", "pull_request")` 的 `approved_by` 仍是空字串，子 Release 測試維持 `xfail(strict=True)`，該來源保持 blocked；**不可用自造 fixture 或改動 Phase 13 的核定紀錄改成綠燈**。

- [x] **Step 5：提交**

```bash
git add tests/integration/test_o6_github_mapping.py
git commit -m "test(ingress): 以O6 fixture鎖定可追溯正規化"
```

## 9. 驗收

```bash
uv run pytest tests/unit/test_ingress_validation.py -q
uv run pytest tests/integration/test_o6_github_mapping.py -q
```

| 路徑 | 輸入 | 預期資料結果 |
|---|---|---|
| Happy | O6 Issue fixture 的六個欄位 | `Ticket(source=TicketSource.GITHUB_ISSUE, author="u_gh-4821")`；`embedding`／`cluster_id` 為 `None`、`feature_ids == []`。單一功能變更的 PR fixture 得到一筆 `Release`，`feature` 與 `kind` 當下就有值。 |
| Failure | 缺 `author` 的手動匯入檔；`kind="renamed"` 但只有 `old_name` | `IngressError(fields=("author",))`／`(("new_name",))`；零個物件、零筆 Repository 寫入。 |
| Failure | `source="slack"`／`kind="deprecated"` | `IngressError(fields=("source",))`／`IngressError(fields=("kind",))`。 |
| Boundary | `author="   "`、`ts="2026-08-03T10:00:00"` | 分別是 `("author",)`、`("ts",)`，不是通過。 |
| Boundary | 同一個 PR 的兩個功能變更 | 兩筆不同 `Release.id`、相同 `source_event_id`；`Release.id` 不等於 `42`。 |

人工驗收（不能只看 PASS）：打開 `tests/fixtures/github/issue-opened.json`，逐欄比對測試斷言的 ID 與作者確實來自 fixture，而不是測試裡另外寫死的字串；再確認 `ingress.py` 全檔沒有 `boto3`、`Repository` 或 `Writer` 呼叫。**停止條件：** O6 未核對或 stable user 無法追溯時維持 `xfail(strict=True)`，停止 Phase 32 的雲端串接，也不得在文件寫「O6 已通過」。

## 10. 常見錯誤與停止條件

| 症狀 | 原因 | 修正／停止 |
|---|---|---|
| author 為 null 或空白仍通過 | 沿用 D09 舊答案（允許空 author） | 依 D23 覆寫：author 必填且需非空白。 |
| PR #42 直接存為 `42` | 混淆顯示編號與全域 ID | 改用 `github_release_id(owner, repo, 42, k)`。 |
| Release 到 pipeline 才判定 kind | 接入沒有完成正規化 | 欄位由 adapter 抽出，`validate_release` 在接入當下驗證完成。 |
| 模型產生 id | 把語意工作混入識別 | 停止；ID 必須確定性且可追溯，不得由模型補。 |
| `error.value.fields` 是 list | 誤以為 `IngressError` 收 list | `fields` 是排序去重後的 `tuple[str, ...]`，測試也要用 tuple 比較。 |
| `changed` 事件丟 `KeyError: 'old_name'` | 用 `payload["old_name"]` 取可為 null 的欄位 | 改用 `payload.get("old_name")`。 |
| 用自造 fixture 讓整合測試變綠 | 想繞過 O6 gate | 停止；O6 未核對時只能是明確 XFAIL。 |

## 11. 來源與 Rule 對照

- [接入來源事件.feature](../../spec/features/接入來源事件.feature)（00B 縮寫 `ING`）
  - Rule 21：「正規化物件必須具有 schema 的必填欄位」→ **primary**；Task 1／Task 2 的必填參數化測試直接斷言。
  - Rule 22：「Ticket 接入時 id、source、text、author、ts 與 project_id 必填」→ **primary**；Task 1 的六欄參數化測試，加上缺 `author` 的匯入檔拒絕案例。
  - Rule 23：「Release 接入時即完成功能與種類解析」→ **primary**；primary 證據是 Task 2 的**單元**斷言（`validate_release` 回來的 `Release` 當下就有非空 `feature` 與合法 `kind`，缺任一即 `IngressError`），Task 3 對 PR fixture 的斷言只是補強——`("github.com", "pull_request")` 未核定時它是 XFAIL，不能當成這條 Rule 的唯一證據（00B ING Rule 23）。
  - Rule 24：「正規化物件的 id 直接使用已全域唯一的上游識別碼」→ **相關（primary 在 [Phase 13](./13-Phase13-O6來源ID與穩定使用者契約.md)）**；本 Phase 只驗證 ID 來自 Phase 13 的編碼函式、PR 編號不單獨成為 `Release.id`，不重複宣稱編碼契約。
  - Rule 25：「正規化物件的枚舉欄位必須使用合法值」→ **primary**；Task 1／Task 2 用 `set(TicketSource)`、`set(ReleaseSource)`、`set(ReleaseKind)` 斷言非法值被拒。
- [依改版更新教學.feature](../../spec/features/依改版更新教學.feature)（00B 縮寫 `REL`）
  - Rule 1：「從 PR diff 或 changelog 抽出 feature、kind、old_name 與 new_name」→ **相關（primary 在 [Phase 37](./37-Phase37-Rote-Agent回退與成功提交.md)）**；抽取工具在 [Phase 36](./36-Phase36-JSONPath與白名單Adapter.md)，本 Phase 只驗證抽取後的 canonical 結果。
- [設計 §7.1](../../design/training-kb.md)：Ticket／Release 必填欄位與合法值；接入失敗回傳不合法欄位，不保存成合法業務物件。
- [設計 §18 O6](../../design/training-kb.md)：來源 ID、STABLE_KEYS 與跨來源 stable user 尚待核對；未核對前該來源 blocked。
- 設計 §19：D10（Release 必填欄位與 renamed 條件）、D23 覆寫 D09（author 必填、三個實體共用穩定 user）、F14（多 Feature 拆成多個子 Release、共用父來源事件識別碼）。

## 12. 完成清單

- [x] Ticket 六個必填欄位與 `source` 已驗證，全空白字串算缺值。
- [x] Release 六個必填欄位、`kind`／`source` 與 renamed 的 `old_name`／`new_name` 已驗證。
- [x] 分析欄位（`embedding`／`cluster_id`／`feature_ids`）預填即拒絕。
- [x] `IngressError.fields` 一律是 tuple，測試以 tuple 比較。
- [x] 多 Feature 使用共同 `source_event_id` 與不同子 Release ID。
- [x] PR number 未直接作 `Release.id`。
- [x] stable user 與 ID 都可追到 Phase 13 的 O6 fixture 與編碼函式。
- [x] O6 若未核對，文件與測試明示 blocked（`xfail(strict=True)`），未宣稱整合完成。

## 13. 實作偏差紀錄（2026-09-14）

實作後回填；每一條都是「Phase 文件與 00A／既有程式不一致」而修文件，不改 00A 的名稱。

| # | 位置 | 原文 | 實際做法與理由 |
|---|---|---|---|
| 1 | §4 | 修改 `models.py` | **未改**。Phase 04 的 validator 已涵蓋本 Phase 需要的模型層限制，00A §3.2 允許但不強制修改。 |
| 2 | §5、§6 Step 3、§7 Step 3 | `TicketSource(payload["source"])`、`payload.get("old_name")` | mypy strict（`files = ["src", "infra"]`）不接受把 `object` 餵給 `str` 參數或 `str \| None` 欄位，改成 `TicketSource(str(...))` 與 `_optional_string(payload, key)`；行為不變。 |
| 3 | §5 流程圖 | 第 (5) 關只寫 aware UTC | 依 00A §3.5「datetime 欄位一律 UTC 整秒」補上微秒即拒；並補第 (6) 關把模型層的 `ValidationError` 收斂成 `IngressError`（00A §4.1 指定這兩個函式是 `IngressError` 的拋出者，webhook handler 只認 `IngressError`／`TimeoutError`）。 |
| 4 | §8 Step 1 | `Path("tests/fixtures/github")` | 相對路徑會隨 pytest 的 cwd 飄掉，改用 `Path(__file__).resolve().parents[2]`，與 Phase 13 的 `test_o6_fixture_contract.py` 同一種寫法。 |
| 5 | §8 Step 2 | 預期紅燈是「缺 `validate_ticket`」 | Task 1／Task 2 先做，該紅燈已在 Task 1 Step 2 消化；Task 3 改用 mutation（暫時拿掉 `TICKET_REQUIRED` 的 `author`）證明整合測試不是假綠。 |
| 6 | §8 Step 3 | 斷言「stable author」 | `Release` 模型沒有 author 欄位（00A §5.1），改為斷言 `github_user_id(sender.id)` 的編碼可追溯到核定紀錄的 `stable_user_source`。 |
| 7 | §8 Step 4 | 「整個檔案維持 `xfail(strict=True)`」 | O6 是**逐 `(domain, event_type)`** 判斷（00A §4.2）：`issues` 已核定所以真綠，`pull_request` 未核定所以 `xfail(strict=True)`。為了讓 strict xfail 成立，每個測試第一行先 `assert (domain, event_type) in APPROVED`。 |
| 8 | §11 Rule 23 | primary 證據寫在 Task 3 | 依 00B ING Rule 23，primary 證據是 Task 2 的單元斷言；Task 3 的 PR 斷言在未核定期間是 XFAIL，只能當補強。 |
| 9 | `ingress.py` 模組 docstring | 區塊清單把「正規化」列為第 4 點卻要求放在接線點之上 | 依「放在接線點之上」為準，把正規化改成第 3 節、接線點改成第 4 節，讓清單順序與檔案實際順序一致。 |
