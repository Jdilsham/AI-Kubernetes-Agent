# Security

## Reporting a vulnerability

Please open a [GitHub issue](https://github.com/Jdilsham/AI-Kubernetes-Agent/issues) or, for anything sensitive,
use [GitHub's private vulnerability reporting](https://github.com/Jdilsham/AI-Kubernetes-Agent/security/advisories/new)
for this repository. Include what you found, how to reproduce it, and the chart/app version.

## What this project accesses

- **Cluster access is read-only.** The ServiceAccount the Helm chart creates only has `get`/`list`/`watch`
  permissions (see `charts/ai-k8s-agent/templates/rbac.yaml`). The agent never creates, modifies or deletes
  cluster resources; it only *suggests* `kubectl` commands for a human to run.
- **No Secret values are read.** Secret access is disabled by default (`rbac.readSecrets=false`). When enabled,
  only Secret names, labels and public TLS certificate contents are read — never Secret data values.
- **Evidence sent to the LLM.** Pod status, a limited number of redacted log lines, events and resource specs are
  sent to whichever LLM endpoint you configure (`llm.baseUrl`). Passwords, tokens and API keys found in commands,
  logs and events are masked before anything leaves the backend. For fully private operation, point `llm.baseUrl`
  at a self-hosted model (e.g. Ollama) instead of a third-party API.
- **Credentials.** The LLM API key and admin password are stored in a Kubernetes Secret, never hardcoded or
  committed. Use `llm.existingSecret` / `auth.existingSecret` to supply your own instead of letting the chart
  generate one.

## Supported versions

Only the latest released chart/app version is supported. Please upgrade before reporting an issue if you're on
an older version.
