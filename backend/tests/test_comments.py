def _create_entry(client, workspace_id, headers, *, is_public=False, playlist_id="p1", coauthor_usernames=None):
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
    return res.json()["id"]


def _comment(client, workspace_id, entry_id, headers, body="hello", parent_comment_id=None):
    payload = {"body": body}
    if parent_comment_id is not None:
        payload["parent_comment_id"] = parent_comment_id
    return client.post(f"/api/workspaces/{workspace_id}/entries/{entry_id}/comments", headers=headers, json=payload)


# --- Create --------------------------------------------------------------


def test_create_comment_requires_auth(client, make_user, make_workspace):
    alice = make_user("alice")
    ws = make_workspace(alice)
    entry_id = _create_entry(client, ws["id"], alice["headers"], is_public=True)

    res = client.post(f"/api/workspaces/{ws['id']}/entries/{entry_id}/comments", json={"body": "hi"})
    assert res.status_code == 401


def test_create_top_level_comment(client, make_user, make_workspace):
    alice = make_user("alice")
    ws = make_workspace(alice)
    entry_id = _create_entry(client, ws["id"], alice["headers"], is_public=True)

    res = _comment(client, ws["id"], entry_id, alice["headers"], body="nice trip!")
    assert res.status_code == 201
    body = res.json()
    assert body["body"] == "nice trip!"
    assert body["parent_comment_id"] is None
    assert body["author_username"] == "alice"
    assert body["replies"] == []
    assert body["edited_at"] is None


def test_any_workspace_member_with_view_access_can_comment_on_public_entry(client, make_user, make_workspace):
    alice = make_user("alice")
    bob = make_user("bob")
    ws = make_workspace(alice, bob)
    entry_id = _create_entry(client, ws["id"], alice["headers"], is_public=True)

    res = _comment(client, ws["id"], entry_id, bob["headers"])
    assert res.status_code == 201


def test_cannot_comment_on_private_entry_without_access(client, make_user, make_workspace):
    alice = make_user("alice")
    bob = make_user("bob")
    ws = make_workspace(alice, bob)
    entry_id = _create_entry(client, ws["id"], alice["headers"], is_public=False)

    res = _comment(client, ws["id"], entry_id, bob["headers"])
    assert res.status_code == 404


def test_cannot_comment_when_not_a_workspace_member_at_all(client, make_user, make_workspace):
    alice = make_user("alice")
    outsider = make_user("outsider")
    ws = make_workspace(alice)
    entry_id = _create_entry(client, ws["id"], alice["headers"], is_public=True)

    res = _comment(client, ws["id"], entry_id, outsider["headers"])
    assert res.status_code == 404


def test_coauthor_can_comment_on_private_entry(client, make_user, make_workspace):
    alice = make_user("alice")
    bob = make_user("bob")
    ws = make_workspace(alice, bob)
    entry_id = _create_entry(client, ws["id"], alice["headers"], is_public=False, coauthor_usernames=["bob"])

    res = _comment(client, ws["id"], entry_id, bob["headers"])
    assert res.status_code == 201


def test_comment_on_nonexistent_entry_returns_404(client, make_user, make_workspace):
    alice = make_user("alice")
    ws = make_workspace(alice)
    res = _comment(client, ws["id"], 999999, alice["headers"])
    assert res.status_code == 404


def test_comment_body_cannot_be_empty(client, make_user, make_workspace):
    alice = make_user("alice")
    ws = make_workspace(alice)
    entry_id = _create_entry(client, ws["id"], alice["headers"], is_public=True)

    res = _comment(client, ws["id"], entry_id, alice["headers"], body="")
    assert res.status_code == 422


# --- Threading -------------------------------------------------------------


def test_reply_to_comment_is_threaded(client, make_user, make_workspace):
    alice = make_user("alice")
    ws = make_workspace(alice)
    entry_id = _create_entry(client, ws["id"], alice["headers"], is_public=True)
    top_id = _comment(client, ws["id"], entry_id, alice["headers"], body="top").json()["id"]

    reply_res = _comment(client, ws["id"], entry_id, alice["headers"], body="a reply", parent_comment_id=top_id)
    assert reply_res.status_code == 201
    assert reply_res.json()["parent_comment_id"] == top_id


