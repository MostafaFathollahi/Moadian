"""Where signing material comes from: the environment, and nothing else.

**No part of a key or certificate path is ever accepted over HTTP.** The paths
come from the process environment at startup, are resolved once, and a profile
selects between them only by naming which *environment* it belongs to. There is
no field in any request body that influences which file is read, so there is no
traversal surface to defend and no key byte in a browser, a request body, a
proxy buffer or the logs those touch.

Configured with, in ``.env``::

    MOADIAN_CERTIFICATE_PATH=/secure/moadian/cert.crt
    MOADIAN_PRIVATE_KEY_PATH=/secure/moadian/key.pem

and, when the two environments use different certificates — the usual case once
a CA-issued certificate exists for production but only a test one for sandbox::

    MOADIAN_SANDBOX_CERTIFICATE_PATH=/secure/moadian/sandbox.crt
    MOADIAN_SANDBOX_PRIVATE_KEY_PATH=/secure/moadian/sandbox.pem
    MOADIAN_PRODUCTION_CERTIFICATE_PATH=/secure/moadian/prod.crt
    MOADIAN_PRODUCTION_PRIVATE_KEY_PATH=/secure/moadian/prod.pem

The key rests on the filesystem rather than inside the passphrase-encrypted
profile store, so it is protected by file mode — which :meth:`SigningMaterial.describe`
reports, flagging anything group- or world-readable — and optionally by its own
PKCS#8 encryption via :data:`KEY_PASSPHRASE_ENV`. With that set the key is
encrypted at rest *and* never transits the application.
"""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from pathlib import Path

from moadian.config.environment import Environment
from moadian.errors import ConfigurationError

__all__ = ["SigningMaterial", "MaterialStatus", "KEY_PASSPHRASE_ENV"]

#: Optional passphrase for an encrypted PKCS#8 private key. Read from the
#: environment, never from a request, and never stored.
KEY_PASSPHRASE_ENV = "MOADIAN_KEY_PASSPHRASE"


@dataclass(frozen=True)
class MaterialStatus:
    """Whether a configured path is usable, described without exposing contents."""

    configured: bool
    path: str | None
    exists: bool = False
    mode: str | None = None
    world_readable: bool = False
    error: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "configured": self.configured,
            # The path is shown so an operator can see which file is in force.
            # It is a filename, not a secret, and the admin panel is useless
            # without it when a certificate turns out to be the wrong one.
            "path": self.path,
            "exists": self.exists,
            "mode": self.mode,
            "worldReadable": self.world_readable,
            "error": self.error,
        }


