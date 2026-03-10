from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class TargetLanguage(str, Enum):
    ENGLISH = "english"
    FRENCH = "french"
    GERMAN = "german"
    PORTUGUESE = "portuguese"
    SPANISH = "spanish"

    @property
    def iso_code(self) -> str:
        return {
            TargetLanguage.ENGLISH: "en",
            TargetLanguage.FRENCH: "fr",
            TargetLanguage.GERMAN: "de",
            TargetLanguage.PORTUGUESE: "pt",
            TargetLanguage.SPANISH: "es",
        }[self]

    @property
    def label(self) -> str:
        return self.value.capitalize()


@dataclass(slots=True, frozen=True)
class DocumentTag:
    id: int
    name: str


@dataclass(slots=True)
class PaperlessDocument:
    id: int
    title: str
    original_filename: str
    mime_type: str
    tags: list[DocumentTag]
    custom_fields: list[dict[str, Any]]
    correspondent: int | None = None
    document_type: int | None = None
    created: str | None = None


@dataclass(slots=True, frozen=True)
class TranslationSource:
    content: bytes
    filename: str
    mime_type: str


@dataclass(slots=True)
class TranslatedArtifact:
    content: bytes
    filename: str
    mime_type: str
    title: str


@dataclass(slots=True)
class UploadResult:
    task_id: str
    raw_response: Any
