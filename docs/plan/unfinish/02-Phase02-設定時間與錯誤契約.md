# Phase 02 設定、時間與錯誤契約 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立所有後續模組共用的設定、UTC 時間與可分類錯誤，讓測試可注入時間且失敗語意不靠字串猜測。

**Architecture:** `clock.py` 只處理 aware UTC datetime；`config.py` 只讀 `TKB_` 前綴環境變數並保存尚未確認的值；`errors.py` 提供固定 exception 類型。業務函式要把 `now` 當參數，不在深層程式直接讀系統時鐘。

**Tech Stack:** Python 3.12、uv、標準函式庫 dataclasses／datetime、pytest。

## 文件定位

- **讀者：** 將撰寫資料模型、Repository、Ingress 或 Pipeline 的工程師。
- **唯一主來源：** [設計 §7.1、§12.1、§14、§18 O4/O5](../../design/training-kb.md)。
- **名稱與欄位準則：** [00A 共用契約與名詞](00A-共用契約與名詞.md) 第 3.5 節（`TKB_*` 環境變數）、第 4.1 節（六個錯誤類別）、第 5.4 節（`Settings`／`Thresholds` 欄位）。本文件與 00A 衝突時以 00A 為準。
- **前置 Phase：** [Phase 01](01-Phase01-專案骨架與離線品質門檻.md) 的 package 與 `uv run` 工具鏈。
- **下一份：** [Phase 03 識別碼、列舉與內容草稿模型](03-Phase03-識別碼列舉與內容草稿模型.md)。
- **本階段不做：** 不核定 O4 的十四天窗口；不猜 Claude model ID、Region 或帳號權限；不連 AWS。

## 全域限制

- 本 Phase 是 `errors.py`、`clock.py`、`config.py` 三個檔案的 owner（00A 第 3.2 節）；後面的 Phase 只能修改，不能改名或搬家。
- `errors.py` 本 Phase 只建立**六個**固定類別。第七個 `ObjectAlreadyExists(PermanentError)` 由 [Phase 07](07-Phase07-S3物件與關係邊讀寫.md) 追加到同一個檔案（00A 第 3.2、6.1 節與裁決 D-30）；本 Phase 不得預先建立它。
- 所有指令一律 `uv run pytest`／`uv run ruff check`／`uv run mypy`（00A 第 3.1 節）；環境變數名稱逐字照 00A 第 3.5 節，**不得**自創縮寫別名（例如把 `TKB_CONTENT_BUCKET`、`TKB_GENERATION_MODEL_ID`、`TKB_EMBEDDING_MODEL_ID` 寫成短名，裁決 D-33）。
- `Thresholds` 是全系統門檻數字的唯一來源；下游模組常數只能是它的別名，不得出現第二份數字，也不得自創 `cosine_cluster`、`recurring_days`、`weak_min_feedback_formal` 這類欄位名（裁決 D-35）。
- 與本 Phase 有關的 gate：**O4**（時間窗口端點）與 **O5**（模型與參數）都尚未通過。本 Phase 只提供 UTC primitive 與空的 `generation_model_id`，不得宣稱窗口已核定，也不得填任何未實測的 Claude model ID。
- 以下程式檔均是實作時預計建立；本計畫本身不代表它們已存在。

## 你在整體流程的位置

```text
環境變數 / 測試注入的 now
           |
           v
   +----------------------+
   | [你在這裡]           |
   | config / clock /errors|
   +-----+----------+-----+
         |          |
         v          v
   資料模型     所有流程的失敗分支
   (P03-P04)    (P06 起全部)
```

## 完成後看得到什麼

輸入 `2026-08-20T00:00:00Z`，`parse_iso` 回傳 UTC aware datetime，`to_iso` 再輸出相同字串；輸入 `2026-08-20T08:00:00+08:00` 會**換算**成 `2026-08-20T00:00:00Z`，不是把後綴換掉。沒有時區的 `2026-08-20T00:00:00` 必須失敗。

