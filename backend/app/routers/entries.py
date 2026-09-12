import logging
import secrets
from datetime import date
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy import Select, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from ..auth import get_current_user, get_current_user_optional
from ..database import get_db
from ..models import EntryEditEvent, EntryImage, JournalEntry, Tag, User, WorkspaceMembership
from ..schemas import EntryEditEventOut, EntryShareOut, JournalEntryOut, JournalEntryUpdate
from ..storage import get_storage
from .workspaces import (
    WRITE_ROLES,
    delete_stored_images,
    require_workspace_read_access,
    require_workspace_write_access,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/workspaces/{workspace_id}/entries", tags=["entries"])

# Same limit/offset convention as GET /api/workspaces/public
# (workspaces.PUBLIC_WORKSPACES_DEFAULT_LIMIT/MAX_LIMIT) and GET
# /api/admin/users (admin.ADMIN_USERS_DEFAULT_LIMIT/MAX_LIMIT) - same
# default/max values, for consistency across the one pagination scheme
# this codebase uses rather than inventing a new one here.
ENTRIES_DEFAULT_LIMIT = 20
ENTRIES_MAX_LIMIT = 100

# Entry-photo upload validation. The frontend's own file picker already
# restricts to accept="image/*" (see NewEntryForm.tsx/EntryCard.tsx), but
# that's an unenforced client-side hint, not a server-side guarantee - a
# direct API call can send anything under any content-type. Before this,
# _save_images accepted any extension/content-type and any size, with no
# allowlist and no cap.
ALLOWED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
ALLOWED_IMAGE_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
# 20MB - generous for a phone photo (even a high-resolution JPEG capture is
# ordinarily a few MB) while still bounding what one upload can cost in
# storage and request-handling time; not so large that it's an easy way to
# make a handful of requests eat a lot of disk/object-storage space.
MAX_IMAGE_UPLOAD_BYTES = 20 * 1024 * 1024

# Not workspace-nested, like /api/comments/{id} - the entry_id in the path
# is enough to resolve the owning workspace via the entry itself, and this
# is the *only* path to an image's bytes now: every fetch goes through
# _visible_or_404 first (see get_entry_image below), unlike the old raw
# /uploads static mount, which served any file to anyone who had or
# guessed its filename regardless of the owning entry's or workspace's
# visibility.
image_router = APIRouter(prefix="/api/entries", tags=["entries"])


def _is_owner(entry: JournalEntry, user: User | None) -> bool:
    return user is not None and entry.user_id == user.id


def _is_coauthor(entry: JournalEntry, user: User | None) -> bool:
    return user is not None and any(u.id == user.id for u in entry.coauthors)


def _is_workspace_member(workspace_id: int, user: User, db: Session) -> bool:
    return (
        db.scalar(
            select(WorkspaceMembership.id).where(
                WorkspaceMembership.workspace_id == workspace_id,
                WorkspaceMembership.user_id == user.id,
            )
        )
        is not None
    )


def _can_view(entry: JournalEntry, user: User | None, db: Session) -> bool:
    # Self-sufficient regardless of upstream gating - re-derives workspace
    # access itself rather than assuming a route already checked it, so
    # this is correct wherever it's called from, including comments.py's
    # /api/comments/{id} routes, which have no workspace_id in their URL at
    # all and rely entirely on the comment's own entry to know which
    # workspace applies.
    if entry.workspace.visibility == "public":
        # A public workspace's *public* entries are readable by anyone,
        # anonymous included. A *private* entry inside a public workspace
        # is still never broadened by the workspace's own publicity - it
        # stays owner/co-author only, exactly as it would in a private
        # workspace.
        if entry.is_public:
            return True
        return _is_owner(entry, user) or _is_coauthor(entry, user)

    # Private workspace: the caller must be authenticated and hold ANY
    # role (owner/member/subscriber) there.
    if user is None or not _is_workspace_member(entry.workspace_id, user, db):
        return False
    return entry.is_public or _is_owner(entry, user) or _is_coauthor(entry, user)


def _can_edit_content(entry: JournalEntry, user: User) -> bool:
    return _is_owner(entry, user) or _is_coauthor(entry, user)


def _visible_or_404(entry: JournalEntry | None, user: User | None, db: Session) -> JournalEntry:
    # A private entry you can't see reads identically to a missing one, so
    # existence of other people's private entries (or of an entry in a
    # workspace you're not in) is never disclosed - including to a fully
    # anonymous caller.
    if entry is None or not _can_view(entry, user, db):
        raise HTTPException(status_code=404, detail="Entry not found")
    return entry


def _get_entry_in_workspace_or_404(entry_id: int, workspace_id: int, db: Session) -> JournalEntry:
    """Existence-and-scope check: does this entry exist, and does it belong
    to the workspace named in the URL? Deliberately separate from
    _visible_or_404 (view permission) - callers that need edit/delete
    permission use this first, then apply their own 403 check, matching the
    existing "404 for missing, 403 for forbidden" split."""
    entry = db.get(JournalEntry, entry_id)
    if entry is None or entry.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="Entry not found")
    return entry


