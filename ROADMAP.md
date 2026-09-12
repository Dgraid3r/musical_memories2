# Roadmap

This is a living document — a snapshot of what's shipped and what's
planned, meant to be edited as things land or priorities change. It's not
a fixed spec; if something here is stale, fix the doc rather than treat it
as gospel.

## Shipped

Roughly in the order it landed:

1. **Initial scaffold.** FastAPI backend, React/TypeScript/Vite frontend,
   Spotipy-powered playlist search — the basic shape of the app before any
   accounts existed.
2. **Local accounts and ownership.** JWT-based username/password login,
   per-user entry ownership, and the first public/private entry
   distinction.
3. **Co-authors and date ranges.** Entries gained a primary author plus
   any number of co-authors with content-edit (but not
   visibility/deletion) rights, and multi-day entries alongside
   single-day ones.
4. **Postgres, tags, full-text search, and Spotify OAuth linking.** The
   database moved off SQLite onto Postgres with Alembic migrations (see
   [`ARCHITECTURE.md`](ARCHITECTURE.md) for why); entries gained free-text
   tags and Postgres-native full-text search; users gained the ability to
   separately connect their own Spotify account and browse their own
   playlists.
5. **Threaded comments and Spotify search caching.** Entries gained
   nested/threaded commenting with author- and primary-author-level
   permissions; the public catalog search gained an in-memory TTL cache.
6. **The workspace model, plus a first pass of security hardening.**
   Entries, tags, and comments became scoped to isolated workspaces with
   owner/member roles and multi-workspace membership; alongside that,
   Spotify tokens were encrypted at rest, login/registration became
   rate-limited, structured logging and optional Sentry error tracking
   were added, and outbound Spotify API calls got logged for visibility.
7. **Public/private workspace visibility and the subscriber role.**
   Workspaces gained an owner-controlled public/private toggle (with a
   dedicated no-login discovery/browse endpoint for public ones) and a
   third, read-only membership role (subscriber), alongside the
   "inaccessible reads as not-found" non-disclosure pattern being
   extended to cover fully anonymous requests.
8. **Real invites, email verification, and password reset.** Joining a
   workspace became a real, consent-based flow — an owner invites by
   email, and the invitee accepts (or registers, if they had no
   account) — replacing an owner unilaterally adding an existing
   username. Registration sends a verification email (tracked via
   `User.email_verified`, though nothing in the app enforces it yet),
   and a forgotten password can be reset self-service via an emailed,
   single-use, time-limited token instead of requiring direct database
   access.
9. **Workspace ownership transfer and account deletion.** A workspace
   owner can hand ownership to another existing member
   (`PATCH /api/workspaces/{id}/transfer-ownership`), and a user can
   permanently delete their own account (`DELETE /api/account`), which
   anonymizes their identifying fields in place while leaving every
   entry/comment they authored untouched under a "Deleted user" label.
10. **Photo storage off local disk.** Uploaded photos moved to a
    pluggable storage backend — local disk by default (unchanged, zero
    setup), or any S3-compatible object storage (AWS S3, Cloudflare R2,
    Backblaze B2, etc.) once configured — with a one-time script to
    migrate already-uploaded local files over.
11. **Containerized deployment, CI, and automated backups.** The app
    now builds as a single Docker image (frontend + backend served
    together) deployable to Railway or any Docker host — see
    [`DEPLOYMENT.md`](DEPLOYMENT.md) — with GitHub Actions CI running
    the full backend test suite and frontend build on every push/PR
    against `master`/`staging`, a scheduled backup script (`pg_dump`,
    gzip-compressed, to object storage or a local fallback, with
    configurable retention), and a `GET /api/health` endpoint any
    uptime monitor can point at.
12. **Geotagging, Google Sign-In, and the admin dashboard.** An entry
    can carry an optional location (latitude/longitude/name, via a
    backend-proxied OpenStreetMap Nominatim search — no third-party API
    key ever reaches the browser); a user can sign in or register with
    Google instead of a local password (additive to local login — see
    [`ARCHITECTURE.md`](ARCHITECTURE.md)); and a small site-wide admin
    dashboard (`/api/admin/*`, granted via `scripts/grant_admin.py`)
    gives user management (list/deactivate/reactivate) and operational
    visibility (user/workspace/entry counts, signup trends, latest
    backup status).
13. **Further concurrency and security hardening.** On top of item 6's
    first pass: fixed a handful of real races under concurrent load
    (two simultaneous ownership transfers, two simultaneous new-tag
    creations, two simultaneous invite accepts), closed a path-traversal
    hole in the production SPA-fallback route, bound Google sign-in's
    CSRF state to the requesting browser, replaced a SQL-wildcard-
    injection-prone email lookup with an exact match against normalized
    (lowercased) stored emails, added a type-allowlist and size cap to
    entry-photo uploads, stopped password-reset/verification/invite
    tokens from ever reaching plaintext logs, and added a dedicated test
    that catches structural drift between the SQLAlchemy models and the
    Alembic migration chain before it reaches a real deployment.

For the exact current data model, permissions, and API shape behind all
of the above, see [`ARCHITECTURE.md`](ARCHITECTURE.md); for the setup
and command reference, see [`README.md`](README.md).

## Planned

Nothing concrete is currently planned as a new feature build. The one
ongoing (not actively-worked-on) concern being watched rather than
built is **Spotify API quota headroom**: the app shares one Spotify
developer app's rate limits across every user of every workspace, and
as real usage grows this needs watching (the app-only catalog search
cache already logs cache hit/miss rates for exactly this purpose — see
[`ARCHITECTURE.md`](ARCHITECTURE.md)) and mitigating before it becomes
a real ceiling — likely some combination of a larger Spotify API quota
tier and smarter caching, if and when it's actually needed.
