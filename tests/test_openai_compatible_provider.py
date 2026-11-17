import json
from collections.abc import AsyncIterator

import httpx
import pytest
from app.config import Settings
from app.providers.base import TranslationProviderError
from app.providers.openai_compatible import PLAMO_STOP_TOKENS, OpenAICompatibleProvider


class ChunkStream(httpx.AsyncByteStream):
    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = chunks
        self.closed = False

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for chunk in self._chunks:
            yield chunk

    async def aclose(self) -> None:
        self.closed = True


def provider_for(handler: httpx.MockTransport) -> OpenAICompatibleProvider:
    client = httpx.AsyncClient(transport=handler)
    return OpenAICompatibleProvider(
        Settings(llm_endpoint="http://llm.test", llm_api_key="secret-key"), client
    )


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
        "messages": [{"role": "user", "content": "こんにちは"}],
        "stream": True,
        "temperature": 0,
        "max_tokens": 512,
        "chat_template_kwargs": {"source_lang": "ja", "target_lang": "en"},
        "stop": PLAMO_STOP_TOKENS,
    }


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
