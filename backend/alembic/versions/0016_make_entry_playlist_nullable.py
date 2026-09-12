"""Make journal_entries.playlist_id/name/url nullable

An offline-created draft (see the PWA offline-drafts feature) has no
network access to Spotify search at capture time, so it syncs with no
playlist at all rather than blocking capture on picking one. The three
columns become independently nullable; every existing row already has
real values in all three, so this is a pure relaxation with nothing to
backfill.

Revision ID: 0016
Revises: 0015
Create Date: 2026-09-12

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0016"
down_revision: Union[str, None] = "0015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column("journal_entries", "playlist_id", existing_type=sa.String(), nullable=True)
    op.alter_column("journal_entries", "playlist_name", existing_type=sa.String(), nullable=True)
    op.alter_column("journal_entries", "playlist_url", existing_type=sa.String(), nullable=True)


def downgrade() -> None:
    op.alter_column("journal_entries", "playlist_url", existing_type=sa.String(), nullable=False)
    op.alter_column("journal_entries", "playlist_name", existing_type=sa.String(), nullable=False)
    op.alter_column("journal_entries", "playlist_id", existing_type=sa.String(), nullable=False)
