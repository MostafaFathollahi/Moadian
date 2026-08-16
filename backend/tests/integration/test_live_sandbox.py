"""Tests that talk to the real tax sandbox. Marked ``live``; deselect with -m "not live".

Two things only, one request each. The sandbox is a shared public service and
these tests exist to observe it, not to exercise it:

* ``GET /nonce`` needs no certificate and proves the base URL, the TLS chain and
  the response shape in WIRE_FORMAT.md are all still what we think they are.
* An authenticated call with a development certificate must fail as a *parseable
  API error* rather than a crash, a hang, or an unrecognised body. That is all
  the second test proves — see its docstring for why it cannot prove the CA gate.

When a CA-issued certificate arrives, the second test flips to a positive one:
same call, expect a 200 and a ``publicKeys`` array.

These tests require network access to the sandbox. As of 2026-08-15 this machine
no longer has it — ``sandboxrc.tax.gov.ir`` resolves into 198.18.0.0/15, the
RFC 2544 benchmarking range, i.e. a sinkhole — so both fail on connection
timeout. That is an environment restriction, not a defect in the client.
"""

from __future__ import annotations

import os
import re
from datetime import UTC, datetime

import pytest

from moadian.client import MoadianClient
from moadian.config import Environment
from moadian.crypto import Pkcs8Signatory
from moadian.errors import TaxApiError

pytestmark = pytest.mark.live

#: Which deployment these tests point at. Sandbox unless told otherwise —
#: production is where filings are real, so it takes a deliberate override.
#:
#:     MOADIAN_TEST_ENVIRONMENT=production .venv/bin/pytest -m live
#:
#: A شناسه یکتای حافظه مالیاتی belongs to exactly one environment, so switching
#: the environment without also switching MOADIAN_TEST_MEMORY_ID is a mistake;
#: the fixture below refuses that combination rather than sending a sandbox
#: identity to the operational service.
ENVIRONMENT = Environment.parse(os.environ.get("MOADIAN_TEST_ENVIRONMENT", "sandbox"))

#: A fiscal memory id of the documented shape. It is almost certainly not
#: registered to us, which is fine — the point is that the API says so in its own
#: error envelope instead of failing some other way. Override to use a real one.
MEMORY_ID = os.environ.get("MOADIAN_TEST_MEMORY_ID", "A11216")

TIMEOUT = 30.0

#: `<uuid4>-<epochMillis>` (WIRE_FORMAT.md "Authentication").
NONCE_RE = re.compile(r"^[0-9a-fA-F-]{36}-\d{13}$")


def _parse_exp_date(value: str) -> datetime:
    """Parse the nonce ``expDate``.

    The field is ISO-8601 UTC but the fractional part has been observed with
    more than the six digits ``fromisoformat`` accepts, so it is truncated
    rather than trusted.
    """
    text = value.rstrip("Z")
    if "." in text:
        whole, _, fraction = text.partition(".")
        text = f"{whole}.{fraction[:6]}"
    return datetime.fromisoformat(text).replace(tzinfo=UTC)


@pytest.fixture
async def sandbox_client(dev_signatory: Pkcs8Signatory):
    """A client pointed at :data:`ENVIRONMENT`.

    Named ``sandbox_client`` because that is what it is by default; set
    ``MOADIAN_TEST_ENVIRONMENT=production`` to aim it at the operational service.
    """
    if ENVIRONMENT.is_production and MEMORY_ID == "A11216":
        pytest.skip(
            "refusing to call the operational service with the placeholder memory id. "
            "Set MOADIAN_TEST_MEMORY_ID to the شناسه یکتای حافظه مالیاتی issued for "
            "production — a sandbox id is not valid there."
        )
    async with MoadianClient(
        base_url=ENVIRONMENT.base_url,
        client_id=MEMORY_ID,
        signatory=dev_signatory,
        timeout=TIMEOUT,
    ) as client:
        yield client


async def test_sandbox_nonce_is_reachable_and_well_formed(
    sandbox_client: MoadianClient,
) -> None:
    """One unauthenticated GET. Proves connectivity and the documented shape."""
    nonce = await sandbox_client.get_nonce()

    assert NONCE_RE.match(nonce.nonce), f"unexpected nonce shape: {nonce.nonce!r}"

    expires = _parse_exp_date(nonce.expDate)
    now = datetime.now(UTC)
    assert expires > now, f"nonce expDate {nonce.expDate!r} is already in the past (now {now})"
    # The API accepts 10-200s and may grant more than asked; only the floor matters.
    assert (expires - now).total_seconds() < 400, (
        f"nonce expDate {nonce.expDate!r} is further out than the documented "
        f"200s ceiling allows"
    )


async def test_authenticated_call_with_a_dev_certificate_fails_as_an_api_error(
    sandbox_client: MoadianClient,
) -> None:
    """A dev-certificate call is refused cleanly, in the organization's own envelope.

    What this proves: the client reaches the API, the API refuses, and the refusal
    arrives as a parseable error envelope with at least one code — not a socket
    error, not a gateway page, not an unhandled body shape.

    What it does **not** prove: that the refusal is the CA gate. ``MEMORY_ID`` is
    a fabricated fiscal memory id (see above), so the sandbox has at least two
    independent grounds to say no — an unregistered ``clientId`` (4110) and the
    OCSP/CRL check on a self-signed certificate (4131). The test passes either
    way and cannot distinguish them, so it claims neither.

    TODO: once a CA-issued certificate and a registered ``MOADIAN_TEST_MEMORY_ID``
    are available, replace this with the positive test — ``get_server_information``
    returns 200 with a non-empty ``publicKeys`` array. Only then is it worth
    asserting a specific code here, by re-running the *same* registered clientId
    with a self-signed certificate and asserting 4131 rather than 4110; with an
    unregistered clientId that assertion is unreachable.
    """
    with pytest.raises(TaxApiError) as caught:
        await sandbox_client.get_server_information()

    error = caught.value
    reported = "; ".join(f"{code}: {message}" for code, message in error.errors)
    context = (
        f"sandbox refused a dev-certificate call with HTTP {error.status_code} "
        f"and [{reported or 'no error entries'}] "
        f"(requestTraceId={error.request_trace_id})"
    )

    assert error.status_code in (400, 401, 403), context
    # The organization always names its reason; a bare status would mean we hit
    # a gateway rather than the API.
    assert error.errors, context
    # Every entry carries both halves of the documented {code, message} pair —
    # that, not the value of the code, is what "cleanly enveloped" means here.
    assert all(code and message for code, message in error.errors), context
