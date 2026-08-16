"""Wire-level tests for the HTTP client. respx stands in for the API; no network.

The assertions are deliberately about *bytes on the wire* — header presence,
query serialisation, datetime spelling — because those are what the tax
organization rejects, and a mocked round trip cannot tell us anything else.
"""

from __future__ import annotations

import base64
import itertools
import json
import threading
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import respx
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.x509.oid import NameOID

from moadian.client import MoadianClient, NonceAuthenticator, build_packet, build_url, endpoints
from moadian.client.api import MAX_PACKETS, format_query_datetime
from moadian.config import Settings
from moadian.crypto import (
    JweEncryptor,
    Pkcs8Signatory,
    ServerKey,
    SigningCredentials,
    b64url_decode,
    canonical_json,
)
from moadian.errors import (
    AuthenticationError,
    ConfigurationError,
    MoadianError,
    TaxApiError,
    TransportError,
    UnknownResponseError,
)
from moadian.models import Invoice
from moadian.pipeline import InvoicePipeline
from moadian.taxid import TEHRAN

BASE = "https://sandboxrc.tax.gov.ir/requestsmanager"
V2 = f"{BASE}/api/v2"
CLIENT_ID = "A11216"


# ------------------------------------------------------------------- fixtures


@pytest.fixture(scope="module")
def credentials() -> SigningCredentials:
    """A throwaway self-signed signing pair — the API's OCSP check is not in play here."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name(
        [
            x509.NameAttribute(NameOID.COMMON_NAME, "Moadian Client Test"),
            x509.NameAttribute(NameOID.SERIAL_NUMBER, "14003778990"),
        ]
    )
    now = datetime.now(UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=365))
        .sign(key, hashes.SHA256())
    )
    return SigningCredentials(certificate=cert, private_key=key)


@pytest.fixture
def signatory(credentials: SigningCredentials) -> Pkcs8Signatory:
    return Pkcs8Signatory(credentials)


@pytest.fixture
async def client(signatory: Pkcs8Signatory):
    async with MoadianClient(
        base_url=BASE, client_id=CLIENT_ID, signatory=signatory
    ) as instance:
        yield instance


def mock_nonce(respx_mock: respx.Router) -> respx.Route:
    """A `/nonce` route handing out a distinct challenge every time it is called."""
    counter = itertools.count(1)

    def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"nonce": f"nonce-{next(counter)}", "expDate": "2026-08-15T09:00:00Z"},
        )

    return respx_mock.get(url=f"{V2}/nonce").mock(side_effect=respond)


def verify_jws(token: str) -> tuple[dict, bytes]:
    """Verify a compact JWS against the certificate in its own x5c, as the API does."""
    protected_b64, body_b64, signature_b64 = token.split(".")
    header = json.loads(b64url_decode(protected_b64))
    cert = x509.load_der_x509_certificate(base64.b64decode(header["x5c"][0]))
    cert.public_key().verify(
        b64url_decode(signature_b64),
        f"{protected_b64}.{body_b64}".encode("ascii"),
        padding.PKCS1v15(),
        hashes.SHA256(),
    )
    return header, b64url_decode(body_b64)


def decrypt_jwe(token: str, private_key: rsa.RSAPrivateKey) -> str:
    """What the organization's server does on receipt (see tests/vectors/poc_crypto.py)."""
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


# ------------------------------------------------------------------ endpoints


def test_build_url_tolerates_trailing_slashes() -> None:
    assert build_url(BASE, "nonce") == f"{V2}/nonce"
    assert build_url(BASE + "/", "nonce") == f"{V2}/nonce"
    assert build_url(BASE + "///", "nonce") == f"{V2}/nonce"


def test_build_url_keeps_the_scheme_intact() -> None:
    # os.path.join/pathlib collapse "//" here; string join must not.
    assert build_url("https://tp.tax.gov.ir/requestsmanager", "invoice").startswith("https://")


