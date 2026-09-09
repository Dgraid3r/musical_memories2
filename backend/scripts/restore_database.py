"""Restores a backup produced by backup_database.py.

Restoring pipes the decompressed SQL dump into psql against a target
database - normally a *fresh, empty* database you just created for this
purpose, not the live one still serving traffic, since this script does
not drop or clear anything for you first. Existing objects with
conflicting names will simply error partway through.

psql itself is expected on PATH (same assumption as pg_dump in
backup_database.py) - override with PSQL_COMMAND if it needs a
different invocation.

Usage (from backend/):
    # Restore a local backup file
    python -m scripts.restore_database backend/backups/backup_20260101T000000Z.sql.gz

    # Restore the most recent backup from object storage (requires
    # OBJECT_STORAGE_* configured)
    python -m scripts.restore_database --from-object-storage

    # ...or a specific one
    python -m scripts.restore_database --from-object-storage --key backups/backup_20260101T000000Z.sql.gz

    # Restore into a database other than DATABASE_URL
    python -m scripts.restore_database <file> --database-url postgresql://user:pass@host:5432/dbname
"""

import argparse
import gzip
import logging
import os
import shlex
import subprocess
import sys

from scripts.backup_database import BACKUP_KEY_PREFIX, _plain_url, parse_backup_timestamp

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

RESTORE_TIMEOUT_SECONDS = 300


def _psql_command() -> list[str]:
    return shlex.split(os.environ.get("PSQL_COMMAND", "psql"))


def restore_dump(data: bytes, database_url: str | None = None) -> None:
    """Decompresses `data` (as produced by backup_database.create_dump)
    and pipes it into psql against database_url (DATABASE_URL if not
    given). Raises RuntimeError if DATABASE_URL is unset or psql fails."""
    database_url = database_url or os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is not set.")

    sql = gzip.decompress(data)
    command = [*_psql_command(), "--set", "ON_ERROR_STOP=1", _plain_url(database_url)]
    result = subprocess.run(command, input=sql, capture_output=True, timeout=RESTORE_TIMEOUT_SECONDS)
    if result.returncode != 0:
        stderr = result.stderr.decode(errors="replace").strip()
        raise RuntimeError(f"psql exited {result.returncode}: {stderr}")


def _most_recent_object_storage_key(storage) -> str | None:
    keys = storage.list_keys(BACKUP_KEY_PREFIX)
    dated = [(parse_backup_timestamp(k), k) for k in keys]
    dated = [(ts, k) for ts, k in dated if ts is not None]
    if not dated:
        return None
    return max(dated, key=lambda pair: pair[0])[1]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("file", nargs="?", help="Path to a local backup_*.sql.gz file")
    parser.add_argument(
        "--from-object-storage", action="store_true", help="Restore from configured object storage instead"
    )
    parser.add_argument("--key", help="Specific object-storage key to restore (defaults to the most recent)")
    parser.add_argument("--database-url", help="Restore target (defaults to DATABASE_URL)")
    args = parser.parse_args(argv)

    if bool(args.file) == bool(args.from_object_storage):
        logger.error("restore.invalid_args - pass exactly one of a local file path or --from-object-storage")
        return 1

    if args.file:
        try:
            with open(args.file, "rb") as f:
                data = f.read()
        except OSError as exc:
            logger.error("restore.read_failed file=%s error=%s", args.file, exc)
            return 1
        source = args.file
    else:
        from app.storage import LocalDiskStorage, get_storage

        storage = get_storage()
        if isinstance(storage, LocalDiskStorage):
            logger.error("restore.object_storage_not_configured - OBJECT_STORAGE_* env vars are unset")
            return 1

        key = args.key or _most_recent_object_storage_key(storage)
        if key is None:
            logger.error("restore.no_backups_found prefix=%s", BACKUP_KEY_PREFIX)
            return 1

        data = storage.get_bytes(key)
        source = key

    try:
        restore_dump(data, database_url=args.database_url)
    except Exception:
        logger.error("restore.failed source=%s", source, exc_info=True)
        return 1

    logger.info("restore.completed source=%s", source)
    return 0


if __name__ == "__main__":
    sys.exit(main())
