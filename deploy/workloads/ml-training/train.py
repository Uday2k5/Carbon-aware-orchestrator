"""Fake ML training: matmul-heavy steps over a large float32 'weights' buffer.
Env: JOB_NAME, STATE_MB (default 200), TOTAL_STEPS (3600), STEP_SECONDS (1), CHECKPOINT_EVERY (60)."""
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "common"))
from checkpoint import CheckpointableState  # noqa: E402

job = os.environ.get("JOB_NAME", "ml-training")
state = CheckpointableState(job, float(os.environ.get("STATE_MB", "200")), int(os.environ.get("TOTAL_STEPS", "3600")))
state.install_signal_handlers()
every = int(os.environ.get("CHECKPOINT_EVERY", "60"))
step_s = float(os.environ.get("STEP_SECONDS", "1"))
a = np.random.default_rng(1).standard_normal((512, 512), dtype=np.float32)

while not state.done():
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < step_s:          # burn ~STEP_SECONDS of CPU
        a = np.tanh(a @ a.T / 512.0)
    state.buffer[: 512 * 512] += a.ravel()[: min(a.size, state.buffer.size)] * 1e-3  # "gradient update"
    state.step()
    if state.step_no % every == 0:
        state.checkpoint()
state.checkpoint()
print(f"[{job}] training complete", flush=True)
while True:                                            # keep pod alive for inspection
    time.sleep(3600)
