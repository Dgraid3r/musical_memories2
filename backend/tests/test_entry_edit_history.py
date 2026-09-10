def _create_entry(
    client,
    workspace_id,
    headers,
    *,
    is_public=True,
    playlist_id="p1",
    text="hello",
    coauthor_usernames=None,
):
    data = {
        "start_date": "2026-01-01",
        "text": text,
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
    return res.json()


def _history(client, workspace_id, entry_id, headers=None):
    return client.get(f"/api/workspaces/{workspace_id}/entries/{entry_id}/edit-history", headers=headers or {})


# --- Recording events on real edits -----------------------------------------


def test_patch_with_real_change_records_event(client, make_user, make_workspace):
    alice = make_user("alice")
    ws = make_workspace(alice)
    entry = _create_entry(client, ws["id"], alice["headers"], text="original")

    res = client.patch(
        f"/api/workspaces/{ws['id']}/entries/{entry['id']}",
        headers=alice["headers"],
        json={"text": "updated"},
    )
    assert res.status_code == 200

    hist_res = _history(client, ws["id"], entry["id"], alice["headers"])
    assert hist_res.status_code == 200
    events = hist_res.json()
    assert len(events) == 1
    event = events[0]
    assert event["editor_user_id"] == alice["id"]
    assert event["editor_username"] == "alice"
    assert event["change_summary"] == "content"
    assert event["edited_at"] is not None


def test_noop_patch_does_not_record_an_event(client, make_user, make_workspace):
    """Resending the entry's current values (same text) must not add a
    noise entry to the history."""
    alice = make_user("alice")
    ws = make_workspace(alice)
    entry = _create_entry(client, ws["id"], alice["headers"], text="same text")

    res = client.patch(
        f"/api/workspaces/{ws['id']}/entries/{entry['id']}",
        headers=alice["headers"],
        json={"text": "same text"},
    )
    assert res.status_code == 200

    events = _history(client, ws["id"], entry["id"], alice["headers"]).json()
    assert events == []


def test_patch_with_no_fields_records_no_event(client, make_user, make_workspace):
    alice = make_user("alice")
    ws = make_workspace(alice)
    entry = _create_entry(client, ws["id"], alice["headers"])

    res = client.patch(f"/api/workspaces/{ws['id']}/entries/{entry['id']}", headers=alice["headers"], json={})
    assert res.status_code == 200

    events = _history(client, ws["id"], entry["id"], alice["headers"]).json()
    assert events == []


def test_tags_noop_does_not_record_event_but_real_tag_change_does(client, make_user, make_workspace):
    alice = make_user("alice")
    ws = make_workspace(alice)
    entry = _create_entry(client, ws["id"], alice["headers"])

    # First set some tags - a real change.
    res = client.patch(
        f"/api/workspaces/{ws['id']}/entries/{entry['id']}",
        headers=alice["headers"],
        json={"tags": ["roadtrip"]},
    )
    assert res.status_code == 200

    # Resending the identical tag set is a no-op.
    res = client.patch(
        f"/api/workspaces/{ws['id']}/entries/{entry['id']}",
        headers=alice["headers"],
        json={"tags": ["roadtrip"]},
    )
    assert res.status_code == 200

    events = _history(client, ws["id"], entry["id"], alice["headers"]).json()
    assert len(events) == 1
    assert events[0]["change_summary"] == "tags"


def test_visibility_and_coauthor_changes_recorded_separately(client, make_user, make_workspace):
    alice = make_user("alice")
    bob = make_user("bob")
    ws = make_workspace(alice, bob)
    entry = _create_entry(client, ws["id"], alice["headers"], is_public=False)

    res = client.patch(
        f"/api/workspaces/{ws['id']}/entries/{entry['id']}",
        headers=alice["headers"],
        json={"is_public": True, "coauthor_usernames": ["bob"]},
    )
    assert res.status_code == 200

    events = _history(client, ws["id"], entry["id"], alice["headers"]).json()
    assert len(events) == 1
    summary = events[0]["change_summary"]
    assert "visibility" in summary
    assert "coauthors" in summary


def test_multiple_edits_recorded_most_recent_first(client, make_user, make_workspace):
    alice = make_user("alice")
    ws = make_workspace(alice)
    entry = _create_entry(client, ws["id"], alice["headers"], text="v1")

    for text in ("v2", "v3"):
        res = client.patch(
            f"/api/workspaces/{ws['id']}/entries/{entry['id']}",
            headers=alice["headers"],
            json={"text": text},
        )
        assert res.status_code == 200

    events = _history(client, ws["id"], entry["id"], alice["headers"]).json()
    assert len(events) == 2
    # Most recent edit (v1 -> v3) listed first.
    assert events[0]["edited_at"] >= events[1]["edited_at"]


def test_adding_images_records_an_event(client, make_user, make_workspace):
    alice = make_user("alice")
    ws = make_workspace(alice)
    entry = _create_entry(client, ws["id"], alice["headers"])

    res = client.post(
        f"/api/workspaces/{ws['id']}/entries/{entry['id']}/images",
        headers=alice["headers"],
        files=[("images", ("photo.png", b"fake image bytes", "image/png"))],
    )
    assert res.status_code == 201

    events = _history(client, ws["id"], entry["id"], alice["headers"]).json()
    assert len(events) == 1
    assert events[0]["change_summary"] == "images"
    assert events[0]["editor_user_id"] == alice["id"]


def test_creating_an_entry_records_no_edit_event(client, make_user, make_workspace):
    alice = make_user("alice")
    ws = make_workspace(alice)
    entry = _create_entry(client, ws["id"], alice["headers"])

    events = _history(client, ws["id"], entry["id"], alice["headers"]).json()
    assert events == []


def test_coauthor_edit_recorded_with_coauthor_as_editor(client, make_user, make_workspace):
    alice = make_user("alice")
    bob = make_user("bob")
    ws = make_workspace(alice, bob)
    entry = _create_entry(client, ws["id"], alice["headers"], coauthor_usernames=["bob"])

    res = client.patch(
        f"/api/workspaces/{ws['id']}/entries/{entry['id']}",
        headers=bob["headers"],
        json={"text": "bob's edit"},
    )
    assert res.status_code == 200

    events = _history(client, ws["id"], entry["id"], alice["headers"]).json()
    assert len(events) == 1
    assert events[0]["editor_user_id"] == bob["id"]
    assert events[0]["editor_username"] == "bob"


# --- Deleted-editor masking ---------------------------------------------


def test_deleted_editors_name_shows_as_deleted_user_in_history(client, make_user, make_workspace):
    alice = make_user("alice")
    bob = make_user("bob")
    # bob owns the workspace so alice (a plain member) can delete her own
    # account with no ownership transfer needed.
    ws = make_workspace(bob, alice)
    entry = _create_entry(client, ws["id"], bob["headers"], coauthor_usernames=["alice"])

    res = client.patch(
        f"/api/workspaces/{ws['id']}/entries/{entry['id']}",
        headers=alice["headers"],
        json={"text": "alice's edit before she deletes her account"},
    )
    assert res.status_code == 200

    del_res = client.request(
        "DELETE", "/api/account", headers=alice["headers"], json={"password": "password123"}
    )
    assert del_res.status_code == 200

    events = _history(client, ws["id"], entry["id"], bob["headers"]).json()
    assert len(events) == 1
    assert events[0]["editor_username"] == "Deleted user"
    assert events[0]["editor_user_id"] == alice["id"]  # the id itself is unchanged, only the name is masked


# --- Visibility matches the entry's own rules -------------------------------


def test_edit_history_requires_auth_for_private_entry(client, make_user, make_workspace):
    alice = make_user("alice")
    ws = make_workspace(alice)
    entry = _create_entry(client, ws["id"], alice["headers"], is_public=False)

    res = _history(client, ws["id"], entry["id"])
    assert res.status_code == 404


def test_edit_history_404s_for_someone_who_cannot_see_the_entry(client, make_user, make_workspace):
    alice = make_user("alice")
    outsider = make_user("outsider")
    ws = make_workspace(alice)  # private workspace, outsider not a member
    entry = _create_entry(client, ws["id"], alice["headers"], is_public=True)

    res = _history(client, ws["id"], entry["id"], outsider["headers"])
    assert res.status_code == 404


def test_edit_history_404s_for_private_entry_non_coauthor_member(client, make_user, make_workspace):
    alice = make_user("alice")
    bob = make_user("bob")
    ws = make_workspace(alice, bob)
    entry = _create_entry(client, ws["id"], alice["headers"], is_public=False)

    res = _history(client, ws["id"], entry["id"], bob["headers"])
    assert res.status_code == 404


def test_edit_history_visible_to_anyone_who_can_see_a_public_entry(client, make_user, make_workspace):
    alice = make_user("alice")
    bob = make_user("bob")
    ws = make_workspace(alice, bob)
    entry = _create_entry(client, ws["id"], alice["headers"], is_public=True)

    client.patch(
        f"/api/workspaces/{ws['id']}/entries/{entry['id']}",
        headers=alice["headers"],
        json={"text": "updated"},
    )

    res = _history(client, ws["id"], entry["id"], bob["headers"])
    assert res.status_code == 200
    assert len(res.json()) == 1


def test_edit_history_on_public_workspace_public_entry_visible_anonymously(client, make_user, make_workspace):
    alice = make_user("alice")
    ws = make_workspace(alice)
    client_ = client
    vis_res = client_.patch(
        f"/api/workspaces/{ws['id']}", headers=alice["headers"], json={"visibility": "public"}
    )
    assert vis_res.status_code == 200
    entry = _create_entry(client, ws["id"], alice["headers"], is_public=True)

    client.patch(
        f"/api/workspaces/{ws['id']}/entries/{entry['id']}",
        headers=alice["headers"],
        json={"text": "updated"},
    )

    res = _history(client, ws["id"], entry["id"])  # no auth headers at all
    assert res.status_code == 200
    assert len(res.json()) == 1
