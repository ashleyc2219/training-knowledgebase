"""Phase 07：S3 物件的條件寫入與讀取。

跑在 moto 的本機 bucket 上：證明「同一個 key 不會被盲目覆寫」這條規則的程式邏輯，
**不**證明真實 S3 行為（真實證據待 Phase 09 之後另外保留）。
第二次 `put_object` 同時是 moto 的器材能力探針：moto 若還沒實作 `IfNoneMatch`
（getmoto/moto#8091）這條會綠給假象，正確處理是升級 moto，不是刪掉斷言。
所有 key 一律落在私有前綴（`tutorials/`、`operations/`、`stepfunctions/`），沒有 `site/`。
"""

import pytest

from training_kb.errors import ObjectAlreadyExists, PermanentError


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
