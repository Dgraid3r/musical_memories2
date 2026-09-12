"""Confirms the SQLAlchemy models and the Alembic migration chain agree on
the resulting database schema.

The rest of this suite deliberately builds its schema with
Base.metadata.create_all() (see conftest.py's autouse _clean_database
fixture), not by running the real migration chain - create_all is far
faster across hundreds of tests, and some tests (test_concurrency_
hardening.py, test_spotify_throttle.py's concurrent-call test) rely on
genuinely independent, separately-committed writes from multiple real
threads, which would conflict with wrapping each test in a rolled-back
transaction the way a per-test `alembic upgrade head` might otherwise be
made fast enough to use instead. CI separately runs `alembic upgrade
head` against a database just to prove the migration chain executes
without erroring, but nothing before this asserted that doing so
produces the *same* schema create_all does.

Those two schema-construction paths can silently drift apart: a model
change with a forgotten or wrong migration passes every other test green
(they all use create_all) and only fails once it hits a real deployed
database, which only ever runs the migration chain. This test closes
that gap using Alembic's own autogenerate machinery - the same code path
`alembic revision --autogenerate` uses - to compare a live database
that's been brought to `alembic upgrade head` against what the models
currently declare, and asserts the resulting diff is empty: "if you
asked Alembic to generate a new migration right now, would it have
nothing to say."

This runs against its own dedicated, disposable database (created and
dropped by the module-scoped fixture below), never the per-test
`musical_memories_test` database every other fixture and test in this
suite shares - conftest.py's autouse _clean_database fixture still runs
around this test like any other (it's harmless: it targets the *other*
database, via the `engine`/DATABASE_URL app.database bound at import
time), but this test's own database is deliberately kept separate so
its `alembic upgrade head` run never interferes with, or is interfered
with by, the create_all-based schema every other test relies on.
"""

import os
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, text

from app.database import Base, normalize_database_url

BACKEND_DIR = Path(__file__).resolve().parent.parent
SCHEMA_CHECK_DB_NAME = "musical_memories_schema_check"


def _replace_database_name(url: str, database_name: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, f"/{database_name}", "", ""))


def _admin_database_url() -> str:
    """Same server/credentials as DATABASE_URL, pointed at Postgres's own
    always-present `postgres` maintenance database - CREATE DATABASE/DROP
    DATABASE can't run on a connection to the database being created or
    dropped."""
    return _replace_database_name(normalize_database_url(os.environ["DATABASE_URL"]), "postgres")


def _schema_check_database_url() -> str:
    return _replace_database_name(normalize_database_url(os.environ["DATABASE_URL"]), SCHEMA_CHECK_DB_NAME)


def _run_admin_statement(sql: str) -> None:
    # AUTOCOMMIT: CREATE DATABASE/DROP DATABASE cannot run inside a
    # transaction block, which psycopg otherwise opens by default.
    engine = create_engine(_admin_database_url(), isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as connection:
            connection.execute(text(sql))
    finally:
        engine.dispose()


@pytest.fixture(scope="module")
def migrated_schema_check_db():
    """Creates a fresh database, runs the real Alembic migration chain
    against it (not create_all), yields its URL, then drops it."""
    _run_admin_statement(f'DROP DATABASE IF EXISTS "{SCHEMA_CHECK_DB_NAME}"')
    _run_admin_statement(f'CREATE DATABASE "{SCHEMA_CHECK_DB_NAME}"')

    schema_check_url = _schema_check_database_url()
    alembic_cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    alembic_cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))

    # alembic/env.py reads DATABASE_URL from the environment itself (not
    # from this Config object) to decide what to migrate - see its own
    # comment on why. Point it at the dedicated database for the
    # duration of this one `upgrade` call, then restore it, since
    # everything else in this suite (including other fixtures that run
    # around this same test) assumes DATABASE_URL still means
    # musical_memories_test.
    original_database_url = os.environ["DATABASE_URL"]
    os.environ["DATABASE_URL"] = schema_check_url
    try:
        command.upgrade(alembic_cfg, "head")
    finally:
        os.environ["DATABASE_URL"] = original_database_url

    yield schema_check_url

    _run_admin_statement(f'DROP DATABASE IF EXISTS "{SCHEMA_CHECK_DB_NAME}"')


def test_migrations_match_models_with_no_drift(migrated_schema_check_db):
    engine = create_engine(migrated_schema_check_db)
    try:
        with engine.connect() as connection:
            migration_context = MigrationContext.configure(connection)
            diff = compare_metadata(migration_context, Base.metadata)
    finally:
        engine.dispose()

    assert diff == [], (
        "Alembic autogenerate detected drift between app/models.py and the "
        "migration chain (alembic upgrade head) - see the diff below. This means "
        "a model change wasn't fully captured by a migration, or a migration "
        "doesn't match what the models currently declare:\n\n"
        f"{diff}\n\n"
        "From backend/, against a database at `alembic upgrade head`, run "
        "`alembic revision --autogenerate -m \"<description>\"` to see (and then "
        "hand-review, never blindly commit) the migration Alembic would generate "
        "to close this gap."
    )
