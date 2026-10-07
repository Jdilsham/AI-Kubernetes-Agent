"""Auth and history API with a temporary SQLite database (no cluster needed)."""

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    from app.core import config, security
    from app.services import store

    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ADMIN_PASSWORD", "test-password")
    config.get_settings.cache_clear()
    security._secret.cache_clear()
    monkeypatch.setattr(store, "_conn", None)
    from app.main import app

    with TestClient(app) as c:
        yield c


def _token(client):
    return client.post("/api/auth/login", json={"password": "test-password"}).json()["token"]


def test_health(client):
    assert client.get("/health").json()["status"] == "healthy"


def test_auth_required(client):
    assert client.get("/api/investigations").status_code == 401
    assert client.post("/api/auth/login", json={"password": "wrong"}).status_code == 401
    assert client.get("/api/investigations", headers={"Authorization": "Bearer 1.forged"}).status_code == 401


def test_history_roundtrip(client):
    from app.services import store

    headers = {"Authorization": f"Bearer {_token(client)}"}
    row = store.create("in-cluster", "default")
    store.update(row["id"], {"status": "success", "progress": "done", "diagnosis": {"root_cause": "x"}})
    listed = client.get("/api/investigations", headers=headers).json()
    assert listed["total"] == 1 and listed["rows"][0]["status"] == "success"
    assert client.get(f"/api/investigations/{row['id']}", headers=headers).json()["diagnosis"] == {"root_cause": "x"}


def test_invalid_namespace_rejected(client):
    headers = {"Authorization": f"Bearer {_token(client)}"}
    assert client.post("/api/investigations", json={"namespace": "Bad NS!"}, headers=headers).status_code == 400