時間字串只有**整秒**一種形狀：`now_utc()` 回來的 datetime `microsecond` 一定是 `0`，`to_iso` 也只吐 `YYYY-MM-DDTHH:MM:SSZ`；真的餵給它一個帶微秒的時間，它會拋 `PermanentError` 而不是偷偷截掉（00A 第 3.5 節）。這一條讓 [Phase 05](05-Phase05-單表鍵與關係邊契約.md) 的 `view_pk` 與 [Phase 10](10-Phase10-O2操作紀錄與永久去重契約.md) 的操作紀錄只會產生一種字串長度。

`load_settings({"TKB_TABLE_NAME": "training_kb_test", "TKB_CONTENT_BUCKET": "tkb-test"})` 會得到一個凍結的 `Settings`，重點是四個「沒有猜值」的欄位：`generation_model_id` 是 `None`（O5 未過，保持空值）、`embedding_model_id` 是設計 §17.1 已查證的 `amazon.titan-embed-text-v2:0`、`project_id` 是 `DEFAULT_PROJECT_ID`（`demo`）、`aws_region` 與 `bedrock_region` 沒給就是 `None`，不去填 boto3 的環境預設。

`IngressError("缺少必填欄位", ["ts", "author", "author"])` 的 `fields` 會是 `("author", "ts")`，`str(error)` 仍是 `缺少必填欄位`。

## 名詞小抄

| 名詞 | 白話意思 |
|---|---|
| aware datetime／naive datetime | 帶時區資訊的時間／沒有時區的時間；naive 跨服務時容易把本地時間誤當 UTC，本專案一律拒絕。固定字串格式是 UTC ISO 8601 `2026-08-20T00:00:00Z`，結尾的 `Z` 就是「UTC ＋0 時區」。 |
| `TransientError`／`PermanentError` | 服務暫時失敗、再送一次有機會成功／資料確定不合法，重送沒有意義、直接走失敗終點。 |
| `IngressError` | `PermanentError` 的子類，專用於接入資料檢查；`fields` 列出是哪幾個欄位不合法，讓提交者知道要改什麼。 |
| frozen dataclass（凍結資料類別） | 建立後就不能改欄位的小型資料容器；設定載入後不會被中途偷改，測試也可以放心共用。 |
| `Thresholds`（門檻） | 把散落各處的判斷數字（0.85、5、10、8、3.5）集中成一份，避免同一個門檻在兩個檔案寫成兩個值。 |
| gate O4／O5 | 設計 §18 的待確認事項：O4 是時間窗口端點怎麼算，O5 是帳號到底能用哪個模型。兩者都要真實證據才算通過。 |
| 微秒（microsecond） | 秒以下的六位數字，例如 `06:25:58.635733` 的 `.635733`。它會讓同一個時刻產生長短不一的字串，所以本專案在時間一進來就把它去掉。 |

## 預計新增／修改的檔案

以下是實作時預計建立，目前不代表檔案存在：

- Create: `src/training_kb/errors.py` — 六個固定錯誤類別（P07 會在同檔追加第七個）。
- Create: `src/training_kb/clock.py` — `now_utc`、`to_iso`、`parse_iso`、`utc_date`。
- Create: `src/training_kb/config.py` — `Thresholds`、`Settings`、`DEFAULT_PROJECT_ID`、`load_settings`。
- Create: `tests/unit/test_clock.py`、`tests/unit/test_errors.py`、`tests/unit/test_config.py`

## 固定介面

### Consumes

- Phase 01 的 `training_kb` package 與 `uv run` 指令。
- 環境 mapping `Mapping[str, str]`；只有 `TKB_` 前綴會被讀取。

### Produces

