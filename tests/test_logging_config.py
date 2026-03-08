from paperlaas_translate.logging_config import configure_logging, get_logger


def test_structlog_renders_stdlib_message(capsys) -> None:
    configure_logging("INFO")

    logger = get_logger("paperlaas_translate.test")
    logger.info("hello world", request_id="req-123")

    captured = capsys.readouterr()
    output = captured.err or captured.out

    assert "hello world" in output
    assert "request_id=req-123" in output
