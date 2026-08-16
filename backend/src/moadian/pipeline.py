"""Invoices in, submissions out — the orchestration over everything else.

Submitting one invoice touches six pieces: a serial, a tax id, canonical JSON, a
JWS, a JWE, and a packet envelope. Each is correct on its own and none of them
knows about the others, so without this module every caller reassembles the same
sequence by hand and gets one step of it subtly wrong.

Nothing here changes the wire format. WIRE_FORMAT.md remains the authority.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
import threading
import time
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from moadian.client import MoadianClient, build_packet
from moadian.client.api import MAX_PACKETS
from moadian.crypto import JweEncryptor, ServerKey, Signatory
from moadian.errors import ConfigurationError, UnknownResponseError
from moadian.models import InquiryResult, Invoice, Packet, RequestStatus, SubmitResult
from moadian.rules import RuleEngine
from moadian.taxid import MAX_SERIAL, generate_tax_id, invoice_serial_hex

try:  # POSIX only; Windows has no flock and falls back to the in-process lock.
    import fcntl
except ImportError:  # pragma: no cover - not exercised on the supported platforms
    fcntl = None  # type: ignore[assignment]

__all__ = ["MAX_PACKETS", "InvoicePipeline", "InvoiceSubmission", "MonotonicSerialCounter"]

#: `GET /inquiry-by-reference-id` refuses more than 100 ids per call (error 4141).
MAX_INQUIRY_IDS = 100


@dataclass(frozen=True)
class InvoiceSubmission:
    """What is known about one invoice once `POST /invoice` has answered.

    ``uid`` is the ``requestTraceId`` we generated and the key for
    `GET /inquiry-by-uid`; ``reference_number`` is the organization's own handle
    and the key for `GET /inquiry-by-reference-id`. A ``None`` reference means
    the batch response carried no result for this uid — the invoice was never
    accepted, so there is nothing to poll for.
    """

    uid: str
    tax_id: str
    reference_number: str | None
    raw: SubmitResult | None


class MonotonicSerialCounter:
    """A persisted, never-repeating invoice serial for one fiscal memory.

    The serial is baked into the شماره منحصر به فرد مالیاتی and into ``inno``
    (WIRE_FORMAT.md "TaxId"). Reusing one produces a duplicate tax id, which the
    organization rejects and which no later request can undo — the official
    samples draw the serial from ``Random``, which collides at a rate that only
    looks small until a taxpayer issues a few thousand invoices.

    Durability here stops at one host: the value is fsynced and swapped in with
    ``os.replace``, and concurrent processes are serialised through an advisory
    lock file where the platform provides one. **A production deployment across
    more than one machine must replace this with a counter the machines share**
    — a database sequence, or an allocation service — because two hosts each
    holding their own file will happily issue the same serial.
    """

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._lock_path = self.path.with_name(self.path.name + ".lock")
        # flock guards against other processes; this guards against other threads
        # in ours, which would otherwise interleave inside one lock acquisition.
        self._thread_lock = threading.Lock()

    def __call__(self) -> int:
        """Return the next serial. The first call on a fresh file returns 1."""
        with self._thread_lock, self._exclusive():
            serial = self._read() + 1
            if serial > MAX_SERIAL:
                raise ConfigurationError(
                    f"serial counter {self.path} is exhausted: {serial} exceeds the "
                    f"10 hex digits the tax id allows ({MAX_SERIAL})"
                )
            self._write(serial)
            return serial

    @property
    def current(self) -> int:
        """The last serial issued, or 0 if none has been. Does not consume one."""
        with self._thread_lock, self._exclusive():
            return self._read()

    @contextmanager
    def _exclusive(self) -> Iterator[None]:
        """Hold an exclusive advisory lock on a sidecar file.

        The lock lives beside the value rather than on it because the value file
        is replaced by rename on every write, and a lock held on the replaced
        inode protects nothing.
        """
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if fcntl is None:
            yield
            return
        with open(self._lock_path, "a+b") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def _read(self) -> int:
        try:
            raw = self.path.read_text(encoding="ascii").strip()
        except FileNotFoundError:
            return 0
        except OSError as exc:
            raise ConfigurationError(f"serial counter {self.path} is unreadable: {exc}") from exc
        try:
            value = int(raw)
        except ValueError as exc:
            # Restarting from zero here would reissue serials that are already on
            # invoices the organization has accepted. Refuse instead.
            raise ConfigurationError(
                f"serial counter {self.path} holds {raw!r}, which is not an integer"
            ) from exc
        if value < 0:
            raise ConfigurationError(f"serial counter {self.path} holds a negative value {value}")
        return value

    def _write(self, serial: int) -> None:
        """Write through a temp file in the same directory, fsync, then rename."""
        fd, tmp_name = tempfile.mkstemp(dir=self.path.parent, prefix=f".{self.path.name}.")
        try:
            with os.fdopen(fd, "w", encoding="ascii") as handle:
                handle.write(f"{serial}\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_name, self.path)
            # Without this the rename itself can be lost on power failure, which
            # would hand the next process a serial it has already issued.
            dir_fd = os.open(self.path.parent, os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        except BaseException:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)
            raise


class InvoicePipeline:
    """Canonicalise, sign, encrypt, submit, and poll — for one fiscal memory."""

    def __init__(
        self,
        client: MoadianClient,
        signatory: Signatory,
        memory_id: str,
        serial_source: Callable[[], int],
        rules: RuleEngine | None = None,
        validate: bool = True,
    ) -> None:
        self._client = client
        self._signatory = signatory
        self._memory_id = memory_id
        self._serial_source = serial_source
        # Validation runs before a serial is drawn, because a serial spent on an
        # invoice the organization will refuse cannot be reused. Pass
        # validate=False only to submit something deliberately malformed — which
        # is a thing the mock tests need and production never does.
        self._validate = validate
        self._rules = rules or RuleEngine()
        self._server_key: ServerKey | None = None
        # submit() may be awaited concurrently; without this, two callers each
        # fetch a key and burn a nonce for the one that loses.
        self._server_key_lock = asyncio.Lock()

    @property
    def memory_id(self) -> str:
        """The شناسه یکتای حافظه مالیاتی sent as ``fiscalId`` and used in every tax id."""
        return self._memory_id

    async def server_key(self) -> ServerKey:
        """The public key invoices are encrypted to, fetched once and kept.

        The .NET SDK refreshes hourly; a pipeline instance is the shorter-lived
        thing, so it caches for its own lifetime. Build a new pipeline to pick
        up a rotated key.
        """
        async with self._server_key_lock:
            if self._server_key is None:
                information = await self._client.get_server_information()
                if not information.publicKeys:
                    raise UnknownResponseError(
                        "GET /server-information returned no public keys; "
                        "invoices cannot be encrypted"
                    )
                # Any of them may be used, so take the first and record the kid.
                chosen = information.publicKeys[0]
                self._server_key = ServerKey(
                    id=chosen.id,
                    key=chosen.key,
                    algorithm=chosen.algorithm or "RSA",
                    purpose=chosen.purpose if chosen.purpose is not None else 1,
                )
            return self._server_key

    async def submit(self, invoices: list[Invoice]) -> list[InvoiceSubmission]:
        """Submit invoices and return one result per input, in order.

        An invoice whose ``header.taxid`` is empty gets one generated from the
        fiscal memory, the next serial, and its own ``indatim``; ``inno`` is set
        from the same serial so the two always agree. Inputs are never mutated —
        a caller retrying keeps their own objects — so the assigned tax id comes
        back on the :class:`InvoiceSubmission`.

        More than :data:`MAX_PACKETS` invoices go out as several requests: one
        oversized request is rejected wholesale (error 4143) *after* every serial
        and tax id in it has been spent, and a spent serial cannot be reclaimed.
        Identities are therefore minted one chunk at a time, immediately before
        that chunk is sent. If a later chunk fails, the exception propagates and
        the results of the chunks already accepted are lost with it — inquire by
        time for those, and never resubmit them.
        """
        if not invoices:
            return []

        encryptor = JweEncryptor(await self.server_key())
        submissions: list[InvoiceSubmission] = []
        for start in range(0, len(invoices), MAX_PACKETS):
            chunk = invoices[start : start + MAX_PACKETS]
            submissions += await self._submit_batch(chunk, encryptor)
        return submissions

    async def await_results(
        self,
        submissions: Sequence[InvoiceSubmission],
        *,
        min_wait: float = 10.0,
        poll_interval: float = 5.0,
        timeout: float = 120.0,
    ) -> list[InquiryResult]:
        """Wait out the mandatory delay, then poll until nothing is `IN_PROGRESS`.

        RC_TICS requires at least ten seconds between submission and inquiry
        (WIRE_FORMAT.md "Submission envelope"); asking sooner returns
        `IN_PROGRESS` and burns a nonce for nothing. ``timeout`` covers the whole
        call, ``min_wait`` included, and at least one inquiry is always made.

        On expiry the last poll is returned as it stands. That is not a failure:
        the invoices are still queued, and the correct response is to inquire
        again later, never to resubmit. Results come back in the order the API
        listed them — match them to submissions on ``referenceNumber``.
        """
        references = [s.reference_number for s in submissions if s.reference_number]
        if not references:
            return []

        deadline = time.monotonic() + timeout
        await asyncio.sleep(min_wait)

        while True:
            results = await self._inquire(references)
            if not any(result.status == RequestStatus.IN_PROGRESS for result in results):
                return results
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return results
            await asyncio.sleep(min(poll_interval, remaining))

    # ------------------------------------------------------------------ internals

    async def _submit_batch(
        self, invoices: Sequence[Invoice], encryptor: JweEncryptor
    ) -> list[InvoiceSubmission]:
        """Build, send, and match up one request's worth of invoices."""
        # An RSA signature and a JWE per invoice, plus a locked read-write-fsync
        # of the serial file: hundreds of milliseconds of pure CPU and blocking
        # I/O for a large batch, and none of it awaits. On the event loop it
        # stalls every co-scheduled task for the whole build, so it goes to a
        # worker thread — once for the batch, not once per invoice.
        packets, identities = await asyncio.to_thread(self._build_packets, invoices, encryptor)

        response = await self._client.submit_invoices(packets)
        # The API answers with a flat list that need not be in request order, so
        # match on the uid we chose rather than on position.
        by_uid = {result.uid: result for result in response.result}

        submissions = []
        for uid, tax_id in identities:
            result = by_uid.get(uid)
            submissions.append(
                InvoiceSubmission(
                    uid=uid,
                    tax_id=tax_id,
                    reference_number=result.referenceNumber if result else None,
                    raw=result,
                )
            )
        return submissions

    def _build_packets(
        self, invoices: Sequence[Invoice], encryptor: JweEncryptor
    ) -> tuple[list[Packet], list[tuple[str, str]]]:
        """Sign and encrypt a batch, in input order. Runs on a worker thread.

        Nothing here awaits, and the serial counter is guarded by a thread lock
        and an flock, so it is safe off the loop thread.
        """
        packets: list[Packet] = []
        identities: list[tuple[str, str]] = []
        for invoice in invoices:
            # Before _with_identity, deliberately: that call draws a serial, and
            # a serial is only monotonic if it is never wasted.
            if self._validate:
                self._rules.validate(invoice).raise_if_invalid()
            complete = self._with_identity(invoice)
            uid = str(uuid4())
            packets.append(
                build_packet(
                    complete.to_wire_dict(),
                    self._signatory,
                    encryptor,
                    self._memory_id,
                    uid,
                )
            )
            identities.append((uid, complete.header.taxid))
        return packets, identities

    def _with_identity(self, invoice: Invoice) -> Invoice:
        """Return a copy carrying a tax id, generating one if the caller left it blank."""
        if invoice.header.taxid:
            return invoice

        serial = self._serial_source()
        # indatim is epoch milliseconds; generate_tax_id re-anchors to Asia/Tehran,
        # which is where the day_range must be computed regardless of host tz.
        issued_at = datetime.fromtimestamp(invoice.header.indatim / 1000, tz=UTC)

        complete = invoice.model_copy(deep=True)
        complete.header.taxid = generate_tax_id(self._memory_id, serial, issued_at)
        complete.header.inno = invoice_serial_hex(serial)
        return complete

    async def _inquire(self, references: Sequence[str]) -> list[InquiryResult]:
        """One inquiry per 100 references — more than that is error 4141."""
        results: list[InquiryResult] = []
        for start in range(0, len(references), MAX_INQUIRY_IDS):
            chunk = references[start : start + MAX_INQUIRY_IDS]
            results += await self._client.inquiry_by_reference_id(chunk)
        return results
