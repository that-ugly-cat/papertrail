"""
PaperTrail — research project tracking, idea to published paper.

Surfaces: the web app (session cookie), and **/mcp** for the model, gated by a
per-user X-API-Key — with the /mcp/k/{key} capability-URL variant for clients
that cannot send custom headers. The MCP key carries an identity, so the model
reaches exactly what its owner reaches, no more (see mcp_app.py).

Fase 1: auth, workspaces, membership, admin, project CRUD, event log, kanban
board with drag-and-drop and author filter. The submission cycle is wired in its
minimal form (open a submission, record an outcome) because without it a paper
that has just gone out has nowhere to sit; the analytics on top of it are Fase 3.
"""
import contextlib
import json
import os
from datetime import datetime
from pathlib import Path

from fastapi import Depends, FastAPI, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from auth import (
    WorkspaceAccess, check_api_key, create_token, get_current_user,
    hash_password, require_admin, set_caller, touch_login, verify_password,
    workspace_dep,
)
from models import (
    AUTHOR_ROLES, ApiKey, LINK_KINDS, OUTCOME_LABELS, ROLES, STATUSES, STATUS_LABELS,
    SUBMISSION_OUTCOMES, Authorship, Link, Membership, Note, Person, Project,
    SessionLocal, Submission, User, Workspace, effective_status, get_db,
    get_or_create_person, init_db, is_dormant, known_people, known_venues,
    last_event_at, log_event, open_submission, slugify, snap, user_workspaces,
    utcnow,
)

from mcp_app import mcp  # noqa: E402


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    async with mcp.session_manager.run():
        yield


BASE = Path(__file__).parent
app = FastAPI(title="PaperTrail", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")
templates = Jinja2Templates(directory=BASE / "templates")


def _md(text: str):
    import markdown as _mdlib
    from markupsafe import Markup
    return Markup(_mdlib.markdown(text or "", extensions=["extra", "nl2br"]))


templates.env.filters["markdown"] = _md
templates.env.globals.update(
    STATUSES=STATUSES, STATUS_LABELS=STATUS_LABELS, ROLES=ROLES,
    AUTHOR_ROLES=AUTHOR_ROLES, LINK_KINDS=LINK_KINDS,
    SUBMISSION_OUTCOMES=SUBMISSION_OUTCOMES, OUTCOME_LABELS=OUTCOME_LABELS,
    effective_status=effective_status, open_submission=open_submission,
)

# The MCP transport checks Host headers against DNS rebinding, so the public
# domain has to be allowed or every Caddy-proxied request is refused.
def _allowed_hosts() -> list[str]:
    from urllib.parse import urlparse
    hosts = ["localhost:8017", "127.0.0.1:8017", "localhost", "127.0.0.1"]
    public = urlparse(os.environ.get("PUBLIC_URL", "")).netloc
    if public:
        hosts.append(public)
    return hosts


from mcp.server.transport_security import TransportSecuritySettings  # noqa: E402

app.mount("/mcp", mcp.streamable_http_app(
    streamable_http_path="/", json_response=True, stateless_http=True,
    transport_security=TransportSecuritySettings(
        allowed_hosts=_allowed_hosts(),
        allowed_origins=[os.environ.get("PUBLIC_URL", "http://localhost:8017")])))


@app.middleware("http")
async def api_key_gate(request: Request, call_next):
    """
    Resolve the MCP caller, or refuse.

    Two ways in, one table. The header is the normal path; /mcp/k/{key} carries
    the same key as a path segment for clients that cannot set headers, and is
    stripped before the mounted app sees it, so the MCP layer stays unaware of
    how the caller authenticated.
    """
    path = request.url.path
    if not path.startswith("/mcp"):
        return await call_next(request)

    if path.startswith("/mcp/k/"):
        key, _, rest = path[len("/mcp/k/"):].partition("/")
        request.scope["path"] = "/mcp/" + rest
        request.scope["raw_path"] = request.scope["path"].encode()
    else:
        key = request.headers.get("X-API-Key", "")

    db = SessionLocal()
    try:
        row = check_api_key(db, key)
        set_caller(row.user if row else None)
    finally:
        db.close()
    if not row:
        return JSONResponse({"error": "missing or invalid API key"},
                            status_code=401)
    return await call_next(request)


@app.exception_handler(HTTPException)
async def auth_redirect(request: Request, exc: HTTPException):
    """Unauthenticated HTML requests get /login instead of raw 401 JSON."""
    accepts_html = "text/html" in request.headers.get("accept", "")
    if exc.status_code == status.HTTP_401_UNAUTHORIZED and accepts_html:
        return RedirectResponse("/login", status_code=302)
    if accepts_html and exc.status_code in (403, 404):
        return templates.TemplateResponse(
            request, "error.html",
            {"user": None, "code": exc.status_code,
             "detail": exc.detail},
            status_code=exc.status_code,
        )
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)


