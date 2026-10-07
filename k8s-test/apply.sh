#!/usr/bin/env bash
# Create the intentionally broken test workloads.
set -euo pipefail
cd "$(dirname "$0")"
kubectl apply -f scenarios.yaml
echo "Wait ~1 minute, then click 'Investigate Cluster' in the app."
