# Phase 24：單篇教學發布提交實作計畫

> **給實作者：** 依 checkbox 逐步執行；每個 Task 先建立失敗測試，再寫最小實作。執行時使用 `superpowers:executing-plans` 或同等逐項流程。

**目標：** 把一個已完整寫好但尚未發布的版本，用 `prepare / inspect / commit` 三段式提交上架，並以**最小**頁面 renderer 產生公開 HTML。

**架構：** `Publisher` 是唯一能切 `published_at` 與 `current_version` 的地方；`SiteRenderer` 只把已保存內容轉成 HTML。頁面先寫私有 staging，DynamoDB 一筆交易同時切兩個欄位，成功之後才把同一份 bytes 複製到公開 `site/`。程式決定順序與條件，AWS 只負責原子性與條件檢查。

**技術：** Python 3.12、Pydantic v2、pytest、boto3 DynamoDB `transact_write_items`、S3、標準函式庫 `html.escape`。

## 全域限制

- 唯一主來源是 [Training KB 設計 §8.2、§8.3、§9.3、§13、§18 O3](../../design/training-kb.md)。
- 前置為 [Phase 23：未發布版本與關係完整寫入](./23-Phase23-未發布版本與關係完整寫入.md)，未通過時停止；下一階段是 [Phase 25：多篇教學整批發布](./25-Phase25-多篇教學整批發布.md)。
- 本階段不做：不做 feedback widget 與下載流程（Phase 57）、不做版本選擇與 diff 檢視畫面（Phase 57）、不做多篇整批提交（Phase 25）、不做退役頁的後繼導向（Phase 26）、不建立任何新版本內容。
- O1–O7 gate 狀態：O3 由 [Phase 12](./12-Phase12-O3發布切換整合驗證.md) 判定為 **FAIL**（報告 `docs/plan/report/o3-20260914t181109z.md`），**目前不得宣稱已通過**；本 Phase 的測試只能證明程式邏輯，不能宣稱「publish 的故障驗收已通過」。O2 未 PASS 時不得宣稱重送必得同版號。O1 的 `META` 直接進交易 Key，O1 未明確接受前它仍是待確認值。
- **O3 未 PASS 不是停止條件（controller 2026-09-14 裁決）：離線開發照常，真實切點驗證延後到 P41／P59。** 本 Phase 照協定 A（私有 staging → `TransactWriteItems` → 逐篇寫 `site/`）在 moto 上完整實作並記錄三個切點，**不得宣稱 O3 已過、不得放寬 F49**。
- `commit` 只能對隔離環境（moto 或專用 Demo bucket）執行；不得對真實公開 bucket 提交，也不得用「沒有連結的 URL」充當未發布。
- 以下程式檔均是實作時預計建立或修改；本計畫本身不代表它們已存在。

---

## 1. 你在整體流程的位置

```text
Phase 23 未發布版本（published_at = null，私有 .md/.diff 已就緒）
                    |
      +-------------+------------------------------+
      | [你在這裡] Publisher 單篇三段式提交         |
      |  prepare -> inspect -> commit              |
      +-------------+------------------------------+
     +--------------+----------------+
  全部通過                        任一失敗
     v                               v
 DynamoDB 交易切兩欄            零變更；讀者仍讀舊版
     v                               v
 複製 staging -> site/          保留私有 staging 供重送
     |
     v
 Phase 25 多篇整批 / Phase 57 完整教學站
```

## 2. 完成後看得到什麼

輸入 `PublishRequest(version_ids=("prepare-meeting@v2",), operation_id="op-pub-2")`；`current_version` 與 `prepare-meeting@v2.supersedes` 都是 `prepare-meeting@v1`。成功後：

```text
VERSION#prepare-meeting@v2 . published_at   : null -> 2026-09-14T00:30:00Z
TUTORIAL#prepare-meeting   . current_version: prepare-meeting@v1 -> prepare-meeting@v2
site/tutorials/prepare-meeting/v2.html      : 新增，與私有 staging bytes 完全相同
```

若 `commit` 之前有人把 `current_version` 改成別的值，結果必須是 `PublishResult(published=(), failed="prepare-meeting@v2", reasons=("current_version 不等於 supersedes",))`，而且 `site/` 不會出現任何新檔案。

## 3. 名詞小抄

| 名詞 | 白話意思 |
|---|---|
| 三段式提交 | 先把產物做好（prepare）、再全部檢查（inspect）、最後一次切換（commit）。 |
| 私有 staging | 放在 `operations/` 前綴下的暫存 HTML；讀者看不到，只給 inspect 與 commit 用。 |
| 條件寫入 | 告訴 DynamoDB「只有欄位還是我剛讀到的值才准改」，避免蓋掉別人的結果。 |
| 失敗切點 | 流程可能中斷的每個時間點；每個切點對外看得到什麼都必須寫清楚。`transact_write_items` 把多個寫入綁成一次全有或全無。 |
| `html.escape` | 把 `&`、`<`、`>`、`"`、`'` 換成安全字元，避免教學文字被當成 HTML 標籤。 |

## 4. 預計檔案

