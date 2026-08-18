"""
Aggancia una pagina wiki a un progetto esistente, e all'occorrenza ne corregge
i campi o ne aggiunge i co-autori.

Passo manuale della riconciliazione wiki (SPEC §8, Fase 5): la prosa resta nel
wiki — il 71% dei suoi link esce verso concetti e tensioni, che PaperTrail non
modella — e qui entra solo il puntatore.

    python migration/wiki_link.py 31 \
        wiki/projects/pubblicazioni/pagina.md \
        --label "Titolo della pagina" \
        --author "Nikola Biller-Andorno" \
        --rename "Titolo migliore" --summary "..."

Idempotente: rilanciarlo non duplica né il link né gli autori, e un campo già
al valore giusto non produce un `field_changed` finto.
"""
import argparse
import sys

sys.path.insert(0, "/app")

from models import (SessionLocal, Project, Link, Authorship, Note, User,
                    get_or_create_person, log_event)

FIELDS = ("title", "final_title", "summary", "output_type", "journal",
          "doi", "pub_year")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("project_id", type=int)
    ap.add_argument("wiki_path", help="path repo-relative dentro Ono3")
    ap.add_argument("--label", default=None)
    ap.add_argument("--author", action="append", default=[],
                    help="co-autore da aggiungere; ripetibile")
    ap.add_argument("--role", default="co-author")
    ap.add_argument("--rename", default=None, help="nuovo Project.title")
    ap.add_argument("--final-title", default=None)
    ap.add_argument("--summary", default=None)
    ap.add_argument("--output-type", default=None)
    ap.add_argument("--journal", default=None)
    ap.add_argument("--doi", default=None)
    ap.add_argument("--pub-year", type=int, default=None)
    ap.add_argument("--link", action="append", default=[], metavar="KIND=TARGET",
                    help="link non-wiki, es. lssr=https://… ; ripetibile")
    ap.add_argument("--note", action="append", default=[],
                    help="nota da aggiungere; ripetibile. Non duplica un testo identico")
    ap.add_argument("--actor", default="giovanni.spitale@ibme.uzh.ch")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    db = SessionLocal()
    try:
        p = db.get(Project, args.project_id)
        if p is None:
            print(f"ERRORE: progetto {args.project_id} inesistente")
            return 1
        actor = db.query(User).filter(User.email == args.actor).first()
        print(f"progetto {p.id} — {p.title}")

        updates = dict(zip(FIELDS, (args.rename, args.final_title, args.summary,
                                    args.output_type, args.journal, args.doi,
                                    args.pub_year)))
        for attr, val in updates.items():
            if val is None:
                continue
            old = getattr(p, attr)
            if old == val:
                print(f"  = {attr} già a questo valore")
                continue
            setattr(p, attr, val)
            log_event(db, p, actor, "field_changed",
                      payload=f"{attr}: {old!r} -> {val!r}")
            print(f"  ~ {attr}: {str(old)[:40]!r} -> {str(val)[:60]!r}")

        existing = {(l.kind, l.target) for l in p.links}
        if ("wiki", args.wiki_path) in existing:
            print(f"  = link wiki già presente: {args.wiki_path}")
        else:
            db.add(Link(project_id=p.id, kind="wiki",
                        target=args.wiki_path, label=args.label))
            log_event(db, p, actor, "link_added",
                      payload=f"wiki: {args.wiki_path}")
            print(f"  + link wiki → {args.wiki_path}")

        for spec in args.link:
            kind, _, target = spec.partition("=")
            kind, target = kind.strip(), target.strip()
            if not target:
                print(f"  ! link malformato, serve KIND=TARGET: {spec!r}")
                continue
            if (kind, target) in existing:
                print(f"  = link {kind} già presente")
                continue
            db.add(Link(project_id=p.id, kind=kind, target=target))
            log_event(db, p, actor, "link_added", payload=f"{kind}: {target}")
            print(f"  + link {kind} → {target}")

        if args.author:
            have = {a.person_id for a in p.authorships}
            nextpos = max([a.position or 0 for a in p.authorships], default=0)
            for name in args.author:
                person = get_or_create_person(db, name)
                if person.id in have:
                    print(f"  = autore già presente: {person.name}")
                    continue
                nextpos += 1
                db.add(Authorship(project_id=p.id, person_id=person.id,
                                  role=args.role, position=nextpos))
                log_event(db, p, actor, "authorship_changed",
                          payload=f"added {person.name} ({args.role})")
                print(f"  + autore: {person.name} ({args.role}, pos {nextpos})")

        for body in args.note:
            body = body.strip()
            if any((n.body_md or "").strip() == body for n in p.notes):
                print("  = nota identica già presente")
                continue
            db.add(Note(project_id=p.id, user_id=(actor.id if actor else None),
                        body_md=body, source="web"))
            log_event(db, p, actor, "note_added")
            print(f"  + nota: {body[:60]}…")

        if args.dry_run:
            db.rollback()
            print("  [dry-run — niente scritto]")
        else:
            db.commit()
            print("  ok, committato")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
