"""What a rule check produces.

A violation names the field, quotes the rule it broke in the organization's own
terms, and points at the clause in RC_IITP_IS_V7_9_1 that says so. The citation
matters: when the tax service rejects an invoice we accepted, the first question
is always "which document says otherwise", and a violation that cannot answer it
is not much better than a boolean.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

__all__ = [
    "Severity",
    "Violation",
    "Obligation",
    "ValidationReport",
    "VerificationResult",
]


class Severity(StrEnum):
    """Whether a finding blocks submission."""

    #: The organization will reject the invoice. Do not send it.
    ERROR = "error"
    #: Accepted, but likely not what was meant — surfaced for the operator.
    WARNING = "warning"


class Obligation(StrEnum):
    """How a field is required, per the الگو (pattern) matrix in RC_IITP table 1."""

    #: اجباری — must be present.
    REQUIRED = "required"
    #: اختیاری — may be absent.
    OPTIONAL = "optional"
    #: اجباری در شرایط خاص — required only when a stated condition holds.
    CONDITIONAL = "conditional"
    #: Not part of this pattern at all. Sending it is a structural error:
    #: "صورتحساب‌های الکترونیکی صرفا شامل اقلام مذکور بوده" (RC_IITP §4).
    NOT_APPLICABLE = "not_applicable"


@dataclass(frozen=True)
class Violation:
    """One broken rule."""

    #: Wire field name, e.g. ``tbill`` or ``body[0].vam``.
    field: str
    #: Stable identifier, e.g. ``arithmetic.tsstam`` or ``obligation.required``.
    rule: str
    #: Persian, phrased as the operator will read it in the UI.
    message: str
    #: Where RC_IITP says so, e.g. "§8-51، جدول ۵۳".
    reference: str
    severity: Severity = Severity.ERROR
    #: Populated by arithmetic checks so the UI can show the discrepancy.
    expected: float | None = None
    actual: float | None = None
    #: Zero-based index when the violation is on a body or payment line.
    line: int | None = None
    #: Extra machine-readable context, e.g. the pattern in force.
    context: dict[str, object] = field(default_factory=dict)

    def __str__(self) -> str:
        where = f"{self.field}" if self.line is None else f"{self.field}[{self.line}]"
        detail = ""
        if self.expected is not None and self.actual is not None:
            detail = f" (انتظار {self.expected:,.0f}، دریافت {self.actual:,.0f})"
        return f"[{self.severity}] {where}: {self.message}{detail} — {self.reference}"


@dataclass(frozen=True)
class ValidationReport:
    """The result of checking one invoice."""

    violations: tuple[Violation, ...] = ()

    @property
    def errors(self) -> tuple[Violation, ...]:
        return tuple(v for v in self.violations if v.severity is Severity.ERROR)

    @property
    def warnings(self) -> tuple[Violation, ...]:
        return tuple(v for v in self.violations if v.severity is Severity.WARNING)

    @property
    def ok(self) -> bool:
        """True when nothing blocks submission. Warnings do not block."""
        return not self.errors

    def __bool__(self) -> bool:
        return self.ok

    def raise_if_invalid(self) -> None:
        """Raise :class:`~moadian.errors.InvoiceValidationError` if this blocks sending.

        The pipeline calls this before minting a tax id: a serial spent on an
        invoice the organization will refuse is a serial that cannot be reused.
        """
        if self.ok:
            return
        from moadian.errors import InvoiceValidationError

        raise InvoiceValidationError(self.errors)


@dataclass(frozen=True)
class VerificationResult:
    """A :class:`ValidationReport` rendered for a person.

    What the اعتبارسنجی button in the invoice form shows, and what the API
    returns: Persian field titles from جدول ۱, a one-line summary, and nothing
    that is not JSON-serialisable.
    """

    ok: bool
    summary: str
    errors: tuple[dict[str, object], ...] = ()
    warnings: tuple[dict[str, object], ...] = ()
    pattern: int | None = None
    pattern_name: str = ""

    @staticmethod
    def _render(violation: Violation, titles: dict[str, str]) -> dict[str, object]:
        return {
            "field": violation.field,
            "title": titles.get(violation.field, "") or violation.context.get("title", ""),
            "line": violation.line,
            "rule": violation.rule,
            "message": violation.message,
            "reference": violation.reference,
            "expected": violation.expected,
            "actual": violation.actual,
        }

    @classmethod
    def from_report(
        cls,
        report: ValidationReport,
        *,
        titles: dict[str, str] | None = None,
        pattern: object | None = None,
    ) -> VerificationResult:
        titles = titles or {}
        errors = tuple(cls._render(v, titles) for v in report.errors)
        warnings = tuple(cls._render(v, titles) for v in report.warnings)
        if not errors:
            summary = "صورتحساب معتبر است."
            if warnings:
                summary += f" ({len(warnings)} هشدار)"
        elif len(errors) == 1:
            summary = f"یک خطا یافت شد: {errors[0]['message']}"
        else:
            summary = f"{len(errors)} خطا در صورتحساب یافت شد."
        return cls(
            ok=not errors,
            summary=summary,
            errors=errors,
            warnings=warnings,
            pattern=getattr(pattern, "number", None),
            pattern_name=getattr(pattern, "name", ""),
        )

    def as_dict(self) -> dict[str, object]:
        """JSON-ready, for an API response."""
        return {
            "ok": self.ok,
            "summary": self.summary,
            "pattern": self.pattern,
            "patternName": self.pattern_name,
            "errors": list(self.errors),
            "warnings": list(self.warnings),
        }
