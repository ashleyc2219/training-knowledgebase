"""O3 gate 的一次性 spike：把「跨 DynamoDB 與 S3 的發布切換」五個失敗切點各跑一次。

這支腳本不是 `Publisher`，也不進 Lambda runtime。它只驗**協定**：用 boto3 client 的
`transact_write_items`（DynamoDB 端的原子提交）加上 S3 `PutObject`（沒有跨物件原子切換），
在每個切點立刻觀察「公開站顯示的版本」與「DynamoDB 的 current_version」，看對外是不是
只會見到整批舊或整批新（設計 §8.3、§18 O3；F36／F37／F49）。

`Repository.transact_write` 是 Phase 24 才有的方法，此時不存在，所以這裡直接用 boto3
client；報告要註明驗的是協定，不是 `Publisher` 的實作。
"""

import argparse
import json
import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

import boto3
from botocore.config import Config

from training_kb.clock import now_utc, to_iso
from training_kb.keys import META, tutorial_pk, version_pk

# --- 1. 契約常數 -------------------------------------------------------------

O3CutPoint = Literal[
    "a1_before_transact", "a2_after_transact_before_site",
    "a3_after_first_site_before_second", "b1_after_site_before_transact",
    "c1_after_delete_site",
]

CUT_POINTS: tuple[O3CutPoint, ...] = (
    "a1_before_transact",
    "a2_after_transact_before_site",
    "a3_after_first_site_before_second",
    "b1_after_site_before_transact",
    "c1_after_delete_site",
)

SLUGS: tuple[str, ...] = ("spike-a", "spike-b")
OLD_GENERATION = "v1"
NEW_GENERATION = "v2"

# 00A §3.4：公開頁一律在 site/ 前綴，未發布產物只能在私有前綴，不靠「沒有連結」充當私有。
PUBLIC_SITE_PREFIX = "site/"
PRIVATE_OPERATIONS_PREFIX = "operations/"

REGION_ENV = "TKB_AWS_REGION"
DEFAULT_REGION = "us-east-1"

# 設計 §14.3：連線 2 秒、讀取 30 秒；SDK 完全不重試，切點的觀察才不會被暗中補救。
SDK_CONFIG = Config(connect_timeout=2, read_timeout=30, retries={"total_max_attempts": 1})

_SITE_VERSION_PATTERN = re.compile(rb'data-site-version="(v[0-9]+)"')


# --- 2. 資料結構 -------------------------------------------------------------


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


# --- 3. 純函式判定 -----------------------------------------------------------


def is_partial(views: Sequence[PublicView], *, expected: str) -> bool:
    """對外同時看得到一部分新、一部分舊就是 partial（F49 禁止的狀態）。

    兩層判斷：先看同一篇的公開頁與指標是否同世代（F37「publish 成功才切指標」），
    再看所有篇是不是同一個世代、而且就是這次應該看到的那一個（F49「整次失敗不發布新版」）。
    """
    generations: set[str | None] = set()
    for view in views:
        if view.site_version != view.current_version:
            return True
        generations.add(view.site_version)
    return generations != {expected}


def site_generation(body: bytes | None) -> str | None:
    """從公開教學索引抓它指到的版本標記；物件不存在（或沒有標記）一律回 `None`。"""
    if body is None:
        return None
    found = _SITE_VERSION_PATTERN.search(body)
    return None if found is None else found.group(1).decode()


def generation_of(version_id: str | None) -> str | None:
    """`spike-a@v2` -> `v2`；`current_version` 還沒設過時回 `None`。"""
    if not version_id or "@" not in version_id:
        return None
    return version_id.rsplit("@", 1)[1]


def build_view(
    slug: str, *, site_body: bytes | None,
    current_version: str | None, published_at: str | None,
) -> PublicView:
    """把「一次 S3 GET ＋ 一次一致讀取」的原始值收成一列可比較的對外觀察。"""
    return PublicView(
        slug, site_generation(site_body), generation_of(current_version), published_at
    )


