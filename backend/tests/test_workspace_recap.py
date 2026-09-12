from sqlalchemy import select

from app.models import WorkspaceRecap


def _create_entry(
    client,
    workspace_id,
    headers,
    *,
    start_date,
    playlist_id="p1",
    playlist_name="Playlist",
    tags=None,
    coauthor_usernames=None,
    images=None,
    text="hello",
):
    data = {
        "start_date": start_date,
        "text": text,
        "playlist_id": playlist_id,
        "playlist_name": playlist_name,
        "playlist_url": f"https://open.spotify.com/playlist/{playlist_id}",
        "is_public": "false",
    }
    files = [("tags", (None, t)) for t in (tags or [])]
    files += [("coauthor_usernames", (None, u)) for u in (coauthor_usernames or [])]
    files += list(images or [])
    res = client.post(
        f"/api/workspaces/{workspace_id}/entries", headers=headers, data=data, files=files or None
    )
    assert res.status_code == 201, res.text
    return res.json()


def _enable_sharing(client, workspace_id, year, headers):
    return client.post(f"/api/workspaces/{workspace_id}/recap/{year}/share", headers=headers)


def _disable_sharing(client, workspace_id, year, headers):
    return client.request("DELETE", f"/api/workspaces/{workspace_id}/recap/{year}/share", headers=headers)


# --- Aggregation correctness -----------------------------------------------


def test_recap_computes_correct_stats_against_known_fixture(client, make_user, make_workspace):
    alice = make_user("alice")
    bob = make_user("bob")
    ws = make_workspace(alice, bob)

    _create_entry(
        client,
        ws["id"],
        alice["headers"],
        start_date="2026-01-05",
        playlist_id="p1",
        playlist_name="Road Trip Mix",
        tags=["roadtrip"],
        images=[("images", ("a.png", b"a", "image/png"))],
    )
    _create_entry(
        client,
        ws["id"],
        alice["headers"],
        start_date="2026-03-02",
        playlist_id="p2",
        playlist_name="Spring Vibes",
        tags=["roadtrip", "spring"],
    )
    _create_entry(
        client,
        ws["id"],
        bob["headers"],
        start_date="2026-03-20",
        playlist_id="p2",
        playlist_name="Spring Vibes",
        tags=["spring"],
        images=[("images", ("b.png", b"b", "image/png")), ("images", ("c.png", b"c", "image/png"))],
    )
    _create_entry(client, ws["id"], alice["headers"], start_date="2026-03-25", playlist_id="p3", playlist_name="One Off")
    # Outside the recapped year entirely - must not affect any stat below.
    _create_entry(client, ws["id"], alice["headers"], start_date="2025-12-31", playlist_id="p-old", playlist_name="Old")

    res = client.get(f"/api/workspaces/{ws['id']}/recap/2026", headers=alice["headers"])
    assert res.status_code == 200, res.text
    body = res.json()

    assert body["year"] == 2026
    assert body["entry_count"] == 4
    assert body["photo_count"] == 3
    assert body["most_active_month"] == "March"

    tag_counts = {t["name"]: t["count"] for t in body["top_tags"]}
    assert tag_counts == {"roadtrip": 2, "spring": 2}

    assert body["first_entry"] == {
        "start_date": "2026-01-05",
        "playlist_name": "Road Trip Mix",
        "playlist_image_url": None,
    }
    assert body["last_entry"] == {
        "start_date": "2026-03-25",
        "playlist_name": "One Off",
        "playlist_image_url": None,
    }

    contributor_usernames = {c["username"] for c in body["contributors"]}
    assert contributor_usernames == {"alice", "bob"}

    assert len(body["top_playlists"]) == 1
    assert body["top_playlists"][0]["playlist_id"] == "p2"
    assert body["top_playlists"][0]["count"] == 2


def test_most_active_month_tie_break_is_deterministic(client, make_user, make_workspace):
    """Two months tied at one entry each - the earlier calendar month
    wins, deterministically (not dependent on dict/insertion order)."""
    alice = make_user("alice")
    ws = make_workspace(alice, name="Solo")
    _create_entry(client, ws["id"], alice["headers"], start_date="2026-05-01")
    _create_entry(client, ws["id"], alice["headers"], start_date="2026-02-01")

    res = client.get(f"/api/workspaces/{ws['id']}/recap/2026", headers=alice["headers"])
    assert res.json()["most_active_month"] == "February"


def test_contributors_empty_for_solo_workspace(client, make_user, make_workspace):
    """A single-person 'who showed up this year' list is trivial, so it's
    left empty rather than shown - see WorkspaceRecapOut's docstring."""
    alice = make_user("alice")
    ws = make_workspace(alice, name="Solo")
    _create_entry(client, ws["id"], alice["headers"], start_date="2026-02-01")

    res = client.get(f"/api/workspaces/{ws['id']}/recap/2026", headers=alice["headers"])
    assert res.json()["contributors"] == []


