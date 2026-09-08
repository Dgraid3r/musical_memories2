"""One-time script: uploads every existing file in backend/uploads/ to
configured object storage, under its *existing* filename/key. Because
EntryImage.filename is already just an opaque stored-key string - the
same value LocalDiskStorage and S3CompatibleStorage each use as their
own key - re-uploading under that same key means no database row needs
to change at all. Once this finishes, the app starts serving those
images from object storage automatically, because get_storage() already
prefers it whenever OBJECT_STORAGE_* is configured (see app/storage.py).

This is a plain script, not an Alembic migration - it moves files, not
schema. It is never run automatically, and it isn't required: until you
actually configure OBJECT_STORAGE_* in backend/.env, existing images
keep working exactly as they do today, straight off local disk. Local
files are left in place after a successful run - remove backend/uploads/
yourself, once you've verified everything looks right, if you want to.

Usage (from backend/, with OBJECT_STORAGE_* already configured):
    python -m scripts.migrate_uploads_to_object_storage [--dry-run]

Idempotent: a manifest file (backend/uploads/.migrated_to_object_storage.json)
records what's already been uploaded, so re-running only picks up files
added since the last run.
"""

import argparse
import json
import logging
import sys
from datetime import datetime, timezone

from app.storage import UPLOADS_DIR, LocalDiskStorage, S3CompatibleStorage, get_storage

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

MANIFEST_FILENAME = ".migrated_to_object_storage.json"


def _manifest_path():
    # A function, not a module-level constant computed once from
    # UPLOADS_DIR at import time - this module's own UPLOADS_DIR name is
    # what a test patches to point at a temp directory, and a
    # pre-computed constant wouldn't follow that patch.
    return UPLOADS_DIR / MANIFEST_FILENAME


def _load_manifest() -> dict:
    path = _manifest_path()
    if path.is_file():
        return json.loads(path.read_text())
    return {}


def _save_manifest(manifest: dict) -> None:
    _manifest_path().write_text(json.dumps(manifest, indent=2, sort_keys=True))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--dry-run", action="store_true", help="List what would be uploaded without uploading anything"
    )
    args = parser.parse_args(argv)

    storage = get_storage()
    if isinstance(storage, LocalDiskStorage):
        logger.error(
            "Object storage isn't configured (OBJECT_STORAGE_* env vars are unset in backend/.env) - "
            "there's nothing to migrate to. Configure it first, then re-run this script."
        )
        return 1
    assert isinstance(storage, S3CompatibleStorage)

    if not UPLOADS_DIR.is_dir():
        logger.info("No local uploads directory found (%s) - nothing to migrate.", UPLOADS_DIR)
        return 0

    manifest = _load_manifest()
    local_files = [p for p in sorted(UPLOADS_DIR.iterdir()) if p.is_file() and p.name != MANIFEST_FILENAME]
    to_migrate = [p for p in local_files if p.name not in manifest]

    if not to_migrate:
        logger.info(
            "Nothing to migrate - every local file is already recorded as migrated (%s).", _manifest_path()
        )
        return 0

    logger.info("Found %d local file(s) to migrate to object storage.", len(to_migrate))
    for path in to_migrate:
        if args.dry_run:
            logger.info("[dry-run] would upload %s", path.name)
            continue
        storage.put(path.name, path.read_bytes())
        manifest[path.name] = datetime.now(timezone.utc).isoformat()
        logger.info("Uploaded %s", path.name)

    if args.dry_run:
        logger.info("[dry-run] no files were actually uploaded, and the manifest was not updated.")
        return 0

    _save_manifest(manifest)
    logger.info(
        "Done. %d file(s) uploaded to object storage under their existing filenames - no database "
        "changes were needed. Local copies in %s were left in place; remove them yourself once "
        "you've verified everything looks right.",
        len(to_migrate),
        UPLOADS_DIR,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
