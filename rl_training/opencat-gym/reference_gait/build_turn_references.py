"""Parse Bittle's built-in `wkL` (walk-turn-left) gait out of InstinctBittleESP.h
and produce wkl_ref.npy + its left/right mirror wkr_ref.npy, in the same format
as wkf_ref.npy (shape (RESAMPLE, 8), radians, URDF joint order).

Same header/frame format as wkF (see build_wkf_reference.py). wkR is not in the
firmware -- it's the leg-swapped mirror of wkL (the sim joints are all sagittal,
so a pure FL<->FR / BL<->BR column swap flips the turn direction, no sign flip).
"""
import re
import numpy as np
import pathlib

HERE = pathlib.Path(__file__).parent
SRC = HERE / "InstinctBittleESP.h"
RESAMPLE = 100

petoi_to_urdf = [0, 4, 1, 5, 2, 6, 3, 7]
# URDF order [FLs,FLk, FRs,FRk, BRs,BRk, BLs,BLk]; swap FL<->FR, BL<->BR
mirror_lr = [2, 3, 0, 1, 6, 7, 4, 5]

text = SRC.read_text()


def parse(name):
    m = re.search(r"const int8_t %s\[\] PROGMEM = \{(.*?)\};" % name, text, re.S)
    if not m:
        raise SystemExit(f"{name} array not found")
    nums = [int(x) for x in re.findall(r"-?\d+", m.group(1))]
    period, _r, _p, ratio = nums[:4]
    body = nums[4:]
    assert len(body) == period * 8, f"{name}: {len(body)} != {period}*8"
    frames_petoi = np.array(body, dtype=float).reshape(period, 8) * ratio
    frames_urdf = frames_petoi[:, petoi_to_urdf]
    src_phase = np.arange(period) / period
    dst_phase = np.arange(RESAMPLE) / RESAMPLE
    res = np.empty((RESAMPLE, 8))
    for j in range(8):
        ext_x = np.concatenate([src_phase, [1.0]])
        ext_y = np.concatenate([frames_urdf[:, j], [frames_urdf[0, j]]])
        res[:, j] = np.interp(dst_phase, ext_x, ext_y)
    return np.deg2rad(res), period


wkl, per = parse("wkL")
np.save(HERE / "wkl_ref.npy", wkl)
wkr = wkl[:, mirror_lr]
np.save(HERE / "wkr_ref.npy", wkr)

print(f"wkL: period={per}  saved wkl_ref.npy {wkl.shape}")
print(f"wkR = mirror(wkL)   saved wkr_ref.npy {wkr.shape}")
print(f"wkL frame0 deg (URDF): {np.rad2deg(wkl[0]).round(1).tolist()}")
print(f"wkR frame0 deg (URDF): {np.rad2deg(wkr[0]).round(1).tolist()}")
try:
    wkf = np.load(HERE / "wkf_ref.npy")
    dl = float(np.mean(np.abs(wkl - wkf)))
    print(f"mean |wkL - wkF| = {np.rad2deg(dl):.1f} deg  (turn gait should differ from straight)")
except FileNotFoundError:
    pass