# --- 4. 觀察（真實 AWS 讀取） ------------------------------------------------

_CLIENTS: dict[str, Any] = {}


def spike_region() -> str:
    return os.environ.get(REGION_ENV) or DEFAULT_REGION


def dynamodb_client() -> Any:
    """這支腳本共用的 DynamoDB client；Region 一律由 `TKB_AWS_REGION` 決定（00A §3.5）。"""
    region = spike_region()
    key = f"dynamodb@{region}"
    if key not in _CLIENTS:
        _CLIENTS[key] = boto3.client("dynamodb", region_name=region, config=SDK_CONFIG)
    return _CLIENTS[key]


def s3_client() -> Any:
    """這支腳本共用的 S3 client；與 DynamoDB client 同一個 Region。"""
    region = spike_region()
    key = f"s3@{region}"
    if key not in _CLIENTS:
        _CLIENTS[key] = boto3.client("s3", region_name=region, config=SDK_CONFIG)
    return _CLIENTS[key]


def tutorial_index_key(slug: str) -> str:
    """公開教學索引（00A §3.4）；spike 只碰 spike-a／spike-b 兩個 slug 的 key。"""
    return f"{PUBLIC_SITE_PREFIX}tutorials/{slug}/index.html"


def site_version_key(slug: str, generation: str) -> str:
    return f"{PUBLIC_SITE_PREFIX}tutorials/{slug}/{generation}.html"


def get_object(bucket: str, key: str) -> bytes | None:
    """讀回整個 body；key 不存在回 `None`（真實 S3 需要 `s3:ListBucket` 才會回 404）。"""
    try:
        raw = s3_client().get_object(Bucket=bucket, Key=key)
    except s3_client().exceptions.NoSuchKey:
        return None
    payload: bytes = raw["Body"].read()
    return payload


def get_meta_item(table: str, pk: str) -> Mapping[str, Any] | None:
    """一致讀取基表的 metadata item；GSI 是最終一致，觀察切點不能走它。"""
    raw = dynamodb_client().get_item(
        TableName=table, Key={"PK": {"S": pk}, "SK": {"S": META}}, ConsistentRead=True
    )
    item: Mapping[str, Any] | None = raw.get("Item")
    return item


def _text(item: Mapping[str, Any] | None, name: str) -> str | None:
    if item is None:
        return None
    value = item.get(name)
    return None if value is None else str(value.get("S"))


def observe(slugs: Sequence[str], *, table: str, bucket: str) -> tuple[PublicView, ...]:
    """對每個 slug 做一次一致讀取與一次 S3 GET，組成「此刻對外看得到什麼」。"""
    views: list[PublicView] = []
    for slug in slugs:
        tutorial = get_meta_item(table, tutorial_pk(slug))
        current_version = _text(tutorial, "current_version")
        version = None if current_version is None else get_meta_item(
            table, version_pk(current_version)
        )
        views.append(
            build_view(
                slug,
                site_body=get_object(bucket, tutorial_index_key(slug)),
                current_version=current_version,
                published_at=_text(version, "published_at"),
            )
        )
    return tuple(views)


# --- 5. 最小雙儲存提交協定與切點注入 -----------------------------------------

# DynamoDB 交易硬限制：一次最多 100 個動作、總量 4 MB、同一 item 不可出現兩次。
# 本案每篇發布固定動 TUTORIAL 與 VERSION 兩個 item，所以單批上限就是 100 / 2 = 50 篇，
# 與 Phase 25 的 MAX_BATCH_VERSIONS 必須是同一個換算。
MAX_TRANSACT_ACTIONS = 100
ACTIONS_PER_VERSION = 2
MAX_BATCH_VERSIONS = MAX_TRANSACT_ACTIONS // ACTIONS_PER_VERSION

OLD_PUBLISHED_AT = "2026-09-01T00:00:00Z"
HTML_CONTENT_TYPE = "text/html; charset=utf-8"

