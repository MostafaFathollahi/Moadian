"""Responses the tax API returns.

Every model is `extra="ignore"`: the organization adds fields between spec
revisions and a strict model would turn a working deployment into a hard failure.

Status fields are `Enum | str` unions in left-to-right mode — a documented value
parses to the enum, an undocumented one survives as its raw string instead of
raising.
"""

from typing import Annotated, Any

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, model_validator

from .enums import Article6Status, InvoiceStatus, RequestStatus

__all__ = [
    "ApiError",
    "BatchResponse",
    "ErrorEnvelope",
    "FiscalInformationResult",
    "InquiryResult",
    "InvoiceStatusResult",
    "NonceResponse",
    "PublicKey",
    "ServerInformation",
    "SubmitResult",
    "TaxpayerResult",
    "ValidationDetail",
]

_TOLERANT = ConfigDict(extra="ignore", populate_by_name=True)


def _code_to_str(value: Any) -> Any:
    """Accept a numeric error code as the string the catalogue is keyed by.

    Observed bodies carry ``"code": "4143"`` in most places and ``"code": 4143``
    in some; a strict ``str`` field turns the numeric form into a validation
    failure, and the operator then sees an error with no code at all. Note that
    the transport-layer codes have a significant leading zero (``04130``), so a
    code that arrives as a string is never renumbered here.
    """
    if isinstance(value, bool):  # bool is an int; a boolean code is garbage.
        return value
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return value


def _null_to_empty_text(value: Any) -> Any:
    """``"message": null`` means "no text", not "unparseable response"."""
    return "" if value is None else value


def _drop_null_entries(value: Any) -> Any:
    """Tolerate ``"errors": null`` and null elements inside the list."""
    if value is None:
        return []
    if isinstance(value, list):
        return [item for item in value if item is not None]
    return value


ErrorCode = Annotated[str, BeforeValidator(_code_to_str)]
ErrorText = Annotated[str, BeforeValidator(_null_to_empty_text)]
ErrorList = Annotated[list["ApiError"], BeforeValidator(_drop_null_entries)]


class NonceResponse(BaseModel):
    """`GET /nonce`. `expDate` stays a string — the observed TTL disagrees with
    the requested one, so the client treats this value as truth and parses it
    itself rather than risking a format-dependent validation error here."""

    model_config = _TOLERANT

    nonce: str
    expDate: str


class PublicKey(BaseModel):
    """One server encryption key; `id` becomes the JWE `kid`."""

    model_config = _TOLERANT

    key: str
    id: str
    algorithm: str | None = None
    purpose: int | None = None


class ServerInformation(BaseModel):
    """`GET /server-information`."""

    model_config = _TOLERANT

    serverTime: int
    publicKeys: list[PublicKey] = []


class SubmitResult(BaseModel):
    """One element of the `POST /invoice` batch response."""

    model_config = _TOLERANT

    uid: str
    packetType: str | None = None
    referenceNumber: str | None = None
    data: str | None = None


class BatchResponse(BaseModel):
    """`POST /invoice`."""

    model_config = _TOLERANT

    timestamp: int
    result: list[SubmitResult] = []


class ApiError(BaseModel):
    """An error or warning entry. `errorType` (`ERROR`/`WARNING`) appears in
    inquiry validation details but not in the top-level error envelope.

    `code` is the diagnostic the operator acts on, so it is parsed as leniently
    as it can be without losing meaning: a numeric code becomes its string form,
    and a null message becomes `""` rather than sinking the whole envelope.
    """

    model_config = _TOLERANT

    code: ErrorCode
    message: ErrorText = ""
    errorType: str | None = None


class ValidationDetail(BaseModel):
    """`data` of an inquiry result once the invoice has been validated."""

    model_config = _TOLERANT

    error: ErrorList = []
    warning: ErrorList = []
    success: bool


class InquiryResult(BaseModel):
    """`GET /inquiry`, `/inquiry-by-uid`, `/inquiry-by-reference-id`.

    `sign` is a compact JWS of the validation outcome, populated only when
    `status == SUCCESS`; otherwise the API sends `""`.
    """

    model_config = _TOLERANT

    referenceNumber: str | None = None
    uid: str | None = None
    status: RequestStatus | str | None = Field(default=None, union_mode="left_to_right")
    # `{}` while IN_PROGRESS/NOT_FOUND, a ValidationDetail once processed.
    data: ValidationDetail | dict[str, Any] | None = Field(
        default=None, union_mode="left_to_right"
    )
    packetType: str | None = None
    fiscalId: str | None = None
    sign: str | None = None


class InvoiceStatusResult(BaseModel):
    """`GET /inquiry-invoice-status`. `error` is `NOT_FOUND`/`ACCESS_DENIED`."""

    model_config = _TOLERANT

    taxId: str | None = None
    invoiceStatus: InvoiceStatus | str | None = Field(
        default=None, union_mode="left_to_right"
    )
    article6Status: Article6Status | str | None = Field(
        default=None, union_mode="left_to_right"
    )
    error: str | None = None


class TaxpayerResult(BaseModel):
    """`GET /taxpayer` and `GET /taxpayer-info`.

    `taxpayerStatus`: NOT_ALLOCATED, ACTIVE, DEACTIVATED, TEMPORARY_UNAUTHORIZE,
    PERMANENT_UNAUTHORIZE, ARTICLE_2_SUBJECT. Left as a plain string — the list
    has grown across spec revisions.
    """

    model_config = _TOLERANT

    nameTrade: str | None = None
    taxpayerStatus: str | None = None
    nationalId: str | None = None
    # taxpayer-info only
    taxpayerType: str | None = None
    postalcodeTaxpayer: str | None = None
    addressTaxpayer: str | None = None


class FiscalInformationResult(BaseModel):
    """`GET /fiscal-information?memoryId=`. `nameTrade` is the memory id."""

    model_config = _TOLERANT

    nameTrade: str | None = None
    fiscalStatus: str | None = None
    nationalId: str | None = None
    economicCode: str | None = None


class ErrorEnvelope(BaseModel):
    """Non-2xx body shape shared by every endpoint.

    Deliberately looser than the documented shape. Failing to parse an envelope
    costs the operator the error codes — the one thing that says what to fix —
    and `timestamp` is not always present (some gateway-level 4xx/5xx bodies
    carry only `errors`). So every documented field is optional here, and the
    model earns its strictness back through :meth:`_require_a_known_field`:
    an HTML page or an unrelated JSON object still fails, and the caller still
    reports the raw body instead of an empty error list.
    """

    model_config = _TOLERANT

    timestamp: int | None = None
    requestTraceId: str | None = None
    errors: ErrorList = []

    @model_validator(mode="before")
    @classmethod
    def _require_a_known_field(cls, data: Any) -> Any:
        """Reject a body that has none of the envelope's own keys.

        Without this, `extra="ignore"` plus all-optional fields would accept any
        JSON object at all, and `{"detail": "gateway timeout"}` would surface as
        a `TaxApiError` with no codes rather than as an `UnknownResponseError`
        carrying the body.
        """
        if isinstance(data, dict):
            if not any(key in data for key in ("timestamp", "requestTraceId", "errors")):
                raise ValueError(
                    "not an error envelope: expected at least one of "
                    "'timestamp', 'requestTraceId', 'errors'"
                )
        return data
