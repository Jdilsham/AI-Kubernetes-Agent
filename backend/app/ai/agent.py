import json
import re
from typing import Any

from loguru import logger

from app.ai.llm_client import LLMError, chat_completion
from app.ai.prompt_builder import build_messages
from app.models.diagnosis import Diagnosis, Issue


class ClusterUnreachable(Exception):
    """kubectl could not collect any evidence (message is user-friendly)."""


def _parse_json(text: str) -> dict[str, Any]:
    """LLMs sometimes wrap JSON in markdown fences; strip them and parse."""
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end == -1:
            raise LLMError("LLM did not return JSON") from None
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError as exc:
            raise LLMError("LLM returned invalid JSON") from exc


def _text(value: Any) -> str:
    """Models sometimes return a literal backslash-n instead of a real line break."""
    return str(value).replace("\\r\\n", "\n").replace("\\n", "\n")


def _list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    return [str(v) for v in value or []]


def _root_cause(data: dict[str, Any]) -> str:
    """Models occasionally skip root_cause when listing many issues; never show 'Unknown' if we can infer it."""
    for key in ("root_cause", "rootCause", "cause", "title"):
        if str(data.get(key) or "").strip():
            return _text(data[key]).strip()
    explanation = _text(data.get("explanation", "")).strip()
    return explanation.split(". ")[0][:200] if explanation else "Unknown"


def _to_issue(data: dict[str, Any]) -> Issue:
    try:
        confidence = max(0, min(100, int(data.get("confidence", 0))))
    except (TypeError, ValueError):
        confidence = 0
    severity = str(data.get("severity", "warning")).lower()
    return Issue(
        title=str(data.get("title", "")),
        severity=severity if severity in ("critical", "warning", "info") else "warning",
        affected=_list(data.get("affected")),
        root_cause=_root_cause(data),
        explanation=_text(data.get("explanation", "")),
        fix=_text(data.get("fix", "")),
        kubectl_commands=_list(data.get("kubectl_commands")),
        prevention=_text(data.get("prevention", "")),
        confidence=confidence,
        confidence_reasoning=_list(data.get("confidence_reasoning")),
    )


IMAGE_PULL_STATUSES = {"ImagePullBackOff", "ErrImagePull", "InvalidImageName"}


def _corrected_image(issue: Issue, current: str) -> str:
    """The image the model proposed (in its commands or text), else the same repo with :latest."""
    text = " ".join([issue.fix, *issue.kubectl_commands])
    for pattern in (r"--image[= ]([^\s'\"]+)", r"set image \S+ \S+=([^\s'\"]+)"):
        m = re.search(pattern, text)
        if m and m.group(1) != current:
            return m.group(1)
    repo = current.split("@")[0]
    last = repo.rsplit("/", 1)[-1]
    if ":" in last:  # strip the tag, but not a registry port (host:5000/image)
        repo = repo[: len(repo) - len(last)] + last.split(":")[0]
    return f"{repo}:latest"


def _prefer_in_place(issue: Issue, inv: dict[str, Any]) -> None:
    """A wrong image can be changed in place, so never delete/re-create the pod for it.

    Models often suggest delete + run; replace that with a single `kubectl set image`
    built from the evidence (real container name, owner and namespace)."""
    names = {a.rsplit("/", 1)[-1] for a in issue.affected} | set(re.findall(r"[a-z0-9][a-z0-9.-]*", issue.title.lower()))
    targets = [
        p
        for p in inv.get("pods", {}).get("problematic_pods", [])
        if p["status"] in IMAGE_PULL_STATUSES and p["name"].lower() in names
    ]
    if len(targets) != 1:
        return
    pod = targets[0]
    ns, name = pod["namespace"], pod["name"]
    containers = (inv.get("pod_details", {}).get(f"{ns}/{name}") or {}).get("containers") or []
    if not containers:
        return
    container = containers[0]
    target = pod.get("fix_target") or f"pod/{name}"
    image = _corrected_image(issue, container.get("image") or "")
    command = f"kubectl set image {target} {container['name']}={image} -n {ns}"
    verify = (
        f"kubectl rollout status {target} -n {ns}"
        if not target.startswith("pod/")
        else f"kubectl wait --for=condition=Ready pod/{name} -n {ns} --timeout=120s"
    )
    issue.fix = (
        f"1. Change the image in place (no need to delete the pod): {command}\n"
        f"2. Confirm the pod pulls the image and becomes Running: {verify}"
    )
    issue.kubectl_commands = [command, verify]


# Deleting these causes outages or data loss and rarely fixes the cause; never suggest it.
DESTRUCTIVE = re.compile(
    r"kubectl\s+delete\s+(?:-n\s+\S+\s+)?(?:service|svc|deployment|deploy|statefulset|sts|daemonset|ds|"
    r"persistentvolumeclaim|pvc|persistentvolume|pv|namespace|ns|ingress|ing|configmap|cm|secret|node|crd)\b",
    re.IGNORECASE,
)


def _resource_findings(inv: dict[str, Any]) -> list[dict[str, Any]]:
    return [f for fs in ((inv.get("resources") or {}).get("findings") or {}).values() for f in fs]


