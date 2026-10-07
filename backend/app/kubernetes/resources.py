"""Inspectors for Kubernetes resources beyond pods/deployments/services.

Every inspector is read-only and returns a list of findings:
    {"kind", "namespace", "name", "problem", "detail", "hint"?}
`hint` is a ready-made kubectl command built from real names, for cases where the fix is certain.
Secret *values* are never read (only names, labels and public TLS certificates).
"""

import base64
import contextvars
from collections import Counter
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import Any

from loguru import logger

from app.kubernetes.kubectl import run_kubectl, run_kubectl_json, scope_args

Finding = dict[str, Any]
CERT_WARN_DAYS = 14
SYSTEM_NAMESPACES = {"kube-system", "kube-public", "kube-node-lease"}
ADDON_HINTS = (
    "coredns", "kube-dns", "metrics-server", "calico", "cilium", "azure-cni", "aws-node", "kube-proxy",
    "csi", "ingress", "cert-manager", "konnectivity", "cloud-node-manager", "ama-",
)


def _items(kind: str, namespaced: bool = True) -> list[dict[str, Any]] | None:
    """`kubectl get <kind>` items, or None if the kind is unknown/forbidden (e.g. CRD not installed)."""
    res = run_kubectl_json(["get", kind, *(scope_args() if namespaced else [])])
    return res["data"].get("items", []) if res["success"] else None


def _finding(obj: dict[str, Any], kind: str, problem: str, detail: str, hint: str | None = None) -> Finding:
    meta = obj.get("metadata", {})
    f: Finding = {"kind": kind, "namespace": meta.get("namespace"), "name": meta.get("name"), "problem": problem, "detail": detail[:300]}
    if hint:
        f["hint"] = hint
    return f


def _age_seconds(ts: str | None) -> float:
    if not ts:
        return 0
    try:
        return (datetime.now(UTC) - datetime.fromisoformat(ts.replace("Z", "+00:00"))).total_seconds()
    except ValueError:
        return 0


def _condition(obj: dict[str, Any], ctype: str) -> dict[str, Any]:
    return next((c for c in obj.get("status", {}).get("conditions", []) if c.get("type") == ctype), {})


# ---------------------------------------------------------------- workloads


def inspect_statefulsets() -> list[Finding]:
    out = []
    for s in _items("statefulsets") or []:
        want, ready = s.get("spec", {}).get("replicas", 1), s.get("status", {}).get("readyReplicas", 0)
        if ready < want:
            ns, name = s["metadata"]["namespace"], s["metadata"]["name"]
            out.append(_finding(s, "StatefulSet", "NotReady", f"{ready}/{want} replicas ready; current revision "
                                f"{s.get('status', {}).get('currentRevision')} update revision {s.get('status', {}).get('updateRevision')}",
                                f"kubectl rollout status statefulset/{name} -n {ns}"))
    return out


def inspect_daemonsets() -> list[Finding]:
    out = []
    for d in _items("daemonsets") or []:
        st = d.get("status", {})
        want, ready = st.get("desiredNumberScheduled", 0), st.get("numberReady", 0)
        if ready < want or st.get("numberMisscheduled", 0):
            out.append(_finding(d, "DaemonSet", "NotReady", f"{ready}/{want} pods ready, {st.get('numberUnavailable', 0)} unavailable, "
                                f"{st.get('numberMisscheduled', 0)} misscheduled"))
    return out


