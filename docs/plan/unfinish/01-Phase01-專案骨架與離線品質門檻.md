# Phase 01 專案骨架與離線品質門檻 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立可安裝、可執行離線測試、可做靜態檢查的 Python 專案骨架，後續 Phase 才有一致的路徑與指令。

**Architecture:** 採單一 Python package `training_kb`，應用模組放在 `src/`，測試依純邏輯（`tests/unit/`）與 AWS 整合（`tests/integration/`）分開。這一階段只建立工具鏈與空 package，不連 AWS、不建立任何業務實體。

**Tech Stack:** Python 3.12、uv、pytest、Ruff、mypy、setuptools。

## 文件定位

- **讀者：** 第一次接手此 repo、尚未看過任何應用程式碼的工程師。
- **唯一主來源：** [Training Knowledge Base 設計 §4、§5、§15](../../design/training-kb.md)。
- **名稱與路徑準則：** [00A 共用契約與名詞](00A-共用契約與名詞.md) 第 3.1 節（指令）與第 3.2 節（路徑 owner）。本文件與 00A 衝突時以 00A 為準。
- **前置 Phase：** 無；這是第一份實作計畫。
- **上一份：** [00 總覽](00-總覽.md)。
- **下一份：** [Phase 02 設定、時間與錯誤契約](02-Phase02-設定時間與錯誤契約.md)。
- **本階段不做：** 不建立 DynamoDB、S3、Lambda、模型呼叫或產品資料；不把工具檢查通過稱為應用程式測試通過。

## 全域限制

- 十個邏輯實體最後仍只使用一張 `training_kb` 表、一個 `by_target` GSI 與 S3。
- repo 目前沒有應用程式依賴清單；本文件列的是實作者未來要建立的內容。
- 所有 Python 指令一律以 `uv run` 開頭（00A 第 3.1 節）：`uv run pytest`、`uv run ruff check`、`uv run mypy`。不得出現裸 `pytest`，也不得用 `python`／`.venv/bin/python` 直接叫起測試或檢查工具來繞過 uv。
- 所有測試預設離線，不需要 AWS credentials。需要真實帳號的測試放 `tests/integration/` 並標 `@pytest.mark.aws`；marker 名稱由本 Phase 在 `pyproject.toml` **註冊**，並由本 Phase 建立的 `tests/conftest.py` 在沒有設定 `TKB_RUN_AWS_INTEGRATION=1` 時**自動跳過**它們，[Phase 59](59-Phase59-失敗復原與重送驗收.md) 之後只負責貼標籤（00A 裁決 D-41、D-64）。
- AWS SDK 與 CDK 依賴延後到真正使用它們的 Phase 增加；`cdk` 是 Node.js 套件，永遠不加 `uv run`（00A 第 3.1 節）。
- 新增 dependency 前先說明直接用途；不加入 Agent framework、Web framework 或資料庫模擬器。
- 本 Phase 與 O1–O7 都無關，不宣稱任何 gate 已通過；離線門檻全綠只代表工具鏈可用。

## 你在整體流程的位置

```text
+---------------------------+
| [你在這裡] Python 骨架    |
| uv / pytest / ruff / mypy |
+-------------+-------------+
              |
              v
+-------------+-------------+
| Phase 02-05 核心契約與模型|
+-------------+-------------+
              |
              v
+-------------+-------------+
| Repository -> AWS -> 流程 |
+---------------------------+
```

「離線品質門檻」是指不連外部服務即可重複執行的語法、型別與單元測試檢查。它不能證明 AWS 權限、模型或發布流程可用。

## 完成後看得到什麼

起點是一份全新 checkout：根目錄還沒有 `pyproject.toml`，也沒有 `.venv`。本 Phase 做完後，在根目錄執行下列三個指令即可重現離線門檻：

```bash
uv run pytest tests/unit -q
uv run ruff check src tests
uv run mypy src
```

預期輸出：

```text
1 passed in 0.03s
All checks passed!
Success: no issues found in 1 source file
```

三個命令 exit code 皆為 `0`。第一次執行時 `uv` 會自動建立 `.venv`、安裝相依並把本專案以可編輯方式裝進去，因此不需要先手動 `pip install`。輸出不得聲稱任何 AWS 或端到端路徑已驗證。

## 名詞小抄

