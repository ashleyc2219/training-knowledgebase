# Phase 42：Feedback 與 View 固定匯入實作計畫

> **給實作者：** 依 checkbox 逐步執行；每個 Task 先建立失敗測試，再寫最小實作。執行時使用 `superpowers:executing-plans` 或同等逐項流程。

**目標：** 讓維護者上傳的回饋與瀏覽紀錄走一條只有程式判斷的固定路徑：驗證欄位、確認版本、永久去重、寫入 DynamoDB，全程不呼叫模型也不啟動流程。

**架構：** `ingress` 先做純欄位檢查（`validate_feedback`／`validate_view`），再由 `import_feedback`／`import_view` 查 `Repository` 的版本與教學狀態、向 `OperationCoordinator` 取得永久去重結果，最後寫 metadata 與 `REFERS_TO` 邊。Rote、Step Functions 與 PROC 完全不參與這條路徑。

**技術：** Python 3.12、Pydantic v2、pytest、moto、既有 `Repository`、`OperationCoordinator` 與 `keys.view_pk`。

## 全域限制

- 唯一主來源是 [Training KB 設計 §5、§7.1、§8.4、§9.1、§9.2、§14.1、§14.2、§16 S4](../../design/training-kb.md)。
- 前置為 [Phase 41：Ticket Analysis 雲端流程驗收](./41-Phase41-Ticket-Analysis雲端流程驗收.md)；資料面另需 [Phase 08：分頁查詢與一致讀取基礎](./08-Phase08-分頁查詢與一致讀取基礎.md) 與 [Phase 11：O2 接受順序與重啟整合驗證](./11-Phase11-O2接受順序與重啟整合驗證.md)；判斷與接線另需 [Phase 26：教學退役與後繼導向](./26-Phase26-教學退役與後繼導向.md)（`assert_accepts_feedback`）、[Phase 30：GitHub Webhook 原始 Body 驗簽](./30-Phase30-GitHub-Webhook原始Body驗簽.md)（`handlers/` 套件與 `normalize_then_accept`）與 [Phase 32：事件接受去重與流程啟動](./32-Phase32-事件接受去重與流程啟動.md)（`operation_id_for`）。前置未通過時停止。
- 下一階段是 [Phase 43：Feedback 類別判定](./43-Phase43-Feedback類別判定.md)。
- 本階段不做：**Feedback／View 這條路徑**不呼叫任何模型、不收斂 `category` 也不分類留言（全部屬 Phase 43）、不啟動 Step Functions、不更新 PROC、不建立或修改教學版本、不計算任何指標。匯入 handler 的 `ticket`／`release` 分支只是把事件原樣交給 [Phase 32](./32-Phase32-事件接受去重與流程啟動.md)／[Phase 37](./37-Phase37-Rote-Agent回退與成功提交.md) 已經寫好的 `normalize_then_accept`，本 Phase 不重寫那條路徑，也不改它的行為。
- 與本 Phase 有關的 O1–O7 gate 狀態：O2 未取得真實整合證據前，「同 ID 重送不重複」只能宣稱單元與 moto 測試通過；O6 未核定前不得宣稱 `user` 已能跨來源對上 `Ticket.author`。本階段不碰 O3，因為它不公開任何內容。
- 以下程式檔均是實作時預計建立或修改；本計畫本身不代表它們已存在。

---

## 1. 你在整體流程的位置

```text
維護者本機 AWS 登入 -> widget 回饋檔 / 瀏覽紀錄匯出檔 -> handlers/import_.py::handler
        |
[你在這裡] validate_* -> 版本與退役檢查 -> OperationCoordinator.accept
        |  accepted  -> put_meta（+ Feedback 的 REFERS_TO 邊）-> saved
        |  duplicate -> 回既有結果，不增加樣本；物件不存在則續跑補寫
        +--X--> Rote / PROC / Step Functions（feedback／view 完全不接）
        v
  Phase 43 類別判定 -> Phase 44 弱教學門檻 -> Phase 53/54 指標
```

回饋與瀏覽是**資料輸入**，不是觸發器；設計 §7.1 明講 Feedback 只保存、不啟動 Step Functions、不更新 PROC。

## 2. 完成後看得到什麼

輸入 `{"id": "f_12", "tutorial_version": "prepare-meeting@v1", "rating": 2, "category": "找不到按鈕", "comment": "第三步沒有指出按鈕在哪一頁與位置", "user": "u_01"}`：

```text
ImportResult(status="saved", object_id="f_12", message="已保存 f_12；來源未提供 ts，改記匯入時間
  2026-09-14T03:00:00Z，非使用者實際提交時間") + FEEDBACK#f_12 metadata
  | FEEDBACK#f_12 -> REFERS_TO#VERSION#prepare-meeting@v1 邊
```

同一個 `f_12` 再送一次回 `duplicate`，樣本數不變；`rating` 換成 `true`、`"4"` 或 `0` 回 `rejected`、`invalid_fields=("rating",)`，圖譜零變動。瀏覽紀錄 `{"tutorial_version": "prepare-meeting@v1", "user": "u_01", "ts": "2026-08-02T09:00:00Z"}` 寫成 PK 為 `VIEW#<64 個 hex>` 的 item，同三元組重送同樣回 `duplicate`。

## 3. 名詞小抄

