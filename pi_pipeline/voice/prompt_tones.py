"""prompt_tones -- the three sounds that tell you where G2 is in a spoken exchange (user, 2026-10-09):

  beep   right after the wake word: he is listening (one short, bright note)
  boop   when he thinks you have finished speaking and has your words (one lower, rounder note that sags a little)
  close  when the follow-up window ends and he has stopped listening (two soft falling notes)

Plain numpy tones in the same family as `wake_chime`; `render_*()` return int16 mono PCM, `play_*()` play without blocking and never raise (a speaker problem is logged)."""
from __future__ import annotations

import logging
import os
import time
import threading

import numpy as np

from .ack_whistle import DEFAULT_PEAK

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


def _lowpass(x: np.ndarray, n: int) -> np.ndarray:
    return np.convolve(x, np.ones(n) / n, mode="same")


def _voiced(f0: float, f1: float, dur: float, rate: int, attack: float, decay: float, harmonics: int = 9, breath: float = 0.0, seed: int = 1) -> np.ndarray:
    """A sagging buzzy voice: a pitch glide f0 -> f1 with 1/n harmonics, a little low-passed noise ("breath") and a fast attack."""
    t = np.arange(0, dur, 1.0 / rate)
    f = np.linspace(f0, f1, t.size)
    ph = 2 * np.pi * np.cumsum(f) / rate
    y = sum(np.sin(k * ph) / k for k in range(1, harmonics + 1))
    if breath:
        noise = _lowpass(np.random.default_rng(seed).standard_normal(t.size), 40)
        y = y + breath * noise / (np.abs(noise).max() or 1.0) * np.abs(y).max()
    return y * np.minimum(1.0, t / attack) * np.exp(-t * decay)


def render_grunt(rate: int = 48000, peak: float = DEFAULT_PEAK) -> np.ndarray:
    """A low, gravelly "hmph" (about 0.35 s): G2 does not like something. Two quick falling pulses, the second shorter and lower."""
    a = _voiced(120.0, 78.0, 0.20, rate, attack=0.01, decay=7.0, breath=0.35, seed=1)
    b = _voiced(100.0, 62.0, 0.14, rate, attack=0.01, decay=9.0, breath=0.35, seed=2)
    return _finish([a, np.zeros(int(rate * 0.04)), b], peak)


# The "losing horn" (user, 2026-10-10), rebuilt from the pitch and loudness measured off a laptop-microphone recording of "The Price is Right Losing
# Horn" (6 s clip). Five pieces: (start s, end s, Hz at start, Hz at end, loudness at start, loudness at end). The laptop's small speaker (like G2's)
# does not reproduce low fundamentals, so these are the frequencies that were actually audible, probably a few overtones above the horn's true low notes.
HORN = [
    (0.00, 0.26, 128, 128, 1.00, 0.12),
    (0.30, 0.52, 143, 141, 0.70, 0.11),
    (0.62, 0.78, 125, 122, 0.85, 0.28),
    (0.80, 1.50, 96, 96, 1.00, 0.30),
    (1.50, 3.74, 283, 208, 0.95, 0.10),        # the long last note: holds near 283 Hz for 1.3 s, then sags in steps to 208
]
HORN_LAST_BREAKS = [(1.50, 283), (2.00, 283), (2.50, 268), (2.80, 258), (3.10, 240), (3.30, 221), (3.60, 214), (3.74, 208)]


def render_refuse(rate: int = 48000, peak: float = DEFAULT_PEAK) -> np.ndarray:
    """The "losing horn" (about 3.7 s): G2 refuses. Four short falling-loudness muted-brass notes, then a long last note that holds and sags in pitch.
    Built from the measured contour in `HORN`."""
    out = np.zeros(int(rate * HORN[-1][1]) + 1)
    for i, (t0, t1, f0, f1, a0, a1) in enumerate(HORN):
        t = np.arange(0, t1 - t0, 1.0 / rate)
        u = t / (t1 - t0)
        if i == len(HORN) - 1:
            f = np.interp(t + t0, [b[0] for b in HORN_LAST_BREAKS], [b[1] for b in HORN_LAST_BREAKS])
            f = f * (1.0 + 0.006 * np.sin(2 * np.pi * 5.5 * t) * np.minimum(1.0, t / 0.4))      # a slight wobble
        else:
            f = f0 + (f1 - f0) * u
        ph = 2 * np.pi * np.cumsum(f) / rate
        y = sum(np.sin(k * ph) / k ** 0.9 for k in range(1, 9))
        env = (a0 + (a1 - a0) * u) * np.minimum(1.0, t / 0.015) * np.minimum(1.0, (t1 - t0 - t) / 0.03)
        y = _lowpass(y, 4) * env                                     # a mute takes the top off the brass
        n0 = int(t0 * rate)
        out[n0:n0 + y.size] += y[: out.size - n0]
    return _finish([out], peak)


