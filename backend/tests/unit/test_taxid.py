"""Tests for the tax id and its Verhoeff check digit."""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from datetime import UTC, datetime, timedelta, timezone

import pytest

from moadian.errors import InvalidTaxIdError
from moadian.taxid import (
    MAX_SERIAL,
    TAX_ID_LENGTH,
    TEHRAN,
    check_digit,
    decimalise,
    generate_tax_id,
    invoice_serial_hex,
    validate,
)

# Real tax ids lifted from RC_TICS.IS_v1.6 (the §7-1-2 invoice sample and the
# inquiry-response samples). These pin the whole algorithm end to end.
SPEC_TAX_IDS = [
    "A1121604C220002F095011",
    "A111DW04E8300004349008",
    "A111DW04E8300003CC4EA5",
    "A111H104EA6001D0B32AC6",
]


def split(tax_id: str) -> tuple[str, int, int, str]:
    """Decompose a tax id into (memory_id, day_range, serial, check_digit)."""
    return tax_id[:6], int(tax_id[6:11], 16), int(tax_id[11:21], 16), tax_id[21]


def control_text(memory_id: str, day_range: int, serial: int) -> str:
    return f"{decimalise(memory_id)}{day_range:06d}{serial:012d}"


# --------------------------------------------------------------------------- #
# Verhoeff
# --------------------------------------------------------------------------- #


def test_published_vector_check_digit():
    assert check_digit("236") == "3"


def test_published_vector_validate():
    assert validate("2363") is True


@pytest.mark.parametrize(
    ("number", "expected"),
    [("236", "3"), ("12345", "1"), ("142857", "0"), ("123456789", "0"), ("1234567890", "2")],
)
def test_known_check_digits(number: str, expected: str):
    assert check_digit(number) == expected


@pytest.mark.parametrize("number", ["0", "7", "236", "12345", "9999999999", "0000000000000001"])
def test_round_trip(number: str):
    assert validate(number + check_digit(number))


@pytest.mark.parametrize("number", ["236", "142857", "9081726354", "1000000000001"])
def test_detects_every_single_digit_change(number: str):
    full = number + check_digit(number)
    for i, ch in enumerate(full):
        for replacement in "0123456789":
            if replacement == ch:
                continue
            corrupted = full[:i] + replacement + full[i + 1 :]
            assert not validate(corrupted), corrupted


@pytest.mark.parametrize("number", ["236", "142857", "9081726354"])
def test_detects_adjacent_transpositions(number: str):
    full = number + check_digit(number)
    for i in range(len(full) - 1):
        if full[i] == full[i + 1]:
            continue
        swapped = full[:i] + full[i + 1] + full[i] + full[i + 2 :]
        assert not validate(swapped), swapped


def test_leading_zeros_are_significant():
    # The control text is zero-padded, so the implementation must not strip them.
    assert check_digit("0236") != check_digit("236")


@pytest.mark.parametrize("bad", ["", "12A34", "12 34", "12.3", "-1", "۱۲۳"])
def test_rejects_non_ascii_digit_input(bad: str):
    with pytest.raises(ValueError):
        check_digit(bad)
    with pytest.raises(ValueError):
        validate(bad)


# --------------------------------------------------------------------------- #
# decimalise
# --------------------------------------------------------------------------- #


def test_decimalise_documented_case():
    assert decimalise("A11216") == "6511216"


@pytest.mark.parametrize(
    ("memory_id", "expected"),
    [("A111DW", "651116887"), ("A111H1", "65111721"), ("123456", "123456")],
)
def test_decimalise(memory_id: str, expected: str):
    assert decimalise(memory_id) == expected


# --------------------------------------------------------------------------- #
# generate_tax_id — reproduce the documented ids
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("tax_id", SPEC_TAX_IDS)
def test_spec_tax_ids_reproduce(tax_id: str):
    memory_id, day_range, serial, _ = split(tax_id)
    # Pick any instant inside that day range; the field is a whole-day bucket.
    issued_at = datetime.fromtimestamp(day_range * 86_400 + 3_600, tz=UTC)
    assert generate_tax_id(memory_id, serial, issued_at) == tax_id


