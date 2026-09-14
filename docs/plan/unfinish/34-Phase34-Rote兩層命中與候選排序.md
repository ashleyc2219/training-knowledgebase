# Phase 34：Rote 兩層命中與候選排序實作計畫

> **給 agentic worker：** 使用 `superpowers:subagent-driven-development`（建議）或 `superpowers:executing-plans` 完成本計畫；每個 Task 先建立失敗測試，再寫最小實作。

**目標：** 實作 Rote 前兩層的確定性選擇：第一層 exact signature；第二層同 domain＋adapter 的 key Jaccard，門檻至少 0.8，並有固定平手順序。

**架構：** 任何 PROC 必須 `status=active` 且 `success_count >= 3` 才能重放。Layer 1 以 `PROC#<signature>` 主鍵取得；沒命中才列出同範圍候選交 `pick_layer2`。兩層都是純比較與查詢，成功選定時不呼叫任何模型。

**技術：** Python 3.12、Pydantic v2 model、pytest、moto DynamoDB repository fixture。

## 1. 文件定位與全域限制

- **主來源：** [設計 §7.2、§9.1、§20.7](../../design/training-kb.md)；名稱以 [00A 共用契約與名詞](00A-共用契約與名詞.md) 第 6.8 節為準。
- **前置：** [Phase 33：Rote 結構簽名與 STABLE_KEYS](33-Phase33-Rote結構簽名與STABLE_KEYS.md) 的 `structure_signature`／`event_stable_keys`；[Phase 06：Repository Metadata 與實體讀寫](06-Phase06-Repository-Metadata與實體讀寫.md) 的 `get_proc`；[Phase 08：分頁查詢與一致讀取基礎](08-Phase08-分頁查詢與一致讀取基礎.md) 的 `list_procs`。前置未通過時停止。
- **後續：** [Phase 35：PROC 成功失敗與退役生命週期](35-Phase35-PROC成功失敗與退役生命週期.md) 負責計數與退役；[Phase 37：Rote Agent 回退與成功提交](37-Phase37-Rote-Agent回退與成功提交.md) 呼叫本 Phase 決定要不要重放。
- **本階段不做：** 不執行 adapter、不做 Agent fallback、不呼叫模型、不寫入任何 `PROC#` item（計數與退役是 Phase 35、寫回是 Phase 37）；不讓 retired 或未滿三次成功的流程進入排序。
- **gate 狀態：** `ProvenWorkflow.domain`／`adapter` 是 00A 裁決 D-09 的**本計畫選擇**，對應 O2 的「PROC 同來源脈絡缺持久化位置」；O2 未 PASS 前，不得宣稱候選範圍的持久化形狀已定案。O6 未核對的 `(domain, event_type)` 在 Phase 33 就被擋下，本 Phase 拿不到 signature，也不得改用 domain 當 fallback 分組。
- 以下程式檔均是實作時預計建立或修改；本計畫本身不代表它們已存在。

`same sender` 在本案是「可信來源網域 ＋ adapter 類型」共同構成的範圍（設計 §19 的決策 D19），不是顯示名稱、寄件 email 或 `project_id`。

## 2. 你在整體流程的位置

```text
Phase 33 產出 signature
       |
       v
[你在這裡] Layer 1：get_proc(signature) 且 replayable？
       | 否（沒有 / retired / success < 3）
       v
[你在這裡] Layer 2：list_procs(domain, adapter) -> replayable -> Jaccard >= 0.8 -> 排序
       | 否                          | 是
       v                             v
Phase 37 走 Agent（第三層）    重放已記錄的 adapter 步驟，全程不呼叫模型
                                     |
                                     v
                    Phase 35 記 on_replay_success / on_replay_failure
```

## 3. 完成後看得到什麼