@dataclass(frozen=True)
class SigningMaterial:
    """The certificate and key paths in force for one environment."""

    environment: Environment
    certificate_path: Path | None
    private_key_path: Path | None

    def require(self) -> tuple[Path, Path]:
        """Both paths, or a message naming exactly which variable is missing."""
        env = "SANDBOX" if self.environment is Environment.SANDBOX else "PRODUCTION"
        if self.certificate_path is None:
            raise ConfigurationError(
                f"no certificate configured for {self.environment}. Set "
                f"MOADIAN_CERTIFICATE_PATH or MOADIAN_{env}_CERTIFICATE_PATH."
            )
        if self.private_key_path is None:
            raise ConfigurationError(
                f"no private key configured for {self.environment}. Set "
                f"MOADIAN_PRIVATE_KEY_PATH or MOADIAN_{env}_PRIVATE_KEY_PATH."
            )
        for label, path in (
            ("certificate", self.certificate_path),
            ("private key", self.private_key_path),
        ):
            if not path.is_file():
                raise ConfigurationError(
                    f"the {label} configured for {self.environment} is not present "
                    f"at {path}. Place it there on the server; it is never uploaded."
                )
        return self.certificate_path, self.private_key_path

    def load(self):  # -> SigningCredentials
        """Read the pair and return a signing object.

        The only place private key bytes are read. They go into
        :class:`~moadian.crypto.SigningCredentials` and are never returned,
        stored on a profile, or serialised.
        """
        from moadian.crypto import SigningCredentials

        certificate_path, private_key_path = self.require()
        credentials = SigningCredentials.from_files(
            certificate_path, private_key_path, key_password=passphrase()
        )
        credentials.assert_usable()
        return credentials

    def describe(self) -> dict[str, object]:
        """Status for the admin panel: configured, present, and how protected.

        Never reads file contents. Listing signing material must not become a way
        to extract it.
        """
        return {
            "environment": str(self.environment),
            "certificate": _status(self.certificate_path).as_dict(),
            "privateKey": _status(self.private_key_path, expect_private=True).as_dict(),
            "keyPassphraseSet": passphrase() is not None,
        }

    def verify(self) -> dict[str, object]:
        """Does the private key actually belong to the certificate?

        :meth:`describe` answers "are the files there"; this answers "are they a
        pair". The two failures look identical from outside and both are fatal at
        a different moment: an unmatched key produces a perfectly well-formed JWS
        that the organization rejects with a signature error, long after the
        serial has been spent, and the only clue is a code in جدول کدهای خطا.
        Checking it costs one RSA modulus comparison, so there is no reason for
        an operator to ever discover it that way.

        Reads both files and compares the certificate's public modulus and
        exponent against the private key's. **Returns no key material**: the
        result carries a boolean, the subject, the validity window, and a
        fingerprint of the public key — enough to tell two certificates apart,
        and not enough to be one.

        Never raises. Every failure — missing path, unreadable file, wrong
        passphrase, unmatched pair — comes back as a report with ``ok`` false and
        a Persian message, because all of them are things the admin panel has to
        render rather than turn into a 500.
        """
        from datetime import UTC, datetime

        from moadian.crypto.keys import _load_private_key, load_certificate
        from moadian.errors import CertificateError

        report: dict[str, object] = {
            "environment": str(self.environment),
            "environmentLabel": self.environment.label,
            "certificatePath": str(self.certificate_path) if self.certificate_path else None,
            "privateKeyPath": str(self.private_key_path) if self.private_key_path else None,
            "keyPassphraseSet": passphrase() is not None,
            "ok": False,
            "matches": None,
            "certificate": None,
            "message": "",
        }

        try:
            certificate_path, private_key_path = self.require()
        except ConfigurationError as exc:
            report["message"] = _persian_material_error(exc)
            return report

        # The certificate first and on its own. It is the half that carries the
        # identity, and an operator whose key is merely locked still needs to see
        # *which* certificate is deployed — that is half of what this button is
        # for. Reading them together would throw both away over one failure.
        try:
            certificate = load_certificate(certificate_path.read_bytes())
        except (CertificateError, OSError) as exc:
            report["message"] = f"فایل گواهی ({certificate_path}) خوانده یا تفسیر نشد: {exc}"
            return report

        report["certificate"] = _certificate_summary(certificate)

        try:
            private_key = _load_private_key(private_key_path.read_bytes(), passphrase())
        except (CertificateError, OSError) as exc:
            report["message"] = _persian_key_error(exc, private_key_path)
            return report

        # The match before the dates: a mismatched pair and an expired
        # certificate are different problems with different fixes, and an
        # operator told only "unusable" cannot tell which one they have.
        matches = _keys_match(certificate, private_key)
        report["matches"] = matches
        if not matches:
            report["message"] = (
                "کلید خصوصی با گواهی مطابقت ندارد. کلید عمومیِ استخراج‌شده از فایل گواهی "
                f"({certificate_path}) با کلید خصوصی ({private_key_path}) یک زوج نیستند؛ "
                "امضا تولید می‌شود ولی سامانه مودیان آن را رد می‌کند. معمولاً یعنی یکی از "
                "دو فایل مربوط به درخواست صدور دیگری است."
            )
            return report

        now = datetime.now(UTC)
        not_before = certificate.not_valid_before_utc
        not_after = certificate.not_valid_after_utc
        if now < not_before:
            report["message"] = (
                f"کلید و گواهی زوج هستند، ولی گواهی تا {not_before.date().isoformat()} "
                "معتبر نمی‌شود."
            )
            return report
        if now > not_after:
            report["message"] = (
                f"کلید و گواهی زوج هستند، ولی گواهی در {not_after.date().isoformat()} "
                "منقضی شده است."
            )
            return report

        report["ok"] = True
        report["message"] = (
            "کلید خصوصی با گواهی مطابقت دارد. گواهی معتبر است و "
            f"{(not_after - now).days} روز تا انقضا باقی مانده است."
        )
        return report


def _keys_match(certificate, private_key) -> bool:
    """The certificate's public numbers against the private key's — the whole check.

    Comparing ``RSAPublicNumbers`` compares the modulus and the exponent, which
    is what "these are a pair" means for RSA. Signing a probe and verifying it
    would prove the same thing more slowly.
    """
    from cryptography.hazmat.primitives.asymmetric import rsa

    certificate_key = certificate.public_key()
    if not isinstance(certificate_key, rsa.RSAPublicKey):
        return False
    return certificate_key.public_numbers() == private_key.public_key().public_numbers()


