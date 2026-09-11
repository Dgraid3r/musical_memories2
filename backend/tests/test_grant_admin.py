from scripts.grant_admin import grant_admin


def test_grant_admin_grants_access(make_user, db_session):
    from app.models import User

    alice = make_user("alice")
    exit_code = grant_admin("alice")
    assert exit_code == 0

    db_session.expire_all()
    user = db_session.get(User, alice["id"])
    assert user.is_admin is True


def test_grant_admin_idempotent_when_already_admin(make_user, db_session):
    from app.models import User

    alice = make_user("alice")
    user = db_session.get(User, alice["id"])
    user.is_admin = True
    db_session.commit()

    exit_code = grant_admin("alice")
    assert exit_code == 0


def test_grant_admin_unknown_username_fails():
    exit_code = grant_admin("nobody-by-this-name")
    assert exit_code == 1


def test_grant_admin_refuses_deleted_account(client, make_user, db_session):
    from app.models import User

    alice = make_user("alice")
    del_res = client.request(
        "DELETE", "/api/account", headers=alice["headers"], json={"password": "password123"}
    )
    assert del_res.status_code == 200

    db_session.expire_all()
    scrubbed_username = db_session.get(User, alice["id"]).username

    exit_code = grant_admin(scrubbed_username)
    assert exit_code == 1

    db_session.expire_all()
    user = db_session.get(User, alice["id"])
    assert user.is_admin is False
