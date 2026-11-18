from app.config import Settings
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
    assert "PDF翻訳は Python 側へ移行中です" in response.text
    assert "sourceLang: 'auto'" not in response.text
    assert "targetLang: 'auto'" not in response.text
    assert "code: 'ja-easy'" not in response.text
    assert "isAutoMode" not in response.text
    assert "setAutoMode" not in response.text
    assert "@click=\"activeTab = 'pdf'\"" not in response.text
