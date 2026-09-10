"""Sorting, pagination, and the entry_count/last_active_at aggregate fields
on GET /api/workspaces/public. See test_workspaces_visibility.py for the
core visibility/security tests on this endpoint (never lists a private
workspace, never leaks entry content, name filter, requires no auth)."""

import time


def _create_entry(client, workspace_id, headers, *, is_public=True, playlist_id="p1", text="hello"):
    res = client.post(
        f"/api/workspaces/{workspace_id}/entries",
        headers=headers,
        data={
            "start_date": "2026-01-01",
            "text": text,
            "playlist_id": playlist_id,
            "playlist_name": "Test Playlist",
            "playlist_url": f"https://open.spotify.com/playlist/{playlist_id}",
            "is_public": str(is_public).lower(),
        },
    )
    assert res.status_code == 201, res.text
    return res.json()


def _set_visibility(client, owner, workspace_id, visibility="public"):
    res = client.patch(f"/api/workspaces/{workspace_id}", headers=owner["headers"], json={"visibility": visibility})
    assert res.status_code == 200, res.text
    return res.json()


# --- Sorting -----------------------------------------------------------


def test_default_sort_is_active(client, make_user, make_workspace):
    """No `sort` param at all defaults to "active"."""
    alice = make_user("alice")
    ws_old = make_workspace(alice, name="Old Activity")
    _set_visibility(client, alice, ws_old["id"])
    _create_entry(client, ws_old["id"], alice["headers"], playlist_id="p-old")

    time.sleep(0.05)
    ws_new = make_workspace(alice, name="Aaa Newest Activity")  # alphabetically first, but newest activity
    _set_visibility(client, alice, ws_new["id"])
    _create_entry(client, ws_new["id"], alice["headers"], playlist_id="p-new")

    res = client.get("/api/workspaces/public")
    assert res.status_code == 200
    ids = [w["id"] for w in res.json()]
    # The most-recently-active workspace comes first even though its name
    # would sort alphabetically ahead under a "name" sort too - the real
    # proof this is really sorting by activity (not accidentally by name)
    # is test_sort_active_orders_by_most_recent_entry below.
    assert ids.index(ws_new["id"]) < ids.index(ws_old["id"])


def test_sort_active_orders_by_most_recent_entry(client, make_user, make_workspace):
    alice = make_user("alice")
    ws_a = make_workspace(alice, name="Zzz Workspace")  # alphabetically last
    ws_b = make_workspace(alice, name="Aaa Workspace")  # alphabetically first
    _set_visibility(client, alice, ws_a["id"])
    _set_visibility(client, alice, ws_b["id"])

    # ws_a gets the more recent entry, despite sorting after ws_b by name.
    _create_entry(client, ws_b["id"], alice["headers"], playlist_id="p-b")
    time.sleep(0.05)
    _create_entry(client, ws_a["id"], alice["headers"], playlist_id="p-a")

    res = client.get("/api/workspaces/public?sort=active")
    assert res.status_code == 200
    ids = [w["id"] for w in res.json()]
    assert ids.index(ws_a["id"]) < ids.index(ws_b["id"])


def test_sort_active_falls_back_to_workspace_created_at_when_no_entries(client, make_user, make_workspace):
    """An empty workspace is never excluded from discovery - just ranked
    among the others (including other empty ones) by its own created_at."""
    alice = make_user("alice")
    ws_older = make_workspace(alice, name="Older Empty")
    _set_visibility(client, alice, ws_older["id"])

    time.sleep(0.05)
    ws_newer = make_workspace(alice, name="Newer Empty")
    _set_visibility(client, alice, ws_newer["id"])

    res = client.get("/api/workspaces/public?sort=active")
    assert res.status_code == 200
    ids = [w["id"] for w in res.json()]
    assert ids.index(ws_newer["id"]) < ids.index(ws_older["id"])

    # Both report zero entries and last_active_at == their own created_at.
    by_id = {w["id"]: w for w in res.json()}
    assert by_id[ws_older["id"]]["entry_count"] == 0
    assert by_id[ws_older["id"]]["last_active_at"] == by_id[ws_older["id"]]["created_at"]
    assert by_id[ws_newer["id"]]["entry_count"] == 0
    assert by_id[ws_newer["id"]]["last_active_at"] == by_id[ws_newer["id"]]["created_at"]