```python
# src/training_kb/errors.py：六個類別，誰拋誰接見 00A 第 4.1 節
class TransientError(Exception): ...
class PermanentError(Exception): ...
class ContentError(PermanentError): ...
class CoordinationError(Exception): ...
class PublishError(Exception): ...

class IngressError(PermanentError):
    message: str
    fields: tuple[str, ...]
    def __init__(self, message: str, fields: Iterable[str] = ()) -> None: ...

# src/training_kb/clock.py
def now_utc() -> datetime: ...
def to_iso(dt: datetime) -> str: ...
def parse_iso(value: str) -> datetime: ...
def utc_date(dt: datetime) -> date: ...

# src/training_kb/config.py：欄位與預設值見下表，完整程式碼在 Task 2 Step 3
DEFAULT_PROJECT_ID = "demo"

@dataclass(frozen=True)
class Thresholds: ...

@dataclass(frozen=True)
class Settings: ...

def load_settings(env: Mapping[str, str] | None = None) -> Settings: ...
```

`IngressError.fields` 的型別固定是 `tuple[str, ...]`，不是 `list[str]`（裁決 D-06）。`CoordinationError` 與 `PublishError` **刻意不繼承** `PermanentError`：它們可能包裝暫時或永久原因，由呼叫端各自判斷。

`Thresholds` 六個欄位（名稱與預設值逐字取自 00A 第 5.4 節）：

| 欄位 | 預設 | 意思 | 主要使用 Phase |
|---|---:|---|---|
| `cosine_match` | 0.85 | 兩段文字語意相似度要到多少才算「同一件事」；工單分群與 Release 找 Feature 共用同一個數字。 | P38、P49 |
| `recurring_tickets` | 5 | 同一群工單在窗口內累積到幾筆才算 recurring（值得寫教學）。 | P39 |
| `recurring_category` | 5 | 同一版本的同一個問題類別要幾筆回饋，才算「重複出現的類別」。 | P44 |
| `production_feedback` | 10 | 正式模式下，一個版本要有幾筆回饋才可以判定是不是弱教學。 | P44 |
| `demo_feedback` | 8 | Demo 隔離模式的同一個下限；**只有筆數不同**，其他條件完全一樣。 | P44 |
| `weak_average` | 3.5 | 平均評分低於這個值才算弱教學（嚴格小於，3.5 本身不算）。 | P44 |

`Settings` 的八個欄位（`table_name`、`content_bucket`、`aws_region`、`bedrock_region`、`generation_model_id`、`embedding_model_id`、`project_id`、`thresholds`）與各自的環境變數見 Task 2 Step 3 的完整程式碼與 00A 第 3.5 節；`weak_average`、`bedrock_region`、`project_id` 是 00A 裁決 D-33／D-34 追加的欄位，都有預設值，不影響既有呼叫。沒有對應欄位、維持模組常數的固定數字（本 Phase **不**收進 `Thresholds`，逐條對照 00A 第 5.4 節的表）：`RECURRING_DAYS = 14`、`reopen_window(..., days=14)`、`JACCARD_THRESHOLD = 0.8`、`PROC_MIN_SUCCESS = 3`、`PROC_MAX_CONSECUTIVE_FAIL = 3`、`SAFETY_NET_CANDIDATES = 5`、`MIN_CANDIDATE_FEEDBACK = 5`、`MAX_BATCH_VERSIONS = 50`、`LEASE_TTL_SECONDS = 120`、`AGENT_MAX_TOOL_CALLS = 6`、`SEQUENCE_ATTEMPTS = 8`（`operations.py`，P11）、`TITAN_DIMENSIONS = 1024`（`writing/client.py`，P16）。其中 `MIN_CANDIDATE_FEEDBACK`（Phase 47）雖然和 `recurring_category` 同樣是 5，但 00A 明文把它留在 `pipelines/feedback.py` 當獨立常數，**不要**把它改寫成這個欄位的別名。

## Task 1：以測試鎖定 UTC 時間與錯誤分類

