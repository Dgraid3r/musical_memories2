# Musical Memories

A multi-tenant journal that ties entries — a date (or date range), a note,
optional photos — to a Spotify playlist. The music side of an entry is
always a playlist, even when it's really just one song (make a
single-track playlist in Spotify for that case).

Entries live in **workspaces** — separate, isolated groups (e.g. one
family's journal vs. a friend group's). A user account can belong to
several workspaces at once (a switcher, not a single fixed group per
account); the app UI lets you pick which one is active. Within a
workspace, each entry is private by default and can be made public;
"public" means visible to every member of that entry's workspace, not the
whole app. The entry list shows every public entry in the active
workspace plus your own private ones there and any private ones you're a
co-author on.

Each entry has one primary author (who can toggle public/private, manage
co-authors, and delete it) and any number of co-authors (who can edit the
text, tags, and photos, same as the primary author, but not change
visibility, manage co-authors, or delete) - co-authors must already be
members of the entry's workspace. A single-day entry has its start and end
date equal; the frontend collapses that to one displayed date instead of a
range.

Entries can carry free-text tags (unique per workspace, not globally), and
both entry text and tags are indexed for full-text search within a
workspace.

## Stack

- **Backend** — Python, FastAPI, SQLAlchemy (Postgres), Alembic migrations, Spotipy, JWT auth (PyJWT + bcrypt)
- **Frontend** — React + TypeScript (Vite)

Everything below is for running the app **locally**. To put it on the
real internet, see **[DEPLOYMENT.md](DEPLOYMENT.md)** for the full
step-by-step guide (Railway hosting + Cloudflare R2 storage).

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

## Workspaces

`Workspace`: id, name, created_at, created_by. Membership is a separate
table with a role - `owner` (created it; can invite/remove members and
delete the workspace) or `member` (everything else: create entries,
comment, etc.) - the same owner/member asymmetry already used for an
entry's primary author vs. co-authors.

Endpoints: `POST /api/workspaces` (create - you become its owner),
`GET /api/workspaces` (list your own, with your role in each),
`GET /api/workspaces/{id}/members`, `DELETE
/api/workspaces/{id}/members/{user_id}` (owner-only; the owner can't
remove themselves this way - delete the whole workspace instead),
`DELETE /api/workspaces/{id}` (owner-only, cascades to every
entry/tag/comment in it). Joining a workspace is a real, consent-based,
email invite flow rather than an owner unilaterally adding an existing
username - see "Invites, email verification, and password reset" below.

An owner can hand ownership to another existing member with `PATCH
/api/workspaces/{id}/transfer-ownership` (body `{"new_owner_user_id":
...}`) - the target must already be a member (not a pending invite), and
the change is immediate with no accept step, since this is meant for
already-trusted collaborators rather than the invite flow's consent
model. Atomic: the old owner becomes a plain member and the target
becomes owner in the same transaction, so a workspace always has exactly
one owner.

Every entry/tag/comment/search endpoint is nested under the workspace:
`GET/POST /api/workspaces/{id}/entries`, `GET/PATCH/DELETE
/api/workspaces/{id}/entries/{entry_id}`, `GET/POST
/api/workspaces/{id}/entries/{entry_id}/comments`, etc. (see "API" below).
A workspace you're not a member of is indistinguishable from one that
doesn't exist - every one of these routes 404s rather than 403s, the same
non-disclosure rule already used for a private entry you can't see.

**Upgrading an existing installation:** migration `0005` creates one
"Default" workspace, adds every existing user as a member of it (the
earliest-registered user becomes its owner, everyone else a member), and
re-points every existing entry and tag at it. A pre-existing public entry
keeps exactly the visibility it had before - every user who could already
see it is now a member of the one workspace holding it.

## Full-text search and tags

Entries can have any number of free-text tags (typing a new one creates it;
typing an existing one reuses it), unique per workspace - two different
workspaces can each have their own "roadtrip" tag. `GET
/api/workspaces/{id}/entries` accepts two optional query params, both
respecting the normal entry visibility rule (public entries in this
workspace, plus your own private ones, plus private ones you co-author):

