"""Grants site-wide admin access (see app/models.py User.is_admin) to an
existing user, by username - run this once manually against your own
database to create the first admin.

There is deliberately no web endpoint for this: an admin-granting
endpoint would itself need an admin to already exist in order to call it
(routers/admin.py's whole surface requires auth.require_admin), which
doesn't help for the very first one. A later admin can grant another the
same way, by running this script again - v1 has no in-app "promote to
admin" UI.

Usage (from backend/):
    python -m scripts.grant_admin <username>
"""

import sys

from app.database import SessionLocal
from app.models import User


def grant_admin(username: str) -> int:
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == username).one_or_none()
        if user is None:
            print(f"No user found with username {username!r}.")
            return 1
        if user.is_deleted:
            print(f"{username!r} is a deleted account - refusing to grant admin access.")
            return 1
        if user.is_admin:
            print(f"{username!r} already has admin access.")
            return 0

        user.is_admin = True
        db.commit()
        print(f"Granted admin access to {username!r} (user id {user.id}).")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python -m scripts.grant_admin <username>")
        sys.exit(1)
    sys.exit(grant_admin(sys.argv[1]))
