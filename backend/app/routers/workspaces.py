import calendar
import logging
import os
import secrets
from collections import Counter
from datetime import datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import extract, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from ..auth import get_current_user, get_current_user_optional
from ..database import get_db
from ..email import send_email
from ..models import JournalEntry, Notification, User, Workspace, WorkspaceInvite, WorkspaceMembership, WorkspaceRecap
from ..schemas import (
    PublicWorkspaceOut,
    RecapEntryHighlight,
    RecapPlaylistCount,
    RecapShareOut,
    RecapTagCount,
    UserPublic,
    WorkspaceCreate,
    WorkspaceInviteCreate,
    WorkspaceInviteOut,
    WorkspaceMemberOut,
    WorkspaceMemberRoleUpdate,
    WorkspaceOut,
    WorkspaceRecapOut,
    WorkspaceTransferOwnershipInput,
    WorkspaceVisibilityUpdate,
)
from ..storage import get_storage

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/workspaces", tags=["workspaces"])


def collect_workspace_image_filenames(workspace: Workspace) -> list[str]:
    """Every stored image filename across every entry in this workspace -
    must be read *before* the workspace (and, through the ORM's own
    cascade="all, delete-orphan" relationships in models.py, every
    entry/image row in it) is deleted, since there's nothing left to
    traverse afterward. The ORM cascade only ever removes database rows;
    it never touches the actual files those EntryImage rows pointed at,
    so without this, every photo belonging to every entry in a deleted
    workspace (or a cascaded sole-owned-workspace account deletion - see
    account.delete_account) would stay orphaned in storage forever -
    unreferenced, and still billed for if using object storage.

    Used by delete_workspace below and by account.delete_account's
    sole-owned-workspace cascade - the one shared helper both call
    instead of duplicating this loop."""
    return [image.filename for entry in workspace.entries for image in entry.images]


def delete_stored_images(filenames: list[str]) -> None:
    """Deletes each given file from whichever storage backend is
    configured, logging (never raising) any individual failure.

    Every caller runs this only *after* the corresponding database
    delete has already committed successfully (see delete_workspace
    below, entries.delete_entry, and account.delete_account) - by that
    point the row is correctly gone either way, so a failure here means
    an orphaned file: the lesser, more visible problem, and one an
    admin can notice and clean up from the logs. The alternative
    ordering (delete files first, then commit the database delete) risks
    the opposite and strictly worse failure: real files deleted while
    the database rows - and whatever redirected a user to "this worked" -
    still exist, because the commit that was supposed to follow never
    happened."""
    storage = get_storage()
    for filename in filenames:
        try:
            storage.delete(filename)
        except Exception:
            logger.error("storage.delete_failed filename=%s", filename, exc_info=True)

WRITE_ROLES = ("owner", "member")
INVITE_EXPIRE_DAYS = 7

# No existing list endpoint in this codebase takes limit/offset as query
# params to match (entries.list_entries has no pagination at all yet, and
# users.search_users hardcodes .limit(10) with no param) - these defaults
# are a fresh, conventional choice: cap well below anything that could be
# used to scrape the whole public directory in one request.
PUBLIC_WORKSPACES_DEFAULT_LIMIT = 20
PUBLIC_WORKSPACES_MAX_LIMIT = 100


def _get_membership(workspace_id: int, current_user: User, db: Session) -> WorkspaceMembership | None:
    return db.scalar(
        select(WorkspaceMembership).where(
            WorkspaceMembership.workspace_id == workspace_id,
            WorkspaceMembership.user_id == current_user.id,
        )
    )


def require_workspace_member(workspace_id: int, db: Session, current_user: User) -> Workspace:
    """Any role (owner/member/subscriber), authenticated only - used where
    the resource isn't itself readable by the public-workspace bypass (e.g.
    the member roster). A workspace the caller holds no role in reads
    identically to one that doesn't exist - the same "never disclose"
    pattern already used for a private entry the caller can't see, which
    also reads as a 404 rather than a 403."""
    membership = _get_membership(workspace_id, current_user, db)
    if membership is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return membership.workspace