def _project_or_404(acc: WorkspaceAccess, pid: int) -> Project:
    p = (acc.db.query(Project)
           .filter(Project.id == pid,
                   Project.workspace_id == acc.workspace.id)
           .first())
    if p is None:
        raise HTTPException(status_code=404, detail="Not found")
    return p


# ── auth ──────────────────────────────────────────────────────────────────────

@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse(
        request, "login.html", {"user": None})


@app.post("/login")
def login(request: Request, email: str = Form(...), password: str = Form(...),
          db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == email.strip().lower()).first()
    if not user or not user.is_active or not verify_password(password, user.hashed_password):
        return templates.TemplateResponse(
            request, "login.html",
            {"user": None, "error": "Invalid credentials."},
            status_code=401,
        )
    touch_login(db, user)
    resp = RedirectResponse("/", status_code=302)
    resp.set_cookie("session", create_token(user.id), httponly=True,
                    samesite="lax", max_age=7 * 24 * 3600,
                    secure=os.environ.get("COOKIE_SECURE", "1") == "1")
    return resp


@app.get("/logout")
def logout():
    resp = RedirectResponse("/login", status_code=302)
    resp.delete_cookie("session")
    return resp


# ── workspaces ────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
def home(request: Request, user: User = Depends(get_current_user),
         db: Session = Depends(get_db)):
    rows = user_workspaces(db, user)
    counts = {}
    for ws, _role in rows:
        counts[ws.id] = (db.query(Project)
                           .filter(Project.workspace_id == ws.id)
                           .count())
    return templates.TemplateResponse(
        request, "workspaces.html",
        {"user": user, "rows": rows, "counts": counts},
    )


@app.get("/w/{slug}", response_class=HTMLResponse)
def board(request: Request, slug: str, person: int | None = None,
          q: str | None = None, dormant: int = 0,
          acc: WorkspaceAccess = Depends(workspace_dep("read"))):
    db, ws = acc.db, acc.workspace
    projects = (db.query(Project)
                  .filter(Project.workspace_id == ws.id)
                  .order_by(Project.position, Project.id)
                  .all())

    if person:
        projects = [p for p in projects
                    if any(a.person_id == person for a in p.authorships)]
    if q:
        needle = q.lower()
        projects = [p for p in projects
                    if needle in (p.title or "").lower()
                    or needle in (p.summary or "").lower()
                    or needle in (p.final_title or "").lower()]
    if dormant:
        projects = [p for p in projects if is_dormant(p, ws.dormant_after_days)]

    columns = {s: [] for s in STATUSES}
    for p in projects:
        columns.setdefault(p.status, []).append(p)

    # Everyone who authors something here, for the filter dropdown.
    people = (db.query(Person)
                .join(Authorship, Authorship.person_id == Person.id)
                .join(Project, Project.id == Authorship.project_id)
                .filter(Project.workspace_id == ws.id)
                .distinct()
                .order_by(Person.name)
                .all())

    venues = known_venues(db, ws)

    return templates.TemplateResponse(
        request, "board.html",
        {"user": acc.user, "ws": ws, "role": acc.role,
         "can_write": acc.can_write, "can_admin": acc.can_admin,
         "columns": columns, "people": people, "sel_person": person,
         "q": q or "", "dormant": dormant,
         "dormant_days": ws.dormant_after_days, "venues": venues,
         "is_dormant": lambda p: is_dormant(p, ws.dormant_after_days)},
    )


