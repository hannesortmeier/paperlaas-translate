import asyncio

import httpx

from paperlaas_translate.paperless_client import PaperlessClient


def test_upload_document_uses_async_safe_multipart_request() -> None:
    captured: dict[str, str] = {}

    async def run_test() -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            captured["content_type"] = request.headers["content-type"]
            captured["body"] = (await request.aread()).decode("utf-8", errors="replace")
            return httpx.Response(200, json={"task_id": "task-123"})

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as http_client:
            client = PaperlessClient(
                http_client,
                token="paperless-token",
                task_poll_seconds=0.1,
                task_timeout_seconds=1.0,
            )
            result = await client.upload_document(
                "https://paperless.example.com",
                artifact_name="translated.txt",
                artifact_bytes=b"hello",
                artifact_mime_type="text/plain",
                title="Translated title",
                tags=[7, 6],
                custom_fields={"2": "TestValue", "1": [1]},
                correspondent=None,
                document_type=None,
                created="2026-03-07",
            )

            assert result.task_id == "task-123"

    asyncio.run(run_test())

    assert "multipart/form-data" in captured["content_type"]
    assert captured["body"].count('name="tags"') == 2
    assert '"2": "TestValue"' in captured["body"]
    assert "Translated title" in captured["body"]
