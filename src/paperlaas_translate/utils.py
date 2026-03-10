from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse, urlunparse

from .models import DocumentTag, TargetLanguage

_DOCUMENT_URL_RE = re.compile(r"/documents/(?P<document_id>\d+)/?$", re.IGNORECASE)
_TRANSLATION_TAG_RE = re.compile(
    r"^translate\s+to\s+(english|french|german|portuguese|spanish)$",
    re.IGNORECASE,
)

_WORD_MIME_TYPES = {
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.oasis.opendocument.text",
}

_EMAIL_MIME_TYPES = {
    "message/rfc822",
}

_SUPPORTED_MIME_TYPES = {
    "application/pdf",
    "text/plain",
    * _WORD_MIME_TYPES,
}


class UnsupportedDocumentTypeError(RuntimeError):
    pass


def extract_document_id(document_url: str) -> int:
    parsed = urlparse(document_url)
    match = _DOCUMENT_URL_RE.search(parsed.path)
    if not match:
        raise ValueError(f"Could not extract a document id from URL: {document_url}")
    return int(match.group("document_id"))


def derive_paperless_base_url(document_url: str) -> str:
    parsed = urlparse(document_url)
    stripped_path = _DOCUMENT_URL_RE.sub("", parsed.path).rstrip("/")
    return urlunparse((parsed.scheme, parsed.netloc, stripped_path, "", "", ""))


def parse_translation_tags(tags: Iterable[DocumentTag]) -> dict[TargetLanguage, list[DocumentTag]]:
    parsed_tags: dict[TargetLanguage, list[DocumentTag]] = {}
    for tag in tags:
        match = _TRANSLATION_TAG_RE.match(tag.name.strip())
        if not match:
            continue
        language = TargetLanguage(match.group(1).lower())
        parsed_tags.setdefault(language, []).append(tag)
    return parsed_tags


def is_supported_mime_type(mime_type: str) -> bool:
    return mime_type in _SUPPORTED_MIME_TYPES


def is_email(mime_type: str) -> bool:
    return mime_type in _EMAIL_MIME_TYPES


def is_pdf(mime_type: str) -> bool:
    return mime_type == "application/pdf"


def is_docx(mime_type: str) -> bool:
    return mime_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def is_legacy_word(mime_type: str) -> bool:
    return mime_type == "application/msword"


def is_odt(mime_type: str) -> bool:
    return mime_type == "application/vnd.oasis.opendocument.text"


def is_text(mime_type: str) -> bool:
    return mime_type == "text/plain"


def make_translated_filename(original_filename: str, target_language: TargetLanguage) -> str:
    path = Path(original_filename)
    suffix = path.suffix or _default_suffix_for_language_output(path.name)
    stem = path.stem or "document"
    return f"{stem}.{target_language.iso_code}.translated{suffix}"


def make_pdf_filename(filename: str) -> str:
    path = Path(filename)
    if path.suffix.lower() == ".pdf":
        return path.name
    if path.suffix:
        return f"{path.stem}.pdf"
    return f"{path.name}.pdf"


def make_translated_title(original_title: str, target_language: TargetLanguage) -> str:
    title = original_title.strip() or "Untitled Document"
    return f"{title} ({target_language.label} translation)"


def custom_fields_to_payload(
    original_custom_fields: list[dict[str, object]],
    original_document_field_id: int,
    original_document_id: int,
) -> dict[str, object]:
    payload: dict[str, object] = {}
    for entry in original_custom_fields:
        field_id = entry.get("field")
        if field_id is None:
            continue
        normalized_field_id = int(field_id)
        if normalized_field_id == original_document_field_id:
            continue
        value = entry.get("value")
        if value is None:
            continue
        payload[str(normalized_field_id)] = value
    payload[str(original_document_field_id)] = [original_document_id]
    return payload


def _default_suffix_for_language_output(filename: str) -> str:
    if filename.endswith(".txt"):
        return ".txt"
    if filename.endswith(".docx"):
        return ".docx"
    return ".bin"
