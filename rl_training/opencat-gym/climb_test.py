"""Step-UP / mount iteration harness. Build a multi-phase scripted keyframe from
params, drive it against a ledge in PyBullet, score whether G2 got up ONTO it.

Motion phases (deltas in DEGREES from the neutral stance, URDF joint order
[FLsh FLkn  FRsh FRkn  BRhip BRkn  BLhip BLkn]):

  0 stance         four feet down, neutral
  1 front reach-up  front shoulders up + front knees flex   -> front feet high, near the ledge face
  2 front plant     front shoulders fwd + front knees extend -> front feet land ON the ledge top
  3 body pull-up    front shoulders rotate back + rear hips push -> body drags forward & up onto the ledge
  4 rear lift       rear hips + knees flex                   -> rear feet come up off the floor
  5 rear plant      rear hips fwd + rear knees extend        -> rear feet land ON the ledge
  6 top stand       relax toward stance, standing on the block

    python climb_test.py                         # defaults, prints a score breakdown
    python climb_test.py --ledge 0.035 --f-up 44 --render
    python climb_test.py --gif /tmp/climb.gif    # labelled side-view GIF

Score (0..~110): forward progress onto the block + correct on-top height +
feet-on-top + uprightness, minus a big penalty for flipping.
"""
import argparse
import os

import numpy as np

for _k, _v in {"G2E_OBSTACLE_COUNT": "0", "G2E_RANDOM_TERRAIN_PROB": "0",
               "G2E_SLOPE_MAX_DEG": "0", "G2E_CLIFF_PROB": "0",
               "G2E_RANDOM_TERRAIN": "0"}.items():
    os.environ[_k] = _v

import pybullet as p                                                  # noqa: E402
import opencat_gym_env                                                # noqa: E402
from opencat_gym_env import OpenCatGymEnv, WKF_REF                     # noqa: E402

REV = [1, 2, 4, 5, 7, 8, 10, 11]        # revolute joints, URDF keyframe order
PAW = [3, 6, 9, 12]                     # FL FR BR BL paw links
FRONT_SH, FRONT_KN = [0, 2], [1, 3]
REAR_HIP, REAR_KN = [4, 6], [5, 7]
STANCE = np.rad2deg(WKF_REF.mean(axis=0))


def build_traj(pr):
    """params dict -> (N, 8) absolute joint trajectory in RADIANS."""
    def pose(*deltas):
        q = STANCE.copy()
        for idx, v in deltas:
            for i in idx:
                q[i] += v
        return q

    # sign map (from the joint->paw probe):
    #   front foot reaches FORWARD with shoulder DECREASE; body is PULLED forward
    #   by front-shoulder INCREASE (rakes planted front feet back) + rear-knee
    #   INCREASE (push); knee increase raises the body.
    fk_hold = pr["f_plant_kn"] - 6           # front knee while planted on the ledge top
    p0 = pose()
    p1 = pose((FRONT_SH, pr["f_up_sh"]), (FRONT_KN, -pr["f_up_kn"]))          # tuck front feet UP
    p2 = pose((FRONT_SH, -pr["f_plant_sh"]), (FRONT_KN, pr["f_plant_kn"]))   # reach fwd + plant on top
    p3 = pose((FRONT_SH, pr["pull_sh"]), (FRONT_KN, fk_hold),                # rake front feet back = drag body fwd
              (REAR_HIP, pr["pull_hip"]), (REAR_KN, pr["pull_kn"]))          # + rear knees push
    # P4 BOOST: no rear lift -- both ends PUSH. Front knees extend (levers front
    # of body up, nose up), rear knees extend hard (push body fwd+up). All feet
    # stay loaded so it doesn't tip.
    p4 = pose((FRONT_SH, pr["pull_sh"] * 0.7), (FRONT_KN, pr["f_plant_kn"] + pr["boost_fkn"]),
              (REAR_HIP, pr["pull_hip"]), (REAR_KN, pr["pull_kn"] + pr["boost_rkn"]))
    # P5 rear shuffle onto the ledge: bring rear feet forward (hip back-rotate),
    # only a small knee tuck so they skim rather than lift off.
    p5 = pose((FRONT_SH, pr["pull_sh"] * 0.5), (FRONT_KN, fk_hold),
              (REAR_HIP, -pr["r_plant_hip"]), (REAR_KN, pr["r_plant_kn"]))
    p6 = pose((FRONT_SH, pr["pull_sh"] * 0.2), (FRONT_KN, 4),
              (REAR_HIP, -pr["r_plant_hip"] * 0.5), (REAR_KN, pr["r_plant_kn"] * 0.5))
    poses = [p0, p1, p2, p3, p4, p5, p6]
    segs = pr["ticks"]
    out = []
    for a, b, n in zip(poses[:-1], poses[1:], segs):
        for t in range(n):
            w = (t + 1) / n
            w = 0.5 - 0.5 * np.cos(np.pi * w)          # ease
            out.append(a * (1 - w) + b * w)
    return np.deg2rad(np.array(out))