def test_top_playlists_empty_when_nothing_repeats(client, make_user, make_workspace):
    alice = make_user("alice")
    ws = make_workspace(alice, name="Solo")
    _create_entry(client, ws["id"], alice["headers"], start_date="2026-02-01", playlist_id="p1")
    _create_entry(client, ws["id"], alice["headers"], start_date="2026-03-01", playlist_id="p2")

    res = client.get(f"/api/workspaces/{ws['id']}/recap/2026", headers=alice["headers"])
    assert res.json()["top_playlists"] == []


def test_recap_for_year_with_no_entries_is_valid_not_an_error(client, make_user, make_workspace):
    alice = make_user("alice")
    ws = make_workspace(alice, name="Solo")

    res = client.get(f"/api/workspaces/{ws['id']}/recap/2099", headers=alice["headers"])
    assert res.status_code == 200
    body = res.json()
    assert body == {
        "year": 2099,
        "entry_count": 0,
        "photo_count": 0,
        "top_tags": [],
        "most_active_month": None,
        "first_entry": None,
        "last_entry": None,
        "contributors": [],
        "top_playlists": [],
    }


# --- Row get-or-create -------------------------------------------------


def test_recap_row_created_once_and_reused_across_views(client, make_user, make_workspace, db_session):
    alice = make_user("alice")
    ws = make_workspace(alice, name="Solo")

    client.get(f"/api/workspaces/{ws['id']}/recap/2026", headers=alice["headers"])
    client.get(f"/api/workspaces/{ws['id']}/recap/2026", headers=alice["headers"])

    rows = db_session.scalars(
        select(WorkspaceRecap).where(WorkspaceRecap.workspace_id == ws["id"], WorkspaceRecap.year == 2026)
    ).all()
    assert len(rows) == 1


# --- Permissions: generating/toggling sharing is owner-only -----------


def test_plain_member_cannot_enable_recap_sharing(client, make_user, make_workspace):
    alice = make_user("alice")
    bob = make_user("bob")
    ws = make_workspace(alice, bob)

    res = _enable_sharing(client, ws["id"], 2026, bob["headers"])
    assert res.status_code == 403


def test_non_member_cannot_enable_recap_sharing(client, make_user, make_workspace):
    alice = make_user("alice")
    dave = make_user("dave")
    ws = make_workspace(alice, name="Solo")

    res = _enable_sharing(client, ws["id"], 2026, dave["headers"])
    assert res.status_code == 404  # non-disclosure, same as everywhere else


def test_enable_recap_sharing_idempotent_not_rotated(client, make_user, make_workspace):
    alice = make_user("alice")
    ws = make_workspace(alice, name="Solo")

    first = _enable_sharing(client, ws["id"], 2026, alice["headers"])
    second = _enable_sharing(client, ws["id"], 2026, alice["headers"])
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["share_token"] == second.json()["share_token"]


def test_disable_recap_sharing_clears_token_and_old_link_404s(client, make_user, make_workspace):
    alice = make_user("alice")
    ws = make_workspace(alice, name="Solo")

    token = _enable_sharing(client, ws["id"], 2026, alice["headers"]).json()["share_token"]
    assert client.get(f"/api/shared-recap/{token}").status_code == 200

    disable_res = _disable_sharing(client, ws["id"], 2026, alice["headers"])
    assert disable_res.status_code == 204
    assert client.get(f"/api/shared-recap/{token}").status_code == 404


def test_disabling_when_never_shared_is_a_harmless_no_op(client, make_user, make_workspace):
    alice = make_user("alice")
    ws = make_workspace(alice, name="Solo")

    res = _disable_sharing(client, ws["id"], 2026, alice["headers"])
    assert res.status_code == 204


def test_plain_member_cannot_disable_recap_sharing(client, make_user, make_workspace):
    alice = make_user("alice")
    bob = make_user("bob")
    ws = make_workspace(alice, bob)

    token = _enable_sharing(client, ws["id"], 2026, alice["headers"]).json()["share_token"]
    res = _disable_sharing(client, ws["id"], 2026, bob["headers"])
    assert res.status_code == 403
    # Unaffected by bob's failed attempt.
    assert client.get(f"/api/shared-recap/{token}").status_code == 200


# --- In-app viewing: any member, not owner-only -------------------------


def test_any_workspace_member_can_view_recap_in_app(client, make_user, make_workspace):
    alice = make_user("alice")
    bob = make_user("bob")
    ws = make_workspace(alice, bob)

    res = client.get(f"/api/workspaces/{ws['id']}/recap/2026", headers=bob["headers"])
    assert res.status_code == 200


def test_non_member_cannot_view_recap_in_app(client, make_user, make_workspace):
    alice = make_user("alice")
    dave = make_user("dave")
    ws = make_workspace(alice, name="Solo")

    res = client.get(f"/api/workspaces/{ws['id']}/recap/2026", headers=dave["headers"])
    assert res.status_code == 404


# --- Public shared-recap endpoint ---------------------------------------


def test_invalid_shared_recap_token_404s(client):
    res = client.get("/api/shared-recap/not-a-real-token")
    assert res.status_code == 404


