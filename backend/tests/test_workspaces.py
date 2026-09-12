from pathlib import Path

UPLOADS_DIR = Path(__file__).resolve().parent.parent / "uploads"


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


# --- Workspace CRUD ----------------------------------------------------


def test_create_workspace_requires_auth(client):
    res = client.post("/api/workspaces", json={"name": "My Family"})
    assert res.status_code == 401


def test_create_workspace_makes_caller_owner(client, make_user):
    alice = make_user("alice")
    res = client.post("/api/workspaces", headers=alice["headers"], json={"name": "My Family"})
    assert res.status_code == 201
    body = res.json()
    assert body["name"] == "My Family"
    assert body["created_by"] == alice["id"]
    assert body["role"] == "owner"


def test_create_workspace_requires_nonempty_name(client, make_user):
    alice = make_user("alice")
    res = client.post("/api/workspaces", headers=alice["headers"], json={"name": ""})
    assert res.status_code == 422


def test_list_workspaces_requires_auth(client):
    res = client.get("/api/workspaces")
    assert res.status_code == 401


def test_list_workspaces_returns_only_callers_own(client, make_user, make_workspace):
    alice = make_user("alice")
    bob = make_user("bob")
    make_workspace(alice, name="Alice's Workspace")
    make_workspace(bob, name="Bob's Workspace")

    res = client.get("/api/workspaces", headers=alice["headers"])
    assert res.status_code == 200
    names = {w["name"] for w in res.json()}
    assert names == {"Alice's Workspace"}


def test_list_workspaces_shows_correct_role_per_workspace(client, make_user, make_workspace):
    """alice owns one workspace and is just a member of another - the list
    must reflect her actual role in each, not a single global role."""
    alice = make_user("alice")
    bob = make_user("bob")
    owned = make_workspace(alice, name="Owned by Alice")
    joined = make_workspace(bob, alice, name="Owned by Bob")

    res = client.get("/api/workspaces", headers=alice["headers"])
    assert res.status_code == 200
    roles_by_name = {w["name"]: w["role"] for w in res.json()}
    assert roles_by_name == {"Owned by Alice": "owner", "Owned by Bob": "member"}
    assert {w["id"] for w in res.json()} == {owned["id"], joined["id"]}


def test_delete_workspace_owner_only(client, make_user, make_workspace):
    alice = make_user("alice")
    bob = make_user("bob")
    ws = make_workspace(alice, bob)

    res = client.delete(f"/api/workspaces/{ws['id']}", headers=bob["headers"])
    assert res.status_code == 403


def test_delete_workspace_not_a_member_returns_404(client, make_user, make_workspace):
    alice = make_user("alice")
    outsider = make_user("outsider")
    ws = make_workspace(alice)

    res = client.delete(f"/api/workspaces/{ws['id']}", headers=outsider["headers"])
    assert res.status_code == 404


def test_delete_workspace_by_owner_succeeds(client, make_user, make_workspace):
    alice = make_user("alice")
    ws = make_workspace(alice)

    res = client.delete(f"/api/workspaces/{ws['id']}", headers=alice["headers"])
    assert res.status_code == 204

    res = client.get("/api/workspaces", headers=alice["headers"])
    assert res.json() == []


def test_delete_workspace_cascades_entries_and_comments(client, make_user, make_workspace):
    alice = make_user("alice")
    ws = make_workspace(alice)
    entry = _create_entry(client, ws["id"], alice["headers"], is_public=True)
    comment_res = client.post(
        f"/api/workspaces/{ws['id']}/entries/{entry['id']}/comments", headers=alice["headers"], json={"body": "hi"}
    )
    assert comment_res.status_code == 201
    comment_id = comment_res.json()["id"]

    res = client.delete(f"/api/workspaces/{ws['id']}", headers=alice["headers"])
    assert res.status_code == 204

    # The comment is gone too, not orphaned - editing it now 404s (same
    # non-disclosure pattern as any other now-inaccessible resource).
    res = client.patch(f"/api/comments/{comment_id}", headers=alice["headers"], json={"body": "x"})
    assert res.status_code == 404


def test_delete_workspace_removes_uploaded_photo_files(client, make_user, make_workspace, db_session):
    """The ORM cascade (see models.py's cascade="all, delete-orphan"
    relationships) only ever removes database rows - without explicit
    cleanup, every photo on every entry in a deleted workspace would
    stay orphaned on disk (or in object storage) forever. See
    workspaces.collect_workspace_image_filenames/delete_stored_images."""
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
    assert create_res.status_code == 201, create_res.text
    image_id = create_res.json()["images"][0]["id"]
    saved_path = UPLOADS_DIR / db_session.get(EntryImage, image_id).filename
    assert saved_path.exists()

    res = client.delete(f"/api/workspaces/{ws['id']}", headers=alice["headers"])
    assert res.status_code == 204

    assert not saved_path.exists()


def test_workspace_not_found_returns_404(client, make_user):
    alice = make_user("alice")
    res = client.get("/api/workspaces/999999/members", headers=alice["headers"])
    assert res.status_code == 404


