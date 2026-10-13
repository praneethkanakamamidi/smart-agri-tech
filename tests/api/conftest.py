"""Fixtures for end-to-end API tests (need TEST_DATABASE_URL; see tests/conftest.py)."""
import itertools
import os

import pytest

pytestmark = pytest.mark.e2e
_counter = itertools.count(1)


def pytest_collection_modifyitems(config, items):
    if not os.getenv("TEST_DATABASE_URL"):
        skip = pytest.mark.skip(reason="TEST_DATABASE_URL is not set; skipping end-to-end API tests.")
        for item in items:
            if "tests" + os.sep + "api" in str(item.fspath) or "tests/api" in str(item.fspath):
                item.add_marker(skip)


@pytest.fixture(scope="session")
def client():
    from fastapi.testclient import TestClient
    from main import smart_agri_tech_app

    # One client (one event loop) for the whole session: asyncpg pools are bound to their loop.
    with TestClient(smart_agri_tech_app, raise_server_exceptions=False) as test_client:
        yield test_client


@pytest.fixture(scope="session")
def sql():
    """Run SQL directly (test setup only, e.g. promoting an admin)."""
    from sqlalchemy import text
    from src.db_connections.database import sync_engine

    def run(statement: str, **params):
        with sync_engine.begin() as conn:
            result = conn.execute(text(statement), params)
            return result.fetchall() if result.returns_rows else None

    return run


class Actor:
    def __init__(self, client, user_id: int, token: str, refresh: str, identifier: str, password: str):
        self.client, self.id, self.token, self.refresh = client, user_id, token, refresh
        self.identifier, self.password = identifier, password

    @property
    def headers(self):
        return {"Authorization": f"Bearer {self.token}"}

    def get(self, path, **kw):
        return self.client.get(path, headers={**self.headers, **kw.pop("headers", {})}, **kw)

    def post(self, path, **kw):
        return self.client.post(path, headers={**self.headers, **kw.pop("headers", {})}, **kw)

    def put(self, path, **kw):
        return self.client.put(path, headers={**self.headers, **kw.pop("headers", {})}, **kw)

    def delete(self, path, **kw):
        return self.client.request("DELETE", path, headers={**self.headers, **kw.pop("headers", {})}, **kw)


def ok(response, status=200):
    assert response.status_code == status, f"{response.request.method} {response.request.url} -> {response.status_code}: {response.text}"
    return response.json()


@pytest.fixture(scope="session")
def register(client):
    def _register(role: str, first_name: str) -> Actor:
        n = next(_counter)
        email = f"{role}{n}.{os.getpid()}@example.com"
        phone = f"+9198{os.getpid() % 100000:05d}{n:03d}"
        password = "Passw0rd!x"
        body = ok(client.post("/api/users", json={
            "email": email, "phone": phone, "first_name": first_name, "last_name": "Test",
            "password": password, "role": role if role != "admin" else "vendor",
        }))
        codes = body["debug_otp"]
        ok(client.post("/api/verify-otp", json={"user_name": phone, "otp": codes["phone"]}))
        ok(client.post("/api/verify-otp", json={"user_name": email, "otp": codes["email"]}))
        login = ok(client.post("/api/login/", data={"username": email, "password": password}))
        return Actor(client, login["id"], login["access_token"], login["refresh_token"], email, password)

    return _register


@pytest.fixture(scope="session")
def farmer(register):
    return register("farmer", "Ravi")


@pytest.fixture(scope="session")
def vendor(register):
    return register("vendor", "Sita")


@pytest.fixture(scope="session")
def admin(register, sql, client):
    actor = register("admin", "Asha")
    sql("UPDATE users SET role_id = (SELECT id FROM roles WHERE lower(name) = 'admin') WHERE id = :id", id=actor.id)
    login = ok(client.post("/api/login/", data={"username": actor.identifier, "password": actor.password}))
    actor.token = login["access_token"]
    return actor


@pytest.fixture(scope="session")
def crop_id(admin):
    ok(admin.post("/api/crops/", json={"crop_name": "Tomato", "crop_type": "vegetable", "description": "Tomato"}))
    crops = ok(admin.get("/api/crops/"))
    return next(c["id"] for c in crops if c["crop_name"] == "Tomato")
