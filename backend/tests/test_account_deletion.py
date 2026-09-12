from datetime import datetime

from sqlalchemy import select

from app.database import SessionLocal
from app.email import last_email_to
from app.models import EmailVerificationToken, PasswordResetToken, SpotifyToken, User, Workspace, WorkspaceMembership


def _create_entry(client, workspace_id, headers, *, is_public=True, playlist_id="p1", coauthor_usernames=None):
    data = {
        "start_date": "2026-01-01",
        "text": "hello",
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


def _comment(client, workspace_id, entry_id, headers, body="hello"):
    res = client.post(
        f"/api/workspaces/{workspace_id}/entries/{entry_id}/comments", headers=headers, json={"body": body}
    )
    assert res.status_code == 201, res.text
    return res.json()


def _delete_account(client, headers, password="password123"):
    return client.request("DELETE", "/api/account", headers=headers, json={"password": password})


def _get_user_row(user_id: int) -> User:
    db = SessionLocal()
    try:
        return db.get(User, user_id)
    finally:
        db.close()


# --- Re-authentication ---------------------------------------------------


def test_delete_account_requires_auth(client):
    res = client.request("DELETE", "/api/account", json={"password": "whatever"})
    assert res.status_code == 401


def test_delete_account_wrong_password_rejected(client, make_user):
    alice = make_user("alice")
    res = _delete_account(client, alice["headers"], password="wrong-password")
    assert res.status_code == 401

    # Nothing changed - alice can still log in normally.
    login_res = client.post("/api/sessions", json={"username": "alice", "password": "password123"})
    assert login_res.status_code == 201
    row = _get_user_row(alice["id"])
    assert row.deleted_at is None


def test_delete_account_correct_password_succeeds(client, make_user, make_workspace):
    alice = make_user("alice")
    make_workspace(alice, name="Alice Only")  # sole owner, sole member - safe to cascade
    res = _delete_account(client, alice["headers"])
    assert res.status_code == 200
    assert "permanently deleted" in res.json()["detail"].lower()


# --- Anonymization, not deletion, of shared content -----------------------


def test_deleted_users_entries_and_comments_survive_and_show_deleted_user(client, make_user, make_workspace):
    alice = make_user("alice")
    bob = make_user("bob")
    ws = make_workspace(alice, bob)

    entry = _create_entry(client, ws["id"], alice["headers"], is_public=True)
    comment = _comment(client, ws["id"], entry["id"], alice["headers"], body="alice's comment")

    # Transfer ownership to bob first (alice is sole owner with another
    # member present, which would otherwise block deletion).
    xfer = client.patch(
        f"/api/workspaces/{ws['id']}/transfer-ownership",
        headers=alice["headers"],
        json={"new_owner_user_id": bob["id"]},
    )
    assert xfer.status_code == 200

    del_res = _delete_account(client, alice["headers"])
    assert del_res.status_code == 200

    # The entry and comment still exist, now attributed to "Deleted user".
    entry_res = client.get(f"/api/workspaces/{ws['id']}/entries/{entry['id']}", headers=bob["headers"])
    assert entry_res.status_code == 200
    entry_body = entry_res.json()
    assert entry_body["user_id"] == alice["id"]
    assert entry_body["owner_username"] == "Deleted user"

    comments_res = client.get(
        f"/api/workspaces/{ws['id']}/entries/{entry['id']}/comments", headers=bob["headers"]
    )
    assert comments_res.status_code == 200
    comments = comments_res.json()
    assert len(comments) == 1
    assert comments[0]["id"] == comment["id"]
    assert comments[0]["author_id"] == alice["id"]
    assert comments[0]["author_username"] == "Deleted user"


def test_deleted_coauthor_appears_as_deleted_user_on_a_survivors_entry(client, make_user, make_workspace):
    alice = make_user("alice")
    bob = make_user("bob")
    # bob owns the workspace - alice is a plain member, so she can delete
    # her own account with no ownership transfer needed.
    ws = make_workspace(bob, alice)

    # bob authors an entry, alice co-authors it.
    entry = _create_entry(client, ws["id"], bob["headers"], coauthor_usernames=["alice"])
    coauthor_ids = [c["id"] for c in entry["coauthors"]]
    assert alice["id"] in coauthor_ids

    del_res = _delete_account(client, alice["headers"])
    assert del_res.status_code == 200

    entry_res = client.get(f"/api/workspaces/{ws['id']}/entries/{entry['id']}", headers=bob["headers"])
    assert entry_res.status_code == 200
    coauthors = entry_res.json()["coauthors"]
    assert len(coauthors) == 1
    assert coauthors[0]["id"] == alice["id"]
    assert coauthors[0]["username"] == "Deleted user"


# --- Login truly blocked after deletion -----------------------------------


def test_deleted_user_cannot_log_in_with_old_credentials(client, make_user, make_workspace):
    alice = make_user("alice")
    make_workspace(alice, name="Alice Only")
    _delete_account(client, alice["headers"])

    res = client.post("/api/sessions", json={"username": "alice", "password": "password123"})
    assert res.status_code == 401


def test_deleted_user_old_jwt_stops_authenticating(client, make_user, make_workspace):
    """The access token issued before deletion must stop working
    immediately - this is what "revoking all active sessions" means for a
    stateless JWT with no server-side session table (see auth._user_from_token)."""
    alice = make_user("alice")
    make_workspace(alice, name="Alice Only")
    old_headers = dict(alice["headers"])

    del_res = _delete_account(client, old_headers)
    assert del_res.status_code == 200

    me_res = client.get("/api/users/me", headers=old_headers)
    assert me_res.status_code == 401


# --- Sole-ownership blocking / cascading -----------------------------------


def test_sole_owner_with_other_members_blocks_deletion_naming_workspace(client, make_user, make_workspace):
    alice = make_user("alice")
    bob = make_user("bob")
    ws = make_workspace(alice, bob, name="Shared Trip")

    res = _delete_account(client, alice["headers"])
    assert res.status_code == 409
    detail = res.json()["detail"]
    assert "Shared Trip" in detail
    assert "transfer" in detail.lower()

    # Nothing was touched - alice is still there, workspace intact.
    row = _get_user_row(alice["id"])
    assert row.deleted_at is None
    db = SessionLocal()
    try:
        ws_row = db.get(Workspace, ws["id"])
        assert ws_row is not None
        memberships = db.scalars(
            select(WorkspaceMembership).where(WorkspaceMembership.workspace_id == ws["id"])
        ).all()
        assert {m.user_id for m in memberships} == {alice["id"], bob["id"]}
    finally:
        db.close()


def test_sole_owner_with_subscriber_also_blocks_deletion(client, make_user, make_workspace):
    """A subscriber (read-only) still counts as "other members" - they have
    legitimate access to the workspace's content and would otherwise be
    orphaned along with it."""
    alice = make_user("alice")
    carol = make_user("carol")
    ws = make_workspace(alice, name="Read Only Folks")

    invite_res = client.post(
        f"/api/workspaces/{ws['id']}/invites",
        headers=alice["headers"],
        json={"email": carol["email"], "role": "subscriber"},
    )
    assert invite_res.status_code == 201
    token = last_email_to(carol["email"])["token"]
    accept_res = client.post(f"/api/invites/{token}/accept", headers=carol["headers"])
    assert accept_res.status_code == 200

    res = _delete_account(client, alice["headers"])
    assert res.status_code == 409
    assert "Read Only Folks" in res.json()["detail"]


def test_multiple_blocking_workspaces_all_named(client, make_user, make_workspace):
    alice = make_user("alice")
    bob = make_user("bob")
    carol = make_user("carol")
    make_workspace(alice, bob, name="Workspace One")
    make_workspace(alice, carol, name="Workspace Two")

    res = _delete_account(client, alice["headers"])
    assert res.status_code == 409
    detail = res.json()["detail"]
    assert "Workspace One" in detail
    assert "Workspace Two" in detail


def test_sole_owner_and_only_member_cascades_workspace_cleanly(client, make_user, make_workspace):
    alice = make_user("alice")
    ws = make_workspace(alice, name="Just Alice")
    entry = _create_entry(client, ws["id"], alice["headers"])

    res = _delete_account(client, alice["headers"])
    assert res.status_code == 200

    db = SessionLocal()
    try:
        assert db.get(Workspace, ws["id"]) is None
        memberships = db.scalars(
            select(WorkspaceMembership).where(WorkspaceMembership.workspace_id == ws["id"])
        ).all()
        assert memberships == []
    finally:
        db.close()

    # The workspace's entry is gone too (cascaded), not left orphaned.
    from app.models import JournalEntry

    db = SessionLocal()
    try:
        assert db.get(JournalEntry, entry["id"]) is None
    finally:
        db.close()


def test_sole_owner_cascade_removes_uploaded_photo_files(client, make_user, make_workspace, db_session):
    """The sole-owned-workspace cascade (see delete_account's own
    comment) only ever removes database rows through the ORM - without
    explicit cleanup, every photo on every entry in that workspace would
    stay orphaned in storage forever. See
    workspaces.collect_workspace_image_filenames/delete_stored_images."""
    from pathlib import Path

    from app.models import EntryImage

    uploads_dir = Path(__file__).resolve().parent.parent / "uploads"

    alice = make_user("alice")
    ws = make_workspace(alice, name="Just Alice")
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
    saved_path = uploads_dir / db_session.get(EntryImage, image_id).filename
    assert saved_path.exists()

    res = _delete_account(client, alice["headers"])
    assert res.status_code == 200

    assert not saved_path.exists()

    # And nothing errored - user row itself still exists, anonymized.
    row = _get_user_row(alice["id"])
    assert row is not None
    assert row.deleted_at is not None


def test_mixed_blocking_and_cascading_workspaces(client, make_user, make_workspace):
    """alice owns two workspaces: one solo (cascades), one shared with bob
    (blocks). The whole deletion must be refused - partial deletion would
    be worse than no deletion."""
    alice = make_user("alice")
    bob = make_user("bob")
    solo_ws = make_workspace(alice, name="Solo")
    shared_ws = make_workspace(alice, bob, name="Shared")

    res = _delete_account(client, alice["headers"])
    assert res.status_code == 409
    assert "Shared" in res.json()["detail"]

    # Nothing changed at all, including the solo workspace that would have
    # been safe to cascade on its own.
    db = SessionLocal()
    try:
        assert db.get(Workspace, solo_ws["id"]) is not None
        assert db.get(Workspace, shared_ws["id"]) is not None
    finally:
        db.close()
    row = _get_user_row(alice["id"])
    assert row.deleted_at is None


def test_member_role_not_owner_can_delete_freely(client, make_user, make_workspace):
    """A plain member (not owner) of a shared workspace can delete their
    account without any transfer, since they don't own anything."""
    alice = make_user("alice")
    bob = make_user("bob")
    ws = make_workspace(alice, bob)

    res = _delete_account(client, bob["headers"])
    assert res.status_code == 200

    db = SessionLocal()
    try:
        assert db.get(Workspace, ws["id"]) is not None  # untouched
        memberships = db.scalars(
            select(WorkspaceMembership).where(WorkspaceMembership.workspace_id == ws["id"])
        ).all()
        assert {m.user_id for m in memberships} == {alice["id"]}  # bob's membership removed
    finally:
        db.close()


# --- Memberships removed, tokens/spotify cleaned up ------------------------


def test_deleted_users_memberships_removed(client, make_user, make_workspace):
    alice = make_user("alice")
    bob = make_user("bob")
    ws = make_workspace(alice, bob)

    _delete_account(client, bob["headers"])

    db = SessionLocal()
    try:
        memberships = db.scalars(select(WorkspaceMembership).where(WorkspaceMembership.user_id == bob["id"])).all()
        assert memberships == []
    finally:
        db.close()


def test_spotify_token_deleted_on_account_deletion(client, make_user, make_workspace, db_session):
    alice = make_user("alice")
    make_workspace(alice, name="Solo")

    db_session.add(
        SpotifyToken(
            user_id=alice["id"],
            access_token="fake-access",
            refresh_token="fake-refresh",
            expires_at=datetime.utcnow(),
        )
    )
    db_session.commit()

    res = _delete_account(client, alice["headers"])
    assert res.status_code == 200

    db = SessionLocal()
    try:
        assert db.scalar(select(SpotifyToken).where(SpotifyToken.user_id == alice["id"])) is None
    finally:
        db.close()


def test_verification_and_reset_tokens_cleaned_up(client, make_user, make_workspace, db_session):
    alice = make_user("alice")
    make_workspace(alice, name="Solo")

    # Registration already created an EmailVerificationToken row for alice
    # (at most one live row per user, per the model's unique user_id index)
    # - update it rather than inserting a second one.
    existing = db_session.scalar(
        select(EmailVerificationToken).where(EmailVerificationToken.user_id == alice["id"])
    )
    assert existing is not None
    existing.token = "tok1"

    db_session.add(
        PasswordResetToken(user_id=alice["id"], token="tok2", expires_at=datetime(2099, 1, 1))
    )
    db_session.commit()

    res = _delete_account(client, alice["headers"])
    assert res.status_code == 200

    db = SessionLocal()
    try:
        assert db.scalar(select(EmailVerificationToken).where(EmailVerificationToken.user_id == alice["id"])) is None
        assert db.scalar(select(PasswordResetToken).where(PasswordResetToken.user_id == alice["id"])) is None
    finally:
        db.close()


def test_deleted_user_pii_scrubbed(client, make_user, make_workspace):
    alice = make_user("alice")
    make_workspace(alice, name="Solo")

    _delete_account(client, alice["headers"])

    row = _get_user_row(alice["id"])
    assert row.deleted_at is not None
    assert row.username != "alice"
    assert row.email != "alice@example.com"
    assert row.email.endswith("@deleted.invalid")
    assert row.is_deleted is True


def test_deleted_user_excluded_from_coauthor_search(client, make_user, make_workspace):
    alice = make_user("alice")
    bob = make_user("bob")
    ws = make_workspace(alice, bob)

    _delete_account(client, bob["headers"])

    res = client.get("/api/users?q=bob", headers=alice["headers"])
    assert res.status_code == 200
    assert res.json() == []
