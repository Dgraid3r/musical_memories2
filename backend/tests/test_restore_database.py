import gzip
from unittest.mock import MagicMock, patch

import pytest

from scripts.restore_database import _most_recent_object_storage_key, main, restore_dump


# --- restore_dump --------------------------------------------------------


def test_restore_dump_requires_database_url(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        restore_dump(gzip.compress(b"select 1;"))


def test_restore_dump_raises_on_psql_failure(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@h:5432/d")
    fake_result = MagicMock(returncode=1, stderr=b"psql: error: relation already exists")
    with patch("scripts.restore_database.subprocess.run", return_value=fake_result):
        with pytest.raises(RuntimeError, match="already exists"):
            restore_dump(gzip.compress(b"create table x();"))


def test_restore_dump_pipes_decompressed_sql_into_psql(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@h:5432/d")
    fake_result = MagicMock(returncode=0, stderr=b"")
    with patch("scripts.restore_database.subprocess.run", return_value=fake_result) as mock_run:
        restore_dump(gzip.compress(b"create table x();"))

    call_kwargs = mock_run.call_args.kwargs
    assert call_kwargs["input"] == b"create table x();"
    command = mock_run.call_args[0][0]
    assert command[0] == "psql"
    assert "postgresql://u:p@h:5432/d" in command


# --- _most_recent_object_storage_key ----------------------------------------


def test_most_recent_object_storage_key_picks_the_latest():
    fake_storage = MagicMock()
    fake_storage.list_keys.return_value = [
        "backups/backup_20200101T000000Z.sql.gz",
        "backups/backup_20260315T091500Z.sql.gz",
        "backups/backup_20230601T000000Z.sql.gz",
    ]
    assert _most_recent_object_storage_key(fake_storage) == "backups/backup_20260315T091500Z.sql.gz"


def test_most_recent_object_storage_key_ignores_unrecognized_keys():
    fake_storage = MagicMock()
    fake_storage.list_keys.return_value = ["backups/not-a-backup.txt"]
    assert _most_recent_object_storage_key(fake_storage) is None


def test_most_recent_object_storage_key_none_when_empty():
    fake_storage = MagicMock()
    fake_storage.list_keys.return_value = []
    assert _most_recent_object_storage_key(fake_storage) is None


# --- CLI (main) --------------------------------------------------------


def test_main_rejects_neither_file_nor_object_storage_flag(caplog):
    with caplog.at_level("ERROR"):
        exit_code = main([])
    assert exit_code == 1
    assert any("restore.invalid_args" in r.message for r in caplog.records)


def test_main_rejects_both_file_and_object_storage_flag(caplog):
    with caplog.at_level("ERROR"):
        exit_code = main(["some_file.sql.gz", "--from-object-storage"])
    assert exit_code == 1
    assert any("restore.invalid_args" in r.message for r in caplog.records)


def test_main_logs_error_on_unreadable_file(caplog):
    with caplog.at_level("ERROR"):
        exit_code = main(["/definitely/does/not/exist.sql.gz"])
    assert exit_code == 1
    assert any("restore.read_failed" in r.message for r in caplog.records)


def test_main_restores_a_local_file_and_reports_completion(tmp_path, monkeypatch, caplog):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@h:5432/d")
    backup_path = tmp_path / "backup_20260101T000000Z.sql.gz"
    backup_path.write_bytes(gzip.compress(b"select 1;"))

    with patch("scripts.restore_database.restore_dump") as mock_restore, caplog.at_level("INFO"):
        exit_code = main([str(backup_path)])

    assert exit_code == 0
    mock_restore.assert_called_once()
    assert mock_restore.call_args[0][0] == gzip.compress(b"select 1;")
    assert any("restore.completed" in r.message for r in caplog.records)


def test_main_object_storage_not_configured_fails_cleanly(monkeypatch, caplog):
    from app.storage import get_storage

    for var in (
        "OBJECT_STORAGE_ENDPOINT_URL",
        "OBJECT_STORAGE_BUCKET",
        "OBJECT_STORAGE_ACCESS_KEY",
        "OBJECT_STORAGE_SECRET_KEY",
    ):
        monkeypatch.delenv(var, raising=False)
    get_storage.cache_clear()

    with caplog.at_level("ERROR"):
        exit_code = main(["--from-object-storage"])
    get_storage.cache_clear()

    assert exit_code == 1
    assert any("restore.object_storage_not_configured" in r.message for r in caplog.records)


def test_main_restores_from_object_storage_by_explicit_key(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@h:5432/d")
    monkeypatch.setenv("OBJECT_STORAGE_ENDPOINT_URL", "https://example.r2.cloudflarestorage.com")
    monkeypatch.setenv("OBJECT_STORAGE_BUCKET", "test-bucket")
    monkeypatch.setenv("OBJECT_STORAGE_ACCESS_KEY", "key")
    monkeypatch.setenv("OBJECT_STORAGE_SECRET_KEY", "secret")

    from app.storage import get_storage

    get_storage.cache_clear()
    fake_client = MagicMock()
    fake_client.get_object.return_value = {"Body": MagicMock(read=lambda: gzip.compress(b"select 1;"))}

    with (
        patch("app.storage.boto3.client", return_value=fake_client),
        patch("scripts.restore_database.restore_dump") as mock_restore,
    ):
        exit_code = main(["--from-object-storage", "--key", "backups/backup_20260101T000000Z.sql.gz"])
    get_storage.cache_clear()

    assert exit_code == 0
    fake_client.get_object.assert_called_once_with(
        Bucket="test-bucket", Key="backups/backup_20260101T000000Z.sql.gz"
    )
    mock_restore.assert_called_once()
