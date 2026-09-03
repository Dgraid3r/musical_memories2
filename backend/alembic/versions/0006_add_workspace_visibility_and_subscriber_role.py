"""Add workspace visibility (public/private) and the subscriber role

`workspaces.visibility` defaults to "private" via server_default, so every
existing workspace becomes private automatically when this column is added
- nothing that was private today becomes publicly readable by surprise. No
separate backfill UPDATE is needed: Postgres applies a column's
server_default to already-existing rows when adding a NOT NULL column.

Also adds CHECK constraints on workspaces.visibility and
workspace_memberships.role for defensive data integrity - the existing
role values ("owner", "member") already satisfy the new constraint, since
"subscriber" is purely additive.

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-02

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "workspaces",
        sa.Column("visibility", sa.String(), nullable=False, server_default="private"),
    )
    op.create_check_constraint(
        "ck_workspaces_visibility", "workspaces", "visibility IN ('public', 'private')"
    )
    op.create_check_constraint(
        "ck_workspace_memberships_role",
        "workspace_memberships",
        "role IN ('owner', 'member', 'subscriber')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_workspace_memberships_role", "workspace_memberships", type_="check")
    op.drop_constraint("ck_workspaces_visibility", "workspaces", type_="check")
    op.drop_column("workspaces", "visibility")
