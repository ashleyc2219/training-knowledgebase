import pytest

from training_kb import errors


def test_ingress_error_keeps_sorted_unique_fields() -> None:
    error = errors.IngressError("缺少必填欄位", ["ts", "author", "author"])
    assert error.fields == ("author", "ts")
    assert error.message == "缺少必填欄位"
    assert str(error) == "缺少必填欄位"
    assert isinstance(error, errors.PermanentError)


def test_error_hierarchy_separates_retryable() -> None:
    assert issubclass(errors.ContentError, errors.PermanentError)
    assert not issubclass(errors.TransientError, errors.PermanentError)
    assert not issubclass(errors.CoordinationError, errors.PermanentError)
    assert not issubclass(errors.PublishError, errors.PermanentError)
    with pytest.raises(errors.TransientError):
        raise errors.TransientError("DynamoDB 暫時取消")