`PROC#d1ad3cfd19a24c4d` 是 `active, success_count=4`，新事件的 signature 剛好相同 → Layer 1 直接回它，連候選清單都不查。把它改成 `retired` 之後，同一個事件改走 Layer 2：同 domain＋adapter 裡有三個 `active, success_count>=3` 的候選，keys 各是 `{action, issue, repository, sender}`（分數 1.0）、多一個 `installation`（分數 0.8）、少掉 `sender` 又多兩個沒核定的欄位（分數 0.5）。分數 0.5 的直接淘汰；分數最高者勝出。若最高分有兩個並列，先比 `last_used` 新的；連 `last_used` 都一樣，就取 PROC 識別碼（signature）字典序最小的那個，所以 `bbbb000000000001` 會贏過 `bbbb000000000009`，而且候選清單無論怎麼排列都得到同一個勝者。

signature 一律是 16 個小寫 hex 字元（[Phase 04](04-Phase04-十個邏輯實體模型.md) 對 `ProvenWorkflow` 的不變條件），所以本文件的測試值也全部長這樣；寫成 `p01`、`sibling-1` 這種好讀的簡寫會在建物件時就被 `ValidationError` 擋下。

## 4. 名詞小抄

| 名詞 | 白話意思 |
|---|---|
| Layer 1／Layer 2 | 第一層用 signature 精確對主鍵；第二層在同範圍內用欄位名重疊度找「夠像」的舊流程。 |
| Jaccard | 兩組欄位名「交集數 ÷ 聯集數」；1.0 是完全一樣，0.0 是完全沒交集。 |
| replayable（可重放） | 一個 PROC 同時滿足 `status=active` 與 `success_count >= 3` 才准重放。 |
| `last_used` | 上一次成功重放或成功寫回的時間，必填且一定帶時區；平手時比它，越新越優先。 |
| 同範圍（same sender） | 同一個 `domain` 加同一個 `adapter`；不看顯示名稱、email 或專案。 |
| D19／F03／F04 | 設計 §19 的決策編號：D19 定義範圍、F03 說第二層沿用三次成功門檻、F04 定平手順序。 |

## 5. 預計檔案

| 動作 | 路徑 | 責任 |
|---|---|---|
| 修改 | `src/training_kb/rote.py` | `JACCARD_THRESHOLD`、`PROC_MIN_SUCCESS`、`jaccard`、`replayable`、`pick_layer2`、`find_replayable`。 |
| 新增 | `tests/unit/rote/test_matching.py` | 門檻、候選範圍、平手排序、空集合。 |
| 新增 | `tests/integration/test_rote_lookup.py` | exact lookup、retired 落到 Layer 2、零模型呼叫。 |
| 消費 | `tests/integration/conftest.py` | Phase 06 的 `repository` fixture。 |

## 6. 固定介面

### Consumes

```text
Phase 02  PermanentError                             # event_stable_keys 對未核定來源丟出，本 Phase 不攔截
Phase 03  ProcStatus                                  # 只有 ACTIVE = "active" 與 RETIRED = "retired"
Phase 04  ProvenWorkflow(signature, domain, adapter, steps, keys,
                         success_count, fail_count, status, last_used)
Phase 06  Repository.get_proc(signature: str) -> ProvenWorkflow | None
Phase 08  Repository.list_procs(domain: str, adapter: str) -> list[ProvenWorkflow]
Phase 33  RawEvent、structure_signature(event) -> str、event_stable_keys(event) -> frozenset[str]
```

### Produces

```python
JACCARD_THRESHOLD: float      # 0.8，設計 §7.2；00A 第 5.4 節列為模組常數
PROC_MIN_SUCCESS: int         # 3，設計 §7.2 與決策 F03；本 Phase 首建，Phase 35 只 import

def jaccard(left: frozenset[str], right: frozenset[str]) -> float: ...
def replayable(proc: ProvenWorkflow) -> bool: ...
def pick_layer2(event: RawEvent, candidates: Sequence[ProvenWorkflow]) -> ProvenWorkflow | None: ...
def find_replayable(event: RawEvent, signature: str, *, repository: Repository) -> ProvenWorkflow | None: ...
```

