#!/bin/sh
# Container entrypoint for the production image (see Dockerfile,
# DEPLOYMENT.md). Applies any pending database migrations before the
# server starts accepting traffic, then starts uvicorn on $PORT - Railway
# (and most hosts) inject that at runtime, so it's never hardcoded here.
set -eu

echo "docker-entrypoint: running database migrations..."
alembic upgrade head

echo "docker-entrypoint: starting server on port ${PORT:-8000}..."
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
