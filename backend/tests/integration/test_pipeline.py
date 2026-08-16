"""The pipeline driven end to end against the mock tax API.

:class:`~moadian.pipeline.InvoicePipeline` is the object the README hands to
callers, and it is the only place where a tax id is minted. Everything below it
is unit-tested in isolation; what is not otherwise covered is the assembly —
whether the serial that reaches the counter, the tax id that reaches the JWS, and
the bytes that reach the server are the same three facts.

So nothing here is stubbed. The pipeline talks to a real
:class:`~moadian.client.MoadianClient` over ``httpx.ASGITransport`` into
:func:`~moadian.mock.create_mock_app`, which decrypts the JWE, verifies the JWS,
and burns the nonce before it will answer. Every assertion about a tax id is made
against the value the *server* recovered, not against the one the client kept.

The one thing replaced is ``asyncio.sleep``: ``await_results`` must wait out the
organization's mandatory ten seconds, and a suite that actually waits them is a
suite nobody runs. The clock is faked; the waiting is asserted.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from moadian.client import MoadianClient, build_packet
from moadian.client.api import MAX_PACKETS
from moadian.crypto import JweEncryptor, Pkcs8Signatory, ServerKey
from moadian.errors import TaxApiError
from moadian.mock import MockState, create_mock_app
from moadian.models import Invoice, InvoiceBodyItem, InvoiceHeader, RequestStatus
from moadian.pipeline import (
    MAX_INQUIRY_IDS,
    InvoicePipeline,
    InvoiceSubmission,
    MonotonicSerialCounter,
)
from moadian.taxid import generate_tax_id, invoice_serial_hex

BASE = "http://mock"

#: Same values as tests/conftest.py, restated rather than imported — `tests` is
#: not an importable package, only a rootdir pytest collects from.
MEMORY_ID = "A11216"
NATIONAL_ID = "14003778990"
BUYER_NATIONAL_ID = "10100302746"
GOODS_DESCRIPTION = "سرسیلندر قطعات صنعت فولاد سازی"

#: Where the serial segment sits inside a tax id: memoryId(6) + day_range(5).
SERIAL_SLICE = slice(11, 21)


# ------------------------------------------------------------------ fixtures


@pytest.fixture
def app() -> FastAPI:
    return create_mock_app()


@pytest.fixture
def state(app: FastAPI) -> MockState:
    return app.state.mock


@pytest.fixture
def requests() -> list[httpx.Request]:
    """Every request the client actually sent, in order."""
    return []


@pytest.fixture
async def http(app: FastAPI, requests: list[httpx.Request]) -> AsyncIterator[httpx.AsyncClient]:
    """An httpx client wired straight into the mock app, recording what goes out.

    The event hook observes; it never answers. The response still comes from the
    mock, which is the point of running against it.
    """

    async def record(request: httpx.Request) -> None:
        requests.append(request)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url=BASE, event_hooks={"request": [record]}
    ) as client:
        yield client


@pytest.fixture
def client(http: httpx.AsyncClient, dev_signatory: Pkcs8Signatory) -> MoadianClient:
    return MoadianClient(
        base_url=BASE, client_id=MEMORY_ID, signatory=dev_signatory, http=http
    )


@pytest.fixture
def counter(tmp_path: Path) -> MonotonicSerialCounter:
    return MonotonicSerialCounter(tmp_path / "instance" / "serial")


@pytest.fixture
def pipeline(
    client: MoadianClient, dev_signatory: Pkcs8Signatory, counter: MonotonicSerialCounter
) -> InvoicePipeline:
    return InvoicePipeline(client, dev_signatory, MEMORY_ID, counter)


# ------------------------------------------------------------------- helpers


def make_invoice(*, taxid: str = "", inno: str | None = None) -> Invoice:
    """A minimal پترن ۱ invoice. ``taxid=""`` is what makes the pipeline mint one."""
    issued_at = datetime.now(UTC)
    return Invoice(
        header=InvoiceHeader(
            taxid=taxid,
            indatim=int(issued_at.timestamp() * 1000),
            inty=1,
            inp=1,
            ins=1,
            inno=inno,
            setm=2,
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


def sent(requests: list[httpx.Request], method: str, path: str) -> list[httpx.Request]:
    return [r for r in requests if r.method == method and r.url.path == f"/api/v2/{path}"]


def batch_sizes(requests: list[httpx.Request]) -> list[int]:
    """How many packets went out in each ``POST /invoice``."""
    return [len(json.loads(r.content)) for r in sent(requests, "POST", "invoice")]


def fake_clock(
    monkeypatch: pytest.MonkeyPatch, log: list[tuple[str, object]]
) -> None:
    """Replace ``asyncio.sleep`` with one that records its delay and returns at once.

    ``await_results`` sleeps ten seconds before its first inquiry by design. The
    delays are the assertion, so they are recorded rather than served.
    """
    real_sleep = asyncio.sleep

    async def instant(delay: float, *args: object, **kwargs: object) -> None:
        log.append(("sleep", delay))
        await real_sleep(0)

    monkeypatch.setattr(asyncio, "sleep", instant)


def spy_on_inquiries(
    monkeypatch: pytest.MonkeyPatch, client: MoadianClient, log: list[tuple[str, object]]
) -> None:
    """Record each inquiry, then make the real one against the mock."""
    original = client.inquiry_by_reference_id

    async def counted(reference_ids, *args, **kwargs):  # type: ignore[no-untyped-def]
        log.append(("inquiry", list(reference_ids)))
        return await original(reference_ids, *args, **kwargs)

    monkeypatch.setattr(client, "inquiry_by_reference_id", counted)


def set_status(state: MockState, status: str) -> None:
    for submission in state.submissions.values():
        submission.status = status


# ----------------------------------------------------------- identity minting


async def test_each_invoice_gets_its_own_tax_id_and_the_server_recovers_it(
    pipeline: InvoicePipeline, state: MockState, counter: MonotonicSerialCounter
) -> None:
    """Three invoices, three serials, three tax ids — as decrypted by the server.

    A tax id read back from the client would prove nothing; these come out of the
    JWE the mock decrypted and the JWS it verified.
    """
    invoices = [make_invoice() for _ in range(3)]

    submissions = await pipeline.submit(invoices)

    assert len(submissions) == 3
    assert len({s.tax_id for s in submissions}) == 3, "two invoices share a tax id"
    assert len({s.uid for s in submissions}) == 3
    assert all(s.reference_number for s in submissions)

    for expected_serial, submission in enumerate(submissions, start=1):
        stored = state.by_uid(submission.uid)
        assert stored is not None, "the server never saw this uid"
        assert stored.tax_id == submission.tax_id, "server and client disagree on the tax id"
        # And the same value inside the signed bytes, not just the stored summary.
        assert json.loads(stored.invoice_bytes)["header"]["taxid"] == submission.tax_id
        assert stored.fiscal_id == MEMORY_ID
        assert submission.tax_id[:6] == MEMORY_ID
        assert len(submission.tax_id) == 22
        assert submission.tax_id[SERIAL_SLICE] == invoice_serial_hex(expected_serial)


async def test_inno_is_set_from_the_same_serial_as_the_tax_id(
    pipeline: InvoicePipeline, state: MockState
) -> None:
    """``inno`` and the tax id's serial segment must agree — they are one number."""
    submissions = await pipeline.submit([make_invoice() for _ in range(2)])

    for submission in submissions:
        stored = state.by_uid(submission.uid)
        assert stored is not None
        header = json.loads(stored.invoice_bytes)["header"]
        assert header["inno"] == submission.tax_id[SERIAL_SLICE]
        assert header["inno"] == invoice_serial_hex(int(submission.tax_id[SERIAL_SLICE], 16))


