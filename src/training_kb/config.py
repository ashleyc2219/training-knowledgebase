from collections.abc import Mapping
from dataclasses import dataclass, field
from os import environ

DEFAULT_PROJECT_ID = "demo"
DEFAULT_EMBEDDING_MODEL_ID = "amazon.titan-embed-text-v2:0"


@dataclass(frozen=True)
class Thresholds:
    cosine_match: float = 0.85
    recurring_tickets: int = 5
    recurring_category: int = 5
    production_feedback: int = 10
    demo_feedback: int = 8
    weak_average: float = 3.5


@dataclass(frozen=True)
class Settings:
    table_name: str
    content_bucket: str
    aws_region: str | None = None
    bedrock_region: str | None = None
    generation_model_id: str | None = None
    embedding_model_id: str = DEFAULT_EMBEDDING_MODEL_ID
    project_id: str = DEFAULT_PROJECT_ID
    thresholds: Thresholds = field(default_factory=Thresholds)


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    values: Mapping[str, str] = environ if env is None else env
    aws_region = values.get("TKB_AWS_REGION")
    return Settings(
        table_name=values.get("TKB_TABLE_NAME", "training_kb"),
        content_bucket=values.get("TKB_CONTENT_BUCKET", "training-kb-content"),
        aws_region=aws_region,
        bedrock_region=values.get("TKB_BEDROCK_REGION") or aws_region,
        generation_model_id=values.get("TKB_GENERATION_MODEL_ID"),
        embedding_model_id=values.get("TKB_EMBEDDING_MODEL_ID", DEFAULT_EMBEDDING_MODEL_ID),
        project_id=values.get("TKB_PROJECT_ID", DEFAULT_PROJECT_ID),
    )
