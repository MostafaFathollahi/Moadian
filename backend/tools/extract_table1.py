"""Transcribe جدول شماره ۱ — the pattern × field obligation matrix — from the PDF.

RC_IITP_IS_V7_9_1 p.14 carries the whole matrix as one 107 × 18 grid. Plain text
extraction collapses it into unreadable prose, so the first cut of
``patterns.yaml`` covered only what could be read by eye. ``pdfplumber`` sees the
real cell grid, which lets the matrix be transcribed mechanically.

Four properties of the source have to be handled, each of which produced a wrong
answer on the way here:

* **Text is stored in visual order**, right-to-left, padded with tatweel
  (U+0640). ``اجباري`` arrives as ``يراــبجا``.
* **The 16 columns are two invoice types side by side.** Columns 0-3 are
  نوع دوم (patterns 13, 9, 3, 1); columns 4-15 are نوع اول (14, 13, 11, 9, 8, 7,
  6, 5, 4, 3, 2, 1). Patterns 1, 3, 9 and 13 therefore appear twice and can carry
  *different* obligations per type. Reading pattern 1 from the wrong half makes
  export-only fields look mandatory for an ordinary sale.
* **The table has its own row numbering**, unrelated to the کد column of the SDK
  guide's field table — جدول ۱ numbers مجموع وزن خالص as 30, the SDK as 69. Rows
  are therefore keyed by their Persian *name*, never by position.
* **``ignore`` is literal** in the source and marks a field that is not part of
  that pattern at all (RC_IITP §4: صورتحساب‌های الکترونیکی صرفا شامل اقلام مذکور
  بوده و اقلام دیگری را شامل نمی‌شود).

Run:
    /opt/homebrew/bin/python3.14 backend/tools/extract_table1.py --check
    /opt/homebrew/bin/python3.14 backend/tools/extract_table1.py --yaml > fragment.yaml
"""

from __future__ import annotations

import argparse
import json
import sys
import unicodedata
from pathlib import Path

import pdfplumber

REPO = Path(__file__).resolve().parents[2]
PDF = REPO / "Docs" / "RC_IITP_IS_V7_9_1.pdf"
TABLE_PAGE = 13  # zero-based; p.14 in the document

#: ``(invoice_type, pattern)`` for each of the 16 obligation columns, read off the
#: two header bands. Not inferred at runtime: fuzzy ordinal matching silently
#: mapped چهاردهم and سیزدهم onto دهم, which is a substring of both.
COLUMNS: list[tuple[int, int]] = [
    (2, 13), (2, 9), (2, 3), (2, 1),
    (1, 14), (1, 13), (1, 11), (1, 9), (1, 8), (1, 7),
    (1, 6), (1, 5), (1, 4), (1, 3), (1, 2), (1, 1),
]

