"""Loads ``patterns.yaml`` into typed rules.

Kept separate from the engine so the matrix can be inspected, diffed and tested
on its own — "which fields does الگوی اول require?" is a question worth being
able to answer without running a validation.
"""

from __future__ import annotations

import functools
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from moadian.errors import ConfigurationError
from moadian.rules.violations import Obligation

__all__ = ["FieldRule", "PatternSpec", "RuleSet", "load_rules", "SPEC_PATH"]

SPEC_PATH = Path(__file__).parent / "patterns.yaml"

#: Conditions accepted in a `when:` clause. Deliberately a tiny fixed vocabulary
#: rather than eval() — these come from a data file, and an expression evaluator
#: reading a data file is a code-execution surface for no benefit.
_CONDITIONS = {
    "setm == 3": lambda h: h.get("setm") == 3,
    "insr == 1": lambda h: h.get("insr") == 1,
    "ins in (2, 3, 4)": lambda h: h.get("ins") in (2, 3, 4),
}

#: جدول ۱ marks a field اجباری در شرایط خاص without always naming the trigger, and
#: the §8 tables only name some of them. Such rules carry this sentinel and are
#: never enforced: a condition we cannot evaluate must not become a rejection.
UNSPECIFIED = "unspecified"


@dataclass(frozen=True)
class FieldRule:
    """How one field behaves under one pattern."""

    name: str
    obligation: Obligation
    reference: str = ""
    message: str = ""
    when: str | None = None
    #: Persian title as printed in جدول ۱ — what a UI should label the input.
    title: str = ""
    #: Per-نوع overrides: a field can be اجباری for نوع اول and اختیاری for نوع دوم.
    by_type: Mapping[int, Obligation] = field(default_factory=dict)

    def for_type(self, invoice_type: int | None) -> Obligation:
        """The obligation in force for this نوع صورتحساب."""
        if invoice_type is None:
            return self.obligation
        return self.by_type.get(int(invoice_type), self.obligation)

    def applies(self, header: dict[str, Any]) -> bool:
        """Whether a CONDITIONAL rule's condition currently holds.

        Unknown conditions return False: an unrecognised `when` must not
        manufacture a rejection. :func:`load_rules` already refuses to load one,
        so this is the belt to that braces.
        """
        if self.obligation is not Obligation.CONDITIONAL:
            return True
        if self.when is None or self.when == UNSPECIFIED:
            return False
        predicate = _CONDITIONS.get(self.when)
        return bool(predicate and predicate(header))

    @property
    def default_message(self) -> str:
        """A message naming the field the way جدول ۱ does, not by wire name.

        An operator reading "فیلد tins اجباری است" has to know the wire format to
        act on it; the Persian title is what the form labels the input.
        """
        if self.message:
            return self.message
        label = self.title or self.name
        if self.obligation is Obligation.CONDITIONAL:
            return f"در این حالت، ثبت «{label}» اجباری است."
        return f"ثبت «{label}» اجباری است."


@dataclass(frozen=True)
class PatternSpec:
    """One الگو."""

    number: int
    name: str
    name_en: str
    header: dict[str, FieldRule]
    body: dict[str, FieldRule]
    payment: dict[str, FieldRule] = field(default_factory=dict)
    #: Fields of the nested کالاهای حمل شده array (الگوی بارنامه). A sub-object
    #: rather than a top-level section, which is why it needs its own slot.
    sg: dict[str, FieldRule] = field(default_factory=dict)
    #: انواع صورتحساب this pattern is defined for, per the two header bands.
    types: tuple[int, ...] = (1,)
    reference: str = ""
    coverage: str = "partial"
    coverage_note: str = ""

    #: The sections an invoice actually has, in wire order.
    SECTIONS = ("header", "body", "payment", "sg")

    def section(self, name: str) -> dict[str, FieldRule]:
        return {
            "header": self.header,
            "body": self.body,
            "payment": self.payment,
            "sg": self.sg,
        }[name]

    @property
    def is_complete(self) -> bool:
        """False while the obligation matrix is only partly transcribed.

        Callers that must not under-report — a pre-submission gate, say — should
        surface this rather than treat a pass as a clean bill of health.
        """
        return self.coverage == "complete"

    def required_header_fields(self) -> tuple[str, ...]:
        return tuple(
            n for n, r in self.header.items() if r.obligation is Obligation.REQUIRED
        )

    def required_body_fields(self) -> tuple[str, ...]:
        return tuple(n for n, r in self.body.items() if r.obligation is Obligation.REQUIRED)