**Files:** `src/training_kb/clock.py`、`src/training_kb/errors.py`、`tests/unit/test_clock.py`、`tests/unit/test_errors.py`。

**Interfaces:** Consumes `datetime`；Produces 四個 clock 函式與六個固定 exception。

- [x] **Step 1：寫時間與錯誤的失敗／成功測試**

`tests/unit/test_clock.py` 的完整內容：

```python
from datetime import UTC, datetime, timedelta, timezone

import pytest

from training_kb.clock import now_utc, parse_iso, to_iso, utc_date
from training_kb.errors import PermanentError

TAIPEI = timezone(timedelta(hours=8))


def test_iso_round_trip_and_offset_conversion() -> None:
    value = datetime(2026, 8, 20, tzinfo=UTC)
    assert to_iso(value) == "2026-08-20T00:00:00Z"
    assert parse_iso("2026-08-20T00:00:00Z") == value
    assert utc_date(value).isoformat() == "2026-08-20"
    assert to_iso(datetime(2026, 8, 20, 8, 0, tzinfo=TAIPEI)) == "2026-08-20T00:00:00Z"
    assert utc_date(datetime(2026, 8, 20, 7, 0, tzinfo=TAIPEI)).isoformat() == "2026-08-19"
    assert now_utc().tzinfo is not None


def test_naive_time_is_rejected() -> None:
    with pytest.raises(ValueError, match="timezone"):
        to_iso(datetime(2026, 8, 20))
    with pytest.raises(ValueError, match="timezone"):
        parse_iso("2026-08-20T00:00:00")


def test_time_strings_are_whole_seconds() -> None:
    assert now_utc().microsecond == 0
    with pytest.raises(PermanentError, match="whole seconds"):
        to_iso(datetime(2026, 8, 20, 6, 25, 58, 635733, tzinfo=UTC))
```

最後一個測試鎖住整秒規則：`now_utc()` 自己就不帶微秒，而帶微秒的時間丟給 `to_iso` 會**明確失敗**（`PermanentError`），不是被靜默截斷。靜默截斷的壞處是兩個不同的時刻會寫出同一個鍵，事後查不出來。

`utc_date(2026-08-20T07:00+08:00)` 必須是 `2026-08-19`：這一行鎖住「先換算再取日期」，[Phase 39](39-Phase39-Recurring與Knowledge-Gap命名.md) 的 recurring 窗口與 [Phase 54](54-Phase54-重開票與呼叫規則指標.md) 的 O4 窗口都依賴它。

`tests/unit/test_errors.py` 的完整內容：

```python
import pytest

from training_kb import errors


def test_ingress_error_keeps_sorted_unique_fields() -> None:
    error = errors.IngressError("缺少必填欄位", ["ts", "author", "author"])
    assert error.fields == ("author", "ts")
    assert error.message == "缺少必填欄位"
    assert str(error) == "缺少必填欄位"
    assert isinstance(error, errors.PermanentError)


def test_error_hierarchy_separates_retryable() -> None:
    assert issubclass(errors.ContentError, errors.PermanentError)
    assert not issubclass(errors.TransientError, errors.PermanentError)
    assert not issubclass(errors.CoordinationError, errors.PermanentError)
    assert not issubclass(errors.PublishError, errors.PermanentError)
    with pytest.raises(errors.TransientError):
        raise errors.TransientError("DynamoDB 暫時取消")
```

- [x] **Step 2：確認測試因模組不存在而失敗**

```bash
uv run pytest tests/unit/test_clock.py tests/unit/test_errors.py -q
```

預期：FAIL，訊號包含 `ModuleNotFoundError: No module named 'training_kb.clock'`。

- [x] **Step 3：建立最小 UTC 與錯誤實作**

`src/training_kb/clock.py` 的完整內容：

