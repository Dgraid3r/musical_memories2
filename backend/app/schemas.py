from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class EntryImageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    filename: str


class UserPublic(BaseModel):
    """Minimal, shareable user info - no email. Used anywhere one user is
    shown to another (co-author search results, entry authorship)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str


class TagOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str


class JournalEntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    owner_username: str
    coauthors: list[UserPublic]
    start_date: date
    end_date: date
    text: str | None
    is_public: bool
    playlist_id: str
    playlist_name: str
    playlist_url: str
    playlist_image_url: str | None
    created_at: datetime
    images: list[EntryImageOut]
    tags: list[TagOut]


class JournalEntryUpdate(BaseModel):
    text: str | None = None
    is_public: bool | None = None
    # None = leave co-authors unchanged; [] = clear them; only the primary
    # author is allowed to set this (enforced in the router, not here).
    coauthor_usernames: list[str] | None = None
    # None = leave tags unchanged; [] = clear them. Any co-author may set
    # this (tags are content, like text), unlike coauthor_usernames.
    tags: list[str] | None = None


class PlaylistResult(BaseModel):
    id: str
    name: str
    url: str
    image_url: str | None
    owner: str
    track_count: int


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=50, pattern=r"^[a-zA-Z0-9_.-]+$")
    email: EmailStr
    password: str = Field(min_length=8, max_length=256)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    email: str
    created_at: datetime


class LoginInput(BaseModel):
    username: str
    password: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


class SpotifyStatusOut(BaseModel):
    """Whether the caller has linked a Spotify account. Never includes the
    stored tokens themselves - those are secrets and never leave the server."""

    connected: bool


class SpotifyConnectOut(BaseModel):
    authorize_url: str