def test_deeply_nested_replies_are_allowed(client, make_user, make_workspace):
    alice = make_user("alice")
    ws = make_workspace(alice)
    entry_id = _create_entry(client, ws["id"], alice["headers"], is_public=True)
    top_id = _comment(client, ws["id"], entry_id, alice["headers"], body="top").json()["id"]
    reply1_id = _comment(client, ws["id"], entry_id, alice["headers"], body="reply1", parent_comment_id=top_id).json()["id"]
    reply2_res = _comment(client, ws["id"], entry_id, alice["headers"], body="reply2", parent_comment_id=reply1_id)
    assert reply2_res.status_code == 201
    assert reply2_res.json()["parent_comment_id"] == reply1_id


def test_reply_with_parent_from_different_entry_rejected(client, make_user, make_workspace):
    alice = make_user("alice")
    ws = make_workspace(alice)
    entry1_id = _create_entry(client, ws["id"], alice["headers"], is_public=True, playlist_id="p1")
    entry2_id = _create_entry(client, ws["id"], alice["headers"], is_public=True, playlist_id="p2")
    top_id = _comment(client, ws["id"], entry1_id, alice["headers"], body="top").json()["id"]

    res = _comment(client, ws["id"], entry2_id, alice["headers"], body="reply", parent_comment_id=top_id)
    assert res.status_code == 422


def test_reply_with_nonexistent_parent_rejected(client, make_user, make_workspace):
    alice = make_user("alice")
    ws = make_workspace(alice)
    entry_id = _create_entry(client, ws["id"], alice["headers"], is_public=True)

    res = _comment(client, ws["id"], entry_id, alice["headers"], body="reply", parent_comment_id=999999)
    assert res.status_code == 422


def test_list_comments_nests_replies_under_parent_in_order(client, make_user, make_workspace):
    alice = make_user("alice")
    ws = make_workspace(alice)
    entry_id = _create_entry(client, ws["id"], alice["headers"], is_public=True)
    top1_id = _comment(client, ws["id"], entry_id, alice["headers"], body="first top-level").json()["id"]
    top2_id = _comment(client, ws["id"], entry_id, alice["headers"], body="second top-level").json()["id"]
    _comment(client, ws["id"], entry_id, alice["headers"], body="reply to first", parent_comment_id=top1_id)
    _comment(client, ws["id"], entry_id, alice["headers"], body="another reply to first", parent_comment_id=top1_id)

    res = client.get(f"/api/workspaces/{ws['id']}/entries/{entry_id}/comments", headers=alice["headers"])
    assert res.status_code == 200
    thread = res.json()

    assert [c["id"] for c in thread] == [top1_id, top2_id]
    assert [r["body"] for r in thread[0]["replies"]] == ["reply to first", "another reply to first"]
    assert thread[1]["replies"] == []


def test_list_comments_of_private_workspace_anonymous_returns_404(client, make_user, make_workspace):
    """Workspaces default to private - an anonymous caller gets 404 (not
    401), the same non-disclosure treatment used everywhere else. See
    test_workspaces_visibility.py for the public-workspace case, where
    this succeeds with no token at all."""
    alice = make_user("alice")
    ws = make_workspace(alice)
    entry_id = _create_entry(client, ws["id"], alice["headers"], is_public=True)
    _comment(client, ws["id"], entry_id, alice["headers"], body="hi")

    res = client.get(f"/api/workspaces/{ws['id']}/entries/{entry_id}/comments")
    assert res.status_code == 404


def test_list_comments_on_private_entry_requires_access(client, make_user, make_workspace):
    alice = make_user("alice")
    bob = make_user("bob")
    ws = make_workspace(alice, bob)
    entry_id = _create_entry(client, ws["id"], alice["headers"], is_public=False)
    _comment(client, ws["id"], entry_id, alice["headers"], body="secret note")

    res = client.get(f"/api/workspaces/{ws['id']}/entries/{entry_id}/comments", headers=bob["headers"])
    assert res.status_code == 404


def test_list_comments_not_a_workspace_member_returns_404(client, make_user, make_workspace):
    alice = make_user("alice")
    outsider = make_user("outsider")
    ws = make_workspace(alice)
    entry_id = _create_entry(client, ws["id"], alice["headers"], is_public=True)
    _comment(client, ws["id"], entry_id, alice["headers"], body="hi")

    res = client.get(f"/api/workspaces/{ws['id']}/entries/{entry_id}/comments", headers=outsider["headers"])
    assert res.status_code == 404


