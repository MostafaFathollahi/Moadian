"""SQLite storage for the things an operator maintains between invoices.

**Buyers and goods are not scoped to a profile; invoices are.** They were, once,
on the reasoning that a buyer entered against sandbox should not appear on a
production invoice. That reasoning does not survive contact with the objects: a
شناسه ملی and a شناسه کالا/خدمت are issued nationally and mean the same thing in
both environments, so scoping them bought no safety and cost the operator two
address books to keep in step. Worse, it made both catalogues unreachable until
a شناسه یکتای حافظه مالیاتی had been obtained — which is precisely the waiting
period during which you want to be entering your customers and your goods codes.
Invoices stay profile-scoped, because *those* really do belong to one memory.

Deliberately not an ORM. The schema is four tables wide and the queries are all
"give me the rows"; SQLAlchemy would be more machinery than the problem has.

One connection, and *every* statement takes the lock — reads included. See
:meth:`RecordStore._read`.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from moadian.errors import ConfigurationError

__all__ = ["Buyer", "GoodsService", "InvoiceRecord", "RecordStore", "InvoiceState"]

SCHEMA_VERSION = 2

#: Split out so :meth:`RecordStore._migrate` can rebuild one table at a time.
#: ``executescript`` commits any open transaction, so the migration must not
#: use it — it issues these one statement at a time instead.
_BUYERS_TABLE = """CREATE TABLE IF NOT EXISTS buyers (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT NOT NULL,
    -- شناسه ملی / شماره ملی / شناسه مشارکت مدنی / کد فراگیر. Text, never integer:
    -- these carry leading zeros that an integer column would eat.
    national_id   TEXT NOT NULL,
    economic_code TEXT,
    -- نوع شخص خریدار (tob): 1 حقیقی, 2 حقوقی, 3 مشارکت مدنی, 4 اتباع غیرایرانی, 5 مصرف‌کننده
    person_type   INTEGER NOT NULL DEFAULT 2,
    postal_code   TEXT,
    branch_code   TEXT,
    note          TEXT,
    created_at    TEXT NOT NULL,
    UNIQUE (national_id)
);
"""

_GOODS_TABLE = """CREATE TABLE IF NOT EXISTS goods (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    -- شناسه کالا/خدمت (sstid), issued by the organization.
    stuff_id     TEXT NOT NULL,
    description  TEXT NOT NULL,
    -- واحد اندازه‌گیری (mu), from the organization's unit table.
    unit         TEXT,
    -- نرخ مالیات بر ارزش افزوده (vra) that normally applies to this item.
    vat_rate     REAL,
    default_fee  REAL,
    is_default   INTEGER NOT NULL DEFAULT 0,
    created_at   TEXT NOT NULL,
    UNIQUE (stuff_id)
);
"""

_REST = """CREATE TABLE IF NOT EXISTS invoices (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    profile        TEXT NOT NULL,
    state          TEXT NOT NULL,
    tax_id         TEXT,
    uid            TEXT,
    reference_number TEXT,
    -- The invoice as entered, so a draft survives a restart and a sent invoice
    -- keeps the exact payload that was signed.
    payload        TEXT NOT NULL,
    -- Last known validation/inquiry detail, as JSON.
    detail         TEXT,
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS invoices_profile_state ON invoices (profile, state);
CREATE INDEX IF NOT EXISTS invoices_uid ON invoices (uid);
CREATE INDEX IF NOT EXISTS invoices_reference ON invoices (reference_number);

CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""

_SCHEMA = _BUYERS_TABLE + _GOODS_TABLE + _REST


class InvoiceState:
    """Where an invoice is in its life.

    Distinct from :class:`~moadian.models.RequestStatus`, which is the
    organization's answer about a *submission*. An invoice can be DRAFT or
    INVALID without the organization ever having heard of it.
    """

    DRAFT = "draft"
    #: Failed our own rule engine — never sent.
    INVALID = "invalid"
    #: Accepted by `POST /invoice`; the organization has not yet validated it.
    SENT = "sent"
    #: Inquiry returned SUCCESS — registered in کارپوشه.
    CONFIRMED = "confirmed"
    #: Inquiry returned FAILED, with the organization's error codes.
    REJECTED = "rejected"
    #: An ابطالی invoice was issued against it.
    CANCELLED = "cancelled"

    ALL = (DRAFT, INVALID, SENT, CONFIRMED, REJECTED, CANCELLED)


@dataclass
class Buyer:
    """خریدار — reusable across invoices."""

    name: str
    national_id: str
    economic_code: str | None = None
    person_type: int = 2
    postal_code: str | None = None
    branch_code: str | None = None
    note: str | None = None
    id: int | None = None
    created_at: str | None = None

    def validate(self) -> None:
        if not self.name.strip():
            raise ConfigurationError("buyer name must not be empty")
        if not self.national_id.strip():
            raise ConfigurationError("buyer national_id must not be empty")
        if not self.national_id.isdigit():
            # Leading zeros are real; only the digits-only shape is checked here.
            raise ConfigurationError(f"national_id {self.national_id!r} must be digits")
        if self.person_type not in (1, 2, 3, 4, 5):
            raise ConfigurationError(f"person_type {self.person_type} is not a valid نوع شخص")


@dataclass
class GoodsService:
    """شناسه کالا/خدمت plus the defaults an operator wants pre-filled."""

    stuff_id: str
    description: str
    unit: str | None = None
    vat_rate: float | None = None
    default_fee: float | None = None
    is_default: bool = False
    id: int | None = None
    created_at: str | None = None

    def validate(self) -> None:
        if not self.stuff_id.strip():
            raise ConfigurationError("stuff_id (شناسه کالا/خدمت) must not be empty")
        if not self.description.strip():
            raise ConfigurationError("description (شرح کالا/خدمت) must not be empty")
        if self.vat_rate is not None and self.vat_rate < 0:
            raise ConfigurationError("vat_rate must not be negative")


@dataclass
class InvoiceRecord:
    """One invoice as this application knows it."""

    profile: str
    state: str
    payload: dict[str, Any]
    tax_id: str | None = None
    uid: str | None = None
    reference_number: str | None = None
    detail: dict[str, Any] | None = None
    id: int | None = None
    created_at: str | None = None
    updated_at: str | None = None


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class RecordStore:
    """The shared buyer and goods catalogues, plus invoice records per profile."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # One connection guarded by a lock rather than a pool: SQLite writes
        # serialise anyway, and a single-writer story is far easier to reason
        # about than connection-per-request with WAL contention.
        # Reentrant: _migrate reads (via _columns) while holding a write.
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(str(self.path), check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute("PRAGMA foreign_keys=ON")
        # Before the schema script, which is CREATE IF NOT EXISTS throughout and
        # so would leave a v1 table exactly as it found it.
        self._migrate()
        with self._write() as cursor:
            cursor.executescript(_SCHEMA)
            cursor.execute(
                "INSERT OR REPLACE INTO meta (key, value) VALUES ('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )

    # -- migration --------------------------------------------------------

    def _columns(self, table: str) -> set[str]:
        """Column names of ``table``, empty if it does not exist."""
        with self._read() as cursor:
            rows = cursor.execute(f"PRAGMA table_info({table})").fetchall()
        return {row["name"] for row in rows}

    def _migrate(self) -> None:
        """v1 → v2: buyers and goods lose their ``profile`` column.

        Rows entered under different profiles collapse onto the identifier that
        was always the real key — the شناسه ملی for a buyer, the شناسه کالا/خدمت
        for a goods entry. Where two profiles held the same identifier the older
        row wins and the newer is dropped; they describe the same nationally
        issued thing, so there is nothing in the duplicate to preserve.

        Nothing is deleted that is not first copied, and the whole thing runs in
        one transaction: an interrupted upgrade leaves v1 intact.
        """
        with self._write() as cursor:
            if "profile" in self._columns("buyers"):
                cursor.execute("ALTER TABLE buyers RENAME TO buyers_v1")
                cursor.execute(_BUYERS_TABLE)
                cursor.execute(
                    "INSERT INTO buyers (name, national_id, economic_code, person_type, "
                    "postal_code, branch_code, note, created_at) "
                    "SELECT name, national_id, economic_code, person_type, postal_code, "
                    "branch_code, note, created_at FROM buyers_v1 "
                    "WHERE id IN (SELECT MIN(id) FROM buyers_v1 GROUP BY national_id)"
                )
                cursor.execute("DROP TABLE buyers_v1")

            if "profile" in self._columns("goods"):
                cursor.execute("ALTER TABLE goods RENAME TO goods_v1")
                cursor.execute(_GOODS_TABLE)
                cursor.execute(
                    "INSERT INTO goods (stuff_id, description, unit, vat_rate, default_fee, "
                    "is_default, created_at) "
                    "SELECT stuff_id, description, unit, vat_rate, default_fee, is_default, "
                    "created_at FROM goods_v1 "
                    "WHERE id IN (SELECT MIN(id) FROM goods_v1 GROUP BY stuff_id)"
                )
                cursor.execute("DROP TABLE goods_v1")
                # One default per profile becomes several once the profiles
                # merge, and the invoice form has one first line to pre-fill.
                cursor.execute(
                    "UPDATE goods SET is_default = 0 WHERE id NOT IN "
                    "(SELECT MIN(id) FROM goods WHERE is_default = 1)"
                )

    @contextmanager
    def _write(self) -> Iterator[sqlite3.Cursor]:
        with self._lock, self._connection:
            yield self._connection.cursor()

    @contextmanager
    def _read(self) -> Iterator[sqlite3.Cursor]:
        """A read, holding the same lock the writes do.

        Not belt-and-braces. A :class:`sqlite3.Connection` caches prepared
        statements, so two threads running identical SQL share one
        ``sqlite3_stmt`` and rebind it under each other; the loser gets an empty
        result for rows that exist. FastAPI serves sync endpoints from a
        threadpool, so this is reachable from any two concurrent requests — it
        cost :mod:`moadian.auth.store` a random 401 on about one call in twenty,
        and nothing about the mechanism was specific to that table.
        """
        with self._lock:
            yield self._connection.cursor()

    def close(self) -> None:
        self._connection.close()

    # -- buyers -----------------------------------------------------------

    def list_buyers(self) -> list[Buyer]:
        with self._read() as cursor:
            rows = cursor.execute("SELECT * FROM buyers ORDER BY name").fetchall()
        return [self._buyer(row) for row in rows]

    def add_buyer(self, buyer: Buyer) -> Buyer:
        buyer.validate()
        created = _now()
        try:
            with self._write() as cursor:
                cursor.execute(
                    "INSERT INTO buyers (name, national_id, economic_code, "
                    "person_type, postal_code, branch_code, note, created_at) "
                    "VALUES (?,?,?,?,?,?,?,?)",
                    (
                        buyer.name,
                        buyer.national_id,
                        buyer.economic_code,
                        buyer.person_type,
                        buyer.postal_code,
                        buyer.branch_code,
                        buyer.note,
                        created,
                    ),
                )
                buyer.id = cursor.lastrowid
        except sqlite3.IntegrityError as exc:
            raise ConfigurationError(
                f"خریداری با شناسه ملی {buyer.national_id} از پیش ثبت شده است"
            ) from exc
        buyer.created_at = created
        return buyer

    def delete_buyer(self, buyer_id: int) -> None:
        with self._write() as cursor:
            cursor.execute("DELETE FROM buyers WHERE id = ?", (buyer_id,))
            if cursor.rowcount == 0:
                raise ConfigurationError(f"no buyer {buyer_id}")

    @staticmethod
    def _buyer(row: sqlite3.Row) -> Buyer:
        return Buyer(
            id=row["id"],
            name=row["name"],
            national_id=row["national_id"],
            economic_code=row["economic_code"],
            person_type=row["person_type"],
            postal_code=row["postal_code"],
            branch_code=row["branch_code"],
            note=row["note"],
            created_at=row["created_at"],
        )

    # -- goods ------------------------------------------------------------

    def list_goods(self) -> list[GoodsService]:
        with self._read() as cursor:
            rows = cursor.execute(
                "SELECT * FROM goods ORDER BY is_default DESC, description"
            ).fetchall()
        return [self._goods(row) for row in rows]

    def add_goods(self, item: GoodsService) -> GoodsService:
        item.validate()
        created = _now()
        try:
            with self._write() as cursor:
                if item.is_default:
                    # At most one default, so the invoice form has one answer.
                    cursor.execute("UPDATE goods SET is_default = 0")
                cursor.execute(
                    "INSERT INTO goods (stuff_id, description, unit, vat_rate, "
                    "default_fee, is_default, created_at) VALUES (?,?,?,?,?,?,?)",
                    (
                        item.stuff_id,
                        item.description,
                        item.unit,
                        item.vat_rate,
                        item.default_fee,
                        int(item.is_default),
                        created,
                    ),
                )
                item.id = cursor.lastrowid
        except sqlite3.IntegrityError as exc:
            raise ConfigurationError(f"شناسه کالا/خدمت {item.stuff_id} از پیش ثبت شده است") from exc
        item.created_at = created
        return item

    def set_default_goods(self, goods_id: int) -> None:
        with self._write() as cursor:
            cursor.execute("UPDATE goods SET is_default = 0")
            cursor.execute("UPDATE goods SET is_default = 1 WHERE id = ?", (goods_id,))
            if cursor.rowcount == 0:
                raise ConfigurationError(f"no goods {goods_id}")

    def delete_goods(self, goods_id: int) -> None:
        with self._write() as cursor:
            cursor.execute("DELETE FROM goods WHERE id = ?", (goods_id,))
            if cursor.rowcount == 0:
                raise ConfigurationError(f"no goods {goods_id}")

    @staticmethod
    def _goods(row: sqlite3.Row) -> GoodsService:
        return GoodsService(
            id=row["id"],
            stuff_id=row["stuff_id"],
            description=row["description"],
            unit=row["unit"],
            vat_rate=row["vat_rate"],
            default_fee=row["default_fee"],
            is_default=bool(row["is_default"]),
            created_at=row["created_at"],
        )

    # -- invoices ---------------------------------------------------------

    def save_invoice(self, record: InvoiceRecord) -> InvoiceRecord:
        now = _now()
        payload = json.dumps(record.payload, ensure_ascii=False)
        detail = json.dumps(record.detail, ensure_ascii=False) if record.detail else None
        with self._write() as cursor:
            if record.id is None:
                cursor.execute(
                    "INSERT INTO invoices (profile, state, tax_id, uid, reference_number, "
                    "payload, detail, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
                    (
                        record.profile,
                        record.state,
                        record.tax_id,
                        record.uid,
                        record.reference_number,
                        payload,
                        detail,
                        now,
                        now,
                    ),
                )
                record.id = cursor.lastrowid
                record.created_at = now
            else:
                cursor.execute(
                    "UPDATE invoices SET state=?, tax_id=?, uid=?, reference_number=?, "
                    "payload=?, detail=?, updated_at=? WHERE id=?",
                    (
                        record.state,
                        record.tax_id,
                        record.uid,
                        record.reference_number,
                        payload,
                        detail,
                        now,
                        record.id,
                    ),
                )
        record.updated_at = now
        return record

    def list_invoices(
        self, profile: str, state: str | None = None, limit: int = 100
    ) -> list[InvoiceRecord]:
        sql = "SELECT * FROM invoices WHERE profile = ?"
        params: list[Any] = [profile]
        if state:
            sql += " AND state = ?"
            params.append(state)
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        # Materialised inside the lock — a lazy cursor drained after release
        # would be the unguarded access this exists to prevent.
        with self._read() as cursor:
            return [self._invoice(row) for row in cursor.execute(sql, params).fetchall()]

    def list_awaiting_inquiry(self, profile: str, limit: int = 500) -> list[InvoiceRecord]:
        """Records the organization has accepted but not yet ruled on.

        A ``SENT`` record with no شماره پیگیری is one whose batch response
        carried no result for its uid, so there is nothing to inquire by — those
        are excluded rather than reported as pending forever. See
        :class:`~moadian.pipeline.InvoiceSubmission`.
        """
        with self._read() as cursor:
            rows = cursor.execute(
                "SELECT * FROM invoices WHERE profile = ? AND state = ? "
                "AND reference_number IS NOT NULL AND reference_number != '' "
                "ORDER BY id ASC LIMIT ?",
                (profile, InvoiceState.SENT, limit),
            ).fetchall()
        return [self._invoice(row) for row in rows]

    def find_by_tax_id(self, profile: str, tax_id: str) -> InvoiceRecord | None:
        """The record carrying this شماره منحصر به فرد مالیاتی, if we issued it.

        Used to resolve an ابطالی back to the invoice it voids. Scoped to the
        profile: a tax id belongs to one fiscal memory.
        """
        with self._read() as cursor:
            row = cursor.execute(
                "SELECT * FROM invoices WHERE profile = ? AND tax_id = ? ORDER BY id DESC LIMIT 1",
                (profile, tax_id),
            ).fetchone()
        return self._invoice(row) if row else None

    def get_invoice(self, invoice_id: int) -> InvoiceRecord | None:
        with self._read() as cursor:
            row = cursor.execute("SELECT * FROM invoices WHERE id = ?", (invoice_id,)).fetchone()
        return self._invoice(row) if row else None

    def counts_by_state(self, profile: str) -> dict[str, int]:
        """What the dashboard cards show. Every state present, zeros included.

        Omitting empty states would make the dashboard's shape depend on the
        data, which reads as a missing card rather than a count of zero.
        """
        with self._read() as cursor:
            rows = cursor.execute(
                "SELECT state, COUNT(*) AS n FROM invoices WHERE profile = ? GROUP BY state",
                (profile,),
            ).fetchall()
        counts = dict.fromkeys(InvoiceState.ALL, 0)
        for row in rows:
            counts[row["state"]] = row["n"]
        counts["total"] = sum(counts[state] for state in InvoiceState.ALL)
        return counts

    @staticmethod
    def _invoice(row: sqlite3.Row) -> InvoiceRecord:
        return InvoiceRecord(
            id=row["id"],
            profile=row["profile"],
            state=row["state"],
            tax_id=row["tax_id"],
            uid=row["uid"],
            reference_number=row["reference_number"],
            payload=json.loads(row["payload"]),
            detail=json.loads(row["detail"]) if row["detail"] else None,
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
