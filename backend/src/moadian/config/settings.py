"""Process-wide settings, overridable from the environment with a MOADIAN_ prefix."""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

from moadian.config.environment import Environment
from moadian.config.keyring import KeyRing

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

    #: Where signing material lives, placed by an operator out of band. Private
    #: keys are read from here and never accepted over HTTP — see
    #: moadian.config.keyring for why. Override with MOADIAN_KEY_DIR.
    key_dir: Path = Path("instance/keys")

    def base_url(self, environment: str | Environment = Environment.SANDBOX) -> str:
        """The base URL for an environment.

        Accepts any spelling :meth:`Environment.parse` understands (``tp``,
        ``operational``, ``prod``…). The settings fields above act as overrides,
        which is what makes ``MOADIAN_SANDBOX_BASE_URL`` useful for pointing a
        whole deployment at a proxy or a local mock.
        """
        env = Environment.parse(environment)
        return self.production_base_url if env.is_production else self.sandbox_base_url

    @property
    def keyring(self) -> KeyRing:
        """The server-side key directory this deployment reads signing material from."""
        return KeyRing(self.key_dir)

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
