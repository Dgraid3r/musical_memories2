def _create_entry(
    client,
    workspace_id,
    headers,
    *,
    is_public=True,
    playlist_id="p1",
    text="hello",
    latitude=None,
    longitude=None,
    location_name=None,
):
    data = {
        "start_date": "2026-01-01",
        "text": text,
        "playlist_id": playlist_id,
        "playlist_name": "Test Playlist",
        "playlist_url": f"https://open.spotify.com/playlist/{playlist_id}",
        "is_public": str(is_public).lower(),
    }
    if latitude is not None:
        data["latitude"] = str(latitude)
    if longitude is not None:
        data["longitude"] = str(longitude)
    if location_name is not None:
        data["location_name"] = location_name
    res = client.post(f"/api/workspaces/{workspace_id}/entries", headers=headers, data=data)
    assert res.status_code == 201, res.text
    return res.json()


def _history(client, workspace_id, entry_id, headers=None):
    res = client.get(f"/api/workspaces/{workspace_id}/entries/{entry_id}/edit-history", headers=headers or {})
    assert res.status_code == 200, res.text
    return res.json()


# --- Create --------------------------------------------------------------


def test_create_entry_with_location_persists_it(client, make_user, make_workspace):
    alice = make_user("alice")
    ws = make_workspace(alice)

    entry = _create_entry(
        client,
        ws["id"],
        alice["headers"],
        latitude=37.7694,
        longitude=-122.4862,
        location_name="Golden Gate Park, San Francisco",
    )
    assert entry["latitude"] == 37.7694
    assert entry["longitude"] == -122.4862
    assert entry["location_name"] == "Golden Gate Park, San Francisco"

    # And it round-trips through a fresh GET too, not just the create response.
    get_res = client.get(f"/api/workspaces/{ws['id']}/entries/{entry['id']}", headers=alice["headers"])
    assert get_res.status_code == 200
    body = get_res.json()
    assert body["latitude"] == 37.7694
    assert body["longitude"] == -122.4862
    assert body["location_name"] == "Golden Gate Park, San Francisco"


def test_create_entry_without_location_works_exactly_as_before(client, make_user, make_workspace):
    """The common case - no location at all - must be completely
    unaffected by this feature."""
    alice = make_user("alice")
    ws = make_workspace(alice)

    entry = _create_entry(client, ws["id"], alice["headers"])
    assert entry["latitude"] is None
    assert entry["longitude"] is None
    assert entry["location_name"] is None


def test_create_entry_with_latitude_but_no_longitude_rejected(client, make_user, make_workspace):
    alice = make_user("alice")
    ws = make_workspace(alice)

    res = client.post(
        f"/api/workspaces/{ws['id']}/entries",
        headers=alice["headers"],
        data={
            "start_date": "2026-01-01",
            "playlist_id": "p1",
            "playlist_name": "Test",
            "playlist_url": "https://open.spotify.com/playlist/p1",
            "latitude": "37.7694",
        },
    )
    assert res.status_code == 422


# --- Update ----------------------------------------------------------------