# --- Membership management ----------------------------------------------
#
# Adding a member is now a real, email-based, consent-required invite flow
# rather than an owner unilaterally adding an existing username - see
# test_invites.py for that flow's own thorough coverage (accept as an
# existing user, accept via registration, expiry, revocation, roles,
# already-a-member handling, etc.). What remains here is the membership
# roster/removal endpoints, which are unchanged.


def test_list_members_requires_membership(client, make_user, make_workspace):
    alice = make_user("alice")
    outsider = make_user("outsider")
    ws = make_workspace(alice)

    res = client.get(f"/api/workspaces/{ws['id']}/members", headers=outsider["headers"])
    assert res.status_code == 404


def test_list_members_includes_role(client, make_user, make_workspace):
    alice = make_user("alice")
    bob = make_user("bob")
    ws = make_workspace(alice, bob)

    res = client.get(f"/api/workspaces/{ws['id']}/members", headers=bob["headers"])
    assert res.status_code == 200
    roles = {m["username"]: m["role"] for m in res.json()}
    assert roles == {"alice": "owner", "bob": "member"}


def test_remove_member_owner_only(client, make_user, make_workspace):
    alice = make_user("alice")
    bob = make_user("bob")
    carol = make_user("carol")
    ws = make_workspace(alice, bob, carol)

    res = client.delete(f"/api/workspaces/{ws['id']}/members/{carol['id']}", headers=bob["headers"])
    assert res.status_code == 403


def test_remove_member_owner_cannot_remove_self(client, make_user, make_workspace):
    alice = make_user("alice")
    ws = make_workspace(alice)

    res = client.delete(f"/api/workspaces/{ws['id']}/members/{alice['id']}", headers=alice["headers"])
    assert res.status_code == 400


def test_remove_member_not_a_member_returns_404(client, make_user, make_workspace):
    alice = make_user("alice")
    outsider = make_user("outsider")
    ws = make_workspace(alice)

    res = client.delete(f"/api/workspaces/{ws['id']}/members/{outsider['id']}", headers=alice["headers"])
    assert res.status_code == 404


def test_remove_member_by_owner_succeeds_and_revokes_access(client, make_user, make_workspace):
    alice = make_user("alice")
    bob = make_user("bob")
    ws = make_workspace(alice, bob)
    _create_entry(client, ws["id"], alice["headers"], is_public=True)

    res = client.delete(f"/api/workspaces/{ws['id']}/members/{bob['id']}", headers=alice["headers"])
    assert res.status_code == 204

    res = client.get(f"/api/workspaces/{ws['id']}/entries", headers=bob["headers"])
    assert res.status_code == 404


# --- Multi-workspace membership -------------------------------------------


def test_user_can_belong_to_multiple_workspaces_scoped_independently(client, make_user, make_workspace):
    """carol is a member of both alice's and bob's workspaces at once (a
    switcher, not a single fixed workspace per account) - each workspace's
    data must stay correctly scoped and never mix, from carol's point of
    view in either direction."""
    alice = make_user("alice")
    bob = make_user("bob")
    carol = make_user("carol")
    ws_a = make_workspace(alice, carol, name="Alice's Workspace")
    ws_b = make_workspace(bob, carol, name="Bob's Workspace")

    entry_a = _create_entry(client, ws_a["id"], alice["headers"], is_public=True, playlist_id="in-a")
    entry_b = _create_entry(client, ws_b["id"], bob["headers"], is_public=True, playlist_id="in-b")

    carol_ws_list = {w["id"] for w in client.get("/api/workspaces", headers=carol["headers"]).json()}
    assert carol_ws_list == {ws_a["id"], ws_b["id"]}

    a_entries = client.get(f"/api/workspaces/{ws_a['id']}/entries", headers=carol["headers"]).json()
    b_entries = client.get(f"/api/workspaces/{ws_b['id']}/entries", headers=carol["headers"]).json()

    assert [e["playlist_id"] for e in a_entries] == ["in-a"]
    assert [e["playlist_id"] for e in b_entries] == ["in-b"]

    # And carol can reach each entry individually, correctly scoped.
    assert client.get(f"/api/workspaces/{ws_a['id']}/entries/{entry_a['id']}", headers=carol["headers"]).status_code == 200
    assert client.get(f"/api/workspaces/{ws_b['id']}/entries/{entry_b['id']}", headers=carol["headers"]).status_code == 200


