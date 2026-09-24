"""Labels / annotations contract between workloads, nodes and the controller."""

NODE_REGION_LABEL = "topology.carbon-aware.io/region"
MANAGED_LABEL = "carbon-aware.io/managed"          # "true" on pods the controller may move
DEPLOYMENT_LABEL = "carbon-aware.io/deployment"    # name of the owning Deployment

A = "carbon-aware.io/"
ANN_KIND = A + "kind"                # ml-training | batch-processing | web-service
ANN_POWER_KW = A + "power-kw"
ANN_STATE_GB = A + "state-gb"
ANN_REMAINING_H = A + "remaining-h"  # updated by the workload as it progresses
ANN_DEADLINE = A + "deadline"        # RFC3339 UTC
ANN_USER_REGION = A + "user-region"
ANN_SLA_RTT_MS = A + "sla-rtt-ms"
ANN_PREEMPTIBLE = A + "preemptible"
ANN_MOVABLE = A + "movable"
ANN_CPU = A + "cpu"
ANN_LAST_DECISION = A + "last-decision"
ANN_LAST_MIGRATION = A + "last-migration"
