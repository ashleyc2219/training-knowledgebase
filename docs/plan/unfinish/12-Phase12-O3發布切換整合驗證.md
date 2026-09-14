# Phase 12：O3 發布切換整合驗證實作計畫

> **給實作者：** 依 checkbox 逐步執行；每個 Task 先建立失敗測試，再寫最小實作。執行時使用 `superpowers:executing-plans` 或同等逐項流程。

**目標：** 用最小 spike 把「跨 DynamoDB 與 S3 的發布切換」所有失敗切點跑過一次，記錄每個切點對外看得到什麼，產出可追溯的 O3 報告。

**架構：** spike 程式住在 `infra/scripts/o3_report.py`（部署前腳本，不進 Lambda runtime），只建立兩篇假教學的最小資產，用兩種提交順序（先交易後寫 site、先寫 site 後交易）逐一注入中斷，再用一致讀取加 S3 GET 觀察「公開站顯示的版本」與「DynamoDB 的 current_version」。它不是 `Publisher`，只驗證協定。

**技術：** Python 3.12、pytest、boto3 DynamoDB／S3 client、**專用於本次 spike 的隔離測試表與測試 bucket**（不是正式內容 bucket）。

## 全域限制

- 唯一主來源是 [Training KB 設計 §8.2、§8.3、§9.3、§13、§17.1、§18 O3](../../design/training-kb.md)。
- 前置為 [Phase 11：O2 接受順序與重啟整合驗證](./11-Phase11-O2接受順序與重啟整合驗證.md)。Phase 11 未 PASS 時停止。
  - **執行紀錄（2026-09-14）：** 本次 spike 在 Phase 11 尚未執行（`docs/plan/report/` 沒有 o2 報告）時就先跑，是排程上的刻意偏離。理由：O2 驗的是操作紀錄與接受順序，O3 驗的是跨 DynamoDB／S3 的提交切點，本 spike 的五個切點不依賴任何 operation 紀錄或 lease，結論不受 O2 影響；而且本次結論是 **FAIL**，不存在「因為跳過前置而誤判成通過」的風險。Phase 11 完成後不需要重跑本 spike。
- 下一階段是 [Phase 13：O6 來源 ID 與穩定使用者契約](./13-Phase13-O6來源ID與穩定使用者契約.md)。
- 本階段不實作 `Publisher`、`SiteRenderer`、教學內容、diff 或退役；那些在 Phase 22–26 與 57。
- **不得新增 CloudFront、公開讀取 API、第二個 bucket 對外入口或任何託管層**；也不得放寬 F49「整次失敗不發布新版」。
- **設計目前沒有宣稱已有可行解。** 本 Phase 允許的結論只有 PASS 或 FAIL。FAIL 時保留報告與重現指令，並阻擋公開路徑：[Phase 24](./24-Phase24-單篇教學發布提交.md)、[Phase 25](./25-Phase25-多篇教學整批發布.md)、[Phase 41](./41-Phase41-Ticket-Analysis雲端流程驗收.md)、[Phase 48](./48-Phase48-Feedback-Review排程流程.md)、[Phase 52](./52-Phase52-Release-RETIRE與流程驗收.md)、[Phase 57](./57-Phase57-S3靜態教學站與回饋下載.md) 都不得開始。[Phase 59](./59-Phase59-失敗復原與重送驗收.md) 是 [00A](./00A-共用契約與名詞.md) 第 4.2 節列的 O3 追驗 Phase，它仍可執行，但只能把切點 4 記成「補償有效」並標為 O3 缺口，不得寫成「發布故障驗收通過」。
- 以下程式檔均是實作時預計建立或修改；本計畫本身不代表它們已存在。

---

## 1. 你在整體流程的位置

```text
Phase 11 O2 PASS
      |
      v
[你在這裡：O3 切點矩陣 spike]
      |
  +---+-----------------------------+
  |                                 |
所有切點皆非 partial            任一切點 partial 可見
  |                                 |
  v                                 v
PASS 報告 -> Phase 24/25 可開始   FAIL 報告 -> 阻擋公開路徑
Phase 41/48/52/57 才有前置        保留限制，不加託管層、不改 F49
```