def inspect_jobs() -> list[Finding]:
    out = []
    jobs = _items("jobs") or []
    for j in jobs:
        st, meta = j.get("status", {}), j["metadata"]
        failed = _condition(j, "Failed")
        if failed.get("status") == "True" or (st.get("failed", 0) and not st.get("succeeded") and not st.get("active")):
            owner = (meta.get("ownerReferences") or [{}])[0]
            ns, name = meta["namespace"], meta["name"]
            if owner.get("kind") == "CronJob":
                hint = (f"kubectl delete job {name} -n {ns} && "
                        f"kubectl create job --from=cronjob/{owner['name']} {owner['name']}-manual-retry -n {ns}")
            else:
                hint = f"kubectl get job {name} -n {ns} -o yaml > {name}.yaml && kubectl delete job {name} -n {ns} && kubectl apply -f {name}.yaml"
            out.append(_finding(j, "Job", failed.get("reason") or "Failed",
                                f"{st.get('failed', 0)} failed pod(s); {failed.get('message', '')}"
                                + (f"; created by CronJob {owner['name']}" if owner.get("kind") == "CronJob" else ""), hint))
    for c in _items("cronjobs") or []:
        spec, st = c.get("spec", {}), c.get("status", {})
        ns, name = c["metadata"]["namespace"], c["metadata"]["name"]
        if spec.get("suspend"):
            out.append(_finding(c, "CronJob", "Suspended", f"schedule '{spec.get('schedule')}' is suspended",
                                f"kubectl patch cronjob {name} -n {ns} -p '{{\"spec\":{{\"suspend\":false}}}}'"))
        elif st.get("lastScheduleTime") and st.get("lastSuccessfulTime") and st["lastSuccessfulTime"] < st["lastScheduleTime"]:
            out.append(_finding(c, "CronJob", "LastRunFailed",
                                f"last scheduled {st['lastScheduleTime']} but last success {st['lastSuccessfulTime']}"))
    return out


def inspect_hpas() -> list[Finding]:
    out = []
    for h in _items("horizontalpodautoscalers") or []:
        spec, st = h.get("spec", {}), h.get("status", {})
        for ctype in ("AbleToScale", "ScalingActive"):
            cond = _condition(h, ctype)
            if cond.get("status") == "False":
                out.append(_finding(h, "HorizontalPodAutoscaler", cond.get("reason") or ctype, cond.get("message", "")))
                break
        else:
            if st.get("currentReplicas") and st.get("currentReplicas") >= spec.get("maxReplicas", 1 << 30):
                target = spec.get("scaleTargetRef", {}).get("name")
                out.append(_finding(h, "HorizontalPodAutoscaler", "AtMaxReplicas",
                                    f"running {st['currentReplicas']} = maxReplicas; target {target} may need more capacity"))
    return out


def inspect_rollouts() -> list[Finding]:
    """Deployments whose newest rollout is stuck: suggest undoing to the previous revision."""
    out = []
    for d in _items("deployments") or []:
        cond = _condition(d, "Progressing")
        if cond.get("reason") == "ProgressDeadlineExceeded":
            ns, name = d["metadata"]["namespace"], d["metadata"]["name"]
            rev = d["metadata"].get("annotations", {}).get("deployment.kubernetes.io/revision")
            out.append(_finding(d, "Deployment", "RolloutStuck", f"revision {rev}: {cond.get('message', '')}",
                                f"kubectl rollout undo deployment/{name} -n {ns}" if rev and rev != "1" else None))
    return out


# ---------------------------------------------------------------- storage


def inspect_storage() -> list[Finding]:
    out = []
    classes = _items("storageclasses", namespaced=False)
    class_names = {c["metadata"]["name"] for c in classes or []}
    default_class = next((c["metadata"]["name"] for c in classes or []
                          if c["metadata"].get("annotations", {}).get("storageclass.kubernetes.io/is-default-class") == "true"), None)
    for pvc in _items("persistentvolumeclaims") or []:
        phase = pvc.get("status", {}).get("phase")
        if phase == "Bound":
            continue
        sc = pvc.get("spec", {}).get("storageClassName")
        detail = f"phase {phase}; storageClass {sc or '(none)'}; requested {pvc.get('spec', {}).get('resources', {}).get('requests', {}).get('storage')}"
        hint = None
        if classes is not None and sc and sc not in class_names:
            detail += f"; StorageClass '{sc}' does not exist (available: {', '.join(sorted(class_names)) or 'none'})"
        elif classes is not None and not sc and not default_class:
            detail += "; no storageClassName and the cluster has no default StorageClass"
            if class_names:
                first = sorted(class_names)[0]
                hint = (f"kubectl patch storageclass {first} -p "
                        "'{\"metadata\":{\"annotations\":{\"storageclass.kubernetes.io/is-default-class\":\"true\"}}}'")
        out.append(_finding(pvc, "PersistentVolumeClaim", phase or "Unbound", detail, hint))
    for pv in _items("persistentvolumes", namespaced=False) or []:
        phase = pv.get("status", {}).get("phase")
        if phase in ("Failed", "Released"):
            claim = pv.get("spec", {}).get("claimRef", {})
            out.append(_finding(pv, "PersistentVolume", phase,
                                f"{pv.get('status', {}).get('message', '')} previously bound to {claim.get('namespace')}/{claim.get('name')}; "
                                f"reclaimPolicy {pv.get('spec', {}).get('persistentVolumeReclaimPolicy')}"))
    return out