```python
from datetime import UTC, date, datetime

from training_kb.errors import PermanentError


def now_utc() -> datetime:
    """現在的 UTC 時間；先去掉微秒，全套時間字串只有整秒一種形狀。"""
    return datetime.now(UTC).replace(microsecond=0)


def _aware(dt: datetime) -> datetime:
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError("datetime must include timezone")
    return dt.astimezone(UTC)


def to_iso(dt: datetime) -> str:
    value = _aware(dt)
    if value.microsecond:
        raise PermanentError(f"datetime must be whole seconds: {value.isoformat()}")
    return value.isoformat().replace("+00:00", "Z")


def parse_iso(value: str) -> datetime:
    # Python 3.11 起 fromisoformat 直接支援結尾的 Z，不需要先做字串置換。
    return _aware(datetime.fromisoformat(value))


def utc_date(dt: datetime) -> date:
    return _aware(dt).date()
```

`src/training_kb/errors.py` 的完整內容：

```python
from collections.abc import Iterable


class TransientError(Exception):
    """暫時性服務故障，重送有機會成功；由 ASL Task 的 Retry 處理。"""


class PermanentError(Exception):
    """確定不合法或不會成功；由 ASL 的 Catch 導向失敗終點。"""


class ContentError(PermanentError):
    """內容不合規：段落缺失、步驟編號不連續、每步不是恰一個 Feature、未命中步驟被改動。"""


class CoordinationError(Exception):
    """操作紀錄不一致：找不到 operation、狀態轉移不合法、同 operation 取到不同版號。"""


class PublishError(Exception):
    """發布前提不成立或中途失敗：版本不完整、current_version 已被改、bytes 不同。"""


class IngressError(PermanentError):
    """接入資料缺欄位或值不合法；fields 是不合法欄位名的 tuple。"""

    def __init__(self, message: str, fields: Iterable[str] = ()) -> None:
        super().__init__(message)
        self.message = message
        self.fields: tuple[str, ...] = tuple(sorted(set(fields)))
```

`fields` 排序去重是**本計畫選擇**（00A 只要求它是 `tuple[str, ...]`），讓同一組錯誤欄位的輸出可重現、方便測試逐字比對。

- [x] **Step 4：驗證時間與錯誤測試通過**

```bash
uv run pytest tests/unit/test_clock.py tests/unit/test_errors.py -q
```

預期：`5 passed`（round-trip 與 offset 換算、naive 拒絕、整秒規則、Ingress 欄位保存、錯誤階層）。

- [x] **Step 5：提交共用時間與錯誤契約**

```bash
git add src/training_kb/clock.py src/training_kb/errors.py tests/unit/test_clock.py tests/unit/test_errors.py
git commit -m "feat(core): 建立時間與錯誤契約"
```

## Task 2：建立不猜值的設定載入器

**Files:** `src/training_kb/config.py`、`tests/unit/test_config.py`。

**Interfaces:** Consumes `Mapping[str, str] | None`；Produces immutable `Thresholds`、`Settings`、`DEFAULT_PROJECT_ID` 與 `load_settings`。

- [x] **Step 1：寫設定測試**

`tests/unit/test_config.py` 的完整內容：

```python
from training_kb.config import DEFAULT_PROJECT_ID, load_settings

MINIMAL = {"TKB_TABLE_NAME": "training_kb_test", "TKB_CONTENT_BUCKET": "tkb-test"}


def test_load_settings_keeps_unverified_model_empty() -> None:
    settings = load_settings({**MINIMAL, "TKB_AWS_REGION": "us-east-1"})
    assert settings.table_name == "training_kb_test"
    assert settings.generation_model_id is None
    assert settings.embedding_model_id == "amazon.titan-embed-text-v2:0"
    assert settings.bedrock_region == "us-east-1"
    assert settings.project_id == DEFAULT_PROJECT_ID == "demo"
    assert settings.thresholds.cosine_match == 0.85
    assert settings.thresholds.weak_average == 3.5
    assert settings.thresholds.production_feedback == 10
    assert settings.thresholds.demo_feedback == 8


def test_bedrock_region_is_independent_and_non_tkb_keys_are_ignored() -> None:
    settings = load_settings(
        {"TKB_AWS_REGION": "ap-northeast-1", "TKB_BEDROCK_REGION": "us-east-1", "AWS_REGION": "x"}
    )
    assert settings.aws_region == "ap-northeast-1"
    assert settings.bedrock_region == "us-east-1"
    assert settings.table_name == "training_kb"
    assert settings.content_bucket == "training-kb-content"
```

