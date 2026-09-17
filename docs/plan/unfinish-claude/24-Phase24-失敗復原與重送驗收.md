# Phase 24：失敗復原與重送驗收

| 項目 | 內容 |
|---|---|
| 上一階段 | Phase 23：Demo 控制台與 Dashboard（`23-Phase23-Demo控制台與Dashboard.md`） |
| 下一階段 | Phase 25：安全檢查與 Demo 當日準備（`25-Phase25-安全檢查與Demo當日準備.md`） |
| 對應設計文件章節 | §8.2、§8.3、§14.1、§14.2、§15、§16、§18 的 O2 與 O3（`docs/design/training-kb.md`） |
| 對應交付切片 | S0、S8（設計文件第 16 節） |
| 預估時間 | 約 8 小時 |
| 做完會得到 | 一組可以在五個切點注入失敗的開關、一份整合測試證明「失敗時讀者還是看到舊版、重送時沿用原版號補齊並成功發布」，以及一份可追溯的驗收紀錄。 |

---

## 1. 這階段做完會得到什麼

設計文件第 18 節列了七個「待確認事項」，其中兩個直接擋在這一階段前面：

- **O2（操作紀錄與接受順序）**：設計文件原話是「只靠 SDK 重試或共享 content 函式，就保證沒有重複與版本分叉」是**不能宣稱**的事。
- **O3（S3 公開與發布提交）**：設計文件 §8.3 原話是「**在解決之前，不可宣稱 publish 的故障驗收已通過**，也不能用『只是沒有連結』代替未發布內容不可公開」。

這一階段就是把這兩句話關掉的階段。做完會得到：

1. `training_kb/faults.py`：用環境變數 `TKB_FAULT=<切點名稱>` 在五個位置人為製造失敗。只在非正式環境啟用。
2. `content.py` 的 `publish` 變成可以重入（re-entrant）：已經提交交易但公開頁沒寫完的版本，重送時會補寫公開頁，而不是因為條件不符整個失敗。
3. `tests/integration/test_recovery.py`：八組整合測試，用 moto 在本機模擬 AWS，逐一驗證（a）到（f）六件事。
4. `infra/scripts/check_asl.py`：檢查三份 ASL 檔的每個 Task 都有 Retry 與 Catch、Catch 導向 `PipelineFailed`。
5. 一個標記 `aws` 的真實環境驗收測試，會把 execution ARN 與前後狀態寫成 `docs/plan/report/recovery-<時間>.md`。

**做完這一階段之前，不可以對任何人說「publish 的故障驗收已通過」。** 這是設計文件 §8.3 的原話，不是本文件加的限制。

---

## 2. 它在整張地圖的位置

```text
基礎層          01 骨架 -> 02 模型與鍵 -> 03 Repository(本機) -> 04 AWS 基礎建設
                                                                      |
AI 與內容層     05 Writing(Bedrock) -> 06 規則注入 -> 07 建立版本 -> 08 發布與退役 -> 09 圖譜查詢
                                                                                        |
接入層          10 Ingress 驗簽 -> 11 Rote 判定 -> 12 Rote Agent -------------------------+
                                                                                        |
流程層          13 Ticket Analysis -> 14 Step Functions 上線 -> 15 Feedback/View 匯入 -> 16 Release Update
                                                                                        |
學習層          17 Review:REFINE -> 18 Review:候選規則+排程 -> 19 Analytics 指標 -> 20 規則驗證
                                                                                        |
展示與驗收層    21 Demo 種子資料 -> 22 靜態教學站 -> 23 Demo 控制台 -> 24 失敗復原驗收 -> 25 安全與當日準備
                                                                     ^^^^^^^^^^^^^^^^
                                                                      ★ 你在這裡 ★
```

Phase 24 不做新功能。它回頭檢查 Phase 07、08、10、14 做出來的東西在**壞掉的時候**行為對不對。所以它同時屬於切片 S0（「O2／O3 的最小整合驗證有可追溯結果」）與切片 S8（「一次儲存失敗復原」）。

---

## 3. 開始前檢查

| # | 前置條件 | 驗證指令 | 預期輸出 |
|---|---|---|---|
| 1 | Phase 07 的版本建立函式存在 | `uv run python -c "from training_kb.content import allocate_version, create_version, verify_version_complete; print('ok')"` | 印出 `ok` |
| 2 | Phase 08 的發布與退役函式存在 | `uv run python -c "from training_kb.content import publish, publish_to_site, with_tutorial_lock; print('ok')"` | 印出 `ok` |
| 3 | Phase 08 的站台 key 函式存在 | `uv run python -c "from training_kb.site import SiteRenderer, site_keys; print(site_keys('a', 1))"` | 印出含 `page`、`diff`、`index`、`root` 的字典 |
| 4 | Phase 10 的接入函式存在 | `uv run python -c "from training_kb.ingress import accept_ticket, accept_release, execution_name; print('ok')"` | 印出 `ok` |
| 5 | Phase 03 的操作紀錄與鎖存在 | `uv run python -c "from training_kb.repository import Repository; r=Repository; print(hasattr(r,'begin_operation'), hasattr(r,'acquire_lock'))"` | 印出 `True True` |
| 6 | Phase 01 的錯誤分類存在 | `uv run python -c "from training_kb.errors import TransientError, PermanentError; print('ok')"` | 印出 `ok` |
| 7 | `moto` 已安裝 | `uv run python -c "from moto import mock_aws; print('ok')"` | 印出 `ok`；沒有就執行 `uv add --dev moto` |
| 8 | Phase 14 的 ASL 檔存在 | `ls infra/asl/` | 列出 `ticket-analysis.asl.json`、`release-update.asl.json`、`feedback-review.asl.json` |

這階段只有 `(h)` 那一組測試需要真實 AWS。其餘全部在本機用 moto 跑，不花錢、不需要網路。

---

## 4. 名詞小抄

| 名詞 | 白話解釋 | 在本階段哪裡用到 |
|---|---|---|
| 切點（fault point） | 程式裡一個特定位置。我們在那裡放一個開關，打開時就故意丟出例外，用來模擬「剛好在這一步斷掉」。 | Task 1、Task 2 |
| 注入失敗（fault injection） | 人為讓程式在指定位置失敗，藉此檢查善後處理對不對。 | 全部 |
| 冪等（idempotent） | 同一件事做一次和做很多次，結果一樣。`accept_ticket` 對同一個事件必須冪等。 | Task 4、Task 6 |
| 重入（re-entrant） | 同一個函式被中斷後再呼叫一次，能接著把沒做完的部分做完，而不是從頭重來或直接報錯。 | Task 3 |
| `operation_id` | 一次「邏輯操作」的編號，例如 `ingest:ticket:t_881`。同一個編號代表同一件事，重送不算新的一件事。 | 全部 |
| 操作紀錄（operation record） | 存在 DynamoDB `OPS#<operation_id>` 與 S3 `operations/<id>.json` 的執行資訊：這次分配到哪個版號、模型輸出是什麼、做到哪一步。**本計劃選擇（對應 O2）。** | Task 4、Task 5 |
| 鎖（lock） | 一把「同一時間只有一個人能拿」的標記，存在 `LOCK#<slug>`。拿到的人才能改那篇教學。**本計劃選擇（對應 O2）。** | Task 8 |
| DynamoDB 交易（transaction） | 一次送出多個寫入，全部成功或全部不生效，不會只成功一半。 | Task 2、Task 3 |
| 條件寫入（conditional write） | 寫入時附帶一個條件，條件不成立就拒絕寫入。用來確保「基底沒有被別人改過」。 | Task 3、Task 8 |
| `current_version` | Tutorial 上指向「讀者現在看到哪一版」的欄位。只有 publish 成功回傳時才切換（釐清 F37）。 | 全部 |
| `published_at` | 版本上的上架時間。空值代表未發布（釐清 D25）。 | 全部 |
| `site/` | S3 上唯一公開的前綴。只有發布流程可以寫。 | Task 2、Task 3 |
| Retry（ASL） | Step Functions 的重試設定：某種錯誤發生時自動再試幾次。 | Task 9 |
| Catch（ASL） | Step Functions 的攔截設定：錯誤發生時跳到哪個 state。本案一律跳到 `PipelineFailed`。 | Task 9 |
| `PipelineFailed` | 一個 `Type` 是 `Fail` 的 state，代表整次執行以失敗結束。 | Task 9 |
| `ExecutionAlreadyExists` | Step Functions 的例外：同名執行已經存在。設計 §14.2 規定不可以把它直接當成功。 | Task 8 |
| `describe_execution` | boto3 的 Step Functions API，用 execution ARN 查一次執行的狀態（`RUNNING`／`SUCCEEDED`／`FAILED`／`TIMED_OUT`／`ABORTED`／`PENDING_REDRIVE`）。 | Task 10 |
| moto | Python 套件，在本機假裝自己是 AWS。用 `with mock_aws():` 包起來，boto3 的呼叫就不會真的出去。 | Task 4 起 |
| `@pytest.mark.aws` | 測試標記。本專案約定：只有環境變數 `TKB_RUN_AWS_TESTS=1` 時才跑這類需要真實 AWS 的測試。 | Task 10 |

---

## 5. 設計說明

### 5.1 為什麼要自己製造失敗

設計文件 §15「測試與驗收設計」列了一張表，其中三列直接是這一階段的驗收：

| 驗收範圍 | 必須看見的結果（原文） |
|---|---|
| 版本與發布 | 同篇 Release／Feedback 按接受順序；重試同版號；v1 空 diff；S3 或邊寫入失敗時 current_version 不變。 |
| 接入去重 | 同事件重送只對應一次邏輯處理；保存後但啟動前失敗可辨識，不遺失也不重複建版。 |
| 呼叫與失敗 | 每個 Task 有 Retry／Catch；終止不發布不合規內容；重試、Map、Rote、embedding 都計入實際請求數。 |

「S3 寫入失敗時 current_version 不變」這件事，不可能靠等待真的斷線來驗證。所以要有一個可控的開關，讓我們在想要的位置、想要的時間讓它斷掉。

### 5.2 五個切點與發布時間軸

```text
 一次「建版 + 發布」的完整時間軸（設計 §8.2 的流程圖）

 ①分配版號          ②驗證五段內容        ③寫 S3 md      ④寫 S3 diff
 allocate_version -> validate_content -> put_object -> put_object
                                             |              |
                                    [s3_after_md]           |
                                                            v
 ⑤寫 VERSION META  ⑥寫 STEP+REFERENCES  ⑦寫 SUPERSEDES/APPLIED_TO
 put_meta ---------> put_edge/put_meta -> put_edge
      |
 [ddb_after_version]
                                                            |
                                                            v
 ⑧核對齊全            ⑨DynamoDB 交易                ⑩寫 site/
 verify_version_    transact_write(published_at    publish_to_site
 complete           + current_version)
      |                     |                            |
      |          [publish_before_transact]   [publish_after_transact_before_site]
      |
      +-- 另一條路：接入層
          ⑪保存 TICKET/RELEASE -> ⑫starter.start(...)
                                        |
                                 [start_execution]
```

方括號裡就是五個切點的名稱。名稱直接說明「失敗發生在哪兩步之間」。

### 5.3 每個切點失敗後，系統應該長什麼樣

```text
切點                                 current_    v2 的        私有產物        site/ 有
                                     version     published_at (md/diff)      v2 頁？
-----------------------------------  ----------  -----------  -------------  --------
s3_after_md                          v1（不變）   VERSION 未建  md 有、diff 無  沒有
ddb_after_version                    v1（不變）   None         md 有、diff 有  沒有
publish_before_transact              v1（不變）   None         齊全            沒有
publish_after_transact_before_site   v2（已切換） 有值         齊全            沒有 ← O3 的缺口
start_execution                      v1（不變）   不適用       不適用          沒有
-----------------------------------  ----------  -----------  -------------  --------
共同點：讀者在任何一個切點失敗後，打開公開站看到的都還是 v1 的內容。
```

前三個切點與第五個切點，行為完全符合釐清 F36（「保留不可公開的待完成版本，待 S3、版本與關聯全部就緒後才允許發布」）與 F37（「publish 成功回傳時切換 current_version」）。

**第四個切點是設計文件 O3 明說的缺口**：DynamoDB 交易沒辦法和 S3 公開切換綁在同一個交易裡。設計文件原話是「DynamoDB 交易不能同時提交 S3 網站的公開切換」。所以這個切點失敗時，資料庫已經說「v2 是目前版本」，但公開站上還沒有 v2 的 HTML。

**本計劃選擇（對應 O3）**：接受這個中間狀態存在，但要求它「可以被補齊」。做法是讓 `publish` 變成可以重入：重送時先看這個版本是不是已經提交過交易，如果是，就只補寫 `site/`，不再跑一次條件交易（因為條件 `current_version == supersedes` 已經不成立了）。這樣讀者只會短暫看到舊版，不會看到半完成的新版，也不會卡在永遠無法發布的狀態。

這條補償路徑會在 Task 3 實作、Task 4 驗證。設計文件 §8.3 另外要求「不能用『只是沒有連結』代替未發布內容不可公開」——所以我們補的是公開頁本身，不是加一個連結。

### 5.4 重送時發生什麼（O2 的流程）

```text
  同一個事件第二次送達（同一個 delivery_id / operation_id）
                       |
                       v
        repo.begin_operation(operation_id, ...)
          條件寫入：OPS#<id> 不存在才寫
                       |
        +--------------+---------------+
        | 回傳 True                     | 回傳 False（已經有人做過或正在做）
        v                              v
   這是新事件                     讀 repo.load_operation(operation_id)
   照正常流程走                          |
                          +--------------+---------------+
                          | status == "done"             | status != "done"
                          v                              v
                  回傳既有結果                    沿用未完成執行：
                  status="duplicate"              重用原本分配的 version_id，
                  execution_arn = 既有             補齊缺的產物，再發布
                  不新增版本、不新增回饋樣本、
                  不新增 PROC 成功樣本
```

這張圖同時落實三條 Rule：`接入來源事件.feature` Rule 30「同一正規化事件重送時只處理一次」、`建立教學版本.feature` Rule 1 的「同一邏輯變更重試重用原版號」（釐清 D26），以及 `收集教學回饋.feature` Rule 10 的「只排除同一提交的重送」（釐清 D14）。

### 5.5 為什麼注入的失敗是 `TransientError`

`InjectedFault` 繼承 `TransientError`（可重試的錯誤）。原因是：Step Functions 的 Retry 設定只攔 `TransientError`，所以注入的失敗會先被重試兩次（間隔 1 秒、2 秒），兩次都因為環境變數還在而再次失敗，最後才落到 Catch 的 `PipelineFailed`。這正好一次走完設計文件 §14.2 規定的「Retry 用完 → Catch → 失敗終點」整條路，比直接丟不可重試的錯誤更能驗證 ASL 設定。

### 5.6 這階段的目錄結構

