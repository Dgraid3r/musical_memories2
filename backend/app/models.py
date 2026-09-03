from datetime import date, datetime

from sqlalchemy import Boolean, Column, Date, DateTime, ForeignKey, Integer, String, Table, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base

entry_coauthors = Table(
    "entry_coauthors",
    Base.metadata,
    Column("entry_id", ForeignKey("journal_entries.id"), primary_key=True),
    Column("user_id", ForeignKey("users.id"), primary_key=True),
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
