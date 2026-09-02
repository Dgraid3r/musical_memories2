import uuid
from datetime import date
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..auth import get_current_user, get_current_user_optional
from ..database import get_db
from ..models import EntryImage, JournalEntry, User
from ..schemas import JournalEntryOut, JournalEntryUpdate

router = APIRouter(prefix="/api/entries", tags=["entries"])

UPLOADS_DIR = Path(__file__).resolve().parent.parent.parent / "uploads"
UPLOADS_DIR.mkdir(exist_ok=True)


def _is_owner(entry: JournalEntry, user: User | None) -> bool:
    return user is not None and entry.user_id == user.id


def _is_coauthor(entry: JournalEntry, user: User | None) -> bool:
    return user is not None and any(u.id == user.id for u in entry.coauthors)


def _can_view(entry: JournalEntry, user: User | None) -> bool:
    return entry.is_public or _is_owner(entry, user) or _is_coauthor(entry, user)


def _can_edit_content(entry: JournalEntry, user: User | None) -> bool:
    return _is_owner(entry, user) or _is_coauthor(entry, user)


def _visible_or_404(entry: JournalEntry | None, user: User | None) -> JournalEntry:
    # A private entry you can't see reads identically to a missing one, so
    # existence of other people's private entries is never disclosed.
    if entry is None or not _can_view(entry, user):
        raise HTTPException(status_code=404, detail="Entry not found")
    return entry


def _resolve_coauthors(usernames: list[str], db: Session, exclude_user_id: int) -> list[User]:
    unique_usernames = {u.strip() for u in usernames if u.strip()}
    if not unique_usernames:
        return []
    users = db.scalars(select(User).where(User.username.in_(unique_usernames))).all()
    missing = unique_usernames - {u.username for u in users}
    if missing:
        raise HTTPException(status_code=422, detail=f"Unknown username(s): {', '.join(sorted(missing))}")
    # Silently drop the primary author if they listed themselves - they're
    # already the owner, not a co-author.
    return [u for u in users if u.id != exclude_user_id]


def _save_images(images: list[UploadFile], entry_id: int, db: Session) -> None:
    for image in images:
        if not image.filename:
            continue
        suffix = Path(image.filename).suffix
        stored_name = f"{uuid.uuid4().hex}{suffix}"
        dest = UPLOADS_DIR / stored_name
        with dest.open("wb") as f:
            f.write(image.file.read())
        db.add(EntryImage(entry_id=entry_id, filename=stored_name))


@router.get("", response_model=list[JournalEntryOut])
def list_entries(
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_current_user_optional),
):
    """Public entries from everyone, plus the caller's own private ones and
    any private entries the caller is a co-author on."""
    stmt = select(JournalEntry)
    if current_user is None:
        stmt = stmt.where(JournalEntry.is_public.is_(True))
    else:
        stmt = stmt.where(
            or_(
                JournalEntry.is_public.is_(True),
                JournalEntry.user_id == current_user.id,
                JournalEntry.coauthors.any(User.id == current_user.id),
            )
        )
    stmt = stmt.order_by(JournalEntry.start_date.desc(), JournalEntry.id.desc())
    return db.scalars(stmt).unique().all()


@router.get("/{entry_id}", response_model=JournalEntryOut)
def get_entry(
    entry_id: int,
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_current_user_optional),
):
    entry = db.get(JournalEntry, entry_id)
    return _visible_or_404(entry, current_user)


@router.post("", response_model=JournalEntryOut, status_code=201)
def create_entry(
    start_date: date = Form(...),
    end_date: date | None = Form(None),
    text: str | None = Form(None),
    playlist_id: str = Form(...),
    playlist_name: str = Form(...),
    playlist_url: str = Form(...),
    playlist_image_url: str | None = Form(None),
    is_public: bool = Form(False),
    coauthor_usernames: list[str] = Form(default=[]),
    images: list[UploadFile] = File(default=[]),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    end_date = end_date or start_date
    if end_date < start_date:
        raise HTTPException(status_code=422, detail="end_date cannot be before start_date")

    entry = JournalEntry(
        user_id=current_user.id,
        start_date=start_date,
        end_date=end_date,
        text=text,
        playlist_id=playlist_id,
        playlist_name=playlist_name,
        playlist_url=playlist_url,
        playlist_image_url=playlist_image_url,
        is_public=is_public,
        coauthors=_resolve_coauthors(coauthor_usernames, db, exclude_user_id=current_user.id),
    )
    db.add(entry)
    db.flush()

    _save_images(images, entry.id, db)

    db.commit()
    db.refresh(entry)
    return entry


@router.post("/{entry_id}/images", response_model=JournalEntryOut, status_code=201)
def add_images(
    entry_id: int,
    images: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    entry = db.get(JournalEntry, entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Entry not found")
    if not _can_edit_content(entry, current_user):
        raise HTTPException(status_code=403, detail="You do not have permission to edit this entry")

    _save_images(images, entry.id, db)

    db.commit()
    db.refresh(entry)
    return entry


@router.patch("/{entry_id}", response_model=JournalEntryOut)
def update_entry(
    entry_id: int,
    payload: JournalEntryUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    entry = db.get(JournalEntry, entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Entry not found")
    if not _can_edit_content(entry, current_user):
        raise HTTPException(status_code=403, detail="You do not have permission to edit this entry")

    if payload.text is not None:
        entry.text = payload.text

    # Visibility and co-author management stay primary-author-only, even for
    # a co-author who otherwise has content-edit rights on this entry.
    if payload.is_public is not None:
        if not _is_owner(entry, current_user):
            raise HTTPException(status_code=403, detail="Only the primary author can change visibility")
        entry.is_public = payload.is_public

    if payload.coauthor_usernames is not None:
        if not _is_owner(entry, current_user):
            raise HTTPException(status_code=403, detail="Only the primary author can manage co-authors")
        entry.coauthors = _resolve_coauthors(payload.coauthor_usernames, db, exclude_user_id=entry.user_id)

    db.commit()
    db.refresh(entry)
    return entry


@router.delete("/{entry_id}", status_code=204)
def delete_entry(
    entry_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    entry = db.get(JournalEntry, entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Entry not found")
    if not _is_owner(entry, current_user):
        raise HTTPException(status_code=403, detail="Only the primary author can delete this entry")
    for image in entry.images:
        image_path = UPLOADS_DIR / image.filename
        image_path.unlink(missing_ok=True)
    db.delete(entry)
    db.commit()
