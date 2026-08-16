"""Compact JWE encryption of the signed invoice to the tax organization.

RSA-OAEP-256 key wrap + A256GCM content encryption; see WIRE_FORMAT.md "JWE".
"""

from __future__ import annotations

import base64
import binascii
import json
import os
from dataclasses import dataclass

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from moadian.crypto.signatory import b64url
from moadian.errors import CryptographyError

__all__ = ["ServerKey", "JweEncryptor"]

_CEK_BYTES = 32  # A256GCM
_IV_BYTES = 12  # 96-bit GCM nonce, per RFC 7518 §5.3
_TAG_BYTES = 16

_OAEP = padding.OAEP(
    mgf=padding.MGF1(algorithm=hashes.SHA256()),
    algorithm=hashes.SHA256(),
    label=None,
)


@dataclass(frozen=True)
class ServerKey:
    """One entry of the ``publicKeys`` array from ``GET /server-information``."""

    id: str
    key: str
    """Standard base64 of the SPKI (X.509 SubjectPublicKeyInfo) DER, as returned."""
    algorithm: str = "RSA"
    purpose: int = 1

    def public_key(self) -> rsa.RSAPublicKey:
        """Decode ``key`` into a usable RSA public key."""
        try:
            der = base64.b64decode(self.key, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise CryptographyError(f"server key {self.id!r} is not valid base64: {exc}") from exc

        try:
            loaded = serialization.load_der_public_key(der)
        except ValueError as exc:
            raise CryptographyError(f"server key {self.id!r} is not a DER SPKI key: {exc}") from exc

        if not isinstance(loaded, rsa.RSAPublicKey):
            raise CryptographyError(
                f"server key {self.id!r} must be RSA, got {type(loaded).__name__}"
            )
        return loaded


class JweEncryptor:
    """Encrypts a signed invoice JWS to one server public key."""

    def __init__(self, server_key: ServerKey) -> None:
        self._server_key = server_key
        # Decoded once: the key is cached and reused for every invoice in a batch.
        self._public_key = server_key.public_key()

    @property
    def server_key(self) -> ServerKey:
        return self._server_key

    @property
    def kid(self) -> str:
        """The ``id`` recorded in the protected header — log it with the submission."""
        return self._server_key.id

    def encrypt(self, plaintext: str) -> str:
        """Return the five-segment compact JWE ``protected.key.iv.ciphertext.tag``."""
        header = {"alg": "RSA-OAEP-256", "enc": "A256GCM", "kid": self._server_key.id}
        protected = b64url(json.dumps(header, separators=(",", ":")).encode("utf-8"))

        cek = os.urandom(_CEK_BYTES)
        iv = os.urandom(_IV_BYTES)

        try:
            encrypted_key = self._public_key.encrypt(cek, _OAEP)
            # AAD binds the header to the ciphertext: tampering with kid breaks the tag.
            sealed = AESGCM(cek).encrypt(
                iv, plaintext.encode("utf-8"), protected.encode("ascii")
            )
        except (ValueError, TypeError) as exc:
            raise CryptographyError(f"JWE encryption failed: {exc}") from exc

        ciphertext, tag = sealed[:-_TAG_BYTES], sealed[-_TAG_BYTES:]
        return ".".join(
            [protected, b64url(encrypted_key), b64url(iv), b64url(ciphertext), b64url(tag)]
        )