def _apply_visibility(stmt: Select, current_user: User | None, workspace_id: int) -> Select:
    """Entries in this workspace that are public, plus the caller's own
    private ones, plus private ones the caller is a co-author on. Shared by
    every endpoint that lists or searches entries so the visibility rule is
    defined in exactly one place.

    Every caller of this has already passed require_workspace_read_access,
    so reaching this function at all means the caller can read *something*
    in workspace_id - either because it's public, or because they hold a
    role there. The only thing left to decide per-row is whether a specific
    private entry belongs to *this* caller: an anonymous caller (only
    possible when the workspace is public) sees just the public entries;
    an authenticated caller also sees their own private ones."""
    stmt = stmt.where(JournalEntry.workspace_id == workspace_id)
    if current_user is None:
        return stmt.where(JournalEntry.is_public.is_(True))
    return stmt.where(
        or_(
            JournalEntry.is_public.is_(True),
            JournalEntry.user_id == current_user.id,
            JournalEntry.coauthors.any(User.id == current_user.id),
        )
    )


def _resolve_coauthors(usernames: list[str], db: Session, exclude_user_id: int, workspace_id: int) -> list[User]:
    unique_usernames = {u.strip() for u in usernames if u.strip()}
    if not unique_usernames:
        return []
    users = db.scalars(select(User).where(User.username.in_(unique_usernames))).all()
    missing = unique_usernames - {u.username for u in users}
    if missing:
        raise HTTPException(status_code=422, detail=f"Unknown username(s): {', '.join(sorted(missing))}")
    # Silently drop the primary author if they listed themselves - they're
    # already the owner, not a co-author.
    candidates = [u for u in users if u.id != exclude_user_id]

    if candidates:
        # Co-authors get full content-edit rights, the same as a workspace
        # member - a subscriber (read-only) is never a valid co-author
        # candidate, same as a non-member isn't.
        writer_ids = set(
            db.scalars(
                select(WorkspaceMembership.user_id).where(
                    WorkspaceMembership.workspace_id == workspace_id,
                    WorkspaceMembership.user_id.in_([u.id for u in candidates]),
                    WorkspaceMembership.role.in_(WRITE_ROLES),
                )
            ).all()
        )
        non_writers = sorted(u.username for u in candidates if u.id not in writer_ids)
        if non_writers:
            raise HTTPException(
                status_code=422,
                detail=f"Not a member of this workspace: {', '.join(non_writers)}",
            )

    return candidates