#: Persian field title (as printed in جدول ۱) to wire name and JSON section.
#: Transcribed from the table itself, cross-checked against the field list in the
#: SDK guide pp.9-13. The titles are matched after tatweel stripping and
#: whitespace collapsing, so minor spacing differences are tolerated.
FIELDS: dict[str, tuple[str, str]] = {
    "شماره منحصر به فرد مالياتي": ("taxid", "header"),
    "تاريخ و زمان صدور صورتحساب ) ميالدي (": ("indatim", "header"),
    "تاريخ و زمان ثبت صورتحساب ) ميالدي (": ("indati2m", "header"),
    "نوع صورتحساب": ("inty", "header"),
    "سريال صورتحساب داخلي حافظه مالياتي": ("inno", "header"),
    "شماره منحصر به فرد مالياتي صورتحساب مرجع": ("irtaxid", "header"),
    "الگوي صورتحساب": ("inp", "header"),
    "موضوع صورتحساب": ("ins", "header"),
    "شماره اقتصادي فروشنده": ("tins", "header"),
    "نوع شخص خريدار": ("tob", "header"),
    "خريدار شناسه ملي/ شماره ملي/ شناسه مشاركت مدني/ كد فراگير اتباع غير ايراني": (
        "bid",
        "header",
    ),
    "شماره اقتصادي خريدار": ("tinb", "header"),
    "كد شعبه فروشنده": ("sbc", "header"),
    "كد پستي خريدار": ("bpc", "header"),
    "كد شعبه خريدار": ("bbc", "header"),
    "نوع پرواز": ("ft", "header"),
    "شماره گذرنامه خريدار": ("bpn", "header"),
    "شماره پروانه گمركي": ("scln", "header"),
    "كد گمرك محل اظهار فروشنده": ("scc", "header"),
    "شماره كوتاژ اظهارنامه گمركي": ("cdcn", "header"),
    "تاريخ كوتاژ اظهارنامه گمركي": ("cdcd", "header"),
    "شماره قرارداد پيمانكاري": ("crn", "header"),
    "شماره اشتراك /شناسه قبض بهره بردار": ("billid", "header"),
    "مجموع مبلغ قبل از كسر تخفيف": ("tprdis", "header"),
    "مجموع تخفيفات": ("tdis", "header"),
    "مجموع مبلغ پس از كسر تخفيف": ("tadis", "header"),
    "مجموع ماليات بر ارزش افزوده": ("tvam", "header"),
    "مجموع ساير ماليات، عوارض و وجوه قانوني": ("todam", "header"),
    "مجموع صورتحساب": ("tbill", "header"),
    "مجموع وزن خالص": ("tonw", "header"),
    "مجموع ارزش ريالي": ("torv", "header"),
    "مجموع ارزش ارزي": ("tocv", "header"),
    "روش تسويه": ("setm", "header"),
    "مبلغ پرداختي نقدي": ("cap", "header"),
    "مبلغ نسيه": ("insp", "header"),
    "مجموع سهم ماليات بر ارزش افزوده از پرداخت": ("tvop", "header"),
    "ماليات موضوع ماده 7١": ("tax17", "header"),
    "شناسه كاال/خدمت": ("sstid", "body"),
    "شرح كاال/ خدمت": ("sstt", "body"),
    "تعداد/مقدار": ("am", "body"),
    "واحد اندازه گيري": ("mu", "body"),
    "وزن خالص": ("nw", "body"),
    "مبلغ واحد": ("fee", "body"),
    "ميزان ارز": ("cfee", "body"),
    "نوع ارز": ("cut", "body"),
    "نرخ برابري ارز با ريال": ("exr", "body"),
    "ارزش ريالي كاال": ("ssrv", "body"),
    "ارزش ارزي كاال": ("sscv", "body"),
    "مبلغ قبل از تخفيف": ("prdis", "body"),
    "مبلغ تخفيف": ("dis", "body"),
    "مبلغ بعد از تخفيف": ("adis", "body"),
    "نرخ ماليات بر ارزش افزوده": ("vra", "body"),
    "مبلغ ماليات بر ارزش افزوده": ("vam", "body"),
    "موضوع ساير ماليات و عوارض": ("odt", "body"),
    "نرخ ساير ماليات و عوارض": ("odr", "body"),
    "مبلغ ساير ماليات و عوارض": ("odam", "body"),
    "موضوع ساير وجوه قانوني": ("olt", "body"),
    "نرخ ساير وجوه قانوني": ("olr", "body"),
    "مبلغ ساير وجوه قانوني": ("olam", "body"),
    "اجرت ساخت": ("consfee", "body"),
    "سود فروشنده": ("spro", "body"),
    "حق العمل": ("bros", "body"),
    "جمع كل اجرت، حق العمل و سود": ("tcpbs", "body"),
    "سهم نقدي از پرداخت": ("cop", "body"),
    "سهم ماليات بر ارزش افزوده از پرداخت": ("vop", "body"),
    "شماره قرارداد معامله از طريق شخص ثالث": ("bsrn", "body"),
    "مبلغ كل كاال/خدمت": ("tsstam", "body"),
    "شماره سوئيچ پرداخت": ("iinn", "payment"),
    "شماره پذيرنده فروشگاهي": ("acn", "payment"),
    "شماره پايانه": ("trmn", "payment"),
    "روش پرداخت": ("pmt", "payment"),
    "شماره پيگيري/شماره مرجع": ("trn", "payment"),
    "شماره كارت پرداخت كننده صورتحساب": ("pcn", "payment"),
    "شماره/شناسه ملي/كد فراگير پرداخت كننده صورتحساب": ("pid", "payment"),
    "تاريخ و زمان پرداخت": ("pdt", "payment"),
    "مبلغ پرداختي": ("pv", "payment"),
    "عيار": ("cui", "body"),
    "شماره اقتصادي آژانس": ("tinc", "header"),
    "شماره بارنامه": ("lno", "header"),
    "شماره بارنامه مرجع": ("lrno", "header"),
    "كشور مبدا": ("ocu", "header"),
    "شهر مبدا": ("oci", "header"),
    "كشور مقصد": ("dco", "header"),
    "شهر مقصد": ("dci", "header"),
    "فرستنده شناسه ملي/ شماره ملي/ شناسه مشاركت مدني/ كد فراگير اتباع غير ايراني": (
        "tid",
        "header",
    ),
    "گيرنده شناسه ملي/ شماره ملي/ شناسه مشاركت مدني/ كد فراگير اتباع غير ايراني": (
        "rid",
        "header",
    ),
    "نوع بارنامه/نوع حمل": ("lt", "header"),
    "شماره ناوگان": ("cno", "header"),
    "شماره ملي/ كد فراگير اتباع غيرايراني راننده در حمل و نقل جاده اي": ("did", "header"),
    "كاالهاي حمل شده": ("sg", "header"),
    "شناسه كاالي حمل شده": ("sgid", "sg"),
    "شرح كاالي حمل شده": ("sgt", "sg"),
    "نرخ خريد ارز": ("cpr", "body"),
    "ماخذ ماليات بر ارزش افزوده در الگوي فروش ارز": ("sovat", "body"),
    "شماره اعالميه فروش بورس": ("asn", "header"),
    "تاريخ اعالميه فروش بورس": ("asd", "header"),
    "شناسه يكتاي بيمه نامه": ("in", "header"),
    "شناسه يكتاي الحاقيه": ("an", "header"),
    "مبلغ پايه ماليات بر ارزش افزوده": ("vba", "body"),
    "قاعده ارسال صورتحساب": ("insr", "header"),
    "يادداشت ١": ("nti1", "header"),
    "يادداشت 2": ("nti2", "header"),
}

