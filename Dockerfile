# Production image for the deployed app (see DEPLOYMENT.md) - builds the
# frontend and serves it from the same FastAPI process that serves the
# API, so there's exactly one deployed service, not two. Build context is
# the repo root (needs both frontend/ and backend/), which is why this
# can't live under backend/ the way Dockerfile.backup does.
#
# NOT used for local development - see the README's "Running locally"
# for the Vite dev server + uvicorn --reload workflow instead.

# ---- Stage 1: build the frontend --------------------------------------
FROM node:20-slim AS frontend-build

WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ---- Stage 2: Python backend, serving the built frontend ---------------
FROM python:3.12-slim AS backend

WORKDIR /app

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/app ./app
COPY backend/alembic ./alembic
COPY backend/alembic.ini .

# The built frontend lands at /app/static/dist - app/main.py serves it
# from there (assets at /assets, an index.html SPA fallback for
# everything else that isn't an /api/* route) only when this directory
# is actually present, which is exactly the case here and never in local
# dev.
COPY --from=frontend-build /frontend/dist ./static/dist

COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh

ENTRYPOINT ["/docker-entrypoint.sh"]
