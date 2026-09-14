"""單篇教學發布提交（Phase 24）：`Publisher` 是唯一能切 `published_at` 與 `current_version`
的地方，也是唯一能寫公開 `site/` 前綴的地方（設計 §8.2、§8.3、§9.3、§13）。

三段式提交，程式決定順序與條件，AWS 只負責原子性與條件檢查：

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
 PublishResult      重新渲染 staging -> 複製 bytes 到 site/ -> 重建兩個索引
 (published=())        +-- 寫 site 失敗 -> PublishError（DB 已切、公開未切）
```

**公開順序固定「先 DynamoDB 再 S3」。** 反過來會讓尚未發布的內容先曝光，直接違反設計
§8.3 與 §13；先 DynamoDB 的殘留風險是「已標記發布但公開站仍是舊頁」，讀者看到的是**舊的
已發布版**而非未發布內容。兩者都不完美，這正是 O3 尚未解的部分（Phase 12 判定 FAIL，切點
`a2_after_transact_before_site` 是已知 partial）。**本模組只固定較安全的一邊並把切點寫出來，
不宣稱 O3 已通過**；真實 AWS 的切點重跑延後到 P41／P59（controller 2026-09-14 裁決）。

**三個公開 key helper 歸本模組**（D-54）：`site_key`／`tutorial_index_key`／`site_index_key`
回的都**不含** `site/` 前綴。公開物件 = `site/` + 相對 key，私有 staging =
`operations/<operation_id>/site/<相對 key>`。Phase 25／26／57 一律 import 這三個，不自己接
字串；只有公開 diff 的 `site_diff_key(version_id)` 歸 Phase 57，而且必須與本檔 module-private
的 `_diff_copy_key(version_id)` 回同一個字串。

**本模組 import `training_kb.site`，`site` 不得反向 import 本模組**（否則兩支檔互相 import）。
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime

from training_kb.clock import to_iso
from training_kb.content import (
    DIFF_CONTENT_TYPE,
    PUBLIC_SITE_PREFIX,
    diff_key,
    parse_markdown,
    parse_version_id,
    verify_version_complete,
)
from training_kb.errors import ObjectAlreadyExists, PublishError
from training_kb.keys import META, OPERATIONS_PREFIX, tutorial_pk, version_pk
from training_kb.models import Tutorial, TutorialContent, TutorialVersion, bare_id
from training_kb.operations import OperationCoordinator
from training_kb.repository import Repository, item_to_model
from training_kb.site import SiteRenderer

SITE_PAGE_CONTENT_TYPE = "text/html; charset=utf-8"
"""公開 HTML 的 content type；教學索引與站台索引也用同一個值。"""

SITE_TUTORIALS_DIR = "tutorials"
"""公開佈局裡放教學的那一層（00A §3.4）。字面值與 `PRIVATE_TUTORIAL_PREFIX` 相同是巧合，
兩者意思不同（一個在 `site/` 底下、一個是私有前綴本身），所以不共用常數。"""

ACTIONS_PER_VERSION = 2
"""每篇固定兩個交易 action，順序是 VERSION、TUTORIAL；`transact_write` 回的 index
就是靠它換算成第幾篇與哪一個欄位。"""

CANCEL_REASONS = ("published_at 已經有值", "current_version 不等於 supersedes")
"""兩個 action 各自的條件不符原因，順序與 `_transact_items` 完全一致。"""


# --- 1. 四個發布 dataclass ---------------------------------------------------


@dataclass(frozen=True)
class PublishRequest:
    """一次發布請求。`operation_id` 決定 staging 前綴，正式路徑由 Phase 32 的
    `operation_id_for` 產生，呼叫端不得自己拼字串。"""

    version_ids: tuple[str, ...]
    operation_id: str


@dataclass(frozen=True)
class PreparedPublish:
    """`prepare` 的結果：已經寫好、但**完全不對外**的私有產物清單。

    `staged_keys` 是**排序後**的 tuple（00A §6.7），每篇兩個：版本頁與公開 diff 副本。
    `version_ids` 與 `request.version_ids` 同值，讓 `inspect`／`commit` 不必再拆 request。
    """

    request: PublishRequest
    version_ids: tuple[str, ...]
    staged_keys: tuple[str, ...]
    prepared_at: datetime


@dataclass(frozen=True)
class PublishInspection:
    """`inspect` 的結果；`ok=False` 時 `problems` 一定非空，而且逐條可讀。"""

    ok: bool
    problems: tuple[str, ...]


@dataclass(frozen=True)
class PublishResult:
    """`commit` 的結果。**條件不符不是例外**：`failed` 有值代表 DynamoDB 擋下了這次切換，
    兩個欄位都沒變、`site/` 也沒有新檔，呼叫端重讀基底再決定。"""

    published: tuple[str, ...]
    failed: str | None
    reasons: tuple[str, ...]


# --- 2. 三個公開 key helper（D-54）-------------------------------------------


def site_key(version_id: str) -> str:
    """已發布版本頁的相對 key：`tutorials/<slug>/v<n>.html`（**不含** `site/` 前綴）。"""
    slug, number = parse_version_id(version_id)
    return f"{SITE_TUTORIALS_DIR}/{slug}/v{number}.html"


def tutorial_index_key(slug: str) -> str:
    """一篇教學的版本紀錄頁：`tutorials/<slug>/index.html`（**不含** `site/` 前綴）。"""
    return f"{SITE_TUTORIALS_DIR}/{bare_id(slug)}/index.html"


def site_index_key() -> str:
    """站台索引：`index.html`（**不含** `site/` 前綴）。"""
    return "index.html"


def _diff_copy_key(version_id: str) -> str:
    """公開 diff 副本的相對 key；Phase 57 的 `site_diff_key` 回同一個字串。"""
    return site_key(version_id).removesuffix(".html") + ".diff.txt"


def _public_key(relative: str) -> str:
    return PUBLIC_SITE_PREFIX + relative


def _staging_key(operation_id: str, relative: str) -> str:
    """私有 staging：`operations/<operation_id>/site/<相對 key>`（00A §3.4）。"""
    return f"{OPERATIONS_PREFIX}{operation_id}/site/{relative}"


# --- 3. 交易 action ----------------------------------------------------------


def _update(table: str, pk: str, expression: str, condition: str,
            values: Mapping[str, object]) -> dict[str, object]:
    """一個 `Update` action。

    值是**原生 Python 值**，不是 `{"S": ...}` 低階 AttributeValue：`Repository` 的
    `self._table.meta.client` 是 boto3 **resource** 的 client，它會自己把 `AttributeValue`
    形狀的參數序列化一次（見 `Repository.transact_write` 的說明）。

    `#rev = #rev + :one` 與業務欄位在同一個 `SET`，所以交易切換也會推進 `_revision`：
    `update_meta` 的 compare-and-swap 才不會在發布之後仍然認為舊的 revision 是最新的
    （與 Phase 12 的 O3 spike `publish_transaction` 同一套算式）。
    """
    return {"Update": {
        "TableName": table,
        "Key": {"PK": pk, "SK": META},
        "UpdateExpression": f"{expression}, #rev = #rev + :one",
        "ConditionExpression": condition,
        "ExpressionAttributeNames": {"#rev": "_revision"},
        "ExpressionAttributeValues": {**values, ":one": 1},
    }}


# --- 4. Publisher ------------------------------------------------------------


class Publisher:
    """`prepare` / `inspect` / `commit` 三段式單篇提交。

    最小 renderer 由建構參數傳進來（Phase 57 只換 `SiteRenderer` 的實作，本類別不動）。
    `operations` 只用來在成功之後 `record_version`，發布過程不讀它。
    """

    def __init__(self, repository: Repository, renderer: SiteRenderer,
                 operations: OperationCoordinator) -> None:
        self._repository = repository
        self._renderer = renderer
        self._operations = operations

    # --- prepare ---

    def prepare(self, request: PublishRequest, *, now: datetime) -> PreparedPublish:
        """把每篇要公開的產物寫進**私有** staging；任何失敗都不留公開產物。

        逐篇處理，任一篇丟 `PublishError` 就整次停下來：已經寫出去的 staging 留在
        `operations/` 私有前綴，讀者看不到，同 operation 重送會覆寫同一份 bytes（設計 §8.2
        規定失敗時保留產物，不刪）。
        """
        staged: list[str] = []
        for version_id in request.version_ids:
            staged.extend(self._stage_one(version_id, request.operation_id))
        return PreparedPublish(request=request, version_ids=tuple(request.version_ids),
                               staged_keys=tuple(sorted(staged)), prepared_at=now)

    def _stage_one(self, version_id: str, operation_id: str) -> tuple[str, str]:
        """一篇的兩個私有 staging 物件：版本頁與公開 diff 副本。"""
        if not verify_version_complete(version_id, self._repository):
            raise PublishError(f"{version_id} 的內容或關係不完整")
        version, tutorial, content = self._load(version_id)
        page = self._renderer.render_version_page(
            tutorial, version, self._repository.get_steps(version_id), content)
        slug, number = parse_version_id(version_id)
        diff = self._repository.get_object(diff_key(slug, number))
        if diff is None:
            raise PublishError(f"{version_id} 缺少私有 diff")
        return (self._stage(operation_id, site_key(version_id),
                            page.encode("utf-8"), SITE_PAGE_CONTENT_TYPE),
                self._stage(operation_id, _diff_copy_key(version_id),
                            diff, DIFF_CONTENT_TYPE))

    def _stage(self, operation_id: str, relative: str, body: bytes,
               content_type: str) -> str:
        """staging 用 `if_none_match=False`：同 operation 重送時渲染結果是決定性的，覆寫
        同一份 bytes 是安全的。公開 `site/` 的寫入才需要 bytes 比對。"""
        key = _staging_key(operation_id, relative)
        self._repository.put_object(key, body, content_type, if_none_match=False)
        return key

    def _load(self, version_id: str) -> tuple[TutorialVersion, Tutorial, TutorialContent]:
        """版本、它的教學與**S3 全文解析出的公開內容**；缺任何一項都是 `PublishError`。"""
        version = self._repository.get_version(version_id)
        if version is None:
            raise PublishError(f"找不到 VERSION item {version_id}")
        tutorial = self._repository.get_tutorial(version.slug)
        if tutorial is None:
            raise PublishError(f"找不到 TUTORIAL item {version.slug}")
        body = self._repository.get_object(version.s3_key)
        if body is None:
            raise PublishError(f"{version_id} 缺少私有全文 {version.s3_key}")
        return version, tutorial, parse_markdown(body.decode("utf-8"))

    # --- inspect ---

    def inspect(self, prepared: PreparedPublish) -> PublishInspection:
        """發布前的全部檢查；**只讀不寫**，所以可以被 `commit` 再呼叫一次。

        三類問題：staging 讀不回來、已保存步驟與公開內容不同步、基底已位移
        （`current_version` 不等於 `supersedes`）。已經有 `published_at` 的版本也在這裡擋下，
        不必等到交易條件失敗。
        """
        problems: list[str] = [
            f"私有 staging 讀不回來：{key}"
            for key in prepared.staged_keys if self._repository.get_object(key) is None
        ]
        for version_id in prepared.version_ids:
            problems.extend(self._version_problems(version_id))
        return PublishInspection(ok=not problems, problems=tuple(problems))

    def _version_problems(self, version_id: str) -> list[str]:
        version = self._repository.get_version(version_id)
        if version is None:
            return [f"找不到 VERSION item {version_id}"]
        problems: list[str] = []
        if version.published_at is not None:
            problems.append(f"{version_id} 的 published_at 已經有值，不可再發布")
        tutorial = self._repository.get_tutorial(version.slug)
        if tutorial is None:
            return [*problems, f"找不到 TUTORIAL item {version.slug}"]
        if tutorial.current_version != version.supersedes:
            problems.append(
                f"{version_id} 的基底已位移：current_version 不等於 supersedes"
                f"（{tutorial.current_version} != {version.supersedes}）")
        body = self._repository.get_object(version.s3_key)
        if body is None:
            return [*problems, f"{version_id} 缺少私有全文 {version.s3_key}"]
        saved = [(step.number, step.text)
                 for step in self._repository.get_steps(version_id)]
        public = [(draft.number, draft.text)
                  for draft in parse_markdown(body.decode("utf-8")).steps]
        if saved != public:
            problems.append(f"{version_id} 的已保存步驟與公開內容不同步")
        return problems

    # --- commit ---

    def commit(self, prepared: PreparedPublish, *, now: datetime) -> PublishResult:
        """一次 `TransactWriteItems` 切兩個欄位，成功之後才寫公開 `site/`。

        `inspect` 沒過就丟 `PublishError`（**不是**回 `PublishResult(published=())`），
        而且交易次數必須是 0：呼叫端看得到的事實是「什麼都沒發生」。條件不符才是回傳值，
        因為那代表 DynamoDB 已經幫我們擋下了一次覆寫，是預期內的併發結果。
        """
        inspection = self.inspect(prepared)
        if not inspection.ok:
            raise PublishError("發布前檢查未通過：" + "；".join(inspection.problems))
        loaded = [self._load(version_id)[:2] for version_id in prepared.version_ids]
        items: list[Mapping[str, object]] = []
        for version, tutorial in loaded:
            items.extend(self._transact_items(version, tutorial, now=now))
        index = self._repository.transact_write(items)
        if index is not None:
            return PublishResult(
                published=(),
                failed=prepared.version_ids[index // ACTIONS_PER_VERSION],
                reasons=(CANCEL_REASONS[index % ACTIONS_PER_VERSION],))
        operation_id = prepared.request.operation_id
        published: list[str] = []
        for version, tutorial in loaded:
            self._publish_site(version, tutorial, operation_id, now=now)
            self._operations.record_version(operation_id, version.version_id)
            published.append(version.version_id)
        return PublishResult(published=tuple(published), failed=None, reasons=())

    def _publish_site(self, version: TutorialVersion, tutorial: Tutorial, operation_id: str,
                      *, now: datetime) -> None:
        """交易成功之後的 S3 階段：重新渲染 -> 版本頁與 diff 副本 -> 教學索引 -> 站台索引。

        **這一段失敗一律轉成 `PublishError`**（設計 §8.3、Phase 24 §6）：此時
        `published_at` 與 `current_version` 已經切換，整個 `commit` 再重跑一次也會被
        `inspect` 擋下（版本已發布），所以它不是可以交給 ASL Retry 的暫時故障。這正是
        Phase 12 標記的切點 `a2_after_transact_before_site`——**DynamoDB 已是新版、公開站
        仍是舊版**。讀者看到的是舊的**已發布**版本，不是未發布內容，但它確實是 partial：
        **不得因為本 Phase 綠燈就宣稱 O3 已通過**。補償重送（`resume_publish`）歸 Phase 59；
        私有 staging 一律保留不刪，讓它有東西可補。
        """
        try:
            self._restage(version, tutorial, operation_id, now=now)
            self._promote(version.version_id, operation_id)
            self._write_indexes(tutorial.slug)
        except PublishError:
            raise
        except Exception as error:
            raise PublishError(
                f"{version.version_id} 已切換 published_at 與 current_version，"
                f"但公開頁尚未寫出（切點 a2_after_transact_before_site）：{error}") from error

    def _transact_items(self, version: TutorialVersion, tutorial: Tutorial, *,
                        now: datetime) -> list[Mapping[str, object]]:
        """一篇固定兩個 `Update`，順序是 VERSION、TUTORIAL（`CANCEL_REASONS` 依它排）。

        - `VERSION#<version_id>`：`SET published_at = :now`，條件是「還沒發布過」——
          已發布版本不可再被覆寫（設計 §8.1）。
        - `TUTORIAL#<slug>`：`SET current_version = :version`，條件是基底未改變；
          v1（`supersedes is None`）時基底是「還沒有任何已發布版本」。

        `published_at`／`current_version` 在表裡是 DynamoDB 的 NULL 型別（模型欄位是
        `None`），所以「還沒有值」要同時認 `attribute_not_exists` 與 `attribute_type(..., :null)`。
        """
        table = self._repository.table_name
        null: dict[str, object] = {":null": "NULL"}
        values: dict[str, object] = {":version": version.version_id}
        if version.supersedes is None:
            clause = ("attribute_not_exists(current_version) "
                      "OR attribute_type(current_version, :null)")
            values |= null
        else:
            clause = "current_version = :base"
            values[":base"] = version.supersedes
        return [
            _update(table, version_pk(version.version_id), "SET published_at = :now",
                    "attribute_not_exists(published_at) "
                    "OR attribute_type(published_at, :null)",
                    {":now": to_iso(now), **null}),
            _update(table, tutorial_pk(tutorial.slug), "SET current_version = :version",
                    clause, values),
        ]

    # --- 交易成功之後：重新渲染 -> promote -> 重建索引 ---

    def _restage(self, version: TutorialVersion, tutorial: Tutorial, operation_id: str, *,
                 now: datetime) -> None:
        """用**已經切換好的**兩個欄位重新渲染，覆寫同一個 staging key（00A §6.7）。

        `prepare` 渲染那次 `published_at` 必然還是 `None`，頁面因此帶
        `data-published="false"`；不重新渲染就直接 promote，等於把「未發布」標記帶進公開站
        （00A §3.8）。重新渲染之後 promote 仍然是「複製 staging 的同一份 bytes」，
        Phase 25 的 `promote_site_objects` 也只需要搬 bytes。

        欄位值直接用交易剛寫進去的那兩個值（`model_copy`），不再讀一次表：交易是
        all-or-nothing，成功就代表表裡就是這兩個值；回頭再讀反而會把別人之後的修改
        誤當成本次結果。
        """
        switched_version = version.model_copy(update={"published_at": now})
        switched_tutorial = tutorial.model_copy(update={"current_version": version.version_id})
        _, _, content = self._load(version.version_id)
        page = self._renderer.render_version_page(
            switched_tutorial, switched_version,
            self._repository.get_steps(version.version_id), content)
        self._stage(operation_id, site_key(version.version_id),
                    page.encode("utf-8"), SITE_PAGE_CONTENT_TYPE)

    def _promote(self, version_id: str, operation_id: str) -> None:
        """把 staging 的同一份 bytes 複製到公開 `site/`：版本頁與公開 diff 副本各一個。"""
        for relative, content_type in ((site_key(version_id), SITE_PAGE_CONTENT_TYPE),
                                       (_diff_copy_key(version_id), DIFF_CONTENT_TYPE)):
            staged = _staging_key(operation_id, relative)
            body = self._repository.get_object(staged)
            if body is None:
                raise PublishError(f"私有 staging 讀不回來：{staged}")
            self._put_public(relative, body, content_type)

    def _put_public(self, relative: str, body: bytes, content_type: str) -> None:
        """版本頁與 diff 副本採條件寫入：同 key 已存在就比對 bytes。

        完全相同代表同 operation 重送，靜靜通過；不同代表兩次不同內容搶同一個公開 key，
        丟 `PublishError` 並**保留既有物件**。條件交給 S3 判斷（`if_none_match=True`），
        不「先查再寫」——那會在兩個請求之間留下空窗。
        """
        key = _public_key(relative)
        try:
            self._repository.put_object(key, body, content_type, if_none_match=True)
        except ObjectAlreadyExists:
            if self._repository.get_object(key) != body:
                raise PublishError(f"公開物件已存在且內容不同，不覆寫：{key}") from None

    def _write_indexes(self, slug: str) -> None:
        """重建教學索引與站台索引。

        兩個索引都是**可重建的投影**（內容完全由 DynamoDB 決定），所以允許重寫
        （`if_none_match=False`）；版本頁與 diff 副本才是不可覆寫的一次性產物。
        順序固定：版本頁 -> 教學索引 -> 站台索引。
        """
        tutorial = self._repository.get_tutorial(slug)
        if tutorial is None:
            raise PublishError(f"找不到 TUTORIAL item {slug}")
        versions = sorted(
            (row for row in self._models("VERSION", TutorialVersion)
             if row.slug == slug and row.published_at is not None),
            key=lambda row: parse_version_id(row.version_id)[1], reverse=True)
        self._put_index(tutorial_index_key(slug),
                        self._renderer.render_tutorial_index(tutorial, versions))
        tutorials = sorted(self._models("TUTORIAL", Tutorial), key=lambda row: row.slug)
        self._put_index(site_index_key(), self._renderer.render_site_index(tutorials))

    def _put_index(self, relative: str, page: str) -> None:
        self._repository.put_object(_public_key(relative), page.encode("utf-8"),
                                    SITE_PAGE_CONTENT_TYPE, if_none_match=False)

    def _models[M: TutorialVersion | Tutorial](self, entity: str,
                                               model: type[M]) -> list[M]:
        """整表掃某一種 metadata item。Phase 27 的 `list_versions_of_tutorial` 還不存在，
        索引頁又必須看到全部已發布版本，所以先走 `scan_entity`（設計 §10 已接受 MVP 的
        基表 Scan 取捨）；Phase 27 之後可以換掉這一個私有 helper，公開行為不變。"""
        return [item_to_model(row, model) for row in self._repository.scan_entity(entity)]
