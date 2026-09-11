import subprocess
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from scripts.backup_database import (
    BACKUP_KEY_PREFIX,
    backup_filename,
    create_dump,
    parse_backup_timestamp,
    run,
)


# --- Filename / timestamp helpers -------------------------------------------


def test_backup_filename_format():
    name = backup_filename("20260315T091500Z")
    assert name == "backup_20260315T091500Z.sql.gz"


def test_parse_backup_timestamp_round_trips():
    name = backup_filename("20260315T091500Z")
    ts = parse_backup_timestamp(name)
    assert ts == datetime(2026, 3, 15, 9, 15, 0, tzinfo=timezone.utc)


def test_parse_backup_timestamp_handles_object_storage_prefix():
    ts = parse_backup_timestamp(f"{BACKUP_KEY_PREFIX}backup_20260315T091500Z.sql.gz")
    assert ts == datetime(2026, 3, 15, 9, 15, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    "name", ["not-a-backup.txt", "backup_garbage.sql.gz", "backup_20260315T091500Z.txt", ""]
)
def test_parse_backup_timestamp_returns_none_for_unrecognized_names(name):
    assert parse_backup_timestamp(name) is None


# --- create_dump -------------------------------------------------------------


def test_create_dump_requires_database_url(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        create_dump()


def test_create_dump_raises_on_pg_dump_failure(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@h:5432/d")
    fake_result = MagicMock(returncode=1, stderr=b"pg_dump: error: connection failed")
    with patch("scripts.backup_database.subprocess.run", return_value=fake_result):
        with pytest.raises(RuntimeError, match="connection failed"):
            create_dump()


def test_create_dump_compresses_pg_dump_output(monkeypatch):
    import gzip

    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@h:5432/d")
    fake_result = MagicMock(returncode=0, stdout=b"-- sql dump content --")
    with patch("scripts.backup_database.subprocess.run", return_value=fake_result) as mock_run:
        data = create_dump()

    assert gzip.decompress(data) == b"-- sql dump content --"
    command = mock_run.call_args[0][0]
    assert command[0] == "pg_dump"
    assert "postgresql://u:p@h:5432/d" in command  # +psycopg driver marker stripped


# --- run(): dump/save failure paths are loud, not silent --------------------


def test_run_returns_nonzero_and_logs_error_on_dump_failure(monkeypatch, caplog):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@h:5432/d")
    with patch("scripts.backup_database.create_dump", side_effect=RuntimeError("pg_dump exited 1: boom")):
        with caplog.at_level("ERROR"):
            exit_code = run()

    assert exit_code == 1
    error_records = [r for r in caplog.records if r.levelname == "ERROR"]
    assert any("backup.dump_failed" in r.message for r in error_records)


def test_run_returns_nonzero_and_logs_error_when_save_fails(monkeypatch, caplog):
    """Confirms the failure path a broken backup takes is exactly what
    Sentry's LoggingIntegration (see sentry_config.py) is configured to
    pick up automatically once SENTRY_DSN is set - a plain ERROR-level
    log record, no separate Sentry call needed anywhere in this script."""
    from app.storage import get_storage

    get_storage.cache_clear()
    for var in (
        "OBJECT_STORAGE_ENDPOINT_URL",
        "OBJECT_STORAGE_BUCKET",
        "OBJECT_STORAGE_ACCESS_KEY",
        "OBJECT_STORAGE_SECRET_KEY",
    ):
        monkeypatch.delenv(var, raising=False)

    with (
        patch("scripts.backup_database.create_dump", return_value=b"fake gzip bytes"),
        patch("scripts.backup_database.BACKUPS_DIR") as fake_dir,
        caplog.at_level("ERROR"),
    ):
        fake_dir.mkdir.side_effect = OSError("disk full")
        exit_code = run()
    get_storage.cache_clear()

    assert exit_code == 1
    error_records = [r for r in caplog.records if r.levelname == "ERROR"]
    assert any("backup.save_failed" in r.message for r in error_records)


def test_run_warns_when_saving_locally_only(monkeypatch, caplog, tmp_path):
    from app.storage import get_storage

    get_storage.cache_clear()
    for var in (
        "OBJECT_STORAGE_ENDPOINT_URL",
        "OBJECT_STORAGE_BUCKET",
        "OBJECT_STORAGE_ACCESS_KEY",
        "OBJECT_STORAGE_SECRET_KEY",
    ):
        monkeypatch.delenv(var, raising=False)

    with (
        patch("scripts.backup_database.create_dump", return_value=b"fake gzip bytes"),
        patch("scripts.backup_database.BACKUPS_DIR", tmp_path),
        caplog.at_level("WARNING"),
    ):
        exit_code = run()
    get_storage.cache_clear()

    assert exit_code == 0
    warning_records = [r for r in caplog.records if r.levelname == "WARNING"]
    assert any("NOT real off-machine protection" in r.message for r in warning_records)


# --- BackupRun recording (see app/models.py BackupRun, GET /api/admin/stats) -


def test_run_records_backup_run_row_on_success(monkeypatch, tmp_path):
    from app.database import SessionLocal
    from app.models import BackupRun
    from app.storage import get_storage

    get_storage.cache_clear()
    for var in (
        "OBJECT_STORAGE_ENDPOINT_URL",
        "OBJECT_STORAGE_BUCKET",
        "OBJECT_STORAGE_ACCESS_KEY",
        "OBJECT_STORAGE_SECRET_KEY",
    ):
        monkeypatch.delenv(var, raising=False)

    with (
        patch("scripts.backup_database.create_dump", return_value=b"fake gzip bytes"),
        patch("scripts.backup_database.BACKUPS_DIR", tmp_path),
    ):
        exit_code = run()
    get_storage.cache_clear()

    assert exit_code == 0
    db = SessionLocal()
    try:
        runs = db.query(BackupRun).order_by(BackupRun.id.desc()).all()
        assert len(runs) == 1
        assert runs[0].succeeded is True
        assert runs[0].error_message is None
        assert runs[0].started_at is not None
    finally:
        db.close()


def test_run_records_backup_run_row_on_dump_failure():
    from app.database import SessionLocal
    from app.models import BackupRun

    with patch("scripts.backup_database.create_dump", side_effect=RuntimeError("pg_dump exited 1: boom")):
        exit_code = run()

    assert exit_code == 1
    db = SessionLocal()
    try:
        runs = db.query(BackupRun).order_by(BackupRun.id.desc()).all()
        assert len(runs) == 1
        assert runs[0].succeeded is False
        assert runs[0].error_message == "pg_dump exited 1: boom"
    finally:
        db.close()


def test_run_records_backup_run_row_on_save_failure(monkeypatch):
    from app.database import SessionLocal
    from app.models import BackupRun
    from app.storage import get_storage

    get_storage.cache_clear()
    for var in (
        "OBJECT_STORAGE_ENDPOINT_URL",
        "OBJECT_STORAGE_BUCKET",
        "OBJECT_STORAGE_ACCESS_KEY",
        "OBJECT_STORAGE_SECRET_KEY",
    ):
        monkeypatch.delenv(var, raising=False)

    with (
        patch("scripts.backup_database.create_dump", return_value=b"fake gzip bytes"),
        patch("scripts.backup_database.BACKUPS_DIR") as fake_dir,
    ):
        fake_dir.mkdir.side_effect = OSError("disk full")
        exit_code = run()
    get_storage.cache_clear()

    assert exit_code == 1
    db = SessionLocal()
    try:
        runs = db.query(BackupRun).order_by(BackupRun.id.desc()).all()
        assert len(runs) == 1
        assert runs[0].succeeded is False
        assert "disk full" in runs[0].error_message
    finally:
        db.close()


def test_record_run_swallows_its_own_failure_rather_than_raising():
    """_record_run's own internal try/except is what makes recording an
    operational nicety rather than a hard dependency of the backup - a
    broken app database must not be able to turn a genuinely successful
    backup into a crash. Proven directly against _record_run (the actual
    protection boundary) rather than through run(), which relies
    entirely on this guarantee and has no second layer of its own."""
    from datetime import datetime, timezone

    from scripts.backup_database import _record_run

    # _record_run imports SessionLocal inline (from app.database) rather
    # than at module level - same reasoning as run()'s own inline
    # app.storage import, see _record_run's docstring - so the patch
    # target is app.database.SessionLocal, not a name on this module.
    with patch("app.database.SessionLocal", side_effect=RuntimeError("db is down")):
        # Must not raise.
        _record_run(datetime.now(timezone.utc), succeeded=True, error_message=None)


# --- Retention: same policy locally and in object storage -------------------


def test_local_retention_deletes_old_backups_keeps_recent_ones(monkeypatch, tmp_path):
    from app.storage import get_storage

    get_storage.cache_clear()
    for var in (
        "OBJECT_STORAGE_ENDPOINT_URL",
        "OBJECT_STORAGE_BUCKET",
        "OBJECT_STORAGE_ACCESS_KEY",
        "OBJECT_STORAGE_SECRET_KEY",
    ):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("BACKUP_RETENTION_DAYS", "30")

    old_name = backup_filename("20200101T000000Z")  # ancient
    recent_name = backup_filename(datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    (tmp_path / old_name).write_bytes(b"old")
    (tmp_path / recent_name).write_bytes(b"recent")

    with (
        patch("scripts.backup_database.create_dump", return_value=b"fake gzip bytes"),
        patch("scripts.backup_database.BACKUPS_DIR", tmp_path),
    ):
        exit_code = run()
    get_storage.cache_clear()

    assert exit_code == 0
    remaining = {p.name for p in tmp_path.iterdir() if p.name.startswith("backup_")}
    assert old_name not in remaining
    assert recent_name in remaining


def test_object_storage_retention_deletes_old_backups_keeps_recent_ones(monkeypatch):
    monkeypatch.setenv("OBJECT_STORAGE_ENDPOINT_URL", "https://example.r2.cloudflarestorage.com")
    monkeypatch.setenv("OBJECT_STORAGE_BUCKET", "test-bucket")
    monkeypatch.setenv("OBJECT_STORAGE_ACCESS_KEY", "key")
    monkeypatch.setenv("OBJECT_STORAGE_SECRET_KEY", "secret")
    monkeypatch.setenv("BACKUP_RETENTION_DAYS", "30")

    old_key = f"{BACKUP_KEY_PREFIX}{backup_filename('20200101T000000Z')}"
    recent_key = f"{BACKUP_KEY_PREFIX}{backup_filename(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))}"

    fake_client = MagicMock()
    fake_client.list_objects_v2.return_value = {
        "Contents": [{"Key": old_key}, {"Key": recent_key}],
        "IsTruncated": False,
    }

    from app.storage import get_storage

    get_storage.cache_clear()
    with (
        patch("scripts.backup_database.create_dump", return_value=b"fake gzip bytes"),
        patch("app.storage.boto3.client", return_value=fake_client),
    ):
        exit_code = run()
    get_storage.cache_clear()

    assert exit_code == 0
    fake_client.put_object.assert_called_once()
    fake_client.delete_object.assert_called_once_with(Bucket="test-bucket", Key=old_key)