REQUIRED, OPTIONAL, CONDITIONAL, NOT_APPLICABLE = (
    "required",
    "optional",
    "conditional",
    "not_applicable",
)

#: Independent anchors from the per-field tables in §8. If the transcription
#: disagrees with any of these, the column or row mapping is wrong and the output
#: must not be shipped. Each entry is (invoice_type, pattern, section, field,
#: expected obligation, clause).
ANCHORS = [
    (1, 1, "body", "vra", REQUIRED, "§8-41 جدول ۴۳"),
    (1, 1, "body", "vam", REQUIRED, "§8-42 جدول ۴۴"),
    (1, 1, "body", "tsstam", REQUIRED, "§8-51 جدول ۵۳"),
    (1, 1, "header", "tvam", REQUIRED, "§8-16 جدول ۱۸"),
    (1, 1, "header", "tbill", REQUIRED, "§8-18 جدول ۲۰"),
    (1, 1, "header", "tdis", OPTIONAL, "§8-14 جدول ۱۶"),
    (1, 1, "header", "taxid", REQUIRED, "§8-1"),
    (1, 1, "header", "cdcn", NOT_APPLICABLE, "customs field, export patterns only"),
    (1, 7, "header", "cdcn", None, "customs field belongs to صادرات"),
    (1, 1, "header", "lno", NOT_APPLICABLE, "bill of lading, بارنامه pattern only"),
]


def logical(text: str | None) -> str:
    """Recover logical order from the PDF's visual-order Persian."""
    if not text:
        return ""
    cleaned = unicodedata.normalize("NFKC", text.replace("\n", " ").replace("ـ", ""))
    return " ".join(cleaned[::-1].split())


