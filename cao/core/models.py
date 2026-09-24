"""Domain model shared by decision engine, simulator and Kubernetes controller."""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Optional


class JobKind(str, Enum):
    ML_TRAINING = "ml-training"
    BATCH = "batch-processing"
    WEB_SERVICE = "web-service"


class ActionType(str, Enum):
    MOVE = "MOVE"      # migrate now to target_region
    WAIT = "WAIT"      # do not run this slot; resume/start at resume_at_h (temporal shift)
    HOLD = "HOLD"      # keep current placement; no greener feasible option exists
    REFUSE = "REFUSE"  # a greener region exists but migration carbon > carbon saved


@dataclass
class Job:
    """A schedulable workload.

    `region` is where the job's *state* currently resides (running or checkpointed).
    Hours are relative to the scheduler's time origin (simulation start or controller epoch).
    """

    job_id: str
    kind: str
    power_kw: float                 # mean electrical draw while running
    duration_h: float               # total execution time needed
    state_gb: float                 # checkpointable state that must move with the job
    origin: str                     # region where the job was submitted
    release_h: float = 0.0          # earliest start
    deadline_h: Optional[float] = None
    user_region: Optional[str] = None
    sla_rtt_ms: Optional[float] = None   # hard latency constraint (web services)
    preemptible: bool = True        # may pause / be delayed (WAIT)
    movable: bool = True            # may change region (MOVE)
    cpu: float = 1.0                # CPU units for capacity constraints
    region: Optional[str] = None    # current residence; defaults to origin
    started: bool = False
    running: bool = False           # executing in the current slot
    progress_h: float = 0.0
    done: bool = False
    completed_at_h: Optional[float] = None
    migrations: int = 0
    exec_carbon_g: float = 0.0
    migration_carbon_g: float = 0.0
    tags: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.region is None:
            self.region = self.origin
        if self.kind == JobKind.WEB_SERVICE.value:
            # Always-on services never wait and are measured over an evaluation horizon.
            self.preemptible = False

    @property
    def remaining_h(self) -> float:
        return max(0.0, self.duration_h - self.progress_h)

    def remaining_slots(self, slot_h: float) -> int:
        return int(math.ceil(self.remaining_h / slot_h - 1e-9))

    @property
    def is_always_on(self) -> bool:
        return self.kind == JobKind.WEB_SERVICE.value

    @property
    def total_carbon_g(self) -> float:
        return self.exec_carbon_g + self.migration_carbon_g

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Decision:
    job_id: str
    action: ActionType
    target_region: Optional[str] = None
    resume_at_h: Optional[float] = None
    reason: str = ""
    saved_g: float = 0.0            # carbon saved over remaining runtime if moved
    migration_g: float = 0.0        # carbon cost of the migration itself
    payback_h: Optional[float] = None
    remaining_h: float = 0.0

    @property
    def net_g(self) -> float:
        return self.saved_g - self.migration_g

    def to_dict(self) -> dict:
        d = asdict(self)
        d["action"] = self.action.value
        d["net_g"] = self.net_g
        return d
