# Deploying Musical Memories

This is a step-by-step guide for putting the app somewhere on the real
internet, written for someone who hasn't done this kind of thing before.
It assumes no prior hosting/infrastructure knowledge - just follow the
steps in order.

The app is hosted on **Railway** (a service that runs your code and gives
it a public web address) with a **Cloudflare R2** bucket for storing
uploaded photos. Neither choice is locked in by anything in the code -
the app already supports any S3-compatible storage provider (see
`backend/app/storage.py`) and any standard Docker-hosting platform - but
these are the ones set up here, and this guide is written for them
specifically.

Nothing in this guide can be done for you automatically: creating
accounts, entering payment details, and generating provider-specific
credentials all require you to be logged in as yourself. Everything else
(the code, the container image, the automated tests) is already built and
verified - this guide is only the remaining hands-on part.

## Before you start

You'll need:

- A GitHub account with access to this repository (you likely already
  have this).
- An email address and a payment method for the Railway account (Railway
  has a free trial/tier, but eventually needs billing info for anything
  beyond light personal use).
- An email address for the Cloudflare account (Cloudflare R2 has a
  generous free tier that's plenty for personal-scale use).
- Your Spotify Developer Dashboard access (the same one already used
  locally for `SPOTIFY_CLIENT_ID`/`SPOTIFY_CLIENT_SECRET` - see the
  README's "Spotify API" section).

## 1. Create a Railway account and project

1. Go to [railway.app](https://railway.app) and sign up (GitHub sign-in
   is the easiest option, since you'll be connecting a GitHub repo
   anyway).
2. Create a **New Project**.
3. Choose **Deploy from GitHub repo**, and select this repository. If
   Railway asks for GitHub permissions, grant it access to this repo (you
   can restrict it to just this one).
4. Railway will create a "service" for this repo and start trying to
   build it. That first build attempt is expected to fail or sit
   incomplete for now - you haven't added the database or any required
   settings yet, both covered below. Don't worry about a red/failed build
   at this point.

This connection is also what gives you **automatic deploys going
forward**: every time new code is merged into `master` on GitHub, Railway
will automatically rebuild and redeploy it. Nothing further needs to be
set up for that - it's a consequence of connecting the repo here, not a
separate step.

Railway already knows to use this repo's `Dockerfile` at the repo root
(via `railway.toml`), so you don't need to tell it how to build the app.

## 2. Add a Postgres database

1. In your Railway project, click **New** -> **Database** -> **Add
   PostgreSQL**.
2. Railway creates a Postgres database and automatically provides a
   `DATABASE_URL` variable containing its connection details.
3. Go to your app service (not the database) -> **Variables** tab, and
   add a variable named `DATABASE_URL` whose value **references** the
   database's own variable - Railway's variable UI lets you pick
   "reference a variable from another service"; select the Postgres
   service's `DATABASE_URL`. This keeps the two in sync automatically if
   Railway ever rotates the database's connection details.

You do not need to reformat or edit the value Railway provides - this
app understands the plain `postgresql://...` format Railway's Postgres
plugin gives you directly (a compatibility fix was added specifically so
this "just works").

## 3. Create a Cloudflare R2 bucket for photo storage

1. Go to [dash.cloudflare.com](https://dash.cloudflare.com), sign up or
   log in, and open **R2 Object Storage** from the sidebar (you may need
   to enable R2 on your account first - Cloudflare will prompt you
   through that, and the free tier requires no payment card for
   light/personal use).
2. Create a bucket - pick any name (e.g. `musical-memories-photos`).
3. Go to **R2** -> **Manage R2 API Tokens** (or **Account API Tokens**)
   and create a new API token with **Object Read & Write** permission,
   scoped to that bucket if given the option.
4. Cloudflare will show you three things - copy all of them somewhere
   safe, you won't be able to see the secret again:
   - **Access Key ID**
   - **Secret Access Key**
   - **Endpoint URL** (looks like
     `https://<account-id>.r2.cloudflarestorage.com`)
5. In Railway, on your app service's **Variables** tab, add:

   | Variable | Value |
   |---|---|
   | `OBJECT_STORAGE_ENDPOINT_URL` | the Endpoint URL from step 4 |
   | `OBJECT_STORAGE_BUCKET` | the bucket name from step 2 |
   | `OBJECT_STORAGE_ACCESS_KEY` | the Access Key ID from step 4 |
   | `OBJECT_STORAGE_SECRET_KEY` | the Secret Access Key from step 4 |
   | `OBJECT_STORAGE_REGION` | `auto` |

   These are the exact same variable names the app already looks for
   locally (see `backend/.env.example`) - R2 needs no special handling
   beyond that, since it speaks the same S3-compatible API the app
   already talks to.

Without this, the app still works, but uploaded photos are stored
directly on Railway's container instead of R2 - which is lost the next
time the container restarts or redeploys. Set this before real use.

## 4. Set the rest of the required and optional variables

Still on your app service's **Variables** tab in Railway, add these:

**Required:**

| Variable | What it's for |
|---|---|
| `JWT_SECRET_KEY` | Signs login sessions. Generate a random value: run `python -c "import secrets; print(secrets.token_hex(32))"` on your own computer and paste the result. |
| `TOKEN_ENCRYPTION_KEY` | Encrypts saved Spotify account tokens. Generate with `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` - this is a different format than `JWT_SECRET_KEY`, don't reuse that command. |
| `SPOTIFY_CLIENT_ID` | From your Spotify Developer Dashboard app - lets the app search Spotify's catalog. |
| `SPOTIFY_CLIENT_SECRET` | The matching secret from the same Spotify app. |
| `FRONTEND_URL` | The web address people will use to reach the app - see step 5, you'll fill this in with Railway's own URL right after the first successful deploy. |

**Optional (the app works without these, just with reduced functionality):**

| Variable | What it's for |
|---|---|
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI` | Only needed if you want the "Sign in with Google" button to appear. Without these, the app still works fully with local username/password accounts - the button just doesn't show. From an OAuth client in the [Google Cloud Console](https://console.cloud.google.com/) (APIs & Services -> Credentials -> Create OAuth client ID -> Web application); set `GOOGLE_REDIRECT_URI` to `<your-railway-url>/api/auth/google/callback` and add that same exact URL as an Authorized redirect URI on the OAuth client (same byte-for-byte matching requirement as `SPOTIFY_REDIRECT_URI` in step 5 below). |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM_ADDRESS` | Only needed if you want workspace-invite, verify-your-email, and password-reset emails to actually be delivered. Without these, the app still works fully, but those links are only written to the server's own logs instead of emailed - fine for just you, not for inviting anyone else to a private workspace. A personal Gmail account works (see the README's "Security and operations" section for the exact settings). |
| `SENTRY_DSN` | Only needed if you want errors reported to a [Sentry](https://sentry.io) account for visibility into problems after deploy. Without it, errors are just logged normally. |

Everything else the app supports has a sensible built-in default and
doesn't need to be set (see `backend/.env.example` for the complete
list, including things like `LOG_LEVEL` and `BACKUP_RETENTION_DAYS`).
You do **not** need to set `PORT` yourself - Railway provides it
automatically, and the app is already built to use whatever value
Railway gives it.

Once these are set (along with `DATABASE_URL` from step 2), Railway
should be able to build and deploy successfully. Watch the **Deployments**
tab; a successful deploy shows a green "Active" status.

## 5. Point Spotify at your real deployed address

Once the first deploy succeeds, Railway gives your app a public URL under
**Settings** -> **Networking** -> **Public Networking** (something like
`https://your-app-name.up.railway.app`, or click **Generate Domain** if
one isn't there yet).

1. Copy that URL.
2. Go back to your Spotify Developer Dashboard, open your app's
   **Settings**, and add a **Redirect URI** of exactly
   `<your-railway-url>/api/spotify/callback` (matching scheme and no
   trailing slash) - this is what lets "Connect Spotify" account linking
   work for real once deployed.
3. In Railway's Variables tab, set:
   - `SPOTIFY_REDIRECT_URI` to that same
     `<your-railway-url>/api/spotify/callback` value.
   - `FRONTEND_URL` (from step 4) to `<your-railway-url>` (no trailing
     path) - since the frontend and API are served from this one same
     address in production, this is just your Railway URL itself.
4. Save - Railway automatically redeploys when variables change, so this
   takes effect on its own.

Until this step is done, the "Connect Spotify" account-linking feature
won't work correctly (it'll redirect to the wrong place), though
everything else in the app works fine without it.

## 6. (Optional, later) Add a custom domain

If you buy a domain name and want the app to live there instead of the
`*.up.railway.app` address, add it under your app service's **Settings**
-> **Networking** -> **Custom Domain** in Railway, and follow the DNS
instructions Railway shows you there. If you do this, repeat step 5 with
the new address (Spotify redirect URI and `FRONTEND_URL` both need to
match wherever the app actually lives).

This is entirely optional and not required to have the app fully working
on its Railway-provided address.

## 7. (Optional, later) Run the daily backup from the deployed environment

Locally, database backups can run on a schedule via a small companion
service defined in `docker-compose.yml` (see the README's "Backups and
monitoring" section). The same idea works on Railway if you want backups
running against the live deployed database rather than only against your
local one:

1. In your Railway project, add another service: **New** -> **Empty
   Service** (or **GitHub Repo**, pointed at this same repository again).
2. Under that new service's **Settings** -> **Build**, set it to build
   from `backend/Dockerfile.backup` instead of the repo-root `Dockerfile`.
3. Give it the same `DATABASE_URL` (reference the Postgres service's
   variable, same as step 2) and the same `OBJECT_STORAGE_*` variables
   (same as step 3) - backups need to be able to reach both the database
   and the storage bucket, and should reuse the exact same bucket
   configuration, not a separate one.
4. Optionally set `BACKUP_RETENTION_DAYS` and `BACKUP_INTERVAL_SECONDS`
   to override their defaults (30 days, once a day) - see
   `backend/.env.example`.

This isn't required to launch - the app and its data are already
protected by Railway's own Postgres backups in the meantime - but it's
available whenever you want an independent backup running from the
deployed environment specifically, using the exact same script already
verified locally.

## Staging environment

Staging is a second, fully separate copy of the app - its own Railway
project, its own database, its own storage - that you can push changes
to and try out before they reach the real production app real users are
on. It's completely optional, but worth setting up once you're making
regular changes, so you have somewhere safe to catch a problem before it
affects anyone.

The two environments share nothing at runtime: staging has its own
database (so testing something there, even something destructive, can
never touch real production data) and its own photo storage bucket (see
the bucket-vs-shared-prefix note in step 3 below for why). The only
thing they share is this one GitHub repository.

### 1. Create a second Railway project for staging

Repeat "1. Create a Railway account and project" above, but:

- Do **not** create a new Railway account - use the same one.
- Do create a **new, separate Railway project** (not a new service inside
  your existing production project, and not Railway's built-in
  "environments" feature within one project - a genuinely separate
  project, so staging can never accidentally share a database or
  variable with production).
- Connect the same GitHub repository again.
- When Railway asks which branch to deploy, choose **`staging`** instead
  of `master`. If it doesn't ask right away, go to the service's
  **Settings** -> **Source** and set the branch there.

This gives you the same "deploys automatically on push" behavior as
production, just watching a different branch: from now on, pushing to
`staging` redeploys the staging app, and pushing to `master` still
redeploys production, independently of each other.

### 2. Add a separate Postgres database

Repeat "2. Add a Postgres database" above, but inside this **new**
staging project. This creates a brand new, empty database that belongs
only to staging - it starts with no data at all (not a copy of
production), and running migrations against it or even wiping it
entirely has zero effect on the real app.

### 3. Set staging's environment variables

Repeat "3. Create a Cloudflare R2 bucket for photo storage" and "4. Set
the rest of the required and optional variables" above, inside the
staging project, with these differences:

- **Object storage: create a second, separate R2 bucket** (e.g.
  `musical-memories-photos-staging`) rather than reusing production's
  bucket with some kind of "staging" prefix inside it. A second bucket
  is simpler to set up (it's the exact same three steps you already did
  for production, just once more) and gives real isolation - the app
  doesn't currently have any concept of a prefix to keep staging and
  production photos apart within one shared bucket, so a second bucket
  is both the easier and the actually-safe choice, not just a
  preference.
- **Spotify: reuse the same Spotify app**, don't create a second one -
  just add an *additional* Redirect URI to it (Spotify apps support more
  than one). You'll add the exact staging URL in step 4 below, once you
  know it. Use the same `SPOTIFY_CLIENT_ID`/`SPOTIFY_CLIENT_SECRET` values
  in both the production and staging Railway projects.
- **Everything else** (`JWT_SECRET_KEY`, `TOKEN_ENCRYPTION_KEY`,
  `SMTP_*`, `SENTRY_DSN`, etc.) - generate fresh values for staging
  rather than copying production's. There's no security benefit to
  staging and production sharing a session-signing key or an encryption
  key, and keeping them different means a staging login token, for
  instance, is never valid against production either.

### 4. Point Spotify at the staging address too

Once staging's first deploy succeeds, repeat "5. Point Spotify at your
real deployed address" above using staging's own Railway URL (it'll be a
different `*.up.railway.app` address than production's) - but instead of
replacing the Redirect URI in the Spotify Developer Dashboard, **add it
as a second one** alongside production's, so both URLs work at the same
time. Set `SPOTIFY_REDIRECT_URI` and `FRONTEND_URL` in the *staging*
Railway project to staging's own URL, exactly as you did for production.

### The new workflow going forward

With staging set up, the day-to-day habit changes slightly:

1. Make your changes on a branch (as before), and open a pull request or
   push into **`staging`** first, not `master`.
2. Once that lands, Railway automatically redeploys the staging app.
   Try the change out there.
3. When you're satisfied it works, **merge `staging` into `master`**
   (or open a pull request from `staging` to `master` if you'd rather
   review the combined diff first) to promote it to production. Railway
   then automatically redeploys the real app from the updated `master`.

`master` is always what's actually live for real users; `staging` is
always what's being tried out next. The automated tests (see the
README's "Tests" section) run the same way against both branches, so a
broken change is caught before it even reaches staging, let alone
production.

## What to expect after this is done

Once steps 1-5 are complete, the app is live at your Railway URL, changes
pushed to `master` deploy automatically, photos are stored durably in
Cloudflare R2, and `/api/health` reports whether the app and its database
are actually working - see the README's "Backups and monitoring" section
for pointing an uptime monitor at it once you're ready for that extra
layer of visibility.