- `q=<text>` — full-text search across entry text and tag names, using
  Postgres's native `tsvector`/`websearch_to_tsquery` (not `ILIKE`),
  ranked by relevance. The `search_vector` column is kept in sync by a
  Postgres trigger (see `backend/app/models.py`) whenever an entry's text
  or tags change, and is backed by a GIN index.
- `tag=<name>` — filter to entries carrying that exact tag.

`GET /api/workspaces/{id}/entries/tags` lists every tag currently in use in
that workspace, across entries visible to the caller, for autocomplete.

## Entry photos

Photos attach to an entry via `POST /api/workspaces/{id}/entries` (at
creation) or `POST /api/workspaces/{id}/entries/{entry_id}/images` (added
later). Fetching one back is `GET
/api/entries/{entry_id}/images/{image_id}` - deliberately not a raw static
file URL. This endpoint enforces the exact same visibility rule as the
entry itself (public, your own, or co-authored) before ever serving or
redirecting to the image; an entry you can't see gives the same 404 for
its photos as for the entry. There is exactly one path to a photo's
bytes, and it's permission-checked.

**Storage backend** — pluggable, the same opt-in pattern as
`SENTRY_DSN`/`SMTP_HOST`: leave `OBJECT_STORAGE_ENDPOINT_URL` unset in
`backend/.env` and photos save to and serve from local disk
(`backend/uploads/`), exactly as before - zero cost, zero signup. Set
`OBJECT_STORAGE_ENDPOINT_URL`/`OBJECT_STORAGE_BUCKET`/
`OBJECT_STORAGE_ACCESS_KEY`/`OBJECT_STORAGE_SECRET_KEY` (see
`backend/.env.example`) to switch to any S3-compatible object storage
instead - AWS S3, Cloudflare R2, Backblaze B2, or a local MinIO container
for dev/testing all work unmodified, since this is built against the
generic S3 API rather than an AWS-specific SDK path. Cloudflare R2 is a
reasonable low-cost pick for personal-scale use (no egress fees), but
nothing here is R2-specific.

With object storage configured, a fetch redirects to a short-lived
(5-minute) presigned URL generated only after the visibility check above
passes - the bucket itself never needs to be public, and a leaked or
cached link stops working shortly after.

**Migrating existing local photos:** configuring object storage doesn't
touch photos already on local disk - nothing changes for them until you
run `python -m scripts.migrate_uploads_to_object_storage` from `backend/`
(add `--dry-run` to preview first). It uploads each local file under its
existing filename, so no database changes are needed - the app just
starts serving them from object storage the next time they're requested,
because it already prefers object storage over local disk whenever it's
configured. Not run automatically, and never required; local copies are
left in place afterward so you can double-check before removing them
yourself.

## Spotify API

Playlist search (the picker on the entry form) uses Spotipy's
client-credentials flow (app-only auth — no user login), which is enough to
search Spotify's public catalog of playlists. Register an app at
https://developer.spotify.com/dashboard, then copy `backend/.env.example`
to `backend/.env` and fill in `SPOTIFY_CLIENT_ID` / `SPOTIFY_CLIENT_SECRET`.

**Rate-limit handling** — every outbound Spotify call (search, per-user
playlist calls, OAuth token exchange/refresh) retries a `429` with capped
backoff (honoring `Retry-After` when Spotify sends one, but always bounded
to a few seconds and a small number of attempts, so a request never hangs
waiting on Spotify). Once retries are exhausted, the API returns a clean
`503` ("Spotify is temporarily unavailable, try again shortly") instead of
a raw error. The shared app-only search client (used by every user's
searches) also throttles its own outbound call rate slightly, to make
tripping Spotify's limit in the first place less likely.

