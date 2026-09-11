"""Add admin dashboard support: users.is_admin/is_active, backup_runs

- users.is_admin: site-wide admin flag, default false - every existing
  user starts as a non-admin, which is correct (see
  scripts/grant_admin.py for how the first admin is granted).
- users.is_active: reversible login-block flag, default true - every
  existing user starts active, unaffected by this migration.
- backup_runs: one row per scripts/backup_database.py attempt, written
  by that script itself (see its run() function).

Revision ID: 0012
Revises: 0011
Create Date: 2026-09-10

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0012"
down_revision: Union[str, None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users", sa.Column("is_admin", sa.Boolean(), nullable=False, server_default="false")
    )
    op.add_column(
        "users", sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true")
    )

    op.create_table(
        "backup_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("succeeded", sa.Boolean(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("backup_runs")
    op.drop_column("users", "is_active")
    op.drop_column("users", "is_admin")
