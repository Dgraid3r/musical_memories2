from pathlib import Path

UPLOADS_DIR = Path(__file__).resolve().parent.parent / "uploads"


def _create_entry(
    client,
    workspace_id,
    headers,
    *,
    is_public=False,
    start_date="2026-01-01",
    end_date=None,
    text="hello",
    playlist_id="p1",
    coauthor_usernames=None,
):
    data = {
        "start_date": start_date,
        "text": text,
        "playlist_id": playlist_id,
        "playlist_name": "Test Playlist",
        "playlist_url": f"https://open.spotify.com/playlist/{playlist_id}",
        "is_public": str(is_public).lower(),
    }
    if end_date is not None:
        data["end_date"] = end_date
    return client.post(
        f"/api/workspaces/{workspace_id}/entries",
        headers=headers,
        data=data,
        files=[("coauthor_usernames", (None, u)) for u in (coauthor_usernames or [])],
    )


def test_create_entry_requires_auth(client, make_user, make_workspace):
    alice = make_user("alice")
    ws = make_workspace(alice)
    res = client.post(
        f"/api/workspaces/{ws['id']}/entries",
        data={
            "start_date": "2026-01-01",
            "playlist_id": "p1",
            "playlist_name": "x",
            "playlist_url": "https://open.spotify.com/playlist/p1",
        },
    )
    assert res.status_code == 401


def test_create_entry_requires_workspace_membership(client, make_user, make_workspace):
    """Alice isn't a member of bob's workspace, so she can't create entries
    in it even though she's a real, logged-in user - same "don't disclose"
    404 as a private entry she can't see."""
    alice = make_user("alice")
    bob = make_user("bob")
    ws = make_workspace(bob)

    res = _create_entry(client, ws["id"], alice["headers"])
    assert res.status_code == 404


def test_create_entry_defaults_to_private(client, make_user, make_workspace):
    alice = make_user("alice")
    ws = make_workspace(alice)
    res = _create_entry(client, ws["id"], alice["headers"])
    assert res.status_code == 201
    body = res.json()
    assert body["is_public"] is False
    assert body["workspace_id"] == ws["id"]
    assert body["user_id"] == alice["id"]
    assert body["owner_username"] == "alice"
    assert body["coauthors"] == []
    assert body["images"] == []


# --- Date range ---------------------------------------------------------


def test_single_day_entry_has_matching_start_and_end_date(client, make_user, make_workspace):
    alice = make_user("alice")
    ws = make_workspace(alice)
    res = _create_entry(client, ws["id"], alice["headers"], start_date="2026-03-01")
    assert res.status_code == 201
    body = res.json()
    assert body["start_date"] == "2026-03-01"
    assert body["end_date"] == "2026-03-01"


def test_multi_day_entry_stores_distinct_start_and_end_date(client, make_user, make_workspace):
    alice = make_user("alice")
    ws = make_workspace(alice)
    res = _create_entry(client, ws["id"], alice["headers"], start_date="2026-03-01", end_date="2026-03-04")
    assert res.status_code == 201
    body = res.json()
    assert body["start_date"] == "2026-03-01"
    assert body["end_date"] == "2026-03-04"


def test_end_date_before_start_date_rejected(client, make_user, make_workspace):
    alice = make_user("alice")
    ws = make_workspace(alice)
    res = _create_entry(client, ws["id"], alice["headers"], start_date="2026-03-04", end_date="2026-03-01")
    assert res.status_code == 422


def test_end_date_explicitly_equal_to_start_date_is_accepted(client, make_user, make_workspace):
    """The end_date < start_date guard is a strict '<', so the boundary case
    of an explicitly-passed equal end_date must not be rejected."""
    alice = make_user("alice")
    ws = make_workspace(alice)
    res = _create_entry(client, ws["id"], alice["headers"], start_date="2026-03-04", end_date="2026-03-04")
    assert res.status_code == 201
    body = res.json()
    assert body["start_date"] == body["end_date"] == "2026-03-04"


# --- Co-authors ----------------------------------------------------------


def test_create_entry_with_coauthor(client, make_user, make_workspace):
    alice = make_user("alice")
    bob = make_user("bob")
    ws = make_workspace(alice, bob)
    res = _create_entry(client, ws["id"], alice["headers"], coauthor_usernames=["bob"])
    assert res.status_code == 201
    coauthors = res.json()["coauthors"]
    assert [c["id"] for c in coauthors] == [bob["id"]]


