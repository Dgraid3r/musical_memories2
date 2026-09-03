"""Error tracking, called once from main.py at startup.

Opt-in via SENTRY_DSN: if it's not set, this is a silent no-op (not a
startup failure) - the captain doesn't have a Sentry account set up yet,
and this app must keep working with nothing configured. sentry_sdk itself
is safe to leave un-initialized: every sentry_sdk.* call is a no-op until
sentry_sdk.init() has been called.
"""

import logging
import os

import sentry_sdk
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.logging import LoggingIntegration

logger = logging.getLogger(__name__)


def configure_sentry() -> None:
    dsn = os.environ.get("SENTRY_DSN")
    if not dsn:
        return

    sentry_sdk.init(
        dsn=dsn,
        integrations=[
            FastApiIntegration(),
            # Mirrors our own logging: any logger.error/logger.exception
            # call also becomes a Sentry event, so nothing has to call
            # Sentry directly to be tracked.
            LoggingIntegration(level=logging.INFO, event_level=logging.ERROR),
        ],
        traces_sample_rate=0.0,
        send_default_pii=False,
    )
    logger.info("sentry.configured")
