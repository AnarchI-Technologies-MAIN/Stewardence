"""Read-only 64-second realtime/monotonic/raw rate discriminator."""
import json
import time

started = time.monotonic()
previous = (time.time_ns(), time.monotonic_ns(), time.clock_gettime_ns(time.CLOCK_MONOTONIC_RAW))
steps = []
segments = []
while time.monotonic() - started < 64:
    time.sleep(0.05)
    current = (time.time_ns(), time.monotonic_ns(), time.clock_gettime_ns(time.CLOCK_MONOTONIC_RAW))
    wall, mono, raw = tuple(b-a for a,b in zip(previous,current))
    segments.append({"wall_ns":wall,"monotonic_ns":mono,"raw_ns":raw})
    if wall-mono < -50_000_000:
        steps.append({"wall_before_ns":previous[0],"wall_after_ns":current[0],"monotonic_delta_ns":mono,"raw_delta_ns":raw,"residual_ns":wall-mono})
    previous = current
positive = [s for s in segments if abs(s["wall_ns"]-s["monotonic_ns"]) < 50_000_000]
raw_total = sum(s["raw_ns"] for s in positive)
print(json.dumps({"samples":len(segments),"backsteps":steps,"monotonic_raw_rate_ratio":sum(s["monotonic_ns"] for s in positive)/raw_total,"realtime_raw_rate_ratio_without_steps":sum(s["wall_ns"] for s in positive)/raw_total,"elapsed_monotonic_seconds":time.monotonic()-started}),flush=True)
