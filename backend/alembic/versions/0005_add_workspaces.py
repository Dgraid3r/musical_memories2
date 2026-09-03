"""Add workspaces (multi-tenant isolation) and backfill existing data

Introduces Workspace and WorkspaceMembership (role: owner/member - the same
owner/member asymmetry as an entry's primary author vs. co-authors), adds a
required workspace_id to journal_entries, and makes tags unique per
workspace instead of globally unique (adds workspace_id + a composite
unique constraint, drops the old global-unique name index).

Existing-data backfill: creates one "Default" workspace, adds every
existing user as a member of it (the earliest-registered user as its
owner, everyone else as a member - an arbitrary but reasonable choice,
since there is no prior signal for who "should" own it), and backfills
workspace_id onto every existing entry and tag. A pre-existing public
entry keeps exactly the visibility it effectively had before: "public"
now means "visible to every member of the entry's workspace," and every
existing user becomes a member of the one workspace that now holds every
pre-existing entry, so nothing changes for anyone who already had access.
If there are no users yet (a fresh database), this step is skipped
entirely - there is nothing to backfill, and no valid `created_by` to use.

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-02

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "workspaces",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
    )

    op.create_table(
        "workspace_memberships",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("role", sa.String(), nullable=False, server_default="member"),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_workspace_memberships_workspace_id", "workspace_memberships", ["workspace_id"])
    op.create_index("ix_workspace_memberships_user_id", "workspace_memberships", ["user_id"])
    op.create_unique_constraint(
        "uq_workspace_membership", "workspace_memberships", ["workspace_id", "user_id"]
    )

    # workspace_id starts nullable on both tables so it can be backfilled
    # below, then gets tightened to NOT NULL once every existing row has one.
    op.add_column(
        "journal_entries", sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("workspaces.id"), nullable=True)
    )
    op.add_column("tags", sa.Column("workspace_id", sa.Integer(), sa.ForeignKey("workspaces.id"), nullable=True))

    conn = op.get_bind()
    first_user = conn.execute(sa.text("SELECT id FROM users ORDER BY created_at ASC, id ASC LIMIT 1")).fetchone()

    if first_user is not None:
        owner_id = first_user[0]
        workspace_id = conn.execute(
            sa.text(
                "INSERT INTO workspaces (name, created_at, created_by) "
                "VALUES ('Default', now(), :owner_id) RETURNING id"
            ),
            {"owner_id": owner_id},
        ).scalar_one()

        conn.execute(
            sa.text(
                "INSERT INTO workspace_memberships (workspace_id, user_id, role, created_at) "
                "SELECT :workspace_id, id, CASE WHEN id = :owner_id THEN 'owner' ELSE 'member' END, now() "
                "FROM users"
            ),
            {"workspace_id": workspace_id, "owner_id": owner_id},
        )

        conn.execute(
            sa.text("UPDATE journal_entries SET workspace_id = :workspace_id"), {"workspace_id": workspace_id}
        )
        conn.execute(sa.text("UPDATE tags SET workspace_id = :workspace_id"), {"workspace_id": workspace_id})

    op.alter_column("journal_entries", "workspace_id", nullable=False)
    op.create_index("ix_journal_entries_workspace_id", "journal_entries", ["workspace_id"])

    op.alter_column("tags", "workspace_id", nullable=False)
    op.create_index("ix_tags_workspace_id", "tags", ["workspace_id"])

    # Tags move from globally-unique names to unique-per-workspace: two
    # different workspaces can now each have their own "roadtrip" tag.
    op.drop_index("ix_tags_name", table_name="tags")
    op.create_index("ix_tags_name", "tags", ["name"])
    op.create_unique_constraint("uq_tag_workspace_name", "tags", ["workspace_id", "name"])


def downgrade() -> None:
    op.drop_constraint("uq_tag_workspace_name", "tags", type_="unique")
    op.drop_index("ix_tags_name", table_name="tags")
    op.create_index("ix_tags_name", "tags", ["name"], unique=True)
    op.drop_index("ix_tags_workspace_id", table_name="tags")
    op.drop_column("tags", "workspace_id")

    op.drop_index("ix_journal_entries_workspace_id", table_name="journal_entries")
    op.drop_column("journal_entries", "workspace_id")

    op.drop_constraint("uq_workspace_membership", "workspace_memberships", type_="unique")
    op.drop_index("ix_workspace_memberships_user_id", table_name="workspace_memberships")
    op.drop_index("ix_workspace_memberships_workspace_id", table_name="workspace_memberships")
    op.drop_table("workspace_memberships")

    op.drop_table("workspaces")
