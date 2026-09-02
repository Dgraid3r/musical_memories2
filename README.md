# Musical Memories

A local, multi-user journal that ties entries — a date (or date range), a
note, optional photos — to a Spotify playlist. The music side of an entry is
always a playlist, even when it's really just one song (make a single-track
playlist in Spotify for that case). Each entry is private by default and can
be made public; the entry list shows everyone's public entries plus your own
private ones and any private entries you're a co-author on.

Each entry has one primary author (who can toggle public/private, manage
co-authors, and delete it) and any number of co-authors (who can edit the
text, tags, and photos, same as the primary author, but not change
visibility, manage co-authors, or delete). A single-day entry has its start
and end date equal; the frontend collapses that to one displayed date
instead of a range.

Entries can carry free-text tags, and both entry text and tags are indexed
for full-text search.

## Stack

- **Backend** — Python, FastAPI, SQLAlchemy (Postgres), Alembic migrations, Spotipy, JWT auth (PyJWT + bcrypt)
- **Frontend** — React + TypeScript (Vite)

## Database (Postgres)

The backend requires Postgres - there is no SQLite fallback. A
`docker-compose.yml` at the project root brings up a local instance:

```
docker compose up -d
```

This creates two databases in the container: `musical_memories` (dev data,
in the persistent `postgres_data` volume) and `musical_memories_test` (used
only by the backend test suite, so `pytest` never touches your journal
entries).

Then, from `backend/`, with `DATABASE_URL` set in `.env` (see
`.env.example` - the default already matches the compose service):

```
alembic upgrade head
```

Run that again any time you pull a change that adds a migration. Schema is
owned entirely by Alembic now - the app no longer auto-creates tables on
startup.

## Full-text search and tags

Entries can have any number of free-text tags (typing a new one creates it;
typing an existing one reuses it). `GET /api/entries` accepts two optional
query params, and both respect the normal entry visibility rule (public
entries, plus your own private ones, plus private ones you co-author):

- `q=<text>` — full-text search across entry text and tag names, using
  Postgres's native `tsvector`/`websearch_to_tsquery` (not `ILIKE`),
  ranked by relevance. The `search_vector` column is kept in sync by a
  Postgres trigger (see `backend/app/models.py`) whenever an entry's text
  or tags change, and is backed by a GIN index.
- `tag=<name>` — filter to entries carrying that exact tag.

`GET /api/entries/tags` lists every tag currently in use across entries
visible to the caller, for autocomplete.

## Spotify API

Playlist search (the picker on the entry form) uses Spotipy's
client-credentials flow (app-only auth — no user login), which is enough to
search Spotify's public catalog of playlists. Register an app at
https://developer.spotify.com/dashboard, then copy `backend/.env.example`
to `backend/.env` and fill in `SPOTIFY_CLIENT_ID` / `SPOTIFY_CLIENT_SECRET`.

### Connecting your own Spotify account (optional)

Separately, a logged-in user can link their own Spotify account (Authorization
Code flow) to browse their own playlists from the entry form's "My playlists"
tab. This is additive on top of local login - it does not replace or change
how you sign in to this app.

To enable it:

1. In the same Spotify developer dashboard app used above, add a **Redirect
   URI** under Settings that matches `SPOTIFY_REDIRECT_URI` in
   `backend/.env` exactly (scheme, host, port, path, and trailing slash all
   have to match byte-for-byte) - by default that's
   `http://localhost:8000/api/spotify/callback`.
2. Set `SPOTIFY_REDIRECT_URI` (and optionally `FRONTEND_URL`, which the
   backend redirects back to once linking finishes) in `backend/.env`.
3. In the app, click "Connect Spotify" next to your username.

Endpoints: `GET /api/spotify/connect` (starts the flow; requires your local
JWT), `GET /api/spotify/callback` (Spotify's own redirect target - not
something you call directly), `GET /api/spotify/status`, and
`GET /api/spotify/me/playlists`. The linked access/refresh tokens are stored
server-side and refreshed automatically when expired; they're never
returned in any API response.

## Auth

Accounts are local to this app (username/email/password), not tied to
Spotify login (see "Connecting your own Spotify account" above for that
separate, optional feature). In `backend/.env`, also set `JWT_SECRET_KEY` —
generate one with:

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
`POST /api/sessions` (login), `GET/POST /api/entries` (optional `q=`/`tag=`
on GET), `GET/PATCH/DELETE /api/entries/{id}`,
`POST /api/entries/{id}/images` (add photos to an existing entry),
`GET /api/entries/tags` (tags in use), `GET /api/spotify/playlists?q=`
(public catalog search), and the Spotify account-linking endpoints
described above.

## Running locally

Bring up Postgres and run migrations (from the project root and
`backend/` respectively - see "Database" above):

```
docker compose up -d
cd backend && alembic upgrade head
```

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

## Tests

From `backend/`, with the Postgres container running (`docker compose up -d`
from the project root - the test suite talks to the `musical_memories_test`
database in the same container, not the dev one):

```
pytest
```
