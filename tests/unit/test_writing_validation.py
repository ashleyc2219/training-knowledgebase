"""Phase 18：schema 通過不等於業務通過、最多一次修正、生成參數與輸出重用。"""

import pytest

from training_kb.errors import ContentError
from training_kb.writing.validators import gap_naming_validator, step_rewrite_validator


def test_step_rewrite_rejects_number_outside_hit_set() -> None:
    validate = step_rewrite_validator(allowed_steps=frozenset({3}),
                                      allowed_features=frozenset({"Prepare"}))
    with pytest.raises(ContentError, match="step_number_not_in_hit_set"):
        validate({"steps": [{"number": 2, "type": "click_ui", "text": "x",
                             "feature_id": "Prepare"}]})


def test_gap_naming_accepts_null_feature_but_rejects_unknown_id() -> None:
    validate = gap_naming_validator(known_feature_ids=frozenset({"Prepare"}))
    validate({"gap": "找不到會前摘要入口", "feature_id": None})
    with pytest.raises(ContentError, match="feature_id_not_found"):
        validate({"gap": "找不到會前摘要入口", "feature_id": "Admin"})