# The exploration-complete sting (user, 2026-10-10): a "ta-da" rebuilt from the notes, timing and loudness measured off a laptop-microphone recording of a stock
# "Ta-Da" sound effect (about 1.25 s per play): a bright stab, then the same chord held and fading. The chord, measured: E4, C5, E5, G5, C6 (a C major chord).
CHORD_HZ = (329.6, 523.3, 659.3, 784.0, 1046.5)
CHORD_WEIGHT = (0.8, 1.0, 1.0, 0.7, 0.6)


def render_hit(rate: int = 48000, peak: float = DEFAULT_PEAK) -> np.ndarray:
    """A long winded "ooooof" (about 1.0 s) when G2 walks into a wall: a low thump of impact, then a breathy vowel that falls in pitch and fades slowly. At 200% of the usual level."""
    n = int(rate * 0.07)
    thump = _lowpass(np.random.default_rng(11).standard_normal(n), 60)
    thump = thump / (np.abs(thump).max() or 1.0) * np.exp(-np.arange(n) / (rate * 0.018))
    vowel = _voiced(230.0, 90.0, 0.95, rate, attack=0.04, decay=3.2, harmonics=6, breath=0.5, seed=12)
    vowel = vowel / (np.abs(vowel).max() or 1.0)
    out = np.concatenate([thump * 1.1 + vowel[:n] * 0.0, vowel])
    return _finish([out], peak * 2.0)


def play_hit(peak: float = DEFAULT_PEAK, rate: int = 48000, wait: bool = False) -> None:
    _play(render_hit, peak, rate, wait)


def render_turn_away(rate: int = 48000, peak: float = DEFAULT_PEAK) -> np.ndarray:
    """A two-note fall (about 0.35 s, at 200% of the usual level: 70%, then 150%, were not heard over the walking noise, 2026-10-10) when G2 turns away from a wall: so you can tell why he is turning (user, 2026-10-10)."""
    gap = np.zeros(int(rate * 0.03))
    return _finish([_note(659.3, 0.14, rate, f1=587.3, decay=10.0), gap, _note(493.9, 0.18, rate, f1=415.3, decay=9.0)], peak * 2.0)


def play_turn_away(peak: float = DEFAULT_PEAK, rate: int = 48000, wait: bool = False) -> None:
    _play(render_turn_away, peak, rate, wait)


def render_complete(rate: int = 48000, peak: float = DEFAULT_PEAK) -> np.ndarray:
    """A "ta-da" (about 1.3 s) for a finished exploration: a short bright chord stab, then the chord held and fading."""
    def chord(dur, attack, release, bright):
        y = sum(w * _brass(f, dur, rate, attack=attack, release=release) for f, w in zip(CHORD_HZ, CHORD_WEIGHT))
        t = np.arange(y.size) / rate
        sparkle = sum(np.sin(2 * np.pi * f * t) for f in (2100.0, 3150.0)) * np.exp(-t / 0.06) * bright      # the bright attack seen at 2.1 and 3.1 kHz
        return y + sparkle
    stab = chord(0.22, 0.008, 0.03, 0.9)
    held = chord(1.05, 0.012, 0.45, 0.35)
    held = held * np.exp(-np.arange(held.size) / rate / 1.4)
    return _finish([stab, held], peak * COMPLETE_GAIN)


START_HORN_GAIN = 1.5           # 50% louder than the other speaker sounds (user, 2026-10-10: first 25%, then 50%)
COMPLETE_GAIN = 1.5             # the same for the ta-da


