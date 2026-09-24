"""Load the organization's شناسه کالا/خدمت export into the local catalogue.

Get the CSVs from کارپوشه (اقلام کالا و خدمت → دریافت فایل). The export is split
into parts, and **each part holds a different slice of the list** — the services
export alone is 208k rows and contains no goods at all. So pass every part in
one command:

    .venv/bin/python tools/import_catalogue.py ~/Downloads/product_service_*.csv

The catalogue is replaced wholesale, not merged. The export is a complete
snapshot, and merging a new one into the old would leave codes the organization
has since withdrawn sitting in the table looking exactly like current ones. That
is also why every part goes in one invocation: run it twice with one file each
and the second run discards the first.

**The same code appears more than once, and that is not a duplicate.** The export
carries one row per code per VAT rate. When a rate changes the old row gains an
``ExpirationDate`` and a new row appears with the same شناسه and description — 74k
of the 208k services rows are superseded history like this. All of it is kept,
because an اصلاحی against an old invoice has to reproduce the rate that invoice
carried. Only the unexpired row is ever offered for a new invoice.

Nothing here contacts the organization.
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from moadian.config import Settings  # noqa: E402
from moadian.store import CatalogueStore  # noqa: E402

# A single description in the services export runs to 625 characters, and the
# default limit is low enough that a future export could trip it.
csv.field_size_limit(10 * 1024 * 1024)

#: The export's own column names. Checked rather than assumed: a column that
#: quietly moved would silently import descriptions as VAT rates.
REQUIRED = ("ID", "DescriptionOfID", "Vat", "Taxable", "RunDate", "ExpirationDate", "Type")


def _number(value: str | None) -> float | None:
    if value is None or not value.strip():
        return None
    try:
        return float(value.strip())
    except ValueError:
        return None


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def read(paths: list[Path]) -> Iterator[dict[str, Any]]:
    """Yield catalogue rows from every file, tagging which are still in force.

    ``is_current`` is derived from ``ExpirationDate`` being empty rather than from
    comparing dates: the dates are Jalali, and a comparison would mean a calendar
    conversion — a second thing that can be wrong, in service of a question the
    export already answers directly.
    """
    for path in paths:
        # utf-8-sig, because the export is BOM-prefixed and utf-8 would make the
        # first column name "﻿ID" and every lookup of "ID" miss.
        with path.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            missing = [column for column in REQUIRED if column not in (reader.fieldnames or [])]
            if missing:
                raise SystemExit(
                    f"{path.name}: missing column(s) {', '.join(missing)}.\n"
                    f"Found: {', '.join(reader.fieldnames or ['(nothing)'])}\n"
                    "This does not look like a product/service export."
                )
            for row in reader:
                stuff_id = (row.get("ID") or "").strip()
                description = (row.get("DescriptionOfID") or "").strip()
                if not stuff_id or not description:
                    continue
                expiration = _clean(row.get("ExpirationDate"))
                yield {
                    "stuff_id": stuff_id,
                    "description": description,
                    "vat_rate": _number(row.get("Vat")),
                    "taxable": _clean(row.get("Taxable")),
                    "run_date": _clean(row.get("RunDate")),
                    "expiration_date": expiration,
                    "kind": _clean(row.get("Type")),
                    "pricing": _clean(row.get("PricingDescription")),
                    "is_current": 0 if expiration else 1,
                }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("csv", nargs="+", type=Path, help="every part of the export")
    args = parser.parse_args()

    paths = []
    for path in args.csv:
        if not path.is_file():
            print(f"error: {path} is not a file", file=sys.stderr)
            return 1
        paths.append(path)

    settings = Settings()
    store = CatalogueStore(settings.catalogue_path)
    before = store.status()

    print(f"catalogue : {settings.catalogue_path}")
    if not before["empty"]:
        print(
            f"replacing : {before['total']} row(s) imported at "
            f"{before['importedAt']} from {before['source'] or 'an unnamed source'}"
        )
    for path in paths:
        print(f"reading   : {path.name}")

    written = store.replace_all(read(paths), source=", ".join(p.name for p in paths))
    after = store.status()

    print(f"\nimported  : {written} row(s)")
    print(f"  current   : {after['current']}")
    print(f"  superseded: {after['superseded']}  (kept for اصلاحی against older invoices)")
    if written == 0:
        print(
            "\nNothing was imported. Check that these are product/service exports.",
            file=sys.stderr,
        )
        return 1

    sample = store.search("خدمات", limit=1)
    print(f"  search    : {'answering' if sample else 'INDEX IS EMPTY'}")
    return 0 if sample else 1


if __name__ == "__main__":
    raise SystemExit(main())
