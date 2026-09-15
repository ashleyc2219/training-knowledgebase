# Phase 42：Feedback 與 View 固定匯入實作計畫

> **給實作者：** 依 checkbox 逐步執行；每個 Task 先建立失敗測試，再寫最小實作。執行時使用 `superpowers:executing-plans` 或同等逐項流程。

> **現況核對（2026-09-14，Phase 41–60 批次 W0）：**
>
> **(a) 已存在、可直接重用（不要重寫）**
> - `src/training_kb/ingress.py`：`missing_nonempty_strings`、`_parsed_ts`（`ts` 必須是 aware ISO-8601 **整秒**，naive／格式錯／帶微秒一律 `IngressError(("ts",))`）、`_optional_string`、`_invalid_fields`、`validate_ticket`／`validate_release`、`operation_id_for(kind: OperationKind, canonical_id) -> str`、`normalize_then_accept`、`PIPELINE_FOR_KIND`（只有 `ticket`／`release`，已明寫「Feedback／View 走 P42 的固定匯入，不啟動任何 pipeline」）。
> - `src/training_kb/content.py::assert_accepts_feedback(tutorial) -> None`（P26）。`content.py` 不 import `ingress`，所以 `ingress` 反向 import 它**沒有循環風險**。
> - `src/training_kb/models.py`：`Feedback` **已經**有 `rating_is_strict_int`（`mode="before"`，`bool` 與非 1..5 直接 `ValueError`）與 `carries_signal`（rating／category／comment 全空即拒絕）；`TutorialView.ts` 是必填 `datetime`；兩者的 ID 欄位都過 `bare_id`。
> - `src/training_kb/keys.py`：`feedback_pk`、`version_pk`、`view_pk(tutorial_version, user, ts)`（內部呼叫 `to_iso`，**ts 帶微秒會丟 `PermanentError`**）、`parse_pk`。
> - `src/training_kb/repository.py`：`get_meta`／`put_meta`／`put_edge`／`get_tutorial`／`get_version`／`get_meta_item`／`list_feedback_of_version`／`list_views_of_version` 全部已實作，本 Phase 只呼叫。`_entity_pk` 已經認得 `Feedback` 與 `TutorialView`（後者的 PK 就是 `view_pk`），`put_meta` 不必再自己算鍵。
> - `src/training_kb/operations.py`：`OperationKind` 已含 `"feedback"`／`"view"`；`AcceptOperation(operation_id, kind, canonical_id, project_id, now)`、`Acceptance(status, operation_id, record)`、`accept`、`complete(operation_id, *, now)`。
> - `src/training_kb/config.py::DEFAULT_PROJECT_ID = "demo"`、`load_settings(env=None)`。
> - 測試器材：`tests/integration/conftest.py` 的 `table`／`bucket`／`repository`（moto 表＋bucket＋`by_target` GSI）；`tests/integration/test_retired_feedback_rejected.py`（P26）是現成的退役種子範例，照抄形狀即可，**不要改那支檔**。
>
> **(b) 因上一批裁決／實作而修正的點**
> 1. `normalize_then_accept` **回 `list[Acceptance]`**（D-73；F14 一個 PR 展開成 n 筆子 Release），不是單一 `Acceptance`。§5 Consumes 與 §7 Task 4 的 handler 片段已改。
> 2. `build_deps(settings) -> Deps` 的 owner 是 **P41**（00A §6 `pipelines/common.py` 名稱表）。目前 `pipelines/common.py` 只有 `Deps`／`run_sequence`，**還沒有 `build_deps`**；P41 在 W1 建立，本 Phase（W2）才 import。
> 3. `infra/training_kb_stack.py` 目前**不存在**（`infra/` 只有 `app.py` 與 `training_kb_data_stack.py`）；`tests/unit/infra/` 目錄也還沒建。兩者都由 P41 在 W1 產出，本 Phase 只用 **Edit** 往裡面追加。
> 4. P41 的包含式斷言在 `tests/unit/infra/test_ticket_asl.py::test_stack_has_one_standard_machine_and_two_named_lambdas`（原文只寫函式名，這裡補上檔案路徑）。它已經用 `handlers[...]` 的包含式比對，多一支 Lambda 不會轉紅。
> 5. §6「Phase 03 的 `StrictModel` 只設 `extra="forbid"`、`frozen=True`，入口必須自己擋」的**理由**要更新：`Feedback` 模型自己就擋掉 `bool` 與 1..5 範圍了。入口仍然要自己判斷，但原因是**要吐 `IngressError(fields=("rating",))` 而不是 pydantic `ValidationError`**（00A §6.8「模型層 `ValidationError` 一律收斂成 `IngressError`」），不是模型沒擋。
> 6. `ts` 一律 aware ISO-8601 **整秒**（00A §3.5）。`validate_feedback`／`validate_view` 應**重用既有的 `_parsed_ts`**（它已同時擋 naive、格式錯與微秒），不要只用 `parse_iso`：`parse_iso` 放行微秒，之後 `view_pk` 內部的 `to_iso` 會丟 `PermanentError`，那不是使用者輸入錯誤該有的形狀。
> 7. §7 Task 4 的 `assert active_repo.started_executions == []` **不成立**：`Repository` 沒有這個屬性。零啟動要用「把 `ingress._build_wiring` 換成會丟 `AssertionError` 的函式」＋「表裡沒有新的 `PROC#`／`VERSION#` item」來斷言（內文已改）。
> 8. 名稱歸屬：`ImportResult`、`FEEDBACK_FIELDS`、`VIEW_FIELDS` 與四個函式放 `ingress.py`；`IMPORT_KINDS`、`IMPORT_DEADLINE_SECONDS`、`handler` 放 `handlers/import_.py`（00A §6.8 那一列）。
> 9. 00A 第 915 列寫成「`validate_feedback` 必須呼叫 P26 的 `assert_accepts_feedback`」，但 `validate_feedback` 是純欄位函式、拿不到 `Tutorial`。**以 00A 第 425 列的實質規則為準**：P42 這條路徑一律呼叫 `assert_accepts_feedback`、不自己再寫一次 retired 判斷；呼叫點在 `import_feedback`（已取得 `Tutorial` 之後）。已回報 controller。
>
> **(c) gate 現況對本 Phase 的影響**（COMMON.md §2）
> - **O2 PASS**（P11，`docs/plan/report/o2-20260914t182824z.md`）：永久去重可以依賴；但本 Phase 的 moto 綠燈只代表「這條路徑也套用了同一份契約」，不是新的 O2 證據。
> - **O3 FAIL**（`docs/plan/report/o3-20260914t181109z.md`）：本 Phase 不公開任何內容，不受影響，也不得宣稱 O3 有變化。
> - **O5 BLOCKED**（`docs/plan/report/o5-20260915T030245Z.md`）：feedback／view 這條路徑零模型呼叫，**不受阻**；真正呼叫模型的是 [Phase 43](./43-Phase43-Feedback類別判定.md)。
> - **O6 4 列待核定**（`docs/plan/report/o6-mapping.md`）：11 個 `xfail(strict=True)` 全部在 Rote／來源簽名那一側（`tests/integration/test_o6_*`、`test_adapter_fixtures.py`、`test_release_extraction.py`、`test_rote_commit.py`、`tests/unit/rote/`）。**固定匯入的 `feedback`／`view` 分支不經 Rote、不查 `approved_stable_keys()`，所以 O6 不擋它**；被擋的只有 handler 的 `ticket`／`release` 分支（那條會走 `normalize_then_accept` → Rote）。`stable_user_from_import` 目前只被 `adapters.py` 的手動 batch parser 呼叫，不在本 Phase 路徑上。**本計畫選擇**：`validate_feedback`／`validate_view` 直接重用 `source_ids.stable_user_from_import(user)` 做 `user` 格式檢查（它丟的正是 `IngressError(fields=("user",))`），既滿足 `COL` Rule 9 又不另寫一份判斷，但**不因此宣稱 O6 已核定**。
>
> **(d) 適用的 controller 裁決**（COMMON.md §3）
> - **R2**：`training-kb-import` **沿用 P41 建立的相依 layer／bundling**，不自己再做一套（`lambda_.Code.from_asset("src")` 不含 `pydantic`／`jsonschema`）。
> - **R3**：本 Phase 在 **W2**，同波次的 **P54 也會改 `infra/training_kb_stack.py`**（加 `training-kb-analytics`）。只用 Edit、放進自己的 `# ---- Phase 42 ----` 區段、不重排別人的程式、`git add` 只加自己的路徑。`ingress.py` 在 W2 只有 P42 動（P43 在 W3、P59 在 W4）。
> - **R5**：本文件的程式片段是示意，名稱與簽名以 00A ＋ 既有程式為準。
> - **R10 本計畫選擇**：`release` 分支要啟動的 `training-kb-release-update` state machine 在 **P52（W3）** 才建立，本 Phase 只能對當下已存在的 `training-kb-ticket-analysis` 授權 `states:StartExecution`；release-update 的授權由 P52 建 state machine 時一併補上，本 Phase 寫進報告「未做／建議」。

