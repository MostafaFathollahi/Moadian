"""The catalogue HTTP surface.

Read-only by design: the export is loaded by tools/import_catalogue.py, not
uploaded. These check the contract the invoice form depends on.
"""

from __future__ import annotations

import httpx
import pytest

from moadian.api.app import create_app
from moadian.api.deps import (
    get_catalogue_store,
    get_profile_store,
    get_record_store,
    get_rule_engine,
    get_settings,
)
from moadian.auth import UserStore
from moadian.config import Environment, Profile, ProfileStore, Settings
from moadian.rules import RuleEngine
from moadian.store import CatalogueStore, RecordStore

PASSPHRASE = "correct horse battery staple"
PROFILE = "آزمایشی"


def row(stuff_id, description, vat=10.0, *, expired=False, run="1405-07-01"):
    return {
        "stuff_id": stuff_id,
        "description": description,
        "vat_rate": vat,
        "taxable": "مشمول",
        "run_date": run,
        "expiration_date": "1405-07-01" if expired else None,
        "kind": "شناسه اختصاصی خدمت",
        "pricing": None,
        "is_current": 0 if expired else 1,
    }


@pytest.fixture
def catalogue(tmp_path):
    store = CatalogueStore(tmp_path / "catalogue.sqlite")
    store.replace_all(
        [
            row("2330004567413", "خدمات مجوز (license) نرم افزار/تخصیص لایسنس یک ساله"),
            row("2330004567420", "پشتیبانی و نگهداری نرم افزار خاص صنعت"),
            row("2330003073403", "خدمات اموزش اشپزی/برگزاری دوره مقدماتی"),
            row("2330009999999", "خدمات مشاوره", vat=9.0, expired=True, run="1403-09-04"),
            row("2330009999999", "خدمات مشاوره", vat=10.0, run="1405-07-02"),
        ],
        source="services.csv",
    )
    yield store
    store.close()


@pytest.fixture
def api(tmp_path, credential_pems, catalogue):
    cert_pem, key_pem = credential_pems
    keys = tmp_path / "keys"
    keys.mkdir()
    (keys / "dev.crt").write_bytes(cert_pem)
    (keys / "dev.pem").write_bytes(key_pem)

    settings = Settings(
        instance_dir=tmp_path,
        certificate_path=keys / "dev.crt",
        private_key_path=keys / "dev.pem",
    )
    profiles = ProfileStore(tmp_path / "profiles.json", PASSPHRASE)
    profiles.save(
        Profile(name=PROFILE, memory_id="A11216", environment=Environment.SANDBOX)
    )

    app = create_app(users=UserStore(tmp_path / "users.sqlite"))
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_profile_store] = lambda: profiles
    app.dependency_overrides[get_record_store] = lambda: RecordStore(tmp_path / "records.sqlite")
    app.dependency_overrides[get_rule_engine] = lambda: RuleEngine()
    app.dependency_overrides[get_catalogue_store] = lambda: catalogue
    return app


@pytest.fixture
async def client(api):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=api), base_url="http://api"
    ) as http:
        response = await http.post(
            "/api/auth/login", json={"username": "admin", "password": "admin1234"}
        )
        assert response.status_code == 200, response.text
        http.headers["Authorization"] = f"Bearer {response.json()['token']}"
        yield http


async def search(client: httpx.AsyncClient, q: str, **params) -> list[dict]:
    response = await client.get("/api/catalogue/search", params={"q": q, **params})
    assert response.status_code == 200, response.text
    return response.json()


# -- status -----------------------------------------------------------------


async def test_status_reports_the_loaded_catalogue(client: httpx.AsyncClient) -> None:
    body = (await client.get("/api/catalogue/status")).json()
    assert body["empty"] is False
    assert body["total"] == 5
    assert body["current"] == 4
    assert body["superseded"] == 1
    assert body["source"] == "services.csv"


async def test_status_is_readable_by_a_non_admin(api) -> None:
    """The invoice form needs it, so it cannot be admin-only.

    Without it the form cannot distinguish "no catalogue loaded" from "nothing
    matched", and every search on a fresh install looks like a broken feature.
    """
    api.state.users.create(username="operator", password="operator1234", role="user")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=api), base_url="http://api"
    ) as http:
        token = (
            await http.post(
                "/api/auth/login", json={"username": "operator", "password": "operator1234"}
            )
        ).json()["token"]
        http.headers["Authorization"] = f"Bearer {token}"
        assert (await http.get("/api/catalogue/status")).status_code == 200
        assert (await http.get("/api/catalogue/search", params={"q": "نرم"})).status_code == 200


