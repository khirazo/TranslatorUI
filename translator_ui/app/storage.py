"""Compatibility helpers for the existing translation-history JSON format."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DEFAULT_TRANSLATIONS_FILE = (
    Path(__file__).resolve().parents[2] / "localingo" / "data" / "translations.json"
)


def load_translations(path: Path = DEFAULT_TRANSLATIONS_FILE) -> list[dict[str, Any]]:
    """Read existing history, treating absent or invalid history as an empty list like Ruby does."""
    try:
        content = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return []
    return content if isinstance(content, list) else []


def save_text_translation(
    *,
    input_text: str,
    output_text: str,
    source_lang: str,
    target_lang: str,
    metrics: dict[str, float | int],
    path: Path = DEFAULT_TRANSLATIONS_FILE,
) -> None:
    """Append one text translation using the established Ruby JSON record shape."""
    translations = load_translations(path)
    translations.append(
        {
            "type": "text",
            "timestamp": datetime.now(UTC).astimezone().isoformat(),
            "source_lang": source_lang,
            "target_lang": target_lang,
            "input": input_text,
            "output": output_text,
            "metrics": metrics,
        }
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(translations, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
