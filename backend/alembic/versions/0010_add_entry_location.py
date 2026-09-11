"""Add optional location fields to journal_entries

latitude/longitude/location_name - all nullable, all set together or not
at all from the API's perspective (see app/schemas.py EntryLocationInput).
Every existing entry has no location, which is a completely normal state,
not a migration to backfill.

Revision ID: 0010
Revises: 0009
Create Date: 2026-09-10

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("journal_entries", sa.Column("latitude", sa.Float(), nullable=True))
    op.add_column("journal_entries", sa.Column("longitude", sa.Float(), nullable=True))
    op.add_column("journal_entries", sa.Column("location_name", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("journal_entries", "location_name")
    op.drop_column("journal_entries", "longitude")
    op.drop_column("journal_entries", "latitude")
