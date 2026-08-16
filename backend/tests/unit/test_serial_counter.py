"""The persisted invoice serial — the one value in the framework that must never repeat.

The serial is baked into the شماره منحصر به فرد مالیاتی and into ``inno``
(WIRE_FORMAT.md "TaxId"). A repeat produces a duplicate tax id on an invoice the
organization has already accepted, and no later request undoes that. So the
counter is tested for the failures that would cause one: a restart that forgets
where it was, a damaged file that is read as zero, and two callers racing for the
same number.

Everything here touches the real filesystem under ``tmp_path``. There is nothing
to mock — the durability *is* the behaviour under test.
"""

from __future__ import annotations

import os
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

import pytest

from moadian.errors import ConfigurationError
from moadian.pipeline import MonotonicSerialCounter
from moadian.taxid import MAX_SERIAL, generate_tax_id, invoice_serial_hex

MEMORY_ID = "A11216"


def _stored(path: Path) -> int:
    """The value on disk, read the way a restarted process would read it."""
    return int(path.read_text(encoding="ascii").strip())


# ------------------------------------------------------------------- the basics


def test_a_fresh_counter_starts_at_one(tmp_path: Path) -> None:
    """The documented first value. Zero is not a serial — it is "none issued yet"."""
    counter = MonotonicSerialCounter(tmp_path / "serial")

    assert counter.current == 0
    assert counter() == 1
    assert counter.current == 1


def test_successive_calls_never_repeat_and_never_skip(tmp_path: Path) -> None:
    counter = MonotonicSerialCounter(tmp_path / "serial")

    assert [counter() for _ in range(5)] == [1, 2, 3, 4, 5]


def test_current_reports_without_consuming(tmp_path: Path) -> None:
    counter = MonotonicSerialCounter(tmp_path / "serial")
    counter()

    assert counter.current == 1
    assert counter.current == 1
    assert counter() == 2


def test_every_issued_serial_is_on_disk_before_it_is_returned(tmp_path: Path) -> None:
    """A crash between issuing and persisting would reissue the serial after a restart."""
    path = tmp_path / "serial"
    counter = MonotonicSerialCounter(path)

    for expected in range(1, 4):
        assert counter() == expected
        assert _stored(path) == expected


def test_the_counter_creates_its_directory(tmp_path: Path) -> None:
    """`instance/serial` is the documented layout, and `instance/` may not exist yet."""
    path = tmp_path / "instance" / "nested" / "serial"
    counter = MonotonicSerialCounter(path)

    assert counter() == 1
    assert path.is_file()


def test_the_value_file_is_not_left_littered_with_temporaries(tmp_path: Path) -> None:
    """The write goes through a temp file in the same directory; none may survive."""
    path = tmp_path / "serial"
    counter = MonotonicSerialCounter(path)
    for _ in range(3):
        counter()

    assert sorted(p.name for p in tmp_path.iterdir()) == ["serial", "serial.lock"]


# ----------------------------------------------------------------- restarts


def test_a_restart_resumes_rather_than_starting_over(tmp_path: Path) -> None:
    """A new process gets a new object over the same path — and must not reissue 1."""
    path = tmp_path / "serial"
    first = MonotonicSerialCounter(path)
    assert [first(), first(), first()] == [1, 2, 3]

    restarted = MonotonicSerialCounter(path)

    assert restarted.current == 3
    assert restarted() == 4


def test_a_counter_moved_to_a_new_path_starts_over(tmp_path: Path) -> None:
    """Per fiscal memory: two memories have separate files and separate serials."""
    one = MonotonicSerialCounter(tmp_path / "A11216")
    two = MonotonicSerialCounter(tmp_path / "B22317")

    assert one() == 1
    assert two() == 1
    assert one() == 2
    assert two.current == 1


# ------------------------------------------------------------- damaged state


@pytest.mark.parametrize("content", ["", "   ", "nine", "1.5", "0x10", "1 2", "12,3"])
def test_a_corrupt_file_raises_instead_of_restarting_from_zero(
    tmp_path: Path, content: str
) -> None:
    """Reading garbage as zero would reissue every serial already on an invoice."""
    path = tmp_path / "serial"
    path.write_text(content, encoding="utf-8")
    counter = MonotonicSerialCounter(path)

    with pytest.raises(ConfigurationError) as excinfo:
        counter()

    message = str(excinfo.value)
    assert str(path) in message, "the operator must be told which file to fix"
    assert path.read_text(encoding="utf-8") == content, "the damaged file was overwritten"


def test_a_negative_value_raises(tmp_path: Path) -> None:
    path = tmp_path / "serial"
    path.write_text("-7\n", encoding="ascii")
    counter = MonotonicSerialCounter(path)

    with pytest.raises(ConfigurationError) as excinfo:
        counter()

    assert "negative" in str(excinfo.value)
    assert str(path) in str(excinfo.value)


def test_current_refuses_a_corrupt_file_too(tmp_path: Path) -> None:
    """Reporting 0 here would tell an operator the counter is fresh when it is broken."""
    path = tmp_path / "serial"
    path.write_text("nine", encoding="ascii")

    with pytest.raises(ConfigurationError):
        _ = MonotonicSerialCounter(path).current


