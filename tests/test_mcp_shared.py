"""A project shared into a workspace is reachable from it, over MCP as on the board.

The surface used to answer on its home workspace only, which made it *narrower*
than the person holding the key — while `mcp_app`'s own instructions promise the
reach of its owner — and it failed in the worst way available: `get_project`
answered `No project 5 in 'ite'`, byte-identical to the answer for a project
that does not exist. A model reading that concludes the paper is not tracked,
which is the miss-is-not-absence trap the SPEC already warns about for search.

What does *not* widen is authorisation. Every tool still asks for the role on
the workspace it was given, so a reader on the sharing workspace still only
reads. That is the web's rule seen from the other side: a shared paper is one
object, and whoever can edit it somewhere can edit it.
"""
import mcp_app
from models import Membership, Project, ProjectWorkspace, SessionLocal, Workspace

from conftest import _seq


def shared_into(world, role="write"):
    """A second workspace the caller belongs to, with `world`'s project shared in.

    The project stays homed where it was: this is the interdepartmental paper,
    one row reachable from two boards.
    """
    n = next(_seq)
    db = SessionLocal()
    try:
        other = Workspace(slug=f"shared{n}", name=f"Sharing workspace {n}")
        db.add(other)
        db.flush()
        db.add(Membership(user_id=world["user"], workspace_id=other.id, role=role))
        db.add(ProjectWorkspace(project_id=world["project"], workspace_id=other.id))
        db.commit()
        return other.slug
    finally:
        db.close()


def test_a_shared_project_is_found_from_the_sharing_workspace(caller):
    slug = shared_into(caller)

    got = mcp_app.get_project(workspace=slug, project_id=caller["project"])
    assert "error" not in got, got
    assert got["title"] == caller["title"]

    listed = mcp_app.list_projects(workspace=slug)
    assert caller["project"] in [p["id"] for p in listed["projects"]], listed

    # search_projects walks every workspace the caller can reach and returns
    # `results`, each stamped with the workspace it was found through.
    found = mcp_app.search_projects(query="Thick bioethics")
    hits = [(h["id"], h["workspace"]) for h in found["results"]]
    assert (caller["project"], slug) in hits, hits


def test_a_shared_project_can_be_written_where_the_caller_may_write(caller):
    slug = shared_into(caller, role="write")

    out = mcp_app.set_status(workspace=slug, project_id=caller["project"],
                             status="writing")
    assert out.get("ok"), out

    db = SessionLocal()
    try:
        assert db.get(Project, caller["project"]).status == "writing"
    finally:
        db.close()


def test_reading_it_through_a_workspace_where_you_only_read_stays_a_read(caller):
    slug = shared_into(caller, role="read")

    got = mcp_app.get_project(workspace=slug, project_id=caller["project"])
    assert "error" not in got, got

    refused = mcp_app.set_status(workspace=slug, project_id=caller["project"],
                                status="published")
    assert "error" in refused, refused

    db = SessionLocal()
    try:
        assert db.get(Project, caller["project"]).status != "published"
    finally:
        db.close()
