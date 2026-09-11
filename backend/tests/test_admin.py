from datetime import datetime, timedelta

from app.models import BackupRun, User, Workspace


def _make_admin(make_user, db_session, username="admin"):
    admin = make_user(username)
    user = db_session.get(User, admin["id"])
    user.is_admin = True
    db_session.commit()
    return admin


# --- Access control ----------------------------------------------------


def test_admin_endpoints_require_auth(client):
    assert client.get("/api/admin/users").status_code == 401
    assert client.get("/api/admin/stats").status_code == 401
    assert client.post("/api/admin/users/1/deactivate").status_code == 401
    assert client.post("/api/admin/users/1/reactivate").status_code == 401


def test_admin_endpoints_forbidden_for_non_admin(client, make_user):
    alice = make_user("alice")
    assert client.get("/api/admin/users", headers=alice["headers"]).status_code == 403
    assert client.get("/api/admin/stats", headers=alice["headers"]).status_code == 403
    assert client.post(f"/api/admin/users/{alice['id']}/deactivate", headers=alice["headers"]).status_code == 403
    assert client.post(f"/api/admin/users/{alice['id']}/reactivate", headers=alice["headers"]).status_code == 403


# --- User search/list ----------------------------------------------------


def test_admin_list_users_returns_results(client, make_user, db_session):
    admin = _make_admin(make_user, db_session)
    make_user("bob")

    res = client.get("/api/admin/users", headers=admin["headers"])
    assert res.status_code == 200
    body = res.json()
    usernames = {u["username"] for u in body}
    assert {"admin", "bob"} <= usernames
    bob = next(u for u in body if u["username"] == "bob")
    assert bob["email"] == "bob@example.com"
    assert bob["is_admin"] is False
    assert bob["is_active"] is True
    assert bob["is_deleted"] is False
    assert "created_at" in bob and "email_verified" in bob


def test_admin_list_users_search_by_username(client, make_user, db_session):
    admin = _make_admin(make_user, db_session)
    make_user("roadtrip_ron")
    make_user("someoneelse")

    res = client.get("/api/admin/users?q=roadtrip", headers=admin["headers"])
    assert res.status_code == 200
    usernames = {u["username"] for u in res.json()}
    assert usernames == {"roadtrip_ron"}


def test_admin_list_users_search_by_email(client, make_user, db_session):
    admin = _make_admin(make_user, db_session)
    make_user("carol")

    res = client.get("/api/admin/users?q=carol@example.com", headers=admin["headers"])
    assert res.status_code == 200
    usernames = {u["username"] for u in res.json()}
    assert usernames == {"carol"}


def test_admin_list_users_pagination(client, make_user, db_session):
    # 3 paged users + admin = 4 registrations total - stays under
    # AUTH_RATE_LIMIT ("5/minute"), which register() is subject to.
    admin = _make_admin(make_user, db_session)
    for i in range(3):
        make_user(f"paged{i}")

    page1 = client.get("/api/admin/users?limit=2&offset=0", headers=admin["headers"])
    page2 = client.get("/api/admin/users?limit=2&offset=2", headers=admin["headers"])
    assert page1.status_code == 200
    assert page2.status_code == 200
    ids1 = {u["id"] for u in page1.json()}
    ids2 = {u["id"] for u in page2.json()}
    assert len(ids1) == 2
    assert len(ids2) == 2
    assert ids1.isdisjoint(ids2)


def test_admin_list_users_rejects_limit_above_max(client, make_user, db_session):
    admin = _make_admin(make_user, db_session)
    res = client.get("/api/admin/users?limit=101", headers=admin["headers"])
    assert res.status_code == 422


def test_admin_list_users_masks_deleted_user(client, make_user, db_session):
    admin = _make_admin(make_user, db_session)
    victim = make_user("todelete")
    make_workspace_res = client.post(
        "/api/workspaces", headers=victim["headers"], json={"name": "Solo"}
    )
    assert make_workspace_res.status_code == 201

    del_res = client.request(
        "DELETE", "/api/account", headers=victim["headers"], json={"password": "password123"}
    )
    assert del_res.status_code == 200

    res = client.get("/api/admin/users", headers=admin["headers"])
    assert res.status_code == 200
    match = next(u for u in res.json() if u["id"] == victim["id"])
    assert match["username"] == "Deleted user"
    assert match["is_deleted"] is True
    # The real username never leaks even in its masked form.
    assert "todelete" not in res.text


# --- Deactivate / reactivate ---------------------------------------------


def test_admin_deactivate_blocks_password_login(client, make_user, db_session):
    admin = _make_admin(make_user, db_session)
    bob = make_user("bob")

    deact_res = client.post(f"/api/admin/users/{bob['id']}/deactivate", headers=admin["headers"])
    assert deact_res.status_code == 200

    login_res = client.post("/api/sessions", json={"username": "bob", "password": "password123"})
    assert login_res.status_code == 401


def test_admin_deactivate_blocks_existing_token(client, make_user, db_session):
    """A token issued before deactivation must stop authenticating
    immediately, the same "revoke on next request" property self-
    deletion already has."""
    admin = _make_admin(make_user, db_session)
    bob = make_user("bob")
    old_token_headers = dict(bob["headers"])

    deact_res = client.post(f"/api/admin/users/{bob['id']}/deactivate", headers=admin["headers"])
    assert deact_res.status_code == 200

    me_res = client.get("/api/users/me", headers=old_token_headers)
    assert me_res.status_code == 401