The throttle assumes personal/light traffic: its default,
`SPOTIFY_SEARCH_MIN_INTERVAL_SECONDS=0.1` (a 10 req/s ceiling on the shared
search client, configurable in `backend/.env`), is generous headroom for
occasional, sparse use, where real traffic is nowhere near that ceiling.
Spotify doesn't publish an exact limit, but the commonly-observed
unofficial one is closer to ~6 req/s sustained (roughly 180 requests per
rolling 30-second window) - so as usage scales up to many concurrent
users, this default could still be tight enough to trip real `429`s under
sustained heavy load (the retry logic above keeps things working either
way, just less efficiently than avoiding the 429 in the first place). The
concurrency behavior of the throttle itself (a `threading.Lock` serializing
every call under FastAPI's threadpool) is covered by
`backend/tests/test_spotify_throttle.py`'s burst test, so it's confirmed
safe as concurrent load grows - what changes with scale is only whether
the *interval* is tight enough, not whether it's thread-safe. The signal
to tighten it: frequent `spotify.rate_limit_exhausted` lines in the logs
(or Sentry, if configured) mean the current interval is no longer enough
headroom for real traffic - lower `SPOTIFY_SEARCH_MIN_INTERVAL_SECONDS`
(e.g. to `0.2` for a ~5 req/s ceiling) and redeploy, no code change
needed. If that stops being enough on its own, that's the point to
revisit this more substantially (e.g. a shared cross-process limiter),
but nothing like that exists yet.

### Connecting your own Spotify account (optional)

Separately, a logged-in user can link their own Spotify account (Authorization
Code flow) to browse their own playlists from the entry form's "My playlists"
tab. This is additive on top of local login - it does not replace or change
how you sign in to this app, and it's not workspace-scoped (your linked
Spotify account is yours across every workspace you belong to).

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
`GET /api/spotify/me/playlists`. The linked access/refresh tokens are
encrypted at rest (see "Security and operations" below), stored
server-side, and refreshed automatically when expired; they're never
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
persists the token in the browser. Both endpoints are rate-limited to 5
attempts/minute per caller IP (see "Security and operations").

## Invites, email verification, and password reset

Creating an account is open to anyone (it's already rate-limited - see
"Security and operations"); an invite is only required to join a specific
*workspace*.

- **Workspace invites** — a workspace owner invites by email address:
  `POST /api/workspaces/{id}/invites` (owner-only; 409s if that email is
  already a member or already has a pending invite), `GET
  /api/workspaces/{id}/invites` (owner-only, lists pending invites),
  `DELETE /api/workspaces/{id}/invites/{invite_id}` (owner-only, revokes
  before acceptance). Each invite emails an accept link/token that expires
  after 7 days. `GET /api/invites/{token}` (no auth) previews an invite
  (workspace name, role, whether the email already has an account) so the
  frontend can route to login or registration. `POST
  /api/invites/{token}/accept` (auth required, rate-limited) accepts it -
  membership is only ever created when the invitee actively accepts, never
  automatically by the owner. If the invited email doesn't have an account
  yet, `POST /api/users` (register) optionally takes an `invite_token` and
  auto-joins the new account to that workspace as part of registration
  itself, rather than requiring a separate accept step after
  registering - one flow, not two mechanisms bolted together. An invalid,
  expired, or mismatched-email invite token passed at registration is
  silently ignored (registration still succeeds; it just doesn't join a
  workspace).
- **Email verification** — registration sends a verification email
  (`POST /api/account/verify-email/{token}`, no auth, token from the
  email); `User.email_verified` tracks status (`GET /api/users/me`).
  **Nothing in the app currently requires verification** - an unverified
  account logs in and uses every feature normally. `POST
  /api/account/verify-email/resend` (auth required, rate-limited)
  re-sends with a fresh token, replacing the previous one.
- **Password reset** — `POST /api/account/password-reset/request` (no
  auth, rate-limited, body `{"email": ...}`) always returns the same
  generic response whether or not that email has an account, so it can't
  be used to probe which emails are registered. If it does, an emailed
  token (1 hour) can be submitted via `POST
  /api/account/password-reset/{token}` (body `{"new_password": ...}`) to
  set a new password; the token is single-use and requesting a new reset
  invalidates any earlier still-unused one.

