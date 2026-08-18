"""
Reconstruct the submission history buried in the imported Notion comments.

Spit kept the submission cycle by hand, in the comments, for years:

    02.01.2026: submitted to Technology in Society (Elsevier)
    09.01.2026: rejected by Technology in Society
    12.01.2026: submitted to Human-Computer interaction (Taylor & Francis)

This turns that prose into Submission rows with real dates and venues, so the
per-journal latencies of Fase 3 have data from day one instead of in a year.

It is heuristic parsing of free text, so it NEVER writes on its own. The default
run produces a proposal (`submissions_proposal.json` + a readable table) for
review; only `--apply` writes, and even then the original notes are untouched,
so nothing is lost if the parse got something wrong.

Confidence is reported per event, and reflects two things: whether the date came
from the text itself or only from the comment timestamp, and whether a venue was
found. Anything below `high` is worth a human glance.

Usage:
    python migration/parse_submissions.py --workspace ite            # proposal
    python migration/parse_submissions.py --workspace ite --verbose  # every event
    python migration/parse_submissions.py --workspace ite --apply    # write
"""
import argparse
import json
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from models import (  # noqa: E402
    Note, Project, SessionLocal, Submission, Workspace, init_db, log_event,
    utcnow,
)

# ── vocabulary, drawn from the actual corpus rather than invented ─────────────

# Order matters: the first pattern that matches an event clause wins, so the
# more specific ones (resubmit, desk reject) come before the generic ones.
ACTIONS = [
    # Revision comes first on purpose. "review 1 submitted", "review 1 done",
    # "review submitted 24.02" mean the response to the reviewers went back: a
    # milestone inside the attempt that is already open, never a new submission.
    # "to revise and resubmit" would otherwise be caught by `resubmit` below and
    # would open a phantom attempt.
    ("revision", r"\brevise and resubmit\b|\bmajor revision\b|\bminor revision\b"
                 r"|\bto revise\b|\breviews? (?:received|back)\b|\bgot reviews?\b"
                 r"|\breview\s*\d*\s*(?:submitted|done|sent|completed)\b"
                 r"|\breview round\s*\d*\b"),
    ("resubmit", r"\bre-?submit(?:ted|ting)?\b"),
    ("desk_reject", r"\bdesk[- ]?reject(?:ed|ion)?\b"),
    ("reject", r"\breject(?:ed|ion|s)?\b|\bdeclin(?:ed|e)\b|\bnot? answer\b"),
    ("accept", r"\baccept(?:ed|ance)?\b"),
    ("withdraw", r"\bwithdraw(?:n|ing)?\b"),
    ("in_review", r"\bin peer review\b|\bunder review\b|\bin review\b"),
    ("submit", r"\bsubmit(?:ted|ting)?\b|\bsumbitted\b|\bsent to\b"),
]

DATE_RE = re.compile(r"\b(\d{1,2})[./](\d{1,2})(?:[./](\d{2,4}))?\b")

# Venue follows a preposition, or sits in parentheses in "Submitted by X (Venue)".
VENUE_AFTER = re.compile(
    r"\b(?:to|by|from|with|at)\s+([^,;.()]{2,60}?)"
    r"(?=\s*(?:[,;.()]|$|\bafter\b|\bfor\b))", re.I)
VENUE_PAREN = re.compile(r"\(([^)]{2,60})\)")

# Publisher tails that are not the venue name.
PUBLISHERS = re.compile(
    r"^(elsevier|springer|wiley|taylor ?& ?francis|sage|nature portfolio|mdpi|"
    r"frontiers media|oxford|cambridge)$", re.I)

# Words that follow "to"/"by" but are never a journal.
NOT_A_VENUE = re.compile(
    r"^(me|us|them|him|her|it|the editor|editor|reviewers?|\d+|whatever reason|"
    r"revise|resubmit|be|being|have|has|do|a|an|the)$", re.I)

# Pasted rejection e-mails and narrative asides produce plausible-looking noise
# ("the end of this email", "2 other reviweers", "several factors"). A venue is
# a journal name, so anything that reads like a sentence fragment is discarded.
VENUE_NOISE = re.compile(
    r"\b(e-?mail|conversation|reviewers?|factors?|reason|manuscript|paper|"
    r"decision|editor|colleagues?|preprint|comments?|feedback|version|"
    r"submission|attention|regret|inform|consideration|we|you|your|our|they|"
    r"their|this|that|these|those|which|because|whatever|other|another)\b",
    re.I)


