"""
Check PaperTrail's author lists against the published record, via Crossref.

The migration from Notion carried `Managed by`, which is who *ran* a project,
not who signed the paper. On the published ones that gap is checkable: the DOI
is already in the row, and Crossref knows the real author list.

Read-only by default and loud about uncertainty. Two rules that matter more than
the diff itself:

- **A name is never merged on a guess.** Matching is on the canonical form, with
  a family-name-plus-initial fallback that is *reported* and never applied. Two
  spellings of one person become two Person rows and split an authorship in
  half — the same fragmentation `models.py` describes for venue names, and the
  reason Fritschi had to be settled by hand.
- **Crossref is authoritative about the published paper, not about the project.**
  A preprint, a chapter, a book has no Crossref record, and absence of data is
  reported as absence of data rather than as an empty author list.

    python migration/crossref_check.py                # report
    python migration/crossref_check.py --project 51   # one project
    python migration/crossref_check.py --apply        # write (asks nothing;
                                                      # confirm with Spit first)
"""
import argparse
import json
import re
import sys
import time
import urllib.parse
import unicodedata
import urllib.request

sys.path.insert(0, "/app")

from models import (Authorship, Person, Project, SessionLocal, User,  # noqa: E402
                    canonical, get_or_create_person, log_event)

MAILTO = "giovanni.spitale@ibme.uzh.ch"
API = "https://api.crossref.org/works/"
DOI_RE = re.compile(r"(10\.\d{4,9}/[^\s\"<>?]+)")


def extract_doi(raw: str) -> str | None:
    """
    Pull a DOI out of whatever ended up in the field.

    The column holds publisher URLs as often as bare DOIs, and two shapes hide a
    real DOI rather than lacking one: percent-encoded slashes from a copied
    Springer link, and Nature's news articles, whose `d41586-…` id is the tail
    of a 10.1038 DOI.
    """
    s = (raw or "").strip()
    if not s:
        return None
    s = s.replace("%2F", "/").replace("%2f", "/")
    m = DOI_RE.search(s)
    if m:
        doi = m.group(1).rstrip(").,;/")
        # A DOI may legitimately contain slashes, so the tail cannot simply be
        # cut at the first one. What can be cut is the publisher's own view
        # suffix: Frontiers links end in /full or /abstract, and leaving those
        # on turns a resolvable DOI into a 404 that reads as "not registered".
        for suffix in ("/full", "/abstract", "/html", "/pdf", "/meta", "/text",
                       "/fulltext"):
            if doi.lower().endswith(suffix):
                doi = doi[: -len(suffix)]
                break
        return doi
    m = re.search(r"nature\.com/articles/(d\d{5}-[\w-]+)", s)
    if m:
        return f"10.1038/{m.group(1)}"
    return None


def fetch(doi: str) -> dict | None:
    url = API + urllib.parse.quote(doi, safe="") + f"?mailto={MAILTO}"
    req = urllib.request.Request(url, headers={
        "User-Agent": f"PaperTrail author check (mailto:{MAILTO})"})
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            return json.load(r).get("message")
    except Exception:                                    # noqa: BLE001
        return None


def crossref_authors(msg: dict) -> list[dict]:
    out = []
    for a in msg.get("author") or []:
        given, family = (a.get("given") or "").strip(), (a.get("family") or "").strip()
        name = " ".join(x for x in (given, family) if x) or (a.get("name") or "").strip()
        if not name:
            continue
        out.append({"name": name, "family": family, "given": given,
                    "orcid": (a.get("ORCID") or "").rsplit("/", 1)[-1] or None})
    return out


# Crossref writes names the way the publisher typeset them, and two of those
# habits are person-splitting traps: U+2010 instead of an ASCII hyphen (seen on
# "Nikola Biller‐Andorno"), and hyphenation that varies between records for the
# same person ("Tyebally-Fang" against "Tyebally Fang"). Matching on canonical()
# alone would call those different people and create a second Person row, which
# is the exact fragmentation this script exists to prevent.
_DASHES = dict.fromkeys(map(ord, "‐‑‒–—―−"), " ")
_DROP = dict.fromkeys(map(ord, ".'’`"), None)


def _norm(name: str) -> str:
    """Match key: unicode-folded, dashes and punctuation flattened to spaces."""
    s = unicodedata.normalize("NFKC", name or "")
    s = s.translate(_DASHES).translate(_DROP).replace("-", " ")
    return canonical(s)


def _initial_key(name: str) -> str:
    """family + first initial, for spotting a probable match without acting."""
    parts = [p for p in _norm(name).split() if p]
    if not parts:
        return ""
    return f"{parts[-1]}|{parts[0][:1]}"


