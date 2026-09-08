from unittest.mock import MagicMock, patch

from app.storage import (
    PRESIGNED_URL_EXPIRE_SECONDS,
    LocalDiskStorage,
    S3CompatibleStorage,
    get_storage,
)


def _fake_s3_storage(fake_client) -> S3CompatibleStorage:
    with patch("app.storage.boto3.client", return_value=fake_client):
        return S3CompatibleStorage(
            endpoint_url="https://example.r2.cloudflarestorage.com",
            bucket="test-bucket",
            access_key="key",
            secret_key="secret",
            region="auto",
        )


# --- Backend selection (same opt-in pattern as SENTRY_DSN/SMTP_HOST) ------


def test_get_storage_defaults_to_local_disk_when_unconfigured(monkeypatch):
    for var in (
        "OBJECT_STORAGE_ENDPOINT_URL",
        "OBJECT_STORAGE_BUCKET",
        "OBJECT_STORAGE_ACCESS_KEY",
        "OBJECT_STORAGE_SECRET_KEY",
    ):
        monkeypatch.delenv(var, raising=False)
    get_storage.cache_clear()

    assert isinstance(get_storage(), LocalDiskStorage)


def test_get_storage_selects_s3_when_fully_configured(monkeypatch):
    monkeypatch.setenv("OBJECT_STORAGE_ENDPOINT_URL", "https://example.r2.cloudflarestorage.com")
    monkeypatch.setenv("OBJECT_STORAGE_BUCKET", "test-bucket")
    monkeypatch.setenv("OBJECT_STORAGE_ACCESS_KEY", "key")
    monkeypatch.setenv("OBJECT_STORAGE_SECRET_KEY", "secret")
    get_storage.cache_clear()

    assert isinstance(get_storage(), S3CompatibleStorage)


def test_get_storage_falls_back_to_local_disk_if_only_partially_configured(monkeypatch):
    """All four required vars must be present - a half-configured object
    store (e.g. endpoint set but no bucket yet) must not be treated as
    ready, silently pointing at a client with missing credentials."""
    monkeypatch.setenv("OBJECT_STORAGE_ENDPOINT_URL", "https://example.r2.cloudflarestorage.com")
    monkeypatch.delenv("OBJECT_STORAGE_BUCKET", raising=False)
    monkeypatch.delenv("OBJECT_STORAGE_ACCESS_KEY", raising=False)
    monkeypatch.delenv("OBJECT_STORAGE_SECRET_KEY", raising=False)
    get_storage.cache_clear()

    assert isinstance(get_storage(), LocalDiskStorage)


# --- LocalDiskStorage ------------------------------------------------------


def test_local_disk_storage_round_trip(tmp_path, monkeypatch):
    import app.storage as storage_module

    monkeypatch.setattr(storage_module, "UPLOADS_DIR", tmp_path)
    storage = LocalDiskStorage()

    key = storage.save(b"hello world", ".png")
    assert key.endswith(".png")
    assert (tmp_path / key).read_bytes() == b"hello world"

    storage.delete(key)
    assert not (tmp_path / key).exists()


def test_local_disk_storage_serve_response_404s_for_missing_file(tmp_path, monkeypatch):
    import app.storage as storage_module
    from fastapi import HTTPException

    monkeypatch.setattr(storage_module, "UPLOADS_DIR", tmp_path)
    storage = LocalDiskStorage()

    try:
        storage.serve_response("does-not-exist.png")
        assert False, "expected HTTPException"
    except HTTPException as exc:
        assert exc.status_code == 404


# --- S3CompatibleStorage (boto3 mocked - no real cloud credentials) --------


def test_s3_storage_save_uploads_bytes_under_a_generated_key():
    fake_client = MagicMock()
    storage = _fake_s3_storage(fake_client)

    key = storage.save(b"image bytes", ".jpg")

    assert key.endswith(".jpg")
    fake_client.put_object.assert_called_once_with(Bucket="test-bucket", Key=key, Body=b"image bytes")


def test_s3_storage_put_uploads_under_an_exact_given_key():
    """Used by the migration script to preserve existing filenames."""
    fake_client = MagicMock()
    storage = _fake_s3_storage(fake_client)

    storage.put("existing-file-abc123.png", b"old bytes")

    fake_client.put_object.assert_called_once_with(
        Bucket="test-bucket", Key="existing-file-abc123.png", Body=b"old bytes"
    )


def test_s3_storage_delete_calls_delete_object():
    fake_client = MagicMock()
    storage = _fake_s3_storage(fake_client)

    storage.delete("some-key.png")

    fake_client.delete_object.assert_called_once_with(Bucket="test-bucket", Key="some-key.png")


def test_s3_storage_serve_response_redirects_to_a_presigned_url_not_a_public_one():
    """The bucket itself is never made public - every read is a
    short-lived signed URL generated only after the caller's permission
    to view the image has already been checked (see routers/entries.py)."""
    fake_client = MagicMock()
    fake_client.generate_presigned_url.return_value = (
        "https://example.r2.cloudflarestorage.com/test-bucket/some-key.png?X-Amz-Signature=deadbeef"
    )
    storage = _fake_s3_storage(fake_client)

    response = storage.serve_response("some-key.png")

    assert response.status_code in (302, 303, 307)
    assert response.headers["location"] == (
        "https://example.r2.cloudflarestorage.com/test-bucket/some-key.png?X-Amz-Signature=deadbeef"
    )
    fake_client.generate_presigned_url.assert_called_once_with(
        "get_object",
        Params={"Bucket": "test-bucket", "Key": "some-key.png"},
        ExpiresIn=PRESIGNED_URL_EXPIRE_SECONDS,
    )


def test_presigned_url_expiry_is_short_lived():
    """A leaked or cached link should stop working shortly after, not
    grant standing access - a handful of minutes, not hours or days."""
    assert 0 < PRESIGNED_URL_EXPIRE_SECONDS <= 900
