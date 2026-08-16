"""Offline validation against RC_IITP_IS_V7_9_1.

The tax service validates asynchronously and a rejected invoice has already
spent a tax id, so everything checkable before signing is checked here::

    report = RuleEngine().validate(invoice)
    if not report.ok:
        for violation in report.errors:
            print(violation)

:func:`~moadian.rules.arithmetic.recompute` fills the derived money fields from
their inputs, which is what an entry form's "calculate" action wants.
"""

from moadian.rules.arithmetic import TOLERANCE_RIAL, check_arithmetic, recompute
from moadian.rules.engine import RuleEngine
from moadian.rules.spec import FieldRule, PatternSpec, RuleSet, load_rules
from moadian.rules.violations import (
    Obligation,
    Severity,
    ValidationReport,
    Violation,
)

__all__ = [
    "RuleEngine",
    "ValidationReport",
    "Violation",
    "Severity",
    "Obligation",
    "FieldRule",
    "PatternSpec",
    "RuleSet",
    "load_rules",
    "check_arithmetic",
    "recompute",
    "TOLERANCE_RIAL",
]