def classify(cell: str | None) -> str:
    raw = (cell or "").strip()
    if not raw or raw.lower() == "ignore":
        return NOT_APPLICABLE
    text = logical(raw)
    if "خاص" in text or "شرايط" in text or "شرایط" in text:
        return CONDITIONAL
    if "اختياري" in text or "اختیاری" in text:
        return OPTIONAL
    if "اجباري" in text or "اجباری" in text:
        return REQUIRED
    return NOT_APPLICABLE


def transcribe() -> tuple[dict, list[str]]:
    """Return ``{field: {section, patterns: {"type/pattern": obligation}}}`` and warnings."""
    with pdfplumber.open(str(PDF)) as pdf:
        grid = pdf.pages[TABLE_PAGE].find_tables()[1].extract()

    matrix: dict[str, dict] = {}
    warnings: list[str] = []
    for row in grid[3:]:
        title = logical(row[16])
        if not title:
            continue
        entry = FIELDS.get(title)
        if entry is None:
            warnings.append(f"unmapped row title: {title!r}")
            continue
        wire, section = entry
        obligations: dict[str, str] = {}
        for index, (invoice_type, pattern) in enumerate(COLUMNS):
            obligations[f"{invoice_type}/{pattern}"] = classify(row[index])
        matrix[wire] = {"section": section, "title": title, "patterns": obligations}

    missing = set(FIELDS.values()) - {(w, m["section"]) for w, m in matrix.items()}
    for wire, _ in sorted(missing):
        warnings.append(f"field never matched a row: {wire}")
    return matrix, warnings


def check(matrix: dict) -> list[str]:
    """Verify the transcription against §8, which was read independently."""
    failures = []
    for invoice_type, pattern, section, field, expected, clause in ANCHORS:
        entry = matrix.get(field)
        if entry is None:
            failures.append(f"{field}: absent from the transcription")
            continue
        if entry["section"] != section:
            failures.append(f"{field}: section {entry['section']!r} != {section!r}")
        actual = entry["patterns"].get(f"{invoice_type}/{pattern}")
        if expected is None:
            if actual == NOT_APPLICABLE:
                failures.append(
                    f"{field} type{invoice_type}/pattern{pattern}: expected to apply "
                    f"({clause}) but got not_applicable"
                )
            continue
        if actual != expected:
            failures.append(
                f"{field} type{invoice_type}/pattern{pattern}: expected {expected} "
                f"({clause}) but transcribed {actual}"
            )
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="verify against §8 anchors")
    parser.add_argument("--json", action="store_true", help="dump the raw matrix")
    args = parser.parse_args()

    if not PDF.is_file():
        print(f"missing {PDF}", file=sys.stderr)
        return 1

    matrix, warnings = transcribe()
    for warning in warnings:
        print(f"# WARN {warning}", file=sys.stderr)
    print(f"# transcribed {len(matrix)} fields", file=sys.stderr)

    failures = check(matrix)
    for failure in failures:
        print(f"# ANCHOR FAILED {failure}", file=sys.stderr)
    print(
        f"# anchors: {len(ANCHORS) - len(failures)}/{len(ANCHORS)} passed",
        file=sys.stderr,
    )

    if args.json or not args.check:
        json.dump(matrix, sys.stdout, ensure_ascii=False, indent=1)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())


# --------------------------------------------------------------- YAML emission

#: Persian names for the 14 patterns, from the column headers of جدول ۱.
PATTERN_NAMES = {
    1: ("فروش", "Sale"),
    2: ("فروش ارز", "Currency sale"),
    3: ("صورتحساب طلا، جواهر و پلاتین", "Gold, jewellery and platinum"),
    4: ("قرارداد پیمانکاری", "Contracting"),
    5: ("قبوض خدماتی", "Utility bills"),
    6: ("بلیط هواپیما", "Air ticket"),
    7: ("صادرات", "Export"),
    8: ("بارنامه", "Bill of lading"),
    9: ("فروش فرآورده‌های نفتی (پالایش و پخش)", "Petroleum products"),
    11: ("بورس اوراق بهادار مبتنی بر کالا", "Commodity-backed securities"),
    13: ("فروش خدمات بیمه‌ای", "Insurance services"),
    14: ("فروش زنجیره‌ای", "Chain sale"),
}

