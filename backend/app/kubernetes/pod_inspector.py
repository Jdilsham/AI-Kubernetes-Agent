from typing import Any

from app.kubernetes.kubectl import friendly_error, run_kubectl_json, scope_args

BAD_WAITING_REASONS = {
    "CrashLoopBackOff",
    "ImagePullBackOff",
    "ErrImagePull",
    "CreateContainerConfigError",
    "RunContainerError",
    "InvalidImageName",
}


def _pod_problem(pod: dict[str, Any]) -> str | None:
    """Return a problem label for the pod, or None if healthy."""
    status = pod.get("status", {})
    phase = status.get("phase")
    if phase == "Succeeded":  # finished jobs are fine
        return None

    containers = status.get("containerStatuses", []) + status.get("initContainerStatuses", [])
    for cs in containers:
        waiting = cs.get("state", {}).get("waiting") or {}
        reason = waiting.get("reason")
        if reason in BAD_WAITING_REASONS:
            return reason
        if reason == "ContainerCreating":
            return "ContainerCreating"
    for cs in containers:
        terminated = cs.get("state", {}).get("terminated") or {}
        last = cs.get("lastState", {}).get("terminated") or {}
        if terminated.get("reason") == "OOMKilled" or last.get("reason") == "OOMKilled":
            return "OOMKilled"
        if terminated and terminated.get("reason") != "Completed" and terminated.get("exitCode", 0) != 0:
            return terminated.get("reason") or "Error"

    if phase == "Pending":
        return "Pending"
    if phase == "Failed":
        return status.get("reason") or "Error"

    # Running, but a container is not ready (failing readiness/startup probe).
    main = status.get("containerStatuses", [])
    if phase == "Running" and any(not cs.get("ready") for cs in main):
        return "NotReady"
    return None


def _fix_target(pod_name: str, owner: dict[str, Any]) -> str:
    """The object a config fix should be applied to (so the fix survives pod restarts)."""
    kind, name = owner.get("kind"), owner.get("name", "")
    if kind == "ReplicaSet":  # Deployment pods: ReplicaSet name is <deployment>-<hash>
        return f"deployment/{name.rsplit('-', 1)[0]}"
    if kind in ("StatefulSet", "DaemonSet", "Job"):
        return f"{kind.lower()}/{name}"
    return f"pod/{pod_name}"  # bare pod: its image/labels can be patched in place


def _details(pod: dict[str, Any]) -> dict[str, Any]:
    status = pod.get("status", {})
    main = status.get("containerStatuses", [])
    details: dict[str, Any] = {
        "ready": f"{sum(1 for c in main if c.get('ready'))}/{len(main)}" if main else "0/0",
        "restarts": sum(c.get("restartCount", 0) for c in main),
        "node": pod.get("spec", {}).get("nodeName"),
    }
    owner = (pod["metadata"].get("ownerReferences") or [{}])[0]
    if owner.get("name"):
        details["owner"] = f"{owner.get('kind')}/{owner['name']}"
    details["fix_target"] = _fix_target(pod["metadata"]["name"], owner)
    for cs in main:
        last = cs.get("lastState", {}).get("terminated") or cs.get("state", {}).get("terminated")
        if last:
            details["last_termination"] = {
                "container": cs.get("name"),
                "reason": last.get("reason"),
                "exit_code": last.get("exitCode"),
            }
            break
    return details


def inspect_pods() -> dict[str, Any]:
    result = run_kubectl_json(["get", "pods", *scope_args()])
    if not result["success"]:
        return {"healthy": None, "error": friendly_error(result["stderr"]), "problematic_pods": []}

    items = result["data"].get("items", [])
    by_owner: dict[str, list[dict[str, Any]]] = {}
    for pod in items:
        owner = (pod["metadata"].get("ownerReferences") or [{}])[0].get("name")
        if owner:
            main = pod.get("status", {}).get("containerStatuses", [])
            by_owner.setdefault(f"{pod['metadata']['namespace']}/{owner}", []).append(
                {
                    "name": pod["metadata"]["name"],
                    "phase": pod.get("status", {}).get("phase"),
                    "ready": f"{sum(1 for c in main if c.get('ready'))}/{len(main)}",
                }
            )
    problems = []
    for pod in items:
        problem = _pod_problem(pod)
        if problem:
            meta = pod["metadata"]
            entry = {"name": meta["name"], "namespace": meta["namespace"], "status": problem, **_details(pod)}
            owner = (meta.get("ownerReferences") or [{}])[0].get("name")
            siblings = [x for x in by_owner.get(f"{meta['namespace']}/{owner}", []) if x["name"] != meta["name"]]
            if siblings:  # lets the AI see e.g. "another replica of this deployment is Running"
                entry["sibling_pods"] = siblings[:5]
            problems.append(entry)
    return {"healthy": not problems, "total_pods": len(items), "problematic_pods": problems}
