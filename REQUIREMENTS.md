# Requirements

This document describes what Musical Memories must do — from a user's
point of view, not the implementation. For how these requirements are
actually met (which database, which libraries, why), see
[`ARCHITECTURE.md`](ARCHITECTURE.md), which this document links to rather
than repeats.

## Functional requirements

### Accounts

- A visitor can register a local account with a username, email address,
  and password.
- A username must be unique across the whole app; so must an email
  address. Registering with either already taken is rejected.
- A registered user can log in with their username and password and
  receives a token that keeps them signed in across requests.
- A user can view their own account details (username, email, when they
  registered).
- Registration and login are both rate-limited per caller, to blunt
  brute-force and mass-account-creation attempts (see
  [`ARCHITECTURE.md`](ARCHITECTURE.md#security-posture-today)).

### Workspaces

- A logged-in user can create a workspace, becoming its owner. There is no
  limit on how many workspaces a user can create or belong to.
- A user can belong to more than one workspace at a time, and can switch
  which one is active in the app.
- A user can see the list of every workspace they belong to, along with
  their role in each.
- A workspace owner can add an existing user to the workspace by username
  (the current stand-in for a real invitation flow — see
  [`ROADMAP.md`](ROADMAP.md)).
- A workspace owner can remove a member (other than themselves) from the
  workspace.
- A workspace owner can change a member's role between **member**
  (read/write) and **subscriber** (read-only).
- A workspace has exactly one owner at a time; the owner cannot remove
  themselves or change their own role, since there is no mechanism yet to
  transfer ownership or recover an ownerless workspace (see
  [`ROADMAP.md`](ROADMAP.md)).
- A workspace owner can delete the entire workspace, which permanently
  removes every entry, tag, and comment in it.
- A workspace owner can toggle the workspace between **private**
  (invisible to and unreachable by anyone who isn't a member) and
  **public** (discoverable by anyone and readable without an account).
  This takes effect immediately.
- Any visitor, logged in or not, can browse and search the list of public
  workspaces by name, and can read a public workspace's entries and
  comments without an account.
- A member of one workspace can never see or reach another workspace's
  content by guessing an ID, whether or not they're logged in.

### Entries

- A member (or owner) of a workspace can create a journal entry in it: a
  date or date range, an optional text note, and a Spotify playlist. A
  single-day entry is entered as one date; a multi-day entry has a
  distinct start and end date.
- An entry's end date cannot be before its start date.
- An entry always has exactly one playlist attached, even for what's
  conceptually a single song (the expectation is a single-track playlist
  in that case).
- An entry can have any number of photos attached, both at creation and
  added afterward.
- An entry is private by default. Its primary author can make it public
  (visible to the workspace's normal audience — see "Workspace visibility
  and entry visibility together" below) or back to private again at any
  time.
- An entry's primary author can add or remove co-authors, who must already
  hold a read/write role (owner or member, not subscriber) in the same
  workspace.
- A co-author can edit an entry's text, tags, and photos, the same as the
  primary author, but cannot change its visibility, manage its
  co-authors, or delete it.
- Only the primary author can delete an entry; doing so also deletes its
  photos.
- A subscriber can read every entry a member can, but cannot create,
  edit, or delete an entry, add photos to one, or become a co-author.

#### Workspace visibility and entry visibility together

- In a private workspace, a public entry is visible to every member (any
  role) of that workspace; a private entry is visible only to its author
  and co-authors.
- In a public workspace, a public entry is visible to anyone at all,
  including someone not logged in; a private entry is still visible only
  to its author and co-authors — workspace publicity never widens an
  individual entry's own privacy setting.

### Tags

- Any workspace member (or owner) can attach any number of free-text tags
  to an entry, either at creation or afterward. Typing a new tag name
  creates it; typing an existing one reuses it.
- Tag names are unique within a workspace, not across the whole app — two
  different workspaces can each have their own tag with the same name
  without conflict.
- A user can list every tag currently in use in a workspace, scoped to
  what they're allowed to see (a tag used only on a private entry someone
  else authored is not listed).

### Comments

- Anyone who can read an entry can also read its comments — including an
  anonymous visitor to a public workspace's public entry.
- A workspace member (or owner) who can view an entry can post a top-level
  comment on it, or reply to any existing comment on it (including a
  reply to a reply — comments can nest to any depth).
- A subscriber and an anonymous public-workspace visitor can read every
  comment but cannot post one.
- A comment's own author can edit or delete it.
- An entry's primary author can additionally delete (but not edit) any
  comment on their own entry, as a moderation power — a co-author of the
  entry does not get this power just from being able to edit the entry's
  content.
- Deleting a comment also deletes every reply nested underneath it.

### Spotify integration

- Any visitor to the entry form can search Spotify's public playlist
  catalog to attach a playlist to an entry, without needing to log in to
  Spotify at all.
- A logged-in user can separately connect their own Spotify account (via
  Spotify's own login and consent screen — the app never sees or stores
  their Spotify password).
- Once connected, a user can browse their own Spotify playlists from
  within the entry form, as an alternative to catalog search.
- A user can see whether their Spotify account is currently connected.
- Spotify account linking is independent of local login — connecting or
  disconnecting Spotify never affects a user's ability to log in to this
  app, and vice versa.

### Search

- A workspace member (or owner, or, for a public workspace, an anonymous
  visitor) can search that workspace's entries by free text, matched
  against both entry text and tag names, ranked by relevance.
- A user can filter a workspace's entries down to those carrying one
  exact tag.
- Search and tag filtering both respect the same visibility rules as
  browsing the entry list normally — a search never surfaces an entry the
  searcher couldn't otherwise see.

## Non-functional requirements

### Security and privacy

- A user's password is never stored or logged in a form that could be
  read back out — only a one-way hashed representation is kept (see
  [`ARCHITECTURE.md`](ARCHITECTURE.md#the-stack-and-why-each-piece-was-picked)).
- A linked Spotify account's access and refresh tokens are encrypted at
  rest and are never included in any API response body, under any
  circumstance (see
  [`ARCHITECTURE.md`](ARCHITECTURE.md#security-posture-today)).
- No user can access another workspace's data — entries, tags, or
  comments — by guessing or constructing an ID, regardless of whether
  they're logged in, logged in as an unrelated user, or a member of a
  *different* workspace. An inaccessible resource must be indistinguishable
  from one that doesn't exist at all (see
  [`ARCHITECTURE.md`](ARCHITECTURE.md#security-posture-today)).
- Login and registration attempts are rate-limited to reduce the
  effectiveness of automated password-guessing or mass account creation.

### Performance

- Full-text search must return results quickly as the number of entries in
  a workspace grows, using an index-backed search rather than a
  linear scan of entry text (see
  [`ARCHITECTURE.md`](ARCHITECTURE.md#full-text-search-and-tags-postgres-not-a-separate-search-service)).
- A repeated identical public-catalog Spotify search within a short window
  should not need to re-contact Spotify's API, both for responsiveness and
  to conserve the app's shared Spotify API quota (see
  [`ARCHITECTURE.md`](ARCHITECTURE.md#caching-in-memory-not-redis) and
  [`ROADMAP.md`](ROADMAP.md)).

### Availability and observability

- Operationally significant events (authentication successes/failures,
  outbound Spotify API activity, workspace and entry lifecycle actions)
  are recorded in a structured, consistent log format that can be read by
  a human or a log-processing tool, rather than left unlogged or logged
  as ad-hoc print statements.
- The system supports optional integration with an error-tracking service
  (Sentry) for both the backend and frontend, without requiring one to be
  configured to run at all (see
  [`ARCHITECTURE.md`](ARCHITECTURE.md#security-posture-today)).
- The database schema is managed through versioned, repeatable migrations
  rather than manual changes, so every environment (a developer's laptop,
  a future production deployment) can be brought to the same known state
  (see
  [`ARCHITECTURE.md`](ARCHITECTURE.md#the-stack-and-why-each-piece-was-picked)).