def norm_year(y: str | None, fallback: datetime) -> int:
    if not y:
        return fallback.year
    y = int(y)
    if y < 100:
        return 2000 + y
    return y


def parse_date(text: str, fallback: datetime) -> tuple[datetime | None, bool]:
    """(date, came_from_text). Falls back to the comment's own timestamp."""
    m = DATE_RE.search(text)
    if not m:
        return fallback, False
    day, month, year = m.group(1), m.group(2), m.group(3)
    try:
        return datetime(norm_year(year, fallback), int(month), int(day)), True
    except ValueError:
        return fallback, False


def clean_venue(v: str | None) -> str | None:
    if not v:
        return None
    v = " ".join(v.split()).strip(" .,:;\"'")
    # Keep "Journal of X" intact; only drop a bare leading "the".
    v = re.sub(r"^the\s+", "", v, flags=re.I)
    v = re.sub(r"^of\s+", "Journal of ", v, flags=re.I)
    # "Public Health Ethics by Simone" — the sender rides along with the venue.
    v = re.sub(r"\s+by\s+\S+\s*$", "", v, flags=re.I).strip()
    if not v or len(v) < 3:
        return None
    if NOT_A_VENUE.match(v) or PUBLISHERS.match(v) or VENUE_NOISE.search(v):
        return None
    # A journal name is a few words, not a clause.
    if len(v.split()) > 8:
        return None
    return v


def find_venue(clause: str, action: str) -> str | None:
    """
    Which preposition carries the venue depends on the verb.

    "submitted by Simone (Tobacco Control)" — after a submit, "by" names the
    person who sent it, and the venue is in the parentheses. After a rejection,
    "rejected by The Lancet" is the normal phrasing and "by" is exactly right.
    """
    preps = r"to|at" if action in ("submit", "resubmit") else r"to|by|from|at"
    m = re.search(
        rf"\b(?:{preps})\s+([^,;.()]{{2,60}}?)"
        r"(?=\s*(?:[,;.()]|$|\bafter\b|\bfor\b))", clause, re.I)
    v = clean_venue(m.group(1)) if m else None
    if v:
        return v
    for cand in VENUE_PAREN.findall(clause):
        # "(by Simone)" names the sender, "(23.10.25)" is a date. Neither is a
        # venue, and both sit exactly where a venue would.
        if re.match(r"\s*by", cand, re.I) or DATE_RE.fullmatch(cand.strip()):
            continue
        v = clean_venue(cand)
        if v:
            return v
    return None


def split_clauses(body: str) -> list[str]:
    """
    One comment can hold several events:
        "rejected by Science (11.8.25), submitted to Nature (18.8.25)"
        "submitted heliyon review submitted 24.02.2026 rejected 08.04.2026"
    Split on separators, then again before any verb that starts a new event.
    """
    parts = re.split(r"[;\n]|,(?=\s*\d{0,2}[.\s]*(?:re-?submit|reject|accept))",
                     body)
    out = []
    for p in parts:
        pieces = re.split(
            r"(?=\b(?:re-?submitted|rejected|accepted|withdrawn|submitted)\b)",
            p, flags=re.I)
        out.extend(x for x in pieces if x.strip())
    return out or [body]


def classify(clause: str) -> str | None:
    for name, pattern in ACTIONS:
        if re.search(pattern, clause, re.I):
            return name
    return None


def events_from_note(note: Note) -> list[dict]:
    body = " ".join(note.body_md.split())
    out = []
    for clause in split_clauses(body):
        action = classify(clause)
        if not action:
            continue
        when, from_text = parse_date(clause, note.ts)
        # A clause with no date of its own inherits the comment's date, which is
        # usually right: these were written as they happened.
        venue = find_venue(clause, action)
        if from_text and venue:
            conf = "high"
        elif from_text or venue:
            conf = "medium"
        else:
            conf = "low"
        out.append({"action": action, "date": when, "venue": venue,
                    "confidence": conf, "note_id": note.id,
                    "raw": clause.strip()[:120]})
    return out


CLOSERS = {"reject": "reject_after_review", "desk_reject": "desk_reject",
           "accept": "accept", "withdraw": "withdrawn"}


