def _create_entry(
    client,
    workspace_id,
    headers,
    *,
    is_public=False,
    text="hello",
    playlist_id="p1",
    tags=None,
):
    data = {
        "start_date": "2026-01-01",
        "text": text,
        "playlist_id": playlist_id,
        "playlist_name": "Test Playlist",
        "playlist_url": f"https://open.spotify.com/playlist/{playlist_id}",
        "is_public": str(is_public).lower(),
    }
    return client.post(
        f"/api/workspaces/{workspace_id}/entries",
        headers=headers,
        data=data,
        files=[("tags", (None, t)) for t in (tags or [])],
    )


# --- Tags on create/update -------------------------------------------------


def test_create_entry_with_tags(client, make_user, make_workspace):
    alice = make_user("alice")
    ws = make_workspace(alice)
    res = _create_entry(client, ws["id"], alice["headers"], tags=["road trip", "Summer"])
    assert res.status_code == 201
    tag_names = {t["name"] for t in res.json()["tags"]}
    assert tag_names == {"road trip", "summer"}


def test_create_entry_tags_are_normalized_and_deduped(client, make_user, make_workspace):
    alice = make_user("alice")
    ws = make_workspace(alice)
    res = _create_entry(client, ws["id"], alice["headers"], tags=["Road Trip", "road trip", " road trip "])
    assert res.status_code == 201
    assert [t["name"] for t in res.json()["tags"]] == ["road trip"]


def test_create_entry_reuses_existing_tag(client, make_user, make_workspace):
    alice = make_user("alice")
    ws = make_workspace(alice)
    res1 = _create_entry(client, ws["id"], alice["headers"], playlist_id="p1", tags=["summer"])
    res2 = _create_entry(client, ws["id"], alice["headers"], playlist_id="p2", tags=["summer"])
    assert res1.status_code == res2.status_code == 201
    tag1 = res1.json()["tags"][0]
    tag2 = res2.json()["tags"][0]
    assert tag1["id"] == tag2["id"]


def test_same_tag_name_in_different_workspaces_is_a_different_tag(client, make_user, make_workspace):
    alice = make_user("alice")
    ws1 = make_workspace(alice, name="Workspace One")
    ws2 = make_workspace(alice, name="Workspace Two")
    res1 = _create_entry(client, ws1["id"], alice["headers"], playlist_id="p1", tags=["summer"])
    res2 = _create_entry(client, ws2["id"], alice["headers"], playlist_id="p2", tags=["summer"])
    assert res1.status_code == res2.status_code == 201
    tag1 = res1.json()["tags"][0]
    tag2 = res2.json()["tags"][0]
    assert tag1["name"] == tag2["name"] == "summer"
    assert tag1["id"] != tag2["id"]


def test_create_entry_without_tags_has_empty_tag_list(client, make_user, make_workspace):
    alice = make_user("alice")
    ws = make_workspace(alice)
    res = _create_entry(client, ws["id"], alice["headers"])
    assert res.status_code == 201
    assert res.json()["tags"] == []


def test_owner_can_update_tags(client, make_user, make_workspace):
    alice = make_user("alice")
    ws = make_workspace(alice)
    entry_id = _create_entry(client, ws["id"], alice["headers"], tags=["old"]).json()["id"]

    res = client.patch(f"/api/workspaces/{ws['id']}/entries/{entry_id}", headers=alice["headers"], json={"tags": ["new", "tags"]})
    assert res.status_code == 200
    assert {t["name"] for t in res.json()["tags"]} == {"new", "tags"}


def test_coauthor_can_update_tags(client, make_user, make_workspace):
    alice = make_user("alice")
    bob = make_user("bob")
    ws = make_workspace(alice, bob)
    entry_id = client.post(
        f"/api/workspaces/{ws['id']}/entries",
        headers=alice["headers"],
        data={
            "start_date": "2026-01-01",
            "playlist_id": "p1",
            "playlist_name": "Test",
            "playlist_url": "https://open.spotify.com/playlist/p1",
            "is_public": "false",
        },
        files=[("coauthor_usernames", (None, "bob"))],
    ).json()["id"]

    res = client.patch(f"/api/workspaces/{ws['id']}/entries/{entry_id}", headers=bob["headers"], json={"tags": ["added-by-bob"]})
    assert res.status_code == 200
    assert [t["name"] for t in res.json()["tags"]] == ["added-by-bob"]


