"""The attempt number is max + 1, on the drag path too.

`open_sub()` and the MCP `open_submission()` both compute it as
`max(attempt) + 1`, with the reason written next to each: counting the rows
repeats a number the first time an attempt is removed or an import leaves a gap
in the sequence. `move_project()` was the third copy and the one still counting
rows, which is how a category the SPEC records as fixed survived on one surface.

A duplicate attempt number is not cosmetic here: the number is what a person
reads to say which round of review a letter belongs to, and two rows called
attempt 2 make the history of a paper unreadable in exactly the place where it
matters — a resubmission after a rejection.
"""
from fastapi.testclient import TestClient

import main
from auth import create_token
from conftest import state
from models import Project, SessionLocal, Submission, utcnow


def board(world) -> TestClient:
    client = TestClient(main.app)
    client.cookies.set("session", create_token(world["user"]))
    return client


def gapped_history(world) -> None:
    """Two closed attempts numbered 1 and 3, as a removal or an import leaves them.

    Nothing is open, so the drag lands on the branch that opens a new one.
    """
    db = SessionLocal()
    try:
        p = db.get(Project, world["project"])
        for n, venue in ((1, "Journal of Bioethics"), (3, "BMC Medical Ethics")):
            db.add(Submission(project_id=p.id, venue=venue, attempt=n,
                              submitted_at=utcnow(), outcome="rejected"))
        p.status = "rejected"
        db.commit()
    finally:
        db.close()


def test_a_drag_after_a_gap_does_not_repeat_an_attempt_number(world):
    gapped_history(world)
    client = board(world)

    r = client.post(
        f"/api/w/{world['slug']}/move",
        json=dict(project_id=world["project"], status="submitted",
                  order=[world["project"]], venue="Bioethics"),
    )
    assert r.status_code == 200, r.text

    numbers = [n for _, _, n in state(world)["attempts"]]
    assert len(numbers) == len(set(numbers)), f"duplicate attempt number: {numbers}"
    assert max(numbers) == 4, f"expected the new attempt to be 4, got {numbers}"
