def _create_entry(client, workspace_id, headers, *, playlist_id="p1", coauthor_usernames=None, text="hello"):
    data = {
        "start_date": "2026-01-01",
        "text": text,
        "playlist_id": playlist_id,
        "playlist_name": "Test Playlist",
        "playlist_url": f"https://open.spotify.com/playlist/{playlist_id}",
        "is_public": "false",
        "latitude": "40.0",
        "longitude": "-74.0",
        "location_name": "New York",
    }
    files = [("coauthor_usernames", (None, u)) for u in (coauthor_usernames or [])]
    files += [("tags", (None, "road trip"))]
    res = client.post(
        f"/api/workspaces/{workspace_id}/entries",
        headers=headers,
        data=data,
        files=files or None,
    )
    assert res.status_code == 201, res.text
    return res.json()


def _enable_sharing(client, workspace_id, entry_id, headers):
    return client.post(f"/api/workspaces/{workspace_id}/entries/{entry_id}/share", headers=headers)


def _disable_sharing(client, workspace_id, entry_id, headers):
    return client.request(
        "DELETE", f"/api/workspaces/{workspace_id}/entries/{entry_id}/share", headers=headers
    )


def test_enable_sharing_generates_a_usable_token(client, make_user, make_workspace):
    alice = make_user("alice")
    ws = make_workspace(alice, name="Solo")
    entry = _create_entry(client, ws["id"], alice["headers"])

    res = _enable_sharing(client, ws["id"], entry["id"], alice["headers"])
    assert res.status_code == 200, res.text
    token = res.json()["share_token"]
    assert token

    shared_res = client.get(f"/api/shared/{token}")
    assert shared_res.status_code == 200, shared_res.text
    body = shared_res.json()
    assert body["text"] == "hello"
    assert body["start_date"] == "2026-01-01"
    assert body["playlist_id"] == "p1"
    assert body["location_name"] == "New York"
    assert [t["name"] for t in body["tags"]] == ["road trip"]


def test_enable_sharing_twice_returns_same_token_not_rotated(client, make_user, make_workspace):
    alice = make_user("alice")
    ws = make_workspace(alice, name="Solo")
    entry = _create_entry(client, ws["id"], alice["headers"])

    first = _enable_sharing(client, ws["id"], entry["id"], alice["headers"])
    second = _enable_sharing(client, ws["id"], entry["id"], alice["headers"])
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["share_token"] == second.json()["share_token"]


def test_disable_sharing_clears_token_and_old_link_immediately_404s(client, make_user, make_workspace):
    alice = make_user("alice")
    ws = make_workspace(alice, name="Solo")
    entry = _create_entry(client, ws["id"], alice["headers"])

    token = _enable_sharing(client, ws["id"], entry["id"], alice["headers"]).json()["share_token"]
    assert client.get(f"/api/shared/{token}").status_code == 200

    disable_res = _disable_sharing(client, ws["id"], entry["id"], alice["headers"])
    assert disable_res.status_code == 204

    assert client.get(f"/api/shared/{token}").status_code == 404
    assert client.get(f"/api/shared/{token}/images/1").status_code == 404


def test_disabling_when_never_shared_is_a_harmless_no_op(client, make_user, make_workspace):
    alice = make_user("alice")
    ws = make_workspace(alice, name="Solo")
    entry = _create_entry(client, ws["id"], alice["headers"])

    res = _disable_sharing(client, ws["id"], entry["id"], alice["headers"])
    assert res.status_code == 204


def test_invalid_share_token_404s(client):
    res = client.get("/api/shared/not-a-real-token")
    assert res.status_code == 404


def test_coauthor_cannot_enable_or_disable_sharing(client, make_user, make_workspace):
    alice = make_user("alice")
    bob = make_user("bob")
    ws = make_workspace(alice, bob)
    entry = _create_entry(client, ws["id"], alice["headers"], coauthor_usernames=["bob"])
    assert any(c["id"] == bob["id"] for c in entry["coauthors"])

    enable_res = _enable_sharing(client, ws["id"], entry["id"], bob["headers"])
    assert enable_res.status_code == 403

    # alice enables it herself; bob still can't turn it back off.
    token = _enable_sharing(client, ws["id"], entry["id"], alice["headers"]).json()["share_token"]
    disable_res = _disable_sharing(client, ws["id"], entry["id"], bob["headers"])
    assert disable_res.status_code == 403
    # Still shared - bob's attempt had no effect.
    assert client.get(f"/api/shared/{token}").status_code == 200


def test_random_workspace_member_cannot_enable_sharing(client, make_user, make_workspace):
    alice = make_user("alice")
    carol = make_user("carol")
    ws = make_workspace(alice, carol)  # carol is a plain member, not owner/coauthor of the entry
    entry = _create_entry(client, ws["id"], alice["headers"])

    res = _enable_sharing(client, ws["id"], entry["id"], carol["headers"])
    assert res.status_code == 403


