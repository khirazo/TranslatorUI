"""Boundaries shared by translation providers."""

from collections.abc import AsyncIterator
from typing import Protocol


class TranslationProviderError(Exception):
    """An expected failure while communicating with a translation provider."""


class TranslationProvider(Protocol):
    """Produces translated text fragments for one translation request."""

    def translate(self, *, text: str, source_lang: str, target_lang: str) -> AsyncIterator[str]:
        """Yield translated text fragments in their received order."""
