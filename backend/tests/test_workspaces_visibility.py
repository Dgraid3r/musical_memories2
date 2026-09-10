"""Public/private workspace visibility and the subscriber role.

Priority is the security boundary: a public workspace must be readable by
literally anyone (no token at all) but never writable without one; a
private workspace must be unreadable by anyone lacking a role there,
anonymous or not; a subscriber must be able to read everything a member
can but write nothing.
"""


def _create_entry(client, workspace_id, headers, *, is_public=False, playlist_id="p1", text="hello"):
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


def _set_visibility(client, owner, workspace_id, visibility):
    res = client.patch(f"/api/workspaces/{workspace_id}", headers=owner["headers"], json={"visibility": visibility})
    assert res.status_code == 200, res.text
    return res.json()


def _set_role(client, owner, workspace_id, user_id, role):
    res = client.patch(
        f"/api/workspaces/{workspace_id}/members/{user_id}", headers=owner["headers"], json={"role": role}
    )
    assert res.status_code == 200, res.text
    return res.json()


# --- Toggling visibility -----------------------------------------------


def test_new_workspace_defaults_to_private(client, make_user, make_workspace):
    alice = make_user("alice")
    ws = make_workspace(alice)
    assert ws["visibility"] == "private"


def test_visibility_toggle_owner_only(client, make_user, make_workspace):
    alice = make_user("alice")
    bob = make_user("bob")
    ws = make_workspace(alice, bob)

    res = client.patch(f"/api/workspaces/{ws['id']}", headers=bob["headers"], json={"visibility": "public"})
    assert res.status_code == 403


def test_visibility_toggle_not_a_member_returns_404(client, make_user, make_workspace):
    alice = make_user("alice")
    outsider = make_user("outsider")
    ws = make_workspace(alice)

    res = client.patch(f"/api/workspaces/{ws['id']}", headers=outsider["headers"], json={"visibility": "public"})
    assert res.status_code == 404


def test_visibility_toggle_rejects_invalid_value(client, make_user, make_workspace):
    alice = make_user("alice")
    ws = make_workspace(alice)
    res = client.patch(f"/api/workspaces/{ws['id']}", headers=alice["headers"], json={"visibility": "everyone"})
    assert res.status_code == 422


def test_toggling_public_to_private_immediately_blocks_anonymous_reads(client, make_user, make_workspace):
    """No stale-cache surprises: the very next request reflects the new
    visibility."""
    alice = make_user("alice")
    ws = make_workspace(alice)
    _create_entry(client, ws["id"], alice["headers"], is_public=True, playlist_id="pub")
    _set_visibility(client, alice, ws["id"], "public")

    before = client.get(f"/api/workspaces/{ws['id']}/entries")
    assert before.status_code == 200
    assert len(before.json()) == 1

    _set_visibility(client, alice, ws["id"], "private")

    after = client.get(f"/api/workspaces/{ws['id']}/entries")
    assert after.status_code == 404


def test_toggling_private_to_public_immediately_allows_anonymous_reads(client, make_user, make_workspace):
    alice = make_user("alice")
    ws = make_workspace(alice)
    _create_entry(client, ws["id"], alice["headers"], is_public=True, playlist_id="pub")

    before = client.get(f"/api/workspaces/{ws['id']}/entries")
    assert before.status_code == 404

    _set_visibility(client, alice, ws["id"], "public")

    after = client.get(f"/api/workspaces/{ws['id']}/entries")
    assert after.status_code == 200
    assert [e["playlist_id"] for e in after.json()] == ["pub"]


# --- Public workspace: readable by anyone, writable by no one anonymous --


def test_public_workspace_entries_readable_with_no_auth_token(client, make_user, make_workspace):
    alice = make_user("alice")
    ws = make_workspace(alice)
    entry = _create_entry(client, ws["id"], alice["headers"], is_public=True, playlist_id="pub")
    _set_visibility(client, alice, ws["id"], "public")

    list_res = client.get(f"/api/workspaces/{ws['id']}/entries")
    assert list_res.status_code == 200
    assert [e["playlist_id"] for e in list_res.json()] == ["pub"]

    get_res = client.get(f"/api/workspaces/{ws['id']}/entries/{entry['id']}")
    assert get_res.status_code == 200


def test_public_workspace_private_entry_not_visible_to_anonymous(client, make_user, make_workspace):
    """Workspace publicity never broadens an individually-private entry -
    it stays owner/co-author-only, exactly as in a private workspace."""
    alice = make_user("alice")
    ws = make_workspace(alice)
    entry = _create_entry(client, ws["id"], alice["headers"], is_public=False, playlist_id="priv")
    _set_visibility(client, alice, ws["id"], "public")

    list_res = client.get(f"/api/workspaces/{ws['id']}/entries")
    assert list_res.status_code == 200
    assert list_res.json() == []

    get_res = client.get(f"/api/workspaces/{ws['id']}/entries/{entry['id']}")
    assert get_res.status_code == 404


