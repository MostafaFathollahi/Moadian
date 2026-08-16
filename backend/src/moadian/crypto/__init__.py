"""Signing, encryption, and the canonical JSON the signature covers.

Protocol facts are pinned in WIRE_FORMAT.md; the JWS protected header and the
JWE algorithm choices there are load-bearing and must not drift.
"""

from moadian.crypto.canonical import canonical_json, strip_nulls
from moadian.crypto.encryptor import JweEncryptor, ServerKey
from moadian.crypto.keys import SigningCredentials
from moadian.crypto.signatory import (
    SIGT_FORMAT,
    Pkcs8Signatory,
    Signatory,
    b64url,
    b64url_decode,
)

__all__ = [
    "canonical_json",
    "strip_nulls",
    "SigningCredentials",
    "Signatory",
    "Pkcs8Signatory",
    "SIGT_FORMAT",
    "b64url",
    "b64url_decode",
    "ServerKey",
    "JweEncryptor",
]
