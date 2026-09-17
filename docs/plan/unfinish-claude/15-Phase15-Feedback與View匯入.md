# Phase 15：Feedback 與 View 匯入

| 項目 | 內容 |
|---|---|
| 上一階段 | Phase 14：Step Functions 與 Lambda 上線（`14-Phase14-StepFunctions與Lambda上線.md`） |
| 下一階段 | Phase 16：Release Note Update 流程（`16-Phase16-Release-Note-Update流程.md`） |
| 對應設計文件章節 | §7.1、§7.6、§8.4、§9.1、§9.2、§11.2、§11.3、§13、§14.1（`docs/design/training-kb.md`） |
| 對應交付切片 | S4（設計文件第 16 節） |
| 預估時間 | 約 5 小時 |
| 做完會得到 | 一條把「使用者的評分／留言」與「誰在什麼時候看過哪一版」存進圖譜的固定路徑，資料可以被 Phase 19 拿去算指標 |

---

## 1. 這階段做完會得到什麼

前面做的是「系統自己長出教學」。這一階段做的是相反方向：**把使用者的回應收進來**。

做完之後你會有兩個新的匯入函式：

1. **`ingress.import_feedback`**：收一筆回饋（評分 1–5、可選的問題類別、可選的留言），驗完欄位、確認版本存在且教學沒退役之後，寫進 DynamoDB 並連上 `REFERS_TO` 邊。留言沒勾類別時，呼叫一次模型幫它分類。
2. **`ingress.import_view`**：收一筆瀏覽紀錄（哪一版、誰、什麼時候），寫進 DynamoDB。同一組三元組重送只算一次。

加上一份 `demo/cli.py` 的 `import` 子命令，以及兩份可以直接照抄的匯入檔範例（設計 §11.2 的八筆 A v1 回饋、§11.3 的十筆瀏覽）。

**這一階段最重要的一句話**：Feedback 與 View 走「固定保存路徑」——不經過 Rote、不啟動 Step Functions、不更新 PROC，也不會讓教學立刻改版。設計 §7.1 的表格與 F06 都明寫了這件事。

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
                                                                 ^^^^^^^^^^^^^^^^^^^^
                                                                 你在這裡
                                                                                        |
學習層          17 Review:REFINE -> 18 Review:候選規則+排程 -> 19 Analytics 指標 -> 20 規則驗證
                                                                                        |
展示與驗收層    21 Demo 種子資料 -> 22 靜態教學站 -> 23 Demo 控制台 -> 24 失敗復原驗收 -> 25 安全與當日準備
```

這一階段是 Phase 17（每日 Review 挑弱教學）、Phase 18（提出候選規則）、Phase 19（算平均評分與重開票率）的**唯一資料來源**。這裡少存一筆，後面三個階段的數字就對不起來。

---

## 3. 開始前檢查

| 前置條件 | 驗證指令 | 預期輸出 |
|---|---|---|
| Phase 01–14 的單元測試全綠 | `uv run pytest tests/unit -q` | 最後一行類似 `168 passed` |
| Phase 02 的模型與常數都在 | `uv run python -c "from training_kb.models import Feedback, TutorialView, APPROVED_CATEGORIES_DEFAULT, PENDING_CATEGORY; print(APPROVED_CATEGORIES_DEFAULT, PENDING_CATEGORY)"` | `['找不到按鈕', '缺少資訊'] 待分類` |
| Phase 02 的 `view_pk` 可用 | `uv run python -c "from training_kb.keys import view_pk; print(view_pk('a@v1','u_01','2026-08-02T09:00:00Z'))"` | 以 `VIEW#` 開頭、後面 32 個十六進位字元 |
| Phase 03 的 `get_config_list` 可用 | `uv run python -c "from training_kb.repository import Repository; print(hasattr(Repository,'get_config_list'))"` | `True` |
| Phase 05 的 schema 與 FakeWriter 可用 | `uv run python -c "from training_kb.writing.client import FakeWriter; from training_kb.writing.schemas import CommentClassification; print(CommentClassification.model_fields.keys())"` | `dict_keys(['category'])` |
| Phase 14 的 import handler 已經在 | `uv run python -c "from training_kb.handlers import import_; print(import_.SUPPORTED_KINDS)"` | `('ticket', 'release')` |
| Phase 07／08 的內容驗證測試仍是綠的 | `uv run pytest tests/unit/test_content_validate.py -q` | 全綠 |

---

## 4. 名詞小抄

| 名詞 | 白話解釋 | 在本階段哪裡用到 |
|---|---|---|
| Feedback | 使用者對「某一個教學版本」留下的評分、問題類別與留言 | `import_feedback` |
| Tutorial View | 一次瀏覽紀錄：誰、在什麼時候、看了哪一版 | `import_view` |
| 固定保存路徑 | 不經過 Rote 判斷、不啟動流程，程式直接驗證後寫入的路徑 | 設計 §7.1、F06 |
| 核定類別表（approved categories） | 一份「合法的問題類別」清單。初始值是「找不到按鈕」與「缺少資訊」 | `CONFIG#feedback_categories` |
| 待分類 | 類別無法對應到核定表時用的值，字面就是「待分類」 | `models.PENDING_CATEGORY` |
| 穩定使用者 ID | 同一個人在 Ticket、Feedback、View 三個地方用的是同一個字串，例如 `u_01` | D23；Phase 19 靠它算重開票率 |
| `REFERS_TO` 邊 | DynamoDB 裡一列資料，表示「這筆回饋指向那個版本」 | `FEEDBACK#f_12 -> VERSION#prepare-meeting@v1` |
| `view_pk` | 把 `[tutorial_version, user, ts]` 算成 SHA-256 再取前 32 字元當主鍵 | 瀏覽去重 |
| 操作紀錄（OPS） | `OPS#<operation_id>` 這一列，用來判斷「這件事是不是已經做過了」 | `import:feedback:<id>` |
| duplicate | 同一個 ID（或同一組瀏覽三元組）再送一次的結果，不會多算一筆樣本 | D14、F09 |
| rejected | 欄位不合法、版本不存在、教學已退役時的結果，會指出哪些欄位有問題 | F51 |
| retired（退役） | 教學的狀態之一。退役後拒收新回饋，既有回饋保留 | F39、設計 §8.4 |
| D11–D14、D23、D24 | 設計文件第 19.1 節的資料決策編號 | 本階段的規則來源 |
| F39、F51 | 設計文件第 19.2 節的功能決策編號 | 退役拒收、不合法回傳 |
| O2 | 設計文件第 18 節的待確認事項：操作紀錄與接受順序 | 匯入的去重作法要標示 |

---

## 5. 設計說明

### 5.1 固定保存路徑：它「不做」什麼比「做」什麼重要

```text
                     Ticket / Release                Feedback / View
                            |                              |
                            v                              v
                    +---------------+             +-----------------+
                    |     Rote      |             |  固定保存路徑   |
                    | 三層選 adapter |             | validate_* 直接 |
                    +---------------+             | 驗證欄位        |
                            |                     +-----------------+
                            v                              |
                    +---------------+                      v
                    | 更新 PROC 計數 |             +-----------------+
                    +---------------+             | 寫 DynamoDB      |
                            |                     | FEEDBACK / VIEW  |
                            v                     | + REFERS_TO 邊   |
                    +---------------+             +-----------------+
                    | StartExecution|                      |
                    +---------------+                      v
                            |                     +-----------------+
                            v                     |    結束          |
                    +---------------+             | 不啟動 Step      |
                    | Step Functions|             | Functions        |
                    +---------------+             | 不更新 PROC      |
                                                  | 不立刻改版       |
                                                  +-----------------+
```

三個「不」的依據：

- **不經 Rote**：F06 明寫「Feedback 不納入 PROVEN_WORKFLOW 學習，只使用固定接入保存流程」。
- **不啟動 Step Functions**：設計 §7.1 的表格寫「保存 FEEDBACK 與 REFERS_TO 關係；不啟動 Step Functions、不更新 PROC」。
- **不立刻改版**：`收集教學回饋.feature` Rule 8「收到單筆低分 Feedback 時不立即修改 Tutorial」。要改版得等 Phase 17 的每日 Review。

### 5.2 類別怎麼決定（勾選優先，非核定值進待分類）

這是本階段唯一會呼叫模型的地方，而且只在很窄的條件下才呼叫。

```text
                    收到一筆回饋
                          |
                有勾選 category 嗎？
                 /                 \
              有                    沒有
               |                      |
    在核定類別表裡嗎？          comment 是空的嗎？
      /            \                 /          \
    是             否              是            否
     |              |               |             |
  直接採用      category =      category =   呼叫模型分類一次
（不覆蓋）      「待分類」        None      prompt_classify_comment
                                              |
                                        回傳值在核定表裡嗎？
                                          /            \
                                        是              否
                                         |               |
                                      直接採用     category = 「待分類」
```

對應規格：

- `收集教學回饋.feature` Rule 4「使用者勾選的 Feedback Category 優先於模型分類」。
- Rule 5「Feedback Category 必須屬於核定類別表或待分類」＋ D13「使用可擴充的核定類別表；初始清單為找不到按鈕、缺少資訊；未知值進入待分類」。
- Rule 6「需要分類的自由留言在接入時計算一次 Feedback Category」＋ D12「只有評分而沒有類別與留言的回饋有效，只參與評分計算，不送模型分類」。

**不自動擴充類別表**（設計 §7.6）：模型回了一個沒見過的字串，我們把它改成「待分類」，而不是把它加進核定表。核定表只有維護者能改。

### 5.3 什麼情況拒絕、什麼情況算重複

```text
拒絕（rejected，指出欄位供修正）        重複（duplicate，不增加樣本）
------------------------------------    --------------------------------
id 沒有 f_ 前綴                          同一個 Feedback.id 再送一次
缺 tutorial_version / user               同一組 [版本, 使用者, 時間] 的瀏覽再送一次
rating 不是 1..5 的整數（0、6、3.5、"4"）
版本不存在於圖譜
所屬教學 status 是 retired
View 缺 ts
```

幾個容易搞錯的地方：

- **`rating` 必須是「整數」**。JSON 裡的 `4.0` 在 Python 會變成 `float`，`True` 在 Python 是 `bool`（而 `bool` 是 `int` 的子類別！）。兩者都要擋掉。
- **同一個人對同一版可以有很多筆回饋**（D14：每個新的 `Feedback.id` 都算一筆），只有「同一個提交 ID 重送」才算重複。
- **未發布的版本可以收回饋**。`收集教學回饋.feature` Rule 1 的補充寫「版本可未發布（`published_at` 空）但仍可存在於圖譜」。我們檢查的是「版本存在」，不是「版本已發布」。
- **回饋的 `ts` 可以缺，瀏覽的 `ts` 不能缺**。設計 §7.1：回饋缺值時用匯入時間並註明；瀏覽的 `ts` 必填，「不能以匯入時間補成先瀏覽的證據」。Phase 19 的重開票率要求 `view.ts < ticket.ts`，補假的時間會讓分子算錯。

### 5.4 寫進 DynamoDB 的長相