`find_replayable` 把「Layer 1 不成才進 Layer 2」這個順序關進一個純查詢函式，讓 `tests/integration/test_rote_lookup.py` 能單獨驗證 00B 判給本 Phase 的 Rule 5／6／7／11。[Phase 37](37-Phase37-Rote-Agent回退與成功提交.md) 的 `Rote._pick_proc` **直接 import 它**（00A 第 6.8 節明文要求），不得自己再抄一次那三行順序；兩層順序全系統只有這一份，改這裡就是改全部。

`PROC_MIN_SUCCESS` 由**本 Phase 首建**（00A 第 5.4 節記在 Phase 34 名下），因為第一個用到它的就是本 Phase 的 `replayable`；[Phase 35](35-Phase35-PROC成功失敗與退役生命週期.md) 只從同一支 `rote.py` `import` 這個名字，不重新宣告，它自己新增的是連敗上限 `PROC_MAX_CONSECUTIVE_FAIL = 3`。不要另取 `MIN_SUCCESS` 這類第二個名字；`3` 這個數字在模組裡只出現一次。

## 7. 設計細節：兩層的判斷順序

```text
signature --> get_proc(signature) --> 有 item 且 replayable？ -- 是 --> Layer 1 命中
                                              |                        （不查候選清單）
              None、retired、success_count < 3 |
                                              v
                              list_procs(domain, adapter)
                                              |
                   replayable 過濾 + 同 domain+adapter 過濾
                                              |
        score = jaccard(event_stable_keys, proc.keys)，只留 score >= 0.8
                                              |
        sort key = (-score, -last_used.timestamp(), signature)
                                              |
                              取第一個；沒有候選就回 None
```

三個容易出錯的地方：

1. **exact 命中但不可重放時，不能直接放棄。** 設計 §7.2 的第二層條件是「第一層未命中」，而 retired／`success_count < 3` 就是未命中（決策 D20 與 Rule 20）。那個 exact PROC 會在 Layer 2 被同一個 `replayable` 過濾掉，所以不需要另外把它排除。
2. **`replayable` 只有兩個硬條件。** `ProcStatus` 只有 `active` 與 `retired` 兩個值（00A 第 5.3 節與 ERM 的 `PROVEN_WORKFLOW` note），沒有 `candidate` 這個狀態；「還沒累積到三次」是靠 `success_count` 表達，不是靠狀態。
3. **平手順序必須到底。** 設計 §19 的決策 F04 要求「分數最高 → `last_used` 最新 → 識別碼升序」，第三個鍵是用來消除平手的，少了它 Scan 回來的順序就會決定勝負，同一份資料換個順序可能得到不同結果。

`jaccard` 的空聯集回 `0.0` 而不是數學上的慣例值 1.0：設計 §7.2 明說「空集合不當成命中」。`0.8` 這個門檻用 `>=` 比較，所以 `4/5` 這種剛好等於 0.8 的分數要命中，`0.7999` 要淘汰；集合的 Jaccard 只能是有理數，最接近且在門檻下方的可構造值是 `3/4 = 0.75`，因此邊界測試同時用「`0.75` 淘汰／`0.8` 命中」的集合案例，以及 `0.7999`／`0.8` 兩個浮點數直接鎖定比較方向。

## 8. TDD Tasks

### Task 1：固定 Jaccard 與 replayable

- [ ] **Step 1：建立失敗測試**

