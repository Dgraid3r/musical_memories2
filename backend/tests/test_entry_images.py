from unittest.mock import MagicMock, patch

from fastapi.responses import RedirectResponse


def _create_entry_with_image(client, workspace_id, headers, *, is_public=False):
    res = client.post(
        f"/api/workspaces/{workspace_id}/entries",
        headers=headers,
        data={
            "start_date": "2026-01-01",
            "text": "with photo",
            "playlist_id": "p1",
            "playlist_name": "Test",
            "playlist_url": "https://open.spotify.com/playlist/p1",
            "is_public": str(is_public).lower(),
        },
        files=[("images", ("photo.png", b"fake image bytes", "image/png"))],
    )
    assert res.status_code == 201, res.text
    return res.json()


# --- Access control: the whole point of this endpoint -----------------------


def test_image_from_private_entry_not_visible_to_non_member_returns_404(client, make_user, make_workspace):
    """The core fix: an unpermitted caller must get exactly the same 404
    an entry itself would give them - never the image bytes, and never a
    403 that would at least confirm the image exists."""
    alice = make_user("alice")
    outsider = make_user("outsider")
    ws = make_workspace(alice)  # private by default
    entry = _create_entry_with_image(client, ws["id"], alice["headers"])
    image_id = entry["images"][0]["id"]

    res = client.get(f"/api/entries/{entry['id']}/images/{image_id}", headers=outsider["headers"])
    assert res.status_code == 404


def test_image_from_private_entry_not_visible_to_anonymous_caller_returns_404(client, make_user, make_workspace):
    alice = make_user("alice")
    ws = make_workspace(alice)
    entry = _create_entry_with_image(client, ws["id"], alice["headers"])
    image_id = entry["images"][0]["id"]

    res = client.get(f"/api/entries/{entry['id']}/images/{image_id}")
    assert res.status_code == 404


def test_image_from_private_entry_visible_to_owner(client, make_user, make_workspace):
    alice = make_user("alice")
    ws = make_workspace(alice)
    entry = _create_entry_with_image(client, ws["id"], alice["headers"])
    image_id = entry["images"][0]["id"]

    res = client.get(f"/api/entries/{entry['id']}/images/{image_id}", headers=alice["headers"])
    assert res.status_code == 200
    assert res.content == b"fake image bytes"


def test_image_from_private_entry_visible_to_coauthor(client, make_user, make_workspace):
    alice = make_user("alice")
    bob = make_user("bob")
    ws = make_workspace(alice, bob)
    res = client.post(
        f"/api/workspaces/{ws['id']}/entries",
        headers=alice["headers"],
        data={
            "start_date": "2026-01-01",
            "playlist_id": "p1",
            "playlist_name": "Test",
            "playlist_url": "https://open.spotify.com/playlist/p1",
            "is_public": "false",
        },
        files=[("images", ("photo.png", b"fake image bytes", "image/png"))] + [("coauthor_usernames", (None, "bob"))],
    )
    entry = res.json()
    image_id = entry["images"][0]["id"]

    res = client.get(f"/api/entries/{entry['id']}/images/{image_id}", headers=bob["headers"])
    assert res.status_code == 200


def test_image_from_private_entry_visible_to_other_workspace_member_when_entry_is_public(
    client, make_user, make_workspace
):
    """The entry's own is_public flag, not just workspace membership,
    governs visibility - matches entry-visibility semantics generally."""
    alice = make_user("alice")
    bob = make_user("bob")
    ws = make_workspace(alice, bob)
    entry = _create_entry_with_image(client, ws["id"], alice["headers"], is_public=True)
    image_id = entry["images"][0]["id"]

    res = client.get(f"/api/entries/{entry['id']}/images/{image_id}", headers=bob["headers"])
    assert res.status_code == 200


def test_image_from_private_entry_not_visible_to_plain_workspace_member(client, make_user, make_workspace):
    """A workspace member with no relation to this specific *private*
    entry (not its owner, not a co-author) still can't see its image -
    workspace membership alone isn't enough, matching entry visibility."""
    alice = make_user("alice")
    bob = make_user("bob")
    ws = make_workspace(alice, bob)
    entry = _create_entry_with_image(client, ws["id"], alice["headers"], is_public=False)
    image_id = entry["images"][0]["id"]

    res = client.get(f"/api/entries/{entry['id']}/images/{image_id}", headers=bob["headers"])
    assert res.status_code == 404