def test_an_unreadable_path_raises_a_clear_error(tmp_path: Path) -> None:
    """A directory where the value file belongs — a real deployment mistake."""
    path = tmp_path / "serial"
    path.mkdir()
    counter = MonotonicSerialCounter(path)

    with pytest.raises(ConfigurationError) as excinfo:
        counter()

    assert "unreadable" in str(excinfo.value)
    assert str(path) in str(excinfo.value)


def test_a_corrupt_file_is_usable_again_once_repaired(tmp_path: Path) -> None:
    """The documented remedy: an operator writes the last known serial back."""
    path = tmp_path / "serial"
    path.write_text("nine", encoding="ascii")
    counter = MonotonicSerialCounter(path)
    with pytest.raises(ConfigurationError):
        counter()

    path.write_text("41\n", encoding="ascii")

    assert counter() == 42


# ---------------------------------------------------------------- exhaustion


def test_exhaustion_raises_rather_than_wrapping(tmp_path: Path) -> None:
    """The serial is 10 hex digits; past that a tax id cannot represent it."""
    path = tmp_path / "serial"
    path.write_text(f"{MAX_SERIAL}\n", encoding="ascii")
    counter = MonotonicSerialCounter(path)

    with pytest.raises(ConfigurationError) as excinfo:
        counter()

    assert "exhausted" in str(excinfo.value)
    assert _stored(path) == MAX_SERIAL, "the exhausted counter advanced anyway"


def test_the_last_representable_serial_is_still_issued(tmp_path: Path) -> None:
    """Off-by-one guard: MAX_SERIAL itself is a valid serial, not one past the end."""
    path = tmp_path / "serial"
    path.write_text(f"{MAX_SERIAL - 1}\n", encoding="ascii")
    counter = MonotonicSerialCounter(path)

    serial = counter()

    assert serial == MAX_SERIAL
    assert invoice_serial_hex(serial) == "FFFFFFFFFF"
    tax_id = generate_tax_id(MEMORY_ID, serial, datetime.now(UTC))
    assert tax_id[11:21] == "FFFFFFFFFF" and len(tax_id) == 22


# --------------------------------------------------------------- concurrency


def test_concurrent_threads_never_receive_a_duplicate(tmp_path: Path) -> None:
    """Eight threads, one counter: 400 calls must yield 400 distinct serials."""
    counter = MonotonicSerialCounter(tmp_path / "serial")
    threads, per_thread = 8, 50
    barrier = threading.Barrier(threads)

    def draw() -> list[int]:
        barrier.wait()  # start together, so the calls actually overlap
        return [counter() for _ in range(per_thread)]

    with ThreadPoolExecutor(max_workers=threads) as pool:
        drawn = [serial for batch in pool.map(lambda _: draw(), range(threads)) for serial in batch]

    total = threads * per_thread
    assert len(drawn) == total
    assert len(set(drawn)) == total, "a serial was issued twice"
    assert sorted(drawn) == list(range(1, total + 1)), "a serial was skipped"
    assert _stored(tmp_path / "serial") == total


def test_separate_counter_objects_on_one_path_still_never_collide(tmp_path: Path) -> None:
    """Stands in for two processes on one host: the flock, not the thread lock, is what holds.

    Each thread gets its own :class:`MonotonicSerialCounter`, so the in-process
    ``threading.Lock`` guards nothing shared and the sidecar advisory lock is the
    only thing left serialising the read-modify-write.
    """
    path = tmp_path / "serial"
    threads, per_thread = 6, 25
    barrier = threading.Barrier(threads)

    def draw() -> list[int]:
        counter = MonotonicSerialCounter(path)
        barrier.wait()
        return [counter() for _ in range(per_thread)]

    with ThreadPoolExecutor(max_workers=threads) as pool:
        drawn = [serial for batch in pool.map(lambda _: draw(), range(threads)) for serial in batch]

    total = threads * per_thread
    assert len(set(drawn)) == total, "two counters on one file issued the same serial"
    assert sorted(drawn) == list(range(1, total + 1))
    assert _stored(path) == total


def test_serials_drawn_concurrently_produce_distinct_tax_ids(tmp_path: Path) -> None:
    """The property that actually matters: no two invoices share a tax id.

    Same instant, same fiscal memory — so the serial is the only thing keeping the
    ids apart, which is precisely the case the counter exists for.
    """
    counter = MonotonicSerialCounter(tmp_path / "serial")
    issued_at = datetime.now(UTC)

    with ThreadPoolExecutor(max_workers=8) as pool:
        tax_ids = list(
            pool.map(lambda _: generate_tax_id(MEMORY_ID, counter(), issued_at), range(200))
        )

    assert len(set(tax_ids)) == 200


def test_a_lock_file_sits_beside_the_value_not_on_it(tmp_path: Path) -> None:
    """The value file is replaced by rename, so a lock held on it would protect nothing."""
    path = tmp_path / "serial"
    counter = MonotonicSerialCounter(path)
    before = path.exists()
    counter()

    assert not before
    assert (tmp_path / "serial.lock").is_file()
    # The rename really happened: the value file is not the temp file it was written to.
    assert _stored(path) == 1
    assert os.stat(path).st_size == len("1\n")