def inspect_config_refs(pod_details: dict[str, Any]) -> list[Finding]:
    """ConfigMaps/Secrets referenced by failing pods that do not exist (only names are checked)."""
    out, existing = [], {}
    for key, details in pod_details.items():
        ns, pod = key.split("/", 1)
        if ns not in existing:
            # Two calls: without Secret access (the default), ConfigMaps can still be checked.
            names: set[str] = set()
            for kind in ("configmaps", "secrets"):
                res = run_kubectl(["get", kind, "-n", ns, "--no-headers"])
                if res["success"]:
                    singular = "configmap" if kind == "configmaps" else "secret"
                    names |= {f"{singular}/{line.split()[0]}" for line in res["stdout"].splitlines() if line.strip()}
                else:
                    names.add(f"{kind}:unreadable")
            existing[ns] = names
        names = existing[ns]
        if names is None:
            continue
        refs: set[tuple[str, str]] = set()
        for c in details.get("containers", []):
            for env in c.get("env", []):
                if " <- secret " in env:
                    refs.add(("secret", env.split(" <- secret ")[1].split("/")[0]))
                elif " <- configmap " in env:
                    refs.add(("configmap", env.split(" <- configmap ")[1].split("/")[0]))
                elif env.startswith("envFrom "):
                    kind, ref = env.split()[1:3]
                    refs.add(("secret" if kind == "secret" else "configmap", ref))
        for v in details.get("volumes", []):
            kind, _, ref = v.partition(" ")
            if kind in ("secret", "configMap"):
                refs.add(("secret" if kind == "secret" else "configmap", ref))
        for kind, ref in sorted(refs):
            if f"{kind}s:unreadable" in names:  # e.g. no Secret access: cannot tell if it exists
                continue
            if f"{kind}/{ref}" not in names:
                hint = (f"kubectl create configmap {ref} -n {ns} --from-literal=KEY=VALUE"
                        if kind == "configmap" else f"kubectl create secret generic {ref} -n {ns} --from-literal=KEY=$VALUE")
                out.append({"kind": kind.capitalize() if kind == "secret" else "ConfigMap", "namespace": ns, "name": ref,
                            "problem": "Missing", "detail": f"referenced by pod {pod} but does not exist", "hint": hint})
    return out


# ---------------------------------------------------------------- networking


def _secret_names(namespaces: set[str]) -> set[str] | None:
    """'ns/name' of secrets. Uses kubectl's default table output, which the API server renders
    without secret data (a JSON/jsonpath list would download every secret's contents)."""
    names: set[str] = set()
    for ns in namespaces:
        res = run_kubectl(["get", "secrets", "-n", ns, "--no-headers"])
        if not res["success"]:
            return None
        names |= {f"{ns}/{line.split()[0]}" for line in res["stdout"].splitlines() if line.strip()}
    return names


