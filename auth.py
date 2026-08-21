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
import ipaddress
import logging
import os
import secrets
from contextvars import ContextVar
from datetime import datetime, timedelta

import bcrypt
from fastapi import Cookie, Depends, HTTPException, Request, status
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from models import (
    ApiKey, User, Workspace, has_role, role_for,
    role_on_project, get_db, utcnow,
)

log = logging.getLogger("papertrail.auth")

SECRET_KEY  = os.environ["JWT_SECRET"]
ALGORITHM   = "HS256"
EXPIRE_DAYS = 7

# Two ways of recognising a user, and `local` is the default on purpose: an app
# that believes an identity header with nothing in front of it lets in anyone
# who sends that header. The gateway path stays dead code until someone turns
# it on deliberately.
#
#   local     email + password against the users table, as it has always worked
#   gateway   an upstream SSO gate vouches for the caller via X-Borant-*
#
# Note what does NOT change: /mcp keeps its own per-user API key, because a
# model client has no browser and no cookie, and authorization stays entirely
# here — the gate says who you are, `workspace_dep` still decides what you may
# touch, and a fresh profile with no Membership rows can see nothing at all.
AUTH_MODE = os.environ.get("AUTH_MODE", "local").strip().lower()

# In gateway mode identity headers are believed only from here — the reverse
# proxy, never the internet. Under Docker this is a bridge gateway and NOT
# 127.0.0.1; DEPLOY.md shows how to read the real value off a running container.
TRUSTED_PROXY = os.environ.get("BORANT_TRUSTED_PROXY", "127.0.0.1")


def _parse_trusted(raw: str) -> list:
    nets = []
    for chunk in raw.replace(";", ",").split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            nets.append(ipaddress.ip_network(chunk, strict=False))
        except ValueError:
            log.warning("BORANT_TRUSTED_PROXY: ignoring %r, not an address or CIDR", chunk)
    return nets


TRUSTED_PROXIES = _parse_trusted(TRUSTED_PROXY)


def gateway_mode() -> bool:
    return AUTH_MODE == "gateway"


def _from_trusted_proxy(request: Request) -> bool:
    peer = request.client.host if request.client else None
    if not peer:
        return False
    try:
        addr = ipaddress.ip_address(peer)
    except ValueError:
        return False
    return any(addr in net for net in TRUSTED_PROXIES)


def user_from_gateway(request: Request, db: Session) -> User | None:
    """The user the gate vouched for, or None.

    Lookup is by `borant_sub` and never by email: a typo in the gate's admin
    panel must not be able to hand one person another person's workspaces.
    An unknown subject gets a fresh profile, which here is a genuinely harmless
    outcome — a user with no `Membership` rows sees no workspace at all, so the
    failure mode is an empty screen and not a leak. `map_borant.py` does the
    linking once, by hand, and prints what it did.
    """
    if not gateway_mode():
        return None
    sub = request.headers.get("x-borant-sub")
    if not sub:
        return None
    if not _from_trusted_proxy(request):
        log.warning("X-Borant-Sub from %s, outside BORANT_TRUSTED_PROXY (%s): ignored",
                    request.client.host if request.client else "?", TRUSTED_PROXY)
        return None

    user = db.query(User).filter(User.borant_sub == sub).first()
    if user is not None:
        return user if user.is_active else None

    email = (request.headers.get("x-borant-email", "") or f"{sub}@borant.invalid").strip().lower()
    # A local password nobody knows, rather than none: `AUTH_MODE=local` has to
    # stay a working way back, and a row with no password is not a way back.
    user = User(email=email, name=request.headers.get("x-borant-name", "") or email,
                hashed_password=hash_password(secrets.token_urlsafe(32)),
                borant_sub=sub, is_active=True, is_admin=False)
    db.add(user)
    db.commit()
    db.refresh(user)
    log.info("gateway: new profile for %s (%s)", email, sub)
    return user


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
    request: Request,
    session: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
) -> User:
    if gateway_mode():
        # The header wins over the local cookie, always: a leftover cookie must
        # not outlive a session the gate has revoked.
        user = user_from_gateway(request, db)
        if user is not None:
            return user
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Not authenticated")
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


def get_user_or_none(session: str | None, db: Session,
                     request: Request | None = None) -> User | None:
    """Plain function (not a Depends) for pages that render logged-out too."""
    if gateway_mode():
        return user_from_gateway(request, db) if request is not None else None
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


def project_access(acc: "WorkspaceAccess", project) -> str:
    """
    The caller's role on a shared project: the best they hold across the
    workspaces it belongs to, never less than the one they have here.

    Without this a project shared into a workspace where the caller is only a
    reader would become read-only for them, even when they are an admin of the
    group that owns it — the same button working or not depending on which board
    they came from.
    """
    best = role_on_project(acc.db, acc.user, project)
    if best is None:
        return acc.role
    return best if has_role(best, acc.role) else acc.role


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
