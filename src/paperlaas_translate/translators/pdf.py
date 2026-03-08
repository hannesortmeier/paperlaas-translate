from __future__ import annotations

import os
import re
import shlex
import subprocess
from collections.abc import Sequence
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Literal

from ..logging_config import get_logger
from ..models import TargetLanguage

logger = get_logger(__name__)
_MISSING_SHARED_LIBRARY_RE = re.compile(
    r"ImportError: (?P<library>[^\s:]+): cannot open shared object file"
)
_REDACTED = "[REDACTED]"


class PdfTranslator:
    def __init__(
        self,
        *,
        command: str,
        openai_api_key: str,
        openai_base_url: str,
        openai_model: str,
        temp_dir: str,
        timeout_seconds: float,
        source_language: str | None = None,
        watermark_output_mode: Literal["watermarked", "no_watermark", "both"] = "no_watermark",
    ) -> None:
        self._command = command
        self._openai_api_key = openai_api_key
        self._openai_base_url = openai_base_url
        self._openai_model = openai_model
        self._temp_dir = Path(temp_dir)
        self._timeout_seconds = timeout_seconds
        self._source_language = source_language
        self._watermark_output_mode = watermark_output_mode

    def translate(self, filename: str, content: bytes, target_language: TargetLanguage) -> bytes:
        self._temp_dir.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(prefix="pdf2zh-", dir=self._temp_dir) as temp_dir_name:
            secrets = (self._openai_api_key,)
            temp_dir = Path(temp_dir_name)
            input_path = temp_dir / filename
            output_dir = temp_dir / "output"
            output_dir.mkdir()
            input_path.write_bytes(content)

            command = [
                "uv",
                "run",
                *shlex.split(self._command),
                str(input_path),
                "--openaicompatible",
                "--lang-out", target_language.iso_code,
                "--openai-compatible-model", self._openai_model,
                "--openai-compatible-base-url", self._openai_base_url,
                "--openai-compatible-api-key", self._openai_api_key,
                "--output", str(output_dir),
                "--save-auto-extracted-glossary",
                "--no-dual",
                "--watermark-output-mode", self._watermark_output_mode,
                "--disable-rich-text-translate",
                "--skip-clean",
                ]
            if self._source_language:
                command.extend(["-li", self._source_language])

            env = os.environ.copy()
            env.update(
                {
                    "OPENAI_API_KEY": self._openai_api_key,
                    "OPENAI_BASE_URL": self._openai_base_url,
                }
            )

            logger.info(
                "starting pdf translation",
                command=_sanitize_command(command, secrets),
                filename=filename,
                target_language=target_language.value,
            )
            try:
                completed = subprocess.run(
                    command,
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=self._timeout_seconds,
                    env=env,
                )
            except FileNotFoundError:
                raise RuntimeError(
                    f"Configured pdf2zh command was not found: {_sanitize_text(self._command, secrets)}"
                ) from None
            except subprocess.CalledProcessError as exc:
                logger.error(
                    "pdf translation failed",
                    stdout=_sanitize_text(exc.stdout[-4000:], secrets),
                    stderr=_sanitize_text(exc.stderr[-4000:], secrets),
                    returncode=exc.returncode,
                )
                raise RuntimeError(
                    _build_pdf_translation_error_message(_sanitize_text(exc.stderr or "", secrets))
                ) from None

            output_path = _find_output_pdf(temp_dir, input_path)
            logger.info(
                "pdf translation finished",
                output_file=str(output_path),
                stdout=_sanitize_text(completed.stdout[-2000:], secrets),
                stderr=_sanitize_text(completed.stderr[-2000:], secrets),
            )
            return output_path.read_bytes()


def _find_output_pdf(temp_dir: Path, input_path: Path) -> Path:
    candidates = sorted(
        [path for path in temp_dir.rglob("*.pdf") if path.resolve() != input_path.resolve()],
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        raise RuntimeError("pdf2zh_next completed but no translated PDF output was found")
    return candidates[0]


def _build_pdf_translation_error_message(stderr: str) -> str:
    match = _MISSING_SHARED_LIBRARY_RE.search(stderr)
    if match:
        library = match.group("library")
        return (
            "pdf2zh_next failed to start because the runtime image is missing the shared "
            f"library {library}"
        )
    return "pdf2zh_next failed to translate the PDF"


def _sanitize_command(command: Sequence[str], secrets: Sequence[str]) -> list[str]:
    return [_sanitize_text(part, secrets) for part in command]


def _sanitize_text(value: str, secrets: Sequence[str]) -> str:
    sanitized = value
    for secret in secrets:
        if secret:
            sanitized = sanitized.replace(secret, _REDACTED)
    return sanitized
