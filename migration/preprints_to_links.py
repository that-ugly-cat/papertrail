"""
Preprints are not submissions.

arXiv, bioRxiv, OSF and friends are not venues: posting there is not an attempt
to publish, it is making a copy public while the real attempt runs somewhere
else — often literally in parallel, as in "in the meanwhile, submitted to ArXiv".

Recording them as Submission rows corrupts two things at once. The chain reads
as if the paper had been sent to one more journal, and the venue statistics grow
an entry for a server that never reviews or rejects anything. Worse, a preprint
attempt sits `pending` forever, so the board shows a paper as under review at
arXiv when it is actually under review at a journal.

So: each one becomes a Link(kind='preprint') plus, when the note that mentions
it does not already exist, a note carrying the date. The original comments are
untouched — they already say what happened, in Spit's own words.

    python migration/preprints_to_links.py --workspace ite [--apply]
"""
import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from models import (  # noqa: E402
    Link, Note, Project, SessionLocal, Workspace, init_db,
    log_event, utcnow,
)

PREPRINT_SERVER = re.compile(
    r"\barxiv\b|\bbiorxiv\b|\bmedrxiv\b|\bssrn\b|\bpsyarxiv\b|\bsocarxiv\b"
    r"|\bosf\b|\bresearch square\b|\bpreprints?\.org\b|\bpreprint\b", re.I)

URL_RE = re.compile(r"https?://[^\s)\]]+")


def server_name(text: str) -> str:
    """The canonical name of the server, for the link label."""
    for name in ("arXiv", "bioRxiv", "medRxiv", "SSRN", "PsyArXiv", "SocArXiv",
                 "OSF", "Research Square"):
        if re.search(rf"\b{name}\b", text, re.I):
            return name
    return "preprint"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workspace", default="ite")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    init_db()
    db = SessionLocal()
    ws = db.query(Workspace).filter(Workspace.slug == args.workspace).first()
    if not ws:
        sys.exit(f"Workspace '{args.workspace}' inesistente.")

    projects = db.query(Project).filter(Project.workspace_id == ws.id).all()
    planned = []

    for p in projects:
        existing = {l.target for l in p.links if l.kind == "preprint"}

        # 1. submissions that are really preprints
        for s in list(p.submissions):
            if s.venue and PREPRINT_SERVER.search(s.venue):
                planned.append(("submission→link", p, s,
                                server_name(s.venue), None))

        # 2. URLs to a preprint sitting in the notes
        for n in p.notes:
            for url in URL_RE.findall(n.body_md or ""):
                if PREPRINT_SERVER.search(url) and url not in existing:
                    planned.append(("url→link", p, None,
                                    server_name(url), url))
                    existing.add(url)

    print(f"{len(planned)} interventi\n")
    for kind, p, s, name, url in planned:
        detail = url or (f"tentativo {s.attempt}, {s.outcome}" if s else "")
        print(f"  {kind:16} [{p.status:9}] {(p.final_title or p.title)[:42]:44} "
              f"{name:14} {detail[:46]}")

    if not args.apply:
        print("\n(dry run: niente scritto. --apply per eseguire)")
        return

    for kind, p, s, name, url in planned:
        if kind == "submission→link":
            when = s.submitted_at
            db.add(Link(project_id=p.id, kind="preprint",
                        target=url or name, label=name))
            # The imported comment already records this in Spit's words; a note
            # is only added when nothing says it.
            said = any(PREPRINT_SERVER.search(n.body_md or "") for n in p.notes)
            if not said:
                db.add(Note(project_id=p.id, source="migration",
                            ts=when or utcnow(),
                            body_md=f"Preprint su {name}"
                                    f"{when and ' il ' + when.strftime('%d/%m/%Y') or ''}."))
            log_event(db, p, None, "link_added",
                      payload=f'{{"kind": "preprint", "from": "submission {s.id}"}}')
            db.delete(s)
        else:
            db.add(Link(project_id=p.id, kind="preprint", target=url,
                        label=name))
            log_event(db, p, None, "link_added",
                      payload='{"kind": "preprint", "from": "note"}')

    db.flush()

    # A real attempt may have been closed as `unknown` only because the preprint
    # looked like a later submission superseding it. Sycophancy is exactly that:
    # "23.03.2026: in peer review" at Computers & Education Open, then closed
    # because arXiv followed on 14/05. The paper never left that journal — the
    # supersession was an artefact of treating a preprint as an attempt.
    reopened = 0
    for kind, p, s, name, url in planned:
        if kind != "submission→link" or not s.submitted_at:
            continue
        stamp = s.submitted_at.strftime("%d/%m/%Y")
        for other in p.submissions:
            if other.outcome == "unknown" and stamp in (other.notes or ""):
                other.outcome = "pending"
                other.outcome_at = None
                other.notes = ((other.notes or "") +
                               "\n[riaperta: la 'supersessione' era il preprint, "
                               "non una submission successiva]")
                reopened += 1

    # attempt numbers close up after a removal
    for p in projects:
        for i, s in enumerate(sorted(p.submissions,
                                     key=lambda x: x.submitted_at or utcnow()), 1):
            s.attempt = i
    db.commit()
    if reopened:
        print(f"{reopened} tentativi riaperti: erano stati chiusi perche' il "
              f"preprint sembrava una submission successiva.")
    print(f"\nFatto: {len(planned)} preprint spostati fuori dalle submission.")


if __name__ == "__main__":
    main()