| 動作 | 路徑 | 責任 |
|---|---|---|
| 建立 | `src/training_kb/publishing.py` | `PublishRequest`、`PreparedPublish`、`PublishInspection`、`PublishResult`、`Publisher`、`site_key`、`tutorial_index_key`、`site_index_key`。 |
| 建立 | `src/training_kb/site.py` | 最小 `SiteRenderer`：版本頁、教學索引、站台索引。[Phase 57](./57-Phase57-S3靜態教學站與回饋下載.md) 只換這支檔案的實作，不改模組路徑。 |
| 修改 | `src/training_kb/repository.py` | 增加 `transact_write` 與唯讀屬性 `table_name`，把條件不符轉成可判斷的回傳值。 |
| 測試 | `tests/unit/test_site_renderer.py` | 五段、步驟、版本號、退役提示與逃脫。 |
| 測試 | `tests/unit/test_publisher_single.py` | `prepare`／`inspect`／`commit` 與條件不符。 |
| 測試 | `tests/integration/test_publish_cutpoints.py` | 三個失敗切點的可觀察結果（moto）。 |

## 5. 固定介面

### Consumes

```text
to_iso(dt) -> str / PublishError / TransientError                          # Phase 02
TutorialContent(title, problem, prerequisites, steps, expected_outcome)    # Phase 03
Tutorial(slug, current_version, topic, feature_ids, status, successor, cluster_id)
TutorialVersion(version_id, slug, supersedes, reason, rules_applied, s3_key,
    published_at) / TutorialStep(tutorial_version, number, type, text, feature_id)  # Phase 04
tutorial_pk(slug) -> str / version_pk(version_id) -> str / META            # Phase 05
Repository.get_tutorial / get_version / get_object / put_object / get_steps  # Phase 06-08
OperationCoordinator.record_version(operation_id: str, version_id: str)    # Phase 10
parse_version_id(value) -> tuple[str, int]                                 # Phase 20
parse_markdown(markdown: str) / diff_key(slug: str, number: int) -> str    # Phase 22
verify_version_complete(version_id: str, repository: Repository) -> bool   # Phase 23
```

### Produces

```python
@dataclass(frozen=True)
class PublishRequest:
    version_ids: tuple[str, ...]
    operation_id: str

@dataclass(frozen=True)
class PreparedPublish:
    request: PublishRequest
    version_ids: tuple[str, ...]
    staged_keys: tuple[str, ...]
    prepared_at: datetime

@dataclass(frozen=True)
class PublishInspection:
    ok: bool
    problems: tuple[str, ...]

@dataclass(frozen=True)
class PublishResult:
    published: tuple[str, ...]
    failed: str | None
    reasons: tuple[str, ...]

class SiteRenderer:   # 模組 src/training_kb/site.py
    def __init__(self, *, notice: str = "", batch: str = "",
                 categories: tuple[str, ...] = (),
                 asset_prefix: str = "/site/assets") -> None: ...
    def render_version_page(self, tutorial: Tutorial, version: TutorialVersion, steps: list[TutorialStep], content: TutorialContent) -> str: ...
    def render_tutorial_index(self, tutorial: Tutorial, versions: list[TutorialVersion]) -> str: ...
    def render_site_index(self, tutorials: list[Tutorial]) -> str: ...

class Publisher:      # 模組 src/training_kb/publishing.py
    def __init__(self, repository: Repository, renderer: SiteRenderer, operations: OperationCoordinator) -> None: ...
    def prepare(self, request: PublishRequest, *, now: datetime) -> PreparedPublish: ...
    def inspect(self, prepared: PreparedPublish) -> PublishInspection: ...
    def commit(self, prepared: PreparedPublish, *, now: datetime) -> PublishResult: ...

def site_key(version_id: str) -> str: ...           # "tutorials/<slug>/v<n>.html"
def tutorial_index_key(slug: str) -> str: ...       # "tutorials/<slug>/index.html"
def site_index_key() -> str: ...                    # "index.html"

class Repository:     # Phase 06 既有類別，本 Phase 追加兩個成員
    @property
    def table_name(self) -> str: ...
    def transact_write(self, items: Sequence[Mapping[str, object]]) -> int | None: ...
```

`transact_write` 全部成功回 `None`；任一 `ConditionalCheckFailed` 回它在 `items` 的 index；其他取消原因轉成 `TransientError`。`table_name` 就是 `self._table.name`。`SiteRenderer` 三個 render 簽名到 Phase 57 都不改，Phase 57 只換實作；`__init__` 的四個 keyword 參數**全部有預設值**，所以本 Phase 與 Phase 25／41／48／52 的 `SiteRenderer()` 無參數建構永遠成立（Phase 57 加畫面選項時也不得拿掉預設值）。

