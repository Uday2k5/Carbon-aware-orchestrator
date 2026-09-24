"""Migration profiler: THE core experiment.

For each state size S: checkpoint (serialise S bytes to disk) -> transfer (loopback TCP or
copy) -> restore (read + checksum), each wrapped in an EnergyMeter.  Output feeds
MigrationCostModel.fit(), which gives measured `a`, `b` per phase instead of guesses.

    cao profile --sizes 0.1,0.5,1,5,10,20 --repeats 3
    cao fit results/migration_profile.csv
"""
from __future__ import annotations

import os
import time
import zlib
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable, List, Optional

import numpy as np
import pandas as pd

from ..energy.meter import EnergyMeter
from ..energy.power_model import UtilizationPowerModel
from .transport import TRANSPORTS

GB = 1024 ** 3
CHUNK = 8 * 1024 * 1024
DEFAULT_SIZES_GB = [0.1, 0.5, 1.0, 5.0, 10.0, 20.0]
SMOKE_SIZES_GB = [0.25, 0.5, 1.0, 2.0]


@dataclass
class MigrationMeasurement:
    state_gb: float
    bytes_state: int
    checkpoint_s: float
    checkpoint_j: float
    transfer_s: float
    transfer_j: float
    bytes_transferred: int
    restore_s: float
    restore_j: float
    transport: str
    energy_method: str
    repeat: int
    timestamp: str

    @property
    def total_s(self) -> float:
        return self.checkpoint_s + self.transfer_s + self.restore_s

    @property
    def total_j(self) -> float:
        return self.checkpoint_j + self.transfer_j + self.restore_j

    def to_dict(self) -> dict:
        d = asdict(self)
        d["total_s"] = self.total_s
        d["total_j"] = self.total_j
        d["throughput_mbps"] = (8 * self.bytes_transferred / 1e6) / self.transfer_s if self.transfer_s else 0.0
        return d


def _write_state(path: str, nbytes: int, rng: np.random.Generator) -> None:
    """Emulates serialising in-memory state: pseudo-random bytes, fsync at the end."""
    block = rng.bytes(CHUNK)
    with open(path, "wb") as fh:
        left = nbytes
        while left > 0:
            n = min(CHUNK, left)
            fh.write(block[:n])
            left -= n
        fh.flush()
        os.fsync(fh.fileno())


def _read_state(path: str) -> int:
    """Emulates deserialising: stream the file and checksum it."""
    crc = 0
    with open(path, "rb") as fh:
        while True:
            data = fh.read(CHUNK)
            if not data:
                break
            crc = zlib.crc32(data, crc)
    return crc


def profile(
    sizes_gb: Iterable[float] = DEFAULT_SIZES_GB,
    workdir: str = "/tmp/cao-profile",
    power_model: Optional[UtilizationPowerModel] = None,
    transport: str = "loopback",
    repeats: int = 1,
    use_rapl: bool = True,
    progress: Optional[Callable[[str], None]] = print,
    seed: int = 0,
) -> pd.DataFrame:
    Path(workdir).mkdir(parents=True, exist_ok=True)
    send = TRANSPORTS[transport]
    pm = power_model or UtilizationPowerModel()
    rng = np.random.default_rng(seed)
    rows: List[MigrationMeasurement] = []
    for s in sizes_gb:
        nbytes = int(s * GB)
        for rep in range(repeats):
            src = os.path.join(workdir, f"state_{s}_{rep}.bin")
            dst = os.path.join(workdir, f"state_{s}_{rep}.restored")
            try:
                with EnergyMeter(pm, use_rapl=use_rapl) as m_ck:
                    _write_state(src, nbytes, rng)
                with EnergyMeter(pm, use_rapl=use_rapl) as m_tx:
                    moved = send(src, dst)
                with EnergyMeter(pm, use_rapl=use_rapl) as m_rs:
                    _read_state(dst)
                row = MigrationMeasurement(
                    state_gb=s, bytes_state=nbytes,
                    checkpoint_s=m_ck.seconds, checkpoint_j=m_ck.joules,
                    transfer_s=m_tx.seconds, transfer_j=m_tx.joules, bytes_transferred=moved,
                    restore_s=m_rs.seconds, restore_j=m_rs.joules,
                    transport=transport, energy_method=m_ck.method, repeat=rep,
                    timestamp=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                )
                rows.append(row)
                if progress:
                    progress(f"{s:>6.2f} GB  ckpt {row.checkpoint_s:6.2f}s/{row.checkpoint_j:7.1f}J  "
                             f"xfer {row.transfer_s:6.2f}s/{row.transfer_j:7.1f}J  "
                             f"restore {row.restore_s:6.2f}s/{row.restore_j:7.1f}J  [{row.energy_method}]")
            finally:
                for p in (src, dst):
                    try:
                        os.remove(p)
                    except OSError:
                        pass
    return pd.DataFrame([r.to_dict() for r in rows])