```python
from datetime import UTC, datetime

import pytest

from training_kb.models import ProcStatus, ProvenWorkflow
from training_kb.rote import JACCARD_THRESHOLD, jaccard, replayable

NOW = datetime(2026, 9, 12, tzinfo=UTC)
ANY_SIG = "0123456789abcdef"   # signature 必須是 16 個小寫 hex（Phase 04 的不變條件）

def proc(signature: str, *, keys: set[str], status: ProcStatus = ProcStatus.ACTIVE,
         success: int = 3, last: datetime = NOW, domain: str = "github.com",
         adapter: str = "github_issue") -> ProvenWorkflow:
    return ProvenWorkflow(
        signature=signature, domain=domain, adapter=adapter, steps=[], keys=sorted(keys),
        success_count=success, fail_count=0, status=status, last_used=last,
    )

@pytest.mark.parametrize(("left", "right", "expected"), [
    (frozenset(), frozenset(), 0.0),
    (frozenset({"a"}), frozenset({"a"}), 1.0),
    (frozenset({"a", "b", "c"}), frozenset({"a", "b", "c", "d"}), 0.75),
    (frozenset({"a", "b", "c", "d"}), frozenset({"a", "b", "c", "d", "e"}), 0.8),
])
def test_jaccard(left: frozenset[str], right: frozenset[str], expected: float) -> None:
    assert jaccard(left, right) == expected

@pytest.mark.parametrize(("score", "accepted"), [(0.7999, False), (0.8, True)])
def test_threshold_uses_greater_or_equal(score: float, accepted: bool) -> None:
    assert (score >= JACCARD_THRESHOLD) is accepted

def test_replay_requires_active_and_three_successes() -> None:
    assert not replayable(proc(ANY_SIG, keys={"a"}, status=ProcStatus.RETIRED, success=9))
    assert not replayable(proc(ANY_SIG, keys={"a"}, success=2))
    assert replayable(proc(ANY_SIG, keys={"a"}, success=3))
```

- [ ] **Step 2：執行並確認紅燈**

```bash
uv run pytest tests/unit/rote/test_matching.py -q
```

預期：FAIL，訊號包含 `cannot import name 'jaccard' from 'training_kb.rote'`。若訊號是 `ProvenWorkflow` 不接受 `domain`／`adapter`，先停下來回 [Phase 04](04-Phase04-十個邏輯實體模型.md) 依 00A 裁決 D-09 補欄位，不要在 item 上偷加模型沒有的屬性。

- [ ] **Step 3：建立最小實作**

```python
from training_kb.models import ProcStatus, ProvenWorkflow

JACCARD_THRESHOLD = 0.8
PROC_MIN_SUCCESS = 3          # 本 Phase 首建；Phase 35 只 import，另加 PROC_MAX_CONSECUTIVE_FAIL

def jaccard(left: frozenset[str], right: frozenset[str]) -> float:
    union = left | right
    if not union:
        return 0.0
    return len(left & right) / len(union)

def replayable(proc: ProvenWorkflow) -> bool:
    return proc.status == ProcStatus.ACTIVE and proc.success_count >= PROC_MIN_SUCCESS
```

- [ ] **Step 4：跑完整檔案確認綠燈**

```bash
uv run pytest tests/unit/rote/test_matching.py -q
```

預期：`7 passed`；空集合回 `0.0`、`0.75` 在門檻下、`0.8` 命中、`retired` 與 `success_count=2` 都不可重放。

- [ ] **Step 5：提交**

```bash
git add src/training_kb/rote.py tests/unit/rote/test_matching.py
git commit -m "feat(rote): 固定重放資格與相似度"
```

### Task 2：確定性選出 Layer 2 候選

- [ ] **Step 1：建立失敗測試**

