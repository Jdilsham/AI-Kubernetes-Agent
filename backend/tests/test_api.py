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


def test_ai_commands_are_kept_with_the_investigation(client, monkeypatch):
    from app.models.diagnosis import Diagnosis
    from app.services import runner, store

    def fake_analyze(data, on_step):
        for step in ("ai|Reviewing the first-look results", "ai|kubectl describe pod a", "ai|Thinking about the results", "ai|kubectl logs a"):
            on_step(step)
        return Diagnosis(root_cause="x", explanation="e", fix="f", confidence=80)

    row = store.create("in-cluster", None)
    assert row["steps"] == []
    monkeypatch.setattr(runner, "run_investigation", lambda on_step: {"pods": {"problematic_pods": []}})
    monkeypatch.setattr(runner, "analyze_investigation", fake_analyze)
    runner._run(row["id"], None, None)
    done = store.get(row["id"])
    # every command the AI chose is kept, in order, with the finished result
    assert done["status"] == "success" and done["steps"] == ["kubectl describe pod a", "kubectl logs a"]


def test_old_database_gets_the_steps_column(tmp_path, monkeypatch):
    import sqlite3

    from app.core import config
    from app.services import store

    db = sqlite3.connect(tmp_path / "agent.db")
    db.execute("CREATE TABLE investigations (id TEXT PRIMARY KEY, status TEXT NOT NULL DEFAULT 'running', progress TEXT NOT NULL DEFAULT 'starting',"
               " cluster TEXT, scope TEXT, namespace TEXT, root_cause TEXT, confidence INTEGER, diagnosis TEXT, error TEXT, created_at TEXT NOT NULL)")
    db.execute("INSERT INTO investigations (id, created_at) VALUES ('old', '2026-01-01')")
    db.commit()
    db.close()
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    config.get_settings.cache_clear()
    monkeypatch.setattr(store, "_conn", None)
    assert store.get("old")["steps"] == []