**目標：** 讓維護者上傳的回饋與瀏覽紀錄走一條只有程式判斷的固定路徑：驗證欄位、確認版本、永久去重、寫入 DynamoDB，全程不呼叫模型也不啟動流程。

**架構：** `ingress` 先做純欄位檢查（`validate_feedback`／`validate_view`），再由 `import_feedback`／`import_view` 查 `Repository` 的版本與教學狀態、向 `OperationCoordinator` 取得永久去重結果，最後寫 metadata 與 `REFERS_TO` 邊。Rote、Step Functions 與 PROC 完全不參與這條路徑。

**技術：** Python 3.12、Pydantic v2、pytest、moto、既有 `Repository`、`OperationCoordinator` 與 `keys.view_pk`。

## 全域限制

- 唯一主來源是 [Training KB 設計 §5、§7.1、§8.4、§9.1、§9.2、§14.1、§14.2、§16 S4](../../design/training-kb.md)。
- 前置為 [Phase 41：Ticket Analysis 雲端流程驗收](./41-Phase41-Ticket-Analysis雲端流程驗收.md)；資料面另需 [Phase 08：分頁查詢與一致讀取基礎](./08-Phase08-分頁查詢與一致讀取基礎.md) 與 [Phase 11：O2 接受順序與重啟整合驗證](./11-Phase11-O2接受順序與重啟整合驗證.md)；判斷與接線另需 [Phase 26：教學退役與後繼導向](./26-Phase26-教學退役與後繼導向.md)（`assert_accepts_feedback`）、[Phase 30：GitHub Webhook 原始 Body 驗簽](./30-Phase30-GitHub-Webhook原始Body驗簽.md)（`handlers/` 套件與 `normalize_then_accept`）與 [Phase 32：事件接受去重與流程啟動](./32-Phase32-事件接受去重與流程啟動.md)（`operation_id_for`）。前置未通過時停止。
- 下一階段是 [Phase 43：Feedback 類別判定](./43-Phase43-Feedback類別判定.md)。
- 本階段不做：**Feedback／View 這條路徑**不呼叫任何模型、不收斂 `category` 也不分類留言（全部屬 Phase 43）、不啟動 Step Functions、不更新 PROC、不建立或修改教學版本、不計算任何指標。匯入 handler 的 `ticket`／`release` 分支只是把事件原樣交給 [Phase 32](./32-Phase32-事件接受去重與流程啟動.md)／[Phase 37](./37-Phase37-Rote-Agent回退與成功提交.md) 已經寫好的 `normalize_then_accept`，本 Phase 不重寫那條路徑，也不改它的行為。
- 與本 Phase 有關的 O1–O7 gate 狀態（**現況核對 2026-09-14**：原寫「O2 未取得真實整合證據前」，實際上 **O2 已 PASS**）：O2 **PASS**（P11，`docs/plan/report/o2-20260914t182824z.md`），永久去重可以依賴，但本 Phase 的 moto 綠燈只是同一份契約的再套用，不是新的 O2 證據；O6 **4 列待核定**（`docs/plan/report/o6-mapping.md`），不得宣稱 `user` 已能跨來源對上 `Ticket.author`——但 O6 blocked 的是 Rote 那一側，`feedback`／`view` 這條不經 Rote 的路徑不受它阻擋（只有 handler 的 `ticket`／`release` 分支受阻）。O3 **FAIL**（`docs/plan/report/o3-20260914t181109z.md`），本階段不碰它，因為它不公開任何內容。O5 **BLOCKED**（`docs/plan/report/o5-20260915T030245Z.md`），本階段零模型呼叫，不受影響。
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
| 修改 | `infra/training_kb_stack.py` | 加 `training-kb-import` 這支 Lambda 與它的最小 IAM（00A D-58）；stack 本體由 [Phase 41](./41-Phase41-Ticket-Analysis雲端流程驗收.md) 建立（**現況核對 2026-09-14：這支檔目前還不存在，P41 在 W1 才建**），本 Phase 只用 **Edit** 加資源，打包沿用 P41 的相依 layer／bundling（COMMON.md R2）。同波次的 P54 也會改這支檔。 |
| 測試 | `tests/unit/infra/test_import_lambda.py` | 用 CDK `Template` 斷言這支 Lambda 的名稱、handler 與「沒有 Function URL」（`tests/unit/infra/` 目錄由 P41 建立）。 |
| 測試 | `tests/unit/test_fixed_import_validate.py` | rating 嚴格整數、`f_` 前綴、必填欄位、`ts` 缺值與必填。 |
| 測試 | `tests/integration/test_fixed_import.py` | moto 下的寫入、退役拒絕、重送去重、續跑與 handler 逐筆分派。 |