```python
from itertools import permutations

from training_kb.rote import RawEvent, pick_layer2

FOUR = {"action", "issue", "repository", "sender"}
EVENT = RawEvent("github.com", "github_issue", "issues", {},
                 {"action": "opened", "issue": {}, "repository": {}, "sender": {}})
EMPTY_EVENT = RawEvent("github.com", "github_issue", "issues", {}, {})

LOOSE = "aaaa000000000000"      # 多一個 installation，分數 0.8
OLDEST = "bbbb000000000002"     # 分數 1.0，last_used 最舊
TIE_HIGH = "bbbb000000000009"   # 分數 1.0、last_used 最新，字典序較大
TIE_LOW = "bbbb000000000001"    # 分數 1.0、last_used 最新，字典序最小 -> 應該勝出

def test_layer2_picks_highest_score_then_last_used_then_signature() -> None:
    loose = proc(LOOSE, keys=FOUR | {"installation"}, last=datetime(2026, 9, 9, tzinfo=UTC))
    older = proc(OLDEST, keys=FOUR, last=datetime(2026, 9, 1, tzinfo=UTC))
    newer_b = proc(TIE_HIGH, keys=FOUR, last=datetime(2026, 9, 2, tzinfo=UTC))
    newer_a = proc(TIE_LOW, keys=FOUR, last=datetime(2026, 9, 2, tzinfo=UTC))
    for order in permutations([loose, older, newer_b, newer_a]):
        assert pick_layer2(EVENT, list(order)).signature == TIE_LOW

@pytest.mark.parametrize("candidate", [
    proc("c0de000000000001", keys=FOUR, status=ProcStatus.RETIRED),
    proc("c0de000000000002", keys=FOUR, success=2),
    proc("c0de000000000003", keys=FOUR, domain="discord.com"),
    proc("c0de000000000004", keys=FOUR, adapter="github_pr"),
    proc("c0de000000000005", keys={"action", "issue", "repository", "x", "y"}),
], ids=["retired", "success-2", "other-domain", "other-adapter", "score-0.5"])
def test_layer2_rejects_unqualified_candidates(candidate: ProvenWorkflow) -> None:
    assert pick_layer2(EVENT, [candidate]) is None

def test_empty_key_sets_and_empty_candidate_list_never_match() -> None:
    assert pick_layer2(EMPTY_EVENT, [proc("0000000000000000", keys=set())]) is None
    assert pick_layer2(EVENT, []) is None
```

- [ ] **Step 2：執行並確認紅燈**

```bash
uv run pytest tests/unit/rote/test_matching.py -q -k layer2
```

預期：FAIL，訊號包含 `cannot import name 'pick_layer2' from 'training_kb.rote'`。

- [ ] **Step 3：建立最小實作**（接在 Phase 33 建立的同一個 `rote.py` 裡；`RawEvent` 與 `event_stable_keys` 已在本模組，不需要再 import）

```python
from collections.abc import Sequence

def _order_key(scored: tuple[float, ProvenWorkflow]) -> tuple[float, float, str]:
    score, proc = scored
    return (-score, -proc.last_used.timestamp(), proc.signature)

def pick_layer2(event: RawEvent, candidates: Sequence[ProvenWorkflow]) -> ProvenWorkflow | None:
    keys = event_stable_keys(event)
    hits = [
        (jaccard(keys, frozenset(proc.keys)), proc)
        for proc in candidates
        if replayable(proc) and proc.domain == event.domain and proc.adapter == event.adapter
    ]
    hits = [pair for pair in hits if pair[0] >= JACCARD_THRESHOLD]
    return min(hits, key=_order_key)[1] if hits else None
```

`last_used` 由 [Phase 04](04-Phase04-十個邏輯實體模型.md) 的 aware validator 保證必填且帶時區，所以排序可以直接用 `.timestamp()`；本 Phase 不補值、不把沒有時區的時間當 UTC，也不用 `now_utc()` 墊檔。即使 `list_procs` 已依 domain＋adapter 查詢，`pick_layer2` 仍再過濾一次，讓這個純函式可以單獨測試，也不倚賴查詢層是否寫對條件。

- [ ] **Step 4：跑完整檔案確認綠燈**

```bash
uv run pytest tests/unit/rote/test_matching.py -q
```

預期：`14 passed`；`permutations` 的 24 種排列都得到同一個勝者 `bbbb000000000001`，五個不合格候選各自回 `None`。`c0de000000000005` 與事件的四個 key 只交集三個、聯集六個，分數正好 `0.5`。

- [ ] **Step 5：提交**

```bash
git add src/training_kb/rote.py tests/unit/rote/test_matching.py
git commit -m "feat(rote): 排序第二層重放候選"
```

### Task 3：串起 exact lookup 並證明不呼叫模型

- [ ] **Step 1：建立失敗測試**

