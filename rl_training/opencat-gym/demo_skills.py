"""Skill parade -- a visual showreel of every Phase E scripted skill on the
frozen `run20m_ppo` walk, on flat ground, so you can watch each one play out.

This is the REUSABLE skill demo, not a one-off. It FORCES each `GaitMode` in
sequence (unlike `eval_skill_switch.py`, which triggers skills from terrain and
reports A/B stats). Each skill gets:
  * a full-screen TITLE CARD in that skill's colour (name + one-line what/why),
  * a brief STAND still so motions don't blur into each other,
  * the skill itself, wrapped in a steady thick border of the skill's colour --
    read the skill at a glance from the colour, not the text. Nothing flashes or
    teleports. A progress strip along the bottom shows which of N you're on.

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
         desc="the learned run20m_ppo walk at top speed (0.15 m/s)"),
    dict(mode=GaitMode.CAREFUL,  ticks=80,  name="CAREFUL",  col=(38, 176, 168),
         desc="obstacle mid-distance -- same walk, speed x0.6 (0.09 m/s)"),
    dict(mode=GaitMode.STEP_OVER, ticks=160, name="STEP OVER", col=(83, 176, 74),
         cycles=5.0,
         desc="low obstacle -- scripted TROT keyframe (this is what's wired), blended in and out"),
    dict(mode=GaitMode.STEP_OVER, ticks=160, name="HIGH-STEP", col=(120, 196, 96),
         ref="highstep_ref.npy", cycles=5.0,
         desc="the authored higher-lift keyframe -- more foot clearance, but it LOST the A/B to trot"),
    dict(mode=GaitMode.INSPECT,  ticks=110, name="INSPECT",  col=(140, 104, 214),
         desc="close & can't classify -- crouch, camera mast pitches down"),
    dict(mode=GaitMode.BRACE,    ticks=90,  name="BRACE",    col=(226, 146, 44),
         desc="impact imminent -- planted crouch, knees flexed, take the bump"),
    dict(mode=GaitMode.BACK_OUT, ticks=140, name="BACK OUT", col=(214, 100, 58),
         desc="stalled -- walk backward one cycle, then re-approach"),
    dict(mode=GaitMode.HALT,     ticks=110, name="HALT",     col=(196, 62, 62),
         desc="wall ahead -- hold neutral stance (nav / turn layer takes over)"),
]

WALK_CMD = 0.15         # the policy's top forward speed on flat ground (CMD_FWD_MAX).
                        # CAREFUL runs this x0.6, so the two are a real speed contrast.
SKILL_LEN_SCALE = 3.0   # multiplies every SKILLS `ticks` -- bump for longer demos

# these auto-release after ~one play, so a HELD command re-triggers them over and
# over (looks like the animation stutters back and forth). In the demo, play them
# ONCE cleanly, then stand for the rest of the segment.
_ONE_SHOT = {GaitMode.STEP_OVER, GaitMode.BACK_OUT, GaitMode.BRACE}
STAND_TICKS = 32        # brief stand still before each skill
CARD_FRAMES = 16        # held frames of the title card (~1.5 s at FRAME_MS)
FRAME_MS = 95           # uniform per-frame GIF duration


# --------------------------------------------------------------------- render
_SKY = np.array([120, 131, 148], np.uint8)     # replaces the renderer's blown-out white


def _grab(env, w, h, cam="side"):
    """`side` (default): a low lateral profile so foot lift / body pitch / bob
    read. `chase`: steep top-down, flat ground fills the frame. Near-white pixels
    (sky / the finite-plane void) are recoloured to a muted slate so nothing
    reads as a blown-out gap."""
    pos, orn = p.getBasePositionAndOrientation(env.robot_id)
    pos = np.array(pos)
    ryaw = p.getEulerFromQuaternion(orn)[2]      # follow HEADING only -- not the
    c, s = np.cos(ryaw), np.sin(ryaw)            # gait's roll/pitch (would wobble the cam)
    if cam == "chase":
        ox, oy, oz, look_dz, fov = -0.45, -0.30, 0.32, 0.02, 52
    else:                                        # straight low broadside profile
        ox, oy, oz, look_dz, fov = 0.0, 0.68, 0.12, 0.05, 46
    eye = pos + np.array([c * ox - s * oy, s * ox + c * oy, oz])
    target = pos + np.array([0.0, 0.0, look_dz])
    _, _, rgb, _, _ = p.getCameraImage(
        w, h,
        viewMatrix=p.computeViewMatrix(eye.tolist(), target.tolist(), [0, 0, 1]),
        projectionMatrix=p.computeProjectionMatrixFOV(fov, w / h, 0.1, 6),
        renderer=p.ER_TINY_RENDERER)
    img = np.reshape(rgb, (h, w, 4))[:, :, :3].astype(np.uint8)
    img[(img > 243).all(axis=2)] = _SKY      # kill blown-out sky / plane-edge void
    return img


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


BORDER_W = 8              # steady skill-colour border thickness


def _title_card(sk, w, h, idx, n):
    from PIL import Image, ImageDraw
    r, g, b = sk["col"]
    bg = (int(r * 0.42) + 26, int(g * 0.42) + 26, int(b * 0.42) + 28)   # muted skill hue
    im = Image.new("RGB", (w, h), bg)
    d = ImageDraw.Draw(im)
    d.rectangle([0, 0, w, 10], fill=sk["col"])
    d.rectangle([0, h - 10, w, h], fill=sk["col"])
    _centre(d, f"SKILL {idx + 1} / {n}", _font(15), int(h * 0.24), w, (225, 228, 232))
    _centre(d, sk["name"], _font(46), int(h * 0.34), w, (250, 250, 251))
    _centre(d, sk["desc"], _font(15), int(h * 0.60), w, (228, 231, 235))
    _pips(d, w, h, idx, n, sk["col"])
    return im


def _decorate(frame, sk, idx, n, src, k_in_skill):
    """steady skill-colour border + name plate + progress pips. No animation --
    the colour alone reads the skill; nothing flashes."""
    from PIL import Image, ImageDraw
    im = Image.fromarray(frame)
    d = ImageDraw.Draw(im)
    w, h = im.size
    for i in range(BORDER_W):
        d.rectangle([i, i, w - 1 - i, h - 1 - i], outline=sk["col"])
    b = BORDER_W
    plate_w = max(120, 14 + int(d.textlength(sk["name"], font=_font(24))))
    d.rectangle([b, b, b + plate_w, b + 30], fill=(18, 19, 23))
    d.text((b + 8, b + 3), sk["name"], font=_font(24), fill=sk["col"])
    _dot = {"rl": (90, 170, 240), "blend": (240, 200, 90), "scripted": (240, 120, 90)}
    d.rectangle([b, b + 30, b + 120, b + 48], fill=(18, 19, 23))
    d.ellipse([b + 8, b + 35, b + 16, b + 43], fill=_dot.get(src, (200, 200, 200)))
    d.text((b + 22, b + 33), src.upper(), font=_font(12), fill=(224, 226, 230))
    _pips(d, w, h, idx, n, sk["col"])
    return im


# --------------------------------------------------------------------- run
def run(render=False, gif=None, stride=4, w=470, h=310, model_path="trained/run20m_ppo",
        step_over_ref="tr_ref.npy"):
    opencat_gym_env.GUI_MODE = render
    opencat_gym_env.DR_EVAL_FULL = False
    env = OpenCatGymEnv()
    model = PPO.load(model_path, device="cpu")

    # one SkillSwitch per distinct STEP_OVER keyframe used in SKILLS (default +
    # any `ref` override), built lazily and cached
    _sw_cache = {}

    def _get_switch(ref):
        key = ref or step_over_ref
        if key not in _sw_cache:
            _sw_cache[key] = make_switch(step_over_ref=key)
        return _sw_cache[key]

    obs, _ = env.reset()
    # floor slab under the sim's finite ground plane so the chase cam never sees
    # past its edge (needs a collision shape or TINY_RENDERER skips it; below z=0
    # so physics is unchanged)
    _vs = p.createVisualShape(p.GEOM_BOX, halfExtents=[25, 25, 0.01],
                              rgbaColor=[0.30, 0.33, 0.40, 1.0])
    _cs = p.createCollisionShape(p.GEOM_BOX, halfExtents=[25, 25, 0.01])
    p.createMultiBody(baseMass=0, baseCollisionShapeIndex=_cs,
                      baseVisualShapeIndex=_vs, basePosition=[0, 0, -0.03])

    imgs = []
    n = len(SKILLS)

    def _sim(sw, mode, ticks, cmd, sk, idx, k0, stop_when_released=False):
        """step the env up to `ticks` times at forward speed `cmd`, driving
        SkillSwitch `sw`; capture every `stride`th frame decorated for skill `sk`.
        `stop_when_released`: return early once the switch has played one skill and
        handed back to the walk (so one-shot skills show a single clean rep)."""
        nonlocal obs
        k = k0
        seen_active = False
        for _ in range(ticks):
            env._cmd_fwd = cmd
            env._look_down = sw.active_skill is GaitMode.INSPECT
            action, _ = model.predict(obs, deterministic=True)
            gp = (env._phase / TIME_PHASE_PERIOD) % 1.0
            joints, src = sw.update(mode, rl_joint_deg(env, action), gait_phase=gp)
            env._cmd_fwd = cmd * sw.speed_scale     # CAREFUL -> 0.6x, visibly slower than CRUISE
            if src is Source.RL:
                obs, _, term, trunc, _ = env.step(action)
            else:
                env._abs_joint_override = joints
                obs, _, term, trunc, _ = env.step(np.zeros(8, dtype=np.float32))
                env._abs_joint_override = None
            if gif and k % stride == 0:
                imgs.append(_decorate(_grab(env, w, h, sk.get("cam", "side")),
                                      sk, idx, n, src.value, (k - k0) // stride))
            k += 1
            if term or trunc:
                # a stumble on flat ground -- reset the env so the next segment is
                # usable, but STOP this one (re-forcing the mode would re-trigger
                # the skill and read as a rewind / double-crouch)
                obs, _ = env.reset()
                sw.reset()
                break
            seen_active = seen_active or sw.active_skill is not None
            if stop_when_released and seen_active and sw.active_skill is None:
                break
        return k

    for idx, sk in enumerate(SKILLS):
        sw = _get_switch(sk.get("ref"))
        sw.reset()
        # everything plays at normal speed. `cycles` just makes a one-shot
        # keyframe skill LOOP more times in a single continuous play (longer on
        # screen, no stutter) before it hands back. Base = 1.0 (one loop).
        sw._cfg.step_over_cycles = sk.get("cycles", 1.0)
        # recenter over the origin so every skill plays in the same spot on floor.
        # This is the ONLY teleport, and it lands on a non-captured frame (behind
        # the title card) so it's never visible.
        (_, _, bz), born = p.getBasePositionAndOrientation(env.robot_id)
        p.resetBasePositionAndOrientation(env.robot_id, [0.0, 0.0, bz], born)
        p.resetBaseVelocity(env.robot_id, [0, 0, 0], [0, 0, 0])
        if gif:
            card = _title_card(sk, w, h, idx, n)
            imgs += [card] * CARD_FRAMES
        k = _sim(sw, GaitMode.CRUISE, STAND_TICKS, 0.0, sk, idx, 0)     # stand still
        total = int(sk["ticks"] * SKILL_LEN_SCALE)
        if sk["mode"] in _ONE_SHOT:
            # ONE clean rep (a held command would re-trigger it into a stutter),
            # then a short stand tail. These motions are quick -- they don't need
            # the full tripled length the held / continuous skills use.
            k2 = _sim(sw, sk["mode"], total, WALK_CMD, sk, idx, k, stop_when_released=True)
            _sim(sw, GaitMode.CRUISE, STAND_TICKS + STAND_TICKS, 0.0, sk, idx, k2)
        else:
            _sim(sw, sk["mode"], total, WALK_CMD, sk, idx, k)
    env.close()
    print(f"parade done: {len(SKILLS)} skills")
    if gif and imgs:
        imgs[0].save(gif, save_all=True, append_images=imgs[1:],
                     duration=FRAME_MS, loop=0, optimize=True, disposal=2)
        print(f"wrote {gif}  ({len(imgs)} frames, {FRAME_MS} ms/frame)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--render", action="store_true", help="watch live in the PyBullet GUI")
    ap.add_argument("--gif", default=None, help="write a labelled GIF here")
    ap.add_argument("--gif-stride", type=int, default=4)
    ap.add_argument("--gif-w", type=int, default=470)
    ap.add_argument("--gif-h", type=int, default=310)
    ap.add_argument("--model", default="trained/run20m_ppo")
    ap.add_argument("--step-over-ref", default="tr_ref.npy",
                    help="keyframe for the main STEP OVER segment "
                         "(tr_ref.npy | highstep_ref.npy). The HIGH-STEP segment "
                         "always shows highstep_ref.npy.")
    a = ap.parse_args()
    run(render=a.render, gif=a.gif, stride=a.gif_stride, w=a.gif_w, h=a.gif_h,
        model_path=a.model, step_over_ref=a.step_over_ref)
