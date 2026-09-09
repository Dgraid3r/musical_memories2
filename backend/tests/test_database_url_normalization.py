import pytest

from app.database import normalize_database_url


@pytest.mark.parametrize(
    "raw,expected",
    [
        (
            "postgresql://user:pass@host:5432/db",
            "postgresql+psycopg://user:pass@host:5432/db",
        ),
        (
            # Railway's Postgres plugin format, roughly.
            "postgresql://postgres:secret@containers-us-west-1.railway.app:6543/railway",
            "postgresql+psycopg://postgres:secret@containers-us-west-1.railway.app:6543/railway",
        ),
        (
            "postgres://user:pass@host:5432/db",
            "postgresql+psycopg://user:pass@host:5432/db",
        ),
        (
            # Already driver-qualified - left untouched.
            "postgresql+psycopg://user:pass@host:5432/db",
            "postgresql+psycopg://user:pass@host:5432/db",
        ),
    ],
)
def test_normalize_database_url(raw, expected):
    assert normalize_database_url(raw) == expected
