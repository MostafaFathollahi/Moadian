"""Concurrent reads must not fabricate missing rows.

A :class:`sqlite3.Connection` caches prepared statements, so two threads running
identical SQL share one ``sqlite3_stmt`` and rebind it under each other. The
loser's ``fetchone()`` returns nothing for a row that plainly exists.

FastAPI serves sync endpoints from a threadpool, and every authenticated request
re-reads the caller through the same ``SELECT * FROM users WHERE id = ?``. So the
collision landed on :meth:`UserStore.get`, ``current_user`` read ``None`` as
"کاربر یافت نشد" and answered 401, and the browser — which clears the session on
any 401 — bounced the operator to the login screen. Roughly one request in
twenty, and worst right after a page switch, when several go out together.

These tests are the reason the reads take the lock.
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from moadian.auth.store import UserStore
from moadian.store import Buyer, GoodsService, InvoiceRecord, InvoiceState, RecordStore

THREADS = 8
ROUNDS = 150


def _hammer(work) -> list[object]:
    """Run ``work`` from several threads at once and collect every result."""
    results: list[object] = []
    errors: list[BaseException] = []
    lock = threading.Lock()

    def run() -> None:
        for _ in range(ROUNDS):
            try:
                value = work()
            except BaseException as exc:  # noqa: BLE001 - the point is to see it
                with lock:
                    errors.append(exc)
                return
            with lock:
                results.append(value)

    threads = [threading.Thread(target=run) for _ in range(THREADS)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert not errors, f"concurrent reads raised: {errors[:3]}"
    return results


@pytest.fixture
def users(tmp_path: Path) -> UserStore:
    store = UserStore(tmp_path / "users.sqlite")
    store.create(username="admin", password="admin1234", role="admin")
    return store


def test_concurrent_get_never_loses_the_user(users: UserStore) -> None:
    """The 401 bug, reduced to one call. Every read must find the account."""
    admin = users.by_username("admin")
    assert admin is not None
    found = _hammer(lambda: users.get(admin.id))
    assert all(user is not None for user in found), (
        f"{sum(u is None for u in found)} of {len(found)} concurrent reads lost a live account"
    )


def test_concurrent_get_returns_the_right_user(users: UserStore) -> None:
    """Not merely non-None — a rebound statement could return another row."""
    users.create(username="second", password="second1234")
    admin = users.by_username("admin")
    assert admin is not None
    assert {user.username for user in _hammer(lambda: users.get(admin.id))} == {"admin"}


def test_concurrent_auth_epoch_is_stable(users: UserStore) -> None:
    """Read on the same hot path as get(), on every authenticated request."""
    epoch = users.revoke_all_sessions()
    assert set(_hammer(users.auth_epoch)) == {epoch}


def test_concurrent_reads_survive_a_writer(users: UserStore) -> None:
    """Requests do not politely stop arriving while an admin edits an account."""
    admin = users.by_username("admin")
    assert admin is not None
    stop = threading.Event()

    def churn() -> None:
        names = ("الف", "ب")
        index = 0
        while not stop.is_set():
            users.update(admin.id, display_name=names[index % 2])
            index += 1

    writer = threading.Thread(target=churn, daemon=True)
    writer.start()
    try:
        found = _hammer(lambda: users.get(admin.id))
    finally:
        stop.set()
        writer.join(timeout=5)
    assert all(user is not None for user in found)


@pytest.fixture
def records(tmp_path: Path) -> RecordStore:
    store = RecordStore(tmp_path / "records.sqlite")
    store.add_buyer(Buyer(name="خریدار", national_id="10100302746"))
    store.add_goods(GoodsService(stuff_id="2710000138624", description="سرسیلندر"))
    store.save_invoice(
        InvoiceRecord(profile="آزمایشی", state=InvoiceState.DRAFT, payload={"header": {}})
    )
    return store


def test_concurrent_catalogue_reads_are_complete(records: RecordStore) -> None:
    """Nothing about the mechanism was specific to the users table."""
    assert set(_hammer(lambda: len(records.list_buyers()))) == {1}
    assert set(_hammer(lambda: len(records.list_goods()))) == {1}


def test_concurrent_dashboard_counts_are_stable(records: RecordStore) -> None:
    """What the dashboard asks for on every page switch."""
    assert set(_hammer(lambda: records.counts_by_state("آزمایشی")["total"])) == {1}


def test_concurrent_invoice_listing_is_complete(records: RecordStore) -> None:
    assert set(_hammer(lambda: len(records.list_invoices("آزمایشی")))) == {1}
