"""Skill parade -- a visual showreel of every Phase E scripted skill on the
frozen `run20m_ppo` walk, on flat ground, so you can watch each one play out.

This is the REUSABLE skill demo, not a one-off. It FORCES each `GaitMode` in
sequence (unlike `eval_skill_switch.py`, which triggers skills from terrain and
reports A/B stats). Each skill gets:
  * a full-screen TITLE CARD in that skill's colour (name + one-line what/why),
  * a brief STAND still so motions don't blur into each other,
  * the skill itself, wrapped in a thick border of the skill's colour that
    FLASHES on entry -- so you can read the skill at a glance from the colour,
    not the text. A progress strip along the bottom shows which of N you're on.

    python demo_skills.py --render                 # watch it live in the GUI
    python demo_skills.py --gif demo_skills.gif    # just write the GIF
    python demo_skills.py --render --gif out.gif   # both

ADDING A NEW SKILL: add one dict to SKILLS below (mode, ticks, name, colour,
desc). The keyframe refs come from `eval_skill_switch.make_switch()` (shared with
the eval harness), so a new `SkillRefs` field / `GaitMode` wired there shows up
here automatically -- the SKILLS entry is the only edit.
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
from eval_skill_switch import make_switch, rl_joint_deg               # noqa: E402

# one dict per skill. `col` is the skill's identity colour (border + title card +
# progress pip). `ticks` is sim steps for the skill itself (title card + stand
# are added around it).
SKILLS = [
    dict(mode=GaitMode.CRUISE,   ticks=90,  name="CRUISE",   col=(70, 132, 200),
         desc="the learned run20m_ppo walk drives"),
    dict(mode=GaitMode.CAREFUL,  ticks=80,  name="CAREFUL",  col=(38, 176, 168),
         desc="obstacle mid-distance -- RL still drives, speed x0.6"),
    dict(mode=GaitMode.STEP_OVER, ticks=140, name="STEP OVER", col=(83, 176, 74),
         desc="low obstacle -- scripted trot keyframe, blended in and out"),
    dict(mode=GaitMode.INSPECT,  ticks=110, name="INSPECT",  col=(140, 104, 214),
         desc="close & can't classify -- crouch, camera mast pitches down"),
    dict(mode=GaitMode.BRACE,    ticks=90,  name="BRACE",    col=(226, 146, 44),
         desc="impact imminent -- planted crouch, knees flexed, take the bump"),
    dict(mode=GaitMode.BACK_OUT, ticks=140, name="BACK OUT", col=(214, 100, 58),
         desc="stalled -- walk backward one cycle, then re-approach"),
    dict(mode=GaitMode.HALT,     ticks=110, name="HALT",     col=(196, 62, 62),
         desc="wall ahead -- hold neutral stance (nav / turn layer takes over)"),
    dict(mode=GaitMode.CRUISE,   ticks=80,  name="RELEASE",  col=(70, 132, 200),
         desc="hand back to the walk"),
]

WALK_CMD = 0.065        # gentle -- keeps the robot near origin so the cam stays on floor
STAND_TICKS = 30        # brief stand still before each skill
CARD_FRAMES = 11        # held frames of the title card
FLASH_FRAMES = 7        # captured skill frames the entry flash lasts
FRAME_MS = 105          # per-frame GIF duration
CARD_MS = 150


# --------------------------------------------------------------------- render
def _grab(env, w, h):
    """Chase cam pitched well down so flat ground fills the frame; grab tall and
    crop the thin sky band off the top."""
    pos = p.getBasePositionAndOrientation(env.robot_id)[0]
    gh = h + 70
    _, _, rgb, _, _ = p.getCameraImage(
        w, gh,
        viewMatrix=p.computeViewMatrixFromYawPitchRoll(
            cameraTargetPosition=[pos[0], pos[1], 0.05], distance=0.70,
            yaw=52, pitch=-50, roll=0, upAxisIndex=2),
        projectionMatrix=p.computeProjectionMatrixFOV(52, w / gh, 0.1, 6),
        renderer=p.ER_TINY_RENDERER)
    return np.reshape(rgb, (gh, w, 4))[70:, :, :3].astype(np.uint8)


_FONT_CACHE = {}


def _font(size):
    if size in _FONT_CACHE:
        return _FONT_CACHE[size]
    from PIL import ImageFont
    for pth in ("/System/Library/Fonts/Supplemental/Arial Bold.ttf",
                "/System/Library/Fonts/Helvetica.ttc",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"):
        try:
            f = ImageFont.truetype(pth, size)
            _FONT_CACHE[size] = f
            return f
        except Exception:
            pass
    try:
        import matplotlib
        f = ImageFont.truetype(os.path.join(
            os.path.dirname(matplotlib.__file__),
            "mpl-data/fonts/ttf/DejaVuSans-Bold.ttf"), size)
    except Exception:
        f = ImageFont.load_default(size)
    _FONT_CACHE[size] = f
    return f


def _pips(d, w, h, idx, n, cur_col):
    """progress strip: n dots along the bottom, filled up to idx, current bigger."""
    gap, r = 16, 4
    x0 = w // 2 - (n - 1) * gap // 2
    y = h - 12
    for i in range(n):
        cx = x0 + i * gap
        col = SKILLS[i]["col"] if i <= idx else (110, 114, 120)
        rr = r + 2 if i == idx else r
        d.ellipse([cx - rr, y - rr, cx + rr, y + rr], fill=col,
                  outline=(255, 255, 255) if i == idx else None,
                  width=2 if i == idx else 0)


def _centre(d, text, font, y, w, fill):
    bb = d.textbbox((0, 0), text, font=font)
    d.text(((w - (bb[2] - bb[0])) // 2, y), text, font=font, fill=fill)


def _title_card(sk, w, h, idx, n):
    from PIL import Image, ImageDraw
    r, g, b = sk["col"]
    bg = (int(r * 0.30) + 12, int(g * 0.30) + 12, int(b * 0.30) + 14)
    im = Image.new("RGB", (w, h), bg)
    d = ImageDraw.Draw(im)
    d.rectangle([0, 0, w, 8], fill=sk["col"])
    d.rectangle([0, h - 8, w, h], fill=sk["col"])
    _centre(d, f"SKILL {idx + 1} / {n}", _font(15), int(h * 0.24), w, (200, 204, 210))
    _centre(d, sk["name"], _font(46), int(h * 0.34), w, (245, 246, 248))
    _centre(d, sk["desc"], _font(15), int(h * 0.60), w, (206, 210, 216))
    _pips(d, w, h, idx, n, sk["col"])
    return im


def _decorate(frame, sk, idx, n, src, k_in_skill):
    """thick skill-colour border (flashing on entry) + name plate + pips."""
    from PIL import Image, ImageDraw
    im = Image.fromarray(frame)
    # entry flash: a colour wash that fades over the first few skill frames
    if k_in_skill < 6:
        a = 0.34 * (1.0 - k_in_skill / 6.0)
        im = Image.blend(im, Image.new("RGB", im.size, sk["col"]), a)
    d = ImageDraw.Draw(im)
    w, h = im.size
    bw = 7 + max(0, FLASH_FRAMES - k_in_skill)          # fat border, thins as flash ends
    for i in range(bw):
        d.rectangle([i, i, w - 1 - i, h - 1 - i], outline=sk["col"])
    # name plate, top-left
    plate_w = max(120, 14 + int(d.textlength(sk["name"], font=_font(24))))
    d.rectangle([bw, bw, bw + plate_w, bw + 30], fill=(18, 19, 23))
    d.text((bw + 8, bw + 3), sk["name"], font=_font(24), fill=sk["col"])
    _dot = {"rl": (90, 170, 240), "blend": (240, 200, 90), "scripted": (240, 120, 90)}
    d.ellipse([bw + 8, bw + 34, bw + 16, bw + 42], fill=_dot.get(src, (200, 200, 200)))
    d.text((bw + 22, bw + 32), src.upper(), font=_font(12), fill=(220, 222, 226))
    _pips(d, w, h, idx, n, sk["col"])
    return im


# --------------------------------------------------------------------- run
def run(render=False, gif=None, stride=4, w=470, h=310, model_path="trained/run20m_ppo"):
    opencat_gym_env.GUI_MODE = render
    opencat_gym_env.DR_EVAL_FULL = False
    env = OpenCatGymEnv()
    model = PPO.load(model_path, device="cpu")
    switch = make_switch()

    obs, _ = env.reset()
    switch.reset()
    # floor slab under the sim's finite ground plane so the chase cam never sees
    # past its edge (needs a collision shape or TINY_RENDERER skips it; below z=0
    # so physics is unchanged)
    _vs = p.createVisualShape(p.GEOM_BOX, halfExtents=[25, 25, 0.01],
                              rgbaColor=[0.30, 0.33, 0.40, 1.0])
    _cs = p.createCollisionShape(p.GEOM_BOX, halfExtents=[25, 25, 0.01])
    p.createMultiBody(baseMass=0, baseCollisionShapeIndex=_cs,
                      baseVisualShapeIndex=_vs, basePosition=[0, 0, -0.03])

    imgs, durs = [], []
    n = len(SKILLS)

    def _sim(mode, ticks, cmd, sk, idx, k0):
        """step the env `ticks` times at forward speed `cmd`; capture every
        `stride`th frame decorated for skill `sk`. returns frames captured."""
        nonlocal obs
        k = k0
        for _ in range(ticks):
            env._cmd_fwd = cmd
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
            if gif and k % stride == 0:
                imgs.append(_decorate(_grab(env, w, h), sk, idx, n, src.value,
                                      (k - k0) // stride))
                durs.append(FRAME_MS)
            k += 1
            if term or trunc:                       # stumble on flat ground -- reset, carry on
                obs, _ = env.reset()
                switch.reset()
        return k

    for idx, sk in enumerate(SKILLS):
        # recenter over the origin so every skill plays in the same spot on floor
        (_, _, bz), born = p.getBasePositionAndOrientation(env.robot_id)
        p.resetBasePositionAndOrientation(env.robot_id, [0.0, 0.0, bz], born)
        p.resetBaseVelocity(env.robot_id, [0, 0, 0], [0, 0, 0])
        if gif:
            card = _title_card(sk, w, h, idx, n)
            imgs += [card] * CARD_FRAMES
            durs += [CARD_MS] * CARD_FRAMES
        k = _sim(GaitMode.CRUISE, STAND_TICKS, 0.0, sk, idx, 0)     # stand still
        _sim(sk["mode"], sk["ticks"], WALK_CMD, sk, idx, k)         # the skill
    env.close()
    print(f"parade done: {len(SKILLS)} skills")
    if gif and imgs:
        imgs[0].save(gif, save_all=True, append_images=imgs[1:],
                     duration=durs, loop=0, optimize=True)
        print(f"wrote {gif}  ({len(imgs)} frames)")


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