def test_list_comments_coauthor_can_read_private_entry_thread(client, make_user, make_workspace):
    alice = make_user("alice")
    bob = make_user("bob")
    ws = make_workspace(alice, bob)
    entry_id = _create_entry(client, ws["id"], alice["headers"], is_public=False, coauthor_usernames=["bob"])
    _comment(client, ws["id"], entry_id, alice["headers"], body="hi bob")

    res = client.get(f"/api/workspaces/{ws['id']}/entries/{entry_id}/comments", headers=bob["headers"])
    assert res.status_code == 200
    assert len(res.json()) == 1


# --- Edit --------------------------------------------------------------


def test_author_can_edit_own_comment(client, make_user, make_workspace):
    alice = make_user("alice")
    ws = make_workspace(alice)
    entry_id = _create_entry(client, ws["id"], alice["headers"], is_public=True)
    comment_id = _comment(client, ws["id"], entry_id, alice["headers"], body="original").json()["id"]

    res = client.patch(f"/api/comments/{comment_id}", headers=alice["headers"], json={"body": "edited"})
    assert res.status_code == 200
    body = res.json()
    assert body["body"] == "edited"
    assert body["edited_at"] is not None


def test_non_author_cannot_edit_comment(client, make_user, make_workspace):
    alice = make_user("alice")
    bob = make_user("bob")
    ws = make_workspace(alice, bob)
    entry_id = _create_entry(client, ws["id"], alice["headers"], is_public=True)
    comment_id = _comment(client, ws["id"], entry_id, alice["headers"], body="original").json()["id"]

    res = client.patch(f"/api/comments/{comment_id}", headers=bob["headers"], json={"body": "hacked"})
    assert res.status_code == 403


def test_entry_primary_author_cannot_edit_someone_elses_comment(client, make_user, make_workspace):
    """Moderation only extends to delete, not edit - editing is always the
    comment author's own privilege, even for the entry's primary author."""
    alice = make_user("alice")
    bob = make_user("bob")
    ws = make_workspace(alice, bob)
    entry_id = _create_entry(client, ws["id"], alice["headers"], is_public=True)
    comment_id = _comment(client, ws["id"], entry_id, bob["headers"], body="bob's comment").json()["id"]

    res = client.patch(f"/api/comments/{comment_id}", headers=alice["headers"], json={"body": "hacked"})
    assert res.status_code == 403


def test_edit_requires_auth(client, make_user, make_workspace):
    alice = make_user("alice")
    ws = make_workspace(alice)
    entry_id = _create_entry(client, ws["id"], alice["headers"], is_public=True)
    comment_id = _comment(client, ws["id"], entry_id, alice["headers"], body="original").json()["id"]

    res = client.patch(f"/api/comments/{comment_id}", json={"body": "edited"})
    assert res.status_code == 401


def test_edit_nonexistent_comment_returns_404(client, make_user):
    alice = make_user("alice")
    res = client.patch("/api/comments/999999", headers=alice["headers"], json={"body": "x"})
    assert res.status_code == 404


def test_edit_comment_in_workspace_caller_is_not_a_member_of_returns_404(client, make_user, make_workspace):
    """The comment/entry both exist and alice is a real logged-in user, but
    she isn't a member of the workspace the comment lives in - same
    non-disclosure 404 as any other cross-workspace lookup."""
    alice = make_user("alice")
    outsider = make_user("outsider")
    ws = make_workspace(alice)
    entry_id = _create_entry(client, ws["id"], alice["headers"], is_public=True)
    comment_id = _comment(client, ws["id"], entry_id, alice["headers"], body="original").json()["id"]

    res = client.patch(f"/api/comments/{comment_id}", headers=outsider["headers"], json={"body": "x"})
    assert res.status_code == 404


# --- Delete permission matrix ---------------------------------------------


def test_comment_author_can_delete_own_comment(client, make_user, make_workspace):
    alice = make_user("alice")
    bob = make_user("bob")
    ws = make_workspace(alice, bob)
    entry_id = _create_entry(client, ws["id"], alice["headers"], is_public=True)
    comment_id = _comment(client, ws["id"], entry_id, bob["headers"], body="bob's comment").json()["id"]

    res = client.delete(f"/api/comments/{comment_id}", headers=bob["headers"])
    assert res.status_code == 204


