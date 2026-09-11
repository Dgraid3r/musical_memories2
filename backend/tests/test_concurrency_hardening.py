"""Real-concurrency regression tests for the three gaps found by the
concurrency audit - each test actually triggers the race (not just the
sequential happy path) and asserts the fixed behavior.

Two different techniques are used, matched to what each fix actually
guarantees:

- Tests 1 and 2 (the IntegrityError-catch-and-retry fixes) need both
  racing requests to have already passed their "does this exist yet"
  check before either commits - deterministically forced by patching the
  model's __init__ (the exact point right after the check, right before
  the insert) to block on a threading.Barrier until every racing thread
  has arrived. Neither side can possibly see the other's row yet by
  construction, so this isn't a timing gamble.

- Test 3 (the SELECT ... FOR UPDATE fix) needs to prove the lock itself
  is what serializes the two requests, not scheduling luck - forced by
  delaying the first concurrent commit long enough that the second
  request's own locked SELECT has genuinely arrived at Postgres and is
  blocked waiting on it, the same "prove the mechanism, don't just hope
  the timing lines up" reasoning.
"""

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

from app.database import SessionLocal
from app.email import last_email_to
from app.models import Tag, WorkspaceMembership


def _create_entry(client, workspace_id, headers, *, playlist_id="p1"):
    res = client.post(
        f"/api/workspaces/{workspace_id}/entries",
        headers=headers,
        data={
            "start_date": "2026-01-01",
            "playlist_id": playlist_id,
            "playlist_name": "Test",
            "playlist_url": f"https://open.spotify.com/playlist/{playlist_id}",
            "is_public": "true",
        },
    )
    assert res.status_code == 201, res.text
    return res.json()["id"]


# --- 1. accept_invite: two near-simultaneous accepts of the same invite ----


def test_concurrent_accept_invite_race_returns_clean_409_not_500(client, make_user, make_workspace):
    alice = make_user("alice")
    bob = make_user("bob")
    ws = make_workspace(alice)

    invite_res = client.post(
        f"/api/workspaces/{ws['id']}/invites", headers=alice["headers"], json={"email": bob["email"]}
    )
    assert invite_res.status_code == 201
    token = last_email_to(bob["email"])["token"]

    worker_count = 2
    barrier = threading.Barrier(worker_count)
    real_init = WorkspaceMembership.__init__

    def barriered_init(self, *args, **kwargs):
        # Reached only after this thread's own "already a member?" check
        # already returned "no" - by the time any thread gets here,
        # every racing thread must have passed that same check too
        # (nothing before this point could have committed a row for the
        # others to see), so releasing the barrier guarantees a genuine
        # race on the insert below, not a lucky/unlucky ordering.
        barrier.wait(timeout=5)
        real_init(self, *args, **kwargs)

    results: list[int] = []
    results_lock = threading.Lock()

    def do_accept(_i: int) -> None:
        res = client.post(f"/api/invites/{token}/accept", headers=bob["headers"])
        with results_lock:
            results.append(res.status_code)

    with patch.object(WorkspaceMembership, "__init__", barriered_init):
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            list(executor.map(do_accept, range(worker_count)))

    assert 500 not in results, results
    assert results.count(200) == 1, results
    assert results.count(409) == worker_count - 1, results

    db = SessionLocal()
    try:
        memberships = db.scalars(
            select(WorkspaceMembership).where(
                WorkspaceMembership.workspace_id == ws["id"], WorkspaceMembership.user_id == bob["id"]
            )
        ).all()
        assert len(memberships) == 1
    finally:
        db.close()


# --- 2. _resolve_tags: two concurrent entries introducing the same tag -----


def test_concurrent_new_tag_creation_does_not_error_or_duplicate(client, make_user, make_workspace):
    alice = make_user("alice")
    ws = make_workspace(alice)

    # Two distinct entries so the only contention is the tag race itself -
    # not two requests mutating the same entry row.
    entry_ids = [_create_entry(client, ws["id"], alice["headers"], playlist_id=f"p{i}") for i in range(2)]

    worker_count = 2
    barrier = threading.Barrier(worker_count)
    real_init = Tag.__init__

    def barriered_init(self, *args, **kwargs):
        # Same reasoning as accept_invite's barrier above: reached only
        # after this thread's own "does this tag already exist?" select
        # already came back empty.
        barrier.wait(timeout=5)
        real_init(self, *args, **kwargs)

    results = []
    results_lock = threading.Lock()

    def add_tag(entry_id: int) -> None:
        res = client.patch(
            f"/api/workspaces/{ws['id']}/entries/{entry_id}",
            headers=alice["headers"],
            json={"tags": ["brandnewtag"]},
        )
        with results_lock:
            results.append(res)

    with patch.object(Tag, "__init__", barriered_init):
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            list(executor.map(add_tag, entry_ids))

    # The race must resolve silently - both requests succeed, neither
    # surfaces an error to the caller.
    assert all(r.status_code == 200 for r in results), [(r.status_code, r.text) for r in results]
    for r in results:
        assert [t["name"] for t in r.json()["tags"]] == ["brandnewtag"]

    db = SessionLocal()
    try:
        tags = db.scalars(select(Tag).where(Tag.workspace_id == ws["id"], Tag.name == "brandnewtag")).all()
        assert len(tags) == 1
    finally:
        db.close()


