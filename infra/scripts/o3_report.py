"""O3 gate 的一次性 spike：把「跨 DynamoDB 與 S3 的發布切換」五個失敗切點各跑一次。

這支腳本不是 `Publisher`，也不進 Lambda runtime。它只驗**協定**：用 boto3 client 的
`transact_write_items`（DynamoDB 端的原子提交）加上 S3 `PutObject`（沒有跨物件原子切換），
在每個切點立刻觀察「公開站顯示的版本」與「DynamoDB 的 current_version」，看對外是不是
只會見到整批舊或整批新（設計 §8.3、§18 O3；F36／F37／F49）。

`Repository.transact_write` 是 Phase 24 才有的方法，此時不存在，所以這裡直接用 boto3
client；報告要註明驗的是協定，不是 `Publisher` 的實作。
"""

import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

import boto3
from botocore.config import Config

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
