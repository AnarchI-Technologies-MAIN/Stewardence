"""Read-only wall/monotonic sampling inside an isolated qualification image."""

import json
import time

started = time.monotonic()
previous_wall = time.time_ns()
previous_mono = time.monotonic_ns()
minimum_residual = 0
steps = []
samples = 0
while time.monotonic() - started < 64:
    time.sleep(0.05)
    wall = time.time_ns()
    mono = time.monotonic_ns()
    residual = (wall - previous_wall) - (mono - previous_mono)
    minimum_residual = min(minimum_residual, residual)
    if residual < -50_000_000:
        steps.append(
            {
                "wall_before_ns": previous_wall,
                "wall_after_ns": wall,
                "monotonic_delta_ns": mono - previous_mono,
                "wall_minus_monotonic_delta_ns": residual,
            }
        )
    previous_wall, previous_mono = wall, mono
    samples += 1
print(
    json.dumps(
        {
            "elapsed_monotonic_seconds": time.monotonic() - started,
            "samples": samples,
            "minimum_residual_ns": minimum_residual,
            "backward_steps_over_50ms": steps,
        }
    ),
    flush=True,
)