def test_twelve_v2_resources_are_defined() -> None:
    paths = {
        endpoints.NONCE,
        endpoints.SERVER_INFORMATION,
        endpoints.INVOICE,
        endpoints.INQUIRY,
        endpoints.INQUIRY_BY_UID,
        endpoints.INQUIRY_BY_REFERENCE_ID,
        endpoints.INQUIRY_INVOICE_STATUS,
        endpoints.TAXPAYER,
        endpoints.TAXPAYER_INFO,
        endpoints.FISCAL_INFORMATION,
        endpoints.TAXPAYER_ARTICLE6_STATUS,
        endpoints.INVOICE_PAYMENT,
    }
    assert len(paths) == 12
    assert not any(path.startswith("/") for path in paths)


# --------------------------------------------------------------------- auth


async def test_bearer_token_signs_a_fresh_nonce(
    respx_mock: respx.Router, signatory: Pkcs8Signatory
) -> None:
    nonce_route = mock_nonce(respx_mock)
    async with httpx.AsyncClient() as http:
        auth = NonceAuthenticator(http, BASE, signatory, CLIENT_ID)
        token = await auth.bearer_token()

    assert token.startswith("Bearer ")
    header, payload = verify_jws(token.removeprefix("Bearer "))

    # The signed payload is exactly the documented structure; anything else is 4101.
    assert json.loads(payload) == {"nonce": "nonce-1", "clientId": CLIENT_ID}
    assert list(header) == ["crit", "sigT", "x5c", "alg"]

    request = nonce_route.calls.last.request
    assert "authorization" not in request.headers  # the challenge itself is public
    assert request.url.params["timeToLive"] == "30"


async def test_tokens_are_never_reused(
    respx_mock: respx.Router, client: MoadianClient
) -> None:
    nonce_route = mock_nonce(respx_mock)
    route = respx_mock.get(url=f"{V2}/taxpayer").mock(
        return_value=httpx.Response(200, json={"nameTrade": "x", "taxpayerStatus": "ACTIVE"})
    )

    await client.get_taxpayer("14003778990")
    await client.get_taxpayer("14003778990")

    assert nonce_route.call_count == 2
    first, second = (call.request.headers["authorization"] for call in route.calls)
    assert first != second


async def test_time_to_live_outside_the_accepted_range_is_rejected(
    signatory: Pkcs8Signatory,
) -> None:
    async with httpx.AsyncClient() as http:
        with pytest.raises(ConfigurationError):
            NonceAuthenticator(http, BASE, signatory, CLIENT_ID, time_to_live=5)
        with pytest.raises(ConfigurationError):
            NonceAuthenticator(http, BASE, signatory, CLIENT_ID, time_to_live=201)


async def test_get_nonce_is_unauthenticated(
    respx_mock: respx.Router, client: MoadianClient
) -> None:
    nonce_route = mock_nonce(respx_mock)
    nonce = await client.get_nonce()

    assert nonce.nonce == "nonce-1"
    assert "authorization" not in nonce_route.calls.last.request.headers


# ------------------------------------------------------- authenticated calls

TAXPAYER_BODY = {"nameTrade": "پیشخوان الکترونیک", "taxpayerStatus": "ACTIVE"}

