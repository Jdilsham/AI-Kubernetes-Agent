from typing import Any

from app.kubernetes.kubectl import redact, run_kubectl_json

MAX_PODS = 8
MAX_EVENTS = 8


def _env(container: dict[str, Any]) -> list[str]:
    """Env var names and where they come from. Values are never collected."""
    out = []
    for e in container.get("env") or []:
        ref = (e.get("valueFrom") or {})
        if "secretKeyRef" in ref:
            out.append(f"{e['name']} <- secret {ref['secretKeyRef'].get('name')}/{ref['secretKeyRef'].get('key')}")
        elif "configMapKeyRef" in ref:
            out.append(f"{e['name']} <- configmap {ref['configMapKeyRef'].get('name')}/{ref['configMapKeyRef'].get('key')}")
        else:
            out.append(e["name"])
    for src in container.get("envFrom") or []:
        for kind in ("secretRef", "configMapRef"):
            if kind in src:
                out.append(f"envFrom {kind[:-3]} {src[kind].get('name')}")
    return out


def _probe(probe: dict[str, Any] | None) -> str | None:
    if not probe:
        return None
    kind = next((k for k in ("httpGet", "tcpSocket", "exec") if k in probe), "probe")
    target = probe.get(kind) or {}
    where = target.get("path", "") + (f":{target['port']}" if "port" in target else "")
    return f"{kind} {where} period={probe.get('periodSeconds')}s failureThreshold={probe.get('failureThreshold')}".strip()


def _state(cs: dict[str, Any]) -> dict[str, Any]:
    def brief(s: dict[str, Any] | None) -> dict[str, Any] | None:
        if not s:
            return None
        kind, body = next(iter(s.items()))
        return {"state": kind, **{k: v for k, v in body.items() if k in ("reason", "message", "exitCode") and v not in (None, "")}}

    return {
        "name": cs.get("name"),
        "ready": cs.get("ready"),
        "restarts": cs.get("restartCount"),
        "state": brief(cs.get("state")),
        "last_state": brief(cs.get("lastState")),
    }


def _summarize(pod: dict[str, Any]) -> dict[str, Any]:
    spec, status = pod.get("spec", {}), pod.get("status", {})
    containers = []
    for c in spec.get("containers", []):
        containers.append(
            {
                "name": c["name"],
                "image": c.get("image"),
                "command": redact(" ".join((c.get("command") or []) + (c.get("args") or [])))[:300] or None,
                "resources": c.get("resources") or None,
                "env": _env(c),
                "readiness_probe": _probe(c.get("readinessProbe")),
                "liveness_probe": _probe(c.get("livenessProbe")),
                "startup_probe": _probe(c.get("startupProbe")),
            }
        )
    volumes = []
    for v in spec.get("volumes", []):
        for kind in ("secret", "configMap", "persistentVolumeClaim"):
            if kind in v:
                ref = v[kind].get("secretName") or v[kind].get("name") or v[kind].get("claimName")
                volumes.append(f"{kind} {ref}")
    return {
        "containers": containers,
        "init_containers": [{"name": c["name"], "image": c.get("image")} for c in spec.get("initContainers", [])],
        "volumes": volumes,
        "node_selector": spec.get("nodeSelector"),
        "tolerations": [
            {k: t.get(k) for k in ("key", "operator", "effect") if t.get(k)} for t in spec.get("tolerations", [])
            if t.get("key") not in ("node.kubernetes.io/not-ready", "node.kubernetes.io/unreachable")
        ] or None,
        "restart_policy": spec.get("restartPolicy"),
        "image_pull_secrets": [s.get("name") for s in spec.get("imagePullSecrets", [])] or None,
        "failing_conditions": [
            {"type": c["type"], "reason": c.get("reason"), "message": (c.get("message") or "")[:200]}
            for c in status.get("conditions", [])
            if c.get("status") != "True"
        ],
        "container_states": [_state(cs) for cs in status.get("containerStatuses", [])],
    }


def _events(namespace: str, name: str) -> list[dict[str, Any]]:
    res = run_kubectl_json(["get", "events", "-n", namespace, "--field-selector", f"involvedObject.name={name}"])
    if not res["success"]:
        return []
    items = sorted(res["data"].get("items", []), key=lambda e: e.get("lastTimestamp") or e.get("eventTime") or "")
    return [
        {"type": e.get("type"), "reason": e.get("reason"), "message": redact(e.get("message") or "")[:250], "count": e.get("count") or 1}
        for e in items[-MAX_EVENTS:]
    ]


def collect_pod_details(problematic_pods: list[dict[str, Any]]) -> dict[str, Any]:
    """Spec, container states and full event history of each failing pod (what `kubectl describe` shows)."""
    details: dict[str, Any] = {}
    for pod in problematic_pods[:MAX_PODS]:
        ns, name = pod["namespace"], pod["name"]
        res = run_kubectl_json(["get", "pod", name, "-n", ns])
        if not res["success"]:
            continue
        details[f"{ns}/{name}"] = {**_summarize(res["data"]), "events": _events(ns, name)}
    return details
