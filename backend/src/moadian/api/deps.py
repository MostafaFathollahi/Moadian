"""Wiring for the HTTP layer: settings, stores, and the active profile.

**This API can sign and submit invoices in your name.** It holds the decrypted
signing key in memory for the lifetime of a request and talks to the tax service
as you. It is built for a single operator on localhost or behind an authenticated
reverse proxy — there is no user model, no session, and no authorisation beyond
the master passphrase that unlocks the profile store at startup. Do not expose it
to a network you do not control.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Annotated

from fastapi import Depends, HTTPException
from fastapi import Path as PathParam

from moadian.config import Profile, ProfileStore, Settings
from moadian.errors import ConfigurationError
from moadian.rules import RuleEngine
from moadian.store import CatalogueStore, RecordStore

__all__ = [
    "get_settings",
    "get_profile_store",
    "get_record_store",
    "get_rule_engine",
    "resolve_profile",
    "ActiveProfile",
]

#: Unlocks the encrypted profile store. Read once at startup; never stored.
PASSPHRASE_ENV = "MOADIAN_MASTER_PASSPHRASE"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


@lru_cache(maxsize=1)
def get_profile_store() -> ProfileStore:
    settings = get_settings()
    # settings first, so a value in .env works; an exported variable still wins
    # for deployments that never write one.
    passphrase = settings.master_passphrase or os.environ.get(PASSPHRASE_ENV)
    if not passphrase:
        raise HTTPException(
            503,
            f"{PASSPHRASE_ENV} تنظیم نشده است. این مقدار مخزن رمزگذاری‌شده حافظه‌های "
            "مالیاتی را باز می‌کند و بدون آن هیچ حافظه‌ای قابل خواندن نیست. آن را در "
            "فایل .env یا در متغیرهای محیطی سرور تنظیم کنید.",
        )
    return ProfileStore(settings.profile_store_path, passphrase)


@lru_cache(maxsize=1)
def get_record_store() -> RecordStore:
    settings = get_settings()
    return RecordStore(Path(settings.instance_dir) / "records.sqlite")


@lru_cache(maxsize=1)
def get_catalogue_store() -> CatalogueStore:
    """The official code list. Opened lazily: an install that never imports it
    should not pay for the file, and the search endpoints report it as empty."""
    settings = get_settings()
    return CatalogueStore(settings.catalogue_path)


@lru_cache(maxsize=1)
def get_rule_engine() -> RuleEngine:
    return RuleEngine()


def resolve_profile(
    name: Annotated[str, PathParam(description="Profile name")],
    store: Annotated[ProfileStore, Depends(get_profile_store)],
) -> Profile:
    """Load a profile by name, or 404.

    Everything downstream keys off this, so an unknown profile fails here rather
    than producing an invoice signed by whatever happened to be configured.
    """
    try:
        return store.load(name)
    except ConfigurationError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


ActiveProfile = Annotated[Profile, Depends(resolve_profile)]
