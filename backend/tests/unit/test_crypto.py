"""Conformance tests for the signing and encryption layer.

``test_official_vector_reproduced_byte_for_byte`` is the load-bearing one: it
re-derives the token published in RC_TICS.IS_v1.6 p.13 from the spec text, so a
drift in the protected header shows up immediately.
"""

from __future__ import annotations

import base64
import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from conftest import sample_keypair_dir
from cryptography import x509
from cryptography.exceptions import InvalidSignature, InvalidTag
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.x509.oid import NameOID

from moadian.crypto import (
    JweEncryptor,
    Pkcs8Signatory,
    ServerKey,
    Signatory,
    SigningCredentials,
    b64url,
    b64url_decode,
    canonical_json,
)
from moadian.errors import CertificateError, CryptographyError

VECTORS = Path(__file__).resolve().parents[1] / "vectors"
SPEC_TEXT = VECTORS / "RC_TICS_extracted.txt"

# Resolved, not hardcoded: this used to be an absolute path containing one
# developer's home directory, which hard-errored on every other machine.
# conftest owns the lookup so there is one place that knows where the keypair is.
SAMPLE = sample_keypair_dir()


# --------------------------------------------------------------- throwaway keys


def _self_signed(
    key: rsa.RSAPrivateKey,
    *,
    national_id: str = "14003778990",
    not_before: datetime | None = None,
    not_after: datetime | None = None,
    public_key: rsa.RSAPublicKey | None = None,
) -> x509.Certificate:
    """Build a throwaway signing certificate in-process (see tools/gen_dev_cert.py)."""
    now = datetime.now(UTC)
    subject = x509.Name(
        [
            x509.NameAttribute(NameOID.COMMON_NAME, "Moadian Test"),
            x509.NameAttribute(NameOID.COUNTRY_NAME, "IR"),
            x509.NameAttribute(NameOID.SERIAL_NUMBER, national_id),
        ]
    )
    return (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(public_key or key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(not_before or now - timedelta(days=1))
        .not_valid_after(not_after or now + timedelta(days=365))
        .sign(key, hashes.SHA256())
    )


def _pem_pair(cert: x509.Certificate, key: rsa.RSAPrivateKey) -> tuple[bytes, bytes]:
    return (
        cert.public_bytes(serialization.Encoding.PEM),
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ),
    )


@pytest.fixture(scope="module")
def dev_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture(scope="module")
def other_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture(scope="module")
def credentials(dev_key: rsa.RSAPrivateKey) -> SigningCredentials:
    cert_pem, key_pem = _pem_pair(_self_signed(dev_key), dev_key)
    return SigningCredentials.from_pem(cert_pem, key_pem)


# ------------------------------------------------------------- canonical_json


def test_canonical_json_drops_none_from_dicts_recursively():
    payload = canonical_json(
        {"header": {"taxid": "A1", "irtaxid": None, "nested": {"scln": None, "keep": 0}}}
    )
    assert json.loads(payload) == {"header": {"taxid": "A1", "nested": {"keep": 0}}}
    assert b"irtaxid" not in payload
    assert b"scln" not in payload


def test_canonical_json_keeps_none_inside_lists():
    # Rows are positional; dropping an element would shift every row after it.
    assert canonical_json({"body": [1, None, {"a": None, "b": 2}]}) == b'{"body":[1,null,{"b":2}]}'


def test_canonical_json_keeps_persian_unescaped_and_compact():
    payload = canonical_json({"sstt": "سرسیلندر قطعات صنعت فولاد سازی", "am": 2})
    assert "سرسیلندر".encode() in payload
    assert b"\\u" not in payload
    assert b", " not in payload and b'": ' not in payload
    assert payload.decode("utf-8") == '{"sstt":"سرسیلندر قطعات صنعت فولاد سازی","am":2}'


def test_canonical_json_preserves_falsy_values():
    # 0 / "" / False are meaningful amounts and flags; only None is unset.
    encoded = canonical_json({"tdis": 0, "s": "", "f": False, "n": None})
    assert encoded == b'{"tdis":0,"s":"","f":false}'


# ---------------------------------------------------------------------- keys


def test_national_id_is_the_subject_serialnumber(credentials: SigningCredentials):
    assert credentials.national_id == "14003778990"


