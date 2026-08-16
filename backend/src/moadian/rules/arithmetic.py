"""The cross-field money rules from RC_IITP_IS_V7_9_1 §8.

The spec names its quantities with single letters — ``Es`` for مبلغ قبل از تخفیف,
``Ks`` for مبلغ مالیات بر ارزش افزوده, and so on — and states each rule as a
formula over them. Those names are kept in the docstrings so a reader can match
each check to its clause without translating twice.

Formulas live here rather than in ``patterns.yaml`` because several have
pattern-specific variants with different *inputs* (the gold pattern folds اجرت
into the base, the currency pattern computes VAT from a separate ماخذ), and a
data format expressive enough for that is just a worse programming language. The
obligation matrix — which is genuinely 16 × ~109 tabular data — does live in YAML.

**Rounding.** Money fields are declared with `حداکثر تعداد رقم اعشار ۰`: zero
decimal places, i.e. whole rials. But `vra` carries two decimals, so
``adis × vra / 100`` is generally fractional and *something* must round it. The
spec does not say what, and we have not been able to observe the service's
behaviour. :data:`TOLERANCE_RIAL` therefore accepts a discrepancy of one rial per
line rather than guessing a rounding mode and silently rejecting valid invoices.
Narrow it once real acceptances are observed.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from moadian.models import Invoice, InvoiceBodyItem
from moadian.rules.violations import Violation

__all__ = ["TOLERANCE_RIAL", "check_arithmetic"]

#: Accepted per-comparison slack, in rials. See the rounding note above.
TOLERANCE_RIAL = 1.0

#: Patterns whose VAT rate is fixed at zero by §8-41 rule 5: صادرات (7),
#: بورس اوراق بهادار مبتنی بر کالا (11), فروش زنجیره‌ای (14).
ZERO_VAT_PATTERNS = frozenset({7, 11, 14})


def _n(value: float | None) -> float:
    """Absent money is zero. The wire omits unset fields rather than sending 0."""
    return 0.0 if value is None else float(value)


def _off(actual: float | None, expected: float) -> bool:
    return abs(_n(actual) - expected) > TOLERANCE_RIAL


def _line_total(item: InvoiceBodyItem, pattern: int) -> float:
    """``Os = Ks + Is + Ks2 + Ks3`` — §8-51, جدول ۵۳ rule 1.

    Pattern 7 (صادرات) substitutes ارزش ریالی کالا for مبلغ بعد از تخفیف
    (rule 4), because an export line is priced in the declared rial value.
    """
    base = _n(item.ssrv) if pattern == 7 else _n(item.adis)
    return base + _n(item.vam) + _n(item.odam) + _n(item.olam)


def _pre_discount(item: InvoiceBodyItem, pattern: int) -> float:
    """``Es = As * Cs`` — §8-38, جدول ۴۰ rule 1, with two pattern variants."""
    if pattern == 2:  # فروش ارز: Es = Cf * exr  (rule 3)
        return _n(item.cfee) * _n(item.exr)
    if pattern == 6:  # بلیط هواپیما: Es = Cs  (rule 4)
        return _n(item.fee)
    return _n(item.am) * _n(item.fee)


def _after_discount(item: InvoiceBodyItem, pattern: int) -> float:
    """``Is = Es - Gs`` — §8-40, جدول ۴۲ rule 1.

    Pattern 3 (طلا، جواهر و پلاتین) adds اجرت/حق‌العمل/سود before discount
    (rule 4): ``Is = Es + TAs - Gs``.
    """
    base = _pre_discount(item, pattern)
    if pattern == 3:
        base += _n(item.tcpbs)
    return base - _n(item.dis)


def _vat(item: InvoiceBodyItem, pattern: int) -> float:
    """``Ks = Is * J / 100`` — §8-42, جدول ۴۴ rule 1, with two variants."""
    rate = _n(item.vra)
    if pattern == 3:  # طلا: Ks = (TAs*10)/100 + (Es*J)/100  (rule 4)
        return (_n(item.tcpbs) * 10.0) / 100.0 + (_pre_discount(item, pattern) * rate) / 100.0
    if pattern == 2:  # فروش ارز: Ks = sovat * J/100  (rule 5)
        return _n(item.sovat) * rate / 100.0
    return _n(item.adis) * rate / 100.0


def _check_line(item: InvoiceBodyItem, index: int, pattern: int) -> Iterable[Violation]:
    """Per-line rules. Each yields at most one violation so the UI can list them."""
    expected_prdis = _pre_discount(item, pattern)
    if _off(item.prdis, expected_prdis):
        yield Violation(
            field="prdis",
            line=index,
            rule="arithmetic.prdis",
            message="مبلغ قبل از تخفیف باید برابر حاصل‌ضرب تعداد در مبلغ واحد باشد.",
            reference="§8-38، جدول ۴۰، ردیف ۱",
            expected=expected_prdis,
            actual=_n(item.prdis),
        )

    if _n(item.prdis) <= 0:
        yield Violation(
            field="prdis",
            line=index,
            rule="arithmetic.prdis.positive",
            message="مبلغ قبل از تخفیف باید بزرگ‌تر از صفر باشد.",
            reference="§8-38، جدول ۴۰، ردیف ۲",
            actual=_n(item.prdis),
        )

    if _n(item.dis) < 0:
        yield Violation(
            field="dis",
            line=index,
            rule="arithmetic.dis.non_negative",
            message="مبلغ تخفیف نمی‌تواند منفی باشد.",
            reference="§8-39، جدول ۴۱، ردیف ۲",
            actual=_n(item.dis),
        )
    elif _n(item.dis) > _n(item.prdis) + TOLERANCE_RIAL:
        yield Violation(
            field="dis",
            line=index,
            rule="arithmetic.dis.at_most_prdis",
            message="مبلغ تخفیف نمی‌تواند از مبلغ قبل از تخفیف بیشتر باشد.",
            reference="§8-39، جدول ۴۱، ردیف ۳",
            expected=_n(item.prdis),
            actual=_n(item.dis),
        )

    expected_adis = _after_discount(item, pattern)
    if _off(item.adis, expected_adis):
        yield Violation(
            field="adis",
            line=index,
            rule="arithmetic.adis",
            message="مبلغ بعد از تخفیف باید برابر مبلغ قبل از تخفیف منهای تخفیف باشد.",
            reference="§8-40، جدول ۴۲، ردیف ۱",
            expected=expected_adis,
            actual=_n(item.adis),
        )

    if _n(item.adis) < 0:
        yield Violation(
            field="adis",
            line=index,
            rule="arithmetic.adis.non_negative",
            message="مبلغ بعد از تخفیف نمی‌تواند منفی باشد.",
            reference="§8-40، جدول ۴۲، ردیف ۳",
            actual=_n(item.adis),
        )

    if _n(item.vra) < 0:
        yield Violation(
            field="vra",
            line=index,
            rule="arithmetic.vra.non_negative",
            message="نرخ مالیات بر ارزش افزوده نمی‌تواند منفی باشد.",
            reference="§8-41، جدول ۴۳، ردیف ۶",
            actual=_n(item.vra),
        )

    if pattern in ZERO_VAT_PATTERNS and _n(item.vra) != 0:
        yield Violation(
            field="vra",
            line=index,
            rule="arithmetic.vra.zero_for_pattern",
            message=(
                "در الگوهای صادرات، بورس اوراق بهادار مبتنی بر کالا و فروش زنجیره‌ای "
                "نرخ مالیات بر ارزش افزوده باید صفر باشد."
            ),
            reference="§8-41، جدول ۴۳، ردیف ۵",
            expected=0.0,
            actual=_n(item.vra),
            context={"pattern": pattern},
        )

    expected_vam = _vat(item, pattern)
    if _off(item.vam, expected_vam):
        yield Violation(
            field="vam",
            line=index,
            rule="arithmetic.vam",
            message="مبلغ مالیات بر ارزش افزوده باید برابر مبلغ بعد از تخفیف ضرب در نرخ باشد.",
            reference="§8-42، جدول ۴۴، ردیف ۱",
            expected=expected_vam,
            actual=_n(item.vam),
        )

    expected_tsstam = _line_total(item, pattern)
    if _off(item.tsstam, expected_tsstam):
        yield Violation(
            field="tsstam",
            line=index,
            rule="arithmetic.tsstam",
            message=(
                "مبلغ کل کالا/خدمت باید برابر مجموع مبلغ بعد از تخفیف، مالیات بر ارزش "
                "افزوده و سایر مالیات و وجوه قانونی باشد."
            ),
            reference="§8-51، جدول ۵۳، ردیف ۱",
            expected=expected_tsstam,
            actual=_n(item.tsstam),
        )


def _sum(items: Sequence[InvoiceBodyItem], attr: str) -> float:
    return sum(_n(getattr(item, attr)) for item in items)


def _check_totals(invoice: Invoice, pattern: int) -> Iterable[Violation]:
    """Header totals, each a sum over the body — §8-13 … §8-18."""
    body = invoice.body
    header = invoice.header

    for wire_name, attr, reference, message in (
        (
            "tprdis",
            "prdis",
            "§8-13، جدول ۱۵، ردیف ۱",
            "مجموع مبلغ قبل از کسر تخفیف باید برابر جمع مبالغ قبل از تخفیف اقلام باشد.",
        ),
        (
            "tdis",
            "dis",
            "§8-14، جدول ۱۶، ردیف ۱",
            "مجموع تخفیفات باید برابر جمع مبالغ تخفیف اقلام باشد.",
        ),
        (
            "tadis",
            "adis",
            "§8-15، جدول ۱۷، ردیف ۱",
            "مجموع مبلغ پس از کسر تخفیف باید برابر جمع مبالغ پس از تخفیف اقلام باشد.",
        ),
        (
            "tvam",
            "vam",
            "§8-16، جدول ۱۸، ردیف ۱",
            "مجموع مالیات بر ارزش افزوده باید برابر جمع مالیات اقلام باشد.",
        ),
        (
            "tbill",
            "tsstam",
            "§8-18، جدول ۲۰، ردیف ۱",
            "مجموع صورتحساب باید برابر جمع مبالغ کل کالا/خدمت باشد.",
        ),
    ):
        expected = _sum(body, attr)
        if _off(getattr(header, wire_name), expected):
            yield Violation(
                field=wire_name,
                rule=f"arithmetic.{wire_name}",
                message=message,
                reference=reference,
                expected=expected,
                actual=_n(getattr(header, wire_name)),
            )

    # W2 = Σ odam + Σ olam — two body columns collapse into one header total.
    expected_todam = _sum(body, "odam") + _sum(body, "olam")
    if _off(header.todam, expected_todam):
        yield Violation(
            field="todam",
            rule="arithmetic.todam",
            message=(
                "مجموع سایر مالیات، عوارض و وجوه قانونی باید برابر جمع سایر مالیات و "
                "عوارض و سایر وجوه قانونی اقلام باشد."
            ),
            reference="§8-17، جدول ۱۹، ردیف ۱",
            expected=expected_todam,
            actual=_n(header.todam),
        )

    if _n(header.tprdis) <= 0:
        yield Violation(
            field="tprdis",
            rule="arithmetic.tprdis.positive",
            message="مجموع مبلغ قبل از کسر تخفیف باید بزرگ‌تر از صفر باشد.",
            reference="§8-13، جدول ۱۵، ردیف ۲",
            actual=_n(header.tprdis),
        )


def _check_settlement(invoice: Invoice) -> Iterable[Violation]:
    """روش تسویه — §8-22 جدول ۲۴, and the cash/credit split in §8-23 and §8-24."""
    header = invoice.header
    setm = header.setm

    if setm is not None and setm not in (1, 2, 3):
        yield Violation(
            field="setm",
            rule="settlement.method",
            message="روش تسویه باید نقدی (۱)، نسیه (۲) یا نقدی/نسیه (۳) باشد.",
            reference="§8-22، جدول ۲۴، ردیف ۱",
            actual=float(setm),
        )
        return

    if setm != 3:
        return

    # نقدی/نسیه: both amounts become mandatory (§8-22 rule 3).
    for wire_name, label in (("cap", "مبلغ پرداختی نقدی"), ("insp", "مبلغ نسیه")):
        if getattr(header, wire_name) is None:
            yield Violation(
                field=wire_name,
                rule="settlement.split_required",
                message=f"در روش تسویه نقدی/نسیه ثبت {label} اجباری است.",
                reference="§8-22، جدول ۲۴، ردیف ۳",
            )

    cap, insp, tbill = _n(header.cap), _n(header.insp), _n(header.tbill)
    if header.cap is not None and cap <= 0:
        yield Violation(
            field="cap",
            rule="settlement.cap.positive",
            message="مبلغ پرداختی نقدی باید بزرگ‌تر از صفر باشد.",
            reference="§8-23، جدول ۲۵، ردیف ۳",
            actual=cap,
        )
    if header.insp is not None and insp <= 0:
        yield Violation(
            field="insp",
            rule="settlement.insp.positive",
            message="مبلغ نسیه باید بزرگ‌تر از صفر باشد.",
            reference="§8-24، جدول ۲۶، ردیف ۳",
            actual=insp,
        )

    # C = Xs - W2 - W - Cr, i.e. cash + credit + VAT + other taxes = the bill.
    if header.cap is not None and header.insp is not None:
        expected_cap = tbill - _n(header.todam) - _n(header.tvam) - insp
        if _off(header.cap, expected_cap):
            yield Violation(
                field="cap",
                rule="settlement.split_balances",
                message=(
                    "مجموع مبلغ نقدی و نسیه به همراه مالیات و عوارض باید با مجموع "
                    "صورتحساب برابر باشد."
                ),
                reference="§8-23، جدول ۲۵، ردیف ۲",
                expected=expected_cap,
                actual=cap,
            )
        if cap >= tbill:
            yield Violation(
                field="cap",
                rule="settlement.cap.below_total",
                message="مبلغ پرداختی نقدی باید از مجموع صورتحساب کمتر باشد.",
                reference="§8-23، جدول ۲۵، ردیف ۱",
                expected=tbill,
                actual=cap,
            )
        if insp >= tbill:
            yield Violation(
                field="insp",
                rule="settlement.insp.below_total",
                message="مبلغ نسیه باید از مجموع صورتحساب کمتر باشد.",
                reference="§8-24، جدول ۲۶، ردیف ۱",
                expected=tbill,
                actual=insp,
            )


def check_arithmetic(invoice: Invoice, pattern: int) -> list[Violation]:
    """Every money rule that applies to ``invoice`` under ``pattern`` (الگو).

    Returns them all rather than stopping at the first: an operator fixing a
    total wants to see every line that disagrees, not one at a time.
    """
    violations: list[Violation] = []
    for index, item in enumerate(invoice.body):
        violations.extend(_check_line(item, index, pattern))
    violations.extend(_check_totals(invoice, pattern))
    violations.extend(_check_settlement(invoice))
    return violations


def recompute(invoice: Invoice, pattern: int = 1) -> Invoice:
    """Return a copy with every derived money field filled in from its inputs.

    The entry UI's "calculate" action: the operator supplies تعداد, مبلغ واحد,
    تخفیف and نرخ, and everything downstream follows from the §8 formulas. Values
    are rounded to whole rials because the wire format allows no decimal places.
    """
    updated = invoice.model_copy(deep=True)
    for item in updated.body:
        item.prdis = round(_pre_discount(item, pattern))
        item.adis = round(_after_discount(item, pattern))
        item.vam = round(_vat(item, pattern))
        item.tsstam = round(_line_total(item, pattern))

    header = updated.header
    header.tprdis = round(_sum(updated.body, "prdis"))
    header.tdis = round(_sum(updated.body, "dis"))
    header.tadis = round(_sum(updated.body, "adis"))
    header.tvam = round(_sum(updated.body, "vam"))
    header.todam = round(_sum(updated.body, "odam") + _sum(updated.body, "olam"))
    header.tbill = round(_sum(updated.body, "tsstam"))
    return updated
