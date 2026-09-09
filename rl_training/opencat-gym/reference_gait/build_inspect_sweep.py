"""Author `inspect_sweep_ref.npy` -- INSPECT's up-and-down camera scan.

The body-mounted camera reads the near obstacle by pitching the whole body. A
single held bow (`buttUp_ref`) points it at the ground; a *sweep* passes the view
from nose-UP (top of the obstacle) down to nose-DOWN (near ground) so the detector
gets the whole vertical profile in one pass.

  stance -> NOSE-UP pose (scan high) -> level -> BOW (buttUp, scan low) -> hold bow

The nose-up pose is searched empirically (the URDF can't horse-rear -- a modest
~10-15 deg is the ceiling, which is enough for a scan). Output: (N, 8) rad, URDF
order, same format as the other refs. INSPECT plays it once over
`SkillSwitchConfig.inspect_sweep_ticks` then holds the last (bow) frame.
"""
import pathlib
import numpy as np

HERE = pathlib.Path(__file__).parent
STANCE = np.load(HERE / "wkf_ref.npy").mean(0)              # (8,) rad, URDF order
BOW = np.load(HERE / "buttUp_ref.npy")[0]                   # Petoi play-bow, ~+22 deg nose-down
FRONT_SH, FRONT_KN, REAR_HIP, REAR_KN = [0, 2], [1, 3], [4, 6], [5, 7]


def _search_nose_up():
    import os
    for k, v in {"G2E_OBSTACLE_COUNT": "0", "G2E_RANDOM_TERRAIN_PROB": "0",
                 "G2E_SLOPE_MAX_DEG": "0", "G2E_CLIFF_PROB": "0"}.items():
        os.environ.setdefault(k, v)
    import pybullet as p
    import opencat_gym_env
    from opencat_gym_env import OpenCatGymEnv
    opencat_gym_env.GUI_MODE = False
    REV = [1, 2, 4, 5, 7, 8, 10, 11]
    env = OpenCatGymEnv()
    st_deg = np.rad2deg(STANCE)
    best = (-1e9, None)
    for fsh in (-30, -18, -6, 6):        # front shoulders fwd -> plant front feet, push front up
        for fkn in (10, 24, 38):         # + front knees extend
            for rh in (10, 22, 34):      # rear hips fold -> drop the rear
                for rk in (-30, -16, -4):  # + rear knees fold
                    q = st_deg.copy()
                    for i in FRONT_SH: q[i] += fsh
                    for i in FRONT_KN: q[i] += fkn
                    for i in REAR_HIP: q[i] += rh
                    for i in REAR_KN: q[i] += rk
                    env.reset()
                    for _ in range(90):
                        p.setJointMotorControlArray(env.robot_id, REV, p.POSITION_CONTROL,
                                                    targetPositions=np.deg2rad(q).tolist(), forces=[2.0] * 8)
                        p.stepSimulation()
                    (_, _, z), orn = p.getBasePositionAndOrientation(env.robot_id)
                    roll, pit, _ = p.getEulerFromQuaternion(orn)
                    # nose-up wanted: pitch < 0 in this URDF (>0 = nose down). stable = upright, not collapsed.
                    if abs(roll) < 0.35 and z > 0.05 and -np.degrees(pit) > best[0]:
                        best = (-np.degrees(pit), np.deg2rad(q))
    env.close()
    return best


def main():
    up_pitch, up_pose = _search_nose_up()
    if up_pose is None:
        up_pose = STANCE.copy()
        up_pitch = 0.0
    print(f"nose-up pose: {up_pitch:+.0f} deg nose-up  {np.rad2deg(up_pose).round(0)}")

    # sweep waypoints and how many frames to spend easing to each
    legs = [(STANCE, 1), (up_pose, 10), (STANCE, 6), (BOW, 12), (BOW, 8)]
    out = [legs[0][0]]
    for (a, _), (b, n) in zip(legs[:-1], legs[1:]):
        for t in range(1, n + 1):
            w = 0.5 - 0.5 * np.cos(np.pi * t / n)
            out.append(a * (1 - w) + b * w)
    ref = np.array(out)
    np.save(HERE / "inspect_sweep_ref.npy", ref)
    print(f"wrote inspect_sweep_ref.npy  {ref.shape}  (radians, URDF order)")


if __name__ == "__main__":
    main()
