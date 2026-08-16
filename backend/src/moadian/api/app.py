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

from typing import Annotated, Any

from fastapi import Body, Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from moadian.client import MoadianClient
from moadian.config import Environment, Profile, ProfileStore, Settings
from moadian.errors import (
    ConfigurationError,
    InvoiceValidationError,
    MoadianError,
    TaxApiError,
    TransportError,
)
from moadian.models import Invoice
from moadian.pipeline import InvoicePipeline, MonotonicSerialCounter
from moadian.rules import RuleEngine, load_rules, recompute
from moadian.store import Buyer, GoodsService, InvoiceRecord, InvoiceState, RecordStore

from .deps import (
    ActiveProfile,
    get_profile_store,
    get_record_store,
    get_rule_engine,
    get_settings,
)

__all__ = ["create_app"]


# ------------------------------------------------------------------ schemas


class ProfileIn(BaseModel):
    """A new profile. The PEMs are write-only — nothing reads them back out."""

    name: str
    memory_id: str = Field(description="شناسه یکتای حافظه مالیاتی, 6 chars of A-Z0-9")
    environment: str = Field(description="sandbox | production (also tp, operational)")
    certificate_pem: str
    private_key_pem: str
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


class InvoiceIn(BaseModel):
    invoice: Invoice
    #: Persist as a draft even when it fails validation, so work is not lost.
    save: bool = True


# ------------------------------------------------------------------ helpers


def _client_for(profile: Profile, settings: Settings) -> MoadianClient:
    return MoadianClient.from_profile(profile, settings=settings)


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