def _resolve_tags(names: list[str], db: Session, workspace_id: int) -> list[Tag]:
    """Unlike co-authors, tags are get-or-create: any free-text tag name is
    valid, and typing one for the first time defines it - scoped to this
    workspace, so two different workspaces can each have their own tag with
    the same name. Names are normalized (trimmed, lowercased) so
    casing/whitespace variants collapse onto the same tag.

    The "not found, so create it" check below is inherently racy: two
    concurrent entry-creations in the same workspace introducing the same
    brand-new tag name for the first time can both pass it before either
    commits. Each new tag is inserted inside its own SAVEPOINT (db.
    begin_nested(), not the whole transaction) so a uq_tag_workspace_name
    conflict here only unwinds that one insert - never the caller's other
    already-flushed-but-uncommitted changes in the same outer transaction
    (e.g. update_entry may have already changed entry.text earlier in the
    same request). On conflict, this re-fetches the tag the other
    concurrent request just committed and uses that instead - the race
    resolves silently, it never surfaces as an error to the caller."""
    normalized = {n.strip().lower() for n in names if n.strip()}
    if not normalized:
        return []
    existing = db.scalars(
        select(Tag).where(Tag.workspace_id == workspace_id, Tag.name.in_(normalized))
    ).all()
    resolved: list[Tag] = list(existing)
    existing_names = {t.name for t in existing}

    for name in normalized - existing_names:
        tag = Tag(name=name, workspace_id=workspace_id)
        try:
            with db.begin_nested():
                db.add(tag)
                db.flush()
        except IntegrityError:
            tag = db.scalar(select(Tag).where(Tag.workspace_id == workspace_id, Tag.name == name))
            # Only ever expected to be None if the constraint fired for
            # some other reason - never silently drop a tag the caller
            # asked for.
            if tag is None:
                raise
        resolved.append(tag)

    return resolved


def _save_images(images: list[UploadFile], entry_id: int, db: Session) -> list[EntryImage]:
    """Returns the EntryImage rows actually created - a request can arrive
    with zero usable files (every UploadFile missing a filename), and the
    caller (add_images) uses this to decide whether an edit-history event
    is warranted.

    Rejects (400, before anything is saved) any file whose extension or
    content-type isn't in the image allowlist, or whose size exceeds
    MAX_IMAGE_UPLOAD_BYTES - raised mid-loop, so an invalid file anywhere
    in the batch discards the whole request rather than silently saving
    only the files that came before it."""
    storage = get_storage()
    saved: list[EntryImage] = []
    for image in images:
        if not image.filename:
            continue
        suffix = Path(image.filename).suffix
        if suffix.lower() not in ALLOWED_IMAGE_EXTENSIONS or image.content_type not in ALLOWED_IMAGE_CONTENT_TYPES:
            raise HTTPException(
                status_code=400,
                detail="Unsupported file type - only JPEG, PNG, WEBP, and GIF images can be uploaded.",
            )
        # image.size is populated by Starlette's multipart parser from the
        # bytes it already received, so this rejects an oversized file
        # without this function itself reading it into memory first.
        if image.size is not None and image.size > MAX_IMAGE_UPLOAD_BYTES:
            raise HTTPException(
                status_code=400,
                detail=f"That image is too large - the limit is {MAX_IMAGE_UPLOAD_BYTES // (1024 * 1024)}MB per photo.",
            )
        data = image.file.read()
        if len(data) > MAX_IMAGE_UPLOAD_BYTES:
            # Defensive fallback for the (in this codebase's usage,
            # untriggered) case where image.size wasn't populated - the
            # same limit enforced against the actual bytes read.
            raise HTTPException(
                status_code=400,
                detail=f"That image is too large - the limit is {MAX_IMAGE_UPLOAD_BYTES // (1024 * 1024)}MB per photo.",
            )
        stored_name = storage.save(data, suffix)
        entry_image = EntryImage(entry_id=entry_id, filename=stored_name)
        db.add(entry_image)
        saved.append(entry_image)
    return saved


