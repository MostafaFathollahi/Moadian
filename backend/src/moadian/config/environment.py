"""The two Moadian environments, and the URLs that identify them.

The service is the same API on two subdomains of ``tax.gov.ir``: ``sandboxrc``
for testing and ``tp`` for real filings. They are modelled as a type rather than
a pair of loose URL strings for one reason — **a شناسه یکتای حافظه مالیاتی is
issued per environment and is not portable between them**. A sandbox memory id
sent to production is rejected at best; the failure mode worth designing against
is the opposite one, where a production identity is used for what the operator
believed was a test.

So environment and memory id always travel together on a
:class:`~moadian.config.Profile`, and switching environments means selecting a
different profile, never editing a URL.
"""

from __future__ import annotations

from enum import StrEnum

from moadian.errors import ConfigurationError

__all__ = ["Environment"]

#: Accepted spellings, deliberately narrow. Each maps a name people actually use
#: for one of these two deployments: the subdomain they see in a URL (``sandboxrc``,
#: ``tp``) and the word they use for it (``operational`` is the term the Persian
#: documents use where the host is ``tp``).
#:
#: Generic devops vocabulary is *not* accepted. "staging" and "test" would imply a
#: third environment that does not exist, and silently resolving them to sandbox
#: would hide a configuration mistake rather than surface it.
_ALIASES = {
    "sandbox": "sandbox",
    "sandboxrc": "sandbox",
    "production": "production",
    "prod": "production",
    "operational": "production",
    "tp": "production",
}


class Environment(StrEnum):
    """Which Moadian deployment a profile targets."""

    SANDBOX = "sandbox"
    PRODUCTION = "production"

    @classmethod
    def parse(cls, value: str | Environment) -> Environment:
        """Resolve a spelling to an environment.

        Accepts the subdomain (``tp``), the English term (``production``), and
        the term the organization's documents use (``operational``), so a value
        copied from a URL, a config file or a PDF all land in the same place.
        """
        if isinstance(value, cls):
            return value
        try:
            return cls(_ALIASES[str(value).strip().lower()])
        except KeyError:
            raise ConfigurationError(
                f"unknown environment {value!r}; expected one of "
                f"{', '.join(sorted(set(_ALIASES)))}"
            ) from None

    @property
    def host(self) -> str:
        """The fully qualified host, e.g. ``sandboxrc.tax.gov.ir``."""
        return f"{'sandboxrc' if self is Environment.SANDBOX else 'tp'}.tax.gov.ir"

    @property
    def base_url(self) -> str:
        """Base URL for the collection web service. No trailing slash.

        Paths are appended by string join, so a trailing slash here would produce
        ``//api/v2`` — see WIRE_FORMAT.md "Base URLs".
        """
        return f"https://{self.host}/requestsmanager"

    @property
    def is_production(self) -> bool:
        """True for the operational environment, where filings are real.

        Worth branching on in a UI: an operator should never have to read a URL
        to work out whether the invoice they are about to send is real.
        """
        return self is Environment.PRODUCTION

    @property
    def label(self) -> str:
        """Persian label, for UI surfaces."""
        return "عملیاتی" if self.is_production else "آزمایشی"
