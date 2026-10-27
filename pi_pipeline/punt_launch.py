"""Hand over from the voice service to one punt attempt when the person says "G2, punt" (user, 2026-10-26).

Like `explore_launch.py`: the attempt (`behavior/ball_chase.py --punts 1`) needs the serial port and the camera to itself, so it runs as a transient systemd unit that stops `g2-voice`
first and ALWAYS starts it again when the attempt ends, with G2 laid down in the rest pose before that however it ended. One attempt: stand up from rest, find the ball, walk to it,
punch it once, rest. The values it uses are read from `~/.local/share/g2/punt_settings.json` at the start of the run (docs/guides/punt.md). Does nothing off a Linux Pi.
"""
from __future__ import annotations

import getpass
import logging
import os
import subprocess
import sys

log = logging.getLogger("g2.punt_launch")

UNIT = "g2-punt"


def command(*, python: str | None = None, workdir: str | None = None, user: str | None = None) -> list[str]:
    python = python or sys.executable
    workdir = workdir or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return ["sudo", "-n", "systemd-run", "--no-block", f"--unit={UNIT}", "--collect", f"--uid={user or getpass.getuser()}",
            "-p", f"WorkingDirectory={workdir}", "-p", "KillSignal=SIGINT", "-p", "TimeoutStopSec=20",
            "-p", "ExecStartPre=+/bin/systemctl stop g2-voice",
            # however the attempt ends (done, a stop, a crash, a kill) lay G2 down in the rest pose before the voice service starts again
            "-p", f"ExecStopPost=+/bin/sh -c '{python} -m pi_pipeline.link.check_serial send krest >/dev/null 2>&1; sleep 2; true'",
            "-p", "ExecStopPost=+/bin/systemctl --no-block start g2-voice",
            "-E", "PYTHONUNBUFFERED=1",
            python, "-m", "pi_pipeline.behavior.ball_chase", "--punts", "1"]


def launch(*, run=None, platform: str | None = None) -> bool:
    """Start one attempt. True if it was started (the voice service is then stopped by the unit itself)."""
    if (platform or sys.platform) != "linux":
        log.warning("punt hand-over skipped: not a Pi (%s)", platform or sys.platform)
        return False
    run = run or subprocess.run
    try:
        if run(["systemctl", "is-active", "--quiet", UNIT], timeout=10).returncode == 0:
            log.info("a punt attempt is already running")
            return False
        run(command(), check=True, timeout=30)
        return True
    except Exception:  # noqa: BLE001
        log.exception("could not start the punt attempt")
        return False
