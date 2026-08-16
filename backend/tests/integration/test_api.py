"""The HTTP surface, driven against the in-process mock tax service.

The whole stack is exercised: FastAPI → rule engine → pipeline → JWS/JWE → the
verifying mock, which decrypts and checks the signature. So a passing test here
means the bytes the API produced were acceptable to something that actually
validates them, not merely that a handler returned 200.
"""

from __future__ import annotations

import httpx
import pytest

from moadian.api.app import create_app
from moadian.api.deps import (
    get_profile_store,
    get_record_store,
    get_rule_engine,
    get_settings,
)
from moadian.config import Environment, Profile, ProfileStore, Settings
from moadian.mock.server import create_mock_app
from moadian.rules import RuleEngine
from moadian.store import RecordStore

PASSPHRASE = "correct horse battery staple"
PROFILE = "آزمایشی"
MEMORY_ID = "A11216"


@pytest.fixture
def mock_transport() -> httpx.ASGITransport:
    return httpx.ASGITransport(app=create_mock_app())


@pytest.fixture
def api(tmp_path, credential_pems, monkeypatch, mock_transport):
    """The API wired to a temp instance directory and the mock tax service."""
    cert_pem, key_pem = credential_pems

    settings = Settings(instance_dir=tmp_path)
    profiles = ProfileStore(tmp_path / "profiles.json", PASSPHRASE)
    records = RecordStore(tmp_path / "records.sqlite")

    profiles.save(
        Profile(
            name=PROFILE,
            memory_id=MEMORY_ID,
            environment=Environment.SANDBOX,
            certificate_pem=cert_pem,
            private_key_pem=key_pem,
            economic_code="14003778990",
            # Points the client at the in-process mock. No /requestsmanager prefix:
            # the mock serves /api/v2 at its root.
            base_url_override="http://mock",
        )
    )

    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_profile_store] = lambda: profiles
    app.dependency_overrides[get_record_store] = lambda: records
    app.dependency_overrides[get_rule_engine] = lambda: RuleEngine()

    # MoadianClient.from_profile builds its own httpx client; route it to the mock.
    original = httpx.AsyncClient.__init__

    def patched(self, *args, **kwargs):
        kwargs.setdefault("transport", mock_transport)
        original(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched)
    return app


@pytest.fixture
async def client(api):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=api), base_url="http://api"
    ) as http:
        yield http


def valid_invoice() -> dict:
    """The RC_TICS p.20 example — the organization's own well-formed invoice."""
    return {
        "header": {
            "taxid": "A1121604C220002F095011",
            "indatim": 1683997837988,
            "inty": 1,
            "inp": 1,
            "ins": 1,
            "tins": "14003778990",
            "tob": 2,
            "tprdis": 20000,
            "tdis": 500,
            "tadis": 19500,
            "tvam": 1755,
            "todam": 0,
            "tbill": 21255,
            "setm": 2,
        },
        "body": [
            {
                "sstid": "2710000138624",
                "sstt": "سرسیلندر قطعات صنعت فولاد سازی",
                "mu": "164",
                "am": 2,
                "fee": 10000,
                "prdis": 20000,
                "dis": 500,
                "adis": 19500,
                "vra": 9,
                "vam": 1755,
                "tsstam": 21255,
            }
        ],
    }


# ------------------------------------------------------------------ metadata


async def test_environments_lists_both_deployments(client: httpx.AsyncClient) -> None:
    body = (await client.get("/api/environments")).json()
    assert {e["value"] for e in body} == {"sandbox", "production"}
    production = next(e for e in body if e["value"] == "production")
    assert production["host"] == "tp.tax.gov.ir"
    assert production["isProduction"] is True
    assert production["label"] == "عملیاتی"


async def test_patterns_are_listed_for_the_switcher(client: httpx.AsyncClient) -> None:
    body = (await client.get("/api/patterns")).json()
    assert [p["number"] for p in body] == [1, 2, 3, 4, 5, 6, 7, 8, 9, 11, 13, 14]
    assert next(p for p in body if p["number"] == 1)["name"] == "فروش"


