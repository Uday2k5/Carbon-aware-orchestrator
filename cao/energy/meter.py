"""EnergyMeter: measure Joules consumed during a code block.

    with EnergyMeter(power_model) as m:
        do_work()
    m.joules, m.seconds, m.avg_watts, m.method

Uses RAPL when available (Linux/Intel), else integrates the utilisation power model over
non-blocking psutil CPU samples.  On macOS / WSL2 without RAPL the estimate is model-based:
calibrate `power_model` with a wall-plug meter before reporting absolute numbers.

Wall time is taken *before* the sampler thread is joined, so short phases are not inflated
by the sampling interval.
"""
from __future__ import annotations

import threading
import time
from typing import List, Optional

from .power_model import UtilizationPowerModel
from .rapl import RaplReader


class EnergyMeter:
    def __init__(
        self,
        power_model: Optional[UtilizationPowerModel] = None,
        sample_interval_s: float = 0.1,
        use_rapl: bool = True,
    ) -> None:
        self.power_model = power_model or UtilizationPowerModel()
        self.sample_interval_s = sample_interval_s
        self.use_rapl = use_rapl
        self.samples: List[float] = []      # cpu utilisation fractions, one per interval
        self.joules = 0.0
        self.seconds = 0.0
        self.method = "model"
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._rapl: Optional[RaplReader] = None
        self._rapl_before = None
        self._t0 = 0.0
        self._psutil = None

    @property
    def avg_watts(self) -> float:
        return self.joules / self.seconds if self.seconds > 0 else 0.0

    @property
    def avg_utilisation(self) -> float:
        return sum(self.samples) / len(self.samples) if self.samples else 0.0

    def __enter__(self) -> "EnergyMeter":
        import psutil

        self._psutil = psutil
        if self.use_rapl and RaplReader.available():
            self._rapl = RaplReader()
            self._rapl_before = self._rapl.read_uj()
            self.method = "rapl"
        psutil.cpu_percent(interval=None)  # prime: next call returns utilisation since now
        self._stop.clear()
        self._thread = threading.Thread(target=self._sample, daemon=True)
        self._t0 = time.perf_counter()
        self._thread.start()
        return self

    def _sample(self) -> None:
        # cpu_percent(None) is non-blocking: utilisation since the previous call.
        while not self._stop.wait(self.sample_interval_s):
            self.samples.append(self._psutil.cpu_percent(interval=None) / 100.0)

    def __exit__(self, *exc) -> None:
        self.seconds = time.perf_counter() - self._t0
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1.0)
        # final partial interval (or the whole phase, if it was shorter than one interval)
        self.samples.append(self._psutil.cpu_percent(interval=None) / 100.0)
        if self._rapl is not None:
            self.joules = self._rapl.delta_j(self._rapl_before, self._rapl.read_uj())
        else:
            self.joules = self.power_model.power_w(self.avg_utilisation) * self.seconds