AUTHENTICATED_CALLS = [
    ("GET", endpoints.SERVER_INFORMATION, {"serverTime": 1, "publicKeys": []},
     lambda c: c.get_server_information()),
    ("POST", endpoints.INVOICE, {"timestamp": 0, "result": []},
     lambda c: c.submit_invoices([])),
    ("GET", endpoints.INQUIRY, [],
     lambda c: c.inquiry_by_time(datetime(2023, 5, 14, 10, 0))),
    ("GET", endpoints.INQUIRY_BY_UID, [],
     lambda c: c.inquiry_by_uid(["u1"], CLIENT_ID)),
    ("GET", endpoints.INQUIRY_BY_REFERENCE_ID, [],
     lambda c: c.inquiry_by_reference_id(["r1"])),
    ("GET", endpoints.INQUIRY_INVOICE_STATUS, [],
     lambda c: c.inquiry_invoice_status(["A111DW04E8300004349008"])),
    ("GET", endpoints.TAXPAYER, TAXPAYER_BODY, lambda c: c.get_taxpayer("14003778990")),
    ("GET", endpoints.TAXPAYER_INFO, TAXPAYER_BODY,
     lambda c: c.get_taxpayer_info("14003778990")),
    ("GET", endpoints.FISCAL_INFORMATION, {"nameTrade": "A11216", "fiscalStatus": "ACTIVE"},
     lambda c: c.get_fiscal_information("A11216")),
    ("GET", endpoints.TAXPAYER_ARTICLE6_STATUS, {"article6RemainStatus": True},
     lambda c: c.get_article6_status("14003778990", 1755, 1)),
    ("POST", endpoints.INVOICE_PAYMENT, {"requestStatus": "SUCCESS", "error": []},
     lambda c: c.register_payment({"taxid": "A11216...", "paidAmount": 1000})),
]


@pytest.mark.parametrize(
    "method, endpoint, body, call",
    AUTHENTICATED_CALLS,
    ids=[endpoint for _, endpoint, _, _ in AUTHENTICATED_CALLS],
)
async def test_every_authenticated_call_carries_a_bearer_token(
    respx_mock: respx.Router,
    client: MoadianClient,
    method: str,
    endpoint: str,
    body: object,
    call,
) -> None:
    nonce_route = mock_nonce(respx_mock)
    route = respx_mock.request(method, url=f"{V2}/{endpoint}").mock(
        return_value=httpx.Response(200, json=body)
    )

    await call(client)

    assert nonce_route.call_count == 1
    request = route.calls.last.request
    assert request.headers["authorization"].startswith("Bearer ey")
    verify_jws(request.headers["authorization"].removeprefix("Bearer "))


async def test_submitted_packets_go_out_as_a_json_list(
    respx_mock: respx.Router, client: MoadianClient, signatory: Pkcs8Signatory
) -> None:
    mock_nonce(respx_mock)
    route = respx_mock.post(url=f"{V2}/invoice").mock(
        return_value=httpx.Response(
            200, json={"timestamp": 1, "result": [{"uid": "u1", "referenceNumber": "r1"}]}
        )
    )
    packet = build_packet(
        {"header": {"taxid": "A11216000AB00000123C4"}},
        signatory,
        _encryptor()[0],
        CLIENT_ID,
        request_trace_id="trace-1",
    )

    response = await client.submit_invoices([packet])

    body = json.loads(route.calls.last.request.content)
    assert body == [
        {"payload": packet.payload, "header": {"requestTraceId": "trace-1", "fiscalId": CLIENT_ID}}
    ]
    assert route.calls.last.request.headers["content-type"] == "application/json"
    assert response.result[0].uid == "u1"


# ------------------------------------------------------------ query encoding


async def test_list_params_are_repeated_keys_not_comma_joined(
    respx_mock: respx.Router, client: MoadianClient
) -> None:
    mock_nonce(respx_mock)
    route = respx_mock.get(url=f"{V2}/inquiry-by-reference-id").mock(
        return_value=httpx.Response(200, json=[])
    )

    await client.inquiry_by_reference_id(["ref-a", "ref-b"])

    url = str(route.calls.last.request.url)
    assert url.endswith("?referenceIds=ref-a&referenceIds=ref-b")


async def test_uid_and_tax_id_lists_repeat_too(
    respx_mock: respx.Router, client: MoadianClient
) -> None:
    mock_nonce(respx_mock)
    uid_route = respx_mock.get(url=f"{V2}/inquiry-by-uid").mock(
        return_value=httpx.Response(200, json=[])
    )
    status_route = respx_mock.get(url=f"{V2}/inquiry-invoice-status").mock(
        return_value=httpx.Response(200, json=[])
    )

    await client.inquiry_by_uid(["u1", "u2"], CLIENT_ID)
    await client.inquiry_invoice_status(["tax-1", "tax-2"])

    assert str(uid_route.calls.last.request.url).endswith(
        "?fiscalId=A11216&uidList=u1&uidList=u2"
    )
    assert str(status_route.calls.last.request.url).endswith("?taxIds=tax-1&taxIds=tax-2")


