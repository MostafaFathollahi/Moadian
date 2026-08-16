"""SQLite storage for the things an operator maintains between invoices.

Three tables, all scoped to a profile because a شناسه یکتای حافظه مالیاتی belongs
to exactly one environment: a buyer or a goods code entered while pointed at the
sandbox must not silently appear on a production invoice.

Deliberately not an ORM. The schema is four tables wide and the queries are all
"give me the rows for this profile"; SQLAlchemy would be more machinery than the
problem has.
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

SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS buyers (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    profile       TEXT NOT NULL,
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
    UNIQUE (profile, national_id)
);

CREATE TABLE IF NOT EXISTS goods (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    profile      TEXT NOT NULL,
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
    UNIQUE (profile, stuff_id)
);

CREATE TABLE IF NOT EXISTS invoices (
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
    """Buyers, goods and invoice records for every profile."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # One connection guarded by a lock rather than a pool: SQLite writes
        # serialise anyway, and a single-writer story is far easier to reason
        # about than connection-per-request with WAL contention.
        self._lock = threading.Lock()
        self._connection = sqlite3.connect(str(self.path), check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute("PRAGMA foreign_keys=ON")
        with self._write() as cursor:
            cursor.executescript(_SCHEMA)
            cursor.execute(
                "INSERT OR IGNORE INTO meta (key, value) VALUES ('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )

    @contextmanager
    def _write(self) -> Iterator[sqlite3.Cursor]:
        with self._lock, self._connection:
            yield self._connection.cursor()

    def close(self) -> None:
        self._connection.close()

    # -- buyers -----------------------------------------------------------

    def list_buyers(self, profile: str) -> list[Buyer]:
        rows = self._connection.execute(
            "SELECT * FROM buyers WHERE profile = ? ORDER BY name", (profile,)
        ).fetchall()
        return [self._buyer(row) for row in rows]

    def add_buyer(self, profile: str, buyer: Buyer) -> Buyer:
        buyer.validate()
        created = _now()
        try:
            with self._write() as cursor:
                cursor.execute(
                    "INSERT INTO buyers (profile, name, national_id, economic_code, "
                    "person_type, postal_code, branch_code, note, created_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?)",
                    (
                        profile,
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
                f"a buyer with national id {buyer.national_id} already exists in this profile"
            ) from exc
        buyer.created_at = created
        return buyer

    def delete_buyer(self, profile: str, buyer_id: int) -> None:
        with self._write() as cursor:
            cursor.execute("DELETE FROM buyers WHERE profile = ? AND id = ?", (profile, buyer_id))
            if cursor.rowcount == 0:
                raise ConfigurationError(f"no buyer {buyer_id} in profile {profile!r}")

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

    def list_goods(self, profile: str) -> list[GoodsService]:
        rows = self._connection.execute(
            "SELECT * FROM goods WHERE profile = ? ORDER BY is_default DESC, description",
            (profile,),
        ).fetchall()
        return [self._goods(row) for row in rows]

    def add_goods(self, profile: str, item: GoodsService) -> GoodsService:
        item.validate()
        created = _now()
        try:
            with self._write() as cursor:
                if item.is_default:
                    # At most one default per profile, so the form has one answer.
                    cursor.execute("UPDATE goods SET is_default = 0 WHERE profile = ?", (profile,))
                cursor.execute(
                    "INSERT INTO goods (profile, stuff_id, description, unit, vat_rate, "
                    "default_fee, is_default, created_at) VALUES (?,?,?,?,?,?,?,?)",
                    (
                        profile,
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
            raise ConfigurationError(
                f"شناسه کالا/خدمت {item.stuff_id} already exists in this profile"
            ) from exc
        item.created_at = created
        return item

    def set_default_goods(self, profile: str, goods_id: int) -> None:
        with self._write() as cursor:
            cursor.execute("UPDATE goods SET is_default = 0 WHERE profile = ?", (profile,))
            cursor.execute(
                "UPDATE goods SET is_default = 1 WHERE profile = ? AND id = ?",
                (profile, goods_id),
            )
            if cursor.rowcount == 0:
                raise ConfigurationError(f"no goods {goods_id} in profile {profile!r}")

    def delete_goods(self, profile: str, goods_id: int) -> None:
        with self._write() as cursor:
            cursor.execute("DELETE FROM goods WHERE profile = ? AND id = ?", (profile, goods_id))
            if cursor.rowcount == 0:
                raise ConfigurationError(f"no goods {goods_id} in profile {profile!r}")

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
        return [self._invoice(row) for row in self._connection.execute(sql, params)]

    def get_invoice(self, invoice_id: int) -> InvoiceRecord | None:
        row = self._connection.execute(
            "SELECT * FROM invoices WHERE id = ?", (invoice_id,)
        ).fetchone()
        return self._invoice(row) if row else None

    def counts_by_state(self, profile: str) -> dict[str, int]:
        """What the dashboard cards show. Every state present, zeros included.

        Omitting empty states would make the dashboard's shape depend on the
        data, which reads as a missing card rather than a count of zero.
        """
        rows = self._connection.execute(
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
