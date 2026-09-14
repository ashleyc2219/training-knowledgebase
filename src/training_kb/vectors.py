"""向量純函式：`cosine` 與 `centroid`，以及兩者共用的輸入檢查。

這支檔沒有 AWS 相依，維度也不綁 1024：1024 維是 Titan 回應的契約，檢查點在
`writing/client.py` 的 `embed`（設計 §14.3）。這裡只保證「算得對、算得可重現」，
錯誤一律用 Phase 02 的 `PermanentError`（00A §4.1），不用 `ValueError`。
0.85 這類門檻屬於 Phase 38／49／50 的業務判斷，唯一來源是 `Thresholds.cosine_match`。
"""

import math

from training_kb.errors import PermanentError


def _checked(vector: list[float], *, expected: int | None = None) -> list[float]:
    """把一條向量檢查成「非空、長度相符、每個元素都是有限數值」的 `list[float]`。

    順序不能換：`True` 是 `int` 的子型別，`isinstance(True, (int, float))` 與
    `math.isfinite(True)` 都成立，所以先排除 `bool`、再判型別，確定是數值才 `isfinite`
    （對字串先做 `isfinite` 會變成 `TypeError`，不是 `PermanentError`）。
    """
    if not vector:
        raise PermanentError("vector must not be empty")
    if expected is not None and len(vector) != expected:
        raise PermanentError(f"vector length {len(vector)} does not match {expected}")
    for value in vector:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise PermanentError(f"vector contains a non-numeric value: {value!r}")
        if not math.isfinite(value):
            raise PermanentError(f"vector contains a non-finite value: {value!r}")
    return [float(value) for value in vector]


def cosine(left: list[float], right: list[float]) -> float:
    """兩條向量的餘弦相似度：`dot / (norm_left * norm_right)`，不先除一次再除一次、不四捨五入。

    固定這個運算順序，Phase 38 才能用整數構成的向量精確斷言 `cosine(AXIS, ON) == 0.85`。
    零向量沒有方向，明確丟 `PermanentError`，不得當成 0 相似度。
    """
    first = _checked(left)
    second = _checked(right, expected=len(first))
    first_norm = math.sqrt(sum(value * value for value in first))
    second_norm = math.sqrt(sum(value * value for value in second))
    if first_norm == 0.0 or second_norm == 0.0:
        raise PermanentError("zero vector has no cosine similarity")
    dot = sum(a * b for a, b in zip(first, second, strict=True))
    return dot / (first_norm * second_norm)


def centroid(vectors: list[list[float]]) -> list[float]:
    """一群向量逐維相加再除以筆數；只有一筆時回它自己（Phase 38 的單樣本群走同一條路徑）。"""
    if not vectors:
        raise PermanentError("centroid needs at least one vector")
    first = _checked(vectors[0])
    rows = [first] + [_checked(row, expected=len(first)) for row in vectors[1:]]
    return [sum(column) / len(rows) for column in zip(*rows, strict=True)]
