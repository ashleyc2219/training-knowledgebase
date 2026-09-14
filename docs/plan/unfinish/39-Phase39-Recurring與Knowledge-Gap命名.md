# Phase 39：Recurring 與 Knowledge Gap 命名實作計畫

> **給實作者：** 依 checkbox 逐步執行；每個 Task 先建立失敗測試，再寫最小實作。執行時使用 `superpowers:executing-plans` 或同等逐項流程。

**目標：** 用 UTC 日界線判斷同群工單是不是重複問題，並且只有達門檻的群才呼叫一次 Claude 命名 Knowledge Gap。

**架構：** 窗口計算與計數是無外部相依的純函式；`name_gap` 才會碰 `Writer` 與私有 operations 物件。模型只負責「這一群在問什麼」與「對應哪個既有 Feature」；要不要呼叫模型、Feature 是否存在、重試要不要再呼叫，都由程式決定。

**技術：** Python 3.12、Pydantic v2、pytest、Phase 02 `utc_date`／`Thresholds`、Phase 15 `Writer.generate_json`、Phase 17 `GapNaming` schema、Phase 18 `gap_naming_validator`（測試另用 Phase 02 `parse_iso` 造時間）。

## 全域限制

- 唯一主來源是 [Training KB 設計 §7.3、§7.6、§14.1、§14.2](../../design/training-kb.md)。
- 前置為 [Phase 38：Ticket Embedding 與群中心分群](./38-Phase38-Ticket-Embedding與群中心分群.md)。`cluster_id` 未寫回前不能判斷 recurring。
- 下一階段是 [Phase 40：Ticket CREATE 與 KEEP](./40-Phase40-Ticket-CREATE與KEEP.md)。
- 本階段不做：不建立 Feature、不建立 Tutorial、不建立版本、不改 `Ticket.feature_ids`、不決定 CREATE／KEEP；未達 recurring 門檻**不得呼叫任何模型**，找不到對應 Feature 是合法業務結果，要保留 gap 紀錄而不是造一個新 Feature。
- 與本 Phase 有關的 gate：O5 未通過時 Claude 呼叫維持 BLOCKED，只能用 FakeWriter；O2 未通過時，「重試不重呼叫」只有單元測試證據，不得宣稱已通過永久去重驗收。
- 以下程式檔均是實作時預計建立或修改；本計畫本身不代表它們已存在。

---

## 1. 你在整體流程的位置

```text
Phase 38 已寫回 cluster_id 的 Ticket
                |
   [你在這裡] is_recurring：同群、窗口內 >= 5 筆？
                |
        +-------+--------+
        | 否             | 是
        v                v
  不呼叫模型        [你在這裡] name_gap -> Claude 一次
  結束本輪               |
             dict：{"gap": "...", "feature_id": "Prepare" 或 None}
                         |
                         v
             Phase 40 decide_ticket_action
```

## 2. 完成後看得到什麼

`t_881` 的 `ts` 是 `2026-09-13T02:00:00Z`，`cluster_id` 是 `c12`。同群另有四筆，日期分別是 09-09、09-10、09-11、09-12。

```text
recurring_window(date(2026, 9, 13)) -> 14 個日期：2026-08-31 ... 2026-09-13
is_recurring(t_881)                 -> True（含自己共 5 筆落在窗口內）
name_gap("c12")                     -> {"gap": "找不到會前摘要入口", "feature_id": "Prepare"}
writer.generate_json 呼叫次數         -> 1
```

拿掉 09-09 只剩四筆：`is_recurring` 是 `False`，`writer.generate_json` 呼叫次數是 **0**。同一個 `operation_id` 重送：`name_gap` 從私有 S3 讀回上次結果，呼叫次數仍是 **1**。

## 3. 名詞小抄

| 名詞 | 白話意思 |
|---|---|
| recurring | 同一群工單在窗口內累積到門檻筆數，代表這是重複發生的問題。 |
| UTC 日界線 | 以世界標準時間的「日期」分桶；同一天內不管幾點都算同一天。 |
| Knowledge Gap | 這群工單共同缺少的教學內容，用一句話描述。 |
| schema dict | Phase 17 的 `GapNaming` 等八個名稱都是**JSON schema 字典**，不是 pydantic 類別；`generate_json` 吃它、回一個普通 `dict`。 |
| operations 物件 | 私有 S3 的執行紀錄 `operations/<operation_id>/gap-naming.json`；重試時重用。 |
| `Fnn`／`Dnn`／`D-nn` | 前兩種是[設計文件](../../design/training-kb.md) §19 的功能／資料決策編號（如 F11、D04）；`D-nn` 是 [00A](00A-共用契約與名詞.md) §8 的跨 Phase 裁決編號（如 D-02）。 |
| `META` | metadata item 的固定 `SK` 值（Phase 05）；`scan_entity` 也會掃到關係邊，靠 `SK == META` 把邊濾掉。 |

