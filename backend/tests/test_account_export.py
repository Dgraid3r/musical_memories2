import io
import json
import zipfile

from app.database import SessionLocal
from app.models import EntryImage


def _create_entry(
    client,
    workspace_id,
    headers,
    *,
    playlist_id="p1",
    coauthor_usernames=None,
    tags=None,
    images=None,
    latitude=None,
    longitude=None,
    location_name=None,
    text="hello",
):
    data = {
        "start_date": "2026-01-01",
        "text": text,
        "playlist_id": playlist_id,
        "playlist_name": "Test Playlist",
        "playlist_url": f"https://open.spotify.com/playlist/{playlist_id}",
        "is_public": "true",
    }
    if latitude is not None:
        data["latitude"] = str(latitude)
        data["longitude"] = str(longitude)
        data["location_name"] = location_name
    files = [("coauthor_usernames", (None, u)) for u in (coauthor_usernames or [])]
    files += [("tags", (None, t)) for t in (tags or [])]
    files += list(images or [])
    res = client.post(
        f"/api/workspaces/{workspace_id}/entries",
        headers=headers,
        data=data,
        files=files or None,
    )
    assert res.status_code == 201, res.text
    return res.json()


def _comment(client, workspace_id, entry_id, headers, body="hello"):
    res = client.post(
        f"/api/workspaces/{workspace_id}/entries/{entry_id}/comments", headers=headers, json={"body": body}
    )
    assert res.status_code == 201, res.text
    return res.json()


def _export(client, headers):
    res = client.get("/api/account/export", headers=headers)
    assert res.status_code == 200, res.text
    assert res.headers["content-type"] == "application/zip"
    assert "attachment" in res.headers["content-disposition"]
    archive = zipfile.ZipFile(io.BytesIO(res.content))
    data = json.loads(archive.read("data.json"))
    return archive, data


def test_export_requires_auth(client):
    res = client.get("/api/account/export")
    assert res.status_code == 401


def test_export_empty_user_gets_valid_empty_archive(client, make_user):
    alice = make_user("alice")
    archive, data = _export(client, alice["headers"])
    assert data["entries"] == []
    assert data["comments"] == []
    assert data["profile"]["username"] == "alice"
    assert data["profile"]["email"] == "alice@example.com"
    assert "created_at" in data["profile"]
    # No photos/ entries at all when there's nothing to export.
    assert all(not name.startswith("photos/") for name in archive.namelist())


def test_export_includes_authored_entry_full_content(client, make_user, make_workspace):
    alice = make_user("alice")
    ws = make_workspace(alice, name="Alice's Trips")
    entry = _create_entry(
        client,
        ws["id"],
        alice["headers"],
        tags=["road trip", "summer"],
        latitude=40.0,
        longitude=-74.0,
        location_name="New York",
        text="a great day",
    )

    _, data = _export(client, alice["headers"])
    assert len(data["entries"]) == 1
    exported = data["entries"][0]
    assert exported["id"] == entry["id"]
    assert exported["role"] == "author"
    assert exported["text"] == "a great day"
    assert exported["workspace"]["id"] == ws["id"]
    assert exported["workspace"]["name"] == "Alice's Trips"
    assert set(exported["tags"]) == {"road trip", "summer"}
    assert exported["location"] == {"latitude": 40.0, "longitude": -74.0, "name": "New York"}
    assert exported["playlist"]["id"] == "p1"
    assert exported["playlist"]["url"] == "https://open.spotify.com/playlist/p1"
    assert exported["start_date"] == "2026-01-01"


def test_export_includes_coauthored_entry(client, make_user, make_workspace):
    alice = make_user("alice")
    bob = make_user("bob")
    ws = make_workspace(alice, bob)
    entry = _create_entry(client, ws["id"], alice["headers"], coauthor_usernames=["bob"])

    _, data = _export(client, bob["headers"])
    assert len(data["entries"]) == 1
    assert data["entries"][0]["id"] == entry["id"]
    assert data["entries"][0]["role"] == "coauthor"


def test_export_excludes_entries_user_can_only_view(client, make_user, make_workspace):
    """Being a workspace member with view access is not enough - only
    entries this user authored or co-authored belong in their export."""
    alice = make_user("alice")
    bob = make_user("bob")
    ws = make_workspace(alice, bob)
    _create_entry(client, ws["id"], alice["headers"])  # bob is neither author nor coauthor

    _, data = _export(client, bob["headers"])
    assert data["entries"] == []


