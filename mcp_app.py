"""
The model-facing surface of PaperTrail.

This is the point of the whole tool. A tracker you have to remember to open is a
tracker that goes stale; one that can be read and written from inside the
conversation where the work is happening is one that stays true. So: ask what is
stuck, add a note, move a status, open a submission, without leaving the chat.

Access. Every call runs as the human who owns the API key, and every workspace
lookup goes through auth.mcp_workspace(), which is the same role_for() the web
app uses. The MCP surface therefore has exactly the reach of its owner, no more.
A workspace the caller is not a member of reports "not found" rather than
"forbidden", so the model cannot enumerate what it cannot see.

Errors are returned as {"error": ...} rather than raised: a tool that throws
gives the model a stack trace to hallucinate around, while a message it can read
lets it correct course.
"""
import json
from datetime import datetime

from mcp.server.mcpserver import MCPServer

import auth
from models import (
    KEEPS_ATTEMPT_OPEN, LINK_KINDS, OUTCOME_LABELS, STATUSES, SUBMISSION_OUTCOMES, Authorship, Link,
    Note, Project, SessionLocal, Submission, apply_outcome, effective_status,
    flag_of,
    OUTPUT_TYPES, get_or_create_person, is_dormant, known_people, known_venues,
    last_event_at, log_event, snap, user_workspaces, utcnow, visible_links,
)
# Aliased: the tool below is also called open_submission, and the model-facing
# name is the one that must stay readable.
from models import open_submission as _open_attempt  # noqa: E402

mcp = MCPServer(
    name="papertrail",
    instructions=(
        "Research project tracking, from idea to published paper. "
        "Use list_workspaces first to see what you can reach. Reads are cheap; "
        "before writing anything, confirm with the user. Note that "
        "search_projects is lexical, not semantic: absence of a hit is not "
        "evidence that nothing relevant exists."
    ),
)


def _fail(msg: str) -> dict:
    return {"error": msg}


def _project_brief(p: Project, ws) -> dict:
    eff = effective_status(p)
    # The caller's own dot, never anyone else's: flags are per user, and the
    # key the model is holding names exactly one of them.
    flag = flag_of(p, auth.current_caller())
    return {
        "flagged": flag is not None,
        "flag_note": flag.note if flag else None,
        "id": p.id,
        "title": p.final_title or p.title,
        "status": p.status,
        "effective_status": eff["label"],
        "detail": eff["detail"],
        "status_mismatch": eff["diverges"],
        "authors": [a.person.name for a in p.authorships],
        "journal": p.journal,
        "type": p.output_type or "paper",
        "year": p.pub_year,
        "doi": p.doi,
        "notes": len(p.notes),
        "dormant": is_dormant(p, ws.dormant_after_days),
        "last_activity": (last_event_at(p) or p.created_at).strftime("%Y-%m-%d"),
        "url": f"/w/{ws.slug}/p/{p.id}",
    }


@mcp.tool()
def list_workspaces() -> dict:
    """Workspaces the caller can reach, with their role in each."""
    db = SessionLocal()
    try:
        user = auth.current_caller()
        return {"you": user.name, "workspaces": [
            {"slug": ws.slug, "name": ws.name, "role": role,
             "projects": len(ws.projects)}
            for ws, role in user_workspaces(db, user)]}
    except PermissionError as e:
        return _fail(str(e))
    finally:
        db.close()


@mcp.tool()
def list_projects(workspace: str, status: str = "", author: str = "",
                  stale_days: int = 0, flagged: bool = False,
                  limit: int = 50) -> dict:
    """
    Projects in a workspace, newest activity first.

    status: one of idea, developed, active, writing, ready, submitted,
            under_review, in_revision, published, archived. Empty means any.
            `submitted` is on an editor's desk, `under_review` is with the
            reviewers — same attempt, same clock, different kind of waiting.
    author: substring of a person's name.
    stale_days: only projects with no event for at least this many days. This is
            the question the old Notion board could not answer at all.
    flagged: only the ones the caller marked as needing their attention. The
            flag is private to whoever set it — this reads the key-holder's
            own dots and nobody else's, and it is set from the web app.
    """
    db = SessionLocal()
    try:
        ws, _role = auth.mcp_workspace(db, workspace)
        rows = db.query(Project).filter(Project.workspace_id == ws.id).all()
        if status:
            if status not in STATUSES:
                return _fail(f"Unknown status '{status}'. One of: {STATUSES}")
            rows = [p for p in rows if p.status == status]
        if author:
            needle = author.lower()
            rows = [p for p in rows
                    if any(needle in a.person.name.lower() for a in p.authorships)]
        if stale_days:
            rows = [p for p in rows
                    if (utcnow() - (last_event_at(p) or p.created_at)).days >= stale_days]
        if flagged:
            me = auth.current_caller()
            rows = [p for p in rows if flag_of(p, me) is not None]
        rows.sort(key=lambda p: last_event_at(p) or p.created_at, reverse=True)
        return {"workspace": ws.slug, "count": len(rows),
                "projects": [_project_brief(p, ws) for p in rows[:limit]]}
    except (LookupError, PermissionError) as e:
        return _fail(str(e))
    finally:
        db.close()