def build_chain(events: list[dict]) -> list[dict]:
    """
    Turn a stream of events into submission attempts.

    A submit/resubmit opens an attempt; the next closing event (reject, accept,
    withdraw) closes the most recent open one. A closing event with no open
    attempt still produces a row, because "rejected by The Lancet" is evidence a
    submission happened even when nobody wrote down the sending.
    """
    events.sort(key=lambda e: e["date"] or utcnow())
    chain, open_attempt = [], None
    for e in events:
        if e["action"] in ("submit", "resubmit"):
            # A new attempt opening while another is still open means the first
            # one's outcome was never written down. Marking it rejected would be
            # a guess, so it stays pending but is flagged: an attempt superseded
            # months ago must not read as "in review since 400 days".
            if open_attempt and open_attempt["outcome"] == "pending":
                open_attempt["superseded_by"] = (
                    e["date"].strftime("%d/%m/%Y") if e["date"] else "?")
                open_attempt["confidence"] = "low"
            open_attempt = {"venue": e["venue"], "submitted_at": e["date"],
                            "outcome": "pending", "outcome_at": None,
                            "confidence": e["confidence"], "evidence": [e["raw"]]}
            chain.append(open_attempt)
        elif e["action"] in CLOSERS:
            if open_attempt and open_attempt["outcome"] == "pending":
                open_attempt["outcome"] = CLOSERS[e["action"]]
                open_attempt["outcome_at"] = e["date"]
                open_attempt["evidence"].append(e["raw"])
                if not open_attempt["venue"] and e["venue"]:
                    open_attempt["venue"] = e["venue"]
                open_attempt = None
            else:
                chain.append({"venue": e["venue"], "submitted_at": None,
                              "outcome": CLOSERS[e["action"]],
                              "outcome_at": e["date"],
                              "confidence": "low", "evidence": [e["raw"]]})
        elif e["action"] in ("revision", "in_review") and open_attempt:
            open_attempt["evidence"].append(e["raw"])
    for i, a in enumerate(chain, 1):
        a["attempt"] = i
    return chain


REVIEW_COLUMNS = ["ok", "venue_corretto", "progetto", "tentativo", "inviato",
                  "venue_proposto", "esito", "esito_il", "confidenza",
                  "superata_da", "evidenza", "project_id"]


def write_review_csv(proposal: list[dict]) -> Path:
    """
    The corpus is too irregular for the venue extraction to be trusted: roughly
    one in three comes out wrong. So the parse ends in a spreadsheet rather than
    in the database — correct the two leftmost columns and feed it back with
    --from-csv. A wrong submission history is worse than none, because it is
    precisely what the latency statistics would be computed from.
    """
    import csv
    path = Path(__file__).parent / "submissions_review.csv"
    with path.open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh, delimiter=";")
        w.writerow(REVIEW_COLUMNS)
        for row in sorted(proposal, key=lambda x: x["title"].lower()):
            for a in row["attempts"]:
                w.writerow([
                    "", "", row["title"], a["attempt"],
                    (a["submitted_at"] or "")[:10] if isinstance(a["submitted_at"], str)
                    else (a["submitted_at"].strftime("%Y-%m-%d") if a["submitted_at"] else ""),
                    a["venue"] or "", a["outcome"],
                    (a["outcome_at"] or "")[:10] if isinstance(a["outcome_at"], str)
                    else (a["outcome_at"].strftime("%Y-%m-%d") if a["outcome_at"] else ""),
                    a["confidence"], a.get("superseded_by", ""),
                    " | ".join(a["evidence"])[:300], row["project_id"],
                ])
    return path


