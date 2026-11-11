"""One auto-log sidecar per scripted firmware gait (owner, 2026-11-10): every `kwkF` / `kwkL` / `kwkR` / `kbkF` G2 is told to play gets a run tagged `kind: scripted_walk`
(token, start and end time, the command that ended it, floor, hardware epoch, commit), next to the learned walks' `policy_walk` runs in `~/g2_runs/auto/<date>/`. The two stay separate:
a scripted walk has no CSV, so the ingest quarantines it as `nolog` and no body or timing fit ever reads it.

The one place is `SerialLink.send`, so it covers every mode (ball goal, exploration, voice service, scripts). A gait runs until the next motion command, so that command ends the run.
It never raises and never blocks a send; `G2_AUTOLOG=off` (autolog.enabled) turns it off.
"""
from __future__ import annotations

import logging

log = logging.getLogger(__name__)

_GAITS = ("kwkF", "kwkL", "kwkR", "kbkF")


def is_gait(command: str) -> bool:
    return command.strip() in _GAITS


class ScriptedWalkLog:
    """Tracks the running scripted gait on one link. `note(command)` is called with every command after it is sent."""

    def __init__(self, new_run=None):
        self._new_run = new_run
        self._run = None
        self._token = None

    def _open(self, token: str) -> None:
        try:
            new_run = self._new_run
            if new_run is None:
                from . import autolog
                new_run = autolog.new_run
            self._run = new_run("scripted_walk", extra={"token": token})
            self._token = token
        except Exception:  # noqa: BLE001
            self._run = None
            log.debug("scripted-walk log could not start", exc_info=True)

    def _close(self, reason: str) -> None:
        run, token = self._run, self._token
        self._run = self._token = None
        if run is None:
            return
        try:
            run.finish(reason, token=token)
        except Exception:  # noqa: BLE001
            log.debug("scripted-walk log could not finish", exc_info=True)

    def note(self, command: str) -> None:
        """A gait token opens a run (ending a running one); any other motion command (`k...`, `d`) ends it, named by that command."""
        try:
            c = (command or "").strip()
            if not c:
                return
            if is_gait(c):
                if self._run is not None:
                    self._close(f"next:{c}")
                self._open(c)
            elif self._run is not None and c[:1] in ("k", "d"):
                self._close(f"ended_by:{c}")
        except Exception:  # noqa: BLE001
            pass

    def close(self, reason: str = "link_closed") -> None:
        if self._run is not None:
            self._close(reason)