async def test_the_on_disk_counter_advances_by_one_per_generated_tax_id(
    pipeline: InvoicePipeline, counter: MonotonicSerialCounter, tmp_path: Path
) -> None:
    """The serial must survive a restart, so it has to be on disk, not in memory."""
    assert counter.current == 0

    await pipeline.submit([make_invoice() for _ in range(3)])
    assert counter.current == 3

    await pipeline.submit([make_invoice()])
    assert counter.current == 4

    # What a restarted process would read.
    assert (tmp_path / "instance" / "serial").read_text(encoding="ascii").strip() == "4"


async def test_an_invoice_that_already_carries_a_tax_id_is_left_alone(
    pipeline: InvoicePipeline, state: MockState, counter: MonotonicSerialCounter
) -> None:
    """A caller's own tax id is authoritative: no serial is spent and nothing is rewritten.

    Reissuing here would replace an id the caller may already have printed, and
    burn a serial for an invoice that never needed one.
    """
    mine = generate_tax_id(MEMORY_ID, 4242, datetime.now(UTC))
    invoice = make_invoice(taxid=mine, inno="MY-OWN-SERIAL")

    (submission,) = await pipeline.submit([invoice])

    assert submission.tax_id == mine
    assert counter.current == 0, "a serial was spent on an invoice that had a tax id"

    stored = state.by_uid(submission.uid)
    assert stored is not None
    header = json.loads(stored.invoice_bytes)["header"]
    assert header["taxid"] == mine
    assert header["inno"] == "MY-OWN-SERIAL", "the caller's inno was overwritten"