def inspect_ingresses() -> list[Finding]:
    out = []
    ingresses = _items("ingresses")
    if not ingresses:
        return out
    services = {f"{s['metadata']['namespace']}/{s['metadata']['name']}": s for s in _items("services") or []}
    secret_names = _secret_names({i["metadata"]["namespace"] for i in ingresses})
    for ing in ingresses:
        ns = ing["metadata"]["namespace"]
        spec = ing.get("spec", {})
        backends = []
        if spec.get("defaultBackend", {}).get("service"):
            backends.append(spec["defaultBackend"]["service"])
        for rule in spec.get("rules", []):
            for path in rule.get("http", {}).get("paths", []):
                if path.get("backend", {}).get("service"):
                    backends.append(path["backend"]["service"])
        for b in backends:
            svc = services.get(f"{ns}/{b.get('name')}")
            port = b.get("port", {})
            if not svc:
                out.append(_finding(ing, "Ingress", "BackendServiceMissing", f"backend service '{b.get('name')}' does not exist in {ns}"))
                continue
            ports = svc.get("spec", {}).get("ports", [])
            if port.get("number") and all(p.get("port") != port["number"] for p in ports):
                out.append(_finding(ing, "Ingress", "BackendPortMismatch",
                                    f"service {b['name']} exposes ports {[p.get('port') for p in ports]}, ingress uses {port['number']}"))
            if port.get("name") and all(p.get("name") != port["name"] for p in ports):
                out.append(_finding(ing, "Ingress", "BackendPortMismatch",
                                    f"service {b['name']} has no port named '{port['name']}'"))
        for tls in spec.get("tls", []):
            if secret_names is not None and tls.get("secretName") and f"{ns}/{tls['secretName']}" not in secret_names:
                out.append(_finding(ing, "Ingress", "TLSSecretMissing", f"TLS secret '{tls['secretName']}' does not exist in {ns}",
                                    f"kubectl create secret tls {tls['secretName']} -n {ns} --cert=tls.crt --key=tls.key"))
        if not ing.get("status", {}).get("loadBalancer", {}).get("ingress") and _age_seconds(ing["metadata"].get("creationTimestamp")) > 300:
            cls = spec.get("ingressClassName")
            out.append(_finding(ing, "Ingress", "NoAddress", "no load balancer address assigned; check the ingress controller and ingressClassName "
                                f"({cls or 'default'})",
                                (f"kubectl get ingressclass {cls}" if cls else "kubectl get ingressclass")
                                + " && kubectl get svc -A -l app.kubernetes.io/component=controller"))
    return out


def inspect_loadbalancers() -> list[Finding]:
    out = []
    for s in _items("services") or []:
        if s.get("spec", {}).get("type") == "LoadBalancer" and not s.get("status", {}).get("loadBalancer", {}).get("ingress") \
                and _age_seconds(s["metadata"].get("creationTimestamp")) > 300:
            ns, name = s["metadata"]["namespace"], s["metadata"]["name"]
            annotations = {k: v for k, v in s["metadata"].get("annotations", {}).items() if "load-balancer" in k or "loadbalancer" in k}
            out.append(_finding(s, "Service", "LoadBalancerPending",
                                f"type LoadBalancer has no external IP after 5 minutes; LB annotations {annotations or 'none'}",
                                f"kubectl get events -n {ns} --field-selector involvedObject.kind=Service,involvedObject.name={name} --sort-by=.lastTimestamp"))
    return out


def inspect_network_policies(problem_pods: list[dict[str, Any]]) -> list[Finding]:
    """NetworkPolicies in namespaces with failing pods (default-deny policies explain connection timeouts)."""
    out = []
    namespaces = {p["namespace"] for p in problem_pods}
    for np in _items("networkpolicies") or []:
        ns = np["metadata"]["namespace"]
        spec = np.get("spec", {})
        default_deny = not spec.get("podSelector") and "Ingress" in spec.get("policyTypes", []) and not spec.get("ingress")
        if ns in namespaces or default_deny:
            out.append(_finding(np, "NetworkPolicy", "DefaultDeny" if default_deny else "Present",
                                f"podSelector {spec.get('podSelector') or 'all pods'}; policyTypes {spec.get('policyTypes')}; "
                                f"{len(spec.get('ingress', []))} ingress / {len(spec.get('egress', []))} egress rules"))
    return out


# ---------------------------------------------------------------- capacity & scheduling


def inspect_quotas() -> list[Finding]:
    out = []
    for q in _items("resourcequotas") or []:
        hard, used = q.get("status", {}).get("hard", {}), q.get("status", {}).get("used", {})
        full = [f"{r} {used.get(r)}/{h}" for r, h in hard.items() if _qty(used.get(r)) >= _qty(h) * 0.9 and _qty(h) > 0]
        if full:
            out.append(_finding(q, "ResourceQuota", "NearlyExhausted", "; ".join(full)))
    for lr in _items("limitranges") or []:
        out.append(_finding(lr, "LimitRange", "Present", str(lr.get("spec", {}).get("limits", []))[:250]))
    return out


