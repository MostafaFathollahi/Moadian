"""Byte-exact conformance against the token published in RC_TICS.IS_v1.6, p.13.

The technical guide prints a complete worked example: the payload, the signing
time, and the resulting compact JWS, produced with the keypair shipped in the
official .NET SDK's ``TaxCollectData.Sample``. RSASSA-PKCS1-v1_5 is
deterministic, so signing the same bytes with the same key must reproduce that
token character for character — including the protected header, whose exact
key set and order are what this pins.

This is the canary. If it fails, :class:`Pkcs8Signatory` no longer produces the
bytes the organization signs, and everything else in the suite is testing our
own assumptions back at us.
"""

from __future__ import annotations

import base64
import json
import re
from datetime import UTC, datetime
from pathlib import Path

import pytest
from conftest import sample_keypair_dir
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.x509 import load_pem_x509_certificate

from moadian.crypto import SIGT_FORMAT, Pkcs8Signatory, SigningCredentials, b64url, b64url_decode

#: Extracted Persian text of the guide. RTL extraction mangles prose but leaves
#: base64 and JSON intact, which is all this needs.
GUIDE = Path(__file__).parent / "RC_TICS_extracted.txt"

#: The token is wrapped across PDF lines and the first one is the auth example.
_TOKEN_START = "eyJjcml0IjpbInNpZ1Qi"

#: The Persian prose that follows the token ("تکه کد زیر …").
_TOKEN_STOP = "تکه"

#: Locating the keypair lives in conftest so exactly one place knows where it is.
#: It is the committed copy under sample_keypair/, NOT ``SDK/`` — see the note there.
sample_dir = sample_keypair_dir


def _documented_token() -> str:
    """Pull the example token out of the extracted guide text."""
    if not GUIDE.is_file():
        pytest.skip(f"{GUIDE} is missing; extract the guide to run the conformance check")
    text = GUIDE.read_text(encoding="utf-8")
    try:
        start = text.index(_TOKEN_START)
        chunk = text[start : start + 4000]
        stop = chunk.index(_TOKEN_STOP)
    except ValueError:  # pragma: no cover - only if the extraction changes
        pytest.skip("the documented token was not found in the extracted guide text")
    # Line wrapping inserts newlines and stray spaces; keep only JWS-legal chars.
    return re.sub(r"[^A-Za-z0-9_\-.]", "", chunk[:stop])


@pytest.fixture(scope="module")
def documented_token() -> str:
    return _documented_token()


@pytest.fixture(scope="module")
def documented_parts(documented_token: str) -> tuple[str, str, str]:
    header_b64, payload_b64, signature_b64 = documented_token.split(".")
    return header_b64, payload_b64, signature_b64


@pytest.fixture(scope="module")
def documented_header(documented_parts: tuple[str, str, str]) -> dict:
    return json.loads(b64url_decode(documented_parts[0]))


@pytest.fixture(scope="module")
def sample_credentials() -> SigningCredentials:
    """The keypair the guide signed its example with."""
    sample = sample_dir()
    return SigningCredentials.from_files(sample / "cert1.crt", sample / "privatekey1.pem")


# --------------------------------------------------------- the document alone


def test_documented_header_is_exactly_the_four_pinned_keys(documented_header: dict) -> None:
    """Key set *and* order — both are inside the signed bytes.

    The .NET SDK emits ``typ`` and ``cty`` as well; the document does not, and
    this is the evidence for WIRE_FORMAT.md preferring the document.
    """
    assert list(documented_header) == ["crit", "sigT", "x5c", "alg"]
    assert documented_header["alg"] == "RS256"
    assert documented_header["crit"] == ["sigT"]
    assert datetime.strptime(documented_header["sigT"], SIGT_FORMAT)


def test_documented_x5c_is_standard_base64_not_base64url(documented_header: dict) -> None:
    """``x5c`` is the one field in a JOSE header that is *not* base64url."""
    (entry,) = documented_header["x5c"]
    der = base64.b64decode(entry, validate=True)
    assert der.startswith(b"\x30\x82"), "x5c does not decode to a DER SEQUENCE"
    # The distinction is only visible on the alphabet and the padding, so state
    # it directly: the documented entry is not what base64url would produce.
    assert entry != b64url(der)
    assert base64.b64encode(der).decode("ascii") == entry


def test_documented_payload_is_the_auth_challenge(documented_parts: tuple[str, str, str]) -> None:
    """The payload is `{"nonce", "clientId"}` — pretty-printed, with CRLF.

    Recorded because it is the proof that payload formatting is unconstrained:
    only the header bytes have to be reproducible.
    """
    payload = b64url_decode(documented_parts[1])
    assert b"\r\n" in payload
    assert set(json.loads(payload)) == {"nonce", "clientId"}


# ------------------------------------------------- the document plus our code


def test_x5c_carries_the_sdk_sample_certificate(
    documented_header: dict, sample_credentials: SigningCredentials
) -> None:
    embedded = base64.b64decode(documented_header["x5c"][0], validate=True)
    assert embedded == sample_credentials.der


def test_documented_signature_verifies_against_the_sample_certificate(
    documented_parts: tuple[str, str, str], sample_credentials: SigningCredentials
) -> None:
    """Sanity check on the extraction before we compare our own output to it."""
    header_b64, payload_b64, signature_b64 = documented_parts
    sample_credentials.certificate.public_key().verify(
        b64url_decode(signature_b64),
        f"{header_b64}.{payload_b64}".encode("ascii"),
        padding.PKCS1v15(),
        hashes.SHA256(),
    )


def test_pkcs8_signatory_reproduces_the_documented_token_byte_for_byte(
    documented_token: str,
    documented_parts: tuple[str, str, str],
    documented_header: dict,
    sample_credentials: SigningCredentials,
) -> None:
    """The whole point: our signatory, the documented sigT, the documented payload.

    The clock is injected because ``sigT`` is inside the signed header, so the
    token is only reproducible at the instant the guide recorded.
    """
    sig_time = datetime.strptime(documented_header["sigT"], SIGT_FORMAT).replace(tzinfo=UTC)
    signatory = Pkcs8Signatory(sample_credentials, clock=lambda: sig_time)

    payload = b64url_decode(documented_parts[1])
    token = signatory.sign(payload)

    header_b64 = token.split(".")[0]
    assert header_b64 == documented_parts[0], (
        "protected header bytes drifted; ours decodes to "
        f"{b64url_decode(header_b64).decode('utf-8')}"
    )
    assert token == documented_token


def test_certificate_matches_its_private_key(sample_credentials: SigningCredentials) -> None:
    """``assert_usable`` at the documented signing time, not today — cert1.crt expired."""
    sample_credentials.assert_usable(at=datetime(2024, 3, 6, 13, 5, 50, tzinfo=UTC))


def test_x5c_round_trips_through_our_encoder(sample_credentials: SigningCredentials) -> None:
    """Regression guard for the base64/base64url distinction in our own code."""
    standard = base64.b64encode(sample_credentials.der).decode("ascii")
    assert standard != b64url(sample_credentials.der)
    assert (
        load_pem_x509_certificate(
            b"-----BEGIN CERTIFICATE-----\n"
            + standard.encode("ascii")
            + b"\n-----END CERTIFICATE-----\n"
        ).public_bytes(serialization.Encoding.DER)
        == sample_credentials.der
    )
