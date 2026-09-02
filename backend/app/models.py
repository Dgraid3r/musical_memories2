from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


class JournalEntry(Base):
    __tablename__ = "journal_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    entry_date: Mapped[date] = mapped_column(Date, nullable=False)
    text: Mapped[str | None] = mapped_column(Text, nullable=True)

    # The music side of an entry is always a Spotify playlist, even a
    # single-song one, so there is no separate "track" reference to model.
    playlist_id: Mapped[str] = mapped_column(String, nullable=False)
    playlist_name: Mapped[str] = mapped_column(String, nullable=False)
    playlist_url: Mapped[str] = mapped_column(String, nullable=False)
    playlist_image_url: Mapped[str | None] = mapped_column(String, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    images: Mapped[list["EntryImage"]] = relationship(
        back_populates="entry", cascade="all, delete-orphan", order_by="EntryImage.id"
    )


class EntryImage(Base):
    __tablename__ = "entry_images"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    entry_id: Mapped[int] = mapped_column(ForeignKey("journal_entries.id"), nullable=False)
    filename: Mapped[str] = mapped_column(String, nullable=False)

    entry: Mapped["JournalEntry"] = relationship(back_populates="images")
