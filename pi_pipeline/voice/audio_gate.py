"""One sound at a time: speech and sound effects wait for each other instead of cutting each other off (user, 2026-10-10: "make sure he doesn't talk while other sounds are playing,
or he waits for them to finish before talking").

Every sound on G2 (speech, chirps, the oof, the turn-away sound, horns, the shutter) plays through `sounddevice.play`, and `play` STOPS whatever is already playing. So a sound that started
mid-sentence cut the sentence off. `install()` wraps `sounddevice.play` once per process: a new sound waits (polling, never holding the audio) until the one playing has finished, up to `max_wait_s`
(default 4 s, so a safety sound such as the turn-away or the oof is never delayed by more than that, then it cuts in as before). Calls from different threads are queued behind one lock in arrival
order. `G2_AUDIO_GATE=0` turns it off. Never raises: if sounddevice is missing the gate is simply not installed.
"""
from __future__ import annotations

import logging
import os
import threading
import time

log = logging.getLogger("g2.audio_gate")

_LOCK = threading.Lock()
_beep_until = 0.0                                    # the BiBoard's own buzzer is not on sounddevice: the link tells the gate when a beep it sent should be over
MAX_WAIT_S = 4.0
POLL_S = 0.02


def _is_playing(sd) -> bool:
    try:
        stream = sd.get_stream()
    except Exception:  # noqa: BLE001 -- nothing has played yet
        return False
    try:
        return bool(stream.active)
    except Exception:  # noqa: BLE001
        return False


def note_beep(seconds: float) -> None:
    """A beep was just sent to the BiBoard buzzer; speech waits for `seconds` (the link computes it from the notes)."""
    global _beep_until
    _beep_until = max(_beep_until, time.monotonic() + max(0.0, seconds))


def beep_seconds(command: str) -> float:
    """How long a `b<note> <dur> ...` command plays: each pair lasts 1/duration seconds (opencat.beep). 0 for anything else."""
    try:
        nums = [int(x) for x in command[1:].split()]
    except ValueError:
        return 0.0
    return sum(1.0 / d for d in nums[1::2] if d > 0)


def is_busy(sd=None) -> bool:
    """True while speech or a sound is playing or a beep is sounding (non-blocking). False when the gate is off."""
    if os.environ.get("G2_AUDIO_GATE", "1") == "0":
        return False
    if sd is None:
        try:
            import sounddevice as sd  # type: ignore
        except Exception:  # noqa: BLE001
            sd = None
    return (sd is not None and _is_playing(sd)) or time.monotonic() < _beep_until


def wait_idle(max_wait_s: float = 2.0, sd=None) -> bool:
    """Block (at most `max_wait_s`) until no speech or sound is playing and no beep is sounding. Returns True if idle at the end. Never raises."""
    if os.environ.get("G2_AUDIO_GATE", "1") == "0":
        return True
    if sd is None:
        try:
            import sounddevice as sd  # type: ignore
        except Exception:  # noqa: BLE001
            sd = None
    t0 = time.monotonic()
    while time.monotonic() - t0 < max_wait_s:
        if not ((sd is not None and _is_playing(sd)) or time.monotonic() < _beep_until):
            return True
        time.sleep(POLL_S)
    return False


def install(max_wait_s: float = MAX_WAIT_S, sd=None) -> bool:
    """Wrap `sounddevice.play` so a new sound waits for the one playing. Returns True when installed (or already installed)."""
    if os.environ.get("G2_AUDIO_GATE", "1") == "0":
        return False
    if sd is None:
        try:
            import sounddevice as sd  # type: ignore
        except Exception:  # noqa: BLE001
            return False
    if getattr(sd, "_g2_gate", False):
        return True
    original = sd.play

    def play(*args, **kwargs):
        with _LOCK:                                              # sounds start in arrival order; the next one waits here, not in the audio
            t0 = time.monotonic()
            waited = False
            while (_is_playing(sd) or time.monotonic() < _beep_until) and time.monotonic() - t0 < max_wait_s:
                waited = True
                time.sleep(POLL_S)
            if waited:
                log.debug("a sound waited %.2f s for the one playing", time.monotonic() - t0)
            return original(*args, **kwargs)

    sd.play = play
    sd._g2_gate = True
    return True
