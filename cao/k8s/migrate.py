"""Cooperative migration on Kubernetes.

    1. record t0, annotate the pod with the decision
    2. patch the Deployment's nodeSelector to the target region
       -> kubelet sends SIGTERM to the old pod; the workload's handler writes a final
          checkpoint to the shared /checkpoints volume (terminationGracePeriodSeconds must
          cover state_gb * seconds_per_gb)
       -> the new pod starts on a node in the target region and restores from /checkpoints
    3. wait until the Deployment is Ready again; total_s is the observed downtime

Checkpoint duration is written by the workload to /checkpoints/<job>/metrics.json (the
controller reads it when it shares the hostPath, e.g. k3d --volume ...:/checkpoints@all).
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Optional

from .client import KubeClient, PodInfo
from . import constants as C


@dataclass
class MigrationRecord:
    timestamp: str
    job_id: str
    from_region: Optional[str]
    to_region: str
    state_gb: float
    checkpoint_s: Optional[float]
    reschedule_s: float
    total_s: float
    success: bool
    detail: dict

    def to_dict(self) -> dict:
        return asdict(self)


def migrate(
    kube: KubeClient,
    pod: PodInfo,
    target_region: str,
    state_gb: float,
    checkpoints_dir: Optional[str] = None,
    timeout_s: float = 900.0,
    from_region: Optional[str] = None,
) -> MigrationRecord:
    dep = pod.deployment
    if not dep:
        raise ValueError(f"pod {pod.name} has no {C.DEPLOYMENT_LABEL} label")
    t0 = time.monotonic()
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    kube.annotate_pod(pod.name, pod.namespace, {C.ANN_LAST_MIGRATION: f"{stamp} -> {target_region}"})
    kube.patch_deployment_node_selector(dep, pod.namespace, target_region)
    ok = kube.wait_for_ready(dep, pod.namespace, timeout_s=timeout_s)
    total = time.monotonic() - t0
    ckpt_s = _read_checkpoint_seconds(checkpoints_dir, dep)
    return MigrationRecord(
        timestamp=stamp, job_id=dep, from_region=from_region, to_region=target_region,
        state_gb=state_gb, checkpoint_s=ckpt_s, reschedule_s=total - (ckpt_s or 0.0),
        total_s=total, success=ok, detail={"pod": pod.name, "namespace": pod.namespace},
    )


def _read_checkpoint_seconds(checkpoints_dir: Optional[str], job: str) -> Optional[float]:
    if not checkpoints_dir:
        return None
    p = os.path.join(checkpoints_dir, job, "metrics.json")
    try:
        with open(p) as fh:
            return float(json.load(fh).get("last_checkpoint_s"))
    except (OSError, ValueError, TypeError):
        return None