@mcp.tool()
def get_project(workspace: str, project_id: int) -> dict:
    """One project in full: fields, authors, submissions, links, notes, history."""
    db = SessionLocal()
    try:
        ws, _role = auth.mcp_workspace(db, workspace)
        p = (db.query(Project)
               .filter(Project.id == project_id,
                       Project.workspace_id == ws.id).first())
        if not p:
            return _fail(f"No project {project_id} in '{workspace}'")
        out = _project_brief(p, ws)
        out["summary"] = p.summary
        out["submissions"] = [
            {"id": s.id, "venue": s.venue, "attempt": s.attempt,
             "submitted_at": s.submitted_at.strftime("%Y-%m-%d") if s.submitted_at else None,
             "outcome": s.outcome, "outcome_label": OUTCOME_LABELS.get(s.outcome),
             "days_open": s.days_open}
            for s in sorted(p.submissions, key=lambda s: s.submitted_at or utcnow())]
        # Same filter as the web page, from the same function: a private link
        # hidden on the page and served here would be worse than not having the
        # feature at all.
        out["links"] = [{"kind": l.kind, "target": l.target, "label": l.label,
                         "private": l.user_id is not None}
                        for l in visible_links(p, auth.current_caller())]
        out["notes"] = [
            {"date": n.ts.strftime("%Y-%m-%d"),
             "author": n.author_label or (n.user.name if n.user else None),
             "body": n.body_md}
            for n in sorted(p.notes, key=lambda n: n.ts or utcnow())]
        out["history"] = [
            {"date": e.ts.strftime("%Y-%m-%d"), "type": e.type,
             "from": e.from_status, "to": e.to_status}
            for e in sorted(p.events, key=lambda e: e.ts or utcnow())]
        return out
    except (LookupError, PermissionError) as e:
        return _fail(str(e))
    finally:
        db.close()


@mcp.tool()
def search_projects(query: str, workspace: str = "", limit: int = 30) -> dict:
    """
    Lexical search over title, summary and notes across the caller's workspaces.

    Substring matching, not semantic: a query that shares no words with a
    project will not find it even when they are about the same thing. Semantic
    search over the dormant ideas is a later phase. Treat a miss as "not found
    by these words", never as "does not exist".
    """
    db = SessionLocal()
    try:
        user = auth.current_caller()
        scopes = [(ws, r) for ws, r in user_workspaces(db, user)
                  if not workspace or ws.slug == workspace]
        if workspace and not scopes:
            return _fail(f"No workspace '{workspace}'")
        needle = query.lower().strip()
        if not needle:
            return _fail("Empty query")
        hits = []
        for ws, _role in scopes:
            for p in ws.projects:
                where = []
                if needle in (p.title or "").lower() \
                        or needle in (p.final_title or "").lower():
                    where.append("title")
                if needle in (p.summary or "").lower():
                    where.append("summary")
                if any(needle in (n.body_md or "").lower() for n in p.notes):
                    where.append("notes")
                if where:
                    brief = _project_brief(p, ws)
                    brief["workspace"] = ws.slug
                    brief["matched_in"] = where
                    hits.append(brief)
        hits.sort(key=lambda h: h["last_activity"], reverse=True)
        return {"query": query, "count": len(hits), "results": hits[:limit],
                "caveat": "lexical match only"}
    except (LookupError, PermissionError) as e:
        return _fail(str(e))
    finally:
        db.close()


