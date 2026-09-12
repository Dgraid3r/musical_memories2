"""Add notifications for comments and workspace invites

New `notifications` table (see app/models.py's Notification docstring
for the full design reasoning - deliberately generic so a future
notification type can reuse it without a schema rework). `entry_id`/
`workspace_id` are ON DELETE SET NULL: deleting the entry/workspace a
notification pointed to leaves the notification row in place (still a
readable historical message) with that one reference nulled out,
rather than cascading the delete into notifications or leaving a
dangling foreign key.

Revision ID: 0014
Revises: 0013
Create Date: 2026-09-12

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0014"
down_revision: Union[str, None] = "0013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "notifications",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("message", sa.String(), nullable=False),
        sa.Column(
            "entry_id", sa.Integer(), sa.ForeignKey("journal_entries.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column(
            "workspace_id", sa.Integer(), sa.ForeignKey("workspaces.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("read_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_notifications_user_id", "notifications", ["user_id"])
    op.create_index("ix_notifications_entry_id", "notifications", ["entry_id"])
    op.create_index("ix_notifications_workspace_id", "notifications", ["workspace_id"])


def downgrade() -> None:
    op.drop_index("ix_notifications_workspace_id", table_name="notifications")
    op.drop_index("ix_notifications_entry_id", table_name="notifications")
    op.drop_index("ix_notifications_user_id", table_name="notifications")
    op.drop_table("notifications")
