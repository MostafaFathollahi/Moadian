"""Compact JWS signing — used for both the auth token and the invoice.

The structure is identical for both (RC_TICS §5-1-2, §7-1-2); only the payload
differs. See WIRE_FORMAT.md "JWS".
"""

from __future__ import annotations

import base64
import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Protocol, runtime_checkable

from cryptography.exceptions import UnsupportedAlgorithm
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding

from moadian.crypto.keys import SigningCredentials
from moadian.errors import CryptographyError

__all__ = ["Signatory", "Pkcs8Signatory", "SIGT_FORMAT", "b64url", "b64url_decode"]

#: "yyyy-MM-dd'T'HH:mm:ss'Z'", UTC — the format the reference Java sample uses.
SIGT_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


def b64url(data: bytes) -> str:
    """Unpadded base64url, as JOSE requires."""
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def b64url_decode(text: str) -> bytes:
    """Inverse of :func:`b64url`, restoring the stripped padding."""
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


@runtime_checkable
class Signatory(Protocol):
    """Produces a compact JWS over raw payload bytes.

    A Protocol so a PKCS#11 (hardware token) implementation can drop in beside
    the PKCS#8 one without a shared base class.
    """

    def sign(self, payload: bytes) -> str: ...


class Pkcs8Signatory:
    """Signs with an in-process RSA private key loaded from PKCS#8 PEM."""

    def __init__(
        self,
        credentials: SigningCredentials,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._credentials = credentials
        # Injectable so tests can reproduce the documented vector, whose sigT is
        # baked into the signed header bytes.
        self._clock = clock or (lambda: datetime.now(UTC))

    @property
    def credentials(self) -> SigningCredentials:
        return self._credentials

    def sign(self, payload: bytes) -> str:
        """Return ``header.payload.signature``, RS256 over the ASCII signing input."""
        protected = b64url(self._protected_header())
        body = b64url(payload)
        signing_input = f"{protected}.{body}".encode("ascii")

        try:
            signature = self._credentials.private_key.sign(
                signing_input, padding.PKCS1v15(), hashes.SHA256()
            )
        except (UnsupportedAlgorithm, ValueError, TypeError) as exc:
            raise CryptographyError(f"JWS signing failed: {exc}") from exc

        return f"{protected}.{body}.{b64url(signature)}"

    def _protected_header(self) -> bytes:
        """Exactly four keys, in this order — anything else changes the signed bytes.

        The .NET SDK also emits ``typ`` and ``cty``; RC_TICS.IS_v1.6 does not
        define them, so they are omitted (WIRE_FORMAT.md wins).
        """
        header = {
            "crit": ["sigT"],
            "sigT": self._sig_time(),
            # Standard base64 of the DER, per RFC 7515 §4.1.6 — NOT base64url.
            "x5c": [base64.b64encode(self._credentials.der).decode("ascii")],
            "alg": "RS256",
        }
        return json.dumps(header, separators=(",", ":")).encode("utf-8")

    def _sig_time(self) -> str:
        now = self._clock()
        if now.tzinfo is not None:
            now = now.astimezone(UTC)
        return now.strftime(SIGT_FORMAT)