@app.post("/w/{slug}/projects")
def create_project(slug: str, title: str = Form(...),
                   status_: str = Form("idea", alias="status"),
                   acc: WorkspaceAccess = Depends(workspace_dep("write"))):
    db = acc.db
    if status_ not in STATUSES:
        status_ = "idea"
    p = Project(workspace_id=acc.workspace.id, title=title.strip(),
                status=status_, created_by=acc.user.id, position=0)
    db.add(p)
    db.flush()
    log_event(db, p, acc.user, "created", to_status=status_)
    db.commit()
    return RedirectResponse(f"/w/{slug}/p/{p.id}", status_code=302)


@app.post("/api/w/{slug}/move")
async def move_project(slug: str, request: Request,
                       acc: WorkspaceAccess = Depends(workspace_dep("write"))):
    """
    Drag-and-drop endpoint.

    Body: {project_id, status, order: [ids in column]} plus, when the move
    crosses the `submitted` boundary, {venue, submitted_at, outcome, note}.

    A status_change event is written only when the column actually changed:
    reordering inside a column is not a transition and must not pollute the
    event log, which is what dormancy and staleness are read from.

    Crossing into `submitted` opens a Submission; crossing out of it records the
    outcome on the open one. That is the moment the information exists — asking
    for it later means never getting it.
    """
    db = acc.db
    body = await request.json()
    p = _project_or_404(acc, int(body.get("project_id", 0)))
    new_status = body.get("status")
    if new_status not in STATUSES:
        raise HTTPException(status_code=400, detail="Unknown status")

    old_status = p.status
    if new_status != old_status:
        p.status = new_status
        log_event(db, p, acc.user, "status_change",
                  from_status=old_status, to_status=new_status)

        if new_status == "submitted":
            venue = snap(body.get("venue"), known_venues(db, acc.workspace)) or ""
            when = utcnow()
            if body.get("submitted_at"):
                try:
                    when = datetime.strptime(body["submitted_at"], "%Y-%m-%d")
                except ValueError:
                    pass
            if venue:
                s = Submission(project_id=p.id, venue=venue,
                               attempt=len(p.submissions) + 1,
                               submitted_at=when, outcome="pending")
                db.add(s)
                log_event(db, p, acc.user, "submission_opened",
                          payload=json.dumps({"venue": venue,
                                              "attempt": s.attempt}))
        elif old_status == "submitted":
            outcome = body.get("outcome")
            s = open_submission(p)
            if s and outcome in SUBMISSION_OUTCOMES and outcome != "pending":
                s.outcome = outcome
                s.outcome_at = utcnow()
                log_event(db, p, acc.user, "submission_outcome",
                          payload=json.dumps({"venue": s.venue,
                                              "outcome": outcome,
                                              "attempt": s.attempt}))

        note = (body.get("note") or "").strip()
        if note:
            db.add(Note(project_id=p.id, user_id=acc.user.id, body_md=note,
                        source="web", ts=utcnow()))
            log_event(db, p, acc.user, "note_added")

    for idx, pid in enumerate(body.get("order", [])):
        row = (db.query(Project)
                 .filter(Project.id == int(pid),
                         Project.workspace_id == acc.workspace.id)
                 .first())
        if row:
            row.position = idx
    db.commit()
    eff = effective_status(p)
    return {"ok": True, "status": p.status, "effective": eff,
            "changed": new_status != old_status}


# ── project page ──────────────────────────────────────────────────────────────

