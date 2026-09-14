# Fix wave 報告（Phase 01–20 最終 review：5 項必修 ＋ 2 項順手）

分支 `backend`，7 項全數完成，6 個獨立 commit，全套 gate 全綠。
基準線（動工前）：`365` 之前是 **356 passed / 23 skipped**；`uv run mypy infra` **10 errors**；ruff 全過。

---

## 必修 1：型別 gate 涵蓋 infra（缺 `py.typed`）

**改了什麼**

- 新增空檔 `src/training_kb/py.typed`。
- `pyproject.toml`：加 `[tool.setuptools.package-data] training_kb = ["py.typed"]`；
  `[tool.mypy] files` 由 `["src"]` 改成 `["src", "infra"]`。
- `uv sync` 重建 editable 安裝把 marker 帶進去。**`uv.lock` 沒有變動**（`git status -- uv.lock` 乾淨），
  因此沒有進 commit。

**測試**

`tests/unit/test_package.py` 新增 `test_package_ships_py_typed_marker`：用
`importlib.resources.files("training_kb").joinpath("py.typed").is_file()` 查**安裝出來的**套件，
而不是 repo 裡的原始檔——marker 沒跟著安裝走，下游 `infra/` 一樣會是 `import-untyped`。

**指令與輸出**

RED（建檔前）：

```
$ uv run pytest tests/unit/test_package.py -q -W error
>       assert files("training_kb").joinpath("py.typed").is_file()
E       AssertionError: assert False
FAILED tests/unit/test_package.py::test_package_ships_py_typed_marker
1 failed, 1 passed in 0.03s
```

GREEN：

```
$ uv run pytest tests/unit/test_package.py -q -W error
2 passed in 0.01s
$ uv run mypy src infra
Success: no issues found in 23 source files
```

**兩個 `no-any-return` 自動消失**（`o2_report.py:194`、`:227`），確認它們只是
`import-untyped` 的下游效應，不需要在 `o2_report.py` 動型別收窄，也沒有用 `# type: ignore` 或 `cast`。

commit：`c8f97c2 chore(core): 加入 py.typed 並讓 mypy 涵蓋 infra`

---

## 必修 2：十實體 datetime 一律 UTC 整秒（00A §3.5）

**改了什麼**

`src/training_kb/models.py` 的 `aware()` 由「只檢查 tz-aware」改成三步：

1. naive 直接 `ValueError("datetime must be timezone aware")`（原有行為不變）；
2. `value.microsecond` 非零 → `ValueError("datetime must be whole seconds")`（**明確拒絕，不靜默截斷**，
   與 `clock.to_iso` 同一句話）；
3. `return value.astimezone(UTC)`。

`aware()` 是十實體全部 datetime 欄位（`Feature.first_seen`、`Ticket.ts`、`Release.ts`、
`Feedback.ts`、`TutorialView.ts`、`TutorialVersion.published_at`、`ProvenWorkflow.last_used`）
的共同 validator，所以一改就全部收斂。`from datetime import datetime` 補上 `UTC`。

這解掉的是：`repository.put_meta` 走 `model_dump(mode="json")`，不正規化就會把 `.123456Z`
與 `+08:00` 原樣寫進表，與 `clock.to_iso`（拒絕微秒、只輸出 `Z`）分岔；`TutorialView` 的
`view_pk`（經 `to_iso`）與 `ts` 屬性也因此對同一時刻有兩種字串。

**測試**（`tests/unit/test_entity_invariants.py` 新增 3 支）

- `test_every_datetime_field_rejects_sub_second_precision`：七個實體的 datetime 欄位逐一餵
  `2026-08-03T10:00:00.123456+00:00`，全部要 `ValidationError` 且訊息含 `whole seconds`。
- `test_datetime_fields_normalise_to_utc_on_the_way_in`：`Ticket`／`Feature` 用 `+08:00` 建模後
  `utcoffset() == 0`，且 `model_dump(mode="json")` 得到 `"2026-08-03T10:00:00Z"`。
- `test_tutorial_view_key_and_ts_agree_across_offsets`：`+08:00` 與同一瞬間的 UTC 建出的
  `TutorialView`，`view_pk` 相同、`model_dump(mode="json")["ts"]` 相同且都是 `...Z`。

**指令與輸出**

RED：

```
$ uv run pytest tests/unit/test_entity_invariants.py -q -W error
E       AssertionError: assert '2026-08-03T18:00:00+08:00' == '2026-08-03T10:00:00Z'
FAILED ...::test_every_datetime_field_rejects_sub_second_precision
FAILED ...::test_datetime_fields_normalise_to_utc_on_the_way_in
FAILED ...::test_tutorial_view_key_and_ts_agree_across_offsets
3 failed, 13 passed in 0.17s
```

