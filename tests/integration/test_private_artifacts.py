"""未發布產物只能以條件寫入落在私有前綴 `tutorials/`（Phase 22）。

跑在 moto 的本機 bucket 上（`repository` fixture 來自 `tests/integration/conftest.py`）：
**第二次 `put_private_artifact` 同時是器材能力探針**——moto 若還沒實作 `IfNoneMatch`
（getmoto/moto#8091），`ObjectAlreadyExists` 不會丟出，「同 key 不同內容」會安靜地變成
覆寫舊產物。正確處理是升級 moto 並把版本記進報告，不是改成「先查存在再寫」的假條件。
moto PASS 只代表本機模擬，O3 發布切點仍未通過。
"""

import pytest

from training_kb.content import diff_key, markdown_key, put_private_artifact
from training_kb.errors import ContentError, PermanentError
from training_kb.repository import Repository

SLUG = "prepare-meeting"
MARKDOWN_TYPE = "text/markdown; charset=utf-8"
DIFF_TYPE = "text/plain; charset=utf-8"


def test_private_artifact_is_written_once(repository: Repository) -> None:
    key = markdown_key(SLUG, 2)
    put_private_artifact(repository, key, "# 準備會議\n", MARKDOWN_TYPE)
    assert repository.get_object(key) == "# 準備會議\n".encode()


def test_public_prefix_refused(repository: Repository) -> None:
    with pytest.raises(ContentError, match="私有前綴"):
        put_private_artifact(repository, "site/prepare-meeting/v2.md", "x", MARKDOWN_TYPE)
    assert repository.get_object("site/prepare-meeting/v2.md") is None


def test_public_site_copy_of_a_private_key_is_refused(repository: Repository) -> None:
    """`site/tutorials/<slug>/v<n>.html` 也是公開 key，不能因為裡面有 `tutorials/` 就放行。"""
    key = "site/" + markdown_key(SLUG, 2)
    with pytest.raises(ContentError, match="私有前綴"):
        put_private_artifact(repository, key, "x", MARKDOWN_TYPE)
    assert repository.get_object(key) is None


def test_same_key_same_content_is_idempotent(repository: Repository) -> None:
    key = markdown_key(SLUG, 2)
    put_private_artifact(repository, key, "# 準備會議\n", MARKDOWN_TYPE)
    put_private_artifact(repository, key, "# 準備會議\n", MARKDOWN_TYPE)
    with pytest.raises(ContentError, match="內容不同"):
        put_private_artifact(repository, key, "# 別的\n", MARKDOWN_TYPE)
    assert repository.get_object(key) == "# 準備會議\n".encode()


def test_first_version_diff_is_written_as_empty_object(repository: Repository) -> None:
    """v1 的 diff 是 0 位元組，但檔案要存在（F50 選 C）；重送一樣冪等。"""
    key = diff_key(SLUG, 1)
    put_private_artifact(repository, key, "", DIFF_TYPE)
    put_private_artifact(repository, key, "", DIFF_TYPE)
    assert repository.get_object(key) == b""


def test_other_permanent_errors_are_not_swallowed(table: object) -> None:
    """只攔 `ObjectAlreadyExists`：沒設定 bucket 是設定錯誤，不是「同操作重送」。"""
    repository = Repository(table)
    with pytest.raises(PermanentError) as caught:
        put_private_artifact(repository, markdown_key(SLUG, 1), "# 準備會議\n", MARKDOWN_TYPE)
    assert not isinstance(caught.value, ContentError)