def run(pr, ledge_h, render=False, gif=None):
    opencat_gym_env.GUI_MODE = render
    opencat_gym_env.DR_EVAL_FULL = False
    env = OpenCatGymEnv()
    env.reset()
    rid = env.robot_id

    front_x = 0.085                                  # ledge front face just ahead of the front paws
    L = 0.40
    vs = p.createVisualShape(p.GEOM_BOX, halfExtents=[L / 2, 0.25, ledge_h / 2],
                             rgbaColor=[0.55, 0.45, 0.35, 1])
    cs = p.createCollisionShape(p.GEOM_BOX, halfExtents=[L / 2, 0.25, ledge_h / 2])
    p.createMultiBody(0, cs, vs, [front_x + L / 2, 0.0, ledge_h / 2])

    traj = build_traj(pr)
    # settle at stance
    for _ in range(40):
        p.setJointMotorControlArray(rid, REV, p.POSITION_CONTROL,
                                    targetPositions=np.deg2rad(STANCE).tolist(), forces=[1.6] * 8)
        p.stepSimulation()
    x0 = p.getBasePositionAndOrientation(rid)[0][0]

    frames, phase_log = [], []
    seg_bounds = np.cumsum(pr["ticks"])
    for k, tgt in enumerate(traj):
        p.setJointMotorControlArray(rid, REV, p.POSITION_CONTROL,
                                    targetPositions=tgt.tolist(), forces=[2.6] * 8)
        p.stepSimulation()
        if gif and k % 3 == 0:
            frames.append(_grab(rid, front_x, ledge_h))
        ph = int(np.searchsorted(seg_bounds, k, side="right"))
        if not phase_log or phase_log[-1][0] != ph:
            pos, orn = p.getBasePositionAndOrientation(rid)
            phase_log.append((ph, pos[0] - x0, pos[2], np.degrees(p.getEulerFromQuaternion(orn)[1])))
    # let it settle on top
    for _ in range(60):
        p.setJointMotorControlArray(rid, REV, p.POSITION_CONTROL,
                                    targetPositions=traj[-1].tolist(), forces=[2.6] * 8)
        p.stepSimulation()
        if gif and _ % 3 == 0:
            frames.append(_grab(rid, front_x, ledge_h))

    pos, orn = p.getBasePositionAndOrientation(rid)
    roll, pitch, _ = p.getEulerFromQuaternion(orn)
    paws = [p.getLinkState(rid, j)[0] for j in PAW]
    on_top = sum(1 for (px, py, pz) in paws
                 if pz > ledge_h - 0.015 and front_x - 0.02 < px < front_x + L)
    dx = pos[0] - x0
    flipped = abs(roll) > 1.4 or abs(pitch) > 1.4
    stand_h = ledge_h + 0.065
    if flipped:
        score = -80.0 + 20 * min(1.0, max(0.0, dx / 0.15))
    else:
        score = (42 * min(1.5, max(0.0, dx / 0.16))                 # progress onto/over
                 + 28 * (1 - min(1.0, abs(pos[2] - stand_h) / 0.09))  # correct on-top height
                 + 22 * (on_top / 4.0)                                # feet on the block
                 - 22 * min(1.0, (abs(roll) + abs(pitch)) / 1.4))     # not tilted
    env.close()

    print(f"  ledge {ledge_h*100:.0f}cm | phases (dx,z,pitch): "
          + " ".join(f"P{ph}({dxp:+.2f},{zp:.2f},{pit:+.0f})" for ph, dxp, zp, pit in phase_log))
    print(f"  END dx {dx:+.3f} m  bodyZ {pos[2]:.3f} (want ~{stand_h:.3f})  "
          f"roll/pitch {np.degrees(roll):+.0f}/{np.degrees(pitch):+.0f}  feet-on-top {on_top}/4  "
          f"{'FLIPPED ' if flipped else ''}=> SCORE {score:.1f}")
    if gif and frames:
        _write_gif(frames, gif, pr, ledge_h, score)
    return score