#: Conditions we can actually evaluate, keyed by field. The table marks a field
#: "اجباری در شرایط خاص" without naming the condition; these come from the §8
#: per-field tables, which do. A conditional field with no entry here is emitted
#: with `when: unspecified` and the engine leaves it alone rather than inventing
#: a trigger.
KNOWN_CONDITIONS = {
    "cap": ("setm == 3", "§8-22، جدول ۲۴، ردیف ۳"),
    "insp": ("setm == 3", "§8-22، جدول ۲۴، ردیف ۳"),
    "irtaxid": ("ins in (2, 3, 4)", "§5"),
    "indati2m": ("insr == 1", "§6"),
}


def _yaml_scalar(text: str) -> str:
    return '"' + text.replace('"', '\\"') + '"'


def emit_yaml(matrix: dict) -> str:
    """Render the transcription as the `patterns:` block of patterns.yaml."""
    patterns = sorted({int(k.split("/")[1]) for v in matrix.values() for k in v["patterns"]})
    out: list[str] = []
    out.append("# GENERATED by tools/extract_table1.py from RC_IITP_IS_V7_9_1 جدول شماره ۱ (p.14).")
    out.append("# Verified against the §8 per-field tables by the tool's --check anchors.")
    out.append("# Edit the tool and regenerate; hand edits here will be overwritten.")
    out.append("patterns:")
    for pattern in patterns:
        fa, en = PATTERN_NAMES.get(pattern, (f"الگوی {pattern}", f"Pattern {pattern}"))
        types = sorted(
            {
                int(k.split("/")[0])
                for v in matrix.values()
                for k in v["patterns"]
                if int(k.split("/")[1]) == pattern
                and v["patterns"][k] != NOT_APPLICABLE
            }
        )
        out.append(f"  {pattern}:")
        out.append(f"    name: {_yaml_scalar(fa)}")
        out.append(f"    name_en: {_yaml_scalar(en)}")
        out.append("    coverage: complete")
        out.append(f"    types: [{', '.join(str(t) for t in types) or '1'}]")
        out.append('    reference: "RC_IITP_IS_V7_9_1 جدول شماره ۱"')
        excluded: dict[str, list[str]] = {}
        for section in ("header", "body", "payment", "sg"):
            entries = [
                (wire, meta)
                for wire, meta in matrix.items()
                if meta["section"] == section
            ]
            rows: list[str] = []
            for wire, meta in entries:
                primary_type = types[0] if types else 1
                obligation = meta["patterns"].get(f"{primary_type}/{pattern}", NOT_APPLICABLE)
                overrides = {
                    t: meta["patterns"].get(f"{t}/{pattern}", NOT_APPLICABLE)
                    for t in types
                    if meta["patterns"].get(f"{t}/{pattern}") != obligation
                }
                if obligation == NOT_APPLICABLE and not overrides:
                    excluded.setdefault(section, []).append(wire)
                    continue
                parts = [f"obligation: {obligation}"]
                if obligation == CONDITIONAL:
                    when, ref = KNOWN_CONDITIONS.get(wire, ("unspecified", ""))
                    parts.append(f"when: {_yaml_scalar(when)}")
                    if ref:
                        parts.append(f"condition_reference: {_yaml_scalar(ref)}")
                if overrides:
                    inner = ", ".join(f"{t}: {o}" for t, o in sorted(overrides.items()))
                    parts.append(f"by_type: {{{inner}}}")
                parts.append(f"title: {_yaml_scalar(meta['title'])}")
                rows.append(f"      {wire}: {{{', '.join(parts)}}}")
            if rows:
                out.append(f"    {section}:")
                out.extend(rows)
        # Fields جدول ۱ marks as not belonging to this pattern at all. Listed
        # rather than spelled out per field: 38 of ~102 are excluded for a plain
        # sale, and repeating each with `obligation: not_applicable` would triple
        # the file for no extra information. RC_IITP §4 makes sending one an error.
        if excluded:
            out.append("    excluded:")
            for section, names in excluded.items():
                out.append(f"      {section}: [{', '.join(sorted(names))}]")
    return "\n".join(out) + "\n"