@app.get("/w/{slug}/p/{pid}", response_class=HTMLResponse)
def project_page(request: Request, slug: str, pid: int, partial: int = 0,
                 acc: WorkspaceAccess = Depends(workspace_dep("read"))):
    """
    One project, rendered two ways from one template.

    `partial=1` returns just the body, which the board injects into a dialog.
    The plain URL still serves the full page, so a card stays shareable,
    refreshable and reachable with the back button — the thing a modal-only
    implementation quietly takes away.
    """
    p = _project_or_404(acc, pid)
    events = sorted(p.events, key=lambda e: e.ts or utcnow(), reverse=True)
    notes = sorted(p.notes, key=lambda n: n.ts or utcnow(), reverse=True)
    subs = sorted(p.submissions, key=lambda s: s.submitted_at or utcnow(),
                  reverse=True)
    return templates.TemplateResponse(
        request, "_project_body.html" if partial else "project.html",
        {"user": acc.user, "ws": acc.workspace,
         "role": acc.role, "can_write": acc.can_write, "p": p,
         "events": events, "notes": notes, "subs": subs,
         "venues": known_venues(acc.db, acc.workspace),
         "people": known_people(acc.db),
         "eff": effective_status(p),
         "dormant": is_dormant(p, acc.workspace.dormant_after_days),
         "last_event": last_event_at(p)},
    )


@app.get("/w/{slug}/done", response_class=HTMLResponse)
def hall_of_done(request: Request, slug: str,
                 acc: WorkspaceAccess = Depends(workspace_dep("read"))):
    """Published work as cards, newest year first. Papers with no year land in
    a bucket of their own rather than being dropped."""
    db, ws = acc.db, acc.workspace
    published = (db.query(Project)
                   .filter(Project.workspace_id == ws.id,
                           Project.status == "published")
                   .all())
    by_year: dict[int | None, list[Project]] = {}
    for p in published:
        by_year.setdefault(p.pub_year, []).append(p)
    for group in by_year.values():
        group.sort(key=lambda x: (x.final_title or x.title).lower())
    years = sorted((y for y in by_year if y), reverse=True)
    if None in by_year:
        years.append(None)
    return templates.TemplateResponse(
        request, "done.html",
        {"user": acc.user, "ws": ws, "role": acc.role,
         "can_admin": acc.can_admin, "by_year": by_year, "years": years,
         "total": len(published)},
    )


@app.post("/w/{slug}/p/{pid}")
def edit_project(slug: str, pid: int,
                 title: str = Form(...), status_: str = Form(..., alias="status"),
                 final_title: str = Form(""), journal: str = Form(""),
                 doi: str = Form(""), pub_year: str = Form(""),
                 summary: str = Form(""),
                 acc: WorkspaceAccess = Depends(workspace_dep("write"))):
    db = acc.db
    p = _project_or_404(acc, pid)
    changed = []
    for field, value in (("title", title.strip()),
                         ("final_title", final_title.strip() or None),
                         ("journal", snap(journal, known_venues(db, acc.workspace))),
                         ("doi", doi.strip() or None),
                         ("summary", summary.strip() or None)):
        if getattr(p, field) != value:
            changed.append(field)
            setattr(p, field, value)

    year = None
    if pub_year.strip():
        try:
            year = int(pub_year.strip())
        except ValueError:
            year = p.pub_year
    if p.pub_year != year:
        changed.append("pub_year")
        p.pub_year = year

    if status_ in STATUSES and status_ != p.status:
        log_event(db, p, acc.user, "status_change",
                  from_status=p.status, to_status=status_)
        p.status = status_

    if changed:
        log_event(db, p, acc.user, "field_changed",
                  payload=json.dumps({"fields": changed}))
    db.commit()
    return RedirectResponse(f"/w/{slug}/p/{pid}", status_code=302)


@app.post("/w/{slug}/p/{pid}/notes")
def add_note(slug: str, pid: int, body: str = Form(...),
             acc: WorkspaceAccess = Depends(workspace_dep("write"))):
    db = acc.db
    p = _project_or_404(acc, pid)
    if body.strip():
        db.add(Note(project_id=p.id, user_id=acc.user.id, body_md=body.strip(),
                    source="web", ts=utcnow()))
        log_event(db, p, acc.user, "note_added")
        db.commit()
    return RedirectResponse(f"/w/{slug}/p/{pid}", status_code=302)


