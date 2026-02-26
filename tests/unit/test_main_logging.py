"""Tests for logging setup and sensitive data redaction."""

import logging

from src.main import SensitiveLogFilter, redact_sensitive_text, setup_logging


def test_redact_sensitive_text_masks_telegram_token() -> None:
    """Token in Telegram API URL and raw token should be masked."""
    text = (
        "HTTP Request: POST https://api.telegram.org/bot"
        "8078587979:AAHfMFrZvAr8PdiRPtztOaOTk3Fm1pWCEJ4/getUpdates "
        '"HTTP/1.1 200 OK" raw=8078587979:AAHfMFrZvAr8PdiRPtztOaOTk3Fm1pWCEJ4'
    )
    redacted = redact_sensitive_text(text)

    assert "AAHfMFrZvAr8PdiRPtztOaOTk3Fm1pWCEJ4" not in redacted
    assert "https://api.telegram.org/bot<redacted>/getUpdates" in redacted
    assert "<redacted_token>" in redacted


def test_sensitive_log_filter_redacts_message_with_args() -> None:
    """Filter should redact and flatten interpolated log message."""
    record = logging.LogRecord(
        name="httpx",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg='HTTP Request: %s %s "%s"',
        args=(
            "POST",
            "https://api.telegram.org/bot8078587979:"
            "AAHfMFrZvAr8PdiRPtztOaOTk3Fm1pWCEJ4/editMessageText",
            "HTTP/1.1 200 OK",
        ),
        exc_info=None,
    )

    filt = SensitiveLogFilter()
    assert filt.filter(record) is True
    assert record.args == ()
    assert "AAHfMFrZvAr8PdiRPtztOaOTk3Fm1pWCEJ4" not in str(record.msg)
    assert "https://api.telegram.org/bot<redacted>/editMessageText" in str(record.msg)


def test_setup_logging_non_debug_keeps_http_client_log_level() -> None:
    """Non-debug logging should keep HTTP client logs (with redaction filter)."""
    logging.getLogger("httpx").setLevel(logging.INFO)
    logging.getLogger("httpcore").setLevel(logging.INFO)

    setup_logging(debug=False)

    assert logging.getLogger("httpx").level == logging.INFO
    assert logging.getLogger("httpcore").level == logging.INFO
    assert any(
        isinstance(log_filter, SensitiveLogFilter)
        for handler in logging.getLogger().handlers
        for log_filter in handler.filters
    )