第二個測試同時鎖住三件事：`TKB_BEDROCK_REGION` 是**獨立欄位**而不是 `TKB_AWS_REGION` 的別名（裁決 D-33）；非 `TKB_` 前綴的 `AWS_REGION` 不得影響 Settings；兩個名稱都缺時用固定預設值而不是空字串。

- [x] **Step 2：確認測試先失敗**

```bash
uv run pytest tests/unit/test_config.py -q
```

預期：FAIL，訊號包含 `ModuleNotFoundError: No module named 'training_kb.config'`。

- [x] **Step 3：建立 frozen 設定模型**

`src/training_kb/config.py` 的完整內容：

```python
from collections.abc import Mapping
from dataclasses import dataclass, field
from os import environ

DEFAULT_PROJECT_ID = "demo"
DEFAULT_EMBEDDING_MODEL_ID = "amazon.titan-embed-text-v2:0"


@dataclass(frozen=True)
class Thresholds:
    cosine_match: float = 0.85
    recurring_tickets: int = 5
    recurring_category: int = 5
    production_feedback: int = 10
    demo_feedback: int = 8
    weak_average: float = 3.5


@dataclass(frozen=True)
class Settings:
    table_name: str
    content_bucket: str
    aws_region: str | None = None
    bedrock_region: str | None = None
    generation_model_id: str | None = None
    embedding_model_id: str = DEFAULT_EMBEDDING_MODEL_ID
    project_id: str = DEFAULT_PROJECT_ID
    thresholds: Thresholds = field(default_factory=Thresholds)


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    values: Mapping[str, str] = environ if env is None else env
    aws_region = values.get("TKB_AWS_REGION")
    return Settings(
        table_name=values.get("TKB_TABLE_NAME", "training_kb"),
        content_bucket=values.get("TKB_CONTENT_BUCKET", "training-kb-content"),
        aws_region=aws_region,
        bedrock_region=values.get("TKB_BEDROCK_REGION") or aws_region,
        generation_model_id=values.get("TKB_GENERATION_MODEL_ID"),
        embedding_model_id=values.get("TKB_EMBEDDING_MODEL_ID", DEFAULT_EMBEDDING_MODEL_ID),
        project_id=values.get("TKB_PROJECT_ID", DEFAULT_PROJECT_ID),
    )
```

Titan ID 是設計 §17.1 已查證的建議值；可用性仍由 [Phase 14](14-Phase14-O5模型可用性與參數驗證.md) 的真實帳號驗證。Claude ID 不設預設值，O5 未通過前 `generation_model_id` 一律保持 `None`。`bedrock_region` 缺值時沿用 `aws_region`，讓只用單一 Region 的人不必設兩個變數，但欄位本身是獨立的。

- [x] **Step 4：跑設定與離線品質門檻**

```bash
uv run pytest tests/unit -q
uv run ruff check src tests
uv run mypy src
```

預期：全部 exit code 0（`8 passed`＝Phase 01 的 1 筆加本 Phase 的 7 筆、`All checks passed!`、`Success: no issues found`）；測試不得讀真實 process environment。

- [x] **Step 5：提交設定契約**

```bash
git add src/training_kb/config.py tests/unit/test_config.py
git commit -m "feat(core): 增加不可變設定模型"
```

## 驗收與停止條件