@pytest.mark.parametrize("tax_id", SPEC_TAX_IDS)
def test_spec_tax_ids_check_digits(tax_id: str):
    memory_id, day_range, serial, digit = split(tax_id)
    assert check_digit(control_text(memory_id, day_range, serial)) == digit


def test_length_and_prefix():
    tax_id = generate_tax_id("A111YO", 123456789, datetime(2024, 1, 1, 12, 0))
    assert len(tax_id) == TAX_ID_LENGTH == 22
    assert tax_id.startswith("A111YO")
    assert tax_id == tax_id.upper()


def test_deterministic():
    args = ("A111YO", 123456789, datetime(2024, 1, 1, 12, 0))
    assert generate_tax_id(*args) == generate_tax_id(*args)


def test_final_digit_validates_against_control_text():
    tax_id = generate_tax_id("A111YO", 987654, datetime(2025, 6, 30, 9, 15))
    memory_id, day_range, serial, digit = split(tax_id)
    assert validate(control_text(memory_id, day_range, serial) + digit)


def test_different_serials_differ():
    when = datetime(2024, 1, 1, 12, 0)
    assert generate_tax_id("A111YO", 100, when) != generate_tax_id("A111YO", 200, when)


def test_lowercase_memory_id_is_normalised():
    when = datetime(2024, 1, 1, 12, 0)
    assert generate_tax_id("a111yo", 100, when) == generate_tax_id("A111YO", 100, when)


# --------------------------------------------------------------------------- #
# Serial boundaries
# --------------------------------------------------------------------------- #


def test_serial_zero():
    tax_id = generate_tax_id("A11216", 0, datetime(2024, 1, 1, 12, 0))
    assert tax_id[11:21] == "0000000000"
    memory_id, day_range, serial, digit = split(tax_id)
    assert serial == 0
    assert validate(control_text(memory_id, day_range, serial) + digit)


def test_max_serial():
    assert MAX_SERIAL == 0xFF_FF_FF_FF_FF
    tax_id = generate_tax_id("A11216", MAX_SERIAL, datetime(2024, 1, 1, 12, 0))
    assert tax_id[11:21] == "FFFFFFFFFF"
    assert len(tax_id) == TAX_ID_LENGTH
    memory_id, day_range, serial, digit = split(tax_id)
    assert serial == MAX_SERIAL
    assert validate(control_text(memory_id, day_range, serial) + digit)


def test_serial_over_max_rejected():
    with pytest.raises(InvalidTaxIdError):
        generate_tax_id("A11216", MAX_SERIAL + 1, datetime(2024, 1, 1, 12, 0))


def test_negative_serial_rejected():
    with pytest.raises(InvalidTaxIdError):
        generate_tax_id("A11216", -1, datetime(2024, 1, 1, 12, 0))


@pytest.mark.parametrize("memory_id", ["", "A1121", "A112166", "A1121!", "A1121ب"])
def test_bad_memory_id_rejected(memory_id: str):
    with pytest.raises(InvalidTaxIdError):
        generate_tax_id(memory_id, 1, datetime(2024, 1, 1, 12, 0))


def test_pre_epoch_date_rejected():
    with pytest.raises(InvalidTaxIdError):
        generate_tax_id("A11216", 1, datetime(1969, 1, 1, 12, 0))


# --------------------------------------------------------------------------- #
# inno
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("serial", "expected"),
    [(0, "0000000000"), (1, "0000000001"), (49321217, "0002F09501"), (MAX_SERIAL, "FFFFFFFFFF")],
)
def test_invoice_serial_hex(serial: int, expected: str):
    assert invoice_serial_hex(serial) == expected


