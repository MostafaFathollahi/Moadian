"""Accounts, password hashing and bearer tokens.

pbkdf2-sha256 hashes from the standard library plus HS256 JWTs. No password
ever leaves this module in a form anything else can read, and no endpoint
returns a hash.

Revocation is the part worth reading. A JWT stays cryptographically valid until
it expires, so "deactivate this account" or "change this password" would
otherwise leave live sessions running for the rest of the TTL. Two cutoffs fix
that, both checked on every request:

* a **global auth epoch**, stored in the database, so one sweep signs everyone
  out and survives a restart;
* a **per-user cutoff**, set on password change and on forced sign-out.

A token whose ``iat`` predates either cutoff is refused. ``iat`` carries
fractional seconds on purpose: whole seconds cannot order "revoked at" against
"minted for the admin who just revoked", and a tie would either keep every
same-second token alive or invalidate the caller's own replacement.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt
from fastapi import Depends, HTTPException, Request

__all__ = [
    "User",
    "hash_password",
    "verify_password",
    "make_token",
    "current_user",
    "admin_user",
    "ROLES",
    "MIN_PASSWORD",
    "USERNAME_RE",
    "secret_key",
    "token_ttl_hours",
]

import re

ROLES = ("user", "admin")
MIN_PASSWORD = 8
USERNAME_RE = re.compile(r"^[a-zA-Z0-9._-]{3,64}$")

_ITERATIONS = 200_000

#: Signs bearer tokens. Not the tax-API signing key — that one is RSA and lives
#: on disk; this is a symmetric secret for our own sessions.
SECRET_ENV = "MOADIAN_APP_SECRET"
TTL_ENV = "MOADIAN_TOKEN_TTL_HOURS"

#: Seeded at startup as "user:pass:role,user:pass:role".
SEED_ENV = "MOADIAN_SEED_USERS"
DEFAULT_SEED = "admin:admin1234:admin"


_EPHEMERAL_SECRET: str | None = None

#: Set once at startup by :func:`configure`. Reading through this rather than
#: os.environ is what makes a value in `.env` work: pydantic-settings parses
#: that file into a Settings object and never touches the process environment,
#: so anything reading os.environ directly silently ignores it.
_SETTINGS: object | None = None


def configure(settings: object) -> None:
    """Point this module at the loaded settings. Called by :func:`create_app`."""
    global _SETTINGS
    _SETTINGS = settings


def _setting(name: str, default=None):
    value = getattr(_SETTINGS, name, None) if _SETTINGS is not None else None
    if value is None:
        # An exported variable still wins, for deployments that never write a
        # .env file at all.
        env = {"app_secret": SECRET_ENV, "token_ttl_hours": TTL_ENV, "seed_users": SEED_ENV}
        raw = os.environ.get(env[name]) if name in env else None
        return raw if raw is not None else default
    return value


def secret_key() -> str:
    """The token-signing secret.

    Defaults to a random value per process rather than a hardcoded literal: a
    known default secret in a shipped app lets anyone mint an admin token. The
    cost is that tokens do not survive a restart unless it is configured, which
    is the safer way round for something that signs tax invoices.
    """
    configured = _setting("app_secret")
    if configured:
        return str(configured)
    global _EPHEMERAL_SECRET
    if _EPHEMERAL_SECRET is None:
        _EPHEMERAL_SECRET = secrets.token_hex(32)
    return _EPHEMERAL_SECRET


def token_ttl_hours() -> int:
    try:
        return int(_setting("token_ttl_hours", 12))
    except (TypeError, ValueError):
        return 12


@dataclass(frozen=True)
class User:
    id: int
    username: str
    display_name: str
    role: str
    is_active: bool
    created_at: str | None = None
    disabled_at: str | None = None
    sessions_valid_from: float | None = None

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    def public(self) -> dict[str, object]:
        """What a client may see. No hash, ever."""
        return {
            "id": self.id,
            "username": self.username,
            "display_name": self.display_name,
            "role": self.role,
            "is_active": self.is_active,
            "created_at": self.created_at,
            "disabled_at": self.disabled_at,
        }


# ------------------------------------------------------------------ passwords


def hash_password(password: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), _ITERATIONS)
    return f"pbkdf2${salt}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, salt, digest = stored.split("$")
    except ValueError:
        return False
    candidate = hash_password(password, salt).split("$")[2]
    # Constant-time: a plain == leaks the prefix length through timing.
    return hmac.compare_digest(candidate, digest)


# --------------------------------------------------------------------- tokens


def make_token(user: User) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": str(user.id),
        "username": user.username,
        "role": user.role,
        # Fractional seconds — see the module docstring on why.
        "iat": now.timestamp(),
        "exp": now + timedelta(hours=token_ttl_hours()),
    }
    return jwt.encode(payload, secret_key(), algorithm="HS256")


def _token_from_request(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:]
    return None


def current_user(request: Request) -> User:
    """Resolve the caller, or 401.

    The role is re-read from the database on every request rather than trusted
    from the token, because the token's copy goes stale the moment an admin
    changes it.
    """
    from moadian.auth.store import UserStore

    store: UserStore | None = getattr(request.app.state, "users", None)
    if store is None:
        raise HTTPException(500, "user store is not configured")

    token = _token_from_request(request)
    if not token:
        raise HTTPException(401, "برای ادامه وارد شوید")
    try:
        payload = jwt.decode(token, secret_key(), algorithms=["HS256"])
    except jwt.PyJWTError as exc:
        raise HTTPException(401, "نشست نامعتبر یا منقضی است — دوباره وارد شوید") from exc

    user = store.get(int(payload["sub"]))
    if user is None:
        raise HTTPException(401, "کاربر یافت نشد")
    # A deactivated account must lose access at once; its token stays
    # cryptographically valid until it expires, so this check is the only thing
    # that stops it.
    if not user.is_active:
        raise HTTPException(401, "حساب کاربری غیرفعال شده است")

    issued = float(payload.get("iat", 0))
    cutoff = store.auth_epoch()
    if user.sessions_valid_from:
        cutoff = max(cutoff, user.sessions_valid_from)
    if cutoff and issued < cutoff:
        raise HTTPException(401, "نشست شما پایان یافته است — دوباره وارد شوید")
    return user


def admin_user(user: User = Depends(current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(403, "این بخش تنها برای مدیر سامانه در دسترس است")
    return user


def seed_users(store, spec: str | None = None) -> int:
    """Create the accounts named in the environment, skipping any that exist.

    Without this a fresh install has no way in. Existing users are never
    overwritten, so changing the variable cannot silently reset a password.
    """
    spec = spec if spec is not None else str(_setting("seed_users", DEFAULT_SEED))
    created = 0
    for entry in spec.split(","):
        entry = entry.strip()
        if not entry:
            continue
        parts = entry.split(":")
        username, password = parts[0], parts[1] if len(parts) > 1 else ""
        role = parts[2] if len(parts) > 2 else "user"
        if not username or not password or store.by_username(username):
            continue
        try:
            store.create(username=username, password=password, display_name=username, role=role)
            created += 1
        except (ValueError, sqlite3.IntegrityError):
            continue
    return created