def test_non_member_cannot_enable_sharing(client, make_user, make_workspace):
    alice = make_user("alice")
    dave = make_user("dave")
    ws = make_workspace(alice, name="Solo")
    entry = _create_entry(client, ws["id"], alice["headers"])

    res = _enable_sharing(client, ws["id"], entry["id"], dave["headers"])
    assert res.status_code == 404  # dave has no membership at all - non-disclosure


def test_share_link_works_even_for_private_entry_in_private_workspace(client, make_user, make_workspace):
    """The whole point: distinct from workspace-level visibility - a
    private workspace's private entry is still individually shareable
    by its owner."""
    alice = make_user("alice")
    ws = make_workspace(alice, name="Very Private")
    entry = _create_entry(client, ws["id"], alice["headers"])
    assert entry["is_public"] is False

    token = _enable_sharing(client, ws["id"], entry["id"], alice["headers"]).json()["share_token"]
    # No auth at all, and the workspace is private.
    res = client.get(f"/api/shared/{token}")
    assert res.status_code == 200


def test_shared_view_exposes_only_entry_content_not_workspace_info(client, make_user, make_workspace):
    alice = make_user("alice")
    ws = make_workspace(alice, name="Secret Workspace Name")
    entry = _create_entry(client, ws["id"], alice["headers"])
    token = _enable_sharing(client, ws["id"], entry["id"], alice["headers"]).json()["share_token"]

    body = client.get(f"/api/shared/{token}").json()
    disclosed_keys = set(body.keys())
    assert disclosed_keys == {
        "start_date",
        "end_date",
        "text",
        "playlist_id",
        "playlist_name",
        "playlist_url",
        "playlist_image_url",
        "latitude",
        "longitude",
        "location_name",
        "tags",
        "images",
    }
    # Nothing here names the workspace, the entry id, or the owner.
    assert "Secret Workspace Name" not in str(body)
    assert "workspace" not in str(body).lower()
    assert "alice" not in str(body).lower()


def test_shared_image_access_works_for_valid_token_and_404s_for_invalid(client, make_user, make_workspace):
    alice = make_user("alice")
    ws = make_workspace(alice, name="Solo")
    create_res = client.post(
        f"/api/workspaces/{ws['id']}/entries",
        headers=alice["headers"],
        data={
            "start_date": "2026-01-01",
            "playlist_id": "p1",
            "playlist_name": "Test",
            "playlist_url": "https://open.spotify.com/playlist/p1",
            "is_public": "false",
        },
        files=[("images", ("photo.png", b"fake image bytes", "image/png"))],
    )
    assert create_res.status_code == 201, create_res.text
    entry = create_res.json()
    image_id = entry["images"][0]["id"]

    token = _enable_sharing(client, ws["id"], entry["id"], alice["headers"]).json()["share_token"]

    ok_res = client.get(f"/api/shared/{token}/images/{image_id}")
    assert ok_res.status_code == 200
    assert ok_res.content == b"fake image bytes"

    assert client.get(f"/api/shared/{token}/images/999999").status_code == 404
    assert client.get(f"/api/shared/not-a-real-token/images/{image_id}").status_code == 404


def test_shared_image_endpoint_does_not_leak_another_entrys_image(client, make_user, make_workspace):
    """A valid token for entry A must never serve an image that belongs
    to a different entry, even one in the same workspace."""
    alice = make_user("alice")
    ws = make_workspace(alice, name="Solo")

    entry_a = client.post(
        f"/api/workspaces/{ws['id']}/entries",
        headers=alice["headers"],
        data={
            "start_date": "2026-01-01",
            "playlist_id": "pa",
            "playlist_name": "A",
            "playlist_url": "https://open.spotify.com/playlist/pa",
            "is_public": "false",
        },
        files=[("images", ("a.png", b"image a bytes", "image/png"))],
    ).json()
    entry_b = client.post(
        f"/api/workspaces/{ws['id']}/entries",
        headers=alice["headers"],
        data={
            "start_date": "2026-01-02",
            "playlist_id": "pb",
            "playlist_name": "B",
            "playlist_url": "https://open.spotify.com/playlist/pb",
            "is_public": "false",
        },
        files=[("images", ("b.png", b"image b bytes", "image/png"))],
    ).json()

    token_a = _enable_sharing(client, ws["id"], entry_a["id"], alice["headers"]).json()["share_token"]
    b_image_id = entry_b["images"][0]["id"]

    res = client.get(f"/api/shared/{token_a}/images/{b_image_id}")
    assert res.status_code == 404


def test_is_shared_flag_reflects_state_and_never_exposes_the_token(client, make_user, make_workspace):
    alice = make_user("alice")
    ws = make_workspace(alice, name="Solo")
    entry = _create_entry(client, ws["id"], alice["headers"])
    assert entry["is_shared"] is False
    assert "share_token" not in entry

    _enable_sharing(client, ws["id"], entry["id"], alice["headers"])
    refreshed = client.get(f"/api/workspaces/{ws['id']}/entries/{entry['id']}", headers=alice["headers"]).json()
    assert refreshed["is_shared"] is True
    assert "share_token" not in refreshed