def _qty(value: Any) -> float:
    """Parse Kubernetes quantities (100m, 2Gi, 5) into a comparable number."""
    if value is None:
        return 0
    s = str(value)
    units = {"m": 1e-3, "Ki": 2**10, "Mi": 2**20, "Gi": 2**30, "Ti": 2**40, "k": 1e3, "M": 1e6, "G": 1e9, "T": 1e12}
    for suffix in sorted(units, key=len, reverse=True):
        if s.endswith(suffix):
            try:
                return float(s[: -len(suffix)]) * units[suffix]
            except ValueError:
                return 0
    try:
        return float(s)
    except ValueError:
        return 0


def _scale_hint(node: str, cloud: str | None, node_count: int) -> str:
    """Add a node to the pool (max pods per node usually cannot be changed on an existing pool)."""
    if cloud and cloud.startswith("AKS") and node.startswith("aks-"):
        pool = node.split("-")[1]  # aks-<pool>-<id>-vmss...
        return (f"az aks nodepool scale --resource-group $RESOURCE_GROUP --cluster-name $CLUSTER_NAME "
                f"--name {pool} --node-count {node_count + 1}")
    if cloud and cloud.startswith("EKS"):
        return f"eksctl scale nodegroup --cluster $CLUSTER_NAME --name $NODEGROUP --nodes {node_count + 1}"
    if cloud and cloud.startswith("GKE"):
        return f"gcloud container clusters resize $CLUSTER_NAME --node-pool $POOL --num-nodes {node_count + 1}"
    return f"kubectl describe node {node} | grep -A5 'Allocated resources'"


def inspect_capacity(nodes: dict[str, Any]) -> list[Finding]:
    """Pod density per node, node usage from `kubectl top` (if metrics-server works), and PDBs that block drains."""
    out = []
    res = run_kubectl(["get", "pods", "-A", "--field-selector=status.phase=Running", "-o", "jsonpath={.items[*].spec.nodeName}"])
    if res["success"]:
        counts = Counter(res["stdout"].split())
        for n in nodes.get("nodes", []):
            max_pods = int(n.get("max_pods") or 0)
            if max_pods and counts.get(n["name"], 0) >= max_pods * 0.9:
                out.append({"kind": "Node", "namespace": None, "name": n["name"], "problem": "PodDensityHigh",
                            "detail": f"{counts[n['name']]}/{max_pods} pods; new pods may fail with 'Too many pods'",
                            "hint": _scale_hint(n["name"], nodes.get("cloud_provider"), len(nodes.get("nodes", [])))})
    top = run_kubectl(["top", "nodes", "--no-headers"])
    if top["success"]:
        for line in top["stdout"].splitlines():
            parts = line.split()
            if len(parts) >= 5 and parts[2].endswith("%") and parts[4].endswith("%"):
                cpu, mem = int(parts[2][:-1]), int(parts[4][:-1])
                if cpu >= 90 or mem >= 90:
                    out.append({"kind": "Node", "namespace": None, "name": parts[0], "problem": "HighUsage",
                                "detail": f"CPU {cpu}%, memory {mem}%"})
    for pdb in _items("poddisruptionbudgets") or []:
        st = pdb.get("status", {})
        if st.get("expectedPods", 0) and st.get("disruptionsAllowed", 1) == 0:
            out.append(_finding(pdb, "PodDisruptionBudget", "BlocksDisruption",
                                f"0 disruptions allowed ({st.get('currentHealthy')}/{st.get('expectedPods')} healthy); node drains will hang"))
    return out


# ---------------------------------------------------------------- security & access


