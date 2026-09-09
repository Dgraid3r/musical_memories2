"""Pluggable storage for entry-photo uploads - the same opt-in pattern
already used for SENTRY_DSN and SMTP_HOST: absent OBJECT_STORAGE_* env
vars means local disk (today's behavior, unchanged, zero cost, zero
signup); configuring them switches to an S3-compatible object storage
backend instead.

Deliberately built against the generic S3 API via boto3 (not an
AWS-specific SDK path), so this works unmodified against AWS S3,
Cloudflare R2, Backblaze B2, or a local MinIO container for dev/testing -
whichever provider the captain picks later, with no code change.

Access control note: nothing in this module is itself a permission
check - routers/entries.py's image-fetch endpoint is what enforces entry
visibility before ever calling serve_response(). This module only knows
how to store, delete, and hand back a Response for a given stored key.
"""

import logging
import os
import uuid
from functools import lru_cache
from pathlib import Path
from typing import Protocol

import boto3
from botocore.client import Config as BotoConfig
from fastapi import HTTPException
from fastapi.responses import FileResponse, RedirectResponse, Response

logger = logging.getLogger(__name__)

UPLOADS_DIR = Path(__file__).resolve().parent.parent / "uploads"

# Short-lived on purpose: a leaked or cached presigned URL (in a browser
# history, a proxy log, a shared screenshot of dev tools) stops working
# shortly after, rather than granting standing access to a private photo.
PRESIGNED_URL_EXPIRE_SECONDS = 300


class ObjectStorage(Protocol):
    def save(self, data: bytes, suffix: str) -> str:
        """Stores the bytes under a newly generated key and returns it -
        the same value persisted as EntryImage.filename."""
        ...

    def delete(self, stored_name: str) -> None: ...

    def serve_response(self, stored_name: str) -> Response:
        """Returns the Response the image-fetch endpoint sends back to an
        already-permission-checked caller - a streamed file (local disk)
        or a redirect to a short-lived presigned URL (object storage)."""
        ...

    def list_keys(self, prefix: str) -> list[str]:
        """Every stored key starting with `prefix` - used by
        scripts/backup_database.py to find backups (stored under a
        backups/ prefix) for retention cleanup."""
        ...

    def get_bytes(self, stored_name: str) -> bytes:
        """Reads a stored object's raw bytes back out - used by
        scripts/restore_database.py to fetch a backup for restoring.
        Distinct from serve_response(), which is for the permission-
        checked photo-fetch endpoint's browser-facing Response, not a
        script that wants the actual bytes."""
        ...


class LocalDiskStorage:
    """Today's behavior: files live in backend/uploads/, named with a
    random UUID (not the original filename) plus the original extension."""

    def __init__(self) -> None:
        UPLOADS_DIR.mkdir(exist_ok=True)

    def save(self, data: bytes, suffix: str) -> str:
        stored_name = f"{uuid.uuid4().hex}{suffix}"
        (UPLOADS_DIR / stored_name).write_bytes(data)
        return stored_name

    def delete(self, stored_name: str) -> None:
        (UPLOADS_DIR / stored_name).unlink(missing_ok=True)

    def serve_response(self, stored_name: str) -> Response:
        path = UPLOADS_DIR / stored_name
        if not path.is_file():
            raise HTTPException(status_code=404, detail="Image not found")
        return FileResponse(path)

    def list_keys(self, prefix: str) -> list[str]:
        return [p.name for p in UPLOADS_DIR.glob(f"{prefix}*") if p.is_file()]

    def get_bytes(self, stored_name: str) -> bytes:
        return (UPLOADS_DIR / stored_name).read_bytes()


class S3CompatibleStorage:
    """Any provider speaking the generic S3 API - AWS S3, Cloudflare R2,
    Backblaze B2, MinIO, etc. The bucket itself never needs to be public:
    reads go through a short-lived presigned URL generated only after
    routers/entries.py has already confirmed the caller may view this
    entry."""

    def __init__(self, endpoint_url: str, bucket: str, access_key: str, secret_key: str, region: str | None) -> None:
        self._bucket = bucket
        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region or "auto",
            config=BotoConfig(signature_version="s3v4"),
        )

    def save(self, data: bytes, suffix: str) -> str:
        stored_name = f"{uuid.uuid4().hex}{suffix}"
        self.put(stored_name, data)
        return stored_name

    def put(self, key: str, data: bytes) -> None:
        """Uploads under an exact, caller-chosen key rather than a newly
        generated one - used by save() above and by
        scripts/migrate_uploads_to_object_storage.py, which re-uploads
        existing local files under their existing filenames so
        EntryImage.filename rows in the database never need to change."""
        self._client.put_object(Bucket=self._bucket, Key=key, Body=data)

    def delete(self, stored_name: str) -> None:
        self._client.delete_object(Bucket=self._bucket, Key=stored_name)

    def serve_response(self, stored_name: str) -> Response:
        url = self._client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self._bucket, "Key": stored_name},
            ExpiresIn=PRESIGNED_URL_EXPIRE_SECONDS,
        )
        return RedirectResponse(url)

    def list_keys(self, prefix: str) -> list[str]:
        keys: list[str] = []
        continuation_token: str | None = None
        while True:
            kwargs: dict = {"Bucket": self._bucket, "Prefix": prefix}
            if continuation_token:
                kwargs["ContinuationToken"] = continuation_token
            response = self._client.list_objects_v2(**kwargs)
            keys.extend(obj["Key"] for obj in response.get("Contents", []))
            if not response.get("IsTruncated"):
                break
            continuation_token = response.get("NextContinuationToken")
        return keys

    def get_bytes(self, stored_name: str) -> bytes:
        response = self._client.get_object(Bucket=self._bucket, Key=stored_name)
        return response["Body"].read()


@lru_cache
def get_storage() -> ObjectStorage:
    endpoint_url = os.environ.get("OBJECT_STORAGE_ENDPOINT_URL")
    bucket = os.environ.get("OBJECT_STORAGE_BUCKET")
    access_key = os.environ.get("OBJECT_STORAGE_ACCESS_KEY")
    secret_key = os.environ.get("OBJECT_STORAGE_SECRET_KEY")
    region = os.environ.get("OBJECT_STORAGE_REGION")

    if endpoint_url and bucket and access_key and secret_key:
        logger.info("storage.backend selected=s3_compatible bucket=%r", bucket)
        return S3CompatibleStorage(endpoint_url, bucket, access_key, secret_key, region)

    logger.info("storage.backend selected=local_disk")
    return LocalDiskStorage()
