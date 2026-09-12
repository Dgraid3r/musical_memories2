from app.email import last_email_to


def _create_entry(client, workspace_id, headers, *, is_public=True, playlist_id="p1", coauthor_usernames=None):
    data = {
        "start_date": "2026-01-01",
        "text": "hello",
        "playlist_id": playlist_id,
        "playlist_name": "Test Playlist",
        "playlist_url": f"https://open.spotify.com/playlist/{playlist_id}",
        "is_public": str(is_public).lower(),
    }
    res = client.post(
        f"/api/workspaces/{workspace_id}/entries",
        headers=headers,
        data=data,
        files=[("coauthor_usernames", (None, u)) for u in (coauthor_usernames or [])],
    )
    assert res.status_code == 201, res.text
    return res.json()["id"]


def _comment(client, workspace_id, entry_id, headers, body="hello"):
    res = client.post(
        f"/api/workspaces/{workspace_id}/entries/{entry_id}/comments", headers=headers, json={"body": body}
    )
    assert res.status_code == 201, res.text
    return res.json()


# --- Comment notifications --------------------------------------------------


def _of_type(notifications, type_):
    return [n for n in notifications if n["type"] == type_]


def test_comment_notifies_primary_author_not_commenter(client, make_user, make_workspace):
    alice = make_user("alice")
    bob = make_user("bob")
    # make_workspace adds bob via the real invite flow (see
    # conftest.py's add_workspace_member) - since bob already has an
    # account, that itself creates one "invite" notification for him
    # (see test_invite_to_existing_user_creates_in_app_notification
    # below), unrelated to this test's own comment-notification
    # assertions, so those filter to type="comment" specifically.
    ws = make_workspace(alice, bob)
    entry_id = _create_entry(client, ws["id"], alice["headers"])

    _comment(client, ws["id"], entry_id, bob["headers"], body="nice trip!")

    alice_notifications = _of_type(client.get("/api/notifications", headers=alice["headers"]).json(), "comment")
    assert len(alice_notifications) == 1
    assert "bob" in alice_notifications[0]["message"]
    assert alice_notifications[0]["entry_id"] == entry_id
    assert alice_notifications[0]["workspace_id"] == ws["id"]
    assert alice_notifications[0]["read_at"] is None

    bob_comment_notifications = _of_type(client.get("/api/notifications", headers=bob["headers"]).json(), "comment")
    assert bob_comment_notifications == []

    sent = last_email_to("alice@example.com")
    assert sent is not None
    assert "bob" in sent["body"]


def test_commenting_on_your_own_entry_notifies_no_one(client, make_user, make_workspace):
    alice = make_user("alice")
    ws = make_workspace(alice)
    entry_id = _create_entry(client, ws["id"], alice["headers"])

    _comment(client, ws["id"], entry_id, alice["headers"], body="note to self")

    assert client.get("/api/notifications", headers=alice["headers"]).json() == []


def test_comment_notifies_coauthors_but_never_the_commenter_even_as_coauthor(client, make_user, make_workspace):
    """Carol comments on alice's entry, which bob co-authors - both alice
    and bob get notified, carol doesn't. Then bob (a co-author) comments -
    alice gets notified, but bob never gets notified about his own
    comment even though he's a co-author on the entry."""
    alice = make_user("alice")
    bob = make_user("bob")
    carol = make_user("carol")
    ws = make_workspace(alice, bob, carol)
    entry_id = _create_entry(client, ws["id"], alice["headers"], coauthor_usernames=["bob"])

    _comment(client, ws["id"], entry_id, carol["headers"], body="lovely")

    def comment_notifications(headers):
        return _of_type(client.get("/api/notifications", headers=headers).json(), "comment")

    assert len(comment_notifications(alice["headers"])) == 1
    assert len(comment_notifications(bob["headers"])) == 1
    assert comment_notifications(carol["headers"]) == []

    _comment(client, ws["id"], entry_id, bob["headers"], body="thanks!")

    assert len(comment_notifications(alice["headers"])) == 2
    # Still just the one comment-notification from carol's comment -
    # bob's own second comment never notified bob himself.
    assert len(comment_notifications(bob["headers"])) == 1


