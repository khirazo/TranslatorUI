"""Streaming provider for OpenAI-compatible Chat Completions endpoints."""

from __future__ import annotations

import codecs
import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

from app.config import Settings
from app.providers.base import TranslationProviderError

PLAMO_STOP_TOKENS = ["<|plamo:tag|>", "<|plamo:bos|>"]


class OpenAICompatibleProvider:
    """Translate via PLaMo 3's OpenAI-compatible Chat Completions interface."""

    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None) -> None:
        self._settings = settings
        self._client = client

    def _request_payload(self, *, text: str, source_lang: str, target_lang: str) -> dict[str, Any]:
        return {
            "model": self._settings.llm_model,
            "messages": [{"role": "user", "content": text}],
            "stream": True,
            "temperature": 0,
            "max_tokens": self._settings.llm_max_tokens,
            "chat_template_kwargs": {
                "source_lang": source_lang,
                "target_lang": target_lang,
            },
            "stop": PLAMO_STOP_TOKENS,
        }

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._settings.llm_api_key:
            headers["Authorization"] = f"Bearer {self._settings.llm_api_key}"
        return headers

    async def translate(
        self, *, text: str, source_lang: str, target_lang: str
    ) -> AsyncIterator[str]:
        """Yield content fields from an upstream OpenAI-style SSE response."""
        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=10.0))
        try:
            async with client.stream(
                "POST",
                f"{self._settings.llm_endpoint}/v1/chat/completions",
                headers=self._headers(),
                json=self._request_payload(
                    text=text, source_lang=source_lang, target_lang=target_lang
                ),
            ) as response:
                if response.status_code != httpx.codes.OK:
                    raise TranslationProviderError(
                        f"Translation provider returned HTTP {response.status_code}."
                    )

                async for event_data in self._sse_data_events(response):
                    if event_data == "[DONE]":
                        return
                    try:
                        payload = json.loads(event_data)
                    except json.JSONDecodeError as error:
                        raise TranslationProviderError(
                            "Translation provider returned malformed streaming data."
                        ) from error

                    choices = payload.get("choices")
                    if not isinstance(choices, list) or not choices:
                        continue
                    choice = choices[0]
                    if not isinstance(choice, dict):
                        continue
                    delta = choice.get("delta")
                    if isinstance(delta, dict) and isinstance(delta.get("content"), str):
                        yield delta["content"]
                    if choice.get("finish_reason") is not None:
                        return
        except httpx.HTTPError as error:
            raise TranslationProviderError(
                "Could not connect to the translation provider."
            ) from error
        finally:
            if owns_client:
                await client.aclose()

    async def _sse_data_events(self, response: httpx.Response) -> AsyncIterator[str]:
        """Parse SSE data fields correctly even when UTF-8 or lines cross byte chunks."""
        decoder = codecs.getincrementaldecoder("utf-8")()
        buffer = ""
        async for chunk in response.aiter_bytes():
            buffer += decoder.decode(chunk)
            lines = buffer.splitlines(keepends=True)
            buffer = ""
            if lines and not lines[-1].endswith(("\n", "\r")):
                buffer = lines.pop()
            for line in lines:
                data = line.strip()
                if data.startswith("data:"):
                    yield data[5:].lstrip()
        buffer += decoder.decode(b"", final=True)
        if buffer.strip().startswith("data:"):
            yield buffer.strip()[5:].lstrip()