def _guard_commands(issue: Issue, inv: dict[str, Any]) -> None:
    """Drop destructive commands, and use verified hints from the inspectors when the model gave none."""
    removed = [c for c in issue.kubectl_commands if DESTRUCTIVE.search(c)]
    issue.kubectl_commands = [c for c in issue.kubectl_commands if c.strip() and not DESTRUCTIVE.search(c)]
    if removed:
        issue.fix = "\n".join(line for line in issue.fix.split("\n") if not DESTRUCTIVE.search(line)).strip()
    if issue.kubectl_commands:
        return
    names = {a.rsplit("/", 1)[-1] for a in issue.affected}
    hints = []
    for f in _resource_findings(inv):
        if f.get("hint") and f.get("name") in names and f["hint"] not in hints:
            hints.append(f["hint"])
    if hints:
        issue.kubectl_commands = hints[:4]
        if not issue.fix.strip():
            issue.fix = "\n".join(f"{n}. {h}" for n, h in enumerate(hints[:4], 1))


RETRY_PROMPT = (
    "Your answer contained no issues, but the evidence shows failing resources. Return the same JSON shape with one "
    "entry in \"issues\" per distinct failure (title, severity, affected, root_cause, explanation, fix, "
    "kubectl_commands, prevention, confidence, confidence_reasoning)."
)


def _issues(data: dict[str, Any]) -> list[Issue]:
    issues = [_to_issue(i) for i in data.get("issues") or [] if isinstance(i, dict)]
    if not issues and data.get("root_cause"):  # model answered with a single issue
        issues = [_to_issue(data)]
    return issues


def _prefer_selector_fix(issue: Issue, inv: dict[str, Any]) -> None:
    """Selector mismatches get the computed selector patch instead of the model's guess."""
    text = f"{issue.title} {' '.join(issue.affected)}".lower()
    for net in (inv.get("network") or {}).get("issues", []):
        if net.get("hint") and net["service"].lower() in re.findall(r"[a-z0-9][a-z0-9.-]*", text):
            ns, svc = net["namespace"], net["service"]
            verify = f"kubectl get endpoints {svc} -n {ns}"
            issue.kubectl_commands = [net["hint"], verify]
            issue.fix = (
                f"1. Point the Service at the pods it was meant for (labels {net['suggested_selector']}): {net['hint']}\n"
                f"2. Confirm the Service now has endpoints: {verify}"
            )
            return


def _is_all_healthy(inv: dict[str, Any]) -> bool:
    # Old warning events are ignored on purpose: current pod/deployment/network state decides.
    return (
        inv["pods"].get("healthy") is True
        and inv["deployments"].get("healthy") is not False
        and inv["network"].get("healthy") is not False
        and (inv.get("nodes") or {}).get("healthy") is not False
        and (inv.get("resources") or {}).get("healthy") is not False
    )


def analyze_investigation(investigation: dict[str, Any]) -> Diagnosis:
    """Root cause + fix + confidence for the collected Kubernetes evidence."""
    if investigation["pods"].get("healthy") is None:
        raise ClusterUnreachable(investigation["pods"].get("error") or "Could not read the cluster.")

    if _is_all_healthy(investigation):
        return Diagnosis(
            root_cause="No critical Kubernetes issues detected",
            explanation="Cluster appears healthy: all pods, deployments and services passed their checks.",
            fix="No action needed.",
            confidence=95,
            healthy=True,
            confidence_reasoning=["No unhealthy pods", "Deployments available", "Services have endpoints"],
        )

    messages = build_messages(investigation)
    data = _parse_json(chat_completion(messages))
    issues = _issues(data)
    if not issues:
        # Free/small models sometimes return valid JSON without issues: ask once more, explicitly.
        logger.warning("LLM returned no issues, retrying. Reply started with: {}", json.dumps(data)[:300])
        messages = [*messages, {"role": "assistant", "content": json.dumps(data)}, {"role": "user", "content": RETRY_PROMPT}]
        data = _parse_json(chat_completion(messages))
        issues = _issues(data)
    if not issues:
        logger.error("LLM returned no issues twice. Reply started with: {}", json.dumps(data)[:300])
        raise LLMError("The AI did not return a usable diagnosis. Please try again.")
    for issue in issues:
        _prefer_in_place(issue, investigation)
        _prefer_selector_fix(issue, investigation)
        _guard_commands(issue, investigation)
    order = {"critical": 0, "warning": 1, "info": 2}
    issues.sort(key=lambda i: order.get(i.severity, 1))

    top = issues[0]
    diagnosis = Diagnosis(
        root_cause=top.root_cause,
        explanation=top.explanation,
        fix=top.fix,
        kubectl_commands=top.kubectl_commands,
        prevention=top.prevention,
        confidence=top.confidence,
        confidence_reasoning=top.confidence_reasoning,
        summary=str(data.get("summary", "")),
        issues=issues,
    )
    logger.info("Diagnosis: {} issue(s), top: {} ({}%)", len(issues), top.root_cause, top.confidence)
    return diagnosis
