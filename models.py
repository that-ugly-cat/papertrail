"""
Database models for PaperTrail.

ORM: SQLAlchemy with SQLite (./data/papertrail.db, persisted via Docker volume).

Access model (SPEC.md §3): a Membership row IS the access. There is no
role='none' — absence of a row means the workspace does not exist for that user,
and routes answer 404 rather than 403 so the existence of a workspace is not
leaked.

Migration strategy (borant house pattern): init_db() runs ALTER TABLE for each
new column on every startup; SQLite raises on duplicates, caught and ignored
(additive only).
"""
import json
import os
import re
import secrets
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean, Column, DateTime, ForeignKey, Integer, String, Text,
    UniqueConstraint, create_engine, text,
)
from sqlalchemy.orm import DeclarativeBase, relationship, sessionmaker

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./data/papertrail.db")

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def utcnow() -> datetime:
    """Naive UTC, consistent with the rest of the borant tools."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ── vocabularies ──────────────────────────────────────────────────────────────

# Declared statuses. `dormant` is NOT here: it is computed from the event log
# (SPEC.md §5). Order matters — it drives the kanban column order.
STATUSES = ["idea", "developed", "active", "writing", "ready", "submitted",
            "in_revision", "published", "archived"]

STATUS_LABELS = {
    "idea":      "Idea",
    "developed": "Developed",
    "active":    "Active",
    "writing":   "Writing up",
    "ready":     "Ready",
    "submitted": "Submitted",
    "in_revision": "In revision",
    "published": "Published",
    "archived":  "Archived",
}

# `submitted` is a *declared* status only while a project has no open Submission
# row. Once one exists, effective_status() overrides the label with the venue and
# the elapsed days. It is kept as a column so the board has somewhere to put a
# paper the moment it goes out, before anyone fills in the venue.

ROLES = ["read", "write", "admin"]
ROLE_RANK = {"read": 1, "write": 2, "admin": 3}

AUTHOR_ROLES = ["lead", "co-author", "PI", "supervisor"]

SUBMISSION_OUTCOMES = ["pending", "desk_reject", "major_revision",
                       "minor_revision", "reject_after_review", "accept",
                       "withdrawn", "transferred", "unknown"]

OUTCOME_LABELS = {
    "pending":             "in review",
    "desk_reject":         "desk reject",
    "major_revision":      "major revision",
    "minor_revision":      "minor revision",
    "reject_after_review": "reject after review",
    "accept":              "accepted",
    "withdrawn":           "withdrawn",
    # Real and frequent in this corpus: 7 notes across 4 projects. A cascade
    # transfer (BMJ, Nature portfolio, SSM) ends the attempt at one venue and
    # starts one at a sister journal without a rejection in between. Recording
    # it as "rejected" would libel the editor and distort the venue statistics.
    "transferred":         "transferred to another journal",
    # Closed, but nobody wrote down how. Distinct from a rejection on purpose:
    # a paper that moved on almost certainly bounced, but "almost certainly" is
    # not a datum. Excluded from latency statistics, which is the right
    # behaviour for a number that was never observed.
    "unknown":             "outcome not recorded",
}

# Leaving `submitted` leftwards and rightwards are different events, so they are
# asked different questions. Going left the paper came back to you; going right
# it moved on. Offering the full list in both directions invites the wrong
# answer — "accepted" has no business being on the way back to Writing up.
OUTCOMES_BACK = ["reject_after_review", "desk_reject", "transferred",
                 "withdrawn", "unknown"]
OUTCOMES_REVISION = ["major_revision", "minor_revision"]
OUTCOMES_PUBLISHED = ["accept"]
OUTCOMES_ARCHIVED = ["withdrawn", "reject_after_review", "desk_reject",
                     "transferred"]

# A revision request does NOT end the attempt: the manuscript is still at that
# venue, the clock is still running, and the next step is a resubmission to the
# same editor. Closing it here would restart the count and lose how long the
# venue actually held the paper — precisely the number this tool exists for.
KEEPS_ATTEMPT_OPEN = {"major_revision", "minor_revision"}


def outcomes_for(from_status: str, to_status: str) -> list[str]:
    """Which outcomes make sense for this particular move out of `submitted`."""
    if to_status == "in_revision":
        return OUTCOMES_REVISION
    if to_status == "published":
        return OUTCOMES_PUBLISHED
    if to_status == "archived":
        return OUTCOMES_ARCHIVED
    try:
        going_back = STATUSES.index(to_status) < STATUSES.index(from_status)
    except ValueError:
        going_back = True
    return OUTCOMES_BACK if going_back else OUTCOMES_PUBLISHED

# What the project produces. Not everything is a paper: this corpus already
# holds a Routledge book, a children's book, and a piece that ended up as a
# LinkedIn post after five journals turned it down. Lumping them together makes
# "attempts to publication" compare things that are not comparable.
OUTPUT_TYPES = ["paper", "book", "book_chapter", "media_piece",
                "linkedin_post", "other"]

OUTPUT_TYPE_LABELS = {
    "paper":         "Paper",
    "book":          "Book",
    "book_chapter":  "Book chapter",
    "media_piece":   "Media piece",
    "linkedin_post": "LinkedIn post",
    "other":         "Other",
}

LINK_KINDS = ["wiki", "file", "grant", "lssr", "doi", "preprint", "url",
              "repo"]

EVENT_TYPES = ["created", "status_change", "note_added", "submission_opened",
               "submission_outcome", "link_added", "authorship_changed",
               "field_changed", "imported", "member_added", "member_changed",
               "member_removed", "deleted", "restored"]


# ── users, workspaces, access ─────────────────────────────────────────────────

class User(Base):
    __tablename__ = "users"
    id                    = Column(Integer, primary_key=True)
    email                 = Column(String, unique=True, nullable=False)
    name                  = Column(String, nullable=False)
    hashed_password       = Column(String, nullable=False)
    totp_secret_encrypted = Column(String, nullable=True)
    totp_enabled          = Column(Boolean, default=False)
    # Global admin creates users and workspaces. It does NOT imply access to
    # workspace content: that still requires a Membership row (SPEC.md §3).
    is_admin              = Column(Boolean, default=False)
    is_active             = Column(Boolean, default=True)
    created_at            = Column(DateTime, default=utcnow)
    last_login            = Column(DateTime, nullable=True)

    # `foreign_keys` is required: memberships points at users twice (user_id and
    # created_by), so the join is otherwise ambiguous.
    memberships = relationship("Membership", back_populates="user",
                               foreign_keys="Membership.user_id",
                               cascade="all, delete-orphan")
    person      = relationship("Person", back_populates="user", uselist=False)


class Workspace(Base):
    __tablename__ = "workspaces"
    id                 = Column(Integer, primary_key=True)
    slug               = Column(String, unique=True, nullable=False)
    name               = Column(String, nullable=False)
    description        = Column(Text, nullable=True)
    archived           = Column(Boolean, default=False)
    # A project with no event for this many days reads as dormant (SPEC.md §5).
    dormant_after_days = Column(Integer, default=180)
    created_at         = Column(DateTime, default=utcnow)
    # 'group' (a research group) or 'personal' (one per user, SPEC.md §3).
    # A personal workspace is a workspace and nothing else: same Membership,
    # same role_for(), same 404. The distinction is only so the UI can pick a
    # sensible default and label it — never a second way to authorise.
    kind               = Column(String, default="group", nullable=False)
    owner_id           = Column(Integer, ForeignKey("users.id"), nullable=True)

    memberships = relationship("Membership", back_populates="workspace",
                               cascade="all, delete-orphan")
    projects    = relationship("Project", back_populates="workspace",
                               cascade="all, delete-orphan")


class ApiKey(Base):
    """
    An MCP credential, and deliberately a credential *of a person*.

    In Contrarian a key carries publisher entitlements; here it carries an
    identity. Every MCP call resolves to `user` and then goes through the same
    role_for() the web app uses, so a key can never reach a workspace its owner
    is not a member of. Without the user binding the MCP surface would be a hole
    straight through the access model described in SPEC.md §3.
    """
    __tablename__ = "api_keys"
    id           = Column(Integer, primary_key=True)
    user_id      = Column(Integer, ForeignKey("users.id"), nullable=False)
    name         = Column(String, nullable=False)
    key          = Column(String, unique=True, nullable=False,
                          default=lambda: "ptr_" + secrets.token_urlsafe(32))
    active       = Column(Boolean, default=True)
    created_at   = Column(DateTime, default=utcnow)
    last_used_at = Column(DateTime, nullable=True)

    user = relationship("User")


class Membership(Base):
    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("user_id", "workspace_id"),)
    id           = Column(Integer, primary_key=True)
    user_id      = Column(Integer, ForeignKey("users.id"), nullable=False)
    workspace_id = Column(Integer, ForeignKey("workspaces.id"), nullable=False)
    role         = Column(String, nullable=False)          # read | write | admin
    created_at   = Column(DateTime, default=utcnow)
    created_by   = Column(Integer, ForeignKey("users.id"), nullable=True)

    user      = relationship("User", foreign_keys=[user_id], back_populates="memberships")
    workspace = relationship("Workspace", back_populates="memberships")


# ── people ────────────────────────────────────────────────────────────────────

class Person(Base):
    """
    Distinct from User on purpose: most co-authors will never have an account
    (SPEC.md §4). Global rather than per-workspace, because the same people
    recur across groups.
    """
    __tablename__ = "people"
    id             = Column(Integer, primary_key=True)
    name           = Column(String, nullable=False)
    canonical_name = Column(String, nullable=False, index=True)
    affiliation    = Column(String, nullable=True)
    orcid          = Column(String, nullable=True)
    wiki_page      = Column(String, nullable=True)
    user_id        = Column(Integer, ForeignKey("users.id"), nullable=True, unique=True)
    created_at     = Column(DateTime, default=utcnow)

    user        = relationship("User", back_populates="person")
    authorships = relationship("Authorship", back_populates="person",
                               cascade="all, delete-orphan")


def canonical(name: str) -> str:
    """Fold a display name to a match key: lowercase, collapsed whitespace."""
    return re.sub(r"\s+", " ", (name or "").strip()).lower()


def get_or_create_person(db, name: str) -> "Person | None":
    name = (name or "").strip()
    if not name:
        return None
    key = canonical(name)
    person = db.query(Person).filter(Person.canonical_name == key).first()
    if not person:
        person = Person(name=name, canonical_name=key)
        db.add(person)
        db.flush()
    return person


# ── projects ──────────────────────────────────────────────────────────────────

class Project(Base):
    __tablename__ = "projects"
    id           = Column(Integer, primary_key=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id"), nullable=False)
    title        = Column(String, nullable=False)
    status       = Column(String, nullable=False, default="idea")
    final_title  = Column(String, nullable=True)
    summary      = Column(Text, nullable=True)
    journal      = Column(String, nullable=True)
    output_type  = Column(String, nullable=True, default="paper")
    doi          = Column(String, nullable=True)
    pub_year     = Column(Integer, nullable=True)
    # Position within its kanban column, so drag-and-drop ordering survives.
    position     = Column(Integer, default=0)
    imported     = Column(Boolean, default=False)
    # Soft delete. A project carries years of notes, submissions and events, and
    # a confirmation dialog in front of an irreversible DELETE is theatre: it
    # asks you to be careful instead of making a mistake survivable. Deleted
    # projects vanish from every view and can be brought back.
    deleted_at   = Column(DateTime, nullable=True)
    # Notion page id, so the import can be re-run without duplicating anything.
    notion_id    = Column(String, nullable=True, unique=True, index=True)
    created_at   = Column(DateTime, default=utcnow)
    created_by   = Column(Integer, ForeignKey("users.id"), nullable=True)

    workspace   = relationship("Workspace", back_populates="projects")
    shares      = relationship("ProjectWorkspace", back_populates="project",
                               cascade="all, delete-orphan")
    authorships = relationship("Authorship", back_populates="project",
                               cascade="all, delete-orphan")
    submissions = relationship("Submission", back_populates="project",
                               cascade="all, delete-orphan")
    events      = relationship("Event", back_populates="project",
                               cascade="all, delete-orphan")
    notes       = relationship("Note", back_populates="project",
                               cascade="all, delete-orphan")
    links       = relationship("Link", back_populates="project",
                               cascade="all, delete-orphan")
    deadlines   = relationship("Deadline", back_populates="project",
                               cascade="all, delete-orphan")


class ProjectWorkspace(Base):
    """
    A project can belong to more than one group.

    `Project.workspace_id` stays as the **home**: the one in the URL, the anchor
    that guarantees a project always lives somewhere. This table adds the others.
    An interdepartmental paper is genuinely shared, not a copy in two places, so
    there is one row in `projects` and several here.

    Consequence, and it is the whole point: sharing a project into a workspace
    gives that workspace's members access to it. That is why only someone with
    `write` in a workspace can put a project into it.
    """
    __tablename__ = "project_workspaces"
    __table_args__ = (UniqueConstraint("project_id", "workspace_id"),)
    id           = Column(Integer, primary_key=True)
    project_id   = Column(Integer, ForeignKey("projects.id"), nullable=False)
    workspace_id = Column(Integer, ForeignKey("workspaces.id"), nullable=False)
    created_at   = Column(DateTime, default=utcnow)

    project   = relationship("Project", back_populates="shares")
    workspace = relationship("Workspace")


class Authorship(Base):
    __tablename__ = "authorships"
    __table_args__ = (UniqueConstraint("project_id", "person_id"),)
    id         = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    person_id  = Column(Integer, ForeignKey("people.id"), nullable=False)
    role       = Column(String, default="co-author")
    position   = Column(Integer, default=0)

    project = relationship("Project", back_populates="authorships")
    person  = relationship("Person", back_populates="authorships")


class Submission(Base):
    """One attempt at one venue. A rejected-and-resubmitted paper is several
    rows, not several statuses (SPEC.md §1)."""
    __tablename__ = "submissions"
    id           = Column(Integer, primary_key=True)
    project_id   = Column(Integer, ForeignKey("projects.id"), nullable=False)
    venue        = Column(String, nullable=False)
    attempt      = Column(Integer, default=1)
    submitted_at = Column(DateTime, default=utcnow)
    outcome      = Column(String, default="pending")
    outcome_at   = Column(DateTime, nullable=True)
    notes        = Column(Text, nullable=True)

    project = relationship("Project", back_populates="submissions")

    @property
    def days_open(self) -> int | None:
        if self.outcome != "pending":
            return None
        return (utcnow() - (self.submitted_at or utcnow())).days


class Event(Base):
    """The spine. Everything derived (staleness, latency, dormancy, activity)
    is a query over this table. Never written by hand."""
    __tablename__ = "events"
    id          = Column(Integer, primary_key=True)
    project_id  = Column(Integer, ForeignKey("projects.id"), nullable=False)
    ts          = Column(DateTime, default=utcnow, index=True)
    user_id     = Column(Integer, ForeignKey("users.id"), nullable=True)
    type        = Column(String, nullable=False)
    from_status = Column(String, nullable=True)
    to_status   = Column(String, nullable=True)
    payload     = Column(Text, nullable=True)

    project = relationship("Project", back_populates="events")
    user    = relationship("User")


class Note(Base):
    __tablename__ = "notes"
    id         = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    ts         = Column(DateTime, default=utcnow)
    user_id    = Column(Integer, ForeignKey("users.id"), nullable=True)
    body_md    = Column(Text, nullable=False)
    source     = Column(String, default="web")   # web | mcp | notion-import
    author_label = Column(String, nullable=True)  # for imports: original author
    # Notion comment id, so a re-import updates instead of duplicating.
    external_id = Column(String, nullable=True, unique=True, index=True)

    project = relationship("Project", back_populates="notes")
    user    = relationship("User")


class Link(Base):
    """
    A pointer from a project to something else.

    `user_id` is the difference between "the project's link" and "my link".
    NULL means it belongs to the project and everyone who can see the project
    sees it — a DOI, a repo, a preprint. Set means it belongs to one person and
    only they see it: a path into a private wiki, an Obsidian vault, a Zotero
    collection. Those exist because the useful pointer is often into somewhere
    nobody else can reach, and a link nobody else can follow is not shared
    information, it is a leaked filename.

    This is not a second way to authorise. The workspace still decides who sees
    the project; this only decides which of its rows they are shown inside it.
    """
    __tablename__ = "links"
    id         = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    kind       = Column(String, nullable=False)
    target     = Column(String, nullable=False)
    label      = Column(String, nullable=True)
    created_at = Column(DateTime, default=utcnow)
    # NULL = the project's, shared. Set = personal, visible only to that user.
    user_id    = Column(Integer, ForeignKey("users.id"), nullable=True)

    project = relationship("Project", back_populates="links")


class Deadline(Base):
    __tablename__ = "deadlines"
    id         = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False)
    kind       = Column(String, nullable=True)
    due        = Column(DateTime, nullable=False)
    done_at    = Column(DateTime, nullable=True)
    note       = Column(Text, nullable=True)

    project = relationship("Project", back_populates="deadlines")


# ── access helpers ────────────────────────────────────────────────────────────

def workspaces_of(project) -> list:
    """Every workspace the project belongs to, home first."""
    out = [project.workspace] if project.workspace else []
    for sh in project.shares:
        if sh.workspace and sh.workspace.id not in {w.id for w in out}:
            out.append(sh.workspace)
    return out


def role_on_project(db, user, project) -> str | None:
    """
    The caller's role on a project: the best they hold in any workspace the
    project belongs to.

    A shared paper is one object. Someone who can edit it through ITE can edit
    it, full stop — refusing because they opened it from the DEH board would be
    arbitrary, and would make the same button work or not depending on the route
    taken to reach it.
    """
    best = None
    for ws in workspaces_of(project):
        r = role_for(db, user, ws)
        if r and (best is None or ROLE_RANK[r] > ROLE_RANK[best]):
            best = r
    return best


def role_for(db, user: User, workspace: Workspace) -> str | None:
    """The single source of truth for access. None means no access at all —
    callers turn that into a 404, never a 403."""
    if user is None or workspace is None:
        return None
    m = (db.query(Membership)
           .filter(Membership.user_id == user.id,
                   Membership.workspace_id == workspace.id)
           .first())
    return m.role if m else None


def has_role(role: str | None, minimum: str) -> bool:
    if role is None:
        return False
    return ROLE_RANK.get(role, 0) >= ROLE_RANK[minimum]


def user_workspaces(db, user: User) -> list[tuple[Workspace, str]]:
    rows = (db.query(Workspace, Membership.role)
              .join(Membership, Membership.workspace_id == Workspace.id)
              .filter(Membership.user_id == user.id)
              .order_by(Workspace.archived, Workspace.name)
              .all())
    return [(ws, role) for ws, role in rows]


def wiki_url(target: str) -> str | None:
    """
    Where a `wiki` link points on Onopedia, or None if it is not servable.

    The stored target stays the **repo-relative path**, which is the stable key
    (§8) and the one thing that still works with a checkout on disk. The URL is
    built for display instead of written into the row: rewriting targets would
    trade a key that works in two places for one that works in one.
    """
    base = os.environ.get("WIKI_BASE_URL", "").rstrip("/")
    t = (target or "").strip()
    if not base or not t.startswith("wiki/") or not t.endswith(".md"):
        return None
    return f"{base}/p/{t[len('wiki/'):-3]}"


def visible_links(project: "Project", user: User) -> list["Link"]:
    """
    The links this user may see on this project: the shared ones, plus their own.

    Every reader goes through here — the project page and the MCP alike. Putting
    the filter in the template instead would leave the MCP serving what the page
    hides, which is the third time that shape of mistake would have bitten
    (SPEC.md §8): the constraint belongs in the function that reads, not in the
    view that renders.
    """
    uid = user.id if user else None
    return [l for l in project.links if l.user_id is None or l.user_id == uid]


def personal_workspace(db, user: User) -> "Workspace | None":
    return (db.query(Workspace)
              .filter(Workspace.kind == "personal",
                      Workspace.owner_id == user.id).first())


def ensure_personal_workspace(db, user: User) -> "Workspace":
    """
    Every user gets one workspace of their own, created with the account.

    The alternative — letting a project belong to no workspace — was rejected:
    a project with no workspace has no access rule, so it would need a second
    authorisation path keyed on an owner, running alongside `role_for()`. That
    is the shape SPEC.md §3 forbids when it insists that null access is the
    absence of a row and never `role='none'`: two ways of saying the same thing,
    and one of them eventually escapes a check. The MCP, which goes through the
    same dependency, would inherit the hole.

    So a personal workspace is a plain Workspace with the owner as `admin`.
    Nothing in the ACL changes. Sharing later is `ProjectWorkspace`, which
    already exists: a project that starts as yours and becomes the group's is
    the same object in two groups, not a move.

    Idempotent — safe to call on every startup and on every account creation.
    """
    ws = personal_workspace(db, user)
    if ws is not None:
        return ws
    base = slugify(user.name) or slugify(user.email.split("@")[0])
    slug = base
    n = 2
    while db.query(Workspace).filter(Workspace.slug == slug).first():
        slug = f"{base}-{n}"
        n += 1
    ws = Workspace(slug=slug, name=user.name, kind="personal",
                   owner_id=user.id,
                   description="Personal workspace — work that is not a group's.")
    db.add(ws)
    db.flush()
    db.add(Membership(user_id=user.id, workspace_id=ws.id, role="admin",
                      created_by=user.id))
    return ws


# ── derived state ─────────────────────────────────────────────────────────────

def open_submission(project: Project) -> Submission | None:
    for s in sorted(project.submissions, key=lambda s: s.submitted_at or utcnow(),
                    reverse=True):
        if s.outcome == "pending":
            return s
    return None


def last_submission(project: Project) -> Submission | None:
    if not project.submissions:
        return None
    return max(project.submissions, key=lambda s: s.submitted_at or utcnow())


def effective_status(project: Project) -> dict:
    """
    Declared up to `ready`, computed past it (SPEC.md §5).

    Returns {label, detail, diverges} — `diverges` flags that the stored status
    disagrees with the submission record, so the UI can say so instead of
    silently overwriting either one.
    """
    declared = project.status
    label, detail, diverges = STATUS_LABELS.get(declared, declared), None, False

    if project.doi:
        label = "Published"
        diverges = declared not in ("published", "archived")
    else:
        s = open_submission(project)
        if s:
            # An attempt still open while the project sits in writing/active
            # means the paper is at that venue but back in the authors' hands:
            # a revision round. Same fact, different word, and the day count
            # keeps running because the venue still has it.
            back_with_authors = declared in ("writing", "active", "in_revision")
            label = "In revision" if back_with_authors else "Under review"
            detail = f"{s.venue} · {s.days_open}d"
            # Anything else is stale. `ready` with an open attempt is the common
            # one and the easiest to miss: you cannot be ready to submit
            # something that is already under review. It happens when the note
            # gets written and the card does not get moved, which is exactly the
            # drift this flag exists to surface.
            diverges = declared not in ("submitted", "in_revision",
                                        "writing", "active")
        else:
            last = last_submission(project)
            if last and last.outcome == "accept":
                label = "Accepted"
                detail = last.venue
                diverges = declared not in ("submitted", "ready", "published")
            elif last and last.outcome in ("desk_reject", "reject_after_review"):
                detail = f"bounced from {last.venue}"
    return {"label": label, "detail": detail, "diverges": diverges}


def last_event_at(project: Project) -> datetime | None:
    if not project.events:
        return project.created_at
    return max(e.ts for e in project.events if e.ts)


def is_dormant(project: Project, threshold_days: int) -> bool:
    if project.status in ("published", "archived"):
        return False
    last = last_event_at(project)
    if last is None:
        return False
    return (utcnow() - last).days >= threshold_days


def append_milestone(existing: str | None, outcome: str,
                     when: datetime | None = None) -> str:
    """A revision round recorded on the attempt it belongs to, without closing
    it: the paper is still at that venue and the clock is still running."""
    line = f"{(when or utcnow()):%Y-%m-%d}: {OUTCOME_LABELS.get(outcome, outcome)}"
    return "
".join(filter(None, [existing, line]))


def apply_outcome(db, submission: "Submission", outcome: str, user: User | None,
                  when: datetime | None = None) -> bool:
    """
    Record an outcome on an attempt, and move the project with it.

    Lives here, and not in a route, because there are two doors onto this
    operation and they had drifted apart: the MCP closed an attempt on
    `major_revision` (contradicting KEEPS_ATTEMPT_OPEN, §4) and never moved the
    project's status, so a paper accepted through the model-facing surface
    stayed `submitted` and showed up as a status mismatch. Two implementations
    of one rule is one implementation and one bug — the fourth time today that
    a constraint sat on the interface instead of on the function that writes.

    `when` is the date on the letter, which is not the date somebody got round
    to typing it in. Defaulting it to now is how a system whose every latency is
    a subtraction of two dates starts lying.
    """
    if outcome not in SUBMISSION_OUTCOMES:
        return False
    p = submission.project
    stamp = when or utcnow()
    if outcome in KEEPS_ATTEMPT_OPEN:
        submission.notes = append_milestone(submission.notes, outcome, stamp)
    else:
        submission.outcome = outcome
        submission.outcome_at = stamp if outcome != "pending" else None
    log_event(db, p, user, "submission_outcome",
              payload=json.dumps({"venue": submission.venue, "outcome": outcome,
                                  "attempt": submission.attempt,
                                  "closed": outcome not in KEEPS_ATTEMPT_OPEN}))
    # A closing outcome moves the card too: leaving it in `submitted` after a
    # rejection is the drift that produced the Smoking bans mismatch.
    if outcome not in KEEPS_ATTEMPT_OPEN and p.status in ("submitted",
                                                          "in_revision"):
        new = "published" if outcome == "accept" else "ready"
        log_event(db, p, user, "status_change", from_status=p.status,
                  to_status=new)
        p.status = new
    elif outcome in KEEPS_ATTEMPT_OPEN and p.status == "submitted":
        log_event(db, p, user, "status_change", from_status=p.status,
                  to_status="in_revision")
        p.status = "in_revision"
    return True


def log_event(db, project: Project, user: User | None, type_: str, *,
              from_status: str | None = None, to_status: str | None = None,
              payload: str | None = None) -> Event:
    ev = Event(project_id=project.id, user_id=(user.id if user else None),
               type=type_, from_status=from_status, to_status=to_status,
               payload=payload, ts=utcnow())
    db.add(ev)
    return ev


# ── controlled vocabularies ───────────────────────────────────────────────────
#
# Journal was a `select` in Notion — a closed list — and became free text here.
# That is a regression, and it shows up as statistics fragmenting across
# spellings: "heliyon" and "Helyon" are one journal that would answer the
# "how long does this venue take" question twice, each time wrongly. The fix is
# not validation (a genuinely new venue must always be typeable) but a vocabulary
# offered for picking, plus a snap to an existing spelling when the difference is
# only case or padding.

def known_venues(db, workspace) -> list[str]:
    """Every venue already used in this workspace, journals and submissions."""
    rows = (db.query(Submission.venue)
              .join(Project, Project.id == Submission.project_id)
              .filter(Project.workspace_id == workspace.id).all())
    journals = (db.query(Project.journal)
                  .filter(Project.workspace_id == workspace.id).all())
    seen = {v for (v,) in rows if v and v != "(unknown)"}
    seen |= {j for (j,) in journals if j}
    return sorted(seen, key=str.lower)


def known_people(db) -> list[str]:
    """The people registry, most-used first so the common names are on top."""
    return [p.name for p in
            sorted(db.query(Person).all(),
                   key=lambda p: (-len(p.authorships), p.name.lower()))]


def snap(value: str | None, vocabulary: list[str]) -> str | None:
    """
    Fold a typed value onto an existing one when they differ only in case or
    surrounding space. Anything genuinely new passes through untouched: the
    vocabulary guides, it does not gate.
    """
    if not value:
        return None
    v = " ".join(value.split())
    if not v:
        return None
    for known in vocabulary:
        if known.lower() == v.lower():
            return known
    return v


def slugify(value: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (value or "").lower()).strip("-")
    return s or secrets.token_hex(4)


# ── db plumbing ───────────────────────────────────────────────────────────────

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# Additive migrations: each entry runs on every startup and is ignored if the
# column already exists. Never drop, never rename (borant house pattern).
_MIGRATIONS = [
    "ALTER TABLE users ADD COLUMN last_login DATETIME",
    "ALTER TABLE users ADD COLUMN totp_secret_encrypted VARCHAR",
    "ALTER TABLE users ADD COLUMN totp_enabled BOOLEAN DEFAULT 0",
    "ALTER TABLE workspaces ADD COLUMN dormant_after_days INTEGER DEFAULT 180",
    "ALTER TABLE projects ADD COLUMN position INTEGER DEFAULT 0",
    "ALTER TABLE projects ADD COLUMN imported BOOLEAN DEFAULT 0",
    "ALTER TABLE notes ADD COLUMN author_label VARCHAR",
    "ALTER TABLE projects ADD COLUMN notion_id VARCHAR",
    "ALTER TABLE notes ADD COLUMN external_id VARCHAR",
    "ALTER TABLE projects ADD COLUMN output_type VARCHAR DEFAULT 'paper'",
    "ALTER TABLE projects ADD COLUMN deleted_at DATETIME",
    # Backfill the sharing table from the home workspace, once. `INSERT OR
    # IGNORE` plus the unique constraint makes re-running a no-op.
    "INSERT OR IGNORE INTO project_workspaces (project_id, workspace_id) "
    "SELECT id, workspace_id FROM projects",
    "ALTER TABLE api_keys ADD COLUMN last_used_at DATETIME",
    "CREATE UNIQUE INDEX IF NOT EXISTS ix_projects_notion_id ON projects (notion_id)",
    "CREATE UNIQUE INDEX IF NOT EXISTS ix_notes_external_id ON notes (external_id)",
    "ALTER TABLE links ADD COLUMN user_id INTEGER",
    "ALTER TABLE workspaces ADD COLUMN kind VARCHAR DEFAULT 'group'",
    "ALTER TABLE workspaces ADD COLUMN owner_id INTEGER",
    "UPDATE workspaces SET kind = 'group' WHERE kind IS NULL",
]


def init_db():
    os.makedirs("data", exist_ok=True)
    Base.metadata.create_all(bind=engine)
    with engine.connect() as conn:
        for stmt in _MIGRATIONS:
            try:
                conn.execute(text(stmt))
                conn.commit()
            except Exception:
                conn.rollback()   # column already there
