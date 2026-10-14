"""Pieces shared by the agent loops (Claude and OpenAI-compatible): the tools, the first prompt, progress labels."""

from typing import Any

from app.ai.prompt_builder import build_evidence
from app.core.config import get_settings
from app.kubernetes.kubectl import current_namespace

SNAPSHOT_CHARS = 15000  # first-look evidence; the model fetches the rest itself
EXTRA_TURNS = 3  # turns beyond the command budget, so the model can still submit its answer

KUBECTL_TOOL = {
    "name": "kubectl",
    "description": (
        "Run one read-only kubectl command against the cluster under investigation and get its output. "
        "Allowed: get, describe, logs, top, events, explain, api-resources, auth can-i, rollout status/history. "
        "Pass the command without the leading 'kubectl', for example: describe pod web-1 -n shop. "
        "No pipes or shell syntax; filter with selectors or -o jsonpath. Output is truncated when long."
    ),
    "input_schema": {
        "type": "object",
        "properties": {"command": {"type": "string", "description": "kubectl arguments, e.g. 'logs web-1 -n shop --previous --tail=100'"}},
        "required": ["command"],
    },
}

_ISSUE_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string", "description": "short name, e.g. test-pod: image pull failure"},
        "severity": {"type": "string", "enum": ["critical", "warning", "info"]},
        "affected": {"type": "array", "items": {"type": "string"}, "description": "namespace/resource"},
        "root_cause": {"type": "string", "description": "short one-sentence root cause"},
        "explanation": {"type": "string", "description": "how the evidence you gathered leads to this root cause"},
        "fix": {"type": "string", "description": "numbered steps, one per line"},
        "kubectl_commands": {"type": "array", "items": {"type": "string"}, "description": "fix commands first, then at most two verification commands"},
        "prevention": {"type": "string"},
        "confidence": {"type": "integer", "description": "0-100"},
        "confidence_reasoning": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["title", "severity", "affected", "root_cause", "explanation", "fix", "kubectl_commands", "confidence"],
}

SUBMIT_TOOL = {
    "name": "submit_diagnosis",
    "description": (
        "Submit the final diagnosis once you have investigated enough. "
        "Call it exactly once, with one entry in issues per distinct problem. Ends the investigation."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "summary": {"type": "string", "description": "one sentence overview of the cluster state"},
            "issues": {"type": "array", "items": _ISSUE_SCHEMA, "description": "empty when the cluster has no real problems"},
        },
        "required": ["summary", "issues"],
    },
}

TOOLS = [KUBECTL_TOOL, SUBMIT_TOOL]


def label(command: str) -> str:
    command = command.strip()
    return command if len(command) <= 90 else command[:87] + "..."


def first_message(investigation: dict[str, Any]) -> str:
    """The user message that starts every investigation: the first-look snapshot and the scope."""
    namespace = get_settings().allowed_namespace or current_namespace.get()
    scope = f"\nThis investigation is limited to namespace '{namespace}'.\n" if namespace else ""
    return (
        f"First-look snapshot of the cluster:{scope}\n\n{build_evidence(investigation, SNAPSHOT_CHARS)}\n\n"
        "Investigate the problems with kubectl, then call submit_diagnosis."
    )
