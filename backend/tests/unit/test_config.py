"""Tests for settings, encrypted profile storage, and the error catalogue."""

from __future__ import annotations

import base64
import datetime as dt
import json
import stat
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from moadian.config import Environment, Profile, ProfileStore, Settings
from moadian.errors import (
    ConfigurationError,
    CryptographyError,
    MoadianError,
    TaxApiError,
    describe,
)

PASSPHRASE = "correct horse battery staple"


@pytest.fixture(scope="module")
def credentials() -> tuple[bytes, bytes]:
    """A throwaway self-signed cert and its key. Local use only — see WIRE_FORMAT.md."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name(
        [
            x509.NameAttribute(NameOID.COMMON_NAME, "آزمایش مودیان"),
            x509.NameAttribute(NameOID.SERIAL_NUMBER, "1234567890"),
        ]
    )
    now = dt.datetime.now(dt.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(0x1234ABCD)
        .not_valid_before(now - dt.timedelta(days=1))
        .not_valid_after(now + dt.timedelta(days=365))
        .sign(key, hashes.SHA256())
    )
    cert_pem = cert.public_bytes(serialization.Encoding.PEM)
    key_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    return cert_pem, key_pem


@pytest.fixture
def key_dir(tmp_path_factory, credentials: tuple[bytes, bytes]) -> Path:
    """A server-side key directory. Signing material is placed here out of band."""
    cert_pem, key_pem = credentials
    directory = tmp_path_factory.mktemp("keys")
    (directory / "dev.crt").write_bytes(cert_pem)
    (directory / "dev.pem").write_bytes(key_pem)
    (directory / "dev.pem").chmod(0o600)
    return directory


@pytest.fixture
def settings(key_dir: Path) -> Settings:
    """Settings whose signing material points at the temp key directory."""
    return Settings(
        certificate_path=key_dir / "dev.crt",
        private_key_path=key_dir / "dev.pem",
    )


@pytest.fixture
def profile(credentials: tuple[bytes, bytes]) -> Profile:
    return Profile(
        name="sandbox",
        memory_id="A1B2C3",
        environment=Environment.SANDBOX,
        economic_code="14001234567",
    )


# -- Settings --------------------------------------------------------------


def test_settings_defaults_match_wire_format() -> None:
    settings = Settings()
    assert settings.sandbox_base_url == "https://sandboxrc.tax.gov.ir/requestsmanager"
    assert settings.production_base_url == "https://tp.tax.gov.ir/requestsmanager"
    assert settings.request_timeout_seconds == 60.0
    assert settings.nonce_time_to_live == 30
    assert settings.instance_dir == Path("instance")


def test_settings_read_env_with_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MOADIAN_NONCE_TIME_TO_LIVE", "45")
    monkeypatch.setenv("MOADIAN_INSTANCE_DIR", "/var/lib/moadian")
    settings = Settings()
    assert settings.nonce_time_to_live == 45
    assert settings.instance_dir == Path("/var/lib/moadian")


# -- Profile ---------------------------------------------------------------


def test_validate_accepts_a_good_profile(profile: Profile) -> None:
    profile.validate()


@pytest.mark.parametrize(
    "field,value",
    [
        ("name", ""),
        ("memory_id", "a1b2c3"),  # must be uppercase
        ("memory_id", "A1B2C"),  # must be 6 chars
        ("memory_id", "A1B2C3D"),
        ("base_url_override", "sandboxrc.tax.gov.ir"),  # no scheme
        ("base_url_override", "https://sandboxrc.tax.gov.ir/requestsmanager/"),  # trailing slash
                ("economic_code", "14A01234567"),
    ],
)
def test_validate_rejects_bad_fields(profile: Profile, field: str, value: object) -> None:
    setattr(profile, field, value)
    with pytest.raises(ConfigurationError):
        profile.validate()


def test_redacted_omits_key_material(profile: Profile, settings: Settings) -> None:
    view = profile.redacted(settings)
    flat = json.dumps(view, ensure_ascii=False)
    assert "PRIVATE KEY" not in flat
    assert "CERTIFICATE" not in flat
    # Stronger than "does not leak": a Profile holds no key bytes at all, so
    # there is nothing for a serialiser, a log line or a repr to expose.
    assert not hasattr(profile, "private_key_pem")
    assert not hasattr(profile, "certificate_pem")
    assert set(view) >= {
        "name",
        "memory_id",
        "environment",
        "base_url",
        "economic_code",
    }
    assert view["memory_id"] == "A1B2C3"
    assert view["economic_code"] == "14001234567"


def test_repr_and_str_carry_no_key_material(profile: Profile) -> None:
    """A dataclass __repr__ is what `logger.exception` with locals, a debugger
    frame dump, or a stray print() renders. It must not contain the unencrypted
    signing key."""
    for text in (repr(profile), str(profile), f"{profile}", f"{profile!r}"):
        assert "PRIVATE KEY" not in text
        assert "BEGIN" not in text
        assert "PRIVATE KEY" not in text
        assert "certificate_pem" not in text
        assert "private_key_pem" not in text


def test_repr_still_identifies_the_profile(profile: Profile) -> None:
    """Redaction must not make the repr useless for diagnosis."""
    text = repr(profile)
    assert "sandbox" in text
    assert "A1B2C3" in text


def test_repr_of_a_container_of_profiles_is_safe(profile: Profile) -> None:
    """The leak path is rarely `repr(profile)` itself — it is a dict or list of
    profiles caught in a traceback."""
    text = repr({"sandbox": profile, "list": [profile]})
    assert b"BEGIN PRIVATE KEY" not in text.encode()
    assert "PRIVATE KEY" not in text


def test_profile_store_repr_hides_the_passphrase(tmp_path: Path) -> None:
    store = ProfileStore(tmp_path / "profiles.json", PASSPHRASE)
    for text in (repr(store), str(store), f"{store}"):
        assert PASSPHRASE not in text
        assert "battery" not in text
        assert "profiles.json" in text


def test_redacted_summarises_the_certificate(profile: Profile, settings: Settings) -> None:
    cert = profile.redacted(settings)["certificate"]
    # national_id is surfaced so the admin panel can show the کد ملی the
    # organization will match against `tins` — a mismatch there is error 4103,
    # and the operator should be able to see it before submitting.
    assert set(cert) == {
        "subject",
        "serial_number",
        "not_before",
        "not_after",
        "national_id",
    }
    assert cert["serial_number"] == "1234abcd"
    assert cert["national_id"] == "1234567890"
    assert "1234567890" in cert["subject"]  # SERIALNUMBER holds the کد ملی
    assert dt.datetime.fromisoformat(cert["not_before"]) < dt.datetime.fromisoformat(
        cert["not_after"]
    )


# -- ProfileStore ----------------------------------------------------------


def test_save_load_round_trip(tmp_path: Path, profile: Profile) -> None:
    store = ProfileStore(tmp_path / "profiles.json", PASSPHRASE)
    store.save(profile)
    assert store.load("sandbox") == profile


def test_list_and_delete(tmp_path: Path, profile: Profile) -> None:
    store = ProfileStore(tmp_path / "profiles.json", PASSPHRASE)
    assert store.list_names() == []

    store.save(profile)
    profile.name = "production"
    profile.environment = Environment.PRODUCTION
    store.save(profile)
    assert store.list_names() == ["production", "sandbox"]

    store.delete("sandbox")
    assert store.list_names() == ["production"]
    with pytest.raises(ConfigurationError):
        store.load("sandbox")
    with pytest.raises(ConfigurationError):
        store.delete("sandbox")


def test_wrong_passphrase_raises_configuration_error(tmp_path: Path, profile: Profile) -> None:
    path = tmp_path / "profiles.json"
    ProfileStore(path, PASSPHRASE).save(profile)

    wrong = ProfileStore(path, "hunter2")
    with pytest.raises(ConfigurationError):
        wrong.load("sandbox")
    with pytest.raises(ConfigurationError):
        wrong.list_names()


def test_empty_passphrase_rejected(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError):
        ProfileStore(tmp_path / "profiles.json", "")


def test_file_leaks_neither_passphrase_nor_pem(tmp_path: Path, profile: Profile) -> None:
    path = tmp_path / "profiles.json"
    ProfileStore(path, PASSPHRASE).save(profile)
    raw = path.read_bytes()

    assert PASSPHRASE.encode() not in raw
    assert b"-----BEGIN" not in raw
    assert b"PRIVATE KEY" not in raw
    assert b"A1B2C3" not in raw  # even the memory id is inside the ciphertext
    assert b"14001234567" not in raw

    envelope = json.loads(raw)
    assert envelope["version"] == 1
    assert envelope["kdf"] == {"name": "scrypt", "n": 2**15, "r": 8, "p": 1, "length": 32}
    assert set(envelope) == {"version", "kdf", "salt", "nonce", "ciphertext"}


def test_file_mode_is_0600(tmp_path: Path, profile: Profile) -> None:
    path = tmp_path / "profiles.json"
    ProfileStore(path, PASSPHRASE).save(profile)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_salt_and_nonce_are_fresh_per_write(tmp_path: Path, profile: Profile) -> None:
    path = tmp_path / "profiles.json"
    store = ProfileStore(path, PASSPHRASE)

    store.save(profile)
    first = json.loads(path.read_bytes())
    store.save(profile)
    second = json.loads(path.read_bytes())

    assert first["salt"] != second["salt"]
    assert first["nonce"] != second["nonce"]
    assert first["ciphertext"] != second["ciphertext"]
    assert store.load("sandbox") == profile


def test_tampered_ciphertext_is_rejected(tmp_path: Path, profile: Profile) -> None:
    path = tmp_path / "profiles.json"
    store = ProfileStore(path, PASSPHRASE)
    store.save(profile)

    envelope = json.loads(path.read_bytes())
    flipped = bytearray(base64.b64decode(envelope["ciphertext"]))
    flipped[0] ^= 0x01
    envelope["ciphertext"] = base64.b64encode(bytes(flipped)).decode()
    path.write_text(json.dumps(envelope))

    with pytest.raises(ConfigurationError):
        store.load("sandbox")


def test_unreadable_store_raises_configuration_error(tmp_path: Path) -> None:
    path = tmp_path / "profiles.json"
    path.write_text("this is not json")
    with pytest.raises(ConfigurationError):
        ProfileStore(path, PASSPHRASE).list_names()


def test_save_rejects_invalid_profile(tmp_path: Path, profile: Profile) -> None:
    profile.memory_id = "nope"
    store = ProfileStore(tmp_path / "profiles.json", PASSPHRASE)
    with pytest.raises(ConfigurationError):
        store.save(profile)
    assert not (tmp_path / "profiles.json").exists()


def test_store_creates_missing_parent_directory(tmp_path: Path, profile: Profile) -> None:
    path = tmp_path / "instance" / "nested" / "profiles.json"
    ProfileStore(path, PASSPHRASE).save(profile)
    assert path.exists()


# -- tools/gen_dev_cert.py -------------------------------------------------


@pytest.fixture(scope="module")
def gen_dev_cert():
    """Import the dev-cert tool by path — `tools/` is not an installed package."""
    import importlib.util

    path = Path(__file__).resolve().parents[2] / "tools" / "gen_dev_cert.py"
    spec = importlib.util.spec_from_file_location("gen_dev_cert", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def permissive_umask():
    """Force a 0o000 umask so a mode-less create really would be world-readable."""
    import os

    previous = os.umask(0)
    try:
        yield
    finally:
        os.umask(previous)


def test_private_key_is_never_world_readable_even_briefly(
    gen_dev_cert, tmp_path: Path, permissive_umask, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The mode must come from the creating syscall, not from a later chmod:
    write_bytes() + chmod() leaves a window in which any local process can read
    the unencrypted PKCS#8 key. Neutralising chmod proves there is no window."""
    import os

    monkeypatch.setattr(os, "chmod", lambda *args, **kwargs: None)
    target = tmp_path / "privatekey.pem"
    gen_dev_cert._write_private(target, b"-----BEGIN PRIVATE KEY-----\n")
    assert stat.S_IMODE(target.stat().st_mode) == 0o600