async def test_a_mixed_batch_only_mints_for_the_invoices_that_need_one(
    pipeline: InvoicePipeline, state: MockState, counter: MonotonicSerialCounter
) -> None:
    mine = generate_tax_id(MEMORY_ID, 999, datetime.now(UTC))
    invoices = [make_invoice(), make_invoice(taxid=mine), make_invoice()]

    submissions = await pipeline.submit(invoices)

    assert submissions[1].tax_id == mine
    assert counter.current == 2, "one serial per generated tax id, and no more"
    assert submissions[0].tax_id[SERIAL_SLICE] == invoice_serial_hex(1)
    assert submissions[2].tax_id[SERIAL_SLICE] == invoice_serial_hex(2)
    assert len({s.tax_id for s in submissions}) == 3


async def test_the_callers_invoices_are_never_mutated(pipeline: InvoicePipeline) -> None:
    """A caller retrying with the same objects must not resubmit a spent tax id."""
    invoices = [make_invoice() for _ in range(2)]

    submissions = await pipeline.submit(invoices)

    assert all(invoice.header.taxid == "" for invoice in invoices)
    assert all(invoice.header.inno is None for invoice in invoices)
    assert all(s.tax_id for s in submissions)


async def test_submissions_come_back_in_input_order(
    pipeline: InvoicePipeline, state: MockState
) -> None:
    """The API's result list need not be ordered, so the pipeline matches on uid."""
    submissions = await pipeline.submit([make_invoice() for _ in range(4)])

    serials = [int(s.tax_id[SERIAL_SLICE], 16) for s in submissions]
    assert serials == [1, 2, 3, 4]
    for submission in submissions:
        assert state.submissions[submission.reference_number].uid == submission.uid


async def test_an_empty_batch_touches_nothing(
    pipeline: InvoicePipeline,
    requests: list[httpx.Request],
    counter: MonotonicSerialCounter,
) -> None:
    assert await pipeline.submit([]) == []
    assert requests == [], "an empty batch still went to the network"
    assert counter.current == 0


# ------------------------------------------------------------- the server key


