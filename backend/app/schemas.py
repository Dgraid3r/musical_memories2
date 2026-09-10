from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator

from .models import DELETED_USER_DISPLAY_NAME


class EntryImageOut(BaseModel):
    """No filename - the frontend fetches an image's bytes through
    GET /api/entries/{entry_id}/images/{image_id} using id alone, and the
    stored filename is an internal storage-layer detail (see
    EntryImage.filename / app/storage.py) with no reason to leave the
    server."""

    model_config = ConfigDict(from_attributes=True)

    id: int


class UserPublic(BaseModel):
    """Minimal, shareable user info - no email. Used anywhere one user is
    shown to another (co-author search results, entry authorship).

    A deleted account's real username never leaves the server via this
    schema - display_username is masked to DELETED_USER_DISPLAY_NAME
    before the normal from_attributes field mapping runs, the same
    outcome JournalEntry.owner_username/Comment.author_username already
    give for those two properties directly."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str

    @model_validator(mode="before")
    @classmethod
    def _mask_deleted_username(cls, data: Any) -> Any:
        if getattr(data, "is_deleted", False):
            return {"id": data.id, "username": DELETED_USER_DISPLAY_NAME}
        return data


class TagOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str


class JournalEntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    workspace_id: int
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


class EntryEditEventOut(BaseModel):
    """One row of an entry's audit log - who edited it, when, and a short
    label for what kind of field changed. No old/new value, no diff - this
    is intentionally audit-log-only, not version history."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    editor_user_id: int
    editor_username: str
    edited_at: datetime
    change_summary: str


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
    # Set when registering from a "join this workspace" invite link whose
    # email had no existing account. If it matches a still-pending invite
    # for this same email, registration also creates that workspace
    # membership - one flow, not a separate step the new user has to
    # remember to go back and do. Silently ignored (registration still
    # succeeds) if the token is missing, expired, already used, or for a
    # different email - a broken invite link must never block someone
    # from creating an account.
    invite_token: str | None = None


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    email: str
    email_verified: bool
    created_at: datetime


class LoginInput(BaseModel):
    username: str
    password: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


class CommentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    entry_id: int
    author_id: int
    author_username: str
    parent_comment_id: int | None
    body: str
    created_at: datetime
    edited_at: datetime | None
    # Populated straight from the ORM's own `replies` relationship (already
    # ordered by created_at), so the tree Pydantic serializes here matches
    # the tree structure in the database - no separate tree-building step.
    replies: list["CommentOut"] = []


CommentOut.model_rebuild()


class CommentCreate(BaseModel):
    body: str = Field(min_length=1, max_length=2000)
    # None = a top-level comment on the entry; otherwise a reply to another
    # comment (which may itself be a reply).
    parent_comment_id: int | None = None


class CommentUpdate(BaseModel):
    body: str = Field(min_length=1, max_length=2000)


class SpotifyStatusOut(BaseModel):
    """Whether the caller has linked a Spotify account. Never includes the
    stored tokens themselves - those are secrets and never leave the server."""

    connected: bool


class SpotifyConnectOut(BaseModel):
    authorize_url: str


class WorkspaceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class WorkspaceOut(BaseModel):
    id: int
    name: str
    visibility: Literal["public", "private"]
    created_at: datetime
    created_by: int
    # The caller's own role in this workspace - not a Workspace column, so
    # this model is always constructed explicitly rather than via
    # from_attributes off the ORM object alone.
    role: str


class PublicWorkspaceOut(BaseModel):
    """Just enough to identify/browse to a public workspace from the
    discovery endpoint - never entry content, and never anything about a
    caller's own role (the discovery endpoint needs no auth at all, so
    there may not even be a caller). entry_count and last_active_at are
    aggregates only (how much/how recent), never anything about what's
    actually in an entry - constructed explicitly by the router rather
    than via from_attributes, since neither is a real Workspace column."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    created_at: datetime
    entry_count: int
    # The most recent JournalEntry.created_at across every entry in this
    # workspace (public or private - this is an activity signal, not a
    # content disclosure), or the workspace's own created_at if it has no
    # entries yet. Same value the "active" sort ranks by.
    last_active_at: datetime


class WorkspaceVisibilityUpdate(BaseModel):
    visibility: Literal["public", "private"]


class WorkspaceMemberOut(BaseModel):
    user_id: int
    username: str
    role: str


class WorkspaceMemberRoleUpdate(BaseModel):
    # Deliberately excludes "owner" - promoting a member all the way to
    # owner goes through the dedicated transfer-ownership endpoint below
    # instead, which also demotes the previous owner atomically so a
    # workspace never ends up with zero or two owners.
    role: Literal["member", "subscriber"]


class WorkspaceTransferOwnershipInput(BaseModel):
    new_owner_user_id: int


class WorkspaceInviteCreate(BaseModel):
    email: EmailStr
    role: Literal["member", "subscriber"] = "member"


class WorkspaceInviteOut(BaseModel):
    """Never includes the token itself - that only ever leaves the server
    inside the emailed link, the same way a Spotify token never leaves the
    server in a response body."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    role: str
    created_at: datetime
    expires_at: datetime


class WorkspaceInvitePreviewOut(BaseModel):
    """What GET /api/invites/{token} shows before the invitee has logged in
    or registered - enough to render "You've been invited to join X as a
    <role>" and to decide whether to show a login form or a registration
    form."""

    workspace_id: int
    workspace_name: str
    email: str
    role: str
    expires_at: datetime
    account_exists: bool


class EmailVerificationResendOut(BaseModel):
    detail: str


class PasswordResetRequestInput(BaseModel):
    email: EmailStr


class PasswordResetRequestOut(BaseModel):
    """Always the same message whether or not the email belongs to an
    account - see PasswordResetRequestInput's router for why."""

    detail: str


class PasswordResetConfirmInput(BaseModel):
    new_password: str = Field(min_length=8, max_length=256)


class AccountDeleteInput(BaseModel):
    """Requires the caller's current password even though they're already
    authenticated - re-proves it's really them before an irreversible
    action, the same reasoning a password change would use if this app
    had one."""

    password: str


class AccountDeleteOut(BaseModel):
    detail: str
