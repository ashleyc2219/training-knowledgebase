from pathlib import Path

from training_kb.config import (
    DEFAULT_PROJECT_ID,
    dotenv_exports_for_shell,
    load_settings,
    parse_dotenv,
)

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


def test_parse_dotenv_keeps_tkb_keys_and_skips_comments() -> None:
    parsed = parse_dotenv(
        "# note\n"
        "export TKB_AWS_REGION=us-east-1\n"
        "TKB_CONTENT_BUCKET='my-bucket'\n"
        "AWS_REGION=ignored\n"
        "TKB_TABLE_NAME=\n"
    )
    assert parsed == {
        "TKB_AWS_REGION": "us-east-1",
        "TKB_CONTENT_BUCKET": "my-bucket",
    }


def test_load_settings_reads_dotenv_only_when_process_env_is_missing(
        tmp_path: Path) -> None:
    dotenv = tmp_path / ".env"
    dotenv.write_text(
        "TKB_AWS_REGION=us-east-1\nTKB_CONTENT_BUCKET=from-file\n", encoding="utf-8")
    explicit = load_settings({"TKB_CONTENT_BUCKET": "from-shell"})
    assert explicit.content_bucket == "from-shell"
    assert explicit.aws_region is None
    filled = load_settings({}, dotenv_path=dotenv)
    assert filled.aws_region == "us-east-1"
    assert filled.content_bucket == "from-file"
    prefers_shell = load_settings(
        {"TKB_CONTENT_BUCKET": "from-shell", "TKB_AWS_REGION": ""}, dotenv_path=dotenv)
    assert prefers_shell.content_bucket == "from-shell"
    assert prefers_shell.aws_region == "us-east-1"


def test_dotenv_exports_skip_keys_already_set(tmp_path: Path) -> None:
    dotenv = tmp_path / ".env"
    dotenv.write_text(
        "TKB_AWS_REGION=us-east-1\nTKB_CONTENT_BUCKET=from-file\n", encoding="utf-8")
    script = dotenv_exports_for_shell(
        path=dotenv, env={"TKB_AWS_REGION": "ap-northeast-1"})
    assert "TKB_CONTENT_BUCKET=" in script
    assert "from-file" in script
    assert "TKB_AWS_REGION" not in script
