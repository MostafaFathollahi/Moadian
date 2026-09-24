"""The serial-counter repair tool.

Tested at unit level because the value it writes decides whether a
شماره منحصر به فرد مالیاتی gets reused, and a reused tax id cannot be withdrawn.
The asymmetry drives every case here: too high is harmless, too low is
unrecoverable.
"""

from __future__ import annotations

import importlib.util
from datetime import UTC, datetime
from pathlib import Path

import pytest

from moadian.taxid import MAX_SERIAL, generate_tax_id

_TOOL = Path(__file__).resolve().parents[2] / "tools" / "serial.py"


def _load():
    spec = importlib.util.spec_from_file_location("serial_tool", _TOOL)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


tool = _load()

ISSUED = datetime(2026, 9, 24, tzinfo=UTC)


@pytest.mark.parametrize("serial", [1, 7, 255, 12345, 0x2F09501, MAX_SERIAL])
def test_the_serial_round_trips_through_a_tax_id(serial: int) -> None:
    """The recovery only works because the serial is carried in the id itself."""
    tax_id = generate_tax_id("A11216", serial, ISSUED)
    memory_id, recovered = tool.serial_of(tax_id)
    assert memory_id == "A11216"
    assert recovered == serial


def test_a_mistyped_tax_id_is_rejected() -> None:
    """A tax id read by eye off a کارپوشه screen arrives transposed sooner or later.

    Accepting one would set the counter to a number that was never issued — and
    if it lands low, every invoice after it collides.
    """
    tax_id = generate_tax_id("A11216", 500, ISSUED)
    digit = tax_id[12]
    tampered = tax_id[:12] + ("0" if digit != "0" else "1") + tax_id[13:]
    with pytest.raises(ValueError, match="check digit"):
        tool.serial_of(tampered)


@pytest.mark.parametrize("bad", ["", "A11216", "A11216050F0000000303901", "not-a-tax-id-at-all!!!"])
def test_something_that_is_not_a_tax_id_is_rejected(bad: str) -> None:
    with pytest.raises(ValueError):
        tool.serial_of(bad)


def test_lowercase_and_surrounding_space_are_accepted() -> None:
    """Copied out of a spreadsheet, a tax id arrives with both."""
    tax_id = generate_tax_id("A11216", 4242, ISSUED)
    assert tool.serial_of(f"  {tax_id.lower()}  ")[1] == 4242


def _run(monkeypatch, tmp_path: Path, *argv: str) -> int:
    monkeypatch.setenv("MOADIAN_INSTANCE_DIR", str(tmp_path))
    monkeypatch.setattr("sys.argv", ["serial.py", *argv])
    return tool.main()


def test_a_missing_counter_reads_as_zero(monkeypatch, tmp_path, capsys) -> None:
    assert _run(monkeypatch, tmp_path, "--memory-id", "A11216") == 0
    assert "last issued  : 0" in capsys.readouterr().out


def test_recovery_takes_the_highest_of_several_tax_ids(monkeypatch, tmp_path) -> None:
    """Order must not matter — these come off a screen, not out of a sorted list."""
    low = generate_tax_id("A11216", 100, ISSUED)
    high = generate_tax_id("A11216", 900, ISSUED)
    assert _run(monkeypatch, tmp_path, "--memory-id", "A11216", "--from-taxid", high, low) == 0
    assert (tmp_path / "serial-A11216").read_text().strip() == "900"


def test_lowering_the_counter_is_refused(monkeypatch, tmp_path) -> None:
    """The failure this tool exists to prevent."""
    (tmp_path / "serial-A11216").write_text("900\n")
    assert _run(monkeypatch, tmp_path, "--memory-id", "A11216", "--set", "5") == 1
    assert (tmp_path / "serial-A11216").read_text().strip() == "900", "counter was modified"


def test_lowering_is_permitted_under_force(monkeypatch, tmp_path) -> None:
    (tmp_path / "serial-A11216").write_text("900\n")
    assert _run(monkeypatch, tmp_path, "--memory-id", "A11216", "--set", "5", "--force") == 0
    assert (tmp_path / "serial-A11216").read_text().strip() == "5"


def test_raising_the_counter_needs_no_force(monkeypatch, tmp_path) -> None:
    """Skipping serials is harmless; nothing requires them to be contiguous."""
    (tmp_path / "serial-A11216").write_text("10\n")
    assert _run(monkeypatch, tmp_path, "--memory-id", "A11216", "--set", "9000") == 0
    assert (tmp_path / "serial-A11216").read_text().strip() == "9000"


def test_a_tax_id_from_another_fiscal_memory_is_refused(monkeypatch, tmp_path) -> None:
    """Each memory has its own counter; crossing them corrupts both."""
    other = generate_tax_id("A11216", 900, ISSUED)
    assert _run(monkeypatch, tmp_path, "--memory-id", "B22327", "--from-taxid", other) == 1
    assert not (tmp_path / "serial-B22327").exists()


def test_set_and_from_taxid_together_is_refused(monkeypatch, tmp_path) -> None:
    tax_id = generate_tax_id("A11216", 900, ISSUED)
    assert (
        _run(monkeypatch, tmp_path, "--memory-id", "A11216", "--set", "5", "--from-taxid", tax_id)
        == 2
    )


def test_a_serial_past_the_maximum_is_refused(monkeypatch, tmp_path) -> None:
    assert _run(monkeypatch, tmp_path, "--memory-id", "A11216", "--set", str(MAX_SERIAL + 1)) == 1
    assert not (tmp_path / "serial-A11216").exists()


def test_the_written_value_is_what_the_counter_then_issues(monkeypatch, tmp_path) -> None:
    """The repair has to agree with the thing it repairs."""
    from moadian.pipeline import MonotonicSerialCounter

    assert _run(monkeypatch, tmp_path, "--memory-id", "A11216", "--set", "4242") == 0
    counter = MonotonicSerialCounter(tmp_path / "serial-A11216")
    assert counter.current == 4242
    assert counter() == 4243
