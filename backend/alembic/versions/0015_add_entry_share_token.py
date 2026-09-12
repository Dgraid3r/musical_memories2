"""Add journal_entries.share_token for single-entry public sharing

Nullable, unique when set - an unguessable public-link token for sharing
one specific entry without making its workspace (or even the entry
itself, via is_public) visible to anyone else. Every existing entry
starts with share_token NULL, which is correct: no entry has ever been
individually shared before this.

Revision ID: 0015
Revises: 0014
Create Date: 2026-09-12

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0015"
down_revision: Union[str, None] = "0014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("journal_entries", sa.Column("share_token", sa.String(), nullable=True))
    op.create_index("ix_journal_entries_share_token", "journal_entries", ["share_token"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_journal_entries_share_token", table_name="journal_entries")
    op.drop_column("journal_entries", "share_token")
