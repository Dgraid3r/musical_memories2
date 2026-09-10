"""Add entry_edit_events for entry edit-history audit log

Audit log only, not version history - no snapshot of the old/new content
is stored anywhere. One row per edit made to an entry after creation
(text/tags/visibility/coauthors via PATCH, or photos via POST .../images),
recording who made it, when, and a short change_summary label. See
app/models.py EntryEditEvent and routers/entries.py update_entry/
add_images/get_entry_edit_history.

Revision ID: 0009
Revises: 0008
Create Date: 2026-09-10

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "entry_edit_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("entry_id", sa.Integer(), sa.ForeignKey("journal_entries.id"), nullable=False),
        sa.Column("editor_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("edited_at", sa.DateTime(), nullable=False),
        sa.Column("change_summary", sa.String(), nullable=False),
    )
    op.create_index("ix_entry_edit_events_entry_id", "entry_edit_events", ["entry_id"])
    op.create_index("ix_entry_edit_events_editor_user_id", "entry_edit_events", ["editor_user_id"])


def downgrade() -> None:
    op.drop_index("ix_entry_edit_events_editor_user_id", table_name="entry_edit_events")
    op.drop_index("ix_entry_edit_events_entry_id", table_name="entry_edit_events")
    op.drop_table("entry_edit_events")