# -- search -----------------------------------------------------------------


async def test_searching_by_full_identifier(client: httpx.AsyncClient) -> None:
    hits = await search(client, "2330004567413")
    assert [h["stuffId"] for h in hits] == ["2330004567413"]
    assert hits[0]["vatRate"] == 10.0
    assert hits[0]["taxable"] == "مشمول"
    assert hits[0]["isCurrent"] is True


async def test_searching_by_partial_identifier(client: httpx.AsyncClient) -> None:
    ids = {h["stuffId"] for h in await search(client, "23300045")}
    assert ids == {"2330004567413", "2330004567420"}


async def test_searching_with_persian_digits(client: httpx.AsyncClient) -> None:
    hits = await search(client, "۲۳۳۰۰۰۴۵۶۷۴۱۳")
    assert [h["stuffId"] for h in hits] == ["2330004567413"]


async def test_searching_by_words(client: httpx.AsyncClient) -> None:
    ids = {h["stuffId"] for h in await search(client, "نرم افزار")}
    assert ids == {"2330004567413", "2330004567420"}


async def test_searching_an_unfinished_word(client: httpx.AsyncClient) -> None:
    assert any(h["stuffId"] == "2330004567413" for h in await search(client, "لایسن"))


async def test_arabic_spelling_finds_the_persian_row(client: httpx.AsyncClient) -> None:
    assert any(h["stuffId"] == "2330003073403" for h in await search(client, "آشپزي"))


async def test_a_superseded_rate_is_never_returned(client: httpx.AsyncClient) -> None:
    hits = await search(client, "مشاوره")
    assert [h["vatRate"] for h in hits] == [10.0]


async def test_an_empty_query_returns_an_empty_list(client: httpx.AsyncClient) -> None:
    assert await search(client, "") == []
    assert (await client.get("/api/catalogue/search")).json() == []


@pytest.mark.parametrize("query", ['"', "AND", "*", "a:b", 'x" OR "y'])
async def test_fts_operators_from_the_search_box_return_200(client, query) -> None:
    """These reach the endpoint from an ordinary search box. A 500 here is a
    crash the operator triggers by typing a quotation mark."""
    response = await client.get("/api/catalogue/search", params={"q": query})
    assert response.status_code == 200


async def test_the_limit_is_honoured(client: httpx.AsyncClient) -> None:
    assert len(await search(client, "خدمات", limit=1)) == 1


async def test_an_absurd_limit_is_capped_not_rejected(client: httpx.AsyncClient) -> None:
    response = await client.get("/api/catalogue/search", params={"q": "خدمات", "limit": 10**9})
    assert response.status_code == 200
    assert len(response.json()) <= 100


# -- one item ---------------------------------------------------------------


async def test_an_item_carries_its_whole_rate_history(client: httpx.AsyncClient) -> None:
    body = (await client.get("/api/catalogue/item/2330009999999")).json()
    assert body["current"]["vatRate"] == 10.0
    assert [h["vatRate"] for h in body["history"]] == [10.0, 9.0]
    assert [h["isCurrent"] for h in body["history"]] == [True, False]


async def test_an_unknown_item_is_404(client: httpx.AsyncClient) -> None:
    assert (await client.get("/api/catalogue/item/1111111111111")).status_code == 404


# -- the catalogue is not writable over HTTP --------------------------------


@pytest.mark.parametrize("path", ["/api/catalogue/search", "/api/catalogue/status"])
async def test_the_catalogue_requires_a_session(anonymous_client, path: str) -> None:
    assert (await anonymous_client.get(path)).status_code == 401


@pytest.fixture
async def anonymous_client(api):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=api), base_url="http://api"
    ) as http:
        yield http


async def test_there_is_no_way_to_write_the_catalogue_over_http(api) -> None:
    """Deliberate: the export is tens of megabytes per part and belongs on the
    server out of band. An upload endpoint would add a way to fill the disk and
    buy nothing."""
    writable = [
        (route.path, sorted(route.methods))
        for route in api.routes
        if getattr(route, "path", "").startswith("/api/catalogue")
        and getattr(route, "methods", set()) - {"GET", "HEAD", "OPTIONS"}
    ]
    assert writable == []