def create_app(*, cors_origins: list[str] | None = None) -> FastAPI:
    app = FastAPI(
        title="Moadian",
        description="صدور و ارسال صورتحساب الکترونیکی — سامانه مودیان",
        version="0.1.0",
    )

    # The UI is served separately in development, so the dev origin needs to be
    # allowed explicitly. Defaults to Vite's port and nothing else — a wildcard
    # here would let any page in the browser drive an invoice-signing API.
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

    # -- metadata: what the UI needs to build its forms -------------------

    @app.get("/api/environments", tags=["metadata"])
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

    @app.get("/api/patterns", tags=["metadata"])
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

    @app.get("/api/patterns/{number}/fields", tags=["metadata"])
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

    @app.get("/api/profiles", tags=["admin"])
    def list_profiles(store: Annotated[ProfileStore, Depends(get_profile_store)]):
        """Every configured fiscal memory. Redacted — no key material leaves here."""
        return [store.load(name).redacted() for name in store.list_names()]

    @app.post("/api/profiles", status_code=201, tags=["admin"])
    def create_profile(
        body: ProfileIn,
        store: Annotated[ProfileStore, Depends(get_profile_store)],
    ):
        profile = Profile(
            name=body.name,
            memory_id=body.memory_id,
            environment=Environment.parse(body.environment),
            certificate_pem=body.certificate_pem.encode(),
            private_key_pem=body.private_key_pem.encode(),
            economic_code=body.economic_code,
            base_url_override=body.base_url_override,
        )
        profile.validate()
        store.save(profile)
        return profile.redacted()

    @app.get("/api/profiles/{name}", tags=["admin"])
    def read_profile(profile: ActiveProfile):
        return profile.redacted()

    @app.delete("/api/profiles/{name}", status_code=204, tags=["admin"])
    def delete_profile(name: str, store: Annotated[ProfileStore, Depends(get_profile_store)]):
        store.delete(name)

    @app.post("/api/profiles/{name}/test-connection", tags=["admin"])
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

    @app.get("/api/profiles/{name}/buyers", tags=["reference"])
    def list_buyers(
        profile: ActiveProfile,
        store: Annotated[RecordStore, Depends(get_record_store)],
    ):
        return store.list_buyers(profile.name)

    @app.post("/api/profiles/{name}/buyers", status_code=201, tags=["reference"])
    def add_buyer(
        profile: ActiveProfile,
        body: BuyerIn,
        store: Annotated[RecordStore, Depends(get_record_store)],
    ):
        return store.add_buyer(profile.name, Buyer(**body.model_dump()))

    @app.delete("/api/profiles/{name}/buyers/{buyer_id}", status_code=204, tags=["reference"])
    def delete_buyer(
        profile: ActiveProfile,
        buyer_id: int,
        store: Annotated[RecordStore, Depends(get_record_store)],
    ):
        store.delete_buyer(profile.name, buyer_id)

    @app.get("/api/profiles/{name}/goods", tags=["reference"])
    def list_goods(
        profile: ActiveProfile,
        store: Annotated[RecordStore, Depends(get_record_store)],
    ):
        return store.list_goods(profile.name)

    @app.post("/api/profiles/{name}/goods", status_code=201, tags=["reference"])
    def add_goods(
        profile: ActiveProfile,
        body: GoodsIn,
        store: Annotated[RecordStore, Depends(get_record_store)],
    ):
        return store.add_goods(profile.name, GoodsService(**body.model_dump()))

    @app.post("/api/profiles/{name}/goods/{goods_id}/default", tags=["reference"])
    def make_default(
        profile: ActiveProfile,
        goods_id: int,
        store: Annotated[RecordStore, Depends(get_record_store)],
    ):
        store.set_default_goods(profile.name, goods_id)
        return {"ok": True}

    @app.delete("/api/profiles/{name}/goods/{goods_id}", status_code=204, tags=["reference"])
    def delete_goods(
        profile: ActiveProfile,
        goods_id: int,
        store: Annotated[RecordStore, Depends(get_record_store)],
    ):
        store.delete_goods(profile.name, goods_id)

    # -- invoices ---------------------------------------------------------

    @app.post("/api/profiles/{name}/invoices/verify", tags=["invoices"])
    def verify_invoice(
        profile: ActiveProfile,
        invoice: Annotated[Invoice, Body(embed=True)],
        engine: Annotated[RuleEngine, Depends(get_rule_engine)],
    ):
        """اعتبارسنجی — every rule we can check offline, before anything is sent."""
        return engine.verify(invoice).as_dict()

    @app.post("/api/profiles/{name}/invoices/recompute", tags=["invoices"])
    def recompute_invoice(
        profile: ActiveProfile,
        invoice: Annotated[Invoice, Body(embed=True)],
    ):
        """Fill in every derived money field from quantity, price, discount and rate."""
        pattern = invoice.header.inp or 1
        return recompute(invoice, pattern).to_wire_dict()

    @app.get("/api/profiles/{name}/invoices", tags=["invoices"])
    def list_invoices(
        profile: ActiveProfile,
        store: Annotated[RecordStore, Depends(get_record_store)],
        state: str | None = None,
        limit: int = 100,
    ):
        return store.list_invoices(profile.name, state=state, limit=limit)

    @app.post("/api/profiles/{name}/invoices", status_code=201, tags=["invoices"])
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

    @app.post("/api/profiles/{name}/invoices/submit", tags=["invoices"])
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

    # -- inquiry ----------------------------------------------------------

    @app.get("/api/profiles/{name}/inquiry/by-reference", tags=["inquiry"])
    async def inquiry_by_reference(
        profile: ActiveProfile,
        settings: Annotated[Settings, Depends(get_settings)],
        reference: Annotated[list[str], Query(description="One or more شماره پیگیری")],
    ):
        async with _client_for(profile, settings) as client:
            return await client.inquiry_by_reference_id(reference)

    @app.get("/api/profiles/{name}/inquiry/by-uid", tags=["inquiry"])
    async def inquiry_by_uid(
        profile: ActiveProfile,
        settings: Annotated[Settings, Depends(get_settings)],
        uid: Annotated[list[str], Query(description="One or more requestTraceId")],
    ):
        async with _client_for(profile, settings) as client:
            return await client.inquiry_by_uid(uid, profile.memory_id)

    @app.get("/api/profiles/{name}/inquiry/invoice-status", tags=["inquiry"])
    async def inquiry_invoice_status(
        profile: ActiveProfile,
        settings: Annotated[Settings, Depends(get_settings)],
        tax_id: Annotated[list[str], Query(alias="taxId")],
    ):
        """وضعیت صورتحساب در کارپوشه — approved, rejected, awaiting reaction, …"""
        async with _client_for(profile, settings) as client:
            return await client.inquiry_invoice_status(tax_id)

    # -- dashboard --------------------------------------------------------

    @app.get("/api/profiles/{name}/dashboard", tags=["dashboard"])
    def dashboard(
        profile: ActiveProfile,
        store: Annotated[RecordStore, Depends(get_record_store)],
    ):
        """Aggregated counts for the summary cards, scoped to this fiscal memory."""
        counts = store.counts_by_state(profile.name)
        return {
            "profile": profile.redacted(),
            "counts": counts,
            "recent": store.list_invoices(profile.name, limit=10),
        }

    @app.get("/api/health", tags=["metadata"])
    def health():
        return {"ok": True}

    return app


app = create_app()
