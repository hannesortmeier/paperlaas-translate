import httpx
import pytest

from paperlaas_translate.main import create_app


class FakeService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, bytes]] = []

    async def handle_webhook(self, url: str, request_id: str, original_file_bytes: bytes) -> None:
        self.calls.append((url, request_id, original_file_bytes))


@pytest.mark.asyncio
async def test_translate_webhook_accepts_valid_request() -> None:
    service = FakeService()
    app = create_app(service=service)

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.post(
                "/hooks/translate",
                data={"url": "https://paperless.example.com/documents/2048/"},
                files={"file": ("invoice.txt", b"Original content", "text/plain")},
            )

    assert response.status_code == 202
    assert response.json()["document_id"] == 2048
    assert service.calls == [
        ("https://paperless.example.com/documents/2048/", response.json()["request_id"], b"Original content")
    ]


@pytest.mark.asyncio
async def test_translate_webhook_rejects_invalid_document_url() -> None:
    service = FakeService()
    app = create_app(service=service)

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            response = await client.post(
                "/hooks/translate",
                data={"url": "https://paperless.example.com/invalid/"},
                files={"file": ("invoice.txt", b"Original content", "text/plain")},
            )

    assert response.status_code == 400
    assert service.calls == []
