"""Multi-profile credential storage, encrypted at rest.

A profile is one fiscal memory (شناسه یکتای حافظه مالیاتی) plus the signing
certificate and private key that speak for it. Several may coexist — a taxpayer
with two shops, or a sandbox profile alongside production — so the store is
keyed by a human-chosen name.

This module deliberately does not import ``moadian.crypto``: credential storage
must stay usable even when the signing stack is not.
"""

from __future__ import annotations

import base64
import json
import os
import re
import secrets
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from cryptography import x509
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

from moadian.config.environment import Environment
from moadian.errors import ConfigurationError

__all__ = ["Profile", "ProfileStore"]

# شناسه یکتای حافظه مالیاتی: 6 chars, uppercase latin letters or digits.
# Enforced server-side too — error 4148 rejects anything else.
_MEMORY_ID_RE = re.compile(r"^[A-Z0-9]{6}$")

_FILE_VERSION = 1
_SCRYPT_N = 2**15
_SCRYPT_R = 8
_SCRYPT_P = 1
_KEY_LENGTH = 32
_SALT_LENGTH = 16
_NONCE_LENGTH = 12


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def _unb64(text: str, field: str) -> bytes:
    try:
        return base64.b64decode(text, validate=True)
    except (ValueError, TypeError) as exc:
        raise ConfigurationError(f"profile store field {field!r} is not valid base64") from exc


@dataclass
class Profile:
    """One fiscal memory's credentials.

    ``certificate_pem`` and ``private_key_pem`` are ``repr=False``: the key is an
    *unencrypted* PKCS#8 PEM, and the generated ``__repr__`` is exactly what a
    ``logger.exception`` with locals, a debugger frame dump, or a stray ``print``
    would render. Keeping the signing credential out of that string is cheaper
    than auditing every call site that might stringify a profile. Use
    :meth:`redacted` when a description is wanted.
    """

    name: str
    memory_id: str
    environment: Environment
    certificate_pem: bytes = field(repr=False)
    private_key_pem: bytes = field(repr=False)
    economic_code: str | None = None
    #: Overrides the environment's URL. For pointing tests at the in-process mock
    #: — not for reaching the real service, which lives at exactly two addresses.
    base_url_override: str | None = None

    def __post_init__(self) -> None:
        # Accept "tp", "operational", "prod" and friends wherever an environment
        # is expected, including values coming back off disk.
        self.environment = Environment.parse(self.environment)

    @property
    def base_url(self) -> str:
        """Where this profile's requests go.

        Derived from :attr:`environment` rather than stored, so a profile cannot
        drift into holding a sandbox memory id alongside a production URL.
        """
        return self.base_url_override or self.environment.base_url

    def validate(self) -> None:
        """Raise :class:`ConfigurationError` if this profile is unusable."""
        if not self.name or not self.name.strip():
            raise ConfigurationError("profile name must not be empty")
        if not _MEMORY_ID_RE.match(self.memory_id):
            raise ConfigurationError(
                f"memory_id {self.memory_id!r} must be 6 characters of A-Z or 0-9"
            )
        if not self.base_url.startswith(("http://", "https://")):
            raise ConfigurationError(f"base_url {self.base_url!r} must be an http(s) URL")
        if self.base_url.endswith("/"):
            # URLs are built by string join, so a trailing slash yields "//api/v2".
            raise ConfigurationError(f"base_url {self.base_url!r} must not end with '/'")
        if not self.certificate_pem:
            raise ConfigurationError("certificate_pem is empty")
        if not self.private_key_pem:
            raise ConfigurationError("private_key_pem is empty")
        self._certificate()
        if self.economic_code is not None and not self.economic_code.isdigit():
            raise ConfigurationError(f"economic_code {self.economic_code!r} must be digits")

    def _certificate(self) -> x509.Certificate:
        try:
            return x509.load_pem_x509_certificate(self.certificate_pem)
        except ValueError as exc:
            raise ConfigurationError(
                f"certificate for profile {self.name!r} is not valid PEM"
            ) from exc

    def redacted(self) -> dict[str, Any]:
        """A description safe to hand to a UI or a log. Carries no key material."""
        cert = self._certificate()
        return {
            "name": self.name,
            "memory_id": self.memory_id,
            "environment": str(self.environment),
            "environment_label": self.environment.label,
            "is_production": self.environment.is_production,
            "base_url": self.base_url,
            "economic_code": self.economic_code,
            "certificate": {
                "subject": cert.subject.rfc4514_string(),
                # Hex, because the decimal form of a 20-byte serial is unreadable.
                "serial_number": format(cert.serial_number, "x"),
                "not_before": cert.not_valid_before_utc.isoformat(),
                "not_after": cert.not_valid_after_utc.isoformat(),
            },
        }

    def _to_json(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "memory_id": self.memory_id,
            "environment": str(self.environment),
            "base_url_override": self.base_url_override,
            "certificate_pem": _b64(self.certificate_pem),
            "private_key_pem": _b64(self.private_key_pem),
            "economic_code": self.economic_code,
        }

    @classmethod
    def _from_json(cls, data: dict[str, Any]) -> Profile:
        try:
            return cls(
                name=data["name"],
                memory_id=data["memory_id"],
                environment=Environment.parse(data["environment"]),
                certificate_pem=_unb64(data["certificate_pem"], "certificate_pem"),
                private_key_pem=_unb64(data["private_key_pem"], "private_key_pem"),
                economic_code=data.get("economic_code"),
                base_url_override=data.get("base_url_override"),
            )
        except KeyError as exc:
            raise ConfigurationError(f"stored profile is missing field {exc.args[0]!r}") from exc


