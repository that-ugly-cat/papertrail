"""
Shared test setup.

`models.py` builds its SQLAlchemy engine and `auth.py` reads `JWT_SECRET` at
import time, so both have to be in place before anything imports the app —
hence a conftest and not a fixture. The database is a throwaway file rather
than `:memory:` because the app hands out its own sessions from
`SessionLocal`, and an in-memory SQLite is a different database per
connection.

`PUBLIC_URL` is here for the same reason it is in the `.env`: the MCP
transport validates the request's Host against it, and the test client calls
itself `testserver`.
"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ.setdefault(
    "DATABASE_URL",
    "sqlite:///" + (Path(tempfile.mkdtemp(prefix="papertrail-tests-"))
                    / "test.db").as_posix())
os.environ.setdefault("JWT_SECRET", "test-secret-not-used-anywhere-else")
os.environ.setdefault("PUBLIC_URL", "http://testserver")
os.environ.setdefault("AUTH_MODE", "local")
os.environ.setdefault("COOKIE_SECURE", "0")

import pytest  # noqa: E402

import auth  # noqa: E402
from models import (  # noqa: E402
    Membership, Project, SessionLocal, Submission, User, Workspace, init_db,
    utcnow,
)

init_db()

_seq = iter(range(1, 10_000))


@pytest.fixture
def world():
    """One user, one workspace they administer, one project in it.

    A fresh slug per test: the tables are shared for the whole run, and a test
    that depends on being alone in the database is a test that passes in
    isolation and fails in a suite.
    """
    n = next(_seq)
    db = SessionLocal()
    user = User(email=f"spit{n}@example.org", name=f"Tester {n}",
                hashed_password="x", is_active=True)
    ws = Workspace(slug=f"ws{n}", name=f"Workspace {n}")
    db.add_all([user, ws])
    db.flush()
    db.add(Membership(user_id=user.id, workspace_id=ws.id, role="admin"))
    p = Project(workspace_id=ws.id, title=f"Thick bioethics {n}",
                status="ready")
    db.add(p)
    db.commit()
    ids = {"user": user.id, "ws": ws.id, "slug": ws.slug, "project": p.id,
           "title": p.title}
    db.close()
    auth.set_caller(None)
    try:
        yield ids
    finally:
        auth.set_caller(None)


@pytest.fixture
def caller(world):
    """The MCP surface runs as a person; this is that person."""
    db = SessionLocal()
    try:
        auth.set_caller(db.get(User, world["user"]))
        yield world
    finally:
        db.close()


def attempt(world, venue="Journal of Bioethics", outcome="pending"):
    """An open submission on the fixture's project, and the project moved to
    match — the state the one-attempt-at-a-time rule exists to protect."""
    db = SessionLocal()
    try:
        p = db.get(Project, world["project"])
        s = Submission(project_id=p.id, venue=venue, attempt=1,
                       submitted_at=utcnow(), outcome=outcome)
        db.add(s)
        p.status = "under_review"
        db.commit()
        return s.id
    finally:
        db.close()


def trash(world):
    """Soft-delete the project, the way the web route does."""
    db = SessionLocal()
    try:
        db.get(Project, world["project"]).deleted_at = utcnow()
        db.commit()
    finally:
        db.close()


def state(world) -> dict:
    """The project as the database has it: status, and one row per attempt.

    Read back through a fresh session on purpose. A refusal that leaves the
    object dirty in somebody's identity map looks like a refusal that wrote
    nothing, right up until the next commit.
    """
    db = SessionLocal()
    try:
        p = db.get(Project, world["project"])
        return {"status": p.status,
                "attempts": [(s.venue, s.outcome, s.attempt)
                             for s in sorted(p.submissions,
                                             key=lambda s: s.id)]}
    finally:
        db.close()
