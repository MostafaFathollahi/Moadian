"""واحدهای اندازه‌گیری کالا/خدمت — the organization's unit-of-measure codes.

The ``mu`` field of an invoice line takes a code from this table and nothing else.
RC_IITP §8-30، جدول ۳۲ declares the field اختیاری and "رشته عددی، حداکثر ۸", and
points at سند واحدهای اندازه‌گیری کالا/خدمت (RC_UMGS.ST) on intamedia.ir for the
values. Sending anything outside it earns error **0103502** — "مقدار وارد شده در
فیلد «واحد اندازه‌گیری» جز مقادیر مجاز نیست" — which is how this table came to be
transcribed here: an invoice was refused for a blank ``mu``, and the list was not
available to check against.

Transcribed from the published table, 97 codes. Two liberties, both cosmetic:
Arabic yeh (U+064A) and kaf (U+0643) in the names are folded to their Persian
forms, because they are keyboard artefacts rather than distinct letters, and a
handful of reversed parenthesis pairs are righted. **The codes are verbatim.**

The code lengths look irregular — 161, 1611, 16110 all exist — and that is the
table's own shape, not a transcription error: 161-169, then 1610-1694, then
16100-16129. ``164`` being کیلوگرم is what the RC_TICS p.20 example and the
official SDK samples use, which is a useful cross-check on the whole list.

This is a snapshot. The organization revises it, so an unrecognised code is
reported as a warning rather than refused — see
:meth:`moadian.rules.engine.RuleEngine._check_lengths`.
"""

from __future__ import annotations

__all__ = ["DEFAULT_UNIT", "UNITS", "unit_name"]

#: کد واحد اندازه‌گیری «عدد». The sensible default for a line that is counted
#: rather than weighed or measured, which is most of them.
DEFAULT_UNIT = "1627"

#: code -> نام واحد, in the published table's own order.
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
    "1610": "کالف",
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
    "16121": "نفر- ساعت",
    "16122": "کیلومتر",
    "16125": "آمپر",
    "16126": "میلی آمپر",
    "16127": "مثقال",
    "16128": "سیر",
    "16129": "دفعه(time)",
}


def unit_name(code: str | None) -> str | None:
    """The Persian name of a unit code, or ``None`` if it is not in this snapshot."""
    return UNITS.get((code or "").strip()) or None