# 每個切點「如果雙儲存是原子的」應該看到的那一個世代：以 DynamoDB 交易是否已提交為界，
# 交易是這次發布唯一的原子提交點。交易前 -> 全舊 v1；交易後 -> 全新 v2。
EXPECTED_GENERATION: dict[O3CutPoint, str] = {
    "a1_before_transact": OLD_GENERATION,
    "a2_after_transact_before_site": NEW_GENERATION,
    "a3_after_first_site_before_second": NEW_GENERATION,
    "b1_after_site_before_transact": OLD_GENERATION,
    "c1_after_delete_site": NEW_GENERATION,
}

CUT_POINT_NOTES: dict[O3CutPoint, str] = {
    "a1_before_transact": "私有 staging 已備妥但不對外，兩篇都還是 v1，符合 F36。",
    "a2_after_transact_before_site": "指標與 published_at 已切到 v2、公開頁仍是 v1，違反 F37。",
    "a3_after_first_site_before_second": "A 新 B 舊，不能宣稱整次沒有發布，違反 F49。",
    "b1_after_site_before_transact": "未發布內容已在 site/ 可讀、指標仍是 v1，違反 F36。",
    "c1_after_delete_site": "site 已回復 v1，但曝光紀錄仍留著被讀出的 v2 內容，收不回來。",
}


def version_id(slug: str, generation: str) -> str:
    return f"{slug}@{generation}"


def staging_key(operation_id: str, slug: str, generation: str) -> str:
    """發布前的私有 staging：`operations/<operation_id>/site/<site_key>`（00A §3.4）。"""
    return f"{PRIVATE_OPERATIONS_PREFIX}{operation_id}/site/tutorials/{slug}/{generation}.html"


def render_version_page(slug: str, generation: str, *, published: bool) -> bytes:
    """版本頁；`published_at is None` 的頁面帶 `data-published="false"`（00A §3.8）。"""
    flag = "true" if published else "false"
    return (
        f'<html data-site-version="{generation}" data-published="{flag}">'
        f"<h1>{slug} {generation}</h1></html>"
    ).encode()


def render_index_page(slug: str, generation: str) -> bytes:
    """教學索引；`data-site-version` 就是公開站此刻顯示的版本標記。"""
    return (
        f'<html data-site-version="{generation}" data-published="true">'
        f'<a href="{generation}.html">{slug} {generation}</a></html>'
    ).encode()


def put_site_object(bucket: str, key: str, body: bytes) -> None:
    """公開切換本來就要覆蓋既有索引，所以這裡不帶 `If-None-Match`。"""
    s3_client().put_object(Bucket=bucket, Key=key, Body=body, ContentType=HTML_CONTENT_TYPE)


def delete_object(bucket: str, key: str) -> None:
    s3_client().delete_object(Bucket=bucket, Key=key)


def _meta_key(pk: str) -> dict[str, Any]:
    return {"PK": {"S": pk}, "SK": {"S": META}}


def _tutorial_item(slug: str, generation: str) -> dict[str, Any]:
    """Tutorial metadata item：模型欄位 ＋ RESERVED_ATTRS，沒有第三類（00A §3.6）。"""
    return {
        **_meta_key(tutorial_pk(slug)),
        "entity": {"S": "TUTORIAL"},
        "_revision": {"N": "1"},
        "slug": {"S": slug},
        "current_version": {"S": version_id(slug, generation)},
        "topic": {"S": f"O3 spike {slug}"},
        "feature_ids": {"L": [{"S": "Prepare"}]},
        "status": {"S": "active"},
    }


def _version_item(slug: str, generation: str, *, published_at: str | None) -> dict[str, Any]:
    item: dict[str, Any] = {
        **_meta_key(version_pk(version_id(slug, generation))),
        "entity": {"S": "VERSION"},
        "_revision": {"N": "1"},
        "version_id": {"S": version_id(slug, generation)},
        "slug": {"S": slug},
        "reason": {"S": "gap:o3-spike"},
        "rules_applied": {"L": []},
        "s3_key": {"S": f"tutorials/{slug}/{generation}.md"},
    }
    if generation == NEW_GENERATION:
        item["supersedes"] = {"S": version_id(slug, OLD_GENERATION)}
    if published_at is not None:
        item["published_at"] = {"S": published_at}
    return item