| 名詞 | 白話意思 |
|---|---|
| 固定匯入 | 只有程式判斷的接入路徑；沒有 adapter 選擇，也沒有模型。入口是 Lambda `training-kb-import` 的 `handler`。 |
| 穩定使用者 ID | 像 `u_01` 這種上游已給定的識別碼；`Ticket.author`、`Feedback.user`、`TutorialView.user` 共用同一個。 |
| 永久去重 | 用 `OPS#<operation_id>` 條件寫入記住「這件事做過了」；不靠 TTL、不靠記憶體。 |
| `view_pk` | 把 `[版本, 使用者, 時間]` 編成固定 JSON 再取 SHA-256 當主鍵；只去重，不是使用者身分。 |
| 續跑 | 操作紀錄已接受、但物件還沒寫完；重送要補完，不是回報重複。 |

## 4. 預計檔案

| 動作 | 路徑 | 責任 |
|---|---|---|
| 修改 | `src/training_kb/ingress.py` | `FEEDBACK_FIELDS`、`VIEW_FIELDS`、`ImportResult`、`validate_feedback`／`validate_view`、`import_feedback`／`import_view`；`operation_id_for` 與 [Phase 32](./32-Phase32-事件接受去重與流程啟動.md) 共用同一個函式，不另外宣告。 |
| 建立 | `src/training_kb/handlers/import_.py` | `training-kb-import` 這支 Lambda 的入口 `handler(event, context)`（00A D-56）；套件 `handlers/__init__.py` 由 Phase 30 建立。 |
| 修改 | `infra/training_kb_stack.py` | 加 `training-kb-import` 這支 Lambda 與它的最小 IAM（00A D-58）；stack 本體由 [Phase 41](./41-Phase41-Ticket-Analysis雲端流程驗收.md) 建立，本 Phase 只加資源。 |
| 測試 | `tests/unit/infra/test_import_lambda.py` | 用 CDK `Template` 斷言這支 Lambda 的名稱、handler 與「沒有 Function URL」。 |
| 測試 | `tests/unit/test_fixed_import_validate.py` | rating 嚴格整數、`f_` 前綴、必填欄位、`ts` 缺值與必填。 |
| 測試 | `tests/integration/test_fixed_import.py` | moto 下的寫入、退役拒絕、重送去重、續跑與 handler 逐筆分派。 |

## 5. 固定介面

### Consumes

```text
Phase 02：IngressError(message: str, fields: tuple[str, ...])、PermanentError、parse_iso、to_iso、now_utc
Phase 02：DEFAULT_PROJECT_ID = "demo"、load_settings(env) -> Settings（從 training_kb.config import，00A D-34）
Phase 03：TutorialStatus.ACTIVE / TutorialStatus.RETIRED（StrEnum 成員大寫、值小寫）
Phase 04：Feedback(id, tutorial_version, rating, category, comment, user, ts)、TutorialView(tutorial_version, user, ts)
Phase 05：feedback_pk、version_pk、view_pk(tutorial_version, user, ts)、parse_pk
Phase 06／07：Repository.get_meta(pk, model, *, consistent=True)、put_meta(entity, *, create_only=True)、get_tutorial、get_version、put_edge(pk, relation, target_pk, attrs=None)
Phase 10：OperationCoordinator.accept(AcceptOperation) -> Acceptance、complete(operation_id, *, now)、OperationKind
Phase 26：assert_accepts_feedback(tutorial: Tutorial) -> None（retired 時丟 IngressError(fields=("tutorial_version",))）
Phase 31：missing_nonempty_strings(payload, keys) -> tuple[str, ...]（必填非空字串檢查，不另寫一份）
Phase 30／32／37：normalize_then_accept(*, domain, adapter, event_type, headers, payload, deadline) -> Acceptance
                 六個參數全 keyword-only（00A D-60）；operation_id_for(kind, canonical_id) -> str
Phase 41：infra/training_kb_stack.py 的 TrainingKbStack（本 Phase 在同一支 stack 加一支 Lambda，00A D-58）
```

### Produces

```python
FEEDBACK_FIELDS: frozenset[str]   # {"id","tutorial_version","rating","category","comment","user","ts","project_id"}
VIEW_FIELDS: frozenset[str]       # {"tutorial_version","user","ts","project_id"}
IMPORT_KINDS: tuple[str, ...]     # ("feedback", "view", "ticket", "release")
IMPORT_DEADLINE_SECONDS = 300.0   # 匯入 Lambda 自己的期限，與 webhook 的八秒無關

@dataclass(frozen=True)
class ImportResult:
    status: Literal["saved", "duplicate", "rejected"]
    object_id: str | None
    message: str
    invalid_fields: tuple[str, ...]

def validate_feedback(payload: Mapping[str, object], *, now: datetime) -> Feedback: ...
def validate_view(payload: Mapping[str, object]) -> TutorialView: ...
def import_feedback(payload: Mapping[str, object], *, repository: Repository, operations: OperationCoordinator, now: datetime) -> ImportResult: ...
def import_view(payload: Mapping[str, object], *, repository: Repository, operations: OperationCoordinator, now: datetime | None = None) -> ImportResult: ...

# src/training_kb/handlers/import_.py（00A D-56）
def handler(event: dict, context: object) -> dict: ...
```

