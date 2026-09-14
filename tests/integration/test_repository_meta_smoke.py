"""Phase 06：實表 metadata smoke。moto 的 PASS 不能代替它（O1 追驗）。

整支標 `aws`；未設 `TKB_RUN_AWS_INTEGRATION=1` 時由 tests/conftest.py 自動跳過。
它寫的是正式 `training_kb` 表，所以 `feature_id` 一定帶 `smoke-` 前綴與隨機碼，
並在 `finally` 清掉。用維護者本人的憑證跑，不用 Phase 09 的資料角色
（那個角色刻意不含 `dynamodb:DeleteItem`）；真的被拒就把殘留 item 記進報告由人工刪，
**不得**為了讓測試過而放寬 IAM。
"""

import os
from datetime import UTC, datetime
from uuid import uuid4

import boto3
import pytest

from training_kb.models import Feature
from training_kb.repository import Repository


@pytest.mark.aws
def test_real_table_metadata_round_trip() -> None:
    table = boto3.resource(
        "dynamodb", region_name=os.environ["TKB_AWS_REGION"]
    ).Table(os.environ["TKB_TABLE_NAME"])
    repository = Repository(table)
    feature_id = f"smoke-{uuid4().hex}"
    item = Feature(feature_id=feature_id, name=feature_id, aliases=[],
                   first_seen=datetime(2026, 8, 1, tzinfo=UTC))
    try:
        repository.put_meta(item)
        assert repository.get_feature(feature_id) == item
        assert repository.revision_of(f"FEATURE#{feature_id}") == 1
    finally:
        table.delete_item(Key={"PK": f"FEATURE#{feature_id}", "SK": "META"})
