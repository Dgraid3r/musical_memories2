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

For the exact current data model, permissions, and API shape behind all
of the above, see [`ARCHITECTURE.md`](ARCHITECTURE.md); for the setup
and command reference, see [`README.md`](README.md).

## Planned

Discussed but not yet built. No commitments on order or timing here —
this section exists so the next priority conversation has a starting
list, not a blank page.

- **A real invite flow.** Today, adding someone to a workspace means an
  owner typing their existing username directly — there's no
  email-based invitation, no accept/decline step, and no way to invite
  someone who doesn't already have an account.
- **Email verification.** Registration doesn't currently confirm that a
  user actually owns the email address they signed up with.
- **Password reset.** There's no self-service way to recover an account
  if a password is forgotten — today that would require direct database
  access.
- **Workspace ownership transfer.** A workspace's owner can't currently
  hand ownership to someone else, or step down, which also means an
  owner can't remove themselves from a workspace they created.
- **Spotify API quota headroom.** The app currently shares one Spotify
  developer app's rate limits across every user of every workspace. As
  real usage grows, this needs to be actively watched (the app-only
  catalog search cache already logs cache hit/miss rates for exactly this
  purpose — see [`ARCHITECTURE.md`](ARCHITECTURE.md)) and mitigated before
  it becomes a real ceiling, likely through some combination of a larger
  Spotify API quota tier and smarter caching.
- **Photo storage off local disk.** Uploaded photos currently live as
  files on the backend server's own disk. That doesn't survive a
  redeploy to a fresh machine and doesn't scale past one server — moving
  to object storage (e.g. S3-compatible storage) is the natural next
  step once the app needs to run somewhere more durable than a single
  machine.
- **Containerized deployment and CI.** The backend and frontend aren't
  yet packaged to run anywhere beyond a developer's own machine (Postgres
  already runs in Docker via `docker-compose.yml`, but the app itself
  doesn't), and there's no automated pipeline that runs the test suite
  and build on every change.
- **Automated backups and uptime monitoring.** Once this runs anywhere
  other than a laptop, it needs a real backup strategy for the database
  and photo storage, plus monitoring that notices — and alerts someone —
  if the app goes down.
