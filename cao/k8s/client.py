"""Thin Kubernetes access layer with an in-memory fake for tests / dry runs."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from . import constants as C


@dataclass
class PodInfo:
    name: str
    namespace: str
    node: Optional[str]
    labels: Dict[str, str] = field(default_factory=dict)
    annotations: Dict[str, str] = field(default_factory=dict)
    phase: str = "Running"
    ready: bool = True

    @property
    def deployment(self) -> Optional[str]:
        return self.labels.get(C.DEPLOYMENT_LABEL)


class KubeClient:
    def list_managed_pods(self, namespace: Optional[str] = None) -> List[PodInfo]:
        raise NotImplementedError

    def node_region(self, node: str) -> Optional[str]:
        raise NotImplementedError

    def patch_deployment_node_selector(self, name: str, namespace: str, region: str) -> None:
        raise NotImplementedError

    def annotate_pod(self, name: str, namespace: str, annotations: Dict[str, str]) -> None:
        raise NotImplementedError

    def deployment_ready(self, name: str, namespace: str) -> bool:
        raise NotImplementedError

    def wait_for_ready(self, name: str, namespace: str, timeout_s: float = 600, poll_s: float = 2.0) -> bool:
        t0 = time.monotonic()
        while time.monotonic() - t0 < timeout_s:
            if self.deployment_ready(name, namespace):
                return True
            time.sleep(poll_s)
        return False


class FakeKubeClient(KubeClient):
    """Deterministic stand-in: patches are recorded, reschedules complete instantly."""

    def __init__(self, pods: List[PodInfo], node_regions: Dict[str, str]):
        self.pods = {(p.namespace, p.name): p for p in pods}
        self.node_regions = dict(node_regions)
        self.patches: List[tuple] = []
        self.annotations: List[tuple] = []

    def list_managed_pods(self, namespace=None):
        return [p for p in self.pods.values()
                if p.labels.get(C.MANAGED_LABEL) == "true" and (namespace is None or p.namespace == namespace)]

    def node_region(self, node):
        return self.node_regions.get(node)

    def patch_deployment_node_selector(self, name, namespace, region):
        self.patches.append((namespace, name, region))
        node = next((n for n, r in self.node_regions.items() if r == region), None)
        for p in self.pods.values():
            if p.namespace == namespace and p.deployment == name:
                p.node = node

    def annotate_pod(self, name, namespace, annotations):
        self.annotations.append((namespace, name, dict(annotations)))
        self.pods[(namespace, name)].annotations.update(annotations)

    def deployment_ready(self, name, namespace):
        return True

    def wait_for_ready(self, name, namespace, timeout_s=600, poll_s=2.0):
        return True


class KubernetesClient(KubeClient):
    """Real client (pip install kubernetes). Loads kubeconfig or in-cluster config."""

    def __init__(self, kubeconfig: Optional[str] = None, context: Optional[str] = None):
        from kubernetes import client, config

        try:
            config.load_incluster_config()
        except Exception:
            config.load_kube_config(config_file=kubeconfig, context=context)
        self.core = client.CoreV1Api()
        self.apps = client.AppsV1Api()
        self._node_cache: Dict[str, Optional[str]] = {}

    def list_managed_pods(self, namespace=None):
        sel = f"{C.MANAGED_LABEL}=true"
        if namespace:
            items = self.core.list_namespaced_pod(namespace, label_selector=sel).items
        else:
            items = self.core.list_pod_for_all_namespaces(label_selector=sel).items
        out = []
        for p in items:
            ready = any(c.type == "Ready" and c.status == "True" for c in (p.status.conditions or []))
            out.append(PodInfo(
                name=p.metadata.name, namespace=p.metadata.namespace, node=p.spec.node_name,
                labels=dict(p.metadata.labels or {}), annotations=dict(p.metadata.annotations or {}),
                phase=p.status.phase or "Unknown", ready=ready,
            ))
        return out

    def node_region(self, node):
        if node not in self._node_cache:
            n = self.core.read_node(node)
            self._node_cache[node] = (n.metadata.labels or {}).get(C.NODE_REGION_LABEL)
        return self._node_cache[node]

    def patch_deployment_node_selector(self, name, namespace, region):
        body = {"spec": {"template": {"spec": {"nodeSelector": {C.NODE_REGION_LABEL: region}}}}}
        self.apps.patch_namespaced_deployment(name, namespace, body)

    def annotate_pod(self, name, namespace, annotations):
        self.core.patch_namespaced_pod(name, namespace, {"metadata": {"annotations": annotations}})

    def deployment_ready(self, name, namespace):
        d = self.apps.read_namespaced_deployment(name, namespace)
        st = d.status
        want = d.spec.replicas or 1
        return (st.ready_replicas or 0) >= want and (st.updated_replicas or 0) >= want \
            and (st.replicas or 0) == want