def test_update_entry_sets_location(client, make_user, make_workspace):
    alice = make_user("alice")
    ws = make_workspace(alice)
    entry = _create_entry(client, ws["id"], alice["headers"])

    res = client.patch(
        f"/api/workspaces/{ws['id']}/entries/{entry['id']}",
        headers=alice["headers"],
        json={"location": {"latitude": 48.8584, "longitude": 2.2945, "location_name": "Eiffel Tower, Paris"}},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["latitude"] == 48.8584
    assert body["longitude"] == 2.2945
    assert body["location_name"] == "Eiffel Tower, Paris"


def test_update_entry_clears_location_with_explicit_null(client, make_user, make_workspace):
    alice = make_user("alice")
    ws = make_workspace(alice)
    entry = _create_entry(
        client, ws["id"], alice["headers"], latitude=1.0, longitude=2.0, location_name="Somewhere"
    )

    res = client.patch(
        f"/api/workspaces/{ws['id']}/entries/{entry['id']}",
        headers=alice["headers"],
        json={"location": None},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["latitude"] is None
    assert body["longitude"] is None
    assert body["location_name"] is None


def test_update_entry_omitting_location_leaves_it_unchanged(client, make_user, make_workspace):
    """The whole point of the model_fields_set distinction: a PATCH that
    doesn't mention "location" at all (e.g. just updating text) must not
    touch an existing location."""
    alice = make_user("alice")
    ws = make_workspace(alice)
    entry = _create_entry(
        client, ws["id"], alice["headers"], latitude=1.0, longitude=2.0, location_name="Somewhere"
    )

    res = client.patch(
        f"/api/workspaces/{ws['id']}/entries/{entry['id']}",
        headers=alice["headers"],
        json={"text": "updated text, no mention of location"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["latitude"] == 1.0
    assert body["longitude"] == 2.0
    assert body["location_name"] == "Somewhere"


def test_coauthor_can_edit_location(client, make_user, make_workspace):
    """Location is content, like text/tags - any co-author with
    content-edit rights can set it, not just the primary author."""
    alice = make_user("alice")
    bob = make_user("bob")
    ws = make_workspace(alice, bob)
    entry = _create_entry(client, ws["id"], alice["headers"])
    # Add bob as coauthor via PATCH (owner-only - alice is the owner here).
    xfer = client.patch(
        f"/api/workspaces/{ws['id']}/entries/{entry['id']}",
        headers=alice["headers"],
        json={"coauthor_usernames": ["bob"]},
    )
    assert xfer.status_code == 200

    res = client.patch(
        f"/api/workspaces/{ws['id']}/entries/{entry['id']}",
        headers=bob["headers"],
        json={"location": {"latitude": 1.0, "longitude": 2.0, "location_name": "Bob's pick"}},
    )
    assert res.status_code == 200
    assert res.json()["location_name"] == "Bob's pick"


# --- Edit-history integration ----------------------------------------------


def test_setting_location_records_edit_history_event(client, make_user, make_workspace):
    alice = make_user("alice")
    ws = make_workspace(alice)
    entry = _create_entry(client, ws["id"], alice["headers"])

    res = client.patch(
        f"/api/workspaces/{ws['id']}/entries/{entry['id']}",
        headers=alice["headers"],
        json={"location": {"latitude": 1.0, "longitude": 2.0, "location_name": "Somewhere"}},
    )
    assert res.status_code == 200

    events = _history(client, ws["id"], entry["id"], alice["headers"])
    assert len(events) == 1
    assert events[0]["change_summary"] == "location"
    assert events[0]["editor_user_id"] == alice["id"]


def test_clearing_location_records_edit_history_event(client, make_user, make_workspace):
    alice = make_user("alice")
    ws = make_workspace(alice)
    entry = _create_entry(
        client, ws["id"], alice["headers"], latitude=1.0, longitude=2.0, location_name="Somewhere"
    )

    res = client.patch(
        f"/api/workspaces/{ws['id']}/entries/{entry['id']}",
        headers=alice["headers"],
        json={"location": None},
    )
    assert res.status_code == 200

    events = _history(client, ws["id"], entry["id"], alice["headers"])
    assert len(events) == 1
    assert events[0]["change_summary"] == "location"


def test_resending_identical_location_is_a_noop(client, make_user, make_workspace):
    alice = make_user("alice")
    ws = make_workspace(alice)
    entry = _create_entry(
        client, ws["id"], alice["headers"], latitude=1.0, longitude=2.0, location_name="Somewhere"
    )

    res = client.patch(
        f"/api/workspaces/{ws['id']}/entries/{entry['id']}",
        headers=alice["headers"],
        json={"location": {"latitude": 1.0, "longitude": 2.0, "location_name": "Somewhere"}},
    )
    assert res.status_code == 200

    events = _history(client, ws["id"], entry["id"], alice["headers"])
    assert events == []


def test_clearing_already_unset_location_is_a_noop(client, make_user, make_workspace):
    alice = make_user("alice")
    ws = make_workspace(alice)
    entry = _create_entry(client, ws["id"], alice["headers"])

    res = client.patch(
        f"/api/workspaces/{ws['id']}/entries/{entry['id']}",
        headers=alice["headers"],
        json={"location": None},
    )
    assert res.status_code == 200

    events = _history(client, ws["id"], entry["id"], alice["headers"])
    assert events == []


def test_location_change_combines_with_other_field_changes_in_one_event(client, make_user, make_workspace):
    alice = make_user("alice")
    ws = make_workspace(alice)
    entry = _create_entry(client, ws["id"], alice["headers"], text="before")

    res = client.patch(
        f"/api/workspaces/{ws['id']}/entries/{entry['id']}",
        headers=alice["headers"],
        json={"text": "after", "location": {"latitude": 1.0, "longitude": 2.0, "location_name": "Somewhere"}},
    )
    assert res.status_code == 200

    events = _history(client, ws["id"], entry["id"], alice["headers"])
    assert len(events) == 1
    assert "content" in events[0]["change_summary"]
    assert "location" in events[0]["change_summary"]


# --- located_only filter (map view) + visibility ---------------------------


def test_located_only_filter_returns_only_entries_with_a_location(client, make_user, make_workspace):
    alice = make_user("alice")
    ws = make_workspace(alice)
    located = _create_entry(client, ws["id"], alice["headers"], latitude=1.0, longitude=2.0, location_name="A")
    _create_entry(client, ws["id"], alice["headers"], playlist_id="p2")  # no location

    res = client.get(f"/api/workspaces/{ws['id']}/entries?located_only=true", headers=alice["headers"])
    assert res.status_code == 200
    ids = [e["id"] for e in res.json()]
    assert ids == [located["id"]]


def test_located_only_omits_a_private_located_entry_from_a_non_coauthor(client, make_user, make_workspace):
    """The core security property: a private entry's location must never
    appear to someone who couldn't see the entry itself."""
    alice = make_user("alice")
    bob = make_user("bob")
    ws = make_workspace(alice, bob)
    _create_entry(
        client, ws["id"], alice["headers"], is_public=False, latitude=1.0, longitude=2.0, location_name="Secret spot"
    )

    res = client.get(f"/api/workspaces/{ws['id']}/entries?located_only=true", headers=bob["headers"])
    assert res.status_code == 200
    assert res.json() == []
    # And the location string itself never appears anywhere in the response.
    assert "Secret spot" not in res.text


def test_located_only_includes_private_located_entry_for_its_coauthor(client, make_user, make_workspace):
    alice = make_user("alice")
    bob = make_user("bob")
    ws = make_workspace(alice, bob)
    entry = _create_entry(
        client, ws["id"], alice["headers"], is_public=False, latitude=1.0, longitude=2.0, location_name="Shared spot"
    )
    add_coauthor = client.patch(
        f"/api/workspaces/{ws['id']}/entries/{entry['id']}",
        headers=alice["headers"],
        json={"coauthor_usernames": ["bob"]},
    )
    assert add_coauthor.status_code == 200

    res = client.get(f"/api/workspaces/{ws['id']}/entries?located_only=true", headers=bob["headers"])
    assert res.status_code == 200
    ids = [e["id"] for e in res.json()]
    assert ids == [entry["id"]]


def test_located_only_requires_workspace_access_for_private_workspace(client, make_user, make_workspace):
    alice = make_user("alice")
    outsider = make_user("outsider")
    ws = make_workspace(alice)  # private, outsider not a member
    _create_entry(client, ws["id"], alice["headers"], latitude=1.0, longitude=2.0, location_name="A")

    res = client.get(f"/api/workspaces/{ws['id']}/entries?located_only=true", headers=outsider["headers"])
    assert res.status_code == 404


def test_located_only_anonymous_sees_only_public_located_entries_in_public_workspace(client, make_user, make_workspace):
    alice = make_user("alice")
    ws = make_workspace(alice)
    public_ws = client.patch(f"/api/workspaces/{ws['id']}", headers=alice["headers"], json={"visibility": "public"})
    assert public_ws.status_code == 200

    public_entry = _create_entry(
        client, ws["id"], alice["headers"], is_public=True, latitude=1.0, longitude=2.0, location_name="Public spot"
    )
    _create_entry(
        client,
        ws["id"],
        alice["headers"],
        is_public=False,
        playlist_id="p2",
        latitude=3.0,
        longitude=4.0,
        location_name="Private spot",
    )

    res = client.get(f"/api/workspaces/{ws['id']}/entries?located_only=true")  # no auth at all
    assert res.status_code == 200
    ids = [e["id"] for e in res.json()]
    assert ids == [public_entry["id"]]
