"""Structured logging setup, called once from main.py at startup.

Replaces ad-hoc prints with real logging: a consistent
timestamp/level/logger/message format, going to stdout so it works the same
whether you're running locally or under any process manager/container log
collector. Individual modules just do `logger = logging.getLogger(__name__)`
and log normally - this only owns the one-time root configuration.
"""

import logging
import os


def configure_logging() -> None:
    level_name = os.environ.get("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S%z",
    )

    # These are noisy at INFO (every SQL statement / HTTP access line) and
    # not what LOG_LEVEL is meant to control here - keep them at WARNING
    # regardless of the app's own log level.
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
