"""Login, identity, and admin account management."""

from __future__ import annotations

import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from moadian.auth.security import (
    MIN_PASSWORD,
    ROLES,
    User,
    admin_user,
    current_user,
    make_token,
    verify_password,
)
from moadian.auth.store import UserStore

__all__ = ["auth_router", "users_router"]

auth_router = APIRouter(prefix="/api/auth", tags=["auth"])
users_router = APIRouter(prefix="/api/admin/users", tags=["admin-users"])


def get_users(request: Request) -> UserStore:
    store = getattr(request.app.state, "users", None)
    if store is None:
        raise HTTPException(500, "user store is not configured")
    return store


Users = Annotated[UserStore, Depends(get_users)]


class LoginRequest(BaseModel):
    username: str
    password: str


class PasswordChange(BaseModel):
    current_password: str
    new_password: str = Field(min_length=MIN_PASSWORD)


class UserCreate(BaseModel):
    username: str
    password: str
    display_name: str = ""
    role: str = "user"


class UserUpdate(BaseModel):
    display_name: str | None = None
    role: str | None = None
    password: str | None = None
    is_active: bool | None = None


# ------------------------------------------------------------------ sessions


@auth_router.post("/login")
def login(body: LoginRequest, users: Users):
    user = users.by_username(body.username.strip())
    stored = users.password_hash(user.id) if user else None
    # Verify even when the user is unknown, against a dummy hash, so a missing
    # account and a wrong password take the same time. Otherwise the endpoint
    # answers "does this username exist" to anyone with a stopwatch.
    if not verify_password(body.password, stored or "pbkdf2$00$00"):
        raise HTTPException(401, "نام کاربری یا گذرواژه نادرست است")
    assert user is not None
    if not user.is_active:
        raise HTTPException(403, "این حساب غیرفعال شده است — با مدیر سامانه تماس بگیرید")
    return {"token": make_token(user), "user": user.public()}


@auth_router.get("/me")
def me(user: User = Depends(current_user)):
    return user.public()


@auth_router.post("/password")
def change_password(body: PasswordChange, users: Users, user: User = Depends(current_user)):
    """Change one's own password. Ends every other session by design."""
    stored = users.password_hash(user.id) or ""
    if not verify_password(body.current_password, stored):
        raise HTTPException(400, "گذرواژه فعلی نادرست است")
    try:
        users.set_password(user.id, body.new_password)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    # set_password revoked this user's tokens, including the caller's. Hand back
    # a fresh one so changing your own password does not log you out.
    refreshed = users.get(user.id)
    assert refreshed is not None
    return {"ok": True, "token": make_token(refreshed)}


# ------------------------------------------------------------ administration


def _guard_last_admin(users: UserStore, target: User) -> None:
    """Refuse any change that would leave the system with no way in."""
    if target.role == "admin" and target.is_active and users.active_admin_count(target.id) == 0:
        raise HTTPException(400, "این تنها مدیر فعال سامانه است — ابتدا مدیر دیگری تعریف کنید")


@users_router.get("")
def list_users(users: Users, _: User = Depends(admin_user), include_inactive: bool = True):
    return [u.public() for u in users.list(include_inactive=include_inactive)]


@users_router.post("", status_code=201)
def create_user(body: UserCreate, users: Users, _: User = Depends(admin_user)):
    if users.by_username(body.username.strip()):
        raise HTTPException(409, "این نام کاربری قبلاً ثبت شده است")
    try:
        user = users.create(
            username=body.username,
            password=body.password,
            display_name=body.display_name,
            role=body.role,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except sqlite3.IntegrityError as exc:
        raise HTTPException(409, "این نام کاربری قبلاً ثبت شده است") from exc
    return user.public()


@users_router.patch("/{user_id}")
def update_user(user_id: int, body: UserUpdate, users: Users, me: User = Depends(admin_user)):
    target = users.get(user_id)
    if target is None:
        raise HTTPException(404, "کاربر یافت نشد")

    if body.password is not None:
        try:
            users.set_password(user_id, body.password)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    if body.role is not None and body.role != target.role:
        if body.role not in ROLES:
            raise HTTPException(422, f"نقش باید یکی از {ROLES} باشد")
        # Self-demotion is how an admin accidentally locks themselves out.
        if target.id == me.id:
            raise HTTPException(400, "نمی‌توانید نقش حساب خودتان را تغییر دهید")
        if target.role == "admin":
            _guard_last_admin(users, target)

    if body.is_active is not None and bool(body.is_active) != target.is_active:
        if target.id == me.id:
            raise HTTPException(400, "نمی‌توانید حساب خودتان را غیرفعال کنید")
        if not body.is_active:
            _guard_last_admin(users, target)

    try:
        updated = users.update(
            user_id,
            display_name=body.display_name,
            role=body.role,
            is_active=body.is_active,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    assert updated is not None
    return updated.public()


@users_router.delete("/{user_id}")
def delete_user(user_id: int, users: Users, me: User = Depends(admin_user), hard: bool = False):
    """Deactivate by default; purge only an account that has never signed in usefully.

    An account is not hard-deleted because invoices carry no user column today
    but audit questions ("who sent this") outlive the row. Deactivation refuses
    login and rejects live tokens on the next request, which is what "remove"
    needs to mean.
    """
    target = users.get(user_id)
    if target is None:
        raise HTTPException(404, "کاربر یافت نشد")
    if target.id == me.id:
        raise HTTPException(400, "نمی‌توانید حساب خودتان را حذف کنید")
    _guard_last_admin(users, target)
    if hard:
        users.delete(user_id)
        return {"ok": True, "deleted": True}
    users.update(user_id, is_active=False)
    users.revoke_user_sessions(user_id)
    updated = users.get(user_id)
    assert updated is not None
    return {"ok": True, "deleted": False, "user": updated.public()}


@users_router.post("/sessions/revoke-all")
def revoke_all(users: Users, me: User = Depends(admin_user)):
    """Sign everyone out. The caller gets a fresh token so it survives its own sweep."""
    epoch = users.revoke_all_sessions()
    return {"ok": True, "epoch": epoch, "token": make_token(me)}


@users_router.post("/{user_id}/sessions/revoke")
def revoke_one(user_id: int, users: Users, me: User = Depends(admin_user)):
    target = users.get(user_id)
    if target is None:
        raise HTTPException(404, "کاربر یافت نشد")
    users.revoke_user_sessions(user_id)
    return {"ok": True, "token": make_token(me) if target.id == me.id else None}
