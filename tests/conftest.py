"""全套測試共用設定。目前只做一件事：沒有 AWS 憑證時跳過 aws 測試。"""

import os

import pytest

RUN_AWS_ENV = "TKB_RUN_AWS_INTEGRATION"


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """未開啟真實 AWS 整合測試時，替所有標了 aws 的測試補上 skip。"""
    if os.environ.get(RUN_AWS_ENV) == "1":
        return
    skip_aws = pytest.mark.skip(reason=f"需要真實 AWS 帳號；設 {RUN_AWS_ENV}=1 才執行")
    for item in items:
        if "aws" in item.keywords:
            item.add_marker(skip_aws)
