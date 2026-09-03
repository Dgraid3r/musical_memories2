# Architecture

This document explains how Musical Memories is built, and — more
importantly — *why* it's built this way. It's written for someone who
knows what the app does but hasn't necessarily worked with these
particular tools before, so it explains the reasoning behind each
non-obvious choice, not just names it.

For "how do I run this" and the exact API endpoint list, see
[`README.md`](README.md) — this document is about design decisions, not
setup steps.

## The stack, and why each piece was picked

| Layer | Choice | The obvious alternative | Why this instead |
|---|---|---|---|
| Backend language/framework | Python + FastAPI | Node/Express, Django | FastAPI generates request validation and API documentation automatically from Python type hints, which keeps the codebase small and catches a whole category of "sent the wrong shape of data" bugs before they ever reach your code. Django would have been heavier than this app needs (it ships an admin panel, template engine, and ORM conventions this app doesn't use). |
| Database | PostgreSQL | SQLite (what this app actually started on) | SQLite is a single file on disk — great for a quick prototype, but it doesn't handle multiple people writing to the same data at once well, doesn't have real user accounts/permissions at the database level, and critically for this app, doesn't have the built-in full-text search and data-integrity features (like enforcing "a tag name must be unique within one workspace") that entries and search now depend on. Postgres is a real client-server database built for exactly this. See "Full-text search" below for the specific feature that made switching worth it. |
| Database access layer | SQLAlchemy | Writing raw SQL by hand | SQLAlchemy lets the Python code describe data as objects (a `JournalEntry` has a `.tags` list) instead of hand-writing SQL joins everywhere, while still allowing raw SQL for the handful of places (full-text search, the tag-sync triggers) where Postgres's own features are better than anything an object layer could express. |
| Schema migrations | Alembic | Just changing the code and hoping | Alembic is SQLAlchemy's companion tool for **migrations** — versioned, one-way instructions for changing a database's structure ("add this column," "create this table") that get applied in order and are safe to re-run. Without it, every change to what data looks like would mean manually running SQL against a live database and hoping every environment (your laptop, a teammate's laptop, production) stays in sync. There are 6 migrations in `backend/alembic/versions/` today, one per structural change the app has needed. |
| Spotify integration | Spotipy | Calling Spotify's HTTP API directly | Spotipy is a well-maintained Python wrapper around Spotify's Web API that handles the fiddly parts of authentication token exchange and refresh, so the app's own code stays focused on "what do we do with the playlist data" rather than "how do we sign this HTTP request." |
| Local login | PyJWT + bcrypt | Rolling your own session system, or a third-party auth provider (Auth0, Firebase Auth, etc.) | bcrypt is the standard way to store a password: it turns a password into a scrambled value that can be checked against but never reversed back into the original password, even if the database leaks. JWT ("JSON Web Token") is a signed, tamper-proof token the server hands the browser after login instead of a plaintext session cookie — the server can verify it's genuine without having to look anything up in a database on every request. A third-party auth provider would add an external dependency and a per-user cost for what a few dozen lines of well-understood code already does correctly for a small app like this. |
| Frontend | React + TypeScript + Vite | Plain JavaScript, or a server-rendered template | React lets the UI be built out of reusable pieces (a "component" per concept — an entry card, a comment thread) instead of one large tangle of DOM manipulation. TypeScript adds type-checking to JavaScript, which catches "you're passing the wrong shape of data to this component" mistakes before the code ever runs, the same benefit FastAPI's type hints give the backend. Vite is the build tool that turns that code into something a browser can run quickly, both during development (near-instant reload on save) and for the final production bundle. |

## The data model

Six kinds of things live in the database, plus two small helper tables.
Every one of the "content" tables — entries, tags, comments — ultimately
belongs to exactly one **workspace** (explained in its own section below),
which is what keeps different groups' journals from ever mixing.

### Users (`users`)

A registered account: username, email, a bcrypted password hash, and when
they signed up. Nothing else — no profile fields, no settings — lives on
the user record today.

### Workspaces (`workspaces`) and memberships (`workspace_memberships`)

A **workspace** is an isolated journal — "one family's journal" or "one
friend group's journal" are the running examples in the code and README.
A workspace has a name, who created it, when, and a `visibility` flag
(`public` or `private` — see "The workspace model" below).

**Membership** is its own table, separate from the workspace itself,
because a single person can belong to *several* workspaces (a family
journal and a separate friend-group journal, say), and a single workspace
has several members — this is a many-to-many relationship, which always
needs its own connecting table rather than a single column on either side.
Each membership row is one (user, workspace) pair plus a **role**:

- **owner** — created the workspace (or was made owner by... nothing yet;
  there's no ownership-transfer feature — see `ROADMAP.md`). Can invite and
  remove members, change a member's role, toggle the workspace between
  public and private, and delete the whole workspace.
- **member** — full read/write access: create entries, add photos, tag,
  comment, add co-authors. Everything except the owner-only powers above.
- **subscriber** — read-only. Can read every entry and comment a member
  can, but cannot create or change anything. This is how an owner shares a
  *private* workspace with someone as a viewer without making them a full
  collaborator.

### Journal entries (`journal_entries`)

The core content: a date (or date range — `start_date`/`end_date`, equal
for a single-day memory), an optional text note, a Spotify playlist
(id/name/URL/cover image — always a playlist, even for a single song, per
the product's own rule), and an `is_public` flag.

Every entry belongs to exactly one **primary author** (the `user_id`
column) and can have any number of **co-authors** (a separate
`entry_coauthors` join table, the same many-to-many pattern as workspace
membership). The primary author can toggle visibility, manage co-authors,
and delete the entry; co-authors can edit its text, tags, and photos, but
not those three things. Co-authors must already hold a write role (owner
or member) in the entry's workspace — a subscriber can never be added as
one, since that would hand them write access through the back door.

### Tags (`tags`) and the entry-tag link (`entry_tags`)

A tag is just a name, scoped to one workspace (`workspace_id` + `name`
together must be unique — see "Full-text search and tags" below for why).
`entry_tags` is the many-to-many join table connecting entries to tags,
the same pattern as co-authors and workspace membership.

### Comments (`comments`)

A threaded comment on an entry. "Threaded" means a comment can be a reply
to another comment (which can itself be a reply, arbitrarily deep) rather
than every comment being flat under the entry. That's implemented with a
single `parent_comment_id` column on the comment itself, pointing back at
its parent comment (or left empty for a top-level comment on the entry) —
a common, simple way to represent a tree of arbitrary depth in one table,
rather than a separate table per nesting level.

### Photos (`entry_images`)

One row per uploaded photo on an entry: which entry it belongs to, and the
filename it was saved under on local disk (see "What's next" in
`ROADMAP.md` for why "local disk" is a known limitation, not a permanent
design).

### Spotify tokens (`spotify_tokens`)

One row per user who has linked their own Spotify account (see "Two
separate auth systems" below) — the access and refresh tokens Spotify
issued them, encrypted (see "Security posture"). This table is
deliberately **not** scoped to a workspace: your own linked Spotify
account is yours everywhere you go in the app, not a per-workspace thing.

### How it fits together

```
User ──< WorkspaceMembership >── Workspace
  │                                  │
  │                                  ├──< Tag
  │                                  │
  ├──< JournalEntry >── (author) ────┘
  │         │
  │         ├──< EntryImage
  │         ├──< Comment ──(self, parent_comment_id)──> Comment
  │         └──(entry_coauthors)──< User (co-authors)
  │
  └── SpotifyToken (one-to-one, not workspace-scoped)
```

## Two separate auth systems, on purpose

The app has two independent ways it deals with "who is this," and they're
kept deliberately separate rather than merged into one:

1. **Local login** (username + password, described above) is how you get
   into the app at all. It's required for everything except reading a
   *public* workspace's entries (see below).
2. **Spotify account linking** (OAuth "Authorization Code" flow — the
   standard way a website asks *"can this app see your Spotify data,
   specifically yours"* and gets a token back from Spotify itself, rather
   than ever seeing your Spotify password) is optional and additive. It
   lets a logged-in user grant the app permission to read *their own*
   Spotify playlists, so the "pick a playlist" screen can offer "search
   my own playlists" alongside the public catalog search that already
   worked without it.

Why not just make Spotify login *be* the app's login? Because they answer
different questions. Local login answers "which account is this," and
doesn't require a Spotify account to exist at all — someone can use this
app to journal without ever connecting Spotify (playlist search still
works via the app's own catalog access, described next). Spotify linking
answers "has this account also granted us access to their own Spotify
library," which is optional, revocable, and unrelated to whether they can
log in. Bundling them together would mean nobody could use the app without
a Spotify account, and losing Spotify access (a revoked grant, an expired
token) would lock someone out of their own journal — a failure completely
unrelated to whether they remember their password.

There's also a third, unrelated Spotify credential: the app's own
**client-credentials** connection to Spotify (`SPOTIFY_CLIENT_ID`/
`SPOTIFY_CLIENT_SECRET`), which powers the public catalog search everyone
gets regardless of login. That's the app authenticating as *itself* to
Spotify, not as any particular user — it's what runs the playlist picker's
default search, and it's a completely separate code path
(`spotify_client.py`) from the per-user OAuth linking (`spotify_oauth.py`).

## The workspace model (multi-tenancy)

**Multi-tenancy** is the general term for "one running application serving
several separate groups of users who shouldn't see each other's data" —
in this app's case, separate journals for separate families or friend
groups, all using the same deployment.

### Why this exists

The app started as a single shared pool: every entry anyone made was
either visible to the whole app (`is_public`) or just to its author and
co-authors. That's fine for one group of people, but doesn't work once
two *unrelated* groups want to use the same installation — there'd be no
way to stop one family's private entries from being technically reachable
by (or worse, showing up mixed in with) a different friend group's. The
workspace model introduces a hard boundary: everything content-related —
entries, tags, comments — belongs to exactly one workspace, and every API
route that reaches content first checks whether the caller belongs to that
workspace at all, before it even considers finer-grained rules like "is
this specific entry public."

A person can belong to several workspaces at once (the family journal and
a separate friend-group journal, say) — the frontend has a workspace
switcher for this, rather than the app supporting only one workspace per
account.

### How visibility works today

There are two layers of visibility that combine:

1. **Workspace visibility** (`private` or `public`, owner-controlled,
   defaults to `private`): a private workspace is invisible to anyone who
   isn't a member (any role) — it can't be found via search, and its
   entries return "not found" to an outsider, not "forbidden" (see "The
   404-not-401 pattern" below for why that distinction matters). A public
   workspace is discoverable through a dedicated browse endpoint and
   readable by *anyone*, including someone who isn't logged in at all.
2. **Entry visibility** (`is_public`, per entry, set by its primary
   author): within whatever audience the workspace already exposes the
   entry to, a private entry narrows that further to just its author and
   co-authors, while a public entry is visible to that whole audience.

Critically, entry-level privacy is never *widened* by workspace publicity.
An entry marked private inside a public workspace still only shows to its
author and co-authors — being in a public workspace never means "all my
entries are now visible to the whole internet," only "my entries that I've
individually marked public are." Privacy settings only ever get stricter
as you compose the two layers, never looser.

### Why "public" had to become workspace-scoped, not app-wide

Before workspaces existed, `is_public` meant "visible to the whole app,"
which was fine when there was only one shared pool of users. Once separate
workspaces exist, "visible to the whole app" stops making sense as a
concept — a family journal marking an entry "public" should mean "visible
to the rest of this family," not "visible to a completely different
friend group's members who happen to also use this installation." So
`is_public` was redefined to mean "visible to this entry's workspace" by
default, and the *separate* app-wide "public" concept — genuinely open to
anyone, logged in or not — was rebuilt one level up, as a property of the
*workspace* itself rather than the entry. That split is what lets both
things coexist: "share with my group" (entry-level `is_public` within a
private workspace) and "share with the whole internet" (workspace-level
`public` visibility) are now two different, independently-controllable
settings instead of one overloaded flag.

### The API shape: nested under `/api/workspaces/{id}/...`

Every entry, tag, and comment endpoint lives under
`/api/workspaces/{workspace_id}/entries/...` rather than a flat
`/api/entries/...` with the workspace implied some other way (a query
parameter, a header, etc.). Putting it in the URL path means the
workspace a request is scoped to is unambiguous just by reading the URL —
there's no way to accidentally query "all entries" without saying which
workspace, and every permission check has the workspace id available
immediately, before it even needs to look up the specific entry. The two
exceptions are `PATCH`/`DELETE /api/comments/{id}` (editing or deleting a
single comment doesn't need the workspace restated in the URL — the
comment's id alone is enough to find its entry and, through that, its
workspace) and the two "which workspaces do I belong to" endpoints
(`POST`/`GET /api/workspaces`), which by definition aren't scoped to any
one workspace yet.

## Full-text search and tags: Postgres, not a separate search service

**Full-text search** means searching *inside* free-form text for words or
phrases — as opposed to an exact match, or a "contains this substring"
scan. Postgres has this built in via a column type called `tsvector`
("text search vector" — a preprocessed, searchable representation of some
text) paired with a `GIN` index (a Postgres index type built for exactly
this kind of "does this row contain X" lookup, rather than the more
familiar "find rows equal to X" kind).

Each entry has a `search_vector` column that's kept up to date
automatically by a database **trigger** — code that runs inside Postgres
itself whenever a row changes — every time an entry's text or its tags
change, combining both into one searchable value (tag matches are weighted
to rank above plain body-text matches). Searching then means
`search_vector @@ websearch_to_tsquery(...)`, matched against that GIN
index — fast even as entries grow, and it understands things like word
stems and multi-word phrases the way a real search feature should, which a
naive `ILIKE '%word%'` substring match doesn't (it doesn't rank results,
doesn't handle "trip" matching "trips," and gets slow on a large table
since it can't use a normal index).

The alternative to any of this would be a dedicated search service
(Elasticsearch, Algolia, etc.) — which is the right call at a scale where
one database can't keep up, but for this app's size, that would mean
running and maintaining an entire second piece of infrastructure, keeping
it in sync with Postgres, just to get a feature Postgres already does
well out of the box.

Tags themselves are a normal database table (`tags`, joined to entries via
`entry_tags`) rather than, say, a comma-separated column, specifically
because a real table supports things a flat column can't: listing every
distinct tag in use (for autocomplete), and enforcing that a tag name is
unique *within* a workspace (so two unrelated workspaces can each have
their own "roadtrip" tag without colliding, and so an autocomplete list
never leaks a tag name that only exists in a workspace the requester can't
see).

## Caching: in-memory, not Redis

The public Spotify catalog search (`spotify_client.py`) caches results for
10 minutes, keyed by the exact search text, using an in-memory **TTL
cache** ("time-to-live" — entries expire and get evicted automatically
after a set duration) from the `cachetools` library, rather than an
external cache server like Redis.

This is a deliberate scale call: Redis is the right tool once a cache
needs to be shared *across multiple running copies* of a backend process
(so they all see the same cached value, and a restart doesn't lose it) —
but this app runs as a single process, so an in-memory cache is visible to
every request already, with no extra infrastructure, no network hop to a
cache server, and one less thing that can fail. If the app is ever scaled
to run multiple backend processes at once, that's the point at which an
in-memory cache would need to be revisited (see `ROADMAP.md`) — until
then, it would be added complexity with no benefit.

## Security posture today

- **Spotify tokens encrypted at rest.** `SpotifyToken.access_token` and
  `.refresh_token` are encrypted before they're written to Postgres
  (using `Fernet`, a standard symmetric-encryption scheme from the
  `cryptography` library) and decrypted only when read back by the app —
  so a database backup, snapshot, or leaked dump doesn't hand over usable
  Spotify credentials, only unreadable ciphertext. The encryption key
  (`TOKEN_ENCRYPTION_KEY`) lives only in the app's own environment
  configuration, never in the database.
- **Rate limiting on login and registration.** Both are capped at 5
  attempts per minute per caller IP address, to blunt brute-force password
  guessing and mass account creation, without affecting normal use (a
  real person logging in once isn't going to hit that limit).
- **The "404, not 401 or 403" non-disclosure pattern.** When something is
  inaccessible because it's private, the app deliberately returns the same
  "not found" response it would give if that thing didn't exist at all,
  rather than a "forbidden" response that would confirm *something* is
  there. This applies consistently across the app: a private entry you
  can't see, a workspace you're not a member of, a comment in a workspace
  you can't reach — all read as "not found," never as "exists, but you
  can't have it." The reasoning: a "forbidden" response leaks the fact
  that a specific ID corresponds to *something real*, which is
  information a private resource shouldn't hand out even to someone who
  can't otherwise touch it.
- **Structured logging and optional error tracking.** The backend logs
  operationally relevant events (login attempts succeeding or failing,
  outbound Spotify API calls, cache hits/misses, workspace/entry
  create-delete actions) through Python's standard `logging` module in a
  consistent format, rather than scattered debug prints. Error tracking
  through [Sentry](https://sentry.io) is available but fully optional —
  set `SENTRY_DSN` (backend) and/or `VITE_SENTRY_DSN` (frontend) to enable
  it; leaving either unset is a complete no-op, not a startup failure,
  since there's no Sentry account configured by default.
