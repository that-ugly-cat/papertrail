"""
Fixes found by the audit after the reconstruction landed.

Root cause of most of them: `parse_submissions.py --apply` wrote venues raw,
bypassing the snap() that every other write path goes through. So the lowercase
forms lifted out of the comments ("nature", "heliyon") ended up beside the
properly cased ones that came from Notion's Journal select — one journal
answering the latency question twice.

    python migration/fix_venues.py --workspace ite [--apply]
"""
import argparse
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from models import (  # noqa: E402
    Project, SessionLocal, Submission, Workspace, log_event,
)

# Canonical spelling for every venue that exists in more than one form. Where
# Notion's Journal select already held a proper-cased version, that one wins;
# where it did not, the journal's real name does.
CANONICAL = {
    "accountability in research": "Accountability in Research",
    "bmj public health": "BMJ Public Health",
    "ethics and information technology": "Ethics and Information Technology",
    "heliyon": "Heliyon",
    "international journal of ethics education":
        "International Journal of Ethics Education",
    "lancet": "The Lancet",
    "nature": "Nature",
    "nature machine intelligence": "Nature Machine Intelligence",
    "science": "Science",
    "scientific reports": "Scientific Reports",
    # Abbreviations Spit used in his own notes, expanded to the names the rest
    # of the vocabulary already uses. Only the bare forms: AJOB Empirical
    # Bioethics, NEJM Catalyst and the JMIR family are separate journals and
    # must keep their own names.
    "eit": "Ethics and Information Technology",
    "ssm": "Social Science & Medicine",
    "pus": "Public Understanding of Science",
    "phe": "Public Health Ethics",
    "ajob": "American Journal of Bioethics",
    "nejm": "New England Journal of Medicine",
    "jmir": "Journal of Medical Internet Research",
    "jmir infodemiology": "JMIR Infodemiology",
    # A stray preposition the venue extractor left attached.
    "by nature human behavior": "Nature Human Behaviour",
    "nature human behavior": "Nature Human Behaviour",
}

# Published papers whose chain ends in a rejection: the accepted attempt at the
# venue on the card was never written in the comments, because by then the news
# had travelled elsewhere.
MISSING_ACCEPT = {
    47: ("Social theory and health", "2026-01-01"),
    54: ("Culturico", "2025-01-01"),
}

# "invoice sent to jole (bk)" — Jole is a person at the publisher, not a venue,
# and it was read as the accepting journal. The DOI settles it:
# 10.3389/ijph.2025.1608617 is the International Journal of Public Health, which
# is also the attempt right before, sitting closed as `unknown`. So: drop the
# phantom, and let the real attempt carry the acceptance.
DROP_VENUE_CLOSE_PREVIOUS = {
    59: ("JOLE", "International Journal of Public Health", "2025-05-15"),
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workspace", default="ite")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    db = SessionLocal()
    ws = db.query(Workspace).filter(Workspace.slug == args.workspace).first()
    if not ws:
        sys.exit(f"Workspace '{args.workspace}' inesistente.")
    P = db.query(Project).filter(Project.workspace_id == ws.id).all()

    renames, adds, jfix = [], [], []
    for p in P:
        for s in p.submissions:
            want = CANONICAL.get((s.venue or "").strip().lower())
            if want and want != s.venue:
                renames.append((s, s.venue, want))
        want_j = CANONICAL.get((p.journal or "").strip().lower())
        if want_j and want_j != p.journal:
            jfix.append((p, p.journal, want_j))
        if p.id in MISSING_ACCEPT:
            venue, when = MISSING_ACCEPT[p.id]
            if not any(x.outcome == "accept" for x in p.submissions):
                adds.append((p, venue, when))

    drops = []
    for p in P:
        if p.id in DROP_VENUE_CLOSE_PREVIOUS:
            bad, real, when = DROP_VENUE_CLOSE_PREVIOUS[p.id]
            ghost = next((s for s in p.submissions if s.venue == bad), None)
            target = next((s for s in p.submissions
                           if s.venue == real and s.outcome != "accept"), None)
            if ghost:
                drops.append((p, ghost, target, real, when))

    for p, ghost, target, real, when in drops:
        print(f"  drop    sub {ghost.id:3d}  {ghost.venue!r} non e' un venue; "
              f"accettazione spostata su {real}")

    print(f"{len(renames)} venue da uniformare, {len(jfix)} campi journal, "
          f"{len(adds)} accettazioni mancanti\n")
    for s, old, new in renames:
        print(f"  venue   sub {s.id:3d}  {old!r:42} → {new!r}")
    for p, old, new in jfix:
        print(f"  journal proj {p.id:3d}  {old!r:42} → {new!r}")
    for p, venue, when in adds:
        print(f"  accept  proj {p.id:3d}  {(p.final_title or p.title)[:34]:36} "
              f"→ {venue} ({when[:4]})")

    if not args.apply:
        print("\n(dry run: niente scritto. --apply per eseguire)")
        return

    for s, old, new in renames:
        s.venue = new
    for p, old, new in jfix:
        p.journal = new
    for p, ghost, target, real, when in drops:
        if target:
            target.outcome = "accept"
            target.outcome_at = datetime.fromisoformat(when)
            target.notes = "\n".join(filter(None, [
                target.notes,
                "[accettazione: 'invoice sent to jole' — Jole e' un contatto "
                "dell'editore, non una rivista; il DOI conferma questo venue]"]))
        db.delete(ghost)
        log_event(db, p, None, "submission_outcome",
                  payload='{"outcome": "accept", "source": "audit:jole"}')

    for p, venue, when in adds:
        n = len(p.submissions) + 1
        db.add(Submission(project_id=p.id, venue=venue, attempt=n,
                          submitted_at=datetime.fromisoformat(when),
                          outcome="accept",
                          outcome_at=datetime.fromisoformat(when),
                          notes="Accettazione dedotta: il progetto risulta "
                                "pubblicato qui, ma i commenti non la "
                                "registrano. Data approssimata all'anno."))
        log_event(db, p, None, "submission_outcome",
                  payload='{"outcome": "accept", "source": "audit"}')
    db.commit()
    print(f"\nFatto: {len(renames)} venue, {len(jfix)} journal, {len(adds)} accept.")


if __name__ == "__main__":
    main()