def test_query_datetime_matches_the_documented_format() -> None:
    # yyyy-MM-ddTHH:mm:ss.fffffff00K — nine fractional digits, offset with a colon.
    assert (
        format_query_datetime(datetime(2023, 5, 14, 10, 0, 0))
        == "2023-05-14T10:00:00.000000000+03:30"
    )


def test_query_datetime_keeps_microseconds_and_explicit_offsets() -> None:
    assert (
        format_query_datetime(datetime(2023, 5, 14, 10, 0, 0, 123456, tzinfo=TEHRAN))
        == "2023-05-14T10:00:00.123456000+03:30"
    )
    assert (
        format_query_datetime(datetime(2023, 5, 14, 6, 30, 0, tzinfo=UTC))
        == "2023-05-14T06:30:00.000000000+00:00"
    )


async def test_time_range_params_use_that_format(
    respx_mock: respx.Router, client: MoadianClient
) -> None:
    mock_nonce(respx_mock)
    route = respx_mock.get(url=f"{V2}/inquiry").mock(return_value=httpx.Response(200, json=[]))

    await client.inquiry_by_time(
        datetime(2023, 5, 14, 10, 0), datetime(2023, 5, 15, 10, 0), status="SUCCESS"
    )

    params = route.calls.last.request.url.params
    assert params["start"] == "2023-05-14T10:00:00.000000000+03:30"
    assert params["end"] == "2023-05-15T10:00:00.000000000+03:30"
    assert params["status"] == "SUCCESS"
    assert (params["pageNumber"], params["pageSize"]) == ("1", "10")


# ------------------------------------------------------------------- errors


ERROR_ENVELOPE = {
    "timestamp": 1786797257758,
    "requestTraceId": "2444eefb-0c1f-4e2f-9a7d-1f2b3c4d5e6f",
    "errors": [{"code": "4100", "message": "متد درخواست ارسالی پشتیبانی نمی‌شود."}],
}


async def test_error_envelope_becomes_a_tax_api_error(
    respx_mock: respx.Router, client: MoadianClient
) -> None:
    mock_nonce(respx_mock)
    respx_mock.get(url=f"{V2}/taxpayer").mock(
        return_value=httpx.Response(400, json=ERROR_ENVELOPE)
    )

    with pytest.raises(TaxApiError) as excinfo:
        await client.get_taxpayer("14003778990")

    error = excinfo.value
    assert error.codes == ["4100"]
    assert error.status_code == 400
    assert error.request_trace_id == ERROR_ENVELOPE["requestTraceId"]
    assert "4100" in str(error)


async def test_unparseable_error_body_becomes_unknown_response_error(
    respx_mock: respx.Router, client: MoadianClient
) -> None:
    mock_nonce(respx_mock)
    respx_mock.get(url=f"{V2}/taxpayer").mock(
        return_value=httpx.Response(502, text="<html>Bad Gateway</html>")
    )

    with pytest.raises(UnknownResponseError) as excinfo:
        await client.get_taxpayer("14003778990")

    assert "<html>Bad Gateway</html>" in str(excinfo.value)
    assert excinfo.value.status_code == 502


async def test_unparseable_success_body_becomes_unknown_response_error(
    respx_mock: respx.Router, client: MoadianClient
) -> None:
    mock_nonce(respx_mock)
    respx_mock.get(url=f"{V2}/taxpayer").mock(
        return_value=httpx.Response(200, text="not json at all")
    )

    with pytest.raises(UnknownResponseError) as excinfo:
        await client.get_taxpayer("14003778990")

    assert "not json at all" in str(excinfo.value)


