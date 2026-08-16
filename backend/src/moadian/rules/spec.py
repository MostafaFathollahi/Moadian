"""Loads ``patterns.yaml`` into typed rules.

Kept separate from the engine so the matrix can be inspected, diffed and tested
on its own — "which fields does الگوی اول require?" is a question worth being
able to answer without running a validation.
"""

from __future__ import annotations

import functools
from dataclasses import dataclass
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


@dataclass(frozen=True)
class FieldRule:
    """How one field behaves under one pattern."""

    name: str
    obligation: Obligation
    reference: str = ""
    message: str = ""
    when: str | None = None

    def applies(self, header: dict[str, Any]) -> bool:
        """Whether a CONDITIONAL rule's condition currently holds.

        Unknown conditions return False: an unrecognised `when` must not
        manufacture a rejection. :func:`load_rules` already refuses to load one,
        so this is the belt to that braces.
        """
        if self.obligation is not Obligation.CONDITIONAL:
            return True
        if self.when is None:
            return False
        predicate = _CONDITIONS.get(self.when)
        return bool(predicate and predicate(header))

    @property
    def default_message(self) -> str:
        return self.message or f"فیلد {self.name} اجباری است."


@dataclass(frozen=True)
class PatternSpec:
    """One الگو."""

    number: int
    name: str
    name_en: str
    header: dict[str, FieldRule]
    body: dict[str, FieldRule]
    reference: str = ""
    coverage: str = "partial"
    coverage_note: str = ""

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


def _field_rules(raw: dict[str, Any] | None, section: str, pattern: int) -> dict[str, FieldRule]:
    rules: dict[str, FieldRule] = {}
    for name, spec in (raw or {}).items():
        try:
            obligation = Obligation(spec["obligation"])
        except (KeyError, ValueError) as exc:
            raise ConfigurationError(
                f"pattern {pattern}.{section}.{name} has an invalid obligation: {exc}"
            ) from exc
        when = spec.get("when")
        if obligation is Obligation.CONDITIONAL:
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
            reference=spec.get("reference", ""),
            message=spec.get("message", ""),
            when=when,
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
        patterns[int(number)] = PatternSpec(
            number=int(number),
            name=spec.get("name", ""),
            name_en=spec.get("name_en", ""),
            header=_field_rules(spec.get("header"), "header", int(number)),
            body=_field_rules(spec.get("body"), "body", int(number)),
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
