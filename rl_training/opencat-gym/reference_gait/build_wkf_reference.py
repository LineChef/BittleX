"""Parse Bittle's built-in `wkF` (walk-Forward) gait out of OpenCatEsp32's
InstinctBittleESP.h and turn it into a per-phase reference trajectory the sim
env can imitate.

wkF format (confirmed from OpenCatEsp32/src/skill.h):
  header = [period, expectedRoll, expectedPitch, angleDataRatio]
         = [116, 0, 0, 1]   -> 116 frames, looping gait, angles are degrees as-is
  each frame = 8 int8 angles for DOF 8..15 (the leg joints), in order
    [FL-shoulder, FR-shoulder, BR-shoulder, BL-shoulder,
     FL-knee,     FR-knee,     BR-knee,     BL-knee]

The sim URDF (ger01d/opencat-gym bittle_esp32.urdf) orders its 8 joints
leg-interleaved:
    [0 FL-shoulder, 1 FL-knee, 2 FR-shoulder, 3 FR-knee,
     4 BR-shoulder, 5 BR-knee, 6 BL-shoulder, 7 BL-knee]

Output: reference_gait/wkf_ref.npy, shape (RESAMPLE, 8), radians, in URDF joint
order. Sign/mirroring is NOT resolved here -- verify_wkf_reference.py tries the
candidate variants against the sim and picks the one that actually walks.
"""
import re
import numpy as np
import pathlib

HERE = pathlib.Path(__file__).parent
SRC = HERE / "InstinctBittleESP.h"
RESAMPLE = 100  # match the env's TIME_PHASE_PERIOD so time_obs maps 1:1 to a frame

text = SRC.read_text()
m = re.search(r"const int8_t wkF\[\] PROGMEM = \{(.*?)\};", text, re.S)
if not m:
    raise SystemExit("wkF array not found")
nums = [int(x) for x in re.findall(r"-?\d+", m.group(1))]

period, exp_roll, exp_pitch, ratio = nums[:4]
body = nums[4:]
assert period > 1, f"expected a gait, got period={period}"
assert len(body) == period * 8, f"{len(body)} angle values != {period}*8"
frames_petoi = np.array(body, dtype=float).reshape(period, 8) * ratio   # degrees, Petoi joint 8..15 order

# Petoi frame column -> URDF joint index
#   petoi: [FLs, FRs, BRs, BLs, FLk, FRk, BRk, BLk]  (cols 0..7)
#   urdf : [FLs, FLk, FRs, FRk, BRs, BRk, BLs, BLk]  (idx 0..7)
petoi_to_urdf = [0, 4, 1, 5, 2, 6, 3, 7]   # urdf[i] = petoi_col[ petoi_to_urdf[i] ]
frames_urdf_deg = frames_petoi[:, petoi_to_urdf]

# resample the cycle to RESAMPLE frames (periodic linear interp)
src_phase = np.arange(period) / period
dst_phase = np.arange(RESAMPLE) / RESAMPLE
res = np.empty((RESAMPLE, 8))
for j in range(8):
    ext_x = np.concatenate([src_phase, [1.0]])
    ext_y = np.concatenate([frames_urdf_deg[:, j], [frames_urdf_deg[0, j]]])
    res[:, j] = np.interp(dst_phase, ext_x, ext_y)

ref_rad = np.deg2rad(res)
np.save(HERE / "wkf_ref.npy", ref_rad)

print(f"wkF: period={period} frames, ratio={ratio}, exp_roll/pitch={exp_roll}/{exp_pitch}")
print(f"Petoi frame 0 (deg):  {frames_petoi[0].round(1).tolist()}")
print(f"URDF-order frame 0 (deg): {frames_urdf_deg[0].round(1).tolist()}")
print(f"per-joint deg range: min {res.min(0).round(1).tolist()}")
print(f"                     max {res.max(0).round(1).tolist()}")
print(f"saved wkf_ref.npy  shape {ref_rad.shape}  (radians, URDF joint order)")
print(f"env standing pose for reference: shoulders +50 deg, knees 0 deg")
