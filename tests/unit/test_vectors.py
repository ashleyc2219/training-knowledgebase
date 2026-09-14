import pytest

from training_kb.errors import PermanentError
from training_kb.vectors import centroid, cosine

NAN = float("nan")


def test_cosine_and_centroid_are_deterministic() -> None:
    assert cosine([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)
    assert cosine([1.0, 1.0], [1.0, 1.0]) == pytest.approx(1.0)
    assert cosine([1.0, 0.0], [-1.0, 0.0]) == pytest.approx(-1.0)
    assert cosine([1.0, 0.0, 0.0], [17.0, 0.0, 0.0]) == 1.0
    assert cosine([1.0, 0.0, 0.0, 0.0, 0.0], [17.0, 7.0, 6.0, 5.0, 1.0]) == 0.85
    assert centroid([[1.0, 0.0], [0.0, 1.0]]) == [0.5, 0.5]
    assert centroid([[0.25, 0.5]]) == [0.25, 0.5]


@pytest.mark.parametrize(("left", "right"), [
    ([], [1.0]),
    ([1.0, 0.0], [1.0]),
    ([0.0, 0.0], [1.0, 0.0]),
    ([NAN, 1.0], [1.0, 0.0]),
    ([True, 1.0], [1.0, 0.0]),
])
def test_cosine_rejects_bad_input(left: list[float], right: list[float]) -> None:
    with pytest.raises(PermanentError):
        cosine(left, right)


@pytest.mark.parametrize("vectors", [[], [[]], [[1.0, 0.0], [1.0]], [[1.0, NAN]]])
def test_centroid_rejects_bad_input(vectors: list[list[float]]) -> None:
    with pytest.raises(PermanentError):
        centroid(vectors)