兩項本計畫選擇：`import_view` 的 `now` 是可選 keyword（缺值用 `now_utc()`），因為 `AcceptOperation` 需要接受時間而 View 的 `ts` 是事件時間；`IMPORT_KINDS` 是 handler 接受的四種 `kind`，順序只影響錯誤訊息；`IMPORT_DEADLINE_SECONDS` 與 `handler` 都放 `src/training_kb/handlers/import_.py`（00A §6.8）。`operation_id_for` **與 Phase 32 共用同一個函式**（owner 是 Phase 32，型別本來就是 `OperationKind`），本 Phase 只是多用 `feedback`／`view` 兩個值，不改簽名也不另外宣告一份。`DEFAULT_PROJECT_ID` 同樣不是本 Phase 產出：它在 Phase 02 的 `config.py`，值是 `"demo"`，這裡只 import 來當操作紀錄的分組，不寫進 `Feedback`／`TutorialView`。[Phase 43](./43-Phase43-Feedback類別判定.md) 之後會在 `import_feedback` 末端加上一個有預設值的 `writer: Writer | None = None`，本 Phase 的呼叫端與測試不受影響。

## 6. 設計細節

驗證順序固定如下，先擋純欄位問題，再查圖譜，最後才問操作紀錄：

```text
未知欄位 / 必填缺值 / rating 非 1..5 整數 --> rejected + invalid_fields
        | 通過
版本存在於圖譜？ ------------ 否 --> rejected(["tutorial_version"])
        | 是
Feedback：assert_accepts_feedback(tutorial) 丟 IngressError？ -- 是 --> 同上 rejected
        | 否（View 不做這一關）
OperationCoordinator.accept
   accepted  -> 寫 metadata（Feedback 另寫 REFERS_TO 邊）--> saved
   duplicate -> 物件真的存在？ -- 是 --> duplicate（不增加樣本）
                      | 否 --> 續跑：補寫物件，仍記同一 operation
```

- **rating 必須是嚴格整數。** `bool` 是 `int` 的子類別，`isinstance(True, int)` 為真，所以用 `type(value) is int`。Pydantic v2 轉換表把 `int` 欄位收到 `bool` 標成 strict 模式不允許，但 Phase 03 的 `StrictModel` 只設 `extra="forbid"`、`frozen=True`，入口必須自己擋；`"4"` 與 `3.5` 同樣拒絕。
- **`Feedback.ts` 缺值用匯入時間並註明。** 設計 §7.1 允許補值，成功訊息必須寫明「非使用者實際提交時間」；`TutorialView.ts` 必填，不得補成「先瀏覽」的證據。
- **退役只擋 Feedback，而且判斷來自 Phase 26。** 設計 §8.4：退役版本拒絕新回饋、既有回饋仍可查閱；退役教學的歷史頁仍會被讀，所以 View 照收。判斷一律呼叫 [Phase 26](./26-Phase26-教學退役與後繼導向.md) 的 `assert_accepts_feedback(tutorial)`，**不得自己再寫一次 `status` 比較**；它丟的 `IngressError` 的 `fields` 就是 `("tutorial_version",)`，接住後直接轉成 `rejected`，不必比對訊息字串。要寫 fixture 時 enum 成員名是大寫的 `TutorialStatus.RETIRED`（值才是小寫 `"retired"`）。
- **重送與續跑不同。** 設計 §14.1／§14.2 要求「取得既有結果或沿用未完成邏輯操作」：`accept` 回 duplicate 只代表這個 `operation_id` 被接受過，目標物件不存在時要補寫。這是 00A D-45 明文允許的**合法補寫**，與 [Phase 10](./10-Phase10-O2操作紀錄與永久去重契約.md) §6 的續跑分支是同一條契約，不算重複處理。
- **`Feedback` 必填 `id, tutorial_version, rating, user`**，取自設計 §7.1 接入表；Phase 04 的模型把 `rating` 宣告為 `int | None` 以容納既有資料，本階段入口更嚴格（00A D-12「模型寬、入口嚴」），被接受的回饋都同時滿足 Phase 04 的不變條件。
- **使用者 ID 只用一種形狀。** Demo 與本文件範例一律 `u_01`；真實 GitHub 來源是 `u_gh-<id>`（Phase 13）。兩者共存但**同一批資料內不得混用**，也不建對照表（00A D-47）。本 Phase 只檢查 `user` 是非空字串，不驗證前綴，也不得自己造 ID。

## 7. TDD Tasks

### Task 1：鎖定 Feedback 與 View 的欄位契約

- [ ] **Step 1：建立失敗測試**

```python
# tests/unit/test_fixed_import_validate.py
NOW = datetime(2026, 9, 14, 3, 0, tzinfo=UTC)
FEEDBACK = {"id": "f_12", "tutorial_version": "prepare-meeting@v1", "rating": 2, "user": "u_01"}
VIEW = {"tutorial_version": "prepare-meeting@v1", "user": "u_01", "ts": "2026-08-02T09:00:00Z"}


@pytest.mark.parametrize("bad_rating", [True, False, "4", 3.5, 0, 6, None])
def test_rating_must_be_a_strict_integer_between_one_and_five(bad_rating: object) -> None:
    with pytest.raises(IngressError) as error:
        validate_feedback({**FEEDBACK, "rating": bad_rating}, now=NOW)
    assert error.value.fields == ("rating",)


def test_missing_feedback_ts_defaults_but_missing_view_ts_fails() -> None:
    assert validate_feedback(FEEDBACK, now=NOW).ts == NOW
    with pytest.raises(IngressError) as error:
        validate_view({k: v for k, v in VIEW.items() if k != "ts"})
    assert error.value.fields == ("ts",)
```

