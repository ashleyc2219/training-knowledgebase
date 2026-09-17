# Phase 01：專案骨架與開發環境

| 項目 | 內容 |
|---|---|
| 上一階段 | 無；這是第一份實作文件。先讀過 `00-總覽.md` |
| 下一階段 | Phase 02：領域模型與資料鍵（`02-Phase02-領域模型與資料鍵.md`） |
| 對應設計文件章節 | §4、§5、§14.3、§17.2（`docs/design/training-kb.md`） |
| 對應交付切片 | S0（設計文件第 16 節） |
| 預估時間 | 約 3 小時 |
| 做完會得到 | 一個 `uv run pytest` 會全部通過的 Python 專案骨架，`.env` 確定不會進 Git，門檻數字與錯誤分類都已就位 |

---

## 1. 這階段做完會得到什麼

設計文件第 4 節寫得很清楚：這個 repo 目前**沒有** `pyproject.toml`、沒有應用程式入口、沒有可執行的測試。所以這一階段是真的從零開始。

做完之後你會有：

1. 一個用 `uv` 管理的 Python 3.12 專案，`uv run pytest` 可以離線跑完並全部通過。
2. `src/training_kb/` 的套件骨架（含 `writing/`、`pipelines/`、`handlers/` 三個空子套件），之後 24 個階段都往這裡面填東西。
3. `.gitignore`，而且你**親手驗證過** `.env` 真的被忽略——設計文件第 2 節記錄了「本次 `git check-ignore .env` 未命中」這個事實，§17.2 要求在實作階段修正它，這件事在 Task 3 完成。同時有一份不含真值的 `.env.example` 清單。
4. `errors.py`：`TransientError`（可重試）與 `PermanentError`（不可重試）兩類錯誤，以及 `IngressError`、`ContentError`；之後 Step Functions 的 Retry／Catch 就靠這個分類。
5. `clock.py`：UTC 時間工具，把「所有時間一律 UTC」這條規則定死。
6. `config.py`：`Thresholds`（把設計文件散在各節的門檻數字集中一處）與 `Settings`／`load_settings()`。
7. 一個「標了 `@pytest.mark.aws` 的測試預設會被跳過」的機制，讓你在沒有 AWS 的情況下也能天天跑測試。

這一階段**沒有**建立任何 AWS 資源，也沒有花任何錢。

---

## 2. 它在整張地圖的位置

```text
基礎層          01 骨架 -> 02 模型與鍵 -> 03 Repository(本機) -> 04 AWS 基礎建設
                 ^^^^^                                                |
              ★ 你在這裡                                              |
AI 與內容層     05 Writing(Bedrock) -> 06 規則注入 -> 07 建立版本 -> 08 發布與退役 -> 09 圖譜查詢
                                                                                        |
接入層          10 Ingress 驗簽 -> 11 Rote 判定 -> 12 Rote Agent -------------------------+
                                                                                        |
流程層          13 Ticket Analysis -> 14 StepFunctions 上線 -> 15 Feedback/View 匯入 -> 16 Release Update
                                                                                        |
學習層          17 Review:REFINE -> 18 Review:候選規則+排程 -> 19 Analytics 指標 -> 20 規則驗證
                                                                                        |
展示與驗收層    21 Demo 種子資料 -> 22 靜態教學站 -> 23 Demo 控制台 -> 24 失敗復原驗收 -> 25 安全與當日準備
```

這一階段做出來的三個檔案（`errors.py`、`clock.py`、`config.py`）幾乎**每一個後面的階段都會 import**，所以名稱與簽名照文件寫，不要自己改。

---

## 3. 開始前檢查

下面六件事全部確認過再開始。每一項都給了驗證指令與「你應該看到什麼」。

**1) 你在正確的資料夾，而且 Git 可以用**

```bash
cd ~/AWS-Hackathon        # 換成你實際 clone 的位置
pwd && ls docs/design/training-kb.md && git --version
```

預期：`pwd` 的結尾是 `AWS-Hackathon`；`ls` 印出 `docs/design/training-kb.md`（沒有 `No such file`）；`git --version` 印出 `git version 2.x.y`。

**2) uv（Python 專案與套件管理工具）**

安裝：macOS／Linux 用 `curl -LsSf https://astral.sh/uv/install.sh | sh`；Windows PowerShell 用 `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`；有 Homebrew 也可以 `brew install uv`。裝完關掉終端機再重開一個（讓 PATH 生效）。

```bash
uv --version
```

預期：印出 `uv 0.9.x` 這種形式的版本號（版本會隨時間改變，有輸出就算成功）。

**3) Python 3.12**

不需要自己去官網裝，uv 可以幫你下載一份：

```bash
uv python install 3.12
uv python list
```

預期：`uv python list` 的輸出裡有一行含 `3.12`，而且**不是** `<download available>` 而是有實際路徑。

> 為什麼一定要 3.12？設計文件與這套實作文件用到 `StrEnum`（3.11 起）與 3.12 的型別寫法。版本不同會在 Phase 02 出錯。

**4) Node.js（現在先裝好，Phase 04 的 CDK CLI 會用到）**

CDK 的命令列工具是用 JavaScript 寫的，所以需要 Node.js。到 <https://nodejs.org/> 下載 LTS 版，或 `brew install node`。

```bash
node --version && npm --version
```

預期：`node --version` 印出 `v20.x.x` 或更新（v22、v24 都可以）；`npm --version` 有輸出。

**5) AWS CLI 與 `aws configure`（只設定，不建立任何資源）**

依 <https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html> 安裝 AWS CLI v2，`aws --version` 的開頭必須是 `aws-cli/2`（v1 太舊）。然後執行 `aws configure`，它會依序問四個問題：

```text
AWS Access Key ID [None]:      ← 貼上你的 Access Key ID
AWS Secret Access Key [None]:  ← 貼上你的 Secret Access Key
Default region name [None]:    ← 例如 us-east-1
Default output format [None]:  ← 輸入 json
```

> **安全提醒（設計文件 §17.2）**：金鑰會被寫到家目錄的 `~/.aws/credentials`，**不在這個 repo 裡**，所以不會被 commit。但你仍然**絕對不可以**把金鑰貼進專案裡的任何檔案，包含 `.env.example`。若你的帳號用 AWS IAM Identity Center（舊名 SSO），改用 `aws configure sso`，之後用 `aws sso login` 登入。

驗證：

```bash
aws sts get-caller-identity
```

預期：印出一段 JSON，含 `UserId`、`Account`、`Arn`。**這個指令只是查你是誰，不會建立、修改或刪除任何資源，也不會產生費用。** 若出現 `Unable to locate credentials`，代表 `aws configure` 沒設定成功，回去重做。

**6) Region 先不用決定**

`Default region name` 先隨便填一個（例如 `us-east-1`）沒關係。**真正要用哪一區，要等 Phase 04 用 `infra/scripts/check_models.py` 確認 Titan 與 Claude 在該區可不可以呼叫之後才決定**（這是設計文件第 18 節的 O5，本計劃選擇在 Phase 04 處理）。

---

## 4. 名詞小抄

| 名詞 | 白話解釋 | 在本階段哪裡用到 |
|---|---|---|
| uv | 很快的 Python 專案與套件管理工具；`uv run <指令>` 會自動用專案的虛擬環境跑 | Task 1 起全部 |
| `pyproject.toml` | Python 專案的設定檔：名稱、版本、依賴、pytest 與 ruff 的設定都在裡面 | Task 1 |
| 虛擬環境 `.venv/` | 只屬於這個專案的套件安裝位置，不污染系統 Python；`uv sync` 會自動建立 | Task 1 |
| src layout | 把套件放在 `src/` 底下的結構；測試一定是 import「安裝好的套件」，不會誤抓工作目錄的檔案 | Task 1、Task 2 |
| `__init__.py` | 有這個檔案的資料夾才是一個 Python 套件（package） | Task 1、Task 2 |
| pytest | Python 測試框架；自動找 `tests/` 底下 `test_*.py` 裡的 `test_*` 函式 | Task 1 起全部 |
| `assert` | Python 內建關鍵字：`assert x == 1` 不成立就讓測試失敗 | 全部測試 |
| marker | pytest 的標籤，例如 `@pytest.mark.aws`；可以用來挑要跑哪些測試 | Task 8 |
| `conftest.py` | pytest 自動載入的設定檔，放共用 fixture 與收集規則 | Task 8 |
| `parametrize` | pytest 的語法糖：同一個測試用不同輸入跑很多次 | Task 2 |
| ruff | 很快的 Python 檢查器與排版器 | Task 1、§7 |
| dataclass | Python 內建「只裝資料、不做驗證」的類別寫法 | Task 6、Task 7 |
| `field(default_factory=...)` | dataclass 裡「每個實例各自建一個新的預設物件」的寫法；可變預設值必須用它 | Task 7 |
| 例外（Exception）／繼承 | 出錯時丟出的物件；`class A(B)` 代表 A 是 B 的一種，`except B` 抓得到 A | Task 4 |
| tz-aware datetime | 帶時區資訊的時間物件；沒帶時區的叫 naive | Task 5 |
| ISO 8601 | 時間字串格式；本案統一寫成 `2026-08-01T00:00:00Z` | Task 5 |
| UTC | 世界協調時間；本案所有時間一律用它 | Task 5 |
| 環境變數 | 由作業系統或雲端執行環境傳給程式的設定值，本案全部用 `TKB_` 前綴 | Task 3、Task 7 |
| `.env` | 放本機祕密設定的檔案，**絕對不能進 Git** | Task 3 |
| `git check-ignore` | 問 Git「這個路徑有沒有被忽略」的指令 | Task 3 |
| boto3 / pydantic / moto | AWS 的 Python SDK／資料驗證套件／本機假裝 AWS 的套件；本階段只是先宣告依賴，Phase 02、03 才用 | Task 1 |

