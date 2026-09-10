"""H9 — replay the firmware get-up keyframes (`rc`, `rl`) in PyBullet and watch.

The hardware-gated-training backlog (H9) asks for this before the robot arrives:
does OpenCat's scripted self-right *plausibly* work in sim, or will it need
re-authoring in Skill Composer on the real robot?

  rc  — "recover" — the firmware self-right for a SIDE or FRONT fall.
  rl  — "roll"    — flips a SUPINE (on-its-back) robot onto its side; the
                    firmware then chains `rc`. So supine here = rl -> rc.

Both are decoded from `InstinctBittleESP.h` as *behaviours* (5-6 keyframes,
resampled to 100) — `build_skill_reference.py rc rl`. That decode is
**approximate**: it drops the per-frame timing params, and the real skill waits
on an IMU trigger angle mid-sequence (`skill.h` `imuException` checks). It also
assumes real foot grip. So a poor sim result is expected and is itself the
finding — it tells us the hardware path can't just be "call `krc`".

    python verify_getup_reference.py                 # score all 4 fall types, headless
    python verify_getup_reference.py --gif           # + write getup_<case>.gif each
    python verify_getup_reference.py --sheet         # + a start/mid/end contact sheet
"""
from __future__ import annotations

import argparse
import pathlib

import numpy as np
import pybullet as p
import pybullet_data

HERE = pathlib.Path(__file__).parent
URDF = str(HERE.parent / "models" / "bittle_esp32.urdf")
RC = np.load(HERE / "rc_ref.npy")           # (100, 8) rad, URDF order
RL = np.load(HERE / "rl_ref.npy")
BOUND = np.deg2rad(115)                      # URDF leg-joint clamp
NEUTRAL = np.array([0.7, -1.0] * 4)          # mild stand — held while the fall settles
DROP_Z = 0.16                                # spawn height so the fall commits to its pose
SETTLE = 120                                 # steps to let the fallen pose settle
PLAY_CYCLES = 3                              # times through the keyframe trajectory
SUBSTEPS = 8
FORCE = 0.40                                 # N·m per joint — above verify_wkf's 0.2;
                                            # P1S alloy peak ~0.29, boosted like Run 6

# fall pose = base euler (roll, pitch, yaw) it's dropped in, and which skill(s)
# the firmware would run for it. NOTE: this URDF has no stable side-lie or
# nose-down rest — a mild tip flops back belly-down, anything past ~1.1 rad rolls
# fully supine (measured). So the two sim-reachable fall states are:
CASES = {
    "prone_flat": dict(euler=(0.85, 0.0, 0.0), skills=[RC],     note="collapsed belly-down (mild side tip → flat)"),
    "supine":     dict(euler=(3.14, 0.0, 0.0), skills=[RL, RC], note="flat on its back — rl then rc"),
}

CAM_W, CAM_H = 380, 285


def _revolute_joints(rid: int) -> list[int]:
    return [j for j in range(p.getNumJoints(rid))
            if p.getJointInfo(rid, j)[2] in (p.JOINT_PRISMATIC, p.JOINT_REVOLUTE)]


def _grab(rid: int) -> np.ndarray:
    pos, _ = p.getBasePositionAndOrientation(rid)
    vm = p.computeViewMatrixFromYawPitchRoll([pos[0], pos[1], 0.04], 0.6, 40, -22, 0, 2)
    pm = p.computeProjectionMatrixFOV(60, CAM_W / CAM_H, 0.1, 5)
    _, _, rgb, _, _ = p.getCameraImage(CAM_W, CAM_H, viewMatrix=vm, projectionMatrix=pm,
                                       renderer=p.ER_TINY_RENDERER)
    return np.reshape(rgb, (CAM_H, CAM_W, 4))[:, :, :3].astype(np.uint8)


def _uprightness(rid: int) -> tuple[float, float, float]:
    """returns (|roll|, |pitch|, base_z) — 'up' ≈ both angles < 0.5 rad and z > 0.04."""
    (_, _, z), orn = p.getBasePositionAndOrientation(rid)
    roll, pitch, _ = p.getEulerFromQuaternion(orn)
    return abs(roll), abs(pitch), z