async def test_pattern_fields_drive_the_entry_form(client: httpx.AsyncClient) -> None:
    """The form's requiredness comes from جدول ۱, not from hard-coded frontend rules."""
    body = (await client.get("/api/patterns/1/fields?type=1")).json()
    header = {f["field"]: f for f in body["sections"]["header"]}
    assert header["tins"]["obligation"] == "required"
    assert header["tins"]["title"], "the UI needs a Persian label"
    assert header["inno"]["obligation"] == "optional"

    # نوع دوم genuinely differs — the switcher must re-fetch when type changes.
    type2 = (await client.get("/api/patterns/1/fields?type=2")).json()
    assert {f["field"]: f for f in type2["sections"]["header"]}["tob"]["obligation"] == "optional"


async def test_unknown_pattern_is_a_404(client: httpx.AsyncClient) -> None:
    assert (await client.get("/api/patterns/12/fields")).status_code == 404


# ------------------------------------------------------------------ profiles


async def test_profiles_never_expose_key_material(client: httpx.AsyncClient) -> None:
    """The security property that matters most on this boundary."""
    listing = (await client.get("/api/profiles")).json()
    assert len(listing) == 1
    raw = (await client.get("/api/profiles")).text
    assert "PRIVATE KEY" not in raw
    assert "BEGIN CERTIFICATE" not in raw

    detail = (await client.get(f"/api/profiles/{PROFILE}")).json()
    assert detail["memory_id"] == MEMORY_ID
    assert detail["environment"] == "sandbox"
    assert detail["is_production"] is False
    assert "certificate" in detail and "subject" in detail["certificate"]
    assert "private_key_pem" not in detail


