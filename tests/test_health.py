from app.config import Settings
from app.main import create_app
from fastapi.testclient import TestClient


def test_health_returns_ok() -> None:
    app = create_app(settings=Settings())

    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
