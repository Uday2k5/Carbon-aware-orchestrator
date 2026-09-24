#!/usr/bin/env bash
# Build the three workload images and import them into the k3d cluster.
set -euo pipefail
NAME="${1:-carbon}"
cd "$(dirname "$0")"
for w in ml-training batch web-service; do
  docker build -t "cao/${w}:dev" -f "${w}/Dockerfile" .
done
k3d image import -c "$NAME" cao/ml-training:dev cao/batch:dev cao/web-service:dev
