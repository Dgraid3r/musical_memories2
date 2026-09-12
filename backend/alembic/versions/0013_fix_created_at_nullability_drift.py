"""Fix created_at/updated_at nullability drift from the models

Every `created_at` column (plus spotify_tokens.updated_at) was created by
an earlier migration as `nullable=True`, but app/models.py has always
declared these as `Mapped[datetime]` (no `| None`) - i.e. NOT NULL, with
a Python-side default (`default=datetime.utcnow`) rather than a
server_default. A new schema-drift check
(tests/test_schema_drift.py, comparing a database at `alembic upgrade
head` against the models via Alembic's own autogenerate machinery)
caught this: `Base.metadata.create_all()`, which the test suite uses to
build its schema, has always applied NOT NULL here (it derives
nullability from the type annotation), so this drift was invisible to
every test - only a real deployment running this actual migration chain
would ever end up with a column the ORM believes can never be NULL, but
the database allows anyway.

Aligning the migration to the model (not the other way around) because
every code path that writes one of these columns already goes through
the ORM's own default - there's no route in this app that leaves one of
them NULL by design, so NOT NULL is the intended, correct constraint,
and the original migrations were simply wrong to allow NULL.

The UPDATE ... WHERE ... IS NULL backfill immediately before each ALTER
COLUMN ... SET NOT NULL is defensive, not because any NULL is expected
in practice (the ORM's Python-side default has applied on every insert
since each table was created, and the one migration that inserts rows
with raw SQL - 0005_add_workspaces.py's backfill - already supplies
created_at explicitly) - it just makes this migration safe to run
unconditionally rather than assuming that history, and makes it a no-op
in the overwhelmingly likely case that no row is actually NULL.

Revision ID: 0013
Revises: 0012
Create Date: 2026-09-12

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0013"
down_revision: Union[str, None] = "0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# (table, column) pairs to correct - every created_at column in the
# schema, plus spotify_tokens.updated_at (also Mapped[datetime], no
# server_default, same drift).
_COLUMNS = [
    ("users", "created_at"),
    ("journal_entries", "created_at"),
    ("spotify_tokens", "created_at"),
    ("spotify_tokens", "updated_at"),
    ("comments", "created_at"),
    ("workspaces", "created_at"),
    ("workspace_memberships", "created_at"),
    ("workspace_invites", "created_at"),
    ("email_verification_tokens", "created_at"),
    ("password_reset_tokens", "created_at"),
]


def upgrade() -> None:
    for table, column in _COLUMNS:
        op.execute(f'UPDATE "{table}" SET "{column}" = now() WHERE "{column}" IS NULL')
        op.alter_column(table, column, existing_type=sa.DateTime(), nullable=False)


def downgrade() -> None:
    for table, column in _COLUMNS:
        op.alter_column(table, column, existing_type=sa.DateTime(), nullable=True)