```python
import inspect
from collections.abc import Callable
from datetime import UTC, datetime

from training_kb.models import ProcStatus, ProvenWorkflow
from training_kb.rote import RawEvent, find_replayable, pick_layer2, structure_signature

FOUR = {"action", "issue", "repository", "sender"}
EVENT = RawEvent("github.com", "github_issue", "issues", {},
                 {"action": "opened", "issue": {}, "repository": {}, "sender": {}})
NEIGHBOUR = "beef000000000001"   # 同範圍的 Layer 2 候選，keys 多一個 installation
STALE = "dead000000000002"       # 同範圍但只成功兩次

def proc(signature: str, *, keys: set[str], status: ProcStatus = ProcStatus.ACTIVE,
         success: int = 3) -> ProvenWorkflow:
    return ProvenWorkflow(
        signature=signature, domain="github.com", adapter="github_issue", steps=[],
        keys=sorted(keys), success_count=success, fail_count=0, status=status,
        last_used=datetime(2026, 9, 12, tzinfo=UTC),
    )

class SpyWriter:
    """任何 Writer 方法被呼叫都會記下來；查詢路徑拿不到它，清單必須維持空的。"""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def __getattr__(self, name: str) -> Callable[..., None]:
        return lambda *args, **kwargs: self.calls.append(name)

def test_layer1_exact_hit_returns_that_proc(repository) -> None:
    signature = structure_signature(EVENT)
    repository.put_meta(proc(signature, keys=FOUR, success=4))
    assert find_replayable(EVENT, signature, repository=repository).signature == signature

def test_retired_exact_falls_through_to_layer2(repository) -> None:
    signature = structure_signature(EVENT)
    repository.put_meta(proc(signature, keys=FOUR, status=ProcStatus.RETIRED, success=9))
    repository.put_meta(proc(NEIGHBOUR, keys=FOUR | {"installation"}))
    picked = find_replayable(EVENT, signature, repository=repository)
    assert picked.signature == NEIGHBOUR

def test_no_qualified_proc_returns_none(repository) -> None:
    repository.put_meta(proc(STALE, keys=FOUR, success=2))
    assert find_replayable(EVENT, structure_signature(EVENT), repository=repository) is None

def test_lookup_never_reaches_a_writer(repository) -> None:
    writer = SpyWriter()
    signature = structure_signature(EVENT)
    repository.put_meta(proc(signature, keys=FOUR, success=4))
    assert find_replayable(EVENT, signature, repository=repository) is not None
    assert writer.calls == []
    assert "writer" not in inspect.signature(find_replayable).parameters
    assert "writer" not in inspect.signature(pick_layer2).parameters
```

`repository` 是 [Phase 06](06-Phase06-Repository-Metadata與實體讀寫.md) 在 `tests/integration/conftest.py` 提供的 fixture；`proc` 與 `SpyWriter` 都在本檔案內完整定義，不依賴其他測試模組。`SpyWriter` 會記下任何 Writer 方法呼叫，但本 Phase 的函式簽名根本收不到它，所以「清單為空」要和 `inspect.signature` 那條一起看才構成 Rule 11 的證據；端到端證據在 [Phase 37](37-Phase37-Rote-Agent回退與成功提交.md)。

- [ ] **Step 2：執行並確認紅燈**

```bash
uv run pytest tests/integration/test_rote_lookup.py -q
```

預期：FAIL，訊號包含 `cannot import name 'find_replayable' from 'training_kb.rote'`。

- [ ] **Step 3：建立最小實作**

```python
from training_kb.repository import Repository

def find_replayable(event: RawEvent, signature: str, *,
                    repository: Repository) -> ProvenWorkflow | None:
    exact = repository.get_proc(signature)
    if exact is not None and replayable(exact):
        return exact
    return pick_layer2(event, repository.list_procs(event.domain, event.adapter))
```

- [ ] **Step 4：跑完整檔案確認綠燈**

```bash
uv run pytest tests/unit/rote/test_matching.py tests/integration/test_rote_lookup.py -q
```

預期：`18 passed`。`beef000000000001` 的分數剛好是 `4/5 = 0.8`，證明門檻是 `>=`；retired 的 exact PROC 分數雖然是 `1.0`，仍被 `replayable` 濾掉，等同未命中。

- [ ] **Step 5：提交**

