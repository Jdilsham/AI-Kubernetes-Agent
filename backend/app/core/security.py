"""Minimal token auth: one admin password, HMAC-signed expiring tokens (no external services)."""

import hashlib
import hmac
import secrets
import time
from functools import lru_cache
from pathlib import Path

from fastapi import Header, HTTPException, Query

from app.core.config import get_settings


@lru_cache
def _secret() -> bytes:
    settings = get_settings()
    if settings.secret_key:
        return settings.secret_key.encode()
    path = Path(settings.data_dir) / "secret.key"
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(secrets.token_hex(32))
        path.chmod(0o600)
    return path.read_text().strip().encode()


def _sign(payload: str) -> str:
    return hmac.new(_secret(), payload.encode(), hashlib.sha256).hexdigest()


def check_password(password: str) -> bool:
    expected = get_settings().admin_password
    return bool(expected) and hmac.compare_digest(password.encode(), expected.encode())


def create_token() -> str:
    expires = int(time.time()) + get_settings().session_hours * 3600
    return f"{expires}.{_sign(str(expires))}"


def verify_token(token: str | None) -> bool:
    if not token or "." not in token:
        return False
    expires, signature = token.split(".", 1)
    return expires.isdigit() and int(expires) > time.time() and hmac.compare_digest(signature, _sign(expires))


def require_auth(authorization: str | None = Header(default=None), token: str | None = Query(default=None)) -> None:
    """FastAPI dependency. `token` query param is for EventSource, which cannot send headers."""
    if get_settings().auth_mode == "none":
        return
    bearer = authorization.split(" ", 1)[1] if authorization and authorization.lower().startswith("bearer ") else None
    if not verify_token(bearer or token):
        raise HTTPException(401, "Login required")