@dataclass(frozen=True)
class EnumRule:
    """A field constrained to a fixed set of wire values."""

    name: str
    values: tuple[int, ...]
    message: str
    reference: str


@dataclass(frozen=True)
class RuleSet:
    """Everything ``patterns.yaml`` describes."""

    version: int
    patterns: dict[int, PatternSpec]
    enums: dict[str, EnumRule]
    default_obligation: Obligation

    def pattern(self, number: int) -> PatternSpec | None:
        """The spec for an الگو, or None if it has not been transcribed yet.

        None is not an error: 15 of the 16 patterns are unencoded, and the engine
        reports that honestly rather than validating against an empty matrix and
        implying the invoice is fine.
        """
        return self.patterns.get(number)


def _field_rules(
    raw: dict[str, Any] | None,
    section: str,
    pattern: int,
    default_reference: str = "",
) -> dict[str, FieldRule]:
    rules: dict[str, FieldRule] = {}
    for name, spec in (raw or {}).items():
        try:
            obligation = Obligation(spec["obligation"])
        except (KeyError, ValueError) as exc:
            raise ConfigurationError(
                f"pattern {pattern}.{section}.{name} has an invalid obligation: {exc}"
            ) from exc
        when = spec.get("when")
        if obligation is Obligation.CONDITIONAL and when != UNSPECIFIED:
            if not when:
                raise ConfigurationError(
                    f"pattern {pattern}.{section}.{name} is conditional but names no 'when'"
                )
            if when not in _CONDITIONS:
                raise ConfigurationError(
                    f"pattern {pattern}.{section}.{name} uses an unknown condition {when!r}; "
                    f"known conditions are {sorted(_CONDITIONS)}"
                )
        rules[name] = FieldRule(
            name=name,
            obligation=obligation,
            reference=spec.get("reference") or spec.get("condition_reference") or default_reference,
            message=spec.get("message", ""),
            when=when,
            title=spec.get("title", ""),
            by_type={
                int(t): Obligation(o) for t, o in (spec.get("by_type") or {}).items()
            },
        )
    return rules


@functools.lru_cache(maxsize=4)
def load_rules(path: Path | None = None) -> RuleSet:
    """Parse the matrix. Cached — the file does not change at runtime."""
    path = path or SPEC_PATH
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ConfigurationError(f"cannot read rule spec {path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise ConfigurationError(f"rule spec {path} is not valid YAML: {exc}") from exc

    if not isinstance(raw, dict):
        raise ConfigurationError(f"rule spec {path} must be a mapping")

    patterns: dict[int, PatternSpec] = {}
    for number, spec in (raw.get("patterns") or {}).items():
        sections = {
            name: _field_rules(spec.get(name), name, int(number), spec.get("reference", ""))
            for name in ("header", "body", "payment", "sg")
        }
        # `excluded` lists the fields جدول ۱ marks as not belonging to this
        # pattern. Expanded into real rules here so the engine can report them,
        # while the file stays readable — 38 of ~102 are excluded for a plain sale.
        for name, names in (spec.get("excluded") or {}).items():
            if name not in sections:
                continue
            for wire in names:
                sections[name][wire] = FieldRule(
                    name=wire,
                    obligation=Obligation.NOT_APPLICABLE,
                    reference=spec.get("reference", ""),
                )
        patterns[int(number)] = PatternSpec(
            number=int(number),
            name=spec.get("name", ""),
            name_en=spec.get("name_en", ""),
            header=sections["header"],
            body=sections["body"],
            payment=sections["payment"],
            sg=sections["sg"],
            types=tuple(int(t) for t in (spec.get("types") or [1])),
            reference=spec.get("reference", ""),
            coverage=spec.get("coverage", "partial"),
            coverage_note=spec.get("coverage_note", ""),
        )

    enums: dict[str, EnumRule] = {}
    for name, spec in (raw.get("enums") or {}).items():
        enums[name] = EnumRule(
            name=name,
            values=tuple(int(v) for v in spec["values"]),
            message=spec.get("message", f"مقدار فیلد {name} مجاز نیست."),
            reference=spec.get("reference", ""),
        )

    default = Obligation((raw.get("defaults") or {}).get("obligation", "optional"))
    return RuleSet(
        version=int(raw.get("version", 1)),
        patterns=patterns,
        enums=enums,
        default_obligation=default,
    )