def require_workspace_read_access(workspace_id: int, db: Session, current_user: User | None) -> Workspace:
    """Read access to a workspace's entries/comments: the workspace is
    public (readable by anyone, including a fully anonymous caller, with no
    membership at all), OR the caller is authenticated and holds ANY role -
    owner, member, or subscriber - in it. A private workspace the caller
    can't read is indistinguishable from one that doesn't exist: 404, never
    401, extending the existing non-disclosure rule to the fully-anonymous
    case too - "no such workspace" and "exists but private" must read
    identically to someone with no token at all, not just to a logged-in
    non-member."""
    workspace = db.get(Workspace, workspace_id)
    if workspace is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    if workspace.visibility == "public":
        return workspace
    if current_user is not None and _get_membership(workspace_id, current_user, db) is not None:
        return workspace
    raise HTTPException(status_code=404, detail="Workspace not found")


def require_workspace_write_access(workspace_id: int, db: Session, current_user: User) -> Workspace:
    """Creating or editing content (entries, photos, comments, co-authors)
    requires an owner or member role. A subscriber gets 403 here - same as
    anyone else without write access - even though they can read everything
    a member can; this never runs for an unauthenticated caller, since
    every write route already requires get_current_user before reaching
    this point."""
    membership = _get_membership(workspace_id, current_user, db)
    if membership is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    if membership.role not in WRITE_ROLES:
        raise HTTPException(status_code=403, detail="You do not have permission to do this")
    return membership.workspace


def require_workspace_owner(workspace_id: int, db: Session, current_user: User) -> Workspace:
    membership = _get_membership(workspace_id, current_user, db)
    if membership is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    if membership.role != "owner":
        raise HTTPException(status_code=403, detail="Only the workspace owner can do this")
    return membership.workspace


def _frontend_url() -> str:
    return os.environ.get("FRONTEND_URL", "http://localhost:5173")


def _send_invite_email(invite: WorkspaceInvite, workspace: Workspace, inviter: User) -> None:
    link = f"{_frontend_url()}/?invite={invite.token}"
    body = (
        f"{inviter.username} has invited you to join the \"{workspace.name}\" workspace on "
        f"Musical Memories as a {invite.role}.\n\n"
        f"Accept the invite: {link}\n\n"
        f"This invite expires on {invite.expires_at.strftime('%Y-%m-%d')}."
    )
    send_email(invite.email, f"You're invited to join \"{workspace.name}\"", body, token=invite.token)


