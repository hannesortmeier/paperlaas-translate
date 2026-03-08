import subprocess

import pytest

from paperlaas_translate.models import TargetLanguage
from paperlaas_translate.translators import pdf as pdf_module
from paperlaas_translate.translators.pdf import (
    PdfTranslator,
    _build_pdf_translation_error_message,
    _sanitize_command,
    _sanitize_text,
)


def test_pdf_error_mentions_missing_shared_library() -> None:
    stderr = (
        "ImportError: libxcb.so.1: cannot open shared object file: "
        "No such file or directory"
    )

    assert _build_pdf_translation_error_message(stderr) == (
        "pdf2zh_next failed to start because the runtime image is missing the shared "
        "library libxcb.so.1"
    )


def test_pdf_error_falls_back_to_generic_message() -> None:
    assert _build_pdf_translation_error_message("some other failure") == (
        "pdf2zh_next failed to translate the PDF"
    )


def test_pdf_sanitizers_redact_api_keys() -> None:
    api_key = "super-secret-key"

    assert _sanitize_text(f"token={api_key}", [api_key]) == "token=[REDACTED]"
    assert _sanitize_command(["tool", "--api-key", api_key], [api_key]) == [
        "tool",
        "--api-key",
        "[REDACTED]",
    ]


def test_pdf_translate_does_not_log_or_raise_api_key(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    api_key = "super-secret-key"
    logger_calls: list[tuple[str, str, dict[str, object]]] = []

    class FakeLogger:
        def info(self, event: str, **kwargs: object) -> None:
            logger_calls.append(("info", event, kwargs))

        def error(self, event: str, **kwargs: object) -> None:
            logger_calls.append(("error", event, kwargs))

    def fake_run(*args, **kwargs):
        raise subprocess.CalledProcessError(
            1,
            ["uv", "run", "pdf2zh_next", "--openai-compatible-api-key", api_key],
            output=f"stdout {api_key}",
            stderr=f"stderr {api_key}",
        )

    monkeypatch.setattr(pdf_module, "logger", FakeLogger())
    monkeypatch.setattr(subprocess, "run", fake_run)

    translator = PdfTranslator(
        command="pdf2zh_next",
        openai_api_key=api_key,
        openai_base_url="https://example.com/v1",
        openai_model="test-model",
        temp_dir=str(tmp_path),
        timeout_seconds=5,
    )

    with pytest.raises(RuntimeError) as exc_info:
        translator.translate("sample.pdf", b"pdf-bytes", TargetLanguage.ENGLISH)

    assert api_key not in str(exc_info.value)
    assert exc_info.value.__suppress_context__ is True
    assert logger_calls
    assert all(api_key not in repr(call) for call in logger_calls)


def test_pdf_translate_disables_watermark_by_default(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    captured: dict[str, object] = {}
    output_path = tmp_path / "translated.pdf"
    output_path.write_bytes(b"translated-pdf")

    class FakeCompletedProcess:
        stdout = ""
        stderr = ""

    def fake_run(command, **kwargs):
        captured["command"] = command
        return FakeCompletedProcess()

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(pdf_module, "_find_output_pdf", lambda *args: output_path)

    translator = PdfTranslator(
        command="pdf2zh_next",
        openai_api_key="super-secret-key",
        openai_base_url="https://example.com/v1",
        openai_model="test-model",
        temp_dir=str(tmp_path),
        timeout_seconds=5,
    )

    translated = translator.translate("sample.pdf", b"pdf-bytes", TargetLanguage.ENGLISH)

    assert translated == b"translated-pdf"
    command = captured["command"]

    assert isinstance(command, list)
    assert command[:3] == ["uv", "run", "pdf2zh_next"]
    assert "--watermark-output-mode" in command
    assert command[command.index("--watermark-output-mode") + 1] == "no_watermark"
    assert "--openai-compatible-api-key" in command
    assert command[command.index("--openai-compatible-api-key") + 1] == "super-secret-key"
    assert "--output" in command
    assert "--no-dual" in command
