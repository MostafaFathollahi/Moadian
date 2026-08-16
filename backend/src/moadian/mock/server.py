"""An in-process stand-in for the tax collection API (RC_TICS.IS_v1.6, API v2).

This is a correctness oracle, not a stub. Every protected route runs the real
server-side checks: it decrypts the JWE with its own RSA key, verifies the inner
JWS against the certificate carried in that token's ``x5c``, asserts the
protected header is exactly the four keys WIRE_FORMAT.md pins, and burns the
nonce so a replay fails. A client that passes here has produced bytes the
organization would accept, minus the parts that need a CA-issued certificate.

Two deliberate divergences from the real service, both in the direction of
failing loudly:

* Packets whose JWE or JWS is broken are rejected inline with HTTP 400 and a
  transport-layer error code. The real API accepts the packet and only reports
  those codes later through ``/inquiry``; waiting is useless in a test.
* ``trusted_certs`` stands in for the chain/OCSP/CRL validation we cannot run
  against a self-signed development certificate.

One RSA keypair serves both roles the organization splits: JWE decryption and
signing the ``sign`` field of inquiry results.
"""

from __future__ import annotations

import base64
import binascii
import json
import re
import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from cryptography import x509
from cryptography.exceptions import InvalidSignature, InvalidTag
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi import APIRouter, Depends, FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from moadian.crypto import b64url, b64url_decode
from moadian.errors import describe
from moadian.models import PaymentMethod, RequestStatus

__all__ = [
    "MockState",
    "NonceRecord",
    "StoredPayment",
    "StoredSubmission",
    "create_mock_app",
]

API_PREFIX = "/api/v2"

#: The only protected-header shape the spec defines, in order (WIRE_FORMAT.md "JWS").
JWS_HEADER_KEYS = ("crit", "sigT", "x5c", "alg")

SIGT_FORMAT = "%Y-%m-%dT%H:%M:%SZ"

NONCE_TTL_DEFAULT = 30
NONCE_TTL_MIN = 10
NONCE_TTL_MAX = 200

MAX_PACKETS = 1000
MAX_INQUIRY_IDS = 100

PACKET_TYPE = "receive_invoice_confirm"

#: A تاریخ منحصر به فرد مالیاتی is 22 uppercase alphanumerics (taxid.TAX_ID_LENGTH).
TAX_ID_RE = re.compile(r"[0-9A-Z]{22}")

#: Mock-only ماده ۶ ceiling, in ریال. RC_TICS does not publish the real figure —
#: this exists so both branches of the flag are reachable from a test.
ARTICLE6_VAT_CEILING = 200_000_000

_OAEP = padding.OAEP(
    mgf=padding.MGF1(algorithm=hashes.SHA256()),
    algorithm=hashes.SHA256(),
    label=None,
)

# fromisoformat rejects the 9-digit fractional seconds the API's own examples use.
_FRACTION = re.compile(r"(\.\d{6})\d+")


def _now() -> datetime:
    return datetime.now(UTC)


def _millis(moment: datetime) -> int:
    return int(moment.timestamp() * 1000)


def _iso_nanos(moment: datetime) -> str:
    """ISO-8601 UTC with nine fractional digits — the shape the real API emits."""
    return f"{moment.strftime('%Y-%m-%dT%H:%M:%S')}.{moment.microsecond:06d}000Z"


# --------------------------------------------------------------------- errors


class Rejection(Exception):
    """A refusal that must surface as the organization's error envelope."""

    def __init__(self, status_code: int, code: str, detail: str | None = None) -> None:
        message = describe(code) or "خطای غیر منتظره‌ای در انجام درخواست رخ داد."
        # The Persian text is what a real client sees; the English detail is why
        # the mock said no, which is the whole reason to run against a mock.
        if detail:
            message = f"{message} ({detail})"
        super().__init__(f"{code}: {message}")
        self.status_code = status_code
        self.code = code
        self.message = message

    def restated(self, status_code: int) -> Rejection:
        """The same complaint at a different status — 401 for auth, 400 for a packet."""
        clone = Rejection(status_code, self.code)
        clone.message = self.message
        return clone


def _envelope(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "timestamp": _millis(_now()),
            "requestTraceId": str(uuid.uuid4()),
            "errors": [{"code": code, "message": message}],
        },
    )


# ---------------------------------------------------------------------- state


@dataclass
class NonceRecord:
    """One issued challenge. Single-use is protocol, not politeness."""

    nonce: str
    expires_at: datetime
    used: bool = False