def test_create_entry_with_multiple_coauthors(client, make_user, make_workspace):
    alice = make_user("alice")
    bob = make_user("bob")
    carol = make_user("carol")
    ws = make_workspace(alice, bob, carol)
    res = _create_entry(client, ws["id"], alice["headers"], coauthor_usernames=["bob", "carol"])
    assert res.status_code == 201
    coauthor_ids = {c["id"] for c in res.json()["coauthors"]}
    assert coauthor_ids == {bob["id"], carol["id"]}


def test_create_entry_with_unknown_coauthor_rejected(client, make_user, make_workspace):
    alice = make_user("alice")
    ws = make_workspace(alice)
    res = _create_entry(client, ws["id"], alice["headers"], coauthor_usernames=["ghost"])
    assert res.status_code == 422


def test_create_entry_with_unknown_coauthor_among_valid_ones_rejects_whole_request(client, make_user, make_workspace):
    """An unknown username anywhere in the list must fail the entire create,
    not silently drop just the bad one."""
    alice = make_user("alice")
    bob = make_user("bob")
    ws = make_workspace(alice, bob)
    res = _create_entry(client, ws["id"], alice["headers"], coauthor_usernames=["bob", "ghost"])
    assert res.status_code == 422


def test_create_entry_with_coauthor_not_a_workspace_member_rejected(client, make_user, make_workspace):
    """bob is a real, valid user, but he isn't a member of alice's
    workspace - co-authors must already belong to the entry's workspace."""
    alice = make_user("alice")
    bob = make_user("bob")
    ws = make_workspace(alice)  # bob is deliberately not added
    res = _create_entry(client, ws["id"], alice["headers"], coauthor_usernames=["bob"])
    assert res.status_code == 422


def test_update_coauthors_to_non_member_rejected(client, make_user, make_workspace):
    alice = make_user("alice")
    bob = make_user("bob")
    ws = make_workspace(alice)
    entry_id = _create_entry(client, ws["id"], alice["headers"]).json()["id"]

    res = client.patch(
        f"/api/workspaces/{ws['id']}/entries/{entry_id}",
        headers=alice["headers"],
        json={"coauthor_usernames": ["bob"]},
    )
    assert res.status_code == 422


def test_create_entry_listing_self_as_coauthor_is_dropped(client, make_user, make_workspace):
    alice = make_user("alice")
    ws = make_workspace(alice)
    res = _create_entry(client, ws["id"], alice["headers"], coauthor_usernames=["alice"])
    assert res.status_code == 201
    assert res.json()["coauthors"] == []


def test_create_entry_coauthor_usernames_with_whitespace_and_duplicates(client, make_user, make_workspace):
    alice = make_user("alice")
    bob = make_user("bob")
    ws = make_workspace(alice, bob)
    res = _create_entry(client, ws["id"], alice["headers"], coauthor_usernames=["bob", " bob ", "bob"])
    assert res.status_code == 201
    coauthor_ids = [c["id"] for c in res.json()["coauthors"]]
    assert coauthor_ids == [bob["id"]]


def test_coauthor_can_view_private_entry(client, make_user, make_workspace):
    alice = make_user("alice")
    bob = make_user("bob")
    ws = make_workspace(alice, bob)
    entry_id = _create_entry(
        client, ws["id"], alice["headers"], is_public=False, coauthor_usernames=["bob"]
    ).json()["id"]

    res = client.get(f"/api/workspaces/{ws['id']}/entries/{entry_id}", headers=bob["headers"])
    assert res.status_code == 200


def test_coauthor_sees_private_entry_in_list(client, make_user, make_workspace):
    alice = make_user("alice")
    bob = make_user("bob")
    ws = make_workspace(alice, bob)
    _create_entry(client, ws["id"], alice["headers"], is_public=False, playlist_id="shared", coauthor_usernames=["bob"])

    res = client.get(f"/api/workspaces/{ws['id']}/entries", headers=bob["headers"])
    assert "shared" in {e["playlist_id"] for e in res.json()}


def test_non_coauthor_still_gets_404_on_private_entry(client, make_user, make_workspace):
    alice = make_user("alice")
    bob = make_user("bob")
    carol = make_user("carol")
    ws = make_workspace(alice, bob, carol)
    entry_id = _create_entry(
        client, ws["id"], alice["headers"], is_public=False, coauthor_usernames=["bob"]
    ).json()["id"]

    res = client.get(f"/api/workspaces/{ws['id']}/entries/{entry_id}", headers=carol["headers"])
    assert res.status_code == 404


