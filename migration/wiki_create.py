"""
Crea un progetto a partire da una pagina wiki che non ha corrispondente in
PaperTrail, e la aggancia.

Secondo braccio della riconciliazione manuale (vedi `wiki_link.py` per il primo:
la pagina che un progetto ce l'ha già). Le pagine nate dopo il congelamento
della scatola Notion non hanno nulla da riconciliare — vanno create.

    python migration/wiki_create.py \
        --title "AI Coding Turing Test" --status developed \
        --wiki wiki/projects/pubblicazioni/pagina.md --label "..." \
        --lead "Giovanni Spitale" --author "Federico Germani"

Stampa l'id assegnato. Non è idempotente: rilanciarlo crea un secondo progetto.
"""
import argparse
import sys

sys.path.insert(0, "/app")

from models import (SessionLocal, Project, Link, Authorship, Note, User,
                    Workspace, STATUSES, get_or_create_person, log_event)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workspace", default="ite")
    ap.add_argument("--title", required=True)
    ap.add_argument("--status", default="idea")
    ap.add_argument("--output-type", default="paper")
    ap.add_argument("--summary", default=None)
    ap.add_argument("--journal", default=None)
    ap.add_argument("--doi", default=None)
    ap.add_argument("--pub-year", type=int, default=None)
    ap.add_argument("--wiki", default=None, help="path repo-relative")
    ap.add_argument("--label", default=None)
    ap.add_argument("--lead", action="append", default=[])
    ap.add_argument("--author", action="append", default=[])
    ap.add_argument("--note", action="append", default=[])
    ap.add_argument("--actor", default="giovanni.spitale@ibme.uzh.ch")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if args.status not in STATUSES:
        print(f"ERRORE: stato '{args.status}' fuori vocabolario: {STATUSES}")
        return 1

    db = SessionLocal()
    try:
        ws = db.query(Workspace).filter(Workspace.slug == args.workspace).first()
        if ws is None:
            print(f"ERRORE: workspace '{args.workspace}' inesistente")
            return 1
        actor = db.query(User).filter(User.email == args.actor).first()

        p = Project(workspace_id=ws.id, title=args.title.strip(),
                    status=args.status, output_type=args.output_type,
                    summary=args.summary, journal=args.journal,
                    doi=args.doi, pub_year=args.pub_year,
                    created_by=(actor.id if actor else None), position=0)
        db.add(p)
        db.flush()
        log_event(db, p, actor, "created", to_status=args.status)
        print(f"progetto {p.id} — {p.title} [{p.status}/{p.output_type}]")

        pos = 0
        for role, names in (("lead", args.lead), ("co-author", args.author)):
            for name in names:
                person = get_or_create_person(db, name)
                db.add(Authorship(project_id=p.id, person_id=person.id,
                                  role=role, position=pos))
                log_event(db, p, actor, "authorship_changed",
                          payload=f"added {person.name} ({role})")
                print(f"  + {role}: {person.name}")
                pos += 1

        if args.wiki:
            db.add(Link(project_id=p.id, kind="wiki",
                        target=args.wiki, label=args.label))
            log_event(db, p, actor, "link_added", payload=f"wiki: {args.wiki}")
            print(f"  + link wiki → {args.wiki}")

        for body in args.note:
            db.add(Note(project_id=p.id, user_id=(actor.id if actor else None),
                        body_md=body.strip(), source="web"))
            log_event(db, p, actor, "note_added")
            print(f"  + nota: {body.strip()[:60]}…")

        if args.dry_run:
            db.rollback()
            print("  [dry-run — niente scritto]")
        else:
            db.commit()
            print(f"  ok, committato — id {p.id}")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