**注意 API 層級不同，但值的形狀相同（2026-09-14 實作更正）：** [Phase 06](./06-Phase06-Repository-Metadata與實體讀寫.md) 的 `Repository` 拿的是 boto3 **resource** Table，`put_item`／`get_item` 用的是原生 Python 值；`transact_write_items` 只存在於 **client**，必須經 `self._table.meta.client` 取得。**但 `items` 的值一律是原生 Python 值，不是 `{"S": ...}` 低階 AttributeValue**：`boto3.resource("dynamodb")` 會在它自己的 client 上註冊 `dynamodb-attr-value-input`（`boto3/dynamodb/transform.py`），把所有 `AttributeValue` 形狀的參數再序列化一次，所以傳 `{"S": "TUTORIAL#x"}` 會變成 `{"M": {"S": {"S": "TUTORIAL#x"}}}`，moto 與真實 DynamoDB 都會拒絕（實測訊號：`TransactionCanceledException` + `CancellationReasons=[{'Code': 'TypeError', 'Message': "unhashable type: 'dict'"}]`）。本段原文與 00A §6.7 的「值用低階 `{"S": ...}` 形式」都與 boto3 實際行為不符，已依實測更正；**00A §6.7 尚待同步**。

## 6. 設計細節

`site_key("prepare-meeting@v2")` 固定回 `tutorials/prepare-meeting/v2.html`；私有 staging 是 `operations/<operation_id>/site/<相對 key>`，公開是 `site/<相對 key>`，公開前綴只有發布流程能寫（設計 §9.3）。同一組佈局的另外兩個 key 也在本 Phase 產出（00A 裁決 D-54）：`tutorial_index_key("prepare-meeting")` 回 `tutorials/prepare-meeting/index.html`、`site_index_key()` 回 `index.html`，[Phase 25](./25-Phase25-多篇教學整批發布.md)、[Phase 26](./26-Phase26-教學退役與後繼導向.md)、[Phase 57](./57-Phase57-S3靜態教學站與回饋下載.md) 一律 import 這三個，不自己接字串。三個 helper 回的都**不含** `site/` 前綴。

**每個版本有兩個公開物件。** 除了版本頁，`prepare` 還要把 [Phase 22](./22-Phase22-Markdown與Diff私有產物.md) 的私有 diff（`tutorials/<slug>/v<n>.diff`）逐字複製一份成公開副本 `tutorials/<slug>/v<n>.diff.txt`，一起放進 staging；Phase 57 的版本頁會用 `href` 指向它，Phase 25 的 `promote_site_objects` 一併 promote。公開副本的相對 key 由 module-private 的 `_diff_copy_key(version_id)` 產生（`site_key(...)` 去掉 `.html` 再加 `.diff.txt`）；Phase 57 給頁面用的 `site_diff_key(version_id)` 回**同一個字串**，兩邊改了一邊就要改另一邊。

```text
prepare:  verify_version_complete -> 讀 S3 全文 -> render -> 寫私有 staging
             +-- 任一篇不完整 -> PublishError；零 staging 對外可見
inspect:  staging 可讀回 + 步驟與內容同步 + current_version 仍等於 supersedes
             +-- 任一項不符 -> PublishInspection(ok=False, problems=(...))
commit:   自己先跑一次 inspect；ok? -- 否 --> PublishError，不進交易
             | 是
             v
          transact_write([VERSION.published_at, TUTORIAL.current_version])
    +--------+---------+
    | 條件不符         | 成功
    v                  v
 PublishResult      複製 staging bytes -> site/
 (published=())        +-- 寫 site 失敗 -> PublishError（DB 已切、公開未切）
```

交易固定兩個 `Update` action：

- `VERSION#<version_id>`：`SET published_at = :now`，條件 `attribute_not_exists(published_at) OR attribute_type(published_at, :null)`；已發布版本不可再被覆寫（設計 §8.1）。
- `TUTORIAL#<slug>`：`SET current_version = :version`，條件 `current_version = :base`（`supersedes` 非空）或 `attribute_not_exists(current_version) OR attribute_type(current_version, :null)`（v1）。

`TransactWriteItems` 是 all-or-nothing，一次最多 100 個 action、總計 4 MB；任一條件不符丟 `TransactionCanceledException`，`CancellationReasons` 依 `TransactItems` 順序回報，只有 `Code == "ConditionalCheckFailed"` 才算條件不符。交易**只涵蓋 DynamoDB**，不含 S3。

公開順序固定「先 DynamoDB 再 S3」。反過來會讓尚未發布的內容先曝光，直接違反設計 §8.3 與 §13；先 DynamoDB 的殘留風險是「已標記發布但公開站仍是舊頁」，讀者看到的是**舊的已發布版**而非未發布內容。兩者都不完美，這正是 O3 尚未解的部分；本 Phase 只固定較安全的一邊並把切點寫出來，不宣稱已解。版本頁的 S3 寫入採條件核對：同 key 已存在時先 `get_object` 比對 bytes，完全相同就不重寫，不同就丟 `PublishError`；教學索引與站台索引是可重建投影，允許重寫。

