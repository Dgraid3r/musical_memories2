from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    DDL,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
    Text,
    event,
)
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base

entry_coauthors = Table(
    "entry_coauthors",
    Base.metadata,
    Column("entry_id", ForeignKey("journal_entries.id"), primary_key=True),
    Column("user_id", ForeignKey("users.id"), primary_key=True),
)

entry_tags = Table(
    "entry_tags",
    Base.metadata,
    Column("entry_id", ForeignKey("journal_entries.id"), primary_key=True),
    Column("tag_id", ForeignKey("tags.id"), primary_key=True),
)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    email: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    hashed_password: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    entries: Mapped[list["JournalEntry"]] = relationship(
        back_populates="owner", cascade="all, delete-orphan"
    )
    spotify_token: Mapped["SpotifyToken | None"] = relationship(
        back_populates="user", cascade="all, delete-orphan", uselist=False
    )


class Tag(Base):
    __tablename__ = "tags"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Stored lowercase/trimmed so "Road Trip" and "road trip" collapse to one
    # tag; the router owns normalization on the way in.
    name: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)

    entries: Mapped[list["JournalEntry"]] = relationship(secondary=entry_tags, back_populates="tags")


class JournalEntry(Base):
    __tablename__ = "journal_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)

    # A single-day memory has start_date == end_date; the frontend collapses
    # that case to one displayed date instead of a range.
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)

    text: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_public: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # The music side of an entry is always a Spotify playlist, even a
    # single-song one, so there is no separate "track" reference to model.
    playlist_id: Mapped[str] = mapped_column(String, nullable=False)
    playlist_name: Mapped[str] = mapped_column(String, nullable=False)
    playlist_url: Mapped[str] = mapped_column(String, nullable=False)
    playlist_image_url: Mapped[str | None] = mapped_column(String, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Maintained by Postgres triggers (see the DDL below) from `text` plus
    # this entry's tag names - never written from Python. Nullable because
    # the trigger populates it only after the row (and its tags) exist.
    search_vector: Mapped[str | None] = mapped_column(TSVECTOR, nullable=True)

    owner: Mapped["User"] = relationship(back_populates="entries")
    # Co-authors can edit an entry's content (text, photos) but only the
    # primary author (owner) can change visibility, manage co-authors, or
    # delete the entry.
    coauthors: Mapped[list["User"]] = relationship(secondary=entry_coauthors)
    images: Mapped[list["EntryImage"]] = relationship(
        back_populates="entry", cascade="all, delete-orphan", order_by="EntryImage.id"
    )
    comments: Mapped[list["Comment"]] = relationship(
        back_populates="entry", cascade="all, delete-orphan", order_by="Comment.created_at"
    )
    tags: Mapped[list["Tag"]] = relationship(secondary=entry_tags, back_populates="entries", order_by="Tag.name")

    @property
    def owner_username(self) -> str:
        return self.owner.username


class EntryImage(Base):
    __tablename__ = "entry_images"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    entry_id: Mapped[int] = mapped_column(ForeignKey("journal_entries.id"), nullable=False)
    filename: Mapped[str] = mapped_column(String, nullable=False)

    entry: Mapped["JournalEntry"] = relationship(back_populates="images")


class Comment(Base):
    """A threaded comment on an entry. `parent_comment_id` is what makes it
    threaded - a null parent is a top-level comment on the entry, a non-null
    parent is a reply to another comment (which may itself be a reply, so
    threads can nest arbitrarily deep). `entry_id` is denormalized onto
    every comment, top-level or reply, so the whole thread for an entry can
    be fetched with a single flat query."""

    __tablename__ = "comments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    entry_id: Mapped[int] = mapped_column(ForeignKey("journal_entries.id"), nullable=False, index=True)
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    parent_comment_id: Mapped[int | None] = mapped_column(ForeignKey("comments.id"), nullable=True, index=True)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    edited_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    entry: Mapped["JournalEntry"] = relationship(back_populates="comments")
    author: Mapped["User"] = relationship()
    parent: Mapped["Comment | None"] = relationship(back_populates="replies", remote_side=[id])
    # Deleting a comment deletes its whole reply subtree with it, same as
    # deleting an entry deletes all of its comments.
    replies: Mapped[list["Comment"]] = relationship(
        back_populates="parent", cascade="all, delete-orphan", order_by="Comment.created_at"
    )

    @property
    def author_username(self) -> str:
        return self.author.username


class SpotifyToken(Base):
    """A user's linked Spotify account (Authorization Code flow), distinct
    from the app-only client-credentials client used for public catalog
    search. One row per user. Tokens are secrets - never serialize this
    model, or any field of it, into an API response."""

    __tablename__ = "spotify_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True, nullable=False, index=True)
    access_token: Mapped[str] = mapped_column(String, nullable=False)
    refresh_token: Mapped[str] = mapped_column(String, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    scope: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user: Mapped["User"] = relationship(back_populates="spotify_token")


# --- Full-text search -------------------------------------------------------
#
# journal_entries.search_vector is a Postgres tsvector kept in sync by
# triggers (not by SQLAlchemy) from that entry's `text` plus its tag names,
# weighted so tag matches rank above body-text matches. The GIN index below
# is what makes `search_vector @@ websearch_to_tsquery(...)` fast.
#
# These DDL statements are registered on Base.metadata's "after_create" event
# so both `Base.metadata.create_all()` (used by the test suite) and the
# Alembic migration (used everywhere else) end up with the identical
# functions/triggers - the migration executes this same SQL rather than a
# hand-duplicated copy. See alembic/versions for the migration that adds this
# to an existing database.

SEARCH_VECTOR_FUNCTIONS_SQL = """
CREATE OR REPLACE FUNCTION update_entry_search_vector(p_entry_id INTEGER) RETURNS VOID AS $$
    UPDATE journal_entries
    SET search_vector =
        setweight(to_tsvector('english', coalesce((
            SELECT string_agg(t.name, ' ')
            FROM entry_tags et JOIN tags t ON t.id = et.tag_id
            WHERE et.entry_id = p_entry_id
        ), '')), 'A')
        || setweight(to_tsvector('english', coalesce((
            SELECT text FROM journal_entries WHERE id = p_entry_id
        ), '')), 'B')
    WHERE id = p_entry_id;
$$ LANGUAGE sql;

CREATE OR REPLACE FUNCTION trg_journal_entries_search_vector() RETURNS TRIGGER AS $$
BEGIN
    PERFORM update_entry_search_vector(NEW.id);
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION trg_entry_tags_search_vector() RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        PERFORM update_entry_search_vector(OLD.entry_id);
        RETURN OLD;
    ELSE
        PERFORM update_entry_search_vector(NEW.entry_id);
        RETURN NEW;
    END IF;
END;
$$ LANGUAGE plpgsql;
"""

SEARCH_VECTOR_TRIGGERS_SQL = """
DROP TRIGGER IF EXISTS journal_entries_search_vector_update ON journal_entries;
CREATE TRIGGER journal_entries_search_vector_update
    AFTER INSERT OR UPDATE OF text ON journal_entries
    FOR EACH ROW EXECUTE FUNCTION trg_journal_entries_search_vector();

DROP TRIGGER IF EXISTS entry_tags_search_vector_update ON entry_tags;
CREATE TRIGGER entry_tags_search_vector_update
    AFTER INSERT OR DELETE ON entry_tags
    FOR EACH ROW EXECUTE FUNCTION trg_entry_tags_search_vector();
"""

Index("ix_journal_entries_search_vector", JournalEntry.search_vector, postgresql_using="gin")

event.listen(Base.metadata, "after_create", DDL(SEARCH_VECTOR_FUNCTIONS_SQL))
event.listen(Base.metadata, "after_create", DDL(SEARCH_VECTOR_TRIGGERS_SQL))
