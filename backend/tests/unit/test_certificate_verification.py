"""`SigningMaterial.verify` — is the private key actually this certificate's key?

The failure this exists to catch is silent everywhere else. A mismatched pair
produces a perfectly well-formed JWS; the tax service rejects the signature, by
which time a serial has been spent on an invoice that will never register. So
the tests below care less about the happy path than about each way it can be
wrong reporting *which* way it is wrong.
"""

from __future__ import annotations

import base64
import datetime as dt
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from moadian.config import Environment, Profile, Settings
from moadian.crypto import load_certificate
from moadian.errors import CertificateError

NATIONAL_ID = "14015095191"


def _certificate(key: rsa.RSAPrivateKey, *, days_from: int = -1, days_to: int = 365):
    now = dt.datetime.now(dt.UTC)
    name = x509.Name(
        [
            x509.NameAttribute(NameOID.COMMON_NAME, "Simorq Human Centered AI [Stamp]"),
            x509.NameAttribute(NameOID.SERIAL_NUMBER, NATIONAL_ID),
        ]
    )
    return (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(0x2F8D2A3B)
        .not_valid_before(now + dt.timedelta(days=days_from))
        .not_valid_after(now + dt.timedelta(days=days_to))
        .sign(key, hashes.SHA256())
    )


def _write_pair(directory: Path, key: rsa.RSAPrivateKey, certificate, *, password=None) -> Settings:
    (directory / "cert.crt").write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    encryption = (
        serialization.BestAvailableEncryption(password)
        if password
        else serialization.NoEncryption()
    )
    (directory / "key.pem").write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=encryption,
        )
    )
    return Settings(
        certificate_path=directory / "cert.crt",
        private_key_path=directory / "key.pem",
    )


@pytest.fixture(scope="module")
def key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture(scope="module")
def other_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


# -- the pair holds --------------------------------------------------------


def test_a_matched_pair_verifies(tmp_path: Path, key: rsa.RSAPrivateKey) -> None:
    settings = _write_pair(tmp_path, key, _certificate(key))
    report = settings.signing_material(Environment.SANDBOX).verify()
    assert report["ok"] is True, report["message"]
    assert report["matches"] is True
    assert "مطابقت دارد" in report["message"]


def test_the_report_carries_the_certificate_identity(
    tmp_path: Path, key: rsa.RSAPrivateKey
) -> None:
    """شناسه ملی is what the organization checks against the memory's permission."""
    settings = _write_pair(tmp_path, key, _certificate(key))
    report = settings.signing_material(Environment.SANDBOX).verify()
    assert report["certificate"]["nationalId"] == NATIONAL_ID
    assert report["certificate"]["keySize"] == 2048


def test_no_key_material_appears_in_the_report(tmp_path: Path, key: rsa.RSAPrivateKey) -> None:
    """The panel renders this. A private byte in it would be a byte in a browser."""
    settings = _write_pair(tmp_path, key, _certificate(key))
    report = settings.signing_material(Environment.SANDBOX).verify()
    rendered = repr(report)
    assert "PRIVATE KEY" not in rendered
    assert "BEGIN" not in rendered
    assert str(key.private_numbers().p) not in rendered


# -- the pair does not hold ------------------------------------------------


def test_a_mismatched_key_is_reported_as_a_mismatch(
    tmp_path: Path, key: rsa.RSAPrivateKey, other_key: rsa.RSAPrivateKey
) -> None:
    """The whole point. Two valid files that are not each other's half."""
    settings = _write_pair(tmp_path, other_key, _certificate(key))
    report = settings.signing_material(Environment.SANDBOX).verify()
    assert report["ok"] is False
    assert report["matches"] is False
    assert "مطابقت ندارد" in report["message"]


def test_an_expired_certificate_is_not_reported_as_a_mismatch(
    tmp_path: Path, key: rsa.RSAPrivateKey
) -> None:
    """Different problem, different fix. Collapsing them tells the operator nothing."""
    settings = _write_pair(tmp_path, key, _certificate(key, days_from=-800, days_to=-1))
    report = settings.signing_material(Environment.SANDBOX).verify()
    assert report["ok"] is False
    assert report["matches"] is True
    assert "منقضی" in report["message"]


def test_an_encrypted_key_without_a_passphrase_names_the_variable(
    tmp_path: Path, key: rsa.RSAPrivateKey
) -> None:
    settings = _write_pair(tmp_path, key, _certificate(key), password=b"secret")
    report = settings.signing_material(Environment.SANDBOX).verify()
    assert report["ok"] is False
    assert "MOADIAN_KEY_PASSPHRASE" in report["message"]