```text
datetime --> _aware() --> 有 tzinfo ? -- 否 --> ValueError（停止，不猜時區）
                              | 是
                              v
                   astimezone(UTC) --> to_iso / utc_date

Mapping  --> load_settings() --> TKB_ 前綴命中 ? -- 否 --> 用固定預設值（不掃整份 env）
                    |
                    v
         generation_model_id 仍是 None --> O5 未過，呼叫端標 BLOCKED
```

| 輸入 | 預期 | 不可接受 |
|---|---|---|
| `Z` 時間 | 回傳 UTC aware datetime | 悄悄移除 tzinfo。 |
| `+08:00` 時間 | 換算成相同瞬間的 UTC（`08:00+08:00` → `00:00Z`） | 只替換字串後綴。 |
| naive datetime 或 naive 字串 | `ValueError`，訊息含 `timezone` | 猜成本地時區。 |
| `now_utc()` 的輸出 | `microsecond == 0`，`to_iso` 得到 `...T06:25:58Z` | 讓微秒流進字串。 |
| 帶微秒的 aware datetime | `to_iso` 拋 `PermanentError`（訊息含 `whole seconds`） | 在 `to_iso` 內靜默截斷成整秒。 |
| 缺 Claude ID | 保持 `None` | 填入未驗證 model ID。 |
| 只給／同時給兩個 Region | 只給 `TKB_AWS_REGION` 時 `bedrock_region` 沿用它；兩個都給時各自保留 | 把 `bedrock_region` 當別名刪掉欄位，或讓後者覆蓋前者。 |
| 非 `TKB_` 變數 | 不影響 Settings | 掃描整份 env 或印出 secrets。 |
| 缺 `TKB_PROJECT_ID` | `project_id == "demo"` | 留空字串或 `None`。 |

人工驗收：閱讀 `Settings` 欄位確認沒有 credential value；把 `Thresholds` 六個與 `Settings` 八個欄位逐一對照 00A 第 5.4 節，確認名稱與預設值逐字相同；注入固定 `now` 的測試不依賴牆上時間。

## 常見錯誤與停止條件

| 症狀 | 原因 | 修正／停止 |
|---|---|---|
| 時間差了 8 小時 | 用 `datetime.replace(tzinfo=UTC)`，那是改解讀而不是換算 | 一律用 `astimezone(UTC)`；`_aware` 已經包好，不要繞過它。 |
| `to_iso(some_time)` 拋 `PermanentError` | 那個時間是別處自己算出來、還帶著微秒的 | 時間一律取自 `now_utc()`（已去微秒）；真的要從外部時間轉換，先 `dt.replace(microsecond=0)` 再交給 `to_iso`。不要改 `to_iso` 讓它靜默截斷，否則兩個不同時刻會寫出同一個鍵而查不出來。 |
| `ruff` 報 `UP035` | 寫成 `from typing import Mapping` | Python 3.12 用 `from collections.abc import Mapping`／`Iterable`。 |
| `rating=True` 被當成 `1` 通過驗證 | `bool` 是 Python `int` 的子類 | 本 Phase 不做 rating 驗證；[Phase 03](03-Phase03-識別碼列舉與內容草稿模型.md) 與 [Phase 42](42-Phase42-Feedback與View固定匯入.md) 要明確排除 `bool`。 |
| 有人在 `errors.py` 先加了 `ObjectAlreadyExists` | 誤以為 S3 條件寫入屬於本 Phase | 停止並移除；owner 是 [Phase 07](07-Phase07-S3物件與關係邊讀寫.md)（裁決 D-30）。 |
| 有人在 `Thresholds` 加 `recurring_days`、`cosine_cluster` | 想讓某個下游模組讀起來順手 | 停止；沒有對應欄位的數字維持模組常數（裁決 D-35），否則同一門檻會出現兩份數字。 |
| 靠錯誤訊息字串決定要不要重試 | 誤以為 `TransientError` 可以一直重試、或用文字判斷 `PublishError` 的原因 | 重試上限由 ASL 的 `Retry`（等 1 秒、2 秒共兩次）決定，程式內不自行疊 retry；`PublishError` 可能包裝暫時或永久原因，呼叫端要保存原分類而不是比對字串。 |
| **停止條件：O4／O5 都未通過** | 窗口端點仍是設計建議值、帳號可用模型未實測 | O4：只提供 UTC primitive，不建立 `[p, p+14 天)` 規則，不得宣稱端點已有規格答案。O5：`generation_model_id` 保持 `None`，因此無法進行的 Phase 標 BLOCKED 並留報告，不填猜測值。 |

