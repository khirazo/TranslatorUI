"""Live model catalogs for OpenAI-compatible translation providers."""

from __future__ import annotations

from collections.abc import Callable
from threading import Lock

import httpx

from app.config import ModelSettings, ProviderSettings, Settings
from app.providers.acp import AcpProvider
from app.providers.base import TranslationProviderError


class ProviderCatalogStore:
    """Refresh live model ids without replacing the last known catalog on failure."""

    def __init__(
        self,
        settings: Settings,
        client_factory: Callable[[], httpx.AsyncClient] | None = None,
        initial_catalog: bool = False,
    ) -> None:
        self._lock = Lock()
        self._client_factory = client_factory or (
            lambda: httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=5.0), trust_env=True)
        )
        self._catalog = (
            {provider.id: provider.selectable_models for provider in settings.selectable_providers}
            if initial_catalog
            else {}
        )
        self._generation = 1

    def current(self) -> tuple[dict[str, tuple[ModelSettings, ...]], int]:
        with self._lock:
            return dict(self._catalog), self._generation

    async def refresh(self, settings: Settings) -> tuple[dict[str, tuple[ModelSettings, ...]], int]:
        """Query every provider and retain its previous entry if its query fails."""
        previous, _ = self.current()
        refreshed: dict[str, tuple[ModelSettings, ...]] = {}
        async with self._client_factory() as client:
            for provider in settings.openai_compatible_providers:
                try:
                    response = await client.get(provider.model_url, headers=self._headers(provider))
                    response.raise_for_status()
                    raw_models = response.json().get("data")
                    if not isinstance(raw_models, list):
                        raise ValueError("model catalog data must be a list")
                    ids = sorted(
                        {
                            item["id"].strip()
                            for item in raw_models
                            if isinstance(item, dict)
                            and isinstance(item.get("id"), str)
                            and item["id"].strip()
                        }
                    )
                    refreshed[provider.id] = tuple(
                        provider.model_for_catalog(model_id) for model_id in ids
                    )
                except (httpx.HTTPError, ValueError, TypeError):
                    if provider.id in previous:
                        refreshed[provider.id] = previous[provider.id]
        for provider in settings.selectable_providers:
            if provider.kind != "acp":
                continue
            try:
                refreshed[provider.id] = await AcpProvider(provider).discover_models()
            except TranslationProviderError:
                if provider.id in previous:
                    refreshed[provider.id] = previous[provider.id]
        with self._lock:
            self._catalog = refreshed
            self._generation += 1
            return dict(self._catalog), self._generation

    @staticmethod
    def _headers(provider: ProviderSettings) -> dict[str, str]:
        return {"Authorization": f"Bearer {provider.api_key}"} if provider.api_key else {}