## 2. 完成後看得到什麼

具體輸入：兩篇假教學 `spike-a`、`spike-b` 各自從 v1 切到 v2；在 `a3_after_first_site_before_second` 切點中斷後立刻觀察：

```text
slug      site 顯示版本   DynamoDB current_version   published_at
--------+---------------+--------------------------+-------------
spike-a | v2            | spike-a@v2               | 有值
spike-b | v1            | spike-b@v2               | 有值
```

`spike-b` 指標已切到 v2 但公開頁仍是 v1，且 A 新 B 舊。這就是 partial，`CutPointResult.partial_visible == True`，整體判定 FAIL；報告要寫下這一列，不能只寫「待處理」。

## 3. 名詞小抄

| 名詞 | 白話意思 |
|---|---|
| O3 | 設計 §18「待確認事項」的第三項：S3 公開切換與發布提交。沒有真實證據就不算通過。 |
| spike | 一次性的最小驗證程式，只為了回答一個問題；跑完留報告，不變成產品程式。 |
| 提交切點 | 發布過程中可能斷掉的位置，例如「交易做完但 site 還沒寫」。 |
| partial | 對外同時看得到一部分新、一部分舊；F49 禁止這種狀態。 |
| 公開站 | S3 `site/` 前綴下任何人可讀的 HTML；`tutorials/` 是私有產物，不算公開。 |
| 交易 | DynamoDB `TransactWriteItems`，只涵蓋 DynamoDB，不包含 S3。 |
| 曝光 | 內容已被讀出去；事後刪除或改回舊版都收不回已經讀到的東西。 |
| 決策出口 | gate FAIL 時可以往哪些方向走的候選清單；候選不等於已核定。 |
| F36／F37／F49 | 設計 §19.2 的功能決策編號：未完成版本不可公開、publish 成功才切 `current_version`、整次失敗不發布新版。 |

## 4. 預計檔案

| 動作 | 路徑 | 責任 |
|---|---|---|
| 新增 | `infra/scripts/o3_report.py` | 最小雙儲存提交協定、五個切點注入、觀察函式與 O3 報告輸出。 |
| 測試 | `tests/unit/test_o3_observation.py` | `is_partial` 與 `render_o3_report` 的純函式判定，不連 AWS。 |
| 測試 | `tests/integration/test_o3_cut_points.py` | 對隔離的測試表與測試 bucket 跑完五個切點；全部標 `@pytest.mark.aws`。 |
| 新增 | `docs/plan/report/o3-<run-id>.md` | O3 報告；原始觀察值另存私有 `operations/o3/<run_id>.json`。 |

原始觀察值寫進**隔離測試 bucket** 的 `operations/o3/<run_id>.json`（00A 第 3.4 節的 gate 證據位置），不寫正式內容 bucket。隔離 bucket 跑完一定刪掉，所以同一份 JSON 逐字抄進報告的「原始觀察值」一節；報告本身才是跑完之後還留得住的證據。

不另開 `tests/spikes/` 目錄：[00A](./00A-共用契約與名詞.md) 第 3.2 節的路徑總表只有 `src/`、`infra/`、`demo/`、`tests/unit/`、`tests/integration/`，表上沒有的路徑不自己發明。注入點只活在這支腳本內；正式的 `TKB_FAULT` 切點模組屬於 [Phase 59](./59-Phase59-失敗復原與重送驗收.md)，本 Phase 不先建立。

## 5. 固定介面

### Consumes

```text
Repository.put_object(key, body, content_type, *, if_none_match) -> None   # Phase 07
Repository.get_object(key) -> bytes | None                                 # Phase 07
Repository.object_exists(key) -> bool                                      # Phase 07
Repository.put_meta(entity, *, create_only=True) -> None                    # Phase 06
Repository.get_meta(pk, model, *, consistent=True) -> T | None              # Phase 06
Tutorial / TutorialVersion                                                 # Phase 04
tutorial_pk(slug) -> str / version_pk(version_id) -> str / META            # Phase 05
to_iso(dt) -> str / ObjectAlreadyExists / PermanentError                    # Phase 02、07
DynamoDB TransactWriteItems（最多 100 個動作、總量 4 MB、同一 item 不可出現兩次）
S3 PutObject + If-None-Match: *（已存在回 412 Precondition Failed）
```

