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
    AUTHOR_ROLES, KEEPS_ATTEMPT_OPEN, LINK_KINDS, OUTCOME_LABELS, STATUSES,
    SUBMISSION_OUTCOMES, Authorship, Link,
    Note, Project, SessionLocal, Submission, apply_outcome, effective_status,
    flag_of, looks_like_preprint_doi,
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
            under_review, in_revision, accepted, published, archived. Empty
            means any. `submitted` is on an editor's desk, `under_review` is
            with the reviewers — same attempt, same clock, different kind of
            waiting. `accepted` is won but not out yet: proofs, embargo, an
            issue that fills up, and nobody here controls the queue.
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

    `accepted` is where a paper lands when the letter arrives, and `published`
    only once it is actually out with a DOI. Recording an `accept` outcome moves
    the card to `accepted` by itself, so this is rarely the tool to reach for.
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
    clock is still running — and the project's status moves with the outcome:
    `accept` lands the card in `accepted`, not in `published`, because an
    acceptance letter is not a DOI and the gap between them is months.
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
        if role not in AUTHOR_ROLES:
            # The web route folds an unknown role onto co-author; here it is an
            # error instead. A form has a select and cannot send nonsense, a
            # model can, and silently storing "first author" as "co-author"
            # writes a fact nobody checked. Same invariant, louder.
            return _fail(f"role must be one of {AUTHOR_ROLES}")
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


# ── correcting what is already there ──────────────────────────────────────────
#
# Everything above this line adds: a note, a status, an attempt, a link, an
# author, a project. Nothing above it could fix a typo or take something back,
# which meant this surface could write mistakes it could not clean up, and every
# correction — including the ones it had just caused — had to be finished by
# hand in the web app. That asymmetry is what the four tools below close.

# Fields update_project will blank on request. `title` is not among them: a
# project without one is unfindable in every list that sorts by it. `status` is
# not a field here at all — it moves through set_status, which logs the
# transition, and two doors onto one invariant is how they diverge (§8).
CLEARABLE_FIELDS = ("final_title", "journal", "doi", "pub_year", "summary")


@mcp.tool()
def update_project(workspace: str, project_id: int,
                   title: str | None = None, final_title: str | None = None,
                   journal: str | None = None, output_type: str | None = None,
                   doi: str | None = None, pub_year: int | None = None,
                   summary: str | None = None, clear: str = "") -> dict:
    """
    Correct a project's fields: title, final_title, journal, output_type, doi,
    pub_year, summary. For the status use set_status, which logs the move.

    Only what you pass is touched. An omitted field is left alone, and so is one
    passed empty — the web form sends every field on every save, so a blank
    there means "erase", but a model fills in what it knows and leaves the rest,
    and a tool where silence erases would quietly empty fields nobody mentioned.
    To blank something you must name it: clear="journal,doi".

    `title` is the working name, `final_title` the one it was published under;
    lists show the second where it exists. `journal` is folded onto a venue the
    workspace already uses when it differs only in case or spacing.

    `doi` is not a bibliographic detail: it is what makes a project read as
    Published everywhere (SPEC §5). A preprint belongs in a link instead —
    add_link(kind="preprint") — and a Zenodo or arXiv DOI here would announce a
    publication that has not happened, so this tool refuses one.
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

        wipe = {f.strip() for f in clear.split(",") if f.strip()}
        unknown = wipe - set(CLEARABLE_FIELDS)
        if unknown:
            return _fail(f"cannot clear {sorted(unknown)}; clearable fields are "
                         f"{list(CLEARABLE_FIELDS)}")
        if title is not None and not title.strip():
            return _fail("A project needs a title; pass a new one to rename it")
        if output_type is not None and output_type not in OUTPUT_TYPES:
            return _fail(f"output_type must be one of {OUTPUT_TYPES}")
        if doi and looks_like_preprint_doi(doi):
            return _fail(
                f"'{doi.strip()}' looks like a preprint DOI, and this field is "
                f"what marks a project Published. Record it as a link instead, "
                f"with add_link, kind 'preprint'.")
        if pub_year is not None and not (1900 <= pub_year <= 2100):
            return _fail("pub_year must be a four-digit year between 1900 and 2100")

        proposed = {
            "title": title.strip() if title and title.strip() else None,
            "final_title": final_title.strip() if final_title and final_title.strip() else None,
            "journal": snap(journal, known_venues(db, ws)) if journal else None,
            "output_type": output_type,
            "doi": doi.strip() if doi and doi.strip() else None,
            "pub_year": pub_year,
            "summary": summary.strip() if summary and summary.strip() else None,
        }
        was_published = bool(p.doi)
        changed = []
        for field, value in proposed.items():
            if field in wipe:
                value = None
            elif value is None:
                continue
            if getattr(p, field) != value:
                setattr(p, field, value)
                changed.append(field)

        if changed:
            log_event(db, p, user, "field_changed",
                      payload=json.dumps({"fields": changed}))
            db.commit()
        eff = effective_status(p)
        out = {"ok": True, "changed": changed, "status": p.status,
               "effective_status": eff["label"],
               "status_mismatch": eff["diverges"],
               "url": f"/w/{ws.slug}/p/{p.id}"}
        if "doi" in changed and bool(p.doi) != was_published:
            # Said out loud, because the caller edited one field and moved the
            # project across the board: the DOI is the switch, not the label.
            out["note"] = ("Reads as Published now." if p.doi else
                           "No DOI any more, so it stops reading as Published.")
        return out
    except (LookupError, PermissionError) as e:
        return _fail(str(e))
    finally:
        db.close()


@mcp.tool()
def remove_author(workspace: str, project_id: int, name: str) -> dict:
    """
    Detach a person from a project. The person record stays: they are on other
    papers, and their name is the vocabulary this workspace autocompletes from.

    By name rather than by id, because a name is what get_project returns and
    what the conversation is already using — and add_author refuses duplicates,
    so on any one project a name identifies exactly one row.
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
        needle = " ".join(name.split()).lower()
        hit = [a for a in p.authorships if a.person.name.lower() == needle]
        if not hit:
            return _fail(f"'{name}' is not an author of {project_id}. On it: "
                         f"{[a.person.name for a in p.authorships]}")
        gone = hit[0].person.name
        log_event(db, p, user, "authorship_changed",
                  payload=json.dumps({"removed": gone}))
        db.delete(hit[0])
        db.commit()
        return {"ok": True, "removed": gone,
                "authors": [a.person.name for a in p.authorships]}
    except (LookupError, PermissionError) as e:
        return _fail(str(e))
    finally:
        db.close()


