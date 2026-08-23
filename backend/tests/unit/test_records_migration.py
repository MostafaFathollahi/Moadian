"""The v1 → v2 upgrade: buyers and goods stop being scoped to a profile.

The point of these tests is that an existing installation does not lose its
address book on upgrade. Everything else about the change is a schema edit;
this is the part that can destroy data.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from moadian.store import Buyer, GoodsService, RecordStore

_V1_SCHEMA = """
CREATE TABLE buyers (
    id INTEGER PRIMARY KEY AUTOINCREMENT, profile TEXT NOT NULL, name TEXT NOT NULL,
    national_id TEXT NOT NULL, economic_code TEXT, person_type INTEGER NOT NULL DEFAULT 2,
    postal_code TEXT, branch_code TEXT, note TEXT, created_at TEXT NOT NULL,
    UNIQUE (profile, national_id)
);
CREATE TABLE goods (
    id INTEGER PRIMARY KEY AUTOINCREMENT, profile TEXT NOT NULL, stuff_id TEXT NOT NULL,
    description TEXT NOT NULL, unit TEXT, vat_rate REAL, default_fee REAL,
    is_default INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL,
    UNIQUE (profile, stuff_id)
);
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
INSERT INTO meta (key, value) VALUES ('schema_version', '1');
"""


@pytest.fixture
def v1_database(tmp_path: Path) -> Path:
    """A store as an existing installation left it, with two profiles in use."""
    path = tmp_path / "records.sqlite"
    connection = sqlite3.connect(path)
    connection.executescript(_V1_SCHEMA)
    connection.executemany(
        "INSERT INTO buyers (profile, name, national_id, created_at) VALUES (?,?,?,?)",
        [
            ("آزمایشی", "شرکت الف", "0012345678", "2026-01-01T00:00:00+00:00"),
            ("عملیاتی", "شرکت الف — دوباره", "0012345678", "2026-02-01T00:00:00+00:00"),
            ("عملیاتی", "شرکت ب", "10100302746", "2026-03-01T00:00:00+00:00"),
        ],
    )
    connection.executemany(
        "INSERT INTO goods (profile, stuff_id, description, is_default, created_at) "
        "VALUES (?,?,?,?,?)",
        [
            ("آزمایشی", "2710000138624", "سرسیلندر", 1, "2026-01-01T00:00:00+00:00"),
            ("عملیاتی", "2710000138624", "سرسیلندر", 1, "2026-02-01T00:00:00+00:00"),
            ("عملیاتی", "1710000138624", "کالای دوم", 1, "2026-03-01T00:00:00+00:00"),
        ],
    )
    connection.commit()
    connection.close()
    return path


def test_the_upgrade_keeps_every_distinct_buyer(v1_database: Path) -> None:
    store = RecordStore(v1_database)
    assert sorted(b.national_id for b in store.list_buyers()) == ["0012345678", "10100302746"]


def test_the_same_national_id_under_two_profiles_collapses_to_the_older_row(
    v1_database: Path,
) -> None:
    """They are the same company. The first spelling of the name is the one kept."""
    store = RecordStore(v1_database)
    duplicated = next(b for b in store.list_buyers() if b.national_id == "0012345678")
    assert duplicated.name == "شرکت الف"


def test_a_leading_zero_survives_the_upgrade(v1_database: Path) -> None:
    store = RecordStore(v1_database)
    assert any(b.national_id == "0012345678" for b in store.list_buyers())


def test_the_upgrade_leaves_exactly_one_default_goods_entry(v1_database: Path) -> None:
    """One default per profile becomes several; the form has one first line."""
    store = RecordStore(v1_database)
    assert sum(1 for g in store.list_goods() if g.is_default) == 1


def test_the_profile_column_is_gone_and_the_version_recorded(v1_database: Path) -> None:
    store = RecordStore(v1_database)
    assert "profile" not in store._columns("buyers")
    assert "profile" not in store._columns("goods")
    version = store._connection.execute(
        "SELECT value FROM meta WHERE key = 'schema_version'"
    ).fetchone()
    assert version[0] == "2"


def test_the_upgrade_is_idempotent(v1_database: Path) -> None:
    """Reopening must not re-run it, nor lose anything if it somehow did."""
    RecordStore(v1_database).close()
    store = RecordStore(v1_database)
    assert len(store.list_buyers()) == 2
    assert len(store.list_goods()) == 2


def test_a_fresh_store_needs_no_fiscal_memory(tmp_path: Path) -> None:
    """The whole point: a catalogue entry before any profile exists."""
    store = RecordStore(tmp_path / "fresh.sqlite")
    store.add_buyer(Buyer(name="خریدار", national_id="10100302746"))
    store.add_goods(GoodsService(stuff_id="271", description="کالا"))
    assert [b.name for b in store.list_buyers()] == ["خریدار"]
    assert [g.stuff_id for g in store.list_goods()] == ["271"]


def test_invoices_stay_scoped_to_their_profile(v1_database: Path) -> None:
    """Only the catalogues were un-scoped. An invoice belongs to one memory."""
    store = RecordStore(v1_database)
    assert "profile" in store._columns("invoices")
