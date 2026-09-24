"""Inspect and repair a fiscal memory's invoice serial counter.

The counter is one small file per شناسه یکتای حافظه مالیاتی holding one integer,
and it is the most dangerous state this application keeps. The serial goes into
every شماره منحصر به فرد مالیاتی and into ``inno``; issuing one twice produces a
duplicate tax id, which the organization rejects and which **no later request
can undo** — the invoice cannot be reissued under that number.

So the file has exactly two failure modes, and they are not symmetric:

* **Too high** — serials are skipped. Harmless. Nothing requires them to be
  contiguous.
* **Too low** — the next invoice reuses a number already filed. Unrecoverable.

Everything here is built around that asymmetry. ``--set`` refuses to move the
counter backwards without ``--force``, and ``--from-taxid`` takes the highest
value it is given rather than the last.

When is this needed? Whenever the counter is lost or suspect and invoices have
already been filed for that memory — a restored backup that predates the last
filing, a rebuilt host, an instance directory deleted by accident. Recovering
the number is possible because **the serial is in the tax id itself**, so any
filed invoice carries it: read the largest one back out and set the counter to
at least that.

    # What does the counter say now?
    .venv/bin/python tools/serial.py --memory-id A11216

    # Recover it from the highest tax id you have filed. Several are fine; the
    # largest wins. Find them in کارپوشه, or via inquiry by time.
    .venv/bin/python tools/serial.py --memory-id A11216 \
        --from-taxid A1121604C220002F095011 A1121604C220002F095022

    # Set it directly, when you know the number.
    .venv/bin/python tools/serial.py --memory-id A11216 --set 12345

Nothing here contacts the organization or submits anything.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from moadian.config import Settings  # noqa: E402
from moadian.errors import MoadianError  # noqa: E402
from moadian.pipeline import MonotonicSerialCounter  # noqa: E402
from moadian.taxid import MAX_SERIAL, TAX_ID_LENGTH, check_digit, decimalise  # noqa: E402

# memoryId(6) | hex(day_range)(5) | hex(serial)(10) | verhoeff(1)
_SERIAL_START = 11
_SERIAL_END = 21


def serial_of(tax_id: str) -> tuple[str, int]:
    """Pull the fiscal memory and the serial back out of a tax id.

    The check digit is verified rather than skipped: this value decides whether
    a number gets reused, and a tax id copied by eye out of a کارپوشه screen is
    exactly the kind of input that arrives with a transposed character.
    """
    tax_id = tax_id.strip().upper()
    if len(tax_id) != TAX_ID_LENGTH:
        raise ValueError(f"{tax_id!r} is {len(tax_id)} characters; a tax id is {TAX_ID_LENGTH}")

    memory_id = tax_id[:6]
    day_hex = tax_id[6:_SERIAL_START]
    serial_hex = tax_id[_SERIAL_START:_SERIAL_END]
    try:
        day_range = int(day_hex, 16)
        serial = int(serial_hex, 16)
    except ValueError as exc:
        raise ValueError(f"{tax_id!r} does not parse as a tax id: {exc}") from exc

    expected = check_digit(f"{decimalise(memory_id)}{day_range:06d}{serial:012d}")
    if tax_id[-1] != str(expected):
        raise ValueError(
            f"{tax_id!r} fails its check digit (got {tax_id[-1]}, expected {expected}). "
            "Re-read it from the source — a mistyped tax id here could set the "
            "counter to the wrong number."
        )
    return memory_id, serial


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--memory-id", required=True, help="شناسه یکتای حافظه مالیاتی")
    parser.add_argument(
        "--from-taxid",
        nargs="+",
        metavar="TAXID",
        help="one or more filed شماره منحصر به فرد مالیاتی; the highest serial in them wins",
    )
    parser.add_argument("--set", type=int, metavar="N", help="set the counter to N")
    parser.add_argument(
        "--force",
        action="store_true",
        help="permit lowering the counter. Reissues serials. Almost never right.",
    )
    args = parser.parse_args()

    if args.set is not None and args.from_taxid:
        print("error: pass --set or --from-taxid, not both", file=sys.stderr)
        return 2

    settings = Settings()
    path = settings.serial_counter_path(args.memory_id)
    counter = MonotonicSerialCounter(path)

    try:
        current = counter.current
    except MoadianError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(f"counter file : {path}")
    print(f"exists       : {path.exists()}")
    print(f"last issued  : {current}   (next invoice would take {current + 1})")

    target = args.set
    if args.from_taxid:
        best = 0
        for tax_id in args.from_taxid:
            try:
                memory_id, serial = serial_of(tax_id)
            except ValueError as exc:
                print(f"error: {exc}", file=sys.stderr)
                return 1
            if memory_id != args.memory_id:
                print(
                    f"error: {tax_id} belongs to fiscal memory {memory_id}, not "
                    f"{args.memory_id}. Each memory has its own counter and they "
                    "must never be crossed.",
                    file=sys.stderr,
                )
                return 1
            print(f"  {tax_id} -> serial {serial}")
            best = max(best, serial)
        target = best

    if target is None:
        return 0

    if target < 0 or target > MAX_SERIAL:
        print(f"error: {target} is outside 0..{MAX_SERIAL}", file=sys.stderr)
        return 1

    if target == current:
        print(f"\nalready {target}; nothing to do")
        return 0

    if target < current and not args.force:
        print(
            f"\nREFUSING to lower the counter from {current} to {target}.\n"
            f"The {target + 1}..{current} range has been issued, and reusing any of "
            "it produces a duplicate tax id that cannot be withdrawn.\n"
            "Pass --force only if you are certain those serials never reached the "
            "organization.",
            file=sys.stderr,
        )
        return 1

    counter._write(target)  # noqa: SLF001 — the repair path; there is no public setter
    print(f"\nset to {target}; the next invoice will take {target + 1}")
    if target < current:
        print("WARNING: lowered under --force. Serials will be reissued.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
