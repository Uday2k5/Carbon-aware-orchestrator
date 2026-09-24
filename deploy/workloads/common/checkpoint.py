"""Cooperative application-level checkpointing shared by the workload containers.

    state = CheckpointableState(job, state_mb)       # loads /checkpoints/<job>/state.bin if present
    state.install_signal_handlers()                   # SIGTERM / SIGUSR1 -> checkpoint now
    ... training loop mutates state.buffer, calls state.step() ...

Metrics (last_checkpoint_s, bytes, restores) go to /checkpoints/<job>/metrics.json so the
controller can read real checkpoint/restore timings on the shared volume.
"""
from __future__ import annotations

import json
import os
import signal
import sys
import time

import numpy as np

CKPT_ROOT = os.environ.get("CHECKPOINT_DIR", "/checkpoints")


class CheckpointableState:
    def __init__(self, job: str, state_mb: float, total_steps: int):
        self.job = job
        self.dir = os.path.join(CKPT_ROOT, job)
        os.makedirs(self.dir, exist_ok=True)
        self.path = os.path.join(self.dir, "state.bin")
        self.meta_path = os.path.join(self.dir, "meta.json")
        self.metrics_path = os.path.join(self.dir, "metrics.json")
        self.total_steps = total_steps
        self.step_no = 0
        self.metrics = {"checkpoints": 0, "restores": 0, "last_checkpoint_s": None,
                        "last_restore_s": None, "bytes": 0, "node": os.environ.get("NODE_NAME", "?")}
        n = int(state_mb * 1024 * 1024 // 4)
        if os.path.exists(self.path) and os.path.exists(self.meta_path):
            t0 = time.perf_counter()
            self.buffer = np.fromfile(self.path, dtype=np.float32)
            with open(self.meta_path) as fh:
                self.step_no = int(json.load(fh)["step"])
            self.metrics["last_restore_s"] = time.perf_counter() - t0
            self.metrics["restores"] += 1
            self._log(f"restored step {self.step_no} ({self.buffer.nbytes / 1e6:.0f} MB) in {self.metrics['last_restore_s']:.2f}s")
        else:
            self.buffer = np.random.default_rng(0).standard_normal(n, dtype=np.float32)
            self._log(f"fresh state ({self.buffer.nbytes / 1e6:.0f} MB)")
        self._write_metrics()

    def checkpoint(self) -> float:
        t0 = time.perf_counter()
        tmp = self.path + ".tmp"
        self.buffer.tofile(tmp)
        with open(tmp, "rb") as fh:
            os.fsync(fh.fileno())
        os.replace(tmp, self.path)
        with open(self.meta_path, "w") as fh:
            json.dump({"step": self.step_no, "ts": time.time()}, fh)
        dt = time.perf_counter() - t0
        self.metrics.update(checkpoints=self.metrics["checkpoints"] + 1, last_checkpoint_s=dt,
                            bytes=int(self.buffer.nbytes))
        self._write_metrics()
        self._log(f"checkpoint step {self.step_no} in {dt:.2f}s")
        return dt

    def step(self) -> None:
        self.step_no += 1
        self.remaining_h_hint()

    def done(self) -> bool:
        return self.step_no >= self.total_steps

    def remaining_h_hint(self) -> None:
        """Write remaining work so the controller can read it (via metrics.json)."""
        step_s = float(os.environ.get("STEP_SECONDS", "1"))
        self.metrics["remaining_h"] = max(0, self.total_steps - self.step_no) * step_s / 3600.0
        if self.step_no % 10 == 0:
            self._write_metrics()

    def install_signal_handlers(self) -> None:
        def on_term(signum, frame):
            self._log(f"signal {signum}: checkpoint and exit")
            self.checkpoint()
            sys.exit(0)

        def on_usr1(signum, frame):
            self.checkpoint()

        signal.signal(signal.SIGTERM, on_term)
        signal.signal(signal.SIGINT, on_term)
        signal.signal(signal.SIGUSR1, on_usr1)

    def _write_metrics(self) -> None:
        tmp = self.metrics_path + ".tmp"
        with open(tmp, "w") as fh:
            json.dump(self.metrics, fh)
        os.replace(tmp, self.metrics_path)

    def _log(self, msg: str) -> None:
        print(f"[{self.job}] {msg}", flush=True)
