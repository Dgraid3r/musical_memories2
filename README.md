# Musical Memories

A local journal that ties entries — a date, a note, optional photos — to a
Spotify playlist. The music side of an entry is always a playlist, even when
it's really just one song (make a single-track playlist in Spotify for that
case).

## Stack

- **Backend** — Python, FastAPI, SQLAlchemy (SQLite), Spotipy
- **Frontend** — React + TypeScript (Vite)

## Spotify API

Playlist search uses Spotipy's client-credentials flow (app-only auth —
no user login), which is enough to search Spotify's public catalog of
playlists. Register an app at https://developer.spotify.com/dashboard,
then copy `backend/.env.example` to `backend/.env` and fill in
`SPOTIFY_CLIENT_ID` / `SPOTIFY_CLIENT_SECRET`.

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
