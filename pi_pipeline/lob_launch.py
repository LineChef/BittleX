"""Hand over from the voice service to one lob when the person says "G2, lob" (owner, 2026-11-21).

Like `punt_launch.py`: the lob (`behavior/lob.py`: stand up, pick the object up, lob it, rest) needs the serial port to itself, so it runs as a transient systemd unit that stops `g2-voice`
first and ALWAYS starts it again when it ends, with G2 laid down in the rest position before that however it ended. Does nothing off a Linux Pi.
"""
from __future__ import annotations

import getpass
import logging
import os
import subprocess
import sys

log = logging.getLogger("g2.lob_launch")

UNIT = "g2-lob"


def command(*, python: str | None = None, workdir: str | None = None, user: str | None = None) -> list[str]:
    python = python or sys.executable
    workdir = workdir or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return ["sudo", "-n", "systemd-run", "--no-block", f"--unit={UNIT}", "--collect", f"--uid={user or getpass.getuser()}",
            "-p", f"WorkingDirectory={workdir}", "-p", "KillSignal=SIGINT", "-p", "TimeoutStopSec=20",
            "-p", "ExecStartPre=+/bin/systemctl stop g2-voice",
            # however the lob ends (done, a stop, a crash, a kill) lay G2 down in the rest pose before the voice service starts again
            "-p", f"ExecStopPost=+/bin/sh -c '{python} -m pi_pipeline.link.check_serial send krest >/dev/null 2>&1; sleep 2; true'",
            "-p", "ExecStopPost=+/bin/systemctl --no-block start g2-voice",
            "-E", "PYTHONUNBUFFERED=1",
            python, "-m", "pi_pipeline.behavior.lob"]


def launch(*, run=None, platform: str | None = None) -> bool:
    """Start one lob. True if it was started (the voice service is then stopped by the unit itself)."""
    if (platform or sys.platform) != "linux":
        log.warning("lob hand-over skipped: not a Pi (%s)", platform or sys.platform)
        return False
    run = run or subprocess.run
    try:
        if run(["systemctl", "is-active", "--quiet", UNIT], timeout=10).returncode == 0:
            log.info("a lob is already running")
            return False
        run(command(), check=True, timeout=30)
        return True
    except Exception:  # noqa: BLE001
        log.exception("could not start the lob")
        return False