## 5. 固定介面

### Consumes

```text
Phase 02：IngressError(message: str, fields: tuple[str, ...])、PermanentError、parse_iso、to_iso、now_utc
Phase 02：DEFAULT_PROJECT_ID = "demo"、load_settings(env=None) -> Settings（從 training_kb.config import，00A D-34）
Phase 13：stable_user_from_import(value: str) -> str（training_kb.source_ids；格式不合丟 IngressError(fields=("user",))）
Phase 31：_parsed_ts(payload) -> datetime（ingress.py 內部；ts 必須 aware ISO-8601 整秒，naive／格式錯／帶微秒一律 IngressError(("ts",))）
Phase 03：TutorialStatus.ACTIVE / TutorialStatus.RETIRED（StrEnum 成員大寫、值小寫）
Phase 04：Feedback(id, tutorial_version, rating, category, comment, user, ts)、TutorialView(tutorial_version, user, ts)
Phase 05：feedback_pk、version_pk、view_pk(tutorial_version, user, ts)、parse_pk
Phase 06／07：Repository.get_meta(pk, model, *, consistent=True)、put_meta(entity, *, create_only=True)、get_tutorial、get_version、put_edge(pk, relation, target_pk, attrs=None)
Phase 10：OperationCoordinator.accept(AcceptOperation) -> Acceptance、complete(operation_id, *, now)、OperationKind
Phase 26：assert_accepts_feedback(tutorial: Tutorial) -> None（retired 時丟 IngressError(fields=("tutorial_version",))）
Phase 31：missing_nonempty_strings(payload, keys) -> tuple[str, ...]（必填非空字串檢查，不另寫一份）
Phase 30／32／37：normalize_then_accept(*, domain, adapter, event_type, headers, payload, deadline) -> list[Acceptance]
                 六個參數全 keyword-only（00A D-60）；**回 list**（D-73，現況核對 2026-09-14：原寫 Acceptance）
                 operation_id_for(kind: OperationKind, canonical_id: str) -> str
Phase 41：infra/training_kb_stack.py 的 TrainingKbStack（本 Phase 在同一支 stack 加一支 Lambda，00A D-58）
Phase 41：pipelines/common.py 的 build_deps(settings: Settings) -> Deps（owner 是 P41，W1 才建立）
Phase 29／38：Deps(operations, now, repository=None, writer=None, settings=None) 與 need_repository()／need_writer()／need_settings()
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

- **rating 必須是嚴格整數。** `bool` 是 `int` 的子類別，`isinstance(True, int)` 為真，所以用 `type(value) is int`；`"4"` 與 `3.5` 同樣拒絕。（**現況核對 2026-09-14：原寫「Phase 03 的 `StrictModel` 只設 `extra="forbid"`、`frozen=True`，入口必須自己擋」，實際上 `Feedback` 模型已有 `rating_is_strict_int`（`mode="before"`）自己擋掉 `bool` 與 1..5 範圍。** 入口仍要自己判斷，但理由是**要吐 `IngressError(fields=("rating",))` 而不是 pydantic `ValidationError`**——00A §6.8 規定接入層一律把 `ValidationError` 收斂成 `IngressError`。`Feedback` 另有 `carries_signal` 驗證器：rating／category／comment 全空會被拒絕，本 Phase 要求 rating 必填所以一定滿足。）
- **`Feedback.ts` 缺值用匯入時間並註明。** 設計 §7.1 允許補值，成功訊息必須寫明「非使用者實際提交時間」；`TutorialView.ts` 必填，不得補成「先瀏覽」的證據。
- **`ts` 一律是 aware ISO-8601 整秒。**（現況核對 2026-09-14）00A §3.5 要求全套時間字串只有一種形狀；`view_pk` 內部呼叫 `to_iso`，遇到微秒會丟 `PermanentError`。所以兩個 `validate_*` 都**重用 `ingress.py` 既有的 `_parsed_ts(payload)`**（naive／格式錯／帶微秒都已經丟 `IngressError(("ts",))`），不要只用 `parse_iso`。`validate_feedback` 因為 `ts` 可缺值，只在 `payload.get("ts") is not None` 時才呼叫它。
- **退役只擋 Feedback，而且判斷來自 Phase 26。** 設計 §8.4：退役版本拒絕新回饋、既有回饋仍可查閱；退役教學的歷史頁仍會被讀，所以 View 照收。判斷一律呼叫 [Phase 26](./26-Phase26-教學退役與後繼導向.md) 的 `assert_accepts_feedback(tutorial)`，**不得自己再寫一次 `status` 比較**；它丟的 `IngressError` 的 `fields` 就是 `("tutorial_version",)`，接住後直接轉成 `rejected`，不必比對訊息字串。要寫 fixture 時 enum 成員名是大寫的 `TutorialStatus.RETIRED`（值才是小寫 `"retired"`）。
- **重送與續跑不同。** 設計 §14.1／§14.2 要求「取得既有結果或沿用未完成邏輯操作」：`accept` 回 duplicate 只代表這個 `operation_id` 被接受過，目標物件不存在時要補寫。這是 00A D-45 明文允許的**合法補寫**，與 [Phase 10](./10-Phase10-O2操作紀錄與永久去重契約.md) §6 的續跑分支是同一條契約，不算重複處理。
- **`Feedback` 必填 `id, tutorial_version, rating, user`**，取自設計 §7.1 接入表；Phase 04 的模型把 `rating` 宣告為 `int | None` 以容納既有資料，本階段入口更嚴格（00A D-12「模型寬、入口嚴」），被接受的回饋都同時滿足 Phase 04 的不變條件。
- **使用者 ID 只用一種形狀。** Demo 與本文件範例一律 `u_01`；真實 GitHub 來源是 `u_gh-<id>`（Phase 13）。兩者共存但**同一批資料內不得混用**，也不建對照表（00A D-47）。本 Phase 不驗證前綴，也不得自己造 ID。（**現況核對 2026-09-14，本計畫選擇**：原寫「只檢查 `user` 是非空字串」；改成直接重用 Phase 13 的 `source_ids.stable_user_from_import(user)`——它只做格式檢查 `^[a-z0-9_-]{2,64}$`，缺值時丟的正是 `IngressError(fields=("user",))`，`u_01` 與 `u_gh-90210` 都通過。這樣 `COL` Rule 9 直接由既有函式滿足，不另寫一份判斷（R10）。`stable_user_from_import` 目前只被 `adapters.py` 的手動 batch parser 呼叫，加這個呼叫點不影響任何 O6 的 `xfail`。）

## 7. TDD Tasks

### Task 1：鎖定 Feedback 與 View 的欄位契約

- [x] **Step 1：建立失敗測試**

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

- [x] **Step 2：執行並確認紅燈**

```bash
uv run pytest tests/unit/test_fixed_import_validate.py -q
```

預期：FAIL，訊號包含 `cannot import name 'validate_feedback'`。

- [x] **Step 3：建立最小實作**

```python
def validate_feedback(payload: Mapping[str, object], *, now: datetime) -> Feedback:
    bad: list[str] = sorted(set(payload) - FEEDBACK_FIELDS)
    feedback_id = _text(payload, "id", bad)
    if feedback_id and not feedback_id.startswith("f_"):
        bad.append("id")
    rating = payload.get("rating")
    if type(rating) is not int or not 1 <= rating <= 5:
        bad.append("rating")
    ts = now
    if payload.get("ts") is not None:            # 現況核對 2026-09-14：改用既有的 `_parsed_ts`
        try:                                     # 它已經擋 naive、格式錯與**微秒**（00A §3.5）
            ts = _parsed_ts(payload)
        except IngressError:
            bad.append("ts")
    values = {"tutorial_version": _text(payload, "tutorial_version", bad),
              "user": _stable_user(payload, bad),   # Phase 13 的 stable_user_from_import
              "category": _optional_text(payload, "category", bad),
              "comment": _optional_text(payload, "comment", bad)}
    if bad:
        raise IngressError("回饋欄位不合法", bad)   # IngressError 自己會排序去重
    return Feedback(id=feedback_id, rating=rating, ts=ts, **values)