---

## 5. 設計說明

### 5.1 為什麼用 src layout

```text
AWS-Hackathon/
  pyproject.toml
  src/
    training_kb/          <-- 套件真正的位置
      __init__.py
  tests/
    unit/
      test_project.py     <-- 這裡寫 import training_kb
```

如果把 `training_kb/` 直接放在 repo 根目錄，執行 `pytest` 時 Python 會從「目前工作目錄」找到它，於是你測到的是**資料夾裡的原始碼**，不是「安裝起來之後長什麼樣」。src layout 逼你透過安裝（`uv sync` 會用可編輯模式把 `src/training_kb` 裝進 `.venv`）才 import 得到，Phase 14 打包進 Lambda 時才不會出現「本機好好的、上雲就 `ModuleNotFoundError`」。

### 5.2 設定值怎麼流進程式

```text
  .env（本機，被 .gitignore 忽略）      Lambda 的環境變數（Phase 14 設定）
    TKB_AWS_REGION=us-east-1              TKB_AWS_REGION=us-east-1
    TKB_TABLE_NAME=training_kb            TKB_TABLE_NAME=training_kb
    TKB_BUCKET_NAME=...                   TKB_BUCKET_NAME=...
            |                                        |
            +--------------------+-------------------+
                                 v
                      load_settings(env=None)
                      （測試時直接傳一個 dict 進去，不碰真實環境）
                                 |
              +------------------+-------------------+
              |                                      |
   少了必填值或值不是數字                        全部齊全
              |                                      |
              v                                      v
  PermanentError("缺少必要的環境變數：       Settings(
   TKB_BUCKET_NAME、TKB_GEN_MODEL_ID")         aws_region=..., table_name=...,
              |                                  gen_model_id=..., ...,
   一次列出全部缺哪些，不要讓人一個一個試        thresholds=Thresholds(...)  )
```

兩個重點：（1）**`load_settings()` 一次列出全部缺少的變數**，不要第一個缺就丟——新手最痛苦的體驗就是補一個、再錯一個；（2）**`Settings` 裡包著 `Thresholds`**，因為設計文件把門檻散在 §7.2（0.8、3）、§7.3（0.85、14、5）、§7.5（3.5、10、8、5）、§12.1（14 天）好幾節，如果讓每個模組自己寫 `0.85`，總有一天會有兩個地方不一致。

### 5.3 錯誤為什麼只分兩大類

```text
                        出事了
                          |
          +---------------+----------------+
          |                                |
  是網路、限流、逾時？                   其他（資料非法、業務驗證失敗）
          |                                |
          v                                v
   TransientError                    PermanentError
          |                                |
  Step Functions 的 Retry            Retry 不理它，直接被
  會重試（1 秒、2 秒，最多兩次）        Catch 導向失敗終點
                                           |
                        +------------------+------------------+
                        |                                     |
                  IngressError                          ContentError
              接入欄位不合法／缺值，                  教學內容驗證失敗：
              要把 fields 回報給提交者                五段不齊、步驟不是恰好
              （設計 §7.1 的「操作失敗」）             引用一個 Feature…
```

設計文件 §14.1 把失敗語意講得很細，但實作上只需要「要不要重試」這一個判斷，所以只做兩個基底類別、其餘用繼承細分；Phase 14 寫 ASL 時 `Retry` 的 `ErrorEquals` 只會列 `TransientError`。注意 `IngressError` 與 `ContentError` 都是 `PermanentError` 的子類別，`except PermanentError` 抓得到它們、`except TransientError` 抓不到，這是刻意的。

### 5.4 為什麼時間函式都吃 `now` 參數

設計文件 §7.3 的 recurring 是「當日加前 13 個 UTC 日期」，§12.1 的重開票窗口是 `[p, p+14 天)`，都跟「現在是幾點」有關。如果程式直接呼叫 `datetime.now()`，測試就只能在對的日子跑。所以共用約定是：**只有真正的入口（Lambda handler、CLI）才呼叫 `now_utc()`，其他所有函式都把 `now: datetime` 當參數收進來。** 這一階段只提供 `now_utc()`，但約定從現在開始生效。

### 5.5 本階段建立的目錄

```text
AWS-Hackathon/
  pyproject.toml         Task 1  專案設定、依賴、pytest 與 ruff 設定
  .python-version        Task 1  釘住 3.12
  .gitignore             Task 3  含 .env、.venv/、build/、cdk.out/、__pycache__/
  .env.example           Task 3  環境變數清單，不含真值
  .env                   Task 3  你自己建的本機真值檔；不進 Git
  src/
    training_kb/
      __init__.py        Task 1  套件入口，只放 __version__
      errors.py          Task 4  TransientError、PermanentError、IngressError、ContentError
      clock.py           Task 5  now_utc、to_iso、parse_iso、utc_date
      config.py          Task 6、7  Thresholds、Settings、load_settings
      writing/
        __init__.py      Task 2  空子套件（Phase 05、06 填）
      pipelines/
        __init__.py      Task 2  空子套件（Phase 13、16、17、18 填）
      handlers/
        __init__.py      Task 2  空子套件（Phase 14、19 填）
  tests/
    conftest.py          Task 8  aws marker 預設跳過
    unit/
      test_project.py        Task 1
      test_package_layout.py Task 2
      test_repo_hygiene.py   Task 3
      test_errors.py         Task 4
      test_clock.py          Task 5
      test_thresholds.py     Task 6
      test_settings.py       Task 7
      test_aws_marker.py     Task 8
    integration/
      .gitkeep           Task 2  先佔位；Phase 03 起放 moto 測試
```

`models.py`、`keys.py`、`repository.py` 等等**這一階段不建立**，留給對應的階段（見 §9）。

---

## 6. 工作項目

### Task 1：建立 uv 專案與第一個測試

**目的**：讓 `uv run pytest` 這個指令可以跑起來，並且有一個會通過的測試。

**檔案**：
- 新增：`pyproject.toml`、`.python-version`、`src/training_kb/__init__.py`
- 測試：`tests/unit/test_project.py`

**介面**：
- 消費：無（這是第一個階段）
- 產出：`training_kb.__version__ -> str`

- [ ] **步驟 0（只有這個 Task 有）：先讓 `uv run pytest` 能執行**

TDD 的前提是「跑得動測試」。第一個專案還沒有測試環境，所以要先做一次無法先寫測試的初始化。這是唯一的例外，Task 2 之後都從寫測試開始。

在 repo 根目錄執行：

```bash
uv python pin 3.12
mkdir -p src/training_kb tests/unit tests/integration
printf '"""Training Knowledge Base：把重複工單變成教學，並用回饋持續改善。"""\n' > src/training_kb/__init__.py
```

預期：`uv python pin 3.12` 印出 `Pinned `.python-version` to `3.12``。

接著建立 `pyproject.toml`，內容完整如下（直接整份貼上）：

```toml
[project]
name = "training-kb"
version = "0.1.0"
description = "Training Knowledge Base：把重複工單變成教學，從回饋改善教學，並在改版時只更新受影響的步驟"
readme = "README.md"
requires-python = ">=3.12,<3.13"
dependencies = [
    "boto3>=1.35",
    "pydantic>=2.7",
]

[dependency-groups]
dev = [
    "pytest>=8.0",
    "moto>=5.0",
    "ruff>=0.6",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/training_kb"]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-ra"
markers = [
    "aws: 需要真實 AWS 資源的測試；只有環境變數 TKB_RUN_AWS_TESTS=1 時才執行",
]

[tool.ruff]
line-length = 100
target-version = "py312"
src = ["src", "tests"]

[tool.ruff.lint]
select = ["E", "F", "W", "I"]

[tool.ruff.lint.isort]
known-first-party = ["training_kb"]
```

`pyproject.toml` 裡 `readme = "README.md"` 需要那個檔案存在，所以順手建一個：

```bash
printf '# Training Knowledge Base\n\n實作計劃見 `docs/plan/unfinish/00-總覽.md`。\n' > README.md
```

然後安裝依賴並確認 pytest 可以執行：

```bash
uv sync
uv run pytest --version
```

預期：`uv sync` 會印出 `Resolved N packages` 與 `Installed N packages` 兩行（N 是實際套件數），並在根目錄建立 `.venv/`；`uv run pytest --version` 印出 `pytest 8.x.y`。

> 你也可以改用 `uv add boto3 pydantic` 與 `uv add --dev pytest moto ruff` 讓 uv 自己把依賴寫進 `pyproject.toml`。本文件直接給完整檔案，是為了讓每個人的 `pyproject.toml` 長得一樣，之後排錯比較容易。