def test_national_id_is_none_when_absent(dev_key: rsa.RSAPrivateKey):
    cert = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "no serial")]))
        .issuer_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "no serial")]))
        .public_key(dev_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.now(UTC) - timedelta(days=1))
        .not_valid_after(datetime.now(UTC) + timedelta(days=1))
        .sign(dev_key, hashes.SHA256())
    )
    cert_pem, key_pem = _pem_pair(cert, dev_key)
    assert SigningCredentials.from_pem(cert_pem, key_pem).national_id is None


def test_der_is_the_raw_certificate_encoding(credentials: SigningCredentials):
    assert credentials.der == credentials.certificate.public_bytes(serialization.Encoding.DER)
    assert credentials.der[:1] == b"\x30"  # DER SEQUENCE, no PEM armour


def test_from_files_round_trips(tmp_path: Path, dev_key: rsa.RSAPrivateKey):
    cert_pem, key_pem = _pem_pair(_self_signed(dev_key, national_id="10100302746"), dev_key)
    (tmp_path / "cert.crt").write_bytes(cert_pem)
    (tmp_path / "key.pem").write_bytes(key_pem)

    creds = SigningCredentials.from_files(tmp_path / "cert.crt", tmp_path / "key.pem")
    creds.assert_usable()
    assert creds.national_id == "10100302746"


def test_assert_usable_accepts_a_matched_valid_pair(credentials: SigningCredentials):
    credentials.assert_usable()


def test_assert_usable_rejects_a_mismatched_key_pair(
    dev_key: rsa.RSAPrivateKey, other_key: rsa.RSAPrivateKey
):
    # Certificate carries other_key's public key but is paired with dev_key.
    cert = _self_signed(dev_key, public_key=other_key.public_key())
    cert_pem, key_pem = _pem_pair(cert, dev_key)
    creds = SigningCredentials.from_pem(cert_pem, key_pem)

    with pytest.raises(CertificateError, match="does not match"):
        creds.assert_usable()


def test_assert_usable_rejects_an_expired_certificate(dev_key: rsa.RSAPrivateKey):
    now = datetime.now(UTC)
    cert = _self_signed(
        dev_key, not_before=now - timedelta(days=30), not_after=now - timedelta(days=1)
    )
    cert_pem, key_pem = _pem_pair(cert, dev_key)

    with pytest.raises(CertificateError, match="expired"):
        SigningCredentials.from_pem(cert_pem, key_pem).assert_usable()


def test_assert_usable_rejects_a_not_yet_valid_certificate(dev_key: rsa.RSAPrivateKey):
    now = datetime.now(UTC)
    cert = _self_signed(
        dev_key, not_before=now + timedelta(days=1), not_after=now + timedelta(days=30)
    )
    cert_pem, key_pem = _pem_pair(cert, dev_key)

    with pytest.raises(CertificateError, match="not valid until"):
        SigningCredentials.from_pem(cert_pem, key_pem).assert_usable()


def test_assert_usable_honours_the_supplied_moment(dev_key: rsa.RSAPrivateKey):
    now = datetime.now(UTC)
    cert = _self_signed(
        dev_key, not_before=now - timedelta(days=30), not_after=now - timedelta(days=1)
    )
    cert_pem, key_pem = _pem_pair(cert, dev_key)
    creds = SigningCredentials.from_pem(cert_pem, key_pem)

    creds.assert_usable(at=now - timedelta(days=10))
    with pytest.raises(CertificateError):
        creds.assert_usable(at=now)


def test_malformed_pem_raises_certificate_error():
    with pytest.raises(CertificateError):
        SigningCredentials.from_pem(b"not a certificate", b"not a key")


# ----------------------------------------------------------------------- JWS


def _frozen(moment: datetime):
    return lambda: moment


def test_pkcs8_signatory_satisfies_the_protocol(credentials: SigningCredentials):
    assert isinstance(Pkcs8Signatory(credentials), Signatory)


def test_jws_round_trip_verifies_against_the_certificate(credentials: SigningCredentials):
    payload = canonical_json({"nonce": "abc-1", "clientId": "A11226", "unset": None})
    token = Pkcs8Signatory(credentials).sign(payload)

    protected_b64, body_b64, signature_b64 = token.split(".")
    assert len(token.split(".")) == 3

    credentials.certificate.public_key().verify(
        b64url_decode(signature_b64),
        f"{protected_b64}.{body_b64}".encode("ascii"),
        padding.PKCS1v15(),
        hashes.SHA256(),
    )
    assert b64url_decode(body_b64) == payload


