"""The built UI served from the API process.

One origin means one port, which is what a single systemd unit behind an SSH
tunnel needs. The risk that buys is a catch-all mount shadowing the API, so
that is what these check.
"""

from __future__ import annotations

import httpx
import pytest

from moadian.api.app import create_app
from moadian.api.deps import get_settings
from moadian.auth import UserStore


@pytest.fixture
def ui(tmp_path, monkeypatch):
    """A create_app whose settings point at a minimal dist directory."""
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<!doctype html><title>Moadian</title>", encoding="utf-8")
    (dist / "assets").mkdir()
    (dist / "assets" / "app.js").write_text("export const x = 1\n", encoding="utf-8")

    monkeypatch.setenv("MOADIAN_STATIC_DIR", str(dist))
    monkeypatch.setenv("MOADIAN_MASTER_PASSPHRASE", "correct horse battery staple")
    monkeypatch.setenv("MOADIAN_INSTANCE_DIR", str(tmp_path / "instance"))
    # create_app reads settings once, at build time, through this cache.
    get_settings.cache_clear()
    try:
        yield create_app(users=UserStore(tmp_path / "users.sqlite"))
    finally:
        get_settings.cache_clear()


@pytest.fixture
async def http(ui):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=ui), base_url="http://api"
    ) as client:
        yield client


async def test_the_root_serves_the_ui(http: httpx.AsyncClient) -> None:
    response = await http.get("/")
    assert response.status_code == 200
    assert "Moadian" in response.text


async def test_assets_are_served(http: httpx.AsyncClient) -> None:
    assert (await http.get("/assets/app.js")).status_code == 200


async def test_the_mount_does_not_shadow_the_api(http: httpx.AsyncClient) -> None:
    """The one way this feature breaks everything.

    A mount at "/" matches any path the routes above it did not. Registered too
    early it answers /api/health with a 404 from StaticFiles, and every endpoint
    in the application disappears behind a file server.
    """
    response = await http.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"ok": True}


async def test_the_api_still_refuses_an_anonymous_call(http: httpx.AsyncClient) -> None:
    """A 401 rather than a 404 proves the route matched before the mount."""
    assert (await http.get("/api/profiles")).status_code == 401


async def test_the_openapi_schema_is_still_reachable(http: httpx.AsyncClient) -> None:
    assert (await http.get("/openapi.json")).status_code == 200


async def test_without_the_setting_there_is_no_mount(tmp_path, monkeypatch) -> None:
    """Development is unchanged: Vite serves the UI and proxies /api here."""
    monkeypatch.delenv("MOADIAN_STATIC_DIR", raising=False)
    monkeypatch.setenv("MOADIAN_MASTER_PASSPHRASE", "correct horse battery staple")
    monkeypatch.setenv("MOADIAN_INSTANCE_DIR", str(tmp_path / "instance"))
    get_settings.cache_clear()
    try:
        app = create_app(users=UserStore(tmp_path / "users.sqlite"))
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://api"
        ) as client:
            assert (await client.get("/")).status_code == 404
            assert (await client.get("/api/health")).status_code == 200
    finally:
        get_settings.cache_clear()


async def test_a_missing_dist_is_not_fatal(tmp_path, monkeypatch, caplog) -> None:
    """An API with no UI is still a working API.

    Raising here would mean a bad frontend build takes down invoice submission,
    and the operator may be starting the service precisely in order to fix it.
    """
    monkeypatch.setenv("MOADIAN_STATIC_DIR", str(tmp_path / "nowhere"))
    monkeypatch.setenv("MOADIAN_MASTER_PASSPHRASE", "correct horse battery staple")
    monkeypatch.setenv("MOADIAN_INSTANCE_DIR", str(tmp_path / "instance"))
    get_settings.cache_clear()
    try:
        app = create_app(users=UserStore(tmp_path / "users.sqlite"))
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://api"
        ) as client:
            assert (await client.get("/api/health")).status_code == 200
    finally:
        get_settings.cache_clear()
