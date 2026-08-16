"""HTTP access to the tax organization's v2 API.

``MoadianClient`` is the whole surface; ``build_packet`` is the bridge from a
wire-shaped invoice dict to something ``submit_invoices`` accepts.
"""

from moadian.client import endpoints
from moadian.client.api import MoadianClient, build_packet, format_query_datetime
from moadian.client.auth import NonceAuthenticator
from moadian.client.endpoints import build_url

__all__ = [
    "MoadianClient",
    "NonceAuthenticator",
    "build_packet",
    "build_url",
    "endpoints",
    "format_query_datetime",
]
