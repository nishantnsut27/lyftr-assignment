from pathlib import Path

import pytest
from litellm import get_llm_provider
from pydantic import ValidationError

from app.config import Settings
from app.main import create_app
from tests.conftest import TEST_KEYS


@pytest.mark.parametrize("keys", ["", "one-key", "a,", ",b", "a,,c", "a,a", "a,b,a"])
def test_key_pool_validation_and_error_redaction(keys):
    with pytest.raises(ValidationError) as failure:
        Settings(_env_file=None, llm_api_keys=keys)
    assert "requires at least two distinct non-empty keys" in str(failure.value)
    assert "input_value" not in str(failure.value)


def test_keys_are_ordered_trimmed_and_redacted():
    settings = Settings(
        _env_file=None, llm_api_keys="  alpha-private , beta-private, gamma-private "
    )
    assert [key.get_secret_value() for key in settings.api_keys] == [
        "alpha-private",
        "beta-private",
        "gamma-private",
    ]
    assert "private" not in repr(settings)
    assert "private" not in settings.model_dump_json()


def test_all_configuration_loads_from_environment(monkeypatch):
    values = {
        "LLM_API_KEYS": ",".join(TEST_KEYS),
        "LLM_MODEL": "groq/openai/gpt-oss-20b",
        "DATABASE_URL": "sqlite:////data/app.db",
        "ALLOWED_ORIGINS": "https://chat.example,http://localhost:3000",
        "ENABLE_FAILURE_SIMULATION": "true",
        "LLM_CACHE_DIR": "/data/cache",
        "DEFAULT_SYSTEM_PROMPT": "Configured default",
        "LLM_TIMEOUT_SECONDS": "22",
        "LLM_MAX_TOKENS": "512",
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    settings = Settings(_env_file=None)
    assert len(settings.api_keys) == 3
    assert settings.llm_model == values["LLM_MODEL"]
    assert settings.database_path == Path("/data/app.db")
    assert settings.llm_cache_dir == Path("/data/cache")
    assert settings.origins == ["https://chat.example", "http://localhost:3000"]
    assert settings.enable_failure_simulation is True
    assert settings.default_system_prompt == "Configured default"
    assert settings.llm_timeout_seconds == 22
    assert settings.llm_max_tokens == 512


@pytest.mark.parametrize(
    "field,value",
    [
        ("database_url", "postgres://host/db"),
        ("database_url", "sqlite:///"),
        ("database_url", "sqlite:///:memory:"),
        ("allowed_origins", "*"),
        ("allowed_origins", "https://chat.example/path"),
        ("allowed_origins", "https://user:password@chat.example"),
        ("allowed_origins", "https://chat.example?x=1"),
        ("allowed_origins", ""),
        ("llm_model", " "),
        ("llm_timeout_seconds", 0),
        ("llm_timeout_seconds", 121),
        ("llm_max_tokens", 0),
        ("llm_max_tokens", 8193),
    ],
)
def test_invalid_configuration_is_rejected(field, value):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, llm_api_keys=",".join(TEST_KEYS), **{field: value})


def test_factory_configuration_failure_does_not_expose_credentials(monkeypatch, test_directory):
    monkeypatch.chdir(test_directory)
    monkeypatch.setenv("LLM_API_KEYS", "private-only-one-key")
    with pytest.raises(RuntimeError) as failure:
        create_app()
    assert str(failure.value) == "Invalid backend configuration; check environment settings"
    assert "private-only-one-key" not in str(failure.value)


def test_default_gpt_oss_model_resolves_to_the_groq_adapter():
    model, provider, _, base_url = get_llm_provider(model="groq/openai/gpt-oss-20b")
    assert model == "openai/gpt-oss-20b"
    assert provider == "groq"
    assert base_url in (None, "https://api.groq.com/openai/v1")
