"""Loading and sanity-checking the taxpayer's signing certificate and key."""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from moadian.errors import CertificateError

__all__ = ["SigningCredentials", "load_certificate"]


def load_certificate(data: bytes) -> x509.Certificate:
    """Accept PEM, DER, or bare base64 — all three arrive named ``.crt``.

    The third is not a hypothetical. مرکز توسعه تجارت الکترونیکی delivers the
    issued certificate as the base64 body with no ``-----BEGIN CERTIFICATE-----``
    armour around it, which is a valid thing to paste into a form and an invalid
    thing to hand to a PEM parser. Rejecting it would mean telling an operator
    their real, correctly issued certificate is corrupt, and the fix — adding two
    lines by hand — is one they should not have to find.

    Public, and the only certificate reader in the application. It was private
    once, which is exactly how :meth:`Profile.certificate` came to call
    ``load_pem_x509_certificate`` directly and reject a certificate the signing
    path had already accepted — the panel said the pair matched while the
    dashboard said the file was unreadable, about the same file.
    """
    try:
        if b"-----BEGIN" in data:
            return x509.load_pem_x509_certificate(data)
        return x509.load_der_x509_certificate(data)
    except ValueError as der_error:
        armoured = _armour(data)
        if armoured is None:
            raise CertificateError(f"could not parse certificate: {der_error}") from der_error
        try:
            return x509.load_pem_x509_certificate(armoured)
        except ValueError as exc:
            raise CertificateError(f"could not parse certificate: {exc}") from exc


def _armour(data: bytes) -> bytes | None:
    """Wrap a bare base64 body in PEM armour, or ``None`` if it is not base64.

    Whitespace-insensitive, so the CRLF line endings these files arrive with are
    not a second failure mode.
    """
    body = b"".join(data.split())
    if not body:
        return None
    try:
        base64.b64decode(body, validate=True)
    except (binascii.Error, ValueError):
        return None
    lines = [body[i : i + 64] for i in range(0, len(body), 64)]
    return b"-----BEGIN CERTIFICATE-----\n" + b"\n".join(lines) + b"\n-----END CERTIFICATE-----\n"


def _load_private_key(data: bytes, password: bytes | None) -> rsa.RSAPrivateKey:
    try:
        key = serialization.load_pem_private_key(data, password=password)
    except (ValueError, TypeError) as exc:
        raise CertificateError(f"could not parse private key: {exc}") from exc
    if not isinstance(key, rsa.RSAPrivateKey):
        raise CertificateError(f"signing key must be RSA, got {type(key).__name__}")
    return key


@dataclass(frozen=True)
class SigningCredentials:
    """A taxpayer signing certificate together with its RSA private key."""

    certificate: x509.Certificate
    private_key: rsa.RSAPrivateKey

    @classmethod
    def from_files(
        cls,
        cert_path: str | Path,
        key_path: str | Path,
        key_password: bytes | None = None,
    ) -> SigningCredentials:
        """Load from a certificate file and an (optionally encrypted) PKCS#8 PEM key."""
        try:
            cert_bytes = Path(cert_path).read_bytes()
            key_bytes = Path(key_path).read_bytes()
        except OSError as exc:
            raise CertificateError(f"could not read credentials: {exc}") from exc
        return cls.from_pem(cert_bytes, key_bytes, key_password)

    @classmethod
    def from_pem(
        cls,
        cert_pem: bytes,
        key_pem: bytes,
        key_password: bytes | None = None,
    ) -> SigningCredentials:
        """Load from in-memory certificate and private-key bytes."""
        return cls(
            certificate=load_certificate(cert_pem),
            private_key=_load_private_key(key_pem, key_password),
        )

    @property
    def national_id(self) -> str | None:
        """Subject ``SERIALNUMBER`` (OID 2.5.4.5) — the کد ملی/شناسه ملی.

        The tax organization requires this identity to hold send-permission for
        the ``clientId`` (fiscal memory) used at submission time; a mismatch is
        rejected at the API, not here.
        """
        attrs = self.certificate.subject.get_attributes_for_oid(NameOID.SERIAL_NUMBER)
        if not attrs:
            return None
        value = attrs[0].value
        return value.decode() if isinstance(value, bytes) else value

    @property
    def der(self) -> bytes:
        """The certificate's DER encoding — what goes into the JWS ``x5c`` header."""
        return self.certificate.public_bytes(serialization.Encoding.DER)

    def assert_usable(self, at: datetime | None = None) -> None:
        """Raise :class:`CertificateError` unless the pair is valid and matched.

        Both checks fail silently otherwise: an expired certificate is rejected
        only by the API, and a mismatched key produces a well-formed JWS whose
        signature nobody can verify.
        """
        moment = at or datetime.now(UTC)
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=UTC)

        not_before = self.certificate.not_valid_before_utc
        not_after = self.certificate.not_valid_after_utc
        if moment < not_before:
            raise CertificateError(
                f"certificate is not valid until {not_before.isoformat()} "
                f"(now {moment.isoformat()})"
            )
        if moment > not_after:
            raise CertificateError(
                f"certificate expired at {not_after.isoformat()} (now {moment.isoformat()})"
            )

        cert_key = self.certificate.public_key()
        if not isinstance(cert_key, rsa.RSAPublicKey):
            raise CertificateError(
                f"certificate public key must be RSA, got {type(cert_key).__name__}"
            )
        if cert_key.public_numbers() != self.private_key.public_key().public_numbers():
            raise CertificateError("private key does not match the certificate public key")
