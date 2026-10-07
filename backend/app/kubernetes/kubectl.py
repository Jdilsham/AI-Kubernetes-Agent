import json
import os
import re
import subprocess
from contextvars import ContextVar
from pathlib import Path
from typing import Any

from loguru import logger

from app.core.config import get_settings

# kubeconfig context to investigate; set per request (copied into worker threads)
current_context: ContextVar[str | None] = ContextVar("kube_context", default=None)
# namespace to investigate; None = all namespaces
current_namespace: ContextVar[str | None] = ContextVar("kube_namespace", default=None)


def scope_args() -> list[str]:
    """`-n <ns>` when a namespace is selected, otherwise `-A` (all namespaces)."""
    ns = current_namespace.get()
    return ["-n", ns] if ns else ["-A"]

DEFAULT_TIMEOUT = 20
REQUEST_TIMEOUT = "5s"  # per API request, so an unreachable cluster fails fast


def _last_line(text: str) -> str:
    """kubectl repeats noisy retry lines; the last one is the real error."""
    lines = [line for line in text.strip().splitlines() if line.strip()]
    return lines[-1] if lines else ""


def run_kubectl(args: list[str], timeout: int = DEFAULT_TIMEOUT) -> dict[str, Any]:
    """Run `kubectl <args>` safely (no shell) and return structured output."""
    cmd = ["kubectl"]
    kubeconfig = get_settings().kubeconfig_path
    if kubeconfig:
        cmd += ["--kubeconfig", kubeconfig]
    context = current_context.get()
    if context:
        cmd += ["--context", context]
    cmd += [f"--request-timeout={REQUEST_TIMEOUT}", *args]
    printable = " ".join(cmd)
    logger.info("Running: {}", printable)

    result: dict[str, Any] = {
        "command": printable,
        "success": False,
        "stdout": "",
        "stderr": "",
        "returncode": None,
    }
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        result.update(
            success=proc.returncode == 0,
            stdout=proc.stdout,
            stderr=_last_line(proc.stderr),
            returncode=proc.returncode,
        )
    except FileNotFoundError:
        result["stderr"] = "kubectl binary not found"
    except subprocess.TimeoutExpired:
        result["stderr"] = f"kubectl timed out after {timeout}s"

    if not result["success"]:
        logger.warning("kubectl failed: {} -> {}", printable, result["stderr"])
    return result


def run_kubectl_json(args: list[str], timeout: int = DEFAULT_TIMEOUT) -> dict[str, Any]:
    """Run kubectl with `-o json`; adds `data` (parsed JSON) to the result."""
    result = run_kubectl([*args, "-o", "json"], timeout=timeout)
    result["data"] = None
    if result["success"]:
        try:
            result["data"] = json.loads(result["stdout"])
        except json.JSONDecodeError:
            result["success"] = False
            result["stderr"] = "could not parse kubectl JSON output"
    result.pop("stdout", None)
    return result


_SECRET_PATTERNS = [
    (re.compile(r"(?i)(--?(?:password|passwd|pwd|token|secret|api[-_]?key)[= ]\s*)\S+"), r"\1***"),
    (re.compile(r"(?i)([A-Za-z0-9_.-]*(?:password|passwd|pwd|token|secret|api[-_]?key|access[-_]?key)\s*[=:]\s*)(?!(?:YES|NO)\b)[^\s,;\"']+"), r"\1***"),
    (re.compile(r"(?<=\s-p)\S+"), "***"),  # mysql -pSECRET
    (re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+"), "Bearer ***"),
    (re.compile(r"\b(?:sk|ghp|xox[bap])-[A-Za-z0-9_-]{10,}"), "***"),
]


def redact(text: str) -> str:
    """Mask passwords/tokens before text leaves the backend (it is sent to the LLM and stored)."""
    for pattern, repl in _SECRET_PATTERNS:
        text = pattern.sub(repl, text)
    return text


def friendly_error(stderr: str) -> str:
    """Turn raw kubectl errors into beginner-friendly messages."""
    text = stderr.lower()
    if "binary not found" in text:
        return "kubectl is not installed on the backend server.\n\nInstall kubectl and restart the backend."
    if "forbidden" in text or "unauthorized" in text:
        return (
            "Kubernetes denied access.\n\nPlease verify:\n"
            "- the kubeconfig user/token is valid\n- kubectl permissions (RBAC) allow reading pods, events and deployments"
        )
    if "no configuration" in text or "invalid configuration" in text or "no such file" in text or "context was not found" in text:
        return (
            "Kubeconfig not found or invalid.\n\nPlease verify:\n"
            "- kubeconfig path (KUBECONFIG_PATH)\n- the selected cluster exists in the kubeconfig"
        )
    if any(k in text for k in ("unable to connect", "timed out", "no route", "refused", "dial tcp", "i/o timeout", "no such host")):
        return (
            "Unable to connect to Kubernetes cluster.\n\nPlease verify:\n"
            "- kubeconfig path\n- cluster access (network/VPN)\n- kubectl permissions"
        )
    return f"kubectl failed: {stderr[:200]}"


def list_contexts() -> dict[str, Any]:
    """Clusters (contexts) from the kubeconfig. Reads the file only, no cluster connection."""
    result = run_kubectl_json(["config", "view"], timeout=10)
    if not result["success"]:
        return {"current": None, "clusters": [], "error": friendly_error(result["stderr"])}
    data = result["data"] or {}
    current = data.get("current-context")
    clusters = [
        {
            "name": c["name"],
            "cluster": c.get("context", {}).get("cluster", ""),
            "user": c.get("context", {}).get("user", ""),
            "current": c["name"] == current,
        }
        for c in data.get("contexts") or []
    ]
    return {"current": current, "clusters": clusters, "error": None}


def list_namespaces() -> dict[str, Any]:
    res = run_kubectl(["get", "namespaces", "-o", "jsonpath={.items[*].metadata.name}"], timeout=15)
    if not res["success"]:
        return {"namespaces": [], "error": friendly_error(res["stderr"])}
    return {"namespaces": sorted(res["stdout"].split()), "error": None}


SA_DIR = Path("/var/run/secrets/kubernetes.io/serviceaccount")


def ensure_in_cluster_kubeconfig() -> None:
    """Inside a pod, point kubectl at the pod's ServiceAccount.

    kubectl does not reliably fall back to in-cluster credentials (it tries localhost:8080),
    so write a kubeconfig that uses the mounted token *file* (kept fresh by Kubernetes' token rotation)."""
    settings = get_settings()
    host, port = os.environ.get("KUBERNETES_SERVICE_HOST"), os.environ.get("KUBERNETES_SERVICE_PORT", "443")
    if settings.kubeconfig_path or not host or not (SA_DIR / "token").exists():
        return  # explicit kubeconfig (local dev) or not running in a pod
    server = f"https://[{host}]:{port}" if ":" in host else f"https://{host}:{port}"
    path = Path(os.environ.get("TMPDIR", "/tmp")) / "in-cluster-kubeconfig"
    path.write_text(
        "apiVersion: v1\nkind: Config\n"
        f"clusters:\n- name: in-cluster\n  cluster:\n    server: {server}\n    certificate-authority: {SA_DIR / 'ca.crt'}\n"
        f"users:\n- name: service-account\n  user:\n    tokenFile: {SA_DIR / 'token'}\n"
        "contexts:\n- name: in-cluster\n  context:\n    cluster: in-cluster\n    user: service-account\n"
        "current-context: in-cluster\n"
    )
    settings.kubeconfig_path = str(path)
