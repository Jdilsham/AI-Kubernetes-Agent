from typing import Any

from app.kubernetes.kubectl import run_kubectl_json, scope_args


def inspect_deployments() -> dict[str, Any]:
    result = run_kubectl_json(["get", "deployments", *scope_args()])
    if not result["success"]:
        return {"healthy": None, "error": result["stderr"], "unhealthy_deployments": []}

    unhealthy = []
    items = result["data"].get("items", [])
    for dep in items:
        status = dep.get("status", {})
        desired = dep.get("spec", {}).get("replicas", 1)
        available = status.get("availableReplicas", 0)
        unavailable = status.get("unavailableReplicas", 0)
        conditions = status.get("conditions", [])
        bad_conditions = [
            {"type": c["type"], "reason": c.get("reason"), "message": c.get("message", "")[:200]}
            for c in conditions
            if (c["type"] == "Available" and c["status"] != "True")
            or (c["type"] == "Progressing" and c.get("reason") == "ProgressDeadlineExceeded")
            or c["type"] == "ReplicaFailure"
        ]
        if available < desired or unavailable or bad_conditions:
            unhealthy.append(
                {
                    "name": dep["metadata"]["name"],
                    "namespace": dep["metadata"]["namespace"],
                    "desired_replicas": desired,
                    "available_replicas": available,
                    "unavailable_replicas": unavailable,
                    "rollout_failed": any(
                        c["reason"] == "ProgressDeadlineExceeded" for c in bad_conditions
                    ),
                    "conditions": bad_conditions,
                }
            )
    return {
        "healthy": not unhealthy,
        "total_deployments": len(items),
        "unhealthy_deployments": unhealthy,
    }