GREEN：

```
$ uv run pytest tests/unit/test_entity_invariants.py -q -W error
16 passed in 0.13s
$ uv run pytest tests -q -W error
360 passed, 23 skipped in 20.34s
```

**沒有任何既有測試依賴微秒或非 UTC 偏移**，所以不需要依 00A 改動既有測試。
（掃過的證據：`grep -rn "microsecond|\+08:00|timezone(timedelta" src tests infra` 只命中
`tests/unit/test_keys.py:208`（本來就是斷言 `view_pk` 拒絕微秒）、`tests/unit/test_clock.py`
（`clock` 自己的測試）、`clock.py`／`check_models.py` 的 `replace(microsecond=0)`。）

commit：`0cf638c fix(core): 實體時間一律正規化為 UTC 整秒`

---

## 必修 3：`accept()` 取號失敗時要先確認是否已被接受

**改了什麼**

`src/training_kb/operations.py` 的 `accept` 把 `next_sequence` 包進 `try`：

```python
try:
    seq = self.next_sequence(f"PROJECT#{request.project_id}")
except CoordinationError:
    existing = self.load(request.operation_id)
    if existing is None:
        raise
    return Acceptance("duplicate", request.operation_id, existing)
```

三分支結構保留，正常路徑仍是條件寫入，**沒有**改成「先查再寫」；多出來的那次讀取只發生在
取號已經失敗的路徑上。docstring 補了一段「**取號失敗時先確認是否已被接受**」，寫明去重依據是
「這筆紀錄存在」而不是「這次取得到號碼」。

**測試**（`tests/unit/test_operation_ordering.py` 新增 2 支，`monkeypatch` 讓 `next_sequence` 丟 `CoordinationError`）

- `test_a_resend_is_still_duplicate_when_the_counter_is_too_hot`：已接受過的 operation 重送 →
  `status == "duplicate"`、`accept_seq` 沿用第一次的、`repository.items["OPS#..."]` 與事前快照**逐鍵相同**。
- `test_a_first_time_accept_still_fails_when_the_counter_is_too_hot`：未接受過 → 例外照丟，
  且 `OPS#` item 一筆都沒寫。

**指令與輸出**

RED：

```
$ uv run pytest tests/unit/test_operation_ordering.py -q -W error
src/training_kb/operations.py:268: in accept
    seq = self.next_sequence(f"PROJECT#{request.project_id}")
E       training_kb.errors.CoordinationError: sequence contention over 8 attempts: PROJECT#demo
FAILED ...::test_a_resend_is_still_duplicate_when_the_counter_is_too_hot
1 failed, 11 passed in 0.41s
```

GREEN：

```
$ uv run pytest tests/unit/test_operation_ordering.py -q -W error
12 passed in 0.30s
$ uv run pytest tests -q -W error
362 passed, 23 skipped in 19.93s
```

commit：`af3d85d fix(ops): 取號失敗時先判定重複接受`

---

## 必修 4：`acquire_lease` 拒絕空白 owner

**改了什麼**

`operations.py` 的 `acquire_lease` 在 `ttl_seconds` 檢查旁加：

```python
if not owner.strip():
    raise PermanentError("lease owner must not be blank")
```

docstring 補「**空白 owner 一律拒絕**」，理由寫明：`release_lease` 拿 `owner=""` 當「已釋放」的
標記，空白 owner 寫下去等於一把誰都能立刻覆蓋、持有者自己也放不掉的租約。

**測試**：`test_a_blank_lease_owner_is_rejected_before_any_write` — `""`、`"  "`、`"\t\n"` 三個都要
`PermanentError` 且 `repository.items == {}`（一個 item 都不寫，與既有的 `ttl_seconds` 測試同形）。

**指令與輸出**

RED：

```
$ uv run pytest tests/unit/test_operation_ordering.py -q -W error
E           Failed: DID NOT RAISE <class 'training_kb.errors.PermanentError'>
FAILED ...::test_a_blank_lease_owner_is_rejected_before_any_write
1 failed, 12 passed in 0.32s
```

GREEN：

```
$ uv run pytest tests -q -W error
363 passed, 23 skipped in 19.60s
```

commit：`80edb43 fix(ops): 租約 owner 不得為空白`

---

## 必修 5：correction 迴圈要有公開入口

**改了什麼（程式）**