`Repository.transact_write` 是 [Phase 24](./24-Phase24-單篇教學發布提交.md) 才產出的方法，此時還不存在；spike 直接用 boto3 client 的 `transact_write_items`，並在報告註明它驗的是**協定**，不是 `Publisher` 的實作。

### Produces

```python
# infra/scripts/o3_report.py（本 Phase 全部的產出都在這一支）
O3CutPoint = Literal[
    "a1_before_transact", "a2_after_transact_before_site",
    "a3_after_first_site_before_second", "b1_after_site_before_transact",
    "c1_after_delete_site",
]

@dataclass(frozen=True)
class PublicView:
    slug: str
    site_version: str | None
    current_version: str | None
    published_at: str | None

@dataclass(frozen=True)
class CutPointResult:
    cut_point: O3CutPoint
    views: tuple[PublicView, ...]
    exposed_bodies: tuple[str, ...]
    partial_visible: bool
    note: str

def observe(slugs: Sequence[str], *, table: str, bucket: str) -> tuple[PublicView, ...]: ...
def is_partial(views: Sequence[PublicView], *, expected: str) -> bool: ...
def run_cut_point(point: O3CutPoint, *, table: str, bucket: str) -> CutPointResult: ...
def o3_verdict(results: Sequence[CutPointResult]) -> Literal["PASS", "FAIL"]: ...
def render_o3_report(
    results: Sequence[CutPointResult], *, run_id: str,
    table: str, bucket: str, region: str,
) -> str: ...

# 以下是這支腳本自己的命令列與隔離資源管理，00A 第 6.4 節的 gate 工具清單沒有列，
# 因為別的 Phase 不消費它們；名稱不與 00A 衝突，只是補上「怎麼把 spike 跑起來」。
def build_parser() -> argparse.ArgumentParser: ...
def main(argv: Sequence[str] | None = None) -> int: ...      # PASS 回 0、FAIL 回 2
def create_spike_resources(run_id: str) -> tuple[str, str]: ...
def delete_spike_resources(table: str, bucket: str) -> int: ...
```

`render_o3_report` 多收 `table`／`bucket`／`region`，因為報告必須寫出它是對哪張表、哪個 bucket、哪個 Region 跑的；[00A 第 6.4 節](00A-共用契約與名詞.md) 的 gate 工具清單已逐字收錄這個簽名，兩邊必須一致。`expected` 是本次切點應該看到的世代標記：`"v1"` 代表全舊、`"v2"` 代表全新。spike 只用這個標記字串，不引入新的業務欄位。
逐切點的值以「DynamoDB 交易是否已提交」為界——交易是這次發布唯一的原子提交點，交易前該看到全舊、交易後該看到全新：`a1`／`b1` 是 `"v1"`，`a2`／`a3`／`c1` 是 `"v2"`（實作在 `EXPECTED_GENERATION`）。五個切點的判定不因這個選擇而改變：`a2`／`a3`／`b1`／`c1` 都先在「同一篇的公開頁與指標不同世代」那一層就判成 partial。

## 6. 設計細節

兩種提交順序都要跑，因為兩種都有切點；不能只驗證比較順眼的那一種。

```text
協定 A（設計 §8.3 建議）            協定 B（先曝光）
staged 私有產物                      staged 私有產物
      |                                   |
   [a1] 中斷 -> 全舊，OK                  |
      v                                   v
TransactWriteItems                   寫 site/tutorials/<slug>/
 published_at + current_version            |
      |                              [b1] 中斷 -> 公開頁已新、指標仍舊
   [a2] 中斷 -> 指標已新、公開頁仍舊        v
      v                              TransactWriteItems
寫 site/tutorials/spike-a/                  |
   [a3] 中斷 -> A 新 B 舊（多篇 partial）    v
      v                                  完成
寫 site/tutorials/spike-b/
      |
   [c1] 事後刪除 spike-a 的公開頁 -> 已讀出的內容收不回
```

