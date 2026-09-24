"""Persian search folding.

Every case here is a real spelling collision from the organization's catalogue.
Without the folding, each one is a search that returns nothing while the row is
sitting in the table — the worst kind of failure, because the screen gives the
operator no reason to doubt the result.
"""

from __future__ import annotations

import pytest

from moadian.persian import fold, fold_digits, is_digits


@pytest.mark.parametrize(
    ("typed", "stored"),
    [
        # Arabic yeh U+064A vs Farsi yeh U+06CC — identical on screen.
        ("آشپزي", "اشپزی"),
        ("مشتري", "مشتری"),
        # Arabic kaf U+0643 vs keheh U+06A9.
        ("كالا", "کالا"),
        ("پزشكي", "پزشکی"),
        # Alef forms.
        ("آموزش", "اموزش"),
        ("إنتقال", "انتقال"),
        ("أحمد", "احمد"),
        # Teh marbuta.
        ("مرحلة", "مرحله"),
        # Waw with hamza.
        ("مؤسسه", "موسسه"),
        # Yeh with hamza.
        ("مسئول", "مسیول"),
    ],
)
def test_spellings_that_look_identical_fold_together(typed: str, stored: str) -> None:
    assert fold(typed) == fold(stored)


def test_zwnj_and_a_space_are_the_same_word_break() -> None:
    """می‌شود and می شود are one word typed two ways; the ZWNJ is invisible."""
    assert fold("می‌شود") == fold("می شود")


def test_tatweel_is_removed() -> None:
    assert fold("کــالا") == fold("کالا")


def test_harakat_are_removed() -> None:
    assert fold("کِتاب") == fold("کتاب")


def test_whitespace_is_collapsed_and_trimmed() -> None:
    assert fold("  نرم    افزار \n") == "نرم افزار"


def test_latin_is_case_folded() -> None:
    """Brand and software names are all over the catalogue."""
    assert fold("Assistelligent") == fold("assistelligent")


def test_folding_is_idempotent() -> None:
    """The query is folded on every keystroke; the index was folded once."""
    once = fold("آموزش آشپزي می‌شود ۱۲۳")
    assert fold(once) == once


def test_folding_empty_text() -> None:
    assert fold("") == ""


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("۲۳۳۰۰۰۴۵۶۷۴۱۳", "2330004567413"),  # Persian digits
        ("٢٣٣٠٠٠٤٥٦٧٤١٣", "2330004567413"),  # Arabic-Indic digits
        ("2330004567413", "2330004567413"),
        ("  ۱۲۳  ", "123"),
    ],
)
def test_digits_fold_to_ascii(text: str, expected: str) -> None:
    """A شناسه pasted out of a Persian PDF arrives in Persian digits."""
    assert fold_digits(text) == expected


def test_fold_keeps_digits_too() -> None:
    assert "2330004567413" in fold("کد ۲۳۳۰۰۰۴۵۶۷۴۱۳")


@pytest.mark.parametrize("text", ["123", "۱۲۳", "٢٣٣", "0", "2330004567413"])
def test_is_digits_accepts_every_digit_system(text: str) -> None:
    assert is_digits(text)


@pytest.mark.parametrize("text", ["", "   ", "abc", "۱۲۳x", "نرم افزار", "123-456"])
def test_is_digits_rejects_everything_else(text: str) -> None:
    assert not is_digits(text)