- [ ] **Step 2：執行並確認紅燈**

```bash
uv run pytest tests/unit/test_fixed_import_validate.py -q
```

預期：FAIL，訊號包含 `cannot import name 'validate_feedback'`。

- [ ] **Step 3：建立最小實作**

```python
def validate_feedback(payload: Mapping[str, object], *, now: datetime) -> Feedback:
    bad: list[str] = sorted(set(payload) - FEEDBACK_FIELDS)
    feedback_id = _text(payload, "id", bad)
    if feedback_id and not feedback_id.startswith("f_"):
        bad.append("id")
    rating = payload.get("rating")
    if type(rating) is not int or not 1 <= rating <= 5:
        bad.append("rating")
    raw_ts, ts = payload.get("ts"), now
    if isinstance(raw_ts, str):
        try:
            ts = parse_iso(raw_ts)
        except ValueError:
            bad.append("ts")
    elif raw_ts is not None:
        bad.append("ts")
    values = {"tutorial_version": _text(payload, "tutorial_version", bad),
              "user": _text(payload, "user", bad),
              "category": _optional_text(payload, "category", bad),
              "comment": _optional_text(payload, "comment", bad)}
    if bad:
        raise IngressError("回饋欄位不合法", bad)   # IngressError 自己會排序去重
    return Feedback(id=feedback_id, rating=rating, ts=ts, **values)
```

- [ ] **Step 4：以同樣形狀補 `validate_view` 並跑完整檔案**

`_text(payload, field, bad)` 取非空字串，缺值就把欄位名記入 `bad` 並回 `""`；`_optional_text` 只把空字串收斂成 `None`，非字串記入 `bad`。`VIEW_FIELDS` 固定為 `{"tutorial_version", "user", "ts", "project_id"}`，三個欄位一律走 `_text`，`ts` 另以 `parse_iso` 驗格式，**沒有**補值分支。再加四個案例：`id` 缺 `f_` 前綴、payload 多一個 `score` 欄位（`invalid_fields` 必須含 `"score"`）、`category` 與 `comment` 皆空但 `rating` 合法（必須成功）、View 的 `ts` 為 `"2026/08/02 09:00"`（必須 `("ts",)`）。跑 `uv run pytest tests/unit/test_fixed_import_validate.py -q` 應全綠。

- [ ] **Step 5：提交**

```bash
git add src/training_kb/ingress.py tests/unit/test_fixed_import_validate.py
git commit -m "feat(ingress): 驗證回饋與瀏覽紀錄匯入欄位"
```

### Task 2：寫入圖譜、退役拒絕與重送去重

- [ ] **Step 1：建立失敗測試**

```python
# tests/integration/test_fixed_import.py
def test_retired_tutorial_rejects_feedback_but_still_accepts_views(retired_repo, operations) -> None:
    rejected = import_feedback(FEEDBACK, repository=retired_repo, operations=operations, now=NOW)
    accepted = import_view(VIEW, repository=retired_repo, operations=operations, now=NOW)
    assert (rejected.status, rejected.invalid_fields) == ("rejected", ("tutorial_version",))
    assert accepted.status == "saved"


def test_same_feedback_id_resent_is_duplicate(active_repo, operations) -> None:
    first = import_feedback(FEEDBACK, repository=active_repo, operations=operations, now=NOW)
    again = import_feedback(FEEDBACK, repository=active_repo, operations=operations, now=NOW)
    assert (first.status, again.status) == ("saved", "duplicate")
    assert len(active_repo.list_feedback_of_version("prepare-meeting@v1")) == 1
```

- [ ] **Step 2：執行並確認紅燈**

```bash
uv run pytest tests/integration/test_fixed_import.py -q
```

預期：FAIL，訊號包含 `cannot import name 'import_feedback'`。

- [ ] **Step 3：依固定順序實作 `import_feedback`**

先 `try: feedback = validate_feedback(payload, now=now)` / `except IngressError as error: return _rejected(error.message, error.fields)`——00A §4.1 規定固定匯入把 `IngressError` 轉成 `rejected`，不讓例外往呼叫端冒。接著 `version = repository.get_version(...)`、`tutorial = repository.get_tutorial(version.slug)`，任一為 `None` 即 `_rejected("版本不存在於圖譜", ("tutorial_version",))` → 用 Phase 26 的檢查擋退役，**不自己比 `status`**：

```python
def _assert_open(tutorial) -> ImportResult | None:
    try:
        assert_accepts_feedback(tutorial)          # Phase 26 唯一的退役判斷
    except IngressError as error:
        return _rejected("此教學已退役，不再接受新回饋", error.fields)
    return None


def _dedupe(payload, feedback, repository, operations, now):
    operation_id = operation_id_for("feedback", feedback.id)
    acceptance = operations.accept(AcceptOperation(
        operation_id=operation_id, kind="feedback", canonical_id=feedback.id,
        project_id=_project_id(payload), now=now,
    ))
    already = repository.get_meta(feedback_pk(feedback.id), Feedback) is not None
    return operation_id, acceptance.status == "duplicate" and already
```

`_assert_open` 回非 `None` 就直接回那個 `ImportResult`；`_dedupe` 回 `True` 就直接回 `ImportResult("duplicate", feedback.id, "相同 Feedback ID 已匯入，不再計一筆有效回饋", ())`；否則 `put_meta(feedback, create_only=True)` → `put_edge(feedback_pk(feedback.id), "REFERS_TO", version_pk(feedback.tutorial_version))` → `operations.complete(operation_id, now=now)` → `ImportResult("saved", feedback.id, _saved_message(payload, feedback), ())`。

