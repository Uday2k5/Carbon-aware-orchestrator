#!/usr/bin/env bash
# Local multi-"region" Kubernetes testbed: 1 server + 5 agents, each agent labelled as a region.
# Requires: docker, k3d, kubectl.   Usage: bash deploy/k3d/create-cluster.sh [cluster-name]
set -euo pipefail
NAME="${1:-carbon}"
CKPT_DIR="${CAO_CHECKPOINTS_DIR:-$HOME/cao-checkpoints}"
mkdir -p "$CKPT_DIR"

# --volume: every node mounts the same host dir at /checkpoints (shared checkpoint store).
k3d cluster create "$NAME" --agents 5 --servers 1 \
  --volume "$CKPT_DIR:/checkpoints@all" \
  --k3s-arg "--disable=traefik@server:0" \
  --wait

REGIONS=(india sweden france us-east uk)
for i in "${!REGIONS[@]}"; do
  kubectl label node "k3d-${NAME}-agent-${i}" "topology.carbon-aware.io/region=${REGIONS[$i]}" --overwrite
done
kubectl taint node "k3d-${NAME}-server-0" node-role.kubernetes.io/control-plane=:NoSchedule --overwrite || true

kubectl create namespace cao --dry-run=client -o yaml | kubectl apply -f -
kubectl get nodes -L topology.carbon-aware.io/region
echo "checkpoints shared at $CKPT_DIR  (export CAO_CHECKPOINTS_DIR to change)"
echo "next: bash deploy/workloads/build.sh $NAME && kubectl apply -f deploy/k8s/workloads/"
