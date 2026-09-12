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
    # All three null together - an offline-created draft (see the PWA
    # offline-drafts feature) syncs with no playlist at all, since
    # picking one needs Spotify search, which needs a connection the
    # draft didn't have when it was captured. Addable afterward via
    # JournalEntryUpdate.playlist below.
    playlist_id: str | None
    playlist_name: str | None
    playlist_url: str | None
    playlist_image_url: str | None
    created_at: datetime
    images: list[EntryImageOut]
    tags: list[TagOut]
    # All three null together (no location set) or all three set together -
    # never a partial location. See models.JournalEntry's location columns
    # and EntryLocationInput below.
    latitude: float | None
    longitude: float | None
    location_name: str | None
    # Whether a public single-entry share link currently exists -
    # deliberately never the actual share_token itself (see models.
    # JournalEntry.share_token's comment on why): anyone who can view this
    # entry can see *that* it's shared, but only the primary author can
    # learn or distribute the real link, via the dedicated share/unshare
    # endpoints below.
    is_shared: bool


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


class EntryLocationInput(BaseModel):
    """A location is always set or cleared as a whole, never partially -
    latitude/longitude alone would be meaningless without the display name
    the user actually searched for and picked."""

    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    location_name: str = Field(min_length=1, max_length=255)


class EntryPlaylistInput(BaseModel):
    """Only ever used to *set* a playlist (see JournalEntryUpdate.playlist
    below) - never to clear one back to nothing, unlike location, since
    there's no real-world reason to remove an entry's playlist once it
    has one. Mirrors exactly what's actually persisted on JournalEntry -
    not schemas.PlaylistResult, which also carries owner/track_count
    that this entry never stores."""

    playlist_id: str = Field(min_length=1)
    playlist_name: str = Field(min_length=1)
    playlist_url: str = Field(min_length=1)
    playlist_image_url: str | None = None


class JournalEntryUpdate(BaseModel):
    text: str | None = None
    is_public: bool | None = None
    # None = leave co-authors unchanged; [] = clear them; only the primary
    # author is allowed to set this (enforced in the router, not here).
    coauthor_usernames: list[str] | None = None
    # None = leave tags unchanged; [] = clear them. Any co-author may set
    # this (tags are content, like text), unlike coauthor_usernames.
    tags: list[str] | None = None
    # Unlike the fields above, this field's *value* alone can't distinguish
    # "the client didn't mention location" from "the client explicitly
    # wants it cleared" - both look like `None`. The router instead checks
    # `"location" in payload.model_fields_set`: absent entirely = leave
    # unchanged, present as JSON null = clear, present as an object = set.
    location: EntryLocationInput | None = None
    # Sets (never clears - see EntryPlaylistInput) the playlist on an
    # entry that doesn't have one yet, most notably an offline-created
    # draft once it's synced. Content, like text/tags - any co-author
    # with content-edit rights may set this, not just the primary author.
    playlist: EntryPlaylistInput | None = None


class EntryShareOut(BaseModel):
    """Returned only from POST .../entries/{id}/share, to the primary
    author who just called it - the one place the actual share_token
    value is ever handed out (see JournalEntryOut.is_shared above, which
    deliberately never includes it)."""

    share_token: str


class SharedEntryOut(BaseModel):
    """The public, unauthenticated single-entry view (GET
    /api/shared/{token}) - deliberately minimal and separate from
    JournalEntryOut: no id, no workspace_id, no owner/co-author identity,
    nothing that would let a viewer learn anything about the workspace
    this entry lives in or who else is in it. Just the memory itself:
    text, date(s), tags, location, and the linked playlist."""

    model_config = ConfigDict(from_attributes=True)

    start_date: date
    end_date: date
    text: str | None
    playlist_id: str | None
    playlist_name: str | None
    playlist_url: str | None
    playlist_image_url: str | None
    latitude: float | None
    longitude: float | None
    location_name: str | None
    tags: list[TagOut]
    images: list[EntryImageOut]


class PlaceResult(BaseModel):
    """What the frontend needs from a place search result - never
    Nominatim's full raw response (see nominatim_client.py)."""

    display_name: str
    latitude: float
    longitude: float