def reset_to_old_generation(slugs: Sequence[str], *, table: str, bucket: str) -> None:
    """建立「全舊」初始狀態：兩篇都 v1 已發布、v2 已寫好但未發布，`site/` 只有 v1。"""
    for slug in slugs:
        dynamodb_client().put_item(TableName=table, Item=_tutorial_item(slug, OLD_GENERATION))
        dynamodb_client().put_item(
            TableName=table, Item=_version_item(slug, OLD_GENERATION, published_at=OLD_PUBLISHED_AT)
        )
        dynamodb_client().put_item(
            TableName=table, Item=_version_item(slug, NEW_GENERATION, published_at=None)
        )
        put_site_object(
            bucket,
            site_version_key(slug, OLD_GENERATION),
            render_version_page(slug, OLD_GENERATION, published=True),
        )
        put_site_object(bucket, tutorial_index_key(slug), render_index_page(slug, OLD_GENERATION))
        delete_object(bucket, site_version_key(slug, NEW_GENERATION))


def stage_private_artifacts(slugs: Sequence[str], *, bucket: str, operation_id: str) -> None:
    """待發布產物先進私有 `operations/` 前綴；未發布頁帶 `data-published="false"`（F36）。"""
    for slug in slugs:
        s3_client().put_object(
            Bucket=bucket,
            Key=staging_key(operation_id, slug, NEW_GENERATION),
            Body=render_version_page(slug, NEW_GENERATION, published=False),
            ContentType=HTML_CONTENT_TYPE,
        )


def publish_transaction(slugs: Sequence[str], *, table: str, stamp: str) -> None:
    """一次 `TransactWriteItems` 同時寫 `published_at` 與 `current_version`，並檢查基底未改變。"""
    actions: list[dict[str, Any]] = []
    for slug in slugs:
        actions.append(
            {
                "Update": {
                    "TableName": table,
                    "Key": _meta_key(tutorial_pk(slug)),
                    "UpdateExpression": "SET current_version = :new, #rev = #rev + :one",
                    "ConditionExpression": "current_version = :old",
                    "ExpressionAttributeNames": {"#rev": "_revision"},
                    "ExpressionAttributeValues": {
                        ":new": {"S": version_id(slug, NEW_GENERATION)},
                        ":old": {"S": version_id(slug, OLD_GENERATION)},
                        ":one": {"N": "1"},
                    },
                }
            }
        )
        actions.append(
            {
                "Update": {
                    "TableName": table,
                    "Key": _meta_key(version_pk(version_id(slug, NEW_GENERATION))),
                    "UpdateExpression": "SET published_at = :stamp, #rev = #rev + :one",
                    "ConditionExpression": "attribute_not_exists(published_at)",
                    "ExpressionAttributeNames": {"#rev": "_revision"},
                    "ExpressionAttributeValues": {":stamp": {"S": stamp}, ":one": {"N": "1"}},
                }
            }
        )
    if len(actions) > MAX_TRANSACT_ACTIONS:
        raise ValueError(f"一次交易最多 {MAX_BATCH_VERSIONS} 篇，不拆交易（F49）")
    dynamodb_client().transact_write_items(TransactItems=actions)


def promote_site(slug: str, *, bucket: str) -> None:
    """把一篇的公開頁切到新世代：先寫版本頁，再換教學索引指到的標記。"""
    put_site_object(
        bucket,
        site_version_key(slug, NEW_GENERATION),
        render_version_page(slug, NEW_GENERATION, published=True),
    )
    put_site_object(bucket, tutorial_index_key(slug), render_index_page(slug, NEW_GENERATION))


