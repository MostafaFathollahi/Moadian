"""Challenge-response authentication, and the response decoding it shares with the API client.

Every authenticated call carries its own token, signed over a nonce fetched for
that call alone (WIRE_FORMAT.md "Authentication"). Nothing is cached — a nonce
is consumed by the first request that presents it, so a reused token fails with
error 4102.

The response helpers live here rather than in ``api`` because this is the lower
module: ``api`` imports ``auth``, never the other way round.
"""

from __future__ import annotations

import json
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from moadian.client import endpoints
from moadian.client.endpoints import build_url
from moadian.crypto import Signatory, canonical_json
from moadian.errors import (
    AuthenticationError,
    ConfigurationError,
    TaxApiError,
    TransportError,
    UnknownResponseError,
)
from moadian.models import ErrorEnvelope, NonceResponse

__all__ = [
    "MAX_TIME_TO_LIVE",
    "MIN_TIME_TO_LIVE",
    "NonceAuthenticator",
    "decode_json_body",
    "decode_model",
    "decode_model_list",
    "raise_for_api_error",
]

#: `timeToLive` bounds the API enforces; outside them it answers 4146.
MIN_TIME_TO_LIVE = 10
MAX_TIME_TO_LIVE = 200

_JSON_HEADERS = {"Accept": "application/json"}

# Enough of an unparseable body to identify it in a log, not enough to dump a
# whole HTML error page into an exception message.
_SNIPPET_LIMIT = 1000

ModelT = TypeVar("ModelT", bound=BaseModel)


def _snippet(response: httpx.Response) -> str:
    text = response.text or ""
    return text if len(text) <= _SNIPPET_LIMIT else text[:_SNIPPET_LIMIT] + "…"


def raise_for_api_error(response: httpx.Response) -> None:
    """Translate a non-2xx response into the matching exception.

    401/403 raise :class:`AuthenticationError` even when the body is unusable:
    the status alone already says what the caller must fix.
    """
    if response.is_success:
        return

    try:
        envelope: ErrorEnvelope | None = ErrorEnvelope.model_validate(response.json())
    except (ValueError, ValidationError):
        # Gateways in front of the API answer with HTML, and 5xx pages are not
        # always enveloped.
        envelope = None

    errors = [(e.code, e.message) for e in envelope.errors] if envelope else []
    trace_id = envelope.requestTraceId if envelope else None

    if response.status_code in (401, 403):
        raise AuthenticationError(
            "the tax API rejected the bearer token"
            if envelope
            else f"the tax API rejected the bearer token; body: {_snippet(response)}",
            status_code=response.status_code,
            errors=errors,
            request_trace_id=trace_id,
        )

    if envelope is None:
        raise UnknownResponseError(
            f"HTTP {response.status_code} with an unparseable body: {_snippet(response)}",
            status_code=response.status_code,
        )

    raise TaxApiError(
        "the tax API rejected the request",
        status_code=response.status_code,
        errors=errors,
        request_trace_id=trace_id,
    )


def decode_json_body(response: httpx.Response) -> Any:
    """Parse a successful response body as JSON."""
    try:
        return response.json()
    except (json.JSONDecodeError, ValueError, UnicodeDecodeError) as exc:
        raise UnknownResponseError(
            f"response body is not JSON ({exc}): {_snippet(response)}",
            status_code=response.status_code,
        ) from exc


def decode_model(response: httpx.Response, model: type[ModelT]) -> ModelT:
    """Parse a successful response body into ``model``."""
    try:
        return model.model_validate(decode_json_body(response))
    except ValidationError as exc:
        raise UnknownResponseError(
            f"response does not match {model.__name__} ({exc}): {_snippet(response)}",
            status_code=response.status_code,
        ) from exc


def decode_model_list(response: httpx.Response, model: type[ModelT]) -> list[ModelT]:
    """Parse a successful response body into a list of ``model``."""
    body = decode_json_body(response)
    if not isinstance(body, list):
        raise UnknownResponseError(
            f"expected a JSON array of {model.__name__}: {_snippet(response)}",
            status_code=response.status_code,
        )
    try:
        return [model.model_validate(item) for item in body]
    except ValidationError as exc:
        raise UnknownResponseError(
            f"response does not match list[{model.__name__}] ({exc}): {_snippet(response)}",
            status_code=response.status_code,
        ) from exc


class NonceAuthenticator:
    """Mints one single-use bearer token per request.

    Holds no state between calls by design: caching either the nonce or the
    token produces a request the organization rejects.
    """

    def __init__(
        self,
        http: httpx.AsyncClient,
        base_url: str,
        signatory: Signatory,
        client_id: str,
        time_to_live: int = 30,
    ) -> None:
        if not MIN_TIME_TO_LIVE <= time_to_live <= MAX_TIME_TO_LIVE:
            raise ConfigurationError(
                f"time_to_live must be between {MIN_TIME_TO_LIVE} and {MAX_TIME_TO_LIVE} "
                f"seconds, got {time_to_live}"
            )
        self._http = http
        self._base_url = base_url
        self._signatory = signatory
        self._client_id = client_id
        self._time_to_live = time_to_live

    @property
    def client_id(self) -> str:
        """The شناسه حافظه مالیاتی the token speaks for."""
        return self._client_id

    @property
    def time_to_live(self) -> int:
        return self._time_to_live

    async def fetch_nonce(self) -> NonceResponse:
        """`GET /nonce`. Deliberately unauthenticated — sending a token here is an error."""
        url = build_url(self._base_url, endpoints.NONCE)
        # Only the send is wrapped: raise_for_api_error's TaxApiError must not be
        # recaught and relabelled as a transport failure.
        try:
            response = await self._http.get(
                url,
                params={"timeToLive": self._time_to_live},
                headers=_JSON_HEADERS,
            )
        except httpx.HTTPError as exc:
            raise TransportError(f"GET {url} failed: {type(exc).__name__}: {exc}") from exc
        raise_for_api_error(response)
        return decode_model(response, NonceResponse)

    async def bearer_token(self) -> str:
        """Fetch a fresh nonce and return the `Authorization` value signed over it."""
        nonce = await self.fetch_nonce()
        # The API parses this payload structurally; a wrong shape is error 4101.
        payload = canonical_json({"nonce": nonce.nonce, "clientId": self._client_id})
        return f"Bearer {self._signatory.sign(payload)}"
