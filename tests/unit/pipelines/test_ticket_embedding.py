"""Phase 38 Task 2：缺向量才呼叫 Titan，重送不重算，例外時一個字都不寫。

這裡綠燈只證明**分支邏輯**正確。O5（模型與參數驗證）未通過前，真實 Titan 呼叫維持
BLOCKED，假向量的綠燈不得被說成「Titan 已驗證」。
"""

import pytest

from training_kb.errors import PermanentError, TransientError
from training_kb.keys import ticket_pk
from training_kb.pipelines.ticket import ensure_embedding

OPERATION_ID = "op-ticket-t_881"


def test_ensure_embedding_calls_model_once_and_persists(
        fake_repo, embedding_writer, ticket_without_embedding):
    embedding_writer.embedding = [0.1] * 1024
    ticket = fake_repo.save_ticket(ticket_without_embedding("t_881"))
    kw = {"writer": embedding_writer, "repository": fake_repo, "operation_id": OPERATION_ID}
    first, second = ensure_embedding(ticket, **kw), ensure_embedding(ticket, **kw)
    assert len(first.embedding) == 1024
    assert second.embedding == first.embedding
    assert embedding_writer.embed_calls == 1
    assert fake_repo.loaded(ticket_pk("t_881")).embedding == first.embedding


def test_stored_embedding_wins_over_the_passed_object(
        fake_repo, embedding_writer, ticket_without_embedding, unclustered):
    """資料庫已有向量、傳入物件沒有：以資料庫為準，模型 0 次。"""
    stored = fake_repo.save_ticket(unclustered("t_881", [0.5] * 1024))
    result = ensure_embedding(ticket_without_embedding("t_881"), writer=embedding_writer,
                              repository=fake_repo, operation_id=OPERATION_ID)
    assert result.embedding == stored.embedding
    assert embedding_writer.embed_calls == 0


def test_permanent_embed_error_writes_nothing(
        fake_repo, embedding_writer, ticket_without_embedding):
    """維度／NaN／bool 由 Phase 16 的 `Writer.embed` 判掉；本函式原樣往上拋、不寫回。"""
    embedding_writer.error = PermanentError("expected 1024 dimensions, got 1023")
    ticket = fake_repo.save_ticket(ticket_without_embedding("t_881"))
    with pytest.raises(PermanentError, match="1023"):
        ensure_embedding(ticket, writer=embedding_writer, repository=fake_repo,
                         operation_id=OPERATION_ID)
    assert embedding_writer.embed_calls == 1
    assert fake_repo.loaded(ticket_pk("t_881")).embedding is None


def test_transient_embed_error_is_reraised_without_local_retry(
        fake_repo, embedding_writer, ticket_without_embedding):
    """暫時性故障交給 ASL 的 Retry，函式內不自行重試（只會看到一次呼叫）。"""
    embedding_writer.error = TransientError("bedrock throttling")
    ticket = fake_repo.save_ticket(ticket_without_embedding("t_881"))
    with pytest.raises(TransientError):
        ensure_embedding(ticket, writer=embedding_writer, repository=fake_repo,
                         operation_id=OPERATION_ID)
    assert embedding_writer.embed_calls == 1
    assert fake_repo.loaded(ticket_pk("t_881")).embedding is None


def test_embed_is_called_with_the_ticket_text_and_the_fixed_node(
        fake_repo, embedding_writer, ticket_without_embedding):
    """節點名固定是 `ticket-embedding`，`operation_id` 原樣傳下去（`CallTrace` 靠它核對）。"""
    ticket = fake_repo.save_ticket(ticket_without_embedding("t_881"))
    ensure_embedding(ticket, writer=embedding_writer, repository=fake_repo,
                     operation_id=OPERATION_ID)
    assert embedding_writer.calls == [
        {"text": ticket.text, "operation_id": OPERATION_ID, "node": "ticket-embedding"}]


def test_writeback_only_touches_the_embedding_field(
        fake_repo, embedding_writer, ticket_without_embedding):
    """回填只動模型欄位：其餘欄位與原本那筆逐欄相同（00A D-40）。"""
    ticket = fake_repo.save_ticket(ticket_without_embedding("t_881"))
    updated = ensure_embedding(ticket, writer=embedding_writer, repository=fake_repo,
                               operation_id=OPERATION_ID)
    before = ticket.model_dump(exclude={"embedding"})
    assert updated.model_dump(exclude={"embedding"}) == before
    assert fake_repo.loaded(ticket_pk("t_881")).model_dump(exclude={"embedding"}) == before