def render_start_horn(rate: int = 48000, peak: float = DEFAULT_PEAK) -> np.ndarray:
    """The "Viking horn" that starts an exploration, played right after "Exploration mode." (user, 2026-10-10). Two notes, rebuilt from two laptop-microphone
    recordings of the clip (the same timing and pitches both times): a short lower note at 206 Hz (0.06 to 0.33 s, rising a little, a rich nasal spectrum with the
    2nd to 4th harmonics stronger than the note), then at once a long higher note at 302.5 Hz (a fifth up; the 2nd harmonic about 0.6 of it, little above) that holds at
    full level to 1.4 s, drifts down, and fades out to silence at 2.65 s."""
    dur = 2.65
    t = np.arange(0, dur, 1.0 / rate)
    # note 1: 0.06 to 0.33 s
    f1 = 205.8 + 9.0 * np.clip((t - 0.06) / 0.27, 0, 1)
    p1 = 2 * np.pi * np.cumsum(f1) / rate
    n1 = sum(w * np.sin(k * p1) for k, w in zip(range(1, 7), (1.0, 1.73, 2.11, 1.07, 0.37, 0.09)))
    e1 = np.interp(t, [0.06, 0.12, 0.20, 0.30, 0.33, 0.35], [0.0, 0.55, 0.92, 0.80, 0.55, 0.0])
    n1 = n1 / 3.2 * e1
    # note 2: from 0.33 s
    f2 = np.where(t < 0.33, 293.0, 302.5 - 9.5 * np.exp(-(t - 0.33) / 0.04))
    p2 = 2 * np.pi * np.cumsum(f2) / rate
    n2 = np.sin(p2) + 0.58 * np.sin(2 * p2) + 0.11 * np.sin(3 * p2) + 0.04 * np.sin(4 * p2) + 0.05 * np.sin(5 * p2)
    e2 = np.interp(t, [0.0, 0.33, 0.37, 0.50, 1.40, 1.80, 2.10, 2.65], [0.0, 0.0, 0.85, 1.0, 1.0, 0.82, 0.55, 0.0])
    n2 = n2 / 1.6 * e2
    return _finish([n1 + n2], peak * START_HORN_GAIN)


START_HORN_DELAY_S = 1.0        # a pause after "Exploration mode." before the horn (user, 2026-10-10: it was too close to the end of the words)


def render_start_sequence(rate: int = 48000, peak: float = DEFAULT_PEAK) -> np.ndarray:
    """One second of silence, then the Viking horn."""
    return np.concatenate([np.zeros(int(rate * START_HORN_DELAY_S), dtype=np.int16), render_start_horn(rate, peak)])


def play_start_horn(peak: float = DEFAULT_PEAK, rate: int = 48000, wait: bool = False) -> None:
    """The sound that starts an exploration: a 1 s pause, then the Viking horn (it replaces the fanfare)."""
    _play(render_start_sequence, peak, rate, wait)


def play_complete(peak: float = DEFAULT_PEAK, rate: int = 48000, wait: bool = False) -> None:
    _play(render_complete, peak, rate, wait)


def render_oof(rate: int = 48000, peak: float = DEFAULT_PEAK) -> np.ndarray:
    """A winded "ooof" (about 0.5 s): a low thump of impact, then a breathy vowel that falls in pitch and fades."""
    n = int(rate * 0.06)
    thump = _lowpass(np.random.default_rng(3).standard_normal(n), 60)
    thump = thump / (np.abs(thump).max() or 1.0) * np.exp(-np.arange(n) / (rate * 0.015))
    vowel = _voiced(210.0, 105.0, 0.44, rate, attack=0.03, decay=5.5, harmonics=6, breath=0.45, seed=4)
    return _finish([thump * 1.2 + vowel[:n] * 0.0, vowel], peak)


def render_sigh(rate: int = 48000, peak: float = DEFAULT_PEAK) -> np.ndarray:
    """A long breathy sigh going to sleep (about 1.3 s): soft noise that swells and fades, with a faint falling hum under it."""
    dur = 1.3
    t = np.arange(0, dur, 1.0 / rate)
    breath = _lowpass(np.random.default_rng(5).standard_normal(t.size), 28)
    breath = breath / (np.abs(breath).max() or 1.0)
    env = np.sin(np.pi * np.clip(t / dur, 0, 1)) ** 1.5 * np.exp(-t * 0.8)
    hum = _voiced(170.0, 105.0, dur, rate, attack=0.25, decay=1.6, harmonics=4)
    hum = hum / (np.abs(hum).max() or 1.0)
    return _finish([breath * env + 0.35 * hum * env], peak)