```text
DynamoDB 表 training_kb（PK, SK）

  PK                      SK                                   其他欄位
  ----------------------  -----------------------------------  --------------------------------
  FEEDBACK#f_12           META                                 entity=FEEDBACK
                                                               tutorial_version=prepare-meeting@v1
                                                               rating=2  user=u_01
                                                               category=找不到按鈕
                                                               comment=第三步沒有指出按鈕...
                                                               ts=2026-08-02T12:00:00Z

  FEEDBACK#f_12           REFERS_TO#VERSION#prepare-meeting@v1  target=VERSION#prepare-meeting@v1
                                                               （這一列讓 by_target 反查得到）

  VIEW#<sha256 前 32 碼>   META                                 entity=TUTORIAL_VIEW
                                                               tutorial_version=prepare-meeting@v1
                                                               user=u_01  ts=2026-08-02T09:00:00Z

  OPS#import:feedback:f_12 META                                entity=OPS  status=done
                                                               object_id=f_12

  CONFIG#feedback_categories META                              entity=CONFIG
                                                               values=["找不到按鈕","缺少資訊"]
```

兩個設計重點：

- **View 沒有關係邊。** 設計 §9.2 明寫「View 先依既有欄位掃描篩選，不新增規格未列的 VIEWED 關係」。Phase 19 會用 `scan_entity("TUTORIAL_VIEW")` 再依 `tutorial_version` 篩。
- **`view_pk` 是去重鍵，不是使用者 ID。** 設計 §9.1：「相同三元組重送得到相同 PK；不同瀏覽時間建立不同紀錄……它只用於瀏覽去重，不是使用者 ID」。

### 5.5 重送時怎麼判斷（本計劃選擇，對應 O2）

```text
  import_feedback(f_12)
        |
  begin_operation("import:feedback:f_12")
        |
   +----+---------------------------+
   | 回 True（第一次）              | 回 False（OPS 已存在）
   v                                v
  繼續寫入                    FEEDBACK#f_12 存在嗎？
                                  /          \
                                是            否
                                 |             |
                          回 duplicate    繼續寫入
                          （不增加樣本）  （上次寫到一半，這次補完）
```

設計 §14.1 要求「同一事件／Feedback 重送：取得既有結果或沿用未完成邏輯操作；不新增版本、回饋樣本或 PROC 成功樣本」。只看操作紀錄會漏掉「紀錄寫了但資料沒寫完」這一種情形，所以要再確認實際資料在不在。這是**本計劃選擇，對應設計第 18 節的 O2**。

### 5.6 本階段新增的目錄結構

```text
AWS-Hackathon/
  src/training_kb/
    ingress.py                  <- 修改：approved_categories、validate_feedback、
                                   validate_view、import_feedback、import_view
    handlers/import_.py         <- 修改：feedback／view 接到真的匯入函式
  demo/
    cli.py                      <- 新增（只做 import 子命令，其餘 Phase 23 補）
  tests/
    unit/
      test_feedback_validate.py     test_view_validate.py
      test_import_feedback.py       test_import_view.py
      test_handler_import_feedback.py
      test_demo_cli_import.py
    fixtures/
      import_feedback_a_v1.json  <- 設計 §11.2 的八筆
      import_views_a_v1.json     <- 設計 §11.3 的十筆
```

---

## 6. 工作項目

### Task 1：核定類別表 `CONFIG#feedback_categories`

**目的**：提供一個「合法問題類別」的單一來源，沒設定時用 D13 的初始清單。

**檔案**：
- 修改：`src/training_kb/ingress.py`
- 測試：`tests/unit/test_feedback_validate.py`（本 Task 只加前兩個測試）

**介面**：
- 消費：`repository.Repository.get_config_list(name, default) -> list[str]`（Phase 03）、`models.APPROVED_CATEGORIES_DEFAULT`、`models.PENDING_CATEGORY`（Phase 02）
- 產出：
  - `ingress.FEEDBACK_CATEGORIES_CONFIG: str`（值為 `"feedback_categories"`）
  - `ingress.approved_categories(repo) -> list[str]`
  - `ingress.resolve_category(raw: str | None, categories: list[str]) -> str | None`
  - 註：這三項簡報第 6.6 節未列，是本階段為了落實 D13 與 `收集教學回饋.feature` Rule 5 新增的。

- [ ] **步驟 1：寫測試**

```python
# tests/unit/test_feedback_validate.py
"""核定類別表與回饋欄位驗證（設計 §7.1、D12、D13）。"""

from __future__ import annotations

from training_kb import ingress
from training_kb.models import APPROVED_CATEGORIES_DEFAULT, PENDING_CATEGORY


class FakeRepo:
    def __init__(self, config: dict[str, list[str]] | None = None):
        self.config = config or {}

    def get_config_list(self, name: str, default: list[str]) -> list[str]:
        return self.config.get(name, default)


def test_沒有設定時用初始核定類別():
    assert ingress.approved_categories(FakeRepo()) == APPROVED_CATEGORIES_DEFAULT
    assert APPROVED_CATEGORIES_DEFAULT == ["找不到按鈕", "缺少資訊"]


def test_維護者擴充過就用擴充後的清單():
    repo = FakeRepo({"feedback_categories": ["找不到按鈕", "缺少資訊", "步驟順序錯誤"]})
    assert "步驟順序錯誤" in ingress.approved_categories(repo)


def test_resolve_category_核定值直接用():
    assert ingress.resolve_category("找不到按鈕", APPROVED_CATEGORIES_DEFAULT) == "找不到按鈕"


def test_resolve_category_非核定值變待分類():
    assert ingress.resolve_category("介面太醜", APPROVED_CATEGORIES_DEFAULT) == PENDING_CATEGORY


def test_resolve_category_空值回_none():
    assert ingress.resolve_category(None, APPROVED_CATEGORIES_DEFAULT) is None
    assert ingress.resolve_category("   ", APPROVED_CATEGORIES_DEFAULT) is None


def test_待分類本身也視為合法值():
    assert ingress.resolve_category(PENDING_CATEGORY, APPROVED_CATEGORIES_DEFAULT) == PENDING_CATEGORY
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：`uv run pytest tests/unit/test_feedback_validate.py -v`

預期：FAIL，`AttributeError: module 'training_kb.ingress' has no attribute 'approved_categories'`。

- [ ] **步驟 3：寫最少的程式讓測試通過**

在 `src/training_kb/ingress.py` 加上：

```python
# ---- Phase 15：核定類別表 ---------------------------------------------------

from training_kb.models import APPROVED_CATEGORIES_DEFAULT, PENDING_CATEGORY

#: CONFIG item 的名稱；完整 PK 是 keys.config_pk("feedback_categories")。
FEEDBACK_CATEGORIES_CONFIG = "feedback_categories"


def approved_categories(repo) -> list[str]:
    """回傳目前的核定問題類別清單（D13：可擴充，初始為找不到按鈕、缺少資訊）。"""
    return repo.get_config_list(FEEDBACK_CATEGORIES_CONFIG, list(APPROVED_CATEGORIES_DEFAULT))


def resolve_category(raw: str | None, categories: list[str]) -> str | None:
    """把一個類別字串收斂成合法值。

    - 空值（None 或只有空白）-> None
    - 在核定表裡，或本身就是「待分類」-> 原樣採用
    - 其他 -> 「待分類」（不自動擴充核定表，設計 §7.6）
    """
    value = (raw or "").strip()
    if not value:
        return None
    if value in categories or value == PENDING_CATEGORY:
        return value
    return PENDING_CATEGORY
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：`uv run pytest tests/unit/test_feedback_validate.py -v`

預期：PASS，6 個測試綠色。

- [ ] **步驟 5：commit**

```bash
git add tests/unit/test_feedback_validate.py src/training_kb/ingress.py
git commit -m "feat(ingress): 加入核定回饋類別表與類別收斂"
```

---

### Task 2：`validate_feedback`——欄位層級的驗證

**目的**：把一包 dict 變成合法的 `Feedback`，不合法就指出是哪些欄位。這一層只看欄位本身，不碰資料庫。

**檔案**：
- 修改：`src/training_kb/ingress.py`
- 測試：`tests/unit/test_feedback_validate.py`（追加）

**介面**：
- 消費：`models.Feedback`（Phase 02）、`errors.IngressError(message, fields)`（Phase 01）、`clock.to_iso(dt)`（Phase 01）
- 產出：`ingress.validate_feedback(data: dict, *, now: datetime) -> Feedback`

驗證清單（缺一不可）：

| 欄位 | 規則 | 依據 |
|---|---|---|
| `id` | 必填，字串，必須以 `f_` 開頭 | D02、`接入來源事件.feature` Rule 24 |
| `tutorial_version` | 必填、非空字串（「存在於圖譜」留給 Task 4 查） | `收集教學回饋.feature` Rule 1 |
| `rating` | 必填，**整數** 1..5；拒絕 0、6、3.5、`"4"`、`True` | Rule 3 |
| `user` | 必填、非空字串 | Rule 9、D11、D23 |
| `category` | 可空；值的收斂在 Task 4 做 | Rule 4、Rule 5 |
| `comment` | 可空 | D12 |
| `ts` | 可空；缺值時用匯入時間 | 設計 §7.1 |

- [ ] **步驟 1：寫測試**（追加到 `tests/unit/test_feedback_validate.py` 檔尾）

```python
# --- Task 2：validate_feedback ------------------------------------------------

from datetime import UTC, datetime

import pytest

from training_kb.errors import IngressError

NOW = datetime(2026, 9, 1, 3, 4, 5, tzinfo=UTC)


def base(**overrides) -> dict:
    data = {
        "id": "f_12",
        "tutorial_version": "prepare-meeting@v1",
        "rating": 2,
        "user": "u_01",
        "category": "找不到按鈕",
        "comment": "第三步沒有指出按鈕在哪一頁與位置",
        "ts": "2026-08-02T12:00:00Z",
    }
    data.update(overrides)
    return {k: v for k, v in data.items() if v is not ...}


def test_完整的回饋通過驗證():
    feedback = ingress.validate_feedback(base(), now=NOW)
    assert feedback.id == "f_12"
    assert feedback.rating == 2
    assert feedback.user == "u_01"
    assert feedback.tutorial_version == "prepare-meeting@v1"


@pytest.mark.parametrize("rating", [1, 2, 3, 4, 5])
def test_rating_1_到_5_都合法(rating):
    assert ingress.validate_feedback(base(rating=rating), now=NOW).rating == rating


@pytest.mark.parametrize("rating", [0, 6, -1, 3.5, "4", True, None])
def test_rating_不合法時指出欄位(rating):
    with pytest.raises(IngressError) as err:
        ingress.validate_feedback(base(rating=rating), now=NOW)
    assert err.value.fields == ["rating"]


def test_只有評分的回饋仍然有效():
    # D12：category 為空、comment 為空，只參與評分計算。
    feedback = ingress.validate_feedback(
        base(category=..., comment=...), now=NOW
    )
    assert feedback.category is None
    assert feedback.comment is None


def test_缺少_user_時操作失敗():
    with pytest.raises(IngressError) as err:
        ingress.validate_feedback(base(user=...), now=NOW)
    assert err.value.fields == ["user"]


def test_id_沒有_f_前綴時操作失敗():
    with pytest.raises(IngressError) as err:
        ingress.validate_feedback(base(id="12"), now=NOW)
    assert err.value.fields == ["id"]


def test_缺少_tutorial_version_時操作失敗():
    with pytest.raises(IngressError) as err:
        ingress.validate_feedback(base(tutorial_version=...), now=NOW)
    assert err.value.fields == ["tutorial_version"]


def test_多個欄位同時不合法時全部列出():
    with pytest.raises(IngressError) as err:
        ingress.validate_feedback({"id": "x", "rating": 9}, now=NOW)
    assert set(err.value.fields) == {"id", "tutorial_version", "rating", "user"}


def test_ts_缺值時用匯入時間():
    feedback = ingress.validate_feedback(base(ts=...), now=NOW)
    assert feedback.ts == "2026-09-01T03:04:05Z"


def test_ts_有值時保留來源時間():
    feedback = ingress.validate_feedback(base(ts="2026-08-02T12:00:00Z"), now=NOW)
    assert feedback.ts == "2026-08-02T12:00:00Z"
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：`uv run pytest tests/unit/test_feedback_validate.py -v`

預期：FAIL，`AttributeError: module 'training_kb.ingress' has no attribute 'validate_feedback'`（Phase 10 只寫了 `validate_ticket` 與 `validate_release`）。

- [ ] **步驟 3：寫最少的程式讓測試通過**

```python
# ---- Phase 15：Feedback 欄位驗證 --------------------------------------------

