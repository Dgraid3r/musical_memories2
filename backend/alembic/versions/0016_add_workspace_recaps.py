"""Add workspace_recaps for the per-workspace, per-year "wrapped" summary

New table, one row per workspace+year, get-or-created on first request
(see routers/workspaces.py's recap endpoints). Deliberately stores no
computed stats - those are always recomputed live from the workspace's
entries (see models.WorkspaceRecap's docstring) - just the share_token
(nullable, unique when set - same shareable-link pattern as
journal_entries.share_token) and bookkeeping.

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
    op.create_table(
        "workspace_recaps",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("share_token", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("workspace_id", "year", name="uq_workspace_recap_workspace_year"),
    )
    op.create_index("ix_workspace_recaps_workspace_id", "workspace_recaps", ["workspace_id"])
    op.create_index("ix_workspace_recaps_share_token", "workspace_recaps", ["share_token"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_workspace_recaps_share_token", table_name="workspace_recaps")
    op.drop_index("ix_workspace_recaps_workspace_id", table_name="workspace_recaps")
    op.drop_table("workspace_recaps")
