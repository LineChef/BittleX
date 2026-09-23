"""Map the policy's 8 joint targets (URDF order, degrees) to an OpenCat 'i'-command
over servo indices, with per-servo sign and zero-offset hooks for hardware calibration.

URDF / WKF_REF / policy order (from reference_gait/build_wkf_reference.py):
    [0 FL-shoulder, 1 FL-knee, 2 FR-shoulder, 3 FR-knee,
     4 BR-shoulder, 5 BR-knee, 6 BL-shoulder, 7 BL-knee]
    FL=front-left  FR=front-right  BR=back-right  BL=back-left

OpenCat Bittle leg servos are indices 8..15 in this order (Petoi joint map):
    [8 FL-shoulder, 9 FR-shoulder, 10 BR-shoulder, 11 BL-shoulder,
     12 FL-knee,    13 FR-knee,    14 BR-knee,     15 BL-knee]

So: URDF i -> servo URDF_TO_SERVO[i].
The reference gait was built with NO sign flips and verified to walk the URDF
open-loop (+0.48 m), and the URDF was authored to Petoi's sign convention -- so
SERVO_SIGN defaults to all +1 and SERVO_OFFSET_DEG to all 0. **Both MUST be
checked on the real robot** before trusting the gait (a mirrored or offset servo
turns a walk into a fall):
  1. `i8 0 9 0 10 0 11 0 12 0 13 0 14 0 15 0` should hold a symmetric neutral.
  2. Drive `wkf_ref.npy` open-loop (see run_gait.py --openloop) and watch: it
     should walk forward slowly. If a leg kicks backward or the gait is mirrored,
     flip that servo's sign here.

Why `i`, not `m` (2026-09-22, traced in OpenCatEsp32 `reaction.h`): `m`
(T_INDEXED_SEQUENTIAL_ASC) moves the listed joints one at a time -- each eased
at 1 deg per 8 ms, then a 10 ms pause -- so one 8-joint command takes >=144 ms
against run_gait's 12.5 ms tick, and a backlog makes the firmware run the
oldest queued command and drop the rest. `i` (T_INDEXED_SIMULTANEOUS_ASC)
moves them together in one eased transform (2 deg per 8 ms). Sim model:
`m` doesn't walk at all, `i` walks at ~96% of ideal speed with ~55 ms lag --
see rl_training/opencat-gym/resilience_joint_cmd.py.
"""
from __future__ import annotations

import numpy as np

# URDF joint index -> OpenCat servo index
URDF_TO_SERVO = [8, 12, 9, 13, 10, 14, 11, 15]

# per-servo calibration (index by URDF joint order, same as the policy output)
SERVO_SIGN = [1, 1, 1, 1, 1, 1, 1, 1]          # flip to -1 if a servo is mirrored vs the URDF
SERVO_OFFSET_DEG = [0, 0, 0, 0, 0, 0, 0, 0]    # added after sign; real servo zero vs URDF zero

# OpenCat servos accept roughly +/-125 deg; the policy already clips to +/-110,
# but clamp again after offset so a bad calibration can't command a slam.
SERVO_LIMIT_DEG = 120


def policy_deg_to_move_cmd(joint_deg_urdf) -> str:
    """[8 ints, URDF order, degrees] -> 'i8 <d> 12 <d> 9 <d> ...' for the BiBoard."""
    jd = np.asarray(joint_deg_urdf, dtype=float).reshape(8)
    out = jd * np.asarray(SERVO_SIGN) + np.asarray(SERVO_OFFSET_DEG)
    out = np.clip(np.rint(out), -SERVO_LIMIT_DEG, SERVO_LIMIT_DEG).astype(int)
    pairs = []
    for i in range(8):
        pairs.append(f"{URDF_TO_SERVO[i]} {int(out[i])}")
    return "i" + " ".join(pairs)
