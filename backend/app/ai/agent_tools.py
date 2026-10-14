"""The kubectl tool the AI agent uses: read-only, namespace-scoped, secret-free and size-limited.

The model chooses the command; this module decides whether it may run. Everything is enforced in code,
never only in the prompt."""

import shlex

from app.core.config import get_settings
from app.kubernetes.kubectl import current_namespace, friendly_error, redact, run_kubectl

MAX_OUTPUT_CHARS = 6000  # every result is re-sent on each following turn, so keep them small
COMMAND_TIMEOUT = 30
DEFAULT_LOG_TAIL = 200

# Verbs that only read. Anything else (delete, apply, patch, edit, exec, cp, port-forward, run, debug, scale,
# set, rollout restart, drain, cordon, config, plugins...) is refused.
READ_VERBS = {"get", "describe", "logs", "top", "events", "explain", "api-resources", "api-versions", "version", "auth", "rollout"}
ROLLOUT_READ = {"status", "history"}
AUTH_READ = {"can-i", "whoami"}

# Flags that change who/where kubectl talks to, stream forever, read local files, or open raw API access.
BLOCKED_FLAGS = {
    "--kubeconfig", "--context", "--cluster", "--user", "--server", "-s", "--token", "--as", "--as-group", "--as-uid",
    "--certificate-authority", "--client-certificate", "--client-key", "--insecure-skip-tls-verify", "--tls-server-name",
    "--username", "--password", "--raw", "--request-timeout", "-f", "--filename", "-k", "--kustomize", "-R", "--recursive",
    "--follow", "-w", "--watch", "--watch-only", "--output-watch-events", "--field-manager", "--save-config", "--edit",
    "--show-managed-fields",
}
SHELL_TOKENS = {">", ">>", "<", "&", "2>&1"}  # only meaningful as a word of their own
SHELL_MARKERS = ("|", ";", "&&", "`", "$(")  # also caught inside a word, e.g. "pods;"
# Output formats that would print a Secret's data (the plain table shows only names, type and key count).
DATA_OUTPUTS = ("json", "yaml", "jsonpath", "go-template", "template", "custom-columns")


class CommandRejected(Exception):
    """The command may not run. The message is shown to the model so it can correct itself."""


def _flag_name(token: str) -> str:
    return token.split("=", 1)[0]


def _output_format(tokens: list[str]) -> str:
    for i, t in enumerate(tokens):
        if t in ("-o", "--output") and i + 1 < len(tokens):
            return tokens[i + 1]
        if t.startswith("--output="):
            return t.split("=", 1)[1]
        if t.startswith("-o") and len(t) > 2 and not t.startswith("--"):
            return t[2:]
    return ""


def _names_secrets(tokens: list[str]) -> bool:
    for t in tokens:
        if t.startswith("-"):
            continue
        for part in t.split(","):
            kind = part.split("/", 1)[0].lower()
            if kind in ("secret", "secrets") or kind.startswith("secrets."):
                return True
    return False


def _scope(tokens: list[str], namespace: str | None) -> list[str]:
    """Keep the command inside the selected namespace (user choice or a namespace-only install)."""
    if not namespace:
        return tokens
    out: list[str] = []
    skip = False
    for i, t in enumerate(tokens):
        if skip:
            skip = False
            continue
        name = _flag_name(t)
        if name in ("-A", "--all-namespaces"):
            raise CommandRejected(f"All namespaces is not allowed; this investigation is limited to namespace '{namespace}'.")
        if name in ("-n", "--namespace"):
            value = t.split("=", 1)[1] if "=" in t else (tokens[i + 1] if i + 1 < len(tokens) else "")
            if value != namespace:
                raise CommandRejected(f"Namespace '{value}' is not allowed; this investigation is limited to namespace '{namespace}'.")
            skip = "=" not in t
            continue
        out.append(t)
    return [*out, "-n", namespace]


def validate(command: str, namespace: str | None) -> list[str]:
    """Return the kubectl arguments to run, or raise CommandRejected with an explanation for the model."""
    command = command.strip()
    if not command:
        raise CommandRejected("Empty command.")
    try:
        tokens = shlex.split(command)
    except ValueError as exc:
        raise CommandRejected(f"Could not parse the command ({exc}).") from exc
    if tokens and tokens[0] == "kubectl":
        tokens = tokens[1:]
    if not tokens:
        raise CommandRejected("Empty command.")
    if any(t in SHELL_TOKENS or any(m in t for m in SHELL_MARKERS) for t in tokens):
        raise CommandRejected(
            "Pipes, redirects and shell syntax are not supported. Run one plain kubectl command (use -o jsonpath or label/field selectors to filter)."
        )

    verb = tokens[0]
    if verb.startswith("-"):
        raise CommandRejected("Start with a kubectl verb such as get, describe, logs, top or events.")
    if verb not in READ_VERBS:
        raise CommandRejected(f"'{verb}' is not allowed: this agent is read-only. Allowed: {', '.join(sorted(READ_VERBS))}.")
    if verb == "rollout" and (len(tokens) < 2 or tokens[1] not in ROLLOUT_READ):
        raise CommandRejected("Only 'rollout status' and 'rollout history' are allowed.")
    if verb == "auth" and (len(tokens) < 2 or tokens[1] not in AUTH_READ):
        raise CommandRejected("Only 'auth can-i' and 'auth whoami' are allowed.")

    for t in tokens[1:]:
        if t.startswith("-") and _flag_name(t) in BLOCKED_FLAGS:
            raise CommandRejected(f"The flag {_flag_name(t)} is not allowed (no following/watching, files, or changing cluster, user or timeouts).")

    if verb in ("get", "describe", "events") and _names_secrets(tokens[1:]):
        if verb == "get" and _output_format(tokens).split("=", 1)[0] in DATA_OUTPUTS:
            raise CommandRejected(
                "Secret values are never shown. 'kubectl get secrets' (default table) lists names, type and key count; 'describe secret' lists key names."
            )

    if verb == "logs" and not any(_flag_name(t) in ("--tail", "--since", "--since-time", "--limit-bytes") for t in tokens):
        tokens = [*tokens, f"--tail={DEFAULT_LOG_TAIL}"]
    if verb == "rollout" and tokens[1] == "status":
        tokens = [*tokens, "--watch=false"]  # report the current state instead of waiting for the rollout
    return _scope(tokens, namespace)


def run_command(command: str) -> tuple[str, bool]:
    """Validate and run a kubectl command for the agent. Returns (text for the model, is_error)."""
    namespace = get_settings().allowed_namespace or current_namespace.get()
    try:
        args = validate(command, namespace)
    except CommandRejected as exc:
        return f"Command not run: {exc}", True

    res = run_kubectl(args, timeout=COMMAND_TIMEOUT)
    if not res["success"]:
        detail = res.get("stderr_full") or res["stderr"] or friendly_error("")
        return f"kubectl failed (exit {res['returncode']}): {detail}", True

    out = redact(res["stdout"]).strip() or "(no output)"
    if len(out) > MAX_OUTPUT_CHARS:
        out = out[:MAX_OUTPUT_CHARS] + f"\n...[output truncated at {MAX_OUTPUT_CHARS} characters; narrow it with -n, a selector, --tail or -o jsonpath]"
    return out, False
