from sqlalchemy import select

from app.database import SessionLocal
from app.models import WorkspaceMembership


def _roles(workspace_id: int) -> dict[int, str]:
    db = SessionLocal()
    try:
        rows = db.scalars(
            select(WorkspaceMembership).where(WorkspaceMembership.workspace_id == workspace_id)
        ).all()
        return {m.user_id: m.role for m in rows}
    finally:
        db.close()


def test_transfer_ownership_requires_owner(client, make_user, make_workspace):
    alice = make_user("alice")
    bob = make_user("bob")
    carol = make_user("carol")
    ws = make_workspace(alice, bob, carol)

    res = client.patch(
        f"/api/workspaces/{ws['id']}/transfer-ownership",
        headers=bob["headers"],
        json={"new_owner_user_id": carol["id"]},
    )
    assert res.status_code == 403


def test_transfer_ownership_not_a_member_returns_404(client, make_user, make_workspace):
    alice = make_user("alice")
    outsider = make_user("outsider")
    ws = make_workspace(alice)

    res = client.patch(
        f"/api/workspaces/{ws['id']}/transfer-ownership",
        headers=outsider["headers"],
        json={"new_owner_user_id": alice["id"]},
    )
    assert res.status_code == 404


def test_transfer_ownership_target_must_already_be_a_member(client, make_user, make_workspace):
    alice = make_user("alice")
    stranger = make_user("stranger")
    ws = make_workspace(alice)

    res = client.patch(
        f"/api/workspaces/{ws['id']}/transfer-ownership",
        headers=alice["headers"],
        json={"new_owner_user_id": stranger["id"]},
    )
    assert res.status_code == 404
    assert "not a member" in res.json()["detail"].lower()

    # Nothing changed - alice is still sole owner.
    assert _roles(ws["id"]) == {alice["id"]: "owner"}


def test_transfer_ownership_rejects_transferring_to_self(client, make_user, make_workspace):
    alice = make_user("alice")
    ws = make_workspace(alice)

    res = client.patch(
        f"/api/workspaces/{ws['id']}/transfer-ownership",
        headers=alice["headers"],
        json={"new_owner_user_id": alice["id"]},
    )
    assert res.status_code == 400


def test_transfer_ownership_succeeds_and_is_immediate(client, make_user, make_workspace):
    alice = make_user("alice")
    bob = make_user("bob")
    ws = make_workspace(alice, bob)

    res = client.patch(
        f"/api/workspaces/{ws['id']}/transfer-ownership",
        headers=alice["headers"],
        json={"new_owner_user_id": bob["id"]},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["role"] == "member"  # the caller's (old owner's) own new role

    # Immediate - no accept step needed from bob.
    assert _roles(ws["id"]) == {alice["id"]: "member", bob["id"]: "owner"}

    members = client.get(f"/api/workspaces/{ws['id']}/members", headers=alice["headers"]).json()
    by_id = {m["user_id"]: m["role"] for m in members}
    assert by_id[alice["id"]] == "member"
    assert by_id[bob["id"]] == "owner"


def test_exactly_one_owner_before_and_after_transfer(client, make_user, make_workspace):
    alice = make_user("alice")
    bob = make_user("bob")
    carol = make_user("carol")
    ws = make_workspace(alice, bob, carol)

    def owners():
        return [uid for uid, role in _roles(ws["id"]).items() if role == "owner"]

    assert owners() == [alice["id"]]

    res = client.patch(
        f"/api/workspaces/{ws['id']}/transfer-ownership",
        headers=alice["headers"],
        json={"new_owner_user_id": bob["id"]},
    )
    assert res.status_code == 200
    assert owners() == [bob["id"]]


def test_new_owner_gains_owner_powers_and_old_owner_loses_them(client, make_user, make_workspace):
    """After transfer, the new owner can do owner-only things (invite,
    remove members) and the old owner can no longer do them - a real
    behavioral check, not just a database row check."""
    alice = make_user("alice")
    bob = make_user("bob")
    ws = make_workspace(alice, bob)

    client.patch(
        f"/api/workspaces/{ws['id']}/transfer-ownership",
        headers=alice["headers"],
        json={"new_owner_user_id": bob["id"]},
    )

    # bob (new owner) can now invite.
    invite_res = client.post(
        f"/api/workspaces/{ws['id']}/invites", headers=bob["headers"], json={"email": "dave@example.com"}
    )
    assert invite_res.status_code == 201

    # alice (old owner, now a plain member) can no longer invite.
    invite_res_alice = client.post(
        f"/api/workspaces/{ws['id']}/invites", headers=alice["headers"], json={"email": "eve@example.com"}
    )
    assert invite_res_alice.status_code == 403


def test_transferred_workspace_can_be_transferred_again(client, make_user, make_workspace):
    """Ownership can keep changing hands - not a one-shot action."""
    alice = make_user("alice")
    bob = make_user("bob")
    carol = make_user("carol")
    ws = make_workspace(alice, bob, carol)

    first = client.patch(
        f"/api/workspaces/{ws['id']}/transfer-ownership",
        headers=alice["headers"],
        json={"new_owner_user_id": bob["id"]},
    )
    assert first.status_code == 200

    second = client.patch(
        f"/api/workspaces/{ws['id']}/transfer-ownership",
        headers=bob["headers"],
        json={"new_owner_user_id": carol["id"]},
    )
    assert second.status_code == 200
    assert _roles(ws["id"]) == {alice["id"]: "member", bob["id"]: "member", carol["id"]: "owner"}


def test_transfer_ownership_to_a_subscriber_member_promotes_them(client, make_user, make_workspace):
    alice = make_user("alice")
    carol = make_user("carol")
    ws = make_workspace(alice)

    # Add carol as a subscriber via the real invite flow.
    invite_res = client.post(
        f"/api/workspaces/{ws['id']}/invites", headers=alice["headers"], json={"email": carol["email"], "role": "subscriber"}
    )
    assert invite_res.status_code == 201
    from app.email import last_email_to

    token = last_email_to(carol["email"])["token"]
    accept_res = client.post(f"/api/invites/{token}/accept", headers=carol["headers"])
    assert accept_res.status_code == 200
    assert accept_res.json()["role"] == "subscriber"

    res = client.patch(
        f"/api/workspaces/{ws['id']}/transfer-ownership",
        headers=alice["headers"],
        json={"new_owner_user_id": carol["id"]},
    )
    assert res.status_code == 200
    assert _roles(ws["id"])[carol["id"]] == "owner"


def test_transfer_ownership_requires_auth(client, make_user, make_workspace):
    alice = make_user("alice")
    ws = make_workspace(alice)

    res = client.patch(f"/api/workspaces/{ws['id']}/transfer-ownership", json={"new_owner_user_id": alice["id"]})
    assert res.status_code == 401