## Security and operations

- **Spotify tokens encrypted at rest** — `SpotifyToken.access_token`/
  `refresh_token` are encrypted in Postgres (Fernet), keyed by
  `TOKEN_ENCRYPTION_KEY` in `backend/.env` - required, generate one with:
  ```
  python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
  ```
  (this is a different key format than `JWT_SECRET_KEY` - don't reuse the
  `secrets.token_hex` command for it).
- **Entry photos are permission-checked, not a public static file** —
  `GET /api/entries/{entry_id}/images/{image_id}` is the only way to fetch
  a photo, and it enforces the exact same visibility rule as the entry
  itself before serving or redirecting to it. There is no raw
  `/uploads/...` static route (there used to be - it served any file to
  anyone who had or guessed its filename, regardless of the owning
  entry's or workspace's privacy). See "Entry photos" above.
- **Rate limiting** — `POST /api/sessions`, `POST /api/users`, `POST
  /api/invites/{token}/accept`, `POST /api/account/verify-email/resend`,
  `POST /api/account/password-reset/request`, and `POST
  /api/account/password-reset/{token}` are each limited to 5
  attempts/minute per caller IP (independent budgets - maxing out one
  doesn't affect another), to blunt brute-forcing and credential
  stuffing/enumeration. Returns `429` with a `{"detail": "..."}` body.
  Invite *creation* isn't rate-limited since it's already owner-gated.
- **Error tracking (optional)** — set `SENTRY_DSN` in `backend/.env` and/or
  `VITE_SENTRY_DSN` in `frontend/.env` to send errors to Sentry. Leaving
  either unset is a complete no-op, not a startup failure - there's no
  Sentry account configured by default.
- **Outgoing email (optional)** — set `SMTP_HOST` (plus `SMTP_PORT`/
  `SMTP_USER`/`SMTP_PASSWORD`/`SMTP_FROM_ADDRESS`) in `backend/.env` to
  send invite, verification, and password-reset emails through any real
  SMTP provider - a personal Gmail account works fine for local use
  (`smtp.gmail.com`, port `587`, an
  [App Password](https://myaccount.google.com/apppasswords) as
  `SMTP_PASSWORD`). Leaving `SMTP_HOST` unset is the same no-op pattern as
  `SENTRY_DSN`: nothing fails, sending just logs the email's recipient,
  subject, and body (including the real link/token) instead of actually
  delivering it - enough to develop and test invites/verification/reset
  locally with no mail setup at all.
- **Structured logging** — the backend logs auth failures/successes,
  Spotify API calls (catalog search and the per-user OAuth client - query,
  cache hit/miss, result counts, refresh events), and other operationally
  relevant events via Python's standard `logging`, not prints. Verbosity is
  controlled by `LOG_LEVEL` in `backend/.env` (default `INFO`).

## Backups and monitoring

The app is deployment-ready (see [DEPLOYMENT.md](DEPLOYMENT.md) for the
full Railway + Cloudflare R2 guide) but hasn't necessarily actually been
deployed yet - whether it's live anywhere depends on whether that guide
has been run. Either way, what's here works identically against whatever
Postgres instance `DATABASE_URL` points at - the local docker-compose one
during development, or a real deployed one in production - without
anything cloud-provider-specific baked in.

### Backups

`python -m scripts.backup_database` (from `backend/`) dumps the database
(`pg_dump`, gzip-compressed) and stores it:

- **Object storage (recommended)** — when `OBJECT_STORAGE_*` is
  configured (see "Entry photos" above; the same config, same S3-compatible
  abstraction, reused rather than reinvented), the dump uploads under a
  `backups/` prefix in the same bucket.
- **Local disk (fallback)** — when it isn't, the dump saves to
  `backend/backups/` instead. **This is not a real safety net.** A
  backup sitting on the same machine (often the same disk) as the
  database it backs up survives a bad migration or an accidental
  `DROP`, but not a lost/corrupted disk, a stolen machine, or the whole
  docker-compose volume being wiped. It's useful for exercising the
  mechanism end to end - and gives the daily sidecar below something to
  actually do before you've configured object storage - but treat it as
  a smoke test, not protection. Configure `OBJECT_STORAGE_*` for the
  real thing.

Backups older than `BACKUP_RETENTION_DAYS` (`backend/.env`, default 30)
are deleted after each run - the same policy either way, based on the
timestamp encoded in each backup's own filename rather than storage
metadata.

Failures are logged at `ERROR` level (`backup.dump_failed`,
`backup.save_failed`), the same as every other failure path in this
app - loud, not silent, and automatically forwarded to Sentry once
`SENTRY_DSN` is configured (see "Security and operations" above; no
extra wiring needed, it's the same `LoggingIntegration` every other
error already goes through).

**Restoring:**

```
# From a local file
python -m scripts.restore_database backend/backups/backup_20260101T000000Z.sql.gz

# From object storage - most recent backup, or a specific one with --key
python -m scripts.restore_database --from-object-storage
python -m scripts.restore_database --from-object-storage --key backups/backup_20260101T000000Z.sql.gz

# Into a database other than DATABASE_URL
python -m scripts.restore_database <file> --database-url postgresql://user:pass@host:5432/dbname
```

Restoring pipes the decompressed dump into `psql` against the target -
normally a **fresh, empty** database created for exactly this purpose,
not the live one still serving traffic, since the script doesn't drop
or clear anything first.

`pg_dump`/`psql` are expected on `PATH` (as they would be on a real
deployed host with the Postgres client tools installed); override with
`PG_DUMP_COMMAND`/`PSQL_COMMAND` in `backend/.env` if that's not where
they live.

**Automatic daily scheduling (current docker-compose setup):** an
opt-in `backup` service is defined in the project-root
`docker-compose.yml`, built from `backend/Dockerfile.backup` (same
Postgres client version as the `postgres` service, with just enough
Python to run the backup script - not the full app image). It isn't
part of the default `docker compose up -d` set, so ordinary local
dev/testing doesn't pay for building it - start it explicitly:

```
docker compose --profile backup up -d backup
```

It runs one backup immediately, then repeats every
`BACKUP_INTERVAL_SECONDS` (default a day). This is deliberately a
simple sleep loop, not a real cron daemon - enough for "keep it simple"
at local/personal scale. **Once real hosting is chosen**, prefer that
platform's own cron/scheduled-job feature (most PaaS/hosting providers
have one) instead of this sidecar, or switch to genuine cron if you're
managing a server yourself - either way, the underlying command is the
same: `python -m scripts.backup_database` with `DATABASE_URL` and (for
real protection) `OBJECT_STORAGE_*` configured.

### Monitoring

`GET /api/health` actually checks the database (`SELECT 1`) rather than
unconditionally claiming ok - it returns `{"status": "ok"}` (`200`) when
Postgres is reachable, or `{"status": "unhealthy", ...}` (`503`) when it
isn't, logging the failure the same way everything else in this app
does.

**Once the app is deployed somewhere reachable from the internet** (see
[DEPLOYMENT.md](DEPLOYMENT.md) if that hasn't happened yet), point an
uptime monitor at `https://<your-domain>/api/health`. A free tier of a service like
[UptimeRobot](https://uptimerobot.com/) or
[Better Stack](https://betterstack.com/uptime) is plenty for a
personal-scale app: create an HTTP(S) monitor, point it at that URL, and
have it alert on anything other than a `200` (or on the request timing
out). Nothing about `/api/health` requires a specific provider - any
monitor that can hit a URL and check the status code works.

## API

REST resources: `POST /api/users` (register, optional `invite_token`),
`GET /api/users/me`, `GET /api/users?q=` (global username search),
`POST /api/sessions` (login).

Account: `POST /api/account/verify-email/resend`, `POST
/api/account/verify-email/{token}`, `POST
/api/account/password-reset/request`, `POST
/api/account/password-reset/{token}`, `DELETE /api/account` (permanently
delete your own account - see "Invites, email verification, and password
reset" and "Workspaces" above for the blocking/cascade rules).

Google Sign-In (additive to local login above - see
[ARCHITECTURE.md](ARCHITECTURE.md) for how and why): `GET
/api/auth/google/config` (no auth - whether the button should show),
`GET /api/auth/google/login` (starts the redirect to Google), `GET
/api/auth/google/callback` (Google's own redirect target - not
something you call directly).

Workspaces: `POST/GET /api/workspaces`, `GET /api/workspaces/public`
(no auth - browse/discover public workspaces, optional `q=`/`sort=`/
`limit=`/`offset=`), `PATCH /api/workspaces/{id}` (owner-only, toggle
public/private), `GET /api/workspaces/{id}/members`, `PATCH
/api/workspaces/{id}/members/{user_id}` (owner-only, set a member's role
to member/subscriber), `DELETE /api/workspaces/{id}/members/{user_id}`,
`DELETE /api/workspaces/{id}`, `PATCH
/api/workspaces/{id}/transfer-ownership`, `POST/GET
/api/workspaces/{id}/invites`, `DELETE
/api/workspaces/{id}/invites/{invite_id}`.

Invites (not workspace-nested - the token alone resolves it): `GET
/api/invites/{token}` (preview, no auth), `POST /api/invites/{token}/accept`.

Workspace-scoped (see "Workspaces" above - every one of these requires
membership in `{id}`): `GET/POST /api/workspaces/{id}/entries` (optional
`q=`/`tag=` on GET), `GET/PATCH/DELETE /api/workspaces/{id}/entries/{entry_id}`,
`GET /api/workspaces/{id}/entries/{entry_id}/edit-history` (who changed
what, when - an audit log, not version history/restore), `POST
/api/workspaces/{id}/entries/{entry_id}/images` (add photos to an
existing entry), `GET /api/workspaces/{id}/entries/tags` (tags in use),
`GET/POST /api/workspaces/{id}/entries/{entry_id}/comments`.

Not workspace-nested (the id alone is enough to resolve which workspace
applies, via the owning entry): `PATCH/DELETE /api/comments/{id}`,
`GET /api/entries/{entry_id}/images/{image_id}` (see "Entry photos" above
- the only way to fetch a photo's bytes, permission-checked the same as
the entry itself).

Spotify: `GET /api/spotify/playlists?q=` (public catalog search) and the
account-linking endpoints described above.

Places (no auth - see `backend/app/routers/places.py`; backend-proxied
OpenStreetMap Nominatim, used by an entry's optional location field):
`GET /api/places/search?q=`, `GET /api/places/reverse?lat=&lon=`.

Admin (site-wide, requires `User.is_admin` - granted with
`python -m scripts.grant_admin <username>` from `backend/`, never a web
endpoint, since the first admin can't grant themselves through one - see
[ARCHITECTURE.md](ARCHITECTURE.md)): `GET /api/admin/users` (optional
`q=`/`limit=`/`offset=`), `POST /api/admin/users/{user_id}/deactivate`,
`POST /api/admin/users/{user_id}/reactivate`, `GET /api/admin/stats`
(user/workspace/entry counts, signup trends, latest backup status).

`GET /api/health` (no auth) - see "Backups and monitoring" above.

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
frontend proxies `/api` to the backend on port 8000.

## Tests

From `backend/`, with the Postgres container running (`docker compose up -d`
from the project root - the test suite talks to the `musical_memories_test`
database in the same container, not the dev one):

```
pytest
```

From `frontend/`: `npm run lint` and `npm run build` (the build itself
type-checks via `tsc -b` first).

`.github/workflows/ci.yml` runs all of the above automatically on every
push and pull request against `master` or `staging` (backend migrations
+ tests against a real Postgres service container, frontend lint +
build) - nothing extra to run by hand before opening a PR, though
running them locally first is still the fastest way to catch a problem.
See `DEPLOYMENT.md`'s "Staging environment" section for what `staging`
is and how it fits into the deploy workflow.