def test_public_workspace_tags_readable_with_no_auth_token(client, make_user, make_workspace):
    alice = make_user("alice")
    ws = make_workspace(alice)
    res = client.post(
        f"/api/workspaces/{ws['id']}/entries",
        headers=alice["headers"],
        data={
            "start_date": "2026-01-01",
            "playlist_id": "p1",
            "playlist_name": "T",
            "playlist_url": "https://open.spotify.com/playlist/p1",
            "is_public": "true",
        },
        files=[("tags", (None, "roadtrip"))],
    )
    assert res.status_code == 201
    _set_visibility(client, alice, ws["id"], "public")

    tags_res = client.get(f"/api/workspaces/{ws['id']}/entries/tags")
    assert tags_res.status_code == 200
    assert tags_res.json() == ["roadtrip"]


def test_public_workspace_comments_readable_with_no_auth_token(client, make_user, make_workspace):
    alice = make_user("alice")
    ws = make_workspace(alice)
    entry = _create_entry(client, ws["id"], alice["headers"], is_public=True)
    client.post(f"/api/workspaces/{ws['id']}/entries/{entry['id']}/comments", headers=alice["headers"], json={"body": "hi"})
    _set_visibility(client, alice, ws["id"], "public")

    res = client.get(f"/api/workspaces/{ws['id']}/entries/{entry['id']}/comments")
    assert res.status_code == 200
    assert len(res.json()) == 1


def test_public_workspace_search_readable_with_no_auth_token(client, make_user, make_workspace):
    alice = make_user("alice")
    ws = make_workspace(alice)
    _create_entry(client, ws["id"], alice["headers"], is_public=True, text="a mountain retreat", playlist_id="pub")
    _set_visibility(client, alice, ws["id"], "public")

    res = client.get(f"/api/workspaces/{ws['id']}/entries?q=mountain")
    assert res.status_code == 200
    assert [e["playlist_id"] for e in res.json()] == ["pub"]


def test_public_workspace_cannot_be_written_to_without_auth(client, make_user, make_workspace):
    """Readable by anyone, but never writable without a token - creating an
    entry, adding a comment, etc. all still require real auth regardless of
    the workspace's visibility."""
    alice = make_user("alice")
    ws = make_workspace(alice)
    entry = _create_entry(client, ws["id"], alice["headers"], is_public=True)
    _set_visibility(client, alice, ws["id"], "public")

    create_res = client.post(
        f"/api/workspaces/{ws['id']}/entries",
        data={
            "start_date": "2026-01-01",
            "playlist_id": "p2",
            "playlist_name": "T",
            "playlist_url": "https://open.spotify.com/playlist/p2",
        },
    )
    assert create_res.status_code == 401

    comment_res = client.post(
        f"/api/workspaces/{ws['id']}/entries/{entry['id']}/comments", json={"body": "hi"}
    )
    assert comment_res.status_code == 401

    patch_res = client.patch(f"/api/workspaces/{ws['id']}/entries/{entry['id']}", json={"text": "hacked"})
    assert patch_res.status_code == 401

    delete_res = client.delete(f"/api/workspaces/{ws['id']}/entries/{entry['id']}")
    assert delete_res.status_code == 401


# --- Private workspace: unreadable without a role, anonymous or not ------


def test_private_workspace_not_readable_without_auth(client, make_user, make_workspace):
    alice = make_user("alice")
    ws = make_workspace(alice)
    _create_entry(client, ws["id"], alice["headers"], is_public=True)

    assert client.get(f"/api/workspaces/{ws['id']}/entries").status_code == 404


def test_private_workspace_not_readable_by_authenticated_non_member(client, make_user, make_workspace):
    alice = make_user("alice")
    outsider = make_user("outsider")
    ws = make_workspace(alice)
    entry = _create_entry(client, ws["id"], alice["headers"], is_public=True)

    assert client.get(f"/api/workspaces/{ws['id']}/entries", headers=outsider["headers"]).status_code == 404
    assert (
        client.get(f"/api/workspaces/{ws['id']}/entries/{entry['id']}", headers=outsider["headers"]).status_code
        == 404
    )


