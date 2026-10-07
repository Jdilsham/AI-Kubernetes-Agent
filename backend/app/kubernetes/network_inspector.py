import json
from typing import Any

from app.kubernetes.kubectl import run_kubectl_json, scope_args

SYSTEM_NAMESPACES = {"kube-system"}


def _suggest_selector(
    service: str, selector: dict[str, str], pods: list[tuple[str, dict[str, str]]]
) -> dict[str, str] | None:
    """The selector the Service most likely meant: the labels of the workload named like the Service.

    Only answers when exactly one candidate fits, so a wrong guess never routes traffic to the wrong pods."""
    candidates: dict[tuple, dict[str, str]] = {}
    for pod_name, labels in pods:
        if not all(k in labels for k in selector):
            continue
        values = {k: labels[k] for k in selector}
        named_like_service = (
            any(v == service for v in values.values())
            or pod_name.startswith(f"{service}-")  # Deployment/StatefulSet pods: <name>-<hash>-<id>
        )
        if named_like_service:
            candidates[tuple(sorted(values.items()))] = values
    return next(iter(candidates.values())) if len(candidates) == 1 else None


def inspect_network() -> dict[str, Any]:
    svc_res = run_kubectl_json(["get", "svc", *scope_args()])
    if not svc_res["success"]:
        return {"healthy": None, "error": svc_res["stderr"], "issues": []}
    ep_res = run_kubectl_json(["get", "endpoints", *scope_args()])
    pod_res = run_kubectl_json(["get", "pods", *scope_args()])

    ready_endpoints: set[tuple[str, str]] = set()
    for ep in (ep_res["data"] or {}).get("items", []):
        if any(s.get("addresses") for s in ep.get("subsets") or []):
            ready_endpoints.add((ep["metadata"]["namespace"], ep["metadata"]["name"]))

    pod_labels: dict[str, list[dict[str, str]]] = {}
    pod_names: dict[str, list[tuple[str, dict[str, str]]]] = {}
    for pod in (pod_res["data"] or {}).get("items", []):
        meta = pod["metadata"]
        pod_labels.setdefault(meta["namespace"], []).append(meta.get("labels") or {})
        pod_names.setdefault(meta["namespace"], []).append((meta["name"], meta.get("labels") or {}))

    issues = []
    for svc in svc_res["data"].get("items", []):
        meta = svc["metadata"]
        ns, name = meta["namespace"], meta["name"]
        spec = svc.get("spec", {})
        selector = spec.get("selector")
        if not selector or spec.get("type") == "ExternalName":
            continue
        matching = [labels for labels in pod_labels.get(ns, []) if selector.items() <= labels.items()]
        problem = None
        if not matching:
            problem = "selector_mismatch"
        elif (ns, name) not in ready_endpoints:
            problem = "no_ready_endpoints"
        if problem:
            issue = {"service": name, "namespace": ns, "issue": problem, "selector": selector}
            if problem == "selector_mismatch":
                fixed = _suggest_selector(name, selector, pod_names.get(ns, []))
                if fixed:
                    issue["suggested_selector"] = fixed
                    issue["hint"] = (
                        f"kubectl patch service {name} -n {ns} -p "
                        f"'{json.dumps({'spec': {'selector': fixed}})}'"
                    )
            issues.append(issue)

    dns = _check_dns()
    return {
        "healthy": not issues and dns["healthy"] is not False,
        "total_services": len(svc_res["data"].get("items", [])),
        "issues": issues,
        "dns": dns,
    }


def _check_dns() -> dict[str, Any]:
    res = run_kubectl_json(["get", "pods", "-n", "kube-system", "-l", "k8s-app=kube-dns"])
    if not res["success"]:
        return {"healthy": None, "error": res["stderr"]}
    pods = res["data"].get("items", [])
    ready = [p for p in pods if p.get("status", {}).get("phase") == "Running"]
    if not pods:
        return {"healthy": False, "detail": "no CoreDNS pods found"}
    return {"healthy": bool(ready), "coredns_pods": len(pods), "running": len(ready)}