def test_entry_primary_author_can_delete_others_comment(client, make_user, make_workspace):
    alice = make_user("alice")
    bob = make_user("bob")
    ws = make_workspace(alice, bob)
    entry_id = _create_entry(client, ws["id"], alice["headers"], is_public=True)
    comment_id = _comment(client, ws["id"], entry_id, bob["headers"], body="bob's comment").json()["id"]

    res = client.delete(f"/api/comments/{comment_id}", headers=alice["headers"])
    assert res.status_code == 204


def test_coauthor_cannot_delete_someone_elses_comment(client, make_user, make_workspace):
    """Co-authors get the same commenting rights as anyone with view access,
    but not the primary author's moderation power."""
    alice = make_user("alice")
    bob = make_user("bob")
    carol = make_user("carol")
    ws = make_workspace(alice, bob, carol)
    entry_id = _create_entry(client, ws["id"], alice["headers"], is_public=True, coauthor_usernames=["bob"])
    comment_id = _comment(client, ws["id"], entry_id, carol["headers"], body="carol's comment").json()["id"]

    res = client.delete(f"/api/comments/{comment_id}", headers=bob["headers"])
    assert res.status_code == 403


def test_unrelated_user_cannot_delete_comment(client, make_user, make_workspace):
    alice = make_user("alice")
    bob = make_user("bob")
    carol = make_user("carol")
    ws = make_workspace(alice, bob, carol)
    entry_id = _create_entry(client, ws["id"], alice["headers"], is_public=True)
    comment_id = _comment(client, ws["id"], entry_id, bob["headers"], body="bob's comment").json()["id"]

    res = client.delete(f"/api/comments/{comment_id}", headers=carol["headers"])
    assert res.status_code == 403


def test_delete_requires_auth(client, make_user, make_workspace):
    alice = make_user("alice")
    ws = make_workspace(alice)
    entry_id = _create_entry(client, ws["id"], alice["headers"], is_public=True)
    comment_id = _comment(client, ws["id"], entry_id, alice["headers"], body="hi").json()["id"]

    res = client.delete(f"/api/comments/{comment_id}")
    assert res.status_code == 401


def test_delete_nonexistent_comment_returns_404(client, make_user):
    alice = make_user("alice")
    res = client.delete("/api/comments/999999", headers=alice["headers"])
    assert res.status_code == 404


def test_delete_comment_in_workspace_caller_is_not_a_member_of_returns_404(client, make_user, make_workspace):
    alice = make_user("alice")
    outsider = make_user("outsider")
    ws = make_workspace(alice)
    entry_id = _create_entry(client, ws["id"], alice["headers"], is_public=True)
    comment_id = _comment(client, ws["id"], entry_id, alice["headers"], body="hi").json()["id"]

    res = client.delete(f"/api/comments/{comment_id}", headers=outsider["headers"])
    assert res.status_code == 404


def test_deleting_comment_deletes_its_replies(client, make_user, make_workspace):
    alice = make_user("alice")
    ws = make_workspace(alice)
    entry_id = _create_entry(client, ws["id"], alice["headers"], is_public=True)
    top_id = _comment(client, ws["id"], entry_id, alice["headers"], body="top").json()["id"]
    reply_id = _comment(client, ws["id"], entry_id, alice["headers"], body="reply", parent_comment_id=top_id).json()["id"]

    res = client.delete(f"/api/comments/{top_id}", headers=alice["headers"])
    assert res.status_code == 204

    # The reply is gone too, not orphaned - editing it now 404s.
    res = client.patch(f"/api/comments/{reply_id}", headers=alice["headers"], json={"body": "x"})
    assert res.status_code == 404


def test_deleting_entry_deletes_its_comments(client, make_user, make_workspace):
    alice = make_user("alice")
    ws = make_workspace(alice)
    entry_id = _create_entry(client, ws["id"], alice["headers"], is_public=True)
    comment_id = _comment(client, ws["id"], entry_id, alice["headers"], body="hi").json()["id"]

    res = client.delete(f"/api/workspaces/{ws['id']}/entries/{entry_id}", headers=alice["headers"])
    assert res.status_code == 204

    res = client.patch(f"/api/comments/{comment_id}", headers=alice["headers"], json={"body": "x"})
    assert res.status_code == 404