def test_private_workspace_anonymous_and_missing_workspace_are_indistinguishable(client, make_user, make_workspace):
    alice = make_user("alice")
    ws = make_workspace(alice)

    private_res = client.get(f"/api/workspaces/{ws['id']}/entries")
    missing_res = client.get("/api/workspaces/999999/entries")

    assert private_res.status_code == missing_res.status_code == 404
    assert private_res.json() == missing_res.json()


# --- Public discovery endpoint --------------------------------------------


def test_public_discovery_requires_no_auth(client, make_user, make_workspace):
    alice = make_user("alice")
    ws = make_workspace(alice)
    _set_visibility(client, alice, ws["id"], "public")

    res = client.get("/api/workspaces/public")
    assert res.status_code == 200
    assert any(w["id"] == ws["id"] for w in res.json())


def test_public_discovery_never_lists_a_private_workspace(client, make_user, make_workspace):
    alice = make_user("alice")
    private_ws = make_workspace(alice, name="Private One")
    public_ws = make_workspace(alice, name="Public One")
    _set_visibility(client, alice, public_ws["id"], "public")

    res = client.get("/api/workspaces/public")
    assert res.status_code == 200
    ids = {w["id"] for w in res.json()}
    assert public_ws["id"] in ids
    assert private_ws["id"] not in ids


def test_public_discovery_never_includes_entry_content(client, make_user, make_workspace):
    alice = make_user("alice")
    ws = make_workspace(alice, name="Browsable")
    _create_entry(client, ws["id"], alice["headers"], is_public=True, text="a very specific secret-ish detail")
    _set_visibility(client, alice, ws["id"], "public")

    res = client.get("/api/workspaces/public")
    assert res.status_code == 200
    match = next(w for w in res.json() if w["id"] == ws["id"])
    # entry_count/last_active_at are aggregates (how much/how recent), never
    # entry content - "a very specific secret-ish detail" must not appear
    # anywhere in the response.
    assert set(match.keys()) == {"id", "name", "created_at", "entry_count", "last_active_at"}
    assert "secret-ish" not in res.text


def test_public_discovery_filters_by_name(client, make_user, make_workspace):
    alice = make_user("alice")
    ws_a = make_workspace(alice, name="Roadtrip Diaries")
    ws_b = make_workspace(alice, name="Book Club Notes")
    _set_visibility(client, alice, ws_a["id"], "public")
    _set_visibility(client, alice, ws_b["id"], "public")

    res = client.get("/api/workspaces/public?q=roadtrip")
    assert res.status_code == 200
    assert [w["id"] for w in res.json()] == [ws_a["id"]]


def test_public_discovery_stops_listing_once_made_private_again(client, make_user, make_workspace):
    alice = make_user("alice")
    ws = make_workspace(alice)
    _set_visibility(client, alice, ws["id"], "public")
    assert any(w["id"] == ws["id"] for w in client.get("/api/workspaces/public").json())

    _set_visibility(client, alice, ws["id"], "private")
    assert not any(w["id"] == ws["id"] for w in client.get("/api/workspaces/public").json())


# --- Subscriber role: read everything a member can, write nothing --------


def test_subscriber_role_owner_only_and_valid_values(client, make_user, make_workspace):
    alice = make_user("alice")
    bob = make_user("bob")
    carol = make_user("carol")
    ws = make_workspace(alice, bob, carol)

    res = client.patch(f"/api/workspaces/{ws['id']}/members/{carol['id']}", headers=bob["headers"], json={"role": "subscriber"})
    assert res.status_code == 403

    res = client.patch(f"/api/workspaces/{ws['id']}/members/{carol['id']}", headers=alice["headers"], json={"role": "owner"})
    assert res.status_code == 422

    res = client.patch(f"/api/workspaces/{ws['id']}/members/{alice['id']}", headers=alice["headers"], json={"role": "subscriber"})
    assert res.status_code == 400


def test_subscriber_can_read_entries_and_comments(client, make_user, make_workspace):
    alice = make_user("alice")
    bob = make_user("bob")
    ws = make_workspace(alice, bob)
    _set_role(client, alice, ws["id"], bob["id"], "subscriber")

    entry = _create_entry(client, ws["id"], alice["headers"], is_public=True)
    client.post(f"/api/workspaces/{ws['id']}/entries/{entry['id']}/comments", headers=alice["headers"], json={"body": "hi"})

    list_res = client.get(f"/api/workspaces/{ws['id']}/entries", headers=bob["headers"])
    assert list_res.status_code == 200
    assert len(list_res.json()) == 1

    get_res = client.get(f"/api/workspaces/{ws['id']}/entries/{entry['id']}", headers=bob["headers"])
    assert get_res.status_code == 200

    comments_res = client.get(f"/api/workspaces/{ws['id']}/entries/{entry['id']}/comments", headers=bob["headers"])
    assert comments_res.status_code == 200
    assert len(comments_res.json()) == 1


