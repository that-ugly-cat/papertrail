"""
Import the Notion "Scatola delle idee" into a PaperTrail workspace.

Source of truth is the Notion API, not the markdown/CSV export: querying the
database gives properties, page ids, created_time and last_edited_time in one
pass, so nothing has to be joined back to filenames.

Idempotent. Projects are keyed by `notion_id` and notes by the Notion comment
id, so re-running updates instead of duplicating. Run it as many times as you
like while Notion is still the live system.

Design decisions worth knowing before reading the code:

  * Statuses map per SPEC.md §6. Nothing is auto-archived: a page nobody has
    touched in two years still arrives as `idea`, with its real date. Dormancy
    makes it filterable without deleting anything.

  * The `imported` event is backdated to Notion's last_edited_time, NOT to the
    moment of import. Stamping it "now" would reset every project's clock and
    leave the board with nothing dormant for six months — which is exactly the
    blindness this tool exists to remove.

  * Submitted / In review / Accepted become a real Submission row plus status
    `submitted`, because in PaperTrail a submission is an entity and not a
    column.

Usage:
    python migration/notion_import.py --workspace ite --dry-run
    python migration/notion_import.py --workspace ite
"""
import argparse
import json
import sys
import urllib.request
from collections import Counter
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from notion_probe import (  # noqa: E402
    API, NOTION_VERSION, TOKEN, call, resolve_user, user_directory,
)
from models import (  # noqa: E402
    Authorship, Link, Note, Project, SessionLocal, Submission, Workspace,
    get_or_create_person, init_db, log_event, utcnow,
)

DATABASE_ID = "8436bbff-584f-47ab-9b8d-c05b4a6cbe44"

# SPEC.md §6. Submitted / In review / Accepted also open a Submission row.
STATUS_MAP = {
    "Idea":                 "idea",
    "Developed idea":       "developed",
    "Data collection":      "active",
    "Analysis":             "active",
    "Writing up":           "writing",
    "Ready for submission": "ready",
    "Submitted":            "submitted",
    "In review":            "submitted",
    "Accepted":             "submitted",
    "Published":            "published",
    "Archived":             "archived",
}
OPENS_SUBMISSION = {"Submitted": "pending", "In review": "pending",
                    "Accepted": "accept"}


def post(path: str, body: dict) -> dict:
    req = urllib.request.Request(f"{API}/{path}", method="POST",
                                 data=json.dumps(body).encode())
    req.add_header("Authorization", f"Bearer {TOKEN}")
    req.add_header("Notion-Version", NOTION_VERSION)
    req.add_header("Content-Type", "application/json")
    import time
    try:
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read().decode())
    finally:
        time.sleep(0.35)


def ts(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)


def prop(page: dict, name: str):
    return page.get("properties", {}).get(name, {})


def text_of(p: dict) -> str | None:
    kind = p.get("type")
    if kind in ("rich_text", "title"):
        out = "".join(t.get("plain_text", "") for t in p.get(kind, []))
        return out.strip() or None
    if kind == "select":
        return (p.get("select") or {}).get("name")
    if kind == "status":
        return (p.get("status") or {}).get("name")
    if kind == "url":
        return p.get("url") or None
    if kind == "number":
        return p.get("number")
    if kind == "date":
        return (p.get("date") or {}).get("start")
    return None


def people_of(p: dict, directory: dict) -> list[str]:
    return [resolve_user(u.get("id"), directory) for u in p.get("people", [])]


def fetch_rows() -> list[dict]:
    rows, cursor = [], None
    while True:
        body = {"page_size": 100}
        if cursor:
            body["start_cursor"] = cursor
        data = post(f"databases/{DATABASE_ID}/query", body)
        rows.extend(data.get("results", []))
        if not data.get("has_more"):
            break
        cursor = data.get("next_cursor")
    return rows


