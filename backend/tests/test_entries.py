from pathlib import Path

UPLOADS_DIR = Path(__file__).resolve().parent.parent / "uploads"


def _create_entry(client, headers, *, is_public=False, entry_date="2026-01-01", text="hello", playlist_id="p1"):
    return client.post(
        "/api/entries",
        headers=headers,
        data={
            "entry_date": entry_date,
            "text": text,
            "playlist_id": playlist_id,
            "playlist_name": "Test Playlist",
            "playlist_url": f"https://open.spotify.com/playlist/{playlist_id}",
            "is_public": str(is_public).lower(),
        },
    )


def test_create_entry_requires_auth(client):
    res = client.post(
        "/api/entries",
        data={
            "entry_date": "2026-01-01",
            "playlist_id": "p1",
            "playlist_name": "x",
            "playlist_url": "https://open.spotify.com/playlist/p1",
        },
    )
    assert res.status_code == 401


def test_create_entry_defaults_to_private(client, make_user):
    alice = make_user("alice")
    res = _create_entry(client, alice["headers"])
    assert res.status_code == 201
    body = res.json()
    assert body["is_public"] is False
    assert body["user_id"] == alice["id"]
    assert body["owner_username"] == "alice"
    assert body["images"] == []


def test_list_entries_anonymous_sees_only_public(client, make_user):
    alice = make_user("alice")
    _create_entry(client, alice["headers"], is_public=False, playlist_id="priv")
    _create_entry(client, alice["headers"], is_public=True, playlist_id="pub")

    res = client.get("/api/entries")
    assert res.status_code == 200
    assert [e["playlist_id"] for e in res.json()] == ["pub"]


def test_list_entries_owner_sees_own_private_and_public(client, make_user):
    alice = make_user("alice")
    _create_entry(client, alice["headers"], is_public=False, playlist_id="priv")
    _create_entry(client, alice["headers"], is_public=True, playlist_id="pub")

    res = client.get("/api/entries", headers=alice["headers"])
    assert {e["playlist_id"] for e in res.json()} == {"priv", "pub"}


def test_list_entries_other_user_sees_only_public(client, make_user):
    alice = make_user("alice")
    bob = make_user("bob")
    _create_entry(client, alice["headers"], is_public=False, playlist_id="priv")
    _create_entry(client, alice["headers"], is_public=True, playlist_id="pub")

    res = client.get("/api/entries", headers=bob["headers"])
    assert {e["playlist_id"] for e in res.json()} == {"pub"}


def test_get_private_entry_as_non_owner_returns_404(client, make_user):
    alice = make_user("alice")
    bob = make_user("bob")
    entry_id = _create_entry(client, alice["headers"], is_public=False).json()["id"]

    res = client.get(f"/api/entries/{entry_id}", headers=bob["headers"])
    assert res.status_code == 404


def test_get_private_entry_anonymous_returns_404(client, make_user):
    alice = make_user("alice")
    entry_id = _create_entry(client, alice["headers"], is_public=False).json()["id"]

    res = client.get(f"/api/entries/{entry_id}")
    assert res.status_code == 404


def test_get_own_private_entry_succeeds(client, make_user):
    alice = make_user("alice")
    entry_id = _create_entry(client, alice["headers"], is_public=False).json()["id"]

    res = client.get(f"/api/entries/{entry_id}", headers=alice["headers"])
    assert res.status_code == 200


def test_get_public_entry_visible_to_anyone(client, make_user):
    alice = make_user("alice")
    entry_id = _create_entry(client, alice["headers"], is_public=True).json()["id"]

    res = client.get(f"/api/entries/{entry_id}")
    assert res.status_code == 200


def test_get_nonexistent_entry_returns_404(client):
    res = client.get("/api/entries/999999")
    assert res.status_code == 404


def test_patch_toggles_visibility(client, make_user):
    alice = make_user("alice")
    entry_id = _create_entry(client, alice["headers"], is_public=False).json()["id"]

    res = client.patch(f"/api/entries/{entry_id}", headers=alice["headers"], json={"is_public": True})
    assert res.status_code == 200
    assert res.json()["is_public"] is True

    # and it actually took effect, not just echoed the request body back
    res = client.get(f"/api/entries/{entry_id}")
    assert res.status_code == 200