def inspect_access(logs: dict[str, Any], pod_details: dict[str, Any]) -> list[Finding]:
    """RBAC 'forbidden' errors in logs, and private-registry pull failures without imagePullSecrets."""
    import re

    out, seen = [], set()
    pattern = re.compile(r'"?(system:serviceaccount:([\w.-]+):([\w.-]+))"? cannot (\w+) resource "([\w./-]+)"(?: in API group "([\w.-]*)")?')
    for log in logs.get("logs", []):
        for line in (log.get("relevant_lines") or []) + (log.get("last_lines") or []):
            m = pattern.search(line)
            if m and m.group(0) not in seen:
                seen.add(m.group(0))
                _, ns, sa, verb, resource, group = m.groups()
                out.append({"kind": "ServiceAccount", "namespace": ns, "name": sa, "problem": "RBACForbidden",
                            "detail": f"cannot {verb} {resource} (api group '{group or 'core'}'), seen in pod {log.get('pod')}",
                            "hint": f"kubectl create role {sa}-{resource.split('.')[0]}-{verb} -n {ns} --verb={verb} --resource={resource} && "
                                    f"kubectl create rolebinding {sa}-{resource.split('.')[0]}-{verb} -n {ns} "
                                    f"--role={sa}-{resource.split('.')[0]}-{verb} --serviceaccount={ns}:{sa}"})
    for key, details in pod_details.items():
        ns, pod = key.split("/", 1)
        auth_error = any(w in (e.get("message") or "").lower() for e in details.get("events", [])
                         for w in ("unauthorized", "authentication required", "denied", "401", "403"))
        if auth_error:
            out.append({"kind": "Pod", "namespace": ns, "name": pod, "problem": "RegistryAuthFailed",
                        "detail": f"image pull was refused by the registry; imagePullSecrets: {details.get('image_pull_secrets') or 'none'}",
                        "hint": f"kubectl create secret docker-registry regcred -n {ns} --docker-server=$REGISTRY "
                                f"--docker-username=$USER --docker-password=$PASSWORD && kubectl patch serviceaccount default -n {ns} "
                                "-p '{\"imagePullSecrets\":[{\"name\":\"regcred\"}]}'"})
    return out


def inspect_certificates() -> list[Finding]:
    """Expired/expiring TLS secrets (only the public certificate is read) and cert-manager Certificates not Ready."""
    out = []
    res = run_kubectl(["get", "secrets", *scope_args(), "--field-selector", "type=kubernetes.io/tls", "-o",
                       "jsonpath={range .items[*]}{.metadata.namespace}{\"\\t\"}{.metadata.name}{\"\\t\"}{.data.tls\\.crt}{\"\\n\"}{end}"])
    if res["success"]:
        try:
            from cryptography import x509
        except ImportError:  # optional dependency
            x509 = None
        for line in res["stdout"].splitlines():
            parts = line.split("\t")
            if len(parts) != 3 or not parts[2] or x509 is None:
                continue
            try:
                cert = x509.load_pem_x509_certificate(base64.b64decode(parts[2]))
            except Exception:  # noqa: BLE001 - malformed cert is not our problem to report
                continue
            days = (cert.not_valid_after_utc - datetime.now(UTC)).days
            if days < CERT_WARN_DAYS:
                out.append({"kind": "Secret", "namespace": parts[0], "name": parts[1],
                            "problem": "CertificateExpired" if days < 0 else "CertificateExpiringSoon",
                            "detail": f"TLS certificate {'expired' if days < 0 else 'expires'} {cert.not_valid_after_utc:%Y-%m-%d} ({days} days)"})
    for c in _items("certificates.cert-manager.io") or []:
        ready = _condition(c, "Ready")
        if ready.get("status") == "False":
            ns, name = c["metadata"]["namespace"], c["metadata"]["name"]
            out.append(_finding(c, "Certificate", ready.get("reason") or "NotReady", ready.get("message", ""),
                                f"kubectl describe certificaterequest -n {ns} -l cert-manager.io/certificate-name={name}"))
    return out


# ---------------------------------------------------------------- platform