from datetime import datetime

from training_kb.clock import to_iso
from training_kb.errors import IngressError
from training_kb.models import Feedback


def _required_text(data: dict, field: str, bad: list[str]) -> str:
    value = data.get(field)
    if not isinstance(value, str) or not value.strip():
        bad.append(field)
        return ""
    return value.strip()


def validate_feedback(data: dict, *, now: datetime) -> Feedback:
    """驗證一筆回饋的欄位；不查資料庫（版本是否存在留給 import_feedback）。"""
    bad: list[str] = []

    feedback_id = _required_text(data, "id", bad)
    if feedback_id and not feedback_id.startswith("f_"):
        bad.append("id")
    tutorial_version = _required_text(data, "tutorial_version", bad)
    user = _required_text(data, "user", bad)

    rating = data.get("rating")
    # bool 是 int 的子類別，要先擋掉，否則 True 會被當成 1。
    if isinstance(rating, bool) or not isinstance(rating, int) or not 1 <= rating <= 5:
        bad.append("rating")

    raw_ts = data.get("ts")
    ts = raw_ts.strip() if isinstance(raw_ts, str) and raw_ts.strip() else to_iso(now)

    category = data.get("category")
    if category is not None and not isinstance(category, str):
        bad.append("category")
    comment = data.get("comment")
    if comment is not None and not isinstance(comment, str):
        bad.append("comment")

    if bad:
        raise IngressError(
            "回饋欄位不合法：" + "、".join(sorted(set(bad))), sorted(set(bad))
        )

    return Feedback(
        id=feedback_id,
        tutorial_version=tutorial_version,
        rating=int(rating),
        user=user,
        category=(category.strip() or None) if isinstance(category, str) else None,
        comment=(comment.strip() or None) if isinstance(comment, str) else None,
        ts=ts,
    )
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：`uv run pytest tests/unit/test_feedback_validate.py -v`

預期：PASS，共 22 個測試（含 parametrize 展開）綠色。

- [ ] **步驟 5：commit**

```bash
git add tests/unit/test_feedback_validate.py src/training_kb/ingress.py
git commit -m "feat(ingress): 加入回饋欄位驗證"
```

---

### Task 3：`validate_view`——瀏覽紀錄的欄位驗證

**目的**：驗證瀏覽紀錄的三個欄位，其中 `ts` 必填。

**檔案**：
- 修改：`src/training_kb/ingress.py`
- 測試：`tests/unit/test_view_validate.py`

**介面**：
- 消費：`models.TutorialView`（Phase 02）、`errors.IngressError`
- 產出：`ingress.validate_view(data: dict) -> TutorialView`

- [ ] **步驟 1：寫測試**

```python
# tests/unit/test_view_validate.py
"""瀏覽紀錄的欄位驗證（設計 §7.1：View 的 ts 必填）。"""

from __future__ import annotations

import pytest

from training_kb import ingress
from training_kb.errors import IngressError


def base(**overrides) -> dict:
    data = {
        "tutorial_version": "prepare-meeting@v1",
        "user": "u_01",
        "ts": "2026-08-02T09:00:00Z",
    }
    data.update(overrides)
    return {k: v for k, v in data.items() if v is not ...}


def test_完整的瀏覽紀錄通過驗證():
    view = ingress.validate_view(base())
    assert view.tutorial_version == "prepare-meeting@v1"
    assert view.user == "u_01"
    assert view.ts == "2026-08-02T09:00:00Z"


def test_ts_必填不可用匯入時間補():
    with pytest.raises(IngressError) as err:
        ingress.validate_view(base(ts=...))
    assert err.value.fields == ["ts"]


def test_缺少_user_時操作失敗():
    with pytest.raises(IngressError) as err:
        ingress.validate_view(base(user=...))
    assert err.value.fields == ["user"]


def test_缺少_tutorial_version_時操作失敗():
    with pytest.raises(IngressError) as err:
        ingress.validate_view(base(tutorial_version=...))
    assert err.value.fields == ["tutorial_version"]


def test_ts_不是_iso_8601_時操作失敗():
    with pytest.raises(IngressError) as err:
        ingress.validate_view(base(ts="2026/08/02 09:00"))
    assert err.value.fields == ["ts"]
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：`uv run pytest tests/unit/test_view_validate.py -v`

預期：FAIL，`AttributeError: module 'training_kb.ingress' has no attribute 'validate_view'`。

- [ ] **步驟 3：寫最少的程式讓測試通過**

```python
# ---- Phase 15：View 欄位驗證 ------------------------------------------------

from training_kb.clock import parse_iso
from training_kb.models import TutorialView


def validate_view(data: dict) -> TutorialView:
    """驗證一筆瀏覽紀錄。

    設計 §7.1：瀏覽的 ts 必填，不能以匯入時間補成「先瀏覽」的證據。
    """
    bad: list[str] = []
    tutorial_version = _required_text(data, "tutorial_version", bad)
    user = _required_text(data, "user", bad)
    ts = _required_text(data, "ts", bad)
    if ts:
        try:
            parse_iso(ts)
        except ValueError:
            bad.append("ts")
    if bad:
        raise IngressError(
            "瀏覽紀錄欄位不合法：" + "、".join(sorted(set(bad))), sorted(set(bad))
        )
    return TutorialView(tutorial_version=tutorial_version, user=user, ts=ts)
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：`uv run pytest tests/unit/test_view_validate.py -v`

預期：PASS，5 個測試綠色。

- [ ] **步驟 5：commit**

```bash
git add tests/unit/test_view_validate.py src/training_kb/ingress.py
git commit -m "feat(ingress): 加入瀏覽紀錄欄位驗證"
```

---

### Task 4：`import_feedback`——真的把回饋寫進圖譜

**目的**：驗證欄位、確認版本存在且教學未退役、決定類別、寫 FEEDBACK 與 `REFERS_TO` 邊、處理重送。

**檔案**：
- 修改：`src/training_kb/ingress.py`
- 測試：`tests/unit/test_import_feedback.py`

**介面**：
- 消費：`ingress.validate_feedback`（Task 2）、`ingress.approved_categories` 與 `resolve_category`（Task 1）、`ingress.operation_id_for(kind, bare_id) -> str`（Phase 10）、`models.parse_version_id(version_id) -> tuple[str, int]`、`models.TutorialStatus`、`repository.Repository`（`get_version`、`get_tutorial`、`get_feedback`、`put_feedback`、`begin_operation`、`load_operation`、`update_operation`；Phase 09 的 `put_feedback` 已經連 `REFERS_TO` 邊一起寫，所以這裡不再自己呼叫 `put_edge`）、`writing.prompts.prompt_classify_comment(comment, categories) -> tuple[str, str]`、`writing.schemas.CommentClassification`、`writing.client.Writer.generate_json`
- 產出：
  - `ingress.ImportResult`（dataclass；欄位 `status`、`object_id`、`message`、`invalid_fields`）
  - `ingress.CLASSIFY_MAX_TOKENS: int`、`ingress.CLASSIFY_TEMPERATURE: float`
  - `ingress.import_feedback(repo, writer, data: dict, *, now: datetime) -> ImportResult`

> **為什麼分類用的是模組常數而不是 `Settings`。** 簡報第 6.6 節把簽名定成 `import_feedback(repo, writer, data, *, now)`，沒有 `settings` 參數。為了不改簽名，分類的 `max_tokens` 與 `temperature` 放成模組常數，值對齊 `Settings.gen_max_tokens_judgement`（512）與 `Settings.gen_temperature`（0.1），依據是設計 §14.3「一般判斷模型 max_tokens 512、temperature 0.1」。這是**本計劃選擇**，若日後要讓它可調，請一併更新簡報的介面契約。

- [ ] **步驟 1：寫測試**