```bash
git add src/training_kb/rote.py tests/integration/test_rote_lookup.py
git commit -m "feat(rote): 串接兩層重放查詢"
```

## 9. 驗收矩陣

| 路徑 | 輸入 | 預期資料結果 |
|---|---|---|
| Happy | exact `PROC#<signature>` 為 `active, success_count=4` | Layer 1 直接回它，不查候選清單 |
| Happy | exact 不可重放，但同範圍有分數 `0.8` 的合格候選 | Layer 2 回該候選，整段查詢沒有任何模型呼叫 |
| Failure | 候選是 `retired`、`success_count=2`、不同 domain 或不同 adapter | 一律回 `None`，不重放 |
| Boundary | Jaccard 恰好 `0.8`（`4/5`）與 `0.75`（`3/4`）；浮點 `0.7999` 與 `0.8` | `0.8` 命中、`0.75` 與 `0.7999` 淘汰 |
| Boundary | 事件與候選 key 都是空集合；候選清單是空的；四個候選（其中三個同分）的 24 種排列 | 前兩者回 `None`；24 種排列得到同一個勝者（`last_used` 最新、signature 升序） |

人工驗收（不能只看 PASS）：用 `rg -n "converse_with_tools|generate_json|embed" src/training_kb/rote.py` 確認前兩層的程式路徑沒有任何模型呼叫；再用 `rg -n "PROC#|update_meta|put_meta" src/training_kb/rote.py` 確認本 Phase 只讀不寫 PROC，寫入全部留給 Phase 35／37。

## 10. 常見錯誤與停止條件

| 症狀 | 原因 | 修正／停止 |
|---|---|---|
| Layer 2 接受 `success_count=2` | 只在 Layer 1 檢查門檻 | 兩層共用 `replayable`，不要各寫一份條件。 |
| 同分結果隨 Scan 順序改變 | 缺最後一個排序鍵 | 補 `signature` 升序；用 `permutations` 測全部排列。 |
| 空集合被當成命中，或 `0.7999` 被當成命中 | 用了數學慣例值 `1.0`；或做了 `round(score, 1)` | 空聯集明確回 `0.0`（設計 §7.2）；直接比較原始浮點數與 `JACCARD_THRESHOLD`，不做位數處理。 |
| 命中後仍呼叫模型 | 把 lookup 與執行耦合在一起 | 用 `SpyWriter` 與 `inspect.signature` 鎖定零呼叫、零相依。 |
| `ProvenWorkflow` 沒有 `domain`／`adapter` | Phase 04 還沒套用 00A 裁決 D-09 | 停止本 Phase，回 Phase 04 補欄位；不得在 PROC item 上加模型沒有的屬性（00A 第 3.6 節）。 |
| 想用 `status="candidate"` 表示「還沒滿三次」 | `ProcStatus` 只有 `active`／`retired` | 用 `success_count` 表達累積進度；要新增狀態必須先改 00A 與 ERM，不在本 Phase 決定。 |
| `dataclasses.replace(proc, status=...)` 丟 `TypeError` | `ProvenWorkflow` 是 Pydantic v2 model，不是 dataclass | 改用 `proc.model_copy(update={...})` 或本文件的 `proc(...)` 測試工廠；`replace` 只能用在 `RawEvent` 這種 dataclass。 |
| `last_used` 缺值時用 `now_utc()` 補 | 把排序鍵變成執行時間 | 停止；`last_used` 必填且 aware，缺值代表資料有問題，回 Phase 04／35 查。 |
| 測試一建 `ProvenWorkflow` 就 `ValidationError` | signature 寫成 `p01`、`sibling-1` 這種簡寫 | Phase 04 要求 16 個小寫 hex；改用本文件的 `aaaa000000000000`、`beef000000000001` 這類值，`ids=` 仍可寫人看得懂的名字。 |
| 模組裡出現第二個 `3`（例如另外定義 `MIN_SUCCESS`） | 沒發現本 Phase 已經宣告過門檻常數 | 只留 `PROC_MIN_SUCCESS`；00A 第 5.4 節要求同一個數字不得有第二份。 |