- [ ] **步驟 1：寫測試**

```python
# tests/unit/test_project.py
"""確認專案骨架可以被 import，而且有版本號。"""

import training_kb


def test_package_is_importable() -> None:
    assert training_kb.__name__ == "training_kb"


def test_package_has_a_non_empty_version() -> None:
    assert isinstance(training_kb.__version__, str)
    assert training_kb.__version__ != ""
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：`uv run pytest tests/unit/test_project.py -v`

預期：`1 failed, 1 passed`。失敗的是 `test_package_has_a_non_empty_version`，訊息是
`AttributeError: module 'training_kb' has no attribute '__version__'`。

為什麼會失敗：步驟 0 建立的 `__init__.py` 裡只有一行說明文字，還沒有 `__version__` 這個變數。

- [ ] **步驟 3：寫最少的程式讓測試通過**

```python
# src/training_kb/__init__.py
"""Training Knowledge Base：把重複工單變成教學，並用回饋持續改善。

設計文件：docs/design/training-kb.md
實作計劃：docs/plan/unfinish/00-總覽.md
"""

__version__ = "0.1.0"
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：`uv run pytest tests/unit/test_project.py -v`

預期：`2 passed`。

- [ ] **步驟 5：commit**

```bash
git add pyproject.toml .python-version README.md src/training_kb/__init__.py tests/unit/test_project.py
git commit -m "chore(project): 建立 uv 專案骨架與第一個測試"
```

---

### Task 2：建立 src layout 的子套件骨架

**目的**：先把 `writing/`、`pipelines/`、`handlers/` 三個子套件的空殼建好，之後的階段直接往裡面加檔案。

**檔案**：
- 新增：`src/training_kb/writing/__init__.py`、`src/training_kb/pipelines/__init__.py`、`src/training_kb/handlers/__init__.py`、`tests/integration/.gitkeep`
- 測試：`tests/unit/test_package_layout.py`

**介面**：
- 消費：`training_kb`（Task 1）
- 產出：可 import 的 `training_kb.writing`、`training_kb.pipelines`、`training_kb.handlers`

- [ ] **步驟 1：寫測試**

```python
# tests/unit/test_package_layout.py
"""確認共用約定裡的子套件都建好了（00-總覽.md §8 的目錄結構）。"""

import importlib

import pytest

EXPECTED_MODULES = [
    "training_kb",
    "training_kb.writing",
    "training_kb.pipelines",
    "training_kb.handlers",
]


@pytest.mark.parametrize("module_name", EXPECTED_MODULES)
def test_subpackage_is_importable(module_name: str) -> None:
    module = importlib.import_module(module_name)
    assert module.__name__ == module_name


def test_subpackages_live_under_src_layout() -> None:
    import training_kb

    path = training_kb.__file__ or ""
    assert path.replace("\\", "/").endswith("src/training_kb/__init__.py")
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：`uv run pytest tests/unit/test_package_layout.py -v`

預期：`3 failed, 2 passed`。三個失敗的訊息是
`ModuleNotFoundError: No module named 'training_kb.writing'`（以及 `pipelines`、`handlers`）。

為什麼會失敗：那三個資料夾還不存在。Python 要看到 `__init__.py` 才把資料夾當成套件。

- [ ] **步驟 3：寫最少的程式讓測試通過**

```bash
mkdir -p src/training_kb/writing src/training_kb/pipelines src/training_kb/handlers
touch tests/integration/.gitkeep
```

```python
# src/training_kb/writing/__init__.py
"""Bedrock 呼叫、輸出驗證與寫作規則注入。

client.py（Phase 05）、schemas.py（Phase 05）、prompts.py（Phase 05）、rules.py（Phase 06）
"""
```

```python
# src/training_kb/pipelines/__init__.py
"""三條 Step Functions 流程的 task 函式。

common.py 與 ticket.py（Phase 13）、release.py（Phase 16）、feedback.py（Phase 17、18）
"""
```

```python
# src/training_kb/handlers/__init__.py
"""Lambda 進入點。

webhook.py、import_.py、pipeline_task.py（Phase 14）、analytics.py（Phase 19）
"""
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：`uv run pytest tests/unit/test_package_layout.py -v`

預期：`5 passed`。

- [ ] **步驟 5：commit**

```bash
git add src/training_kb/writing src/training_kb/pipelines src/training_kb/handlers \
        tests/integration/.gitkeep tests/unit/test_package_layout.py
git commit -m "chore(project): 建立 src layout 子套件骨架"
```

---

### Task 3：`.gitignore` 與 `.env.example`

**目的**：確保 `.env` 永遠不會進 Git，並留下一張「要設哪些環境變數」的清單。

**檔案**：
- 新增：`.gitignore`、`.env.example`
- 測試：`tests/unit/test_repo_hygiene.py`

**介面**：
- 消費：無
- 產出：`.env.example` 定義的 `TKB_*` 變數名稱清單（Task 7 的 `load_settings()` 會讀同一批名稱；Phase 04 會把確認過的模型 ID 填進 `.env`）

> 對應設計文件第 2 節的觀察：「prompt 說 `.env` 已忽略 / 本次 `git check-ignore .env` 未命中，不能宣稱已受保護」，以及 §17.2 的「目前 `.env` 尚未被忽略的事實需在實作階段修正」。這個 Task 就是修正它。

- [ ] **步驟 1：寫測試**

```python
# tests/unit/test_repo_hygiene.py
"""檢查 repo 的基本衛生：.gitignore 有擋住祕密檔，.env.example 有清單但沒有真值。"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

REQUIRED_IGNORE_ENTRIES = [
    ".env",
    ".venv/",
    "build/",
    "cdk.out/",
    "__pycache__/",
]

REQUIRED_ENV_KEYS = {
    "TKB_AWS_REGION",
    "TKB_TABLE_NAME",
    "TKB_BUCKET_NAME",
    "TKB_PROJECT_ID",
    "TKB_EMBED_MODEL_ID",
    "TKB_EMBED_DIMENSIONS",
    "TKB_GEN_MODEL_ID",
    "TKB_GITHUB_WEBHOOK_SECRET",
}


def _lines(path: Path) -> list[str]:
    return [line.strip() for line in path.read_text(encoding="utf-8").splitlines()]


def test_gitignore_exists_and_covers_required_entries() -> None:
    gitignore = REPO_ROOT / ".gitignore"
    assert gitignore.is_file(), "repo 根目錄必須有 .gitignore"
    entries = set(_lines(gitignore))
    missing = [item for item in REQUIRED_IGNORE_ENTRIES if item not in entries]
    assert missing == [], f".gitignore 缺少這些項目：{missing}"


def test_env_example_lists_every_required_key() -> None:
    example = REPO_ROOT / ".env.example"
    assert example.is_file(), "repo 根目錄必須有 .env.example"
    keys = {
        line.split("=", 1)[0].strip()
        for line in _lines(example)
        if line and not line.startswith("#") and "=" in line
    }
    missing = sorted(REQUIRED_ENV_KEYS - keys)
    assert missing == [], f".env.example 缺少這些變數：{missing}"


def test_env_example_contains_no_real_credentials() -> None:
    text = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
    assert "AKIA" not in text, "不可以把 AWS Access Key 放進範本檔"
    assert "aws_secret_access_key" not in text.lower()
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：`uv run pytest tests/unit/test_repo_hygiene.py -v`

預期：`3 failed`。第一個失敗訊息是 `AssertionError: repo 根目錄必須有 .gitignore`，第二、三個是
`FileNotFoundError` 或 `AssertionError: repo 根目錄必須有 .env.example`。

為什麼會失敗：這兩個檔案都還不存在。

- [ ] **步驟 3：寫最少的程式讓測試通過**

`.gitignore`（完整內容）：

```gitignore
# --- Python ---
__pycache__/
*.py[cod]
.venv/
.pytest_cache/
.ruff_cache/
*.egg-info/

# --- 環境與祕密 ---
# 設計文件 §17.2：webhook secret 只由執行環境提供，不進 Git、頁面、種子檔與公開 log
.env
.env.*
!.env.example

# --- 建置與部署產物 ---
build/
dist/
cdk.out/

# --- 編輯器與作業系統 ---
.DS_Store
.idea/
.vscode/
```

`.env.example`（完整內容）：

```bash
# 這是範本。複製成 .env 之後再填真值：cp .env.example .env
# .env 已被 .gitignore 忽略，不會進 Git。
# 這個檔案本身不可以放任何真實金鑰或 secret。

# --- AWS 基本設定（Phase 04 建立資源後填入實際值）---
TKB_AWS_REGION=us-east-1
TKB_TABLE_NAME=training_kb
TKB_BUCKET_NAME=training-kb-content-CHANGE-ME
TKB_PROJECT_ID=demo-project

# --- Bedrock 模型 ---
TKB_EMBED_MODEL_ID=amazon.titan-embed-text-v2:0
TKB_EMBED_DIMENSIONS=1024
# 生成模型 ID 由 Phase 04 用 infra/scripts/check_models.py 實際確認後才填，
# 這裡故意留空，不填猜測值（本計劃選擇，對應設計文件第 18 節的 O5）。
TKB_GEN_MODEL_ID=

