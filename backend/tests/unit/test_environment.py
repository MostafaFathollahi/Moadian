"""The sandbox/operational split, and the binding that keeps a memory id with it.

A شناسه یکتای حافظه مالیاتی is issued per environment and is not portable, so the
thing worth testing is not just that two URLs are correct — it is that an
environment and a memory id cannot drift apart.
"""

from __future__ import annotations

import pytest

from moadian.config import Environment, Profile, ProfileStore, Settings
from moadian.errors import ConfigurationError

PASSPHRASE = "correct horse battery staple"


# ----------------------------------------------------------------- the two URLs


def test_the_two_environments_are_the_documented_hosts() -> None:
    assert Environment.SANDBOX.host == "sandboxrc.tax.gov.ir"
    assert Environment.PRODUCTION.host == "tp.tax.gov.ir"
    assert Environment.SANDBOX.base_url == "https://sandboxrc.tax.gov.ir/requestsmanager"
    assert Environment.PRODUCTION.base_url == "https://tp.tax.gov.ir/requestsmanager"


def test_base_urls_have_no_trailing_slash() -> None:
    """Paths are appended by string join; a trailing slash would yield '//api/v2'."""
    for env in Environment:
        assert not env.base_url.endswith("/")


def test_is_production_distinguishes_real_filings() -> None:
    assert Environment.PRODUCTION.is_production is True
    assert Environment.SANDBOX.is_production is False


# -------------------------------------------------------------------- parsing


@pytest.mark.parametrize(
    "spelling,expected",
    [
        ("sandbox", Environment.SANDBOX),
        ("sandboxrc", Environment.SANDBOX),
        ("SANDBOX", Environment.SANDBOX),
        ("  sandbox  ", Environment.SANDBOX),
        ("production", Environment.PRODUCTION),
        ("prod", Environment.PRODUCTION),
        ("operational", Environment.PRODUCTION),  # the term the Persian docs use
        ("tp", Environment.PRODUCTION),  # the subdomain, as copied from a URL
        (Environment.PRODUCTION, Environment.PRODUCTION),
    ],
)
def test_parse_accepts_the_names_people_actually_use(
    spelling: str | Environment, expected: Environment
) -> None:
    assert Environment.parse(spelling) is expected


@pytest.mark.parametrize("bad", ["staging", "test", "dev", "", "tp.tax.gov.ir", "sandbox2"])
def test_parse_rejects_anything_implying_a_third_environment(bad: str) -> None:
    """Silently resolving these would hide a misconfiguration instead of surfacing it."""
    with pytest.raises(ConfigurationError) as excinfo:
        Environment.parse(bad)
    assert "unknown environment" in str(excinfo.value)


# --------------------------------------------------- the binding that matters


def test_profile_derives_its_url_from_its_environment(credential_pems) -> None:
    cert_pem, key_pem = credential_pems
    profile = Profile(
        name="prod",
        memory_id="A1B2C3",
        environment=Environment.PRODUCTION,
        certificate_file="dev.crt",
        private_key_file="dev.pem",
    )
    assert profile.base_url == "https://tp.tax.gov.ir/requestsmanager"

    # Switching the environment moves the URL with it — they cannot disagree.
    profile.environment = Environment.SANDBOX
    assert profile.base_url == "https://sandboxrc.tax.gov.ir/requestsmanager"


def test_profile_accepts_a_spelling_for_its_environment(credential_pems) -> None:
    profile = Profile(
        name="p",
        memory_id="A1B2C3",
        environment="tp",  # type: ignore[arg-type]
        certificate_file="dev.crt",
        private_key_file="dev.pem",
    )
    assert profile.environment is Environment.PRODUCTION


def test_override_is_honoured_for_pointing_at_a_mock(credential_pems) -> None:
    profile = Profile(
        name="mock",
        memory_id="A1B2C3",
        environment=Environment.SANDBOX,
        certificate_file="dev.crt",
        private_key_file="dev.pem",
        base_url_override="http://testserver/requestsmanager",
    )
    assert profile.base_url == "http://testserver/requestsmanager"


def test_environment_survives_a_store_round_trip(tmp_path, credential_pems) -> None:
    """The memory id and its environment must come back off disk together."""
    cert_pem, key_pem = credential_pems
    store = ProfileStore(tmp_path / "profiles.json", PASSPHRASE)
    store.save(
        Profile(
            name="live-filing",
            memory_id="B9Z8Y7",
            environment=Environment.PRODUCTION,
            certificate_file="dev.crt",
            private_key_file="dev.pem",
        )
    )

    loaded = store.load("live-filing")
    assert loaded.environment is Environment.PRODUCTION
    assert loaded.memory_id == "B9Z8Y7"
    assert loaded.base_url == "https://tp.tax.gov.ir/requestsmanager"


def test_two_profiles_keep_separate_memory_ids(tmp_path, credential_pems) -> None:
    """The whole point: one memory id per environment, never crossed."""
    cert_pem, key_pem = credential_pems
    store = ProfileStore(tmp_path / "profiles.json", PASSPHRASE)
    for name, env, memory in [
        ("آزمایشی", Environment.SANDBOX, "A11216"),
        ("عملیاتی", Environment.PRODUCTION, "B22327"),
    ]:
        store.save(
            Profile(
                name=name,
                memory_id=memory,
                environment=env,
                certificate_file="dev.crt",
                private_key_file="dev.pem",
            )
        )

    sandbox, production = store.load("آزمایشی"), store.load("عملیاتی")
    assert sandbox.memory_id != production.memory_id
    assert sandbox.base_url != production.base_url
    assert "sandboxrc" in sandbox.base_url
    assert "tp.tax.gov.ir" in production.base_url


def test_redacted_tells_a_ui_which_environment_it_is(credential_pems) -> None:
    profile = Profile(
        name="p",
        memory_id="A1B2C3",
        environment=Environment.PRODUCTION,
        certificate_file="dev.crt",
        private_key_file="dev.pem",
    )
    view = profile.redacted()
    assert view["environment"] == "production"
    assert view["is_production"] is True
    assert view["environment_label"] == "عملیاتی"


# ------------------------------------------------------------------ settings


def test_settings_base_url_accepts_any_valid_spelling() -> None:
    settings = Settings()
    assert settings.base_url("tp") == settings.base_url(Environment.PRODUCTION)
    assert settings.base_url("operational") == "https://tp.tax.gov.ir/requestsmanager"
    assert settings.base_url("sandboxrc") == "https://sandboxrc.tax.gov.ir/requestsmanager"


def test_settings_override_wins_so_a_deployment_can_use_a_proxy() -> None:
    settings = Settings(production_base_url="https://proxy.internal/rm")
    assert settings.base_url(Environment.PRODUCTION) == "https://proxy.internal/rm"
    assert settings.base_url(Environment.SANDBOX) == "https://sandboxrc.tax.gov.ir/requestsmanager"