def rollback_site(slugs: Sequence[str], *, bucket: str) -> None:
    """事後刪除公開頁並把索引改回舊版；這**不會**收回已經被讀出去的內容。"""
    for slug in slugs:
        delete_object(bucket, site_version_key(slug, NEW_GENERATION))
        put_site_object(bucket, tutorial_index_key(slug), render_index_page(slug, OLD_GENERATION))


def read_exposed_bodies(slugs: Sequence[str], *, bucket: str) -> tuple[str, ...]:
    """此刻真的能從公開前綴 GET 回來、而且屬於新世代的內容；每一筆都是一次實際 S3 GET。"""
    bodies: list[str] = []
    for slug in slugs:
        for key in (tutorial_index_key(slug), site_version_key(slug, NEW_GENERATION)):
            body = get_object(bucket, key)
            if body is not None and site_generation(body) == NEW_GENERATION:
                bodies.append(body.decode())
    return tuple(bodies)


def run_cut_point(point: O3CutPoint, *, table: str, bucket: str) -> CutPointResult:
    """四步固定流程：建立全舊初始狀態 -> 執行到注入點 -> 立刻觀察並記曝光 -> 回傳一列結果。

    注入用的是「執行到這裡就停」的旗標，不用 `sleep`；停下來之後不做任何補救，
    觀察到的就是真的中斷當下對外看得到的狀態。
    """
    reset_to_old_generation(SLUGS, table=table, bucket=bucket)
    stage_private_artifacts(SLUGS, bucket=bucket, operation_id=f"o3-{point}")

    if point == "b1_after_site_before_transact":
        # 協定 B（先曝光）：site/ 先寫完，交易還沒做就中斷。
        for slug in SLUGS:
            promote_site(slug, bucket=bucket)
    elif point != "a1_before_transact":
        # 協定 A（設計 §8.3 建議）：先交易，再逐篇換公開頁。
        publish_transaction(SLUGS, table=table, stamp=to_iso(now_utc()))
        if point == "a3_after_first_site_before_second":
            promote_site(SLUGS[0], bucket=bucket)
        elif point == "c1_after_delete_site":
            for slug in SLUGS:
                promote_site(slug, bucket=bucket)

    # 曝光一定在任何回復動作之前讀：事後刪除收不回已經讀到的東西。
    exposed = read_exposed_bodies(SLUGS, bucket=bucket)
    if point == "c1_after_delete_site":
        rollback_site(SLUGS, bucket=bucket)

    views = observe(SLUGS, table=table, bucket=bucket)
    partial = is_partial(views, expected=EXPECTED_GENERATION[point])
    return CutPointResult(point, views, exposed, partial, CUT_POINT_NOTES[point])


# --- 6. O3 報告與 FAIL 出口 --------------------------------------------------

HEADER = "| 切點 | DynamoDB | site | partial | 曝光筆數 | 說明 |\n|---|---|---|---|---|---|\n"

# 00A §4.2 的 O3 停止語句，逐字採用。
O3_STOP_SENTENCE = (
    "O3 尚未 PASS，公開發布路徑保留 FAIL；不得用未連結 URL 充當私有，不得放寬 F49。"
)

BLOCKED_PHASES: tuple[str, ...] = (
    "Phase 24 單篇教學發布提交",
    "Phase 25 多篇教學整批發布",
    "Phase 41 Ticket Analysis 雲端流程驗收",
    "Phase 48 Feedback Review 排程流程",
    "Phase 52 Release RETIRE 與流程驗收",
    "Phase 57 S3 靜態教學站與回饋下載",
)

