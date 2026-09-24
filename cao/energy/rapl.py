"""Intel RAPL energy counters (Linux only): /sys/class/powercap/intel-rapl:*/energy_uj."""
from __future__ import annotations

import glob
import os
from typing import List


class RaplReader:
    ROOT = "/sys/class/powercap"

    def __init__(self) -> None:
        self.domains: List[str] = sorted(
            d for d in glob.glob(os.path.join(self.ROOT, "intel-rapl:*"))
            if os.path.exists(os.path.join(d, "energy_uj")) and ":" in os.path.basename(d)
            and os.path.basename(d).count(":") == 1  # packages only (skip sub-domains)
        )
        self._max = {}
        for d in self.domains:
            try:
                with open(os.path.join(d, "max_energy_range_uj")) as fh:
                    self._max[d] = int(fh.read().strip())
            except OSError:
                self._max[d] = 2**32

    @staticmethod
    def available() -> bool:
        try:
            r = RaplReader()
            r.read_uj()
            return bool(r.domains)
        except Exception:
            return False

    def read_uj(self) -> dict:
        out = {}
        for d in self.domains:
            with open(os.path.join(d, "energy_uj")) as fh:
                out[d] = int(fh.read().strip())
        return out

    def delta_j(self, before: dict, after: dict) -> float:
        total = 0
        for d in self.domains:
            diff = after[d] - before[d]
            if diff < 0:
                diff += self._max.get(d, 2**32)
            total += diff
        return total / 1e6