# --- Invite notifications ---------------------------------------------------


def test_invite_to_existing_user_creates_in_app_notification(client, make_user, make_workspace):
    alice = make_user("alice")
    bob = make_user("bob")
    ws = make_workspace(alice)

    res = client.post(f"/api/workspaces/{ws['id']}/invites", headers=alice["headers"], json={"email": bob["email"]})
    assert res.status_code == 201, res.text

    bob_notifications = client.get("/api/notifications", headers=bob["headers"]).json()
    assert len(bob_notifications) == 1
    assert bob_notifications[0]["type"] == "invite"
    assert "alice" in bob_notifications[0]["message"]
    assert bob_notifications[0]["workspace_id"] == ws["id"]
    assert bob_notifications[0]["entry_id"] is None

    # The invite email itself still goes out too - notifications are
    # additive, never a replacement for it.
    assert last_email_to(bob["email"]) is not None


def test_invite_to_brand_new_email_does_not_error_and_creates_no_notification(client, make_user, make_workspace):
    alice = make_user("alice")
    ws = make_workspace(alice)

    res = client.post(
        f"/api/workspaces/{ws['id']}/invites", headers=alice["headers"], json={"email": "nobody@example.com"}
    )
    assert res.status_code == 201, res.text
    assert last_email_to("nobody@example.com") is not None


# --- Listing / permission ----------------------------------------------------


def test_list_notifications_requires_auth(client):
    res = client.get("/api/notifications")
    assert res.status_code == 401


def test_list_notifications_only_returns_own(client, make_user, make_workspace):
    alice = make_user("alice")
    bob = make_user("bob")
    ws = make_workspace(alice, bob)
    entry_id = _create_entry(client, ws["id"], alice["headers"])
    _comment(client, ws["id"], entry_id, bob["headers"])

    # bob has his own "invite" notification from being added to the
    # workspace (see make_workspace/add_workspace_member), but never
    # alice's "comment" notification about his own comment.
    bob_notifications = client.get("/api/notifications", headers=bob["headers"]).json()
    assert _of_type(bob_notifications, "comment") == []


def test_list_notifications_most_recent_first(client, make_user, make_workspace):
    alice = make_user("alice")
    bob = make_user("bob")
    ws = make_workspace(alice, bob)
    entry_id = _create_entry(client, ws["id"], alice["headers"])
    _comment(client, ws["id"], entry_id, bob["headers"], body="first")
    _comment(client, ws["id"], entry_id, bob["headers"], body="second")

    notifications = client.get("/api/notifications", headers=alice["headers"]).json()
    assert len(notifications) == 2
    assert notifications[0]["id"] > notifications[1]["id"]


def test_list_notifications_respects_limit_and_offset(client, make_user, make_workspace):
    alice = make_user("alice")
    bob = make_user("bob")
    ws = make_workspace(alice, bob)
    entry_id = _create_entry(client, ws["id"], alice["headers"])
    for i in range(5):
        _comment(client, ws["id"], entry_id, bob["headers"], body=f"comment {i}")

    page1 = client.get("/api/notifications?limit=2&offset=0", headers=alice["headers"]).json()
    page2 = client.get("/api/notifications?limit=2&offset=2", headers=alice["headers"]).json()
    assert len(page1) == 2
    assert len(page2) == 2
    assert {n["id"] for n in page1}.isdisjoint({n["id"] for n in page2})


def test_list_notifications_limit_rejects_values_above_the_max(client, make_user):
    alice = make_user("alice")
    res = client.get("/api/notifications?limit=101", headers=alice["headers"])
    assert res.status_code == 422


# --- Unread count / mark read / mark all read -------------------------------