## 4. 預計檔案

| 動作 | 路徑 | 責任 |
|---|---|---|
| 修改 | `src/training_kb/pipelines/ticket.py` | `recurring_window`、`is_recurring`、`known_features`、`name_gap`。 |
| 修改 | `src/training_kb/writing/prompts.py` | `prompt_name_gap`：只含同群文字與 Feature 清單。 |
| 測試 | `tests/unit/pipelines/test_ticket_recurring.py` | 窗口長度、UTC 日界線、四筆／五筆。 |
| 測試 | `tests/unit/pipelines/test_ticket_name_gap.py` | 未達門檻不呼叫、Feature 驗證、重試不重叫。 |

## 5. 固定介面

### Consumes

```text
utc_date(dt: datetime) -> date                                   # Phase 02（測試另用 parse_iso 造時間）
Thresholds.recurring_tickets: int = 5                            # Phase 02，5 的唯一來源
PermanentError / ContentError                                    # Phase 02
META: str                                                        # Phase 05，metadata item 的固定 SK
Ticket(id, source, text, author, ts: datetime, project_id, cluster_id, feature_ids, embedding)   # Phase 04
Feature(feature_id, name, aliases, first_seen)                   # Phase 04
Repository.list_tickets(project_id: str) -> list[Ticket]         # Phase 08
Repository.scan_entity(entity: str, *, consistent: bool = True,
                       meta_only: bool = True) -> list[DynamoItem]   # Phase 08
item_to_model(item: DynamoItem, model: type[T]) -> T             # Phase 08 的模組函式，不是方法
Repository.put_object(key, body, content_type, *, if_none_match) / get_object(key)   # Phase 07
operation_ref(operation_id: str, name: str) -> str                # Phase 10，operations/<id>/<name>.json
OperationCoordinator.record_model_output(operation_id: str, output_ref: str) -> None  # Phase 10
Writer.generate_json(system: str, user: str, schema: Mapping[str, Any], *,
                     operation_id: str, node: str) -> dict[str, Any]                 # Phase 15
GapNaming: dict[str, object]                                     # Phase 17 的 JSON schema 常數
BusinessValidator = Callable[[dict[str, Any]], None]                                 # Phase 18
gap_naming_validator(*, known_feature_ids: frozenset[str]) -> BusinessValidator      # Phase 18
```

### Produces

```python
from collections.abc import Sequence
from datetime import date

RECURRING_DAYS = 14                                      # 沒有對應的 Thresholds 欄位，維持模組常數
RECURRING_MIN_TICKETS = Thresholds().recurring_tickets   # 別名，不另外寫一份 5

def recurring_window(anchor: date, days: int = RECURRING_DAYS) -> frozenset[date]: ...

def is_recurring(ticket: "Ticket", *, repository: "Repository") -> bool: ...

def known_features(repository: "Repository") -> tuple["Feature", ...]: ...

def name_gap(
    cluster_id: str, *, repository: "Repository", writer: "Writer",
    operation_id: str, operations: "OperationCoordinator",
) -> dict[str, object]: ...

def prompt_name_gap(ticket_texts: Sequence[str],
                    allowed_features: Sequence[str]) -> tuple[str, str]: ...
```

`GapNaming` 是 Phase 17 已固定的 **JSON schema 字典**（`gap` 必填、`feature_id` 可為 `null`），不是 pydantic 類別；本 Phase 不重新定義它，只把它傳給 `generate_json` 並對拿回來的 `dict` 加業務驗證。因此 `name_gap` 的回傳型別是 `dict[str, object]`，呼叫端用 `naming["feature_id"]` 取值（00A D-02）。「Feature 存不存在」這條業務檢查只有一份，就是 Phase 18 的 `gap_naming_validator`；本 Phase 的私有 `_validated_naming` 只是包裝它並多加一條「`gap` 非空」，不得自己再寫一遍存在性判斷（Phase 18 §5 明文要求）。`prompt_name_gap` 依 Phase 17 的 `prompt_<node>` 命名加進同一個 `writing/prompts.py`，回 `(system, user)`；工單文字是**不可信資料**，一律經 Phase 17 的 `_as_data`（`html.escape(text, quote=False)`）包進 `<source_data>` 分區當資料、不當指令（00A D-67，Phase 60 的 `check_output_safety` 只認這一個標記）。`known_features` 把 `scan_entity("FEATURE")` 的 item 先濾掉 `SK != META` 的關係邊，再用 `item_to_model` 還原成 `Feature` 並依 `feature_id` 升序，Phase 40 重用同一份清單。