def _grab(rid, front_x, h):
    pos = p.getBasePositionAndOrientation(rid)[0]
    _, _, rgb, _, _ = p.getCameraImage(
        420, 300,
        viewMatrix=p.computeViewMatrix(
            [pos[0] - 0.05, 0.62, 0.10 + h], [pos[0], 0.0, 0.04 + h], [0, 0, 1]),
        projectionMatrix=p.computeProjectionMatrixFOV(46, 420 / 300, 0.1, 6),
        renderer=p.ER_TINY_RENDERER)
    im = np.reshape(rgb, (300, 420, 4))[:, :, :3].astype(np.uint8)
    im[(im > 243).all(axis=2)] = (120, 131, 148)
    return im


def _write_gif(frames, path, pr, h, score):
    from PIL import Image, ImageDraw
    imgs = []
    for f in frames:
        im = Image.fromarray(f)
        d = ImageDraw.Draw(im)
        d.rectangle([0, 0, im.width, 16], fill=(20, 20, 24))
        d.text((5, 3), f"ledge {h*100:.0f}cm  f-up {pr['f_up_sh']:.0f}/{pr['f_up_kn']:.0f}  "
                       f"pull {pr['pull_sh']:.0f}/{pr['pull_hip']:.0f}  score {score:.0f}",
               fill=(235, 235, 235))
        imgs.append(im)
    imgs[0].save(path, save_all=True, append_images=imgs[1:], duration=70, loop=0, disposal=2)
    print(f"  wrote {path} ({len(imgs)} frames)")


DEFAULTS = dict(
    f_up_sh=40, f_up_kn=34,          # phase 1: front feet up toward the ledge face
    f_plant_sh=10, f_plant_kn=30,    # phase 2: front feet forward + down onto the top
    pull_sh=34, pull_hip=16, pull_kn=10,   # phase 3: front legs pull, rear legs push
    boost_fkn=18, boost_rkn=26,      # phase 4: extra front / rear knee EXTENSION (lever the body up, no lift)
    r_up_hip=42, r_up_kn=36,         # (unused now -- kept for CLI compat)
    r_plant_hip=12, r_plant_kn=30,   # phase 5: rear feet shuffle onto the top
    ticks=[26, 30, 40, 30, 34, 30],
)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ledge", type=float, default=0.035)
    ap.add_argument("--render", action="store_true")
    ap.add_argument("--gif", default=None)
    for key, val in DEFAULTS.items():
        if key == "ticks":
            ap.add_argument("--ticks", default=",".join(map(str, val)))
        else:
            ap.add_argument(f"--{key.replace('_', '-')}", type=float, default=val)
    a = ap.parse_args()
    pr = {k: getattr(a, k) for k in DEFAULTS if k != "ticks"}
    pr["ticks"] = [int(x) for x in a.ticks.split(",")]
    print(f"params: {pr}")
    run(pr, a.ledge, render=a.render, gif=a.gif)


if __name__ == "__main__":
    main()
