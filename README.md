# Musical Memories

A local, multi-user journal that ties entries — a date (or date range), a
note, optional photos — to a Spotify playlist. The music side of an entry is
always a playlist, even when it's really just one song (make a single-track
playlist in Spotify for that case). Each entry is private by default and can
be made public; the entry list shows everyone's public entries plus your own
private ones and any private entries you're a co-author on.

Each entry has one primary author (who can toggle public/private, manage
co-authors, and delete it) and any number of co-authors (who can edit the
text and add photos, same as the primary author, but not change visibility,
manage co-authors, or delete). A single-day entry has its start and end date
equal; the frontend collapses that to one displayed date instead of a range.

## Stack

- **Backend** — Python, FastAPI, SQLAlchemy (SQLite), Spotipy, JWT auth (PyJWT + bcrypt)
- **Frontend** — React + TypeScript (Vite)

## Spotify API

Playlist search uses Spotipy's client-credentials flow (app-only auth —
no user login), which is enough to search Spotify's public catalog of
playlists. Register an app at https://developer.spotify.com/dashboard,
then copy `backend/.env.example` to `backend/.env` and fill in
`SPOTIFY_CLIENT_ID` / `SPOTIFY_CLIENT_SECRET`.

## Auth

Accounts are local to this app (username/email/password), not tied to
Spotify login. In `backend/.env`, also set `JWT_SECRET_KEY` — generate one
with:

```
python -c "import secrets; print(secrets.token_hex(32))"
```

Register via `POST /api/users`, log in via `POST /api/sessions` (returns a
bearer token), send it as `Authorization: Bearer <token>` on subsequent
requests. The frontend's login/register screen handles this for you and
persists the token in the browser.

## API

REST resources: `POST /api/users` (register), `GET /api/users/me`,
`GET /api/users?q=` (username search, for picking co-authors),
`POST /api/sessions` (login), `GET/POST /api/entries`,
`GET/PATCH/DELETE /api/entries/{id}`, `POST /api/entries/{id}/images`
(add photos to an existing entry), `GET /api/spotify/playlists?q=`.

Note: schema changes (co-authors, date range) mean a `musical_memories.db`
from before this point won't match the current models. Delete it and let
the backend recreate it fresh — there's no migration tooling yet, and no
real data to preserve at this stage.

## Running locally

Backend (from `backend/`):

```
python -m venv .venv
.venv/Scripts/activate   # .venv/bin/activate on macOS/Linux
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Frontend (from `frontend/`), in a second terminal:

```
npm install
npm run dev
```

Then open the Vite dev server URL (default `http://localhost:5173`). The
frontend proxies `/api` and `/uploads` to the backend on port 8000.