**`data-published` 與重新渲染在本 Phase 就做（依 00A §3.8、§6.7 更正）。** 原文把標記與重新渲染都推給 [Phase 57](./57-Phase57-S3靜態教學站與回饋下載.md)，但 00A §3.8 要求「`published_at is None` 的頁面渲染時帶 `data-published="false"`，只能存在於私有 staging」，00A §6.7 也把「重新渲染的責任」明確歸給 **P24 的 `commit`**（P57 只負責頁面上其他標記）。所以本 Phase 的最小 renderer **就輸出** `data-published`，而 `prepare` 渲染時 `published_at` 必然還是 `None`；`commit` 在交易成功後、寫 `site/` 之前，用已切換的 `published_at`／`current_version` 重新渲染並覆寫**同一個 staging key**，promote 才仍然是「複製 staging 的同一份 bytes」（Phase 25 的 `promote_site_objects` 因此只要搬 bytes），也才不會把 `data-published="false"` 帶進公開站。

**教學索引額外帶 `data-site-version`。** 值是 `tutorial.current_version` 的 `v<n>`（沒有已發布版本時是空字串）。[Phase 12](./12-Phase12-O3發布切換整合驗證.md) 的 O3 觀察腳本就是讀這個標記判斷「公開站此刻是哪一個世代」，本 Phase 的切點測試沿用同一個觀察方法，P41／P59 之後才能在真實 AWS 重跑同一組切點。Phase 57 換實作時不得拿掉它。

**交易成功之後的 S3 階段失敗一律轉成 `PublishError`。** 此時兩個欄位已經切換，整個 `commit` 重跑會被 `inspect` 擋下（版本已發布），所以它不是可交給 ASL Retry 的暫時故障；補償重送 `resume_publish` 歸 [Phase 59](./59-Phase59-失敗復原與重送驗收.md)，私有 staging 一律保留不刪。

## 7. TDD Tasks

共用器材寫在**使用它的測試檔裡**（原文寫「對應的 `conftest.py`」，但 `tests/unit/conftest.py` 的 owner 是 P15、`tests/integration/conftest.py` 的 owner 是 P06，P24 都不是它們的修改者，見 00A §3.2；做法與 Phase 23 相同）。整合測試的 moto fixture 名一律是 `repository`（00A §3.2），只有單元測試的 `Repository` 子類別叫 `repo`。`renderer` 是 `SiteRenderer()`（無參數）；`fixtures.active_v1(...)` 回一組 `(Tutorial, TutorialVersion, list[TutorialStep], TutorialContent)`；`repo` 是接上 moto 表與 bucket 的 `Repository`，`repo.objects` 是它 bucket 內所有 key 的唯讀檢視；`publisher` 是 `Publisher(repo, SiteRenderer(), operations)`，其中的 `prepare-meeting@v2` 已由 [Phase 23](./23-Phase23-未發布版本與關係完整寫入.md) 的 `create_version` 寫成完整未發布版本。`NOW` 是固定且不含微秒的 aware UTC 時間，`to_iso` 與 pydantic 的往返才會相等。測試字串 `"op-pub-2"` 只是 fixture，正式路徑的 `operation_id` 一律由 Phase 32 的 `operation_id_for` 產生。

### Task 1：最小 SiteRenderer 與逃脫

- [x] **Step 1：建立失敗測試**

```python
def test_render_version_page_escapes_text_and_shows_version(renderer, fixtures):
    tutorial, version, steps, content = fixtures.active_v1(step_text="開啟 <會議> 頁面")
    page = renderer.render_version_page(tutorial, version, steps, content)
    assert "&lt;會議&gt;" in page
    assert "<會議>" not in page
    assert "prepare-meeting@v1" in page
    assert 'class="retired"' not in page
    for section in ("Problem", "Prerequisites", "Steps", "Expected Outcome"):
        assert f"<h2>{section}</h2>" in page
```

- [x] **Step 2：執行並確認紅燈**

```bash
uv run pytest tests/unit/test_site_renderer.py -q
```

預期：FAIL，訊號包含 `cannot import name 'SiteRenderer'`。

- [x] **Step 3：建立最小實作**

```python
def render_version_page(self, tutorial, version, steps, content) -> str:
    if [(s.number, s.text) for s in steps] != [(d.number, d.text) for d in content.steps]:
        raise PublishError(f"{version.version_id} 的已保存步驟與公開內容不同步")
    esc = html.escape   # from html import escape 亦可；所有可見文字都要過這一關
    need = "".join(f"<li>{esc(item)}</li>" for item in content.prerequisites)
    todo = "".join(f"<li>{esc(step.text)}</li>" for step in steps)
    page = (f"<h1>{esc(content.title)}</h1>"
            f'<p class="version">{esc(version.version_id)}</p>'
            f"<h2>Problem</h2><p>{esc(content.problem)}</p>"
            f"<h2>Prerequisites</h2><ul>{need}</ul><h2>Steps</h2><ol>{todo}</ol>"
            f"<h2>Expected Outcome</h2><p>{esc(content.expected_outcome)}</p>")
    if tutorial.status == "retired":
        page += '<p class="retired">此教學已退役，內容僅供歷史查閱。</p>'
    return page
```

- [x] **Step 4：補上兩個索引方法並跑綠燈**