class ReverseGeocodeResult(BaseModel):
    """What GET /api/places/reverse returns for a set of coordinates -
    just the place name, same "never Nominatim's raw response" rule as
    PlaceResult above."""

    display_name: str


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
    # Exposed here (unlike is_active, which a logged-in caller never
    # needs to see about themselves) so the frontend can gate the admin
    # dashboard nav link off the current user's own attributes, the same
    # AuthContext-driven pattern used everywhere else in the frontend -
    # see AuthContext.tsx/App.tsx.
    is_admin: bool


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


class GoogleSignInConfigOut(BaseModel):
    """Whether "Sign in with Google" is available at all - opt-in like
    every other external integration in this app (Spotify, Sentry, SMTP,
    object storage). No auth required to check this - it has to be
    readable before anyone can be logged in, unlike SpotifyStatusOut
    above, which is about an already-authenticated user's own account."""

    enabled: bool


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


class MyPendingInviteOut(BaseModel):
    """One row of GET /api/invites - every invite currently pending for
    the *caller's own* email, so a logged-in user has somewhere to see
    (and act on) an invite beyond just the emailed link. Unlike
    WorkspaceInviteOut above (what a workspace owner sees for invites
    *they sent*, which deliberately never includes the token), this one
    does include it: the query behind this endpoint is already scoped to
    "invites addressed to my own authenticated account's email", so the
    token isn't protecting anything further here - the frontend needs it
    to call POST /api/invites/{token}/accept directly.

    Built manually in the router (workspace_name/inviter_username come
    from the invite's related Workspace/User rows, not columns on the
    WorkspaceInvite row itself) rather than via from_attributes."""

    token: str
    workspace_id: int
    workspace_name: str
    role: str
    inviter_username: str
    created_at: datetime
    expires_at: datetime


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


# --- Admin ------------------------------------------------------------------


class AdminUserOut(BaseModel):
    """One row of GET /api/admin/users. Reuses the exact same deleted-
    account username masking as UserPublic/owner_username/author_username
    above - a deleted account's real username never leaves the server
    here either. Its email is already the synthetic
    deleted-user-{id}@deleted.invalid placeholder from self-deletion's
    own PII scrub (see account.py) by the time this runs, so no separate
    email masking is needed on top of that."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    email: str
    created_at: datetime
    email_verified: bool
    is_admin: bool
    is_active: bool
    is_deleted: bool

    @model_validator(mode="before")
    @classmethod
    def _mask_deleted_username(cls, data: Any) -> Any:
        if getattr(data, "is_deleted", False):
            return {
                "id": data.id,
                "username": DELETED_USER_DISPLAY_NAME,
                "email": data.email,
                "created_at": data.created_at,
                "email_verified": data.email_verified,
                "is_admin": data.is_admin,
                "is_active": data.is_active,
                "is_deleted": True,
            }
        return data


class AdminUserActionOut(BaseModel):
    detail: str


class BackupStatusOut(BaseModel):
    """The most recent scripts/backup_database.py run - see models.
    BackupRun. None of this is shown anywhere but the admin stats panel."""

    started_at: datetime
    succeeded: bool
    error_message: str | None


class AdminStatsOut(BaseModel):
    """GET /api/admin/stats - operational visibility only, deliberately
    no content (no entry text, no workspace names) - see routers/admin.py
    module docstring for the explicit "not content moderation" scope
    boundary this whole router stays inside."""

    total_users: int
    total_workspaces: int
    total_entries: int
    new_signups_7d: int
    new_signups_30d: int
    database_healthy: bool
    # None means no backup has ever run yet (e.g. a brand new
    # deployment) - distinct from a run that happened and failed.
    latest_backup: BackupStatusOut | None


class NotificationOut(BaseModel):
    """One row of GET /api/notifications - see models.Notification for why
    this is deliberately generic (a `type` string plus a pre-rendered
    `message`) rather than one shape per notification kind. `entry_id`/
    `workspace_id` are None either when this notification's type never
    had one to begin with, or once the entry/workspace it pointed to was
    later deleted (ON DELETE SET NULL - see the model) - either way, the
    frontend just has nothing left to link to. `read_at` being None means
    unread, the same marker convention used everywhere else in this app."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    type: str
    message: str
    entry_id: int | None
    workspace_id: int | None
    read_at: datetime | None
    created_at: datetime


class NotificationActionOut(BaseModel):
    detail: str


class UnreadNotificationCountOut(BaseModel):
    """Powers the bell icon's unread badge - a plain count, so the
    frontend doesn't have to fetch every notification just to count how
    many are unread."""

    count: int
