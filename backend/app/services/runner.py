"""Runs investigations in background threads and records progress in the store."""

import threading
from typing import Any

from loguru import logger

from app.ai.agent import ClusterUnreachable, analyze_investigation
from app.ai.llm_client import LLMError
from app.kubernetes.kubectl import current_context, current_namespace
from app.services import store
from app.services.investigation_service import run_investigation

IN_CLUSTER = "in-cluster"
_cancelled: set[str] = set()


class InvestigationCancelled(Exception):
    pass


def _namespace(data: dict[str, Any]) -> str:
    namespaces = {p["namespace"] for p in data["pods"].get("problematic_pods", [])}
    return ", ".join(sorted(namespaces)) if namespaces else "all"


def _root_cause_label(diagnosis: Any) -> str:
    extra = len(diagnosis.issues) - 1
    return f"{diagnosis.root_cause} (+{extra} more issue{'s' if extra > 1 else ''})" if extra > 0 else diagnosis.root_cause


def _run(row_id: str, cluster: str | None, namespace: str | None) -> None:
    current_context.set(None if cluster in (None, IN_CLUSTER) else cluster)
    current_namespace.set(namespace)

    def progress(step: str) -> None:
        if row_id in _cancelled:
            raise InvestigationCancelled()
        store.update(row_id, {"progress": step})

    try:
        data = run_investigation(on_step=progress)
        progress("ai")
        affected = _namespace(data)
        try:
            diagnosis = analyze_investigation(data)
        except ClusterUnreachable as exc:
            store.update(row_id, {"status": "failed", "progress": "done", "error": str(exc)})
            return
        except LLMError as exc:  # evidence was collected; only the AI step failed
            logger.error("AI analysis failed: {}", exc)
            store.update(row_id, {"status": "partial", "progress": "done", "namespace": affected, "error": str(exc)})
            return
        if row_id in _cancelled:
            raise InvestigationCancelled()
        store.update(row_id, {
            "status": "success",
            "progress": "done",
            "namespace": affected,
            "root_cause": _root_cause_label(diagnosis),
            "confidence": diagnosis.confidence,
            "diagnosis": diagnosis.model_dump(),
        })
    except InvestigationCancelled:
        logger.info("Investigation {} cancelled", row_id)
    except Exception:  # noqa: BLE001 - never leave a row stuck in "running"
        logger.exception("Investigation crashed")
        store.update(row_id, {"status": "failed", "progress": "done", "error": "Unexpected server error. Check the backend logs."})
    finally:
        _cancelled.discard(row_id)


def start(cluster: str | None, namespace: str | None) -> dict[str, Any]:
    row = store.create(cluster, namespace)
    threading.Thread(target=_run, args=(row["id"], cluster, namespace), daemon=True, name=f"investigation-{row['id'][:8]}").start()
    return row


def cancel(row_id: str) -> None:
    _cancelled.add(row_id)
    store.update(row_id, {"status": "cancelled"})
