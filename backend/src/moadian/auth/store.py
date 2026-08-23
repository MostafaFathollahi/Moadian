"""SQLite storage for accounts.

Same shape as :mod:`moadian.store.records` — one connection behind a lock, no
ORM. *Every* statement takes the lock, reads included; see :meth:`UserStore._read`
for the bug that taught us why. Kept in its own database file from the invoice records: accounts are
operational data with a different backup and retention story from tax filings,
and mixing them makes "restore the invoices" mean "restore whoever could log in
that day too".
"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from moadian.auth.security import (
    MIN_PASSWORD,
    ROLES,
    USERNAME_RE,
    User,
    hash_password,
)

__all__ = ["UserStore"]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    username            TEXT NOT NULL UNIQUE,
    password_hash       TEXT NOT NULL,
    display_name        TEXT NOT NULL DEFAULT '',
    role                TEXT NOT NULL DEFAULT 'user',
    -- Deactivation, not deletion: an account that issued invoices must stay
    -- referenceable, so "remove" disables login and leaves the row.
    is_active           INTEGER NOT NULL DEFAULT 1,
    disabled_at         TEXT,
    -- Tokens issued before this instant are refused. Set on password change
    -- and forced sign-out; see auth.security.
    sessions_valid_from REAL,
    created_at          TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS auth_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class UserStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Reentrant: a write may need to read (see records.RecordStore._migrate),
        # and a plain Lock would deadlock on itself there.
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(str(self.path), check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA journal_mode=WAL")
        with self._write() as cursor:
            cursor.executescript(_SCHEMA)

    @contextmanager
    def _write(self) -> Iterator[sqlite3.Cursor]:
        with self._lock, self._connection:
            yield self._connection.cursor()

    @contextmanager
    def _read(self) -> Iterator[sqlite3.Cursor]:
        """A read, holding the same lock the writes do.

        Reads used to go straight to ``self._connection`` unguarded, on the
        assumption that concurrent SELECTs on one connection are harmless. They
        are not. A :class:`sqlite3.Connection` keeps a prepared-statement cache,
        so two threads running the *same* SQL text share one ``sqlite3_stmt``;
        each rebinds and resets it under the other, and the loser's
        ``fetchone()`` comes back empty for a row that plainly exists.

        FastAPI runs sync endpoints in a threadpool, and every authenticated
        request re-reads the caller through the identical
        ``SELECT * FROM users WHERE id = ?``. So the collision landed almost
        entirely on :meth:`get`, returning ``None`` for a live account — which
        :func:`~moadian.auth.security.current_user` can only read as "کاربر یافت
        نشد" and answer 401. The browser clears the session on any 401, so a user
        was thrown back to the login screen at random, most often just after
        switching pages, because that is when several requests go out at once.
        Roughly one call in twenty under a five-way fan-out.

        Serialising is the right size of fix here: this is a single-operator
        application whose queries are all indexed lookups over a handful of rows.
        """
        with self._lock:
            yield self._connection.cursor()

    def close(self) -> None:
        self._connection.close()

    # -- reads ------------------------------------------------------------

    @staticmethod
    def _row(row: sqlite3.Row) -> User:
        return User(
            id=row["id"],
            username=row["username"],
            display_name=row["display_name"] or row["username"],
            role=row["role"],
            is_active=bool(row["is_active"]),
            created_at=row["created_at"],
            disabled_at=row["disabled_at"],
            sessions_valid_from=row["sessions_valid_from"],
        )

    def get(self, user_id: int) -> User | None:
        with self._read() as cursor:
            row = cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return self._row(row) if row else None

    def by_username(self, username: str) -> User | None:
        with self._read() as cursor:
            row = cursor.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        return self._row(row) if row else None

    def password_hash(self, user_id: int) -> str | None:
        with self._read() as cursor:
            row = cursor.execute(
                "SELECT password_hash FROM users WHERE id = ?", (user_id,)
            ).fetchone()
        return row["password_hash"] if row else None

    def list(self, include_inactive: bool = True) -> list[User]:
        sql = "SELECT * FROM users"
        if not include_inactive:
            sql += " WHERE is_active = 1"
        sql += " ORDER BY is_active DESC, id ASC"
        # Materialised inside the lock: a lazy cursor read after release would
        # be exactly the unguarded access this exists to prevent.
        with self._read() as cursor:
            return [self._row(row) for row in cursor.execute(sql).fetchall()]

    def active_admin_count(self, exclude_id: int | None = None) -> int:
        sql = "SELECT COUNT(*) AS n FROM users WHERE role = 'admin' AND is_active = 1"
        params: list[object] = []
        if exclude_id is not None:
            sql += " AND id != ?"
            params.append(exclude_id)
        with self._read() as cursor:
            return int(cursor.execute(sql, params).fetchone()["n"])

    # -- writes -----------------------------------------------------------

    def create(
        self, *, username: str, password: str, display_name: str = "", role: str = "user"
    ) -> User:
        username = username.strip()
        if not USERNAME_RE.match(username):
            raise ValueError("نام کاربری: ۳ تا ۶۴ نویسه از حروف و ارقام انگلیسی و . _ -")
        if len(password.strip()) < MIN_PASSWORD:
            raise ValueError(f"گذرواژه باید دست‌کم {MIN_PASSWORD} نویسه باشد")
        if role not in ROLES:
            raise ValueError(f"نقش باید یکی از {ROLES} باشد")
        with self._write() as cursor:
            cursor.execute(
                "INSERT INTO users (username, password_hash, display_name, role, created_at) "
                "VALUES (?,?,?,?,?)",
                (
                    username,
                    hash_password(password.strip()),
                    (display_name.strip() or username)[:128],
                    role,
                    _now(),
                ),
            )
            user_id = cursor.lastrowid
        user = self.get(int(user_id))
        assert user is not None
        return user

    def set_password(self, user_id: int, password: str) -> None:
        if len(password.strip()) < MIN_PASSWORD:
            raise ValueError(f"گذرواژه باید دست‌کم {MIN_PASSWORD} نویسه باشد")
        with self._write() as cursor:
            cursor.execute(
                "UPDATE users SET password_hash = ?, sessions_valid_from = ? WHERE id = ?",
                # A reset that leaves the old sessions alive is not a reset.
                (hash_password(password.strip()), datetime.now(UTC).timestamp(), user_id),
            )

    def update(
        self,
        user_id: int,
        *,
        display_name: str | None = None,
        role: str | None = None,
        is_active: bool | None = None,
    ) -> User | None:
        sets: list[str] = []
        params: list[object] = []
        if display_name is not None:
            sets.append("display_name = ?")
            params.append(display_name.strip()[:128])
        if role is not None:
            if role not in ROLES:
                raise ValueError(f"نقش باید یکی از {ROLES} باشد")
            sets.append("role = ?")
            params.append(role)
        if is_active is not None:
            sets.append("is_active = ?")
            params.append(int(is_active))
            sets.append("disabled_at = ?")
            params.append(None if is_active else _now())
        if not sets:
            return self.get(user_id)
        params.append(user_id)
        with self._write() as cursor:
            cursor.execute(f"UPDATE users SET {', '.join(sets)} WHERE id = ?", params)
        return self.get(user_id)

    def delete(self, user_id: int) -> None:
        with self._write() as cursor:
            cursor.execute("DELETE FROM users WHERE id = ?", (user_id,))

    # -- revocation -------------------------------------------------------

    def revoke_user_sessions(self, user_id: int) -> None:
        with self._write() as cursor:
            cursor.execute(
                "UPDATE users SET sessions_valid_from = ? WHERE id = ?",
                (datetime.now(UTC).timestamp(), user_id),
            )

    def auth_epoch(self) -> float:
        # Read on every authenticated request, alongside get() — so it is on the
        # same hot path and takes the same lock.
        with self._read() as cursor:
            row = cursor.execute(
                "SELECT value FROM auth_settings WHERE key = 'auth_epoch'"
            ).fetchone()
        try:
            return float(row["value"]) if row else 0.0
        except (TypeError, ValueError):
            return 0.0

    def revoke_all_sessions(self) -> float:
        """Void every token issued so far. The caller mints its replacement
        *after* this returns, so that token's iat is strictly greater."""
        epoch = datetime.now(UTC).timestamp()
        with self._write() as cursor:
            cursor.execute(
                "INSERT INTO auth_settings (key, value) VALUES ('auth_epoch', ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (repr(epoch),),
            )
        return epoch