# 三個出口都不新增服務與公開讀取 API，也不改寫 F49；選哪一個由維護者決定。
DECISION_EXITS: tuple[tuple[str, str], ...] = (
    (
        "出口 1：縮限公開範圍",
        "只允許單篇發布，明示公開頁可能短暫落後於指標。這不解決 "
        "`a2_after_transact_before_site`，只縮小影響面；多篇路徑維持阻擋。",
    ),
    (
        "出口 2：公開世代改由單一 S3 物件決定",
        "讓 `site/` 的目前版本由一個 manifest 物件切換，多篇提交變成換一個 key。代價是靜態站要靠"
        "瀏覽器端自己讀 manifest 才知道該顯示哪一版，而 DynamoDB 與 S3 仍是兩個 store，"
        "`a2_after_transact_before_site`／`b1_after_site_before_transact` 切點照舊存在。",
    ),
    (
        "出口 3：接受 FAIL",
        "公開站停用，Demo 只展示私有預覽與報告。",
    ),
)


def o3_verdict(results: Sequence[CutPointResult]) -> Literal["PASS", "FAIL"]:
    """任一切點看得到 partial 就是 FAIL；沒有觀察值不算 PASS（由呼叫端保證五列齊全）。"""
    return "FAIL" if any(row.partial_visible for row in results) else "PASS"


def _transaction_arithmetic() -> str:
    return (
        "## 交易限制換算\n\n"
        f"- `TransactWriteItems` 一次最多 {MAX_TRANSACT_ACTIONS} 個動作、總量 4 MB，"
        "且同一個 item 不可在同一筆交易出現兩次。\n"
        f"- 本案每篇發布固定動 `TUTORIAL#<slug>` 與 `VERSION#<slug>@v<n>` 兩個 item"
        f"（{ACTIONS_PER_VERSION} 個動作），所以單次交易最多 "
        f"{MAX_TRANSACT_ACTIONS} / {ACTIONS_PER_VERSION} = {MAX_BATCH_VERSIONS} 篇；"
        f"這就是 Phase 25 的 `MAX_BATCH_VERSIONS = {MAX_BATCH_VERSIONS}`。\n"
        "- 超過就必須拆成多筆交易，中途失敗的 partial 視窗再增加一層；拆交易等於放棄全有或全無，"
        "所以 Phase 25 直接丟 `PublishError` 而不是拆。\n"
        "- S3 那側沒有等價機制：`PutObject` 只有單物件層級的條件寫入"
        "（`If-None-Match: *` 已存在回 `412 Precondition Failed`，併發刪除時可能回 "
        "`409 Conflict`），不存在跨物件原子切換。\n"
    )


def _fail_tail() -> str:
    exits = "".join(
        f"- **{name}（尚未核定）。** {detail}\n" for name, detail in DECISION_EXITS
    )
    blocked = "".join(f"- {phase}\n" for phase in BLOCKED_PHASES)
    return (
        "\n## 停止語句\n\n"
        f"{O3_STOP_SENTENCE}\n"
        "\n## 阻擋的公開路徑\n\n"
        f"{blocked}"
        "\nPhase 59 仍可執行，但它的切點 4（交易後、寫 `site/` 前）只能記成「補償有效」並標為 "
        "**O3 缺口**，不得寫成「發布故障驗收通過」。\n"
        "\n## 決策出口（每一個都仍未核定，選定後要重跑同一組五個切點）\n\n"
        f"{exits}"
    )


def render_o3_report(
    results: Sequence[CutPointResult], *, run_id: str,
    table: str, bucket: str, region: str,
) -> str:
    """O3 報告：六欄觀察值 ＋ 交易換算 ＋ 判定；FAIL 時附停止語句、阻擋清單與三個出口。"""
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
    head = (
        f"# O3 報告 {run_id}\n\n"
        f"Region：{region}｜表：{table}｜bucket：{bucket}｜run id：{run_id}\n\n"
    )
    body = f"{head}{HEADER}{rows}\n{tail}\n\n{_transaction_arithmetic()}"
    return body + (_fail_tail() if verdict == "FAIL" else "")


# --- 7. 隔離的 spike 資源與命令列 --------------------------------------------

