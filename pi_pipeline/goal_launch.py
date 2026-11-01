"""Hand over from the voice service to one goal session when the person says a goal's start phrase ("G2, ball goal"; goals plan, 2026-10-31).

Like `punt_launch.py`: the session (`python -m pi_pipeline.goals run GOAL`) needs the serial port and the camera to itself, so it runs as a transient systemd unit that stops `g2-voice`
first and ALWAYS starts it again when the session ends, with G2 laid down in the rest pose before that however it ended. Does nothing off a Linux Pi.
"""
from __future__ import annotations

import getpass
import logging
import os
import subprocess
import sys

log = logging.getLogger("g2.goal_launch")

UNIT = "g2-goal"


def command(goal: str, *, python: str | None = None, workdir: str | None = None, user: str | None = None) -> list[str]:
    python = python or sys.executable
    workdir = workdir or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return ["sudo", "-n", "systemd-run", "--no-block", f"--unit={UNIT}", "--collect", f"--uid={user or getpass.getuser()}",
            "-p", f"WorkingDirectory={workdir}", "-p", "KillSignal=SIGINT", "-p", "TimeoutStopSec=30",
            "-p", "ExecStartPre=+/bin/systemctl stop g2-voice",
            "-p", f"ExecStopPost=+/bin/sh -c '{python} -m pi_pipeline.link.check_serial send krest >/dev/null 2>&1; sleep 2; true'",
            "-p", "ExecStopPost=+/bin/systemctl --no-block start g2-voice",
            "-E", "PYTHONUNBUFFERED=1",
            python, "-m", "pi_pipeline.goals", "run", goal]


def launch(goal: str, *, run=None, platform: str | None = None) -> bool:
    """Start one session. True if it was started (the voice service is then stopped by the unit itself)."""
    if (platform or sys.platform) != "linux":
        log.warning("goal hand-over skipped: not a Pi (%s)", platform or sys.platform)
        return False
    run = run or subprocess.run
    try:
        for unit in (UNIT, "g2-punt"):
            if run(["systemctl", "is-active", "--quiet", unit], timeout=10).returncode == 0:
                log.info("%s is already running", unit)
                return False
        run(command(goal), check=True, timeout=30)
        return True
    except Exception:  # noqa: BLE001
        log.exception("could not start the goal session")
        return False
