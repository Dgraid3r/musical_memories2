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


def _visible_or_404(entry: JournalEntry | None, user: User | None) -> JournalEntry:
    # A private entry you don't own reads identically to a missing one, so
    # existence of other people's private entries is never disclosed.
    if entry is None or (not entry.is_public and (user is None or entry.user_id != user.id)):
        raise HTTPException(status_code=404, detail="Entry not found")
    return entry


@router.get("", response_model=list[JournalEntryOut])
def list_entries(
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_current_user_optional),
):
    """Public entries from everyone, plus the caller's own private ones."""
    stmt = select(JournalEntry)
    if current_user is None:
        stmt = stmt.where(JournalEntry.is_public.is_(True))
    else:
        stmt = stmt.where(
            or_(JournalEntry.is_public.is_(True), JournalEntry.user_id == current_user.id)
        )
    stmt = stmt.order_by(JournalEntry.entry_date.desc(), JournalEntry.id.desc())
    return db.scalars(stmt).all()


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
    entry_date: date = Form(...),
    text: str | None = Form(None),
    playlist_id: str = Form(...),
    playlist_name: str = Form(...),
    playlist_url: str = Form(...),
    playlist_image_url: str | None = Form(None),
    is_public: bool = Form(False),
    images: list[UploadFile] = File(default=[]),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    entry = JournalEntry(
        user_id=current_user.id,
        entry_date=entry_date,
        text=text,
        playlist_id=playlist_id,
        playlist_name=playlist_name,
        playlist_url=playlist_url,
        playlist_image_url=playlist_image_url,
        is_public=is_public,
    )
    db.add(entry)
    db.flush()

    for image in images:
        if not image.filename:
            continue
        suffix = Path(image.filename).suffix
        stored_name = f"{uuid.uuid4().hex}{suffix}"
        dest = UPLOADS_DIR / stored_name
        with dest.open("wb") as f:
            f.write(image.file.read())
        db.add(EntryImage(entry_id=entry.id, filename=stored_name))

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
    if entry.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="You do not own this entry")

    if payload.text is not None:
        entry.text = payload.text
    if payload.is_public is not None:
        entry.is_public = payload.is_public

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
    if entry.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="You do not own this entry")
    for image in entry.images:
        image_path = UPLOADS_DIR / image.filename
        image_path.unlink(missing_ok=True)
    db.delete(entry)
    db.commit()
