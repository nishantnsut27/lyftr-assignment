from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        hide_input_in_errors=True,
    )

    llm_api_keys: SecretStr = Field(repr=False)
    llm_model: str = "groq/openai/gpt-oss-20b"
    database_url: str = "sqlite:///./data/app.db"
    allowed_origins: str = "http://localhost:3000,http://localhost:5173"
    enable_failure_simulation: bool = False
    llm_cache_dir: Path = Path("./data/llm-cache")
    default_system_prompt: str = "You are a helpful assistant. Answer clearly and concisely."
    llm_timeout_seconds: float = Field(default=30, gt=0, le=120)
    llm_max_tokens: int = Field(default=1024, ge=1, le=8192)

    @model_validator(mode="before")
    @classmethod
    def protect_key_input(cls, values: Any) -> Any:
        if isinstance(values, dict) and isinstance(values.get("llm_api_keys"), str):
            values = {**values, "llm_api_keys": SecretStr(values["llm_api_keys"])}
        return values

    @field_validator("llm_api_keys")
    @classmethod
    def validate_key_pool(cls, value: SecretStr) -> SecretStr:
        keys = [key.strip() for key in value.get_secret_value().split(",")]
        if len(keys) < 2 or any(not key for key in keys) or len(set(keys)) != len(keys):
            raise ValueError("LLM_API_KEYS requires at least two distinct non-empty keys")
        return value

    @field_validator("llm_model")
    @classmethod
    def validate_model(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("LLM_MODEL must not be empty")
        return value.strip()

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, value: str) -> str:
        if not value.startswith("sqlite:///") or not value.removeprefix("sqlite:///"):
            raise ValueError("DATABASE_URL must identify a SQLite file using sqlite:///")
        if value.removeprefix("sqlite:///") == ":memory:":
            raise ValueError("DATABASE_URL must use a persistent SQLite file")
        return value

    @field_validator("allowed_origins")
    @classmethod
    def validate_origins(cls, value: str) -> str:
        for origin in value.split(","):
            parts = urlsplit(origin.strip())
            if (
                parts.scheme not in {"http", "https"}
                or not parts.hostname
                or "*" in parts.netloc
                or (parts.port is not None and not 1 <= parts.port <= 65535)
                or parts.username
                or parts.password
                or parts.path not in {"", "/"}
                or parts.query
                or parts.fragment
            ):
                raise ValueError("ALLOWED_ORIGINS must contain explicit HTTP(S) origins")
        return value

    @property
    def api_keys(self) -> tuple[SecretStr, ...]:
        return tuple(
            SecretStr(key.strip()) for key in self.llm_api_keys.get_secret_value().split(",")
        )

    @property
    def origins(self) -> list[str]:
        return [origin.strip().rstrip("/") for origin in self.allowed_origins.split(",")]

    @property
    def database_path(self) -> Path:
        return Path(self.database_url.removeprefix("sqlite:///"))