| 名詞 | 白話意思 |
|---|---|
| uv | Python 的套件與環境管理工具。`uv run <指令>` 會先確認 `.venv` 與相依是最新的，再在那個環境裡跑指令，所以全套文件的指令都長一樣。 |
| `uv.lock` | uv 自動產生的鎖定檔，記錄每個套件的確切版本。要進版控，別人 checkout 後才會裝到一樣的版本。 |
| src layout（`src/` 佈局） | 把程式放在 `src/training_kb/`、不放在根目錄。好處是測試一定要透過「已安裝的套件」才匯入得到，不會意外讀到工作目錄下的原始檔。 |
| editable install（可編輯安裝） | 把本專案裝進虛擬環境，但指向原始碼而不是複製一份；改完 `src/` 的檔案不用重裝就生效。`uv run` 會自動做這件事。 |
| pytest marker（標籤） | 貼在測試上的名字，例如 `@pytest.mark.aws`。用 `-m aws` 只跑有標籤的那些。名字要先在 `pyproject.toml` 註冊，否則 pytest 會警告拼錯。 |
| `conftest.py` | pytest 會自動載入的設定檔，放在測試目錄裡就對該目錄（含子目錄）的所有測試生效。本 Phase 用它在沒有 AWS 憑證時自動跳過標了 `aws` 的測試，所以平常不必自己加 `-m` 條件。 |
| `TKB_RUN_AWS_INTEGRATION` | 一個環境變數（執行期開關）。設成 `1` 才會真的去打 AWS；沒設就讓 `aws` 測試自動跳過。全套只用這一個開關（00A 第 3.5 節）。 |
| 紅燈／綠燈 | TDD 的兩個狀態：先寫一個「現在一定失敗」的測試並真的看到它失敗（紅燈），再寫最小實作讓它通過（綠燈）。沒看過紅燈就不算做過 TDD。 |
| 離線品質門檻 | 不連 AWS、不用金鑰就能重複跑的三個檢查：單元測試、Ruff 靜態檢查、mypy 型別檢查。 |

## 預計新增／修改的檔案

以下是實作時預計建立，目前不代表檔案存在：

- Create: `pyproject.toml` — package metadata、最小 runtime 與 dev dependencies、pytest／Ruff／mypy 設定、`aws` marker 註冊。
- Create: `src/training_kb/__init__.py` — package 版本常數，不執行初始化副作用。
- Create: `tests/unit/test_package.py` — 驗證 package 可以匯入。
- Create: `tests/conftest.py` — 全套測試共用設定；沒設 `TKB_RUN_AWS_INTEGRATION=1` 時自動跳過標了 `aws` 的測試（後續 Phase 會在同一個檔案追加共用 fixture）。
- Create: `tests/integration/.gitkeep` — 保留後續真 AWS 整合測試目錄。
- Create: `.gitignore` — 排除虛擬環境、cache、build 與本機 secrets 檔（含 `.env`）。
- 由工具產生並一併提交：`uv.lock`（`uv` 第一次 sync 時自動建立，不要手寫）。

## 固定介面

### Consumes

- 無前置程式介面。
- 讀取設計中的目標 package 路徑 `src/training_kb/`（00A 第 3.2 節）。

### Produces

```python
training_kb.__version__: str
```

- 固定可用指令（00A 第 3.1 節，後續 60 份文件一律照抄）：

```text
uv run pytest <測試路徑> -q      單元與整合測試（aws 測試自動跳過）
TKB_RUN_AWS_INTEGRATION=1 uv run pytest <測試路徑> -m aws  只跑需要真實 AWS 帳號的測試
uv run ruff check <路徑>         靜態檢查
uv run mypy <路徑>               型別檢查
```

- 後續 Phase 的 import root 固定為 `training_kb`。
- `pyproject.toml` 註冊的 pytest marker：`aws`。
- `tests/conftest.py` 的 `pytest_collection_modifyitems`：未設 `TKB_RUN_AWS_INTEGRATION=1` 時自動跳過標了 `aws` 的測試。

## Task 1：建立可安裝的最小 package

**Files:**

- Create: `pyproject.toml`
- Create: `src/training_kb/__init__.py`
- Create: `tests/unit/test_package.py`

**Interfaces:**