公開 key 佈局照 [00A](./00A-共用契約與名詞.md) 第 3.4 節：版本頁 `site/tutorials/<slug>/v<n>.html`、教學索引 `site/tutorials/<slug>/index.html`、站台索引 `site/index.html`。spike 只碰 `spike-a`、`spike-b` 兩個 slug 的 key，跑完刪掉。

五個切點的可觀察結果與判定依據：

| 切點 | DynamoDB | site | 是否 partial | 依據 |
|---|---|---|---|---|
| `a1_before_transact` | 全舊 | 全舊 | 否 | 私有 staging 不對外，符合 F36。 |
| `a2_after_transact_before_site` | 全新 | 全舊 | 是 | 違反 F37「publish 成功才切指標」。 |
| `a3_after_first_site_before_second` | 全新 | A 新 B 舊 | 是 | 違反 F49，且不可宣稱整次沒有發布。 |
| `b1_after_site_before_transact` | 全舊 | 全新 | 是 | 未發布內容已公開，違反 F36。 |
| `c1_after_delete_site` | 全新 | 回復全舊 | 是 | `exposed_bodies` 仍留有新內容，刪除不消除曝光。 |

DynamoDB 交易的硬限制會直接放大 `a3`：一次 `TransactWriteItems` 最多 100 個動作、總量 4 MB，且同一個 item 不能在同一筆交易出現兩次。本案每篇發布固定動 `TUTORIAL#<slug>` 與 `VERSION#<slug>@v<n>` 兩個 item（兩個 action），所以單次交易最多 `100 / 2 = 50` 篇——這就是 [Phase 25](./25-Phase25-多篇教學整批發布.md) 的 `MAX_BATCH_VERSIONS = 50`，兩份文件的換算必須一致。超過就必須拆成多筆交易，中途失敗的 partial 視窗再增加一層；拆交易等於放棄全有或全無，因此 Phase 25 直接丟 `PublishError` 而不是拆。S3 那側沒有等價機制，`PutObject` 只有單物件層級的條件寫入（`If-None-Match: *` 已存在時回 `412 Precondition Failed`，併發刪除時可能回 `409 Conflict`），不存在跨物件原子切換。

因此本 Phase 很可能得到 FAIL。FAIL 時必須寫下決策出口，而且每個出口都仍未核定、仍要重跑同一組切點：

- **出口 1：縮限公開範圍（未核定）。** 只允許單篇發布，明示公開頁可能短暫落後於指標。這不解決 `a2`，只縮小影響面；多篇路徑維持阻擋。
- **出口 2：公開世代改由單一 S3 物件決定（未核定）。** 讓 `site/` 的目前版本由一個 manifest 物件切換，多篇提交變成換一個 key。代價是靜態站要靠瀏覽器端自己讀 manifest 才知道該顯示哪一版，而 DynamoDB 與 S3 仍是兩個 store，`a2`／`b1` 切點照舊存在。
- **出口 3：接受 FAIL（未核定）。** 公開站停用，Demo 只展示私有預覽與報告。

三個出口都不新增服務與公開讀取 API，也不改寫 F49；選哪一個由維護者決定，本計畫不宣稱任一個已可行，選定後仍要重跑同一組五個切點。

## 7. TDD Tasks

### Task 1：固定「對外可見狀態」的判定

- [x] **Step 1：建立失敗測試**

```python
def test_is_partial_detects_pointer_and_cross_slug_mismatch() -> None:
    stamp = "2026-09-13T00:00:00Z"
    both_old = [PublicView("spike-a", "v1", "v1", None), PublicView("spike-b", "v1", "v1", None)]
    pointer_ahead = [PublicView("spike-a", "v1", "v2", stamp)]
    half_new = [PublicView("spike-a", "v2", "v2", stamp), PublicView("spike-b", "v1", "v1", None)]
    assert is_partial(both_old, expected="v1") is False
    assert is_partial(pointer_ahead, expected="v2") is True
    assert is_partial(half_new, expected="v2") is True
```

