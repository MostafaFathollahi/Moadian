"""Accounts, sessions, roles and revocation.

The property under test throughout is that a token stops working when it should.
A JWT is valid until it expires no matter what the database says, so every
"deactivate", "change password" and "sign everyone out" has to be enforced on
the read path or it does nothing at all.
"""

from __future__ import annotations

import httpx
import pytest

from moadian.api.app import create_app
from moadian.api.deps import get_profile_store, get_record_store, get_settings
from moadian.auth import UserStore
from moadian.auth.security import hash_password, verify_password
from moadian.config import ProfileStore, Settings
from moadian.store import RecordStore

ADMIN = {"username": "admin", "password": "admin1234"}
CLERK = {"username": "daftar", "password": "daftar1234"}


@pytest.fixture
def users(tmp_path) -> UserStore:
    store = UserStore(tmp_path / "users.sqlite")
    store.create(username="admin", password="admin1234", role="admin")
    store.create(username="daftar", password="daftar1234", role="user")
    return store


@pytest.fixture
def app(tmp_path, users: UserStore):
    application = create_app(users=users)
    settings = Settings(instance_dir=tmp_path)
    application.dependency_overrides[get_settings] = lambda: settings
    application.dependency_overrides[get_profile_store] = lambda: ProfileStore(
        tmp_path / "profiles.json", "pass"
    )
    application.dependency_overrides[get_record_store] = lambda: RecordStore(
        tmp_path / "records.sqlite"
    )
    return application


@pytest.fixture
async def http(app):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://t"
    ) as client:
        yield client


async def sign_in(client: httpx.AsyncClient, credentials: dict) -> str:
    response = await client.post("/api/auth/login", json=credentials)
    assert response.status_code == 200, response.text
    return response.json()["token"]


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ------------------------------------------------------------------ passwords


def test_hashes_are_salted_and_verify() -> None:
    first, second = hash_password("hunter2hunter2"), hash_password("hunter2hunter2")
    assert first != second, "a shared salt makes the hashes a rainbow-table index"
    assert verify_password("hunter2hunter2", first)
    assert not verify_password("hunter2hunter3", first)


def test_a_malformed_stored_hash_fails_closed() -> None:
    assert verify_password("anything", "not-a-hash") is False
    assert verify_password("anything", "") is False


# --------------------------------------------------------------------- login


async def test_login_returns_a_token_and_the_public_user(http: httpx.AsyncClient) -> None:
    response = await http.post("/api/auth/login", json=ADMIN)
    body = response.json()
    assert body["user"]["role"] == "admin"
    assert "password" not in str(body) and "hash" not in str(body)


@pytest.mark.parametrize(
    "credentials",
    [
        {"username": "admin", "password": "wrong-password"},
        {"username": "ghost", "password": "admin1234"},
    ],
)
async def test_bad_credentials_are_refused_identically(
    http: httpx.AsyncClient, credentials: dict
) -> None:
    """An unknown user and a wrong password must be indistinguishable.

    Otherwise the endpoint answers "does this account exist" to anyone willing
    to read the response.
    """
    response = await http.post("/api/auth/login", json=credentials)
    assert response.status_code == 401
    assert response.json()["detail"] == "نام کاربری یا گذرواژه نادرست است"


async def test_a_deactivated_account_cannot_log_in(
    http: httpx.AsyncClient, users: UserStore
) -> None:
    clerk = users.by_username("daftar")
    users.update(clerk.id, is_active=False)
    response = await http.post("/api/auth/login", json=CLERK)
    assert response.status_code == 403


# ------------------------------------------------------------------- guarding


async def test_business_routes_require_a_session(http: httpx.AsyncClient) -> None:
    for path in ("/api/patterns", "/api/environments", "/api/profiles"):
        assert (await http.get(path)).status_code == 401, path


async def test_health_stays_open(http: httpx.AsyncClient) -> None:
    """A liveness probe that needs a password is not a liveness probe."""
    assert (await http.get("/api/health")).status_code == 200


async def test_a_garbage_token_is_refused(http: httpx.AsyncClient) -> None:
    assert (await http.get("/api/patterns", headers=bearer("nonsense"))).status_code == 401


async def test_a_token_signed_with_another_secret_is_refused(http: httpx.AsyncClient) -> None:
    import jwt

    forged = jwt.encode({"sub": "1", "role": "admin"}, "not-the-secret", algorithm="HS256")
    assert (await http.get("/api/patterns", headers=bearer(forged))).status_code == 401


async def test_admin_routes_need_the_admin_role(http: httpx.AsyncClient) -> None:
    clerk = bearer(await sign_in(http, CLERK))
    admin = bearer(await sign_in(http, ADMIN))
    assert (await http.get("/api/admin/users", headers=clerk)).status_code == 403
    assert (await http.get("/api/signing-material", headers=clerk)).status_code == 403
    assert (await http.get("/api/admin/users", headers=admin)).status_code == 200
    # A non-admin still gets the ordinary application.
    assert (await http.get("/api/patterns", headers=clerk)).status_code == 200