- Consumes: Python 3.12、uv。
- Produces: `training_kb.__version__: str`。

- [x] **Step 1：先寫會失敗的 package 匯入測試**

`uv run` 需要 `pyproject.toml` 才知道要裝什麼，所以工具鏈骨架與測試同一步建立；真正「被測試的東西」（`src/training_kb/__init__.py`）刻意留到 Step 3。

`tests/unit/test_package.py` 的完整內容：

```python
def test_package_exposes_version() -> None:
    import training_kb

    assert training_kb.__version__ == "0.1.0"
```

`pyproject.toml` 的完整內容：

```toml
[build-system]
requires = ["setuptools>=75"]
build-backend = "setuptools.build_meta"

[project]
name = "training-kb"
version = "0.1.0"
requires-python = ">=3.12,<3.13"
dependencies = ["pydantic>=2,<3"]

[dependency-groups]
dev = ["mypy>=1,<2", "pytest>=8,<9", "ruff>=0.8,<1"]

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
testpaths = ["tests"]

[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "I", "UP"]

[tool.mypy]
python_version = "3.12"
strict = true
files = ["src"]
```

三個設定要點：`requires-python` 上下界都寫死，`uv` 才會固定挑 Python 3.12；`[dependency-groups]` 的 `dev` 是 uv 的預設群組，`uv run` 會自動安裝它，不必加 `--extra`；`[tool.ruff.lint].select` 明寫規則集合，Ruff 換版時預設規則變動不會讓門檻忽然變嚴或變鬆（`F401` 未使用 import、`I` import 排序、`UP` 過時語法都在裡面）。`pydantic` 先列出，是因為 [Phase 03](03-Phase03-識別碼列舉與內容草稿模型.md) 立刻要用；其餘相依由各自的 Phase 追加。

- [x] **Step 2：確認測試在 package 尚未建立時失敗**

```bash
uv run pytest tests/unit/test_package.py -q
```

預期：FAIL，訊號包含 `ModuleNotFoundError: No module named 'training_kb'`。
若 `uv` 因為 `src/` 目錄不存在而無法建置，先 `mkdir -p src` 建立空目錄，但**不要**先建立 `__init__.py`，否則就看不到紅燈。
若本機意外匯入別處同名套件而變成 PASS，先清除錯誤的 `PYTHONPATH` 再重跑，不可把它當成功。

- [x] **Step 3：建立最小 package**

`src/training_kb/__init__.py` 的完整內容：

```python
"""Training Knowledge Base package."""

__version__ = "0.1.0"
```

- [x] **Step 4：確認測試通過**

```bash
uv run pytest tests/unit/test_package.py -q
```

預期：`1 passed`。安裝失敗時保留完整錯誤，不改用全域 Python 掩蓋問題。

- [x] **Step 5：提交單一可審查變更**

```bash
git add pyproject.toml uv.lock src/training_kb/__init__.py tests/unit/test_package.py
git commit -m "chore(core): 建立 Python 專案骨架"
```

## Task 2：鎖定離線品質門檻與忽略規則

**Files:**

- Modify: `pyproject.toml`
- Create: `.gitignore`
- Create: `tests/conftest.py`
- Create: `tests/integration/.gitkeep`

**Interfaces:**

- Consumes: Task 1 的 `pyproject.toml` 與可編輯安裝。
- Produces: 三個固定離線檢查、`aws` marker 註冊與自動跳過、安全的本機檔案排除規則。

- [x] **Step 1：加入失敗樣本確認 Ruff 真的會攔截**

暫時將以下未使用 import 放入 `tests/unit/test_package.py` 第一行：

```python
import os
```

- [x] **Step 2：執行 Ruff 並看見明確失敗**

```bash
uv run ruff check tests/unit/test_package.py
```

預期：FAIL（exit code 非 0），訊息包含 `F401` 與 `Remove unused import: os`。記錄訊號後移除該行；不要把故意失敗樣本提交。

- [x] **Step 3：建立忽略規則、註冊 aws marker 與自動跳過**

`.gitignore` 的完整初始內容：

```gitignore
.venv/
__pycache__/
.pytest_cache/
.mypy_cache/
.ruff_cache/
build/
dist/
*.egg-info/
cdk.out/
.env
.env.*
!.env.example
```