數字只有一份：`5` 來自 Phase 02 的 `Thresholds.recurring_tickets`，模組常數 `RECURRING_MIN_TICKETS` 只是它的別名（00A D-35）；`14` 在 `Thresholds` **沒有**對應欄位，所以 `RECURRING_DAYS = 14` 留在本模組，不得自創 `Thresholds.recurring_days` 這種新欄位名。

## 6. 設計細節

窗口是「日期集合」，不是時間區間。設計 §7.3 與決策 F11（設計 §19.2 功能決策編號，選 C 案）：以 `Ticket.ts` 換算的 UTC **日期**為 anchor，取當日及前 13 個日期。

```text
Ticket.ts = 2026-09-13T02:00:00Z        Ticket.ts = 2026-09-13T23:59:59Z
            |                                       |
            +------------ utc_date() ---------------+
                              |
                      2026-09-13（同一桶）
                              |
   recurring_window -> { 2026-08-31, ..., 2026-09-13 } 共 14 個日期
                              |
   2026-08-30T23:59:59Z 在窗口外；2026-08-31T00:00:00Z 在窗口內
```

`is_recurring` 的固定順序：

```text
  ticket.cluster_id 為空？ -- 是 --> PermanentError（Phase 38 還沒跑完）
            | 否
  anchor = utc_date(ticket.ts)；window = recurring_window(anchor)
            |
  list_tickets -> 只留同 cluster_id -> 依 Ticket.id 去重 -> 只留日期在 window 的
            |
   筆數 >= 5？ -- 是 --> True（含觸發本輪的那一筆）；否 --> False
```

`Ticket.ts` 在 Phase 04 的模型裡**已經是 `datetime`**，所以這裡直接 `utc_date(ticket.ts)`，不要再套一層 `parse_iso`（那是給字串用的，只有測試造資料時才需要）。anchor 固定用「觸發本輪的那筆工單」而不是執行當下的時間，所以同一批輸入什麼時候重跑都一樣；同一天內的多筆各算一筆，日期只用來過濾。`name_gap` 的固定順序與兩道守衛：

```text
  known_features -> validate = gap_naming_validator(known_feature_ids=...)（Phase 18）
            |
  get_object("operations/<op>/gap-naming.json") 讀得到？
            | 是 --> json.loads 後重跑 validate -> 回傳（模型 0 次）
            | 否
  scan_entity("TICKET") 濾 SK == META -> 同群工單總數 >= 5？ -- 否 --> PermanentError，模型 0 次
            | 是
  組 prompt（只放同群文字 + known_features 的 ID）-> generate_json 一次
            |
  gap 去頭尾後非空？ -- 否 --> ContentError
            | 是
  validate：feature_id 是 null？ -- 是 --> 合法結果：保留 gap，不建 Feature
            | 否
  feature_id 在 known_feature_ids 內？ -- 否 --> ContentError（不改寫成 null、不建 Feature）
            | 是
  put_object(if_none_match=True) -> record_model_output -> 回傳
```

去重的判準是**物件本身**而不是 operation 紀錄的 ref 清單：先寫物件、再記 ref，中間如果失敗，紀錄裡沒有 ref 但物件已存在；此時若只看 `operations.load` 就會再呼叫一次模型，而且 `put_object(if_none_match=True)` 還會撞成 `ObjectAlreadyExists`。先讀物件可以同時蓋掉這兩個洞，`record_model_output` 仍照寫，讓 Phase 41 與指標看得到這次輸出。

第二道守衛是「必要條件」檢查：任何 14 天窗口都不可能從不到五筆的群裡湊出五筆，所以群總數不足五一定是呼叫端漏做 `is_recurring`，直接 `PermanentError` 擋掉，不會誤擋已判定 recurring 的群；精確窗口判斷仍只由 `is_recurring` 負責。`name_gap` 只拿得到 `cluster_id`（Phase 41 的 `NameGap` Task 不傳 Ticket 也不傳 `project_id`），所以群成員用 `scan_entity("TICKET")` + `item_to_model` 取得再依 `cluster_id` 過濾；`is_recurring` 手上有 Ticket，就用比較精準的 `list_tickets(ticket.project_id)`。MVP 是單一專案（設計 §19.1 資料決策 D01），兩條路徑的結果一致。

