"""The organization's شناسه کالا/خدمت catalogue, searchable.

**Its own database file, not a table in records.sqlite.** The two have opposite
properties and the separation is the point:

* ``records.sqlite`` is irreplaceable. Profiles, invoices, buyers, serial
  counters — if it is lost there is no way to rebuild it.
* The catalogue is reference data published by the organization. It is hundreds
  of thousands of rows, it is replaced wholesale whenever a new export is
  downloaded, and losing it costs one re-import.

Keeping regenerable bulk out of the file that must be backed up means a catalogue
refresh can never put the precious data at risk, and a backup of what matters
stays small enough that someone will actually take one.

**Why every version of a code is kept.** The export carries one row per code per
VAT rate: when a rate changes the old row gains an ``ExpirationDate`` and a new
row appears with the same شناسه and description. Of 208k rows in the services
export, 74k are superseded history. They are kept because an اصلاحی issued
against an old invoice has to reproduce the rate that invoice carried, and
thrown-away history cannot be recovered from the current export. Search only
ever returns current rows — see :meth:`CatalogueStore.search`.
"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from moadian.persian import fold, fold_digits, is_digits

__all__ = ["CatalogueEntry", "CatalogueStore"]

SCHEMA_VERSION = 1

#: Beyond this a "search" is a listing, and the UI cannot show it usefully.
MAX_RESULTS = 100

_SCHEMA = """
CREATE TABLE IF NOT EXISTS catalogue (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    -- شناسه کالا/خدمت. TEXT, never INTEGER: these are identifiers, and one row
    -- in the official services export is 14 digits rather than 13.
    stuff_id        TEXT NOT NULL,
    description     TEXT NOT NULL,
    -- نرخ مالیات بر ارزش افزوده as a percentage, as the export gives it.
    vat_rate        REAL,
    -- مشمول / معاف / غیر مشمول
    taxable         TEXT,
    -- Jalali, exactly as exported. Not converted: these are for the operator to
    -- read, and a conversion is a second thing that can be wrong.
    run_date        TEXT,
    expiration_date TEXT,
    kind            TEXT,
    pricing         TEXT,
    -- Superseded rows are kept but never offered. See the module docstring.
    is_current      INTEGER NOT NULL DEFAULT 1,
    UNIQUE (stuff_id, run_date, vat_rate)
);

CREATE INDEX IF NOT EXISTS catalogue_stuff_id ON catalogue (stuff_id);
CREATE INDEX IF NOT EXISTS catalogue_current ON catalogue (is_current, stuff_id);

CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""