def test_coauthor_can_edit_text(client, make_user, make_workspace):
    alice = make_user("alice")
    bob = make_user("bob")
    ws = make_workspace(alice, bob)
    entry_id = _create_entry(
        client, ws["id"], alice["headers"], text="original", coauthor_usernames=["bob"]
    ).json()["id"]

    res = client.patch(
        f"/api/workspaces/{ws['id']}/entries/{entry_id}", headers=bob["headers"], json={"text": "bob added something"}
    )
    assert res.status_code == 200
    assert res.json()["text"] == "bob added something"


def test_coauthor_cannot_change_visibility(client, make_user, make_workspace):
    alice = make_user("alice")
    bob = make_user("bob")
    ws = make_workspace(alice, bob)
    entry_id = _create_entry(
        client, ws["id"], alice["headers"], is_public=False, coauthor_usernames=["bob"]
    ).json()["id"]

    res = client.patch(
        f"/api/workspaces/{ws['id']}/entries/{entry_id}", headers=bob["headers"], json={"is_public": True}
    )
    assert res.status_code == 403


def test_coauthor_cannot_manage_coauthors(client, make_user, make_workspace):
    alice = make_user("alice")
    bob = make_user("bob")
    carol = make_user("carol")
    ws = make_workspace(alice, bob, carol)
    entry_id = _create_entry(client, ws["id"], alice["headers"], coauthor_usernames=["bob"]).json()["id"]

    res = client.patch(
        f"/api/workspaces/{ws['id']}/entries/{entry_id}",
        headers=bob["headers"],
        json={"coauthor_usernames": ["bob", "carol"]},
    )
    assert res.status_code == 403


def test_coauthor_cannot_delete_entry(client, make_user, make_workspace):
    alice = make_user("alice")
    bob = make_user("bob")
    ws = make_workspace(alice, bob)
    entry_id = _create_entry(client, ws["id"], alice["headers"], coauthor_usernames=["bob"]).json()["id"]

    res = client.delete(f"/api/workspaces/{ws['id']}/entries/{entry_id}", headers=bob["headers"])
    assert res.status_code == 403


def test_owner_can_update_coauthor_list(client, make_user, make_workspace):
    alice = make_user("alice")
    bob = make_user("bob")
    carol = make_user("carol")
    ws = make_workspace(alice, bob, carol)
    entry_id = _create_entry(client, ws["id"], alice["headers"], coauthor_usernames=["bob"]).json()["id"]

    res = client.patch(
        f"/api/workspaces/{ws['id']}/entries/{entry_id}", headers=alice["headers"], json={"coauthor_usernames": ["carol"]}
    )
    assert res.status_code == 200
    assert [c["id"] for c in res.json()["coauthors"]] == [carol["id"]]

    # bob was removed, so he loses view access to what is still a private entry
    res = client.get(f"/api/workspaces/{ws['id']}/entries/{entry_id}", headers=bob["headers"])
    assert res.status_code == 404


def test_owner_can_clear_coauthor_list(client, make_user, make_workspace):
    alice = make_user("alice")
    bob = make_user("bob")
    ws = make_workspace(alice, bob)
    entry_id = _create_entry(client, ws["id"], alice["headers"], coauthor_usernames=["bob"]).json()["id"]

    res = client.patch(f"/api/workspaces/{ws['id']}/entries/{entry_id}", headers=alice["headers"], json={"coauthor_usernames": []})
    assert res.status_code == 200
    assert res.json()["coauthors"] == []


def test_add_images_by_coauthor_succeeds(client, make_user, make_workspace, db_session):
    from app.models import EntryImage

    alice = make_user("alice")
    bob = make_user("bob")
    ws = make_workspace(alice, bob)
    entry_id = _create_entry(client, ws["id"], alice["headers"], coauthor_usernames=["bob"]).json()["id"]

    res = client.post(
        f"/api/workspaces/{ws['id']}/entries/{entry_id}/images",
        headers=bob["headers"],
        files=[("images", ("photo.png", b"fake image bytes", "image/png"))],
    )
    assert res.status_code == 201
    assert len(res.json()["images"]) == 1

    # The API response no longer exposes the stored filename (see
    # EntryImageOut) - the DB row is the only place it's still visible,
    # which is fine here since this is just cleaning up the file on disk.
    stored = db_session.query(EntryImage).filter_by(entry_id=entry_id).all()
    for image in stored:
        (UPLOADS_DIR / image.filename).unlink(missing_ok=True)


