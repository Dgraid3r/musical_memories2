"""Add users.deleted_at for account deletion (soft-delete/anonymization)

Self-deletion (see routers/account.py DELETE /api/account) never deletes a
User row - it anonymizes it in place and sets this timestamp. Null means
"not deleted", the same nullable-timestamp-as-marker pattern already used
by workspace_invites.revoked_at/accepted_at and password_reset_tokens.
used_at. Every existing user starts with deleted_at NULL, which is
correct - no existing account is affected by adding this column.

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-09

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("deleted_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "deleted_at")