# --- GitHub webhook（Phase 10 使用；本機測試可先填任意字串）---
TKB_GITHUB_WEBHOOK_SECRET=

# --- 選用：呼叫與生成參數；不填就用 config.py 的預設值（設計文件 §14.3）---
# TKB_BEDROCK_CONNECT_TIMEOUT_S=2.0
# TKB_BEDROCK_READ_TIMEOUT_S=30.0
# TKB_GEN_MAX_TOKENS_JUDGEMENT=512
# TKB_GEN_MAX_TOKENS_WRITING=2048
# TKB_GEN_TEMPERATURE=0.1

# --- 選用：要跑需要真實 AWS 的測試時才設成 1（見 Task 8）---
# TKB_RUN_AWS_TESTS=1
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：`uv run pytest tests/unit/test_repo_hygiene.py -v`

預期：`3 passed`。

接著做**手動驗證**（這一步很重要，測試檢查不到 Git 的實際行為）：

```bash
cp .env.example .env
git check-ignore -v .env
git status --short
```

預期：

- `git check-ignore -v .env` 印出 `.gitignore:11:.env	.env` 這種形式的一行（行號可能不同），而且指令的離開碼是 0。
- `git status --short` 的輸出裡**看不到** `.env`，但看得到 `.gitignore` 與 `.env.example`。

如果 `git check-ignore -v .env` 什麼都沒印（離開碼 1），代表 `.env` 之前已經被 `git add` 追蹤過了——**已追蹤的檔案不受 `.gitignore` 影響**。解法見 §8 的第 4 題。

- [ ] **步驟 5：commit**

```bash
git add .gitignore .env.example tests/unit/test_repo_hygiene.py
git commit -m "chore(repo): 加入 .gitignore 與 .env.example 並確認 .env 被忽略"
```

---

### Task 4：`errors.py`

**目的**：定義「可重試」與「不可重試」兩類錯誤，之後 Step Functions 的 Retry／Catch 靠它分流。

**檔案**：
- 新增：`src/training_kb/errors.py`
- 測試：`tests/unit/test_errors.py`

**介面**：
- 消費：無
- 產出：
  - `class TransientError(Exception)`
  - `class PermanentError(Exception)`
  - `class IngressError(PermanentError).__init__(message: str, fields: list[str] | None = None)`，屬性 `message: str`、`fields: list[str]`
  - `class ContentError(PermanentError)`

> 與 `00-總覽.md` §9.2 的差異：`fields` 加了預設值 `None`（等同空清單），讓只想給訊息的呼叫端不用寫 `[]`。用 `IngressError("...", ["author"])` 呼叫的寫法完全不變。

- [ ] **步驟 1：寫測試**

```python
# tests/unit/test_errors.py
"""錯誤分類：設計文件 §14.1、§14.2。"""

import pytest

from training_kb.errors import ContentError, IngressError, PermanentError, TransientError


def test_transient_and_permanent_are_independent() -> None:
    assert issubclass(TransientError, Exception)
    assert issubclass(PermanentError, Exception)
    assert not issubclass(TransientError, PermanentError)
    assert not issubclass(PermanentError, TransientError)


def test_ingress_error_is_permanent_and_keeps_invalid_fields() -> None:
    err = IngressError("必填欄位缺少", ["author", "ts"])
    assert isinstance(err, PermanentError)
    assert err.fields == ["author", "ts"]
    assert err.message == "必填欄位缺少"
    assert "必填欄位缺少" in str(err)


def test_ingress_error_fields_default_to_empty_list() -> None:
    assert IngressError("格式錯誤").fields == []


def test_ingress_error_copies_the_field_list() -> None:
    original = ["rating"]
    err = IngressError("rating 不在 1..5", original)
    original.append("user")
    assert err.fields == ["rating"]


def test_content_error_is_permanent() -> None:
    assert issubclass(ContentError, PermanentError)
    with pytest.raises(PermanentError):
        raise ContentError("五段內容不齊")


def test_permanent_error_is_not_caught_by_transient_handler() -> None:
    with pytest.raises(ContentError):
        try:
            raise ContentError("步驟引用了兩個 Feature")
        except TransientError:  # pragma: no cover - 這裡本來就不該抓到
            pytest.fail("PermanentError 不應該被 TransientError 的 except 抓到")
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：`uv run pytest tests/unit/test_errors.py -v`

預期：收集階段就報錯，訊息是
`ModuleNotFoundError: No module named 'training_kb.errors'`，結果顯示 `1 error`。

為什麼會失敗：`errors.py` 還不存在，`import` 那一行就掛了，所以整個檔案的測試都跑不起來。

- [ ] **步驟 3：寫最少的程式讓測試通過**

```python
# src/training_kb/errors.py
"""training_kb 的錯誤分類。

設計文件 §14.1、§14.2：
- 暫時性失敗（網路、限流、逾時）值得重試；
- 永久性失敗（資料非法、業務驗證失敗）重試也不會變成功。

Phase 14 的 ASL 只會把 TransientError 列進 Retry 的 ErrorEquals；
PermanentError 直接交給 Catch 導向失敗終點。
"""


class TransientError(Exception):
    """暫時性失敗：網路、限流、逾時。值得重試。"""


class PermanentError(Exception):
    """永久性失敗：資料非法、業務驗證失敗。重試不會變成功。"""