# 隔離資源只為這一次 spike 存在，跑完一定刪掉；正式表與正式內容 bucket 完全不碰。
SPIKE_TABLE_PREFIX = "training_kb_o3_"
SPIKE_BUCKET_PREFIX = "training-kb-o3-"
EVIDENCE_PREFIX = f"{PRIVATE_OPERATIONS_PREFIX}o3/"
REPORT_DIR = Path(__file__).resolve().parents[2] / "docs" / "plan" / "report"


def spike_table_name(run_id: str) -> str:
    return f"{SPIKE_TABLE_PREFIX}{run_id}"


def spike_bucket_name(run_id: str, account_suffix: str) -> str:
    return f"{SPIKE_BUCKET_PREFIX}{run_id}-{account_suffix}"


def account_suffix() -> str:
    """bucket 名稱要全域唯一，補帳號後六碼；報告不寫完整帳號以外的敏感值。"""
    region = spike_region()
    sts = boto3.client("sts", region_name=region, config=SDK_CONFIG)
    account: str = sts.get_caller_identity()["Account"]
    return account[-6:]


def evidence_key(run_id: str) -> str:
    """gate 證據固定在私有前綴 `operations/o3/<run_id>.json`（00A §3.4）。"""
    return f"{EVIDENCE_PREFIX}{run_id}.json"


def create_spike_resources(run_id: str) -> tuple[str, str]:
    """建立隔離的測試表與測試 bucket：PAY_PER_REQUEST、Block Public Access 全開、無公開 policy。"""
    table, bucket = spike_table_name(run_id), spike_bucket_name(run_id, account_suffix())
    dynamodb_client().create_table(
        TableName=table,
        KeySchema=[
            {"AttributeName": "PK", "KeyType": "HASH"},
            {"AttributeName": "SK", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "PK", "AttributeType": "S"},
            {"AttributeName": "SK", "AttributeType": "S"},
        ],
        BillingMode="PAY_PER_REQUEST",
    )
    dynamodb_client().get_waiter("table_exists").wait(TableName=table)
    region = spike_region()
    if region == "us-east-1":
        s3_client().create_bucket(Bucket=bucket)
    else:
        s3_client().create_bucket(
            Bucket=bucket, CreateBucketConfiguration={"LocationConstraint": region}
        )
    s3_client().get_waiter("bucket_exists").wait(Bucket=bucket)
    # 「公開切換」在 spike 裡只用 site/ 前綴的 key 存在與否來觀察，不真的開放公開讀取。
    s3_client().put_public_access_block(
        Bucket=bucket,
        PublicAccessBlockConfiguration={
            "BlockPublicAcls": True,
            "IgnorePublicAcls": True,
            "BlockPublicPolicy": True,
            "RestrictPublicBuckets": True,
        },
    )
    return table, bucket


def empty_bucket(bucket: str) -> int:
    """刪 bucket 之前先清空；回傳刪掉的物件數，報告要記這個數字。"""
    removed = 0
    paginator = s3_client().get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket):
        keys = [{"Key": row["Key"]} for row in page.get("Contents", ())]
        if keys:
            s3_client().delete_objects(Bucket=bucket, Delete={"Objects": keys})
            removed += len(keys)
    return removed


def delete_spike_resources(table: str, bucket: str) -> int:
    removed = empty_bucket(bucket)
    s3_client().delete_bucket(Bucket=bucket)
    dynamodb_client().delete_table(TableName=table)
    dynamodb_client().get_waiter("table_not_exists").wait(TableName=table)
    return removed


def evidence_payload(
    results: Sequence[CutPointResult], *, run_id: str,
    table: str, bucket: str, region: str, started_at: str,
) -> dict[str, Any]:
    """原始觀察值；報告是給人看的摘要，這份 JSON 是逐欄位的證據。"""
    return {
        "run_id": run_id,
        "gate": "O3",
        "region": region,
        "table": table,
        "bucket": bucket,
        "started_at": started_at,
        "finished_at": to_iso(now_utc()),
        "verdict": o3_verdict(results),
        "max_batch_versions": MAX_BATCH_VERSIONS,
        "cut_points": [
            {
                "cut_point": row.cut_point,
                "expected": EXPECTED_GENERATION[row.cut_point],
                "partial_visible": row.partial_visible,
                "note": row.note,
                "views": [asdict(view) for view in row.views],
                "exposed_bodies": list(row.exposed_bodies),
            }
            for row in results
        ],
    }