def render_yawn(rate: int = 48000, peak: float = DEFAULT_PEAK) -> np.ndarray:
    """A yawn waking up (about 1.4 s): a voiced "aaah" that rises, holds, then falls and trails off into breath."""
    dur = 1.4
    t = np.arange(0, dur, 1.0 / rate)
    u = t / dur
    f = 140.0 + 130.0 * np.sin(np.pi * np.clip(u / 0.7, 0, 1)) ** 1.2 * (u < 0.7) + (u >= 0.7) * (140.0 - 30.0 * (u - 0.7) / 0.3)
    ph = 2 * np.pi * np.cumsum(f) / rate
    bright = 0.3 + 0.7 * np.sin(np.pi * np.clip(u, 0, 1))          # the mouth opens then closes: more upper harmonics in the middle
    y = sum(np.sin(k * ph) / k * (bright if k > 2 else 1.0) for k in range(1, 9))
    breath = _lowpass(np.random.default_rng(6).standard_normal(t.size), 30)
    y = y / (np.abs(y).max() or 1.0) + 0.3 * breath / (np.abs(breath).max() or 1.0)
    env = np.minimum(1.0, t / 0.12) * np.minimum(1.0, (dur - t) / 0.45)
    return _finish([y * env], peak)


def play_beep(peak: float = DEFAULT_PEAK, rate: int = 48000, wait: bool = False) -> None:
    _play(render_beep, peak, rate, wait)


def play_boop(peak: float = DEFAULT_PEAK, rate: int = 48000, wait: bool = False) -> None:
    _play(render_boop, peak, rate, wait)


def play_close(peak: float = DEFAULT_PEAK, rate: int = 48000, wait: bool = False) -> None:
    _play(render_close, peak, rate, wait)


def play_double(peak: float = DEFAULT_PEAK, rate: int = 48000, wait: bool = False) -> None:
    _play(render_double, peak, rate, wait)


def play_grunt(peak: float = DEFAULT_PEAK, rate: int = 48000, wait: bool = False) -> None:
    _play(render_grunt, peak, rate, wait)


def play_refuse(peak: float = DEFAULT_PEAK, rate: int = 48000, wait: bool = False) -> None:
    _play(render_refuse, peak, rate, wait)


_HORN_LAST: dict[str, float] = {}


def play_horn_if_enabled(env_var: str, wait: bool = False, cooldown_s: float = 20.0) -> None:
    """The losing horn for one situation, unless that situation's switch (`G2_REFUSE_SOUND`, `G2_FALL_HORN`) is set to 0. The same situation does not
    play it twice within `cooldown_s` (a fall seen by both the walk loop and the stand guard sounds once)."""
    if os.environ.get(env_var, "1") == "0":
        return
    now = time.monotonic()
    if now - _HORN_LAST.get(env_var, -1e9) < cooldown_s:
        return
    _HORN_LAST[env_var] = now
    play_refuse(wait=wait)


def play_oof(peak: float = DEFAULT_PEAK, rate: int = 48000, wait: bool = False) -> None:
    _play(render_oof, peak, rate, wait)


def play_sigh(peak: float = DEFAULT_PEAK, rate: int = 48000, wait: bool = False) -> None:
    _play(render_sigh, peak, rate, wait)


def play_yawn(peak: float = DEFAULT_PEAK, rate: int = 48000, wait: bool = False) -> None:
    _play(render_yawn, peak, rate, wait)


if __name__ == "__main__":          # audition on the Pi:  python -m pi_pipeline.voice.prompt_tones grunt|oof|beep|boop|close|double|horn
    import sys
    name = sys.argv[1] if len(sys.argv) > 1 else "grunt"
    fn = globals().get(f"play_{name}")
    if fn is None:
        raise SystemExit("sounds: grunt refuse complete turn_away hit oof sigh yawn beep boop close double")
    fn(wait=True)