```

- [x] **Step 4：以同樣形狀補 `validate_view` 並跑完整檔案**

`_text(payload, field, bad)` 取非空字串，缺值就把欄位名記入 `bad` 並回 `""`；`_optional_text` 只把空字串收斂成 `None`，非字串記入 `bad`；`_stable_user(payload, bad)` 先 `_text` 再交給 Phase 13 的 `stable_user_from_import`，它丟 `IngressError` 就把 `"user"` 記入 `bad`（現況核對 2026-09-14）。`VIEW_FIELDS` 固定為 `{"tutorial_version", "user", "ts", "project_id"}`，`tutorial_version` 走 `_text`、`user` 走 `_stable_user`，`ts` 另以 **`_parsed_ts`** 驗格式（現況核對 2026-09-14：原寫 `parse_iso`，它放行微秒會讓 `view_pk` 丟 `PermanentError`），**沒有**補值分支。再加四個案例：`id` 缺 `f_` 前綴、payload 多一個 `score` 欄位（`invalid_fields` 必須含 `"score"`）、`category` 與 `comment` 皆空但 `rating` 合法（必須成功）、View 的 `ts` 為 `"2026/08/02 09:00"`（必須 `("ts",)`）。另加兩個現況核對補上的案例（2026-09-14）：View 的 `ts` 為 `"2026-08-02T09:00:00.500Z"`（帶微秒，必須 `("ts",)`，否則 `view_pk` 會在下游丟 `PermanentError`）、`user` 為 `"U_01"`（大寫不符 `stable_user_from_import` 的 `^[a-z0-9_-]{2,64}$`，必須 `("user",)`）。跑 `uv run pytest tests/unit/test_fixed_import_validate.py -q` 應全綠。

- [x] **Step 5：提交**

```bash
git add src/training_kb/ingress.py tests/unit/test_fixed_import_validate.py
git commit -m "feat(ingress): 驗證回饋與瀏覽紀錄匯入欄位"
```

### Task 2：寫入圖譜、退役拒絕與重送去重

- [x] **Step 1：建立失敗測試**

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

- [x] **Step 2：執行並確認紅燈**

```bash
uv run pytest tests/integration/test_fixed_import.py -q
```

預期：FAIL，訊號包含 `cannot import name 'import_feedback'`。

- [x] **Step 3：依固定順序實作 `import_feedback`**

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

- [x] **Step 4：補三個 helper 與兩個案例，再跑完整檔案**

`_rejected(message, fields)` 固定回 `ImportResult("rejected", None, message, tuple(fields))`；`_project_id` 取 payload 的 `project_id`，缺值用 `DEFAULT_PROJECT_ID`；`_saved_message` 只有在 `payload.get("ts") is None` 時才附加「來源未提供 ts，改記匯入時間 …，非使用者實際提交時間」。兩個新案例：版本不存在時 `rejected` 且圖譜零變動；同一 `u_01` 用 `f_12`、`f_13` 送同一版本，兩筆都 `saved` 且各計一筆。

- [x] **Step 5：提交**

```bash
git add src/training_kb/ingress.py tests/integration/test_fixed_import.py
git commit -m "feat(ingress): 保存回饋並以操作紀錄永久去重"
```

### Task 3：View 去重與未完成操作續跑

- [x] **Step 1：建立失敗測試**

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

- [x] **Step 2：執行並確認紅燈**

```bash
uv run pytest tests/integration/test_fixed_import.py::test_same_view_triple_is_deduplicated -q
```

預期：FAIL，訊號包含 `cannot import name 'import_view'`。

- [x] **Step 3：依固定順序實作 `import_view`**

`accepted_at = now_utc() if now is None else now` → `validate_view`（同樣 `except IngressError` 轉 `rejected`）→ 版本不存在即 `_rejected("版本不存在於圖譜", ("tutorial_version",))`（**不**查 retired）→ `pk = view_pk(view.tutorial_version, view.user, view.ts)`、`canonical_id = parse_pk(pk)[1]` → `operations.accept(AcceptOperation(operation_id=operation_id_for("view", canonical_id), kind="view", canonical_id=canonical_id, project_id=_project_id(payload), now=accepted_at))` → duplicate 且 `repository.get_meta(pk, TutorialView)` 有值才回 `duplicate`，否則續跑 → `put_meta(view, create_only=True)` → `operations.complete(...)` → `ImportResult("saved", pk, "已保存瀏覽紀錄", ())`。View 沒有關係邊，設計 §9.2 明講不新增 `VIEWED`。

- [x] **Step 4：跑整份整合測試並核對副作用**

```bash
uv run pytest tests/integration/test_fixed_import.py -q
```

逐一斷言：整個測試過程沒有任何 `StartExecution`、沒有 `PROC#` item、沒有新 `VERSION#` item、FakeWriter 呼叫數為 0。

