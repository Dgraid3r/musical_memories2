from datetime import datetime, timezone

from app.email import last_email_to
from app.models import JournalEntry
from scripts.send_on_this_day_reminders import run, summary_message, years_ago_message

TODAY = datetime.now(timezone.utc).date()


def _create_entry(client, workspace_id, headers, *, playlist_id="p1", coauthor_usernames=None):
    data = {
        "start_date": "2020-01-01",
        "playlist_id": playlist_id,
        "playlist_name": "Test",
        "playlist_url": f"https://open.spotify.com/playlist/{playlist_id}",
        "is_public": "false",
    }
    res = client.post(
        f"/api/workspaces/{workspace_id}/entries",
        headers=headers,
        data=data,
        files=[("coauthor_usernames", (None, u)) for u in (coauthor_usernames or [])],
    )
    assert res.status_code == 201, res.text
    return res.json()["id"]


def _set_created_at(db_session, entry_id, created_at):
    entry = db_session.get(JournalEntry, entry_id)
    entry.created_at = created_at
    db_session.commit()


def _on_this_day_years_ago(years: int) -> datetime:
    """A datetime on today's real month/day, `years` years in the past -
    noon, to stay well clear of any UTC-midnight boundary flakiness."""
    return datetime(TODAY.year - years, TODAY.month, TODAY.day, 12, 0, 0)


def _today_notifications(client, headers):
    return [n for n in client.get("/api/notifications", headers=headers).json() if n["type"] == "on_this_day"]


# --- Pure message-builder functions -----------------------------------------


def test_years_ago_message_singular():
    msg = years_ago_message(datetime(TODAY.year - 1, TODAY.month, TODAY.day), TODAY)
    assert "1 year ago" in msg
    assert "1 years ago" not in msg


def test_years_ago_message_plural():
    msg = years_ago_message(datetime(TODAY.year - 3, TODAY.month, TODAY.day), TODAY)
    assert "3 years ago" in msg


def test_summary_message_mentions_count():
    assert "5" in summary_message(5)


# --- run() behavior ----------------------------------------------------------


def test_single_matching_entry_notifies_with_direct_link(client, make_user, make_workspace, db_session):
    alice = make_user("alice")
    ws = make_workspace(alice)
    entry_id = _create_entry(client, ws["id"], alice["headers"])
    _set_created_at(db_session, entry_id, _on_this_day_years_ago(2))

    result = run()
    assert result == 0

    notifications = _today_notifications(client, alice["headers"])
    assert len(notifications) == 1
    assert notifications[0]["entry_id"] == entry_id
    assert notifications[0]["workspace_id"] == ws["id"]
    assert "2 years ago" in notifications[0]["message"]

    sent = last_email_to(alice["email"])
    assert sent is not None
    assert "2 years ago" in sent["body"]


def test_multiple_matching_entries_summarizes_with_no_link(client, make_user, make_workspace, db_session):
    alice = make_user("alice")
    ws = make_workspace(alice)
    entry1_id = _create_entry(client, ws["id"], alice["headers"], playlist_id="p1")
    entry2_id = _create_entry(client, ws["id"], alice["headers"], playlist_id="p2")
    _set_created_at(db_session, entry1_id, _on_this_day_years_ago(1))
    _set_created_at(db_session, entry2_id, _on_this_day_years_ago(3))

    run()

    notifications = _today_notifications(client, alice["headers"])
    assert len(notifications) == 1
    assert notifications[0]["entry_id"] is None
    assert notifications[0]["workspace_id"] is None
    assert "2" in notifications[0]["message"]


def test_no_matching_entries_creates_nothing(client, make_user, make_workspace):
    alice = make_user("alice")
    ws = make_workspace(alice)
    _create_entry(client, ws["id"], alice["headers"])  # created_at is real "now" - not on-this-day-in-the-past

    run()

    assert _today_notifications(client, alice["headers"]) == []


def test_running_twice_same_day_only_notifies_once(client, make_user, make_workspace, db_session):
    alice = make_user("alice")
    ws = make_workspace(alice)
    entry_id = _create_entry(client, ws["id"], alice["headers"])
    _set_created_at(db_session, entry_id, _on_this_day_years_ago(1))

    first = run()
    second = run()
    assert first == 0
    assert second == 0

    assert len(_today_notifications(client, alice["headers"])) == 1


def test_entry_from_this_year_does_not_count(client, make_user, make_workspace, db_session):
    """Same month/day, but this year, not a prior one - must never
    trigger a notification (it isn't "on this day in the past" yet)."""
    alice = make_user("alice")
    ws = make_workspace(alice)
    entry_id = _create_entry(client, ws["id"], alice["headers"])
    _set_created_at(db_session, entry_id, datetime(TODAY.year, TODAY.month, TODAY.day, 1, 0, 0))

    run()

    assert _today_notifications(client, alice["headers"]) == []


def test_coauthor_is_notified_for_a_shared_entry(client, make_user, make_workspace, db_session):
    alice = make_user("alice")
    bob = make_user("bob")
    ws = make_workspace(alice, bob)
    entry_id = _create_entry(client, ws["id"], alice["headers"], coauthor_usernames=["bob"])
    _set_created_at(db_session, entry_id, _on_this_day_years_ago(4))

    run()

    alice_notifications = _today_notifications(client, alice["headers"])
    bob_notifications = _today_notifications(client, bob["headers"])
    assert len(alice_notifications) == 1
    assert len(bob_notifications) == 1
    assert bob_notifications[0]["entry_id"] == entry_id


def test_view_only_member_is_not_notified(client, make_user, make_workspace, db_session):
    """carol is a real member of the workspace (so she can *view* the
    entry) but is neither its primary author nor a co-author - she must
    never be notified about it, even though she can see it."""
    alice = make_user("alice")
    carol = make_user("carol")
    ws = make_workspace(alice, carol)
    entry_id = _create_entry(client, ws["id"], alice["headers"])
    _set_created_at(db_session, entry_id, _on_this_day_years_ago(1))

    run()

    assert _today_notifications(client, carol["headers"]) == []
    # alice (the actual primary author) still gets hers.
    assert len(_today_notifications(client, alice["headers"])) == 1


def test_entries_in_different_workspaces_are_both_counted(client, make_user, make_workspace, db_session):
    alice = make_user("alice")
    ws1 = make_workspace(alice, name="Workspace One")
    ws2 = make_workspace(alice, name="Workspace Two")
    entry1_id = _create_entry(client, ws1["id"], alice["headers"], playlist_id="p1")
    entry2_id = _create_entry(client, ws2["id"], alice["headers"], playlist_id="p2")
    _set_created_at(db_session, entry1_id, _on_this_day_years_ago(1))
    _set_created_at(db_session, entry2_id, _on_this_day_years_ago(2))

    run()

    notifications = _today_notifications(client, alice["headers"])
    assert len(notifications) == 1
    assert "2" in notifications[0]["message"]
