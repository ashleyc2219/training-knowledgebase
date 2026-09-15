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
字串；只有公開 diff 的 `site_diff_key(version_id)` 歸 Phase 57，它也在本檔（Phase 24 先以
module-private 的 `_diff_copy_key` 落地，Phase 57 改成公開名稱，同一個函式、同一份字串）。

**多篇整批（Phase 25）走同一組 `prepare`／`inspect`／`commit`，單篇就是 N=1 特例**：

```text
assert_batch_publishable  空／>50 篇／重複 id／同 slug 兩版 -> PublishError（零 staging）
  v
prepare 全部 -> inspect 全部 -> build_commit_transaction（2N 個 action）-> 一次 transact_write
  |                                                          |
  任一不通過 -> 零篇發布                     條件不符 -> PublishResult(published=())
                                             成功 -> pending-promote.json -> promote_site_objects
                                                  -> 逐篇教學索引 -> 站台索引
```

**F49 不可放寬**：只要一篇失敗就整批不發布，不得改成「允許部分成功再補」，也不得用
「先發布 A、B 失敗就刪掉 A」代替——事後刪除不會消除先前曝光（設計 §8.3、§19 F49）。
交易成功之後才逐一寫 `site/`，那一段中斷仍然是 partial（切點
`a3_after_first_site_before_second`），本模組只把它縮到最小並留下 `pending-promote.json`
給 Phase 59 精確補齊，**不宣稱 O3 已通過**。

