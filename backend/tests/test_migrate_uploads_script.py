import json
import os
from unittest.mock import MagicMock, patch

from app.storage import get_storage
from scripts.migrate_uploads_to_object_storage import main


def test_refuses_to_run_when_object_storage_is_not_configured(tmp_path, caplog):
    for var in (
        "OBJECT_STORAGE_ENDPOINT_URL",
        "OBJECT_STORAGE_BUCKET",
        "OBJECT_STORAGE_ACCESS_KEY",
        "OBJECT_STORAGE_SECRET_KEY",
    ):
        os.environ.pop(var, None)

    get_storage.cache_clear()
    with patch("scripts.migrate_uploads_to_object_storage.UPLOADS_DIR", tmp_path), caplog.at_level("ERROR"):
        exit_code = main([])
    get_storage.cache_clear()

    assert exit_code != 0
    assert "isn't configured" in caplog.text


def test_migrates_local_files_to_object_storage_under_same_filenames(tmp_path):
    (tmp_path / "abc123.png").write_bytes(b"photo one")
    (tmp_path / "def456.jpg").write_bytes(b"photo two")

    fake_client = MagicMock()
    with (
        patch("scripts.migrate_uploads_to_object_storage.UPLOADS_DIR", tmp_path),
        patch("app.storage.UPLOADS_DIR", tmp_path),
        patch("app.storage.boto3.client", return_value=fake_client),
    ):
        get_storage.cache_clear()
        with patch.dict(
            "os.environ",
            {
                "OBJECT_STORAGE_ENDPOINT_URL": "https://example.r2.cloudflarestorage.com",
                "OBJECT_STORAGE_BUCKET": "test-bucket",
                "OBJECT_STORAGE_ACCESS_KEY": "key",
                "OBJECT_STORAGE_SECRET_KEY": "secret",
            },
        ):
            exit_code = main([])
        get_storage.cache_clear()

    assert exit_code == 0
    uploaded_keys = {call.kwargs["Key"] for call in fake_client.put_object.call_args_list}
    assert uploaded_keys == {"abc123.png", "def456.jpg"}
    uploaded_bodies = {call.kwargs["Key"]: call.kwargs["Body"] for call in fake_client.put_object.call_args_list}
    assert uploaded_bodies["abc123.png"] == b"photo one"
    assert uploaded_bodies["def456.jpg"] == b"photo two"

    manifest = json.loads((tmp_path / ".migrated_to_object_storage.json").read_text())
    assert set(manifest.keys()) == {"abc123.png", "def456.jpg"}

    # Local copies are left in place - this is additive, not destructive.
    assert (tmp_path / "abc123.png").exists()
    assert (tmp_path / "def456.jpg").exists()


def test_is_idempotent_and_only_uploads_new_files_on_a_second_run(tmp_path):
    (tmp_path / "already-done.png").write_bytes(b"old")

    fake_client = MagicMock()
    env = {
        "OBJECT_STORAGE_ENDPOINT_URL": "https://example.r2.cloudflarestorage.com",
        "OBJECT_STORAGE_BUCKET": "test-bucket",
        "OBJECT_STORAGE_ACCESS_KEY": "key",
        "OBJECT_STORAGE_SECRET_KEY": "secret",
    }
    with (
        patch("scripts.migrate_uploads_to_object_storage.UPLOADS_DIR", tmp_path),
        patch("app.storage.UPLOADS_DIR", tmp_path),
        patch("app.storage.boto3.client", return_value=fake_client),
    ):
        get_storage.cache_clear()
        with patch.dict("os.environ", env):
            main([])
        get_storage.cache_clear()

        # A new file shows up between runs.
        (tmp_path / "new-file.png").write_bytes(b"new")
        fake_client.put_object.reset_mock()

        get_storage.cache_clear()
        with patch.dict("os.environ", env):
            exit_code = main([])
        get_storage.cache_clear()

    assert exit_code == 0
    uploaded_keys = {call.kwargs["Key"] for call in fake_client.put_object.call_args_list}
    assert uploaded_keys == {"new-file.png"}


def test_dry_run_uploads_nothing_and_does_not_write_a_manifest(tmp_path):
    (tmp_path / "abc123.png").write_bytes(b"photo one")

    fake_client = MagicMock()
    with (
        patch("scripts.migrate_uploads_to_object_storage.UPLOADS_DIR", tmp_path),
        patch("app.storage.UPLOADS_DIR", tmp_path),
        patch("app.storage.boto3.client", return_value=fake_client),
    ):
        get_storage.cache_clear()
        with patch.dict(
            "os.environ",
            {
                "OBJECT_STORAGE_ENDPOINT_URL": "https://example.r2.cloudflarestorage.com",
                "OBJECT_STORAGE_BUCKET": "test-bucket",
                "OBJECT_STORAGE_ACCESS_KEY": "key",
                "OBJECT_STORAGE_SECRET_KEY": "secret",
            },
        ):
            exit_code = main(["--dry-run"])
        get_storage.cache_clear()

    assert exit_code == 0
    fake_client.put_object.assert_not_called()
    assert not (tmp_path / ".migrated_to_object_storage.json").exists()


def test_no_uploads_directory_is_a_clean_no_op(tmp_path):
    missing_dir = tmp_path / "does-not-exist"
    fake_client = MagicMock()
    with (
        patch("scripts.migrate_uploads_to_object_storage.UPLOADS_DIR", missing_dir),
        patch("app.storage.boto3.client", return_value=fake_client),
    ):
        get_storage.cache_clear()
        with patch.dict(
            "os.environ",
            {
                "OBJECT_STORAGE_ENDPOINT_URL": "https://example.r2.cloudflarestorage.com",
                "OBJECT_STORAGE_BUCKET": "test-bucket",
                "OBJECT_STORAGE_ACCESS_KEY": "key",
                "OBJECT_STORAGE_SECRET_KEY": "secret",
            },
        ):
            exit_code = main([])
        get_storage.cache_clear()

    assert exit_code == 0
    fake_client.put_object.assert_not_called()