- [x] **Step 5：提交**

```bash
git add src/training_kb/ingress.py tests/integration/test_fixed_import.py
git commit -m "feat(ingress): 保存瀏覽紀錄並以 view_pk 去重"
```

### Task 4：`training-kb-import` 的 Lambda 入口

- [x] **Step 1：建立失敗測試**

```python
# 續寫 tests/integration/test_fixed_import.py
import pytest
from training_kb.errors import PermanentError
from training_kb.handlers import import_
from training_kb.pipelines.common import Deps


def test_handler_imports_every_item_and_starts_no_pipeline(active_repo, operations, monkeypatch):
    monkeypatch.setattr(import_, "_DEPS",
                        Deps(operations=operations, now=lambda: NOW, repository=active_repo))
    # 現況核對 2026-09-14：`Repository` 沒有 `started_executions`。零啟動改成「任何要連 AWS
    # 的接受路徑一被碰到就炸」——`ingress._build_wiring` 是 `PipelineStarter` 的唯一產地。
    def boom(*args, **kwargs):
        raise AssertionError("feedback／view 不得啟動任何 pipeline")
    monkeypatch.setattr(ingress, "_build_wiring", boom)
    monkeypatch.setattr(ingress, "_build_rote_deps", boom)
    ingress._reset_wiring()
    items = [FEEDBACK, {**FEEDBACK, "id": "f_13"}, {**FEEDBACK, "rating": True}]
    body = import_.handler({"kind": "feedback", "source": "widget-download", "items": items}, None)
    assert [row["status"] for row in body["results"]] == ["saved", "saved", "rejected"]
    assert body["results"][2]["invalid_fields"] == ("rating",)
    assert active_repo.scan_entity("PROC") == []     # 整條路徑零 PROC 變動（ING Rule 31）


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

- [x] **Step 2：執行並確認紅燈**

```bash
uv run pytest tests/integration/test_fixed_import.py -q
```

預期：FAIL，訊號包含 `No module named 'training_kb.handlers.import_'`。

- [x] **Step 3：建立最小實作**

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
    accepted = normalize_then_accept(                # 00A D-60：六個 keyword 參數
        domain=str(payload["domain"]), adapter=str(payload["adapter"]),
        event_type=str(payload["event_type"]),
        headers={name.lower(): value for name, value in (payload.get("headers") or {}).items()},
        payload=payload["payload"],
        deadline=monotonic() + IMPORT_DEADLINE_SECONDS)
    # 現況核對 2026-09-14：`normalize_then_accept` 回 **list[Acceptance]**（D-73）。
    # 一個 PR 可展開成 n 筆子 Release，各自一個 operation；這裡與 P30 的 handler 同口徑：
    # `object_id` 取第一筆，訊息列出全部 operation ID，不丟掉其餘幾筆。
    first = accepted[0]
    status = "duplicate" if all(a.status == "duplicate" for a in accepted) else "saved"
    ids = ", ".join(a.operation_id for a in accepted)
    return ImportResult(status, first.record.canonical_id, f"{kind} 已交給 {ids}", ())
```

