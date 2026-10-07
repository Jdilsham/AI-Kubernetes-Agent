"""Investigation history in SQLite (one file on the backend's volume)."""

import json
import sqlite3
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.core.config import get_settings

_lock = threading.Lock()
_conn: sqlite3.Connection | None = None
COLUMNS = ("id", "status", "progress", "cluster", "scope", "namespace", "root_cause", "confidence", "diagnosis", "error", "created_at")


def _db() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        path = Path(get_settings().data_dir) / "agent.db"
        path.parent.mkdir(parents=True, exist_ok=True)
        _conn = sqlite3.connect(path, check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.execute(
            """CREATE TABLE IF NOT EXISTS investigations (
                id TEXT PRIMARY KEY,
                status TEXT NOT NULL DEFAULT 'running',
                progress TEXT NOT NULL DEFAULT 'starting',
                cluster TEXT, scope TEXT, namespace TEXT, root_cause TEXT,
                confidence INTEGER, diagnosis TEXT, error TEXT,
                created_at TEXT NOT NULL)"""
        )
        _conn.execute("CREATE INDEX IF NOT EXISTS investigations_created ON investigations (created_at DESC)")
        _conn.commit()
    return _conn


def _row(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    data = dict(row)
    data["diagnosis"] = json.loads(data["diagnosis"]) if data.get("diagnosis") else None
    return data


def create(cluster: str | None, scope: str | None) -> dict[str, Any]:
    row_id = str(uuid.uuid4())
    now = datetime.now(UTC).isoformat()
    with _lock:
        _db().execute(
            "INSERT INTO investigations (id, cluster, scope, created_at) VALUES (?, ?, ?, ?)", (row_id, cluster, scope, now)
        )
        _db().commit()
    return get(row_id)  # type: ignore[return-value]


def update(row_id: str, fields: dict[str, Any]) -> None:
    fields = {k: (json.dumps(v) if k == "diagnosis" and v is not None else v) for k, v in fields.items() if k in COLUMNS}
    if not fields:
        return
    with _lock:
        _db().execute(
            f"UPDATE investigations SET {', '.join(f'{k} = ?' for k in fields)} WHERE id = ?", (*fields.values(), row_id)
        )
        _db().commit()


def get(row_id: str) -> dict[str, Any] | None:
    with _lock:
        return _row(_db().execute("SELECT * FROM investigations WHERE id = ?", (row_id,)).fetchone())


def list_rows(offset: int, limit: int, status: str | None = None) -> tuple[list[dict[str, Any]], int]:
    where, args = ("WHERE status = ?", (status,)) if status else ("", ())
    with _lock:
        total = _db().execute(f"SELECT COUNT(*) FROM investigations {where}", args).fetchone()[0]
        rows = _db().execute(
            f"SELECT id, status, progress, cluster, scope, namespace, root_cause, confidence, created_at "
            f"FROM investigations {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (*args, limit, offset),
        ).fetchall()
    return [dict(r) for r in rows], total


def fail_running() -> None:
    """At startup: runs still marked 'running' were killed by the restart."""
    with _lock:
        _db().execute(
            "UPDATE investigations SET status = 'failed', progress = 'done', "
            "error = 'Interrupted: the server restarted during this investigation.' WHERE status = 'running'"
        )
        _db().commit()
