from training_kb.config import DEFAULT_PROJECT_ID, load_settings

MINIMAL = {"TKB_TABLE_NAME": "training_kb_test", "TKB_CONTENT_BUCKET": "tkb-test"}


def test_load_settings_keeps_unverified_model_empty() -> None:
    settings = load_settings({**MINIMAL, "TKB_AWS_REGION": "us-east-1"})
    assert settings.table_name == "training_kb_test"
    assert settings.generation_model_id is None
    assert settings.embedding_model_id == "amazon.titan-embed-text-v2:0"
    assert settings.bedrock_region == "us-east-1"
    assert settings.project_id == DEFAULT_PROJECT_ID == "demo"
    assert settings.thresholds.cosine_match == 0.85
    assert settings.thresholds.weak_average == 3.5
    assert settings.thresholds.production_feedback == 10
    assert settings.thresholds.demo_feedback == 8


def test_bedrock_region_is_independent_and_non_tkb_keys_are_ignored() -> None:
    settings = load_settings(
        {"TKB_AWS_REGION": "ap-northeast-1", "TKB_BEDROCK_REGION": "us-east-1", "AWS_REGION": "x"}
    )
    assert settings.aws_region == "ap-northeast-1"
    assert settings.bedrock_region == "us-east-1"
    assert settings.table_name == "training_kb"
    assert settings.content_bucket == "training-kb-content"