```text
AWS-Hackathon/
  src/training_kb/
    faults.py                 ★ Task 1：TKB_FAULT 開關與五個切點名稱
    content.py                ★ Task 2、3：插入四個切點 + publish 重入補償
    ingress.py                ★ Task 2、8：插入 start_execution 切點 + 同名執行判斷
  infra/
    asl/
      ticket-analysis.asl.json      （Phase 14 產出，本階段只檢查）
      release-update.asl.json       （Phase 16 產出，本階段只檢查）
      feedback-review.asl.json      （Phase 18 產出，本階段只檢查）
    scripts/
      check_asl.py            ★ Task 9：Retry／Catch 檢查腳本
  tests/
    unit/
      test_faults.py          ★ Task 1
      test_check_asl.py       ★ Task 9
      test_existing_execution.py  ★ Task 8
    integration/
      test_recovery.py        ★ Task 4–8、10：本階段的主戰場
  docs/plan/report/
    recovery-<YYYYMMDD-HHMM>.md     ★ Task 10 產出的可追溯驗收紀錄
    assets/                          ★ 截圖放這裡
```

---

## 6. 工作項目

### Task 1：`training_kb/faults.py` 失敗注入開關

**目的**：用一個環境變數決定「在哪個切點丟例外」，而且正式環境一定不會被觸發。

**檔案**：
- 新增：`src/training_kb/faults.py`
- 測試：`tests/unit/test_faults.py`

**介面**：
- 消費：`training_kb.errors.TransientError`（Phase 01）
- 產出：
  - `training_kb.faults.FAULT_POINTS: tuple[str, ...]`
  - `training_kb.faults.InjectedFault(TransientError)`
  - `training_kb.faults.active_fault(env: Mapping[str, str] | None = None) -> str | None`
  - `training_kb.faults.maybe_fail(point: str, env: Mapping[str, str] | None = None) -> None`

- [ ] **步驟 1：寫測試**

```python
# tests/unit/test_faults.py
from __future__ import annotations

import pytest

from training_kb.errors import TransientError
from training_kb.faults import FAULT_POINTS, InjectedFault, active_fault, maybe_fail


def test_五個切點名稱固定():
    assert FAULT_POINTS == (
        "s3_after_md",
        "ddb_after_version",
        "publish_before_transact",
        "publish_after_transact_before_site",
        "start_execution",
    )


def test_沒有設環境變數時不注入():
    assert active_fault({}) is None
    maybe_fail("s3_after_md", {})  # 不應該丟例外


def test_設了切點就在那個切點丟例外():
    env = {"TKB_FAULT": "s3_after_md"}
    assert active_fault(env) == "s3_after_md"
    with pytest.raises(InjectedFault) as exc:
        maybe_fail("s3_after_md", env)
    assert exc.value.point == "s3_after_md"
    assert "s3_after_md" in str(exc.value)


def test_其他切點不受影響():
    env = {"TKB_FAULT": "s3_after_md"}
    maybe_fail("ddb_after_version", env)
    maybe_fail("publish_before_transact", env)


def test_注入的失敗屬於可重試錯誤():
    assert issubclass(InjectedFault, TransientError)


def test_正式環境一律不注入():
    env = {"TKB_FAULT": "s3_after_md", "TKB_ENV": "prod"}
    assert active_fault(env) is None
    maybe_fail("s3_after_md", env)
    upper = {"TKB_FAULT": "s3_after_md", "TKB_ENV": "PROD"}
    assert active_fault(upper) is None


def test_空字串與空白視同沒設定():
    assert active_fault({"TKB_FAULT": ""}) is None
    assert active_fault({"TKB_FAULT": "   "}) is None


def test_未知的切點名稱立刻報錯():
    with pytest.raises(ValueError) as exc:
        active_fault({"TKB_FAULT": "somewhere_else"})
    assert "somewhere_else" in str(exc.value)
    assert "s3_after_md" in str(exc.value)


def test_呼叫端傳錯切點名稱也報錯():
    with pytest.raises(ValueError):
        maybe_fail("not_a_point", {})


def test_預設讀真正的環境變數(monkeypatch):
    monkeypatch.delenv("TKB_FAULT", raising=False)
    monkeypatch.delenv("TKB_ENV", raising=False)
    assert active_fault() is None
    monkeypatch.setenv("TKB_FAULT", "start_execution")
    assert active_fault() == "start_execution"
    with pytest.raises(InjectedFault):
        maybe_fail("start_execution")
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：`uv run pytest tests/unit/test_faults.py -v`

預期：FAIL，錯誤訊息是 `ModuleNotFoundError: No module named 'training_kb.faults'`，因為這個檔案還不存在。

- [ ] **步驟 3：寫最少的程式讓測試通過**

```python
# src/training_kb/faults.py
"""人為注入失敗的開關，只用於驗收失敗復原。

用法：設定環境變數 TKB_FAULT=<切點名稱>，程式跑到那個切點就丟 InjectedFault。

安全限制：
1. 只有五個固定的切點名稱，打錯字會立刻報錯，不會安靜地不生效。
2. TKB_ENV=prod 時一律不注入。正式部署不設定 TKB_FAULT，也把 TKB_ENV 設成 prod。
3. InjectedFault 繼承 TransientError，所以會先被 Step Functions 的 Retry 攔到，
   重試耗盡後才進 Catch 的 PipelineFailed（設計文件 §14.2）。
"""

from __future__ import annotations

import os
from collections.abc import Mapping

from training_kb.errors import TransientError

FAULT_POINTS: tuple[str, ...] = (
    # 寫完 tutorials/<slug>/v<n>.md 之後、寫 .diff 之前
    "s3_after_md",
    # 寫完 VERSION META 之後、寫 STEP items 之前
    "ddb_after_version",
    # publish 的 DynamoDB 交易送出之前
    "publish_before_transact",
    # 交易已提交、開始寫 site/ 之前
    "publish_after_transact_before_site",
    # 物件已保存、呼叫 StartExecution 之前
    "start_execution",
)

_ENV_FAULT = "TKB_FAULT"
_ENV_ENV = "TKB_ENV"


class InjectedFault(TransientError):
    """由 TKB_FAULT 注入的人工失敗；正式環境不會出現。"""

    def __init__(self, point: str) -> None:
        super().__init__(f"注入失敗切點：{point}")
        self.point = point


def _check_point(point: str) -> None:
    if point not in FAULT_POINTS:
        raise ValueError(
            f"未知的失敗切點：{point}；可用的切點是 {'、'.join(FAULT_POINTS)}"
        )


def active_fault(env: Mapping[str, str] | None = None) -> str | None:
    """目前啟用的切點名稱；沒有啟用就回傳 None。"""
    source = os.environ if env is None else env
    if source.get(_ENV_ENV, "dev").strip().lower() == "prod":
        return None
    point = source.get(_ENV_FAULT, "").strip()
    if not point:
        return None
    _check_point(point)
    return point


def maybe_fail(point: str, env: Mapping[str, str] | None = None) -> None:
    """在指定切點檢查是否要注入失敗。沒有啟用就什麼都不做。"""
    _check_point(point)
    if active_fault(env) == point:
        raise InjectedFault(point)
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：`uv run pytest tests/unit/test_faults.py -v`

預期：PASS，10 個測試全綠。

- [ ] **步驟 5：commit**

```bash
git add src/training_kb/faults.py tests/unit/test_faults.py
git commit -m "feat(faults): 以 TKB_FAULT 在五個切點注入失敗"
```

---

### Task 2：把五個切點插進 `content.py` 與 `ingress.py`

**目的**：讓開關真的能在正確位置生效。

**檔案**：
- 修改：`src/training_kb/content.py`
- 修改：`src/training_kb/ingress.py`
- 測試：`tests/unit/test_fault_points_wired.py`

**介面**：
- 消費：`training_kb.faults.maybe_fail(point)`（Task 1）
- 產出：無新介面（只在既有函式裡插入呼叫）

這個 Task 只加入五行程式加兩行 import。每一行都有明確的錨點，照著找就不會插錯位置。

- [ ] **步驟 1：寫測試**

```python
# tests/unit/test_fault_points_wired.py
"""護欄測試：確認五個切點都真的接到程式裡，而且順序正確。

這裡不跑 AWS，只讀原始碼檢查。行為層面的驗收在 tests/integration/test_recovery.py。
"""

from __future__ import annotations

from pathlib import Path

import pytest

CONTENT = Path("src/training_kb/content.py")
INGRESS = Path("src/training_kb/ingress.py")


@pytest.fixture(scope="module")
def content_src() -> str:
    return CONTENT.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def ingress_src() -> str:
    return INGRESS.read_text(encoding="utf-8")


def test_content_匯入了_maybe_fail(content_src):
    assert "from training_kb.faults import maybe_fail" in content_src


def test_ingress_匯入了_maybe_fail(ingress_src):
    assert "from training_kb.faults import maybe_fail" in ingress_src


def test_content_有四個切點(content_src):
    for point in (
        "s3_after_md",
        "ddb_after_version",
        "publish_before_transact",
        "publish_after_transact_before_site",
    ):
        assert f'maybe_fail("{point}")' in content_src, f"content.py 缺少切點 {point}"


def test_ingress_有_start_execution_切點(ingress_src):
    assert 'maybe_fail("start_execution")' in ingress_src


def test_md_切點在_diff_之前(content_src):
    at_md = content_src.index('maybe_fail("s3_after_md")')
    at_version = content_src.index('maybe_fail("ddb_after_version")')
    assert at_md < at_version


def test_交易切點在寫站台切點之前(content_src):
    at_before = content_src.index('maybe_fail("publish_before_transact")')
    at_after = content_src.index('maybe_fail("publish_after_transact_before_site")')
    assert at_before < at_after


def test_start_execution_切點在_starter_start_之前(ingress_src):
    at_fault = ingress_src.index('maybe_fail("start_execution")')
    at_start = ingress_src.index("starter.start(")
    assert at_fault < at_start
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：`uv run pytest tests/unit/test_fault_points_wired.py -v`

預期：FAIL，第一個測試就掛：`AssertionError: assert 'from training_kb.faults import maybe_fail' in ...`。因為還沒插進去。

- [ ] **步驟 3：寫最少的程式讓測試通過**

**修改 1：`src/training_kb/content.py` 的 import 區塊**，加上這一行（放在其他 `from training_kb...` 匯入的旁邊）：

```python
from training_kb.faults import maybe_fail
```

**修改 2：`create_version()` 內，寫完 md 之後**。找到寫 `tutorials/<slug>/v<n>.md` 的那一行（長得像 `repo.put_object(md_key, markdown, ...)`），在它的**下一行**插入：

```python
    maybe_fail("s3_after_md")  # Phase 24 切點：md 已寫、diff 未寫
```

**修改 3：`create_version()` 內，寫完 VERSION META 之後**。找到寫 VERSION metadata 的那一行（長得像 `repo.put_meta(version_pk(plan.version_id), {...})`），在它的**下一行**插入：

```python
    maybe_fail("ddb_after_version")  # Phase 24 切點：VERSION 已寫、STEP 未寫