`scan_entity` 是靠 item 的 `entity` 屬性篩選，而關係邊的 `entity` 等於**起點** PK 的前綴（Phase 07 `put_edge`），所以 Phase 40 寫的 `TICKET#<id>` → `ASKS_ABOUT#FEATURE#<id>` 邊與 `TICKET#` 同前綴。[Phase 08](08-Phase08-分頁查詢與一致讀取基礎.md) 的 `scan_entity` **預設 `meta_only=True`**（00A §6.3），已經先幫我們把這些邊濾掉；本 Phase 沿用 [Phase 27](27-Phase27-固定圖譜查詢.md) 的做法再自己濾一次 `str(row["SK"]) == META`，這樣呼叫端哪天改傳 `meta_only=False` 也不會把邊丟進 `item_to_model` 而 `ValidationError`。不改 Phase 08 的簽名。`known_features` 同樣先濾一次：現在 `FEATURE#` 起點沒有邊，但濾掉是零成本的保險。

**本計畫選擇：** 模型回不存在的 `feature_id` 時丟 `ContentError`，不自動改成 `null`。「找不到有效 Feature」（模型回 `null`）是設計 §14.1 明列的業務結果；「捏造一個 ID」是設計 §7.6 要求程式攔下的違規輸出，兩者不可混為一談。「最多修正一次」的迴圈屬於 Phase 18 的 `writing/client.py`，用的就是本 Phase 建好的同一個 `gap_naming_validator`；本 Phase 自己**不重試、不第二次呼叫模型**，拿到的 dict 仍不合法就丟 `ContentError` 永久失敗。

## 7. TDD Tasks

### Task 1：固定 UTC 日界線窗口

- [x] **Step 1：建立失敗測試**

```python
def test_window_has_exactly_fourteen_dates():
    window = recurring_window(date(2026, 9, 13))
    assert len(window) == 14
    assert date(2026, 9, 13) in window        # 當日
    assert date(2026, 8, 31) in window        # 前第 13 個日期
    assert date(2026, 8, 30) not in window


def test_utc_day_boundary_is_the_cut_line():
    window = recurring_window(date(2026, 9, 13))
    assert utc_date(parse_iso("2026-08-31T00:00:00Z")) in window
    assert utc_date(parse_iso("2026-08-30T23:59:59Z")) not in window
    assert utc_date(parse_iso("2026-09-13T23:59:59Z")) in window
```

- [x] **Step 2：執行 `uv run pytest tests/unit/pipelines/test_ticket_recurring.py -q` 確認紅燈**

預期 FAIL，訊號包含 `cannot import name 'recurring_window'`。

- [x] **Step 3：建立最小實作**

```python
def recurring_window(anchor, days=RECURRING_DAYS):
    if days < 1:
        raise PermanentError(f"recurring 窗口天數至少為 1，收到 {days}")
    return frozenset(anchor - timedelta(days=offset) for offset in range(days))
```

- [x] **Step 4：補邊界測試後跑綠並提交**

再加兩個案例：`days=0` 與 `days=-1` 都丟 `PermanentError`；同一 UTC 日的 `00:00:01Z` 與 `23:59:58Z` 換算後相等。執行 `uv run pytest tests/unit/pipelines/test_ticket_recurring.py -q` 後，用 `git add src/training_kb/pipelines/ticket.py tests/unit/pipelines/test_ticket_recurring.py` 加入新檔再 `git commit -m "feat(ticket): 固定 recurring 日期窗口"`。

### Task 2：四筆不算 recurring、五筆才算

- [x] **Step 1：建立失敗測試**

`fake_repo` 是測試檔自備的假 `Repository`：底層一個 list 當表、一個 dict 當私有 S3，提供 `scan_entity`／`get_object`／`put_object`／`put_meta`（建 Feature 才會記進 `created_features`）與種子鉤子 `save_ticket`／`save_feature`／`save_edge`。**不需要 `list_tickets`**：`name_gap` 只走 `scan_entity("TICKET")`（`is_recurring` 才用 `list_tickets`，那是 Task 2 的事，沿用 conftest 的 `fake_repo` 就夠），`scan_entity` 必須連手寫進去的關係邊一起回傳——刻意模擬 `meta_only=False` 的情況，才驗得到本 Phase 自己那層 `SK == META` 過濾（真實 `Repository` 的預設 `meta_only=True` 已先擋掉一次）。`saved_ticket(repo, id, *, cluster, ts)` 寫一筆 `Ticket` 並回傳它（`ts` 用 Phase 02 `parse_iso` 轉成 datetime）；`seed_cluster(repo, cluster_id, *, count)` 一次寫 `count` 筆同群工單；`fake_writer` **直接用 `tests/unit/conftest.py` 既有的 `RecordingWriter`**（它已經把每次 `generate_json` 的 `(system, user, schema, node)` 記進 `calls`，回應排在 `replies` 佇列裡），不另外寫一個只有單一 `reply` 的替身——排一個回應本身就代表「模型只該被呼叫一次」，第二次呼叫會因為佇列空掉而失敗，去重斷言因此更強；`fake_ops` 記下 `record_model_output` 並用 `model_output_refs(op)` 讀回。

