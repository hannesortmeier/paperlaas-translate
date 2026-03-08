from __future__ import annotations

import json
import re
from collections.abc import Sequence

from openai import OpenAI
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from .logging_config import get_logger
from .models import TargetLanguage

logger = get_logger(__name__)

_JSON_ARRAY_RE = re.compile(r"\[[\s\S]*\]")


class SegmentTranslationError(RuntimeError):
    pass


class OpenAISegmentTranslator:
    def __init__(self, *, api_key: str, base_url: str, model: str) -> None:
        self._model = model
        self._client = OpenAI(api_key=api_key, base_url=base_url.rstrip("/"))

    @retry(
        reraise=True,
        retry=retry_if_exception_type(SegmentTranslationError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
    )
    def translate_segments(
        self,
        segments: Sequence[str],
        target_language: TargetLanguage,
    ) -> list[str]:
        if not segments:
            return []

        response = self._client.chat.completions.create(
            model=self._model,
            temperature=0,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a document translation engine. Translate each array item independently "
                        f"into {target_language.label}. Preserve meaning, numbering, URLs, placeholders, "
                        "and line breaks. Preserve placeholder tokens like [[PAPERLAAS_...]] exactly "
                        "and do not translate, remove, or reorder them. Return only a JSON array with "
                        "the same number of items."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(list(segments), ensure_ascii=False),
                },
            ],
        )

        content = response.choices[0].message.content or ""
        translated_segments = _parse_json_array(content)
        if len(translated_segments) != len(segments):
            logger.warning(
                "segment translation response length mismatch",
                requested_item_count=len(segments),
                returned_item_count=len(translated_segments),
                target_language=target_language.value,
                model=self._model,
            )
            raise SegmentTranslationError(
                f"Model returned {len(translated_segments)} items for {len(segments)} requested segments"
            )

        logger.info(
            "translated segment batch",
            batch_size=len(segments),
            target_language=target_language.value,
            model=self._model,
        )
        return translated_segments


def _parse_json_array(raw_content: str) -> list[str]:
    cleaned = raw_content.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        cleaned = cleaned.replace("json\n", "", 1).strip()

    match = _JSON_ARRAY_RE.search(cleaned)
    candidate = match.group(0) if match else cleaned
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise SegmentTranslationError(f"Failed to parse model response as JSON array: {raw_content}") from exc

    if not isinstance(parsed, list) or not all(isinstance(item, str) for item in parsed):
        raise SegmentTranslationError("Model response was not a JSON array of strings")
    return parsed
