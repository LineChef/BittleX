"""Parse any built-in OpenCat skill out of InstinctBittleESP.h into a per-phase
reference trajectory, same format/orientation as wkf_ref.npy.

Generalises build_wkf_reference.py (which is wkF-only). Handles:
  * GAITS  (period > 1): header [period, expRoll, expPitch, ratio] then
    period * 8 int8 leg-joint angles -> (RESAMPLE, 8) radians, URDF order.
  * BEHAVIOURS (period < -1): 7-byte header
    [period, expRoll, expPitch, ratio, loopStart, loopEnd, loopCycles] then
    abs(period) * (16 + 4) values/frame -- 16 full-DOF angles + 4 timing params.
    Only the 8 leg joints (DOF 8..15) are kept, timing params dropped, so the
    output matches the gait format. Marked approximate -- behaviours aren't a
    looping phase trajectory, this is a keyframe reference for sim work only.

Usage:
    python build_skill_reference.py vtF          -> vt_ref.npy
    python build_skill_reference.py crF trF bkF  -> cr_ref.npy tr_ref.npy bk_ref.npy
    python build_skill_reference.py rc           -> rc_ref.npy  (behaviour, approx)

Petoi leg-joint column order  [FLs,FRs,BRs,BLs, FLk,FRk,BRk,BLk]
URDF joint order              [FLs,FLk, FRs,FRk, BRs,BRk, BLs,BLk]
"""
import re
import sys
import numpy as np
import pathlib

HERE = pathlib.Path(__file__).parent
SRC = HERE / "InstinctBittleESP.h"
RESAMPLE = 100                       # matches the env's TIME_PHASE_PERIOD
PETOI_TO_URDF = [0, 4, 1, 5, 2, 6, 3, 7]
WALKING_DOF = 8
FULL_DOF = 16
BEHAVIOUR_EXTRA = 4                  # trailing timing params per behaviour frame

_text = SRC.read_text()


def _nums(name):
    m = re.search(r"const int8_t %s\[\] PROGMEM = \{(.*?)\};" % re.escape(name), _text, re.S)
    if not m:
        raise SystemExit(f"{name}[] not found in {SRC.name}")
    return [int(x) for x in re.findall(r"-?\d+", m.group(1))]


def _resample(frames_urdf_deg, period):
    src_phase = np.arange(period) / period
    dst_phase = np.arange(RESAMPLE) / RESAMPLE
    out = np.empty((RESAMPLE, 8))
    for j in range(8):
        ext_x = np.concatenate([src_phase, [1.0]])
        ext_y = np.concatenate([frames_urdf_deg[:, j], [frames_urdf_deg[0, j]]])
        out[:, j] = np.interp(dst_phase, ext_x, ext_y)
    return np.deg2rad(out)


def build(name):
    nums = _nums(name)
    period = nums[0]
    ratio = nums[3]
    if period > 1:                                   # gait
        body = np.array(nums[4:4 + period * WALKING_DOF], dtype=float) * ratio
        frames_petoi = body.reshape(period, WALKING_DOF)
        kind = "gait"
    elif period <= -1:                               # behaviour (period == -1 -> single keyframe)
        n = abs(period)
        stride = FULL_DOF + BEHAVIOUR_EXTRA
        body = np.array(nums[7:7 + n * stride], dtype=float).reshape(n, stride) * ratio
        frames_petoi = body[:, 8:16]                 # leg joints only (DOF 8..15)
        period = n
        kind = "behaviour (approx -- keyframes, not a phase loop)"
    elif period == 1:                                # static posture: one full-DOF row
        row = np.array(nums[4:4 + FULL_DOF], dtype=float) * ratio
        frames_petoi = row[8:16].reshape(1, WALKING_DOF)   # 8 leg joints
        kind = "posture (single frame)"
    else:
        raise SystemExit(f"{name}: period={period} not supported")

    frames_urdf_deg = frames_petoi[:, PETOI_TO_URDF]
    ref_rad = (np.deg2rad(frames_urdf_deg) if period == 1
               else _resample(frames_urdf_deg, period))

    out_name = re.sub(r"(F|L)$", "", name) + "_ref.npy"
    np.save(HERE / out_name, ref_rad)
    deg = np.rad2deg(ref_rad)
    print(f"{name:8s} {kind:42s} period={period:3d} ratio={ratio}")
    print(f"  per-joint deg  min {deg.min(0).round(0).astype(int).tolist()}")
    print(f"                 max {deg.max(0).round(0).astype(int).tolist()}")
    try:
        wkf = np.rad2deg(np.load(HERE / "wkf_ref.npy"))
        if deg.shape == wkf.shape:
            print(f"  mean |{name} - wkF| = {np.abs(deg - wkf).mean():.1f} deg   "
                  f"knee-swing range vs wkF: {deg[:,1::2].ptp():.0f} vs {wkf[:,1::2].ptp():.0f}")
    except FileNotFoundError:
        pass
    print(f"  wrote {out_name}  {ref_rad.shape}  (radians, URDF order)")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    for s in sys.argv[1:]:
        build(s)