```python
THREE = ["09-10", "09-11", "09-12"]
FOUR = ["09-09", *THREE]


@pytest.mark.parametrize(("others", "expected"), [(THREE, False), (FOUR, True)])
def test_is_recurring_needs_five_tickets_in_window(fake_repo, others, expected):
    target = saved_ticket(fake_repo, "t_881", cluster="c12", ts="2026-09-13T02:00:00Z")
    for index, day in enumerate(others):
        saved_ticket(fake_repo, f"t_90{index}", cluster="c12", ts=f"2026-{day}T09:00:00Z")
    assert is_recurring(target, repository=fake_repo) is expected


def test_out_of_window_and_other_cluster_do_not_count(fake_repo):
    target = saved_ticket(fake_repo, "t_881", cluster="c12", ts="2026-09-13T02:00:00Z")
    saved_ticket(fake_repo, "t_901", cluster="c12", ts="2026-08-30T23:59:59Z")   # 窗口外
    saved_ticket(fake_repo, "t_902", cluster="c99", ts="2026-09-12T09:00:00Z")   # 別群
    for index, day in enumerate(THREE):
        saved_ticket(fake_repo, f"t_91{index}", cluster="c12", ts=f"2026-{day}T09:00:00Z")
    assert is_recurring(target, repository=fake_repo) is False
```

- [x] **Step 2：執行 `uv run pytest tests/unit/pipelines/test_ticket_recurring.py -q` 確認紅燈**

預期 FAIL，訊號包含 `cannot import name 'is_recurring'`。

- [x] **Step 3：建立最小實作**

```python
def is_recurring(ticket, *, repository):
    if not ticket.cluster_id:
        raise PermanentError(f"工單 {ticket.id} 尚未分群，不能判斷 recurring")
    window = recurring_window(utc_date(ticket.ts))          # Ticket.ts 已經是 datetime
    seen = {
        other.id
        for other in repository.list_tickets(ticket.project_id)
        if other.cluster_id == ticket.cluster_id and utc_date(other.ts) in window
    }
    seen.add(ticket.id)   # anchor 自己的日期一定在窗口內，即使還沒讀回也算一筆
    return len(seen) >= RECURRING_MIN_TICKETS
```

- [x] **Step 4：補同日多筆與去重測試後跑綠並提交**

同一天內的兩筆各算一筆；同一個 `Ticket.id` 出現兩次只算一筆；未分群的 Ticket 丟 `PermanentError`。執行 `uv run pytest tests/unit/pipelines/test_ticket_recurring.py -q` 後 `git add src/training_kb/pipelines/ticket.py tests/unit/pipelines/test_ticket_recurring.py` 並 `git commit -m "feat(ticket): 判斷同群 recurring"`。

### Task 3：只有 recurring 才命名 gap，且重試不重呼叫

- [x] **Step 1：建立失敗測試**

```python
KW = {"operation_id": "op-1"}


def test_name_gap_refuses_cluster_below_threshold(fake_repo, fake_writer, fake_ops):
    seed_cluster(fake_repo, "c12", count=4)
    with pytest.raises(PermanentError, match="recurring"):
        name_gap("c12", repository=fake_repo, writer=fake_writer, operations=fake_ops, **KW)
    assert fake_writer.calls == []


def test_name_gap_reuses_saved_output_on_retry(fake_repo, fake_writer, fake_ops):
    seed_cluster(fake_repo, "c12", count=5)
    fake_repo.save_feature("Prepare")
    fake_writer.replies.append({"gap": "找不到會前摘要入口", "feature_id": "Prepare"})
    kw = {"repository": fake_repo, "writer": fake_writer, "operations": fake_ops, **KW}
    first, second = name_gap("c12", **kw), name_gap("c12", **kw)
    assert first["feature_id"] == second["feature_id"] == "Prepare"
    assert len(fake_writer.calls) == 1
    assert fake_ops.model_output_refs("op-1") == ("operations/op-1/gap-naming.json",)


def test_name_gap_rejects_unknown_feature(fake_repo, fake_writer, fake_ops):
    seed_cluster(fake_repo, "c12", count=5)
    fake_writer.replies.append({"gap": "找不到會前摘要入口", "feature_id": "NotThere"})
    with pytest.raises(ContentError):
        name_gap("c12", repository=fake_repo, writer=fake_writer, operations=fake_ops, **KW)
    assert fake_repo.created_features == []   # 不存在就拒絕，絕不補建 Feature
```

