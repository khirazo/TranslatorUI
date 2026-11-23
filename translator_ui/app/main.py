"""FastAPI routes for TranslatorUI's parallel text-translation service."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.catalog import ProviderCatalogStore
from app.config import ModelSettings, ProviderSettings, Settings, SettingsStore
from app.profiles import (
    ProfileInput,
    ProfileRevisionConflictError,
    ProfilesStore,
    ProfileWriteDisabledError,
)
from app.providers.acp import AcpProvider
from app.providers.base import TranslationProvider, TranslationProviderError
from app.providers.openai_compatible import OpenAICompatibleProvider
from app.storage import save_text_translation

logger = logging.getLogger(__name__)
STATIC_DIR = Path(__file__).resolve().parent / "static"
INDEX_FILE = STATIC_DIR / "index.html"

LANGUAGE_CODES = {
    "ja",
    "en",
    "ko",
    "ar",
    "it",
    "id",
    "nl",
    "es",
    "th",
    "de",
    "fr",
    "vi",
    "ru",
    "zh",
    "zh-tw",
}
LANGUAGE_ALIASES = {"zh": "zh-hans", "zh-tw": "zh-hant"}


def provider_for_settings(settings: ProviderSettings) -> TranslationProvider:
    return AcpProvider(settings) if settings.kind == "acp" else OpenAICompatibleProvider(settings)


class TranslateRequest(BaseModel):
    """The existing browser request body for text translation."""

    text: str
    source_lang: str = "auto"
    target_lang: str = "auto"
    provider_id: str | None = None
    model_id: str | None = None
    effort: str | None = None
    japanese_style: Literal["polite", "plain"] | None = None


class ProfileCreateRequest(BaseModel):
    revision: str
    profile: ProfileInput


class ProfileDeleteRequest(BaseModel):
    revision: str


def _sse(payload: dict[str, object]) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False, separators=(',', ':'))}\n\n"


def _validate_language_pair(source_lang: str, target_lang: str) -> tuple[str, str] | str:
    if source_lang in {"auto", "ja-easy"} or target_lang in {"auto", "ja-easy"}:
        return "auto and ja-easy are not supported by the PLaMo 3 MVP."
    if source_lang not in LANGUAGE_CODES or target_lang not in LANGUAGE_CODES:
        return "An unsupported source_lang or target_lang was provided."
    return LANGUAGE_ALIASES.get(source_lang, source_lang), LANGUAGE_ALIASES.get(
        target_lang, target_lang
    )


async def stream_translation_events(
    *,
    payload: TranslateRequest,
    request: Request,
    settings: Settings,
    model_catalog: dict[str, tuple[ModelSettings, ...]] | None,
    provider_factory: Callable[[ProviderSettings], TranslationProvider],
) -> AsyncIterator[str]:
    """Produce client-facing SSE events and stop the provider on browser disconnect."""
    if not payload.text:
        yield _sse({"error": "text must not be empty."})
        return
    language_pair = _validate_language_pair(payload.source_lang, payload.target_lang)
    if isinstance(language_pair, str):
        yield _sse({"error": language_pair})
        return

    source_lang, target_lang = language_pair
    resolved = settings.resolve_options(
        payload.provider_id,
        payload.model_id,
        payload.effort,
        payload.japanese_style,
        payload.target_lang,
        model_catalog,
    )
    if isinstance(resolved, str):
        yield _sse({"error": resolved})
        return
    provider_settings, options = resolved
    started_at = time.monotonic()
    first_token_at: float | None = None
    token_count = 0
    translated_parts: list[str] = []

    try:
        provider = provider_factory(provider_settings)
        translation = provider.translate(
            text=payload.text, source_lang=source_lang, target_lang=target_lang, options=options
        )
        try:
            async for token in translation:
                if await request.is_disconnected():
                    return
                first_token_at = first_token_at or time.monotonic()
                token_count += 1
                translated_parts.append(token)
                yield _sse({"token": token})
        finally:
            aclose = getattr(translation, "aclose", None)
            if aclose is not None:
                await aclose()

        if await request.is_disconnected():
            return
        if settings.save_translations and translated_parts:
            elapsed = time.monotonic() - started_at
            try:
                save_text_translation(
                    input_text=payload.text,
                    output_text="".join(translated_parts),
                    source_lang=payload.source_lang,
                    target_lang=payload.target_lang,
                    metrics={
                        "token_count": token_count,
                        "time_to_first_token": round(
                            (first_token_at or started_at) - started_at, 3
                        ),
                        "total_time": round(elapsed, 3),
                        "tokens_per_sec": round(token_count / elapsed, 2) if elapsed else 0,
                    },
                )
            except OSError:
                logger.exception("Failed to save a translation history record")
        yield _sse({"done": True})
    except asyncio.CancelledError:
        return
    except TranslationProviderError as error:
        yield _sse({"error": str(error)})
    except Exception:
        logger.exception("Unexpected translation request failure")
        yield _sse({"error": "Translation failed unexpectedly."})


def create_app(
    settings: Settings | None = None,
    provider_factory: Callable[[ProviderSettings], TranslationProvider] | None = None,
) -> FastAPI:
    """Create an application, allowing tests to substitute its provider boundary."""

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        if application.state.settings_store is not None:
            await application.state.catalog_store.refresh(application.state.settings)
        yield

    app = FastAPI(lifespan=lifespan)
    app.state.settings_store = SettingsStore() if settings is None else None
    app.state.settings = settings or app.state.settings_store.current()[0]
    app.state.catalog_store = ProviderCatalogStore(
        app.state.settings, initial_catalog=settings is not None
    )
    app.state.profiles_store = ProfilesStore(app.state.settings)
    app.state.provider_factory = provider_factory or provider_for_settings
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        return FileResponse(INDEX_FILE)

    @app.get("/health")
    async def health() -> JSONResponse:
        return JSONResponse({"status": "ok"})

    @app.get("/api/providers")
    async def providers() -> JSONResponse:
        store = app.state.settings_store
        configured_settings, generation = store.current() if store else (app.state.settings, 1)
        catalog, catalog_generation = app.state.catalog_store.current()
        return JSONResponse(
            configured_settings.provider_choices(generation, catalog, catalog_generation)
        )

    @app.post("/api/settings/reload")
    async def reload_settings() -> JSONResponse:
        store = app.state.settings_store
        if store is None:
            return JSONResponse(
                {"detail": "Configuration reload failed: unavailable."}, status_code=422
            )
        try:
            configured_settings, generation = store.reload()
        except Exception:
            logger.warning("Configuration reload failed")
            return JSONResponse(
                {"detail": "Configuration reload failed: invalid configuration."}, status_code=422
            )
        app.state.settings = configured_settings
        app.state.profiles_store = ProfilesStore(configured_settings)
        catalog, catalog_generation = await app.state.catalog_store.refresh(configured_settings)
        return JSONResponse(
            configured_settings.provider_choices(generation, catalog, catalog_generation)
        )

    @app.get("/api/profiles")
    async def profiles(request: Request) -> JSONResponse:
        try:
            saved_profiles, revision = request.app.state.profiles_store.current()
        except (OSError, ValueError):
            return JSONResponse({"detail": "Profiles could not be read."}, status_code=422)
        return JSONResponse(
            {
                "revision": revision,
                "writes_enabled": request.app.state.profiles_store.writes_enabled,
                "profiles": [profile.model_dump() for profile in saved_profiles],
            }
        )

    @app.post("/api/profiles", status_code=201)
    async def create_profile(payload: ProfileCreateRequest, request: Request) -> JSONResponse:
        language_pair = _validate_language_pair(
            payload.profile.source_lang, payload.profile.target_lang
        )
        if isinstance(language_pair, str):
            return JSONResponse(
                {"detail": "Profile language selection is invalid."}, status_code=422
            )
        settings_snapshot = (
            request.app.state.settings_store.current()[0]
            if request.app.state.settings_store
            else request.app.state.settings
        )
        catalog, _ = request.app.state.catalog_store.current()
        try:
            profiles, revision = request.app.state.profiles_store.create(
                payload.profile, payload.revision, settings_snapshot, catalog
            )
        except ProfileWriteDisabledError:
            return JSONResponse({"detail": "Profile writes are disabled."}, status_code=403)
        except ProfileRevisionConflictError:
            return JSONResponse(
                {"detail": "Profiles changed; reload before saving."}, status_code=409
            )
        except (OSError, ValueError):
            return JSONResponse({"detail": "Profile could not be saved."}, status_code=422)
        return JSONResponse(
            {
                "revision": revision,
                "writes_enabled": request.app.state.profiles_store.writes_enabled,
                "profiles": [profile.model_dump() for profile in profiles],
            },
            status_code=201,
        )

    @app.delete("/api/profiles/{profile_id}")
    async def delete_profile(
        profile_id: str, payload: ProfileDeleteRequest, request: Request
    ) -> JSONResponse:
        try:
            profiles, revision = request.app.state.profiles_store.delete(
                profile_id, payload.revision
            )
        except ProfileWriteDisabledError:
            return JSONResponse({"detail": "Profile writes are disabled."}, status_code=403)
        except ProfileRevisionConflictError:
            return JSONResponse(
                {"detail": "Profiles changed; reload before deleting."}, status_code=409
            )
        except KeyError:
            return JSONResponse({"detail": "Profile is unavailable."}, status_code=404)
        except OSError:
            return JSONResponse({"detail": "Profile could not be deleted."}, status_code=422)
        return JSONResponse(
            {
                "revision": revision,
                "writes_enabled": request.app.state.profiles_store.writes_enabled,
                "profiles": [profile.model_dump() for profile in profiles],
            }
        )

    @app.post("/api/translate-text")
    async def translate_text(payload: TranslateRequest, request: Request) -> StreamingResponse:
        catalog, _ = request.app.state.catalog_store.current()
        return StreamingResponse(
            stream_translation_events(
                payload=payload,
                request=request,
                settings=(
                    request.app.state.settings_store.current()[0]
                    if request.app.state.settings_store
                    else request.app.state.settings
                ),
                model_catalog=catalog,
                provider_factory=request.app.state.provider_factory,
            ),
            media_type="text/event-stream",
        )

    return app


app = create_app()
