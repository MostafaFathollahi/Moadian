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
