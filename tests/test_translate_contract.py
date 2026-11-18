from collections.abc import AsyncIterator

from app.config import Settings
from app.main import TranslateRequest, create_app, stream_translation_events
from app.providers.base import TranslationProviderError
from fastapi.testclient import TestClient


class TokenProvider:
    async def translate(
        self, *, text: str, source_lang: str, target_lang: str
    ) -> AsyncIterator[str]:
        assert text == "hello"
        assert (source_lang, target_lang) == ("en", "ja")
        yield "こんにちは"
        yield "。"


class FailingProvider:
    async def translate(
        self, *, text: str, source_lang: str, target_lang: str
    ) -> AsyncIterator[str]:
        raise TranslationProviderError("Could not connect to the translation provider.")
        yield ""  # pragma: no cover


class DisconnectingRequest:
    def __init__(self) -> None:
        self._checks = 0

    async def is_disconnected(self) -> bool:
        self._checks += 1
        return self._checks > 1


def make_client(provider_factory: object) -> TestClient:
    app = create_app(settings=Settings(), provider_factory=provider_factory)  # type: ignore[arg-type]
    return TestClient(app)


def test_translate_stream_preserves_token_and_done_contract() -> None:
    with make_client(lambda settings: TokenProvider()) as client:
        response = client.post(
            "/api/translate-text",
            json={"text": "hello", "source_lang": "en", "target_lang": "ja"},
        )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.text == (
        'data: {"token":"こんにちは"}\n\ndata: {"token":"。"}\n\ndata: {"done":true}\n\n'
    )


def test_translate_converts_chinese_codes_for_plamo_three() -> None:
    received: list[tuple[str, str]] = []

    class ChineseProvider:
        async def translate(
            self, *, text: str, source_lang: str, target_lang: str
        ) -> AsyncIterator[str]:
            received.append((source_lang, target_lang))
            yield "你好"

    with make_client(lambda settings: ChineseProvider()) as client:
        response = client.post(
            "/api/translate-text",
            json={"text": "こんにちは", "source_lang": "ja", "target_lang": "zh"},
        )

    assert response.text.endswith('data: {"done":true}\n\n')
    assert received == [("ja", "zh-hans")]


def test_translate_rejects_auto_and_easy_japanese_with_one_error_event() -> None:
    with make_client(lambda settings: TokenProvider()) as client:
        response = client.post(
            "/api/translate-text",
            json={"text": "hello", "source_lang": "auto", "target_lang": "ja"},
        )

    assert response.text.count("data: ") == 1
    assert '"error"' in response.text
    assert '"done"' not in response.text


def test_translate_emits_one_error_for_provider_failure() -> None:
    with make_client(lambda settings: FailingProvider()) as client:
        response = client.post(
            "/api/translate-text",
            json={"text": "hello", "source_lang": "en", "target_lang": "ja"},
        )

    assert response.text == ('data: {"error":"Could not connect to the translation provider."}\n\n')


async def test_disconnect_closes_provider_without_done_or_error() -> None:
    provider_closed = False

    class DelayedProvider:
        async def translate(
            self, *, text: str, source_lang: str, target_lang: str
        ) -> AsyncIterator[str]:
            nonlocal provider_closed
            try:
                yield "first"
                yield "second"
            finally:
                provider_closed = True

    events = [
        event
        async for event in stream_translation_events(
            payload=TranslateRequest(text="hello", source_lang="en", target_lang="ja"),
            request=DisconnectingRequest(),  # type: ignore[arg-type]
            settings=Settings(),
            provider_factory=lambda settings: DelayedProvider(),
        )
    ]

    assert events == ['data: {"token":"first"}\n\n']
    assert provider_closed is True
    assert not any('"done"' in event or '"error"' in event for event in events)