- [ ] **Step 4：補三個 helper 與兩個案例，再跑完整檔案**

`_rejected(message, fields)` 固定回 `ImportResult("rejected", None, message, tuple(fields))`；`_project_id` 取 payload 的 `project_id`，缺值用 `DEFAULT_PROJECT_ID`；`_saved_message` 只有在 `payload.get("ts") is None` 時才附加「來源未提供 ts，改記匯入時間 …，非使用者實際提交時間」。兩個新案例：版本不存在時 `rejected` 且圖譜零變動；同一 `u_01` 用 `f_12`、`f_13` 送同一版本，兩筆都 `saved` 且各計一筆。

- [ ] **Step 5：提交**

```bash
git add src/training_kb/ingress.py tests/integration/test_fixed_import.py
git commit -m "feat(ingress): 保存回饋並以操作紀錄永久去重"
```

### Task 3：View 去重與未完成操作續跑

- [ ] **Step 1：建立失敗測試**

```python
def test_same_view_triple_is_deduplicated(active_repo, operations) -> None:
    first = import_view(VIEW, repository=active_repo, operations=operations, now=NOW)
    second = import_view(VIEW, repository=active_repo, operations=operations, now=NOW)
    assert (first.status, second.status) == ("saved", "duplicate")
    assert second.object_id == first.object_id
    assert len(active_repo.list_views_of_version("prepare-meeting@v1")) == 1


def test_accepted_but_unwritten_operation_is_resumed(active_repo, operations) -> None:
    operations.accept(accept_request_for(VIEW))  # 模擬寫 item 之前就中斷
    resumed = import_view(VIEW, repository=active_repo, operations=operations, now=NOW)
    assert resumed.status == "saved"
    assert len(active_repo.list_views_of_version("prepare-meeting@v1")) == 1
```

- [ ] **Step 2：執行並確認紅燈**

```bash
uv run pytest tests/integration/test_fixed_import.py::test_same_view_triple_is_deduplicated -q
```

預期：FAIL，訊號包含 `cannot import name 'import_view'`。

- [ ] **Step 3：依固定順序實作 `import_view`**

`accepted_at = now_utc() if now is None else now` → `validate_view`（同樣 `except IngressError` 轉 `rejected`）→ 版本不存在即 `_rejected("版本不存在於圖譜", ("tutorial_version",))`（**不**查 retired）→ `pk = view_pk(view.tutorial_version, view.user, view.ts)`、`canonical_id = parse_pk(pk)[1]` → `operations.accept(AcceptOperation(operation_id=operation_id_for("view", canonical_id), kind="view", canonical_id=canonical_id, project_id=_project_id(payload), now=accepted_at))` → duplicate 且 `repository.get_meta(pk, TutorialView)` 有值才回 `duplicate`，否則續跑 → `put_meta(view, create_only=True)` → `operations.complete(...)` → `ImportResult("saved", pk, "已保存瀏覽紀錄", ())`。View 沒有關係邊，設計 §9.2 明講不新增 `VIEWED`。

- [ ] **Step 4：跑整份整合測試並核對副作用**

```bash
uv run pytest tests/integration/test_fixed_import.py -q
```

逐一斷言：整個測試過程沒有任何 `StartExecution`、沒有 `PROC#` item、沒有新 `VERSION#` item、FakeWriter 呼叫數為 0。

- [ ] **Step 5：提交**

```bash
git add src/training_kb/ingress.py tests/integration/test_fixed_import.py
git commit -m "feat(ingress): 保存瀏覽紀錄並以 view_pk 去重"
```

### Task 4：`training-kb-import` 的 Lambda 入口

- [ ] **Step 1：建立失敗測試**

```python
# 續寫 tests/integration/test_fixed_import.py
import pytest
from training_kb.errors import PermanentError
from training_kb.handlers import import_
from training_kb.pipelines.common import Deps


def test_handler_imports_every_item_and_starts_no_pipeline(active_repo, operations, monkeypatch):
    monkeypatch.setattr(import_, "_DEPS",
                        Deps(operations=operations, now=lambda: NOW, repository=active_repo))
    items = [FEEDBACK, {**FEEDBACK, "id": "f_13"}, {**FEEDBACK, "rating": True}]
    body = import_.handler({"kind": "feedback", "source": "widget-download", "items": items}, None)
    assert [row["status"] for row in body["results"]] == ["saved", "saved", "rejected"]
    assert body["results"][2]["invalid_fields"] == ("rating",)
    assert active_repo.started_executions == []      # Feedback 永遠不啟動 pipeline


@pytest.mark.parametrize("event", [{"kind": "tutorial", "items": []}, {"kind": "feedback"}])
def test_handler_refuses_unknown_kind_or_missing_items(event):
    with pytest.raises(PermanentError):
        import_.handler(event, None)
```

同一個 Step 另外建 `tests/unit/infra/test_import_lambda.py`，用 CDK 的 `Template`（把合成出來的 CloudFormation 樣板當字典查）斷言這支 Lambda 真的被接上去：