@mcp.tool()
def vocabularies(workspace: str) -> dict:
    """
    The venues and people already known in a workspace.

    A venue is not always a journal: this corpus also contains a book
    publisher, arXiv and a paper that ended up on LinkedIn. The vocabulary
    holds all of them.

    Read this before recording a submission or adding an author: reusing an
    existing spelling keeps the per-venue statistics from fragmenting, and stops
    the same person appearing twice. New values are still allowed — this is a
    vocabulary, not a whitelist.
    """
    db = SessionLocal()
    try:
        ws, _role = auth.mcp_workspace(db, workspace)
        return {"venues": known_venues(db, ws), "people": known_people(db)}
    except (LookupError, PermissionError) as e:
        return _fail(str(e))
    finally:
        db.close()


@mcp.tool()
def add_note(workspace: str, project_id: int, body: str) -> dict:
    """Append a note to a project. Notes are the record of the thinking; this is
    the replacement for the Notion comments."""
    db = SessionLocal()
    try:
        ws, _role = auth.mcp_workspace(db, workspace, "write")
        user = auth.current_caller()
        p = (db.query(Project)
               .filter(Project.id == project_id,
                       Project.workspace_id == ws.id).first())
        if not p:
            return _fail(f"No project {project_id} in '{workspace}'")
        if not body.strip():
            return _fail("Empty note")
        db.add(Note(project_id=p.id, user_id=user.id, body_md=body.strip(),
                    source="mcp", ts=utcnow()))
        log_event(db, p, user, "note_added", payload=json.dumps({"via": "mcp"}))
        db.commit()
        return {"ok": True, "project": p.title, "notes": len(p.notes)}
    except (LookupError, PermissionError) as e:
        return _fail(str(e))
    finally:
        db.close()


@mcp.tool()
def set_status(workspace: str, project_id: int, status: str,
               note: str = "") -> dict:
    """
    Move a project to a new status, optionally with a note explaining why.

    Moving into `submitted` without opening a submission leaves the venue
    unknown; prefer open_submission, which does both.

    `submitted` → `under_review` is the ordinary next step and means the paper
    reached the reviewers. It is a stage marker on the same attempt: it opens
    nothing, closes nothing, and the day count keeps running.
    """
    db = SessionLocal()
    try:
        ws, _role = auth.mcp_workspace(db, workspace, "write")
        user = auth.current_caller()
        if status not in STATUSES:
            return _fail(f"Unknown status '{status}'. One of: {STATUSES}")
        p = (db.query(Project)
               .filter(Project.id == project_id,
                       Project.workspace_id == ws.id).first())
        if not p:
            return _fail(f"No project {project_id} in '{workspace}'")
        old = p.status
        if old == status:
            return {"ok": True, "unchanged": True, "status": status}
        p.status = status
        log_event(db, p, user, "status_change", from_status=old, to_status=status)
        if note.strip():
            db.add(Note(project_id=p.id, user_id=user.id, body_md=note.strip(),
                        source="mcp", ts=utcnow()))
            log_event(db, p, user, "note_added")
        db.commit()
        return {"ok": True, "project": p.title, "from": old, "to": status,
                "effective": effective_status(p)}
    except (LookupError, PermissionError) as e:
        return _fail(str(e))
    finally:
        db.close()


