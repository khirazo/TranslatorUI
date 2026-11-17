"""FastAPI routes for TranslatorUI's parallel text-translation service."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator, Callable

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from app.config import Settings
from app.providers.base import TranslationProvider, TranslationProviderError
from app.providers.openai_compatible import OpenAICompatibleProvider
from app.storage import save_text_translation

logger = logging.getLogger(__name__)

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


class TranslateRequest(BaseModel):
    """The existing browser request body for text translation."""

    text: str
    source_lang: str = "auto"
    target_lang: str = "auto"


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


def create_app(
    settings: Settings | None = None,
    provider_factory: Callable[[Settings], TranslationProvider] | None = None,
) -> FastAPI:
    """Create an application, allowing tests to substitute its provider boundary."""
    app = FastAPI()
    app.state.settings = settings or Settings.from_environment()
    app.state.provider_factory = provider_factory or OpenAICompatibleProvider

    @app.get("/health")
    async def health() -> JSONResponse:
        return JSONResponse({"status": "ok"})

    @app.post("/api/translate-text")
    async def translate_text(payload: TranslateRequest, request: Request) -> StreamingResponse:
        async def events() -> AsyncIterator[str]:
            if not payload.text:
                yield _sse({"error": "text must not be empty."})
                return
            language_pair = _validate_language_pair(payload.source_lang, payload.target_lang)
            if isinstance(language_pair, str):
                yield _sse({"error": language_pair})
                return

            source_lang, target_lang = language_pair
            started_at = time.monotonic()
            first_token_at: float | None = None
            token_count = 0
            translated_parts: list[str] = []

            try:
                provider = request.app.state.provider_factory(request.app.state.settings)
                async for token in provider.translate(
                    text=payload.text, source_lang=source_lang, target_lang=target_lang
                ):
                    if await request.is_disconnected():
                        return
                    first_token_at = first_token_at or time.monotonic()
                    token_count += 1
                    translated_parts.append(token)
                    yield _sse({"token": token})

                if await request.is_disconnected():
                    return
                if request.app.state.settings.save_translations and translated_parts:
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

        return StreamingResponse(events(), media_type="text/event-stream")

    return app


app = create_app()
