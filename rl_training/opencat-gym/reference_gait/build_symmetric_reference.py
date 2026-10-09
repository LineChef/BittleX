"""Make a reference gait exactly left/right symmetric (user, 2026-10-09: "fix just the back legs so they are at 0 like the front legs").

wkF's front legs are exact mirrors of each other (left = right shifted by half a cycle, 0.00 deg) but its back legs are off by up to 1.1 deg: their best match is a shift of 49
frames, not 50. Here each pair of legs is replaced by one shape and its half-cycle shift: leg A := the mean of A and the half-cycle-shifted B, leg B := A shifted by half a cycle.
Each leg moves by at most half the old mismatch (about 0.6 deg) and the cycle length, timing and diagonal coordination are untouched.

    python build_symmetric_reference.py                  # wkf_ref.npy -> wkfsym_ref.npy   (use with G2E_SKILL_REF=wkfsym)
    python build_symmetric_reference.py highstep         # highstep_ref.npy -> highstepsym_ref.npy
"""
import pathlib
import sys

import numpy as np

HERE = pathlib.Path(__file__).parent
# URDF joint order: 0 FLsh 1 FLkn  2 FRsh 3 FRkn  4 BRhip 5 BRkn  6 BLhip 7 BLkn ; the mirrored pairs are (0,2) (1,3) (4,6) (5,7)
PAIRS = ((0, 2), (1, 3), (4, 6), (5, 7))


def symmetrize(ref: np.ndarray) -> np.ndarray:
    out = ref.copy()
    half = len(ref) // 2
    for a, b in PAIRS:
        mean = 0.5 * (ref[:, a] + np.roll(ref[:, b], half))           # leg a and leg b brought to the same phase, then averaged
        out[:, a] = mean
        out[:, b] = np.roll(mean, -half)                               # np.roll(out[:, b], half) == out[:, a]
    return out


def mismatch_deg(ref: np.ndarray) -> list:
    half = len(ref) // 2
    return [round(float(np.degrees(np.abs(ref[:, a] - np.roll(ref[:, b], half)).max())), 3) for a, b in PAIRS]


if __name__ == "__main__":
    name = sys.argv[1] if len(sys.argv) > 1 else "wkf"
    src = HERE / f"{name}_ref.npy"
    ref = np.load(src)
    out = symmetrize(ref)
    dst = HERE / f"{name}sym_ref.npy"
    np.save(dst, out)
    print(f"{src.name}: half-cycle mismatch per pair (deg) {mismatch_deg(ref)} -> {dst.name}: {mismatch_deg(out)}; largest change per joint (deg) {np.round(np.degrees(np.abs(out - ref).max(axis=0)), 2).tolist()}")
