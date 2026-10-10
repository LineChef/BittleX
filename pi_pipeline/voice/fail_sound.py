"""The "wrong answer" signal when a command fails (user, 2026-10-10: "any time a command fails play the wrong answer signal so I know it failed").

It is the losing horn (`prompt_tones.play_refuse`), at most once every 8 s so a burst of failures is one horn, and it never raises. `G2_FAIL_SOUND=0` turns it off. Callers: the serial link when a
command cannot be sent, a refused unsafe command, a failed Claude call, a failed picture, a restart or power-off that did not work, and a voice turn that raised."""
from __future__ import annotations

import logging

log = logging.getLogger("g2.fail")


def command_failed(why: str = "") -> None:
    log.warning("command failed: %s", why or "unknown")
    try:
        from . import prompt_tones
        prompt_tones.play_horn_if_enabled("G2_FAIL_SOUND", cooldown_s=8.0)
    except Exception:  # noqa: BLE001 -- the failure signal must never cause a failure
        log.debug("fail sound could not play", exc_info=True)