`render_tutorial_index` 只列 `published_at` 非空的版本並標出 `current_version`；`render_site_index` 只列 `current_version` 非空的 Tutorial；所有文字一律先 `html.escape`。`__init__` 的四個 keyword 參數在本 Phase 只是存起來備用，Phase 57 才會真的用到，但現在就要有預設值。退役提示文字由 [Phase 26](./26-Phase26-教學退役與後繼導向.md)／Phase 57 定案，本 Phase 只放一句固定佔位，不顯示退役原因。

```bash
uv run pytest tests/unit/test_site_renderer.py -q
```

預期：三個 render 測試全部 PASS。

- [x] **Step 5：提交**

```bash
git add src/training_kb/site.py tests/unit/test_site_renderer.py
git commit -m "feat(content): 建立最小公開頁 renderer"
```

### Task 2：prepare 與 inspect 只碰私有前綴

- [x] **Step 1：建立失敗測試**

```python
def test_prepare_stages_privately_and_never_touches_site(publisher, repo):
    request = PublishRequest(version_ids=("prepare-meeting@v2",), operation_id="op-pub-2")
    prepared = publisher.prepare(request, now=NOW)
    assert prepared.staged_keys == (            # 版本頁與公開 diff 副本，排序後固定兩個
        "operations/op-pub-2/site/tutorials/prepare-meeting/v2.diff.txt",
        "operations/op-pub-2/site/tutorials/prepare-meeting/v2.html")
    assert prepared.prepared_at == NOW
    assert [key for key in repo.objects if key.startswith("site/")] == []
    assert repo.get_version("prepare-meeting@v2").published_at is None
    assert repo.get_tutorial("prepare-meeting").current_version == "prepare-meeting@v1"
```

再加兩個案例：`verify_version_complete` 回 `False` 時 `prepare` 丟 `PublishError` 且零 staging；`prepare` 之後把 `current_version` 改掉時 `inspect` 必須回 `ok=False`，`problems` 指出 `current_version`。

- [x] **Step 2：執行並確認紅燈**

```bash
uv run pytest tests/unit/test_publisher_single.py -q
```

預期：FAIL，訊號包含 `cannot import name 'Publisher'`。

- [x] **Step 3：建立最小實作**

```python
def _diff_copy_key(version_id: str) -> str:
    """公開 diff 副本的相對 key；Phase 57 的 site_diff_key 回同一個字串。"""
    return site_key(version_id).removesuffix(".html") + ".diff.txt"


def _stage_one(self, version_id: str, operation_id: str) -> tuple[str, str]:
    if not verify_version_complete(version_id, self._repository):
        raise PublishError(f"{version_id} 的內容或關係不完整")
    version = self._repository.get_version(version_id)
    body = self._repository.get_object(version.s3_key)
    if body is None:
        raise PublishError(f"{version_id} 缺少私有全文")
    page = self._renderer.render_version_page(
        self._repository.get_tutorial(version.slug), version,
        self._repository.get_steps(version_id), parse_markdown(body.decode("utf-8")))
    slug, number = parse_version_id(version_id)
    diff = self._repository.get_object(diff_key(slug, number))
    if diff is None:
        raise PublishError(f"{version_id} 缺少私有 diff")
    return (self._stage(operation_id, site_key(version_id),
                        page.encode("utf-8"), "text/html; charset=utf-8"),
            self._stage(operation_id, _diff_copy_key(version_id),
                        diff, "text/plain; charset=utf-8"))


def _stage(self, operation_id: str, relative: str, body: bytes, content_type: str) -> str:
    key = f"operations/{operation_id}/site/{relative}"
    self._repository.put_object(key, body, content_type, if_none_match=False)
    return key
```

`prepare` 只是對 `request.version_ids` 逐一呼叫 `_stage_one`，把每篇回傳的兩個 key 收齊，再回傳 `PreparedPublish(request, tuple(request.version_ids), tuple(sorted(keys)), now)`。staging 用 `if_none_match=False`：同 operation 重送時渲染結果是決定性的，覆寫同一份 bytes 是安全的；公開 `site/` 的寫入才需要第 6 節說的 bytes 比對。

- [x] **Step 4：跑綠燈**

```bash
uv run pytest tests/unit/test_publisher_single.py -q
```

預期：三個 `prepare`／`inspect` 測試 PASS，且 `repo.objects` 中沒有任何 `site/` 開頭的 key。

- [x] **Step 5：提交**

```bash
git add src/training_kb/publishing.py tests/unit/test_publisher_single.py
git commit -m "feat(content): 以私有 staging 準備單篇發布"
```

### Task 3：一筆交易同時切 published_at 與 current_version

- [x] **Step 1：建立失敗測試**

```python
def test_commit_switches_both_fields_then_writes_site(publisher, repo):
    prepared = publisher.prepare(PublishRequest(("prepare-meeting@v2",), "op-pub-2"), now=NOW)
    assert publisher.inspect(prepared).ok is True
    result = publisher.commit(prepared, now=NOW)
    assert result == PublishResult(published=("prepare-meeting@v2",), failed=None, reasons=())
    assert repo.get_version("prepare-meeting@v2").published_at == NOW
    assert repo.get_tutorial("prepare-meeting").current_version == "prepare-meeting@v2"
    assert "site/tutorials/prepare-meeting/v2.html" in repo.objects
```

