import re
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

from app.kubernetes.kubectl import run_kubectl, run_kubectl_json, scope_args

INTERESTING_REASONS = {
    "FailedScheduling",
    "BackOff",
    "FailedMount",
    "FailedAttachVolume",
    "Failed",
    "FailedPull",
    "ErrImagePull",
    "ImagePullBackOff",
    "Unhealthy",
    "OOMKilling",
    "Evicted",
}
MAX_FINDINGS = 30


RECENT_MINUTES = 30


def _existing(kind: str) -> set[str] | None:
    """Names ('namespace/name' for pods, 'name' for nodes) that exist now, or None if unreadable."""
    template = (
        '{range .items[*]}{.metadata.namespace}/{.metadata.name}{"\\n"}{end}'
        if kind == "pods"
        else '{range .items[*]}{.metadata.name}{"\\n"}{end}'
    )
    flags = ["-A"] if kind == "pods" else []
    res = run_kubectl(["get", kind, *flags, "-o", f"jsonpath={template}"])
    return set(res["stdout"].split()) if res["success"] else None


def _is_recent(ts: str | None) -> bool:
    if not ts:
        return True
    try:
        seen = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return True
    return datetime.now(UTC) - seen < timedelta(minutes=RECENT_MINUTES)


def analyze_events() -> dict[str, Any]:
    result = run_kubectl_json(["get", "events", *scope_args()])
    if not result["success"]:
        return {"error": result["stderr"], "findings": []}

    pods_now, nodes_now = _existing("pods"), _existing("nodes")
    grouped: dict[tuple, dict[str, Any]] = defaultdict(dict)
    for ev in result["data"].get("items", []):
        reason = ev.get("reason")
        if reason not in INTERESTING_REASONS and ev.get("type") != "Warning":
            continue
        obj = ev.get("involvedObject", {})
        # Events outlive the objects they describe (~1h): skip stale ones.
        ns = ev["metadata"].get("namespace")
        if not _is_recent(ev.get("lastTimestamp") or ev.get("eventTime")):
            continue
        if pods_now is not None and obj.get("kind") == "Pod" and f"{ns}/{obj.get('name')}" not in pods_now:
            continue
        if nodes_now is not None:
            if obj.get("kind") == "Node" and obj.get("name") not in nodes_now:
                continue
            missing = re.search(r"Node (\S+) Not Found", ev.get("message") or "")
            if missing and missing.group(1) not in nodes_now:
                continue
        key = (ev["metadata"].get("namespace"), obj.get("kind"), obj.get("name"), reason)
        entry = grouped[key]
        entry.update(
            namespace=key[0],
            kind=key[1],
            object=key[2],
            reason=reason,
            message=(ev.get("message") or "")[:300],
            last_seen=ev.get("lastTimestamp") or ev.get("eventTime"),
        )
        entry["count"] = entry.get("count", 0) + (ev.get("count") or 1)

    findings = sorted(grouped.values(), key=lambda e: e["count"], reverse=True)
    return {
        "total_findings": len(findings),
        "reasons": sorted({f["reason"] for f in findings}),
        "findings": findings[:MAX_FINDINGS],
    }
