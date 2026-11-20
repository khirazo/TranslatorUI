"""Configuration, selectable model metadata, and atomic settings snapshots."""

from __future__ import annotations

import os
import tomllib
from collections.abc import Mapping
from pathlib import Path
from threading import Lock
from typing import Literal
from urllib.parse import urljoin

from dotenv import dotenv_values
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = REPOSITORY_ROOT / ".env"
DEFAULT_CONFIG_FILE = REPOSITORY_ROOT / "translator-ui.toml"


class ModelSettings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    id: str
    name: str | None = None
    enabled: bool = True
    efforts: tuple[str, ...] = ()
    default_effort: str | None = None
    effort_request_field: Literal["reasoning_effort", "effort"] | None = None

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        if not (normalized := value.strip()):
            raise ValueError("model id must not be empty")
        return normalized

    @field_validator("efforts")
    @classmethod
    def validate_efforts(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(item.strip() for item in value)
        if any(not item for item in normalized) or len(set(normalized)) != len(normalized):
            raise ValueError("efforts must be unique non-empty strings")
        return normalized

    @model_validator(mode="after")
    def validate_efforts_config(self) -> ModelSettings:
        if self.efforts and (
            self.default_effort not in self.efforts or not self.effort_request_field
        ):
            raise ValueError(
                "effort-enabled models require default_effort and effort_request_field"
            )
        if not self.efforts and (self.default_effort or self.effort_request_field):
            raise ValueError(
                "unsupported effort settings must not specify defaults or request fields"
            )
        return self

    @property
    def display_name(self) -> str:
        return self.name or self.id


class TranslationOptions(BaseModel):
    model_config = ConfigDict(frozen=True)
    model_id: str
    effort: str | None = None
    effort_request_field: Literal["reasoning_effort", "effort"] | None = None
    japanese_style: Literal["polite", "plain"] | None = None


class ProviderSettings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    id: str
    name: str
    kind: Literal["openai_compatible", "acp"] = "openai_compatible"
    enabled: bool = True
    base_url: str | None = None
    model: str | None = None
    models: tuple[ModelSettings, ...] = ()
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
        if not normalized or not all(char.isalnum() or char in "_-" for char in normalized):
            raise ValueError(
                "provider id must contain only letters, digits, hyphens, or underscores"
            )
        return normalized

    @field_validator("base_url")
    @classmethod
    def normalize_base_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        endpoint = value.strip().rstrip("/")
        if not endpoint.startswith(("http://", "https://")) or endpoint.endswith("/v1"):
            raise ValueError("base_url must be an HTTP(S) URL without the /v1 suffix")
        return endpoint

    @model_validator(mode="after")
    def validate_provider(self) -> ProviderSettings:
        if self.kind == "openai_compatible":
            if self.base_url is None or (not self.models and not self.model):
                raise ValueError("openai_compatible providers require base_url and model or models")
            if len({model.id for model in self.models}) != len(self.models):
                raise ValueError("model ids must be unique within a provider")
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

    @property
    def selectable_models(self) -> tuple[ModelSettings, ...]:
        if self.models:
            return tuple(model for model in self.models if model.enabled)
        assert self.model is not None
        return (ModelSettings(id=self.model),)

    @classmethod
    def from_mapping(
        cls, value: Mapping[str, object], environment: Mapping[str, str]
    ) -> ProviderSettings:
        provider = cls.model_validate(value)
        return provider.model_copy(
            update={"api_key": environment.get(provider.api_key_env or "") or None}
        )


class Settings(BaseModel):
    model_config = ConfigDict(frozen=True)
    save_translations: bool = False
    default_provider_id: str = "default"
    providers: tuple[ProviderSettings, ...] = Field(
        default_factory=lambda: (
            ProviderSettings(
                id="default",
                name="Default provider",
                base_url="http://host.docker.internal:1234",
                model="plamo-3-translate-0.8b",
            ),
        )
    )

    @model_validator(mode="after")
    def validate_providers(self) -> Settings:
        if len({provider.id for provider in self.providers}) != len(self.providers):
            raise ValueError("provider ids must be unique")
        if self.provider_for(self.default_provider_id) is None:
            raise ValueError(
                "default_provider_id must identify an enabled OpenAI-compatible provider"
            )
        return self

    @property
    def selectable_providers(self) -> tuple[ProviderSettings, ...]:
        return tuple(p for p in self.providers if p.enabled and p.kind == "openai_compatible")

    def provider_for(self, provider_id: str | None) -> ProviderSettings | None:
        selected = provider_id or self.default_provider_id
        return next((p for p in self.selectable_providers if p.id == selected), None)

    def resolve_options(
        self,
        provider_id: str | None,
        model_id: str | None,
        effort: str | None,
        japanese_style: Literal["polite", "plain"] | None,
        target_lang: str,
    ) -> tuple[ProviderSettings, TranslationOptions] | str:
        provider = self.provider_for(provider_id)
        if provider is None:
            return "The selected translation provider is unavailable."
        model = next(
            (
                m
                for m in provider.selectable_models
                if m.id == (model_id or provider.selectable_models[0].id)
            ),
            None,
        )
        if model is None:
            return "The selected translation model is unavailable."
        selected_effort = effort if effort is not None else model.default_effort
        if selected_effort is not None and selected_effort not in model.efforts:
            return "The selected translation effort is unavailable."
        if japanese_style is not None and target_lang != "ja":
            return "japanese_style is only supported when target_lang is ja."
        return provider, TranslationOptions(
            model_id=model.id,
            effort=selected_effort,
            effort_request_field=model.effort_request_field,
            japanese_style=(japanese_style or "polite") if target_lang == "ja" else None,
        )

    def provider_choices(self, generation: int) -> dict[str, object]:
        default = self.provider_for(self.default_provider_id)
        assert default is not None
        default_model = default.selectable_models[0]
        return {
            "generation": generation,
            "defaults": {
                "provider_id": default.id,
                "model_id": default_model.id,
                "effort": default_model.default_effort,
            },
            "providers": [
                {
                    "id": p.id,
                    "name": p.name,
                    "models": [
                        {
                            "id": m.id,
                            "name": m.display_name,
                            "efforts": list(m.efforts),
                            "default_effort": m.default_effort,
                        }
                        for m in p.selectable_models
                    ],
                }
                for p in self.selectable_providers
            ],
        }

    @classmethod
    def legacy(cls, values: Mapping[str, str]) -> Settings:
        provider = ProviderSettings(
            id="default",
            name="Default provider",
            base_url=values.get("LLM_ENDPOINT", "http://host.docker.internal:1234"),
            model=values.get("LLM_MODEL", "plamo-3-translate-0.8b"),
            model_endpoint=values.get("LLM_MODEL_ENDPOINT", "/v1/models"),
            chat_endpoint=values.get("LLM_CHAT_ENDPOINT", "/v1/chat/completions"),
            api_key=values.get("LLM_API_KEY") or None,
            max_tokens=values.get("LLM_MAX_TOKENS", "512"),
        )
        return cls(
            save_translations=values.get("SAVE_TRANSLATIONS", "false"),
            default_provider_id="default",
            providers=(provider,),
        )

    @classmethod
    def from_file(cls, path: Path, environment: Mapping[str, str] | None = None) -> Settings:
        with path.open("rb") as file:
            raw = tomllib.load(file)
        app, providers = raw.get("app", {}), raw.get("providers", [])
        if (
            not isinstance(app, dict)
            or not isinstance(providers, list)
            or not all(isinstance(p, dict) for p in providers)
        ):
            raise ValueError("translator-ui.toml must contain valid app and providers sections")
        values = environment or os.environ
        return cls(
            save_translations=app.get("save_translations", False),
            default_provider_id=app.get("default_provider", ""),
            providers=tuple(ProviderSettings.from_mapping(p, values) for p in providers),
        )

    @classmethod
    def from_environment(cls) -> Settings:
        return SettingsLoader().load()


class SettingsLoader:
    def __init__(
        self,
        environment: Mapping[str, str] | None = None,
        env_file: Path = ENV_FILE,
        default_config_file: Path = DEFAULT_CONFIG_FILE,
    ) -> None:
        self._environment, self._env_file, self._default_config_file = (
            dict(environment or os.environ),
            env_file,
            default_config_file,
        )

    def load(self) -> Settings:
        values = {
            k: v for k, v in dotenv_values(self._env_file).items() if v is not None
        } | self._environment
        configured = values.get("TRANSLATOR_UI_CONFIG")
        path = Path(configured) if configured else self._default_config_file
        if path.exists():
            return Settings.from_file(path, values)
        if configured:
            raise ValueError("The configured provider registry is unavailable.")
        return Settings.legacy(values)


class SettingsStore:
    def __init__(self, loader: SettingsLoader | None = None) -> None:
        self._loader, self._lock = loader or SettingsLoader(), Lock()
        self._snapshot, self._generation = self._loader.load(), 1

    def current(self) -> tuple[Settings, int]:
        with self._lock:
            return self._snapshot, self._generation

    def reload(self) -> tuple[Settings, int]:
        snapshot = self._loader.load()
        with self._lock:
            self._snapshot, self._generation = snapshot, self._generation + 1
            return self._snapshot, self._generation
