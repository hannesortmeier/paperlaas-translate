from types import SimpleNamespace

from paperlaas_translate.llm import OpenAISegmentTranslator
from paperlaas_translate.logging_config import configure_logging
from paperlaas_translate.models import TargetLanguage


class FakeCompletions:
    def __init__(self, response) -> None:
        self.response = response
        self.calls: list[dict[str, object]] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


def test_translate_segments_logs_request_and_response_usage(capsys) -> None:
    configure_logging("INFO")
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content='["Hallo Welt"]'))],
        usage=SimpleNamespace(prompt_tokens=17, completion_tokens=9, total_tokens=26),
    )
    completions = FakeCompletions(response)
    translator = OpenAISegmentTranslator(
        api_key="test-key",
        base_url="https://example.com/v1",
        model="gpt-test",
    )
    translator._client = SimpleNamespace(chat=SimpleNamespace(completions=completions))

    translated_segments = translator.translate_segments(["Hello world"], TargetLanguage.GERMAN)

    captured = capsys.readouterr()
    output = captured.err or captured.out

    assert translated_segments == ["Hallo Welt"]
    assert len(completions.calls) == 1
    assert "sending llm translation request" in output
    assert "received llm translation response" in output
    assert "prompt_tokens=17" in output
    assert "request_tokens=17" in output
    assert "completion_tokens=9" in output
    assert "response_tokens=9" in output
    assert "total_tokens=26" in output


def test_translate_segments_logs_when_usage_is_unavailable(capsys) -> None:
    configure_logging("INFO")
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content='["Bonjour"]'))],
        usage=None,
    )
    completions = FakeCompletions(response)
    translator = OpenAISegmentTranslator(
        api_key="test-key",
        base_url="https://example.com/v1",
        model="gpt-test",
    )
    translator._client = SimpleNamespace(chat=SimpleNamespace(completions=completions))

    translated_segments = translator.translate_segments(["Hello"], TargetLanguage.FRENCH)

    captured = capsys.readouterr()
    output = captured.err or captured.out

    assert translated_segments == ["Bonjour"]
    assert "received llm translation response" in output
    assert "token_usage_available=False" in output


def test_translate_segments_logs_full_payload_in_debug_mode(capsys) -> None:
    configure_logging("DEBUG")
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content='["Hallo Welt", "Zweite Zeile"]'))],
        usage=SimpleNamespace(prompt_tokens=17, completion_tokens=9, total_tokens=26),
    )
    completions = FakeCompletions(response)
    translator = OpenAISegmentTranslator(
        api_key="test-key",
        base_url="https://example.com/v1",
        model="gpt-test",
    )
    translator._client = SimpleNamespace(chat=SimpleNamespace(completions=completions))

    translator.translate_segments(["Hello world", "Second line"], TargetLanguage.GERMAN)

    captured = capsys.readouterr()
    output = captured.err or captured.out

    assert "llm translation request payload" in output
    assert 'user_payload=\'["Hello world", "Second line"]\'' in output
    assert "system_prompt='You are a document translation engine." in output
