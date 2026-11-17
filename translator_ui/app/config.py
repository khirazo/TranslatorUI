"""Application configuration loaded from the repository-root .env file."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field, field_validator

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = REPOSITORY_ROOT / ".env"


class Settings(BaseModel):
    """Validated settings for the OpenAI-compatible translation service."""

    model_config = ConfigDict(frozen=True)

    llm_endpoint: str = "http://host.docker.internal:1234"
    llm_model: str = "plamo-3-translate-0.8b"
    llm_api_key: str | None = None
    llm_max_tokens: int = Field(default=512, gt=0)
    save_translations: bool = False

    @field_validator("llm_endpoint")
    @classmethod
    def normalize_endpoint(cls, value: str) -> str:
        endpoint = value.strip().rstrip("/")
        if not endpoint.startswith(("http://", "https://")):
            raise ValueError("LLM_ENDPOINT must be an HTTP(S) URL")
        if endpoint.endswith("/v1"):
            raise ValueError("LLM_ENDPOINT must not include the /v1 suffix")
        return endpoint

    @field_validator("llm_model")
    @classmethod
    def validate_model(cls, value: str) -> str:
        model = value.strip()
        if not model:
            raise ValueError("LLM_MODEL must not be empty")
        return model

    @classmethod
    def from_environment(cls) -> Settings:
        """Load repository-root .env values without overwriting process environment."""
        load_dotenv(ENV_FILE, override=False)
        api_key = os.getenv("LLM_API_KEY")
        return cls(
            llm_endpoint=os.getenv("LLM_ENDPOINT", cls.model_fields["llm_endpoint"].default),
            llm_model=os.getenv("LLM_MODEL", cls.model_fields["llm_model"].default),
            llm_api_key=api_key if api_key else None,
            llm_max_tokens=os.getenv("LLM_MAX_TOKENS", cls.model_fields["llm_max_tokens"].default),
            save_translations=os.getenv(
                "SAVE_TRANSLATIONS", cls.model_fields["save_translations"].default
            ),
        )