```python
# tests/unit/test_import_feedback.py
"""import_feedback：版本檢查、退役拒絕、類別決定、重送去重。"""

from __future__ import annotations

from datetime import UTC, datetime

from training_kb import ingress
from training_kb.keys import feedback_pk, version_pk
from training_kb.models import (
    PENDING_CATEGORY,
    Feedback,
    Tutorial,
    TutorialStatus,
    TutorialVersion,
)
from training_kb.writing.schemas import CommentClassification

NOW = datetime(2026, 9, 1, 3, 4, 5, tzinfo=UTC)
VERSION_ID = "prepare-meeting@v1"


class FakeRepo:
    """夠用的假 Repository：只實作 import_feedback 會呼叫到的方法。"""

    def __init__(self, *, status: TutorialStatus = TutorialStatus.active, version_exists=True):
        self.versions = (
            {VERSION_ID: TutorialVersion(
                version_id=VERSION_ID, supersedes=None, reason="gap:c12",
                rules_applied=[], s3_key="tutorials/prepare-meeting/v1.md", published_at=None,
            )}
            if version_exists
            else {}
        )
        self.tutorials = {
            "prepare-meeting": Tutorial(
                slug="prepare-meeting", current_version=None, topic="準備會議",
                feature_ids=["Prepare"], status=status, successor=None, cluster_id="c12",
            )
        }
        self.feedback: dict[str, Feedback] = {}
        self.edges: list[tuple[str, str, str]] = []
        self.operations: dict[str, dict] = {}
        self.config: dict[str, list[str]] = {}

    def get_config_list(self, name, default):
        return self.config.get(name, default)

    def get_version(self, version_id):
        return self.versions.get(version_id)

    def get_tutorial(self, slug):
        return self.tutorials.get(slug)

    def get_feedback(self, feedback_id):
        return self.feedback.get(feedback_id)

    def put_feedback(self, feedback, *, if_not_exists=False):
        created = feedback.id not in self.feedback
        self.feedback[feedback.id] = feedback
        # 與 Phase 09 的真實實作一致：本體與 REFERS_TO 邊一起寫。
        self.edges.append(
            (feedback_pk(feedback.id), "REFERS_TO", version_pk(feedback.tutorial_version))
        )
        return created

    def begin_operation(self, operation_id, record):
        if operation_id in self.operations:
            return False
        self.operations[operation_id] = dict(record)
        return True

    def load_operation(self, operation_id):
        return self.operations.get(operation_id)

    def update_operation(self, operation_id, patch):
        self.operations.setdefault(operation_id, {}).update(patch)


class FakeClassifier:
    """只回傳預先排定分類結果的假 Writer。"""

    def __init__(self, category: str = "找不到按鈕"):
        self.category = category
        self.calls = 0

    def generate_json(self, *, system, user, schema, operation_id, node, max_tokens, temperature=0.1):
        self.calls += 1
        self.last = {"node": node, "max_tokens": max_tokens, "temperature": temperature}
        return CommentClassification(category=self.category)


def payload(**overrides) -> dict:
    data = {
        "id": "f_12",
        "tutorial_version": VERSION_ID,
        "rating": 2,
        "user": "u_01",
        "category": "找不到按鈕",
        "comment": "第三步沒有指出按鈕在哪一頁與位置",
        "ts": "2026-08-02T12:00:00Z",
    }
    data.update(overrides)
    return {k: v for k, v in data.items() if v is not ...}


def test_成功寫入_feedback_與_refers_to_邊():
    repo, writer = FakeRepo(), FakeClassifier()

    result = ingress.import_feedback(repo, writer, payload(), now=NOW)

    assert result.status == "saved"
    assert result.object_id == "f_12"
    assert repo.feedback["f_12"].rating == 2
    assert repo.edges == [(feedback_pk("f_12"), "REFERS_TO", version_pk(VERSION_ID))]
    assert repo.operations["import:feedback:f_12"]["status"] == "done"


def test_勾選的核定類別優先不呼叫模型():
    repo, writer = FakeRepo(), FakeClassifier(category="缺少資訊")

    ingress.import_feedback(repo, writer, payload(category="找不到按鈕"), now=NOW)

    assert repo.feedback["f_12"].category == "找不到按鈕"
    assert writer.calls == 0


def test_勾選的非核定類別直接變待分類且不呼叫模型():
    repo, writer = FakeRepo(), FakeClassifier()

    ingress.import_feedback(repo, writer, payload(category="介面太醜"), now=NOW)

    assert repo.feedback["f_12"].category == PENDING_CATEGORY
    assert writer.calls == 0


def test_未勾選且留言非空時呼叫一次模型():
    repo, writer = FakeRepo(), FakeClassifier(category="缺少資訊")

    ingress.import_feedback(repo, writer, payload(category=...), now=NOW)

    assert writer.calls == 1
    assert repo.feedback["f_12"].category == "缺少資訊"
    assert writer.last["max_tokens"] == ingress.CLASSIFY_MAX_TOKENS
    assert writer.last["temperature"] == ingress.CLASSIFY_TEMPERATURE


def test_模型回了不在核定表的類別就變待分類():
    repo, writer = FakeRepo(), FakeClassifier(category="使用者不會用")

    ingress.import_feedback(repo, writer, payload(category=...), now=NOW)

    assert repo.feedback["f_12"].category == PENDING_CATEGORY


def test_未勾選且留言為空時類別是_none_且不呼叫模型():
    repo, writer = FakeRepo(), FakeClassifier()

    result = ingress.import_feedback(repo, writer, payload(category=..., comment=...), now=NOW)

    assert result.status == "saved"
    assert repo.feedback["f_12"].category is None
    assert writer.calls == 0


def test_版本不存在時拒絕並指出欄位():
    repo, writer = FakeRepo(version_exists=False), FakeClassifier()

    result = ingress.import_feedback(repo, writer, payload(), now=NOW)

    assert result.status == "rejected"
    assert result.invalid_fields == ["tutorial_version"]
    assert repo.feedback == {}


def test_教學已退役時拒絕新回饋():
    repo, writer = FakeRepo(status=TutorialStatus.retired), FakeClassifier()

    result = ingress.import_feedback(repo, writer, payload(), now=NOW)

    assert result.status == "rejected"
    assert result.invalid_fields == ["tutorial_version"]
    assert "退役" in result.message
    assert repo.feedback == {}


def test_欄位不合法時拒絕並列出欄位():
    repo, writer = FakeRepo(), FakeClassifier()

    result = ingress.import_feedback(repo, writer, payload(rating=6), now=NOW)

    assert result.status == "rejected"
    assert result.invalid_fields == ["rating"]


def test_同一個_id_重送時是_duplicate_且不增加樣本():
    repo, writer = FakeRepo(), FakeClassifier()

    first = ingress.import_feedback(repo, writer, payload(), now=NOW)
    second = ingress.import_feedback(repo, writer, payload(rating=5), now=NOW)

    assert first.status == "saved"
    assert second.status == "duplicate"
    assert repo.feedback["f_12"].rating == 2       # 沒有被覆蓋
    assert len(repo.edges) == 1                    # 沒有多一條邊
    assert writer.calls == 0


def test_同一人不同_id_的兩筆都算樣本():
    repo, writer = FakeRepo(), FakeClassifier()

    ingress.import_feedback(repo, writer, payload(id="f_12"), now=NOW)
    ingress.import_feedback(repo, writer, payload(id="f_13", rating=3), now=NOW)

    assert sorted(repo.feedback) == ["f_12", "f_13"]


def test_操作紀錄寫了但資料沒寫完時會補完():
    repo, writer = FakeRepo(), FakeClassifier()
    repo.operations["import:feedback:f_12"] = {"status": "started"}

    result = ingress.import_feedback(repo, writer, payload(), now=NOW)

    assert result.status == "saved"
    assert "f_12" in repo.feedback


def test_ts_缺值時在訊息裡註明用了匯入時間():
    repo, writer = FakeRepo(), FakeClassifier()

    result = ingress.import_feedback(repo, writer, payload(ts=...), now=NOW)

    assert result.status == "saved"
    assert "匯入時間" in result.message
    assert repo.feedback["f_12"].ts == "2026-09-01T03:04:05Z"


def test_未發布的版本仍可收回饋():
    repo, writer = FakeRepo(), FakeClassifier()
    assert repo.get_version(VERSION_ID).published_at is None

    assert ingress.import_feedback(repo, writer, payload(), now=NOW).status == "saved"
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：`uv run pytest tests/unit/test_import_feedback.py -v`

預期：FAIL，`AttributeError: module 'training_kb.ingress' has no attribute 'import_feedback'`。

- [ ] **步驟 3：寫最少的程式讓測試通過**

```python
# ---- Phase 15：Feedback 匯入 ------------------------------------------------

from dataclasses import dataclass
from typing import Literal

from training_kb.models import TutorialStatus, parse_version_id
from training_kb.writing.prompts import prompt_classify_comment
from training_kb.writing.schemas import CommentClassification

#: 留言分類屬於「判斷節點」，沿用設計 §14.3 的一般判斷參數。
CLASSIFY_MAX_TOKENS = 512
CLASSIFY_TEMPERATURE = 0.1


@dataclass
class ImportResult:
    status: Literal["saved", "duplicate", "rejected"]
    object_id: str | None
    message: str
    invalid_fields: list[str]


def _rejected(message: str, fields: list[str]) -> ImportResult:
    return ImportResult(status="rejected", object_id=None, message=message, invalid_fields=fields)


def import_feedback(repo, writer, data: dict, *, now: datetime) -> ImportResult:
    """把一筆回饋存進圖譜（設計 §7.1 的固定保存路徑）。

    不經 Rote、不啟動 Step Functions、不更新 PROC、不立刻改版。
    """
    try:
        feedback = validate_feedback(data, now=now)
    except IngressError as exc:
        return _rejected(str(exc), list(exc.fields))

    raw_ts = data.get("ts")
    ts_defaulted = not (isinstance(raw_ts, str) and raw_ts.strip())

    # 版本必須存在於圖譜；未發布（published_at 為空）仍然可以收回饋。
    if repo.get_version(feedback.tutorial_version) is None:
        return _rejected(
            f"版本 {feedback.tutorial_version} 不存在於圖譜", ["tutorial_version"]
        )
    try:
        slug, _n = parse_version_id(feedback.tutorial_version)
    except ValueError:
        return _rejected("tutorial_version 格式不正確", ["tutorial_version"])
    tutorial = repo.get_tutorial(slug)
    if tutorial is None:
        return _rejected(f"找不到教學 {slug}", ["tutorial_version"])
    if tutorial.status == TutorialStatus.retired:
        # F39：已退役教學的既有版本拒絕新回饋，既有回饋保留供歷史查詢。
        return _rejected(f"教學 {slug} 已退役，拒絕新回饋", ["tutorial_version"])

    operation_id = operation_id_for("feedback", feedback.id)
    started = repo.begin_operation(
        operation_id,
        {"kind": "import:feedback", "object_id": feedback.id, "status": "started", "at": to_iso(now)},
    )
    if not started and repo.get_feedback(feedback.id) is not None:
        # D14：只有同一個提交 ID 的重送算重複，不增加樣本。
        return ImportResult(
            status="duplicate",
            object_id=feedback.id,
            message=f"回饋 {feedback.id} 已匯入，不重複計算樣本",
            invalid_fields=[],
        )

    categories = approved_categories(repo)
    category = resolve_category(feedback.category, categories)
    if category is None and (feedback.comment or "").strip():
        # 只有「未勾選類別 + 留言非空」才呼叫模型，而且只呼叫一次。
        system, user = prompt_classify_comment(feedback.comment or "", categories)
        judged: CommentClassification = writer.generate_json(
            system=system,
            user=user,
            schema=CommentClassification,
            operation_id=operation_id,
            node="classify_comment",
            max_tokens=CLASSIFY_MAX_TOKENS,
            temperature=CLASSIFY_TEMPERATURE,
        )
        category = resolve_category(judged.category, categories)
    feedback = feedback.model_copy(update={"category": category})

    # Phase 09 的 put_feedback 會同時寫 FEEDBACK META 與 REFERS_TO 邊。
    repo.put_feedback(feedback)
    repo.update_operation(
        operation_id,
        {"status": "done", "object_id": feedback.id, "category": category, "at": to_iso(now)},
    )

    message = f"已保存回饋 {feedback.id}"
    if ts_defaulted:
        message += f"；來源未提供 ts，已記錄匯入時間 {feedback.ts}（非使用者實際提交時間）"
    return ImportResult(status="saved", object_id=feedback.id, message=message, invalid_fields=[])
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：`uv run pytest tests/unit/test_import_feedback.py -v`

預期：PASS，14 個測試綠色。

- [ ] **步驟 5：commit**

```bash
git add tests/unit/test_import_feedback.py src/training_kb/ingress.py
git commit -m "feat(ingress): 加入回饋匯入與留言分類"
```

