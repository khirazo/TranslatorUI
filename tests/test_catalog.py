import logging

import httpx
import pytest
from app.catalog import ProviderCatalogStore
from app.config import ModelSettings, ProviderSettings, Settings
from app.providers.base import TranslationProviderError


def catalog_settings() -> Settings:
    return Settings(
        default_provider_id="lmstudio",
        providers=(
            ProviderSettings(
                id="lmstudio",
                name="LM Studio",
                base_url="http://lmstudio.test",
                model="plamo-3-translate-0.8b",
                api_key="catalog-secret",
                model_overrides=(
                    ModelSettings(
                        id="plamo-3-translate-0.8b",
                        name="PLaMo",
                        translation_profile="plamo3",
                    ),
                ),
            ),
        ),
    )


@pytest.mark.asyncio
async def test_catalog_refresh_uses_live_ids_and_merges_toml_metadata(caplog) -> None:
    caplog.set_level(logging.INFO, logger="uvicorn.error")

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "http://lmstudio.test/v1/models"
        assert request.headers["authorization"] == "Bearer catalog-secret"
        return httpx.Response(
            200,
            json={
                "data": [
                    {"id": "qwen/qwen3-coder-next"},
                    {"id": "plamo-3-translate-0.8b"},
                    {"id": "qwen/qwen3-coder-next"},
                    {"id": ""},
                ]
            },
        )

    store = ProviderCatalogStore(
        catalog_settings(),
        client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        initial_catalog=True,
    )

    catalog, generation = await store.refresh(catalog_settings())

    assert generation == 2
    assert [model.id for model in catalog["lmstudio"]] == [
        "plamo-3-translate-0.8b",
        "qwen/qwen3-coder-next",
    ]
    assert catalog["lmstudio"][0].display_name == "PLaMo"
    assert "Refreshing model catalog for provider lmstudio" in caplog.text
    assert "Model catalog for provider lmstudio contains 2 model(s)" in caplog.text
    assert catalog["lmstudio"][0].translation_profile == "plamo3"
    resolved = catalog_settings().resolve_options(
        "lmstudio", "qwen/qwen3-coder-next", None, None, "en", catalog
    )
    assert not isinstance(resolved, str)
    assert resolved[1].translation_profile == "plamo3"
    assert (
        catalog_settings().resolve_options("lmstudio", "not-listed", None, None, "en", catalog)
        == "The selected translation model is unavailable."
    )


@pytest.mark.asyncio
async def test_catalog_refresh_logs_acp_auth_failure(monkeypatch, caplog) -> None:
    settings = Settings(
        default_provider_id="lmstudio",
        providers=(
            *catalog_settings().providers,
            ProviderSettings(id="acp", name="ACP", kind="acp", command=("agent",)),
        ),
    )

    async def fail_discovery(self) -> tuple[ModelSettings, ...]:
        raise TranslationProviderError("ACP initialize failed: Authentication required.")

    monkeypatch.setattr("app.catalog.AcpProvider.discover_models", fail_discovery)
    catalog, _ = await ProviderCatalogStore(settings, initial_catalog=True).refresh(settings)

    assert [model.id for model in catalog["acp"]] == ["agent-default"]
    assert "ACP model catalog refresh failed for provider acp" in caplog.text
    assert "Authentication required" in caplog.text


@pytest.mark.asyncio
async def test_catalog_refresh_keeps_the_previous_entry_on_provider_failure() -> None:
    settings = catalog_settings()
    store = ProviderCatalogStore(
        settings,
        client_factory=lambda: httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(503))
        ),
        initial_catalog=True,
    )

    catalog, generation = await store.refresh(settings)

    assert generation == 2
    assert [model.id for model in catalog["lmstudio"]] == ["plamo-3-translate-0.8b"]
