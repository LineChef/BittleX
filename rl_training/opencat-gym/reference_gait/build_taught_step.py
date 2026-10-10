"""Build a walking reference (like wkf_ref.npy) from ONE leg the user taught by hand (pi_pipeline/gait/teach.py).

    python build_taught_step.py ~/g2_taught/hi_step.json --name hiT            -> hiT_ref.npy
    python build_taught_step.py steps.json --name hiT --rear replace --rear-scale 1.0

The taught steps are the leg's path round ONE walking cycle, in order, ending just before the first step again (the loop closes by itself).
Only the taught leg's two joints are used. The path is a smooth closed curve through the steps (cubic Hermite, periodic), resampled to
100 frames. The other three legs follow the same path shifted by wkF's own leg phase offsets (FR 50, BR 88, BL 37 frames behind FL),
so the diagonal timing stays wkF's. Front legs use the taught angles directly; rear legs (`--rear delta`, default) take wkF's own rear
motion and add the taught leg's change about its mean times `--rear-scale`, because a rear leg's geometry is not a copy of a front leg's.
`--rear replace` uses the taught angles for the rear legs too. `--steps-at` gives each step's share of the cycle (default equal).
Check the result in the sim before G2 sees it:  ../../.venv/bin/python gait_probe.py wkf <name>   (G2E_SKILL_REF for the env).

Output: <name>_ref.npy, (100, 8) radians, URDF order [FLs, FLk, FRs, FRk, BRs, BRk, BLs, BLk].
"""
import argparse
import json
import pathlib

import numpy as np

HERE = pathlib.Path(__file__).parent
N = 100
LEG_INDEX = {"fl": 0, "fr": 1, "br": 2, "bl": 3}
PHASE = {"fl": 0, "fr": 50, "br": 88, "bl": 37}       # leg_i(t) = FL(t + PHASE_i), measured on wkF
LIMIT = 120.0


def closed_curve(points, times=None, n=N):
    """Periodic cubic Hermite through `points` (k, d) at cycle fractions `times` (k, increasing, in [0,1)); returns (n, d). Catmull-Rom tangents."""
    p = np.asarray(points, float)
    k = len(p)
    if k < 3:
        raise ValueError("teach at least 3 steps round the cycle")
    t = np.arange(k) / k if times is None else np.asarray(times, float)
    if len(t) != k or np.any(np.diff(t) <= 0) or t[0] < 0 or t[-1] >= 1:
        raise ValueError("step times must be increasing and inside [0, 1)")
    tt = np.concatenate([[t[-1] - 1], t, [t[0] + 1]])
    pp = np.vstack([p[-1], p, p[0]])
    m = (pp[2:] - pp[:-2]) / (tt[2:] - tt[:-2])[:, None]          # tangent at each step
    out = np.empty((n, p.shape[1]))
    for i in range(n):
        x = i / n
        j = np.searchsorted(t, x, side="right") - 1               # segment start (-1 = the wrap segment from the last step)
        a, b = (t[j], t[j + 1]) if 0 <= j < k - 1 else ((t[-1], t[0] + 1) if j == k - 1 else (t[-1] - 1, t[0]))
        pa, pb = (p[j], p[j + 1]) if 0 <= j < k - 1 else ((p[-1], p[0]) if j == k - 1 else (p[-1], p[0]))
        ma, mb = (m[j], m[j + 1]) if 0 <= j < k - 1 else ((m[-1], m[0]) if j == k - 1 else (m[-1], m[0]))
        h = b - a
        u = (x - a) / h
        out[i] = ((2*u**3 - 3*u**2 + 1) * pa + (u**3 - 2*u**2 + u) * h * ma + (-2*u**3 + 3*u**2) * pb + (u**3 - u**2) * h * mb)
    return out


def build(steps_deg, taught_leg, wkf_deg, rear="delta", rear_scale=1.0, times=None, start_frame=0):
    """steps_deg: list of 8-angle lists (only the taught leg's pair is used). wkf_deg: (100, 8) degrees. Returns (100, 8) degrees."""
    ti = LEG_INDEX[taught_leg]
    pair = np.array([[s[2 * ti], s[2 * ti + 1]] for s in steps_deg], float)
    path = closed_curve(pair, times)                                    # (100, 2): the taught leg over one cycle
    path = np.roll(path, -int(start_frame), axis=0)
    mean = path.mean(0)
    out = np.empty((N, 8))
    for leg, li in LEG_INDEX.items():
        shift = (PHASE[leg] - PHASE[taught_leg]) % N                    # this leg is `shift` frames ahead of the taught one
        seg = np.roll(path, -shift, axis=0)                             # seg[t] = path[t + shift]
        cols = slice(2 * li, 2 * li + 2)
        if leg in ("br", "bl") and rear == "delta":
            out[:, cols] = wkf_deg[:, cols] + (seg - mean) * rear_scale
        else:
            out[:, cols] = seg
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("steps_json")
    ap.add_argument("--name", required=True, help="writes <name>_ref.npy here")
    ap.add_argument("--rear", choices=["delta", "replace"], default="delta")
    ap.add_argument("--rear-scale", type=float, default=1.0)
    ap.add_argument("--steps-at", type=float, nargs="*", help="each step's cycle fraction 0..1 (default equal)")
    ap.add_argument("--start-frame", type=int, default=0, help="rotate the cycle by this many frames")
    ap.add_argument("--src", default="wkf_ref.npy")
    a = ap.parse_args()
    d = json.loads(pathlib.Path(a.steps_json).expanduser().read_text())
    wkf = np.rad2deg(np.load(HERE / a.src))
    out = build([s["deg"] for s in d["steps"]], d.get("leg", "fl"), wkf, a.rear, a.rear_scale, a.steps_at, a.start_frame)
    if np.abs(out).max() > LIMIT:
        raise SystemExit(f"a joint passes +/-{LIMIT:g} deg ({np.abs(out).max():.0f}); reteach or lower --rear-scale")
    np.save(HERE / f"{a.name}_ref.npy", np.deg2rad(out))
    print(f"wrote {a.name}_ref.npy  (100, 8)  taught leg {d.get('leg', 'fl')}, {len(d['steps'])} steps")
    print("  per-joint deg  min", out.min(0).round(0).astype(int).tolist())
    print("                 max", out.max(0).round(0).astype(int).tolist())
    print("  wkF            min", wkf.min(0).round(0).astype(int).tolist())
    print("                 max", wkf.max(0).round(0).astype(int).tolist())


if __name__ == "__main__":
    main()
