"""Application-level encryption for secrets stored in Postgres.

Currently used for SpotifyToken.access_token/refresh_token: those rows are
someone's real Spotify credentials, and storing them in plaintext means
anyone with read access to the database (a backup, a leaked snapshot, an
over-broad SELECT) can use them directly. EncryptedString is a SQLAlchemy
TypeDecorator, so this is transparent to every caller - the ORM always
sees/sets plaintext strings, Postgres only ever stores ciphertext. No schema
change is needed: the column stays a plain string type, just holding an
encrypted blob instead of the raw value.
"""

import logging
import os
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import String
from sqlalchemy.types import TypeDecorator

logger = logging.getLogger(__name__)


@lru_cache
def _fernet() -> Fernet:
    key = os.environ.get("TOKEN_ENCRYPTION_KEY")
    if not key:
        raise RuntimeError(
            "TOKEN_ENCRYPTION_KEY is not set. Copy backend/.env.example to backend/.env and set one "
            "(e.g. `python -c \"from cryptography.fernet import Fernet; "
            'print(Fernet.generate_key().decode())"`).'
        )
    try:
        return Fernet(key.encode())
    except ValueError as exc:
        raise RuntimeError(
            "TOKEN_ENCRYPTION_KEY is not a valid Fernet key. Generate one with "
            "`python -c \"from cryptography.fernet import Fernet; "
            'print(Fernet.generate_key().decode())"` - it is not the same format as JWT_SECRET_KEY.'
        ) from exc


class EncryptedString(TypeDecorator):
    """A String column that is encrypted at rest with Fernet (symmetric,
    authenticated encryption), keyed by TOKEN_ENCRYPTION_KEY."""

    impl = String
    cache_ok = True

    def process_bind_param(self, value: str | None, dialect) -> str | None:
        if value is None:
            return None
        return _fernet().encrypt(value.encode()).decode()

    def process_result_value(self, value: str | None, dialect) -> str | None:
        if value is None:
            return None
        try:
            return _fernet().decrypt(value.encode()).decode()
        except InvalidToken:
            # Most likely a value written before encryption was introduced,
            # or a key rotation - never surface ciphertext or crash the
            # request, but make it loud in the logs since it means that
            # token is unusable and the affected account needs to reconnect.
            logger.error("Failed to decrypt stored token - it may predate TOKEN_ENCRYPTION_KEY or the key rotated.")
            raise
