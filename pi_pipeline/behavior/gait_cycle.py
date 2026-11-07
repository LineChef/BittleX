"""How long one cycle of a firmware gait takes (kwkL, kwkR, kwkF, kbkF), for the whole-cycle stop (ball_chase.CYCLE_STOP).

Why (2026-11-06 firmware reading, docs/research/falls-at-transitions-outside-sources-2026-11-06.md): a skill switch loads the new skill's first frame and moves there in one fast eased
jump. A stop (`kbalance`) out of a stride therefore jumps from a mid-stride pose to the balance pose. Stopped after a whole number of cycles the legs are back near where the gait started,
so the jump is smaller. The frame time is not in the skill data (116 frames for wkL, 43 for the arm's wkArmL), so the period is measured from the roll / pitch oscillation:

    python -m pi_pipeline.behavior.transition_drill --measure      # on the Pi, G2 standing on the floor: each gait for 4 s, writes ~/.local/share/g2/gait_cycles.json

`period_for(token, stamps, samples)` uses, in order: `G2_GAIT_CYCLE_S` (one number for every gait, an override), the measured file, then an estimate from the current move's own IMU frames.
"""
from __future__ import annotations

import json
import os
import time

CYCLES_PATH = "~/.local/share/g2/gait_cycles.json"
MIN_PERIOD_S, MAX_PERIOD_S = 0.25, 2.0
MIN_STRENGTH = 0.30            # the autocorrelation peak must be at least this (1.0 = a perfect repeat); below it there is no cycle to trust


def cycles_path() -> str:
    return os.path.expanduser(os.environ.get("G2_GAIT_CYCLES", CYCLES_PATH))


def _resample(stamps, values, hz: float):
    """Evenly spaced samples (linear interpolation) so the autocorrelation lag is a time."""
    if len(stamps) < 8:
        return []
    t0, t1 = stamps[0], stamps[-1]
    if t1 - t0 < 1.0:
        return []
    n = int((t1 - t0) * hz)
    out, j = [], 0
    for i in range(n):
        t = t0 + i / hz
        while j + 1 < len(stamps) - 1 and stamps[j + 1] < t:
            j += 1
        a, b = stamps[j], stamps[j + 1]
        f = 0.0 if b <= a else min(1.0, max(0.0, (t - a) / (b - a)))
        out.append(values[j] + (values[j + 1] - values[j]) * f)
    return out


def _autocorr_period(x, hz: float):
    """(period s, strength) of the strongest repeat in `x`, or None."""
    if len(x) < int(2.2 * MIN_PERIOD_S * hz) + 4:
        return None
    mean = sum(x) / len(x)
    x = [v - mean for v in x]
    den = sum(v * v for v in x)
    if den < 1e-6:
        return None
    lo, hi = int(MIN_PERIOD_S * hz), min(int(MAX_PERIOD_S * hz), len(x) // 2)
    if hi <= lo + 2:
        return None
    ac = []
    for lag in range(lo - 1, hi + 2):
        ac.append(sum(x[i] * x[i + lag] for i in range(len(x) - lag)) / den * len(x) / max(1, len(x) - lag))
    best = None
    for k in range(1, len(ac) - 1):                                 # local maxima only: the first strong one is the period (a longer lag is a multiple of it)
        if ac[k] >= ac[k - 1] and ac[k] > ac[k + 1] and ac[k] >= MIN_STRENGTH:
            best = (k + lo - 1, ac[k])
            break
    if best is None:
        return None
    lag, strength = best
    return lag / hz, strength


def estimate(stamps, rolls, pitches, hz: float = 50.0):
    """(period s, strength) from an IMU recording of a gait, or None. Roll and pitch are tried; the stronger repeat wins."""
    found = []
    for vals in (rolls, pitches):
        n = min(len(stamps), len(vals))
        r = _autocorr_period(_resample(list(stamps[-n:]), list(vals[-n:]), hz), hz)
        if r:
            found.append(r)
    return max(found, key=lambda r: r[1]) if found else None


def load() -> dict:
    try:
        return json.load(open(cycles_path()))
    except (OSError, ValueError):
        return {}


def save(token: str, period_s: float, strength: float, n: int) -> None:
    d = load()
    d[token] = {"period_s": round(period_s, 3), "strength": round(strength, 2), "samples": n, "at": time.strftime("%Y-%m-%d %H:%M:%S")}
    p = cycles_path()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w") as f:
        json.dump(d, f, indent=1)


def period_for(token: str, stamps=(), rolls=(), pitches=()):
    """(period s, where it came from) for a gait, or (None, why not). The override, then the measured file, then this move's own IMU frames."""
    v = os.environ.get("G2_GAIT_CYCLE_S", "").strip()
    if v:
        try:
            p = float(v)
            if MIN_PERIOD_S <= p <= MAX_PERIOD_S:
                return p, "G2_GAIT_CYCLE_S"
        except ValueError:
            pass
    row = load().get(token)
    if row and MIN_PERIOD_S <= float(row.get("period_s", 0)) <= MAX_PERIOD_S:
        return float(row["period_s"]), "measured"
    est = estimate(stamps, rolls, pitches)
    if est:
        return est[0], f"estimated from this move (strength {est[1]:.2f})"
    return None, "no cycle found"


def stop_after(ran_s: float, period_s: float, max_extra_s: float):
    """Seconds still to wait so that the move ends on a whole number of cycles (at least one), or None when that is more than `max_extra_s` away."""
    cycles = max(1, int(ran_s / period_s + 0.999))
    extra = cycles * period_s - ran_s
    if extra < 0.03:
        return 0.0
    return extra if extra <= max_extra_s else None