@mcp.tool()
def open_submission(workspace: str, project_id: int, venue: str,
                    submitted_at: str = "") -> dict:
    """
    Record that a paper went out. Date as YYYY-MM-DD, today if empty.

    `venue` is a journal, but also a book publisher, a preprint server or a
    platform — whatever the piece was actually sent to.

    Also moves the project to `submitted`, because a paper on an editor's desk
    is not still "ready". Move it on to `under_review` with set_status once the
    reviewers have it.
    """
    db = SessionLocal()
    try:
        ws, _role = auth.mcp_workspace(db, workspace, "write")
        user = auth.current_caller()
        p = (db.query(Project)
               .filter(Project.id == project_id,
                       Project.workspace_id == ws.id).first())
        if not p:
            return _fail(f"No project {project_id} in '{workspace}'")
        if not venue.strip():
            return _fail("A venue is required")
        when = utcnow()
        if submitted_at.strip():
            try:
                when = datetime.strptime(submitted_at.strip(), "%Y-%m-%d")
            except ValueError:
                return _fail("submitted_at must be YYYY-MM-DD")
        venue = snap(venue, known_venues(db, ws))
        # A resubmission after a revision reopens the same attempt: a second row
        # would leave the first pending forever and shadow every later outcome.
        reopened = _open_attempt(p)
        if reopened and venue.lower() == reopened.venue.lower():
            log_event(db, p, user, "submission_opened",
                      payload=json.dumps({"venue": reopened.venue,
                                          "attempt": reopened.attempt,
                                          "resubmission": True}))
            db.commit()
            return {"ok": True, "submission_id": reopened.id,
                    "venue": reopened.venue, "attempt": reopened.attempt,
                    "resubmission": True,
                    "note": "same attempt reopened, the clock kept running"}
        # A different venue while one is still open is not a resubmission, it
        # is two live attempts — and the older would stay pending forever, the
        # same failure the branch above avoids. Refuse and say what to do.
        if reopened:
            return _fail(f"Attempt {reopened.attempt} is still open at "
                         f"'{reopened.venue}'. Record its outcome first, or "
                         f"pass that venue to reopen the same attempt.")
        # Snap onto a venue already used here, so the model coining
        # "Nature Human Behavior" does not fork the stats for a journal already
        # recorded as "Nature Human Behaviour".
        # max(attempt) + 1, not len(): counting rows repeats a number as soon as
        # there is a gap.
        nxt = (max((x.attempt or 0) for x in p.submissions) + 1
               if p.submissions else 1)
        s = Submission(project_id=p.id, venue=venue,
                       attempt=nxt, submitted_at=when,
                       outcome="pending")
        db.add(s)
        # Same set as the web route: sending out settles the question, but a
        # published or archived project is not resurrected by recording history.
        if p.status in ("idea", "developed", "active", "writing", "ready",
                        "in_revision"):
            log_event(db, p, user, "status_change",
                      from_status=p.status, to_status="submitted")
            p.status = "submitted"
        log_event(db, p, user, "submission_opened",
                  payload=json.dumps({"venue": s.venue, "attempt": s.attempt}))
        db.commit()
        return {"ok": True, "submission_id": s.id, "venue": s.venue,
                "attempt": s.attempt}
    except (LookupError, PermissionError) as e:
        return _fail(str(e))
    finally:
        db.close()


@mcp.tool()
def record_outcome(workspace: str, submission_id: int, outcome: str,
                   note: str = "", outcome_at: str = "") -> dict:
    """
    Record an outcome on a submission attempt. outcome: desk_reject,
    major_revision, minor_revision, reject_after_review, accept, withdrawn.

    `outcome_at` is the date on the decision letter (YYYY-MM-DD), which is
    usually NOT today: pass it whenever you know it, or every latency this
    system computes is wrong by however long it took to get round to typing it.

    A revision keeps the attempt open — the paper is still at that venue and the
    clock is still running — and the project's status moves with the outcome.
    """
    db = SessionLocal()
    try:
        ws, _role = auth.mcp_workspace(db, workspace, "write")
        user = auth.current_caller()
        s = (db.query(Submission)
               .join(Project, Project.id == Submission.project_id)
               .filter(Submission.id == submission_id,
                       Project.workspace_id == ws.id).first())
        if not s:
            return _fail(f"No submission {submission_id} in '{workspace}'")
        if outcome not in SUBMISSION_OUTCOMES or outcome == "pending":
            return _fail(f"outcome must be one of "
                         f"{[o for o in SUBMISSION_OUTCOMES if o != 'pending']}")
        p = s.project
        when = None
        if outcome_at.strip():
            try:
                when = datetime.strptime(outcome_at.strip(), "%Y-%m-%d")
            except ValueError:
                return _fail("outcome_at must be YYYY-MM-DD")
        # Same function the web route uses. Two implementations of one rule is
        # one implementation and one bug: this surface used to close an attempt
        # on major_revision and never move the project's status.
        apply_outcome(db, s, outcome, user, when)
        if note.strip():
            db.add(Note(project_id=p.id, user_id=user.id, body_md=note.strip(),
                        source="mcp", ts=utcnow()))
            log_event(db, p, user, "note_added")
        db.commit()
        return {"ok": True, "venue": s.venue, "outcome": outcome,
                "attempt_still_open": outcome in KEEPS_ATTEMPT_OPEN,
                "project_status": p.status,
                "days_in_review": (s.outcome_at - s.submitted_at).days
                if s.outcome_at and s.submitted_at else None}
    except (LookupError, PermissionError) as e:
        return _fail(str(e))
    finally:
        db.close()


