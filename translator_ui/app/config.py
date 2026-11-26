"""Configuration, selectable model metadata, and atomic settings snapshots."""

from __future__ import annotations

import os
import re
import tomllib
from collections.abc import Mapping
from pathlib import Path
from threading import Lock
from typing import Literal
from urllib.parse import urljoin

from dotenv import dotenv_values
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator, model_validator

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = REPOSITORY_ROOT / ".env"
DEFAULT_CONFIG_FILE = REPOSITORY_ROOT / "translator-ui.toml"
ACP_DEFAULT_MODEL_ID = "agent-default"


class ModelSettings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    id: str
    name: str | None = None
    enabled: bool = True
    efforts: tuple[str, ...] = ()
    default_effort: str | None = None
    effort_request_field: Literal["reasoning_effort", "effort"] | None = None
    translation_profile: Literal["plamo3", "generic"] | None = None
    max_tokens: int | None = Field(default=None, gt=0)

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


class ModelRuleSettings(BaseModel):
    """A validated model-id rule used when no exact override exists."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    pattern: str
    translation_profile: Literal["plamo3", "generic"]

    @field_validator("pattern")
    @classmethod
    def validate_pattern(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("model rule pattern must not be empty")
        try:
            re.compile(value)
        except re.error as error:
            raise ValueError("model rule pattern must be a valid regular expression") from error
        return value

    def matches(self, model_id: str) -> bool:
        return re.search(self.pattern, model_id) is not None


class TranslationOptions(BaseModel):
    model_config = ConfigDict(frozen=True)
    model_id: str
    max_tokens: int = Field(default=4096, gt=0)
    effort: str | None = None
    effort_request_field: Literal["reasoning_effort", "effort"] | None = None
    translation_profile: Literal["plamo3", "generic"] = "plamo3"
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
    model_overrides: tuple[ModelSettings, ...] = ()
    model_rules: tuple[ModelRuleSettings, ...] = ()
    model_endpoint: str = "/v1/models"
    chat_endpoint: str = "/v1/chat/completions"
    completions_endpoint: str = "/v1/completions"
    api_key_env: str | None = None
    api_key: str | None = Field(default=None, repr=False)
    max_tokens: int = Field(default=4096, gt=0)
    translation_profile: Literal["plamo3", "generic"] = Field(
        default="plamo3",
        validation_alias=AliasChoices("translation_profile", "default_translation_profile"),
    )
    command: tuple[str, ...] = ()
    environment: tuple[str, ...] = ()
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

    @field_validator("environment")
    @classmethod
    def validate_environment(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(item.strip() for item in value)
        if (
            any(not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", item) for item in normalized)
            or len(set(normalized)) != len(normalized)
        ):
            raise ValueError("environment must contain unique environment-variable names")
        return normalized

    @model_validator(mode="after")
    def validate_provider(self) -> ProviderSettings:
        if self.kind == "openai_compatible":
            has_model_metadata = self.models or self.model_overrides or self.model
            if self.base_url is None or not has_model_metadata:
                raise ValueError(
                    "openai_compatible providers require base_url and model metadata"
                )
            configured_models = (*self.models, *self.model_overrides)
            if len({model.id for model in configured_models}) != len(configured_models):
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
    def completions_url(self) -> str:
        return self.resolve_endpoint(self.completions_endpoint)

    @property
    def selectable_models(self) -> tuple[ModelSettings, ...]:
        configured_models = (*self.models, *self.model_overrides)
        if configured_models:
            return tuple(model for model in configured_models if model.enabled)
        if self.model is not None:
            return (ModelSettings(id=self.model),)
        if self.kind == "acp":
            return (ModelSettings(id=ACP_DEFAULT_MODEL_ID, name="Agent default"),)
        return ()

    def translation_profile_for(self, model: ModelSettings) -> Literal["plamo3", "generic"]:
        """Resolve an exact model override, then ordered rules, then the provider default."""
        if model.translation_profile is not None:
            return model.translation_profile
        for rule in self.model_rules:
            if rule.matches(model.id):
                return rule.translation_profile
        return self.translation_profile

    def model_for_catalog(self, model_id: str) -> ModelSettings:
        """Merge a live model id with optional TOML metadata."""
        configured_models = (*self.models, *self.model_overrides)
        for model in configured_models:
            if model.id == model_id:
                return model
        return ModelSettings(id=model_id)

    def max_tokens_for(self, model: ModelSettings) -> int:
        """Resolve a model-specific output limit before the provider default."""
        return model.max_tokens or self.max_tokens

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
    allow_profile_writes: bool = False
    profiles_file: Path | None = None
    default_provider_id: str = "default"
    providers: tuple[ProviderSettings, ...] = Field(
        default_factory=lambda: (
            ProviderSettings(
                id="default",
                name="Default provider",
                base_url="http://localhost:1234",
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
        return tuple(p for p in self.providers if p.enabled)

    @property
    def openai_compatible_providers(self) -> tuple[ProviderSettings, ...]:
        return tuple(p for p in self.selectable_providers if p.kind == "openai_compatible")

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
        model_catalog: Mapping[str, tuple[ModelSettings, ...]] | None = None,
    ) -> tuple[ProviderSettings, TranslationOptions] | str:
        provider = self.provider_for(provider_id)
        if provider is None:
            return "The selected translation provider is unavailable."
        available_models = (
            model_catalog.get(provider.id, ())
            if model_catalog is not None
            else provider.selectable_models
        )
        if not available_models:
            return "The selected translation provider has no available models."
        model = next(
            (
                m
                for m in available_models
                if m.id == (model_id or available_models[0].id)
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
            max_tokens=provider.max_tokens_for(model),
            effort=selected_effort,
            effort_request_field=model.effort_request_field,
            translation_profile=provider.translation_profile_for(model),
            japanese_style=(japanese_style or "polite") if target_lang == "ja" else None,
        )

    def provider_choices(
        self,
        generation: int,
        model_catalog: Mapping[str, tuple[ModelSettings, ...]] | None = None,
        catalog_generation: int | None = None,
    ) -> dict[str, object]:
        default = self.provider_for(self.default_provider_id)
        assert default is not None
        default_models = (
            model_catalog.get(default.id, ())
            if model_catalog is not None
            else default.selectable_models
        )
        default_model = default_models[0] if default_models else None
        result: dict[str, object] = {
            "generation": generation,
            "defaults": {
                "provider_id": default.id,
                "model_id": default_model.id if default_model else None,
                "effort": default_model.default_effort if default_model else None,
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
                        for m in (
                            model_catalog.get(p.id, ())
                            if model_catalog is not None
                            else p.selectable_models
                        )
                    ],
                }
                for p in self.selectable_providers
            ],
        }
        if catalog_generation is not None:
            result["catalog_generation"] = catalog_generation
        return result

    @classmethod
    def legacy(cls, values: Mapping[str, str]) -> Settings:
        provider = ProviderSettings(
            id="default",
            name="Default provider",
            base_url=values.get("LLM_ENDPOINT", "http://localhost:1234"),
            model=values.get("LLM_MODEL", "plamo-3-translate-0.8b"),
            model_endpoint=values.get("LLM_MODEL_ENDPOINT", "/v1/models"),
            chat_endpoint=values.get("LLM_CHAT_ENDPOINT", "/v1/chat/completions"),
            completions_endpoint=values.get("LLM_COMPLETIONS_ENDPOINT", "/v1/completions"),
            api_key=values.get("LLM_API_KEY") or None,
            max_tokens=values.get("LLM_MAX_TOKENS", "4096"),
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
            allow_profile_writes=app.get("allow_profile_writes", False),
            profiles_file=cls._profiles_file_for(path, app.get("profiles_file")),
            default_provider_id=app.get("default_provider", ""),
            providers=tuple(ProviderSettings.from_mapping(p, values) for p in providers),
        )

    @staticmethod
    def _profiles_file_for(config_file: Path, configured: object) -> Path:
        if configured is None:
            return config_file.with_name("translator-ui.profiles.toml")
        if not isinstance(configured, str) or not configured.strip():
            raise ValueError("profiles_file must be a non-empty path")
        path = Path(configured)
        return path if path.is_absolute() else config_file.parent / path

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