async def test_success_body_of_the_wrong_shape_is_rejected(
    respx_mock: respx.Router, client: MoadianClient
) -> None:
    mock_nonce(respx_mock)
    respx_mock.get(url=f"{V2}/inquiry-invoice-status").mock(
        return_value=httpx.Response(200, json={"taxId": "A11216"})  # object, not array
    )

    with pytest.raises(UnknownResponseError):
        await client.inquiry_invoice_status(["A11216"])


@pytest.mark.parametrize("status_code", [401, 403])
async def test_rejected_token_raises_authentication_error(
    respx_mock: respx.Router, client: MoadianClient, status_code: int
) -> None:
    mock_nonce(respx_mock)
    respx_mock.get(url=f"{V2}/server-information").mock(
        return_value=httpx.Response(
            status_code,
            json={"timestamp": 1, "errors": [{"code": "4102", "message": "چالش معتبر نیست."}]},
        )
    )

    with pytest.raises(AuthenticationError) as excinfo:
        await client.get_server_information()

    assert excinfo.value.codes == ["4102"]
    assert excinfo.value.status_code == status_code


async def test_a_failing_nonce_call_surfaces_as_an_api_error(
    respx_mock: respx.Router, client: MoadianClient
) -> None:
    respx_mock.get(url=f"{V2}/nonce").mock(
        return_value=httpx.Response(
            400,
            json={
                "timestamp": 1,
                "errors": [{"code": "4146", "message": "زمان اعتبار چالش تصادفی…"}],
            },
        )
    )

    with pytest.raises(TaxApiError) as excinfo:
        await client.get_server_information()

    assert excinfo.value.codes == ["4146"]


# -------------------------------------------------------------- build_packet