async def test_creating_a_profile_binds_environment_to_memory_id(
    client: httpx.AsyncClient, credential_pems
) -> None:
    cert_pem, key_pem = credential_pems
    response = await client.post(
        "/api/profiles",
        json={
            "name": "عملیاتی",
            "memory_id": "B22327",
            "environment": "tp",  # the subdomain spelling must resolve
            "certificate_pem": cert_pem.decode(),
            "private_key_pem": key_pem.decode(),
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["environment"] == "production"
    assert body["base_url"] == "https://tp.tax.gov.ir/requestsmanager"


async def test_an_unknown_environment_is_refused(
    client: httpx.AsyncClient, credential_pems
) -> None:
    cert_pem, key_pem = credential_pems
    response = await client.post(
        "/api/profiles",
        json={
            "name": "x",
            "memory_id": "C33333",
            "environment": "staging",
            "certificate_pem": cert_pem.decode(),
            "private_key_pem": key_pem.decode(),
        },
    )
    assert response.status_code == 400
    assert "unknown environment" in response.json()["detail"]


async def test_missing_profile_is_a_404(client: httpx.AsyncClient) -> None:
    assert (await client.get("/api/profiles/nope")).status_code == 404


async def test_test_connection_separates_reachability_from_authentication(
    client: httpx.AsyncClient,
) -> None:
    """The operator needs to know *which* half failed, not just that something did."""
    body = (await client.post(f"/api/profiles/{PROFILE}/test-connection")).json()
    assert body["nonce"]["ok"] is True
    assert body["authenticated"]["ok"] is True  # the mock trusts the dev cert
    assert body["environment"] == "sandbox"


# ------------------------------------------------------------ reference data


async def test_buyers_round_trip(client: httpx.AsyncClient) -> None:
    created = await client.post(
        f"/api/profiles/{PROFILE}/buyers",
        json={"name": "شرکت نمونه", "national_id": "10100302746", "person_type": 2},
    )
    assert created.status_code == 201
    listing = (await client.get(f"/api/profiles/{PROFILE}/buyers")).json()
    assert [b["name"] for b in listing] == ["شرکت نمونه"]
    assert listing[0]["national_id"] == "10100302746"

    await client.delete(f"/api/profiles/{PROFILE}/buyers/{created.json()['id']}")
    assert (await client.get(f"/api/profiles/{PROFILE}/buyers")).json() == []


async def test_a_national_id_keeps_its_leading_zeros(client: httpx.AsyncClient) -> None:
    """Storing these as integers would silently corrupt them."""
    await client.post(
        f"/api/profiles/{PROFILE}/buyers",
        json={"name": "الف", "national_id": "0012345678", "person_type": 1},
    )
    listing = (await client.get(f"/api/profiles/{PROFILE}/buyers")).json()
    assert listing[0]["national_id"] == "0012345678"


async def test_duplicate_buyer_is_rejected(client: httpx.AsyncClient) -> None:
    payload = {"name": "الف", "national_id": "10100302746"}
    assert (await client.post(f"/api/profiles/{PROFILE}/buyers", json=payload)).status_code == 201
    second = await client.post(f"/api/profiles/{PROFILE}/buyers", json=payload)
    assert second.status_code == 400


async def test_goods_catalogue_with_one_default(client: httpx.AsyncClient) -> None:
    """A default pre-fills the invoice line, so exactly one may hold the flag."""
    first = await client.post(
        f"/api/profiles/{PROFILE}/goods",
        json={
            "stuff_id": "2710000138624",
            "description": "سرسیلندر",
            "unit": "164",
            "vat_rate": 9,
            "is_default": True,
        },
    )
    second = await client.post(
        f"/api/profiles/{PROFILE}/goods",
        json={"stuff_id": "1710000138624", "description": "کالای دوم", "is_default": True},
    )
    assert first.status_code == second.status_code == 201

    listing = (await client.get(f"/api/profiles/{PROFILE}/goods")).json()
    defaults = [g for g in listing if g["is_default"]]
    assert len(defaults) == 1, "two defaults would give the form no answer"
    assert defaults[0]["stuff_id"] == "1710000138624"

    await client.post(f"/api/profiles/{PROFILE}/goods/{first.json()['id']}/default")
    listing = (await client.get(f"/api/profiles/{PROFILE}/goods")).json()
    assert [g["stuff_id"] for g in listing if g["is_default"]] == ["2710000138624"]


async def test_reference_data_is_scoped_to_a_profile(
    client: httpx.AsyncClient, credential_pems
) -> None:
    """A buyer entered against sandbox must not appear on a production invoice."""
    cert_pem, key_pem = credential_pems
    await client.post(
        "/api/profiles",
        json={
            "name": "عملیاتی",
            "memory_id": "B22327",
            "environment": "production",
            "certificate_pem": cert_pem.decode(),
            "private_key_pem": key_pem.decode(),
        },
    )
    await client.post(
        f"/api/profiles/{PROFILE}/buyers",
        json={"name": "فقط آزمایشی", "national_id": "10100302746"},
    )
    assert (await client.get("/api/profiles/عملیاتی/buyers")).json() == []


# ------------------------------------------------------------------ invoices


async def test_verify_accepts_the_documented_invoice(client: httpx.AsyncClient) -> None:
    body = (
        await client.post(
            f"/api/profiles/{PROFILE}/invoices/verify", json={"invoice": valid_invoice()}
        )
    ).json()
    assert body["ok"] is True
    assert body["errors"] == []
    assert body["patternName"] == "فروش"


async def test_verify_reports_persian_messages_for_a_broken_invoice(
    client: httpx.AsyncClient,
) -> None:
    invoice = valid_invoice()
    invoice["header"]["tbill"] = 999
    body = (
        await client.post(f"/api/profiles/{PROFILE}/invoices/verify", json={"invoice": invoice})
    ).json()
    assert body["ok"] is False
    error = next(e for e in body["errors"] if e["field"] == "tbill")
    assert error["title"] and error["reference"]
    assert error["expected"] == 21255 and error["actual"] == 999


async def test_recompute_fills_the_derived_fields(client: httpx.AsyncClient) -> None:
    skeleton = {
        "header": {"taxid": "A" * 22, "indatim": 1683997837988, "ins": 1, "inp": 1, "inty": 1},
        "body": [{"sstid": "2710000138624", "am": 2, "fee": 10000, "dis": 500, "vra": 9}],
    }
    body = (
        await client.post(
            f"/api/profiles/{PROFILE}/invoices/recompute", json={"invoice": skeleton}
        )
    ).json()
    assert body["body"][0]["tsstam"] == 21255
    assert body["header"]["tbill"] == 21255


async def test_a_draft_is_saved_even_when_invalid(client: httpx.AsyncClient) -> None:
    """Half-typed is the normal state of an invoice; refusing to save loses work."""
    invoice = valid_invoice()
    invoice["header"]["tbill"] = 1
    response = await client.post(
        f"/api/profiles/{PROFILE}/invoices", json={"invoice": invoice}
    )
    assert response.status_code == 201
    assert response.json()["state"] == "invalid"
    assert response.json()["verification"]["ok"] is False

    listing = (await client.get(f"/api/profiles/{PROFILE}/invoices")).json()
    assert len(listing) == 1


async def test_submit_sends_a_valid_invoice_end_to_end(client: httpx.AsyncClient) -> None:
    """Through the rule engine, the JWS, the JWE, and a mock that verifies both."""
    response = await client.post(
        f"/api/profiles/{PROFILE}/invoices/submit", json={"invoice": valid_invoice()}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["state"] == "sent"
    assert body["uid"] and body["referenceNumber"]
    assert body["taxId"] == "A1121604C220002F095011"


async def test_submit_refuses_an_invalid_invoice(client: httpx.AsyncClient) -> None:
    invoice = valid_invoice()
    invoice["header"]["tvam"] = 99999
    response = await client.post(
        f"/api/profiles/{PROFILE}/invoices/submit", json={"invoice": invoice}
    )
    assert response.status_code == 422
    assert response.json()["detail"]["ok"] is False

    # It was recorded as invalid rather than silently dropped.
    listing = (await client.get(f"/api/profiles/{PROFILE}/invoices?state=invalid")).json()
    assert len(listing) == 1


# ----------------------------------------------------------------- dashboard


async def test_dashboard_counts_every_state_including_zeros(
    client: httpx.AsyncClient,
) -> None:
    """A missing key would read as a missing card rather than a count of zero."""
    await client.post(f"/api/profiles/{PROFILE}/invoices/submit", json={"invoice": valid_invoice()})
    body = (await client.get(f"/api/profiles/{PROFILE}/dashboard")).json()

    assert set(body["counts"]) == {
        "draft",
        "invalid",
        "sent",
        "confirmed",
        "rejected",
        "cancelled",
        "total",
    }
    assert body["counts"]["sent"] == 1
    assert body["counts"]["total"] == 1
    assert body["profile"]["memory_id"] == MEMORY_ID
    assert len(body["recent"]) == 1


async def test_dashboard_is_scoped_to_the_selected_profile(
    client: httpx.AsyncClient, credential_pems
) -> None:
    """Switching environment must switch the numbers, not merge them."""
    cert_pem, key_pem = credential_pems
    await client.post(
        "/api/profiles",
        json={
            "name": "عملیاتی",
            "memory_id": "B22327",
            "environment": "production",
            "certificate_pem": cert_pem.decode(),
            "private_key_pem": key_pem.decode(),
        },
    )
    await client.post(f"/api/profiles/{PROFILE}/invoices/submit", json={"invoice": valid_invoice()})

    assert (await client.get(f"/api/profiles/{PROFILE}/dashboard")).json()["counts"]["sent"] == 1
    assert (await client.get("/api/profiles/عملیاتی/dashboard")).json()["counts"]["total"] == 0