def test_jws_signature_rejects_a_tampered_payload(credentials: SigningCredentials):
    protected_b64, body_b64, signature_b64 = (
        Pkcs8Signatory(credentials).sign(b'{"nonce":"a"}').split(".")
    )
    with pytest.raises(InvalidSignature):
        credentials.certificate.public_key().verify(
            b64url_decode(signature_b64),
            f"{protected_b64}.{body_b64}x".encode("ascii"),
            padding.PKCS1v15(),
            hashes.SHA256(),
        )


def test_jws_header_has_exactly_four_keys_in_order(credentials: SigningCredentials):
    protected_b64 = Pkcs8Signatory(credentials).sign(b"{}").split(".")[0]
    raw = b64url_decode(protected_b64)

    # object_pairs_hook keeps document order — key order is part of the signed bytes.
    pairs = json.loads(raw, object_pairs_hook=list)
    assert [k for k, _ in pairs] == ["crit", "sigT", "x5c", "alg"]

    header = dict(pairs)
    assert header["crit"] == ["sigT"]
    assert header["alg"] == "RS256"
    assert b", " not in raw and b'": ' not in raw  # compact separators


def test_jws_x5c_is_standard_base64_der(credentials: SigningCredentials):
    header = json.loads(b64url_decode(Pkcs8Signatory(credentials).sign(b"{}").split(".")[0]))
    (x5c,) = header["x5c"]
    assert "-----BEGIN" not in x5c
    assert base64.b64decode(x5c, validate=True) == credentials.der


def test_jws_segments_are_unpadded_base64url(credentials: SigningCredentials):
    # A 5-byte payload forces base64 padding; JOSE forbids it.
    token = Pkcs8Signatory(credentials).sign(b"12345")
    assert "=" not in token
    assert "+" not in token and "/" not in token


def test_sigt_is_utc_seconds_precision(credentials: SigningCredentials):
    moment = datetime(2024, 3, 6, 13, 5, 50, 123456, tzinfo=UTC)
    header = json.loads(
        b64url_decode(Pkcs8Signatory(credentials, clock=_frozen(moment)).sign(b"{}").split(".")[0])
    )
    assert header["sigT"] == "2024-03-06T13:05:50Z"


def test_sigt_is_converted_to_utc_from_a_local_clock(credentials: SigningCredentials):
    from zoneinfo import ZoneInfo

    tehran = datetime(2024, 3, 6, 16, 35, 50, tzinfo=ZoneInfo("Asia/Tehran"))  # UTC+03:30
    header = json.loads(
        b64url_decode(Pkcs8Signatory(credentials, clock=_frozen(tehran)).sign(b"{}").split(".")[0])
    )
    assert header["sigT"] == "2024-03-06T13:05:50Z"


# ------------------------------------------------------------ official vector


def _documented_token() -> str:
    """Pull the p.13 example token out of the extracted spec text.

    The PDF wraps it across lines and trails it with Persian prose; keep only
    JWS-legal characters up to that prose.
    """
    text = SPEC_TEXT.read_text(encoding="utf-8")
    start = text.index("eyJjcml0IjpbInNpZ1Qi")
    chunk = text[start : start + 4000]
    return re.sub(r"[^A-Za-z0-9_\-.]", "", chunk[: chunk.index("تکه")])


def test_official_vector_reproduced_byte_for_byte():
    """RC_TICS.IS_v1.6 p.13 — the conformance oracle for the whole JWS layer.

    RSASSA-PKCS1-v1_5 is deterministic, so a correct implementation signing the
    documented payload at the documented sigT must emit the documented token.
    """
    documented = _documented_token()
    header_b64, payload_b64, _ = documented.split(".")

    # Payload bytes come from the spec itself: pretty-printed JSON with CRLF.
    payload = b64url_decode(payload_b64)
    assert payload == (
        b'{\r\n  "nonce": "91dc28af-4c95-47f0-9913-87f8162b1708-1709717749862",'
        b'\r\n  "clientId": "A11226"\r\n}'
    )
    assert json.loads(b64url_decode(header_b64))["sigT"] == "2024-03-06T13:05:50Z"

    credentials = SigningCredentials.from_files(SAMPLE / "cert1.crt", SAMPLE / "privatekey1.pem")
    signatory = Pkcs8Signatory(
        credentials, clock=_frozen(datetime(2024, 3, 6, 13, 5, 50, tzinfo=UTC))
    )

    assert signatory.sign(payload) == documented


