import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..database import get_db
from ..models import User, Workspace, WorkspaceMembership
from ..schemas import (
    PublicWorkspaceOut,
    WorkspaceCreate,
    WorkspaceMemberAdd,
    WorkspaceMemberOut,
    WorkspaceMemberRoleUpdate,
    WorkspaceOut,
    WorkspaceVisibilityUpdate,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/workspaces", tags=["workspaces"])

WRITE_ROLES = ("owner", "member")


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


@router.get("/public", response_model=list[PublicWorkspaceOut])
def browse_public_workspaces(
    q: str | None = Query(None, min_length=1, description="Filter by name"),
    db: Session = Depends(get_db),
):
    """Discovery - no auth required, and deliberately returns just enough
    to identify a workspace (name, when it was created), never entry
    content and never a private workspace."""
    stmt = select(Workspace).where(Workspace.visibility == "public")
    if q:
        stmt = stmt.where(Workspace.name.ilike(f"%{q}%"))
    stmt = stmt.order_by(Workspace.name)
    return db.scalars(stmt).all()


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


@router.post("/{workspace_id}/members", response_model=WorkspaceMemberOut, status_code=201)
def add_member(
    workspace_id: int,
    payload: WorkspaceMemberAdd,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Owner-only. A stand-in for a real invite flow (email invites,
    verification, etc. are explicitly out of scope for now) - adds an
    existing user to the workspace by username, immediately, with no
    acceptance step. Always starts as "member"; use the role-update
    endpoint below to make them a "subscriber" instead."""
    require_workspace_owner(workspace_id, db, current_user)

    user = db.scalar(select(User).where(User.username == payload.username))
    if user is None:
        raise HTTPException(status_code=404, detail="No user with that username")

    if _get_membership(workspace_id, user, db) is not None:
        raise HTTPException(status_code=409, detail="That user is already a member of this workspace")

    membership = WorkspaceMembership(workspace_id=workspace_id, user_id=user.id, role="member")
    db.add(membership)
    db.commit()
    logger.info("workspace.member_added workspace_id=%s user_id=%s by=%s", workspace_id, user.id, current_user.id)
    return WorkspaceMemberOut(user_id=user.id, username=user.username, role="member")


@router.patch("/{workspace_id}/members/{user_id}", response_model=WorkspaceMemberOut)
def update_member_role(
    workspace_id: int,
    user_id: int,
    payload: WorkspaceMemberRoleUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Owner-only. Sets a member to "member" (full read/write collaborator)
    or "subscriber" (read-only) - not "owner", there's no ownership-
    transfer flow. The owner can't change their own role this way, for the
    same reason they can't remove themselves via the endpoint below: it
    would leave the workspace without an owner with no way to recover."""
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
    """Owner-only. The owner can't remove themselves this way - there's no
    ownership-transfer flow, so that would either orphan the workspace or
    silently strand it without an owner; deleting the whole workspace is
    the explicit action for that instead."""
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
    """Owner-only. Cascades to every entry, tag, and comment in the
    workspace (see the cascade="all, delete-orphan" relationships in
    models.py) - this is genuinely destructive and irreversible."""
    workspace = require_workspace_owner(workspace_id, db, current_user)
    db.delete(workspace)
    db.commit()
    logger.warning("workspace.deleted workspace_id=%s by=%s", workspace_id, current_user.id)