---

### Task 5：`import_view`——瀏覽紀錄匯入與去重

**目的**：把一筆瀏覽紀錄寫進 DynamoDB，同一組 `[版本, 使用者, 時間]` 重送只算一次。

**檔案**：
- 修改：`src/training_kb/ingress.py`
- 測試：`tests/unit/test_import_view.py`

**介面**：
- 消費：`ingress.validate_view`（Task 3）、`keys.view_pk(tutorial_version, user, ts) -> str`、`repository.Repository.get_version(version_id)`、`repository.Repository.put_view(view) -> bool`（Phase 09：內部用 `if_not_exists=True`，同一組三元組已存在時回傳 `False`）
- 產出：`ingress.import_view(repo, data: dict) -> ImportResult`

> **退役的教學還收不收瀏覽紀錄？** 收。F39 只說「已退役教學的既有版本拒絕新回饋」，沒有提到瀏覽。而且設計 §12.1 的重開票率分母就是「該版窗口內 TUTORIAL_VIEW 的不同 user」，少存瀏覽會讓分母變小、比率被高估。所以本階段的選擇是：**View 不檢查教學狀態，只檢查版本存在**。這是**本計劃選擇**，理由寫在這裡供審閱者確認。

- [ ] **步驟 1：寫測試**

```python
# tests/unit/test_import_view.py
"""import_view：版本檢查與瀏覽去重（設計 §9.1 的 view_pk）。"""

from __future__ import annotations

from training_kb import ingress
from training_kb.keys import view_pk
from training_kb.models import Tutorial, TutorialStatus, TutorialVersion

VERSION_ID = "prepare-meeting@v1"


class FakeRepo:
    def __init__(self, *, status: TutorialStatus = TutorialStatus.active, version_exists=True):
        self.versions = (
            {VERSION_ID: TutorialVersion(
                version_id=VERSION_ID, supersedes=None, reason="gap:c12",
                rules_applied=[], s3_key="tutorials/prepare-meeting/v1.md",
                published_at="2026-08-01T00:00:00Z",
            )}
            if version_exists
            else {}
        )
        self.tutorials = {
            "prepare-meeting": Tutorial(
                slug="prepare-meeting", current_version=VERSION_ID, topic="準備會議",
                feature_ids=["Prepare"], status=status, successor=None, cluster_id="c12",
            )
        }
        self.metas: dict[str, dict] = {}
        self.views: list = []

    def get_version(self, version_id):
        return self.versions.get(version_id)

    def get_tutorial(self, slug):
        return self.tutorials.get(slug)

    def put_view(self, view) -> bool:
        pk = view_pk(view.tutorial_version, view.user, view.ts)
        if pk in self.metas:
            return False
        self.metas[pk] = {
            "entity": "TUTORIAL_VIEW",
            "tutorial_version": view.tutorial_version,
            "user": view.user,
            "ts": view.ts,
        }
        self.views.append(view)
        return True


def payload(**overrides) -> dict:
    data = {"tutorial_version": VERSION_ID, "user": "u_01", "ts": "2026-08-02T09:00:00Z"}
    data.update(overrides)
    return {k: v for k, v in data.items() if v is not ...}


def test_成功寫入瀏覽紀錄():
    repo = FakeRepo()

    result = ingress.import_view(repo, payload())

    assert result.status == "saved"
    assert result.object_id == view_pk(VERSION_ID, "u_01", "2026-08-02T09:00:00Z")
    assert len(repo.views) == 1


def test_完全相同的三元組重送是_duplicate():
    repo = FakeRepo()

    ingress.import_view(repo, payload())
    second = ingress.import_view(repo, payload())

    assert second.status == "duplicate"
    assert len(repo.views) == 1


def test_同一人不同時間是兩筆不同紀錄():
    repo = FakeRepo()

    ingress.import_view(repo, payload(ts="2026-08-02T09:00:00Z"))
    ingress.import_view(repo, payload(ts="2026-08-02T10:00:00Z"))

    assert len(repo.views) == 2


def test_不同人同一時間是兩筆不同紀錄():
    repo = FakeRepo()

    ingress.import_view(repo, payload(user="u_01"))
    ingress.import_view(repo, payload(user="u_02"))

    assert len(repo.views) == 2


def test_版本不存在時拒絕():
    repo = FakeRepo(version_exists=False)

    result = ingress.import_view(repo, payload())

    assert result.status == "rejected"
    assert result.invalid_fields == ["tutorial_version"]
    assert repo.views == []


def test_缺_ts_時拒絕():
    repo = FakeRepo()

    result = ingress.import_view(repo, payload(ts=...))

    assert result.status == "rejected"
    assert result.invalid_fields == ["ts"]


def test_退役的教學仍然接受瀏覽紀錄():
    # F39 只限制「新回饋」；瀏覽是指標的分母來源（設計 §12.1），照收。
    repo = FakeRepo(status=TutorialStatus.retired)

    assert ingress.import_view(repo, payload()).status == "saved"
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：`uv run pytest tests/unit/test_import_view.py -v`

預期：FAIL，`AttributeError: module 'training_kb.ingress' has no attribute 'import_view'`。

- [ ] **步驟 3：寫最少的程式讓測試通過**

```python
# ---- Phase 15：View 匯入 ----------------------------------------------------

from training_kb.keys import view_pk


def import_view(repo, data: dict) -> ImportResult:
    """把一筆瀏覽紀錄存進圖譜。

    去重鍵是 keys.view_pk([tutorial_version, user, ts]) 的 SHA-256 前 32 字元
    （設計 §9.1）；它只用於去重，不是使用者 ID。
    """
    try:
        view = validate_view(data)
    except IngressError as exc:
        return _rejected(str(exc), list(exc.fields))

    if repo.get_version(view.tutorial_version) is None:
        return _rejected(f"版本 {view.tutorial_version} 不存在於圖譜", ["tutorial_version"])

    pk = view_pk(view.tutorial_version, view.user, view.ts)
    # put_view 內部用條件寫入；已存在時回傳 False，不覆蓋也不重複計算。
    if not repo.put_view(view):
        return ImportResult(
            status="duplicate",
            object_id=pk,
            message="相同版本、使用者與時間的瀏覽紀錄已存在，不重複計算",
            invalid_fields=[],
        )

    return ImportResult(
        status="saved",
        object_id=pk,
        message=f"已保存 {view.user} 於 {view.ts} 對 {view.tutorial_version} 的瀏覽紀錄",
        invalid_fields=[],
    )
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：`uv run pytest tests/unit/test_import_view.py -v`

預期：PASS，7 個測試綠色。

- [ ] **步驟 5：commit**

```bash
git add tests/unit/test_import_view.py src/training_kb/ingress.py
git commit -m "feat(ingress): 加入瀏覽紀錄匯入與去重"
```

---

### Task 6：`handlers/import_.py` 接上 feedback 與 view

**目的**：把 Phase 14 先回「未支援」的兩種 kind，換成真的呼叫 Task 4、Task 5。

**檔案**：
- 修改：`src/training_kb/handlers/import_.py`
- 測試：`tests/unit/test_handler_import_feedback.py`

**介面**：
- 消費：`ingress.import_feedback(repo, writer, data, *, now)`、`ingress.import_view(repo, data)`、`ingress.ImportResult`
- 產出：`handlers.import_.SUPPORTED_KINDS` 擴充為 `("ticket", "release", "feedback", "view")`；`UNSUPPORTED_KINDS` 變成空字典

- [ ] **步驟 1：寫測試**

```python
# tests/unit/test_handler_import_feedback.py
"""import handler：feedback 與 view 兩種 kind 的分派。"""

from __future__ import annotations

import pytest

from training_kb.handlers import import_ as import_handler
from training_kb.ingress import ImportResult


@pytest.fixture
def ctx():
    context = import_handler.ImportContext(
        settings=object(), repo=object(), rote=object(), starter=object(), writer=object()
    )
    import_handler.set_context(context)
    yield context
    import_handler.set_context(None)


def test_feedback_逐筆呼叫_import_feedback(ctx, monkeypatch):
    seen: list[dict] = []

    def fake(repo, writer, data, *, now):
        seen.append(data)
        return ImportResult(status="saved", object_id=data["id"], message="ok", invalid_fields=[])

    monkeypatch.setattr(import_handler.ingress, "import_feedback", fake)

    response = import_handler.handler(
        {"kind": "feedback", "source": "widget", "items": [{"id": "f_12"}, {"id": "f_15"}]}, None
    )

    assert response["count"] == 2
    assert [r["object_id"] for r in response["results"]] == ["f_12", "f_15"]
    assert len(seen) == 2


def test_view_逐筆呼叫_import_view(ctx, monkeypatch):
    monkeypatch.setattr(
        import_handler.ingress,
        "import_view",
        lambda repo, data: ImportResult(
            status="saved", object_id="VIEW#abc", message="ok", invalid_fields=[]
        ),
    )

    response = import_handler.handler(
        {"kind": "view", "source": "widget", "items": [{"user": "u_01"}]}, None
    )

    assert response["results"][0]["status"] == "saved"
    assert response["kind"] == "view"


def test_被拒絕的回饋會列出欄位(ctx, monkeypatch):
    monkeypatch.setattr(
        import_handler.ingress,
        "import_feedback",
        lambda repo, writer, data, *, now: ImportResult(
            status="rejected", object_id=None, message="rating 不合法", invalid_fields=["rating"]
        ),
    )

    response = import_handler.handler(
        {"kind": "feedback", "source": "widget", "items": [{"id": "f_1"}]}, None
    )

    assert response["results"][0]["status"] == "rejected"
    assert response["results"][0]["invalid_fields"] == ["rating"]


def test_feedback_與_view_不需要_source_枚舉(ctx, monkeypatch):
    # Ticket／Release 的 source 是枚舉；Feedback／View 沒有 source 欄位，
    # 這裡的 source 只是給維護者標示來源的自由文字。
    monkeypatch.setattr(
        import_handler.ingress,
        "import_view",
        lambda repo, data: ImportResult(
            status="saved", object_id="VIEW#abc", message="ok", invalid_fields=[]
        ),
    )
    response = import_handler.handler({"kind": "view", "source": "任意字串", "items": [{}]}, None)
    assert response["results"][0]["status"] == "saved"


def test_四種_kind_都被支援():
    assert set(import_handler.SUPPORTED_KINDS) == {"ticket", "release", "feedback", "view"}
    assert import_handler.UNSUPPORTED_KINDS == {}
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：`uv run pytest tests/unit/test_handler_import_feedback.py -v`

預期：FAIL。`test_四種_kind_都被支援` 會 `AssertionError`，其餘測試會拿到 `"status": "unsupported"` 而不是 `"saved"`。

- [ ] **步驟 3：寫最少的程式讓測試通過**

把 `src/training_kb/handlers/import_.py` 的常數與 `handler` 改成下面這樣（其餘不動）：

```python
SUPPORTED_KINDS: tuple[str, ...] = ("ticket", "release", "feedback", "view")
#: Phase 15 之後沒有未支援的種類了；保留這個字典是為了讓將來新增種類時有地方放。
UNSUPPORTED_KINDS: dict[str, str] = {}


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    kind = str(event.get("kind") or "")
    source = str(event.get("source") or "")
    items = event.get("items")
    now = now_utc()

    if kind in UNSUPPORTED_KINDS:
        message = UNSUPPORTED_KINDS[kind]
        count = len(items) if isinstance(items, list) else 1
        results = [
            {
                "status": "unsupported",
                "object_id": None,
                "execution_arn": None,
                "message": message,
                "invalid_fields": [],
            }
            for _ in range(max(count, 1))
        ]
        return {"kind": kind, "count": len(results), "results": results}

    if kind not in SUPPORTED_KINDS:
        return {"kind": kind, "count": 1, "results": [_failed(f"未知的 kind：{kind}", ["kind"])]}

    source_enum = None
    if kind in ("ticket", "release"):
        try:
            source_enum = TicketSource(source) if kind == "ticket" else ReleaseSource(source)
        except ValueError:
            return {
                "kind": kind,
                "count": 1,
                "results": [_failed(f"不合法的 source：{source}", ["source"])],
            }

    if not isinstance(items, list):
        return {"kind": kind, "count": 1, "results": [_failed("items 必須是清單", ["items"])]}

    ctx = get_context()
    results: list[dict[str, Any]] = []
    for item in items:
        try:
            if kind == "ticket":
                results.append(
                    asdict(
                        ingress.handle_manual_ticket(
                            ctx.repo, ctx.rote, ctx.starter, item, source_enum, now=now
                        )
                    )
                )
            elif kind == "release":
                results.append(
                    asdict(
                        ingress.handle_manual_release(
                            ctx.repo, ctx.rote, ctx.starter, item, source_enum, now=now
                        )
                    )
                )
            elif kind == "feedback":
                # 固定保存路徑：不經 Rote、不啟動 Step Functions（設計 §7.1、F06）。
                results.append(asdict(ingress.import_feedback(ctx.repo, ctx.writer, item, now=now)))
            else:
                results.append(asdict(ingress.import_view(ctx.repo, item)))
        except IngressError as exc:
            results.append(_failed(str(exc), list(exc.fields)))
        except (PermanentError, TransientError) as exc:
            results.append(_failed(str(exc), []))
    return {"kind": kind, "count": len(results), "results": results}
