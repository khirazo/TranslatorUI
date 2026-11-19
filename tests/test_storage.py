import json
from pathlib import Path

from app.storage import load_translations, save_text_translation


def test_save_text_translation_writes_a_text_record(tmp_path: Path) -> None:
    path = tmp_path / "translations.json"

    save_text_translation(
        input_text="Hello",
        output_text="こんにちは",
        source_lang="en",
        target_lang="ja",
        metrics={"token_count": 1, "total_time": 0.1},
        path=path,
    )

    records = json.loads(path.read_text(encoding="utf-8"))
    assert records[0]["type"] == "text"
    assert records[0]["source_lang"] == "en"
    assert records[0]["target_lang"] == "ja"
    assert records[0]["input"] == "Hello"
    assert records[0]["output"] == "こんにちは"
    assert records[0]["metrics"] == {"token_count": 1, "total_time": 0.1}
    assert records[0]["timestamp"]


def test_load_translations_treats_missing_or_invalid_history_as_empty(tmp_path: Path) -> None:
    path = tmp_path / "translations.json"
    assert load_translations(path) == []

    path.write_text("not json", encoding="utf-8")
    assert load_translations(path) == []