def test_concurrent_new_tag_creation_both_entries_reference_the_same_tag_row(client, make_user, make_workspace):
    """Not just "no duplicate row" - both racing requests must actually
    end up referencing the *same* tag id, proving the loser really did
    re-fetch and use the winner's tag rather than something coincidental."""
    alice = make_user("alice")
    ws = make_workspace(alice)
    entry_ids = [_create_entry(client, ws["id"], alice["headers"], playlist_id=f"q{i}") for i in range(2)]

    worker_count = 2
    barrier = threading.Barrier(worker_count)
    real_init = Tag.__init__

    def barriered_init(self, *args, **kwargs):
        barrier.wait(timeout=5)
        real_init(self, *args, **kwargs)

    results = []
    results_lock = threading.Lock()

    def add_tag(entry_id: int) -> None:
        res = client.patch(
            f"/api/workspaces/{ws['id']}/entries/{entry_id}",
            headers=alice["headers"],
            json={"tags": ["sharedtag"]},
        )
        with results_lock:
            results.append(res)

    with patch.object(Tag, "__init__", barriered_init):
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            list(executor.map(add_tag, entry_ids))

    assert all(r.status_code == 200 for r in results), [(r.status_code, r.text) for r in results]
    tag_ids = {r.json()["tags"][0]["id"] for r in results}
    assert len(tag_ids) == 1


# --- 3. transfer_ownership: two near-simultaneous transfers -----------------


def test_concurrent_transfer_ownership_never_leaves_two_owners(client, make_user, make_workspace):
    alice = make_user("alice")
    bob = make_user("bob")
    carol = make_user("carol")
    ws = make_workspace(alice, bob, carol)  # alice is sole owner

    worker_count = 2
    barrier = threading.Barrier(worker_count)
    real_commit = OrmSession.commit
    delay_state = {"delayed": False}
    delay_lock = threading.Lock()

    def delayed_commit(self, *args, **kwargs):
        should_delay = False
        with delay_lock:
            if not delay_state["delayed"]:
                delay_state["delayed"] = True
                should_delay = True
        if should_delay:
            # Whichever of the two requests reaches its commit first is
            # already holding the row lock at this point (it acquired it
            # via SELECT ... FOR UPDATE before ever reaching commit) -
            # pausing here, still holding that lock, gives the other
            # concurrent request's own locked SELECT time to actually
            # arrive at Postgres and genuinely block on it. This is what
            # proves the lock is doing real serialization work, rather
            # than the test just getting lucky with thread scheduling.
            time.sleep(0.4)
        return real_commit(self, *args, **kwargs)

    results = []
    results_lock = threading.Lock()

    def do_transfer(target_id: int) -> None:
        barrier.wait(timeout=5)
        res = client.patch(
            f"/api/workspaces/{ws['id']}/transfer-ownership",
            headers=alice["headers"],
            json={"new_owner_user_id": target_id},
        )
        with results_lock:
            results.append(res)

    with patch.object(OrmSession, "commit", delayed_commit):
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            list(executor.map(do_transfer, [bob["id"], carol["id"]]))

    statuses = [r.status_code for r in results]
    assert 500 not in statuses, statuses
    assert statuses.count(200) == 1, statuses
    # The loser is rejected specifically because it's no longer the
    # owner by the time its (unblocked) locked read completes - not some
    # unrelated error.
    losers = [r.status_code for r in results if r.status_code != 200]
    assert losers == [403], statuses

    db = SessionLocal()
    try:
        owners = db.scalars(
            select(WorkspaceMembership).where(
                WorkspaceMembership.workspace_id == ws["id"], WorkspaceMembership.role == "owner"
            )
        ).all()
        assert len(owners) == 1
        # And alice herself ends up a plain member either way - never
        # left as a second owner alongside whichever target won.
        alice_role = db.scalar(
            select(WorkspaceMembership.role).where(
                WorkspaceMembership.workspace_id == ws["id"], WorkspaceMembership.user_id == alice["id"]
            )
        )
        assert alice_role == "member"
    finally:
        db.close()