- `src/training_kb/writing/client.py`：`_generate_with_correction` →
  **`generate_validated_json`**，參數順序原封不動
  （`writer, system, user, schema, validate, *, operation_id, node`）。
  docstring 把「module-private 是刻意的／不跨模組 import」改成「**這是唯一合法的修正迴圈入口**：
  呼叫一次，不自己包重試、也不自己再組一次修正 prompt——『最多一次修正』這個上限只在這支函式裡成立」。
- `src/training_kb/writing/__init__.py`：re-export `generate_validated_json`，並加進 `__all__`。
- `src/training_kb/writing/validators.py` 的 docstring 內文參照同步改名。

**改了什麼（文件）**

- `docs/plan/unfinish/00A-共用契約與名詞.md` §6.5：
  - 介面表新增一列 `generate_validated_json`（canonical 簽名、owner **P18**、消費 **P39–P51**，
    備註寫明「唯一合法的修正迴圈入口，最多一次修正…呼叫端不得自己重試」）。
  - 「業務 validator」那列的「呼叫端一律只呼叫 `generate_json` 一次」改成
    「呼叫端一律只呼叫 **`generate_validated_json`** 一次」。
- `docs/plan/unfinish/18-Phase18-模型輸出業務驗證與有限重試.md`：
  - 第 111 行附近「前面的底線代表它是 module-private…不跨模組 import 它」整句改寫成
    「是**公開**的修正迴圈入口（由 `writing/__init__.py` re-export）：P39–P51 一律 import 它、呼叫一次」。
  - 第 99 行的簽名區塊同步改名。
  - 完成清單「correction loop（`_generate_with_correction`）是 module-private，沒有被跨模組 import」
    這一句已與裁決相反，改成「只有這一份實作，呼叫端一律 import 它、呼叫一次，沒有人自己再寫一遍或自己重試」。
  - 其餘純名稱出現處（§2 retry 分層、流程圖、TDD 腳本片段）一併改名，文件裡不留已不存在的符號。

**測試**

- `tests/unit/test_writing_validation.py`、`tests/integration/test_claude_validation.py`
  兩支呼叫端全部改用新名稱（共 9 處），續行縮排重新對齊。
- 新增 `test_the_correction_loop_is_the_packages_public_entry_point`：
  斷言 `"generate_validated_json" in writing.__all__` 且
  `writing.generate_validated_json is generate_validated_json`（鎖住 re-export，不只是改名）。

**指令與輸出**

RED：

```
$ uv run pytest tests/unit/test_writing_validation.py -q -W error
E   ImportError: cannot import name 'generate_validated_json' from 'training_kb.writing.client'
1 error in 0.35s
```

GREEN：

```
$ uv run pytest tests -q -W error
364 passed, 23 skipped in 19.36s
$ grep -rn "_generate_with_correction" src/ infra/ tests/ docs/plan/unfinish/
（無輸出）
```

commit：`2888b4f refactor(writing): 公開 generate_validated_json 修正迴圈入口`（含 00A 與 Phase 18 文件）

---

## 順手 A：`o2_report.py` 改用 `training_kb.content` 的版號函式

**改了什麼**

`infra/scripts/o2_report.py` 刪掉自己那兩支寬鬆實作（`make_version`／`version_number`），
改 `from training_kb.content import make_version_id, parse_version_id`；9 個呼叫點全部換名。
`allocate_stub` 內的「`current_version` → 版號加一」改成：

```python
current = tutorial.current_version
number = 0 if current is None else parse_version_id(current)[1]
version_id = make_version_id(slug, number + 1)
```

`parse_version_id` 有 round-trip 檢查，所以 `a@v01`（前導零）、`a@v１`（全形）這種
舊版 `version_number` 會讀成 1 的字串現在直接 `ValueError`；`make_version_id` 也擋掉 `number < 1`
與帶 `@`／`#` 的 slug。模組 docstring 的「字串直接組成 `<slug>@v<n>`」與 `allocate_stub` docstring
同步改成「版號字串一律走 `training_kb.content`，本檔不另寫一份」。

**測試**

`tests/integration/test_o2_cases.py` 新增 `test_the_script_reuses_contents_version_functions`：
斷言 `o2_report.make_version_id is make_version_id`、`o2_report.parse_version_id is parse_version_id`，
且 `not hasattr(o2_report, "make_version")`／`"version_number"`——直接鎖住「只有一份定義」。
行為回歸由既有的 `test_every_case_also_passes_offline`（moto，4 個案例）覆蓋 `allocate_stub` 新路徑。

**指令與輸出**

RED：

```
$ uv run pytest tests/integration/test_o2_cases.py -q -W error
E       AttributeError: module 'o2_report' has no attribute 'make_version_id'. Did you mean: 'make_version'?
FAILED ...::test_the_script_reuses_contents_version_functions
1 failed, 4 passed, 7 skipped in 1.66s
```