def run_case(name: str, want_gif: bool, want_sheet: bool) -> dict:
    cfg = CASES[name]
    p.connect(p.DIRECT)
    p.setGravity(0, 0, -9.81)
    p.setAdditionalSearchPath(pybullet_data.getDataPath())
    p.loadURDF("plane.urdf")
    rid = p.loadURDF(URDF, [0, 0, DROP_Z],
                     p.getQuaternionFromEuler(list(cfg["euler"])),
                     flags=p.URDF_USE_SELF_COLLISION)
    jid = _revolute_joints(rid)
    for j in jid:
        p.changeDynamics(rid, j, maxJointVelocity=np.pi * 10)

    traj = np.concatenate([np.clip(s, -BOUND, BOUND) for s in cfg["skills"]], axis=0)

    # let the robot fall and settle in a normal stance, THEN run the skill
    for _ in range(SETTLE):
        p.setJointMotorControlArray(rid, jid, p.POSITION_CONTROL, NEUTRAL,
                                    forces=np.ones(len(jid)) * FORCE)
        p.stepSimulation()
    start = _uprightness(rid)
    frames = [_grab(rid)] if (want_gif or want_sheet) else []

    total = PLAY_CYCLES * len(traj)
    best_up = 1e9
    for t in range(total):
        tgt = traj[t % len(traj)]
        p.setJointMotorControlArray(rid, jid, p.POSITION_CONTROL, tgt,
                                    forces=np.ones(len(jid)) * FORCE)
        for _ in range(SUBSTEPS):
            p.stepSimulation()
        r, pi_, _ = _uprightness(rid)
        best_up = min(best_up, r + pi_)
        if frames is not None and want_gif and t % 3 == 0:
            frames.append(_grab(rid))
    end = _uprightness(rid)
    if (want_gif or want_sheet):
        frames.append(_grab(rid))

    p.disconnect()

    righted = end[0] < 0.5 and end[1] < 0.5 and end[2] > 0.04
    res = dict(case=name, note=cfg["note"],
               start_roll=start[0], start_pitch=start[1],
               end_roll=end[0], end_pitch=end[1], end_z=end[2],
               best_tilt_sum=best_up, righted=righted, frames=frames)
    return res


def _sheet(results: list[dict], path: pathlib.Path) -> None:
    from PIL import Image, ImageDraw
    rows = [r for r in results if r["frames"]]
    if not rows:
        return
    cols = 3  # start / mid / end
    cw, ch = CAM_W, CAM_H
    pad, top = 8, 22
    sheet = Image.new("RGB", (cols * cw + (cols + 1) * pad,
                              len(rows) * (ch + top) + pad), (24, 26, 30))
    d = ImageDraw.Draw(sheet)
    for i, r in enumerate(rows):
        fr = r["frames"]
        picks = [fr[0], fr[len(fr) // 2], fr[-1]]
        y = pad + i * (ch + top)
        d.text((pad, y + 4), f'{r["case"]}  ({r["note"]})  ->  '
               f'{"RIGHTED" if r["righted"] else "did not right"}  '
               f'end |roll|={r["end_roll"]:.2f} |pitch|={r["end_pitch"]:.2f}',
               fill=(230, 232, 236))
        for c, im in enumerate(picks):
            sheet.paste(Image.fromarray(im), (pad + c * (cw + pad), y + top))
    sheet.save(path)
    print(f"wrote {path}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gif", action="store_true", help="write getup_<case>.gif for each")
    ap.add_argument("--sheet", action="store_true", help="write getup_contact_sheet.png")
    a = ap.parse_args()

    print(f"{'case':<11} {'start r/p':>12} {'end r/p':>12} {'end z':>7} "
          f"{'min tilt-sum':>13}  verdict")
    results = []
    for name in CASES:
        r = run_case(name, a.gif, a.sheet)
        results.append(r)
        print(f"{r['case']:<11} "
              f"{r['start_roll']:>5.2f}/{r['start_pitch']:<5.2f} "
              f"{r['end_roll']:>5.2f}/{r['end_pitch']:<5.2f} "
              f"{r['end_z']:>7.3f} {r['best_tilt_sum']:>13.2f}  "
              f"{'RIGHTED' if r['righted'] else 'no'}")
        if a.gif and r["frames"]:
            from PIL import Image
            out = HERE / f"getup_{name}.gif"
            ims = [Image.fromarray(f) for f in r["frames"]]
            ims[0].save(out, save_all=True, append_images=ims[1:],
                        duration=90, loop=0, optimize=True)
            print(f"  wrote {out}")
    if a.sheet:
        _sheet(results, HERE / "getup_contact_sheet.png")

    n_ok = sum(r["righted"] for r in results)
    print(f"\n{n_ok}/{len(results)} fall types recovered in sim "
          f"(rc/rl are approximate keyframe decodes — see the module docstring)")


if __name__ == "__main__":
    main()