- [x] **Step 2：執行並確認紅燈**

```bash
uv run pytest tests/unit/test_o3_observation.py::test_is_partial_detects_pointer_and_cross_slug_mismatch -q
```

預期：FAIL，訊號包含 `cannot import name 'is_partial'`。
**實測**：這是第一個 Task，`o3_report.py` 還不存在，所以紅燈訊號是同一層的 `ModuleNotFoundError: No module named 'o3_report'`；後面兩個 Task 才是 `cannot import name ...`。

- [x] **Step 3：建立最小實作**

```python
def is_partial(views: Sequence[PublicView], *, expected: str) -> bool:
    generations = set()
    for view in views:
        if view.site_version != view.current_version:
            return True
        generations.add(view.site_version)
    return generations != {expected}
```

- [x] **Step 4：補 `observe` 與邊界後跑綠燈**

`observe` 讀 DynamoDB 時固定 `consistent=True`（GSI 是最終一致，這裡只走基表），讀 S3 時 GET `site/tutorials/<slug>/index.html` 並抓出它指到的版本標記；缺物件回 `None`。補測：缺 site 物件、缺 VERSION item、三篇中只有一篇落後。

```bash
uv run pytest tests/unit/test_o3_observation.py -q
git add infra/scripts/o3_report.py tests/unit/test_o3_observation.py
git commit -m "feat(spike): 判定發布切點的對外可見狀態"
```

### Task 2：跑完五個切點並保留曝光紀錄

- [x] **Step 1：建立失敗測試**

```python
import pytest

CUT_POINTS = (
    "a1_before_transact",
    "a2_after_transact_before_site",
    "a3_after_first_site_before_second",
    "b1_after_site_before_transact",
    "c1_after_delete_site",
)

@pytest.mark.aws
def test_every_cut_point_is_observed(live_table, live_bucket) -> None:
    results = [run_cut_point(point, table=live_table, bucket=live_bucket) for point in CUT_POINTS]
    assert [row.cut_point for row in results] == list(CUT_POINTS)
    rollback = results[-1]
    assert rollback.exposed_bodies != ()
```

最後兩行是「事後刪除不消除曝光」的直接斷言：回復舊版之後，視窗內讀到的新內容仍留在 `exposed_bodies`。`live_table`／`live_bucket` 兩個 fixture 從 `TKB_TABLE_NAME`、`TKB_CONTENT_BUCKET` 讀**隔離的測試資源**，沒設就 `pytest.skip`；`@pytest.mark.aws` 是 00A 第 3.1 節規定的真實 AWS 標籤，marker 在 [Phase 01](./01-Phase01-專案骨架與離線品質門檻.md) 的 `pyproject.toml` 註冊，而且 Phase 01 的 `tests/conftest.py` 在沒設 `TKB_RUN_AWS_INTEGRATION=1` 時會自動跳過它們（裁決 D-64），所以平常不必自己加 `-m` 條件。

- [x] **Step 2：執行並確認紅燈**

```bash
TKB_RUN_AWS_INTEGRATION=1 uv run pytest tests/integration/test_o3_cut_points.py::test_every_cut_point_is_observed -q -m aws
```

預期：FAIL，訊號包含 `cannot import name 'run_cut_point'`。

- [x] **Step 3：實作切點注入**

每個切點固定四步：建立全舊初始狀態 → 依協定執行到注入點 → 立刻 `observe` 並做一次 S3 GET 存進 `exposed_bodies` → 回復乾淨狀態給下一個切點。注入用 spike 內的旗標，不用 `sleep`。

- [x] **Step 4：對真實表與 bucket 執行並提交**

```bash
TKB_RUN_AWS_INTEGRATION=1 uv run pytest tests/integration/test_o3_cut_points.py -q -m aws
git add infra/scripts/o3_report.py tests/integration/test_o3_cut_points.py
git commit -m "test(spike): 觀察O3五個提交切點"
```

預期：五列都有實際 DynamoDB 與 S3 讀寫。bucket 只碰 `spike-a`、`spike-b` 兩個 slug 的 key，測試結束刪掉；正式教學的 `site/` 內容不在本 Phase 建立，也不對正式內容 bucket 提交。

