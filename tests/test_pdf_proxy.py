import httpx
from app.config import Settings
from app.main import create_app
from fastapi.testclient import TestClient


def make_client(handler: httpx.MockTransport) -> TestClient:
    app = create_app(
        settings=Settings(pdf_gateway_url="http://ruby.test"),
        pdf_client_factory=lambda: httpx.AsyncClient(transport=handler),
    )
    return TestClient(app)


def test_pdf_upload_forwards_file_and_form_data() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert str(request.url) == "http://ruby.test/api/translate-pdf"
        assert b'name="source_lang"\r\n\r\nja' in request.content
        assert b'name="target_lang"\r\n\r\nen' in request.content
        assert b'name="pages"\r\n\r\n[1,2]' in request.content
        assert b'filename="example.pdf"' in request.content
        assert b"%PDF-test" in request.content
        return httpx.Response(200, json={"task_id": "task-1"})

    with make_client(httpx.MockTransport(handler)) as client:
        response = client.post(
            "/api/translate-pdf",
            data={"source_lang": "ja", "target_lang": "en", "pages": "[1,2]"},
            files={"file": ("example.pdf", b"%PDF-test", "application/pdf")},
        )

    assert response.status_code == 200
    assert response.json() == {"task_id": "task-1"}


def test_pdf_status_and_cancel_preserve_ruby_responses() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            assert str(request.url) == "http://ruby.test/api/translate-pdf/task-1/status"
            return httpx.Response(200, json={"status": "progress", "current": 1, "total": 3})
        assert request.method == "DELETE"
        assert str(request.url) == "http://ruby.test/api/translate-pdf/task-1"
        return httpx.Response(200, json={"success": True})

    with make_client(httpx.MockTransport(handler)) as client:
        status = client.get("/api/translate-pdf/task-1/status")
        cancelled = client.delete("/api/translate-pdf/task-1")

    assert status.json() == {"status": "progress", "current": 1, "total": 3}
    assert cancelled.json() == {"success": True}


def test_pdf_download_preserves_content_headers_and_error_status() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/mono"):
            return httpx.Response(
                200,
                content=b"%PDF-result",
                headers={
                    "content-type": "application/pdf",
                    "content-disposition": 'attachment; filename="result.pdf"',
                },
            )
        return httpx.Response(404, json={"error": "ファイルが見つかりません"})

    with make_client(httpx.MockTransport(handler)) as client:
        download = client.get("/api/translate-pdf/task-1/mono")
        missing = client.get("/api/translate-pdf/task-1/dual")

    assert download.content == b"%PDF-result"
    assert download.headers["content-type"] == "application/pdf"
    assert download.headers["content-disposition"] == 'attachment; filename="result.pdf"'
    assert missing.status_code == 404
    assert missing.json() == {"error": "ファイルが見つかりません"}


def test_pdf_gateway_failure_returns_bad_gateway() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline", request=request)

    with make_client(httpx.MockTransport(handler)) as client:
        response = client.get("/api/translate-pdf/task-1/status")

    assert response.status_code == 502
    assert response.json() == {"error": "PDF gateway is unavailable."}
