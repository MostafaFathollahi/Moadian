"""The twelve v2 resource paths and the URL builder.

Paths are relative to ``{base}/api/v2/`` (WIRE_FORMAT.md "Base URLs"). Every
name here is the wire path verbatim.
"""

from __future__ import annotations

__all__ = [
    "API_PREFIX",
    "FISCAL_INFORMATION",
    "INQUIRY",
    "INQUIRY_BY_REFERENCE_ID",
    "INQUIRY_BY_UID",
    "INQUIRY_INVOICE_STATUS",
    "INVOICE",
    "INVOICE_PAYMENT",
    "NONCE",
    "SERVER_INFORMATION",
    "TAXPAYER",
    "TAXPAYER_ARTICLE6_STATUS",
    "TAXPAYER_INFO",
    "build_url",
]

#: Everything in v2 hangs off this prefix.
API_PREFIX = "/api/v2/"

# -- authentication
NONCE = "nonce"  # the only unauthenticated resource

# -- keys
SERVER_INFORMATION = "server-information"

# -- submission
INVOICE = "invoice"
INVOICE_PAYMENT = "invoice-payment"

# -- inquiry
INQUIRY = "inquiry"
INQUIRY_BY_UID = "inquiry-by-uid"
INQUIRY_BY_REFERENCE_ID = "inquiry-by-reference-id"
INQUIRY_INVOICE_STATUS = "inquiry-invoice-status"

# -- reference data
TAXPAYER = "taxpayer"
TAXPAYER_INFO = "taxpayer-info"
TAXPAYER_ARTICLE6_STATUS = "taxpayer-article6-status"
FISCAL_INFORMATION = "fiscal-information"


def build_url(base_url: str, endpoint: str) -> str:
    """Join a base URL and a v2 endpoint name.

    String concatenation only: ``os.path.join``/``pathlib`` collapse ``//`` in
    ``https://`` and rewrite separators on Windows, which silently produces a
    URL that resolves nowhere.
    """
    return base_url.rstrip("/") + API_PREFIX + endpoint.lstrip("/")
