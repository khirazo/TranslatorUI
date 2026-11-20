from app.config import Settings, SettingsLoader, SettingsStore


def test_toml_provider_registry_loads_secret_from_environment(tmp_path, monkeypatch) -> None:
    config_file = tmp_path / "translator-ui.toml"
    config_file.write_text(
        """
[app]
default_provider = "generic"

[[providers]]
id = "plamo"
name = "PLaMo"
kind = "openai_compatible"
enabled = true
base_url = "http://localhost:1234"
model = "plamo-3-translate-0.8b"
translation_profile = "plamo3"

[[providers]]
id = "generic"
name = "Generic"
kind = "openai_compatible"
enabled = true
base_url = "https://api.example.test"
model = "example-model"
api_key_env = "EXAMPLE_API_KEY"
translation_profile = "generic"

[[providers]]
id = "future-acp"
name = "Future ACP"
kind = "acp"
enabled = true
command = ["agent", "acp"]
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("EXAMPLE_API_KEY", "secret")

    settings = Settings.from_file(config_file)

    assert settings.default_provider_id == "generic"
    assert [provider.id for provider in settings.selectable_providers] == ["plamo", "generic"]
    assert settings.provider_for("generic").api_key == "secret"  # type: ignore[union-attr]
    assert settings.provider_for("future-acp") is None


def test_missing_explicit_config_file_is_rejected(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("TRANSLATOR_UI_CONFIG", str(tmp_path / "missing.toml"))

    try:
        Settings.from_environment()
    except ValueError as error:
        assert str(error) == "The configured provider registry is unavailable."
    else:
        raise AssertionError("An explicit missing config file must be rejected.")


def test_settings_store_reloads_a_valid_new_snapshot_and_rolls_back_on_failure(tmp_path) -> None:
    config_file = tmp_path / "translator-ui.toml"
    config_file.write_text(
        """
[app]
default_provider = "first"

[[providers]]
id = "first"
name = "First"
base_url = "http://first.test"
model = "first-model"
""",
        encoding="utf-8",
    )
    store = SettingsStore(
        SettingsLoader(
            environment={"TRANSLATOR_UI_CONFIG": str(config_file)}, env_file=tmp_path / ".env"
        )
    )
    original, generation = store.current()

    config_file.write_text("invalid", encoding="utf-8")
    try:
        store.reload()
    except ValueError:
        pass
    else:
        raise AssertionError("An invalid reload must fail.")

    current, current_generation = store.current()
    assert current == original
    assert current_generation == generation == 1
