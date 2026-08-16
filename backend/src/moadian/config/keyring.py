"""The server-side directory that holds signing material.

**Private keys never travel over HTTP.** An operator places the ``.pem`` and
``.crt`` in this directory out of band — ``scp``, a config-management tool, a
mounted secret — and a profile refers to them *by filename only*. Nothing in the
API accepts, returns, logs or echoes key bytes, so there is no request body, no
proxy buffer and no browser tab that has ever held the signing credential.

The trade-off is deliberate and worth naming: the key now rests on the
filesystem rather than inside the passphrase-encrypted profile store. It is
therefore protected by file permissions, which this module checks, and
optionally by the key's own PKCS#8 encryption via
:data:`KEY_PASSPHRASE_ENV`. Set that and the key is encrypted at rest *and*
never transits the application — strictly better than the upload it replaces.
"""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from pathlib import Path

from moadian.errors import ConfigurationError

__all__ = ["KeyRing", "KeyFile", "KEY_PASSPHRASE_ENV"]

#: Optional passphrase for an encrypted PKCS#8 private key. Read from the
#: environment, never from a request, and never stored.
KEY_PASSPHRASE_ENV = "MOADIAN_KEY_PASSPHRASE"

#: Extensions treated as certificates and keys when listing the directory.
CERT_SUFFIXES = frozenset({".crt", ".cer", ".pem"})
KEY_SUFFIXES = frozenset({".pem", ".key"})


@dataclass(frozen=True)
class KeyFile:
    """One file in the key directory, described without reading its contents."""

    name: str
    size: int
    mode: str
    #: True when group or other can read it — worth surfacing for a private key.
    world_readable: bool

    def as_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "size": self.size,
            "mode": self.mode,
            "worldReadable": self.world_readable,
        }


class KeyRing:
    """Resolves profile filenames to paths inside one directory."""

    def __init__(self, directory: Path) -> None:
        self.directory = Path(directory)

    def ensure(self) -> Path:
        self.directory.mkdir(parents=True, exist_ok=True)
        return self.directory

    def resolve(self, filename: str) -> Path:
        """Map a bare filename to a path inside the key directory.

        Rejects anything that is not a plain filename. A profile is operator
        input that arrives over HTTP, so ``../../etc/shadow`` or an absolute
        path must not become a file read — the containment check below is the
        only thing standing between the API and arbitrary local files.
        """
        if not filename or filename != Path(filename).name:
            raise ConfigurationError(
                f"{filename!r} must be a bare filename inside the key directory, "
                "not a path"
            )
        if filename.startswith("."):
            raise ConfigurationError(f"{filename!r} must not be a dotfile")

        base = self.directory.resolve()
        candidate = (base / filename).resolve()
        # Belt to the braces above: resolve() collapses any symlink that might
        # point outside the directory.
        if candidate.parent != base:
            raise ConfigurationError(f"{filename!r} resolves outside the key directory")
        if not candidate.is_file():
            raise ConfigurationError(
                f"{filename!r} is not present in the key directory ({base}). "
                "Place it there out of band; it is never uploaded."
            )
        return candidate

    def describe(self, filename: str) -> KeyFile:
        path = self.resolve(filename)
        info = path.stat()
        mode = stat.S_IMODE(info.st_mode)
        return KeyFile(
            name=filename,
            size=info.st_size,
            mode=format(mode, "04o"),
            world_readable=bool(mode & (stat.S_IRGRP | stat.S_IROTH)),
        )

    def list_files(self) -> dict[str, list[dict[str, object]]]:
        """Names only, split by kind, so an admin UI can offer a picker.

        Contents are never read here — listing a directory must not be a way to
        exfiltrate a key one byte at a time.
        """
        if not self.directory.is_dir():
            return {"certificates": [], "keys": []}
        certificates: list[dict[str, object]] = []
        keys: list[dict[str, object]] = []
        for entry in sorted(self.directory.iterdir()):
            if not entry.is_file() or entry.name.startswith("."):
                continue
            suffix = entry.suffix.lower()
            described = self.describe(entry.name).as_dict()
            if suffix in CERT_SUFFIXES:
                certificates.append(described)
            if suffix in KEY_SUFFIXES:
                keys.append(described)
        return {"certificates": certificates, "keys": keys}

    @staticmethod
    def passphrase() -> bytes | None:
        """The PKCS#8 passphrase, if the key is encrypted at rest."""
        value = os.environ.get(KEY_PASSPHRASE_ENV)
        return value.encode() if value else None
