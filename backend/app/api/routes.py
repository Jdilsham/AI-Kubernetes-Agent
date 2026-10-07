import asyncio
import json
import re

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.core.config import get_settings
from app.core.security import check_password, create_token, require_auth
from app.kubernetes.kubectl import current_context, list_contexts, list_namespaces
from app.services import runner, store

router = APIRouter(prefix="/api")
protected = APIRouter(prefix="/api", dependencies=[Depends(require_auth)])

NAMESPACE_RE = re.compile(r"[a-z0-9]([-a-z0-9]{0,61}[a-z0-9])?")


# ---------------------------------------------------------------- auth


@router.get("/auth/config", tags=["auth"])
def auth_config() -> dict:
    return {"mode": get_settings().auth_mode}


class LoginRequest(BaseModel):
    password: str


@router.post("/auth/login", tags=["auth"])
def login(body: LoginRequest) -> dict:
    if get_settings().auth_mode == "none":
        return {"token": ""}
    if not check_password(body.password):
        raise HTTPException(401, "Wrong password")
    return {"token": create_token()}


@protected.get("/auth/me", tags=["auth"])
def me() -> dict:
    return {"ok": True}


# ---------------------------------------------------------------- clusters


def _clusters() -> dict:
    data = list_contexts()
    if not data["clusters"]:  # no kubeconfig: running inside the cluster with a ServiceAccount
        return {
            "current": runner.IN_CLUSTER,
            "clusters": [{"name": runner.IN_CLUSTER, "cluster": "this cluster", "user": "service account", "current": True}],
            "error": None,
        }
    return data


@protected.get("/clusters", tags=["clusters"])
async def clusters() -> dict:
    return await run_in_threadpool(_clusters)


async def _check_cluster(cluster: str | None) -> None:
    if cluster and cluster not in {c["name"] for c in (await run_in_threadpool(_clusters))["clusters"]}:
        raise HTTPException(400, f"Cluster '{cluster}' was not found")


@protected.get("/namespaces", tags=["clusters"])
async def namespaces(cluster: str | None = Query(default=None)) -> dict:
    allowed = get_settings().allowed_namespace
    if allowed:  # namespace-scoped install
        return {"namespaces": [allowed], "error": None, "locked": True}
    await _check_cluster(cluster)

    def load() -> dict:
        current_context.set(None if cluster in (None, runner.IN_CLUSTER) else cluster)
        return list_namespaces()

    return await run_in_threadpool(load)


# ---------------------------------------------------------------- investigations


class StartRequest(BaseModel):
    cluster: str | None = None
    namespace: str | None = None  # None = all namespaces


@protected.post("/investigations", tags=["investigations"])
async def start_investigation(body: StartRequest) -> dict:
    namespace = get_settings().allowed_namespace or body.namespace
    if namespace and not NAMESPACE_RE.fullmatch(namespace):
        raise HTTPException(400, "Invalid namespace name")
    await _check_cluster(body.cluster)
    return await run_in_threadpool(runner.start, body.cluster, namespace)


@protected.get("/investigations", tags=["investigations"])
def list_investigations(
    offset: int = Query(0, ge=0), limit: int = Query(20, ge=1, le=100), status: str | None = None
) -> dict:
    rows, total = store.list_rows(offset, limit, status)
    return {"rows": rows, "total": total}


@protected.get("/investigations/{row_id}", tags=["investigations"])
def get_investigation(row_id: str) -> dict:
    row = store.get(row_id)
    if not row:
        raise HTTPException(404, "Investigation not found")
    return row


@protected.post("/investigations/{row_id}/cancel", tags=["investigations"])
def cancel_investigation(row_id: str) -> dict:
    row = store.get(row_id)
    if not row:
        raise HTTPException(404, "Investigation not found")
    if row["status"] == "running":
        runner.cancel(row_id)
    return {"status": "cancelled"}


@protected.get("/investigations/{row_id}/events", tags=["investigations"])
async def investigation_events(row_id: str) -> StreamingResponse:
    """Server-Sent Events: pushes the row whenever its progress/status changes, ends when it finishes."""
    if not store.get(row_id):
        raise HTTPException(404, "Investigation not found")

    async def stream():
        last, idle = None, 0
        while True:
            row = store.get(row_id)
            if row is None:
                return
            state = (row["status"], row["progress"])
            if state != last:
                last, idle = state, 0
                yield f"data: {json.dumps(row)}\n\n"
                if row["status"] != "running":
                    return
            else:
                idle += 1
                if idle % 15 == 0:
                    yield ": keep-alive\n\n"  # stops proxies from closing an idle stream
            await asyncio.sleep(1)

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