再加一個 `test_commit_refuses_when_base_version_moved`：`prepare` 後把 `current_version` 改成 `prepare-meeting@v9`，`commit` 自己那次 `inspect` 就會擋下來，所以斷言是 `pytest.raises(PublishError)`（訊息含 `current_version`）且 `repo.transact_calls == 0`，`published_at` 仍是 `None`、`site/` 無新檔：

```python
def test_commit_refuses_when_base_version_moved(publisher, repo):
    prepared = publisher.prepare(PublishRequest(("prepare-meeting@v2",), "op-pub-2"), now=NOW)
    repo.set_current_version("prepare-meeting", "prepare-meeting@v9")
    with pytest.raises(PublishError, match="current_version"):
        publisher.commit(prepared, now=NOW)
    assert repo.transact_calls == 0            # inspect 沒過就不送交易
    assert repo.get_version("prepare-meeting@v2").published_at is None
    assert [key for key in repo.objects if key.startswith("site/")] == []
```

`repo.transact_calls` 是 `Repository` 子類別記下的 `transact_write` 呼叫次數（子類別只加觀察點，`transact_write` 先記一筆再原樣呼叫父類別）。**位移發生在交易當下**（`inspect` 時還沒改、送出交易才不符）是另一條路徑：那時 DynamoDB 的條件失敗，`commit` 回 `PublishResult(published=(), failed=..., reasons=(...))` 而不丟例外，由 [Phase 25](./25-Phase25-多篇教學整批發布.md) 的整批測試涵蓋。

- [x] **Step 2：執行並確認紅燈**

```bash
uv run pytest tests/unit/test_publisher_single.py -q -k commit
```

預期：FAIL，訊號包含 `'Repository' object has no attribute 'transact_write'`。（**實作時的實際紅燈訊號不同**：`transact_write` 先補上了，所以 8 個 `commit` 測試一起紅在 `TransientError: transaction cancelled: [{'Code': 'TypeError', 'Message': "unhashable type: 'dict'"}, ...]`——那是第 5 節更正的「低階 AttributeValue 被 resource client 再序列化一次」造成的，換成原生 Python 值就全綠。）

- [x] **Step 3：建立最小實作**

```python
def _update(table, pk, expression, condition, values):
    # 值是原生 Python 值，不是 {"S": ...}：resource 的 client 會自己序列化一次。
    # "#rev = #rev + :one" 與業務欄位同一個 SET，交易切換才會推進 _revision，
    # update_meta 的 compare-and-swap 不會在發布之後仍以為舊 revision 是最新的
    # （與 Phase 12 的 O3 spike publish_transaction 同一套算式）。
    return {"Update": {"TableName": table, "Key": {"PK": pk, "SK": META},
                       "UpdateExpression": f"{expression}, #rev = #rev + :one",
                       "ConditionExpression": condition,
                       "ExpressionAttributeNames": {"#rev": "_revision"},
                       "ExpressionAttributeValues": {**values, ":one": 1}}}


def _transact_items(self, version, tutorial, *, now: datetime) -> list[Mapping[str, object]]:
    table, null = self._repository.table_name, {":null": "NULL"}
    values = {":version": version.version_id}
    if version.supersedes is None:
        clause = "attribute_not_exists(current_version) OR attribute_type(current_version, :null)"
        values |= null
    else:
        clause, values = "current_version = :base", values | {":base": version.supersedes}
    return [
        _update(table, version_pk(version.version_id), "SET published_at = :now",
                "attribute_not_exists(published_at) OR attribute_type(published_at, :null)",
                {":now": to_iso(now), **null}),
        _update(table, tutorial_pk(tutorial.slug), "SET current_version = :version", clause, values),
    ]
```

- [x] **Step 4：補上 `commit` 並跑綠燈**

`commit` 先呼叫 `inspect`，不通過就丟 `PublishError`（`problems` 一併放進訊息）；再把 `_transact_items` 的兩個 action 一次送進 `transact_write`。回非 `None` 時換算成 `version_ids[index // 2]`（每篇固定兩個 action，順序是 VERSION、TUTORIAL）與對應原因字串，回 `PublishResult(published=(), failed=..., reasons=(...))` 而**不丟例外**；回 `None` 才進 S3 階段：先用已切換的 `published_at`／`current_version` **重新渲染並覆寫同一個 staging key**（第 6 節），再把 staging bytes 複製到 `site/`——每篇兩個物件（版本頁 `v<n>.html` 與公開 diff 副本 `v<n>.diff.txt`），同 key 已存在先比對 bytes，不同就丟 `PublishError`——再用 `tutorial_index_key(slug)` 與 `site_index_key()` 重寫教學索引與站台索引（可重建投影，允許重寫），最後呼叫 `operations.record_version(operation_id, version_id)`。這整個 S3 階段的任何失敗都轉成 `PublishError`。

```bash
uv run pytest tests/unit/test_publisher_single.py -q
```

預期：`commit` 的成功與「基底位移被 `inspect` 擋下」兩個測試都 PASS。