def test_unread_count_accurate(client, make_user, make_workspace):
    alice = make_user("alice")
    bob = make_user("bob")
    ws = make_workspace(alice, bob)
    entry_id = _create_entry(client, ws["id"], alice["headers"])
    _comment(client, ws["id"], entry_id, bob["headers"], body="one")
    _comment(client, ws["id"], entry_id, bob["headers"], body="two")

    res = client.get("/api/notifications/unread-count", headers=alice["headers"])
    assert res.status_code == 200
    assert res.json()["count"] == 2

    notification_id = client.get("/api/notifications", headers=alice["headers"]).json()[0]["id"]
    mark_res = client.post(f"/api/notifications/{notification_id}/read", headers=alice["headers"])
    assert mark_res.status_code == 200
    assert mark_res.json()["read_at"] is not None

    res = client.get("/api/notifications/unread-count", headers=alice["headers"])
    assert res.json()["count"] == 1


def test_mark_read_is_idempotent(client, make_user, make_workspace):
    alice = make_user("alice")
    bob = make_user("bob")
    ws = make_workspace(alice, bob)
    entry_id = _create_entry(client, ws["id"], alice["headers"])
    _comment(client, ws["id"], entry_id, bob["headers"])
    notification_id = client.get("/api/notifications", headers=alice["headers"]).json()[0]["id"]

    first = client.post(f"/api/notifications/{notification_id}/read", headers=alice["headers"])
    second = client.post(f"/api/notifications/{notification_id}/read", headers=alice["headers"])
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["read_at"] == second.json()["read_at"]


def test_mark_someone_elses_notification_read_returns_404(client, make_user, make_workspace):
    alice = make_user("alice")
    bob = make_user("bob")
    ws = make_workspace(alice, bob)
    entry_id = _create_entry(client, ws["id"], alice["headers"])
    _comment(client, ws["id"], entry_id, bob["headers"])
    alice_notification_id = client.get("/api/notifications", headers=alice["headers"]).json()[0]["id"]

    res = client.post(f"/api/notifications/{alice_notification_id}/read", headers=bob["headers"])
    assert res.status_code == 404

    # And it must genuinely still be unread for alice - bob's attempt
    # didn't silently succeed against the wrong row.
    res = client.get("/api/notifications", headers=alice["headers"])
    assert res.json()[0]["read_at"] is None


def test_mark_read_nonexistent_notification_returns_404(client, make_user):
    alice = make_user("alice")
    res = client.post("/api/notifications/999999/read", headers=alice["headers"])
    assert res.status_code == 404


def test_mark_all_read(client, make_user, make_workspace):
    alice = make_user("alice")
    bob = make_user("bob")
    ws = make_workspace(alice, bob)
    entry_id = _create_entry(client, ws["id"], alice["headers"])
    _comment(client, ws["id"], entry_id, bob["headers"], body="one")
    _comment(client, ws["id"], entry_id, bob["headers"], body="two")

    res = client.post("/api/notifications/mark-all-read", headers=alice["headers"])
    assert res.status_code == 200

    notifications = client.get("/api/notifications", headers=alice["headers"]).json()
    assert all(n["read_at"] is not None for n in notifications)
    assert client.get("/api/notifications/unread-count", headers=alice["headers"]).json()["count"] == 0


def test_mark_all_read_never_touches_another_users_notifications(client, make_user, make_workspace):
    alice = make_user("alice")
    bob = make_user("bob")
    carol = make_user("carol")
    ws = make_workspace(alice, bob, carol)
    entry_id = _create_entry(client, ws["id"], alice["headers"])
    _comment(client, ws["id"], entry_id, bob["headers"])

    res = client.post("/api/notifications/mark-all-read", headers=carol["headers"])
    assert res.status_code == 200

    # Alice's notification from bob's comment is untouched by carol's
    # mark-all-read call.
    alice_notifications = client.get("/api/notifications", headers=alice["headers"]).json()
    assert alice_notifications[0]["read_at"] is None
