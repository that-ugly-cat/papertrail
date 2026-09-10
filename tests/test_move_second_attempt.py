"""
One open attempt at a time, on the drag-and-drop path as well.

Two `pending` rows on one project is not a cosmetic problem: `open_submission()`
returns the most recent, so the older one becomes unreachable and sits there for
ever, and every outcome recorded afterwards lands on the wrong attempt. Both
`open_sub()` and the MCP `open_submission()` refuse it. `move_project()` did
not — dragging a card into `submitted` while an attempt was open, naming a
different venue, fell past the resubmission branch and opened a second row.

The companion test matters as much as the refusal: the resubmission case has to
keep working, or the guard has fixed a rare bug by breaking the common path.
"""
from fastapi.testclient import TestClient

import main
from auth import create_token
from conftest import attempt, state


def board(world) -> TestClient:
    client = TestClient(main.app)
    client.cookies.set("session", create_token(world["user"]))
    return client


def move(client, world, status, **extra):
    return client.post(
        f"/api/w/{world['slug']}/move",
        json=dict(project_id=world["project"], status=status,
                  order=[world["project"]], **extra))


def test_a_move_that_would_open_a_second_attempt_is_refused(world):
    attempt(world, venue="Journal of Bioethics")
    client = board(world)

    # Out of the venue and back in at a different one, in one drag. This is the
    # move that used to open attempt 2 beside a still-pending attempt 1.
    move(client, world, "in_revision", outcome="major_revision")
    r = move(client, world, "submitted", venue="Bioethics")

    assert r.status_code == 400
    assert "Already out at Journal of Bioethics" in r.json()["detail"]
    # The reason is in `detail`, which is what the board reads to say why: a
    # card that springs back in silence reads as a broken board, not as a rule.
    assert "Record that outcome" in r.json()["detail"]

    # And nothing was written. The guard runs before the status change, so a
    # refusal is not relying on the session being rolled back for it.
    after = state(world)
    assert after["attempts"] == [("Journal of Bioethics", "pending", 1)]
    assert after["status"] == "in_revision"


def test_the_same_venue_still_reopens_the_same_attempt(world):
    """A resubmission after a revision is the same manuscript going back to the
    same editor, and the guard must not mistake it for a second attempt."""
    attempt(world, venue="Journal of Bioethics")
    client = board(world)

    move(client, world, "in_revision", outcome="major_revision")
    r = move(client, world, "submitted", venue="Journal of Bioethics")

    assert r.status_code == 200
    after = state(world)
    assert after["attempts"] == [("Journal of Bioethics", "pending", 1)]
    assert after["status"] == "submitted"


def test_a_first_attempt_still_opens(world):
    """Nothing open, a venue named: the ordinary case, unrefused."""
    client = board(world)

    r = move(client, world, "submitted", venue="Bioethics")

    assert r.status_code == 200
    assert state(world)["attempts"] == [("Bioethics", "pending", 1)]
