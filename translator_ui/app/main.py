"""FastAPI routes for TranslatorUI's parallel text-translation service."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Annotated, Literal

import httpx
from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from pydantic import BaseModel

from app.config import ProviderSettings, Settings
from app.providers.base import TranslationProvider, TranslationProviderError
from app.providers.openai_compatible import OpenAICompatibleProvider
from app.storage import save_text_translation

logger = logging.getLogger(__name__)
STATIC_DIR = Path(__file__).resolve().parent / "static"
INDEX_FILE = STATIC_DIR / "index.html"
PdfClientFactory = Callable[[], httpx.AsyncClient]

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
    provider_id: str | None = None


def _sse(payload: dict[str, object]) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False, separators=(',', ':'))}\n\n"


def _pdf_response_headers(response: httpx.Response) -> dict[str, str]:
    return {
        header: value
        for header, value in response.headers.items()
        if header.lower() in {"content-type", "content-disposition", "content-length"}
    }


async def _proxy_pdf_request(
    client_factory: PdfClientFactory,
    method: str,
    url: str,
    **kwargs: object,
) -> Response:
    try:
        async with client_factory() as client:
            response = await client.request(method, url, **kwargs)
        return Response(
            content=response.content,
            status_code=response.status_code,
            headers=_pdf_response_headers(response),
        )
    except httpx.HTTPError:
        return JSONResponse({"error": "PDF gateway is unavailable."}, status_code=502)


async def _proxy_pdf_download(
    client_factory: PdfClientFactory, url: str
) -> Response | StreamingResponse:
    client = client_factory()
    try:
        request = client.build_request("GET", url)
        response = await client.send(request, stream=True)
    except httpx.HTTPError:
        await client.aclose()
        return JSONResponse({"error": "PDF gateway is unavailable."}, status_code=502)

    async def body() -> AsyncIterator[bytes]:
        try:
            async for chunk in response.aiter_bytes():
                yield chunk
        finally:
            await response.aclose()
            await client.aclose()

    return StreamingResponse(
        body(),
        status_code=response.status_code,
        headers=_pdf_response_headers(response),
    )


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
    provider_settings = settings.provider_for(payload.provider_id)
    if provider_settings is None:
        yield _sse({"error": "The selected translation provider is unavailable."})
        return
    started_at = time.monotonic()
    first_token_at: float | None = None
    token_count = 0
    translated_parts: list[str] = []

    try:
        provider = provider_factory(provider_settings)
        translation = provider.translate(
            text=payload.text, source_lang=source_lang, target_lang=target_lang
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
    pdf_client_factory: PdfClientFactory | None = None,
) -> FastAPI:
    """Create an application, allowing tests to substitute its provider boundary."""
    app = FastAPI()
    app.state.settings = settings or Settings.from_environment()
    app.state.provider_factory = provider_factory or OpenAICompatibleProvider
    app.state.pdf_client_factory = pdf_client_factory or (
        lambda: httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=10.0))
    )

    @app.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        return FileResponse(INDEX_FILE)

    @app.get("/health")
    async def health() -> JSONResponse:
        return JSONResponse({"status": "ok"})

    @app.get("/api/providers")
    async def providers() -> JSONResponse:
        configured_settings: Settings = app.state.settings
        return JSONResponse(
            {
                "default_provider_id": configured_settings.default_provider_id,
                "providers": [
                    {"id": provider.id, "name": provider.name}
                    for provider in configured_settings.selectable_providers
                ],
            }
        )

    @app.post("/api/translate-text")
    async def translate_text(payload: TranslateRequest, request: Request) -> StreamingResponse:
        return StreamingResponse(
            stream_translation_events(
                payload=payload,
                request=request,
                settings=request.app.state.settings,
                provider_factory=request.app.state.provider_factory,
            ),
            media_type="text/event-stream",
        )

    @app.post("/api/translate-pdf")
    async def translate_pdf(
        file: Annotated[UploadFile, File()],
        source_lang: Annotated[str, Form()] = "en",
        target_lang: Annotated[str, Form()] = "ja",
        pages: Annotated[str | None, Form()] = None,
    ) -> Response:
        gateway_url = f"{app.state.settings.pdf_gateway_url}/api/translate-pdf"
        form_data = {"source_lang": source_lang, "target_lang": target_lang}
        if pages is not None:
            form_data["pages"] = pages
        content = await file.read()
        return await _proxy_pdf_request(
            app.state.pdf_client_factory,
            "POST",
            gateway_url,
            data=form_data,
            files={
                "file": (
                    file.filename or "upload.pdf",
                    content,
                    file.content_type or "application/pdf",
                )
            },
        )

    @app.get("/api/translate-pdf/{task_id}/status")
    async def pdf_status(task_id: str) -> Response:
        return await _proxy_pdf_request(
            app.state.pdf_client_factory,
            "GET",
            f"{app.state.settings.pdf_gateway_url}/api/translate-pdf/{task_id}/status",
        )

    @app.get("/api/translate-pdf/{task_id}/{variant}")
    async def download_pdf(task_id: str, variant: Literal["mono", "dual"]) -> Response:
        return await _proxy_pdf_download(
            app.state.pdf_client_factory,
            f"{app.state.settings.pdf_gateway_url}/api/translate-pdf/{task_id}/{variant}",
        )

    @app.delete("/api/translate-pdf/{task_id}")
    async def cancel_pdf(task_id: str) -> Response:
        return await _proxy_pdf_request(
            app.state.pdf_client_factory,
            "DELETE",
            f"{app.state.settings.pdf_gateway_url}/api/translate-pdf/{task_id}",
        )

    return app


app = create_app()