```

`ImportResult` 沒有 `execution_arn` 欄位，`asdict` 出來的字典只有四個鍵——這是刻意的，代表這條路徑本來就不會啟動流程。

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：

```bash
uv run pytest tests/unit/test_handler_import_feedback.py tests/unit/test_handler_import.py -v
```

預期：兩個檔案的測試都 PASS（Phase 14 的 `test_feedback_與_view_本階段回未支援` 會失敗——**這是預期的**，請把該測試刪掉，Task 6 的新測試已經取代它）。

- [ ] **步驟 5：commit**

```bash
git add tests/unit/test_handler_import_feedback.py tests/unit/test_handler_import.py \
        src/training_kb/handlers/import_.py
git commit -m "feat(handlers): 匯入 handler 接上回饋與瀏覽紀錄"
```

---

### Task 7：`demo/cli.py` 的 `import` 子命令與匯入檔範例

**目的**：讓維護者在自己的電腦上用一行指令把回饋檔或瀏覽檔匯入，並提供兩份可以直接照抄的範例檔。

**檔案**：
- 新增：`demo/cli.py`
- 新增：`tests/fixtures/import_feedback_a_v1.json`
- 新增：`tests/fixtures/import_views_a_v1.json`
- 測試：`tests/unit/test_demo_cli_import.py`

**介面**：
- 消費：`ingress.import_feedback`、`ingress.import_view`、`config.load_settings(env)`、`repository.build_repository(settings)`、`writing.client.build_writer(settings, trace)`、`writing.client.CallTrace`、`clock.now_utc()`
- 產出：
  - `demo.cli.load_items(path: Path) -> list[dict]`
  - `demo.cli.run_import(repo, writer, kind: str, items: list[dict], *, now) -> list[ImportResult]`
  - `demo.cli.summarize(results: list[ImportResult]) -> dict[str, int]`
  - `demo.cli.build_parser() -> argparse.ArgumentParser`
  - `demo.cli.main(argv: list[str] | None = None) -> int`
  - 註：簡報第 6.11 節寫「`demo/cli.py`：子命令 seed、trigger-ticket、trigger-release、trigger-review、import、metrics」。本階段只做 `import`，其餘五個子命令由 Phase 23 補上；`build_parser()` 已經留好 subparser 的位置。

**匯入檔格式**：一個 JSON 陣列，每個元素就是 `import_feedback` 或 `import_view` 吃的那包 dict。

- [ ] **步驟 1：寫測試**

```python
# tests/unit/test_demo_cli_import.py
"""demo/cli.py 的 import 子命令與匯入檔範例。"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(".").resolve()))

from demo import cli  # noqa: E402
from training_kb.ingress import ImportResult  # noqa: E402

NOW = datetime(2026, 9, 1, 0, 0, 0, tzinfo=UTC)
FEEDBACK_FIXTURE = Path("tests/fixtures/import_feedback_a_v1.json")
VIEWS_FIXTURE = Path("tests/fixtures/import_views_a_v1.json")


def test_回饋範例檔有八筆且可以重算出_2_875():
    items = cli.load_items(FEEDBACK_FIXTURE)
    assert len(items) == 8
    assert {i["tutorial_version"] for i in items} == {"prepare-meeting@v1"}
    assert sum(i["rating"] for i in items) == 23
    assert sum(i["rating"] for i in items) / len(items) == pytest.approx(2.875)
    assert all(i["category"] == "找不到按鈕" for i in items)
    assert len({i["id"] for i in items}) == 8
    assert len({i["user"] for i in items}) == 8


def test_瀏覽範例檔有十筆不同使用者():
    items = cli.load_items(VIEWS_FIXTURE)
    assert len(items) == 10
    assert len({i["user"] for i in items}) == 10
    assert {i["ts"] for i in items} == {"2026-08-02T09:00:00Z"}
    assert {i["tutorial_version"] for i in items} == {"prepare-meeting@v1"}


def test_匯入檔必須是_json_陣列(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"id": "f_1"}), encoding="utf-8")
    with pytest.raises(ValueError):
        cli.load_items(bad)


def test_run_import_逐筆呼叫_import_feedback(monkeypatch):
    calls: list[dict] = []
    monkeypatch.setattr(
        cli.ingress,
        "import_feedback",
        lambda repo, writer, data, *, now: (
            calls.append(data),
            ImportResult(status="saved", object_id=data["id"], message="ok", invalid_fields=[]),
        )[1],
    )

    results = cli.run_import(object(), object(), "feedback", [{"id": "f_1"}, {"id": "f_2"}], now=NOW)

    assert [r.object_id for r in results] == ["f_1", "f_2"]
    assert len(calls) == 2


def test_run_import_逐筆呼叫_import_view(monkeypatch):
    monkeypatch.setattr(
        cli.ingress,
        "import_view",
        lambda repo, data: ImportResult(
            status="saved", object_id="VIEW#x", message="ok", invalid_fields=[]
        ),
    )
    results = cli.run_import(object(), object(), "view", [{"user": "u_01"}], now=NOW)
    assert results[0].status == "saved"


def test_run_import_不認識的_kind_會拋錯():
    with pytest.raises(ValueError):
        cli.run_import(object(), object(), "banana", [], now=NOW)


def test_summarize_統計三種結果():
    results = [
        ImportResult(status="saved", object_id="f_1", message="", invalid_fields=[]),
        ImportResult(status="saved", object_id="f_2", message="", invalid_fields=[]),
        ImportResult(status="duplicate", object_id="f_1", message="", invalid_fields=[]),
        ImportResult(status="rejected", object_id=None, message="", invalid_fields=["rating"]),
    ]
    assert cli.summarize(results) == {"saved": 2, "duplicate": 1, "rejected": 1}


def test_parser_目前只註冊_import_子命令():
    parser = cli.build_parser()
    args = parser.parse_args(["import", "--kind", "feedback", "--file", str(FEEDBACK_FIXTURE)])
    assert args.command == "import"
    assert args.kind == "feedback"
```

- [ ] **步驟 2：跑測試，確認它失敗**

執行：`uv run pytest tests/unit/test_demo_cli_import.py -v`

預期：FAIL，`ModuleNotFoundError: No module named 'demo.cli'`。

- [ ] **步驟 3：寫最少的程式讓測試通過**

先建立兩份範例檔。**`tests/fixtures/import_feedback_a_v1.json`**（設計 §11.2 的八筆；總分 23，平均 2.875，顯示一位小數是 2.9；八筆都有核定問題類別，所以負面回饋是 8）：

```json
[
  {"id": "f_12", "tutorial_version": "prepare-meeting@v1", "rating": 2, "user": "u_01", "category": "找不到按鈕", "comment": "第三步沒有指出按鈕在哪一頁與位置", "ts": "2026-08-02T12:00:00Z"},
  {"id": "f_15", "tutorial_version": "prepare-meeting@v1", "rating": 2, "user": "u_02", "category": "找不到按鈕", "comment": "第三步沒有指出按鈕在哪一頁與位置", "ts": "2026-08-02T12:00:00Z"},
  {"id": "f_19", "tutorial_version": "prepare-meeting@v1", "rating": 3, "user": "u_03", "category": "找不到按鈕", "comment": "第三步沒有指出按鈕在哪一頁與位置", "ts": "2026-08-02T12:00:00Z"},
  {"id": "f_23", "tutorial_version": "prepare-meeting@v1", "rating": 3, "user": "u_04", "category": "找不到按鈕", "comment": "第三步沒有指出按鈕在哪一頁與位置", "ts": "2026-08-02T12:00:00Z"},
  {"id": "f_27", "tutorial_version": "prepare-meeting@v1", "rating": 3, "user": "u_05", "category": "找不到按鈕", "comment": "第三步沒有指出按鈕在哪一頁與位置", "ts": "2026-08-02T12:00:00Z"},
  {"id": "f_31", "tutorial_version": "prepare-meeting@v1", "rating": 3, "user": "u_06", "category": "找不到按鈕", "comment": "第三步沒有指出按鈕在哪一頁與位置", "ts": "2026-08-02T12:00:00Z"},
  {"id": "f_34", "tutorial_version": "prepare-meeting@v1", "rating": 3, "user": "u_07", "category": "找不到按鈕", "comment": "第三步沒有指出按鈕在哪一頁與位置", "ts": "2026-08-02T12:00:00Z"},
  {"id": "f_40", "tutorial_version": "prepare-meeting@v1", "rating": 4, "user": "u_08", "category": "找不到按鈕", "comment": "第三步沒有指出按鈕在哪一頁與位置", "ts": "2026-08-02T12:00:00Z"}
]
```

**`tests/fixtures/import_views_a_v1.json`**（設計 §11.3：A v1 的模擬發布時間是 `2026-08-01T00:00:00Z`，u_01～u_10 各在 `08-02T09:00:00Z` 瀏覽一次）：

```json
[
  {"tutorial_version": "prepare-meeting@v1", "user": "u_01", "ts": "2026-08-02T09:00:00Z"},
  {"tutorial_version": "prepare-meeting@v1", "user": "u_02", "ts": "2026-08-02T09:00:00Z"},
  {"tutorial_version": "prepare-meeting@v1", "user": "u_03", "ts": "2026-08-02T09:00:00Z"},
  {"tutorial_version": "prepare-meeting@v1", "user": "u_04", "ts": "2026-08-02T09:00:00Z"},
  {"tutorial_version": "prepare-meeting@v1", "user": "u_05", "ts": "2026-08-02T09:00:00Z"},
  {"tutorial_version": "prepare-meeting@v1", "user": "u_06", "ts": "2026-08-02T09:00:00Z"},
  {"tutorial_version": "prepare-meeting@v1", "user": "u_07", "ts": "2026-08-02T09:00:00Z"},
  {"tutorial_version": "prepare-meeting@v1", "user": "u_08", "ts": "2026-08-02T09:00:00Z"},
  {"tutorial_version": "prepare-meeting@v1", "user": "u_09", "ts": "2026-08-02T09:00:00Z"},
  {"tutorial_version": "prepare-meeting@v1", "user": "u_10", "ts": "2026-08-02T09:00:00Z"}
]
```

> 這兩份是**明示的合成資料**（F01）。回饋的 `ts` 是「各版模擬發布後第二日」，時刻 `12:00:00Z` 由本計劃選定，排在同日瀏覽 `09:00:00Z` 之後，避免出現「先回饋後瀏覽」這種不合理的順序。Phase 21 會把它們連同 A v2 的十筆一起展開成 `demo/seed/feedback.json` 與 `demo/seed/views.json`，格式完全相同。

再寫 CLI：

```python
# demo/cli.py
"""Demo 命令列工具。

