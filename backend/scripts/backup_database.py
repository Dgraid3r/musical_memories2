"""Dumps the configured Postgres database (DATABASE_URL) via pg_dump,
gzip-compresses it, and stores it - in object storage (backend/app/
storage.py, reused rather than reinvented) under a backups/ prefix when
OBJECT_STORAGE_* is configured, or in a local backend/backups/ directory
when it isn't.

IMPORTANT - a local-only backup is not real protection: it sits on the
same machine (often the same disk) as the database it backs up, so it
survives a bad migration or an accidental DROP, but not a lost or
corrupted disk, a stolen machine, or the whole docker-compose volume
being wiped. It's useful for exercising this mechanism end to end (and
gives the daily cron sidecar something to actually do before object
storage is configured), but treat it as a smoke test, not a safety net.
Configure OBJECT_STORAGE_* (see backend/.env.example) for real
off-machine protection.

Format: plain SQL text (pg_dump's default format), gzip-compressed by
this script rather than relying on pg_dump's own compression - simple,
portable, and restorable with nothing more exotic than psql (see
restore_database.py / the README's restore procedure).

Retention: backups older than BACKUP_RETENTION_DAYS (env var, default
30) are deleted after each successful run, the same policy whether
backups live locally or in object storage. Age is read from the
timestamp encoded in each backup's own filename, not filesystem/object
metadata, so retention behaves identically either way.

pg_dump itself is expected on PATH (as it would be on a real deployed
host with the Postgres client tools installed, or the docker-compose
cron sidecar's own image) - override with PG_DUMP_COMMAND if it needs a
different invocation (e.g. a full path, or a wrapper command).

Usage (from backend/):
    python -m scripts.backup_database
"""

import gzip
import logging
import os
import shlex
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

BACKUPS_DIR = Path(__file__).resolve().parent.parent / "backups"
BACKUP_KEY_PREFIX = "backups/"
BACKUP_FILENAME_PREFIX = "backup_"
BACKUP_FILENAME_SUFFIX = ".sql.gz"
TIMESTAMP_FORMAT = "%Y%m%dT%H%M%SZ"

DEFAULT_RETENTION_DAYS = 30
DUMP_TIMEOUT_SECONDS = 300


def _retention_days() -> int:
    return int(os.environ.get("BACKUP_RETENTION_DAYS", str(DEFAULT_RETENTION_DAYS)))


def _pg_dump_command() -> list[str]:
    return shlex.split(os.environ.get("PG_DUMP_COMMAND", "pg_dump"))


def _plain_url(database_url: str) -> str:
    """pg_dump doesn't understand SQLAlchemy's driver-qualified scheme
    (postgresql+psycopg://) - strip everything but the base scheme."""
    scheme, _, rest = database_url.partition("://")
    return f"{scheme.split('+')[0]}://{rest}"


def _timestamp_now() -> str:
    return datetime.now(timezone.utc).strftime(TIMESTAMP_FORMAT)


def backup_filename(timestamp: str) -> str:
    return f"{BACKUP_FILENAME_PREFIX}{timestamp}{BACKUP_FILENAME_SUFFIX}"


def parse_backup_timestamp(name: str) -> datetime | None:
    """Extracts the UTC timestamp from a backup filename or object-storage
    key (e.g. "backups/backup_20260101T000000Z.sql.gz" or the bare
    filename) - returns None for anything that doesn't look like one of
    ours, rather than raising, since retention just skips those."""
    stem = name.rsplit("/", 1)[-1]
    if not (stem.startswith(BACKUP_FILENAME_PREFIX) and stem.endswith(BACKUP_FILENAME_SUFFIX)):
        return None
    middle = stem[len(BACKUP_FILENAME_PREFIX) : -len(BACKUP_FILENAME_SUFFIX)]
    try:
        return datetime.strptime(middle, TIMESTAMP_FORMAT).replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def create_dump(database_url: str | None = None) -> bytes:
    """Runs pg_dump against database_url (DATABASE_URL if not given) and
    returns the gzip-compressed SQL output. Raises RuntimeError if
    DATABASE_URL is unset or pg_dump fails."""
    database_url = database_url or os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is not set.")

    command = [*_pg_dump_command(), "--no-owner", "--no-privileges", _plain_url(database_url)]
    result = subprocess.run(command, capture_output=True, timeout=DUMP_TIMEOUT_SECONDS)
    if result.returncode != 0:
        stderr = result.stderr.decode(errors="replace").strip()
        raise RuntimeError(f"pg_dump exited {result.returncode}: {stderr}")
    return gzip.compress(result.stdout)


