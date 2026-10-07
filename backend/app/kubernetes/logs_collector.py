import re
from typing import Any

from app.kubernetes.kubectl import redact, run_kubectl

TAIL_LINES = 100
MAX_RELEVANT_LINES = 12

ERROR_PATTERN = re.compile(
    r"exception|traceback|error|fatal|panic|refused|timeout|timed out|unreachable|"
    r"no such host|not found|missing|undefined|denied|failed|cannot|can't|oom",
    re.IGNORECASE,
)


def _fetch(args: list[str]) -> dict[str, Any]:
    """kubectl sometimes exits 0 but prints 'unable to retrieve container logs'; treat that as a failure."""
    res = run_kubectl(args)
    if res["success"] and res["stdout"].lower().startswith("unable to retrieve container logs"):
        res["success"] = False
        res["stderr"] = res["stdout"].strip()
    return res


def collect_logs(problematic_pods: list[dict[str, Any]]) -> dict[str, Any]:
    """Fetch concise, error-focused logs for each unhealthy pod."""
    collected = []
    for pod in problematic_pods:
        name, ns = pod["name"], pod["namespace"]
        # Crashed containers: the previous run's logs are best, otherwise use the current ones.
        res = _fetch(["logs", name, "-n", ns, "--all-containers", "--prefix", "--previous", f"--tail={TAIL_LINES}"])
        if not res["success"]:
            res = _fetch(["logs", name, "-n", ns, "--all-containers", "--prefix", f"--tail={TAIL_LINES}"])
        if not res["success"]:
            collected.append(
                {"pod": name, "namespace": ns, "available": False, "error": res["stderr"]}
            )
            continue

        lines = [redact(line) for line in res["stdout"].splitlines() if line.strip()]
        relevant = [line for line in lines if ERROR_PATTERN.search(line)]
        collected.append(
            {
                "pod": name,
                "namespace": ns,
                "available": True,
                "relevant_lines": relevant[-MAX_RELEVANT_LINES:],
                "last_lines": lines[-5:],
            }
        )
    return {"pods_checked": len(collected), "logs": collected}
