"""Phase 07：S3 物件的條件寫入與讀取。

跑在 moto 的本機 bucket 上：證明「同一個 key 不會被盲目覆寫」這條規則的程式邏輯，
**不**證明真實 S3 行為（真實證據待 Phase 09 之後另外保留）。
第二次 `put_object` 同時是 moto 的器材能力探針：moto 若還沒實作 `IfNoneMatch`
（getmoto/moto#8091）這條會綠給假象，正確處理是升級 moto，不是刪掉斷言。
所有 key 一律落在私有前綴（`tutorials/`、`operations/`、`stepfunctions/`），沒有 `site/`。
"""

from types import SimpleNamespace

import pytest
from botocore.exceptions import ClientError

from training_kb.errors import ObjectAlreadyExists, PermanentError, TransientError
from training_kb.repository import Repository

PRIVATE_PREFIXES = ("tutorials/", "operations/", "stepfunctions/", "demo/previews/")
"""00A §3.4 的四個私有前綴；只是本地核對清單，真正的公開範圍由 bucket policy 決定。"""


def test_put_object_refuses_to_overwrite_same_key(repository) -> None:
    key = "tutorials/prepare-meeting/v1.md"
    repository.put_object(key, b"# Prepare Meeting", "text/markdown", if_none_match=True)
    with pytest.raises(ObjectAlreadyExists, match="already exists"):
        repository.put_object(key, b"# changed", "text/markdown", if_none_match=True)
    assert issubclass(ObjectAlreadyExists, PermanentError)
    assert repository.get_object(key) == b"# Prepare Meeting"
    assert repository.object_exists(key) is True
    assert repository.get_object("tutorials/prepare-meeting/v2.md") is None
    assert repository.object_exists("tutorials/prepare-meeting/v2.md") is False


def test_put_object_sends_only_documented_parameters() -> None:
    """固定證據：沒有 `ACL`、沒有 `public-read`、沒有多餘欄位（00A §3.8）。"""
    calls: list[dict[str, object]] = []
    bucket = SimpleNamespace(put_object=lambda **kwargs: calls.append(kwargs))
    repository = Repository(table=None, bucket=bucket)
    repository.put_object("operations/op-1/input.json", b"{}", "application/json",
                          if_none_match=True)
    assert calls == [{
        "Key": "operations/op-1/input.json", "Body": b"{}",
        "ContentType": "application/json", "IfNoneMatch": "*",
    }]


def test_s3_methods_without_bucket_fail_clearly() -> None:
    """忘了給 bucket 要是看得懂的 `PermanentError`，不是 `AttributeError: 'NoneType'...`。"""
    repository = Repository(table=None)
    key = "tutorials/prepare-meeting/v1.md"
    with pytest.raises(PermanentError, match="bucket"):
        repository.put_object(key, b"x", "text/markdown", if_none_match=True)
    with pytest.raises(PermanentError, match="bucket"):
        repository.get_object(key)
    with pytest.raises(PermanentError, match="bucket"):
        repository.object_exists(key)


def test_identical_retry_is_treated_as_done(repository) -> None:
    """Phase 22 `put_private_artifact` 的最小原型：412 + bytes 相同 = 本次已完成，不重寫。"""
    key = "operations/op-ticket-t_881/input.json"
    body = b'{"ticket_id": "t_881"}'
    repository.put_object(key, body, "application/json", if_none_match=True)
    already_done = False
    try:
        repository.put_object(key, body, "application/json", if_none_match=True)
    except ObjectAlreadyExists:
        already_done = repository.get_object(key) == body
    assert already_done is True


def test_every_written_key_stays_in_a_private_prefix(repository, bucket) -> None:
    """人工驗收自動化：本 Phase 寫的 key 一律落在私有前綴，沒有任何 `site/`（00A §3.4、§3.8）。"""
    for key, content_type in (
        ("tutorials/prepare-meeting/v1.md", "text/markdown"),
        ("operations/op-ticket-t_881/input.json", "application/json"),
        ("stepfunctions/ticket-analysis/v1.json", "application/json"),
    ):
        repository.put_object(key, b"{}", content_type, if_none_match=True)
    keys = [stored.key for stored in bucket.objects.all()]
    assert len(keys) == 3
    assert all(key.startswith(PRIVATE_PREFIXES) for key in keys)
    assert not any(key.startswith("site/") for key in keys)


def test_conflict_is_transient_and_other_client_errors_are_not_swallowed() -> None:
    """409 轉 `TransientError` 交 ASL Retry（這裡不自己迴圈）；其餘 `ClientError` 一律往外丟。"""
    def fail_with(code: str):
        def put_object(**kwargs: object) -> None:
            raise ClientError({"Error": {"Code": code, "Message": code}}, "PutObject")
        return put_object

    conflicted = Repository(table=None, bucket=SimpleNamespace(put_object=fail_with(
        "ConditionalRequestConflict")))
    with pytest.raises(TransientError, match="conflicted"):
        conflicted.put_object("operations/op-1/input.json", b"{}", "application/json",
                              if_none_match=True)
    denied = Repository(table=None, bucket=SimpleNamespace(put_object=fail_with("AccessDenied")))
    with pytest.raises(ClientError):
        denied.put_object("operations/op-1/input.json", b"{}", "application/json",
                          if_none_match=True)
