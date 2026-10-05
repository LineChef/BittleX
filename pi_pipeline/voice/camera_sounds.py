"""Sounds that say the camera is in use, so G2 never looks without you hearing it (2026-10-04).

  * shutter:         a short click-chirp, once for every picture taken (e.g. when you ask what G2 sees).
  * recording:       a rising two-note chirp when continuous camera capture starts (the vision detection feed), repeated as a reminder
                     every `reminder_s` while it runs.
  * recording_stop:  the same two notes falling, when it stops.
All three differ from the acknowledgement tone (one 880 Hz blip), the whistle and the siren. `render()` returns int16 mono PCM;
`play()` plays without blocking, at the alert level by default (a privacy indicator should be noticeable)."""
from __future__ import annotations

import logging
import threading

import numpy as np

log = logging.getLogger("g2.camera_sounds")

DEFAULT_PEAK = 0.045


def _note(freq: float, dur: float, rate: int, attack: float = 0.005, release: float = 0.03, harmonics=(1.0, 0.2)) -> np.ndarray:
    t = np.arange(0, dur, 1.0 / rate)
    y = sum(w * np.sin(2 * np.pi * (k + 1) * freq * t) for k, w in enumerate(harmonics))
    return y * np.minimum(1.0, np.minimum(t / attack, (dur - t) / release))


def render(name: str, rate: int = 48000, peak: float = DEFAULT_PEAK) -> np.ndarray:
    gap = np.zeros(int(0.02 * rate))
    if name == "shutter":                      # a tick, then a short falling chirp: "click-brrp"
        y = np.concatenate([_note(3200, 0.012, rate, 0.001, 0.008, (1.0,)), np.zeros(int(0.012 * rate)),
                            _note(1800, 0.05, rate, 0.003, 0.03, (1.0, 0.3))])
    elif name == "recording":                  # low note then a higher one: rising
        y = np.concatenate([_note(660, 0.09, rate), gap, _note(990, 0.14, rate)])
    elif name == "recording_stop":             # the same two notes, falling
        y = np.concatenate([_note(990, 0.09, rate), gap, _note(660, 0.14, rate)])
    else:
        raise ValueError(f"unknown camera sound {name!r}")
    y = y / np.abs(y).max() * peak
    return (y * 32767).astype(np.int16)


def play(name: str, peak: float = DEFAULT_PEAK, rate: int = 48000, wait: bool = False) -> None:
    """Never raises: a speaker problem is logged and ignored."""
    def _run() -> None:
        try:
            import sounddevice as sd
            sd.play(render(name, rate, peak), rate)
            if wait:
                sd.wait()
        except Exception:  # noqa: BLE001
            log.debug("camera sound %r failed", name, exc_info=True)
    if wait:
        _run()
    else:
        threading.Thread(target=_run, name="camera-sound", daemon=True).start()


class CameraActivityIndicator:
    """Plays `recording` when continuous capture starts, again every `reminder_s` while it runs (0 = no reminders), and
    `recording_stop` when it ends. `play` is injectable for tests."""

    def __init__(self, *, peak: float = DEFAULT_PEAK, reminder_s: float = 60.0, play=None):
        self._peak, self._reminder_s = peak, reminder_s
        self._play = play or (lambda name: play_sound(name, self._peak))
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> "CameraActivityIndicator":
        self._play("recording")
        if self._reminder_s > 0:
            self._thread = threading.Thread(target=self._remind, name="camera-reminder", daemon=True)
            self._thread.start()
        return self

    def _remind(self) -> None:
        while not self._stop.wait(self._reminder_s):
            self._play("recording")

    def stop(self) -> None:
        if self._stop.is_set():
            return
        self._stop.set()
        self._play("recording_stop")


play_sound = play      # the module-level `play`, under a name the class can use without shadowing