def _encryptor() -> tuple[JweEncryptor, rsa.RSAPrivateKey]:
    """Stand in for a key from GET /server-information."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    spki = key.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    server_key = ServerKey(id="server-key-1", key=base64.b64encode(spki).decode("ascii"))
    return JweEncryptor(server_key), key


INVOICE = {
    "header": {
        "taxid": "A11216000AB00000123C4",
        "indatim": 1755259200000,
        "irtaxid": None,  # unset — must not reach the wire
        "tprdis": 20000,
    },
    "body": [{"sstid": "2710000138624", "sstt": "سرسیلندر قطعات صنعت فولاد سازی"}],
}


def test_build_packet_round_trips_through_the_server_side(
    signatory: Pkcs8Signatory,
) -> None:
    encryptor, private_key = _encryptor()

    packet = build_packet(INVOICE, signatory, encryptor, CLIENT_ID, request_trace_id="trace-9")

    assert packet.header.fiscalId == CLIENT_ID
    assert packet.header.requestTraceId == "trace-9"
    assert len(packet.payload.split(".")) == 5

    jws = decrypt_jwe(packet.payload, private_key)
    header, payload = verify_jws(jws)

    assert list(header) == ["crit", "sigT", "x5c", "alg"]
    assert payload == canonical_json(INVOICE)
    assert b"irtaxid" not in payload  # null omitted
    assert "سرسیلندر".encode() in payload  # Persian unescaped
    assert json.loads(payload)["header"]["tprdis"] == 20000  # wire names preserved


def test_build_packet_generates_a_trace_id_when_none_is_given(
    signatory: Pkcs8Signatory,
) -> None:
    encryptor, _ = _encryptor()

    first = build_packet(INVOICE, signatory, encryptor, CLIENT_ID)
    second = build_packet(INVOICE, signatory, encryptor, CLIENT_ID)

    assert len(first.header.requestTraceId) == 36
    assert first.header.requestTraceId != second.header.requestTraceId


# ------------------------------------------------------------------ lifetime


async def test_close_only_touches_a_client_we_created(signatory: Pkcs8Signatory) -> None:
    external = httpx.AsyncClient()
    async with MoadianClient(
        base_url=BASE, client_id=CLIENT_ID, signatory=signatory, http=external
    ):
        pass
    assert not external.is_closed
    await external.aclose()

    owned = MoadianClient(base_url=BASE, client_id=CLIENT_ID, signatory=signatory)
    inner = owned._http
    async with owned:
        pass
    assert inner.is_closed


# ---------------------------------------------------------------- transport
#
# Nothing below the client can turn a dead socket into a response, but the
# package promises that everything it raises is a MoadianError — a caller
# wrapping a submission in one `except` must not have httpx leak through it.


async def test_a_read_timeout_becomes_a_transport_error(
    respx_mock: respx.Router, client: MoadianClient
) -> None:
    mock_nonce(respx_mock)
    respx_mock.get(url=f"{V2}/taxpayer").mock(side_effect=httpx.ReadTimeout("timed out"))

    with pytest.raises(TransportError) as excinfo:
        await client.get_taxpayer("14003778990")

    assert isinstance(excinfo.value, MoadianError)
    # The original survives, so retry logic can still tell a timeout from a refusal.
    assert isinstance(excinfo.value.__cause__, httpx.ReadTimeout)
    assert "taxpayer" in str(excinfo.value)


async def test_an_unreachable_nonce_endpoint_becomes_a_transport_error(
    respx_mock: respx.Router, client: MoadianClient
) -> None:
    # The nonce is fetched before every authenticated call, so this is the first
    # thing that fails when the host cannot reach the organization at all.
    respx_mock.get(url=f"{V2}/nonce").mock(side_effect=httpx.ConnectError("no route to host"))

    with pytest.raises(TransportError) as excinfo:
        await client.get_server_information()

    assert isinstance(excinfo.value.__cause__, httpx.ConnectError)


async def test_direct_nonce_transport_failures_are_wrapped_too(
    respx_mock: respx.Router, client: MoadianClient
) -> None:
    respx_mock.get(url=f"{V2}/nonce").mock(side_effect=httpx.ConnectTimeout("timed out"))

    with pytest.raises(TransportError):
        await client.get_nonce()


async def test_wrapping_transport_errors_does_not_swallow_api_errors(
    respx_mock: respx.Router, client: MoadianClient
) -> None:
    """A rejected request is a TaxApiError, not a TransportError.

    The status handling runs after the send, so it must sit outside the
    ``except httpx.HTTPError`` that produces TransportError.
    """
    mock_nonce(respx_mock)
    respx_mock.get(url=f"{V2}/taxpayer").mock(
        return_value=httpx.Response(400, json=ERROR_ENVELOPE)
    )

    with pytest.raises(TaxApiError) as excinfo:
        await client.get_taxpayer("14003778990")

    assert not isinstance(excinfo.value, TransportError)
    assert excinfo.value.codes == ["4100"]


# ------------------------------------------------------------------ settings


async def test_time_to_live_reaches_the_nonce_query_string(
    respx_mock: respx.Router, signatory: Pkcs8Signatory
) -> None:
    nonce_route = mock_nonce(respx_mock)
    respx_mock.get(url=f"{V2}/server-information").mock(
        return_value=httpx.Response(200, json={"serverTime": 1, "publicKeys": []})
    )

    async with MoadianClient(
        base_url=BASE, client_id=CLIENT_ID, signatory=signatory, time_to_live=120
    ) as instance:
        await instance.get_server_information()

    assert nonce_route.calls.last.request.url.params["timeToLive"] == "120"


async def test_client_refuses_a_time_to_live_the_api_would_reject(
    signatory: Pkcs8Signatory,
) -> None:
    with pytest.raises(ConfigurationError):
        MoadianClient(base_url=BASE, client_id=CLIENT_ID, signatory=signatory, time_to_live=5)


async def test_from_settings_plumbs_url_timeout_and_time_to_live(
    respx_mock: respx.Router, signatory: Pkcs8Signatory
) -> None:
    settings = Settings(
        sandbox_base_url=BASE,
        production_base_url="https://tp.tax.gov.ir/requestsmanager",
        request_timeout_seconds=12.5,
        nonce_time_to_live=45,
    )
    nonce_route = mock_nonce(respx_mock)

    async with MoadianClient.from_settings(
        settings, client_id=CLIENT_ID, signatory=signatory
    ) as instance:
        assert instance.base_url == BASE
        assert instance._http.timeout.read == 12.5
        await instance.get_nonce()

    # MOADIAN_NONCE_TIME_TO_LIVE is only worth setting if it lands here.
    assert nonce_route.calls.last.request.url.params["timeToLive"] == "45"


def test_from_settings_selects_the_environment(signatory: Pkcs8Signatory) -> None:
    settings = Settings(sandbox_base_url=BASE, production_base_url="https://prod.example/rm")

    production = MoadianClient.from_settings(
        settings, client_id=CLIENT_ID, signatory=signatory, environment="production"
    )
    assert production.base_url == "https://prod.example/rm"

    with pytest.raises(ConfigurationError):
        MoadianClient.from_settings(
            settings, client_id=CLIENT_ID, signatory=signatory, environment="staging"
        )


# ------------------------------------------------------------- the 1000 cap


async def test_more_than_a_thousand_packets_is_refused_before_the_request(
    respx_mock: respx.Router, client: MoadianClient, signatory: Pkcs8Signatory
) -> None:
    """Error 4143 is cheaper to raise here than to learn from the server.

    A rejected batch has already consumed a serial and a tax id per invoice, and
    neither can be reclaimed — so nothing may go out at all.
    """
    nonce_route = mock_nonce(respx_mock)
    invoice_route = respx_mock.post(url=f"{V2}/invoice").mock(
        return_value=httpx.Response(200, json={"timestamp": 0, "result": []})
    )
    packet = build_packet({"header": {}}, signatory, _encryptor()[0], CLIENT_ID)

    with pytest.raises(TaxApiError) as excinfo:
        await client.submit_invoices([packet] * (MAX_PACKETS + 1))

    assert excinfo.value.codes == ["4143"]
    assert not invoice_route.called
    assert not nonce_route.called  # not even a nonce is burned


async def test_exactly_a_thousand_packets_is_still_allowed(
    respx_mock: respx.Router, client: MoadianClient, signatory: Pkcs8Signatory
) -> None:
    mock_nonce(respx_mock)
    route = respx_mock.post(url=f"{V2}/invoice").mock(
        return_value=httpx.Response(200, json={"timestamp": 0, "result": []})
    )
    packet = build_packet({"header": {}}, signatory, _encryptor()[0], CLIENT_ID)

    await client.submit_invoices([packet] * MAX_PACKETS)

    assert route.called


# ------------------------------------------------------- pipeline batching
#
# The pipeline is what most callers hold, so the cap has to be handled there
# too — by splitting, not by refusing: a caller with 1500 invoices wants them
# sent, and serials must only be spent on a batch that can actually go out.


@pytest.fixture(scope="module")
def server_information_body() -> dict:
    """A `GET /server-information` body carrying one usable RSA encryption key."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    spki = key.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    return {
        "serverTime": 1,
        "publicKeys": [
            {
                "id": "server-key-1",
                "key": base64.b64encode(spki).decode("ascii"),
                "algorithm": "RSA",
                "purpose": 1,
            }
        ],
    }


