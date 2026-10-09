"""prompt_tones -- the three sounds that tell you where G2 is in a spoken exchange (user, 2026-10-09):

  beep   right after the wake word: he is listening (one short, bright note)
  boop   when he thinks you have finished speaking and has your words (one lower, rounder note that sags a little)
  close  when the follow-up window ends and he has stopped listening (two soft falling notes)

Plain numpy tones in the same family as `wake_chime`; `render_*()` return int16 mono PCM, `play_*()` play without blocking and never raise (a speaker problem is logged)."""
from __future__ import annotations

import logging
import threading

import numpy as np

from .star_trek_whistle import DEFAULT_PEAK

log = logging.getLogger("g2.prompt_tones")

BELL = (1.0, 0.25, 0.08)            # fundamental and two overtones: a soft bell-like timbre


def _note(f0: float, dur: float, rate: int, f1: float | None = None, decay: float = 12.0, overtones=BELL) -> np.ndarray:
    t = np.arange(0, dur, 1.0 / rate)
    f = f0 if f1 is None else np.linspace(f0, f1, t.size)                 # f1 = a glide from f0 to f1
    phase = 2 * np.pi * np.cumsum(f * np.ones_like(t)) / rate
    y = sum(w * np.sin((k + 1) * phase) for k, w in enumerate(overtones))
    return y * np.minimum(1.0, t / 0.006) * np.exp(-t * decay)             # 6 ms attack, then a decay


def _finish(parts, peak: float) -> np.ndarray:
    y = np.concatenate(parts)
    y = y / np.abs(y).max() * peak
    return (y * 32767).astype(np.int16)


def render_beep(rate: int = 48000, peak: float = DEFAULT_PEAK) -> np.ndarray:
    """One short bright note (C6, about 0.12 s): "I'm listening"."""
    return _finish([_note(1046.5, 0.12, rate, decay=14.0)], peak)


def render_boop(rate: int = 48000, peak: float = DEFAULT_PEAK) -> np.ndarray:
    """One lower, rounder note that sags (G4 to E4, about 0.2 s): "got it, you've finished"."""
    return _finish([_note(392.0, 0.2, rate, f1=329.6, decay=7.0, overtones=(1.0, 0.12))], peak)


def render_close(rate: int = 48000, peak: float = DEFAULT_PEAK) -> np.ndarray:
    """Two soft falling notes (C5 then F4, about 0.4 s): "I've stopped listening"."""
    gap = np.zeros(int(rate * 0.04))
    return _finish([_note(523.3, 0.18, rate, decay=9.0), gap, _note(349.2, 0.22, rate, decay=8.0)], peak)


def _play(pcm_fn, peak: float, rate: int, wait: bool) -> None:
    def _run() -> None:
        try:
            import sounddevice as sd
            sd.play(pcm_fn(rate, peak), rate)
            if wait:
                sd.wait()
        except Exception:  # noqa: BLE001
            log.debug("prompt tone failed", exc_info=True)
    if wait:
        _run()
    else:
        threading.Thread(target=_run, daemon=True).start()


def play_beep(peak: float = DEFAULT_PEAK, rate: int = 48000, wait: bool = False) -> None:
    _play(render_beep, peak, rate, wait)


def play_boop(peak: float = DEFAULT_PEAK, rate: int = 48000, wait: bool = False) -> None:
    _play(render_boop, peak, rate, wait)


def play_close(peak: float = DEFAULT_PEAK, rate: int = 48000, wait: bool = False) -> None:
    _play(render_close, peak, rate, wait)