**現況核對（2026-09-14）—— 型別註記**：`mypy` 是 strict 且 `files = ["src", "infra"]`，上面的片段是示意，實際要照 `handlers/github_webhook.py` 的寫法標註完整型別：`def handler(event: dict[str, Any], context: object) -> dict[str, object]`、`_DEPS: Deps | None = None`、`def _import_one(kind: str, payload: Mapping[str, object]) -> ImportResult`。`build_deps` 由 P41 在 W1 建立於 `pipelines/common.py`（若你在 W2 開工時它還不存在，那是 P41 未完成，回報 controller，不要自己在本 Phase 造一份）。

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
machine.grant_start_execution(import_fn)      # ticket 分支要能啟動 ticket-analysis
```

**現況核對（2026-09-14）**：`code=` 與 `environment=base_env` 一律**沿用 P41 那兩支 Lambda 的寫法**（相依 layer 或 bundling，COMMON.md R2），不要退回裸的 `Code.from_asset("src")`——那樣不會帶 `pydantic`／`jsonschema`。`machine` 在 P41 的 stack 裡只有 `training-kb-ticket-analysis` 一條；`release` 分支要的 `training-kb-release-update` 由 [Phase 52](./52-Phase52-Release-Update流程與RETIRE.md) 在 W3 才建立，所以**本 Phase 只授權 ticket-analysis**，release-update 的 `grant_start_execution(import_fn)` 由 P52 建 state machine 時一併補上（本計畫選擇，寫進報告「未做／建議」）。新增的資源全部放在 `# ---- Phase 42：training-kb-import ----` 註解區段裡，不動 P41 既有的程式（R3）。

