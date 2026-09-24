"""The catalogue importer's CSV reading.

Shaped after the real export: a UTF-8 BOM, Jalali dates, and the same code
repeated once per VAT rate with the superseded row carrying an ExpirationDate.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_TOOL = Path(__file__).resolve().parents[2] / "tools" / "import_catalogue.py"


def _load():
    spec = importlib.util.spec_from_file_location("import_catalogue", _TOOL)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


tool = _load()

HEADER = (
    "ID,DescriptionOfID,Vat,Taxable,RunDate,ExpirationDate,CreateDate,"
    "LastEditDate,Type,PricingDescription"
)


def write(tmp_path: Path, *lines: str, bom: bool = True, name: str = "export.csv") -> Path:
    path = tmp_path / name
    path.write_text(
        "\n".join((HEADER, *lines)) + "\n", encoding="utf-8-sig" if bom else "utf-8"
    )
    return path


def test_a_bom_does_not_break_the_first_column(tmp_path: Path) -> None:
    """The real export is BOM-prefixed. Read as plain utf-8 the first column is
    named '\\ufeffID', every lookup of 'ID' misses, and every row is skipped for
    having no identifier — an importer that reports zero rows and no error."""
    path = write(tmp_path, "2330004567413,خدمات مجوز,10,مشمول,1405-07-01,,,,شناسه اختصاصی خدمت,")
    rows = list(tool.read([path]))
    assert len(rows) == 1
    assert rows[0]["stuff_id"] == "2330004567413"


def test_every_field_is_carried_across(tmp_path: Path) -> None:
    path = write(
        tmp_path,
        "2330004567413,خدمات مجوز نرم افزار,10,مشمول,1405-07-01,,1405-07-01,"
        "1405-07-01,شناسه اختصاصی خدمت,per unit",
    )
    row = next(iter(tool.read([path])))
    assert row == {
        "stuff_id": "2330004567413",
        "description": "خدمات مجوز نرم افزار",
        "vat_rate": 10.0,
        "taxable": "مشمول",
        "run_date": "1405-07-01",
        "expiration_date": None,
        "kind": "شناسه اختصاصی خدمت",
        "pricing": "per unit",
        "is_current": 1,
    }


def test_an_expiration_date_marks_the_row_superseded(tmp_path: Path) -> None:
    """is_current comes from this field being present, not from comparing dates.

    The dates are Jalali; comparing them would need a calendar conversion, which
    is a second thing that can be wrong in service of a question the export
    already answers outright."""
    path = write(
        tmp_path,
        "2330009999999,خدمات مشاوره,9,مشمول,1403-09-04,1405-07-01,,,شناسه اختصاصی خدمت,",
        "2330009999999,خدمات مشاوره,10,مشمول,1405-07-02,,,,شناسه اختصاصی خدمت,",
    )
    rows = list(tool.read([path]))
    assert [r["is_current"] for r in rows] == [0, 1]
    assert [r["vat_rate"] for r in rows] == [9.0, 10.0]


def test_several_parts_are_read_as_one_catalogue(tmp_path: Path) -> None:
    """Each part of the export is a different slice — the services file contains
    no goods at all — so they have to be imported together."""
    first = write(tmp_path, "2330004567413,خدمت الف,10,مشمول,1405-07-01,,,,خدمت,", name="p1.csv")
    second = write(tmp_path, "2440004567413,کالای ب,9,مشمول,1405-07-01,,,,کالا,", name="p2.csv")
    assert [r["stuff_id"] for r in tool.read([first, second])] == [
        "2330004567413",
        "2440004567413",
    ]


def test_a_row_with_no_identifier_or_no_description_is_skipped(tmp_path: Path) -> None:
    path = write(
        tmp_path,
        ",خدمات بی‌شناسه,10,مشمول,1405-07-01,,,,خدمت,",
        "2330004567413,,10,مشمول,1405-07-01,,,,خدمت,",
        "2330004567420,خدمات درست,10,مشمول,1405-07-01,,,,خدمت,",
    )
    assert [r["stuff_id"] for r in tool.read([path])] == ["2330004567420"]


def test_a_fourteen_digit_identifier_is_kept(tmp_path: Path) -> None:
    """One row of the official services export really is 14 digits. Dropping it
    would silently lose a code the organization published."""
    path = write(tmp_path, "23300032442921,اماده سازی قبر,0,معاف,1405-07-01,,,,خدمت,")
    assert next(iter(tool.read([path])))["stuff_id"] == "23300032442921"


@pytest.mark.parametrize(
    ("vat", "expected"),
    [("10", 10.0), ("9", 9.0), ("0", 0.0), ("", None), ("  ", None), ("x", None)],
)
def test_an_unparseable_vat_becomes_null_rather_than_zero(tmp_path, vat, expected) -> None:
    """Zero is a real rate — معاف rows carry it. Coercing a blank to 0.0 would
    make an unknown rate indistinguishable from an exempt one."""
    path = write(tmp_path, f"2330004567413,خدمات,{vat},مشمول,1405-07-01,,,,خدمت,")
    assert next(iter(tool.read([path])))["vat_rate"] == expected


def test_blank_optional_fields_become_none_not_empty_string(tmp_path: Path) -> None:
    path = write(tmp_path, "2330004567413,خدمات,10,,,,,,,")
    row = next(iter(tool.read([path])))
    assert row["taxable"] is None
    assert row["run_date"] is None
    assert row["pricing"] is None


def test_a_file_with_the_wrong_columns_is_refused_by_name(tmp_path: Path) -> None:
    """A column that quietly moved would import descriptions as VAT rates. The
    error has to name what is missing, or the operator has nothing to act on."""
    path = tmp_path / "wrong.csv"
    path.write_text("a,b,c\n1,2,3\n", encoding="utf-8")
    with pytest.raises(SystemExit) as caught:
        list(tool.read([path]))
    message = str(caught.value)
    assert "ID" in message and "DescriptionOfID" in message


def test_a_quoted_description_containing_commas_survives(tmp_path: Path) -> None:
    """Catalogue descriptions are full of commas and parentheses."""
    path = write(
        tmp_path,
        '2330004567413,"خدمات مجوز (license) نرم افزار, سخت افزار, کامپیوتر",10,مشمول,'
        "1405-07-01,,,,خدمت,",
    )
    row = next(iter(tool.read([path])))
    assert row["description"] == "خدمات مجوز (license) نرم افزار, سخت افزار, کامپیوتر"


def test_an_empty_export_yields_nothing_without_raising(tmp_path: Path) -> None:
    assert list(tool.read([write(tmp_path)])) == []
