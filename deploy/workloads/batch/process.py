"""Batch processing: chunked I/O-ish work over a buffer with periodic checkpoints.
Env: JOB_NAME, STATE_MB (default 500), TOTAL_STEPS (1800), STEP_SECONDS (1), CHECKPOINT_EVERY (120)."""
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "common"))
from checkpoint import CheckpointableState  # noqa: E402

job = os.environ.get("JOB_NAME", "batch")
state = CheckpointableState(job, float(os.environ.get("STATE_MB", "500")), int(os.environ.get("TOTAL_STEPS", "1800")))
state.install_signal_handlers()
every = int(os.environ.get("CHECKPOINT_EVERY", "120"))
step_s = float(os.environ.get("STEP_SECONDS", "1"))
chunk = max(1, state.buffer.size // 64)

while not state.done():
    t0 = time.perf_counter()
    i = (state.step_no % 64) * chunk
    seg = state.buffer[i:i + chunk]
    while time.perf_counter() - t0 < step_s:
        seg[:] = np.sort(seg)[::-1] * 0.999 + 0.001
    state.step()
    if state.step_no % every == 0:
        state.checkpoint()
state.checkpoint()
print(f"[{job}] batch complete", flush=True)
while True:
    time.sleep(3600)