def _local_backup_files() -> list[Path]:
    if not BACKUPS_DIR.is_dir():
        return []
    return [
        p
        for p in BACKUPS_DIR.iterdir()
        if p.is_file() and p.name.startswith(BACKUP_FILENAME_PREFIX) and p.name.endswith(BACKUP_FILENAME_SUFFIX)
    ]


def _apply_retention(*, list_names, delete, retention_days: int, log_target: str) -> None:
    """Shared retention sweep: `list_names()` returns filenames/keys,
    `delete(name)` removes one. Age comes from each name's own encoded
    timestamp - identical logic for local disk and object storage."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    for name in list_names():
        timestamp = parse_backup_timestamp(name)
        if timestamp is not None and timestamp < cutoff:
            delete(name)
            logger.info("backup.retention_deleted target=%s name=%s", log_target, name)


def _record_run(started_at: datetime, *, succeeded: bool, error_message: str | None) -> None:
    """Writes one row to backup_runs (see app/models.py BackupRun), read
    back by GET /api/admin/stats to show the most recent backup's
    outcome without reading logs. Imported inline, same reasoning as
    run()'s own inline app.storage import - this script's pure helpers
    (backup_filename, parse_backup_timestamp, etc.) stay importable
    without needing a configured app database at all.

    Recording failure must never crash the backup script itself - it's
    an operational nicety, not something a DB hiccup should compound
    into "the backup script itself also failed" for."""
    try:
        from app.database import SessionLocal
        from app.models import BackupRun

        db = SessionLocal()
        try:
            db.add(BackupRun(started_at=started_at, succeeded=succeeded, error_message=error_message))
            db.commit()
        finally:
            db.close()
    except Exception:
        logger.error("backup.run_record_failed", exc_info=True)


def run() -> int:
    from app.storage import LocalDiskStorage, S3CompatibleStorage, get_storage

    started_at = datetime.now(timezone.utc)
    timestamp = _timestamp_now()
    filename = backup_filename(timestamp)

    try:
        data = create_dump()
    except Exception as exc:
        logger.error("backup.dump_failed", exc_info=True)
        _record_run(started_at, succeeded=False, error_message=str(exc))
        return 1

    retention_days = _retention_days()
    storage = get_storage()

    try:
        if isinstance(storage, S3CompatibleStorage):
            key = f"{BACKUP_KEY_PREFIX}{filename}"
            storage.put(key, data)
            logger.info("backup.uploaded target=object_storage key=%s bytes=%d", key, len(data))
            _apply_retention(
                list_names=lambda: storage.list_keys(BACKUP_KEY_PREFIX),
                delete=storage.delete,
                retention_days=retention_days,
                log_target="object_storage",
            )
        else:
            assert isinstance(storage, LocalDiskStorage)
            BACKUPS_DIR.mkdir(exist_ok=True)
            (BACKUPS_DIR / filename).write_bytes(data)
            logger.warning(
                "backup.saved_locally_only file=%s - this is NOT real off-machine protection "
                "(same machine as the database) - configure OBJECT_STORAGE_* in backend/.env for that.",
                filename,
            )
            _apply_retention(
                list_names=lambda: [p.name for p in _local_backup_files()],
                delete=lambda name: (BACKUPS_DIR / name).unlink(missing_ok=True),
                retention_days=retention_days,
                log_target="local",
            )
    except Exception as exc:
        logger.error("backup.save_failed file=%s", filename, exc_info=True)
        _record_run(started_at, succeeded=False, error_message=str(exc))
        return 1

    logger.info(
        "backup.completed file=%s bytes=%d retention_days=%d", filename, len(data), retention_days
    )
    _record_run(started_at, succeeded=True, error_message=None)
    return 0


if __name__ == "__main__":
    sys.exit(run())