# Contentless (``content=''``): the index stores the terms and the rowid but not
# the text, which is already in `catalogue` and is joined back on that rowid.
#
# NOT external-content (``content='catalogue'``). That variant reads column
# values out of the content table *by column name*, and the text indexed here is
# a folded concatenation of two columns that exists nowhere in `catalogue` —
# FTS5 would look for `catalogue.folded` and not find it. Contentless is both
# smaller and the only one of the two that is correct for a derived column.
#
# prefix='2 3 4' is what makes typing match before a word is finished. The cost
# is index size; the benefit is that a search box feels like one.
_FTS_SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS catalogue_fts USING fts5(
    folded,
    content='',
    tokenize="unicode61 remove_diacritics 2",
    prefix='2 3 4'
);
"""


@dataclass(frozen=True)
class CatalogueEntry:
    """One row of the official catalogue."""

    stuff_id: str
    description: str
    vat_rate: float | None
    taxable: str | None
    run_date: str | None
    expiration_date: str | None
    kind: str | None
    pricing: str | None
    is_current: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "stuffId": self.stuff_id,
            "description": self.description,
            "vatRate": self.vat_rate,
            "taxable": self.taxable,
            "runDate": self.run_date,
            "expirationDate": self.expiration_date,
            "kind": self.kind,
            "pricing": self.pricing,
            "isCurrent": self.is_current,
        }


def _fts_query(text: str) -> str:
    """Turn a person's typing into an FTS5 MATCH expression, safely.

    FTS5 has an expression syntax: bare ``AND``, ``OR``, ``NOT``, ``NEAR``, and
    the characters ``" * ( ) :`` all mean something. Passing a search box
    straight through means a query containing any of them is either a syntax
    error or silently does something else — and Persian text that happens to
    contain a colon is not rare.

    So every token is quoted, which makes it a literal, and then given a ``*``
    to match by prefix. Tokens are ANDed: typing more words narrows, which is
    what the gesture means.
    """
    tokens = [t for t in fold(text).split() if t]
    if not tokens:
        return ""
    # A doubled quote is FTS5's own escape for a quote inside a string.
    return " AND ".join(f'"{t.replace(chr(34), chr(34) * 2)}"*' for t in tokens)


class CatalogueStore:
    """Read and replace the official catalogue.

    One connection behind a lock, for the same reason
    :class:`~moadian.store.records.RecordStore` does it: a
    :class:`sqlite3.Connection` caches prepared statements, and two threads
    running identical SQL rebind each other's parameters. FastAPI serves sync
    endpoints from a threadpool, so two concurrent searches are the ordinary
    case, not an edge one.
    """

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(str(self.path), check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA journal_mode=WAL")
        with self._write() as cursor:
            cursor.executescript(_SCHEMA)
            cursor.executescript(_FTS_SCHEMA)
            cursor.execute(
                "INSERT OR REPLACE INTO meta (key, value) VALUES ('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )

    @contextmanager
    def _write(self) -> Iterator[sqlite3.Cursor]:
        with self._lock, self._connection:
            yield self._connection.cursor()

    @contextmanager
    def _read(self) -> Iterator[sqlite3.Cursor]:
        with self._lock:
            yield self._connection.cursor()

    def close(self) -> None:
        self._connection.close()

    # -- writing ----------------------------------------------------------

    def replace_all(self, rows: Iterable[dict[str, Any]], *, source: str = "") -> int:
        """Replace the catalogue with ``rows`` and rebuild the index.

        Wholesale rather than incremental: the export is a complete snapshot, and
        merging one into the previous contents would leave codes the organization
        has withdrawn sitting in the table forever, indistinguishable from
        current ones. Import every part of a multi-part export in one call.

        Runs in a single transaction, so an interrupted import leaves the
        previous catalogue intact rather than a half-replaced one.
        """
        with self._write() as cursor:
            # A contentless FTS5 table is emptied with this command; a plain
            # DELETE would need the original text back to un-index each row.
            cursor.execute("INSERT INTO catalogue_fts (catalogue_fts) VALUES ('delete-all')")
            cursor.execute("DELETE FROM catalogue")
            cursor.executemany(
                "INSERT OR IGNORE INTO catalogue (stuff_id, description, vat_rate, taxable, "
                "run_date, expiration_date, kind, pricing, is_current) "
                "VALUES (:stuff_id, :description, :vat_rate, :taxable, :run_date, "
                ":expiration_date, :kind, :pricing, :is_current)",
                rows,
            )

            # Indexed after the bulk insert rather than per row: FTS5 is an order
            # of magnitude faster filled in one pass, and the folded text has to
            # be derived in Python either way. Streamed in batches because the
            # services export alone is 208k rows and materialising every folded
            # description at once is tens of megabytes for no reason.
            reader = self._connection.execute("SELECT id, stuff_id, description FROM catalogue")
            while batch := reader.fetchmany(5000):
                cursor.executemany(
                    "INSERT INTO catalogue_fts (rowid, folded) VALUES (?, ?)",
                    [
                        # The identifier is indexed alongside the description so
                        # a query mixing a code and a word still matches.
                        (row["id"], f"{row['stuff_id']} {fold(row['description'])}")
                        for row in batch
                    ],
                )
            cursor.execute("INSERT INTO catalogue_fts (catalogue_fts) VALUES ('optimize')")

            written = cursor.execute("SELECT count(*) FROM catalogue").fetchone()[0]
            cursor.execute(
                "INSERT OR REPLACE INTO meta (key, value) VALUES ('imported_at', ?)",
                (datetime.now(UTC).isoformat(timespec="seconds"),),
            )
            cursor.execute(
                "INSERT OR REPLACE INTO meta (key, value) VALUES ('source', ?)", (source,)
            )
        return written

    # -- reading ----------------------------------------------------------

    def status(self) -> dict[str, Any]:
        """What the admin panel shows: is there a catalogue, and how old is it."""
        with self._read() as cursor:
            total = cursor.execute("SELECT count(*) FROM catalogue").fetchone()[0]
            current = cursor.execute(
                "SELECT count(*) FROM catalogue WHERE is_current = 1"
            ).fetchone()[0]
            meta = dict(cursor.execute("SELECT key, value FROM meta").fetchall())
        return {
            "total": total,
            "current": current,
            "superseded": total - current,
            "importedAt": meta.get("imported_at"),
            "source": meta.get("source") or None,
            "empty": total == 0,
        }

    def get(self, stuff_id: str) -> CatalogueEntry | None:
        """The current row for one شناسه کالا/خدمت, exact match."""
        stuff_id = fold_digits(stuff_id)
        with self._read() as cursor:
            row = cursor.execute(
                "SELECT * FROM catalogue WHERE stuff_id = ? "
                "ORDER BY is_current DESC, run_date DESC LIMIT 1",
                (stuff_id,),
            ).fetchone()
        return _entry(row) if row else None

    def history(self, stuff_id: str) -> list[CatalogueEntry]:
        """Every version of one code, newest first — the VAT rate over time."""
        stuff_id = fold_digits(stuff_id)
        with self._read() as cursor:
            rows = cursor.execute(
                "SELECT * FROM catalogue WHERE stuff_id = ? ORDER BY run_date DESC",
                (stuff_id,),
            ).fetchall()
        return [_entry(row) for row in rows]

    def search(self, query: str, limit: int = 25) -> list[CatalogueEntry]:
        """Find current codes by number or by description.

        Two paths, chosen by what was typed:

        * **All digits** — matched as a prefix of the شناسه. Typing the first few
          digits of a code narrows, and typing all thirteen finds the one row.
          Ordered by the identifier so the result is stable rather than by a
          relevance score that means nothing for an exact identifier.
        * **Anything else** — every word matched as a prefix against the folded
          description, ANDed, ranked by bm25. Identifiers are in the same index,
          so a query mixing a code and a word still works.

        Superseded rows are excluded. Offering an expired VAT rate to someone
        building an invoice would produce a rejection whose cause is invisible
        on the screen that caused it.
        """
        limit = max(1, min(limit, MAX_RESULTS))
        if not query or not query.strip():
            return []

        if is_digits(query):
            needle = fold_digits(query).replace(" ", "")
            with self._read() as cursor:
                rows = cursor.execute(
                    "SELECT * FROM catalogue WHERE is_current = 1 AND stuff_id LIKE ? "
                    "ORDER BY length(stuff_id), stuff_id LIMIT ?",
                    (f"{needle}%", limit),
                ).fetchall()
            return [_entry(row) for row in rows]

        match = _fts_query(query)
        if not match:
            return []
        with self._read() as cursor:
            rows = cursor.execute(
                "SELECT c.* FROM catalogue_fts f JOIN catalogue c ON c.id = f.rowid "
                "WHERE catalogue_fts MATCH ? AND c.is_current = 1 "
                "ORDER BY bm25(catalogue_fts) LIMIT ?",
                (match, limit),
            ).fetchall()
        return [_entry(row) for row in rows]


def _entry(row: sqlite3.Row) -> CatalogueEntry:
    return CatalogueEntry(
        stuff_id=row["stuff_id"],
        description=row["description"],
        vat_rate=row["vat_rate"],
        taxable=row["taxable"],
        run_date=row["run_date"],
        expiration_date=row["expiration_date"],
        kind=row["kind"],
        pricing=row["pricing"],
        is_current=bool(row["is_current"]),
    )
