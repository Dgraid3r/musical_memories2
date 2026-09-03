"""Add tags and full-text search on journal entries

Adds a normalized tags + entry_tags join table (enables listing all tags in
use and filtering by tag), plus a Postgres-native tsvector search_vector
column on journal_entries kept in sync by triggers from that entry's text
and tag names, with a GIN index for fast `@@` queries.

The trigger/function SQL is imported from app.models so the migration and
`Base.metadata.create_all()` (used by the test suite) can never drift apart.

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-02

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import TSVECTOR

from app.models import SEARCH_VECTOR_FUNCTIONS_SQL, SEARCH_VECTOR_TRIGGERS_SQL

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "tags",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
    )
    op.create_index("ix_tags_name", "tags", ["name"], unique=True)

    op.create_table(
        "entry_tags",
        sa.Column("entry_id", sa.Integer(), sa.ForeignKey("journal_entries.id"), primary_key=True),
        sa.Column("tag_id", sa.Integer(), sa.ForeignKey("tags.id"), primary_key=True),
    )

    op.add_column("journal_entries", sa.Column("search_vector", TSVECTOR(), nullable=True))
    op.create_index(
        "ix_journal_entries_search_vector",
        "journal_entries",
        ["search_vector"],
        postgresql_using="gin",
    )

    op.execute(SEARCH_VECTOR_FUNCTIONS_SQL)
    op.execute(SEARCH_VECTOR_TRIGGERS_SQL)

    # Backfill: populate search_vector for any rows that already exist.
    op.execute(
        "UPDATE journal_entries SET search_vector = "
        "setweight(to_tsvector('english', coalesce((SELECT string_agg(t.name, ' ') "
        "FROM entry_tags et JOIN tags t ON t.id = et.tag_id WHERE et.entry_id = journal_entries.id), '')), 'A') "
        "|| setweight(to_tsvector('english', coalesce(text, '')), 'B')"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS entry_tags_search_vector_update ON entry_tags")
    op.execute("DROP TRIGGER IF EXISTS journal_entries_search_vector_update ON journal_entries")
    op.execute("DROP FUNCTION IF EXISTS trg_entry_tags_search_vector()")
    op.execute("DROP FUNCTION IF EXISTS trg_journal_entries_search_vector()")
    op.execute("DROP FUNCTION IF EXISTS update_entry_search_vector(INTEGER)")

    op.drop_index("ix_journal_entries_search_vector", table_name="journal_entries")
    op.drop_column("journal_entries", "search_vector")

    op.drop_table("entry_tags")
    op.drop_index("ix_tags_name", table_name="tags")
    op.drop_table("tags")