def apply_from_csv(db, path: Path) -> int:
    """Write only the rows marked ok, using the corrected venue where given."""
    import csv
    written, skipped = 0, 0
    by_project: dict[int, list[dict]] = {}
    with path.open(encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh, delimiter=";"):
            if (r.get("ok") or "").strip().lower() not in ("x", "1", "si", "sì", "y", "yes"):
                skipped += 1
                continue
            by_project.setdefault(int(r["project_id"]), []).append(r)

    for pid, rows in by_project.items():
        p = db.query(Project).filter(Project.id == pid).first()
        if not p:
            continue
        for s in list(p.submissions):
            if s.notes and ("Ricostruita dallo stato Notion" in s.notes
                            or "Ricostruita dai commenti" in s.notes):
                db.delete(s)
        for i, r in enumerate(sorted(rows, key=lambda x: int(x["tentativo"])), 1):
            venue = (r.get("venue_corretto") or "").strip() or \
                    (r.get("venue_proposto") or "").strip() or "(unknown)"
            sub = datetime.strptime(r["inviato"], "%Y-%m-%d") if r.get("inviato") else None
            out = datetime.strptime(r["esito_il"], "%Y-%m-%d") if r.get("esito_il") else None
            db.add(Submission(project_id=p.id, venue=venue, attempt=i,
                              submitted_at=sub or out or utcnow(),
                              outcome=r["esito"], outcome_at=out,
                              notes="Ricostruita dai commenti Notion, "
                                    "rivista a mano.\n" + (r.get("evidenza") or "")))
            written += 1
        log_event(db, p, None, "submission_opened",
                  payload=json.dumps({"source": "parse_submissions:csv",
                                      "attempts": len(rows)}))
        db.commit()
    print(f"  righe non marcate ok, ignorate: {skipped}")
    return written


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workspace", default="ite")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--from-csv", action="store_true",
                    help="applica submissions_review.csv, solo le righe con ok")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    if args.from_csv:
        init_db()
        db = SessionLocal()
        path = Path(__file__).parent / "submissions_review.csv"
        if not path.exists():
            sys.exit(f"{path.name} non trovato: lancia prima il parse.")
        n = apply_from_csv(db, path)
        print(f"Scritte {n} submission dalle righe revisionate.")
        return

    init_db()
    db = SessionLocal()
    ws = db.query(Workspace).filter(Workspace.slug == args.workspace).first()
    if not ws:
        sys.exit(f"Workspace '{args.workspace}' inesistente.")

    projects = db.query(Project).filter(Project.workspace_id == ws.id).all()
    proposal, stats = [], Counter()

    for p in projects:
        notes = sorted([n for n in p.notes if n.source == "notion-import"],
                       key=lambda n: n.ts or utcnow())
        events = []
        for n in notes:
            events.extend(events_from_note(n))
        if not events:
            continue
        chain = build_chain(events)
        if not chain:
            continue
        proposal.append({"project_id": p.id, "title": p.title,
                         "status": p.status, "existing": len(p.submissions),
                         "attempts": chain})
        stats["progetti"] += 1
        stats["tentativi"] += len(chain)
        for a in chain:
            stats[f"conf:{a['confidence']}"] += 1
            stats[f"esito:{a['outcome']}"] += 1
            if not a["venue"]:
                stats["senza venue"] += 1
            if a.get("superseded_by"):
                stats["pending superati"] += 1

    out = Path(__file__).parent / "submissions_proposal.json"
    out.write_text(json.dumps(proposal, indent=1, ensure_ascii=False,
                              default=str), encoding="utf-8")
    write_review_csv(proposal)

    proposal.sort(key=lambda x: -len(x["attempts"]))
    print(f"{'progetto':42} {'n':>2}  catena")
    print("-" * 100)
    for row in proposal[: (len(proposal) if args.verbose else 14)]:
        chain = " → ".join(
            f"{(a['venue'] or '?')[:22]}"
            f"{'' if a['outcome'] == 'pending' else ' ✗' if 'reject' in a['outcome'] else ' ✓'}"
            for a in row["attempts"])
        print(f"{row['title'][:42]:42} {len(row['attempts']):>2}  {chain[:52]}")
    if not args.verbose and len(proposal) > 14:
        print(f"… e altri {len(proposal) - 14} progetti (--verbose per tutti)")

    print("\n" + "=" * 56)
    for k, v in sorted(stats.items()):
        print(f"  {k:18} {v}")

    if not args.apply:
        print(f"\nProposta salvata in {out.name}. Niente scritto.")
        print("Per applicare:  --apply")
        return

    written = 0
    for row in proposal:
        p = db.query(Project).filter(Project.id == row["project_id"]).first()
        # The 7 submissions the import reconstructed from the Notion status are
        # cruder than these (approximate date, often no venue), so they give way.
        for s in list(p.submissions):
            if s.notes and "Ricostruita dallo stato Notion" in s.notes:
                db.delete(s)
        for a in row["attempts"]:
            db.add(Submission(
                project_id=p.id, venue=a["venue"] or "(unknown)",
                attempt=a["attempt"],
                submitted_at=a["submitted_at"] or a["outcome_at"] or utcnow(),
                outcome=a["outcome"], outcome_at=a["outcome_at"],
                notes=f"Ricostruita dai commenti Notion (confidenza "
                      f"{a['confidence']}):\n" + "\n".join(a["evidence"])))
            written += 1
        log_event(db, p, None, "submission_opened",
                  payload=json.dumps({"source": "parse_submissions",
                                      "attempts": len(row["attempts"])}))
        db.commit()
    print(f"\nScritte {written} submission su {len(proposal)} progetti.")


if __name__ == "__main__":
    main()