def test_patch_omitted_tags_left_unchanged(client, make_user, make_workspace):
    alice = make_user("alice")
    ws = make_workspace(alice)
    entry_id = _create_entry(client, ws["id"], alice["headers"], tags=["keep-me"]).json()["id"]

    res = client.patch(f"/api/workspaces/{ws['id']}/entries/{entry_id}", headers=alice["headers"], json={"text": "updated"})
    assert res.status_code == 200
    assert [t["name"] for t in res.json()["tags"]] == ["keep-me"]


def test_patch_empty_tags_list_clears_tags(client, make_user, make_workspace):
    alice = make_user("alice")
    ws = make_workspace(alice)
    entry_id = _create_entry(client, ws["id"], alice["headers"], tags=["clear-me"]).json()["id"]

    res = client.patch(f"/api/workspaces/{ws['id']}/entries/{entry_id}", headers=alice["headers"], json={"tags": []})
    assert res.status_code == 200
    assert res.json()["tags"] == []


# --- GET /api/workspaces/{id}/entries/tags ----------------------------------


def test_list_tags_returns_tags_in_use(client, make_user, make_workspace):
    alice = make_user("alice")
    ws = make_workspace(alice)
    _create_entry(client, ws["id"], alice["headers"], playlist_id="p1", is_public=True, tags=["alpha", "beta"])

    res = client.get(f"/api/workspaces/{ws['id']}/entries/tags", headers=alice["headers"])
    assert res.status_code == 200
    assert set(res.json()) == {"alpha", "beta"}


def test_list_tags_excludes_tags_only_on_others_private_entries(client, make_user, make_workspace):
    alice = make_user("alice")
    bob = make_user("bob")
    ws = make_workspace(alice, bob)
    _create_entry(client, ws["id"], alice["headers"], is_public=False, tags=["secret-tag"])

    res = client.get(f"/api/workspaces/{ws['id']}/entries/tags", headers=bob["headers"])
    assert res.status_code == 200
    assert "secret-tag" not in res.json()


def test_list_tags_includes_own_private_entry_tags(client, make_user, make_workspace):
    alice = make_user("alice")
    ws = make_workspace(alice)
    _create_entry(client, ws["id"], alice["headers"], is_public=False, tags=["my-private-tag"])

    res = client.get(f"/api/workspaces/{ws['id']}/entries/tags", headers=alice["headers"])
    assert "my-private-tag" in res.json()


def test_list_tags_requires_workspace_membership(client, make_user, make_workspace):
    alice = make_user("alice")
    outsider = make_user("outsider")
    ws = make_workspace(alice)
    _create_entry(client, ws["id"], alice["headers"], is_public=True, tags=["visible-tag"])

    res = client.get(f"/api/workspaces/{ws['id']}/entries/tags", headers=outsider["headers"])
    assert res.status_code == 404


# --- Filtering by exact tag --------------------------------------------------


def test_list_entries_filters_by_tag(client, make_user, make_workspace):
    alice = make_user("alice")
    ws = make_workspace(alice)
    _create_entry(client, ws["id"], alice["headers"], playlist_id="tagged", is_public=True, tags=["road-trip"])
    _create_entry(client, ws["id"], alice["headers"], playlist_id="untagged", is_public=True)

    res = client.get(f"/api/workspaces/{ws['id']}/entries?tag=road-trip", headers=alice["headers"])
    assert res.status_code == 200
    assert [e["playlist_id"] for e in res.json()] == ["tagged"]


def test_list_entries_tag_filter_respects_visibility(client, make_user, make_workspace):
    alice = make_user("alice")
    bob = make_user("bob")
    ws = make_workspace(alice, bob)
    _create_entry(client, ws["id"], alice["headers"], playlist_id="priv", is_public=False, tags=["shared-tag"])

    res = client.get(f"/api/workspaces/{ws['id']}/entries?tag=shared-tag", headers=bob["headers"])
    assert res.status_code == 200
    assert res.json() == []


# --- Full-text search (q) ---------------------------------------------------


def test_search_matches_entry_text(client, make_user, make_workspace):
    alice = make_user("alice")
    ws = make_workspace(alice)
    _create_entry(
        client, ws["id"], alice["headers"], playlist_id="mountains", is_public=True, text="a road trip to the mountains"
    )
    _create_entry(client, ws["id"], alice["headers"], playlist_id="beach", is_public=True, text="a lazy day at the beach")

    res = client.get(f"/api/workspaces/{ws['id']}/entries?q=mountains", headers=alice["headers"])
    assert res.status_code == 200
    assert [e["playlist_id"] for e in res.json()] == ["mountains"]


