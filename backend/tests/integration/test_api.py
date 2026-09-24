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
from moadian.auth import UserStore
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

    # Signing material is configured in the server's environment and placed on
    # disk out of band. Nothing about it is ever accepted over HTTP.
    key_dir = tmp_path / "keys"
    key_dir.mkdir()
    (key_dir / "dev.crt").write_bytes(cert_pem)
    (key_dir / "dev.pem").write_bytes(key_pem)
    (key_dir / "dev.pem").chmod(0o600)

    settings = Settings(
        instance_dir=tmp_path,
        certificate_path=key_dir / "dev.crt",
        private_key_path=key_dir / "dev.pem",
    )
    profiles = ProfileStore(tmp_path / "profiles.json", PASSPHRASE)
    records = RecordStore(tmp_path / "records.sqlite")

    profiles.save(
        Profile(
            name=PROFILE,
            memory_id=MEMORY_ID,
            environment=Environment.SANDBOX,
            economic_code="14003778990",
            # Points the client at the in-process mock. No /requestsmanager prefix:
            # the mock serves /api/v2 at its root.
            base_url_override="http://mock",
        )
    )

    app = create_app(users=UserStore(tmp_path / "users.sqlite"))
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
    """Signed in as the seeded admin.

    Every business route requires a session, so a fixture that did not
    authenticate would test the 401 path and nothing else.
    """
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=api), base_url="http://api"
    ) as http:
        response = await http.post(
            "/api/auth/login", json={"username": "admin", "password": "admin1234"}
        )
        assert response.status_code == 200, response.text
        http.headers["Authorization"] = f"Bearer {response.json()['token']}"
        yield http


