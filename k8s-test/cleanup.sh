#!/usr/bin/env bash
# Remove all test workloads.
set -euo pipefail
kubectl delete namespace k8s-agent-test --ignore-not-found