@dataclass
class StoredSubmission:
    """A packet the mock accepted, decrypted, and verified."""

    reference_number: str
    uid: str
    fiscal_id: str
    client_id: str
    tax_id: str | None
    invoice: dict[str, Any]
    invoice_bytes: bytes
    """The exact signed payload bytes, for byte-identity assertions."""
    jws: str
    signer_der: bytes
    received_at: datetime
    status: str = RequestStatus.SUCCESS


@dataclass
class StoredPayment:
    """A payment the mock accepted against a known taxid (RC_TICS §11)."""

    tax_id: str
    paid_amount: int
    payment_date: int
    payment_method: str
    terminal_number: str | None
    reference_number: str | None
    client_id: str
    recorded_at: datetime


class MockState:
    """Server keypair, issued nonces, and everything submitted so far.

    Reachable from a built app as ``app.state.mock`` so tests can inspect what
    the server actually recovered.
    """

    def __init__(
        self,
        *,
        trusted_certs: Sequence[x509.Certificate] | None = None,
        private_key: rsa.RSAPrivateKey | None = None,
        key_id: str | None = None,
    ) -> None:
        self.private_key = private_key or rsa.generate_private_key(
            public_exponent=65537, key_size=2048
        )
        # Stable for the app's lifetime: clients cache it as the JWE `kid`.
        self.key_id = key_id or str(uuid.uuid4())
        self.nonces: dict[str, NonceRecord] = {}
        self.submissions: dict[str, StoredSubmission] = {}
        self.payments: list[StoredPayment] = []
        self.trusted_der: frozenset[bytes] | None = (
            None
            if trusted_certs is None
            else frozenset(c.public_bytes(serialization.Encoding.DER) for c in trusted_certs)
        )

    # -- keys ---------------------------------------------------------------

    @property
    def public_key_b64(self) -> str:
        """Standard base64 of the SPKI DER, as ``GET /server-information`` returns."""
        der = self.private_key.public_key().public_bytes(
            encoding=serialization.Encoding.DER,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        return base64.b64encode(der).decode("ascii")

    # -- nonces -------------------------------------------------------------

    def issue_nonce(self, time_to_live: int = NONCE_TTL_DEFAULT) -> NonceRecord:
        """Mint ``uuid4-epochMillis`` valid for ``time_to_live`` seconds."""
        ttl = max(NONCE_TTL_MIN, min(NONCE_TTL_MAX, time_to_live))
        now = _now()
        record = NonceRecord(
            nonce=f"{uuid.uuid4()}-{_millis(now)}",
            expires_at=now + timedelta(seconds=ttl),
        )
        self.nonces[record.nonce] = record
        return record

    def consume_nonce(self, nonce: str) -> NonceRecord:
        """Burn ``nonce``, or raise 4102 — unknown, expired, and replayed alike."""
        record = self.nonces.get(nonce)
        if record is None:
            raise Rejection(401, "4102", "nonce was never issued by this server")
        if record.used:
            raise Rejection(401, "4102", "nonce already used")
        if record.expires_at <= _now():
            raise Rejection(401, "4102", "nonce expired")
        record.used = True
        return record

    def expire_nonce(self, nonce: str) -> None:
        """Test hook: backdate a nonce instead of sleeping out its 10s minimum."""
        record = self.nonces[nonce]
        record.expires_at = _now() - timedelta(seconds=1)

    # -- submissions --------------------------------------------------------

    def by_uid(self, uid: str) -> StoredSubmission | None:
        return next((s for s in self.submissions.values() if s.uid == uid), None)

    def sign_result(self, submission: StoredSubmission) -> str:
        """The ``sign`` field of a SUCCESS inquiry result (RC_TICS §8-2).

        Two header keys only — the organization's own response signature is not
        the taxpayer's four-key form.
        """
        header = {"alg": "RS256", "sigT": _now().strftime(SIGT_FORMAT)}
        payload = {
            "referenceNumber": submission.reference_number,
            "clientId": submission.client_id,
            "taxId": submission.tax_id,
            "receivedDate": submission.received_at.isoformat(timespec="milliseconds").replace(
                "+00:00", "Z"
            ),
        }
        protected = b64url(json.dumps(header, separators=(",", ":")).encode("utf-8"))
        body = b64url(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
        signature = self.private_key.sign(
            f"{protected}.{body}".encode("ascii"), padding.PKCS1v15(), hashes.SHA256()
        )
        return f"{protected}.{body}.{b64url(signature)}"


@dataclass(frozen=True)
class AuthContext:
    """What a verified bearer token established about the caller."""

    client_id: str
    nonce: str
    certificate: x509.Certificate
    header: dict[str, Any] = field(default_factory=dict)


# ------------------------------------------------------------------- JWS side


def _decode_certificate(entry: Any, *, code: str) -> x509.Certificate:
    """Load one ``x5c`` entry: standard base64 of bare DER, no armour, no base64url."""
    if not isinstance(entry, str):
        raise Rejection(401, code, "x5c entry is not a string")
    try:
        der = base64.b64decode(entry, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise Rejection(401, code, f"x5c is not standard base64: {exc}") from exc
    try:
        return x509.load_der_x509_certificate(der)
    except ValueError as exc:
        raise Rejection(401, code, f"x5c is not a DER certificate: {exc}") from exc


def _check_protected_header(header: dict[str, Any], *, code: str) -> None:
    """Assert the exact four-key form. Drift, including the SDK's typ/cty, fails here."""
    if tuple(header) != JWS_HEADER_KEYS:
        raise Rejection(
            401,
            code,
            f"protected header must be exactly {list(JWS_HEADER_KEYS)} in order, "
            f"got {list(header)}",
        )
    if header["alg"] != "RS256":
        raise Rejection(401, code, f"alg must be RS256, got {header['alg']!r}")
    if header["crit"] != ["sigT"]:
        raise Rejection(401, code, f"crit must be ['sigT'], got {header['crit']!r}")
    if not isinstance(header["x5c"], list) or not header["x5c"]:
        raise Rejection(401, "4135", "x5c is empty")
    try:
        datetime.strptime(header["sigT"], SIGT_FORMAT)
    except (TypeError, ValueError) as exc:
        raise Rejection(401, code, f"sigT must be {SIGT_FORMAT!r}: {exc}") from exc


def _verify_jws(
    token: str,
    state: MockState,
    *,
    structure_code: str,
    signature_code: str,
    cert_code: str,
) -> tuple[dict[str, Any], bytes, x509.Certificate]:
    """Verify a compact JWS against the certificate in its own ``x5c``.

    Returns ``(protected header, payload bytes, signing certificate)``.
    """
    parts = token.split(".")
    if len(parts) != 3:
        raise Rejection(401, structure_code, f"expected 3 JWS segments, got {len(parts)}")
    protected_b64, payload_b64, signature_b64 = parts

    try:
        raw_header = b64url_decode(protected_b64)
        header = json.loads(raw_header)
        payload = b64url_decode(payload_b64)
        signature = b64url_decode(signature_b64)
    except (binascii.Error, ValueError, json.JSONDecodeError) as exc:
        raise Rejection(401, structure_code, f"undecodable JWS segments: {exc}") from exc
    if not isinstance(header, dict):
        raise Rejection(401, structure_code, "protected header is not a JSON object")

    _check_protected_header(header, code=structure_code)
    certificate = _decode_certificate(header["x5c"][0], code="4136")

    now = _now()
    if not (certificate.not_valid_before_utc <= now <= certificate.not_valid_after_utc):
        raise Rejection(401, cert_code, "signing certificate is outside its validity window")

    # Stands in for the chain + OCSP/CRL check the organization runs; a
    # self-signed development certificate can never satisfy the real one.
    if state.trusted_der is not None:
        der = certificate.public_bytes(serialization.Encoding.DER)
        if der not in state.trusted_der:
            raise Rejection(401, cert_code, "signing certificate is not trusted")

    public_key = certificate.public_key()
    if not isinstance(public_key, rsa.RSAPublicKey):
        raise Rejection(401, "4132", "signing certificate does not carry an RSA key")
    try:
        public_key.verify(
            signature,
            f"{protected_b64}.{payload_b64}".encode("ascii"),
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
    except InvalidSignature as exc:
        raise Rejection(401, signature_code, "signature does not verify") from exc

    return header, payload, certificate


# ------------------------------------------------------------------- JWE side


def _decrypt_jwe(token: str, state: MockState) -> str:
    """Undo the client's compact JWE with the mock's private key."""
    parts = token.split(".")
    if len(parts) != 5:
        raise Rejection(400, "04150", f"expected 5 JWE segments, got {len(parts)}")
    protected_b64, key_b64, iv_b64, ciphertext_b64, tag_b64 = parts

    try:
        header = json.loads(b64url_decode(protected_b64))
        encrypted_key = b64url_decode(key_b64)
        iv = b64url_decode(iv_b64)
        ciphertext = b64url_decode(ciphertext_b64)
        tag = b64url_decode(tag_b64)
    except (binascii.Error, ValueError, json.JSONDecodeError) as exc:
        raise Rejection(400, "04150", f"undecodable JWE segments: {exc}") from exc
    if not isinstance(header, dict):
        raise Rejection(400, "04150", "protected header is not a JSON object")

    if header.get("alg") != "RSA-OAEP-256" or header.get("enc") != "A256GCM":
        raise Rejection(
            400,
            "04152",
            f"expected RSA-OAEP-256/A256GCM, got {header.get('alg')!r}/{header.get('enc')!r}",
        )
    if header.get("kid") != state.key_id:
        raise Rejection(400, "04150", f"unknown kid {header.get('kid')!r}")
    if len(iv) != 12:
        raise Rejection(400, "04153", f"IV must be 96 bits, got {len(iv) * 8}")

    try:
        cek = state.private_key.decrypt(encrypted_key, _OAEP)
    except ValueError as exc:
        raise Rejection(400, "04150", f"could not unwrap the content key: {exc}") from exc
    if len(cek) != 32:
        raise Rejection(400, "04152", f"A256GCM needs a 256-bit CEK, got {len(cek) * 8}")

    try:
        # AAD is the ASCII of the encoded protected header, per RFC 7516.
        plaintext = AESGCM(cek).decrypt(iv, ciphertext + tag, protected_b64.encode("ascii"))
    except InvalidTag as exc:
        raise Rejection(
            400, "04150", "AEAD tag mismatch: ciphertext or header was altered"
        ) from exc
    try:
        return plaintext.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise Rejection(400, "4134", f"plaintext is not UTF-8: {exc}") from exc


# ------------------------------------------------------------------ inquiries


def _parse_timestamp(value: str | None, name: str) -> datetime | None:
    if value is None:
        return None
    try:
        moment = datetime.fromisoformat(_FRACTION.sub(r"\1", value))
    except ValueError as exc:
        raise Rejection(400, "4147", f"{name} is not ISO-8601: {exc}") from exc
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def _inquiry_result(state: MockState, submission: StoredSubmission) -> dict[str, Any]:
    succeeded = submission.status == RequestStatus.SUCCESS
    return {
        "referenceNumber": submission.reference_number,
        "uid": submission.uid,
        "status": submission.status,
        "data": {"error": [], "warning": [], "success": succeeded},
        "packetType": PACKET_TYPE,
        "fiscalId": submission.fiscal_id,
        "sign": state.sign_result(submission) if succeeded else "",
    }


def _not_found(identifier: str, *, by_uid: bool) -> dict[str, Any]:
    return {
        "referenceNumber": None if by_uid else identifier,
        "uid": identifier if by_uid else None,
        "status": RequestStatus.NOT_FOUND,
        "data": {},
        "packetType": None,
        "fiscalId": None,
        "sign": "",
    }


def _window(
    submissions: list[StoredSubmission], start: datetime | None, end: datetime | None
) -> list[StoredSubmission]:
    if start is not None and end is not None and start > end:
        raise Rejection(400, "4140", "start must precede end")
    if start is None and end is None:
        # Documented default: the last 24 hours.
        start = _now() - timedelta(days=1)
    return [
        s
        for s in submissions
        if (start is None or s.received_at >= start) and (end is None or s.received_at <= end)
    ]


# ----------------------------------------------------------- taxpayer lookups


def _check_economic_code(economic_code: str) -> None:
    """Shared by ``/taxpayer``, ``/taxpayer-info`` and ``/taxpayer-article6-status``."""
    if len(economic_code) < 10:
        raise Rejection(404, "4171", f"economicCode is {len(economic_code)} characters")


# -------------------------------------------------------------------- payment


def _required_int(body: dict[str, Any], name: str) -> int:
    """One required integer field of the payment body, JSON booleans excluded."""
    value = body.get(name)
    if isinstance(value, bool) or not isinstance(value, int):
        raise Rejection(400, "4147", f"{name} must be an integer, got {value!r}")
    if value < 0:
        raise Rejection(400, "4147", f"{name} must not be negative, got {value}")
    return value


def _optional_str(body: dict[str, Any], name: str) -> str | None:
    value = body.get(name)
    if value is None:
        return None
    if not isinstance(value, str):
        raise Rejection(400, "4147", f"{name} must be a string, got {type(value).__name__}")
    return value


def _accept_payment(body: dict[str, Any], auth: AuthContext) -> StoredPayment:
    """Validate one ``POST /invoice-payment`` body (RC_TICS §11).

    RC_TICS spells the invoice reference ``taxid`` in its field list and ``taxId``
    in its own curl example on the same page; the SDK's ``RegisterPaymentRequestDto``
    uses ``TaxId``. Both spellings are accepted rather than pinning our guess as
    if the document were consistent.
    """
    tax_id = body.get("taxid", body.get("taxId"))
    if not isinstance(tax_id, str) or not TAX_ID_RE.fullmatch(tax_id):
        raise Rejection(400, "4147", f"taxid must be 22 uppercase alphanumerics: {tax_id!r}")

    paid_amount = _required_int(body, "paidAmount")
    if paid_amount == 0:
        raise Rejection(400, "4147", "paidAmount must be greater than zero")
    payment_date = _required_int(body, "paymentDate")

    method = body.get("paymentMethod")
    allowed = sorted(str(m) for m in PaymentMethod)
    if not isinstance(method, str) or method not in allowed:
        raise Rejection(400, "4147", f"paymentMethod must be one of {allowed}, got {method!r}")

    return StoredPayment(
        tax_id=tax_id,
        paid_amount=paid_amount,
        payment_date=payment_date,
        payment_method=method,
        terminal_number=_optional_str(body, "terminalNumber"),
        reference_number=_optional_str(body, "referenceNumber"),
        client_id=auth.client_id,
        recorded_at=_now(),
    )


# ------------------------------------------------------------------- the app


def create_mock_app(*, trusted_certs: Sequence[x509.Certificate] | None = None) -> FastAPI:
    """Build an ASGI app that impersonates the tax API and checks what it is sent.

    ``trusted_certs`` restricts which signing certificates are accepted, standing
    in for the organization's CA validation.
    """
    state = MockState(trusted_certs=trusted_certs)
    app = FastAPI(title="Moadian mock", version="2.0")
    app.state.mock = state

    async def authenticate(request: Request) -> AuthContext:
        """Every route but ``/nonce`` goes through here (RC_TICS §5)."""
        authorization = request.headers.get("authorization", "")
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not token.strip():
            raise Rejection(401, "4130", "missing or malformed Authorization: Bearer header")

        header, payload, certificate = _verify_jws(
            token.strip(),
            state,
            structure_code="4130",
            signature_code="4133",
            cert_code="4131",
        )

        try:
            claims = json.loads(payload)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise Rejection(401, "4101", f"payload is not JSON: {exc}") from exc
        if not isinstance(claims, dict) or set(claims) != {"nonce", "clientId"}:
            raise Rejection(
                401,
                "4101",
                f"payload must be exactly nonce+clientId, got "
                f"{sorted(claims) if isinstance(claims, dict) else type(claims).__name__}",
            )

        nonce, client_id = claims["nonce"], claims["clientId"]
        if not isinstance(client_id, str) or not client_id:
            raise Rejection(401, "4110", "clientId is empty")
        if not isinstance(nonce, str) or not nonce:
            raise Rejection(401, "4102", "nonce is empty")

        state.consume_nonce(nonce)
        context = AuthContext(
            client_id=client_id, nonce=nonce, certificate=certificate, header=header
        )
        # Stashed rather than injected: `from __future__ import annotations` turns
        # a route's `Annotated[AuthContext, Depends(authenticate)]` into a string
        # FastAPI cannot evaluate, because `authenticate` is a closure local.
        request.state.auth = context
        return context

    public = APIRouter(prefix=API_PREFIX)
    protected = APIRouter(prefix=API_PREFIX, dependencies=[Depends(authenticate)])

    # -- challenge ----------------------------------------------------------

    @public.get("/nonce")
    async def nonce(timeToLive: int = NONCE_TTL_DEFAULT) -> dict[str, str]:
        record = state.issue_nonce(timeToLive)
        return {"nonce": record.nonce, "expDate": _iso_nanos(record.expires_at)}

    # -- server keys --------------------------------------------------------

    @protected.get("/server-information")
    async def server_information() -> dict[str, Any]:
        return {
            "serverTime": _millis(_now()),
            "publicKeys": [
                {
                    "key": state.public_key_b64,
                    "id": state.key_id,
                    "algorithm": "RSA",
                    "purpose": 1,
                }
            ],
        }

    # -- submission ---------------------------------------------------------

    @protected.post("/invoice")
    async def invoice(request: Request) -> dict[str, Any]:
        auth: AuthContext = request.state.auth  # set by the router's dependency
        try:
            packets = json.loads(await request.body())
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise Rejection(400, "4144", f"body is not JSON: {exc}") from exc
        if not isinstance(packets, list) or not packets:
            raise Rejection(400, "4144", "body must be a non-empty JSON array of packets")
        if len(packets) > MAX_PACKETS:
            raise Rejection(400, "4143", f"{len(packets)} packets in one request")

        # Verify the whole batch before storing any of it, so a rejected request
        # leaves no half-accepted state behind.
        #
        # Duplicates are checked against every uid this mock has ever accepted, not
        # just the current batch: requestTraceId is what inquiry-by-uid keys on, so
        # replaying one across requests makes the result ambiguous. RC_TICS does not
        # say whether the real service dedupes across requests or only within one
        # (4163 reads "شناسه درخواست تکراری" either way), so the mock takes the
        # strict reading — reusing a uid is a client bug under both.
        already = {s.uid for s in state.submissions.values()}
        seen: set[str] = set()
        accepted: list[StoredSubmission] = []
        for packet in packets:
            uid, submission = _accept(state, packet, auth)
            if uid in seen or uid in already:
                raise Rejection(400, "4163", f"duplicate requestTraceId {uid!r}")
            seen.add(uid)
            accepted.append(submission)

        for submission in accepted:
            state.submissions[submission.reference_number] = submission

        return {
            "timestamp": _millis(_now()),
            "result": [
                {
                    "uid": s.uid,
                    "packetType": None,
                    "referenceNumber": s.reference_number,
                    "data": None,
                }
                for s in accepted
            ],
        }

    # -- inquiry ------------------------------------------------------------

    @protected.get("/inquiry-by-reference-id")
    async def inquiry_by_reference_id(
        referenceIds: Annotated[list[str], Query()] = [],  # noqa: B006 — FastAPI reads the default
        start: str | None = None,
        end: str | None = None,
    ) -> list[dict[str, Any]]:
        if not referenceIds:
            raise Rejection(400, "4147", "referenceIds is required")
        if len(referenceIds) > MAX_INQUIRY_IDS:
            raise Rejection(400, "4141", f"{len(referenceIds)} ids in one request")
        window = _window(
            list(state.submissions.values()),
            _parse_timestamp(start, "start"),
            _parse_timestamp(end, "end"),
        )
        found = {s.reference_number: s for s in window}
        return [
            _inquiry_result(state, found[r]) if r in found else _not_found(r, by_uid=False)
            for r in referenceIds
        ]

    @protected.get("/inquiry-by-uid")
    async def inquiry_by_uid(
        uidList: Annotated[list[str], Query()] = [],  # noqa: B006 — FastAPI reads the default
        fiscalId: str | None = None,
        start: str | None = None,
        end: str | None = None,
    ) -> list[dict[str, Any]]:
        if not uidList:
            raise Rejection(400, "4147", "uidList is required")
        if len(uidList) > MAX_INQUIRY_IDS:
            raise Rejection(400, "4141", f"{len(uidList)} ids in one request")
        window = _window(
            [
                s
                for s in state.submissions.values()
                if fiscalId is None or s.fiscal_id == fiscalId
            ],
            _parse_timestamp(start, "start"),
            _parse_timestamp(end, "end"),
        )
        found = {s.uid: s for s in window}
        return [
            _inquiry_result(state, found[u]) if u in found else _not_found(u, by_uid=True)
            for u in uidList
        ]

    @protected.get("/inquiry")
    async def inquiry(
        pageNumber: int = 1,
        pageSize: int = 10,
        status: str | None = None,
        start: str | None = None,
        end: str | None = None,
    ) -> list[dict[str, Any]]:
        if pageNumber < 1 or not 1 <= pageSize <= 100:
            raise Rejection(400, "4147", "pageNumber >= 1 and pageSize in 1..100")
        allowed = {RequestStatus.SUCCESS, RequestStatus.FAILED, RequestStatus.IN_PROGRESS,
                   RequestStatus.TIMEOUT}
        if status is not None and status not in allowed:
            raise Rejection(400, "4142", f"unknown status {status!r}")

        window = _window(
            [s for s in state.submissions.values() if status is None or s.status == status],
            _parse_timestamp(start, "start"),
            _parse_timestamp(end, "end"),
        )
        page = window[(pageNumber - 1) * pageSize : pageNumber * pageSize]
        return [_inquiry_result(state, s) for s in page]

    # -- stubs --------------------------------------------------------------

    @protected.get("/inquiry-invoice-status")
    async def inquiry_invoice_status(
        taxIds: Annotated[list[str], Query()] = [],  # noqa: B006 — FastAPI reads the default
    ) -> list[dict[str, Any]]:
        if not taxIds:
            raise Rejection(400, "4147", "taxIds is required")
        known = {s.tax_id for s in state.submissions.values() if s.tax_id}
        return [
            {
                "taxId": tax_id,
                "invoiceStatus": "SYSTEMIC_APPROVED" if tax_id in known else None,
                "article6Status": "NOT_EXCEEDED" if tax_id in known else None,
                "error": None if tax_id in known else "NOT_FOUND",
            }
            for tax_id in taxIds
        ]

    @protected.get("/taxpayer")
    async def taxpayer(economicCode: str) -> dict[str, Any]:
        _check_economic_code(economicCode)
        return {
            "nameTrade": "شرکت آزمایشی مودیان",
            "taxpayerStatus": "ACTIVE",
            "nationalId": economicCode,
        }

    @protected.get("/taxpayer-info")
    async def taxpayer_info(economicCode: str) -> dict[str, Any]:
        """The same taxpayer file as ``/taxpayer``, plus type and address.

        Not attested by RC_TICS.IS_v1.6 — the path exists only in the .NET SDK
        (``PacketTypeConstants.cs:12``, ``RequestProvider.cs:126-131``). The extra
        fields mirror ``TaxpayerResult``; see WIRE_FORMAT.md "Endpoints".
        """
        _check_economic_code(economicCode)
        return {
            "nameTrade": "شرکت آزمایشی مودیان",
            "taxpayerStatus": "ACTIVE",
            "nationalId": economicCode,
            "taxpayerType": "LEGAL",
            "postalcodeTaxpayer": "1994844121",
            "addressTaxpayer": "تهران، خیابان آزمایشی، پلاک ۱",
        }

    @protected.get("/taxpayer-article6-status")
    async def taxpayer_article6_status(
        economicCode: str, vatValue: int, period: int
    ) -> dict[str, Any]:
        """Would this VAT amount cross the ماده ۶ ceiling in this period?

        Also SDK-only (``PacketTypeConstants.cs:13``, ``RequestProvider.cs:133-140``),
        including the economicCode/vatValue/period triple; RC_TICS never names it.
        A non-integer ``vatValue``/``period`` is caught by FastAPI and comes back
        as 4147 through the validation handler, so only the ranges are checked here.
        """
        _check_economic_code(economicCode)
        if vatValue < 0:
            raise Rejection(400, "4147", f"vatValue must not be negative, got {vatValue}")
        # The SDK types period as a plain int with no documented range, so the
        # mock asserts only what that implies: a positive period number.
        if period < 1:
            raise Rejection(400, "4147", f"period must be positive, got {period}")
        return {"article6RemainStatus": vatValue <= ARTICLE6_VAT_CEILING}

    # -- payment ------------------------------------------------------------

    @protected.post("/invoice-payment")
    async def invoice_payment(request: Request) -> dict[str, Any]:
        """Register a payment against a نسیه invoice (RC_TICS §11).

        Returns the documented ``{requestStatus, error}`` shape: SUCCESS with an
        empty list, or FAILED naming a taxid this server never accepted.
        """
        auth: AuthContext = request.state.auth  # set by the router's dependency
        try:
            body = json.loads(await request.body())
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise Rejection(400, "4144", f"body is not JSON: {exc}") from exc
        if not isinstance(body, dict):
            raise Rejection(400, "4144", "body must be a JSON object")

        payment = _accept_payment(body, auth)
        if payment.tax_id not in {s.tax_id for s in state.submissions.values()}:
            # RC_TICS publishes no code for "no such invoice"; 4147 is the generic
            # input error and the English detail carries the actual reason.
            return {
                "requestStatus": RequestStatus.FAILED,
                "error": [
                    {
                        "code": "4147",
                        "message": f"{describe('4147')} (no invoice with taxid "
                        f"{payment.tax_id!r} was submitted to this server)",
                    }
                ],
            }

        state.payments.append(payment)
        return {"requestStatus": RequestStatus.SUCCESS, "error": []}

    @protected.get("/fiscal-information")
    async def fiscal_information(memoryId: str) -> dict[str, Any]:
        if not re.fullmatch(r"[A-Z0-9]{6}", memoryId):
            raise Rejection(
                400, "4148", f"memoryId must be 6 uppercase alphanumerics: {memoryId!r}"
            )
        return {
            "nameTrade": memoryId,
            "fiscalStatus": "ACTIVE",
            "nationalId": "14003778990",
            "economicCode": "14003778990",
        }

    app.include_router(public)
    app.include_router(protected)

    # -- error envelope everywhere -----------------------------------------
    # FastAPI's default {"detail": ...} would let a client that mishandles the
    # real envelope pass its tests, so every failure path is remapped.

    async def _on_rejection(_: Request, exc: Exception) -> JSONResponse:
        assert isinstance(exc, Rejection)
        return _envelope(exc.status_code, exc.code, exc.message)

    async def _on_validation(_: Request, exc: Exception) -> JSONResponse:
        return _envelope(400, "4147", f"{describe('4147')} ({exc})")

    async def _on_http(_: Request, exc: Exception) -> JSONResponse:
        assert isinstance(exc, StarletteHTTPException)
        code = "4100" if exc.status_code == 405 else "4147"
        return _envelope(exc.status_code, code, f"{describe(code)} ({exc.detail})")

    app.add_exception_handler(Rejection, _on_rejection)
    app.add_exception_handler(RequestValidationError, _on_validation)
    app.add_exception_handler(StarletteHTTPException, _on_http)

    @app.middleware("http")
    async def _catch_all(
        request: Request, call_next: Callable[[Request], Awaitable[Any]]
    ) -> Any:
        # Registering a handler for Exception would make Starlette re-raise after
        # responding; a middleware returns the envelope and stops there.
        try:
            return await call_next(request)
        except Exception as exc:  # noqa: BLE001 — a real server never leaks a traceback
            return _envelope(500, "5199", f"{describe('5199')} ({exc!r})")

    return app


def _accept(state: MockState, packet: Any, auth: AuthContext) -> tuple[str, StoredSubmission]:
    """Decrypt, verify and parse one submission packet."""
    if not isinstance(packet, dict):
        raise Rejection(400, "4144", "packet is not a JSON object")
    header = packet.get("header")
    payload = packet.get("payload")
    if not isinstance(header, dict) or not isinstance(payload, str) or not payload:
        raise Rejection(400, "4145", "packet needs a string payload and an object header")

    uid = header.get("requestTraceId")
    fiscal_id = header.get("fiscalId")
    if not isinstance(uid, str) or not uid or not isinstance(fiscal_id, str) or not fiscal_id:
        raise Rejection(400, "4145", "header needs requestTraceId and fiscalId")
    try:
        uuid.UUID(uid)
    except ValueError as exc:
        raise Rejection(400, "4162", f"requestTraceId {uid!r} is not a uuid") from exc

    jws = _decrypt_jwe(payload, state)
    try:
        _, invoice_bytes, certificate = _verify_jws(
            jws,
            state,
            structure_code="04130",
            signature_code="04131",
            cert_code="04131",
        )
    except Rejection as exc:
        # Same checks, but these are transport-layer codes on a 400, not a 401.
        raise exc.restated(400) from exc

    try:
        invoice = json.loads(invoice_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise Rejection(400, "04130", f"invoice payload is not JSON: {exc}") from exc
    if not isinstance(invoice, dict) or "header" not in invoice or "body" not in invoice:
        raise Rejection(400, "04130", "invoice needs a header object and a body array")
    tax_id = invoice["header"].get("taxid") if isinstance(invoice["header"], dict) else None
    if not isinstance(tax_id, str) or not tax_id:
        raise Rejection(400, "04148", "invoice header carries no taxid")

    return uid, StoredSubmission(
        reference_number=str(uuid.uuid4()),
        uid=uid,
        fiscal_id=fiscal_id,
        client_id=auth.client_id,
        tax_id=tax_id,
        invoice=invoice,
        invoice_bytes=invoice_bytes,
        jws=jws,
        signer_der=certificate.public_bytes(serialization.Encoding.DER),
        received_at=_now(),
    )