- [x] **Step 2：執行 `uv run pytest tests/unit/pipelines/test_ticket_name_gap.py -q` 確認紅燈**

預期 FAIL，訊號包含 `cannot import name 'name_gap'`。

- [x] **Step 3：建立最小實作**

```python
def _meta_rows(repository, entity):
    return [row for row in repository.scan_entity(entity) if str(row["SK"]) == META]


def known_features(repository):
    features = (item_to_model(row, Feature) for row in _meta_rows(repository, "FEATURE"))
    return tuple(sorted(features, key=lambda feature: feature.feature_id))


def _validated_naming(payload, validate):
    if not str(payload["gap"]).strip():
        raise ContentError("gap_empty: gap")
    validate(payload)              # Phase 18 的 gap_naming_validator，不另寫存在性判斷
    return payload


def name_gap(cluster_id, *, repository, writer, operation_id, operations):
    ref = operation_ref(operation_id, "gap-naming")       # operations/<op>/gap-naming.json
    features = known_features(repository)
    validate = gap_naming_validator(
        known_feature_ids=frozenset(one.feature_id for one in features))
    saved = repository.get_object(ref)
    if saved is not None:                                  # 重送：物件本身就是證據，模型 0 次
        naming = _validated_naming(json.loads(saved), validate)
        operations.record_model_output(operation_id, ref)  # §6 說的「ref 照補」就在這裡
        return naming
    tickets = sorted((item_to_model(row, Ticket) for row in _meta_rows(repository, "TICKET")),
                     key=lambda ticket: ticket.id)         # prompt 不隨掃描順序漂移
    texts = [one.text for one in tickets if one.cluster_id == cluster_id]
    if len(texts) < RECURRING_MIN_TICKETS:
        raise PermanentError(f"群 {cluster_id} 未達 recurring 門檻，不呼叫模型")
    system, user = prompt_name_gap(texts, [one.feature_id for one in features])
    reply = writer.generate_json(system, user, GapNaming, operation_id=operation_id, node="name_gap")
    naming = _validated_naming(reply, validate)
    body = json.dumps(naming, ensure_ascii=False, sort_keys=True).encode("utf-8")
    repository.put_object(ref, body, "application/json", if_none_match=True)
    operations.record_model_output(operation_id, ref)
    return naming
```

`_validated_naming` 收一個 `dict`、回同一個 `dict`，只做兩件事：`payload["gap"]` 去頭尾後必須非空，然後把 `payload` 交給 Phase 18 的 `gap_naming_validator`（`feature_id` 是 `None` 或在 `known_feature_ids` 內，否則 `ContentError("feature_id_not_found: feature_id")`）。schema 形狀已由 Phase 17／18 擋過；「Feature 存不存在」這條規則全系統只有 Phase 18 那一份，本 Phase 不得改用 `get_feature` 再判一次。`operation_ref` 是 Phase 10 的 key 組字函式，不要在這裡自己拼字串。

- [x] **Step 4：補 prompt 隔離與 null feature 測試後跑綠並提交**

`feature_id` 為 `null` 是合法結果，不丟例外也不建 Feature；傳給 FakeWriter 的 user prompt 只含 `c12` 的工單文字，不得出現 `c99` 的文字，`allowed_features` 只有裸 ID（`Prepare`）；`node == "name_gap"`。再補兩個案例：一是「物件已存在但 operation 紀錄還沒記 ref」——先手動寫好 `gap-naming.json` 再呼叫，模型仍是 0 次且不丟 `ObjectAlreadyExists`；二是「表裡有一筆 `TICKET#t_881` 的 `ASKS_ABOUT#FEATURE#Prepare` 邊 item」——`name_gap` 必須照常回傳，不得因為邊沒有 `Ticket` 欄位而 `ValidationError`。執行 `uv run pytest tests/unit/pipelines/test_ticket_name_gap.py -q` 後 `git add src/training_kb/pipelines/ticket.py src/training_kb/writing/prompts.py tests/unit/pipelines/test_ticket_name_gap.py` 並 `git commit -m "feat(ticket): 命名教學缺口"`。

## 8. 驗收矩陣