GREEN：

```
$ uv run pytest tests/integration/test_o2_cases.py tests/unit/test_operation_ordering.py -q -W error
18 passed, 7 skipped in 1.68s
$ uv run mypy src infra
Success: no issues found in 23 source files
```

commit：`304d527 refactor(infra): o2_report 改用 content 的版號函式`

---

## 順手 B：00A §6.5 的 trace node 敘述改字（不改程式）

原文（與實作不符）：

> 寫進 `CallTrace` 的 node 名一律取 `schema.get("$id", "model")`（P17 實作；沒有 `$id` 的裸 schema
> 也要能呼叫，不得寫成 `schema["$id"]`）。

改為：

> 寫進 `CallTrace` 的 node 名是**呼叫端傳入的必填 `node` 參數**，`generate_json` 原樣使用、不改寫；
> `schema.get("$id", "model")` 只用於 `inference_config` 的查表與解析錯誤訊息的預設名稱
> （沒有 `$id` 的裸 schema 也要能呼叫，不得寫成 `schema["$id"]`）。

依據：`writing/client.py` 的 `generate_json`（約 251–257 行）把呼叫端的 `node` 原樣往下傳給
`_converse`；`schema.get("$id", "model")` 只出現在 `_parse_schema_json` 的錯誤訊息與
`inference_config` 的查表。**程式未動。** 併入必修 5 的 commit `2888b4f`。

---

## 最終 gate

```
$ uv run pytest tests -q -W error
365 passed, 23 skipped in 19.40s

$ uv run ruff check src tests infra
All checks passed!

$ uv run mypy src infra
Success: no issues found in 23 source files

$ grep -rn "type: ignore" src/ infra/
（無輸出）
```

零 warning（`-W error` 下全綠）。`# type: ignore` 在 `src/` 與 `infra/` 完全沒有（本次也未新增）。
`tests/` 內有兩個既存的 `# type: ignore`（`tests/unit/test_operation_ordering.py:51`、`:141`，
記憶體 fake Repository 的 `arg-type`／`method-assign`），是 Phase 11 留下的、不在 mypy 的
`files` 範圍內，本次未動。

## commits

| commit | 主旨 |
|---|---|
| `c8f97c2` | `chore(core): 加入 py.typed 並讓 mypy 涵蓋 infra` |
| `0cf638c` | `fix(core): 實體時間一律正規化為 UTC 整秒` |
| `af3d85d` | `fix(ops): 取號失敗時先判定重複接受` |
| `80edb43` | `fix(ops): 租約 owner 不得為空白` |
| `2888b4f` | `refactor(writing): 公開 generate_validated_json 修正迴圈入口`（含 00A §6.5 兩處改字＋新增一列、Phase 18 文件） |
| `304d527` | `refactor(infra): o2_report 改用 content 的版號函式` |

每個 commit 都只 `git add` 自己改的檔、用 `git commit -m "..." -- <同一批檔案>`；
沒有 `git add -A`、沒有 push、沒有動 `docs/plan/report/` 下的檔案。

## 疑慮與待確認

1. **`docs/plan/unfinish/43-Phase43-Feedback類別判定.md` 的改動留在工作樹、未 commit。**
   它第 124 行寫「不包 Phase 18 的 module-private `_generate_with_correction`」，改名後這句
   同時有壞掉的符號與已失效的「module-private」說法，我改成「不走 Phase 18 的
   `generate_validated_json`」（決策本身不變：`CommentClassification` 仍然不走 correction）。
   但這個檔在 git 裡是**未追蹤**（`??`），是別人尚未提交的新檔，依 COMMON.md 不該由我 `git add`，
   所以只留在工作樹。請 controller 決定要不要隨該檔的原 owner 一起提交。
2. **必修 2 的 `aware()` 現在會拒絕微秒。** 全套 365 個測試沒有任何一支依賴微秒，但 P21 之後
   還沒實作的 Phase 若打算把 `datetime.now(UTC)`（含微秒）直接餵進實體，會在建模時就炸；
   正確做法是一律用 `clock.now_utc()`（已去微秒），這與 00A §3.5 本來就一致。
3. **O2 gate 狀態未改變。** 順手 A 只動了離線腳本的版號函式來源；O2 仍只認
   `tests/integration/test_o2_cases.py` 對真實 DynamoDB 跑出來的觀察值，本次沒有跑真實 AWS
   （未設 `TKB_RUN_AWS_INTEGRATION=1`），23 個 skip 全部維持原狀。
4. `uv.lock` 全程未變動，因此未進任何 commit。
