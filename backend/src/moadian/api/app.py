"""The HTTP surface: profiles, reference data, invoices, and inquiry.

Read the warning in :mod:`moadian.api.deps` before exposing this anywhere.

Design notes worth stating once:

* **Key material never crosses this boundary.** Profiles go out through
  :meth:`Profile.redacted`, which carries the certificate's subject and expiry
  but no PEM. There is no endpoint that returns a private key, by construction.
* **Environment is chosen by picking a profile, not by a query parameter.** A
  شناسه یکتای حافظه مالیاتی belongs to one environment, so letting a caller name
  an environment separately would let a sandbox identity address production.
* **Nothing is submitted without passing the rule engine.** ``/verify`` and
  ``/submit`` run the same checks; submit refuses on error rather than spending a
  serial the organization will reject.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

from fastapi import Body, Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from moadian.auth import UserStore, auth_router, current_user, seed_users, users_router
from moadian.auth.security import admin_user
from moadian.auth.security import configure as configure_auth
from moadian.client import MoadianClient
from moadian.config import Environment, Profile, ProfileStore, Settings
from moadian.config.keyring import set_passphrase as set_key_passphrase
from moadian.errors import (
    ConfigurationError,
    CryptographyError,
    InvoiceValidationError,
    MoadianError,
    TaxApiError,
    TransportError,
)
from moadian.models import InquiryResult, Invoice, RequestStatus
from moadian.pipeline import MAX_INQUIRY_IDS, InvoicePipeline, MonotonicSerialCounter
from moadian.rules import RuleEngine, load_rules, recompute
from moadian.store import Buyer, GoodsService, InvoiceRecord, InvoiceState, RecordStore

from .deps import (
    ActiveProfile,
    get_profile_store,
    get_record_store,
    get_rule_engine,
    get_settings,
)

# ``app`` is deliberately absent: it exists only through the module
# ``__getattr__`` at the bottom of this file, and naming a lazy attribute here
# would be a name no static reader can resolve.
__all__ = ["create_app"]

_log = logging.getLogger(__name__)

# Applied to every route rather than repeated inline: this API signs and submits
# tax invoices, so "authenticated by default" has to be the shape of the file.
AUTHENTICATED = [Depends(current_user)]
ADMIN_ONLY = [Depends(admin_user)]


# ------------------------------------------------------------------ schemas


class ProfileIn(BaseModel):
    """A new profile.

    Carries **no key material and no path to any**. Which certificate signs for
    this profile follows from its environment, resolved against the server's own
    configuration. There is deliberately no field here — not a PEM, not a
    filename, not a path — that could influence which file is read.
    """

    name: str
    memory_id: str = Field(description="شناسه یکتای حافظه مالیاتی, 6 chars of A-Z0-9")
    environment: str = Field(description="sandbox | production (also tp, operational)")
    economic_code: str | None = None
    base_url_override: str | None = Field(
        default=None, description="Testing only — points at a mock instead of the real service"
    )


class BuyerIn(BaseModel):
    name: str
    national_id: str
    economic_code: str | None = None
    person_type: int = 2
    postal_code: str | None = None
    branch_code: str | None = None
    note: str | None = None


class GoodsIn(BaseModel):
    stuff_id: str
    description: str
    unit: str | None = None
    vat_rate: float | None = None
    default_fee: float | None = None
    is_default: bool = False


class PaymentIn(BaseModel):
    """ارسال پرداخت صورتحساب — RC_TICS §11."""

    taxid: str
    # Whole rials. RC_IITP types money with "حداکثر تعداد رقم اعشار ۰", and the
    # service rejects a fractional amount outright (error 4147).
    paidAmount: int
    paymentDate: int | None = None
    paymentMethod: str = "CASH"
    terminalNumber: str | None = None
    referenceNumber: str | None = None


class InvoiceIn(BaseModel):
    invoice: Invoice
    #: Persist as a draft even when it fails validation, so work is not lost.
    save: bool = True


# ------------------------------------------------------------------ helpers


def _client_for(profile: Profile, settings: Settings) -> MoadianClient:
    return MoadianClient.from_profile(profile, settings=settings)


def _report_signing_material(settings: Settings) -> None:
    """Check every configured certificate/key pair once, at startup, and log it.

    The same check the admin panel runs, at the one moment nobody is watching the
    panel. A mismatched pair signs cleanly and is rejected by the organization,
    so the failure otherwise surfaces on a real submission with a serial already
    spent. Logged rather than raised: a broken sandbox pair must not stop a
    server whose production pair is fine, and the operator may be starting the
    application precisely in order to fix it.

    Distinct pairs only. Both environments fall back to the same
    MOADIAN_CERTIFICATE_PATH by default, and one warning about one file is the
    honest count.
    """
    seen: set[tuple[str | None, str | None]] = set()
    for environment in Environment:
        material = settings.signing_material(environment)
        key = (
            str(material.certificate_path) if material.certificate_path else None,
            str(material.private_key_path) if material.private_key_path else None,
        )
        if key in seen:
            continue
        seen.add(key)
        report = material.verify()
        if report["ok"]:
            _log.info("signing material for %s: %s", environment, report["message"])
        elif report["matches"] is False:
            # The one failure that is silent everywhere else.
            _log.error(
                "signing material for %s: the private key does not match the "
                "certificate (%s vs %s). Invoices will be signed and rejected.",
                environment,
                key[0],
                key[1],
            )
        else:
            _log.warning("signing material for %s: %s", environment, report["message"])


#: The only two inquiry statuses that are a verdict.
#:
#: ``IN_PROGRESS`` is the ordinary answer for the first stretch after submission.
#: ``TIMEOUT`` and ``NOT_FOUND`` mean the organization has not answered — not
#: that it answered no — and RC_TICS §8 is explicit that the response to either
#: is to inquire again later, never to resubmit. Moving a record out of ``SENT``
#: on any of the three would tell the operator a queued invoice was finished.
_VERDICTS: dict[str, str] = {
    RequestStatus.SUCCESS: InvoiceState.CONFIRMED,
    RequestStatus.FAILED: InvoiceState.REJECTED,
}


def _inquiry_block(result: InquiryResult) -> dict[str, Any]:
    """The organization's answer about one submission, flattened for storage.

    Stored under ``detail["inquiry"]`` rather than replacing ``detail``: that key
    holds our own اعتبارسنجی report, and an operator comparing what we predicted
    against what the organization said needs both. ``data`` is ``{}`` until the
    packet has been processed, so the error lists are normally empty.
    """
    data: Any = result.data
    if hasattr(data, "model_dump"):
        data = data.model_dump(exclude_none=True)
    if not isinstance(data, dict):
        data = {}
    status = result.status.value if isinstance(result.status, RequestStatus) else result.status
    return {
        "status": status,
        "checkedAt": datetime.now(UTC).isoformat(timespec="seconds"),
        "referenceNumber": result.referenceNumber,
        "uid": result.uid,
        # Named `error`/`warning` on the wire, singular. Pluralised here to match
        # the verification report beside it, so the UI renders one shape.
        "errors": list(data.get("error") or []),
        "warnings": list(data.get("warning") or []),
    }


def _apply_cancellation(
    record: InvoiceRecord, profile: Profile, store: RecordStore
) -> str | None:
    """Mark the invoice a confirmed ابطالی voids, and return its tax id.

    An ابطالی is not its own API call — it is an ordinary invoice carrying
    ``ins=3`` and the voided invoice's شماره منحصر به فرد مالیاتی in ``irtaxid``
    (RC_IITP §5-3). So the only moment the original can be known to be void is
    when the ابطالی itself is confirmed, which is here.
    """
    header = record.payload.get("header") or {}
    if header.get("ins") != 3:
        return None
    reference = header.get("irtaxid")
    if not reference:
        return None
    target = store.find_by_tax_id(profile.name, str(reference))
    if target is None or target.id == record.id or target.state == InvoiceState.CANCELLED:
        return None
    target.state = InvoiceState.CANCELLED
    detail = dict(target.detail or {})
    detail["cancelledBy"] = {
        "id": record.id,
        "taxId": record.tax_id,
        "at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    target.detail = detail
    store.save_invoice(target)
    return str(reference)


async def _reconcile(
    records: list[InvoiceRecord],
    profile: Profile,
    settings: Settings,
    store: RecordStore,
) -> dict[str, Any]:
    """Inquire on accepted submissions and write the verdicts back.

    The second half of filing an invoice. `POST /invoice` only says the packet
    was *accepted*; the organization validates asynchronously and the outcome
    exists nowhere until `GET /inquiry-by-reference-id` is asked for it. Without
    this, every invoice stays ``SENT`` forever and a rejection is invisible.

    Batched at :data:`MAX_INQUIRY_IDS` per request — more is error 4141 — and
    matched on ``referenceNumber`` because the response need not be in order.
    """
    pending = [r for r in records if r.reference_number]
    if not pending:
        return {"checked": 0, "updated": 0, "records": []}

    by_reference: dict[str, InquiryResult] = {}
    async with _client_for(profile, settings) as client:
        for start in range(0, len(pending), MAX_INQUIRY_IDS):
            chunk = pending[start : start + MAX_INQUIRY_IDS]
            results = await client.inquiry_by_reference_id(
                [str(r.reference_number) for r in chunk]
            )
            for result in results:
                if result.referenceNumber:
                    by_reference[result.referenceNumber] = result

    reported: list[dict[str, Any]] = []
    updated = 0
    for record in pending:
        result = by_reference.get(str(record.reference_number))
        if result is None:
            # Asked about, not answered about. Left exactly as it was.
            continue
        block = _inquiry_block(result)
        previous = record.state
        detail = dict(record.detail or {})
        detail["inquiry"] = block
        record.detail = detail
        verdict = _VERDICTS.get(block["status"] or "")
        if verdict:
            record.state = verdict
        store.save_invoice(record)
        cancelled = (
            _apply_cancellation(record, profile, store)
            if record.state == InvoiceState.CONFIRMED
            else None
        )
        if record.state != previous:
            updated += 1
        reported.append(
            {
                "id": record.id,
                "taxId": record.tax_id,
                "referenceNumber": record.reference_number,
                "previousState": previous,
                "state": record.state,
                "inquiry": block,
                "cancelledTaxId": cancelled,
            }
        )
    return {"checked": len(pending), "updated": updated, "records": reported}


def _pipeline_for(
    profile: Profile, client: MoadianClient, settings: Settings, engine: RuleEngine
) -> InvoicePipeline:
    counter = MonotonicSerialCounter(settings.serial_counter_path(profile.memory_id))
    return InvoicePipeline(
        client,
        client.signatory,
        profile.memory_id,
        counter,
        rules=engine,
    )


def create_app(
    *,
    cors_origins: list[str] | None = None,
    users: UserStore | None = None,
) -> FastAPI:
    app = FastAPI(
        title="Moadian",
        description="صدور و ارسال صورتحساب الکترونیکی — سامانه مودیان",
        version="0.1.0",
    )

    # The UI is served separately in development, so the dev origin needs to be
    # allowed explicitly. Defaults to Vite's port and nothing else — a wildcard
    # here would let any page in the browser drive an invoice-signing API.
    # Accounts live beside the invoice records but in their own database — see
    # moadian.auth.store for why. Seeded so a fresh install has a way in.
    settings = get_settings()
    # pydantic-settings parses .env into this object and never into os.environ,
    # so anything reading the environment directly would silently ignore the
    # file. Hand the loaded values to the modules that need them instead.
    configure_auth(settings)
    set_key_passphrase(settings.key_passphrase)
    _report_signing_material(settings)
    app.state.users = users or UserStore(Path(settings.instance_dir) / "users.sqlite")
    seed_users(app.state.users)

    app.include_router(auth_router)
    app.include_router(users_router)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins or ["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(InvoiceValidationError)
    async def _validation_error(_request, exc: InvoiceValidationError):
        from fastapi.responses import JSONResponse

        return JSONResponse(
            status_code=422,
            content={"detail": str(exc), "fields": exc.fields},
        )

    @app.exception_handler(TaxApiError)
    async def _api_error(_request, exc: TaxApiError):
        from fastapi.responses import JSONResponse

        return JSONResponse(
            status_code=502,
            content={
                "detail": str(exc),
                "codes": list(exc.codes),
                "statusCode": exc.status_code,
                "requestTraceId": exc.request_trace_id,
            },
        )

    @app.exception_handler(TransportError)
    async def _transport_error(_request, exc: TransportError):
        from fastapi.responses import JSONResponse

        return JSONResponse(
            status_code=504,
            content={"detail": f"سامانه مودیان در دسترس نیست: {exc}"},
        )

    @app.exception_handler(ConfigurationError)
    async def _config_error(_request, exc: ConfigurationError):
        from fastapi.responses import JSONResponse

        return JSONResponse(status_code=400, content={"detail": str(exc)})

    @app.exception_handler(CryptographyError)
    async def _crypto_error(_request, exc: CryptographyError):
        """An unusable certificate or key is operator configuration, not a bug.

        Reported as 400 with the reason — an expired certificate or a key that
        does not match its certificate is something the admin panel must show,
        not a 500 that reads as "the server is broken".
        """
        from fastapi.responses import JSONResponse

        return JSONResponse(status_code=400, content={"detail": str(exc)})

    # -- metadata: what the UI needs to build its forms -------------------

    @app.get("/api/environments", tags=["metadata"], dependencies=AUTHENTICATED)
    def environments() -> list[dict[str, Any]]:
        """The two deployments, for the environment switcher."""
        return [
            {
                "value": str(env),
                "label": env.label,
                "host": env.host,
                "baseUrl": env.base_url,
                "isProduction": env.is_production,
            }
            for env in Environment
        ]

    @app.get("/api/patterns", tags=["metadata"], dependencies=AUTHENTICATED)
    def patterns() -> list[dict[str, Any]]:
        """الگوهای صورتحساب, with the invoice types each supports."""
        rules = load_rules()
        return [
            {
                "number": spec.number,
                "name": spec.name,
                "nameEn": spec.name_en,
                "types": list(spec.types),
                "coverage": spec.coverage,
            }
            for spec in sorted(rules.patterns.values(), key=lambda s: s.number)
        ]

    @app.get("/api/patterns/{number}/fields", tags=["metadata"], dependencies=AUTHENTICATED)
    def pattern_fields(number: int, invoice_type: int = Query(1, alias="type")):
        """Per-field obligations and Persian labels — the entry form is a projection of this.

        Returning the matrix instead of hard-coding requiredness in the UI keeps
        one source of truth: a correction to جدول ۱ changes the form without a
        frontend release.
        """
        spec = load_rules().pattern(number)
        if spec is None:
            raise HTTPException(status_code=404, detail=f"الگوی {number} تعریف نشده است")
        out: dict[str, list[dict[str, Any]]] = {}
        for section in ("header", "body", "payment"):
            out[section] = [
                {
                    "field": rule.name,
                    "title": rule.title,
                    "obligation": str(rule.for_type(invoice_type)),
                    "condition": rule.when,
                    "reference": rule.reference,
                }
                for rule in spec.section(section).values()
            ]
        return {"pattern": spec.number, "name": spec.name, "type": invoice_type, "sections": out}

    # -- profiles ---------------------------------------------------------

    @app.get("/api/profiles", tags=["admin"], dependencies=AUTHENTICATED)
    def list_profiles(
        store: Annotated[ProfileStore, Depends(get_profile_store)],
        settings: Annotated[Settings, Depends(get_settings)],
    ):
        """Every configured fiscal memory. Redacted — no key material leaves here."""
        return [store.load(name).redacted(settings) for name in store.list_names()]

    @app.post("/api/profiles", status_code=201, tags=["admin"], dependencies=ADMIN_ONLY)
    def create_profile(
        body: ProfileIn,
        store: Annotated[ProfileStore, Depends(get_profile_store)],
        settings: Annotated[Settings, Depends(get_settings)],
    ):
        profile = Profile(
            name=body.name,
            memory_id=body.memory_id,
            environment=Environment.parse(body.environment),
            economic_code=body.economic_code,
            base_url_override=body.base_url_override,
        )
        profile.validate()
        # Prove the configured pair exists and matches before storing the
        # profile. Otherwise the first failure surfaces at submission time, which
        # is the worst moment to discover the server was misconfigured.
        profile.load_credentials(settings)
        store.save(profile)
        return profile.redacted(settings)

    @app.get("/api/profiles/{name}", tags=["admin"], dependencies=AUTHENTICATED)
    def read_profile(
        profile: ActiveProfile,
        settings: Annotated[Settings, Depends(get_settings)],
    ):
        return profile.redacted(settings)

    @app.get("/api/signing-material", tags=["admin"], dependencies=ADMIN_ONLY)
    def signing_material(settings: Annotated[Settings, Depends(get_settings)]):
        """Whether each environment's configured certificate and key are usable.

        Read-only status: which path is in force, whether it exists, its file
        mode, and whether the key is group- or world-readable. Contents are never
        read, and there is nothing here to change — signing material is set in
        the server's environment, not through this API.
        """
        return [settings.signing_material(env).describe() for env in Environment]

    @app.get("/api/signing-material/verify", tags=["admin"], dependencies=ADMIN_ONLY)
    def verify_signing_material(settings: Annotated[Settings, Depends(get_settings)]):
        """Does each environment's private key actually belong to its certificate?

        The check `/api/signing-material` cannot make: it reads both files, pulls
        the public key out of the certificate, and compares it with the public
        half of the private key. A mismatch is invisible until the organization
        rejects a signature — by which point a serial has been spent on an
        invoice that will never register.

        A GET because it changes nothing and the UI runs it on load as well as
        on the button. No key material is in the response; see
        :meth:`SigningMaterial.verify`.
        """
        return [settings.signing_material(env).verify() for env in Environment]

    @app.delete("/api/profiles/{name}", status_code=204, tags=["admin"], dependencies=ADMIN_ONLY)
    def delete_profile(name: str, store: Annotated[ProfileStore, Depends(get_profile_store)]):
        store.delete(name)

    @app.post("/api/profiles/{name}/test-connection", tags=["admin"], dependencies=ADMIN_ONLY)
    async def test_connection(
        profile: ActiveProfile,
        settings: Annotated[Settings, Depends(get_settings)],
    ):
        """Prove this profile can actually reach and authenticate to its environment.

        Two steps, reported separately: the unauthenticated nonce (which proves
        routing and TLS) and one authenticated call (which proves the certificate
        is accepted). A self-signed certificate passes the first and fails the
        second, and the operator needs to see which.
        """
        result: dict[str, Any] = {
            "profile": profile.name,
            "environment": str(profile.environment),
            "baseUrl": profile.base_url,
        }
        async with _client_for(profile, settings) as client:
            try:
                nonce = await client.get_nonce()
                result["nonce"] = {"ok": True, "expDate": nonce.expDate}
            except MoadianError as exc:
                result["nonce"] = {"ok": False, "error": str(exc)}
                result["authenticated"] = {"ok": False, "error": "skipped — no nonce"}
                return result
            try:
                info = await client.get_server_information()
                result["authenticated"] = {"ok": True, "serverKeys": len(info.publicKeys)}
            except TaxApiError as exc:
                result["authenticated"] = {
                    "ok": False,
                    "error": str(exc),
                    "codes": list(exc.codes),
                }
            except MoadianError as exc:
                result["authenticated"] = {"ok": False, "error": str(exc)}
        return result

    # -- reference data ---------------------------------------------------
    #
    # Not under /api/profiles/{name}. A خریدار is identified by a nationally
    # issued شناسه ملی and a کالا/خدمت by a nationally issued شناسه کالا/خدمت;
    # neither changes meaning between sandbox and production, so scoping them to
    # a fiscal memory only forced the same address book to be typed twice — and,
    # worse, put both catalogues behind a شناسه یکتای حافظه مالیاتی that a new
    # taxpayer does not have yet. Building them up is exactly what there is to do
    # while waiting for one.

    @app.get("/api/buyers", tags=["reference"], dependencies=AUTHENTICATED)
    def list_buyers(store: Annotated[RecordStore, Depends(get_record_store)]):
        return store.list_buyers()

    @app.post("/api/buyers", status_code=201, tags=["reference"], dependencies=AUTHENTICATED)
    def add_buyer(
        body: BuyerIn,
        store: Annotated[RecordStore, Depends(get_record_store)],
    ):
        return store.add_buyer(Buyer(**body.model_dump()))

    @app.delete(
        "/api/buyers/{buyer_id}",
        status_code=204,
        tags=["reference"],
        dependencies=AUTHENTICATED,
    )
    def delete_buyer(
        buyer_id: int,
        store: Annotated[RecordStore, Depends(get_record_store)],
    ):
        store.delete_buyer(buyer_id)

    @app.get("/api/goods", tags=["reference"], dependencies=AUTHENTICATED)
    def list_goods(store: Annotated[RecordStore, Depends(get_record_store)]):
        return store.list_goods()

    @app.post("/api/goods", status_code=201, tags=["reference"], dependencies=AUTHENTICATED)
    def add_goods(
        body: GoodsIn,
        store: Annotated[RecordStore, Depends(get_record_store)],
    ):
        return store.add_goods(GoodsService(**body.model_dump()))

    @app.post("/api/goods/{goods_id}/default", tags=["reference"], dependencies=AUTHENTICATED)
    def make_default(
        goods_id: int,
        store: Annotated[RecordStore, Depends(get_record_store)],
    ):
        store.set_default_goods(goods_id)
        return {"ok": True}

    @app.delete(
        "/api/goods/{goods_id}",
        status_code=204,
        tags=["reference"],
        dependencies=AUTHENTICATED,
    )
    def delete_goods(
        goods_id: int,
        store: Annotated[RecordStore, Depends(get_record_store)],
    ):
        store.delete_goods(goods_id)

    # -- invoices ---------------------------------------------------------

    @app.post("/api/profiles/{name}/invoices/verify", tags=["invoices"], dependencies=AUTHENTICATED)
    def verify_invoice(
        profile: ActiveProfile,
        invoice: Annotated[Invoice, Body(embed=True)],
        engine: Annotated[RuleEngine, Depends(get_rule_engine)],
    ):
        """اعتبارسنجی — every rule we can check offline, before anything is sent."""
        return engine.verify(invoice).as_dict()

    @app.post(
        "/api/profiles/{name}/invoices/recompute",
        tags=["invoices"],
        dependencies=AUTHENTICATED,
    )
    def recompute_invoice(
        profile: ActiveProfile,
        invoice: Annotated[Invoice, Body(embed=True)],
    ):
        """Fill in every derived money field from quantity, price, discount and rate."""
        pattern = invoice.header.inp or 1
        return recompute(invoice, pattern).to_wire_dict()

    @app.get("/api/profiles/{name}/invoices", tags=["invoices"], dependencies=AUTHENTICATED)
    def list_invoices(
        profile: ActiveProfile,
        store: Annotated[RecordStore, Depends(get_record_store)],
        state: str | None = None,
        limit: int = 100,
    ):
        return store.list_invoices(profile.name, state=state, limit=limit)

    @app.post(
        "/api/profiles/{name}/invoices",
        status_code=201,
        tags=["invoices"],
        dependencies=AUTHENTICATED,
    )
    def save_invoice(
        profile: ActiveProfile,
        body: InvoiceIn,
        store: Annotated[RecordStore, Depends(get_record_store)],
        engine: Annotated[RuleEngine, Depends(get_rule_engine)],
    ):
        """Save a draft. Validation is reported but does not block saving.

        A half-finished invoice is the normal state of one being typed; refusing
        to store it would lose the operator's work at exactly the wrong moment.
        """
        report = engine.verify(body.invoice)
        record = InvoiceRecord(
            profile=profile.name,
            state=InvoiceState.DRAFT if report.ok else InvoiceState.INVALID,
            payload=body.invoice.to_wire_dict(),
            tax_id=body.invoice.header.taxid or None,
            detail=report.as_dict(),
        )
        store.save_invoice(record)
        return {"id": record.id, "state": record.state, "verification": report.as_dict()}

    @app.post("/api/profiles/{name}/invoices/submit", tags=["invoices"], dependencies=AUTHENTICATED)
    async def submit_invoice(
        profile: ActiveProfile,
        body: InvoiceIn,
        settings: Annotated[Settings, Depends(get_settings)],
        store: Annotated[RecordStore, Depends(get_record_store)],
        engine: Annotated[RuleEngine, Depends(get_rule_engine)],
    ):
        """Validate, sign, encrypt and send. Refuses on any rule error.

        The refusal happens before a serial is drawn — see
        :class:`~moadian.pipeline.InvoicePipeline`.
        """
        report = engine.verify(body.invoice)
        if not report.ok:
            record = InvoiceRecord(
                profile=profile.name,
                state=InvoiceState.INVALID,
                payload=body.invoice.to_wire_dict(),
                detail=report.as_dict(),
            )
            store.save_invoice(record)
            raise HTTPException(status_code=422, detail=report.as_dict())

        async with _client_for(profile, settings) as client:
            pipeline = _pipeline_for(profile, client, settings, engine)
            submissions = await pipeline.submit([body.invoice])

        submission = submissions[0]
        record = InvoiceRecord(
            profile=profile.name,
            state=InvoiceState.SENT,
            payload=body.invoice.to_wire_dict(),
            tax_id=submission.tax_id,
            uid=submission.uid,
            reference_number=submission.reference_number,
            detail=report.as_dict(),
        )
        store.save_invoice(record)
        return {
            "id": record.id,
            "state": record.state,
            "taxId": submission.tax_id,
            "uid": submission.uid,
            "referenceNumber": submission.reference_number,
        }

    @app.post(
        "/api/profiles/{name}/invoices/inquire",
        tags=["invoices"],
        dependencies=AUTHENTICATED,
    )
    async def inquire_pending(
        profile: ActiveProfile,
        settings: Annotated[Settings, Depends(get_settings)],
        store: Annotated[RecordStore, Depends(get_record_store)],
        limit: int = 500,
    ):
        """استعلام وضعیت — ask about every invoice still awaiting a verdict.

        The companion to ``/submit``. Submission ends at ``SENT``; this is what
        turns that into ``CONFIRMED`` or ``REJECTED``.

        Safe to call as often as the operator likes, but not sooner than ten
        seconds after a submission (RC_TICS §8) — before that the answer is
        ``IN_PROGRESS`` and the nonce is spent for nothing.
        """
        return await _reconcile(store.list_awaiting_inquiry(profile.name, limit), profile,
                                settings, store)

    @app.post(
        "/api/profiles/{name}/invoices/{invoice_id}/inquire",
        tags=["invoices"],
        dependencies=AUTHENTICATED,
    )
    async def inquire_one(
        profile: ActiveProfile,
        invoice_id: int,
        settings: Annotated[Settings, Depends(get_settings)],
        store: Annotated[RecordStore, Depends(get_record_store)],
    ):
        """استعلام وضعیت for a single record."""
        record = store.get_invoice(invoice_id)
        if record is None or record.profile != profile.name:
            raise HTTPException(404, "صورتحساب یافت نشد")
        if not record.reference_number:
            raise HTTPException(
                400,
                "این صورتحساب شماره پیگیری ندارد؛ تنها صورتحساب پذیرفته‌شده قابل استعلام است.",
            )
        outcome = await _reconcile([record], profile, settings, store)
        if not outcome["records"]:
            raise HTTPException(502, "سامانه پاسخی برای این شماره پیگیری بازنگرداند.")
        return outcome["records"][0]

    @app.post(
        "/api/profiles/{name}/invoices/{invoice_id}/referring",
        tags=["invoices"],
        dependencies=AUTHENTICATED,
    )
    def referring_invoice(
        profile: ActiveProfile,
        invoice_id: int,
        subject: int,
        store: Annotated[RecordStore, Depends(get_record_store)],
    ):
        """Prefill an اصلاحی / ابطالی / برگشت از فروش against an existing invoice.

        None of these is a separate API call: RC_IITP §5 defines them as ordinary
        invoices carrying ``ins`` and the reference's شماره منحصر به فرد مالیاتی in
        ``irtaxid``. What an operator needs is the *draft*, correctly seeded — it
        is not filed until they verify and submit it like any other invoice.

        What gets copied follows the rules attached to each subject:

        * **ابطالی (3)** — §5-3 says the buyer and the whole body are fetched
          from the reference, so they need not be repeated. Header identity only.
        * **اصلاحی (2)** — §5-2 keeps نوع, الگو, the buyer fields, شناسه کالا/خدمت
          and نرخ مالیات fixed, so the body is copied for the operator to adjust
          only what may change.
        * **برگشت از فروش (4)** — §5-4 is the goods sold minus those returned, so
          the body is the starting point to reduce.
        """
        if subject not in (2, 3, 4):
            raise HTTPException(
                400, "موضوع باید اصلاحی (۲)، ابطالی (۳) یا برگشت از فروش (۴) باشد"
            )
        record = store.get_invoice(invoice_id)
        if record is None or record.profile != profile.name:
            raise HTTPException(404, "صورتحساب یافت نشد")
        if not record.tax_id:
            raise HTTPException(
                400,
                "این صورتحساب هنوز شماره مالیاتی ندارد؛ تنها صورتحساب ارسال‌شده مرجع می‌شود.",
            )

        source = record.payload
        header = dict(source.get("header") or {})
        draft: dict[str, Any] = {
            "header": {
                "inty": header.get("inty", 1),
                "inp": header.get("inp", 1),
                "ins": subject,
                "irtaxid": record.tax_id,
                "indatim": int(datetime.now(UTC).timestamp() * 1000),
                "tins": header.get("tins"),
                "tob": header.get("tob"),
                "bid": header.get("bid"),
                "tinb": header.get("tinb"),
                "bpc": header.get("bpc"),
                "setm": header.get("setm"),
            },
            "body": [] if subject == 3 else [dict(item) for item in source.get("body") or []],
            "payments": [],
        }
        draft["header"] = {k: v for k, v in draft["header"].items() if v is not None}
        return {
            "reference": {"id": record.id, "taxId": record.tax_id, "state": record.state},
            "subject": subject,
            "invoice": draft,
        }

    @app.post("/api/profiles/{name}/payments", tags=["invoices"], dependencies=AUTHENTICATED)
    async def register_payment(
        profile: ActiveProfile,
        body: PaymentIn,
        settings: Annotated[Settings, Depends(get_settings)],
    ):
        """ارسال پرداخت صورتحساب — RC_TICS §11.

        Reported against an already-issued شماره مالیاتی, so it is its own action
        rather than part of submission.
        """
        payload = body.model_dump(exclude_none=True)
        payload.setdefault("paymentDate", int(datetime.now(UTC).timestamp() * 1000))
        async with _client_for(profile, settings) as client:
            return await client.register_payment(payload)

    # -- inquiry ----------------------------------------------------------

    @app.get(
        "/api/profiles/{name}/inquiry/by-reference",
        tags=["inquiry"],
        dependencies=AUTHENTICATED,
    )
    async def inquiry_by_reference(
        profile: ActiveProfile,
        settings: Annotated[Settings, Depends(get_settings)],
        reference: Annotated[list[str], Query(description="One or more شماره پیگیری")],
    ):
        async with _client_for(profile, settings) as client:
            return await client.inquiry_by_reference_id(reference)

    @app.get("/api/profiles/{name}/inquiry/by-uid", tags=["inquiry"], dependencies=AUTHENTICATED)
    async def inquiry_by_uid(
        profile: ActiveProfile,
        settings: Annotated[Settings, Depends(get_settings)],
        uid: Annotated[list[str], Query(description="One or more requestTraceId")],
    ):
        async with _client_for(profile, settings) as client:
            return await client.inquiry_by_uid(uid, profile.memory_id)

    @app.get(
        "/api/profiles/{name}/inquiry/invoice-status",
        tags=["inquiry"],
        dependencies=AUTHENTICATED,
    )
    async def inquiry_invoice_status(
        profile: ActiveProfile,
        settings: Annotated[Settings, Depends(get_settings)],
        tax_id: Annotated[list[str], Query(alias="taxId")],
    ):
        """وضعیت صورتحساب در کارپوشه — approved, rejected, awaiting reaction, …"""
        async with _client_for(profile, settings) as client:
            return await client.inquiry_invoice_status(tax_id)

    @app.get("/api/profiles/{name}/inquiry/by-time", tags=["inquiry"], dependencies=AUTHENTICATED)
    async def inquiry_by_time(
        profile: ActiveProfile,
        settings: Annotated[Settings, Depends(get_settings)],
        start: datetime,
        end: datetime | None = None,
        status: RequestStatus | None = None,
        page_number: int = 1,
        page_size: int = 10,
    ):
        """استعلام بر اساس بازه زمانی — paged, and the only inquiry needing no ids."""
        async with _client_for(profile, settings) as client:
            return await client.inquiry_by_time(
                start, end, status=status, page_number=page_number, page_size=page_size
            )

    @app.get("/api/profiles/{name}/taxpayer", tags=["inquiry"], dependencies=AUTHENTICATED)
    async def taxpayer(
        profile: ActiveProfile,
        settings: Annotated[Settings, Depends(get_settings)],
        economic_code: Annotated[str, Query(alias="economicCode")],
    ):
        """استعلام اطلاعات پرونده مودی."""
        async with _client_for(profile, settings) as client:
            return await client.get_taxpayer(economic_code)

    @app.get("/api/profiles/{name}/taxpayer-info", tags=["inquiry"], dependencies=AUTHENTICATED)
    async def taxpayer_info(
        profile: ActiveProfile,
        settings: Annotated[Settings, Depends(get_settings)],
        economic_code: Annotated[str, Query(alias="economicCode")],
    ):
        """Extended taxpayer detail. SDK-only — not attested by RC_TICS."""
        async with _client_for(profile, settings) as client:
            return await client.get_taxpayer_info(economic_code)

    @app.get(
        "/api/profiles/{name}/fiscal-information", tags=["inquiry"], dependencies=AUTHENTICATED
    )
    async def fiscal_information(
        profile: ActiveProfile,
        settings: Annotated[Settings, Depends(get_settings)],
        memory_id: Annotated[str | None, Query(alias="memoryId")] = None,
    ):
        """استعلام اطلاعات حافظه مالیاتی. Defaults to this profile's own memory."""
        async with _client_for(profile, settings) as client:
            return await client.get_fiscal_information(memory_id or profile.memory_id)

    @app.get("/api/profiles/{name}/article6-status", tags=["inquiry"], dependencies=AUTHENTICATED)
    async def article6_status(
        profile: ActiveProfile,
        settings: Annotated[Settings, Depends(get_settings)],
        economic_code: Annotated[str, Query(alias="economicCode")],
        vat_value: Annotated[float, Query(alias="vatValue")],
        period: int,
    ):
        """وضعیت عبور از حد مجاز ماده ۶. SDK-only — not attested by RC_TICS."""
        async with _client_for(profile, settings) as client:
            return await client.get_article6_status(economic_code, vat_value, period)

    # -- dashboard --------------------------------------------------------

    @app.get("/api/profiles/{name}/dashboard", tags=["dashboard"], dependencies=AUTHENTICATED)
    def dashboard(
        profile: ActiveProfile,
        store: Annotated[RecordStore, Depends(get_record_store)],
        settings: Annotated[Settings, Depends(get_settings)],
    ):
        """Aggregated counts for the summary cards, scoped to this fiscal memory."""
        counts = store.counts_by_state(profile.name)
        return {
            "profile": profile.redacted(settings),
            "counts": counts,
            "recent": store.list_invoices(profile.name, limit=10),
        }

    @app.get("/api/health", tags=["metadata"])
    def health():
        return {"ok": True}

    # Last, and only last: a mount at "/" matches anything the routes above did
    # not, so registering it earlier would swallow every /api path below it.
    static_dir = settings.static_dir
    if static_dir is not None:
        resolved = Path(static_dir).expanduser()
        if (resolved / "index.html").is_file():
            app.mount("/", StaticFiles(directory=resolved, html=True), name="ui")
            _log.info("serving the UI from %s", resolved)
        else:
            # Not fatal. An API with no UI is still a working API, and the
            # operator may be starting the service precisely to build the UI.
            _log.warning(
                "MOADIAN_STATIC_DIR is %s but there is no index.html there; "
                "the API will run without a UI",
                resolved,
            )

    return app


#: Cache for the lazily built module-level ``app``.
_app: FastAPI | None = None


def __getattr__(name: str) -> Any:
    """Build ``moadian.api.app:app`` on first access, not on import.

    ``app = create_app()`` at module scope was the obvious spelling and it is a
    trap. :func:`create_app` reads ``.env``, loads the signing key, and *seeds
    accounts* — so merely importing this module wrote to the instance directory.
    Running the test suite from a deployment checkout was therefore enough to
    create an ``admin``/``admin1234`` account in the live database, with the real
    ``MOADIAN_SEED_USERS`` ignored ever after because seeding deliberately never
    overwrites an existing user. It took a failing login on a fresh install to
    notice, which is late.

    A module ``__getattr__`` runs only for an attribute Python did not find, so
    ``from moadian.api.app import create_app`` now touches nothing, while
    ``uvicorn moadian.api.app:app`` resolves through here exactly as before. No
    caller changes.
    """
    if name == "app":
        global _app
        if _app is None:
            _app = create_app()
        return _app
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