| 路徑 | 輸入 | 預期資料結果 |
|---|---|---|
| Happy | 同群五筆落在窗口內 | `is_recurring` 為 `True`；`name_gap` 呼叫模型一次。 |
| Failure | 同群只有四筆 | `is_recurring` 為 `False`；`name_gap` 丟 `PermanentError`，模型 0 次。 |
| Failure | 模型回不存在的 `feature_id` | `ContentError`；沒有任何 FEATURE 被建立。 |
| Boundary | `2026-08-31T00:00:00Z` 對 `2026-08-30T23:59:59Z` | 前者在窗口內，後者在窗口外。 |
| Boundary | 模型回 `feature_id=null` | 合法結果，保留 gap，不建 Feature、不丟例外。 |
| Idempotency | 同 `operation_id` 重送 | 讀回 `gap-naming.json`；模型呼叫數維持 1，prompt 不含他群資料。 |
| Idempotency | 物件已寫、`model_output_refs` 還沒記到 | 仍讀回舊物件；模型 0 次，不丟 `ObjectAlreadyExists`。 |
| Boundary | 表裡同時有 `TICKET#` 的 `ASKS_ABOUT` 邊 item | 邊被 `SK == META` 濾掉；筆數與 prompt 內容不受影響。 |

人工驗收：打開 `operations/<operation_id>/gap-naming.json`，確認內容就是本次採用的 `gap` 與 `feature_id`；再看 `CallTrace`，同一個 operation 只能有一筆 `node=name_gap` 的 attempt。只看 pytest PASS 不算完成。

## 9. 常見錯誤與停止條件

| 症狀 | 原因 | 修正／停止 |
|---|---|---|
| 未達門檻仍有 Bedrock 呼叫 | 先呼叫模型再檢查筆數 | 守衛放在呼叫之前；測試斷言 `writer.calls == []`。 |
| 窗口用 `now - 14 days` 算 | 把日期集合誤解成時間區間 | 改用 `utc_date` 分桶；窗口是 14 個日期。 |
| 模型給的 Feature 不存在卻照用 | 只驗 schema 沒驗業務 | 用 Phase 18 的 `gap_naming_validator` 丟 `ContentError`；停止進入 Phase 40。 |
| `item_to_model` 對某筆 item 丟 `ValidationError` | `scan_entity` 連 `ASKS_ABOUT` 等關係邊一起掃到 | 先濾 `str(row["SK"]) == META` 再轉模型（Phase 27 同做法）。 |
| 重送又呼叫一次模型 | 先看 operation 紀錄的 ref 而不是物件 | 先 `get_object(ref)`；有物件就直接回，`record_model_output` 照補。 |
| `GapNaming.model_validate(...)` 找不到方法 | 把 schema dict 當成 pydantic 類別 | `GapNaming` 是 JSON schema 字典；`generate_json` 回的是 `dict`，用 `naming["gap"]` 取值。 |
| `parse_iso(ticket.ts)` 丟型別錯 | `Ticket.ts` 已經是 `datetime` | 直接 `utc_date(ticket.ts)`；`parse_iso` 只用在測試造字串。 |

## 10. 來源與 Rule 對照

- [分析工單.feature](../../spec/features/分析工單.feature)
  - Rule 3「同群在 14 天內至少有 5 筆 Ticket 才算 recurring」→ Task 2 的四筆／五筆參數化測試與窗口外案例直接斷言。
  - Rule 4「只有達 recurring 門檻的群才交給模型命名 Knowledge Gap」→ Task 3 的 `test_name_gap_refuses_cluster_below_threshold` 直接斷言 `writer.calls == []`。
  - Rule 5「Knowledge Gap 的命名結果包含對應 Feature」→ Task 3 的 Feature 存在性驗證與 `null` 合法案例直接斷言。
  - Rule 6「一張 Ticket 對應零或一個 Feature」→ **相關（primary 在 Phase 04）**；本 Phase 只保證 `feature_id` 最多一個且不寫回 Ticket，寫回由 Phase 40 負責。
- 設計 §7.3：依 `Ticket.ts` 的 UTC 日期取當日及前十三個日期；同群至少五筆才交模型命名；無有效 Feature 時保留 gap 診斷紀錄，不建立 Feature 或 Tutorial。§7.6：命名 gap 的程式驗證是「Feature 存在、Ticket 最多一個 Feature」。§14.1：找不到有效 Feature 是業務結果，不是模型服務故障。§14.2：已保存的模型輸出在重試時重用。
- 決策（設計 §19）F11（UTC 當日加前 13 個日期）、F13（保留待釐清的 gap）、D04（一張 Ticket 零或一個 Feature）。
- [00A 共用契約與名詞](00A-共用契約與名詞.md)：D-02（`generate_json` 吃 schema dict、回 dict）、D-29（raw item 一律用 `item_to_model`）、D-35（`Thresholds` 欄位名以 Phase 02 為準）；Phase 18 §5「消費 Phase 的 private helper 應包裝 `gap_naming_validator`」。

