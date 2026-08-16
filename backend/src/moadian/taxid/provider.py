"""Generation of the شماره منحصر به فرد مالیاتی (tax id) and the ``inno`` serial.

Layout (WIRE_FORMAT.md "TaxId"), 22 characters, uppercase::

    memoryId(6) | hex(day_range)(5) | hex(serial)(10) | verhoeff(1)

The check digit is computed over a *decimal* rendering of the same three parts,
not over the hex text.
"""

from __future__ import annotations

import math
import re
from datetime import datetime
from zoneinfo import ZoneInfo

from moadian.errors import InvalidTaxIdError

from .verhoeff import check_digit

__all__ = [
    "TEHRAN",
    "TAX_ID_LENGTH",
    "MAX_SERIAL",
    "generate_tax_id",
    "invoice_serial_hex",
    "decimalise",
]

TEHRAN = ZoneInfo("Asia/Tehran")

TAX_ID_LENGTH = 22

# The serial occupies exactly 10 hex digits.
MAX_SERIAL = 0xFF_FF_FF_FF_FF

# day_range occupies exactly 5 hex digits; 0xFFFFF days after the epoch is year 4840.
_MAX_DAY_RANGE = 0xF_FF_FF

_SECONDS_PER_DAY = 86_400

_MEMORY_ID_RE = re.compile(r"[0-9A-Za-z]{6}")


def _to_tehran(moment: datetime) -> datetime:
    """Anchor ``moment`` to Asia/Tehran.

    Naive input is *interpreted* as Tehran wall-clock; aware input is
    *converted*. Pinning this is the whole point — the .NET reference builds a
    ``DateTimeOffset`` from an unspecified-kind ``DateTime``, so it silently
    picks up the host timezone and a UTC host disagrees with a Tehran host near
    midnight.
    """
    if moment.tzinfo is None or moment.tzinfo.utcoffset(moment) is None:
        return moment.replace(tzinfo=TEHRAN)
    return moment.astimezone(TEHRAN)


def _day_range(issued_at: datetime) -> int:
    """Whole days between the Unix epoch and ``issued_at``."""
    # .timestamp() is the true UTC epoch of the anchored instant, matching the
    # .NET reference's DateTimeOffset(...).ToUnixTimeSeconds(). Floor rather than
    # truncate so sub-second and pre-epoch values do not drift by a day.
    return math.floor(_to_tehran(issued_at).timestamp()) // _SECONDS_PER_DAY


def decimalise(memory_id: str) -> str:
    """Map a fiscal memory id to the digits used in the check-digit control text.

    Digits pass through; letters become their code point, so ``A`` → ``65``.
    Exposed for testing.
    """
    return "".join(ch if ch in "0123456789" else str(ord(ch)) for ch in memory_id)


def _validate_memory_id(memory_id: str) -> str:
    if not isinstance(memory_id, str) or not _MEMORY_ID_RE.fullmatch(memory_id):
        raise InvalidTaxIdError(
            f"memory_id must be 6 alphanumeric ASCII characters, got {memory_id!r}"
        )
    # Uppercase before anything else. The emitted tax id is uppercased wholesale,
    # so a lowercase memory_id would otherwise produce a tax id whose check digit
    # was computed over control text nobody can rederive from the tax id itself.
    return memory_id.upper()


def _validate_serial(serial: int) -> int:
    if isinstance(serial, bool) or not isinstance(serial, int):
        raise InvalidTaxIdError(f"serial must be an int, got {type(serial).__name__}")
    if serial < 0:
        raise InvalidTaxIdError(f"serial must be non-negative, got {serial}")
    if serial > MAX_SERIAL:
        raise InvalidTaxIdError(f"serial must fit 10 hex digits (<= {MAX_SERIAL}), got {serial}")
    return serial


def generate_tax_id(memory_id: str, serial: int, issued_at: datetime) -> str:
    """Build the 22-character tax id for one invoice.

    ``serial`` must be non-repeating per fiscal memory — use a persisted
    monotonic counter, never a random draw.
    """
    memory_id = _validate_memory_id(memory_id)
    serial = _validate_serial(serial)

    day_range = _day_range(issued_at)
    if not 0 <= day_range <= _MAX_DAY_RANGE:
        raise InvalidTaxIdError(
            f"issued_at is outside the representable range (day_range={day_range})"
        )

    control = f"{decimalise(memory_id)}{day_range:06d}{serial:012d}"
    return f"{memory_id}{day_range:05X}{serial:010X}{check_digit(control)}"


def invoice_serial_hex(serial: int) -> str:
    """The ``inno`` field: the serial as 10 uppercase hex digits.

    Same rendering as the serial segment of the tax id, so the two always agree.
    """
    return f"{_validate_serial(serial):010X}"
