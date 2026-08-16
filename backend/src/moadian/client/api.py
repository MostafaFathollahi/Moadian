"""Async client for the Moadian v2 API.

One method per resource in WIRE_FORMAT.md "Endpoints". Every authenticated call
mints its own token first; that is the protocol, not a policy choice.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from types import TracebackType
from typing import TYPE_CHECKING, Any
from uuid import uuid4

import httpx

from moadian.client import endpoints
from moadian.client.auth import (
    NonceAuthenticator,
    decode_json_body,
    decode_model,
    decode_model_list,
    raise_for_api_error,
)
from moadian.client.endpoints import build_url
from moadian.crypto import (
    JweEncryptor,
    Pkcs8Signatory,
    Signatory,
    SigningCredentials,
    canonical_json,
)
from moadian.errors import TaxApiError, TransportError, describe
from moadian.models import (
    BatchResponse,
    FiscalInformationResult,
    InquiryResult,
    InvoiceStatusResult,
    NonceResponse,
    Packet,
    PacketHeader,
    RequestStatus,
    ServerInformation,
    TaxpayerResult,
)
from moadian.taxid import TEHRAN

if TYPE_CHECKING:  # imported for typing only — config must not become a runtime dep here
    from moadian.config import Profile, Settings

__all__ = ["MAX_PACKETS", "MoadianClient", "build_packet", "format_query_datetime"]

#: `POST /invoice` refuses more than 1000 packets in one request (error 4143).
MAX_PACKETS = 1000

_JSON_HEADERS = {"Accept": "application/json"}
_JSON_CONTENT_TYPE = {"Content-Type": "application/json", **_JSON_HEADERS}

#: One query parameter, already stringified. Repeated keys are legal and used.
_Param = tuple[str, str]


def format_query_datetime(moment: datetime) -> str:
    """Render a datetime the way the API's query parser expects.

    The SDK's format string is ``yyyy-MM-ddTHH:mm:ss.fffffff00K`` — seven
    fractional digits (.NET 100-ns ticks) followed by two literal zeros, so nine
    in total, then a ``+03:30``-style offset. Python only carries microseconds,
    so the last three digits are always zero.

    Naive input is anchored to Asia/Tehran; aware input keeps its own offset, so
    what goes on the wire is always the instant the caller meant.
    """
    anchored = moment if moment.tzinfo is not None else moment.replace(tzinfo=TEHRAN)
    offset = anchored.utcoffset() or timedelta(0)
    total_minutes = int(offset.total_seconds() // 60)
    sign = "-" if total_minutes < 0 else "+"
    hours, minutes = divmod(abs(total_minutes), 60)
    return (
        f"{anchored:%Y-%m-%dT%H:%M:%S}.{anchored.microsecond:06d}000"
        f"{sign}{hours:02d}:{minutes:02d}"
    )


def build_packet(
    invoice_wire_dict: Mapping[str, Any],
    signatory: Signatory,
    encryptor: JweEncryptor,
    fiscal_id: str,
    request_trace_id: str | None = None,
) -> Packet:
    """Turn an invoice dict into a submittable packet: canonicalise, sign, encrypt.

    ``invoice_wire_dict`` must already use wire field names; nulls are dropped by
    :func:`canonical_json`. ``request_trace_id`` is the uid used later for
    inquiry, so keep it if you want to look the submission up again.
    """
    jws = signatory.sign(canonical_json(invoice_wire_dict))
    return Packet(
        payload=encryptor.encrypt(jws),
        header=PacketHeader(
            requestTraceId=request_trace_id or str(uuid4()),
            fiscalId=fiscal_id,
        ),
    )


class MoadianClient:
    """Async client for one fiscal memory against one environment."""

    def __init__(
        self,
        *,
        base_url: str,
        client_id: str,
        signatory: Signatory,
        http: httpx.AsyncClient | None = None,
        timeout: float = 60.0,
        time_to_live: int = 30,
    ) -> None:
        self.base_url = base_url
        self.client_id = client_id
        # A caller-supplied client carries its own timeout and lifetime; we only
        # configure and close one we made ourselves.
        self._owns_http = http is None
        self._http = http if http is not None else httpx.AsyncClient(timeout=timeout)
        self.authenticator = NonceAuthenticator(
            self._http, base_url, signatory, client_id, time_to_live=time_to_live
        )
        self._signatory = signatory

    @property
    def signatory(self) -> Signatory:
        """The identity this client signs with.

        Exposed so a caller that already has a configured client — the API layer
        building a pipeline, say — does not have to carry the signatory alongside
        it and risk the two disagreeing.
        """
        return self._signatory

    @classmethod
    def from_settings(
        cls,
        settings: Settings,
        *,
        client_id: str,
        signatory: Signatory,
        environment: str = "sandbox",
        http: httpx.AsyncClient | None = None,
    ) -> MoadianClient:
        """Build a client from :class:`~moadian.config.Settings`.

        ``environment`` picks which of the two pinned base URLs to use, and the
        timeout and nonce ``timeToLive`` come from the settings object — which is
        the only way ``MOADIAN_REQUEST_TIMEOUT_SECONDS`` and
        ``MOADIAN_NONCE_TIME_TO_LIVE`` ever reach the wire.
        """
        return cls(
            base_url=settings.base_url(environment),
            client_id=client_id,
            signatory=signatory,
            http=http,
            timeout=settings.request_timeout_seconds,
            time_to_live=settings.nonce_time_to_live,
        )

    @classmethod
    def from_profile(
        cls,
        profile: Profile,
        *,
        settings: Settings | None = None,
        http: httpx.AsyncClient | None = None,
    ) -> MoadianClient:
        """Build a client for a stored profile — the intended way to switch environments.

        A profile carries its environment, its شناسه یکتای حافظه مالیاتی and its
        signing credentials as one unit, so moving between آزمایشی and عملیاتی is
        selecting a different profile rather than editing a URL. That matters
        because a memory id is issued per environment and is not portable: pairing
        a production URL with a sandbox identity is the mistake this prevents.

        The signatory is built from the profile's own certificate, so the identity
        that signs is always the one the profile names.
        """
        # Imported here, not at module scope: config depends on nothing in client,
        # and the TYPE_CHECKING guard above keeps that direction one-way.
        from moadian.config import Settings as _Settings

        profile.validate()
        settings = settings or _Settings()
        credentials = SigningCredentials.from_pem(
            profile.certificate_pem, profile.private_key_pem
        )
        credentials.assert_usable()
        return cls(
            base_url=profile.base_url_override or settings.base_url(profile.environment),
            client_id=profile.memory_id,
            signatory=Pkcs8Signatory(credentials),
            http=http,
            timeout=settings.request_timeout_seconds,
            time_to_live=settings.nonce_time_to_live,
        )

    async def __aenter__(self) -> MoadianClient:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        """Close the HTTP client, unless it was passed in."""
        if self._owns_http:
            await self._http.aclose()

    # ------------------------------------------------------------------ core

    async def _request(
        self,
        method: str,
        endpoint: str,
        *,
        params: Sequence[_Param] | None = None,
        content: bytes | None = None,
    ) -> httpx.Response:
        """Send one authenticated request, with a token minted for it alone."""
        headers = dict(_JSON_CONTENT_TYPE if content is not None else _JSON_HEADERS)
        headers["Authorization"] = await self.authenticator.bearer_token()

        url = build_url(self.base_url, endpoint)
        # Only the send is inside the try: raise_for_api_error raises TaxApiError,
        # which must reach the caller as itself and not be relabelled transport.
        try:
            response = await self._http.request(
                method,
                url,
                # A list of pairs, so repeated keys survive: httpx would otherwise
                # need a dict, which cannot express ?taxIds=a&taxIds=b.
                params=list(params) if params else None,
                content=content,
                headers=headers,
            )
        except httpx.HTTPError as exc:
            raise TransportError(f"{method} {url} failed: {type(exc).__name__}: {exc}") from exc
        raise_for_api_error(response)
        return response

    # -------------------------------------------------------------- resources

    async def get_nonce(self) -> NonceResponse:
        """`GET /nonce` — unauthenticated by definition."""
        return await self.authenticator.fetch_nonce()

    async def get_server_information(self) -> ServerInformation:
        """`GET /server-information` — the public keys invoices are encrypted to."""
        response = await self._request("GET", endpoints.SERVER_INFORMATION)
        return decode_model(response, ServerInformation)

    async def submit_invoices(self, packets: list[Packet]) -> BatchResponse:
        """`POST /invoice`. Max 1000 packets per request (error 4143).

        The cap is checked here rather than left to the server: an oversized
        batch is rejected wholesale, and by then its serials and tax ids have
        already been spent. :meth:`~moadian.pipeline.InvoicePipeline.submit`
        chunks for you; this is the backstop for direct callers.
        """
        if len(packets) > MAX_PACKETS:
            raise TaxApiError(
                f"cannot submit more than {MAX_PACKETS} packets in one request, "
                f"got {len(packets)}",
                errors=[("4143", describe("4143") or "")],
            )
        body = canonical_json([packet.model_dump() for packet in packets])
        response = await self._request("POST", endpoints.INVOICE, content=body)
        return decode_model(response, BatchResponse)

    async def inquiry_by_reference_id(
        self,
        reference_ids: Sequence[str],
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[InquiryResult]:
        """`GET /inquiry-by-reference-id` — look up by the server's reference numbers."""
        params: list[_Param] = [("referenceIds", ref) for ref in reference_ids]
        params += _time_range(start, end)
        response = await self._request("GET", endpoints.INQUIRY_BY_REFERENCE_ID, params=params)
        return decode_model_list(response, InquiryResult)

    async def inquiry_by_uid(
        self,
        uid_list: Sequence[str],
        fiscal_id: str,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[InquiryResult]:
        """`GET /inquiry-by-uid` — look up by the `requestTraceId`s we generated."""
        params: list[_Param] = [("fiscalId", fiscal_id)]
        params += [("uidList", uid) for uid in uid_list]
        params += _time_range(start, end)
        response = await self._request("GET", endpoints.INQUIRY_BY_UID, params=params)
        return decode_model_list(response, InquiryResult)

    async def inquiry_by_time(
        self,
        start: datetime,
        end: datetime | None = None,
        status: RequestStatus | str | None = None,
        page_number: int = 1,
        page_size: int = 10,
    ) -> list[InquiryResult]:
        """`GET /inquiry` — a time range, at most one week wide (error 4164)."""
        params: list[_Param] = [("start", format_query_datetime(start))]
        if end is not None:
            params.append(("end", format_query_datetime(end)))
        if status is not None:
            params.append(("status", str(status)))
        params += [("pageNumber", str(page_number)), ("pageSize", str(page_size))]
        response = await self._request("GET", endpoints.INQUIRY, params=params)
        return decode_model_list(response, InquiryResult)

    async def inquiry_invoice_status(self, tax_ids: list[str]) -> list[InvoiceStatusResult]:
        """`GET /inquiry-invoice-status` — the buyer's reaction in the کارپوشه."""
        params: list[_Param] = [("taxIds", tax_id) for tax_id in tax_ids]
        response = await self._request("GET", endpoints.INQUIRY_INVOICE_STATUS, params=params)
        return decode_model_list(response, InvoiceStatusResult)

    async def get_taxpayer(self, economic_code: str) -> TaxpayerResult:
        """`GET /taxpayer?economicCode=` — name and file status."""
        response = await self._request(
            "GET", endpoints.TAXPAYER, params=[("economicCode", economic_code)]
        )
        return decode_model(response, TaxpayerResult)

    async def get_taxpayer_info(self, economic_code: str) -> TaxpayerResult:
        """`GET /taxpayer-info?economicCode=` — same file, plus address and type."""
        response = await self._request(
            "GET", endpoints.TAXPAYER_INFO, params=[("economicCode", economic_code)]
        )
        return decode_model(response, TaxpayerResult)

    async def get_fiscal_information(self, memory_id: str) -> FiscalInformationResult:
        """`GET /fiscal-information?memoryId=` — is this fiscal memory active?"""
        response = await self._request(
            "GET", endpoints.FISCAL_INFORMATION, params=[("memoryId", memory_id)]
        )
        return decode_model(response, FiscalInformationResult)

    async def get_article6_status(
        self, economic_code: str, vat_value: int, period: int
    ) -> dict[str, Any]:
        """`GET /taxpayer-article6-status` — would this VAT amount cross the ماده ۶ ceiling?

        Returns the raw object (`{"article6RemainStatus": bool}` in the SDK); the
        response has no documented model in RC_TICS, so it is not narrowed here.
        """
        params: list[_Param] = [
            ("economicCode", economic_code),
            ("vatValue", str(vat_value)),
            ("period", str(period)),
        ]
        response = await self._request("GET", endpoints.TAXPAYER_ARTICLE6_STATUS, params=params)
        return decode_json_body(response)

    async def register_payment(self, request: dict[str, Any]) -> dict[str, Any]:
        """`POST /invoice-payment` — record a payment against a نسیه invoice.

        The request body is passed through as given (nulls dropped): its fields
        are `taxid`, `paidAmount`, `paymentDate`, `paymentMethod`,
        `terminalNumber`, `referenceNumber`.
        """
        response = await self._request(
            "POST", endpoints.INVOICE_PAYMENT, content=canonical_json(request)
        )
        return decode_json_body(response)


def _time_range(start: datetime | None, end: datetime | None) -> list[_Param]:
    """Optional `start`/`end` bounds, formatted for the query string."""
    params: list[_Param] = []
    if start is not None:
        params.append(("start", format_query_datetime(start)))
    if end is not None:
        params.append(("end", format_query_datetime(end)))
    return params