```

**修改 4：`publish()` 內，送出交易之前**。找到 `repo.transact_write(` 那一行，在它的**上一行**插入：

```python
    maybe_fail("publish_before_transact")  # Phase 24 切點：交易尚未送出
```

**修改 5：`publish_to_site()` 函式本體的第一行**（在 docstring 後面、任何實際動作之前）插入：

```python
    maybe_fail("publish_after_transact_before_site")  # Phase 24 切點：交易已提交、公開頁未寫
```

**修改 6：`src/training_kb/ingress.py` 的 import 區塊**，加上：

```python
from training_kb.faults import maybe_fail
```

**修改 7：`accept_ticket()` 與 `accept_release()` 內**，找到 `starter.start(` 那一行，在它的**上一行**各插入一次：

```python
    maybe_fail("start_execution")  # Phase 24 切點：物件已保存、流程尚未啟動
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：`uv run pytest tests/unit/test_fault_points_wired.py -v`

預期：PASS，7 個測試全綠。

接著確認沒有弄壞既有測試：

```bash
uv run pytest tests/ -q
```

預期：原本會通過的測試全部仍然通過（因為沒有設 `TKB_FAULT`，`maybe_fail` 什麼都不做）。

- [ ] **步驟 5：commit**

```bash
git add src/training_kb/content.py src/training_kb/ingress.py tests/unit/test_fault_points_wired.py
git commit -m "feat(faults): 在建版、發布與啟動流程插入五個切點"
```

---

### Task 3：`publish` 的重入補償（O3 的缺口處理）

**目的**：交易已提交但公開頁沒寫完時，重送要能只補公開頁，而不是被條件擋住永遠發不出去。

**檔案**：
- 修改：`src/training_kb/content.py`
- 測試：`tests/integration/test_recovery.py`（本 Task 建立這個檔案的骨架與第一組測試）

**介面**：
- 消費：`training_kb.site.site_keys(slug, n) -> dict[str, str]`、`training_kb.content.publish_to_site(repo, renderer, slug, version_id) -> list[str]`、`training_kb.models.parse_version_id(version_id) -> tuple[str, int]`、`training_kb.repository.Repository.object_exists(key) -> bool`
- 產出：
  - `training_kb.content.PublishTargets`（dataclass：`remaining: list[str]`、`resumed: list[str]`、`missing: str | None`）
  - `training_kb.content.split_publish_targets(repo, version_ids, renderer) -> PublishTargets`
  - `training_kb.content.publish(...)`（外層改為重入版本；原本的實作改名為 `_publish_new`）

- [ ] **步驟 1：寫測試**

```python
# tests/integration/test_recovery.py
"""Phase 24：失敗復原與重送的整合驗收。

全部使用 moto 在本機模擬 AWS，不需要網路也不花錢。
標記 aws 的那一組例外，只有 TKB_RUN_AWS_TESTS=1 才執行。
"""

from __future__ import annotations

from datetime import datetime, timezone

import boto3
import pytest
from moto import mock_aws

from training_kb.content import (
    allocate_version,
    create_tutorial,
    create_version,
    publish,
    split_publish_targets,
    verify_version_complete,
)
from training_kb.faults import InjectedFault
from training_kb.models import (
    Feature,
    StepDraft,
    StepType,
    TutorialContent,
)
from training_kb.repository import Repository
from training_kb.site import SiteRenderer, site_keys

REGION = "us-west-2"
TABLE = "training_kb_recovery_test"
BUCKET = "training-kb-recovery-test"
NOW = datetime(2026, 9, 13, 10, 0, 0, tzinfo=timezone.utc)

SLUG_A = "prepare-meeting"
SLUG_B = "share-summary"


def make_content(marker: str, feature_id: str = "Prepare") -> TutorialContent:
    """四步的教學內容；marker 讓不同版本的文字不同，方便看 diff。"""
    return TutorialContent(
        title=f"準備會議（{marker}）",
        problem="使用者找不到會前摘要要在哪裡開啟。",
        prerequisites=["已經建立一場會議"],
        steps=[
            StepDraft(
                type=StepType.read,
                text=f"打開會議清單（{marker}）",
                feature_id=feature_id,
            ),
            StepDraft(
                type=StepType.click_ui,
                text=f"點選要準備的會議（{marker}）",
                feature_id=feature_id,
            ),
            StepDraft(
                type=StepType.click_ui,
                text=f"在右上角選擇 Prepare（{marker}）",
                feature_id=feature_id,
            ),
            StepDraft(
                type=StepType.read,
                text=f"閱讀自動整理的重點（{marker}）",
                feature_id=feature_id,
            ),
        ],
        expected_outcome="看到這場會議的會前摘要。",
    )


@pytest.fixture()
def repo(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", REGION)
    monkeypatch.delenv("TKB_FAULT", raising=False)
    monkeypatch.delenv("TKB_ENV", raising=False)
    with mock_aws():
        ddb = boto3.resource("dynamodb", region_name=REGION)
        ddb.create_table(
            TableName=TABLE,
            KeySchema=[
                {"AttributeName": "PK", "KeyType": "HASH"},
                {"AttributeName": "SK", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "PK", "AttributeType": "S"},
                {"AttributeName": "SK", "AttributeType": "S"},
                {"AttributeName": "target", "AttributeType": "S"},
            ],
            GlobalSecondaryIndexes=[
                {
                    "IndexName": "by_target",
                    "KeySchema": [{"AttributeName": "target", "KeyType": "HASH"}],
                    "Projection": {"ProjectionType": "ALL"},
                }
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        s3 = boto3.client("s3", region_name=REGION)
        s3.create_bucket(
            Bucket=BUCKET,
            CreateBucketConfiguration={"LocationConstraint": REGION},
        )
        yield Repository(ddb.Table(TABLE), s3, BUCKET)


@pytest.fixture()
def renderer() -> SiteRenderer:
    return SiteRenderer()


def site_key_set(repo) -> set[str]:
    """目前公開區有哪些 key。"""
    listed = repo.s3.list_objects_v2(Bucket=BUCKET, Prefix="site/")
    return {obj["Key"] for obj in listed.get("Contents", [])}


def seed_feature(repo, feature_id: str = "Prepare") -> None:
    repo.put_meta(
        f"FEATURE#{feature_id}",
        {
            "entity": "FEATURE",
            "name": feature_id,
            "aliases": [],
            "first_seen": "2026-08-01T00:00:00Z",
        },
    )


def make_published_v1(repo, renderer, slug: str, feature_id: str = "Prepare") -> str:
    """建立一篇教學並發布 v1，回傳 v1 的 version_id。"""
    seed_feature(repo, feature_id)
    create_tutorial(
        repo,
        slug=slug,
        topic=slug,
        feature_ids=[feature_id],
        cluster_id="c12",
        now=NOW,
    )
    operation_id = f"gap:c12:{slug}"
    repo.begin_operation(operation_id, {"kind": "gap", "slug": slug, "status": "running"})
    plan = allocate_version(repo, slug, operation_id, "gap:c12", [])
    create_version(repo, plan, make_content("v1", feature_id), now=NOW)
    result = publish(repo, [plan.version_id], renderer, now=NOW)
    assert result.failed is None
    repo.update_operation(operation_id, {"status": "done"})
    return plan.version_id


def start_v2(repo, slug: str, operation_id: str, reason: str):
    """為既有教學分配 v2 的版號。"""
    repo.begin_operation(
        operation_id, {"kind": "release", "slug": slug, "status": "running"}
    )
    return allocate_version(repo, slug, operation_id, reason, [])


# ---------------------------------------------------------------- Task 3 的測試


def test_全新版本不會被判成已提交(repo, renderer):
    v1 = make_published_v1(repo, renderer, SLUG_A)
    plan = start_v2(repo, SLUG_A, "release:r_42", "release:r_42")
    create_version(repo, plan, make_content("v2"), now=NOW)

    targets = split_publish_targets(repo, [plan.version_id], renderer)
    assert targets.remaining == [plan.version_id]
    assert targets.resumed == []
    assert targets.missing is None
    assert repo.get_tutorial(SLUG_A).current_version == v1


def test_版本不存在時整批標成缺漏(repo, renderer):
    make_published_v1(repo, renderer, SLUG_A)
    targets = split_publish_targets(repo, ["prepare-meeting@v9"], renderer)
    assert targets.missing == "prepare-meeting@v9"
    assert targets.remaining == []


def test_已提交且公開頁齊全的版本視為完成(repo, renderer):
    make_published_v1(repo, renderer, SLUG_A)
    plan = start_v2(repo, SLUG_A, "release:r_42", "release:r_42")
    create_version(repo, plan, make_content("v2"), now=NOW)
    publish(repo, [plan.version_id], renderer, now=NOW)

    targets = split_publish_targets(repo, [plan.version_id], renderer)
    assert targets.resumed == [plan.version_id]
    assert targets.remaining == []


def test_交易已提交但公開頁缺少時會補寫(repo, renderer):
    make_published_v1(repo, renderer, SLUG_A)
    plan = start_v2(repo, SLUG_A, "release:r_42", "release:r_42")
    create_version(repo, plan, make_content("v2"), now=NOW)
    publish(repo, [plan.version_id], renderer, now=NOW)

    # 人為刪掉公開頁，模擬「交易提交了但 site/ 沒寫完」
    page = site_keys(SLUG_A, 2)["page"]
    repo.s3.delete_object(Bucket=BUCKET, Key=page)
    assert repo.object_exists(page) is False

    targets = split_publish_targets(repo, [plan.version_id], renderer)
    assert targets.resumed == [plan.version_id]
    assert repo.object_exists(page) is True


def test_重入的_publish_回傳已補齊的版本(repo, renderer):
    make_published_v1(repo, renderer, SLUG_A)
    plan = start_v2(repo, SLUG_A, "release:r_42", "release:r_42")
    create_version(repo, plan, make_content("v2"), now=NOW)
    publish(repo, [plan.version_id], renderer, now=NOW)
    repo.s3.delete_object(Bucket=BUCKET, Key=site_keys(SLUG_A, 2)["page"])

    again = publish(repo, [plan.version_id], renderer, now=NOW)
    assert again.failed is None
    assert again.published == [plan.version_id]
    assert repo.get_tutorial(SLUG_A).current_version == plan.version_id
    assert verify_version_complete(repo, plan.version_id) == []
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：`uv run pytest tests/integration/test_recovery.py -v`

預期：FAIL，`ImportError: cannot import name 'split_publish_targets' from 'training_kb.content'`。

- [ ] **步驟 3：寫最少的程式讓測試通過**

在 `src/training_kb/content.py` 做兩件事。

**第一件：把原本的 `def publish(` 那一行改名**（只改函式名稱，內容一個字都不動）：

```python
def _publish_new(
    repo, version_ids: list[str], renderer: "SiteRenderer", *, now: datetime
) -> PublishResult:
```

**第二件：在 `_publish_new` 後面新增下面這一整段。** 這是新的對外入口，名稱與參數與原本的 `publish` 完全相同，所以呼叫端（Phase 13、16、17 的 pipelines）一行都不用改。

```python
@dataclass
class PublishTargets:
    """把待發布清單分成三類。

    remaining：還沒提交交易，要走完整的發布流程。
    resumed：交易已經提交過；缺公開頁就在分類時補寫，補完算完成。
    missing：找不到的版本 ID；只要有一個，整批就不發布（釐清 F49）。
    """

    remaining: list[str]
    resumed: list[str]
    missing: str | None


def split_publish_targets(
    repo, version_ids: list[str], renderer: "SiteRenderer"
) -> PublishTargets:
    """分類待發布版本，並補寫「交易已提交但公開頁沒寫完」的那些。

    這是設計文件第 18 節 O3 的補償路徑（本計劃選擇）：
    DynamoDB 交易沒辦法和 S3 公開切換綁在同一個交易，
    所以允許中間狀態存在，但要求重送時能補齊，而不是永遠卡住。
    """
    remaining: list[str] = []
    resumed: list[str] = []
    for version_id in version_ids:
        version = repo.get_version(version_id)
        if version is None:
            return PublishTargets(remaining=[], resumed=[], missing=version_id)
        slug, number = parse_version_id(version_id)
        tutorial = repo.get_tutorial(slug)
        committed = (
            version.published_at is not None
            and tutorial is not None
            and tutorial.current_version == version_id
        )
        if not committed:
            remaining.append(version_id)
            continue
        if not repo.object_exists(site_keys(slug, number)["page"]):
            publish_to_site(repo, renderer, slug, version_id)
        resumed.append(version_id)
    return PublishTargets(remaining=remaining, resumed=resumed, missing=None)


def publish(
    repo, version_ids: list[str], renderer: "SiteRenderer", *, now: datetime
) -> PublishResult:
    """發布指定版本。可以重入：已提交的版本只補公開頁，不重跑條件交易。"""
    targets = split_publish_targets(repo, version_ids, renderer)
    if targets.missing is not None:
        return PublishResult(published=[], failed=targets.missing)
    if not targets.remaining:
        return PublishResult(published=sorted(targets.resumed), failed=None)
    result = _publish_new(repo, targets.remaining, renderer, now=now)
    if result.failed is not None:
        return result
    return PublishResult(
        published=sorted(targets.resumed + list(result.published)), failed=None
    )
```

如果 `content.py` 的檔首還沒有這些匯入，一併補上：

```python
from dataclasses import dataclass

from training_kb.models import parse_version_id
from training_kb.site import site_keys
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：`uv run pytest tests/integration/test_recovery.py -v`

預期：PASS，5 個測試全綠。再跑一次整包確認沒有弄壞 Phase 08 的測試：

```bash
uv run pytest tests/ -q
```

預期：全部通過。

- [ ] **步驟 5：commit**

```bash
git add src/training_kb/content.py tests/integration/test_recovery.py
git commit -m "feat(content): publish 可重入以補齊未完成的公開頁"
```

---

### Task 4：(a) 每個切點注入後的狀態驗收

**目的**：逐一驗證五個切點失敗後，`current_version` 與公開區的狀態符合第 5.3 節那張表。

**檔案**：
- 修改：`tests/integration/test_recovery.py`

**介面**：
- 消費：`training_kb.faults.InjectedFault`、`training_kb.content.create_version`、`publish`、`training_kb.site.site_keys`
- 產出：無新程式碼（只加測試）

- [ ] **步驟 1：寫測試**

```python
# tests/integration/test_recovery.py（在檔尾附加）
# ---------------------------------------------------------------- Task 4：(a)


def test_md_寫完就失敗時保留私有產物且不改_current_version(
    repo, renderer, monkeypatch
):
    v1 = make_published_v1(repo, renderer, SLUG_A)
    before = site_key_set(repo)
    plan = start_v2(repo, SLUG_A, "release:r_42", "release:r_42")

    monkeypatch.setenv("TKB_FAULT", "s3_after_md")
    with pytest.raises(InjectedFault):
        create_version(repo, plan, make_content("v2"), now=NOW)

    assert repo.object_exists(f"tutorials/{SLUG_A}/v2.md") is True
    assert repo.object_exists(f"tutorials/{SLUG_A}/v2.diff") is False
    assert repo.get_version(plan.version_id) is None
    assert repo.get_tutorial(SLUG_A).current_version == v1
    assert site_key_set(repo) == before


def test_VERSION_寫完就失敗時版本未發布且步驟不齊(repo, renderer, monkeypatch):
    v1 = make_published_v1(repo, renderer, SLUG_A)
    before = site_key_set(repo)
    plan = start_v2(repo, SLUG_A, "release:r_42", "release:r_42")

    monkeypatch.setenv("TKB_FAULT", "ddb_after_version")
    with pytest.raises(InjectedFault):
        create_version(repo, plan, make_content("v2"), now=NOW)

    version = repo.get_version(plan.version_id)
    assert version is not None
    assert version.published_at is None
    assert repo.get_steps(plan.version_id) == []
    assert verify_version_complete(repo, plan.version_id) != []
    assert repo.get_tutorial(SLUG_A).current_version == v1
    assert site_key_set(repo) == before


def test_交易前失敗時舊版仍是_current_version(repo, renderer, monkeypatch):
    v1 = make_published_v1(repo, renderer, SLUG_A)
    before = site_key_set(repo)
    plan = start_v2(repo, SLUG_A, "release:r_42", "release:r_42")
    create_version(repo, plan, make_content("v2"), now=NOW)

    monkeypatch.setenv("TKB_FAULT", "publish_before_transact")
    with pytest.raises(InjectedFault):
        publish(repo, [plan.version_id], renderer, now=NOW)

    assert repo.get_tutorial(SLUG_A).current_version == v1
    assert repo.get_version(plan.version_id).published_at is None
    assert site_key_set(repo) == before


def test_交易後寫站台前失敗是_O3_的缺口而且可以補齊(repo, renderer, monkeypatch):
    make_published_v1(repo, renderer, SLUG_A)
    plan = start_v2(repo, SLUG_A, "release:r_42", "release:r_42")
    create_version(repo, plan, make_content("v2"), now=NOW)

    monkeypatch.setenv("TKB_FAULT", "publish_after_transact_before_site")
    with pytest.raises(InjectedFault):
        publish(repo, [plan.version_id], renderer, now=NOW)

    # 交易已經提交：資料庫說 v2 是目前版本，但公開頁還沒寫。
    assert repo.get_tutorial(SLUG_A).current_version == plan.version_id
    assert repo.get_version(plan.version_id).published_at is not None
    page = site_keys(SLUG_A, 2)["page"]
    assert repo.object_exists(page) is False

    # 關掉開關重送：重入路徑補寫公開頁，不重跑條件交易。
    monkeypatch.delenv("TKB_FAULT")
    again = publish(repo, [plan.version_id], renderer, now=NOW)
    assert again.failed is None
    assert repo.object_exists(page) is True


def test_啟動流程前失敗時物件已保存但沒有新版本(repo, renderer, monkeypatch):
    make_published_v1(repo, renderer, SLUG_A)
    before = site_key_set(repo)

    from training_kb.faults import maybe_fail

    monkeypatch.setenv("TKB_FAULT", "start_execution")
    repo.put_meta(
        "TICKET#t_881",
        {
            "entity": "TICKET",
            "source": "github_issue",
            "text": "會前摘要在哪裡開啟？",
            "author": "u_01",
            "ts": "2026-09-13T09:00:00Z",
            "project_id": "demo-project",
        },
    )
    with pytest.raises(InjectedFault):
        maybe_fail("start_execution")

    assert repo.get_meta("TICKET#t_881") is not None
    assert repo.get_version("prepare-meeting@v2") is None
    assert site_key_set(repo) == before


def test_五個切點失敗後讀者看到的公開頁都還是舊版(repo, renderer, monkeypatch):
    v1 = make_published_v1(repo, renderer, SLUG_A)
    page_v1 = repo.get_object(site_keys(SLUG_A, 1)["page"]).decode("utf-8")
    plan = start_v2(repo, SLUG_A, "release:r_42", "release:r_42")

    monkeypatch.setenv("TKB_FAULT", "publish_before_transact")
    create_version(repo, plan, make_content("v2"), now=NOW)
    with pytest.raises(InjectedFault):
        publish(repo, [plan.version_id], renderer, now=NOW)

    assert repo.get_object(site_keys(SLUG_A, 1)["page"]).decode("utf-8") == page_v1
    assert repo.object_exists(site_keys(SLUG_A, 2)["page"]) is False
    assert repo.get_tutorial(SLUG_A).current_version == v1
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：`uv run pytest tests/integration/test_recovery.py -k "切點 or 缺口 or 舊版" -v`

預期：FAIL。如果 Task 2 的插入位置不對，這裡就會看到「沒有丟出 InjectedFault」或「diff 竟然存在」之類的斷言失敗。這正是這組測試存在的意義：它會抓出插錯位置。

- [ ] **步驟 3：寫最少的程式讓測試通過**

這個 Task 不新增產品程式碼。如果測試失敗，回頭修正 Task 2 的插入位置。常見修正：

- `s3_after_md` 插到 diff 的 `put_object` **之後**了 → 往上移一行，要在 md 之後、diff 之前。
- `ddb_after_version` 插到寫 STEP 之後 → 往上移，要在 VERSION META 之後、第一個 STEP 之前。
- `publish_before_transact` 插到 `transact_write` 之後 → 往上移一行。
- `publish_after_transact_before_site` 沒有插在 `publish_to_site` 的第一行 → 移到 docstring 的下一行。

如果 `repo.get_meta` 這個方法在你的 `Repository` 上叫別的名字，把測試裡的 `repo.get_meta("TICKET#t_881")` 換成 Phase 03 實際提供的讀取函式（介面契約上是 `get_meta(pk, *, consistent=True)`）。

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：`uv run pytest tests/integration/test_recovery.py -v`

預期：PASS，11 個測試全綠（Task 3 的 5 個加上這裡的 6 個）。

- [ ] **步驟 5：commit**

```bash
git add tests/integration/test_recovery.py
git commit -m "test(recovery): 五個切點失敗後的狀態驗收"
```

---

### Task 5：(b) 同一個 `operation_id` 重送沿用原版號並補齊

**目的**：驗證釐清 D26「同一邏輯變更重試時重用原版本號」與釐清 F36「待 S3、版本與關聯全部就緒後才允許發布」。

**檔案**：
- 修改：`tests/integration/test_recovery.py`

**介面**：
- 消費：`training_kb.content.allocate_version(repo, slug, operation_id, reason, rules_applied) -> VersionPlan`、`verify_version_complete(repo, version_id) -> list[str]`
- 產出：無新程式碼

- [ ] **步驟 1：寫測試**

```python
# tests/integration/test_recovery.py（在檔尾附加）
# ---------------------------------------------------------------- Task 5：(b)


def test_同_operation_id_重送沿用原版號(repo, renderer, monkeypatch):
    make_published_v1(repo, renderer, SLUG_A)
    operation_id = "release:r_42"

    plan_first = start_v2(repo, SLUG_A, operation_id, "release:r_42")
    monkeypatch.setenv("TKB_FAULT", "ddb_after_version")
    with pytest.raises(InjectedFault):
        create_version(repo, plan_first, make_content("v2"), now=NOW)

    monkeypatch.delenv("TKB_FAULT")
    plan_again = allocate_version(repo, SLUG_A, operation_id, "release:r_42", [])
    assert plan_again.version_id == plan_first.version_id == "prepare-meeting@v2"
    assert plan_again.supersedes == plan_first.supersedes


def test_重送補齊缺的產物後可以發布成功(repo, renderer, monkeypatch):
    v1 = make_published_v1(repo, renderer, SLUG_A)
    operation_id = "release:r_42"

    plan = start_v2(repo, SLUG_A, operation_id, "release:r_42")
    monkeypatch.setenv("TKB_FAULT", "ddb_after_version")
    with pytest.raises(InjectedFault):
        create_version(repo, plan, make_content("v2"), now=NOW)
    assert verify_version_complete(repo, plan.version_id) != []
    assert repo.get_tutorial(SLUG_A).current_version == v1

    monkeypatch.delenv("TKB_FAULT")
    plan_again = allocate_version(repo, SLUG_A, operation_id, "release:r_42", [])
    create_version(repo, plan_again, make_content("v2"), now=NOW)
    assert verify_version_complete(repo, plan_again.version_id) == []

    result = publish(repo, [plan_again.version_id], renderer, now=NOW)
    assert result.failed is None
    assert repo.get_tutorial(SLUG_A).current_version == "prepare-meeting@v2"
    assert repo.object_exists(site_keys(SLUG_A, 2)["page"]) is True


def test_重送不會跳號到_v3(repo, renderer, monkeypatch):
    make_published_v1(repo, renderer, SLUG_A)
    operation_id = "release:r_42"

    plan = start_v2(repo, SLUG_A, operation_id, "release:r_42")
    monkeypatch.setenv("TKB_FAULT", "s3_after_md")
    with pytest.raises(InjectedFault):
        create_version(repo, plan, make_content("v2"), now=NOW)

    monkeypatch.delenv("TKB_FAULT")
    for _ in range(3):
        again = allocate_version(repo, SLUG_A, operation_id, "release:r_42", [])
        assert again.version_id == "prepare-meeting@v2"
    assert repo.get_version("prepare-meeting@v3") is None


def test_不同_operation_id_才會拿到新版號(repo, renderer):
    make_published_v1(repo, renderer, SLUG_A)
    first = start_v2(repo, SLUG_A, "release:r_42", "release:r_42")
    create_version(repo, first, make_content("v2"), now=NOW)
    publish(repo, [first.version_id], renderer, now=NOW)

    second = start_v2(repo, SLUG_A, "feedback:2026-09-13", "feedback:8 則 找不到按鈕")
    assert second.version_id == "prepare-meeting@v3"
    assert second.supersedes == "prepare-meeting@v2"


def test_永久失敗後留下版號缺口是允許的(repo, renderer, monkeypatch):
    """釐清 D26：同一邏輯變更重試重用原版號；永久失敗可保留號碼缺口。"""
    make_published_v1(repo, renderer, SLUG_A)
    broken = start_v2(repo, SLUG_A, "release:bad", "release:bad")
    monkeypatch.setenv("TKB_FAULT", "s3_after_md")
    with pytest.raises(InjectedFault):
        create_version(repo, broken, make_content("bad"), now=NOW)
    monkeypatch.delenv("TKB_FAULT")

    # 放棄那次操作，改由另一個邏輯操作接手：基底仍是最近「已發布」的 v1。
    later = start_v2(repo, SLUG_A, "feedback:2026-09-14", "feedback:8 則 找不到按鈕")
    assert later.supersedes == "prepare-meeting@v1"
    create_version(repo, later, make_content("next"), now=NOW)
    assert publish(repo, [later.version_id], renderer, now=NOW).failed is None
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：`uv run pytest tests/integration/test_recovery.py -k "重送 or 版號 or 缺口" -v`

預期：如果 Phase 07 的 `allocate_version` 沒有依操作紀錄重用版號，會看到 `AssertionError: assert 'prepare-meeting@v3' == 'prepare-meeting@v2'`。

- [ ] **步驟 3：寫最少的程式讓測試通過**

這個 Task 不新增產品程式碼。若測試沒過，代表 Phase 07 的 `allocate_version` 需要修正：它必須先讀 `repo.load_operation(operation_id)`，看裡面有沒有已經記下來的 `version_id`；有就直接沿用，沒有才以最近「已發布」版本為基底 +1，並把結果寫回操作紀錄：

```python
# src/training_kb/content.py 的 allocate_version 內（Phase 07 的既有邏輯，這裡列出必要條件）
    record = repo.load_operation(operation_id) or {}
    if record.get("version_id"):
        # 同一邏輯變更的重試：沿用原版號（釐清 D26）
        version_id = record["version_id"]
        slug_from_record, number = parse_version_id(version_id)
        return VersionPlan(
            slug=slug_from_record,
            version_id=version_id,
            n=number,
            supersedes=record.get("supersedes"),
            reason=record.get("reason", reason),
            rules_applied=record.get("rules_applied", rules_applied),
            operation_id=operation_id,
        )
    # 以下才是分配新版號的路徑，分配完要寫回操作紀錄：
    # repo.update_operation(operation_id, {"version_id": ..., "supersedes": ..., "reason": ..., "rules_applied": ...})
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：`uv run pytest tests/integration/test_recovery.py -v`

預期：PASS，16 個測試全綠。

- [ ] **步驟 5：commit**

```bash
git add tests/integration/test_recovery.py src/training_kb/content.py
git commit -m "test(recovery): 重送沿用原版號並補齊後發布成功"
```

---

### Task 6：(c) 同一事件重送只對應一次邏輯處理

**目的**：驗證釐清 F09「同一事件只接受一次邏輯處理；重送回傳既有結果或沿用未完成執行」，而且重送**不新增版本、不新增回饋樣本、不新增 PROC 成功樣本**。

**檔案**：
- 修改：`tests/integration/test_recovery.py`

**介面**：
- 消費：`training_kb.ingress.accept_ticket(repo, starter, ticket, *, delivery_id, now) -> AcceptResult`、`import_feedback(repo, writer, data, *, now) -> ImportResult`、`training_kb.ingress.PipelineStarter`、`training_kb.rote.Rote.commit_success`
- 產出：`tests/integration/test_recovery.py::FakeStarter`（測試用，實作 `PipelineStarter` 協定）

- [ ] **步驟 1：寫測試**

```python
# tests/integration/test_recovery.py（在檔尾附加）
# ---------------------------------------------------------------- Task 6：(c)

from training_kb.ingress import accept_ticket, import_feedback
from training_kb.models import ProcStatus, ProvenWorkflow, Ticket, TicketSource
from training_kb.writing.client import CallTrace, FakeWriter


class FakeStarter:
    """實作 PipelineStarter 協定；記錄每次啟動，同名已存在時回傳既有 ARN。"""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict]] = []
        self.by_name: dict[str, str] = {}

    def start(self, pipeline: str, execution_name: str, input: dict) -> str:
        if execution_name in self.by_name:
            return self.by_name[execution_name]
        arn = f"arn:aws:states:us-west-2:1:execution:{pipeline}:{len(self.calls)}"
        self.by_name[execution_name] = arn
        self.calls.append((pipeline, execution_name, input))
        return arn


def make_ticket() -> Ticket:
    return Ticket(
        id="t_881",
        source=TicketSource.github_issue,
        text="會前摘要在哪裡開啟？",
        author="u_01",
        ts="2026-09-13T09:00:00Z",
        project_id="demo-project",
    )


def test_同一事件重送回傳既有結果且只啟動一次流程(repo, renderer):
    seed_feature(repo)
    starter = FakeStarter()
    ticket = make_ticket()

    first = accept_ticket(repo, starter, ticket, delivery_id="d-1", now=NOW)
    second = accept_ticket(repo, starter, ticket, delivery_id="d-1", now=NOW)

    assert first.status == "accepted"
    assert second.status == "duplicate"
    assert second.execution_arn == first.execution_arn
    assert len(starter.calls) == 1


def test_同一事件重送不新增教學版本(repo, renderer):
    make_published_v1(repo, renderer, SLUG_A)
    starter = FakeStarter()
    ticket = make_ticket()

    accept_ticket(repo, starter, ticket, delivery_id="d-1", now=NOW)
    versions_before = len(repo.list_versions_of_tutorial(SLUG_A))
    accept_ticket(repo, starter, ticket, delivery_id="d-1", now=NOW)
    assert len(repo.list_versions_of_tutorial(SLUG_A)) == versions_before


def test_同一筆回饋重送不增加回饋樣本(repo, renderer):
    v1 = make_published_v1(repo, renderer, SLUG_A)
    writer = FakeWriter(trace=CallTrace())
    data = {
        "id": "f_12",
        "tutorial_version": v1,
        "rating": 2,
        "user": "u_01",
        "category": "找不到按鈕",
        "comment": "第三步沒有指出按鈕在哪一頁與位置",
        "ts": "2026-08-02T09:00:00Z",
    }

    first = import_feedback(repo, writer, data, now=NOW)
    second = import_feedback(repo, writer, data, now=NOW)

    assert first.status == "saved"
    assert second.status == "duplicate"
    assert len(repo.list_feedback_of_version(v1)) == 1


def test_同一事件重送不新增_PROC_成功樣本(repo):
    proc = ProvenWorkflow(
        signature="abc1234567890def",
        domain="github.com",
        adapter_type="ticket",
        keys=["action", "issue", "repository", "sender"],
        steps=[],
        success_count=1,
        fail_count=0,
        status=ProcStatus.active,
        last_used="2026-09-12T00:00:00Z",
    )
    repo.put_proc(proc)

    # 重送同一事件時，ingress 判定為 duplicate，不會再呼叫 commit_success。
    seed_feature(repo)
    starter = FakeStarter()
    ticket = make_ticket()
    accept_ticket(repo, starter, ticket, delivery_id="d-1", now=NOW)
    accept_ticket(repo, starter, ticket, delivery_id="d-1", now=NOW)

    assert repo.get_proc("abc1234567890def").success_count == 1


def test_保存後啟動前失敗的事件重送時沿用未完成執行(repo, monkeypatch):
    seed_feature(repo)
    starter = FakeStarter()
    ticket = make_ticket()

    monkeypatch.setenv("TKB_FAULT", "start_execution")
    with pytest.raises(InjectedFault):
        accept_ticket(repo, starter, ticket, delivery_id="d-1", now=NOW)
    assert starter.calls == []
    assert repo.get_ticket("t_881") is not None

    monkeypatch.delenv("TKB_FAULT")
    retry = accept_ticket(repo, starter, ticket, delivery_id="d-1", now=NOW)
    assert retry.status in ("accepted", "duplicate")
    assert retry.execution_arn is not None
    assert len(starter.calls) == 1
    assert repo.get_ticket("t_881") is not None
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：`uv run pytest tests/integration/test_recovery.py -k "重送 and (既有 or 回饋 or PROC or 未完成)" -v`

預期：如果 Phase 10 的 `accept_ticket` 沒有先查操作紀錄，第一個測試會看到 `assert 'accepted' == 'duplicate'` 失敗，`starter.calls` 也會是 2。

- [ ] **步驟 3：寫最少的程式讓測試通過**

這個 Task 不新增產品程式碼。若測試沒過，代表 Phase 10 的 `accept_*` 需要補上去重流程。必要的順序是：

```python
# src/training_kb/ingress.py 的 accept_ticket 內（Phase 10 的既有邏輯，這裡列出必要條件）
    operation_id = operation_id_for("ticket", ticket.id)
    is_new = repo.begin_operation(
        operation_id,
        {"kind": "ticket", "object_id": ticket.id, "delivery_id": delivery_id,
         "status": "running"},
    )
    if not is_new:
        record = repo.load_operation(operation_id) or {}
        return AcceptResult(
            status="duplicate",
            object_id=ticket.id,
            execution_arn=record.get("execution_arn"),
            message="同一事件已處理過，回傳既有結果。",
            invalid_fields=[],
        )
    repo.put_ticket(ticket)
    maybe_fail("start_execution")          # Phase 24 切點
    arn = starter.start("ticket", execution_name(operation_id), {...})
    repo.update_operation(operation_id, {"execution_arn": arn, "status": "done"})
```

「保存後啟動前失敗」的重送之所以能繼續，是因為 `begin_operation` 已經寫過 `OPS#<id>`，第二次回傳 `False`，於是走 `load_operation` 這條路；記錄裡的 `status` 還是 `running`、`execution_arn` 是空的，所以要接續啟動：

```python
    if not is_new:
        record = repo.load_operation(operation_id) or {}
        if record.get("status") == "done":
            return AcceptResult(status="duplicate", object_id=ticket.id,
                                execution_arn=record.get("execution_arn"),
                                message="同一事件已處理過，回傳既有結果。", invalid_fields=[])
        # 沿用未完成執行：物件已保存，只補啟動流程（釐清 F09）
        arn = starter.start("ticket", execution_name(operation_id), {...})
        repo.update_operation(operation_id, {"execution_arn": arn, "status": "done"})
        return AcceptResult(status="accepted", object_id=ticket.id, execution_arn=arn,
                            message="沿用未完成的執行，已補啟動流程。", invalid_fields=[])
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：`uv run pytest tests/integration/test_recovery.py -v`

預期：PASS，21 個測試全綠。

- [ ] **步驟 5：commit**

```bash
git add tests/integration/test_recovery.py src/training_kb/ingress.py
git commit -m "test(recovery): 同事件重送只對應一次邏輯處理"
```

---

### Task 7：(d) 多篇同批發布其中一篇失敗，整批不切換

**目的**：驗證釐清 F49 與設計文件 §8.3 原話：「不能在逐篇 Map 中先發布 A，再因 B 失敗而聲稱整次沒有發布」。

**檔案**：
- 修改：`tests/integration/test_recovery.py`

**介面**：
- 消費：`training_kb.content.publish(repo, version_ids, renderer, *, now) -> PublishResult`
- 產出：無新程式碼

- [ ] **步驟 1：寫測試**

```python
# tests/integration/test_recovery.py（在檔尾附加）
# ---------------------------------------------------------------- Task 7：(d)


def make_two_pending_v2(repo, renderer):
    """A 與 B 各有一個完整但未發布的 v2，回傳 (a_v1, b_v1, a_v2, b_v2)。"""
    a_v1 = make_published_v1(repo, renderer, SLUG_A, "Prepare")
    b_v1 = make_published_v1(repo, renderer, SLUG_B, "Share Summary")
    a_plan = start_v2(repo, SLUG_A, "release:r_42:a", "release:r_42")
    create_version(repo, a_plan, make_content("a-v2", "Prepare"), now=NOW)
    b_plan = start_v2(repo, SLUG_B, "release:r_42:b", "release:r_42")
    create_version(repo, b_plan, make_content("b-v2", "Share Summary"), now=NOW)
    return a_v1, b_v1, a_plan.version_id, b_plan.version_id


def test_其中一篇產物不完整時整批都不切換(repo, renderer):
    a_v1, b_v1, a_v2, b_v2 = make_two_pending_v2(repo, renderer)
    # 讓 B 的 diff 消失，模擬「其中一篇沒有通過完整性驗證」
    repo.s3.delete_object(Bucket=BUCKET, Key=f"tutorials/{SLUG_B}/v2.diff")
    assert verify_version_complete(repo, b_v2) != []

    result = publish(repo, [a_v2, b_v2], renderer, now=NOW)

    assert result.failed == b_v2
    assert result.published == []
    assert repo.get_tutorial(SLUG_A).current_version == a_v1
    assert repo.get_tutorial(SLUG_B).current_version == b_v1
    assert repo.get_version(a_v2).published_at is None
    assert repo.object_exists(site_keys(SLUG_A, 2)["page"]) is False
    assert repo.object_exists(site_keys(SLUG_B, 2)["page"]) is False


def test_交易前注入失敗時整批都不切換(repo, renderer, monkeypatch):
    a_v1, b_v1, a_v2, b_v2 = make_two_pending_v2(repo, renderer)
    before = site_key_set(repo)

    monkeypatch.setenv("TKB_FAULT", "publish_before_transact")
    with pytest.raises(InjectedFault):
        publish(repo, [a_v2, b_v2], renderer, now=NOW)

    assert repo.get_tutorial(SLUG_A).current_version == a_v1
    assert repo.get_tutorial(SLUG_B).current_version == b_v1
    assert site_key_set(repo) == before


def test_版本_ID_不存在時整批都不切換(repo, renderer):
    a_v1, b_v1, a_v2, _ = make_two_pending_v2(repo, renderer)
    result = publish(repo, [a_v2, "share-summary@v9"], renderer, now=NOW)

    assert result.failed == "share-summary@v9"
    assert result.published == []
    assert repo.get_tutorial(SLUG_A).current_version == a_v1
    assert repo.get_tutorial(SLUG_B).current_version == b_v1


def test_兩篇都完整時才一起切換(repo, renderer):
    _, _, a_v2, b_v2 = make_two_pending_v2(repo, renderer)
    result = publish(repo, [a_v2, b_v2], renderer, now=NOW)

    assert result.failed is None
    assert sorted(result.published) == sorted([a_v2, b_v2])
    assert repo.get_tutorial(SLUG_A).current_version == a_v2
    assert repo.get_tutorial(SLUG_B).current_version == b_v2
    assert repo.object_exists(site_keys(SLUG_A, 2)["page"]) is True
    assert repo.object_exists(site_keys(SLUG_B, 2)["page"]) is True
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：`uv run pytest tests/integration/test_recovery.py -k "整批 or 一起切換" -v`

預期：如果 Phase 08 的 publish 是「逐篇提交」，第一個測試會看到 A 已經切換成 v2，`result.published` 不是空的。

- [ ] **步驟 3：寫最少的程式讓測試通過**

這個 Task 不新增產品程式碼。若測試沒過，代表 Phase 08 的 `_publish_new` 需要改成兩段式：**先把整批都驗證完，再一次送出交易**。

```python
# src/training_kb/content.py 的 _publish_new 內（Phase 08 的既有邏輯，這裡列出必要條件）
    # 第一段：全部驗證完成才繼續（釐清 F49、設計 §8.3）
    for version_id in version_ids:
        problems = verify_version_complete(repo, version_id)
        if problems:
            return PublishResult(published=[], failed=version_id)

    # 第二段：一次把整批的 published_at 與 current_version 放進同一個交易
    actions = []
    for version_id in version_ids:
        slug, _ = parse_version_id(version_id)
        version = repo.get_version(version_id)
        actions.append({...寫 VERSION.published_at...})
        actions.append({...寫 TUTORIAL.current_version，條件 current_version == version.supersedes...})
    maybe_fail("publish_before_transact")
    repo.transact_write(actions)

    # 第三段：交易成功後才寫公開頁
    for version_id in version_ids:
        slug, _ = parse_version_id(version_id)
        publish_to_site(repo, renderer, slug, version_id)
    return PublishResult(published=list(version_ids), failed=None)
```

注意 DynamoDB 交易一次最多 100 個動作。本案一批頂多幾篇教學，不會踩到上限；如果未來超過，必須先拆批並重新設計整批不切換的保證，不可以直接放寬。

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：`uv run pytest tests/integration/test_recovery.py -v`

預期：PASS，25 個測試全綠。

- [ ] **步驟 5：commit**

```bash
git add tests/integration/test_recovery.py src/training_kb/content.py
git commit -m "test(recovery): 多篇同批發布任一失敗整批不切換"
```

---

### Task 8：(e) 同篇的 Release 與 Feedback 依鎖與接受順序串行

**目的**：驗證釐清 F35「同篇變更依接受順序串行處理，每次讀取最新可用基底再產生下一版」，也就是不從舊基底分叉出第二條版本鏈。

**檔案**：
- 修改：`tests/integration/test_recovery.py`

**介面**：
- 消費：`training_kb.repository.Repository.acquire_lock(slug, owner, ttl_seconds, now) -> bool`、`release_lock(slug, owner)`、`training_kb.content.with_tutorial_lock(repo, slug, owner, now, fn) -> T`、`training_kb.errors.TransientError`
- 產出：無新程式碼

- [ ] **步驟 1：寫測試**

```python
# tests/integration/test_recovery.py（在檔尾附加）
# ---------------------------------------------------------------- Task 8：(e)

from training_kb.content import with_tutorial_lock
from training_kb.errors import TransientError


def test_同一篇同時只有一個持有者能拿到鎖(repo, renderer):
    make_published_v1(repo, renderer, SLUG_A)
    assert repo.acquire_lock(SLUG_A, "release:r_42", 60, NOW) is True
    assert repo.acquire_lock(SLUG_A, "review:demo:r1", 60, NOW) is False
    repo.release_lock(SLUG_A, "release:r_42")
    assert repo.acquire_lock(SLUG_A, "review:demo:r1", 60, NOW) is True


def test_拿不到鎖時丟可重試錯誤(repo, renderer):
    make_published_v1(repo, renderer, SLUG_A)
    repo.acquire_lock(SLUG_A, "release:r_42", 60, NOW)
    with pytest.raises(TransientError):
        with_tutorial_lock(repo, SLUG_A, "review:demo:r1", NOW, lambda: "不應該執行到")


def test_後到的改版從最新基底長下一版而不是分叉(repo, renderer):
    v1 = make_published_v1(repo, renderer, SLUG_A)

    # 先到的 Release 取鎖、建 v2、發布、放鎖
    def do_release():
        plan = start_v2(repo, SLUG_A, "release:r_42", "release:r_42")
        create_version(repo, plan, make_content("v2"), now=NOW)
        assert publish(repo, [plan.version_id], renderer, now=NOW).failed is None
        return plan.version_id

    v2 = with_tutorial_lock(repo, SLUG_A, "release:r_42", NOW, do_release)
    assert v2 == "prepare-meeting@v2"

    # 後到的 Feedback 這時才取得鎖，讀到的基底必須是 v2
    def do_review():
        plan = start_v2(repo, SLUG_A, "review:demo:r1", "feedback:8 則 找不到按鈕")
        assert plan.version_id == "prepare-meeting@v3"
        assert plan.supersedes == "prepare-meeting@v2"
        create_version(repo, plan, make_content("v3"), now=NOW)
        assert publish(repo, [plan.version_id], renderer, now=NOW).failed is None
        return plan.version_id

    v3 = with_tutorial_lock(repo, SLUG_A, "review:demo:r1", NOW, do_review)
    assert v3 == "prepare-meeting@v3"
    assert repo.get_version(v3).supersedes == v2
    assert repo.get_version(v2).supersedes == v1
    assert repo.get_tutorial(SLUG_A).current_version == v3


def test_先前版本沒完成時後來的改版不從舊基底分叉(repo, renderer, monkeypatch):
    """設計 §8.3：先前版本尚未完成時，後來的 Release／Feedback 不得同時從舊版寫出另一條版本鏈。"""
    v1 = make_published_v1(repo, renderer, SLUG_A)

    # Release 拿到鎖、建到一半就失敗，鎖還在它手上
    repo.acquire_lock(SLUG_A, "release:r_42", 300, NOW)
    plan = start_v2(repo, SLUG_A, "release:r_42", "release:r_42")
    monkeypatch.setenv("TKB_FAULT", "ddb_after_version")
    with pytest.raises(InjectedFault):
        create_version(repo, plan, make_content("v2"), now=NOW)
    monkeypatch.delenv("TKB_FAULT")

    # Feedback 這時要改版，會被鎖擋下來，不會另外長一條 v2
    with pytest.raises(TransientError):
        with_tutorial_lock(repo, SLUG_A, "review:demo:r1", NOW, lambda: None)
    assert repo.get_tutorial(SLUG_A).current_version == v1
    assert repo.get_version("prepare-meeting@v3") is None


def test_鎖過期後才換手(repo, renderer):
    from datetime import timedelta

    make_published_v1(repo, renderer, SLUG_A)
    assert repo.acquire_lock(SLUG_A, "release:r_42", 60, NOW) is True
    assert repo.acquire_lock(SLUG_A, "review:demo:r1", 60, NOW + timedelta(seconds=30)) is False
    assert repo.acquire_lock(SLUG_A, "review:demo:r1", 60, NOW + timedelta(seconds=61)) is True
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：`uv run pytest tests/integration/test_recovery.py -k "鎖 or 分叉 or 基底" -v`

預期：如果 Phase 03 的 `acquire_lock` 沒有做條件寫入或沒有處理 TTL，第一個或最後一個測試會失敗。

- [ ] **步驟 3：寫最少的程式讓測試通過**

這個 Task 不新增產品程式碼。若測試沒過，代表 Phase 03 的鎖需要修正。必要條件是「條件寫入 + TTL」：

```python
# src/training_kb/repository.py 的 acquire_lock 內（Phase 03 的既有邏輯，這裡列出必要條件）
    expires_at = to_iso(now + timedelta(seconds=ttl_seconds))
    try:
        self.table.put_item(
            Item={"PK": lock_pk(slug), "SK": META, "entity": "LOCK",
                  "owner": owner, "expires_at": expires_at},
            # 沒有人持有，或持有者已經過期，或就是自己 → 才寫得進去
            ConditionExpression="attribute_not_exists(PK) OR expires_at < :now OR #o = :owner",
            ExpressionAttributeNames={"#o": "owner"},
            ExpressionAttributeValues={":now": to_iso(now), ":owner": owner},
        )
        return True
    except self.table.meta.client.exceptions.ConditionalCheckFailedException:
        return False
```

`release_lock` 也要帶條件，只有持有者本人可以放鎖：

```python
    try:
        self.table.delete_item(
            Key={"PK": lock_pk(slug), "SK": META},
            ConditionExpression="#o = :owner",
            ExpressionAttributeNames={"#o": "owner"},
            ExpressionAttributeValues={":owner": owner},
        )
    except self.table.meta.client.exceptions.ConditionalCheckFailedException:
        return
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：`uv run pytest tests/integration/test_recovery.py -v`

預期：PASS，30 個測試全綠。

- [ ] **步驟 5：commit**

```bash
git add tests/integration/test_recovery.py src/training_kb/repository.py
git commit -m "test(recovery): 同篇改版依鎖與接受順序串行"
```

---

### Task 9：(f) `StartExecution` 同名已結束時的處理

**目的**：設計文件 §14.2 原話：「已結束的同名執行會回傳 `ExecutionAlreadyExists`，不能把此例外直接當成功，也不能改名就無條件重跑。需檢查原結果與操作紀錄。」這個 Task 把「怎麼檢查」寫成一個可測試的決策函式。

**檔案**：
- 修改：`src/training_kb/ingress.py`
- 測試：`tests/unit/test_existing_execution.py`

**介面**：
- 消費：`training_kb.repository.Repository.load_operation(operation_id) -> dict | None`
- 產出：
  - `training_kb.ingress.ExistingExecutionDecision`（dataclass：`action: Literal["reuse", "needs_review"]`、`execution_arn: str | None`、`message: str`）
  - `training_kb.ingress.decide_existing_execution(operation: dict | None) -> ExistingExecutionDecision`

**本計劃選擇（對應 O2）**：操作紀錄顯示 `status == "done"` 才可以沿用既有結果；其他情況一律回報「需要人工確認」，不自動改名重跑。這是保守做法，因為無法從 `ExecutionAlreadyExists` 這個例外本身判斷上一次到底做完了沒有。

- [ ] **步驟 1：寫測試**

```python
# tests/unit/test_existing_execution.py
from __future__ import annotations

from training_kb.ingress import decide_existing_execution


def test_操作紀錄完成時沿用既有結果():
    decision = decide_existing_execution(
        {
            "status": "done",
            "execution_arn": "arn:aws:states:us-west-2:1:execution:p:e1",
            "object_id": "t_881",
        }
    )
    assert decision.action == "reuse"
    assert decision.execution_arn == "arn:aws:states:us-west-2:1:execution:p:e1"
    assert "既有結果" in decision.message


def test_操作紀錄還在進行時需要人工確認():
    decision = decide_existing_execution(
        {"status": "running", "execution_arn": "arn:aws:states:us-west-2:1:execution:p:e1"}
    )
    assert decision.action == "needs_review"
    assert decision.execution_arn == "arn:aws:states:us-west-2:1:execution:p:e1"
    assert "人工確認" in decision.message


def test_沒有操作紀錄時需要人工確認而且不可當成成功():
    decision = decide_existing_execution(None)
    assert decision.action == "needs_review"
    assert decision.execution_arn is None
    assert "不可當成成功" in decision.message


def test_操作紀錄沒有_status_欄位時視為未完成():
    decision = decide_existing_execution({"object_id": "t_881"})
    assert decision.action == "needs_review"


def test_標成失敗的操作紀錄也需要人工確認():
    decision = decide_existing_execution({"status": "failed", "execution_arn": "arn:x"})
    assert decision.action == "needs_review"


def test_決策結果不會自己換名字重跑():
    decision = decide_existing_execution({"status": "running"})
    assert "改名" not in decision.message
    assert decision.action in ("reuse", "needs_review")
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：`uv run pytest tests/unit/test_existing_execution.py -v`

預期：FAIL，`ImportError: cannot import name 'decide_existing_execution' from 'training_kb.ingress'`。

- [ ] **步驟 3：寫最少的程式讓測試通過**

在 `src/training_kb/ingress.py` 檔尾新增：

```python
# src/training_kb/ingress.py（新增）


@dataclass(frozen=True)
class ExistingExecutionDecision:
    """遇到 ExecutionAlreadyExists 時該怎麼辦。

    設計文件 §14.2：不能把這個例外直接當成功，也不能改名就無條件重跑。
    本計劃選擇（對應 O2）：只有操作紀錄明確標成 done 才沿用既有結果。
    """

    action: Literal["reuse", "needs_review"]
    execution_arn: str | None
    message: str


def decide_existing_execution(operation: dict | None) -> ExistingExecutionDecision:
    """依操作紀錄決定要沿用既有結果，還是交給人工確認。"""
    if operation is None:
        return ExistingExecutionDecision(
            action="needs_review",
            execution_arn=None,
            message="同名執行已存在，但找不到對應的操作紀錄；不可當成成功。",
        )
    arn = operation.get("execution_arn")
    if operation.get("status") == "done":
        return ExistingExecutionDecision(
            action="reuse",
            execution_arn=arn,
            message="同一事件已處理完成，回傳既有結果。",
        )
    return ExistingExecutionDecision(
        action="needs_review",
        execution_arn=arn,
        message="同名執行已結束但操作紀錄未完成，需要人工確認後再重送。",
    )
```

如果檔首還沒有這些匯入，一併補上：

```python
from dataclasses import dataclass
from typing import Literal
```

**整合點**：Phase 14 的 `StepFunctionsStarter.start()` 在攔到 `ExecutionAlreadyExists` 時，要照下面這樣處理，而不是直接回傳成功：

```python
# src/training_kb/handlers/pipeline_task.py 或 Phase 14 的 starter 實作
    try:
        response = self.client.start_execution(
            stateMachineArn=arn, name=execution_name, input=json.dumps(input)
        )
        return response["executionArn"]
    except self.client.exceptions.ExecutionAlreadyExists:
        existing_arn = self._find_execution_arn(execution_name)
        described = self.client.describe_execution(executionArn=existing_arn)
        if described["status"] == "RUNNING":
            # 同名且仍在執行：直接沿用（設計 §14.2 的冪等行為）
            return existing_arn
        decision = decide_existing_execution(self.repo.load_operation(operation_id))
        if decision.action == "reuse":
            return decision.execution_arn or existing_arn
        raise PermanentError(decision.message)
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：`uv run pytest tests/unit/test_existing_execution.py -v`

預期：PASS，6 個測試全綠。

- [ ] **步驟 5：commit**

```bash
git add src/training_kb/ingress.py tests/unit/test_existing_execution.py
git commit -m "feat(ingress): 同名執行已結束時依操作紀錄判斷"
```

---

### Task 10：(g) `infra/scripts/check_asl.py` 檢查 Retry 與 Catch

**目的**：用腳本檢查三份 ASL 檔的每個 Task 都有 Retry 與 Catch，而且 Catch 導向 `PipelineFailed`。這對應 `執行教學流程.feature` 的 Rule 6 與 Rule 7。

**檔案**：
- 新增：`infra/scripts/check_asl.py`
- 測試：`tests/unit/test_check_asl.py`

**介面**：
- 消費：無（純 JSON 檢查）
- 產出：
  - `infra.scripts.check_asl.FAIL_STATE = "PipelineFailed"`
  - `infra.scripts.check_asl.iter_task_states(states: dict, prefix: str = "") -> Iterator[tuple[str, dict]]`
  - `infra.scripts.check_asl.check_asl_document(doc: dict, *, fail_state: str = FAIL_STATE) -> list[str]`
  - `infra.scripts.check_asl.main(argv: list[str] | None = None) -> int`

- [ ] **步驟 1：寫測試**

```python
# tests/unit/test_check_asl.py
from __future__ import annotations

import json

from infra.scripts.check_asl import check_asl_document, iter_task_states, main

GOOD_TASK = {
    "Type": "Task",
    "Resource": "arn:aws:lambda:us-west-2:1:function:training-kb-pipeline-task",
    "Retry": [
        {
            "ErrorEquals": ["TransientError"],
            "IntervalSeconds": 1,
            "MaxAttempts": 2,
            "BackoffRate": 2,
        }
    ],
    "Catch": [{"ErrorEquals": ["States.ALL"], "Next": "PipelineFailed"}],
    "End": True,
}


def good_doc() -> dict:
    return {
        "StartAt": "Embed",
        "States": {
            "Embed": json.loads(json.dumps(GOOD_TASK)),
            "PipelineFailed": {"Type": "Fail", "Error": "PipelineFailed"},
        },
    }


def test_合格的文件沒有問題():
    assert check_asl_document(good_doc()) == []


def test_缺少_Retry_會被抓到():
    doc = good_doc()
    del doc["States"]["Embed"]["Retry"]
    problems = check_asl_document(doc)
    assert any("Embed" in p and "Retry" in p for p in problems)


def test_Retry_沒有涵蓋_TransientError_會被抓到():
    doc = good_doc()
    doc["States"]["Embed"]["Retry"][0]["ErrorEquals"] = ["States.Timeout"]
    problems = check_asl_document(doc)
    assert any("TransientError" in p for p in problems)


def test_缺少_Catch_會被抓到():
    doc = good_doc()
    del doc["States"]["Embed"]["Catch"]
    problems = check_asl_document(doc)
    assert any("Embed" in p and "Catch" in p for p in problems)


def test_Catch_沒有導向_PipelineFailed_會被抓到():
    doc = good_doc()
    doc["States"]["Embed"]["Catch"][0]["Next"] = "SomewhereElse"
    problems = check_asl_document(doc)
    assert any("PipelineFailed" in p for p in problems)


def test_Catch_沒有涵蓋_States_ALL_會被抓到():
    doc = good_doc()
    doc["States"]["Embed"]["Catch"][0]["ErrorEquals"] = ["TransientError"]
    problems = check_asl_document(doc)
    assert any("States.ALL" in p for p in problems)


def test_沒有失敗終點會被抓到():
    doc = good_doc()
    del doc["States"]["PipelineFailed"]
    problems = check_asl_document(doc)
    assert any("缺少失敗終點" in p for p in problems)


def test_失敗終點型別不是_Fail_會被抓到():
    doc = good_doc()
    doc["States"]["PipelineFailed"] = {"Type": "Pass"}
    problems = check_asl_document(doc)
    assert any("不是 Fail" in p for p in problems)


def test_Map_內的_Task_也要檢查():
    doc = good_doc()
    inner = json.loads(json.dumps(GOOD_TASK))
    del inner["Catch"]
    doc["States"]["PublishEach"] = {
        "Type": "Map",
        "ItemProcessor": {"StartAt": "PublishOne", "States": {"PublishOne": inner}},
        "Next": "PipelineFailed",
    }
    problems = check_asl_document(doc)
    assert any("PublishEach.PublishOne" in p for p in problems)


def test_Parallel_分支內的_Task_也要檢查():
    doc = good_doc()
    inner = json.loads(json.dumps(GOOD_TASK))
    del inner["Retry"]
    doc["States"]["Both"] = {
        "Type": "Parallel",
        "Branches": [{"StartAt": "One", "States": {"One": inner}}],
        "Next": "PipelineFailed",
    }
    problems = check_asl_document(doc)
    assert any("Both[0].One" in p for p in problems)


def test_沒有_States_區塊時直接回報():
    assert check_asl_document({}) == ["ASL 沒有 States 區塊"]


def test_只列出_Task_型別的節點():
    doc = good_doc()
    doc["States"]["Decide"] = {"Type": "Choice", "Choices": [], "Default": "PipelineFailed"}
    names = [name for name, _ in iter_task_states(doc["States"])]
    assert names == ["Embed"]


def test_main_對合格檔案回傳零(tmp_path, capsys):
    path = tmp_path / "good.asl.json"
    path.write_text(json.dumps(good_doc()), encoding="utf-8")
    assert main([str(path)]) == 0
    assert "通過" in capsys.readouterr().out


def test_main_對不合格檔案回傳一(tmp_path, capsys):
    doc = good_doc()
    del doc["States"]["Embed"]["Retry"]
    path = tmp_path / "bad.asl.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    assert main([str(path)]) == 1
    assert "Retry" in capsys.readouterr().out
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：`uv run pytest tests/unit/test_check_asl.py -v`

預期：FAIL，`ModuleNotFoundError: No module named 'infra'`。先建立兩個空的 `__init__.py`：

```bash
touch infra/__init__.py infra/scripts/__init__.py
```

再跑一次，會變成 `ModuleNotFoundError: No module named 'infra.scripts.check_asl'`。

- [ ] **步驟 3：寫最少的程式讓測試通過**

```python
# infra/scripts/check_asl.py
"""檢查 ASL 檔的每個 Task 都有 Retry 與 Catch，且 Catch 導向 PipelineFailed。

對應 docs/spec/features/執行教學流程.feature 的 Rule 6 與 Rule 7，
以及設計文件 §14.2。

用法：
    uv run python -m infra.scripts.check_asl infra/asl/*.asl.json
    uv run python -m infra.scripts.check_asl          # 不給參數就掃 infra/asl/
"""

from __future__ import annotations

import json
import sys
from collections.abc import Iterator
from pathlib import Path

FAIL_STATE = "PipelineFailed"
RETRY_ERROR = "TransientError"
CATCH_ERROR = "States.ALL"
DEFAULT_DIR = Path("infra/asl")


def iter_task_states(states: dict, prefix: str = "") -> Iterator[tuple[str, dict]]:
    """列出所有 Type 是 Task 的節點，包含 Map 與 Parallel 內部的。"""
    for name in sorted(states):
        state = states[name]
        if not isinstance(state, dict):
            continue
        full = f"{prefix}{name}"
        kind = state.get("Type")
        if kind == "Task":
            yield full, state
        elif kind == "Map":
            inner = state.get("ItemProcessor") or state.get("Iterator") or {}
            yield from iter_task_states(inner.get("States", {}), prefix=f"{full}.")
        elif kind == "Parallel":
            for index, branch in enumerate(state.get("Branches", [])):
                yield from iter_task_states(
                    branch.get("States", {}), prefix=f"{full}[{index}]."
                )


def check_asl_document(doc: dict, *, fail_state: str = FAIL_STATE) -> list[str]:
    """回傳問題清單；空清單代表通過。"""
    states = doc.get("States")
    if not isinstance(states, dict) or not states:
        return ["ASL 沒有 States 區塊"]

    problems: list[str] = []
    if fail_state not in states:
        problems.append(f"缺少失敗終點 {fail_state}")
    elif states[fail_state].get("Type") != "Fail":
        problems.append(f"{fail_state} 的 Type 不是 Fail")

    for name, state in iter_task_states(states):
        retry = state.get("Retry")
        if not isinstance(retry, list) or not retry:
            problems.append(f"Task {name} 沒有 Retry")
        else:
            covered = {
                error for entry in retry for error in entry.get("ErrorEquals", [])
            }
            if RETRY_ERROR not in covered:
                problems.append(f"Task {name} 的 Retry 沒有涵蓋 {RETRY_ERROR}")

        catch = state.get("Catch")
        if not isinstance(catch, list) or not catch:
            problems.append(f"Task {name} 沒有 Catch")
        else:
            covered = {
                error for entry in catch for error in entry.get("ErrorEquals", [])
            }
            if CATCH_ERROR not in covered:
                problems.append(f"Task {name} 的 Catch 沒有涵蓋 {CATCH_ERROR}")
            targets = {entry.get("Next") for entry in catch}
            if fail_state not in targets:
                problems.append(f"Task {name} 的 Catch 沒有導向 {fail_state}")
    return problems


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    paths = [Path(a) for a in args] or sorted(DEFAULT_DIR.glob("*.asl.json"))
    if not paths:
        print(f"找不到任何 ASL 檔（預設目錄：{DEFAULT_DIR}）")
        return 1

    failed = False
    for path in paths:
        doc = json.loads(path.read_text(encoding="utf-8"))
        problems = check_asl_document(doc)
        if problems:
            failed = True
            print(f"[不通過] {path}")
            for problem in problems:
                print(f"  - {problem}")
        else:
            print(f"[通過] {path}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：`uv run pytest tests/unit/test_check_asl.py -v`

預期：PASS，14 個測試全綠。接著對真正的 ASL 檔跑一次：

```bash
uv run python -m infra.scripts.check_asl
```

預期輸出三行 `[通過] infra/asl/xxx.asl.json`。如果看到 `[不通過]`，回頭補 Phase 14／16／18 的 ASL 設定，不要改這個腳本的門檻。

- [ ] **步驟 5：commit**

```bash
git add infra/__init__.py infra/scripts/__init__.py infra/scripts/check_asl.py tests/unit/test_check_asl.py
git commit -m "feat(infra): 檢查 ASL 每個 Task 的 Retry 與 Catch"
```

---

### Task 11：(h) 真實 AWS 的驗收與可追溯紀錄

**目的**：在已部署的環境走一次 `TKB_FAULT`，把 execution ARN 與前後狀態寫成報告，讓別人可以回頭查證。

**檔案**：
- 修改：`tests/integration/test_recovery.py`
- 產出檔案：`docs/plan/report/recovery-<YYYYMMDD-HHMM>.md`

**介面**：
- 消費：
  - `boto3` 的 `lambda.update_function_configuration(FunctionName, Environment={"Variables": {...}})`
  - `boto3` 的 `lambda.get_function_configuration(FunctionName)`
  - `boto3` 的 `stepfunctions.start_execution(stateMachineArn, name, input)`
  - `boto3` 的 `stepfunctions.describe_execution(executionArn)` → `status` 為 `RUNNING`／`SUCCEEDED`／`FAILED`／`TIMED_OUT`／`ABORTED`／`PENDING_REDRIVE`
  - `demo.cli.load_targets()`（Phase 23）
- 產出：
  - `tests/integration/test_recovery.py::RecoveryEntry`（dataclass：`fault_point`、`operation_id`、`execution_arn`、`status`、`error`、`current_version_before`、`current_version_after`、`site_keys_added`、`screenshot`）
  - `tests/integration/test_recovery.py::render_recovery_report(entries, *, run_at, region, account) -> str`
  - `tests/integration/test_recovery.py::wait_for_execution(client, execution_arn, *, timeout_s=300, interval_s=5) -> dict`

**報告格式**（`docs/plan/report/recovery-<YYYYMMDD-HHMM>.md`）：

```markdown
# 失敗復原驗收紀錄

- 執行時間（UTC）：2026-09-13T11:20:00Z
- Region：us-west-2
- 帳號：123456789012
- 驗收依據：設計文件 §8.3（O3）、§14（O2）、§15「版本與發布」「接入去重」「呼叫與失敗」三列

| 切點 | operation_id | execution ARN | 結束狀態 | 錯誤 | current_version（前） | current_version（後） | site/ 新增 | 截圖 |
|---|---|---|---|---|---|---|---|---|
| publish_before_transact | release:r_42 | arn:...:execution:training-kb-release-update:x1 | FAILED | InjectedFault | prepare-meeting@v2 | prepare-meeting@v2 | （無） | assets/x1.png |
| （重送）publish_before_transact | release:r_42 | arn:...:execution:training-kb-release-update:x2 | SUCCEEDED | - | prepare-meeting@v2 | prepare-meeting@v3 | site/prepare-meeting/v3.html | assets/x2.png |
```

- [ ] **步驟 1：寫測試**

```python
# tests/integration/test_recovery.py（在檔尾附加）
# ---------------------------------------------------------------- Task 11：(h)

def test_報告每個切點都有一列而且欄位齊全():
    entries = [
        RecoveryEntry(
            fault_point="publish_before_transact",
            operation_id="release:r_42",
            execution_arn="arn:x1",
            status="FAILED",
            error="InjectedFault",
            current_version_before="prepare-meeting@v2",
            current_version_after="prepare-meeting@v2",
            screenshot="assets/x1.png",
        ),
        RecoveryEntry(
            fault_point="（重送）publish_before_transact",
            operation_id="release:r_42",
            execution_arn="arn:x2",
            status="SUCCEEDED",
            error="",
            current_version_before="prepare-meeting@v2",
            current_version_after="prepare-meeting@v3",
            site_keys_added=["site/prepare-meeting/v3.html"],
            screenshot="assets/x2.png",
        ),
    ]
    text = render_recovery_report(
        entries, run_at="2026-09-13T11:20:00Z", region="us-west-2", account="123456789012"
    )
    assert "# 失敗復原驗收紀錄" in text
    assert "2026-09-13T11:20:00Z" in text
    assert "us-west-2" in text
    assert "123456789012" in text
    assert "arn:x1" in text and "arn:x2" in text
    assert "site/prepare-meeting/v3.html" in text
    assert text.count("\n|") >= 4  # 表頭、分隔列與兩筆資料
    assert "（無）" in text


def test_沒有錯誤時錯誤欄顯示破折號():
    text = render_recovery_report(
        [
            RecoveryEntry(
                fault_point="p",
                operation_id="o",
                execution_arn="a",
                status="SUCCEEDED",
                error="",
                current_version_before="v1",
                current_version_after="v2",
            )
        ],
        run_at="t",
        region="r",
        account="a",
    )
    assert "| - |" in text


@pytest.mark.aws
@pytest.mark.skipif(
    os.environ.get("TKB_RUN_AWS_TESTS") != "1",
    reason="需要真實 AWS；設定 TKB_RUN_AWS_TESTS=1 才執行",
)
def test_真實環境注入一次失敗再重送成功():
    """對已部署環境走一次切點，並把結果寫成可追溯的報告。

    步驟：
      1. 記下目前的 current_version 與 site/ key 清單。
      2. 把 TKB_FAULT 設進 pipeline-task Lambda 的環境變數。
      3. 啟動 release-update，等它結束，預期 FAILED。
      4. 檢查 current_version 沒變、site/ 沒有新檔。
      5. 移除 TKB_FAULT，用同一個 operation_id 再啟動一次，預期 SUCCEEDED。
      6. 檢查 current_version 已切換、site/ 有新檔。
      7. 寫報告到 docs/plan/report/。
    """
    from datetime import datetime as _dt

    from demo.cli import load_targets
    from training_kb.config import load_settings
    from training_kb.ingress import execution_name
    from training_kb.repository import build_repository

    fault_point = "publish_before_transact"
    settings = load_settings()
    targets = load_targets()
    live_repo = build_repository(settings)
    lam = boto3.client("lambda", region_name=targets.region)
    sfn = boto3.client("stepfunctions", region_name=targets.region)
    sts = boto3.client("sts", region_name=targets.region)
    account = sts.get_caller_identity()["Account"]

    slug = os.environ.get("TKB_AWS_TEST_SLUG", SLUG_A)
    state_machine_arn = os.environ["TKB_RELEASE_UPDATE_ARN"]
    task_function = os.environ.get("TKB_PIPELINE_TASK_FUNCTION", "training-kb-pipeline-task")
    operation_id = f"release:aws-recovery-{_dt.utcnow():%Y%m%d%H%M%S}"

    def current_version() -> str:
        tutorial = live_repo.get_tutorial(slug)
        return "" if tutorial is None else (tutorial.current_version or "")

    def site_keys_now() -> set[str]:
        paginator = live_repo.s3.get_paginator("list_objects_v2")
        keys: set[str] = set()
        for page in paginator.paginate(Bucket=settings.bucket_name, Prefix=f"site/{slug}/"):
            keys.update(obj["Key"] for obj in page.get("Contents", []))
        return keys

    def set_fault(value: str | None) -> None:
        config = lam.get_function_configuration(FunctionName=task_function)
        variables = dict(config.get("Environment", {}).get("Variables", {}))
        if value is None:
            variables.pop("TKB_FAULT", None)
        else:
            variables["TKB_FAULT"] = value
        lam.update_function_configuration(
            FunctionName=task_function, Environment={"Variables": variables}
        )
        time.sleep(10)  # 等設定生效

    entries: list[RecoveryEntry] = []
    before_version = current_version()
    before_keys = site_keys_now()

    set_fault(fault_point)
    try:
        failed_arn = sfn.start_execution(
            stateMachineArn=state_machine_arn,
            name=execution_name(operation_id),
            input=json.dumps(
                {"release_id": os.environ["TKB_AWS_TEST_RELEASE_ID"],
                 "operation_id": operation_id},
                ensure_ascii=False,
            ),
        )["executionArn"]
        failed = wait_for_execution(sfn, failed_arn)
        assert failed["status"] == "FAILED", failed
        assert current_version() == before_version
        assert site_keys_now() == before_keys
        entries.append(
            RecoveryEntry(
                fault_point=fault_point,
                operation_id=operation_id,
                execution_arn=failed_arn,
                status=failed["status"],
                error=failed.get("error", ""),
                current_version_before=before_version,
                current_version_after=current_version(),
                screenshot=f"assets/{failed_arn.rsplit(':', 1)[-1]}.png",
            )
        )
    finally:
        set_fault(None)

    retry_arn = sfn.start_execution(
        stateMachineArn=state_machine_arn,
        name=execution_name(operation_id + ":retry"),
        input=json.dumps(
            {"release_id": os.environ["TKB_AWS_TEST_RELEASE_ID"],
             "operation_id": operation_id},
            ensure_ascii=False,
        ),
    )["executionArn"]
    succeeded = wait_for_execution(sfn, retry_arn)
    assert succeeded["status"] == "SUCCEEDED", succeeded
    after_version = current_version()
    after_keys = site_keys_now()
    assert after_version != before_version
    assert after_keys - before_keys
    entries.append(
        RecoveryEntry(
            fault_point=f"（重送）{fault_point}",
            operation_id=operation_id,
            execution_arn=retry_arn,
            status=succeeded["status"],
            error="",
            current_version_before=before_version,
            current_version_after=after_version,
            site_keys_added=sorted(after_keys - before_keys),
            screenshot=f"assets/{retry_arn.rsplit(':', 1)[-1]}.png",
        )
    )

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    run_at = f"{_dt.utcnow():%Y-%m-%dT%H:%M:%SZ}"
    path = REPORT_DIR / f"recovery-{_dt.utcnow():%Y%m%d-%H%M}.md"
    path.write_text(
        render_recovery_report(
            entries, run_at=run_at, region=targets.region, account=account
        ),
        encoding="utf-8",
    )
    assert path.exists()
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：`uv run pytest tests/integration/test_recovery.py -k 報告 -v`

預期：FAIL，`NameError: name 'RecoveryEntry' is not defined`（前兩個純函式測試）。標記 `aws` 的那一個會顯示 `SKIPPED`，因為沒有設 `TKB_RUN_AWS_TESTS=1`。

- [ ] **步驟 3：寫最少的程式讓測試通過**

把下面這一整段插進 `tests/integration/test_recovery.py`，放在 `# ---- Task 11：(h)` 註解的下一行、測試函式的前面。報告的產生器與輪詢工具都放在測試檔裡，因為只有驗收流程會用到它們。

```python
# tests/integration/test_recovery.py（插在 Task 11 的測試函式前面）
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

REPORT_DIR = Path("docs/plan/report")


@dataclass
class RecoveryEntry:
    fault_point: str
    operation_id: str
    execution_arn: str
    status: str
    error: str
    current_version_before: str
    current_version_after: str
    site_keys_added: list[str] = field(default_factory=list)
    screenshot: str = ""


def render_recovery_report(
    entries: list[RecoveryEntry], *, run_at: str, region: str, account: str
) -> str:
    header = [
        "# 失敗復原驗收紀錄",
        "",
        f"- 執行時間（UTC）：{run_at}",
        f"- Region：{region}",
        f"- 帳號：{account}",
        "- 驗收依據：設計文件 §8.3（O3）、§14（O2）、"
        "§15「版本與發布」「接入去重」「呼叫與失敗」三列",
        "",
        "| 切點 | operation_id | execution ARN | 結束狀態 | 錯誤 | "
        "current_version（前） | current_version（後） | site/ 新增 | 截圖 |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    rows = [
        "| {p} | {o} | {a} | {s} | {e} | {b} | {f} | {k} | {c} |".format(
            p=entry.fault_point,
            o=entry.operation_id,
            a=entry.execution_arn,
            s=entry.status,
            e=entry.error or "-",
            b=entry.current_version_before,
            f=entry.current_version_after,
            k="、".join(entry.site_keys_added) or "（無）",
            c=entry.screenshot or "-",
        )
        for entry in entries
    ]
    return "\n".join(header + rows) + "\n"


def wait_for_execution(client, execution_arn: str, *, timeout_s: int = 300,
                       interval_s: int = 5) -> dict:
    """輪詢 describe_execution 直到不是 RUNNING 為止。"""
    deadline = time.monotonic() + timeout_s
    described = client.describe_execution(executionArn=execution_arn)
    while described["status"] == "RUNNING" and time.monotonic() < deadline:
        time.sleep(interval_s)
        described = client.describe_execution(executionArn=execution_arn)
    return described
```

如果 `json` 還沒在這個檔案匯入，在檔首補上：

```python
import json
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：`uv run pytest tests/integration/test_recovery.py -v`

預期：PASS 32 個，SKIPPED 1 個（標記 `aws` 的那個）。

有真實環境時，先把這幾個環境變數填好再跑：

```bash
export TKB_RUN_AWS_TESTS=1
export TKB_RELEASE_UPDATE_ARN="arn:aws:states:us-west-2:<帳號>:stateMachine:training-kb-release-update"
export TKB_AWS_TEST_RELEASE_ID="r_42"
export TKB_PIPELINE_TASK_FUNCTION="training-kb-pipeline-task"
uv run pytest tests/integration/test_recovery.py -m aws -v
```

預期：PASS，而且 `docs/plan/report/` 底下多出一個 `recovery-<日期>-<時間>.md`。用 `cat` 打開它，應該看到兩列：第一列 `FAILED` 且 `current_version` 前後相同，第二列 `SUCCEEDED` 且 `site/` 新增了一個 key。

截圖要自己補：在 Step Functions 主控台打開這兩個 execution，各截一張圖，存成報告表格裡寫的 `docs/plan/report/assets/<execution 名稱>.png`。

- [ ] **步驟 5：commit**

```bash
git add tests/integration/test_recovery.py
git commit -m "test(recovery): 真實環境注入失敗與重送的可追溯紀錄"
```

---

## 7. 完成檢查清單

這一階段對應設計文件第 16 節的 S0（「O2／O3 的最小整合驗證有可追溯結果」）與 S8（「一次儲存失敗復原」）。逐條確認：

- [ ] `uv run pytest tests/unit/test_faults.py tests/unit/test_fault_points_wired.py tests/unit/test_existing_execution.py tests/unit/test_check_asl.py -v` 全部 PASS。
- [ ] `uv run pytest tests/integration/test_recovery.py -v` 全部 PASS（標記 `aws` 的那一個可以 SKIPPED）。
- [ ] `uv run pytest tests/ -q` 全部 PASS，沒有弄壞前面階段的測試。
- [ ] `uv run ruff check .` 與 `uv run ruff format --check .` 沒有錯誤。
- [ ] `uv run python -m infra.scripts.check_asl` 三份 ASL 都是 `[通過]`。
- [ ] 對照第 5.3 節那張表，五個切點失敗後的狀態逐格核對過。
- [ ] `publish_after_transact_before_site` 失敗後重送一次，公開頁補齊（O3 的補償路徑可用）。
- [ ] 同一個 `operation_id` 重送三次，版號一直是 `prepare-meeting@v2`，沒有跳號。
- [ ] 同一個事件重送，`starter.calls` 長度是 1；同一筆回饋重送，`list_feedback_of_version` 長度是 1；同一個簽名的 PROC `success_count` 沒有增加。
- [ ] 多篇同批發布其中一篇不完整時，`published` 是空清單，兩篇的 `current_version` 都沒變，`site/` 兩篇都沒有新檔。
- [ ] 先到的操作持有鎖時，後到的操作拿不到鎖並得到 `TransientError`；先到的完成後，後到的讀到的基底是最新版本。
- [ ] `decide_existing_execution` 只有在 `status == "done"` 時回傳 `reuse`。
- [ ] 真實環境跑過一次，`docs/plan/report/recovery-<日期>.md` 存在，裡面有兩個 execution ARN、前後 `current_version` 與 `site/` 新增的 key。
- [ ] 報告表格裡的截圖檔案真的存在於 `docs/plan/report/assets/`。
- [ ] **確認上面全部打勾之後，才可以說「publish 的故障驗收已通過」**（設計文件 §8.3 的原話限制）。

---

## 8. 常見錯誤與排除

**症狀 1：設了 `TKB_FAULT` 但什麼事都沒發生**
原因有三個可能：切點名稱打錯（會拋 `ValueError`，去看 traceback）、`TKB_ENV` 被設成 `prod`（這時一律不注入）、或者 `maybe_fail` 插在錯的位置（被跳過了）。
解法：先跑 `uv run python -c "from training_kb.faults import active_fault; print(active_fault())"` 確認開關本身有讀到。再跑 `uv run pytest tests/unit/test_fault_points_wired.py -v` 確認插入位置。

**症狀 2：`test_交易後寫站台前失敗...` 測試裡，`current_version` 竟然還是 v1**
原因：`publish_after_transact_before_site` 這個切點被插在交易**之前**了。
解法：把它移到 `publish_to_site()` 函式本體的第一行。這個切點的定義就是「交易已經提交」，插錯位置會讓整個 O3 的驗收失去意義。

**症狀 3：`ConditionalCheckFailedException` 在重送時冒出來**
原因：`publish` 的交易條件是 `tutorial.current_version == supersedes`。交易已經提交過之後再跑一次，條件當然不成立。
解法：這正是 Task 3 的重入補償要解決的問題。確認 `publish` 的第一行有呼叫 `split_publish_targets`，而且原本的實作已經改名成 `_publish_new`。

**症狀 4：moto 的 `create_bucket` 報 `IllegalLocationConstraintException`**
原因：`us-east-1` 不可以帶 `CreateBucketConfiguration`，其他 Region 則必須帶。
解法：測試固定用 `us-west-2` 並保留 `CreateBucketConfiguration={"LocationConstraint": "us-west-2"}`。要換 Region 時，`REGION` 常數與 `create_bucket` 兩處一起改。

**症狀 5：真實 AWS 測試裡，設了 `TKB_FAULT` 卻還是成功了**
原因：`update_function_configuration` 是非同步生效的。設定送出後，Lambda 要一小段時間才會用新的環境變數建立新的執行環境。
解法：測試裡的 `set_fault()` 已經有 `time.sleep(10)`。如果還是不夠，用 `lam.get_function_configuration(FunctionName=...)` 輪詢到 `LastUpdateStatus` 變成 `Successful` 再繼續。

**症狀 6：真實 AWS 測試跑完，`TKB_FAULT` 留在 Lambda 上沒清掉**
原因：測試中途失敗，`finally` 沒有執行到（例如整個 process 被中斷）。
解法：手動清掉：

```bash
aws lambda get-function-configuration --function-name training-kb-pipeline-task \
  --query 'Environment.Variables' --output json
```

看到 `TKB_FAULT` 就用 `aws lambda update-function-configuration` 把它拿掉。**Demo 當天開始前一定要再檢查一次這個**，Phase 25 的當日 runbook 也會列。

**症狀 7：`describe_execution` 一直回傳 `RUNNING`，測試卡住**
原因：流程真的還在跑，或者 `wait_for_execution` 的 `timeout_s` 太短。
解法：先在 Step Functions 主控台看執行圖。如果卡在某個 Task，看那個 Task 的 CloudWatch 日誌。Standard 流程沒有全域逾時，所以 ASL 每個 Task 都應該設 `TimeoutSeconds`（設計 §14.3 建議 Task 最多 120 秒）。

**症狀 8：`ModuleNotFoundError: No module named 'infra'`**
原因：`infra/` 底下沒有 `__init__.py`，或 repo 根目錄不在 Python 搜尋路徑上。
解法：`touch infra/__init__.py infra/scripts/__init__.py`，並確認 `pyproject.toml` 有 `[tool.pytest.ini_options]` 底下的 `pythonpath = ["."]`。

---

## 9. 這階段不做的事

| 項目 | 留給哪裡 |
|---|---|
| Snyk 掃描、IAM 最小權限核對、`.env` 忽略確認 | Phase 25（`25-Phase25-安全檢查與Demo當日準備.md`） |
| Demo 當日 runbook、備援切換流程、結束後停用清單 | Phase 25 |
| 觸發流程的控制台、Dashboard 畫面 | Phase 23（`23-Phase23-Demo控制台與Dashboard.md`） |
| ASL 檔本身的內容（有哪些 state、怎麼分支） | Phase 14（ticket-analysis）、Phase 16（release-update）、Phase 18（feedback-review）；本階段只檢查 Retry／Catch |
| 自動修復（偵測到未完成版本就自動補完） | 不做。設計文件 §14.1 原話：「不新增待審狀態或另一個待處理入口」。補齊只在重送同一個 `operation_id` 時發生 |
| PROC 退役後的重置 | 設計文件 §7.2 與釐清 F53：退役簽名保持停用，由人工核定新序列後才明確重置。本階段不做自動重置 |
| 多租戶、跨專案的併發協調 | 不在 MVP 範圍。設計文件 §8.3：黑客松先採單一專案的序列化寫入 |
| 壓力測試、併發量測 | 不做。本階段只驗證正確性，不驗證吞吐量 |
| 把 `TKB_FAULT` 做成 API 或主控台按鈕 | 不做。它只是環境變數，正式部署不設定 |

---

## 10. 對照：設計章節與 Rule 編號

| Rule 來源檔 | Rule 編號與原文 | 本階段哪個 Task 落實 |
|---|---|---|
| `執行教學流程.feature` | Rule 6「每個 Step Functions Task 設定 Retry」 | Task 10（`check_asl_document` 檢查 Retry 且涵蓋 `TransientError`） |
| `執行教學流程.feature` | Rule 7「每個 Step Functions Task 設定 Catch」 | Task 10（檢查 Catch 涵蓋 `States.ALL` 且導向 `PipelineFailed`） |
| `執行教學流程.feature` | Rule 8「LLM 輸出遵循指定 JSON schema」 | Task 7（`verify_version_complete` 不通過就整批不發布，對應釐清 F48「不發布不合規內容」） |
| `建立教學版本.feature` | Rule 1「新 Tutorial 的版本從 v1 起算」 | Task 5（重試重用原版號、永久失敗可留缺口，對應釐清 D26） |
| `建立教學版本.feature` | Rule 2「任一 pipeline 修改既有教學時使用該篇的下一個版本號」 | Task 5、Task 8（依接受順序串行，每次讀最新基底，對應釐清 F35） |
| `建立教學版本.feature` | Rule 3「新版以 supersedes 關聯同一篇教學的前一版」 | Task 8（`test_後到的改版從最新基底長下一版而不是分叉`） |
| `建立教學版本.feature` | Rule 5「每個版本的完整內容儲存在 tutorials/&lt;slug&gt;/v&lt;n&gt;.md」 | Task 4（`s3_after_md` 失敗後 md 保留在私有區，對應釐清 F36） |
| `建立教學版本.feature` | Rule 7「與前版的 diff 儲存在 tutorials/&lt;slug&gt;/v&lt;n&gt;.diff」 | Task 4（`s3_after_md` 失敗後 diff 不存在，版本判定為未完成） |
| `建立教學版本.feature` | Rule 8「建立 TutorialStep 時保存 references Feature 邊」 | Task 4（`ddb_after_version` 失敗後 `get_steps` 為空，`verify_version_complete` 不通過） |
| `發布教學版本.feature` | Rule 1「publish 上架指定的 TutorialVersion」 | Task 3、Task 7（全部驗證完成才提交） |
| `發布教學版本.feature` | Rule 4「Tutorial 的 current_version 指向目前教學版本」 | Task 4、Task 7（失敗時不切換，對應釐清 F37） |
| `發布教學版本.feature` | Rule 5「已上架的版本具有 published_at」 | Task 4（失敗時 `published_at` 維持 None，對應釐清 D25） |
| `接入來源事件.feature` | Rule 14「寫回新流程前 Step Functions 必須成功啟動」 | Task 4、Task 6（`start_execution` 切點失敗時不記 PROC 成功） |
| `接入來源事件.feature` | Rule 30「同一正規化事件重送時只處理一次」 | Task 6（重送回傳既有結果或沿用未完成執行，對應釐清 F09） |
| `接入來源事件.feature` | Rule 8「新流程每次完整成功才將 success_count 加 1」 | Task 6（`test_同一事件重送不新增_PROC_成功樣本`） |
| `收集教學回饋.feature` | Rule 10「同一使用者對同一版本的每次新提交都計一筆」 | Task 6（只排除同一提交 ID 的重送，對應釐清 D14） |
| `查詢知識圖譜.feature` | Rule 4「可查詢某篇 Tutorial 所屬的版本」 | Task 5（`list_versions_of_tutorial` 用來確認沒有跳號、沒有分叉） |

補充說明：

- **本計劃選擇（對應 O2）**：操作紀錄放在 DynamoDB `OPS#<operation_id>`（條件寫入做去重）與 S3 `operations/<id>.json`（保存原輸出與版號）；同篇教學寫入前先取 `LOCK#<slug>` 鎖（條件寫入 + TTL）。設計文件第 18 節把儲存形狀列為待確認。
- **本計劃選擇（對應 O3）**：接受「交易已提交但公開頁未寫」這個中間狀態存在，改為要求它在重送時能被補齊（`split_publish_targets`）。設計文件第 18 節 O3 的原話是「跨 S3、DynamoDB 與多篇教學的提交尚無完整契約」，本階段補的是驗收，不是宣稱契約已完備。
- **本計劃選擇**：注入失敗用環境變數 `TKB_FAULT`，切點限五個，`TKB_ENV=prod` 時一律不注入。設計文件沒有規定注入機制，只規定「針對公開、指標與多篇提交切點注入失敗」。
- **本計劃選擇（對應 O2）**：`ExecutionAlreadyExists` 且執行已結束時，只有操作紀錄 `status == "done"` 才沿用既有結果，其餘回報需要人工確認。設計文件 §14.2 只說「需檢查原結果與操作紀錄」，沒有指定判準。

---

## 11. 參考來源

設計文件（`docs/design/training-kb.md`）：

- §8.2 create_version 的完成條件（S3 成功但版本或關係未完成時，保留不可公開的產物）
- §8.3 發布與併發必須守住的界線（O3 原話：「在解決之前，不可宣稱 publish 的故障驗收已通過」）
- §9.3 S3 與執行資訊（`operations/` 的地位）
- §14.1 各層如何結束（S3／DynamoDB 部分寫入、Task 重試耗盡、同一事件重送）
- §14.2 重試不是重新抽一次文字（`StartExecution` 冪等限制、Retry／Catch、`States.ALL` 並非涵蓋所有終止錯誤）
- §14.3 執行參數的建議起點（重試兩次、等待 1 秒與 2 秒；Task 最多 120 秒）
- §15 測試與驗收設計（「版本與發布」「接入去重」「呼叫與失敗」三列）
- §16 交付切片 S0、S8
- §18 待確認事項 O2、O3
- §20.3、§20.6、§20.7、§20.9、§20.10、§20.12 的 Rule 對照

規格與釐清紀錄：

- `docs/spec/features/建立教學版本.feature`
- `docs/spec/features/發布教學版本.feature`
- `docs/spec/features/執行教學流程.feature`
- `docs/spec/features/接入來源事件.feature`
- `docs/spec/.clarify/resolved/features/接入來源事件_同一正規化事件重送時是否再次觸發_pipeline.md`（F09，答案 A）
- `docs/spec/.clarify/resolved/features/建立教學版本_內容已寫入但版本關聯不完整時如何處理.md`（F36，答案 A）
- `docs/spec/.clarify/resolved/features/發布教學版本_current_version_在哪個時點切換到新版.md`（F37，答案 A）
- `docs/spec/.clarify/resolved/features/執行教學流程_Task_重試耗盡並進入_Catch_後如何結束流程.md`（F49，答案 A）
- `docs/spec/.clarify/resolved/features/執行教學流程_LLM_輸出通過_schema_但違反業務規則時如何處理.md`（F48，答案 A）
- `docs/spec/.clarify/resolved/features/建立教學版本_同篇教學的_Release_與_Feedback_改版同時執行時如何排序.md`（F35，答案 A）
- `docs/spec/.clarify/resolved/data/TUTORIAL_VERSION_版本建立失敗後重試是否重用原版本號.md`（D26，答案 A）
- `docs/spec/.clarify/resolved/data/TUTORIAL_VERSION_尚未發布的版本如何與已發布版本區分.md`（D25，答案 A）
- `docs/spec/.clarify/resolved/data/FEEDBACK_同一使用者對同一版本多次回饋計為幾筆.md`（D14，答案 A）

外部官方文件（以 Context7 MCP 與 AWS 官方站查證）：

- Step Functions `StartExecution` API（同名冪等與 `ExecutionAlreadyExists`）：https://docs.aws.amazon.com/step-functions/latest/apireference/API_StartExecution.html
- Step Functions 錯誤處理（Retry、Catch、`States.ALL` 的範圍）：https://docs.aws.amazon.com/step-functions/latest/dg/concepts-error-handling.html
- boto3 `describe_execution`（狀態值 `RUNNING`／`SUCCEEDED`／`FAILED`／`TIMED_OUT`／`ABORTED`／`PENDING_REDRIVE`）：https://docs.aws.amazon.com/boto3/latest/reference/services/stepfunctions/client/describe_execution.html
- boto3 `update_function_configuration`（設定 Lambda 環境變數）：https://docs.aws.amazon.com/boto3/latest/reference/services/lambda/client/update_function_configuration.html
- DynamoDB 交易與大小限制：https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/transaction-apis.html
- DynamoDB 條件運算式：https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/Expressions.ConditionExpressions.html
- S3 條件寫入（避免同 key 覆蓋）：https://docs.aws.amazon.com/AmazonS3/latest/userguide/conditional-writes.html
- moto 使用方式（`from moto import mock_aws`）：https://docs.getmoto.org/en/latest/docs/getting_started.html