### Task 3：產出 O3 報告與 FAIL 出口

- [x] **Step 1：建立失敗測試**

```python
def test_report_lists_every_cut_point_and_blocks_on_partial(sample_results) -> None:
    report = render_o3_report(
        sample_results, run_id="spike-1",
        table="training_kb_spike", bucket="training-kb-spike", region="ap-northeast-1",
    )
    assert o3_verdict(sample_results) == "FAIL"
    assert "a3_after_first_site_before_second" in report
    assert "阻擋公開路徑" in report
    assert "CloudFront" not in report
```

`sample_results` 是寫死在測試裡的 `CutPointResult`，所以這條是純函式測試，放 `tests/unit/test_o3_observation.py`，不需要 AWS。

- [x] **Step 2：執行並確認紅燈**

```bash
uv run pytest tests/unit/test_o3_observation.py::test_report_lists_every_cut_point_and_blocks_on_partial -q
```

預期：FAIL，訊號包含 `cannot import name 'render_o3_report'`。

- [x] **Step 3：建立最小實作**

```python
HEADER = "| 切點 | DynamoDB | site | partial | 曝光筆數 | 說明 |\n|---|---|---|---|---|---|\n"


def o3_verdict(results: Sequence[CutPointResult]) -> Literal["PASS", "FAIL"]:
    return "FAIL" if any(row.partial_visible for row in results) else "PASS"


def render_o3_report(
    results: Sequence[CutPointResult], *, run_id: str,
    table: str, bucket: str, region: str,
) -> str:
    rows = "".join(
        "| {0.cut_point} | {1} | {2} | {0.partial_visible} |"
        " {3} | {0.note} |\n".format(
            row,
            ",".join(str(view.current_version) for view in row.views),
            ",".join(str(view.site_version) for view in row.views),
            len(row.exposed_bodies),
        )
        for row in results
    )
    verdict = o3_verdict(results)
    tail = "整體判定：FAIL，阻擋公開路徑。" if verdict == "FAIL" else "整體判定：PASS。"
    head = f"# O3 報告 {run_id}\n\nRegion：{region}｜表：{table}｜bucket：{bucket}｜run id：{run_id}\n\n"
    return f"{head}{HEADER}{rows}\n{tail}\n"
```

- [x] **Step 4：寫下決策出口並提交**

報告末段固定列出三個出口與「尚未核定」字樣；不得寫入未授權服務名稱，也不得建議放寬 F49。

```bash
uv run pytest tests/unit/test_o3_observation.py -q
git add infra/scripts/o3_report.py tests/unit/test_o3_observation.py docs/plan/report
git commit -m "test(spike): 產出O3報告與決策出口"
```

## 8. 驗收矩陣

| 路徑 | 輸入 | 預期資料結果 |
|---|---|---|
| Happy | `a1_before_transact` | 兩篇都是 v1，`partial_visible=False`。 |
| Failure | `a2_after_transact_before_site` | `current_version=v2` 但 `site_version=v1`，判定 partial。 |
| Failure | `a3_after_first_site_before_second` | A 新 B 舊，判定 partial，整體 FAIL。 |
| Failure | `b1_after_site_before_transact` | 未發布內容已公開，判定 partial。 |
| Boundary | `c1_after_delete_site` | site 回舊版，`exposed_bodies` 仍非空。 |
| Boundary | 同 key 以 `If-None-Match: *` 重寫 | S3 回 `412 Precondition Failed`，`Repository.put_object` 轉成 `ObjectAlreadyExists`，不盲目覆蓋。 |

人工驗收：打開 `docs/plan/report/o3-<run-id>.md`，對每個切點用 `aws s3 cp` 與 `aws dynamodb get-item` 各重看一次，確認報告的兩欄和手動讀到的一致。同時把 `site/tutorials/spike-a/index.html` 與 `site/tutorials/spike-b/index.html` 兩個檔讀出來對照，確認 partial 是肉眼看得到的，不是只在測試裡。

