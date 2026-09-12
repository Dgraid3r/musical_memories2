"""JournalEntry.playlist_id/name/url are nullable specifically to support
offline-created drafts (see the PWA offline-drafts feature): a draft
captured with no network access has no way to search Spotify, so it
must be creatable - and later completable - with no playlist at all.
See models.JournalEntry's comment and schemas.EntryPlaylistInput."""


def _create_entry(client, workspace_id, headers, **overrides):
    data = {
        "start_date": "2026-01-01",
        "text": "an offline draft, synced",
        "is_public": "false",
    }
    data.update(overrides)
    res = client.post(f"/api/workspaces/{workspace_id}/entries", headers=headers, data=data)
    return res


def test_create_entry_with_no_playlist_succeeds(client, make_user, make_workspace):
    alice = make_user("alice")
    ws = make_workspace(alice, name="Solo")

    res = _create_entry(client, ws["id"], alice["headers"])
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["playlist_id"] is None
    assert body["playlist_name"] is None
    assert body["playlist_url"] is None
    assert body["playlist_image_url"] is None
    assert body["text"] == "an offline draft, synced"


def test_create_entry_with_full_playlist_still_works(client, make_user, make_workspace):
    alice = make_user("alice")
    ws = make_workspace(alice, name="Solo")

    res = _create_entry(
        client,
        ws["id"],
        alice["headers"],
        playlist_id="p1",
        playlist_name="Test Playlist",
        playlist_url="https://open.spotify.com/playlist/p1",
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["playlist_id"] == "p1"
    assert body["playlist_name"] == "Test Playlist"


def test_create_entry_with_partial_playlist_is_rejected(client, make_user, make_workspace):
    """Never a half-set playlist - all three or none, same discipline as
    latitude/longitude."""
    alice = make_user("alice")
    ws = make_workspace(alice, name="Solo")

    res = _create_entry(client, ws["id"], alice["headers"], playlist_id="p1")
    assert res.status_code == 422


def test_playlistless_entry_appears_in_list_and_get(client, make_user, make_workspace):
    alice = make_user("alice")
    ws = make_workspace(alice, name="Solo")
    created = _create_entry(client, ws["id"], alice["headers"]).json()

    list_res = client.get(f"/api/workspaces/{ws['id']}/entries", headers=alice["headers"])
    assert list_res.status_code == 200
    assert any(e["id"] == created["id"] and e["playlist_id"] is None for e in list_res.json())

    get_res = client.get(f"/api/workspaces/{ws['id']}/entries/{created['id']}", headers=alice["headers"])
    assert get_res.status_code == 200
    assert get_res.json()["playlist_id"] is None


def test_owner_can_add_playlist_to_a_playlistless_entry(client, make_user, make_workspace):
    alice = make_user("alice")
    ws = make_workspace(alice, name="Solo")
    entry = _create_entry(client, ws["id"], alice["headers"]).json()
    assert entry["playlist_id"] is None

    res = client.patch(
        f"/api/workspaces/{ws['id']}/entries/{entry['id']}",
        headers=alice["headers"],
        json={
            "playlist": {
                "playlist_id": "p1",
                "playlist_name": "Added Later",
                "playlist_url": "https://open.spotify.com/playlist/p1",
                "playlist_image_url": "https://example.com/cover.png",
            }
        },
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["playlist_id"] == "p1"
    assert body["playlist_name"] == "Added Later"
    assert body["playlist_image_url"] == "https://example.com/cover.png"


def test_coauthor_can_add_playlist_same_as_other_content_edits(client, make_user, make_workspace):
    """Playlist is content, like text/tags - a co-author (not just the
    primary author) can set it."""
    alice = make_user("alice")
    bob = make_user("bob")
    ws = make_workspace(alice, bob)
    entry_res = client.post(
        f"/api/workspaces/{ws['id']}/entries",
        headers=alice["headers"],
        data={"start_date": "2026-01-01", "is_public": "false"},
        files=[("coauthor_usernames", (None, "bob"))],
    )
    assert entry_res.status_code == 201, entry_res.text
    entry = entry_res.json()

    res = client.patch(
        f"/api/workspaces/{ws['id']}/entries/{entry['id']}",
        headers=bob["headers"],
        json={
            "playlist": {
                "playlist_id": "p1",
                "playlist_name": "Bob's Pick",
                "playlist_url": "https://open.spotify.com/playlist/p1",
            }
        },
    )
    assert res.status_code == 200, res.text
    assert res.json()["playlist_name"] == "Bob's Pick"


def test_updating_playlist_records_an_edit_event(client, make_user, make_workspace):
    alice = make_user("alice")
    ws = make_workspace(alice, name="Solo")
    entry = _create_entry(client, ws["id"], alice["headers"]).json()

    client.patch(
        f"/api/workspaces/{ws['id']}/entries/{entry['id']}",
        headers=alice["headers"],
        json={
            "playlist": {
                "playlist_id": "p1",
                "playlist_name": "Added Later",
                "playlist_url": "https://open.spotify.com/playlist/p1",
            }
        },
    )
    history = client.get(
        f"/api/workspaces/{ws['id']}/entries/{entry['id']}/edit-history", headers=alice["headers"]
    ).json()
    assert len(history) == 1
    assert "playlist" in history[0]["change_summary"]


def test_resending_the_same_playlist_is_a_no_op_not_a_new_edit_event(client, make_user, make_workspace):
    alice = make_user("alice")
    ws = make_workspace(alice, name="Solo")
    entry = _create_entry(
        client,
        ws["id"],
        alice["headers"],
        playlist_id="p1",
        playlist_name="Test",
        playlist_url="https://open.spotify.com/playlist/p1",
    ).json()

    res = client.patch(
        f"/api/workspaces/{ws['id']}/entries/{entry['id']}",
        headers=alice["headers"],
        json={
            "playlist": {
                "playlist_id": "p1",
                "playlist_name": "Test",
                "playlist_url": "https://open.spotify.com/playlist/p1",
            }
        },
    )
    assert res.status_code == 200
    history = client.get(
        f"/api/workspaces/{ws['id']}/entries/{entry['id']}/edit-history", headers=alice["headers"]
    ).json()
    assert history == []
