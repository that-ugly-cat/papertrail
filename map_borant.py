"""
Link existing users to the subjects an SSO gate knows them by.

Run once, by hand, BEFORE switching AUTH_MODE to `gateway`, and read the report
before believing it:

    docker exec papertrail python map_borant.py --map you@example.org=01ABC...
    docker exec papertrail python map_borant.py --report

Why a script rather than an automatic match at request time: linking by email is
defensible in principle, because the address arrives from the gate and not from
the client — but doing it live means one typo in the gate's admin panel silently
hands one person another person's workspaces, and nobody finds out.

What is *not* at stake here, and it is worth saying: this app keeps its own
authorization. Someone who arrives unlinked gets a fresh profile with no
`Membership` rows, and a user with no memberships sees no workspace at all. The
failure mode is an empty screen, not a leak — which is why `workspace_dep` doing
the real work matters more than the gate being right.

Nothing here is destructive: an existing link is reported, never overwritten,
and --unlink undoes one.
"""
import argparse
import sys

from models import Membership, Project, SessionLocal, User, Workspace


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--map", action="append", default=[], metavar="EMAIL=SUBJECT",
                    help="link one user to one gate subject; repeatable")
    ap.add_argument("--unlink", action="append", default=[], metavar="EMAIL",
                    help="drop the link for one user; repeatable")
    ap.add_argument("--report", action="store_true",
                    help="print who is linked and who is not, and change nothing")
    args = ap.parse_args()

    db = SessionLocal()
    changed = 0

    for pair in args.map:
        email, sep, subject = pair.partition("=")
        email, subject = email.strip().lower(), subject.strip()
        if not sep or not email or not subject:
            print(f"  SALTO     {pair!r}: serve la forma email=subject")
            continue
        user = db.query(User).filter(User.email == email).first()
        if user is None:
            print(f"  ASSENTE   {email}: nessun utente con questo indirizzo")
            continue
        if user.borant_sub == subject:
            print(f"  GIA-OK    {email} -> {subject}")
            continue
        if user.borant_sub:
            print(f"  CONFLITTO {email}: gia' legato a {user.borant_sub}, non sovrascrivo. "
                  f"Usa --unlink prima, se e' voluto.")
            continue
        clash = db.query(User).filter(User.borant_sub == subject).first()
        if clash is not None:
            print(f"  CONFLITTO {email}: il subject {subject} e' gia' di {clash.email}")
            continue
        user.borant_sub = subject
        changed += 1
        print(f"  LEGATO    {email} -> {subject}")

    for email in args.unlink:
        email = email.strip().lower()
        user = db.query(User).filter(User.email == email).first()
        if user is None or not user.borant_sub:
            print(f"  NIENTE    {email}: non era legato")
            continue
        print(f"  SLEGATO   {email} (era {user.borant_sub})")
        user.borant_sub = None
        changed += 1

    if changed:
        db.commit()

    print("\n-- stato degli utenti --")
    scoperti = []
    for u in db.query(User).order_by(User.id).all():
        ms = db.query(Membership).filter(Membership.user_id == u.id).all()
        where = ", ".join(f"{db.get(Workspace, m.workspace_id).slug}:{m.role}" for m in ms) or "—"
        flag = " ADMIN" if u.is_admin else ""
        print(f"  {u.email:<34} {u.borant_sub or '(nessun legame)':<28} [{where}]{flag}")
        if not u.borant_sub and u.is_active:
            scoperti.append((u, len(ms)))

    print(f"\n  {len(scoperti)} utenti attivi senza legame.")
    if scoperti:
        print("  In `gateway` arrivano come profilo NUOVO, quindi senza le loro")
        print("  membership: vedrebbero un elenco di workspace vuoto. Nessuna fuga di")
        print("  dati, ma nemmeno il loro lavoro. Legali prima di accendere.")
        persi = sum(n for _, n in scoperti)
        if persi:
            print(f"  Fra loro ci sono {persi} membership che resterebbero attaccate a")
            print("  profili irraggiungibili dal gate.")
    db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
