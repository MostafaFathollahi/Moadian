"""واحدهای اندازه‌گیری — the unit-of-measure table.

Transcribed from RC_UMGS.ST_V1.18, which makes the transcription itself worth
testing: a wrong code is error 0103502 on a real filing, and a missing one is a
unit the operator cannot select.
"""

from __future__ import annotations

import pytest

from moadian.units import DEFAULT_UNIT, UNITS, unit_name


def test_the_table_has_every_published_row():
    """RC_UMGS.ST_V1.18 — ردیف 1 تا 102."""
    assert len(UNITS) == 102


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
    """The table's own shape: 161-169, then 1610-1694, then 16100-16134. An entry
    outside it is a transcription slip, not a new kind of code."""
    assert code.startswith("16")
    assert len(code) in (3, 4, 5)


def test_the_gaps_in_the_numbering_are_the_documents_own():
    """16106, 16107, 16109, 16123 and 16124 are simply not in RC_UMGS.ST_V1.18.

    Asserted so that a future transcription which quietly invents them — or one
    that drops a real code and leaves a gap that looks like these — is caught.
    """
    assert not ({"16106", "16107", "16109", "16123", "16124"} & set(UNITS))


@pytest.mark.parametrize(
    ("code", "name"),
    [
        ("16130", "مگا یونیت"),
        ("16131", "کادر"),
        ("16132", "پرس"),
        ("16133", "بلوک"),
        ("16134", "نفر-ماه"),
    ],
)
def test_the_codes_added_since_v1_16_are_present(code: str, name: str):
    """V1.18's own changelog records نفر-ماه as ردیف ۱۰۲. These five are the ones
    an older copy of the table would be missing."""
    assert UNITS[code] == name


def test_names_mangled_by_the_pdf_text_layer_are_repaired():
    """The PDF renders these with the parenthesis on the wrong side, or half of
    one missing, or two words run together. A name is what the operator picks
    from, so it has to read correctly."""
    assert UNITS["1668"] == "حلقه (رینگ)"
    assert UNITS["1630"] == "حلقه (رول)"
    assert UNITS["1667"] == "حلقه (دیسک)"
    assert UNITS["16120"] == "نسخه (جلد)"
    assert UNITS["1694"] == "قراصه (bundle)"
    assert UNITS["1693"] == "کارتن (case master)"
    assert UNITS["16129"] == "دفعه (time)"
    assert UNITS["1679"] == "فوت مربع"


def test_the_skein_is_spelled_as_the_document_spells_it():
    """کلاف, not کالف. The reversed form is what لا does to a naive text
    extraction, and it had made it into an earlier copy of this table."""
    assert UNITS["1610"] == "کلاف"


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
        ("16129", "دفعه (time)"),
        ("1611", "لنگه"),
        ("16122", "کیلومتر"),
        ("16134", "نفر-ماه"),
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
