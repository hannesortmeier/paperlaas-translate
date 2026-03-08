from paperlaas_translate.models import DocumentTag, TargetLanguage
from paperlaas_translate.utils import (
    derive_paperless_base_url,
    extract_document_id,
    is_supported_mime_type,
    parse_translation_tags,
)


def test_extract_document_id_and_base_url_with_subpath() -> None:
    url = "https://paperless.example.com/paperless/documents/2048/"

    assert extract_document_id(url) == 2048
    assert derive_paperless_base_url(url) == "https://paperless.example.com/paperless"


def test_parse_translation_tags_filters_and_groups() -> None:
    tags = [
        DocumentTag(id=1, name="translate to german"),
        DocumentTag(id=2, name="Accounting"),
        DocumentTag(id=3, name="Translate To Spanish"),
        DocumentTag(id=4, name="translate to german"),
    ]

    parsed = parse_translation_tags(tags)

    assert set(parsed) == {TargetLanguage.GERMAN, TargetLanguage.SPANISH}
    assert [tag.id for tag in parsed[TargetLanguage.GERMAN]] == [1, 4]
    assert [tag.id for tag in parsed[TargetLanguage.SPANISH]] == [3]


def test_odt_is_supported_mime_type() -> None:
    assert is_supported_mime_type("application/vnd.oasis.opendocument.text") is True