@mcp.tool()
def remove_link(workspace: str, project_id: int, target: str) -> dict:
    """
    Detach a link, named by its target — the same string add_link took.

    Someone else's private link is invisible here, so it is unremovable here
    too, and the answer is "no such link" rather than a refusal: saying no
    loudly would confirm that something is there (§3).
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
        needle = target.strip()
        visible = visible_links(p, user)
        hit = [l for l in visible if l.target == needle]
        if not hit:
            return _fail(f"No link to '{needle}' on {project_id}. Present: "
                         f"{[l.target for l in visible]}")
        if len(hit) > 1:
            return _fail(f"{len(hit)} links point at '{needle}'; remove the "
                         f"right one in the web app")
        db.delete(hit[0])
        db.commit()
        return {"ok": True, "removed": needle,
                "links": len(visible_links(p, user))}
    except (LookupError, PermissionError) as e:
        return _fail(str(e))
    finally:
        db.close()


@mcp.tool()
def edit_submission(workspace: str, submission_id: int, venue: str = "",
                    submitted_at: str = "", outcome_at: str = "") -> dict:
    """
    Fix an attempt's venue or its dates. Dates as YYYY-MM-DD; empty leaves the
    field alone.

    Separate from record_outcome on purpose: one says what the editor decided,
    the other fixes what we wrote down, and conflating them logs a typo as an
    editorial event. Reach for it above all on `submitted_at` — every latency
    this system reports is measured from it, so a date left at today because
    nobody looked it up makes the whole clock lie.
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
        p = s.project
        changed = {}
        if venue.strip():
            new_venue = snap(venue, known_venues(db, ws))
            if new_venue and new_venue != s.venue:
                changed["venue"] = [s.venue, new_venue]
                s.venue = new_venue
        for field, raw in (("submitted_at", submitted_at),
                           ("outcome_at", outcome_at)):
            if not raw.strip():
                continue
            try:
                parsed = datetime.strptime(raw.strip(), "%Y-%m-%d")
            except ValueError:
                # Not the old value back, which is the bug SPEC §8 names as a
                # category: a malformed date quietly becoming a plausible one
                # is a record that lies with a straight face.
                return _fail(f"{field} must be YYYY-MM-DD, got '{raw.strip()}'")
            current = getattr(s, field)
            if parsed != current:
                changed[field] = [current and current.strftime("%Y-%m-%d"),
                                  parsed.strftime("%Y-%m-%d")]
                setattr(s, field, parsed)
        if s.submitted_at and s.outcome_at and s.outcome_at < s.submitted_at:
            db.rollback()
            return _fail("outcome_at is before submitted_at; a decision cannot "
                         "predate the submission it answers")
        if changed:
            log_event(db, p, user, "field_changed",
                      payload=json.dumps({"submission": s.id, "fields": changed}))
            db.commit()
        return {"ok": True, "changed": changed, "venue": s.venue,
                "days_open": s.days_open,
                "url": f"/w/{ws.slug}/p/{p.id}"}
    except (LookupError, PermissionError) as e:
        return _fail(str(e))
    finally:
        db.close()
