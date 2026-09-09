#!/bin/sh
# Deliberately simple scheduling - a sleep loop, not a real cron daemon:
# runs the backup once immediately on container start (useful feedback
# that it's actually working), then again every BACKUP_INTERVAL_SECONDS
# (default: a day). This is "keep it simple" scheduling for the current
# docker-compose setup, not a permanent design - once real hosting is
# chosen, prefer that platform's own cron/scheduled-job feature (or
# genuine cron) instead; see the README's "Backups" section.
set -eu

interval="${BACKUP_INTERVAL_SECONDS:-86400}"

while true; do
  echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) backup-cron: running scheduled backup..."
  if ! python -m scripts.backup_database; then
    echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) backup-cron: backup run failed - see the log lines above"
  fi
  sleep "$interval"
done
