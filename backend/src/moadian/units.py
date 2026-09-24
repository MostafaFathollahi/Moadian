"""واحدهای اندازه‌گیری کالا/خدمت — the organization's unit-of-measure codes.

Transcribed from **RC_UMGS.ST_V1.18** (اردیبهشت ۱۴۰۴), `Docs/RC_UMGS_ST_V1_18.pdf`,
which is the document RC_IITP §8-30، جدول ۳۲ points at for the values ``mu`` may
take. 102 codes. Anything outside them earns error **0103502** — "مقدار وارد شده
در فیلد «واحد اندازه‌گیری» جز مقادیر مجاز نیست" — which is how this table came to
be needed: an invoice was refused for a blank ``mu`` and there was no list to
check against.

The code lengths look irregular — 161, 1611 and 16110 all exist — and the numbers
are not contiguous: 16106, 16107, 16109, 16123 and 16124 are simply absent. That
is the document's own shape, not a gap in the transcription.

Two departures from the PDF's text, both presentational. Arabic yeh (U+064A) and
kaf (U+0643) in the names are folded to their Persian forms — they are keyboard
artefacts, and leaving them in makes a name unfindable to anyone typing Persian.
And eight names whose parentheses the PDF's text layer mangles are repaired, each
one listed in the generator rather than pattern-matched. **The codes are verbatim.**

``164`` being کیلوگرم is worth noting: it is the value the RC_TICS p.20 example
invoice and every sample in the official .NET SDK use, for a سرسیلندر — sold by
weight. The agreement is a cross-check that the rows did not shift.

The organization revises this list (V1.18 added نفر-ماه over V1.16), so an
unrecognised code is reported as a warning rather than refused — see
:meth:`moadian.rules.engine.RuleEngine._check_lengths`.
"""

from __future__ import annotations

__all__ = ["DEFAULT_UNIT", "UNITS", "unit_name"]

#: کد واحد اندازه‌گیری «عدد». The default for a new invoice line: most things are
#: counted rather than weighed or measured.
DEFAULT_UNIT = "1627"

#: code -> نام واحد, in the document's own row order.
UNITS: dict[str, str] = {
    "1611": "لنگه",
    "1612": "عدل",
    "1613": "جعبه",
    "1618": "توپ",
    "1619": "ست",
    "1620": "دست",
    "1624": "کارتن",
    "1627": "عدد",
    "1628": "بسته",
    "1629": "پاکت",
    "1631": "دستگاه",
    "1640": "تخته",
    "1641": "رول",
    "1642": "طاقه",
    "1643": "جفت",
    "1645": "متر مربع",
    "1649": "پالت",
    "1661": "دوجین",
    "1668": "حلقه (رینگ)",
    "1673": "قراص",
    "1694": "قراصه (bundle)",
    "1637": "لیتر",
    "1650": "ساشه",
    "1683": "کپسول",
    "1656": "بندیل",
    "1630": "حلقه (رول)",
    "163": "قالب",
    "1660": "شانه",
    "1647": "متر مکعب",
    "1689": "ثوب",
    "1690": "نیم دوجین",
    "1635": "قرقره",
    "164": "کیلوگرم",
    "1638": "بطری",
    "161": "برگ",
    "1625": "سطل",
    "1654": "ورق",
    "1646": "شاخه",
    "1644": "قوطی",
    "1617": "جلد",
    "162": "تیوب",
    "165": "متر",
    "1610": "کلاف",
    "1615": "کیسه",
    "1680": "طغرا",
    "1639": "بشکه",
    "1614": "گالن",
    "1687": "فاقد بسته بندی",
    "1693": "کارتن (case master)",
    "166": "صفحه",
    "1666": "مخزن",
    "1626": "تانکر",
    "1648": "دبه",
    "1684": "سبد",
    "169": "تن",
    "1651": "بانکه",
    "1633": "سیلندر",
    "1679": "فوت مربع",
    "168": "حلب",
    "1665": "شیت",
    "1659": "چلیک",
    "1636": "جام",
    "1622": "گرم",
    "1616": "نخ",
    "1652": "شعله",
    "1678": "قیراط",
    "16100": "میلی لیتر",
    "16101": "میلی متر",
    "16102": "میلی گرم",
    "16103": "ساعت",
    "16104": "روز",
    "16105": "تن کیلومتر",
    "1669": "کیلووات ساعت",
    "1676": "نفر",
    "16110": "ثانیه",
    "16111": "دقیقه",
    "16112": "ماه",
    "16113": "سال",
    "16114": "قطعه",
    "16115": "سانتی متر",
    "16116": "سانتی متر مربع",
    "1632": "فروند",
    "1653": "واحد",
    "16108": "لیوان",
    "16117": "نوبت",
    "16118": "مگا وات ساعت",
    "16119": "گیگا بایت بر ثانیه",
    "1681": "ویال",
    "1667": "حلقه (دیسک)",
    "16120": "نسخه (جلد)",
    "16121": "نفر-ساعت",
    "16122": "کیلومتر",
    "16125": "آمپر",
    "16126": "میلی آمپر",
    "16127": "مثقال",
    "16128": "سیر",
    "16129": "دفعه (time)",
    "16130": "مگا یونیت",
    "16131": "کادر",
    "16132": "پرس",
    "16133": "بلوک",
    "16134": "نفر-ماه",
}


def unit_name(code: str | None) -> str | None:
    """The Persian name of a unit code, or ``None`` if it is not in this edition."""
    return UNITS.get((code or "").strip()) or None
