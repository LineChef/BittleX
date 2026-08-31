"""Drive the sim URDF open-loop through the wkf_ref.npy trajectory and see which
sign/mirroring variant actually produces a forward walk. Petoi's servo
convention (rotationDirection / middleShift) may not match this URDF's joint
axes, so we try candidates and score them by net forward distance + not falling.

Usage: python verify_wkf_reference.py            # score all variants
       python verify_wkf_reference.py <name> --render   # render frames for one
"""
import sys
import numpy as np
import pybullet as p
import pybullet_data
import pathlib

HERE = pathlib.Path(__file__).parent
REF = np.load(HERE / "wkf_ref.npy")          # (100, 8) rad, URDF order
N = len(REF)
BOUND = np.deg2rad(110)

# URDF joint order: [FLs, FLk, FRs, FRk, BRs, BRk, BLs, BLk]
FRONT_LEGS = [0, 1, 2, 3]
BACK_LEGS = [4, 5, 6, 7]
LEFT_LEGS = [0, 1, 6, 7]
RIGHT_LEGS = [2, 3, 4, 5]
SHOULDERS = [0, 2, 4, 6]
KNEES = [1, 3, 5, 7]

def variant(name, ref):
    r = ref.copy()
    if name == "identity":
        pass
    elif name == "global_flip":
        r = -r
    elif name == "flip_LR":                 # negate left-side joints
        r[:, LEFT_LEGS] *= -1
    elif name == "flip_RL":                 # negate right-side joints
        r[:, RIGHT_LEGS] *= -1
    elif name == "flip_knees":
        r[:, KNEES] *= -1
    elif name == "flip_shoulders":
        r[:, SHOULDERS] *= -1
    elif name == "phase_reverse":           # play the cycle backwards
        r = r[::-1].copy()
    elif name == "phase_reverse_flip":
        r = (-r[::-1]).copy()
    elif name == "swap_diag":              # swap the two diagonal pairs' phase
        r = np.roll(r, N // 2, axis=0)
    else:
        raise ValueError(name)
    return r

VARIANTS = ["identity", "global_flip", "flip_LR", "flip_RL", "flip_knees",
            "flip_shoulders", "phase_reverse", "phase_reverse_flip", "swap_diag"]

def run(ref_variant, cycles=4, gui=False, render_dir=None):
    p.connect(p.GUI if gui else p.DIRECT)
    p.setGravity(0, 0, -9.81)
    p.setAdditionalSearchPath(pybullet_data.getDataPath())
    p.loadURDF("plane.urdf")
    rid = p.loadURDF("models/bittle_esp32.urdf", [0, 0, 0.08],
                     p.getQuaternionFromEuler([0, 0, 0]),
                     flags=p.URDF_USE_SELF_COLLISION)
    jid = [j for j in range(p.getNumJoints(rid))
           if p.getJointInfo(rid, j)[2] in (p.JOINT_PRISMATIC, p.JOINT_REVOLUTE)]
    for j in jid:
        p.changeDynamics(rid, j, maxJointVelocity=np.pi * 10)
    # start at the reference's first frame
    for i, j in enumerate(jid):
        p.resetJointState(rid, j, float(np.clip(ref_variant[0, i], -BOUND, BOUND)))

    x0 = p.getBasePositionAndOrientation(rid)[0][0]
    fell_at = None
    frames = []
    total = cycles * N
    for t in range(total):
        tgt = np.clip(ref_variant[t % N], -BOUND, BOUND)
        p.setJointMotorControlArray(rid, jid, p.POSITION_CONTROL, tgt,
                                    forces=np.ones(8) * 0.2)
        for _ in range(4):
            p.stepSimulation()
        pos, orn = p.getBasePositionAndOrientation(rid)
        roll, pitch, _ = p.getEulerFromQuaternion(orn)
        if fell_at is None and (abs(roll) > 1.3 or abs(pitch) > 1.3):
            fell_at = t
        if render_dir and t % 6 == 0 and t < 2 * N:
            w, h, rgb, _, _ = p.getCameraImage(
                360, 270,
                viewMatrix=p.computeViewMatrixFromYawPitchRoll(
                    [pos[0], pos[1], 0.05], 0.55, 50, -30, 0, 2),
                projectionMatrix=p.computeProjectionMatrixFOV(60, 360 / 270, 0.1, 5),
                renderer=p.ER_TINY_RENDERER)
            frames.append(np.reshape(rgb, (h, w, 4))[:, :, :3].astype(np.uint8))
    xf = p.getBasePositionAndOrientation(rid)[0][0]
    p.disconnect()
    if render_dir and frames:
        from PIL import Image
        pathlib.Path(render_dir).mkdir(parents=True, exist_ok=True)
        imgs = [Image.fromarray(f) for f in frames]
        imgs[0].save(pathlib.Path(render_dir) / "wkf_openloop.gif", save_all=True,
                     append_images=imgs[1:], duration=80, loop=0, optimize=True)
    return xf - x0, fell_at, total

if __name__ == "__main__":
    if len(sys.argv) > 1 and not sys.argv[1].startswith("-"):
        name = sys.argv[1]
        dist, fell, total = run(variant(name, REF), cycles=4,
                                render_dir="frames_wkf" if "--render" in sys.argv else None)
        print(f"{name}: forward {dist:+.3f} m, fell_at={fell}/{total}")
    else:
        print(f"{'variant':<20} {'forward(m)':>10} {'fell_at':>10}")
        for name in VARIANTS:
            dist, fell, total = run(variant(name, REF))
            tag = "" if fell is None else f"  (fell {fell}/{total})"
            print(f"{name:<20} {dist:>+10.3f} {str(fell):>10}{tag}")