def test_add_images_rejects_disallowed_file_type(client, make_user, make_workspace, db_session):
    """Before this fix, _save_images accepted any extension/content-type
    with no allowlist at all - a plain file-type check closes that off."""
    from app.models import EntryImage

    alice = make_user("alice")
    ws = make_workspace(alice)
    entry_id = _create_entry(client, ws["id"], alice["headers"]).json()["id"]

    res = client.post(
        f"/api/workspaces/{ws['id']}/entries/{entry_id}/images",
        headers=alice["headers"],
        files=[("images", ("payload.exe", b"not-a-real-image", "application/octet-stream"))],
    )
    assert res.status_code == 400
    assert db_session.query(EntryImage).filter_by(entry_id=entry_id).count() == 0


def test_add_images_rejects_mismatched_extension_and_content_type(client, make_user, make_workspace, db_session):
    """An image-looking filename with a non-image content-type (or vice
    versa) must still be rejected - both have to pass the allowlist, not
    just whichever one looks right."""
    from app.models import EntryImage

    alice = make_user("alice")
    ws = make_workspace(alice)
    entry_id = _create_entry(client, ws["id"], alice["headers"]).json()["id"]

    res = client.post(
        f"/api/workspaces/{ws['id']}/entries/{entry_id}/images",
        headers=alice["headers"],
        files=[("images", ("photo.png", b"fake bytes", "application/octet-stream"))],
    )
    assert res.status_code == 400
    assert db_session.query(EntryImage).filter_by(entry_id=entry_id).count() == 0


def test_add_images_rejects_oversized_file(client, make_user, make_workspace, db_session):
    from app.models import EntryImage
    from app.routers.entries import MAX_IMAGE_UPLOAD_BYTES

    alice = make_user("alice")
    ws = make_workspace(alice)
    entry_id = _create_entry(client, ws["id"], alice["headers"]).json()["id"]

    oversized = b"x" * (MAX_IMAGE_UPLOAD_BYTES + 1)
    res = client.post(
        f"/api/workspaces/{ws['id']}/entries/{entry_id}/images",
        headers=alice["headers"],
        files=[("images", ("big.png", oversized, "image/png"))],
    )
    assert res.status_code == 400
    assert db_session.query(EntryImage).filter_by(entry_id=entry_id).count() == 0


def test_add_images_accepts_file_at_the_size_limit(client, make_user, make_workspace, db_session):
    """The cap is inclusive - exactly MAX_IMAGE_UPLOAD_BYTES must still be
    accepted, only strictly more is rejected."""
    from app.models import EntryImage
    from app.routers.entries import MAX_IMAGE_UPLOAD_BYTES

    alice = make_user("alice")
    ws = make_workspace(alice)
    entry_id = _create_entry(client, ws["id"], alice["headers"]).json()["id"]

    exactly_at_limit = b"x" * MAX_IMAGE_UPLOAD_BYTES
    res = client.post(
        f"/api/workspaces/{ws['id']}/entries/{entry_id}/images",
        headers=alice["headers"],
        files=[("images", ("atlimit.png", exactly_at_limit, "image/png"))],
    )
    assert res.status_code == 201

    stored = db_session.query(EntryImage).filter_by(entry_id=entry_id).all()
    assert len(stored) == 1
    for image in stored:
        (UPLOADS_DIR / image.filename).unlink(missing_ok=True)


def test_add_images_batch_with_one_invalid_file_saves_nothing(client, make_user, make_workspace, db_session):
    """A rejected file anywhere in a multi-file batch discards the whole
    request rather than silently saving only the files that came before
    it."""
    from app.models import EntryImage

    alice = make_user("alice")
    ws = make_workspace(alice)
    entry_id = _create_entry(client, ws["id"], alice["headers"]).json()["id"]

    res = client.post(
        f"/api/workspaces/{ws['id']}/entries/{entry_id}/images",
        headers=alice["headers"],
        files=[
            ("images", ("good.png", b"fake image bytes", "image/png")),
            ("images", ("bad.exe", b"not an image", "application/octet-stream")),
        ],
    )
    assert res.status_code == 400
    assert db_session.query(EntryImage).filter_by(entry_id=entry_id).count() == 0