def test_search_matches_tag_names(client, make_user, make_workspace):
    alice = make_user("alice")
    ws = make_workspace(alice)
    _create_entry(client, ws["id"], alice["headers"], playlist_id="p1", is_public=True, text="just a note", tags=["roadtrip"])
    _create_entry(client, ws["id"], alice["headers"], playlist_id="p2", is_public=True, text="a different note")

    res = client.get(f"/api/workspaces/{ws['id']}/entries?q=roadtrip", headers=alice["headers"])
    assert res.status_code == 200
    assert [e["playlist_id"] for e in res.json()] == ["p1"]


def test_search_no_match_returns_empty_list(client, make_user, make_workspace):
    alice = make_user("alice")
    ws = make_workspace(alice)
    _create_entry(client, ws["id"], alice["headers"], is_public=True, text="a road trip to the mountains")

    res = client.get(f"/api/workspaces/{ws['id']}/entries?q=nonexistent-xyz-search-term", headers=alice["headers"])
    assert res.status_code == 200
    assert res.json() == []


def test_search_respects_visibility_rules(client, make_user, make_workspace):
    alice = make_user("alice")
    bob = make_user("bob")
    ws = make_workspace(alice, bob)
    _create_entry(client, ws["id"], alice["headers"], playlist_id="priv", is_public=False, text="secret camping trip")
    _create_entry(client, ws["id"], alice["headers"], playlist_id="pub", is_public=True, text="public camping trip")

    owner_res = client.get(f"/api/workspaces/{ws['id']}/entries?q=camping", headers=alice["headers"])
    assert {e["playlist_id"] for e in owner_res.json()} == {"priv", "pub"}

    other_res = client.get(f"/api/workspaces/{ws['id']}/entries?q=camping", headers=bob["headers"])
    assert {e["playlist_id"] for e in other_res.json()} == {"pub"}


def test_search_coauthor_sees_private_entry(client, make_user, make_workspace):
    alice = make_user("alice")
    bob = make_user("bob")
    ws = make_workspace(alice, bob)
    create_res = client.post(
        f"/api/workspaces/{ws['id']}/entries",
        headers=alice["headers"],
        data={
            "start_date": "2026-01-01",
            "text": "a shared camping trip",
            "playlist_id": "p1",
            "playlist_name": "Test",
            "playlist_url": "https://open.spotify.com/playlist/p1",
            "is_public": "false",
        },
        files=[("coauthor_usernames", (None, "bob"))],
    )
    assert create_res.status_code == 201

    res = client.get(f"/api/workspaces/{ws['id']}/entries?q=camping", headers=bob["headers"])
    assert res.status_code == 200
    assert len(res.json()) == 1


def test_search_updates_after_text_edit(client, make_user, make_workspace):
    alice = make_user("alice")
    ws = make_workspace(alice)
    entry_id = _create_entry(client, ws["id"], alice["headers"], is_public=True, text="original wording").json()["id"]

    before = client.get(f"/api/workspaces/{ws['id']}/entries?q=mountains", headers=alice["headers"]).json()
    assert before == []

    client.patch(f"/api/workspaces/{ws['id']}/entries/{entry_id}", headers=alice["headers"], json={"text": "now mentions mountains"})

    after = client.get(f"/api/workspaces/{ws['id']}/entries?q=mountains", headers=alice["headers"]).json()
    assert [e["id"] for e in after] == [entry_id]


def test_search_requires_nonempty_query(client, make_user, make_workspace):
    alice = make_user("alice")
    ws = make_workspace(alice)
    res = client.get(f"/api/workspaces/{ws['id']}/entries?q=", headers=alice["headers"])
    assert res.status_code == 422


def test_search_does_not_cross_workspace_boundaries(client, make_user, make_workspace):
    """Same search term, same author, two different workspaces - a search
    in workspace A must never surface a match that only exists in
    workspace B, even though alice belongs to (and owns) both."""
    alice = make_user("alice")
    ws_a = make_workspace(alice, name="Workspace A")
    ws_b = make_workspace(alice, name="Workspace B")
    _create_entry(client, ws_a["id"], alice["headers"], playlist_id="in-a", is_public=True, text="a mountain retreat")
    _create_entry(client, ws_b["id"], alice["headers"], playlist_id="in-b", is_public=True, text="a mountain cabin")

    res_a = client.get(f"/api/workspaces/{ws_a['id']}/entries?q=mountain", headers=alice["headers"])
    res_b = client.get(f"/api/workspaces/{ws_b['id']}/entries?q=mountain", headers=alice["headers"])

    assert [e["playlist_id"] for e in res_a.json()] == ["in-a"]
    assert [e["playlist_id"] for e in res_b.json()] == ["in-b"]