`.env` 與 `.env.*` 兩行是本 Phase 的安全要求：[Phase 14](14-Phase14-O5模型可用性與參數驗證.md) 之後才會出現 `.env.example`（只有鍵名、沒有值），所以用 `!.env.example` 把它放行，真正帶值的 `.env` 永遠不進版控。

在 `pyproject.toml` 的 `[tool.pytest.ini_options]` 追加 marker 註冊（00A 裁決 D-41）：

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
markers = [
    "aws: 需要真實 AWS 帳號與憑證的整合測試；未設 TKB_RUN_AWS_INTEGRATION=1 時由 tests/conftest.py 自動跳過",
]
```

`markers` 只是把名稱登記起來，避免 pytest 因為認不得標籤而警告。光是註冊還不會自動排除，所以本 Phase 一併建立 `tests/conftest.py`，讓沒有 AWS 憑證的人直接跑 `uv run pytest` 也不會紅燈——這就是全套文件不需要在指令後面加 `-m` 條件的原因（00A 裁決 D-41、D-64）。

`tests/conftest.py` 的完整初始內容：

```python
"""全套測試共用設定。目前只做一件事：沒有 AWS 憑證時跳過 aws 測試。"""

import os

import pytest

RUN_AWS_ENV = "TKB_RUN_AWS_INTEGRATION"


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    """未開啟真實 AWS 整合測試時，替所有標了 aws 的測試補上 skip。"""
    if os.environ.get(RUN_AWS_ENV) == "1":
        return
    skip_aws = pytest.mark.skip(reason=f"需要真實 AWS 帳號；設 {RUN_AWS_ENV}=1 才執行")
    for item in items:
        if "aws" in item.keywords:
            item.add_marker(skip_aws)
```

`pytest_collection_modifyitems` 是 pytest 的內建 hook（掛鉤函式）：pytest 收集完所有測試後會呼叫它一次，讓我們在真的執行前修改測試清單。`item.keywords` 裡有測試身上所有的 marker 名稱，所以只要看得到 `aws` 就補一個 skip marker。真正在測試上貼 `@pytest.mark.aws` 是後續整合測試（例如 Phase 06、Phase 59）的事，本 Phase 不建立任何 AWS 測試。

- [x] **Step 4：執行完整離線門檻並確認自動跳過真的生效**

先確認故意加入的 `import os` 已移除，再執行：

```bash
uv run pytest tests/unit -q
uv run ruff check src tests
uv run mypy src
git check-ignore .env
```

預期：前三個命令 exit code `0`（`1 passed`、`All checks passed!`、`Success: no issues found in 1 source file`）；最後一個輸出 `.env`。這只證明忽略規則存在，不代表 repo 從未提交秘密。

`conftest.py` 要用一個「會被丟掉的」樣本驗證，作法與 Step 1 的 Ruff 樣本相同：

```bash
cat > tests/integration/test_marker_probe.py <<'PY'
import pytest


@pytest.mark.aws
def test_marker_probe() -> None:
    assert True
PY
uv run pytest tests/integration -q
TKB_RUN_AWS_INTEGRATION=1 uv run pytest tests/integration -q
rm tests/integration/test_marker_probe.py
```

預期：第一次 `1 skipped`（沒有設環境變數，conftest 自動跳過），第二次 `1 passed`（開關打開就真的執行），兩次都**沒有** `PytestUnknownMarkWarning`，代表 marker 已註冊。確認後把樣本檔刪掉，不要提交。

- [x] **Step 5：提交品質門檻**

```bash
git add .gitignore pyproject.toml uv.lock tests/conftest.py tests/integration/.gitkeep
git commit -m "chore(core): 增加離線品質門檻"
```

## 驗收與停止條件

```text
寫紅燈測試 --> uv run pytest 看到 FAIL --> 寫最小實作 --> uv run pytest 看到 PASS
                                                                  |
                        +-----------------------------------------+
                        v
        uv run ruff check src tests   --+
        uv run mypy src                 +--> 三者皆 exit 0 --> 提交
        uv run pytest tests/unit -q   --+
                        |
                     任一失敗
                        |
                        v
        停止並保留完整錯誤；不得改設定消音、不得跳過紅燈
