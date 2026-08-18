import sys
sys.path.insert(0, '.')
from models import SessionLocal, Project, OUTPUT_TYPE_LABELS
import collections

# id -> tipo, deciso guardando i dati vivi e, dove i campi non bastavano,
# le note e il wiki.
TYPES = {
    17:  "book",           # AI and Infodemic Management, volume curato Routledge
    84:  "book",           # Mi fa male la scienza — Edizioni Tlon 2025, Hrönir 11
    41:  "book",           # la versione internazionale dello stesso libro
    119: "book",           # Children's book on disinformation
    38:  "linkedin_post",  # cinque riviste, poi LinkedIn
    54:  "media_piece",    # Culturico è una rivista online, non accademica
    115: "media_piece",    # "Trust article for media (submitted to e.g. Quillette)"
    116: "other",          # guidance WHO, non un articolo su rivista
}

db = SessionLocal()
changed = []
for pid, t in TYPES.items():
    p = db.query(Project).filter(Project.id == pid).first()
    if p and p.output_type != t:
        changed.append((p.id, OUTPUT_TYPE_LABELS[t], (p.final_title or p.title)[:52]))
        p.output_type = t
# everything else is a paper, including preprints and software papers
for p in db.query(Project).all():
    if not p.output_type:
        p.output_type = "paper"
db.commit()
for pid, lab, title in changed:
    print(f"  {pid:4d}  {lab:14} {title}")
print()
print("distribuzione:", dict(collections.Counter(
    p.output_type for p in db.query(Project).all())))