```python
import aws_cdk as cdk
from aws_cdk.assertions import Match, Template
from infra.training_kb_stack import TrainingKbStack


def test_import_lambda_is_wired_without_a_function_url():
    template = Template.from_stack(TrainingKbStack(cdk.App(), "TrainingKbApp"))
    template.has_resource_properties("AWS::Lambda::Function", {
        "FunctionName": "training-kb-import",
        "Handler": "training_kb.handlers.import_.handler"})
    # 全 stack 只有 Phase 30 的 webhook 有公開網址；匯入用 boto3 invoke，不開 Function URL
    template.resource_count_is("AWS::Lambda::Url", 1)
    template.has_resource_properties("AWS::IAM::Policy", {
        "PolicyDocument": Match.object_like({"Statement": Match.array_with([
            Match.object_like({"Action": "states:StartExecution"})])})})
```

- [ ] **Step 2：執行並確認紅燈**

```bash
uv run pytest tests/integration/test_fixed_import.py -q
```

預期：FAIL，訊號包含 `No module named 'training_kb.handlers.import_'`。

- [ ] **Step 3：建立最小實作**

```python
# src/training_kb/handlers/import_.py（00A D-56；handlers/__init__.py 由 Phase 30 建立）
import os
from dataclasses import asdict
from time import monotonic

from training_kb.config import load_settings
from training_kb.errors import PermanentError
from training_kb.ingress import (IMPORT_KINDS, ImportResult, import_feedback, import_view,
                                 missing_nonempty_strings, normalize_then_accept)
from training_kb.pipelines.common import build_deps

IMPORT_DEADLINE_SECONDS = 300.0
_DEPS = None


def handler(event, context):
    global _DEPS
    kind, items = str(event.get("kind") or ""), event.get("items")
    if kind not in IMPORT_KINDS or not isinstance(items, list):
        raise PermanentError(f"匯入事件不合法：kind={event.get('kind')!r}")
    if _DEPS is None:
        _DEPS = build_deps(load_settings(os.environ))
    return {"kind": kind, "source": event.get("source"),
            "results": [asdict(_import_one(kind, item)) for item in items]}


def _import_one(kind, payload) -> ImportResult:
    repository, operations = _DEPS.need_repository(), _DEPS.operations
    if kind == "feedback":
        return import_feedback(payload, repository=repository, operations=operations,
                               now=_DEPS.now())
    if kind == "view":
        return import_view(payload, repository=repository, operations=operations, now=_DEPS.now())
    missing = missing_nonempty_strings(payload, ("domain", "adapter", "event_type"))
    if missing:
        raise PermanentError(f"{kind} 匯入缺少來源欄位：{missing}")
    acceptance = normalize_then_accept(              # 00A D-60：六個 keyword 參數
        domain=str(payload["domain"]), adapter=str(payload["adapter"]),
        event_type=str(payload["event_type"]),
        headers={name.lower(): value for name, value in (payload.get("headers") or {}).items()},
        payload=payload["payload"],
        deadline=monotonic() + IMPORT_DEADLINE_SECONDS)
    return ImportResult("duplicate" if acceptance.status == "duplicate" else "saved",
                        acceptance.record.canonical_id,
                        f"{kind} 已交給 {acceptance.operation_id}", ())
```

`handler` 逐筆處理、逐筆回結果：一筆 `rejected` 不影響其他筆，這正是設計 §7.1「指出欄位、允許修正」（F51）的形狀。`ticket`／`release` 只是把原始事件交給 `normalize_then_accept`（那條路徑才有 Rote 與 `StartExecution`），本 Phase 不重寫也不改它的 deadline 語意——八秒是公開 webhook 的限制，受控匯入用自己的 `IMPORT_DEADLINE_SECONDS`。那六個 keyword 參數是 00A D-60 固定的：匯入檔的每一筆自己帶 `domain`／`adapter`／`event_type`／`headers`／`payload`（維護者匯出時就填好），**不從 payload 反推**，缺了就整筆 `PermanentError`。`_DEPS` 快取讓 Lambda 暖啟動不重建連線，測試直接 monkeypatch 它。

同一個 Step 在 [Phase 41](./41-Phase41-Ticket-Analysis雲端流程驗收.md) 建立的 `infra/training_kb_stack.py` 裡加這支 Lambda（00A D-58：`training-kb-import` 的 CDK 接線歸本 Phase）：

```python
# infra/training_kb_stack.py：接在 Phase 41 的 task_fn／webhook_fn 之後
import_fn = lambda_.Function(
    self, "ImportFunction", function_name="training-kb-import",
    runtime=lambda_.Runtime.PYTHON_3_12, code=lambda_.Code.from_asset("src"),
    handler="training_kb.handlers.import_.handler",
    timeout=Duration.seconds(300), environment=base_env)   # 對齊 IMPORT_DEADLINE_SECONDS
table.grant_read_write_data(import_fn)
bucket.grant_read_write(import_fn)
machine.grant_start_execution(import_fn)      # ticket／release 分支要能啟動 pipeline
```

**不開 Function URL**：這支只給維護者用 boto3 `invoke` 呼叫，沒有公開入口就沒有驗簽需求（公開的只有 Phase 30 的 `training-kb-webhook`）。IAM 只到「table 讀寫、bucket 讀寫、`states:StartExecution`」三項，沒有 `bedrock:InvokeModel`——本 Phase 這條路徑不呼叫模型（[Phase 43](./43-Phase43-Feedback類別判定.md) 加留言分類時才會補上）。`timeout` 設 300 秒與 `IMPORT_DEADLINE_SECONDS` 對齊，數字改一邊就要改另一邊。

- [ ] **Step 4：跑整份整合測試與 CDK 斷言確認綠燈**