**不開 Function URL**：這支只給維護者用 boto3 `invoke` 呼叫，沒有公開入口就沒有驗簽需求（公開的只有 Phase 30 的 `training-kb-webhook`）。IAM 只到「table 讀寫、bucket 讀寫、`states:StartExecution`」三項，沒有 `bedrock:InvokeModel`——本 Phase 這條路徑不呼叫模型（[Phase 43](./43-Phase43-Feedback類別判定.md) 加留言分類時才會補上）。`timeout` 設 300 秒與 `IMPORT_DEADLINE_SECONDS` 對齊，數字改一邊就要改另一邊。

- [x] **Step 4：跑整份整合測試與 CDK 斷言確認綠燈**

```bash
uv run pytest tests/integration/test_fixed_import.py tests/unit/infra/test_import_lambda.py -q
```

再補一個 `{"kind": "view", "items": [VIEW, VIEW]}` 的案例：兩筆結果是 `saved`、`duplicate`，`list_views_of_version` 仍只有一筆。多出第三支 Lambda 之後，Phase 41 的 `tests/unit/infra/test_ticket_asl.py::test_stack_has_one_standard_machine_and_two_named_lambdas` 仍要綠（**現況核對 2026-09-14**：原文只寫函式名，實際檔案是 `test_ticket_asl.py`；它已經是 `handlers[...]` 的包含式斷言，多一支 Lambda 不會轉紅）。若你看到它因為「字典**等於**兩筆」而轉紅，改那個斷言，**不要**刪掉本 Phase 的資源讓它變綠。另外，同波次的 P54 也會往同一支 stack 加 `training-kb-analytics`；若整套測試的紅燈來自 P54 進行中的檔案，用 `--ignore=` 排除並在報告寫明，不要去修別人的測試（R3.5）。