def test_admin_reactivate_restores_login(client, make_user, db_session):
    admin = _make_admin(make_user, db_session)
    bob = make_user("bob")

    client.post(f"/api/admin/users/{bob['id']}/deactivate", headers=admin["headers"])
    login_blocked = client.post("/api/sessions", json={"username": "bob", "password": "password123"})
    assert login_blocked.status_code == 401

    react_res = client.post(f"/api/admin/users/{bob['id']}/reactivate", headers=admin["headers"])
    assert react_res.status_code == 200

    login_res = client.post("/api/sessions", json={"username": "bob", "password": "password123"})
    assert login_res.status_code == 201


def test_admin_deactivate_does_not_touch_other_fields(client, make_user, db_session):
    admin = _make_admin(make_user, db_session)
    bob = make_user("bob")

    client.post(f"/api/admin/users/{bob['id']}/deactivate", headers=admin["headers"])

    db_session.expire_all()
    user = db_session.get(User, bob["id"])
    assert user.username == "bob"
    assert user.email == "bob@example.com"
    assert user.is_deleted is False
    assert user.is_active is False


def test_admin_cannot_deactivate_self(client, make_user, db_session):
    admin = _make_admin(make_user, db_session)
    res = client.post(f"/api/admin/users/{admin['id']}/deactivate", headers=admin["headers"])
    assert res.status_code == 400

    # Self is untouched and can still log in.
    login_res = client.post("/api/sessions", json={"username": "admin", "password": "password123"})
    assert login_res.status_code == 201


def test_admin_can_deactivate_another_admin(client, make_user, db_session):
    """v1 deliberately has no admin-hierarchy system - only self-
    deactivation is blocked."""
    admin1 = _make_admin(make_user, db_session, username="admin1")
    admin2 = _make_admin(make_user, db_session, username="admin2")

    res = client.post(f"/api/admin/users/{admin2['id']}/deactivate", headers=admin1["headers"])
    assert res.status_code == 200

    login_res = client.post("/api/sessions", json={"username": "admin2", "password": "password123"})
    assert login_res.status_code == 401


def test_admin_deactivate_nonexistent_user_404(client, make_user, db_session):
    admin = _make_admin(make_user, db_session)
    res = client.post("/api/admin/users/999999/deactivate", headers=admin["headers"])
    assert res.status_code == 404


# --- Stats -----------------------------------------------------------------


def test_admin_stats_counts_are_accurate(client, make_user, db_session):
    admin = _make_admin(make_user, db_session)
    bob = make_user("bob")
    carol = make_user("carol")

    ws_res = client.post("/api/workspaces", headers=bob["headers"], json={"name": "Trip"})
    assert ws_res.status_code == 201
    ws_id = ws_res.json()["id"]

    for i in range(2):
        entry_res = client.post(
            f"/api/workspaces/{ws_id}/entries",
            headers=bob["headers"],
            data={
                "start_date": "2026-01-01",
                "playlist_id": f"p{i}",
                "playlist_name": "Test",
                "playlist_url": f"https://open.spotify.com/playlist/p{i}",
                "is_public": "true",
            },
        )
        assert entry_res.status_code == 201

    res = client.get("/api/admin/stats", headers=admin["headers"])
    assert res.status_code == 200
    body = res.json()
    # admin + bob + carol = 3 users total in this freshly-created test DB
    # (the autouse _clean_database fixture gives every test its own
    # empty database, so this count is exact, not "at least").
    assert body["total_users"] == 3
    assert body["total_workspaces"] == 1
    assert body["total_entries"] == 2
    assert body["database_healthy"] is True


def test_admin_stats_new_signups_windows(client, make_user, db_session):
    admin = _make_admin(make_user, db_session)
    recent = make_user("recentsignup")
    old = make_user("oldsignup")

    old_user = db_session.get(User, old["id"])
    old_user.created_at = datetime.utcnow() - timedelta(days=31)
    db_session.commit()

    res = client.get("/api/admin/stats", headers=admin["headers"])
    assert res.status_code == 200
    body = res.json()
    # admin + recent are within both windows; old is outside both.
    assert body["new_signups_7d"] == 2
    assert body["new_signups_30d"] == 2


def test_admin_stats_no_backup_runs_yet(client, make_user, db_session):
    admin = _make_admin(make_user, db_session)
    res = client.get("/api/admin/stats", headers=admin["headers"])
    assert res.status_code == 200
    assert res.json()["latest_backup"] is None


def test_admin_stats_reflects_most_recent_backup_run(client, make_user, db_session):
    admin = _make_admin(make_user, db_session)

    older = datetime.utcnow() - timedelta(hours=2)
    newer = datetime.utcnow() - timedelta(minutes=5)
    db_session.add(BackupRun(started_at=older, succeeded=False, error_message="pg_dump exited 1: boom"))
    db_session.add(BackupRun(started_at=newer, succeeded=True, error_message=None))
    db_session.commit()

    res = client.get("/api/admin/stats", headers=admin["headers"])
    assert res.status_code == 200
    latest = res.json()["latest_backup"]
    assert latest is not None
    assert latest["succeeded"] is True
    assert latest["error_message"] is None
