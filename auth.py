"""
Authentication and authorization for PaperTrail.

Auth (borant house pattern, same as LSSR): JWT in an httpOnly cookie named
'session', 7-day lifetime, secret from JWT_SECRET (startup crashes if missing).

Authorization is the part that matters here. Every workspace-scoped route goes
through `workspace_dep(minimum)`, which resolves (user, workspace) -> role once
and raises 404 when there is no membership. Permissions are never checked in
templates: templates receive the already-resolved `role` and only decide what to
draw with it (SPEC.md §3).
"""
import os
from contextvars import ContextVar
from datetime import datetime, timedelta

import bcrypt
from fastapi import Cookie, Depends, HTTPException, status
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from models import (
    ApiKey, User, Workspace, has_role, role_for, get_db, utcnow,
)

SECRET_KEY  = os.environ["JWT_SECRET"]
ALGORITHM   = "HS256"
EXPIRE_DAYS = 7


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())


def create_token(user_id: int) -> str:
    expire = datetime.utcnow() + timedelta(days=EXPIRE_DAYS)
    return jwt.encode({"sub": str(user_id), "exp": expire}, SECRET_KEY,
                      algorithm=ALGORITHM)


def _decode_token(token: str) -> int:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return int(payload["sub"])
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Invalid session")


def get_current_user(
    session: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
) -> User:
    if not session:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Not authenticated")
    user_id = _decode_token(session)
    user = db.query(User).filter(User.id == user_id,
                                 User.is_active == True).first()  # noqa: E712
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="User not found")
    return user


def get_user_or_none(session: str | None, db: Session) -> User | None:
    """Plain function (not a Depends) for pages that render logged-out too."""
    if not session:
        return None
    try:
        user_id = _decode_token(session)
    except HTTPException:
        return None
    return db.query(User).filter(User.id == user_id,
                                 User.is_active == True).first()  # noqa: E712


def require_admin(user: User = Depends(get_current_user)) -> User:
    """Global admin: creates users and workspaces. Deliberately does NOT grant
    access to workspace content — that needs a Membership (SPEC.md §3)."""
    if not user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="Admin required")
    return user


class WorkspaceAccess:
    """What a workspace-scoped route receives once access is settled."""

    def __init__(self, workspace: Workspace, role: str, user: User, db: Session):
        self.workspace = workspace
        self.role = role
        self.user = user
        self.db = db

    @property
    def can_write(self) -> bool:
        return has_role(self.role, "write")

    @property
    def can_admin(self) -> bool:
        return has_role(self.role, "admin")


def workspace_dep(minimum: str = "read"):
    """
    Dependency factory. Usage:

        @app.get("/w/{slug}")
        def board(acc: WorkspaceAccess = Depends(workspace_dep("read"))): ...

    Two failure modes, both deliberate:
      - no such workspace          -> 404
      - workspace exists, no row   -> 404 (never 403: a 403 confirms existence)
      - membership below `minimum` -> 403 (the user already knows it exists)
    """
    def _dep(
        slug: str,
        user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ) -> WorkspaceAccess:
        ws = db.query(Workspace).filter(Workspace.slug == slug).first()
        if ws is None:
            raise HTTPException(status_code=404, detail="Not found")
        role = role_for(db, user, ws)
        if role is None:
            raise HTTPException(status_code=404, detail="Not found")
        if not has_role(role, minimum):
            raise HTTPException(status_code=403,
                                detail="Insufficient permissions")
        return WorkspaceAccess(ws, role, user, db)

    return _dep


def touch_login(db: Session, user: User) -> None:
    user.last_login = utcnow()
    db.commit()


# ── MCP surface ───────────────────────────────────────────────────────────────

# The MCP tools are plain sync functions with no access to the request, so the
# caller resolved by the middleware is handed over in a contextvar. One per
# request, and `stateless_http` means one request per call.
_caller: ContextVar["User | None"] = ContextVar("mcp_caller", default=None)


def check_api_key(db: Session, key: str) -> "ApiKey | None":
    """The active ApiKey row for this key, or None. Stamps last_used_at so a
    key that is still in use somewhere is visible in /admin."""
    from models import ApiKey
    if not key:
        return None
    row = (db.query(ApiKey)
             .filter(ApiKey.key == key, ApiKey.active == True)      # noqa: E712
             .first())
    if row is None or not row.user or not row.user.is_active:
        return None
    row.last_used_at = utcnow()
    db.commit()
    return row


def set_caller(user: "User | None") -> None:
    _caller.set(user)


def current_caller() -> "User":
    user = _caller.get()
    if user is None:
        raise PermissionError("No authenticated caller")
    return user


def mcp_workspace(db: Session, slug: str, minimum: str = "read"):
    """
    Resolve a workspace for an MCP call under the caller's own permissions.

    Same rule as the web app: no membership is indistinguishable from no
    workspace. The model gets told "not found", never "exists but forbidden".
    """
    user = current_caller()
    ws = db.query(Workspace).filter(Workspace.slug == slug).first()
    if ws is None:
        raise LookupError(f"No workspace '{slug}'")
    role = role_for(db, user, ws)
    if role is None:
        raise LookupError(f"No workspace '{slug}'")
    if not has_role(role, minimum):
        raise PermissionError(
            f"'{slug}' requires {minimum} access, you have {role}")
    return ws, role
