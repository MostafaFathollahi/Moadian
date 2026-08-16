"""Process-wide settings, overridable from the environment with a MOADIAN_ prefix."""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

from moadian.config.environment import Environment
from moadian.config.keyring import SigningMaterial

__all__ = ["Settings"]


class Settings(BaseSettings):
    """Runtime configuration. Base URLs are pinned in WIRE_FORMAT.md."""

    model_config = SettingsConfigDict(
        env_prefix="MOADIAN_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    sandbox_base_url: str = "https://sandboxrc.tax.gov.ir/requestsmanager"
    production_base_url: str = "https://tp.tax.gov.ir/requestsmanager"

    request_timeout_seconds: float = 60.0

    # Seconds. The API accepts 10-200; the server may grant more than asked, so
    # the response expDate is authoritative (WIRE_FORMAT.md "Authentication").
    nonce_time_to_live: int = 30

    # Holds the profile store, the taxid serial counter, and cached server keys.
    instance_dir: Path = Path("instance")

    #: Unlocks the encrypted profile store. Required — the API cannot read any
    #: fiscal memory without it.
    master_passphrase: str | None = None

    #: Passphrase of an encrypted PKCS#8 private key, if the key is encrypted.
    key_passphrase: str | None = None

    #: Signs this application's own session tokens. NOT the tax-API signing key.
    #: Unset means a random value per process: safe, but every restart signs
    #: everyone out.
    app_secret: str | None = None
    token_ttl_hours: int = 12

    #: Accounts created at first start, as "user:pass:role,user:pass:role".
    seed_users: str = "admin:admin1234:admin"

    #: Signing material. Set from the environment at startup and never from a
    #: request — see moadian.config.keyring for why. The bare pair is the default
    #: for both environments; the per-environment pairs override it, which is what
    #: you want once production has a CA-issued certificate and sandbox does not.
    certificate_path: Path | None = None
    private_key_path: Path | None = None
    sandbox_certificate_path: Path | None = None
    sandbox_private_key_path: Path | None = None
    production_certificate_path: Path | None = None
    production_private_key_path: Path | None = None

    def base_url(self, environment: str | Environment = Environment.SANDBOX) -> str:
        """The base URL for an environment.

        Accepts any spelling :meth:`Environment.parse` understands (``tp``,
        ``operational``, ``prod``…). The settings fields above act as overrides,
        which is what makes ``MOADIAN_SANDBOX_BASE_URL`` useful for pointing a
        whole deployment at a proxy or a local mock.
        """
        env = Environment.parse(environment)
        return self.production_base_url if env.is_production else self.sandbox_base_url

    def signing_material(self, environment: str | Environment) -> SigningMaterial:
        """Which certificate and key this environment signs with.

        Resolution is environment-specific first, then the shared default. A
        profile picks between them only by naming its environment; nothing a
        caller sends can influence which file is read.
        """
        env = Environment.parse(environment)
        if env.is_production:
            certificate = self.production_certificate_path or self.certificate_path
            private_key = self.production_private_key_path or self.private_key_path
        else:
            certificate = self.sandbox_certificate_path or self.certificate_path
            private_key = self.sandbox_private_key_path or self.private_key_path
        return SigningMaterial(
            environment=env,
            certificate_path=Path(certificate) if certificate else None,
            private_key_path=Path(private_key) if private_key else None,
        )

    @property
    def profile_store_path(self) -> Path:
        """Where :class:`~moadian.config.ProfileStore` keeps the encrypted profiles."""
        return self.instance_dir / "profiles.json"

    def serial_counter_path(self, memory_id: str) -> Path:
        """Where :class:`~moadian.pipeline.MonotonicSerialCounter` keeps one memory's serial.

        One file per شناسه یکتای حافظه مالیاتی: the serial is part of that
        memory's tax ids, so two memories must never share a counter.
        """
        return self.instance_dir / f"serial-{memory_id}"