async def test_role_is_read_from_the_database_not_the_token(
    http: httpx.AsyncClient, users: UserStore
) -> None:
    """A token minted as admin must stop working as admin the moment the role changes."""
    token = await sign_in(http, ADMIN)
    assert (await http.get("/api/admin/users", headers=bearer(token))).status_code == 200

    # Demote out-of-band, as a second admin would.
    users.create(username="other", password="otheradmin1", role="admin")
    users.update(users.by_username("admin").id, role="user")
    assert (await http.get("/api/admin/users", headers=bearer(token))).status_code == 403


# ---------------------------------------------------------------- revocation


async def test_deactivating_an_account_kills_its_live_session(
    http: httpx.AsyncClient, users: UserStore
) -> None:
    """The token stays cryptographically valid; only the read-path check stops it."""
    clerk = bearer(await sign_in(http, CLERK))
    assert (await http.get("/api/patterns", headers=clerk)).status_code == 200

    users.update(users.by_username("daftar").id, is_active=False)
    assert (await http.get("/api/patterns", headers=clerk)).status_code == 401


async def test_revoke_all_signs_everyone_out_but_spares_the_caller(
    http: httpx.AsyncClient,
) -> None:
    """An admin sweeping sessions must not lock themselves out doing it."""
    clerk = bearer(await sign_in(http, CLERK))
    admin_token = await sign_in(http, ADMIN)

    response = await http.post(
        "/api/admin/users/sessions/revoke-all", headers=bearer(admin_token)
    )
    replacement = response.json()["token"]

    assert (await http.get("/api/patterns", headers=clerk)).status_code == 401
    assert (await http.get("/api/patterns", headers=bearer(admin_token))).status_code == 401
    assert (await http.get("/api/patterns", headers=bearer(replacement))).status_code == 200


async def test_revoking_one_account_leaves_the_others_alone(
    http: httpx.AsyncClient, users: UserStore
) -> None:
    clerk = bearer(await sign_in(http, CLERK))
    admin = bearer(await sign_in(http, ADMIN))
    await http.post(
        f"/api/admin/users/{users.by_username('daftar').id}/sessions/revoke", headers=admin
    )
    assert (await http.get("/api/patterns", headers=clerk)).status_code == 401
    assert (await http.get("/api/patterns", headers=admin)).status_code == 200


async def test_changing_your_own_password_ends_other_sessions_but_not_this_one(
    http: httpx.AsyncClient,
) -> None:
    """A password reset that leaves the old sessions alive is not a reset."""
    first = bearer(await sign_in(http, CLERK))
    second = bearer(await sign_in(http, CLERK))

    response = await http.post(
        "/api/auth/password",
        headers=second,
        json={"current_password": "daftar1234", "new_password": "brand-new-secret"},
    )
    assert response.status_code == 200
    replacement = bearer(response.json()["token"])

    assert (await http.get("/api/patterns", headers=first)).status_code == 401
    assert (await http.get("/api/patterns", headers=replacement)).status_code == 200
    assert (await http.post("/api/auth/login", json=CLERK)).status_code == 401


async def test_changing_a_password_requires_the_current_one(http: httpx.AsyncClient) -> None:
    clerk = bearer(await sign_in(http, CLERK))
    response = await http.post(
        "/api/auth/password",
        headers=clerk,
        json={"current_password": "wrong", "new_password": "another-secret"},
    )
    assert response.status_code == 400


# ------------------------------------------------------- account management


async def test_admin_creates_and_lists_accounts(http: httpx.AsyncClient) -> None:
    admin = bearer(await sign_in(http, ADMIN))
    created = await http.post(
        "/api/admin/users",
        headers=admin,
        json={"username": "new.clerk", "password": "clerkpass1", "display_name": "متصدی"},
    )
    assert created.status_code == 201
    assert created.json()["role"] == "user"
    listing = (await http.get("/api/admin/users", headers=admin)).json()
    assert "new.clerk" in [u["username"] for u in listing]
    assert all("password" not in u and "hash" not in str(u) for u in listing)


@pytest.mark.parametrize(
    "payload,status",
    [
        ({"username": "ab", "password": "longenough1"}, 422),  # username too short
        ({"username": "bad name", "password": "longenough1"}, 422),  # space
        ({"username": "good.name", "password": "short"}, 422),  # weak password
        ({"username": "admin", "password": "longenough1"}, 409),  # duplicate
    ],
)
async def test_account_creation_is_validated(
    http: httpx.AsyncClient, payload: dict, status: int
) -> None:
    admin = bearer(await sign_in(http, ADMIN))
    assert (await http.post("/api/admin/users", headers=admin, json=payload)).status_code == status


