#!/bin/sh
# Runs once, at container first-init, alongside the main POSTGRES_DB - creates
# a second database for the backend test suite so `pytest` never touches
# real journal data. See backend/tests/conftest.py (TEST_DATABASE_URL).
set -e

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    CREATE DATABASE musical_memories_test;
EOSQL