def test_sort_active_mixes_empty_and_nonempty_workspaces_correctly(client, make_user, make_workspace):
    """An empty workspace created after a nonempty one's last entry ranks
    ahead of it under "active" sort - "active" really means most recent
    activity of any kind (an entry, or just the workspace's own creation),
    not "nonempty workspaces first"."""
    alice = make_user("alice")
    ws_nonempty = make_workspace(alice, name="Has An Old Entry")
    _set_visibility(client, alice, ws_nonempty["id"])
    _create_entry(client, ws_nonempty["id"], alice["headers"])

    time.sleep(0.05)
    ws_empty_but_newer = make_workspace(alice, name="Empty But Just Created")
    _set_visibility(client, alice, ws_empty_but_newer["id"])

    res = client.get("/api/workspaces/public?sort=active")
    assert res.status_code == 200
    ids = [w["id"] for w in res.json()]
    assert ids.index(ws_empty_but_newer["id"]) < ids.index(ws_nonempty["id"])


def test_sort_name_matches_alphabetical_order(client, make_user, make_workspace):
    alice = make_user("alice")
    ws_z = make_workspace(alice, name="Zzz Workspace")
    ws_a = make_workspace(alice, name="Aaa Workspace")
    _set_visibility(client, alice, ws_z["id"])
    _set_visibility(client, alice, ws_a["id"])
    # Give ws_z the more recent activity, to prove sort=name really ignores
    # activity recency entirely (today's pre-existing behavior).
    _create_entry(client, ws_z["id"], alice["headers"])

    res = client.get("/api/workspaces/public?sort=name")
    assert res.status_code == 200
    ids = [w["id"] for w in res.json()]
    assert ids.index(ws_a["id"]) < ids.index(ws_z["id"])


# --- Pagination ----------------------------------------------------------


def test_limit_caps_the_number_of_results(client, make_user, make_workspace):
    alice = make_user("alice")
    for i in range(5):
        ws = make_workspace(alice, name=f"Workspace {i}")
        _set_visibility(client, alice, ws["id"])

    res = client.get("/api/workspaces/public?limit=2")
    assert res.status_code == 200
    assert len(res.json()) == 2


def test_offset_pages_through_distinct_results(client, make_user, make_workspace):
    alice = make_user("alice")
    ids_created = []
    for i in range(5):
        ws = make_workspace(alice, name=f"Paged Workspace {i}")
        _set_visibility(client, alice, ws["id"])
        ids_created.append(ws["id"])

    page1 = client.get("/api/workspaces/public?sort=name&limit=2&offset=0")
    page2 = client.get("/api/workspaces/public?sort=name&limit=2&offset=2")
    assert page1.status_code == 200
    assert page2.status_code == 200
    page1_ids = [w["id"] for w in page1.json()]
    page2_ids = [w["id"] for w in page2.json()]
    assert len(page1_ids) == 2
    assert len(page2_ids) == 2
    assert set(page1_ids).isdisjoint(page2_ids)


def test_limit_rejects_values_above_the_max(client, make_user, make_workspace):
    res = client.get("/api/workspaces/public?limit=101")
    assert res.status_code == 422


def test_limit_rejects_zero_or_negative(client, make_user, make_workspace):
    res = client.get("/api/workspaces/public?limit=0")
    assert res.status_code == 422


def test_offset_rejects_negative(client, make_user, make_workspace):
    res = client.get("/api/workspaces/public?offset=-1")
    assert res.status_code == 422


def test_default_limit_is_twenty(client, make_user, make_workspace):
    alice = make_user("alice")
    for i in range(25):
        ws = make_workspace(alice, name=f"Bulk Workspace {i}")
        _set_visibility(client, alice, ws["id"])

    res = client.get("/api/workspaces/public")
    assert res.status_code == 200
    assert len(res.json()) == 20


# --- entry_count accuracy -------------------------------------------------


def test_entry_count_reflects_actual_number_of_entries(client, make_user, make_workspace):
    alice = make_user("alice")
    ws = make_workspace(alice, name="Counted")
    _set_visibility(client, alice, ws["id"])
    _create_entry(client, ws["id"], alice["headers"], playlist_id="p1")
    _create_entry(client, ws["id"], alice["headers"], playlist_id="p2")
    _create_entry(client, ws["id"], alice["headers"], playlist_id="p3", is_public=False)

    res = client.get("/api/workspaces/public")
    assert res.status_code == 200
    match = next(w for w in res.json() if w["id"] == ws["id"])
    assert match["entry_count"] == 3


def test_entry_count_zero_for_empty_workspace(client, make_user, make_workspace):
    alice = make_user("alice")
    ws = make_workspace(alice, name="Empty")
    _set_visibility(client, alice, ws["id"])

    res = client.get("/api/workspaces/public")
    assert res.status_code == 200
    match = next(w for w in res.json() if w["id"] == ws["id"])
    assert match["entry_count"] == 0