@router.get("", response_model=list[JournalEntryOut])
def list_entries(
    workspace_id: int,
    q: str | None = Query(None, min_length=1, description="Full-text search across entry text and tags"),
    tag: str | None = Query(None, description="Filter to entries carrying this exact tag name"),
    located_only: bool = Query(
        False, description="Only entries with a location set - powers the map view, same visibility rules apply"
    ),
    limit: int = Query(ENTRIES_DEFAULT_LIMIT, ge=1, le=ENTRIES_MAX_LIMIT),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_current_user_optional),
):
    """Entries in this workspace that are public, plus (if logged in) the
    caller's own private ones and any private entries the caller is a
    co-author on. A public workspace is readable with no auth token at all;
    a private one requires holding any role there. Optionally narrowed by a
    full-text search (`q`, matched against entry text and tag names via
    Postgres tsvector), an exact tag filter (`tag`), and/or `located_only`
    (for the map view) - reuses this same _apply_visibility call rather
    than a separate endpoint or permission check, so a located entry the
    caller couldn't otherwise see never appears on the map either.

    `limit`/`offset` page through results, same convention (and same
    default/max values) as GET /api/workspaces/public and GET
    /api/admin/users - the frontend's "load more" pattern (see
    PublicWorkspaceBrowser.tsx, and App.tsx's entry list) fetches
    `limit` at a time and treats a page shorter than `limit` as the end.

    Eager-loads coauthors/images/tags with `selectinload` so returning a
    page of entries costs a small constant number of queries (one for
    the entries themselves, one per eager-loaded relationship) rather
    than scaling with how many entries are on the page - without this,
    JournalEntryOut's serialization triggers a separate query per
    relationship *per row* (an N+1 pattern) as it reads each entry's
    `.coauthors`/`.images`/`.tags`."""
    require_workspace_read_access(workspace_id, db, current_user)

    stmt = _apply_visibility(select(JournalEntry), current_user, workspace_id)
    stmt = stmt.options(
        selectinload(JournalEntry.coauthors),
        selectinload(JournalEntry.images),
        selectinload(JournalEntry.tags),
    )

    if tag is not None:
        stmt = stmt.where(JournalEntry.tags.any(Tag.name == tag.strip().lower()))

    if located_only:
        stmt = stmt.where(JournalEntry.latitude.isnot(None))

    if q is not None:
        tsquery = func.websearch_to_tsquery("english", q)
        stmt = stmt.where(JournalEntry.search_vector.op("@@")(tsquery))
        stmt = stmt.order_by(func.ts_rank(JournalEntry.search_vector, tsquery).desc(), JournalEntry.id.desc())
    else:
        stmt = stmt.order_by(JournalEntry.start_date.desc(), JournalEntry.id.desc())

    stmt = stmt.limit(limit).offset(offset)

    return db.scalars(stmt).unique().all()


@router.get("/tags", response_model=list[str])
def list_tags(
    workspace_id: int,
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_current_user_optional),
):
    """All tag names in use in this workspace, across entries visible to the
    caller - the same visibility rule as listing entries, so a tag used only
    on someone else's private entry doesn't leak here. Used to power tag
    autocomplete."""
    require_workspace_read_access(workspace_id, db, current_user)

    # Tag isn't a JournalEntry, so the visibility helper's JournalEntry.*
    # filters need an explicit join from Tag back to journal_entries.
    stmt = select(Tag.name).where(Tag.workspace_id == workspace_id).join(Tag.entries)
    stmt = _apply_visibility(stmt, current_user, workspace_id).distinct().order_by(Tag.name)
    return db.scalars(stmt).all()


@router.get("/{entry_id}", response_model=JournalEntryOut)
def get_entry(
    workspace_id: int,
    entry_id: int,
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_current_user_optional),
):
    require_workspace_read_access(workspace_id, db, current_user)
    entry = _get_entry_in_workspace_or_404(entry_id, workspace_id, db)
    return _visible_or_404(entry, current_user, db)


