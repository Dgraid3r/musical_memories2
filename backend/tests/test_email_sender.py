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


def test_send_email_without_smtp_logs_recipient_and_subject_only(monkeypatch, caplog):
    """The log line identifies which email would have been sent (useful
    for debugging "did this fire at all") without ever putting the
    actual body/token into the log stream. SMTP_* is documented as fully
    optional (see DEPLOYMENT.md), so this dev-mode path is the real
    default production behavior for a first deploy, not just a local
    convenience - a reset/verification/invite link/token must never
    reach a real log stream (or a Sentry breadcrumb) this way."""
    monkeypatch.delenv("SMTP_HOST", raising=False)
    with caplog.at_level(logging.INFO, logger="app.email"):
        send_email("logme@example.com", "Log Subject", "Log body with the real link/token=SECRET123")

    messages = [r.getMessage() for r in caplog.records]
    combined = "\n".join(messages)
    assert "logme@example.com" in combined
    assert "Log Subject" in combined
    assert "Log body with the real link/token=SECRET123" not in combined
    assert "SECRET123" not in combined


def test_send_email_without_smtp_still_records_full_body_in_dev_outbox_despite_safe_logging(monkeypatch):
    """The fix must only change what reaches the logger - the in-memory
    dev outbox (last_email_to) is the test/local-dev-only inspection
    path and must keep recording the full body and token exactly as
    before, since the rest of this suite pulls tokens out of it."""
    monkeypatch.delenv("SMTP_HOST", raising=False)
    send_email("logme2@example.com", "Subject", "Body with token=SECRET456", token="SECRET456")

    sent = last_email_to("logme2@example.com")
    assert sent is not None
    assert sent["body"] == "Body with token=SECRET456"
    assert sent["token"] == "SECRET456"


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