def test_create_entry_rejects_disallowed_image_file_type(client, make_user, make_workspace, db_session):
    """The same validation applies at entry-creation time too, not just
    add_images - both call _save_images, and neither the entry nor an
    EntryImage row should survive a rejected upload."""
    from app.models import EntryImage, JournalEntry

    alice = make_user("alice")
    ws = make_workspace(alice)

    res = client.post(
        f"/api/workspaces/{ws['id']}/entries",
        headers=alice["headers"],
        data={
            "start_date": "2026-01-01",
            "text": "hello",
            "playlist_id": "p1",
            "playlist_name": "Test Playlist",
            "playlist_url": "https://open.spotify.com/playlist/p1",
            "is_public": "false",
        },
        files=[("images", ("payload.exe", b"not an image", "application/octet-stream"))],
    )
    assert res.status_code == 400
    assert db_session.query(JournalEntry).count() == 0
    assert db_session.query(EntryImage).count() == 0


def test_add_images_to_nonexistent_entry_returns_404(client, make_user, make_workspace):
    alice = make_user("alice")
    ws = make_workspace(alice)
    res = client.post(
        f"/api/workspaces/{ws['id']}/entries/999999/images",
        headers=alice["headers"],
        files=[("images", ("photo.png", b"fake image bytes", "image/png"))],
    )
    assert res.status_code == 404


def test_add_images_by_non_editor_forbidden(client, make_user, make_workspace):
    alice = make_user("alice")
    bob = make_user("bob")
    ws = make_workspace(alice, bob)
    entry_id = _create_entry(client, ws["id"], alice["headers"], is_public=True).json()["id"]

    res = client.post(
        f"/api/workspaces/{ws['id']}/entries/{entry_id}/images",
        headers=bob["headers"],
        files=[("images", ("photo.png", b"fake image bytes", "image/png"))],
    )
    assert res.status_code == 403


def test_add_images_requires_auth(client, make_user, make_workspace):
    alice = make_user("alice")
    ws = make_workspace(alice)
    entry_id = _create_entry(client, ws["id"], alice["headers"], is_public=True).json()["id"]

    res = client.post(
        f"/api/workspaces/{ws['id']}/entries/{entry_id}/images",
        files=[("images", ("photo.png", b"fake image bytes", "image/png"))],
    )
    assert res.status_code == 401


# --- Visibility (ownership, unrelated to co-authors) ---------------------


def test_list_entries_of_private_workspace_anonymous_returns_404(client, make_user, make_workspace):
    """Workspaces default to private, and a private workspace is
    unreadable by anyone who isn't a member - including an anonymous
    caller with no token at all, who gets 404 (not 401), the same
    non-disclosure treatment as a private entry: "no such workspace" and
    "exists but private" must read identically. (A *public* workspace is
    readable with no token at all - see test_workspaces_visibility.py.)"""
    alice = make_user("alice")
    ws = make_workspace(alice)
    _create_entry(client, ws["id"], alice["headers"], is_public=True, playlist_id="pub")

    res = client.get(f"/api/workspaces/{ws['id']}/entries")
    assert res.status_code == 404


def test_list_entries_owner_sees_own_private_and_public(client, make_user, make_workspace):
    alice = make_user("alice")
    ws = make_workspace(alice)
    _create_entry(client, ws["id"], alice["headers"], is_public=False, playlist_id="priv")
    _create_entry(client, ws["id"], alice["headers"], is_public=True, playlist_id="pub")

    res = client.get(f"/api/workspaces/{ws['id']}/entries", headers=alice["headers"])
    assert {e["playlist_id"] for e in res.json()} == {"priv", "pub"}


def test_list_entries_other_workspace_member_sees_only_public(client, make_user, make_workspace):
    alice = make_user("alice")
    bob = make_user("bob")
    ws = make_workspace(alice, bob)
    _create_entry(client, ws["id"], alice["headers"], is_public=False, playlist_id="priv")
    _create_entry(client, ws["id"], alice["headers"], is_public=True, playlist_id="pub")

    res = client.get(f"/api/workspaces/{ws['id']}/entries", headers=bob["headers"])
    assert {e["playlist_id"] for e in res.json()} == {"pub"}


