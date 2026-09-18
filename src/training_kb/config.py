import re
import shlex
from collections.abc import Mapping
from dataclasses import dataclass, field
from os import environ
from pathlib import Path

DEFAULT_PROJECT_ID = "demo"
DEFAULT_EMBEDDING_MODEL_ID = "amazon.titan-embed-text-v2:0"
DOTENV_NAME = ".env"
"""專案根目錄的本機設定檔；已被 `.gitignore` 忽略。"""

_DOTENV_LINE = re.compile(r"^(?:export\s+)?(TKB_[A-Z0-9_]+)=(.*)$")
"""只收 `TKB_` 鍵；可帶 `export ` 前綴。空值與註解不進結果。"""


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


def parse_dotenv(text: str) -> dict[str, str]:
    """把 `.env` 正文收成 `TKB_` 鍵值；註解、空值、非 `TKB_` 鍵一律略過。"""
    parsed: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = _DOTENV_LINE.match(line)
        if match is None:
            continue
        value = match.group(2).strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if value:
            parsed[match.group(1)] = value
    return parsed


def _dotenv_path(path: Path | None) -> Path:
    return path if path is not None else Path.cwd() / DOTENV_NAME


def read_dotenv(path: Path | None = None) -> dict[str, str]:
    """讀一個 `.env`；檔案不存在時回空 dict。"""
    target = _dotenv_path(path)
    if not target.is_file():
        return {}
    return parse_dotenv(target.read_text(encoding="utf-8"))


def fill_missing(env: Mapping[str, str], file_values: Mapping[str, str]) -> dict[str, str]:
    """已在環境裡且非空的鍵勝出；缺或空字串才用檔案值。"""
    filled = dict(env)
    for key, value in file_values.items():
        if not (filled.get(key) or "").strip():
            filled[key] = value
    return filled


def dotenv_exports_for_shell(
        path: Path | None = None, env: Mapping[str, str] | None = None) -> str:
    """給 `eval` 用的 `export KEY=...`；只補目前環境沒有的鍵。"""
    current = environ if env is None else env
    additions = {
        key: value for key, value in read_dotenv(path).items()
        if not (current.get(key) or "").strip()}
    return "\n".join(
        f"export {key}={shlex.quote(value)}" for key, value in sorted(additions.items()))


def load_settings(
        env: Mapping[str, str] | None = None, *,
        dotenv_path: Path | None = None) -> Settings:
    """讀設定。`env is None` 時用行程環境，並用 `.env` 補缺的 `TKB_` 鍵。

    測試傳入 mapping、且沒給 `dotenv_path` 時不讀檔，避免被開發者本機 `.env` 影響。
    """
    if env is None:
        values: Mapping[str, str] = fill_missing(environ, read_dotenv(dotenv_path))
    elif dotenv_path is not None:
        values = fill_missing(env, read_dotenv(dotenv_path))
    else:
        values = env
    aws_region = values.get("TKB_AWS_REGION") or None
    return Settings(
        table_name=values.get("TKB_TABLE_NAME") or "training_kb",
        content_bucket=values.get("TKB_CONTENT_BUCKET") or "training-kb-content",
        aws_region=aws_region,
        bedrock_region=values.get("TKB_BEDROCK_REGION") or aws_region,
        generation_model_id=values.get("TKB_GENERATION_MODEL_ID") or None,
        embedding_model_id=values.get("TKB_EMBEDDING_MODEL_ID") or DEFAULT_EMBEDDING_MODEL_ID,
        project_id=values.get("TKB_PROJECT_ID") or DEFAULT_PROJECT_ID,
    )