def test_write_private_tightens_a_preexisting_loose_file(gen_dev_cert, tmp_path: Path) -> None:
    """O_CREAT ignores the mode when the file already exists, so re-running the
    tool over a world-readable leftover must still end up at 0o600."""
    target = tmp_path / "privatekey.pem"
    target.write_bytes(b"old")
    target.chmod(0o666)
    gen_dev_cert._write_private(target, b"new")
    assert target.read_bytes() == b"new"
    assert stat.S_IMODE(target.stat().st_mode) == 0o600


def test_generate_writes_a_usable_key_at_0600(
    gen_dev_cert, tmp_path: Path, permissive_umask
) -> None:
    key_path, cert_path, pub_path = gen_dev_cert.generate(
        out_dir=tmp_path / "dev-certs",
        national_id="14003778990",
        common_name="Moadian Dev",
        org="Test",
        days=1,
    )
    assert stat.S_IMODE(key_path.stat().st_mode) == 0o600

    key = serialization.load_pem_private_key(key_path.read_bytes(), password=None)
    cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
    assert cert.public_key().public_numbers() == key.public_key().public_numbers()
    # The binding the tax org checks: subject serialNumber == invoice `tins`.
    assert cert.subject.get_attributes_for_oid(NameOID.SERIAL_NUMBER)[0].value == "14003778990"
    assert pub_path.exists()