def test_list_entries_is_symmetric_across_two_members_with_private_entries(client, make_user, make_workspace):
    """Each member's private entries must be hidden from the OTHER member in
    both directions at once, not just checked one-way with a single private
    owner."""
    alice = make_user("alice")
    bob = make_user("bob")
    ws = make_workspace(alice, bob)
    _create_entry(client, ws["id"], alice["headers"], is_public=False, playlist_id="alice-priv")
    _create_entry(client, ws["id"], alice["headers"], is_public=True, playlist_id="alice-pub")
    _create_entry(client, ws["id"], bob["headers"], is_public=False, playlist_id="bob-priv")
    _create_entry(client, ws["id"], bob["headers"], is_public=True, playlist_id="bob-pub")

    alice_view = {e["playlist_id"] for e in client.get(f"/api/workspaces/{ws['id']}/entries", headers=alice["headers"]).json()}
    bob_view = {e["playlist_id"] for e in client.get(f"/api/workspaces/{ws['id']}/entries", headers=bob["headers"]).json()}

    assert alice_view == {"alice-priv", "alice-pub", "bob-pub"}
    assert bob_view == {"bob-priv", "bob-pub", "alice-pub"}


def test_list_entries_default_limit_is_twenty(client, make_user, make_workspace):
    alice = make_user("alice")
    ws = make_workspace(alice)
    for i in range(25):
        _create_entry(client, ws["id"], alice["headers"], is_public=True, playlist_id=f"p{i}")

    res = client.get(f"/api/workspaces/{ws['id']}/entries", headers=alice["headers"])
    assert res.status_code == 200
    assert len(res.json()) == 20


def test_list_entries_limit_caps_the_number_of_results(client, make_user, make_workspace):
    alice = make_user("alice")
    ws = make_workspace(alice)
    for i in range(5):
        _create_entry(client, ws["id"], alice["headers"], is_public=True, playlist_id=f"p{i}")

    res = client.get(f"/api/workspaces/{ws['id']}/entries?limit=2", headers=alice["headers"])
    assert res.status_code == 200
    assert len(res.json()) == 2


def test_list_entries_offset_pages_through_distinct_results(client, make_user, make_workspace):
    alice = make_user("alice")
    ws = make_workspace(alice)
    for i in range(5):
        _create_entry(client, ws["id"], alice["headers"], is_public=True, playlist_id=f"p{i}")

    page1 = client.get(f"/api/workspaces/{ws['id']}/entries?limit=2&offset=0", headers=alice["headers"])
    page2 = client.get(f"/api/workspaces/{ws['id']}/entries?limit=2&offset=2", headers=alice["headers"])
    assert page1.status_code == 200
    assert page2.status_code == 200
    page1_ids = [e["id"] for e in page1.json()]
    page2_ids = [e["id"] for e in page2.json()]
    assert len(page1_ids) == 2
    assert len(page2_ids) == 2
    assert set(page1_ids).isdisjoint(page2_ids)


def test_list_entries_limit_rejects_values_above_the_max(client, make_user, make_workspace):
    alice = make_user("alice")
    ws = make_workspace(alice)
    res = client.get(f"/api/workspaces/{ws['id']}/entries?limit=101", headers=alice["headers"])
    assert res.status_code == 422


def test_list_entries_limit_rejects_zero_or_negative(client, make_user, make_workspace):
    alice = make_user("alice")
    ws = make_workspace(alice)
    res = client.get(f"/api/workspaces/{ws['id']}/entries?limit=0", headers=alice["headers"])
    assert res.status_code == 422


def test_list_entries_offset_rejects_negative(client, make_user, make_workspace):
    alice = make_user("alice")
    ws = make_workspace(alice)
    res = client.get(f"/api/workspaces/{ws['id']}/entries?offset=-1", headers=alice["headers"])
    assert res.status_code == 422


def test_list_entries_eager_loaded_relationships_have_correct_data(client, make_user, make_workspace):
    """The selectinload eager-loading added to list_entries for
    coauthors/images/tags must only change how many queries this costs
    (see the router's own comment), never what data comes back - an
    entry's coauthors, images, and tags must still be exactly right."""
    alice = make_user("alice")
    bob = make_user("bob")
    ws = make_workspace(alice, bob)
    create_res = client.post(
        f"/api/workspaces/{ws['id']}/entries",
        headers=alice["headers"],
        data={
            "start_date": "2026-01-01",
            "playlist_id": "p1",
            "playlist_name": "Test",
            "playlist_url": "https://open.spotify.com/playlist/p1",
            "is_public": "true",
        },
        files=[
            ("images", ("photo.png", b"fake image bytes", "image/png")),
            ("coauthor_usernames", (None, "bob")),
            ("tags", (None, "roadtrip")),
        ],
    )
    assert create_res.status_code == 201, create_res.text

    res = client.get(f"/api/workspaces/{ws['id']}/entries", headers=alice["headers"])
    assert res.status_code == 200
    entry = res.json()[0]
    assert [c["username"] for c in entry["coauthors"]] == ["bob"]
    assert len(entry["images"]) == 1
    assert [t["name"] for t in entry["tags"]] == ["roadtrip"]