@app.post("/w/{slug}/p/{pid}/authors")
def add_author(slug: str, pid: int, name: str = Form(...),
               role: str = Form("co-author"),
               acc: WorkspaceAccess = Depends(workspace_dep("write"))):
    db = acc.db
    p = _project_or_404(acc, pid)
    person = get_or_create_person(db, name)
    if person and not any(a.person_id == person.id for a in p.authorships):
        db.add(Authorship(project_id=p.id, person_id=person.id,
                          role=role if role in AUTHOR_ROLES else "co-author",
                          position=len(p.authorships)))
        log_event(db, p, acc.user, "authorship_changed",
                  payload=json.dumps({"added": person.name, "role": role}))
        db.commit()
    return RedirectResponse(f"/w/{slug}/p/{pid}", status_code=302)


@app.post("/w/{slug}/p/{pid}/authors/{aid}/remove")
def remove_author(slug: str, pid: int, aid: int,
                  acc: WorkspaceAccess = Depends(workspace_dep("write"))):
    db = acc.db
    p = _project_or_404(acc, pid)
    a = db.query(Authorship).filter(Authorship.id == aid,
                                    Authorship.project_id == p.id).first()
    if a:
        log_event(db, p, acc.user, "authorship_changed",
                  payload=json.dumps({"removed": a.person.name}))
        db.delete(a)
        db.commit()
    return RedirectResponse(f"/w/{slug}/p/{pid}", status_code=302)


@app.post("/w/{slug}/p/{pid}/links")
def add_link(slug: str, pid: int, kind: str = Form(...), target: str = Form(...),
             label: str = Form(""),
             acc: WorkspaceAccess = Depends(workspace_dep("write"))):
    db = acc.db
    p = _project_or_404(acc, pid)
    if kind in LINK_KINDS and target.strip():
        db.add(Link(project_id=p.id, kind=kind, target=target.strip(),
                    label=label.strip() or None))
        log_event(db, p, acc.user, "link_added",
                  payload=json.dumps({"kind": kind, "target": target.strip()}))
        db.commit()
    return RedirectResponse(f"/w/{slug}/p/{pid}", status_code=302)


@app.post("/w/{slug}/p/{pid}/links/{lid}/remove")
def remove_link(slug: str, pid: int, lid: int,
                acc: WorkspaceAccess = Depends(workspace_dep("write"))):
    db = acc.db
    p = _project_or_404(acc, pid)
    link = db.query(Link).filter(Link.id == lid, Link.project_id == p.id).first()
    if link:
        db.delete(link)
        db.commit()
    return RedirectResponse(f"/w/{slug}/p/{pid}", status_code=302)


@app.post("/w/{slug}/p/{pid}/submissions")
def open_sub(slug: str, pid: int, venue: str = Form(...),
             submitted_at: str = Form(""),
             acc: WorkspaceAccess = Depends(workspace_dep("write"))):
    db = acc.db
    p = _project_or_404(acc, pid)
    when = utcnow()
    if submitted_at.strip():
        try:
            when = datetime.strptime(submitted_at.strip(), "%Y-%m-%d")
        except ValueError:
            pass
    s = Submission(project_id=p.id,
                   venue=snap(venue, known_venues(db, acc.workspace)),
                   attempt=len(p.submissions) + 1, submitted_at=when,
                   outcome="pending")
    db.add(s)
    if p.status in ("ready", "writing", "active"):
        log_event(db, p, acc.user, "status_change",
                  from_status=p.status, to_status="submitted")
        p.status = "submitted"
    log_event(db, p, acc.user, "submission_opened",
              payload=json.dumps({"venue": s.venue, "attempt": s.attempt}))
    db.commit()
    return RedirectResponse(f"/w/{slug}/p/{pid}", status_code=302)