def test_patch_updates_text(client, make_user):
    alice = make_user("alice")
    entry_id = _create_entry(client, alice["headers"], text="original").json()["id"]

    res = client.patch(f"/api/entries/{entry_id}", headers=alice["headers"], json={"text": "updated"})
    assert res.status_code == 200
    assert res.json()["text"] == "updated"


def test_patch_omitted_fields_are_left_unchanged(client, make_user):
    alice = make_user("alice")
    entry_id = _create_entry(client, alice["headers"], text="original", is_public=True).json()["id"]

    res = client.patch(f"/api/entries/{entry_id}", headers=alice["headers"], json={})
    assert res.status_code == 200
    body = res.json()
    assert body["text"] == "original"
    assert body["is_public"] is True


def test_patch_by_non_owner_forbidden(client, make_user):
    alice = make_user("alice")
    bob = make_user("bob")
    entry_id = _create_entry(client, alice["headers"], is_public=True).json()["id"]

    res = client.patch(f"/api/entries/{entry_id}", headers=bob["headers"], json={"is_public": False})
    assert res.status_code == 403

    # confirm the forbidden request didn't leak through
    res = client.get(f"/api/entries/{entry_id}")
    assert res.json()["is_public"] is True


def test_patch_requires_auth(client, make_user):
    alice = make_user("alice")
    entry_id = _create_entry(client, alice["headers"], is_public=True).json()["id"]

    res = client.patch(f"/api/entries/{entry_id}", json={"is_public": False})
    assert res.status_code == 401


def test_patch_nonexistent_entry_returns_404(client, make_user):
    alice = make_user("alice")
    res = client.patch("/api/entries/999999", headers=alice["headers"], json={"is_public": True})
    assert res.status_code == 404


def test_delete_by_owner_succeeds(client, make_user):
    alice = make_user("alice")
    entry_id = _create_entry(client, alice["headers"]).json()["id"]

    res = client.delete(f"/api/entries/{entry_id}", headers=alice["headers"])
    assert res.status_code == 204

    res = client.get(f"/api/entries/{entry_id}", headers=alice["headers"])
    assert res.status_code == 404


def test_delete_by_non_owner_forbidden(client, make_user):
    alice = make_user("alice")
    bob = make_user("bob")
    entry_id = _create_entry(client, alice["headers"], is_public=True).json()["id"]

    res = client.delete(f"/api/entries/{entry_id}", headers=bob["headers"])
    assert res.status_code == 403

    # entry must still exist
    res = client.get(f"/api/entries/{entry_id}")
    assert res.status_code == 200


def test_delete_requires_auth(client, make_user):
    alice = make_user("alice")
    entry_id = _create_entry(client, alice["headers"]).json()["id"]

    res = client.delete(f"/api/entries/{entry_id}")
    assert res.status_code == 401


def test_delete_nonexistent_entry_returns_404(client, make_user):
    alice = make_user("alice")
    res = client.delete("/api/entries/999999", headers=alice["headers"])
    assert res.status_code == 404


def test_create_entry_with_image_upload(client, make_user):
    alice = make_user("alice")
    res = client.post(
        "/api/entries",
        headers=alice["headers"],
        data={
            "entry_date": "2026-01-01",
            "text": "with photo",
            "playlist_id": "p1",
            "playlist_name": "Test",
            "playlist_url": "https://open.spotify.com/playlist/p1",
            "is_public": "false",
        },
        files=[("images", ("photo.png", b"fake image bytes", "image/png"))],
    )
    assert res.status_code == 201
    body = res.json()
    assert len(body["images"]) == 1
    saved_path = UPLOADS_DIR / body["images"][0]["filename"]
    try:
        assert saved_path.exists()
    finally:
        saved_path.unlink(missing_ok=True)


def test_delete_entry_removes_uploaded_images(client, make_user):
    alice = make_user("alice")
    create_res = client.post(
        "/api/entries",
        headers=alice["headers"],
        data={
            "entry_date": "2026-01-01",
            "playlist_id": "p1",
            "playlist_name": "Test",
            "playlist_url": "https://open.spotify.com/playlist/p1",
            "is_public": "false",
        },
        files=[("images", ("photo.png", b"fake image bytes", "image/png"))],
    )
    filename = create_res.json()["images"][0]["filename"]
    saved_path = UPLOADS_DIR / filename
    assert saved_path.exists()

    entry_id = create_res.json()["id"]
    client.delete(f"/api/entries/{entry_id}", headers=alice["headers"])

    assert not saved_path.exists()
