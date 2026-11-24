"""User-owned translation profiles stored in a dedicated TOML file."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import tomllib
from threading import Lock
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator

from app.config import ModelSettings, Settings


class SavedProfile(BaseModel):
    """A validated selection that a user deliberately chose to persist."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    id: str
    name: str
    provider_id: str
    model_id: str
    source_lang: str
    target_lang: str
    japanese_style: Literal["polite", "plain"] = "polite"
    effort: str | None = None

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized or not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", normalized):
            raise ValueError(
                "profile id must contain lowercase letters, digits, hyphens, or underscores"
            )
        return normalized

    @field_validator("name", "provider_id", "model_id", "source_lang", "target_lang")
    @classmethod
    def validate_non_empty(cls, value: str) -> str:
        if not (normalized := value.strip()):
            raise ValueError("profile fields must not be empty")
        return normalized

    @field_validator("effort")
    @classmethod
    def normalize_effort(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not (normalized := value.strip()):
            return None
        return normalized


class ProfileInput(BaseModel):
    """Profile fields accepted from the same-origin GUI; the server assigns the id."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    name: str
    provider_id: str
    model_id: str
    source_lang: str
    target_lang: str
    japanese_style: Literal["polite", "plain"] = "polite"
    effort: str | None = None

    def to_saved(self, profile_id: str) -> SavedProfile:
        return SavedProfile(id=profile_id, **self.model_dump())


class ProfileWriteDisabledError(Exception):
    """Raised when the administrator did not opt in to profile writes."""


class ProfileRevisionConflictError(Exception):
    """Raised rather than overwriting a profile file edited since it was read."""


class ProfilesStore:
    """Read and atomically update only the dedicated profiles TOML file."""

    def __init__(self, settings: Settings) -> None:
        self._path = settings.profiles_file
        self._writes_enabled = settings.allow_profile_writes and self._path is not None
        self._lock = Lock()

    @property
    def writes_enabled(self) -> bool:
        return self._writes_enabled

    def current(self) -> tuple[tuple[SavedProfile, ...], str]:
        with self._lock:
            return self._read()

    def create(
        self,
        profile: ProfileInput,
        revision: str,
        settings: Settings,
        model_catalog: dict[str, tuple[ModelSettings, ...]],
    ) -> tuple[tuple[SavedProfile, ...], str]:
        if not self._writes_enabled:
            raise ProfileWriteDisabledError
        self._validate_selection(profile, settings, model_catalog)
        with self._lock:
            profiles, current_revision = self._read()
            if revision != current_revision:
                raise ProfileRevisionConflictError
            profile_id = self._next_id(profile.name, {item.id for item in profiles})
            saved = profile.to_saved(profile_id)
            return self._write((*profiles, saved))

    def delete(
        self, profile_id: str, revision: str
    ) -> tuple[tuple[SavedProfile, ...], str]:
        if not self._writes_enabled:
            raise ProfileWriteDisabledError
        with self._lock:
            profiles, current_revision = self._read()
            if revision != current_revision:
                raise ProfileRevisionConflictError
            remaining = tuple(profile for profile in profiles if profile.id != profile_id)
            if len(remaining) == len(profiles):
                raise KeyError(profile_id)
            return self._write(remaining)

    @staticmethod
    def _validate_selection(
        profile: ProfileInput,
        settings: Settings,
        model_catalog: dict[str, tuple[ModelSettings, ...]],
    ) -> None:
        resolved = settings.resolve_options(
            profile.provider_id,
            profile.model_id,
            profile.effort,
            profile.japanese_style if profile.target_lang == "ja" else None,
            profile.target_lang,
            model_catalog,
        )
        if isinstance(resolved, str):
            raise ValueError("profile selection is not currently available")

    def _read(self) -> tuple[tuple[SavedProfile, ...], str]:
        if self._path is None or not self._path.exists():
            return (), self._revision(b"")
        contents = self._path.read_bytes()
        raw = tomllib.loads(contents.decode("utf-8"))
        profiles = raw.get("profiles", [])
        if not isinstance(profiles, list):
            raise ValueError("profiles TOML must contain a profiles array")
        parsed = tuple(SavedProfile.model_validate(item) for item in profiles)
        if len({profile.id for profile in parsed}) != len(parsed):
            raise ValueError("profile ids must be unique")
        return parsed, self._revision(contents)

    def _write(self, profiles: tuple[SavedProfile, ...]) -> tuple[tuple[SavedProfile, ...], str]:
        assert self._path is not None
        contents = self._serialize(profiles)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(
            prefix=f".{self._path.name}.", suffix=".tmp", dir=self._path.parent
        )
        try:
            with os.fdopen(descriptor, "wb") as file:
                file.write(contents)
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary, self._path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        return profiles, self._revision(contents)

    @staticmethod
    def _next_id(name: str, existing: set[str]) -> str:
        base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "profile"
        candidate, suffix = base, 2
        while candidate in existing:
            candidate = f"{base}-{suffix}"
            suffix += 1
        return candidate

    @staticmethod
    def _serialize(profiles: tuple[SavedProfile, ...]) -> bytes:
        lines = ["# Saved by TranslatorUI. Edit only while the application is stopped.", ""]
        for profile in profiles:
            lines.append("[[profiles]]")
            for key, value in profile.model_dump(exclude_none=True).items():
                lines.append(f"{key} = {json.dumps(value, ensure_ascii=False)}")
            lines.append("")
        return "\n".join(lines).encode("utf-8")

    @staticmethod
    def _revision(contents: bytes) -> str:
        return hashlib.sha256(contents).hexdigest()