本階段（Phase 15）只做 import 子命令；
seed、trigger-ticket、trigger-release、trigger-review、metrics 由 Phase 23 補上。

用法：
    uv run python -m demo.cli import --kind feedback --file tests/fixtures/import_feedback_a_v1.json
    uv run python -m demo.cli import --kind view --file tests/fixtures/import_views_a_v1.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

from training_kb import ingress
from training_kb.clock import now_utc
from training_kb.config import load_settings
from training_kb.ingress import ImportResult
from training_kb.repository import build_repository
from training_kb.writing.client import CallTrace, build_writer

IMPORT_KINDS = ("feedback", "view")


def load_items(path: Path) -> list[dict]:
    """讀一份匯入檔；必須是 JSON 陣列。"""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"{path} 必須是 JSON 陣列（最外層是 [ ]）")
    for index, item in enumerate(data):
        if not isinstance(item, dict):
            raise ValueError(f"{path} 的第 {index + 1} 筆不是物件")
    return data


def run_import(repo, writer, kind: str, items: list[dict], *, now: datetime) -> list[ImportResult]:
    if kind not in IMPORT_KINDS:
        raise ValueError(f"--kind 只支援 {', '.join(IMPORT_KINDS)}，收到 {kind}")
    results: list[ImportResult] = []
    for item in items:
        if kind == "feedback":
            results.append(ingress.import_feedback(repo, writer, item, now=now))
        else:
            results.append(ingress.import_view(repo, item))
    return results


