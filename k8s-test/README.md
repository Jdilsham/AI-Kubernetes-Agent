# Failure scenarios

Intentionally broken workloads in the `k8s-agent-test` namespace, used to check that the agent finds the right root cause.

| Workload | Failure | Expected diagnosis |
|---|---|---|
| `payment-service` | CrashLoopBackOff, `DATABASE_URL` env var missing | Missing env variable, add it via secret/configmap |
| `web-frontend` | ImagePullBackOff, image tag does not exist | Invalid image tag, update the deployment image |
| `memory-hog` | OOMKilled, 20Mi memory limit | Memory limit exceeded, raise requests/limits |
| `api` (Service) | Selector `app=api-server` does not match pod label `app=api` | Service selector mismatch, fix the selector |
| `data-volume` (PVC) | StorageClass `fast-ssd-does-not-exist` | PVC Pending, use an existing StorageClass |
| `config-reader` | References ConfigMap `app-config` that does not exist | Missing ConfigMap, create it |
| `nightly-report` (Job) | Exits 1 (database unreachable) | Failed Job, fix the cause and re-run |
| `shop` (Ingress) | Backend Service `shop-frontend` does not exist | Ingress backend missing, create or rename the Service |

```bash
./k8s-test/apply.sh     # create them (wait ~1 minute)
# open the app and click Investigate Cluster
./k8s-test/cleanup.sh   # delete the namespace
```

To test one scenario at a time, scale the others to zero, for example `kubectl -n k8s-agent-test scale deploy/web-frontend --replicas=0`.