## 來源與 Rule 對照

- [設計 §7.1](../../design/training-kb.md#s7)：接入失敗要回傳「操作失敗」與不合法欄位，這是 `IngressError.fields` 的用途。
- [設計 §14、§14.3](../../design/training-kb.md#s14)：暫時故障、非法資料與失敗終點需分開；暫時錯誤最多重試兩次（等 1 秒、2 秒），且只讓一層管理重試。
- [設計 §12.1](../../design/training-kb.md#s12)、[§11.2](../../design/training-kb.md#s11)：弱教學與指標的門檻數值，對應 `Thresholds` 六個欄位（正式 n≥10、Demo n≥8、平均 <3.5、同類 ≥5、cosine ≥0.85）。
- [設計 §18 O4/O5](../../design/training-kb.md#s18)：時間端點、Region 與模型仍待確認。[00A 共用契約與名詞](00A-共用契約與名詞.md)：第 3.5 節（`TKB_*` 名稱與 UTC 規定）、第 4.1 節（六個錯誤類別）、第 5.4 節（`Settings`／`Thresholds` 逐字欄位）、裁決 D-06、D-13、D-30、D-33、D-34、D-35。
- [接入來源事件.feature](../../spec/features/接入來源事件.feature)：後續欄位錯誤須能以 `IngressError.fields` 指出。
- 本 Phase 沒有 primary Rule（見 [00B 需求覆蓋對照](00B-需求覆蓋對照.md) 第 2 節）。00B 把 P02 列為 `ING` Rule 18「Agent 最終仍無法產出合法物件時回傳失敗」與 `ING` Rule 21「正規化物件必須具有 schema 的必填欄位」的**其他相關 Phase**；這兩條的直接斷言分別在 [Phase 37](37-Phase37-Rote-Agent回退與成功提交.md) 與 [Phase 31](31-Phase31-Ticket與Release正規化.md)，本 Phase 只提供它們要用的錯誤型別與 UTC primitive。

## 完成清單

- [x] aware UTC round-trip、`+08:00` 換算與 naive 拒絕測試通過。
- [x] `now_utc()` 不帶微秒，`to_iso` 只輸出整秒字串且對帶微秒的輸入拋 `PermanentError`（00A 第 3.5 節）。
- [x] `errors.py` 只有六個類別（沒有預先加入 `ObjectAlreadyExists`），可由後續模組 import，且 `IngressError.fields` 是 `tuple[str, ...]`。
- [x] `Thresholds` 六個欄位與 `Settings` 八個欄位逐字符合 00A 第 5.4 節，含 `weak_average`、`bedrock_region`、`project_id`。
- [x] 只有 `TKB_` 前綴設定被消費、名稱逐字符合 00A 第 3.5 節，且 `generation_model_id` 仍是 `None`（Claude ID 未被猜測）。
- [x] O4 仍明示未核定，未將時間 helper 說成窗口驗收。
- [x] `uv run pytest tests/unit -q`、`uv run ruff check src tests`、`uv run mypy src` 三者皆 exit 0。
- [x] 下一份可以引用固定錯誤、clock 與 Settings。

**下一份可用成果：** 可注入的 UTC 時間、不可變設定（含 `project_id`、`bedrock_region` 與六個門檻）與跨模組一致的錯誤分類。
