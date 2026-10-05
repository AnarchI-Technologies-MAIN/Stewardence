"""User-authorized reversible local clock-controller experiment, no app writes."""

import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if sys.argv[1:] not in (
    ["--authorized-clock-trial"],
    ["--authorized-clock-trial", "--settlement-windows", "6"],
):
    raise SystemExit("Explicit authorization argument required for this service trial")
settlement_windows = 6 if len(sys.argv) == 4 else 1
IMAGE = "sha256:afd7c85b5339b47489a927c86dd036f893bc54d2e9c602dffcf1bc3edc292f1a"
receipt = ROOT / "evidence" / "clock-controller-trial" / datetime.now(UTC).strftime(
    "%Y%m%dT%H%M%S.%fZ"
)
receipt.mkdir(parents=True)


def mail_service(action):
    result = subprocess.run(
        ["wsl", "-d", "AnarchI-Mail", "-u", "root", "--", "systemctl", action,
         "systemd-timesyncd.service"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    return {"exit_code": result.returncode, "stdout": result.stdout, "stderr": result.stderr}


def sample(label):
    discipline = subprocess.run(
        ["wsl", "-d", "docker-desktop", "--", "adjtimex"],
        capture_output=True, text=True, timeout=30,
    )
    (receipt / (label + "-adjtimex.json")).write_text(
        json.dumps({"exit_code": discipline.returncode, "stdout": discipline.stdout,
                    "stderr": discipline.stderr}, indent=2), encoding="utf-8"
    )
    result = subprocess.run(
        ["docker", "run", "--rm", "--init", "--network", "none", "--memory", "128m",
         "--pids-limit", "32", "--mount",
         "type=bind,source=" + str(ROOT / "scripts/probe_clock_discontinuity.py")
         + ",target=/clock_probe.py,readonly", IMAGE, "/app/.venv/bin/python",
         "/clock_probe.py"],
        capture_output=True,
        text=True,
        timeout=100,
    )
    (receipt / (label + ".json")).write_text(
        json.dumps({"exit_code": result.returncode, "stdout": result.stdout,
                    "stderr": result.stderr}, indent=2), encoding="utf-8"
    )
    result.check_returncode()
    print(label + ": " + result.stdout.strip(), flush=True)


state = {"user_authorized": True, "production_touched": False, "image": IMAGE,
         "settlement_windows": settlement_windows,
         "ubuntu_chrony_controls_clock": False}
state["before"] = mail_service("is-active")
if state["before"]["exit_code"] != 0:
    raise RuntimeError("Expected active mail time-sync service; no change admitted")
sample("mail_timesync_active_before")
try:
    state["stop"] = mail_service("stop")
    if state["stop"]["exit_code"] != 0:
        raise RuntimeError("Time-sync stop failed")
    state["during"] = mail_service("is-active")
    if state["during"]["exit_code"] == 0:
        raise RuntimeError("Time-sync remained active")
    for window in range(settlement_windows):
        sample("mail_timesync_stopped_window_" + str(window + 1))
finally:
    state["restore"] = mail_service("start")
    state["after"] = mail_service("is-active")
    (receipt / "service-transition.json").write_text(
        json.dumps(state, indent=2), encoding="utf-8"
    )
    if state["restore"]["exit_code"] != 0 or state["after"]["exit_code"] != 0:
        raise RuntimeError("Time-sync restoration failed; inspect receipt immediately")
sample("mail_timesync_active_restored")
print(str(receipt), flush=True)
