# ai-k8s-agent

AI-powered Kubernetes troubleshooting agent. Collects read-only evidence (pods, logs, events, workloads,
networking, storage, capacity, security) and asks an OpenAI-compatible LLM for root causes and fixes.

```bash
helm install k8s-agent oci://ghcr.io/jdilsham/charts/ai-k8s-agent --version 0.1.0 -n k8s-agent --create-namespace \
  --set llm.apiKey=$OPENROUTER_API_KEY --set llm.model=nvidia/nemotron-3-super-120b-a12b:free
kubectl port-forward -n k8s-agent svc/k8s-agent-ai-k8s-agent 8080:80
```

The admin password is generated on install; `helm status k8s-agent -n k8s-agent` prints how to read it.

- Read-only RBAC (`get`/`list`/`watch`), no Secret access unless `rbac.readSecrets=true`.
- `rbac.scope=namespace` limits the agent to the release namespace.
- History is stored in SQLite on a PVC (kept on `helm uninstall`).
- Redacted evidence is sent to the configured LLM; use a local model via `llm.baseUrl` to keep it private.

See `values.yaml` for all options and the project README for details:
https://github.com/Jdilsham/AI-Kubernetes-Agent
