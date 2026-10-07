from collections.abc import Callable
from typing import Any

from loguru import logger

from app.kubernetes.deployment_inspector import inspect_deployments
from app.kubernetes.events_analyzer import analyze_events
from app.kubernetes.logs_collector import collect_logs
from app.kubernetes.network_inspector import inspect_network
from app.kubernetes.node_inspector import inspect_nodes
from app.kubernetes.pod_details import collect_pod_details
from app.kubernetes.pod_inspector import inspect_pods
from app.kubernetes.resources import inspect_resources


def run_investigation(on_step: Callable[[str], None] | None = None) -> dict[str, Any]:
    """Collect Kubernetes evidence step by step (no AI reasoning yet)."""
    def step(name: str) -> None:
        if on_step:
            on_step(name)

    logger.info("Investigation started")
    step("pods")
    pods = inspect_pods()
    nodes = inspect_nodes() if pods.get("healthy") is not None else {}
    if pods.get("healthy") is None:
        # First call failed (cluster unreachable / kubectl missing): don't repeat it 4 more times.
        skipped = {"skipped": True, "error": pods["error"]}
        return {
            "pods": pods,
            "logs": skipped,
            "events": skipped,
            "deployments": skipped,
            "network": skipped,
            "nodes": skipped,
            "resources": skipped,
        }
    step("logs")
    logs = collect_logs(pods.get("problematic_pods", []))
    pod_details = collect_pod_details(pods.get("problematic_pods", []))
    step("events")
    events = analyze_events()
    step("deployments")
    deployments = inspect_deployments()
    step("network")
    network = inspect_network()
    step("resources")
    resources = inspect_resources(pods.get("problematic_pods", []), pod_details, logs, nodes)
    logger.info("Investigation finished")
    return {
        "pods": pods,
        "logs": logs,
        "events": events,
        "deployments": deployments,
        "network": network,
        "nodes": nodes,
        "pod_details": pod_details,
        "resources": resources,
    }
