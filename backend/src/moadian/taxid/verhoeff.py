"""Verhoeff check digit — the error-detection scheme behind the tax id's last digit.

Ported from the official .NET SDK
(``TaxCollectData.Library/Algorithms/VerhoeffAlgorithm.cs``) and cross-checked
against the published vectors. The digit iteration runs over the *reversed*
number, which is the detail most ports get wrong.
"""

from __future__ import annotations

__all__ = ["check_digit", "validate"]

_ASCII_DIGITS = frozenset("0123456789")

# Multiplication table of the dihedral group D5.
_D: tuple[tuple[int, ...], ...] = (
    (0, 1, 2, 3, 4, 5, 6, 7, 8, 9),
    (1, 2, 3, 4, 0, 6, 7, 8, 9, 5),
    (2, 3, 4, 0, 1, 7, 8, 9, 5, 6),
    (3, 4, 0, 1, 2, 8, 9, 5, 6, 7),
    (4, 0, 1, 2, 3, 9, 5, 6, 7, 8),
    (5, 9, 8, 7, 6, 0, 4, 3, 2, 1),
    (6, 5, 9, 8, 7, 1, 0, 4, 3, 2),
    (7, 6, 5, 9, 8, 2, 1, 0, 4, 3),
    (8, 7, 6, 5, 9, 3, 2, 1, 0, 4),
    (9, 8, 7, 6, 5, 4, 3, 2, 1, 0),
)

# Permutation table; row is chosen by position modulo 8.
_P: tuple[tuple[int, ...], ...] = (
    (0, 1, 2, 3, 4, 5, 6, 7, 8, 9),
    (1, 5, 7, 6, 2, 8, 3, 0, 9, 4),
    (5, 8, 0, 3, 7, 9, 6, 1, 4, 2),
    (8, 9, 1, 6, 0, 4, 3, 5, 2, 7),
    (9, 4, 5, 3, 1, 2, 6, 8, 7, 0),
    (4, 2, 8, 6, 5, 7, 3, 9, 0, 1),
    (2, 7, 9, 3, 8, 0, 6, 4, 1, 5),
    (7, 0, 4, 6, 9, 1, 3, 2, 5, 8),
)

# Multiplicative inverse in D5.
_INV: tuple[int, ...] = (0, 4, 3, 2, 1, 5, 6, 7, 8, 9)


def _reversed_digits(number: str) -> list[int]:
    """Least-significant digit first.

    Rejects non-ASCII digits explicitly: ``"۱۲۳".isdigit()`` is true and
    ``int()`` accepts it, so a Persian-digit string would otherwise checksum
    silently and produce a tax id the organization cannot reproduce.
    """
    if not number:
        raise ValueError("number must not be empty")
    bad = next((ch for ch in number if ch not in _ASCII_DIGITS), None)
    if bad is not None:
        raise ValueError(f"number must be ASCII digits only, found {bad!r}")
    return [ord(ch) - 48 for ch in reversed(number)]


def check_digit(number: str) -> str:
    """Return the single Verhoeff check digit for ``number``."""
    c = 0
    for i, digit in enumerate(_reversed_digits(number)):
        c = _D[c][_P[(i + 1) % 8][digit]]
    return str(_INV[c])


def validate(number_with_check_digit: str) -> bool:
    """Return whether ``number_with_check_digit`` carries a correct trailing digit."""
    c = 0
    for i, digit in enumerate(_reversed_digits(number_with_check_digit)):
        c = _D[c][_P[i % 8][digit]]
    return c == 0