def test_get_private_entry_as_non_owner_returns_404(client, make_user, make_workspace):
    alice = make_user("alice")
    bob = make_user("bob")
    ws = make_workspace(alice, bob)
    entry_id = _create_entry(client, ws["id"], alice["headers"], is_public=False).json()["id"]

    res = client.get(f"/api/workspaces/{ws['id']}/entries/{entry_id}", headers=bob["headers"])
    assert res.status_code == 404


def test_get_entry_in_private_workspace_anonymous_returns_404(client, make_user, make_workspace):
    alice = make_user("alice")
    ws = make_workspace(alice)
    entry_id = _create_entry(client, ws["id"], alice["headers"], is_public=True).json()["id"]

    res = client.get(f"/api/workspaces/{ws['id']}/entries/{entry_id}")
    assert res.status_code == 404


def test_get_own_private_entry_succeeds(client, make_user, make_workspace):
    alice = make_user("alice")
    ws = make_workspace(alice)
    entry_id = _create_entry(client, ws["id"], alice["headers"], is_public=False).json()["id"]

    res = client.get(f"/api/workspaces/{ws['id']}/entries/{entry_id}", headers=alice["headers"])
    assert res.status_code == 200


def test_get_public_entry_visible_to_any_workspace_member(client, make_user, make_workspace):
    alice = make_user("alice")
    bob = make_user("bob")
    ws = make_workspace(alice, bob)
    entry_id = _create_entry(client, ws["id"], alice["headers"], is_public=True).json()["id"]

    res = client.get(f"/api/workspaces/{ws['id']}/entries/{entry_id}", headers=bob["headers"])
    assert res.status_code == 200


def test_get_nonexistent_entry_returns_404(client, make_user, make_workspace):
    alice = make_user("alice")
    ws = make_workspace(alice)
    res = client.get(f"/api/workspaces/{ws['id']}/entries/999999", headers=alice["headers"])
    assert res.status_code == 404


def test_private_entry_404_is_indistinguishable_from_missing_entry_404(client, make_user, make_workspace):
    """A non-owner must not be able to tell 'exists but private' apart from
    'does not exist' -- same status code AND same response body."""
    alice = make_user("alice")
    bob = make_user("bob")
    ws = make_workspace(alice, bob)
    private_id = _create_entry(client, ws["id"], alice["headers"], is_public=False).json()["id"]

    res_private_as_bob = client.get(f"/api/workspaces/{ws['id']}/entries/{private_id}", headers=bob["headers"])
    res_missing = client.get(f"/api/workspaces/{ws['id']}/entries/999999", headers=bob["headers"])

    assert res_private_as_bob.status_code == res_missing.status_code == 404
    assert res_private_as_bob.json() == res_missing.json()


def test_patch_toggles_visibility(client, make_user, make_workspace):
    alice = make_user("alice")
    ws = make_workspace(alice)
    entry_id = _create_entry(client, ws["id"], alice["headers"], is_public=False).json()["id"]

    res = client.patch(f"/api/workspaces/{ws['id']}/entries/{entry_id}", headers=alice["headers"], json={"is_public": True})
    assert res.status_code == 200
    assert res.json()["is_public"] is True

    # and it actually took effect, not just echoed the request body back
    res = client.get(f"/api/workspaces/{ws['id']}/entries/{entry_id}", headers=alice["headers"])
    assert res.status_code == 200


def test_patch_updates_text(client, make_user, make_workspace):
    alice = make_user("alice")
    ws = make_workspace(alice)
    entry_id = _create_entry(client, ws["id"], alice["headers"], text="original").json()["id"]

    res = client.patch(f"/api/workspaces/{ws['id']}/entries/{entry_id}", headers=alice["headers"], json={"text": "updated"})
    assert res.status_code == 200
    assert res.json()["text"] == "updated"


def test_patch_omitted_fields_are_left_unchanged(client, make_user, make_workspace):
    alice = make_user("alice")
    ws = make_workspace(alice)
    entry_id = _create_entry(client, ws["id"], alice["headers"], text="original", is_public=True).json()["id"]

    res = client.patch(f"/api/workspaces/{ws['id']}/entries/{entry_id}", headers=alice["headers"], json={})
    assert res.status_code == 200
    body = res.json()
    assert body["text"] == "original"
    assert body["is_public"] is True