def put_evidence(payload: Mapping[str, Any], *, bucket: str, run_id: str) -> bytes:
    """把證據寫進私有 `operations/o3/<run_id>.json` 再讀回來核對，確認真的存進去了。"""
    body = json.dumps(payload, ensure_ascii=False, indent=2).encode()
    s3_client().put_object(
        Bucket=bucket, Key=evidence_key(run_id), Body=body, ContentType="application/json"
    )
    stored = get_object(bucket, evidence_key(run_id))
    if stored != body:
        raise RuntimeError(f"證據寫入後讀回不一致：{evidence_key(run_id)}")
    return body


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="O3 發布切換切點 spike 與報告（gate 用）")
    parser.add_argument(
        "--region", default=None, help=f"預設讀 {REGION_ENV}，再退到 {DEFAULT_REGION}"
    )
    parser.add_argument("--run-id", default=None, help="報告檔名與資源名的 run id，預設 UTC 時間戳")
    parser.add_argument("--report-dir", default=None, help=f"報告輸出目錄，預設 {REPORT_DIR}")
    parser.add_argument(
        "--provision", action="store_true", help="只建立隔離資源並印出環境變數，不跑切點"
    )
    parser.add_argument("--teardown", action="store_true", help="只刪除隔離資源")
    parser.add_argument("--keep", action="store_true", help="跑完不刪隔離資源（預設會刪）")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """全程跑完回 0（PASS）或 2（FAIL）；FAIL 是本 gate 允許的結論之一，不是腳本崩潰。"""
    args = build_parser().parse_args(argv)
    if args.region:
        os.environ[REGION_ENV] = str(args.region)
    region = spike_region()
    started_at = to_iso(now_utc())
    stamp_id = started_at.replace(":", "").replace("-", "").lower()
    run_id = str(args.run_id) if args.run_id else stamp_id

    if args.teardown:
        table, bucket = spike_table_name(run_id), spike_bucket_name(run_id, account_suffix())
        print(f"已刪除 {table} 與 {bucket}（清掉 {delete_spike_resources(table, bucket)} 個物件）")
        return 0

    table, bucket = create_spike_resources(run_id)
    print(f"已建立隔離資源（{to_iso(now_utc())}）：{table} / {bucket}")
    if args.provision:
        print(f"TKB_TABLE_NAME={table}\nTKB_CONTENT_BUCKET={bucket}\n{REGION_ENV}={region}")
        return 0

    try:
        results = [run_cut_point(point, table=table, bucket=bucket) for point in CUT_POINTS]
        report = render_o3_report(
            results, run_id=run_id, table=table, bucket=bucket, region=region
        )
        payload = evidence_payload(
            results, run_id=run_id, table=table, bucket=bucket,
            region=region, started_at=started_at,
        )
        put_evidence(payload, bucket=bucket, run_id=run_id)
        report_dir = Path(args.report_dir) if args.report_dir else REPORT_DIR
        report_dir.mkdir(parents=True, exist_ok=True)
        report_path = report_dir / f"o3-{run_id}.md"
        report_path.write_text(report, encoding="utf-8")
        print(report)
        print(f"報告：{report_path}")
        print(f"證據：s3://{bucket}/{evidence_key(run_id)}")
    finally:
        if not args.keep:
            removed = delete_spike_resources(table, bucket)
            print(
                f"已刪除隔離資源（{to_iso(now_utc())}）：{table} / {bucket}，"
                f"清掉 {removed} 個物件"
            )
    return 2 if o3_verdict(results) == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover - 命令列進入點
    raise SystemExit(main())
