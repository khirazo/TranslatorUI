from pathlib import Path

import pytest
from app.config import ModelSettings, ProviderSettings, Settings
from app.main import create_app
from app.profiles import (
    ProfileInput,
    ProfileRevisionConflictError,
    ProfilesStore,
    ProfileWriteDisabledError,
)
from fastapi.testclient import TestClient


def profile_settings(path: Path, *, writes_enabled: bool = True) -> Settings:
    return Settings(
        allow_profile_writes=writes_enabled,
        profiles_file=path,
        default_provider_id="lmstudio",
        providers=(
            ProviderSettings(
                id="lmstudio",
                name="LM Studio",
                base_url="http://localhost:1234",
                model_overrides=(ModelSettings(id="qwen/qwen3-coder-next"),),
            ),
        ),
    )


def profile_input() -> ProfileInput:
    return ProfileInput(
        name="Qwen English to Japanese",
        provider_id="lmstudio",
        model_id="qwen/qwen3-coder-next",
        source_lang="en",
        target_lang="ja",
        japanese_style="plain",
    )


def test_profiles_store_creates_toml_with_a_server_generated_id(tmp_path) -> None:
    settings = profile_settings(tmp_path / "translator-ui.profiles.toml")
    store = ProfilesStore(settings)
    _, revision = store.current()

    profiles, revised = store.create(
        profile_input(),
        revision,
        settings,
        {"lmstudio": (ModelSettings(id="qwen/qwen3-coder-next"),)},
    )

    assert revised != revision
    assert profiles[0].id == "qwen-english-to-japanese"
    assert profiles[0].japanese_style == "plain"
    assert settings.profiles_file is not None
    assert "[[profiles]]" in settings.profiles_file.read_text(encoding="utf-8")


def test_profiles_store_rejects_disabled_writes_and_stale_revisions(tmp_path) -> None:
    path = tmp_path / "translator-ui.profiles.toml"
    disabled = profile_settings(path, writes_enabled=False)
    _, revision = ProfilesStore(disabled).current()
    with pytest.raises(ProfileWriteDisabledError):
        ProfilesStore(disabled).create(profile_input(), revision, disabled, {})

    settings = profile_settings(path)
    store = ProfilesStore(settings)
    _, revision = store.current()
    store.create(
        profile_input(),
        revision,
        settings,
        {"lmstudio": (ModelSettings(id="qwen/qwen3-coder-next"),)},
    )
    with pytest.raises(ProfileRevisionConflictError):
        store.create(
            profile_input(),
            revision,
            settings,
            {"lmstudio": (ModelSettings(id="qwen/qwen3-coder-next"),)},
        )


def test_profiles_api_saves_and_deletes_an_available_selection(tmp_path) -> None:
    settings = profile_settings(tmp_path / "translator-ui.profiles.toml")
    app = create_app(settings=settings)

    with TestClient(app) as client:
        initial = client.get("/api/profiles").json()
        created = client.post(
            "/api/profiles",
            json={
                "revision": initial["revision"],
                "profile": profile_input().model_dump(),
            },
        )
        assert created.status_code == 201
        created_body = created.json()
        profile_id = created_body["profiles"][0]["id"]
        deleted = client.request(
            "DELETE",
            f"/api/profiles/{profile_id}",
            json={"revision": created_body["revision"]},
        )

    assert deleted.status_code == 200
    assert deleted.json()["profiles"] == []
