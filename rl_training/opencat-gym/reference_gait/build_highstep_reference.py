"""Author a HIGH-STEP gait from wkF -- exaggerated swing-foot clearance for
stepping OVER a low obstacle (Phase E `STEP_OVER`). Trot (`tr_ref`) is a walk
gait, not a lift-and-clear; this is.

Method: keep wkF's timing + diagonal coordination, but during each leg's swing
phase (shoulder above its own mean = leg lifting) add extra shoulder lift and
extra knee flex (foot tucks up toward the body), raised-cosine gated so the
motion stays smooth and the stance phase is untouched.

    python build_highstep_reference.py                 -> highstep_ref.npy
    python build_highstep_reference.py --shoulder 14 --knee 24

Output: reference_gait/highstep_ref.npy, (100, 8) radians, URDF joint order
(same format as wkf_ref.npy), so it drops into SkillRefs / G2E_SKILL_REF.
"""
import argparse
import pathlib

import numpy as np

HERE = pathlib.Path(__file__).parent
# URDF joint order: 0 FLsh 1 FLkn  2 FRsh 3 FRkn  4 BRhip 5 BRkn  6 BLhip 7 BLkn
SH = [0, 2, 4, 6]
KN = [1, 3, 5, 7]

ap = argparse.ArgumentParser()
ap.add_argument("--shoulder", type=float, default=12.0, help="extra shoulder lift, deg (peak of swing)")
ap.add_argument("--knee", type=float, default=20.0, help="extra knee flex, deg (peak of swing) -- foot tucks up")
ap.add_argument("--src", default="wkf_ref.npy")
ap.add_argument("--out", default="highstep_ref.npy")
args = ap.parse_args()

base = np.load(HERE / args.src)                 # (100, 8) rad
deg = np.rad2deg(base)
out = deg.copy()

for sh_j, kn_j in zip(SH, KN):
    s = deg[:, sh_j]
    lo, hi = s.min(), s.max()
    # swing weight: 0 at the bottom of the shoulder cycle, 1 at the top, smooth
    w = np.clip((s - lo) / max(1e-6, hi - lo), 0.0, 1.0)
    w = 0.5 - 0.5 * np.cos(np.pi * w)           # raised cosine -> gentle onset/return
    out[:, sh_j] = s + args.shoulder * w
    # knee: subtract (more negative = more flexed = foot up), based on this leg's
    # sign of "flex". wkF knee mean ~ +12; below mean = flexing -> push it further.
    k = deg[:, kn_j]
    km = k.mean()
    flexing = np.clip((km - k) / max(1e-6, km - k.min()), 0.0, 1.0)
    kw = w * (0.4 + 0.6 * flexing)              # lift-gated, deepest where it's already flexing
    out[:, kn_j] = k - args.knee * kw

out = np.clip(out, -100.0, 100.0)
ref = np.deg2rad(out)
np.save(HERE / args.out, ref)

print(f"src {args.src}  +shoulder {args.shoulder}  +knee {args.knee}")
for name, idx in (("shoulder/hip", SH), ("knee", KN)):
    b = deg[:, idx]; a = out[:, idx]
    print(f"  {name:12s} swing range  wkF {b.ptp(0).round(0).astype(int).tolist()}"
          f"  ->  highstep {a.ptp(0).round(0).astype(int).tolist()}")
print(f"  wrote {args.out}  {ref.shape}  (radians, URDF order)")
