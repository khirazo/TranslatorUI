"""Configuration for TranslatorUI providers and local application settings."""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Literal
from urllib.parse import urljoin

from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = REPOSITORY_ROOT / ".env"
DEFAULT_CONFIG_FILE = REPOSITORY_ROOT / "translator-ui.toml"


class ProviderSettings(BaseModel):
    """One configured translation provider; secrets remain in environment variables."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    name: str
    kind: Literal["openai_compatible", "acp"] = "openai_compatible"
    enabled: bool = True
    base_url: str | None = None
    model: str | None = None
    model_endpoint: str = "/v1/models"
    chat_endpoint: str = "/v1/chat/completions"
    api_key_env: str | None = None
    api_key: str | None = Field(default=None, repr=False)
    max_tokens: int = Field(default=512, gt=0)
    translation_profile: Literal["plamo3", "generic"] = "plamo3"
    command: tuple[str, ...] = ()
    timeout_seconds: int = Field(default=180, gt=0)
    mode: str | None = None

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized or not all(
            character.isalnum() or character in "_-" for character in normalized
        ):
            raise ValueError(
                "provider id must contain only letters, digits, hyphens, or underscores"
            )
        return normalized

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("provider name must not be empty")
        return normalized

    @field_validator("base_url")
    @classmethod
    def normalize_base_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        endpoint = value.strip().rstrip("/")
        if not endpoint.startswith(("http://", "https://")):
            raise ValueError("base_url must be an HTTP(S) URL")
        if endpoint.endswith("/v1"):
            raise ValueError("base_url must not include the /v1 suffix")
        return endpoint

    @field_validator("model_endpoint", "chat_endpoint")
    @classmethod
    def validate_api_endpoint(cls, value: str) -> str:
        endpoint = value.strip()
        if not endpoint:
            raise ValueError("API endpoint must not be empty")
        if endpoint.startswith(("http://", "https://")):
            return endpoint.rstrip("/")
        if not endpoint.startswith("/"):
            raise ValueError("API endpoint must be an absolute URL or begin with /")
        return endpoint

    @model_validator(mode="after")
    def validate_provider(self) -> ProviderSettings:
        if self.kind == "openai_compatible":
            if self.base_url is None:
                raise ValueError("openai_compatible providers require base_url")
            if not self.model or not self.model.strip():
                raise ValueError("openai_compatible providers require model")
        elif self.command and any(not argument for argument in self.command):
            raise ValueError("ACP command arguments must not be empty")
        return self

    def resolve_endpoint(self, endpoint: str) -> str:
        if endpoint.startswith(("http://", "https://")):
            return endpoint
        assert self.base_url is not None
        return urljoin(self.base_url, endpoint)

    @property
    def model_url(self) -> str:
        return self.resolve_endpoint(self.model_endpoint)

    @property
    def chat_url(self) -> str:
        return self.resolve_endpoint(self.chat_endpoint)

    @classmethod
    def from_mapping(cls, value: dict[str, object]) -> ProviderSettings:
        provider = cls.model_validate(value)
        if provider.api_key_env:
            return provider.model_copy(update={"api_key": os.getenv(provider.api_key_env) or None})
        return provider


def _default_provider() -> ProviderSettings:
    return ProviderSettings(
        id="default",
        name="Default provider",
        base_url="http://host.docker.internal:1234",
        model="plamo-3-translate-0.8b",
    )


class Settings(BaseModel):
    """Validated application settings, including a provider registry."""

    model_config = ConfigDict(frozen=True)

    save_translations: bool = False
    default_provider_id: str = "default"
    providers: tuple[ProviderSettings, ...] = Field(default_factory=lambda: (_default_provider(),))

    @model_validator(mode="after")
    def validate_providers(self) -> Settings:
        provider_ids = [provider.id for provider in self.providers]
        if len(set(provider_ids)) != len(provider_ids):
            raise ValueError("provider ids must be unique")
        if self.default_provider_id not in provider_ids:
            raise ValueError("default_provider_id must identify a configured provider")
        return self

    @property
    def selectable_providers(self) -> tuple[ProviderSettings, ...]:
        """Providers currently supported by the server and allowed in the UI."""
        return tuple(
            provider
            for provider in self.providers
            if provider.enabled and provider.kind == "openai_compatible"
        )

    def provider_for(self, provider_id: str | None) -> ProviderSettings | None:
        selected_id = provider_id or self.default_provider_id
        return next(
            (provider for provider in self.selectable_providers if provider.id == selected_id),
            None,
        )

    @classmethod
    def legacy(cls) -> Settings:
        """Preserve the previous one-provider .env configuration during migration."""
        api_key = os.getenv("LLM_API_KEY") or None
        provider = ProviderSettings(
            id="default",
            name="Default provider",
            base_url=os.getenv("LLM_ENDPOINT", "http://host.docker.internal:1234"),
            model_endpoint=os.getenv("LLM_MODEL_ENDPOINT", "/v1/models"),
            chat_endpoint=os.getenv("LLM_CHAT_ENDPOINT", "/v1/chat/completions"),
            model=os.getenv("LLM_MODEL", "plamo-3-translate-0.8b"),
            api_key=api_key,
            max_tokens=os.getenv("LLM_MAX_TOKENS", "512"),
            translation_profile="plamo3",
        )
        return cls(
            save_translations=os.getenv("SAVE_TRANSLATIONS", "false"),
            default_provider_id=provider.id,
            providers=(provider,),
        )

    @classmethod
    def from_file(cls, path: Path) -> Settings:
        with path.open("rb") as config_file:
            raw = tomllib.load(config_file)
        app = raw.get("app", {})
        providers = raw.get("providers", [])
        if not isinstance(app, dict) or not isinstance(providers, list):
            raise ValueError("translator-ui.toml must contain [app] and [[providers]] sections")
        parsed_providers = tuple(
            ProviderSettings.from_mapping(provider)
            for provider in providers
            if isinstance(provider, dict)
        )
        if len(parsed_providers) != len(providers):
            raise ValueError("each [[providers]] entry must be a table")
        return cls(
            save_translations=app.get("save_translations", False),
            default_provider_id=app.get("default_provider", ""),
            providers=parsed_providers,
        )

    @classmethod
    def from_environment(cls) -> Settings:
        """Load .env secrets and then the selected TOML provider registry."""
        load_dotenv(ENV_FILE, override=False)
        configured_path = os.getenv("TRANSLATOR_UI_CONFIG")
        path = Path(configured_path) if configured_path else DEFAULT_CONFIG_FILE
        if path.exists():
            return cls.from_file(path)
        if configured_path:
            raise ValueError(f"TRANSLATOR_UI_CONFIG does not exist: {path}")
        return cls.legacy()