def test_invoice_serial_hex_matches_tax_id_segment():
    serial = 49321217
    tax_id = generate_tax_id("A11216", serial, datetime(2023, 5, 13, 12, 0))
    assert tax_id[11:21] == invoice_serial_hex(serial)


@pytest.mark.parametrize("serial", [-1, MAX_SERIAL + 1])
def test_invoice_serial_hex_rejects_out_of_range(serial: int):
    with pytest.raises(InvalidTaxIdError):
        invoice_serial_hex(serial)


# --------------------------------------------------------------------------- #
# Timezone — the part that silently corrupts ids near midnight
# --------------------------------------------------------------------------- #

# 2024-01-01 00:10 Tehran == 2023-12-31 20:40 UTC. The two instants straddle a
# UTC calendar day, so a naive-as-UTC reading would land in a different bucket.
NEAR_MIDNIGHT_NAIVE = datetime(2024, 1, 1, 0, 10)
NEAR_MIDNIGHT_UTC = datetime(2023, 12, 31, 20, 40, tzinfo=UTC)


def test_naive_is_interpreted_as_tehran_not_utc():
    assert NEAR_MIDNIGHT_NAIVE.replace(tzinfo=TEHRAN) == NEAR_MIDNIGHT_UTC
    naive = generate_tax_id("A11216", 42, NEAR_MIDNIGHT_NAIVE)
    aware = generate_tax_id("A11216", 42, NEAR_MIDNIGHT_UTC)
    assert naive == aware

    # ...and it is genuinely not the naive-as-UTC answer.
    as_utc = generate_tax_id("A11216", 42, NEAR_MIDNIGHT_NAIVE.replace(tzinfo=UTC))
    assert as_utc != naive


def test_aware_input_is_converted_not_reinterpreted():
    """The same instant expressed in any zone yields the same tax id."""
    ids = {
        generate_tax_id("A11216", 7, NEAR_MIDNIGHT_UTC.astimezone(tz))
        for tz in (UTC, TEHRAN, timezone(timedelta(hours=-8)), timezone(timedelta(hours=13)))
    }
    assert len(ids) == 1


def test_day_range_rolls_at_tehran_midnight():
    before = generate_tax_id("A11216", 1, datetime(2024, 1, 1, 3, 20))
    after = generate_tax_id("A11216", 1, datetime(2024, 1, 1, 3, 40))
    # 03:30 Tehran is 00:00 UTC, where the epoch-day bucket advances.
    assert before[6:11] != after[6:11]

    same_a = generate_tax_id("A11216", 1, datetime(2024, 1, 1, 4, 0))
    same_b = generate_tax_id("A11216", 1, datetime(2024, 1, 2, 3, 0))
    assert same_a[6:11] == same_b[6:11]


_HOST_TZ_PROBE = textwrap.dedent(
    """
    from datetime import datetime, timezone
    from moadian.taxid import generate_tax_id
    naive = generate_tax_id("A11216", 42, datetime(2024, 1, 1, 0, 10))
    aware = generate_tax_id("A11216", 42, datetime(2023, 12, 31, 20, 40, tzinfo=timezone.utc))
    print(naive, aware)
    """
)


@pytest.mark.parametrize(
    "host_tz", ["UTC", "Asia/Tehran", "America/Los_Angeles", "Pacific/Kiritimati"]
)
def test_result_does_not_depend_on_host_timezone(host_tz: str):
    """Run in a subprocess: TZ is read once at process start, so it must be set there."""
    env = {**os.environ, "TZ": host_tz}
    out = subprocess.run(
        [sys.executable, "-c", _HOST_TZ_PROBE],
        capture_output=True,
        text=True,
        check=True,
        env=env,
    ).stdout.split()
    naive, aware = out
    assert naive == aware
    # Same answer as this process, whatever the host zone.
    assert naive == generate_tax_id("A11216", 42, NEAR_MIDNIGHT_NAIVE)