def test_export_includes_own_comment_on_someone_elses_entry(client, make_user, make_workspace):
    alice = make_user("alice")
    bob = make_user("bob")
    ws = make_workspace(alice, bob)
    entry = _create_entry(client, ws["id"], alice["headers"])
    comment = _comment(client, ws["id"], entry["id"], bob["headers"], body="nice photo")

    _, data = _export(client, bob["headers"])
    # bob is neither author nor coauthor, so the entry itself is excluded...
    assert data["entries"] == []
    # ...but bob's own comment on it is still his data to export.
    assert len(data["comments"]) == 1
    assert data["comments"][0]["id"] == comment["id"]
    assert data["comments"][0]["body"] == "nice photo"
    assert data["comments"][0]["entry_id"] == entry["id"]


def test_export_excludes_others_comments_on_own_entry(client, make_user, make_workspace):
    """Someone else's comment on this user's entry is their data, not
    this user's - never included even though it's on the user's own
    entry."""
    alice = make_user("alice")
    bob = make_user("bob")
    ws = make_workspace(alice, bob)
    entry = _create_entry(client, ws["id"], alice["headers"])
    _comment(client, ws["id"], entry["id"], bob["headers"], body="bob's remark")
    own_comment = _comment(client, ws["id"], entry["id"], alice["headers"], body="alice's own reply")

    _, data = _export(client, alice["headers"])
    assert len(data["comments"]) == 1
    assert data["comments"][0]["id"] == own_comment["id"]
    assert data["comments"][0]["body"] == "alice's own reply"


def test_export_includes_actual_photo_bytes(client, make_user, make_workspace, db_session):
    alice = make_user("alice")
    ws = make_workspace(alice, name="Solo")
    photo_bytes = b"fake image bytes for export test"
    entry = _create_entry(
        client,
        ws["id"],
        alice["headers"],
        images=[("images", ("photo.png", photo_bytes, "image/png"))],
    )
    image_id = entry["images"][0]["id"]
    filename = db_session.get(EntryImage, image_id).filename

    archive, data = _export(client, alice["headers"])
    assert data["entries"][0]["photos"] == [filename]
    assert f"photos/{filename}" in archive.namelist()
    assert archive.read(f"photos/{filename}") == photo_bytes


def test_export_photo_fetch_failure_does_not_abort_export(client, make_user, make_workspace, db_session):
    """A missing/corrupted stored photo file shouldn't take down the
    whole export - the entry's JSON still lists the filename, the
    archive just skips that one file."""
    from pathlib import Path

    alice = make_user("alice")
    ws = make_workspace(alice, name="Solo")
    entry = _create_entry(
        client,
        ws["id"],
        alice["headers"],
        images=[("images", ("photo.png", b"bytes", "image/png"))],
    )
    image_id = entry["images"][0]["id"]
    filename = db_session.get(EntryImage, image_id).filename
    uploads_dir = Path(__file__).resolve().parent.parent / "uploads"
    (uploads_dir / filename).unlink()  # simulate a missing/corrupted file

    archive, data = _export(client, alice["headers"])
    assert data["entries"][0]["photos"] == [filename]  # still listed in the JSON
    assert f"photos/{filename}" not in archive.namelist()  # but not actually present


def test_export_multiple_entries_across_workspaces(client, make_user, make_workspace):
    alice = make_user("alice")
    ws1 = make_workspace(alice, name="Workspace One")
    ws2 = make_workspace(alice, name="Workspace Two")
    entry1 = _create_entry(client, ws1["id"], alice["headers"], playlist_id="p1")
    entry2 = _create_entry(client, ws2["id"], alice["headers"], playlist_id="p2")

    _, data = _export(client, alice["headers"])
    exported_ids = {e["id"] for e in data["entries"]}
    assert exported_ids == {entry1["id"], entry2["id"]}
    workspace_names = {e["workspace"]["name"] for e in data["entries"]}
    assert workspace_names == {"Workspace One", "Workspace Two"}


def test_export_does_not_include_deleted_users_data(client, make_user, make_workspace):
    """Sanity check that export is scoped strictly to the authenticated
    caller - alice's export never contains bob's entries or comments."""
    alice = make_user("alice")
    bob = make_user("bob")
    ws = make_workspace(alice, bob)
    _create_entry(client, ws["id"], bob["headers"], playlist_id="bobs")

    _, data = _export(client, alice["headers"])
    assert data["entries"] == []
    assert data["comments"] == []