- [x] **Step 5：依第 8 節切點表逐一注入失敗，存成證據檔後提交**

三個切點用 `monkeypatch` 在 `Publisher` 內部注入例外（本 Phase 還沒有 [Phase 59](./59-Phase59-失敗復原與重送驗收.md) 的 `TKB_FAULT` 模組，不要提前建立），每次注入後把 DynamoDB 兩個欄位與公開讀取結果寫進測試輸出當證據。

```bash
uv run pytest tests/integration/test_publish_cutpoints.py -q
git add src/training_kb/publishing.py src/training_kb/repository.py tests/integration/test_publish_cutpoints.py
git commit -m "feat(content): 以單筆交易提交單篇發布"
```

## 8. 驗收矩陣

| 路徑 | 輸入 | 預期資料結果 |
|---|---|---|
| Happy | v2 完整、`current_version=v1` | 兩欄同時切換；`site/.../v2.html` 與 `site/.../v2.diff.txt` 都出現；`failed is None`。 |
| Happy | v1 首次發布（`supersedes=None`） | `current_version` 由空切成 v1；索引頁列出該教學。 |
| Failure | `verify_version_complete` 回 `False` | `prepare` 丟 `PublishError`；零 staging、零公開檔案。 |
| Failure | commit 前 `current_version` 被改 | `commit` 內的 `inspect` 擋下 → `PublishError`；`transact_write` 0 次；兩欄皆不變；`site/` 無新檔。 |
| Failure | 交易當下才位移／版本已有 `published_at` | 條件不符 → `PublishResult(published=(), failed=...)`，不丟例外；兩欄皆不變；`site/` 無新檔。 |
| Boundary | `commit` 內部的 `inspect` 不通過（例如 staging 被刪掉） | `PublishError`；不進交易。 |
| Boundary | 同 operation 重送、staging 已存在 | 重用相同 bytes，不產生第二個版本或第二份 HTML。 |
| Privacy | 任何時點掃描 `site/` | 只有 `published_at` 非空的版本頁，沒有草稿、diff 或回饋原文。 |

三個失敗切點的可觀察結果（切點代號與 [Phase 12](./12-Phase12-O3發布切換整合驗證.md) 的 `O3CutPoint` 相同，本 Phase 只是在單篇路徑上重現它們）：

| 切點 | DynamoDB | 公開 `site/` | 停止／復原 |
|---|---|---|---|
| `a1_before_transact`（交易前） | `published_at=null`、`current_version` 舊值 | 舊版 | 可安全重送；staging 私有可重用。 |
| `a1_before_transact`（交易被取消，觀察結果相同） | 兩欄皆未變 | 舊版 | 回 `PublishResult(published=())`，呼叫端重讀基底。 |
| `a2_after_transact_before_site`（交易成功、寫 `site/` 前） | 已是新版 | **仍是舊版** | 丟 `PublishError`；同 operation 重送補寫；Phase 12 已判定它是 partial，補齊前不得宣稱 O3 通過。 |

另外三個代號不屬於本 Phase：`b1_after_site_before_transact`（先 site 後交易）是被本 Phase 明文禁止的順序，程式不會走到；`a3_after_first_site_before_second` 只出現在 [Phase 25](./25-Phase25-多篇教學整批發布.md) 的多篇路徑；`c1_after_delete_site`（事後刪除公開頁）由 Phase 12 負責證明「刪除不消除已發生的曝光」，本 Phase 不得拿刪檔當回滾。

人工驗收（**延後至 P41／P59**，controller 2026-09-14 裁決：離線開發照常，真實切點驗證延後）：用公開 website endpoint 實際讀一次頁面，同時 `get_item` 讀 `VERSION` 與 `TUTORIAL`，兩邊必須指向同一版本；不能只看測試顯示 PASS。S3 website endpoint 只有 HTTP，本 Phase 不把它描述成 HTTPS。

## 9. 常見錯誤與停止條件

| 症狀 | 原因 | 修正／停止 |
|---|---|---|
| 先寫 `site/` 再切 DynamoDB | 想讓頁面早點出現 | 立即停止：未發布內容曝光違反設計 §8.3；順序必須 DB 先。 |
| `published_at` 有值但公開頁仍舊 | 交易後寫 S3 失敗 | 以同 operation 重送補寫；不要刪版本或回寫 `published_at`。 |
| 兩個 `UpdateItem` 分開送 | 不知道有交易 API | 改用一次 `transact_write_items`；分開送會出現只切一半。 |
| 教學文字把版面弄壞 | 忘記 `html.escape` | 所有使用者可見文字一律逃脫後再拼字串。 |
| 宣稱 publish 故障驗收通過 | 把 moto 綠燈當 O3 證據 | 停止：O3 仍待 [Phase 12](./12-Phase12-O3發布切換整合驗證.md) 的真實整合結果。 |

## 10. 來源與 Rule 對照

Rule 原文逐字取自 feature 檔；primary 歸屬依 [00B 需求覆蓋對照](./00B-需求覆蓋對照.md)。

