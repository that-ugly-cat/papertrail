"""
Seed the first admin and the ITE workspace.

Usage (locally, or via `docker exec -it papertrail python seed.py`):
    python seed.py <email> <name> <password>

Idempotent: re-running it adds whatever is missing and leaves the rest alone.
"""
import sys

from auth import hash_password
from models import (
    Membership, SessionLocal, User, Workspace, get_or_create_person, init_db,
)

ITE_SLUG = "ite"
ITE_NAME = "ITE"
ITE_DESC = ("Information, Technology & Experimental Ethics Lab — IBME, "
            "Università di Zurigo")


def main():
    if len(sys.argv) != 4:
        print("Usage: python seed.py <email> <name> <password>")
        sys.exit(1)
    email, name, password = sys.argv[1].strip().lower(), sys.argv[2], sys.argv[3]

    init_db()
    db = SessionLocal()

    user = db.query(User).filter(User.email == email).first()
    if user:
        print(f"User {email} already exists.")
    else:
        user = User(email=email, name=name, hashed_password=hash_password(password),
                    is_admin=True, is_active=True)
        db.add(user)
        db.flush()
        person = get_or_create_person(db, name)
        if person and person.user_id is None:
            person.user_id = user.id
        print(f"Admin {email} created.")

    ws = db.query(Workspace).filter(Workspace.slug == ITE_SLUG).first()
    if ws:
        print(f"Workspace {ITE_SLUG} already exists.")
    else:
        ws = Workspace(slug=ITE_SLUG, name=ITE_NAME, description=ITE_DESC)
        db.add(ws)
        db.flush()
        print(f"Workspace {ITE_SLUG} created.")

    member = (db.query(Membership)
                .filter(Membership.user_id == user.id,
                        Membership.workspace_id == ws.id)
                .first())
    if not member:
        db.add(Membership(user_id=user.id, workspace_id=ws.id, role="admin",
                          created_by=user.id))
        print(f"{email} is now admin of {ITE_SLUG}.")

    db.commit()


if __name__ == "__main__":
    main()
