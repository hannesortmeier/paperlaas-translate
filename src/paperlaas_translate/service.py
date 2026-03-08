from __future__ import annotations

import asyncio
import time

from structlog.contextvars import bind_contextvars, clear_contextvars

from .logging_config import get_logger
from .models import PaperlessDocument, TargetLanguage, TranslatedArtifact
from .paperless_client import PaperlessClient
from .translators import OfficeAndTextTranslator, PdfTranslator
from .utils import (
    UnsupportedDocumentTypeError,
    custom_fields_to_payload,
    derive_paperless_base_url,
    extract_document_id,
    is_pdf,
    is_supported_mime_type,
    make_translated_filename,
    make_translated_title,
    parse_translation_tags,
)

logger = get_logger(__name__)


class TranslationService:
    def __init__(
        self,
        paperless_client: PaperlessClient,
        pdf_translator: PdfTranslator,
        office_translator: OfficeAndTextTranslator,
        *,
        translated_tag_name: str = "translated",
        original_document_field_name: str = "original document",
    ) -> None:
        self._paperless_client = paperless_client
        self._pdf_translator = pdf_translator
        self._office_translator = office_translator
        self._translated_tag_name = translated_tag_name
        self._original_document_field_name = original_document_field_name

    async def handle_webhook(
        self,
        url: str,
        request_id: str,
        original_file_bytes: bytes,
    ) -> None:
        clear_contextvars()
        bind_contextvars(request_id=request_id)
        started = time.monotonic()
        document_id = extract_document_id(url)
        paperless_base_url = derive_paperless_base_url(url)
        bind_contextvars(document_id=document_id)

        logger.info(
            "starting translation workflow",
            source_url=url,
            paperless_base_url=paperless_base_url,
        )
        try:
            document = await self._paperless_client.fetch_document(paperless_base_url, document_id)
            if not is_supported_mime_type(document.mime_type):
                raise UnsupportedDocumentTypeError(
                    f"Unsupported MIME type for document {document_id}: {document.mime_type}"
                )

            translation_tags = parse_translation_tags(document.tags)
            if not translation_tags:
                logger.info("document has no translation tags; skipping")
                return

            translated_tag_id = await self._paperless_client.find_tag_id(
                paperless_base_url,
                self._translated_tag_name,
            )
            original_document_field_id = await self._paperless_client.find_custom_field_id(
                paperless_base_url,
                self._original_document_field_name,
            )

            requested_languages = [language.value for language in translation_tags]
            logger.info(
                "loaded translation inputs",
                mime_type=document.mime_type,
                requested_languages=requested_languages,
                tag_count=len(document.tags),
            )

            translation_tag_ids = {tag.id for tags in translation_tags.values() for tag in tags}
            base_tag_ids = [tag.id for tag in document.tags if tag.id not in translation_tag_ids]
            upload_tag_ids = list(dict.fromkeys([*base_tag_ids, translated_tag_id]))
            successful_tag_ids: list[int] = []
            failures: dict[str, str] = {}

            for target_language, language_tags in translation_tags.items():
                bind_contextvars(target_language=target_language.value)
                try:
                    artifact = await self._translate_document(
                        document,
                        original_file_bytes,
                        target_language,
                    )
                    custom_fields = custom_fields_to_payload(
                        document.custom_fields,
                        original_document_field_id,
                        document.id,
                    )
                    upload_result = await self._paperless_client.upload_document(
                        paperless_base_url,
                        artifact_name=artifact.filename,
                        artifact_bytes=artifact.content,
                        artifact_mime_type=artifact.mime_type,
                        title=artifact.title,
                        tags=upload_tag_ids,
                        custom_fields=custom_fields,
                        correspondent=document.correspondent,
                        document_type=document.document_type,
                        created=document.created,
                    )
                    await self._paperless_client.wait_for_task(paperless_base_url, upload_result.task_id)
                    successful_tag_ids.extend(tag.id for tag in language_tags)
                    logger.info(
                        "completed translation target",
                        filename=artifact.filename,
                        removed_tag_ids=[tag.id for tag in language_tags],
                    )
                except Exception as exc:
                    failures[target_language.value] = str(exc)
                    logger.exception("translation target failed")

            if successful_tag_ids:
                remaining_tags = [tag.id for tag in document.tags if tag.id not in set(successful_tag_ids)]
                await self._paperless_client.update_document_tags(
                    paperless_base_url,
                    document.id,
                    remaining_tags,
                )

            logger.info(
                "translation workflow complete",
                successful_languages=sorted(
                    {
                        language.value
                        for language, tags in translation_tags.items()
                        if any(tag.id in successful_tag_ids for tag in tags)
                    }
                ),
                failed_languages=failures,
                removed_tag_ids=sorted(set(successful_tag_ids)),
                duration_seconds=round(time.monotonic() - started, 2),
            )
        except Exception:
            logger.exception("translation workflow failed")
        finally:
            clear_contextvars()

    async def _translate_document(
        self,
        document: PaperlessDocument,
        original_file: bytes,
        target_language: TargetLanguage,
    ) -> TranslatedArtifact:
        logger.info(
            "translating document",
            mime_type=document.mime_type,
            original_filename=document.original_filename,
        )
        if is_pdf(document.mime_type):
            translated_bytes = await asyncio.to_thread(
                self._pdf_translator.translate,
                document.original_filename,
                original_file,
                target_language,
            )
            output_mime_type = "application/pdf"
        else:
            translated_bytes = await asyncio.to_thread(
                self._office_translator.translate,
                document.mime_type,
                original_file,
                target_language,
            )
            output_mime_type = document.mime_type

        return TranslatedArtifact(
            content=translated_bytes,
            filename=make_translated_filename(document.original_filename, target_language),
            mime_type=output_mime_type,
            title=make_translated_title(document.title, target_language),
        )
