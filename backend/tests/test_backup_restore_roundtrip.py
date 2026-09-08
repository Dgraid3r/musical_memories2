"""A real dump -> restore -> verify round trip, not just "pg_dump exited
0". This dev machine has no native pg_dump/psql install, so PG_DUMP_COMMAND
/PSQL_COMMAND (an env override backup_database.py/restore_database.py
already support, meant for a deployment where the client tools live at a
non-default path) are pointed at the exact same binaries running inside
the docker-compose postgres container the test database itself lives in
- a real deployment would instead have postgresql-client installed
alongside the app and leave these unset, using plain "pg_dump"/"psql" on
PATH; the script code path exercised here is identical either way.

Restores into a freshly created scratch database rather than the shared
musical_memories_test database other tests depend on, so this never
risks disrupting anything else.
"""

import uuid
from pathlib import Path

from sqlalchemy import create_engine, text

from scripts.backup_database import create_dump
from scripts.restore_database import restore_dump

COMPOSE_FILE = Path(__file__).resolve().parent.parent.parent / "docker-compose.yml"
ADMIN_URL = "postgresql+psycopg://musical_memories:musical_memories@localhost:5432/postgres"


def _docker_exec_command(tool: str) -> str:
    return f'docker compose -f "{COMPOSE_FILE.as_posix()}" exec -T postgres {tool}'


def test_dump_and_restore_round_trip_preserves_real_data(monkeypatch, make_user):
    monkeypatch.setenv("PG_DUMP_COMMAND", _docker_exec_command("pg_dump"))
    monkeypatch.setenv("PSQL_COMMAND", _docker_exec_command("psql"))

    # Real, distinctive data in the live test database before the dump -
    # this is what proves the restored database is actually usable, not
    # just that psql returned success on an empty script.
    marker = make_user("alice_roundtrip_marker")

    data = create_dump()
    assert len(data) > 0

    scratch_db = f"backup_roundtrip_{uuid.uuid4().hex[:12]}"
    scratch_url = f"postgresql+psycopg://musical_memories:musical_memories@localhost:5432/{scratch_db}"
    admin_engine = create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")

    try:
        with admin_engine.connect() as conn:
            conn.execute(text(f'CREATE DATABASE "{scratch_db}"'))

        restore_dump(data, database_url=scratch_url)

        scratch_engine = create_engine(scratch_url)
        try:
            with scratch_engine.connect() as conn:
                row = conn.execute(
                    text("SELECT username, email FROM users WHERE id = :id"), {"id": marker["id"]}
                ).one()
        finally:
            scratch_engine.dispose()

        assert row.username == "alice_roundtrip_marker"
        assert row.email == "alice_roundtrip_marker@example.com"
    finally:
        with admin_engine.connect() as conn:
            conn.execute(
                text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = :db AND pid <> pg_backend_pid()"
                ),
                {"db": scratch_db},
            )
            conn.execute(text(f'DROP DATABASE IF EXISTS "{scratch_db}"'))
        admin_engine.dispose()
