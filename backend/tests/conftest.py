"""Fixtures shared across the suite.

Everything here is in-process and offline. The one exception is
:func:`sandbox_base_url`, which only names the sandbox — the tests marked
``live`` are the ones that talk to it.

Modules that define a fixture of the same name shadow these, which is why the
credential fixtures are prefixed ``dev_``: several test modules already build
their own certificate with different subject fields, and a silent override
between the two would be hard to see.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from moadian.crypto import Pkcs8Signatory, SigningCredentials
from moadian.models import Invoice, InvoiceBodyItem, InvoiceHeader
from moadian.taxid import generate_tax_id, invoice_serial_hex

#: شناسه یکتای حافظه مالیاتی — six chars of A-Z0-9, the shape error 4148 enforces.
MEMORY_ID = "A11216"

REPO_ROOT = Path(__file__).resolve().parents[2]

#: The vendor's published sample keypair, committed at tests/vectors/sample_keypair/.
#: Deliberately not sourced from ``SDK/``, which is gitignored — the byte-exact
#: conformance canary used to skip (and the suite report green) wherever SDK/ was
#: absent, i.e. every clone and every CI runner.
SAMPLE_KEYPAIR = Path(__file__).parent / "vectors" / "sample_keypair"


@pytest.fixture(scope="session")
def credential_pems(dev_credentials: SigningCredentials) -> tuple[bytes, bytes]:
    """A throwaway cert/key PEM pair, for tests that build :class:`Profile` objects."""
    from cryptography.hazmat.primitives import serialization

    cert_pem = dev_credentials.certificate.public_bytes(serialization.Encoding.PEM)
    key_pem = dev_credentials.private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    return cert_pem, key_pem


def sample_keypair_dir() -> Path:
    """Locate the sample keypair, preferring the committed copy.

    Raises rather than returning ``None``: a canary that can quietly disappear is
    not a canary, so a missing keypair must turn the suite red.
    """
    candidates = [SAMPLE_KEYPAIR, *sorted((REPO_ROOT / "SDK").glob("*/TaxCollectData.Sample"))]
    for candidate in candidates:
        if (candidate / "cert1.crt").is_file() and (candidate / "privatekey1.pem").is_file():
            return candidate
    raise FileNotFoundError(
        f"the sample keypair is missing from {SAMPLE_KEYPAIR} and no vendored SDK copy was "
        "found. cert1.crt and privatekey1.pem are required for the byte-exact conformance "
        "check; restore them rather than skipping the test."
    )

#: شناسه ملی of the sample taxpayer. Must equal the certificate's subject
#: SERIALNUMBER and the invoice's `tins`, or the organization answers 4103.
NATIONAL_ID = "14003778990"

#: A buyer شناسه ملی, taken from the spec's own worked example.
BUYER_NATIONAL_ID = "10100302746"

#: Persian text in the signed bytes — the canary for `ensure_ascii=False`.
GOODS_DESCRIPTION = "سرسیلندر قطعات صنعت فولاد سازی"


@pytest.fixture(scope="session")
def dev_credentials() -> SigningCredentials:
    """A throwaway self-signed signing pair, generated once per session.

    Equivalent to ``tools/gen_dev_cert.py`` but never touching disk. It is
    useless against the real API — the organization validates the issuing chain
    by OCSP and CRL — and is here to exercise the JWS, the mock server, and the
    rejection path in the live tests.

    Session-scoped because RSA-2048 keygen is the slowest thing in the suite and
    the credentials are immutable.
    """
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name(
        [
            x509.NameAttribute(NameOID.COMMON_NAME, "Moadian Dev"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Moadian Framework Development"),
            x509.NameAttribute(NameOID.COUNTRY_NAME, "IR"),
            # The binding the tax organization checks.
            x509.NameAttribute(NameOID.SERIAL_NUMBER, NATIONAL_ID),
        ]
    )
    now = datetime.now(UTC)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=30))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    return SigningCredentials(certificate=certificate, private_key=key)


@pytest.fixture(scope="session")
def dev_signatory(dev_credentials: SigningCredentials) -> Pkcs8Signatory:
    """A signatory over :func:`dev_credentials`. Stateless, so shared safely."""
    return Pkcs8Signatory(dev_credentials)


@pytest.fixture
def sample_invoice() -> Invoice:
    """A minimal پترن ۱ (فروش) invoice: one line, 9% VAT, cash settlement.

    Money fields are the spec's own p.20 example. Optional fields are left unset
    so the canonical bytes exercise the null-omission rule.
    """
    issued_at = datetime.now(UTC)
    serial = 1
    return Invoice(
        header=InvoiceHeader(
            taxid=generate_tax_id(MEMORY_ID, serial, issued_at),
            indatim=int(issued_at.timestamp() * 1000),
            inty=1,  # صورتحساب نوع اول
            inp=1,  # الگوی ۱ — فروش
            ins=1,  # اصلی
            inno=invoice_serial_hex(serial),
            setm=2,  # نقد
            tins=NATIONAL_ID,
            tinb=BUYER_NATIONAL_ID,
            tprdis=20000,
            tdis=500,
            tadis=19500,
            tvam=1755,
            todam=0,
            tbill=21255,
        ),
        body=[
            InvoiceBodyItem(
                sstid="2710000138624",
                sstt=GOODS_DESCRIPTION,
                mu="164",
                am=2,
                fee=10000,
                prdis=20000,
                dis=500,
                adis=19500,
                vra=9,
                vam=1755,
                tsstam=21255,
            )
        ],
    )


@pytest.fixture(scope="session")
def sandbox_base_url() -> str:
    """The sandbox base URL, overridable with ``MOADIAN_SANDBOX_BASE_URL``.

    Read straight from the environment rather than through ``Settings`` so a
    stray ``.env`` in the working directory cannot silently point the live tests
    at production.
    """
    return os.environ.get(
        "MOADIAN_SANDBOX_BASE_URL", "https://sandboxrc.tax.gov.ir/requestsmanager"
    )