```bash
uv run pytest tests/integration/test_fixed_import.py tests/unit/infra/test_import_lambda.py -q
```

再補一個 `{"kind": "view", "items": [VIEW, VIEW]}` 的案例：兩筆結果是 `saved`、`duplicate`，`list_views_of_version` 仍只有一筆。多出第三支 Lambda 之後，Phase 41 的 `test_stack_has_one_standard_machine_and_two_named_lambdas` 仍要綠：它已改成包含式斷言（那兩支仍在、handler 不變）。若你看到它因為「字典**等於**兩筆」而轉紅，改那個斷言，**不要**刪掉本 Phase 的資源讓它變綠。

- [ ] **Step 5：提交**

```bash
git add src/training_kb/handlers/import_.py infra/training_kb_stack.py \
        tests/integration/test_fixed_import.py tests/unit/infra/test_import_lambda.py
git commit -m "feat(ingress): 建立固定匯入的 Lambda 入口"
```

## 8. 驗收矩陣

| 路徑 | 輸入 | 預期資料結果 |
|---|---|---|
| Happy | `f_12` 指向已發布的 `prepare-meeting@v1`；只有 `rating` 的回饋；指向未發布版本的 View | 全部 `saved`；回饋另寫一條 `REFERS_TO` 邊，§7.1 允許只評分，View 不要求已發布。 |
| Failure | `rating` 為 `True`／`"4"`／`3.5`／`0`／`6` | `rejected`，`invalid_fields=("rating",)`，零寫入。 |
| Failure | 缺 `user`，或 View 缺 `ts` | `rejected` 並指出該欄位；View 不得用匯入時間補。 |
| Failure | 教學 `status=retired`（由 `assert_accepts_feedback` 判定），或 `tutorial_version` 不在圖譜 | `rejected` 且 `invalid_fields == ("tutorial_version",)`；退役時同版 View 仍 `saved`。 |
| Boundary | 同 ID／同三元組重送；同人不同 ID（`f_12`、`f_13`） | 前者 `duplicate` 且樣本數不變，後者兩筆都 `saved` 各計一筆。 |
| Boundary | 操作已接受但物件未寫成 | 續跑補寫，最後仍只有一筆。 |
| Happy | handler 收到三筆 feedback（兩筆合法、一筆 `rating=True`） | `results` 依序 `saved`／`saved`／`rejected`，一筆壞資料不影響其他筆，零次 `StartExecution`。 |
| Failure | handler 的 `kind` 不在四種內，或 `items` 不是陣列 | 丟 `PermanentError`，一筆都不寫。 |

人工驗收：跑完整合測試後直接 `Query` `FEEDBACK#f_12` 與 `by_target=VERSION#prepare-meeting@v1`，用眼睛確認 metadata 與邊各只有一筆，再確認執行紀錄沒有任何 Step Functions 啟動；不能只看 pytest 顯示 PASS。

## 9. 常見錯誤與停止條件

| 症狀 | 原因 | 修正／停止 |
|---|---|---|
| `rating=True` 被存成 1 分 | 用 `isinstance(value, int)` 判斷 | 改成 `type(value) is int`；平均分已受污染就停止 Phase 44。 |
| 重送多一筆回饋 | 去重只查記憶體或只靠 TTL | 回到 Phase 10／11 的 `OPS#` 條件寫入；O2 未過不得宣稱去重完成。 |
| View 缺 `ts` 仍寫入，或退役教學仍收回饋 | 沿用回饋的補值邏輯；只查版本沒查 Tutorial 狀態 | `ts` 必填以免偽造「先瀏覽後開票」證據；退役判斷一律呼叫 Phase 26 的 `assert_accepts_feedback`。 |
| 自己寫 `tutorial.status == "retired"` 或 `TutorialStatus.retired` | 沒有沿用 Phase 26，或用了小寫成員名 | 改呼叫 `assert_accepts_feedback`；StrEnum 成員名是大寫 `TutorialStatus.RETIRED`，小寫寫法會 `AttributeError`。 |
| 成功訊息沒說時間是補的，或匯入後流程被啟動 | 只回「已保存」；沿用 Ticket／Release 的接入程式 | 補上「非使用者實際提交時間」；Feedback／View 不啟動 pipeline、不進 Rote。 |
| handler 遇到一筆壞資料就整批失敗 | 讓 `IngressError` 往外冒 | 固定匯入把 `IngressError` 轉成 `ImportResult(status="rejected")`（00A §4.1、F51），逐筆回結果。 |

## 10. 來源與 Rule 對照

