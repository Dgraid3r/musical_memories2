#!/bin/sh
# Same "deliberately simple scheduling" as run_backup_daily.sh - a sleep
# loop, not a real cron daemon: runs the check once immediately on
# container start, then again every ON_THIS_DAY_INTERVAL_SECONDS
# (default: a day). send_on_this_day_reminders.py is itself idempotent
# per user per real calendar day (see its own docstring), so an extra
# run on the same day - a restart, or this loop's own first-run-then-
# interval shape overlapping a previous day's run - is always a safe
# no-op, never a duplicate notification.
set -eu

interval="${ON_THIS_DAY_INTERVAL_SECONDS:-86400}"

while true; do
  echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) on-this-day-cron: running scheduled check..."
  if ! python -m scripts.send_on_this_day_reminders; then
    echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) on-this-day-cron: run failed - see the log lines above"
  fi
  sleep "$interval"
done