def _echo_submissions(request: httpx.Request) -> httpx.Response:
    """Answer a POST /invoice the way the API does: one result per uid sent."""
    packets = json.loads(request.content)
    return httpx.Response(
        200,
        json={
            "timestamp": 1,
            "result": [
                {
                    "uid": packet["header"]["requestTraceId"],
                    "referenceNumber": f"ref-{index}",
                }
                for index, packet in enumerate(packets)
            ],
        },
    )


def _unidentified(sample_invoice: Invoice, count: int) -> list[Invoice]:
    """``count`` copies of the sample invoice with no tax id, so the pipeline mints one."""
    invoices = []
    for _ in range(count):
        invoice = sample_invoice.model_copy(deep=True)
        invoice.header.taxid = ""
        invoices.append(invoice)
    return invoices


async def test_pipeline_splits_oversized_batches_instead_of_failing(
    respx_mock: respx.Router,
    client: MoadianClient,
    signatory: Pkcs8Signatory,
    sample_invoice: Invoice,
    server_information_body: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Two per request rather than 1000, so the test signs five invoices, not 1001.
    monkeypatch.setattr("moadian.pipeline.MAX_PACKETS", 2)
    mock_nonce(respx_mock)
    respx_mock.get(url=f"{V2}/server-information").mock(
        return_value=httpx.Response(200, json=server_information_body)
    )
    invoice_route = respx_mock.post(url=f"{V2}/invoice").mock(side_effect=_echo_submissions)

    serials = itertools.count(1)
    pipeline = InvoicePipeline(client, signatory, CLIENT_ID, lambda: next(serials))
    submissions = await pipeline.submit(_unidentified(sample_invoice, 5))

    # Three requests of 2, 2, 1 — and one result per input, in input order.
    assert [len(json.loads(call.request.content)) for call in invoice_route.calls] == [2, 2, 1]
    assert len(submissions) == 5
    assert all(s.reference_number is not None for s in submissions)
    assert len({s.tax_id for s in submissions}) == 5
    assert next(serials) == 6  # exactly five serials consumed


async def test_pipeline_spends_no_serials_on_a_batch_that_never_goes_out(
    respx_mock: respx.Router,
    client: MoadianClient,
    signatory: Pkcs8Signatory,
    sample_invoice: Invoice,
    server_information_body: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The second chunk fails, so only the first chunk's serials are gone."""
    monkeypatch.setattr("moadian.pipeline.MAX_PACKETS", 2)
    mock_nonce(respx_mock)
    respx_mock.get(url=f"{V2}/server-information").mock(
        return_value=httpx.Response(200, json=server_information_body)
    )
    responses = [_echo_submissions, httpx.Response(400, json=ERROR_ENVELOPE)]
    respx_mock.post(url=f"{V2}/invoice").mock(
        side_effect=lambda request: (
            responses.pop(0)(request) if callable(responses[0]) else responses.pop(0)
        )
    )

    serials = itertools.count(1)
    pipeline = InvoicePipeline(client, signatory, CLIENT_ID, lambda: next(serials))

    with pytest.raises(TaxApiError):
        await pipeline.submit(_unidentified(sample_invoice, 4))

    # Two for the chunk that was sent, two never minted for the chunk after the
    # failure — a whole-batch build would have burned all four.
    assert next(serials) == 5


async def test_packet_building_leaves_the_event_loop_free(
    respx_mock: respx.Router,
    client: MoadianClient,
    signatory: Pkcs8Signatory,
    sample_invoice: Invoice,
    server_information_body: dict,
) -> None:
    """Signing, encrypting, and the serial file's flock+fsync run off the loop thread.

    Done inline they block every co-scheduled task for the length of the batch,
    which for a few hundred invoices is a visible stall in any server hosting
    this pipeline.
    """
    mock_nonce(respx_mock)
    respx_mock.get(url=f"{V2}/server-information").mock(
        return_value=httpx.Response(200, json=server_information_body)
    )
    respx_mock.post(url=f"{V2}/invoice").mock(side_effect=_echo_submissions)

    loop_thread = threading.get_ident()
    building_threads: list[int] = []
    serials = itertools.count(1)

    def serial_source() -> int:
        building_threads.append(threading.get_ident())
        return next(serials)

    pipeline = InvoicePipeline(client, signatory, CLIENT_ID, serial_source)
    submissions = await pipeline.submit(_unidentified(sample_invoice, 3))

    assert len(submissions) == 3
    assert building_threads and all(ident != loop_thread for ident in building_threads)
