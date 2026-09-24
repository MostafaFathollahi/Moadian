"""واحدهای اندازه‌گیری — the unit-of-measure table.

Transcribed by hand from the organization's published list, which makes the
transcription itself worth testing: a wrong code is error 0103502 on a real
filing, and a missing one is a unit the operator cannot select.
"""

from __future__ import annotations

import pytest

from moadian.units import DEFAULT_UNIT, UNITS, unit_name


def test_the_table_has_every_published_row():
    assert len(UNITS) == 97


def test_codes_are_unique():
    """A dict makes this structurally true; the test guards a future edit that
    pastes a duplicate and silently loses one name."""
    assert len(set(UNITS)) == len(UNITS)


def test_names_are_unique():
    """Two identical names in a dropdown are indistinguishable to the operator."""
    assert len(set(UNITS.values())) == len(UNITS)


@pytest.mark.parametrize("code", sorted(UNITS))
def test_every_code_is_a_short_ascii_numeric_string(code: str):
    """§8-30: "رشته عددی، حداکثر ۸". ASCII because Persian digits are a different
    string on the wire, and `"۱۶۴".isdigit()` is True in Python."""
    assert code.isascii() and code.isdigit()
    assert 1 <= len(code) <= 8


@pytest.mark.parametrize("code", sorted(UNITS))
def test_every_code_belongs_to_the_published_16_series(code: str):
    """The table's own shape: 161-169, then 1610-1694, then 16100-16129. An entry
    outside it is a transcription slip, not a new kind of code."""
    assert code.startswith("16")
    assert len(code) in (3, 4, 5)


def test_no_name_is_empty_or_padded():
    assert all(name and name == name.strip() for name in UNITS.values())


def test_names_carry_no_arabic_yeh_or_kaf():
    """Folded on transcription: these are keyboard artefacts in the source table,
    and leaving them in makes a name unsearchable by anyone typing Persian."""
    assert not [n for n in UNITS.values() if "ي" in n or "ك" in n]


@pytest.mark.parametrize(
    ("code", "name"),
    [
        ("1627", "عدد"),
        ("164", "کیلوگرم"),
        ("161", "برگ"),
        ("16129", "دفعه(time)"),
        ("1611", "لنگه"),
        ("1694", "قراصه (bundle)"),
        ("16122", "کیلومتر"),
    ],
)
def test_spot_checks_against_the_published_table(code: str, name: str):
    assert UNITS[code] == name


def test_the_sdk_sample_code_is_kilogram():
    """A cross-check on the whole transcription rather than a fact worth knowing.

    Every sample in the official .NET SDK and the RC_TICS p.20 example invoice use
    mu="164" for a سرسیلندر — a cylinder head, sold by weight. The table agreeing
    with that is evidence the codes did not shift by a row somewhere.
    """
    assert UNITS["164"] == "کیلوگرم"


def test_the_default_is_a_countable_unit_present_in_the_table():
    assert DEFAULT_UNIT in UNITS
    assert UNITS[DEFAULT_UNIT] == "عدد"


def test_unit_name_resolves_and_tolerates_junk():
    assert unit_name("1627") == "عدد"
    assert unit_name(" 1627 ") == "عدد"
    assert unit_name("9999") is None
    assert unit_name("") is None
    assert unit_name(None) is None
