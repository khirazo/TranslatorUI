import asyncio
import json
from collections.abc import AsyncIterator

import httpx
import pytest
from app.config import ProviderSettings, TranslationOptions
from app.providers.base import TranslationProviderError
from app.providers.openai_compatible import (
    PLAMO_STOP_TOKENS,
    OpenAICompatibleProvider,
    build_pfml3_prompt,
)


class ChunkStream(httpx.AsyncByteStream):
    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = chunks
        self.closed = False

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for chunk in self._chunks:
            yield chunk

    async def aclose(self) -> None:
        self.closed = True


class BlockingStream(httpx.AsyncByteStream):
    def __init__(self) -> None:
        self.closed = False
        self._release = asyncio.Event()

    async def __aiter__(self) -> AsyncIterator[bytes]:
        yield b'data: {"choices":[{"delta":{"content":"first"}}]}\n\n'
        await self._release.wait()

    async def aclose(self) -> None:
        self.closed = True
        self._release.set()


def provider_settings(**overrides: object) -> ProviderSettings:
    values: dict[str, object] = {
        "id": "test",
        "name": "Test provider",
        "base_url": "http://llm.test",
        "model": "plamo-3-translate-0.8b",
        "api_key": "secret-key",
    }
    values.update(overrides)
    return ProviderSettings(**values)


def provider_for(handler: httpx.MockTransport) -> OpenAICompatibleProvider:
    client = httpx.AsyncClient(transport=handler)
    return OpenAICompatibleProvider(provider_settings(), client)


def test_provider_settings_resolve_default_relative_and_explicit_api_endpoints() -> None:
    settings = provider_settings(base_url="http://provider.test/root/")
    assert settings.model_url == "http://provider.test/v1/models"
    assert settings.chat_url == "http://provider.test/v1/chat/completions"

    custom = provider_settings(
        base_url="http://provider.test/base",
        model_endpoint="/catalog/models",
        chat_endpoint="https://chat.provider.test/generate",
    )
    assert custom.model_url == "http://provider.test/catalog/models"
    assert custom.chat_url == "https://chat.provider.test/generate"


@pytest.mark.asyncio
async def test_provider_parses_events_split_at_arbitrary_byte_boundaries() -> None:
    upstream = (
        b'data: {"choices":[{"delta":{"content":"\xe3\x81\x93\xe3\x82\x93"}}]}\n\n'
        b'data: {"choices":[{"delta":{"content":"\xe3\x81\xab\xe3\x81\xa1\xe3\x81\xaf"}}]}\n\n'
        b"data: [DONE]\n\n"
    )
    chunks = [upstream[index : index + 5] for index in range(0, len(upstream), 5)]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=ChunkStream(chunks))

    provider = provider_for(httpx.MockTransport(handler))
    tokens = [
        token
        async for token in provider.translate(text="hello", source_lang="en", target_lang="ja")
    ]

    assert tokens == ["こん", "にちは"]


@pytest.mark.asyncio
async def test_provider_stops_on_finish_reason_and_sends_plamo_three_payload() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["headers"] = dict(request.headers)
        captured["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            content=b'data: {"choices":[{"delta":{"content":"hi"},"finish_reason":"stop"}]}\n\n',
        )

    provider = provider_for(httpx.MockTransport(handler))
    tokens = [
        token
        async for token in provider.translate(text="こんにちは", source_lang="ja", target_lang="en")
    ]

    assert tokens == ["hi"]
    assert captured["headers"]["authorization"] == "Bearer secret-key"  # type: ignore[index]
    assert captured["payload"] == {
        "model": "plamo-3-translate-0.8b",
        "messages": [
            {
                "role": "user",
                "content": build_pfml3_prompt(
                    text="こんにちは", source_lang="ja", target_lang="en", form=None
                ),
            }
        ],
        "stream": True,
        "temperature": 0,
        "max_tokens": 512,
        "stop": PLAMO_STOP_TOKENS,
    }


def test_generic_profile_omits_plamo_specific_prompt_fields() -> None:
    provider = OpenAICompatibleProvider(
        provider_settings(translation_profile="generic", model="generic-model")
    )

    payload = provider._request_payload(text="hello", source_lang="en", target_lang="ja")

    assert payload == {
        "model": "generic-model",
        "messages": [{"role": "user", "content": "hello"}],
        "stream": True,
        "temperature": 0,
        "max_tokens": 512,
    }


@pytest.mark.parametrize("style", ["polite", "plain"])
def test_plamo_three_sends_japanese_form_in_chat_template_kwargs(style: str) -> None:
    provider = OpenAICompatibleProvider(provider_settings())

    payload = provider._request_payload(
        text="hello",
        source_lang="en",
        target_lang="ja",
        options=TranslationOptions(model_id="plamo-3-translate-0.8b", japanese_style=style),
    )

    assert payload["messages"] == [
        {
            "role": "user",
            "content": build_pfml3_prompt(
                text="hello", source_lang="en", target_lang="ja", form=style
            ),
        }
    ]


@pytest.mark.asyncio
async def test_provider_uses_configured_chat_endpoint() -> None:
    received_url: str | None = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal received_url
        received_url = str(request.url)
        return httpx.Response(200, content=b"data: [DONE]\n\n")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = OpenAICompatibleProvider(
        provider_settings(base_url="http://provider.test", chat_endpoint="/custom/openai/chat"),
        client,
    )
    tokens = [
        token
        async for token in provider.translate(text="hello", source_lang="en", target_lang="ja")
    ]

    assert tokens == []
    assert received_url == "http://provider.test/custom/openai/chat"


@pytest.mark.asyncio
async def test_closing_provider_generator_closes_upstream_stream() -> None:
    stream = BlockingStream()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=stream)

    provider = provider_for(httpx.MockTransport(handler))
    translation = provider.translate(text="hello", source_lang="en", target_lang="ja")

    assert await anext(translation) == "first"
    await translation.aclose()

    assert stream.closed is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status_code", "body", "message"),
    [
        (503, b"unavailable", "Translation provider returned HTTP 503."),
        (200, b"data: not-json\n\n", "Translation provider returned malformed streaming data."),
    ],
)
async def test_provider_surfaces_http_and_malformed_stream_failures(
    status_code: int, body: bytes, message: str
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, content=body)

    provider = provider_for(httpx.MockTransport(handler))
    with pytest.raises(TranslationProviderError, match=message):
        async for _ in provider.translate(text="hello", source_lang="en", target_lang="ja"):
            pass


@pytest.mark.asyncio
async def test_provider_surfaces_connection_failure() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline", request=request)

    provider = provider_for(httpx.MockTransport(handler))
    with pytest.raises(TranslationProviderError, match="Could not connect"):
        async for _ in provider.translate(text="hello", source_lang="en", target_lang="ja"):
            pass