**本模組 import `training_kb.site`，`site` 不得反向 import 本模組**（否則兩支檔互相 import）。
"""

import json
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
from training_kb.errors import CoordinationError, ObjectAlreadyExists, PublishError
from training_kb.faults import maybe_fail
from training_kb.keys import META, OPERATIONS_PREFIX, operation_ref, tutorial_pk, version_pk
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
"""兩個 action 各自的條件不符原因，順序與 `_version_and_tutorial_actions` 完全一致。"""

MAX_BATCH_VERSIONS = 50
"""一次 `TransactWriteItems` 最多 100 個 action、每篇固定 2 個，所以一批最多 50 篇
（00A §6.7）。超過就丟 `PublishError`：**不可以**拆成兩次交易換取「跑得完」，拆了就不再是
全有或全無，上游要自己分批並各自遵守 F49（設計 §8.3、§19 F49）。"""

PENDING_PROMOTE_NAME = "pending-promote"
"""整批待 promote 清單的檔名，完整 key 是 `operation_ref(operation_id, 這個值)`
（`operations/<operation_id>/pending-promote.json`）。**只寫私有前綴**：十實體是嚴格模型，
往 `TUTORIAL`／`VERSION` item 多塞一個欄位，下次 `get_meta` 就整筆驗證失敗（00A §3.6）。"""

PENDING_PROMOTE_CONTENT_TYPE = "application/json"
"""待 promote 清單的 content type；與 `operations/` 底下其他操作紀錄一致。"""


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


def site_diff_key(version_id: str) -> str:
    """公開 diff 副本的相對 key：`tutorials/<slug>/v<n>.diff.txt`（**不含** `site/` 前綴）。

    Phase 24 先以模組私有的 `_diff_copy_key` 落地，Phase 57 依 00A §6.7／D-54 把它改成公開
    名稱：**一份字串兩個用途**（`Publisher` 拿它算 key、教學站拿同一個版號組相對 href），
    不在 `site.py` 另寫一份。owner 是 P57，但落點與另外三個 helper 一樣在本模組
    （`site` 不得 import `publishing`，反向 import 會循環）。
    """
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


def _version_and_tutorial_actions(version: TutorialVersion, tutorial: Tutorial, table: str, *,
                                  now: datetime) -> list[dict[str, object]]:
    """一篇固定兩個 `Update`，順序是 VERSION、TUTORIAL（`CANCEL_REASONS` 依它排）。

    - `VERSION#<version_id>`：`SET published_at = :now`，條件是「還沒發布過」——
      已發布版本不可再被覆寫（設計 §8.1）。
    - `TUTORIAL#<slug>`：`SET current_version = :version`，條件是基底未改變；
      v1（`supersedes is None`）時基底是「還沒有任何已發布版本」。

    `published_at`／`current_version` 在表裡是 DynamoDB 的 NULL 型別（模型欄位是
    `None`），所以「還沒有值」要同時認 `attribute_not_exists` 與 `attribute_type(..., :null)`。

    Phase 25 把它從 `Publisher._transact_items` 搬成模組函式（私有 helper 不是跨 Phase
    介面），單篇於是成為整批的 N=1 特例，**全套只有一份條件式**。
    """
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


# --- 4. 整批發布：邊界、交易組成與 promote（Phase 25）------------------------


def assert_batch_publishable(prepared: PreparedPublish) -> None:
    """整批的四個邊界；**任何拒絕都必須發生在寫第一個 staging 物件之前**。

    | 拒絕 | 理由 |
    |---|---|
    | 空清單 | 「成功但沒事做」會讓上游以為已發布，`PublishResult` 也說不出發布了什麼。 |
    | 超過 `MAX_BATCH_VERSIONS` | 交易上限 100 個 action；拆成兩次交易就不再是全有或全無。 |
    | 重複的 `version_id` | 一律拒絕、**不自動去重**，去重會遮蔽上游的錯誤。 |
    | 同 slug 兩個版本 | 兩個 action 指到同一筆 `TUTORIAL#<slug>`，AWS 判 validation error。 |

    同 slug 兩版屬於接受順序（O2）問題：上游把同一篇的兩次變更放進同一批了，必須回頭
    串行處理，**不得由程式自己挑較新的那一版**。

    slug 用 Phase 20 的 `parse_version_id` 取，不自己 `split("@")`：那樣擋不掉形狀不對的
    `version_id`，等於在專案裡多一份版本 ID 解析規則（D-19）。
    """
    version_ids = list(prepared.version_ids)
    if not version_ids:
        raise PublishError("整批發布至少要有一個版本")
    if len(version_ids) > MAX_BATCH_VERSIONS:
        raise PublishError(
            f"一次交易最多 {MAX_BATCH_VERSIONS} 篇，收到 {len(version_ids)} 篇")
    if len(set(version_ids)) != len(version_ids):
        raise PublishError("整批內有重複的 version_id")
    slugs = [parse_version_id(version_id)[0] for version_id in version_ids]
    if len(set(slugs)) != len(slugs):
        raise PublishError("同一篇教學不可在同一批出現兩個版本，請依接受順序串行處理")


def build_commit_transaction(prepared: PreparedPublish, *, repository: Repository,
                             now: datetime) -> list[dict[str, object]]:
    """整批的 2N 個交易 action，順序是「第 1 篇 VERSION、第 1 篇 TUTORIAL、第 2 篇…」。

    `transact_write` 回的 index 因此可以換算回「第 `index // ACTIONS_PER_VERSION` 篇、
    `CANCEL_REASONS[index % ACTIONS_PER_VERSION]` 的原因」。先重跑一次
    `assert_batch_publishable`：這個函式是 Phase 48／52／59 也會直接呼叫的公開入口，
    不能假設呼叫端一定先經過 `prepare`。

    版本或教學讀不到一律 `PublishError`（不是讓 `None` 一路帶到 `AttributeError`）：
    這代表資料不完整，屬於「不可發布」而不是程式錯誤。
    """
    assert_batch_publishable(prepared)
    items: list[dict[str, object]] = []
    for version_id in prepared.version_ids:
        version = repository.get_version(version_id)
        if version is None:
            raise PublishError(f"{version_id} 不存在，不能提交")
        tutorial = repository.get_tutorial(version.slug)
        if tutorial is None:
            raise PublishError(f"{version.slug} 不存在，不能提交")
        items.extend(
            _version_and_tutorial_actions(version, tutorial, repository.table_name, now=now))
    return items


def _public_pairs(version_id: str) -> tuple[tuple[str, str], tuple[str, str]]:
    """一篇要公開的兩個物件：**版本頁先、公開 diff 副本後**（D-54），各帶自己的 content type。"""
    return ((site_key(version_id), SITE_PAGE_CONTENT_TYPE),
            (site_diff_key(version_id), DIFF_CONTENT_TYPE))


def public_site_keys(version_ids: tuple[str, ...]) -> tuple[str, ...]:
    """這一批會寫出的公開 key（含 `site/` 前綴），順序與 `version_ids` 相同、每篇兩個。

    `commit` 用它寫 `pending-promote.json`，`promote_site_objects` 用同一份順序實際搬 bytes，
    所以待補清單與實際寫出的物件不可能分岔。
    """
    return tuple(_public_key(relative)
                 for version_id in version_ids
                 for relative, _ in _public_pairs(version_id))


UNPUBLISHED_MARKER = b'data-published="false"'
"""未發布頁的機器可讀標記（00A §3.8）。它只能存在於私有 staging；`_put_public_object` 在
**寫出去之前**再擋一次，不只靠 `_restage` 的呼叫順序與整合測試事後掃描。"""


def _put_public_object(repository: Repository, relative: str, body: bytes,
                       content_type: str, *, if_none_match: bool = True) -> None:
    """**寫進 `site/` 的唯一出口**；寫出去之前一律先驗 `UNPUBLISHED_MARKER`。

    帶「未發布」標記的 bytes 不得進 `site/`（00A §3.8）。這是 runtime 守門，不是測試斷言
    ——`promote_site_objects` 是公開函式，Phase 48／52／59 可以不經 `Publisher.commit`
    直接呼叫它，而兩個索引頁也一樣要過這一關（不能因為它們是可重建投影就繞過去）。

    版本頁與 diff 副本是一次性產物，採條件寫入（`if_none_match=True`）：同 key 已存在就
    比對 bytes，完全相同代表同 operation 重送，靜靜通過；不同代表兩次不同內容搶同一個公開
    key，丟 `PublishError` 並**保留既有物件**。條件交給 S3 判斷，不「先查再寫」——那會在
    兩個請求之間留下空窗。

    `if_none_match=False` 是索引頁的覆寫語意：內容完全由 DynamoDB 決定，重建多少次都一樣，
    所以既有物件本來就該被新的投影蓋掉，沒有「兩份不同內容搶同一個 key」的問題。
    """
    key = _public_key(relative)
    if UNPUBLISHED_MARKER in body:
        raise PublishError(f"未發布標記不得進公開前綴，停止寫入：{key}")
    if not if_none_match:
        repository.put_object(key, body, content_type, if_none_match=False)
        return
    try:
        repository.put_object(key, body, content_type, if_none_match=True)
    except ObjectAlreadyExists:
        if repository.get_object(key) != body:
            raise PublishError(f"公開物件已存在且內容不同，不覆寫：{key}") from None


def _promote_version(version_id: str, operation_id: str,
                     repository: Repository) -> tuple[str, ...]:
    """把一篇的 staging bytes 複製到公開 `site/`：版本頁先、公開 diff 副本後。

    回傳**這一次實際寫出去的**公開 key（含 `site/` 前綴），順序與 `_public_pairs` 相同。
    回傳值由迴圈累積而不是事後重算一次 `public_site_keys(...)`：那樣兩邊都由同一個算式
    產生，回傳值就只是同義反覆，看不出「寫了什麼」（修正波：final review C#7）。
    """
    written: list[str] = []
    for relative, content_type in _public_pairs(version_id):
        staged = _staging_key(operation_id, relative)
        body = repository.get_object(staged)
        if body is None:
            raise PublishError(
                f"{version_id} 的 staging 物件不見了，停止 promote：{relative}")
        _put_public_object(repository, relative, body, content_type)
        written.append(_public_key(relative))
    return tuple(written)


def _cut_point(prepared: PreparedPublish) -> str:
    """交易成功之後失敗時，這是 Phase 12 的哪一個 O3 切點代號。

    單篇只有「交易成功、`site/` 還沒寫」一種；多篇多了「第 1 篇已公開、第 j 篇還沒」，
    兩者的可觀察結果不同（前者公開站整體落後一個世代，後者公開站**一新一舊**），
    所以錯誤訊息要分得出來，P41／P59 在真實 AWS 重跑時才對得上 Phase 12 的切點表。
    """
    if len(prepared.version_ids) < 2:
        return "a2_after_transact_before_site"
    return "a3_after_first_site_before_second"


def promote_site_objects(prepared: PreparedPublish, *,
                         repository: Repository) -> tuple[str, ...]:
    """依 `prepared.version_ids` 的順序把私有 staging 的同一份 bytes 複製到 `site/`。

    回傳這一批**實際寫出**的公開 key（含 `site/` 前綴），順序與 `prepared.version_ids`
    相同、每篇兩個。**已存在且 bytes 相同的 key 仍然回傳**，因為它同樣代表「這個公開物件
    已就緒」——Phase 59 以同一個 `operation_id` 重送時靠這一點只補齊缺的那幾個。

    這裡只做整批 promote 的**第一段**（版本頁與 diff 副本）；教學索引與站台索引是可重建
    投影，由 `Publisher.commit` 在本函式回傳之後用 `SiteRenderer` 重寫，整體順序仍然是
    「版本頁 → 教學索引 → 站台索引」。**本計畫選擇：** 這樣切分是為了讓本函式的參數只有
    `prepared` 與 `repository`，不必再傳一個 renderer 進來。
    """
    operation_id = prepared.request.operation_id
    written: list[str] = []
    for version_id in prepared.version_ids:
        written.extend(_promote_version(version_id, operation_id, repository))
    return tuple(written)


# --- 5. Publisher ------------------------------------------------------------


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

        **第一件事是 `assert_batch_publishable`**（Phase 25）：整批的四個邊界要在寫第一個
        staging 物件之前就擋下來，所以先用一個 `staged_keys` 還是空的 `PreparedPublish`
        問一次。單篇只是 N=1 的特例，不另外開一條路。
        """
        assert_batch_publishable(
            PreparedPublish(request=request, version_ids=tuple(request.version_ids),
                            staged_keys=(), prepared_at=now))
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
                self._stage(operation_id, site_diff_key(version_id),
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
        """一次 `TransactWriteItems` 切這一批的 2N 個欄位，成功之後才寫公開 `site/`。

        `inspect` 沒過就丟 `PublishError`（**不是**回 `PublishResult(published=())`），
        而且交易次數必須是 0：呼叫端看得到的事實是「什麼都沒發生」。條件不符才是回傳值，
        因為那代表 DynamoDB 已經幫我們擋下了一次覆寫，是預期內的併發結果。

        **整批只送出一次交易**（Phase 25、F49）：任一 action 條件不符就整批取消，
        `failed` 指出第 `index // ACTIONS_PER_VERSION` 篇，`published` 保持空 tuple。
        **不得**改成逐篇重試或只重送失敗那一篇——那等於承認部分成功。
        """
        inspection = self.inspect(prepared)
        if not inspection.ok:
            raise PublishError("發布前檢查未通過：" + "；".join(inspection.problems))
        loaded = [self._load(version_id)[:2] for version_id in prepared.version_ids]
        maybe_fail("publish_before_transact")   # Phase 59 切點 3：交易還沒送出，全舊
        items = build_commit_transaction(prepared, repository=self._repository, now=now)
        index = self._repository.transact_write(items)
        if index is not None:
            return PublishResult(
                published=(),
                failed=prepared.version_ids[index // ACTIONS_PER_VERSION],
                reasons=(CANCEL_REASONS[index % ACTIONS_PER_VERSION],))
        self._after_transaction(prepared, loaded, now=now)
        return PublishResult(published=tuple(prepared.version_ids), failed=None, reasons=())

    def _after_transaction(self, prepared: PreparedPublish,
                           loaded: list[tuple[TutorialVersion, Tutorial]], *,
                           now: datetime) -> None:
        """交易成功之後的收尾：**先記版號、再寫 `site/`**，任何失敗一律轉 `PublishError`。

        `record_version` 排在 S3 之前有兩個理由：它是 write-once、同值 no-op 的零副作用寫入，
        而且 P59 的**單篇**復原就是靠 `OPS#<operation_id>.version_id` + `site_key` 重算要補
        什麼（00A §6.7：單篇不寫 `pending-promote.json`）。排在後面的話，切點
        `a2_after_transact_before_site` 一發生 ledger 就留 `None`，復原沒有輸入
        （Phase 24 review Important 1）。

        **交易之後的任何例外都轉成 `PublishError`**（設計 §8.3）：此時 `published_at` 與
        `current_version` 已經切換，再跑一次 `commit` 也會被 `inspect` 擋下（版本已發布），
        所以它不是可以交給 ASL Retry 的暫時故障。單篇是 Phase 12 標記的切點
        `a2_after_transact_before_site`，多篇是 `a3_after_first_site_before_second`——
        **DynamoDB 已是新版、公開站一新一舊**。轉型別是為了讓「半發布」永遠以同一種錯誤
        現身，呼叫端不會因為漏接 `CoordinationError` 之類的型別而把它當成別的故障
        （Phase 24 review Important 2）。**不得因為本 Phase 綠燈就宣稱 O3 已通過**，也不得
        刪掉已 promote 的頁面充當回滾（事後刪除不消除曝光）。補償重送（`resume_publish`）
        歸 Phase 59；私有 staging 一律保留不刪，讓它有東西可補。
        """
        try:
            self._record_versions(prepared)
            self._publish_site(prepared, loaded, now=now)
        except PublishError:
            raise
        except Exception as error:
            raise PublishError(
                f"{'、'.join(prepared.version_ids)} 已切換 published_at 與 current_version，"
                f"但公開頁尚未寫出（切點 {_cut_point(prepared)}）：{error}") from error

    def _publish_site(self, prepared: PreparedPublish,
                      loaded: list[tuple[TutorialVersion, Tutorial]], *,
                      now: datetime) -> None:
        """交易成功之後的 S3 階段，五步順序固定，不可對調：

        1. 把待 promote 的公開 key 清單寫進 `operations/<operation_id>/pending-promote.json`；
        2. 用已切換好的欄位**重新渲染**每篇的 staging（還是私有前綴，讀者看不到）；
        3. 逐篇 `_promote`（與 `promote_site_objects` 同一段邏輯）搬版本頁與公開 diff 副本；
        4. 依 `version_ids` 首次出現順序重寫每個 slug 的教學索引；
        5. 重寫站台索引（整批只寫一次）。

        **待補清單排第一，排在 N 次 `_restage` 之前**：它是 P59 復原**整批**的唯一輸入
        （父 operation 依 D-59 不持有版號）。排在重新渲染之後的話，「交易成功、第一次
        `_restage` 就中斷」這個切點會讓 DynamoDB 已經切換、待補清單卻不存在，復原沒有輸入
        （Phase 25 review 必修 A1）。提前寫是零風險的：payload 只由 `prepared.version_ids`
        決定（確定性），只寫私有前綴，而且 `if_none_match=False` 允許同 operation 重送覆寫。

        「版本頁 → 教學索引 → 站台索引」的順序讓中斷時公開站最多是「新頁已存在但索引還沒
        指過去」，而不是索引指向不存在的頁。例外轉換在 `_after_transaction`。
        """
        operation_id = prepared.request.operation_id
        self._record_pending_promote(prepared)
        # Phase 59 切點 4：交易已提交、待補清單（或單篇的 ledger 版號）已就緒、公開物件還沒寫。
        # 例外會被 `_after_transaction` 轉成 `PublishError`（訊息帶 `_cut_point` 代號）。
        maybe_fail("publish_after_transact_before_site")
        for version, tutorial in loaded:
            self._restage(version, tutorial, operation_id, now=now)
        for version_id in prepared.version_ids:
            self._promote(version_id, operation_id)
        for slug in dict.fromkeys(tutorial.slug for _, tutorial in loaded):
            self._write_tutorial_index(slug)
        self._write_site_index()

    def _record_pending_promote(self, prepared: PreparedPublish) -> None:
        """**多篇才寫**待 promote 的公開 key 清單；只寫私有前綴，一個欄位都不進十實體 item。

        單篇不寫這個檔（00A §6.7）：P59 用 operation 紀錄的 `version_id` + `site_key` 就能
        重算要補什麼，多開一個 S3 物件只是多一份會過期的真相。整批做不到這件事——父
        operation 依 D-59 不持有版號，所以整批的待補輸入只能是這份清單。兩者剛好互補：

        ```text
        單篇  ledger 的 OPS#<op>.version_id            <- _record_versions
        多篇  operations/<op>/pending-promote.json     <- 這裡
        ```

        用 `if_none_match=False` 寫：同一個 `operation_id` 重送要能覆寫成同一份內容
        （清單完全由 `version_ids` 決定，是決定性的）。
        """
        if len(prepared.version_ids) < 2:
            return
        payload = {"version_ids": list(prepared.version_ids),
                   "site_keys": list(public_site_keys(prepared.version_ids))}
        self._repository.put_object(
            operation_ref(prepared.request.operation_id, PENDING_PROMOTE_NAME),
            json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            PENDING_PROMOTE_CONTENT_TYPE, if_none_match=False)

    def _record_versions(self, prepared: PreparedPublish) -> None:
        """單篇才把版號記進這一筆 operation；多篇的父 operation **不持有版號**（D-59）。

        `OperationRecord.version_id` 是單值，一個 operation 只能對應一篇教學的一個版本。
        多篇流程（Phase 48 的 Feedback Review、Phase 52 的 Release）一律對每篇各開一筆
        per-slug 子 operation，版號在那裡 `allocate_version` 時就寫進去了；父 operation 只
        負責整批追溯。在這裡硬寫第二篇會直接撞 `record_version` 的 `CoordinationError`。
        """
        if len(prepared.version_ids) != 1:
            return
        self._operations.record_version(prepared.request.operation_id,
                                        prepared.version_ids[0])

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
        """一篇的 promote；`promote_site_objects` 的單篇入口，兩者共用 `_promote_version`。

        `commit` 逐篇走這個方法而不是直接呼叫 `promote_site_objects`，是為了讓 Phase 12 與
        Phase 24 的切點注入點（`monkeypatch` 這個方法）留在路徑上，Phase 25 的切點 5 才有
        辦法只讓**第 j 篇**失敗。寫出的 key、順序與條件寫入語意兩邊完全相同。
        """
        _promote_version(version_id, operation_id, self._repository)

    def write_tutorial_index(self, slug: str) -> None:
        """重建一篇教學的版本紀錄頁（公開方法）。

        修正波（final review C 的 minor）：`_write_tutorial_index` 有兩個**外部**呼叫端
        （`release.task_retire` 的 D-83 重寫、`resume_publish` 的收尾），所以它不是私有的。
        方法本體維持不動，這裡只是把名字提成公開的，兩個呼叫端改用它。
        """
        self._write_tutorial_index(slug)

    def write_site_index(self) -> None:
        """重建站台索引（公開方法）；同 `write_tutorial_index` 的理由。"""
        self._write_site_index()

    def _write_tutorial_index(self, slug: str) -> None:
        """重建一篇教學的版本紀錄頁；只列已發布版本，版號大的在前。

        版本清單一律取自 Phase 27 的 `list_versions_of_tutorial`（它已經用
        `version_sort_key` 排成**升序**，反轉就是「版號大的在前」），本模組不再自己掃一次
        `VERSION` 也不自己排一次序：兩份排序邏輯遲早會分岔。

        索引是**可重建的投影**（內容完全由 DynamoDB 決定），所以允許重寫
        （`if_none_match=False`）；版本頁與 diff 副本才是不可覆寫的一次性產物。
        """
        tutorial = self._repository.get_tutorial(slug)
        if tutorial is None:
            raise PublishError(f"找不到 TUTORIAL item {slug}")
        versions = [row for row in self._repository.list_versions_of_tutorial(slug)
                    if row.published_at is not None][::-1]
        self._put_index(tutorial_index_key(slug),
                        self._renderer.render_tutorial_index(tutorial, versions))

    def _write_site_index(self) -> None:
        """重建站台索引；整批只寫**一次**，而且一定在所有教學索引之後。"""
        tutorials = sorted(self._tutorials(), key=lambda row: row.slug)
        self._put_index(site_index_key(), self._renderer.render_site_index(tutorials))

    def _put_index(self, relative: str, page: str) -> None:
        """兩個索引頁的唯一寫入點；覆寫語意，但守門與版本頁同一個 `_put_public_object`。"""
        _put_public_object(self._repository, relative, page.encode("utf-8"),
                           SITE_PAGE_CONTENT_TYPE, if_none_match=False)

    def _tutorials(self) -> list[Tutorial]:
        """站台索引要看到**全部** `TUTORIAL` item，所以走基表 `scan_entity`
        （設計 §10 已接受 MVP 的 Scan 取捨）；Phase 27 沒有對應的固定查詢。

        版本清單不再經過這裡：`write_tutorial_index` 改用
        `Repository.list_versions_of_tutorial`（見該方法說明）。
        """
        return [item_to_model(row, Tutorial)
                for row in self._repository.scan_entity("TUTORIAL")]


# ---- Phase 59 ----------------------------------------------------------------


def _string_tuple(operation_id: str, payload: object, field: str) -> tuple[str, ...]:
    """從 `pending-promote.json` 取一個字串陣列欄位；形狀不對是協調錯誤，不是程式錯誤。"""
    values = payload.get(field) if isinstance(payload, Mapping) else None
    if not isinstance(values, list) or not values:
        raise CoordinationError(f"{operation_id} 的待補清單缺少 {field}")
    return tuple(str(item) for item in values)


def _resume_targets(operation_id: str, *, operations: OperationCoordinator,
                    repository: Repository) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """這次要復原哪幾篇、應該補出哪幾個公開 key；兩種輸入互補（00A §6.7）。

    ```text
    多篇  operations/<op>/pending-promote.json   <- Publisher._record_pending_promote
    單篇  ledger 的 OPS#<op>.version_id          <- Publisher._record_versions
    ```

    待補清單優先：父 operation 依 D-59 不持有版號，所以多篇只有這一份輸入；清單裡的
    `site_keys` 與 `public_site_keys(version_ids)` 同一套算法，不會分岔。兩個都沒有代表這
    筆 operation 根本還沒走到交易，沒有東西可以補，直接 `CoordinationError` 交人工看。
    """
    body = repository.get_object(operation_ref(operation_id, PENDING_PROMOTE_NAME))
    if body is not None:
        payload = json.loads(body.decode("utf-8"))
        return (_string_tuple(operation_id, payload, "version_ids"),
                _string_tuple(operation_id, payload, "site_keys"))
    record = operations.load(operation_id)
    if record is None or record.version_id is None:
        raise CoordinationError(f"沒有可沿用的操作紀錄：{operation_id}")
    return (record.version_id,), public_site_keys((record.version_id,))


def resume_publish(operation_id: str, *, operations: OperationCoordinator,
                   repository: Repository, publisher: Publisher,
                   now: datetime) -> PublishResult:
    """同 operation 的**補償重送**：沿用原版號，交易已提交時只補公開物件。

    **順序是硬性的（00A §6.7、上一批 REP §8 第 9 項）：先 `prepare` 再
    `promote_site_objects`。** 切點 4 之前留下的 staging 是交易**前**渲染的，那時
    `published_at` 還是 `None`，頁面帶著 `UNPUBLISHED_MARKER`；直接 promote 會被
    `_put_public_object` 的 runtime 守門擋下並丟 `PublishError`——擋得好，但那代表**復原
    失敗**而不是成功。重跑 `prepare` 時表裡的 `published_at` 已經有值，重新渲染出來的
    staging 才是 `data-published="true"`。

    三條路：

    | 版本狀態 | 做什麼 | 從哪個切點進得來 |
    |---|---|---|
    | `published_at is None` | 照正常路徑 `commit`（`inspect` 會再檢查一次） | **只有切點 3** |
    | 全部已發布 | 只 `promote_site_objects` 補公開物件，再重建兩層索引 | 切點 4 |
    | 版本不存在 | `CoordinationError` | 資料不完整 |

    **切點 1、2、5 不從這裡復原**（Phase 59 review Minor）：切點 1／2 中斷時版本的私有產物或
    關係邊還不齊，`prepare` 會先被 `verify_version_complete` 擋下；切點 5 連版本都還沒建，
    ledger 也還沒有 `version_id`。這三個的復原方式是**以同一個 `operation_id` 重走完整路徑**
    （`create_version` 對同一份 plan 冪等、`allocate_version` 沿用 ledger 版號），
    走完之後才會落到本函式的第一列。

    **不得**在已發布的情況再呼叫 `commit`（`inspect` 會以「版本已發布」擋下）、**不得**
    刪除既有公開物件、**不得**重新 `allocate_version`。

    `written != expected` 這一道是 **`pending-promote.json` 自身的一致性檢查**，不是
    「實際補出來的東西對不對」的檢查（修正波：final review C#7 更正原本的說法）。
    `written` 來自 `promote_site_objects`——它逐篇累積這次真的寫出去的 key，而那些 key 由
    `_public_pairs(version_id)` 決定，所以只要 `version_ids` 相同就必然等於
    `public_site_keys(version_ids)`。`expected` 在單篇是同一個算式算出來的（永遠相等），
    在多篇才是讀自待補清單的 `site_keys` 欄位。因此這道守門實際攔得住的只有一種情況：
    待補清單被手動改壞，`site_keys` 與 `version_ids` 對不起來。那仍然值得攔——那時候
    「補完了」這句話已經沒有意義——但它**不保證** `site/` 上真的有那些物件（要保證得逐 key
    `object_exists`，那是另一件事，本函式不做）。

    **本計畫選擇（2026-09-14）：** 補完版本頁與 diff 副本之後**接著重建教學索引與站台索引**。
    `Publisher._publish_site` 的第 4、5 步就是它們，00A 第 1230 列說 `resume_publish` 要
    「把中斷的發布接著做完」；只補版本頁會讓公開站永遠沒有連到新版的路徑，那是半完成的
    復原。索引是可重建投影（`if_none_match=False`），重寫多少次結果都一樣。

    **切點 1／2／5 的復原機制**（修正波：把 P59 的文件 nit 併在這裡講清楚）：那三個切點
    不從本函式進來，復原方式是**以同一個 `operation_id` 重走完整路徑**——`allocate_version`
    對同一筆 operation 沿用 ledger 的版號、`create_version` 對同一份 plan 冪等，所以重跑
    不會產生第二個版號，走完之後才會落到本函式的第一列。
    """
    version_ids, expected = _resume_targets(operation_id, operations=operations,
                                            repository=repository)
    versions: list[TutorialVersion] = []
    for version_id in version_ids:
        version = repository.get_version(version_id)
        if version is None:
            raise CoordinationError(f"操作紀錄指向不存在的版本：{version_id}")
        versions.append(version)
    prepared = publisher.prepare(
        PublishRequest(version_ids=version_ids, operation_id=operation_id), now=now)
    if any(version.published_at is None for version in versions):
        return publisher.commit(prepared, now=now)
    written = promote_site_objects(prepared, repository=repository)
    if written != expected:
        raise CoordinationError(f"補寫的公開 key 與待補清單不一致：{operation_id}")
    for slug in dict.fromkeys(version.slug for version in versions):
        publisher.write_tutorial_index(slug)
    publisher.write_site_index()
    return PublishResult(published=version_ids, failed=None, reasons=())