def test_subscriber_cannot_create_entry(client, make_user, make_workspace):
    alice = make_user("alice")
    bob = make_user("bob")
    ws = make_workspace(alice, bob)
    _set_role(client, alice, ws["id"], bob["id"], "subscriber")

    res = client.post(
        f"/api/workspaces/{ws['id']}/entries",
        headers=bob["headers"],
        data={
            "start_date": "2026-01-01",
            "playlist_id": "p1",
            "playlist_name": "T",
            "playlist_url": "https://open.spotify.com/playlist/p1",
        },
    )
    assert res.status_code == 403


def test_subscriber_cannot_add_photos(client, make_user, make_workspace):
    alice = make_user("alice")
    bob = make_user("bob")
    ws = make_workspace(alice, bob)
    entry = _create_entry(client, ws["id"], alice["headers"], is_public=True)
    _set_role(client, alice, ws["id"], bob["id"], "subscriber")

    res = client.post(
        f"/api/workspaces/{ws['id']}/entries/{entry['id']}/images",
        headers=bob["headers"],
        files=[("images", ("photo.png", b"fake", "image/png"))],
    )
    assert res.status_code == 403


def test_subscriber_cannot_edit_entry(client, make_user, make_workspace):
    alice = make_user("alice")
    bob = make_user("bob")
    ws = make_workspace(alice, bob)
    entry = _create_entry(client, ws["id"], alice["headers"], is_public=True)
    _set_role(client, alice, ws["id"], bob["id"], "subscriber")

    res = client.patch(f"/api/workspaces/{ws['id']}/entries/{entry['id']}", headers=bob["headers"], json={"text": "hacked"})
    assert res.status_code == 403


def test_subscriber_cannot_delete_entry(client, make_user, make_workspace):
    alice = make_user("alice")
    bob = make_user("bob")
    ws = make_workspace(alice, bob)
    entry = _create_entry(client, ws["id"], alice["headers"], is_public=True)
    _set_role(client, alice, ws["id"], bob["id"], "subscriber")

    res = client.delete(f"/api/workspaces/{ws['id']}/entries/{entry['id']}", headers=bob["headers"])
    assert res.status_code == 403


def test_subscriber_cannot_comment(client, make_user, make_workspace):
    alice = make_user("alice")
    bob = make_user("bob")
    ws = make_workspace(alice, bob)
    entry = _create_entry(client, ws["id"], alice["headers"], is_public=True)
    _set_role(client, alice, ws["id"], bob["id"], "subscriber")

    res = client.post(f"/api/workspaces/{ws['id']}/entries/{entry['id']}/comments", headers=bob["headers"], json={"body": "hi"})
    assert res.status_code == 403


def test_subscriber_cannot_be_added_as_coauthor(client, make_user, make_workspace):
    alice = make_user("alice")
    bob = make_user("bob")
    ws = make_workspace(alice, bob)
    _set_role(client, alice, ws["id"], bob["id"], "subscriber")

    res = client.post(
        f"/api/workspaces/{ws['id']}/entries",
        headers=alice["headers"],
        data={
            "start_date": "2026-01-01",
            "playlist_id": "p1",
            "playlist_name": "T",
            "playlist_url": "https://open.spotify.com/playlist/p1",
        },
        files=[("coauthor_usernames", (None, "bob"))],
    )
    assert res.status_code == 422


def test_promoting_subscriber_back_to_member_restores_write_access(client, make_user, make_workspace):
    alice = make_user("alice")
    bob = make_user("bob")
    ws = make_workspace(alice, bob)
    _set_role(client, alice, ws["id"], bob["id"], "subscriber")
    _set_role(client, alice, ws["id"], bob["id"], "member")

    res = client.post(
        f"/api/workspaces/{ws['id']}/entries",
        headers=bob["headers"],
        data={
            "start_date": "2026-01-01",
            "playlist_id": "p1",
            "playlist_name": "T",
            "playlist_url": "https://open.spotify.com/playlist/p1",
        },
    )
    assert res.status_code == 201


def test_subscriber_role_persists_in_member_list(client, make_user, make_workspace):
    alice = make_user("alice")
    bob = make_user("bob")
    ws = make_workspace(alice, bob)
    _set_role(client, alice, ws["id"], bob["id"], "subscriber")

    res = client.get(f"/api/workspaces/{ws['id']}/members", headers=alice["headers"])
    roles = {m["username"]: m["role"] for m in res.json()}
    assert roles == {"alice": "owner", "bob": "subscriber"}
