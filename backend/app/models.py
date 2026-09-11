from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    DDL,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
    event,
)
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .crypto import EncryptedString
from .database import Base

# Shown in place of a deleted account's real name anywhere the app renders
# authorship (entry owner/co-authors, comment authors) - see User.deleted_at
# and User.is_deleted. Deliberately a fixed, generic string rather than the
# scrubbed placeholder username actually stored on the row (e.g.
# "deleted-user-42"), which exists only to satisfy the unique constraint,
# not to be shown to anyone.
DELETED_USER_DISPLAY_NAME = "Deleted user"

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
    # Tracked, but never enforced against core app usage - a freshly
    # registered, unverified user can log in and use the app normally.
    # See EmailVerificationToken.
    email_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    # Set once, permanently, on self-deletion (see routers/account.py) - the
    # row itself is never deleted, so every entry/comment this user
    # authored keeps its real foreign key and survives untouched; only
    # this user's own identifying fields get scrubbed. Null means "not
    # deleted", the same nullable-timestamp-as-marker pattern already used
    # by WorkspaceInvite.revoked_at/accepted_at and
    # PasswordResetToken.used_at.
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Google's stable per-account identifier (the "sub" claim in their ID
    # token) - kept separate from email since email can theoretically
    # change on Google's side while sub never does. Null for a local-only
    # account (most accounts); unique only among non-null values, which
    # Postgres already gives a nullable unique index for free (multiple
    # NULLs are never considered duplicates of each other). See
    # routers/google_auth.py.
    google_sub: Mapped[str | None] = mapped_column(String, unique=True, nullable=True, index=True)

    entries: Mapped[list["JournalEntry"]] = relationship(
        back_populates="owner", cascade="all, delete-orphan"
    )
    spotify_token: Mapped["SpotifyToken | None"] = relationship(
        back_populates="user", cascade="all, delete-orphan", uselist=False
    )
    # A user can belong to several workspaces at once (a switcher, not a
    # single fixed group per account) - this is the join table that makes
    # that possible.
    memberships: Mapped[list["WorkspaceMembership"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    email_verification_token: Mapped["EmailVerificationToken | None"] = relationship(
        back_populates="user", cascade="all, delete-orphan", uselist=False
    )
    password_reset_tokens: Mapped[list["PasswordResetToken"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None


class Workspace(Base):
    """An isolated group - e.g. one family's journal vs. a friend group's.
    Entries and tags belong to exactly one workspace; a user can belong to
    several workspaces via WorkspaceMembership.

    `visibility` is owner-controlled and defaults to "private": a "public"
    workspace is discoverable via the public browse endpoint and its
    entries are readable by anyone, including fully anonymous requests,
    with no membership at all. A "private" workspace is invisible to that
    search and unreadable by anyone who isn't a member (any role)."""

    __tablename__ = "workspaces"
    __table_args__ = (CheckConstraint("visibility IN ('public', 'private')", name="ck_workspaces_visibility"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    visibility: Mapped[str] = mapped_column(String, nullable=False, default="private", server_default="private")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)

    creator: Mapped["User"] = relationship(foreign_keys=[created_by])
    memberships: Mapped[list["WorkspaceMembership"]] = relationship(
        back_populates="workspace", cascade="all, delete-orphan"
    )
    entries: Mapped[list["JournalEntry"]] = relationship(back_populates="workspace", cascade="all, delete-orphan")
    tags: Mapped[list["Tag"]] = relationship(back_populates="workspace", cascade="all, delete-orphan")
    invites: Mapped[list["WorkspaceInvite"]] = relationship(back_populates="workspace", cascade="all, delete-orphan")


class WorkspaceMembership(Base):
    """One user's membership in one workspace, with a role:
    - "owner" created the workspace and can invite/remove members, change
      a member's role, toggle public/private, and delete the workspace.
    - "member" can do everything else (create entries, comment, add
      co-authors, etc.) - the same power an entry co-author has over
      content, one level up.
    - "subscriber" is read-only: can read the workspace's entries and
      comments (same as a member would) but cannot create or edit
      anything - no entries, no photos, no comments, no co-authoring. This
      is how an owner grants view access to a *private* workspace without
      making someone a full collaborator; public workspaces don't need
      subscribers for reading (anyone can already read those), but nothing
      stops an owner from adding one there too, e.g. to track who's
      "following" it."""

    __tablename__ = "workspace_memberships"
    __table_args__ = (
        UniqueConstraint("workspace_id", "user_id", name="uq_workspace_membership"),
        CheckConstraint("role IN ('owner', 'member', 'subscriber')", name="ck_workspace_memberships_role"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id"), nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String, nullable=False, default="member")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    workspace: Mapped["Workspace"] = relationship(back_populates="memberships")
    user: Mapped["User"] = relationship(back_populates="memberships")


class WorkspaceInvite(Base):
    """A pending invitation to join a workspace, by email address rather
    than an existing username - the replacement for the old owner-adds-
    an-existing-user-by-username mechanism. Joining a workspace is now
    always consent-based: the invitee has to act (log in and accept, or
    register) before a WorkspaceMembership row is created; an owner can
    never unilaterally add someone.

    `token` is the unguessable, unique value emailed to the invitee - it's
    what /api/invites/{token} and /api/invites/{token}/accept look up by,
    and it's also what a new registration's `invite_token` field matches
    against when the invitee has no account yet."""

    __tablename__ = "workspace_invites"
    __table_args__ = (CheckConstraint("role IN ('member', 'subscriber')", name="ck_workspace_invites_role"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id"), nullable=False, index=True)
    email: Mapped[str] = mapped_column(String, nullable=False, index=True)
    role: Mapped[str] = mapped_column(String, nullable=False, default="member")
    token: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    invited_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    workspace: Mapped["Workspace"] = relationship(back_populates="invites")
    inviter: Mapped["User"] = relationship(foreign_keys=[invited_by])


class Tag(Base):
    __tablename__ = "tags"
    __table_args__ = (UniqueConstraint("workspace_id", "name", name="uq_tag_workspace_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id"), nullable=False, index=True)
    # Stored lowercase/trimmed so "Road Trip" and "road trip" collapse to one
    # tag; the router owns normalization on the way in. Unique per workspace
    # (not globally) - otherwise autocomplete would leak tag names across
    # unrelated workspaces, and two workspaces couldn't each have their own
    # "roadtrip" tag.
    name: Mapped[str] = mapped_column(String, nullable=False, index=True)

    workspace: Mapped["Workspace"] = relationship(back_populates="tags")
    entries: Mapped[list["JournalEntry"]] = relationship(secondary=entry_tags, back_populates="tags")


class JournalEntry(Base):
    __tablename__ = "journal_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspaces.id"), nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)

    # A single-day memory has start_date == end_date; the frontend collapses
    # that case to one displayed date instead of a range.
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)

    text: Mapped[str | None] = mapped_column(Text, nullable=True)
    # "Public" now means visible to every *member of this entry's
    # workspace*, not the whole app - workspaces are the isolation boundary,
    # and every route that can reach an entry already requires workspace
    # membership first. "Private" is unchanged: owner + co-authors only.
    is_public: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # The music side of an entry is always a Spotify playlist, even a
    # single-song one, so there is no separate "track" reference to model.
    playlist_id: Mapped[str] = mapped_column(String, nullable=False)
    playlist_name: Mapped[str] = mapped_column(String, nullable=False)
    playlist_url: Mapped[str] = mapped_column(String, nullable=False)
    playlist_image_url: Mapped[str | None] = mapped_column(String, nullable=True)

    # Optional, user-provided location - never inferred or captured
    # automatically (see routers/places.py's backend-proxied Nominatim
    # search, and the frontend's explicit "use my current location"
    # button, which only triggers the browser's geolocation prompt on a
    # click). The API treats all three as set-or-cleared together (see
    # schemas.EntryLocationInput), though the columns themselves are
    # independently nullable at the DB level.
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    location_name: Mapped[str | None] = mapped_column(String, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Maintained by Postgres triggers (see the DDL below) from `text` plus
    # this entry's tag names - never written from Python. Nullable because
    # the trigger populates it only after the row (and its tags) exist.
    search_vector: Mapped[str | None] = mapped_column(TSVECTOR, nullable=True)

    workspace: Mapped["Workspace"] = relationship(back_populates="entries")
    owner: Mapped["User"] = relationship(back_populates="entries")
    # Co-authors can edit an entry's content (text, photos) but only the
    # primary author (owner) can change visibility, manage co-authors, or
    # delete the entry. Co-authors must already be members of the entry's
    # workspace - enforced in the router, not here (see entries.py).
    coauthors: Mapped[list["User"]] = relationship(secondary=entry_coauthors)
    images: Mapped[list["EntryImage"]] = relationship(
        back_populates="entry", cascade="all, delete-orphan", order_by="EntryImage.id"
    )
    comments: Mapped[list["Comment"]] = relationship(
        back_populates="entry", cascade="all, delete-orphan", order_by="Comment.created_at"
    )
    tags: Mapped[list["Tag"]] = relationship(secondary=entry_tags, back_populates="entries", order_by="Tag.name")
    # Audit log only - who edited this entry and when, plus a short label
    # for what kind of edit it was. Deliberately not a version history: no
    # snapshot of the old/new content is stored anywhere, so there's no
    # diff or restore functionality built on this (see EntryEditEvent).
    edit_events: Mapped[list["EntryEditEvent"]] = relationship(
        back_populates="entry", cascade="all, delete-orphan", order_by="EntryEditEvent.edited_at.desc()"
    )

    @property
    def owner_username(self) -> str:
        return DELETED_USER_DISPLAY_NAME if self.owner.is_deleted else self.owner.username


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
        return DELETED_USER_DISPLAY_NAME if self.author.is_deleted else self.author.username


class EntryEditEvent(Base):
    """One row per edit made to an entry after creation - an audit log, not
    version history. There is deliberately no snapshot of the changed
    content here, just who changed something, when, and a short label for
    roughly what kind of field changed (e.g. "content", "tags",
    "visibility", "coauthors", "images") - enough to make the history more
    useful than a bare timestamp list, without doing actual diffing or
    supporting any restore/rollback. See entries.py update_entry/
    add_images for where these get recorded, and get_entry_edit_history for
    how they're read back."""

    __tablename__ = "entry_edit_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    entry_id: Mapped[int] = mapped_column(ForeignKey("journal_entries.id"), nullable=False, index=True)
    editor_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    edited_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    change_summary: Mapped[str] = mapped_column(String, nullable=False)

    entry: Mapped["JournalEntry"] = relationship(back_populates="edit_events")
    editor: Mapped["User"] = relationship()

    @property
    def editor_username(self) -> str:
        # Same DELETED_USER_DISPLAY_NAME masking as JournalEntry.
        # owner_username/Comment.author_username - reused, not
        # reimplemented, per an editor who has since deleted their account.
        return DELETED_USER_DISPLAY_NAME if self.editor.is_deleted else self.editor.username


class SpotifyToken(Base):
    """A user's linked Spotify account (Authorization Code flow), distinct
    from the app-only client-credentials client used for public catalog
    search. One row per user. Tokens are secrets - never serialize this
    model, or any field of it, into an API response."""

    __tablename__ = "spotify_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True, nullable=False, index=True)
    # Encrypted at rest (see crypto.EncryptedString) - these are someone's
    # real Spotify credentials. The column stays a plain string type in
    # Postgres; only the ciphertext is ever stored there.
    access_token: Mapped[str] = mapped_column(EncryptedString, nullable=False)
    refresh_token: Mapped[str] = mapped_column(EncryptedString, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    scope: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user: Mapped["User"] = relationship(back_populates="spotify_token")


class EmailVerificationToken(Base):
    """At most one live row per user - resending replaces the existing
    row's token/expiry rather than accumulating old ones. Deleted outright
    on successful verification, which both marks the flow complete and
    means a reused link naturally 404s afterward."""

    __tablename__ = "email_verification_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True, nullable=False, index=True)
    token: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    user: Mapped["User"] = relationship(back_populates="email_verification_token")


class PasswordResetToken(Base):
    """Unlike email verification, a user can have several of these rows at
    once (each password-reset request makes a new one) - but requesting a
    new reset marks every previous still-live token for that user as used,
    so only the most recently requested link is ever actually usable, the
    same "your old link stopped working because you asked for a new one"
    behavior most password-reset flows have."""

    __tablename__ = "password_reset_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    token: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    user: Mapped["User"] = relationship(back_populates="password_reset_tokens")


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