def resolve_person(db, name: str) -> tuple["Person | None", bool]:
    """
    (person, is_new) for a Crossref name.

    Deliberately NOT get_or_create_person(): that matches on `canonical_name`,
    which keeps U+2010 and hyphenation intact, so it would happily create a
    second "Nikola Biller-Andorno" next to the first. Here the existing registry
    is scanned with the same key used for comparison, and a Person is created
    only when nothing in it matches — and then under the ASCII spelling, so the
    row that lands in the table is the one a human would type.
    """
    key = _norm(name)
    for person in db.query(Person).all():
        if _norm(person.name) == key:
            return person, False
    clean = unicodedata.normalize("NFKC", name).translate(_DASHES).strip()
    clean = re.sub(r"\s+", " ", clean)
    return Person(name=clean, canonical_name=canonical(clean)), True


def compare(p: Project, cr: list[dict]) -> dict:
    have = {_norm(a.person.name): a for a in p.authorships}
    have_init = {}
    for k, a in have.items():
        have_init.setdefault(_initial_key(a.person.name), []).append(a)

    exact, probable, missing = [], [], []
    for c in cr:
        key = _norm(c["name"])
        if key in have:
            exact.append((c, have[key]))
            continue
        hits = have_init.get(_initial_key(c["name"]), [])
        if len(hits) == 1:
            probable.append((c, hits[0]))
        else:
            missing.append(c)
    cr_keys = {_norm(c["name"]) for c in cr}
    cr_init = {_initial_key(c["name"]) for c in cr}
    extra = [a for k, a in have.items()
             if k not in cr_keys and _initial_key(a.person.name) not in cr_init]
    return {"exact": exact, "probable": probable, "missing": missing,
            "extra": extra}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", type=int, default=None)
    ap.add_argument("--apply", action="store_true",
                    help="add missing authors and fill ORCIDs")
    ap.add_argument("--actor", default="giovanni.spitale@ibme.uzh.ch")
    ap.add_argument("--sleep", type=float, default=0.4)
    args = ap.parse_args()

    db = SessionLocal()
    actor = db.query(User).filter(User.email == args.actor).first()
    q = db.query(Project).filter(Project.deleted_at == None)  # noqa: E711
    if args.project:
        q = q.filter(Project.id == args.project)
    else:
        q = q.filter(Project.status == "published")
    projects = q.order_by(Project.id).all()

    no_doi, no_record, clean = [], [], 0
    changes = 0

    for p in projects:
        doi = extract_doi(p.doi or "")
        if not doi:
            no_doi.append(p)
            continue
        msg = fetch(doi)
        time.sleep(args.sleep)
        if not msg:
            no_record.append((p, doi))
            continue
        cr = crossref_authors(msg)
        if not cr:
            no_record.append((p, doi))
            continue
        d = compare(p, cr)

        head = f"#{p.id} {p.title[:52]}"
        if not d["missing"] and not d["extra"] and not d["probable"]:
            clean += 1
            for c, a in d["exact"]:
                if c["orcid"] and not a.person.orcid:
                    if args.apply:
                        a.person.orcid = c["orcid"]
                        changes += 1
                    print(f"{head}\n   orcid {a.person.name}: {c['orcid']}")
            continue

        print(f"\n{head}")
        print(f"   crossref: {', '.join(c['name'] for c in cr)}")
        if d["missing"]:
            print(f"   MANCANO in PaperTrail: {', '.join(c['name'] for c in d['missing'])}")
        if d["probable"]:
            for c, a in d["probable"]:
                print(f"   ~ grafia diversa? crossref '{c['name']}' "
                      f"vs papertrail '{a.person.name}' — non tocco, decidi tu")
        if d["extra"]:
            print(f"   in PaperTrail e non su Crossref: "
                  f"{', '.join(a.person.name for a in d['extra'])}")

        if args.apply and d["missing"]:
            pos = max([a.position or 0 for a in p.authorships], default=0)
            for c in d["missing"]:
                person, is_new = resolve_person(db, c["name"])
                if is_new:
                    db.add(person)
                    db.flush()
                if c["orcid"] and not person.orcid:
                    person.orcid = c["orcid"]
                pos += 1
                db.add(Authorship(project_id=p.id, person_id=person.id,
                                  role="co-author", position=pos))
                log_event(db, p, actor, "authorship_changed",
                          payload=f"added {person.name} (crossref {doi})")
                changes += 1
                print(f"   + aggiunto {person.name}"
                      + ("" if is_new else "  (persona già in anagrafica)"))
        for c, a in d["exact"]:
            if c["orcid"] and not a.person.orcid and args.apply:
                a.person.orcid = c["orcid"]
                changes += 1

    if args.apply:
        db.commit()
    print("\n" + "=" * 60)
    print(f"controllati    : {len(projects)}")
    print(f"già coerenti   : {clean}")
    print(f"senza DOI      : {len(no_doi)}"
          + (f" — {', '.join('#%d' % x.id for x in no_doi)}" if no_doi else ""))
    print(f"non su Crossref: {len(no_record)}"
          + (f" — {', '.join('#%d' % x[0].id for x in no_record)}" if no_record else ""))
    if args.apply:
        print(f"scritture      : {changes}")
    else:
        print("nessuna scrittura (usa --apply dopo aver deciso)")
    db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