**這兩個檔用 `aws s3 cp s3://<bucket>/<key> -` 讀原文，不是用瀏覽器開公開 URL。** spike 的隔離 bucket 刻意維持 Block Public Access 全開、不放公開 policy（本 Phase 不得新增公開讀取入口），所以它根本沒有可在瀏覽器開啟的公開 URL；要看渲染結果就把檔案下載到本機再開。用「私有 bucket 內 `site/` 前綴的 key 存在與否」觀察公開切換，和真的開放公開讀取在切點判定上完全等價：partial 與否只看兩個 store 的內容差異。

## 9. 常見錯誤與停止條件

| 症狀 | 原因 | 修正／停止 |
|---|---|---|
| 只驗證協定 A | 以為先寫 DB 就安全 | 兩種順序都跑；漏跑等同未驗證。 |
| 把回復當成沒發生 | 誤以為刪掉物件就收回內容 | 保留 `exposed_bodies`；`c1` 必須判 partial。 |
| 用未連結的 URL 充當私有 | 混淆「沒有入口」與「不可公開」 | 未發布產物只能在 `tutorials/` 私有前綴。 |
| FAIL 後改用 CloudFront | 靜默擴大架構 | 停止；只能在三個出口中選，並由維護者核定。 |
| 多篇改成逐篇成功 | 為求綠燈放寬 F49 | 停止 Phase 25；F49 不可改寫。 |
| 報告只寫「待處理」 | 沒有記錄觀察值 | 補齊六欄與曝光筆數；沒有觀察值等同未驗證。 |

## 10. 來源與 Rule 對照

- [發布教學版本.feature](../../spec/features/發布教學版本.feature)
  - Rule 4：「Tutorial 的 current_version 指向目前教學版本」→ **相關（primary 在 [Phase 24](./24-Phase24-單篇教學發布提交.md)）**。`a2` 切點在整合情境觀察：指標已切但公開頁仍舊即為 partial。
  - Rule 5：「已上架的版本具有 published_at」→ **相關（primary 在 [Phase 24](./24-Phase24-單篇教學發布提交.md)）**。`b1` 切點觀察 `published_at` 仍為空時公開頁不得是新版。
- [建立教學版本.feature](../../spec/features/建立教學版本.feature)
  - Rule 5：「每個版本的完整內容儲存在 tutorials/&lt;slug&gt;/v&lt;n&gt;.md」→ **相關（primary 在 [Phase 22](./22-Phase22-Markdown與Diff私有產物.md)）**。`a1` 切點觀察私有產物存在但不對外。
- 設計 §8.3、§13、§18 O3：跨 S3 與 DynamoDB 沒有共同交易；多篇提交途中失敗一併納入 O3，不得默默改成允許部分成功；S3 website endpoint 只有 HTTP，公開區只放可公開教學。
- [S3 條件寫入](https://docs.aws.amazon.com/AmazonS3/latest/userguide/conditional-writes.html)：`If-None-Match: *` 已存在回 `412 Precondition Failed`，併發刪除可能回 `409 Conflict`。
- [DynamoDB 交易](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/transaction-apis.html)：最多 100 個動作、4 MB，同一 item 不可重複出現，且只涵蓋 DynamoDB。

## 11. 完成清單

- [x] 五個切點都標 `@pytest.mark.aws`、有實際 AWS 讀寫與觀察值，沒有以 mock 代替。
- [x] 兩種提交順序都跑過。
- [x] `c1` 保留曝光紀錄，證明事後刪除不消除曝光。
- [x] 交易的 100 動作與 4 MB 限制換算成「每篇 2 個 action、單批最多 50 篇」，與 Phase 25 的 `MAX_BATCH_VERSIONS` 一致，並寫進報告。
- [x] 報告六欄齊全，含 Region、表名、bucket 與 run id。
- [x] FAIL 時列出三個決策出口，且都標示尚未核定。
- [x] 報告與程式都沒有新增 CloudFront、公開讀取 API 或放寬 F49。
- [x] FAIL 時 Phase 24、25、41、48、52、57 標為阻擋，Phase 59 的切點 4 標為 O3 缺口，未宣稱 O3 已通過。