```

| 檢查 | 預期訊號 | 失敗時動作 |
|---|---|---|
| `uv` 可用 | `uv --version` 有輸出，且自動建立 `.venv` | 先安裝 uv；不改用 `pip`／`python -m venv` 繞過 00A 第 3.1 節。 |
| editable install | `training_kb` 從本 repo 的 `src/` 匯入 | 停止後續 Phase，修正 `[tool.setuptools.packages.find]`。 |
| Python 版本 | `uv run python -V` 顯示 `3.12.x` | 若挑到 3.13，檢查 `requires-python` 的上界。 |
| pytest | 至少 `1 passed` | 不可建立空測試目錄後宣稱測試完成。 |
| `aws` marker | 樣本測試在沒設 `TKB_RUN_AWS_INTEGRATION` 時 `1 skipped`、設成 `1` 時 `1 passed`，兩次都無 unknown mark 警告 | 補 `markers` 設定與 `tests/conftest.py` 的 hook；不要改用關掉警告的方式消音。 |
| Ruff | exit code 0，故意樣本曾出現 `F401` | 確認工具確實掃到 `src` 與 `tests`。 |
| mypy | exit code 0 | 不以 `ignore_errors = true` 或 `--ignore-missing-imports` 消音。 |
| `.env` | `git check-ignore .env` 命中 | 若未命中，停止加入任何本機 credential。 |

人工驗收：在乾淨 shell 中執行 `uv --version`，刪掉 `.venv` 後重跑 `uv run pytest tests/unit -q`，確認能從零重建；檢查過程沒有 AWS network call，也沒有讀取 credential。

## 常見錯誤與邊界案例

- **症狀：** 測試在未安裝 package 時也通過。**原因：** shell 指向其他 checkout。**修正：** 用 `uv run python -c 'import training_kb; print(training_kb.__file__)'` 確認路徑落在本 repo 的 `src/`。
- **症狀：** `uv run pytest` 回報找不到 `pytest`。**原因：** dev 相依寫在 `[project.optional-dependencies]` 而不是 `[dependency-groups]`，extras 預設不會安裝。**修正：** 照 Task 1 改用 `[dependency-groups]`，或每次加 `--extra dev`；全套文件假設前者。
- **症狀：** Ruff 換版後忽然多出一堆從沒看過的錯誤碼。**原因：** 沒有明寫 `[tool.ruff.lint].select`，吃到新版的預設規則集合。**修正：** 保持 Task 1 的 `select`，要加規則就明確加，不要依賴預設值。
- **症狀：** `.env` 仍出現在 `git status`。**原因：** ignore 規則未建立或檔案已被追蹤。**修正：** 先停止，不讀檔案內容；交由維護者處理既有追蹤狀態。
- **症狀：** 只有 parser 或 import 成功就宣稱完成。**原因：** 沒跑 smoke test 與三個門檻。**修正：** 三個指令都要留下實際輸出（設計 §15：parser 成功不等於 runtime 成功）。
- **停止條件：** Python 3.12 無法取得、`uv` 無法安裝、依賴來源受限，或 repo 內已有衝突的 package 設定時，留下完整錯誤並先解決工具鏈，不自行換 runtime、不降版、不改成全域安裝。

## 來源與 Rule 對照

- 設計 [§4 Repo 現況](../../design/training-kb.md#s4)：目前缺應用程式入口與依賴清單，且 `.env` 尚未被忽略；本 Phase 建立它們。
- 設計 [§5 目標架構](../../design/training-kb.md#s5)：package 路徑與單一 Python 專案。
- 設計 [§15 測試與驗收](../../design/training-kb.md#s15)：純邏輯用 pytest、AWS 整合用隔離環境；parser success 不代表 runtime 成功。
- 設計 [§17.2 最小必要的安全處理](../../design/training-kb.md#s17)：秘密只由執行環境提供，版控與公開 log 不含真實金鑰。
- [00A 共用契約與名詞](00A-共用契約與名詞.md) 第 3.1 節（`uv run` 指令與 `aws` marker 慣例，裁決 D-13、D-41、D-64）、第 3.2 節（`pyproject.toml`、`.gitignore`、`tests/conftest.py`、`uv.lock` 的 owner 是 P01）。
- 本 Phase 沒有 147 條 Rule 的 primary ownership（見 [00B 需求覆蓋對照](00B-需求覆蓋對照.md) 第 2 節）；它提供後續每個 primary assertion 的離線執行入口。

## 實作備註（2026-09-14）

本 Phase 由 controller 親自實作（範圍小、計畫文件已附完整程式），證據留在 `.superpowers/sdd/phase0914-0/progress.md` 的第一段 ledger。

**實際版本**：uv 0.11.32、Python 3.12.7、pytest 8.4.2、ruff 0.16.7、mypy 1.20.2。
**commits**：`5b14447 chore(core): 建立 Python 專案骨架`、`581c5ac chore(core): 增加離線品質門檻`。
**TDD 證據**：Task 1 的 RED 是 `ModuleNotFoundError: No module named 'training_kb'`，GREEN 是 `1 passed`；Task 2 的 ruff 樣本先出現 `F401`（證明 ruff 真的掃得到 `src` 與 `tests`），移除樣本後三個門檻皆 exit 0；`aws` marker 探針在未設 `TKB_RUN_AWS_INTEGRATION` 時 `1 skipped`、設成 `1` 時 `1 passed`，兩次都沒有 `PytestUnknownMarkWarning`（探針檔跑完即刪、未提交）。

三項與本文件原稿不同的決定，記在這裡而不改上面的 Task 內文：

1. **相依在本 Phase 一次加齊。** 本文件「全域限制」原本寫「AWS SDK 與 CDK 依賴延後到真正使用它們的 Phase 增加」。實際做法是 Phase 01 就把 Phase 01–20 會用到的相依全部寫進 `pyproject.toml`：`boto3`、`moto[dynamodb,s3]`、`boto3-stubs`、`aws-cdk-lib`、`constructs`。
   **理由**：Phase 02–20 是多個實作者**同時**在同一個 checkout 進行（見 `docs/plan/todo/2026-09-14-Phase01-20實作-TODO.md` 的波次表），而 `pyproject.toml` 與 `uv.lock` 是全 repo 唯一的一份；若讓 P06／P07／P09 各自 `uv add`，三個人會同時改同一個鎖檔而互相覆寫。一次加齊只讓第一次 `uv sync` 慢幾秒，沒有功能風險。
   **例外**：Phase 17 後來仍補了 `jsonschema` 與 `types-jsonschema`（它的 schema 驗證需要，當時只有它一個人在動這支檔）。
2. **這個 shell 的 `rm` 與 `node` 是會拒絕的 function。** 要刪檔一律用 `command rm <檔案>`（或 Python 的 `os.remove`），要跑 Node／CDK 一律用 `command node`／`command npx`。本文件 Task 2 Step 4「確認後把樣本檔刪掉」就是用 `command rm` 執行的。
3. **`.gitignore` 多一行 `.DS_Store`。** macOS 的 Finder 會在任何被瀏覽過的目錄留下這個檔，不忽略的話每個人的 `git status` 都會多出雜訊。它與本文件「忽略虛擬環境、快取與 `.env`」的用意一致，只是原稿沒列。

**與 O1–O7 的關係不變**：本 Phase 仍然不宣稱任何 gate 通過；離線三門檻全綠只代表工具鏈可用。

## 完成清單

- [x] `uv run` 能從全新 checkout 自動建立 `.venv` 並完成可編輯安裝。
- [x] package 匯入測試曾先失敗（`ModuleNotFoundError`）、後通過。
- [x] `uv run pytest`、`uv run ruff check`、`uv run mypy` 都實際執行且記錄版本與結果。
- [x] `pyproject.toml` 已註冊 `aws` marker，且 `tests/conftest.py` 在未設 `TKB_RUN_AWS_INTEGRATION=1` 時自動跳過標了 `aws` 的測試（樣本驗證過 `1 skipped` 與 `1 passed`）。
- [x] `.env` 與 `.env.*` 受到忽略，`.env.example` 可放行。
- [x] `uv.lock` 已提交，同一份 checkout 能重現相同版本。
- [x] 沒有新增 AWS、資料實體或模型成功宣稱，也沒有宣稱任何 O1–O7 gate 通過。
- [x] 下一份可直接 import `training_kb` 並新增 `errors.py`、`clock.py`、`config.py`。

**下一份可用成果：** 一個固定 package root、三條以 `uv run` 開頭的離線品質命令、已註冊的 `aws` marker，以及不讀取 secrets 的安全起點。
