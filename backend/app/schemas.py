from datetime import date, datetime

from pydantic import BaseModel, ConfigDict


class EntryImageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    filename: str


class JournalEntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    entry_date: date
    text: str | None
    playlist_id: str
    playlist_name: str
    playlist_url: str
    playlist_image_url: str | None
    created_at: datetime
    images: list[EntryImageOut]


class PlaylistResult(BaseModel):
    id: str
    name: str
    url: str
    image_url: str | None
    owner: str
    track_count: int