- [發布教學版本.feature](../../spec/features/發布教學版本.feature)
  - Rule 1：「publish 上架指定的 TutorialVersion」→ **primary**，Task 3 `test_commit_switches_both_fields_then_writes_site` 直接斷言。
  - Rule 4：「Tutorial 的 current_version 指向目前教學版本」→ **primary**，Task 3 兩個測試分別斷言切換與不切換。
  - Rule 5：「已上架的版本具有 published_at」→ **primary**，Task 3 斷言交易同時寫入，且已發布版本不可再切。
  - Rule 2：「發布的教學透過 S3 靜態 docs 站提供」→ 相關（primary 在 [Phase 57](./57-Phase57-S3靜態教學站與回饋下載.md)）；本 Phase 只做最小頁面 renderer，Task 2／3 斷言公開 HTML 只出現在 `site/` 前綴，完整 docs 站與 bucket policy 由 Phase 57 證明。
  - Rule 3：「發布的教學提供 feedback widget」→ 相關（primary 在 Phase 57）；**不在本階段**。
- [建立教學版本.feature](../../spec/features/建立教學版本.feature) Rule 5、6、7 → 相關（primary 在 [Phase 22](./22-Phase22-Markdown與Diff私有產物.md)、[Phase 23](./23-Phase23-未發布版本與關係完整寫入.md)）：本 Phase 只讀 `s3_key`，不重寫全文或 diff。
- [執行教學流程.feature](../../spec/features/執行教學流程.feature) Rule 7：「每個 Step Functions Task 設定 Catch」→ 相關（primary 在 [Phase 29](./29-Phase29-共用Pipeline執行器與ASL失敗語意.md)）；本 Phase 只保證 `commit` 失敗時整次執行失敗且不留下新公開版本，這是決策 F49，不是 Rule 7 本身。
- 設計 §8.2：建立版本與發布是兩個步驟，`published_at=null` 代表未發布。§8.3：同一交易更新 `published_at` 與 `current_version` 並檢查基底未改變，O3 未解。§9.3、§13：`site/` 只由發布流程寫入，回饋原文、身份與執行紀錄保持私有。
- [DynamoDB TransactWriteItems](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/transaction-apis.html)：all-or-nothing、最多 100 個 action 與 4 MB，條件不符回 `TransactionCanceledException` 與 `CancellationReasons`。
- [S3 條件寫入](https://docs.aws.amazon.com/AmazonS3/latest/userguide/conditional-writes.html)：`If-None-Match` 只接受 `*`，已存在時回 `412 Precondition Failed`。
- [Python html.escape](https://docs.python.org/3/library/html.html)：`html.escape(s, quote=True)` 轉換 `&`、`<`、`>`，`quote` 為真時另轉 `"` 與 `'`；[S3 website endpoints](https://docs.aws.amazon.com/AmazonS3/latest/userguide/WebsiteEndpoints.html) 只有 HTTP。

## 11. 完成清單

- [x] `PublishRequest`、`PreparedPublish`、`PublishInspection`、`PublishResult`、`Publisher`、`SiteRenderer` 簽名逐字符合本文件；`SiteRenderer` 在 `src/training_kb/site.py`，且 `SiteRenderer()` 可以無參數建構。
- [x] `site_key("prepare-meeting@v2")` 回 `tutorials/prepare-meeting/v2.html`、`tutorial_index_key("prepare-meeting")` 回 `tutorials/prepare-meeting/index.html`、`site_index_key()` 回 `index.html`（D-54），公開物件都是它們前面加 `site/`。
- [x] `prepare` 每篇 staging 兩個物件（版本頁與 `v<n>.diff.txt` 公開副本），只寫 `operations/` 私有前綴，任何失敗都不留公開產物。
- [x] `commit` 用一次 `transact_write_items` 同時切 `published_at` 與 `current_version`，條件是 `supersedes` 非空時 `current_version = :base`、v1 時 `attribute_not_exists(current_version) OR attribute_type(current_version, :null)`。
- [x] 交易成功之後才寫 `site/`；順序反過來即視為缺陷。`commit` 內的 `inspect` 不通過時丟 `PublishError` 且 `transact_write` 0 次。
- [x] 公開文字全部經 `html.escape`，索引頁不列未發布版本。
- [x] `a1_before_transact`、交易被取消、`a2_after_transact_before_site` 三個切點各有一筆實際注入證據與可觀察結果紀錄。
- [x] 發布教學版本 Rule 1、4、5 各有直接 assertion；Rule 2、3 只標為相關（primary 在 Phase 57）。
- [x] 未把單元測試或 moto PASS 說成 O3 已通過、AWS 已驗收或站台已上線。
- [x] 最小 renderer 輸出 `data-published`，`commit` 在交易成功後重新渲染同一個 staging key，`site/` 掃描不得出現 `data-published="false"`（00A §3.8、§6.7）。
- [x] `transact_write` 的 `items` 用原生 Python 值（resource client 自己序列化），交易同時推進 `_revision`。
- [ ] 真實 AWS 上重跑三個切點與 website endpoint 人工驗收 —— **延後至 P41／P59**（O3 仍是 FAIL）。
