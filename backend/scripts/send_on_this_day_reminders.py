"""Once a day, checks whether any user has journal entries added on this
exact month/day in a previous year, and if so, sends them an "on this
day" reminder - through the notification system already built (see
app/models.py's Notification and app/routers/notifications.py), both
channels it already supports (an in-app Notification row, plus an email
via app/email.py's existing send_email), reusing that system exactly
rather than building a second delivery path.

Looks at JournalEntry.created_at (when the memory was actually added to
the app), not start_date (the date the memory is *about*) - this is a
"you were here on this day" usage anniversary, not something tied to the
content's own date. An entry counts for a user if they're its primary
author *or* a co-author - never just because they can view it (a
subscriber, or a workspace member with no authorship role on that
specific entry, is never notified about it).

Message content: exactly one matching entry links directly to it
(sets entry_id/workspace_id) and mentions how long ago it was. More than
one (several years, or several entries the same day) summarizes instead,
with no entry_id - there's no single right one to link to, and guessing
would be misleading.

Idempotent: never sends more than one on_this_day notification to the
same user on the same real calendar day, even if this script runs more
than once that day (e.g. a sidecar restart) - checks for an
already-created on_this_day notification for that user dated today
before creating another, rather than trusting the scheduler to only
fire once. `type="on_this_day"` needed no migration - see
models.Notification's docstring on why `type` is a plain, unconstrained
string specifically so a new notification type like this one could be
added as a pure application-level change.

Usage (from backend/):
    python -m scripts.send_on_this_day_reminders
"""

import logging
from datetime import date, datetime, timezone

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

NOTIFICATION_TYPE = "on_this_day"


def years_ago_message(entry_created_at: datetime, today: date) -> str:
    """The single-match message - mentions how long ago, matching this
    app's existing warm, "memories"-centric wording (see App.tsx's own
    "No memories yet - add your first one above.")."""
    years = today.year - entry_created_at.year
    unit = "year" if years == 1 else "years"
    return f"{years} {unit} ago today, you added a memory - take a look back!"


def summary_message(entry_count: int) -> str:
    """The multiple-matches message - deliberately no specific entry
    singled out, since there's no single right one to link to."""
    return f"You have {entry_count} memories from this day in past years - take a look back!"


def _find_matching_entries(db, user, today: date):
    """Every entry `user` is the primary author or a co-author of, added
    (JournalEntry.created_at) on today's month/day in some prior year -
    any prior year, not just exactly one year ago. Never entries the
    user merely has view access to (workspace membership, or an
    entry-level `is_public` flag, are both irrelevant here)."""
    from sqlalchemy import extract, or_, select

    from app.models import JournalEntry, User

    stmt = select(JournalEntry).where(
        or_(JournalEntry.user_id == user.id, JournalEntry.coauthors.any(User.id == user.id)),
        extract("month", JournalEntry.created_at) == today.month,
        extract("day", JournalEntry.created_at) == today.day,
        extract("year", JournalEntry.created_at) < today.year,
    )
    return list(db.scalars(stmt).unique().all())


def _already_notified_today(db, user_id: int, today: date) -> bool:
    """True if `user_id` already has an on_this_day notification dated
    today - what makes re-running this script on the same day (e.g. a
    sidecar restart) a no-op for that user instead of a second
    notification."""
    from sqlalchemy import func, select

    from app.models import Notification

    return (
        db.scalar(
            select(Notification.id)
            .where(
                Notification.user_id == user_id,
                Notification.type == NOTIFICATION_TYPE,
                func.date(Notification.created_at) == today,
            )
            .limit(1)
        )
        is not None
    )


def run(today: date | None = None) -> int:
    """Iterates every non-deleted user, skips anyone already notified
    today, and creates+emails an on_this_day notification for anyone
    with at least one matching entry. `today` is overridable purely for
    tests - production always uses the real current UTC date."""
    from sqlalchemy import select

    from app.database import SessionLocal
    from app.email import send_email
    from app.models import Notification, User

    today = today or datetime.now(timezone.utc).date()
    notified_count = 0

    db = SessionLocal()
    try:
        users = db.scalars(select(User).where(User.deleted_at.is_(None))).all()
        for user in users:
            if _already_notified_today(db, user.id, today):
                continue

            entries = _find_matching_entries(db, user, today)
            if not entries:
                continue

            if len(entries) == 1:
                entry = entries[0]
                message = years_ago_message(entry.created_at, today)
                notification = Notification(
                    user_id=user.id,
                    type=NOTIFICATION_TYPE,
                    message=message,
                    entry_id=entry.id,
                    workspace_id=entry.workspace_id,
                )
            else:
                message = summary_message(len(entries))
                notification = Notification(user_id=user.id, type=NOTIFICATION_TYPE, message=message)

            db.add(notification)
            db.commit()
            send_email(user.email, "On this day - Musical Memories", message)
            logger.info("on_this_day.notified user_id=%s entry_count=%d", user.id, len(entries))
            notified_count += 1
    finally:
        db.close()

    logger.info("on_this_day.completed date=%s users_notified=%d", today.isoformat(), notified_count)
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(run())
