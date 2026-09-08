"""Skill parade -- a visual showreel of every Phase E scripted skill on the
frozen `run20m_ppo` walk, on flat ground, so you can watch each one play out.

This is the REUSABLE skill demo, not a one-off. It FORCES each `GaitMode` in a
scripted timeline (unlike `eval_skill_switch.py`, which triggers skills from
terrain and reports A/B stats), with a smooth hand-back to the walk between each,
and writes a labelled GIF (top bar = control source + mode; lower band = what
you're looking at).

    python demo_skills.py --render                 # watch it live in the GUI
    python demo_skills.py --gif demo_skills.gif    # just write the GIF
    python demo_skills.py --render --gif out.gif   # both

ADDING A NEW SKILL: add its `GaitMode` value + one `(mode, ticks, caption)` line
to TIMELINE below. The keyframe refs come from `eval_skill_switch.make_switch()`
(shared with the eval harness), so a new `SkillRefs` field / `GaitMode` wired
there shows up here automatically -- the timeline line is the only edit.

Segments (each non-CRUISE one is preceded by a short CRUISE so the switch-in is
visible):
    CRUISE -> CAREFUL -> STEP_OVER -> INSPECT -> BRACE -> BACK_OUT -> HALT
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

# flat ground -- override the obstacle-course knobs eval_skill_switch sets by
# setdefault (ours win because we set them first)
for k, v in {
    "G2E_OBSTACLE_COUNT": "0", "G2E_RANDOM_TERRAIN_PROB": "0", "G2E_LEDGE_PROB": "0",
    "G2E_RUBBLE_PROB": "0", "G2E_SLOPE_MAX_DEG": "0", "G2E_CLIFF_PROB": "0",
    "G2E_RANDOM_TERRAIN": "0",
}.items():
    os.environ[k] = v

import numpy as np                                                    # noqa: E402

import opencat_gym_env                                                # noqa: E402
from opencat_gym_env import OpenCatGymEnv, TIME_PHASE_PERIOD          # noqa: E402
from stable_baselines3 import PPO                                     # noqa: E402
from pi_pipeline.gait.skill_switch import GaitMode, Source            # noqa: E402

import pybullet as p                                                  # noqa: E402
from eval_skill_switch import make_switch, rl_joint_deg, _SRC_DOT      # noqa: E402


def _grab(env, w, h):
    """Chase cam, pulled back a little and pitched down more than the eval's grab
    so flat ground fills the frame (less empty sky)."""
    pos = p.getBasePositionAndOrientation(env.robot_id)[0]
    grab_h = h + 70                          # grab tall, crop the sky band off the top
    _, _, rgb, _, _ = p.getCameraImage(
        w, grab_h,
        viewMatrix=p.computeViewMatrixFromYawPitchRoll(
            cameraTargetPosition=[pos[0], pos[1], 0.05], distance=0.70,
            yaw=52, pitch=-50, roll=0, upAxisIndex=2),
        projectionMatrix=p.computeProjectionMatrixFOV(52, w / grab_h, 0.1, 6),
        renderer=p.ER_TINY_RENDERER)
    return np.reshape(rgb, (grab_h, w, 4))[70:, :, :3].astype(np.uint8)

# (mode, ticks, caption). A short CRUISE is inserted before every non-CRUISE
# segment automatically.
TIMELINE = [
    (GaitMode.CRUISE,    80, "CRUISE -- the learned run20m_ppo walk drives"),
    (GaitMode.CAREFUL,   70, "CAREFUL -- obstacle mid-distance: RL still drives, speed x0.6"),
    (GaitMode.STEP_OVER, 120, "STEP_OVER -- low obstacle: scripted trot keyframe, via-stance blend"),
    (GaitMode.INSPECT,   95, "INSPECT -- close & can't classify: crouch, mast pitches down"),
    (GaitMode.BRACE,     70, "BRACE -- impact imminent: planted crouch, knees flexed, take the bump"),
    (GaitMode.BACK_OUT,  120, "BACK_OUT -- stalled: walk backward a cycle, then re-approach"),
    (GaitMode.HALT,      95, "HALT -- wall ahead: hold neutral stance (nav / turn layer takes over)"),
    (GaitMode.CRUISE,    70, "release -- back to the walk"),
]
_LINK_CRUISE = (GaitMode.CRUISE, 34, "hand back to the walk")

WALK_CMD = 0.065      # gentle -- keeps the robot near origin so the chase cam stays on floor


def _expand(timeline):
    out = [timeline[0]]
    for seg in timeline[1:]:
        if seg[0] is not GaitMode.CRUISE:
            out.append(_LINK_CRUISE)
        out.append(seg)
    return out


def run(render=False, gif=None, stride=4, w=470, h=310, model_path="trained/run20m_ppo"):
    opencat_gym_env.GUI_MODE = render
    opencat_gym_env.DR_EVAL_FULL = False
    env = OpenCatGymEnv()
    model = PPO.load(model_path, device="cpu")
    switch = make_switch()

    obs, _ = env.reset()
    switch.reset()
    # a big floor slab just under the sim's finite ground plane so the chase cam
    # never sees past its edge (no white void) as the robot walks / yaws. Needs a
    # collision shape or ER_TINY_RENDERER skips it; sits below z=0 so physics is
    # unchanged (the robot walks on the real plane).
    _vs = p.createVisualShape(p.GEOM_BOX, halfExtents=[25, 25, 0.01],
                              rgbaColor=[0.30, 0.33, 0.40, 1.0])
    _cs = p.createCollisionShape(p.GEOM_BOX, halfExtents=[25, 25, 0.01])
    p.createMultiBody(baseMass=0, baseCollisionShapeIndex=_cs,
                      baseVisualShapeIndex=_vs, basePosition=[0, 0, -0.03])
    frames, labels, caps = [], [], []
    tick = 0
    for mode, ticks, caption in _expand(TIMELINE):
        # recenter the base over the origin at each segment boundary (keep height +
        # orientation) so the chase cam stays on floor and every skill plays in the
        # same spot. The seam lands on the labelled transition -- unobtrusive.
        (bx, by, bz), born = p.getBasePositionAndOrientation(env.robot_id)
        p.resetBasePositionAndOrientation(env.robot_id, [0.0, 0.0, bz], born)
        p.resetBaseVelocity(env.robot_id, [0, 0, 0], [0, 0, 0])
        for _ in range(ticks):
            env._cmd_fwd = WALK_CMD          # BACK_OUT / held skills ignore this (scripted drives)
            env._look_down = switch.active_skill is GaitMode.INSPECT
            action, _ = model.predict(obs, deterministic=True)
            gp = (env._phase / TIME_PHASE_PERIOD) % 1.0
            joints, src = switch.update(mode, rl_joint_deg(env, action), gait_phase=gp)
            if src is Source.RL:
                obs, _, term, trunc, _ = env.step(action)
            else:
                env._abs_joint_override = joints
                obs, _, term, trunc, _ = env.step(np.zeros(8, dtype=np.float32))
                env._abs_joint_override = None
            if gif and tick % stride == 0:
                frames.append(_grab(env, w, h))
                labels.append((switch.active_skill.value if switch.active_skill else mode.value, src.value))
                caps.append(caption)
            tick += 1
            if term or trunc:               # a stumble on flat ground -- just reset and carry on
                obs, _ = env.reset()
                switch.reset()
    env.close()
    print(f"parade done: {tick} ticks")
    if gif and frames:
        _write_demo_gif(frames, labels, caps, gif, stride)


def _write_demo_gif(frames, labels, caps, path, stride):
    from PIL import Image, ImageDraw
    imgs = []
    for frame, (mode, src), cap in zip(frames, labels, caps):
        im = Image.fromarray(frame)
        d = ImageDraw.Draw(im)
        d.rectangle([0, 0, im.width, 18], fill=(20, 20, 24))
        d.ellipse([5, 5, 13, 13], fill=_SRC_DOT.get(src, (200, 200, 200)))
        d.text((18, 4), f"{src.upper():8s} {mode}", fill=(235, 235, 235))
        d.rectangle([0, im.height - 16, im.width, im.height], fill=(20, 20, 24))
        d.text((6, im.height - 13), cap[:78], fill=(210, 214, 220))
        imgs.append(im)
    imgs[0].save(path, save_all=True, append_images=imgs[1:],
                 duration=int(1000 * stride / 50), loop=0, optimize=True)
    print(f"wrote {path}  ({len(imgs)} frames)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--render", action="store_true", help="watch live in the PyBullet GUI")
    ap.add_argument("--gif", default=None, help="write a labelled GIF here")
    ap.add_argument("--gif-stride", type=int, default=4)
    ap.add_argument("--gif-w", type=int, default=470)
    ap.add_argument("--gif-h", type=int, default=310)
    ap.add_argument("--model", default="trained/run20m_ppo")
    a = ap.parse_args()
    run(render=a.render, gif=a.gif, stride=a.gif_stride, w=a.gif_w, h=a.gif_h,
        model_path=a.model)
