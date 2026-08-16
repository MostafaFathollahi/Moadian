"""Validates an invoice against RC_IITP before it is signed.

The organization validates asynchronously: submit, wait ten seconds, inquire,
and only then learn that ``tbill`` was off by a rial. Worse, a rejected invoice
has already consumed a tax id and a serial, neither of which can be reused. So
everything checkable offline is checked offline.

What this cannot check: anything requiring the organization's own data — whether
a شناسه کالا/خدمت exists, whether a نرخ مالیات matches the rate published for that
class of goods, whether the buyer's شماره اقتصادی is registered. Those stay the
service's job. See :meth:`RuleEngine.validate` for how the gap is reported.
"""

from __future__ import annotations

from typing import Any

from moadian.models import Invoice
from moadian.rules.arithmetic import check_arithmetic
from moadian.rules.spec import RuleSet, load_rules
from moadian.rules.violations import (
    Obligation,
    Severity,
    ValidationReport,
    VerificationResult,
    Violation,
)

__all__ = ["RuleEngine"]

#: The الگو to assume when the header does not name one. Pattern 1 (فروش) is the
#: ordinary sale, and `inp` is اجباری anyway, so this only affects the message
#: shown for an invoice that already fails the required-field check.
DEFAULT_PATTERN = 1


class RuleEngine:
    """Checks invoices against the transcribed portion of RC_IITP."""

    def __init__(self, rules: RuleSet | None = None) -> None:
        self._rules = rules or load_rules()

    @property
    def rules(self) -> RuleSet:
        return self._rules

    def validate(self, invoice: Invoice) -> ValidationReport:
        """Every rule this engine can evaluate, reported at once.

        Collects rather than short-circuits: an operator correcting an invoice
        wants the whole list, not one error per round trip.
        """
        pattern_number = invoice.header.inp or DEFAULT_PATTERN
        violations: list[Violation] = []

        spec = self._rules.pattern(pattern_number)
        if spec is None:
            # Say so plainly. Silently returning "valid" for an unencoded pattern
            # would let an operator read a clean report as a guarantee.
            violations.append(
                Violation(
                    field="inp",
                    rule="coverage.pattern_not_encoded",
                    message=(
                        f"قواعد الگوی {pattern_number} هنوز در این نسخه پیاده‌سازی نشده "
                        "است؛ تنها قواعد عمومی بررسی شد."
                    ),
                    reference="rules/patterns.yaml",
                    severity=Severity.WARNING,
                    context={"pattern": pattern_number},
                )
            )
        else:
            violations.extend(self._check_obligations(invoice, spec))
            if not spec.is_complete:
                violations.append(
                    Violation(
                        field="inp",
                        rule="coverage.partial",
                        message=(
                            f"ماتریس قواعد الگوی {pattern_number} ناقص است؛ نبود خطا به "
                            "معنای تأیید کامل نیست."
                        ),
                        reference=spec.reference or "rules/patterns.yaml",
                        severity=Severity.WARNING,
                        context={"pattern": pattern_number, "coverage": spec.coverage},
                    )
                )

        violations.extend(self._check_enums(invoice))
        violations.extend(check_arithmetic(invoice, pattern_number))
        return ValidationReport(tuple(violations))

    # -- obligations ------------------------------------------------------

    def _check_obligations(self, invoice: Invoice, spec: Any) -> list[Violation]:
        header = invoice.header.model_dump(exclude_none=True, by_alias=True)
        invoice_type = invoice.header.inty
        violations: list[Violation] = []

        for name, rule in spec.header.items():
            obligation = rule.for_type(invoice_type)
            if obligation is Obligation.NOT_APPLICABLE:
                if name in header:
                    violations.append(
                        Violation(
                            field=name,
                            rule="obligation.not_applicable",
                            message=(
                                f"فیلد «{rule.title or name}» جزو اقلام این الگو نیست و "
                                "نباید ارسال شود."
                            ),
                            reference=rule.reference,
                            context={"title": rule.title},
                        )
                    )
                continue
            if obligation is Obligation.OPTIONAL:
                continue
            if obligation is Obligation.CONDITIONAL and not rule.applies(header):
                continue
            if name not in header:
                violations.append(
                    Violation(
                        field=name,
                        rule=(
                            "obligation.conditional"
                            if obligation is Obligation.CONDITIONAL
                            else "obligation.required"
                        ),
                        message=rule.default_message,
                        reference=rule.reference,
                        context={"title": rule.title},
                    )
                )

        if not invoice.body:
            violations.append(
                Violation(
                    field="body",
                    rule="obligation.body_not_empty",
                    message="صورتحساب باید دست‌کم یک قلم کالا/خدمت داشته باشد.",
                    reference="RC_IITP §7",
                )
            )

        for index, item in enumerate(invoice.body):
            present = item.model_dump(exclude_none=True, by_alias=True)
            for name, rule in spec.body.items():
                if rule.for_type(invoice_type) is not Obligation.REQUIRED:
                    continue
                if name not in present:
                    violations.append(
                        Violation(
                            field=name,
                            line=index,
                            rule="obligation.required",
                            message=rule.default_message,
                            reference=rule.reference,
                            context={"title": rule.title},
                        )
                    )
        return violations

    # -- enumerations -----------------------------------------------------

    def _check_enums(self, invoice: Invoice) -> list[Violation]:
        header = invoice.header
        violations: list[Violation] = []
        for name, rule in self._rules.enums.items():
            value = getattr(header, name, None)
            if value is None:
                continue
            if int(value) not in rule.values:
                violations.append(
                    Violation(
                        field=name,
                        rule="enum.out_of_range",
                        message=rule.message,
                        reference=rule.reference,
                        actual=float(value),
                        context={"allowed": list(rule.values)},
                    )
                )
        return violations

    # -- the اعتبارسنجی button --------------------------------------------

    def verify(self, invoice: Invoice) -> VerificationResult:
        """Validate and render the outcome for a person.

        :meth:`validate` returns typed violations for code; this returns the same
        findings shaped for an اعتبارسنجی button and for an API response — Persian
        field titles, a one-line summary, and everything JSON-serialisable.
        """
        report = self.validate(invoice)
        spec = self._rules.pattern(invoice.header.inp or DEFAULT_PATTERN)
        titles: dict[str, str] = {}
        if spec is not None:
            for section in ("header", "body", "payment"):
                for name, rule in spec.section(section).items():
                    if rule.title:
                        titles.setdefault(name, rule.title)
        return VerificationResult.from_report(report, titles=titles, pattern=spec)