def summarize(results: list[ImportResult]) -> dict[str, int]:
    counts = {"saved": 0, "duplicate": 0, "rejected": 0}
    for result in results:
        counts[result.status] = counts.get(result.status, 0) + 1
    return counts


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="demo.cli", description="Training KB Demo 工具")
    sub = parser.add_subparsers(dest="command", required=True)

    importer = sub.add_parser("import", help="把回饋或瀏覽紀錄匯入圖譜")
    importer.add_argument("--kind", required=True, choices=list(IMPORT_KINDS))
    importer.add_argument("--file", required=True, help="JSON 陣列檔的路徑")
    # Phase 23 會在這裡加上 seed、trigger-ticket、trigger-release、trigger-review、metrics。
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    items = load_items(Path(args.file))

    settings = load_settings(os.environ)
    repo = build_repository(settings)
    writer = build_writer(settings, CallTrace())

    results = run_import(repo, writer, args.kind, items, now=now_utc())
    for item, result in zip(items, results, strict=True):
        label = item.get("id") or item.get("user", "?")
        print(f"[{result.status}] {label}：{result.message}")

    counts = summarize(results)
    print(
        f"完成：saved={counts['saved']} duplicate={counts['duplicate']} "
        f"rejected={counts['rejected']}"
    )
    return 1 if counts["rejected"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
```

`demo/` 需要有 `__init__.py` 才能用 `python -m demo.cli`：

```bash
touch demo/__init__.py
```

- [ ] **步驟 4：再跑一次測試，確認通過**

執行：

```bash
uv run pytest tests/unit/test_demo_cli_import.py -v
uv run python -m demo.cli import --kind view --file tests/fixtures/import_views_a_v1.json
```

預期：8 個測試綠色；CLI 印出十行 `[saved] u_0X：已保存 ...`，最後一行 `完成：saved=10 duplicate=0 rejected=0`。再跑一次同樣的指令，會變成 `saved=0 duplicate=10 rejected=0`——這就是去重在運作。

> 這個指令會真的寫進 `.env` 指定的 DynamoDB 與 S3。如果你只想在本機驗證，請先確認 `TKB_TABLE_NAME` 指向測試用的表。

- [ ] **步驟 5：commit**

```bash
git add demo/__init__.py demo/cli.py tests/unit/test_demo_cli_import.py \
        tests/fixtures/import_feedback_a_v1.json tests/fixtures/import_views_a_v1.json
git commit -m "feat(demo): 加入回饋與瀏覽紀錄的匯入命令"
```

---

## 7. 完成檢查清單

- [ ] `uv run pytest tests/unit -q` 全綠；`uv run ruff check .` 與 `uv run ruff format --check .` 沒有錯誤。
- [ ] 設計 §15「回饋輸入」整列都有對應測試並通過：
  - [ ] `rating` 為 0 → rejected（`test_rating_不合法時指出欄位`）
  - [ ] `rating` 為 1 → saved（`test_rating_1_到_5_都合法`）
  - [ ] `rating` 為 5 → saved（同上）
  - [ ] `rating` 為 6 → rejected（同第一項）
  - [ ] `rating` 為非整數（`3.5`、`"4"`、`True`）→ rejected（同第一項）
  - [ ] 僅評分（category 與 comment 皆空）→ saved 且不呼叫模型（`test_只有評分的回饋仍然有效`、`test_未勾選且留言為空時類別是_none_且不呼叫模型`）
  - [ ] 勾選優先 → 不呼叫模型（`test_勾選的核定類別優先不呼叫模型`）
  - [ ] 未知類別 → 待分類（`test_勾選的非核定類別直接變待分類且不呼叫模型`、`test_模型回了不在核定表的類別就變待分類`）
  - [ ] 同 ID 重送 → duplicate 且不增加樣本（`test_同一個_id_重送時是_duplicate_且不增加樣本`）
- [ ] 退役教學拒收新回饋（`test_教學已退役時拒絕新回饋`），既有回饋仍查得到。
- [ ] View 的 `ts` 缺值時 rejected（`test_ts_必填不可用匯入時間補`）。
- [ ] 相同三元組的瀏覽重送是 duplicate；不同時間或不同人是兩筆。
- [ ] 手動驗證 `REFERS_TO` 邊真的寫進去了：
  ```bash
  aws dynamodb query --table-name training_kb \
    --key-condition-expression 'PK = :pk' \
    --expression-attribute-values '{":pk":{"S":"FEEDBACK#f_12"}}' \
    --query 'Items[].SK.S'
  ```
  預期看到 `["META", "REFERS_TO#VERSION#prepare-meeting@v1"]`。
- [ ] 手動驗證 by_target 反查得到（Phase 17 會用到）：
  ```bash
  aws dynamodb query --table-name training_kb --index-name by_target \
    --key-condition-expression '#t = :t' \
    --expression-attribute-names '{"#t":"target"}' \
    --expression-attribute-values '{":t":{"S":"VERSION#prepare-meeting@v1"}}' \
    --query 'Items[].PK.S'
  ```
  預期看到八筆 `FEEDBACK#f_*`。
- [ ] **S4 切片**（設計 §16）：View 與 Feedback 可匯入；穩定 user 能對上工單；重送不重複。用兩份範例檔各跑兩次確認。
- [ ] 匯入沒有啟動任何 Step Functions 執行：
  ```bash
  aws stepfunctions list-executions --state-machine-arn $TKB_TICKET_STATE_MACHINE_ARN --max-results 5 --query 'executions[].startDate'
  ```
  匯入前後的清單應該一模一樣。
- [ ] 匯入沒有新增或改動任何 `PROC#` item（`aws dynamodb scan --table-name training_kb --filter-expression 'entity = :e' --expression-attribute-values '{":e":{"S":"PROVEN_WORKFLOW"}}' --query 'Count'` 前後相同）。
- [ ] 範例檔的合成標示還在：文件與 Phase 23 的畫面都要寫「合成資料示範」。

---

## 8. 常見錯誤與排除

**症狀 1：`rating` 傳 `True` 竟然通過驗證。**
原因：Python 的 `bool` 是 `int` 的子類別，`isinstance(True, int)` 會回 `True`，而 `1 <= True <= 5` 也成立。
解法：驗證時先 `isinstance(rating, bool)` 擋掉。`validate_feedback` 已經這樣寫，改動它時不要把這一行拿掉，`test_rating_不合法時指出欄位` 的 `True` 參數就是在守這條。

**症狀 2：同一個人的兩筆回饋只被算成一筆。**
原因：把 `user` 當成去重鍵了。D14 規定「每個新的 `Feedback.id` 計一筆有效回饋，同一提交重送只處理一次」。
解法：去重鍵永遠是 `Feedback.id`（經由 `operation_id_for("feedback", id)`），不是 `user`，也不是 `(user, version)`。

**症狀 3：留言分類每次匯入都重新呼叫一次模型，Bedrock 呼叫數爆增。**
原因：分類寫在錯的位置，或是每次重送都重跑一次。
解法：`import_feedback` 的順序是「先查重 → 再分類 → 再寫入」，duplicate 會在分類之前就 return。`test_同一個_id_重送時是_duplicate_且不增加樣本` 裡的 `assert writer.calls == 0` 就是在守這條。設計 §12.1 規定每次實際送出的請求都要計數，所以不能靠「反正重算一樣」帶過。

**症狀 4：退役的教學還是收得到回饋。**
原因：只檢查了版本存在，沒有再往上查 Tutorial 的 status。
解法：`import_feedback` 要用 `parse_version_id` 取出 slug，再 `repo.get_tutorial(slug)` 檢查 `status`。注意是看**教學**的狀態，不是版本的 `published_at`——未發布的版本照收，退役教學的版本才拒收。

**症狀 5：Phase 19 算出來的重開票率比預期高很多。**
原因：瀏覽紀錄少存了。常見的是匯入檔的 `ts` 被補成匯入時間，導致 `view.ts` 跑到窗口外；或是同一個人同一時間的兩筆被去重掉，但那本來就應該是一筆。
解法：先確認瀏覽的 `ts` 是來源時間而不是匯入時間（`validate_view` 會擋掉缺值）；再用上面「完成檢查清單」的 `scan` 指令數一數該版有幾筆 View、幾個不同 user。設計 §12.1 的分母是「該版窗口內 TUTORIAL_VIEW 的不同 user」，不是總筆數。

**症狀 6：`aws dynamodb query --index-name by_target` 查不到剛剛寫進去的回饋。**
原因：GSI 是最終一致讀，剛寫入的邊可能還沒反映。設計 §10 明寫這件事。
解法：等幾秒再查。**不要**因此把「查不到」當成「沒有」——Phase 16 與 Phase 17 在需要完整集合時會改用基表一致讀核對。這裡只是手動檢查，等一下再查即可。

**症狀 7：`uv run python -m demo.cli` 回 `No module named demo`。**
原因：`demo/__init__.py` 沒建，或不是在 repo 根目錄執行。
解法：`touch demo/__init__.py`，並確認目前工作目錄是 repo 根目錄（`ls pyproject.toml` 看得到檔案）。

**症狀 8：匯入一份 8 筆的回饋檔，得到 8 個 rejected，訊息都是「版本不存在於圖譜」。**
原因：`prepare-meeting@v1` 還沒建立。回饋必須掛在已經存在的版本上。
解法：先讓 Phase 13／14 的流程建出 `prepare-meeting@v1`，或等 Phase 21 用種子載入器一次把 Feature、教學版本、回饋、瀏覽照順序載進去。順序是「先有版本，才有回饋」。

---

## 9. 這階段不做的事

- **不做每日 Review。** 挑弱教學、REFINE、提出候選規則都是 Phase 17 與 Phase 18。這裡只負責把資料存好。
- **不算任何指標。** 平均評分、負面回饋數、重開票率是 Phase 19 的 `analytics.py`。本階段只確認資料齊全到「可以被重算」。
- **不做回饋 widget 的網頁。** 設計 §13 的「產生回饋檔讓維護者匯入」那個畫面是 Phase 22。本階段只定義那個檔案長什麼樣。
- **不做完整的 `demo/cli.py`。** `seed`、`trigger-ticket`、`trigger-release`、`trigger-review`、`metrics` 五個子命令是 Phase 23。
- **不做 A v2 的十筆回饋與瀏覽。** 設計 §11.2、§11.3 的 A v2 資料（f_101～f_110、08-21 的瀏覽）由 Phase 21 連同核定批次一起展開。本階段只提供 A v1 的部分作為格式範例。
- **不擴充核定類別表。** `CONFIG#feedback_categories` 的內容由維護者決定；程式只讀不寫。
- **不把合成資料說成實測。** 兩份範例檔是明示的合成資料（F01），任何展示都要標「合成資料示範」。
- **不讓回饋觸發 PROC 學習。** F06 明寫 Feedback 不納入 PROVEN_WORKFLOW 學習。

---

## 10. 對照：設計章節與 Rule 編號

| Rule 來源檔 | Rule 編號與原文 | 本階段哪個 Task 落實 |
|---|---|---|
| `收集教學回饋.feature` | Rule 1：Feedback 的 tutorial_version 必須存在於圖譜 | Task 4（`test_版本不存在時拒絕並指出欄位`、`test_未發布的版本仍可收回饋`） |
| `收集教學回饋.feature` | Rule 2：已退役教學的既有版本拒絕新回饋 | Task 4（`test_教學已退役時拒絕新回饋`） |
| `收集教學回饋.feature` | Rule 3：Feedback 的 rating 只能為 1 到 5 的整數 | Task 2（`test_rating_1_到_5_都合法`、`test_rating_不合法時指出欄位`） |
| `收集教學回饋.feature` | Rule 4：使用者勾選的 Feedback Category 優先於模型分類 | Task 4（`test_勾選的核定類別優先不呼叫模型`） |
| `收集教學回饋.feature` | Rule 5：Feedback Category 必須屬於核定類別表或待分類 | Task 1（`resolve_category`）、Task 4（`test_模型回了不在核定表的類別就變待分類`） |
| `收集教學回饋.feature` | Rule 6：需要分類的自由留言在接入時計算一次 Feedback Category | Task 4（`test_未勾選且留言非空時呼叫一次模型`、`test_未勾選且留言為空時類別是_none_且不呼叫模型`） |
| `收集教學回饋.feature` | Rule 7：回饋關聯到提交時指定的 TutorialVersion | Task 4（寫 `REFERS_TO` 邊；`tutorial_version` 保存裸 version_id，不改綁 current_version） |
| `收集教學回饋.feature` | Rule 8：收到單筆低分 Feedback 時不立即修改 Tutorial | Task 4（`import_feedback` 只寫資料，不呼叫 `content.*`、不啟動流程）；第 9 節也明列 |
| `收集教學回饋.feature` | Rule 9：Feedback 接入時必須提供穩定使用者 ID | Task 2（`test_缺少_user_時操作失敗`） |
| `收集教學回饋.feature` | Rule 10：同一使用者對同一版本的每次新提交都計一筆 | Task 4（`test_同一人不同_id_的兩筆都算樣本`、`test_同一個_id_重送時是_duplicate_且不增加樣本`） |
| `接入來源事件.feature` | Rule 21：正規化物件必須具有 schema 的必填欄位 | Task 2、Task 3（缺欄位一律 `IngressError` 並列出欄位） |
| `接入來源事件.feature` | Rule 24：正規化物件的 id 直接使用已全域唯一的上游識別碼 | Task 2（`test_id_沒有_f_前綴時操作失敗`） |
| `接入來源事件.feature` | Rule 25：正規化物件的枚舉欄位必須使用合法值 | Task 1（類別收斂到核定表或「待分類」） |
| `接入來源事件.feature` | Rule 28：正規化成功的 Feedback 寫入 FEEDBACK item | Task 4（`test_成功寫入_feedback_與_refers_to_邊`） |
| `接入來源事件.feature` | Rule 29：單筆 Feedback 接入不立即觸發教學改版 | Task 4、Task 6（完成檢查清單有「匯入沒有啟動任何 Step Functions 執行」） |
| `接入來源事件.feature` | Rule 30：同一正規化事件重送時只處理一次 | Task 4、Task 5（duplicate 分支） |
| `檢視學習指標.feature` | Rule 4：同題重開票率的分母取自教學瀏覽事件 | Task 5（本階段提供分母資料；實際計算在 Phase 19） |
| `檢視學習指標.feature` | Rule 5：看過教學又開票的同一人比對穩定使用者 ID | Task 3、Task 5（`user` 必填且與 `Ticket.author` 同一組 ID） |

資料決策對照：

| 編號 | 內容 | 本階段怎麼落實 |
|---|---|---|
| D11 | 不允許沒有穩定使用者識別碼 | `validate_feedback` 的 `user` 必填 |
| D12 | 只有評分的回饋有效，不送模型分類 | `import_feedback` 只在「未勾選 + 留言非空」時呼叫模型 |
| D13 | 可擴充的核定類別表，未知值進待分類 | `CONFIG#feedback_categories` 與 `resolve_category` |
| D14 | 每次新的提交 ID 都算一筆，只排除同一提交的重送 | 去重鍵是 `Feedback.id` |
| D23 | 瀏覽、回饋與 Ticket 共用同一個穩定使用者 ID | `user` 與 `Ticket.author` 同一組字串，不做身分對照表 |
| D24 | MVP 新增瀏覽事件，至少記錄版本、使用者與瀏覽時間 | `validate_view` 的三個必填欄位 |
| F39 | 退役教學拒絕新回饋，保留既有回饋 | `import_feedback` 的 retired 分支 |
| F51 | 立即拒絕並指出不合法欄位，不建立 FEEDBACK 或成功回執 | `ImportResult(status="rejected", invalid_fields=[...])` |

待確認事項：

| 編號 | 本階段怎麼處理 |
|---|---|
| O2（操作紀錄與接受順序） | **本計劃選擇**：以 `OPS#import:feedback:<id>` 條件寫入去重，再確認 `FEEDBACK#<id>` 是否真的存在，避免「紀錄寫了但資料沒寫完」被誤判成 duplicate。 |
| O4（時間與窗口） | 本階段只保存時間，不做窗口計算。回饋缺 `ts` 用匯入時間並在訊息註明；瀏覽的 `ts` 必填。窗口 `[p, p+14 天)` 的使用在 Phase 19。 |
| O7（核定種子） | 兩份範例檔是設計 §11.2、§11.3 配方的一部分，**尚未核定**。Phase 21 完成全部展開並以程式重算驗證後才算核定。 |

---

## 11. 參考來源

設計文件章節（`docs/design/training-kb.md`）：

- §7.1 接入路徑（Feedback／View 的必填欄位、`ts` 的處理、不啟動 Step Functions）
- §7.6 共用寫作介面（分類留言：不自動擴充類別表、已勾選時不覆蓋）
- §8.4 退役後的畫面與資料（退役版本拒絕新回饋，原回饋仍可查閱）
- §9.1 鍵與原生型別（`VIEW#<事件摘要>` 的 SHA-256 選擇）
- §9.2 關係邊（`FEEDBACK#f_12 -> REFERS_TO#VERSION#...`；View 不新增 VIEWED 關係）
- §11.2 可重算的評分與負面回饋（八筆 A v1 的完整資料與 2.875／2.9）
- §11.3 可重算的瀏覽、重開票筆數與比例（十筆瀏覽與模擬發布時間）
- §12.1 指標公式（負面回饋數、重開票率的分母定義）
- §13 Demo UI（widget 先產生回饋檔，維護者再匯入）
- §14.1 各層如何結束（欄位非法或版本不存在時指出欄位；重送只處理一次）
- §15 測試與驗收設計（「回饋輸入」整列）
- §16 交付切片 S4
- §18 待確認事項 O2、O4、O7
- §19.1 資料決策 D11、D12、D13、D14、D23、D24
- §19.2 功能決策 F01、F06、F39、F51

規格檔：

- `docs/spec/features/收集教學回饋.feature`（Rule 1–10 全部）
- `docs/spec/features/接入來源事件.feature`（Rule 21、24、25、28、29、30）
- `docs/spec/features/檢視學習指標.feature`（Rule 4、5）
- `docs/spec/erm.dbml`（FEEDBACK 與 TUTORIAL_VIEW 的欄位投影）

其他：

- 本階段沒有用到新的 AWS API；DynamoDB 的分頁與一致性讀取沿用 Phase 03、Phase 09 已查證的用法：<https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/HowItWorks.ReadConsistency.html>
- pydantic v2 的 `model_copy(update=...)`：<https://docs.pydantic.dev/latest/concepts/serialization/#model_copy>
- Python `argparse` 的 subparsers：<https://docs.python.org/3/library/argparse.html#sub-commands>
