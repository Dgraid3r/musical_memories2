import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..database import get_db
from ..models import User, Workspace, WorkspaceMembership
from ..schemas import WorkspaceCreate, WorkspaceMemberAdd, WorkspaceMemberOut, WorkspaceOut

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/workspaces", tags=["workspaces"])


def _get_membership(workspace_id: int, current_user: User, db: Session) -> WorkspaceMembership | None:
    return db.scalar(
        select(WorkspaceMembership).where(
            WorkspaceMembership.workspace_id == workspace_id,
            WorkspaceMembership.user_id == current_user.id,
        )
    )


def require_workspace_member(workspace_id: int, db: Session, current_user: User) -> Workspace:
    """A workspace the caller isn't a member of reads identically to one
    that doesn't exist - the same "never disclose" pattern already used for
    a private entry the caller can't see, which also reads as a 404 rather
    than a 403. Used by every workspace-scoped route (entries, comments,
    tags, search) as the first gate before anything else happens."""
    membership = _get_membership(workspace_id, current_user, db)
    if membership is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return membership.workspace


def require_workspace_owner(workspace_id: int, db: Session, current_user: User) -> Workspace:
    membership = _get_membership(workspace_id, current_user, db)
    if membership is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    if membership.role != "owner":
        raise HTTPException(status_code=403, detail="Only the workspace owner can do this")
    return membership.workspace


@router.post("", response_model=WorkspaceOut, status_code=201)
def create_workspace(
    payload: WorkspaceCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Any authenticated user can create a workspace; doing so makes them
    its owner. There is no cap on how many workspaces a user can create or
    belong to."""
    workspace = Workspace(name=payload.name, created_by=current_user.id)
    db.add(workspace)
    db.flush()
    db.add(WorkspaceMembership(workspace_id=workspace.id, user_id=current_user.id, role="owner"))
    db.commit()
    db.refresh(workspace)
    logger.info("workspace.created workspace_id=%s created_by=%s", workspace.id, current_user.id)
    return WorkspaceOut(
        id=workspace.id, name=workspace.name, created_at=workspace.created_at, created_by=workspace.created_by,
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
        WorkspaceOut(id=w.id, name=w.name, created_at=w.created_at, created_by=w.created_by, role=role)
        for w, role in rows
    ]


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
    acceptance step."""
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
