"""單元測試不碰外部服務：把會觸發 HTTP／LLM 的環境變數清空（load_dotenv 不會覆蓋既有 env）。"""

import pytest


@pytest.fixture(autouse=True)
def _no_external_services(monkeypatch):
    for key in (
        "HYDRADB_URI",
        "HYDRADB_APIKEY",
        "ANTHROPIC_API_KEY",
        "ROCKETRIDE_PROJECT_ID",
        "OLLAMA_BASE_URL",
        "OLLAMA_API_KEY",
        "OLLAMA_MODEL",
    ):
        monkeypatch.setenv(key, "")
    yield