def test_public_entry_image_visible_with_no_auth_at_all(client, make_user, make_workspace):
    alice = make_user("alice")
    ws = make_workspace(alice)
    res = client.patch(f"/api/workspaces/{ws['id']}", headers=alice["headers"], json={"visibility": "public"})
    assert res.status_code == 200
    entry = _create_entry_with_image(client, ws["id"], alice["headers"], is_public=True)
    image_id = entry["images"][0]["id"]

    res = client.get(f"/api/entries/{entry['id']}/images/{image_id}")
    assert res.status_code == 200
    assert res.content == b"fake image bytes"


# --- Existence / scoping edge cases -----------------------------------------


def test_nonexistent_image_id_returns_404(client, make_user, make_workspace):
    alice = make_user("alice")
    ws = make_workspace(alice)
    entry = _create_entry_with_image(client, ws["id"], alice["headers"])

    res = client.get(f"/api/entries/{entry['id']}/images/999999", headers=alice["headers"])
    assert res.status_code == 404


def test_nonexistent_entry_id_returns_404(client, make_user):
    alice = make_user("alice")
    res = client.get("/api/entries/999999/images/1", headers=alice["headers"])
    assert res.status_code == 404


def test_image_id_belonging_to_a_different_entry_returns_404(client, make_user, make_workspace):
    """An image_id that's real, but under the *wrong* entry_id in the
    URL, must not resolve - prevents using one entry's permission to
    view an image that actually belongs to a different (possibly
    inaccessible) entry."""
    alice = make_user("alice")
    ws = make_workspace(alice)
    entry_a = _create_entry_with_image(client, ws["id"], alice["headers"])
    entry_b = _create_entry_with_image(client, ws["id"], alice["headers"])
    image_id_of_b = entry_b["images"][0]["id"]

    res = client.get(f"/api/entries/{entry_a['id']}/images/{image_id_of_b}", headers=alice["headers"])
    assert res.status_code == 404


# --- The old raw static mount is gone ---------------------------------------


def test_raw_uploads_static_path_no_longer_resolves(client):
    res = client.get("/uploads/anything.png")
    assert res.status_code == 404


# --- S3-compatible storage path: redirect, not raw bytes --------------------


def test_get_entry_image_with_s3_storage_redirects_instead_of_streaming(client, make_user, make_workspace):
    alice = make_user("alice")
    ws = make_workspace(alice)
    entry = _create_entry_with_image(client, ws["id"], alice["headers"])
    image_id = entry["images"][0]["id"]

    fake_storage = MagicMock()
    fake_storage.serve_response.return_value = RedirectResponse(
        "https://example.r2.cloudflarestorage.com/bucket/key?X-Amz-Signature=abc"
    )

    with patch("app.routers.entries.get_storage", return_value=fake_storage):
        res = client.get(
            f"/api/entries/{entry['id']}/images/{image_id}", headers=alice["headers"], follow_redirects=False
        )

    assert res.status_code in (302, 303, 307)
    assert res.headers["location"] == "https://example.r2.cloudflarestorage.com/bucket/key?X-Amz-Signature=abc"
    # Still permission-checked first - the mock is only consulted with the
    # already-resolved image's stored filename, after _visible_or_404.
    fake_storage.serve_response.assert_called_once()


def test_get_entry_image_with_s3_storage_still_enforces_permission_before_redirecting(
    client, make_user, make_workspace
):
    """Swapping in the S3 backend must not bypass the visibility check -
    an unpermitted caller still gets 404, and the storage backend is
    never even consulted."""
    alice = make_user("alice")
    outsider = make_user("outsider")
    ws = make_workspace(alice)
    entry = _create_entry_with_image(client, ws["id"], alice["headers"])
    image_id = entry["images"][0]["id"]

    fake_storage = MagicMock()
    fake_storage.serve_response.return_value = RedirectResponse("https://example.com/should-not-be-reached")

    with patch("app.routers.entries.get_storage", return_value=fake_storage):
        res = client.get(
            f"/api/entries/{entry['id']}/images/{image_id}", headers=outsider["headers"], follow_redirects=False
        )

    assert res.status_code == 404
    fake_storage.serve_response.assert_not_called()