def inspect_helm() -> list[Finding]:
    """Helm releases whose latest revision failed or is stuck pending (read from release labels only)."""
    # Table output with --show-labels: release name/version/status come from labels, no secret data is fetched.
    res = run_kubectl(["get", "secrets", *scope_args(), "-l", "owner=helm", "--no-headers", "--show-labels"])
    if not res["success"]:
        return []
    rows = []
    for line in res["stdout"].splitlines():
        cols = line.split()
        if not cols:
            continue
        ns = cols[0] if scope_args() == ["-A"] else scope_args()[1]
        labels = dict(kv.split("=", 1) for kv in cols[-1].split(",") if "=" in kv)
        rows.append([ns, labels.get("name", ""), labels.get("version", ""), labels.get("status", "")])
    latest: dict[tuple[str, str], tuple[int, str]] = {}
    for parts in rows:
        if parts[1] and parts[2].isdigit():
            key, rev = (parts[0], parts[1]), int(parts[2])
            if rev > latest.get(key, (0, ""))[0]:
                latest[key] = (rev, parts[3])
    out = []
    for (ns, name), (rev, status) in latest.items():
        if status in ("failed", "pending-install", "pending-upgrade", "pending-rollback"):
            hint = f"helm rollback {name} {rev - 1} -n {ns}" if rev > 1 and status != "pending-install" else None
            out.append({"kind": "HelmRelease", "namespace": ns, "name": name, "problem": status,
                        "detail": f"revision {rev} is {status}", **({"hint": hint} if hint else {})})
    return out


def inspect_addons(problem_pods: list[dict[str, Any]], findings: list[Finding]) -> list[Finding]:
    """Flag failures in cluster add-ons (CNI, DNS, metrics, CSI, ingress); these cascade into many symptoms."""
    out = []
    for p in problem_pods:
        if p["namespace"] in SYSTEM_NAMESPACES or any(h in p["name"] for h in ADDON_HINTS):
            out.append({"kind": "Pod", "namespace": p["namespace"], "name": p["name"], "problem": "AddonUnhealthy",
                        "detail": f"cluster add-on pod is {p['status']} (ready {p.get('ready')}); fix this first, other failures may be side effects"})
    for f in findings:
        if f["kind"] == "DaemonSet" and (f.get("namespace") in SYSTEM_NAMESPACES or any(h in (f.get("name") or "") for h in ADDON_HINTS)):
            out.append({**f, "problem": "AddonUnhealthy"})
    return out


# ---------------------------------------------------------------- entry point


def inspect_resources(problem_pods: list[dict[str, Any]], pod_details: dict[str, Any],
                      logs: dict[str, Any], nodes: dict[str, Any]) -> dict[str, Any]:
    """Run every inspector; one failing (e.g. forbidden) inspector never breaks the others."""
    checks: dict[str, Callable[[], list[Finding]]] = {
        "workloads": lambda: inspect_statefulsets() + inspect_daemonsets() + inspect_jobs() + inspect_hpas() + inspect_rollouts(),
        "storage": lambda: inspect_storage() + inspect_config_refs(pod_details),
        "networking": lambda: inspect_ingresses() + inspect_loadbalancers() + inspect_network_policies(problem_pods),
        "capacity": lambda: inspect_quotas() + inspect_capacity(nodes),
        "security": lambda: inspect_access(logs, pod_details) + inspect_certificates(),
        "platform": inspect_helm,
    }
    def run(name: str, check: Callable[[], list[Finding]]) -> list[Finding]:
        try:
            return check()
        except Exception as exc:  # noqa: BLE001 - keep the investigation going
            logger.warning("Inspector {} failed: {}", name, exc)
            return []

    # Categories are independent, so run them in parallel. Each thread gets a copy of the
    # context so the selected cluster/namespace (ContextVars) apply inside it.
    with ThreadPoolExecutor(max_workers=len(checks)) as pool:
        futures = {name: pool.submit(contextvars.copy_context().run, run, name, check) for name, check in checks.items()}
        findings: dict[str, list[Finding]] = {name: f.result() for name, f in futures.items()}
    findings["platform"] += inspect_addons(problem_pods, findings["workloads"])
    # LimitRanges / non-deny NetworkPolicies are context, not problems
    context_only = {"Present"}
    problems = sum(1 for fs in findings.values() for f in fs if f["problem"] not in context_only)
    return {"healthy": problems == 0, "problem_count": problems, "findings": {k: v for k, v in findings.items() if v}}
