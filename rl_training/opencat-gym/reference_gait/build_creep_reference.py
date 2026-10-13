"""The high-step creep base gait: a slow walk with three feet on the ground at all times, built from a few parameters (user, 2026-10-12; plan:
docs/plan-detail/high-step-creep-training-plan.md). The numbers are picked by a sim parameter search (creep_sweep.py), not written by hand.

    ../../../.venv/bin/python build_creep_reference.py --name creep [--params '{"sway": 15, "lean": 8}']      # -> creep_ref.npy (100, 8) rad + creep_ref.json (the parameters)

Structure (URDF joint order [FLs, FLk, FRs, FRk, BRs, BRk, BLs, BLk], degrees before the save):
  - Lateral-sequence creep: back-left, front-left, back-right, front-right, each leg in the air for (1 - duty) of the cycle. The left/right mirror image is the same gait half a
    cycle later (what mirror.py's loss assumes).
  - Stance: the shoulder sweeps c - A -> c + A (a growing shoulder angle moves the paw back, as in wkF: that is the push). Swing: the shoulder returns and the knee dips by L
    (negative knee = paw up), a half-sine.
  - sway: while a REAR leg is in the air, the knees of the other legs on its side straighten by `sway` deg and the knees on the far side bend by `sway`. G2 has no sideways hip
    joint, so this roll is the only way to move his weight over the three planted feet; without it the rear corner sinks onto the lifting paw and it never leaves the floor
    (sim, 2026-10-12: rear paw lift 0.2 in without sway, 0.76 in with 15 deg). `sway_f` is the same for a front leg in the air (0 = none: it did not help the front feet).
  - lean: while a rear leg is in the air every stance shoulder adds `lean` deg (paws back = body forward over the front feet).
  - A 7-frame circular moving average smooths the sway / lean switching.
"""
import argparse
import json
import os

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
OFFS = (0.5, 0.0, 0.25, 0.75)          # phase offsets FL, FR, BR, BL: BL swings first (phase 0-0.2 at duty 0.8), then FL, BR, FR
LEFT = (True, False, False, True)      # FL, FR, BR, BL
DEFAULTS = dict(A=12.0, Lf=29.0, Lr=35.0, cf=39.0, cr=52.0, ksf=7.0, ksr=17.0, duty=0.8, lean=0.0, sway=15.0, sway_f=0.0)


def build(**kw) -> np.ndarray:
    """(100, 8) degrees, URDF order."""
    q = dict(DEFAULTS, **kw)
    A, duty = q["A"], q["duty"]
    legs = ((0, 1, q["cf"], q["ksf"], q["Lf"]), (2, 3, q["cf"], q["ksf"], q["Lf"]), (4, 5, q["cr"], q["ksr"], q["Lr"]), (6, 7, q["cr"], q["ksr"], q["Lr"]))
    ref = np.zeros((100, 8))
    for i in range(100):
        ph = i / 100
        phases = [(ph + o) % 1.0 for o in OFFS]
        swing = [j for j in range(4) if phases[j] >= duty]
        rear_swing = any(j >= 2 for j in swing)
        for j, (si, ki, c, ks, L) in enumerate(legs):
            s_ = phases[j]
            if s_ < duty:
                s = s_ / duty
                sh, kn = c - A + 2 * A * s, ks
                if rear_swing:
                    sh += q["lean"]
                for sj in swing:
                    amt = q["sway"] if sj >= 2 else q["sway_f"]
                    kn += amt if LEFT[j] == LEFT[sj] else -amt
            else:
                s = (s_ - duty) / (1 - duty)
                sh = c + A - 2 * A * (0.5 - 0.5 * np.cos(np.pi * s))
                kn = ks - L * np.sin(np.pi * s)
            ref[i, si], ref[i, ki] = sh, kn
    k = 7
    return np.array([np.mean(ref[[(i + d) % 100 for d in range(-(k // 2), k // 2 + 1)]], axis=0) for i in range(100)])


def mirror_error_deg(ref_deg: np.ndarray) -> float:
    """Largest joint difference between the gait mirrored left/right and the same gait half a cycle later (0 for a symmetric creep)."""
    m = ref_deg[:, [2, 3, 0, 1, 6, 7, 4, 5]]
    return float(np.max(np.abs(m - np.roll(ref_deg, -50, axis=0))))


def save(name: str, params: dict, out_dir: str = HERE) -> str:
    ref = build(**params)
    path = os.path.join(out_dir, f"{name}_ref.npy")
    np.save(path, np.radians(ref))
    json.dump({"generator": "build_creep_reference.py", "params": dict(DEFAULTS, **params), "mirror_error_deg": round(mirror_error_deg(ref), 4)},
              open(os.path.join(out_dir, f"{name}_ref.json"), "w"), indent=1)
    return path


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", default="creep")
    ap.add_argument("--params", default="{}", help="JSON of parameters to change from DEFAULTS")
    ap.add_argument("--out-dir", default=HERE)
    a = ap.parse_args()
    print(save(a.name, json.loads(a.params), a.out_dir))