@app.post("/w/{slug}/p/{pid}/submissions/{sid}/outcome")
def sub_outcome(slug: str, pid: int, sid: int, outcome: str = Form(...),
                acc: WorkspaceAccess = Depends(workspace_dep("write"))):
    db = acc.db
    p = _project_or_404(acc, pid)
    s = db.query(Submission).filter(Submission.id == sid,
                                    Submission.project_id == p.id).first()
    if s and outcome in SUBMISSION_OUTCOMES:
        s.outcome = outcome
        s.outcome_at = utcnow() if outcome != "pending" else None
        log_event(db, p, acc.user, "submission_outcome",
                  payload=json.dumps({"venue": s.venue, "outcome": outcome,
                                      "attempt": s.attempt}))
        db.commit()
    return RedirectResponse(f"/w/{slug}/p/{pid}", status_code=302)


# ── members ───────────────────────────────────────────────────────────────────

@app.get("/w/{slug}/members", response_class=HTMLResponse)
def members_page(request: Request, slug: str,
                 acc: WorkspaceAccess = Depends(workspace_dep("admin"))):
    db = acc.db
    rows = (db.query(Membership, User)
              .join(User, User.id == Membership.user_id)
              .filter(Membership.workspace_id == acc.workspace.id)
              .order_by(User.name)
              .all())
    member_ids = {m.user_id for m, _ in rows}
    candidates = (db.query(User)
                    .filter(User.is_active == True,          # noqa: E712
                            ~User.id.in_(member_ids or [0]))
                    .order_by(User.name).all())
    return templates.TemplateResponse(
        request, "members.html",
        {"user": acc.user, "ws": acc.workspace,
         "role": acc.role, "can_admin": True, "rows": rows,
         "candidates": candidates},
    )


@app.post("/w/{slug}/members")
def add_member(slug: str, user_id: int = Form(...), role: str = Form(...),
               acc: WorkspaceAccess = Depends(workspace_dep("admin"))):
    db = acc.db
    if role not in ROLES:
        raise HTTPException(status_code=400, detail="Unknown role")
    exists = (db.query(Membership)
                .filter(Membership.user_id == user_id,
                        Membership.workspace_id == acc.workspace.id).first())
    if not exists:
        db.add(Membership(user_id=user_id, workspace_id=acc.workspace.id,
                          role=role, created_by=acc.user.id))
        db.commit()
    return RedirectResponse(f"/w/{slug}/members", status_code=302)


@app.post("/w/{slug}/members/{mid}")
def change_member(slug: str, mid: int, role: str = Form(...),
                  acc: WorkspaceAccess = Depends(workspace_dep("admin"))):
    db = acc.db
    m = db.query(Membership).filter(Membership.id == mid,
                                    Membership.workspace_id == acc.workspace.id).first()
    if m and role in ROLES:
        # Do not let the last admin demote themselves out of the workspace.
        if m.role == "admin" and role != "admin":
            admins = (db.query(Membership)
                        .filter(Membership.workspace_id == acc.workspace.id,
                                Membership.role == "admin").count())
            if admins <= 1:
                raise HTTPException(status_code=400,
                                    detail="A workspace needs at least one admin")
        m.role = role
        db.commit()
    return RedirectResponse(f"/w/{slug}/members", status_code=302)


@app.post("/w/{slug}/members/{mid}/remove")
def remove_member(slug: str, mid: int,
                  acc: WorkspaceAccess = Depends(workspace_dep("admin"))):
    db = acc.db
    m = db.query(Membership).filter(Membership.id == mid,
                                    Membership.workspace_id == acc.workspace.id).first()
    if m:
        if m.role == "admin":
            admins = (db.query(Membership)
                        .filter(Membership.workspace_id == acc.workspace.id,
                                Membership.role == "admin").count())
            if admins <= 1:
                raise HTTPException(status_code=400,
                                    detail="A workspace needs at least one admin")
        db.delete(m)
        db.commit()
    return RedirectResponse(f"/w/{slug}/members", status_code=302)


