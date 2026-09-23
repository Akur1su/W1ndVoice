import httpx
import pytest

from app.ai import (
    AIAnalyzer,
    build_system_prompt,
    extract_provider_error,
    normalize_analysis,
    parse_json,
    validate_endpoint_url,
)
from app.database import Database
from app.security import SecretStore


def test_normalizes_analysis() -> None:
    result = normalize_analysis(
        {"summary": "有用的摘要", "importance": 120, "tags": ["AI", "模型"], "risk_level": "HIGH"}
    )
    assert result["importance"] == 100
    assert result["risk_level"] == "high"


def test_parses_fenced_json() -> None:
    assert parse_json('```json\n{"summary":"ok"}\n```')["summary"] == "ok"


def test_local_ai_endpoint_is_allowed() -> None:
    assert validate_endpoint_url("http://127.0.0.1:11434/v1/") == "http://127.0.0.1:11434/v1"
    with pytest.raises(ValueError):
        validate_endpoint_url("file:///etc/passwd")


def test_configure_encrypts_key_and_blank_keeps_it(tmp_path) -> None:
    db = Database(tmp_path / "test.db")
    secrets = SecretStore(tmp_path / "secret.key")
    analyzer = AIAnalyzer(db, secrets)
    analyzer.configure("https://api.example.com/v1", "test-model", "secret-key")

    encrypted = db.get_settings()["ai_api_key"]
    assert encrypted != "secret-key"
    assert secrets.decrypt(encrypted) == "secret-key"
    assert analyzer.public_settings()["has_api_key"] is True

    analyzer.configure("https://api.example.com/v1", "new-model", "")
    assert db.get_settings()["ai_api_key"] == encrypted
    assert analyzer.public_settings()["model"] == "new-model"


def test_system_prompt_always_requests_json() -> None:
    prompt = build_system_prompt("分析当前页面")
    assert "json" in prompt
    assert all(field in prompt for field in ("summary", "importance", "tags", "risk_level"))


def test_extracts_provider_error_message() -> None:
    request = httpx.Request("POST", "https://api.example.com/chat/completions")
    response = httpx.Response(
        400,
        request=request,
        json={"error": {"message": "Prompt must contain json", "type": "invalid_request_error"}},
    )
    assert extract_provider_error(response) == "Prompt must contain json"