class IngressError(PermanentError):
    """接入驗證失敗，對應規格的「操作失敗」（設計文件 §7.1、§14.1）。

    fields 是不合法或缺少的欄位名稱，必須原樣回報給提交者，讓他可以修正後重送。
    """

    def __init__(self, message: str, fields: list[str] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.fields = list(fields) if fields else []


class ContentError(PermanentError):
    """教學內容驗證失敗。

    例如：五段內容不齊、步驟不是恰好引用一個既有 Feature、步驟型態不在
    click_ui / input / read 之中（設計文件 §7.3、§7.6）。
    """
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：`uv run pytest tests/unit/test_errors.py -v`

預期：`6 passed`。

- [ ] **步驟 5：commit**

```bash
git add src/training_kb/errors.py tests/unit/test_errors.py
git commit -m "feat(errors): 定義暫時性與永久性錯誤分類"
```

---

### Task 5：`clock.py`

**目的**：把「所有時間一律 UTC、存成 `2026-08-01T00:00:00Z`」這條共用約定變成程式。

**檔案**：
- 新增：`src/training_kb/clock.py`
- 測試：`tests/unit/test_clock.py`

**介面**：
- 消費：無
- 產出：
  - `now_utc() -> datetime`
  - `to_iso(dt: datetime) -> str`
  - `parse_iso(s: str) -> datetime`
  - `utc_date(dt: datetime) -> date`

- [ ] **步驟 1：寫測試**

```python
# tests/unit/test_clock.py
"""UTC 時間工具：設計文件 §12.1、§14.3 與共用約定「一律 UTC、tz-aware」。"""

from datetime import date, datetime, timedelta, timezone

import pytest

from training_kb.clock import now_utc, parse_iso, to_iso, utc_date


def test_now_utc_is_timezone_aware_and_utc() -> None:
    now = now_utc()
    assert now.tzinfo is not None
    assert now.utcoffset() == timedelta(0)


def test_to_iso_uses_the_z_suffix() -> None:
    dt = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
    assert to_iso(dt) == "2026-08-01T00:00:00Z"


def test_to_iso_drops_microseconds() -> None:
    dt = datetime(2026, 8, 1, 9, 30, 15, 123456, tzinfo=timezone.utc)
    assert to_iso(dt) == "2026-08-01T09:30:15Z"


def test_to_iso_converts_other_offsets_to_utc() -> None:
    taipei = timezone(timedelta(hours=8))
    dt = datetime(2026, 8, 1, 8, 0, 0, tzinfo=taipei)
    assert to_iso(dt) == "2026-08-01T00:00:00Z"


def test_to_iso_rejects_naive_datetime() -> None:
    with pytest.raises(ValueError):
        to_iso(datetime(2026, 8, 1, 0, 0, 0))


def test_parse_iso_accepts_z_suffix() -> None:
    assert parse_iso("2026-08-01T00:00:00Z") == datetime(2026, 8, 1, tzinfo=timezone.utc)


def test_parse_iso_accepts_explicit_offset() -> None:
    assert parse_iso("2026-08-01T08:00:00+08:00") == datetime(2026, 8, 1, tzinfo=timezone.utc)


def test_parse_iso_rejects_a_string_without_timezone() -> None:
    with pytest.raises(ValueError):
        parse_iso("2026-08-01T00:00:00")


def test_round_trip_keeps_the_same_instant() -> None:
    text = "2026-08-20T00:00:00Z"
    assert to_iso(parse_iso(text)) == text


def test_utc_date_uses_the_utc_day_not_the_local_day() -> None:
    # 台北時間 2026-08-02 07:00 其實是 UTC 2026-08-01 23:00，UTC 日期仍然是 8/1。
    taipei = timezone(timedelta(hours=8))
    dt = datetime(2026, 8, 2, 7, 0, 0, tzinfo=taipei)
    assert utc_date(dt) == date(2026, 8, 1)
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：`uv run pytest tests/unit/test_clock.py -v`

預期：`1 error`，訊息是 `ModuleNotFoundError: No module named 'training_kb.clock'`。

為什麼會失敗：`clock.py` 還不存在。

- [ ] **步驟 3：寫最少的程式讓測試通過**

```python
# src/training_kb/clock.py
"""UTC 時間工具。

共用約定（00-總覽.md §7）：
- 一律 UTC、tz-aware datetime；
- 儲存成 ISO 8601 字串，固定寫法 "2026-08-01T00:00:00Z"；
- 只有真正的入口（Lambda handler、CLI）才呼叫 now_utc()，
  其餘所有函式都把 now: datetime 當參數收進來，測試才能指定固定時間。
"""

from datetime import date, datetime, timezone

ISO_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


def now_utc() -> datetime:
    """現在時間，帶 UTC 時區。"""
    return datetime.now(timezone.utc)


def _as_utc(dt: datetime) -> datetime:
    """檢查是 tz-aware 並轉成 UTC；naive datetime 直接拒絕。"""
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError(f"時間必須帶時區（tz-aware），收到沒有時區的值：{dt!r}")
    return dt.astimezone(timezone.utc)


def to_iso(dt: datetime) -> str:
    """轉成 "2026-08-01T00:00:00Z"；秒以下捨去，其他時區先換算成 UTC。"""
    return _as_utc(dt).strftime(ISO_FORMAT)


def parse_iso(s: str) -> datetime:
    """把 ISO 8601 字串轉回 tz-aware 的 UTC datetime；"Z" 與 "+00:00" 都接受。"""
    text = s.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    return _as_utc(datetime.fromisoformat(text))


def utc_date(dt: datetime) -> date:
    """取這個時間點的 UTC 日期。

    設計文件 §7.3 的 recurring 窗口是「Ticket.ts 的 UTC 日期，當日加前 13 個日期」，
    必須用 UTC 日界線，不能用本機時區。
    """
    return _as_utc(dt).date()
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：`uv run pytest tests/unit/test_clock.py -v`

預期：`10 passed`。

- [ ] **步驟 5：commit**

```bash
git add src/training_kb/clock.py tests/unit/test_clock.py
git commit -m "feat(clock): 加入 UTC 時間工具"
```

---

### Task 6：`config.py` 的 `Thresholds`

**目的**：把設計文件散在各節的門檻數字集中到一個 dataclass，避免不同模組寫出不一致的 0.85。

**檔案**：
- 新增：`src/training_kb/config.py`
- 測試：`tests/unit/test_thresholds.py`

**介面**：
- 消費：無
- 產出：`@dataclass class Thresholds`，12 個欄位與預設值

- [ ] **步驟 1：寫測試**

```python
# tests/unit/test_thresholds.py
"""門檻數字必須跟設計文件一致，而且只有這一個來源。"""

from training_kb.config import Thresholds


def test_defaults_match_the_design_document() -> None:
    t = Thresholds()
    assert t.cosine_cluster == 0.85  # §7.3 工單分群
    assert t.cosine_feature == 0.85  # §7.4 Feature 語意搜尋
    assert t.jaccard_replay == 0.8  # §7.2 Rote 第二層
    assert t.proc_min_success == 3  # §7.2 可重放的最少成功數
    assert t.proc_max_consecutive_fail == 3  # §7.2 連續失敗達此數退役
    assert t.recurring_days == 14  # §7.3 當日加前 13 個 UTC 日期
    assert t.recurring_min_tickets == 5  # §7.3
    assert t.weak_avg_below == 3.5  # §7.5 弱教學平均評分門檻
    assert t.weak_min_feedback_formal == 10  # §7.5 正式門檻
    assert t.weak_min_feedback_demo == 8  # §7.5 Demo 隔離門檻（F20）
    assert t.category_min_count == 5  # §7.5 同類回饋與 candidate 提出
    assert t.reopen_window_days == 14  # §12.1 重開票窗口 [p, p+14 天)


def test_thresholds_can_be_overridden_without_touching_the_others() -> None:
    t = Thresholds(recurring_min_tickets=2)
    assert t.recurring_min_tickets == 2
    assert t.cosine_cluster == 0.85


def test_two_default_instances_are_equal() -> None:
    assert Thresholds() == Thresholds()
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：`uv run pytest tests/unit/test_thresholds.py -v`

預期：`1 error`，訊息是 `ModuleNotFoundError: No module named 'training_kb.config'`。

- [ ] **步驟 3：寫最少的程式讓測試通過**

```python
# src/training_kb/config.py
"""執行設定與門檻常數。

門檻數字的唯一來源。設計文件把它們散在 §7.2、§7.3、§7.5、§12.1，
集中在這裡是為了避免兩個模組各寫一個 0.85 卻不一致。
測試要換門檻時，直接建一個改過的 Thresholds 傳進去，不要改這裡的預設值。
"""

from dataclasses import dataclass


@dataclass
class Thresholds:
    """全部業務門檻。預設值對應設計文件，不要隨意調整。"""

    cosine_cluster: float = 0.85  # §7.3：Ticket 與群中心的同群門檻
    cosine_feature: float = 0.85  # §7.4：Feature 語意搜尋最低相似度
    jaccard_replay: float = 0.8  # §7.2：Rote 第二層的 key 重疊門檻
    proc_min_success: int = 3  # §7.2：PROC 可重放的最少成功數
    proc_max_consecutive_fail: int = 3  # §7.2：連續失敗達此數就 retired
    recurring_days: int = 14  # §7.3：當日 + 前 13 個 UTC 日期
    recurring_min_tickets: int = 5  # §7.3：同群至少幾筆才算 recurring
    weak_avg_below: float = 3.5  # §7.5：弱教學的平均評分上限（嚴格小於）
    weak_min_feedback_formal: int = 10  # §7.5：正式模式的最少回饋數
    weak_min_feedback_demo: int = 8  # §7.5：Demo 隔離模式的最少回饋數（F20）
    category_min_count: int = 5  # §7.5：同版同類回饋數，提 candidate 也用這個
    reopen_window_days: int = 14  # §12.1：重開票窗口 [p, p + 14 天)
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：`uv run pytest tests/unit/test_thresholds.py -v`

預期：`3 passed`。

- [ ] **步驟 5：commit**

```bash
git add src/training_kb/config.py tests/unit/test_thresholds.py
git commit -m "feat(config): 加入門檻常數 Thresholds"
```

---

### Task 7：`Settings` 與 `load_settings()`

**目的**：從 `TKB_*` 環境變數讀出執行設定；缺值時一次列出全部缺哪些。

**檔案**：
- 修改：`src/training_kb/config.py`
- 測試：`tests/unit/test_settings.py`

**介面**：
- 消費：`training_kb.errors.PermanentError`（Task 4）、`training_kb.config.Thresholds`（Task 6）
- 產出：
  - `@dataclass class Settings`（8 個必填欄位 + 5 個有預設值的欄位 + `thresholds`）
  - `REQUIRED_KEYS: tuple[str, ...]`（新增項目，不在 `00-總覽.md` §9.2；讓測試與 `.env.example` 可以對照同一份清單）
  - `load_settings(env: Mapping[str, str] | None = None) -> Settings`

- [ ] **步驟 1：寫測試**

```python
# tests/unit/test_settings.py
"""load_settings()：從 TKB_* 環境變數讀設定；缺值一次列完。"""

import pytest

from training_kb.config import REQUIRED_KEYS, Settings, Thresholds, load_settings
from training_kb.errors import PermanentError

FULL_ENV = {
    "TKB_AWS_REGION": "us-east-1",
    "TKB_TABLE_NAME": "training_kb",
    "TKB_BUCKET_NAME": "training-kb-content-demo-001",
    "TKB_PROJECT_ID": "demo-project",
    "TKB_EMBED_MODEL_ID": "amazon.titan-embed-text-v2:0",
    "TKB_EMBED_DIMENSIONS": "1024",
    # 下面這個值在 Phase 04 用 check_models.py 確認之前只是佔位字串。
    "TKB_GEN_MODEL_ID": "placeholder-claude-model-id",
    "TKB_GITHUB_WEBHOOK_SECRET": "local-test-secret",
}


def test_required_keys_match_the_env_example_contract() -> None:
    assert set(REQUIRED_KEYS) == set(FULL_ENV)


def test_load_settings_reads_every_required_value() -> None:
    s = load_settings(FULL_ENV)
    assert s.aws_region == "us-east-1"
    assert s.table_name == "training_kb"
    assert s.bucket_name == "training-kb-content-demo-001"
    assert s.project_id == "demo-project"
    assert s.embed_model_id == "amazon.titan-embed-text-v2:0"
    assert s.embed_dimensions == 1024
    assert s.gen_model_id == "placeholder-claude-model-id"
    assert s.github_webhook_secret == "local-test-secret"


def test_load_settings_uses_the_documented_defaults() -> None:
    s = load_settings(FULL_ENV)
    assert s.bedrock_connect_timeout_s == 2.0  # 設計 §14.3
    assert s.bedrock_read_timeout_s == 30.0  # 設計 §14.3
    assert s.gen_max_tokens_judgement == 512  # 設計 §14.3
    assert s.gen_max_tokens_writing == 2048  # 設計 §14.3
    assert s.gen_temperature == 0.1  # 設計 §14.3
    assert s.thresholds == Thresholds()


def test_optional_values_can_be_overridden() -> None:
    env = dict(FULL_ENV, TKB_GEN_TEMPERATURE="0.0", TKB_BEDROCK_READ_TIMEOUT_S="45")
    s = load_settings(env)
    assert s.gen_temperature == 0.0
    assert s.bedrock_read_timeout_s == 45.0


def test_missing_keys_are_all_listed_in_one_error() -> None:
    env = dict(FULL_ENV)
    del env["TKB_BUCKET_NAME"]
    del env["TKB_GEN_MODEL_ID"]
    with pytest.raises(PermanentError) as exc:
        load_settings(env)
    message = str(exc.value)
    assert "TKB_BUCKET_NAME" in message
    assert "TKB_GEN_MODEL_ID" in message


def test_empty_string_counts_as_missing() -> None:
    env = dict(FULL_ENV, TKB_GEN_MODEL_ID="")
    with pytest.raises(PermanentError) as exc:
        load_settings(env)
    assert "TKB_GEN_MODEL_ID" in str(exc.value)


def test_non_numeric_value_is_rejected_with_the_key_name() -> None:
    env = dict(FULL_ENV, TKB_EMBED_DIMENSIONS="一千零二十四")
    with pytest.raises(PermanentError) as exc:
        load_settings(env)
    assert "TKB_EMBED_DIMENSIONS" in str(exc.value)


def test_whitespace_around_values_is_trimmed() -> None:
    env = dict(FULL_ENV, TKB_AWS_REGION="  us-west-2\n")
    assert load_settings(env).aws_region == "us-west-2"


def test_settings_can_be_built_directly_in_tests() -> None:
    s = Settings(
        aws_region="us-east-1",
        table_name="training_kb",
        bucket_name="bucket",
        project_id="demo-project",
        embed_model_id="amazon.titan-embed-text-v2:0",
        embed_dimensions=1024,
        gen_model_id="placeholder-claude-model-id",
        github_webhook_secret="secret",
    )
    assert s.thresholds.cosine_cluster == 0.85
    assert s.gen_max_tokens_writing == 2048
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：`uv run pytest tests/unit/test_settings.py -v`

預期：`1 error`，訊息是
`ImportError: cannot import name 'REQUIRED_KEYS' from 'training_kb.config'`。

為什麼會失敗：`config.py` 目前只有 `Thresholds`，還沒有 `Settings`、`REQUIRED_KEYS` 與 `load_settings`。

- [ ] **步驟 3：寫最少的程式讓測試通過**

把 `src/training_kb/config.py` 換成下面這份完整內容（包含 Task 6 已經寫好的 `Thresholds`）：

```python
# src/training_kb/config.py
"""執行設定與門檻常數。

門檻數字的唯一來源。設計文件把它們散在 §7.2、§7.3、§7.5、§12.1，
集中在這裡是為了避免兩個模組各寫一個 0.85 卻不一致。
測試要換門檻時，直接建一個改過的 Thresholds 傳進去，不要改這裡的預設值。

環境變數一律 TKB_ 前綴（00-總覽.md §7）。load_settings() 只讀環境變數，
不讀 .env 檔；本機要用時自己把 .env 載進環境（見本階段文件 §8）。
設計文件 §17.2：secret 只由執行環境提供，不寫進任何檔案。
"""

import os
from collections.abc import Mapping
from dataclasses import dataclass, field

from training_kb.errors import PermanentError


@dataclass
class Thresholds:
    """全部業務門檻。預設值對應設計文件，不要隨意調整。"""

    cosine_cluster: float = 0.85  # §7.3：Ticket 與群中心的同群門檻
    cosine_feature: float = 0.85  # §7.4：Feature 語意搜尋最低相似度
    jaccard_replay: float = 0.8  # §7.2：Rote 第二層的 key 重疊門檻
    proc_min_success: int = 3  # §7.2：PROC 可重放的最少成功數
    proc_max_consecutive_fail: int = 3  # §7.2：連續失敗達此數就 retired
    recurring_days: int = 14  # §7.3：當日 + 前 13 個 UTC 日期
    recurring_min_tickets: int = 5  # §7.3：同群至少幾筆才算 recurring
    weak_avg_below: float = 3.5  # §7.5：弱教學的平均評分上限（嚴格小於）
    weak_min_feedback_formal: int = 10  # §7.5：正式模式的最少回饋數
    weak_min_feedback_demo: int = 8  # §7.5：Demo 隔離模式的最少回饋數（F20）
    category_min_count: int = 5  # §7.5：同版同類回饋數，提 candidate 也用這個
    reopen_window_days: int = 14  # §12.1：重開票窗口 [p, p + 14 天)


@dataclass
class Settings:
    """一次執行所需要的全部設定。"""

    aws_region: str
    table_name: str  # 設計 §9.1：DynamoDB 表名，預設 "training_kb"
    bucket_name: str  # 實際 bucket 名稱；邏輯名稱是 training-kb-content
    project_id: str  # MVP 單一專案 ID，例 "demo-project"
    embed_model_id: str  # 例 "amazon.titan-embed-text-v2:0"
    embed_dimensions: int  # 設計 §17.1：固定 1024 維
    gen_model_id: str  # Claude model ID 或 inference profile，由 Phase 04 確認（O5）
    github_webhook_secret: str  # 只從環境變數讀，不落地成檔案
    bedrock_connect_timeout_s: float = 2.0  # 設計 §14.3
    bedrock_read_timeout_s: float = 30.0  # 設計 §14.3
    gen_max_tokens_judgement: int = 512  # 設計 §14.3：一般判斷節點
    gen_max_tokens_writing: int = 2048  # 設計 §14.3：教學寫作節點
    gen_temperature: float = 0.1  # 設計 §14.3：只設 temperature，不動 top_p
    thresholds: Thresholds = field(default_factory=Thresholds)


REQUIRED_KEYS: tuple[str, ...] = (
    "TKB_AWS_REGION",
    "TKB_TABLE_NAME",
    "TKB_BUCKET_NAME",
    "TKB_PROJECT_ID",
    "TKB_EMBED_MODEL_ID",
    "TKB_EMBED_DIMENSIONS",
    "TKB_GEN_MODEL_ID",
    "TKB_GITHUB_WEBHOOK_SECRET",
)


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    """從 TKB_* 環境變數建出 Settings。

    env 傳 None 就讀真正的 os.environ；測試請直接傳一個 dict 進來，
    這樣不會受到本機環境影響。

    缺必填值或值不是合法數字時，丟 PermanentError 並「一次列出全部」，
    不要讓使用者補一個再錯一個。
    """
    source: Mapping[str, str] = os.environ if env is None else env

    missing = [key for key in REQUIRED_KEYS if not (source.get(key) or "").strip()]
    if missing:
        raise PermanentError("缺少必要的環境變數：" + "、".join(missing))

    bad: list[str] = []

    def _int(key: str, default: int) -> int:
        raw = (source.get(key) or "").strip()
        if not raw:
            return default
        try:
            return int(raw)
        except ValueError:
            bad.append(key)
            return default

    def _float(key: str, default: float) -> float:
        raw = (source.get(key) or "").strip()
        if not raw:
            return default
        try:
            return float(raw)
        except ValueError:
            bad.append(key)
            return default

    settings = Settings(
        aws_region=source["TKB_AWS_REGION"].strip(),
        table_name=source["TKB_TABLE_NAME"].strip(),
        bucket_name=source["TKB_BUCKET_NAME"].strip(),
        project_id=source["TKB_PROJECT_ID"].strip(),
        embed_model_id=source["TKB_EMBED_MODEL_ID"].strip(),
        embed_dimensions=_int("TKB_EMBED_DIMENSIONS", 1024),
        gen_model_id=source["TKB_GEN_MODEL_ID"].strip(),
        # secret 也去掉前後空白，避免從終端機複製時多帶一個換行導致 HMAC 對不上。
        github_webhook_secret=source["TKB_GITHUB_WEBHOOK_SECRET"].strip(),
        bedrock_connect_timeout_s=_float("TKB_BEDROCK_CONNECT_TIMEOUT_S", 2.0),
        bedrock_read_timeout_s=_float("TKB_BEDROCK_READ_TIMEOUT_S", 30.0),
        gen_max_tokens_judgement=_int("TKB_GEN_MAX_TOKENS_JUDGEMENT", 512),
        gen_max_tokens_writing=_int("TKB_GEN_MAX_TOKENS_WRITING", 2048),
        gen_temperature=_float("TKB_GEN_TEMPERATURE", 0.1),
    )
    if bad:
        raise PermanentError("環境變數的值不是合法數字：" + "、".join(bad))
    return settings
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：`uv run pytest tests/unit/test_settings.py -v`

預期：`9 passed`。

再跑一次全部測試，確認 Task 6 的測試沒被弄壞：`uv run pytest -v` → 全部 passed。

- [ ] **步驟 5：commit**

```bash
git add src/training_kb/config.py tests/unit/test_settings.py
git commit -m "feat(config): 加入 Settings 與 load_settings"
```

---

### Task 8：讓 `@pytest.mark.aws` 預設跳過

**目的**：把「需要真 AWS 的測試」跟「離線就能跑的測試」分開，讓 `uv run pytest` 在沒有網路、沒有 AWS 憑證時也能跑完。

**檔案**：
- 新增：`tests/conftest.py`
- 測試：`tests/unit/test_aws_marker.py`

**介面**：
- 消費：`pyproject.toml` 裡註冊的 `aws` marker（Task 1）
- 產出：測試收集規則——只要沒有 `TKB_RUN_AWS_TESTS=1`，所有標了 `@pytest.mark.aws` 的測試一律 skip。Phase 03 起的整合測試都依賴這個行為。

- [ ] **步驟 1：寫測試**

```python
# tests/unit/test_aws_marker.py
"""aws marker 的自我檢查。

這個測試故意寫成「只有 TKB_RUN_AWS_TESTS=1 時才會通過」。
所以在預設情況下，它必須被 conftest.py 跳過；一旦沒被跳過就會失敗，
代表跳過機制壞了。
"""

import os

import pytest


@pytest.mark.aws
def test_aws_marked_test_only_runs_when_explicitly_enabled() -> None:
    assert os.environ.get("TKB_RUN_AWS_TESTS") == "1"
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：`uv run pytest tests/unit/test_aws_marker.py -v`

預期：`1 failed`，訊息是 `AssertionError: assert None == '1'`。

為什麼會失敗：目前沒有任何東西會跳過它，於是它真的被執行，而環境變數沒設，所以斷言不成立。

- [ ] **步驟 3：寫最少的程式讓測試通過**

```python
# tests/conftest.py
"""pytest 共用設定。

設計文件 §15：AWS 整合測試使用隔離的 Demo 環境。
本專案的預設是「離線也要跑得完」：標了 @pytest.mark.aws 的測試，
只有在環境變數 TKB_RUN_AWS_TESTS=1 時才執行，其餘時候一律跳過。

用 moto 模擬 AWS 的測試（Phase 03 起）不算在內，它們不需要這個 marker，
因為 moto 完全在記憶體裡跑，不連網也不花錢。
"""

import os

import pytest

RUN_AWS_TESTS_ENV = "TKB_RUN_AWS_TESTS"


def _aws_tests_enabled() -> bool:
    return os.environ.get(RUN_AWS_TESTS_ENV, "") == "1"


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """收集完測試之後，把 aws 測試標成 skip。"""
    del config  # 這個 hook 的簽名固定，這裡用不到 config
    if _aws_tests_enabled():
        return
    skip_aws = pytest.mark.skip(reason=f"需要真實 AWS 資源；設定 {RUN_AWS_TESTS_ENV}=1 才會執行")
    for item in items:
        if "aws" in item.keywords:
            item.add_marker(skip_aws)
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：`uv run pytest tests/unit/test_aws_marker.py -v`

預期：`1 skipped`，而且那一行顯示
`SKIPPED (需要真實 AWS 資源；設定 TKB_RUN_AWS_TESTS=1 才會執行)`。
**對這個 Task 來說，「skipped」就是通過的樣子。**

再驗證另一邊（確認打開開關時它真的會跑）：

```bash
TKB_RUN_AWS_TESTS=1 uv run pytest tests/unit/test_aws_marker.py -v
```

預期：`1 passed`。

（Windows PowerShell 請改成 `$env:TKB_RUN_AWS_TESTS="1"; uv run pytest tests/unit/test_aws_marker.py -v`，測完用 `Remove-Item Env:TKB_RUN_AWS_TESTS` 清掉。）

- [ ] **步驟 5：commit**

```bash
git add tests/conftest.py tests/unit/test_aws_marker.py
git commit -m "test(pytest): aws marker 預設跳過"
```

---

## 7. 完成檢查清單

一條一條執行、看到預期輸出才打勾。

- [ ] `uv run pytest -v` → 全部通過，結果行是 `38 passed, 1 skipped`（重點是 **0 failed、0 error**）。
- [ ] `uv run ruff check .` → 輸出 `All checks passed!`。
- [ ] `uv run ruff format --check .` → 輸出 `N files already formatted`（沒有 `Would reformat`）。
- [ ] `git check-ignore -v .env` → 有輸出（像 `.gitignore:11:.env	.env`）；`echo $?` 是 `0`。
- [ ] `git status --short` → 看不到 `.env`，也看不到 `.venv/`。
- [ ] `uv run python -c "import training_kb, training_kb.writing, training_kb.pipelines, training_kb.handlers; print(training_kb.__version__)"` → 印出 `0.1.0`。
- [ ] `uv run python -c "from training_kb.config import Thresholds; print(Thresholds())"` → 印出一行含 `cosine_cluster=0.85` … `reopen_window_days=14` 的內容。
- [ ] `uv run python -c "from training_kb.config import load_settings; load_settings({})"` → 丟出 `PermanentError` 並列出 8 個缺少的變數名稱。
- [ ] 打開 `.env.example`，確認裡面**沒有**任何真實的 Access Key、Secret 或 webhook secret。
- [ ] `node --version` 與 `aws sts get-caller-identity` 都有正常輸出（Phase 04 會用到）。
- [ ] `git log --oneline | head -10` → 看得到 Task 1–8 的 8 個 commit。

對應設計文件第 16 節的 S0 檢查：S0 完整要求「O2／O3 的最小整合驗證有可追溯結果；來源 ID、白名單與模型可用性已確認」。**這一階段只完成 S0 的第一小塊（專案可跑、設定與錯誤分類就位）**，O2／O3 的驗證在 Phase 03、08、24，模型可用性在 Phase 04。不要把本階段通過就宣稱 S0 已完成。

---

## 8. 常見錯誤與排除

**1. `ModuleNotFoundError: No module named 'training_kb'`**

- 症狀：`uv run pytest` 時所有測試都 import 失敗。
- 原因：多半是三種之一——(a) 你直接打 `pytest` 而不是 `uv run pytest`，用到系統 Python；(b) `pyproject.toml` 的 `[tool.hatch.build.targets.wheel] packages` 沒有寫 `["src/training_kb"]`；(c) `src/training_kb/__init__.py` 不存在。
- 解法：一律用 `uv run` 開頭；檢查上面兩個檔案；再跑一次 `uv sync`。確認 `uv run python -c "import training_kb; print(training_kb.__file__)"` 印出的路徑含 `src/training_kb`。

**2. `uv sync` 失敗：`Failed to build \`training-kb\`` 或 `Unable to determine which files to ship`**

- 症狀：`uv sync` 在建置專案本身時就停住。
- 原因：hatchling 找不到要打包的套件目錄。src layout 一定要明確告訴它位置。
- 解法：確認 `pyproject.toml` 裡有這兩行並且拼字正確：

  ```toml
  [tool.hatch.build.targets.wheel]
  packages = ["src/training_kb"]
  ```

  並確認 `src/training_kb/__init__.py` 確實存在（`ls src/training_kb/__init__.py`）。

**3. `error: No interpreter found for Python 3.12`**

- 症狀：`uv sync` 或 `uv run` 說找不到 3.12。
- 原因：本機沒有 3.12，而且 uv 還沒下載過。
- 解法：`uv python install 3.12`，再 `uv python pin 3.12`，然後重跑 `uv sync`。用 `cat .python-version` 確認裡面是 `3.12`。

**4. `git check-ignore -v .env` 沒有任何輸出（離開碼 1）**

- 症狀：`.gitignore` 明明有 `.env`，但 Git 說沒被忽略；`git status` 甚至列出 `.env`。
- 原因：**`.gitignore` 對「已經被 Git 追蹤過的檔案」無效**。如果 `.env` 曾經被 `git add` 過，它就一直被追蹤。
- 解法：

  ```bash
  git rm --cached .env
  git check-ignore -v .env
  ```

  然後 commit 這個移除。**另外務必檢查歷史紀錄裡有沒有已經被 commit 的金鑰**：`git log --oneline -- .env`。如果有，那把金鑰已經外洩過，必須到 AWS 或 GitHub 後台**作廢並重新產生**，光是刪檔案沒有用。

**5. `PermanentError: 缺少必要的環境變數：...`（在本機手動試 `load_settings()` 時）**

- 症狀：明明 `.env` 填好了，`load_settings()` 還是說缺變數。
- 原因：`load_settings()` 只讀**環境變數**，不會自己去讀 `.env` 檔。
- 解法：測試裡一律傳 dict 進去，不要依賴真實環境。真的要在終端機試的話用 `set -a && source .env && set +a` 先把它載進環境，再 `uv run python -c "from training_kb.config import load_settings; print(load_settings())"`。（Windows PowerShell 沒有 `source`，請用 `$env:TKB_AWS_REGION="us-east-1"` 這樣一個一個設。）

**6. ruff 報 `I001 Import block is un-sorted or un-formatted`**

- 症狀：`uv run ruff check .` 抱怨 import 順序。
- 原因：我們在 `[tool.ruff.lint] select` 裡開了 isort 規則（`I`）。
- 解法：`uv run ruff check --fix .` 讓它自動排好，再 `uv run ruff format .`。

**7. `PytestUnknownMarkWarning: Unknown pytest.mark.aws`；或 `aws sts get-caller-identity` 說 `Unable to locate credentials`**

- 原因與解法：前者是 `pyproject.toml` 的 `[tool.pytest.ini_options]` 裡沒有 `markers = ["aws: ..."]` 這一段，補上即可；後者是沒跑過 `aws configure`（或用 SSO 但還沒 `aws sso login`），重做 §3 的第 5 項。這一階段其實用不到 AWS，但 Phase 04 一定要，早點確認早點安心。

---

## 9. 這階段不做的事

| 不做的事 | 留給哪一階段 |
|---|---|
| 建立任何 AWS 資源（DynamoDB table、S3 bucket、Lambda、Step Functions） | Phase 04（資料資源）、Phase 14（應用資源） |
| 安裝 `aws-cdk-lib`、`streamlit` 等之後才用的依賴 | Phase 04（CDK）、Phase 23（Streamlit） |
| 決定並填入真正的 `TKB_GEN_MODEL_ID` | Phase 04；這是設計文件第 18 節的 O5，本計劃選擇用 `infra/scripts/check_models.py` 實際小量呼叫後才填，不填猜測值 |
| 決定要用哪一個 AWS Region | Phase 04（要先確認 Titan 與 Claude 在該區可用） |
| `models.py`（十個實體與枚舉）、`keys.py`（PK／SK 轉換） | Phase 02 |
| `repository.py`（DynamoDB 與 S3 讀寫、moto 測試） | Phase 03、Phase 09 |
| 任何 Bedrock 呼叫程式碼（本階段只定義逾時與 token 上限的**數值**） | Phase 05 |
| 把 `.env` 的內容載進環境的工具（例如 python-dotenv） | 不做；共用約定是「設定由執行環境提供」，本機自己 `source .env` |
| CI（GitHub Actions）、pre-commit hook | 不在這 26 份文件的範圍內 |
| Snyk 依賴掃描與 secrets 掃描 | Phase 25 |
| 把 `.env` 曾經外洩的金鑰作廢 | 不是這份文件能代勞的事；若 §8 第 4 題命中，請自己到 AWS／GitHub 後台處理 |

---

## 10. 對照：設計章節與 Rule 編號

設計文件第 20 節**沒有**把任何 Rule 指派給「專案骨架」這個模組——147 條 Rule 都是業務行為。所以下表列的是：本階段提供的常數與錯誤分類，將被哪一條 Rule 使用，以及由哪個後續階段真正落實。**本階段只是把數字與型別放到位，不宣稱這些 Rule 已經通過驗收。**

| Rule 來源檔 | Rule 編號與原文 | 本階段哪個 Task 提供 | 真正落實的階段 |
|---|---|---|---|
| `執行教學流程.feature` | Rule 4：每個 Bedrock 呼叫設定 max_tokens | Task 7：`gen_max_tokens_judgement=512`、`gen_max_tokens_writing=2048` | Phase 05 |
| `執行教學流程.feature` | Rule 5：每個 Bedrock 呼叫設定逾時 | Task 7：`bedrock_connect_timeout_s=2.0`、`bedrock_read_timeout_s=30.0` | Phase 05 |
| `執行教學流程.feature` | Rule 9：判斷節點使用低 temperature | Task 7：`gen_temperature=0.1` | Phase 05 |
| `執行教學流程.feature` | Rule 6：每個 Step Functions Task 設定 Retry | Task 4：`TransientError`（ASL 的 `ErrorEquals` 只列它） | Phase 14 |
| `執行教學流程.feature` | Rule 7：每個 Step Functions Task 設定 Catch | Task 4：`PermanentError` 及其子類別 | Phase 14 |
| `接入來源事件.feature` | Rule 7：第一層流程的 success_count 必須至少為 3 | Task 6：`proc_min_success=3` | Phase 11 |
| `接入來源事件.feature` | Rule 9：第一層未命中才在同寄件者的流程中以 Jaccard 至少 0.8 比對欄位 | Task 6：`jaccard_replay=0.8` | Phase 11 |
| `接入來源事件.feature` | Rule 19：同一流程連續三次重放失敗後 status 變為 retired | Task 6：`proc_max_consecutive_fail=3` | Phase 11 |
| `接入來源事件.feature` | Rule 18：Agent 最終仍無法產出合法物件時回傳失敗 | Task 4：`IngressError(message, fields)` | Phase 10、12 |
| `接入來源事件.feature` | Rule 21：正規化物件必須具有 schema 的必填欄位 | Task 4：`IngressError` 的 `fields` 屬性 | Phase 10 |
| `分析工單.feature` | Rule 1：每則 Ticket 在接入分析時計算一次並儲存 1024 維 embedding | Task 7：`embed_dimensions`（預設 1024）、`embed_model_id` | Phase 05、13 |
| `分析工單.feature` | Rule 2：demo 分群以 cosine 至少 0.85 為同群門檻 | Task 6：`cosine_cluster=0.85` | Phase 13 |
| `分析工單.feature` | Rule 3：同群在 14 天內至少有 5 筆 Ticket 才算 recurring | Task 6：`recurring_days=14`、`recurring_min_tickets=5`；Task 5：`utc_date()` | Phase 13 |
| `依改版更新教學.feature` | Rule 4：alias 比對未命中時以向量搜尋最相近的 Feature | Task 6：`cosine_feature=0.85` | Phase 16 |
| `定期檢視回饋.feature` | Rule 2：弱教學的版本平均評分必須小於 3.5 | Task 6：`weak_avg_below=3.5` | Phase 17 |
| `定期檢視回饋.feature` | Rule 3：弱教學的版本回饋樣本數必須至少為 10 | Task 6：`weak_min_feedback_formal=10`（Demo 隔離門檻 `weak_min_feedback_demo=8`，對應 F20） | Phase 17 |
| `定期檢視回饋.feature` | Rule 4：弱教學必須具有 recurring Feedback Category | Task 6：`category_min_count=5` | Phase 17 |
| `提出教學規則.feature` | Rule 1：同類 Feedback 至少 5 筆才可提出 candidate 規則 | Task 6：`category_min_count=5` | Phase 18 |
| `檢視學習指標.feature` | Rule 3：同題重開票率計算看過教學的使用者在版本發布後 14 天內同 cluster 再開票的比例 | Task 6：`reopen_window_days=14`；Task 5：`parse_iso()` | Phase 19 |
| `建立教學版本.feature` | Rule 9：沒有 Feature 或引用多個 Feature 的步驟不可保存 | Task 4：`ContentError` | Phase 07 |

---

## 11. 參考來源

**設計文件章節**（`docs/design/training-kb.md`）

- §2（來源優先順序）：記錄了「prompt 說 `.env` 已忽略／本次 `git check-ignore .env` 未命中」這個事實。
- §4（Repo 現況）：`pyproject.toml`、`package.json` 不存在，`tests/unit/`、`tests/integration/` 無檔案。
- §5：目標架構與模組責任、目錄結構、相依方向。
- §7.2、§7.3、§7.5：Rote、Ticket Analysis、Feedback Review 的門檻數字來源；§12.1：指標公式與重開票窗口。
- §14.1、§14.2：失敗語意與「重試不是重新抽一次文字」；§14.3：Bedrock 逾時、max_tokens、temperature 的建議起點。
- §16：交付切片 S0 的完成檢查；§17.2：secret 只由執行環境提供；§18：待確認事項 O5（模型與參數驗證）。
- §20.1、§20.2、§20.3、§20.5、§20.6、§20.7、§20.8、§20.11：本階段 §10 對照表引用的 Rule 原文。

**Repo 規範**：`AGENTS.md`（commit 訊息格式 `<type>(<scope>): <中文主旨>`）。

**外部文件**（本次以 Context7 MCP 查證；實作時請以當下版本為準）

| 主題 | 連結 |
|---|---|
| uv：專案與依賴（`uv add`、`uv add --dev`） | https://github.com/astral-sh/uv/blob/main/docs/guides/projects.md ｜ https://github.com/astral-sh/uv/blob/main/docs/concepts/projects/dependencies.md |
| uv：`uv python pin` 與 `.python-version` | https://github.com/astral-sh/uv/blob/main/README.md |
| pytest：在 `pyproject.toml` 用 `[tool.pytest.ini_options]` 設定 | https://github.com/pytest-dev/pytest/blob/main/doc/en/changelog.rst |
| pytest：註冊自訂 marker | https://github.com/pytest-dev/pytest/blob/main/doc/en/example/markers.rst |
| ruff：設定檔與規則選取（`[tool.ruff]`、`[tool.ruff.lint]`、`target-version`、`src`） | https://docs.astral.sh/ruff/configuration ｜ https://docs.astral.sh/ruff/linter ｜ https://docs.astral.sh/ruff/settings |
| AWS CLI 安裝與 `aws configure` | https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html ｜ https://docs.aws.amazon.com/cli/latest/userguide/cli-chap-configure.html |
| Node.js（CDK CLI 的前置需求） | https://nodejs.org/ |

---

**下一步**：`02-Phase02-領域模型與資料鍵.md`。