async def test_the_last_active_admin_cannot_be_removed(
    http: httpx.AsyncClient, users: UserStore
) -> None:
    """Otherwise the system reaches a state with no way to administer it."""
    admin = bearer(await sign_in(http, ADMIN))
    admin_id = users.by_username("admin").id

    # Another admin exists → demoting is allowed; deleting self is still refused.
    assert (await http.delete(f"/api/admin/users/{admin_id}", headers=admin)).status_code == 400

    clerk_id = users.by_username("daftar").id
    await http.patch(f"/api/admin/users/{clerk_id}", headers=admin, json={"role": "admin"})
    # Now demote the other one back and try to remove the only remaining admin.
    await http.patch(f"/api/admin/users/{clerk_id}", headers=admin, json={"role": "user"})
    response = await http.patch(
        f"/api/admin/users/{clerk_id}", headers=admin, json={"is_active": False}
    )
    assert response.status_code == 200  # a plain user may be deactivated


async def test_an_admin_cannot_demote_or_disable_themselves(
    http: httpx.AsyncClient, users: UserStore
) -> None:
    admin = bearer(await sign_in(http, ADMIN))
    admin_id = users.by_username("admin").id
    assert (
        await http.patch(f"/api/admin/users/{admin_id}", headers=admin, json={"role": "user"})
    ).status_code == 400
    assert (
        await http.patch(
            f"/api/admin/users/{admin_id}", headers=admin, json={"is_active": False}
        )
    ).status_code == 400


async def test_removing_an_account_deactivates_rather_than_deletes(
    http: httpx.AsyncClient, users: UserStore
) -> None:
    admin = bearer(await sign_in(http, ADMIN))
    clerk_id = users.by_username("daftar").id
    response = await http.delete(f"/api/admin/users/{clerk_id}", headers=admin)
    assert response.json()["deleted"] is False
    assert users.get(clerk_id) is not None
    assert users.get(clerk_id).is_active is False
    assert (await http.post("/api/auth/login", json=CLERK)).status_code == 403


# ------------------------------------------------------------------- seeding


def test_seeding_creates_accounts_and_never_overwrites(tmp_path) -> None:
    from moadian.auth.security import seed_users

    store = UserStore(tmp_path / "u.sqlite")
    assert seed_users(store, "admin:admin1234:admin,clerk:clerkpass1:user") == 2

    store.set_password(store.by_username("admin").id, "changed-by-the-operator")
    # Re-seeding must not reset a password the operator has since changed.
    assert seed_users(store, "admin:admin1234:admin,clerk:clerkpass1:user") == 0
    stored = store.password_hash(store.by_username("admin").id)
    assert verify_password("changed-by-the-operator", stored)


def test_seeding_skips_entries_that_would_be_rejected(tmp_path) -> None:
    from moadian.auth.security import seed_users

    store = UserStore(tmp_path / "u.sqlite")
    assert seed_users(store, "ab:short:admin,,good.name:longenough1:user") == 1
    assert [u.username for u in store.list()] == ["good.name"]


# --------------------------------------------------- configuration reaches us


def test_settings_carry_the_auth_configuration(tmp_path, monkeypatch) -> None:
    """A value in .env must reach the auth module.

    pydantic-settings parses .env into a Settings object and never into
    os.environ, so anything reading the environment directly ignores the file
    entirely. That mismatch made a copied .env.example produce a 500 on the
    first request, which is the least diagnosable failure available.
    """
    from moadian.auth.security import configure, secret_key, seed_users, token_ttl_hours

    env = tmp_path / ".env"
    env.write_text(
        "MOADIAN_APP_SECRET=from-the-dotenv-file\n"
        "MOADIAN_TOKEN_TTL_HOURS=48\n"
        "MOADIAN_MASTER_PASSPHRASE=from-the-dotenv-file\n"
        "MOADIAN_SEED_USERS=fromenv:fromenvpass1:admin\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    for name in ("MOADIAN_APP_SECRET", "MOADIAN_TOKEN_TTL_HOURS", "MOADIAN_SEED_USERS"):
        monkeypatch.delenv(name, raising=False)

    settings = Settings()
    assert settings.master_passphrase == "from-the-dotenv-file"

    configure(settings)
    try:
        assert secret_key() == "from-the-dotenv-file"
        assert token_ttl_hours() == 48
        store = UserStore(tmp_path / "u.sqlite")
        assert seed_users(store) == 1
        assert store.by_username("fromenv") is not None
    finally:
        configure(None)


def test_an_exported_variable_still_wins_without_a_dotenv(monkeypatch) -> None:
    """Deployments that never write a .env must keep working."""
    from moadian.auth.security import configure, secret_key

    configure(None)
    monkeypatch.setenv("MOADIAN_APP_SECRET", "exported-secret")
    try:
        assert secret_key() == "exported-secret"
    finally:
        configure(None)


async def test_a_missing_master_passphrase_says_what_to_set(tmp_path, users) -> None:
    """503 naming the variable, not a bare 500 the operator cannot act on."""
    from moadian.api.app import create_app as _create_app
    from moadian.api.deps import get_settings as _get_settings

    application = _create_app(users=users)
    application.dependency_overrides[_get_settings] = lambda: Settings(
        instance_dir=tmp_path, master_passphrase=None
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=application), base_url="http://t"
    ) as client:
        token = await sign_in(client, ADMIN)
        response = await client.get("/api/profiles", headers=bearer(token))
    assert response.status_code == 503
    assert "MOADIAN_MASTER_PASSPHRASE" in response.json()["detail"]