## 11. 完成清單

- [x] 五個產出名稱（`recurring_window`、`is_recurring`、`known_features`、`name_gap`、`prompt_name_gap`）的簽名與本文件一致，且任何路徑都沒有建立 Feature 或 Tutorial。
- [x] `name_gap` 回的是 `dict`，全檔沒有 `GapNaming.model_validate`／`model_dump_json` 這類把 schema 當模型用的寫法。
- [x] 窗口恰為 14 個 UTC 日期，端點兩側都有獨立斷言；四筆與五筆兩案例都有直接斷言，四筆時模型呼叫數為 0。
- [x] 不存在的 `feature_id` 被拒絕、`null` 是合法結果，且這條檢查是包裝 Phase 18 的 `gap_naming_validator`，沒有第二份存在性判斷。
- [x] `scan_entity` 的結果一律先濾 `SK == META` 再 `item_to_model`；表裡有關係邊時 `name_gap`／`known_features` 仍正常。
- [x] 同 `operation_id` 重送時重用 `gap-naming.json`，模型呼叫數不增加；`5` 只有 `Thresholds.recurring_tickets` 一份。
- [x] 未把 FakeWriter 綠燈描述成 Claude 或 AWS 已通過；O5 未過維持 BLOCKED。

## 12. 實作裁決紀錄（2026-09-14 實作時補）

| 疑點 | 來源衝突 | 採用 | 理由 |
|---|---|---|---|
| `name_gap` 要不要走 `generate_validated_json`？ | [00A](00A-共用契約與名詞.md) §6.5 的通用列寫「P39–P51 呼叫端一律只呼叫 `generate_validated_json` 一次」，但 00A §6.9 的 **P39 專屬列**寫「`generate_json` 在整個節點只呼叫一次」，本文件 §6／§8 也明文要求不存在的 `feature_id` 丟 `ContentError`、本 Phase 不做第二次呼叫。 | 直接 `writer.generate_json(...)` 一次，再用 `_validated_naming`（包裝 Phase 18 的 `gap_naming_validator`）丟 `ContentError`。 | Phase 專屬契約優先於通用列；`generate_validated_json` 會多送一次修正請求並把失敗改成 `PermanentError`，與本文件 §8 驗收矩陣的 `ContentError` 直接衝突。**副作用：`GapNaming` 實際上不走 correction**，與 `writing/validators.py` 模組註解的表格（`GapNaming` → correction「是」）不一致，留給主導者裁決。 |
| 重送路徑要不要 `record_model_output`？ | §6 流程圖與 §9 表格說「`record_model_output` 照補」，但 Task 3 Step 3 的最小實作片段直接 `return`。 | 重送路徑也補記 ref（已同步修正 Step 3 片段）。 | 「物件已寫、ref 還沒記」正是要修掉的那個洞；不補記的話重送永遠留著缺 ref 的操作紀錄。 |
| `name_gap` 的群成員順序 | 文件沒規定。 | 依 `Ticket.id` 升序後才組 prompt。 | `scan_entity` 是 Scan，順序不保證；排序讓同一批輸入的 prompt 可重現（與 `known_features` 依 `feature_id` 升序同理）。 |
| 測試替身 | Task 3 Step 1 原本描述一個自帶 `self.reply` 的 writer 替身。 | 改用 `tests/unit/conftest.py` 既有的 `RecordingWriter`（`replies` 佇列 ＋ `calls`）。 | 不另造第二個 writer 替身；佇列只排一個回應，第二次呼叫會失敗，「只呼叫一次」的斷言更強。 |
| `fake_repo` 兩種形狀 | 本文件把 `fake_repo` 描述成單一替身。 | `test_ticket_recurring.py` 沿用 `tests/unit/pipelines/conftest.py`（P38 明列給 P39 用）的 `fake_repo`；`test_ticket_name_gap.py` 在**模組層級**定義同名 fixture 刻意遮蔽它。 | 兩個 Task 需要的方法完全不同（`list_tickets` vs `scan_entity`／S3）；00A §3.2 只准 P39 動兩個測試檔，不能改 P38 的 conftest。模組層級 fixture 的遮蔽範圍只有該檔。 |
