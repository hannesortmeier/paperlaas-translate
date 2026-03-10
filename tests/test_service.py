import pytest
from paperlaas_translate.models import DocumentTag, PaperlessDocument, TargetLanguage
from paperlaas_translate.service import TranslationService


class FakePaperlessClient:
    def __init__(self) -> None:
        self.document = PaperlessDocument(
            id=42,
            title="Invoice",
            original_filename="invoice.txt",
            mime_type="text/plain",
            tags=[
                DocumentTag(id=1, name="translate to german"),
                DocumentTag(id=2, name="translate to french"),
                DocumentTag(id=3, name="Accounting"),
            ],
            custom_fields=[{"field": 11, "value": "2026-1001"}],
            correspondent=9,
            document_type=8,
            created="2026-03-06",
        )
        self.uploads: list[dict[str, object]] = []
        self.updated_tags: list[int] | None = None
        self.downloaded_document_ids: list[int] = []

    async def fetch_document(self, base_url: str, document_id: int) -> PaperlessDocument:
        return self.document

    async def download_document(self, base_url: str, document_id: int) -> bytes:
        self.downloaded_document_ids.append(document_id)
        return b"%PDF-1.7 archived"

    async def find_tag_id(self, base_url: str, tag_name: str) -> int:
        assert tag_name == "translated"
        return 99

    async def find_custom_field_id(self, base_url: str, field_name: str) -> int:
        assert field_name == "original document"
        return 77

    async def upload_document(self, base_url: str, **kwargs):
        self.uploads.append(kwargs)
        return type("UploadResult", (), {"task_id": f"task-{len(self.uploads)}"})()

    async def wait_for_task(self, base_url: str, task_id: str) -> dict[str, str]:
        return {"status": "SUCCESS", "task_id": task_id}

    async def update_document_tags(self, base_url: str, document_id: int, tag_ids: list[int]) -> None:
        self.updated_tags = tag_ids


class FakeOfficeTranslator:
    def translate(self, mime_type: str, content: bytes, target_language: TargetLanguage) -> bytes:
        return f"{target_language.value}:{content.decode('utf-8')}".encode("utf-8")


class FakePdfTranslator:
    def translate(self, filename: str, content: bytes, target_language: TargetLanguage) -> bytes:
        raise AssertionError("PDF translator should not be used for text documents")


class RecordingPdfTranslator:
    def __init__(self) -> None:
        self.calls: list[tuple[str, bytes, TargetLanguage]] = []

    def translate(self, filename: str, content: bytes, target_language: TargetLanguage) -> bytes:
        self.calls.append((filename, content, target_language))
        return f"pdf:{target_language.value}:{filename}".encode("utf-8")


@pytest.fixture(autouse=True)
def run_translators_inline(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _run_blocking(self: TranslationService, func, *args):
        return func(*args)

    monkeypatch.setattr(TranslationService, "_run_blocking", _run_blocking)


@pytest.mark.asyncio
async def test_service_uploads_all_requested_languages_and_removes_only_successful_tags() -> None:
    paperless_client = FakePaperlessClient()
    service = TranslationService(
        paperless_client,
        FakePdfTranslator(),
        FakeOfficeTranslator(),
    )

    await service.handle_webhook(
        "https://paperless.example.com/documents/42/",
        request_id="req-1",
        original_file_bytes=b"Original content",
    )

    assert len(paperless_client.uploads) == 2
    assert paperless_client.uploads[0]["tags"] == [3, 99]
    assert paperless_client.uploads[0]["artifact_bytes"] == b"german:Original content"
    assert paperless_client.uploads[1]["artifact_bytes"] == b"french:Original content"
    assert paperless_client.uploads[0]["custom_fields"] == {"11": "2026-1001", "77": [42]}
    assert paperless_client.updated_tags == [3]

class FlakyOfficeTranslator:
    def translate(self, mime_type: str, content: bytes, target_language: TargetLanguage) -> bytes:
        if target_language is TargetLanguage.GERMAN:
            raise RuntimeError("German translation failed")
        return f"{target_language.value}:{content.decode('utf-8')}".encode("utf-8")


@pytest.mark.asyncio
async def test_service_keeps_failed_translation_tags_on_original_document() -> None:
    paperless_client = FakePaperlessClient()
    service = TranslationService(
        paperless_client,
        FakePdfTranslator(),
        FlakyOfficeTranslator(),
    )

    await service.handle_webhook(
        "https://paperless.example.com/documents/42/",
        request_id="req-2",
        original_file_bytes=b"Original content",
    )

    assert len(paperless_client.uploads) == 1
    assert paperless_client.uploads[0]["title"] == "Invoice (French translation)"
    assert paperless_client.updated_tags == [1, 3]


@pytest.mark.asyncio
async def test_service_downloads_archived_pdf_for_eml_documents() -> None:
    paperless_client = FakePaperlessClient()
    paperless_client.document = PaperlessDocument(
        id=42,
        title="Inbox message",
        original_filename="message.eml",
        mime_type="message/rfc822",
        tags=[DocumentTag(id=1, name="translate to german")],
        custom_fields=[],
        correspondent=9,
        document_type=8,
        created="2026-03-06",
    )
    pdf_translator = RecordingPdfTranslator()
    service = TranslationService(
        paperless_client,
        pdf_translator,
        FakeOfficeTranslator(),
    )

    await service.handle_webhook(
        "https://paperless.example.com/documents/42/",
        request_id="req-3",
        original_file_bytes=b"From: sender@example.com",
    )

    assert paperless_client.downloaded_document_ids == [42]
    assert pdf_translator.calls == [("message.pdf", b"%PDF-1.7 archived", TargetLanguage.GERMAN)]
    assert len(paperless_client.uploads) == 1
    assert paperless_client.uploads[0]["artifact_name"] == "message.de.translated.pdf"
    assert paperless_client.uploads[0]["artifact_mime_type"] == "application/pdf"
    assert paperless_client.uploads[0]["artifact_bytes"] == b"pdf:german:message.pdf"