## 11. 來源與 Rule 對照

- [接入來源事件.feature](../../spec/features/接入來源事件.feature)
  - Rule 5（primary）：「第一層以 PROC 主鍵精確比對來源簽名」→ `test_layer1_exact_hit_returns_that_proc`；Phase 33 為相關（產出那把主鍵）。Rule 6（primary）：「第一層只允許 status 為 active 的流程重放」→ `test_replay_requires_active_and_three_successes` 與 `test_retired_exact_falls_through_to_layer2`；Phase 35 為相關（狀態由它寫入）。
  - Rule 7（primary）：「第一層流程的 success_count 必須至少為 3」→ `test_replay_requires_active_and_three_successes` 的 `success=2`／`success=3` 與 `test_no_qualified_proc_returns_none`；Phase 60 改列為相關（實機累積三次成功）。
  - Rule 9（primary）：「第一層未命中才在同寄件者的流程中以 Jaccard 至少 0.8 比對欄位」→ `test_jaccard`、`test_threshold_uses_greater_or_equal`、`test_layer2_rejects_unqualified_candidates` 與 `test_retired_exact_falls_through_to_layer2` 的 `4/5` 案例。
  - Rule 11（primary）：「接入層命中已驗證流程的重放路徑不呼叫 LLM」→ `test_lookup_never_reaches_a_writer` 的 `writer.calls == []` 與兩個 `inspect.signature` 斷言；Phase 37、54 為相關。Rule 20（相關，primary 在 [Phase 35](35-Phase35-PROC成功失敗與退役生命週期.md)）：本 Phase 在查詢端斷言 retired 落到 Layer 2 且不勝出。
- [設計 §7.2](../../design/training-kb.md)：兩層都要求 `status=active` 且 `success_count >= 3`；Jaccard 是交集除以聯集；「多個合格候選依分數最高、last_used 最新、PROC 識別碼升序選定」；空集合不當成命中。
- 設計 §19 決策 F03：「沿用；第二層也必須 active 且 success_count >= 3 才可重放。」決策 F04：「選 Jaccard 最高者，同分時選最近成功使用者；須固定最後的識別碼排序以消除平手。」決策 D19：「來源網域與 adapter 類型共同構成範圍。」決策 D20：「代表連續失敗；成功重放後歸零，達到 3 才退役。」決策 F05（「首次成功記為 1，每次完整成功才累加」）解釋 `success_count` 怎麼長到 3，實作屬於 [Phase 35](35-Phase35-PROC成功失敗與退役生命週期.md)；本 Phase 只讀這個值。
- 設計 §15「來源與 Rote」驗收列：「Jaccard 0.7999／0.8；成功數 2／3」對應第 9 節的兩列 Boundary。
- [00A 共用契約與名詞](00A-共用契約與名詞.md) 第 5.1、5.3、5.4、6.8 節與裁決 D-01、D-09。

## 12. 完成清單

- [ ] `jaccard` 的空集合回 `0.0`，`3/4` 與 `4/5` 兩個邊界方向正確。
- [ ] `JACCARD_THRESHOLD` 用 `>=` 比較，`0.7999` 淘汰、`0.8` 命中，程式裡沒有第二份 `0.8`，門檻 `3` 也只有 `PROC_MIN_SUCCESS` 一份。
- [ ] Layer 1 與 Layer 2 共用同一個 `replayable`，沒有各寫一份門檻。
- [ ] exact PROC 不可重放時會繼續 Layer 2，而且不會被自己選回來。
- [ ] Layer 2 只看同 `domain` ＋同 `adapter` 的候選，`ProvenWorkflow.domain`／`adapter` 依裁決 D-09 存在。
- [ ] 三段排序（分數、`last_used`、signature）在所有排列下得到同一個勝者。
- [ ] 前兩層命中時 `writer.calls == []`、`find_replayable` 與 `pick_layer2` 的簽名都沒有 writer，且本 Phase 只讀不寫 PROC。