async def test_the_server_key_is_fetched_once_and_reused(
    pipeline: InvoicePipeline, state: MockState, requests: list[httpx.Request]
) -> None:
    """Every fetch burns a nonce; a per-invoice fetch would double the traffic."""
    key = await pipeline.server_key()
    assert key.id == state.key_id
    assert await pipeline.server_key() is key

    await pipeline.submit([make_invoice()])
    await pipeline.submit([make_invoice()])

    assert len(sent(requests, "GET", "server-information")) == 1
    assert len(sent(requests, "POST", "invoice")) == 2


async def test_concurrent_submits_share_one_server_key_fetch(
    pipeline: InvoicePipeline, state: MockState, requests: list[httpx.Request]
) -> None:
    """The lock exists so the loser of the race does not burn a nonce for nothing."""
    first, second = await asyncio.gather(
        pipeline.submit([make_invoice()]), pipeline.submit([make_invoice()])
    )

    assert len(sent(requests, "GET", "server-information")) == 1
    assert first[0].tax_id != second[0].tax_id
    assert len(state.submissions) == 2


# ------------------------------------------------------------------ chunking


async def test_more_than_a_thousand_invoices_go_out_in_several_requests(
    pipeline: InvoicePipeline,
    state: MockState,
    requests: list[httpx.Request],
    counter: MonotonicSerialCounter,
) -> None:
    """`POST /invoice` refuses more than 1000 packets (error 4143), and the mock enforces it.

    The full 1001 rather than a lowered constant: the boundary is the thing that
    fails in production, and a rejected batch has already spent its serials.
    """
    invoices = [make_invoice() for _ in range(MAX_PACKETS + 1)]

    submissions = await pipeline.submit(invoices)

    assert batch_sizes(requests) == [MAX_PACKETS, 1]
    assert len(submissions) == MAX_PACKETS + 1
    assert len({s.tax_id for s in submissions}) == MAX_PACKETS + 1, "a tax id repeated"
    assert counter.current == MAX_PACKETS + 1
    # Every one of them was decrypted and verified by the server, not just sent.
    assert len(state.submissions) == MAX_PACKETS + 1
    assert {s.tax_id for s in state.submissions.values()} == {s.tax_id for s in submissions}


async def test_the_cap_is_what_forces_the_split(
    client: MoadianClient, state: MockState, dev_signatory: Pkcs8Signatory
) -> None:
    """Without chunking the request would be refused — proof the split is not cosmetic."""
    information = await client.get_server_information()
    entry = information.publicKeys[0]
    encryptor = JweEncryptor(
        ServerKey(id=entry.id, key=entry.key, algorithm="RSA", purpose=1)
    )
    packet = build_packet(
        make_invoice(taxid=generate_tax_id(MEMORY_ID, 1, datetime.now(UTC))).to_wire_dict(),
        dev_signatory,
        encryptor,
        MEMORY_ID,
    )

    with pytest.raises(TaxApiError) as excinfo:
        await client.submit_invoices([packet] * (MAX_PACKETS + 1))

    assert excinfo.value.codes == ["4143"]


# ------------------------------------------------------------- await_results


