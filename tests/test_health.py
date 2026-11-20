from app.config import ProviderSettings, Settings
from app.main import create_app
from fastapi.testclient import TestClient


def test_health_returns_ok() -> None:
    app = create_app(settings=Settings())

    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_root_serves_the_python_ui() -> None:
    app = create_app(settings=Settings())

    with TestClient(app) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "TranslatorUI" in response.text
    assert "PDF翻訳" not in response.text
    assert "sourceLang: 'auto'" not in response.text
    assert "targetLang: 'auto'" not in response.text
    assert "code: 'ja-easy'" not in response.text
    assert "isAutoMode" not in response.text
    assert "setAutoMode" not in response.text
    assert "translate-pdf" not in response.text
    assert "model_id:this.modelId" in response.text
    assert "japanese_style:this.targetLang === 'ja' ? this.japaneseStyle : null" in response.text
    assert "設定を再読み込み" in response.text


def test_providers_lists_only_enabled_openai_compatible_entries() -> None:
    settings = Settings(
        default_provider_id="second",
        providers=(
            ProviderSettings(
                id="first", name="First", base_url="http://first.test", model="first-model"
            ),
            ProviderSettings(
                id="second", name="Second", base_url="http://second.test", model="second-model"
            ),
            ProviderSettings(
                id="future", name="Future", kind="acp", enabled=True, command=("agent", "acp")
            ),
        ),
    )
    app = create_app(settings=settings)

    with TestClient(app) as client:
        response = client.get("/api/providers")

    assert response.json() == {
        "generation": 1,
        "defaults": {"provider_id": "second", "model_id": "second-model", "effort": None},
        "providers": [
            {
                "id": "first",
                "name": "First",
                "models": [
                    {
                        "id": "first-model",
                        "name": "first-model",
                        "efforts": [],
                        "default_effort": None,
                    }
                ],
            },
            {
                "id": "second",
                "name": "Second",
                "models": [
                    {
                        "id": "second-model",
                        "name": "second-model",
                        "efforts": [],
                        "default_effort": None,
                    }
                ],
            },
        ],
    }
