"""Pluggable email sending for invites, verification, and password reset.

Configured via SMTP env vars (SMTP_HOST/PORT/USER/PASSWORD/FROM_ADDRESS) -
plain SMTP rather than a proprietary provider API, so it isn't locked to
one paid vendor and works with anything from a real transactional-email
provider to a personal Gmail account later.

The captain doesn't have an email provider set up yet, so when SMTP_HOST
isn't configured, sending doesn't fail - it logs the email's content
(recipient, subject, and critically the actual link/token) to the
structured logger instead, the same optional-no-op shape as SENTRY_DSN.
That makes every flow that sends an email fully usable and testable
locally right now, with no mail server anywhere.

A send never raises: a broken SMTP config (bad credentials, unreachable
host) must not break the underlying action (registering, requesting a
reset, inviting someone) - the token this email carries still exists and
is still valid in the database either way, only the notification failed,
and that failure is logged loudly instead.
"""

import logging
import os
import smtplib
from email.message import EmailMessage

logger = logging.getLogger(__name__)

# A small in-memory record of every email "sent" through this module -
# always populated, regardless of whether a real SMTP send also happens -
# so tests (and local dev without SMTP configured) can inspect exactly
# what would have been sent, especially the token embedded in it, without
# a real mail server anywhere. Bounded so it can't grow unbounded in a
# long-running process.
_DEV_OUTBOX_MAX = 200
_dev_outbox: list[dict] = []


def clear_dev_outbox() -> None:
    """Test-only: reset the in-memory record between tests, the same
    pattern as clear_search_cache() and limiter.reset()."""
    _dev_outbox.clear()


def last_email_to(recipient: str) -> dict | None:
    """Test/dev-only: the most recent email recorded for this recipient,
    or None. Used by tests to pull the token out of an invite/
    verification/reset email without needing a real inbox."""
    for sent in reversed(_dev_outbox):
        if sent["to"] == recipient:
            return sent
    return None


def send_email(to: str, subject: str, body: str, *, token: str | None = None) -> None:
    """`token` is recorded alongside the email purely for local
    dev/testing convenience (see last_email_to) - it's already embedded in
    `body` as a real link for the actual recipient."""
    _dev_outbox.append({"to": to, "subject": subject, "body": body, "token": token})
    if len(_dev_outbox) > _DEV_OUTBOX_MAX:
        del _dev_outbox[: len(_dev_outbox) - _DEV_OUTBOX_MAX]

    host = os.environ.get("SMTP_HOST")
    if not host:
        logger.info("email.dev_mode to=%r subject=%r body=%s", to, subject, body)
        return

    port = int(os.environ.get("SMTP_PORT", "587"))
    user = os.environ.get("SMTP_USER")
    password = os.environ.get("SMTP_PASSWORD")
    from_address = os.environ.get("SMTP_FROM_ADDRESS") or user or "no-reply@musicalmemories.local"

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = from_address
    msg["To"] = to
    msg.set_content(body)

    try:
        with smtplib.SMTP(host, port, timeout=10) as smtp:
            smtp.starttls()
            if user and password:
                smtp.login(user, password)
            smtp.send_message(msg)
        logger.info("email.sent to=%r subject=%r", to, subject)
    except Exception:
        logger.exception("email.send_failed to=%r subject=%r", to, subject)
