"""End-to-end tests against the mock tax API — no network, no CA-issued cert.

The mock verifies what the client sends (JWE decryption, JWS signature, the exact
four-key protected header, single-use nonces), so a green run here means the
bytes on the wire are the bytes RC_TICS.IS_v1.6 describes.
"""

from __future__ import annotations

import base64
import json
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.x509.oid import NameOID
from fastapi import FastAPI

from moadian.crypto import (
    JweEncryptor,
    Pkcs8Signatory,
    ServerKey,
    SigningCredentials,
    b64url,
    canonical_json,
)
from moadian.mock import MockState, create_mock_app
from moadian.models import Invoice, InvoiceBodyItem, InvoiceHeader
from moadian.taxid import generate_tax_id, invoice_serial_hex

BASE = "http://mock"
API = "/api/v2"  # URLs are built by string join — never os.path.join

MEMORY_ID = "A11216"
NATIONAL_ID = "14003778990"
DESCRIPTION = "سرسیلندر قطعات صنعت فولاد سازی"


# ------------------------------------------------------------------ fixtures


def _dev_credentials(national_id: str = NATIONAL_ID) -> SigningCredentials:
    """A throwaway self-signed signing certificate (see tools/gen_dev_cert.py)."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name(
        [
            x509.NameAttribute(NameOID.COMMON_NAME, "Moadian Mock Test"),
            x509.NameAttribute(NameOID.COUNTRY_NAME, "IR"),
            # The binding the organization checks: SERIALNUMBER holds the شناسه ملی.
            x509.NameAttribute(NameOID.SERIAL_NUMBER, national_id),
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
        .sign(key, hashes.SHA256())
    )
    return SigningCredentials(certificate=certificate, private_key=key)


@pytest.fixture
def credentials() -> SigningCredentials:
    return _dev_credentials()


@pytest.fixture
def signatory(credentials: SigningCredentials) -> Pkcs8Signatory:
    return Pkcs8Signatory(credentials)


@pytest.fixture
def app() -> FastAPI:
    return create_mock_app()


@pytest.fixture
def state(app: FastAPI) -> MockState:
    return app.state.mock


@pytest.fixture
async def client(app: FastAPI):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url=BASE) as client:
        yield client


# ------------------------------------------------------------------- helpers


async def _nonce(client: httpx.AsyncClient, time_to_live: int | None = None) -> str:
    params = {} if time_to_live is None else {"timeToLive": time_to_live}
    response = await client.get(API + "/nonce", params=params)
    assert response.status_code == 200
    return response.json()["nonce"]


def _token(signatory: Pkcs8Signatory, nonce: str, client_id: str = MEMORY_ID) -> str:
    return signatory.sign(canonical_json({"nonce": nonce, "clientId": client_id}))


async def _bearer(client: httpx.AsyncClient, signatory: Pkcs8Signatory) -> dict[str, str]:
    """A fresh nonce signed into a bearer token — tokens are single-use."""
    return {"Authorization": "Bearer " + _token(signatory, await _nonce(client))}


def _invoice(serial: int = 1) -> Invoice:
    issued_at = datetime.now(UTC)
    return Invoice(
        header=InvoiceHeader(
            taxid=generate_tax_id(MEMORY_ID, serial, issued_at),
            indatim=int(issued_at.timestamp() * 1000),
            inty=1,
            inp=1,
            ins=1,
            inno=invoice_serial_hex(serial),
            tins=NATIONAL_ID,
            tinb="10100302746",
            tprdis=20000,
            tdis=500,
            tadis=19500,
            tvam=1755,
            todam=0,
            tbill=21255,
            setm=2,
        ),
        body=[
            InvoiceBodyItem(
                sstid="2710000138624",
                sstt=DESCRIPTION,
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


async def _server_key(client: httpx.AsyncClient, signatory: Pkcs8Signatory) -> ServerKey:
    response = await client.get(
        API + "/server-information", headers=await _bearer(client, signatory)
    )
    assert response.status_code == 200, response.text
    entry = response.json()["publicKeys"][0]
    return ServerKey(id=entry["id"], key=entry["key"], algorithm=entry["algorithm"],
                     purpose=entry["purpose"])


async def _submit(
    client: httpx.AsyncClient, signatory: Pkcs8Signatory, jwe: str, uid: str
) -> httpx.Response:
    packet = {"payload": jwe, "header": {"requestTraceId": uid, "fiscalId": MEMORY_ID}}
    return await client.post(
        API + "/invoice", json=[packet], headers=await _bearer(client, signatory)
    )


def _assert_error_envelope(response: httpx.Response) -> list[dict[str, Any]]:
    """The organization's shape — never FastAPI's {"detail": ...}."""
    body = response.json()
    assert "detail" not in body, body
    assert set(body) == {"timestamp", "requestTraceId", "errors"}, body
    assert isinstance(body["timestamp"], int)
    assert body["errors"] and all(set(e) == {"code", "message"} for e in body["errors"])
    return body["errors"]


# --------------------------------------------------------------- the pipeline


async def test_full_pipeline_roundtrip(
    client: httpx.AsyncClient,
    state: MockState,
    signatory: Pkcs8Signatory,
) -> None:
    """Sign, encrypt, submit — and the server recovers the invoice byte for byte."""
    invoice = _invoice()
    payload = canonical_json(invoice.to_wire_dict())
    assert b"irtaxid" not in payload, "unset field leaked into the signed payload"
    assert DESCRIPTION.encode("utf-8") in payload, "Persian text was escaped"

    jws = signatory.sign(payload)
    encryptor = JweEncryptor(await _server_key(client, signatory))
    jwe = encryptor.encrypt(jws)
    assert len(jwe.split(".")) == 5

    uid = "6e1c7696-064c-4d95-b9eb-711ab931a734"
    response = await _submit(client, signatory, jwe, uid)
    assert response.status_code == 200, response.text

    body = response.json()
    assert isinstance(body["timestamp"], int)
    (result,) = body["result"]
    assert result["uid"] == uid
    reference = result["referenceNumber"]
    assert reference

    stored = state.submissions[reference]
    assert stored.invoice_bytes == payload, "server did not recover the signed bytes"
    assert stored.invoice == json.loads(payload)
    assert stored.tax_id == invoice.header.taxid
    assert stored.fiscal_id == MEMORY_ID
    assert stored.invoice["body"][0]["sstt"] == DESCRIPTION

    # The mock only stores what it decrypted and verified, so an inquiry proves
    # the whole chain rather than an echo of the request.
    inquiry = await client.get(
        API + "/inquiry-by-uid",
        params={"uidList": uid, "fiscalId": MEMORY_ID},
        headers=await _bearer(client, signatory),
    )
    assert inquiry.status_code == 200, inquiry.text
    (found,) = inquiry.json()
    assert found["status"] == "SUCCESS"
    assert found["referenceNumber"] == reference
    assert found["data"] == {"error": [], "warning": [], "success": True}

    # `sign` is a JWS by the organization's key, verifiable with the key the
    # client already fetched from /server-information.
    protected_b64, payload_b64, signature_b64 = found["sign"].split(".")
    encryptor.server_key.public_key().verify(
        base64.urlsafe_b64decode(signature_b64 + "=="),
        f"{protected_b64}.{payload_b64}".encode("ascii"),
        padding.PKCS1v15(),
        hashes.SHA256(),
    )


async def test_nonce_honours_and_clamps_time_to_live(client: httpx.AsyncClient) -> None:
    response = await client.get(API + "/nonce", params={"timeToLive": 1})
    body = response.json()
    assert set(body) == {"nonce", "expDate"}
    # uuid4 + "-" + epoch millis
    assert len(body["nonce"].split("-")) == 6
    expires = datetime.strptime(body["expDate"][:26] + "Z", "%Y-%m-%dT%H:%M:%S.%fZ")
    assert expires.replace(tzinfo=UTC) - datetime.now(UTC) >= timedelta(seconds=9)


# ------------------------------------------------------------ auth enforcement


async def test_nonce_cannot_be_replayed(
    client: httpx.AsyncClient, signatory: Pkcs8Signatory
) -> None:
    """Single-use is protocol: the second presentation of a valid token fails."""
    token = _token(signatory, await _nonce(client))
    headers = {"Authorization": "Bearer " + token}

    first = await client.get(API + "/server-information", headers=headers)
    assert first.status_code == 200

    second = await client.get(API + "/server-information", headers=headers)
    assert second.status_code == 401
    assert _assert_error_envelope(second)[0]["code"] == "4102"


async def test_expired_nonce_is_rejected(
    client: httpx.AsyncClient, state: MockState, signatory: Pkcs8Signatory
) -> None:
    nonce = await _nonce(client)
    state.expire_nonce(nonce)

    response = await client.get(
        API + "/server-information",
        headers={"Authorization": "Bearer " + _token(signatory, nonce)},
    )
    assert response.status_code == 401
    assert _assert_error_envelope(response)[0]["code"] == "4102"


async def test_unknown_nonce_is_rejected(
    client: httpx.AsyncClient, signatory: Pkcs8Signatory
) -> None:
    response = await client.get(
        API + "/server-information",
        headers={"Authorization": "Bearer " + _token(signatory, "not-a-nonce")},
    )
    assert response.status_code == 401
    assert _assert_error_envelope(response)[0]["code"] == "4102"


async def test_missing_authorization_returns_the_org_error_envelope(
    client: httpx.AsyncClient,
) -> None:
    response = await client.get(API + "/server-information")
    assert response.status_code == 401
    assert _assert_error_envelope(response)[0]["code"] == "4130"


async def test_sdk_typ_and_cty_headers_are_rejected(
    client: httpx.AsyncClient, credentials: SigningCredentials
) -> None:
    """Drift detection: the .NET SDK's extra headers are not in RC_TICS.IS_v1.6.

    The signature over them is perfectly valid, so only a strict header check
    catches this.
    """
    nonce = await _nonce(client)
    header = {
        "typ": "jose",
        "crit": ["sigT"],
        "sigT": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "x5c": [base64.b64encode(credentials.der).decode("ascii")],
        "cty": "text/plain",
        "alg": "RS256",
    }
    protected = b64url(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    body = b64url(canonical_json({"nonce": nonce, "clientId": MEMORY_ID}))
    signature = credentials.private_key.sign(
        f"{protected}.{body}".encode("ascii"), padding.PKCS1v15(), hashes.SHA256()
    )
    token = f"{protected}.{body}.{b64url(signature)}"

    response = await client.get(
        API + "/server-information", headers={"Authorization": "Bearer " + token}
    )
    assert response.status_code == 401
    errors = _assert_error_envelope(response)
    assert errors[0]["code"] == "4130"
    assert "typ" in errors[0]["message"]


async def test_untrusted_certificate_is_rejected(signatory: Pkcs8Signatory) -> None:
    """`trusted_certs` stands in for the CA/OCSP check we cannot otherwise run."""
    app = create_mock_app(trusted_certs=[_dev_credentials().certificate])
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url=BASE) as client:
        response = await client.get(
            API + "/server-information", headers=await _bearer(client, signatory)
        )
    assert response.status_code == 401
    assert _assert_error_envelope(response)[0]["code"] == "4131"


async def test_forged_signature_is_rejected(
    client: httpx.AsyncClient, credentials: SigningCredentials
) -> None:
    """A token signed by a key that does not match the certificate in its x5c."""
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    impostor = SigningCredentials(certificate=credentials.certificate, private_key=other)
    token = _token(Pkcs8Signatory(impostor), await _nonce(client))

    response = await client.get(
        API + "/server-information", headers={"Authorization": "Bearer " + token}
    )
    assert response.status_code == 401
    assert _assert_error_envelope(response)[0]["code"] == "4133"


# ---------------------------------------------------------------- submission


async def test_tampered_ciphertext_fails_cleanly(
    client: httpx.AsyncClient, state: MockState, signatory: Pkcs8Signatory
) -> None:
    """One flipped ciphertext byte must give a 400 envelope, never a 500."""
    jws = signatory.sign(canonical_json(_invoice().to_wire_dict()))
    jwe = JweEncryptor(await _server_key(client, signatory)).encrypt(jws)

    protected, key, iv, ciphertext, tag = jwe.split(".")
    flipped = ("B" if ciphertext[0] != "B" else "C") + ciphertext[1:]
    tampered = ".".join([protected, key, iv, flipped, tag])

    response = await _submit(
        client, signatory, tampered, "6e1c7696-064c-4d95-b9eb-711ab931a734"
    )
    assert response.status_code == 400, response.text
    assert _assert_error_envelope(response)[0]["code"] == "04150"
    assert not state.submissions


async def test_malformed_jwe_is_rejected(
    client: httpx.AsyncClient, signatory: Pkcs8Signatory
) -> None:
    response = await _submit(
        client, signatory, "not.a.valid.jwe", "6e1c7696-064c-4d95-b9eb-711ab931a734"
    )
    assert response.status_code == 400
    assert _assert_error_envelope(response)[0]["code"] == "04150"


async def test_invoice_signed_with_sdk_headers_is_rejected(
    client: httpx.AsyncClient, credentials: SigningCredentials, signatory: Pkcs8Signatory
) -> None:
    """The same four-key rule applies to the invoice JWS, not just the token."""
    header = {
        "crit": ["sigT"],
        "sigT": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "x5c": [base64.b64encode(credentials.der).decode("ascii")],
        "alg": "RS256",
        "cty": "text/plain",
    }
    protected = b64url(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    body = b64url(canonical_json(_invoice().to_wire_dict()))
    signature = credentials.private_key.sign(
        f"{protected}.{body}".encode("ascii"), padding.PKCS1v15(), hashes.SHA256()
    )
    jwe = JweEncryptor(await _server_key(client, signatory)).encrypt(
        f"{protected}.{body}.{b64url(signature)}"
    )

    response = await _submit(client, signatory, jwe, "6e1c7696-064c-4d95-b9eb-711ab931a734")
    assert response.status_code == 400
    assert _assert_error_envelope(response)[0]["code"] == "04130"


async def test_x5c_must_be_standard_base64(client: httpx.AsyncClient) -> None:
    """base64url in x5c is a real drift risk — every other JOSE field uses it."""
    credentials = _dev_credentials()
    header = {
        "crit": ["sigT"],
        "sigT": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "x5c": [b64url(credentials.der)],
        "alg": "RS256",
    }
    protected = b64url(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    body = b64url(canonical_json({"nonce": await _nonce(client), "clientId": MEMORY_ID}))
    signature = credentials.private_key.sign(
        f"{protected}.{body}".encode("ascii"), padding.PKCS1v15(), hashes.SHA256()
    )

    response = await client.get(
        API + "/server-information",
        headers={"Authorization": f"Bearer {protected}.{body}.{b64url(signature)}"},
    )
    assert response.status_code == 401
    assert _assert_error_envelope(response)[0]["code"] == "4136"


async def test_duplicate_request_trace_id_is_rejected(
    client: httpx.AsyncClient, signatory: Pkcs8Signatory
) -> None:
    jws = signatory.sign(canonical_json(_invoice().to_wire_dict()))
    jwe = JweEncryptor(await _server_key(client, signatory)).encrypt(jws)
    uid = "6e1c7696-064c-4d95-b9eb-711ab931a734"
    packet = {"payload": jwe, "header": {"requestTraceId": uid, "fiscalId": MEMORY_ID}}

    response = await client.post(
        API + "/invoice", json=[packet, packet], headers=await _bearer(client, signatory)
    )
    assert response.status_code == 400
    assert _assert_error_envelope(response)[0]["code"] == "4163"


# -------------------------------------------------------------------- stubs


async def test_stub_endpoints_answer(
    client: httpx.AsyncClient, signatory: Pkcs8Signatory
) -> None:
    fiscal = await client.get(
        API + "/fiscal-information",
        params={"memoryId": MEMORY_ID},
        headers=await _bearer(client, signatory),
    )
    assert fiscal.status_code == 200
    assert fiscal.json()["nameTrade"] == MEMORY_ID

    taxpayer = await client.get(
        API + "/taxpayer",
        params={"economicCode": NATIONAL_ID},
        headers=await _bearer(client, signatory),
    )
    assert taxpayer.status_code == 200
    assert taxpayer.json()["taxpayerStatus"] == "ACTIVE"

    status = await client.get(
        API + "/inquiry-invoice-status",
        params={"taxIds": "A1121600000000000000C4"},
        headers=await _bearer(client, signatory),
    )
    assert status.status_code == 200
    assert status.json()[0]["error"] == "NOT_FOUND"


async def test_taxpayer_info_returns_the_taxpayer_file_plus_address(
    client: httpx.AsyncClient, signatory: Pkcs8Signatory
) -> None:
    """`taxpayer-info` is SDK-only (see WIRE_FORMAT.md) but must still answer."""
    response = await client.get(
        API + "/taxpayer-info",
        params={"economicCode": NATIONAL_ID},
        headers=await _bearer(client, signatory),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["taxpayerStatus"] == "ACTIVE"
    assert body["nationalId"] == NATIONAL_ID
    # The fields that distinguish it from plain /taxpayer.
    assert body["taxpayerType"] and body["addressTaxpayer"]

    short = await client.get(
        API + "/taxpayer-info",
        params={"economicCode": "123"},
        headers=await _bearer(client, signatory),
    )
    assert short.status_code == 404
    assert _assert_error_envelope(short)[0]["code"] == "4171"


async def test_article6_status_answers_and_validates_its_triple(
    client: httpx.AsyncClient, signatory: Pkcs8Signatory
) -> None:
    response = await client.get(
        API + "/taxpayer-article6-status",
        params={"economicCode": NATIONAL_ID, "vatValue": 1755, "period": 1},
        headers=await _bearer(client, signatory),
    )
    assert response.status_code == 200, response.text
    assert response.json()["article6RemainStatus"] is True

    negative = await client.get(
        API + "/taxpayer-article6-status",
        params={"economicCode": NATIONAL_ID, "vatValue": -1, "period": 1},
        headers=await _bearer(client, signatory),
    )
    assert negative.status_code == 400
    assert _assert_error_envelope(negative)[0]["code"] == "4147"

    # A missing member of the triple is FastAPI's own validation error, which the
    # mock must still dress in the organization's envelope.
    incomplete = await client.get(
        API + "/taxpayer-article6-status",
        params={"economicCode": NATIONAL_ID, "vatValue": 1755},
        headers=await _bearer(client, signatory),
    )
    assert incomplete.status_code == 400
    assert _assert_error_envelope(incomplete)[0]["code"] == "4147"


async def test_invoice_payment_records_a_payment_for_a_known_taxid(
    client: httpx.AsyncClient, state: MockState, signatory: Pkcs8Signatory
) -> None:
    invoice = _invoice()
    jwe = JweEncryptor(await _server_key(client, signatory)).encrypt(
        signatory.sign(canonical_json(invoice.to_wire_dict()))
    )
    submitted = await _submit(
        client, signatory, jwe, "6e1c7696-064c-4d95-b9eb-711ab931a734"
    )
    assert submitted.status_code == 200, submitted.text

    response = await client.post(
        API + "/invoice-payment",
        json={
            "taxid": invoice.header.taxid,
            "paidAmount": 21255,
            "paymentDate": int(datetime.now(UTC).timestamp() * 1000),
            "paymentMethod": "CARD",
            "terminalNumber": "12345678",
            "referenceNumber": "987654321",
        },
        headers=await _bearer(client, signatory),
    )
    assert response.status_code == 200, response.text
    assert response.json() == {"requestStatus": "SUCCESS", "error": []}

    # The mock stores what it accepted, so this proves more than an echo.
    (recorded,) = state.payments
    assert recorded.tax_id == invoice.header.taxid
    assert recorded.paid_amount == 21255
    assert recorded.payment_method == "CARD"
    assert recorded.client_id == MEMORY_ID


async def test_invoice_payment_reports_failed_for_an_unknown_taxid(
    client: httpx.AsyncClient, state: MockState, signatory: Pkcs8Signatory
) -> None:
    response = await client.post(
        API + "/invoice-payment",
        json={
            "taxid": "A1121600000000000000C4",
            "paidAmount": 1000,
            "paymentDate": 1786797257758,
            "paymentMethod": "CASH",
        },
        headers=await _bearer(client, signatory),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["requestStatus"] == "FAILED"
    assert body["error"][0]["code"] == "4147"
    assert not state.payments


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("taxid", "too-short"),
        ("paidAmount", 0),
        ("paidAmount", "21255"),
        ("paymentDate", -1),
        ("paymentMethod", "BITCOIN"),
    ],
)
async def test_invoice_payment_rejects_a_malformed_body(
    client: httpx.AsyncClient, signatory: Pkcs8Signatory, field: str, value: Any
) -> None:
    body = {
        "taxid": "A1121600000000000000C4",
        "paidAmount": 1000,
        "paymentDate": 1786797257758,
        "paymentMethod": "CASH",
    }
    body[field] = value

    response = await client.post(
        API + "/invoice-payment", json=body, headers=await _bearer(client, signatory)
    )
    assert response.status_code == 400, response.text
    assert _assert_error_envelope(response)[0]["code"] == "4147"


@pytest.mark.parametrize(
    ("method", "path", "params"),
    [
        ("GET", "/taxpayer-info", {"economicCode": NATIONAL_ID}),
        ("GET", "/taxpayer-article6-status",
         {"economicCode": NATIONAL_ID, "vatValue": 1, "period": 1}),
        ("POST", "/invoice-payment", None),
    ],
)
async def test_newly_added_routes_require_the_same_auth(
    client: httpx.AsyncClient, method: str, path: str, params: dict[str, Any] | None
) -> None:
    """No route may be reachable without a signed, single-use bearer token."""
    response = await client.request(method, API + path, params=params)
    assert response.status_code == 401, response.text
    assert _assert_error_envelope(response)[0]["code"] == "4130"


async def test_inquiry_by_reference_id_reports_not_found(
    client: httpx.AsyncClient, signatory: Pkcs8Signatory
) -> None:
    response = await client.get(
        API + "/inquiry-by-reference-id",
        params={"referenceIds": "93367b02-23dd-4568-90e1-2b47d799f361"},
        headers=await _bearer(client, signatory),
    )
    assert response.status_code == 200
    assert response.json()[0]["status"] == "NOT_FOUND"


async def test_inquiry_by_time_range_lists_submissions(
    client: httpx.AsyncClient, signatory: Pkcs8Signatory
) -> None:
    jws = signatory.sign(canonical_json(_invoice().to_wire_dict()))
    jwe = JweEncryptor(await _server_key(client, signatory)).encrypt(jws)
    submitted = await _submit(
        client, signatory, jwe, "6e1c7696-064c-4d95-b9eb-711ab931a734"
    )
    assert submitted.status_code == 200

    response = await client.get(
        API + "/inquiry",
        params={"pageNumber": 1, "pageSize": 10, "status": "SUCCESS"},
        headers=await _bearer(client, signatory),
    )
    assert response.status_code == 200
    (found,) = response.json()
    assert found["packetType"] == "receive_invoice_confirm"
    assert found["fiscalId"] == MEMORY_ID


async def test_unsupported_method_uses_the_error_envelope(client: httpx.AsyncClient) -> None:
    response = await client.post(API + "/nonce")
    assert response.status_code == 405
    assert _assert_error_envelope(response)[0]["code"] == "4100"