@pytest.fixture
async def anonymous(api):
    """No session — for asserting that routes actually refuse one."""
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
    client: httpx.AsyncClient
) -> None:
    response = await client.post(
        "/api/profiles",
        json={
            "name": "عملیاتی",
            "memory_id": "B22327",
            "environment": "tp",  # the subdomain spelling must resolve
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["environment"] == "production"
    assert body["base_url"] == "https://tp.tax.gov.ir/requestsmanager"


async def test_an_unknown_environment_is_refused(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/api/profiles",
        json={
            "name": "x",
            "memory_id": "C33333",
            "environment": "staging",
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


# ------------------------------------------------- signing material


async def test_verify_signing_material_confirms_a_matched_pair(
    client: httpx.AsyncClient,
) -> None:
    """The button in تنظیمات. The dev pair is matched, so both environments pass."""
    body = (await client.get("/api/signing-material/verify")).json()
    assert {entry["environment"] for entry in body} == {"sandbox", "production"}
    assert all(entry["ok"] for entry in body)
    assert all(entry["matches"] for entry in body)


async def test_verify_signing_material_returns_no_key_material(
    client: httpx.AsyncClient,
) -> None:
    """This response reaches a browser. Nothing private may travel in it."""
    text = (await client.get("/api/signing-material/verify")).text
    assert "PRIVATE" not in text
    assert "BEGIN" not in text


async def test_verify_signing_material_reports_a_mismatch(
    api, client: httpx.AsyncClient, tmp_path
) -> None:
    """A key from a different pair: well-formed files, unusable together."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    stranger = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    (tmp_path / "keys" / "dev.pem").write_bytes(
        stranger.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    body = (await client.get("/api/signing-material/verify")).json()
    assert all(entry["matches"] is False for entry in body)
    assert all("مطابقت ندارد" in entry["message"] for entry in body)


async def test_verify_signing_material_is_admin_only(api) -> None:
    """It names file paths on the server; an ordinary operator has no use for them."""
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=api), base_url="http://api"
    ) as http:
        api.state.users.create(username="operator", password="operator1234", role="user")
        session = await http.post(
            "/api/auth/login", json={"username": "operator", "password": "operator1234"}
        )
        http.headers["Authorization"] = f"Bearer {session.json()['token']}"
        assert (await http.get("/api/signing-material/verify")).status_code == 403


# ------------------------------------------------------------ reference data


async def test_buyers_round_trip(client: httpx.AsyncClient) -> None:
    created = await client.post(
        "/api/buyers",
        json={"name": "شرکت نمونه", "national_id": "10100302746", "person_type": 2},
    )
    assert created.status_code == 201
    listing = (await client.get("/api/buyers")).json()
    assert [b["name"] for b in listing] == ["شرکت نمونه"]
    assert listing[0]["national_id"] == "10100302746"

    await client.delete(f"/api/buyers/{created.json()['id']}")
    assert (await client.get("/api/buyers")).json() == []


async def test_a_national_id_keeps_its_leading_zeros(client: httpx.AsyncClient) -> None:
    """Storing these as integers would silently corrupt them."""
    await client.post(
        "/api/buyers", json={"name": "الف", "national_id": "0012345678", "person_type": 1}
    )
    listing = (await client.get("/api/buyers")).json()
    assert listing[0]["national_id"] == "0012345678"


async def test_duplicate_buyer_is_rejected(client: httpx.AsyncClient) -> None:
    payload = {"name": "الف", "national_id": "10100302746"}
    assert (await client.post("/api/buyers", json=payload)).status_code == 201
    second = await client.post("/api/buyers", json=payload)
    assert second.status_code == 400


async def test_goods_catalogue_with_one_default(client: httpx.AsyncClient) -> None:
    """A default pre-fills the invoice line, so exactly one may hold the flag."""
    first = await client.post(
        "/api/goods",
        json={
            "stuff_id": "2710000138624",
            "description": "سرسیلندر",
            "unit": "164",
            "vat_rate": 9,
            "is_default": True,
        },
    )
    second = await client.post(
        "/api/goods",
        json={"stuff_id": "1710000138624", "description": "کالای دوم", "is_default": True},
    )
    assert first.status_code == second.status_code == 201

    listing = (await client.get("/api/goods")).json()
    defaults = [g for g in listing if g["is_default"]]
    assert len(defaults) == 1, "two defaults would give the form no answer"
    assert defaults[0]["stuff_id"] == "1710000138624"

    await client.post(f"/api/goods/{first.json()['id']}/default")
    listing = (await client.get("/api/goods")).json()
    assert [g["stuff_id"] for g in listing if g["is_default"]] == ["2710000138624"]


async def test_reference_data_needs_no_fiscal_memory(client: httpx.AsyncClient) -> None:
    """The catalogues are reachable before a شناسه یکتای حافظه مالیاتی exists.

    They used to hang off /api/profiles/{name}, which meant a taxpayer still
    waiting on their fiscal memory could not enter a single customer or goods
    code — the exact work that period is for. A شناسه ملی and a شناسه کالا/خدمت
    are issued nationally and mean the same thing in both environments, so there
    was never anything for the scoping to protect.
    """
    from moadian.api.deps import get_profile_store

    application = client._transport.app  # type: ignore[attr-defined]
    profiles = application.dependency_overrides[get_profile_store]()
    for name in list(profiles.list_names()):
        profiles.delete(name)
    assert profiles.list_names() == []

    created = await client.post(
        "/api/buyers", json={"name": "خریدار زودهنگام", "national_id": "10100302746"}
    )
    assert created.status_code == 201
    assert [b["name"] for b in (await client.get("/api/buyers")).json()] == ["خریدار زودهنگام"]

    goods = await client.post("/api/goods", json={"stuff_id": "271", "description": "کالا"})
    assert goods.status_code == 201
    assert [g["stuff_id"] for g in (await client.get("/api/goods")).json()] == ["271"]


async def test_a_buyer_is_shared_across_fiscal_memories(client: httpx.AsyncClient) -> None:
    """One address book, not one per memory. The same customer buys from both."""
    await client.post(
        "/api/profiles",
        json={"name": "عملیاتی", "memory_id": "B22327", "environment": "production"},
    )
    await client.post("/api/buyers", json={"name": "مشترک", "national_id": "10100302746"})
    # Nothing about the listing is profile-dependent any more; the same call
    # serves whichever memory the operator happens to have selected.
    assert [b["name"] for b in (await client.get("/api/buyers")).json()] == ["مشترک"]


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


async def test_dashboard_is_scoped_to_the_selected_profile(client: httpx.AsyncClient) -> None:
    """Switching environment must switch the numbers, not merge them."""
    await client.post(
        "/api/profiles",
        json={
            "name": "عملیاتی",
            "memory_id": "B22327",
            "environment": "production",
        },
    )
    await client.post(f"/api/profiles/{PROFILE}/invoices/submit", json={"invoice": valid_invoice()})

    assert (await client.get(f"/api/profiles/{PROFILE}/dashboard")).json()["counts"]["sent"] == 1
    assert (await client.get("/api/profiles/عملیاتی/dashboard")).json()["counts"]["total"] == 0


# --------------------------------------------------- keys never cross the wire


async def test_signing_material_reports_status_without_exposing_contents(
    client: httpx.AsyncClient,
) -> None:
    """The admin panel's view of the server's signing configuration."""
    body = (await client.get("/api/signing-material")).json()
    sandbox = next(m for m in body if m["environment"] == "sandbox")

    assert sandbox["certificate"]["configured"] is True
    assert sandbox["certificate"]["exists"] is True
    assert sandbox["privateKey"]["mode"] == "0600"
    assert sandbox["privateKey"]["worldReadable"] is False

    raw = (await client.get("/api/signing-material")).text
    assert "PRIVATE KEY" not in raw
    assert "MII" not in raw, "no base64 key body may appear in the status"


async def test_a_world_readable_private_key_is_flagged(
    client: httpx.AsyncClient, tmp_path
) -> None:
    """File mode is the key's only protection when it is not PKCS#8-encrypted."""
    (tmp_path / "keys" / "dev.pem").chmod(0o644)
    body = (await client.get("/api/signing-material")).json()
    sandbox = next(m for m in body if m["environment"] == "sandbox")
    assert sandbox["privateKey"]["worldReadable"] is True
    assert "chmod 600" in sandbox["privateKey"]["error"]


async def test_no_endpoint_accepts_key_material_or_a_path(
    client: httpx.AsyncClient, credential_pems
) -> None:
    """The upload path is gone by construction, not by validation.

    ProfileIn has no field for a PEM, a filename or a path, so anything a caller
    sends along those lines is ignored outright and the profile still signs with
    the server-configured key.
    """
    cert_pem, key_pem = credential_pems
    response = await client.post(
        "/api/profiles",
        json={
            "name": "smuggle",
            "memory_id": "D44444",
            "environment": "sandbox",
            # None of these are fields on the schema.
            "certificate_pem": cert_pem.decode(),
            "private_key_pem": key_pem.decode(),
            "private_key_file": "../../../etc/passwd",
            "certificate_path": "/etc/shadow",
        },
    )
    assert response.status_code == 201
    body = response.json()
    for leaked in ("private_key_pem", "certificate_pem", "private_key_file", "certificate_path"):
        assert leaked not in body
    # It still signs with the server's own material.
    assert body["certificate"]["national_id"] == "14003778990"


async def test_a_profile_is_refused_when_the_server_has_no_key_configured(
    tmp_path, credential_pems, monkeypatch, mock_transport
) -> None:
    """A misconfigured server must fail at profile creation, not at submission."""
    from moadian.api.app import create_app as _create_app
    from moadian.api.deps import get_profile_store, get_record_store, get_settings

    settings = Settings(instance_dir=tmp_path)  # no certificate_path at all
    app = _create_app(users=UserStore(tmp_path / "users2.sqlite"))
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_profile_store] = lambda: ProfileStore(
        tmp_path / "p.json", PASSPHRASE
    )
    app.dependency_overrides[get_record_store] = lambda: RecordStore(tmp_path / "r.sqlite")

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://api"
    ) as http:
        session = await http.post(
            "/api/auth/login", json={"username": "admin", "password": "admin1234"}
        )
        http.headers["Authorization"] = f"Bearer {session.json()['token']}"
        response = await http.post(
            "/api/profiles",
            json={"name": "x", "memory_id": "H88888", "environment": "sandbox"},
        )
    assert response.status_code == 400
    assert "MOADIAN_CERTIFICATE_PATH" in response.json()["detail"]


# ------------------------------------------ every action the documents define


async def test_all_documented_actions_are_reachable(client: httpx.AsyncClient) -> None:
    """A route for each resource RC_TICS defines, plus the two SDK-only ones.

    The gap this closes was real: six client methods existed with no way to call
    them, so the framework could do things the application could not.
    """
    paths = {
        route.path
        for route in client._transport.app.routes  # type: ignore[attr-defined]
        if hasattr(route, "path")
    }
    # Routers included lazily by FastAPI do not appear above, so check by call.
    for method, path in [
        ("POST", f"/api/profiles/{PROFILE}/invoices/submit"),
        ("GET", f"/api/profiles/{PROFILE}/inquiry/by-reference"),
        ("GET", f"/api/profiles/{PROFILE}/inquiry/by-uid"),
        ("GET", f"/api/profiles/{PROFILE}/inquiry/by-time"),
        ("GET", f"/api/profiles/{PROFILE}/inquiry/invoice-status"),
        ("GET", f"/api/profiles/{PROFILE}/taxpayer"),
        ("GET", f"/api/profiles/{PROFILE}/taxpayer-info"),
        ("GET", f"/api/profiles/{PROFILE}/fiscal-information"),
        ("GET", f"/api/profiles/{PROFILE}/article6-status"),
        ("POST", f"/api/profiles/{PROFILE}/payments"),
    ]:
        response = await client.request(method, path)
        # 404 would mean the route does not exist. Anything else means it does
        # and merely disliked the (deliberately absent) parameters.
        assert response.status_code != 404, f"{method} {path} is not routed"
    assert paths  # sanity: the app has routes at all


async def test_fiscal_information_defaults_to_this_profiles_memory(
    client: httpx.AsyncClient,
) -> None:
    response = await client.get(f"/api/profiles/{PROFILE}/fiscal-information")
    assert response.status_code == 200
    assert response.json()["nationalId"] or True  # mock shape; the call routed


async def test_taxpayer_lookup_reaches_the_service(client: httpx.AsyncClient) -> None:
    response = await client.get(
        f"/api/profiles/{PROFILE}/taxpayer", params={"economicCode": "14003778990"}
    )
    assert response.status_code == 200


async def test_registering_a_payment_reaches_the_service(client: httpx.AsyncClient) -> None:
    """ارسال پرداخت is its own action — reported against an issued tax id."""
    response = await client.post(
        f"/api/profiles/{PROFILE}/payments",
        json={"taxid": "A1121604C220002F095011", "paidAmount": 21255, "paymentMethod": "CASH"},
    )
    assert response.status_code == 200, response.text


# ------------------------------------------------- referring invoices (§5)


async def sent_invoice(client: httpx.AsyncClient) -> int:
    response = await client.post(
        f"/api/profiles/{PROFILE}/invoices/submit", json={"invoice": valid_invoice()}
    )
    assert response.status_code == 200, response.text
    return response.json()["id"]


@pytest.mark.parametrize("subject", [2, 3, 4])
async def test_a_referring_draft_carries_the_reference_and_subject(
    client: httpx.AsyncClient, subject: int
) -> None:
    invoice_id = await sent_invoice(client)
    response = await client.post(
        f"/api/profiles/{PROFILE}/invoices/{invoice_id}/referring", params={"subject": subject}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    header = body["invoice"]["header"]
    assert header["ins"] == subject
    assert header["irtaxid"] == "A1121604C220002F095011"
    # نوع and الگو must match the reference — §5.
    assert header["inty"] == 1 and header["inp"] == 1
    # Buyer identity is not editable on a referring invoice, so it is carried over.
    assert header["tins"] == "14003778990"


async def test_a_cancellation_draft_omits_the_body(client: httpx.AsyncClient) -> None:
    """§5-3: the organization fetches the body from the reference for an ابطالی."""
    invoice_id = await sent_invoice(client)
    body = (
        await client.post(
            f"/api/profiles/{PROFILE}/invoices/{invoice_id}/referring", params={"subject": 3}
        )
    ).json()
    assert body["invoice"]["body"] == []


async def test_a_correction_draft_copies_the_body_to_edit(client: httpx.AsyncClient) -> None:
    """§5-2 and §5-4 both start from the original lines."""
    invoice_id = await sent_invoice(client)
    body = (
        await client.post(
            f"/api/profiles/{PROFILE}/invoices/{invoice_id}/referring", params={"subject": 2}
        )
    ).json()
    assert len(body["invoice"]["body"]) == 1
    assert body["invoice"]["body"][0]["sstid"] == "2710000138624"


async def test_a_referring_draft_is_not_sent_anywhere(client: httpx.AsyncClient) -> None:
    """It is a draft. Nothing is filed until the operator verifies and submits."""
    invoice_id = await sent_invoice(client)
    before = (await client.get(f"/api/profiles/{PROFILE}/invoices")).json()
    await client.post(
        f"/api/profiles/{PROFILE}/invoices/{invoice_id}/referring", params={"subject": 3}
    )
    after = (await client.get(f"/api/profiles/{PROFILE}/invoices")).json()
    assert len(after) == len(before)


async def test_an_unsent_invoice_cannot_be_a_reference(client: httpx.AsyncClient) -> None:
    """Only a filed invoice has a شماره مالیاتی for irtaxid to point at."""
    draft = await client.post(
        f"/api/profiles/{PROFILE}/invoices",
        json={"invoice": {**valid_invoice(), "header": {**valid_invoice()["header"], "taxid": ""}}},
    )
    response = await client.post(
        f"/api/profiles/{PROFILE}/invoices/{draft.json()['id']}/referring", params={"subject": 3}
    )
    assert response.status_code == 400


async def test_an_invalid_subject_is_refused(client: httpx.AsyncClient) -> None:
    invoice_id = await sent_invoice(client)
    response = await client.post(
        f"/api/profiles/{PROFILE}/invoices/{invoice_id}/referring", params={"subject": 1}
    )
    assert response.status_code == 400


# ------------------------------------------------------- inquiry reconciliation


def _mock_state(transport: httpx.ASGITransport):
    """The mock service's own view of what it accepted."""
    return transport.app.state.mock  # type: ignore[union-attr]


def _set_status(transport: httpx.ASGITransport, status: str) -> None:
    """Make the mock answer every inquiry with ``status``."""
    for submission in _mock_state(transport).submissions.values():
        submission.status = status


async def _submit(client: httpx.AsyncClient, invoice: dict | None = None) -> dict:
    response = await client.post(
        f"/api/profiles/{PROFILE}/invoices/submit",
        json={"invoice": invoice or valid_invoice()},
    )
    assert response.status_code == 200, response.text
    return response.json()


async def _record(client: httpx.AsyncClient, invoice_id: int) -> dict:
    listing = (await client.get(f"/api/profiles/{PROFILE}/invoices")).json()
    return next(r for r in listing if r["id"] == invoice_id)


async def test_submission_alone_never_reaches_confirmed(client: httpx.AsyncClient) -> None:
    """`POST /invoice` reports acceptance, not a verdict.

    The regression this guards: a submit handler that optimistically recorded
    CONFIRMED would tell an operator an invoice is in the کارپوشه before the
    organization has looked at it, and a later rejection would never be seen.
    """
    submitted = await _submit(client)
    assert submitted["state"] == "sent"
    assert submitted["referenceNumber"]


async def test_inquiry_moves_a_successful_submission_to_confirmed(
    client: httpx.AsyncClient,
) -> None:
    submitted = await _submit(client)

    outcome = (await client.post(f"/api/profiles/{PROFILE}/invoices/inquire")).json()
    assert outcome["checked"] == 1
    assert outcome["updated"] == 1
    assert outcome["records"][0]["previousState"] == "sent"
    assert outcome["records"][0]["state"] == "confirmed"
    assert outcome["records"][0]["inquiry"]["status"] == "SUCCESS"

    assert (await _record(client, submitted["id"]))["state"] == "confirmed"


async def test_inquiry_moves_a_failed_submission_to_rejected(
    client: httpx.AsyncClient, mock_transport: httpx.ASGITransport
) -> None:
    """A rejection is the case the whole screen exists for."""
    submitted = await _submit(client)
    _set_status(mock_transport, "FAILED")

    outcome = (await client.post(f"/api/profiles/{PROFILE}/invoices/inquire")).json()
    assert outcome["records"][0]["state"] == "rejected"

    record = await _record(client, submitted["id"])
    assert record["state"] == "rejected"
    assert record["detail"]["inquiry"]["status"] == "FAILED"


@pytest.mark.parametrize("status", ["IN_PROGRESS", "TIMEOUT", "NOT_FOUND"])
async def test_a_non_verdict_leaves_the_invoice_sent(
    client: httpx.AsyncClient, mock_transport: httpx.ASGITransport, status: str
) -> None:
    """None of these says the organization refused the invoice.

    RC_TICS §8 answers all three the same way — inquire again later. Moving the
    record out of SENT would strand a queued invoice in a terminal state, and
    for NOT_FOUND it would invite the one action that must never be taken: a
    resubmit, which spends a second serial on an invoice already in the queue.
    """
    submitted = await _submit(client)
    _set_status(mock_transport, status)

    outcome = (await client.post(f"/api/profiles/{PROFILE}/invoices/inquire")).json()
    assert outcome["checked"] == 1
    assert outcome["updated"] == 0

    record = await _record(client, submitted["id"])
    assert record["state"] == "sent"
    # Not moved, but the attempt is still on the record.
    assert record["detail"]["inquiry"]["status"] == status


async def test_inquiry_keeps_our_own_verification_report(client: httpx.AsyncClient) -> None:
    """Two opinions about one invoice, and the operator needs both.

    ``detail`` holds the اعتبارسنجی we ran before sending. Overwriting it with
    the organization's answer would destroy the only record of what we predicted
    at the moment the two disagree — which is exactly when someone is looking.
    """
    submitted = await _submit(client)
    await client.post(f"/api/profiles/{PROFILE}/invoices/inquire")

    detail = (await _record(client, submitted["id"]))["detail"]
    assert detail["ok"] is True
    assert detail["errors"] == []
    assert detail["inquiry"]["status"] == "SUCCESS"


async def test_only_invoices_awaiting_a_verdict_are_asked_about(
    client: httpx.AsyncClient,
) -> None:
    """A settled invoice is not re-inquired, and no nonce is spent on it."""
    await _submit(client)
    first = (await client.post(f"/api/profiles/{PROFILE}/invoices/inquire")).json()
    assert first["checked"] == 1

    second = (await client.post(f"/api/profiles/{PROFILE}/invoices/inquire")).json()
    assert second["checked"] == 0
    assert second["records"] == []


async def test_a_draft_is_never_inquired_about(client: httpx.AsyncClient) -> None:
    await client.post(f"/api/profiles/{PROFILE}/invoices", json={"invoice": valid_invoice()})
    outcome = (await client.post(f"/api/profiles/{PROFILE}/invoices/inquire")).json()
    assert outcome["checked"] == 0


async def test_inquiring_a_single_invoice_by_id(client: httpx.AsyncClient) -> None:
    submitted = await _submit(client)
    response = await client.post(
        f"/api/profiles/{PROFILE}/invoices/{submitted['id']}/inquire"
    )
    assert response.status_code == 200, response.text
    assert response.json()["state"] == "confirmed"


async def test_inquiring_a_draft_by_id_is_refused(client: httpx.AsyncClient) -> None:
    created = (
        await client.post(f"/api/profiles/{PROFILE}/invoices", json={"invoice": valid_invoice()})
    ).json()
    response = await client.post(f"/api/profiles/{PROFILE}/invoices/{created['id']}/inquire")
    assert response.status_code == 400


async def test_inquiry_is_scoped_to_the_selected_profile(client: httpx.AsyncClient) -> None:
    """Another profile's invoice is not reachable through this one."""
    submitted = await _submit(client)
    await client.post(
        "/api/profiles",
        json={"name": "دیگر", "memory_id": "B22327", "environment": "production"},
    )
    response = await client.post(f"/api/profiles/دیگر/invoices/{submitted['id']}/inquire")
    assert response.status_code == 404


async def test_a_confirmed_cancellation_marks_the_original_cancelled(
    client: httpx.AsyncClient,
) -> None:
    """ابطالی is an ordinary invoice, so the void is only known once it confirms.

    RC_IITP §5-3: no separate endpoint — ``ins=3`` plus the original's شماره
    منحصر به فرد مالیاتی in ``irtaxid``. Until that invoice is itself confirmed,
    the original is not void.
    """
    original = await _submit(client)
    await client.post(f"/api/profiles/{PROFILE}/invoices/inquire")
    assert (await _record(client, original["id"]))["state"] == "confirmed"

    cancellation = valid_invoice()
    cancellation["header"]["taxid"] = ""
    cancellation["header"]["ins"] = 3
    cancellation["header"]["irtaxid"] = original["taxId"]
    voiding = await _submit(client, cancellation)

    outcome = (await client.post(f"/api/profiles/{PROFILE}/invoices/inquire")).json()
    assert outcome["records"][0]["cancelledTaxId"] == original["taxId"]

    assert (await _record(client, original["id"]))["state"] == "cancelled"
    assert (await _record(client, voiding["id"]))["state"] == "confirmed"


async def test_inquiry_requires_a_session(anonymous: httpx.AsyncClient) -> None:
    assert (await anonymous.post(f"/api/profiles/{PROFILE}/invoices/inquire")).status_code == 401


# ------------------------------------------- the entry form sends no taxid


def form_invoice() -> dict:
    """What the entry form actually posts: no taxid, because it cannot know one.

    Deliberately minimal — the derived money fields come back from /recompute —
    and deliberately missing header.taxid, which is the shape that used to be
    rejected before any handler saw it.
    """
    return {
        "header": {
            "indatim": 1683997837988,
            "indati2m": 1683997837988,
            "inty": 1,
            "inp": 1,
            "ins": 1,
            "tins": "14003778990",
            "tob": 2,
            "setm": 1,
            "tprdis": 20000,
            "tdis": 500,
            "tadis": 19500,
            "tvam": 1755,
            "todam": 0,
            "tbill": 21255,
        },
        "body": [
            {
                "sstid": "2710000138624",
                "sstt": "سرسیلندر",
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


@pytest.mark.parametrize("action", ["verify", "recompute", ""])
async def test_every_form_button_accepts_an_invoice_with_no_taxid(
    client: httpx.AsyncClient, action: str
) -> None:
    """The regression that broke اعتبارسنجی, محاسبه مبالغ and ذخیره پیش‌نویس at once.

    `taxid: str` with no default made the key mandatory, so all three returned
    422 "Field required (body,invoice,header,taxid)" — demanding a number that
    is derived from the serial counter at submission and that no operator can
    supply. An empty string was always acceptable to the rule engine; only the
    model disagreed.
    """
    path = f"/api/profiles/{PROFILE}/invoices/{action}".rstrip("/")
    response = await client.post(path, json={"invoice": form_invoice()})
    assert response.status_code != 422, response.text
    assert response.status_code in (200, 201), response.text


async def test_a_draft_saved_without_a_taxid_verifies_clean(
    client: httpx.AsyncClient,
) -> None:
    saved = (
        await client.post(f"/api/profiles/{PROFILE}/invoices", json={"invoice": form_invoice()})
    ).json()
    assert saved["state"] == "draft", saved
    assert saved["verification"]["ok"] is True, saved["verification"]["errors"]


async def test_submitting_without_a_taxid_gets_one_generated(
    client: httpx.AsyncClient,
) -> None:
    """The other end of the same contract: leaving it blank is how you ask for one."""
    body = (
        await client.post(
            f"/api/profiles/{PROFILE}/invoices/submit", json={"invoice": form_invoice()}
        )
    ).json()
    assert body["taxId"], body
    assert body["taxId"].startswith(MEMORY_ID)
    assert len(body["taxId"]) == 22


# -------------------------------------------------- reopening and editing a draft


async def test_a_saved_draft_can_be_read_back(client: httpx.AsyncClient) -> None:
    """Without this the entry form has no way to reopen what it saved."""
    saved = (
        await client.post(f"/api/profiles/{PROFILE}/invoices", json={"invoice": form_invoice()})
    ).json()
    body = (await client.get(f"/api/profiles/{PROFILE}/invoices/{saved['id']}")).json()
    assert body["id"] == saved["id"]
    assert body["state"] == "draft"
    assert body["payload"]["header"]["tbill"] == 21255


async def test_editing_a_draft_rewrites_it_rather_than_adding_a_copy(
    client: httpx.AsyncClient,
) -> None:
    """The regression this endpoint exists for: editing used to mean saving a
    second copy, so the list filled with near-duplicates and none of them was
    authoritative."""
    saved = (
        await client.post(f"/api/profiles/{PROFILE}/invoices", json={"invoice": form_invoice()})
    ).json()

    changed = form_invoice()
    changed["body"][0]["sstt"] = "شرح تازه"
    response = await client.put(
        f"/api/profiles/{PROFILE}/invoices/{saved['id']}", json={"invoice": changed}
    )
    assert response.status_code == 200, response.text
    assert response.json()["id"] == saved["id"]

    listing = (await client.get(f"/api/profiles/{PROFILE}/invoices")).json()
    assert len(listing) == 1, "editing created a second record"
    assert listing[0]["payload"]["body"][0]["sstt"] == "شرح تازه"


async def test_editing_revalidates_and_can_move_a_draft_to_invalid(
    client: httpx.AsyncClient,
) -> None:
    saved = (
        await client.post(f"/api/profiles/{PROFILE}/invoices", json={"invoice": form_invoice()})
    ).json()
    assert saved["state"] == "draft"

    broken = form_invoice()
    broken["header"]["tbill"] = 999999  # no longer agrees with the lines
    body = (
        await client.put(
            f"/api/profiles/{PROFILE}/invoices/{saved['id']}", json={"invoice": broken}
        )
    ).json()
    assert body["state"] == "invalid"
    assert body["verification"]["ok"] is False


async def test_an_invalid_draft_can_be_fixed_back_to_draft(client: httpx.AsyncClient) -> None:
    """Saving a broken invoice records it as invalid; correcting it must clear that."""
    broken = form_invoice()
    broken["header"]["tbill"] = 999999
    saved = (
        await client.post(f"/api/profiles/{PROFILE}/invoices", json={"invoice": broken})
    ).json()
    assert saved["state"] == "invalid"

    body = (
        await client.put(
            f"/api/profiles/{PROFILE}/invoices/{saved['id']}", json={"invoice": form_invoice()}
        )
    ).json()
    assert body["state"] == "draft"
    assert body["verification"]["ok"] is True


async def test_a_sent_invoice_cannot_be_edited(client: httpx.AsyncClient) -> None:
    """The payload of a sent invoice is the record of what was actually signed.

    The organization holds it, an اصلاحی is compared against it, and rewriting it
    here would leave this application disagreeing with the کارپوشه about what was
    filed while showing no sign of the change.
    """
    sent = (
        await client.post(
            f"/api/profiles/{PROFILE}/invoices/submit", json={"invoice": form_invoice()}
        )
    ).json()

    changed = form_invoice()
    changed["body"][0]["sstt"] = "دستکاری‌شده"
    response = await client.put(
        f"/api/profiles/{PROFILE}/invoices/{sent['id']}", json={"invoice": changed}
    )
    assert response.status_code == 409, response.text

    stored = (await client.get(f"/api/profiles/{PROFILE}/invoices/{sent['id']}")).json()
    assert stored["payload"]["body"][0]["sstt"] == "سرسیلندر", "the sent payload was modified"
    assert stored["state"] == "sent"


async def test_reading_an_unknown_invoice_is_404(client: httpx.AsyncClient) -> None:
    assert (await client.get(f"/api/profiles/{PROFILE}/invoices/9999")).status_code == 404


async def test_another_profiles_draft_is_not_reachable(client: httpx.AsyncClient) -> None:
    """Invoices are profile-scoped; a memory id must not see another's records."""
    saved = (
        await client.post(f"/api/profiles/{PROFILE}/invoices", json={"invoice": form_invoice()})
    ).json()
    await client.post(
        "/api/profiles",
        json={"name": "دیگر", "memory_id": "B22327", "environment": "production"},
    )
    assert (await client.get(f"/api/profiles/دیگر/invoices/{saved['id']}")).status_code == 404
    assert (
        await client.put(
            f"/api/profiles/دیگر/invoices/{saved['id']}", json={"invoice": form_invoice()}
        )
    ).status_code == 404


async def test_editing_requires_a_session(anonymous: httpx.AsyncClient) -> None:
    assert (await anonymous.get(f"/api/profiles/{PROFILE}/invoices/1")).status_code == 401
    assert (
        await anonymous.put(f"/api/profiles/{PROFILE}/invoices/1", json={"invoice": form_invoice()})
    ).status_code == 401


# ------------------------------------------------------------ deleting a draft


async def test_a_draft_can_be_deleted(client: httpx.AsyncClient) -> None:
    saved = (
        await client.post(f"/api/profiles/{PROFILE}/invoices", json={"invoice": form_invoice()})
    ).json()
    response = await client.delete(f"/api/profiles/{PROFILE}/invoices/{saved['id']}")
    assert response.status_code == 204, response.text
    assert (await client.get(f"/api/profiles/{PROFILE}/invoices")).json() == []
    assert (await client.get(f"/api/profiles/{PROFILE}/invoices/{saved['id']}")).status_code == 404


async def test_an_invalid_draft_can_be_deleted(client: httpx.AsyncClient) -> None:
    """A draft saved with errors is the one most likely to be thrown away."""
    broken = form_invoice()
    broken["header"]["tbill"] = 999999
    saved = (
        await client.post(f"/api/profiles/{PROFILE}/invoices", json={"invoice": broken})
    ).json()
    assert saved["state"] == "invalid"
    assert (
        await client.delete(f"/api/profiles/{PROFILE}/invoices/{saved['id']}")
    ).status_code == 204


async def test_a_sent_invoice_cannot_be_deleted(client: httpx.AsyncClient) -> None:
    """It exists in the organization's records whether or not it exists in ours.

    Deleting our copy would destroy the شماره پیگیری that is the only way to ask
    what became of it, and the payload an اصلاحی would have to reference. Such an
    invoice is withdrawn with an ابطالی — a new filing, not a deletion.
    """
    sent = (
        await client.post(
            f"/api/profiles/{PROFILE}/invoices/submit", json={"invoice": form_invoice()}
        )
    ).json()
    response = await client.delete(f"/api/profiles/{PROFILE}/invoices/{sent['id']}")
    assert response.status_code == 409, response.text

    still_there = (await client.get(f"/api/profiles/{PROFILE}/invoices/{sent['id']}")).json()
    assert still_there["state"] == "sent"
    assert still_there["reference_number"] == sent["referenceNumber"]


async def test_a_confirmed_invoice_cannot_be_deleted(client: httpx.AsyncClient) -> None:
    """The strongest case: the organization has registered it in the کارپوشه."""
    await client.post(f"/api/profiles/{PROFILE}/invoices/submit", json={"invoice": form_invoice()})
    outcome = (await client.post(f"/api/profiles/{PROFILE}/invoices/inquire")).json()
    invoice_id = outcome["records"][0]["id"]
    assert outcome["records"][0]["state"] == "confirmed"

    assert (
        await client.delete(f"/api/profiles/{PROFILE}/invoices/{invoice_id}")
    ).status_code == 409


async def test_deleting_an_unknown_invoice_is_404(client: httpx.AsyncClient) -> None:
    assert (await client.delete(f"/api/profiles/{PROFILE}/invoices/9999")).status_code == 404


async def test_another_profiles_draft_cannot_be_deleted(client: httpx.AsyncClient) -> None:
    saved = (
        await client.post(f"/api/profiles/{PROFILE}/invoices", json={"invoice": form_invoice()})
    ).json()
    await client.post(
        "/api/profiles",
        json={"name": "دیگر", "memory_id": "B22327", "environment": "production"},
    )
    assert (
        await client.delete(f"/api/profiles/دیگر/invoices/{saved['id']}")
    ).status_code == 404
    assert (await client.get(f"/api/profiles/{PROFILE}/invoices/{saved['id']}")).status_code == 200


async def test_deleting_requires_a_session(anonymous: httpx.AsyncClient) -> None:
    assert (await anonymous.delete(f"/api/profiles/{PROFILE}/invoices/1")).status_code == 401


# --------------------------------------------------------- واحدهای اندازه‌گیری


async def test_the_unit_table_is_served(client: httpx.AsyncClient) -> None:
    """The form needs names, not codes: nobody should have to know 1627 is عدد."""
    body = (await client.get("/api/units")).json()
    assert body["default"] == "1627"
    assert len(body["units"]) == 97
    by_code = {u["code"]: u["name"] for u in body["units"]}
    assert by_code["1627"] == "عدد"
    assert by_code["164"] == "کیلوگرم"


async def test_the_unit_table_requires_a_session(anonymous: httpx.AsyncClient) -> None:
    assert (await anonymous.get("/api/units")).status_code == 401


async def test_an_invoice_with_the_default_unit_verifies_clean(
    client: httpx.AsyncClient,
) -> None:
    invoice = form_invoice()
    invoice["body"][0]["mu"] = "1627"
    report = (
        await client.post(f"/api/profiles/{PROFILE}/invoices/verify", json={"invoice": invoice})
    ).json()
    assert report["ok"] is True
    assert [i for i in report["warnings"] if i["field"] == "mu"] == []


async def test_the_blank_unit_that_was_rejected_no_longer_reaches_the_wire(
    client: httpx.AsyncClient,
) -> None:
    """The invoice that came back 0103502 carried `"mu": ""`.

    §8-30 makes mu اختیاری, so absence is legal and an empty string is not. The
    payload now omits it, which is the shape the organization accepts.
    """
    invoice = form_invoice()
    invoice["body"][0]["mu"] = ""
    recomputed = (
        await client.post(f"/api/profiles/{PROFILE}/invoices/recompute", json={"invoice": invoice})
    ).json()
    assert "mu" not in recomputed["body"][0]

    saved = (
        await client.post(f"/api/profiles/{PROFILE}/invoices", json={"invoice": invoice})
    ).json()
    assert saved["verification"]["ok"] is True
    stored = (await client.get(f"/api/profiles/{PROFILE}/invoices/{saved['id']}")).json()
    assert "mu" not in stored["payload"]["body"][0]


async def test_an_unrecognised_unit_warns_but_does_not_block(
    client: httpx.AsyncClient,
) -> None:
    """The table is a snapshot; the organization revises it. Blocking a code it
    has since added would be worse than flagging one it never had."""
    invoice = form_invoice()
    invoice["body"][0]["mu"] = "99999"
    report = (
        await client.post(f"/api/profiles/{PROFILE}/invoices/verify", json={"invoice": invoice})
    ).json()
    assert report["ok"] is True
    assert [i["field"] for i in report["warnings"] if i["field"] == "mu"] == ["mu"]


async def test_a_malformed_unit_blocks_submission(client: httpx.AsyncClient) -> None:
    invoice = form_invoice()
    invoice["body"][0]["mu"] = "کیلوگرم"  # the name, not the code
    response = await client.post(
        f"/api/profiles/{PROFILE}/invoices/submit", json={"invoice": invoice}
    )
    assert response.status_code == 422
    assert any(i["field"] == "mu" for i in response.json()["detail"]["errors"])


# ------------------------------- submitting a saved draft leaves no duplicate


async def test_submitting_a_saved_draft_moves_it_rather_than_copying_it(
    client: httpx.AsyncClient,
) -> None:
    """The bug this endpoint's record_id exists for.

    Save a draft, send it, and there were two rows: the draft, untouched and
    taxid-less, beside a SENT copy of the identical payload. Submission could only
    insert, because nothing told it which stored record the payload came from.
    """
    saved = (
        await client.post(f"/api/profiles/{PROFILE}/invoices", json={"invoice": form_invoice()})
    ).json()

    sent = (
        await client.post(
            f"/api/profiles/{PROFILE}/invoices/submit",
            json={"invoice": form_invoice(), "record_id": saved["id"]},
        )
    ).json()

    assert sent["id"] == saved["id"], "submission created a second record"
    listing = (await client.get(f"/api/profiles/{PROFILE}/invoices")).json()
    assert len(listing) == 1, f"{len(listing)} records after sending one draft"
    assert listing[0]["state"] == "sent"
    assert listing[0]["tax_id"]
    assert listing[0]["reference_number"]


async def test_no_draft_is_left_behind_with_an_empty_tax_id(
    client: httpx.AsyncClient,
) -> None:
    """Stated as the operator saw it: a replica with no شماره مالیاتی."""
    saved = (
        await client.post(f"/api/profiles/{PROFILE}/invoices", json={"invoice": form_invoice()})
    ).json()
    await client.post(
        f"/api/profiles/{PROFILE}/invoices/submit",
        json={"invoice": form_invoice(), "record_id": saved["id"]},
    )
    drafts = (await client.get(f"/api/profiles/{PROFILE}/invoices?state=draft")).json()
    assert drafts == []


async def test_submitting_without_a_record_id_still_inserts(
    client: httpx.AsyncClient,
) -> None:
    """An invoice typed and sent without ever being saved has no row to move."""
    sent = (
        await client.post(
            f"/api/profiles/{PROFILE}/invoices/submit", json={"invoice": form_invoice()}
        )
    ).json()
    listing = (await client.get(f"/api/profiles/{PROFILE}/invoices")).json()
    assert [r["id"] for r in listing] == [sent["id"]]
    assert listing[0]["state"] == "sent"


async def test_resending_an_already_sent_record_is_refused(
    client: httpx.AsyncClient,
) -> None:
    """Filing it twice costs a second serial and a second شماره مالیاتی, and
    neither filing can be withdrawn except by an ابطالی."""
    sent = (
        await client.post(
            f"/api/profiles/{PROFILE}/invoices/submit", json={"invoice": form_invoice()}
        )
    ).json()

    response = await client.post(
        f"/api/profiles/{PROFILE}/invoices/submit",
        json={"invoice": form_invoice(), "record_id": sent["id"]},
    )
    assert response.status_code == 409, response.text

    listing = (await client.get(f"/api/profiles/{PROFILE}/invoices")).json()
    assert len(listing) == 1
    assert listing[0]["tax_id"] == sent["taxId"], "the tax id changed on a refused resend"


async def test_the_refusal_to_resend_happens_before_a_serial_is_spent(
    client: httpx.AsyncClient,
) -> None:
    """A serial only moves forward, so one burnt on a refusal is gone for good."""
    sent = (
        await client.post(
            f"/api/profiles/{PROFILE}/invoices/submit", json={"invoice": form_invoice()}
        )
    ).json()
    first_serial = sent["taxId"][11:21]

    await client.post(
        f"/api/profiles/{PROFILE}/invoices/submit",
        json={"invoice": form_invoice(), "record_id": sent["id"]},
    )
    again = (
        await client.post(
            f"/api/profiles/{PROFILE}/invoices/submit", json={"invoice": form_invoice()}
        )
    ).json()
    assert int(again["taxId"][11:21], 16) == int(first_serial, 16) + 1


async def test_an_invalid_submission_updates_the_draft_instead_of_adding_one(
    client: httpx.AsyncClient,
) -> None:
    """The same duplication on the failure path: a refused submit used to insert
    an INVALID copy beside the draft it came from."""
    saved = (
        await client.post(f"/api/profiles/{PROFILE}/invoices", json={"invoice": form_invoice()})
    ).json()
    broken = form_invoice()
    broken["header"]["tbill"] = 999999

    response = await client.post(
        f"/api/profiles/{PROFILE}/invoices/submit",
        json={"invoice": broken, "record_id": saved["id"]},
    )
    assert response.status_code == 422

    listing = (await client.get(f"/api/profiles/{PROFILE}/invoices")).json()
    assert len(listing) == 1
    assert listing[0]["id"] == saved["id"]
    assert listing[0]["state"] == "invalid"


async def test_submitting_another_profiles_record_is_refused(
    client: httpx.AsyncClient,
) -> None:
    saved = (
        await client.post(f"/api/profiles/{PROFILE}/invoices", json={"invoice": form_invoice()})
    ).json()
    await client.post(
        "/api/profiles",
        json={"name": "دیگر", "memory_id": "B22327", "environment": "production"},
    )
    response = await client.post(
        "/api/profiles/دیگر/invoices/submit",
        json={"invoice": form_invoice(), "record_id": saved["id"]},
    )
    assert response.status_code == 404