- [x] **Step 5：提交**

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

> **實作結果（2026-09-14／15，Phase 42 實作者）：** 全部 Task 與完成清單都做到，並依 controller
> 裁決**真的部署到 AWS**（原 brief §8 寫「本 Phase 不直接跑真實 AWS」，以 controller 的 dispatch
> 為準）。與本文件片段不同、屬於**本計畫選擇**的地方：
>
> 1. **退役測試的位置**：`test_retired_tutorial_rejects_feedback_but_still_accepts_views`（00B
>    引用的名字）放在 **Task 3**，因為它同時要 `import_feedback` 與 `import_view`，而後者在
>    Task 3 才落地；Task 2 自己有一條只看回饋的 `test_retired_tutorial_rejects_new_feedback`。
> 2. **`_dedupe` 是泛型的**（`def _dedupe[MetaT: StrictModel](...)`，PEP 695）：回饋與瀏覽共用
>    同一份「accept → 目標物件是否真的存在 → 重複或續跑」邏輯，不各寫一份。
> 3. **`import_feedback` 本 Phase 不宣告 `writer`**：00A 第 915 列的完整簽名含
>    `writer: Writer | None = None`，但同一列註明「`writer` 由 P43 追加」。參數全是
>    keyword-only，P43 追加時不會動到任何呼叫端（§5 Produces 已這樣寫）。
> 4. **IAM 用 P41 的 `_grant_data` 而不是 CDK 的 `grant_read_write_data`**（本文件 §7 Task 4 的
>    片段寫後者）：CDK 的 grant 會把 `DeleteItem` 混進同一條敘述，D-79 要的「只有一條
>    `DeleteItem`」就守不住。範圍依 controller 2026-09-14 的補充交代收到最小：S3 只有
>    `operations/*`（**沒有** `site/*`）、DynamoDB 只有 `GetItem`／`PutItem`／`UpdateItem`／`Scan`
>    （`Scan` 是 `ticket`／`release` 分支的 `rote.list_procs` 要的），**不給索引**。
> 5. **`missing_nonempty_strings` 也用在 `_text`**：單一欄位的必填檢查沿用同一份實作，
>    「一次回報所有缺欄位」仍然只有一個地方決定什麼叫「缺」。
> 6. **雲端證據**在 `docs/plan/report/phases/2026-09-14-Phase42-REP.md` §4：`training-kb-import`
>    的 `aws lambda invoke` 回應原文（saved／duplicate／rejected 七種結果）、寫進真表的 item
>    原文、IAM policy 原文、CloudWatch log 與「ticket-analysis 執行數 5 → 5」。

## 11. 完成清單

- [x] `ImportResult`、`validate_feedback`、`validate_view`、`import_feedback`、`import_view` 簽名與本文件一致；`operation_id_for` 與 `DEFAULT_PROJECT_ID` 都是 import 來的，沒有第二份定義。
- [x] rating 只接受 1..5 的嚴格整數，`bool`、字串與小數全部落在 `invalid_fields`。
- [x] `Feedback.ts` 缺值改記匯入時間且訊息明示；`TutorialView.ts` 必填；退役檢查呼叫 Phase 26 的 `assert_accepts_feedback`，同版瀏覽紀錄仍可匯入。
- [x] 同 ID／同三元組重送回 `duplicate`，已接受但未寫成的操作會續跑。
- [x] `src/training_kb/handlers/import_.py::handler` 存在且逐筆回結果，`kind` 不在四種內丟 `PermanentError`；`feedback`／`view` 分支零次 `StartExecution`。
- [x] `infra/training_kb_stack.py` 有 `training-kb-import` 這支 Lambda（handler `training_kb.handlers.import_.handler`、無 Function URL、IAM 只到 table／bucket／`states:StartExecution`），並有 `Template` 斷言。
- [x] `ticket`／`release` 分支呼叫 `normalize_then_accept` 的六個 keyword 參數（D-60），並正確處理它回傳的 **`list[Acceptance]`**（D-73，現況核對 2026-09-14）；缺 `domain`／`adapter`／`event_type` 時整筆 `PermanentError`。
- [x] `ts` 走既有的 `_parsed_ts`（aware、整秒；微秒被拒），`user` 走 Phase 13 的 `stable_user_from_import`，兩者都沒有第二份實作（現況核對 2026-09-14）。
- [x] 整條路徑零模型呼叫、零 Step Functions 啟動、零 PROC 變更；收集 Rule 1、2、3、7、8、9、10 與接入 Rule 28、29 各有直接 assertion。
- [x] 未把 moto 綠燈說成 O2 永久去重或 O6 穩定使用者契約已通過。
