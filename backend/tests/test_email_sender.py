"""Confirms the pluggable email sender's dev-mode fallback: with no
SMTP_HOST configured (the state every other test already runs in, since
none of them set it), send_email must never raise and must still record
the content - including the token - somewhere a test or developer can
find it. This mirrors how SENTRY_DSN being unset is a silent no-op rather
than a startup failure."""

import logging

from app.email import last_email_to, send_email


def test_send_email_without_smtp_configured_does_not_raise(monkeypatch):
    monkeypatch.delenv("SMTP_HOST", raising=False)
    send_email("someone@example.com", "Subject", "Body text", token="abc123")


def test_send_email_without_smtp_records_content_in_dev_outbox(monkeypatch):
    monkeypatch.delenv("SMTP_HOST", raising=False)
    send_email("dev@example.com", "Hello", "Body with a link", token="the-token-value")

    sent = last_email_to("dev@example.com")
    assert sent is not None
    assert sent["subject"] == "Hello"
    assert sent["body"] == "Body with a link"
    assert sent["token"] == "the-token-value"


def test_send_email_without_smtp_logs_the_content(monkeypatch, caplog):
    monkeypatch.delenv("SMTP_HOST", raising=False)
    with caplog.at_level(logging.INFO, logger="app.email"):
        send_email("logme@example.com", "Log Subject", "Log body with the real link/token")

    messages = [r.getMessage() for r in caplog.records]
    combined = "\n".join(messages)
    assert "logme@example.com" in combined
    assert "Log Subject" in combined
    assert "Log body with the real link/token" in combined


def test_last_email_to_returns_none_for_unknown_recipient():
    assert last_email_to("nobody-ever-emailed@example.com") is None


def test_real_flows_never_set_smtp_host_so_dev_fallback_is_what_tests_exercise(make_user, client):
    """A guard against silent drift: if a future change accidentally sets
    SMTP_HOST in the test environment, these flows would start attempting
    real network sends instead of exercising the fallback this suite
    relies on."""
    import os

    assert not os.environ.get("SMTP_HOST")
    make_user("alice")
    assert last_email_to("alice@example.com") is not None