class ProfileStore:
    """Profiles in a single AES-GCM encrypted file, unlocked by a passphrase.

    The whole file is one ciphertext, so every write re-derives a key under a
    fresh salt and encrypts under a fresh nonce. That costs one Scrypt run per
    operation and buys nonce reuse being impossible by construction.
    """

    def __init__(self, path: Path, master_passphrase: str) -> None:
        if not master_passphrase:
            raise ConfigurationError("master passphrase must not be empty")
        self.path = Path(path)
        self._passphrase = master_passphrase.encode("utf-8")

    def __repr__(self) -> str:
        """Path only. The passphrase lives in ``__dict__``, so the default
        ``object.__repr__`` is safe but anything that dumps attributes is not;
        this at least keeps the common ``repr()``/``f"{store}"`` paths clean."""
        return f"{type(self).__name__}(path={str(self.path)!r})"

    def list_names(self) -> list[str]:
        """Profile names, sorted."""
        return sorted(self._read_all())

    def save(self, profile: Profile) -> None:
        """Validate and store a profile, replacing any of the same name."""
        profile.validate()
        profiles = self._read_all()
        profiles[profile.name] = profile
        self._write_all(profiles)

    def load(self, name: str) -> Profile:
        """Fetch a profile by name."""
        profiles = self._read_all()
        try:
            return profiles[name]
        except KeyError:
            raise ConfigurationError(f"no profile named {name!r} in {self.path}") from None

    def delete(self, name: str) -> None:
        """Remove a profile by name."""
        profiles = self._read_all()
        if name not in profiles:
            raise ConfigurationError(f"no profile named {name!r} in {self.path}")
        del profiles[name]
        self._write_all(profiles)

    # -- encryption -------------------------------------------------------

    def _derive_key(self, salt: bytes, n: int, r: int, p: int) -> bytes:
        kdf = Scrypt(salt=salt, length=_KEY_LENGTH, n=n, r=r, p=p)
        return kdf.derive(self._passphrase)

    def _read_all(self) -> dict[str, Profile]:
        if not self.path.exists():
            return {}
        try:
            envelope = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ConfigurationError(f"profile store {self.path} is unreadable: {exc}") from exc
        if not isinstance(envelope, dict):
            raise ConfigurationError(f"profile store {self.path} is not a JSON object")

        version = envelope.get("version")
        if version != _FILE_VERSION:
            raise ConfigurationError(
                f"profile store {self.path} has version {version!r}, expected {_FILE_VERSION}"
            )
        kdf_params = envelope.get("kdf") or {}
        try:
            n, r, p = int(kdf_params["n"]), int(kdf_params["r"]), int(kdf_params["p"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ConfigurationError(f"profile store {self.path} has malformed kdf params") from exc

        salt = _unb64(envelope.get("salt", ""), "salt")
        nonce = _unb64(envelope.get("nonce", ""), "nonce")
        ciphertext = _unb64(envelope.get("ciphertext", ""), "ciphertext")

        key = self._derive_key(salt, n, r, p)
        try:
            plaintext = AESGCM(key).decrypt(nonce, ciphertext, None)
        except (InvalidTag, ValueError) as exc:
            # The tag cannot distinguish a wrong passphrase from a tampered
            # file, so report the likely cause without promising either.
            raise ConfigurationError(
                f"could not decrypt {self.path}: wrong master passphrase or corrupted file"
            ) from exc

        payload = json.loads(plaintext.decode("utf-8"))
        return {
            name: Profile._from_json(data) for name, data in payload.get("profiles", {}).items()
        }

    def _write_all(self, profiles: dict[str, Profile]) -> None:
        plaintext = json.dumps(
            {"profiles": {name: p._to_json() for name, p in profiles.items()}},
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")

        salt = secrets.token_bytes(_SALT_LENGTH)
        nonce = secrets.token_bytes(_NONCE_LENGTH)
        key = self._derive_key(salt, _SCRYPT_N, _SCRYPT_R, _SCRYPT_P)
        ciphertext = AESGCM(key).encrypt(nonce, plaintext, None)

        envelope = {
            "version": _FILE_VERSION,
            "kdf": {"name": "scrypt", "n": _SCRYPT_N, "r": _SCRYPT_R, "p": _SCRYPT_P,
                    "length": _KEY_LENGTH},
            "salt": _b64(salt),
            "nonce": _b64(nonce),
            "ciphertext": _b64(ciphertext),
        }
        self._atomic_write(json.dumps(envelope, indent=2).encode("utf-8"))

    def _atomic_write(self, data: bytes) -> None:
        """Write via a temp file in the same directory, then rename.

        mkstemp creates at 0o600 and os.replace keeps the source's mode, so the
        target is never briefly world-readable — which a plain open() would be.
        """
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(dir=self.path.parent, prefix=f".{self.path.name}.")
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_name, self.path)
        except BaseException:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)
            raise