def test_multi_workspace_member_private_entries_stay_workspace_scoped(client, make_user, make_workspace):
    """carol has a private entry in each of her two workspaces - alice
    (only in workspace A) must never see carol's workspace-B private entry,
    and bob (only in workspace B) must never see her workspace-A one."""
    alice = make_user("alice")
    bob = make_user("bob")
    carol = make_user("carol")
    ws_a = make_workspace(alice, carol, name="Workspace A")
    ws_b = make_workspace(bob, carol, name="Workspace B")

    _create_entry(client, ws_a["id"], carol["headers"], is_public=False, playlist_id="carol-a-private")
    _create_entry(client, ws_b["id"], carol["headers"], is_public=False, playlist_id="carol-b-private")

    alice_view = {e["playlist_id"] for e in client.get(f"/api/workspaces/{ws_a['id']}/entries", headers=alice["headers"]).json()}
    bob_view = {e["playlist_id"] for e in client.get(f"/api/workspaces/{ws_b['id']}/entries", headers=bob["headers"]).json()}

    # carol's private entries aren't public, and neither alice nor bob is
    # their author or a co-author, so neither sees them in their own
    # workspace's list.
    assert alice_view == set()
    assert bob_view == set()

    # And alice can't even reach workspace B to try.
    assert client.get(f"/api/workspaces/{ws_b['id']}/entries", headers=alice["headers"]).status_code == 404


# --- Cross-workspace isolation (guessing an ID directly) -------------------


def test_entry_not_reachable_via_a_different_workspace_id(client, make_user, make_workspace):
    """bob's entry lives in workspace B. alice is a member of workspace A
    only. Even though alice is a real, authenticated, workspace-having user,
    naming bob's entry id under *her own* workspace's URL must 404 - the
    entry simply doesn't belong to workspace A."""
    alice = make_user("alice")
    bob = make_user("bob")
    ws_a = make_workspace(alice, name="Workspace A")
    ws_b = make_workspace(bob, name="Workspace B")
    bob_entry = _create_entry(client, ws_b["id"], bob["headers"], is_public=True)

    res = client.get(f"/api/workspaces/{ws_a['id']}/entries/{bob_entry['id']}", headers=alice["headers"])
    assert res.status_code == 404


def test_entry_not_reachable_by_non_member_even_with_correct_workspace_id(client, make_user, make_workspace):
    """Same setup, but this time alice uses bob's *actual* workspace id in
    the URL - she still can't reach it, because she isn't a member of that
    workspace at all."""
    alice = make_user("alice")
    bob = make_user("bob")
    make_workspace(alice, name="Workspace A")
    ws_b = make_workspace(bob, name="Workspace B")
    bob_entry = _create_entry(client, ws_b["id"], bob["headers"], is_public=True)

    res = client.get(f"/api/workspaces/{ws_b['id']}/entries/{bob_entry['id']}", headers=alice["headers"])
    assert res.status_code == 404


def test_entry_list_never_leaks_across_workspaces_for_the_same_user(client, make_user, make_workspace):
    """alice owns two separate workspaces (e.g. one family, one friend
    group). An entry created in one must never appear when listing the
    other, even though she's the owner (and author) of both."""
    alice = make_user("alice")
    ws_a = make_workspace(alice, name="Family")
    ws_b = make_workspace(alice, name="Friends")
    _create_entry(client, ws_a["id"], alice["headers"], is_public=True, playlist_id="family-trip")
    _create_entry(client, ws_b["id"], alice["headers"], is_public=True, playlist_id="friends-trip")

    a_view = {e["playlist_id"] for e in client.get(f"/api/workspaces/{ws_a['id']}/entries", headers=alice["headers"]).json()}
    b_view = {e["playlist_id"] for e in client.get(f"/api/workspaces/{ws_b['id']}/entries", headers=alice["headers"]).json()}

    assert a_view == {"family-trip"}
    assert b_view == {"friends-trip"}


def test_comment_not_reachable_from_a_workspace_the_caller_is_not_in(client, make_user, make_workspace):
    alice = make_user("alice")
    bob = make_user("bob")
    ws_b = make_workspace(bob, name="Workspace B")
    bob_entry = _create_entry(client, ws_b["id"], bob["headers"], is_public=True)
    comment_res = client.post(
        f"/api/workspaces/{ws_b['id']}/entries/{bob_entry['id']}/comments", headers=bob["headers"], json={"body": "hi"}
    )
    comment_id = comment_res.json()["id"]

    # alice is not a member of workspace B at all.
    res = client.patch(f"/api/comments/{comment_id}", headers=alice["headers"], json={"body": "hacked"})
    assert res.status_code == 404
    res = client.delete(f"/api/comments/{comment_id}", headers=alice["headers"])
    assert res.status_code == 404


def test_coauthor_candidate_from_a_different_workspace_is_rejected(client, make_user, make_workspace):
    """bob is a member of workspace B but not workspace A - alice can't add
    him as a co-author on an entry in workspace A even though he's a real,
    valid username."""
    alice = make_user("alice")
    bob = make_user("bob")
    ws_a = make_workspace(alice, name="Workspace A")
    make_workspace(bob, name="Workspace B")

    res = client.post(
        f"/api/workspaces/{ws_a['id']}/entries",
        headers=alice["headers"],
        data={
            "start_date": "2026-01-01",
            "playlist_id": "p1",
            "playlist_name": "Test",
            "playlist_url": "https://open.spotify.com/playlist/p1",
            "is_public": "false",
        },
        files=[("coauthor_usernames", (None, "bob"))],
    )
    assert res.status_code == 422
