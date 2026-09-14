"""O3 gate 的真實 AWS 切點觀察：五個提交切點各跑一次，全部標 `@pytest.mark.aws`。

`live_table`／`live_bucket` 讀的是**隔離的 spike 測試資源**（`infra/scripts/o3_report.py
--provision` 建的那一組），不是正式表與正式內容 bucket；沒設環境變數就 skip。
"""

import os
import sys
from collections.abc import Iterator
from pathlib import Path

import boto3
import pytest

from training_kb.errors import ObjectAlreadyExists
from training_kb.repository import Repository

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "infra" / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from o3_report import (  # noqa: E402
    PUBLIC_SITE_PREFIX,
    SLUGS,
    is_partial,
    observe,
    reset_to_old_generation,
    run_cut_point,
    site_version_key,
    spike_region,
)

CUT_POINTS = (
    "a1_before_transact",
    "a2_after_transact_before_site",
    "a3_after_first_site_before_second",
    "b1_after_site_before_transact",
    "c1_after_delete_site",
)

TABLE_ENV = "TKB_TABLE_NAME"
BUCKET_ENV = "TKB_CONTENT_BUCKET"


@pytest.fixture
def live_table() -> str:
    name = os.environ.get(TABLE_ENV)
    if not name:
        pytest.skip(f"需要隔離的 spike 測試表；設 {TABLE_ENV}=training_kb_o3_<run_id>")
    return name


@pytest.fixture
def live_bucket() -> str:
    name = os.environ.get(BUCKET_ENV)
    if not name:
        pytest.skip(f"需要隔離的 spike 測試 bucket；設 {BUCKET_ENV}=training-kb-o3-<run_id>-<帳號>")
    return name


@pytest.mark.aws
def test_every_cut_point_is_observed(live_table: str, live_bucket: str) -> None:
    results = [run_cut_point(point, table=live_table, bucket=live_bucket) for point in CUT_POINTS]
    assert [row.cut_point for row in results] == list(CUT_POINTS)
    rollback = results[-1]
    assert rollback.exposed_bodies != ()


@pytest.mark.aws
def test_first_cut_point_shows_only_the_old_generation(live_table: str, live_bucket: str) -> None:
    """Happy 路徑：交易之前中斷，兩篇都還是 v1，私有 staging 不對外（F36）。"""
    result = run_cut_point("a1_before_transact", table=live_table, bucket=live_bucket)
    assert result.partial_visible is False
    assert {view.site_version for view in result.views} == {"v1"}
    assert {view.current_version for view in result.views} == {"v1"}
    assert result.exposed_bodies == ()


@pytest.mark.aws
def test_pointer_moves_before_public_page(live_table: str, live_bucket: str) -> None:
    """交易後、寫 site 前：指標已新、公開頁仍舊，違反 F37。"""
    result = run_cut_point("a2_after_transact_before_site", table=live_table, bucket=live_bucket)
    assert result.partial_visible is True
    assert {view.current_version for view in result.views} == {"v2"}
    assert {view.site_version for view in result.views} == {"v1"}
    assert all(view.published_at for view in result.views)


@pytest.mark.aws
def test_batch_cut_point_shows_one_new_one_old(live_table: str, live_bucket: str) -> None:
    """多篇整批：A 新 B 舊，不能宣稱整次沒有發布（F49）。"""
    result = run_cut_point(
        "a3_after_first_site_before_second", table=live_table, bucket=live_bucket
    )
    assert result.partial_visible is True
    assert [view.site_version for view in result.views] == ["v2", "v1"]
    assert [view.current_version for view in result.views] == ["v2", "v2"]


@pytest.mark.aws
def test_site_first_order_exposes_unpublished_content(live_table: str, live_bucket: str) -> None:
    """先寫 site 後交易：未發布內容已公開，違反 F36。"""
    result = run_cut_point("b1_after_site_before_transact", table=live_table, bucket=live_bucket)
    assert result.partial_visible is True
    assert {view.site_version for view in result.views} == {"v2"}
    assert {view.current_version for view in result.views} == {"v1"}
    assert result.exposed_bodies != ()


@pytest.mark.aws
def test_deleting_the_public_page_does_not_undo_exposure(
    live_table: str, live_bucket: str
) -> None:
    """事後刪除公開頁：site 回復舊版，但 `exposed_bodies` 仍留著已被讀出的新內容。"""
    result = run_cut_point("c1_after_delete_site", table=live_table, bucket=live_bucket)
    assert result.partial_visible is True
    assert {view.site_version for view in result.views} == {"v1"}
    assert {view.current_version for view in result.views} == {"v2"}
    assert any('data-site-version="v2"' in body for body in result.exposed_bodies)


@pytest.mark.aws
def test_conditional_write_refuses_to_overwrite_the_same_key(live_bucket: str) -> None:
    """驗收矩陣邊界：同 key 以 `If-None-Match: *` 重寫，S3 回 412 -> `ObjectAlreadyExists`。"""
    bucket = boto3.resource("s3", region_name=spike_region()).Bucket(live_bucket)
    repository = Repository(None, bucket)
    key = site_version_key("spike-a", "v2")
    boto3.client("s3", region_name=spike_region()).delete_object(Bucket=live_bucket, Key=key)
    repository.put_object(key, b"first", "text/html; charset=utf-8", if_none_match=True)
    with pytest.raises(ObjectAlreadyExists):
        repository.put_object(key, b"second", "text/html; charset=utf-8", if_none_match=True)
    assert repository.get_object(key) == b"first"


@pytest.mark.aws
def test_public_prefix_never_holds_an_unpublished_page(live_table: str, live_bucket: str) -> None:
    """00A §3.8：`published_at is None` 的頁面只能在私有 staging，`site/` 掃到就失敗。"""
    run_cut_point("a3_after_first_site_before_second", table=live_table, bucket=live_bucket)
    listed = boto3.client("s3", region_name=spike_region()).list_objects_v2(
        Bucket=live_bucket, Prefix=PUBLIC_SITE_PREFIX
    )
    keys = [row["Key"] for row in listed.get("Contents", ())]
    assert keys
    for key in keys:
        body = boto3.client("s3", region_name=spike_region()).get_object(
            Bucket=live_bucket, Key=key
        )["Body"].read()
        assert b'data-published="false"' not in body


@pytest.fixture(autouse=True)
def restore_old_generation(request: pytest.FixtureRequest) -> Iterator[None]:
    """每個 aws 測試跑完都把兩篇回復成全舊，下一個切點從乾淨狀態開始。"""
    yield
    table, bucket = os.environ.get(TABLE_ENV), os.environ.get(BUCKET_ENV)
    if table and bucket and "aws" in request.keywords:
        reset_to_old_generation(SLUGS, table=table, bucket=bucket)
        assert is_partial(observe(SLUGS, table=table, bucket=bucket), expected="v1") is False
