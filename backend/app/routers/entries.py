import uuid
from datetime import date
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import EntryImage, JournalEntry
from ..schemas import JournalEntryOut

router = APIRouter(prefix="/api/entries", tags=["entries"])

UPLOADS_DIR = Path(__file__).resolve().parent.parent.parent / "uploads"
UPLOADS_DIR.mkdir(exist_ok=True)


@router.get("", response_model=list[JournalEntryOut])
def list_entries(db: Session = Depends(get_db)):
    stmt = select(JournalEntry).order_by(JournalEntry.entry_date.desc(), JournalEntry.id.desc())
    return db.scalars(stmt).all()


@router.get("/{entry_id}", response_model=JournalEntryOut)
def get_entry(entry_id: int, db: Session = Depends(get_db)):
    entry = db.get(JournalEntry, entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Entry not found")
    return entry


@router.post("", response_model=JournalEntryOut, status_code=201)
def create_entry(
    entry_date: date = Form(...),
    text: str | None = Form(None),
    playlist_id: str = Form(...),
    playlist_name: str = Form(...),
    playlist_url: str = Form(...),
    playlist_image_url: str | None = Form(None),
    images: list[UploadFile] = File(default=[]),
    db: Session = Depends(get_db),
):
    entry = JournalEntry(
        entry_date=entry_date,
        text=text,
        playlist_id=playlist_id,
        playlist_name=playlist_name,
        playlist_url=playlist_url,
        playlist_image_url=playlist_image_url,
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


@router.delete("/{entry_id}", status_code=204)
def delete_entry(entry_id: int, db: Session = Depends(get_db)):
    entry = db.get(JournalEntry, entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Entry not found")
    for image in entry.images:
        image_path = UPLOADS_DIR / image.filename
        image_path.unlink(missing_ok=True)
    db.delete(entry)
    db.commit()
