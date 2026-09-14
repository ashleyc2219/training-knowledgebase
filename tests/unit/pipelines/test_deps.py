"""Phase 38 Task 1：`Deps` 帶得動 repository／writer／settings，缺相依時明確失敗。"""

import pytest

from training_kb.errors import PermanentError
from training_kb.pipelines.common import Deps


def test_deps_keeps_old_construction(fake_operations, fake_clock):
    """Phase 29 既有的兩參數建構方式不能壞（三個新欄位都有預設 `None`）。"""
    legacy = Deps(operations=fake_operations, now=fake_clock)
    assert legacy.repository is None
    with pytest.raises(PermanentError, match="repository"):
        legacy.need_repository()


def test_deps_returns_wired_dependencies(
        fake_operations, fake_clock, fake_repo, embedding_writer, settings):
    deps = Deps(fake_operations, fake_clock,
                repository=fake_repo, writer=embedding_writer, settings=settings)
    assert deps.need_repository() is fake_repo
    assert deps.need_writer() is embedding_writer
    assert deps.need_settings() is settings


def test_missing_writer_and_settings_fail_with_their_own_message(fake_operations, fake_clock):
    """三個 helper 各有各的訊息，不是共用一句看不出缺什麼的錯誤。"""
    bare = Deps(operations=fake_operations, now=fake_clock)
    assert bare.writer is None
    assert bare.settings is None
    with pytest.raises(PermanentError, match="writer"):
        bare.need_writer()
    with pytest.raises(PermanentError, match="settings"):
        bare.need_settings()