def fetch_comments(page_id: str) -> list[dict]:
    out, cursor = [], None
    while True:
        params = f"?block_id={page_id}&page_size=100"
        if cursor:
            params += f"&start_cursor={cursor}"
        data = call("comments", params)
        if not data or "_error" in data:
            break
        out.extend(data.get("results", []))
        if not data.get("has_more"):
            break
        cursor = data.get("next_cursor")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workspace", default="ite")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int)
    args = ap.parse_args()

    init_db()
    db = SessionLocal()
    ws = db.query(Workspace).filter(Workspace.slug == args.workspace).first()
    if not ws:
        sys.exit(f"Workspace '{args.workspace}' inesistente. Crealo prima.")

    directory = user_directory()
    print("Interrogo il database Notion…")
    rows = fetch_rows()
    if args.limit:
        rows = rows[: args.limit]
    print(f"{len(rows)} righe.\n")

    stats = Counter()
    for i, page in enumerate(rows, 1):
        pid = page["id"]
        title = text_of(prop(page, "Name")) or "(senza titolo)"
        notion_status = text_of(prop(page, "Status")) or "Idea"
        status = STATUS_MAP.get(notion_status, "idea")
        created = ts(page.get("created_time"))
        edited = ts(page.get("last_edited_time"))

        existing = db.query(Project).filter(Project.notion_id == pid).first()
        if existing:
            p = existing
            stats["aggiornati"] += 1
        else:
            p = Project(workspace_id=ws.id, notion_id=pid, imported=True,
                        created_at=created or utcnow())
            db.add(p)
            stats["creati"] += 1

        p.title = title
        p.status = status
        p.final_title = text_of(prop(page, "Final title"))
        p.summary = text_of(prop(page, "Summary"))
        p.journal = text_of(prop(page, "Journal"))
        p.doi = text_of(prop(page, "DOI/link"))
        year = text_of(prop(page, "Publication year"))
        p.pub_year = int(year) if year else None
        stats[f"stato:{status}"] += 1

        if args.dry_run:
            if i <= 8:
                print(f"  {title[:46]:46} {notion_status:20} -> {status}")
            continue

        db.flush()

        # ── authorship ───────────────────────────────────────────────────────
        managers = people_of(prop(page, "Managed by"), directory)
        for pos, name in enumerate(managers):
            person = get_or_create_person(db, name)
            if person and not any(a.person_id == person.id for a in p.authorships):
                db.add(Authorship(project_id=p.id, person_id=person.id,
                                  role="lead", position=pos))
                stats["autori"] += 1

        # ── DOI as a link, on top of the field ───────────────────────────────
        if p.doi and not any(l.kind == "doi" for l in p.links):
            db.add(Link(project_id=p.id, kind="doi", target=p.doi))
            stats["link"] += 1

        # ── submission, where the Notion status implied one ──────────────────
        outcome = OPENS_SUBMISSION.get(notion_status)
        if outcome and not p.submissions:
            db.add(Submission(project_id=p.id, venue=p.journal or "(unknown)",
                              attempt=1, submitted_at=edited or created or utcnow(),
                              outcome=outcome,
                              outcome_at=edited if outcome == "accept" else None,
                              notes="Ricostruita dallo stato Notion "
                                    f"'{notion_status}': data e venue sono "
                                    "un'approssimazione."))
            stats["submission"] += 1

        # ── comments become notes, keeping author and original timestamp ─────
        for c in fetch_comments(pid):
            cid = c["id"]
            if db.query(Note).filter(Note.external_id == cid).first():
                continue
            body = "".join(t.get("plain_text", "") for t in c.get("rich_text", []))
            if not body.strip():
                continue
            db.add(Note(project_id=p.id, external_id=cid, source="notion-import",
                        ts=ts(c.get("created_time")) or utcnow(),
                        author_label=resolve_user(
                            c.get("created_by", {}).get("id"), directory),
                        body_md=body))
            stats["note"] += 1

        # ── events: real dates, so dormancy is honest from day one ───────────
        if not p.events:
            # Use log_event's return value: p.events is not populated until the
            # session flushes, so indexing it here would hit an empty list.
            ev = log_event(db, p, None, "created", to_status=status)
            ev.ts = created or utcnow()
            ev = log_event(db, p, None, "imported",
                           payload=json.dumps({"notion_id": pid,
                                               "notion_status": notion_status}))
            ev.ts = edited or created or utcnow()
            stats["eventi"] += 2

        db.commit()
        if i % 20 == 0:
            print(f"  … {i}/{len(rows)}")

    print("\n" + "=" * 56)
    for k, v in sorted(stats.items()):
        print(f"  {k:22} {v}")
    if args.dry_run:
        print("\n(dry run: niente scritto)")
    db.close()


if __name__ == "__main__":
    main()