@mcp.tool()
def add_link(workspace: str, project_id: int, kind: str, target: str,
             label: str = "", private: bool = False) -> dict:
    """Attach a link. kind: wiki, file, grant, lssr, doi, url, repo. This is how
    a project stops being an island and points at the wiki page, the draft on
    disk, the grant, the systematic review.

    Set `private` when the target is somewhere only you can reach — a path in a
    personal wiki or vault, a local file. Private links are visible only to you,
    here and on the web. Prefer it over a shared link nobody else can follow:
    that is not shared information, it is a leaked filename."""
    db = SessionLocal()
    try:
        ws, _role = auth.mcp_workspace(db, workspace, "write")
        user = auth.current_caller()
        if kind not in LINK_KINDS:
            return _fail(f"kind must be one of {LINK_KINDS}")
        p = (db.query(Project)
               .filter(Project.id == project_id,
                       Project.workspace_id == ws.id).first())
        if not p:
            return _fail(f"No project {project_id} in '{workspace}'")
        if not target.strip():
            return _fail("A target is required")
        db.add(Link(project_id=p.id, kind=kind, target=target.strip(),
                    label=label.strip() or None,
                    user_id=user.id if private else None))
        # A private link's target is the thing being kept private: it must not
        # land in the event payload, which the whole workspace can read.
        log_event(db, p, user, "link_added",
                  payload=json.dumps({"kind": kind, "private": True} if private
                                     else {"kind": kind,
                                           "target": target.strip()}))
        db.commit()
        return {"ok": True, "links": len(p.links), "private": bool(private)}
    except (LookupError, PermissionError) as e:
        return _fail(str(e))
    finally:
        db.close()


@mcp.tool()
def add_author(workspace: str, project_id: int, name: str,
               role: str = "co-author") -> dict:
    """Attach a person to a project. role: lead, co-author, PI, supervisor.
    People need no account: most co-authors will never have one."""
    db = SessionLocal()
    try:
        ws, _role = auth.mcp_workspace(db, workspace, "write")
        user = auth.current_caller()
        p = (db.query(Project)
               .filter(Project.id == project_id,
                       Project.workspace_id == ws.id).first())
        if not p:
            return _fail(f"No project {project_id} in '{workspace}'")
        person = get_or_create_person(db, name)
        if not person:
            return _fail("A name is required")
        if any(a.person_id == person.id for a in p.authorships):
            return {"ok": True, "unchanged": True, "person": person.name}
        db.add(Authorship(project_id=p.id, person_id=person.id, role=role,
                          position=len(p.authorships)))
        log_event(db, p, user, "authorship_changed",
                  payload=json.dumps({"added": person.name, "role": role}))
        db.commit()
        return {"ok": True, "person": person.name, "role": role}
    except (LookupError, PermissionError) as e:
        return _fail(str(e))
    finally:
        db.close()


@mcp.tool()
def create_project(workspace: str, title: str, status: str = "idea",
                   summary: str = "", author: str = "",
                   output_type: str = "paper") -> dict:
    """
    Add a new project. Default status `idea`, which is where most things start
    and where many stay.

    output_type: paper, book, book_chapter, media_piece, linkedin_post, other.
    Not everything is a paper, and counting a book alongside one distorts every
    per-output statistic.
    """
    db = SessionLocal()
    try:
        ws, _role = auth.mcp_workspace(db, workspace, "write")
        user = auth.current_caller()
        if status not in STATUSES:
            return _fail(f"Unknown status '{status}'. One of: {STATUSES}")
        if not title.strip():
            return _fail("A title is required")
        p = Project(workspace_id=ws.id, title=title.strip(), status=status,
                    summary=summary.strip() or None, created_by=user.id,
                    output_type=(output_type if output_type in OUTPUT_TYPES
                                 else "paper"))
        db.add(p)
        db.flush()
        if author.strip():
            person = get_or_create_person(db, author)
            if person:
                db.add(Authorship(project_id=p.id, person_id=person.id,
                                  role="lead", position=0))
        log_event(db, p, user, "created", to_status=status)
        db.commit()
        return {"ok": True, "id": p.id, "title": p.title,
                "url": f"/w/{ws.slug}/p/{p.id}"}
    except (LookupError, PermissionError) as e:
        return _fail(str(e))
    finally:
        db.close()
