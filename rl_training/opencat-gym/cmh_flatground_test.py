"""Sanity check: play the raw, unmodified `cmh` climbing keyframe sequence on
FLAT ground, no ledge, no obstacle -- does the motion itself execute without
the robot falling over? Isolates "can this motion be simulated at all" from
"does it succeed at climbing something", since every climb test so far has
confounded the two.

    python cmh_flatground_test.py out.gif
"""
import argparse

import numpy as np
import pybullet as p
import pybullet_data

from climb_env import _BASE, REV, STANCE, _URDF, JOINT_FORCE, FRAME_SKIP

ap = argparse.ArgumentParser()
ap.add_argument("out", nargs="?", default=None)
ap.add_argument("--speed", type=float, default=2.0)
ap.add_argument("--w", type=int, default=480)
ap.add_argument("--h", type=int, default=360)
args = ap.parse_args()

FRAME_MS = 67
CAPTURE_EVERY = max(1, round(FRAME_MS / 1000 * 60 * args.speed))

p.connect(p.DIRECT)
p.setAdditionalSearchPath(pybullet_data.getDataPath())
p.setGravity(0, 0, -9.81)
p.setTimeStep(1.0 / 240.0)
p.loadURDF("plane.urdf", [0, 0, 0])
rid = p.loadURDF(_URDF, [0, 0, 0.08], p.getQuaternionFromEuler([0, 0, 0]), flags=p.URDF_USE_SELF_COLLISION)
for j, a in zip(REV, STANCE):
    p.resetJointState(rid, j, a)
for _ in range(30):
    p.setJointMotorControlArray(rid, REV, p.POSITION_CONTROL, targetPositions=STANCE.tolist(), forces=[2.4] * 8)
    p.stepSimulation()

frames = []
_step_count = 0


def tilt():
    bo = p.getBasePositionAndOrientation(rid)[1]
    return np.rad2deg(max(abs(x) for x in p.getEulerFromQuaternion(bo)[0:2]))


def _snap():
    pos = p.getBasePositionAndOrientation(rid)[0]
    _, _, rgb, _, _ = p.getCameraImage(
        args.w, args.h,
        viewMatrix=p.computeViewMatrixFromYawPitchRoll(
            cameraTargetPosition=[pos[0], pos[1], 0.05], distance=0.45,
            yaw=35, pitch=-20, roll=0, upAxisIndex=2),
        projectionMatrix=p.computeProjectionMatrixFOV(60, args.w / args.h, 0.1, 5),
        renderer=p.ER_TINY_RENDERER)
    frames.append(np.reshape(rgb, (args.h, args.w, 4))[:, :, :3].astype(np.uint8))


def sim_step():
    global _step_count
    p.stepSimulation()
    _step_count += 1
    if args.out and _step_count % CAPTURE_EVERY == 0:
        _snap()


print(f"Playing raw cmh sequence ({len(_BASE)} ticks) on flat ground, zero residual...")
flipped_at = None
for t in range(len(_BASE)):
    tgt = _BASE[t]
    for _ in range(FRAME_SKIP):
        p.setJointMotorControlArray(rid, REV, p.POSITION_CONTROL, targetPositions=tgt.tolist(), forces=[JOINT_FORCE] * 8)
        sim_step()
    tl = tilt()
    if t % 20 == 0:
        bx = p.getBasePositionAndOrientation(rid)[0][0]
        print(f"  tick {t}: tilt={tl:.1f}, body_x={bx:.4f}")
    if tl > 68.8:   # ~1.2 rad, matches climb_env.py's FLIP_RAD threshold
        flipped_at = t
        print(f"FLIPPED at tick {t}/{len(_BASE)} -- the motion itself is not stable on flat ground")
        break

if flipped_at is None:
    for _ in range(60):
        p.setJointMotorControlArray(rid, REV, p.POSITION_CONTROL, targetPositions=_BASE[-1].tolist(), forces=[JOINT_FORCE] * 8)
        sim_step()
    bx = p.getBasePositionAndOrientation(rid)[0][0]
    print(f"Sequence completed without flipping. body_x={bx:.4f}, final tilt={tilt():.1f}")
    print("-> the cmh motion IS simulatable/executable on its own (flat ground, no obstacle).")
else:
    print("-> the cmh motion itself is NOT stable even with nothing to climb -- a real motion-level issue,")
    print("   not just a footing/obstacle problem.")

if args.out and frames:
    for _ in range(15):
        _snap()
    from PIL import Image
    imgs = [Image.fromarray(f) for f in frames]
    durations = [FRAME_MS] * (len(imgs) - 15) + [150] * 15
    imgs[0].save(args.out, save_all=True, append_images=imgs[1:], duration=durations, loop=0, optimize=True)
    print(f"{args.out}: {len(imgs)} frames")
p.disconnect()
