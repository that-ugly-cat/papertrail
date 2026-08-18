"""
Read-only audit of a workspace. Writes nothing, ever.

Checks the invariants that three migrations and a hand review could have broken,
and the ones the data model implies but does not enforce. Each finding prints
the project id, so anything reported can be opened directly.

    python migration/audit.py --workspace ite
"""
import argparse
import collections
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from models import (  # noqa: E402
    OUTPUT_TYPES, SUBMISSION_OUTCOMES, STATUSES, Link, Note, Person, Project,
    SessionLocal, Submission, Workspace, effective_status, is_dormant,
    last_event_at, open_submission, utcnow,
)

FINDINGS = []


def flag(severity: str, check: str, detail: str):
    FINDINGS.append((severity, check, detail))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workspace", default="ite")
    args = ap.parse_args()

    db = SessionLocal()
    ws = db.query(Workspace).filter(Workspace.slug == args.workspace).first()
    if not ws:
        sys.exit(f"Workspace '{args.workspace}' inesistente.")
    P = db.query(Project).filter(Project.workspace_id == ws.id).all()
    S = [s for p in P for s in p.submissions]

    print(f"WORKSPACE {ws.slug} — {len(P)} progetti, {len(S)} submission, "
          f"{sum(len(p.notes) for p in P)} note, "
          f"{sum(len(p.links) for p in P)} link, "
          f"{sum(len(p.authorships) for p in P)} authorship\n")

    # ── vocabularies ─────────────────────────────────────────────────────────
    for p in P:
        if p.status not in STATUSES:
            flag("ERR", "stato fuori vocabolario", f"{p.id} {p.status}")
        if p.output_type not in OUTPUT_TYPES:
            flag("ERR", "tipo fuori vocabolario", f"{p.id} {p.output_type}")
    for s in S:
        if s.outcome not in SUBMISSION_OUTCOMES:
            flag("ERR", "esito fuori vocabolario", f"sub {s.id} {s.outcome}")

    # ── the submission cycle ─────────────────────────────────────────────────
    for p in P:
        subs = sorted(p.submissions, key=lambda s: s.attempt)
        pend = [s for s in subs if s.outcome == "pending"]
        if len(pend) > 1:
            flag("ERR", "più tentativi aperti insieme",
                 f"{p.id} {(p.final_title or p.title)[:40]} → "
                 f"{[s.venue for s in pend]}")
        nums = [s.attempt for s in subs]
        if nums and nums != list(range(1, len(nums) + 1)):
            flag("WARN", "numerazione tentativi non contigua", f"{p.id} {nums}")
        for s in subs:
            if s.submitted_at and s.outcome_at and s.outcome_at < s.submitted_at:
                flag("ERR", "esito prima dell'invio",
                     f"sub {s.id} {p.id} {s.submitted_at:%Y-%m-%d} → "
                     f"{s.outcome_at:%Y-%m-%d}")
            for d, what in ((s.submitted_at, "invio"), (s.outcome_at, "esito")):
                if d and d > utcnow():
                    flag("WARN", f"data {what} nel futuro",
                         f"sub {s.id} {p.id} {d:%Y-%m-%d}")
            if not s.venue or not s.venue.strip():
                flag("ERR", "submission senza venue", f"sub {s.id} {p.id}")

        # status against the record
        openx = open_submission(p)
        if p.status in ("submitted", "in_revision") and not openx:
            flag("WARN", "in submitted/in_revision senza tentativo aperto",
                 f"{p.id} {(p.final_title or p.title)[:44]}")
        if openx and p.status in ("published", "archived"):
            flag("WARN", "pubblicato/archiviato con tentativo ancora aperto",
                 f"{p.id} {(p.final_title or p.title)[:36]} @ {openx.venue}")
        if effective_status(p)["diverges"]:
            flag("WARN", "stato dichiarato ≠ stato effettivo",
                 f"{p.id} {p.status} vs {effective_status(p)['label']}")

    # ── published papers ─────────────────────────────────────────────────────
    for p in P:
        if p.status != "published":
            continue
        if not p.doi:
            flag("INFO", "pubblicato senza DOI",
                 f"{p.id} {(p.final_title or p.title)[:44]}")
        if not p.pub_year:
            flag("INFO", "pubblicato senza anno",
                 f"{p.id} {(p.final_title or p.title)[:44]}")
        if not p.journal:
            flag("INFO", "pubblicato senza journal/venue",
                 f"{p.id} {(p.final_title or p.title)[:44]}")
        if not any(s.outcome == "accept" for s in p.submissions) and p.submissions:
            flag("WARN", "pubblicato ma nessun tentativo accettato",
                 f"{p.id} {(p.final_title or p.title)[:40]}")

    # ── venues that do not look like venues ──────────────────────────────────
    PRE = re.compile(r"arxiv|biorxiv|osf|preprint", re.I)
    counts = collections.Counter(s.venue for s in S if s.venue)
    for v, n in counts.items():
        if PRE.search(v):
            flag("ERR", "preprint server usato come venue", f"{v} ×{n}")
        if len(v) < 4 or len(v.split()) > 8:
            flag("WARN", "venue di forma sospetta", f"{v!r} ×{n}")
    lowered = collections.defaultdict(set)
    for v in counts:
        lowered[v.lower()].add(v)
    for k, variants in lowered.items():
        if len(variants) > 1:
            flag("ERR", "stesso venue con grafie diverse", f"{sorted(variants)}")

    # ── people ───────────────────────────────────────────────────────────────
    people = db.query(Person).all()
    for person in people:
        if not person.authorships:
            flag("INFO", "persona senza authorship", person.name)
    keys = collections.defaultdict(list)
    for person in people:
        keys[re.sub(r"[^a-z]", "", person.name.lower())].append(person.name)
    for k, names in keys.items():
        if len(names) > 1:
            flag("WARN", "persone forse duplicate", str(names))
    noauth = [p for p in P if not p.authorships]
    if noauth:
        flag("INFO", "progetti senza autori", f"{len(noauth)} progetti")

    # ── history ──────────────────────────────────────────────────────────────
    for p in P:
        if not p.events:
            flag("ERR", "progetto senza eventi", f"{p.id}")
        elif last_event_at(p) and last_event_at(p) > utcnow():
            flag("WARN", "ultimo evento nel futuro", f"{p.id}")
    for n in db.query(Note).all():
        if not (n.body_md or "").strip():
            flag("WARN", "nota vuota", f"note {n.id}")
    for l in db.query(Link).all():
        if l.kind in ("url", "doi", "repo", "preprint") and l.target:
            if not (l.target.startswith("http") or l.target.startswith("10.")
                    or l.target in ("arXiv", "OSF")):
                flag("INFO", "link non risolvibile", f"{l.kind} {l.target[:44]}")

    # ── report ───────────────────────────────────────────────────────────────
    by_sev = collections.Counter(f[0] for f in FINDINGS)
    grouped = collections.defaultdict(list)
    for sev, check, detail in FINDINGS:
        grouped[(sev, check)].append(detail)
    for sev in ("ERR", "WARN", "INFO"):
        for (s, check), details in sorted(grouped.items()):
            if s != sev:
                continue
            print(f"[{sev}] {check} — {len(details)}")
            for d in details[:8]:
                print(f"        {d}")
            if len(details) > 8:
                print(f"        … e altri {len(details) - 8}")
    print(f"\ntotale: {dict(by_sev) or 'nessun rilievo'}")


if __name__ == "__main__":
    main()
