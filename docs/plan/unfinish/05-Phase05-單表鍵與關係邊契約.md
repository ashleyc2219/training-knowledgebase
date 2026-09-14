# Phase 05 單表鍵與關係邊契約 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把十個邏輯實體穩定轉成單一 DynamoDB 表的物理鍵，並將 O1 `META` 建議留下可審查的接受或拒絕記錄。

**Architecture:** `models.py` 保留裸 ID，`keys.py` 是唯一可加上 `TUTORIAL#`、`VERSION#` 等類型前綴的地方。關係邊把完整終點 PK 放入 `SK` 與 `target`；View 鍵使用固定 JSON 編碼後的 SHA-256，不新增 `view_id` 實體欄位。

**Tech Stack:** Python 3.12、標準函式庫 `hashlib` / `json`、pytest。

## 文件定位

- **讀者：** 即將實作 Repository 與 DynamoDB 投影的工程師。
- **唯一主來源：** [設計 §9.1–9.2 與 §18 O1](../../design/training-kb.md#s9)。名稱與簽名以 [00A 共用契約與名詞](00A-共用契約與名詞.md) 第 3.3、6.2 節為準。
- **前置 Phase：** [Phase 04 十個邏輯實體](04-Phase04-十個邏輯實體模型.md)。
- **上一份：** [Phase 04](04-Phase04-十個邏輯實體模型.md)。
- **下一份：** [Phase 06 Repository Metadata 與實體讀寫](06-Phase06-Repository-Metadata與實體讀寫.md)。
- **本階段不做：** 不建立 AWS 表、不實作分頁、不寫任何 item、不產生 `OPS#`／`CONFIG#`／`SEQ#`／`LEASE#` 這類非業務前綴（`ops_pk`、`operation_ref` 由 [Phase 10](10-Phase10-O2操作紀錄與永久去重契約.md) 加在同一支 `keys.py`）、不提供 `make_version_id`／`parse_version_id`（[00A](00A-共用契約與名詞.md) 第 3.3、6.6 節把它們指派給 [Phase 20](20-Phase20-版本分配與重試重用.md) 的 `content.py`，`keys.py` 不得複製第二份版本 ID 解析規則）、不用計畫文字宣稱 O1 已核定。
- **與本 Phase 有關的 gate：** O1 是本 Phase 的首要 gate，只能由 `docs/decisions/O1-metadata-sort-key.md` 的真實核定紀錄改變狀態。**目前狀態：provisionally accepted（暫定接受）**——2026-09-14 由 controller 依維護者授權暫定接受 `META`，待 Timmy Lin 親自確認；紀錄的 `Approver` 欄寫的是 controller，不得寫成維護者本人已核定。未核定前一律寫「O1 尚未核定，`META` 仍是建議值，不得宣稱物理鍵契約已定案。」並停止 [Phase 06](06-Phase06-Repository-Metadata與實體讀寫.md)。O2、O3、O6 與本 Phase 無關，也不得因為鍵測試全綠而宣稱它們有進展。
- 以下程式檔均是實作時預計建立；本計畫本身不代表它們已存在。

## 你在整體流程的位置

```text
Phase 04 十個邏輯實體（只帶裸 ID）
            |
            v
+-----------+--------------------------+
| [你在這裡] Phase 05 keys.py          |
|  十個 PK builder / META 候選         |
|  edge_sk / parse_edge_sk / parse_pk  |
+-----------+--------------------------+
            |
            v
 Phase 06 Repository -> training_kb 單表
            |
            +--> Phase 07 邊與 target
            +--> Phase 10 追加 ops_pk / operation_ref
```

**metadata** 是實體本身的資料；**edge** 是「起點透過某關係指向終點」的獨立 item。`META` 是 metadata 的 sort key 候選，而非來源 ERM 已寫死的事實。

## 完成後看得到什麼

輸入裸 version ID `prepare-meeting@v2`，`version_pk` 回傳 `VERSION#prepare-meeting@v2`；再經 `parse_pk` 回得 `("VERSION", "prepare-meeting@v2")`。輸入同一組 View 的 version、user、UTC 時間兩次，`view_pk` 必須回傳相同 PK。

同一張表上，metadata 與 edge 只差在 SK 的形狀；本 Phase 只產生這兩種字串，不負責寫進去：

```text
metadata item                         edge item
+-----------------------------+       +--------------------------------------+
| PK = FEATURE#Prepare        |       | PK = STEP#prepare-meeting@v2#3       |
| SK = META（O1 建議值）      |       | SK = REFERENCES#FEATURE#Prepare      |
+-----------------------------+       | target = FEATURE#Prepare             |
       ^                              +--------------------------------------+
       |                                       ^
   feature_pk("Prepare")                       |
                                    step_pk("prepare-meeting@v2", 3)
                                    + edge_sk("REFERENCES", feature_pk("Prepare"))
                                    -> parse_edge_sk(...) 回 ("REFERENCES", "FEATURE#Prepare")
```

`TutorialStep` 沒有自己的 `META` item：設計 §9.1 讓同一筆 edge item 同時表達「第幾步」與「引用哪個 Feature」，所以步驟由 [Phase 07](07-Phase07-S3物件與關係邊讀寫.md) 的 `put_edge` 寫入，不走 metadata 路徑。

## 名詞小抄

| 名詞 | 白話意思 |
|---|---|
| 裸 ID | 不帶類型前綴的識別字串，例如 `Prepare`、`prepare-meeting@v2`、`R-007`；模型與流程只傳這種。 |
| 前綴 PK | 加了類型前綴的物理主鍵，例如 `FEATURE#Prepare`；只有 `keys.py` 可以加。 |
| metadata item | 實體本身那一筆 item，sort key 固定是 O1 選定的 `META`。 |
| 關係邊（edge） | 一筆獨立 item，用 `SK=關係#終點`、`target=終點` 表示「起點透過某關係指向終點」。 |
| `target` | 邊的終點完整 PK；唯一的 `by_target` GSI 用它當分割鍵反查（Phase 08、09）。 |
| digest（摘要） | 把一組值算成固定長度字串；View 用 SHA-256 摘要當 PK，只做去重，不是使用者身分。 |
| gate | 必須有真實證據才能通過的關卡；本 Phase 的 gate 是 O1，文件寫得再完整都不能自行關閉。 |

## 預計新增／修改的檔案

以下是實作時預計建立，目前不代表檔案存在：

- Create: `src/training_kb/keys.py`
- Create: `tests/unit/test_keys.py`
- Create: `docs/decisions/O1-metadata-sort-key.md`

## 固定介面

### Consumes

- Phase 02：`to_iso(dt: datetime) -> str`。
- Phase 04：十實體使用的裸 ID；不傳入已有類型前綴的關聯 ID。

### Produces

```python
META: str

def tutorial_pk(slug: str) -> str: ...
def version_pk(version_id: str) -> str: ...
def step_pk(version_id: str, number: int) -> str: ...
def feature_pk(feature_id: str) -> str: ...
def ticket_pk(ticket_id: str) -> str: ...
def release_pk(release_id: str) -> str: ...
def feedback_pk(feedback_id: str) -> str: ...
def view_pk(tutorial_version: str, user: str, ts: datetime) -> str: ...
def rule_pk(rule_id: str) -> str: ...
def proc_pk(signature: str) -> str: ...
def edge_sk(relation: str, target_pk: str) -> str: ...
def parse_edge_sk(value: str) -> tuple[str, str]: ...
def parse_pk(value: str) -> tuple[str, str]: ...
def parse_step_pk(value: str) -> tuple[str, int]: ...
```

簽名逐字取自 [00A 第 6.2 節](00A-共用契約與名詞.md)：十個 builder 只吃裸 ID，`view_pk` 是三元組固定 JSON 編碼的 SHA-256，`parse_edge_sk` 只切第一個 `#`。`META` 只能在 O1 決策記錄明確接受後成為實作常數。

`parse_step_pk` 是 `step_pk` 的反函式：`STEP#prepare-meeting@v2#3` 回 `("prepare-meeting@v2", 3)`。步驟的「第幾步」只存在 PK 裡（item 上沒有 `number` 屬性），所以 [Phase 08](08-Phase08-分頁查詢與一致讀取基礎.md) 的 `get_steps` 要靠它把步驟號還原並排序；它和 `parse_pk` 一樣放在 `keys.py`，不讓 Repository 自己切字串。`RELATIONS` 是 `keys.py` 的內部常數（五種關係的白名單），其他模組不 import 它。

`keys.py` 的 owner 是本 Phase，但不是最終形狀：[Phase 10](10-Phase10-O2操作紀錄與永久去重契約.md) 會在同一支檔案加上 `ops_pk(operation_id) -> str`（`OPS#<id>`）與 `operation_ref(operation_id, name) -> str`（`operations/<id>/<name>.json`）。`CONFIG#`、`SEQ#`、`LEASE#` 三個非業務前綴不經 builder，由 Phase 10 的 `put_meta_item`／`get_meta_item` 直接組字串。本 Phase 不預先寫這些函式；`parse_pk` 也刻意不維護前綴白名單，所以 Phase 10 追加前綴時不必回頭改它。

## Task 1：用 round-trip 測試鎖定鍵編碼

**Files:** `src/training_kb/keys.py`、`tests/unit/test_keys.py`。

**Interfaces:** Consumes 裸 ID 與 aware datetime；Produces 十種 PK builder、View digest 與 parser。

- [x] **Step 1：先寫十種 PK 與錯誤邊界測試**

```python
from datetime import UTC, datetime, timedelta

import pytest

from training_kb.keys import (
    edge_sk,
    feature_pk,
    parse_edge_sk,
    parse_pk,
    parse_step_pk,
    step_pk,
    version_pk,
    view_pk,
)


def test_version_and_edge_round_trip() -> None:
    assert parse_pk(version_pk("prepare-meeting@v2")) == (
        "VERSION", "prepare-meeting@v2"
    )
    value = edge_sk("REFERENCES", feature_pk("Prepare"))
    assert value == "REFERENCES#FEATURE#Prepare"
    assert parse_edge_sk(value) == ("REFERENCES", "FEATURE#Prepare")


def test_view_key_is_deterministic_but_time_sensitive() -> None:
    ts = datetime(2026, 8, 20, tzinfo=UTC)
    first = view_pk("prepare-meeting@v2", "u_01", ts)
    assert first == view_pk("prepare-meeting@v2", "u_01", ts)
    assert first.startswith("VIEW#")
    assert len(first) == len("VIEW#") + 64
    assert first != view_pk("prepare-meeting@v2", "u_01", ts + timedelta(seconds=1))
    assert first != view_pk("prepare-meeting@v2", "u_02", ts)


def test_already_prefixed_input_is_rejected() -> None:
    with pytest.raises(ValueError, match="bare identifier"):
        feature_pk("FEATURE#Prepare")
    with pytest.raises(ValueError, match="bare identifier"):
        step_pk("VERSION#prepare-meeting@v2", 3)


def test_step_pk_round_trip_recovers_the_step_number() -> None:
    value = step_pk("prepare-meeting@v2", 3)
    assert value == "STEP#prepare-meeting@v2#3"
    assert parse_step_pk(value) == ("prepare-meeting@v2", 3)
    with pytest.raises(ValueError, match="invalid step primary key"):
        parse_step_pk(version_pk("prepare-meeting@v2"))


def test_invalid_step_number_is_rejected() -> None:
    with pytest.raises(ValueError, match="positive"):
        step_pk("prepare-meeting@v2", 0)
    with pytest.raises(ValueError, match="positive"):
        step_pk("prepare-meeting@v2", True)


def test_unknown_relation_is_rejected() -> None:
    with pytest.raises(ValueError, match="unsupported edge relation"):
        edge_sk("VIEWED", feature_pk("Prepare"))
    with pytest.raises(ValueError, match="invalid edge sort key"):
        parse_edge_sk("HAS_VERSION#VERSION#prepare-meeting@v1")
```

`step_pk(..., True)` 也要被擋下來：Python 的 `bool` 是 `int` 的子類別，`True` 會被當成 `1` 而產生一筆假的第 1 步。

- [x] **Step 2：確認缺少 keys 模組時測試為紅**

```bash
uv run pytest tests/unit/test_keys.py -q
```

預期：FAIL，並指出 `training_kb.keys` 或目標函式不存在。

- [x] **Step 3：實作單一編碼入口**

```python
import json
from datetime import datetime
from hashlib import sha256

from training_kb.clock import to_iso

RELATIONS = frozenset({"REFERENCES", "SUPERSEDES", "APPLIED_TO", "ASKS_ABOUT", "REFERS_TO"})


def _bare(value: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip() or "#" in value:
        raise ValueError(f"key input must be a non-empty bare identifier: {value!r}")
    return value


def _pk(kind: str, value: str) -> str:
    return f"{kind}#{_bare(value)}"


def tutorial_pk(slug: str) -> str:
    return _pk("TUTORIAL", slug)


def version_pk(version_id: str) -> str:
    return _pk("VERSION", version_id)


def feature_pk(feature_id: str) -> str:
    return _pk("FEATURE", feature_id)


def ticket_pk(ticket_id: str) -> str:
    return _pk("TICKET", ticket_id)


def release_pk(release_id: str) -> str:
    return _pk("RELEASE", release_id)


def feedback_pk(feedback_id: str) -> str:
    return _pk("FEEDBACK", feedback_id)


def rule_pk(rule_id: str) -> str:
    return _pk("RULE", rule_id)


def proc_pk(signature: str) -> str:
    return _pk("PROC", signature)


def step_pk(version_id: str, number: int) -> str:
    if isinstance(number, bool) or not isinstance(number, int) or number < 1:
        raise ValueError(f"step number must be a positive int: {number!r}")
    return f"STEP#{_bare(version_id)}#{number}"


def view_pk(tutorial_version: str, user: str, ts: datetime) -> str:
    canonical = json.dumps(
        [_bare(tutorial_version), _bare(user), to_iso(ts)],
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"VIEW#{sha256(canonical).hexdigest()}"


def parse_pk(value: str) -> tuple[str, str]:
    kind, separator, identifier = value.partition("#")
    if not separator or not kind or not identifier:
        raise ValueError(f"invalid physical primary key: {value!r}")
    return kind, identifier


def edge_sk(relation: str, target_pk: str) -> str:
    if relation not in RELATIONS:
        raise ValueError(f"unsupported edge relation: {relation!r}")
    parse_pk(target_pk)
    return f"{relation}#{target_pk}"


def parse_edge_sk(value: str) -> tuple[str, str]:
    relation, separator, target = value.partition("#")
    if not separator or relation not in RELATIONS:
        raise ValueError(f"invalid edge sort key: {value!r}")
    parse_pk(target)
    return relation, target


def parse_step_pk(value: str) -> tuple[str, int]:
    kind, identifier = parse_pk(value)
    version_id, separator, number = identifier.rpartition("#")
    if (
        kind != "STEP"
        or not separator
        or not version_id
        or not number.isdecimal()
        or str(int(number)) != number
    ):
        raise ValueError(f"invalid step primary key: {value!r}")
    return version_id, int(number)
```

`parse_step_pk` 用 `rpartition`（從**右邊**切第一個 `#`）而不是 `partition`：版本 ID 本身長得像 `prepare-meeting@v2`，未來若含 `#` 也不會把步驟號切錯邊。

**四道守門缺一不可**（controller 裁決：review 發現本計畫原本給的 `if kind != "STEP" or not separator or not number.isdigit():` 過度寬鬆，已在此改成修正後的版本）。判準是 round-trip 必須封閉，也就是 `step_pk(*parse_step_pk(pk)) == pk` 對任何能通過的字串都成立：

| 畸形輸入 | 原本的條件 | 修正後 | 為什麼要擋 |
|---|---|---|---|
| `STEP##3` | 回 `("", 3)` | `ValueError` | 版本 ID 空字串，`step_pk` 根本產不出這把鍵（`_bare` 會先拒絕）。 |
| `STEP#slug#03` | 回 `("slug", 3)` | `ValueError` | 前導零：組回去是 `STEP#slug#3`，不是原字串，等於同一步有兩把鍵。 |
| `STEP#slug#３` | 回 `("slug", 3)` | `ValueError` | 全形數字：`str.isdigit()` 與 `int()` 都會放行，組回去卻不是原字串。 |
| `STEP#slug#³` | 丟 `int()` 的 `invalid literal for int()` | `ValueError: invalid step primary key: …` | 上標數字：`isdigit()` 為真但 `isdecimal()` 為假；先用 `isdecimal()` 擋掉，錯誤訊息才會是契約訊息而不是 `int()` 的內部訊息。 |
| `STEP#slug#` | `ValueError`（`""` 非數字） | `ValueError` | 原本就會擋，修正後仍擋。 |

`isdecimal()` 只解決 `³`；`３` 與 `03` 要靠 `str(int(number)) == number` 這道「正規形」檢查。兩者的順序不能對調：`or` 由左至右短路，`isdecimal()` 必須排在 `int()` 前面，否則 `³` 會先讓 `int()` 丟出非契約訊息。

三件事要看懂：`_bare` 是「不准重複加前綴」的唯一守門員，八個單值 builder 經由 `_pk` 呼叫它，`step_pk`、`view_pk` 直接呼叫它，十個入口都擋得住重複前綴；`RELATIONS` 就是設計 §9.2 的五種關係，多一種都不行，所以 `HAS_VERSION`、`VIEWED`、`SUCCESSOR` 在這裡就被擋掉；`view_pk` 先用 `to_iso` 把時間轉成 UTC `Z` 字串再雜湊，所以同一個三元組在任何機器上都得到同一把鍵。

- [x] **Step 4：執行正反向鍵空間測試**

```bash
uv run pytest tests/unit/test_keys.py -q
uv run ruff check src/training_kb/keys.py tests/unit/test_keys.py
uv run mypy src/training_kb/keys.py
```

預期：全部 PASS。十種 builder 都有合法、空值與已加前綴案例；同一 View 三元組完全一致，`user` 或 `ts` 改變時 digest 不同；五種以外的關係與 `step_pk(..., 0)`、`step_pk(..., True)` 都被拒。此時 `META` 還沒宣告，`tests/unit/test_keys.py` 不得 import 它。

- [x] **Step 5：提交獨立的鍵函式**

```bash
git add src/training_kb/keys.py tests/unit/test_keys.py
git commit -m "feat(data): 增加單表鍵與關係邊"
```

## Task 2：讓 `META` 常數與 O1 決策紀錄一字不差

**Files:** `docs/decisions/O1-metadata-sort-key.md`、`src/training_kb/keys.py`、`tests/unit/test_keys.py`。

**Interfaces:** Consumes `META` 候選值；Produces 可稽核的 O1 決策狀態與唯一 metadata SK 常數。

這個 Task 刻意**不**寫 `assert META == "META"`。直接把建議值抄進測試，等於用計畫文字宣稱 O1 已核定；設計 §18 說 `META` 只是建議值。測試改成「常數必須等於決策紀錄裡寫下的最終值」，紀錄沒寫完就紅燈——gate 由真實紀錄關閉，不由測試關閉。

- [x] **Step 1：建立失敗測試**

```python
import re
from pathlib import Path

from training_kb.keys import META

DECISION = Path(__file__).resolve().parents[2] / "docs/decisions/O1-metadata-sort-key.md"


def test_metadata_sort_key_matches_the_recorded_o1_decision() -> None:
    text = DECISION.read_text(encoding="utf-8")
    status = re.search(r"^Status: (accepted|rejected)$", text, re.M)
    approver = re.search(r"^Approver: \S.*$", text, re.M)
    decided_on = re.search(r"^Date: \d{4}-\d{2}-\d{2}$", text, re.M)
    sort_key = re.search(r"^Sort-Key: (\S+)$", text, re.M)
    assert status is not None, "O1 尚未核定：Status 必須是 accepted 或 rejected"
    assert approver is not None, "O1 決策紀錄缺核定者"
    assert decided_on is not None, "O1 決策紀錄缺決策日期"
    assert sort_key is not None, "O1 決策紀錄缺最終 metadata sort key"
    assert META == sort_key.group(1)
```

- [x] **Step 2：執行並確認紅燈**

```bash
uv run pytest tests/unit/test_keys.py::test_metadata_sort_key_matches_the_recorded_o1_decision -q
```

預期：FAIL。第一次執行時訊號是 `cannot import name 'META' from 'training_kb.keys'`；補上常數後會換成 `FileNotFoundError`（紀錄還沒建立）或 `AssertionError: O1 尚未核定...`。三種訊號都是正確的紅燈，代表 gate 還開著。

- [x] **Step 3：建立最小實作（決策紀錄 + 常數）**

`docs/decisions/O1-metadata-sort-key.md` 用固定欄位開頭，讓測試與 `rg` 都能核對：

四個欄位**各自獨佔一行、行尾不得有註解**：Step 1 的正則是行尾錨定的
`^Status: (accepted|rejected)$`、`^Date: \d{4}-\d{2}-\d{2}$`、`^Sort-Key: (\S+)$`，
在同一行加說明就比不到，測試會停在「O1 尚未核定」。各欄位的規則是：`Status` 只能是
`accepted` 或 `rejected`（未定案時整個檔案不要建立）；`Date` 是決策當天，UTC；
`Approver` 必須是具體的人，不能寫 team 或 TBD；`Sort-Key` 在 accepted 時就是採用值，
在 rejected 時是經核定的替代字串。

```text
# O1：metadata sort key

Status: accepted
Date: 2026-09-13
Approver: <核定者姓名或代為暫定者，並在說明段落寫清楚是誰、依據什麼授權>
Sort-Key: META

## 決策內容
- 十個邏輯實體的 metadata item 一律用這個 sort key；TUTORIAL_STEP 不在此列，它以
  REFERENCES#<Feature PK> 當 SK（設計 §9.1）。
- 對十實體的影響：逐一列出 PK 形狀與受影響的讀寫路徑。
- rejected 時要寫替代字串與改用理由，並同步更新 keys.py 與測試。
```

```python
META = "META"
```

`META` 的值必須等於紀錄裡的 `Sort-Key`。若紀錄為 rejected，先在同一份紀錄寫出具體替代字串，再同步改常數；不允許用空字串，也不允許各實體各自猜值。

- [x] **Step 4：跑完整檔案確認綠燈並保留 gate 證據**

```bash
uv run pytest tests/unit/test_keys.py -q
rg -n '^(Status|Date|Approver|Sort-Key): ' docs/decisions/O1-metadata-sort-key.md
```

預期：整支測試檔 PASS，`rg` 四個欄位都印得出來。任一欄位缺少、或核定者仍是佔位字串時，本 Phase 的結論寫「O1 尚未核定，`META` 仍是建議值，不得宣稱物理鍵契約已定案。」並標記 `O1 BLOCKED`，[Phase 06](06-Phase06-Repository-Metadata與實體讀寫.md) 停止，不進入任何 metadata 寫入。O1 accepted 也只代表鍵**命名**定案；實表 CRUD 由 Phase 06、Phase 09 另外留證。核定者若是代為暫定（本專案即是：controller 依授權暫定），紀錄與報告一律寫 **provisionally accepted**，不得簡寫成「已核定」。

- [x] **Step 5：提交**

```bash
git add docs/decisions/O1-metadata-sort-key.md src/training_kb/keys.py tests/unit/test_keys.py
git commit -m "docs(data): 記錄 O1 metadata 鍵決策"
```

## 驗收與停止條件

| 路徑 | 輸入 | 預期資料結果 |
|---|---|---|
| Happy | 裸 ID `Prepare` 傳給 `feature_pk` | `FEATURE#Prepare`；`parse_pk` 回 `("FEATURE", "Prepare")` |
| Happy | `edge_sk("REFERENCES", "FEATURE#Prepare")` | `REFERENCES#FEATURE#Prepare`；`parse_edge_sk` 只切第一個 `#` |
| Happy | 同一 View 三元組重送 | 相同 PK，形狀是 `VIEW#` 加 64 個 hex 字元 |
| Failure | 已加前綴的 `FEATURE#Prepare` 傳給 `feature_pk` | `ValueError`，訊息含 `bare identifier`；避免雙重前綴 |
| Failure | `edge_sk("VIEWED", ...)`、`parse_edge_sk("HAS_VERSION#...")` | `ValueError`；五種關係以外一律拒絕 |
| Boundary | `step_pk(..., 0)`、`step_pk(..., True)` | `ValueError`，訊息含 `positive`；`step_pk(..., 1)` 才通過 |
| Happy | `parse_step_pk("STEP#prepare-meeting@v2#3")` | `("prepare-meeting@v2", 3)`；非 STEP 的 PK 一律 `ValueError` |
| Boundary | 同 version、同 user、時間差 1 秒的兩筆 View | 兩把不同的 PK，不會被合併 |
| Gate | O1 紀錄缺 `Status`／`Approver`／`Date`／`Sort-Key` | Task 2 測試 FAIL，標 `O1 BLOCKED`，Phase 06 停止 |

人工驗收（不能只看 PASS）：打開 `keys.py` 對照設計 §9.1 的十列表格與 §9.2 的五列關係表，逐列確認前綴字串一字不差；確認沒有第十一種實體，也沒有 `HAS_VERSION`、`VIEWED`、`SUCCESSOR` 邊。再打開 `docs/decisions/O1-metadata-sort-key.md`，確認核定者是具體的人而不是佔位字串。

## 常見錯誤與邊界案例

| 症狀 | 原因 | 修正／停止 |
|---|---|---|
| `parse_edge_sk` 回的 target 變成 `FEATURE`，`#Prepare` 不見了 | 用 `split("#")` 或切了不只第一個 `#` | 改用 `partition("#")`，終點本身就含 `#`。 |
| 同一次瀏覽在兩台機器算出不同 View PK | 用 `str(ts)`、Python `repr` 或預設 `json.dumps` 空白 | 固定 `to_iso(ts)` 與 `separators=(",", ":")`、`ensure_ascii=False`。 |
| PK 出現 `FEATURE#FEATURE#Prepare` | 呼叫端把已加前綴的字串再傳進 builder | `_bare` 已擋；呼叫端改傳裸 ID，不要在 builder 外面自己拼字串。 |
| 步驟編號 1 出現兩筆 item | `step_pk(version_id, True)` 被當成 `1` | `step_pk` 先擋 `bool` 再檢查正整數。 |
| 有人想把 `OPS#`／`CONFIG#` 加進本 Phase | 誤以為所有前綴都歸 `keys.py` 的 builder | `ops_pk`／`operation_ref` 屬 Phase 10；`CONFIG#`、`SEQ#`、`LEASE#` 由 Phase 10 的 `put_meta_item` 直接組。 |
| 文件寫「O1 已定案」 | 把建議值當結論 | 寫「O1 尚未核定，`META` 仍是建議值，不得宣稱物理鍵契約已定案。」並停止 Phase 06。 |

SHA-256 在本 Phase 只用於確定性去重，不是使用者身分驗證，也不能反推出 `user`。O1 accepted 也不代表 AWS CRUD 已通過；序列化與實表由 Phase 06、Phase 09 各自留證。

## 來源與 Rule 對照

- [設計 §9.1](../../design/training-kb.md#s9)：十實體 PK、`META` 建議值、View digest、裸 ID 與原生型別。
- [設計 §9.2](../../design/training-kb.md#s9)：`PK=起點`、`SK=關係#終點`、`target=終點`；五種關係；沒有 `HAS_VERSION`、`VIEWED`、`SUCCESSOR` 邊。
- [設計 §18 O1](../../design/training-kb.md#s18)：`META` 仍是建議，需要實作前決策。
- [00A 第 3.3、6.2 節](00A-共用契約與名詞.md)：裸 ID 與前綴 PK 的分工、十個 builder 與三個 parser（含 `parse_step_pk`）的 canonical 簽名。
- 本 Phase 在 [00B 需求覆蓋對照](00B-需求覆蓋對照.md) 中**沒有** primary Rule；它提供下列 Rule 的鍵契約，一律標「相關」：
  - [建立教學版本.feature](../../spec/features/建立教學版本.feature) Rule 8：「建立 TutorialStep 時保存 references Feature 邊」→ 相關（primary 在 Phase 23）。
  - [建立教學版本.feature](../../spec/features/建立教學版本.feature) Rule 10：「references 邊的 target 等於 SK 中的關係終點」→ 相關（primary 在 Phase 07）；本 Phase 只保證 `edge_sk`／`parse_edge_sk` 可互為反函式。
  - [查詢知識圖譜.feature](../../spec/features/查詢知識圖譜.feature) Rule 1：「查詢某起點的關係使用該起點的 PK」→ 相關（primary 在 Phase 08）。
  - [查詢知識圖譜.feature](../../spec/features/查詢知識圖譜.feature) Rule 2：「查詢誰引用 Feature 時使用 by_target 的 target」→ 相關（primary 在 Phase 08）。
  - [提出教學規則.feature](../../spec/features/提出教學規則.feature) Rule 6：「MVP 的教學與產品功能識別碼在單一專案範圍內唯一」→ 相關（primary 在 Phase 04）。

## 完成清單

- [x] 八個單值 builder 加 `step_pk`、`view_pk` 共十種 PK 與三個 parser（`parse_pk`、`parse_edge_sk`、`parse_step_pk`）可 round-trip，且 `step_pk(*parse_step_pk(pk)) == pk` 封閉（前導零、全形／上標數字、空版本 ID 一律拒絕）。
- [x] `view_pk` 只消耗 version、stable user 與 UTC ts，同三元組同鍵、差一秒不同鍵。
- [x] metadata SK 與 edge SK 沒有混用；`TutorialStep` 明確走 edge 而非 `META`。
- [x] 五種關係以外一律拒絕，`_bare` 擋掉所有重複加前綴的輸入。
- [x] `docs/decisions/O1-metadata-sort-key.md` 有 `Status`／`Date`／`Approver`／`Sort-Key` 四個欄位，且 `META` 等於 `Sort-Key`；未決時文件明確標 `O1 BLOCKED`，代為暫定時標 `provisionally accepted`。
- [x] 所有 `uv run pytest` 測試都是本機契約，未宣稱 AWS 已驗證。
- [x] Phase 06 可直接消耗 `META` 與全部 key builders，Phase 08 可用 `parse_step_pk` 還原步驟號，Phase 10 可在同一支檔案追加 `ops_pk`／`operation_ref`。

**下一份可用成果：** 一套不重複加前綴、可反向解析的物理鍵，以及明確的 O1 gate 狀態。
