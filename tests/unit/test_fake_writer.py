import pytest

from training_kb.errors import PermanentError
from training_kb.writing.client import Writer


def count_dimensions(writer: Writer) -> int:     # 只收 Writer，用來證明形狀相容
    return len(writer.embed("開啟摘要。", operation_id="op-1", node="embed"))


def test_fake_writer_records_every_call(fake_writer) -> None:
    fake_writer.replies.append({"gap": "找不到 Prepare 按鈕"})
    answer = fake_writer.generate_json("s", "u", {}, operation_id="op-1", node="name_gap")
    assert answer == {"gap": "找不到 Prepare 按鈕"}
    assert count_dimensions(fake_writer) == 1024
    assert fake_writer.request_attempts == 2
    assert [call["kind"] for call in fake_writer.calls] == ["generation", "embedding"]
    assert [call["node"] for call in fake_writer.calls] == ["name_gap", "embed"]


def test_fake_writer_fails_loudly_when_no_reply_is_queued(fake_writer) -> None:
    with pytest.raises(PermanentError):
        fake_writer.generate_json("s", "u", {}, operation_id="op-1", node="draft")