def _certificate_summary(certificate) -> dict[str, object]:
    """What the panel shows about a certificate. No key bytes, by construction."""
    import hashlib

    from cryptography.hazmat.primitives import serialization
    from cryptography.x509.oid import NameOID

    public_der = certificate.public_key().public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    # A truncated digest of the *public* key. Public by definition, and short
    # enough to read aloud when checking that what is deployed is what the CA
    # issued — which is the operator task this actually supports.
    digest = hashlib.sha256(public_der).hexdigest()[:32]
    national_id = certificate.subject.get_attributes_for_oid(NameOID.SERIAL_NUMBER)
    return {
        "subject": certificate.subject.rfc4514_string(),
        "issuer": certificate.issuer.rfc4514_string(),
        "serialNumber": format(certificate.serial_number, "x"),
        "notBefore": certificate.not_valid_before_utc.isoformat(),
        "notAfter": certificate.not_valid_after_utc.isoformat(),
        # شناسه ملی. The organization checks this against the fiscal memory's
        # send-permission, so it is the field an operator most often needs to read.
        "nationalId": national_id[0].value if national_id else None,
        "keySize": certificate.public_key().key_size,
        "publicKeyFingerprint": ":".join(digest[i : i + 4] for i in range(0, len(digest), 4)),
    }


def _persian_key_error(exc: Exception, path: Path) -> str:
    """Name the specific fix. "could not parse private key" names none of them."""
    text = str(exc)
    if "Password was not given" in text:
        return (
            f"کلید خصوصی ({path}) رمزگذاری‌شده است و گذرواژه‌ای برای آن تنظیم نشده. "
            "مقدار MOADIAN_KEY_PASSPHRASE را در فایل .env سرور قرار دهید و سرویس را "
            "دوباره راه‌اندازی کنید."
        )
    if "Incorrect password" in text or "Bad decrypt" in text:
        return (
            f"گذرواژه‌ی MOADIAN_KEY_PASSPHRASE کلید خصوصی ({path}) را باز نکرد. "
            "همان گذرواژه‌ای لازم است که هنگام ساخت یا استخراج کلید تعیین شده."
        )
    return f"کلید خصوصی ({path}) خوانده یا تفسیر نشد: {text}"


def _persian_material_error(exc: ConfigurationError) -> str:
    """:meth:`SigningMaterial.require` speaks English to the log; the panel does not."""
    text = str(exc)
    if "no certificate configured" in text:
        return (
            "مسیر گواهی امضا تنظیم نشده است. MOADIAN_CERTIFICATE_PATH را در فایل .env "
            "سرور مقدار دهید."
        )
    if "no private key configured" in text:
        return (
            "مسیر کلید خصوصی تنظیم نشده است. MOADIAN_PRIVATE_KEY_PATH را در فایل .env "
            "سرور مقدار دهید."
        )
    return f"فایل تنظیم‌شده در دسترس نیست: {text}"


def _status(path: Path | None, *, expect_private: bool = False) -> MaterialStatus:
    if path is None:
        return MaterialStatus(configured=False, path=None)
    if not path.exists():
        return MaterialStatus(
            configured=True, path=str(path), exists=False, error="file not found"
        )
    info = path.stat()
    mode = stat.S_IMODE(info.st_mode)
    world_readable = bool(mode & (stat.S_IRGRP | stat.S_IROTH))
    error = None
    if expect_private and world_readable:
        error = "readable by group or other; chmod 600 it"
    return MaterialStatus(
        configured=True,
        path=str(path),
        exists=True,
        mode=format(mode, "04o"),
        world_readable=world_readable,
        error=error,
    )


#: Set by :func:`moadian.auth.security.configure`-style wiring in create_app, so
#: a value in `.env` reaches this module. See that function for why reading
#: os.environ directly is not enough.
_CONFIGURED_PASSPHRASE: str | None = None


def set_passphrase(value: str | None) -> None:
    global _CONFIGURED_PASSPHRASE
    _CONFIGURED_PASSPHRASE = value


def passphrase() -> bytes | None:
    """The PKCS#8 passphrase, if the private key is encrypted at rest."""
    value = _CONFIGURED_PASSPHRASE or os.environ.get(KEY_PASSPHRASE_ENV)
    return value.encode() if value else None
