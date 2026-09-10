"""
What the MCP surface may not reach: the trash.

Soft delete is the whole reason there is no confirmation dialog in front of a
DELETE — a project carries years of notes, submissions and events, and the
answer to that is a mistake you can survive, not a question you are asked.
That promise is only worth something if a deleted project is deleted on every
surface. It was not: every tool in `mcp_app.py` filtered on the workspace and
nothing else, so a project invisible in the interface stayed readable and
writable from a chat client.

These tests read the surface, not the helper. `projects_in()` having the filter
is not the property that matters — the property is that no tool gets to that
row, which is what erodes the next time somebody writes a query by hand.
"""
import inspect

import mcp_app
from conftest import attempt, trash


def test_the_trash_is_invisible_to_every_read(caller):
    slug, pid = caller["slug"], caller["project"]

    listed = mcp_app.list_projects(slug)
    assert [p["id"] for p in listed["projects"]] == [pid]
    assert listed["count"] == 1
    assert mcp_app.get_project(slug, pid)["id"] == pid
    assert mcp_app.search_projects("thick", slug)["count"] == 1
    assert [w["projects"] for w in mcp_app.list_workspaces()["workspaces"]
            if w["slug"] == slug] == [1]

    trash(caller)

    listed = mcp_app.list_projects(slug)
    assert listed["projects"] == []
    assert listed["count"] == 0
    assert "error" in mcp_app.get_project(slug, pid)
    assert mcp_app.search_projects("thick", slug)["count"] == 0
    # The count on the workspace card too: a number that includes the trash is
    # a number that disagrees with the list underneath it.
    assert [w["projects"] for w in mcp_app.list_workspaces()["workspaces"]
            if w["slug"] == slug] == [0]


def test_the_trash_refuses_every_write(caller):
    slug, pid = caller["slug"], caller["project"]
    trash(caller)

    calls = [
        ("add_note", lambda: mcp_app.add_note(slug, pid, "a thought")),
        ("set_status", lambda: mcp_app.set_status(slug, pid, "published")),
        ("open_submission",
         lambda: mcp_app.open_submission(slug, pid, "Nature")),
        ("update_project",
         lambda: mcp_app.update_project(slug, pid, title="renamed")),
        ("add_author", lambda: mcp_app.add_author(slug, pid, "Someone")),
        ("add_link",
         lambda: mcp_app.add_link(slug, pid, "url", "https://example.org")),
        ("remove_author", lambda: mcp_app.remove_author(slug, pid, "Someone")),
        ("remove_link",
         lambda: mcp_app.remove_link(slug, pid, "https://example.org")),
    ]
    for name, call in calls:
        assert "error" in call(), name


def test_a_trashed_project_takes_its_submissions_with_it(caller):
    """The two submission-addressed tools do not name a project, so they were
    the easiest place for the rule to be missing."""
    slug = caller["slug"]
    sid = attempt(caller)

    assert "error" not in mcp_app.edit_submission(slug, sid,
                                                  venue="Journal of Bioethics")
    trash(caller)

    assert "error" in mcp_app.edit_submission(slug, sid, venue="Elsewhere")
    assert "error" in mcp_app.record_outcome(slug, sid, "desk_reject")


def test_no_tool_filters_the_workspace_by_hand(caller):
    """The rule this fix is really making: one place, not fifteen.

    Fails when somebody writes `Project.workspace_id == ws.id` into a new tool
    instead of going through the helper — which is exactly how the filter went
    missing the first time, and it costs nothing to keep watching for.
    """
    src = inspect.getsource(mcp_app)
    hand_written = [line.strip() for line in src.splitlines()
                    if "Project.workspace_id" in line
                    and "workspace_id=ws.id" not in line.replace(" ", "")]
    assert hand_written == [], hand_written