def test_the_certificate_is_still_reported_when_the_key_cannot_be_read(
    tmp_path: Path, key: rsa.RSAPrivateKey
) -> None:
    """A locked key must not hide which certificate is deployed — that is half
    of what an operator opens this panel to find out."""
    settings = _write_pair(tmp_path, key, _certificate(key), password=b"secret")
    report = settings.signing_material(Environment.SANDBOX).verify()
    assert report["certificate"]["nationalId"] == NATIONAL_ID
    assert report["matches"] is None


def test_an_unconfigured_path_names_the_variable_to_set() -> None:
    report = Settings().signing_material(Environment.SANDBOX).verify()
    assert report["ok"] is False
    assert "MOADIAN_CERTIFICATE_PATH" in report["message"]


def test_a_missing_file_is_a_report_and_not_an_exception(tmp_path: Path) -> None:
    """Every failure the panel has to render must come back as a report."""
    settings = Settings(
        certificate_path=tmp_path / "absent.crt",
        private_key_path=tmp_path / "absent.pem",
    )
    report = settings.signing_material(Environment.SANDBOX).verify()
    assert report["ok"] is False
    assert "absent.crt" in report["message"]


# -- certificate encodings -------------------------------------------------


def test_a_bare_base64_certificate_is_accepted(key: rsa.RSAPrivateKey) -> None:
    """مرکز توسعه تجارت الکترونیکی issues the body with no PEM armour.

    Rejecting it would mean telling an operator that their real, correctly
    issued certificate is corrupt.
    """
    der = _certificate(key).public_bytes(serialization.Encoding.DER)
    bare = base64.b64encode(der)
    body = b"\r\n".join(bare[i : i + 64] for i in range(0, len(bare), 64)) + b"\r\n"
    loaded = load_certificate(body)
    assert loaded.public_key().public_numbers() == key.public_key().public_numbers()


def test_pem_and_der_still_load(key: rsa.RSAPrivateKey) -> None:
    certificate = _certificate(key)
    for encoding in (serialization.Encoding.PEM, serialization.Encoding.DER):
        assert load_certificate(certificate.public_bytes(encoding)).serial_number == 0x2F8D2A3B


def test_a_certificate_that_is_neither_is_still_an_error() -> None:
    with pytest.raises(CertificateError):
        load_certificate(b"this is not a certificate, it is a sentence")


# -- one reader, not two ---------------------------------------------------


def test_the_profile_reads_the_same_certificate_the_signing_path_does(
    tmp_path: Path, key: rsa.RSAPrivateKey
) -> None:
    """The dashboard and the signing path must agree about a given file.

    They did not. ``Profile.certificate`` called ``load_pem_x509_certificate``
    directly while the signing path went through the shared reader, so a bare
    base64 certificate produced a تنظیمات panel reporting a matched pair and a
    dashboard reporting "گواهی امضا خوانده نشد" — about the same file, in the
    same process.
    """
    der = _certificate(key).public_bytes(serialization.Encoding.DER)
    bare = base64.b64encode(der)
    (tmp_path / "cert.crt").write_bytes(
        b"\r\n".join(bare[i : i + 64] for i in range(0, len(bare), 64)) + b"\r\n"
    )
    (tmp_path / "key.pem").write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    settings = Settings(
        certificate_path=tmp_path / "cert.crt", private_key_path=tmp_path / "key.pem"
    )
    profile = Profile(name="آزمایشی", memory_id="A11216", environment=Environment.SANDBOX)

    summary = profile.redacted(settings)
    assert "certificate_error" not in summary, summary.get("certificate_error")
    assert summary["certificate"]["national_id"] == NATIONAL_ID
    # And the two readers agree.
    assert settings.signing_material(Environment.SANDBOX).verify()["ok"] is True


def test_an_unreadable_certificate_still_lists_the_profile(tmp_path: Path) -> None:
    """A profile whose certificate has gone bad must stay listable, or the panel
    cannot show the operator what is wrong."""
    (tmp_path / "cert.crt").write_bytes(b"not a certificate at all")
    (tmp_path / "key.pem").write_bytes(b"nor is this")
    settings = Settings(
        certificate_path=tmp_path / "cert.crt", private_key_path=tmp_path / "key.pem"
    )
    summary = Profile(
        name="آزمایشی", memory_id="A11216", environment=Environment.SANDBOX
    ).redacted(settings)
    assert summary["certificate"] is None
    assert "certificate_error" in summary