@router.get("/{entry_id}/edit-history", response_model=list[EntryEditEventOut])
def get_entry_edit_history(
    workspace_id: int,
    entry_id: int,
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_current_user_optional),
):
    """Same visibility rule as the entry itself (_visible_or_404) - no
    separate permission logic for the history than for the entry it
    belongs to. Most-recent-first (see JournalEntry.edit_events'
    order_by)."""
    require_workspace_read_access(workspace_id, db, current_user)
    entry = _get_entry_in_workspace_or_404(entry_id, workspace_id, db)
    entry = _visible_or_404(entry, current_user, db)
    return entry.edit_events


@router.post("", response_model=JournalEntryOut, status_code=201)
def create_entry(
    workspace_id: int,
    start_date: date = Form(...),
    end_date: date | None = Form(None),
    text: str | None = Form(None),
    # Optional - see models.JournalEntry's comment on why. The online
    # form still always sends all three (NewEntryForm.tsx refuses to
    # submit without a picked playlist); only a synced offline draft
    # (offlineDrafts.ts, which never had network access to search
    # Spotify) omits them, and can add a playlist afterward via
    # PATCH .../entries/{id}'s `playlist` field.
    playlist_id: str | None = Form(None),
    playlist_name: str | None = Form(None),
    playlist_url: str | None = Form(None),
    playlist_image_url: str | None = Form(None),
    is_public: bool = Form(False),
    coauthor_usernames: list[str] = Form(default=[]),
    tags: list[str] = Form(default=[]),
    images: list[UploadFile] = File(default=[]),
    # Optional, user-supplied location - see models.JournalEntry's comment
    # and routers/places.py. Omitting all three is a completely normal
    # entry, not an error state.
    latitude: float | None = Form(None),
    longitude: float | None = Form(None),
    location_name: str | None = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_workspace_write_access(workspace_id, db, current_user)

    end_date = end_date or start_date
    if end_date < start_date:
        raise HTTPException(status_code=422, detail="end_date cannot be before start_date")

    if (latitude is None) != (longitude is None):
        raise HTTPException(status_code=422, detail="latitude and longitude must be provided together")

    if not (playlist_id and playlist_name and playlist_url) and any((playlist_id, playlist_name, playlist_url)):
        raise HTTPException(status_code=422, detail="playlist_id, playlist_name, and playlist_url must be provided together")

    entry = JournalEntry(
        workspace_id=workspace_id,
        user_id=current_user.id,
        start_date=start_date,
        end_date=end_date,
        text=text,
        playlist_id=playlist_id,
        playlist_name=playlist_name,
        playlist_url=playlist_url,
        playlist_image_url=playlist_image_url,
        is_public=is_public,
        coauthors=_resolve_coauthors(coauthor_usernames, db, exclude_user_id=current_user.id, workspace_id=workspace_id),
        tags=_resolve_tags(tags, db, workspace_id),
        latitude=latitude,
        longitude=longitude,
        location_name=(location_name.strip() or None) if location_name else None,
    )
    db.add(entry)
    db.flush()

    _save_images(images, entry.id, db)

    db.commit()
    db.refresh(entry)
    logger.info("entry.created workspace_id=%s entry_id=%s user_id=%s", workspace_id, entry.id, current_user.id)
    return entry


@router.post("/{entry_id}/images", response_model=JournalEntryOut, status_code=201)
def add_images(
    workspace_id: int,
    entry_id: int,
    images: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_workspace_write_access(workspace_id, db, current_user)
    entry = _get_entry_in_workspace_or_404(entry_id, workspace_id, db)
    if not _can_edit_content(entry, current_user):
        raise HTTPException(status_code=403, detail="You do not have permission to edit this entry")

    saved = _save_images(images, entry.id, db)
    if saved:
        db.add(EntryEditEvent(entry_id=entry.id, editor_user_id=current_user.id, change_summary="images"))

    db.commit()
    db.refresh(entry)
    return entry


@router.patch("/{entry_id}", response_model=JournalEntryOut)
def update_entry(
    workspace_id: int,
    entry_id: int,
    payload: JournalEntryUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_workspace_write_access(workspace_id, db, current_user)
    entry = _get_entry_in_workspace_or_404(entry_id, workspace_id, db)
    if not _can_edit_content(entry, current_user):
        raise HTTPException(status_code=403, detail="You do not have permission to edit this entry")

    # Tracks which fields actually changed value (not just which fields
    # were present in the request) - a PATCH that resends the entry's
    # current values is a no-op and must not add an edit-history entry.
    changed_fields: list[str] = []

    if payload.text is not None and payload.text != entry.text:
        entry.text = payload.text
        changed_fields.append("content")

    if payload.tags is not None:
        new_tags = _resolve_tags(payload.tags, db, workspace_id)
        if {t.id for t in new_tags} != {t.id for t in entry.tags}:
            entry.tags = new_tags
            changed_fields.append("tags")

    # Location is content, like text/tags - any co-author with content-edit
    # rights can set or clear it, not just the primary author. `"location"
    # in payload.model_fields_set` is what distinguishes "the client didn't
    # mention location at all" (leave unchanged) from an explicit JSON
    # `"location": null` (clear it) - payload.location being None alone is
    # ambiguous between those two (see schemas.JournalEntryUpdate).
    if "location" in payload.model_fields_set:
        if payload.location is None:
            if entry.latitude is not None or entry.longitude is not None or entry.location_name is not None:
                entry.latitude = None
                entry.longitude = None
                entry.location_name = None
                changed_fields.append("location")
        else:
            new_location = (payload.location.latitude, payload.location.longitude, payload.location.location_name)
            if new_location != (entry.latitude, entry.longitude, entry.location_name):
                entry.latitude, entry.longitude, entry.location_name = new_location
                changed_fields.append("location")

    # Playlist is content, like text/tags - most relevant for an offline-
    # created draft (see models.JournalEntry's comment) that synced with
    # none at all and is now being completed. Only ever sets one - see
    # schemas.EntryPlaylistInput on why there's no "clear" path here the
    # way location has.
    if payload.playlist is not None:
        new_playlist = (
            payload.playlist.playlist_id,
            payload.playlist.playlist_name,
            payload.playlist.playlist_url,
            payload.playlist.playlist_image_url,
        )
        current_playlist = (entry.playlist_id, entry.playlist_name, entry.playlist_url, entry.playlist_image_url)
        if new_playlist != current_playlist:
            entry.playlist_id, entry.playlist_name, entry.playlist_url, entry.playlist_image_url = new_playlist
            changed_fields.append("playlist")

    # Visibility and co-author management stay primary-author-only, even for
    # a co-author who otherwise has content-edit rights on this entry.
    if payload.is_public is not None:
        if not _is_owner(entry, current_user):
            raise HTTPException(status_code=403, detail="Only the primary author can change visibility")
        if payload.is_public != entry.is_public:
            entry.is_public = payload.is_public
            changed_fields.append("visibility")

    if payload.coauthor_usernames is not None:
        if not _is_owner(entry, current_user):
            raise HTTPException(status_code=403, detail="Only the primary author can manage co-authors")
        new_coauthors = _resolve_coauthors(
            payload.coauthor_usernames, db, exclude_user_id=entry.user_id, workspace_id=workspace_id
        )
        if {u.id for u in new_coauthors} != {u.id for u in entry.coauthors}:
            entry.coauthors = new_coauthors
            changed_fields.append("coauthors")

    if changed_fields:
        db.add(
            EntryEditEvent(
                entry_id=entry.id,
                editor_user_id=current_user.id,
                change_summary=", ".join(changed_fields),
            )
        )

    db.commit()
    db.refresh(entry)
    return entry


@router.delete("/{entry_id}", status_code=204)
def delete_entry(
    workspace_id: int,
    entry_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    require_workspace_write_access(workspace_id, db, current_user)
    entry = _get_entry_in_workspace_or_404(entry_id, workspace_id, db)
    if not _is_owner(entry, current_user):
        raise HTTPException(status_code=403, detail="Only the primary author can delete this entry")
    # Read the filenames before deleting the row - nothing left to
    # traverse afterward - but don't touch storage until the database
    # delete has actually committed (see workspaces.delete_stored_images
    # for why this ordering, not the reverse, is the safe one: a commit
    # failure here must never have already deleted real files for a
    # database row that's still there).
    image_filenames = [image.filename for image in entry.images]
    db.delete(entry)
    db.commit()
    delete_stored_images(image_filenames)
    logger.info("entry.deleted workspace_id=%s entry_id=%s user_id=%s", workspace_id, entry_id, current_user.id)


@router.post("/{entry_id}/share", response_model=EntryShareOut)
def enable_entry_sharing(
    workspace_id: int,
    entry_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Turns on a public, unauthenticated link to this one entry (see
    routers/sharing.py's GET /api/shared/{token}) - independent of
    is_public/Workspace.visibility, so a private entry in a private
    workspace is still individually shareable this way.

    Only the primary author can toggle sharing, not a co-author - the
    same extra visibility-control power the primary author already holds
    over is_public, co-authors, and deletion above (see update_entry/
    delete_entry).

    Idempotent: calling this again while already shared returns the
    existing token rather than rotating it - rotating on every call
    would silently break a link someone was already given, for no
    benefit, since generating a genuinely *new* link is what disabling
    and re-enabling is for."""
    require_workspace_write_access(workspace_id, db, current_user)
    entry = _get_entry_in_workspace_or_404(entry_id, workspace_id, db)
    if not _is_owner(entry, current_user):
        raise HTTPException(status_code=403, detail="Only the primary author can share this entry")

    if entry.share_token is None:
        entry.share_token = secrets.token_urlsafe(32)
        db.commit()
        db.refresh(entry)
        logger.info(
            "entry.sharing_enabled workspace_id=%s entry_id=%s user_id=%s", workspace_id, entry_id, current_user.id
        )

    return EntryShareOut(share_token=entry.share_token)


@router.delete("/{entry_id}/share", status_code=204)
def disable_entry_sharing(
    workspace_id: int,
    entry_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Clears the share token, immediately invalidating any previously-
    shared link - GET /api/shared/{old-token} 404s right after this
    commits, the same non-disclosure 404 it would give a token that
    never existed. Only the primary author, same as enable above."""
    require_workspace_write_access(workspace_id, db, current_user)
    entry = _get_entry_in_workspace_or_404(entry_id, workspace_id, db)
    if not _is_owner(entry, current_user):
        raise HTTPException(status_code=403, detail="Only the primary author can share this entry")

    if entry.share_token is not None:
        entry.share_token = None
        db.commit()
        logger.info(
            "entry.sharing_disabled workspace_id=%s entry_id=%s user_id=%s", workspace_id, entry_id, current_user.id
        )


@image_router.get("/{entry_id}/images/{image_id}")
def get_entry_image(
    entry_id: int,
    image_id: int,
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_current_user_optional),
):
    """The only path to an image's bytes - reuses the exact same
    visibility rule as GET .../entries/{entry_id} (_visible_or_404),
    rather than a raw static file mount that would serve any image to
    anyone who had or guessed its stored filename, regardless of whether
    its entry or workspace is private. Readable with no auth token at all
    when the entry is genuinely public, same as the entry itself.

    Serves the bytes directly for local-disk storage, or redirects to a
    short-lived presigned URL for object storage (see storage.py) - the
    permission check above runs either way, before either kind of
    response is ever produced."""
    entry = db.get(JournalEntry, entry_id)
    entry = _visible_or_404(entry, current_user, db)
    image = next((img for img in entry.images if img.id == image_id), None)
    if image is None:
        raise HTTPException(status_code=404, detail="Image not found")
    return get_storage().serve_response(image.filename)