def test_official_vector_certificate_is_the_sdk_sample():
    header = json.loads(b64url_decode(_documented_token().split(".")[0]))
    credentials = SigningCredentials.from_files(SAMPLE / "cert1.crt", SAMPLE / "privatekey1.pem")
    assert base64.b64decode(header["x5c"][0]) == credentials.der
    # The vector's cert expired 2024-03-23; assert_usable must say so.
    with pytest.raises(CertificateError, match="expired"):
        credentials.assert_usable()
    credentials.assert_usable(at=datetime(2024, 3, 6, 13, 5, 50, tzinfo=UTC))


# ----------------------------------------------------------------------- JWE


@pytest.fixture(scope="module")
def server_private_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture(scope="module")
def server_key(server_private_key: rsa.RSAPrivateKey) -> ServerKey:
    spki = server_private_key.public_key().public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return ServerKey(
        id="6a2bcd88-a871-4245-a393-2843eafe6e02",
        key=base64.b64encode(spki).decode("ascii"),
    )


def _decrypt(token: str, private_key: rsa.RSAPrivateKey) -> str:
    """What the organization's server does on receipt."""
    protected, encrypted_key, iv, ciphertext, tag = token.split(".")
    cek = private_key.decrypt(
        b64url_decode(encrypted_key),
        padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=None,
        ),
    )
    return AESGCM(cek).decrypt(
        b64url_decode(iv),
        b64url_decode(ciphertext) + b64url_decode(tag),
        protected.encode("ascii"),
    ).decode("utf-8")


def test_server_key_defaults_match_the_documented_response(server_key: ServerKey):
    assert server_key.algorithm == "RSA"
    assert server_key.purpose == 1


def test_jwe_round_trip(server_key: ServerKey, server_private_key: rsa.RSAPrivateKey):
    plaintext = "eyJ...jws...با متن فارسی"
    token = JweEncryptor(server_key).encrypt(plaintext)

    segments = token.split(".")
    assert len(segments) == 5
    assert "=" not in token

    header = json.loads(b64url_decode(segments[0]))
    assert header == {"alg": "RSA-OAEP-256", "enc": "A256GCM", "kid": server_key.id}
    assert len(b64url_decode(segments[2])) == 12  # 96-bit IV
    assert len(b64url_decode(segments[4])) == 16  # 128-bit GCM tag

    assert _decrypt(token, server_private_key) == plaintext


def test_jwe_cek_is_256_bit_and_fresh_per_call(
    server_key: ServerKey, server_private_key: rsa.RSAPrivateKey
):
    encryptor = JweEncryptor(server_key)
    first, second = encryptor.encrypt("same"), encryptor.encrypt("same")
    assert first != second  # fresh CEK + IV every time

    oaep = padding.OAEP(
        mgf=padding.MGF1(algorithm=hashes.SHA256()), algorithm=hashes.SHA256(), label=None
    )
    cek = server_private_key.decrypt(b64url_decode(first.split(".")[1]), oaep)
    assert len(cek) == 32


def test_jwe_aad_binds_the_protected_header(
    server_key: ServerKey, server_private_key: rsa.RSAPrivateKey
):
    protected, encrypted_key, iv, ciphertext, tag = (
        JweEncryptor(server_key).encrypt("payload").split(".")
    )

    tampered_header = json.loads(b64url_decode(protected))
    tampered_header["kid"] = "attacker-supplied-kid"
    tampered = b64url(json.dumps(tampered_header, separators=(",", ":")).encode("utf-8"))

    with pytest.raises(InvalidTag):
        _decrypt(".".join([tampered, encrypted_key, iv, ciphertext, tag]), server_private_key)


def test_jwe_rejects_a_non_rsa_or_malformed_server_key():
    with pytest.raises(CryptographyError, match="base64"):
        ServerKey(id="k", key="not base64!!").public_key()
    with pytest.raises(CryptographyError, match="SPKI"):
        ServerKey(id="k", key=base64.b64encode(b"not a key").decode()).public_key()
    with pytest.raises(CryptographyError):
        JweEncryptor(ServerKey(id="k", key="****"))
