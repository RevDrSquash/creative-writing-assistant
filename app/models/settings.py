"""Hard-coded model settings for the Phase 2 chat agent."""

from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_MODEL = "anthropic/claude-sonnet-5"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
REPO_ROOT = Path(__file__).resolve().parents[2]


class ModelSettings(BaseSettings):
    """Environment-backed settings for OpenRouter access."""

    openrouter_api_key: str = Field(alias="OPENROUTER_API_KEY")

    model_config = SettingsConfigDict(env_file=REPO_ROOT / ".env", extra="ignore")

    @field_validator("openrouter_api_key")
    @classmethod
    def validate_openrouter_api_key(cls, value: str) -> str:
        """Ensure the OpenRouter key was loaded and looks like an OpenRouter key."""

        key = value.strip()
        if not key:
            msg = "OPENROUTER_API_KEY is required and was not loaded from the environment."
            raise ValueError(msg)
        if not key.startswith("sk-or-v1-"):
            msg = 'OPENROUTER_API_KEY must start with "sk-or-v1-".'
            raise ValueError(msg)
        return key
