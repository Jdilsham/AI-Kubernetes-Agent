from typing import Any

from app.kubernetes.kubectl import run_kubectl_json

PRESSURE = ("MemoryPressure", "DiskPressure", "PIDPressure", "NetworkUnavailable")


def inspect_nodes() -> dict[str, Any]:
    """Which nodes exist and whether they are Ready (also tells the AI which node names are real)."""
    result = run_kubectl_json(["get", "nodes"])
    if not result["success"]:
        return {"healthy": None, "error": result["stderr"], "nodes": []}

    nodes, unhealthy, provider = [], 0, None
    for node in result["data"].get("items", []):
        conds = {c["type"]: c["status"] for c in node.get("status", {}).get("conditions", [])}
        problems = []
        if conds.get("Ready") != "True":
            problems.append("NotReady")
        problems += [c for c in PRESSURE if conds.get(c) == "True"]
        unhealthy += bool(problems)
        provider = provider or (node.get("spec", {}).get("providerID") or "").split(":")[0] or None
        taints = [f"{t['key']}={t.get('value', '')}:{t['effect']}" for t in node.get("spec", {}).get("taints", [])]
        nodes.append(
            {
                "name": node["metadata"]["name"],
                "ready": conds.get("Ready") == "True",
                "problems": problems,
                "taints": taints,
                "max_pods": node.get("status", {}).get("allocatable", {}).get("pods"),
            }
        )
    # azure -> AKS, aws -> EKS, gce -> GKE: lets the AI give cloud-specific fixes
    cloud = {"azure": "AKS (Azure)", "aws": "EKS (AWS)", "gce": "GKE (Google Cloud)"}.get(provider or "", provider)
    return {"healthy": unhealthy == 0, "total_nodes": len(nodes), "cloud_provider": cloud, "nodes": nodes}