def test_shared_recap_response_contains_only_aggregate_stats(client, make_user, make_workspace):
    alice = make_user("alice")
    ws = make_workspace(alice, name="Top Secret Workspace Name")
    _create_entry(client, ws["id"], alice["headers"], start_date="2026-05-01", text="a very private journal secret")

    token = _enable_sharing(client, ws["id"], 2026, alice["headers"]).json()["share_token"]
    res = client.get(f"/api/shared-recap/{token}")
    assert res.status_code == 200
    body = res.json()

    assert set(body.keys()) == {
        "year",
        "entry_count",
        "photo_count",
        "top_tags",
        "most_active_month",
        "first_entry",
        "last_entry",
        "contributors",
        "top_playlists",
    }
    dumped = str(body)
    assert "a very private journal secret" not in dumped
    assert "Top Secret Workspace Name" not in dumped
    assert "workspace" not in dumped.lower()


def test_shared_recap_matches_authenticated_in_app_recap(client, make_user, make_workspace):
    """The public and authenticated surfaces must never diverge - both
    call the same aggregation function."""
    alice = make_user("alice")
    ws = make_workspace(alice, name="Solo")
    _create_entry(client, ws["id"], alice["headers"], start_date="2026-04-01", tags=["x"])

    token = _enable_sharing(client, ws["id"], 2026, alice["headers"]).json()["share_token"]
    authed = client.get(f"/api/workspaces/{ws['id']}/recap/2026", headers=alice["headers"]).json()
    public = client.get(f"/api/shared-recap/{token}").json()
    assert authed == public


def test_shared_recap_image_bytes_never_appear(client, make_user, make_workspace):
    """Photo *bytes* are never part of the recap payload at all - only a
    count. Sanity check that uploading a photo doesn't leak its content
    into the shared aggregate."""
    alice = make_user("alice")
    ws = make_workspace(alice, name="Solo")
    _create_entry(
        client,
        ws["id"],
        alice["headers"],
        start_date="2026-06-01",
        images=[("images", ("secret.png", b"unique-photo-bytes-marker", "image/png"))],
    )
    token = _enable_sharing(client, ws["id"], 2026, alice["headers"]).json()["share_token"]

    res = client.get(f"/api/shared-recap/{token}")
    assert b"unique-photo-bytes-marker" not in res.content
    assert res.json()["photo_count"] == 1


# --- Interaction with playlist-less entries (offline drafts) -----------


def _create_entry_without_playlist(client, workspace_id, headers, *, start_date, text="an offline draft"):
    res = client.post(
        f"/api/workspaces/{workspace_id}/entries",
        headers=headers,
        data={"start_date": start_date, "text": text, "is_public": "false"},
    )
    assert res.status_code == 201, res.text
    return res.json()


def test_recap_handles_entry_with_no_playlist_as_first_and_last(client, make_user, make_workspace):
    """An entry synced from an offline draft has no playlist at all -
    the recap must still be able to name it as the year's first/last
    entry rather than erroring."""
    alice = make_user("alice")
    ws = make_workspace(alice, name="Solo")
    _create_entry_without_playlist(client, ws["id"], alice["headers"], start_date="2026-01-01")

    res = client.get(f"/api/workspaces/{ws['id']}/recap/2026", headers=alice["headers"])
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["entry_count"] == 1
    assert body["first_entry"] == {"start_date": "2026-01-01", "playlist_name": None, "playlist_image_url": None}
    assert body["last_entry"] == body["first_entry"]


def test_recap_excludes_playlistless_entries_from_top_playlists(client, make_user, make_workspace):
    """Multiple entries with no playlist must never be counted together
    as if "no playlist" were itself a repeated playlist."""
    alice = make_user("alice")
    ws = make_workspace(alice, name="Solo")
    _create_entry_without_playlist(client, ws["id"], alice["headers"], start_date="2026-02-01")
    _create_entry_without_playlist(client, ws["id"], alice["headers"], start_date="2026-03-01")
    _create_entry_without_playlist(client, ws["id"], alice["headers"], start_date="2026-04-01")

    res = client.get(f"/api/workspaces/{ws['id']}/recap/2026", headers=alice["headers"])
    assert res.status_code == 200, res.text
    assert res.json()["top_playlists"] == []


def test_recap_top_playlists_still_correct_alongside_playlistless_entries(client, make_user, make_workspace):
    alice = make_user("alice")
    ws = make_workspace(alice, name="Solo")
    _create_entry_without_playlist(client, ws["id"], alice["headers"], start_date="2026-01-01")
    _create_entry_without_playlist(client, ws["id"], alice["headers"], start_date="2026-02-01")
    _create_entry(client, ws["id"], alice["headers"], start_date="2026-03-01", playlist_id="p1")
    _create_entry(client, ws["id"], alice["headers"], start_date="2026-03-15", playlist_id="p1")

    res = client.get(f"/api/workspaces/{ws['id']}/recap/2026", headers=alice["headers"])
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["entry_count"] == 4
    assert len(body["top_playlists"]) == 1
    assert body["top_playlists"][0]["playlist_id"] == "p1"
    assert body["top_playlists"][0]["count"] == 2