@router.get("/public", response_model=list[PublicWorkspaceOut])
def browse_public_workspaces(
    q: str | None = Query(None, min_length=1, description="Filter by name"),
    sort: Literal["active", "name"] = Query(
        "active", description="active = most recently active first (default); name = alphabetical"
    ),
    limit: int = Query(PUBLIC_WORKSPACES_DEFAULT_LIMIT, ge=1, le=PUBLIC_WORKSPACES_MAX_LIMIT),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """Discovery - no auth required, and deliberately returns just enough
    to identify and gauge a workspace (name, when it was created, how many
    entries it has, and when it was last active) - never entry content and
    never a private workspace.

    "Most recently active" is the latest JournalEntry.created_at across
    every entry in the workspace (public or private - a count/timestamp is
    an activity signal, not a content disclosure), falling back to the
    workspace's own created_at when it has no entries yet, so an empty
    workspace is never excluded - just ranked among the others by when it
    was created."""
    entry_stats = (
        select(
            JournalEntry.workspace_id.label("workspace_id"),
            func.count(JournalEntry.id).label("entry_count"),
            func.max(JournalEntry.created_at).label("last_entry_at"),
        )
        .group_by(JournalEntry.workspace_id)
        .subquery()
    )
    entry_count_expr = func.coalesce(entry_stats.c.entry_count, 0)
    last_active_expr = func.coalesce(entry_stats.c.last_entry_at, Workspace.created_at)

    stmt = (
        select(Workspace, entry_count_expr, last_active_expr)
        .outerjoin(entry_stats, entry_stats.c.workspace_id == Workspace.id)
        .where(Workspace.visibility == "public")
    )
    if q:
        stmt = stmt.where(Workspace.name.ilike(f"%{q}%"))

    if sort == "name":
        stmt = stmt.order_by(Workspace.name)
    else:
        # Tie-broken by id (desc) for a stable, deterministic order across
        # pages - two workspaces can otherwise share an identical
        # last_active_at (both empty, created in the same instant; or two
        # entries created in the same instant).
        stmt = stmt.order_by(last_active_expr.desc(), Workspace.id.desc())

    stmt = stmt.limit(limit).offset(offset)

    rows = db.execute(stmt).all()
    return [
        PublicWorkspaceOut(
            id=workspace.id,
            name=workspace.name,
            created_at=workspace.created_at,
            entry_count=entry_count,
            last_active_at=last_active_at,
        )
        for workspace, entry_count, last_active_at in rows
    ]


@router.post("", response_model=WorkspaceOut, status_code=201)
def create_workspace(
    payload: WorkspaceCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Any authenticated user can create a workspace; doing so makes them
    its owner. There is no cap on how many workspaces a user can create or
    belong to. Always starts private - the owner opts in to public
    visibility afterward via PATCH."""
    workspace = Workspace(name=payload.name, created_by=current_user.id)
    db.add(workspace)
    db.flush()
    db.add(WorkspaceMembership(workspace_id=workspace.id, user_id=current_user.id, role="owner"))
    db.commit()
    db.refresh(workspace)
    logger.info("workspace.created workspace_id=%s created_by=%s", workspace.id, current_user.id)
    return WorkspaceOut(
        id=workspace.id,
        name=workspace.name,
        visibility=workspace.visibility,
        created_at=workspace.created_at,
        created_by=workspace.created_by,
        role="owner",
    )


@router.get("", response_model=list[WorkspaceOut])
def list_my_workspaces(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Every workspace the caller belongs to - a user can be a member of
    several at once (a switcher, not a single fixed workspace per
    account)."""
    stmt = (
        select(Workspace, WorkspaceMembership.role)
        .join(WorkspaceMembership, WorkspaceMembership.workspace_id == Workspace.id)
        .where(WorkspaceMembership.user_id == current_user.id)
        .order_by(Workspace.created_at)
    )
    rows = db.execute(stmt).all()
    return [
        WorkspaceOut(
            id=w.id, name=w.name, visibility=w.visibility, created_at=w.created_at, created_by=w.created_by, role=role
        )
        for w, role in rows
    ]


@router.patch("/{workspace_id}", response_model=WorkspaceOut)
def update_workspace_visibility(
    workspace_id: int,
    payload: WorkspaceVisibilityUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Owner-only. Takes effect immediately - the very next read of this
    workspace (even from a caller with no token at all) reflects the new
    visibility, since read access is computed from the live column on every
    request rather than cached anywhere."""
    workspace = require_workspace_owner(workspace_id, db, current_user)
    workspace.visibility = payload.visibility
    db.commit()
    db.refresh(workspace)
    logger.info("workspace.visibility_changed workspace_id=%s visibility=%s by=%s", workspace_id, payload.visibility, current_user.id)
    return WorkspaceOut(
        id=workspace.id,
        name=workspace.name,
        visibility=workspace.visibility,
        created_at=workspace.created_at,
        created_by=workspace.created_by,
        role="owner",
    )


@router.get("/{workspace_id}/members", response_model=list[WorkspaceMemberOut])
def list_members(
    workspace_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_workspace_member(workspace_id, db, current_user)
    stmt = (
        select(WorkspaceMembership)
        .where(WorkspaceMembership.workspace_id == workspace_id)
        .order_by(WorkspaceMembership.created_at)
    )
    memberships = db.scalars(stmt).all()
    return [WorkspaceMemberOut(user_id=m.user_id, username=m.user.username, role=m.role) for m in memberships]


@router.post("/{workspace_id}/invites", response_model=WorkspaceInviteOut, status_code=201)
def create_invite(
    workspace_id: int,
    payload: WorkspaceInviteCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Owner-only. Joining a workspace is consent-based: this creates a
    pending invite and emails it - it does not add anyone to the
    workspace by itself. The invitee has to accept it (see
    routers/invites.py), either by logging into an existing account or by
    registering a new one with this same email."""
    workspace = require_workspace_owner(workspace_id, db, current_user)
    # Both lookups below use == (not ilike, which treats % and _ as SQL
    # wildcards an attacker-supplied email could exploit - see
    # account.py's password-reset request) against columns that are
    # themselves stored lowercase (User.email in users.register/
    # google_auth.callback; WorkspaceInvite.email a few lines below), so
    # normalizing just this incoming value is enough for an exact,
    # case-insensitive match.
    email = payload.email.lower()

    existing_user = db.scalar(select(User).where(User.email == email))
    if existing_user is not None and _get_membership(workspace_id, existing_user, db) is not None:
        raise HTTPException(status_code=409, detail="That person is already a member of this workspace")

    pending = db.scalar(
        select(WorkspaceInvite).where(
            WorkspaceInvite.workspace_id == workspace_id,
            WorkspaceInvite.email == email,
            WorkspaceInvite.accepted_at.is_(None),
            WorkspaceInvite.revoked_at.is_(None),
            WorkspaceInvite.expires_at > datetime.utcnow(),
        )
    )
    if pending is not None:
        raise HTTPException(status_code=409, detail="An invite is already pending for that email")

    invite = WorkspaceInvite(
        workspace_id=workspace_id,
        email=email,
        role=payload.role,
        token=secrets.token_urlsafe(32),
        invited_by=current_user.id,
        expires_at=datetime.utcnow() + timedelta(days=INVITE_EXPIRE_DAYS),
    )
    db.add(invite)
    # The invite email (below) always goes out regardless of whether this
    # email belongs to an existing account - that's the only notice a
    # brand-new invitee (no account yet) can get. An in-app Notification
    # is additionally created only when it does belong to an existing
    # account (existing_user, already looked up above) - a would-be
    # invitee with no account yet has nowhere to see an in-app
    # notification in the first place.
    if existing_user is not None:
        db.add(
            Notification(
                user_id=existing_user.id,
                type="invite",
                message=f'{current_user.username} invited you to join "{workspace.name}".',
                workspace_id=workspace_id,
            )
        )
    db.commit()
    db.refresh(invite)

    _send_invite_email(invite, workspace, current_user)
    logger.info("workspace.invite_created workspace_id=%s email=%r role=%s by=%s", workspace_id, email, payload.role, current_user.id)
    return invite


@router.get("/{workspace_id}/invites", response_model=list[WorkspaceInviteOut])
def list_invites(
    workspace_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Owner-only. Only ever shows invites that are still actually
    actionable - accepted or revoked ones drop off this list (the
    membership itself, or its absence, is the durable record at that
    point)."""
    require_workspace_owner(workspace_id, db, current_user)
    stmt = (
        select(WorkspaceInvite)
        .where(
            WorkspaceInvite.workspace_id == workspace_id,
            WorkspaceInvite.accepted_at.is_(None),
            WorkspaceInvite.revoked_at.is_(None),
        )
        .order_by(WorkspaceInvite.created_at.desc())
    )
    return db.scalars(stmt).all()


@router.delete("/{workspace_id}/invites/{invite_id}", status_code=204)
def revoke_invite(
    workspace_id: int,
    invite_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Owner-only. A revoked invite's token stops working immediately -
    see routers/invites.py's accept endpoint."""
    require_workspace_owner(workspace_id, db, current_user)
    invite = db.get(WorkspaceInvite, invite_id)
    if invite is None or invite.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="Invite not found")
    if invite.accepted_at is not None:
        raise HTTPException(status_code=409, detail="That invite has already been accepted")
    invite.revoked_at = datetime.utcnow()
    db.commit()
    logger.info("workspace.invite_revoked workspace_id=%s invite_id=%s by=%s", workspace_id, invite_id, current_user.id)


@router.patch("/{workspace_id}/transfer-ownership", response_model=WorkspaceOut)
def transfer_ownership(
    workspace_id: int,
    payload: WorkspaceTransferOwnershipInput,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Owner-only. Hands ownership to another existing member, atomically:
    the old owner's role becomes "member" and the target's becomes
    "owner" in the same transaction, so a workspace is never left without
    an owner (or with two). The target must already be a member - not a
    pending invite, not a stranger - since this is meant for already-
    trusted collaborators handing off control between themselves, unlike
    the invite flow. Unlike an invite, this takes effect immediately with
    no accept step from the new owner: both parties are already inside
    the workspace and this is a decision the current owner alone is
    trusted to make.

    Returns the *caller's* own WorkspaceOut (now role="member"), the same
    shape update_workspace_visibility returns - the frontend uses it to
    refresh its own view of this workspace without a second round trip.

    Locks the caller's own membership row (SELECT ... FOR UPDATE) before
    checking or changing anything, rather than using the plain
    require_workspace_owner/_get_membership helpers every other owner-only
    endpoint in this file uses unlocked. Nothing in the schema stops two
    "owner" rows existing in the same workspace at once, so without this,
    two near-simultaneous transfer requests from the same owner to two
    different targets could both pass an unlocked role check before
    either commits, and both succeed - leaving the workspace with two
    owners, contradicting this function's own "never with two" guarantee
    above. With the lock, the second request blocks until the first's
    transaction commits, then re-reads the row - now "member" - and
    correctly 403s instead of racing to also transfer ownership. A
    smaller, more surgical fix than a new partial unique index/migration,
    matching how narrow this race actually is: it needs the same owner
    racing against themselves, so only this one endpoint needs it."""
    current_owner_membership = db.scalar(
        select(WorkspaceMembership)
        .where(
            WorkspaceMembership.workspace_id == workspace_id,
            WorkspaceMembership.user_id == current_user.id,
        )
        .with_for_update()
    )
    if current_owner_membership is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    if current_owner_membership.role != "owner":
        raise HTTPException(status_code=403, detail="Only the workspace owner can do this")
    workspace = current_owner_membership.workspace

    if payload.new_owner_user_id == current_user.id:
        raise HTTPException(status_code=400, detail="You are already the owner of this workspace")

    target_membership = db.scalar(
        select(WorkspaceMembership).where(
            WorkspaceMembership.workspace_id == workspace_id,
            WorkspaceMembership.user_id == payload.new_owner_user_id,
        )
    )
    if target_membership is None:
        raise HTTPException(status_code=404, detail="That user is not a member of this workspace")

    current_owner_membership.role = "member"
    target_membership.role = "owner"
    db.commit()
    db.refresh(workspace)

    logger.warning(
        "workspace.ownership_transferred workspace_id=%s from_user_id=%s to_user_id=%s",
        workspace_id, current_user.id, payload.new_owner_user_id,
    )
    return WorkspaceOut(
        id=workspace.id,
        name=workspace.name,
        visibility=workspace.visibility,
        created_at=workspace.created_at,
        created_by=workspace.created_by,
        role="member",
    )


@router.patch("/{workspace_id}/members/{user_id}", response_model=WorkspaceMemberOut)
def update_member_role(
    workspace_id: int,
    user_id: int,
    payload: WorkspaceMemberRoleUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Owner-only. Sets a member to "member" (full read/write collaborator)
    or "subscriber" (read-only) - not "owner"; promoting a member all the
    way to owner goes through transfer_ownership above instead, which also
    demotes the previous owner atomically. The owner can't change their
    own role this way, for the same reason they can't remove themselves
    via the endpoint below: it would leave the workspace without an owner
    with no way to recover."""
    require_workspace_owner(workspace_id, db, current_user)

    if user_id == current_user.id:
        raise HTTPException(status_code=400, detail="The owner cannot change their own role")

    membership = db.scalar(
        select(WorkspaceMembership).where(
            WorkspaceMembership.workspace_id == workspace_id, WorkspaceMembership.user_id == user_id
        )
    )
    if membership is None:
        raise HTTPException(status_code=404, detail="That user is not a member of this workspace")

    membership.role = payload.role
    db.commit()
    logger.info(
        "workspace.member_role_changed workspace_id=%s user_id=%s role=%s by=%s",
        workspace_id, user_id, payload.role, current_user.id,
    )
    return WorkspaceMemberOut(user_id=membership.user_id, username=membership.user.username, role=membership.role)


@router.delete("/{workspace_id}/members/{user_id}", status_code=204)
def remove_member(
    workspace_id: int,
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Owner-only. The owner can't remove themselves this way - that would
    leave the workspace without an owner. Transfer ownership first (see
    transfer_ownership above) if someone else should take over, or delete
    the whole workspace if it should end entirely."""
    require_workspace_owner(workspace_id, db, current_user)

    if user_id == current_user.id:
        raise HTTPException(
            status_code=400, detail="The owner cannot remove themselves; delete the workspace instead"
        )

    membership = db.scalar(
        select(WorkspaceMembership).where(
            WorkspaceMembership.workspace_id == workspace_id, WorkspaceMembership.user_id == user_id
        )
    )
    if membership is None:
        raise HTTPException(status_code=404, detail="That user is not a member of this workspace")

    db.delete(membership)
    db.commit()
    logger.info("workspace.member_removed workspace_id=%s user_id=%s by=%s", workspace_id, user_id, current_user.id)


@router.delete("/{workspace_id}", status_code=204)
def delete_workspace(
    workspace_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Owner-only. Cascades to every entry, tag, comment, and pending
    invite in the workspace (see the cascade="all, delete-orphan"
    relationships in models.py) - this is genuinely destructive and
    irreversible. Every entry's stored photo files are explicitly
    deleted too (see collect_workspace_image_filenames/
    delete_stored_images above) - the ORM cascade alone would silently
    orphan them in storage forever, since it only ever removes database
    rows."""
    workspace = require_workspace_owner(workspace_id, db, current_user)
    image_filenames = collect_workspace_image_filenames(workspace)
    db.delete(workspace)
    db.commit()
    delete_stored_images(image_filenames)


# --- Yearly recap ("wrapped") -----------------------------------------

# A reasonable top N for tags/playlists - a "wrapped"-style summary is
# meant to be a handful of highlights, not a full frequency table.
RECAP_TOP_TAGS_LIMIT = 8
RECAP_TOP_PLAYLISTS_LIMIT = 5


def _get_or_create_recap(workspace_id: int, year: int, db: Session) -> WorkspaceRecap:
    """Get-or-create, matching entries._resolve_tags' own SAVEPOINT
    pattern for the same reason: two near-simultaneous first views of the
    same never-before-seen workspace+year (e.g. two members opening the
    recap page around the same moment) could both pass the "does a row
    already exist" check before either commits, and uq_workspace_recap_
    workspace_year would otherwise turn that race into an unhandled
    IntegrityError instead of both callers simply getting the one row
    that exists either way."""
    recap = db.scalar(
        select(WorkspaceRecap).where(WorkspaceRecap.workspace_id == workspace_id, WorkspaceRecap.year == year)
    )
    if recap is not None:
        return recap

    recap = WorkspaceRecap(workspace_id=workspace_id, year=year)
    try:
        with db.begin_nested():
            db.add(recap)
            db.flush()
    except IntegrityError:
        recap = db.scalar(
            select(WorkspaceRecap).where(WorkspaceRecap.workspace_id == workspace_id, WorkspaceRecap.year == year)
        )
        if recap is None:
            raise
    return recap


def _compute_recap_stats(workspace_id: int, year: int, db: Session) -> WorkspaceRecapOut:
    """Always computed live from the workspace's own entries dated in
    `year` (start_date, the same "which year this memory belongs to"
    field entries are already ordered/searched by elsewhere) - see
    models.WorkspaceRecap's docstring for why this is never cached. Used
    identically by the authenticated in-app recap endpoint and the
    public shared-recap endpoint (routers/sharing.py), so a stat added
    or fixed here is correct in both places at once."""
    entries = (
        db.scalars(
            select(JournalEntry)
            .where(JournalEntry.workspace_id == workspace_id, extract("year", JournalEntry.start_date) == year)
            .options(
                selectinload(JournalEntry.tags),
                selectinload(JournalEntry.images),
                selectinload(JournalEntry.coauthors),
                selectinload(JournalEntry.owner),
            )
            .order_by(JournalEntry.start_date)
        )
        .unique()
        .all()
    )

    photo_count = sum(len(entry.images) for entry in entries)

    tag_counter: Counter[str] = Counter()
    for entry in entries:
        for tag in entry.tags:
            tag_counter[tag.name] += 1
    top_tags = [
        RecapTagCount(name=name, count=count) for name, count in tag_counter.most_common(RECAP_TOP_TAGS_LIMIT)
    ]

    most_active_month: str | None = None
    if entries:
        month_counter = Counter(entry.start_date.month for entry in entries)
        busiest_count = max(month_counter.values())
        # Ties broken by earliest calendar month - arbitrary but
        # deterministic, so the same year always recomputes the same
        # answer rather than depending on dict/Counter iteration order.
        busiest_month = min(month for month, count in month_counter.items() if count == busiest_count)
        most_active_month = calendar.month_name[busiest_month]

    first_entry = None
    last_entry = None
    if entries:
        # Already ordered by start_date above.
        first_entry = RecapEntryHighlight(
            start_date=entries[0].start_date,
            playlist_name=entries[0].playlist_name,
            playlist_image_url=entries[0].playlist_image_url,
        )
        last_entry = RecapEntryHighlight(
            start_date=entries[-1].start_date,
            playlist_name=entries[-1].playlist_name,
            playlist_image_url=entries[-1].playlist_image_url,
        )

    contributors_by_id: dict[int, User] = {}
    for entry in entries:
        contributors_by_id[entry.owner.id] = entry.owner
        for coauthor in entry.coauthors:
            contributors_by_id[coauthor.id] = coauthor
    # Only an interesting "who showed up this year" story once there's
    # more than one person - a solo workspace's list of exactly itself
    # is trivial, so it's left empty rather than shown.
    contributors = (
        [UserPublic.model_validate(user) for user in sorted(contributors_by_id.values(), key=lambda u: u.username.lower())]
        if len(contributors_by_id) > 1
        else []
    )

    playlist_stats: dict[str, dict] = {}
    for entry in entries:
        # An entry with no playlist yet (e.g. synced from an offline
        # draft - see models.JournalEntry's comment) has nothing to
        # count here: "no playlist" isn't itself a playlist that can be
        # most-referenced, and grouping every playlist-less entry
        # together under one None key would wrongly report them as all
        # sharing "the same" playlist.
        if entry.playlist_id is None:
            continue
        stat = playlist_stats.setdefault(
            entry.playlist_id,
            {"name": entry.playlist_name, "image_url": entry.playlist_image_url, "count": 0},
        )
        stat["count"] += 1
    top_playlists = sorted(
        (
            RecapPlaylistCount(
                playlist_id=playlist_id,
                playlist_name=stat["name"],
                playlist_image_url=stat["image_url"],
                count=stat["count"],
            )
            for playlist_id, stat in playlist_stats.items()
            if stat["count"] > 1  # "most-referenced" only means anything once something actually repeats
        ),
        key=lambda p: p.count,
        reverse=True,
    )[:RECAP_TOP_PLAYLISTS_LIMIT]

    return WorkspaceRecapOut(
        year=year,
        entry_count=len(entries),
        photo_count=photo_count,
        top_tags=top_tags,
        most_active_month=most_active_month,
        first_entry=first_entry,
        last_entry=last_entry,
        contributors=contributors,
        top_playlists=top_playlists,
    )


@router.get("/{workspace_id}/recap/{year}", response_model=WorkspaceRecapOut)
def get_workspace_recap(
    workspace_id: int,
    year: int,
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_current_user_optional),
):
    """Same visibility rule as reading the workspace's entries at all
    (require_workspace_read_access) - a recap is an aggregate over
    content the caller can already read, not a new disclosure, so it
    isn't gated on share_token the way the public GET /api/shared-recap/
    {token} endpoint is. Get-or-creates the underlying WorkspaceRecap row
    on first view (see _get_or_create_recap) purely so share_token has
    somewhere to live if the owner later decides to share this year -
    that bookkeeping is incidental and available to any viewer, distinct
    from actually turning sharing on/off, which stays owner-only below."""
    require_workspace_read_access(workspace_id, db, current_user)
    _get_or_create_recap(workspace_id, year, db)
    db.commit()
    return _compute_recap_stats(workspace_id, year, db)


@router.post("/{workspace_id}/recap/{year}/share", response_model=RecapShareOut)
def enable_workspace_recap_sharing(
    workspace_id: int,
    year: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Owner-only, the workspace-level analogue of entries.
    enable_entry_sharing - the same "the entity's controlling party
    decides what leaves it publicly" precedent, one level up (workspace
    owner here, entry's primary author there). Idempotent: calling this
    again while already shared returns the existing token rather than
    rotating it, for the same reason entry sharing doesn't rotate on
    repeat calls - a link already handed out shouldn't silently break."""
    require_workspace_owner(workspace_id, db, current_user)
    recap = _get_or_create_recap(workspace_id, year, db)
    if recap.share_token is None:
        recap.share_token = secrets.token_urlsafe(32)
        db.commit()
        db.refresh(recap)
        logger.info(
            "workspace.recap_sharing_enabled workspace_id=%s year=%s user_id=%s",
            workspace_id, year, current_user.id,
        )
    return RecapShareOut(share_token=recap.share_token)


@router.delete("/{workspace_id}/recap/{year}/share", status_code=204)
def disable_workspace_recap_sharing(
    workspace_id: int,
    year: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Clears the share token - GET /api/shared-recap/{old-token} 404s
    immediately afterward, same as disabling a single entry's share
    link. Owner-only, same as enabling above. A harmless no-op if this
    workspace+year was never shared (or never even viewed) in the first
    place - nothing to revoke."""
    require_workspace_owner(workspace_id, db, current_user)
    recap = db.scalar(
        select(WorkspaceRecap).where(WorkspaceRecap.workspace_id == workspace_id, WorkspaceRecap.year == year)
    )
    if recap is not None and recap.share_token is not None:
        recap.share_token = None
        db.commit()
        logger.info(
            "workspace.recap_sharing_disabled workspace_id=%s year=%s user_id=%s",
            workspace_id, year, current_user.id,
        )
    logger.warning("workspace.deleted workspace_id=%s by=%s", workspace_id, current_user.id)