- [收集教學回饋.feature](../../spec/features/收集教學回饋.feature)
  - Rule 1：「Feedback 的 tutorial_version 必須存在於圖譜」→ Task 2 Step 4 的版本不存在案例直接斷言 `status="rejected"` 且 `invalid_fields == ("tutorial_version",)`。
  - Rule 2：「已退役教學的既有版本拒絕新回饋」→ Task 2 的 `test_retired_tutorial_rejects_feedback_but_still_accepts_views`。本 Phase 是 primary（00B 第 3.2 節），但判斷本身呼叫 [Phase 26](./26-Phase26-教學退役與後繼導向.md) 的 `assert_accepts_feedback`（Phase 26 為相關，測試保留）；[Phase 57](./57-Phase57-S3靜態教學站與回饋下載.md) 的「退役頁不出現 widget」也是相關。
  - Rule 3：「Feedback 的 rating 只能為 1 到 5 的整數」→ Task 1 的參數化案例（`True`／`"4"`／`3.5`／`0`／`6`）。
  - Rule 7：「回饋關聯到提交時指定的 TutorialVersion」→ Task 2 斷言 `REFERS_TO#VERSION#prepare-meeting@v1` 邊，且不改綁 `current_version`；Rule 8「收到單筆低分 Feedback 時不立即修改 Tutorial」→ Task 3 Step 4 斷言零新 `VERSION#` item。
  - Rule 9：「Feedback 接入時必須提供穩定使用者 ID」→ Task 1 Step 4 的缺 `user` 案例；Rule 10「同一使用者對同一版本的每次新提交都計一筆」→ Task 2 的 `f_12`／`f_13` 與重送案例。
  - Rule 4、5、6（勾選優先、核定類別表、留言分類）由 [Phase 43](./43-Phase43-Feedback類別判定.md) 擁有；本階段保留 `category` 原值，不得宣稱類別契約已滿足。
- [接入來源事件.feature](../../spec/features/接入來源事件.feature)
  - Rule 28：「正規化成功的 Feedback 寫入 FEEDBACK item」→ Task 2 斷言寫入成功且沒有 PROC、沒有 StartExecution；Rule 29「單筆 Feedback 接入不立即觸發教學改版」→ Task 3 Step 4 與 Task 4 的副作用斷言。兩條的 primary 都是本 Phase。
  - Rule 24「正規化物件的 id 直接使用已全域唯一的上游識別碼」→ **相關（primary [Phase 13](./13-Phase13-O6來源ID與穩定使用者契約.md)）**；Task 1 只檢查 `f_` 前綴與非空 `user`，ID 編碼函式不在本 Phase。
  - Rule 30「同一正規化事件重送時只處理一次」→ **相關（primary [Phase 10](./10-Phase10-O2操作紀錄與永久去重契約.md)）**；Task 2、Task 3 的重送與續跑案例是固定匯入這條路徑的再驗，不重新認領。
  - Rule 31「只有 Rote 接入層讀寫 PROVEN_WORKFLOW」→ **相關（primary [Phase 35](./35-Phase35-PROC成功失敗與退役生命週期.md)）**；Task 3 Step 4 斷言整條路徑零 `PROC#` 變動。
- 設計 §5：Feedback／View 走固定保存路徑、不通過 Rote。§7.1：必填欄位、`ts` 補值與「不啟動 Step Functions、不更新 PROC」。§9.1／§9.2：`VIEW#` 的 SHA-256 鍵與 `REFERS_TO` 邊格式，且不新增 `VIEWED` 邊。§8.4／§14.1／§14.2：退役拒絕新回饋、重送取得既有結果或續跑未完成操作。§16 S4：View 與 Feedback 可匯入、穩定 user 能對上工單、重送不重複。
- 設計 §19 決策：D11（不允許沒有穩定使用者 ID）、D12（只有評分的回饋有效，不送模型分類）、D13（核定類別表，未知值進待分類，屬 Phase 43）、D14（每個新提交 ID 算一筆，只排除同提交重送）、D23（瀏覽／回饋／Ticket 共用同一個穩定使用者 ID）、D24（MVP 新增瀏覽事件，至少記版本、使用者與時間）、F39（退役後拒絕新回饋、保留既有回饋）、F51（立即拒絕並指出不合法欄位，不建立 FEEDBACK 或成功回執）。
- [Pydantic v2 轉換表](https://pydantic.dev/docs/validation/latest/concepts/conversion_table/)：`int` 欄位收到 `bool` 在 strict 模式不允許、lax 模式會被轉換；本階段因此在入口自行擋 `bool`。

## 11. 完成清單

- [ ] `ImportResult`、`validate_feedback`、`validate_view`、`import_feedback`、`import_view` 簽名與本文件一致；`operation_id_for` 與 `DEFAULT_PROJECT_ID` 都是 import 來的，沒有第二份定義。
- [ ] rating 只接受 1..5 的嚴格整數，`bool`、字串與小數全部落在 `invalid_fields`。
- [ ] `Feedback.ts` 缺值改記匯入時間且訊息明示；`TutorialView.ts` 必填；退役檢查呼叫 Phase 26 的 `assert_accepts_feedback`，同版瀏覽紀錄仍可匯入。
- [ ] 同 ID／同三元組重送回 `duplicate`，已接受但未寫成的操作會續跑。
- [ ] `src/training_kb/handlers/import_.py::handler` 存在且逐筆回結果，`kind` 不在四種內丟 `PermanentError`；`feedback`／`view` 分支零次 `StartExecution`。
- [ ] `infra/training_kb_stack.py` 有 `training-kb-import` 這支 Lambda（handler `training_kb.handlers.import_.handler`、無 Function URL、IAM 只到 table／bucket／`states:StartExecution`），並有 `Template` 斷言。
- [ ] `ticket`／`release` 分支呼叫 `normalize_then_accept` 的六個 keyword 參數（D-60），缺 `domain`／`adapter`／`event_type` 時整筆 `PermanentError`。
- [ ] 整條路徑零模型呼叫、零 Step Functions 啟動、零 PROC 變更；收集 Rule 1、2、3、7、8、9、10 與接入 Rule 28、29 各有直接 assertion。
- [ ] 未把 moto 綠燈說成 O2 永久去重或 O6 穩定使用者契約已通過。