# -- errors ----------------------------------------------------------------


def test_describe_known_codes() -> None:
    assert describe("4100") == "متد درخواست ارسالی پشتیبانی نمی‌شود."
    assert describe("5199") == "خطای غیر منتظره‌ای در انجام درخواست رخ داد."
    assert describe("04153") == "طول فیلد IV باید 96 بیت باشد."
    assert describe("9999") is None


def test_tax_api_error_exposes_codes() -> None:
    err = TaxApiError(
        "rejected",
        status_code=401,
        errors=[("4100", describe("4100")), ("5199", describe("5199"))],
        request_trace_id="2444eefb",
    )
    assert err.codes == ["4100", "5199"]
    assert err.status_code == 401
    assert err.request_trace_id == "2444eefb"
    assert "4100" in str(err)
    assert isinstance(err, MoadianError)


def test_tax_api_error_defaults() -> None:
    err = TaxApiError("boom")
    assert err.codes == []
    assert err.status_code is None
    assert err.request_trace_id is None
    assert str(err) == "boom"


def test_exception_hierarchy() -> None:
    from moadian.errors import (
        AuthenticationError,
        CertificateError,
        InvalidTaxIdError,
        UnknownResponseError,
    )

    assert issubclass(CertificateError, CryptographyError)
    assert issubclass(CryptographyError, MoadianError)
    assert issubclass(AuthenticationError, TaxApiError)
    assert issubclass(UnknownResponseError, TaxApiError)
    assert issubclass(InvalidTaxIdError, MoadianError)
    assert issubclass(ConfigurationError, MoadianError)
