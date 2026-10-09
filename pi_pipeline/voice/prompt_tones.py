"""prompt_tones -- the three sounds that tell you where G2 is in a spoken exchange (user, 2026-10-09):

  beep   right after the wake word: he is listening (one short, bright note)
  boop   when he thinks you have finished speaking and has your words (one lower, rounder note that sags a little)
  close  when the follow-up window ends and he has stopped listening (two soft falling notes)

Plain numpy tones in the same family as `wake_chime`; `render_*()` return int16 mono PCM, `play_*()` play without blocking and never raise (a speaker problem is logged)."""
from __future__ import annotations

import logging
import os
import threading

import numpy as np

from .star_trek_whistle import DEFAULT_PEAK

log = logging.getLogger("g2.prompt_tones")

def speaker_enabled() -> bool:
    """Speaker sounds play on the Pi (Linux) by default and never on a dev machine unless `G2_SPEAKER_SOUNDS=1`; `0` silences them everywhere (the tests set it)."""
    import sys
    v = os.environ.get("G2_SPEAKER_SOUNDS")
    return (v == "1") if v is not None else sys.platform.startswith("linux")


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


def render_double(rate: int = 48000, peak: float = DEFAULT_PEAK) -> np.ndarray:
    """A short double beep (two identical C6 notes, about 0.3 s): "I'm switching gait"."""
    gap = np.zeros(int(rate * 0.07))
    return _finish([_note(1046.5, 0.08, rate, decay=16.0), gap, _note(1046.5, 0.08, rate, decay=16.0)], peak)


def render_close(rate: int = 48000, peak: float = DEFAULT_PEAK) -> np.ndarray:
    """Two soft falling notes (C5 then F4, about 0.4 s): "I've stopped listening"."""
    gap = np.zeros(int(rate * 0.04))
    return _finish([_note(523.3, 0.18, rate, decay=9.0), gap, _note(349.2, 0.22, rate, decay=8.0)], peak)


def _brass(f0: float, dur: float, rate: int, attack: float = 0.03, release: float = 0.06, scoop: float = 0.0, vibrato: float = 0.0) -> np.ndarray:
    """A trumpet-like note: a harmonic series falling off as 1/n (the bright, buzzy brass spectrum), a quick attack that starts a hair flat, a sustained body and a short release;
    `vibrato` (Hz-fraction depth) wobbles the long notes."""
    t = np.arange(0, dur, 1.0 / rate)
    f = f0 * (1.0 - scoop * np.exp(-t / 0.03))                     # the note slides up into pitch over the first ~30 ms
    if vibrato:
        f = f * (1.0 + vibrato * np.sin(2 * np.pi * 5.5 * t) * np.minimum(1.0, t / 0.25))
    phase = 2 * np.pi * np.cumsum(f) / rate
    y = sum(np.sin(k * phase) / k ** 0.9 for k in range(1, 9))
    env = np.minimum(1.0, t / attack) * np.minimum(1.0, (dur - t) / release)
    return y * env


def render_fanfare(rate: int = 48000, peak: float = DEFAULT_PEAK) -> np.ndarray:
    """"ba nun na NAAA!": C5 E5 G5 short, then a long held C6 with a little vibrato (a rising brass arpeggio, about 1.4 s)."""
    gap = np.zeros(int(rate * 0.025))
    parts = [_brass(523.3, 0.11, rate, scoop=0.02), gap, _brass(659.3, 0.15, rate, scoop=0.02), gap,
             _brass(784.0, 0.11, rate, scoop=0.02), gap, _brass(1046.5, 0.75, rate, attack=0.04, release=0.18, scoop=0.03, vibrato=0.006)]
    return _finish(parts, peak)


def _play(pcm_fn, peak: float, rate: int, wait: bool) -> None:
    if not speaker_enabled():
        return
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


def play_fanfare(peak: float = DEFAULT_PEAK, rate: int = 48000, wait: bool = False) -> None:
    _play(render_fanfare, peak, rate, wait)


def play_double(peak: float = DEFAULT_PEAK, rate: int = 48000, wait: bool = False) -> None:
    _play(render_double, peak, rate, wait)