# ── admin ─────────────────────────────────────────────────────────────────────

@app.get("/admin", response_class=HTMLResponse)
def admin_page(request: Request, user: User = Depends(require_admin),
               db: Session = Depends(get_db)):
    users = db.query(User).order_by(User.name).all()
    workspaces = db.query(Workspace).order_by(Workspace.name).all()
    return templates.TemplateResponse(
        request, "admin.html",
        {"user": user, "users": users,
         "workspaces": workspaces},
    )


@app.post("/admin/users")
def admin_create_user(email: str = Form(...), name: str = Form(...),
                      password: str = Form(...), is_admin: str = Form(""),
                      user: User = Depends(require_admin),
                      db: Session = Depends(get_db)):
    email = email.strip().lower()
    if not db.query(User).filter(User.email == email).first():
        u = User(email=email, name=name.strip(),
                 hashed_password=hash_password(password),
                 is_admin=bool(is_admin), is_active=True)
        db.add(u)
        db.flush()
        # Mirror every account into the people registry so authorship can point
        # at it without a second lookup.
        p = get_or_create_person(db, u.name)
        if p and p.user_id is None:
            p.user_id = u.id
        db.commit()
    return RedirectResponse("/admin", status_code=302)


@app.post("/admin/workspaces")
def admin_create_workspace(name: str = Form(...), slug: str = Form(""),
                           description: str = Form(""),
                           user: User = Depends(require_admin),
                           db: Session = Depends(get_db)):
    s = slugify(slug or name)
    if not db.query(Workspace).filter(Workspace.slug == s).first():
        ws = Workspace(slug=s, name=name.strip(),
                       description=description.strip() or None)
        db.add(ws)
        db.flush()
        # The creator becomes admin of it, otherwise nobody can open it.
        db.add(Membership(user_id=user.id, workspace_id=ws.id, role="admin",
                          created_by=user.id))
        db.commit()
    return RedirectResponse("/admin", status_code=302)


@app.get("/profile", response_class=HTMLResponse)
def profile(request: Request, user: User = Depends(get_current_user),
            db: Session = Depends(get_db)):
    keys = (db.query(ApiKey)
              .filter(ApiKey.user_id == user.id)
              .order_by(ApiKey.created_at.desc()).all())
    return templates.TemplateResponse(
        request, "profile.html",
        {"user": user, "keys": keys,
         "public_url": os.environ.get("PUBLIC_URL", "http://localhost:8017")})


@app.post("/profile/keys")
def create_key(name: str = Form(...), user: User = Depends(get_current_user),
               db: Session = Depends(get_db)):
    """Mint an MCP key for yourself. Keys belong to people, never to the
    deployment: a key reaches exactly the workspaces its owner is a member of,
    and revoking the person's membership revokes the key's reach with it."""
    db.add(ApiKey(user_id=user.id, name=name.strip() or "mcp"))
    db.commit()
    return RedirectResponse("/profile", status_code=302)


@app.post("/profile/keys/{key_id}/revoke")
def revoke_key(key_id: int, user: User = Depends(get_current_user),
               db: Session = Depends(get_db)):
    row = (db.query(ApiKey)
             .filter(ApiKey.id == key_id, ApiKey.user_id == user.id).first())
    if row:
        row.active = False
        db.commit()
    return RedirectResponse("/profile", status_code=302)


@app.post("/profile/password")
def change_password(request: Request, current: str = Form(...),
                    new: str = Form(...),
                    user: User = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    if not verify_password(current, user.hashed_password):
        return templates.TemplateResponse(
        request, "profile.html",
            {"user": user, "error": "Current password is wrong."},
            status_code=400,
        )
    user.hashed_password = hash_password(new)
    db.commit()
    return templates.TemplateResponse(
        request, "profile.html", {"user": user, "ok": "Password updated."})


@app.get("/healthz")
def healthz():
    return {"ok": True}