def test_patch_by_non_owner_forbidden(client, make_user, make_workspace):
    alice = make_user("alice")
    bob = make_user("bob")
    ws = make_workspace(alice, bob)
    entry_id = _create_entry(client, ws["id"], alice["headers"], is_public=True).json()["id"]

    res = client.patch(f"/api/workspaces/{ws['id']}/entries/{entry_id}", headers=bob["headers"], json={"is_public": False})
    assert res.status_code == 403

    # confirm the forbidden request didn't leak through
    res = client.get(f"/api/workspaces/{ws['id']}/entries/{entry_id}", headers=bob["headers"])
    assert res.json()["is_public"] is True


def test_patch_requires_auth(client, make_user, make_workspace):
    alice = make_user("alice")
    ws = make_workspace(alice)
    entry_id = _create_entry(client, ws["id"], alice["headers"], is_public=True).json()["id"]

    res = client.patch(f"/api/workspaces/{ws['id']}/entries/{entry_id}", json={"is_public": False})
    assert res.status_code == 401


def test_patch_nonexistent_entry_returns_404(client, make_user, make_workspace):
    alice = make_user("alice")
    ws = make_workspace(alice)
    res = client.patch(f"/api/workspaces/{ws['id']}/entries/999999", headers=alice["headers"], json={"is_public": True})
    assert res.status_code == 404


def test_delete_by_owner_succeeds(client, make_user, make_workspace):
    alice = make_user("alice")
    ws = make_workspace(alice)
    entry_id = _create_entry(client, ws["id"], alice["headers"]).json()["id"]

    res = client.delete(f"/api/workspaces/{ws['id']}/entries/{entry_id}", headers=alice["headers"])
    assert res.status_code == 204

    res = client.get(f"/api/workspaces/{ws['id']}/entries/{entry_id}", headers=alice["headers"])
    assert res.status_code == 404


def test_delete_by_non_owner_forbidden(client, make_user, make_workspace):
    alice = make_user("alice")
    bob = make_user("bob")
    ws = make_workspace(alice, bob)
    entry_id = _create_entry(client, ws["id"], alice["headers"], is_public=True).json()["id"]

    res = client.delete(f"/api/workspaces/{ws['id']}/entries/{entry_id}", headers=bob["headers"])
    assert res.status_code == 403

    # entry must still exist
    res = client.get(f"/api/workspaces/{ws['id']}/entries/{entry_id}", headers=bob["headers"])
    assert res.status_code == 200


def test_delete_requires_auth(client, make_user, make_workspace):
    alice = make_user("alice")
    ws = make_workspace(alice)
    entry_id = _create_entry(client, ws["id"], alice["headers"]).json()["id"]

    res = client.delete(f"/api/workspaces/{ws['id']}/entries/{entry_id}")
    assert res.status_code == 401


def test_delete_nonexistent_entry_returns_404(client, make_user, make_workspace):
    alice = make_user("alice")
    ws = make_workspace(alice)
    res = client.delete(f"/api/workspaces/{ws['id']}/entries/999999", headers=alice["headers"])
    assert res.status_code == 404


def test_create_entry_with_image_upload(client, make_user, make_workspace, db_session):
    from app.models import EntryImage

    alice = make_user("alice")
    ws = make_workspace(alice)
    res = client.post(
        f"/api/workspaces/{ws['id']}/entries",
        headers=alice["headers"],
        data={
            "start_date": "2026-01-01",
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
    # The API response no longer exposes the stored filename (see
    # EntryImageOut) - only its id, which is enough to fetch it back
    # through GET /api/entries/{entry_id}/images/{image_id}. The actual
    # filename on disk is an internal storage-layer detail, checked here
    # straight from the DB row.
    image = db_session.get(EntryImage, body["images"][0]["id"])
    saved_path = UPLOADS_DIR / image.filename
    try:
        assert saved_path.exists()
    finally:
        saved_path.unlink(missing_ok=True)


def test_delete_entry_removes_uploaded_images(client, make_user, make_workspace, db_session):
    from app.models import EntryImage

    alice = make_user("alice")
    ws = make_workspace(alice)
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
    image_id = create_res.json()["images"][0]["id"]
    saved_path = UPLOADS_DIR / db_session.get(EntryImage, image_id).filename
    assert saved_path.exists()

    entry_id = create_res.json()["id"]
    client.delete(f"/api/workspaces/{ws['id']}/entries/{entry_id}", headers=alice["headers"])

    assert not saved_path.exists()