async def test_await_results_waits_the_mandatory_ten_seconds_before_asking(
    pipeline: InvoicePipeline,
    client: MoadianClient,
    state: MockState,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RC_TICS requires >= 10s between submission and inquiry; sooner is a wasted nonce.

    The recorded order is the assertion: the sleep comes first, and it is ten
    seconds, not a token pause.
    """
    submissions = await pipeline.submit([make_invoice()])
    log: list[tuple[str, object]] = []
    fake_clock(monkeypatch, log)
    spy_on_inquiries(monkeypatch, client, log)

    results = await pipeline.await_results(submissions)

    assert log[0] == ("sleep", 10.0), "an inquiry went out before the mandatory wait"
    assert log[1][0] == "inquiry"
    assert [r.status for r in results] == [RequestStatus.SUCCESS]
    assert [r.referenceNumber for r in results] == [submissions[0].reference_number]


async def test_await_results_polls_until_nothing_is_in_progress(
    pipeline: InvoicePipeline,
    client: MoadianClient,
    state: MockState,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One poll is not enough: an invoice stays IN_PROGRESS until the server settles it."""
    submissions = await pipeline.submit([make_invoice() for _ in range(2)])
    set_status(state, RequestStatus.IN_PROGRESS)

    log: list[tuple[str, object]] = []
    real_sleep = asyncio.sleep
    sleeps: list[float] = []

    async def instant(delay: float, *args: object, **kwargs: object) -> None:
        sleeps.append(delay)
        log.append(("sleep", delay))
        # The second sleep is the poll interval, which only happens because the
        # first inquiry came back IN_PROGRESS. Settle the batch there so the next
        # poll is the one that ends the loop.
        if len(sleeps) == 2:
            set_status(state, RequestStatus.SUCCESS)
        await real_sleep(0)

    monkeypatch.setattr(asyncio, "sleep", instant)
    spy_on_inquiries(monkeypatch, client, log)

    results = await pipeline.await_results(submissions, min_wait=10.0, poll_interval=5.0)

    assert [entry[0] for entry in log] == ["sleep", "inquiry", "sleep", "inquiry"]
    assert sleeps == [10.0, 5.0]
    assert [r.status for r in results] == [RequestStatus.SUCCESS] * 2
    assert {r.referenceNumber for r in results} == {s.reference_number for s in submissions}


async def test_await_results_returns_the_last_poll_when_the_timeout_expires(
    pipeline: InvoicePipeline,
    client: MoadianClient,
    state: MockState,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Expiry is not a failure — the invoices are queued, and resubmitting would duplicate them."""
    submissions = await pipeline.submit([make_invoice()])
    set_status(state, RequestStatus.IN_PROGRESS)

    log: list[tuple[str, object]] = []
    fake_clock(monkeypatch, log)
    spy_on_inquiries(monkeypatch, client, log)

    results = await pipeline.await_results(submissions, min_wait=1.0, timeout=0.0)

    # One inquiry is always made, even with no time left at all.
    assert [entry[0] for entry in log] == ["sleep", "inquiry"]
    assert [r.status for r in results] == [RequestStatus.IN_PROGRESS]


async def test_await_results_asks_nothing_when_nothing_was_accepted(
    pipeline: InvoicePipeline,
    requests: list[httpx.Request],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A submission with no reference number was never accepted; there is nothing to poll."""
    log: list[tuple[str, object]] = []
    fake_clock(monkeypatch, log)
    unaccepted = [InvoiceSubmission(uid="u", tax_id="t", reference_number=None, raw=None)]

    assert await pipeline.await_results(unaccepted) == []
    assert await pipeline.await_results([]) == []
    assert log == [], "the mandatory wait was served for an empty poll"
    assert requests == []


async def test_more_than_a_hundred_references_are_inquired_in_chunks(
    pipeline: InvoicePipeline,
    client: MoadianClient,
    requests: list[httpx.Request],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`GET /inquiry-by-reference-id` refuses more than 100 ids (error 4141)."""
    submissions = [
        InvoiceSubmission(uid=f"uid-{i}", tax_id=f"tax-{i}", reference_number=f"ref-{i}", raw=None)
        for i in range(MAX_INQUIRY_IDS + 1)
    ]
    log: list[tuple[str, object]] = []
    fake_clock(monkeypatch, log)

    results = await pipeline.await_results(submissions)

    inquiries = sent(requests, "GET", "inquiry-by-reference-id")
    assert [len(r.url.params.get_list("referenceIds")) for r in inquiries] == [
        MAX_INQUIRY_IDS,
        1,
    ]
    # One result per reference, and the mock only knows references it issued.
    assert len(results) == MAX_INQUIRY_IDS + 1
    assert {r.status for r in results} == {RequestStatus.NOT_FOUND}


async def test_a_single_oversized_inquiry_is_what_the_chunking_avoids(
    client: MoadianClient,
) -> None:
    """The server-side rule the chunk size mirrors, asserted rather than assumed."""
    with pytest.raises(TaxApiError) as excinfo:
        await client.inquiry_by_reference_id([f"ref-{i}" for i in range(MAX_INQUIRY_IDS + 1)])

    assert excinfo.value.codes == ["4141"]


# ------------------------------------------------------- submit then inquire


async def test_submit_and_await_results_is_the_documented_two_step(
    pipeline: InvoicePipeline,
    client: MoadianClient,
    state: MockState,
    monkeypatch: pytest.MonkeyPatch,
    requests: list[httpx.Request],
) -> None:
    """The README's short path, run for real: submit, wait, inquire, verify.

    The mock signs its SUCCESS results with the same key it publishes through
    ``/server-information``, so a verified ``sign`` proves the result came from
    the server rather than from anything in this test.
    """
    invoices = [make_invoice() for _ in range(3)]
    submissions = await pipeline.submit(invoices)
    log: list[tuple[str, object]] = []
    fake_clock(monkeypatch, log)

    results = await pipeline.await_results(submissions)

    assert len(results) == 3
    assert all(r.status == RequestStatus.SUCCESS for r in results)
    assert all(r.fiscalId == MEMORY_ID for r in results)
    assert all(r.sign for r in results), "a SUCCESS result carries the organization's signature"
    by_reference = {r.referenceNumber: r for r in results}
    for submission in submissions:
        result = by_reference[submission.reference_number]
        assert result.uid == submission.uid
        assert result.data.success is True

    # Three invoices, one request each way: key, submission, inquiry.
    assert len(sent(requests, "POST", "invoice")) == 1
    assert len(sent(requests, "GET", "inquiry-by-reference-id")) == 1


async def test_every_authenticated_request_burned_its_own_nonce(
    pipeline: InvoicePipeline, state: MockState, requests: list[httpx.Request]
) -> None:
    """The mock rejects a replayed nonce, so a green submit already proves freshness.

    This pins *why* it stayed green: one nonce issued and consumed per protected
    call, never a cached one.
    """
    await pipeline.submit([make_invoice()])

    issued = list(state.nonces.values())
    protected = [r for r in requests if r.url.path != "/api/v2/nonce"]
    assert len(issued) == len(protected) == len(sent(requests, "GET", "nonce"))
    assert all(record.used for record in issued)
    assert len({record.nonce for record in issued}) == len(issued)


# ------------------------------------------------------ failure does not lie


async def test_a_rejected_chunk_propagates_instead_of_reporting_success(
    pipeline: InvoicePipeline,
    client: MoadianClient,
    state: MockState,
    monkeypatch: pytest.MonkeyPatch,
    counter: MonotonicSerialCounter,
) -> None:
    """Second chunk refused by the server: the error surfaces and no serial is minted for a third.

    The refusal is produced by the server (a duplicate ``requestTraceId``, error
    4163), not by an intercepted response — the pipeline is left entirely alone.
    """
    monkeypatch.setattr("moadian.pipeline.MAX_PACKETS", 1)
    real_submit = client.submit_invoices
    calls: list[int] = []

    async def submit(packets, *args, **kwargs):  # type: ignore[no-untyped-def]
        calls.append(len(packets))
        if len(calls) == 2:
            # The uid of the packet the server already accepted, replayed.
            packets = [packets[0].model_copy(deep=True)]
            packets[0].header.requestTraceId = next(iter(state.submissions.values())).uid
        return await real_submit(packets, *args, **kwargs)

    monkeypatch.setattr(client, "submit_invoices", submit)

    with pytest.raises(TaxApiError) as excinfo:
        await pipeline.submit([make_invoice() for _ in range(3)])

    assert excinfo.value.codes == ["4163"]
    assert calls == [1, 1], "the third chunk was built after the second had failed"
    assert counter.current == 2, "serials were spent on a chunk that never went out"
    assert len(state.submissions) == 1
