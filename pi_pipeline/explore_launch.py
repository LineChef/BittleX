"""Hand over from the voice service to an exploration session (`explore_session.py`) when the person says "go ahead and look around".

The voice service has no behavior runtime, so "explore" cannot be acted on inside it. Instead this starts `explore_session` as a transient systemd
unit that stops `g2-voice` first and ALWAYS starts it again when the session ends (ExecStopPost), however it ends. Does nothing off a Linux Pi.
"""
from __future__ import annotations

import getpass
import logging
import os
import subprocess
import sys

log = logging.getLogger("g2.explore_launch")

UNIT = "g2-explore"
FEATURES = "+vision,+vision_perception,+vision_safety,+explore,-avoidance_act,-object_gallery"


def command(roam_s: float = 600.0, *, python: str | None = None, workdir: str | None = None, user: str | None = None) -> list[str]:
    python = python or sys.executable
    workdir = workdir or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return ["sudo", "-n", "systemd-run", "--no-block", f"--unit={UNIT}", "--collect", f"--uid={user or getpass.getuser()}",
            "-p", f"WorkingDirectory={workdir}", "-p", "KillSignal=SIGTERM", "-p", "TimeoutStopSec=15",
            "-p", "ExecStartPre=+/bin/systemctl stop g2-voice",
            "-p", "ExecStopPost=+/bin/systemctl --no-block start g2-voice",
            "-E", f"G2_FEATURES={FEATURES}", "-E", "G2_LOG_HEARD=1",
            python, "-m", "pi_pipeline.explore_session", "--arm-on-start", "--exit-when-roam-ends", "--roam-s", str(int(roam_s))]


def launch(roam_s: float = 600.0, *, run=None, platform: str | None = None) -> bool:
    """Start the session. True if it was started (the voice service is then stopped by the unit itself)."""
    if (platform or sys.platform) != "linux":
        log.warning("exploration hand-over skipped: not a Pi (%s)", platform or sys.platform)
        return False
    run = run or subprocess.run
    try:
        active = run(["systemctl", "is-active", "--quiet", UNIT], timeout=10).returncode == 0
        if active:
            log.info("an exploration session is already running")
            return False
        run(command(roam_s), check=True, timeout=30)
        return True
    except Exception:  # noqa: BLE001
        log.exception("could not start the exploration session")
        return False
