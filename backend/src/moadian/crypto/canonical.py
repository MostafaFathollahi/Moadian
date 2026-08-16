"""Canonical JSON serialisation for bytes that get signed.

The rules come from WIRE_FORMAT.md "Invoice JSON": omit unset fields, compact
separators, and never escape non-ASCII.
"""

from __future__ import annotations

import json
from typing import Any

from moadian.errors import CryptographyError

__all__ = ["canonical_json", "strip_nulls"]


def strip_nulls(obj: Any) -> Any:
    """Recursively drop ``None``-valued keys from mappings.

    List elements are left alone: the tax organization indexes ``body`` and
    ``payments`` rows positionally, so dropping a null element would silently
    shift every row after it.
    """
    if isinstance(obj, dict):
        return {k: strip_nulls(v) for k, v in obj.items() if v is not None}
    if isinstance(obj, list):
        return [strip_nulls(v) for v in obj]
    return obj


def canonical_json(obj: Any) -> bytes:
    """Serialise ``obj`` to the exact UTF-8 bytes that are signed.

    Compact separators, ``ensure_ascii=False`` so Persian text travels as UTF-8
    rather than ``\\uXXXX``, and null/unset fields omitted entirely.

    ``allow_nan=False``: Python's default would emit the JavaScript literals
    ``NaN``/``Infinity``/``-Infinity``, which RFC 8259 has no production for. Those
    bytes would still be signed and encrypted, so the rejection would arrive from
    the organization *after* a tax id had been burned. Fail here instead.

    :raises CryptographyError: the object cannot be serialised to valid JSON —
        a non-finite float, or a structure json cannot walk.
    """
    try:
        return json.dumps(
            strip_nulls(obj),
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except ValueError as exc:
        # ValueError covers both "Out of range float values are not JSON
        # compliant" (allow_nan=False) and "Circular reference detected".
        raise CryptographyError(
            f"payload cannot be canonicalised to valid JSON and must not be signed: {exc}"
        ) from exc
